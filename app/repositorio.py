"""Leitura e escrita do plano de controle, com versionamento append-only.

Regra do versionamento: nada é editado no lugar. Salvar cria uma linha nova com
`versao + 1` e aposenta a anterior (`vigente = FALSE`, `vigente_chave = NULL`).
O dataset é versionado como agregado: suas colunas, campos calculados e regras
apontam para a *versão* do pai, então uma execução antiga continua enxergando
exatamente a configuração sob a qual rodou.
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator

from .sinks import Sink

log = logging.getLogger("portal.repositorio")


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
    classe: str = "escalar"        # escalar | janela | numerico
    tipo_retorno: str = "numeric"
    particao_por: list[str] | None = None
    ordena_por: list[str] | None = None
    # Frame da função de janela, ex.: "ROWS BETWEEN 20 PRECEDING AND CURRENT
    # ROW". Sem ele, ORDER BY acumula desde o início da partição.
    moldura: str | None = None
    # Uma linha nova muda o valor de linhas já gravadas? `is_latest` sim — a
    # reapresentação rebaixa a versão anterior. `hv21` não — o pregão de hoje
    # não altera a volatilidade de ontem. Quem não retroage só reescreve as
    # linhas da própria carga; quem retroage reescreve a tabela.
    retroage: bool = True
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
    # Valores que o template de URL da fonte pede além de {ano} e {janela}.
    parametros: dict[str, str] = field(default_factory=dict)
    # Regex casado contra a linha crua, só no formato de largura fixa. Serve
    # para separar tipos de registro que dividem o mesmo arquivo.
    filtro_linha: str | None = None
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
    # Ordem em que as fontes são consultadas para *este* atributo. Vazio
    # significa "usa a da classe" — precedência por fonte inteira é grosseira
    # demais: a melhor fonte para a razão social não é a melhor para o resto.
    precedencia: list[str] = field(default_factory=list)


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
    resolucao: str = "unica"       # unica | precedencia
    precedencia: list[str] = field(default_factory=list)
    descricao: str | None = None
    ativo: bool = True


@dataclass
class Fonte:
    chave: str
    nome: str
    tipo_transporte: str           # ver TRANSPORTES, abaixo
    url_template: str
    encoding: str = "utf-8"
    separador: str = ";"
    # Como ler os bytes de um membro: `csv` (separador), `larguras`
    # (posição declarada em cfg_coluna) ou `xml` (caminho declarado em
    # cfg_coluna, relativo ao elemento que o dataset nomeia em `registro`).
    # Ortogonal ao transporte — um ZIP pode trazer qualquer um dos três.
    formato_registro: str = "csv"
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
# `http_token` são duas requisições para um arquivo: a primeira devolve um
# bilhete em JSON, a segunda o troca pelos bytes. O nome do campo e o segundo
# endereço vivem nos parâmetros do mapeamento, não aqui — um transporte que
# soubesse o nome de uma fonte específica quebraria o engine único.
TRANSPORTES = ("http_zip", "http_csv", "http_json", "http_token")


def salvar_fonte(sink: Sink, f: Fonte, autor: str = "sistema") -> int:
    if f.tipo_transporte not in TRANSPORTES:
        raise ErroConfiguracao(
            f"tipo_transporte desconhecido: {f.tipo_transporte}. "
            f"Conhecidos: {', '.join(TRANSPORTES)}."
        )
    if f.formato_registro not in ("csv", "larguras", "xml"):
        raise ErroConfiguracao(
            f"formato_registro desconhecido: {f.formato_registro}. "
            f"Use 'csv', 'larguras' ou 'xml'."
        )
    versao = _aposentar(sink, "cfg_fonte", f.chave)
    novo_id = sink.proximo_id("cfg_fonte")
    sink.executar(
        """INSERT INTO cfg_fonte
           (id, nome, descricao, tipo_transporte, url_template, encoding,
            separador, formato_registro, credencial_ref, ativo, chave, versao,
            vigente, vigente_chave, criado_por)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,TRUE,?,?)""",
        (novo_id, f.nome, f.descricao, f.tipo_transporte, f.url_template,
         f.encoding, f.separador, f.formato_registro, f.credencial_ref,
         f.ativo, f.chave, versao, f.chave, autor),
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

# Coluna de sistema que uma classe pode indexar sem declarar como atributo.
# `captura_id` existe em toda tabela de classe (motor.ddl.COLUNAS_DE_SISTEMA)
# e é o filtro do `calcular` (`calculados._recorte`): sem índice, cada campo
# varre a tabela inteira para achar a carga do dia (24,5 s por varredura em
# `fato_negociacao`, medido em 2026-11-11).
COLUNAS_DE_SISTEMA_INDEXAVEIS = frozenset({"captura_id"})


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
        fora = [k for k in indice
                if k not in nomes and k not in COLUNAS_DE_SISTEMA_INDEXAVEIS]
        if fora:
            raise ErroConfiguracao(
                f"índice da classe '{c.chave}' cita atributo inexistente: "
                f"{', '.join(fora)}"
            )
    if c.resolucao not in ("unica", "precedencia"):
        raise ErroConfiguracao(
            f"classe '{c.chave}' declara resolução desconhecida: {c.resolucao}"
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
            resolucao, precedencia, ativo, chave, versao, vigente,
            vigente_chave, criado_por)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,TRUE,?,?)""",
        (novo_id, c.nome, c.descricao, c.tabela, ",".join(c.chave_identidade),
         ";".join(",".join(i) for i in c.indices), c.sla_horas, c.resolucao,
         ",".join(c.precedencia), c.ativo, c.chave, versao, c.chave, autor),
    )
    for a in c.atributos:
        sink.executar(
            """INSERT INTO cfg_atributo
               (id, classe_id, nome, tipo, origem, obrigatorio, guarda_texto,
                unidade, descricao, ordem, precedencia)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (sink.proximo_id("cfg_atributo"), novo_id, a.nome, a.tipo, a.origem,
             a.obrigatorio, a.guarda_texto, a.unidade, a.descricao, a.ordem,
             ",".join(a.precedencia)),
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


@dataclass
class Vista:
    """Uma vista de gold — o contrato que o consumidor lê.

    Fica ligada a uma classe porque é da tabela dela que a vista sai: é isso
    que permite publicar classe nova sem editar código de publicação.
    """

    chave: str
    classe_chave: str
    corpo: str                     # SQL com `{V}` no lugar da publicação
    descricao: str | None = None
    ordem: int = 0
    ativo: bool = True


def salvar_vista(sink: Sink, v: Vista, autor: str = "sistema") -> int:
    if "{V}" not in v.corpo:
        raise ErroConfiguracao(
            f"vista '{v.chave}' não usa o marcador {{V}}: sem ele a vista não "
            f"filtra por publicação e o gate de qualidade deixa de valer"
        )
    if not v.chave.replace("_", "").isalnum():
        raise ErroConfiguracao(f"nome de vista inválido: {v.chave}")
    versao = _aposentar(sink, "cfg_vista", v.chave)
    novo_id = sink.proximo_id("cfg_vista")
    sink.executar(
        """INSERT INTO cfg_vista
           (id, classe_chave, corpo, descricao, ordem, ativo, chave, versao,
            vigente, vigente_chave, criado_por)
           VALUES (?,?,?,?,?,?,?,?,TRUE,?,?)""",
        (novo_id, v.classe_chave, v.corpo, v.descricao, v.ordem, v.ativo,
         v.chave, versao, v.chave, autor),
    )
    return novo_id


def listar_vistas(sink: Sink, so_ativas: bool = True) -> list[dict]:
    sql = "SELECT * FROM cfg_vista WHERE vigente"
    if so_ativas:
        sql += " AND ativo"
    return sink.consultar(sql + " ORDER BY ordem, chave")


RELACIONAMENTOS = ("um_para_um", "um_para_muitos", "muitos_para_um")


@dataclass
class Correlacao:
    """Como duas classes se ligam, declarado em vez de escrito em SQL.

    Existe pelo mesmo motivo que a classe existe: enquanto a junção estiver na
    consulta de quem consome, ela é invisível para o escopo por classe da
    chave de API, e cada consumidor reinventa a ligação — inclusive errada.
    """

    chave: str
    classe_origem: str
    classe_destino: str
    atributo_origem: str
    atributo_destino: str
    relacionamento: str = "um_para_muitos"
    descricao: str | None = None
    ativo: bool = True


def validar_correlacao(sink: Sink, c: Correlacao) -> None:
    """Recusa na configuração o que só apareceria como número errado.

    A regra de fan-out vem do MetricFlow: uma junção só é segura quando o lado
    de destino não multiplica a linha de origem sem que isso esteja declarado.
    Aqui isso é explícito — quem declara `um_para_um` está afirmando que o
    atributo de destino é único, e a afirmação é conferida contra a chave de
    identidade da classe.
    """
    if c.relacionamento not in RELACIONAMENTOS:
        raise ErroConfiguracao(
            f"relacionamento '{c.relacionamento}' desconhecido; use um de: "
            + ", ".join(RELACIONAMENTOS)
        )
    for papel, classe_chave, atributo in (
        ("origem", c.classe_origem, c.atributo_origem),
        ("destino", c.classe_destino, c.atributo_destino),
    ):
        classe = classe_vigente(sink, classe_chave)
        if classe is None:
            raise ErroConfiguracao(
                f"classe de {papel} '{classe_chave}' não existe ou não está vigente"
            )
        nomes = {a["nome"] for a in atributos_de(sink, classe["id"])}
        if atributo not in nomes:
            raise ErroConfiguracao(
                f"a classe '{classe_chave}' não declara o atributo '{atributo}'"
            )
        if papel == "destino" and c.relacionamento == "um_para_um":
            identidade = [
                p for p in (classe["chave_identidade"] or "").split(",") if p
            ]
            if identidade != [atributo]:
                raise ErroConfiguracao(
                    f"'{atributo}' não é a identidade de '{classe_chave}' "
                    f"({', '.join(identidade)}), então a junção pode multiplicar "
                    f"a linha de origem: declare 'um_para_muitos'"
                )


def salvar_correlacao(sink: Sink, c: Correlacao, autor: str = "sistema") -> int:
    validar_correlacao(sink, c)
    versao = _aposentar(sink, "cfg_correlacao", c.chave)
    novo_id = sink.proximo_id("cfg_correlacao")
    sink.executar(
        """INSERT INTO cfg_correlacao
           (id, classe_origem, classe_destino, atributo_origem, atributo_destino,
            relacionamento, descricao, ativo, chave, versao,
            vigente, vigente_chave, criado_por)
           VALUES (?,?,?,?,?,?,?,?,?,?,TRUE,?,?)""",
        (novo_id, c.classe_origem, c.classe_destino, c.atributo_origem,
         c.atributo_destino, c.relacionamento, c.descricao, c.ativo,
         c.chave, versao, c.chave, autor),
    )
    return novo_id


def listar_correlacoes(sink: Sink, so_ativas: bool = True) -> list[dict]:
    sql = "SELECT * FROM cfg_correlacao WHERE vigente"
    if so_ativas:
        sql += " AND ativo"
    return sink.consultar(sql + " ORDER BY chave")


def correlacao_vigente(sink: Sink, chave: str) -> dict | None:
    return sink.um(
        "SELECT * FROM cfg_correlacao WHERE chave = ? AND vigente", (chave,)
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
            parametros, filtro_linha, chave, versao, vigente, vigente_chave,
            criado_por)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,TRUE,?,?)""",
        (novo_id, d.fonte_chave, d.nome, d.descricao, d.padrao_arquivo,
         d.tabela_destino, ",".join(d.chave_natural), d.politica_versao,
         d.particao, d.ativo, d.classe_chave, json.dumps(d.parametros),
         d.filtro_linha, d.chave, versao, d.chave, autor),
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
                tipo_retorno, particao_por, ordena_por, moldura, retroage,
                materializacao, descricao, ativo, ordem)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (sink.proximo_id("cfg_campo_calculado"), novo_id, cc.nome, cc.classe,
             cc.expressao, ",".join(cc.colunas_origem), cc.tipo_retorno,
             ",".join(cc.particao_por) if cc.particao_por else None,
             ",".join(cc.ordena_por) if cc.ordena_por else None,
             cc.moldura, cc.retroage, cc.materializacao, cc.descricao,
             cc.ativo, cc.ordem),
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


