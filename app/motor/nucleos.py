"""Funções numéricas puras que uma expressão SQL não consegue exprimir.

O catálogo de campos calculados é SQL: `UPDATE ... SET campo = <expressão>`.
Isso cobre escala, razão e função de janela — mas não cobre método iterativo.
Volatilidade implícita é a inversão de Black-Scholes-Merton: não existe forma
fechada, só busca até o preço teórico bater com o prêmio observado.

Daí este registro. É *matemática*, não fonte: nada aqui sabe o que é B3, e um
campo declarado no catálogo escolhe a função pelo nome, como escolheria
`upper()` numa expressão. O motor não interpreta código do usuário — só
resolve um nome contra este dicionário e passa colunas como argumentos.

Convenções, todas explícitas porque mudam o número:

- **Prazo em dias úteis sobre 252**, que é a convenção da B3. Feriado não é
  excluído: exigiria um calendário, que é outra fonte de dado. O erro é de
  um dia útil por feriado no intervalo, e some no prazo longo. `prazo_anos`
  fica exposto como coluna justamente para o efeito ser auditável.
- **Sem dividendos.** O modelo é Black-Scholes-Merton simples. Opção sobre
  papel que paga provento no intervalo terá IV levemente enviesada.
- **Taxa contínua.** A taxa livre de risco entra como fração ao ano
  (0,105 para 10,5%), composta continuamente.
"""
from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Any, Callable

DIAS_UTEIS_ANO = 252


class ErroNucleo(ValueError):
    """Argumento que a função numérica não aceita."""


