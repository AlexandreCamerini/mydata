"""O MyData como relying party do portal semente.id (Fase 2 do ADR-23).

Terceiro caminho de entrada, ao lado do token e do passkey — nunca no lugar
deles, mesmo princípio do ADR-19: um sistema novo entra somando, e a
verificação de que ele funciona vem antes de qualquer um dos dois antigos
sair de cena. A sessão que abre aqui é a mesma `sessao_admin` de sempre; só
a origem muda.

Authorization Code + PKCE contra o portal, como qualquer relying party do
protocolo. `SEMENTE_ID_EMAIL_DONO`, se definida, é a segunda trava: o portal
é multiusuário por natureza (outros sistemas do portfólio o compartilham),
e o MyData continua sendo admin de dono único — o portal vouches pelo email,
o MyData decide se aquele email abre *esta* administração.
"""
from __future__ import annotations

import base64
import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import requests

from ..sinks import Sink

MINUTOS_DE_FLUXO = 10


class ErroSementeId(Exception):
    """A federação falhou. Mensagem para humano."""


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def configurado() -> bool:
    return bool(os.getenv("SEMENTE_ID_CLIENT_ID")
                and os.getenv("SEMENTE_ID_CLIENT_SECRET"))


def _url_portal() -> str:
    return os.getenv("SEMENTE_ID_URL", "https://id.semente.dev").rstrip("/")


def _url_callback() -> str:
    publica = os.getenv("PORTAL_URL_PUBLICA", "").strip().rstrip("/")
    return f"{publica or 'http://localhost:8420'}/callback/semente-id"


def _s256(verifier: str) -> str:
    resumo = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(resumo).rstrip(b"=").decode()


def iniciar_login(sink: Sink, destino: str) -> str:
    """Guarda o estado do fluxo e devolve a URL de autorização do portal."""
    verifier = secrets.token_urlsafe(48)
    state = secrets.token_urlsafe(24)
    nonce = secrets.token_urlsafe(16)
    sink.executar(
        "DELETE FROM fluxo_semente_id WHERE criado_em < ?",
        (_agora() - timedelta(minutes=MINUTOS_DE_FLUXO),),
    )
    sink.executar(
        "INSERT INTO fluxo_semente_id (state, code_verifier, nonce, destino) "
        "VALUES (?,?,?,?)",
        (state, verifier, nonce, destino),
    )
    params = {
        "client_id": os.environ["SEMENTE_ID_CLIENT_ID"],
        "redirect_uri": _url_callback(),
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "nonce": nonce,
        "code_challenge": _s256(verifier),
        "code_challenge_method": "S256",
    }
    return f"{_url_portal()}/authorize?" + urlencode(params)


def _validar_id_token(id_token: str, nonce_esperado: str) -> dict:
    from authlib.jose import JsonWebKey, jwt

    resposta = requests.get(f"{_url_portal()}/jwks", timeout=15)
    resposta.raise_for_status()
    chaves = JsonWebKey.import_key_set(resposta.json())
    try:
        claims = jwt.decode(id_token, chaves)
        claims.validate()
    except Exception as e:
        raise ErroSementeId(
            "O token de identidade do portal não pôde ser validado.") from e
    if claims.get("iss") != _url_portal():
        raise ErroSementeId("Issuer inesperado no token de identidade.")
    if claims.get("aud") != os.environ["SEMENTE_ID_CLIENT_ID"]:
        raise ErroSementeId("Audience inesperada no token de identidade.")
    if nonce_esperado and claims.get("nonce") != nonce_esperado:
        raise ErroSementeId("O nonce do login não confere.")
    return claims


def concluir_login(sink: Sink, state: str | None, code: str | None,
                   erro_do_portal: str | None) -> tuple[str, str]:
    """Troca o code, valida o id_token e devolve (email, destino).

    O estado é consumido mesmo quando o portal recusou (`erro_do_portal`):
    um fluxo abortado não deve continuar vivo para uma segunda tentativa com
    o mesmo state.
    """
    linha = sink.um(
        "SELECT * FROM fluxo_semente_id WHERE state = ?", (state or "",))
    if linha is not None:
        sink.executar(
            "DELETE FROM fluxo_semente_id WHERE state = ?", (state,))
    if erro_do_portal:
        raise ErroSementeId(f"O portal recusou: {erro_do_portal}")
    if linha is None:
        raise ErroSementeId(
            "Fluxo de login não encontrado ou vencido. Tente de novo.")
    if not code:
        raise ErroSementeId("O portal não devolveu um código de autorização.")

    resposta = requests.post(f"{_url_portal()}/token", data={
        "grant_type": "authorization_code", "code": code,
        "redirect_uri": _url_callback(), "code_verifier": linha["code_verifier"],
        "client_id": os.environ["SEMENTE_ID_CLIENT_ID"],
        "client_secret": os.environ["SEMENTE_ID_CLIENT_SECRET"],
    }, timeout=15)
    if resposta.status_code != 200:
        raise ErroSementeId("O portal recusou a troca do código de autorização.")
    id_token = resposta.json().get("id_token", "")

    claims = _validar_id_token(id_token, linha["nonce"])
    if not claims.get("email_verified") or not claims.get("email"):
        raise ErroSementeId("O portal não confirmou um email verificado.")

    dono = os.getenv("SEMENTE_ID_EMAIL_DONO", "").strip().lower()
    email = str(claims["email"]).strip().lower()
    if dono and email != dono:
        raise ErroSementeId(
            "Esta conta do portal não tem acesso a esta administração.")
    return email, linha["destino"]
