"""Captura de fonte JSON paginada, declarada em configuração.

Até aqui o motor sabia dois transportes — ZIP e CSV —, e os dois entregam o
conteúdo inteiro numa requisição. Uma API paginada não entrega: são N
respostas que só juntas formam o que a fonte publicou.

Isto obriga a responder o que é "o arquivo oficial" quando não há arquivo. A
resposta adotada: **bronze guarda todas as páginas, cruas, na ordem em que
vieram** — `{"paginas": [<corpo1>, <corpo2>, ...]}`. Nada é fundido, nada é
descartado. Fundir os registros seria conveniente e já seria derivação, e o
invariante do bronze não admite derivação.

A paginação é declarada em `cfg_dataset.parametros`, não em código:

    {
      "paginacao": {"tamanho": 100, "caminho_total_paginas": "page.totalPages"},
      "codificacao": "base64_json",
      "modelo": {"language": "pt-br", "pageNumber": "{pagina}", "pageSize": 100},
      "caminho_registros": "results"
    }

`codificacao: base64_json` cobre o padrão — usado pela B3 e por outras APIs
públicas brasileiras — de mandar os parâmetros como JSON em base64 dentro do
caminho da URL, em vez de query string.
"""
from __future__ import annotations

import base64
import json
import logging
import time
from typing import Any, Callable

log = logging.getLogger("portal.paginacao")

LIMITE_PAGINAS = 500        # guarda contra API que sempre devolve "há mais"
PAUSA_ENTRE_PAGINAS = 0.2   # cortesia com a origem


class ErroPaginacao(RuntimeError):
    pass


def caminho(dado: Any, expressao: str) -> Any:
    """Lê `a.b.c` dentro de dicionários aninhados. `None` se faltar."""
    atual = dado
    for parte in expressao.split("."):
        if not isinstance(atual, dict) or parte not in atual:
            return None
        atual = atual[parte]
    return atual


def montar_url(template: str, parametros: dict, pagina: int,
               item: str | None = None) -> str:
    """Resolve o template para uma página específica.

    `{item}` é o valor da iteração corrente, quando o dataset declara
    `iteracao` — uma API que responde por companhia, por exemplo, recebe um
    código por vez ali. Fica no modelo como `{pagina}` fica: placeholder
    declarado, nunca nome de fonte no motor.
    """
    modelo = parametros.get("modelo")
    if modelo is None:
        return template.format(pagina=pagina)

    serializado = (
        json.dumps(modelo)
        .replace('"{pagina}"', str(pagina))
        .replace("{pagina}", str(pagina))
    )
    if item is not None:
        serializado = serializado.replace("{item}", str(item))
    concreto = json.loads(serializado)
    codificacao = parametros.get("codificacao", "base64_json")
    if codificacao == "base64_json":
        valor = base64.b64encode(
            json.dumps(concreto, separators=(",", ":")).encode()
        ).decode()
    elif codificacao == "json":
        valor = json.dumps(concreto, separators=(",", ":"))
    else:
        raise ErroPaginacao(f"codificação desconhecida: {codificacao}")
    return template.replace("{parametros}", valor)


def capturar(
    template: str, parametros: dict, baixar: Callable[[str], bytes],
    pausa: float = PAUSA_ENTRE_PAGINAS, limite: int = LIMITE_PAGINAS,
    itens: list[str] | None = None,
) -> bytes:
    """Percorre as páginas e devolve o corpo do bronze.

    Devolve `{"paginas": [...]}` serializado: tudo o que a fonte respondeu,
    na ordem, sem fusão.

    `itens` é a iteração declarada: uma fonte que responde por valor — uma
    companhia por chamada — recebe cada valor em `{item}` do modelo, e todas
    as respostas entram no mesmo bronze, na ordem dos itens. De onde os
    valores vêm é decisão de quem chama (a ingestão resolve o SQL declarado
    em `iteracao`); este módulo só percorre.
    """
    cfg = parametros.get("paginacao") or {}
    caminho_total = cfg.get("caminho_total_paginas")
    caminho_registros = parametros.get("caminho_registros")

    # Uma fonte sem lugar para o número da página entrega tudo numa resposta
    # só. Sem esta guarda, a URL invariável seria buscada de novo a cada volta
    # e o "para quando vier vazio" nunca dispararia: o bronze acabaria com 500
    # cópias da mesma resposta.
    pagina_unica = (
        not cfg
        and "{pagina}" not in template
        and "{pagina}" not in json.dumps(parametros.get("modelo") or {})
    )

    paginas: list[Any] = []
    for item in itens if itens is not None else [None]:
        total = None
        numero = 1
        while numero <= limite:
            corpo = json.loads(baixar(montar_url(template, parametros, numero, item)))
            paginas.append(corpo)

            if pagina_unica:
                break

            if total is None and caminho_total:
                total = caminho(corpo, caminho_total)
                if total is None:
                    raise ErroPaginacao(
                        f"a resposta não traz '{caminho_total}'; sem isso não há "
                        f"como saber quantas páginas existem"
                    )
                log.info("fonte paginada: %s páginas a buscar", total)

            if total is not None and numero >= int(total):
                break
            if total is None:
                # Sem contagem declarada, para quando a página vier vazia.
                registros = caminho(corpo, caminho_registros) if caminho_registros else corpo
                if not registros:
                    break
            numero += 1
            if pausa:
                time.sleep(pausa)
        else:
            raise ErroPaginacao(
                f"parei em {limite} páginas sem a fonte indicar o fim"
            )
        if pausa and itens is not None:
            time.sleep(pausa)

    return json.dumps({"paginas": paginas}, ensure_ascii=False).encode()


def registros_do_bronze(
    payload: bytes, caminho_registros: str | None,
    herdar: dict[str, str] | None = None,
) -> list[dict]:
    """Extrai os registros das páginas guardadas. É derivação, e por isso
    acontece na leitura, nunca na captura.

    Uma página que seja uma *string* JSON é desencapsulada aqui: há API que
    responde o corpo duplamente codificado — JSON dentro de string JSON — e
    o bronze guarda o que veio; decidir o que aquilo significa é leitura.

    `herdar` copia campos do objeto-pai para cada registro extraído. Existe
    para resposta aninhada — um objeto por companhia com a lista de eventos
    dentro — onde a identidade (o código da companhia) está no pai e o
    registro é o filho. Declarado como `{destino_no_registro: campo_do_pai}`;
    o motor não sabe o que os campos significam.
    """
    corpo = json.loads(payload)
    paginas = corpo.get("paginas", []) if isinstance(corpo, dict) else corpo
    saida: list[dict] = []
    for pagina in paginas:
        if isinstance(pagina, str):
            try:
                pagina = json.loads(pagina)
            except ValueError:
                continue
        pais = pagina if isinstance(pagina, list) else [pagina]
        for pai in pais:
            if not isinstance(pai, dict):
                continue
            trecho = caminho(pai, caminho_registros) if caminho_registros else pai
            if isinstance(trecho, dict):
                trecho = [trecho]
            if not isinstance(trecho, list):
                continue
            for registro in trecho:
                if not isinstance(registro, dict):
                    continue
                if herdar:
                    registro = {
                        **registro,
                        **{destino: pai.get(origem) for destino, origem in herdar.items()},
                    }
                saida.append(registro)
    return saida
