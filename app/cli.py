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
from .motor import download, ingestao, publicacao
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
        seed_cvm.aplicar(sink)
        print("configuração da CVM cadastrada")
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


def cmd_chave(args) -> int:
    from .api import auth

    sink = criar_sink()
    emitida = auth.emitir(sink, args.consumidor, args.quota_minuto, args.quota_dia)
    print(f"consumidor: {emitida.consumidor}")
    print(f"prefixo:    {emitida.prefixo}")
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

    c = sub.add_parser("chave", help="emite chave de API")
    c.add_argument("consumidor")
    c.add_argument("--quota-minuto", type=int, default=120)
    c.add_argument("--quota-dia", type=int, default=50000)
    c.set_defaults(func=cmd_chave)

    s = sub.add_parser("status", help="mostra publicação e últimas execuções")
    s.add_argument("--limite", type=int, default=10)
    s.set_defaults(func=cmd_status)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
