"""Etapa 1 — a classe de informação como espelho verificado.

Nesta etapa a classe não manda em nada: o motor continua lendo
`tabela_destino` e as tabelas continuam vindo da migração. O que os testes
garantem é que a configuração descreve fielmente o que existe no banco.

Sem essa garantia, a Etapa 2 entregaria um gerador que produz uma tabela
*parecida* com a que está em produção — e "parecida" é exatamente o defeito
que uma migração de modelo não pode ter.
"""
from __future__ import annotations

import pytest

from app import repositorio as repo
from app import seed_cvm
from app.motor import ddl


CLASSES_ESPERADAS = {"demonstracao_financeira": "fato_conta",
                     "empresa": "dim_empresa",
                     "indicador_macro": "fato_indicador",
                     "negociacao_b3": "fato_negociacao"}


def test_seed_cadastra_as_classes_da_cvm(sink_cvm):
    classes = {c["chave"]: c["tabela"] for c in repo.listar_classes(sink_cvm)}
    assert classes == CLASSES_ESPERADAS


@pytest.mark.parametrize("chave", sorted(CLASSES_ESPERADAS))
def test_classe_declarada_bate_com_a_tabela_fisica(sink_cvm, chave):
    """O teste central da etapa. Qualquer coluna a mais ou a menos falha aqui,
    antes de a configuração ganhar poder sobre o banco."""
    classe = repo.classe_vigente(sink_cvm, chave)
    atributos = repo.atributos_de(sink_cvm, classe["id"])
    assert ddl.divergencias(sink_cvm, classe, atributos) == []


@pytest.mark.parametrize("chave", sorted(CLASSES_ESPERADAS))
def test_chave_de_identidade_e_a_chave_natural_do_dataset(sink_cvm, chave):
    """Identidade da classe e chave natural do dataset dizem a mesma coisa por
    ângulos diferentes; divergirem significa upsert num critério e resolução
    de duplicata em outro."""
    classe = repo.classe_vigente(sink_cvm, chave)
    identidade = classe["chave_identidade"].split(",")
    for ds in repo.datasets_da_classe(sink_cvm, chave):
        assert ds["chave_natural"].split(",") == identidade, ds["chave"]


def test_todo_dataset_aponta_para_uma_classe(sink_cvm):
    orfaos = [d["chave"] for d in repo.listar_datasets(sink_cvm)
              if not d["classe_chave"]]
    assert orfaos == []


def test_atributo_calculado_tem_campo_calculado_correspondente(sink_cvm):
    """Atributo marcado como calculado sem catálogo que o produza é coluna que
    nasce nula para sempre."""
    classe = repo.classe_vigente(sink_cvm, "demonstracao_financeira")
    calculados = {a["nome"] for a in repo.atributos_de(sink_cvm, classe["id"])
                  if a["origem"] == "calculado"}
    ds = repo.dataset_vigente(sink_cvm, "cvm_dfp")
    produzidos = {c["nome"] for c in repo.calculados_do(sink_cvm, ds["id"])}
    assert calculados == produzidos


def test_atributo_de_fonte_tem_coluna_que_o_alimenta(sink_cvm):
    classe = repo.classe_vigente(sink_cvm, "demonstracao_financeira")
    de_fonte = {a["nome"] for a in repo.atributos_de(sink_cvm, classe["id"])
                if a["origem"] == "fonte"}
    ds = repo.dataset_vigente(sink_cvm, "cvm_dfp")
    mapeados = {c["nome_destino"] for c in repo.colunas_do(sink_cvm, ds["id"])}
    assert de_fonte - mapeados == set()


# --------------------------------------------------------------------------
# Validação
# --------------------------------------------------------------------------
def test_classe_sem_chave_de_identidade_e_recusada():
    with pytest.raises(repo.ErroConfiguracao, match="chave de identidade"):
        repo.validar_classe(repo.Classe(
            chave="x", nome="X", tabela="tab_x", chave_identidade=[],
            atributos=[repo.Atributo("a")],
        ))


