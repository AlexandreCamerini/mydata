"""As origens do Bloco A: uma classe por origem, todas somente-leitura.

Nenhuma origem aplica mudança em nada — nem no sistema monitorado, nem no
mydata além das próprias tabelas `console_*` (isso é o coletor, não aqui).
Cada origem lê sua configuração (`CONSOLE_*`) na hora da coleta, nunca no
import do módulo nem no construtor: origem sem variável configurada não é
erro de coleta, é ausência de configuração — registra `nao_configurada` sem
chamar rede.

Timeout e retentativa (§6 da spec): 5 s / 1 retentativa imediata para os
quatro envelopes ADR-23; 10 s / 1 retentativa imediata para o Railway. O
mydata não tem timeout — é chamada de função interna, nunca HTTP para si
mesmo.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

import requests

from ..sinks import Sink

TIMEOUT_ENVELOPE = 5.0
TIMEOUT_RAILWAY = 10.0
RAILWAY_GRAPHQL_URL = "https://backboard.railway.com/graphql/v2"

# A query GraphQL é sempre `query`, nunca `mutation` — a console só lê. Um
# teste (guardião b) prova que o corpo enviado começa com este texto.
_RAILWAY_QUERY = """query($p: String!) {
  deployments(first: 30, input: {projectId: $p}) {
    edges {
      node {
        id
        status
        createdAt
        meta
        service { name }
        environment { name }
      }
    }
  }
}"""


# --------------------------------------------------------------------------
# Transporte HTTP — injetável, para os testes usarem um fake sem rede real.
# Mesmo espírito do `baixar=` injetável que `app/motor/ingestao.py` já usa.
# --------------------------------------------------------------------------
class Transporte(Protocol):
    def get(self, url: str, *, headers: dict | None = None,
            timeout: float = TIMEOUT_ENVELOPE) -> Any: ...

    def post(self, url: str, *, json: Any = None, headers: dict | None = None,
              timeout: float = TIMEOUT_RAILWAY) -> Any: ...


class _TransporteRequests:
    """Implementação real, usada em produção. `requests` é dependência
    principal do projeto (`pyproject.toml`); `httpx` só existe em `dev`."""

    def get(self, url: str, *, headers: dict | None = None,
            timeout: float = TIMEOUT_ENVELOPE):
        return requests.get(url, headers=headers, timeout=timeout)

    def post(self, url: str, *, json: Any = None, headers: dict | None = None,
              timeout: float = TIMEOUT_RAILWAY):
        return requests.post(url, json=json, headers=headers, timeout=timeout)


def transporte_padrao() -> Transporte:
    return _TransporteRequests()


# --------------------------------------------------------------------------
# Resultado de uma coleta — o que o coletor grava.
# --------------------------------------------------------------------------
@dataclass
class MetricaDiaria:
    sistema: str
    metrica: str
    valor: str
    fonte: str


@dataclass
class Deploy:
    sistema: str
    ambiente: str
    deploy_id: str
    commit_sha: str | None
    quando: Any
    status: str | None


@dataclass
class Resultado:
    ok: bool
    duracao_ms: int
    erro: str | None = None
    metricas: list[MetricaDiaria] = field(default_factory=list)
    deploys: list[Deploy] = field(default_factory=list)


def nao_configurada() -> Resultado:
    return Resultado(ok=False, duracao_ms=0, erro="nao_configurada")


def _metricas_do_envelope(sistema: str, envelope: dict, fonte: str) -> list[MetricaDiaria]:
    """`situacao`, `alertas_ativos` e `alertas_criticos` — as três métricas
    que §2 pede derivadas de qualquer envelope ADR-23, com a fonte exata
    (URL/rota) para rastreio."""
    alertas = envelope.get("alertas") or []
    criticos = sum(
        1 for a in alertas if isinstance(a, dict) and a.get("severidade") == "critico"
    )
    return [
        MetricaDiaria(sistema, "situacao", str(envelope.get("situacao", "")), fonte),
        MetricaDiaria(sistema, "alertas_ativos", str(len(alertas)), fonte),
        MetricaDiaria(sistema, "alertas_criticos", str(criticos), fonte),
    ]


def _get_com_retentativa(
    transporte: Transporte, url: str, *, headers: dict | None, timeout: float,
) -> tuple[Any | None, str | None]:
    """Uma tentativa, e se falhar, mais uma imediata (§6). Devolve a
    resposta com `status_code == 200`, ou `None` + descrição do erro."""
    ultimo_erro = None
    for _ in range(2):
        try:
            resp = transporte.get(url, headers=headers, timeout=timeout)
        except Exception as e:  # timeout, conexão recusada, DNS, etc.
            ultimo_erro = f"{type(e).__name__}: {e}"
            continue
        if resp.status_code == 200:
            return resp, None
        ultimo_erro = f"http_{resp.status_code}"
    return None, ultimo_erro


# --------------------------------------------------------------------------
# Envelope ADR-23: MCP, Boris+, portal MCP — mesmo formato, credencial e URL
# diferentes.
# --------------------------------------------------------------------------
class OrigemMCP:
    nome = "mcp"

    def __init__(self, transporte: Transporte | None = None):
        self.transporte = transporte or transporte_padrao()

    def coletar(self, sink: Sink) -> Resultado:
        base = os.getenv("CONSOLE_MCP_URL")
        bearer = os.getenv("CONSOLE_MCP_BEARER")
        if not base or not bearer:
            return nao_configurada()
        url = f"{base.rstrip('/')}/observabilidade"
        inicio = time.monotonic()
        resp, erro = _get_com_retentativa(
            self.transporte, url,
            headers={"Authorization": f"Bearer {bearer}"},
            timeout=TIMEOUT_ENVELOPE,
        )
        duracao_ms = int((time.monotonic() - inicio) * 1000)
        if resp is None:
            return Resultado(ok=False, duracao_ms=duracao_ms, erro=erro)
        envelope = resp.json()
        return Resultado(
            ok=True, duracao_ms=duracao_ms,
            metricas=_metricas_do_envelope("mcp", envelope, url),
        )


class OrigemBoris:
    nome = "boris"

    def __init__(self, transporte: Transporte | None = None):
        self.transporte = transporte or transporte_padrao()

    def coletar(self, sink: Sink) -> Resultado:
        base = os.getenv("CONSOLE_BORIS_URL")
        chave = os.getenv("CONSOLE_BORIS_OBS_CHAVE")
        if not base or not chave:
            return nao_configurada()
        url = f"{base.rstrip('/')}/observabilidade"
        inicio = time.monotonic()
        resp, erro = _get_com_retentativa(
            self.transporte, url,
            headers={"X-Observabilidade-Chave": chave},
            timeout=TIMEOUT_ENVELOPE,
        )
        duracao_ms = int((time.monotonic() - inicio) * 1000)
        if resp is None:
            return Resultado(ok=False, duracao_ms=duracao_ms, erro=erro)
        envelope = resp.json()
        return Resultado(
            ok=True, duracao_ms=duracao_ms,
            metricas=_metricas_do_envelope("boris", envelope, url),
        )


class OrigemPortal:
    nome = "portal"

    def __init__(self, transporte: Transporte | None = None):
        self.transporte = transporte or transporte_padrao()

    def coletar(self, sink: Sink) -> Resultado:
        base = os.getenv("CONSOLE_PORTAL_URL")
        if not base:
            return nao_configurada()
        # NOTA (decisão fora da spec): a lista de variáveis do bloco A não
        # inclui uma credencial de bearer para o portal — só a URL. O portal
        # real valida bearer via `/userinfo` do semente.id (spec §1); sem uma
        # `CONSOLE_PORTAL_*` de credencial, esta origem chama sem
        # `Authorization` e deixa o portal responder o que responder (inclusive
        # 401, registrado como falha comum). Ver relatório de entrega, item
        # "decisões fora da spec".
        url = f"{base.rstrip('/')}/observabilidade"
        inicio = time.monotonic()
        resp, erro = _get_com_retentativa(
            self.transporte, url, headers=None, timeout=TIMEOUT_ENVELOPE,
        )
        duracao_ms = int((time.monotonic() - inicio) * 1000)
        if resp is None:
            return Resultado(ok=False, duracao_ms=duracao_ms, erro=erro)
        envelope = resp.json()
        return Resultado(
            ok=True, duracao_ms=duracao_ms,
            metricas=_metricas_do_envelope("portal", envelope, url),
        )


# --------------------------------------------------------------------------
# mydata — função interna, nunca HTTP para si mesmo (§6: "o que a console
# nunca faz" não proíbe isto, mas chamar a própria rota por rede seria
# absurdo dentro do mesmo processo).
# --------------------------------------------------------------------------
class _AppFalso:
    """Só o suficiente para `admin.obter_sink`/`get_observabilidade` lerem
    `request.app.state.sink` sem precisar de uma requisição HTTP real."""

    def __init__(self, sink: Sink):
        class _Estado:
            pass

        self.state = _Estado()
        self.state.sink = sink


class _RequestFalso:
    def __init__(self, sink: Sink):
        self.app = _AppFalso(sink)


class OrigemMydata:
    nome = "mydata"

    def coletar(self, sink: Sink) -> Resultado:
        import asyncio

        from ..api import admin

        inicio = time.monotonic()
        try:
            resposta = asyncio.run(admin.get_observabilidade(_RequestFalso(sink)))
        except Exception as e:
            duracao_ms = int((time.monotonic() - inicio) * 1000)
            return Resultado(ok=False, duracao_ms=duracao_ms,
                              erro=f"{type(e).__name__}: {e}")
        duracao_ms = int((time.monotonic() - inicio) * 1000)
        envelope = resposta["dados"]
        return Resultado(
            ok=True, duracao_ms=duracao_ms,
            metricas=_metricas_do_envelope(
                "mydata", envelope, "/admin/api/observabilidade",
            ),
        )


# --------------------------------------------------------------------------
# Railway — deploys via GraphQL público. Um projeto por entrada de
# `CONSOLE_RAILWAY_PROJETOS` (`nome=projectId,nome2=projectId2`); uma linha
# de `console_coleta` só, cobrindo todos os projetos configurados.
# --------------------------------------------------------------------------
def _projetos_railway() -> list[tuple[str, str]]:
    bruto = os.getenv("CONSOLE_RAILWAY_PROJETOS", "")
    projetos = []
    for par in bruto.split(","):
        par = par.strip()
        if not par or "=" not in par:
            continue
        nome, project_id = par.split("=", 1)
        if nome.strip() and project_id.strip():
            projetos.append((nome.strip(), project_id.strip()))
    return projetos


class OrigemRailway:
    nome = "railway"

    def __init__(self, transporte: Transporte | None = None):
        self.transporte = transporte or transporte_padrao()

    def coletar(self, sink: Sink) -> Resultado:
        token = os.getenv("CONSOLE_RAILWAY_TOKEN")
        projetos = _projetos_railway()
        if not token or not projetos:
            return nao_configurada()

        inicio = time.monotonic()
        deploys: list[Deploy] = []
        falhas: list[str] = []
        for nome, project_id in projetos:
            resp, erro = self._chamar(token, project_id)
            if resp is None:
                falhas.append(f"{nome}: {erro}")
                continue
            corpo = resp.json()
            edges = (
                corpo.get("data", {})
                .get("deployments", {})
                .get("edges", [])
            )
            for edge in edges:
                node = edge.get("node", {})
                meta = node.get("meta") or {}
                commit_sha = meta.get("commitHash") if isinstance(meta, dict) else None
                deploys.append(Deploy(
                    sistema=nome,
                    ambiente=(node.get("environment") or {}).get("name"),
                    deploy_id=node.get("id"),
                    commit_sha=commit_sha,
                    quando=node.get("createdAt"),
                    status=node.get("status"),
                ))
        duracao_ms = int((time.monotonic() - inicio) * 1000)
        if falhas:
            return Resultado(ok=False, duracao_ms=duracao_ms,
                              erro="; ".join(falhas), deploys=deploys)
        return Resultado(ok=True, duracao_ms=duracao_ms, deploys=deploys)

    def _chamar(self, token: str, project_id: str) -> tuple[Any | None, str | None]:
        corpo = {"query": _RAILWAY_QUERY, "variables": {"p": project_id}}
        headers = {"Authorization": f"Bearer {token}"}
        ultimo_erro = None
        for _ in range(2):
            try:
                resp = self.transporte.post(
                    RAILWAY_GRAPHQL_URL, json=corpo, headers=headers,
                    timeout=TIMEOUT_RAILWAY,
                )
            except Exception as e:
                ultimo_erro = f"{type(e).__name__}: {e}"
                continue
            if resp.status_code == 200:
                return resp, None
            ultimo_erro = f"http_{resp.status_code}"
        return None, ultimo_erro


def origens_padrao() -> list:
    """As 5 origens do Bloco A, com o transporte real. É o que o agendador
    interno (`coletor.py`) usa em produção; os testes injetam suas próprias
    instâncias com um transporte fake."""
    return [
        OrigemMCP(), OrigemMydata(), OrigemBoris(), OrigemPortal(),
        OrigemRailway(),
    ]
