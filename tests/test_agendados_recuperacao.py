"""`agendados` não pode perder pregão, nem duplicar execução, nem deixar
execução morta para sempre.

Incidente de produção (mydata-cron, 2026-09-15..28): o COTAHIST publicou os
pregões 09-14, 16, 18, 21, 22 e 24 e nunca carregou 09-15, 17, 23 e 25. Causa:
a decisão de rodar comparava o horário do último `publicado` com a ocorrência
devida do cron, e a publicação levava 16–44 h — mais que o ciclo de 24 h. O
`terminado_em` de uma janela velha passava da ocorrência do dia seguinte, o
agendamento respondia «já rodou» e a janela do dia seguinte não era nunca mais
revisitada, porque cada disparo pedia uma janela só.

Aqui `ingestao.executar` é substituído por um falso que só grava a linha em
`log_execucao`: o que se testa é a decisão do agendador, não a carga.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app import agenda, cli, repositorio as repo
from app.motor import ingestao

COTAHIST = "b3_cotahist_diario"


def acordar(mes: int, dia: int, hora: int = 6, minuto: int = 4) -> datetime:
    """O serviço do Railway acorda por volta das 06:04 UTC."""
    return datetime(2026, mes, dia, hora, minuto, tzinfo=timezone.utc)


def inserir(sink, dataset, janela, status, iniciado, terminado=None, erro=None):
    exec_id = sink.proximo_id("log_execucao")
    sink.executar(
        "INSERT INTO log_execucao (id, dataset_chave, janela, status, "
        "trigger_tipo, iniciado_em, terminado_em, erro) VALUES (?,?,?,?,?,?,?,?)",
        (exec_id, dataset, janela, status, "cron", iniciado, terminado, erro),
    )
    return exec_id


class Falso:
    """Substitui `ingestao.executar`: registra a chamada e grava a execução."""

    def __init__(self, sink, monkeypatch, *, relogio, lag=timedelta(hours=1),
                 falha_em=(), ocupada_em=()):
        self.sink, self.relogio, self.lag = sink, relogio, lag
        self.falha_em, self.ocupada_em = set(falha_em), set(ocupada_em)
        self.chamadas: list[tuple[str, str]] = []
        monkeypatch.setattr(ingestao, "executar", self)

    def __call__(self, sink, dataset, janela, *, trigger="manual", baixar=None,
                 **_):
        self.chamadas.append((dataset, janela))
        if janela in self.ocupada_em:
            return ingestao.Resultado(0, dataset, janela, "ja_em_execucao")
        agora = self.relogio()
        if janela in self.falha_em:
            inserir(sink, dataset, janela, "falha", agora, agora, "404")
            raise RuntimeError(f"404 em {janela}")
        eid = inserir(sink, dataset, janela, "publicado", agora, agora + self.lag)
        return ingestao.Resultado(eid, dataset, janela, "publicado",
                                  linhas_silver=1)

    def janelas(self, dataset="b3_cotahist"):
        return [j for d, j in self.chamadas if d == dataset]


def rodar(sink, agora, **kw):
    return cli.rodar_agendados(
        sink, chave=COTAHIST, agora=agora, baixar=lambda *a, **k: b"", **kw
    )


def publicadas(sink, dataset="b3_cotahist"):
    return sorted(repo.janelas_publicadas(sink, dataset))


# --------------------------------------------------------------------------
# A causa
# --------------------------------------------------------------------------
def test_publicacao_de_22h_nao_faz_pular_pregao_nenhum(sink_cvm, monkeypatch):
    """Reproduz o padrão alternado do log de produção: cada janela leva 22 h
    para publicar. Antes da correção, 09-14, 16, 18, 22 e 24 eram puladas."""
    relogio = {"t": acordar(9, 14)}
    Falso(sink_cvm, monkeypatch, relogio=lambda: relogio["t"],
          lag=timedelta(hours=22))
    inserir(sink_cvm, "b3_cotahist", "2026-09-10", "publicado",
            acordar(9, 11), acordar(9, 11))

    for dia in range(14, 29):
        relogio["t"] = acordar(9, dia)
        rodar(sink_cvm, relogio["t"])

    esperado = [
        "2026-09-10", "2026-09-11", "2026-09-14", "2026-09-15", "2026-09-16",
        "2026-09-17", "2026-09-18", "2026-09-21", "2026-09-22", "2026-09-23",
        "2026-09-24", "2026-09-25",
    ]
    assert publicadas(sink_cvm) == esperado
    # E cada pregão foi carregado uma vez só.
    execucoes = sink_cvm.consultar(
        "SELECT janela, count(*) AS n FROM log_execucao "
        "WHERE dataset_chave = 'b3_cotahist' GROUP BY janela"
    )
    assert {e["janela"]: e["n"] for e in execucoes} == {j: 1 for j in esperado}


# --------------------------------------------------------------------------
# Recuperação de janelas
# --------------------------------------------------------------------------
def test_recupera_lacunas_em_ordem_crescente(sink_cvm, monkeypatch):
    falso = Falso(sink_cvm, monkeypatch, relogio=lambda: acordar(9, 16))
    inserir(sink_cvm, "b3_cotahist", "2026-09-08", "publicado",
            acordar(9, 9), acordar(9, 9))

    saida, falhas = rodar(sink_cvm, acordar(9, 16))

    # 09-09, 10, 11, 14 e 15 — o fim de semana 12/13 não é ocorrência do cron.
    assert falso.janelas() == [
        "2026-09-09", "2026-09-10", "2026-09-11", "2026-09-14", "2026-09-15",
    ]
    assert falhas == 0
    assert [s["status"] for s in saida] == ["publicado"] * 5


def test_teto_por_disparo_e_o_resto_fica_para_o_proximo(sink_cvm, monkeypatch):
    falso = Falso(sink_cvm, monkeypatch, relogio=lambda: acordar(9, 16))
    inserir(sink_cvm, "b3_cotahist", "2026-09-08", "publicado",
            acordar(9, 9), acordar(9, 9))

    saida, _ = rodar(sink_cvm, acordar(9, 16), teto_janelas=2)

    assert falso.janelas() == ["2026-09-09", "2026-09-10"]
    adiado = [s for s in saida if s["status"] == "adiado"]
    assert adiado and adiado[0]["janelas"] == [
        "2026-09-11", "2026-09-14", "2026-09-15",
    ]

    # O disparo seguinte continua de onde parou, sem repetir.
    falso.chamadas.clear()
    rodar(sink_cvm, acordar(9, 17), teto_janelas=2)
    assert falso.janelas() == ["2026-09-11", "2026-09-14"]


def test_feriado_na_cabeca_da_fila_nao_trava_o_teto(sink_cvm, monkeypatch):
    """Produção, 2026-10: o 12/10 (feriado, 404) ficava na cabeça da fila e,
    com teto 1, era a única janela tentada em todo disparo — 13/10 em diante
    nunca rodava e o cron saía com 1 todos os dias."""
    falso = Falso(sink_cvm, monkeypatch, relogio=lambda: acordar(9, 16),
                  falha_em={"2026-09-09"})
    inserir(sink_cvm, "b3_cotahist", "2026-09-08", "publicado",
            acordar(9, 9), acordar(9, 9))

    saida, falhas = rodar(sink_cvm, acordar(9, 16), teto_janelas=1)

    assert falso.janelas() == ["2026-09-09", "2026-09-10"]
    assert falhas == 1
    adiado = [s for s in saida if s["status"] == "adiado"]
    assert adiado[0]["janelas"] == ["2026-09-11", "2026-09-14", "2026-09-15"]

    # A marca d'água andou: o feriado saiu da fila e o disparo seguinte segue.
    falso.chamadas.clear()
    saida, falhas = rodar(sink_cvm, acordar(9, 17), teto_janelas=1)
    assert falso.janelas() == ["2026-09-11"]
    assert falhas == 0


@pytest.fixture(autouse=True)
def _teto_cinco_nos_cenarios(monkeypatch):
    """Os cenários de recuperação foram escritos com teto 5; o padrão de
    produção é 1 (ver `test_teto_padrao_e_um`, que remove a variável)."""
    monkeypatch.setenv("PORTAL_MAX_JANELAS_POR_DISPARO", "5")


def test_teto_padrao_e_um(sink_cvm, monkeypatch):
    falso = Falso(sink_cvm, monkeypatch, relogio=lambda: acordar(9, 30))
    inserir(sink_cvm, "b3_cotahist", "2026-09-01", "publicado",
            acordar(9, 2), acordar(9, 2))
    monkeypatch.delenv("PORTAL_MAX_JANELAS_POR_DISPARO", raising=False)

    rodar(sink_cvm, acordar(9, 30))

    assert len(falso.janelas()) == 1, "padrão 1 enquanto o calcular leva horas por janela"


def test_nao_recarrega_janela_ja_publicada(sink_cvm, monkeypatch):
    falso = Falso(sink_cvm, monkeypatch, relogio=lambda: acordar(9, 18))
    for j in ("2026-09-14", "2026-09-16"):
        inserir(sink_cvm, "b3_cotahist", j, "publicado", acordar(9, 17),
                acordar(9, 17))

    rodar(sink_cvm, acordar(9, 18))   # devida: 09-17

    # 09-15 está abaixo do maior publicado (09-16): fica para `ingerir` manual,
    # de propósito (ver o comentário em `agenda.janelas_pendentes`).
    assert falso.janelas() == ["2026-09-17"]


def test_fim_de_semana_nunca_e_tentado(sink_cvm, monkeypatch):
    falso = Falso(sink_cvm, monkeypatch, relogio=lambda: acordar(9, 14))
    inserir(sink_cvm, "b3_cotahist", "2026-09-10", "publicado",
            acordar(9, 11), acordar(9, 11))

    # Segunda 09-14 06:04: a ocorrência devida é sexta 09-11.
    rodar(sink_cvm, acordar(9, 14))
    assert falso.janelas() == ["2026-09-11"]

    # Sábado 09-12 e domingo 09-13 não têm o que rodar depois disso.
    falso.chamadas.clear()
    saida, _ = rodar(sink_cvm, acordar(9, 14, 12, 0))
    assert falso.chamadas == [] and saida[0]["status"] == "nao_vencido"


def test_nunca_publicado_roda_so_a_janela_corrente(sink_cvm, monkeypatch):
    """Sem marca d'água não há lacuna a medir — backfill de anos por engano é
    pior que nenhum."""
    falso = Falso(sink_cvm, monkeypatch, relogio=lambda: acordar(9, 16))
    rodar(sink_cvm, acordar(9, 16))
    assert falso.janelas() == ["2026-09-15"]


def test_falha_numa_janela_nao_trava_as_seguintes(sink_cvm, monkeypatch):
    """Feriado é 404 e vira `falha` visível. Se ele parasse a fila, um feriado
    na cabeça dela travaria o dataset para sempre."""
    falso = Falso(sink_cvm, monkeypatch, relogio=lambda: acordar(9, 16),
                  falha_em=["2026-09-10"])
    inserir(sink_cvm, "b3_cotahist", "2026-09-08", "publicado",
            acordar(9, 9), acordar(9, 9))

    saida, falhas = rodar(sink_cvm, acordar(9, 16))

    assert falso.janelas() == [
        "2026-09-09", "2026-09-10", "2026-09-11", "2026-09-14", "2026-09-15",
    ]
    assert falhas == 1
    assert [s["status"] for s in saida] == [
        "publicado", "falha", "publicado", "publicado", "publicado",
    ]
    # Passada a marca d'água, o feriado deixa de ser tentado.
    falso.chamadas.clear()
    rodar(sink_cvm, acordar(9, 17))
    assert falso.janelas() == ["2026-09-16"]


def test_janela_ja_em_execucao_e_pulada_e_nao_e_falha(sink_cvm, monkeypatch):
    """E para a fila: publicar 09-11 com 09-10 nas mãos de outro processo
    deixaria 09-10 abaixo da marca d'água, perdida se o outro falhar."""
    falso = Falso(sink_cvm, monkeypatch, relogio=lambda: acordar(9, 14),
                  ocupada_em=["2026-09-10"])
    inserir(sink_cvm, "b3_cotahist", "2026-09-09", "publicado",
            acordar(9, 10), acordar(9, 10))

    saida, falhas = rodar(sink_cvm, acordar(9, 14))

    assert falhas == 0
    assert falso.janelas() == ["2026-09-10"]
    assert saida[-1]["status"] == "pulado"
    assert "ja_em_execucao" in saida[-1]["motivo"]


