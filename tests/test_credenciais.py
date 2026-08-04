"""Credencial de fonte: a configuração guarda a referência, o ambiente o valor.

`cfg_fonte.credencial_ref` existia desde a etapa 1 e nada a lia — o transporte
mandava só `User-Agent`. Na prática o motor não conseguia consumir nenhuma API
autenticada, e a primeira que apareceu expôs a falta.

O que estes testes fixam, além do caminho feliz: que o segredo não entra no
banco, que o erro nomeia a variável que falta, e que a URL gravada em bronze
sai censurada quando o modo é `query`.
"""
from __future__ import annotations

import json

import pytest

from app import repositorio as repo
from app.motor import credenciais, ingestao


def test_sem_credencial_a_fonte_continua_aberta():
    assert credenciais.declarada(None) is None
    assert credenciais.declarada("  ") is None
    assert credenciais.aplicar(None, "https://x/y") == ("https://x/y", {})


def test_nome_solto_significa_bearer(monkeypatch):
    """É o formato do brapi, e o mais comum: sem prefixo, é Bearer."""
    monkeypatch.setenv("TOKEN_TESTE", "abc123")
    url, cab = credenciais.aplicar("TOKEN_TESTE", "https://brapi.dev/api/quote/list")
    assert url == "https://brapi.dev/api/quote/list"
    assert cab == {"Authorization": "Bearer abc123"}


def test_cabecalho_nomeado(monkeypatch):
    monkeypatch.setenv("OUTRO", "s3gr3d0")
    url, cab = credenciais.aplicar("header:X-API-Key:OUTRO", "https://x/y")
    assert cab == {"X-API-Key": "s3gr3d0"}
    assert url == "https://x/y"


def test_query_acrescenta_ao_endereco_existente(monkeypatch):
    monkeypatch.setenv("Q", "v")
    url, cab = credenciais.aplicar("query:token:Q", "https://x/y?a=1")
    assert url == "https://x/y?a=1&token=v"
    assert cab == {}


def test_variavel_ausente_nomeia_qual_falta(monkeypatch):
    """Uma carga que falha por token ausente precisa dizer *qual* token, senão
    o operador procura no lugar errado."""
    monkeypatch.delenv("NAO_DEFINIDA", raising=False)
    with pytest.raises(credenciais.ErroCredencial, match="NAO_DEFINIDA"):
        credenciais.aplicar("NAO_DEFINIDA", "https://x/y")


def test_sintaxe_desconhecida_e_recusada_com_as_opcoes():
    with pytest.raises(credenciais.ErroCredencial, match="bearer:VARIAVEL"):
        credenciais.declarada("mágico:demais:para:isto:aqui")


def test_query_e_censurada_no_que_fica_guardado(monkeypatch):
    """No modo `query` o segredo está no endereço, e o endereço vai para
    `bronze_captura.url` e para o log — os dois lugares que alguém lê depois."""
    monkeypatch.setenv("Q", "s3gr3d0")
    url, _ = credenciais.aplicar("query:token:Q", "https://x/y")
    assert "s3gr3d0" in url
    assert credenciais.censurar(url, "query:token:Q") == "https://x/y?token=***"
    # No modo cabeçalho não há o que censurar: o segredo nunca esteve na URL.
    assert credenciais.censurar("https://x/y", "Q") == "https://x/y"


def test_presenca_nao_devolve_o_valor(monkeypatch):
    monkeypatch.setenv("PRESENTE", "x")
    monkeypatch.delenv("AUSENTE", raising=False)
    assert credenciais.presente("PRESENTE") is True
    assert credenciais.presente("AUSENTE") is False
    assert credenciais.presente(None) is True


def test_a_ingestao_manda_o_cabecalho_da_fonte(sink_cvm, monkeypatch):
    """O caminho inteiro: fonte declara variável, ambiente tem o valor, e o
    baixador recebe o cabeçalho — sem que o transporte saiba de quem é o dado."""
    monkeypatch.setenv("TOKEN_FALSO", "tok-123")
    repo.salvar_fonte(sink_cvm, repo.Fonte(
        chave="bcb", nome="BCB com token", tipo_transporte="http_json",
        url_template=(
            "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{serie}/dados"
            "?formato=json&dataInicial=01/01/{ano}&dataFinal=31/12/{ano}"
        ),
        encoding="utf-8", credencial_ref="TOKEN_FALSO",
    ), autor="teste")

    vistos: list[dict] = []

    def falso(url: str, cabecalhos=None) -> bytes:
        vistos.append(cabecalhos or {})
        return json.dumps([{"data": "01/01/2024", "valor": "11.75"}]).encode()

    ingestao.executar(sink_cvm, "bcb_selic_meta", "2024",
                      baixar=falso, apenas_bronze=True)
    assert vistos and vistos[0] == {"Authorization": "Bearer tok-123"}


def test_token_ausente_interrompe_a_carga_nomeando_a_variavel(sink_cvm, monkeypatch):
    monkeypatch.delenv("TOKEN_FALSO", raising=False)
    repo.salvar_fonte(sink_cvm, repo.Fonte(
        chave="bcb", nome="BCB com token", tipo_transporte="http_json",
        url_template="https://api.bcb.gov.br/dados/serie/bcdata.sgs.{serie}/dados",
        encoding="utf-8", credencial_ref="TOKEN_FALSO",
    ), autor="teste")

    # A execução registra a falha e relança: quem chamou decide o que fazer,
    # e o log guarda o motivo com o nome da variável.
    with pytest.raises(credenciais.ErroCredencial, match="TOKEN_FALSO"):
        ingestao.executar(sink_cvm, "bcb_selic_meta", "2024",
                          baixar=lambda u, cabecalhos=None: b"[]")

    ultima = sink_cvm.um(
        "SELECT status, erro FROM log_execucao "
        "WHERE dataset_chave = 'bcb_selic_meta' ORDER BY id DESC"
    )
    assert ultima["status"] == "falha"
    assert "TOKEN_FALSO" in ultima["erro"]


def test_nenhum_segredo_no_que_o_seed_grava(sink_cvm):
    """A fonte do brapi é cadastrada com o *nome* da variável, não com o token.
    Se algum dia alguém colar o valor aqui, este teste continua passando — mas
    o que ele fixa é a forma esperada, e a forma é um identificador."""
    fonte = repo.fonte_vigente(sink_cvm, "brapi")
    assert fonte is not None, "a fonte brapi é cadastrada pelo seed"
    assert fonte["credencial_ref"] == "BRAPI_TOKEN"
    cred = credenciais.declarada(fonte["credencial_ref"])
    assert cred.modo == "bearer" and cred.variavel == "BRAPI_TOKEN"
    # Um identificador de ambiente: maiúsculas, dígitos e sublinhado.
    assert cred.variavel.replace("_", "").isalnum()
