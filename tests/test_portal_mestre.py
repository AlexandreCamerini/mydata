"""Etapa 7 — o portal mestre no domínio.

Um serviço só ocupa `https://mydata.acamerini.app/`: `/v1` para os apps,
`/admin` para o plano de controle, `/health` para o Railway.

O MyData ocupa subdomínio próprio, nunca o ápice: ele serve vários sistemas e
o ápice pertence a outro. A URL sai de `PORTAL_URL_PUBLICA` e de lugar nenhum
mais — migrar para um domínio registrado à parte é trocar a variável e o DNS.

Cada app consumidor tem sua chave, e o escopo dela diz quais classes ele lê.
App novo é chave nova, não código novo.
"""
from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient

from app import bootstrap, seed_fontes
from app.api import auth
from app.motor import ingestao, publicacao
from app.sinks import SinkDuckDB


def baixador(mapa):
    def _baixar(url: str, cabecalhos=None) -> bytes:
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
    seed_fontes.aplicar(s)
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


def test_emissao_publica_tem_escopo_e_quota_travados(base):
    from app.api.main import ESCOPOS_PUBLICOS, app

    with TestClient(app) as c:
        vazio = c.post("/v1/chaves", json={"consumidor": "   "})
        assert vazio.status_code == 422
        assert vazio.json()["erro"]["codigo"] == "entrada_invalida"

        primeira = c.post(
            "/v1/chaves",
            json={
                "consumidor": "app-publico",
                "classes": ["negociacao_b3"],
                "escopos": "leitura,fonte:b3",
            },
        )
        assert primeira.status_code == 200, primeira.text
        dados = primeira.json()["dados"]
        assert dados["escopos"] == ESCOPOS_PUBLICOS

        linha = app.state.sink.um(
            "SELECT quota_minuto, quota_dia, escopos FROM cfg_chave_api "
            "WHERE prefixo = ?",
            (dados["prefixo"],),
        )
        assert (linha["quota_minuto"], linha["quota_dia"], linha["escopos"]) == (
            30, 2000, ESCOPOS_PUBLICOS,
        )

        for numero in range(2, 6):
            resposta = c.post(
                "/v1/chaves", json={"consumidor": f"app-publico-{numero}"}
            )
            assert resposta.status_code == 200, resposta.text

        sexta = c.post("/v1/chaves", json={"consumidor": "app-publico-6"})
        assert sexta.status_code == 429
        assert sexta.json()["erro"]["codigo"] == "quota_excedida"


# --------------------------------------------------------------------------
# Domínio público
# --------------------------------------------------------------------------
def test_openapi_anuncia_a_url_publica(base, monkeypatch):
    """Sem isto, o cliente gerado a partir do schema aponta para localhost."""
    monkeypatch.setenv("PORTAL_URL_PUBLICA", "https://mydata.acamerini.app")
    app = recarregar_app()
    with TestClient(app) as c:
        schema = c.get("/openapi.json").json()
    assert schema["servers"] == [
        {"url": "https://mydata.acamerini.app", "description": "produção"}
    ]


def test_sem_url_publica_o_schema_nao_inventa_servidor(base, monkeypatch):
    monkeypatch.delenv("PORTAL_URL_PUBLICA", raising=False)
    app = recarregar_app()
    with TestClient(app) as c:
        schema = c.get("/openapi.json").json()
    assert "servers" not in schema or not schema["servers"]


def test_cors_libera_o_subdominio_declarado(base, monkeypatch):
    monkeypatch.setenv("PORTAL_ORIGENS", "https://consumidor.exemplo.app")
    app = recarregar_app()
    with TestClient(app) as c:
        r = c.options("/v1/empresas", headers={
            "Origin": "https://consumidor.exemplo.app",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "X-API-Key",
        })
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "https://consumidor.exemplo.app"


def test_cors_nega_origem_nao_declarada(base, monkeypatch):
    monkeypatch.setenv("PORTAL_ORIGENS", "https://consumidor.exemplo.app")
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


# --------------------------------------------------------------------------
# Plano de controle
# --------------------------------------------------------------------------
def test_admin_exige_token_para_ler_tambem(base, monkeypatch):
    """Com PORTAL_ADMIN_TOKEN definido, *ler* o plano de controle também exige
    o token.

    Encontrado em produção: o token protegia só a escrita, e
    `/admin/api/catalogo/{tabela}` devolvia amostra de qualquer tabela sem
    autenticação nenhuma — contornando de uma vez o escopo por classe das
    chaves de API.
    """
    monkeypatch.setenv("PORTAL_ADMIN_TOKEN", "segredo-de-teste")
    app = recarregar_app()
    with TestClient(app) as c:
        for caminho in ("/admin/api/classes", "/admin/api/execucoes",
                        "/admin/api/frescor", "/admin/api/catalogo",
                        "/admin/api/catalogo/dim_empresa"):
            r = c.get(caminho)
            assert r.status_code == 401, f"{caminho} respondeu {r.status_code}"

        cab = {"X-Admin-Token": "segredo-de-teste"}
        assert c.get("/admin/api/classes", headers=cab).status_code == 200


def test_sem_token_configurado_o_admin_fica_aberto_para_dev(base, monkeypatch):
    """O modo local não pode exigir token: a ausência da variável é a escolha."""
    monkeypatch.delenv("PORTAL_ADMIN_TOKEN", raising=False)
    app = recarregar_app()
    with TestClient(app) as c:
        assert c.get("/admin/api/classes").status_code == 200
