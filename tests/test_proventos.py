"""Proventos e eventos corporativos (ADR-22).

Três coisas novas do motor entram em cena aqui, todas declaradas e nenhuma
sabendo o que é B3: iteração por lista vinda de SQL declarado (uma chamada
por companhia), desencapsulamento de resposta duplamente codificada na
leitura, e herança de campos do objeto-pai — o `codeCVM` mora no pai e o
evento é o filho.

O caso que definiu a identidade está no fake: a Petrobras aprova duas
parcelas de JCP na mesma reunião — mesmo ISIN, mesmo tipo, mesma data de
aprovação — separadas só pela data de pagamento.
"""
from __future__ import annotations

import base64
import json

import pytest

from app import repositorio as repo
from app.motor import ingestao, paginacao

# A resposta real da B3 é uma STRING JSON embrulhando a lista — duplamente
# codificada — com o codeCVM no objeto-pai. O fake reproduz isso fielmente.
SUPLEMENTOS = {
    "PETR": [{
        "code": "PETR", "codeCVM": "9512", "tradingName": "PETROBRAS   ",
        "cashDividends": [
            {"assetIssued": "BRPETRACNOR9", "paymentDate": "21/12/2026",
             "rate": "0,47156696000", "relatedTo": "Anual/2026",
             "approvedOn": "06/08/2026", "isinCode": "BRPETRACNOR9",
             "label": "DIVIDENDO", "lastDatePrior": "21/08/2026", "remarks": ""},
            # A parcela-irmã: tudo igual, menos a data de pagamento.
            {"assetIssued": "BRPETRACNOR9", "paymentDate": "23/11/2026",
             "rate": "0,67407131000", "relatedTo": "Anual/2026",
             "approvedOn": "06/08/2026", "isinCode": "BRPETRACNOR9",
             "label": "DIVIDENDO", "lastDatePrior": "21/08/2026", "remarks": ""},
        ],
        "stockDividends": [],
        "subscriptions": [],
    }],
    "BBAS": [{
        "code": "BBAS", "codeCVM": "1023", "tradingName": "BRASIL",
        "cashDividends": [
            {"assetIssued": "BRBBASACNOR3", "paymentDate": "30/09/2026",
             "rate": "0,08130019210", "relatedTo": "3º Trimestre/2026",
             "approvedOn": "12/08/2026", "isinCode": "BRBBASACNOR3",
             "label": "JRS CAP PROPRIO", "lastDatePrior": "22/08/2026",
             "remarks": ""},
        ],
        "stockDividends": [
            {"assetIssued": "BRBBASACNOR3", "factor": "5,00000000000",
             "approvedOn": "22/12/2025", "isinCode": "BRBBASACNOR3",
             "label": "BONIFICACAO", "lastDatePrior": "29/12/2025",
             "remarks": ""},
        ],
        "subscriptions": [],
    }],
    "VALE": [{
        "code": "VALE", "codeCVM": "4170", "tradingName": "VALE",
        "cashDividends": [], "stockDividends": [], "subscriptions": [],
    }],
}

LISTADAS = [
    {"codeCVM": 9512, "issuingCompany": "PETR", "companyName": "PETROBRAS",
     "segment": "NM", "market": "", "dateListing": "2000-08-09"},
    {"codeCVM": 1023, "issuingCompany": "BBAS", "companyName": "BANCO DO BRASIL",
     "segment": "NM", "market": "", "dateListing": "1976-06-15"},
    {"codeCVM": 4170, "issuingCompany": "VALE", "companyName": "VALE",
     "segment": "NM", "market": "", "dateListing": "2002-03-01"},
]


def falso_baixar(chamadas: list[str] | None = None):
    """A API de listadas inteira: o endpoint está na URL, o pedido em base64."""
    def _baixar(url: str, cabecalhos=None) -> bytes:
        if chamadas is not None:
            chamadas.append(url)
        pedido = json.loads(base64.b64decode(url.rsplit("/", 1)[-1]))
        if "GetInitialCompanies" in url:
            pagina = int(pedido["pageNumber"])
            inicio = (pagina - 1) * 100
            return json.dumps({
                "page": {"totalPages": 1, "totalRecords": len(LISTADAS)},
                "results": LISTADAS[inicio:inicio + 100],
            }).encode()
        if "GetListedSupplementCompany" in url:
            corpo = SUPLEMENTOS.get(pedido["issuingCompany"], [])
            # Duplamente codificado, como a B3 responde de verdade.
            return json.dumps(json.dumps(corpo, ensure_ascii=False)).encode()
        raise AssertionError(f"endpoint não previsto: {url}")
    return _baixar


