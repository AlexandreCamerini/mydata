"""O cadastro de instrumentos da B3 — a fonte adotada pelo ADR-20.

As linhas do arquivo são reais, copiadas do arquivo de 04/08/2026: `ABCBH255`
é a única call americana da amostra, `PETRG450`/`PETRS450` são o par europeu
sobre PETR4, e `PETR4` é o papel à vista, que entra junto porque a carga não
filtra. Escrevê-las à mão inventaria um layout de 52 colunas que a B3 não
publica desse jeito — foi assim que a fixture do COTAHIST errou o strike em
uma casa decimal, e o teste passou a afirmar o erro.
"""
from __future__ import annotations

import pytest

from app import bootstrap, seed_cvm
from app.motor import ingestao
from app.sinks import SinkDuckDB, sql_upsert_da_staging

CABECALHO = (
    "RptDt;TckrSymb;Asst;AsstDesc;SgmtNm;MktNm;SctyCtgyNm;XprtnDt;XprtnCd;"
    "TradgStartDt;TradgEndDt;BaseCd;ConvsCritNm;MtrtyDtTrgtPt;ReqrdConvsInd;"
    "ISIN;CFICd;DlvryNtceStartDt;DlvryNtceEndDt;OptnTp;CtrctMltplr;AsstQtnQty;"
    "AllcnRndLot;TradgCcy;DlvryTpNm;WdrwlDays;WrkgDays;ClnrDays;RlvrBasePricNm;"
    "OpngFutrPosDay;SdTpCd1;UndrlygTckrSymb1;SdTpCd2;UndrlygTckrSymb2;"
    "PureGoldWght;ExrcPric;OptnStyle;ValTpNm;PrmUpfrntInd;OpngPosLmtDt;"
    "DstrbtnId;PricFctr;DaysToSttlm;SrsTpNm;PrtcnFlg;AutomtcExrcInd;"
    "SpcfctnCd;CrpnNm;CorpActnStartDt;CtdyTrtmntTpNm;MktCptlstn;CorpGovnLvlNm"
)

LINHAS = [
    "{dt};ABCBH255;ABCB4;ABCB;EQUITY CALL;EQUITY-DERIVATE;OPTION ON EQUITIES;"
    "2026-08-21;;2026-05-25;2026-08-21;;;;;BRABCB4H01B5;OCASPS;;;Call;;;100;"
    "BRL;FINANCIAL;;;;;;;;;;;{strike_abcb};AMER;;true;;150;1;1;SEM CORRECAO;"
    "true;false;;;;;;",
    "{dt};PETRG450;PETR4;PETR;EQUITY CALL;EQUITY-DERIVATE;OPTION ON EQUITIES;"
    "2027-07-16;;2025-07-28;2027-07-16;;;;;BRPETR4G1MD3;OCESPS;;;Call;;;100;"
    "BRL;FINANCIAL;;;;;;;;;;;42,43;EURO;;true;;219;1;1;SEM CORRECAO;true;"
    "false;;;;;;",
    "{dt};PETRS450;PETR4;PETR;EQUITY PUT;EQUITY-DERIVATE;OPTION ON EQUITIES;"
    "2027-07-16;;2025-07-28;2027-07-16;;;;;BRPETR4S1MN8;OPESPS;;;Put;;;100;"
    "BRL;FINANCIAL;;;;;;;;;;;42,43;EURO;;true;;219;1;1;SEM CORRECAO;true;"
    "false;;;;;;",
    "{dt};PETR4;PETR;PETR;CASH;EQUITY-CASH;SHARES;;;2026-07-23;9999-12-31;;;;;"
    "BRPETRACNPR6;EPNNPR;;;;;;1;BRL;;;;;;;;;;;;;;;;;229;1;2;;;;PN      N2;"
    "PETROLEO BRASILEIRO S.A. PETROBRAS;9999-12-31;FUNGIBLE;5446501379;NIVEL 2",
]


def arquivo(dt: str = "2026-08-04", strike_abcb: str = "24,4",
            repetir: bool = False) -> bytes:
    """O CSV como a B3 o serve: preâmbulo, cabeçalho, linhas."""
    corpo = [l.format(dt=dt, strike_abcb=strike_abcb) for l in LINHAS]
    if repetir:
        corpo.append(corpo[0])   # o arquivo real traz duas linhas repetidas
    texto = "\n".join(["Status do Arquivo: Final", CABECALHO, *corpo]) + "\n"
    return texto.encode("iso-8859-1")


