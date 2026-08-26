"""O que precisa de intervenção agora, numa lista só.

Todo o estado que estas regras leem já existia — frescor, log_execucao,
credenciais, divergência de DDL, duração de carga, agendamento. O que não
existia era a resposta pronta à pergunta que o operador faz primeiro:
"tem algo que eu precise fazer?". Cada tela respondia um pedaço, nenhuma
respondia inteiro, e falha ficava enterrada no meio de cinquenta linhas.

Duas severidades, de propósito:

- ``critico`` — algo já quebrou ou vai quebrar sozinho: carga falhou, dado
  estourou o dobro do SLA, credencial de fonte ativa sumiu do ambiente.
- ``atencao`` — pede olhar humano, mas o sistema segue: SLA vencido dentro
  do dobro, gate retendo linhas, DDL divergente, duração fora do padrão.

Cada alerta carrega a ação — a rota da tela onde se age —, porque alarme sem
porta de saída é só ansiedade com timestamp.

O módulo não sabe o que é CVM nem B3: só lê configuração e log, como o resto
de ``app/motor/``.
"""
from __future__ import annotations

import statistics
from datetime import datetime, timedelta, timezone
from typing import Any

from .. import agenda
from .. import repositorio as repo
from ..sinks import Sink
from . import credenciais, ddl, observabilidade

# Um alerta: tipo, severidade, titulo, detalhe, acao {rotulo, rota}.
Alerta = dict[str, Any]

# Duração anômala: só acusa quando a última carga passou de N vezes a mediana
# das anteriores E de um piso absoluto — sem o piso, uma carga que foi de 2s
# para 8s viraria alerta, e ninguém age sobre 8 segundos.
FATOR_DURACAO = 3.0
PISO_DURACAO_MS = 60_000
MINIMO_AMOSTRAS = 4

# Agendamento vencido só vira alerta com folga sobre o horário devido: o cron
# do painel acorda de hora em hora, então "devido há 10 minutos" é operação
# normal, não incidente.
FOLGA_AGENDAMENTO = timedelta(hours=2)


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def _de_frescor(sink: Sink) -> list[Alerta]:
    saida: list[Alerta] = []
    for f in observabilidade.frescor(sink):
        rota = f"#/execucoes?classe={f['classe']}"
        if f["situacao"] == "atrasada":
            estouro = (f["idade_horas"] or 0) / f["sla_horas"] if f["sla_horas"] else 0
            saida.append({
                "tipo": "classe_atrasada",
                "severidade": "critico" if estouro >= 2 else "atencao",
                "titulo": f"{f['nome']} está {f['idade_horas']:.0f}h sem carga "
                          f"(SLA: {f['sla_horas']:.0f}h)",
                "detalhe": f"Última publicação: "
                           f"{(f['ultima_publicacao'] or {}).get('dataset_chave', '—')}. "
                           f"Fontes da classe: {', '.join(f['fontes']) or '—'}.",
                "acao": {"rotulo": "Ver execuções", "rota": rota},
            })
        elif f["situacao"] == "sem_carga" and f["fontes"]:
            # Classe com mapeamento declarado e nenhuma carga nunca: ou é
            # recém-configurada, ou a primeira carga nunca aconteceu. Vale um
            # olhar; sem fonte declarada não vale nem isso.
            saida.append({
                "tipo": "classe_sem_carga",
                "severidade": "atencao",
                "titulo": f"{f['nome']} nunca recebeu carga",
                "detalhe": f"Fontes declaradas: {', '.join(f['fontes'])}. "
                           "Dispare a primeira carga ou desative a classe.",
                "acao": {"rotulo": "Disparar carga", "rota": "#/execucoes"},
            })
    return saida


