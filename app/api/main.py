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
from ..motor import contrato, correlacao, ingestao, observabilidade, publicacao
from ..motor.ddl import SUFIXO_ORIGEM
from ..sinks import Sink, criar_sink
from . import admin, auth
from . import metricas as metricas_cat

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


def _admin_ok(valor: str | None) -> bool:
    """O valor confere com PORTAL_ADMIN_TOKEN? Sem a variável, não há sessão
    de admin — o modo aberto de dev é PORTAL_API_ABERTA, não isto."""
    import hmac

    esperado = os.getenv("PORTAL_ADMIN_TOKEN")
    if not esperado or not valor:
        return False
    return hmac.compare_digest(valor, esperado)


def sessao_admin(request: Request) -> bool:
    """Sessão do dono: cookie HttpOnly criado em /entrar, ou o header que o
    admin já usa. O navegador nunca vê chave de API — a sessão é a credencial,
    e o servidor responde por ela perante /v1."""
    return _admin_ok(request.cookies.get(COOKIE_SESSAO)) or _admin_ok(
        request.headers.get("X-Admin-Token")
    )


COOKIE_SESSAO = "portal_sessao"


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
            # Sem estes dois, o `sha256` acima é um número que o consumidor
            # teria de aceitar no fio do bigode: a URL de origem é endereço
            # mutável e não reproduz a captura. Com eles, ele baixa e confere.
            "captura": linha["id"],
            "arquivo_em": f"/v1/capturas/{linha['id']}/arquivo",
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


@app.get("/v1/empresas", tags=["empresas"])
async def listar_empresas(
    request: Request,
    response: Response,
    q: str | None = Query(None, description="Busca por denominação, CNPJ ou ticker"),
    setor: str | None = None,
    segmento: str | None = Query(
        None, description="Segmento de listagem na B3 (NM, N1, N2, MB...)"),
    listada_b3: bool | None = Query(
        None, description="Só companhias com registro de negociação na B3"),
    com_balanco: bool | None = Query(
        None, description="Só companhias que publicaram DFP ou ITR"),
    limite: int = Query(50, ge=1, le=500),
    cursor: str | None = None,
    _chave: dict = Depends(exigir_chave),
) -> Any:
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
    return {"dados": _decorar(sink, linhas), "total": total,
            "proximo_cursor": proximo}


@app.get("/v1/empresas/{cd_cvm}", tags=["empresas"])
async def obter_empresa(
    cd_cvm: int, request: Request, response: Response,
    _chave: dict = Depends(exigir_chave),
) -> Any:
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
    exigir_vista(sink, "gold_itr_trimestre", _chave)
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


@app.get("/v1/cotacoes/{ticker}", tags=["negociação"])
async def cotacoes(
    ticker: str, request: Request, response: Response,
    de: str | None = Query(None, description="Data inicial, AAAA-MM-DD"),
    ate: str | None = Query(None, description="Data final, AAAA-MM-DD"),
    limite: int = Query(200, ge=1, le=2000),
    cursor: str | None = None,
    _chave: dict = Depends(exigir_chave),
) -> Any:
    """Pregão do lote padrão de um papel, com volatilidade histórica."""
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
    return {"dados": _decorar(sink, linhas), "proximo_cursor": proximo}


