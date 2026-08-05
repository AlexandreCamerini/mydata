"""Aplicação dos campos calculados declarados no catálogo.

Três classes, com consequências operacionais diferentes:

- `escalar`: expressão linha a linha. `UPDATE ... SET campo = <expr>`.
- `janela`: precisa de partição. `is_latest` é o caso canônico — a partição é
  global por (cd_cvm, tipo_doc, dt_refer) e **cruza janelas de carga**, então
  recomputar só o ano ingerido deixaria o flag errado em anos vizinhos quando
  chega uma reapresentação. Por isso campo de janela é sempre recomputado
  sobre a tabela inteira. `moldura` é o frame: sem ele, uma função de janela
  com ORDER BY acumula desde o começo da partição.
- `numerico`: o que SQL não exprime. Volatilidade implícita é a inversão de
  Black-Scholes — método iterativo, sem forma fechada. A expressão aqui é
  `funcao(coluna, coluna, ...)`, e `funcao` é resolvida contra o registro de
  `nucleos.py`. Nome fora do registro é erro de configuração.

Em nenhuma das três o motor avalia texto livre. Na primeira e na segunda a
expressão é SQL restrito, validada antes de rodar: sem DDL, sem ponto e
vírgula, sem comentário. Na terceira nem SQL há — só um nome de função e uma
lista de colunas. O campo é editável pela interface, então executar texto
livre seria RCE com formulário.
"""
from __future__ import annotations

import logging
import re

from ..repositorio import ErroConfiguracao
from ..sinks import Sink, sql_criar_staging
from .nucleos import NUCLEOS

# Staging própria do cálculo: a da carga (`_stg_carga`) pode estar viva na
# mesma transação, e as duas têm colunas diferentes.
STAGING = "_stg_calculo"

log = logging.getLogger("portal.calculados")

# `bs_iv(preco, spot, strike)` — nome, e argumentos que são coluna ou número.
CHAMADA = re.compile(r"^\s*(?P<funcao>\w+)\s*\((?P<args>[^()]*)\)\s*$")
ARGUMENTO = re.compile(r"^(?:[A-Za-z_]\w*|-?\d+(?:\.\d+)?|'[^']*')$")
# Quantas linhas carregar por vez ao avaliar campo numérico. O pregão inteiro
# são ~14 mil linhas; o limite existe para o histórico de anos não subir de
# uma vez à memória do container.
LOTE = 20_000

PROIBIDO = re.compile(
    r"\b(drop|delete|insert|update|alter|create|grant|revoke|attach|copy|"
    r"pg_read_file|pg_sleep|system|load|install)\b|;|--|/\*",
    re.IGNORECASE,
)


def validar_expressao(expressao: str, nome: str) -> None:
    if PROIBIDO.search(expressao):
        raise ErroConfiguracao(
            f"expressão do campo '{nome}' contém construção não permitida. "
            f"Use apenas expressão de leitura: operadores, CASE, funções "
            f"escalares e de janela."
        )


def _lista(valor: str | None) -> list[str]:
    return [p.strip() for p in (valor or "").split(",") if p.strip()]


def compilar_chamada(expressao: str, nome: str) -> tuple[str, list[str]]:
    """Valida `funcao(arg, arg)` e devolve o nome da função e os argumentos.

    Não é um avaliador: só reconhece a forma. Argumento é identificador de
    coluna, número ou texto entre aspas — nada que possa virar chamada
    aninhada, atributo ou índice.
    """
    m = CHAMADA.match(expressao or "")
    if not m:
        raise ErroConfiguracao(
            f"campo numérico '{nome}' precisa da forma funcao(coluna, ...); "
            f"recebeu {expressao!r}"
        )
    funcao = m.group("funcao")
    if funcao not in NUCLEOS:
        raise ErroConfiguracao(
            f"campo '{nome}' chama função numérica desconhecida '{funcao}'. "
            f"Disponíveis: {', '.join(sorted(NUCLEOS))}"
        )
    argumentos = [a.strip() for a in m.group("args").split(",") if a.strip()]
    invalidos = [a for a in argumentos if not ARGUMENTO.match(a)]
    if invalidos:
        raise ErroConfiguracao(
            f"campo '{nome}' passa argumento que não é coluna, número ou "
            f"texto literal: {', '.join(invalidos)}"
        )
    return funcao, argumentos


