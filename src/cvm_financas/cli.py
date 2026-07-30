"""CLI: cvm-ingest."""
from __future__ import annotations

import argparse
import logging
import sys

from .config import GRUPOS
from .load import schema_sql
from .pipeline import executar


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="cvm-ingest",
        description="Ingestor CVM DFP/ITR -> base própria (DuckDB/Postgres).",
    )
    ap.add_argument("--tipos", nargs="+", default=["DFP", "ITR"], choices=["DFP", "ITR"])
    ap.add_argument("--anos", default="2023", help="ex: 2020-2024 ou 2021,2023")
    ap.add_argument("--grupos", nargs="+", default=list(GRUPOS.keys()),
                    help="subset de grupos (default: todos)")
    ap.add_argument("--db", default="cvm.duckdb", help="arquivo DuckDB (sink default)")
    ap.add_argument("--pg", default=None, help="DSN Postgres; se setado, ignora --db")
    ap.add_argument("--arquivo-local", default=None,
                    help="caminho de um .zip local (pula download; teste offline)")
    ap.add_argument("--dry-run", action="store_true",
                    help="transforma e resume, sem carregar no banco")
    ap.add_argument("--print-schema", action="store_true",
                    help="imprime o DDL Postgres empacotado e sai")
    ap.add_argument("-v", "--verbose", action="store_true")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(message)s", stream=sys.stderr,
    )

    if args.print_schema:
        print(schema_sql())
        return 0

    res = executar(
        tipos=args.tipos, anos=args.anos, grupos=args.grupos,
        db=args.db, pg=args.pg, arquivo_local=args.arquivo_local, dry_run=args.dry_run,
    )
    if res.linhas == 0:
        print("[cvm-ingest] nada carregado.", file=sys.stderr)
        return 1

    destino = "dry-run (sem carga)" if args.dry_run else (args.pg or args.db)
    print(
        f"[cvm-ingest] {res.linhas:,} linhas | {res.linhas_latest:,} na última versão "
        f"| {len(res.arquivos)} arquivos | destino: {destino}",
        file=sys.stderr,
    )
    if res.carregado and res.total_no_banco is not None:
        print(f"[cvm-ingest] total no banco: {res.total_no_banco:,}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
