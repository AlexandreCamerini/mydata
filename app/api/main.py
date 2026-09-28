"""API pública e plano de controle, servidos pelo mesmo processo.

Um serviço só: `/v1` para o consumidor, `/admin/api` para a interface de
configuração, `/admin` para o build estático do front. É o que mantém o custo
no Railway em um serviço em vez de dois.
"""
from __future__ import annotations

import base64
import json
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
# Renomeado para não colidir com fastapi.Path, usado abaixo para documentar
# parâmetro de rota (cd_cvm, ticker etc.) — os dois se chamam "Path" e fazem
# coisas completamente diferentes.
from pathlib import Path as CaminhoDoArquivo
from typing import Any

from fastapi import (
    Depends, FastAPI, Header, HTTPException, Path, Query, Request, Response,
)
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, field_validator

from .. import bootstrap, repositorio as repo
from ..console import api as console_api
from ..console import coletor as console_coletor
from ..motor import (
    contrato, correlacao, custo, ingestao, observabilidade, publicacao,
)
from ..sinks import Sink, criar_sink
from . import acesso, admin, auth, proveniencia, semente_id
from . import metricas as metricas_cat

RAIZ_WEB = CaminhoDoArquivo(__file__).resolve().parents[2] / "web" / "dist"


# --------------------------------------------------------------------------
# Ciclo de vida e dependências
# --------------------------------------------------------------------------
@asynccontextmanager
async def ciclo(app: FastAPI):
    sink = criar_sink()
    if os.getenv("PORTAL_MIGRAR_NO_BOOT", "1") == "1":
        bootstrap.preparar(sink)
    app.state.sink = sink
    # Agendador interno da console (Bloco A, ADR-25) — só com
    # CONSOLE_COLETOR=1. Sem a variável, `iniciar` não cria nenhuma tarefa e
    # o mydata sobe exatamente como sobe hoje (critério de aceite do dono).
    console_coletor.iniciar(app)
    yield
    await console_coletor.parar(app)
    sink.fechar()


# O hub ocupa a raiz do domínio; os apps consumidores vivem em subdomínios e
# chamam a API pelo navegador, então a origem deles precisa ser declarada.
# Lista vazia significa "nenhuma origem cruzada" — negar por omissão, e não
# liberar `*` por conveniência de desenvolvimento.
URL_PUBLICA = os.getenv("PORTAL_URL_PUBLICA", "").rstrip("/")
ORIGENS = [o.strip() for o in os.getenv("PORTAL_ORIGENS", "").split(",") if o.strip()]

app = FastAPI(
    title="MyData — hub de dados multi-fonte",
    version="0.1.0",
    description=(
        "Classes de informação alimentadas por múltiplas fontes, com "
        "proveniência em toda resposta — a fonte é sempre a origem oficial, "
        "nunca um revendedor. Primeira fonte: CVM Dados Abertos."
    ),
    lifespan=ciclo,
    # Sem isto o OpenAPI publicado anuncia `http://localhost`, e o cliente
    # gerado a partir dele aponta para a máquina de quem o gerou.
    servers=[{"url": URL_PUBLICA, "description": "produção"}] if URL_PUBLICA else None,
)

if ORIGENS:
    from fastapi.middleware.cors import CORSMiddleware

    app.add_middleware(
        CORSMiddleware,
        allow_origins=ORIGENS,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["X-API-Key", "X-Admin-Token", "Content-Type", "If-None-Match"],
        expose_headers=["ETag", "X-Quota-Limite", "X-Quota-Restante"],
        max_age=600,
    )


def obter_sink(request: Request) -> Sink:
    return request.app.state.sink


def erro(codigo: str, mensagem: str, status: int, detalhe: Any = None) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"erro": {"codigo": codigo, "mensagem": mensagem, "detalhe": detalhe}},
    )


class ChavePublicaEntrada(BaseModel):
    """Entrada mínima da emissão pública.

    `classes` e `escopos` não fazem parte do modelo: o servidor nunca aceita
    configuração de acesso vinda do consumidor.
    """

    consumidor: str

    @field_validator("consumidor")
    @classmethod
    def consumidor_nao_pode_ser_vazio(cls, valor: str) -> str:
        valor = valor.strip()
        if not valor:
            raise ValueError("consumidor não pode ser vazio")
        return valor


@app.exception_handler(RequestValidationError)
async def tratar_validacao(request: Request, exc: RequestValidationError):
    if request.url.path == "/v1/chaves":
        return erro(
            "entrada_invalida",
            "Informe um consumidor não vazio em JSON.",
            422,
        )
    return await request_validation_exception_handler(request, exc)


# A checagem de sessão mora em `auth`: as duas superfícies precisam dela, e
# `admin` não pode importar `main`. O navegador nunca vê chave de API — a
# sessão é a credencial, e o servidor responde por ela perante /v1.
_admin_ok = auth.admin_ok
sessao_admin = auth.sessao_admin
COOKIE_SESSAO = auth.COOKIE_SESSAO


async def exigir_chave(
    request: Request,
    response: Response,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict:
    """Autentica e consome quota. `PORTAL_API_ABERTA=1` libera em dev."""
    sink = obter_sink(request)
    if os.getenv("PORTAL_API_ABERTA") == "1" and not x_api_key:
        return {"prefixo": "aberta", "consumidor": "dev", "escopos": "leitura"}
    # A apresentação lê /v1 sob a sessão do dono: mesma leitura que uma chave
    # de escopo total, sem quota — é o dono — e sem chave alguma no navegador.
    if not x_api_key and sessao_admin(request):
        return {"prefixo": "admin", "consumidor": "apresentacao",
                "escopos": "leitura"}
    chave = auth.verificar(sink, x_api_key)
    if chave is None:
        raise HTTPException(
            status_code=401,
            detail={"codigo": "chave_invalida",
                    "mensagem": "Informe uma chave válida no cabeçalho X-API-Key."},
        )
    quota = auth.consumir_quota(sink, chave)
    response.headers["X-Quota-Limite"] = str(quota["limite"])
    response.headers["X-Quota-Restante"] = str(quota["restante"])
    if not quota["ok"]:
        raise HTTPException(
            status_code=429,
            detail={"codigo": "quota_excedida",
                    "mensagem": f"Quota por {quota['janela']} esgotada."},
            headers={"Retry-After": "60" if quota["janela"] == "minuto" else "3600"},
        )
    return chave


async def exigir_chave_setups(chave: dict = Depends(exigir_chave)) -> dict:
    """`exigir_chave` mais o escopo `setups` — toda rota de `/v1/setups`,
    leitura incluída, porque setup é estado privado do consumidor, não classe
    pública (ver `auth.pode_setups`)."""
    if not auth.pode_setups(chave):
        raise HTTPException(
            status_code=403,
            detail={"codigo": "escopo_insuficiente",
                    "mensagem": f"A chave de '{chave.get('consumidor')}' não tem "
                                f"escopo 'setups'."},
        )
    return chave


@app.exception_handler(HTTPException)
async def tratar_http(request: Request, exc: HTTPException):
    detalhe = exc.detail
    if isinstance(detalhe, dict) and "codigo" in detalhe:
        corpo = {"erro": {**detalhe, "detalhe": detalhe.get("detalhe")}}
    else:
        corpo = {"erro": {"codigo": "erro", "mensagem": str(detalhe), "detalhe": None}}
    return JSONResponse(status_code=exc.status_code, content=corpo,
                        headers=getattr(exc, "headers", None))


# --------------------------------------------------------------------------
# Proveniência e cache
# --------------------------------------------------------------------------
def exigir_vista(sink: Sink, nome: str, chave: dict | None = None) -> None:
    """Porteiro de gold: a vista existe, e esta chave pode ler esta classe.

    A existência: vista de gold vem de `cfg_vista`. Um banco migrado e sem
    configuração — deploy novo antes do primeiro seed — não tem gold nenhuma;
    sem esta checagem o consumidor receberia um 500 sobre relação ausente.

    O escopo: cada app consumidor tem chave própria, e o escopo dela diz
    quais *classes* ele lê. Um app novo é uma chave nova, não código novo.
    """
    if not sink.um(
        "SELECT 1 AS ok FROM information_schema.tables WHERE table_name = ?",
        (nome,),
    ):
        raise HTTPException(
            status_code=503,
            detail={
                "codigo": "gold_indisponivel",
                "mensagem": f"A vista '{nome}' ainda não foi publicada. "
                            f"Rode `python -m app.cli migrar --seed` e uma ingestão.",
            },
        )
    if chave is None:
        return
    classe = publicacao.classe_da_vista(sink, nome)
    if not auth.pode_ler(chave, classe):
        raise HTTPException(
            status_code=403,
            detail={
                "codigo": "escopo_insuficiente",
                "mensagem": f"A chave de '{chave.get('consumidor')}' não tem "
                            f"escopo para a classe '{classe}'.",
            },
        )


def _cursor_codificar(valores: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(valores).encode()).decode().rstrip("=")


def _cursor_decodificar(cursor: str | None) -> dict | None:
    if not cursor:
        return None
    try:
        pad = "=" * (-len(cursor) % 4)
        return json.loads(base64.urlsafe_b64decode(cursor + pad))
    except Exception:  # noqa: BLE001
        raise HTTPException(
            status_code=400,
            detail={"codigo": "parametro_invalido", "mensagem": "cursor inválido"},
        ) from None


def _etag(sink: Sink, chave: str) -> str:
    """Gold só muda quando há publicação — a versão é a identidade do cache."""
    return f'W/"{publicacao.versao_atual(sink)}-{abs(hash(chave)) % (10 ** 12)}"'


def _talvez_304(request: Request, etag: str) -> Response | None:
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})
    return None


