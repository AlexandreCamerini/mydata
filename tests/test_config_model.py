"""Fase 1 — modelo de configuração: migrações, versionamento e validação."""
from __future__ import annotations

import pytest

from app import migracoes, repositorio as repo
from app.repositorio import (
    CampoCalculado, Coluna, Dataset, ErroConfiguracao, Fonte, RegraQualidade,
)
from app.sinks import SinkDuckDB, qmark_para_pyformat


@pytest.fixture()
def sink():
    s = SinkDuckDB(":memory:")
    migracoes.aplicar(s)
    yield s
    s.fechar()


def fonte_exemplo() -> Fonte:
    return Fonte(
        chave="cvm",
        nome="CVM Dados Abertos",
        tipo_transporte="http_zip",
        url_template="https://exemplo/{tipo}_{ano}.zip",
        encoding="latin-1",
        separador=";",
    )


def dataset_exemplo(**over) -> Dataset:
    base = dict(
        chave="cvm_dfp",
        fonte_chave="cvm",
        nome="DFP",
        padrao_arquivo=r"^dfp_.*\.csv$",
        tabela_destino="fato_conta",
        chave_natural=["cd_cvm", "dt_refer", "cd_conta"],
        colunas=[
            Coluna("CD_CVM", "cd_cvm", "inteiro", obrigatoria=True),
            Coluna("DT_REFER", "dt_refer", "data", "data_iso", obrigatoria=True),
            Coluna("CD_CONTA", "cd_conta", "texto", obrigatoria=True),
            Coluna("VL_CONTA", "vl_conta", "numero", "decimal_ptbr"),
            Coluna("ESCALA_MOEDA", "escala_moeda", "texto"),
            Coluna("VERSAO", "versao", "inteiro"),
            Coluna("TIPO_DOC", "tipo_doc", "texto"),
        ],
        calculados=[
            CampoCalculado(
                nome="vl_conta_norm",
                expressao="vl_conta * CASE upper(escala_moeda) "
                          "WHEN 'MIL' THEN 1000 WHEN 'MILHAO' THEN 1000000 ELSE 1 END",
                colunas_origem=["vl_conta", "escala_moeda"],
                ordem=1,
            ),
        ],
        regras=[
            RegraQualidade(
                nome="sem_valor_nulo",
                expressao_sql="SELECT 1 FROM fato_conta WHERE vl_conta IS NULL "
                              "AND vl_conta_txt IS NOT NULL",
                severidade="alerta",
            ),
        ],
    )
    base.update(over)
    return Dataset(**base)


# --------------------------------------------------------------------------
# Migrações
# --------------------------------------------------------------------------
def _tabelas(sink) -> set[str]:
    return {
        r["table_name"]
        for r in sink.consultar(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'main'"
        )
    }


def test_migracoes_criam_a_infraestrutura(sink):
    esperadas = {
        "schema_migracao", "cfg_fonte", "cfg_dataset", "cfg_coluna",
        "cfg_campo_calculado", "cfg_regra_qualidade", "cfg_agendamento",
        "cfg_chave_api", "uso_chave_api", "log_execucao", "bronze_captura",
        "cfg_classe", "cfg_atributo", "cfg_vista", "cfg_seed", "publicacao",
    }
    faltando = esperadas - _tabelas(sink)
    assert not faltando, f"faltando: {faltando}"


def test_migracao_nao_cria_tabela_de_classe(sink):
    """A propriedade central da Etapa 3.

    Enquanto `CREATE TABLE fato_conta` estiver numa migração, cadastrar uma
    classe nova pela interface exige deploy. A tabela de classe passa a vir
    de `motor.ddl`, a partir de `cfg_classe` — e o banco migrado e sem
    configuração não tem tabela de domínio nenhuma.
    """
    assert not ({"fato_conta", "dim_empresa"} & _tabelas(sink))


def test_tabela_de_classe_aparece_com_a_configuracao(sink):
    from app import seed_cvm

    seed_cvm.aplicar(sink)
    assert {"fato_conta", "dim_empresa"} <= _tabelas(sink)


def test_migracao_e_idempotente(sink):
    """Aplicar duas vezes na mesma base não gera erro nem duplicata."""
    antes = sink.consultar("SELECT nome FROM schema_migracao ORDER BY nome")
    novas = migracoes.aplicar(sink)
    depois = sink.consultar("SELECT nome FROM schema_migracao ORDER BY nome")
    assert novas == [], "segunda aplicação não deveria rodar nada"
    assert antes == depois


def test_terceira_aplicacao_tambem_e_no_op(sink):
    migracoes.aplicar(sink)
    assert migracoes.aplicar(sink) == []
    total = sink.um("SELECT count(*) AS n FROM schema_migracao")["n"]
    assert total == len(migracoes.MIGRACOES)


# --------------------------------------------------------------------------
# Versionamento
# --------------------------------------------------------------------------
def test_salvar_fonte_cria_versao_1(sink):
    repo.salvar_fonte(sink, fonte_exemplo())
    f = repo.fonte_vigente(sink, "cvm")
    assert f["versao"] == 1 and f["vigente"] is True


