"""A tabela física como consequência da classe declarada.

Enquanto `CREATE TABLE fato_conta (...)` estiver escrito à mão numa migração,
cadastrar uma classe de informação nova pela interface exige deploy. Este
módulo tira o DDL do código e o deriva de `cfg_classe` / `cfg_atributo`.

Três colunas de sistema entram sempre, porque o resto do motor depende delas
e nenhuma é assunto de quem modela o domínio:

- `captura_id` e `fonte_arquivo` ligam a linha à captura em bronze que a
  produziu. É o que permite recomputar uma janela e descartar carga reprovada.
- `publicado_em_versao` é o rótulo do gate de qualidade: linha sem rótulo
  existe em silver e não aparece em gold.

`carregado_em` completa o conjunto para diagnóstico. Nenhuma delas é atributo
da classe — `empresa` não tem "id da captura" como característica.
"""
from __future__ import annotations

import hashlib
import json
import logging

from .. import repositorio as repo
from ..sinks import Sink, render

log = logging.getLogger("portal.ddl")

# Atributo declarado -> tipo do dialeto. `data` vira texto de propósito: o
# parsing devolve ISO como string para os dois sinks concordarem sobre o valor.
TIPO_DDL = {
    "texto": "{TEXTO}",
    "inteiro": "{INT}",
    "numero": "{NUM}",
    "data": "{TEXTO}",
    "booleano": "{BOOL}",
}

COLUNAS_DE_SISTEMA: list[tuple[str, str]] = [
    ("captura_id", "{INT} NOT NULL"),
    ("fonte_arquivo", "{TEXTO} NOT NULL"),
    # Qual mapeamento produziu esta linha. Entra na identidade física para
    # que duas fontes falando da mesma coisa coexistam: sem isso, a segunda
    # carga sobrescreveria a primeira e a divergência entre elas seria
    # apagada antes de alguém poder decidir qual vale.
    ("origem_dataset", "{TEXTO}"),
    ("carregado_em", "{TSTZ} NOT NULL DEFAULT {AGORA}"),
    ("publicado_em_versao", "{INT}"),
]

# Sufixo da coluna que diz qual fonte venceu um atributo disputado.
SUFIXO_ORIGEM = "_origem"


def colunas_da_classe(atributos: list[dict]) -> list[tuple[str, str]]:
    """(nome, tipo) de toda coluna que a classe implica, sistema incluído.

    Um atributo com `guarda_texto` ganha a coluna sombra `<nome>_txt`: é onde
    a representação original do arquivo fica intacta ao lado do valor
    convertido. Converter tipo é conversão de representação, não
    transformação de dado — a sombra é o que torna isso verificável.
    """
    colunas = list(COLUNAS_DE_SISTEMA)
    for a in sorted(atributos, key=lambda x: (x["ordem"], x["id"])):
        tipo = TIPO_DDL.get(a["tipo"])
        if tipo is None:
            raise repo.ErroConfiguracao(
                f"atributo '{a['nome']}' tem tipo sem correspondente físico: "
                f"{a['tipo']}"
            )
        colunas.append((a["nome"], tipo))
        if a["guarda_texto"]:
            colunas.append((f"{a['nome']}_txt", "{TEXTO}"))
    return colunas


def identidade_de(classe: dict) -> list[str]:
    """Os atributos que dizem quando duas linhas falam da mesma coisa."""
    return [c.strip() for c in classe["chave_identidade"].split(",") if c.strip()]


def identidade_fisica(classe: dict) -> list[str]:
    """A identidade mais a fonte: é a chave da tabela, não da informação.

    Duas fontes descrevendo a mesma empresa são duas linhas com a mesma
    identidade lógica e origens diferentes. Qual valor publicar é decidido
    depois, na vista resolvida.
    """
    return [*identidade_de(classe), "origem_dataset"]


def sentencas_da_classe(classe: dict, atributos: list[dict]) -> list[str]:
    """DDL completo da classe: tabela, unicidade da identidade e índices."""
    tabela = classe["tabela"]
    colunas = colunas_da_classe(atributos)
    corpo = ",\n  ".join(f"{nome} {tipo}" for nome, tipo in colunas)
    sentencas = [
        f"CREATE TABLE IF NOT EXISTS {tabela} (\n  {corpo}\n)",
        f"CREATE UNIQUE INDEX IF NOT EXISTS ux_{tabela}_identidade "
        f"ON {tabela} ({', '.join(identidade_fisica(classe))})",
        f"CREATE INDEX IF NOT EXISTS ix_{tabela}_publicado "
        f"ON {tabela} (publicado_em_versao)",
    ]
    for numero, grupo in enumerate(repo.indices_de(classe), start=1):
        sentencas.append(
            f"CREATE INDEX IF NOT EXISTS ix_{tabela}_{numero} "
            f"ON {tabela} ({', '.join(grupo)})"
        )
    return sentencas


