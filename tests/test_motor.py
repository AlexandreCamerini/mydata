"""Fase 2 — motor de ingestão: bronze, idempotência, calculados, gate, gold."""
from __future__ import annotations

import pytest

from app import repositorio as repo
from app.motor import ingestao, publicacao
from app.motor.parsing import ErroParse


def baixador(mapa: dict[str, bytes]):
    """Substitui a rede: devolve o payload pela URL."""
    def _baixar(url: str) -> bytes:
        for chave, dado in mapa.items():
            if chave in url:
                return dado
        raise AssertionError(f"URL não prevista no teste: {url}")
    return _baixar


# --------------------------------------------------------------------------
# Bronze
# --------------------------------------------------------------------------
def test_bronze_guarda_hash_url_e_tamanho(sink_cvm, zip_dfp_2023):
    ingestao.executar(
        sink_cvm, "cvm_dfp", "2023",
        baixar=baixador({"dfp_cia_aberta_2023.zip": zip_dfp_2023}),
    )
    captura = sink_cvm.um("SELECT * FROM bronze_captura")
    assert len(captura["sha256"]) == 64
    assert captura["tamanho_bytes"] == len(zip_dfp_2023)
    assert captura["url"].startswith("https://dados.cvm.gov.br/")
    assert captura["janela"] == "2023"


def test_recaptura_identica_nao_duplica(sink_cvm, zip_dfp_2023):
    """O cron rebaixa o mesmo ano com frequência; só reapresentação é nova."""
    b = baixador({"dfp_cia_aberta_2023.zip": zip_dfp_2023})
    r1 = ingestao.executar(sink_cvm, "cvm_dfp", "2023", baixar=b)
    r2 = ingestao.executar(sink_cvm, "cvm_dfp", "2023", baixar=b)
    assert r1.capturas_novas == 1
    assert r2.capturas_novas == 0
    assert sink_cvm.um("SELECT count(*) AS n FROM bronze_captura")["n"] == 1


def test_conteudo_diferente_gera_nova_captura(sink_cvm, zip_dfp_2023):
    from tests.conftest import csv_conta, linha, zip_cvm

    ingestao.executar(
        sink_cvm, "cvm_dfp", "2023",
        baixar=baixador({"dfp_cia_aberta_2023.zip": zip_dfp_2023}),
    )
    reapresentado = zip_cvm({
        "dfp_cia_aberta_BPA_con_2023.csv": csv_conta([
            linha(versao=3, cd_conta="1", vl="1200,00"),
        ]),
    })
    ingestao.executar(
        sink_cvm, "cvm_dfp", "2023",
        baixar=baixador({"dfp_cia_aberta_2023.zip": reapresentado}),
    )
    assert sink_cvm.um("SELECT count(*) AS n FROM bronze_captura")["n"] == 2


# --------------------------------------------------------------------------
# Silver e idempotência
# --------------------------------------------------------------------------
def test_carga_ignora_arquivo_fora_do_padrao(sink_cvm, zip_dfp_2023):
    """O ZIP tem um CSV que não casa com padrao_arquivo."""
    ingestao.executar(
        sink_cvm, "cvm_dfp", "2023",
        baixar=baixador({"dfp_cia_aberta_2023.zip": zip_dfp_2023}),
    )
    arquivos = {
        r["fonte_arquivo"]
        for r in sink_cvm.consultar("SELECT DISTINCT fonte_arquivo FROM fato_conta")
    }
    assert "dfp_cia_aberta_2023.csv" not in arquivos
    assert len(arquivos) == 4


def test_mesma_janela_duas_vezes_nao_duplica_linhas(sink_cvm, zip_dfp_2023):
    """Critério de aceite da Fase 2 (a)."""
    b = baixador({"dfp_cia_aberta_2023.zip": zip_dfp_2023})
    ingestao.executar(sink_cvm, "cvm_dfp", "2023", baixar=b)
    n1 = sink_cvm.um("SELECT count(*) AS n FROM fato_conta")["n"]
    ingestao.executar(sink_cvm, "cvm_dfp", "2023", baixar=b)
    n2 = sink_cvm.um("SELECT count(*) AS n FROM fato_conta")["n"]
    assert n1 == n2 > 0


