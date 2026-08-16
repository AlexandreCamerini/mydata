"""O COTAHIST da B3 como configuração, e o que o arquivo real ensinou.

Três coisas aqui não vieram do PDF de layout — vieram de contar linhas do
pregão de 31/07/2026:

1. `PRAZOT` faz parte da identidade. Sem ele, quinze contratos a termo do
   mesmo papel com prazos diferentes colidem e o upsert guarda um só.
2. O `CODISI` de um registro de opção é o ISIN do *ativo-objeto*. Casar contra
   o registro à vista do mesmo pregão resolve 11.320 de 11.321 opções, sem
   arquivo auxiliar e sem inferir pelo prefixo do código.
3. A opção órfã existe e é normal: o papel dela não negociou naquele dia. Por
   isso a regra alerta com tolerância, em vez de bloquear a carga.

As linhas são recortadas do arquivo real (ver `test_largura_fixa`), montadas
num ZIP com o nome que a B3 usa.
"""
from __future__ import annotations

import io
import zipfile

import pytest

from app import seed_fontes
from app.motor import ingestao
from tests.test_largura_fixa import CABECALHO, CALL_ABCB, PETR4, PUT_AAPL, TRAILER

# ABCB4 à vista, para o ISIN da call ter com quem casar. Mesmo ISIN da
# ABCBH255, mercado 010.
ABCB4 = (
    "012026073102ABCB4       010ABC BRASIL  PN      N2   R$  00000000024090"
    "0000000024390000000002400000000000241200000000024000000000002400000000"
    "0002401014520000000000004963000000000011971825000000000000000099991231"
    "00000010000000000000BRABCBACNPR4151"
)

# Dois contratos a termo do mesmo papel no mesmo pregão. Só o prazo os separa
# — 060 e 090 —, e é o caso que aparece quinze vezes em 31/07/2026.
TERMO_060 = (
    "012026073162CPTS11T     030FII CAPI SECCI        060R$  00000000007680"
    "0000000007690000000000767000000000076800000000007680000000000000000000"
    "0000000000040000000000000900000000000000691201350000000000000099991231"
    "00000010000000000000BRCPTSCTF004259"
)
TERMO_090 = (
    "012026073162CPTS11T     030FII CAPI SECCI        090R$  00000000007790"
    "0000000007800000000000779000000000077900000000007800000000000000000000"
    "0000000000040000000000000500000000000000389869200000000000000099991231"
    "00000010000000000000BRCPTSCTF004259"
)


