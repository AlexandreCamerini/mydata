"""A camada de acesso humana: sessão, passkey e o token que continua valendo.

Implementa o [ADR-19](../../docs/arquitetura.md#adr-19). O ponto da decisão é
que passkey entra **ao lado** do token, nunca no lugar: enquanto o Alex não
verificar o caminho novo num navegador limpo, tudo que funcionava continua
funcionando. Uma decisão que se desfaz sozinha não precisa de portão.

O que muda de verdade é o que a sessão *é*. Antes o cookie carregava o próprio
`PORTAL_ADMIN_TOKEN`; agora carrega um identificador opaco com linha em
`sessao_admin`. Só assim as três faltas do §5.2 da auditoria somem: identidade
(a origem diz qual autenticador abriu), revogação individual (apagar uma linha
não derruba as outras) e expiração real (no servidor, não só no `max-age`).

O que **não** muda, e está registrado para não se perder por descuido: cookie
`HttpOnly` `SameSite=Lax`, comparação em tempo constante, CORS negado por
omissão, nada em `localStorage`, e `X-Admin-Token` continuando a valer para
`curl` e script — que não têm navegador e portanto não têm passkey.
"""
from __future__ import annotations

import base64
import os
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from ..sinks import Sink

DIAS_DE_SESSAO = 30
# Um desafio serve a um clique. Cinco minutos cobrem quem se distrai no meio
# do gesto e não deixam rastro utilizável.
MINUTOS_DE_DESAFIO = 5


class ErroAcesso(Exception):
    """A tentativa não confere. A mensagem é para humano, não para máquina."""


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def _dt(valor) -> datetime | None:
    """O DuckDB devolve `datetime`; o Postgres também, mas o texto aparece
    quando a linha veio de um `INSERT` com parâmetro em string."""
    if valor is None or isinstance(valor, datetime):
        return valor
    return datetime.fromisoformat(str(valor))


# ---------------------------------------------------------------------------
# Sessão
# ---------------------------------------------------------------------------
def abrir_sessao(sink: Sink, origem: str) -> str:
    """Cria a sessão e devolve o identificador que vai no cookie.

    `origem` é o que dá identidade ao acesso: `token` ou `passkey:<rótulo>`.
    Sem ela, `sessao_admin` continuaria dizendo apenas que alguém entrou.
    """
    ident = secrets.token_urlsafe(32)
    sink.executar(
        "INSERT INTO sessao_admin (id, origem, expira_em) VALUES (?,?,?)",
        (ident, origem, _agora() + timedelta(days=DIAS_DE_SESSAO)),
    )
    return ident


def sessao_valida(sink: Sink, ident: str | None) -> dict | None:
    """A sessão existe e não venceu? Marca o uso e devolve a linha."""
    if not ident:
        return None
    linha = sink.um("SELECT * FROM sessao_admin WHERE id = ?", (ident,))
    if linha is None:
        return None
    expira = _dt(linha["expira_em"])
    if expira is not None and expira <= _agora():
        # Vencida é apagada na hora: deixá-la faria a tabela crescer com
        # linha que só serve para ser recusada de novo.
        fechar_sessao(sink, ident)
        return None
    sink.executar(
        "UPDATE sessao_admin SET ultimo_uso_em = ? WHERE id = ?", (_agora(), ident)
    )
    return linha


def fechar_sessao(sink: Sink, ident: str | None) -> None:
    if ident:
        sink.executar("DELETE FROM sessao_admin WHERE id = ?", (ident,))


def sessoes(sink: Sink) -> list[dict]:
    return sink.consultar(
        "SELECT id, origem, criada_em, expira_em, ultimo_uso_em "
        "FROM sessao_admin ORDER BY criada_em DESC"
    )


# ---------------------------------------------------------------------------
# Identidade do site para o WebAuthn
# ---------------------------------------------------------------------------
def identidade_do_site(origem_pedida: str | None = None) -> tuple[str, list[str]]:
    """`(rp_id, origens aceitas)`.

    Sai de `PORTAL_URL_PUBLICA`, que já é o único lugar onde o endereço
    público mora — uma variável nova só para o WebAuthn seria um segundo
    endereço a manter em dia com o primeiro.

    A origem pedida pelo navegador entra na lista só quando é `localhost`:
    em desenvolvimento a porta varia e o `rp_id` continua sendo `localhost`,
    que é o que a especificação permite tratar como seguro sem TLS.
    """
    publica = os.getenv("PORTAL_URL_PUBLICA", "").strip().rstrip("/")
    aceitas: list[str] = []
    if publica:
        aceitas.append(publica)
        rp_id = urlparse(publica).hostname or "localhost"
    else:
        rp_id = "localhost"

    if origem_pedida:
        host = urlparse(origem_pedida).hostname or ""
        if host in ("localhost", "127.0.0.1"):
            aceitas.append(origem_pedida.rstrip("/"))
            if not publica:
                rp_id = "localhost"
    if not aceitas:
        aceitas.append("http://localhost:8420")
    return rp_id, aceitas


