"""Preparo do banco: migrações + ponteiros de gold vazios.

Separado de `migracoes` para evitar ciclo de import — `publicacao` precisa de
`migracoes.TABELAS_SILVER`.
"""
from __future__ import annotations

from . import migracoes
from .motor import publicacao
from .sinks import Sink


def preparar(sink: Sink) -> list[str]:
    """Deixa o banco pronto para uso. Idempotente."""
    novas = migracoes.aplicar(sink)
    # Gold precisa existir antes da primeira carga, senão a API quebra entre
    # a migração e a primeira publicação.
    publicacao.criar_views_vazias(sink)
    return novas
