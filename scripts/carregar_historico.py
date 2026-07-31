#!/usr/bin/env python
"""Carrega vários anos da CVM, parando antes de encher o disco.

A parada por espaço não é zelo: uma carga interrompida por disco cheio deixa
o banco num estado que o recomputo resolve, mas o *sistema* fica sem espaço
para recomputar. Vale mais parar com folga e retomar.

Uso:
    python scripts/carregar_historico.py --dfp 2020-2025 --itr 2022-2026
    python scripts/carregar_historico.py --dfp 2024 --piso-gb 5
"""
from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from app import bootstrap                      # noqa: E402
from app.motor import download, ingestao       # noqa: E402
from app.sinks import criar_sink               # noqa: E402


def livre_gb() -> float:
    return shutil.disk_usage(RAIZ).free / 1e9


def faixa(texto: str) -> list[str]:
    """`2020-2025` ou `2024` ou `2020,2023`."""
    anos: list[str] = []
    for parte in texto.split(","):
        parte = parte.strip()
        if "-" in parte:
            ini, fim = parte.split("-")
            anos += [str(a) for a in range(int(ini), int(fim) + 1)]
        elif parte:
            anos.append(parte)
    return anos


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dfp", default="", help="anos de DFP, ex.: 2020-2025")
    p.add_argument("--itr", default="", help="anos de ITR, ex.: 2022-2026")
    p.add_argument("--empresa", action="store_true", default=True,
                   help="alimenta também a classe empresa a partir da DFP")
    p.add_argument("--piso-gb", type=float, default=4.0,
                   help="para quando o disco livre cair abaixo disto")
    args = p.parse_args(argv)

    unidades: list[tuple[str, str]] = []
    for ano in faixa(args.dfp):
        unidades.append(("cvm_dfp", ano))
        if args.empresa:
            unidades.append(("cvm_dfp_empresa", ano))
    for ano in faixa(args.itr):
        unidades.append(("cvm_itr", ano))

    if not unidades:
        print("nada a carregar; use --dfp e/ou --itr", file=sys.stderr)
        return 2

    sink = criar_sink()
    bootstrap.preparar(sink)
    print(f"{len(unidades)} unidades · disco livre {livre_gb():.1f} GB", flush=True)

    feitas, puladas = 0, 0
    for dataset, ano in unidades:
        if livre_gb() < args.piso_gb:
            print(f"PARANDO: disco livre {livre_gb():.1f} GB abaixo do piso "
                  f"de {args.piso_gb} GB. Faltou: {dataset} {ano}", flush=True)
            break
        inicio = time.monotonic()
        try:
            res = ingestao.executar(sink, dataset, ano, trigger="historico",
                                    baixar=download.baixar)
            print(f"  {dataset:<16} {ano}  {res.status:<10} "
                  f"delta={res.delta_linhas:>8,}  "
                  f"{time.monotonic()-inicio:5.0f}s  "
                  f"livre={livre_gb():.1f}GB", flush=True)
            feitas += 1
        except Exception as e:  # noqa: BLE001 — um ano ruim não para os outros
            puladas += 1
            print(f"  {dataset:<16} {ano}  FALHOU: {type(e).__name__}: "
                  f"{str(e)[:70]}", flush=True)

    print(f"\nconcluídas {feitas}, falharam {puladas}, "
          f"disco livre {livre_gb():.1f} GB", flush=True)
    sink.fechar()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
