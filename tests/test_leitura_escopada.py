"""Campo de janela: a leitura escopada tem de dar o mesmo que a integral.

A carga diária do COTAHIST é um pregão novo no fim da série. `log_retorno`,
`hv21` e `hv63` não retroagem, então só as linhas da carga são escritas — mas,
até esta correção, a subconsulta da função de janela relia `fato_negociacao`
inteira a cada campo, e isso cresce ~20 mil linhas por pregão
(docs/diagnostico-retencao-e-carga.md, plano de ação, item 1).

O escopo lê só as partições (tickers) da carga e só o histórico que a maior
janela do campo alcança, derivado da configuração. Estes testes provam que o
resultado é o mesmo do caminho integral, linha a linha, e que o recorte de
fato lê menos.
"""
from __future__ import annotations

import math
import random
from datetime import date, datetime, timedelta, timezone

import pytest

from app import repositorio as repo
from app import seed_fontes
from app.motor import calculados as calc

CAMPOS = ("log_retorno", "hv21", "hv63")
SENTINELA = -999.0
CAPTURA_DELTA = 9999

LIQUIDOS = [f"LIQ{i}" for i in range(1, 6)]


def _pregoes(n: int, inicio: date = date(2026, 1, 5)) -> list[str]:
    dias, d = [], inicio
    while len(dias) < n:
        if d.weekday() < 5:
            dias.append(d.isoformat())
        d += timedelta(days=1)
    return dias


def _linha(dt, codneg, preco, captura, prazo_termo=None, tp_mercado="010"):
    return [captura, "sintetico.txt", datetime(2026, 1, 1, tzinfo=timezone.utc),
            "b3_cotahist", dt, codneg, tp_mercado, "02", prazo_termo, preco]


INSERIR = (
    "INSERT INTO fato_negociacao (captura_id, fonte_arquivo, carregado_em, "
    "origem_dataset, dt_pregao, codneg, tp_mercado, cod_bdi, prazo_termo, "
    "preco_fechamento) VALUES (?,?,?,?,?,?,?,?,?,?)"
)


def _historico(n_pregoes: int, semente: int = 7) -> tuple[list[list], list[str]]:
    """Histórico multi-ticker com os casos que quebram um recorte ingênuo.

    - LIQ1..LIQ5: negociam todo pregão; LIQ4 e LIQ5 às vezes com fechamento
      zero (o `ln` sai nulo e a contagem da janela muda).
    - ILIQ1: negocia a cada 17 pregões — tem histórico, mas poucas linhas
      dentro de «N pregões atrás»; o corte por data sozinho truncaria a
      janela dele.
    - ILIQ2: negociou só no começo; o anterior dele está longe no tempo.
    - CURTO: estreou há 8 pregões — janela maior que o histórico.
    - TERM1: termo, com `prazo_termo` preenchido (chave natural com coluna
      que costuma ser nula).
    - FORA: negociou até ontem e não está na carga — não pode ser lido nem
      escrito.
    """
    rnd = random.Random(semente)
    dias = _pregoes(n_pregoes)
    linhas: list[list] = []
    precos = {t: 10.0 + i for i, t in enumerate([*LIQUIDOS, "ILIQ1", "ILIQ2",
                                                 "CURTO", "TERM1", "FORA"])}

    def andar(t):
        precos[t] = max(0.5, precos[t] * (1 + rnd.gauss(0, 0.02)))
        return round(precos[t], 2)

    for i, dia in enumerate(dias):
        captura = i + 1
        for t in LIQUIDOS:
            # Zero só em LIQ4 e LIQ5: LIQ1 fica limpo, para a janela dele
            # encher e a igualdade não ser só nulo = nulo.
            zero = t in ("LIQ4", "LIQ5") and rnd.random() < 0.05
            preco = 0.0 if zero else andar(t)
            linhas.append(_linha(dia, t, preco, captura))
        if i % 17 == 0:
            linhas.append(_linha(dia, "ILIQ1", andar("ILIQ1"), captura))
        if i in (0, 1, 2):
            linhas.append(_linha(dia, "ILIQ2", andar("ILIQ2"), captura))
        if i >= n_pregoes - 8:
            linhas.append(_linha(dia, "CURTO", andar("CURTO"), captura))
        linhas.append(_linha(dia, "TERM1", andar("TERM1"), captura,
                             prazo_termo="030", tp_mercado="030"))
        linhas.append(_linha(dia, "FORA", andar("FORA"), captura))
    return linhas, dias


