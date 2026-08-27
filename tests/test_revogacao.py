"""Revogar chave de API pelo prefixo.

A revogação é o único jeito de desligar uma credencial: como só o hash fica no
banco, uma chave cujo segredo se perdeu não pode ser recuperada nem conferida —
pode apenas ser revogada. Por isso o comando aceita o PREFIXO, que é público, e
não a chave inteira: exigir o segredo para desligar seria exigir justamente o
que falta no caso que mais importa.
"""
from __future__ import annotations

from app import cli
from app.api import auth


class _Args:
    def __init__(self, prefixo: str) -> None:
        self.prefixo = prefixo


def _com_sink(monkeypatch, sink):
    """O CLI abre o próprio sink; nos testes ele usa o da fixture."""
    monkeypatch.setattr(cli, "criar_sink", lambda: sink)
    monkeypatch.setattr(sink, "fechar", lambda: None)


def test_revogar_desliga_a_chave(monkeypatch, sink, capsys):
    emitida = auth.emitir(sink, "consumidor-de-teste", 10, 100)
    assert auth.verificar(sink, emitida.chave_completa) is not None

    _com_sink(monkeypatch, sink)
    assert cli.cmd_revogar(_Args(emitida.prefixo)) == 0
    assert emitida.prefixo in capsys.readouterr().out

    assert auth.verificar(sink, emitida.chave_completa) is None, \
        "a chave continuou valendo depois de revogada"


def test_revogar_prefixo_inexistente_falha_dizendo(monkeypatch, sink, capsys):
    _com_sink(monkeypatch, sink)
    assert cli.cmd_revogar(_Args("00000000")) == 1, \
        "código de saída 0 faria um script achar que revogou"
    assert "nada a revogar" in capsys.readouterr().out


def test_revogar_duas_vezes_e_seguro(monkeypatch, sink, capsys):
    """Idempotência importa: um script de limpeza roda duas vezes."""
    emitida = auth.emitir(sink, "consumidor-de-teste", 10, 100)
    _com_sink(monkeypatch, sink)
    assert cli.cmd_revogar(_Args(emitida.prefixo)) == 0
    assert cli.cmd_revogar(_Args(emitida.prefixo)) == 1
    assert "já está revogada" in capsys.readouterr().out


def test_revogar_nao_atinge_as_outras(monkeypatch, sink):
    """O erro caro seria derrubar a chave do consumidor que está em produção."""
    alvo = auth.emitir(sink, "descartavel", 10, 100)
    vizinha = auth.emitir(sink, "em-producao", 10, 100)

    _com_sink(monkeypatch, sink)
    cli.cmd_revogar(_Args(alvo.prefixo))

    assert auth.verificar(sink, vizinha.chave_completa) is not None, \
        "revogar uma chave derrubou outra"


# --------------------------------------------------------------------------
# Listagem
# --------------------------------------------------------------------------
class _ArgsLista:
    def __init__(self, consumidor=None, todas=False) -> None:
        self.consumidor = consumidor
        self.todas = todas


def test_chaves_lista_as_ativas_e_esconde_as_revogadas(monkeypatch, sink, capsys):
    viva = auth.emitir(sink, "consumidor-a", 10, 100)
    morta = auth.emitir(sink, "consumidor-a", 10, 100)
    auth.revogar(sink, morta.prefixo)

    _com_sink(monkeypatch, sink)
    assert cli.cmd_chaves(_ArgsLista()) == 0
    saida = capsys.readouterr().out
    assert viva.prefixo in saida
    assert morta.prefixo not in saida, "chave revogada apareceu como se valesse"

    assert cli.cmd_chaves(_ArgsLista(todas=True)) == 0
    assert morta.prefixo in capsys.readouterr().out


def test_chaves_nunca_imprime_o_segredo(monkeypatch, sink, capsys):
    """O segredo não está no banco — mas se um dia a query mudar e passar a
    trazer o hash, este teste quebra antes de virar um `cat` de credencial."""
    emitida = auth.emitir(sink, "consumidor-a", 10, 100)
    _com_sink(monkeypatch, sink)
    cli.cmd_chaves(_ArgsLista())
    saida = capsys.readouterr().out

    _, _, segredo = emitida.chave_completa.split("_", 2)
    assert segredo not in saida
    assert emitida.chave_completa not in saida
    assert "hash" not in saida.lower()


def test_chaves_separa_ampla_de_restrita(monkeypatch, sink, capsys):
    """A diferença decide o que a chave enxerga: `leitura` recebe os atributos
    de origem B3, restrita por classe não — e a resposta vem amputada com 200."""
    ampla = auth.emitir(sink, "consumidor-a", 10, 100)
    estreita = auth.emitir(sink, "consumidor-a", 10, 100,
                           escopos="classe:negociacao_b3")

    _com_sink(monkeypatch, sink)
    cli.cmd_chaves(_ArgsLista())
    linhas = {l.split()[0]: l for l in capsys.readouterr().out.splitlines()
              if l and not l.startswith(" ")}
    assert "AMPLA" in linhas[ampla.prefixo]
    assert "restrita" in linhas[estreita.prefixo]


def test_chaves_filtra_por_consumidor(monkeypatch, sink, capsys):
    minha = auth.emitir(sink, "portal-mcp", 10, 100)
    alheia = auth.emitir(sink, "bolsia", 10, 100)

    _com_sink(monkeypatch, sink)
    cli.cmd_chaves(_ArgsLista(consumidor="portal-mcp"))
    saida = capsys.readouterr().out
    assert minha.prefixo in saida
    assert alheia.prefixo not in saida, "o filtro vazou a chave de outro consumidor"