def test_dataset_com_execucao_nao_terminal_recente_nao_e_disparado(
    sink_cvm, monkeypatch
):
    falso = Falso(sink_cvm, monkeypatch, relogio=lambda: acordar(9, 16))
    inserir(sink_cvm, "b3_cotahist", "2026-09-08", "publicado",
            acordar(9, 9), acordar(9, 9))
    for estado in ("recomputando", "carregando", "baixando", "pendente"):
        inserir(sink_cvm, "b3_cotahist", "2026-09-09", estado,
                acordar(9, 15), None)
        saida, falhas = rodar(sink_cvm, acordar(9, 16))
        assert falso.chamadas == [], estado
        assert falhas == 0
        assert saida[-1]["status"] == "pulado"
        assert "ja_em_execucao" in saida[-1]["motivo"]
        sink_cvm.executar("DELETE FROM log_execucao WHERE status = ?", (estado,))


def test_reaper_roda_antes_e_libera_o_dataset(sink_cvm, monkeypatch):
    """Execução morta há mais de 72 h vira `falha` e deixa de bloquear."""
    falso = Falso(sink_cvm, monkeypatch, relogio=lambda: acordar(9, 16))
    inserir(sink_cvm, "b3_cotahist", "2026-09-08", "publicado",
            acordar(9, 9), acordar(9, 9))
    morta = inserir(sink_cvm, "b3_cotahist", "2026-09-09", "recomputando",
                    acordar(9, 10), None)   # 6 dias antes

    saida, _ = rodar(sink_cvm, acordar(9, 16))

    linha = sink_cvm.um("SELECT status, erro, terminado_em FROM log_execucao "
                        "WHERE id = ?", (morta,))
    assert linha["status"] == "falha"
    assert linha["erro"] == "abandonada (reaper)"
    assert linha["terminado_em"] is not None
    assert falso.janelas()  # e o dataset voltou a rodar
    assert any(s.get("status") == "reaper" and s["abandonadas"] == 1
               for s in saida)