@pytest.fixture()
def com_listadas(sink_cvm):
    res = ingestao.executar(sink_cvm, "b3_listadas", "atual",
                            baixar=falso_baixar())
    assert res.status == "publicado", res.erro
    return sink_cvm


# --------------------------------------------------------------------------
# As peças do motor, isoladas
# --------------------------------------------------------------------------
def test_item_entra_no_modelo_da_url():
    url = paginacao.montar_url(
        "https://x/{parametros}",
        {"modelo": {"issuingCompany": "{item}", "language": "pt-br"}},
        pagina=1, item="PETR",
    )
    pedido = json.loads(base64.b64decode(url.rsplit("/", 1)[-1]))
    assert pedido["issuingCompany"] == "PETR"


def test_captura_itera_os_itens_no_mesmo_bronze():
    chamadas: list[str] = []
    payload = paginacao.capturar(
        "https://x/GetListedSupplementCompany/{parametros}",
        {"modelo": {"issuingCompany": "{item}", "language": "pt-br"}},
        falso_baixar(chamadas), pausa=0, itens=["PETR", "BBAS", "VALE"],
    )
    assert len(chamadas) == 3, "uma chamada por companhia"
    guardado = json.loads(payload)
    assert len(guardado["paginas"]) == 3
    # O bronze guarda o que veio: a string duplamente codificada, sem decidir
    # o que ela significa — decidir é leitura.
    assert all(isinstance(p, str) for p in guardado["paginas"])


def test_leitura_desencapsula_e_herda_do_pai():
    payload = paginacao.capturar(
        "https://x/GetListedSupplementCompany/{parametros}",
        {"modelo": {"issuingCompany": "{item}"}},
        falso_baixar(), pausa=0, itens=["BBAS"],
    )
    registros = paginacao.registros_do_bronze(
        payload, "cashDividends", herdar={"cd_cvm": "codeCVM", "raiz": "code"},
    )
    assert len(registros) == 1
    assert registros[0]["cd_cvm"] == "1023", "o codeCVM desceu do pai"
    assert registros[0]["raiz"] == "BBAS"
    assert registros[0]["label"] == "JRS CAP PROPRIO"


def test_companhia_sem_resposta_nao_derruba_as_outras():
    """Descoberto na primeira carga real: das ~350 listadas, alguma responde
    corpo vazio ou não-JSON — e a captura inteira morria por causa de uma.
    Sem paginação declarada, a resposta entra crua no bronze e a leitura a
    pula; as outras companhias seguem."""
    def _baixar(url, cabecalhos=None):
        pedido = json.loads(base64.b64decode(url.rsplit("/", 1)[-1]))
        alvo = pedido["issuingCompany"]
        if alvo == "MORT":
            return b""
        if alvo == "HTML":
            return b"<html>erro 500 da fonte</html>"
        corpo = SUPLEMENTOS.get(alvo, [])
        return json.dumps(json.dumps(corpo, ensure_ascii=False)).encode()

    payload = paginacao.capturar(
        "https://x/GetListedSupplementCompany/{parametros}",
        {"modelo": {"issuingCompany": "{item}"}},
        _baixar, pausa=0, itens=["PETR", "MORT", "HTML", "BBAS"],
    )
    assert len(json.loads(payload)["paginas"]) == 4, "tudo guardado, como veio"
    registros = paginacao.registros_do_bronze(
        payload, "cashDividends", herdar={"cd_cvm": "codeCVM"},
    )
    # PETR tem 2, BBAS tem 1; as páginas mortas foram puladas na leitura.
    assert len(registros) == 3


def test_fonte_paginada_com_resposta_nao_json_falha_alto():
    """Com paginação declarada não há tolerância: sem JSON não dá para contar
    páginas, e adivinhar seria pior que parar."""
    def _baixar(url, cabecalhos=None):
        return b"<html>erro</html>"

    with pytest.raises(paginacao.ErroPaginacao, match="não-JSON"):
        paginacao.capturar(
            "https://x/{parametros}",
            {"modelo": {"pageNumber": "{pagina}"},
             "paginacao": {"caminho_total_paginas": "page.totalPages"}},
            _baixar, pausa=0,
        )


