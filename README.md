# mydata

Hub de dados com ingestão declarativa das fontes oficiais, incluindo as
demonstrações financeiras DFP/ITR da CVM, para DuckDB local ou Postgres.

## Instalação

```bash
pip install -e ".[dev]"
```

## Uso

```bash
python -m app.cli migrar --seed
python -m app.cli ingerir cvm_dfp 2023
python -m app.cli recomputar
python -m app.cli verificar
python scripts/servidor.py subir
```

O motor executa o ciclo baixar → bronze → parsear → silver → campos
calculados → qualidade → gold. A CVM é uma configuração em
`app/seed_fontes.py`, não um pipeline Python separado.

## Estrutura

```
mydata/
├── app/
│   ├── motor/          # ingestão, parsing, DDL, qualidade e publicação
│   ├── api/            # API FastAPI
│   └── seed_fontes.py  # configuração declarativa das fontes
├── scripts/            # entrada do serviço e utilitários locais
├── tests/              # suíte do motor, API e fontes
└── web/                # front-end estático
```

## As armadilhas da CVM

As sete armadilhas — reapresentação, `ORDEM_EXERC`, escala, con/ind, ITR
acumulado, contas custom e encoding — estão declaradas em
`app/seed_fontes.py`, nos comentários `# Armadilha N`. O parsing comum fica em
`app/motor/parsing.py`; as regras de qualidade ficam em
`app/motor/qualidade.py`.

Nenhuma agregação deve ocorrer sem filtrar `is_latest`,
`ordem_exerc = 'ÚLTIMO'` e um único valor de `consolidado`.

## Testes

```bash
python -m pytest -q
```