def _delta(dia: str) -> list[list]:
    rnd = random.Random(99)
    return [
        *[_linha(dia, t, round(20 + rnd.random() * 5, 2), CAPTURA_DELTA)
          for t in [*LIQUIDOS, "ILIQ1", "ILIQ2", "CURTO"]],
        _linha(dia, "NOVO", 12.34, CAPTURA_DELTA),
        _linha(dia, "TERM1", 30.0, CAPTURA_DELTA, prazo_termo="030",
               tp_mercado="030"),
    ]


def _ds_e_campos(sink):
    ds = repo.dataset_vigente(sink, "b3_cotahist")
    campos = [c for c in repo.calculados_do(sink, ds["id"])
              if c["nome"] in CAMPOS]
    assert {c["nome"] for c in campos} == set(CAMPOS)
    return ds, campos


def _estado(sink) -> dict:
    linhas = sink.consultar(
        "SELECT dt_pregao, codneg, tp_mercado, prazo_termo, "
        + ", ".join(CAMPOS) + " FROM fato_negociacao"
    )
    return {
        (l["dt_pregao"], l["codneg"], l["tp_mercado"], l["prazo_termo"]):
            tuple(l[c] for c in CAMPOS)
        for l in linhas
    }


def _sujar_delta(sink):
    """Sentinela nas linhas da carga: se o UPDATE pular alguma, aparece."""
    sink.executar(
        "UPDATE fato_negociacao SET "
        + ", ".join(f"{c} = {SENTINELA}" for c in CAMPOS)
        + f" WHERE captura_id = {CAPTURA_DELTA}"
    )


def _espiar(sink, monkeypatch) -> list[tuple[str, list]]:
    executados: list[tuple[str, list]] = []
    original = sink.executar

    def espiar(sql, params=()):
        executados.append((sql, list(params)))
        return original(sql, params)

    monkeypatch.setattr(sink, "executar", espiar)
    return executados


def _updates_de_janela(executados) -> list[str]:
    return [sql for sql, _ in executados
            if "valor_calculado" in sql and sql.lstrip().startswith("UPDATE")]


def _preparar(sink, n_pregoes):
    seed_fontes.aplicar(sink)
    historico, dias = _historico(n_pregoes)
    sink.executar_muitos(INSERIR, historico)
    ds, campos = _ds_e_campos(sink)
    calc.aplicar(sink, ds, campos, capturas=None)   # histórico calculado
    novo_dia = _pregoes(n_pregoes + 1)[-1]
    sink.executar_muitos(INSERIR, _delta(novo_dia))
    return ds, campos, dias, novo_dia


def _tolerancia(sink) -> float:
    """Exato no Postgres (produção); 1e-12 relativo no DuckDB, só nas hv.

    O Postgres não tem transição inversa para agregado de `float8`: a cada
    linha ele reagrega a moldura do começo, na ordem — o mesmo conjunto de
    linhas dá o mesmo resultado bit a bit, leia-se a tabela inteira ou o
    recorte. O DuckDB agrega a moldura por árvore de segmentos, e a forma da
    árvore depende da posição da linha na partição — que é justamente o que o
    recorte muda. O `stddev_samp` pode então variar no último bit (medido:
    0.33069412124006 × 0.3306941212400599). `log_retorno` (lag, sem soma) é
    comparado exato nos dois.
    """
    from app.sinks import SinkPostgres

    return 0.0 if isinstance(sink, SinkPostgres) else 1e-12


def _comparar(a: dict, b: dict, *, tolerancia: float = 0.0):
    """Igualdade linha a linha, campo a campo. Nulo só é igual a nulo.

    A tolerância vale só para as hv (posições 1 e 2); log_retorno é exato.
    """
    assert a.keys() == b.keys()

    def igual(i, x, y):
        if x is None or y is None:
            return x is None and y is None
        if i == 0 or not tolerancia:
            return x == y
        return math.isclose(x, y, rel_tol=tolerancia)

    diferentes = [(k, a[k], b[k]) for k in sorted(a, key=str)
                  if not all(igual(i, x, y)
                             for i, (x, y) in enumerate(zip(a[k], b[k])))]
    assert not diferentes, f"{len(diferentes)} linhas divergem: {diferentes[:5]}"


