"""Constantes de origem e layout dos datasets da CVM."""
from __future__ import annotations

import re

BASE_URL = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC"

URL_TEMPLATE = {
    "DFP": BASE_URL + "/DFP/DADOS/dfp_cia_aberta_{ano}.zip",
    "ITR": BASE_URL + "/ITR/DADOS/itr_cia_aberta_{ano}.zip",
}

# Grupo de demonstração -> (label, eh_fluxo)
#   eh_fluxo=True  -> DRE/DFC/DVA/DRA: no ITR o valor é ACUMULADO no ano (YTD)
#   eh_fluxo=False -> BPA/BPP/DMPL: posição, não acumula
GRUPOS: dict[str, tuple[str, bool]] = {
    "BPA":    ("BPA", False),   # Balanço Patrimonial Ativo
    "BPP":    ("BPP", False),   # Balanço Patrimonial Passivo
    "DRE":    ("DRE", True),    # Demonstração do Resultado
    "DFC_MI": ("DFC_MI", True), # Fluxo de Caixa - método indireto
    "DFC_MD": ("DFC_MD", True), # Fluxo de Caixa - método direto
    "DVA":    ("DVA", True),    # Valor Adicionado
    "DRA":    ("DRA", True),    # Resultado Abrangente
    "DMPL":   ("DMPL", False),  # Mutações do PL
}

# Nome dos CSVs de conta dentro do ZIP, ex:
#   dfp_cia_aberta_BPA_con_2023.csv | itr_cia_aberta_DFC_MI_ind_2023.csv
FNAME_RE = re.compile(
    r"^(dfp|itr)_cia_aberta_(BPA|BPP|DRE|DFC_MI|DFC_MD|DVA|DRA|DMPL)_(con|ind)_(\d{4})\.csv$",
    re.IGNORECASE,
)

COLS_ESPERADAS = [
    "CNPJ_CIA", "DT_REFER", "VERSAO", "DENOM_CIA", "CD_CVM", "GRUPO_DFP",
    "MOEDA", "ESCALA_MOEDA", "ORDEM_EXERC", "DT_INI_EXERC", "DT_FIM_EXERC",
    "CD_CONTA", "DS_CONTA", "VL_CONTA", "ST_CONTA_FIXA", "COLUNA_DF",
]

ESCALA_FATOR = {"UNIDADE": 1, "MIL": 1000, "MILHAO": 1_000_000}

# Mapeamento colunas internas (upper) -> nomes de saída (snake_case do schema)
COLS_SAIDA = {
    "CD_CVM": "cd_cvm", "CNPJ_CIA": "cnpj", "DENOM_CIA": "denom_cia",
    "TIPO_DOC": "tipo_doc", "GRUPO": "grupo", "CONSOLIDADO": "consolidado",
    "DT_REFER": "dt_refer", "DT_INI_EXERC": "dt_ini_exerc", "DT_FIM_EXERC": "dt_fim_exerc",
    "ORDEM_EXERC": "ordem_exerc", "VERSAO": "versao",
    "CD_CONTA": "cd_conta", "DS_CONTA": "ds_conta", "ST_CONTA_FIXA": "st_conta_fixa",
    "MOEDA": "moeda", "ESCALA_MOEDA": "escala_moeda", "COLUNA_DF": "coluna_df",
    "VL_CONTA": "vl_conta", "VL_CONTA_NORM": "vl_conta_norm",
    "IS_LATEST": "is_latest", "ITR_ACUMULADO": "itr_acumulado",
    "FONTE_ARQUIVO": "fonte_arquivo",
}