# Estados em que a execução acabou. `capturado` NÃO está aqui de propósito:
# uma carga `apenas_bronze` termina nele, mas com `terminado_em` preenchido —
# por isso "não terminal" é `terminado_em IS NULL` além do status.
ESTADOS_TERMINAIS = ("publicado", "bloqueada", "falha")
_NAO_TERMINAL = (
    "terminado_em IS NULL AND status NOT IN ("
    + ",".join(f"'{e}'" for e in ESTADOS_TERMINAIS) + ")"
)


def _agora_utc(agora: datetime | None) -> datetime:
    return (agora or datetime.now(timezone.utc)).astimezone(timezone.utc)


def abandonar_execucoes(
    sink: Sink, horas: float, agora: datetime | None = None,
) -> list[int]:
    """Reaper: execução não terminal iniciada há mais de `horas` vira `falha`.

    O processo que a tocava morreu (deploy, OOM, timeout do cron) e não há
    quem a feche: sem isto ela fica em `recomputando` para sempre, e o
    agendador — que não dispara dataset com execução em curso — o trava junto.

    Idempotente: a linha já sai do conjunto "não terminal". Devolve os ids
    fechados. O corte entra como parâmetro com fuso, sem aritmética de
    interval, para o mesmo SQL valer em DuckDB e Postgres.
    """
    agora = _agora_utc(agora)
    corte = agora - timedelta(hours=horas)
    ids = [
        r["id"] for r in sink.consultar(
            f"SELECT id FROM log_execucao WHERE {_NAO_TERMINAL} "
            f"AND iniciado_em < ? ORDER BY id",
            (corte,),
        )
    ]
    for exec_id in ids:
        # Repete o filtro: entre o SELECT e o UPDATE o dono legítimo pode ter
        # terminado, e fechar como `falha` uma execução `publicada` seria pior.
        sink.executar(
            f"UPDATE log_execucao SET status = 'falha', erro = ?, "
            f"terminado_em = ? WHERE id = ? AND {_NAO_TERMINAL}",
            ("abandonada (reaper)", agora, exec_id),
        )
    return ids


