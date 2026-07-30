"""Abstração de sink: mesmo código sobre Postgres (prod) e DuckDB (dev/teste).

O SQL do projeto é escrito com placeholders `?`. O sink Postgres traduz para
`%s` respeitando literais entre aspas, para que um `?` dentro de string não
vire parâmetro.
"""
from __future__ import annotations

import os
import re
from contextlib import contextmanager
from typing import Any, Iterable, Iterator, Protocol

# --------------------------------------------------------------------------
# Tipos por dialeto. O SQL das migrações usa estes placeholders em chaves.
# --------------------------------------------------------------------------
TIPOS = {
    "postgres": {
        "SERIAL": "bigserial PRIMARY KEY",
        "BINARIO": "bytea",
        "TSTZ": "timestamptz",
        "JSON": "text",          # snapshot não é consultado; texto é portátil
        "BOOL": "boolean",
        "TEXTO": "text",
        "INT": "bigint",
        "NUM": "numeric",
        "AGORA": "now()",
    },
    "duckdb": {
        "SERIAL": "bigint PRIMARY KEY",   # id vem de sequência explícita
        "BINARIO": "blob",
        "TSTZ": "timestamptz",
        "JSON": "text",
        "BOOL": "boolean",
        "TEXTO": "text",
        "INT": "bigint",
        "NUM": "double",
        "AGORA": "now()",
    },
}


def render(sql: str, dialeto: str) -> str:
    """Substitui os placeholders de tipo pelo equivalente do dialeto."""
    for chave, valor in TIPOS[dialeto].items():
        sql = sql.replace("{" + chave + "}", valor)
    return sql


_LITERAL = re.compile(r"'(?:[^']|'')*'")


def qmark_para_pyformat(sql: str) -> str:
    """`?` -> `%s`, preservando `?` dentro de literais e escapando `%` solto."""
    partes: list[str] = []
    pos = 0
    for m in _LITERAL.finditer(sql):
        partes.append(sql[pos : m.start()].replace("%", "%%").replace("?", "%s"))
        partes.append(m.group(0))
        pos = m.end()
    partes.append(sql[pos:].replace("%", "%%").replace("?", "%s"))
    return "".join(partes)


class Sink(Protocol):
    dialeto: str

    def executar(self, sql: str, params: Iterable[Any] = ()) -> None: ...
    def executar_muitos(self, sql: str, linhas: Iterable[Iterable[Any]]) -> None: ...
    def consultar(self, sql: str, params: Iterable[Any] = ()) -> list[dict]: ...
    def um(self, sql: str, params: Iterable[Any] = ()) -> dict | None: ...
    def proximo_id(self, tabela: str) -> int: ...
    def fechar(self) -> None: ...


class SinkDuckDB:
    """Sink de desenvolvimento e teste. Zero setup, arquivo local ou memória."""

    dialeto = "duckdb"

    def __init__(self, caminho: str = ":memory:"):
        import duckdb

        if caminho != ":memory:":
            pasta = os.path.dirname(os.path.abspath(caminho))
            os.makedirs(pasta, exist_ok=True)
        self.con = duckdb.connect(caminho)

    def executar(self, sql: str, params: Iterable[Any] = ()) -> None:
        self.con.execute(sql, list(params))

    def executar_muitos(self, sql: str, linhas: Iterable[Iterable[Any]]) -> None:
        dados = [list(linha) for linha in linhas]
        if dados:
            self.con.executemany(sql, dados)

    def consultar(self, sql: str, params: Iterable[Any] = ()) -> list[dict]:
        cur = self.con.execute(sql, list(params))
        colunas = [d[0] for d in cur.description] if cur.description else []
        return [dict(zip(colunas, linha)) for linha in cur.fetchall()]

    def um(self, sql: str, params: Iterable[Any] = ()) -> dict | None:
        linhas = self.consultar(sql, params)
        return linhas[0] if linhas else None

    def proximo_id(self, tabela: str) -> int:
        return self.consultar(f"SELECT nextval('seq_{tabela}') AS id")[0]["id"]

    def fechar(self) -> None:
        self.con.close()


class SinkPostgres:
    """Sink de produção. Railway injeta a DATABASE_URL."""

    dialeto = "postgres"

    def __init__(self, dsn: str):
        import psycopg
        from psycopg.rows import dict_row

        self.con = psycopg.connect(dsn, row_factory=dict_row, autocommit=True)

    def executar(self, sql: str, params: Iterable[Any] = ()) -> None:
        with self.con.cursor() as cur:
            cur.execute(qmark_para_pyformat(sql), list(params))

    def executar_muitos(self, sql: str, linhas: Iterable[Iterable[Any]]) -> None:
        dados = [list(linha) for linha in linhas]
        if not dados:
            return
        with self.con.cursor() as cur:
            cur.executemany(qmark_para_pyformat(sql), dados)

    def consultar(self, sql: str, params: Iterable[Any] = ()) -> list[dict]:
        with self.con.cursor() as cur:
            cur.execute(qmark_para_pyformat(sql), list(params))
            return [dict(linha) for linha in cur.fetchall()]

    def um(self, sql: str, params: Iterable[Any] = ()) -> dict | None:
        linhas = self.consultar(sql, params)
        return linhas[0] if linhas else None

    def proximo_id(self, tabela: str) -> int:
        return self.consultar(f"SELECT nextval('seq_{tabela}') AS id")[0]["id"]

    def fechar(self) -> None:
        self.con.close()


@contextmanager
def abrir_sink(dsn: str | None = None, caminho_duckdb: str | None = None) -> Iterator[Sink]:
    sink = criar_sink(dsn, caminho_duckdb)
    try:
        yield sink
    finally:
        sink.fechar()


def criar_sink(dsn: str | None = None, caminho_duckdb: str | None = None) -> Sink:
    """Postgres quando há DATABASE_URL; DuckDB caso contrário."""
    dsn = dsn if dsn is not None else os.getenv("DATABASE_URL")
    if dsn:
        return SinkPostgres(dsn)
    caminho = caminho_duckdb or os.getenv("PORTAL_DUCKDB", "dados/portal.duckdb")
    return SinkDuckDB(caminho)