# --------------------------------------------------------------------------
# O que NÃO é janela diária de pregão
# --------------------------------------------------------------------------
def test_so_recupera_dataset_cuja_janela_muda_o_endereco(sink_cvm):
    """A discriminação vem da configuração, não do nome: recuperar é possível
    quando pedir outro dia devolve outro arquivo."""
    assert ingestao.janela_recuperavel(sink_cvm, "b3_cotahist") is True
    # Fotografia: a janela vira `date=` mas reingerir dia velho não retrocede.
    assert ingestao.janela_recuperavel(sink_cvm, "b3_instrumentos") is False
    # API por companhia: a URL nem contém a janela.
    assert ingestao.janela_recuperavel(sink_cvm, "b3_proventos_dinheiro") is False
    assert ingestao.janela_recuperavel(sink_cvm, "cvm_dfp") is False


def test_fotografia_diaria_mantem_o_caminho_antigo(sink_cvm, monkeypatch):
    falso = Falso(sink_cvm, monkeypatch, relogio=lambda: acordar(9, 16))
    inserir(sink_cvm, "b3_instrumentos", "2026-09-01", "publicado",
            acordar(9, 2), acordar(9, 2))

    saida, _ = cli.rodar_agendados(
        sink_cvm, chave="b3_instrumentos_diario", agora=acordar(9, 16),
        baixar=lambda *a, **k: b"",
    )

    # Uma janela só — a devida —, sem backfill dos dias no meio.
    assert falso.janelas("b3_instrumentos") == ["2026-09-15"]
    assert saida[0]["status"] == "publicado"


