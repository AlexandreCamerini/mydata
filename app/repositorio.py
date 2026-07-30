"""Leitura e escrita do plano de controle, com versionamento append-only.

Regra do versionamento: nada é editado no lugar. Salvar cria uma linha nova com
`versao + 1` e aposenta a anterior (`vigente = FALSE`, `vigente_chave = NULL`).
O dataset é versionado como agregado: suas colunas, campos calculados e regras
apontam para a *versão* do pai, então uma execução antiga continua enxergando
exatamente a configuração sob a qual rodou.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from .sinks import Sink


class ErroConfiguracao(ValueError):
    """Configuração inválida — recusada antes de tocar em dado."""


# --------------------------------------------------------------------------
# Estruturas
# --------------------------------------------------------------------------
@dataclass
class Coluna:
    nome_origem: str
    nome_destino: str
    tipo: str = "texto"            # texto | inteiro | numero | data | booleano
    formato: str | None = None     # decimal_ptbr | data_iso | ...
    obrigatoria: bool = False
    ordem: int = 0


@dataclass
class CampoCalculado:
    nome: str
    expressao: str
    colunas_origem: list[str]
    classe: str = "escalar"        # escalar | janela
    tipo_retorno: str = "numeric"
    particao_por: list[str] | None = None
    ordena_por: list[str] | None = None
    materializacao: str = "coluna"
    descricao: str | None = None
    ativo: bool = True
    ordem: int = 0


@dataclass
class RegraQualidade:
    nome: str
    expressao_sql: str             # deve retornar 0 linhas quando está tudo bem
    severidade: str = "alerta"     # informa | alerta | bloqueia
    tolerancia: float = 0.0
    descricao: str | None = None
    ativo: bool = True


@dataclass
class Dataset:
    chave: str
    fonte_chave: str
    nome: str
    padrao_arquivo: str
    tabela_destino: str
    chave_natural: list[str]
    classe_chave: str | None = None
    colunas: list[Coluna] = field(default_factory=list)
    calculados: list[CampoCalculado] = field(default_factory=list)
    regras: list[RegraQualidade] = field(default_factory=list)
    politica_versao: str = "max_versao"
    particao: str = "ano"
    descricao: str | None = None
    ativo: bool = True


@dataclass
class Atributo:
    """Um campo da classe de informação, independente de quem o alimenta."""

    nome: str
    tipo: str = "texto"            # texto | inteiro | numero | data | booleano
    origem: str = "fonte"          # fonte | calculado
    obrigatorio: bool = False
    guarda_texto: bool = False     # mantém a representação original em <nome>_txt
    unidade: str | None = None
    descricao: str | None = None
    ordem: int = 0


@dataclass
class Classe:
    """Uma coisa sobre a qual o portal guarda informação — Empresa, Cotação,
    Demonstração Financeira. Vive acima do dataset: uma classe é alimentada
    por N fontes, e é dela que sai a tabela física."""

    chave: str
    nome: str
    tabela: str
    chave_identidade: list[str]
    atributos: list[Atributo] = field(default_factory=list)
    indices: list[list[str]] = field(default_factory=list)
    sla_horas: int | None = None
    descricao: str | None = None
    ativo: bool = True


@dataclass
class Fonte:
    chave: str
    nome: str
    tipo_transporte: str           # http_zip | http_csv
    url_template: str
    encoding: str = "utf-8"
    separador: str = ";"
    credencial_ref: str | None = None
    descricao: str | None = None
    ativo: bool = True


# --------------------------------------------------------------------------
# Versionamento
# --------------------------------------------------------------------------
def _aposentar(sink: Sink, tabela: str, chave: str) -> int:
    """Marca a versão vigente como superada e devolve o número da próxima."""
    atual = sink.um(
        f"SELECT versao FROM {tabela} WHERE chave = ? AND vigente ORDER BY versao DESC",
        (chave,),
    )
    if atual:
        sink.executar(
            f"UPDATE {tabela} SET vigente = FALSE, vigente_chave = NULL "
            f"WHERE chave = ? AND vigente",
            (chave,),
        )
        return int(atual["versao"]) + 1
    return 1


# --------------------------------------------------------------------------
# Fonte
# --------------------------------------------------------------------------
def salvar_fonte(sink: Sink, f: Fonte, autor: str = "sistema") -> int:
    if f.tipo_transporte not in ("http_zip", "http_csv"):
        raise ErroConfiguracao(f"tipo_transporte desconhecido: {f.tipo_transporte}")
    versao = _aposentar(sink, "cfg_fonte", f.chave)
    novo_id = sink.proximo_id("cfg_fonte")
    sink.executar(
        """INSERT INTO cfg_fonte
           (id, nome, descricao, tipo_transporte, url_template, encoding,
            separador, credencial_ref, ativo, chave, versao, vigente,
            vigente_chave, criado_por)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,TRUE,?,?)""",
        (novo_id, f.nome, f.descricao, f.tipo_transporte, f.url_template,
         f.encoding, f.separador, f.credencial_ref, f.ativo, f.chave, versao,
         f.chave, autor),
    )
    return novo_id


def fonte_vigente(sink: Sink, chave: str) -> dict | None:
    return sink.um("SELECT * FROM cfg_fonte WHERE chave = ? AND vigente", (chave,))


def listar_fontes(sink: Sink) -> list[dict]:
    return sink.consultar("SELECT * FROM cfg_fonte WHERE vigente ORDER BY chave")


# --------------------------------------------------------------------------
# Classe de informação (agregado)
# --------------------------------------------------------------------------
TIPOS_ATRIBUTO = ("texto", "inteiro", "numero", "data", "booleano")


def validar_classe(c: Classe) -> None:
    nomes = [a.nome for a in c.atributos]
    if not nomes:
        raise ErroConfiguracao(f"classe '{c.chave}' não declara nenhum atributo")
    repetidos = {n for n in nomes if nomes.count(n) > 1}
    if repetidos:
        raise ErroConfiguracao(
            f"classe '{c.chave}' declara atributo repetido: {', '.join(sorted(repetidos))}"
        )
    for a in c.atributos:
        if a.tipo not in TIPOS_ATRIBUTO:
            raise ErroConfiguracao(
                f"atributo '{a.nome}' tem tipo desconhecido '{a.tipo}'. "
                f"Use um de: {', '.join(TIPOS_ATRIBUTO)}"
            )
    if not c.chave_identidade:
        raise ErroConfiguracao(
            f"classe '{c.chave}' precisa de chave de identidade: é ela que diz "
            f"quando duas linhas falam da mesma coisa"
        )
    ausentes = [k for k in c.chave_identidade if k not in nomes]
    if ausentes:
        raise ErroConfiguracao(
            f"chave de identidade da classe '{c.chave}' cita atributo "
            f"inexistente: {', '.join(ausentes)}"
        )
    for indice in c.indices:
        fora = [k for k in indice if k not in nomes]
        if fora:
            raise ErroConfiguracao(
                f"índice da classe '{c.chave}' cita atributo inexistente: "
                f"{', '.join(fora)}"
            )
    if not c.tabela.replace("_", "").isalnum():
        raise ErroConfiguracao(
            f"nome de tabela inválido para a classe '{c.chave}': {c.tabela}"
        )


def salvar_classe(sink: Sink, c: Classe, autor: str = "sistema") -> int:
    validar_classe(c)
    versao = _aposentar(sink, "cfg_classe", c.chave)
    novo_id = sink.proximo_id("cfg_classe")
    sink.executar(
        """INSERT INTO cfg_classe
           (id, nome, descricao, tabela, chave_identidade, indices, sla_horas,
            ativo, chave, versao, vigente, vigente_chave, criado_por)
           VALUES (?,?,?,?,?,?,?,?,?,?,TRUE,?,?)""",
        (novo_id, c.nome, c.descricao, c.tabela, ",".join(c.chave_identidade),
         ";".join(",".join(i) for i in c.indices), c.sla_horas, c.ativo,
         c.chave, versao, c.chave, autor),
    )
    for a in c.atributos:
        sink.executar(
            """INSERT INTO cfg_atributo
               (id, classe_id, nome, tipo, origem, obrigatorio, guarda_texto,
                unidade, descricao, ordem) VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (sink.proximo_id("cfg_atributo"), novo_id, a.nome, a.tipo, a.origem,
             a.obrigatorio, a.guarda_texto, a.unidade, a.descricao, a.ordem),
        )
    return novo_id