# --------------------------------------------------------------------------
# Base
# --------------------------------------------------------------------------
def _fdp(x: float) -> float:
    """Densidade da normal padrão."""
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def _fda(x: float) -> float:
    """Acumulada da normal padrão, via erf — sem dependência externa."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _data(valor: Any) -> date | None:
    if valor is None:
        return None
    if isinstance(valor, date):
        return valor
    texto = str(valor).strip()[:10]
    try:
        return date.fromisoformat(texto)
    except ValueError:
        return None


def _num(valor: Any) -> float | None:
    if valor is None:
        return None
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


def prazo_anos(dt_inicio: Any, dt_fim: Any) -> float | None:
    """Dias úteis entre duas datas, em anos de 252.

    Só conta dia de semana. A sentinela 9999-12-31 que a B3 grava em papel
    sem vencimento devolve None em vez de um prazo de oito mil anos.
    """
    inicio, fim = _data(dt_inicio), _data(dt_fim)
    if inicio is None or fim is None or fim.year > 2400:
        return None
    if fim <= inicio:
        return 0.0
    dias = 0
    # Vencimento no mesmo dia vale zero; a partir daí conta dia útil.
    passo = inicio
    while passo < fim:
        passo += timedelta(days=1)
        if passo.weekday() < 5:
            dias += 1
    return dias / DIAS_UTEIS_ANO


def _d1_d2(s: float, k: float, t: float, r: float, sigma: float) -> tuple[float, float]:
    raiz = sigma * math.sqrt(t)
    d1 = (math.log(s / k) + (r + 0.5 * sigma * sigma) * t) / raiz
    return d1, d1 - raiz


def _valido(s, k, t, sigma) -> bool:
    return None not in (s, k, t, sigma) and s > 0 and k > 0 and t > 0 and sigma > 0


def _ehcall(tipo: Any) -> bool:
    """`070` é opção de compra, `080` é de venda — mas o campo também aceita
    'call'/'put', para a função não depender do vocabulário de uma fonte."""
    t = str(tipo).strip().lower()
    return t in ("070", "70", "c", "call", "compra")


# --------------------------------------------------------------------------
# Black-Scholes-Merton
# --------------------------------------------------------------------------
def bs_preco(tipo, s, k, t, r, sigma) -> float | None:
    s, k, t, r, sigma = (_num(v) for v in (s, k, t, r, sigma))
    r = 0.0 if r is None else r
    if not _valido(s, k, t, sigma):
        return None
    d1, d2 = _d1_d2(s, k, t, r, sigma)
    desconto = math.exp(-r * t)
    if _ehcall(tipo):
        return s * _fda(d1) - k * desconto * _fda(d2)
    return k * desconto * _fda(-d2) - s * _fda(-d1)


def bs_delta(tipo, s, k, t, r, sigma) -> float | None:
    s, k, t, r, sigma = (_num(v) for v in (s, k, t, r, sigma))
    r = 0.0 if r is None else r
    if not _valido(s, k, t, sigma):
        return None
    d1, _ = _d1_d2(s, k, t, r, sigma)
    return _fda(d1) if _ehcall(tipo) else _fda(d1) - 1.0


def bs_gamma(tipo, s, k, t, r, sigma) -> float | None:
    """Igual para compra e venda; `tipo` entra só para a assinatura ser a
    mesma de todas as gregas e o catálogo declarar sempre os mesmos campos."""
    s, k, t, r, sigma = (_num(v) for v in (s, k, t, r, sigma))
    r = 0.0 if r is None else r
    if not _valido(s, k, t, sigma):
        return None
    d1, _ = _d1_d2(s, k, t, r, sigma)
    return _fdp(d1) / (s * sigma * math.sqrt(t))


def bs_vega(tipo, s, k, t, r, sigma) -> float | None:
    """Por ponto de volatilidade (1%), não por unidade — é como a mesa lê."""
    s, k, t, r, sigma = (_num(v) for v in (s, k, t, r, sigma))
    r = 0.0 if r is None else r
    if not _valido(s, k, t, sigma):
        return None
    d1, _ = _d1_d2(s, k, t, r, sigma)
    return s * _fdp(d1) * math.sqrt(t) / 100.0


def bs_theta(tipo, s, k, t, r, sigma) -> float | None:
    """Por dia útil, não por ano: é a perda de valor de um pregão."""
    s, k, t, r, sigma = (_num(v) for v in (s, k, t, r, sigma))
    r = 0.0 if r is None else r
    if not _valido(s, k, t, sigma):
        return None
    d1, d2 = _d1_d2(s, k, t, r, sigma)
    comum = -(s * _fdp(d1) * sigma) / (2.0 * math.sqrt(t))
    desconto = r * k * math.exp(-r * t)
    anual = comum - desconto * _fda(d2) if _ehcall(tipo) else comum + desconto * _fda(-d2)
    return anual / DIAS_UTEIS_ANO


def bs_rho(tipo, s, k, t, r, sigma) -> float | None:
    """Por ponto percentual de taxa."""
    s, k, t, r, sigma = (_num(v) for v in (s, k, t, r, sigma))
    r = 0.0 if r is None else r
    if not _valido(s, k, t, sigma):
        return None
    _, d2 = _d1_d2(s, k, t, r, sigma)
    desconto = k * t * math.exp(-r * t)
    valor = desconto * _fda(d2) if _ehcall(tipo) else -desconto * _fda(-d2)
    return valor / 100.0


# --------------------------------------------------------------------------
# Inversão: a razão de este módulo existir
# --------------------------------------------------------------------------
def bs_iv(tipo, premio, s, k, t, r) -> float | None:
    """Volatilidade implícita: o sigma que faz o preço teórico virar o prêmio.

    Bisseção, não Newton. Newton converge mais rápido no meio da curva e
    diverge nas pontas — em opção muito dentro ou muito fora do dinheiro o
    vega tende a zero e o passo explode. Bisseção sobre [1e-4, 5,0] custa
    cinquenta avaliações no pior caso, o que é irrelevante aqui, e não tem
    ponta ruim.

    Devolve None, e não um número, quando o prêmio está fora do que o modelo
    consegue produzir — prêmio abaixo do valor intrínseco descontado, ou
    acima do preço do próprio ativo. Isso acontece de verdade: prêmio de
    fechamento de contrato ilíquido é o último negócio, que pode ser de
    horas antes e não bater com o spot do fim do dia. Devolver o extremo da
    busca nesses casos encheria a base de IV de 500% com cara de dado.
    """
    premio, s, k, t, r = (_num(v) for v in (premio, s, k, t, r))
    r = 0.0 if r is None else r
    if None in (premio, s, k, t) or premio <= 0 or s <= 0 or k <= 0 or t <= 0:
        return None

    baixo, alto = 1e-4, 5.0
    preco_baixo = bs_preco(tipo, s, k, t, r, baixo)
    preco_alto = bs_preco(tipo, s, k, t, r, alto)
    if preco_baixo is None or preco_alto is None:
        return None
    # Fora do intervalo que o modelo alcança não há sigma que resolva.
    if premio <= preco_baixo or premio >= preco_alto:
        return None

    for _ in range(100):
        meio = 0.5 * (baixo + alto)
        preco = bs_preco(tipo, s, k, t, r, meio)
        if preco is None:
            return None
        if abs(preco - premio) < 1e-8 or (alto - baixo) < 1e-8:
            return meio
        if preco < premio:
            baixo = meio
        else:
            alto = meio
    return 0.5 * (baixo + alto)


# --------------------------------------------------------------------------
# O registro
# --------------------------------------------------------------------------
# Um campo do catálogo escolhe a função pelo nome. Nome que não está aqui é
# erro de configuração, não texto executado: o motor nunca avalia expressão
# livre em Python.
NUCLEOS: dict[str, Callable[..., Any]] = {
    "prazo_anos": prazo_anos,
    "bs_preco": bs_preco,
    "bs_delta": bs_delta,
    "bs_gamma": bs_gamma,
    "bs_vega": bs_vega,
    "bs_theta": bs_theta,
    "bs_rho": bs_rho,
    "bs_iv": bs_iv,
}
