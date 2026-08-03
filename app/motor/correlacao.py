"""Junção entre classes, declarada em configuração e executada com escopo.

Enquanto a junção estiver na consulta de quem consome, três coisas se perdem:
o escopo por classe da chave de API não enxerga a travessia, cada consumidor
reinventa a ligação — inclusive errada —, e ninguém consegue dizer que
`empresa` e `demonstracao_financeira` se ligam por `cd_cvm` sem ler o código
de alguém.

Declarada, a junção é dado: `cfg_correlacao` diz quais classes, por quais
atributos e com que cardinalidade. Sem linha correspondente, a travessia é
recusada — como o Cube recusa com "can't find join path". Nunca há inferência.
Ver `docs/pesquisa-mercado.md` § Q7.

**Nenhum SQL vem de fora.** Nome de vista, de coluna e de atributo são
conferidos contra o que a configuração declara e contra as colunas físicas que
existem; valor de filtro sempre viaja como parâmetro. É a mesma guarda que o
gerador de DDL aplica, pelo mesmo motivo.
"""
from __future__ import annotations

from .. import repositorio as repo
from ..sinks import Sink
from . import ddl, publicacao

LIMITE_PADRAO = 50
LIMITE_MAXIMO = 500


class ErroCorrelacao(ValueError):
    """Travessia pedida que a configuração não declara, ou não permite."""


def vista_principal(sink: Sink, classe_chave: str) -> str:
    """A vista de gold pela qual uma classe é lida.

    Uma classe pode ter mais de uma vista — `demonstracao_financeira` tem a
    publicada e a de trimestre isolado. A de menor ordem é a canônica; é a que
    o consumidor recebe quando não pede outra coisa.
    """
    candidatas = [
        v for v in repo.listar_vistas(sink) if v["classe_chave"] == classe_chave
    ]
    if candidatas:
        return min(candidatas, key=lambda v: (v["ordem"], v["chave"]))["chave"]
    # Classe que resolve por precedência tem a vista gerada, não cadastrada.
    gerada = f"gold_{classe_chave}"
    if gerada in publicacao.vistas(sink):
        return gerada
    raise ErroCorrelacao(f"a classe '{classe_chave}' não tem vista publicada")


def _colunas(sink: Sink, vista: str) -> set[str]:
    return {c.lower() for c in ddl.colunas_fisicas(sink, vista)}


def _validar_campos(pedidos: list[str], disponiveis: set[str], onde: str) -> list[str]:
    faltando = [c for c in pedidos if c.lower() not in disponiveis]
    if faltando:
        raise ErroCorrelacao(
            f"{onde} não tem a coluna: {', '.join(faltando)}. "
            f"Disponíveis: {', '.join(sorted(disponiveis))}"
        )
    return [c.lower() for c in pedidos]


def consultar(
    sink: Sink,
    chave: str,
    *,
    campos_destino: list[str] | None = None,
    filtros_destino: dict[str, str] | None = None,
    limite: int = LIMITE_PADRAO,
) -> dict:
    """Executa uma correlação declarada.

    Devolve as linhas da classe de origem com os campos pedidos da classe de
    destino, mais a proveniência das duas pontas: quem pergunta "de onde veio"
    precisa da resposta para cada metade, não para o conjunto.
    """
    cfg = repo.correlacao_vigente(sink, chave)
    if cfg is None or not cfg["ativo"]:
        raise ErroCorrelacao(
            f"correlação '{chave}' não está declarada. Uma junção entre classes "
            f"só existe quando alguém a declarou — não há inferência aqui."
        )

    origem = vista_principal(sink, cfg["classe_origem"])
    destino = vista_principal(sink, cfg["classe_destino"])
    cols_origem = _colunas(sink, origem)
    cols_destino = _colunas(sink, destino)

    _validar_campos([cfg["atributo_origem"]], cols_origem, f"a vista '{origem}'")
    _validar_campos([cfg["atributo_destino"]], cols_destino, f"a vista '{destino}'")

    pedidos = _validar_campos(
        campos_destino or [cfg["atributo_destino"]],
        cols_destino,
        f"a vista '{destino}'",
    )
    filtros = filtros_destino or {}
    _validar_campos(list(filtros), cols_destino, f"a vista '{destino}'")

    limite = max(1, min(int(limite), LIMITE_MAXIMO))

    selecao = ", ".join(
        [f"o.{c} AS {c}" for c in sorted(cols_origem)]
        + [f"d.{c} AS destino_{c}" for c in pedidos if f"destino_{c}" not in cols_origem]
    )
    condicoes = [f"d.{c} = ?" for c in filtros]
    params = list(filtros.values())
    onde = (" AND " + " AND ".join(condicoes)) if condicoes else ""

    linhas = sink.consultar(
        f"SELECT {selecao} FROM {origem} o "
        f"JOIN {destino} d ON d.{cfg['atributo_destino']} = o.{cfg['atributo_origem']}"
        f"{' WHERE 1=1' + onde if onde else ''} "
        f"ORDER BY o.{cfg['atributo_origem']} LIMIT {limite}",
        params,
    )

    return {
        "correlacao": {
            "chave": cfg["chave"],
            "origem": {"classe": cfg["classe_origem"], "vista": origem,
                       "atributo": cfg["atributo_origem"]},
            "destino": {"classe": cfg["classe_destino"], "vista": destino,
                        "atributo": cfg["atributo_destino"]},
            "relacionamento": cfg["relacionamento"],
            "descricao": cfg["descricao"],
        },
        "dados": linhas,
    }


def classes_da(sink: Sink, chave: str) -> tuple[str, str]:
    """As duas classes que uma correlação atravessa.

    Quem chama usa para conferir o escopo da chave de API **antes** de
    executar: uma travessia que alcança classe fora do escopo é negada
    inteira, nunca servida com as colunas daquela classe omitidas em silêncio.
    """
    cfg = repo.correlacao_vigente(sink, chave)
    if cfg is None:
        raise ErroCorrelacao(f"correlação '{chave}' não está declarada")
    return cfg["classe_origem"], cfg["classe_destino"]
