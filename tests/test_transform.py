"""Testes do núcleo de transformação (dedup, escala, con/ind, ITR acumulado)."""
import zipfile

import pandas as pd

from cvm_financas import extrair_dataframes, marcar_versao_latest, preparar_saida
from cvm_financas.config import GRUPOS


def _carregar(dfp_zip, itr_zip):
    frames = []
    for tipo, path in [("DFP", dfp_zip), ("ITR", itr_zip)]:
        zf = zipfile.ZipFile(path)
        frames.extend(extrair_dataframes(zf, tipo, set(GRUPOS.keys())))
    df = marcar_versao_latest(pd.concat(frames, ignore_index=True))
    return preparar_saida(df)


def test_dedup_versao(dfp_zip, itr_zip):
    out = _carregar(dfp_zip, itr_zip)
    bpa = out[(out.grupo == "BPA") & out.consolidado]
    assert bpa[bpa.versao == 2].is_latest.all()
    assert not bpa[bpa.versao == 1].is_latest.any()


def test_escala_mil(dfp_zip, itr_zip):
    out = _carregar(dfp_zip, itr_zip)
    at = out[(out.grupo == "BPA") & out.consolidado & (out.versao == 2) & (out.cd_conta == "1")]
    assert at.vl_conta_norm.iloc[0] == 105000 * 1000


def test_con_ind(dfp_zip, itr_zip):
    out = _carregar(dfp_zip, itr_zip)
    assert (~out.consolidado).any()
    assert out.consolidado.any()


def test_itr_acumulado_flag(dfp_zip, itr_zip):
    out = _carregar(dfp_zip, itr_zip)
    dre_itr = out[(out.tipo_doc == "ITR") & (out.grupo == "DRE")]
    assert dre_itr.itr_acumulado.all()
    assert not out[out.tipo_doc == "DFP"].itr_acumulado.any()


def test_trimestre_isolado(dfp_zip, itr_zip):
    """Q2 isolado = 65.000 acum - 30.000 acum (em MIL) -> *1000."""
    out = _carregar(dfp_zip, itr_zip)
    d = out[(out.tipo_doc == "ITR") & (out.grupo == "DRE")].copy()
    d["dt_fim_exerc"] = pd.to_datetime(d["dt_fim_exerc"])
    d["ano"] = d.dt_fim_exerc.dt.year
    d = d.sort_values("dt_fim_exerc")
    d["isolado"] = (
        d.groupby(["cd_cvm", "consolidado", "cd_conta", "ano"])["vl_conta_norm"]
        .diff().fillna(d.vl_conta_norm)
    )
    q2 = d[d.dt_fim_exerc.dt.month == 6].isolado.iloc[0]
    assert q2 == (65000 - 30000) * 1000