def _de_execucoes(sink: Sink, horas: int = 24) -> list[Alerta]:
    desde = _agora() - timedelta(hours=horas)
    linhas = sink.consultar(
        "SELECT dataset_chave, status, erro, terminado_em FROM log_execucao "
        "WHERE status IN ('falha', 'bloqueada') AND terminado_em >= ? "
        "ORDER BY terminado_em DESC",
        (desde,),
    )
    # Uma linha por dataset, não por tentativa: três falhas do mesmo dataset
    # são um problema, não três.
    por_dataset: dict[str, dict] = {}
    for ln in linhas:
        atual = por_dataset.setdefault(ln["dataset_chave"], {"n": 0, "ultima": ln})
        atual["n"] += 1
    saida: list[Alerta] = []
    for chave, info in por_dataset.items():
        ultima = info["ultima"]
        bloqueio = ultima["status"] == "bloqueada"
        saida.append({
            "tipo": "execucao_bloqueada" if bloqueio else "execucao_falhou",
            "severidade": "atencao" if bloqueio else "critico",
            "titulo": (f"Gate de qualidade bloqueou {chave}" if bloqueio
                       else f"Carga de {chave} falhou"
                       + (f" ({info['n']}× em {horas}h)" if info["n"] > 1 else "")),
            "detalhe": (ultima["erro"] or "Sem mensagem de erro registrada.")[:300],
            "acao": {"rotulo": "Ver execuções", "rota": "#/execucoes"},
        })
    return saida


def _de_credenciais(sink: Sink) -> list[Alerta]:
    """Credencial ausente só alarma quando alguma carga AGENDADA depende dela.

    Fonte com credencial declarada e nenhum agendamento ativo — o caso do
    agregador de reserva — não tem "próxima carga" para falhar; alarmar por
    ela ensinaria a ignorar o alarme.
    """
    agendados = {
        ag["dataset_chave"] for ag in repo.listar_agendamentos(sink)
        if ag["ativo"]
    }
    saida: list[Alerta] = []
    for f in repo.listar_fontes(sink):
        if not f.get("ativo") or not f.get("credencial_ref"):
            continue
        if credenciais.presente(f["credencial_ref"]):
            continue
        datasets = [
            d["chave"] for d in repo.listar_datasets(sink)
            if d.get("fonte_chave") == f["chave"] and d["chave"] in agendados
        ]
        if not datasets:
            continue
        saida.append({
            "tipo": "credencial_ausente",
            "severidade": "critico",
            "titulo": f"Credencial de {f['chave']} ausente do ambiente",
            "detalhe": f"A variável referida por '{f['credencial_ref']}' não "
                       f"está definida e há carga agendada dependendo dela "
                       f"({', '.join(datasets)}) — a próxima vai falhar.",
            "acao": {"rotulo": "Ver fontes", "rota": "#/fontes"},
        })
    return saida


def _de_ddl(sink: Sink) -> list[Alerta]:
    saida: list[Alerta] = []
    for c in repo.listar_classes(sink, so_ativas=True):
        atributos = repo.atributos_de(sink, c["id"])
        div = ddl.divergencias(sink, c, atributos)
        if div:
            saida.append({
                "tipo": "ddl_divergente",
                "severidade": "atencao",
                "titulo": f"Tabela de {c['nome']} divergente da configuração",
                "detalhe": "; ".join(div)[:300],
                "acao": {"rotulo": "Aplicar DDL", "rota": f"#/classes?classe={c['chave']}"},
            })
    return saida


def _de_duracao(sink: Sink) -> list[Alerta]:
    saida: list[Alerta] = []
    datasets = sink.consultar(
        "SELECT DISTINCT dataset_chave FROM relatorio_carga"
    )
    for d in datasets:
        chave = d["dataset_chave"]
        series = sink.consultar(
            "SELECT duracao_ms FROM relatorio_carga WHERE dataset_chave = ? "
            "AND duracao_ms IS NOT NULL ORDER BY gerado_em DESC LIMIT 11",
            (chave,),
        )
        if len(series) < MINIMO_AMOSTRAS + 1:
            continue
        ultima = series[0]["duracao_ms"]
        anteriores = [s["duracao_ms"] for s in series[1:]]
        mediana = statistics.median(anteriores)
        if ultima >= PISO_DURACAO_MS and mediana > 0 and ultima > FATOR_DURACAO * mediana:
            saida.append({
                "tipo": "duracao_anomala",
                "severidade": "atencao",
                "titulo": f"Carga de {chave} levou {ultima / 60000:.0f} min "
                          f"({ultima / mediana:.0f}× o normal)",
                "detalhe": f"Mediana das últimas {len(anteriores)} cargas: "
                           f"{mediana / 1000:.0f}s. Vale olhar as fases da "
                           "execução para achar onde o tempo foi.",
                "acao": {"rotulo": "Ver carga e custo", "rota": "#/carga"},
            })
    return saida


