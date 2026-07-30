"""Parse + normalização dos CSVs de conta da CVM."""
from __future__ import annotations

import io
import logging
import zipfile
from pathlib import Path

import pandas as pd

from .config import COLS_ESPERADAS, COLS_SAIDA, ESCALA_FATOR, FNAME_RE, GRUPOS

log = logging.getLogger("cvm_financas")


def parse_csv_conta(
    raw: bytes, tipo_doc: str, grupo: str, consolidado: bool, eh_fluxo: bool, fonte: str
) -> pd.DataFrame:
    """Lê um CSV de conta (latin-1, ';') e devolve DataFrame normalizado.

    Grão: 1 linha por conta contábil. Normalizações aplicadas:
    tipagem, escala->UNIDADE, flags (consolidado, itr_acumulado), ordem_exerc.
    """
    df = pd.read_csv(
        io.BytesIO(raw), sep=";", encoding="latin-1", dtype=str, na_values=[""]
    )
    df.columns = [c.strip().upper() for c in df.columns]

    for col in COLS_ESPERADAS:
        if col not in df.columns:
            df[col] = pd.NA

    # tipagem
    df["VL_CONTA"] = (
        df["VL_CONTA"].astype(str)
        .str.replace(",", ".", regex=False)
        .pipe(pd.to_numeric, errors="coerce")
    )
    df["VERSAO"] = pd.to_numeric(df["VERSAO"], errors="coerce").astype("Int64")
    df["CD_CVM"] = pd.to_numeric(df["CD_CVM"], errors="coerce").astype("Int64")
    for dcol in ("DT_REFER", "DT_INI_EXERC", "DT_FIM_EXERC"):
        df[dcol] = pd.to_datetime(df[dcol], errors="coerce").dt.date

    # escala -> unidade
    fator = df["ESCALA_MOEDA"].str.upper().map(ESCALA_FATOR).fillna(1)
    df["VL_CONTA_NORM"] = df["VL_CONTA"] * fator

    # enriquecimento
    df["TIPO_DOC"] = tipo_doc
    df["GRUPO"] = grupo
    df["CONSOLIDADO"] = consolidado
    df["ITR_ACUMULADO"] = (tipo_doc == "ITR") and eh_fluxo
    df["FONTE_ARQUIVO"] = fonte
    df["ORDEM_EXERC"] = (
        df["ORDEM_EXERC"].astype(str).str.strip().str.upper()
        .str.replace("ULTIMO", "ÚLTIMO").str.replace("PENULTIMO", "PENÚLTIMO")
    )
    return df


def extrair_dataframes(
    zf: zipfile.ZipFile, tipo_doc: str, grupos_alvo: set[str]
) -> list[pd.DataFrame]:
    """Extrai e parseia todos os CSVs de conta de um ZIP para os grupos alvo."""
    frames: list[pd.DataFrame] = []
    for nome in zf.namelist():
        m = FNAME_RE.match(Path(nome).name)
        if not m:
            continue
        prefixo, grupo_raw, con_ind, _ano = m.groups()
        # tipo_doc vem do NOME do arquivo (fonte de verdade), não do argumento
        if prefixo.upper() != tipo_doc.upper():
            continue
        grupo_raw = grupo_raw.upper()
        if grupo_raw not in grupos_alvo:
            continue
        label, eh_fluxo = GRUPOS[grupo_raw]
        consolidado = con_ind.lower() == "con"
        with zf.open(nome) as fh:
            df = parse_csv_conta(
                fh.read(), tipo_doc.upper(), label, consolidado, eh_fluxo, fonte=nome
            )
        frames.append(df)
        log.info("ok %s: %d linhas", nome, len(df))
    return frames


def marcar_versao_latest(df: pd.DataFrame) -> pd.DataFrame:
    """is_latest = maior VERSÃO por (empresa, período, grupo, con/ind, tipo_doc)."""
    chave = ["CD_CVM", "TIPO_DOC", "GRUPO", "CONSOLIDADO", "DT_REFER"]
    max_versao = df.groupby(chave, dropna=False)["VERSAO"].transform("max")
    df["IS_LATEST"] = df["VERSAO"].eq(max_versao)
    return df


def preparar_saida(df: pd.DataFrame) -> pd.DataFrame:
    """Seleciona e renomeia colunas para o schema de saída."""
    return df[list(COLS_SAIDA.keys())].rename(columns=COLS_SAIDA)
