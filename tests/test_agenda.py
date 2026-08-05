"""O Railway acorda o processo; o processo decide o que está vencido.

Sem isto, `agendados` roda todos os datasets a cada invocação, e o cron do
painel vira a única frequência do sistema — a mesma para o cadastro semanal e
para a DFP anual. Um gatilho diário reingeriria 2 milhões de linhas por dia.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app import agenda
from app.agenda import ErroCron, esta_vencido, ultima_ocorrencia

AGORA = datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc)   # sexta-feira


def em(ano, mes, dia, hora=0, minuto=0):
    return datetime(ano, mes, dia, hora, minuto, tzinfo=timezone.utc)


# --------------------------------------------------------------------------
# Leitura da expressão
# --------------------------------------------------------------------------
@pytest.mark.parametrize("cron,esperado", [
    ("0 5 * * 1", em(2026, 7, 27, 5)),          # segunda anterior
    ("0 6 1 4 *", em(2026, 4, 1, 6)),           # 1º de abril
    ("0 6 15 2,5,8,11 *", em(2026, 5, 15, 6)),  # trimestral, o mais recente
    ("*/30 * * * *", em(2026, 7, 31, 12, 0)),   # passo de 30 min
    ("0 0 1 1 *", em(2026, 1, 1, 0)),           # anual, no início do ano
])
def test_ultima_ocorrencia(cron, esperado):
    assert ultima_ocorrencia(cron, AGORA) == esperado


def test_hora_futura_do_mesmo_dia_nao_conta():
    """São 12h; um cron das 18h ainda não rodou hoje."""
    assert ultima_ocorrencia("0 18 * * *", AGORA) == em(2026, 7, 30, 18)


def test_dia_do_mes_e_dia_da_semana_juntos_sao_OU():
    """Regra do padrão, contraintuitiva: com os dois restritos, o dia casa se
    qualquer um casar. 31/07/2026 é sexta e não é dia 1 — mas casa pela sexta."""
    assert ultima_ocorrencia("0 8 1 * 5", AGORA) == em(2026, 7, 31, 8)


def test_cron_malformado_e_recusado():
    with pytest.raises(ErroCron, match="5 campos"):
        ultima_ocorrencia("0 6 1 4", AGORA)
    with pytest.raises(ErroCron, match="fora da faixa"):
        ultima_ocorrencia("0 99 * * *", AGORA)


# --------------------------------------------------------------------------
# Decisão de rodar
# --------------------------------------------------------------------------
def test_nunca_executado_esta_vencido():
    vencido, motivo = esta_vencido("0 5 * * 1", None, AGORA)
    assert vencido and motivo == "nunca executado"


def test_ja_rodou_depois_do_devido_nao_repete():
    """O caso que custa dinheiro: um gatilho diário não pode reingerir a DFP
    anual todo dia."""
    vencido, _ = esta_vencido("0 6 1 4 *", em(2026, 4, 1, 7), AGORA)
    assert not vencido


def test_rodou_antes_do_devido_esta_vencido():
    vencido, motivo = esta_vencido("0 5 * * 1", em(2026, 7, 20), AGORA)
    assert vencido and "devido em 2026-07-27" in motivo


def test_execucao_sem_fuso_e_tratada_como_utc():
    """O DuckDB devolve timestamp sem fuso em algumas consultas; comparar com
    um datetime consciente estouraria."""
    vencido, _ = esta_vencido("0 5 * * 1", datetime(2026, 7, 20), AGORA)
    assert vencido


# --------------------------------------------------------------------------
# Fuso — a coluna que existia e ninguém lia
# --------------------------------------------------------------------------
def test_cron_e_lido_no_fuso_declarado():
    """`59 23` em São Paulo é 02:59 do dia seguinte em UTC.

    Avaliado em UTC, o mesmo cron dispararia às 20:59 de Brasília. Três horas
    de deslocamento que a hora de uma carga em lote raramente denuncia — e
    que, num agendamento de pregão, muda o dia pedido.
    """
    # 03/08/2026 02:30 UTC = 23:30 de 02/08 em São Paulo: ainda não deu 23:59.
    agora = datetime(2026, 8, 3, 2, 30, tzinfo=timezone.utc)
    anterior = agenda.ultima_ocorrencia(
        "59 23 * * 1-5", agora.astimezone(agenda.zona("America/Sao_Paulo"))
    )
    assert anterior.strftime("%Y-%m-%d %H:%M") == "2026-07-31 23:59"

    # 04/08 03:30 UTC = 00:30 de terça em São Paulo: a segunda-feira já
    # disparou, e o pregão pedido é o dela.
    agora = datetime(2026, 8, 4, 3, 30, tzinfo=timezone.utc)
    anterior = agenda.ultima_ocorrencia(
        "59 23 * * 1-5", agora.astimezone(agenda.zona("America/Sao_Paulo"))
    )
    assert anterior.strftime("%Y-%m-%d %H:%M") == "2026-08-03 23:59"


def test_fuso_desconhecido_cai_em_utc_sem_derrubar_a_agenda():
    assert agenda.zona(None) is timezone.utc
    assert agenda.zona("Marte/Olympus") is timezone.utc
    assert agenda.zona("America/Sao_Paulo") is not timezone.utc


def test_janela_hoje_usa_o_fuso_do_agendamento(monkeypatch):
    """Às 23:59 em São Paulo já é o dia seguinte em UTC. Sem o fuso, o
    agendamento pediria o pregão de amanhã e tomaria 404 toda noite."""
    from app import cli

    class Congelado(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 8, 5, 2, 59, tzinfo=timezone.utc)

    monkeypatch.setattr(cli, "datetime", Congelado)
    assert cli.janela_corrente("hoje", "America/Sao_Paulo") == "2026-08-04"
    assert cli.janela_corrente("hoje") == "2026-08-05"
    assert cli.janela_corrente("dia_anterior", "America/Sao_Paulo") == "2026-08-03"


def test_a_janela_sai_da_ocorrencia_devida_nao_do_relogio():
    """O caso que o par cron+janela quase deixou passar.

    O Railway acorda o serviço na frequência dele; `agendados` é que decide o
    que está vencido. Acordado às 08:00 de terça, com o disparo de 23:59 de
    segunda ainda pendente, a janela tem de ser a de **segunda** — pelo
    relógio seria a de terça, cujo pregão nem fechou, e a carga tomaria 404
    todo dia sem que nada no agendamento parecesse errado.
    """
    from app import cli

    # 11:00 UTC de terça = 08:00 em São Paulo.
    acordou = datetime(2026, 8, 4, 11, 0, tzinfo=timezone.utc)
    devida = agenda.ocorrencia_devida(
        "59 23 * * 1-5", "America/Sao_Paulo", acordou
    )
    assert devida.strftime("%Y-%m-%d %H:%M") == "2026-08-03 23:59"
    assert cli.janela_corrente(
        "hoje", "America/Sao_Paulo", devida
    ) == "2026-08-03"
