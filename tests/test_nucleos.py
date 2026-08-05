"""Black-Scholes-Merton e a inversão, contra valores de referência.

O caso canônico do livro-texto — S=100, K=100, T=1, r=5%, sigma=20% — tem
valores tabelados que não saíram deste código: call 10,4506, put 5,5735,
delta 0,63683, gama 0,018762, vega 37,524 e theta anual −6,414. É o único
jeito de o teste não ser o código conferindo a si mesmo.

Duas convenções desta casa aparecem aqui e são deliberadas: vega vem por
ponto de volatilidade (1%) e theta por dia útil, porque é como se lê numa
mesa. A referência é dividida no teste, à vista, para a conversão ficar
explícita em vez de escondida.
"""
from __future__ import annotations

import math

import pytest

from app.motor import nucleos as nuc

S, K, T, R, SIGMA = 100.0, 100.0, 1.0, 0.05, 0.20


# --------------------------------------------------------------------------
# Preço
# --------------------------------------------------------------------------
def test_call_e_put_batem_com_a_referencia():
    assert nuc.bs_preco("call", S, K, T, R, SIGMA) == pytest.approx(10.4506, abs=1e-4)
    assert nuc.bs_preco("put", S, K, T, R, SIGMA) == pytest.approx(5.5735, abs=1e-4)


def test_paridade_call_put():
    """C − P = S − K·e^(−rT). Vale para qualquer parâmetro, e pega erro de
    sinal que os dois preços sozinhos não pegariam."""
    c = nuc.bs_preco("call", 87.0, 95.0, 0.4, 0.11, 0.33)
    p = nuc.bs_preco("put", 87.0, 95.0, 0.4, 0.11, 0.33)
    assert c - p == pytest.approx(87.0 - 95.0 * math.exp(-0.11 * 0.4), abs=1e-9)


def test_o_codigo_de_mercado_da_b3_escolhe_o_tipo():
    """`070` é compra e `080` é venda: a função aceita o vocabulário da fonte
    sem o motor ter de traduzir antes."""
    assert nuc.bs_preco("070", S, K, T, R, SIGMA) == pytest.approx(
        nuc.bs_preco("call", S, K, T, R, SIGMA))
    assert nuc.bs_preco("080", S, K, T, R, SIGMA) == pytest.approx(
        nuc.bs_preco("put", S, K, T, R, SIGMA))


# --------------------------------------------------------------------------
# Gregas
# --------------------------------------------------------------------------
def test_delta_bate_com_a_referencia():
    assert nuc.bs_delta("call", S, K, T, R, SIGMA) == pytest.approx(0.63683, abs=1e-5)
    # Delta de put = delta de call − 1.
    assert nuc.bs_delta("put", S, K, T, R, SIGMA) == pytest.approx(-0.36317, abs=1e-5)


def test_gamma_bate_e_independe_do_tipo():
    assert nuc.bs_gamma("call", S, K, T, R, SIGMA) == pytest.approx(0.018762, abs=1e-6)
    assert nuc.bs_gamma("put", S, K, T, R, SIGMA) == pytest.approx(0.018762, abs=1e-6)


def test_vega_sai_por_ponto_de_volatilidade():
    assert nuc.bs_vega("call", S, K, T, R, SIGMA) == pytest.approx(37.524 / 100, abs=1e-5)


def test_theta_sai_por_dia_util():
    assert nuc.bs_theta("call", S, K, T, R, SIGMA) == pytest.approx(
        -6.4140 / 252, abs=1e-6)


def test_rho_sai_por_ponto_percentual():
    assert nuc.bs_rho("call", S, K, T, R, SIGMA) == pytest.approx(53.232 / 100, abs=1e-4)


def test_vega_confere_contra_a_derivada_numerica():
    """Independe da fórmula fechada: se vega estivesse errada, a diferença
    finita denunciaria."""
    h = 1e-5
    derivada = (nuc.bs_preco("call", S, K, T, R, SIGMA + h)
                - nuc.bs_preco("call", S, K, T, R, SIGMA - h)) / (2 * h)
    assert nuc.bs_vega("call", S, K, T, R, SIGMA) == pytest.approx(
        derivada / 100, rel=1e-5)


