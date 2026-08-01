"""Fase 3 — API pública: proveniência, cursor, quota, ETag, catálogo."""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from app import bootstrap, seed_cvm
from app.api import auth
from app.motor import ingestao
from app.sinks import SinkDuckDB


def baixador(mapa: dict[str, bytes]):
    def _baixar(url: str) -> bytes:
        for chave, dado in mapa.items():
            if chave in url:
                return dado
        raise AssertionError(f"URL não prevista: {url}")
    return _baixar


@pytest.fixture()
def cliente(tmp_path, zip_dfp_2023, csv_cadastro, monkeypatch):
    """API sobre uma base DuckDB em arquivo, já carregada com dado."""
    banco = str(tmp_path / "api.duckdb")
    monkeypatch.setenv("PORTAL_DUCKDB", banco)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("PORTAL_ADMIN_TOKEN", raising=False)

    s = SinkDuckDB(banco)
    bootstrap.preparar(s)
    seed_cvm.aplicar(s)
    ingestao.executar(s, "cvm_dfp", "2023",
                      baixar=baixador({"dfp_cia_aberta_2023.zip": zip_dfp_2023}))
    ingestao.executar(s, "cvm_cadastro", "atual",
                      baixar=baixador({"cad_cia_aberta.csv": csv_cadastro}))
    emitida = auth.emitir(s, "bolsia", quota_minuto=5, quota_dia=1000)
    s.fechar()

    from app.api.main import app
    with TestClient(app) as c:
        c.headers.update({"X-API-Key": emitida.chave_completa})
        c.chave = emitida
        yield c


# --------------------------------------------------------------------------
# Saúde e autenticação
# --------------------------------------------------------------------------
def test_health_responde_sem_tocar_no_banco(cliente):
    r = cliente.get("/health", headers={"X-API-Key": ""})
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_sem_chave_recusa_com_codigo_estavel(cliente):
    r = cliente.get("/v1/empresas", headers={"X-API-Key": ""})
    assert r.status_code == 401
    assert r.json()["erro"]["codigo"] == "chave_invalida"


def test_chave_revogada_para_de_funcionar(cliente):
    r = cliente.delete(f"/admin/api/chaves/{cliente.chave.prefixo}")
    assert r.status_code == 200
    r = cliente.get("/v1/empresas")
    assert r.status_code == 401


def test_quota_estoura_com_retry_after(cliente):
    for _ in range(5):
        assert cliente.get("/v1/empresas").status_code == 200
    r = cliente.get("/v1/empresas")
    assert r.status_code == 429
    assert r.json()["erro"]["codigo"] == "quota_excedida"
    assert r.headers["Retry-After"] == "60"


# --------------------------------------------------------------------------
# Empresas
# --------------------------------------------------------------------------
def test_lista_empresas_com_proveniencia(cliente):
    r = cliente.get("/v1/empresas")
    assert r.status_code == 200
    dados = r.json()["dados"]
    assert len(dados) == 2
    prov = dados[0]["proveniencia"]
    assert prov["fonte"].startswith("https://dados.cvm.gov.br/")
    assert len(prov["sha256"]) == 64
    # A publicação do cadastro é a 2ª (DFP publicou a 1ª) — o que importa é
    # que a linha carrega em qual publicação entrou.
    assert prov["dt_captura"] and prov["publicacao"] >= 1


def test_busca_por_nome(cliente):
    r = cliente.get("/v1/empresas", params={"q": "outra"})
    assert [d["cd_cvm"] for d in r.json()["dados"]] == [1023]


def test_empresa_inexistente_404_com_codigo(cliente):
    r = cliente.get("/v1/empresas/999999")
    assert r.status_code == 404
    assert r.json()["erro"]["codigo"] == "empresa_nao_encontrada"


