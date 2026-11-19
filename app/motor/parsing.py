"""Parse genérico dirigido por `cfg_coluna`.

Não há parser da CVM aqui — há um leitor de CSV que obedece à configuração.
O conhecimento específico da CVM (nome dos arquivos, grupos, escalas) vive em
linhas de configuração, não em código. É isso que permite cadastrar a segunda
fonte sem deploy.

Conversão de tipo é conversão de *representação*: `"1.234,50"` vira 1234.50 e
a string original continua disponível em `<coluna>_txt`.
"""
from __future__ import annotations

import csv
import io
import re
import zipfile
from datetime import date
from typing import Any, Iterator


class ErroParse(ValueError):
    """Arquivo não bate com o contrato declarado em cfg_coluna."""


def _num(txt: str, formato: str | None) -> float | None:
    txt = txt.strip()
    if not txt:
        return None
    if formato == "decimal_ptbr":
        txt = txt.replace(".", "").replace(",", ".") if "," in txt else txt
    casas = 0
    if formato and formato.startswith("implicito:"):
        # `implicito:2` — o arquivo grava 0000000000057 e quer dizer 0,57.
        # Layout posicional não tem onde pôr a vírgula, então a escala é
        # declarada. Dividir aqui, e não num campo calculado, mantém a
        # coluna com o número que o campo significa.
        casas = int(formato.split(":", 1)[1])
    try:
        valor = float(txt)
    except ValueError:
        return None
    return valor / (10 ** casas) if casas else valor


def _int(txt: str) -> int | None:
    txt = txt.strip()
    if not txt:
        return None
    try:
        return int(float(txt))
    except ValueError:
        return None