# --------------------------------------------------------------------------
# Equivalência
# --------------------------------------------------------------------------
@pytest.mark.parametrize("n_pregoes", [
    90,   # histórico maior que hv63: o corte por data entra
    30,   # entre hv21 e hv63: hv63 lê a história inteira das partições
    5,    # menor que todas as janelas
])
def test_escopado_e_identico_ao_integral(sink, monkeypatch, n_pregoes):
    ds, campos, _, novo_dia = _preparar(sink, n_pregoes)

    # Caminho integral de antes: sem alcance derivável, a leitura é a tabela
    # inteira (a escrita continua recortada à carga, como já era).
    with monkeypatch.context() as m:
        m.setattr(calc, "alcance_para_tras", lambda *a, **k: None)
        _sujar_delta(sink)
        executados = _espiar(sink, m)
        calc.aplicar(sink, ds, campos, capturas=[CAPTURA_DELTA])
        assert all("AS afetada" not in sql
                   for sql in _updates_de_janela(executados))
    integral = _estado(sink)

    with monkeypatch.context() as m:
        _sujar_delta(sink)
        executados = _espiar(sink, m)
        calc.aplicar(sink, ds, campos, capturas=[CAPTURA_DELTA])
        updates = _updates_de_janela(executados)
        assert len(updates) == 3
        assert all("AS afetada" in sql for sql in updates), \
            "o caminho escopado não foi tomado"
    escopado = _estado(sink)

    # E a verdade de chão: tudo recalculado do zero, sem recorte nenhum.
    calc.aplicar(sink, ds, campos, capturas=None)
    do_zero = _estado(sink)

    assert all(SENTINELA not in v for v in escopado.values()), \
        "linha da carga ficou sem escrever"
    # Integral × escopado e do zero × escopado. No do zero o histórico também
    # é reescrito, com partições uma linha maiores que no primeiro cálculo —
    # no DuckDB, mesmo efeito de árvore de segmentos (ver `_tolerancia`).
    _comparar(integral, escopado, tolerancia=_tolerancia(sink))
    _comparar(do_zero, escopado, tolerancia=_tolerancia(sink))

    # As linhas da carga têm valor de verdade nos tickers líquidos quando o
    # histórico enche a janela — senão a igualdade podia ser nulo = nulo.
    liq = escopado[(novo_dia, "LIQ1", "010", None)]
    assert liq[0] is not None
    if n_pregoes >= 63:
        assert liq[1] is not None and liq[2] is not None


def test_ticker_novo_sem_historico(sink):
    ds, campos, _, novo_dia = _preparar(sink, 30)
    _sujar_delta(sink)
    calc.aplicar(sink, ds, campos, capturas=[CAPTURA_DELTA])
    novo = _estado(sink)[(novo_dia, "NOVO", "010", None)]
    assert novo == (None, None, None)


def test_janela_maior_que_o_historico_disponivel(sink, monkeypatch):
    """CURTO tem 8 pregões + o da carga: hv21 e hv63 nulos, log_retorno não.
    E com 30 pregões na tabela não existe o 62º valor distinto: hv63 não tem
    corte e lê a história inteira das partições da carga."""
    ds, campos, _, novo_dia = _preparar(sink, 30)
    _sujar_delta(sink)
    executados = _espiar(sink, monkeypatch)
    calc.aplicar(sink, ds, campos, capturas=[CAPTURA_DELTA])
    curto = _estado(sink)[(novo_dia, "CURTO", "010", None)]
    assert curto[0] is not None
    assert curto[1] is None and curto[2] is None

    hv63 = next(sql for sql in _updates_de_janela(executados)
                if "SET hv63" in sql)
    assert "AS afetada" in hv63 and "AS descoberta" not in hv63
    hv21 = next(sql for sql in _updates_de_janela(executados)
                if "SET hv21" in sql)
    assert "AS descoberta" in hv21


