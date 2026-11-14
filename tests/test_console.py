"""Bloco A da console central (ADR-25): guardiões, degradação por origem,
auth compartilhada com o admin, e idempotência da migração `0021_console`.

Nenhum teste aqui chama rede real — todo transporte é fake, injetado no
construtor de cada origem (mesmo espírito do `baixar=` de
`tests/conftest.py`).
"""
from __future__ import annotations

import logging
import pathlib
import re
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app import bootstrap
from app.console import credencial, coletor, origens
from app.sinks import SinkDuckDB

TOKEN = "Testes#12345#"

PACOTE = pathlib.Path(__file__).resolve().parents[1] / "app" / "console"


# --------------------------------------------------------------------------
# Fakes de transporte — sem rede real em teste nenhum.
# --------------------------------------------------------------------------
class _RespostaFake:
    def __init__(self, status_code: int, corpo):
        self.status_code = status_code
        self._corpo = corpo

    def json(self):
        return self._corpo


class _TransporteFake:
    """Roteia por substring da URL, como `baixador()` em conftest.py.

    `sequencias_get` consome uma lista de respostas por chave (na ordem);
    `respostas_form` consome, na ordem, as respostas do endpoint de token
    (uma exceção na lista é levantada em vez de devolvida)."""

    def __init__(self, *, respostas_get=None, respostas_post=None,
                 excecoes_get=None, sequencias_get=None, respostas_form=None):
        self.chamadas: list[tuple] = []
        self.chamadas_form: list[dict] = []
        self._get = respostas_get or {}
        self._post = respostas_post or {}
        self._excecoes_get = excecoes_get or {}
        self._sequencias_get = {k: list(v) for k, v in (sequencias_get or {}).items()}
        self._form = list(respostas_form or [])

    def get(self, url, *, headers=None, timeout=5.0):
        self.chamadas.append(("get", url, headers, None))
        for chave, excecao in self._excecoes_get.items():
            if chave in url:
                raise excecao
        for chave, fila in self._sequencias_get.items():
            if chave in url:
                return fila.pop(0)
        for chave, resposta in self._get.items():
            if chave in url:
                return resposta
        raise AssertionError(f"URL GET não prevista pelo fake: {url}")

    def post(self, url, *, json=None, headers=None, timeout=10.0):
        self.chamadas.append(("post", url, headers, json))
        for chave, resposta in self._post.items():
            if chave in url:
                return resposta
        raise AssertionError(f"URL POST não prevista pelo fake: {url}")

    def post_form(self, url, *, data, auth, timeout=5.0):
        self.chamadas.append(("post_form", url, auth, data))
        self.chamadas_form.append(
            {"url": url, "data": data, "auth": auth, "timeout": timeout},
        )
        if not self._form:
            raise AssertionError(f"POST de token não previsto pelo fake: {url}")
        item = self._form.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _token(access_token: str, expires_in=3600):
    corpo = {"access_token": access_token}
    if expires_in is not None:
        corpo["expires_in"] = expires_in
    return _RespostaFake(200, corpo)


ENVELOPE_OK = {"situacao": "ok", "alertas": [], "ultimas_execucoes": [], "proximas": []}
CLIENT_ID = "console-client"
CLIENT_SECRET = "Testes#12345#"


@pytest.fixture(autouse=True)
def _ambiente_limpo(monkeypatch):
    """Nenhum teste herda credencial do ambiente real nem token em cache."""
    for var in ("CONSOLE_CLIENT_ID", "CONSOLE_CLIENT_SECRET",
                "CONSOLE_ID_TOKEN_URL", "CONSOLE_PORTAL_RECURSO"):
        monkeypatch.delenv(var, raising=False)
    credencial.limpar_cache()
    yield
    credencial.limpar_cache()


