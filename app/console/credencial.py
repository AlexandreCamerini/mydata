"""Token de máquina da console (OAuth2 `client_credentials`, RFC 6749 §4.4).

A console é um cliente do semente.id: troca `CONSOLE_CLIENT_ID` /
`CONSOLE_CLIENT_SECRET` por um access token com `aud` restrito ao recurso
que vai chamar (`resource`, RFC 8707 — exatamente um por pedido). Nada aqui
escreve em serviço monitorado: o endpoint de token é o segundo e último
POST permitido do pacote (o outro é o GraphQL de leitura do Railway; o
guardião em `tests/test_console.py` prova os dois).

Regras de higiene:
- as variáveis são lidas na hora da chamada, nunca no import;
- o segredo só viaja no HTTP Basic do pedido — nunca em URL, log nem em
  mensagem de erro (`ErroCredencial` carrega só um código curto);
- cache em memória por recurso, protegido por lock (o coletor roda em
  `asyncio.to_thread`, então há mais de uma thread); sem `expires_in`
  legível, não cacheia.
"""
from __future__ import annotations

import math
import os
import threading
import time
from typing import Any

TOKEN_URL_PADRAO = "https://id.semente.dev/token"
TIMEOUT_TOKEN = 5.0
# Renova quando faltarem menos que isto para o token vencer.
MARGEM_RENOVACAO_S = 60.0

# Relógio monotônico do cache — trocável nos testes (monkeypatch), pois o
# vencimento é a parte que só se prova avançando o tempo.
_relogio = time.monotonic

_trava = threading.Lock()
# recurso -> (access_token, instante monotônico de vencimento)
_cache: dict[str, tuple[str, float]] = {}


class ErroCredencial(Exception):
    """Falha ao obter o token. `codigo` é curto e seguro para gravar em
    `console_coleta.erro`: `token_http_<status>`, `token_rede` ou
    `token_invalido`."""

    def __init__(self, codigo: str):
        super().__init__(codigo)
        self.codigo = codigo


def _client() -> tuple[str, str] | None:
    client_id = (os.getenv("CONSOLE_CLIENT_ID") or "").strip()
    segredo = os.getenv("CONSOLE_CLIENT_SECRET") or ""
    if not client_id or not segredo.strip():
        return None
    return client_id, segredo


def client_configurado() -> bool:
    """`True` quando id e segredo estão presentes (sem chamar rede)."""
    return _client() is not None


def _url_do_token() -> str:
    return (os.getenv("CONSOLE_ID_TOKEN_URL") or "").strip() or TOKEN_URL_PADRAO


def _segundos_de_vida(corpo: dict) -> float | None:
    """`expires_in` como número positivo e finito, ou `None` (ausente ou
    ilegível — nesse caso o token não é cacheado)."""
    bruto = corpo.get("expires_in")
    if bruto is None or isinstance(bruto, bool):
        return None
    try:
        valor = float(bruto)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(valor) or valor <= 0:
        return None
    return valor


def _pedir_token(recurso: str, transporte, client: tuple[str, str]) -> tuple[str, float | None]:
    data = {"grant_type": "client_credentials", "resource": recurso}
    try:
        resp = transporte.post_form(
            _url_do_token(), data=data, auth=client, timeout=TIMEOUT_TOKEN,
        )
    except Exception:
        # Sem `from e` e sem texto da exceção: o código basta, e nada do
        # pedido (que carrega o segredo) volta em mensagem.
        raise ErroCredencial("token_rede") from None
    if resp.status_code != 200:
        raise ErroCredencial(f"token_http_{resp.status_code}")
    try:
        corpo: Any = resp.json()
    except Exception:
        raise ErroCredencial("token_invalido") from None
    if not isinstance(corpo, dict):
        raise ErroCredencial("token_invalido")
    token = corpo.get("access_token")
    if not isinstance(token, str) or not token.strip():
        raise ErroCredencial("token_invalido")
    return token, _segundos_de_vida(corpo)


def token_para(recurso: str, transporte) -> str | None:
    """Access token para `recurso`, do cache ou recém-pedido.

    `None` quando `CONSOLE_CLIENT_ID`/`CONSOLE_CLIENT_SECRET` não estão
    configurados (a origem decide o que fazer). Falha do endpoint de token
    levanta `ErroCredencial`. Uma tentativa só — sem retentativa.
    """
    client = _client()
    if client is None:
        return None
    with _trava:
        agora = _relogio()
        guardado = _cache.get(recurso)
        if guardado is not None and guardado[1] - agora >= MARGEM_RENOVACAO_S:
            return guardado[0]
        # Segurar a trava durante o POST evita que duas threads peçam o
        # mesmo token ao mesmo tempo; o custo é no máximo 5 s de espera.
        token, vida = _pedir_token(recurso, transporte, client)
        if vida is None:
            _cache.pop(recurso, None)
        else:
            _cache[recurso] = (token, agora + vida)
        return token


def invalidar(recurso: str) -> None:
    """Esquece o token de `recurso` (ex.: o recurso respondeu 401)."""
    with _trava:
        _cache.pop(recurso, None)


def limpar_cache() -> None:
    """Esvazia o cache inteiro — uso em testes."""
    with _trava:
        _cache.clear()
