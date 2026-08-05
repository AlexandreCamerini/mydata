"""O contrato de opções: `/v1/cotacoes` e `/v1/opcoes`.

O consumidor recebe a cadeia com ativo-objeto resolvido, prazo, volatilidade
implícita e gregas — e a mesma proveniência das outras classes, porque é o
que distingue este hub de um agregador que republica sem dizer de onde veio.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import bootstrap, seed_cvm
from app.api import auth
from app.motor import ingestao
from app.sinks import SinkDuckDB
from tests.test_cotahist import ARQUIVO


@pytest.fixture()
def cliente_b3(tmp_path, monkeypatch):
    banco = str(tmp_path / "b3.duckdb")
    monkeypatch.setenv("PORTAL_DUCKDB", banco)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("PORTAL_ADMIN_TOKEN", raising=False)

    s = SinkDuckDB(banco)
    bootstrap.preparar(s)
    seed_cvm.aplicar(s)
    s.executar(
        "INSERT INTO fato_indicador (captura_id, fonte_arquivo, origem_dataset,"
        " indicador, dt_referencia, valor, unidade) VALUES (0,'manual','bcb_cdi',"
        " 'cdi', '2026-07-30', 10.40, '% a.a.')"
    )
    ingestao.executar(
        s, "b3_cotahist", "2026-07-31",
        baixar=lambda url, cabecalhos=None: ARQUIVO,
    )
    emitida = auth.emitir(s, "bolsia", quota_minuto=200, quota_dia=10_000)
    s.fechar()

    from app.api.main import app

    with TestClient(app) as c:
        c.headers.update({"X-API-Key": emitida.chave_completa})
        yield c


# --------------------------------------------------------------------------
# A cadeia
# --------------------------------------------------------------------------
def test_opcoes_do_ativo_objeto(cliente_b3):
    r = cliente_b3.get("/v1/opcoes/ABCB4")
    assert r.status_code == 200
    dados = r.json()["dados"]
    assert [d["contrato"] for d in dados] == ["ABCBH255"]
    linha = dados[0]
    assert linha["ticker_objeto"] == "ABCB4"
    assert linha["tipo"] == "CALL"
    assert linha["strike"] == pytest.approx(24.40)
    assert linha["dt_vencimento"] == "2026-08-21"
    assert linha["premio"] == pytest.approx(0.57)


def test_a_cadeia_traz_implicita_e_gregas(cliente_b3):
    linha = cliente_b3.get("/v1/opcoes/ABCB4").json()["dados"][0]
    assert 0 < linha["volatilidade_implicita"] < 5
    assert linha["preco_teorico"] == pytest.approx(linha["premio"], abs=1e-3)
    # Call tem delta entre 0 e 1; gama e vega são positivos; theta corrói.
    assert 0 <= linha["delta"] <= 1
    assert linha["gamma"] > 0 and linha["vega"] > 0
    assert linha["theta"] <= 0
    assert linha["prazo_anos"] == pytest.approx(15 / 252)


def test_cada_linha_carrega_proveniencia(cliente_b3):
    """Mesmo contrato das outras classes: sem isto, o produto vira o
    intermediário que ele existe para dispensar."""
    linha = cliente_b3.get("/v1/opcoes/ABCB4").json()["dados"][0]
    prov = linha["proveniencia"]
    assert prov["sha256"]
    assert prov["dt_captura"]
    assert prov["arquivo"].startswith("COTAHIST_D")
    assert prov["arquivo_em"].startswith("/v1/capturas/")


def test_filtra_por_vencimento_e_por_tipo(cliente_b3):
    assert cliente_b3.get(
        "/v1/opcoes/ABCB4?vencimento=2026-08-21").json()["dados"]
    assert cliente_b3.get(
        "/v1/opcoes/ABCB4?vencimento=2030-01-18").json()["dados"] == []
    assert cliente_b3.get("/v1/opcoes/ABCB4?tipo=PUT").json()["dados"] == []
    assert cliente_b3.get("/v1/opcoes/ABCB4?tipo=call").json()["dados"]


def test_papel_sem_opcao_devolve_lista_vazia(cliente_b3):
    """Vazio, não 404: a pergunta é legítima e a resposta é «não negociou»."""
    r = cliente_b3.get("/v1/opcoes/PETR4")
    assert r.status_code == 200 and r.json()["dados"] == []


def test_sem_pregao_vale_o_ultimo_daquele_papel(cliente_b3):
    """E não o último da base: um papel que parou de negociar devolveria
    vazio com corte global, o que pareceria falta de dado."""
    assert cliente_b3.get("/v1/opcoes/ABCB4").json()["dados"]
    assert cliente_b3.get("/v1/opcoes/ABCB4?pregao=2026-07-31").json()["dados"]
    assert cliente_b3.get("/v1/opcoes/ABCB4?pregao=2026-07-30").json()["dados"] == []


def test_vencimentos_resume_a_cadeia(cliente_b3):
    dados = cliente_b3.get("/v1/opcoes/ABCB4/vencimentos").json()["dados"]
    assert dados == [{
        "dt_vencimento": "2026-08-21", "contratos": 1,
        "menor_strike": pytest.approx(24.40), "maior_strike": pytest.approx(24.40),
    }]


# --------------------------------------------------------------------------
# As cotações
# --------------------------------------------------------------------------
def test_cotacoes_do_lote_padrao(cliente_b3):
    dados = cliente_b3.get("/v1/cotacoes/PETR4").json()["dados"]
    assert len(dados) == 1
    assert dados[0]["preco_fechamento"] == pytest.approx(43.42)
    assert dados[0]["volume_financeiro"] == pytest.approx(1_084_118_619.0)


def test_cotacoes_nao_devolvem_opcao(cliente_b3):
    """`gold_cotacoes` é o recorte à vista. Contrato de opção aparecendo aqui
    misturaria prêmio com preço de ação na mesma série."""
    assert cliente_b3.get("/v1/cotacoes/ABCBH255").json()["dados"] == []


def test_cotacoes_filtram_por_data(cliente_b3):
    assert cliente_b3.get("/v1/cotacoes/PETR4?de=2026-08-01").json()["dados"] == []
    assert cliente_b3.get("/v1/cotacoes/PETR4?ate=2026-07-31").json()["dados"]


# --------------------------------------------------------------------------
# O porteiro
# --------------------------------------------------------------------------
def test_chave_sem_a_classe_no_escopo_nao_le_a_cadeia(cliente_b3, tmp_path):
    """Escopo por classe: um app novo é chave nova, não código novo."""
    from app.sinks import SinkDuckDB as S

    s = S(str(tmp_path / "b3.duckdb"))
    restrita = auth.emitir(s, "so_empresa", escopos="classe:empresa")
    s.fechar()
    r = cliente_b3.get(
        "/v1/opcoes/ABCB4", headers={"X-API-Key": restrita.chave_completa}
    )
    assert r.status_code == 403
