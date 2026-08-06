"""Plano de controle sobre HTTP — o que as telas de configuração consomem.

Separado de `/v1` de propósito: público lê dado, administração muda
configuração. Escrita exige `PORTAL_ADMIN_TOKEN`.
"""
from __future__ import annotations

import os
from typing import Any

from fastapi import (
    APIRouter, Depends, Header, HTTPException, Path, Query, Request, Response,
)
from pydantic import BaseModel, Field

from .. import repositorio as repo
from ..motor import (
    correlacao, credenciais, custo, ddl, ingestao, observabilidade, publicacao,
)
from ..repositorio import (
    CampoCalculado, Coluna, Dataset, ErroConfiguracao, Fonte, RegraQualidade,
)
from ..sinks import Sink
from . import acesso, auth, metricas, proveniencia

async def exigir_admin(request: Request) -> None:
    """Sessão do dono, por cookie ou por cabeçalho.

    Antes só o cabeçalho valia, e a interface o lia do `localStorage` — que
    nada preenchia: não havia tela de login no /admin, então entrar exigia
    abrir o console do navegador. O cookie que `/entrar` já emitia servia à
    apresentação e parava na porta da administração.

    Aceitar os dois fecha isso sem criar credencial nova. O cabeçalho segue
    valendo para `curl` e script, que não têm cookie.

    **CSRF.** Aceitar cookie numa rota de escrita abre a porta que o cabeçalho
    fechava por construção — um formulário de outro site não consegue definir
    cabeçalho. Três coisas seguram: o cookie é `SameSite=Lax`, que não
    acompanha POST vindo de outra origem; o CORS nega origem cruzada por
    omissão; e a interface só fala JSON, que dispara verificação prévia.
    """
    if not os.getenv("PORTAL_ADMIN_TOKEN"):
        return  # dev: sem token configurado, administração fica aberta local
    if not auth.sessao_admin(request):
        raise HTTPException(
            status_code=401,
            detail={"codigo": "admin_nao_autorizado",
                    "mensagem": "Entre em / para abrir uma sessão, ou informe "
                                "X-Admin-Token."},
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
    """Toda classe de informação cadastrada, com atributos e o que diverge
    entre a tabela física e a configuração vigente.

    `divergencias` é o que orienta a tela a oferecer "aplicar DDL" — uma
    classe editada na interface e ainda não aplicada ao banco aparece aqui
    antes de qualquer erro em produção.
    """
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
async def get_classe_ddl(
    request: Request,
    chave: str = Path(..., description="Chave da classe já cadastrada"),
) -> Any:
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
    """Toda fonte de dado cadastrada: de onde vem, como baixar, que
    credencial exige."""
    return {"dados": repo.listar_fontes(obter_sink(request))}


@router.post("/fontes")
async def post_fonte(entrada: FonteEntrada, request: Request) -> Any:
    """Cadastra ou reversiona uma fonte — nunca sobrescreve.

    Salvar uma fonte já existente cria uma versão nova; a anterior continua
    no banco, vigente=false, e qualquer execução passada aponta para o
    snapshot de configuração que usou, não para a versão atual.
    """
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
    """Todo mapeamento fonte→classe: colunas, campos calculados e regras de
    qualidade, incluindo os inativos."""
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
    """Cadastra ou reversiona um mapeamento — como a fonte, nunca sobrescreve.

    Salvar já valida e recusa configuração inválida (422). Para o erro
    aparecer no formulário antes do clique em salvar, chame
    `/datasets/{chave}/validar` primeiro — mesma validação, sem gravar nada.
    """
    sink = obter_sink(request)
    d = _dataset_de(entrada)
    try:
        novo = repo.salvar_dataset(sink, d, autor="ui")
    except ErroConfiguracao as e:
        raise _erro_config(e) from e
    return {"dados": repo.dataset_vigente(sink, entrada.chave), "id": novo}


@router.post("/datasets/{chave}/validar")
async def validar_dataset(
    entrada: DatasetEntrada, request: Request,
    chave: str = Path(..., description="Chave do mapeamento sendo editado. Não entra na "
                                       "validação, que roda inteira sobre o corpo enviado"),
) -> Any:
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
async def get_execucoes(
    request: Request,
    dataset: str | None = Query(
        None, description="Restringe ao mapeamento com esta chave. Omitido, traz todos"),
    limite: int = Query(50, description="Quantas execuções recentes trazer"),
) -> Any:
    """Histórico de carga — o que rodou, para a tela de Execuções."""
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
    """Idade do dado de cada classe contra o SLA declarado — para a tela
    saber o que mostrar como atrasado."""
    return {"dados": observabilidade.frescor(obter_sink(request))}


@router.get("/execucoes/{execucao_id}/fases")
async def get_fases(
    request: Request,
    execucao_id: int = Path(..., description="Id da execução — vem em /execucoes"),
) -> Any:
    """Onde a execução gastou o tempo, fase a fase — não só quanto durou ao
    todo."""
    return {"dados": observabilidade.linha_do_tempo(obter_sink(request), execucao_id)}


@router.get("/publicacoes")
async def get_publicacoes(request: Request) -> Any:
    """As últimas 50 versões de gold, com qual é a vigente agora — a lista
    que alimenta o botão de reverter."""
    sink = obter_sink(request)
    return {"dados": sink.consultar(
        "SELECT * FROM publicacao ORDER BY versao DESC LIMIT 50"
    ), "atual": publicacao.versao_atual(sink)}


@router.post("/publicacoes/{versao}/reverter")
async def post_reverter(
    request: Request,
    versao: int = Path(..., description="Número da versão de publicação para onde voltar "
                                        "— vem em /publicacoes"),
) -> Any:
    """Move o ponteiro de gold para uma versão anterior. Não apaga nada: as
    versões mais novas continuam no banco, só deixam de ser a vigente."""
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
@router.get("/carga")
async def get_carga(
    request: Request,
    dataset: str | None = Query(
        None, description="Restringe ao mapeamento com esta chave. Omitido, traz todos"),
    limite: int = Query(50, description="Quantas execuções recentes trazer, até 500"),
) -> Any:
    """Relatório de carga para a interface. Mesma resposta de `/v1/meta/carga`
    — a diferença entre as rotas é quem pode chamar, não o que respondem."""
    return custo.painel(obter_sink(request), dataset, min(max(limite, 1), 500))


# --------------------------------------------------------------------------
# Camada de acesso (ADR-19)
# --------------------------------------------------------------------------
# Registrar exige sessão. É o que impede que qualquer visitante registre o
# próprio autenticador e passe a ser dono — o primeiro passkey entra por quem
# já tem o token, que é exatamente o papel que o token conserva.
class PasskeyEntrada(BaseModel):
    rotulo: str
    credencial: dict


@router.get("/acesso")
async def get_acesso(request: Request) -> Any:
    """O estado da camada de acesso: autenticadores, sessões e qual caminho
    está aberto."""
    sink = obter_sink(request)
    return {"dados": {
        "passkeys": acesso.passkeys(sink),
        "sessoes": acesso.sessoes(sink),
        "token_configurado": bool(os.getenv("PORTAL_ADMIN_TOKEN")),
        "token_no_formulario": acesso.token_no_formulario(sink),
        "acesso_legado": os.getenv("PORTAL_ACESSO_LEGADO") == "1",
        "identidade": acesso.identidade_do_site(request.headers.get("origin"))[0],
    }}


@router.post("/acesso/passkeys/opcoes")
async def post_passkey_opcoes(request: Request) -> Any:
    """Desafio WebAuthn para registrar um novo autenticador — o primeiro
    passo do fluxo, antes do navegador pedir a assinatura biométrica."""
    corpo = await request.json()
    return Response(
        content=acesso.opcoes_de_registro(
            obter_sink(request), (corpo or {}).get("rotulo", ""),
            request.headers.get("origin"),
        ),
        media_type="application/json",
    )


@router.post("/acesso/passkeys")
async def post_passkey(request: Request, entrada: PasskeyEntrada) -> Any:
    """Registra o autenticador cuja assinatura o navegador acabou de
    devolver — o segundo passo do fluxo, depois de /acesso/passkeys/opcoes."""
    try:
        return {"dados": acesso.registrar(
            obter_sink(request), entrada.credencial, entrada.rotulo,
            request.headers.get("origin"),
        )}
    except acesso.ErroAcesso as e:
        raise HTTPException(
            status_code=400,
            detail={"codigo": "passkey_invalida", "mensagem": str(e)},
        ) from e


@router.delete("/acesso/passkeys/{credential_id:path}")
async def delete_passkey(
    request: Request,
    credential_id: str = Path(..., description="Id do autenticador, como listado em "
                                                "/acesso"),
) -> Any:
    """Revogar um autenticador sem derrubar os outros — a segunda falta que a
    auditoria registrou no §5.2."""
    sink = obter_sink(request)
    if not acesso.esquecer_passkey(sink, credential_id):
        raise HTTPException(
            status_code=404,
            detail={"codigo": "passkey_nao_encontrada", "mensagem": credential_id},
        )
    return {"dados": {"revogada": credential_id,
                      "restantes": len(acesso.passkeys(sink))}}


@router.delete("/acesso/sessoes/{sessao_id:path}")
async def delete_sessao(
    request: Request,
    sessao_id: str = Path(..., description="Identificador opaco da sessão, como "
                                           "listado em /acesso"),
) -> Any:
    """Encerra uma sessão aberta — derruba quem estiver logado com ela, sem
    mexer nas outras."""
    acesso.fechar_sessao(obter_sink(request), sessao_id)
    return {"dados": {"encerrada": sessao_id}}


# --------------------------------------------------------------------------
# Linhagem e correlações no plano de controle
# --------------------------------------------------------------------------
# As três respondem o mesmo que suas irmãs em `/v1`. A diferença entre as
# rotas é quem pode chamar, não o que respondem — é o arranjo que `/carga` já
# usava, e existe por um motivo concreto: `/v1` exige chave de API ou sessão
# do dono, enquanto `/admin/api` fica aberto localmente sem
# `PORTAL_ADMIN_TOKEN`. A interface de configuração chamando `/v1` recebia
# "informe uma chave válida no cabeçalho X-API-Key" em desenvolvimento — a
# mensagem de máquina numa tela de humano que a auditoria condenou na
# apresentação, reaparecendo aqui.
#
# Aqui não há filtro por escopo, e é deliberado: escopo restringe consumidor,
# e quem entra no plano de controle é o dono.
@router.get("/linhagem")
async def get_linhagem(
    request: Request,
    classe: str = Query(..., description="Chave da classe de informação"),
    atributo: str = Query(..., description="Nome do atributo dentro da classe"),
) -> Any:
    """De onde veio este número: fonte, captura, regra de qualidade que
    aprovou, versão de publicação. Espelho de /v1/meta/linhagem, sem exigir
    chave de API — quem está no plano de controle é o dono."""
    try:
        return {"dados": observabilidade.linhagem(
            obter_sink(request), classe, atributo)}
    except ErroConfiguracao as e:
        raise HTTPException(
            status_code=404,
            detail={"codigo": "linhagem_nao_encontrada", "mensagem": str(e)},
        ) from e


@router.get("/contrato")
async def get_contrato(
    request: Request,
    classe: str = Query(..., description="Chave da classe de informação"),
) -> Any:
    """O perfil ODCS da classe. Espelho de `/v1/meta/contrato`, pelo mesmo
    motivo dos outros: a interface de configuração roda sem chave de API."""
    from ..motor import contrato as contrato_mod

    try:
        return {"dados": contrato_mod.contrato(obter_sink(request), classe)}
    except ErroConfiguracao as e:
        raise HTTPException(
            status_code=404,
            detail={"codigo": "classe_nao_encontrada", "mensagem": str(e)},
        ) from e


@router.get("/correlacoes")
async def get_correlacoes(request: Request) -> Any:
    """Toda junção entre classes declarada em configuração — sem filtrar por
    escopo, porque quem chama aqui é o dono, não um consumidor com chave."""
    return {"dados": [
        {"chave": c["chave"], "origem": c["classe_origem"],
         "destino": c["classe_destino"],
         "por": {"origem": c["atributo_origem"],
                 "destino": c["atributo_destino"]},
         "relacionamento": c["relacionamento"], "descricao": c["descricao"]}
        for c in repo.listar_correlacoes(obter_sink(request))
    ]}


@router.get("/correlacoes/{chave_correlacao}")
async def get_travessia(
    request: Request,
    chave_correlacao: str = Path(
        ..., description="Chave declarada em cfg_correlacao — ver /correlacoes"),
    limite: int = Query(5, description="Quantas linhas trazer da travessia"),
) -> Any:
    """Executa a travessia declarada, para o dono conferir que ela funciona.

    Listar o nome de uma correlação não prova que ela atravessa: era o que a
    tela de gestão fazia, e conferir exigia abrir o banco."""
    sink = obter_sink(request)
    try:
        saida = correlacao.consultar(
            sink, chave_correlacao, limite=min(max(limite, 1), 50),
        )
        # Mesma decoração de /v1: sem ela a tabela mostraria `captura_id` e
        # `publicado_em_versao` como se fossem atributos da classe.
        saida["dados"] = proveniencia.decorar(sink, saida["dados"])
        return saida
    except correlacao.ErroCorrelacao as e:
        raise HTTPException(
            status_code=404,
            detail={"codigo": "correlacao_nao_declarada", "mensagem": str(e)},
        ) from e


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
            # A falha vai junto da publicação, não no lugar dela: uma classe
            # pode estar em dia e ter quebrado ontem, e quem só recebe a
            # publicação nunca fica sabendo da segunda.
            "ultima_falha": f.get("ultima_falha"),
        })

    # Duas medidas, não uma. `tamanho_bytes` é o tamanho do arquivo que a fonte
    # publicou — o que o consumidor baixa. `ocupado` é o que a tabela custa em
    # disco, com índices e TOAST. Com a compressão do [ADR-21] ligada as duas
    # deixam de coincidir, e chamar a primeira de "espaço" faria a gestão
    # superestimar o próprio custo em uma ordem de grandeza.
    bronze = sink.um(
        "SELECT count(*) AS capturas, COALESCE(sum(tamanho_bytes), 0) AS bytes "
        "FROM bronze_captura"
    )
    ocupado = custo.tamanho_tabela(sink, "bronze_captura")
    chaves = sink.consultar(
        "SELECT consumidor, prefixo, quota_minuto, quota_dia, escopos, "
        "criada_em, revogada_em FROM cfg_chave_api ORDER BY id DESC"
    )

    return {"dados": {
        "classes": classes,
        "bronze": {
            "capturas": int(bronze["capturas"] or 0),
            # `ocupado` é nulo no DuckDB, que não expõe a medida. Nulo é fato:
            # a tela mostra traço em vez de fingir que mediu.
            "ocupado_bytes": ocupado,
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
    """Toda chave de API emitida, ativa ou revogada — nunca o segredo, só o
    prefixo que a identifica publicamente."""
    sink = obter_sink(request)
    return {"dados": sink.consultar(
        "SELECT id, consumidor, prefixo, quota_minuto, quota_dia, escopos, "
        "criada_em, revogada_em FROM cfg_chave_api ORDER BY id DESC"
    )}


@router.post("/chaves")
async def post_chave(entrada: ChaveEntrada, request: Request) -> Any:
    """Emite uma chave de API nova, com o escopo de classes que ela pode ler.

    A chave completa só aparece nesta resposta — o banco guarda o hash, não
    o valor. Perdida, não tem como recuperar: revogue e emita outra.
    """
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
async def delete_chave(
    request: Request,
    prefixo: str = Path(..., description="Prefixo público da chave, como listado em "
                                         "/chaves — não é a chave completa"),
) -> Any:
    """Revoga a chave. Imediato: a próxima chamada com ela recebe 401, e o
    consumidor precisa de uma chave nova para voltar a ler."""
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
    """Todo indicador fundamentalista cadastrado, com a fórmula sobre conta
    contábil que o alimenta."""
    return {"dados": metricas.listar(obter_sink(request))}


@router.post("/metricas")
async def post_metrica(entrada: MetricaEntrada, request: Request) -> Any:
    """Cadastra ou reversiona uma métrica.

    A fórmula é validada antes de gravar — `c('1.01')` precisa referenciar
    pelo menos uma conta e não pode chamar nenhuma função além de aritmética,
    ou a chamada recusa com 422 antes de tocar o banco.
    """
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
    """Nome de toda tabela do banco — bronze, silver, gold e plano de
    controle juntos. Ponto de entrada da tela de Catálogo."""
    sink = obter_sink(request)
    tabelas = sink.consultar(
        "SELECT table_name AS nome FROM information_schema.tables "
        "WHERE table_schema IN ('main','public') ORDER BY table_name"
    )
    return {"dados": [t["nome"] for t in tabelas]}


@router.get("/catalogo/{tabela}")
async def get_catalogo_tabela(
    request: Request,
    tabela: str = Path(..., description="Nome exato da tabela, como listado em "
                                        "/catalogo"),
    limite: int = Query(10, description="Linhas de amostra a trazer, até 100"),
) -> Any:
    """Schema e amostra de uma tabela — colunas, tipos e as primeiras linhas.

    Contorna o escopo por classe das chaves de API de propósito: só chega
    aqui quem já está autenticado como dono do plano de controle.
    """
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