@pytest.fixture()
def com_client(monkeypatch):
    monkeypatch.setenv("CONSOLE_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("CONSOLE_CLIENT_SECRET", CLIENT_SECRET)


@pytest.fixture()
def mcp_com_client(monkeypatch, com_client):
    monkeypatch.setenv("CONSOLE_MCP_URL", "https://mcp.exemplo.dev/")
    monkeypatch.delenv("CONSOLE_MCP_BEARER", raising=False)


# --------------------------------------------------------------------------
# (a) guardião de import: app/console/ nunca importa app/motor.
# --------------------------------------------------------------------------
def test_guardiao_console_nao_importa_app_motor():
    proibidos = ("app.motor", "from ..motor", "from .motor", "from app.motor")
    for caminho in sorted(PACOTE.glob("*.py")):
        texto = caminho.read_text(encoding="utf-8")
        for termo in proibidos:
            assert termo not in texto, f"{caminho.name} importa motor via '{termo}'"


# --------------------------------------------------------------------------
# (b) guardião de escrita: os únicos POSTs permitidos do pacote são (i) o
# GraphQL do Railway (`query`, nunca `mutation`) e (ii) o endpoint de token
# com `grant_type=client_credentials`.
# --------------------------------------------------------------------------
def _ocorrencias(texto: str, padrao: str) -> list[str]:
    return [linha.strip() for linha in texto.splitlines() if padrao in linha]


def test_guardiao_pacote_so_posta_railway_query_e_token_client_credentials():
    """Três pontos do pacote emitem `POST` de verdade: no transporte real
    (`requests.post` com `json=` para o Railway e com `data=` para o token) e
    nos dois únicos chamadores dele (`OrigemRailway._chamar` e
    `credencial._pedir_token`). `@router.post("/coletar")` é rota de entrada
    do próprio admin, não escrita contra origem externa, e fica fora."""
    arquivos = {c.name: c.read_text(encoding="utf-8") for c in PACOTE.glob("*.py")}
    fontes = list(arquivos.values())

    # (i) Railway: um chamador, e é o GraphQL.
    chamadas_transporte_post = [l for f in fontes for l in _ocorrencias(f, ".transporte.post(")]
    assert len(chamadas_transporte_post) == 1, chamadas_transporte_post
    assert ".transporte.post(" in arquivos["origens.py"]

    # (ii) token: um chamador, só em credencial.py, e só client_credentials.
    chamadas_form = [l for f in fontes for l in _ocorrencias(f, "transporte.post_form(")]
    assert len(chamadas_form) == 1, chamadas_form
    assert "transporte.post_form(" in arquivos["credencial.py"]
    assert '"grant_type": "client_credentials"' in arquivos["credencial.py"]
    outros_grants = [
        l for f in fontes for l in _ocorrencias(f, "grant_type")
        if "client_credentials" not in l
    ]
    assert outros_grants == [], outros_grants

    # O transporte real tem exatamente dois `requests.post(`: um por rota
    # permitida, cada um identificado pelo seu corpo.
    posts_reais = [l for f in fontes for l in _ocorrencias(f, "requests.post(")]
    assert len(posts_reais) == 2, posts_reais
    assert sum("json=json" in l for l in posts_reais) == 1, posts_reais
    assert sum("data=data" in l and "auth=auth" in l for l in posts_reais) == 1, posts_reais

    for verbo in ("put(", "patch(", "delete("):
        for alvo in ("requests.", ".transporte.", "transporte."):
            achados = [l for f in fontes for l in _ocorrencias(f, alvo + verbo)]
            assert achados == [], f"achou '{alvo}{verbo}' em app/console/: {achados}"


def test_guardiao_railway_manda_sempre_query_nunca_mutation(sink, monkeypatch):
    monkeypatch.setenv("CONSOLE_RAILWAY_TOKEN", "token-railway")
    monkeypatch.setenv("CONSOLE_RAILWAY_PROJETOS", "boris=proj-123")
    resposta = _RespostaFake(200, {"data": {"deployments": {"edges": []}}})
    transporte = _TransporteFake(respostas_post={"backboard.railway.com": resposta})

    resultado = origens.OrigemRailway(transporte=transporte).coletar(sink)

    assert resultado.ok is True
    assert len(transporte.chamadas) == 1
    metodo, url, _headers, corpo = transporte.chamadas[0]
    assert metodo == "post"
    assert url == origens.RAILWAY_GRAPHQL_URL
    assert corpo["query"].strip().startswith("query")
    assert "mutation" not in corpo["query"]


# --------------------------------------------------------------------------
# (d) origem sem variável configurada: nao_configurada, zero requisição.
# --------------------------------------------------------------------------
@pytest.mark.parametrize("origem_cls, variaveis", [
    (origens.OrigemMCP, ["CONSOLE_MCP_URL", "CONSOLE_MCP_BEARER"]),
    (origens.OrigemBoris, ["CONSOLE_BORIS_URL", "CONSOLE_BORIS_OBS_CHAVE"]),
    (origens.OrigemPortal, ["CONSOLE_PORTAL_URL"]),
    (origens.OrigemRailway, ["CONSOLE_RAILWAY_TOKEN", "CONSOLE_RAILWAY_PROJETOS"]),
])
def test_origem_sem_variavel_e_nao_configurada_sem_chamar_rede(
    sink, monkeypatch, origem_cls, variaveis,
):
    for var in variaveis:
        monkeypatch.delenv(var, raising=False)
    transporte = _TransporteFake()
    resultado = origem_cls(transporte=transporte).coletar(sink)

    assert resultado.ok is False
    assert resultado.erro == "nao_configurada"
    assert transporte.chamadas == []


# --------------------------------------------------------------------------
# (c) degradação: uma origem fora do ar nunca impede a gravação das demais.
# --------------------------------------------------------------------------
def test_coletar_tudo_degrada_por_origem_sem_derrubar_as_demais(sink, monkeypatch):
    monkeypatch.setenv("CONSOLE_MCP_URL", "https://mcp.exemplo.dev")
    monkeypatch.setenv("CONSOLE_MCP_BEARER", "tok-mcp")
    monkeypatch.setenv("CONSOLE_BORIS_URL", "https://boris.exemplo.dev")
    monkeypatch.setenv("CONSOLE_BORIS_OBS_CHAVE", "chave-boris")
    monkeypatch.setenv("CONSOLE_PORTAL_URL", "https://portal.exemplo.dev")
    monkeypatch.setenv("CONSOLE_RAILWAY_TOKEN", "tok-railway")
    monkeypatch.setenv("CONSOLE_RAILWAY_PROJETOS", "boris=proj-123")

    envelope_ok = {"situacao": "ok", "alertas": [], "ultimas_execucoes": [],
                    "proximas": []}
    transporte = _TransporteFake(
        respostas_get={
            "portal.exemplo.dev": _RespostaFake(200, envelope_ok),
            "mcp.exemplo.dev": _RespostaFake(500, None),
        },
        respostas_post={
            "backboard.railway.com": _RespostaFake(
                200, {"data": {"deployments": {"edges": []}}},
            ),
        },
        excecoes_get={"boris.exemplo.dev": TimeoutError("timeout simulado")},
    )
    lista = [
        origens.OrigemMCP(transporte=transporte),
        origens.OrigemMydata(),
        origens.OrigemBoris(transporte=transporte),
        origens.OrigemPortal(transporte=transporte),
        origens.OrigemRailway(transporte=transporte),
    ]
    momento = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)

    coletor.coletar_tudo(sink, lista, agora=lambda: momento)

    linhas = sink.consultar("SELECT origem, ok, erro FROM console_coleta")
    assert len(linhas) == 5

    falhas = {l["origem"] for l in linhas if not l["ok"]}
    sucessos = {l["origem"] for l in linhas if l["ok"]}
    assert falhas == {"mcp", "boris"}
    assert sucessos == {"mydata", "portal", "railway"}
    # As duas falhas carregam erro preenchido — nunca silencioso.
    assert all(l["erro"] for l in linhas if not l["ok"])

    metricas = sink.consultar(
        "SELECT DISTINCT sistema FROM console_metrica_diaria"
    )
    sistemas_com_metrica = {m["sistema"] for m in metricas}
    # As origens boas (mydata, portal) derivam métrica; as duas ruins não.
    assert "mydata" in sistemas_com_metrica
    assert "portal" in sistemas_com_metrica
    assert "mcp" not in sistemas_com_metrica
    assert "boris" not in sistemas_com_metrica


