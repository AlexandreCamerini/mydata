"""Etapa 3 — a virada: configuração assume o lugar do código.

Depois desta etapa não existe mais nome de tabela nem corpo de vista escritos
em Python. O que os testes precisam garantir é que a troca é invisível: os
mesmos dados, as mesmas respostas, e uma base já existente atravessa a
migração sem perder nada.
"""
from __future__ import annotations

import pytest

from app import bootstrap, migracoes, repositorio as repo, seed_fontes
from app.motor import ingestao, publicacao, verificacao
from app.sinks import SinkDuckDB, render


def baixador(mapa):
    return lambda url: next(v for k, v in mapa.items() if k in url)


# --------------------------------------------------------------------------
# O código deixou de saber o nome das coisas
# --------------------------------------------------------------------------
def test_publicacao_nao_tem_nome_de_tabela_nem_de_vista_escrito(sink_cvm):
    """Se `publicacao.py` voltar a citar `fato_conta` ou `gold_*`, publicar
    uma classe nova volta a exigir deploy."""
    from pathlib import Path

    fonte = Path(publicacao.__file__).read_text()
    corpo = fonte.split('"""', 2)[-1]   # fora da docstring do módulo
    for proibido in ("fato_conta", "dim_empresa", "gold_demonstracoes",
                     "gold_empresa", "gold_itr"):
        assert proibido not in corpo, f"'{proibido}' voltou para o código"


def test_vistas_vem_da_configuracao(sink_cvm):
    nomes = set(publicacao.vistas(sink_cvm))
    assert nomes == {"gold_demonstracoes", "gold_itr_trimestre",
                     "gold_indicadores", "gold_empresa",
                     "gold_cotacoes", "gold_opcoes"}
    repo.salvar_vista(sink_cvm, repo.Vista(
        chave="gold_empresa_sp", classe_chave="empresa",
        corpo="SELECT * FROM dim_empresa WHERE uf = 'SP' "
              "AND publicado_em_versao IS NOT NULL AND publicado_em_versao <= {V}",
    ))
    assert "gold_empresa_sp" in publicacao.vistas(sink_cvm)


def test_tabelas_publicaveis_vem_das_classes(sink_cvm):
    assert set(publicacao.tabelas_publicaveis(sink_cvm)) == {
        "fato_conta", "dim_empresa", "fato_indicador", "fato_negociacao",
        "dim_instrumento",
    }


def test_vista_sem_marcador_de_publicacao_e_recusada(sink_cvm):
    """Vista sem `{V}` não filtra por publicação: o gate de qualidade deixaria
    de existir para ela, em silêncio."""
    with pytest.raises(repo.ErroConfiguracao, match="{V}"):
        repo.salvar_vista(sink_cvm, repo.Vista(
            chave="gold_solta", classe_chave="empresa",
            corpo="SELECT * FROM dim_empresa",
        ))


# --------------------------------------------------------------------------
# Classe nova agora participa do ciclo inteiro
# --------------------------------------------------------------------------
def test_classe_nova_publica_em_gold_sem_editar_codigo(sink):
    """O que a Etapa 2 ainda não fazia: a classe nova era ingerível, mas o
    rótulo de publicação e a vista de gold ainda eram privilégio da CVM."""
    seed_fontes.aplicar(sink)
    repo.salvar_classe(sink, repo.Classe(
        chave="indicador_macro", nome="Indicador macroeconômico",
        tabela="fato_indicador_macro", chave_identidade=["serie", "competencia"],
        atributos=[
            repo.Atributo("serie", "texto", obrigatorio=True, ordem=1),
            repo.Atributo("competencia", "data", obrigatorio=True, ordem=2),
            repo.Atributo("valor", "numero", ordem=3),
        ],
    ))
    from app.motor import ddl

    ddl.garantir_classes(sink)
    repo.salvar_vista(sink, repo.Vista(
        chave="gold_indicador_macro", classe_chave="indicador_macro",
        corpo="SELECT serie, competencia, valor, publicado_em_versao "
              "FROM fato_indicador_macro WHERE publicado_em_versao IS NOT NULL "
              "AND publicado_em_versao <= {V}",
    ))

    sink.executar(
        "INSERT INTO fato_indicador_macro (captura_id, fonte_arquivo, serie, "
        "competencia, valor) VALUES (1, 'ipca.csv', 'ipca', '2026-06-01', 0.42)"
    )
    assert "fato_indicador_macro" in publicacao.tabelas_publicaveis(sink)

    publicacao.publicar(sink)
    linhas = sink.consultar("SELECT * FROM gold_indicador_macro")
    # `float()` porque o Postgres devolve Decimal para `numeric` e o DuckDB
    # devolve float para `double` — o mapeamento está em `sinks.TIPOS`. O que
    # o teste afirma é o valor, não o tipo Python que carrega o valor.
    assert len(linhas) == 1 and float(linhas[0]["valor"]) == 0.42


