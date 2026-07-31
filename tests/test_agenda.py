"""O Railway acorda o processo; o processo decide o que está vencido.

Sem isto, `agendados` roda todos os datasets a cada invocação, e o cron do
painel vira a única frequência do sistema — a mesma para o cadastro semanal e
para a DFP anual. Um gatilho diário reingeriria 2 milhões de linhas por dia.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

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