# --------------------------------------------------------------------------
# /v1 — API pública
# --------------------------------------------------------------------------
@app.get("/health", tags=["operação"])
async def health() -> dict:
    """Healthcheck do Railway: responde sem tocar no banco."""
    return {"status": "ok", "versao": "0.1.0"}


ESCOPOS_PUBLICOS = (
    "classe:empresa,classe:demonstracao_financeira,"
    "classe:indicador_macro"
)


@app.post("/v1/chaves", tags=["acesso"])
async def post_chave_publica(entrada: ChavePublicaEntrada, request: Request) -> Any:
    """Emite uma chave inicial para leitura pública das classes republicáveis."""
    ip = request.client.host if request.client is not None else None
    if ip is None:
        raise HTTPException(
            status_code=400,
            detail={
                "codigo": "ip_indisponivel",
                "mensagem": "Não foi possível identificar o IP para limitar emissões.",
            },
        )

    quota = auth.consumir_quota_ip_emissao(obter_sink(request), ip)
    if not quota["ok"]:
        raise HTTPException(
            status_code=429,
            detail={
                "codigo": "quota_excedida",
                "mensagem": "Quota diária de emissão de chaves esgotada.",
            },
            headers={"Retry-After": "86400"},
        )

    # Ponto de partida conservador; ajustável depois via revogar + emitir pelo
    # admin. O consumidor nunca escolhe quota nem escopo nesta superfície.
    emitida = auth.emitir(
        obter_sink(request), entrada.consumidor,
        quota_minuto=30, quota_dia=2000, escopos=ESCOPOS_PUBLICOS,
    )
    return {"dados": {
        "prefixo": emitida.prefixo,
        "chave": emitida.chave_completa,
        "escopos": ESCOPOS_PUBLICOS,
        "aviso": "Guarde agora: a chave completa não é exibida de novo.",
    }}


@app.get("/v1/empresas", tags=["empresas"])
async def listar_empresas(
    request: Request,
    response: Response,
    q: str | None = Query(None, description="Busca por denominação, CNPJ ou ticker"),
    setor: str | None = Query(
        None, description="Filtra pelo setor de atividade declarado no cadastro da CVM"),
    segmento: str | None = Query(
        None, description="Segmento de listagem na B3 (NM, N1, N2, MB...)"),
    listada_b3: bool | None = Query(
        None, description="Só companhias com registro de negociação na B3"),
    com_balanco: bool | None = Query(
        None, description="Só companhias que publicaram DFP ou ITR"),
    limite: int = Query(
        50, ge=1, le=500, description="Tamanho da página, até 500 linhas por chamada"),
    cursor: str | None = Query(
        None, description="Cursor opaco de 'proximo_cursor' da chamada anterior — "
                          "leva à página seguinte. Omitido, começa do início"),
    _chave: dict = Depends(exigir_chave),
) -> Any:
    """Busca companhias no universo unificado CVM + B3.

    A CVM sozinha inclui companhia aberta que nunca teve ação negociada; os
    filtros `listada_b3` e `com_balanco`, combinados, recortam o universo que
    interessa a quem faz análise fundamentalista — quem de fato negocia e já
    publicou pelo menos uma demonstração. O `total` no topo da resposta é
    sobre esse universo filtrado inteiro, antes do corte da página; a lista
    de baixo é só a página pedida, paginada por cursor.
    """
    sink = obter_sink(request)
    exigir_vista(sink, "gold_empresa", _chave)
    etag = _etag(
        sink,
        f"empresas:{q}:{setor}:{segmento}:{listada_b3}:{com_balanco}:{limite}:{cursor}",
    )
    if (r := _talvez_304(request, etag)):
        return r

    onde, params = ["1=1"], []
    if q:
        # Ticker casa por prefixo do termo, não por substring: a B3 registra a
        # raiz ("PETR"), e quem busca digita o papel ("PETR4").
        onde.append(
            "(lower(denom_social) LIKE ? OR lower(denom_comerc) LIKE ? "
            "OR cnpj LIKE ? "
            "OR (COALESCE(ticker, '') != '' AND ? LIKE lower(ticker) || '%'))"
        )
        params += [f"%{q.lower()}%", f"%{q.lower()}%", f"%{q}%", q.lower()]
    if setor:
        onde.append("lower(setor_atividade) LIKE ?")
        params.append(f"%{setor.lower()}%")
    if segmento:
        onde.append("lower(COALESCE(segmento_listagem, '')) = ?")
        params.append(segmento.lower())
    # A CVM registra companhia que nunca teve ação em bolsa, e a B3 lista ETF
    # e BDR que não publicam balanço. Os dois filtros juntos dão o universo
    # que interessa a quem faz análise fundamentalista.
    if listada_b3 is not None:
        onde.append("COALESCE(listada_b3, FALSE) = ?")
        params.append(listada_b3)
    if com_balanco is not None:
        onde.append(
            ("cd_cvm IN" if com_balanco else "cd_cvm NOT IN")
            + " (SELECT cd_cvm FROM gold_demonstracoes)"
        )
    # O total do universo filtrado, antes do cursor: é o número que a tela
    # mostra ("564 companhias") e que uma página sozinha não sabe.
    total = sink.um(
        f"SELECT count(*) AS n FROM gold_empresa WHERE {' AND '.join(onde)}",
        params,
    )["n"]

    desloc = _cursor_decodificar(cursor)
    if desloc:
        onde.append("cd_cvm > ?")
        params.append(desloc["cd_cvm"])

    linhas = sink.consultar(
        f"SELECT * FROM gold_empresa WHERE {' AND '.join(onde)} "
        f"ORDER BY cd_cvm LIMIT ?",
        [*params, limite + 1],
    )
    proximo = None
    if len(linhas) > limite:
        linhas = linhas[:limite]
        proximo = _cursor_codificar({"cd_cvm": linhas[-1]["cd_cvm"]})

    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "public, max-age=300"
    return {"dados": proveniencia.decorar(
        sink, linhas, classe="empresa", chave=_chave,
    ), "total": total,
            "proximo_cursor": proximo}


@app.get("/v1/empresas/{cd_cvm}", tags=["empresas"])
async def obter_empresa(
    request: Request, response: Response,
    cd_cvm: int = Path(..., description="Código CVM que identifica a companhia — a "
                                        "mesma chave usada em todas as outras rotas de empresa"),
    _chave: dict = Depends(exigir_chave),
) -> Any:
    """Ficha de uma companhia no universo unificado CVM + B3.

    A mesma linha que aparece em `/v1/empresas`, isolada por `cd_cvm` — para
    quem já sabe qual empresa quer, sem paginar a lista inteira.
    """
    sink = obter_sink(request)
    exigir_vista(sink, "gold_empresa", _chave)
    linha = sink.um("SELECT * FROM gold_empresa WHERE cd_cvm = ?", (cd_cvm,))
    if linha is None:
        raise HTTPException(
            status_code=404,
            detail={"codigo": "empresa_nao_encontrada",
                    "mensagem": f"Nenhuma companhia com cd_cvm {cd_cvm}."},
        )
    etag = _etag(sink, f"empresa:{cd_cvm}")
    if (r := _talvez_304(request, etag)):
        return r
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "public, max-age=300"
    return {"dados": proveniencia.decorar(
        sink, [linha], classe="empresa", chave=_chave,
    )[0]}


