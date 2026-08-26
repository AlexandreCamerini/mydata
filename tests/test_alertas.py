"""Alertas — a resposta pronta a "tem algo que eu precise fazer?".

Cada regra é testada pelo efeito que justifica a existência dela: falha
recente vira alerta crítico, credencial ausente de fonte ativa vira alerta
antes de a carga quebrar, e sistema sem problema responde `ok` — porque
alarme que grita à toa ensina a ignorar alarme.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app import agenda
from app.motor import alertas


# --------------------------------------------------------------------------
# proxima_ocorrencia — o espelho de ultima_ocorrencia, para a frente
# --------------------------------------------------------------------------
def test_proxima_ocorrencia_no_mesmo_dia():
    agora = datetime(2026, 8, 26, 10, 0, tzinfo=timezone.utc)
    proxima = agenda.proxima_ocorrencia("59 23 * * 1-5", agora)
    assert proxima == datetime(2026, 8, 26, 23, 59, tzinfo=timezone.utc)


def test_proxima_ocorrencia_pula_fim_de_semana():
    # 2026-08-28 é sexta; depois das 23:59 dela, o próximo 1-5 é segunda.
    agora = datetime(2026, 8, 28, 23, 59, tzinfo=timezone.utc)
    proxima = agenda.proxima_ocorrencia("59 23 * * 1-5", agora)
    assert proxima == datetime(2026, 8, 31, 23, 59, tzinfo=timezone.utc)


def test_proxima_ocorrencia_e_estritamente_futura():
    agora = datetime(2026, 8, 26, 6, 0, tzinfo=timezone.utc)
    proxima = agenda.proxima_ocorrencia("0 6 * * *", agora)
    assert proxima == datetime(2026, 8, 27, 6, 0, tzinfo=timezone.utc)


# --------------------------------------------------------------------------
# ativos() — o semáforo
# --------------------------------------------------------------------------
def test_sistema_recem_configurado_nao_grita(sink_cvm):
    """Base configurada e nunca carregada gera atenção (classes sem carga),
    nunca crítico: nada quebrou ainda."""
    estado = alertas.ativos(sink_cvm)
    assert estado["resumo"]["critico"] == 0
    assert estado["resumo"]["situacao"] in ("ok", "atencao")


def test_falha_recente_vira_alerta_critico(sink_cvm):
    agora = datetime.now(timezone.utc)
    sink_cvm.executar(
        "INSERT INTO log_execucao (id, dataset_chave, janela, status, erro, "
        "iniciado_em, terminado_em) VALUES (?,?,?,?,?,?,?)",
        (sink_cvm.proximo_id("log_execucao"), "cvm_dfp", "2023", "falha",
         "boom", agora - timedelta(minutes=30), agora - timedelta(minutes=29)),
    )
    estado = alertas.ativos(sink_cvm)
    tipos = {a["tipo"]: a for a in estado["alertas"]}
    assert "execucao_falhou" in tipos
    assert tipos["execucao_falhou"]["severidade"] == "critico"
    assert estado["resumo"]["situacao"] == "critico"
    # Crítico vem primeiro na lista — é a ordem que a tela pinta.
    assert estado["alertas"][0]["severidade"] == "critico"


def test_falha_antiga_nao_alarma(sink_cvm):
    antigo = datetime.now(timezone.utc) - timedelta(days=3)
    sink_cvm.executar(
        "INSERT INTO log_execucao (id, dataset_chave, janela, status, erro, "
        "iniciado_em, terminado_em) VALUES (?,?,?,?,?,?,?)",
        (sink_cvm.proximo_id("log_execucao"), "cvm_dfp", "2023", "falha",
         "boom antigo", antigo, antigo),
    )
    estado = alertas.ativos(sink_cvm)
    assert not any(a["tipo"] == "execucao_falhou" for a in estado["alertas"])


def test_bloqueio_de_gate_e_atencao_nao_critico(sink_cvm):
    """Gate retendo linhas é o sistema funcionando — pede olhar, não pânico."""
    agora = datetime.now(timezone.utc)
    sink_cvm.executar(
        "INSERT INTO log_execucao (id, dataset_chave, janela, status, erro, "
        "iniciado_em, terminado_em) VALUES (?,?,?,?,?,?,?)",
        (sink_cvm.proximo_id("log_execucao"), "cvm_dfp", "2023", "bloqueada",
         "regra reteve 3 linhas", agora, agora),
    )
    tipos = {a["tipo"]: a for a in alertas.ativos(sink_cvm)["alertas"]}
    assert tipos["execucao_bloqueada"]["severidade"] == "atencao"


def test_todo_alerta_carrega_acao(sink_cvm):
    agora = datetime.now(timezone.utc)
    sink_cvm.executar(
        "INSERT INTO log_execucao (id, dataset_chave, janela, status, erro, "
        "iniciado_em, terminado_em) VALUES (?,?,?,?,?,?,?)",
        (sink_cvm.proximo_id("log_execucao"), "cvm_dfp", "2023", "falha",
         "boom", agora, agora),
    )
    for a in alertas.ativos(sink_cvm)["alertas"]:
        assert a["acao"]["rota"].startswith("#/"), a
        assert a["acao"]["rotulo"], a


# --------------------------------------------------------------------------
# proximas_execucoes — a agenda que nunca teve tela
# --------------------------------------------------------------------------
def test_proximas_execucoes_traz_todo_agendamento_com_proxima(sink_cvm):
    lista = alertas.proximas_execucoes(sink_cvm)
    assert lista, "o seed declara agendamentos; a lista não pode sair vazia"
    for item in lista:
        assert item["cron"]
        if item["ativo"]:
            assert item["proxima"] is not None, item["chave"]
