"""MyData como relying party do portal semente.id (Fase 2 do ADR-23).

O gesto de login federado não dá para simular sem o portal de verdade — o
que se testa é tudo em volta: PKCE de ponta a ponta contra um id_token
assinado de verdade (gerado aqui como o portal geraria), state de uso
único, e as duas travas de confiança — issuer/audience do token e
`SEMENTE_ID_EMAIL_DONO` como segunda trava sobre o que o portal vouches.
"""
from __future__ import annotations

import time
from urllib.parse import parse_qs, urlparse

import pytest
from authlib.jose import JsonWebKey, jwt

from app.api import semente_id

CLIENT_ID = "mydata-teste"
PORTAL = "https://id.semente.dev"


@pytest.fixture()
def env_semente_id(monkeypatch):
    monkeypatch.setenv("SEMENTE_ID_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("SEMENTE_ID_CLIENT_SECRET", "Testes#12345#")
    monkeypatch.setenv("SEMENTE_ID_URL", PORTAL)
    monkeypatch.setenv("PORTAL_URL_PUBLICA", "https://mydata.acamerini.app")


@pytest.fixture()
def chave_portal():
    return JsonWebKey.generate_key("RSA", 2048, is_private=True)


def _id_token(chave, **extra) -> str:
    agora = int(time.time())
    claims = {
        "iss": PORTAL, "sub": "conta-1", "aud": CLIENT_ID,
        "iat": agora, "exp": agora + 600,
        "email": "alex@example.com", "email_verified": True,
    }
    claims.update(extra)
    return jwt.encode({"alg": "RS256"}, claims, chave).decode()


def _mock_portal(monkeypatch, chave, id_token: str, status_token: int = 200):
    """Substitui `requests.get/post` — a fronteira de rede do módulo."""
    import requests

    class Resposta:
        def __init__(self, dados, status=200):
            self._dados = dados
            self.status_code = status

        def json(self):
            return self._dados

        def raise_for_status(self):
            pass

    def fake_get(url, timeout=None):
        assert url == f"{PORTAL}/jwks"
        publica = chave.as_dict(is_private=False)
        return Resposta({"keys": [publica]})

    def fake_post(url, data=None, timeout=None):
        assert url == f"{PORTAL}/token"
        assert data["grant_type"] == "authorization_code"
        assert data["client_id"] == CLIENT_ID
        return Resposta({"id_token": id_token}, status=status_token)

    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setattr(requests, "post", fake_post)


# --------------------------------------------------------------------------
# configurado()
# --------------------------------------------------------------------------
def test_sem_client_id_e_secret_nao_esta_configurado(monkeypatch, sink):
    monkeypatch.delenv("SEMENTE_ID_CLIENT_ID", raising=False)
    monkeypatch.delenv("SEMENTE_ID_CLIENT_SECRET", raising=False)
    assert semente_id.configurado() is False


def test_com_as_duas_variaveis_esta_configurado(env_semente_id, sink):
    assert semente_id.configurado() is True


# --------------------------------------------------------------------------
# iniciar_login — PKCE de ponta, state gravado
# --------------------------------------------------------------------------
def test_iniciar_login_monta_url_com_pkce_e_grava_o_fluxo(env_semente_id, sink):
    url = semente_id.iniciar_login(sink, "/admin/")
    q = parse_qs(urlparse(url).query)
    assert q["client_id"] == [CLIENT_ID]
    assert q["response_type"] == ["code"]
    assert q["code_challenge_method"] == ["S256"]
    assert "code_challenge" in q and "state" in q and "nonce" in q

    linha = sink.um(
        "SELECT * FROM fluxo_semente_id WHERE state = ?", (q["state"][0],))
    assert linha is not None
    assert linha["destino"] == "/admin/"
    assert linha["nonce"] == q["nonce"][0]


# --------------------------------------------------------------------------
# concluir_login — o ciclo completo
# --------------------------------------------------------------------------
def test_concluir_login_feliz_devolve_email_e_destino(
    env_semente_id, sink, chave_portal, monkeypatch,
):
    url = semente_id.iniciar_login(sink, "/admin/")
    state = parse_qs(urlparse(url).query)["state"][0]
    nonce = parse_qs(urlparse(url).query)["nonce"][0]
    _mock_portal(monkeypatch, chave_portal, _id_token(chave_portal, nonce=nonce))

    email, destino = semente_id.concluir_login(sink, state, "code-falso", None)
    assert email == "alex@example.com"
    assert destino == "/admin/"

    # State é de uso único.
    assert sink.um(
        "SELECT count(*) AS n FROM fluxo_semente_id WHERE state = ?",
        (state,))["n"] == 0


def test_state_desconhecido_falha(env_semente_id, sink):
    with pytest.raises(semente_id.ErroSementeId):
        semente_id.concluir_login(sink, "inventado", "code", None)


def test_erro_do_portal_consome_o_fluxo_e_falha(env_semente_id, sink):
    url = semente_id.iniciar_login(sink, "/admin/")
    state = parse_qs(urlparse(url).query)["state"][0]
    with pytest.raises(semente_id.ErroSementeId):
        semente_id.concluir_login(sink, state, None, "access_denied")
    assert sink.um(
        "SELECT count(*) AS n FROM fluxo_semente_id WHERE state = ?",
        (state,))["n"] == 0


def test_nonce_errado_falha(env_semente_id, sink, chave_portal, monkeypatch):
    url = semente_id.iniciar_login(sink, "/admin/")
    state = parse_qs(urlparse(url).query)["state"][0]
    _mock_portal(monkeypatch, chave_portal,
                 _id_token(chave_portal, nonce="outro-nonce"))
    with pytest.raises(semente_id.ErroSementeId):
        semente_id.concluir_login(sink, state, "code-falso", None)


def test_issuer_diferente_falha(env_semente_id, sink, chave_portal, monkeypatch):
    url = semente_id.iniciar_login(sink, "/admin/")
    state = parse_qs(urlparse(url).query)["state"][0]
    nonce = parse_qs(urlparse(url).query)["nonce"][0]
    _mock_portal(monkeypatch, chave_portal,
                 _id_token(chave_portal, nonce=nonce, iss="https://mal.example"))
    with pytest.raises(semente_id.ErroSementeId):
        semente_id.concluir_login(sink, state, "code-falso", None)


def test_email_nao_verificado_falha(env_semente_id, sink, chave_portal, monkeypatch):
    url = semente_id.iniciar_login(sink, "/admin/")
    state = parse_qs(urlparse(url).query)["state"][0]
    nonce = parse_qs(urlparse(url).query)["nonce"][0]
    _mock_portal(monkeypatch, chave_portal,
                 _id_token(chave_portal, nonce=nonce, email_verified=False))
    with pytest.raises(semente_id.ErroSementeId):
        semente_id.concluir_login(sink, state, "code-falso", None)


def test_email_dono_restringe_quando_definido(
    env_semente_id, sink, chave_portal, monkeypatch,
):
    monkeypatch.setenv("SEMENTE_ID_EMAIL_DONO", "outro@example.com")
    url = semente_id.iniciar_login(sink, "/admin/")
    state = parse_qs(urlparse(url).query)["state"][0]
    nonce = parse_qs(urlparse(url).query)["nonce"][0]
    _mock_portal(monkeypatch, chave_portal, _id_token(chave_portal, nonce=nonce))
    with pytest.raises(semente_id.ErroSementeId):
        semente_id.concluir_login(sink, state, "code-falso", None)


def test_email_dono_deixa_passar_quando_confere(
    env_semente_id, sink, chave_portal, monkeypatch,
):
    monkeypatch.setenv("SEMENTE_ID_EMAIL_DONO", "Alex@Example.com")
    url = semente_id.iniciar_login(sink, "/admin/")
    state = parse_qs(urlparse(url).query)["state"][0]
    nonce = parse_qs(urlparse(url).query)["nonce"][0]
    _mock_portal(monkeypatch, chave_portal, _id_token(chave_portal, nonce=nonce))
    email, _ = semente_id.concluir_login(sink, state, "code-falso", None)
    assert email == "alex@example.com"


def test_token_endpoint_recusado_falha(env_semente_id, sink, chave_portal, monkeypatch):
    url = semente_id.iniciar_login(sink, "/admin/")
    state = parse_qs(urlparse(url).query)["state"][0]
    nonce = parse_qs(urlparse(url).query)["nonce"][0]
    _mock_portal(monkeypatch, chave_portal,
                 _id_token(chave_portal, nonce=nonce), status_token=400)
    with pytest.raises(semente_id.ErroSementeId):
        semente_id.concluir_login(sink, state, "code-falso", None)
