"""Plano do `calcular` no Postgres (incidente de 2026-09-29).

Em produção o UPDATE de campo de janela escolheu laço aninhado — estatística
velha estimava 1 linha para a captura nova — e a window function sobre a
tabela inteira foi reavaliada por linha da carga: 16 h num campo que leva
11 s com plano de junção. A correção tem duas partes, e este teste trava a
ordem delas sem precisar de Postgres: ANALYZE antes de tudo; laço aninhado
desligado só em volta do UPDATE de janela, e religado depois.
"""
from __future__ import annotations

from app.motor import calculados as calc


class _Gravador:
    """Sink de mentira com dialeto Postgres: só grava o SQL."""

    dialeto = "postgres"

    def __init__(self):
        self.sql: list[str] = []

    def executar(self, sql, params=()):
        self.sql.append(" ".join(sql.split()))

    def um(self, sql, params=()):
        return None

    def consultar(self, sql, params=()):
        return []


DS = {"chave": "b3_cotahist", "tabela_destino": "fato_negociacao",
      "chave_natural": "dt_pregao,codneg"}
JANELA = {"id": 1, "ordem": 1, "nome": "log_retorno", "classe": "janela",
          "materializacao": "coluna", "retroage": True,
          "expressao": "lag(preco_fechamento) OVER (w)",
          "particao_por": "codneg", "ordena_por": "dt_pregao"}
ESCALAR = {"id": 2, "ordem": 0, "nome": "x", "classe": "escalar",
           "materializacao": "coluna", "expressao": "1"}


def _executar(campos):
    g = _Gravador()
    calc.aplicar(g, DS, campos, capturas=[187])
    return g.sql


def test_analyze_vem_antes_de_qualquer_update():
    sql = _executar([ESCALAR, JANELA])
    assert sql[0] == "ANALYZE fato_negociacao"
    assert all(not s.startswith("UPDATE") for s in sql[:1])


def test_laco_aninhado_desligado_so_em_volta_do_update_de_janela():
    sql = _executar([ESCALAR, JANELA])
    i_set = sql.index("SET enable_nestloop = off")
    i_reset = sql.index("RESET enable_nestloop")
    atualiza_janela = [i for i, s in enumerate(sql)
                       if s.startswith("UPDATE") and "log_retorno" in s]
    atualiza_escalar = [i for i, s in enumerate(sql)
                        if s.startswith("UPDATE fato_negociacao SET x")]
    assert atualiza_janela and i_set < atualiza_janela[0] < i_reset
    assert atualiza_escalar and not (i_set < atualiza_escalar[0] < i_reset)


def test_reset_acontece_mesmo_se_o_update_falhar():
    class _Falha(_Gravador):
        def executar(self, sql, params=()):
            super().executar(sql, params)
            if sql.lstrip().startswith("UPDATE") and "log_retorno" in sql:
                raise RuntimeError("cancelado")

    g = _Falha()
    try:
        calc.aplicar(g, DS, [JANELA], capturas=[187])
    except RuntimeError:
        pass
    assert g.sql[-1] == "RESET enable_nestloop"


def test_duckdb_nao_recebe_nada_disso(sink):
    """Nos testes em DuckDB a sequência não muda: nem ANALYZE nem SET."""
    gravado = []
    original = sink.executar

    def espiar(sql, params=()):
        gravado.append(sql)
        return original(sql, params)

    sink.executar = espiar
    try:
        calc._sem_laco_aninhado(sink).__enter__()
    finally:
        sink.executar = original
    assert not any("enable_nestloop" in s for s in gravado)