def baixador(payload: bytes, bilhete: str = "abc123"):
    """Simula os dois passos: bilhete em JSON, depois os bytes."""
    def _baixar(url: str, cabecalhos=None) -> bytes:
        if "requestname" in url:
            return b'{"token":"%s"}' % bilhete.encode()
        assert f"token={bilhete}" in url, f"segundo passo sem o bilhete: {url}"
        return payload
    return _baixar


@pytest.fixture()
def sink_inst(tmp_path):
    s = SinkDuckDB(str(tmp_path / "inst.duckdb"))
    bootstrap.preparar(s)
    seed_cvm.aplicar(s)
    yield s
    s.fechar()


# --------------------------------------------------------------------------
# O transporte em dois passos
# --------------------------------------------------------------------------
def test_carga_completa(sink_inst):
    r = ingestao.executar(sink_inst, "b3_instrumentos", "2026-08-04",
                          baixar=baixador(arquivo()))
    assert r.status == "publicado"
    assert r.linhas_silver == 4
    assert r.violacoes == []


def test_a_carga_nao_filtra(sink_inst):
    """PETR4 entra junto das opções.

    Filtrar seria o motor decidindo qual linha do arquivo oficial merece
    existir — o mesmo argumento que fez a classe do COTAHIST ser
    `negociacao_b3` e não `opcao`."""
    ingestao.executar(sink_inst, "b3_instrumentos", "2026-08-04",
                      baixar=baixador(arquivo()))
    cats = {l["categoria"] for l in
            sink_inst.consultar("SELECT categoria FROM dim_instrumento")}
    assert cats == {"OPTION ON EQUITIES", "SHARES"}


def test_o_bronze_guarda_o_endereco_do_pedido(sink_inst):
    """E não o do bilhete, que vence em minutos.

    Proveniência que aponta para endereço morto não é proveniência."""
    ingestao.executar(sink_inst, "b3_instrumentos", "2026-08-04",
                      baixar=baixador(arquivo()))
    url = sink_inst.um(
        "SELECT url FROM bronze_captura WHERE dataset_chave = 'b3_instrumentos'"
    )["url"]
    assert "requestname" in url and "2026-08-04" in url
    assert "token=" not in url


def test_sem_url_arquivo_o_erro_diz_o_que_falta(sink_inst):
    sink_inst.executar(
        "UPDATE cfg_dataset SET parametros = '{}' "
        "WHERE chave = 'b3_instrumentos' AND vigente"
    )
    with pytest.raises(ingestao.ErroIngestao, match="url_arquivo"):
        ingestao.executar(sink_inst, "b3_instrumentos", "2026-08-04",
                          baixar=baixador(arquivo()))


def test_primeiro_passo_sem_json_falha_dizendo_o_que_veio(sink_inst):
    def _baixar(url, cabecalhos=None):
        return b"<html>manutencao</html>"
    with pytest.raises(ingestao.ErroIngestao, match="não devolveu JSON"):
        ingestao.executar(sink_inst, "b3_instrumentos", "2026-08-04",
                          baixar=_baixar)


def test_json_sem_o_campo_do_bilhete_lista_os_que_vieram(sink_inst):
    def _baixar(url, cabecalhos=None):
        return b'{"erro":"data invalida","codigo":400}'
    with pytest.raises(ingestao.ErroIngestao, match="codigo, erro"):
        ingestao.executar(sink_inst, "b3_instrumentos", "2026-08-04",
                          baixar=_baixar)


# --------------------------------------------------------------------------
# O preâmbulo
# --------------------------------------------------------------------------
def test_o_preambulo_e_descartado(sink_inst):
    """A primeira linha é "Status do Arquivo: Final".

    Sem declarar o salto, ela vira o cabeçalho e nenhuma coluna casa — com
    erro que fala de campo ausente, não de linha a mais."""
    ingestao.executar(sink_inst, "b3_instrumentos", "2026-08-04",
                      baixar=baixador(arquivo()))
    linha = sink_inst.um(
        "SELECT * FROM dim_instrumento WHERE ticker = 'PETRG450'")
    assert linha["ativo_objeto"] == "PETR4"
    assert linha["dt_referencia"] == "2026-08-04"


def test_strike_com_virgula_decimal(sink_inst):
    """O COTAHIST grava escala implícita porque é posicional; este grava
    `42,43`. São formatos diferentes do mesmo número."""
    ingestao.executar(sink_inst, "b3_instrumentos", "2026-08-04",
                      baixar=baixador(arquivo()))
    linha = sink_inst.um(
        "SELECT preco_exercicio FROM dim_instrumento WHERE ticker = 'PETRG450'")
    assert linha["preco_exercicio"] == pytest.approx(42.43)


