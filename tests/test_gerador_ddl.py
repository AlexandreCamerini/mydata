"""Etapa 2 — o gerador de DDL, provado em terreno vazio.

A máquina nova nasce exercitada numa classe que não existia: nada aqui toca
`fato_conta`. Duas provas, e as duas precisam passar antes de a Etapa 3
entregar as tabelas da CVM ao gerador:

1. Uma classe de informação criada pela API é ingerível e legível na mesma
   sessão, sem nenhuma migração escrita à mão.
2. O gerador reproduz o schema que a migração `0004` criou. Um gerador que
   não recria a tabela que já está em produção não está pronto para ser dono
   dela.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import bootstrap, repositorio as repo, seed_cvm
from app.motor import ddl, ingestao
from app.sinks import SinkDuckDB

# Uma classe de outro domínio de propósito: nada de contabilidade, nada de
# CVM. Se precisasse de qualquer coisa específica, o gerador não seria geral.
CLASSE_NOVA = {
    "chave": "leitura_sensor",
    "nome": "Leitura de sensor",
    "tabela": "fato_leitura_sensor",
    "chave_identidade": ["sensor", "medido_em"],
    "indices": [["sensor"]],
    "atributos": [
        {"nome": "sensor", "tipo": "texto", "obrigatorio": True, "ordem": 1},
        {"nome": "medido_em", "tipo": "data", "obrigatorio": True, "ordem": 2},
        {"nome": "temperatura", "tipo": "numero", "guarda_texto": True,
         "unidade": "°C", "ordem": 3},
        {"nome": "ativo", "tipo": "booleano", "ordem": 4},
    ],
}

CSV_SENSOR = (
    "SENSOR;MEDIDO_EM;TEMPERATURA;ATIVO\n"
    "s-01;2026-01-10;21,5;S\n"
    "s-01;2026-01-11;23,0;S\n"
    "s-02;2026-01-10;19,25;N\n"
).encode("utf-8")


@pytest.fixture()
def admin(tmp_path, monkeypatch):
    """API sobre uma base limpa, com a CVM cadastrada e nada ingerido."""
    banco = str(tmp_path / "gerador.duckdb")
    monkeypatch.setenv("PORTAL_DUCKDB", banco)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("PORTAL_ADMIN_TOKEN", raising=False)

    s = SinkDuckDB(banco)
    bootstrap.preparar(s)
    seed_cvm.aplicar(s)
    s.fechar()

    from app.api.main import app

    with TestClient(app) as c:
        yield c


# --------------------------------------------------------------------------
# Prova 1: classe nova, ponta a ponta, sem deploy
# --------------------------------------------------------------------------
def test_classe_criada_pela_api_e_ingerivel_e_legivel(admin):
    """O aceite da etapa. Cria a classe, a fonte e o mapeamento por HTTP;
    ingere um CSV; lê o resultado. Nenhuma migração foi escrita para isso."""
    sink = admin.app.state.sink

    resposta = admin.post("/admin/api/classes", json=CLASSE_NOVA)
    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["ddl_aplicado"], "a classe tem de materializar a tabela"

    # A tabela passou a existir agora, e não estava em migração nenhuma.
    colunas = ddl.colunas_fisicas(sink, "fato_leitura_sensor")
    assert {"sensor", "medido_em", "temperatura", "temperatura_txt", "ativo",
            "captura_id", "publicado_em_versao"} <= set(colunas)

    admin.post("/admin/api/fontes", json={
        "chave": "predial", "nome": "Telemetria predial",
        "tipo_transporte": "http_csv",
        "url_template": "https://exemplo.invalido/leituras_{ano}.csv",
        "encoding": "utf-8", "separador": ";",
    })
    admin.post("/admin/api/datasets", json={
        "chave": "predial_leituras", "fonte_chave": "predial",
        "nome": "Leituras horárias",
        "padrao_arquivo": r"^leituras_(?P<ano>\d{4})\.csv$",
        "tabela_destino": "fato_leitura_sensor",
        "classe_chave": "leitura_sensor",
        "chave_natural": ["sensor", "medido_em"],
        "colunas": [
            {"nome_origem": "SENSOR", "nome_destino": "sensor",
             "tipo": "texto", "obrigatoria": True, "ordem": 1},
            {"nome_origem": "MEDIDO_EM", "nome_destino": "medido_em",
             "tipo": "data", "formato": "data_iso", "obrigatoria": True, "ordem": 2},
            {"nome_origem": "TEMPERATURA", "nome_destino": "temperatura",
             "tipo": "numero", "formato": "decimal_ptbr", "ordem": 3},
            {"nome_origem": "ATIVO", "nome_destino": "ativo",
             "tipo": "booleano", "ordem": 4},
        ],
    })

    res = ingestao.executar(
        sink, "predial_leituras", "2026",
        baixar=lambda url: CSV_SENSOR,
    )
    assert res.status == "publicado", res.erro
    assert res.linhas_silver == 3

    linhas = sink.consultar(
        "SELECT sensor, medido_em, temperatura, temperatura_txt, ativo "
        "FROM fato_leitura_sensor ORDER BY sensor, medido_em"
    )
    assert [l["sensor"] for l in linhas] == ["s-01", "s-01", "s-02"]
    assert linhas[0]["temperatura"] == 21.5
    assert linhas[0]["temperatura_txt"] == "21,5", "a representação original fica"
    assert linhas[2]["ativo"] is False


def test_classe_nova_aparece_no_catalogo_de_classes(admin):
    admin.post("/admin/api/classes", json=CLASSE_NOVA)
    dados = admin.get("/admin/api/classes").json()["dados"]
    por_chave = {c["chave"]: c for c in dados}
    assert "leitura_sensor" in por_chave
    assert por_chave["leitura_sensor"]["divergencias"] == []


def test_classe_invalida_e_recusada_antes_de_criar_tabela(admin):
    sink = admin.app.state.sink
    ruim = {**CLASSE_NOVA, "chave": "ruim", "tabela": "tab_ruim",
            "chave_identidade": ["nao_existe"]}
    resposta = admin.post("/admin/api/classes", json=ruim)
    assert resposta.status_code == 422
    assert "inexistente" in resposta.json()["erro"]["mensagem"]
    assert ddl.colunas_fisicas(sink, "tab_ruim") == {}


def test_ddl_da_classe_e_consultavel_antes_de_aplicar(admin):
    """Quem administra precisa ver o que vai rodar no banco antes de salvar."""
    admin.post("/admin/api/classes", json=CLASSE_NOVA)
    dados = admin.get("/admin/api/classes/leitura_sensor/ddl").json()["dados"]
    juntas = "\n".join(dados["sentencas"])
    assert "CREATE TABLE IF NOT EXISTS fato_leitura_sensor" in juntas
    assert "ux_fato_leitura_sensor_identidade" in juntas
    assert dados["divergencias"] == []


def test_salvar_classe_de_novo_nao_quebra_a_tabela_existente(admin):
    """Reversionar a classe é comum. O DDL é idempotente; a tabela e o dado
    que já está nela continuam onde estavam."""
    sink = admin.app.state.sink
    admin.post("/admin/api/classes", json=CLASSE_NOVA)
    sink.executar(
        "INSERT INTO fato_leitura_sensor (captura_id, fonte_arquivo, sensor, "
        "medido_em) VALUES (1, 'x.csv', 's-99', '2026-02-01')"
    )
    segunda = admin.post("/admin/api/classes",
                         json={**CLASSE_NOVA, "nome": "Leitura (v2)"})
    assert segunda.status_code == 200
    assert sink.um("SELECT count(*) AS n FROM fato_leitura_sensor")["n"] == 1


# --------------------------------------------------------------------------
# Prova 2: o gerador reproduz o que a migração criou
# --------------------------------------------------------------------------
@pytest.mark.parametrize("chave,tabela", [("demonstracao_financeira", "fato_conta"),
                                          ("empresa", "dim_empresa")])
def test_gerador_reproduz_o_schema_de_producao(tmp_path, chave, tabela):
    """Compara o que o gerador produz com o DDL que a base de produção tem.

    `DDL_HISTORICO_SILVER` é literalmente o que a migração `0004` aplicou
    antes da virada — é o schema que existe hoje no Postgres do Railway.
    Divergir aqui significa que a configuração descreve outra tabela.
    """
    from app import migracoes
    from app.sinks import render

    # Banco A: só o DDL histórico, aplicado à mão.
    producao = SinkDuckDB(str(tmp_path / "producao.duckdb"))
    for sentenca in migracoes.DDL_HISTORICO_SILVER:
        producao.executar(render(sentenca, producao.dialeto))
    esperado = ddl.colunas_fisicas(producao, tabela)
    producao.fechar()
    assert esperado, "o DDL histórico tem de criar a tabela"

    # Banco B: só o gerador, a partir da configuração.
    gerado = SinkDuckDB(str(tmp_path / "gerado.duckdb"))
    bootstrap.preparar(gerado)
    seed_cvm.aplicar(gerado)
    obtido = ddl.colunas_fisicas(gerado, tabela)
    gerado.fechar()

    faltando = {c: t for c, t in esperado.items() if obtido.get(c) != t}
    assert not faltando, f"a configuração perdeu ou mudou colunas: {faltando}"

    # Coluna nova é acréscimo consciente, e cada uma tem motivo registrado.
    # O que este teste protege é a direção: a configuração pode acrescentar,
    # nunca perder nem mudar o que produção já tem.
    acrescimos = {
        "origem_dataset",                                    # Etapa 4, multi-fonte
        "ticker", "nome_pregao", "setor_b3",                  # fonte B3
        "segmento_listagem", "dt_listagem", "listada_b3",
    }
    inesperadas = set(obtido) - set(esperado) - acrescimos
    assert not inesperadas, f"coluna sem decisão registrada: {inesperadas}"


def test_gerador_cria_o_indice_de_identidade(tmp_path):
    """Sem o índice único, o upsert da carga não tem em que se apoiar."""
    sink = SinkDuckDB(str(tmp_path / "ix.duckdb"))
    bootstrap.preparar(sink)
    seed_cvm.aplicar(sink)
    classe = repo.classe_vigente(sink, "empresa")
    ddl.garantir_tabela(sink, classe, repo.atributos_de(sink, classe["id"]))
    sink.executar(
        "INSERT INTO dim_empresa (captura_id, fonte_arquivo, origem_dataset, "
        "cd_cvm) VALUES (1, 'a.csv', 'cvm_cadastro', 4242)"
    )
    with pytest.raises(Exception):
        sink.executar(
            "INSERT INTO dim_empresa (captura_id, fonte_arquivo, origem_dataset,"
            " cd_cvm) VALUES (2, 'b.csv', 'cvm_cadastro', 4242)"
        )
    # A mesma empresa vinda de outra fonte convive: é isso que permite
    # comparar as duas em vez de a segunda apagar a primeira.
    sink.executar(
        "INSERT INTO dim_empresa (captura_id, fonte_arquivo, origem_dataset, "
        "cd_cvm) VALUES (3, 'c.csv', 'outra_fonte', 4242)"
    )
    assert sink.um("SELECT count(*) AS n FROM dim_empresa")["n"] == 2
    sink.fechar()