def zip_cotahist(linhas: list[str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "COTAHIST_D31072026.TXT",
            ("\r\n".join(linhas) + "\r\n").encode("latin-1"),
        )
    return buf.getvalue()


ARQUIVO = zip_cotahist(
    [CABECALHO, PETR4, ABCB4, CALL_ABCB, PUT_AAPL, TRAILER]
)


def test_as_linhas_do_fixture_tem_245_bytes():
    assert [len(linha) for linha in (ABCB4, TERMO_060, TERMO_090)] == [245] * 3


@pytest.fixture()
def carregado(sink):
    seed_fontes.aplicar(sink)
    resultado = ingestao.executar(
        sink, "b3_cotahist", "2026-07-31",
        baixar=lambda url, cabecalhos=None: ARQUIVO,
    )
    return sink, resultado


# --------------------------------------------------------------------------
# A carga
# --------------------------------------------------------------------------
def test_a_janela_iso_vira_o_nome_do_arquivo_diario(sink):
    """A janela fica em ISO — ordenável e igual à do resto do sistema — e o
    template da fonte a decompõe em dia/mês/ano. Guardá-la como `31072026` só
    para montar a URL deixaria a partição impossível de comparar."""
    seed_fontes.aplicar(sink)
    urls = []

    def baixar(url, cabecalhos=None):
        urls.append(url)
        return ARQUIVO

    ingestao.executar(sink, "b3_cotahist", "2026-07-31", baixar=baixar)
    assert urls == [
        "https://bvmf.bmfbovespa.com.br/InstDados/SerHist/COTAHIST_D31072026.ZIP"
    ]


def test_carrega_so_os_registros_de_cotacao(carregado):
    """Cabeçalho e encerramento têm os mesmos 245 bytes de uma cotação."""
    sink, resultado = carregado
    assert resultado.status == "publicado"
    assert resultado.linhas_silver == 4
    assert sink.um("SELECT count(*) AS n FROM fato_negociacao")["n"] == 4


def test_a_tabela_nasce_da_classe_e_nao_de_migracao(sink):
    """ADR-11: não existe CREATE TABLE de domínio. Se a classe não gerasse a
    tabela, a carga acima falharia por tabela inexistente — este teste só
    torna o motivo explícito."""
    seed_fontes.aplicar(sink)
    colunas = {
        linha["column_name"]
        for linha in sink.consultar(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'fato_negociacao'"
        )
    }
    assert {"dt_pregao", "codneg", "preco_exercicio", "dt_vencimento",
            "isin", "ticker_objeto"} <= colunas
    # Coluna sombra do preço: é ela que permite conferir uma escala suspeita
    # sem voltar ao bronze.
    assert "preco_fechamento_txt" in colunas


# --------------------------------------------------------------------------
# O dado
# --------------------------------------------------------------------------
def test_precos_saem_na_escala_certa(carregado):
    sink, _ = carregado
    petr = sink.um(
        "SELECT * FROM fato_negociacao WHERE codneg = 'PETR4' AND tp_mercado = '010'"
    )
    assert petr["preco_fechamento"] == pytest.approx(43.42)
    assert petr["volume_financeiro"] == pytest.approx(1_084_118_619.0)
    assert petr["isin"] == "BRPETRACNPR6"


def test_strike_e_vencimento_da_opcao(carregado):
    sink, _ = carregado
    call = sink.um("SELECT * FROM fato_negociacao WHERE codneg = 'ABCBH255'")
    assert call["tp_mercado"] == "070"
    assert call["cod_bdi"] == "78"
    assert call["preco_exercicio"] == pytest.approx(24.40)
    assert call["dt_vencimento"] == "2026-08-21"
    assert call["preco_fechamento"] == pytest.approx(0.57)


def test_o_isin_resolve_o_ativo_objeto(carregado):
    """A ligação opção→papel é dado publicado, não convenção de nome."""
    sink, _ = carregado
    call = sink.um("SELECT * FROM fato_negociacao WHERE codneg = 'ABCBH255'")
    assert call["isin"] == "BRABCBACNPR4"
    assert call["ticker_objeto"] == "ABCB4"


def test_opcao_sem_papel_no_pregao_fica_sem_objeto_e_so_alerta(carregado):
    """A put da AAPL34 está no fixture sem o BDR à vista — é a órfã.

    Bloquear aqui derrubaria a carga do pregão inteiro por causa de um papel
    que não negociou. O gate existe para barrar dado errado, não dado ausente.
    """
    sink, resultado = carregado
    put = sink.um("SELECT * FROM fato_negociacao WHERE codneg = 'AAPLV862'")
    assert put["ticker_objeto"] is None
    assert resultado.status == "publicado"
    assert [v["nome"] for v in resultado.violacoes] == [
        "negociacao_opcao_sem_ativo_objeto"
    ]


def test_acao_traz_a_sentinela_de_vencimento_que_a_b3_grava(carregado):
    """9999-12-31 é o que está no arquivo. Trocar por nulo na carga seria o
    motor decidindo o que aquilo significa; quem decide é a vista de gold."""
    sink, _ = carregado
    petr = sink.um(
        "SELECT * FROM fato_negociacao WHERE codneg = 'PETR4' AND tp_mercado = '010'"
    )
    assert petr["dt_vencimento"] == "9999-12-31"


# --------------------------------------------------------------------------
# A identidade
# --------------------------------------------------------------------------
def test_prazo_do_termo_faz_parte_da_identidade(sink):
    """Dois termos do mesmo papel, mesmo pregão, mesmo BDI, prazos diferentes.

    É o caso real que aparece quinze vezes no pregão de 31/07/2026. Sem
    `prazo_termo` na chave, o segundo sobrescreve o primeiro e a perda é
    silenciosa — nenhuma contagem denuncia, porque a carga «funcionou».
    """
    seed_fontes.aplicar(sink)
    ingestao.executar(
        sink, "b3_cotahist", "2026-07-31",
        baixar=lambda url, cabecalhos=None: zip_cotahist([TERMO_060, TERMO_090]),
    )
    guardadas = sink.consultar(
        "SELECT prazo_termo, preco_fechamento FROM fato_negociacao "
        "WHERE codneg = 'CPTS11T' ORDER BY prazo_termo"
    )
    assert [linha["prazo_termo"] for linha in guardadas] == ["060", "090"]
    assert [linha["preco_fechamento"] for linha in guardadas] == [
        pytest.approx(7.68), pytest.approx(7.80)
    ]


def test_campo_em_branco_na_identidade_nao_pode_virar_nulo(carregado):
    """`PRAZOT` vem em branco fora do termo, e branco vira NULL.

    NULL na chave natural não conflita — o índice único trata cada NULL como
    distinto —, então o upsert vira insert e a recarga duplica sem erro. Foi
    o que aconteceu: as duas linhas à vista deste fixture dobraram na segunda
    carga. O literal declarado (`vazio:000`) é o que fecha isso, e `000` é o
    que a própria B3 grava nas opções.
    """
    sink, _ = carregado
    prazos = {
        linha["codneg"]: linha["prazo_termo"]
        for linha in sink.consultar("SELECT codneg, prazo_termo FROM fato_negociacao")
    }
    assert prazos["PETR4"] == "000"
    assert prazos["ABCB4"] == "000"
    assert None not in prazos.values()


def test_chave_natural_nula_falha_alto_em_vez_de_duplicar(sink):
    """A guarda genérica, para o próximo dataset que cair nisto.

    Tirar o literal declarado devolve o branco ao NULL. Antes, a carga
    passava e a tabela dobrava na recarga seguinte; agora recusa dizendo qual
    coluna e o que fazer.
    """
    from app import repositorio as repo
    from app.motor.ingestao import ErroIngestao

    seed_fontes.aplicar(sink)
    ds = repo.dataset_vigente(sink, "b3_cotahist")
    sink.executar(
        "UPDATE cfg_coluna SET formato = NULL "
        "WHERE dataset_id = ? AND nome_destino = 'prazo_termo'",
        (ds["id"],),
    )
    with pytest.raises(ErroIngestao, match="prazo_termo"):
        ingestao.executar(
            sink, "b3_cotahist", "2026-07-31",
            baixar=lambda url, cabecalhos=None: ARQUIVO,
        )


def test_recarregar_o_mesmo_pregao_nao_duplica(carregado):
    """Idempotência pela identidade da classe: o cron pode rebaixar o dia."""
    sink, _ = carregado
    ingestao.executar(
        sink, "b3_cotahist", "2026-07-31",
        baixar=lambda url, cabecalhos=None: ARQUIVO,
    )
    assert sink.um("SELECT count(*) AS n FROM fato_negociacao")["n"] == 4