@app.get("/v1/empresas/{cd_cvm}/demonstracoes", tags=["demonstrações"])
async def demonstracoes(
    request: Request, response: Response,
    cd_cvm: int = Path(..., description="Código CVM da companhia"),
    tipo: str | None = Query(
        None, pattern="^(DFP|ITR|dfp|itr)$",
        description="DFP (anual) ou ITR (trimestral). Omitido, traz os dois"),
    grupo: str | None = Query(
        None, description="Grupo contábil da CVM: BPA, BPP, DRE, DFC_MI, DFC_MD, "
                          "DVA, DRA ou DMPL"),
    de: str | None = Query(None, description="dt_refer mínima (AAAA-MM-DD)"),
    ate: str | None = Query(None, description="dt_refer máxima (AAAA-MM-DD)"),
    consolidado: bool = Query(
        True, description="TRUE para consolidado, FALSE para individual. Os dois "
                          "escopos nunca devem ser somados na mesma conta"),
    conta: str | None = Query(None, description="Prefixo do código da conta"),
    limite: int = Query(200, ge=1, le=2000, description="Tamanho da página, até 2000 linhas"),
    cursor: str | None = Query(
        None, description="Cursor de 'proximo_cursor' da chamada anterior"),
    _chave: dict = Depends(exigir_chave),
) -> Any:
    """Contas contábeis publicadas por uma companhia, já filtradas e prontas
    para somar.

    Cada linha já passou pelas armadilhas do dado padronizado da CVM: só a
    versão mais recente de cada reapresentação, só `ORDEM_EXERC = 'ÚLTIMO'`,
    valor normalizado pela escala declarada (`vl_conta_norm`). O que a rota
    não decide por conta própria é o que teria de ser decisão explícita de
    quem consulta — individual vs. consolidado (`consolidado`) e, no ITR,
    acumulado no ano vs. trimestre isolado: aqui a linha vem como a CVM
    publicou, **acumulada**; para o trimestre já isolado, use
    `/v1/empresas/{cd_cvm}/trimestres`.
    """
    sink = obter_sink(request)
    etag = _etag(sink, f"dem:{cd_cvm}:{tipo}:{grupo}:{de}:{ate}:{consolidado}:{conta}:{limite}:{cursor}")
    if (r := _talvez_304(request, etag)):
        return r

    onde = ["cd_cvm = ?", "consolidado = ?"]
    params: list[Any] = [cd_cvm, consolidado]
    if tipo:
        onde.append("upper(tipo_doc) = ?")
        params.append(tipo.upper())
    if grupo:
        onde.append("upper(grupo) = ?")
        params.append(grupo.upper())
    if de:
        onde.append("dt_refer >= ?")
        params.append(de)
    if ate:
        onde.append("dt_refer <= ?")
        params.append(ate)
    if conta:
        onde.append("cd_conta LIKE ?")
        params.append(f"{conta}%")
    desloc = _cursor_decodificar(cursor)
    if desloc:
        onde.append("(dt_refer, cd_conta) > (?, ?)")
        params += [desloc["dt_refer"], desloc["cd_conta"]]

    exigir_vista(sink, "gold_demonstracoes", _chave)
    linhas = sink.consultar(
        f"SELECT * FROM gold_demonstracoes WHERE {' AND '.join(onde)} "
        f"ORDER BY dt_refer, cd_conta LIMIT ?",
        [*params, limite + 1],
    )
    proximo = None
    if len(linhas) > limite:
        linhas = linhas[:limite]
        proximo = _cursor_codificar(
            {"dt_refer": linhas[-1]["dt_refer"], "cd_conta": linhas[-1]["cd_conta"]}
        )

    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "public, max-age=300"
    return {"dados": proveniencia.decorar(
        sink, linhas, classe="demonstracao_financeira", chave=_chave,
    ), "proximo_cursor": proximo}


@app.get("/v1/empresas/{cd_cvm}/trimestres", tags=["demonstrações"])
async def trimestres(
    request: Request, response: Response,
    cd_cvm: int = Path(..., description="Código CVM da companhia"),
    conta: str | None = Query(None, description="Prefixo do código da conta"),
    exercicio: str | None = Query(
        None, description="Ano do exercício (ex.: '2024'). Omitido, traz todos"),
    consolidado: bool = Query(
        True, description="TRUE para consolidado, FALSE para individual"),
    limite: int = Query(200, ge=1, le=2000, description="Tamanho da página, até 2000 linhas"),
    _chave: dict = Depends(exigir_chave),
) -> Any:
    """ITR com o trimestre isolado já calculado (o acumulado YTD desfeito).

    O ITR trimestral que a CVM publica traz contas de fluxo (DRE, DFC, DVA,
    DRA) acumuladas desde o início do ano, não o trimestre isolado — somar Q1
    e Q2 acumulados não dá "primeiro semestre", dá quase o dobro dele. Esta
    rota já faz a subtração (Q2 isolado = Q2 acumulado − Q1 acumulado) e
    devolve o trimestre de verdade. Contas de posição (BPA, BPP, DMPL) não
    têm essa armadilha — elas não acumulam, e aqui saem como no arquivo
    original.
    """
    sink = obter_sink(request)
    onde = ["cd_cvm = ?", "consolidado = ?"]
    params: list[Any] = [cd_cvm, consolidado]
    if conta:
        onde.append("cd_conta LIKE ?")
        params.append(f"{conta}%")
    if exercicio:
        onde.append("exercicio = ?")
        params.append(exercicio)
    exigir_vista(sink, "gold_itr_trimestre", _chave)
    linhas = sink.consultar(
        f"SELECT * FROM gold_itr_trimestre WHERE {' AND '.join(onde)} "
        f"ORDER BY dt_refer, cd_conta LIMIT ?",
        [*params, limite],
    )
    etag = _etag(sink, f"tri:{cd_cvm}:{conta}:{exercicio}:{consolidado}")
    response.headers["ETag"] = etag
    return {"dados": proveniencia.decorar(
        sink, linhas, classe="demonstracao_financeira", chave=_chave,
    )}


@app.get("/v1/empresas/{cd_cvm}/metricas", tags=["demonstrações"])
async def metricas(
    request: Request, response: Response,
    cd_cvm: int = Path(..., description="Código CVM da companhia"),
    nomes: str | None = Query(
        None, description="Lista de chaves de métrica separadas por vírgula "
                          "(ver /v1/meta/campos-calculados ou /admin/api/metricas "
                          "para os nomes disponíveis). Omitida, calcula todas"),
    consolidado: bool = Query(
        True, description="TRUE para consolidado, FALSE para individual"),
    _chave: dict = Depends(exigir_chave),
) -> Any:
    """Indicadores fundamentalistas calculados a partir das demonstrações.

    Cada métrica é uma fórmula sobre conta contábil (ex.: liquidez corrente
    = ativo circulante / passivo circulante), editável em `/admin/api/metricas`
    sem deploy. A resposta carrega a proveniência da demonstração de onde
    cada indicador saiu — um número sem rastro até o arquivo oficial não
    serve para decisão.
    """
    from .metricas import calcular

    sink = obter_sink(request)
    pedidos = [n.strip() for n in (nomes or "").split(",") if n.strip()] or None
    return {"dados": calcular(sink, cd_cvm, consolidado, pedidos)}


@app.get("/v1/meta/carga", tags=["catálogo"])
async def meta_carga(
    request: Request,
    dataset: str | None = Query(
        None, description="Restringe ao mapeamento com esta chave (ex.: 'cvm_dfp'). "
                          "Omitido, traz todos"),
    limite: int = Query(
        50, ge=1, le=500, description="Quantas execuções recentes trazer, no máximo 500"),
    _chave: dict = Depends(exigir_chave),
) -> Any:
    """Relatório por execução: o que a carga trouxe e o que ela pesa.

    Físico é medido — bytes vêm do catálogo do banco e da coluna do bronze.
    Financeiro é derivado: GB medidos vezes a tarifa vigente em `cfg_tarifa`,
    e o câmbio sai da série que a configuração indica. O campo `medicao` diz
    qual número é medida e qual é conta, e o que ficou de fora.
    """
    return custo.painel(obter_sink(request), dataset, limite)


@app.get("/v1/cotacoes/{ticker}", tags=["negociação"])
async def cotacoes(
    request: Request, response: Response,
    ticker: str = Path(..., description="Código de negociação na B3 (ex.: PETR4)"),
    de: str | None = Query(None, description="Data inicial, AAAA-MM-DD"),
    ate: str | None = Query(None, description="Data final, AAAA-MM-DD"),
    limite: int = Query(200, ge=1, le=2000, description="Tamanho da página, até 2000 pregões"),
    cursor: str | None = Query(
        None, description="Cursor de 'proximo_cursor' da chamada anterior"),
    _chave: dict = Depends(exigir_chave),
) -> Any:
    """Série histórica de pregão do lote padrão de um papel, com volatilidade.

    Vem do COTAHIST da B3 — o mesmo arquivo que qualquer corretora usa para
    reconstruir preço histórico. `hv21`/`hv63` (volatilidade histórica de 21
    e 63 pregões) são calculadas sobre a própria série, não vêm da fonte, e
    só ficam completas a partir do vigésimo primeiro/sexagésimo terceiro
    pregão carregado.
    """
    sink = obter_sink(request)
    etag = _etag(sink, f"cot:{ticker}:{de}:{ate}:{limite}:{cursor}")
    if (r := _talvez_304(request, etag)):
        return r

    onde = ["ticker = ?"]
    params: list[Any] = [ticker.upper()]
    if de:
        onde.append("dt_pregao >= ?")
        params.append(de)
    if ate:
        onde.append("dt_pregao <= ?")
        params.append(ate)
    if (desloc := _cursor_decodificar(cursor)):
        onde.append("dt_pregao > ?")
        params.append(desloc["dt_pregao"])

    exigir_vista(sink, "gold_cotacoes", _chave)
    linhas = sink.consultar(
        f"SELECT * FROM gold_cotacoes WHERE {' AND '.join(onde)} "
        f"ORDER BY dt_pregao LIMIT ?",
        [*params, limite + 1],
    )
    proximo = None
    if len(linhas) > limite:
        linhas = linhas[:limite]
        proximo = _cursor_codificar({"dt_pregao": linhas[-1]["dt_pregao"]})

    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "public, max-age=300"
    return {"dados": proveniencia.decorar(
        sink, linhas, classe="negociacao_b3", chave=_chave,
    ), "proximo_cursor": proximo}


