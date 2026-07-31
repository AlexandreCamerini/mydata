"""Etapa 7 — o portal mestre no domínio.

Um serviço só ocupa `https://acamerini.app/`: `/v1` para os apps, `/admin`
para o plano de controle, `/health` para o Railway. Os apps vivem em
subdomínios e são consumidores — cada um com sua chave, e o escopo dela diz
quais classes ele lê. App novo é chave nova, não código novo.
"""
from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient

from app import bootstrap, seed_cvm
from app.api import auth
from app.motor import ingestao, publicacao
from app.sinks import SinkDuckDB


def baixador(mapa):
    def _baixar(url: str) -> bytes:
        for chave, dado in mapa.items():
            if chave in url:
                return dado
        raise AssertionError(f"URL não prevista: {url}")
    return _baixar


@pytest.fixture()
def base(tmp_path, monkeypatch, zip_dfp_2023, csv_cadastro):
    banco = str(tmp_path / "mestre.duckdb")
    monkeypatch.setenv("PORTAL_DUCKDB", banco)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("PORTAL_ADMIN_TOKEN", raising=False)
    monkeypatch.delenv("PORTAL_API_ABERTA", raising=False)

    s = SinkDuckDB(banco)
    bootstrap.preparar(s)
    seed_cvm.aplicar(s)
    ingestao.executar(s, "cvm_dfp", "2023",
                      baixar=baixador({"dfp_cia_aberta_2023.zip": zip_dfp_2023}))
    ingestao.executar(s, "cvm_cadastro", "atual",
                      baixar=baixador({"cad_cia_aberta.csv": csv_cadastro}))
    s.fechar()
    return banco


def recarregar_app():
    """A configuração de domínio é lida na importação do módulo."""
    import app.api.main as m

    return importlib.reload(m).app


# --------------------------------------------------------------------------
# Escopo por classe
# --------------------------------------------------------------------------
def test_chave_com_escopo_le_a_classe_que_lhe_cabe(base):
    s = SinkDuckDB(base)
    so_empresa = auth.emitir(s, "watchlist", escopos="classe:empresa")
    s.fechar()

    from app.api.main import app

    with TestClient(app) as c:
        cab = {"X-API-Key": so_empresa.chave_completa}
        assert c.get("/v1/empresas", headers=cab).status_code == 200


def test_chave_com_escopo_e_barrada_fora_dele(base):
    """O ponto do escopo: um app de watchlist não precisa de demonstração
    financeira, e não deve conseguir lê-la só por ter uma chave válida."""
    s = SinkDuckDB(base)
    so_empresa = auth.emitir(s, "watchlist", escopos="classe:empresa")
    s.fechar()

    from app.api.main import app

    with TestClient(app) as c:
        r = c.get("/v1/empresas/9512/demonstracoes",
                  headers={"X-API-Key": so_empresa.chave_completa})
    assert r.status_code == 403
    assert r.json()["erro"]["codigo"] == "escopo_insuficiente"
    assert "demonstracao_financeira" in r.json()["erro"]["mensagem"]


def test_chave_de_leitura_ampla_continua_lendo_tudo(base):
    """Chave já emitida diz `leitura`. Introduzir escopo não pode revogá-la."""
    s = SinkDuckDB(base)
    ampla = auth.emitir(s, "bolsia")
    s.fechar()

    from app.api.main import app

    with TestClient(app) as c:
        cab = {"X-API-Key": ampla.chave_completa}
        assert c.get("/v1/empresas", headers=cab).status_code == 200
        assert c.get("/v1/empresas/9512/demonstracoes", headers=cab).status_code == 200


def test_escopo_e_declarado_em_classe_nao_em_vista():
    chave = {"consumidor": "x", "escopos": "classe:empresa,classe:cotacao"}
    assert auth.classes_permitidas(chave) == {"empresa", "cotacao"}
    assert auth.pode_ler(chave, "empresa") is True
    assert auth.pode_ler(chave, "demonstracao_financeira") is False
    assert auth.pode_ler({"escopos": "leitura"}, "qualquer_coisa") is True