def colunas_fisicas(sink: Sink, tabela: str) -> dict[str, str]:
    linhas = sink.consultar(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_name = ?",
        (tabela,),
    )
    return {linha["column_name"]: linha["data_type"].lower() for linha in linhas}


def indice_existe(sink: Sink, nome: str) -> bool:
    """Índice não aparece em `information_schema`, então cada dialeto tem o seu.

    Existe para a guarda de `garantir_tabela` afirmar o que ela diz afirmar:
    que a tabela está materializada, e não que a configuração dela não mudou.
    """
    if sink.dialeto == "postgres":
        sql = "SELECT 1 AS ok FROM pg_indexes WHERE indexname = ?"
    else:
        sql = "SELECT 1 AS ok FROM duckdb_indexes() WHERE index_name = ?"
    return sink.um(sql, (nome,)) is not None


def colunas_do_indice(sink: Sink, nome: str) -> list[str] | None:
    """Colunas do índice, na ordem, lidas do catálogo; `None` se não existe.

    Os dois dialetos guardam a definição como texto (`indexdef` no Postgres,
    `sql` no DuckDB), sempre terminando na lista de colunas entre parênteses.
    Os índices do motor só usam coluna simples, sem expressão, então a lista
    é separável por vírgula.
    """
    if sink.dialeto == "postgres":
        sql = "SELECT indexdef AS definicao FROM pg_indexes WHERE indexname = ?"
    else:
        sql = "SELECT sql AS definicao FROM duckdb_indexes() WHERE index_name = ?"
    linha = sink.um(sql, (nome,))
    if linha is None or not linha["definicao"]:
        return None
    definicao = linha["definicao"]
    dentro = definicao[definicao.rindex("(") + 1:definicao.rindex(")")]
    return [c.strip().strip('"') for c in dentro.split(",") if c.strip()]


def divergencias(sink: Sink, classe: dict, atributos: list[dict]) -> list[str]:
    """O que a classe declara e a tabela não tem, e vice-versa.

    Lista vazia significa que a configuração é espelho fiel do banco. É a
    verificação que autoriza a configuração a assumir o lugar do DDL escrito
    à mão: um gerador que não reproduz a tabela existente não está pronto
    para passar a ser dono dela.
    """
    fisicas = colunas_fisicas(sink, classe["tabela"])
    if not fisicas:
        return [f"tabela '{classe['tabela']}' não existe"]
    declaradas = {nome for nome, _ in colunas_da_classe(atributos)}
    faltando = sorted(declaradas - set(fisicas))
    sobrando = sorted(set(fisicas) - declaradas)
    problemas = [f"declarado e ausente na tabela: {c}" for c in faltando]
    problemas += [f"na tabela e não declarado: {c}" for c in sobrando]
    return problemas


def _digest(classe: dict, atributos: list[dict]) -> str:
    corpo = json.dumps(
        [colunas_da_classe(atributos), identidade_fisica(classe),
         repo.indices_de(classe)],
        sort_keys=True,
    )
    return hashlib.sha256(corpo.encode()).hexdigest()