@app.get("/v1/opcoes/{ticker}", tags=["negociação"])
async def opcoes(
    request: Request, response: Response,
    ticker: str = Path(..., description="Código do ativo-objeto na B3 (ex.: PETR4, não o "
                                        "código da série de opção)"),
    vencimento: str | None = Query(None, description="Vencimento, AAAA-MM-DD"),
    pregao: str | None = Query(
        None, description="Data do pregão. Omitida, vale o último publicado."
    ),
    tipo: str | None = Query(None, description="CALL ou PUT"),
    limite: int = Query(
        500, ge=1, le=2000, description="Tamanho da página, até 2000 séries"),
    cursor: str | None = Query(
        None, description="Cursor de 'proximo_cursor' da chamada anterior"),
    _chave: dict = Depends(exigir_chave),
) -> Any:
    """Cadeia de opções de um ativo-objeto num pregão, com implícita e gregas.

    Vem do COTAHIST da B3, sob uso pessoal (ver ADR-18) — não é redistribuído
    a terceiros. Sem `pregao`, responde o último pregão publicado *daquele
    papel*, não o último da base: um papel que parou de negociar devolveria
    vazio se o corte fosse global, o que pareceria ausência de dado em vez de
    ausência de negócio. Volatilidade implícita e gregas são calculadas por
    Black-Scholes a partir do preço do ativo-objeto no mesmo pregão.
    """
    sink = obter_sink(request)
    etag = _etag(sink, f"opc:{ticker}:{vencimento}:{pregao}:{tipo}:{limite}:{cursor}")
    if (r := _talvez_304(request, etag)):
        return r

    exigir_vista(sink, "gold_opcoes", _chave)
    alvo = ticker.upper()
    if not pregao:
        ultimo = sink.um(
            "SELECT max(dt_pregao) AS dia FROM gold_opcoes WHERE ticker_objeto = ?",
            (alvo,),
        )
        pregao = ultimo["dia"] if ultimo else None
        if pregao is None:
            return {"dados": [], "proximo_cursor": None}

    onde = ["ticker_objeto = ?", "dt_pregao = ?"]
    params: list[Any] = [alvo, pregao]
    if vencimento:
        onde.append("dt_vencimento = ?")
        params.append(vencimento)
    if tipo:
        onde.append("tipo = ?")
        params.append(tipo.upper())
    if (desloc := _cursor_decodificar(cursor)):
        onde.append("(dt_vencimento, strike) > (?, ?)")
        params += [desloc["dt_vencimento"], desloc["strike"]]

    linhas = sink.consultar(
        f"SELECT * FROM gold_opcoes WHERE {' AND '.join(onde)} "
        f"ORDER BY dt_vencimento, strike LIMIT ?",
        [*params, limite + 1],
    )
    proximo = None
    if len(linhas) > limite:
        linhas = linhas[:limite]
        proximo = _cursor_codificar({
            "dt_vencimento": linhas[-1]["dt_vencimento"],
            "strike": linhas[-1]["strike"],
        })

    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "public, max-age=300"
    return {"dados": proveniencia.decorar(
        sink, linhas, classe="negociacao_b3", chave=_chave,
    ), "proximo_cursor": proximo}


@app.get("/v1/opcoes/{ticker}/vencimentos", tags=["negociação"])
async def vencimentos(
    request: Request,
    ticker: str = Path(..., description="Código do ativo-objeto na B3 (ex.: PETR4)"),
    pregao: str | None = Query(
        None, description="Data do pregão, AAAA-MM-DD. Omitida, vale o último "
                          "pregão publicado daquele papel"),
    _chave: dict = Depends(exigir_chave),
) -> Any:
    """Vencimentos disponíveis, para o consumidor não varrer a cadeia inteira
    só para descobrir o que existe.

    Sem `pregao`, vale o último pregão *daquele papel* — a mesma regra de
    `/v1/opcoes`. Sem isso as duas rotas discordavam: a cadeia respondia um
    pregão e a lista agregava o histórico inteiro, oferecendo vencimento já
    liquidado como se ainda existisse. Com trinta pregões carregados, PETR4
    listava seis vencimentos vencidos antes do primeiro válido.

    A resposta publica `pregao` (raiz) e `dt_pregao` (por item) para o
    consumidor saber de que dia é a lista sem inferir pelo relógio; antes de
    tratar um vencimento como vigente, confira também `GET /v1/meta/frescor`
    (`ultima_publicacao.janela` da classe `negociacao_b3`).
    """
    sink = obter_sink(request)
    exigir_vista(sink, "gold_opcoes", _chave)
    alvo = ticker.upper()
    if not pregao:
        ultimo = sink.um(
            "SELECT max(dt_pregao) AS dia FROM gold_opcoes WHERE ticker_objeto = ?",
            (alvo,),
        )
        pregao = ultimo["dia"] if ultimo else None
        if pregao is None:
            return {"dados": [], "pregao": None}
    onde = ["ticker_objeto = ?", "dt_pregao = ?"]
    params: list[Any] = [alvo, pregao]
    # `com_sigma` é o que separa vencimento útil de vencimento morto. O que
    # vence no próprio pregão tem prazo zero: não existe sigma que resolva
    # Black-Scholes sem tempo, então a cadeia inteira sai sem volatilidade e
    # sem grega. Devolver só a contagem de contratos fazia esse vencimento
    # parecer igual aos outros até o consumidor abri-lo.
    dados = sink.consultar(
        f"SELECT dt_pregao, dt_vencimento, count(*) AS contratos, "
        f"       sum(CASE WHEN volatilidade_implicita IS NOT NULL THEN 1 ELSE 0 END)"
        f"         AS com_sigma, "
        f"       max(CASE WHEN prazo_anos > 0 THEN 0 ELSE 1 END) AS vence_no_pregao, "
        f"       min(strike) AS menor_strike, max(strike) AS maior_strike "
        f"FROM gold_opcoes WHERE {' AND '.join(onde)} "
        f"GROUP BY dt_pregao, dt_vencimento ORDER BY dt_vencimento",
        params,
    )
    return {"dados": dados, "pregao": pregao}


@app.get("/v1/meta/datasets", tags=["catálogo"])
async def meta_datasets(request: Request, _chave: dict = Depends(exigir_chave)) -> Any:
    """Cada mapeamento fonte→classe: o que ele extrai e como tipa cada coluna.

    É o catálogo técnico por trás de `/v1/meta/classes` — enquanto aquela
    rota descreve a classe de informação, esta descreve os mapeamentos que a
    alimentam: qual fonte, qual coluna de origem virou qual coluna destino,
    e se é obrigatória.
    """
    sink = obter_sink(request)
    saida = []
    for ds in repo.listar_datasets(sink):
        saida.append({
            "chave": ds["chave"],
            "nome": ds["nome"],
            "descricao": ds["descricao"],
            "fonte": ds["fonte_chave"],
            "tabela": ds["tabela_destino"],
            "versao_config": ds["versao"],
            "colunas": [
                {"nome": c["nome_destino"], "tipo": c["tipo"],
                 "origem": c["nome_origem"], "obrigatoria": c["obrigatoria"]}
                for c in repo.colunas_do(sink, ds["id"])
            ],
        })
    return {"dados": saida}


@app.get("/v1/meta/campos-calculados", tags=["catálogo"])
async def meta_calculados(request: Request, _chave: dict = Depends(exigir_chave)) -> Any:
    """Todo campo derivado declarado em cada mapeamento, com a expressão e as
    colunas de origem que ele usa.

    Um campo calculado que não conseguisse declarar as colunas de origem que
    lê falharia na validação, não na carga — esta rota é onde essa
    declaração fica visível, para auditar de onde cada derivada vem sem ler
    código.
    """
    sink = obter_sink(request)
    saida = []
    for ds in repo.listar_datasets(sink):
        for c in repo.calculados_do(sink, ds["id"]):
            saida.append({
                "dataset": ds["chave"],
                "nome": c["nome"],
                "classe": c["classe"],
                "expressao": c["expressao"],
                "colunas_origem": c["colunas_origem"].split(","),
                "descricao": c["descricao"],
            })
    return {"dados": saida}


@app.get("/v1/meta/publicacoes", tags=["catálogo"])
async def meta_publicacoes(request: Request, _chave: dict = Depends(exigir_chave)) -> Any:
    """As últimas 50 versões de gold publicadas, mais recente primeiro.

    Gold só muda quando há publicação — a versão listada aqui é a mesma que
    o ETag de cada resposta usa como identidade de cache. Reverter uma
    publicação move o ponteiro para uma versão anterior sem apagar dado
    nenhum.
    """
    sink = obter_sink(request)
    return {"dados": sink.consultar(
        "SELECT versao, publicado_em, execucao_id, observacao FROM publicacao "
        "ORDER BY versao DESC LIMIT 50"
    )}


