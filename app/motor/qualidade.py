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

        if not achadas:
            continue

        # Dentro da tolerância a violação continua sendo reportada — só deixa
        # de barrar. Silenciar seria pior que não ter regra: o operador
        # perderia de vista o caso isolado justamente porque ele é raro, e a
        # tolerância existe para não reter um ano inteiro por causa de uma
        # declaração torta na origem, não para esconder que ela existe.
        tolerada = achadas <= float(regra["tolerancia"] or 0)
        severidade = "alerta" if tolerada else regra["severidade"]
        violacoes.append({
            "nome": regra["nome"],
            "severidade": severidade,
            "linhas": achadas,
            "tolerada": tolerada,
            "tolerancia": float(regra["tolerancia"] or 0),
            "erro": None,
        })
        log.warning(
            "regra '%s' (%s): %d linhas fora do esperado%s",
            regra["nome"], severidade, achadas,
            f" — dentro da tolerância de {regra['tolerancia']:.0f}" if tolerada else "",
        )
    return violacoes
