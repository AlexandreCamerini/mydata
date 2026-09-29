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


def _limites_da_carga(
    sink: Sink, tabela: str, coluna: str, capturas: list[int]
) -> tuple:
    """(menor valor de `coluna` nesta carga, maior valor no que já existia)."""
    marcadores = ",".join("?" for _ in capturas)
    carga = sink.um(
        f"SELECT min({coluna}) AS limite FROM {tabela} "
        f"WHERE captura_id IN ({marcadores})", list(capturas),
    )
    existente = sink.um(
        f"SELECT max({coluna}) AS limite FROM {tabela} "
        f"WHERE captura_id NOT IN ({marcadores})", list(capturas),
    )
    return (carga["limite"] if carga else None,
            existente["limite"] if existente else None)


def _carga_no_fim(
    sink: Sink, tabela: str, ordena: list[str], capturas: list[int],
    limites: tuple | None = None,
) -> bool:
    """Esta carga entra depois de tudo o que já existe na tabela?

    É a condição que autoriza escopar a escrita de um campo que não retroage.
    A moldura olha para trás: escrever só as linhas da carga é correto quando
    nenhuma linha anterior passa a ter um vizinho novo à frente.

    Carregar histórico viola isso — e é justamente o que fazer histórico
    significa. Ao ingerir 03/08 depois de 04/08, a linha de 04/08 ganha um
    antecessor e o retorno dela deixa de ser nulo; sem reescrevê-la, ela fica
    nula para sempre, com a plausibilidade de quem é o primeiro pregão da
    série. Nesse caso a escrita volta a ser da tabela inteira.

    Sem coluna de ordenação declarada não há "depois", e o recorte não se
    justifica.
    """
    if not ordena:
        return False
    carga, existente = limites or _limites_da_carga(
        sink, tabela, ordena[0], capturas
    )
    if carga is None:
        return False
    if existente is None:
        return True      # tabela só tem esta carga
    return carga >= existente


# --------------------------------------------------------------------------
# Leitura escopada do campo de janela
# --------------------------------------------------------------------------
# Agregados cujo alcance é o da moldura. `lag` ignora a moldura e tem alcance
# próprio (o deslocamento). Qualquer outra função — `lead`, `row_number`,
# `rank`, `ntile`… — olha para a frente ou para a partição inteira, e aí não
# existe "N linhas para trás" que baste: o campo fica no caminho integral.
AGREGADOS_DE_MOLDURA = frozenset({
    "count", "sum", "avg", "min", "max", "stddev", "stddev_samp",
    "stddev_pop", "variance", "var_samp", "var_pop", "first_value",
    "last_value", "bool_and", "bool_or",
})
MOLDURA_PARA_TRAS = re.compile(
    r"ROWS\s+BETWEEN\s+(\d+)\s+PRECEDING\s+AND\s+(?:CURRENT\s+ROW|\d+\s+PRECEDING)",
    re.IGNORECASE,
)
IDENTIFICADOR = re.compile(r"^[A-Za-z_]\w*$")


def _argumentos(texto: str) -> list[str]:
    """Separa argumentos por vírgula de nível zero."""
    partes, nivel, atual = [], 0, ""
    for ch in texto:
        if ch == "(":
            nivel += 1
        elif ch == ")":
            nivel -= 1
        if ch == "," and nivel == 0:
            partes.append(atual.strip())
            atual = ""
        else:
            atual += ch
    if atual.strip():
        partes.append(atual.strip())
    return partes