def execucao_em_andamento(
    sink: Sink, dataset_chave: str, horas: float, agora: datetime | None = None,
) -> dict | None:
    """A execução não terminal mais recente do dataset que ainda pode estar
    viva (iniciada há menos de `horas`), ou `None`. Complemento exato do
    reaper: o que ele ainda não fechou é o que bloqueia um novo disparo."""
    corte = _agora_utc(agora) - timedelta(hours=horas)
    return sink.um(
        f"SELECT id, janela, status, iniciado_em FROM log_execucao "
        f"WHERE dataset_chave = ? AND {_NAO_TERMINAL} AND iniciado_em >= ? "
        f"ORDER BY id DESC LIMIT 1",
        (dataset_chave, corte),
    )


def janelas_publicadas(sink: Sink, dataset_chave: str) -> list[str]:
    return [
        r["janela"] for r in sink.consultar(
            "SELECT DISTINCT janela FROM log_execucao "
            "WHERE dataset_chave = ? AND status = 'publicado'",
            (dataset_chave,),
        )
    ]


# --------------------------------------------------------------------------
# Trava por dataset+janela
# --------------------------------------------------------------------------
# Duas cargas da mesma janela escrevem nas mesmas linhas e se enroscam
# (`DeadlockDetected` em `cvm_itr`/2026, 04/08). No Postgres a trava é advisory
# lock de **sessão** (some sozinha se o processo morrer, ao contrário de uma
# linha de status). Como ela é reentrante na mesma conexão, também há um
# registro em processo — que é a checagem equivalente no DuckDB, onde só existe
# um processo, e o que protege dois usos do mesmo sink.
_TRAVAS_EM_PROCESSO: set[tuple[str, str]] = set()
_TRAVAS_LOCK = threading.Lock()