def test_agendamento_anual_segue_o_criterio_por_horario(sink_cvm, monkeypatch):
    falso = Falso(sink_cvm, monkeypatch, relogio=lambda: acordar(9, 16))
    inserir(sink_cvm, "cvm_dfp", "2026", "publicado", acordar(4, 1, 10, 0),
            acordar(4, 1, 12, 0))

    saida, _ = cli.rodar_agendados(
        sink_cvm, chave="cvm_dfp_anual", agora=acordar(9, 16),
        baixar=lambda *a, **k: b"",
    )

    assert falso.chamadas == [] and saida[0]["status"] == "nao_vencido"


# --------------------------------------------------------------------------
# agenda.janelas_pendentes, sem banco
# --------------------------------------------------------------------------
def _janela_de(padrao="hoje", tz="America/Sao_Paulo"):
    return lambda ocorrencia: cli.janela_corrente(padrao, tz, ocorrencia)


def test_janelas_pendentes_pura():
    pend = agenda.janelas_pendentes(
        "59 23 * * 1-5", "America/Sao_Paulo", ["2026-09-09"],
        acordar(9, 16), _janela_de(),
    )
    assert pend == ["2026-09-10", "2026-09-11", "2026-09-14", "2026-09-15"]


def test_janelas_pendentes_ignora_janela_que_nao_e_data_e_a_futura():
    pend = agenda.janelas_pendentes(
        "59 23 * * 1-5", "America/Sao_Paulo",
        ["2026", "lixo", "2026-09-14", "2027-01-01"],
        acordar(9, 16), _janela_de(),
    )
    # 2027-01-01 está no futuro da devida: não vira marca d'água, senão
    # esconderia tudo até lá.
    assert pend == ["2026-09-15"]


