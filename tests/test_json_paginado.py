"""Transporte JSON paginado, declarado em configuração.

Até aqui o motor sabia ZIP e CSV, e os dois entregam tudo numa requisição.
Uma API paginada não entrega, e isso obriga a responder o que é "o arquivo
oficial" quando não há arquivo.

A resposta adotada e verificada aqui: bronze guarda **todas as páginas,
cruas, na ordem**. Fundir os registros na captura seria conveniente e já
seria derivação — e o invariante do bronze não admite derivação.
"""
from __future__ import annotations

import base64
import json

import pytest

from app import repositorio as repo
from app.motor import ingestao, paginacao, parsing

PARAMETROS = {
    "modelo": {"language": "pt-br", "pageNumber": "{pagina}", "pageSize": 2},
    "codificacao": "base64_json",
    "paginacao": {"tamanho": 2, "caminho_total_paginas": "page.totalPages"},
    "caminho_registros": "results",
}

REGISTROS = [
    {"codeCVM": 9512, "issuingCompany": "PETR", "companyName": "PETROBRAS",
     "segment": "NM", "market": "", "dateListing": "2000-08-09"},
    {"codeCVM": 1023, "issuingCompany": "BBAS", "companyName": "BANCO DO BRASIL",
     "segment": "NM", "market": "", "dateListing": "1976-06-15"},
    {"codeCVM": 4170, "issuingCompany": "VALE", "companyName": "VALE",
     "segment": "NM", "market": "", "dateListing": "2002-03-01"},
]


def falso_baixar(chamadas: list[str]):
    """Simula a API: 2 registros por página, 2 páginas."""
    def _baixar(url: str, cabecalhos=None) -> bytes:
        chamadas.append(url)
        cru = url.rsplit("/", 1)[-1]
        pedido = json.loads(base64.b64decode(cru))
        pagina = int(pedido["pageNumber"])
        inicio = (pagina - 1) * 2
        return json.dumps({
            "page": {"totalPages": 2, "totalRecords": len(REGISTROS)},
            "results": REGISTROS[inicio:inicio + 2],
        }).encode()
    return _baixar


# --------------------------------------------------------------------------
# Captura
# --------------------------------------------------------------------------
def test_percorre_todas_as_paginas():
    chamadas: list[str] = []
    payload = paginacao.capturar("https://x/{parametros}", PARAMETROS,
                                 falso_baixar(chamadas), pausa=0)
    assert len(chamadas) == 2, "leu a contagem da primeira página e parou certo"
    guardado = json.loads(payload)
    assert len(guardado["paginas"]) == 2


def test_bronze_guarda_as_paginas_cruas_sem_fundir():
    """O invariante: nada é fundido na captura. Fundir é derivação, e
    derivação acontece na leitura, onde é refazível."""
    payload = paginacao.capturar("https://x/{parametros}", PARAMETROS,
                                 falso_baixar([]), pausa=0)
    guardado = json.loads(payload)
    assert "paginas" in guardado
    assert guardado["paginas"][0]["page"]["totalPages"] == 2, "metadado preservado"
    assert len(guardado["paginas"][0]["results"]) == 2
    assert len(guardado["paginas"][1]["results"]) == 1


def test_registros_sao_extraidos_na_leitura():
    payload = paginacao.capturar("https://x/{parametros}", PARAMETROS,
                                 falso_baixar([]), pausa=0)
    registros = paginacao.registros_do_bronze(payload, "results")
    assert [r["issuingCompany"] for r in registros] == ["PETR", "BBAS", "VALE"]


def test_parametros_vao_em_base64_no_caminho():
    url = paginacao.montar_url("https://x/{parametros}", PARAMETROS, 3)
    pedido = json.loads(base64.b64decode(url.rsplit("/", 1)[-1]))
    assert pedido == {"language": "pt-br", "pageNumber": 3, "pageSize": 2}


def test_sem_contagem_declarada_para_na_pagina_vazia():
    sem_total = {**PARAMETROS, "paginacao": {"tamanho": 2}}
    chamadas: list[str] = []

    def _baixar(url, cabecalhos=None):
        chamadas.append(url)
        cru = url.rsplit("/", 1)[-1]
        pagina = int(json.loads(base64.b64decode(cru))["pageNumber"])
        inicio = (pagina - 1) * 2
        return json.dumps({"results": REGISTROS[inicio:inicio + 2]}).encode()

    payload = paginacao.capturar("https://x/{parametros}", sem_total, _baixar,
                                 pausa=0)
    assert len(chamadas) == 3, "buscou até vir página vazia"
    assert len(paginacao.registros_do_bronze(payload, "results")) == 3


def test_api_que_nunca_acaba_e_interrompida():
    """Guarda contra API que sempre diz 'há mais': sem limite, a captura
    rodaria para sempre e encheria o bronze."""
    def _infinito(url):
        return json.dumps({"results": [{"codeCVM": 1}]}).encode()

    with pytest.raises(paginacao.ErroPaginacao, match="sem a fonte indicar o fim"):
        paginacao.capturar("https://x/{parametros}",
                           {**PARAMETROS, "paginacao": {}}, _infinito,
                           pausa=0, limite=5)