def _resolver(argumento: str, linha: dict):
    if argumento.startswith("'"):
        return argumento[1:-1]
    try:
        return float(argumento)
    except ValueError:
        return linha.get(argumento)


def _recorte(capturas: list[int] | None) -> tuple[str, list[int]]:
    """Filtro pelas capturas desta execução, para os campos que são da linha.

    Campo escalar e campo numérico só olham a própria linha, então recomputar
    a tabela inteira a cada carga é trabalho jogado fora — e cresce com o
    histórico: um pregão são catorze mil linhas, um ano são três milhões e
    meio, e a inversão de Black-Scholes não é barata. Campo de janela fica
    de fora deste recorte de propósito: a partição dele cruza janelas.
    """
    if not capturas:
        return "", []
    marcadores = ",".join("?" for _ in capturas)
    return f" WHERE captura_id IN ({marcadores})", list(capturas)


def _aplicar_numericos(
    sink: Sink, ds: dict, campos: list[dict], capturas: list[int] | None = None
) -> list[str]:
    """Avalia todos os campos numéricos numa passada e grava juntos.

    Um UPDATE por campo custaria uma varredura por grega — seis, para o mesmo
    conjunto de linhas, recalculando `d1` toda vez. Uma passada só resolve o
    dataset inteiro e escreve uma linha por vez com todas as colunas.
    """
    tabela = ds["tabela_destino"]
    chaves = _lista(ds["chave_natural"])
    if not chaves:
        raise ErroConfiguracao(
            f"dataset '{ds['chave']}' sem chave natural: campo numérico não "
            f"tem como voltar para a linha certa"
        )

    compilados = [(c["nome"], *compilar_chamada(c["expressao"], c["nome"]))
                  for c in campos]
    necessarias = {
        a for _, _, args in compilados for a in args
        if ARGUMENTO.match(a) and not a[0].isdigit() and not a.startswith(("'", "-"))
    }
    colunas = sorted(set(chaves) | necessarias)

    nomes = [nome for nome, _, _ in compilados]
    # Um UPDATE por linha custava vinte segundos por pregão — quase tudo em
    # ida e volta ao banco, não na matemática. O resultado vai para uma
    # staging temporária em carga em bloco, e volta numa junção só.
    escrita = [*chaves, *nomes]
    sink.executar(f"DROP TABLE IF EXISTS {STAGING}")
    sink.executar(sql_criar_staging(tabela, escrita, STAGING))
    inserir = (f"INSERT INTO {STAGING} ({', '.join(escrita)}) "
               f"VALUES ({', '.join('?' for _ in escrita)})")

    filtro, parametros = _recorte(capturas)
    deslocamento = 0
    while True:
        linhas = sink.consultar(
            f"SELECT {', '.join(colunas)} FROM {tabela}{filtro} "
            f"ORDER BY {', '.join(chaves)} LIMIT {LOTE} OFFSET {deslocamento}",
            parametros,
        )
        if not linhas:
            break
        sink.executar_muitos(inserir, [
            [*[linha[c] for c in chaves],
             *[NUCLEOS[funcao](*[_resolver(a, linha) for a in args])
               for _, funcao, args in compilados]]
            for linha in linhas
        ])
        deslocamento += len(linhas)

    sink.executar(
        f"UPDATE {tabela} AS alvo SET "
        + ", ".join(f"{n} = origem.{n}" for n in nomes)
        + f" FROM {STAGING} AS origem WHERE "
        + " AND ".join(f"alvo.{c} = origem.{c}" for c in chaves)
    )
    sink.executar(f"DROP TABLE IF EXISTS {STAGING}")

    for nome in nomes:
        log.info("campo calculado aplicado: %s (numerico)", nome)
    return nomes