def test_metadado_vem_do_nome_do_arquivo(sink_cvm, zip_dfp_2023):
    """tipo_doc, grupo e consolidado saem dos grupos nomeados do regex."""
    ingestao.executar(
        sink_cvm, "cvm_dfp", "2023",
        baixar=baixador({"dfp_cia_aberta_2023.zip": zip_dfp_2023}),
    )
    linhas = sink_cvm.consultar(
        "SELECT DISTINCT tipo_doc, grupo, consolidado FROM fato_conta ORDER BY grupo, consolidado"
    )
    assert {(r["tipo_doc"], r["grupo"], r["consolidado"]) for r in linhas} == {
        ("dfp", "BPA", True), ("dfp", "BPA", False),
        ("dfp", "BPP", True), ("dfp", "DRE", True),
    }


def test_valor_original_preservado_ao_lado_do_convertido(sink_cvm, zip_dfp_2023):
    ingestao.executar(
        sink_cvm, "cvm_dfp", "2023",
        baixar=baixador({"dfp_cia_aberta_2023.zip": zip_dfp_2023}),
    )
    linha = sink_cvm.um(
        "SELECT vl_conta, vl_conta_txt, vl_conta_norm FROM fato_conta "
        "WHERE cd_cvm = 9512 AND versao = 2 AND cd_conta = '1' AND consolidado"
    )
    assert linha["vl_conta_txt"] == "1100,00"   # exatamente como a CVM publicou
    assert linha["vl_conta"] == 1100.0          # conversão de representação
    assert linha["vl_conta_norm"] == 1100000.0  # campo calculado (escala MIL)


def test_coluna_obrigatoria_ausente_falha_a_carga(sink_cvm):
    """Contrato de schema: coluna sumiu na fonte => falha, não nulo silencioso."""
    from tests.conftest import zip_cvm

    quebrado = zip_cvm({
        "dfp_cia_aberta_BPA_con_2023.csv":
            "CNPJ_CIA;DT_REFER;CD_CONTA\n00.0;2023-12-31;1\n".encode("latin-1"),
    })
    with pytest.raises(ErroParse) as e:
        ingestao.executar(
            sink_cvm, "cvm_dfp", "2023",
            baixar=baixador({"dfp_cia_aberta_2023.zip": quebrado}),
        )
    assert "CD_CVM" in str(e.value)


# --------------------------------------------------------------------------
# Campos calculados
# --------------------------------------------------------------------------
def test_escala_normalizada_por_empresa(sink_cvm, zip_dfp_2023):
    """Armadilha 3: MIL numa empresa, UNIDADE na outra."""
    ingestao.executar(
        sink_cvm, "cvm_dfp", "2023",
        baixar=baixador({"dfp_cia_aberta_2023.zip": zip_dfp_2023}),
    )
    outra = sink_cvm.um(
        "SELECT vl_conta, vl_conta_norm FROM fato_conta "
        "WHERE cd_cvm = 1023 AND cd_conta = '1'"
    )
    assert outra["vl_conta"] == 5000000.0 and outra["vl_conta_norm"] == 5000000.0


def test_is_latest_marca_so_a_ultima_versao(sink_cvm, zip_dfp_2023):
    """Armadilha 1: reapresentação. Somar sem filtrar dobraria o ativo."""
    ingestao.executar(
        sink_cvm, "cvm_dfp", "2023",
        baixar=baixador({"dfp_cia_aberta_2023.zip": zip_dfp_2023}),
    )
    linhas = sink_cvm.consultar(
        "SELECT versao, is_latest FROM fato_conta WHERE cd_cvm = 9512 "
        "AND cd_conta = '1' AND consolidado AND ordem_exerc = 'ÚLTIMO' "
        "ORDER BY versao"
    )
    assert [(r["versao"], r["is_latest"]) for r in linhas] == [(1, False), (2, True)]


