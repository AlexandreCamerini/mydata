"""Correlação entre classes: declarada, executada com escopo, nunca inferida.

Enquanto a junção viver na consulta de quem consome, três coisas se perdem: o
escopo por classe da chave de API não enxerga a travessia, cada consumidor
reinventa a ligação, e ninguém consegue dizer como duas classes se ligam sem
ler o código de alguém.

O que estes testes fixam é o oposto disso — e a recusa vale tanto para a
travessia não declarada quanto para a chave que não alcança as duas pontas.
"""
from __future__ import annotations

import pytest

from app import repositorio as repo
from app.api import auth
from app.motor import correlacao


def test_correlacao_declarada_atravessa(cliente):
    """O aceite da etapa: a companhia com as contas que ela publicou, numa
    consulta só, sem o consumidor escrever junção nenhuma."""
    r = cliente.get(
        "/v1/correlacoes/empresa_demonstracoes",
        params={"campos": "cd_conta,ds_conta,vl_conta_norm,dt_refer",
                "onde": "grupo:BPA,cd_conta:1", "limite": 5},
    )
    assert r.status_code == 200, r.text
    corpo = r.json()

    assert corpo["correlacao"]["origem"]["classe"] == "empresa"
    assert corpo["correlacao"]["destino"]["classe"] == "demonstracao_financeira"
    assert corpo["correlacao"]["relacionamento"] == "um_para_muitos"

    linhas = corpo["dados"]
    assert linhas, "a fixture tem DFP de 2023 carregada"
    for l in linhas:
        assert l["destino_cd_conta"] == "1", "o filtro do destino valeu"
        assert l["destino_vl_conta_norm"] is not None
        assert l["cd_cvm"] is not None, "a origem veio junto"
        # Travessia é resposta de dado como qualquer outra, e sai com
        # proveniência — não com as colunas internas da vista.
        assert l["proveniencia"]["sha256"]
        assert "captura_id" not in l and "publicado_em_versao" not in l


def test_travessia_nao_declarada_e_recusada(cliente):
    """Como o Cube recusa com 'can't find join path': sem linha em
    `cfg_correlacao`, não há junção. Nunca se infere uma."""
    r = cliente.get("/v1/correlacoes/empresa_indicadores")
    assert r.status_code == 404
    assert r.json()["erro"]["codigo"] == "correlacao_nao_declarada"


def test_escopo_restrito_recebe_403_na_travessia(cliente):
    """A outra metade do aceite. A chave lê `empresa` e nada mais; a correlação
    alcança `demonstracao_financeira`, então a consulta é negada inteira — não
    servida com as colunas do destino omitidas em silêncio."""
    from conftest import sink_do_ambiente

    s = sink_do_ambiente()
    restrita = auth.emitir(s, "watchlist", escopos="classe:empresa")
    s.fechar()

    r = cliente.get(
        "/v1/correlacoes/empresa_demonstracoes",
        headers={"X-API-Key": restrita.chave_completa},
    )
    assert r.status_code == 403
    corpo = r.json()["erro"]
    assert corpo["codigo"] == "escopo_insuficiente"
    assert "demonstracao_financeira" in corpo["mensagem"]

    # E a mesma chave continua lendo o que é dela.
    assert cliente.get(
        "/v1/empresas", headers={"X-API-Key": restrita.chave_completa}
    ).status_code == 200


def test_catalogo_esconde_travessia_que_a_chave_nao_alcanca(cliente):
    """Anunciar uma correlação que a chave não pode executar é anunciar porta
    fechada."""
    from conftest import sink_do_ambiente

    s = sink_do_ambiente()
    restrita = auth.emitir(s, "watchlist2", escopos="classe:empresa")
    s.fechar()

    completa = cliente.get("/v1/meta/correlacoes").json()["dados"]
    assert [c["chave"] for c in completa] == [
        "empresa_demonstracoes", "negociacao_cadastro"]

    parcial = cliente.get(
        "/v1/meta/correlacoes", headers={"X-API-Key": restrita.chave_completa}
    ).json()["dados"]
    assert parcial == []