@app.get("/v1/meta/classes", tags=["catálogo"])
async def meta_classes(request: Request, _chave: dict = Depends(exigir_chave)) -> Any:
    """As classes de informação e quem as alimenta."""
    sink = obter_sink(request)
    saida = []
    for c in repo.listar_classes(sink, so_ativas=True):
        # A precedência declarada faz parte do contrato: é o que explica *por
        # que* uma fonte venceu um atributo disputado, não só qual venceu.
        saida.append({
            "chave": c["chave"], "nome": c["nome"], "descricao": c["descricao"],
            "identidade": c["chave_identidade"].split(","),
            "resolucao": c["resolucao"],
            "precedencia": [p for p in (c["precedencia"] or "").split(",") if p],
            "fontes": [d["chave"] for d in repo.datasets_da_classe(sink, c["chave"])],
            "atributos": [
                {"nome": a["nome"], "tipo": a["tipo"], "origem": a["origem"],
                 "unidade": a["unidade"], "descricao": a["descricao"],
                 "precedencia": [p for p in (a["precedencia"] or "").split(",") if p]}
                for a in repo.atributos_de(sink, c["id"])
            ],
        })
    return {"dados": saida}


@app.get("/v1/empresas/{cd_cvm}/resumo", tags=["empresas"])
async def resumo_da_empresa(
    request: Request,
    cd_cvm: int = Path(..., description="Código CVM da companhia"),
    _chave: dict = Depends(exigir_chave),
) -> Any:
    """O que existe para esta companhia, e quanto — sem trazer nenhum número.

    É o que permite uma tela de entrada por empresa não oferecer porta que não
    abre: cada família de dado vem com contagem e período, e a que não tem
    linha nenhuma simplesmente não aparece na resposta.

    Devolve os grupos como a fonte os nomeia (`BPA`, `DRE`, …) em vez de
    traduzi-los: quem sabe que `BPA` é balanço patrimonial é a apresentação,
    que já carrega esse dicionário. Traduzir aqui poria conhecimento de uma
    fonte específica dentro da API.
    """
    sink = obter_sink(request)
    exigir_vista(sink, "gold_empresa", _chave)
    if sink.um("SELECT 1 AS ok FROM gold_empresa WHERE cd_cvm = ?", (cd_cvm,)) is None:
        raise HTTPException(
            status_code=404,
            detail={"codigo": "empresa_nao_encontrada",
                    "mensagem": f"Nenhuma companhia com cd_cvm {cd_cvm}."},
        )

    grupos: list[dict] = []
    if publicacao.classe_da_vista(sink, "gold_demonstracoes") is not None and auth.pode_ler(
        _chave, "demonstracao_financeira"
    ):
        grupos = sink.consultar(
            "SELECT grupo, upper(tipo_doc) AS tipo_doc, consolidado, "
            "count(*) AS linhas, min(dt_refer) AS de, max(dt_refer) AS ate "
            "FROM gold_demonstracoes WHERE cd_cvm = ? "
            "GROUP BY grupo, upper(tipo_doc), consolidado "
            "ORDER BY grupo, tipo_doc, consolidado",
            (cd_cvm,),
        )

    trimestres = None
    if grupos:
        linha = sink.um(
            "SELECT count(*) AS linhas, min(dt_refer) AS de, max(dt_refer) AS ate "
            "FROM gold_itr_trimestre WHERE cd_cvm = ?",
            (cd_cvm,),
        )
        if linha and linha["linhas"]:
            trimestres = dict(linha)

    return {"dados": {
        "cd_cvm": cd_cvm,
        "demonstracoes": [
            {**dict(g), "linhas": int(g["linhas"]), "consolidado": bool(g["consolidado"])}
            for g in grupos
        ],
        "trimestres": trimestres,
        "metricas": [m["nome"] for m in metricas_cat.listar(sink)] if grupos else [],
        "capturas": _capturas_da_empresa(sink, cd_cvm, bool(grupos)),
    }}


def _capturas_da_empresa(sink: Sink, cd_cvm: int, com_demonstracoes: bool) -> list[dict]:
    """Os arquivos que originaram os números **desta** companhia.

    Duas correções que só apareceram ao olhar a tela. A primeira: listar as
    últimas capturas do sistema mostrava arquivos que não têm nada a ver com a
    companhia aberta — a lista é filtrada pelas capturas que de fato
    produziram linha dela.

    A segunda: o mesmo arquivo é capturado uma vez por mapeamento, então o ZIP
    da DFP aparece duas vezes, uma para `cvm_dfp` e outra para
    `cvm_dfp_empresa` (é a questão 4 do §14). São dois registros do mesmo
    documento; para quem quer conferir a digital, é um arquivo só. Agrupamos
    por `sha256` e ficamos com a primeira captura.
    """
    fontes = ["SELECT captura_id FROM gold_empresa WHERE cd_cvm = ?"]
    params: list[Any] = [cd_cvm]
    if com_demonstracoes:
        fontes.append("SELECT captura_id FROM gold_demonstracoes WHERE cd_cvm = ?")
        params.append(cd_cvm)

    linhas = sink.consultar(
        "SELECT id, nome_arquivo, sha256, tamanho_bytes FROM bronze_captura "
        f"WHERE id IN ({' UNION '.join(fontes)}) ORDER BY id DESC",
        params,
    )
    por_hash: dict[str, dict] = {}
    for linha in linhas:
        por_hash.setdefault(linha["sha256"], dict(linha))
    return list(por_hash.values())


# --------------------------------------------------------------------------
# Bronze — o arquivo oficial, servido para conferência
# --------------------------------------------------------------------------
def _captura_ou_404(sink: Sink, captura_id: int, chave: dict) -> dict:
    """A captura, se ela existe e se esta chave alcança a classe que ela alimenta.

    O escopo vale aqui como vale em gold: a captura é o dado antes de virar
    linha, então liberá-la sem checar daria, por uma porta lateral, o que a
    porta da frente nega.
    """
    linha = sink.um(
        "SELECT id, dataset_chave, janela, url, nome_arquivo, sha256, "
        "tamanho_bytes, capturado_em FROM bronze_captura WHERE id = ?",
        (captura_id,),
    )
    if linha is None:
        raise HTTPException(
            status_code=404,
            detail={"codigo": "captura_nao_encontrada",
                    "mensagem": f"Não há captura com id {captura_id}."},
        )
    ds = repo.dataset_vigente(sink, linha["dataset_chave"])
    classe = ds["classe_chave"] if ds else None
    if not auth.pode_ler(chave, classe):
        raise HTTPException(
            status_code=403,
            detail={
                "codigo": "escopo_insuficiente",
                "mensagem": f"A chave de '{chave.get('consumidor')}' não tem "
                            f"escopo para a classe '{classe}'.",
                },
            )
    if (
        linha["dataset_chave"] in proveniencia.DATASETS_B3
        and not auth.pode_ver_fonte(chave, "b3")
    ):
        raise HTTPException(
            status_code=403,
            detail={
                "codigo": "escopo_insuficiente",
                "mensagem": f"A chave de '{chave.get('consumidor')}' não tem "
                            "escopo para a fonte B3.",
            },
        )
    return {**dict(linha), "classe": classe}


def _sobre_captura(linha: dict) -> dict:
    capturado = linha["capturado_em"]
    return {
        "id": linha["id"],
        "classe": linha["classe"],
        "mapeamento": linha["dataset_chave"],
        "janela": linha["janela"],
        "arquivo": linha["nome_arquivo"],
        "sha256": linha["sha256"],
        "tamanho_bytes": int(linha["tamanho_bytes"]),
        "capturado_em": (
            capturado.isoformat() if hasattr(capturado, "isoformat") else str(capturado)
        ),
        "url_de_origem": linha["url"],
        "arquivo_em": f"/v1/capturas/{linha['id']}/arquivo",
        "como_conferir": (
            f"Baixe o arquivo e rode `shasum -a 256 {linha['nome_arquivo']}`. "
            f"A saída tem de ser exatamente o `sha256` acima. Se bater, o que "
            f"está guardado aqui é byte a byte o que a fonte publicou."
        ),
    }


@app.get("/v1/capturas/{captura_id}", tags=["proveniência"])
async def sobre_captura(
    request: Request,
    captura_id: int = Path(..., description="Id de bronze_captura — vem em "
                                            "proveniencia.captura de qualquer resposta de dado"),
    chave: dict = Depends(exigir_chave),
) -> Any:
    """O que se sabe sobre um arquivo capturado, sem baixá-lo."""
    sink = obter_sink(request)
    return {"dados": _sobre_captura(_captura_ou_404(sink, captura_id, chave))}