def test_contagem_de_paginas_ausente_e_erro_explicito():
    """Declarar `caminho_total_paginas` e a resposta não trazer é configuração
    errada, não motivo para adivinhar."""
    def _baixar(url, cabecalhos=None):
        return json.dumps({"results": REGISTROS}).encode()

    with pytest.raises(paginacao.ErroPaginacao, match="page.totalPages"):
        paginacao.capturar("https://x/{parametros}", PARAMETROS, _baixar, pausa=0)


# --------------------------------------------------------------------------
# Mapeamento: JSON usa o mesmo caminho do CSV
# --------------------------------------------------------------------------
def test_json_usa_o_mesmo_mapeamento_de_colunas(sink_cvm):
    """Se o mapeamento fosse reescrito por transporte, cada fonte nova traria
    de volta o parsing específico que o produto existe para eliminar."""
    ds = repo.dataset_vigente(sink_cvm, "b3_listadas")
    colunas = repo.colunas_do(sink_cvm, ds["id"])
    payload = paginacao.capturar("https://x/{parametros}", PARAMETROS,
                                 falso_baixar([]), pausa=0)
    linhas = list(parsing.ler_json(payload, colunas, "results",
                                   extras={"origem_dataset": "b3_listadas"}))
    assert [l["ticker"] for l in linhas] == ["PETR", "BBAS", "VALE"]
    assert linhas[0]["cd_cvm"] == 9512, "tipo inteiro convertido"
    assert linhas[0]["dt_listagem"] == "2000-08-09", "tipo data convertido"
    assert linhas[0]["origem_dataset"] == "b3_listadas"


def test_campo_obrigatorio_ausente_no_json_e_recusado(sink_cvm):
    ds = repo.dataset_vigente(sink_cvm, "b3_listadas")
    colunas = repo.colunas_do(sink_cvm, ds["id"])
    sem_ticker = json.dumps({"paginas": [{"results": [{"codeCVM": 1}]}]}).encode()
    with pytest.raises(parsing.ErroParse, match="issuingCompany"):
        list(parsing.ler_json(sem_ticker, colunas, "results"))


# --------------------------------------------------------------------------
# Ciclo completo
# --------------------------------------------------------------------------
def test_fonte_json_atravessa_o_ciclo_inteiro(sink_cvm):
    """Da captura à gold, sem nenhuma linha de código sobre esta fonte."""
    res = ingestao.executar(sink_cvm, "b3_listadas", "atual",
                            baixar=falso_baixar([]))
    assert res.status == "publicado", res.erro
    assert res.linhas_silver == 3

    linhas = sink_cvm.consultar(
        "SELECT cd_cvm, ticker, setor_b3, listada_b3 FROM dim_empresa "
        "WHERE origem_dataset = 'b3_listadas' ORDER BY cd_cvm")
    assert [l["ticker"] for l in linhas] == ["BBAS", "VALE", "PETR"]
    assert all(l["listada_b3"] for l in linhas), "o calculado derivou do ticker"

    em_gold = sink_cvm.consultar(
        "SELECT cd_cvm, ticker, listada_b3 FROM gold_empresa WHERE ticker IS NOT NULL")
    assert len(em_gold) == 3


def test_api_filtra_o_universo_da_b3(sink_cvm, tmp_path, monkeypatch):
    """A pergunta que motivou a fonte: 'só as empresas listadas na B3'.

    A CVM registra companhia que nunca teve ação em bolsa; a B3 lista ETF e
    BDR que não publicam balanço. Nenhuma das duas bases responde sozinha —
    é o cruzamento que responde, e ele é filtro em gold, não recorte na
    ingestão. O bronze de cada fonte continua inteiro.
    """
    from fastapi.testclient import TestClient
    from app import bootstrap, seed_cvm
    from app.api import auth
    from app.sinks import SinkDuckDB

    banco = str(tmp_path / "b3.duckdb")
    monkeypatch.setenv("PORTAL_DUCKDB", banco)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("PORTAL_ADMIN_TOKEN", raising=False)
    s = SinkDuckDB(banco)
    bootstrap.preparar(s)
    seed_cvm.aplicar(s)
    ingestao.executar(s, "b3_listadas", "atual", baixar=falso_baixar([]))
    # Uma companhia no cadastro da CVM que não negocia em bolsa.
    s.executar(
        "INSERT INTO dim_empresa (captura_id, fonte_arquivo, origem_dataset, "
        "cd_cvm, denom_social, publicado_em_versao) "
        "VALUES (1, 'cad.csv', 'cvm_cadastro', 7777, 'FECHADA S.A.', 1)")
    chave = auth.emitir(s, "teste")
    s.fechar()

    from app.api.main import app

    with TestClient(app) as c:
        cab = {"X-API-Key": chave.chave_completa}
        todas = c.get("/v1/empresas?limite=500", headers=cab).json()["dados"]
        so_b3 = c.get("/v1/empresas?listada_b3=true&limite=500",
                      headers=cab).json()["dados"]

    assert len(todas) == 4, "a base tem as 3 da B3 mais a fechada"
    assert len(so_b3) == 3
    assert 7777 not in {e["cd_cvm"] for e in so_b3}
    assert all(e["ticker"] for e in so_b3)