def test_janelas_pendentes_dia_anterior():
    pend = agenda.janelas_pendentes(
        "0 6 * * *", "UTC", ["2026-09-12"], acordar(9, 15, 7, 0),
        _janela_de("dia_anterior", "UTC"),
    )
    assert pend == ["2026-09-13", "2026-09-14"]


# --------------------------------------------------------------------------
# Reaper (repositório)
# --------------------------------------------------------------------------
def test_reaper_so_toca_o_que_e_nao_terminal_e_velho(sink):
    agora = acordar(9, 28)
    velha = inserir(sink, "d", "j1", "recomputando", agora - timedelta(hours=73))
    limite = inserir(sink, "d", "j2", "carregando", agora - timedelta(hours=71))
    nova = inserir(sink, "d", "j3", "baixando", agora - timedelta(hours=1))
    publicado = inserir(sink, "d", "j4", "publicado", agora - timedelta(hours=200),
                        agora - timedelta(hours=190))
    bloqueada = inserir(sink, "d", "j5", "bloqueada", agora - timedelta(hours=200),
                        agora - timedelta(hours=190))
    # `apenas_bronze` termina em `capturado` COM terminado_em: não é abandono.
    bronze = inserir(sink, "d", "j6", "capturado", agora - timedelta(hours=200),
                     agora - timedelta(hours=190))

    ids = repo.abandonar_execucoes(sink, 72, agora)

    assert ids == [velha]
    status = {r["id"]: r["status"] for r in sink.consultar(
        "SELECT id, status FROM log_execucao")}
    assert status == {velha: "falha", limite: "carregando", nova: "baixando",
                      publicado: "publicado", bloqueada: "bloqueada",
                      bronze: "capturado"}


def test_reaper_e_idempotente(sink):
    agora = acordar(9, 28)
    inserir(sink, "d", "j1", "validando", agora - timedelta(hours=100))
    assert len(repo.abandonar_execucoes(sink, 72, agora)) == 1
    assert repo.abandonar_execucoes(sink, 72, agora) == []
    linha = sink.um("SELECT status, erro FROM log_execucao")
    assert (linha["status"], linha["erro"]) == ("falha", "abandonada (reaper)")


def test_execucao_em_andamento_respeita_o_limite(sink):
    agora = acordar(9, 28)
    inserir(sink, "d", "j1", "recomputando", agora - timedelta(hours=80))
    assert repo.execucao_em_andamento(sink, "d", 72, agora) is None
    inserir(sink, "d", "j2", "recomputando", agora - timedelta(hours=30))
    achada = repo.execucao_em_andamento(sink, "d", 72, agora)
    assert achada["janela"] == "j2"
    assert repo.execucao_em_andamento(sink, "outro", 72, agora) is None


