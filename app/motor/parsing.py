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
