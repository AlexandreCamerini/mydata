"""Publicação em gold: rótulo por linha + troca de ponteiro.

Duas metades, e as duas são necessárias:

1. **Rótulo por linha.** Linha carregada nasce sem `publicado_em_versao`.
   Gold só enxerga linha rotulada. É isso que faz o gate de qualidade valer:
   carga reprovada fica em silver, invisível para o consumidor, até ser
   corrigida ou descartada. Sem o rótulo, gold seria uma view sobre silver e
   o dado errado apareceria no mesmo instante em que fosse carregado.

2. **Ponteiro versionado.** Cada publicação cria `*_v{n}` e move o alias que a
   API lê. Reverter é mover o ponteiro de volta — a definição anterior
   continua existindo.

Limite conhecido: uma linha já publicada que seja sobrescrita por um upsert
com valor diferente muda em gold sem passar pelo gate. Para a CVM isso só
ocorreria se ela republicasse a mesma chave natural (mesma versão de
documento) com outro valor, o que é evento de integridade que merece
investigação, não acomodação.
"""
from __future__ import annotations

import logging

from ..migracoes import TABELAS_SILVER
from ..sinks import Sink

log = logging.getLogger("portal.publicacao")

# `{V}` é substituído pelo número da publicação.
VIEWS: dict[str, str] = {
    # Só o dado correto: última versão do documento, exercício de referência.
    "gold_demonstracoes": """
        SELECT cd_cvm, denom_cia, cnpj, tipo_doc, grupo, consolidado,
               dt_refer, dt_ini_exerc, dt_fim_exerc, versao,
               cd_conta, ds_conta, st_conta_fixa, escala_moeda, moeda,
               vl_conta, vl_conta_norm, itr_acumulado,
               captura_id, fonte_arquivo, publicado_em_versao
        FROM fato_conta
        WHERE is_latest AND ordem_exerc = 'ÚLTIMO'
          AND publicado_em_versao IS NOT NULL AND publicado_em_versao <= {V}
    """,
    # Trimestre isolado das contas de fluxo do ITR: acumulado menos acumulado
    # do período anterior do mesmo exercício. Q1 isolado = Q1 acumulado.
    "gold_itr_trimestre": """
        WITH acumulado AS (
          SELECT cd_cvm, denom_cia, grupo, consolidado, cd_conta, ds_conta,
                 dt_refer, vl_conta_norm, substr(dt_refer, 1, 4) AS exercicio,
                 captura_id, fonte_arquivo, publicado_em_versao
          FROM fato_conta
          WHERE is_latest AND ordem_exerc = 'ÚLTIMO'
            AND upper(tipo_doc) = 'ITR' AND itr_acumulado
            AND publicado_em_versao IS NOT NULL AND publicado_em_versao <= {V}
        )
        SELECT a.cd_cvm, a.denom_cia, a.grupo, a.consolidado, a.cd_conta,
               a.ds_conta, a.dt_refer, a.exercicio,
               a.vl_conta_norm AS vl_acumulado,
               a.vl_conta_norm - COALESCE(
                 LAG(a.vl_conta_norm) OVER (
                   PARTITION BY a.cd_cvm, a.grupo, a.consolidado, a.cd_conta,
                                a.exercicio
                   ORDER BY a.dt_refer
                 ), 0) AS vl_trimestre,
               a.captura_id, a.fonte_arquivo, a.publicado_em_versao
        FROM acumulado a
    """,
    "gold_empresa": """
        SELECT cd_cvm, cnpj, denom_social, denom_comerc, setor_atividade,
               situacao, controle_acionario, uf, municipio, dt_registro,
               captura_id, fonte_arquivo, publicado_em_versao
        FROM dim_empresa
        WHERE publicado_em_versao IS NOT NULL AND publicado_em_versao <= {V}
    """,
}


def vistas(sink: Sink) -> dict[str, str]:
    """As vistas de gold e seus corpos, com `{V}` ainda por substituir."""
    return dict(VIEWS)


def tabelas_publicaveis(sink: Sink) -> tuple[str, ...]:
    """As tabelas silver que participam do rótulo de publicação."""
    return TABELAS_SILVER


def versao_atual(sink: Sink) -> int:
    linha = sink.um("SELECT max(versao) AS v FROM publicacao")
    return int(linha["v"]) if linha and linha["v"] is not None else 0


def garantir_ponteiros(sink: Sink) -> int:
    """Garante que gold existe, apontando para a publicação corrente.

    Antes da primeira carga a versão é 0 e gold fica vazia — a API responde
    em vez de quebrar. Depois, aponta para a última publicação: recriar os
    ponteiros no boot não pode esconder dado já publicado.
    """
    versao = versao_atual(sink)
    for nome, corpo in vistas(sink).items():
        sink.executar(
            f"CREATE OR REPLACE VIEW {nome} AS " + corpo.replace("{V}", str(versao))
        )
    return versao


def publicar(
    sink: Sink, execucao_id: int | None = None, observacao: str | None = None
) -> int:
    """Rotula as linhas pendentes e move o ponteiro de gold para a nova versão."""
    nova = versao_atual(sink) + 1
    for tabela in tabelas_publicaveis(sink):
        sink.executar(
            f"UPDATE {tabela} SET publicado_em_versao = ? "
            f"WHERE publicado_em_versao IS NULL",
            (nova,),
        )
    for nome, corpo in vistas(sink).items():
        sink.executar(f"CREATE OR REPLACE VIEW {nome}_v{nova} AS "
                      + corpo.replace("{V}", str(nova)))
        sink.executar(f"CREATE OR REPLACE VIEW {nome} AS SELECT * FROM {nome}_v{nova}")
    sink.executar(
        "INSERT INTO publicacao (versao, execucao_id, observacao) VALUES (?,?,?)",
        (nova, execucao_id, observacao),
    )
    log.info("gold publicada: versão %d", nova)
    return nova


def descartar_nao_publicado(sink: Sink, capturas: list[int]) -> int:
    """Remove de silver as linhas que não passaram no gate.

    Só apaga linha sem rótulo — dado já publicado não é tocado.
    """
    if not capturas:
        return 0
    marcadores = ",".join("?" for _ in capturas)
    total = 0
    for tabela in tabelas_publicaveis(sink):
        antes = sink.um(f"SELECT count(*) AS n FROM {tabela}")["n"]
        sink.executar(
            f"DELETE FROM {tabela} WHERE publicado_em_versao IS NULL "
            f"AND captura_id IN ({marcadores})",
            capturas,
        )
        total += antes - sink.um(f"SELECT count(*) AS n FROM {tabela}")["n"]
    return total


def reverter(sink: Sink, versao: int) -> int:
    """Move o ponteiro de volta para uma versão já publicada."""
    existe = sink.um("SELECT versao FROM publicacao WHERE versao = ?", (versao,))
    if existe is None:
        raise ValueError(f"publicação {versao} não existe")
    for nome in vistas(sink):
        sink.executar(f"CREATE OR REPLACE VIEW {nome} AS SELECT * FROM {nome}_v{versao}")
    log.warning("gold revertida para a versão %d", versao)
    return versao