@app.get("/v1/capturas/{captura_id}/arquivo", tags=["proveniência"])
async def arquivo_da_captura(
    request: Request,
    response: Response,
    captura_id: int = Path(..., description="Id de bronze_captura — vem em "
                                            "proveniencia.captura de qualquer resposta de dado"),
    chave: dict = Depends(exigir_chave),
) -> Any:
    """O arquivo oficial, byte a byte como a fonte o publicou.

    É o que transforma a proveniência de afirmação em prova. Até esta rota
    existir, o `sha256` na resposta era um número que o consumidor tinha de
    aceitar no fio do bigode: a URL de origem não serve para conferir, porque
    ela é endereço mutável — a fonte regenera o arquivo a cada reapresentação,
    e baixar de novo não reproduz a captura de antes.

    O `ETag` é o próprio `sha256`. Conteúdo imutável por construção, então uma
    segunda chamada com `If-None-Match` devolve 304 e nenhum byte.
    """
    sink = obter_sink(request)
    linha = _captura_ou_404(sink, captura_id, chave)
    etag = f'"{linha["sha256"]}"'

    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})

    payload = ingestao.payload_de(sink, captura_id)
    # Nome de arquivo vem da nossa própria captura, mas aspas ou quebra de
    # linha no cabeçalho quebrariam a resposta — sanear é barato.
    nome = "".join(c for c in linha["nome_arquivo"] if c.isprintable() and c != '"')
    return Response(
        content=payload,
        media_type="application/octet-stream",
        headers={
            "ETag": etag,
            "Content-Disposition": f'attachment; filename="{nome}"',
            # O consumidor confere sem precisar de outra chamada.
            "X-Conteudo-SHA256": linha["sha256"],
            "Cache-Control": "public, max-age=31536000, immutable",
        },
    )


@app.get("/v1/meta/correlacoes", tags=["catálogo"])
async def meta_correlacoes(
    request: Request, chave: dict = Depends(exigir_chave)
) -> Any:
    """As junções entre classes que a configuração declara.

    Só as que esta chave alcança inteiras: mostrar uma travessia que ela não
    pode executar seria anunciar porta fechada.
    """
    sink = obter_sink(request)
    saida = []
    for c in repo.listar_correlacoes(sink):
        if not (auth.pode_ler(chave, c["classe_origem"])
                and auth.pode_ler(chave, c["classe_destino"])):
            continue
        saida.append({
            "chave": c["chave"],
            "origem": c["classe_origem"],
            "destino": c["classe_destino"],
            "por": {"origem": c["atributo_origem"], "destino": c["atributo_destino"]},
            "relacionamento": c["relacionamento"],
            "descricao": c["descricao"],
        })
    return {"dados": saida}


@app.get("/v1/correlacoes/{chave_correlacao}", tags=["dados"])
async def executar_correlacao(
    request: Request,
    chave_correlacao: str = Path(
        ..., description="Chave declarada em cfg_correlacao — ver /v1/meta/correlacoes "
                         "para as travessias disponíveis"),
    campos: str | None = Query(
        None, description="colunas da classe de destino, separadas por vírgula"
    ),
    onde: str | None = Query(
        None, description="filtros sobre o destino: campo:valor,campo:valor"
    ),
    limite: int = Query(
        correlacao.LIMITE_PADRAO, ge=1, le=correlacao.LIMITE_MAXIMO,
        description="Tamanho da página de resultado da travessia"),
    chave: dict = Depends(exigir_chave),
) -> Any:
    """Atravessa uma correlação declarada.

    O escopo da chave vale para as duas pontas: se ela não lê a classe de
    destino, a consulta é negada inteira. Servir a origem com as colunas do
    destino omitidas em silêncio daria a impressão de que o dado não existe.
    """
    sink = obter_sink(request)
    try:
        origem, destino = correlacao.classes_da(sink, chave_correlacao)
    except correlacao.ErroCorrelacao as e:
        raise HTTPException(
            status_code=404,
            detail={"codigo": "correlacao_nao_declarada", "mensagem": str(e)},
        ) from e

    for classe in (origem, destino):
        if not auth.pode_ler(chave, classe):
            raise HTTPException(
                status_code=403,
                detail={
                    "codigo": "escopo_insuficiente",
                    "mensagem": f"A chave de '{chave.get('consumidor')}' não tem "
                                f"escopo para a classe '{classe}', que esta "
                                f"correlação atravessa.",
                },
            )

    filtros: dict[str, str] = {}
    for par in (onde or "").split(","):
        if not par.strip():
            continue
        if ":" not in par:
            raise HTTPException(
                status_code=400,
                detail={"codigo": "filtro_invalido",
                        "mensagem": f"'{par}' não é 'campo:valor'"},
            )
        campo, valor = par.split(":", 1)
        filtros[campo.strip()] = valor.strip()

    try:
        saida = correlacao.consultar(
            sink, chave_correlacao,
            campos_destino=[c.strip() for c in (campos or "").split(",") if c.strip()]
            or None,
            filtros_destino=filtros,
            limite=limite,
        )
        # Travessia é resposta de dado como qualquer outra: sai com
        # proveniência, não com as colunas internas da vista. Sem isto o
        # consumidor receberia `captura_id` e `publicado_em_versao` crus por
        # esta rota e proveniência decorada por todas as outras.
        saida["dados"] = proveniencia.decorar(
            sink, saida["dados"], classe=destino, chave=chave,
        )
        return saida
    except correlacao.ErroCorrelacao as e:
        raise HTTPException(
            status_code=400,
            detail={"codigo": "correlacao_invalida", "mensagem": str(e)},
        ) from e


@app.get("/v1/meta/contrato", tags=["catálogo"])
async def meta_contrato(
    request: Request,
    classe: str = Query(..., description="chave da classe de informação"),
    _chave: dict = Depends(exigir_chave),
) -> Any:
    """O que esta classe promete, e de onde cada campo vem.

    É `/v1/meta/classes` levado até o fim: além dos atributos, quais colunas de
    quais arquivos os alimentam, o que a normalização faz com cada um, o que a
    qualidade vigia e o que barra a publicação. Perfil ODCS — ver
    `docs/pesquisa-mercado.md` § Q6.
    """
    try:
        return {"dados": contrato.contrato(obter_sink(request), classe)}
    except repo.ErroConfiguracao as e:
        raise HTTPException(
            status_code=404,
            detail={"codigo": "classe_nao_encontrada", "mensagem": str(e)},
        ) from e


@app.get("/v1/meta/frescor", tags=["catálogo"])
async def meta_frescor(request: Request, _chave: dict = Depends(exigir_chave)) -> Any:
    """Quão velho está o dado de cada classe, contra o SLA declarado."""
    return {"dados": observabilidade.frescor(obter_sink(request))}


@app.get("/v1/meta/linhagem", tags=["catálogo"])
async def meta_linhagem(
    request: Request,
    classe: str = Query(..., description="chave da classe de informação"),
    atributo: str = Query(..., description="nome do atributo"),
    _chave: dict = Depends(exigir_chave),
) -> Any:
    """De onde veio este número: fonte, captura, regra que aprovou, publicação."""
    try:
        return {"dados": observabilidade.linhagem(obter_sink(request), classe, atributo)}
    except repo.ErroConfiguracao as e:
        raise HTTPException(
            status_code=404,
            detail={"codigo": "linhagem_nao_encontrada", "mensagem": str(e)},
        ) from e


@app.get("/v1/meta/execucoes", tags=["catálogo"])
async def meta_execucoes(
    request: Request,
    dataset: str | None = Query(
        None, description="Restringe ao mapeamento com esta chave. Omitido, traz todos"),
    status: str | None = Query(
        None, description="Filtra por status, separados por vírgula "
                          "(ex.: falha,bloqueada)"),
    limite: int = Query(
        50, ge=1, le=200, description="Quantas execuções recentes trazer, no máximo 200"),
    _chave: dict = Depends(exigir_chave),
) -> Any:
    """O que rodou e o que quebrou. É o que o painel do operador lê para
    responder 'o que falhou' sem abrir o banco."""
    sink = obter_sink(request)
    lista = [s.strip() for s in (status or "").split(",") if s.strip()]
    return {"dados": repo.execucoes(sink, limite, dataset, lista or None)}


@app.get("/v1/meta/execucoes/{execucao_id}/fases", tags=["catálogo"])
async def meta_fases(
    request: Request,
    execucao_id: int = Path(..., description="Id de log_execucao — vem em "
                                             "/v1/meta/execucoes"),
    _chave: dict = Depends(exigir_chave),
) -> Any:
    """Onde a carga gastou o tempo — não só que ela demorou."""
    return {"dados": observabilidade.linha_do_tempo(obter_sink(request), execucao_id)}


# --------------------------------------------------------------------------
# /v1/setups — estado do MCP (vigias de candle), não classe do motor
# --------------------------------------------------------------------------
# `registro` é o JSON inteiro do MCP (`~/dev/MCP/servers/mydata/armazem.py`),
# opaco para este arquivo: valida-se só o mínimo que a identidade exige
# (`setup.name`). O resto — o que cada campo de controle significa — é
# assunto do MCP, nunca deste servidor. Ver ADR-24 em docs/arquitetura.md.
class SetupEntrada(BaseModel):
    registro: dict[str, Any]


class SetupPatchEntrada(BaseModel):
    campo: str
    valor: Any = None


def _setup_linha(sink: Sink, consumidor: str, nome: str) -> dict | None:
    return sink.um(
        "SELECT registro, status FROM setup_mcp WHERE consumidor = ? AND nome = ?",
        (consumidor, nome),
    )