# ---------------------------------------------------------------------------
# Desafio
# ---------------------------------------------------------------------------
def novo_desafio(sink: Sink, proposito: str) -> bytes:
    bruto = secrets.token_bytes(32)
    sink.executar("DELETE FROM desafio_webauthn WHERE criado_em < ?",
                  (_agora() - timedelta(minutes=MINUTOS_DE_DESAFIO),))
    sink.executar(
        "INSERT INTO desafio_webauthn (desafio, proposito) VALUES (?,?)",
        (b64(bruto), proposito),
    )
    return bruto


def consumir_desafio(sink: Sink, valor: str, proposito: str) -> bytes:
    """Devolve o desafio e o apaga. Usado duas vezes não é desafio."""
    linha = sink.um(
        "SELECT * FROM desafio_webauthn WHERE desafio = ? AND proposito = ?",
        (valor, proposito),
    )
    if linha is None:
        raise ErroAcesso("O desafio não confere. Tente entrar de novo.")
    sink.executar("DELETE FROM desafio_webauthn WHERE desafio = ?", (valor,))
    criado = _dt(linha["criado_em"])
    if criado and criado + timedelta(minutes=MINUTOS_DE_DESAFIO) < _agora():
        raise ErroAcesso("O desafio expirou. Tente entrar de novo.")
    return de_b64(valor)


# ---------------------------------------------------------------------------
# base64url — a codificação que o WebAuthn fala do lado do navegador
# ---------------------------------------------------------------------------
def b64(bruto: bytes) -> str:
    return base64.urlsafe_b64encode(bruto).decode().rstrip("=")


def de_b64(valor: str) -> bytes:
    return base64.urlsafe_b64decode(valor + "=" * (-len(valor) % 4))


# ---------------------------------------------------------------------------
# Passkeys
# ---------------------------------------------------------------------------
def passkeys(sink: Sink) -> list[dict]:
    return sink.consultar(
        "SELECT credential_id, rotulo, transportes, criada_em, ultimo_uso_em, "
        "sign_count FROM cfg_passkey ORDER BY criada_em"
    )


def ha_passkey(sink: Sink) -> bool:
    return bool(sink.um("SELECT count(*) AS n FROM cfg_passkey")["n"])


def esquecer_passkey(sink: Sink, credential_id: str) -> bool:
    """Revogar é apagar. Uma credencial 'inativa' que ainda autentica seria
    pior do que credencial nenhuma."""
    if sink.um("SELECT 1 AS ok FROM cfg_passkey WHERE credential_id = ?",
               (credential_id,)) is None:
        return False
    sink.executar("DELETE FROM cfg_passkey WHERE credential_id = ?", (credential_id,))
    return True


def opcoes_de_registro(sink: Sink, rotulo: str, origem: str | None = None) -> str:
    """O que o navegador precisa para criar uma credencial nova.

    As já registradas vão em `exclude_credentials`: sem isso, registrar o mesmo
    autenticador duas vezes cria duas linhas para a mesma chave, e apagar uma
    delas passa a não revogar nada.
    """
    from webauthn import generate_registration_options, options_to_json
    from webauthn.helpers.structs import (
        AuthenticatorSelectionCriteria, PublicKeyCredentialDescriptor,
        ResidentKeyRequirement, UserVerificationRequirement,
    )

    rp_id, _ = identidade_do_site(origem)
    opcoes = generate_registration_options(
        rp_id=rp_id,
        rp_name="MyData",
        # Dono único: o "usuário" é o sistema. Um nome por pessoa viraria
        # decisão nova no dia em que houver mais de uma — está no ADR.
        user_name="dono",
        user_display_name="Dono do MyData",
        challenge=novo_desafio(sink, "registro"),
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
        exclude_credentials=[
            PublicKeyCredentialDescriptor(id=de_b64(p["credential_id"]))
            for p in passkeys(sink)
        ],
    )
    _ = rotulo  # o rótulo é do nosso lado; o autenticador não o vê
    return options_to_json(opcoes)