# --------------------------------------------------------------------------
# Configuração por variável de ambiente
# --------------------------------------------------------------------------
@pytest.mark.parametrize("bruto,esperado", [
    (None, 72.0), ("", 72.0), ("48", 48.0), ("0", 72.0), ("-3", 72.0),
    ("abc", 72.0), ("nan", 72.0), ("inf", 72.0), ("0.5", 0.5),
])
def test_horas_de_abandono_invalida_volta_ao_padrao(bruto, esperado):
    """Zero horas mataria toda execução em curso: valor ruim não pode passar."""
    assert cli._positivo(bruto, 72.0, "PORTAL_EXECUCAO_ABANDONADA_HORAS") == esperado


def test_teto_de_janelas_lido_do_ambiente(sink_cvm, monkeypatch):
    falso = Falso(sink_cvm, monkeypatch, relogio=lambda: acordar(9, 16))
    inserir(sink_cvm, "b3_cotahist", "2026-09-08", "publicado",
            acordar(9, 9), acordar(9, 9))
    monkeypatch.setenv("PORTAL_MAX_JANELAS_POR_DISPARO", "1")

    rodar(sink_cvm, acordar(9, 16))

    assert falso.janelas() == ["2026-09-09"]


# --------------------------------------------------------------------------
# Ponta a ponta com o `executar` de verdade
# --------------------------------------------------------------------------
def test_rodada_completa_com_o_motor_real(sink_cvm):
    from tests.test_cotahist import ARQUIVO

    agora = acordar(8, 4)   # devida: segunda 08-03, 23:59 em São Paulo
    saida, falhas = cli.rodar_agendados(
        sink_cvm, chave=COTAHIST, agora=agora,
        baixar=lambda url, cabecalhos=None: ARQUIVO,
    )
    assert falhas == 0
    assert [(s["janela"], s["status"]) for s in saida] == [
        ("2026-08-03", "publicado")]
    # E a rodada seguinte, sem dia novo, não tem o que fazer.
    saida, _ = cli.rodar_agendados(
        sink_cvm, chave=COTAHIST, agora=agora,
        baixar=lambda url, cabecalhos=None: ARQUIVO,
    )
    assert saida[0]["status"] == "nao_vencido"


@pytest.mark.parametrize("bruto", ["0.5", "2.7", "0.99"])
def test_teto_fracionario_nunca_vira_zero(sink_cvm, monkeypatch, bruto):
    """`int(0.5)` é 0: o cron passaria a não carregar nada, sem falha e com
    exit 0. O teto tem piso de uma janela."""
    falso = Falso(sink_cvm, monkeypatch, relogio=lambda: acordar(9, 16))
    inserir(sink_cvm, "b3_cotahist", "2026-09-08", "publicado",
            acordar(9, 9), acordar(9, 9))
    monkeypatch.setenv("PORTAL_MAX_JANELAS_POR_DISPARO", bruto)

    rodar(sink_cvm, acordar(9, 16))

    assert len(falso.janelas()) == max(1, int(float(bruto)))


# --------------------------------------------------------------------------
# Dialeto Postgres: o SQL novo sobrevive à tradução `?` -> `%s`
# --------------------------------------------------------------------------
def test_sql_novo_traduz_para_psycopg_sem_sobrar_interrogacao():
    from app.sinks import qmark_para_pyformat

    trava = qmark_para_pyformat("SELECT pg_try_advisory_lock(CAST(? AS bigint)) AS ok")
    assert trava == "SELECT pg_try_advisory_lock(CAST(%s AS bigint)) AS ok"
    reaper = qmark_para_pyformat(
        f"UPDATE log_execucao SET status = 'falha', erro = ?, terminado_em = ? "
        f"WHERE id = ? AND {repo._NAO_TERMINAL}"
    )
    assert "?" not in reaper and reaper.count("%s") == 3
    assert "%" not in reaper.replace("%s", "")