def _setup_ou_404(sink: Sink, consumidor: str, nome: str) -> dict:
    linha = _setup_linha(sink, consumidor, nome)
    if linha is None:
        raise HTTPException(
            status_code=404,
            detail={
                "codigo": "setup_inexistente",
                "mensagem": f"Não há setup '{nome}' para este consumidor.",
            },
        )
    return json.loads(linha["registro"])


@app.get("/v1/setups", tags=["setups"])
async def listar_setups(
    request: Request,
    incluir_inativos: bool = Query(
        False, description="Inclui setups com status inativo"),
    chave: dict = Depends(exigir_chave_setups),
) -> Any:
    """Os setups (vigias de candle) deste consumidor — nunca o de outro:
    isolamento é por `consumidor` da própria chave, não por filtro opcional."""
    sink = obter_sink(request)
    filtro = "" if incluir_inativos else "AND status = 'ativo'"
    linhas = sink.consultar(
        f"SELECT registro FROM setup_mcp WHERE consumidor = ? {filtro} "
        f"ORDER BY criado_em",
        (chave["consumidor"],),
    )
    return {"dados": [json.loads(l["registro"]) for l in linhas]}


@app.get("/v1/setups/{nome}", tags=["setups"])
async def obter_setup(
    request: Request,
    nome: str = Path(..., description="setup.name — a identidade do setup"),
    chave: dict = Depends(exigir_chave_setups),
) -> Any:
    sink = obter_sink(request)
    return {"dados": _setup_ou_404(sink, chave["consumidor"], nome)}