def garantir_tabela(sink: Sink, classe: dict, atributos: list[dict]) -> list[str]:
    """Aplica o DDL da classe, evoluindo a tabela que já existe.

    Três casos, e o terceiro é o que faltava até aqui:

    - Tabela ausente: cria com tudo.
    - Atributo novo na classe: `ALTER TABLE ADD COLUMN`. Nunca o contrário —
      remover atributo da configuração não derruba coluna, porque isso
      apagaria dado. A coluna órfã aparece em `divergencias` para alguém
      decidir.
    - Identidade alterada: o índice único é refeito. `CREATE INDEX IF NOT
      EXISTS` manteria em silêncio o índice antigo, e a carga passaria a
      resolver conflito por um critério diferente do declarado.

    O digest em `cfg_seed` evita refazer índice a cada boot: numa tabela de
    centenas de milhares de linhas isso custaria segundos por deploy sem
    nenhuma mudança.
    """
    tabela = classe["tabela"]
    digest = _digest(classe, atributos)
    marcador = f"classe:{tabela}"
    ja = sink.um("SELECT sha256 FROM cfg_seed WHERE chave = ?", (marcador,))
    existentes = colunas_fisicas(sink, tabela)
    # O digest sozinho não basta como guarda: ele descreve a *configuração*,
    # e concluir dela que o schema físico está correto é uma inferência que
    # falha em silêncio. Foi o que aconteceu em produção — `fato_conta` ficou
    # sem o índice único da identidade, o `ON CONFLICT` da carga passou a
    # falhar toda noite, `is_latest` parou de ser recomputado, e gold ficou
    # servindo 5.048 linhas de 731.034. O digest, batendo, impedia o conserto
    # a cada boot.
    #
    # Conferir a existência do índice custa uma consulta ao catálogo; refazê-lo
    # à toa é que custaria segundos por deploy. A guarda continua barata e
    # passa a ser sobre o que ela afirma.
    if (
        ja and ja["sha256"] == digest and existentes
        and indice_existe(sink, f"ux_{tabela}_identidade")
    ):
        return []

    aplicadas: list[str] = []
    if not existentes:
        for sentenca in sentencas_da_classe(classe, atributos):
            sink.executar(render(sentenca, sink.dialeto))
            aplicadas.append(sentenca.split("\n")[0])
    else:
        for nome, tipo in colunas_da_classe(atributos):
            if nome in existentes:
                continue
            # Sem restrição no ALTER: o DuckDB não aceita, e uma coluna que
            # nasce em tabela cheia não tem como já ser NOT NULL.
            sink.executar(render(
                f"ALTER TABLE {tabela} ADD COLUMN {nome} {tipo.split(' ')[0]}",
                sink.dialeto,
            ))
            aplicadas.append(f"ALTER TABLE {tabela} ADD COLUMN {nome}")
            if nome == "origem_dataset":
                # A origem das linhas que já estavam lá é recuperável: a
                # captura em bronze sabe de qual dataset veio. Preencher com
                # um literal perderia essa informação para sempre.
                sink.executar(
                    f"UPDATE {tabela} SET origem_dataset = COALESCE("
                    f"  (SELECT b.dataset_chave FROM bronze_captura b"
                    f"   WHERE b.id = {tabela}.captura_id), '') "
                    f"WHERE origem_dataset IS NULL"
                )
                aplicadas.append(f"UPDATE {tabela} SET origem_dataset (do bronze)")
        # O índice único só é refeito quando a identidade mudou ou ele sumiu.
        # O digest muda também quando muda só um índice comum, e refazer o
        # único nesse caso é caro e arriscado: em `fato_negociacao`, com
        # 1,4 milhão de linhas, o DROP + CREATE roda no boot, sem
        # CONCURRENTLY, e entre os dois o `ON CONFLICT` da carga fica sem
        # apoio.
        indice = f"ux_{tabela}_identidade"
        if colunas_do_indice(sink, indice) != identidade_fisica(classe):
            sink.executar(f"DROP INDEX IF EXISTS {indice}")
            sink.executar(
                f"CREATE UNIQUE INDEX {indice} ON {tabela} "
                f"({', '.join(identidade_fisica(classe))})"
            )
            aplicadas.append(f"CREATE UNIQUE INDEX {indice}")
        for sentenca in sentencas_da_classe(classe, atributos)[2:]:
            nome = sentenca.split()[5]   # CREATE INDEX IF NOT EXISTS <nome> ON …
            if not indice_existe(sink, nome):
                aplicadas.append(f"CREATE INDEX {nome}")
            sink.executar(render(sentenca, sink.dialeto))

    sink.executar("DELETE FROM cfg_seed WHERE chave = ?", (marcador,))
    sink.executar(
        "INSERT INTO cfg_seed (chave, sha256) VALUES (?, ?)", (marcador, digest)
    )
    return aplicadas


# --------------------------------------------------------------------------
# Resolução multi-fonte
# --------------------------------------------------------------------------
def _lista(valor: str | None) -> list[str]:
    return [p.strip() for p in (valor or "").split(",") if p.strip()]


def datasets_por_atributo(sink: Sink, classe: dict) -> dict[str, list[str]]:
    """Quais mapeamentos alimentam cada atributo da classe.

    Um atributo alimentado por mais de um deles está em disputa — e é só
    para esses que a proveniência precisa descer ao nível do atributo.
    """
    mapa: dict[str, list[str]] = {}
    for ds in repo.datasets_da_classe(sink, classe["chave"]):
        nomes = [c["nome_destino"] for c in repo.colunas_do(sink, ds["id"])]
        nomes += [c["nome"] for c in repo.calculados_do(sink, ds["id"])]
        for nome in nomes:
            mapa.setdefault(nome, [])
            if ds["chave"] not in mapa[nome]:
                mapa[nome].append(ds["chave"])
    return mapa