# --------------------------------------------------------------------------
# O ciclo inteiro
# --------------------------------------------------------------------------
def test_proventos_atravessam_o_ciclo_inteiro(com_listadas):
    res = ingestao.executar(com_listadas, "b3_proventos_dinheiro", "2026-08-26",
                            baixar=falso_baixar())
    assert res.status == "publicado", res.erro
    assert res.linhas_silver == 3, "duas parcelas PETR + um JCP BBAS"

    linhas = com_listadas.consultar(
        "SELECT cd_cvm, ticker_raiz, isin, tipo_evento, valor, dt_pagamento "
        "FROM fato_provento ORDER BY cd_cvm, dt_pagamento")
    assert [l["cd_cvm"] for l in linhas] == [1023, 9512, 9512]
    assert linhas[1]["valor"] == pytest.approx(0.67407131)
    assert linhas[1]["dt_pagamento"] == "2026-11-23", "dd/MM/yyyy convertida"
    assert linhas[0]["ticker_raiz"] == "BBAS", "herdado do pai da resposta"


def test_parcelas_da_mesma_aprovacao_nao_colidem(com_listadas):
    """O caso que definiu a identidade: mesma aprovação, mesmo ISIN, mesmo
    tipo — só a data de pagamento separa. Sem ela na chave, a segunda parcela
    sobrescreveria a primeira em silêncio."""
    ingestao.executar(com_listadas, "b3_proventos_dinheiro", "2026-08-26",
                      baixar=falso_baixar())
    petr = com_listadas.consultar(
        "SELECT discriminante, valor FROM fato_provento "
        "WHERE cd_cvm = 9512 ORDER BY discriminante")
    assert len(petr) == 2
    assert petr[0]["discriminante"] != petr[1]["discriminante"]


def test_recarga_e_idempotente(com_listadas):
    ingestao.executar(com_listadas, "b3_proventos_dinheiro", "2026-08-26",
                      baixar=falso_baixar())
    de_novo = ingestao.executar(com_listadas, "b3_proventos_dinheiro",
                                "2026-08-26", baixar=falso_baixar())
    assert de_novo.status == "publicado"
    total = com_listadas.um("SELECT count(*) AS n FROM fato_provento")["n"]
    assert total == 3, "mesmos eventos, mesmas linhas — upsert pela identidade"


def test_eventos_em_acoes_entram_pelo_proprio_recorte(com_listadas):
    res = ingestao.executar(com_listadas, "b3_proventos_acoes", "2026-08-26",
                            baixar=falso_baixar())
    assert res.status == "publicado", res.erro
    linhas = com_listadas.consultar(
        "SELECT tipo_evento, fator, dt_pagamento, discriminante "
        "FROM fato_provento WHERE origem_dataset = 'b3_proventos_acoes'")
    assert len(linhas) == 1
    assert linhas[0]["tipo_evento"] == "BONIFICACAO"
    assert linhas[0]["fator"] == pytest.approx(5.0)
    assert linhas[0]["dt_pagamento"] is None, "bonificação não paga em dinheiro"
    assert linhas[0]["discriminante"] == "5,00000000000", "o fator separa irmãos"


def test_gold_proventos_junta_os_dois_recortes(com_listadas):
    ingestao.executar(com_listadas, "b3_proventos_dinheiro", "2026-08-26",
                      baixar=falso_baixar())
    ingestao.executar(com_listadas, "b3_proventos_acoes", "2026-08-26",
                      baixar=falso_baixar())
    gold = com_listadas.consultar(
        "SELECT tipo_evento, valor, fator FROM gold_proventos ORDER BY tipo_evento")
    assert [g["tipo_evento"] for g in gold] == [
        "BONIFICACAO", "DIVIDENDO", "DIVIDENDO", "JRS CAP PROPRIO"]
    assert gold[0]["fator"] is not None and gold[0]["valor"] is None


def test_sem_listadas_carregadas_a_iteracao_falha_alto(sink_cvm):
    """Proventos dependem de saber quem está listado. Sem `dim_empresa`
    carregada a iteração não tem valores — e isso é erro com nome, não uma
    captura vazia fingindo sucesso."""
    with pytest.raises(ingestao.ErroIngestao, match="itera"):
        ingestao.executar(sink_cvm, "b3_proventos_dinheiro", "2026-08-26",
                          baixar=falso_baixar())
