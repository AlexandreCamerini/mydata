"""Etapa 0 — a rede de segurança.

Todo o plano de evolução do modelo apoia-se numa frase do CLAUDE.md: "dropar
e recomputar do bronze é a rotina normal de correção". Enquanto ninguém
executa essa frase, ela é uma intenção. Estes testes a executam.
"""
from __future__ import annotations

import time

from app.motor import ingestao, verificacao


def _baixar(mapa):
    return lambda url: next(v for k, v in mapa.items() if k in url)


def _carregar_tudo(sink, dfp, itr, cadastro):
    ingestao.executar(sink, "cvm_dfp", "2023",
                      baixar=_baixar({"dfp_cia_aberta_2023.zip": dfp}))
    ingestao.executar(sink, "cvm_itr", "2024",
                      baixar=_baixar({"itr_cia_aberta_2024.zip": itr}))
    ingestao.executar(sink, "cvm_cadastro", "atual",
                      baixar=_baixar({"cad_cia_aberta.csv": cadastro}))


def test_recomputar_do_bronze_reproduz_gold(
    sink_cvm, zip_dfp_2023, zip_itr_2024, csv_cadastro
):
    """O teste central: sem rede, só do bronze, gold volta idêntica.

    Se isto falhar, alguma coisa entrou no banco por fora do pipeline e o
    plano de volta de qualquer migração deixa de existir.
    """
    _carregar_tudo(sink_cvm, zip_dfp_2023, zip_itr_2024, csv_cadastro)
    antes = verificacao.impressao_digital(sink_cvm)
    assert antes["gold_demonstracoes"]["linhas"] > 0

    resultados = ingestao.recomputar_tudo(sink_cvm)

    assert [r.status for r in resultados] == ["publicado"] * len(resultados)
    assert verificacao.impressao_digital(sink_cvm) == antes


def test_recomputo_nao_depende_de_rede(sink_cvm, zip_dfp_2023):
    """`recomputar` recusa baixar: se tentar, o teste explode em vez de sair
    para a internet no meio da suíte."""
    ingestao.executar(sink_cvm, "cvm_dfp", "2023",
                      baixar=_baixar({"dfp_cia_aberta_2023.zip": zip_dfp_2023}))

    def proibido(url):  # pragma: no cover — falha o teste se for chamado
        raise AssertionError(f"recomputo tentou baixar {url}")

    import app.motor.download as download

    original, download.baixar = download.baixar, proibido
    try:
        res = ingestao.recomputar(sink_cvm, "cvm_dfp", "2023")
    finally:
        download.baixar = original
    assert res.status == "publicado"


def test_digital_ignora_o_numero_da_publicacao(sink_cvm, zip_dfp_2023):
    """Recomputar cria publicação nova. Isso não é mudança de dado, e a
    digital não pode dizer que é — senão ela acusa falso a cada verificação."""
    ingestao.executar(sink_cvm, "cvm_dfp", "2023",
                      baixar=_baixar({"dfp_cia_aberta_2023.zip": zip_dfp_2023}))
    from app.motor import publicacao

    v1 = publicacao.versao_atual(sink_cvm)
    antes = verificacao.impressao_digital(sink_cvm)
    ingestao.recomputar(sink_cvm, "cvm_dfp", "2023")
    assert publicacao.versao_atual(sink_cvm) > v1
    assert verificacao.impressao_digital(sink_cvm) == antes


def test_digital_acusa_quando_o_dado_muda(sink_cvm, zip_dfp_2023):
    """Uma digital que nunca muda não prova nada."""
    ingestao.executar(sink_cvm, "cvm_dfp", "2023",
                      baixar=_baixar({"dfp_cia_aberta_2023.zip": zip_dfp_2023}))
    antes = verificacao.impressao_digital(sink_cvm)
    sink_cvm.executar("UPDATE fato_conta SET vl_conta_norm = vl_conta_norm + 1")
    assert verificacao.impressao_digital(sink_cvm) != antes


