"""O Banco Central como fonte, e o que ele obrigou o motor a aprender.

Esta é a primeira fonte que entrou depois de o produto prometer que fonte
nova é configuração. O critério de aceite foi literal — nenhuma linha em
`app/` sobre o BCB — e ele revelou três coisas que o motor ainda não sabia
fazer *genericamente*, todas descobertas por tentar:

1. uma API sem lugar para o número da página era buscada 500 vezes;
2. a janela da execução não chegava ao endereço de uma fonte JSON, então toda
   janela capturava a mesma resposta;
3. numa fonte de arquivo o contexto das pseudo-colunas vem do nome do arquivo,
   e numa API não vinha de lugar nenhum.

Os três consertos são de transporte, não de fonte: nada em `app/motor/` sabe
o que é o SGS. Os testes abaixo fixam isso.
"""
from __future__ import annotations

import json

import pytest

from app import repositorio as repo
from app.motor import ingestao, paginacao

# Como o SGS responde: um array na raiz, sem envelope e sem paginação.
SERIE_SELIC = [
    {"data": "01/01/2024", "valor": "11.75"},
    {"data": "01/02/2024", "valor": "11.25"},
    {"data": "01/03/2024", "valor": "10.75"},
]


def falso_sgs(chamadas: list[str], registros=None):
    """Responde por ano, como o SGS. Devolver o mesmo corpo para janelas
    diferentes faria a segunda captura virar no-op por `sha256` — o que é o
    comportamento certo do bronze, e tornaria o teste irreal."""
    def _baixar(url: str) -> bytes:
        chamadas.append(url)
        if registros is not None:
            return json.dumps(registros).encode()
        ano = url.split("dataInicial=01/01/")[1][:4] if "dataInicial" in url else "2024"
        return json.dumps([
            {**r, "data": r["data"][:6] + ano} for r in SERIE_SELIC
        ]).encode()
    return _baixar


def test_fonte_sem_pagina_e_buscada_uma_vez_so():
    """Sem esta guarda, a URL invariável seria buscada de novo a cada volta e
    o 'para quando vier vazio' nunca dispararia — o bronze terminaria com 500
    cópias da mesma resposta."""
    chamadas: list[str] = []
    payload = paginacao.capturar(
        "https://api.exemplo/serie/432", {}, falso_sgs(chamadas)
    )
    assert len(chamadas) == 1
    assert json.loads(payload)["paginas"] == [SERIE_SELIC]


def test_array_na_raiz_e_lido_sem_caminho_declarado():
    payload = json.dumps({"paginas": [SERIE_SELIC]}).encode()
    assert paginacao.registros_do_bronze(payload, None) == SERIE_SELIC


def test_a_janela_chega_ao_endereco_da_api(sink_cvm):
    """Uma série histórica recorta por ano no próprio endereço. Sem a janela na
    URL, 2023 e 2024 capturariam a mesma resposta e o `sha256` idêntico faria a
    segunda virar no-op — dado faltando, sem erro nenhum."""
    chamadas: list[str] = []
    ingestao.executar(sink_cvm, "bcb_selic_meta", "2024",
                      baixar=falso_sgs(chamadas), apenas_bronze=True)
    ingestao.executar(sink_cvm, "bcb_selic_meta", "2023",
                      baixar=falso_sgs(chamadas), apenas_bronze=True)

    assert "dataInicial=01/01/2024" in chamadas[0]
    assert "dataInicial=01/01/2023" in chamadas[1]
    # `bcdata.sgs.432` veio dos parâmetros do mapeamento, não do código.
    assert all("bcdata.sgs.432" in u for u in chamadas)


def test_parametros_do_mapeamento_viram_coluna(sink_cvm):
    """`$indicador` e `$unidade` não existem na resposta do SGS: vêm do que o
    mapeamento declara. É o mesmo mecanismo que tira `tipo_doc` do nome do
    arquivo — muda de onde o contexto vem, não como se declara."""
    res = ingestao.executar(sink_cvm, "bcb_ipca", "2024", baixar=falso_sgs([]))
    assert res.status == "publicado", res.erro

    linhas = sink_cvm.consultar(
        "SELECT indicador, unidade, dt_referencia, valor FROM fato_indicador "
        "ORDER BY dt_referencia"
    )
    assert {l["indicador"] for l in linhas} == {"ipca"}
    assert {l["unidade"] for l in linhas} == {"% a.m."}
    # dd/MM/yyyy do SGS vira ISO sem formato declarado — o conversor já cobria.
    assert linhas[0]["dt_referencia"] == "2024-01-01"
    assert linhas[0]["valor"] == pytest.approx(11.75)


def test_fonte_nova_atravessa_o_ciclo_ate_gold(sink_cvm):
    """O aceite da etapa: uma fonte que não existia chega a dado publicado."""
    res = ingestao.executar(sink_cvm, "bcb_selic_meta", "2024",
                            baixar=falso_sgs([]))
    assert res.status == "publicado", res.erro
    assert res.linhas_silver == 3

    em_gold = sink_cvm.consultar(
        "SELECT indicador, dt_referencia, valor, unidade FROM gold_indicadores "
        "ORDER BY dt_referencia"
    )
    assert len(em_gold) == 3
    assert em_gold[0]["unidade"] == "% a.a."


def test_valor_ilegivel_barra_a_publicacao(sink_cvm):
    """O SGS mudar o formato do número é falha silenciosa: `valor` vira nulo e
    a série fica cheia de buracos. A regra bloqueante existe para isso."""
    quebrado = [{"data": "01/01/2024", "valor": "11,75 %"}]
    res = ingestao.executar(sink_cvm, "bcb_selic_meta", "2024",
                            baixar=falso_sgs([], quebrado))
    assert res.status == "bloqueada"
    # A carga reprovada é descartada de silver: nada sem rótulo sobrevive ao
    # gate, então não há como o dado ruim vazar para o consumidor depois.
    assert sink_cvm.consultar("SELECT 1 FROM fato_indicador") == []
    # O arquivo original continua guardado. É o que permite corrigir a regra e
    # recomputar sem pedir nada de volta à fonte.
    bronze = sink_cvm.consultar(
        "SELECT sha256 FROM bronze_captura WHERE nome_arquivo LIKE 'bcb_%'")
    assert len(bronze) == 1


def test_nada_em_app_sabe_o_que_e_o_bcb():
    """A promessa do produto, verificada: fonte nova é linha em `cfg_*`, e o
    motor continua sem saber de quem é o dado que transporta."""
    from pathlib import Path

    raiz = Path(__file__).resolve().parents[1] / "app"
    ofensores = []
    for arq in raiz.rglob("*.py"):
        if arq.name == "seed_cvm.py":
            continue      # o seed é dado, e é a exceção declarada no CLAUDE.md
        corpo = arq.read_text(encoding="utf-8").lower()
        for termo in ("bcb", "sgs", "selic", "ipca"):
            if termo in corpo:
                ofensores.append(f"{arq.name}: {termo}")
    assert ofensores == [], "conhecimento de fonte vazou para o motor"
