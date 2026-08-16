"""O que cada carga pesa, e o que isso custa por mês.

A tabela de risco da arquitetura já previa «bronze cresce além do plano», e
nada media crescimento: dava para saber que uma carga rodou, não o que ela
acrescentou. O relatório fecha isso — físico medido, financeiro derivado, e a
separação entre os dois dita explicitamente na resposta.

Bytes de disco só o Postgres responde de forma útil; o DuckDB destes testes
roda em memória e devolveria zero, que é pior que nulo porque parece medida.
Por isso o que se afirma aqui é o comportamento na ausência da medida — e a
aritmética do custo, que é dialeto-independente.
"""
from __future__ import annotations

import pytest

from app import seed_fontes
from app.motor import custo, ingestao
from tests.test_cotahist import ARQUIVO


@pytest.fixture()
def carregado(sink):
    seed_fontes.aplicar(sink)
    ingestao.executar(
        sink, "b3_cotahist", "2026-07-31",
        baixar=lambda url, cabecalhos=None: ARQUIVO,
    )
    return sink


def relatorio(sink):
    return sink.um("SELECT * FROM relatorio_carga ORDER BY id DESC LIMIT 1")


# --------------------------------------------------------------------------
# O que é medido
# --------------------------------------------------------------------------
def test_toda_carga_gera_uma_linha_de_relatorio(carregado):
    r = relatorio(carregado)
    assert r["dataset_chave"] == "b3_cotahist"
    assert r["janela"] == "2026-07-31"
    assert r["status"] == "publicado"
    assert r["classe_chave"] == "negociacao_b3"


def test_o_fisico_vem_da_medida_e_nao_da_contagem_do_motor(carregado):
    """`linhas_classe` é contado na tabela, não herdado do resultado: é a
    diferença entre o que a carga disse que fez e o que ficou no banco."""
    r = relatorio(carregado)
    assert r["linhas_carregadas"] == 4
    assert r["linhas_classe"] == 4
    assert r["bytes_capturados"] > 0
    assert r["bytes_bronze"] >= r["bytes_capturados"]
    assert r["duracao_ms"] is not None and r["duracao_ms"] >= 0


def test_bytes_de_disco_ficam_nulos_onde_nao_ha_como_medir(carregado):
    """Zero pareceria medida. Nulo diz «não sei», que é o fato."""
    r = relatorio(carregado)
    if carregado.dialeto == "postgres":
        assert r["bytes_banco"] > 0 and r["bytes_classe"] > 0
    else:
        assert r["bytes_banco"] is None and r["bytes_classe"] is None
        assert r["custo_mes_usd"] is None


def test_carga_bloqueada_tambem_e_relatada(sink):
    """O bronze foi capturado e continua ocupando disco mesmo com o gate
    reprovando. Relatar só o sucesso esconderia o custo que não virou dado."""
    from app import repositorio as repo

    seed_fontes.aplicar(sink)
    ds = repo.dataset_vigente(sink, "b3_cotahist")
    sink.executar(
        """INSERT INTO cfg_regra_qualidade
           (id, dataset_id, nome, expressao_sql, severidade, tolerancia,
            descricao, ativo)
           VALUES (?,?,?,?,'bloqueia',0,'reprova tudo',TRUE)""",
        (sink.proximo_id("cfg_regra_qualidade"), ds["id"], "reprova_tudo",
         "SELECT 1 FROM fato_negociacao"),
    )
    res = ingestao.executar(
        sink, "b3_cotahist", "2026-07-31",
        baixar=lambda url, cabecalhos=None: ARQUIVO,
    )
    assert res.status == "bloqueada"
    r = relatorio(sink)
    assert r["status"] == "bloqueada"
    assert r["bytes_capturados"] > 0, "o disco foi ocupado mesmo sem publicar"


