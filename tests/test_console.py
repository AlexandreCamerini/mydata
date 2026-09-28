"""Bloco A da console central (ADR-25): guardiões, degradação por origem,
auth compartilhada com o admin, e idempotência da migração `0021_console`.

Nenhum teste aqui chama rede real — todo transporte é fake, injetado no
construtor de cada origem (mesmo espírito do `baixar=` de
`tests/conftest.py`).
"""
from __future__ import annotations

import pathlib
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app import bootstrap
from app.console import coletor, origens
from app.sinks import SinkDuckDB

TOKEN = "token-console-de-teste-com-tamanho-razoavel"

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
    """Roteia por substring da URL, como `baixador()` em conftest.py."""

    def __init__(self, *, respostas_get=None, respostas_post=None, excecoes_get=None):
        self.chamadas: list[tuple] = []
        self._get = respostas_get or {}
        self._post = respostas_post or {}
        self._excecoes_get = excecoes_get or {}

    def get(self, url, *, headers=None, timeout=5.0):
        self.chamadas.append(("get", url, headers, None))
        for chave, excecao in self._excecoes_get.items():
            if chave in url:
                raise excecao
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
# (b) guardião de escrita: o único POST do pacote é o GraphQL do Railway, e
# a operação enviada é sempre `query`, nunca `mutation`.
# --------------------------------------------------------------------------
def _ocorrencias(texto: str, padrao: str) -> list[str]:
    return [linha.strip() for linha in texto.splitlines() if padrao in linha]


def test_guardiao_pacote_so_tem_um_post_e_nenhum_verbo_de_escrita_http():
    """Só dois pontos do pacote emitem `POST` de verdade — o transporte real
    (`requests.post`, dentro de `_TransporteRequests`) e o único chamador
    dele (`self.transporte.post`, dentro de `OrigemRailway._chamar`) — e os
    dois são o mesmo GraphQL do Railway. `@router.post("/coletar")` é rota
    de entrada do próprio admin, não escrita contra origem externa, e fica
    fora desta contagem.
    """
    fontes = [c.read_text(encoding="utf-8") for c in PACOTE.glob("*.py")]

    chamadas_transporte_post = [l for f in fontes for l in _ocorrencias(f, ".transporte.post(")]
    assert len(chamadas_transporte_post) == 1, chamadas_transporte_post

    chamadas_requests_post = [l for f in fontes for l in _ocorrencias(f, "requests.post(")]
    assert len(chamadas_requests_post) == 1, chamadas_requests_post

    for verbo in ("put(", "patch(", "delete("):
        for alvo in ("requests.", ".transporte."):
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
