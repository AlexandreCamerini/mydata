"""O ciclo HTTP completo: /entrar/semente-id → volta do portal → admin
aberto — o aceite da Fase 2 do ADR-23 ("login pelo portal abre o admin do
MyData de ponta a ponta"), exercitado pela rota real, não só pela função.
"""
from __future__ import annotations

import time
from urllib.parse import parse_qs, quote, urlparse

import pytest
from authlib.jose import JsonWebKey, jwt
from fastapi.testclient import TestClient

from app import bootstrap, seed_fontes
from app.sinks import SinkDuckDB

CLIENT_ID = "mydata-teste"
PORTAL = "https://id.semente.dev"


@pytest.fixture()
def chave_portal():
    return JsonWebKey.generate_key("RSA", 2048, is_private=True)


@pytest.fixture()
def cliente(tmp_path, monkeypatch, chave_portal):
    monkeypatch.setenv("PORTAL_DUCKDB", str(tmp_path / "sessao.duckdb"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    # Um PORTAL_ADMIN_TOKEN precisa existir para a raiz gatear e mostrar a
    # tela de entrar — é nela que o botão do semente.id aparece. O token em
    # si não é usado nestes testes: o caminho exercitado é o federado.
    monkeypatch.setenv("PORTAL_ADMIN_TOKEN", "token-nao-usado-nesta-suite")
    monkeypatch.setenv("SEMENTE_ID_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("SEMENTE_ID_CLIENT_SECRET", "segredo-teste")
    monkeypatch.setenv("SEMENTE_ID_URL", PORTAL)
    monkeypatch.setenv("PORTAL_URL_PUBLICA", "http://testserver")

    s = SinkDuckDB(str(tmp_path / "sessao.duckdb"))
    bootstrap.preparar(s)
    seed_fontes.aplicar(s)
    s.fechar()

    from app.api.main import app
    with TestClient(app) as c:
        yield c


def _id_token(chave, **extra) -> str:
    agora = int(time.time())
    claims = {
        "iss": PORTAL, "sub": "conta-1", "aud": CLIENT_ID,
        "iat": agora, "exp": agora + 600,
        "email": "alex@example.com", "email_verified": True,
    }
    claims.update(extra)
    return jwt.encode({"alg": "RS256"}, claims, chave).decode()


def _mock_portal(monkeypatch, chave, id_token):
    import requests

    class Resposta:
        def __init__(self, dados, status=200):
            self._dados, self.status_code = dados, status

        def json(self):
            return self._dados

        def raise_for_status(self):
            pass

    monkeypatch.setattr(
        requests, "get",
        lambda url, timeout=None: Resposta(
            {"keys": [chave.as_dict(is_private=False)]}))
    monkeypatch.setattr(
        requests, "post",
        lambda url, data=None, timeout=None: Resposta({"id_token": id_token}))


def test_login_pelo_portal_abre_a_administracao_de_ponta_a_ponta(
    cliente, chave_portal, monkeypatch,
):
    r = cliente.get("/entrar/semente-id?destino=/admin/", follow_redirects=False)
    assert r.status_code == 302
    q = parse_qs(urlparse(r.headers["location"]).query)
    assert q["client_id"] == [CLIENT_ID]

    _mock_portal(monkeypatch, chave_portal,
                 _id_token(chave_portal, nonce=q["nonce"][0]))
    r = cliente.get(f"/callback/semente-id?state={q['state'][0]}&code=x",
                    follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/admin/"
    assert "portal_sessao" in cliente.cookies

    r = cliente.get("/admin/api/gestao")
    assert r.status_code == 200
    assert "classes" in r.json()["dados"]


def test_erro_do_portal_no_callback_mostra_a_tela_de_entrar(cliente):
    r = cliente.get("/entrar/semente-id?destino=/admin/", follow_redirects=False)
    state = parse_qs(urlparse(r.headers["location"]).query)["state"][0]
    r = cliente.get(f"/callback/semente-id?state={state}&error=access_denied")
    assert r.status_code == 401
    assert "portal_sessao" not in r.cookies


def test_destino_com_rota_de_hash_sobrevive_ao_link_do_semente_id(
    cliente, chave_portal, monkeypatch,
):
    # Rota real do admin (roteamento por hash): sem url-encode no `href`,
    # o navegador cortaria a query no `#` e o servidor nunca veria o que
    # vem depois — foi exatamente o bug relatado (login pelo semente.id
    # sempre voltava para a raiz do admin, nunca para a página pedida).
    destino_completo = "/admin/#/empresa/9512"
    r = cliente.get(f"/?destino={quote(destino_completo, safe='')}")
    assert quote(destino_completo, safe="") in r.text
    assert f'destino={destino_completo}"' not in r.text

    r = cliente.get(
        f"/entrar/semente-id?destino={quote(destino_completo, safe='')}",
        follow_redirects=False,
    )
    assert r.status_code == 302
    q = parse_qs(urlparse(r.headers["location"]).query)

    _mock_portal(monkeypatch, chave_portal,
                 _id_token(chave_portal, nonce=q["nonce"][0]))
    r = cliente.get(f"/callback/semente-id?state={q['state'][0]}&code=x",
                    follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == destino_completo


def test_botao_so_aparece_com_as_variaveis_definidas(cliente, monkeypatch):
    r = cliente.get("/")
    assert "semente.dev" in r.text

    monkeypatch.delenv("SEMENTE_ID_CLIENT_ID")
    r = cliente.get("/")
    assert "semente.dev" not in r.text
    # E a rota de início do fluxo se recusa, em vez de tentar sem client_id.
    r = cliente.get("/entrar/semente-id", follow_redirects=False)
    assert r.status_code == 401