def _data(txt: str) -> str | None:
    """Devolve ISO como texto. Data vira texto para não divergir entre sinks."""
    txt = txt.strip()
    if not txt or txt.startswith("0000"):
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y%m%d"):
        try:
            from datetime import datetime

            return datetime.strptime(txt, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _bool(txt: str, formato: str | None = None) -> bool | None:
    t = txt.strip()
    if not t:
        return None
    if formato and formato.startswith("igual:"):
        # `igual:con` -> verdadeiro quando o valor é exatamente 'con'.
        return t.lower() == formato.split(":", 1)[1].strip().lower()
    return t.upper() in ("S", "SIM", "TRUE", "T", "1", "Y")


_MAPAS: dict[str, dict[str, str]] = {}


def _tabela_mapa(formato: str) -> dict[str, str]:
    """Interpreta `mapa:a=b;c=d` uma vez por formato distinto."""
    tabela = _MAPAS.get(formato)
    if tabela is None:
        tabela = {}
        for par in formato[len("mapa:"):].split(";"):
            if not par.strip():
                continue
            if "=" not in par:
                raise ErroParse(
                    f"formato 'mapa:' com par sem '=': {par!r}. "
                    f"Use mapa:codigo=nome;codigo=nome"
                )
            codigo, nome = par.split("=", 1)
            tabela[codigo.strip()] = nome.strip()
        _MAPAS[formato] = tabela
    return tabela


def converter(valor: str, tipo: str, formato: str | None) -> Any:
    if tipo == "inteiro":
        return _int(valor)
    if tipo == "numero":
        return _num(valor, formato)
    if tipo == "data":
        return _data(valor)
    if tipo == "booleano":
        return _bool(valor, formato)
    v = valor.strip()
    if formato and formato.startswith("mapa:"):
        # `mapa:7=OPTION ON EQUITIES;11=SHARES` — a fonte publica código onde
        # a classe guarda nome. A tabela de-para é dado da fonte, declarado no
        # mapeamento; código fora dela passa cru, para aparecer em vez de
        # virar nulo mudo. Destino vazio (`0=`) é nulo de propósito.
        tabela = _tabela_mapa(formato)
        if v in tabela:
            return tabela[v] or None
    if not v and formato and formato.startswith("vazio:"):
        # Arquivo posicional preenche com espaço o campo que não se aplica.
        # Quando esse campo está na identidade, o branco vira NULL e o
        # `ON CONFLICT` deixa de conflitar: cada recarga insere de novo, sem
        # erro e sem sintoma. Declarar o literal é o que fecha esse buraco.
        return formato.split(":", 1)[1]
    return v if v else None


def mapear(
    linhas: Iterator[dict[str, Any]],
    colunas: list[dict],
    cabecalho: set[str],
    contexto: dict[str, str] | None = None,
    extras: dict[str, Any] | None = None,
) -> Iterator[dict[str, Any]]:
    """Aplica `cfg_coluna` a registros já lidos, venham de onde vierem.

    Separado do leitor de CSV para que uma fonte JSON use exatamente o mesmo
    mapeamento — tipo, formato, coluna sombra `_txt` e pseudo-colunas `$grupo`.
    Se o mapeamento fosse reescrito por transporte, cada fonte nova traria de
    volta o parsing específico que o produto existe para eliminar.
    """
    contexto = {k.upper(): v for k, v in (contexto or {}).items()}
    do_arquivo = [c for c in colunas if c["nome_origem"].startswith("$")]
    do_registro = [c for c in colunas if not c["nome_origem"].startswith("$")]

    ausentes = [
        c["nome_origem"] for c in do_registro
        if c["obrigatoria"] and c["nome_origem"].strip().upper() not in cabecalho
    ]
    if ausentes:
        raise ErroParse(
            "a fonte não traz campo obrigatório declarado: " + ", ".join(ausentes)
        )
    sem_grupo = [
        c["nome_origem"] for c in do_arquivo
        if c["obrigatoria"] and c["nome_origem"][1:].upper() not in contexto
    ]
    if sem_grupo:
        raise ErroParse(
            "padrao_arquivo não captura grupo nomeado exigido: " + ", ".join(sem_grupo)
        )

    mapa = [
        (c["nome_origem"].strip().upper(), c["nome_destino"], c["tipo"], c["formato"])
        for c in do_registro
    ]
    fixos: dict[str, Any] = dict(extras or {})
    for c in do_arquivo:
        fixos[c["nome_destino"]] = converter(
            contexto.get(c["nome_origem"][1:].upper(), ""), c["tipo"], c["formato"]
        )
    guardar_txt = {
        c["nome_destino"] for c in do_registro if c["tipo"] in ("numero", "inteiro")
    }

    for linha in linhas:
        normalizada = {(k or "").strip().upper(): v for k, v in linha.items()}
        saida: dict[str, Any] = dict(fixos)
        for origem, destino, tipo, formato in mapa:
            bruto = normalizada.get(origem)
            bruto = "" if bruto is None else str(bruto)
            saida[destino] = converter(bruto, tipo, formato)
            if destino in guardar_txt:
                saida[f"{destino}_txt"] = bruto.strip() or None
        yield saida


def ler_json(
    raw: bytes,
    colunas: list[dict],
    caminho_registros: str | None = None,
    contexto: dict[str, str] | None = None,
    extras: dict[str, Any] | None = None,
    herdar: dict[str, str] | None = None,
) -> Iterator[dict[str, Any]]:
    """Lê registros de uma captura JSON paginada, com o mesmo mapeamento do CSV."""
    from .paginacao import registros_do_bronze

    registros = registros_do_bronze(raw, caminho_registros, herdar)
    cabecalho = {str(k).strip().upper() for r in registros[:50] for k in r}
    return mapear(iter(registros), colunas, cabecalho, contexto, extras)


def ler_csv(
    raw: bytes,
    colunas: list[dict],
    encoding: str,
    separador: str,
    contexto: dict[str, str] | None = None,
    extras: dict[str, Any] | None = None,
    preambulo: int = 0,
) -> Iterator[dict[str, Any]]:
    """Lê um CSV e devolve dicts já mapeados para os nomes de destino.

    `contexto` traz o que foi capturado do *nome do arquivo* pelos grupos
    nomeados de `padrao_arquivo`. Uma coluna cujo `nome_origem` começa com `$`
    é lida dali em vez do CSV — é assim que `tipo_doc`, `grupo` e `escopo`
    entram sem uma linha de código específica da CVM.

    `extras` são constantes do carregamento (id da captura, nome do arquivo).

    `preambulo` são linhas a descartar antes do cabeçalho. Existe porque há
    fonte que abre o arquivo com um aviso — "Status do Arquivo: Final" — e o
    cabeçalho real vem depois. Sem declarar isso, a primeira linha vira nome
    de coluna e o mapeamento inteiro deixa de casar, com erro que fala de
    coluna ausente e não de linha a mais.
    """
    texto = raw.decode(encoding, errors="strict")
    fluxo = io.StringIO(texto)
    for _ in range(max(0, preambulo)):
        if not fluxo.readline():
            break
    leitor = csv.DictReader(fluxo, delimiter=separador)
    cabecalho = {(c or "").strip().upper() for c in (leitor.fieldnames or [])}
    return mapear(iter(leitor), colunas, cabecalho, contexto, extras)


def previa_csv(
    raw: bytes, encoding: str, separador: str,
    preambulo: int = 0, limite: int = 5,
) -> dict[str, Any]:
    """Cabeçalho e as primeiras linhas, cru — sem mapeamento nenhum.

    `ler_csv` acima exige `colunas` porque já sabe para onde cada campo vai;
    aqui é o oposto, o passo que existe *antes* de qualquer campo estar
    ligado — o que o assistente de conexão nova mostra para o operador ligar
    contra o valor real, em vez de digitar contra um arquivo aberto em outra
    janela.
    """
    texto = raw.decode(encoding, errors="strict")
    fluxo = io.StringIO(texto)
    for _ in range(max(0, preambulo)):
        if not fluxo.readline():
            break
    leitor = csv.DictReader(fluxo, delimiter=separador)
    colunas = [c for c in (leitor.fieldnames or []) if c]
    amostra = []
    for linha in leitor:
        if len(amostra) >= limite:
            break
        amostra.append({k: v for k, v in linha.items() if k})
    return {"colunas": colunas, "amostra": amostra}


_FAIXA = re.compile(r"^(?P<campo>[^@]+)@(?P<ini>\d+)-(?P<fim>\d+)$")


def faixa_de(nome_origem: str) -> tuple[int, int] | None:
    """Interpreta `PREEXE@189-201` como a fatia 189..201, 1-indexada inclusive.

    A posição mora no `nome_origem` em vez de numa coluna nova de `cfg_coluna`
    pela mesma razão que `$grupo` mora ali: é a identificação do campo *na
    origem*. Num CSV a origem se identifica por nome, num layout posicional se
    identifica por posição, e nos dois casos é a mesma pergunta — de onde vem
    este valor.
    """
    m = _FAIXA.match(nome_origem.strip())
    if not m:
        return None
    ini, fim = int(m.group("ini")), int(m.group("fim"))
    if ini < 1 or fim < ini:
        raise ErroParse(
            f"faixa inválida em '{nome_origem}': posição inicial {ini}, final {fim}"
        )
    return ini, fim


def ler_larguras(
    raw: bytes,
    colunas: list[dict],
    encoding: str,
    filtro_linha: str | None = None,
    contexto: dict[str, str] | None = None,
    extras: dict[str, Any] | None = None,
) -> Iterator[dict[str, Any]]:
    """Lê um arquivo de registro posicional, com o mesmo mapeamento do CSV.

    Cada coluna declara a faixa em `nome_origem` (`CAMPO@ini-fim`). O leitor
    recorta e entrega o registro com a chave igual ao `nome_origem` declarado,
    então `mapear` — tipo, formato, coluna sombra `_txt`, pseudo-coluna `$` —
    vale sem uma linha de exceção.

    `filtro_linha` é um regex casado contra a linha crua. Arquivo posicional
    costuma misturar tipos de registro (cabeçalho, dado, encerramento) na
    mesma sequência de bytes; sem o filtro, o cabeçalho vira uma linha de
    dado com todos os campos deslocados.
    """
    texto = raw.decode(encoding, errors="strict")
    rx = re.compile(filtro_linha) if filtro_linha else None

    faixas: list[tuple[str, int, int]] = []
    largura_min = 0
    for c in colunas:
        origem = c["nome_origem"].strip()
        if origem.startswith("$"):
            continue
        faixa = faixa_de(origem)
        if faixa is None:
            raise ErroParse(
                f"formato 'larguras' exige faixa em nome_origem, e '{origem}' "
                f"não traz — use CAMPO@inicio-fim, com posições 1-indexadas"
            )
        ini, fim = faixa
        faixas.append((origem, ini - 1, fim))
        largura_min = max(largura_min, fim)

    def registros() -> Iterator[dict[str, Any]]:
        for linha in texto.splitlines():
            if not linha or (rx and not rx.match(linha)):
                continue
            if len(linha) < largura_min:
                raise ErroParse(
                    f"linha com {len(linha)} caracteres, mas o mapeamento "
                    f"declara campo até a posição {largura_min}"
                )
            yield {origem: linha[ini:fim] for origem, ini, fim in faixas}

    cabecalho = {origem.upper() for origem, _, _ in faixas}
    return mapear(registros(), colunas, cabecalho, contexto, extras)


def _caminho_xml(caminho: str) -> str:
    """`A/*/B` vira `{*}A/*/{*}B`: o caminho declarado ignora namespace.

    O XML da B3 troca de namespace a cada versão de mensagem (`bvmf.100.02`);
    amarrar o mapeamento ao namespace faria a troca de versão parecer arquivo
    vazio, não arquivo diferente.
    """
    partes = [p.strip() for p in caminho.strip().strip("/").split("/")]
    if not all(partes):
        raise ErroParse(f"caminho XML com trecho vazio: '{caminho}'")
    return "/".join(p if p in ("*", ".") else "{*}" + p for p in partes)


def _compilar_origem(origem: str) -> list[list[str]]:
    """`a|b` é o primeiro caminho que tiver valor — a B3 chama o estilo de
    exercício de `OptnStyle` numa opção sobre ação e de `ExrcStyle` numa
    opção sobre futuro. `a+b` junta os valores com `/` — mercado e segmento só
    viram nome juntos (o segmento 2 é `EQUITY CALL` no mercado 70 e `EQUITY
    PUT` no 80).
    """
    return [[_caminho_xml(t) for t in alt.split("+")] for alt in origem.split("|")]


def _valor_xml(registro, compilada: list[list[str]]) -> str:
    """O texto que a origem compilada aponta dentro do registro."""
    for alternativa in compilada:
        partes = [(registro.findtext(c) or "").strip() for c in alternativa]
        if any(partes):
            return "/".join(partes)
    return ""


def ler_xml(
    fluxo,
    colunas: list[dict],
    registro: str,
    filtro_registro: str | None = None,
    contexto: dict[str, str] | None = None,
    extras: dict[str, Any] | None = None,
) -> Iterator[dict[str, Any]]:
    """Lê registros de um XML em fluxo, com o mesmo mapeamento do CSV.

    `fluxo` é bytes ou um arquivo binário aberto. O arquivo da B3 tem ~450 MB
    descomprimido; ler inteiro para a memória seria o container pagando por
    uma árvore que só se percorre uma vez. Cada registro é lido, mapeado e
    tirado da árvore — e o que está fora de registro (cabeçalho de mensagem)
    também, senão os 120 mil `AppHdr` ficariam pendurados no pai.

    `registro` é o nome local do elemento que vira uma linha. Cada coluna
    declara em `nome_origem` o caminho relativo a ele (`InstrmInf/*/TckrSymb`),
    como o layout posicional declara a faixa.

    `filtro_registro` é um caminho que precisa ter valor para o registro
    entrar — o par do `filtro_linha` do posicional. Título de dívida e
    contrato de balcão vêm no mesmo arquivo do cadastro e não têm código de
    negociação; sem o filtro, cada um deles chegaria com a chave nula.

    Nenhum registro é erro, não arquivo vazio: um XML que não traz o elemento
    declarado é outro arquivo, e publicar zero linhas como sucesso deixaria a
    fotografia anterior parada sem alarme.
    """
    import xml.etree.ElementTree as ET

    if isinstance(fluxo, (bytes, bytearray)):
        fluxo = io.BytesIO(fluxo)
    origens = [c["nome_origem"].strip() for c in colunas
               if not c["nome_origem"].startswith("$")]
    # Compilado antes de abrir o arquivo: caminho inválido falha sem ler byte.
    compiladas = {o: _compilar_origem(o) for o in origens}
    filtro = _caminho_xml(filtro_registro) if filtro_registro else None

    def local(tag: str) -> str:
        return tag.rsplit("}", 1)[-1]

    def registros() -> Iterator[dict[str, Any]]:
        lidos = aceitos = 0
        pilha: list = []
        dentro = 0
        for evento, el in ET.iterparse(fluxo, events=("start", "end")):
            e_registro = local(el.tag) == registro
            if evento == "start":
                pilha.append(el)
                dentro += e_registro
                continue
            pilha.pop()
            pai = pilha[-1] if pilha else None
            if e_registro:
                dentro -= 1
                lidos += 1
                if filtro is None or (el.findtext(filtro) or "").strip():
                    aceitos += 1
                    yield {o: _valor_xml(el, c) for o, c in compiladas.items()}
                if pai is not None:
                    pai.remove(el)
            elif dentro == 0 and pai is not None:
                pai.remove(el)
        if not lidos:
            raise ErroParse(
                f"o XML não traz nenhum elemento <{registro}>: ou o arquivo "
                f"não é o declarado, ou o parâmetro 'registro' está errado"
            )
        if not aceitos:
            raise ErroParse(
                f"{lidos} registro(s) <{registro}>, nenhum com valor em "
                f"'{filtro_registro}'"
            )

    cabecalho = {o.upper() for o in origens}
    return mapear(registros(), colunas, cabecalho, contexto, extras)


def membros_em_fluxo(payload: bytes, padrao: str):
    """Como `membros_do_zip`, mas entrega o membro aberto, não os bytes.

    Para arquivo grande demais para a memória. Desce em ZIP dentro de ZIP: a
    B3 serve o cadastro como `IN261118.zip` contendo `IN261118.zip` contendo
    os XMLs. Quem consome tem de terminar de ler um membro antes de pedir o
    próximo — o arquivo fecha quando o gerador anda.
    """
    rx = re.compile(padrao, re.IGNORECASE)

    def percorrer(zf: zipfile.ZipFile):
        for nome in sorted(zf.namelist()):
            base = nome.rsplit("/", 1)[-1]
            m = rx.match(base)
            if m:
                with zf.open(nome) as fh:
                    yield base, fh, {k: (v or "") for k, v in m.groupdict().items()}
            elif base.lower().endswith(".zip"):
                with zipfile.ZipFile(io.BytesIO(zf.read(nome))) as interno:
                    yield from percorrer(interno)

    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        yield from percorrer(zf)


def membros_do_zip(
    payload: bytes, padrao: str
) -> Iterator[tuple[str, bytes, dict[str, str]]]:
    """Arquivos do ZIP que casam com o padrão, mais os grupos nomeados do nome.

    Os grupos nomeados do regex viram metadado da linha — é o mecanismo que
    torna `tipo_doc`, `grupo` e `con/ind` configuração em vez de código.
    """
    rx = re.compile(padrao, re.IGNORECASE)
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        for nome in sorted(zf.namelist()):
            base = nome.rsplit("/", 1)[-1]
            m = rx.match(base)
            if m:
                with zf.open(nome) as fh:
                    yield base, fh.read(), {
                        k: (v or "") for k, v in m.groupdict().items()
                    }
