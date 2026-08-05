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
    """`?` -> `%s`, preservando `?` dentro de literais e escapando todo `%`.

    A distinção entre dentro e fora do literal vale para o `?`, que só é
    placeholder fora dele. Para o `%` não vale: o psycopg varre a string
    inteira e não sabe o que é literal de SQL, então um `%` dentro de aspas
    precisa ser escapado igual. Foi o que quebrou a busca por ticker, cujo
    `LIKE lower(ticker) || '%'` é literal — em DuckDB passava, e o defeito só
    existia no dialeto de produção.
    """
    partes: list[str] = []
    pos = 0
    for m in _LITERAL.finditer(sql):
        partes.append(sql[pos : m.start()].replace("%", "%%").replace("?", "%s"))
        partes.append(m.group(0).replace("%", "%%"))
        pos = m.end()
    partes.append(sql[pos:].replace("%", "%%").replace("?", "%s"))
    return "".join(partes)


# --------------------------------------------------------------------------
# Carga em bloco
# --------------------------------------------------------------------------
# Upsert linha a linha contra tabela indexada custa ~300 linhas/s: um ano da
# CVM levava 27 minutos. O caminho rápido é encher uma staging sem índice e
# resolver tudo numa instrução só — medido em ~9.300 linhas/s, trinta vezes
# mais. A staging carrega `_ord` para o desempate ficar determinístico: a CVM
# repete a mesma chave natural dentro do arquivo, e a primeira ocorrência é a
# que vale, como era no laço em Python.
STAGING = "_stg_carga"


def sql_upsert_da_staging(
    tabela: str, campos: list[str], chave_natural: list[str], stg: str = STAGING
) -> str:
    lista = ", ".join(campos)
    atualizaveis = [c for c in campos if c not in chave_natural]
    resolucao = (
        f"DO UPDATE SET {', '.join(f'{c} = excluded.{c}' for c in atualizaveis)}"
        if atualizaveis
        else "DO NOTHING"
    )
    return (
        f"INSERT INTO {tabela} ({lista}) SELECT {lista} FROM ("
        f"  SELECT {lista}, row_number() OVER ("
        f"    PARTITION BY {', '.join(chave_natural)} ORDER BY _ord) AS _rn"
        f"  FROM {stg}"
        f") s WHERE _rn = 1 "
        f"ON CONFLICT ({', '.join(chave_natural)}) {resolucao}"
    )


def sql_criar_staging(tabela: str, campos: list[str], stg: str = STAGING) -> str:
    """Staging com os tipos da tabela alvo, sem índice e sem restrição."""
    return (
        f"CREATE TEMP TABLE {stg} AS "
        f"SELECT {', '.join(campos)}, CAST(0 AS bigint) AS _ord "
        f"FROM {tabela} WHERE 1 = 0"
    )


class Sink(Protocol):
    dialeto: str

    def executar(self, sql: str, params: Iterable[Any] = ()) -> None: ...
    def executar_muitos(self, sql: str, linhas: Iterable[Iterable[Any]]) -> None: ...
    def carregar_em_lote(
        self, tabela: str, campos: list[str], chave_natural: list[str],
        linhas: Iterable[Iterable[Any]],
    ) -> int: ...
    def consultar(self, sql: str, params: Iterable[Any] = ()) -> list[dict]: ...
    def um(self, sql: str, params: Iterable[Any] = ()) -> dict | None: ...
    def proximo_id(self, tabela: str) -> int: ...
    def transacao(self): ...
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

    @contextmanager
    def transacao(self):
        """Tudo ou nada. Migração pela metade deixa schema irreconhecível —
        e o conserto teria de adivinhar até onde ela chegou."""
        self.con.begin()
        try:
            yield
        except Exception:
            self.con.rollback()
            raise
        else:
            self.con.commit()

    def executar(self, sql: str, params: Iterable[Any] = ()) -> None:
        self.con.execute(sql, list(params))

    def executar_muitos(self, sql: str, linhas: Iterable[Iterable[Any]]) -> None:
        dados = [list(linha) for linha in linhas]
        if dados:
            self.con.executemany(sql, dados)

    def carregar_em_lote(
        self, tabela: str, campos: list[str], chave_natural: list[str],
        linhas: Iterable[Iterable[Any]],
    ) -> int:
        # `executemany` do DuckDB é uma execução preparada por linha. Blocos de
        # 200 num único VALUES foram o melhor ponto medido; blocos maiores
        # voltam a piorar por causa do custo de parsear a instrução gigante.
        self.executar(f"DROP TABLE IF EXISTS {STAGING}")
        self.executar(sql_criar_staging(tabela, campos))
        marcador = "(" + ",".join(["?"] * (len(campos) + 1)) + ")"
        total, bloco = 0, []
        try:
            for linha in linhas:
                bloco.append([*linha, total])
                total += 1
                if len(bloco) >= 200:
                    self._despejar(marcador, bloco)
                    bloco = []
            if bloco:
                self._despejar(marcador, bloco)
            if total:
                self.executar(sql_upsert_da_staging(tabela, campos, chave_natural))
        finally:
            self.executar(f"DROP TABLE IF EXISTS {STAGING}")
        return total

    def _despejar(self, marcador: str, bloco: list[list]) -> None:
        self.con.execute(
            f"INSERT INTO {STAGING} VALUES " + ",".join([marcador] * len(bloco)),
            [valor for linha in bloco for valor in linha],
        )

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