def test_paginacao_por_cursor(cliente):
    r1 = cliente.get("/v1/empresas", params={"limite": 1})
    corpo = r1.json()
    assert len(corpo["dados"]) == 1 and corpo["proximo_cursor"]

    r2 = cliente.get("/v1/empresas",
                     params={"limite": 1, "cursor": corpo["proximo_cursor"]})
    assert r2.json()["dados"][0]["cd_cvm"] != corpo["dados"][0]["cd_cvm"]
    assert r2.json()["proximo_cursor"] is None


def test_cursor_invalido_e_erro_de_parametro(cliente):
    r = cliente.get("/v1/empresas", params={"cursor": "nao-e-base64-valido!!"})
    assert r.status_code == 400
    assert r.json()["erro"]["codigo"] == "parametro_invalido"


# --------------------------------------------------------------------------
# Demonstrações
# --------------------------------------------------------------------------
def test_demonstracoes_so_traz_dado_correto(cliente):
    """Gold já filtrou is_latest e ORDEM_EXERC — a API não repete a regra."""
    r = cliente.get("/v1/empresas/9512/demonstracoes",
                    params={"tipo": "DFP", "grupo": "BPA"})
    dados = r.json()["dados"]
    assert all(d["versao"] == 2 for d in dados)
    assert len(dados) == 2


def test_consolidado_e_individual_nao_se_misturam(cliente):
    con = cliente.get("/v1/empresas/9512/demonstracoes",
                      params={"grupo": "BPA", "consolidado": True}).json()["dados"]
    ind = cliente.get("/v1/empresas/9512/demonstracoes",
                      params={"grupo": "BPA", "consolidado": False}).json()["dados"]
    assert {d["vl_conta_norm"] for d in con} == {1100000.0, 400000.0}
    assert {d["vl_conta_norm"] for d in ind} == {800000.0}


def test_filtro_por_conta_e_periodo(cliente):
    r = cliente.get("/v1/empresas/9512/demonstracoes",
                    params={"conta": "1.01", "de": "2023-01-01", "ate": "2023-12-31"})
    dados = r.json()["dados"]
    assert len(dados) == 1 and dados[0]["cd_conta"] == "1.01"


def test_valor_original_e_normalizado_lado_a_lado(cliente):
    r = cliente.get("/v1/empresas/9512/demonstracoes", params={"conta": "1."})
    d = [x for x in r.json()["dados"] if x["cd_conta"] == "1.01"][0]
    assert d["vl_conta"] == 400.0 and d["vl_conta_norm"] == 400000.0
    assert d["escala_moeda"] == "MIL"


# --------------------------------------------------------------------------
# Cache
# --------------------------------------------------------------------------
def test_etag_devolve_304(cliente):
    r1 = cliente.get("/v1/empresas")
    etag = r1.headers["ETag"]
    r2 = cliente.get("/v1/empresas", headers={"If-None-Match": etag})
    assert r2.status_code == 304


# --------------------------------------------------------------------------
# Catálogo e métricas
# --------------------------------------------------------------------------
def test_meta_datasets_expoe_o_contrato(cliente):
    r = cliente.get("/v1/meta/datasets")
    chaves = {d["chave"] for d in r.json()["dados"]}
    assert {"cvm_dfp", "cvm_itr", "cvm_cadastro"} <= chaves
    dfp = [d for d in r.json()["dados"] if d["chave"] == "cvm_dfp"][0]
    assert any(c["origem"] == "$grupo" for c in dfp["colunas"])


def test_meta_calculados_mostra_linhagem(cliente):
    r = cliente.get("/v1/meta/campos-calculados")
    is_latest = [d for d in r.json()["dados"] if d["nome"] == "is_latest"][0]
    assert is_latest["classe"] == "janela"
    assert "versao" in is_latest["colunas_origem"]


def test_metricas_calculadas_a_partir_do_catalogo(cliente):
    r = cliente.get("/v1/empresas/9512/metricas")
    assert r.status_code == 200
    # A fixture não tem 2.01/3.01, então só entram as métricas calculáveis;
    # o contrato é: sem conta, sem métrica — nunca um zero inventado.
    for periodo in r.json()["dados"]:
        assert all(v is not None for v in periodo["metricas"].values())


