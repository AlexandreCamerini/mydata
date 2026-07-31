"""Fixtures: gera ZIPs sintéticos no layout exato da CVM.

A primeira metade serve o pacote legado `cvm_financas`; a segunda serve o
portal (`app`). Os dois convivem: o pacote continua sendo entregável próprio.
"""
import io
import os
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


# ==========================================================================
# Portal (app) — sink em memória e ZIPs no layout da CVM
# ==========================================================================
from app import bootstrap, seed_cvm  # noqa: E402
from app.sinks import SinkDuckDB  # noqa: E402

CAB = (
    "CNPJ_CIA;DT_REFER;VERSAO;DENOM_CIA;CD_CVM;GRUPO_DFP;MOEDA;ESCALA_MOEDA;"
    "ORDEM_EXERC;DT_INI_EXERC;DT_FIM_EXERC;CD_CONTA;DS_CONTA;VL_CONTA;"
    "ST_CONTA_FIXA;COLUNA_DF"
)


def linha(
    *, cnpj="00.000.000/0001-00", dt_refer="2023-12-31", versao=1,
    denom="EMPRESA TESTE S.A.", cd_cvm=9512, grupo_dfp="DF Consolidado - BPA",
    moeda="REAL", escala="MIL", ordem="ÚLTIMO", ini="2023-01-01",
    fim="2023-12-31", cd_conta="1", ds_conta="Ativo Total", vl="1000,00",
    fixa="S", coluna="",
) -> str:
    return ";".join(str(x) for x in [
        cnpj, dt_refer, versao, denom, cd_cvm, grupo_dfp, moeda, escala,
        ordem, ini, fim, cd_conta, ds_conta, vl, fixa, coluna,
    ])


def csv_conta(linhas: list[str]) -> bytes:
    return ("\n".join([CAB, *linhas]) + "\n").encode("latin-1")


def zip_cvm(arquivos: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for nome, conteudo in arquivos.items():
            zf.writestr(nome, conteudo)
    return buf.getvalue()


# Um DSN em PORTAL_TESTE_POSTGRES faz a suíte inteira rodar contra Postgres.
# Sem ele, DuckDB em memória, como sempre. Os dois caminhos existem no código
# de produção; testar só um deixa o outro por conta da sorte.
DSN_TESTE = os.getenv("PORTAL_TESTE_POSTGRES")


@pytest.fixture()
def sink():
    if DSN_TESTE:
        from app.sinks import SinkPostgres

        s = SinkPostgres(DSN_TESTE)
        # Schema limpo por teste: é o equivalente ao ":memory:" do DuckDB.
        # Recriar `public` é mais rápido que derrubar o banco, e reproduz a
        # topologia de produção, onde tudo mora nesse schema.
        s.executar("DROP SCHEMA IF EXISTS public CASCADE")
        s.executar("CREATE SCHEMA public")
    else:
        s = SinkDuckDB(":memory:")
    bootstrap.preparar(s)
    yield s
    s.fechar()


@pytest.fixture()
def sink_cvm(sink):
    """Sink com a configuração da CVM já cadastrada."""
    seed_cvm.aplicar(sink)
    return sink


@pytest.fixture()
def zip_dfp_2023() -> bytes:
    """DFP 2023 com as armadilhas: reapresentação, ÚLTIMO/PENÚLTIMO,
    escalas diferentes, consolidado e individual."""
    bpa_con = csv_conta([
        linha(versao=1, cd_conta="1", vl="1000,00", ordem="ÚLTIMO"),
        linha(versao=1, cd_conta="1", vl="900,00", ordem="PENÚLTIMO",
              ini="2022-01-01", fim="2022-12-31"),
        linha(versao=2, cd_conta="1", vl="1100,00", ordem="ÚLTIMO"),
        linha(versao=2, cd_conta="1.01", vl="400,00", ordem="ÚLTIMO",
              ds_conta="Ativo Circulante"),
        linha(cd_cvm=1023, denom="OUTRA S.A.", escala="UNIDADE",
              cd_conta="1", vl="5000000,00", versao=1),
    ])
    bpp_con = csv_conta([
        linha(versao=2, cd_conta="2", vl="1100,00", ds_conta="Passivo Total",
              grupo_dfp="DF Consolidado - BPP"),
        linha(cd_cvm=1023, denom="OUTRA S.A.", escala="UNIDADE", cd_conta="2",
              vl="5000000,00", versao=1, ds_conta="Passivo Total",
              grupo_dfp="DF Consolidado - BPP"),
    ])
    bpa_ind = csv_conta([
        linha(versao=2, cd_conta="1", vl="800,00",
              grupo_dfp="DF Individual - BPA"),
    ])
    dre_con = csv_conta([
        linha(versao=2, cd_conta="3.01", vl="500,00", ds_conta="Receita",
              grupo_dfp="DF Consolidado - DRE"),
    ])
    return zip_cvm({
        "dfp_cia_aberta_BPA_con_2023.csv": bpa_con,
        "dfp_cia_aberta_BPP_con_2023.csv": bpp_con,
        "dfp_cia_aberta_BPA_ind_2023.csv": bpa_ind,
        "dfp_cia_aberta_DRE_con_2023.csv": dre_con,
        "dfp_cia_aberta_2023.csv": b"fora;do;padrao\n",
    })


@pytest.fixture()
def zip_itr_2024() -> bytes:
    """ITR 2024: DRE acumulada (YTD) em três trimestres."""
    dre = csv_conta([
        linha(dt_refer="2024-03-31", cd_conta="3.01", vl="100,00",
              ini="2024-01-01", fim="2024-03-31", grupo_dfp="DF Consolidado - DRE"),
        linha(dt_refer="2024-06-30", cd_conta="3.01", vl="250,00",
              ini="2024-01-01", fim="2024-06-30", grupo_dfp="DF Consolidado - DRE"),
        linha(dt_refer="2024-09-30", cd_conta="3.01", vl="420,00",
              ini="2024-01-01", fim="2024-09-30", grupo_dfp="DF Consolidado - DRE"),
    ])
    bpa = csv_conta([
        linha(dt_refer="2024-03-31", cd_conta="1", vl="1000,00",
              ini="2024-01-01", fim="2024-03-31"),
    ])
    return zip_cvm({
        "itr_cia_aberta_DRE_con_2024.csv": dre,
        "itr_cia_aberta_BPA_con_2024.csv": bpa,
    })


@pytest.fixture()
def csv_cadastro() -> bytes:
    cab = ("CNPJ_CIA;DENOM_SOCIAL;DENOM_COMERC;DT_REG;SETOR_ATIV;SIT;"
           "CONTROLE_ACIONARIO;UF;MUN;CD_CVM")
    linhas = [
        "00.000.000/0001-00;EMPRESA TESTE S.A.;TESTE;1999-05-10;"
        "Petróleo e Gás;ATIVO;Estatal;RJ;RIO DE JANEIRO;9512",
        "11.111.111/0001-11;OUTRA S.A.;OUTRA;2005-02-01;"
        "Bancos;ATIVO;Privado;SP;SAO PAULO;1023",
    ]
    return ("\n".join([cab, *linhas]) + "\n").encode("latin-1")
