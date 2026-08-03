"""Etapa 4 — duas fontes, uma informação.

O problema que o resto do plano não resolve: quando duas fontes descrevem a
mesma coisa e discordam, "agregar tudo num banco só" produz um número que
ninguém consegue defender. A decisão aqui é que resolver a divergência é
**derivação**, não sobrescrita — cada fonte grava as próprias linhas intactas
e a vista escolhe.

A consequência prática, e é ela que os testes verificam: mudar a precedência
é republicar, não recarregar. E remover uma fonte nunca destrói o que ela já
trouxe.

A divergência usada aqui é real e interna à CVM: o cadastro traz
`DENOM_SOCIAL` e o arquivo de DFP traz `DENOM_CIA` para a mesma companhia, e
os dois não coincidem.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import bootstrap, repositorio as repo, seed_cvm
from app.api import auth
from app.motor import ddl, ingestao, publicacao
from app.sinks import SinkDuckDB

from conftest import csv_conta, linha, zip_cvm


def baixador(mapa):
    def _baixar(url: str) -> bytes:
        for chave, dado in mapa.items():
            if chave in url:
                return dado
        raise AssertionError(f"URL não prevista: {url}")
    return _baixar


# A DFP chama a companhia de "PETROBRAS"; o cadastro, de
# "PETROLEO BRASILEIRO S.A. PETROBRAS". As duas estão certas no seu contexto.
DENOM_DFP = "PETROBRAS"
DENOM_CADASTRO = "PETROLEO BRASILEIRO S.A. PETROBRAS"


@pytest.fixture()
def zip_dfp() -> bytes:
    return zip_cvm({
        "dfp_cia_aberta_BPA_con_2023.csv": csv_conta([
            linha(cd_cvm=9512, denom=DENOM_DFP, cd_conta="1", vl="1000,00"),
        ]),
    })


@pytest.fixture()
def csv_cad() -> bytes:
    return (
        "CNPJ_CIA;DENOM_SOCIAL;DENOM_COMERC;DT_REG;SETOR_ATIV;SIT;"
        "CONTROLE_ACIONARIO;UF;MUN;CD_CVM\n"
        f"33.000.167/0001-01;{DENOM_CADASTRO};PETROBRAS;1977-05-10;"
        "Petróleo e Gás;ATIVO;Estatal;RJ;RIO DE JANEIRO;9512\n"
    ).encode("latin-1")


@pytest.fixture()
def carregado(sink_cvm, zip_dfp, csv_cad):
    """As duas fontes ingeridas na classe `empresa`."""
    ingestao.executar(sink_cvm, "cvm_cadastro", "atual",
                      baixar=baixador({"cad_cia_aberta.csv": csv_cad}))
    ingestao.executar(sink_cvm, "cvm_dfp_empresa", "2023",
                      baixar=baixador({"dfp_cia_aberta_2023.zip": zip_dfp}))
    return sink_cvm


# --------------------------------------------------------------------------
# Coexistência: nada é sobrescrito
# --------------------------------------------------------------------------
def test_as_duas_fontes_coexistem_na_tabela(carregado):
    """Antes desta etapa, a segunda carga sobrescreveria a primeira e a
    divergência seria apagada antes de alguém poder olhar para ela."""
    linhas = carregado.consultar(
        "SELECT origem_dataset, denom_social FROM dim_empresa "
        "WHERE cd_cvm = 9512 ORDER BY origem_dataset"
    )
    assert [(l["origem_dataset"], l["denom_social"]) for l in linhas] == [
        ("cvm_cadastro", DENOM_CADASTRO),
        ("cvm_dfp_empresa", DENOM_DFP),
    ]


def test_gold_publica_o_valor_da_fonte_de_maior_precedencia(carregado):
    """O aceite da etapa."""
    linhas = carregado.consultar("SELECT * FROM gold_empresa WHERE cd_cvm = 9512")
    assert len(linhas) == 1, "a classe tem de resolver para uma linha por empresa"
    assert linhas[0]["denom_social"] == DENOM_CADASTRO
    assert linhas[0]["denom_social_origem"] == "cvm_cadastro"


def test_atributo_de_uma_fonte_so_nao_ganha_coluna_de_origem(carregado):
    """`setor_atividade` só vem do cadastro: dizer isso em toda linha seria
    uma constante repetida."""
    colunas = set(carregado.consultar("SELECT * FROM gold_empresa LIMIT 1")[0])
    assert "denom_social_origem" in colunas
    assert "setor_atividade_origem" not in colunas


def test_fonte_secundaria_preenche_o_que_a_primeira_nao_tem(carregado, zip_dfp):
    """Companhia que publicou balanço e ainda não está no cadastro aparece —
    é o motivo de ter a segunda fonte, não um efeito colateral."""
    outra = zip_cvm({
        "dfp_cia_aberta_BPA_con_2023.csv": csv_conta([
            linha(cd_cvm=7777, denom="NOVATA S.A.", cd_conta="1", vl="10,00"),
        ]),
    })
    ingestao.executar(carregado, "cvm_dfp_empresa", "2024",
                      baixar=baixador({"dfp_cia_aberta_2024.zip": outra}))
    nova = carregado.um("SELECT * FROM gold_empresa WHERE cd_cvm = 7777")
    assert nova["denom_social"] == "NOVATA S.A."
    assert nova["denom_social_origem"] == "cvm_dfp_empresa"
    assert nova["setor_atividade"] is None, "a DFP não sabe o setor"


# --------------------------------------------------------------------------
# Mudar de ideia é republicar, não recarregar
# --------------------------------------------------------------------------
def test_inverter_a_precedencia_muda_o_publicado_sem_tocar_no_dado(carregado):
    """A propriedade que justifica a escolha de derivar em vez de sobrescrever."""
    antes = carregado.um("SELECT count(*) AS n FROM dim_empresa")["n"]

    invertida = seed_cvm.CLASSE_EMPRESA
    atributos = [
        repo.Atributo(**{**vars(a), "precedencia": ["cvm_dfp_empresa", "cvm_cadastro"]})
        if a.nome == "denom_social" else a
        for a in invertida.atributos
    ]
    repo.salvar_classe(carregado, repo.Classe(
        **{**vars(invertida), "atributos": atributos,
           "precedencia": ["cvm_dfp_empresa", "cvm_cadastro"]}
    ))
    publicacao.publicar(carregado)

    resolvida = carregado.um("SELECT * FROM gold_empresa WHERE cd_cvm = 9512")
    assert resolvida["denom_social"] == DENOM_DFP
    assert resolvida["denom_social_origem"] == "cvm_dfp_empresa"
    assert carregado.um("SELECT count(*) AS n FROM dim_empresa")["n"] == antes


def test_remover_a_segunda_fonte_nao_apaga_o_que_ela_trouxe(carregado):
    """Desligar um mapeamento é decisão de publicação. O dado que ele trouxe
    continua em silver, recuperável."""
    guardadas = carregado.um(
        "SELECT count(*) AS n FROM dim_empresa WHERE origem_dataset = 'cvm_dfp_empresa'"
    )["n"]
    ds = repo.dataset_vigente(carregado, "cvm_dfp_empresa")
    carregado.executar(
        "UPDATE cfg_dataset SET ativo = FALSE WHERE id = ?", (ds["id"],)
    )
    assert carregado.um(
        "SELECT count(*) AS n FROM dim_empresa WHERE origem_dataset = 'cvm_dfp_empresa'"
    )["n"] == guardadas


# --------------------------------------------------------------------------
# Precedência por atributo, não por fonte
# --------------------------------------------------------------------------
def test_precedencia_e_declarada_por_atributo(sink_cvm):
    classe = repo.classe_vigente(sink_cvm, "empresa")
    atributos = {a["nome"]: a for a in repo.atributos_de(sink_cvm, classe["id"])}
    mapa = ddl.datasets_por_atributo(sink_cvm, classe)

    # O mesmo atributo pode ter ordem diferente da ordem da classe.
    ordem = ddl.precedencia_do_atributo(
        classe, atributos["denom_social"], mapa["denom_social"])
    assert ordem[0] == "cvm_cadastro", "o cadastro é o registro formal"
    assert set(ordem) == set(mapa["denom_social"])

    sem_declaracao = {**atributos["cnpj"], "precedencia": ""}
    herdada = ddl.precedencia_do_atributo(classe, sem_declaracao, mapa["cnpj"])
    assert herdada[0] == "cvm_cadastro", "cai na precedência da classe"


def test_classe_de_fonte_unica_nao_ganha_vista_resolvida(sink_cvm):
    """`demonstracao_financeira` tem uma fonte por chave: resolver ali seria
    um GROUP BY sobre centenas de milhares de linhas sem nada a decidir."""
    geradas = ddl.vistas_resolvidas(sink_cvm)
    assert "gold_empresa" in geradas
    assert "gold_demonstracao_financeira" not in geradas


def test_resolucao_desconhecida_e_recusada():
    with pytest.raises(repo.ErroConfiguracao, match="resolução desconhecida"):
        repo.validar_classe(repo.Classe(
            chave="x", nome="X", tabela="tab_x", chave_identidade=["a"],
            atributos=[repo.Atributo("a")], resolucao="votacao",
        ))


# --------------------------------------------------------------------------
# A API diz de onde veio cada atributo disputado
# --------------------------------------------------------------------------
def test_api_informa_a_origem_por_atributo(tmp_path, monkeypatch, zip_dfp, csv_cad):
    banco = str(tmp_path / "multi.duckdb")
    monkeypatch.setenv("PORTAL_DUCKDB", banco)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("PORTAL_ADMIN_TOKEN", raising=False)

    s = SinkDuckDB(banco)
    bootstrap.preparar(s)
    seed_cvm.aplicar(s)
    ingestao.executar(s, "cvm_cadastro", "atual",
                      baixar=baixador({"cad_cia_aberta.csv": csv_cad}))
    ingestao.executar(s, "cvm_dfp_empresa", "2023",
                      baixar=baixador({"dfp_cia_aberta_2023.zip": zip_dfp}))
    emitida = auth.emitir(s, "bolsia")
    s.fechar()

    from app.api.main import app

    with TestClient(app) as c:
        r = c.get("/v1/empresas/9512", headers={"X-API-Key": emitida.chave_completa})
    assert r.status_code == 200, r.text
    dado = r.json()["dados"]
    assert dado["denom_social"] == DENOM_CADASTRO
    assert dado["proveniencia"]["por_atributo"]["denom_social"] == "cvm_cadastro"
    # A origem não vaza como campo solto ao lado do dado.
    assert "denom_social_origem" not in dado


def test_vista_resolvida_nao_agrega_booleano_com_max(sink_cvm):
    """`MAX(boolean)` funciona no DuckDB e não existe no Postgres — foi assim
    que uma migração passou em teste e derrubou o boot em produção. A vista
    usa BOOL_OR para os atributos booleanos, que os dois dialetos entendem.

    A asserção é sobre o SQL gerado, de propósito: assim ela vale mesmo na
    suíte que roda só em DuckDB, onde a diferença é invisível.
    """
    import re

    classe = repo.classe_vigente(sink_cvm, "empresa")
    atributos = repo.atributos_de(sink_cvm, classe["id"])
    booleanos = [a["nome"] for a in atributos if a["tipo"] == "booleano"]
    assert booleanos, "a classe empresa tem listada_b3; sem ele o teste não prova nada"

    sql = ddl.sql_vista_resolvida(sink_cvm, classe, atributos)
    assert sql is not None
    for nome in booleanos:
        assert not re.search(rf"MAX\(CASE WHEN [^)]*THEN {nome} END\)", sql), (
            f"'{nome}' é booleano e está sob MAX — o Postgres recusa"
        )
        assert f"BOOL_OR(CASE WHEN origem_dataset = " in sql


def test_precedencia_nomeia_mapeamento_e_nao_fonte(sink_cvm):
    """Precedência casa contra `origem_dataset`, que é a chave do mapeamento.

    Declarar a chave da *fonte* — `b3` em vez de `b3_listadas` — não dá erro:
    o nome simplesmente não casa com candidato nenhum e o mapeamento cai para
    o fim da fila. Foi o que aconteceu com `cnpj`, e o sintoma era invisível.
    """
    ofensores = []
    for classe in repo.listar_classes(sink_cvm, so_ativas=True):
        mapeamentos = {
            d["chave"] for d in repo.datasets_da_classe(sink_cvm, classe["chave"])
        }
        declarados = [
            (classe["chave"], "(classe)", n)
            for n in (classe["precedencia"] or "").split(",") if n
        ]
        for a in repo.atributos_de(sink_cvm, classe["id"]):
            declarados += [
                (classe["chave"], a["nome"], n)
                for n in (a["precedencia"] or "").split(",") if n
            ]
        ofensores += [
            f"{c}.{atr}: '{n}' não é mapeamento de '{c}' ({', '.join(sorted(mapeamentos))})"
            for c, atr, n in declarados if n not in mapeamentos
        ]
    assert ofensores == []
