"""Aplicação dos campos calculados declarados no catálogo.

Duas classes, com consequências operacionais diferentes:

- `escalar`: expressão linha a linha. `UPDATE ... SET campo = <expr>`.
- `janela`: precisa de partição. `is_latest` é o caso canônico — a partição é
  global por (cd_cvm, tipo_doc, dt_refer) e **cruza janelas de carga**, então
  recomputar só o ano ingerido deixaria o flag errado em anos vizinhos quando
  chega uma reapresentação. Por isso campo de janela é sempre recomputado
  sobre a tabela inteira.

A expressão é SQL restrito, validado antes de rodar: sem DDL, sem subconsulta
a tabela não declarada, sem ponto e vírgula. O campo é editável pela interface,
então executar texto livre aqui seria RCE com formulário.
"""
from __future__ import annotations

import logging
import re

from ..repositorio import ErroConfiguracao
from ..sinks import Sink

log = logging.getLogger("portal.calculados")

PROIBIDO = re.compile(
    r"\b(drop|delete|insert|update|alter|create|grant|revoke|attach|copy|"
    r"pg_read_file|pg_sleep|system|load|install)\b|;|--|/\*",
    re.IGNORECASE,
)


def validar_expressao(expressao: str, nome: str) -> None:
    if PROIBIDO.search(expressao):
        raise ErroConfiguracao(
            f"expressão do campo '{nome}' contém construção não permitida. "
            f"Use apenas expressão de leitura: operadores, CASE, funções "
            f"escalares e de janela."
        )


def _lista(valor: str | None) -> list[str]:
    return [p.strip() for p in (valor or "").split(",") if p.strip()]


def aplicar(sink: Sink, ds: dict, campos: list[dict]) -> list[str]:
    """Recomputa os campos calculados do dataset. Devolve os nomes aplicados."""
    tabela = ds["tabela_destino"]
    aplicados: list[str] = []

    for campo in sorted(campos, key=lambda c: (c["ordem"], c["id"])):
        if campo["materializacao"] != "coluna":
            continue
        validar_expressao(campo["expressao"], campo["nome"])

        if campo["classe"] == "escalar":
            sink.executar(f"UPDATE {tabela} SET {campo['nome']} = {campo['expressao']}")
        else:
            particao = _lista(campo["particao_por"])
            if not particao:
                raise ErroConfiguracao(
                    f"campo de janela '{campo['nome']}' sem particao_por"
                )
            ordena = _lista(campo["ordena_por"])
            over = f"PARTITION BY {', '.join(particao)}"
            if ordena:
                over += f" ORDER BY {', '.join(ordena)}"
            # A junção é pela chave natural, não pela partição: partição
            # identifica o grupo, não a linha. rowid/ctid não são portáteis.
            chaves = _lista(ds["chave_natural"])
            if not chaves:
                raise ErroConfiguracao(
                    f"dataset '{ds['chave']}' sem chave natural: campo de janela "
                    f"'{campo['nome']}' não tem como casar linha a linha"
                )
            expressao = campo["expressao"].replace("{OVER}", f"OVER ({over})")
            sink.executar(
                f"""UPDATE {tabela} AS alvo
                    SET {campo['nome']} = origem.valor_calculado
                    FROM (
                      SELECT {', '.join(chaves)}, {expressao} AS valor_calculado
                      FROM {tabela}
                    ) AS origem
                    WHERE """
                + " AND ".join(
                    f"(alvo.{c} = origem.{c} OR "
                    f"(alvo.{c} IS NULL AND origem.{c} IS NULL))"
                    for c in chaves
                )
            )
        aplicados.append(campo["nome"])
        log.info("campo calculado aplicado: %s (%s)", campo["nome"], campo["classe"])
    return aplicados
