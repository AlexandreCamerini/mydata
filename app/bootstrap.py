"""Preparo do banco: migrações + ponteiros de gold vazios.

Separado de `migracoes` para evitar ciclo de import — `publicacao` precisa de
`migracoes.TABELAS_SILVER`.
"""
from __future__ import annotations

from . import migracoes
from .motor import ddl, publicacao
from .sinks import Sink


def preparar(sink: Sink) -> list[str]:
    """Deixa o banco pronto para uso. Idempotente."""
    novas = migracoes.aplicar(sink)
    # A tabela de uma classe é consequência da configuração, não de código:
    # materializar aqui é o que faz classe cadastrada em outra instância
    # existir fisicamente neste banco depois de um deploy.
    ddl.garantir_classes(sink)
    # Gold precisa existir antes da primeira carga, senão a API quebra entre
    # a migração e a primeira publicação. Aponta para a publicação corrente —
    # recriar no boot não pode esconder dado já publicado.
    publicacao.garantir_ponteiros(sink)
    return novas