# --------------------------------------------------------------------------
# O que é derivado
# --------------------------------------------------------------------------
def test_tarifa_vigente_e_a_da_data_nao_a_de_hoje(carregado):
    """Recomputar um relatório antigo com o preço de hoje reescreveria a
    história: o custo daquele mês foi o que foi."""
    carregado.executar(
        "INSERT INTO cfg_tarifa (id, recurso, unidade, preco_usd, vigente_desde) "
        "VALUES (?, 'armazenamento', 'GB-mês', 0.99, '2027-01-01')",
        (carregado.proximo_id("cfg_tarifa"),),
    )
    assert float(custo.tarifa_vigente(
        carregado, "armazenamento", "2026-09-01")["preco_usd"]) == 0.15
    assert float(custo.tarifa_vigente(
        carregado, "armazenamento", "2027-06-01")["preco_usd"]) == 0.99


def test_custo_em_real_usa_o_cambio_da_propria_base(carregado):
    """O hub já ingere USD/BRL do BCB. Usar uma constante seria o relatório
    ter fonte de número que o próprio sistema não guarda."""
    carregado.executar(
        "INSERT INTO fato_indicador (captura_id, fonte_arquivo, origem_dataset,"
        " indicador, dt_referencia, valor, unidade) VALUES (0,'manual',"
        "'bcb_cambio_usd', 'cambio_usd_brl', '2026-07-30', 5.40, 'BRL/USD')"
    )
    assert custo.cambio_do_dia(carregado, "2026-08-01") == pytest.approx(5.40)


def test_sem_cambio_carregado_o_custo_em_real_fica_nulo(carregado):
    """Nulo, não zero: R$ 0,00 pareceria de graça."""
    assert custo.cambio_do_dia(carregado, "2026-08-01") is None
    assert relatorio(carregado)["custo_mes_brl"] is None


@pytest.mark.parametrize("dias,delta_gb,esperado", [
    (1.0, 2.0, 2.0),
    (2.0, 1.0, 0.5),
    (7.0, 7.0, 1.0),
])
def test_crescimento_por_dia(dias, delta_gb, esperado):
    from datetime import datetime, timedelta, timezone

    agora = datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc)
    antes = agora - timedelta(days=dias)
    base = 10 * custo.BYTES_POR_GB
    anterior = {"bytes_banco": base, "gerado_em": antes}
    agora_bytes = base + int(delta_gb * custo.BYTES_POR_GB)
    assert custo._crescimento_por_dia(
        anterior, agora_bytes, agora) == pytest.approx(esperado, rel=1e-6)


def test_duas_cargas_no_mesmo_instante_nao_viram_crescimento_infinito():
    """Divisão por intervalo quase nulo daria projeção absurda — e uma
    recarga logo depois da outra é rotina, não exceção."""
    from datetime import datetime, timezone

    agora = datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc)
    anterior = {"bytes_banco": 1000, "gerado_em": agora}
    assert custo._crescimento_por_dia(anterior, 2000, agora) is None


# --------------------------------------------------------------------------
# A linha do log
# --------------------------------------------------------------------------
def test_resumo_cabe_numa_linha_e_diz_o_essencial(carregado):
    """Relatório que ocupa vinte linhas some no meio da saída da carga — que
    é justamente quando ele importa."""
    linha = custo.resumo(dict(relatorio(carregado)))
    assert "\n" not in linha
    assert "carga b3_cotahist/2026-07-31" in linha
    assert "status=publicado" in linha
    assert "linhas=4" in linha


def test_resumo_nao_inventa_numero_que_nao_tem():
    """Sem medida de disco, o resumo omite o custo em vez de imprimir zero."""
    linha = custo.resumo({
        "dataset_chave": "x", "janela": "2026", "status": "publicado",
        "linhas_carregadas": 1, "delta_linhas": 1, "bytes_capturados": 10,
        "bytes_banco": None, "delta_bytes_banco": None, "custo_mes_usd": None,
        "custo_mes_brl": None, "projecao_12m_usd": None, "projecao_12m_gb": None,
    })
    assert "custo" not in linha and "projeção" not in linha
    assert "banco=?" in linha


