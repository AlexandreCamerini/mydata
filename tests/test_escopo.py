"""Acrescentar escopo a uma chave ativa sem trocar o segredo (`cli escopo`)."""
from __future__ import annotations

import pytest

from app import cli
from app.api import auth


class _Args:
    def __init__(self, prefixo: str, adicionar: str) -> None:
        self.prefixo, self.adicionar = prefixo, adicionar


def _com_sink(monkeypatch, sink):
    monkeypatch.setattr(cli, "criar_sink", lambda: sink)
    monkeypatch.setattr(sink, "fechar", lambda: None)


def test_acrescenta_setups_e_a_chave_passa_a_poder(monkeypatch, sink, capsys):
    emitida = auth.emitir(sink, "MCP serviço", 10, 100,
                          escopos="classe:empresa,fonte:b3")
    assert not auth.pode_setups(auth.verificar(sink, emitida.chave_completa))

    _com_sink(monkeypatch, sink)
    assert cli.cmd_escopo(_Args(emitida.prefixo, "setups")) == 0
    assert "ganhou" in capsys.readouterr().out

    chave = auth.verificar(sink, emitida.chave_completa)
    assert auth.pode_setups(chave)
    assert chave["escopos"] == "classe:empresa,fonte:b3,setups", \
        "o escopo novo entrou sem apagar os anteriores"


def test_segunda_vez_e_no_op(monkeypatch, sink, capsys):
    emitida = auth.emitir(sink, "x", 10, 100)
    _com_sink(monkeypatch, sink)
    assert cli.cmd_escopo(_Args(emitida.prefixo, "setups")) == 0
    assert cli.cmd_escopo(_Args(emitida.prefixo, "setups")) == 0
    assert "já tinha" in capsys.readouterr().out
    assert auth.verificar(sink, emitida.chave_completa)["escopos"] == "leitura,setups"


def test_revogada_ou_inexistente_falha_dizendo(monkeypatch, sink, capsys):
    emitida = auth.emitir(sink, "x", 10, 100)
    auth.revogar(sink, emitida.prefixo)
    _com_sink(monkeypatch, sink)
    assert cli.cmd_escopo(_Args(emitida.prefixo, "setups")) == 1
    assert cli.cmd_escopo(_Args("00000000", "setups")) == 1


def test_escopo_com_virgula_e_recusado(sink):
    emitida = auth.emitir(sink, "x", 10, 100)
    with pytest.raises(ValueError):
        auth.acrescentar_escopo(sink, emitida.prefixo, "setups,leitura")
