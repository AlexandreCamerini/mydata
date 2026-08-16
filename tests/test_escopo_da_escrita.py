"""Campo de janela: ler tudo, escrever só o que mudou.

A leitura tem de ser completa — a partição cruza janelas de carga, e recortá-la
daria janela truncada: a volatilidade de 21 pregões passaria a olhar só o que a
carga trouxe. A escrita é outra pergunta, e a resposta depende do campo.

`is_latest` **retroage**: quando chega uma reapresentação, é a linha *antiga*
que precisa virar falsa. `hv21` não retroage: o pregão de hoje não altera a
volatilidade de ontem.

Isso não dá para inferir da expressão, então é declarado. O padrão é retroagir,
porque é o comportamento que já valia — ganhar velocidade exige dizer, e errar
a declaração é caro demais para ser o silêncio.
"""
from __future__ import annotations

import zipfile

import pytest

from app import seed_fontes
from app.motor import ingestao
from tests.conftest import csv_conta, linha, zip_cvm
from tests.test_cotahist import (
    ABCB4, CABECALHO, CALL_ABCB, PETR4, TRAILER, zip_cotahist,
)


# --------------------------------------------------------------------------
# O que o conserto NÃO pode quebrar
# --------------------------------------------------------------------------
def test_reapresentacao_continua_rebaixando_a_versao_anterior(sink):
    """O caso que proíbe escopar a escrita de `is_latest`.

    A versão 1 chega numa carga, a versão 2 em outra. Se a segunda carga só
    escrevesse as próprias linhas, a linha da versão 1 continuaria com
    `is_latest` verdadeiro — duas versões marcadas como última, e a soma em
    gold contando a conta duas vezes. Sem erro, sem alerta, sem sintoma.
    """
    seed_fontes.aplicar(sink)

    def carga(versao, valor):
        arquivo = csv_conta([
            linha(versao=versao, vl=valor, cd_conta="1", ds_conta="Ativo Total"),
        ])
        return zip_cvm({f"dfp_cia_aberta_BPA_con_2023.csv": arquivo})

    ingestao.executar(sink, "cvm_dfp", "2023",
                      baixar=lambda url, cabecalhos=None: carga(1, "1000,00"))
    ingestao.executar(sink, "cvm_dfp", "2023",
                      baixar=lambda url, cabecalhos=None: carga(2, "2000,00"))

    linhas = sink.consultar(
        "SELECT versao, is_latest FROM fato_conta ORDER BY versao"
    )
    assert [(l["versao"], l["is_latest"]) for l in linhas] == [(1, False), (2, True)]


def test_is_latest_declara_que_retroage(sink):
    seed_fontes.aplicar(sink)
    campo = sink.um(
        "SELECT retroage FROM cfg_campo_calculado WHERE nome = 'is_latest' "
        "ORDER BY id DESC LIMIT 1"
    )
    assert campo["retroage"] is True


# --------------------------------------------------------------------------
# O que o conserto precisa fazer
# --------------------------------------------------------------------------
ARQ_D1 = zip_cotahist([CABECALHO, PETR4, ABCB4, CALL_ABCB, TRAILER])


def _com_fechamento(codneg, valor):
    """A mesma linha do pregão seguinte, com outro preço de fechamento.

    O fechamento ocupa as posições 109–121, com duas casas implícitas.
    """
    base = {"PETR4": PETR4, "ABCB4": ABCB4}[codneg]
    campo = f"{int(round(valor * 100)):013d}"
    trocada = base[:2] + "20260803" + base[10:108] + campo + base[121:]
    assert len(trocada) == 245
    return trocada


ARQ_D2 = zip_cotahist([
    CABECALHO,
    _com_fechamento("PETR4", 44.42),
    _com_fechamento("ABCB4", 25.00),
    TRAILER,
])


