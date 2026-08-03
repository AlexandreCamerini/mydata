"""O contrato publicado de uma classe: o que o consumidor recebe, e de onde.

O contrato não é informação nova — é a configuração que já governa a carga,
montada na forma que quem consome consegue ler. `cfg_atributo` diz o que a
classe promete; `cfg_coluna` diz de qual coluna de qual arquivo cada atributo
sai e o que a tipagem faz com ela; `cfg_campo_calculado` diz o que foi derivado
e a partir de quê; `cfg_regra_qualidade` diz o que vigia a carga e o que barra
a publicação.

**Montado, nunca gravado.** Um contrato guardado à parte seria uma segunda
declaração do mesmo fato, livre para divergir da configuração que de fato roda
— e a divergência apareceria justamente para o consumidor, que é quem não tem
como conferir.

**Forma: subconjunto do ODCS** (Open Data Contract Standard, Bitol/Linux
Foundation). Campos do padrão onde eles mapeiam; `customProperties` para o que
nem o ODCS nem o `contracts` do dbt têm conceito — duas fontes disputando o
mesmo atributo. Ver `docs/pesquisa-mercado.md` § Q6.

Limite assumido: `version` é o inteiro monotônico da configuração, não semver.
Ele sobe em qualquer mudança, quebrando ou não. Distinguir quebra exigiria
comparar schemas entre versões, e não há caso concreto que pague isso hoje.
"""
from __future__ import annotations

from .. import repositorio as repo
from ..sinks import Sink

PERFIL = "mydata/1 — subconjunto do ODCS v3.1.0"

# Tipo declarado na classe -> `logicalType` do ODCS, que é agnóstico de motor.
# `physicalType` fica de fora de propósito: ele depende do dialeto do sink, e
# prometer um tipo físico que muda entre DuckDB e Postgres seria promessa que o
# contrato não cumpre.
LOGICO = {
    "texto": "string",
    "inteiro": "integer",
    "numero": "number",
    "data": "date",
    "booleano": "boolean",
}

ATRIBUICAO = (
    "Dado obtido do portal de dados abertos da fonte oficial. A resposta de "
    "cada consulta carrega fonte, hash da captura, versão do documento e "
    "publicação — é a citação de fonte que a licença da origem exige."
)


def _lista(valor: str | None) -> list[str]:
    return [p for p in (valor or "").split(",") if p]


def _origens_por_atributo(sink: Sink, classe_chave: str) -> dict[str, list[dict]]:
    """Para cada atributo, de qual coluna de qual fonte ele chega.

    O mapeamento mora em `cfg_coluna`: `nome_origem` é a coluna do arquivo e
    `nome_destino` é o atributo da classe. Um atributo alimentado por duas
    fontes aparece duas vezes, e é isso que torna a disputa visível.
    """
    saida: dict[str, list[dict]] = {}
    for ds in repo.datasets_da_classe(sink, classe_chave):
        for c in repo.colunas_do(sink, ds["id"]):
            saida.setdefault(c["nome_destino"], []).append({
                "fonte": ds["fonte_chave"],
                "mapeamento": ds["chave"],
                "coluna_origem": c["nome_origem"],
                "tipo_origem": c["tipo"],
                # `formato` é o que a normalização aplica: decimal em padrão
                # brasileiro, data ISO, e assim por diante. Nulo significa que
                # o valor entra como a fonte o escreveu.
                "normalizacao": c["formato"],
                "obrigatoria_na_origem": bool(c["obrigatoria"]),
            })
    return saida


def _calculados(sink: Sink, classe_chave: str) -> list[dict]:
    saida = []
    for ds in repo.datasets_da_classe(sink, classe_chave):
        for c in repo.calculados_do(sink, ds["id"]):
            saida.append({
                "nome": c["nome"],
                "mapeamento": ds["chave"],
                "expressao": c["expressao"],
                "colunas_origem": _lista(c["colunas_origem"]),
                "materializacao": c["materializacao"],
                "descricao": c["descricao"],
            })
    return saida


