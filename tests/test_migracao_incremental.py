"""Migrar um banco que já tem configuração — que é o caso de produção.

A suíte inteira aplica as migrações do zero, e do zero tudo passa. Produção
não é zero: ela está na `0011`, com configuração viva. A `0013` **recria**
`cfg_campo_calculado` — renomeia, cria, copia, descarta —, e é aí que um banco
povoado se comporta diferente de um vazio.

A configuração antiga é inserida por SQL, não pelo seed: o seed deste commit
já escreve colunas que só existem depois da `0012`, e produção nunca o executa
contra o schema velho — `entrada.sh` roda `migrar --seed`, que migra primeiro.
Reproduzir a ordem errada testaria um caminho que não existe.
"""
from __future__ import annotations

import pytest

from app import migracoes, seed_cvm
from app.sinks import SinkDuckDB

# Os três campos calculados que resolvem armadilhas da CVM. Se a recriação da
# tabela os perdesse, sumiriam a escala, a reapresentação e o acumulado do ITR
# — e o dado continuaria sendo servido, errado.
CALCULADOS_ANTIGOS = [
    (1, "vl_conta_norm", "escalar",
     "vl_conta * CASE upper(escala_moeda) WHEN 'MIL' THEN 1000 ELSE 1 END",
     "vl_conta,escala_moeda", "numeric", None, None),
    (2, "itr_acumulado", "escalar", "upper(tipo_doc) = 'ITR'",
     "tipo_doc,grupo", "boolean", None, None),
    (3, "is_latest", "janela", "versao = max(versao) {OVER}",
     "versao,cd_cvm", "boolean", "cd_cvm,tipo_doc,dt_refer", None),
]


@pytest.fixture()
def ate_0011():
    """Um banco no estado em que produção estava antes desta leva."""
    s = SinkDuckDB(":memory:")
    migracoes.aplicar(s, ate="0011_correlacao")
    for linha in CALCULADOS_ANTIGOS:
        # Pela sequência, como produção fez: `0013` recria a tabela e não a
        # sequência, então o próximo id continua onde parou. Cravar id à mão
        # aqui faria o seed seguinte colidir — no teste, não em produção.
        s.executar(
            """INSERT INTO cfg_campo_calculado
               (id, dataset_id, nome, classe, expressao, colunas_origem,
                tipo_retorno, particao_por, ordena_por, materializacao,
                descricao, ativo, ordem)
               VALUES (?, 7, ?, ?, ?, ?, ?, ?, ?, 'coluna', NULL, TRUE, ?)""",
            (s.proximo_id("cfg_campo_calculado"), linha[1], linha[2], linha[3],
             linha[4], linha[5], linha[6], linha[7], linha[0]),
        )
    yield s
    s.fechar()


def test_o_banco_parou_onde_deveria(ate_0011):
    aplicadas = {
        r["nome"] for r in ate_0011.consultar("SELECT nome FROM schema_migracao")
    }
    assert "0011_correlacao" in aplicadas
    assert "0013_campo_numerico" not in aplicadas


def test_campo_calculado_sobrevive_a_recriacao_da_tabela(ate_0011):
    """O risco concreto deste deploy."""
    def retrato():
        return {
            (r["id"], r["nome"], r["classe"], r["expressao"],
             r["colunas_origem"], r["tipo_retorno"], r["particao_por"],
             r["dataset_id"], r["ordem"], r["ativo"])
            for r in ate_0011.consultar("SELECT * FROM cfg_campo_calculado")
        }

    antes = retrato()
    assert {t[1] for t in antes} == {"vl_conta_norm", "itr_acumulado", "is_latest"}

    migracoes.aplicar(ate_0011)

    assert retrato() == antes, "a recriação da tabela mudou o que estava guardado"


def test_a_tabela_intermediaria_nao_fica_para_tras(ate_0011):
    """`cfg_campo_calculado_ate_v12` é andaime. Deixá-la no banco confundiria
    quem for depurar dali a seis meses."""
    migracoes.aplicar(ate_0011)
    sobrou = ate_0011.um(
        "SELECT 1 AS ok FROM information_schema.tables "
        "WHERE table_name = 'cfg_campo_calculado_ate_v12'"
    )
    assert sobrou is None


def test_a_coluna_nova_nasce_nula(ate_0011):
    migracoes.aplicar(ate_0011)
    assert ate_0011.um(
        "SELECT moldura FROM cfg_campo_calculado WHERE nome = 'is_latest'"
    )["moldura"] is None


def test_a_classe_nova_passa_a_ser_aceita(ate_0011):
    """O CHECK antigo só permitia escalar e janela. Se a recriação tivesse
    copiado o CHECK velho, o seed seguinte falharia no primeiro campo
    numérico — e falharia no deploy, não aqui."""
    migracoes.aplicar(ate_0011)
    ate_0011.executar(
        """INSERT INTO cfg_campo_calculado
           (id, dataset_id, nome, classe, expressao, colunas_origem,
            tipo_retorno, materializacao, ativo, ordem)
           VALUES (99, 7, 'iv', 'numerico', 'bs_iv(a,b,c,d,e,f)', 'a',
                   'numeric', 'coluna', TRUE, 1)"""
    )
    assert ate_0011.um(
        "SELECT classe FROM cfg_campo_calculado WHERE id = 99"
    )["classe"] == "numerico"


def test_migrar_e_semear_na_ordem_do_deploy(ate_0011):
    """`entrada.sh` roda `migrar --seed`: migra e semeia no mesmo comando."""
    migracoes.aplicar(ate_0011)
    seed_cvm.aplicar(ate_0011)

    classes = {
        r["chave"] for r in ate_0011.consultar(
            "SELECT chave FROM cfg_classe WHERE vigente"
        )
    }
    assert "negociacao_b3" in classes
    assert ate_0011.um(
        "SELECT count(*) AS n FROM cfg_tarifa WHERE recurso = 'armazenamento'"
    )["n"] == 1
    assert ate_0011.um(
        "SELECT valor FROM cfg_parametro WHERE chave = 'indicador_cambio'"
    )["valor"] == "cambio_usd_brl"


# --------------------------------------------------------------------------
# Atomicidade
# --------------------------------------------------------------------------
def test_migracao_que_falha_no_meio_nao_deixa_rastro(ate_0011, monkeypatch):
    """A conexão de produção é autocommit: cada statement confirmaria sozinho.

    Sem transação, uma falha entre o `RENAME` e o `INSERT` da `0013` deixaria
    a configuração dentro de `cfg_campo_calculado_ate_v12` e nenhuma tabela
    com o nome que o sistema procura — e sem registro em `schema_migracao`,
    então o conserto teria de adivinhar até onde a migração chegou.
    """
    antes = ate_0011.um("SELECT count(*) AS n FROM cfg_campo_calculado")["n"]

    quebrada = migracoes.Migracao(
        nome="9999_quebra_no_meio",
        sql=[
            "ALTER TABLE cfg_campo_calculado RENAME TO cfg_campo_calculado_meio",
            "ISTO NÃO É SQL",
        ],
    )
    monkeypatch.setattr(migracoes, "MIGRACOES", [*migracoes.MIGRACOES, quebrada])

    with pytest.raises(Exception):
        migracoes.aplicar(ate_0011)

    assert ate_0011.um(
        "SELECT count(*) AS n FROM cfg_campo_calculado"
    )["n"] == antes
    aplicadas = {
        r["nome"] for r in ate_0011.consultar("SELECT nome FROM schema_migracao")
    }
    assert "9999_quebra_no_meio" not in aplicadas