# --------------------------------------------------------------------------
# Base existente atravessa a virada
# --------------------------------------------------------------------------
def test_base_anterior_a_etapa_1_migra_sem_perder_dado(
    tmp_path, zip_dfp_2023, csv_cadastro
):
    """Simula a base do Railway: schema e dado do jeito que estavam antes das
    classes existirem. A migração roda por cima e a digital de gold tem de
    sair idêntica — nenhuma reingestão, só o bronze que já estava lá."""
    banco = str(tmp_path / "producao.duckdb")
    velho = SinkDuckDB(banco)

    # 1. Estado anterior: migrações até bronze + o DDL de silver como era.
    migracoes.aplicar(velho, ate="0004_silver_cvm")
    for sentenca in migracoes.DDL_HISTORICO_SILVER:
        velho.executar(render(sentenca, velho.dialeto))
    velho.executar("INSERT INTO schema_migracao (nome) VALUES ('0005_rotulo_de_publicacao')")
    velho.fechar()

    # 2. Sobe a versão nova e carrega dado, como o serviço faria.
    atual = SinkDuckDB(banco)
    bootstrap.preparar(atual)
    seed_fontes.aplicar(atual)
    ingestao.executar(atual, "cvm_dfp", "2023",
                      baixar=baixador({"dfp_cia_aberta_2023.zip": zip_dfp_2023}))
    ingestao.executar(atual, "cvm_cadastro", "atual",
                      baixar=baixador({"cad_cia_aberta.csv": csv_cadastro}))
    antes = verificacao.impressao_digital(atual)
    assert antes["gold_demonstracoes"]["linhas"] > 0

    # 3. A tabela que já existia continua sendo a mesma, e recomputar do
    #    bronze reproduz o estado — o plano de volta continua de pé.
    classe = repo.classe_vigente(atual, "demonstracao_financeira")
    from app.motor import ddl

    assert ddl.divergencias(atual, classe, repo.atributos_de(atual, classe["id"])) == []
    ingestao.recomputar_tudo(atual)
    assert verificacao.impressao_digital(atual) == antes
    atual.fechar()


def test_migrar_duas_vezes_nao_duplica_tabela_de_classe(tmp_path):
    banco = str(tmp_path / "duas.duckdb")
    s = SinkDuckDB(banco)
    bootstrap.preparar(s)
    seed_fontes.aplicar(s)
    colunas = sink_colunas = s.consultar(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'fato_conta'"
    )
    bootstrap.preparar(s)
    seed_fontes.aplicar(s)
    assert s.consultar(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'fato_conta'"
    ) == colunas
    s.fechar()


# --------------------------------------------------------------------------
# Seed idempotente
# --------------------------------------------------------------------------
def test_seed_repetido_nao_versiona_de_novo(sink):
    """O boot do Railway roda `migrar --seed`. Sem idempotência, cada deploy
    criaria uma versão nova de cada objeto de configuração."""
    assert seed_fontes.aplicar(sink) is True
    versoes = lambda: {                                            # noqa: E731
        c["chave"]: c["versao"] for c in repo.listar_classes(sink)
    }
    antes = versoes()
    assert seed_fontes.aplicar(sink) is False
    assert seed_fontes.aplicar(sink) is False
    assert versoes() == antes


def test_seed_forcado_versiona(sink):
    seed_fontes.aplicar(sink)
    antes = repo.classe_vigente(sink, "empresa")["versao"]
    assert seed_fontes.aplicar(sink, forcar=True) is True
    assert repo.classe_vigente(sink, "empresa")["versao"] == antes + 1


def test_seed_reaplica_quando_a_configuracao_muda(sink, monkeypatch):
    seed_fontes.aplicar(sink)
    monkeypatch.setattr(seed_fontes.CLASSE_EMPRESA, "descricao", "outra coisa")
    assert seed_fontes.aplicar(sink) is True


