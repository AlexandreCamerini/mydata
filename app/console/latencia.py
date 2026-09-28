"""p50/p95 das próprias rotas de `/admin/api/console/*`, num anel em memória.

§9 exige essa métrica exposta: é a válvula objetiva de extração para C (§1)
— sem medir o próprio p95, não há como o console saber quando se tornou
grande demais para viver dentro do processo `mydata`. Decorator, não
middleware: fica inteiro dentro de `app/console/`, sem tocar em
`app/api/main.py` além do já previsto (include_router + lifespan).

Em memória, de propósito — como o resto do Bloco A não pede persistência
disto, e um anel pequeno (500 amostras) já basta para o p95 recente.
"""
from __future__ import annotations

import functools
import time
from collections import deque

_JANELA = 500
_amostras_ms: deque[float] = deque(maxlen=_JANELA)


def medir(fn):
    """Decorator para rota async: cronometra a chamada e guarda no anel."""

    @functools.wraps(fn)
    async def envolvida(*args, **kwargs):
        inicio = time.monotonic()
        try:
            return await fn(*args, **kwargs)
        finally:
            _amostras_ms.append((time.monotonic() - inicio) * 1000)

    return envolvida


def _percentil(dados_ordenados: list[float], p: float) -> float:
    if len(dados_ordenados) == 1:
        return dados_ordenados[0]
    k = (len(dados_ordenados) - 1) * p
    piso, teto = int(k), min(int(k) + 1, len(dados_ordenados) - 1)
    if piso == teto:
        return dados_ordenados[piso]
    return dados_ordenados[piso] + (dados_ordenados[teto] - dados_ordenados[piso]) * (k - piso)


def resumo() -> dict:
    dados = sorted(_amostras_ms)
    if not dados:
        return {"p50_ms": None, "p95_ms": None, "contagem": 0}
    return {
        "p50_ms": round(_percentil(dados, 0.50), 2),
        "p95_ms": round(_percentil(dados, 0.95), 2),
        "contagem": len(dados),
    }


def _resetar_para_teste() -> None:
    """Só para a suíte — evita amostra de um teste vazar pro próximo."""
    _amostras_ms.clear()
