"""O cadastro de instrumentos no BVBG.028 — a fonte adotada pelo ADR-26.

A fixture `fixtures/bvbg028_20261118_amostra.xml` é recortada do XML real de
18/11/2026, com o envelope da B3: um par europeu sobre PETR4 (`PETRA673`,
`PETRM673`) e o próprio `PETR4`, uma call americana sobre BOVX11 cujo objeto
não está na amostra (`BOVXC200`), uma opção sobre IDI que chama o estilo de
`ExrcStyle` (`IDIN27P588100`), um instrumento de exercício cuja categoria não
tem nome no CSV (`BBASF272E`), um título sem código de negociação e duas das
dez distribuições de `RECV3L`. Escrever o XML à mão inventaria um layout que a
B3 não publica.
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from app import bootstrap, seed_fontes
from app.motor import ingestao, parsing, publicacao, verificacao
from app.repositorio import ErroConfiguracao, Fonte, salvar_fonte
from app.sinks import SinkDuckDB

AMOSTRA = (Path(__file__).parent / "fixtures" / "bvbg028_20261118_amostra.xml").read_bytes()
NOME_XML = "BVBG.028.02_BV000327202611180327130273181084200.xml"
ZIP_VAZIO = b"PK\x05\x06" + b"\x00" * 18   # os 22 bytes de dia sem pregão


def pacote(*xmls: tuple[str, bytes]) -> bytes:
    """Como a Pesquisa por pregão serve: ZIP com um ZIP com os XMLs."""
    interno = io.BytesIO()
    with zipfile.ZipFile(interno, "w", zipfile.ZIP_DEFLATED) as zf:
        for nome, corpo in xmls:
            zf.writestr(nome, corpo)
    externo = io.BytesIO()
    with zipfile.ZipFile(externo, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("IN261118.zip", interno.getvalue())
    return externo.getvalue()


def baixador(payload: bytes, pedidos: list[str] | None = None):
    def _baixar(url: str, cabecalhos=None) -> bytes:
        if pedidos is not None:
            pedidos.append(url)
        return payload
    return _baixar


@pytest.fixture()
def sink_bvbg(tmp_path):
    s = SinkDuckDB(str(tmp_path / "bvbg.duckdb"))
    bootstrap.preparar(s)
    seed_fontes.aplicar(s)
    yield s
    s.fechar()


def carregar(sink, payload: bytes | None = None, janela: str = "2026-11-18"):
    return ingestao.executar(
        sink, "b3_instrumentos_bvbg", janela,
        baixar=baixador(payload or pacote((NOME_XML, AMOSTRA))),
    )


def linha(sink, ticker: str, origem: str = "b3_instrumentos_bvbg") -> dict:
    return sink.um(
        "SELECT * FROM dim_instrumento WHERE ticker = ? AND origem_dataset = ?",
        (ticker, origem),
    )


# --------------------------------------------------------------------------
# Transporte e envelope
# --------------------------------------------------------------------------
def test_o_endereco_usa_o_ano_em_dois_digitos(sink_bvbg):
    pedidos: list[str] = []
    ingestao.executar(sink_bvbg, "b3_instrumentos_bvbg", "2026-11-18",
                      baixar=baixador(pacote((NOME_XML, AMOSTRA)), pedidos))
    assert pedidos == [
        "https://www.b3.com.br/pesquisapregao/download?filelist=IN261118.zip"
    ]


def test_carga_completa_desce_no_zip_dentro_do_zip(sink_bvbg):
    res = carregar(sink_bvbg)
    assert res.status == "publicado"
    tickers = {r["ticker"] for r in sink_bvbg.consultar(
        "SELECT ticker FROM dim_instrumento WHERE origem_dataset = 'b3_instrumentos_bvbg'")}
    assert tickers == {"PETR4", "PETRA673", "PETRM673", "BOVXC200",
                       "IDIN27P588100", "BBASF272E", "RECV3L"}


def test_registro_sem_codigo_de_negociacao_fica_de_fora(sink_bvbg):
    """O título não tem `TckrSymb`; sem o filtro, chegaria com chave nula e a
    carga inteira falharia."""
    carregar(sink_bvbg)
    assert sink_bvbg.um("SELECT count(*) AS n FROM dim_instrumento "
                        "WHERE ticker IS NULL")["n"] == 0


def test_dia_sem_pregao_falha_em_vez_de_publicar_vazio(sink_bvbg):
    """A B3 responde 200 com um ZIP de 22 bytes para fim de semana, feriado e
    data futura. Publicar zero linhas como sucesso deixaria a fotografia
    parada sem alarme."""
    with pytest.raises(ingestao.ErroIngestao, match="não traz arquivo"):
        carregar(sink_bvbg, ZIP_VAZIO, janela="2026-11-20")
    ultima = sink_bvbg.um(
        "SELECT status FROM log_execucao WHERE dataset_chave = 'b3_instrumentos_bvbg' "
        "ORDER BY id DESC LIMIT 1")
    assert ultima["status"] == "falha"
    assert sink_bvbg.um("SELECT count(*) AS n FROM dim_instrumento")["n"] == 0


def test_zip_vazio_nao_vira_bronze_e_o_recomputo_sobrevive(sink_bvbg):
    """O bronze é imutável e deduplica por hash: um ZIP vazio gravado lá seria
    relido — e falharia — em todo recomputo, e todo feriado seguinte cairia
    na mesma captura."""
    carregar(sink_bvbg)
    with pytest.raises(ingestao.ErroIngestao):
        carregar(sink_bvbg, ZIP_VAZIO, janela="2026-11-20")
    assert ingestao.janelas_capturadas(sink_bvbg, "b3_instrumentos_bvbg") == [
        "2026-11-18"]
    resultados = ingestao.recomputar_tudo(sink_bvbg)
    assert {r.status for r in resultados} == {"publicado"}


def test_a_captura_guarda_o_nome_do_pacote(sink_bvbg):
    """O endereço é `.../download?filelist=IN261118.zip`: chamar a captura de
    `download` apagaria de qual dia ela é."""
    carregar(sink_bvbg)
    nome = sink_bvbg.um("SELECT nome_arquivo FROM bronze_captura "
                        "WHERE dataset_chave = 'b3_instrumentos_bvbg'")
    assert nome["nome_arquivo"] == "IN261118.zip"


def test_campo_obrigatorio_que_some_do_xml_falha(sink_bvbg):
    """Se a B3 renomear a tag do estilo, a coluna não pode virar nula calada."""
    sem_estilo = (AMOSTRA.replace(b"OptnStyle>", b"EstiloNovo>")
                  .replace(b"ExrcStyle>", b"EstiloNovo>"))
    with pytest.raises(parsing.ErroParse, match="estilo|OptnStyle"):
        carregar(sink_bvbg, pacote((NOME_XML, sem_estilo)))
    assert sink_bvbg.um("SELECT count(*) AS n FROM dim_instrumento")["n"] == 0


def test_xml_sem_o_elemento_declarado_falha(sink_bvbg):
    outro = b'<?xml version="1.0"?><Document><Outra/></Document>'
    with pytest.raises(parsing.ErroParse, match="nenhum elemento <Instrm>"):
        carregar(sink_bvbg, pacote((NOME_XML, outro)))


def test_reemissao_do_mesmo_dia_entra_inteira(sink_bvbg):
    """O pacote de 18/11 trazia dois XMLs, o segundo com 138 tickers a mais."""
    so_petr4 = AMOSTRA.replace(b"PETRA673", b"PETRZ999")
    res = carregar(sink_bvbg, pacote(
        ("BVBG.028.02_BV0001.xml", so_petr4), (NOME_XML, AMOSTRA)))
    assert res.status == "publicado"
    assert linha(sink_bvbg, "PETRZ999") is not None
    assert linha(sink_bvbg, "PETRA673") is not None


# --------------------------------------------------------------------------
# O dado
# --------------------------------------------------------------------------
def test_estilo_de_exercicio_nos_dois_nomes_do_campo(sink_bvbg):
    carregar(sink_bvbg)
    assert linha(sink_bvbg, "PETRA673")["estilo_exercicio"] == "EURO"
    assert linha(sink_bvbg, "BOVXC200")["estilo_exercicio"] == "AMER"
    # Opção sobre disponível: `ExrcStyle`, não `OptnStyle`.
    assert linha(sink_bvbg, "IDIN27P588100")["estilo_exercicio"] == "EURO"


def test_codigos_viram_os_nomes_do_csv(sink_bvbg):
    carregar(sink_bvbg)
    call, put, acao = (linha(sink_bvbg, t) for t in ("PETRA673", "PETRM673", "PETR4"))
    assert (call["categoria"], call["mercado"], call["segmento"]) == (
        "OPTION ON EQUITIES", "EQUITY-DERIVATE", "EQUITY CALL")
    assert put["segmento"] == "EQUITY PUT"
    assert (call["tipo_opcao"], put["tipo_opcao"]) == ("Call", "Put")
    assert (acao["categoria"], acao["mercado"], acao["segmento"]) == (
        "SHARES", "EQUITY-CASH", "CASH")
    # Categoria 0 é vazio no CSV, e vazio é nulo.
    assert linha(sink_bvbg, "IDIN27P588100")["categoria"] is None


def test_codigo_sem_nome_passa_cru(sink_bvbg):
    """O CSV não trazia instrumento de exercício: não há nome a copiar, e
    inventar um seria pior que mostrar o código."""
    carregar(sink_bvbg)
    exercicio = linha(sink_bvbg, "BBASF272E")
    assert exercicio["categoria"] == "17"
    assert exercicio["mercado"] == "12/1"


def test_strike_com_ponto_decimal(sink_bvbg):
    carregar(sink_bvbg)
    assert linha(sink_bvbg, "PETRA673")["preco_exercicio"] == pytest.approx(66.19)


def test_ativo_objeto_resolvido_pelo_id(sink_bvbg):
    """O XML referencia o objeto da opção por id; o ticker dele está no
    registro do PETR4, no mesmo arquivo."""
    carregar(sink_bvbg)
    assert linha(sink_bvbg, "PETRA673")["ativo_objeto"] == "PETR4"
    assert linha(sink_bvbg, "PETRA673")["ativo_raiz"] == "PETR"
    # Sem objeto (ação), fica a raiz — o que o CSV publicava.
    assert linha(sink_bvbg, "PETR4")["ativo_objeto"] == "PETR"
    # Objeto fora do arquivo: a raiz, não nulo.
    assert linha(sink_bvbg, "BOVXC200")["ativo_objeto"] == "BOVX"


def test_distribuicao_repetida_fica_com_a_primeira(sink_bvbg):
    """Limite conhecido e declarado no seed: a ordem do arquivo não é a de
    vigência, então vale a regra de todo dataset."""
    carregar(sink_bvbg)
    assert linha(sink_bvbg, "RECV3L")["dt_inicio_negociacao"] == "2022-04-27"


# --------------------------------------------------------------------------
# Duas origens na mesma classe (ADR-12)
# --------------------------------------------------------------------------
def test_duas_origens_resolvem_uma_linha_por_ticker(sink_bvbg):
    from tests.test_instrumentos import arquivo, baixador as baixador_csv

    ingestao.executar(sink_bvbg, "b3_instrumentos", "2026-08-04",
                      baixar=baixador_csv(arquivo()))
    carregar(sink_bvbg)

    assert sink_bvbg.um("SELECT count(*) AS n FROM dim_instrumento "
                        "WHERE ticker = 'PETR4'")["n"] == 2
    resolvida = sink_bvbg.consultar(
        "SELECT ticker, dt_referencia, dt_referencia_origem FROM gold_instrumento_b3 "
        "WHERE ticker IN ('PETR4', 'ABCBH255') ORDER BY ticker")
    assert [r["ticker"] for r in resolvida] == ["ABCBH255", "PETR4"]
    petr4 = resolvida[1]
    # O BVBG é a fotografia mais nova e vence.
    assert (petr4["dt_referencia"], petr4["dt_referencia_origem"]) == (
        "2026-11-18", "b3_instrumentos_bvbg")
    # Ticker que só existiu no tempo do CSV continua respondendo pelo CSV.
    assert resolvida[0]["dt_referencia_origem"] == "b3_instrumentos"


def test_cadeia_de_opcoes_nao_duplica_com_duas_origens(sink_bvbg):
    from tests.test_instrumentos import arquivo, baixador as baixador_csv

    sink_bvbg.executar(
        "INSERT INTO fato_negociacao (captura_id, fonte_arquivo, origem_dataset, "
        " dt_pregao, codneg, tp_mercado, cod_bdi, prazo_termo, ticker_objeto, "
        " dt_vencimento, preco_exercicio, prazo_anos) "
        "VALUES (0,'x','b3_cotahist','2026-11-18','PETRA673','070','078','000',"
        " 'PETR4','2027-01-15', 66.19, 0.2)")
    publicacao.publicar(sink_bvbg)
    ingestao.executar(sink_bvbg, "b3_instrumentos", "2026-08-04",
                      baixar=baixador_csv(arquivo().replace(b"PETRG450", b"PETRA673")))
    carregar(sink_bvbg)

    linhas = sink_bvbg.consultar(
        "SELECT contrato, estilo_exercicio, strike_cadastro FROM gold_opcoes "
        "WHERE contrato = 'PETRA673'")
    assert len(linhas) == 1
    assert linhas[0]["estilo_exercicio"] == "EURO"
    # O strike do BVBG (66,19), não o do CSV (42,43).
    assert linhas[0]["strike_cadastro"] == pytest.approx(66.19)


def test_recomputar_reproduz_as_duas_origens(sink_bvbg):
    """O bronze em CSV continua recomputável depois da troca de fonte — é por
    isso que o BVBG é dataset novo, e não versão nova do antigo."""
    from tests.test_instrumentos import arquivo, baixador as baixador_csv

    ingestao.executar(sink_bvbg, "b3_instrumentos", "2026-08-04",
                      baixar=baixador_csv(arquivo()))
    carregar(sink_bvbg)
    antes = verificacao.impressao_digital(sink_bvbg)

    for ds in ("b3_instrumentos", "b3_instrumentos_bvbg"):
        for janela in ingestao.janelas_capturadas(sink_bvbg, ds):
            assert ingestao.recomputar(sink_bvbg, ds, janela).status == "publicado"

    depois = verificacao.impressao_digital(sink_bvbg)
    assert depois == antes


def test_o_agendamento_aponta_para_o_bvbg_e_o_csv_fica_desligado(sink_bvbg):
    from app import repositorio as repo

    ags = {a["chave"]: a for a in repo.listar_agendamentos(sink_bvbg)}
    assert ags["b3_instrumentos_diario"]["dataset_chave"] == "b3_instrumentos_bvbg"
    assert ags["b3_instrumentos_diario"]["ativo"]
    assert ags["b3_instrumentos_csv_diario"]["dataset_chave"] == "b3_instrumentos"
    assert not ags["b3_instrumentos_csv_diario"]["ativo"]


# --------------------------------------------------------------------------
# O leitor, isolado
# --------------------------------------------------------------------------
def _col(origem, destino, tipo="texto", formato=None, obrigatoria=False):
    return {"nome_origem": origem, "nome_destino": destino, "tipo": tipo,
            "formato": formato, "obrigatoria": obrigatoria}


XML_MINIMO = b"""<?xml version="1.0"?>
<R xmlns="urn:x"><Hdr><Id>cabecalho</Id></Hdr>
  <Doc><Reg><A><B>1</B></A><K><Opc><X>x1</X></Opc></K></Reg></Doc>
  <Doc><Reg><A><B>2</B><C>c</C></A><K><Fut><Y>y2</Y></Fut></K></Reg></Doc>
  <Doc><Reg><A><C>sem-b</C></A></Reg></Doc>