# --------------------------------------------------------------------------
# (g) migração idempotente, em DuckDB em memória.
# --------------------------------------------------------------------------
def test_migracao_0021_console_aplica_em_duckdb_e_e_idempotente():
    from app import migracoes

    s = SinkDuckDB(":memory:")
    try:
        primeira = migracoes.aplicar(s)
        assert "0021_console" in primeira

        segunda = migracoes.aplicar(s)
        assert segunda == []  # rodar de novo é no-op

        agora = datetime.now(timezone.utc)
        id_ = s.proximo_id("console_coleta")
        s.executar(
            "INSERT INTO console_coleta (id, origem, quando, ok, duracao_ms, erro) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (id_, "mcp", agora, True, 12, None),
        )
        linha = s.um("SELECT * FROM console_coleta WHERE id = ?", (id_,))
        assert linha["origem"] == "mcp"
        assert linha["ok"] is True

        s.executar(
            "INSERT INTO console_metrica_diaria (dia, sistema, metrica, valor, fonte) "
            "VALUES (?, ?, ?, ?, ?)",
            ("2026-09-27", "mcp", "situacao", "ok", "/observabilidade"),
        )
        s.executar(
            "INSERT INTO console_deploy "
            "(sistema, ambiente, deploy_id, commit_sha, quando, status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("mcp", "production", "dep-1", "abc123", agora, "SUCCESS"),
        )
    finally:
        s.fechar()


