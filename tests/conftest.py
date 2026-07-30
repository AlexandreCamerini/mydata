"""Fixtures: gera ZIPs sintéticos no layout exato da CVM."""
import zipfile

import pytest

_BPA_CON = """CNPJ_CIA;DT_REFER;VERSAO;DENOM_CIA;CD_CVM;GRUPO_DFP;MOEDA;ESCALA_MOEDA;ORDEM_EXERC;DT_FIM_EXERC;CD_CONTA;DS_CONTA;VL_CONTA;ST_CONTA_FIXA;COLUNA_DF
33.000.167/0001-01;2023-12-31;1;PETROBRAS;9512;DF Consolidado - BPA;REAL;MIL;ÚLTIMO;2023-12-31;1;Ativo Total;100000;S;
33.000.167/0001-01;2023-12-31;1;PETROBRAS;9512;DF Consolidado - BPA;REAL;MIL;ÚLTIMO;2023-12-31;1.01;Ativo Circulante;40000;S;
33.000.167/0001-01;2023-12-31;2;PETROBRAS;9512;DF Consolidado - BPA;REAL;MIL;ÚLTIMO;2023-12-31;1;Ativo Total;105000;S;
33.000.167/0001-01;2023-12-31;2;PETROBRAS;9512;DF Consolidado - BPA;REAL;MIL;ÚLTIMO;2023-12-31;1.01;Ativo Circulante;42000;S;
"""

_BPA_IND = """CNPJ_CIA;DT_REFER;VERSAO;DENOM_CIA;CD_CVM;GRUPO_DFP;MOEDA;ESCALA_MOEDA;ORDEM_EXERC;DT_FIM_EXERC;CD_CONTA;DS_CONTA;VL_CONTA;ST_CONTA_FIXA;COLUNA_DF
33.000.167/0001-01;2023-12-31;2;PETROBRAS;9512;DF Individual - BPA;REAL;MIL;ÚLTIMO;2023-12-31;1;Ativo Total;90000;S;
"""

_DRE_CON = """CNPJ_CIA;DT_REFER;VERSAO;DENOM_CIA;CD_CVM;GRUPO_DFP;MOEDA;ESCALA_MOEDA;ORDEM_EXERC;DT_INI_EXERC;DT_FIM_EXERC;CD_CONTA;DS_CONTA;VL_CONTA;ST_CONTA_FIXA;COLUNA_DF
33.000.167/0001-01;2023-03-31;1;PETROBRAS;9512;DF Consolidado - DRE;REAL;MIL;ÚLTIMO;2023-01-01;2023-03-31;3.01;Receita;30000;S;
33.000.167/0001-01;2023-06-30;1;PETROBRAS;9512;DF Consolidado - DRE;REAL;MIL;ÚLTIMO;2023-01-01;2023-06-30;3.01;Receita;65000;S;
"""


@pytest.fixture
def dfp_zip(tmp_path):
    p = tmp_path / "dfp_cia_aberta_2023.zip"
    with zipfile.ZipFile(p, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("dfp_cia_aberta_BPA_con_2023.csv", _BPA_CON.encode("latin-1"))
        z.writestr("dfp_cia_aberta_BPA_ind_2023.csv", _BPA_IND.encode("latin-1"))
    return str(p)


@pytest.fixture
def itr_zip(tmp_path):
    p = tmp_path / "itr_cia_aberta_2023.zip"
    with zipfile.ZipFile(p, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("itr_cia_aberta_DRE_con_2023.csv", _DRE_CON.encode("latin-1"))
    return str(p)
