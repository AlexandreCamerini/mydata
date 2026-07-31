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
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .. import bootstrap, repositorio as repo
from ..motor import observabilidade, publicacao
from ..motor.ddl import SUFIXO_ORIGEM
from ..sinks import Sink, criar_sink
from . import admin, auth

RAIZ_WEB = Path(__file__).resolve().parents[2] / "web" / "dist"


# --------------------------------------------------------------------------
# Ciclo de vida e dependências
# --------------------------------------------------------------------------
@asynccontextmanager
async def ciclo(app: FastAPI):
    sink = criar_sink()
    if os.getenv("PORTAL_MIGRAR_NO_BOOT", "1") == "1":
        bootstrap.preparar(sink)
    app.state.sink = sink
    yield
    sink.fechar()


app = FastAPI(
    title="Portal de Dados — B3/CVM",
    version="0.1.0",
    description=(
        "Dados oficiais de companhias abertas, com proveniência em toda "
        "resposta. Fonte canônica: CVM Dados Abertos."
    ),
    lifespan=ciclo,
)


def obter_sink(request: Request) -> Sink:
    return request.app.state.sink


def erro(codigo: str, mensagem: str, status: int, detalhe: Any = None) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"erro": {"codigo": codigo, "mensagem": mensagem, "detalhe": detalhe}},
    )


