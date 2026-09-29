"""Trava por dataset+janela: duas cargas da mesma janela não coexistem.

Produção: `cvm_itr`/2026, execuções 24 e 26 sobrepostas entre 06:17 e 07:31 de
04/08, com `DeadlockDetected` numa delas. Nada impedia o segundo disparo.
"""
from __future__ import annotations

import pytest

from app import repositorio as repo, seed_fontes
from app.motor import ingestao
from tests.test_cotahist import ARQUIVO

JANELA = "2026-07-31"


def baixa(url, cabecalhos=None):
    return ARQUIVO


def n_execucoes(sink) -> int:
    return sink.um("SELECT count(*) AS n FROM log_execucao")["n"]


@pytest.fixture()
def cotahist(sink):
    seed_fontes.aplicar(sink)
    return sink


def test_janela_ocupada_devolve_ja_em_execucao_sem_abrir_execucao(cotahist):
    with repo.trava_execucao(cotahist, "b3_cotahist", JANELA) as obtida:
        assert obtida
        res = ingestao.executar(cotahist, "b3_cotahist", JANELA, baixar=baixa)

    assert res.status == "ja_em_execucao"
    assert res.execucao_id == 0
    assert n_execucoes(cotahist) == 0   # nem a linha de log nasceu
    assert cotahist.um("SELECT count(*) AS n FROM bronze_captura")["n"] == 0


def test_libera_no_fim_e_a_janela_volta_a_rodar(cotahist):
    primeira = ingestao.executar(cotahist, "b3_cotahist", JANELA, baixar=baixa)
    segunda = ingestao.executar(cotahist, "b3_cotahist", JANELA, baixar=baixa)
    assert primeira.status == segunda.status == "publicado"


def test_libera_mesmo_quando_a_carga_estoura(cotahist):
    def quebra(url, cabecalhos=None):
        raise RuntimeError("rede caiu")

    with pytest.raises(RuntimeError, match="rede caiu"):
        ingestao.executar(cotahist, "b3_cotahist", JANELA, baixar=quebra)

    with repo.trava_execucao(cotahist, "b3_cotahist", JANELA) as obtida:
        assert obtida, "a exceção deixou a trava presa"


def test_janela_diferente_ou_dataset_diferente_nao_e_bloqueado(cotahist):
    with repo.trava_execucao(cotahist, "b3_cotahist", "2026-07-30") as obtida:
        assert obtida
        res = ingestao.executar(cotahist, "b3_cotahist", JANELA, baixar=baixa)
    assert res.status == "publicado"


def test_trava_nao_reentra_na_mesma_janela(cotahist):
    with repo.trava_execucao(cotahist, "b3_cotahist", JANELA) as primeira:
        with repo.trava_execucao(cotahist, "b3_cotahist", JANELA) as segunda:
            assert primeira and not segunda


def test_recomputar_recusado_nao_apaga_o_silver(cotahist):
    """`recomputar` apaga antes de reexecutar. Com a janela em mãos de outro
    processo, apagar e desistir deixaria o silver vazio."""
    ingestao.executar(cotahist, "b3_cotahist", JANELA, baixar=baixa)
    antes = cotahist.um("SELECT count(*) AS n FROM fato_negociacao")["n"]
    assert antes > 0

    with repo.trava_execucao(cotahist, "b3_cotahist", JANELA):
        res = ingestao.recomputar(cotahist, "b3_cotahist", JANELA)

    assert res.status == "ja_em_execucao"
    assert cotahist.um("SELECT count(*) AS n FROM fato_negociacao")["n"] == antes


# --------------------------------------------------------------------------
# Caminho Postgres, sem Postgres: o SQL e o ciclo de vida da trava
# --------------------------------------------------------------------------
class FalsoPostgres:
    dialeto = "postgres"

    def __init__(self, concede=True):
        self.concede, self.sql = concede, []

    def um(self, sql, params=()):
        self.sql.append((sql, tuple(params)))
        if "pg_try_advisory_lock" in sql:
            return {"ok": self.concede}
        return {"ok": True}