@pytest.fixture()
def dois_pregoes(sink):
    seed_fontes.aplicar(sink)
    ingestao.executar(sink, "b3_cotahist", "2026-07-31",
                      baixar=lambda url, cabecalhos=None: ARQ_D1)
    ingestao.executar(sink, "b3_cotahist", "2026-08-03",
                      baixar=lambda url, cabecalhos=None: ARQ_D2)
    return sink


def test_hv_e_log_retorno_declaram_que_nao_retroagem(dois_pregoes):
    campos = {
        r["nome"]: r["retroage"]
        for r in dois_pregoes.consultar(
            "SELECT nome, retroage FROM cfg_campo_calculado "
            "WHERE nome IN ('log_retorno','hv21','hv63')"
        )
    }
    assert campos == {"log_retorno": False, "hv21": False, "hv63": False}


def test_a_leitura_continua_completa_apesar_do_recorte_na_escrita(dois_pregoes):
    """O ponto delicado: a linha do segundo pregão precisa enxergar o primeiro.

    Se o recorte tivesse ido para a subconsulta em vez da condição do UPDATE,
    o `lag` não teria com que comparar e o retorno sairia nulo — silenciosa e
    plausivelmente, porque o primeiro pregão de qualquer carga é nulo mesmo.
    """
    petr = dois_pregoes.um(
        "SELECT log_retorno FROM fato_negociacao "
        "WHERE codneg = 'PETR4' AND dt_pregao = '2026-08-03'"
    )
    import math

    assert petr["log_retorno"] == pytest.approx(math.log(44.42 / 43.42))


def test_o_pregao_anterior_nao_e_reescrito(dois_pregoes):
    """Primeiro pregão não tem anterior: o retorno dele é nulo e continua
    nulo depois da segunda carga."""
    petr = dois_pregoes.um(
        "SELECT log_retorno FROM fato_negociacao "
        "WHERE codneg = 'PETR4' AND dt_pregao = '2026-07-31'"
    )
    assert petr["log_retorno"] is None


def test_recomputar_reproduz_o_mesmo_estado(dois_pregoes):
    """A garantia que o recorte não pode custar: dropar e refazer do bronze
    tem de dar exatamente o mesmo resultado. Se o escopo da escrita deixasse
    linha por atualizar, é aqui que apareceria."""
    from app.motor import verificacao

    antes = verificacao.impressao_digital(dois_pregoes)
    for janela in ("2026-07-31", "2026-08-03"):
        ingestao.recomputar(dois_pregoes, "b3_cotahist", janela)
    assert verificacao.impressao_digital(dois_pregoes) == antes


def test_o_update_recortado_toca_menos_linhas(dois_pregoes, monkeypatch):
    """A razão de existir do conserto, medida em vez de suposta.

    Sem o recorte, o UPDATE de `log_retorno` reescreve as quatro linhas da
    tabela a cada carga; com ele, só as duas da carga corrente. Num ano de
    pregões a diferença é entre reescrever milhares de linhas e reescrever
    milhões.
    """
    from app import repositorio as repo
    from app.motor import calculados as calc

    ds = repo.dataset_vigente(dois_pregoes, "b3_cotahist")
    campos = [c for c in repo.calculados_do(dois_pregoes, ds["id"])
              if c["nome"] == "log_retorno"]
    capturas = [
        c["id"] for c in ingestao.capturas_da_janela(
            dois_pregoes, "b3_cotahist", "2026-08-03"
        )
    ]

    executados: list[tuple[str, list]] = []
    original = dois_pregoes.executar

    def espiar(sql, params=()):
        executados.append((sql, list(params)))
        return original(sql, params)

    monkeypatch.setattr(dois_pregoes, "executar", espiar)
    calc.aplicar(dois_pregoes, ds, campos, capturas=capturas)

    sql, params = executados[-1]
    assert "captura_id IN" in sql, "o recorte não chegou ao UPDATE"
    assert params == capturas


