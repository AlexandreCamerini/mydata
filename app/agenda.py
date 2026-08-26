"""Quando um agendamento está vencido.

O Railway acorda o processo; é o processo que decide o que fazer. Sem isto,
`agendados` roda tudo a cada invocação: um gatilho diário reingeriria DFP e
ITR todo dia, e o cron do painel viraria a única frequência do sistema — a
mesma para o cadastro semanal e para a DFP anual.

Avaliador mínimo de cron, sem dependência nova: `*`, valores, listas `a,b`,
faixas `a-b` e passos `*/n`. É o que `cfg_agendamento` usa e o que a interface
oferece.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo

log = logging.getLogger("portal.agenda")


class ErroCron(ValueError):
    """Expressão de cron que não dá para avaliar."""


def _campo(valor: str, minimo: int, maximo: int) -> set[int]:
    if valor.strip() == "*":
        return set(range(minimo, maximo + 1))
    encontrados: set[int] = set()
    for parte in valor.split(","):
        parte = parte.strip()
        passo = 1
        if "/" in parte:
            parte, txt = parte.split("/", 1)
            passo = int(txt)
        if parte == "*":
            faixa = range(minimo, maximo + 1)
        elif "-" in parte:
            a, b = parte.split("-", 1)
            faixa = range(int(a), int(b) + 1)
        else:
            faixa = range(int(parte), int(parte) + 1)
        encontrados |= {v for i, v in enumerate(faixa) if i % passo == 0}
    fora = [v for v in encontrados if not minimo <= v <= maximo]
    if fora:
        raise ErroCron(f"valor fora da faixa {minimo}-{maximo}: {fora}")
    return encontrados


def _dia_casa(quando: datetime, doms: set[int], dows: set[int],
              dom_livre: bool, dow_livre: bool) -> bool:
    """Semântica do cron: com dia-do-mês e dia-da-semana ambos restritos, o
    dia casa se **qualquer um** casar — não os dois. É contraintuitivo e é a
    regra do padrão."""
    no_mes = quando.day in doms
    # `date.weekday()` é 0=segunda; o cron usa 0=domingo.
    na_semana = ((quando.weekday() + 1) % 7) in dows
    if dom_livre and dow_livre:
        return True
    if dom_livre:
        return na_semana
    if dow_livre:
        return no_mes
    return no_mes or na_semana


def ultima_ocorrencia(cron: str, agora: datetime, limite_dias: int = 400) -> datetime | None:
    """O momento mais recente, até `agora`, em que este cron deveria ter rodado."""
    campos = cron.split()
    if len(campos) != 5:
        raise ErroCron(f"cron precisa de 5 campos, recebeu {len(campos)}: {cron!r}")
    m, h, dom, mes, dow = campos
    minutos, horas = _campo(m, 0, 59), _campo(h, 0, 23)
    doms, meses, dows = _campo(dom, 1, 31), _campo(mes, 1, 12), _campo(dow, 0, 6)
    dom_livre, dow_livre = dom.strip() == "*", dow.strip() == "*"

    dia = agora.replace(second=0, microsecond=0)
    for passo in range(limite_dias):
        if dia.month in meses and _dia_casa(dia, doms, dows, dom_livre, dow_livre):
            candidatos = [
                dia.replace(hour=hh, minute=mm)
                for hh in horas for mm in minutos
                if passo > 0 or (hh, mm) <= (agora.hour, agora.minute)
            ]
            if candidatos:
                return max(candidatos)
        dia = (dia - timedelta(days=1)).replace(hour=23, minute=59)
    return None


def proxima_ocorrencia(cron: str, agora: datetime, limite_dias: int = 400) -> datetime | None:
    """O primeiro momento depois de `agora` em que este cron vai disparar.

    Espelho de `ultima_ocorrencia`, andando para a frente. É o que permite à
    interface mostrar "próxima carga do COTAHIST: hoje 23:59" — sem isto o
    operador só descobre o horário lendo a expressão de cron de cabeça.
    """
    campos = cron.split()
    if len(campos) != 5:
        raise ErroCron(f"cron precisa de 5 campos, recebeu {len(campos)}: {cron!r}")
    m, h, dom, mes, dow = campos
    minutos, horas = _campo(m, 0, 59), _campo(h, 0, 23)
    doms, meses, dows = _campo(dom, 1, 31), _campo(mes, 1, 12), _campo(dow, 0, 6)
    dom_livre, dow_livre = dom.strip() == "*", dow.strip() == "*"

    dia = agora.replace(second=0, microsecond=0)
    for passo in range(limite_dias):
        if dia.month in meses and _dia_casa(dia, doms, dows, dom_livre, dow_livre):
            candidatos = [
                dia.replace(hour=hh, minute=mm)
                for hh in horas for mm in minutos
                if passo > 0 or (hh, mm) > (agora.hour, agora.minute)
            ]
            if candidatos:
                return min(candidatos)
        dia = (dia + timedelta(days=1)).replace(hour=0, minute=0)
    return None


def zona(nome: str | None) -> tzinfo:
    """O fuso declarado no agendamento, com UTC como piso.

    `cfg_agendamento.timezone` existia desde o início e não era lido por
    ninguém: todo cron era avaliado em UTC. O efeito era um deslocamento de
    três horas que ninguém via, porque a hora do dia de uma carga em lote
    raramente denuncia — o `0 6` da DFP disparava às 03:00 de Brasília. Fuso
    desconhecido continua valendo UTC, e não é erro: derrubar o agendamento
    inteiro por causa de um nome de fuso seria pior que rodar deslocado.
    """
    if not nome:
        return timezone.utc
    try:
        return ZoneInfo(nome)
    except Exception:  # noqa: BLE001 — nome inválido não derruba a agenda
        log.warning("fuso desconhecido em agendamento: %r; usando UTC", nome)
        return timezone.utc


def ocorrencia_devida(cron: str, timezone_nome: str | None = None,
                      agora: datetime | None = None) -> datetime | None:
    """O momento em que este cron deveria ter disparado por último, no fuso
    dele. É de onde a janela sai — e não do relógio de quem acordou."""
    tz = zona(timezone_nome)
    agora = (agora or datetime.now(timezone.utc)).astimezone(tz)
    return ultima_ocorrencia(cron, agora)


def esta_vencido(cron: str, ultima_execucao: datetime | None,
                 agora: datetime | None = None,
                 timezone_nome: str | None = None) -> tuple[bool, str]:
    """(vencido, motivo). Vencido quando o cron deveria ter disparado depois
    da última execução bem-sucedida.

    O cron é lido no fuso do agendamento — `59 23` quer dizer 23:59 em São
    Paulo —, e a comparação com a última execução acontece em UTC, que é como
    o timestamp está gravado.
    """
    tz = zona(timezone_nome)
    agora = (agora or datetime.now(timezone.utc)).astimezone(tz)
    devida = ultima_ocorrencia(cron, agora)
    if devida is None:
        return False, "o cron não tem ocorrência no último ano"
    if ultima_execucao is None:
        return True, "nunca executado"
    if ultima_execucao.tzinfo is None:
        ultima_execucao = ultima_execucao.replace(tzinfo=timezone.utc)
    if ultima_execucao < devida:
        return True, f"devido em {devida:%Y-%m-%d %H:%M}, última em {ultima_execucao:%Y-%m-%d %H:%M}"
    return False, f"já rodou depois de {devida:%Y-%m-%d %H:%M}"