def chave_trava(dataset_chave: str, janela: str) -> int:
    """Chave `bigint` estável entre processos. `hash()` muda a cada processo."""
    digest = hashlib.blake2b(
        f"mydata:execucao:{dataset_chave}:{janela}".encode(), digest_size=8
    ).digest()
    return int.from_bytes(digest, "big", signed=True)


@contextmanager
def trava_execucao(sink: Sink, dataset_chave: str, janela: str) -> Iterator[bool]:
    """`with trava_execucao(...) as obtida:` — `False` se outra carga da mesma
    janela está rodando; nesse caso nada foi travado nem precisa ser solto."""
    id_local = (dataset_chave, janela)
    with _TRAVAS_LOCK:
        ocupada = id_local in _TRAVAS_EM_PROCESSO
        if not ocupada:
            _TRAVAS_EM_PROCESSO.add(id_local)
    if ocupada:
        yield False
        return
    no_banco = False
    try:
        if sink.dialeto == "postgres":
            no_banco = bool((sink.um(
                "SELECT pg_try_advisory_lock(CAST(? AS bigint)) AS ok",
                (chave_trava(dataset_chave, janela),),
            ) or {}).get("ok"))
            if not no_banco:
                yield False
                return
        yield True
    finally:
        try:
            if no_banco:
                sink.um(
                    "SELECT pg_advisory_unlock(CAST(? AS bigint)) AS ok",
                    (chave_trava(dataset_chave, janela),),
                )
        except Exception as e:  # noqa: BLE001 — soltar não pode mascarar a causa
            log.warning("não consegui soltar a trava de %s/%s: %s",
                        dataset_chave, janela, e)
        finally:
            with _TRAVAS_LOCK:
                _TRAVAS_EM_PROCESSO.discard(id_local)


def execucoes(sink: Sink, limite: int = 50, dataset_chave: str | None = None,
              status: list[str] | None = None) -> list[dict]:
    onde, params = [], []
    if dataset_chave:
        onde.append("dataset_chave = ?")
        params.append(dataset_chave)
    if status:
        onde.append(f"status IN ({','.join('?' for _ in status)})")
        params += status
    filtro = f"WHERE {' AND '.join(onde)} " if onde else ""
    return sink.consultar(
        f"SELECT * FROM log_execucao {filtro}ORDER BY id DESC LIMIT ?",
        (*params, limite),
    )
