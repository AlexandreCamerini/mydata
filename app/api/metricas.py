"""Indicadores fundamentalistas — campos calculados de nível empresa.

A fórmula vive em `cfg_metrica`, editável pela interface. Referencia conta
contábil com `c('1.01')`, que o motor expande para um pivô sobre
`gold_demonstracoes`. É uma DSL de uma função de propósito: pequena o
suficiente para ser segura, expressiva o bastante para os indicadores usuais.

Toda métrica carrega a proveniência da demonstração que a originou — um
indicador sem rastro até o arquivo oficial não serve para análise.
"""
from __future__ import annotations

import re

from ..sinks import Sink

CONTA = re.compile(r"c\(\s*'([0-9.]{1,20})'\s*\)")
PERMITIDO = re.compile(r"^[0-9\s+\-*/().,'a-zA-Z_]*$")


class ErroMetrica(ValueError):
    pass


def expandir(formula: str) -> tuple[str, list[str]]:
    """Troca `c('1.01')` por agregação condicional. Devolve (sql, contas)."""
    if not PERMITIDO.match(formula):
        raise ErroMetrica(f"fórmula contém caractere não permitido: {formula!r}")
    contas: list[str] = []

    def troca(m: re.Match) -> str:
        conta = m.group(1)
        contas.append(conta)
        return f"MAX(CASE WHEN cd_conta = '{conta}' THEN vl_conta_norm END)"

    sql = CONTA.sub(troca, formula)
    if not contas:
        raise ErroMetrica("fórmula não referencia nenhuma conta com c('...')")
    if re.search(r"[a-zA-Z_]{2,}\s*\(", sql.replace("MAX(", "").replace("CASE", "")):
        raise ErroMetrica("fórmula só aceita a função c('conta') e aritmética")
    return sql, contas


def listar(sink: Sink) -> list[dict]:
    return sink.consultar(
        "SELECT * FROM cfg_metrica WHERE vigente AND ativo ORDER BY nome"
    )


def calcular(
    sink: Sink, cd_cvm: int, consolidado: bool = True,
    nomes: list[str] | None = None,
) -> list[dict]:
    """Calcula as métricas por período para uma empresa."""
    metricas = [m for m in listar(sink) if not nomes or m["chave"] in nomes]
    if not metricas:
        return []

    selecoes, usadas = [], {}
    for m in metricas:
        try:
            sql, contas = expandir(m["formula"])
        except ErroMetrica:
            continue
        # O alias é a chave (identificador), não o nome de exibição — "Margem
        # líquida" não é identificador SQL válido.
        selecoes.append(f"({sql}) AS {m['chave']}")
        usadas[m["chave"]] = {"nome": m["nome"], "contas": contas,
                              "unidade": m["unidade"], "descricao": m["descricao"]}
    if not selecoes:
        return []

    linhas = sink.consultar(
        f"""SELECT dt_refer, tipo_doc, MIN(captura_id) AS captura_id,
                   {', '.join(selecoes)}
            FROM gold_demonstracoes
            WHERE cd_cvm = ? AND consolidado = ?
            GROUP BY dt_refer, tipo_doc
            ORDER BY dt_refer DESC, tipo_doc""",
        (cd_cvm, consolidado),
    )

    saida = []
    for linha in linhas:
        valores = {
            nome: linha[nome] for nome in usadas
            if linha.get(nome) is not None
        }
        if not valores:
            continue
        saida.append({
            "dt_refer": linha["dt_refer"],
            "tipo_doc": linha["tipo_doc"],
            "metricas": valores,
            "definicoes": {n: usadas[n] for n in valores},
            "proveniencia": {"captura_id": linha["captura_id"]},
        })
    return saida