def _executar(cur, sql: str, params: Iterable[Any] = ()) -> None:
    """Executa no psycopg, convertendo só quando há o que converter.

    Sem parâmetros, o SQL vai cru. Isso não é otimização: o psycopg só procura
    placeholder quando recebe uma sequência de parâmetros, e passar uma lista
    vazia faz ele tratar como placeholder qualquer `%` do texto. O corpo do
    trigger de imutabilidade do bronze tem `%` dentro de um literal —
    `RAISE EXCEPTION '... : % na captura %'` — e era o suficiente para
    `migrar` estourar no boot, que é o primeiro comando do deploy.
    """
    lista = list(params)
    if lista:
        cur.execute(qmark_para_pyformat(sql), lista)
    else:
        cur.execute(sql)


class SinkPostgres:
    """Sink de produção. Railway injeta a DATABASE_URL."""

    dialeto = "postgres"

    def __init__(self, dsn: str):
        import psycopg
        from psycopg.rows import dict_row
        from psycopg.types.numeric import FloatLoader

        self.con = psycopg.connect(dsn, row_factory=dict_row, autocommit=True)
        # `numeric` chega como `Decimal`, e o serializador JSON do FastAPI
        # transforma `Decimal` em **string**. O efeito era o consumidor receber
        # `"105409478000.0"` no lugar de um número — em produção, porque só lá
        # o dialeto é Postgres; em DuckDB o mesmo campo é `double` e sai como
        # número. O ADR-17 notou a diferença e ajustou os testes; o contrato
        # publicado ficou torto esse tempo todo.
        #
        # Trocar por `float` no carregamento é a correção certa aqui: o sink
        # existe justamente para o resto do sistema não precisar saber qual
        # dialeto está embaixo. Precisão: `vl_conta` é valor contábil em reais,
        # bem dentro do que o double representa exatamente.
        self.con.adapters.register_loader("numeric", FloatLoader)

    @contextmanager
    def transacao(self):
        """A conexão é autocommit — cada statement confirma sozinho. Sem isto,
        uma migração que renomeia, recria e copia deixaria a tabela de
        configuração no chão se falhasse no meio."""
        with self.con.transaction():
            yield

    def executar(self, sql: str, params: Iterable[Any] = ()) -> None:
        with self.con.cursor() as cur:
            _executar(cur, sql, params)

    def executar_muitos(self, sql: str, linhas: Iterable[Iterable[Any]]) -> None:
        dados = [list(linha) for linha in linhas]
        if not dados:
            return
        with self.con.cursor() as cur:
            cur.executemany(qmark_para_pyformat(sql), dados)

    def carregar_em_lote(
        self, tabela: str, campos: list[str], chave_natural: list[str],
        linhas: Iterable[Iterable[Any]],
    ) -> int:
        total = 0
        with self.con.cursor() as cur:
            cur.execute(f"DROP TABLE IF EXISTS {STAGING}")
            cur.execute(sql_criar_staging(tabela, campos))
            copia = f"COPY {STAGING} ({', '.join(campos)}, _ord) FROM STDIN"
            try:
                with cur.copy(copia) as fluxo:
                    for linha in linhas:
                        fluxo.write_row([*linha, total])
                        total += 1
                if total:
                    cur.execute(sql_upsert_da_staging(tabela, campos, chave_natural))
            finally:
                cur.execute(f"DROP TABLE IF EXISTS {STAGING}")
        return total

    def consultar(self, sql: str, params: Iterable[Any] = ()) -> list[dict]:
        with self.con.cursor() as cur:
            _executar(cur, sql, params)
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