# --------------------------------------------------------------------------
# Administração
# --------------------------------------------------------------------------
def test_admin_valida_campo_calculado_sem_gravar(cliente):
    base = cliente.get("/admin/api/datasets").json()["dados"]
    dfp = [d for d in base if d["chave"] == "cvm_dfp"][0]
    payload = {
        "chave": "cvm_dfp", "fonte_chave": "cvm", "nome": dfp["nome"],
        "padrao_arquivo": dfp["padrao_arquivo"],
        "tabela_destino": dfp["tabela_destino"],
        "chave_natural": dfp["chave_natural"].split(","),
        "colunas": [
            {"nome_origem": c["nome_origem"], "nome_destino": c["nome_destino"],
             "tipo": c["tipo"], "formato": c["formato"],
             "obrigatoria": c["obrigatoria"], "ordem": c["ordem"]}
            for c in dfp["colunas"]
        ],
        "calculados": [{"nome": "x", "expressao": "coluna_fantasma * 2",
                        "colunas_origem": ["coluna_fantasma"]}],
        "regras": [],
    }
    r = cliente.post("/admin/api/datasets/cvm_dfp/validar", json=payload)
    corpo = r.json()
    assert corpo["valido"] is False
    assert "coluna_fantasma" in corpo["mensagem"]


def test_admin_emite_chave_uma_vez(cliente):
    r = cliente.post("/admin/api/chaves", json={"consumidor": "novo"})
    assert r.status_code == 200
    assert r.json()["dados"]["chave"].startswith("pd_")
    listadas = cliente.get("/admin/api/chaves").json()["dados"]
    assert all("hash_chave" not in c for c in listadas)


def test_admin_execucoes_registram_historico(cliente):
    r = cliente.get("/admin/api/execucoes")
    dados = r.json()["dados"]
    assert len(dados) == 2
    assert {d["dataset_chave"] for d in dados} == {"cvm_dfp", "cvm_cadastro"}
    assert all(d["status"] == "publicado" for d in dados)


def test_admin_replay_roda_sem_rede(cliente):
    r = cliente.post("/admin/api/execucoes",
                     json={"dataset_chave": "cvm_dfp", "janela": "2023",
                           "baixar": False})
    assert r.status_code == 200
    assert r.json()["dados"]["status"] == "publicado"


def test_admin_catalogo_mostra_amostra(cliente):
    r = cliente.get("/admin/api/catalogo/fato_conta", params={"limite": 3})
    corpo = r.json()["dados"]
    assert corpo["linhas"] > 0
    assert len(corpo["amostra"]) == 3
    assert any(c["nome"] == "vl_conta_norm" for c in corpo["colunas"])


def test_admin_publicacoes_e_reversao(cliente):
    antes = cliente.get("/admin/api/publicacoes").json()
    assert antes["atual"] >= 1
    r = cliente.post(f"/admin/api/publicacoes/{antes['atual']}/reverter")
    assert r.status_code == 200


def test_admin_metrica_com_formula_invalida_recusa(cliente):
    r = cliente.post("/admin/api/metricas", json={
        "chave": "ruim", "nome": "Ruim",
        "formula": "DROP TABLE fato_conta",
    })
    assert r.status_code == 422
    assert r.json()["erro"]["codigo"] == "formula_invalida"


def test_openapi_documenta_os_endpoints(cliente):
    r = cliente.get("/openapi.json")
    caminhos = r.json()["paths"]
    assert "/v1/empresas/{cd_cvm}/demonstracoes" in caminhos
    assert "/health" in caminhos


