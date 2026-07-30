"""Chaves de API: emissão, verificação e quota.

Hash: SHA-256 do segredo, não bcrypt/argon2. Os últimos existem para segredo de
baixa entropia escolhido por humano; aqui a chave são 32 bytes aleatórios, onde
força bruta é inviável por construção. bcrypt custaria dezenas de milissegundos
por requisição — num serviço com CPU limitada pelo plano, seria a maior fatia
do tempo de resposta, sem ganho de segurança.
"""
from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone

from ..sinks import Sink

PREFIXO_TAM = 8


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
