"""Sinks de carga (DuckDB, Postgres) e acesso ao schema empacotado."""
from __future__ import annotations

import logging
from importlib.resources import files

import pandas as pd

log = logging.getLogger("cvm_financas")

_DDL_DUCKDB = """
CREATE TABLE IF NOT EXISTS fato_conta (
    cd_cvm INTEGER, cnpj TEXT, denom_cia TEXT,
    tipo_doc TEXT, grupo TEXT, consolidado BOOLEAN,
    dt_refer DATE, dt_ini_exerc DATE, dt_fim_exerc DATE,
    ordem_exerc TEXT, versao INTEGER,
    cd_conta TEXT, ds_conta TEXT, st_conta_fixa TEXT,
    moeda TEXT, escala_moeda TEXT, coluna_df TEXT,
    vl_conta DOUBLE, vl_conta_norm DOUBLE,
    is_latest BOOLEAN, itr_acumulado BOOLEAN, fonte_arquivo TEXT
);
"""


def schema_sql() -> str:
    """Retorna o DDL Postgres empacotado (schema + views + checks)."""
    return (files("cvm_financas") / "sql" / "schema_postgres.sql").read_text(encoding="utf-8")


def load_duckdb(df: pd.DataFrame, path: str) -> int:
    """Carga idempotente em DuckDB. Retorna o total de linhas na tabela."""
    import duckdb

    con = duckdb.connect(path)
    con.execute(_DDL_DUCKDB)
    chaves = df[["cd_cvm", "tipo_doc", "dt_refer"]].drop_duplicates()
    con.register("novos", df)
    con.register("chaves", chaves)
    con.execute(
        "DELETE FROM fato_conta f USING chaves c "
        "WHERE f.cd_cvm=c.cd_cvm AND f.tipo_doc=c.tipo_doc AND f.dt_refer=c.dt_refer;"
    )
    con.execute("INSERT INTO fato_conta SELECT * FROM novos;")
    total = con.execute("SELECT count(*) FROM fato_conta").fetchone()[0]
    con.close()
    log.info("duckdb %s: +%d | total %d", path, len(df), total)
    return int(total)


def load_postgres(df: pd.DataFrame, dsn: str) -> int:
    """Carga idempotente em Postgres (schema cvm). Retorna linhas inseridas."""
    from sqlalchemy import create_engine, text

    engine = create_engine(dsn)
    with engine.begin() as conn:
        chaves = df[["cd_cvm", "tipo_doc", "dt_refer"]].drop_duplicates()
        chaves.to_sql("_stg_chaves", conn, schema="cvm", if_exists="replace", index=False)
        conn.execute(text(
            "DELETE FROM cvm.fato_conta f USING cvm._stg_chaves c "
            "WHERE f.cd_cvm=c.cd_cvm AND f.tipo_doc=c.tipo_doc AND f.dt_refer=c.dt_refer;"
        ))
        df.to_sql("fato_conta", conn, schema="cvm", if_exists="append", index=False)
        conn.execute(text("DROP TABLE IF EXISTS cvm._stg_chaves;"))
    log.info("postgres: +%d linhas em cvm.fato_conta", len(df))
    return len(df)
