"""O contrato de opções: `/v1/cotacoes` e `/v1/opcoes`.

O consumidor recebe a cadeia com ativo-objeto resolvido, prazo, volatilidade
implícita e gregas — e a mesma proveniência das outras classes, porque é o
que distingue este hub de um agregador que republica sem dizer de onde veio.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import bootstrap, seed_fontes
from app.api import auth
from app.motor import ingestao
from app.sinks import SinkDuckDB
from tests.test_cotahist import ARQUIVO


@pytest.fixture()
def cliente_b3(tmp_path, monkeypatch):
    banco = str(tmp_path / "b3.duckdb")
    monkeypatch.setenv("PORTAL_DUCKDB", banco)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("PORTAL_ADMIN_TOKEN", raising=False)

    s = SinkDuckDB(banco)
    bootstrap.preparar(s)
    seed_fontes.aplicar(s)
    s.executar(
        "INSERT INTO fato_indicador (captura_id, fonte_arquivo, origem_dataset,"
        " indicador, dt_referencia, valor, unidade) VALUES (0,'manual','bcb_cdi',"
        " 'cdi', '2026-07-30', 10.40, '% a.a.')"
    )
    ingestao.executar(
        s, "b3_cotahist", "2026-07-31",
        baixar=lambda url, cabecalhos=None: ARQUIVO,
    )
    emitida = auth.emitir(s, "bolsia", quota_minuto=200, quota_dia=10_000)
    s.fechar()

    from app.api.main import app

    with TestClient(app) as c:
        c.headers.update({"X-API-Key": emitida.chave_completa})
        yield c


# --------------------------------------------------------------------------
# A cadeia
# --------------------------------------------------------------------------
def test_opcoes_do_ativo_objeto(cliente_b3):
    r = cliente_b3.get("/v1/opcoes/ABCB4")
    assert r.status_code == 200
    dados = r.json()["dados"]
    assert [d["contrato"] for d in dados] == ["ABCBH255"]
    linha = dados[0]
    assert linha["ticker_objeto"] == "ABCB4"
    assert linha["tipo"] == "CALL"
    assert linha["strike"] == pytest.approx(24.40)
    assert linha["dt_vencimento"] == "2026-08-21"
    assert linha["premio"] == pytest.approx(0.57)


def test_a_cadeia_traz_implicita_e_gregas(cliente_b3):
    linha = cliente_b3.get("/v1/opcoes/ABCB4").json()["dados"][0]
    assert 0 < linha["volatilidade_implicita"] < 5
    assert linha["preco_teorico"] == pytest.approx(linha["premio"], abs=1e-3)
    # Call tem delta entre 0 e 1; gama e vega são positivos; theta corrói.
    assert 0 <= linha["delta"] <= 1
    assert linha["gamma"] > 0 and linha["vega"] > 0
    assert linha["theta"] <= 0
    assert linha["prazo_anos"] == pytest.approx(15 / 252)


def test_cada_linha_carrega_proveniencia(cliente_b3):
    """Mesmo contrato das outras classes: sem isto, o produto vira o
    intermediário que ele existe para dispensar."""
    linha = cliente_b3.get("/v1/opcoes/ABCB4").json()["dados"][0]
    prov = linha["proveniencia"]
    assert prov["sha256"]
    assert prov["dt_captura"]
    assert prov["arquivo"].startswith("COTAHIST_D")
    assert prov["arquivo_em"].startswith("/v1/capturas/")


def test_filtra_por_vencimento_e_por_tipo(cliente_b3):
    assert cliente_b3.get(
        "/v1/opcoes/ABCB4?vencimento=2026-08-21").json()["dados"]
    assert cliente_b3.get(
        "/v1/opcoes/ABCB4?vencimento=2030-01-18").json()["dados"] == []
    assert cliente_b3.get("/v1/opcoes/ABCB4?tipo=PUT").json()["dados"] == []
    assert cliente_b3.get("/v1/opcoes/ABCB4?tipo=call").json()["dados"]


def test_papel_sem_opcao_devolve_lista_vazia(cliente_b3):
    """Vazio, não 404: a pergunta é legítima e a resposta é «não negociou»."""
    r = cliente_b3.get("/v1/opcoes/PETR4")
    assert r.status_code == 200 and r.json()["dados"] == []


def test_sem_pregao_vale_o_ultimo_daquele_papel(cliente_b3):
    """E não o último da base: um papel que parou de negociar devolveria
    vazio com corte global, o que pareceria falta de dado."""
    assert cliente_b3.get("/v1/opcoes/ABCB4").json()["dados"]
    assert cliente_b3.get("/v1/opcoes/ABCB4?pregao=2026-07-31").json()["dados"]
    assert cliente_b3.get("/v1/opcoes/ABCB4?pregao=2026-07-30").json()["dados"] == []


def test_vencimentos_resume_a_cadeia(cliente_b3):
    dados = cliente_b3.get("/v1/opcoes/ABCB4/vencimentos").json()["dados"]
    assert dados == [{
        "dt_vencimento": "2026-08-21", "contratos": 1,
        # `com_sigma` separa vencimento útil de vencimento morto: sem ele, um
        # vencimento cuja cadeia inteira saiu sem volatilidade parecia igual
        # aos outros até o consumidor abri-lo.
        "com_sigma": 1, "vence_no_pregao": 0,
        "menor_strike": pytest.approx(24.40), "maior_strike": pytest.approx(24.40),
    }]


def test_vencimento_do_proprio_pregao_se_anuncia(cliente_b3):
    """Prazo zero não tem sigma, e a lista precisa dizer isso antes do clique.

    Em 31/07/2026 eram 584 séries assim — 38% de tudo que aparecia sem
    volatilidade implícita, com a tela sugerindo defeito onde havia
    aritmética."""
    # A API e o teste falam com o mesmo banco; é o `app.state.sink` que a
    # fixture já abriu.
    from app.api.main import app

    # Prazo zero e sigma nulo andam juntos: é o que `bs_iv` produz quando não
    # há tempo até o vencimento. Zerar só o prazo montaria um estado que o
    # pipeline nunca gera, e o teste passaria a afirmar coisa que não existe.
    app.state.sink.executar(
        "UPDATE fato_negociacao SET dt_vencimento = dt_pregao, prazo_anos = 0, "
        "volatilidade_implicita = NULL WHERE tp_mercado IN ('070','080')"
    )
    dados = cliente_b3.get("/v1/opcoes/ABCB4/vencimentos").json()["dados"]
    assert dados and dados[0]["vence_no_pregao"] == 1
    assert dados[0]["com_sigma"] == 0


# --------------------------------------------------------------------------
# As cotações
# --------------------------------------------------------------------------
def test_cotacoes_do_lote_padrao(cliente_b3):
    dados = cliente_b3.get("/v1/cotacoes/PETR4").json()["dados"]
    assert len(dados) == 1
    assert dados[0]["preco_fechamento"] == pytest.approx(43.42)
    assert dados[0]["volume_financeiro"] == pytest.approx(1_084_118_619.0)


def test_cotacoes_nao_devolvem_opcao(cliente_b3):
    """`gold_cotacoes` é o recorte à vista. Contrato de opção aparecendo aqui
    misturaria prêmio com preço de ação na mesma série."""
    assert cliente_b3.get("/v1/cotacoes/ABCBH255").json()["dados"] == []


def test_cotacoes_filtram_por_data(cliente_b3):
    assert cliente_b3.get("/v1/cotacoes/PETR4?de=2026-08-01").json()["dados"] == []
    assert cliente_b3.get("/v1/cotacoes/PETR4?ate=2026-07-31").json()["dados"]


# --------------------------------------------------------------------------
# O porteiro
# --------------------------------------------------------------------------
def test_chave_sem_a_classe_no_escopo_nao_le_a_cadeia(cliente_b3, tmp_path):
    """Escopo por classe: um app novo é chave nova, não código novo."""
    from app.sinks import SinkDuckDB as S

    s = S(str(tmp_path / "b3.duckdb"))
    restrita = auth.emitir(s, "so_empresa", escopos="classe:empresa")
    s.fechar()
    r = cliente_b3.get(
        "/v1/opcoes/ABCB4", headers={"X-API-Key": restrita.chave_completa}
    )
    assert r.status_code == 403


def test_escopo_b3_bloqueia_rotas_e_campos_de_origem_b3(cliente_b3):
    """Ticker e segmento não atravessam uma vista sem a classe autorizada."""
    from app.api.main import app

    sem_empresa = auth.emitir(
        app.state.sink, "sem_empresa", escopos="classe:negociacao_b3"
    )
    sem_negociacao = auth.emitir(
        app.state.sink, "sem_negociacao", escopos="classe:empresa"
    )
    casos = [
        (sem_empresa, "/v1/empresas?q=PETR4", "empresa"),
        (sem_empresa, "/v1/empresas?segmento=NM", "empresa"),
        (sem_empresa, "/v1/empresas/9512", "empresa"),
        (sem_negociacao, "/v1/cotacoes/PETR4", "negociacao_b3"),
        (sem_negociacao, "/v1/opcoes/ABCB4", "negociacao_b3"),
        (sem_negociacao, "/v1/opcoes/ABCB4/vencimentos", "negociacao_b3"),
    ]

    for chave, rota, classe in casos:
        resposta = cliente_b3.get(rota, headers={"X-API-Key": chave.chave_completa})
        assert resposta.status_code == 403, (rota, resposta.text)
        corpo = resposta.json()["erro"]
        assert corpo["codigo"] == "escopo_insuficiente"
        assert classe in corpo["mensagem"]
        assert "ticker" not in resposta.text
        assert "segmento_listagem" not in resposta.text


def test_vencimentos_seguem_o_mesmo_pregao_da_cadeia(cliente_b3):
    """Sem isto a lista agrega o histórico inteiro e oferece vencimento já
    liquidado. Com trinta pregões carregados, PETR4 listava seis vencimentos
    vencidos antes do primeiro válido — e todos rotulados «vence hoje»,
    porque no dia deles o prazo era mesmo zero."""
    from app.api.main import app

    # Um segundo pregão, anterior, com um vencimento que só existia lá.
    app.state.sink.executar(
        "INSERT INTO fato_negociacao (captura_id, fonte_arquivo, origem_dataset, "
        " dt_pregao, codneg, tp_mercado, cod_bdi, prazo_termo, ticker_objeto, "
        " dt_vencimento, preco_exercicio, prazo_anos, publicado_em_versao) "
        "VALUES (0,'x','b3_cotahist','2026-07-30','ABCBG100','070','078','000',"
        " 'ABCB4','2026-07-30', 10.0, 0, 1)"
    )
    dados = cliente_b3.get("/v1/opcoes/ABCB4/vencimentos").json()["dados"]
    assert [d["dt_vencimento"] for d in dados] == ["2026-08-21"]
    # E pedindo o pregão antigo, ele aparece — o dado não sumiu, mudou o corte.
    antigo = cliente_b3.get(
        "/v1/opcoes/ABCB4/vencimentos?pregao=2026-07-30").json()["dados"]
    assert [d["dt_vencimento"] for d in antigo] == ["2026-07-30"]
    assert antigo[0]["vence_no_pregao"] == 1


def test_cadeia_traz_estilo_de_exercicio(cliente_b3):
    """O que o COTAHIST não publica, e é a razão do ADR-20.

    Sem o cadastro carregado a coluna vem nula e a cadeia continua
    respondendo: `LEFT JOIN`, não `JOIN`. A ausência de uma fonte auxiliar
    não pode apagar a classe principal."""
    linha = cliente_b3.get("/v1/opcoes/ABCB4").json()["dados"][0]
    assert "estilo_exercicio" in linha
    assert linha["estilo_exercicio"] is None
    assert linha["strike_cadastro"] is None


def test_com_o_cadastro_o_estilo_aparece(cliente_b3):
    from app.api.main import app
    from app.motor import ingestao
    from tests.test_instrumentos import arquivo, baixador

    ingestao.executar(app.state.sink, "b3_instrumentos", "2026-08-04",
                      baixar=baixador(arquivo()))
    linha = cliente_b3.get("/v1/opcoes/ABCB4").json()["dados"][0]
    assert linha["contrato"] == "ABCBH255"
    assert linha["estilo_exercicio"] == "AMER"
    # O strike do cadastro entra ao lado do que veio do pregão, não no lugar.
    assert linha["strike"] == pytest.approx(24.40)
    assert linha["strike_cadastro"] == pytest.approx(24.40)


def test_travessia_declarada_liga_pregao_e_cadastro(cliente_b3):
    """A correlação existe para o consumidor não reinventar a junção."""
    corrs = cliente_b3.get("/v1/meta/correlacoes").json()["dados"]
    nossa = next(c for c in corrs if c["chave"] == "negociacao_cadastro")
    assert nossa["origem"] == "negociacao_b3"
    assert nossa["destino"] == "instrumento_b3"
    assert nossa["por"] == {"origem": "codneg", "destino": "ticker"}
