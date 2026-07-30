"""A tabela física como consequência da classe declarada.

Enquanto `CREATE TABLE fato_conta (...)` estiver escrito à mão numa migração,
cadastrar uma classe de informação nova pela interface exige deploy. Este
módulo tira o DDL do código e o deriva de `cfg_classe` / `cfg_atributo`.

Três colunas de sistema entram sempre, porque o resto do motor depende delas
e nenhuma é assunto de quem modela o domínio:

- `captura_id` e `fonte_arquivo` ligam a linha à captura em bronze que a
  produziu. É o que permite recomputar uma janela e descartar carga reprovada.
- `publicado_em_versao` é o rótulo do gate de qualidade: linha sem rótulo
  existe em silver e não aparece em gold.

`carregado_em` completa o conjunto para diagnóstico. Nenhuma delas é atributo
da classe — `empresa` não tem "id da captura" como característica.
"""
from __future__ import annotations

import logging

from .. import repositorio as repo
from ..sinks import Sink, render

log = logging.getLogger("portal.ddl")

# Atributo declarado -> tipo do dialeto. `data` vira texto de propósito: o
# parsing devolve ISO como string para os dois sinks concordarem sobre o valor.
TIPO_DDL = {
    "texto": "{TEXTO}",
    "inteiro": "{INT}",
    "numero": "{NUM}",
    "data": "{TEXTO}",
    "booleano": "{BOOL}",
}

COLUNAS_DE_SISTEMA: list[tuple[str, str]] = [
    ("captura_id", "{INT} NOT NULL"),
    ("fonte_arquivo", "{TEXTO} NOT NULL"),
    ("carregado_em", "{TSTZ} NOT NULL DEFAULT {AGORA}"),
    ("publicado_em_versao", "{INT}"),
]


def colunas_da_classe(atributos: list[dict]) -> list[tuple[str, str]]:
    """(nome, tipo) de toda coluna que a classe implica, sistema incluído.

    Um atributo com `guarda_texto` ganha a coluna sombra `<nome>_txt`: é onde
    a representação original do arquivo fica intacta ao lado do valor
    convertido. Converter tipo é conversão de representação, não
    transformação de dado — a sombra é o que torna isso verificável.
    """
    colunas = list(COLUNAS_DE_SISTEMA)
    for a in sorted(atributos, key=lambda x: (x["ordem"], x["id"])):
        tipo = TIPO_DDL.get(a["tipo"])
        if tipo is None:
            raise repo.ErroConfiguracao(
                f"atributo '{a['nome']}' tem tipo sem correspondente físico: "
                f"{a['tipo']}"
            )
        colunas.append((a["nome"], tipo))
        if a["guarda_texto"]:
            colunas.append((f"{a['nome']}_txt", "{TEXTO}"))
    return colunas


def sentencas_da_classe(classe: dict, atributos: list[dict]) -> list[str]:
    """DDL completo da classe: tabela, unicidade da identidade e índices."""
    tabela = classe["tabela"]
    colunas = colunas_da_classe(atributos)
    corpo = ",\n  ".join(f"{nome} {tipo}" for nome, tipo in colunas)
    identidade = [
        c.strip() for c in classe["chave_identidade"].split(",") if c.strip()
    ]
    sentencas = [
        f"CREATE TABLE IF NOT EXISTS {tabela} (\n  {corpo}\n)",
        f"CREATE UNIQUE INDEX IF NOT EXISTS ux_{tabela}_identidade "
        f"ON {tabela} ({', '.join(identidade)})",
        f"CREATE INDEX IF NOT EXISTS ix_{tabela}_publicado "
        f"ON {tabela} (publicado_em_versao)",
    ]
    for numero, grupo in enumerate(repo.indices_de(classe), start=1):
        sentencas.append(
            f"CREATE INDEX IF NOT EXISTS ix_{tabela}_{numero} "
            f"ON {tabela} ({', '.join(grupo)})"
        )
    return sentencas


def colunas_fisicas(sink: Sink, tabela: str) -> dict[str, str]:
    linhas = sink.consultar(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_name = ?",
        (tabela,),
    )
    return {linha["column_name"]: linha["data_type"].lower() for linha in linhas}


def divergencias(sink: Sink, classe: dict, atributos: list[dict]) -> list[str]:
    """O que a classe declara e a tabela não tem, e vice-versa.

    Lista vazia significa que a configuração é espelho fiel do banco. É a
    verificação que autoriza a configuração a assumir o lugar do DDL escrito
    à mão: um gerador que não reproduz a tabela existente não está pronto
    para passar a ser dono dela.
    """
    fisicas = colunas_fisicas(sink, classe["tabela"])
    if not fisicas:
        return [f"tabela '{classe['tabela']}' não existe"]
    declaradas = {nome for nome, _ in colunas_da_classe(atributos)}
    faltando = sorted(declaradas - set(fisicas))
    sobrando = sorted(set(fisicas) - declaradas)
    problemas = [f"declarado e ausente na tabela: {c}" for c in faltando]
    problemas += [f"na tabela e não declarado: {c}" for c in sobrando]
    return problemas


def garantir_tabela(sink: Sink, classe: dict, atributos: list[dict]) -> list[str]:
    """Aplica o DDL da classe. Idempotente: rodar de novo é no-op."""
    aplicadas = []
    for sentenca in sentencas_da_classe(classe, atributos):
        sink.executar(render(sentenca, sink.dialeto))
        aplicadas.append(sentenca.split("\n")[0])
    return aplicadas


def garantir_classes(sink: Sink) -> dict[str, list[str]]:
    """Materializa toda classe cadastrada. Chamado no boot e ao salvar classe."""
    saida: dict[str, list[str]] = {}
    for classe in repo.listar_classes(sink, so_ativas=True):
        atributos = repo.atributos_de(sink, classe["id"])
        if not atributos:
            continue
        saida[classe["chave"]] = garantir_tabela(sink, classe, atributos)
        log.info("classe materializada: %s -> %s", classe["chave"], classe["tabela"])
    return saida
