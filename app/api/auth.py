"""Chaves de API: emissão, verificação e quota.

Hash: SHA-256 do segredo, não bcrypt/argon2. Os últimos existem para segredo de
baixa entropia escolhido por humano; aqui a chave são 32 bytes aleatórios, onde
força bruta é inviável por construção. bcrypt custaria dezenas de milissegundos
por requisição — num serviço com CPU limitada pelo plano, seria a maior fatia
do tempo de resposta, sem ganho de segurança.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone

from ..sinks import Sink

PREFIXO_TAM = 8

# --------------------------------------------------------------------------
# Sessão do dono
# --------------------------------------------------------------------------
# Mora aqui, e não em `main`, porque as duas superfícies precisam dela: a
# apresentação, que a cria, e a administração, que passou a aceitá-la. Deixar
# a checagem em `main` obrigaria `admin` a importar `main`, que já importa
# `admin` — e a duplicação seria a alternativa, com as duas cópias divergindo
# na primeira mudança.
COOKIE_SESSAO = "portal_sessao"


def admin_ok(valor: str | None) -> bool:
    """O valor confere com PORTAL_ADMIN_TOKEN?

    Sem a variável definida não há sessão de administração — é o modo de
    desenvolvimento local, e a ausência é escolha explícita, não descuido.
    """
    esperado = os.getenv("PORTAL_ADMIN_TOKEN")
    if not esperado or not valor:
        return False
    return hmac.compare_digest(valor, esperado)


def sessao_admin(request) -> bool:
    """Sessão do dono: o cookie criado em `/entrar`, ou o cabeçalho.

    O cookie é `HttpOnly` e `SameSite=Lax` — Lax não acompanha requisição
    cruzada que não seja navegação de topo, e é o que segura CSRF nas rotas
    de escrita da administração. O cabeçalho continua valendo para script e
    `curl`, que não têm cookie.

    Três caminhos, nesta ordem, e o ADR-19 é o motivo de serem três:

    1. `X-Admin-Token`. Vale sempre, com ou sem passkey registrada. É o que
       garante que ninguém fica trancado fora do terminal.
    2. O cookie como identificador de sessão, com linha em `sessao_admin`.
       É o caminho novo, e o único que carrega identidade e expiração.
    3. O cookie carregando o próprio token. É o formato antigo; continua
       aceito porque um cookie já emitido não deve parar de valer no deploy.
    """
    if admin_ok(request.headers.get("X-Admin-Token")):
        return True
    biscoito = request.cookies.get(COOKIE_SESSAO)
    if not biscoito:
        return False
    sink = getattr(request.app.state, "sink", None)
    if sink is not None:
        from . import acesso

        if acesso.sessao_valida(sink, biscoito):
            return True
    return admin_ok(biscoito)


@dataclass
class ChaveEmitida:
    prefixo: str
    chave_completa: str   # mostrada uma única vez, no momento da emissão
    consumidor: str


def _hash(segredo: str) -> str:
    return hashlib.sha256(segredo.encode()).hexdigest()


def emitir(
    sink: Sink, consumidor: str, quota_minuto: int = 120,
    quota_dia: int = 50000, escopos: str = "leitura",
) -> ChaveEmitida:
    prefixo = secrets.token_hex(PREFIXO_TAM // 2)
    segredo = secrets.token_urlsafe(32)
    sink.executar(
        """INSERT INTO cfg_chave_api
           (id, consumidor, prefixo, hash_chave, quota_minuto, quota_dia, escopos)
           VALUES (?,?,?,?,?,?,?)""",
        (sink.proximo_id("cfg_chave_api"), consumidor, prefixo, _hash(segredo),
         quota_minuto, quota_dia, escopos),
    )
    return ChaveEmitida(prefixo, f"pd_{prefixo}_{segredo}", consumidor)


def revogar(sink: Sink, prefixo: str) -> bool:
    linha = sink.um(
        "SELECT id FROM cfg_chave_api WHERE prefixo = ? AND revogada_em IS NULL",
        (prefixo,),
    )
    if linha is None:
        return False
    sink.executar(
        "UPDATE cfg_chave_api SET revogada_em = ? WHERE prefixo = ?",
        (datetime.now(timezone.utc), prefixo),
    )
    return True


def verificar(sink: Sink, chave: str | None) -> dict | None:
    """Devolve a chave se válida e não revogada; None caso contrário."""
    if not chave or not chave.startswith("pd_"):
        return None
    partes = chave.split("_", 2)
    if len(partes) != 3:
        return None
    _, prefixo, segredo = partes
    linha = sink.um(
        "SELECT * FROM cfg_chave_api WHERE prefixo = ? AND revogada_em IS NULL",
        (prefixo,),
    )
    if linha is None:
        return None
    if not secrets.compare_digest(linha["hash_chave"], _hash(segredo)):
        return None
    return linha


def classes_permitidas(chave: dict) -> set[str] | None:
    """Quais classes de informação esta chave pode ler. `None` = todas.

    O escopo é o contrato de cada app consumidor: um app de análise
    fundamentalista lê demonstração financeira e empresa; um de watchlist não
    precisa de nada além de empresa. App novo é chave nova com o escopo dele —
    não código novo.

    Sintaxe: `leitura` libera tudo; `classe:empresa` restringe. As duas
    convivem porque a chave antiga já emitida diz `leitura`, e revogar tudo
    para introduzir escopo seria migração desnecessária.
    """
    escopos = [e.strip() for e in (chave.get("escopos") or "").split(",") if e.strip()]
    classes = {e.split(":", 1)[1] for e in escopos if e.startswith("classe:")}
    return classes or None


def fontes_permitidas(chave: dict) -> set[str]:
    """Quais fontes esta chave pode ler explicitamente.

    A sintaxe é paralela à de `classes_permitidas`: `fonte:b3` é um
    consentimento explícito para os atributos cuja origem vencedora é B3.
    `leitura` continua sendo tratado como acesso amplo por
    `pode_ver_fonte`, para não alterar chaves antigas.
    """
    escopos = [e.strip() for e in (chave.get("escopos") or "").split(",") if e.strip()]
    return {e.split(":", 1)[1] for e in escopos if e.startswith("fonte:")}


def pode_ver_fonte(chave: dict, fonte: str) -> bool:
    """Se a chave pode receber atributos cuja origem é `fonte`.

    Só B3 exige opt-in: fontes republicáveis continuam disponíveis para uma
    chave restrita por classe. Chaves antigas com `escopos == "leitura"`
    permanecem amplas.
    """
    if (chave.get("escopos") or "").strip() == "leitura":
        return True
    return fonte in fontes_permitidas(chave)


def pode_ler(chave: dict, classe: str | None) -> bool:
    permitidas = classes_permitidas(chave)
    if permitidas is None or classe is None:
        return True
    return classe in permitidas


def consumir_quota(sink: Sink, chave: dict, agora: datetime | None = None) -> dict:
    """Incrementa e avalia a quota. Devolve {ok, limite, restante, janela}."""
    agora = agora or datetime.now(timezone.utc)
    baldes = [
        ("minuto", agora.strftime("%Y%m%d%H%M"), int(chave["quota_minuto"])),
        ("dia", agora.strftime("%Y%m%d"), int(chave["quota_dia"])),
    ]
    pior = {"ok": True, "limite": 0, "restante": 0, "janela": "minuto"}
    for janela, balde, limite in baldes:
        sink.executar(
            """INSERT INTO uso_chave_api (prefixo, janela, balde, chamadas)
               VALUES (?,?,?,1)
               ON CONFLICT (prefixo, janela, balde)
               DO UPDATE SET chamadas = uso_chave_api.chamadas + 1""",
            (chave["prefixo"], janela, balde),
        )
        linha = sink.um(
            "SELECT chamadas FROM uso_chave_api "
            "WHERE prefixo = ? AND janela = ? AND balde = ?",
            (chave["prefixo"], janela, balde),
        )
        usadas = int(linha["chamadas"])
        restante = max(0, limite - usadas)
        if usadas > limite:
            return {"ok": False, "limite": limite, "restante": 0, "janela": janela}
        if pior["ok"] and (restante < pior["restante"] or pior["limite"] == 0):
            pior = {"ok": True, "limite": limite, "restante": restante, "janela": janela}
    return pior


def consumir_quota_ip_emissao(
    sink: Sink, ip: str, agora: datetime | None = None, limite: int = 5,
) -> dict:
    """Conta emissões por IP no balde diário da rota pública de chaves."""
    agora = agora or datetime.now(timezone.utc)
    janela = "dia"
    balde = agora.strftime("%Y%m%d")
    sink.executar(
        """INSERT INTO uso_ip_emissao_chave (ip, janela, balde, chamadas)
           VALUES (?,?,?,1)
           ON CONFLICT (ip, janela, balde)
           DO UPDATE SET chamadas = uso_ip_emissao_chave.chamadas + 1""",
        (ip, janela, balde),
    )
    linha = sink.um(
        "SELECT chamadas FROM uso_ip_emissao_chave "
        "WHERE ip = ? AND janela = ? AND balde = ?",
        (ip, janela, balde),
    )
    usadas = int(linha["chamadas"])
    return {
        "ok": usadas <= limite,
        "limite": limite,
        "restante": max(0, limite - usadas),
        "janela": janela,
    }
