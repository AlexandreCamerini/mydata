"""Registro posicional: o terceiro formato que o motor aprendeu a ler.

CSV e JSON dizem onde um campo termina — um separador, uma chave. O COTAHIST
da B3 não diz: são 245 bytes por linha, cada campo numa faixa de posições, e
três tipos de registro compartilhando o mesmo arquivo. Nada disso é da B3;
layout posicional é comum em dado público brasileiro, e o motor passou a
tratá-lo como formato, não como fonte.

As linhas abaixo são recortadas do arquivo real de 31/07/2026 — não foram
reconstruídas a partir da tabela do PDF de layout. É a diferença entre testar
o que a B3 publica e testar o que eu entendi que ela publica.
"""
from __future__ import annotations

import pytest

from app.motor import parsing
from app.motor.parsing import ErroParse

CABECALHO = (
    "00COTAHIST.2026BOVESPA 20260731" + " " * 214
)
PETR4 = (
    "012026073102PETR4       010PETROBRAS   PN  ATZ N2   R$  00000000043000"
    "0000000043550000000004286000000000433600000000043420000000004341000000"
    "0004342452770000000000249973000000001084118619000000000000000099991231"
    "00000010000000000000BRPETRACNPR6229"
)
CALL_ABCB = (
    "012026073178ABCBH255    070ABCB  FM    PN      N2000R$  00000000000570"
    "0000000000570000000000057000000000005700000000000570000000000010000000"
    "0000000000010000000000000010000000000000000570000000000002440020260821"
    "00000010000000000000BRABCBACNPR4150"
)
PUT_AAPL = (
    "012026073182AAPLV862    080AAPLE       DRN       000R$  00000000008310"
    "0000000008310000000000831000000000083100000000008310000000000000000000"
    "0000000000010000000000000031000000000000025761000000000008620020261016"
    "00000010000000000000BRAAPLBDR004159"
)
TRAILER = (
    "99COTAHIST.2026BOVESPA 2026073100000013821" + " " * 203
)

LINHAS = [CABECALHO, PETR4, CALL_ABCB, PUT_AAPL, TRAILER]
ARQUIVO = "\r\n".join(LINHAS).encode("latin-1")


def test_fixture_tem_o_registro_de_245_bytes_do_arquivo_real():
    """Trava o recorte. Um literal quebrado em várias linhas de código já
    deslocou campo aqui uma vez, e o sintoma foi um strike dez vezes menor —
    número plausível, teste verde noutro lugar."""
    assert [len(linha) for linha in LINHAS] == [245] * 5


def col(origem, destino, tipo="texto", formato=None, obrigatoria=False):
    return {
        "nome_origem": origem, "nome_destino": destino, "tipo": tipo,
        "formato": formato, "obrigatoria": obrigatoria, "ordem": 0,
    }


COLUNAS = [
    col("DATA@3-10", "dt_pregao", "data", obrigatoria=True),
    col("CODBDI@11-12", "cod_bdi", obrigatoria=True),
    col("CODNEG@13-24", "codneg", obrigatoria=True),
    col("TPMERC@25-27", "tp_mercado"),
    col("PREULT@109-121", "preco_fechamento", "numero", "implicito:2"),
    col("PREEXE@189-201", "preco_exercicio", "numero", "implicito:2"),
    col("DATVEN@203-210", "dt_vencimento", "data"),
    col("CODISI@231-242", "isin"),
]


def ler(**kw):
    return list(parsing.ler_larguras(ARQUIVO, COLUNAS, "latin-1", **kw))


# --------------------------------------------------------------------------
# O recorte
# --------------------------------------------------------------------------
def test_filtro_linha_separa_o_dado_do_cabecalho_e_do_trailer():
    """Sem filtro, o cabeçalho vira uma linha de dado com tudo deslocado.

    O registro `00` tem 245 bytes como qualquer outro, então o leitor não tem
    como notar sozinho que aquilo não é cotação: `COTAHIST.202` cairia na
    faixa do código de negociação e passaria.
    """
    assert len(ler(filtro_linha=r"^01")) == 3
    assert len(ler()) == 5


def test_recorta_cada_campo_na_faixa_declarada():
    petr, call, put = ler(filtro_linha=r"^01")

    assert petr["codneg"] == "PETR4"
    assert petr["dt_pregao"] == "2026-07-31"
    assert petr["cod_bdi"] == "02"
    assert petr["tp_mercado"] == "010"
    assert petr["isin"] == "BRPETRACNPR6"

    assert call["codneg"] == "ABCBH255"
    assert call["tp_mercado"] == "070"
    assert put["codneg"] == "AAPLV862"
    assert put["tp_mercado"] == "080"


def test_decimal_implicito_divide_pela_escala_declarada():
    """`(11)V99` grava 0000000004342 e quer dizer 43,42.

    Layout posicional não tem onde pôr a vírgula. Se a escala não fosse
    declarada, o fechamento da PETR4 entraria como R$ 4.342,00 — cem vezes o
    valor, e plausível o bastante para ninguém notar.
    """
    petr, call, _ = ler(filtro_linha=r"^01")
    assert petr["preco_fechamento"] == pytest.approx(43.42)
    assert call["preco_fechamento"] == pytest.approx(0.57)
    assert call["preco_exercicio"] == pytest.approx(24.40)


def test_coluna_sombra_txt_guarda_o_bruto():
    """A string original continua disponível, como no CSV: é ela que permite
    conferir uma conversão suspeita sem voltar ao bronze."""
    petr, *_ = ler(filtro_linha=r"^01")
    assert petr["preco_fechamento_txt"] == "0000000004342"


def test_data_sentinela_do_vencimento_nao_e_inventada():
    """Ação tem DATVEN = 99991231. O leitor devolve o que a B3 gravou.

    Trocar por nulo aqui seria o motor decidindo que aquilo *significa* «sem
    vencimento» — juízo de domínio, que pertence à vista de gold. O parse
    converte representação, não sentido.
    """
    petr, call, _ = ler(filtro_linha=r"^01")
    assert petr["dt_vencimento"] == "9999-12-31"
    assert call["dt_vencimento"] == "2026-08-21"


# --------------------------------------------------------------------------
# O que o leitor recusa
# --------------------------------------------------------------------------
def test_coluna_sem_faixa_e_erro_de_configuracao():
    colunas = [*COLUNAS, col("PREMED", "preco_medio", "numero")]
    with pytest.raises(ErroParse, match="faixa em nome_origem"):
        list(parsing.ler_larguras(ARQUIVO, colunas, "latin-1", filtro_linha=r"^01"))


def test_linha_mais_curta_que_o_mapeamento_falha_alto():
    """Truncamento silencioso preencheria as últimas colunas com vazio, e uma
    carga inteira entraria com ISIN nulo sem nada reclamar."""
    curto = b"012026073102PETR4       010PETROBRAS\r\n"
    with pytest.raises(ErroParse, match="declara campo até a posição"):
        list(parsing.ler_larguras(curto, COLUNAS, "latin-1", filtro_linha=r"^01"))


def test_faixa_invertida_e_erro():
    with pytest.raises(ErroParse, match="faixa inválida"):
        parsing.faixa_de("CAMPO@201-189")


def test_faixa_de_ignora_nome_sem_arroba():
    assert parsing.faixa_de("PREULT") is None
    assert parsing.faixa_de("PREULT@109-121") == (109, 121)
