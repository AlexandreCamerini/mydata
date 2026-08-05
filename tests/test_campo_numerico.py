"""A terceira classe de campo calculado, e por que ela existe.

`escalar` e `janela` são SQL. Volatilidade implícita não é: a inversão de
Black-Scholes é iterativa, sem forma fechada. `numerico` resolve um nome
contra o registro de `motor/nucleos.py` e passa colunas como argumentos — o
motor continua sem avaliar texto livre, que num campo editável pela interface
seria RCE com formulário.
"""
from __future__ import annotations

import pytest

from app import repositorio as repo
from app import seed_cvm
from app.motor import calculados as calc
from app.motor import ingestao
from app.repositorio import ErroConfiguracao
from tests.test_cotahist import ARQUIVO


# --------------------------------------------------------------------------
# A forma da chamada
# --------------------------------------------------------------------------
def test_reconhece_funcao_e_argumentos():
    funcao, args = calc.compilar_chamada("bs_iv(tp_mercado, preco, 0.5)", "x")
    assert funcao == "bs_iv"
    assert args == ["tp_mercado", "preco", "0.5"]


def test_funcao_fora_do_registro_e_recusada():
    with pytest.raises(ErroConfiguracao, match="desconhecida"):
        calc.compilar_chamada("os_system(a)", "x")


@pytest.mark.parametrize("expressao", [
    "bs_iv(__import__('os').system('ls'))",
    "bs_iv(a.b)",
    "bs_iv(f(g))",
    "bs_iv(a); DROP TABLE fato_negociacao",
    "bs_iv(a)[0]",
    "preco_fechamento * 2",
])
def test_expressao_que_nao_e_chamada_simples_e_recusada(expressao):
    """A superfície é estreita de propósito: nome de função do registro, e
    argumentos que só podem ser coluna, número ou texto entre aspas."""
    with pytest.raises(ErroConfiguracao):
        calc.compilar_chamada(expressao, "x")


# --------------------------------------------------------------------------
# A execução
# --------------------------------------------------------------------------
@pytest.fixture()
def carregado(sink):
    seed_cvm.aplicar(sink)
    sink.executar(
        "INSERT INTO fato_indicador (captura_id, fonte_arquivo, origem_dataset,"
        " indicador, dt_referencia, valor, unidade) VALUES (0,'manual','bcb_cdi',"
        " 'cdi', '2026-07-30', 10.40, '% a.a.')"
    )
    ingestao.executar(
        sink, "b3_cotahist", "2026-07-31",
        baixar=lambda url, cabecalhos=None: ARQUIVO,
    )
    return sink


def linha(sink, codneg):
    return sink.um("SELECT * FROM fato_negociacao WHERE codneg = ?", (codneg,))


def test_a_onda_seguinte_enxerga_o_que_a_anterior_gravou(carregado):
    """A inversão é insumo das gregas. Numa passada só, o delta leria a
    volatilidade da execução anterior — nula, na primeira carga. As ondas por
    `ordem` são o que torna a dependência declarável.
    """
    call = linha(carregado, "ABCBH255")
    assert call["prazo_anos"] is not None          # onda 10
    assert call["volatilidade_implicita"] is not None   # onda 11, usa o prazo
    assert call["delta"] is not None               # onda 12, usa a inversão


def test_a_inversao_reproduz_o_premio_negociado(carregado):
    """O teste que fecha o ciclo: se o preço teórico com a IV extraída bate
    com o prêmio, a inversão e o modelo estão consistentes entre si."""
    call = linha(carregado, "ABCBH255")
    assert call["preco_teorico"] == pytest.approx(call["preco_fechamento"], abs=1e-3)


def test_o_spot_do_ativo_objeto_entra_no_calculo(carregado):
    call = linha(carregado, "ABCBH255")
    abcb4 = linha(carregado, "ABCB4")
    assert call["preco_objeto"] == pytest.approx(abcb4["preco_fechamento"])


def test_a_taxa_livre_de_risco_vem_do_cdi_em_fracao(carregado):
    """O BCB publica 10,40 querendo dizer 10,4% ao ano; o modelo quer 0,104.
    Entrar em porcento faria a taxa valer 1.040% e a IV sair irreconhecível."""
    assert linha(carregado, "ABCBH255")["taxa_livre_risco"] == pytest.approx(0.104)


def test_papel_a_vista_nao_ganha_grega(carregado):
    """Ação não tem strike nem vencimento: o prazo é nulo pela sentinela, e
    tudo que depende dele sai nulo em vez de sair errado."""
    petr = linha(carregado, "PETR4")
    assert petr["prazo_anos"] is None
    assert petr["volatilidade_implicita"] is None
    assert petr["delta"] is None


def test_sem_carga_de_cdi_a_taxa_fica_nula_e_o_calculo_segue(sink):
    """A classe de indicador pode não ter carga. Isso não pode derrubar a
    ingestão do pregão — o modelo roda com r=0, enviesado e explicável."""
    seed_cvm.aplicar(sink)
    ingestao.executar(
        sink, "b3_cotahist", "2026-07-31",
        baixar=lambda url, cabecalhos=None: ARQUIVO,
    )
    call = linha(sink, "ABCBH255")
    assert call["taxa_livre_risco"] is None
    assert call["volatilidade_implicita"] is not None


# --------------------------------------------------------------------------
# A moldura da janela
# --------------------------------------------------------------------------
def test_moldura_entra_no_over(carregado):
    campo = carregado.um(
        "SELECT moldura FROM cfg_campo_calculado WHERE nome = 'hv21'"
    )
    assert campo["moldura"] == "ROWS BETWEEN 20 PRECEDING AND CURRENT ROW"


def test_moldura_fora_do_formato_e_recusada(carregado):
    """O frame é concatenado no SQL, então a forma é fixada. Texto livre ali
    seria injeção por campo de formulário."""
    ds = repo.dataset_vigente(carregado, "b3_cotahist")
    carregado.executar(
        "UPDATE cfg_campo_calculado SET moldura = ? "
        "WHERE dataset_id = ? AND nome = 'hv21'",
        ("ROWS BETWEEN 20 PRECEDING AND CURRENT ROW) -- e o resto", ds["id"]),
    )
    with pytest.raises(ErroConfiguracao, match="moldura"):
        calc.aplicar(carregado, ds, repo.calculados_do(carregado, ds["id"]))


def test_volatilidade_historica_precisa_de_historico(carregado):
    """Com um pregão só não há retorno anterior, então HV é nula. É o
    comportamento certo: uma volatilidade calculada sobre uma observação
    seria um número sem significado ocupando o lugar de «ainda não sei»."""
    assert linha(carregado, "PETR4")["log_retorno"] is None
    assert linha(carregado, "PETR4")["hv21"] is None