def registrar(sink: Sink, credencial: dict, rotulo: str,
              origem: str | None = None) -> dict:
    """Confere o que o autenticador devolveu e guarda a chave pública."""
    from webauthn import verify_registration_response

    rp_id, origens = identidade_do_site(origem)
    desafio = consumir_desafio(
        sink, _desafio_de(credencial), "registro"
    )
    try:
        verificada = verify_registration_response(
            credential=credencial,
            expected_challenge=desafio,
            expected_rp_id=rp_id,
            expected_origin=origens,
        )
    except Exception as e:  # a biblioteca levanta vários tipos próprios
        raise ErroAcesso(f"O autenticador não pôde ser registrado: {e}") from e

    ident = b64(verificada.credential_id)
    transportes = ",".join(
        (credencial.get("response") or {}).get("transports") or []
    )
    sink.executar(
        "INSERT INTO cfg_passkey (credential_id, chave_publica, sign_count, "
        "rotulo, transportes) VALUES (?,?,?,?,?)",
        (ident, verificada.credential_public_key, verificada.sign_count,
         rotulo.strip() or "sem rótulo", transportes),
    )
    return {"credential_id": ident, "rotulo": rotulo}


def opcoes_de_entrada(sink: Sink, origem: str | None = None) -> str:
    from webauthn import generate_authentication_options, options_to_json
    from webauthn.helpers.structs import PublicKeyCredentialDescriptor

    rp_id, _ = identidade_do_site(origem)
    opcoes = generate_authentication_options(
        rp_id=rp_id,
        challenge=novo_desafio(sink, "entrada"),
        allow_credentials=[
            PublicKeyCredentialDescriptor(id=de_b64(p["credential_id"]))
            for p in passkeys(sink)
        ],
    )
    return options_to_json(opcoes)


def entrar_com_passkey(sink: Sink, credencial: dict,
                       origem: str | None = None) -> str:
    """Verifica a assertiva e abre a sessão. Devolve o id do cookie."""
    from webauthn import verify_authentication_response

    rp_id, origens = identidade_do_site(origem)
    ident = credencial.get("id") or ""
    guardada = sink.um(
        "SELECT * FROM cfg_passkey WHERE credential_id = ?", (ident,)
    )
    if guardada is None:
        # O desafio fica de pé: quem tenta com credencial desconhecida não
        # deve conseguir consumir o desafio de quem tem a certa.
        raise ErroAcesso("Este autenticador não está registrado aqui.")

    desafio = consumir_desafio(sink, _desafio_de(credencial), "entrada")
    try:
        verificada = verify_authentication_response(
            credential=credencial,
            expected_challenge=desafio,
            expected_rp_id=rp_id,
            expected_origin=origens,
            credential_public_key=bytes(guardada["chave_publica"]),
            credential_current_sign_count=int(guardada["sign_count"] or 0),
        )
    except Exception as e:
        raise ErroAcesso(f"A verificação falhou: {e}") from e

    sink.executar(
        "UPDATE cfg_passkey SET sign_count = ?, ultimo_uso_em = ? "
        "WHERE credential_id = ?",
        (verificada.new_sign_count, _agora(), ident),
    )
    return abrir_sessao(sink, f"passkey:{guardada['rotulo']}")


def _desafio_de(credencial: dict) -> str:
    """O desafio que o navegador assinou, lido do `clientDataJSON`.

    Vem daí e não de um campo à parte no corpo: o que vale é o que foi
    assinado, e um segundo lugar para a mesma informação seria um lugar onde
    ela pode divergir.
    """
    import json

    dados = (credencial.get("response") or {}).get("clientDataJSON")
    if not dados:
        raise ErroAcesso("Resposta do autenticador sem clientDataJSON.")
    try:
        return json.loads(de_b64(dados))["challenge"]
    except Exception as e:
        raise ErroAcesso("Não consegui ler o desafio da resposta.") from e


# ---------------------------------------------------------------------------
# O caminho do token, e quando ele aparece
# ---------------------------------------------------------------------------
def token_no_formulario(sink: Sink) -> bool:
    """O formulário de token deve aparecer na tela de entrada?

    Enquanto não houver passkey registrada, sim — é por ele que o primeiro
    autenticador entra, e escondê-lo antes disso trancaria o dono do lado de
    fora. Depois, não: o campo de segredo digitado é a queixa que motivou tudo
    isto.

    `PORTAL_ACESSO_LEGADO=1` traz o formulário de volta. É a saída de
    emergência do ADR-19, e existe para o caso do autenticador perdido às onze
    da noite — o Alex define a variável no painel do Railway e entra de novo.

    O cabeçalho `X-Admin-Token` **não** passa por aqui: ele vale sempre, para
    `curl` e script. Quem opera por terminal nunca fica trancado.
    """
    if not os.getenv("PORTAL_ADMIN_TOKEN"):
        return False
    if os.getenv("PORTAL_ACESSO_LEGADO") == "1":
        return True
    return not ha_passkey(sink)