# --------------------------------------------------------------------------
# A garantia que importa
# --------------------------------------------------------------------------
def test_relatorio_quebrado_nao_derruba_a_carga(sink, monkeypatch):
    """Medir não pode custar o dado. Se a medição falha, a carga publica
    mesmo assim e o problema vira aviso no log."""
    seed_fontes.aplicar(sink)

    def explode(*a, **kw):
        raise RuntimeError("catálogo do banco indisponível")

    monkeypatch.setattr(custo, "gerar", explode)
    res = ingestao.executar(
        sink, "b3_cotahist", "2026-07-31",
        baixar=lambda url, cabecalhos=None: ARQUIVO,
    )
    assert res.status == "publicado"
    assert sink.um("SELECT count(*) AS n FROM relatorio_carga")["n"] == 0


# --------------------------------------------------------------------------
# Pela API
# --------------------------------------------------------------------------
def test_endpoint_separa_o_medido_do_derivado(cliente):
    """O consumidor precisa saber qual número é medida e qual é conta —
    apresentar os dois como iguais é o que transforma estimativa em fato."""
    r = cliente.get("/v1/meta/carga")
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["medicao"]["fisico"].startswith("medido")
    assert corpo["medicao"]["financeiro"].startswith("derivado")
    assert "CPU e memória" in corpo["medicao"]["nao_coberto"]
    assert corpo["tarifa"]["recurso"] == "armazenamento"


def test_endpoint_lista_as_cargas_mais_recentes_primeiro(cliente):
    dados = cliente.get("/v1/meta/carga").json()["dados"]
    assert dados, "a fixture carrega DFP e cadastro"
    assert [d["dataset_chave"] for d in dados[:2]] == ["cvm_cadastro", "cvm_dfp"]


def test_endpoint_filtra_por_dataset(cliente):
    dados = cliente.get("/v1/meta/carga?dataset=cvm_dfp").json()["dados"]
    assert {d["dataset_chave"] for d in dados} == {"cvm_dfp"}


@pytest.mark.parametrize("horas", [0.0, 1.0, 6.0, 19.0])
def test_intervalo_curto_nao_vira_taxa_diaria(horas):
    """O defeito que a primeira medição em produção mostrou.

    Duas cargas separadas por uma hora, com 24,5 MB de diferença, projetaram
    205 GB em doze meses — vinte e quatro vezes o crescimento real, porque a
    conta extrapolava relógio e não pregão. Abaixo da idade mínima a resposta
    é nula: projeção inventada é pior que projeção ausente, porque ela decide.
    """
    from datetime import datetime, timedelta, timezone

    agora = datetime(2026, 8, 5, 2, 39, tzinfo=timezone.utc)
    anterior = {
        "bytes_banco": 1_505_367_743,
        "gerado_em": agora - timedelta(hours=horas),
    }
    assert custo._crescimento_por_dia(
        anterior, 1_529_874_000, agora) is None


def test_delta_e_taxa_usam_baselines_diferentes(carregado):
    """São duas perguntas: quanto esta carga somou, e quanto isto cresce por
    dia. A primeira é contra o relatório anterior, qualquer que seja o
    intervalo; a segunda precisa de régua com idade.

    As linhas são sintéticas porque o DuckDB não mede disco — e é o valor de
    `bytes_banco` que separa uma baseline da outra.
    """
    from datetime import datetime, timedelta, timezone

    agora = datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc)
    for idade_horas, bytes_banco in ((72, 1_000_000_000), (1, 1_100_000_000)):
        carregado.executar(
            "INSERT INTO relatorio_carga (id, execucao_id, dataset_chave, "
            "janela, status, gerado_em, bytes_banco) VALUES (?,1,'sintetico',"
            "'2026','publicado',?,?)",
            (carregado.proximo_id("relatorio_carga"),
             agora - timedelta(hours=idade_horas), bytes_banco),
        )

    # O último é o de uma hora atrás; a régua pula para o de três dias.
    assert custo._ultimo(carregado, "sintetico")["bytes_banco"] == 1_100_000_000
    assert custo._regua(
        carregado, "sintetico", agora)["bytes_banco"] == 1_000_000_000
