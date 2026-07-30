#!/usr/bin/env python
"""Sobe uma base local com dado de exemplo, pronta para abrir o portal.

Uso:  python scripts/demo.py
Depois:  uvicorn app.api.main:app --port 8099

Usa dado sintético (segundos). Para dado real da CVM, veja o fim do arquivo.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "tests"))

from app import bootstrap, seed_cvm                      # noqa: E402
from app.api import auth                                 # noqa: E402
from app.motor import ingestao                           # noqa: E402
from app.sinks import SinkDuckDB                         # noqa: E402
from conftest import csv_conta, linha, zip_cvm           # noqa: E402

BANCO = os.getenv("PORTAL_DUCKDB", "dados/demo.duckdb")


def main() -> int:
    Path(BANCO).parent.mkdir(parents=True, exist_ok=True)
    if Path(BANCO).exists():
        Path(BANCO).unlink()

    sink = SinkDuckDB(BANCO)
    bootstrap.preparar(sink)
    seed_cvm.aplicar(sink)

    dfp = zip_cvm({
        "dfp_cia_aberta_BPA_con_2023.csv": csv_conta([
            linha(versao=1, cd_conta="1", vl="1000,00"),
            linha(versao=2, cd_conta="1", vl="1100,00"),
            linha(versao=2, cd_conta="1.01", vl="400,00", ds_conta="Ativo Circulante"),
            linha(versao=2, cd_conta="1.02", vl="700,00", ds_conta="Ativo Não Circulante"),
            linha(cd_cvm=1023, denom="OUTRA S.A.", escala="UNIDADE",
                  cd_conta="1", vl="5000000,00", versao=1),
        ]),
        "dfp_cia_aberta_BPP_con_2023.csv": csv_conta([
            linha(versao=2, cd_conta="2", vl="1100,00", ds_conta="Passivo Total"),
            linha(versao=2, cd_conta="2.01", vl="300,00", ds_conta="Passivo Circulante"),
            linha(versao=2, cd_conta="2.02", vl="0,00", ds_conta="Passivo Não Circulante"),
            linha(versao=2, cd_conta="2.03", vl="800,00", ds_conta="Patrimônio Líquido"),
            linha(cd_cvm=1023, denom="OUTRA S.A.", escala="UNIDADE", cd_conta="2",
                  vl="5000000,00", versao=1, ds_conta="Passivo Total"),
        ]),
        "dfp_cia_aberta_DRE_con_2023.csv": csv_conta([
            linha(versao=2, cd_conta="3.01", vl="2000,00", ds_conta="Receita"),
            linha(versao=2, cd_conta="3.11", vl="180,00", ds_conta="Lucro do Período"),
        ]),
    })
    itr = zip_cvm({
        "itr_cia_aberta_DRE_con_2024.csv": csv_conta([
            linha(dt_refer="2024-03-31", cd_conta="3.01", vl="500,00",
                  ini="2024-01-01", fim="2024-03-31"),
            linha(dt_refer="2024-06-30", cd_conta="3.01", vl="1150,00",
                  ini="2024-01-01", fim="2024-06-30"),
            linha(dt_refer="2024-09-30", cd_conta="3.01", vl="1800,00",
                  ini="2024-01-01", fim="2024-09-30"),
        ]),
    })
    cadastro = (
        "CNPJ_CIA;DENOM_SOCIAL;DENOM_COMERC;DT_REG;SETOR_ATIV;SIT;"
        "CONTROLE_ACIONARIO;UF;MUN;CD_CVM\n"
        "00.000.000/0001-00;EMPRESA TESTE S.A.;TESTE;1999-05-10;"
        "Petróleo e Gás;ATIVO;Estatal;RJ;RIO DE JANEIRO;9512\n"
        "11.111.111/0001-11;OUTRA S.A.;OUTRA;2005-02-01;"
        "Bancos;ATIVO;Privado;SP;SAO PAULO;1023\n"
    ).encode("latin-1")

    def de(mapa):
        return lambda url: next(v for k, v in mapa.items() if k in url)

    ingestao.executar(sink, "cvm_dfp", "2023",
                      baixar=de({"dfp_cia_aberta_2023.zip": dfp}))
    ingestao.executar(sink, "cvm_itr", "2024",
                      baixar=de({"itr_cia_aberta_2024.zip": itr}))
    ingestao.executar(sink, "cvm_cadastro", "atual",
                      baixar=de({"cad_cia_aberta.csv": cadastro}))

    chave = auth.emitir(sink, "demo")
    linhas = sink.um("SELECT count(*) AS n FROM gold_demonstracoes")["n"]
    sink.fechar()

    print(f"""
Base pronta: {BANCO}  ({linhas} linhas em gold)

  1) Suba o servidor:
       PORTAL_DUCKDB={BANCO} uvicorn app.api.main:app --port 8099

  2) Abra no navegador:
       Telas de configuração ... http://127.0.0.1:8099/admin/
       Documentação da API .... http://127.0.0.1:8099/docs

  3) Chame a API (a chave só aparece agora):
       curl -H 'X-API-Key: {chave.chave_completa}' \\
         'http://127.0.0.1:8099/v1/empresas/9512/demonstracoes?grupo=BPA'
""")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# Para dado real da CVM (baixa ~13 MB, leva ~27 min por ano):
#   python -m app.cli migrar --seed
#   python -m app.cli ingerir cvm_dfp 2023