def test_editar_fonte_versiona_em_vez_de_sobrescrever(sink):
    repo.salvar_fonte(sink, fonte_exemplo())
    nova = fonte_exemplo()
    nova.encoding = "utf-8"
    repo.salvar_fonte(sink, nova)

    vigente = repo.fonte_vigente(sink, "cvm")
    assert vigente["versao"] == 2 and vigente["encoding"] == "utf-8"

    todas = sink.consultar("SELECT versao, vigente, encoding FROM cfg_fonte ORDER BY versao")
    assert len(todas) == 2, "a versão anterior tem de continuar no banco"
    assert todas[0]["encoding"] == "latin-1" and todas[0]["vigente"] is False


def test_apenas_um_vigente_por_chave_no_banco(sink):
    """A unicidade de vigente_chave é a garantia, não a disciplina do código."""
    repo.salvar_fonte(sink, fonte_exemplo())
    with pytest.raises(Exception):
        sink.executar(
            """INSERT INTO cfg_fonte (id, nome, tipo_transporte, url_template,
                 chave, versao, vigente, vigente_chave)
               VALUES (999,'pirata','http_zip','x','cvm',99,TRUE,'cvm')"""
        )


def test_dataset_versionado_como_agregado(sink):
    repo.salvar_fonte(sink, fonte_exemplo())
    id1 = repo.salvar_dataset(sink, dataset_exemplo())

    d2 = dataset_exemplo()
    d2.colunas.append(Coluna("DS_CONTA", "ds_conta", "texto"))
    id2 = repo.salvar_dataset(sink, d2)

    assert id1 != id2
    # Os filhos da versão antiga continuam apontando para ela.
    assert len(repo.colunas_do(sink, id1)) == 7
    assert len(repo.colunas_do(sink, id2)) == 8
    assert repo.dataset_vigente(sink, "cvm_dfp")["id"] == id2


def test_snapshot_registra_versao_da_config(sink):
    repo.salvar_fonte(sink, fonte_exemplo())
    ds_id = repo.salvar_dataset(sink, dataset_exemplo())
    exec_id = repo.abrir_execucao(sink, "cvm_dfp", ds_id, "2023")

    linha = sink.um("SELECT cfg_snapshot FROM log_execucao WHERE id = ?", (exec_id,))
    import json
    snap = json.loads(linha["cfg_snapshot"])
    assert snap["dataset"]["versao"] == 1
    assert snap["fonte"]["chave"] == "cvm"
    assert "vl_conta_norm" in [c["nome"] for c in snap["calculados"]]


# --------------------------------------------------------------------------
# Validação
# --------------------------------------------------------------------------
def test_campo_calculado_com_coluna_inexistente_e_rejeitado(sink):
    d = dataset_exemplo()
    d.calculados = [
        CampoCalculado("bobo", "col_que_nao_existe * 2", ["col_que_nao_existe"])
    ]
    with pytest.raises(ErroConfiguracao) as e:
        repo.salvar_dataset(sink, d)
    assert "col_que_nao_existe" in str(e.value), "a mensagem precisa nomear a coluna"


def test_campo_calculado_pode_referenciar_calculado_anterior(sink):
    repo.salvar_fonte(sink, fonte_exemplo())
    d = dataset_exemplo()
    d.calculados.append(
        CampoCalculado("dobro_norm", "vl_conta_norm * 2", ["vl_conta_norm"], ordem=2)
    )
    assert repo.salvar_dataset(sink, d) > 0


def test_campo_de_janela_exige_particao(sink):
    d = dataset_exemplo()
    d.calculados = [
        CampoCalculado("is_latest", "versao = max(versao)", ["versao"], classe="janela")
    ]
    with pytest.raises(ErroConfiguracao) as e:
        repo.salvar_dataset(sink, d)
    assert "particao_por" in str(e.value)


def test_chave_natural_precisa_existir(sink):
    d = dataset_exemplo(chave_natural=["cd_cvm", "coluna_fantasma"])
    with pytest.raises(ErroConfiguracao) as e:
        repo.salvar_dataset(sink, d)
    assert "coluna_fantasma" in str(e.value)


def test_dataset_sem_coluna_e_rejeitado(sink):
    with pytest.raises(ErroConfiguracao):
        repo.salvar_dataset(sink, dataset_exemplo(colunas=[], chave_natural=[]))


# --------------------------------------------------------------------------
# Tradução de placeholders (a parte chata que quebra silenciosamente)
# --------------------------------------------------------------------------
def test_qmark_preserva_interrogacao_dentro_de_literal():
    sql = "SELECT * FROM t WHERE a = ? AND b = 'tem ? aqui' AND c = ?"
    assert qmark_para_pyformat(sql) == (
        "SELECT * FROM t WHERE a = %s AND b = 'tem ? aqui' AND c = %s"
    )


def test_qmark_escapa_porcento_literal():
    sql = "SELECT * FROM t WHERE nome LIKE 'a%' AND id = ?"
    assert qmark_para_pyformat(sql) == (
        "SELECT * FROM t WHERE nome LIKE 'a%' AND id = %s"
    )