@app.post("/v1/setups", status_code=201, tags=["setups"])
async def criar_setup(
    entrada: SetupEntrada,
    request: Request,
    chave: dict = Depends(exigir_chave_setups),
) -> Any:
    """Espelha `ArmazemArquivo.salvar`: nome repetido é erro, não substituição
    silenciosa — desativar e recriar deixa rastro."""
    setup = entrada.registro.get("setup")
    nome = setup.get("name") if isinstance(setup, dict) else None
    if not isinstance(nome, str) or not nome.strip():
        raise HTTPException(
            status_code=400,
            detail={
                "codigo": "entrada_invalida",
                "mensagem": "registro.setup.name precisa ser string não vazia.",
            },
        )

    registro = dict(entrada.registro)
    registro.setdefault("status", "ativo")

    sink = obter_sink(request)
    consumidor = chave["consumidor"]
    if _setup_linha(sink, consumidor, nome) is not None:
        raise HTTPException(
            status_code=409,
            detail={
                "codigo": "setup_existente",
                "mensagem": f"Já existe um setup '{nome}' para este consumidor.",
            },
        )

    agora = datetime.now(timezone.utc)
    sink.executar(
        """INSERT INTO setup_mcp
           (consumidor, nome, registro, status, criado_em, atualizado_em)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (consumidor, nome, json.dumps(registro, ensure_ascii=False),
         registro["status"], agora, agora),
    )
    return {"dados": registro}


@app.patch("/v1/setups/{nome}", tags=["setups"])
async def anotar_setup(
    entrada: SetupPatchEntrada,
    request: Request,
    nome: str = Path(..., description="setup.name — a identidade do setup"),
    chave: dict = Depends(exigir_chave_setups),
) -> Any:
    """Espelha `ArmazemArquivo.anotar`: grava um campo de controle (ex.:
    `ultimo_pregao_notificado`) fora de `setup` — o setup em si é imutável
    depois de ativado, o que mantém o backtest da criação comparável com o
    comportamento monitorado."""
    if entrada.campo in ("setup", "status"):
        raise HTTPException(
            status_code=400,
            detail={
                "codigo": "campo_reservado",
                "mensagem": f"'{entrada.campo}' não é campo de controle: "
                            f"'setup' não muda depois de criado, e 'status' "
                            f"só muda por /desativar.",
            },
        )

    sink = obter_sink(request)
    consumidor = chave["consumidor"]
    registro = _setup_ou_404(sink, consumidor, nome)
    registro[entrada.campo] = entrada.valor
    sink.executar(
        "UPDATE setup_mcp SET registro = ?, atualizado_em = ? "
        "WHERE consumidor = ? AND nome = ?",
        (json.dumps(registro, ensure_ascii=False), datetime.now(timezone.utc),
         consumidor, nome),
    )
    return {"dados": registro}


@app.post("/v1/setups/{nome}/desativar", tags=["setups"])
async def desativar_setup(
    request: Request,
    nome: str = Path(..., description="setup.name — a identidade do setup"),
    chave: dict = Depends(exigir_chave_setups),
) -> Any:
    """Espelha `ArmazemArquivo.desativar`: devolve bool, nunca 404 — nome
    inexistente e setup já inativo são o mesmo "nada para fazer"."""
    sink = obter_sink(request)
    consumidor = chave["consumidor"]
    linha = _setup_linha(sink, consumidor, nome)
    if linha is None or linha["status"] != "ativo":
        return {"dados": {"desativado": False}}

    registro = json.loads(linha["registro"])
    registro["status"] = "inativo"
    sink.executar(
        "UPDATE setup_mcp SET registro = ?, status = 'inativo', atualizado_em = ? "
        "WHERE consumidor = ? AND nome = ?",
        (json.dumps(registro, ensure_ascii=False), datetime.now(timezone.utc),
         consumidor, nome),
    )
    return {"dados": {"desativado": True}}


# --------------------------------------------------------------------------
# /admin — plano de controle
# --------------------------------------------------------------------------
app.include_router(admin.router)
# Console central, Bloco A (ADR-25) — pacote isolado, tabelas próprias
# `console_*`, mesma sessão do dono (`exigir_admin`, reaproveitado por import).
app.include_router(console_api.router)

# ---------------------------------------------------------------------------
# Acesso à apresentação. Ela é do dono, não pública: com PORTAL_ADMIN_TOKEN
# definido, a raiz exige a sessão criada em /entrar. O token vira cookie
# HttpOnly — JavaScript não o lê, localStorage não o guarda, e nenhuma chave
# de API existe do lado do navegador.
# ---------------------------------------------------------------------------
PAGINA_ENTRAR = """<!doctype html>
<html lang="pt-BR">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Entrar — MyData</title>
<style>
 body {{ font-family: system-ui, sans-serif; display: grid; place-items: center;
        min-height: 100vh; margin: 0; background: #fafaf9; color: #1c1917; }}
 main {{ background: #fff; border: 1px solid #d6d3d1; border-radius: 6px;
        padding: 2rem; max-width: 22rem; width: 100%; }}
 form {{ margin: 0; }}
 label {{ display: block; font-weight: 600; margin-bottom: .5rem; }}
 input {{ width: 100%; box-sizing: border-box; padding: .5rem; font-size: 1rem;
         border: 1px solid #d6d3d1; border-radius: 4px; margin-bottom: 1rem; }}
 button {{ background: #1c1917; color: #fff; border: 0; border-radius: 4px;
          padding: .5rem 1rem; font-size: 1rem; cursor: pointer; width: 100%; }}
 #pk {{ margin-bottom: 1rem; }}
 button:focus-visible, input:focus-visible {{ outline: 3px solid #2f3d8f;
          outline-offset: 2px; }}
 p.erro {{ color: #b91c1c; }}
</style></head>
<body>
<main>
  <h1 style="font-size:1.1rem">MyData</h1>
  <p style="font-size:.9rem;color:#57534e">{convite}</p>
  {erro}
  {semente_id}
  {passkey}
  {formulario}
</main>
</body></html>"""

# Só um link, sem JavaScript: o portal é quem conduz o resto do fluxo. Fica
# antes do passkey por ser o caminho pensado para o dia a dia (Fase 2 do
# ADR-23) — token e passkey continuam abaixo, sem sair de cena.
BLOCO_SEMENTE_ID = """
<a href="/entrar/semente-id?destino={destino}"
   style="display:block;text-align:center;text-decoration:none;
          background:#1c1917;color:#fff;border-radius:4px;
          padding:.5rem 1rem;margin-bottom:1rem;">Entrar com semente.dev</a>
"""

# O bloco do passkey. JavaScript à mão, sem empacotador: esta página é servida
# pelo FastAPI antes de qualquer bundle existir, e é justamente a página que
# precisa funcionar quando o resto não carregou.
BLOCO_PASSKEY = """
<button id="pk" type="button">Entrar com passkey</button>
<p id="pkerro" class="erro" role="alert" hidden></p>
<script>
const b64 = (s) => Uint8Array.from(atob(s.replace(/-/g,'+').replace(/_/g,'/')),
                                   c => c.charCodeAt(0));
const b64u = (b) => btoa(String.fromCharCode(...new Uint8Array(b)))
                    .replace(/\\+/g,'-').replace(/\\//g,'_').replace(/=+$/,'');
const erro = (t) => {{ const p = document.getElementById('pkerro');
                       p.textContent = t; p.hidden = false; }};
document.getElementById('pk').addEventListener('click', async () => {{
  try {{
    const r = await fetch('/acesso/desafio', {{method:'POST'}});
    if (!r.ok) return erro('Nenhum autenticador registrado neste portal.');
    const o = await r.json();
    o.challenge = b64(o.challenge);
    (o.allowCredentials || []).forEach(c => {{ c.id = b64(c.id); }});
    const cred = await navigator.credentials.get({{publicKey: o}});
    const env = await fetch('/acesso/passkey', {{
      method:'POST', headers:{{'Content-Type':'application/json'}},
      body: JSON.stringify({{destino: {destino_js},  credencial: {{
        id: cred.id, rawId: b64u(cred.rawId), type: cred.type,
        response: {{
          clientDataJSON: b64u(cred.response.clientDataJSON),
          authenticatorData: b64u(cred.response.authenticatorData),
          signature: b64u(cred.response.signature),
          userHandle: cred.response.userHandle
                      ? b64u(cred.response.userHandle) : null,
        }},
      }}}}),
    }});
    const corpo = await env.json();
    if (!env.ok) return erro(corpo?.erro?.mensagem || 'Não consegui entrar.');
    window.location.assign(corpo.destino || '/');
  }} catch (e) {{
    // `NotAllowedError` é o cancelamento do gesto — não é falha do portal, e
    // dizer "erro" nesse caso mandaria o dono procurar defeito que não existe.
    erro(e && e.name === 'NotAllowedError'
         ? 'Autenticação cancelada.' : 'Este navegador não completou o passkey.');
  }}
}});
</script>
"""

FORMULARIO_TOKEN = """
<form method="post" action="/entrar">
  <input type="hidden" name="destino" value="{destino}">
  <label for="token">Token</label>
  <input id="token" name="token" type="password" autocomplete="current-password" required>
  <button type="submit">Entrar</button>
</form>
"""


def destino_local(valor: str | None) -> str:
    """Só caminho do próprio site. `//outro.site` é URL absoluta protocolo-
    relativa: sem esta checagem, um link com `?destino=//exemplo.com` faria o
    formulário de login mandar o dono para fora depois de autenticar."""
    if not valor or not valor.startswith("/") or valor.startswith("//"):
        return "/"
    return valor


def _pagina_entrar(sink: Sink, erro: str = "", status: int = 401,
                   destino: str = "/") -> Response:
    import json
    from html import escape

    destino = destino_local(destino)
    onde = "A administração" if destino.startswith("/admin") else "A apresentação"
    com_token = acesso.token_no_formulario(sink)
    com_passkey = acesso.ha_passkey(sink)

    if com_passkey and com_token:
        convite = f"{onde} é privada. Entre com o passkey, ou com o token."
    elif com_passkey:
        convite = f"{onde} é privada. Entre com o passkey registrado."
    else:
        convite = f"{onde} é privada. Informe o token de administração."

    corpo = PAGINA_ENTRAR.format(
        erro=f'<p class="erro" role="alert">{escape(erro)}</p>' if erro else "",
        convite=convite,
        semente_id=(BLOCO_SEMENTE_ID.format(
                        destino=escape(destino, quote=True))
                    if semente_id.configurado() else ""),
        # `json.dumps` e não aspas à mão: o destino entra num literal de
        # JavaScript, e escapar HTML não escapa JavaScript.
        passkey=(BLOCO_PASSKEY.format(destino_js=json.dumps(destino))
                 if com_passkey else ""),
        formulario=(FORMULARIO_TOKEN.format(destino=escape(destino, quote=True))
                    if com_token else ""),
    )
    return Response(content=corpo, status_code=status, media_type="text/html")


def _plantar_sessao(resposta: Response, request: Request, ident: str) -> Response:
    """O cookie de sessão, nas mesmas condições de antes.

    Muda o que vai dentro — identificador opaco em vez do próprio token — e
    não muda nada do que protegia: `HttpOnly` mantém o JavaScript fora,
    `SameSite=Lax` segura CSRF nas rotas de escrita, e `secure` acompanha o
    esquema para não quebrar o desenvolvimento em http.
    """
    resposta.set_cookie(
        COOKIE_SESSAO, ident, httponly=True, samesite="lax",
        secure=request.url.scheme == "https", path="/",
        max_age=60 * 60 * 24 * acesso.DIAS_DE_SESSAO,
    )
    return resposta


@app.post("/entrar", include_in_schema=False)
async def entrar(request: Request):
    # Sem python-multipart de propósito: um campo urlencoded não justifica
    # dependência nova.
    from urllib.parse import parse_qs

    sink = obter_sink(request)
    corpo = parse_qs((await request.body()).decode())
    token = (corpo.get("token") or [""])[0]
    destino = destino_local((corpo.get("destino") or ["/"])[0])
    if not _admin_ok(token):
        return _pagina_entrar(sink, "Token inválido.", destino=destino)
    if not acesso.token_no_formulario(sink):
        # Passkey registrada e `PORTAL_ACESSO_LEGADO` desligado: o formulário
        # não deveria estar na tela, então aceitar o POST seria manter aberta
        # a porta que a tela diz estar fechada.
        return _pagina_entrar(
            sink, "O acesso por token está desligado. Use o passkey.",
            destino=destino,
        )
    return _plantar_sessao(
        Response(status_code=303, headers={"Location": destino}),
        request, acesso.abrir_sessao(sink, "token"),
    )


@app.post("/acesso/desafio", include_in_schema=False)
async def acesso_desafio(request: Request):
    """As opções que o navegador precisa para assinar. Rota pública de
    propósito: é o passo anterior a entrar, e exigir sessão aqui seria exigir
    estar dentro para poder entrar."""
    sink = obter_sink(request)
    if not acesso.ha_passkey(sink):
        raise HTTPException(
            status_code=404,
            detail={"codigo": "sem_passkey",
                    "mensagem": "Nenhum autenticador registrado neste portal."},
        )
    origem = request.headers.get("origin")
    return Response(
        content=acesso.opcoes_de_entrada(sink, origem),
        media_type="application/json",
    )


@app.post("/acesso/passkey", include_in_schema=False)
async def acesso_passkey(request: Request):
    sink = obter_sink(request)
    corpo = await request.json()
    destino = destino_local(corpo.get("destino"))
    try:
        ident = acesso.entrar_com_passkey(
            sink, corpo.get("credencial") or {}, request.headers.get("origin")
        )
    except acesso.ErroAcesso as e:
        raise HTTPException(
            status_code=401,
            detail={"codigo": "passkey_recusada", "mensagem": str(e)},
        ) from e
    return _plantar_sessao(
        JSONResponse({"destino": destino}), request, ident
    )


@app.get("/entrar/semente-id", include_in_schema=False)
async def entrar_semente_id(request: Request):
    sink = obter_sink(request)
    if not semente_id.configurado():
        return _pagina_entrar(
            sink, "O login pelo semente.id não está configurado aqui.")
    destino = destino_local(request.query_params.get("destino", "/"))
    url = semente_id.iniciar_login(sink, destino)
    return Response(status_code=302, headers={"Location": url})


@app.get("/callback/semente-id", include_in_schema=False)
async def callback_semente_id(request: Request):
    sink = obter_sink(request)
    qp = request.query_params
    try:
        _email, destino = semente_id.concluir_login(
            sink, qp.get("state"), qp.get("code"), qp.get("error"))
    except semente_id.ErroSementeId as e:
        return _pagina_entrar(sink, str(e))
    return _plantar_sessao(
        Response(status_code=303, headers={"Location": destino}),
        request, acesso.abrir_sessao(sink, f"semente-id:{_email}"),
    )


@app.get("/sair", include_in_schema=False)
async def sair(request: Request):
    # Sair apaga a linha, não só o cookie. Um cookie descartado pelo navegador
    # deixaria a sessão de pé no servidor, e "sair" passaria a significar
    # "esconder" — que é o contrário do que a palavra promete.
    acesso.fechar_sessao(obter_sink(request), request.cookies.get(COOKIE_SESSAO))
    resposta = Response(status_code=303, headers={"Location": "/"})
    resposta.delete_cookie(COOKIE_SESSAO, path="/")
    return resposta


if RAIZ_WEB.exists():
    app.mount("/admin", StaticFiles(directory=str(RAIZ_WEB), html=True), name="admin")

    # A raiz é a apresentação — onde se vê o dado. A administração fica em
    # /admin. Mesmo build, mesmo serviço; os assets das duas superfícies
    # saem pelo mount /admin.
    @app.get("/", include_in_schema=False)
    async def raiz(request: Request):
        if os.getenv("PORTAL_ADMIN_TOKEN") and not sessao_admin(request):
            # `destino` volta para onde a interface mandou o dono — o /admin
            # rebate para cá quando a sessão não existe.
            return _pagina_entrar(
                obter_sink(request),
                destino=request.query_params.get("destino", "/"),
            )
        pagina = RAIZ_WEB / "apresentacao.html"
        if not pagina.exists():
            pagina = RAIZ_WEB / "index.html"
        return FileResponse(str(pagina))
else:
    @app.get("/", include_in_schema=False)
    async def raiz_sem_front():
        return {
            "portal": "dados B3/CVM",
            "docs": "/docs",
            "aviso": "front não construído — rode `npm run build` em web/",
        }