@app.get("/v1/opcoes/{ticker}", tags=["negociação"])
async def opcoes(
    ticker: str, request: Request, response: Response,
    vencimento: str | None = Query(None, description="Vencimento, AAAA-MM-DD"),
    pregao: str | None = Query(
        None, description="Data do pregão. Omitida, vale o último publicado."
    ),
    tipo: str | None = Query(None, description="CALL ou PUT"),
    limite: int = Query(500, ge=1, le=2000),
    cursor: str | None = None,
    _chave: dict = Depends(exigir_chave),
) -> Any:
    """Cadeia de opções de um ativo-objeto, com implícita e gregas.

    Sem `pregao`, responde o último pregão publicado *daquele papel* — e não
    o último da base. Um papel que parou de negociar devolveria vazio se o
    corte fosse global, o que pareceria ausência de dado em vez de ausência
    de negócio.
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
    return {"dados": _decorar(sink, linhas), "proximo_cursor": proximo}


@app.get("/v1/opcoes/{ticker}/vencimentos", tags=["negociação"])
async def vencimentos(
    ticker: str, request: Request,
    pregao: str | None = None,
    _chave: dict = Depends(exigir_chave),
) -> Any:
    """Vencimentos disponíveis, para o consumidor não varrer a cadeia inteira
    só para descobrir o que existe."""
    sink = obter_sink(request)
    exigir_vista(sink, "gold_opcoes", _chave)
    onde = ["ticker_objeto = ?"]
    params: list[Any] = [ticker.upper()]
    if pregao:
        onde.append("dt_pregao = ?")
        params.append(pregao)
    return {"dados": sink.consultar(
        f"SELECT dt_vencimento, count(*) AS contratos, "
        f"       min(strike) AS menor_strike, max(strike) AS maior_strike "
        f"FROM gold_opcoes WHERE {' AND '.join(onde)} "
        f"GROUP BY dt_vencimento ORDER BY dt_vencimento",
        params,
    )}


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
    cd_cvm: int, request: Request, _chave: dict = Depends(exigir_chave)
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
    request: Request, captura_id: int, chave: dict = Depends(exigir_chave)
) -> Any:
    """O que se sabe sobre um arquivo capturado, sem baixá-lo."""
    sink = obter_sink(request)
    return {"dados": _sobre_captura(_captura_ou_404(sink, captura_id, chave))}


@app.get("/v1/capturas/{captura_id}/arquivo", tags=["proveniência"])
async def arquivo_da_captura(
    request: Request,
    captura_id: int,
    response: Response,
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
    chave_correlacao: str,
    campos: str | None = Query(
        None, description="colunas da classe de destino, separadas por vírgula"
    ),
    onde: str | None = Query(
        None, description="filtros sobre o destino: campo:valor,campo:valor"
    ),
    limite: int = Query(correlacao.LIMITE_PADRAO, ge=1, le=correlacao.LIMITE_MAXIMO),
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
        saida["dados"] = _decorar(sink, saida["dados"])
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
    dataset: str | None = None,
    status: str | None = Query(
        None, description="Filtra por status, separados por vírgula "
                          "(ex.: falha,bloqueada)"),
    limite: int = Query(50, ge=1, le=200),
    _chave: dict = Depends(exigir_chave),
) -> Any:
    """O que rodou e o que quebrou. É o que o painel do operador lê para
    responder 'o que falhou' sem abrir o banco."""
    sink = obter_sink(request)
    lista = [s.strip() for s in (status or "").split(",") if s.strip()]
    return {"dados": repo.execucoes(sink, limite, dataset, lista or None)}


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
 form {{ background: #fff; border: 1px solid #d6d3d1; border-radius: 6px;
        padding: 2rem; max-width: 22rem; width: 100%; }}
 label {{ display: block; font-weight: 600; margin-bottom: .5rem; }}
 input {{ width: 100%; box-sizing: border-box; padding: .5rem; font-size: 1rem;
         border: 1px solid #d6d3d1; border-radius: 4px; margin-bottom: 1rem; }}
 button {{ background: #1c1917; color: #fff; border: 0; border-radius: 4px;
          padding: .5rem 1rem; font-size: 1rem; cursor: pointer; }}
 p.erro {{ color: #b91c1c; }}
</style></head>
<body>
<form method="post" action="/entrar">
  <h1 style="font-size:1.1rem">MyData</h1>
  <p style="font-size:.9rem;color:#57534e">A apresentação é privada.
  Informe o token de administração para entrar.</p>
  {erro}
  <label for="token">Token</label>
  <input id="token" name="token" type="password" autocomplete="current-password" required>
  <button type="submit">Entrar</button>
</form>
</body></html>"""


def _pagina_entrar(erro: str = "", status: int = 401) -> Response:
    corpo = PAGINA_ENTRAR.format(
        erro=f'<p class="erro" role="alert">{erro}</p>' if erro else ""
    )
    return Response(content=corpo, status_code=status, media_type="text/html")


@app.post("/entrar", include_in_schema=False)
async def entrar(request: Request):
    # Sem python-multipart de propósito: um campo urlencoded não justifica
    # dependência nova.
    from urllib.parse import parse_qs

    corpo = parse_qs((await request.body()).decode())
    token = (corpo.get("token") or [""])[0]
    if not _admin_ok(token):
        return _pagina_entrar("Token inválido.")
    resposta = Response(status_code=303, headers={"Location": "/"})
    resposta.set_cookie(
        COOKIE_SESSAO, token, httponly=True, samesite="lax",
        secure=request.url.scheme == "https", path="/",
        max_age=60 * 60 * 24 * 30,
    )
    return resposta


@app.get("/sair", include_in_schema=False)
async def sair():
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
            return _pagina_entrar()
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
