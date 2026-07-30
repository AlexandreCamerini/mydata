# Portal de Dados / cvm-financas

Portal de API de dados de empresas listadas na B3, com plano de controle
configurável. Consumidor inicial: BOLSIA (análise fundamentalista). A primeira
fonte é a CVM Dados Abertos, e o ingestor dela já existe aqui.

- Arquitetura e definição do sistema: [docs/arquitetura.md](docs/arquitetura.md)
- Brief de construção, por fases: [prompt-portal-dados-otimizado.md](prompt-portal-dados-otimizado.md)

## Stack (decidido — mudar só aqui)

| Dimensão | Decisão |
|---|---|
| Backend | Python 3.10+, FastAPI + uvicorn |
| Frontend | React + Vite + TypeScript + Tailwind + shadcn/ui, build estático servido pelo FastAPI (um serviço só) |
| Hospedagem | Railway: API, front e cron de ingestão no mesmo projeto |
| Banco | Postgres do Railway, dentro do que o plano já inclui. DuckDB em arquivo só para dev local e testes |
| Agendamento | Cron do Railway, não runner externo |
| Auth | Chave de API por consumidor, hash em repouso, quota por chave |

**Regra de custo:** nada além do que o plano do Railway já inclui. Serviço
gerenciado de terceiros, add-on ou tier pago precisa de aprovação antes de
entrar no código — vale para banco, fila, storage, observabilidade e qualquer
outra decisão de infraestrutura.

## O dado

Imutável é **o arquivo oficial que a CVM publicou** (bronze): gravado intacto,
com hash SHA-256, URL e timestamp de captura; nunca reescrito, nunca apagado.
É a única cópia que não dá para reconstruir — a URL da CVM é endereço mutável,
regerado a cada reapresentação, então rebaixar não reproduz a captura.

Bronze mora na tabela `bronze_captura` (`bytea`), não em volume nem em disco:
o filesystem do container é efêmero e o volume do Railway monta em um serviço
só. Imutabilidade é imposta por trigger, não por convenção
([ADR-10](docs/arquitetura.md#adr-10--bronze-em-tabela-não-em-volume)).

Tudo que o portal deriva — silver tipado, campos calculados, views gold — é
descartável por construção. **Dropar e recomputar do bronze é a rotina normal
de correção**, não um último recurso. Se recomputar não reproduzir o estado do
banco, existe um bug: alguma coisa entrou por fora do pipeline.

Campos calculados vivem em catálogo declarativo e declaram as colunas de origem
que usam. Um que não consiga declarar isso falha na validação, não na carga.

Um hook `PreToolUse` bloqueia escrita em `bronze/` e DDL contra as tabelas de
captura. Ele não atrapalha nada em silver/gold — se você foi bloqueado, o alvo
era dado oficial.

## Comandos

```bash
pip install -e ".[dev]"            # ambiente
pytest -q                          # testes
cvm-ingest --print-schema          # DDL
cvm-ingest --dry-run --anos 2023   # pipeline sem rede
uvicorn app.main:app --reload      # API local
npm run build                      # front
```

## Armadilhas da CVM

A skill `dados-cvm` carrega as sete armadilhas do dado (reapresentação,
`ORDEM_EXERC`, escala, con/ind, ITR acumulado, contas custom, encoding) e a
regra de consulta. Ela dispara sozinha ao mexer em demonstrações financeiras —
não reescreva o parsing do pacote, reutilize `cvm_financas`.

Resumo operacional: nenhuma agregação sem filtrar `is_latest`,
`ordem_exerc = 'ÚLTIMO'` e um único valor de `consolidado`.

## Convenções

- Domínio contábil em português (`fato_conta`, `vl_conta_norm`); infraestrutura
  em inglês.
- Carga idempotente pela chave natural declarada em `cfg_dataset`.
- Toda resposta de dado carrega proveniência: `fonte`, `dt_captura`,
  `versao_documento`, `calculado_em`.
- Um commit por fase concluída.
