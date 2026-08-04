"""Plano de controle sobre HTTP — o que as telas de configuração consomem.

Separado de `/v1` de propósito: público lê dado, administração muda
configuração. Escrita exige `PORTAL_ADMIN_TOKEN`.
"""
from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from .. import repositorio as repo
from ..motor import credenciais, ddl, ingestao, observabilidade, publicacao
from ..repositorio import (
    CampoCalculado, Coluna, Dataset, ErroConfiguracao, Fonte, RegraQualidade,
)
from ..sinks import Sink
from . import auth, metricas

async def exigir_admin(
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> None:
    esperado = os.getenv("PORTAL_ADMIN_TOKEN")
    if not esperado:
        return  # dev: sem token configurado, administração fica aberta local
    if x_admin_token != esperado:
        raise HTTPException(
            status_code=401,
            detail={"codigo": "admin_nao_autorizado",
                    "mensagem": "Informe X-Admin-Token válido."},
        )


# O token protege o router inteiro, não só a escrita. Ler a configuração, o
# histórico de execução e — pior — a amostra de qualquer tabela via
# `/catalogo/{tabela}` contorna o escopo por classe das chaves de API. Sem
# PORTAL_ADMIN_TOKEN definido, `exigir_admin` libera: é o modo de
# desenvolvimento local, e a ausência da variável é a escolha explícita.
router = APIRouter(
    prefix="/admin/api",
    tags=["administração"],
    dependencies=[Depends(exigir_admin)],
)


def obter_sink(request: Request) -> Sink:
    return request.app.state.sink


# --------------------------------------------------------------------------
# Modelos de entrada
# --------------------------------------------------------------------------
class FonteEntrada(BaseModel):
    chave: str
    nome: str
    tipo_transporte: str = "http_zip"
    url_template: str
    encoding: str = "utf-8"
    separador: str = ";"
    # Nome da variável de ambiente que guarda o token, nunca o token. Aceita
    # `VARIAVEL`, `bearer:VARIAVEL`, `header:Nome:VARIAVEL` ou
    # `query:nome:VARIAVEL` — ver `app/motor/credenciais.py`.
    credencial_ref: str | None = None
    descricao: str | None = None
    ativo: bool = True


class ColunaEntrada(BaseModel):
    nome_origem: str
    nome_destino: str
    tipo: str = "texto"
    formato: str | None = None
    obrigatoria: bool = False
    ordem: int = 0


class CalculadoEntrada(BaseModel):
    nome: str
    expressao: str
    colunas_origem: list[str]
    classe: str = "escalar"
    tipo_retorno: str = "numeric"
    particao_por: list[str] | None = None
    ordena_por: list[str] | None = None
    materializacao: str = "coluna"
    descricao: str | None = None
    ativo: bool = True
    ordem: int = 0


class RegraEntrada(BaseModel):
    nome: str
    expressao_sql: str
    severidade: str = "alerta"
    tolerancia: float = 0.0
    descricao: str | None = None
    ativo: bool = True


class DatasetEntrada(BaseModel):
    chave: str
    fonte_chave: str
    nome: str
    padrao_arquivo: str
    tabela_destino: str
    chave_natural: list[str]
    classe_chave: str | None = None
    politica_versao: str = "max_versao"
    particao: str = "ano"
    parametros: dict[str, str] = Field(default_factory=dict)
    colunas: list[ColunaEntrada] = Field(default_factory=list)
    calculados: list[CalculadoEntrada] = Field(default_factory=list)
    regras: list[RegraEntrada] = Field(default_factory=list)
    descricao: str | None = None
    ativo: bool = True


class AtributoEntrada(BaseModel):
    nome: str
    tipo: str = "texto"
    origem: str = "fonte"
    obrigatorio: bool = False
    guarda_texto: bool = False
    unidade: str | None = None
    descricao: str | None = None
    ordem: int = 0
    # Vazio herda a precedência da classe.
    precedencia: list[str] = Field(default_factory=list)


class ClasseEntrada(BaseModel):
    chave: str
    nome: str
    tabela: str
    chave_identidade: list[str]
    atributos: list[AtributoEntrada] = Field(default_factory=list)
    indices: list[list[str]] = Field(default_factory=list)
    sla_horas: int | None = None
    resolucao: str = "unica"
    precedencia: list[str] = Field(default_factory=list)
    descricao: str | None = None
    ativo: bool = True


class ChaveEntrada(BaseModel):
    consumidor: str
    quota_minuto: int = 120
    quota_dia: int = 50000
    # Vazio = leitura de tudo. Preenchido, restringe às classes nomeadas —
    # é o contrato de cada app consumidor.
    classes: list[str] = Field(default_factory=list)


class ExecucaoEntrada(BaseModel):
    dataset_chave: str
    janela: str
    baixar: bool = True


class MetricaEntrada(BaseModel):
    chave: str
    nome: str
    formula: str
    unidade: str = "razao"
    descricao: str | None = None
    ativo: bool = True


def _erro_config(e: ErroConfiguracao) -> HTTPException:
    return HTTPException(
        status_code=422,
        detail={"codigo": "configuracao_invalida", "mensagem": str(e)},
    )


# --------------------------------------------------------------------------
# Classes de informação
# --------------------------------------------------------------------------
@router.get("/classes")
async def get_classes(request: Request) -> Any:
    sink = obter_sink(request)
    saida = []
    for c in repo.listar_classes(sink):
        atributos = repo.atributos_de(sink, c["id"])
        saida.append({
            **c,
            "atributos": atributos,
            "datasets": [d["chave"] for d in repo.datasets_da_classe(sink, c["chave"])],
            "divergencias": ddl.divergencias(sink, c, atributos),
        })
    return {"dados": saida}


def _classe_de(entrada: ClasseEntrada) -> repo.Classe:
    return repo.Classe(
        chave=entrada.chave, nome=entrada.nome, tabela=entrada.tabela,
        chave_identidade=entrada.chave_identidade, indices=entrada.indices,
        sla_horas=entrada.sla_horas, resolucao=entrada.resolucao,
        precedencia=entrada.precedencia, descricao=entrada.descricao,
        ativo=entrada.ativo,
        atributos=[repo.Atributo(**a.model_dump()) for a in entrada.atributos],
    )


def _como_vigente(c: repo.Classe) -> tuple[dict, list[dict]]:
    """A classe do payload nas formas que o gerador de DDL consome — os dicts
    que `classe_vigente`/`atributos_de` devolveriam se ela estivesse salva."""
    classe = {
        "tabela": c.tabela,
        "chave_identidade": ",".join(c.chave_identidade),
        "indices": ";".join(",".join(i) for i in c.indices),
    }
    atributos = [
        {"id": i, "nome": a.nome, "tipo": a.tipo, "ordem": a.ordem,
         "guarda_texto": a.guarda_texto}
        for i, a in enumerate(c.atributos)
    ]
    return classe, atributos


@router.post("/classes")
async def post_classe(entrada: ClasseEntrada, request: Request) -> Any:
    """Cadastra a classe e materializa a tabela dela na mesma chamada.

    É o ponto do produto: criar uma classe de informação nova não passa por
    deploy. O DDL sai da configuração e é aplicado aqui.
    """
    sink = obter_sink(request)
    c = _classe_de(entrada)
    try:
        novo = repo.salvar_classe(sink, c, autor="ui")
    except ErroConfiguracao as e:
        raise _erro_config(e) from e
    salva = repo.classe_vigente(sink, entrada.chave)
    aplicadas = ddl.garantir_tabela(sink, salva, repo.atributos_de(sink, novo))
    return {"dados": salva, "id": novo, "ddl_aplicado": aplicadas}


@router.post("/classes/previa")
async def previa_classe(entrada: ClasseEntrada, request: Request) -> Any:
    """O DDL que o payload implica, sem gravar nem aplicar nada.

    É o que permite à interface mostrar o que vai rodar *antes* de salvar —
    o GET de DDL só enxerga classe já persistida.
    """
    sink = obter_sink(request)
    c = _classe_de(entrada)
    try:
        repo.validar_classe(c)
    except ErroConfiguracao as e:
        raise _erro_config(e) from e
    classe, atributos = _como_vigente(c)
    try:
        sentencas = ddl.sentencas_da_classe(classe, atributos)
    except ErroConfiguracao as e:
        raise _erro_config(e) from e
    return {"dados": {
        "sentencas": sentencas,
        "divergencias": ddl.divergencias(sink, classe, atributos),
    }}


@router.get("/classes/{chave}/ddl")
async def get_classe_ddl(chave: str, request: Request) -> Any:
    """O DDL que a configuração implica, e o que diverge do banco hoje."""
    sink = obter_sink(request)
    c = repo.classe_vigente(sink, chave)
    if c is None:
        raise HTTPException(
            status_code=404,
            detail={"codigo": "classe_nao_encontrada", "mensagem": chave},
        )
    atributos = repo.atributos_de(sink, c["id"])
    return {"dados": {
        "sentencas": ddl.sentencas_da_classe(c, atributos),
        "divergencias": ddl.divergencias(sink, c, atributos),
    }}


# --------------------------------------------------------------------------
# Fontes e datasets
# --------------------------------------------------------------------------
@router.get("/fontes")
async def get_fontes(request: Request) -> Any:
    return {"dados": repo.listar_fontes(obter_sink(request))}


@router.post("/fontes")
async def post_fonte(entrada: FonteEntrada, request: Request) -> Any:
    sink = obter_sink(request)
    try:
        novo = repo.salvar_fonte(sink, Fonte(**entrada.model_dump()), autor="ui")
    except ErroConfiguracao as e:
        raise _erro_config(e) from e
    return {"dados": repo.fonte_vigente(sink, entrada.chave), "id": novo}


@router.get("/credenciais")
async def get_credenciais(request: Request) -> Any:
    """Quais fontes exigem token, qual variável cada uma espera, e se ela está
    definida neste ambiente.

    O valor nunca sai daqui — nem deste processo. A configuração guarda a
    referência; o segredo mora no ambiente, e o que a tela mostra é presença,
    não conteúdo.
    """
    sink = obter_sink(request)
    saida = []
    for f in repo.listar_fontes(sink):
        try:
            cred = credenciais.declarada(f["credencial_ref"])
        except credenciais.ErroCredencial as e:
            saida.append({"fonte": f["chave"], "nome": f["nome"], "erro": str(e)})
            continue
        if cred is None:
            continue
        saida.append({
            "fonte": f["chave"],
            "nome": f["nome"],
            "modo": cred.modo,
            "cabecalho": cred.nome or None,
            "variavel": cred.variavel,
            "definida": bool(os.getenv(cred.variavel)),
        })
    return {"dados": saida}


@router.get("/datasets")
async def get_datasets(request: Request) -> Any:
    sink = obter_sink(request)
    saida = []
    for ds in repo.listar_datasets(sink):
        saida.append({
            **ds,
            "colunas": repo.colunas_do(sink, ds["id"]),
            "calculados": repo.calculados_do(sink, ds["id"], so_ativos=False),
            "regras": repo.regras_do(sink, ds["id"], so_ativas=False),
        })
    return {"dados": saida}


def _dataset_de(entrada: DatasetEntrada) -> Dataset:
    return Dataset(
        chave=entrada.chave, fonte_chave=entrada.fonte_chave, nome=entrada.nome,
        padrao_arquivo=entrada.padrao_arquivo, tabela_destino=entrada.tabela_destino,
        chave_natural=entrada.chave_natural, classe_chave=entrada.classe_chave,
        politica_versao=entrada.politica_versao, particao=entrada.particao,
        parametros=entrada.parametros, descricao=entrada.descricao,
        ativo=entrada.ativo,
        colunas=[Coluna(**c.model_dump()) for c in entrada.colunas],
        calculados=[CampoCalculado(**c.model_dump()) for c in entrada.calculados],
        regras=[RegraQualidade(**r.model_dump()) for r in entrada.regras],
    )


@router.post("/datasets")
async def post_dataset(entrada: DatasetEntrada, request: Request) -> Any:
    sink = obter_sink(request)
    d = _dataset_de(entrada)
    try:
        novo = repo.salvar_dataset(sink, d, autor="ui")
    except ErroConfiguracao as e:
        raise _erro_config(e) from e
    return {"dados": repo.dataset_vigente(sink, entrada.chave), "id": novo}


@router.post("/datasets/{chave}/validar")
async def validar_dataset(chave: str, entrada: DatasetEntrada, request: Request) -> Any:
    """Valida sem gravar — é o que dá o retorno imediato no formulário."""
    d = _dataset_de(entrada)
    try:
        repo.validar_dataset(d)
    except ErroConfiguracao as e:
        return {"valido": False, "mensagem": str(e)}
    return {"valido": True, "mensagem": "Configuração válida."}


# --------------------------------------------------------------------------
# Execuções
# --------------------------------------------------------------------------
@router.get("/execucoes")
async def get_execucoes(request: Request, dataset: str | None = None,
                        limite: int = 50) -> Any:
    return {"dados": repo.execucoes(obter_sink(request), limite, dataset)}


@router.post("/execucoes")
async def post_execucao(entrada: ExecucaoEntrada, request: Request) -> Any:
    """Dispara carga ou replay. Replay roda sem rede, do bronze."""
    from ..motor import download

    sink = obter_sink(request)
    try:
        if entrada.baixar:
            res = ingestao.executar(
                sink, entrada.dataset_chave, entrada.janela,
                trigger="manual", baixar=download.baixar,
            )
        else:
            res = ingestao.recomputar(sink, entrada.dataset_chave, entrada.janela)
    except ingestao.ErroIngestao as e:
        raise HTTPException(
            status_code=422,
            detail={"codigo": "ingestao_falhou", "mensagem": str(e)},
        ) from e
    return {"dados": {
        "execucao_id": res.execucao_id, "status": res.status,
        "capturas": res.capturas, "capturas_novas": res.capturas_novas,
        "linhas_silver": res.linhas_silver, "delta_linhas": res.delta_linhas,
        "publicacao": res.publicacao, "violacoes": res.violacoes,
    }}


@router.get("/frescor")
async def get_frescor(request: Request) -> Any:
    return {"dados": observabilidade.frescor(obter_sink(request))}


@router.get("/execucoes/{execucao_id}/fases")
async def get_fases(execucao_id: int, request: Request) -> Any:
    return {"dados": observabilidade.linha_do_tempo(obter_sink(request), execucao_id)}


@router.get("/publicacoes")
async def get_publicacoes(request: Request) -> Any:
    sink = obter_sink(request)
    return {"dados": sink.consultar(
        "SELECT * FROM publicacao ORDER BY versao DESC LIMIT 50"
    ), "atual": publicacao.versao_atual(sink)}


@router.post("/publicacoes/{versao}/reverter")
async def post_reverter(versao: int, request: Request) -> Any:
    sink = obter_sink(request)
    try:
        publicacao.reverter(sink, versao)
    except ValueError as e:
        raise HTTPException(
            status_code=404,
            detail={"codigo": "publicacao_nao_encontrada", "mensagem": str(e)},
        ) from e
    return {"dados": {"atual": versao}}


# --------------------------------------------------------------------------
# Chaves de API
# --------------------------------------------------------------------------
@router.get("/gestao")
async def get_gestao(request: Request) -> Any:
    """O hub inteiro numa resposta: o que tem, quanto tem, quem consome,
    quanto ocupa e o que está para vencer o SLA.

    Não há dado novo aqui — frescor, execuções e chaves já existiam, cada um
    numa rota. Reuni-los é o que evita o operador abrir cinco telas para
    responder "como está o sistema", que é a pergunta que ele faz primeiro.

    A contagem sai da tabela física, não da vista de gold: a diferença entre
    as duas é exatamente o que o gate reteve, e escondê-la faria carga
    reprovada parecer carga inexistente.
    """
    sink = obter_sink(request)
    frescor = {f["classe"]: f for f in observabilidade.frescor(sink)}

    classes = []
    for c in repo.listar_classes(sink, so_ativas=True):
        tabela = c["tabela"]
        if not ddl.colunas_fisicas(sink, tabela):
            continue
        total = sink.um(f"SELECT count(*) AS n FROM {tabela}")["n"]
        publicadas = sink.um(
            f"SELECT count(*) AS n FROM {tabela} WHERE publicado_em_versao IS NOT NULL"
        )["n"]
        f = frescor.get(c["chave"], {})
        classes.append({
            "chave": c["chave"],
            "nome": c["nome"],
            "tabela": tabela,
            "linhas": int(total),
            "linhas_publicadas": int(publicadas),
            "retidas_no_gate": int(total) - int(publicadas),
            "fontes": [d["chave"] for d in repo.datasets_da_classe(sink, c["chave"])],
            "situacao": f.get("situacao"),
            "idade_horas": f.get("idade_horas"),
            "sla_horas": c.get("sla_horas"),
            "ultima_publicacao": f.get("ultima_publicacao"),
        })

    bronze = sink.um(
        "SELECT count(*) AS capturas, COALESCE(sum(tamanho_bytes), 0) AS bytes "
        "FROM bronze_captura"
    )
    chaves = sink.consultar(
        "SELECT consumidor, prefixo, quota_minuto, quota_dia, escopos, "
        "criada_em, revogada_em FROM cfg_chave_api ORDER BY id DESC"
    )

    return {"dados": {
        "classes": classes,
        "bronze": {
            "capturas": int(bronze["capturas"] or 0),
            "bytes": int(bronze["bytes"] or 0),
        },
        "consumidores": [
            {**dict(k), "ativa": k["revogada_em"] is None} for k in chaves
        ],
        "correlacoes": [
            {"chave": c["chave"], "origem": c["classe_origem"],
             "destino": c["classe_destino"]}
            for c in repo.listar_correlacoes(sink)
        ],
        "fora_do_sla": [
            c["chave"] for c in classes if c["situacao"] not in ("em_dia", None)
        ],
    }}


@router.get("/chaves")
async def get_chaves(request: Request) -> Any:
    sink = obter_sink(request)
    return {"dados": sink.consultar(
        "SELECT id, consumidor, prefixo, quota_minuto, quota_dia, escopos, "
        "criada_em, revogada_em FROM cfg_chave_api ORDER BY id DESC"
    )}


@router.post("/chaves")
async def post_chave(entrada: ChaveEntrada, request: Request) -> Any:
    sink = obter_sink(request)
    conhecidas = {c["chave"] for c in repo.listar_classes(sink)}
    desconhecidas = [c for c in entrada.classes if c not in conhecidas]
    if desconhecidas:
        raise HTTPException(
            status_code=422,
            detail={"codigo": "classe_desconhecida",
                    "mensagem": f"Escopo cita classe inexistente: "
                                f"{', '.join(desconhecidas)}"},
        )
    escopos = (",".join(f"classe:{c}" for c in entrada.classes)
               if entrada.classes else "leitura")
    emitida = auth.emitir(
        sink, entrada.consumidor, entrada.quota_minuto, entrada.quota_dia,
        escopos=escopos,
    )
    return {"dados": {
        "prefixo": emitida.prefixo,
        "chave": emitida.chave_completa,
        "escopos": escopos,
        "aviso": "Guarde agora: a chave completa não é exibida de novo.",
    }}


@router.delete("/chaves/{prefixo}")
async def delete_chave(prefixo: str, request: Request) -> Any:
    if not auth.revogar(obter_sink(request), prefixo):
        raise HTTPException(
            status_code=404,
            detail={"codigo": "chave_nao_encontrada",
                    "mensagem": f"Nenhuma chave ativa com prefixo {prefixo}."},
        )
    return {"dados": {"prefixo": prefixo, "revogada": True}}


# --------------------------------------------------------------------------
# Métricas
# --------------------------------------------------------------------------
@router.get("/metricas")
async def get_metricas(request: Request) -> Any:
    return {"dados": metricas.listar(obter_sink(request))}


@router.post("/metricas")
async def post_metrica(entrada: MetricaEntrada, request: Request) -> Any:
    sink = obter_sink(request)
    try:
        _, contas = metricas.expandir(entrada.formula)
    except metricas.ErroMetrica as e:
        raise HTTPException(
            status_code=422,
            detail={"codigo": "formula_invalida", "mensagem": str(e)},
        ) from e
    versao = repo._aposentar(sink, "cfg_metrica", entrada.chave)
    sink.executar(
        """INSERT INTO cfg_metrica
           (id, nome, formula, unidade, descricao, ativo, chave, versao,
            vigente, vigente_chave, criado_por)
           VALUES (?,?,?,?,?,?,?,?,TRUE,?,'ui')""",
        (sink.proximo_id("cfg_metrica"), entrada.nome, entrada.formula,
         entrada.unidade, entrada.descricao, entrada.ativo, entrada.chave,
         versao, entrada.chave),
    )
    return {"dados": {"chave": entrada.chave, "contas_referenciadas": contas}}


# --------------------------------------------------------------------------
# Catálogo (leitura)
# --------------------------------------------------------------------------
@router.get("/catalogo")
async def get_catalogo(request: Request) -> Any:
    sink = obter_sink(request)
    tabelas = sink.consultar(
        "SELECT table_name AS nome FROM information_schema.tables "
        "WHERE table_schema IN ('main','public') ORDER BY table_name"
    )
    return {"dados": [t["nome"] for t in tabelas]}


@router.get("/catalogo/{tabela}")
async def get_catalogo_tabela(tabela: str, request: Request, limite: int = 10) -> Any:
    sink = obter_sink(request)
    existe = sink.um(
        "SELECT 1 AS ok FROM information_schema.tables WHERE table_name = ?",
        (tabela,),
    )
    if not existe:
        raise HTTPException(
            status_code=404,
            detail={"codigo": "tabela_nao_encontrada", "mensagem": tabela},
        )
    colunas = sink.consultar(
        "SELECT column_name AS nome, data_type AS tipo FROM information_schema.columns "
        "WHERE table_name = ? ORDER BY ordinal_position",
        (tabela,),
    )
    amostra = sink.consultar(f"SELECT * FROM {tabela} LIMIT ?", (min(limite, 100),))
    total = sink.um(f"SELECT count(*) AS n FROM {tabela}")["n"]
    return {"dados": {"tabela": tabela, "colunas": colunas,
                      "linhas": total, "amostra": amostra}}