def test_delta_confere_contra_a_derivada_numerica():
    h = 1e-5
    derivada = (nuc.bs_preco("call", S + h, K, T, R, SIGMA)
                - nuc.bs_preco("call", S - h, K, T, R, SIGMA)) / (2 * h)
    assert nuc.bs_delta("call", S, K, T, R, SIGMA) == pytest.approx(derivada, rel=1e-6)


# --------------------------------------------------------------------------
# A inversão
# --------------------------------------------------------------------------
def test_iv_recupera_a_volatilidade_que_gerou_o_preco():
    for sigma in (0.08, 0.20, 0.45, 1.20):
        premio = nuc.bs_preco("call", S, K, T, R, sigma)
        assert nuc.bs_iv("call", premio, S, K, T, R) == pytest.approx(sigma, abs=1e-6)


def test_iv_funciona_fora_do_dinheiro_nos_dois_lados():
    """É onde Newton diverge: o vega tende a zero e o passo explode. A
    bisseção não tem essa ponta ruim, e é por isso que ela está lá."""
    for strike in (60.0, 150.0):
        for tipo in ("call", "put"):
            premio = nuc.bs_preco(tipo, S, strike, 0.25, R, 0.35)
            assert nuc.bs_iv(tipo, premio, S, strike, 0.25, R) == pytest.approx(
                0.35, abs=1e-5)


def test_premio_fora_do_alcance_do_modelo_devolve_nulo():
    """Prêmio abaixo do intrínseco descontado ou acima do próprio ativo não
    tem sigma que resolva. Devolver o extremo da busca encheria a base de IV
    de 500% com cara de dado — e isso acontece de verdade, porque o
    fechamento de contrato ilíquido é o último negócio, que pode ser de
    horas antes e não bater com o spot do fim do dia.
    """
    assert nuc.bs_iv("call", 0.01, S, K, T, R) is None      # barato demais
    assert nuc.bs_iv("call", 99.0, S, K, T, R) is None       # caro demais
    assert nuc.bs_iv("call", -1.0, S, K, T, R) is None
    assert nuc.bs_iv("call", 5.0, S, K, 0.0, R) is None      # já venceu


def test_taxa_ausente_vira_zero_em_vez_de_erro():
    """A série de CDI pode não ter carga ainda. Sem taxa o preço é o do
    modelo com r=0 — enviesado e explicável, em vez de nulo sem motivo."""
    assert nuc.bs_preco("call", S, K, T, None, SIGMA) == pytest.approx(
        nuc.bs_preco("call", S, K, T, 0.0, SIGMA))


# --------------------------------------------------------------------------
# Prazo
# --------------------------------------------------------------------------
def test_prazo_conta_dia_util_sobre_252():
    """De 31/07/2026 a 21/08/2026 há 15 dias de semana."""
    assert nuc.prazo_anos("2026-07-31", "2026-08-21") == pytest.approx(15 / 252)


def test_prazo_ignora_a_sentinela_de_papel_sem_vencimento():
    """A B3 grava 9999-12-31 em ação. Sem este corte, o prazo viria como oito
    mil anos e a grega sairia numericamente absurda em vez de nula."""
    assert nuc.prazo_anos("2026-07-31", "9999-12-31") is None


def test_prazo_de_vencimento_no_mesmo_dia_e_zero():
    assert nuc.prazo_anos("2026-07-31", "2026-07-31") == 0.0


def test_prazo_com_data_invalida_nao_explode():
    assert nuc.prazo_anos("2026-07-31", None) is None
    assert nuc.prazo_anos("nao e data", "2026-08-21") is None


# --------------------------------------------------------------------------
# O registro
# --------------------------------------------------------------------------
def test_registro_expoe_exatamente_o_que_o_catalogo_pode_chamar():
    assert set(nuc.NUCLEOS) == {
        "prazo_anos", "bs_preco", "bs_delta", "bs_gamma", "bs_vega",
        "bs_theta", "bs_rho", "bs_iv",
    }
