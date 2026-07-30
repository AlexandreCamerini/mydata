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
from ..motor import ingestao, publicacao
from ..repositorio import (
    CampoCalculado, Coluna, Dataset, ErroConfiguracao, Fonte, RegraQualidade,
)
from ..sinks import Sink
from . import auth, metricas

router = APIRouter(prefix="/admin/api", tags=["administração"])


def obter_sink(request: Request) -> Sink:
    return request.app.state.sink


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
    colunas: list[ColunaEntrada] = Field(default_factory=list)
    calculados: list[CalculadoEntrada] = Field(default_factory=list)
    regras: list[RegraEntrada] = Field(default_factory=list)
    descricao: str | None = None
    ativo: bool = True


class ChaveEntrada(BaseModel):
    consumidor: str
    quota_minuto: int = 120
    quota_dia: int = 50000


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
# Fontes e datasets
# --------------------------------------------------------------------------
@router.get("/fontes")
async def get_fontes(request: Request) -> Any:
    return {"dados": repo.listar_fontes(obter_sink(request))}


@router.post("/fontes", dependencies=[Depends(exigir_admin)])
async def post_fonte(entrada: FonteEntrada, request: Request) -> Any:
    sink = obter_sink(request)
    try:
        novo = repo.salvar_fonte(sink, Fonte(**entrada.model_dump()), autor="ui")
    except ErroConfiguracao as e:
        raise _erro_config(e) from e
    return {"dados": repo.fonte_vigente(sink, entrada.chave), "id": novo}


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


@router.post("/datasets", dependencies=[Depends(exigir_admin)])
async def post_dataset(entrada: DatasetEntrada, request: Request) -> Any:
    sink = obter_sink(request)
    d = Dataset(
        chave=entrada.chave, fonte_chave=entrada.fonte_chave, nome=entrada.nome,
        padrao_arquivo=entrada.padrao_arquivo, tabela_destino=entrada.tabela_destino,
        chave_natural=entrada.chave_natural, descricao=entrada.descricao,
        ativo=entrada.ativo,
        colunas=[Coluna(**c.model_dump()) for c in entrada.colunas],
        calculados=[CampoCalculado(**c.model_dump()) for c in entrada.calculados],
        regras=[RegraQualidade(**r.model_dump()) for r in entrada.regras],
    )
    try:
        novo = repo.salvar_dataset(sink, d, autor="ui")
    except ErroConfiguracao as e:
        raise _erro_config(e) from e
    return {"dados": repo.dataset_vigente(sink, entrada.chave), "id": novo}


@router.post("/datasets/{chave}/validar")
async def validar_dataset(chave: str, entrada: DatasetEntrada, request: Request) -> Any:
    """Valida sem gravar — é o que dá o retorno imediato no formulário."""
    d = Dataset(
        chave=entrada.chave, fonte_chave=entrada.fonte_chave, nome=entrada.nome,
        padrao_arquivo=entrada.padrao_arquivo, tabela_destino=entrada.tabela_destino,
        chave_natural=entrada.chave_natural,
        colunas=[Coluna(**c.model_dump()) for c in entrada.colunas],
        calculados=[CampoCalculado(**c.model_dump()) for c in entrada.calculados],
        regras=[RegraQualidade(**r.model_dump()) for r in entrada.regras],
    )
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


@router.post("/execucoes", dependencies=[Depends(exigir_admin)])
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


@router.get("/publicacoes")
async def get_publicacoes(request: Request) -> Any:
    sink = obter_sink(request)
    return {"dados": sink.consultar(
        "SELECT * FROM publicacao ORDER BY versao DESC LIMIT 50"
    ), "atual": publicacao.versao_atual(sink)}


@router.post("/publicacoes/{versao}/reverter", dependencies=[Depends(exigir_admin)])
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
@router.get("/chaves")
async def get_chaves(request: Request) -> Any:
    sink = obter_sink(request)
    return {"dados": sink.consultar(
        "SELECT id, consumidor, prefixo, quota_minuto, quota_dia, escopos, "
        "criada_em, revogada_em FROM cfg_chave_api ORDER BY id DESC"
    )}


@router.post("/chaves", dependencies=[Depends(exigir_admin)])
async def post_chave(entrada: ChaveEntrada, request: Request) -> Any:
    emitida = auth.emitir(
        obter_sink(request), entrada.consumidor,
        entrada.quota_minuto, entrada.quota_dia,
    )
    return {"dados": {
        "prefixo": emitida.prefixo,
        "chave": emitida.chave_completa,
        "aviso": "Guarde agora: a chave completa não é exibida de novo.",
    }}


@router.delete("/chaves/{prefixo}", dependencies=[Depends(exigir_admin)])
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


@router.post("/metricas", dependencies=[Depends(exigir_admin)])
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