# --------------------------------------------------------------------------
# O estilo de exercício — a razão da fonte existir
# --------------------------------------------------------------------------
def test_estilo_de_exercicio_chega(sink_inst):
    ingestao.executar(sink_inst, "b3_instrumentos", "2026-08-04",
                      baixar=baixador(arquivo()))
    por = {l["ticker"]: l["estilo_exercicio"] for l in sink_inst.consultar(
        "SELECT ticker, estilo_exercicio FROM dim_instrumento "
        "WHERE categoria LIKE 'OPTION%'")}
    assert por == {"ABCBH255": "AMER", "PETRG450": "EURO", "PETRS450": "EURO"}


def test_opcao_sem_estilo_alerta_sem_bloquear(sink_inst):
    """É o campo que motivou a fonte. Se vier vazio, a cadeia volta a não
    saber para quais séries o modelo europeu é aproximação — mas o resto do
    cadastro continua útil, então alerta e não bloqueia."""
    quebrado = arquivo().replace(b";AMER;", b";;")
    r = ingestao.executar(sink_inst, "b3_instrumentos", "2026-08-04",
                          baixar=baixador(quebrado))
    assert r.status == "publicado"
    assert [v["nome"] for v in r.violacoes] == ["instrumento_opcao_sem_estilo"]


# --------------------------------------------------------------------------
# A guarda de recarga fora de ordem
# --------------------------------------------------------------------------
def test_recarga_antiga_nao_desfaz_o_cadastro(sink_inst):
    """A identidade é o instrumento, sem a data.

    Sem a guarda, reingerir um dia antigo devolveria o cadastro ao estado
    dele — sem erro e sem sintoma, que é a pior forma de errar. O strike
    corrigido por provento é exatamente o campo que andaria para trás."""
    ingestao.executar(sink_inst, "b3_instrumentos", "2026-08-04",
                      baixar=baixador(arquivo(strike_abcb="24,4")))
    ingestao.executar(
        sink_inst, "b3_instrumentos", "2026-07-20",
        baixar=baixador(arquivo(dt="2026-07-20", strike_abcb="25,1")),
    )
    linha = sink_inst.um(
        "SELECT preco_exercicio, dt_referencia FROM dim_instrumento "
        "WHERE ticker = 'ABCBH255'")
    assert linha["preco_exercicio"] == pytest.approx(24.4)
    assert linha["dt_referencia"] == "2026-08-04"


def test_recarga_nova_atualiza(sink_inst):
    """A guarda não pode virar congelamento: o dia seguinte tem de entrar."""
    ingestao.executar(sink_inst, "b3_instrumentos", "2026-08-04",
                      baixar=baixador(arquivo(strike_abcb="24,4")))
    ingestao.executar(
        sink_inst, "b3_instrumentos", "2026-08-05",
        baixar=baixador(arquivo(dt="2026-08-05", strike_abcb="24,1")),
    )
    linha = sink_inst.um(
        "SELECT preco_exercicio, dt_referencia FROM dim_instrumento "
        "WHERE ticker = 'ABCBH255'")
    assert linha["preco_exercicio"] == pytest.approx(24.1)
    assert linha["dt_referencia"] == "2026-08-05"


def test_linha_repetida_e_absorvida(sink_inst):
    """O arquivo de 04/08/2026 traz duas linhas idênticas nos 52 campos.

    Não é conflito de identidade; é linha duplicada, e o upsert a absorve."""
    r = ingestao.executar(sink_inst, "b3_instrumentos", "2026-08-04",
                          baixar=baixador(arquivo(repetir=True)))
    assert r.status == "publicado"
    assert sink_inst.um(
        "SELECT count(*) AS n FROM dim_instrumento")["n"] == 4


def test_guarda_recusa_coluna_que_nao_existe():
    """Erro na configuração aparece ao montar o SQL, não como linha faltando
    meses depois."""
    with pytest.raises(ValueError, match="nao_retroceder"):
        sql_upsert_da_staging("t", ["k", "v"], ["k"], nao_retroceder="inventada")


def test_sem_guarda_o_sql_nao_ganha_clausula():
    sql = sql_upsert_da_staging("t", ["k", "v"], ["k"])
    assert "WHERE t." not in sql
    com = sql_upsert_da_staging("t", ["k", "v", "dt"], ["k"],
                                nao_retroceder="dt")
    assert "WHERE t.dt <= excluded.dt" in com
