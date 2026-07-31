# Portal de Dados / cvm-financas

Hub multi-fonte de informação sobre companhias da B3, com plano de controle
configurável e API que abastece os apps do Alex. Raiz pública:
`https://acamerini.app/`. Primeiro consumidor: BOLSIA (análise
fundamentalista). Primeira fonte: CVM Dados Abertos.

- Arquitetura e definição do sistema: [docs/arquitetura.md](docs/arquitetura.md)
- O que depende do painel do Railway: [docs/deploy-railway.md](docs/deploy-railway.md)
- Brief das fases 1–5: [prompt-portal-dados-otimizado.md](prompt-portal-dados-otimizado.md)
- Brief do hub multi-fonte: [prompt-hub-multifonte-otimizado.md](prompt-hub-multifonte-otimizado.md)

## Stack (decidido — mudar só aqui)

| Dimensão | Decisão |
|---|---|
| Backend | Python 3.10+, FastAPI + uvicorn |
| Frontend | React + Vite + TypeScript + Tailwind, build estático servido pelo FastAPI (um serviço só) |
| Hospedagem | Railway: API, front e cron de ingestão no mesmo projeto |
| Banco | Postgres do Railway, dentro do que o plano já inclui. DuckDB em arquivo só para dev local e testes |
| Agendamento | Cron do Railway, não runner externo |
| Auth | Chave de API por consumidor, hash em repouso, quota e escopo por classe |

**Regra de custo:** nada além do que o plano do Railway já inclui. Serviço
gerenciado de terceiros, add-on ou tier pago precisa de aprovação antes de
entrar no código — vale para banco, fila, storage, observabilidade e qualquer
outra decisão de infraestrutura.

## Classe de informação é o conceito central

Uma **classe** é a coisa sobre a qual o portal guarda dado — Empresa,
Demonstração financeira, Cotação. Ela tem atributos, chave de identidade e é
alimentada por N mapeamentos (`cfg_dataset`), cada um lendo uma fonte.

A tabela física é **consequência** da classe, não código: `motor.ddl` gera
DDL a partir de `cfg_classe`/`cfg_atributo`, e `cfg_vista` guarda o corpo das
vistas de gold. Não existe `CREATE TABLE` de domínio em migração — se você
está prestes a escrever um, a classe é que devia declarar aquilo
([ADR-11](docs/arquitetura.md#adr-11--a-tabela-como-consequência-da-classe)).

**Engine único:** `app/motor/`, `app/api/` e `app/migracoes.py` não sabem o
que é CVM. Fonte nova é linha em `cfg_*`, nunca linha em `app/`.
`app/seed_cvm.py` é a única exceção, porque ele é dado.

Duas fontes na mesma classe **coexistem**: `origem_dataset` faz parte da
identidade física, e a linha publicada sai de uma vista que escolhe por
precedência declarada **por atributo**. Reordenar precedência é republicar,
não recarregar
([ADR-12](docs/arquitetura.md#adr-12--resolução-multi-fonte-é-derivação-não-sobrescrita)).

## O dado

Imutável é **o arquivo oficial que a fonte publicou** (bronze): gravado
intacto, com hash SHA-256, URL e timestamp de captura; nunca reescrito, nunca
apagado. É a única cópia que não dá para reconstruir — a URL da CVM é endereço
mutável, regerado a cada reapresentação, então rebaixar não reproduz a captura.

Bronze mora na tabela `bronze_captura` (`bytea`), não em volume nem em disco:
o filesystem do container é efêmero e o volume do Railway monta em um serviço
só. Imutabilidade é imposta por trigger, não por convenção
([ADR-10](docs/arquitetura.md#adr-10--bronze-em-tabela-não-em-volume)).

Tudo que o portal deriva — silver tipado, campos calculados, vistas de gold —
é descartável por construção. **Dropar e recomputar do bronze é a rotina
normal de correção**, não um último recurso. `python -m app.cli recomputar`
faz isso e compara a digital de gold antes e depois; código de saída 3
significa que o recomputo não reproduziu o estado, ou seja, alguma coisa
entrou no banco por fora do pipeline.

Campos calculados vivem em catálogo declarativo e declaram as colunas de
origem que usam. Um que não consiga declarar isso falha na validação, não na
carga.

Um hook `PreToolUse` bloqueia escrita em `bronze/` e DDL contra as tabelas de
captura. Ele não atrapalha nada em silver/gold — se você foi bloqueado, o alvo
era dado oficial.

## Comandos

```bash
pip install -e ".[dev]"                 # ambiente
pytest -q                               # testes
python scripts/demo.py                  # base local com dado de exemplo
python -m app.cli migrar --seed         # migrações + configuração (idempotente)
python -m app.cli ingerir cvm_dfp 2023  # uma janela, com rede
python -m app.cli recomputar            # refaz tudo do bronze e verifica
python -m app.cli verificar             # digital de gold, sem mexer em nada
python -m app.cli chave app --classe empresa   # chave com escopo
uvicorn app.api.main:app --reload       # API local
npm run build                           # front (em web/)
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
- Carga idempotente pela identidade da classe mais `origem_dataset`.
- Toda resposta de dado carrega proveniência: `fonte`, `dt_captura`,
  `versao_documento`, `publicacao` — e `por_atributo` quando a classe tem mais
  de uma fonte disputando o mesmo campo.
- Um commit por etapa concluída.