# --------------------------------------------------------------------------
# Carregar histórico — a ordem em que o recorte deixa de valer
# --------------------------------------------------------------------------
def test_carregar_um_pregao_anterior_reescreve_o_posterior(sink):
    """Fazer histórico é carregar para trás, e aí o recorte não vale.

    Ao ingerir 31/07 *depois* de 03/08, a linha de 03/08 ganha um antecessor
    e o retorno dela deixa de ser nulo. Se a escrita continuasse escopada à
    carga, ela ficaria nula para sempre — e nula é o valor plausível de quem
    é o primeiro pregão da série, então ninguém notaria.
    """
    import math

    seed_fontes.aplicar(sink)
    ingestao.executar(sink, "b3_cotahist", "2026-08-03",
                      baixar=lambda url, cabecalhos=None: ARQ_D2)
    posterior = sink.um(
        "SELECT log_retorno FROM fato_negociacao "
        "WHERE codneg = 'PETR4' AND dt_pregao = '2026-08-03'"
    )
    assert posterior["log_retorno"] is None, "sem anterior, nulo"

    # Agora o pregão de trás.
    ingestao.executar(sink, "b3_cotahist", "2026-07-31",
                      baixar=lambda url, cabecalhos=None: ARQ_D1)

    posterior = sink.um(
        "SELECT log_retorno FROM fato_negociacao "
        "WHERE codneg = 'PETR4' AND dt_pregao = '2026-08-03'"
    )
    assert posterior["log_retorno"] == pytest.approx(math.log(44.42 / 43.42))


def test_a_carga_no_fim_e_reconhecida_como_tal(dois_pregoes):
    from app import repositorio as repo
    from app.motor import calculados as calc

    ds = repo.dataset_vigente(dois_pregoes, "b3_cotahist")
    del ds
    do_fim = [c["id"] for c in ingestao.capturas_da_janela(
        dois_pregoes, "b3_cotahist", "2026-08-03")]
    do_comeco = [c["id"] for c in ingestao.capturas_da_janela(
        dois_pregoes, "b3_cotahist", "2026-07-31")]

    assert calc._carga_no_fim(
        dois_pregoes, "fato_negociacao", ["dt_pregao"], do_fim) is True
    assert calc._carga_no_fim(
        dois_pregoes, "fato_negociacao", ["dt_pregao"], do_comeco) is False


# --------------------------------------------------------------------------
# A janela só vale cheia
# --------------------------------------------------------------------------
def test_hv_e_nula_enquanto_a_janela_nao_enche(dois_pregoes):
    """Dois pregões dão um retorno; `hv21` pede vinte e um.

    Sem esta guarda a moldura entregava o que houvesse, e o terceiro pregão da
    série já trazia uma «volatilidade de 21 dias» calculada sobre dois
    retornos — mesma coluna, mesmo nome, mesma cara de uma calculada sobre
    vinte e um. É a descrição do atributo que o código não cumpria.
    """
    valores = dois_pregoes.consultar(
        "SELECT dt_pregao, hv21, hv63 FROM fato_negociacao "
        "WHERE codneg = 'PETR4' AND tp_mercado = '010' ORDER BY dt_pregao"
    )
    assert [v["hv21"] for v in valores] == [None, None]
    assert [v["hv63"] for v in valores] == [None, None]


def test_a_moldura_e_o_count_usam_a_mesma_janela(sink):
    """`{OVER}` é substituído em todas as ocorrências: se o `count` recebesse
    moldura diferente da do `stddev`, a guarda contaria outra coisa."""
    seed_fontes.aplicar(sink)
    campo = sink.um(
        "SELECT expressao, moldura FROM cfg_campo_calculado WHERE nome = 'hv21' "
        "ORDER BY id DESC LIMIT 1"
    )
    assert campo["expressao"].count("{OVER}") == 2
    assert campo["moldura"] == "ROWS BETWEEN 20 PRECEDING AND CURRENT ROW"
