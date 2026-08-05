"""Proveniência anexada a cada linha de dado.

Mora fora de `main` porque as duas superfícies decoram: `/v1`, que serve o
consumidor, e `/admin/api`, que serve o dono conferindo uma travessia. Com o
código em `main`, o plano de controle teria de importar quem já o importa — e
a alternativa seria uma segunda cópia, divergindo na primeira mudança.
"""
from __future__ import annotations

from ..motor.ddl import SUFIXO_ORIGEM
from ..sinks import Sink


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


def decorar(sink: Sink, linhas: list[dict]) -> list[dict]:
    """Anexa proveniência a cada linha e remove colunas internas.

    Numa classe alimentada por mais de uma fonte, dizer "veio da captura X"
    não basta: atributos diferentes da mesma linha podem ter vindo de fontes
    diferentes. As colunas `<atributo>_origem` que a vista resolvida produz
    viram `proveniencia.por_atributo`, em vez de campos soltos no dado.
    """
    prov = de_capturas(sink, {r["captura_id"] for r in linhas if r.get("captura_id")})
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
        item["proveniencia"] = {
            **prov.get(captura, {}),
            "versao_documento": linha.get("versao"),
            "publicacao": versao_pub,
        }
        if por_atributo:
            item["proveniencia"]["por_atributo"] = por_atributo
        saida.append(item)
    return saida