async def exigir_chave(
    request: Request,
    response: Response,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict:
    """Autentica e consome quota. `PORTAL_API_ABERTA=1` libera em dev."""
    sink = obter_sink(request)
    if os.getenv("PORTAL_API_ABERTA") == "1" and not x_api_key:
        return {"prefixo": "aberta", "consumidor": "dev", "escopos": "leitura"}
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
def _proveniencia(sink: Sink, capturas: set[int]) -> dict:
    if not capturas:
        return {}
    marcadores = ",".join("?" for _ in capturas)
    linhas = sink.consultar(
        f"SELECT id, url, sha256, capturado_em, nome_arquivo FROM bronze_captura "
        f"WHERE id IN ({marcadores})",
        list(capturas),
    )
    return {
        linha["id"]: {
            "fonte": linha["url"],
            "arquivo": linha["nome_arquivo"],
            "sha256": linha["sha256"],
            "dt_captura": (
                linha["capturado_em"].isoformat()
                if hasattr(linha["capturado_em"], "isoformat")
                else str(linha["capturado_em"])
            ),
        }
        for linha in linhas
    }


def _decorar(sink: Sink, linhas: list[dict]) -> list[dict]:
    """Anexa proveniência a cada linha e remove colunas internas.

    Numa classe alimentada por mais de uma fonte, dizer "veio da captura X"
    não basta: atributos diferentes da mesma linha podem ter vindo de fontes
    diferentes. As colunas `<atributo>_origem` que a vista resolvida produz
    viram `proveniencia.por_atributo`, em vez de campos soltos no dado.
    """
    prov = _proveniencia(sink, {r["captura_id"] for r in linhas if r.get("captura_id")})
    saida = []
    for linha in linhas:
        captura = linha.pop("captura_id", None)
        linha.pop("fonte_arquivo", None)
        versao_pub = linha.pop("publicado_em_versao", None)
        por_atributo = {
            chave[: -len(SUFIXO_ORIGEM)]: linha.pop(chave)
            for chave in [c for c in linha if c.endswith(SUFIXO_ORIGEM)]
        }
        item = dict(linha)
        item["proveniencia"] = {
            **prov.get(captura, {}),
            "versao_documento": linha.get("versao"),
            "publicacao": versao_pub,
        }
        if por_atributo:
            item["proveniencia"]["por_atributo"] = por_atributo
        saida.append(item)
    return saida


def exigir_vista(sink: Sink, nome: str) -> None:
    """Recusa com mensagem útil quando a vista de gold ainda não existe.

    Vista de gold passou a vir de `cfg_vista`. Um banco migrado e sem
    configuração — deploy novo antes do primeiro seed — não tem gold nenhuma;
    sem esta checagem o consumidor receberia um 500 sobre relação ausente.
    """
    if sink.um(
        "SELECT 1 AS ok FROM information_schema.tables WHERE table_name = ?",
        (nome,),
    ):
        return
    raise HTTPException(
        status_code=503,
        detail={
            "codigo": "gold_indisponivel",
            "mensagem": f"A vista '{nome}' ainda não foi publicada. "
                        f"Rode `python -m app.cli migrar --seed` e uma ingestão.",
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


@app.get("/v1/empresas", tags=["empresas"])
async def listar_empresas(
    request: Request,
    response: Response,
    q: str | None = Query(None, description="Busca por denominação ou CNPJ"),
    setor: str | None = None,
    limite: int = Query(50, ge=1, le=500),
    cursor: str | None = None,
    _chave: dict = Depends(exigir_chave),
) -> Any:
    sink = obter_sink(request)
    exigir_vista(sink, "gold_empresa")
    etag = _etag(sink, f"empresas:{q}:{setor}:{limite}:{cursor}")
    if (r := _talvez_304(request, etag)):
        return r

    onde, params = ["1=1"], []
    if q:
        onde.append("(lower(denom_social) LIKE ? OR lower(denom_comerc) LIKE ? OR cnpj LIKE ?)")
        params += [f"%{q.lower()}%", f"%{q.lower()}%", f"%{q}%"]
    if setor:
        onde.append("lower(setor_atividade) LIKE ?")
        params.append(f"%{setor.lower()}%")
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
    return {"dados": _decorar(sink, linhas), "proximo_cursor": proximo}


@app.get("/v1/empresas/{cd_cvm}", tags=["empresas"])
async def obter_empresa(
    cd_cvm: int, request: Request, response: Response,
    _chave: dict = Depends(exigir_chave),
) -> Any:
    sink = obter_sink(request)
    exigir_vista(sink, "gold_empresa")
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
    return {"dados": _decorar(sink, [linha])[0]}


@app.get("/v1/empresas/{cd_cvm}/demonstracoes", tags=["demonstrações"])
async def demonstracoes(
    cd_cvm: int, request: Request, response: Response,
    tipo: str | None = Query(None, pattern="^(DFP|ITR|dfp|itr)$"),
    grupo: str | None = None,
    de: str | None = Query(None, description="dt_refer mínima (AAAA-MM-DD)"),
    ate: str | None = None,
    consolidado: bool = True,
    conta: str | None = Query(None, description="Prefixo do código da conta"),
    limite: int = Query(200, ge=1, le=2000),
    cursor: str | None = None,
    _chave: dict = Depends(exigir_chave),
) -> Any:
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

    exigir_vista(sink, "gold_demonstracoes")
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
    return {"dados": _decorar(sink, linhas), "proximo_cursor": proximo}


@app.get("/v1/empresas/{cd_cvm}/trimestres", tags=["demonstrações"])
async def trimestres(
    cd_cvm: int, request: Request, response: Response,
    conta: str | None = None,
    exercicio: str | None = None,
    consolidado: bool = True,
    limite: int = Query(200, ge=1, le=2000),
    _chave: dict = Depends(exigir_chave),
) -> Any:
    """ITR com o trimestre isolado já calculado (o acumulado YTD desfeito)."""
    sink = obter_sink(request)
    onde = ["cd_cvm = ?", "consolidado = ?"]
    params: list[Any] = [cd_cvm, consolidado]
    if conta:
        onde.append("cd_conta LIKE ?")
        params.append(f"{conta}%")
    if exercicio:
        onde.append("exercicio = ?")
        params.append(exercicio)
    exigir_vista(sink, "gold_itr_trimestre")
    linhas = sink.consultar(
        f"SELECT * FROM gold_itr_trimestre WHERE {' AND '.join(onde)} "
        f"ORDER BY dt_refer, cd_conta LIMIT ?",
        [*params, limite],
    )
    etag = _etag(sink, f"tri:{cd_cvm}:{conta}:{exercicio}:{consolidado}")
    response.headers["ETag"] = etag
    return {"dados": _decorar(sink, linhas)}


@app.get("/v1/empresas/{cd_cvm}/metricas", tags=["demonstrações"])
async def metricas(
    cd_cvm: int, request: Request, response: Response,
    nomes: str | None = Query(None, description="Lista separada por vírgula"),
    consolidado: bool = True,
    _chave: dict = Depends(exigir_chave),
) -> Any:
    """Campos calculados de nível empresa, a partir do catálogo declarativo."""
    from .metricas import calcular

    sink = obter_sink(request)
    pedidos = [n.strip() for n in (nomes or "").split(",") if n.strip()] or None
    return {"dados": calcular(sink, cd_cvm, consolidado, pedidos)}


@app.get("/v1/meta/datasets", tags=["catálogo"])
async def meta_datasets(request: Request, _chave: dict = Depends(exigir_chave)) -> Any:
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
        saida.append({
            "chave": c["chave"], "nome": c["nome"], "descricao": c["descricao"],
            "identidade": c["chave_identidade"].split(","),
            "resolucao": c["resolucao"],
            "fontes": [d["chave"] for d in repo.datasets_da_classe(sink, c["chave"])],
            "atributos": [
                {"nome": a["nome"], "tipo": a["tipo"], "origem": a["origem"],
                 "unidade": a["unidade"], "descricao": a["descricao"]}
                for a in repo.atributos_de(sink, c["id"])
            ],
        })
    return {"dados": saida}


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


@app.get("/v1/meta/execucoes/{execucao_id}/fases", tags=["catálogo"])
async def meta_fases(
    execucao_id: int, request: Request, _chave: dict = Depends(exigir_chave)
) -> Any:
    """Onde a carga gastou o tempo — não só que ela demorou."""
    return {"dados": observabilidade.linha_do_tempo(obter_sink(request), execucao_id)}


# --------------------------------------------------------------------------
# /admin — plano de controle
# --------------------------------------------------------------------------
app.include_router(admin.router)

if RAIZ_WEB.exists():
    app.mount("/admin", StaticFiles(directory=str(RAIZ_WEB), html=True), name="admin")

    @app.get("/", include_in_schema=False)
    async def raiz():
        return FileResponse(str(RAIZ_WEB / "index.html"))
else:
    @app.get("/", include_in_schema=False)
    async def raiz_sem_front():
        return {
            "portal": "dados B3/CVM",
            "docs": "/docs",
            "aviso": "front não construído — rode `npm run build` em web/",
        }
