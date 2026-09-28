"""CLI do portal — é o que o cron do Railway executa.

A ingestão roda como processo curto, não como thread dentro da API: sobe,
trabalha, morre. Assim a API não carrega memória de carga nem cai junto com
uma ingestão que falhou.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timedelta, timezone

from . import agenda, bootstrap, repositorio as repo, seed_fontes
from .motor import download, ingestao, publicacao, verificacao
from .sinks import criar_sink

log = logging.getLogger("portal")


def janela_corrente(
    padrao: str, timezone_nome: str | None = None,
    referencia: datetime | None = None,
) -> str:
    """A janela que este agendamento pede, no fuso que ele declara.

    `referencia` é o momento em que o cron *deveria* ter disparado — não a
    hora em que o processo acordou. Os dois se separam porque o Railway
    acorda o serviço na frequência dele e `agendados` é que decide o que está
    vencido: acordado às 08:00 com um agendamento de 23:59 pendente da noite
    anterior, «hoje» pelo relógio pediria o pregão que ainda não fechou.

    O fuso importa pelo mesmo motivo: às 23:59 em São Paulo já é o dia
    seguinte em UTC, e a janela calculada em UTC pediria o pregão de amanhã.
    """
    agora = (referencia or datetime.now(timezone.utc)).astimezone(
        agenda.zona(timezone_nome)
    )
    if padrao == "ano_corrente":
        return str(agora.year)
    if padrao == "ano_anterior":
        return str(agora.year - 1)
    if padrao == "hoje":
        return agora.date().isoformat()
    if padrao == "dia_anterior":
        return (agora - timedelta(days=1)).date().isoformat()
    return padrao


def cmd_migrar(args) -> int:
    sink = criar_sink()
    novas = bootstrap.preparar(sink)
    print(f"migrações aplicadas: {novas or 'nenhuma (já estava em dia)'}")
    if args.seed:
        # Idempotente: configuração idêntica à vigente não cria versão nova.
        # É isto que torna seguro semear a cada boot do serviço.
        if seed_fontes.aplicar(sink, forcar=args.forcar_seed):
            print("configuração da CVM cadastrada")
        else:
            print("configuração da CVM já estava em dia")
    sink.fechar()
    return 0


def cmd_ingerir(args) -> int:
    sink = criar_sink()
    bootstrap.preparar(sink)
    try:
        if args.replay:
            res = ingestao.recomputar(sink, args.dataset, args.janela)
        else:
            res = ingestao.executar(
                sink, args.dataset, args.janela,
                trigger=args.trigger, baixar=download.baixar,
            )
    except ingestao.ErroIngestao as e:
        print(f"erro: {e}", file=sys.stderr)
        return 2
    finally:
        pass

    print(json.dumps({
        "execucao": res.execucao_id, "status": res.status,
        "capturas": res.capturas, "capturas_novas": res.capturas_novas,
        "linhas": res.linhas_silver, "delta": res.delta_linhas,
        "publicacao": res.publicacao,
        "violacoes": [v["nome"] for v in res.violacoes],
    }, ensure_ascii=False))
    sink.fechar()
    # Bloqueio não é falha de processo: o dado ficou fora de gold de propósito.
    return 0 if res.status in ("publicado", "bloqueada") else 1


def cmd_agendados(args) -> int:
    """Roda tudo que o agendamento manda — o comando que o cron chama."""
    sink = criar_sink()
    bootstrap.preparar(sink)
    saida, falhas = [], 0
    for ag in repo.listar_agendamentos(sink):
        if not ag["ativo"]:
            continue
        if args.chave and ag["chave"] != args.chave:
            continue
        # A janela sai da ocorrência devida, não do relógio: o Railway acorda
        # o processo na frequência dele, e um agendamento de 23:59 pendente
        # da noite anterior pediria, pelo relógio, o pregão de hoje.
        devida = agenda.ocorrencia_devida(ag["cron"], ag.get("timezone"))
        janela = janela_corrente(ag["janela_padrao"], ag.get("timezone"), devida)

        # O Railway acorda o processo; é aqui que se decide o que fazer.
        # Sem esta checagem um gatilho diário reingeriria tudo todo dia, e o
        # cron do painel viraria a única frequência do sistema.
        ultima = sink.um(
            "SELECT max(terminado_em) AS q FROM log_execucao "
            "WHERE dataset_chave = ? AND status = 'publicado'",
            (ag["dataset_chave"],),
        )
        vencido, motivo = agenda.esta_vencido(
            ag["cron"], (ultima or {}).get("q"), timezone_nome=ag.get("timezone")
        )
        if not vencido and not args.forcar:
            saida.append({"agendamento": ag["chave"], "janela": janela,
                          "status": "nao_vencido", "motivo": motivo})
            continue

        try:
            res = ingestao.executar(
                sink, ag["dataset_chave"], janela,
                trigger="cron", baixar=download.baixar,
            )
            saida.append({"agendamento": ag["chave"], "janela": janela,
                          "status": res.status, "linhas": res.linhas_silver})
        except Exception as e:  # noqa: BLE001 — um dataset ruim não para os outros
            falhas += 1
            saida.append({"agendamento": ag["chave"], "janela": janela,
                          "status": "falha", "erro": str(e)})
            log.error("agendamento %s falhou: %s", ag["chave"], e)
    _notificar_alertas(sink, saida, falhas)
    print(json.dumps(saida, ensure_ascii=False, indent=2))
    sink.fechar()
    return 1 if falhas else 0


def _notificar_alertas(sink, rodada: list[dict], falhas: int) -> None:
    """Empurra os alertas críticos para `PORTAL_WEBHOOK_ALERTAS`, se definida.

    Era o único furo do ciclo: falha ficava gravada e ninguém era avisado —
    a detecção dependia de alguém abrir o painel. O webhook é genérico (POST
    de JSON), então serve a qualquer receptor sem dependência nova nem custo:
    um bridge de Slack/Discord/Telegram, um `ntfy.sh`, um endpoint próprio.

    Nunca derruba a rodada: alarme que quebra o processo monitorado é pior
    que alarme nenhum.
    """
    import os
    import urllib.request

    url = os.getenv("PORTAL_WEBHOOK_ALERTAS")
    if not url:
        return
    try:
        from .motor import alertas as motor_alertas

        estado = motor_alertas.ativos(sink)
        if estado["resumo"]["situacao"] != "critico" and not falhas:
            return
        criticos = [a for a in estado["alertas"] if a["severidade"] == "critico"]
        corpo = json.dumps({
            "origem": "mydata",
            "situacao": estado["resumo"]["situacao"],
            "falhas_na_rodada": falhas,
            "text": "MyData: "
                    + (f"{len(criticos)} alerta(s) crítico(s). " if criticos else "")
                    + (f"{falhas} falha(s) nesta rodada de cron. " if falhas else "")
                    + "; ".join(a["titulo"] for a in criticos[:5]),
            "alertas": criticos[:10],
        }, ensure_ascii=False, default=str).encode()
        pedido = urllib.request.Request(
            url, data=corpo, headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(pedido, timeout=10)  # noqa: S310 — URL vem do operador, não de dado
        log.info("alertas notificados via webhook")
    except Exception as e:  # noqa: BLE001 — notificação nunca derruba a rodada
        log.warning("webhook de alertas falhou: %s", e)


def cmd_recomputar(args) -> int:
    """Refaz o derivado a partir do bronze — a rotina normal de correção."""
    sink = criar_sink()
    bootstrap.preparar(sink)
    antes = verificacao.impressao_digital(sink)
    if args.dataset:
        janelas = [args.janela] if args.janela else ingestao.janelas_capturadas(
            sink, args.dataset
        )
        resultados = [ingestao.recomputar(sink, args.dataset, j) for j in janelas]
    else:
        resultados = ingestao.recomputar_tudo(sink)
    depois = verificacao.impressao_digital(sink)
    print(json.dumps({
        "recomputadas": [
            {"dataset": r.dataset_chave, "janela": r.janela, "status": r.status,
             "linhas": r.linhas_silver}
            for r in resultados
        ],
        "antes": antes,
        "depois": depois,
        "reproduziu": antes == depois,
    }, ensure_ascii=False, indent=2))
    sink.fechar()
    return 0 if antes == depois or not antes else 3


def cmd_verificar(args) -> int:
    sink = criar_sink()
    print(json.dumps(verificacao.impressao_digital(sink), ensure_ascii=False, indent=2))
    sink.fechar()
    return 0


def cmd_chave(args) -> int:
    from .api import auth

    sink = criar_sink()
    # `fonte:b3` é o opt-in que libera os atributos de origem B3 para uma
    # chave restrita por classe — sem ele, a resposta vem amputada com 200
    # (auth.pode_ver_fonte). É consentimento explícito por causa da restrição
    # de redistribuição do ADR-18, não um detalhe de sintaxe.
    partes = [f"classe:{c}" for c in args.classe]
    partes += [f"fonte:{f}" for f in args.fonte]
    escopos = ",".join(partes) if partes else "leitura"
    emitida = auth.emitir(sink, args.consumidor, args.quota_minuto,
                          args.quota_dia, escopos=escopos)
    print(f"consumidor: {emitida.consumidor}")
    print(f"prefixo:    {emitida.prefixo}")
    print(f"escopos:    {escopos}")
    print(f"chave:      {emitida.chave_completa}")
    print("Guarde agora: só o hash fica no banco.")
    sink.fechar()
    return 0


def cmd_chaves(args) -> int:
    """Lista as chaves de API. Nunca o segredo — ele não está no banco.

    Só o hash é guardado, então esta listagem responde "quais existem", nunca
    "qual é". A consequência prática merece ser dita em voz alta: uma chave
    cujo segredo se perdeu não pode ser recuperada nem conferida — só revogada.

    A coluna de escopo separa AMPLA de restrita porque a diferença decide o que
    a chave enxerga: `leitura` recebe os atributos de origem B3, uma chave
    restrita por classe não (ver `auth.pode_ver_fonte`), e a resposta vem
    amputada com status 200.
    """
    sink = criar_sink()
    try:
        onde, params = ["1=1"], []
        if args.consumidor:
            onde.append("consumidor = ?")
            params.append(args.consumidor)
        if not args.todas:
            onde.append("revogada_em IS NULL")

        linhas = sink.consultar(
            f"SELECT prefixo, consumidor, escopos, quota_minuto, quota_dia, "
            f"criada_em, revogada_em FROM cfg_chave_api "
            f"WHERE {' AND '.join(onde)} ORDER BY criada_em",
            params,
        )
        if not linhas:
            print("nenhuma chave" + (f" para {args.consumidor}" if args.consumidor else ""))
            return 0

        for l in linhas:
            escopos = (l["escopos"] or "").strip()
            largura = "AMPLA   " if escopos == "leitura" else "restrita"
            estado = "revogada" if l["revogada_em"] else "ativa   "
            print(f"{l['prefixo']}  {estado}  {largura}  "
                  f"{l['consumidor']:<20} {str(l['criada_em'])[:19]}")
            print(f"{'':10}escopos: {escopos}")
            print(f"{'':10}quota:   {l['quota_minuto']}/min · {l['quota_dia']}/dia")
        print()
        print(f"{len(linhas)} chave(s). O segredo não fica no banco: chave sem "
              f"segredo em mãos é para revogar, não reaproveitar.")
        return 0
    finally:
        sink.fechar()


def cmd_revogar(args) -> int:
    """Revoga uma chave pelo prefixo. Sem volta: não existe des-revogar.

    O prefixo é o identificador público — é o que aparece nos logs e o que o
    consumidor pode citar sem entregar o segredo. O segredo não é aceito aqui
    de propósito: pedir a chave inteira para desligá-la obrigaria a tê-la em
    mãos, e a chave que mais precisa ser revogada é justamente a que se perdeu.
    """
    from .api import auth

    sink = criar_sink()
    try:
        if not auth.revogar(sink, args.prefixo):
            print(f"nada a revogar: {args.prefixo} não existe ou já está revogada.")
            return 1
        print(f"revogada: {args.prefixo}")
        return 0
    finally:
        sink.fechar()


def cmd_escopo(args) -> int:
    """Acrescenta um escopo a uma chave ativa pelo prefixo, sem reemitir.

    Antes disto, dar `setups` à chave do MCP serviço obrigava a revogar e
    emitir outra — e trocar o segredo num serviço em produção por causa de um
    token de escopo é risco sem ganho. Só acrescenta; tirar continua sendo
    revogar (ver `auth.acrescentar_escopo`).
    """
    from .api import auth

    sink = criar_sink()
    try:
        r = auth.acrescentar_escopo(sink, args.prefixo, args.adicionar)
        if r is None:
            print(f"nada feito: {args.prefixo} não existe ou está revogada.")
            return 1
        if r is False:
            print(f"{args.prefixo} já tinha o escopo {args.adicionar!r}.")
            return 0
        print(f"{args.prefixo} ganhou o escopo {args.adicionar!r}.")
        return 0
    finally:
        sink.fechar()


def cmd_status(args) -> int:
    sink = criar_sink()
    print(f"publicação em gold: v{publicacao.versao_atual(sink)}")
    for e in repo.execucoes(sink, limite=args.limite):
        print(f"  #{e['id']:<4} {e['dataset_chave']:<14} {e['janela']:<6} "
              f"{e['status']:<10} linhas={e['linhas_silver']:<8} "
              f"delta={e['delta_linhas']}")
    sink.fechar()
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    p = argparse.ArgumentParser(prog="portal", description="Portal de Dados B3/CVM")
    sub = p.add_subparsers(dest="cmd", required=True)

    m = sub.add_parser("migrar", help="aplica migrações (idempotente)")
    m.add_argument("--seed", action="store_true", help="cadastra a config da CVM")
    m.add_argument("--forcar-seed", action="store_true",
                   help="reversiona a config mesmo sem mudança")
    m.set_defaults(func=cmd_migrar)

    i = sub.add_parser("ingerir", help="roda uma janela de um dataset")
    i.add_argument("dataset")
    i.add_argument("janela")
    i.add_argument("--replay", action="store_true",
                   help="recomputa do bronze, sem rede")
    i.add_argument("--trigger", default="manual")
    i.set_defaults(func=cmd_ingerir)

    a = sub.add_parser("agendados", help="roda os agendamentos ativos (cron)")
    a.add_argument("--chave", help="roda só um agendamento")
    a.add_argument("--forcar", action="store_true",
                   help="roda mesmo o que não está vencido")
    a.set_defaults(func=cmd_agendados)

    r = sub.add_parser(
        "recomputar",
        help="refaz silver/calculados/gold a partir do bronze, sem rede",
    )
    r.add_argument("dataset", nargs="?", help="omitido = todos")
    r.add_argument("janela", nargs="?", help="omitida = todas as capturadas")
    r.set_defaults(func=cmd_recomputar)

    v = sub.add_parser("verificar", help="imprime a digital de gold")
    v.set_defaults(func=cmd_verificar)

    c = sub.add_parser("chave", help="emite chave de API")
    c.add_argument("consumidor")
    c.add_argument("--quota-minuto", type=int, default=120)
    c.add_argument("--quota-dia", type=int, default=50000)
    c.add_argument("--classe", action="append", default=[],
                   help="restringe a chave a uma classe (repetível)")
    c.add_argument("--fonte", action="append", default=[],
                   help="opt-in de fonte com restrição de uso (ex.: b3) — sem "
                        "ele, chave restrita por classe recebe a resposta sem "
                        "os atributos dessa origem (repetível)")
    c.set_defaults(func=cmd_chave)

    k = sub.add_parser("chaves", help="lista as chaves de API")
    k.add_argument("--consumidor", help="filtra por consumidor")
    k.add_argument("--todas", action="store_true",
                   help="inclui as já revogadas")
    k.set_defaults(func=cmd_chaves)

    rv = sub.add_parser("revogar", help="revoga uma chave de API pelo prefixo")
    rv.add_argument("prefixo", help="o identificador público da chave")
    rv.set_defaults(func=cmd_revogar)

    es = sub.add_parser("escopo", help="acrescenta um escopo a uma chave ativa")
    es.add_argument("prefixo", help="o identificador público da chave")
    es.add_argument("--adicionar", required=True, metavar="ESCOPO",
                    help="um token, ex.: setups, fonte:b3, classe:empresa")
    es.set_defaults(func=cmd_escopo)

    s = sub.add_parser("status", help="mostra publicação e últimas execuções")
    s.add_argument("--limite", type=int, default=10)
    s.set_defaults(func=cmd_status)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
