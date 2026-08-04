"""Credencial de fonte: declarada na configuração, guardada no ambiente.

`cfg_fonte.credencial_ref` existia como coluna desde a etapa 1 e nada a lia —
o transporte mandava só `User-Agent`. Na prática isso significava que o motor
não conseguia consumir nenhuma API que exigisse autenticação, e a primeira que
apareceu (brapi) expôs a falta.

**O que a configuração guarda é a referência, nunca o segredo.** O valor mora
numa variável de ambiente; o banco guarda o nome dela. Três razões: o banco é
copiado, exportado e restaurado com frequência e não deve levar token junto; um
segredo em `cfg_*` entraria no versionamento append-only e ficaria lá para
sempre; e trocar um token vazado passa a ser mudar uma variável, não editar
linha de configuração histórica.

Sintaxe de `credencial_ref`, escolhida para caber numa coluna de texto que já
existe em vez de exigir migração:

    BRAPI_TOKEN                  → Authorization: Bearer <valor>
    bearer:BRAPI_TOKEN           → idem, explícito
    header:X-API-Key:MINHA_VAR   → X-API-Key: <valor>
    query:token:MINHA_VAR        → acrescenta ?token=<valor> à URL

O modo `query` existe porque algumas APIs públicas só aceitam assim, e está
documentado como último recurso: segredo em query string vaza para log de
servidor, histórico de proxy e Referer. Onde a fonte aceitar cabeçalho, use
cabeçalho.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

MODOS = ("bearer", "header", "query")


class ErroCredencial(RuntimeError):
    """A fonte declara credencial e o ambiente não a tem."""


@dataclass(frozen=True)
class Credencial:
    modo: str
    nome: str        # nome do cabeçalho ou do parâmetro; vazio para bearer
    variavel: str    # a variável de ambiente que guarda o valor


def declarada(credencial_ref: str | None) -> Credencial | None:
    """Interpreta `credencial_ref`. `None` quando a fonte é aberta."""
    bruto = (credencial_ref or "").strip()
    if not bruto:
        return None

    partes = bruto.split(":")
    if len(partes) == 1:
        return Credencial("bearer", "", partes[0])
    modo = partes[0].lower()
    if modo == "bearer" and len(partes) == 2:
        return Credencial("bearer", "", partes[1])
    if modo in ("header", "query") and len(partes) == 3:
        return Credencial(modo, partes[1], partes[2])
    raise ErroCredencial(
        f"credencial_ref '{bruto}' não é reconhecida. Use VARIAVEL, "
        f"bearer:VARIAVEL, header:Nome:VARIAVEL ou query:nome:VARIAVEL."
    )


def presente(credencial_ref: str | None) -> bool:
    """A variável declarada existe no ambiente? Não devolve o valor."""
    cred = declarada(credencial_ref)
    return cred is None or bool(os.getenv(cred.variavel))


def aplicar(credencial_ref: str | None, url: str) -> tuple[str, dict[str, str]]:
    """Devolve a URL e os cabeçalhos já com a credencial.

    Levanta `ErroCredencial` nomeando a variável que falta — uma carga que
    falha por token ausente precisa dizer *qual* token, senão o operador vai
    procurar no lugar errado.
    """
    cred = declarada(credencial_ref)
    if cred is None:
        return url, {}

    valor = os.getenv(cred.variavel)
    if not valor:
        raise ErroCredencial(
            f"a fonte declara a credencial '{cred.variavel}' e essa variável "
            f"de ambiente não está definida. Defina-a e rode de novo; o valor "
            f"não é guardado no banco."
        )

    if cred.modo == "bearer":
        return url, {"Authorization": f"Bearer {valor}"}
    if cred.modo == "header":
        return url, {cred.nome: valor}
    separador = "&" if "?" in url else "?"
    return f"{url}{separador}{cred.nome}={valor}", {}


def censurar(url: str, credencial_ref: str | None) -> str:
    """A URL como ela pode ser registrada em log e gravada em bronze.

    No modo `query` o segredo está no endereço, e o endereço vai para
    `bronze_captura.url` e para o log de execução — os dois lugares que alguém
    lê depois. Sai substituído.
    """
    cred = declarada(credencial_ref)
    if cred is None or cred.modo != "query":
        return url
    valor = os.getenv(cred.variavel)
    return url.replace(valor, "***") if valor else url
