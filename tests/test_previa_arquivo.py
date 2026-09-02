"""`previa_arquivo` — o passo "Arquivo" do assistente de conexão nova.

Baixa a fonte de verdade (via `baixar` injetado) e devolve colunas + amostra
crua, sem gravar nada. Reaproveita `_urls_da_janela`/`_com_credencial` que
`executar()` já usa, e `parsing.membros_do_zip` para escolher o membro certo
dentro do ZIP — nada aqui duplica o pipeline de carga real.
"""
import pytest

from app import repositorio as repo
from app.motor import ingestao
from tests.conftest import baixador


def test_previa_zip_devolve_colunas_e_amostra(sink_cvm, zip_dfp_2023):
    ds = repo.dataset_vigente(sink_cvm, "cvm_dfp")
    rascunho = {
        "chave": ds["chave"],
        "padrao_arquivo": ds["padrao_arquivo"],
        "parametros": ds["parametros"],
    }
    b = baixador({"dfp_cia_aberta_2023.zip": zip_dfp_2023})

    r = ingestao.previa_arquivo(sink_cvm, "cvm", rascunho, "2023", baixar=b)

    # O primeiro membro do ZIP que casa com o padrão, em ordem alfabética —
    # a mesma escolha que uma carga de verdade faria.
    assert r["nome_arquivo"] == "dfp_cia_aberta_BPA_con_2023.csv"
    assert r["colunas"] == [
        "CNPJ_CIA", "DT_REFER", "VERSAO", "DENOM_CIA", "CD_CVM", "GRUPO_DFP",
        "MOEDA", "ESCALA_MOEDA", "ORDEM_EXERC", "DT_INI_EXERC", "DT_FIM_EXERC",
        "CD_CONTA", "DS_CONTA", "VL_CONTA", "ST_CONTA_FIXA", "COLUNA_DF",
    ]
    # Cru — sem conversão de tipo nem mapeamento. "1000,00" continua string,
    # é exatamente o que o passo "Ligar campos" precisa mostrar.
    assert len(r["amostra"]) == 5
    assert r["amostra"][0]["CNPJ_CIA"] == "00.000.000/0001-00"
    assert r["amostra"][0]["VL_CONTA"] == "1000,00"


def test_previa_respeita_limite(sink_cvm, zip_dfp_2023):
    ds = repo.dataset_vigente(sink_cvm, "cvm_dfp")
    rascunho = {
        "chave": ds["chave"], "padrao_arquivo": ds["padrao_arquivo"],
        "parametros": ds["parametros"],
    }
    b = baixador({"dfp_cia_aberta_2023.zip": zip_dfp_2023})

    r = ingestao.previa_arquivo(sink_cvm, "cvm", rascunho, "2023", baixar=b, limite=2)

    assert len(r["amostra"]) == 2


def test_previa_csv_direto(sink_cvm, csv_cadastro):
    ds = repo.dataset_vigente(sink_cvm, "cvm_cadastro")
    rascunho = {
        "chave": ds["chave"], "padrao_arquivo": ds["padrao_arquivo"],
        "parametros": ds["parametros"],
    }
    b = baixador({"cad_cia_aberta.csv": csv_cadastro})

    r = ingestao.previa_arquivo(sink_cvm, "cvm_cadastro", rascunho, "2024", baixar=b)

    assert "DENOM_SOCIAL" in r["colunas"]
    assert len(r["amostra"]) == 2


def test_previa_recusa_transporte_json(sink_cvm):
    # `b3` é http_json na configuração seed — sem "primeira linha" fora da
    # própria captura paginada, a prévia não cobre.
    rascunho = {"chave": "b3_listadas", "padrao_arquivo": "", "parametros": "{}"}
    with pytest.raises(ingestao.ErroIngestao, match="não cobre"):
        ingestao.previa_arquivo(
            sink_cvm, "b3", rascunho, "2024", baixar=lambda url: b"",
        )


def test_previa_fonte_desconhecida(sink_cvm):
    rascunho = {"chave": "x", "padrao_arquivo": "", "parametros": "{}"}
    with pytest.raises(ingestao.ErroIngestao, match="não está configurada"):
        ingestao.previa_arquivo(
            sink_cvm, "fonte_que_nao_existe", rascunho, "2024",
            baixar=lambda url: b"",
        )
