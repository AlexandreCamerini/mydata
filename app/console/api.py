"""Rotas do Bloco A: leitura do que o coletor grava, mais o disparo manual.

Mesma disciplina do resto do admin (`app/api/admin.py`): sessão do dono
exigida no router inteiro (`exigir_admin`, reaproveitado por import — sem
duplicar a lógica de cookie/cabeçalho), resposta sempre `{"dados": ...}`.

Única rota de escrita: `POST /coletar`. Ela dispara `coletor.coletar_tudo`
contra o próprio banco do mydata — nunca contra um serviço externo (a
escrita externa não existe neste pacote; ver guardião em
`tests/test_console.py`).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query, Request

from ..sinks import Sink
from ..api.admin import exigir_admin
from . import coletor, latencia
from . import origens as origens_mod

router = APIRouter(
    prefix="/admin/api/console",
    tags=["console"],
    dependencies=[Depends(exigir_admin)],
)

# As 5 origens do Bloco A — mesma ordem de `origens_mod.origens_padrao()`,
# repetida aqui só como constante de leitura (a tela de `/situacao` precisa
# da lista mesmo quando uma origem nunca gravou nenhuma linha ainda).
ORIGENS_CONHECIDAS = ("mcp", "mydata", "boris", "portal", "railway")


def _sink(request: Request) -> Sink:
    return request.app.state.sink


def _ultima_coleta(sink: Sink, origem: str) -> dict | None:
    return sink.um(
        "SELECT quando, ok, duracao_ms, erro FROM console_coleta "
        "WHERE origem = ? ORDER BY quando DESC, id DESC LIMIT 1",
        (origem,),
    )


def _indisponivel_desde(sink: Sink, origem: str) -> Any:
    """A hora da primeira falha sem sucesso posterior (§1/§3a) — ou `None`
    quando a última tentativa foi `ok=true`, ou quando a origem nunca
    coletou nada ainda."""
    linhas = sink.consultar(
        "SELECT quando, ok FROM console_coleta WHERE origem = ? "
        "ORDER BY quando DESC, id DESC LIMIT 2000",
        (origem,),
    )
    if not linhas or linhas[0]["ok"]:
        return None
    desde = linhas[0]["quando"]
    for linha in linhas[1:]:
        if linha["ok"]:
            break
        desde = linha["quando"]
    return desde


@router.get("/situacao")
@latencia.medir
async def get_situacao(request: Request) -> Any:
    """Por origem: última coleta, `ok`, e `indisponivel_desde` — o que
    sustenta o rótulo "indisponível desde <hora>" sem afetar as demais
    quatro origens (§1, §9)."""
    sink = _sink(request)
    dados = []
    for origem in ORIGENS_CONHECIDAS:
        ultima = _ultima_coleta(sink, origem)
        dados.append({
            "origem": origem,
            "ultima_coleta": ultima["quando"] if ultima else None,
            "ok": ultima["ok"] if ultima else None,
            "duracao_ms": ultima["duracao_ms"] if ultima else None,
            "erro": ultima["erro"] if ultima else None,
            "indisponivel_desde": _indisponivel_desde(sink, origem),
        })
    return {"dados": dados}


@router.get("/coletas")
@latencia.medir
async def get_coletas(
    request: Request,
    origem: str | None = None,
    limite: int = Query(50, ge=1, le=500),
) -> Any:
    sink = _sink(request)
    if origem:
        linhas = sink.consultar(
            "SELECT id, origem, quando, ok, duracao_ms, erro FROM console_coleta "
            f"WHERE origem = ? ORDER BY quando DESC, id DESC LIMIT {limite}",
            (origem,),
        )
    else:
        linhas = sink.consultar(
            "SELECT id, origem, quando, ok, duracao_ms, erro FROM console_coleta "
            f"ORDER BY quando DESC, id DESC LIMIT {limite}",
        )
    return {"dados": linhas}


@router.get("/metricas")
@latencia.medir
async def get_metricas(
    request: Request,
    dias: int = Query(7, ge=1, le=400),
) -> Any:
    """`console_metrica_diaria` dos últimos N dias (retenção-alvo: 400, §2 —
    PREMISSA de desenho, a confirmar com o dono em §10.4)."""
    sink = _sink(request)
    limite_dia = (datetime.now(timezone.utc).date() - timedelta(days=dias)).isoformat()
    linhas = sink.consultar(
        "SELECT dia, sistema, metrica, valor, fonte FROM console_metrica_diaria "
        "WHERE dia >= ? ORDER BY dia DESC, sistema, metrica",
        (limite_dia,),
    )
    return {"dados": linhas}


@router.get("/deploys")
@latencia.medir
async def get_deploys(request: Request, sistema: str | None = None) -> Any:
    sink = _sink(request)
    if sistema:
        linhas = sink.consultar(
            "SELECT sistema, ambiente, deploy_id, commit_sha, quando, status "
            "FROM console_deploy WHERE sistema = ? ORDER BY quando DESC",
            (sistema,),
        )
    else:
        linhas = sink.consultar(
            "SELECT sistema, ambiente, deploy_id, commit_sha, quando, status "
            "FROM console_deploy ORDER BY quando DESC",
        )
    return {"dados": linhas}


@router.get("/latencia")
@latencia.medir
async def get_latencia(request: Request) -> Any:
    """p50/p95/contagem das próprias rotas de `/admin/api/console/*` — a
    válvula objetiva de extração para C (§1, §9) depende de existir isto."""
    return {"dados": latencia.resumo()}


@router.post("/coletar")
@latencia.medir
async def post_coletar(request: Request) -> Any:
    """Dispara `coletor.coletar_tudo` uma vez, contra o próprio banco do
    mydata — nunca contra serviço externo (a escrita é sempre local)."""
    sink = _sink(request)
    await asyncio.to_thread(coletor.coletar_tudo, sink, origens_mod.origens_padrao())
    return {"dados": {"disparado": True}}