def test_itr_acumulado_so_em_conta_de_fluxo(sink_cvm, zip_itr_2024):
    """Armadilha 5: DRE acumula no ITR, BPA não."""
    ingestao.executar(
        sink_cvm, "cvm_itr", "2024",
        baixar=baixador({"itr_cia_aberta_2024.zip": zip_itr_2024}),
    )
    dre = sink_cvm.um("SELECT itr_acumulado FROM fato_conta WHERE grupo = 'DRE' LIMIT 1")
    bpa = sink_cvm.um("SELECT itr_acumulado FROM fato_conta WHERE grupo = 'BPA' LIMIT 1")
    assert dre["itr_acumulado"] is True
    assert bpa["itr_acumulado"] is False


def test_is_latest_recomputa_global_ao_reingerir_ano_antigo(sink_cvm):
    """O caso que a partição global existe para pegar.

    Carrega 2023, depois carrega 2022 contendo reapresentação de um documento
    de 2023. Sem recomputação global, o is_latest de 2023 ficaria errado.
    """
    from tests.conftest import csv_conta, linha, zip_cvm

    zip23 = zip_cvm({"dfp_cia_aberta_BPA_con_2023.csv": csv_conta([
        linha(versao=1, dt_refer="2023-12-31", cd_conta="1", vl="1000,00"),
    ])})
    ingestao.executar(
        sink_cvm, "cvm_dfp", "2023",
        baixar=baixador({"dfp_cia_aberta_2023.zip": zip23}),
    )
    assert sink_cvm.um(
        "SELECT is_latest FROM fato_conta WHERE versao = 1"
    )["is_latest"] is True

    # ZIP de 2022 traz a versão 3 do documento de 2023-12-31 (reapresentação).
    zip22 = zip_cvm({"dfp_cia_aberta_BPA_con_2022.csv": csv_conta([
        linha(versao=3, dt_refer="2023-12-31", cd_conta="1", vl="1300,00"),
    ])})
    ingestao.executar(
        sink_cvm, "cvm_dfp", "2022",
        baixar=baixador({"dfp_cia_aberta_2022.zip": zip22}),
    )
    estados = {
        r["versao"]: r["is_latest"]
        for r in sink_cvm.consultar("SELECT versao, is_latest FROM fato_conta")
    }
    assert estados == {1: False, 3: True}, (
        "a carga de 2022 tem de rebaixar o documento de 2023"
    )


# --------------------------------------------------------------------------
# Recomputação
# --------------------------------------------------------------------------
def test_recomputar_do_bronze_reproduz_a_carga(sink_cvm, zip_dfp_2023):
    """Critério de aceite da Fase 2 (b). Roda sem rede."""
    ingestao.executar(
        sink_cvm, "cvm_dfp", "2023",
        baixar=baixador({"dfp_cia_aberta_2023.zip": zip_dfp_2023}),
    )
    antes = sink_cvm.consultar(
        "SELECT cd_cvm, cd_conta, consolidado, versao, vl_conta, vl_conta_norm, "
        "is_latest FROM fato_conta ORDER BY cd_cvm, cd_conta, consolidado, versao"
    )
    res = ingestao.recomputar(sink_cvm, "cvm_dfp", "2023")   # baixar=None
    depois = sink_cvm.consultar(
        "SELECT cd_cvm, cd_conta, consolidado, versao, vl_conta, vl_conta_norm, "
        "is_latest FROM fato_conta ORDER BY cd_cvm, cd_conta, consolidado, versao"
    )
    assert res.status == "publicado"
    assert antes == depois and len(antes) > 0


def test_recomputar_sem_bronze_falha_com_mensagem_util(sink_cvm):
    with pytest.raises(ingestao.ErroIngestao) as e:
        ingestao.recomputar(sink_cvm, "cvm_dfp", "1998")
    assert "bronze" in str(e.value).lower()


