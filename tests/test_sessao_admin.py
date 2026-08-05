"""Uma sessão só para as duas superfícies.

`/entrar` sempre emitiu um cookie, e ele servia à apresentação. A
administração aceitava apenas o cabeçalho `X-Admin-Token`, que a interface lia
do `localStorage` — e nada preenchia o `localStorage`, porque não havia tela de
login no /admin. Na prática, entrar na configuração exigia abrir o console do
navegador.

Aceitar o cookie nas duas fecha isso sem criar credencial nova. O cabeçalho
continua valendo para `curl` e script, que não têm cookie.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import bootstrap, seed_cvm
from app.api import auth
from app.sinks import SinkDuckDB

TOKEN = "token-de-teste-com-tamanho-razoavel"


@pytest.fixture()
def cliente_com_token(tmp_path, monkeypatch):
    monkeypatch.setenv("PORTAL_DUCKDB", str(tmp_path / "sessao.duckdb"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("PORTAL_ADMIN_TOKEN", TOKEN)

    s = SinkDuckDB(str(tmp_path / "sessao.duckdb"))
    bootstrap.preparar(s)
    seed_cvm.aplicar(s)
    s.fechar()

    from app.api.main import app

    with TestClient(app) as c:
        yield c


# --------------------------------------------------------------------------
# As duas portas
# --------------------------------------------------------------------------
def test_sem_credencial_a_administracao_recusa(cliente_com_token):
    r = cliente_com_token.get("/admin/api/gestao")
    assert r.status_code == 401
    assert r.json()["erro"]["codigo"] == "admin_nao_autorizado"
    # A mensagem diz o que fazer, e as duas formas de fazer.
    assert "Entre em /" in r.json()["erro"]["mensagem"]


def test_o_cabecalho_continua_valendo(cliente_com_token):
    """É o caminho de `curl` e de script, que não têm cookie."""
    r = cliente_com_token.get(
        "/admin/api/gestao", headers={"X-Admin-Token": TOKEN}
    )
    assert r.status_code == 200


def test_a_sessao_de_entrar_abre_a_administracao(cliente_com_token):
    """O conserto: entrar uma vez em `/` passa a valer para o /admin."""
    r = cliente_com_token.post(
        "/entrar", data={"token": TOKEN}, follow_redirects=False
    )
    assert r.status_code == 303
    assert auth.COOKIE_SESSAO in r.cookies

    # O TestClient guarda o cookie; nenhuma credencial vai no cabeçalho.
    r = cliente_com_token.get("/admin/api/gestao")
    assert r.status_code == 200
    assert "classes" in r.json()["dados"]


def test_sair_fecha_as_duas(cliente_com_token):
    cliente_com_token.post("/entrar", data={"token": TOKEN},
                           follow_redirects=False)
    assert cliente_com_token.get("/admin/api/gestao").status_code == 200
    cliente_com_token.get("/sair", follow_redirects=False)
    assert cliente_com_token.get("/admin/api/gestao").status_code == 401


def test_token_errado_nao_abre_nada(cliente_com_token):
    r = cliente_com_token.post(
        "/entrar", data={"token": "chute"}, follow_redirects=False
    )
    assert r.status_code == 401
    assert auth.COOKIE_SESSAO not in r.cookies
    assert cliente_com_token.get("/admin/api/gestao").status_code == 401


# --------------------------------------------------------------------------
# A volta para onde se estava
# --------------------------------------------------------------------------
def test_entrar_devolve_ao_destino_pedido(cliente_com_token):
    r = cliente_com_token.post(
        "/entrar", data={"token": TOKEN, "destino": "/admin/#/carga"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/admin/#/carga"


def test_a_pagina_de_login_carrega_o_destino_no_formulario(cliente_com_token):
    r = cliente_com_token.get("/?destino=/admin/")
    assert r.status_code == 401
    assert 'name="destino" value="/admin/"' in r.text
    assert "A administração é privada" in r.text


@pytest.mark.parametrize("hostil", [
    "//exemplo.com",
    "https://exemplo.com/roubo",
    "javascript:alert(1)",
    "",
    None,
])
def test_destino_para_fora_do_site_e_recusado(hostil):
    """`//exemplo.com` é URL absoluta protocolo-relativa. Sem esta checagem,
    um link com `?destino=//exemplo.com` faria o login mandar o dono para
    fora logo depois de ele digitar o token."""
    from app.api.main import destino_local

    assert destino_local(hostil) == "/"


def test_destino_local_passa():
    from app.api.main import destino_local

    assert destino_local("/admin/") == "/admin/"
    assert destino_local("/admin/#/carga") == "/admin/#/carga"


# --------------------------------------------------------------------------
# O que não pode ter mudado
# --------------------------------------------------------------------------
def test_sem_token_configurado_a_administracao_fica_aberta(tmp_path, monkeypatch):
    """Modo de desenvolvimento local: a ausência da variável é escolha
    explícita, e continua valendo."""
    monkeypatch.setenv("PORTAL_DUCKDB", str(tmp_path / "aberta.duckdb"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("PORTAL_ADMIN_TOKEN", raising=False)

    s = SinkDuckDB(str(tmp_path / "aberta.duckdb"))
    bootstrap.preparar(s)
    seed_cvm.aplicar(s)
    s.fechar()

    from app.api.main import app

    with TestClient(app) as c:
        assert c.get("/admin/api/gestao").status_code == 200


def test_a_sessao_nao_serve_de_chave_de_api_para_terceiro(cliente_com_token):
    """A sessão lê /v1 como o dono. Isso é deliberado — mas não pode virar
    uma chave que qualquer um usa: sem cookie e sem chave, /v1 recusa."""
    assert cliente_com_token.get("/v1/empresas").status_code == 401
    cliente_com_token.post("/entrar", data={"token": TOKEN},
                           follow_redirects=False)
    assert cliente_com_token.get("/v1/empresas").status_code == 200