def classe_vigente(sink: Sink, chave: str) -> dict | None:
    return sink.um("SELECT * FROM cfg_classe WHERE chave = ? AND vigente", (chave,))


def listar_classes(sink: Sink, so_ativas: bool = False) -> list[dict]:
    sql = "SELECT * FROM cfg_classe WHERE vigente"
    if so_ativas:
        sql += " AND ativo"
    return sink.consultar(sql + " ORDER BY chave")


def atributos_de(sink: Sink, classe_id: int) -> list[dict]:
    return sink.consultar(
        "SELECT * FROM cfg_atributo WHERE classe_id = ? ORDER BY ordem, id",
        (classe_id,),
    )


def datasets_da_classe(sink: Sink, classe_chave: str) -> list[dict]:
    return sink.consultar(
        "SELECT * FROM cfg_dataset WHERE vigente AND classe_chave = ? ORDER BY chave",
        (classe_chave,),
    )


def indices_de(classe: dict) -> list[list[str]]:
    bruto = classe.get("indices") or ""
    return [
        [c.strip() for c in grupo.split(",") if c.strip()]
        for grupo in bruto.split(";")
        if grupo.strip()
    ]


# --------------------------------------------------------------------------
# Dataset (agregado)
# --------------------------------------------------------------------------
def validar_dataset(d: Dataset) -> None:
    """Recusa configuração incoerente antes de gravar."""
    destinos = {c.nome_destino for c in d.colunas}
    if not destinos:
        raise ErroConfiguracao(f"dataset '{d.chave}' não declara nenhuma coluna")

    faltando = [c for c in d.chave_natural if c not in destinos]
    if faltando:
        raise ErroConfiguracao(
            f"chave natural do dataset '{d.chave}' referencia coluna inexistente: "
            f"{', '.join(faltando)}"
        )

    # Um campo calculado pode referenciar colunas da fonte e campos calculados
    # declarados antes dele — daí a validação incremental, na ordem.
    conhecidas = set(destinos)
    for cc in sorted(d.calculados, key=lambda x: x.ordem):
        ausentes = [c for c in cc.colunas_origem if c not in conhecidas]
        if ausentes:
            raise ErroConfiguracao(
                f"campo calculado '{cc.nome}' referencia coluna inexistente: "
                f"{', '.join(ausentes)}"
            )
        if cc.classe == "janela" and not cc.particao_por:
            raise ErroConfiguracao(
                f"campo calculado '{cc.nome}' é de janela e precisa de particao_por"
            )
        if cc.classe == "escalar" and (cc.particao_por or cc.ordena_por):
            raise ErroConfiguracao(
                f"campo calculado '{cc.nome}' é escalar e não aceita "
                f"particao_por/ordena_por"
            )
        conhecidas.add(cc.nome)

    for r in d.regras:
        if r.severidade not in ("informa", "alerta", "bloqueia"):
            raise ErroConfiguracao(f"severidade inválida em '{r.nome}': {r.severidade}")