def test_identidade_que_cita_atributo_inexistente_e_recusada():
    with pytest.raises(repo.ErroConfiguracao, match="inexistente"):
        repo.validar_classe(repo.Classe(
            chave="x", nome="X", tabela="tab_x", chave_identidade=["b"],
            atributos=[repo.Atributo("a")],
        ))


def test_atributo_repetido_e_recusado():
    with pytest.raises(repo.ErroConfiguracao, match="repetido"):
        repo.validar_classe(repo.Classe(
            chave="x", nome="X", tabela="tab_x", chave_identidade=["a"],
            atributos=[repo.Atributo("a"), repo.Atributo("a")],
        ))


def test_nome_de_tabela_com_injecao_e_recusado():
    """O nome da tabela entra em DDL por interpolação — não há parâmetro para
    identificador. A validação é a única barreira."""
    with pytest.raises(repo.ErroConfiguracao, match="tabela"):
        repo.validar_classe(repo.Classe(
            chave="x", nome="X", tabela="x; DROP TABLE fato_conta",
            chave_identidade=["a"], atributos=[repo.Atributo("a")],
        ))


def test_tipo_desconhecido_e_recusado():
    with pytest.raises(repo.ErroConfiguracao, match="tipo desconhecido"):
        repo.validar_classe(repo.Classe(
            chave="x", nome="X", tabela="tab_x", chave_identidade=["a"],
            atributos=[repo.Atributo("a", tipo="jsonb")],
        ))


# --------------------------------------------------------------------------
# Versionamento
# --------------------------------------------------------------------------
def test_salvar_classe_versiona_em_vez_de_editar(sink_cvm):
    antes = repo.classe_vigente(sink_cvm, "empresa")
    nova = repo.Classe(
        chave="empresa", nome="Empresa (revisada)", tabela="dim_empresa",
        chave_identidade=["cd_cvm"],
        atributos=[repo.Atributo("cd_cvm", "inteiro")],
    )
    repo.salvar_classe(sink_cvm, nova)
    depois = repo.classe_vigente(sink_cvm, "empresa")
    assert depois["versao"] == antes["versao"] + 1
    assert depois["nome"] == "Empresa (revisada)"
    # A versão anterior continua no banco, aposentada.
    todas = sink_cvm.consultar(
        "SELECT versao, vigente FROM cfg_classe WHERE chave = 'empresa' "
        "ORDER BY versao"
    )
    assert [t["vigente"] for t in todas] == [False, True]


def test_atributos_seguem_a_versao_do_pai(sink_cvm):
    """Como no dataset: filho aponta para a versão, não para a chave. Uma
    execução antiga continua enxergando a classe sob a qual rodou."""
    antiga = repo.classe_vigente(sink_cvm, "empresa")
    repo.salvar_classe(sink_cvm, repo.Classe(
        chave="empresa", nome="Empresa", tabela="dim_empresa",
        chave_identidade=["cd_cvm"],
        atributos=[repo.Atributo("cd_cvm", "inteiro")],
    ))
    nova = repo.classe_vigente(sink_cvm, "empresa")
    assert len(repo.atributos_de(sink_cvm, antiga["id"])) == len(
        seed_cvm.CLASSE_EMPRESA.atributos)
    assert len(repo.atributos_de(sink_cvm, nova["id"])) == 1


# --------------------------------------------------------------------------
# Colunas de sistema
# --------------------------------------------------------------------------
def test_colunas_de_sistema_entram_sem_serem_declaradas(sink_cvm):
    classe = repo.classe_vigente(sink_cvm, "empresa")
    colunas = dict(ddl.colunas_da_classe(repo.atributos_de(sink_cvm, classe["id"])))
    assert {"captura_id", "fonte_arquivo", "carregado_em",
            "publicado_em_versao"} <= set(colunas)


def test_guarda_texto_gera_a_coluna_sombra(sink_cvm):
    classe = repo.classe_vigente(sink_cvm, "demonstracao_financeira")
    colunas = dict(ddl.colunas_da_classe(repo.atributos_de(sink_cvm, classe["id"])))
    assert "vl_conta_txt" in colunas
    assert "cd_cvm_txt" not in colunas, "sombra é opt-in, não automática"
