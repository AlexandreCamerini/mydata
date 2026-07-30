"""cvm-financas — ingestor das demonstrações financeiras da CVM (DFP/ITR)."""
from __future__ import annotations

from .pipeline import ResultadoIngestao, executar, parse_anos
from .parse import (
    extrair_dataframes,
    marcar_versao_latest,
    parse_csv_conta,
    preparar_saida,
)
from .load import load_duckdb, load_postgres, schema_sql

__version__ = "0.1.0"
__all__ = [
    "executar",
    "parse_anos",
    "ResultadoIngestao",
    "parse_csv_conta",
    "extrair_dataframes",
    "marcar_versao_latest",
    "preparar_saida",
    "load_duckdb",
    "load_postgres",
    "schema_sql",
    "__version__",
]