def alcance_para_tras(expressao: str, moldura: str | None) -> int | None:
    """Quantas linhas anteriores da partição o valor de uma linha precisa ver.

    Derivado da configuração do campo, nunca fixado à mão: `lag(x)` pede 1,
    `lag(x, 3)` pede 3, `stddev_samp(x) {OVER}` com `ROWS BETWEEN 62
    PRECEDING AND CURRENT ROW` pede 62. O campo pede o maior entre as
    chamadas que faz.

    `None` é "não sei dizer" — e não saber é motivo para ler a tabela
    inteira, não para chutar. Cai em `None`: moldura ausente num agregado
    (acumula desde o começo da partição), moldura `RANGE` (alcance em valor,
    não em linhas), `FOLLOWING` (olha para a frente), função fora das duas
    listas acima, deslocamento que não é inteiro literal, subconsulta na
    expressão, `OVER` escrito à mão, `IGNORE NULLS`, aspas ou `$$`, ou
    `{OVER}` que não segue uma chamada reconhecível.
    """
    if not expressao or "{OVER}" not in expressao:
        return None
    # Só se enxerga o que passa por `{OVER}`: um `OVER (...)` escrito à mão
    # teria alcance desconhecido. Aspas e `$$` escondem parênteses do
    # casamento abaixo; `IGNORE NULLS` faz o `lag` saltar linhas nulas e ir
    # arbitrariamente para trás.
    if re.search(r"\bselect\b|\bover\b|\bignore\s+nulls\b|\brespect\s+nulls\b"
                 r"|['\"$]", expressao.replace("{OVER}", ""), re.IGNORECASE):
        return None
    alcance = 0
    pos = expressao.find("{OVER}")
    while pos != -1:
        antes = expressao[:pos].rstrip()
        if not antes.endswith(")"):
            return None
        nivel, i = 0, len(antes) - 1
        while i >= 0:
            if antes[i] == ")":
                nivel += 1
            elif antes[i] == "(":
                nivel -= 1
                if nivel == 0:
                    break
            i -= 1
        if i < 0:
            return None
        nome = re.search(r"(\w+)\s*$", antes[:i])
        if not nome:
            return None
        funcao = nome.group(1).lower()
        args = _argumentos(antes[i + 1:-1])
        if funcao == "lag":
            if len(args) == 1:
                alcance = max(alcance, 1)
            elif len(args) >= 2 and re.fullmatch(r"\d+", args[1]):
                alcance = max(alcance, int(args[1]))
            else:
                return None
        elif funcao in AGREGADOS_DE_MOLDURA:
            m = MOLDURA_PARA_TRAS.fullmatch((moldura or "").strip())
            if not m:
                return None
            alcance = max(alcance, int(m.group(1)))
        else:
            return None
        pos = expressao.find("{OVER}", pos + len("{OVER}"))
    return alcance


