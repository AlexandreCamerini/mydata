"""Etapa 5 — as três perguntas do operador.

O que está desatualizado, o que quebrou, e de onde veio este número. Todas
respondidas por classe, porque é assim que quem opera pensa: "a Empresa está
velha", não "o cvm_cadastro não rodou".
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import bootstrap, seed_fontes
from app.api import auth
from app.motor import ingestao, observabilidade as obs
from app.sinks import SinkDuckDB


def baixador(mapa):
    def _baixar(url: str, cabecalhos=None) -> bytes:
        for chave, dado in mapa.items():
            if chave in url:
                return dado
        raise AssertionError(f"URL não prevista: {url}")
    return _baixar


@pytest.fixture()
def carregado(sink_cvm, zip_dfp_2023, csv_cadastro):
    ingestao.executar(sink_cvm, "cvm_dfp", "2023",
                      baixar=baixador({"dfp_cia_aberta_2023.zip": zip_dfp_2023}))
    ingestao.executar(sink_cvm, "cvm_cadastro", "atual",
                      baixar=baixador({"cad_cia_aberta.csv": csv_cadastro}))
    return sink_cvm


# --------------------------------------------------------------------------
# O que está desatualizado
# --------------------------------------------------------------------------
def test_frescor_lista_toda_classe_com_idade_e_situacao(carregado):
    por_classe = {f["classe"]: f for f in obs.frescor(carregado)}
    assert set(por_classe) == {"demonstracao_financeira", "empresa",
                               "instrumento_b3", "provento_b3",
                               "indicador_macro", "negociacao_b3"}
    # A fixture carrega CVM e B3; o BCB, o COTAHIST e o cadastro de
    # instrumentos estão configurados e nunca foram ingeridos, e é justamente
    # o caso que o frescor existe para não deixar passar.
    assert por_classe.pop("indicador_macro")["situacao"] == "sem_carga"
    assert por_classe.pop("negociacao_b3")["situacao"] == "sem_carga"
    assert por_classe.pop("instrumento_b3")["situacao"] == "sem_carga"
    assert por_classe.pop("provento_b3")["situacao"] == "sem_carga"
    for f in por_classe.values():
        assert f["situacao"] == "em_dia"
        assert f["idade_horas"] is not None and f["idade_horas"] < 1
        assert f["ultima_publicacao"] is not None


def test_classe_sem_carga_aparece_como_sem_carga(sink_cvm):
    """Classe configurada e nunca carregada não pode se confundir com classe
    em dia — é o caso mais fácil de passar despercebido."""
    for f in obs.frescor(sink_cvm):
        assert f["situacao"] == "sem_carga"
        assert f["idade_horas"] is None


def test_sla_estourado_marca_a_classe_como_atrasada(carregado):
    """Envelhece a execução para além do SLA em vez de esperar.

    A data vem calculada da aplicação, não de `INTERVAL` no SQL: a sintaxe de
    intervalo difere entre DuckDB e Postgres, e o teste roda nos dois.
    """
    from datetime import datetime, timedelta, timezone

    carregado.executar(
        "UPDATE log_execucao SET terminado_em = ?",
        (datetime.now(timezone.utc) - timedelta(days=400),),
    )
    por_classe = {f["classe"]: f for f in obs.frescor(carregado)}
    assert por_classe["empresa"]["situacao"] == "atrasada"
    assert por_classe["empresa"]["idade_horas"] > por_classe["empresa"]["sla_horas"]


def test_frescor_mostra_a_ultima_falha_ao_lado(carregado):
    """A classe pode estar em dia e ainda assim ter quebrado ontem: as duas
    informações precisam aparecer juntas, senão a falha some da vista.

    A falha é provocada por regra nova — o caso realista. Sujar a tabela não
    serviria: a recarga vem do bronze e desfaz a sujeira antes de validar.
    """
    from app import repositorio as repo

    ds = repo.dataset_vigente(carregado, "cvm_dfp")
    carregado.executar(
        """INSERT INTO cfg_regra_qualidade
           (id, dataset_id, nome, expressao_sql, severidade, descricao, ativo)
           VALUES (?,?,?,?,'bloqueia','regra nova reprova a carga',TRUE)""",
        (carregado.proximo_id("cfg_regra_qualidade"), ds["id"],
         "reapresentacao_inesperada",
         "SELECT 1 FROM fato_conta WHERE versao > 1"),
    )
    ingestao.executar(carregado, "cvm_dfp", "2023", baixar=None)

    dfp = [f for f in obs.frescor(carregado)
           if f["classe"] == "demonstracao_financeira"][0]
    assert dfp["situacao"] == "em_dia", "a última publicação boa continua valendo"
    assert dfp["ultima_falha"] is not None
    assert dfp["ultima_falha"]["status"] == "bloqueada"
    assert "reapresentacao_inesperada" in dfp["ultima_falha"]["erro"]


# --------------------------------------------------------------------------
# Onde a carga gastou o tempo
# --------------------------------------------------------------------------
def test_linha_do_tempo_cobre_o_ciclo_inteiro(carregado):
    execucao = carregado.um(
        "SELECT id FROM log_execucao WHERE dataset_chave = 'cvm_dfp' "
        "ORDER BY id LIMIT 1"
    )["id"]
    fases = obs.linha_do_tempo(carregado, execucao)
    assert [f["fase"] for f in fases] == [
        "baixar", "carregar", "calcular", "validar", "publicar"
    ]
    assert all(f["duracao_ms"] is not None for f in fases)


def test_fase_e_registrada_mesmo_quando_falha(sink_cvm):
    """Fase que só se registra no sucesso é inútil justamente quando importa."""
    exec_id = sink_cvm.proximo_id("log_execucao")
    sink_cvm.executar(
        "INSERT INTO log_execucao (id, dataset_chave, janela, status) "
        "VALUES (?, 'x', '2023', 'pendente')", (exec_id,)
    )
    with pytest.raises(RuntimeError):
        with obs.fase(sink_cvm, exec_id, "carregar"):
            raise RuntimeError("estourou no meio")
    fases = obs.linha_do_tempo(sink_cvm, exec_id)
    assert len(fases) == 1 and fases[0]["duracao_ms"] is not None


# --------------------------------------------------------------------------
# De onde veio este número
# --------------------------------------------------------------------------
def test_linhagem_de_atributo_calculado_mostra_a_expressao(carregado):
    l = obs.linhagem(carregado, "demonstracao_financeira", "vl_conta_norm")
    origem = l["origens"][0]
    assert "escala_moeda" in origem["expressao"]
    assert set(origem["colunas_que_usa"]) == {"vl_conta", "escala_moeda"}
    assert l["disputado"] is False


def test_linhagem_de_atributo_de_fonte_mostra_a_coluna_do_arquivo(carregado):
    l = obs.linhagem(carregado, "demonstracao_financeira", "vl_conta")
    origem = l["origens"][0]
    assert origem["coluna_de_origem"] == "VL_CONTA"
    assert origem["formato"] == "decimal_ptbr"
    assert origem["capturas_recentes"], "tem de chegar até a captura em bronze"
    assert origem["capturas_recentes"][0]["sha256"]


def test_linhagem_mostra_a_regra_que_aprovou(carregado):
    l = obs.linhagem(carregado, "demonstracao_financeira", "vl_conta")
    regras = {r["nome"] for r in l["origens"][0]["regras"]}
    assert "reconciliacao_ativo_passivo" in regras
    assert "escala_desconhecida" in regras


def test_linhagem_de_atributo_disputado_mostra_a_precedencia(carregado):
    l = obs.linhagem(carregado, "empresa", "denom_social")
    assert l["disputado"] is True
    assert l["precedencia"][0] == "cvm_cadastro"
    assert [o["dataset"] for o in l["origens"]] == l["precedencia"]
    assert "gold_empresa" in l["vistas"]


def test_linhagem_de_atributo_inexistente_diz_quais_existem(carregado):
    from app.repositorio import ErroConfiguracao

    with pytest.raises(ErroConfiguracao, match="denom_social"):
        obs.linhagem(carregado, "empresa", "razao_social")


# --------------------------------------------------------------------------
# Pela API
# --------------------------------------------------------------------------
@pytest.fixture()
def cliente(tmp_path, monkeypatch, zip_dfp_2023, csv_cadastro):
    banco = str(tmp_path / "obs.duckdb")
    monkeypatch.setenv("PORTAL_DUCKDB", banco)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("PORTAL_ADMIN_TOKEN", raising=False)

    s = SinkDuckDB(banco)
    bootstrap.preparar(s)
    seed_fontes.aplicar(s)
    ingestao.executar(s, "cvm_dfp", "2023",
                      baixar=baixador({"dfp_cia_aberta_2023.zip": zip_dfp_2023}))
    ingestao.executar(s, "cvm_cadastro", "atual",
                      baixar=baixador({"cad_cia_aberta.csv": csv_cadastro}))
    emitida = auth.emitir(s, "bolsia", quota_minuto=100)
    s.fechar()

    from app.api.main import app

    with TestClient(app) as c:
        c.headers.update({"X-API-Key": emitida.chave_completa})
        yield c


def test_endpoint_de_frescor(cliente):
    r = cliente.get("/v1/meta/frescor")
    assert r.status_code == 200
    classes = {d["classe"]: d["situacao"] for d in r.json()["dados"]}
    assert classes == {"demonstracao_financeira": "em_dia", "empresa": "em_dia",
                       "instrumento_b3": "sem_carga",
                       "provento_b3": "sem_carga",
                       "indicador_macro": "sem_carga",
                       "negociacao_b3": "sem_carga"}


def test_endpoint_de_linhagem(cliente):
    r = cliente.get("/v1/meta/linhagem",
                    params={"classe": "empresa", "atributo": "denom_social"})
    assert r.status_code == 200
    dado = r.json()["dados"]
    assert dado["disputado"] is True
    assert dado["precedencia"][0] == "cvm_cadastro"


def test_endpoint_de_linhagem_com_atributo_errado_devolve_404(cliente):
    r = cliente.get("/v1/meta/linhagem",
                    params={"classe": "empresa", "atributo": "inexistente"})
    assert r.status_code == 404
    assert r.json()["erro"]["codigo"] == "linhagem_nao_encontrada"


def test_endpoint_de_classes(cliente):
    r = cliente.get("/v1/meta/classes")
    por_chave = {d["chave"]: d for d in r.json()["dados"]}
    assert por_chave["empresa"]["resolucao"] == "precedencia"
    assert {"cvm_cadastro", "cvm_dfp_empresa", "b3_listadas"} <= set(
        por_chave["empresa"]["fontes"])


def test_endpoint_de_fases(cliente):
    execucoes = cliente.get("/admin/api/execucoes").json()["dados"]
    r = cliente.get(f"/v1/meta/execucoes/{execucoes[-1]['id']}/fases")
    assert [f["fase"] for f in r.json()["dados"]][0] == "baixar"