# --------------------------------------------------------------------------
# Gate de qualidade
# --------------------------------------------------------------------------
def test_regra_bloqueante_impede_publicacao(sink_cvm):
    """Escala desconhecida => vl_conta_norm errado em silêncio => barra."""
    from tests.conftest import csv_conta, linha, zip_cvm

    ruim = zip_cvm({"dfp_cia_aberta_BPA_con_2023.csv": csv_conta([
        linha(escala="BILHAO", cd_conta="1", vl="1,00"),
    ])})
    res = ingestao.executar(
        sink_cvm, "cvm_dfp", "2023",
        baixar=baixador({"dfp_cia_aberta_2023.zip": ruim}),
    )
    assert res.status == "bloqueada"
    assert any(v["nome"] == "escala_desconhecida" for v in res.violacoes)
    assert res.publicacao is None
    assert publicacao.versao_atual(sink_cvm) == 0


def test_versao_anterior_continua_no_ar_apos_bloqueio(sink_cvm, zip_dfp_2023):
    """O consumidor não vê dado quebrado — vê o último bom."""
    from tests.conftest import csv_conta, linha, zip_cvm

    ingestao.executar(
        sink_cvm, "cvm_dfp", "2023",
        baixar=baixador({"dfp_cia_aberta_2023.zip": zip_dfp_2023}),
    )
    boas = sink_cvm.um("SELECT count(*) AS n FROM gold_demonstracoes")["n"]
    v1 = publicacao.versao_atual(sink_cvm)

    ruim = zip_cvm({"dfp_cia_aberta_BPA_con_2024.csv": csv_conta([
        linha(dt_refer="2024-12-31", escala="ZILHAO", cd_conta="1", vl="1,00"),
    ])})
    res = ingestao.executar(
        sink_cvm, "cvm_dfp", "2024",
        baixar=baixador({"dfp_cia_aberta_2024.zip": ruim}),
    )
    assert res.status == "bloqueada"
    assert publicacao.versao_atual(sink_cvm) == v1
    assert sink_cvm.um("SELECT count(*) AS n FROM gold_demonstracoes")["n"] == boas


def test_reconciliacao_ativo_passivo_passa_com_dado_coerente(sink_cvm, zip_dfp_2023):
    res = ingestao.executar(
        sink_cvm, "cvm_dfp", "2023",
        baixar=baixador({"dfp_cia_aberta_2023.zip": zip_dfp_2023}),
    )
    nomes = {v["nome"] for v in res.violacoes}
    assert "reconciliacao_ativo_passivo" not in nomes
    assert res.status == "publicado"


def test_reconciliacao_pega_ativo_diferente_de_passivo(sink_cvm):
    from tests.conftest import csv_conta, linha, zip_cvm

    desbalanceado = zip_cvm({
        "dfp_cia_aberta_BPA_con_2023.csv": csv_conta([
            linha(cd_conta="1", vl="1000,00"),
        ]),
        "dfp_cia_aberta_BPP_con_2023.csv": csv_conta([
            linha(cd_conta="2", vl="700,00", grupo_dfp="DF Consolidado - BPP"),
        ]),
    })
    res = ingestao.executar(
        sink_cvm, "cvm_dfp", "2023",
        baixar=baixador({"dfp_cia_aberta_2023.zip": desbalanceado}),
    )
    assert res.status == "bloqueada"
    assert any(v["nome"] == "reconciliacao_ativo_passivo" for v in res.violacoes)


# --------------------------------------------------------------------------
# Gold
# --------------------------------------------------------------------------
def test_gold_filtra_latest_e_ultimo_exercicio(sink_cvm, zip_dfp_2023):
    ingestao.executar(
        sink_cvm, "cvm_dfp", "2023",
        baixar=baixador({"dfp_cia_aberta_2023.zip": zip_dfp_2023}),
    )
    linhas = sink_cvm.consultar(
        "SELECT versao, cd_conta FROM gold_demonstracoes "
        "WHERE cd_cvm = 9512 AND consolidado AND grupo = 'BPA'"
    )
    assert all(r["versao"] == 2 for r in linhas)
    assert len(linhas) == 2   # conta 1 e 1.01 da versão 2, sem PENÚLTIMO