</R>"""


def test_caminho_ignora_namespace_e_aceita_curinga():
    linhas = list(parsing.ler_xml(
        XML_MINIMO, [_col("A/B", "b"), _col("K/*/X|K/*/Y", "xy")], "Reg",
        filtro_registro="A/B"))
    assert [(l["b"], l["xy"]) for l in linhas] == [("1", "x1"), ("2", "y2")]


def test_caminho_composto_junta_com_barra():
    linhas = list(parsing.ler_xml(
        XML_MINIMO, [_col("A/B+A/C", "bc")], "Reg"))
    assert [l["bc"] for l in linhas] == ["1/", "2/c", "/sem-b"]


def test_filtro_que_recusa_tudo_e_erro():
    with pytest.raises(parsing.ErroParse, match="nenhum com valor"):
        list(parsing.ler_xml(XML_MINIMO, [_col("A/B", "b")], "Reg",
                             filtro_registro="A/Inexistente"))


def test_caminho_com_trecho_vazio_falha_antes_de_ler():
    with pytest.raises(parsing.ErroParse, match="trecho vazio"):
        parsing.ler_xml(b"<nao-e-lido/>", [_col("A//B", "b")], "Reg")


def test_mapa_traduz_e_deixa_o_desconhecido_cru():
    assert parsing.converter("7", "texto", "mapa:7=OPCAO;0=") == "OPCAO"
    assert parsing.converter("0", "texto", "mapa:7=OPCAO;0=") is None
    assert parsing.converter("99", "texto", "mapa:7=OPCAO;0=") == "99"
    with pytest.raises(parsing.ErroParse, match="sem '='"):
        parsing.converter("7", "texto", "mapa:7-OPCAO")


def test_formato_xml_e_aceito_e_o_desconhecido_nao(sink_bvbg):
    base = dict(chave="f_teste", nome="t", tipo_transporte="http_zip",
                url_template="https://exemplo/{janela}.zip")
    salvar_fonte(sink_bvbg, Fonte(**base, formato_registro="xml"))
    with pytest.raises(ErroConfiguracao, match="formato_registro desconhecido"):
        salvar_fonte(sink_bvbg, Fonte(**base, formato_registro="json"))


def test_previa_recusa_xml(sink_bvbg):
    with pytest.raises(ingestao.ErroIngestao, match="não cobre o formato 'xml'"):
        ingestao.previa_arquivo(
            sink_bvbg, "b3_pesquisa_pregao",
            {"chave": "x", "padrao_arquivo": ".*", "parametros": "{}"},
            "2026-11-18", baixar=baixador(b""))
