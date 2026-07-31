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
from datetime import datetime, timezone

from . import bootstrap, repositorio as repo, seed_cvm
from .motor import download, ingestao, publicacao, verificacao
from .sinks import criar_sink

log = logging.getLogger("portal")


def janela_corrente(padrao: str) -> str:
    agora = datetime.now(timezone.utc)
    if padrao == "ano_corrente":
        return str(agora.year)
    if padrao == "ano_anterior":
        return str(agora.year - 1)
    return padrao


def cmd_migrar(args) -> int:
    sink = criar_sink()
    novas = bootstrap.preparar(sink)
    print(f"migrações aplicadas: {novas or 'nenhuma (já estava em dia)'}")
    if args.seed:
        # Idempotente: configuração idêntica à vigente não cria versão nova.
        # É isto que torna seguro semear a cada boot do serviço.
        if seed_cvm.aplicar(sink, forcar=args.forcar_seed):
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
        janela = janela_corrente(ag["janela_padrao"])
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
    print(json.dumps(saida, ensure_ascii=False, indent=2))
    sink.fechar()
    return 1 if falhas else 0


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
    escopos = (",".join(f"classe:{c}" for c in args.classe)
               if args.classe else "leitura")
    emitida = auth.emitir(sink, args.consumidor, args.quota_minuto,
                          args.quota_dia, escopos=escopos)
    print(f"consumidor: {emitida.consumidor}")
    print(f"prefixo:    {emitida.prefixo}")
    print(f"escopos:    {escopos}")
    print(f"chave:      {emitida.chave_completa}")
    print("Guarde agora: só o hash fica no banco.")
    sink.fechar()
    return 0


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
    c.set_defaults(func=cmd_chave)

    s = sub.add_parser("status", help="mostra publicação e últimas execuções")
    s.add_argument("--limite", type=int, default=10)
    s.set_defaults(func=cmd_status)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