def salvar_dataset(sink: Sink, d: Dataset, autor: str = "sistema") -> int:
    validar_dataset(d)
    versao = _aposentar(sink, "cfg_dataset", d.chave)
    novo_id = sink.proximo_id("cfg_dataset")
    sink.executar(
        """INSERT INTO cfg_dataset
           (id, fonte_chave, nome, descricao, padrao_arquivo, tabela_destino,
            chave_natural, politica_versao, particao, ativo, classe_chave,
            chave, versao, vigente, vigente_chave, criado_por)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,TRUE,?,?)""",
        (novo_id, d.fonte_chave, d.nome, d.descricao, d.padrao_arquivo,
         d.tabela_destino, ",".join(d.chave_natural), d.politica_versao,
         d.particao, d.ativo, d.classe_chave, d.chave, versao, d.chave, autor),
    )
    for c in d.colunas:
        sink.executar(
            """INSERT INTO cfg_coluna
               (id, dataset_id, nome_origem, nome_destino, tipo, formato,
                obrigatoria, ordem) VALUES (?,?,?,?,?,?,?,?)""",
            (sink.proximo_id("cfg_coluna"), novo_id, c.nome_origem,
             c.nome_destino, c.tipo, c.formato, c.obrigatoria, c.ordem),
        )
    for cc in d.calculados:
        sink.executar(
            """INSERT INTO cfg_campo_calculado
               (id, dataset_id, nome, classe, expressao, colunas_origem,
                tipo_retorno, particao_por, ordena_por, materializacao,
                descricao, ativo, ordem) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (sink.proximo_id("cfg_campo_calculado"), novo_id, cc.nome, cc.classe,
             cc.expressao, ",".join(cc.colunas_origem), cc.tipo_retorno,
             ",".join(cc.particao_por) if cc.particao_por else None,
             ",".join(cc.ordena_por) if cc.ordena_por else None,
             cc.materializacao, cc.descricao, cc.ativo, cc.ordem),
        )
    for r in d.regras:
        sink.executar(
            """INSERT INTO cfg_regra_qualidade
               (id, dataset_id, nome, expressao_sql, severidade, tolerancia,
                descricao, ativo) VALUES (?,?,?,?,?,?,?,?)""",
            (sink.proximo_id("cfg_regra_qualidade"), novo_id, r.nome,
             r.expressao_sql, r.severidade, r.tolerancia, r.descricao, r.ativo),
        )
    return novo_id


def dataset_vigente(sink: Sink, chave: str) -> dict | None:
    return sink.um("SELECT * FROM cfg_dataset WHERE chave = ? AND vigente", (chave,))


def listar_datasets(sink: Sink) -> list[dict]:
    return sink.consultar("SELECT * FROM cfg_dataset WHERE vigente ORDER BY chave")


def colunas_do(sink: Sink, dataset_id: int) -> list[dict]:
    return sink.consultar(
        "SELECT * FROM cfg_coluna WHERE dataset_id = ? ORDER BY ordem, id",
        (dataset_id,),
    )


def calculados_do(sink: Sink, dataset_id: int, so_ativos: bool = True) -> list[dict]:
    sql = "SELECT * FROM cfg_campo_calculado WHERE dataset_id = ?"
    if so_ativos:
        sql += " AND ativo"
    return sink.consultar(sql + " ORDER BY ordem, id", (dataset_id,))


def regras_do(sink: Sink, dataset_id: int, so_ativas: bool = True) -> list[dict]:
    sql = "SELECT * FROM cfg_regra_qualidade WHERE dataset_id = ?"
    if so_ativas:
        sql += " AND ativo"
    return sink.consultar(sql + " ORDER BY id", (dataset_id,))


def snapshot_config(sink: Sink, dataset_id: int) -> str:
    """Fotografia da configuração usada numa execução, para reprodutibilidade."""
    ds = sink.um("SELECT * FROM cfg_dataset WHERE id = ?", (dataset_id,))
    if ds is None:
        return "{}"
    fonte = fonte_vigente(sink, ds["fonte_chave"])
    return json.dumps(
        {
            "dataset": {"chave": ds["chave"], "versao": ds["versao"], "id": ds["id"]},
            "fonte": (
                {"chave": fonte["chave"], "versao": fonte["versao"]} if fonte else None
            ),
            "colunas": [c["nome_destino"] for c in colunas_do(sink, dataset_id)],
            "calculados": [
                {"nome": c["nome"], "classe": c["classe"]}
                for c in calculados_do(sink, dataset_id)
            ],
            "regras": [
                {"nome": r["nome"], "severidade": r["severidade"]}
                for r in regras_do(sink, dataset_id)
            ],
        },
        ensure_ascii=False,
        sort_keys=True,
    )


# --------------------------------------------------------------------------
# Agendamento
# --------------------------------------------------------------------------
def salvar_agendamento(
    sink: Sink, chave: str, dataset_chave: str, cron: str,
    timezone: str = "America/Sao_Paulo", janela_padrao: str = "ano_corrente",
    ativo: bool = True, autor: str = "sistema",
) -> int:
    versao = _aposentar(sink, "cfg_agendamento", chave)
    novo_id = sink.proximo_id("cfg_agendamento")
    sink.executar(
        """INSERT INTO cfg_agendamento
           (id, dataset_chave, cron, timezone, janela_padrao, ativo, chave,
            versao, vigente, vigente_chave, criado_por)
           VALUES (?,?,?,?,?,?,?,?,TRUE,?,?)""",
        (novo_id, dataset_chave, cron, timezone, janela_padrao, ativo, chave,
         versao, chave, autor),
    )
    return novo_id


def listar_agendamentos(sink: Sink) -> list[dict]:
    return sink.consultar("SELECT * FROM cfg_agendamento WHERE vigente ORDER BY chave")


# --------------------------------------------------------------------------
# Execuções
# --------------------------------------------------------------------------
def abrir_execucao(
    sink: Sink, dataset_chave: str, dataset_id: int, janela: str,
    trigger_tipo: str = "manual",
) -> int:
    exec_id = sink.proximo_id("log_execucao")
    sink.executar(
        """INSERT INTO log_execucao
           (id, dataset_chave, dataset_id, janela, status, trigger_tipo,
            cfg_snapshot) VALUES (?,?,?,?,'pendente',?,?)""",
        (exec_id, dataset_chave, dataset_id, janela, trigger_tipo,
         snapshot_config(sink, dataset_id)),
    )
    return exec_id


def atualizar_execucao(sink: Sink, exec_id: int, **campos: Any) -> None:
    if not campos:
        return
    sets = ", ".join(f"{k} = ?" for k in campos)
    sink.executar(
        f"UPDATE log_execucao SET {sets} WHERE id = ?",
        (*campos.values(), exec_id),
    )


def execucoes(sink: Sink, limite: int = 50, dataset_chave: str | None = None) -> list[dict]:
    if dataset_chave:
        return sink.consultar(
            "SELECT * FROM log_execucao WHERE dataset_chave = ? "
            "ORDER BY id DESC LIMIT ?",
            (dataset_chave, limite),
        )
    return sink.consultar(
        "SELECT * FROM log_execucao ORDER BY id DESC LIMIT ?", (limite,)
    )