# --------------------------------------------------------------------------
# (e)/(f) auth compartilhada com o admin, e /situacao por sessão.
# --------------------------------------------------------------------------
@pytest.fixture()
def cliente_console(tmp_path, monkeypatch):
    monkeypatch.setenv("PORTAL_DUCKDB", str(tmp_path / "console.duckdb"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("PORTAL_ADMIN_TOKEN", TOKEN)
    # Crítico: sem CONSOLE_COLETOR=1 o agendador não nasce — o mydata sobe
    # exatamente como sobe hoje. Este teste prova isso implicitamente: se o
    # agendador tentasse subir aqui, ele chamaria rede real e o teste falharia.
    monkeypatch.delenv("CONSOLE_COLETOR", raising=False)

    s = SinkDuckDB(str(tmp_path / "console.duckdb"))
    bootstrap.preparar(s)
    s.fechar()

    from app.api.main import app

    with TestClient(app) as c:
        yield c


def test_sem_sessao_a_console_recusa_como_o_resto_do_admin(cliente_console):
    r = cliente_console.get("/admin/api/console/situacao")
    assert r.status_code == 401


def test_com_sessao_indisponivel_desde_e_so_de_quem_falhou(cliente_console, monkeypatch):
    from app.api.main import app

    sink = app.state.sink
    monkeypatch.setenv("CONSOLE_MCP_URL", "https://mcp.exemplo.dev")
    monkeypatch.setenv("CONSOLE_MCP_BEARER", "tok-mcp")

    transporte = _TransporteFake(
        excecoes_get={"mcp.exemplo.dev": TimeoutError("timeout simulado")},
    )
    lista = [origens.OrigemMCP(transporte=transporte), origens.OrigemMydata()]
    momento = datetime(2026, 9, 27, 9, 0, tzinfo=timezone.utc)
    coletor.coletar_tudo(sink, lista, agora=lambda: momento)

    cliente_console.post("/entrar", data={"token": TOKEN}, follow_redirects=False)
    r = cliente_console.get("/admin/api/console/situacao")
    assert r.status_code == 200

    por_origem = {d["origem"]: d for d in r.json()["dados"]}
    assert por_origem["mcp"]["ok"] is False
    assert por_origem["mcp"]["indisponivel_desde"] is not None
    assert por_origem["mydata"]["ok"] is True
    assert por_origem["mydata"]["indisponivel_desde"] is None
    # As três origens sem nenhuma coleta ainda não aparecem como falha.
    assert por_origem["boris"]["indisponivel_desde"] is None


# --------------------------------------------------------------------------
# Token de máquina (client_credentials) — transporte fake, zero rede.
# --------------------------------------------------------------------------
def test_token_e_pedido_com_basic_e_form_certos(sink, mcp_com_client):
    transporte = _TransporteFake(
        respostas_form=[_token("tok-1")],
        respostas_get={"mcp.exemplo.dev": _RespostaFake(200, ENVELOPE_OK)},
    )

    resultado = origens.OrigemMCP(transporte=transporte).coletar(sink)

    assert resultado.ok is True
    (pedido,) = transporte.chamadas_form
    assert pedido["url"] == "https://id.semente.dev/token"
    assert pedido["auth"] == (CLIENT_ID, CLIENT_SECRET)  # o transporte faz o Basic
    assert pedido["timeout"] == 5.0
    # Guardião (ii): só client_credentials, e exatamente um `resource`.
    assert pedido["data"] == {
        "grant_type": "client_credentials",
        "resource": "https://mcp.exemplo.dev/mcp",
    }
    # O segredo não vai em URL nem no corpo do form.
    assert CLIENT_SECRET not in pedido["url"]
    assert CLIENT_SECRET not in str(pedido["data"])
    # O GET leva o token recebido como Bearer.
    (_, url, headers, _) = [c for c in transporte.chamadas if c[0] == "get"][0]
    assert url == "https://mcp.exemplo.dev/observabilidade"
    assert headers == {"Authorization": "Bearer tok-1"}


def test_url_do_endpoint_de_token_vem_do_ambiente(sink, mcp_com_client, monkeypatch):
    monkeypatch.setenv("CONSOLE_ID_TOKEN_URL", "https://id.exemplo.dev/oauth/token")
    transporte = _TransporteFake(
        respostas_form=[_token("tok-1")],
        respostas_get={"mcp.exemplo.dev": _RespostaFake(200, ENVELOPE_OK)},
    )
    origens.OrigemMCP(transporte=transporte).coletar(sink)
    assert transporte.chamadas_form[0]["url"] == "https://id.exemplo.dev/oauth/token"


def test_resource_do_mcp_e_a_url_publica_mais_mcp(sink, mcp_com_client):
    transporte = _TransporteFake(
        respostas_form=[_token("tok-1")],
        respostas_get={"mcp.exemplo.dev": _RespostaFake(200, ENVELOPE_OK)},
    )
    origens.OrigemMCP(transporte=transporte).coletar(sink)
    assert transporte.chamadas_form[0]["data"]["resource"] == "https://mcp.exemplo.dev/mcp"


def test_cache_reaproveita_o_token_entre_duas_coletas(sink, mcp_com_client):
    transporte = _TransporteFake(
        respostas_form=[_token("tok-1", 3600)],
        respostas_get={"mcp.exemplo.dev": _RespostaFake(200, ENVELOPE_OK)},
    )
    origem = origens.OrigemMCP(transporte=transporte)

    assert origem.coletar(sink).ok is True
    assert origem.coletar(sink).ok is True

    assert len(transporte.chamadas_form) == 1
    gets = [c for c in transporte.chamadas if c[0] == "get"]
    assert len(gets) == 2
    assert all(g[2] == {"Authorization": "Bearer tok-1"} for g in gets)


def test_token_e_renovado_quando_faltam_menos_de_60s(sink, mcp_com_client, monkeypatch):
    agora = [1000.0]
    monkeypatch.setattr(credencial, "_relogio", lambda: agora[0])
    transporte = _TransporteFake(
        respostas_form=[_token("tok-1", 120), _token("tok-2", 120)],
        respostas_get={"mcp.exemplo.dev": _RespostaFake(200, ENVELOPE_OK)},
    )
    origem = origens.OrigemMCP(transporte=transporte)

    origem.coletar(sink)                # t=0: pede tok-1 (vence em t=120)
    agora[0] = 1000.0 + 59              # faltam 61 s: ainda vale
    origem.coletar(sink)
    assert len(transporte.chamadas_form) == 1

    agora[0] = 1000.0 + 61              # faltam 59 s: renova
    origem.coletar(sink)
    assert len(transporte.chamadas_form) == 2

    gets = [c for c in transporte.chamadas if c[0] == "get"]
    assert [g[2]["Authorization"] for g in gets] == [
        "Bearer tok-1", "Bearer tok-1", "Bearer tok-2",
    ]


@pytest.mark.parametrize("expires_in", [None, "abc", 0, -5, True])
def test_expires_in_ausente_ou_ilegivel_nao_cacheia(sink, mcp_com_client, expires_in):
    transporte = _TransporteFake(
        respostas_form=[_token("tok-1", expires_in), _token("tok-2", expires_in)],
        respostas_get={"mcp.exemplo.dev": _RespostaFake(200, ENVELOPE_OK)},
    )
    origem = origens.OrigemMCP(transporte=transporte)
    origem.coletar(sink)
    origem.coletar(sink)
    assert len(transporte.chamadas_form) == 2


def test_cache_e_por_recurso(sink, com_client, monkeypatch):
    monkeypatch.setenv("CONSOLE_MCP_URL", "https://mcp.exemplo.dev")
    monkeypatch.delenv("CONSOLE_MCP_BEARER", raising=False)
    monkeypatch.setenv("CONSOLE_PORTAL_URL", "https://portal.exemplo.dev")
    transporte = _TransporteFake(
        respostas_form=[_token("tok-mcp"), _token("tok-portal")],
        respostas_get={
            "mcp.exemplo.dev": _RespostaFake(200, ENVELOPE_OK),
            "portal.exemplo.dev": _RespostaFake(200, ENVELOPE_OK),
        },
    )
    origens.OrigemMCP(transporte=transporte).coletar(sink)
    origens.OrigemPortal(transporte=transporte).coletar(sink)

    assert [p["data"]["resource"] for p in transporte.chamadas_form] == [
        "https://mcp.exemplo.dev/mcp", "https://portal.exemplo.dev",
    ]
    gets = {c[1]: c[2]["Authorization"] for c in transporte.chamadas if c[0] == "get"}
    assert gets["https://mcp.exemplo.dev/observabilidade"] == "Bearer tok-mcp"
    assert gets["https://portal.exemplo.dev/observabilidade"] == "Bearer tok-portal"


def test_401_no_envelope_invalida_e_renova_uma_vez(sink, mcp_com_client):
    transporte = _TransporteFake(
        respostas_form=[_token("tok-velho"), _token("tok-novo")],
        sequencias_get={"mcp.exemplo.dev": [
            _RespostaFake(401, None), _RespostaFake(200, ENVELOPE_OK),
        ]},
    )
    resultado = origens.OrigemMCP(transporte=transporte).coletar(sink)

    assert resultado.ok is True
    assert len(transporte.chamadas_form) == 2
    gets = [c for c in transporte.chamadas if c[0] == "get"]
    assert [g[2]["Authorization"] for g in gets] == ["Bearer tok-velho", "Bearer tok-novo"]

    # O token novo ficou em cache: a próxima coleta não pede outro.
    transporte._sequencias_get["mcp.exemplo.dev"] = [_RespostaFake(200, ENVELOPE_OK)]
    origens.OrigemMCP(transporte=transporte).coletar(sink)
    assert len(transporte.chamadas_form) == 2


def test_401_persistente_para_depois_de_uma_renovacao(sink, mcp_com_client):
    transporte = _TransporteFake(
        respostas_form=[_token("tok-1"), _token("tok-2")],
        sequencias_get={"mcp.exemplo.dev": [
            _RespostaFake(401, None), _RespostaFake(401, None),
        ]},
    )
    resultado = origens.OrigemMCP(transporte=transporte).coletar(sink)

    assert resultado.ok is False
    assert resultado.erro == "http_401"
    assert len(transporte.chamadas_form) == 2
    assert len([c for c in transporte.chamadas if c[0] == "get"]) == 2


def test_portal_usa_token_com_recurso_padrao_e_renova_no_401(sink, com_client, monkeypatch):
    monkeypatch.setenv("CONSOLE_PORTAL_URL", "https://b-mcp.exemplo.dev/")
    transporte = _TransporteFake(
        respostas_form=[_token("tok-a"), _token("tok-b")],
        sequencias_get={"b-mcp.exemplo.dev": [
            _RespostaFake(401, None), _RespostaFake(200, ENVELOPE_OK),
        ]},
    )
    resultado = origens.OrigemPortal(transporte=transporte).coletar(sink)

    assert resultado.ok is True
    assert [p["data"]["resource"] for p in transporte.chamadas_form] == [
        "https://b-mcp.exemplo.dev", "https://b-mcp.exemplo.dev",
    ]
    gets = [c for c in transporte.chamadas if c[0] == "get"]
    assert [g[2]["Authorization"] for g in gets] == ["Bearer tok-a", "Bearer tok-b"]


def test_portal_respeita_recurso_configurado(sink, com_client, monkeypatch):
    monkeypatch.setenv("CONSOLE_PORTAL_URL", "https://b-mcp.exemplo.dev")
    monkeypatch.setenv("CONSOLE_PORTAL_RECURSO", "https://outro.exemplo.dev/api")
    transporte = _TransporteFake(
        respostas_form=[_token("tok-a")],
        respostas_get={"b-mcp.exemplo.dev": _RespostaFake(200, ENVELOPE_OK)},
    )
    origens.OrigemPortal(transporte=transporte).coletar(sink)
    assert transporte.chamadas_form[0]["data"]["resource"] == "https://outro.exemplo.dev/api"


def test_portal_sem_client_chama_sem_authorization(sink, monkeypatch):
    monkeypatch.setenv("CONSOLE_PORTAL_URL", "https://b-mcp.exemplo.dev")
    transporte = _TransporteFake(
        respostas_get={"b-mcp.exemplo.dev": _RespostaFake(200, ENVELOPE_OK)},
    )
    resultado = origens.OrigemPortal(transporte=transporte).coletar(sink)

    assert resultado.ok is True
    assert transporte.chamadas_form == []
    (_, _url, headers, _) = transporte.chamadas[0]
    assert headers is None


def test_mcp_com_bearer_estatico_funciona_sem_client(sink, monkeypatch):
    monkeypatch.setenv("CONSOLE_MCP_URL", "https://mcp.exemplo.dev")
    monkeypatch.setenv("CONSOLE_MCP_BEARER", "tok-estatico")
    transporte = _TransporteFake(
        respostas_get={"mcp.exemplo.dev": _RespostaFake(200, ENVELOPE_OK)},
    )
    resultado = origens.OrigemMCP(transporte=transporte).coletar(sink)

    assert resultado.ok is True
    assert transporte.chamadas_form == []
    assert transporte.chamadas[0][2] == {"Authorization": "Bearer tok-estatico"}


def test_mcp_bearer_estatico_tem_precedencia_sobre_o_client(sink, mcp_com_client, monkeypatch):
    monkeypatch.setenv("CONSOLE_MCP_BEARER", "tok-estatico")
    transporte = _TransporteFake(
        respostas_get={"mcp.exemplo.dev": _RespostaFake(200, ENVELOPE_OK)},
    )
    assert origens.OrigemMCP(transporte=transporte).coletar(sink).ok is True
    assert transporte.chamadas_form == []


def test_mcp_com_url_mas_sem_bearer_e_sem_client_e_nao_configurada(sink, monkeypatch):
    monkeypatch.setenv("CONSOLE_MCP_URL", "https://mcp.exemplo.dev")
    monkeypatch.delenv("CONSOLE_MCP_BEARER", raising=False)
    transporte = _TransporteFake()
    resultado = origens.OrigemMCP(transporte=transporte).coletar(sink)
    assert resultado.erro == "nao_configurada"
    assert transporte.chamadas == []


def test_mcp_com_client_mas_sem_url_e_nao_configurada(sink, com_client, monkeypatch):
    monkeypatch.delenv("CONSOLE_MCP_URL", raising=False)
    transporte = _TransporteFake()
    resultado = origens.OrigemMCP(transporte=transporte).coletar(sink)
    assert resultado.erro == "nao_configurada"
    assert transporte.chamadas == []


@pytest.mark.parametrize("resposta, codigo", [
    (_RespostaFake(401, {"error": "invalid_client"}), "token_http_401"),
    (_RespostaFake(503, None), "token_http_503"),
    (TimeoutError("timeout simulado"), "token_rede"),
    (_RespostaFake(200, {"expires_in": 60}), "token_invalido"),
    (_RespostaFake(200, {"access_token": "", "expires_in": 60}), "token_invalido"),
    (_RespostaFake(200, ["nao", "e", "objeto"]), "token_invalido"),
])
def test_falha_do_endpoint_de_token_vira_ok_false_com_codigo(
    sink, mcp_com_client, resposta, codigo,
):
    transporte = _TransporteFake(respostas_form=[resposta])
    resultado = origens.OrigemMCP(transporte=transporte).coletar(sink)

    assert resultado.ok is False
    assert resultado.erro == codigo
    # Sem retentativa do token e sem GET no envelope.
    assert len(transporte.chamadas_form) == 1
    assert [c for c in transporte.chamadas if c[0] == "get"] == []
    assert CLIENT_SECRET not in (resultado.erro or "")


def test_json_ilegivel_no_token_e_token_invalido(sink, mcp_com_client):
    class _Quebrada:
        status_code = 200

        def json(self):
            raise ValueError("não é JSON")

    transporte = _TransporteFake(respostas_form=[_Quebrada()])
    resultado = origens.OrigemMCP(transporte=transporte).coletar(sink)
    assert resultado.erro == "token_invalido"


def test_falha_de_token_nao_derruba_as_outras_origens(sink, com_client, monkeypatch):
    monkeypatch.setenv("CONSOLE_MCP_URL", "https://mcp.exemplo.dev")
    monkeypatch.delenv("CONSOLE_MCP_BEARER", raising=False)
    monkeypatch.setenv("CONSOLE_BORIS_URL", "https://boris.exemplo.dev")
    monkeypatch.setenv("CONSOLE_BORIS_OBS_CHAVE", "chave-boris")
    transporte = _TransporteFake(
        respostas_form=[_RespostaFake(401, {"error": "invalid_client"})],
        respostas_get={"boris.exemplo.dev": _RespostaFake(200, ENVELOPE_OK)},
    )
    lista = [
        origens.OrigemMCP(transporte=transporte),
        origens.OrigemMydata(),
        origens.OrigemBoris(transporte=transporte),
    ]
    coletor.coletar_tudo(
        sink, lista, agora=lambda: datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc),
    )

    linhas = {l["origem"]: l for l in sink.consultar(
        "SELECT origem, ok, erro FROM console_coleta")}
    assert linhas["mcp"]["ok"] is False
    assert linhas["mcp"]["erro"] == "token_http_401"
    assert linhas["mydata"]["ok"] is True
    assert linhas["boris"]["ok"] is True


def test_client_incompleto_nao_conta_como_configurado(monkeypatch):
    monkeypatch.setenv("CONSOLE_CLIENT_ID", CLIENT_ID)
    monkeypatch.delenv("CONSOLE_CLIENT_SECRET", raising=False)
    assert credencial.client_configurado() is False
    assert credencial.token_para("https://x.exemplo.dev", _TransporteFake()) is None


def test_invalidar_forca_novo_pedido(com_client):
    transporte = _TransporteFake(respostas_form=[_token("tok-1"), _token("tok-2")])
    assert credencial.token_para("r", transporte) == "tok-1"
    assert credencial.token_para("r", transporte) == "tok-1"
    credencial.invalidar("r")
    assert credencial.token_para("r", transporte) == "tok-2"


# --------------------------------------------------------------------------
# "Não configurada" não é indisponibilidade; /situacao expõe `configurada`.
# --------------------------------------------------------------------------
def _gravar(sink, origem, quando, ok, erro):
    id_ = sink.proximo_id("console_coleta")
    sink.executar(
        "INSERT INTO console_coleta (id, origem, quando, ok, duracao_ms, erro) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (id_, origem, quando, ok, 0, erro),
    )


def test_situacao_nao_configurada_nao_e_indisponivel(cliente_console):
    from app.api.main import app

    sink = app.state.sink
    momento = datetime(2026, 9, 28, 9, 0, tzinfo=timezone.utc)
    # boris: nunca configurado, várias linhas nao_configurada.
    for minuto in range(3):
        _gravar(sink, "boris", momento.replace(minute=minuto), False, "nao_configurada")
    # mcp: falha real.
    _gravar(sink, "mcp", momento, False, "http_500")
    # railway: falhou e depois foi desconfigurado.
    _gravar(sink, "railway", momento, False, "http_500")
    _gravar(sink, "railway", momento.replace(minute=30), False, "nao_configurada")
    # portal: ok, depois desconfigurado, depois ok de novo.
    _gravar(sink, "portal", momento, True, None)
    _gravar(sink, "portal", momento.replace(minute=10), False, "nao_configurada")

    cliente_console.post("/entrar", data={"token": TOKEN}, follow_redirects=False)
    r = cliente_console.get("/admin/api/console/situacao")
    assert r.status_code == 200
    por_origem = {d["origem"]: d for d in r.json()["dados"]}

    assert por_origem["boris"]["indisponivel_desde"] is None
    assert por_origem["boris"]["configurada"] is False
    assert por_origem["railway"]["indisponivel_desde"] is None
    assert por_origem["railway"]["configurada"] is False
    assert por_origem["portal"]["indisponivel_desde"] is None
    assert por_origem["portal"]["configurada"] is False

    assert por_origem["mcp"]["indisponivel_desde"] is not None
    assert por_origem["mcp"]["configurada"] is True
    # Origem que nunca coletou é "configurada" (não há evidência em contrário).
    assert por_origem["mydata"]["configurada"] is True
    assert por_origem["mydata"]["indisponivel_desde"] is None


def test_nao_configurada_no_meio_nao_interrompe_a_janela_de_falha(cliente_console):
    """As linhas `nao_configurada` são ignoradas: nem quebram uma sequência de
    falhas (sucesso) nem entram nela (falha)."""
    from app.api.main import app

    sink = app.state.sink
    t = datetime(2026, 9, 28, 9, 0, tzinfo=timezone.utc)
    _gravar(sink, "mcp", t.replace(minute=0), True, None)
    _gravar(sink, "mcp", t.replace(minute=5), False, "http_500")
    _gravar(sink, "mcp", t.replace(minute=10), False, "nao_configurada")
    _gravar(sink, "mcp", t.replace(minute=15), False, "http_500")

    cliente_console.post("/entrar", data={"token": TOKEN}, follow_redirects=False)
    por_origem = {d["origem"]: d for d in
                  cliente_console.get("/admin/api/console/situacao").json()["dados"]}
    assert por_origem["mcp"]["configurada"] is True
    desde = por_origem["mcp"]["indisponivel_desde"]
    # Início da janela = a falha das 09:05 (a das 09:15 é posterior a ela).
    assert datetime.fromisoformat(desde) == t.replace(minute=5)


# --------------------------------------------------------------------------
# Log por origem por ciclo.
# --------------------------------------------------------------------------
_FORMATO_LOG = re.compile(
    r"^console coleta origem=(?P<origem>\w+) ok=(?P<ok>True|False) "
    r"duracao_ms=(?P<ms>\d+) erro=(?P<erro>\S.*)$"
)


def test_coletar_tudo_loga_uma_linha_por_origem_sem_segredo(
    sink, com_client, monkeypatch, caplog,
):
    monkeypatch.setenv("CONSOLE_MCP_URL", "https://mcp.exemplo.dev")
    monkeypatch.delenv("CONSOLE_MCP_BEARER", raising=False)
    monkeypatch.setenv("CONSOLE_BORIS_URL", "https://boris.exemplo.dev")
    monkeypatch.setenv("CONSOLE_BORIS_OBS_CHAVE", "chave-boris-secreta")
    monkeypatch.delenv("CONSOLE_PORTAL_URL", raising=False)
    monkeypatch.delenv("CONSOLE_RAILWAY_TOKEN", raising=False)
    transporte = _TransporteFake(
        respostas_form=[_token("tok-ultra-secreto")],
        sequencias_get={
            "mcp.exemplo.dev": [_RespostaFake(500, None), _RespostaFake(500, None)],
        },
        excecoes_get={
            "boris.exemplo.dev": TimeoutError(
                "falha com chave-boris-secreta e segredo " + CLIENT_SECRET
            ),
        },
    )
    lista = [
        origens.OrigemMCP(transporte=transporte),
        origens.OrigemMydata(),
        origens.OrigemBoris(transporte=transporte),
        origens.OrigemPortal(transporte=transporte),
        origens.OrigemRailway(transporte=transporte),
    ]
    with caplog.at_level(logging.INFO, logger="portal.console"):
        coletor.coletar_tudo(
            sink, lista, agora=lambda: datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc),
        )

    registros = [r for r in caplog.records if r.name == "portal.console"]
    assert len(registros) == 5
    assert all(r.levelno == logging.INFO for r in registros)

    por_origem = {}
    for r in registros:
        m = _FORMATO_LOG.match(r.getMessage())
        assert m, r.getMessage()
        por_origem[m["origem"]] = m
    assert list(por_origem) == ["mcp", "mydata", "boris", "portal", "railway"]
    assert por_origem["mcp"]["ok"] == "False" and por_origem["mcp"]["erro"] == "http_500"
    assert por_origem["mydata"]["ok"] == "True" and por_origem["mydata"]["erro"] == "-"
    assert por_origem["boris"]["ok"] == "False"
    assert por_origem["portal"]["erro"] == "nao_configurada"
    assert por_origem["railway"]["erro"] == "nao_configurada"

    texto = caplog.text
    for segredo in (CLIENT_SECRET, "tok-ultra-secreto", "chave-boris-secreta",
                    "Bearer", "Authorization", "https://"):
        assert segredo not in texto, segredo


def test_log_do_coletor_sai_mesmo_com_raiz_em_warning(monkeypatch):
    """Em produção o uvicorn não configura o raiz (WARNING); o `iniciar`
    garante um handler INFO só no logger da console."""
    import logging
    from app.console import coletor

    alvo = logging.getLogger("portal.console")
    antes = (list(alvo.handlers), alvo.level, alvo.propagate)
    try:
        alvo.handlers.clear()
        coletor._garantir_saida_do_log()
        assert alvo.isEnabledFor(logging.INFO)
        assert len(alvo.handlers) == 1 and alvo.propagate is False
        coletor._garantir_saida_do_log()
        assert len(alvo.handlers) == 1, "não duplica handler"
    finally:
        alvo.handlers[:] = antes[0]
        alvo.setLevel(antes[1])
        alvo.propagate = antes[2]
