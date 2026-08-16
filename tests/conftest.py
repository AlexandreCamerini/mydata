"""Fixtures: gera ZIPs sintéticos no layout exato da CVM para o portal."""
import io
import os
import pathlib
import zipfile

import pytest
from fastapi.testclient import TestClient

# ==========================================================================
# Portal (app) — sink em memória e ZIPs no layout da CVM
# ==========================================================================
from app import bootstrap, seed_fontes  # noqa: E402
from app.api import auth  # noqa: E402
from app.motor import ingestao  # noqa: E402
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
    seed_fontes.aplicar(sink)
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


def baixador(mapa: dict[str, bytes]):
    def _baixar(url: str, cabecalhos=None) -> bytes:
        for chave, dado in mapa.items():
            if chave in url:
                return dado
        raise AssertionError(f"URL não prevista: {url}")
    return _baixar


def sink_do_ambiente():
    """Abre o mesmo banco que a fixture `cliente` preparou.

    Existe porque vários testes precisam emitir chave ou inspecionar
    configuração por fora da API, e não podem supor o dialeto: com
    `PORTAL_TESTE_POSTGRES` definido, a API roda em Postgres.
    """
    if DSN_TESTE:
        from app.sinks import SinkPostgres

        return SinkPostgres(DSN_TESTE)
    return SinkDuckDB(os.environ["PORTAL_DUCKDB"])


@pytest.fixture()
def cliente(tmp_path, zip_dfp_2023, csv_cadastro, monkeypatch):
    """API sobre a base já carregada com dado.

    Roda nos dois dialetos: com `PORTAL_TESTE_POSTGRES` definido, a API sobe
    contra Postgres. Sem isso, a camada de API — que é a que mais SQL escreve
    — nunca era exercitada no dialeto de produção, e foi ali que os dois
    últimos deploys quebraram.
    """
    monkeypatch.delenv("PORTAL_ADMIN_TOKEN", raising=False)
    if DSN_TESTE:
        monkeypatch.setenv("DATABASE_URL", DSN_TESTE)
        from app.sinks import SinkPostgres

        s = SinkPostgres(DSN_TESTE)
        s.executar("DROP SCHEMA IF EXISTS public CASCADE")
        s.executar("CREATE SCHEMA public")
    else:
        banco = str(tmp_path / "api.duckdb")
        monkeypatch.setenv("PORTAL_DUCKDB", banco)
        monkeypatch.delenv("DATABASE_URL", raising=False)
        s = SinkDuckDB(banco)
    bootstrap.preparar(s)
    seed_fontes.aplicar(s)
    ingestao.executar(s, "cvm_dfp", "2023",
                      baixar=baixador({"dfp_cia_aberta_2023.zip": zip_dfp_2023}))
    ingestao.executar(s, "cvm_cadastro", "atual",
                      baixar=baixador({"cad_cia_aberta.csv": csv_cadastro}))
    emitida = auth.emitir(s, "bolsia", quota_minuto=5, quota_dia=1000)
    s.fechar()

    from app.api.main import app
    with TestClient(app) as c:
        c.headers.update({"X-API-Key": emitida.chave_completa})
        c.chave = emitida
        yield c

    # O arquivo sai junto com o teste. `tmp_path` guarda um diretório por teste
    # e só apaga entre sessões, então os ~47 testes que usam esta fixture
    # deixavam ~47 bancos DuckDB vivos ao mesmo tempo — perto de 2 GB de disco
    # para rodar a suíte. Apagando aqui, existe um de cada vez.
    if not DSN_TESTE:
        pathlib.Path(banco).unlink(missing_ok=True)