def _qualidade(sink: Sink, classe_chave: str) -> list[dict]:
    """As regras no vocabulário de `quality` do ODCS."""
    saida = []
    for ds in repo.datasets_da_classe(sink, classe_chave):
        for r in repo.regras_do(sink, ds["id"]):
            saida.append({
                "name": r["nome"],
                "type": "sql",
                "rule": r["expressao_sql"],
                "severity": r["severidade"],
                # O que o consumidor precisa saber não é a severidade nominal e
                # sim a consequência: uma regra que bloqueia significa que todo
                # dado publicado passou por ela.
                "impedePublicacao": r["severidade"] == "bloqueia",
                "tolerance": float(r["tolerancia"] or 0),
                "description": r["descricao"],
                "customProperties": {"mapeamento": ds["chave"]},
            })
    return saida


def _propriedades(sink: Sink, classe: dict) -> list[dict]:
    origens = _origens_por_atributo(sink, classe["chave"])
    precedencia_classe = _lista(classe.get("precedencia"))

    saida = []
    for a in repo.atributos_de(sink, classe["id"]):
        propria = _lista(a.get("precedencia"))
        origem = origens.get(a["nome"], [])
        saida.append({
            "name": a["nome"],
            "logicalType": LOGICO.get(a["tipo"], "string"),
            "required": bool(a.get("obrigatorio")),
            "description": a["descricao"],
            "unit": a["unidade"],
            "customProperties": {
                # Precedência vazia no atributo herda a da classe. Devolver a
                # herdada já resolvida poupa o consumidor de repetir a regra.
                "precedencia": propria or precedencia_classe,
                "precedenciaHerdada": not propria,
                "disputado": len(origem) > 1,
                "origens": origem,
            },
        })
    return saida


def contrato(sink: Sink, classe_chave: str) -> dict:
    """O contrato publicado de uma classe, no perfil ODCS descrito acima.

    Levanta `repo.ErroConfiguracao` quando a classe não existe ou não está
    vigente — quem chama traduz para 404.
    """
    classe = repo.classe_vigente(sink, classe_chave)
    if classe is None:
        raise repo.ErroConfiguracao(
            f"classe '{classe_chave}' não existe ou não está vigente"
        )

    slas = []
    if classe.get("sla_horas"):
        slas.append({
            "property": "frescor",
            "value": int(classe["sla_horas"]),
            "unit": "h",
            "description": "idade máxima aceita do dado desde a última publicação",
        })

    publicacao = sink.um(
        "SELECT versao, publicado_em FROM publicacao ORDER BY versao DESC"
    )

    return {
        "apiVersion": "v3.1.0",
        "kind": "DataContract",
        "perfil": PERFIL,
        "id": classe["chave"],
        "name": classe["nome"],
        "version": classe["versao"],
        "status": "active" if classe.get("ativo", True) else "retired",
        "description": {
            "purpose": classe["descricao"],
            "usage": ATRIBUICAO,
        },
        "schema": [{
            "name": classe["chave"],
            "logicalType": "object",
            "physicalName": classe["tabela"],
            "properties": _propriedades(sink, classe),
        }],
        "quality": _qualidade(sink, classe_chave),
        "slas": slas,
        "customProperties": {
            "identidade": _lista(classe["chave_identidade"]),
            "resolucao": classe["resolucao"],
            "precedencia": _lista(classe.get("precedencia")),
            "fontes": [
                d["fonte_chave"] for d in repo.datasets_da_classe(sink, classe_chave)
            ],
            "calculados": _calculados(sink, classe_chave),
            "publicacao": dict(publicacao) if publicacao else None,
            "original": (
                "O arquivo que a fonte publicou é gravado intacto, com SHA-256, "
                "URL e instante de captura, e nunca é reescrito. Todo valor "
                "descrito acima é derivado dele e recomputável a partir dele."
            ),
        },
    }