def aplicar(
    sink: Sink, ds: dict, campos: list[dict], capturas: list[int] | None = None
) -> list[str]:
    """Recomputa os campos calculados do dataset. Devolve os nomes aplicados.

    `capturas` recorta o que é da linha — escalar e numérico — ao que esta
    execução carregou. Campo de janela ignora o recorte: a partição dele
    cruza janelas de carga, e é por isso que `is_latest` funciona.
    """
    tabela = ds["tabela_destino"]
    aplicados: list[str] = []
    numericos: list[dict] = []
    filtro, parametros = _recorte(capturas)

    for campo in sorted(campos, key=lambda c: (c["ordem"], c["id"])):
        if campo["materializacao"] != "coluna":
            continue

        if campo["classe"] == "numerico":
            # Acumulados: dependem dos escalares e de janela que vêm antes,
            # então rodam depois de todos.
            numericos.append(campo)
            continue

        validar_expressao(campo["expressao"], campo["nome"])

        if campo["classe"] == "escalar":
            sink.executar(
                f"UPDATE {tabela} SET {campo['nome']} = {campo['expressao']}{filtro}",
                parametros,
            )
        else:
            particao = _lista(campo["particao_por"])
            if not particao:
                raise ErroConfiguracao(
                    f"campo de janela '{campo['nome']}' sem particao_por"
                )
            ordena = _lista(campo["ordena_por"])
            over = f"PARTITION BY {', '.join(particao)}"
            if ordena:
                over += f" ORDER BY {', '.join(ordena)}"
            moldura = (campo.get("moldura") or "").strip()
            if moldura:
                # Sem frame, ORDER BY implica acumular desde o início da
                # partição: uma volatilidade de 21 pregões viraria a
                # volatilidade desde a primeira captura. É restrito à forma
                # que o catálogo oferece — nada de SQL livre aqui dentro.
                if not re.fullmatch(
                    r"(ROWS|RANGE) BETWEEN \d+ PRECEDING AND "
                    r"(CURRENT ROW|\d+ (PRECEDING|FOLLOWING))",
                    moldura, re.IGNORECASE,
                ):
                    raise ErroConfiguracao(
                        f"moldura do campo '{campo['nome']}' fora do formato "
                        f"aceito: {moldura!r}"
                    )
                over += f" {moldura}"
            # A junção é pela chave natural, não pela partição: partição
            # identifica o grupo, não a linha. rowid/ctid não são portáteis.
            chaves = _lista(ds["chave_natural"])
            if not chaves:
                raise ErroConfiguracao(
                    f"dataset '{ds['chave']}' sem chave natural: campo de janela "
                    f"'{campo['nome']}' não tem como casar linha a linha"
                )
            expressao = campo["expressao"].replace("{OVER}", f"OVER ({over})")
            # A subconsulta lê a tabela inteira, sempre: a partição cruza
            # janelas de carga, e recortar a leitura daria janela truncada —
            # a volatilidade de 21 pregões passaria a olhar só o que esta
            # carga trouxe.
            #
            # A escrita é outra pergunta: a linha nova muda o valor das que já
            # estavam gravadas? Quem retroage reescreve tudo, porque é
            # exatamente a linha *antiga* que precisa mudar — é o caso da
            # reapresentação rebaixando `is_latest`. Quem não retroage só
            # reescreve o que esta carga trouxe, e aí o custo do UPDATE para
            # de crescer com o histórico.
            condicao = [
                f"(alvo.{c} = origem.{c} OR "
                f"(alvo.{c} IS NULL AND origem.{c} IS NULL))"
                for c in chaves
            ]
            parametros_janela: list = []
            if not campo.get("retroage", True) and capturas:
                marcadores = ",".join("?" for _ in capturas)
                condicao.append(f"alvo.captura_id IN ({marcadores})")
                parametros_janela = list(capturas)
            sink.executar(
                f"""UPDATE {tabela} AS alvo
                    SET {campo['nome']} = origem.valor_calculado
                    FROM (
                      SELECT {', '.join(chaves)}, {expressao} AS valor_calculado
                      FROM {tabela}
                    ) AS origem
                    WHERE """ + " AND ".join(condicao),
                parametros_janela,
            )
        aplicados.append(campo["nome"])
        log.info("campo calculado aplicado: %s (%s)", campo["nome"], campo["classe"])

    # Uma onda por valor de `ordem`. Campo numérico pode alimentar outro — a
    # volatilidade implícita é insumo das gregas —, e uma passada só leria da
    # linha o valor anterior. Dentro da onda nenhum lê o resultado do outro,
    # que é justamente o que a igualdade de `ordem` declara.
    for ordem in sorted({c["ordem"] for c in numericos}):
        aplicados += _aplicar_numericos(
            sink, ds, [c for c in numericos if c["ordem"] == ordem], capturas
        )
    return aplicados