def leitura_escopada(
    sink: Sink, tabela: str, particao: list[str], coluna: str,
    capturas: list[int], alcance: int, inicio_carga,
) -> tuple[str, list] | None:
    """O recorte de `tabela` que basta para recalcular as linhas desta carga.

    Só vale quando a carga está no fim (`_carga_no_fim`) e o campo não
    retroage: aí toda linha escrita é da carga, e cada uma precisa, da
    própria partição, das `alcance` linhas imediatamente anteriores — mais
    nada. Duas reduções, as duas exatas:

    1. Partição: só as que aparecem na carga. Ticker que não negociou hoje
       não é lido.
    2. Tempo: `corte` é o `alcance`-ésimo valor distinto de `coluna` antes do
       início da carga — "N pregões atrás". Partição que tem pelo menos
       `alcance` linhas em [corte, início da carga) tem as anteriores de que
       precisa dentro do recorte: tudo o que ficou de fora é estritamente
       anterior a elas, então a vizinhança de cada linha na moldura é a
       mesma da tabela inteira. Partição que não tem — papel ilíquido, que
       pulou pregões — é lida inteira (segundo ramo do `UNION ALL`). Com
       menos de `alcance` valores distintos na tabela, não há corte: lê-se a
       história inteira das partições da carga.

    Os dois ramos filtram por comparação simples (`coluna >= corte`,
    `particao = valor`), que o banco resolve pelos índices da classe — a
    identidade começa pela data. A igualdade é a mesma do `PARTITION BY`
    (sem passar por texto: `-0.0`/`0.0`, `1.0`/`1.00` continuam iguais),
    e é por isso que partição nula na carga desliga o recorte — `=` não
    casaria nulo com nulo.

    Devolve (fonte, parâmetros) para usar no lugar de `tabela` no FROM, com o
    próprio nome da tabela como apelido — a expressão continua resolvendo as
    colunas do mesmo jeito. `None` quando o recorte não se justifica: nulo na
    coluna de ordenação ou na partição da carga, ou nome que não é
    identificador simples.
    """
    if not IDENTIFICADOR.match(coluna) or not all(
            IDENTIFICADOR.match(p) for p in particao):
        return None
    # Nulo na ordenação vai para o fim da partição, depois da carga — o
    # "tudo o que ficou de fora é anterior" deixaria de valer.
    if sink.um(f"SELECT 1 AS n FROM {tabela} WHERE {coluna} IS NULL LIMIT 1"):
        return None

    marcadores = ",".join("?" for _ in capturas)
    colunas_particao = ", ".join(particao)
    da_carga = f"{coluna} >= ? AND captura_id IN ({marcadores})"
    p_carga: list = [inicio_carga, *capturas]
    nulos = " OR ".join(f"{p} IS NULL" for p in particao)
    if sink.um(f"SELECT 1 AS n FROM {tabela} WHERE {da_carga} AND ({nulos}) "
               f"LIMIT 1", p_carga):
        return None

    afetadas = f"SELECT DISTINCT {colunas_particao} FROM {tabela} WHERE {da_carga}"

    def junto(apelido: str) -> str:
        return " AND ".join(f"hist.{p} = {apelido}.{p}" for p in particao)

    if alcance == 0:
        corte = inicio_carga
    else:
        linha = sink.um(
            f"SELECT DISTINCT {coluna} AS limite FROM {tabela} "
            f"WHERE {coluna} < ? ORDER BY limite DESC "
            f"LIMIT 1 OFFSET {int(alcance) - 1}",
            [inicio_carga],
        )
        corte = linha["limite"] if linha else None

    fonte = (f"SELECT hist.* FROM {tabela} AS hist "
             f"JOIN ({afetadas}) AS afetada ON {junto('afetada')}")
    parametros: list = [*p_carga]
    if corte is not None:
        fonte += f" WHERE hist.{coluna} >= ?"
        parametros.append(corte)
    if corte is not None and alcance > 0:
        descobertas = (
            f"{afetadas} EXCEPT "
            f"SELECT {colunas_particao} FROM {tabela} "
            f"WHERE {coluna} >= ? AND {coluna} < ? GROUP BY {colunas_particao} "
            f"HAVING count(*) >= {int(alcance)}"
        )
        fonte += (
            f" UNION ALL SELECT hist.* FROM {tabela} AS hist "
            f"JOIN ({descobertas}) AS descoberta ON {junto('descoberta')} "
            f"WHERE hist.{coluna} < ?"
        )
        parametros += [*p_carga, corte, inicio_carga, corte]
    return f"({fonte}) AS {tabela}", parametros


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

    A exceção é o campo de janela que não retroage numa carga que entra no
    fim da série: aí só as linhas da carga são escritas, e a leitura se
    restringe às partições da carga e ao histórico que a moldura alcança
    (`leitura_escopada`). Com retroação, carga fora de ordem ou alcance que
    não se deriva da configuração, lê a tabela inteira, como sempre.
    """
    tabela = ds["tabela_destino"]
    aplicados: list[str] = []
    numericos: list[dict] = []
    filtro, parametros = _recorte(capturas)
    # Os limites da carga não mudam de um campo para o outro — o cálculo não
    # mexe em `captura_id` nem na coluna de ordenação —, e cada consulta é
    # uma varredura da tabela: uma vez por coluna basta.
    limites: dict[str, tuple] = {}

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
            # A subconsulta não pode ler só o que esta carga trouxe: a
            # partição cruza janelas de carga, e a volatilidade de 21 pregões
            # passaria a olhar só a carga. No caminho integral ela lê a
            # tabela inteira. No escopado (abaixo) lê as partições da carga e
            # só o histórico que a maior janela do campo alcança — ver
            # `leitura_escopada`.
            #
            # A escrita é outra pergunta: a linha nova muda o valor das que já
            # estavam gravadas? Quem retroage reescreve tudo, porque é
            # exatamente a linha *antiga* que precisa mudar — é o caso da
            # reapresentação rebaixando `is_latest`. Quem não retroage só
            # reescreve o que esta carga trouxe, e aí o custo do UPDATE para
            # de crescer com o histórico.
            #
            # A igualdade precisa ser null-safe — chave natural pode ter
            # coluna nula (`prazo_termo` fora de termo) — mas `a = b OR (a IS
            # NULL AND b IS NULL)` não é sargável: Postgres não decompõe OR
            # dentro de AND em condição de hash/merge join, e cai em nested
            # loop reavaliando a condição linha a linha do lado de fora contra
            # o lado de dentro inteiro. Sobre `fato_negociacao` (734 mil
            # linhas) isso mediu Nested Loop de custo ~627M e foi a causa
            # raiz de uma execução de 22h36min em produção — 9 linhas/s
            # efetivas escondendo um produto cartesiano parcial, não volume.
            # `IS NOT DISTINCT FROM` é null-safe e mais direto, mas não muda
            # o plano: testado localmente (Postgres 16), o planner também não
            # o decompõe em hash/merge join aqui, e o custo estimado piora
            # (~260M). `COALESCE(col, sentinela) = COALESCE(col, sentinela)`
            # é uma igualdade comum — hashable e mergeable — que preserva a
            # semântica null-safe sem depender de suporte especial do
            # planner: testado no mesmo cenário, vira Merge Join de custo
            # ~372K, ~1.700x mais barato. `chr(1)` é o sentinela: caractere
            # de controle que não ocorre em código de negociação, data ISO
            # ou nenhuma outra coluna de chave natural do catálogo — nenhuma
            # é do tipo `numero`, então o cast para texto é exato (inteiro,
            # texto, data-como-texto e booleano têm representação textual
            # unívoca; ponto flutuante não, e por isso não entra em chave).
            condicao = [
                f"COALESCE(alvo.{c}::text, chr(1)) = "
                f"COALESCE(origem.{c}::text, chr(1))"
                for c in chaves
            ]
            parametros_janela: list = []
            leitura, parametros_leitura = tabela, []
            caminho = "integral"
            if not campo.get("retroage", True) and capturas and ordena:
                if ordena[0] not in limites:
                    limites[ordena[0]] = _limites_da_carga(
                        sink, tabela, ordena[0], capturas
                    )
                if _carga_no_fim(sink, tabela, ordena, capturas,
                                 limites[ordena[0]]):
                    inicio_carga = limites[ordena[0]][0]
                    alcance = alcance_para_tras(campo["expressao"], moldura)
                    escopo = None
                    if alcance is not None:
                        escopo = leitura_escopada(
                            sink, tabela, particao, ordena[0], capturas,
                            alcance, inicio_carga,
                        )
                    if escopo is not None:
                        leitura, parametros_leitura = escopo
                        caminho = f"escopado, alcance {alcance}"
                        # Redundante para o resultado — toda linha da carga
                        # está a partir de `inicio_carga` —, mas deixa o
                        # banco achar o alvo pelo índice da identidade, que
                        # começa pela data, em vez de varrer a tabela atrás
                        # de `captura_id`, que não tem índice.
                        condicao.append(f"alvo.{ordena[0]} >= ?")
                        parametros_janela.append(inicio_carga)
                    else:
                        caminho = "leitura integral, escrita recortada"
                    marcadores = ",".join("?" for _ in capturas)
                    condicao.append(f"alvo.captura_id IN ({marcadores})")
                    parametros_janela += list(capturas)
            sink.executar(
                f"""UPDATE {tabela} AS alvo
                    SET {campo['nome']} = origem.valor_calculado
                    FROM (
                      SELECT {', '.join(chaves)}, {expressao} AS valor_calculado
                      FROM {leitura}
                    ) AS origem
                    WHERE """ + " AND ".join(condicao),
                parametros_leitura + parametros_janela,
            )
            log.info("campo calculado aplicado: %s (janela, %s)",
                     campo["nome"], caminho)
            aplicados.append(campo["nome"])
            continue
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