def test_coluna_inexistente_e_recusada_com_a_lista(cliente):
    """Nome de coluna nunca entra em SQL sem passar pelo que a vista tem de
    fato. A mensagem diz o que existe, para o erro ser acionável."""
    r = cliente.get(
        "/v1/correlacoes/empresa_demonstracoes",
        params={"campos": "vl_conta_norm; DROP TABLE fato_conta"},
    )
    assert r.status_code == 400
    assert r.json()["erro"]["codigo"] == "correlacao_invalida"
    assert "Disponíveis" in r.json()["erro"]["mensagem"]


def test_um_para_um_sobre_atributo_que_nao_e_identidade_e_recusado(sink_cvm):
    """A regra de fan-out do MetricFlow, na configuração em vez de na consulta:
    declarar `um_para_um` sobre atributo que não é a identidade do destino
    multiplicaria a linha de origem sem ninguém perceber."""
    with pytest.raises(repo.ErroConfiguracao, match="não é a identidade"):
        repo.salvar_correlacao(sink_cvm, repo.Correlacao(
            chave="empresa_conta_unica",
            classe_origem="empresa",
            classe_destino="demonstracao_financeira",
            atributo_origem="cd_cvm",
            atributo_destino="cd_cvm",
            relacionamento="um_para_um",
        ))


def test_atributo_que_a_classe_nao_declara_e_recusado(sink_cvm):
    with pytest.raises(repo.ErroConfiguracao, match="não declara o atributo"):
        repo.salvar_correlacao(sink_cvm, repo.Correlacao(
            chave="empresa_invencao",
            classe_origem="empresa",
            classe_destino="demonstracao_financeira",
            atributo_origem="nao_existe",
            atributo_destino="cd_cvm",
        ))


def test_correlacao_nova_nao_exige_deploy(sink_cvm):
    """A promessa do produto aplicada à correlação: declarar uma ligação nova é
    gravar configuração, e ela já responde."""
    repo.salvar_correlacao(sink_cvm, repo.Correlacao(
        chave="empresa_indicadores",
        classe_origem="empresa",
        classe_destino="indicador_macro",
        atributo_origem="cd_cvm",
        atributo_destino="dt_referencia",
        descricao="Ligação sem sentido de negócio; serve para provar que "
                  "declarar é o bastante para existir.",
    ))
    assert correlacao.classes_da(sink_cvm, "empresa_indicadores") == (
        "empresa", "indicador_macro"
    )


def test_gestao_reune_o_que_estava_em_cinco_rotas(cliente, monkeypatch):
    """A pergunta que o operador faz primeiro — "como está o sistema" — passa a
    ter uma resposta só, sem ele abrir o banco nem cinco telas."""
    monkeypatch.setenv("PORTAL_ADMIN_TOKEN", "Testes#12345#")
    r = cliente.get("/admin/api/gestao", headers={"X-Admin-Token": "Testes#12345#"})
    assert r.status_code == 200, r.text
    d = r.json()["dados"]

    por_classe = {c["chave"]: c for c in d["classes"]}
    assert {"empresa", "demonstracao_financeira"} <= set(por_classe)
    empresa = por_classe["empresa"]
    assert empresa["linhas"] > 0
    # A contagem sai da tabela física: a diferença para o publicado é o que o
    # gate reteve, e escondê-la faria carga reprovada parecer inexistente.
    assert empresa["retidas_no_gate"] == empresa["linhas"] - empresa["linhas_publicadas"]

    assert d["bronze"]["capturas"] >= 2 and d["bronze"]["bytes"] > 0
    assert any(c["consumidor"] == "bolsia" and c["ativa"] for c in d["consumidores"])
    assert [c["chave"] for c in d["correlacoes"]] == [
        "empresa_demonstracoes", "negociacao_cadastro"]
    # O BCB está configurado e nunca foi ingerido nesta fixture.
    assert "indicador_macro" in d["fora_do_sla"]
