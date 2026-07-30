"""Impressão digital do que está publicado — a rede de segurança do plano.

Toda etapa que mexe no modelo de dados usa "derruba e recomputa do bronze"
como plano de volta. Isso só é uma garantia se alguém conseguir provar que o
recomputo reproduz o mesmo resultado. É o que este módulo faz: reduz gold a
um par (linhas, sha256) comparável antes e depois.

O rótulo de publicação fica de fora do digest de propósito: recomputar cria
uma publicação nova, e o número dela mudar não significa que o dado mudou.

O digest compara um banco consigo mesmo, não bancos de dialetos diferentes —
DuckDB devolve float onde o Postgres devolve Decimal, e a representação
textual dos dois difere sem que exista divergência de dado.
"""
from __future__ import annotations

import hashlib

from ..sinks import Sink

IGNORADAS = ("publicado_em_versao",)


def _colunas(sink: Sink, objeto: str) -> list[str]:
    linhas = sink.consultar(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = ? ORDER BY ordinal_position",
        (objeto,),
    )
    return [linha["column_name"] for linha in linhas]


def digest_de(sink: Sink, objeto: str, ignorar: tuple[str, ...] = IGNORADAS) -> dict:
    colunas = [c for c in _colunas(sink, objeto) if c not in ignorar]
    if not colunas:
        return {"linhas": 0, "sha256": "vazio", "ausente": True}
    lista = ", ".join(colunas)
    ordem = ", ".join(str(i + 1) for i in range(len(colunas)))
    resumo = hashlib.sha256()
    total = 0
    for linha in sink.consultar(f"SELECT {lista} FROM {objeto} ORDER BY {ordem}"):
        resumo.update(repr([linha[c] for c in colunas]).encode())
        total += 1
    return {"linhas": total, "sha256": resumo.hexdigest()[:16]}


def impressao_digital(sink: Sink) -> dict[str, dict]:
    """Digest de cada vista de gold, na ordem, pronto para comparação."""
    from . import publicacao as pub

    return {nome: digest_de(sink, nome) for nome in sorted(pub.vistas(sink))}
