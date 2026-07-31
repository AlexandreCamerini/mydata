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

from .. import repositorio as repo
from ..migracoes import TABELAS_SILVER
from ..sinks import Sink
from . import ddl

log = logging.getLogger("portal.publicacao")

def vistas(sink: Sink) -> dict[str, str]:
    """As vistas de gold e seus corpos, com `{V}` ainda por substituir.

    Vem de `cfg_vista`, não mais de um dicionário em Python: é o que permite
    publicar uma classe nova sem editar este arquivo. Vista cuja classe ainda
    não foi materializada é pulada — banco recém-migrado e sem configuração
    responde vazio em vez de quebrar no boot.
    """
    saida: dict[str, str] = {}
    for v in repo.listar_vistas(sink):
        classe = repo.classe_vigente(sink, v["classe_chave"])
        if classe is None or not ddl.colunas_fisicas(sink, classe["tabela"]):
            log.warning(
                "vista %s ignorada: classe '%s' não está materializada",
                v["chave"], v["classe_chave"],
            )
            continue
        saida[v["chave"]] = v["corpo"]
    return saida


def tabelas_publicaveis(sink: Sink) -> tuple[str, ...]:
    """As tabelas que participam do rótulo de publicação.

    São as tabelas das classes ativas. `TABELAS_SILVER` permanece como piso
    para uma base anterior à Etapa 1, migrada e ainda sem classe cadastrada:
    sem isso, um deploy que rodasse a migração antes do seed pararia de
    publicar em silêncio.
    """
    tabelas = [c["tabela"] for c in repo.listar_classes(sink, so_ativas=True)]
    if not tabelas:
        tabelas = list(TABELAS_SILVER)
    return tuple(
        dict.fromkeys(t for t in tabelas if ddl.colunas_fisicas(sink, t))
    )


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