# --------------------------------------------------------------------------
# Carga em bloco
# --------------------------------------------------------------------------
def test_carga_em_bloco_deduplica_pela_ordem_de_leitura(sink_cvm):
    """A CVM repete chave natural dentro do mesmo CSV. Vale a primeira
    ocorrência — como valia no laço em Python que a staging substituiu."""
    campos = ["captura_id", "fonte_arquivo", "cd_cvm", "tipo_doc", "dt_refer",
              "grupo", "consolidado", "cd_conta", "ordem_exerc", "versao",
              "ds_conta"]
    chave = ["cd_cvm", "tipo_doc", "dt_refer", "grupo", "consolidado",
             "cd_conta", "ordem_exerc", "versao"]
    base = [1, "x.csv", 9512, "dfp", "2023-12-31", "BPA", True, "1", "ÚLTIMO", 1]
    total = sink_cvm.carregar_em_lote("fato_conta", campos, chave, [
        [*base, "primeira"],
        [*base, "segunda"],
        [*base, "terceira"],
    ])
    assert total == 3, "todas as linhas passam pela staging"
    guardadas = sink_cvm.consultar("SELECT ds_conta FROM fato_conta")
    assert [g["ds_conta"] for g in guardadas] == ["primeira"]


def test_carga_em_bloco_atualiza_linha_existente(sink_cvm):
    campos = ["captura_id", "fonte_arquivo", "cd_cvm", "tipo_doc", "dt_refer",
              "grupo", "consolidado", "cd_conta", "ordem_exerc", "versao",
              "ds_conta"]
    chave = ["cd_cvm", "tipo_doc", "dt_refer", "grupo", "consolidado",
             "cd_conta", "ordem_exerc", "versao"]
    base = [1, "x.csv", 9512, "dfp", "2023-12-31", "BPA", True, "1", "ÚLTIMO", 1]
    sink_cvm.carregar_em_lote("fato_conta", campos, chave, [[*base, "antes"]])
    sink_cvm.carregar_em_lote("fato_conta", campos, chave, [[*base, "depois"]])
    assert sink_cvm.um("SELECT ds_conta FROM fato_conta")["ds_conta"] == "depois"
    assert sink_cvm.um("SELECT count(*) AS n FROM fato_conta")["n"] == 1


def test_carga_em_bloco_nao_deixa_staging_para_tras(sink_cvm):
    """Staging pendurada faz a próxima carga falhar por tabela já existente."""
    from app.sinks import STAGING

    campos = ["captura_id", "fonte_arquivo", "cd_cvm", "tipo_doc", "dt_refer",
              "grupo", "consolidado", "cd_conta", "ordem_exerc", "versao"]
    linha = [1, "x.csv", 9512, "dfp", "2023-12-31", "BPA", True, "1", "ÚLTIMO", 1]
    sink_cvm.carregar_em_lote("fato_conta", campos, campos[2:], [linha])
    existe = sink_cvm.consultar(
        "SELECT table_name FROM information_schema.tables WHERE table_name = ?",
        (STAGING,),
    )
    assert existe == []


def test_carga_em_bloco_e_ordens_de_grandeza_mais_rapida(sink_cvm):
    """Guarda-corpo de regressão: 20 mil linhas em menos de 15 segundos.

    O limite é folgado de propósito — a medição foi ~7.000 linhas/s numa
    máquina de desenvolvimento, e o teste existe para pegar volta ao upsert
    linha a linha (300 linhas/s), não para cravar desempenho.
    """
    campos = ["captura_id", "fonte_arquivo", "cd_cvm", "tipo_doc", "dt_refer",
              "grupo", "consolidado", "cd_conta", "ordem_exerc", "versao"]
    chave = campos[2:]
    linhas = [
        [1, "x.csv", 9000 + (i // 500), "dfp", "2023-12-31", "BPA", True,
         str(i), "ÚLTIMO", 1]
        for i in range(20_000)
    ]
    inicio = time.monotonic()
    sink_cvm.carregar_em_lote("fato_conta", campos, chave, linhas)
    decorrido = time.monotonic() - inicio
    assert decorrido < 15, f"carga de 20 mil linhas levou {decorrido:.1f}s"