def test_vista_gerada_resolve_para_a_classe(base):
    """`gold_empresa` é gerada, não está em cfg_vista: o escopo tem de
    reconhecê-la mesmo assim, senão a classe multi-fonte fica sem porteiro."""
    s = SinkDuckDB(base)
    assert publicacao.classe_da_vista(s, "gold_empresa") == "empresa"
    assert publicacao.classe_da_vista(s, "gold_demonstracoes") == "demonstracao_financeira"
    assert publicacao.classe_da_vista(s, "gold_inexistente") is None
    s.fechar()


def test_emitir_chave_com_classe_inexistente_e_recusado(base):
    from app.api.main import app

    with TestClient(app) as c:
        r = c.post("/admin/api/chaves",
                   json={"consumidor": "novo", "classes": ["nao_existe"]})
    assert r.status_code == 422
    assert r.json()["erro"]["codigo"] == "classe_desconhecida"


def test_app_novo_e_chave_nova_nao_codigo_novo(base):
    """O critério de aceite do portal mestre, escrito como teste."""
    from app.api.main import app

    with TestClient(app) as c:
        r = c.post("/admin/api/chaves", json={
            "consumidor": "app-carteira", "classes": ["empresa"],
        })
        assert r.status_code == 200, r.text
        emitida = r.json()["dados"]
        assert emitida["escopos"] == "classe:empresa"
        cab = {"X-API-Key": emitida["chave"]}
        assert c.get("/v1/empresas", headers=cab).status_code == 200
        assert c.get("/v1/empresas/9512/demonstracoes",
                     headers=cab).status_code == 403


# --------------------------------------------------------------------------
# Domínio público
# --------------------------------------------------------------------------
def test_openapi_anuncia_a_url_publica(base, monkeypatch):
    """Sem isto, o cliente gerado a partir do schema aponta para localhost."""
    monkeypatch.setenv("PORTAL_URL_PUBLICA", "https://acamerini.app")
    app = recarregar_app()
    with TestClient(app) as c:
        schema = c.get("/openapi.json").json()
    assert schema["servers"] == [
        {"url": "https://acamerini.app", "description": "produção"}
    ]


def test_sem_url_publica_o_schema_nao_inventa_servidor(base, monkeypatch):
    monkeypatch.delenv("PORTAL_URL_PUBLICA", raising=False)
    app = recarregar_app()
    with TestClient(app) as c:
        schema = c.get("/openapi.json").json()
    assert "servers" not in schema or not schema["servers"]


def test_cors_libera_o_subdominio_declarado(base, monkeypatch):
    monkeypatch.setenv("PORTAL_ORIGENS", "https://bolsia.acamerini.app")
    app = recarregar_app()
    with TestClient(app) as c:
        r = c.options("/v1/empresas", headers={
            "Origin": "https://bolsia.acamerini.app",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "X-API-Key",
        })
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "https://bolsia.acamerini.app"


def test_cors_nega_origem_nao_declarada(base, monkeypatch):
    monkeypatch.setenv("PORTAL_ORIGENS", "https://bolsia.acamerini.app")
    app = recarregar_app()
    with TestClient(app) as c:
        r = c.get("/v1/empresas", headers={"Origin": "https://site-qualquer.com"})
    assert "access-control-allow-origin" not in r.headers


def test_sem_origens_declaradas_nenhuma_origem_cruzada_passa(base, monkeypatch):
    """Negar por omissão. Liberar `*` por conveniência de desenvolvimento é
    o tipo de default que sobrevive até produção."""
    monkeypatch.delenv("PORTAL_ORIGENS", raising=False)
    app = recarregar_app()
    with TestClient(app) as c:
        r = c.get("/health", headers={"Origin": "https://site-qualquer.com"})
    assert "access-control-allow-origin" not in r.headers


def test_health_continua_sem_chave_e_sem_banco(base):
    """O healthcheck do Railway não pode depender de chave nem de banco."""
    app = recarregar_app()
    with TestClient(app) as c:
        assert c.get("/health").status_code == 200