def precedencia_do_atributo(
    classe: dict, atributo: dict, candidatos: list[str]
) -> list[str]:
    """A ordem em que as fontes são consultadas para este atributo.

    Precedência é declarada **por atributo**, não por fonte inteira: o
    cadastro da CVM é a melhor fonte para a razão social e não diz nada
    sobre o resto. Declarar "cadastro vence sempre" seria grosseiro demais
    para ser verdade.
    """
    for ordem in (_lista(atributo.get("precedencia")),
                  _lista(classe.get("precedencia"))):
        preferidos = [d for d in ordem if d in candidatos]
        if preferidos:
            return preferidos + [d for d in candidatos if d not in preferidos]
    return candidatos


def sql_vista_resolvida(
    sink: Sink, classe: dict, atributos: list[dict]
) -> str | None:
    """Uma linha por identidade, cada atributo vindo da fonte de maior
    precedência que o tenha preenchido.

    A tabela continua com uma linha por (identidade, fonte), intacta. Isto
    aqui é derivação: mudar precedência é republicar, não recarregar.
    """
    if classe.get("resolucao") != "precedencia":
        return None
    mapa = datasets_por_atributo(sink, classe)
    if not mapa:
        return None
    identidade = identidade_de(classe)
    ordem_classe = _lista(classe.get("precedencia")) or sorted(
        {d for ds in mapa.values() for d in ds}
    )

    def escolher(coluna: str, tipo: str, fonte: str) -> str:
        """Pega o valor desta fonte dentro do grupo da identidade.

        Há uma linha por (identidade, fonte), então qualquer agregado que
        ignore NULL devolve o valor daquela fonte. `MAX` seria o natural, mas
        o Postgres não o define para booleano — e a classe `empresa` tem
        `listada_b3`. `BOOL_OR` faz o mesmo papel nos dois dialetos.
        """
        agregado = "BOOL_OR" if tipo == "booleano" else "MAX"
        return f"{agregado}(CASE WHEN origem_dataset = '{fonte}' THEN {coluna} END)"

    def preferir(coluna: str, tipo: str, fontes: list[str]) -> str:
        partes = [escolher(coluna, tipo, f) for f in fontes]
        return partes[0] if len(partes) == 1 else f"COALESCE({', '.join(partes)})"

    campos = list(identidade)
    for a in sorted(atributos, key=lambda x: (x["ordem"], x["id"])):
        nome = a["nome"]
        if nome in identidade:
            continue
        fontes = precedencia_do_atributo(classe, a, mapa.get(nome, []))
        if not fontes:
            continue
        campos.append(f"{preferir(nome, a['tipo'], fontes)} AS {nome}")
        if len(fontes) > 1:
            # Só atributo disputado ganha coluna de origem: para os demais
            # ela seria uma constante repetida em toda linha.
            caso = " ".join(
                f"WHEN {escolher(nome, a['tipo'], f)} IS NOT NULL THEN '{f}'"
                for f in fontes
            )
            campos.append(f"CASE {caso} END AS {nome}{SUFIXO_ORIGEM}")
    campos.append(f"{preferir('captura_id', 'inteiro', ordem_classe)} AS captura_id")
    campos.append(
        f"{preferir('fonte_arquivo', 'texto', ordem_classe)} AS fonte_arquivo"
    )
    campos.append("max(publicado_em_versao) AS publicado_em_versao")

    return (
        "SELECT " + ",\n       ".join(campos) + f"\nFROM {classe['tabela']}\n"
        "WHERE publicado_em_versao IS NOT NULL AND publicado_em_versao <= {V}\n"
        f"GROUP BY {', '.join(identidade)}"
    )


def vistas_resolvidas(sink: Sink) -> dict[str, str]:
    """Vista de gold gerada para cada classe que resolve por precedência."""
    saida: dict[str, str] = {}
    for classe in repo.listar_classes(sink, so_ativas=True):
        if not colunas_fisicas(sink, classe["tabela"]):
            continue
        corpo = sql_vista_resolvida(
            sink, classe, repo.atributos_de(sink, classe["id"])
        )
        if corpo:
            saida[f"gold_{classe['chave']}"] = corpo
    return saida


def garantir_classes(sink: Sink) -> dict[str, list[str]]:
    """Materializa toda classe cadastrada. Chamado no boot e ao salvar classe."""
    saida: dict[str, list[str]] = {}
    for classe in repo.listar_classes(sink, so_ativas=True):
        atributos = repo.atributos_de(sink, classe["id"])
        if not atributos:
            continue
        saida[classe["chave"]] = garantir_tabela(sink, classe, atributos)
        log.info("classe materializada: %s -> %s", classe["chave"], classe["tabela"])
    return saida
