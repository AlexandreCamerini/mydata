"""O coletor do Bloco A: agendador interno + gravação em `console_*`.

`coletar_tudo` executa cada origem de forma independente — a falha de uma
nunca impede a gravação das demais (§6 da spec, "o que a console nunca
faz" não inclui isto, mas é a mesma disciplina de degradação por origem que
sustenta o "indisponível desde <hora>"). Uma linha em `console_coleta` por
tentativa, sucesso ou falha; upsert em `console_metrica_diaria` e
`console_deploy` só quando a origem respondeu.

O agendador (`iniciar`/`parar`) só existe quando `CONSOLE_COLETOR=1` — sem a
variável, o mydata continua exatamente igual (critério de aceite do dono).
Intervalos por origem, herdados de §6: 5 min para os quatro envelopes ADR-23,
15 min para o Railway.
"""
from __future__ import annotations

import asyncio
import contextlib
import os
from collections.abc import Callable
from datetime import datetime, timezone

from ..sinks import Sink
from . import origens as origens_mod

INTERVALO_ENVELOPES_S = 5 * 60
INTERVALO_RAILWAY_S = 15 * 60


def _agora_utc() -> datetime:
    return datetime.now(timezone.utc)


def coletar_tudo(
    sink: Sink,
    origens: list,
    agora: Callable[[], datetime] = _agora_utc,
) -> None:
    """Roda cada origem, grava a tentativa e — se deu certo — as métricas ou
    os deploys que ela derivou. Uma origem que estoura exceção não impede as
    demais: é capturada aqui, nunca propagada."""
    for origem in origens:
        try:
            resultado = origem.coletar(sink)
        except Exception as e:  # a origem já trata os próprios erros; isto
            # é o cinto extra — um bug numa origem não pode derrubar as outras
            # quatro, nem o processo `mydata` inteiro (válvula de extração,
            # §1: um bug aqui derrubar `/v1` é gatilho para a opção C).
            resultado = origens_mod.Resultado(
                ok=False, duracao_ms=0, erro=f"{type(e).__name__}: {e}",
            )

        momento = agora()
        _gravar_coleta(sink, origem.nome, momento, resultado)
        if not resultado.ok:
            continue

        dia = momento.date().isoformat()
        for metrica in resultado.metricas:
            _upsert_metrica_diaria(sink, dia, metrica)
        for deploy in resultado.deploys:
            _upsert_deploy(sink, deploy)


def _gravar_coleta(sink: Sink, origem: str, quando: datetime, resultado) -> None:
    id_ = sink.proximo_id("console_coleta")
    sink.executar(
        "INSERT INTO console_coleta (id, origem, quando, ok, duracao_ms, erro) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (id_, origem, quando, resultado.ok, resultado.duracao_ms, resultado.erro),
    )


def _upsert_metrica_diaria(sink: Sink, dia: str, metrica) -> None:
    sink.executar(
        "INSERT INTO console_metrica_diaria (dia, sistema, metrica, valor, fonte) "
        "VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT (dia, sistema, metrica) DO UPDATE SET "
        "valor = excluded.valor, fonte = excluded.fonte",
        (dia, metrica.sistema, metrica.metrica, metrica.valor, metrica.fonte),
    )


def _upsert_deploy(sink: Sink, deploy) -> None:
    if not deploy.deploy_id:
        return  # sem identidade, não há o que fazer upsert
    sink.executar(
        "INSERT INTO console_deploy "
        "(sistema, ambiente, deploy_id, commit_sha, quando, status) "
        "VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT (deploy_id) DO UPDATE SET "
        "sistema = excluded.sistema, ambiente = excluded.ambiente, "
        "commit_sha = excluded.commit_sha, quando = excluded.quando, "
        "status = excluded.status",
        (deploy.sistema, deploy.ambiente, deploy.deploy_id, deploy.commit_sha,
         deploy.quando, deploy.status),
    )


# --------------------------------------------------------------------------
# Agendador interno — uma asyncio.Task por cadência, só com CONSOLE_COLETOR=1.
# --------------------------------------------------------------------------
async def _laco(sink: Sink, origens: list, intervalo_s: int) -> None:
    while True:
        try:
            await asyncio.to_thread(coletar_tudo, sink, origens, _agora_utc)
        except Exception:
            # O laço nunca morre por causa de uma coleta ruim — a próxima
            # tentativa é em `intervalo_s`, e cada origem já registra a
            # própria falha em `console_coleta`.
            pass
        await asyncio.sleep(intervalo_s)


def ligado() -> bool:
    return os.getenv("CONSOLE_COLETOR") == "1"


def iniciar(app) -> None:
    """Chamado no lifespan (`app/api/main.py`). Sem `CONSOLE_COLETOR=1`, não
    faz nada — o mydata sobe exatamente como sobe hoje."""
    if not ligado():
        app.state.console_tarefas = []
        return
    sink = app.state.sink
    envelopes = [
        origens_mod.OrigemMCP(), origens_mod.OrigemMydata(),
        origens_mod.OrigemBoris(), origens_mod.OrigemPortal(),
    ]
    railway = [origens_mod.OrigemRailway()]
    app.state.console_tarefas = [
        asyncio.create_task(_laco(sink, envelopes, INTERVALO_ENVELOPES_S)),
        asyncio.create_task(_laco(sink, railway, INTERVALO_RAILWAY_S)),
    ]


async def parar(app) -> None:
    """Cancelamento limpo no shutdown — nunca deixa a tarefa órfã."""
    tarefas = getattr(app.state, "console_tarefas", None) or []
    for tarefa in tarefas:
        tarefa.cancel()
    for tarefa in tarefas:
        with contextlib.suppress(asyncio.CancelledError):
            await tarefa
