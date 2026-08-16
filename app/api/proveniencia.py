"""Proveniência anexada a cada linha de dado.

Mora fora de `main` porque as duas superfícies decoram: `/v1`, que serve o
consumidor, e `/admin/api`, que serve o dono conferindo uma travessia. Com o
código em `main`, o plano de controle teria de importar quem já o importa — e
a alternativa seria uma segunda cópia, divergindo na primeira mudança.
"""
from __future__ import annotations

from .. import repositorio as repo
from ..motor import ddl
from ..motor.ddl import SUFIXO_ORIGEM
from ..sinks import Sink
from . import auth


DATASETS_B3 = frozenset({"b3_cotahist", "b3_instrumentos", "b3_listadas"})


def de_capturas(sink: Sink, capturas: set[int]) -> dict:
    if not capturas:
        return {}
    marcadores = ",".join("?" for _ in capturas)
    linhas = sink.consultar(
        f"SELECT id, url, sha256, capturado_em, nome_arquivo FROM bronze_captura "
        f"WHERE id IN ({marcadores})",
        list(capturas),
    )
    return {
        linha["id"]: {
            "fonte": linha["url"],
            "arquivo": linha["nome_arquivo"],
            "sha256": linha["sha256"],
            "dt_captura": (
                linha["capturado_em"].isoformat()
                if hasattr(linha["capturado_em"], "isoformat")
                else str(linha["capturado_em"])
            ),
            # Sem estes dois, o `sha256` acima é um número que o consumidor
            # teria de aceitar no fio do bigode: a URL de origem é endereço
            # mutável e não reproduz a captura. Com eles, ele baixa e confere.
            "captura": linha["id"],
            "arquivo_em": f"/v1/capturas/{linha['id']}/arquivo",
        }
        for linha in linhas
    }


def _atributos_b3(sink: Sink, classe: str) -> tuple[set[str], set[str]]:
    """Classifica atributos B3-only e atributos disputados com B3.

    A classificação vem dos datasets realmente cadastrados para a classe; não
    é uma lista de campos de domínio. Ela é calculada uma vez por resposta,
    antes de percorrer as linhas.
    """
    configuracao = repo.classe_vigente(sink, classe)
    if configuracao is None:
        raise ValueError(f"classe inexistente para proveniência: {classe}")
    mapa = ddl.datasets_por_atributo(sink, configuracao)
    somente_b3 = set()
    disputados = set()
    for atributo, candidatos in mapa.items():
        candidatos_set = set(candidatos)
        if candidatos_set and candidatos_set <= DATASETS_B3:
            somente_b3.add(atributo)
        elif candidatos_set & DATASETS_B3:
            disputados.add(atributo)
    return somente_b3, disputados


def decorar(
    sink: Sink,
    linhas: list[dict],
    classe: str | None = None,
    chave: dict | None = None,
) -> list[dict]:
    """Anexa proveniência a cada linha e remove colunas internas.

    Numa classe alimentada por mais de uma fonte, dizer "veio da captura X"
    não basta: atributos diferentes da mesma linha podem ter vindo de fontes
    diferentes. As colunas `<atributo>_origem` que a vista resolvida produz
    viram `proveniencia.por_atributo`, em vez de campos soltos no dado.
    """
    prov = de_capturas(sink, {r["captura_id"] for r in linhas if r.get("captura_id")})
    somente_b3: set[str] = set()
    disputados_b3: set[str] = set()
    if chave is not None and not auth.pode_ver_fonte(chave, "b3"):
        if classe is None:
            raise ValueError("classe é obrigatória para filtrar proveniência B3")
        somente_b3, disputados_b3 = _atributos_b3(sink, classe)

    saida = []
    for linha in linhas:
        captura = linha.pop("captura_id", None)
        linha.pop("fonte_arquivo", None)
        versao_pub = linha.pop("publicado_em_versao", None)
        por_atributo = {
            chave[: -len(SUFIXO_ORIGEM)]: linha.pop(chave)
            for chave in [c for c in linha if c.endswith(SUFIXO_ORIGEM)]
        }
        item = dict(linha)
        if somente_b3 or disputados_b3:
            remover = somente_b3 | {
                atributo for atributo in disputados_b3
                if por_atributo.get(atributo) in DATASETS_B3
            }
            for atributo in remover:
                item.pop(atributo, None)
                por_atributo.pop(atributo, None)
        item["proveniencia"] = {
            **prov.get(captura, {}),
            "versao_documento": linha.get("versao"),
            "publicacao": versao_pub,
        }
        if por_atributo:
            item["proveniencia"]["por_atributo"] = por_atributo
        saida.append(item)
    return saida
