"""Regras de qualidade como gate de publicação.

Convenção: a expressão de uma regra SELECIONA as linhas *erradas*. Zero linhas
significa aprovado. Isso é o oposto de um assert, e é de propósito — a regra
serve tanto de gate quanto de relatório: quando falha, o operador já tem as
linhas problemáticas na mão.
"""
from __future__ import annotations

import logging

from .calculados import validar_expressao
from ..sinks import Sink

log = logging.getLogger("portal.qualidade")


def avaliar(sink: Sink, regras: list[dict]) -> list[dict]:
    """Roda as regras e devolve as violações. Não decide nada — só informa."""
    violacoes: list[dict] = []
    for regra in regras:
        sql = regra["expressao_sql"].strip().rstrip(";")
        if not sql.lower().startswith("select"):
            violacoes.append({
                "nome": regra["nome"],
                "severidade": "bloqueia",
                "linhas": -1,
                "erro": "regra precisa ser um SELECT das linhas erradas",
            })
            continue
        validar_expressao(sql.replace("select", "", 1), regra["nome"])
        try:
            linha = sink.um(f"SELECT count(*) AS n FROM ({sql}) AS r")
            achadas = int(linha["n"]) if linha else 0
        except Exception as e:  # noqa: BLE001 — regra ruim não derruba a carga
            violacoes.append({
                "nome": regra["nome"],
                "severidade": "bloqueia" if regra["severidade"] == "bloqueia" else "alerta",
                "linhas": -1,
                "erro": f"{type(e).__name__}: {e}",
            })
            continue

        if achadas > float(regra["tolerancia"] or 0):
            violacoes.append({
                "nome": regra["nome"],
                "severidade": regra["severidade"],
                "linhas": achadas,
                "erro": None,
            })
            log.warning(
                "regra '%s' (%s): %d linhas fora do esperado",
                regra["nome"], regra["severidade"], achadas,
            )
    return violacoes