# --------------------------------------------------------------------------
# Retroação: o escopo não se aplica
# --------------------------------------------------------------------------
def test_retroacao_cai_no_caminho_integral(sink, monkeypatch):
    """Um pregão do meio chega depois dos posteriores (fazer histórico).

    As linhas posteriores ganham antecessor e precisam ser reescritas; o
    escopo não pode entrar. O resultado tem de bater com o recálculo do zero.
    """
    seed_fontes.aplicar(sink)
    historico, dias = _historico(70)
    buraco = dias[40]
    sink.executar_muitos(INSERIR, [l for l in historico if l[4] != buraco])
    ds, campos = _ds_e_campos(sink)
    calc.aplicar(sink, ds, campos, capturas=None)

    atrasadas = [l for l in historico if l[4] == buraco]
    for l in atrasadas:
        l[0] = CAPTURA_DELTA
    sink.executar_muitos(INSERIR, atrasadas)

    executados = _espiar(sink, monkeypatch)
    calc.aplicar(sink, ds, campos, capturas=[CAPTURA_DELTA])
    updates = _updates_de_janela(executados)
    assert len(updates) == 3
    assert all("AS afetada" not in sql and "captura_id IN" not in sql
               for sql in updates), "retroação não pode usar o recorte"
    depois = _estado(sink)

    monkeypatch.undo()
    calc.aplicar(sink, ds, campos, capturas=None)
    _comparar(_estado(sink), depois, tolerancia=_tolerancia(sink))


# --------------------------------------------------------------------------
# O recorte lê menos — medido
# --------------------------------------------------------------------------
def test_escopado_le_so_as_chaves_da_carga_e_o_alcance(sink):
    _, _, dias, novo_dia = _preparar(sink, 90)
    total = sink.um("SELECT count(*) AS n FROM fato_negociacao")["n"]

    def lidas(alcance):
        fonte, params = calc.leitura_escopada(
            sink, "fato_negociacao", ["codneg"], "dt_pregao",
            [CAPTURA_DELTA], alcance, novo_dia,
        )
        linhas = sink.consultar(
            f"SELECT codneg, count(*) AS n FROM {fonte} GROUP BY codneg",
            params,
        )
        return {l["codneg"]: l["n"] for l in linhas}

    da_carga = {"LIQ1", "LIQ2", "LIQ3", "LIQ4", "LIQ5", "ILIQ1", "ILIQ2",
                "CURTO", "NOVO", "TERM1"}

    for alcance in (1, 20, 62):
        por_ticker = lidas(alcance)
        assert set(por_ticker) == da_carga, "leu partição fora da carga"
        assert "FORA" not in por_ticker
        # Líquido: exatamente o alcance para trás, mais a linha da carga.
        for t in [*LIQUIDOS, "TERM1"]:
            assert por_ticker[t] == alcance + 1, (t, alcance)
        # Ilíquido não coberto pelo corte: lido inteiro, senão a janela
        # truncaria (ILIQ1 tem 90/17 ≈ 6 linhas; ILIQ2, três).
        assert por_ticker["ILIQ2"] == 4
        assert por_ticker["ILIQ1"] == len(range(0, 90, 17)) + 1
        assert por_ticker["NOVO"] == 1
        assert sum(por_ticker.values()) < total

    # log_retorno lê dois pregões dos líquidos; o integral leria a tabela.
    assert sum(lidas(1).values()) <= 0.1 * total


# --------------------------------------------------------------------------
# O alcance é derivado da configuração, nunca fixado
# --------------------------------------------------------------------------
@pytest.mark.parametrize("expressao, moldura, esperado", [
    ("lag(x) {OVER}", None, 1),
    ("lag(x, 3) {OVER}", None, 3),
    ("lag(x, 3, 0) {OVER}", "ROWS BETWEEN 1 PRECEDING AND CURRENT ROW", 3),
    ("ln(x / lag(x) {OVER})", None, 1),
    ("stddev_samp(x) {OVER}", "ROWS BETWEEN 20 PRECEDING AND CURRENT ROW", 20),
    ("sum(x) {OVER}", "ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING", 5),
    ("lag(x, 70) {OVER} + avg(x) {OVER}",
     "ROWS BETWEEN 9 PRECEDING AND CURRENT ROW", 70),
    # Não sei dizer → integral.
    ("sum(x) {OVER}", None, None),                     # acumula desde o início
    ("sum(x) {OVER}", "RANGE BETWEEN 5 PRECEDING AND CURRENT ROW", None),
    ("sum(x) {OVER}", "ROWS BETWEEN 5 PRECEDING AND 2 FOLLOWING", None),
    ("lead(x) {OVER}", None, None),                    # olha para a frente
    ("row_number() {OVER}", None, None),
    ("lag(x, n) {OVER}", None, None),                  # deslocamento não literal
    ("versao = max(versao) {OVER}", None, None),       # is_latest
    ("(SELECT max(y) FROM t) + lag(x) {OVER}", None, None),
    ("x + 1", None, None),                             # sem {OVER}
    # Falso-seguro que a revisão achou: só `{OVER}` é enxergado.
    ("lag(x) {OVER} + row_number() OVER (PARTITION BY p ORDER BY d)",
     None, None),
    ("lag(x) {OVER} + count(*) over (partition by p)", None, None),
    ("ntile(CASE WHEN $$lag($$ = $$x$$ THEN 5 ELSE 3 END) {OVER}", None, None),
    ('lag("x(") {OVER}', None, None),
    ("lag(x IGNORE NULLS) {OVER}", None, None),
    ("LAG(x) {OVER}", None, 1),
])
def test_alcance_para_tras(expressao, moldura, esperado):
    assert calc.alcance_para_tras(expressao, moldura) == esperado