def test_postgres_pega_e_solta_a_advisory_lock_com_a_mesma_chave():
    sink = FalsoPostgres()
    with repo.trava_execucao(sink, "b3_cotahist", JANELA) as obtida:
        assert obtida
    assert [s for s, _ in sink.sql] == [
        "SELECT pg_try_advisory_lock(CAST(? AS bigint)) AS ok",
        "SELECT pg_advisory_unlock(CAST(? AS bigint)) AS ok",
    ]
    assert sink.sql[0][1] == sink.sql[1][1] == (
        repo.chave_trava("b3_cotahist", JANELA),
    )


def test_postgres_solta_a_lock_quando_o_corpo_levanta():
    sink = FalsoPostgres()
    with pytest.raises(ValueError):
        with repo.trava_execucao(sink, "b3_cotahist", JANELA):
            raise ValueError("estourou")
    assert "pg_advisory_unlock" in sink.sql[-1][0]
    # E a trava em processo também saiu: dá para pegar de novo.
    with repo.trava_execucao(FalsoPostgres(), "b3_cotahist", JANELA) as obtida:
        assert obtida


def test_postgres_recusada_nao_tenta_soltar_e_nao_fica_presa():
    sink = FalsoPostgres(concede=False)
    with repo.trava_execucao(sink, "b3_cotahist", JANELA) as obtida:
        assert not obtida
    assert all("unlock" not in s for s, _ in sink.sql)
    with repo.trava_execucao(FalsoPostgres(), "b3_cotahist", JANELA) as obtida:
        assert obtida


def test_falha_ao_soltar_nao_mascara_a_excecao_original():
    class QuebraNoUnlock(FalsoPostgres):
        def um(self, sql, params=()):
            if "unlock" in sql:
                raise ConnectionError("conexão já morreu")
            return super().um(sql, params)

    with pytest.raises(ValueError, match="original"):
        with repo.trava_execucao(QuebraNoUnlock(), "b3_cotahist", JANELA):
            raise ValueError("original")


def test_chave_e_estavel_entre_processos_e_cabe_em_bigint():
    """`hash()` do Python muda a cada processo e derrubaria a trava: dois
    crons calculariam chaves diferentes para a mesma janela. Fixada num
    literal para que uma troca de algoritmo apareça aqui."""
    chave = repo.chave_trava("b3_cotahist", JANELA)
    assert chave == repo.chave_trava("b3_cotahist", JANELA)
    assert chave != repo.chave_trava("b3_cotahist", "2026-07-30")
    assert chave != repo.chave_trava("b3_instrumentos", JANELA)
    assert -(2**63) <= chave < 2**63
    assert chave == CHAVE_FIXADA


CHAVE_FIXADA = 4089040923998509363   # blake2b-8 de 'mydata:execucao:b3_cotahist:2026-07-31'


# --------------------------------------------------------------------------
# Postgres real (só no CI, com PORTAL_TESTE_POSTGRES): a advisory lock de
# verdade, em duas conexões — o que o sink falso não prova.
# --------------------------------------------------------------------------
import os as _os

import pytest as _pytest


@_pytest.mark.skipif(not _os.getenv("PORTAL_TESTE_POSTGRES"),
                     reason="só com Postgres real (CI)")
def test_advisory_lock_real_em_duas_conexoes():
    from app import repositorio as repo
    from app.sinks import SinkPostgres

    dsn = _os.environ["PORTAL_TESTE_POSTGRES"]
    a, b = SinkPostgres(dsn), SinkPostgres(dsn)
    chave = repo.chave_trava("b3_cotahist", "2026-09-25")
    try:
        with repo.trava_execucao(a, "b3_cotahist", "2026-09-25") as obtida:
            assert obtida is True
            outra = b.um("SELECT pg_try_advisory_lock(CAST(? AS bigint)) AS ok", (chave,))
            assert outra["ok"] is False, "a segunda conexão não pode pegar a mesma trava"
        livre = b.um("SELECT pg_try_advisory_lock(CAST(? AS bigint)) AS ok", (chave,))
        assert livre["ok"] is True, "a trava tinha de ser solta no fim do with"
        b.um("SELECT pg_advisory_unlock(CAST(? AS bigint)) AS ok", (chave,))
    finally:
        a.fechar()
        b.fechar()