def test_gold_soma_sem_dobrar(sink_cvm, zip_dfp_2023):
    """A prova de que as armadilhas 1, 2 e 4 estão fechadas em gold."""
    ingestao.executar(
        sink_cvm, "cvm_dfp", "2023",
        baixar=baixador({"dfp_cia_aberta_2023.zip": zip_dfp_2023}),
    )
    total = sink_cvm.um(
        "SELECT sum(vl_conta_norm) AS t FROM gold_demonstracoes "
        "WHERE cd_cvm = 9512 AND consolidado AND grupo = 'BPA' AND cd_conta = '1'"
    )["t"]
    assert total == 1100000.0   # só a versão 2, só ÚLTIMO, só consolidado


def test_itr_trimestre_isolado(sink_cvm, zip_itr_2024):
    """Armadilha 5: Q2 isolado = acumulado(Q2) - acumulado(Q1)."""
    ingestao.executar(
        sink_cvm, "cvm_itr", "2024",
        baixar=baixador({"itr_cia_aberta_2024.zip": zip_itr_2024}),
    )
    linhas = sink_cvm.consultar(
        "SELECT dt_refer, vl_acumulado, vl_trimestre FROM gold_itr_trimestre "
        "WHERE cd_conta = '3.01' ORDER BY dt_refer"
    )
    assert [(r["vl_acumulado"], r["vl_trimestre"]) for r in linhas] == [
        (100000.0, 100000.0),   # Q1 isolado = Q1 acumulado
        (250000.0, 150000.0),   # 250 - 100
        (420000.0, 170000.0),   # 420 - 250
    ]


def test_publicacao_troca_ponteiro_e_reverte(sink_cvm, zip_dfp_2023):
    b = baixador({"dfp_cia_aberta_2023.zip": zip_dfp_2023})
    ingestao.executar(sink_cvm, "cvm_dfp", "2023", baixar=b)
    v1 = publicacao.versao_atual(sink_cvm)
    ingestao.executar(sink_cvm, "cvm_dfp", "2023", baixar=b)
    v2 = publicacao.versao_atual(sink_cvm)
    assert v2 == v1 + 1

    publicacao.reverter(sink_cvm, v1)
    # O ponteiro voltou; a view versionada anterior continua existindo.
    assert sink_cvm.um(f"SELECT count(*) AS n FROM gold_demonstracoes_v{v1}")["n"] > 0


# --------------------------------------------------------------------------
# Cadastro (dim_empresa)
# --------------------------------------------------------------------------
def test_cadastro_carrega_dim_empresa(sink_cvm, csv_cadastro):
    ingestao.executar(
        sink_cvm, "cvm_cadastro", "atual",
        baixar=baixador({"cad_cia_aberta.csv": csv_cadastro}),
    )
    linhas = sink_cvm.consultar("SELECT * FROM gold_empresa ORDER BY cd_cvm")
    assert [r["cd_cvm"] for r in linhas] == [1023, 9512]
    assert linhas[1]["denom_social"] == "EMPRESA TESTE S.A."
    assert linhas[1]["setor_atividade"] == "Petróleo e Gás"  # latin-1 preservado


# --------------------------------------------------------------------------
# Log de execução
# --------------------------------------------------------------------------
def test_execucao_registra_snapshot_e_delta(sink_cvm, zip_dfp_2023):
    b = baixador({"dfp_cia_aberta_2023.zip": zip_dfp_2023})
    ingestao.executar(sink_cvm, "cvm_dfp", "2023", baixar=b)
    ingestao.executar(sink_cvm, "cvm_dfp", "2023", baixar=b)

    execs = repo.execucoes(sink_cvm, dataset_chave="cvm_dfp")
    assert len(execs) == 2
    assert execs[0]["status"] == "publicado"
    assert execs[0]["delta_linhas"] == 0   # segunda carga não acrescenta linha
    assert execs[1]["delta_linhas"] > 0
    assert "cvm_dfp" in execs[0]["cfg_snapshot"]


def test_falha_fica_registrada_no_log(sink_cvm):
    def explode(url: str) -> bytes:
        raise RuntimeError("rede caiu")

    with pytest.raises(RuntimeError):
        ingestao.executar(sink_cvm, "cvm_dfp", "2023", baixar=explode)
    ultima = repo.execucoes(sink_cvm)[0]
    assert ultima["status"] == "falha" and "rede caiu" in ultima["erro"]