def test_alcance_dos_campos_do_catalogo(sink):
    seed_fontes.aplicar(sink)
    ds, campos = _ds_e_campos(sink)
    alcance = {c["nome"]: calc.alcance_para_tras(c["expressao"], c.get("moldura"))
               for c in campos}
    assert alcance == {"log_retorno": 1, "hv21": 20, "hv63": 62}


# --------------------------------------------------------------------------
# Onde o recorte se desliga sozinho
# --------------------------------------------------------------------------
def _caminhos(executados) -> list[bool]:
    return ["AS afetada" in sql for sql in _updates_de_janela(executados)]


def test_particao_nula_na_carga_cai_no_integral(sink, monkeypatch):
    """`=` não casa nulo com nulo, e o PARTITION BY junta os nulos: com
    partição nula na carga o recorte perderia o histórico dela."""
    ds, campos, _, novo_dia = _preparar(sink, 30)
    sink.executar(
        "UPDATE fato_negociacao SET codneg = NULL "
        f"WHERE captura_id = {CAPTURA_DELTA} AND codneg = 'NOVO'"
    )
    executados = _espiar(sink, monkeypatch)
    calc.aplicar(sink, ds, campos, capturas=[CAPTURA_DELTA])
    assert _caminhos(executados) == [False, False, False]


def test_nulo_na_ordenacao_cai_no_integral(sink, monkeypatch):
    ds, campos, _, _ = _preparar(sink, 30)
    sink.executar(
        "UPDATE fato_negociacao SET dt_pregao = NULL "
        "WHERE codneg = 'FORA' AND captura_id = 1"
    )
    executados = _espiar(sink, monkeypatch)
    calc.aplicar(sink, ds, campos, capturas=[CAPTURA_DELTA])
    assert _caminhos(executados) == [False, False, False]


def test_carga_que_encosta_no_ultimo_pregao(sink, monkeypatch):
    """Carga de duas datas cuja menor é igual à maior já existente (parte do
    último pregão reprocessada numa captura nova, mais o pregão seguinte):
    continua sendo carga no fim, e o recorte tem de dar o mesmo resultado."""
    seed_fontes.aplicar(sink)
    historico, dias = _historico(80)
    ultimo = dias[-1]
    # LIQ1 e TERM1 do último pregão chegam de novo, na captura da carga.
    reproc = [l for l in historico
              if l[4] == ultimo and l[5] in ("LIQ1", "TERM1")]
    sink.executar_muitos(INSERIR, [l for l in historico if l not in reproc])
    ds, campos = _ds_e_campos(sink)
    calc.aplicar(sink, ds, campos, capturas=None)
    novo_dia = _pregoes(81)[-1]
    for l in reproc:
        l[0] = CAPTURA_DELTA
    sink.executar_muitos(INSERIR, [*reproc, *_delta(novo_dia)])

    with monkeypatch.context() as m:
        m.setattr(calc, "alcance_para_tras", lambda *a, **k: None)
        _sujar_delta(sink)
        calc.aplicar(sink, ds, campos, capturas=[CAPTURA_DELTA])
    integral = _estado(sink)

    with monkeypatch.context() as m:
        _sujar_delta(sink)
        executados = _espiar(sink, m)
        calc.aplicar(sink, ds, campos, capturas=[CAPTURA_DELTA])
        assert _caminhos(executados) == [True, True, True]
    escopado = _estado(sink)
    assert all(SENTINELA not in v for v in escopado.values())
    _comparar(integral, escopado, tolerancia=_tolerancia(sink))