def _de_agendamentos(sink: Sink) -> list[Alerta]:
    saida: list[Alerta] = []
    agora = _agora()
    for ag in repo.listar_agendamentos(sink):
        if not ag["ativo"]:
            continue
        ultima = sink.um(
            "SELECT max(terminado_em) AS q FROM log_execucao "
            "WHERE dataset_chave = ? AND status = 'publicado'",
            (ag["dataset_chave"],),
        )
        try:
            vencido, _ = agenda.esta_vencido(
                ag["cron"], (ultima or {}).get("q"), timezone_nome=ag.get("timezone")
            )
            devida = agenda.ocorrencia_devida(ag["cron"], ag.get("timezone"))
        except agenda.ErroCron:
            continue
        if not vencido or devida is None:
            continue
        atraso = agora - devida.astimezone(timezone.utc)
        # Nunca executado não tem "devida" comparável — o alerta certo para
        # isso é o de classe_sem_carga, não este.
        if (ultima or {}).get("q") is None:
            continue
        if atraso > FOLGA_AGENDAMENTO:
            saida.append({
                "tipo": "agendamento_atrasado",
                "severidade": "atencao",
                "titulo": f"Agendamento {ag['chave']} devido há "
                          f"{atraso.total_seconds() / 3600:.0f}h e não rodou",
                "detalhe": "O cron do painel deveria tê-lo disparado. Ou o "
                           "serviço de cron não está acordando, ou a carga "
                           "está falhando antes de registrar execução.",
                "acao": {"rotulo": "Ver execuções", "rota": "#/execucoes"},
            })
    return saida


def ativos(sink: Sink) -> dict[str, Any]:
    """Todos os alertas ativos, com o resumo que a interface pinta.

    ``situacao`` é o semáforo: ``ok`` sem alerta nenhum, ``atencao`` quando
    só há alertas de atenção, ``critico`` quando qualquer um é crítico.
    """
    alertas: list[Alerta] = []
    alertas += _de_credenciais(sink)
    alertas += _de_execucoes(sink)
    alertas += _de_frescor(sink)
    alertas += _de_agendamentos(sink)
    alertas += _de_ddl(sink)
    alertas += _de_duracao(sink)

    ordem = {"critico": 0, "atencao": 1}
    alertas.sort(key=lambda a: ordem[a["severidade"]])
    criticos = sum(1 for a in alertas if a["severidade"] == "critico")
    return {
        "alertas": alertas,
        "resumo": {
            "critico": criticos,
            "atencao": len(alertas) - criticos,
            "situacao": ("critico" if criticos
                         else "atencao" if alertas else "ok"),
        },
    }


def proximas_execucoes(sink: Sink) -> list[dict]:
    """Cada agendamento ativo com o próximo disparo esperado, no fuso dele.

    ``cfg_agendamento`` nunca teve tela: o operador não tinha como saber que
    o COTAHIST dispara às 23:59 sem ler a expressão de cron no banco.
    """
    saida = []
    for ag in repo.listar_agendamentos(sink):
        try:
            tz = agenda.zona(ag.get("timezone"))
            agora_local = _agora().astimezone(tz)
            proxima = agenda.proxima_ocorrencia(ag["cron"], agora_local)
        except agenda.ErroCron:
            proxima = None
        ultima = sink.um(
            "SELECT status, terminado_em FROM log_execucao "
            "WHERE dataset_chave = ? ORDER BY terminado_em DESC, id DESC",
            (ag["dataset_chave"],),
        )
        saida.append({
            "chave": ag["chave"],
            "dataset_chave": ag["dataset_chave"],
            "cron": ag["cron"],
            "timezone": ag.get("timezone"),
            "ativo": bool(ag["ativo"]),
            "proxima": proxima.isoformat() if proxima else None,
            "ultima_situacao": (ultima or {}).get("status"),
            "ultima_em": ((ultima or {}).get("terminado_em") or None),
        })
    saida.sort(key=lambda x: (not x["ativo"], x["proxima"] or "9999"))
    return saida