def test_seed_repara_tabela_ausente_mesmo_sem_mudanca(sink):
    """Configuração igual e tabela sumida: o deploy tem de recriar a tabela,
    não pular por o digest bater."""
    seed_fontes.aplicar(sink)
    sink.executar("DROP TABLE dim_empresa")
    assert seed_fontes.aplicar(sink) is False
    assert sink.consultar(
        "SELECT 1 AS ok FROM information_schema.tables "
        "WHERE table_name = 'dim_empresa'"
    )


def test_api_sem_configuracao_responde_503_e_nao_500(tmp_path, monkeypatch):
    """Deploy novo, banco migrado e ainda sem seed: o consumidor tem de
    receber uma indisponibilidade explicada, não um erro de relação ausente."""
    from fastapi.testclient import TestClient

    monkeypatch.setenv("PORTAL_DUCKDB", str(tmp_path / "vazio.duckdb"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("PORTAL_API_ABERTA", "1")
    from app.api.main import app

    with TestClient(app) as c:
        assert c.get("/health").status_code == 200
        r = c.get("/v1/empresas")
    assert r.status_code == 503
    assert r.json()["erro"]["codigo"] == "gold_indisponivel"


# --------------------------------------------------------------------------
# Recriar vista quando o conjunto de colunas muda
# --------------------------------------------------------------------------
def test_vista_e_recriada_quando_as_colunas_mudam(sink_cvm):
    """Classe que ganha atributo novo muda as colunas da vista. No Postgres,
    `CREATE OR REPLACE VIEW` recusa isso — foi como um deploy parou de subir
    depois que a B3 acrescentou `ticker` a `empresa`."""
    sink_cvm.executar("CREATE OR REPLACE VIEW v_teste AS SELECT 1 AS antigo")
    publicacao.definir_vista(sink_cvm, "v_teste", "SELECT 2 AS novo, 3 AS outro")
    linha = sink_cvm.um("SELECT * FROM v_teste")
    assert linha == {"novo": 2, "outro": 3}


def test_vista_recriada_quando_o_replace_e_recusado():
    """O caminho que só o Postgres percorre, provado sem Postgres: o sink
    finge a recusa e a vista tem de ser dropada e recriada.

    Sem isto o teste passaria em DuckDB — que aceita a substituição — e o
    defeito continuaria invisível fora de produção.
    """
    class SinkQueRecusaReplace:
        """Recusa CREATE OR REPLACE, como o Postgres faz quando as colunas
        mudam, e registra o que foi executado."""

        dialeto = "postgres"

        def __init__(self):
            self.executados: list[str] = []

        def executar(self, sql, params=()):
            self.executados.append(sql)
            if sql.startswith("CREATE OR REPLACE VIEW"):
                raise RuntimeError(
                    'cannot change name of view column "captura_id" to "ticker"'
                )

    sink = SinkQueRecusaReplace()
    publicacao.definir_vista(sink, "gold_empresa", "SELECT 1 AS ticker")

    assert sink.executados == [
        "CREATE OR REPLACE VIEW gold_empresa AS SELECT 1 AS ticker",
        "DROP VIEW IF EXISTS gold_empresa CASCADE",
        "CREATE VIEW gold_empresa AS SELECT 1 AS ticker",
    ]


def test_publicar_refaz_o_ponteiro_derrubado_pelo_cascade(sink_cvm, monkeypatch):
    """`gold_x` aponta para `gold_x_vN`; recriar a versionada com CASCADE
    derruba o ponteiro. A publicação tem de deixá-lo de pé no fim."""
    ingestao.executar(
        sink_cvm, "cvm_cadastro", "atual",
        baixar=lambda url: (
            "CNPJ_CIA;DENOM_SOCIAL;DENOM_COMERC;DT_REG;SETOR_ATIV;SIT;"
            "CONTROLE_ACIONARIO;UF;MUN;CD_CVM\n"
            "00.000.000/0001-00;TESTE S.A.;TESTE;1999-05-10;"
            "Petróleo e Gás;ATIVO;Estatal;RJ;RIO DE JANEIRO;9512\n"
        ).encode("latin-1"),
    )
    versao = publicacao.publicar(sink_cvm)
    for nome in publicacao.vistas(sink_cvm):
        assert sink_cvm.consultar(f"SELECT * FROM {nome} LIMIT 1") is not None
        assert sink_cvm.consultar(f"SELECT * FROM {nome}_v{versao} LIMIT 1") is not None
