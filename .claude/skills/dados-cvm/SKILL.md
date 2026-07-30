---
name: dados-cvm
description: Regras de leitura e agregação dos dados da CVM Dados Abertos (DFP/ITR) — layout dos ZIPs/CSVs, as sete armadilhas do dado padronizado (reapresentação, ordem de exercício, escala, con/ind, ITR acumulado, contas custom, encoding) e como consultar sem dobrar valores. Use ao ingerir, modelar, consultar ou revisar qualquer coisa que toque demonstrações financeiras da CVM.
---

# Dados da CVM — o que o layout não conta

O dado da CVM é **padronizado, não normalizado**. Ele chega consistente em
formato e inconsistente em semântica. Sete pontos decidem se um número está
certo.

## Origem

Não é REST. São ZIPs anuais em
`https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/{DFP|ITR}/DADOS/{dfp|itr}_cia_aberta_{ano}.zip`.
Dentro, um CSV por grupo e por escopo:
`{dfp|itr}_cia_aberta_{BPA|BPP|DRE|DFC_MI|DFC_MD|DVA|DRA|DMPL}_{con|ind}_{ano}.csv`.

Encoding `latin-1`, separador `;`. Lido como UTF-8, `DENOM_CIA` e `DS_CONTA`
quebram.

O cadastro de empresas é um dataset separado: `cad_cia_aberta.csv`.

## As sete armadilhas

| # | Armadilha | Como se manifesta | Resolução |
|---|---|---|---|
| 1 | **Reapresentação** | a mesma empresa/período aparece em mais de uma `VERSAO`; somar tudo dobra o valor | manter só a maior `VERSAO` por `(cd_cvm, tipo_doc, dt_refer)` → flag `is_latest` |
| 2 | **`ORDEM_EXERC`** | cada arquivo traz `ÚLTIMO` e `PENÚLTIMO` exercício; somar os dois dobra | filtrar `ORDEM_EXERC = 'ÚLTIMO'` |
| 3 | **`ESCALA_MOEDA`** | `VL_CONTA` vem em UNIDADE, MIL ou MILHÃO, variando por empresa | multiplicar pelo fator → `vl_conta_norm`, preservando `vl_conta` |
| 4 | **Individual vs consolidado** | o mesmo período existe em `con` e `ind`; misturar soma a empresa duas vezes | flag `consolidado`, e escolher um escopo por consulta |
| 5 | **ITR é acumulado (YTD)** | no ITR, contas de fluxo (DRE, DFC, DVA, DRA) são acumuladas no ano, não do trimestre | flag `itr_acumulado`; trimestre isolado = acumulado − acumulado do período anterior do mesmo exercício (Q1 isolado = Q1 acumulado) |
| 6 | **Contas custom** | `ST_CONTA_FIXA = 'N'` marca conta criada pela empresa; `CD_CONTA` não é comparável entre empresas | comparar entre empresas só com `ST_CONTA_FIXA = 'S'` |
| 7 | **Encoding** | ver acima | ler como `latin-1` |

Contas de posição (BPA, BPP, DMPL) não acumulam — a armadilha 5 não se aplica a
elas.

## Regra de consulta

Nenhuma agregação sem, no mínimo:

```sql
WHERE is_latest
  AND ordem_exerc = 'ÚLTIMO'
  AND consolidado = TRUE   -- ou FALSE, mas nunca os dois na mesma soma
```

E, para ITR de contas de fluxo, decidir explicitamente entre acumulado e
trimestre isolado antes de somar.

## Neste repositório

`src/cvm_financas/` já implementa tudo acima:

- `config.py` — URLs, `GRUPOS` (com a marca `eh_fluxo`), colunas esperadas, `ESCALA_FATOR`
- `download.py` — busca dos ZIPs
- `parse.py` — parse, normalização e `marcar_versao_latest`
- `load.py` — `load_duckdb` / `load_postgres` / `schema_sql`
- `pipeline.py` — `executar()` → `ResultadoIngestao`
- `cli.py` — entry point `cvm-ingest`
- `sql/schema_postgres.sql` — `fato_conta`, view de consumo já filtrada, view de trimestre isolado

`tipo_doc` é derivado do nome do arquivo, não do argumento da CLI. A carga é
idempotente por `(cd_cvm, tipo_doc, dt_refer)`.

Reutilize essas funções em vez de reescrever o parsing.
