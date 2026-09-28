"""O contrato de setups do MCP: `/v1/setups`.

O MCP (`~/dev/MCP/servers/mydata/armazem.py`) guarda vigias de candle num JSON
local hoje, e declara este endpoint como alvo de produção. `registro` é o
JSON dele inteiro — opaco para o MyData, que só guarda. A tabela é própria,
fora do motor (ADR-24 em docs/arquitetura.md), porque setup é estado privado
de UM consumidor, não classe de informação republicável entre chaves — e é
isso que estes testes fixam: o escopo `setups` (que `leitura` não substitui)
e o isolamento entre consumidores.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import bootstrap
from app.api import auth
from app.sinks import SinkDuckDB


@pytest.fixture()
def cliente_setups(tmp_path, monkeypatch):
    """API sobre um banco vazio — setups não depende de nenhuma classe da
    CVM/B3, então não há por que carregar dado de domínio aqui."""
    banco = str(tmp_path / "setups.duckdb")
    monkeypatch.setenv("PORTAL_DUCKDB", banco)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("PORTAL_ADMIN_TOKEN", raising=False)

    s = SinkDuckDB(banco)
    bootstrap.preparar(s)
    chave_a = auth.emitir(s, "mcp-teste-a", escopos="setups")
    chave_b = auth.emitir(s, "mcp-teste-b", escopos="setups")
    chave_sem_escopo = auth.emitir(s, "leitor-amplo", escopos="leitura")
    s.fechar()

    from app.api.main import app

    with TestClient(app) as c:
        c.headers.update({"X-API-Key": chave_a.chave_completa})
        c.chave_a = chave_a
        c.chave_b = chave_b
        c.chave_sem_escopo = chave_sem_escopo
        yield c


def _registro(nome: str = "vigia-petr4", **extra) -> dict:
    base = {
        "setup": {
            "name": nome,
            "ativo_objeto": "PETR4",
            "regra": "cruzamento_mm",
        },
    }
    base.update(extra)
    return base


def _com_chave(chave) -> dict:
    return {"X-API-Key": chave.chave_completa}


# --------------------------------------------------------------------------
# Fluxo completo
# --------------------------------------------------------------------------
def test_fluxo_completo_criar_listar_obter_anotar_desativar(cliente_setups):
    c = cliente_setups

    r = c.post("/v1/setups", json={"registro": _registro("vigia-1")})
    assert r.status_code == 201, r.text
    criado = r.json()["dados"]
    assert criado["setup"]["name"] == "vigia-1"
    assert criado["status"] == "ativo"

    r = c.get("/v1/setups/vigia-1")
    assert r.status_code == 200
    assert r.json()["dados"] == criado

    r = c.get("/v1/setups")
    assert r.status_code == 200
    assert [d["setup"]["name"] for d in r.json()["dados"]] == ["vigia-1"]

    r = c.patch("/v1/setups/vigia-1",
                json={"campo": "ultimo_pregao_notificado", "valor": "2026-09-25"})
    assert r.status_code == 200, r.text
    assert r.json()["dados"]["ultimo_pregao_notificado"] == "2026-09-25"
    # Persistiu — não é só o eco da resposta.
    assert c.get("/v1/setups/vigia-1").json()["dados"][
        "ultimo_pregao_notificado"] == "2026-09-25"

    r = c.post("/v1/setups/vigia-1/desativar")
    assert r.status_code == 200
    assert r.json()["dados"] == {"desativado": True}

    assert c.get("/v1/setups/vigia-1").json()["dados"]["status"] == "inativo"
    assert c.get("/v1/setups").json()["dados"] == []
    inativos = c.get("/v1/setups", params={"incluir_inativos": "true"}).json()["dados"]
    assert [d["setup"]["name"] for d in inativos] == ["vigia-1"]


def test_status_ausente_vira_ativo(cliente_setups):
    registro = _registro("sem-status")
    assert "status" not in registro
    r = cliente_setups.post("/v1/setups", json={"registro": registro})
    assert r.status_code == 201
    assert r.json()["dados"]["status"] == "ativo"


def test_lista_ordenada_por_criacao(cliente_setups):
    c = cliente_setups
    for nome in ("primeiro", "segundo", "terceiro"):
        assert c.post("/v1/setups", json={"registro": _registro(nome)}).status_code == 201
    nomes = [d["setup"]["name"] for d in c.get("/v1/setups").json()["dados"]]
    assert nomes == ["primeiro", "segundo", "terceiro"]


# --------------------------------------------------------------------------
# Nome repetido
# --------------------------------------------------------------------------
def test_nome_repetido_e_409(cliente_setups):
    c = cliente_setups
    assert c.post("/v1/setups", json={"registro": _registro("dup")}).status_code == 201
    r = c.post("/v1/setups", json={"registro": _registro("dup")})
    assert r.status_code == 409
    assert r.json()["erro"]["codigo"] == "setup_existente"


# --------------------------------------------------------------------------
# Isolamento entre consumidores
# --------------------------------------------------------------------------
def test_isolamento_entre_consumidores(cliente_setups):
    c = cliente_setups
    r = c.post("/v1/setups", json={"registro": _registro("mesmo-nome")},
               headers=_com_chave(c.chave_a))
    assert r.status_code == 201

    # `b` não vê o setup de `a`.
    assert c.get("/v1/setups", headers=_com_chave(c.chave_b)).json()["dados"] == []
    r = c.get("/v1/setups/mesmo-nome", headers=_com_chave(c.chave_b))
    assert r.status_code == 404
    assert r.json()["erro"]["codigo"] == "setup_inexistente"

    # E o nome não colide: identidade é (consumidor, nome), não só nome.
    r = c.post("/v1/setups", json={"registro": _registro("mesmo-nome")},
               headers=_com_chave(c.chave_b))
    assert r.status_code == 201

    assert len(c.get("/v1/setups", headers=_com_chave(c.chave_a)).json()["dados"]) == 1
    assert len(c.get("/v1/setups", headers=_com_chave(c.chave_b)).json()["dados"]) == 1


# --------------------------------------------------------------------------
# Escopo
# --------------------------------------------------------------------------
def test_leitura_sem_escopo_setups_e_403(cliente_setups):
    c = cliente_setups
    cab = _com_chave(c.chave_sem_escopo)

    r = c.get("/v1/setups", headers=cab)
    assert r.status_code == 403
    assert r.json()["erro"]["codigo"] == "escopo_insuficiente"

    # A negação vale para escrita também, não só leitura.
    r = c.post("/v1/setups", json={"registro": _registro("x")}, headers=cab)
    assert r.status_code == 403
    assert r.json()["erro"]["codigo"] == "escopo_insuficiente"


def test_pode_setups_exige_o_token_explicito():
    """Unitário do helper: `leitura` sozinho não é suficiente — diferente do
    resto do modelo de escopo, onde `leitura` libera tudo."""
    assert auth.pode_setups({"escopos": "setups"}) is True
    assert auth.pode_setups({"escopos": "classe:empresa,setups"}) is True
    assert auth.pode_setups({"escopos": "leitura"}) is False
    assert auth.pode_setups({"escopos": "classe:empresa"}) is False
    assert auth.pode_setups({"escopos": ""}) is False
    assert auth.pode_setups({}) is False


# --------------------------------------------------------------------------
# PATCH: campos reservados
# --------------------------------------------------------------------------
def test_patch_recusa_setup_e_status(cliente_setups):
    c = cliente_setups
    assert c.post("/v1/setups", json={"registro": _registro("reservado")}).status_code == 201

    for campo in ("setup", "status"):
        r = c.patch("/v1/setups/reservado", json={"campo": campo, "valor": "x"})
        assert r.status_code == 400, (campo, r.text)
        assert r.json()["erro"]["codigo"] == "campo_reservado"


# --------------------------------------------------------------------------
# Entrada inválida
# --------------------------------------------------------------------------
def test_setup_sem_nome_e_400(cliente_setups):
    r = cliente_setups.post("/v1/setups", json={"registro": {"setup": {}}})
    assert r.status_code == 400
    assert r.json()["erro"]["codigo"] == "entrada_invalida"

    r = cliente_setups.post("/v1/setups", json={"registro": {"setup": {"name": "  "}}})
    assert r.status_code == 400
    assert r.json()["erro"]["codigo"] == "entrada_invalida"


# --------------------------------------------------------------------------
# 404
# --------------------------------------------------------------------------
def test_obter_inexistente_e_404(cliente_setups):
    r = cliente_setups.get("/v1/setups/fantasma")
    assert r.status_code == 404
    assert r.json()["erro"]["codigo"] == "setup_inexistente"


def test_patch_inexistente_e_404(cliente_setups):
    r = cliente_setups.patch("/v1/setups/fantasma",
                             json={"campo": "x", "valor": 1})
    assert r.status_code == 404
    assert r.json()["erro"]["codigo"] == "setup_inexistente"


def test_desativar_inexistente_devolve_false_nao_404(cliente_setups):
    """Espelha `ArmazemArquivo.desativar`, que devolve bool."""
    r = cliente_setups.post("/v1/setups/fantasma/desativar")
    assert r.status_code == 200
    assert r.json()["dados"] == {"desativado": False}


def test_desativar_ja_inativo_devolve_false(cliente_setups):
    c = cliente_setups
    c.post("/v1/setups", json={"registro": _registro("ja-inativo")})
    assert c.post("/v1/setups/ja-inativo/desativar").json()["dados"]["desativado"] is True
    r = c.post("/v1/setups/ja-inativo/desativar")
    assert r.status_code == 200
    assert r.json()["dados"] == {"desativado": False}
