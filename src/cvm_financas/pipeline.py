"""Orquestração do pipeline: download -> parse -> normaliza -> load."""
from __future__ import annotations

import logging
import zipfile
from dataclasses import dataclass, field

import pandas as pd

from .config import GRUPOS
from .download import baixar_zip
from .load import load_duckdb, load_postgres
from .parse import extrair_dataframes, marcar_versao_latest, preparar_saida

log = logging.getLogger("cvm_financas")


@dataclass
class ResultadoIngestao:
    df: pd.DataFrame                      # saída normalizada (grão = conta)
    linhas: int = 0
    linhas_latest: int = 0
    carregado: bool = False
    total_no_banco: int | None = None
    arquivos: list[str] = field(default_factory=list)


def parse_anos(spec: str) -> list[int]:
    """'2020-2024' ou '2021,2023' -> lista de anos."""
    anos: set[int] = set()
    for parte in str(spec).split(","):
        parte = parte.strip()
        if "-" in parte:
            ini, fim = map(int, parte.split("-"))
            anos.update(range(ini, fim + 1))
        elif parte:
            anos.add(int(parte))
    return sorted(anos)


def executar(
    *,
    tipos: list[str] | None = None,
    anos: list[int] | str = "2023",
    grupos: list[str] | None = None,
    db: str | None = "cvm.duckdb",
    pg: str | None = None,
    arquivo_local: str | None = None,
    dry_run: bool = False,
) -> ResultadoIngestao:
    """Executa o pipeline. Com dry_run=True, transforma mas não carrega.

    Retorna ResultadoIngestao com o DataFrame normalizado e métricas.
    """
    tipos = tipos or ["DFP", "ITR"]
    grupos_alvo = {g.upper() for g in (grupos or list(GRUPOS.keys()))}
    lista_anos = parse_anos(anos) if isinstance(anos, str) else sorted(anos)
    log.info("tipos=%s anos=%s grupos=%s", tipos, lista_anos, sorted(grupos_alvo))

    todos: list[pd.DataFrame] = []
    fontes: list[str] = []
    for tipo in tipos:
        for ano in lista_anos:
            try:
                zf = zipfile.ZipFile(arquivo_local) if arquivo_local else baixar_zip(tipo, ano)
            except Exception as e:  # noqa: BLE001
                log.warning("skip %s %s: %s", tipo, ano, e)
                continue
            frames = extrair_dataframes(zf, tipo, grupos_alvo)
            todos.extend(frames)
            fontes.extend(f["FONTE_ARQUIVO"].iloc[0] for f in frames if len(f))

    if not todos:
        return ResultadoIngestao(df=pd.DataFrame(), arquivos=fontes)

    df = marcar_versao_latest(pd.concat(todos, ignore_index=True))
    saida = preparar_saida(df)
    res = ResultadoIngestao(
        df=saida,
        linhas=len(saida),
        linhas_latest=int(saida["is_latest"].sum()),
        arquivos=fontes,
    )
    if dry_run:
        return res

    if pg:
        res.total_no_banco = load_postgres(saida, pg)
    else:
        res.total_no_banco = load_duckdb(saida, db)
    res.carregado = True
    return res
