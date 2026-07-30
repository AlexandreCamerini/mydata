# cvm-financas

Ingestor das demonstrações financeiras da CVM (Dados Abertos — DFP anual e ITR
trimestral) para uma base própria (DuckDB ou Postgres), com **normalização**
explícita dos furos que quebram análise fundamentalista.

## Instalação

```bash
pip install .                      # núcleo (requests + pandas)
pip install ".[duckdb]"            # + sink DuckDB (default)
pip install ".[postgres]"          # + SQLAlchemy/psycopg
pip install ".[dev]"               # + pytest e duckdb (para rodar os testes)
```

## Uso — CLI

```bash
# DuckDB (zero-setup)
cvm-ingest --tipos DFP ITR --anos 2020-2024 --db cvm.duckdb -v

# Postgres (rode o schema antes)
cvm-ingest --print-schema | psql "$DSN"
cvm-ingest --anos 2023 --pg "postgresql+psycopg://user:pass@host:5432/cvm"

# subset de grupos / transformação sem carga / teste offline com zip local
cvm-ingest --anos 2023 --grupos BPA BPP DRE
cvm-ingest --anos 2023 --dry-run -v
cvm-ingest --arquivo-local ./dfp_cia_aberta_2023.zip --tipos DFP --anos 2023 --dry-run -v
```

## Uso — como biblioteca

```python
from cvm_financas import executar

res = executar(tipos=["DFP", "ITR"], anos="2023", db="cvm.duckdb")
print(res.linhas, res.linhas_latest, res.total_no_banco)

# só o DataFrame normalizado, sem tocar em banco:
df = executar(anos="2023", dry_run=True).df
```

## Estrutura

```
cvm-financas/
├── pyproject.toml                 # metadata, deps, entry-point cvm-ingest
├── src/cvm_financas/
│   ├── config.py                  # URLs, grupos, colunas, escalas
│   ├── download.py                # baixar_zip (requests)
│   ├── parse.py                   # parse + normalização + dedup de versão
│   ├── load.py                    # sinks DuckDB/Postgres + schema_sql()
│   ├── pipeline.py                # executar() -> ResultadoIngestao
│   ├── cli.py                     # cvm-ingest
│   └── sql/schema_postgres.sql    # DDL + views (empacotado)
└── tests/                         # pytest + fixtures no layout CVM
```

Camadas medallion: zips da CVM = **bronze**; `fato_conta` = **silver** (tipado,
deduplicado, escala normalizada); views (`vw_conta_atual`,
`vw_itr_trimestre_isolado`) = início da **gold**.

## Os dados vêm normalizados? Não — vêm *padronizados*.

Schema fixo e plano de contas de nível superior padronizado
(`ST_CONTA_FIXA='S'`), mas **não pronto para análise**. O que o pacote resolve:

| # | Furo na origem | Tratamento |
|---|----------------|-----------|
| 1 | **Reapresentação (`VERSAO`)** — várias versões do mesmo período | flag `is_latest` (maior versão por empresa/período/grupo/con-ind) |
| 2 | **`ORDEM_EXERC`** — período atual + comparativo no mesmo doc | view filtra `ÚLTIMO` |
| 3 | **`ESCALA_MOEDA`** (UNIDADE/MIL) — erro de 1000x | `vl_conta_norm` = `vl_conta × escala` |
| 4 | **Individual vs Consolidado** coexistem | flag `consolidado`; view usa `TRUE` |
| 5 | **ITR é acumulado no ano (YTD)** — Q2 = 6 meses | flag `itr_acumulado` + `vw_itr_trimestre_isolado` |
| 6 | **Contas custom (`'N'`)** — não comparáveis entre empresas | flag preservada; use `='S'` p/ cross-company |
| 7 | **Encoding `latin-1` + `;`** | parse fixo, coerção numérica robusta |

## Riscos / dívida em aberto

- **Reconciliação Ativo = Passivo+PL não é automática** — check pós-load recomendado
  (esqueleto no fim de `schema_postgres.sql`). Divergência = reapresentação não capturada.
- `dim_empresa` (cadastro `cad_cia_aberta.csv`, dataset separado) não é carregado no loop.
- Full-file por ano (sem CDC) — adequado ao volume da CVM (poucos MB/ano).
- `is_latest` é recalculado por execução; reingerir anos antigos exige reprocessar o conjunto.

## Testes

```bash
pytest -q      # valida dedup, escala, con/ind, itr_acumulado e trimestre isolado
```