# --------------------------------------------------------------------------
# Busca por ticker e filtro por segmento (Fase 2 da apresentação)
# --------------------------------------------------------------------------
@pytest.fixture()
def cliente_b3(cliente):
    """O cliente de sempre, com a B3 ingerida por cima: 9512 ganha ticker
    PETR e segmento NM; 1023 continua sem registro de negociação."""
    import json

    def _baixar(url: str) -> bytes:
        return json.dumps({
            "page": {"totalPages": 1, "totalRecords": 1},
            "results": [{
                "codeCVM": 9512, "issuingCompany": "PETR",
                "companyName": "PETROBRAS", "tradingName": "PETROBRAS",
                "cnpj": "00000000000100", "segment": "Petróleo e Gás",
                "market": "NM", "dateListing": "2000-08-09",
            }],
        }).encode()

    sink = cliente.app.state.sink
    ingestao.executar(sink, "b3_listadas", "atual", baixar=_baixar)
    return cliente


def test_busca_por_ticker_casa_por_prefixo(cliente_b3):
    """A B3 registra a raiz (PETR); quem busca digita o papel (PETR4)."""
    r = cliente_b3.get("/v1/empresas", params={"q": "PETR4"})
    assert r.status_code == 200, r.text
    codigos = [e["cd_cvm"] for e in r.json()["dados"]]
    assert codigos == [9512]

    r = cliente_b3.get("/v1/empresas", params={"q": "petr"})
    assert [e["cd_cvm"] for e in r.json()["dados"]] == [9512]


def test_busca_por_ticker_ignora_quem_nao_tem(cliente_b3):
    """Empresa sem ticker não pode casar com qualquer termo por ter a coluna
    vazia — 'PETR4' LIKE '' || '%' seria verdadeiro para todo mundo."""
    r = cliente_b3.get("/v1/empresas", params={"q": "PETR4"})
    codigos = [e["cd_cvm"] for e in r.json()["dados"]]
    assert 1023 not in codigos


def test_filtro_por_segmento_de_listagem(cliente_b3):
    r = cliente_b3.get("/v1/empresas", params={"segmento": "nm"})
    assert [e["cd_cvm"] for e in r.json()["dados"]] == [9512]

    r = cliente_b3.get("/v1/empresas", params={"segmento": "N2"})
    assert r.json()["dados"] == []


def test_lista_traz_o_total_do_universo_filtrado(cliente_b3):
    """Uma página não sabe quantas companhias o filtro alcança; o total sabe,
    e não muda quando o cursor anda."""
    r = cliente_b3.get("/v1/empresas", params={"limite": 1})
    corpo = r.json()
    assert corpo["total"] == 2
    assert len(corpo["dados"]) == 1

    r2 = cliente_b3.get("/v1/empresas", params={"listada_b3": "true"})
    assert r2.json()["total"] == 1


def test_meta_classes_declara_a_precedencia(cliente):
    """O contrato diz por que uma fonte vence, não só qual venceu: a
    precedência da classe e a do atributo que a sobrepõe saem no catálogo."""
    r = cliente.get("/v1/meta/classes")
    classes = {c["chave"]: c for c in r.json()["dados"]}
    empresa = classes["empresa"]
    assert empresa["precedencia"] == ["cvm_cadastro", "b3", "cvm_dfp_empresa"]
    atributo = {a["nome"]: a for a in empresa["atributos"]}["denom_social"]
    assert atributo["precedencia"] == ["cvm_cadastro", "cvm_dfp_empresa"]


def test_meta_execucoes_filtra_por_status(cliente):
    """O painel do operador pergunta 'o que quebrou'; o filtro responde sem
    trazer o histórico inteiro."""
    r = cliente.get("/v1/meta/execucoes")
    assert r.status_code == 200
    todas = r.json()["dados"]
    assert len(todas) >= 2, "a fixture ingeriu DFP e cadastro"
    assert {"id", "dataset_chave", "status", "iniciado_em"} <= set(todas[0])

    r = cliente.get("/v1/meta/execucoes", params={"status": "falha,bloqueada"})
    assert r.status_code == 200
    assert all(e["status"] in ("falha", "bloqueada") for e in r.json()["dados"])
