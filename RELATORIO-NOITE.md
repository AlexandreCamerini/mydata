# Relatório da noite — 2026-08-02/03

Execução autônoma do plano de implantação. Atualizado ao fim de cada etapa.

## Resultado

| Etapa | Situação |
|---|---|
| 0 — Produção com dado | **bloqueada** — depende do painel do Railway |
| 1 — Fechar o merge do scrap | **pronta** — 242 testes |
| 2 — Pesquisa que fecha decisão | **pronta** — 7 questões, `docs/pesquisa-mercado.md` |
| 3 — A lei | **pronta** — `docs/fundacao-de-dados.md` + ponteiro global |
| 4 — Contrato e normalização visíveis | **pronta** — 245 testes; verificação de tela pendente |
| 5 — Fonte nova pelo fluxo declarativo | em andamento |
| 6 — Correlação declarada | — |
| 7 — Gestão consolidada | — |
| 8 — Acesso público gratuito | — (último, por decisão do Alex) |

## O achado da noite

**A B3 veda redistribuição.** Os Termos de Uso proíbem "distribuição,
redistribuição […] reformatação, publicação a terceiros" e uso comercial sem
autorização prévia e por escrito, e a página do COTAHIST não tem regime próprio
que a dispense. Consequências:

1. **A etapa 5 trocou de fonte** — sai a B3, entra o Banco Central, que é dado
   aberto de verdade e prova o mesmo ponto: fonte nova é configuração.
2. **Preço virou decisão do Alex** — falar com a B3, ou aceitar uso interno.
3. **`empresa` já tem `ticker` e `segmento_listagem` vindos da B3.** Uso
   interno está amparado; publicá-los numa API pública, não. Precisa de decisão
   antes da etapa 8.

Em contrapartida, a **CVM é republicável**: o Decreto 8.777/2016 e o termo do
portal exigem citar a fonte e nada além. O núcleo do MyData está liberado, e a
proveniência que já emitimos é exatamente a citação exigida.

## Decisões que tomei sozinho

| # | Decisão | Por quê | Como reverter |
|---|---|---|---|
| 1 | Merge do `scrap` por subtree, não cópia | os quatro commits dele passam a ser história do MyData; cópia perderia autoria e data | `git revert 233093e` |
| 2 | `src/brapi_client/` achatado; pyproject, README e .gitignore do scrap removidos | `packages.find` já procura em `src/`; segundo pyproject dentro do repositório não é lido por ninguém | `git revert` do commit da etapa 1 |
| 3 | O `CLAUDE.md` do scrap virou `docs/fontes-terceiros.md` | a tabela de fonte primária e atraso era o conteúdo mais valioso dele, e um `CLAUDE.md` aninhado seria carregado como instrução naquele diretório | mesmo commit |
| 4 | brapi não será fonte de preço nem de fundamentos | preço é a B3 atrasada e sem arquivo original; fundamentos são a CVM, que já ingerimos na origem | rever `docs/fontes-terceiros.md` |
| 5 | O quinto caso do teste de decisão — dado que um terceiro pede e nenhum app do Alex usa | o MyData passou a ter consumidor fora de casa, e sem esse caso a lei não responderia à pergunta que a etapa 8 cria | rever `docs/fundacao-de-dados.md` § 2 |
| 6 | Ponteiro para a lei em `~/.claude/CLAUDE.md` | é o que faz "obrigatório" ser mecânico em vez de aspiracional; esse arquivo é global e não está neste repositório | remover a seção "Onde cada dado mora" |
| 7 | Contrato montado da configuração, nunca gravado | contrato guardado à parte é segunda declaração do mesmo fato, livre para divergir do que roda | — |
| 8 | Forma do contrato: subconjunto do ODCS, não do `contracts` do dbt | o dbt só carrega schema; ODCS carrega qualidade, SLA e versão, que é o que o consumidor precisa | rever `app/motor/contrato.py` |
| 9 | `version` do contrato é o inteiro da configuração, não semver | distinguir mudança que quebra exigiria comparar schemas entre versões, e não há caso concreto que pague isso | lacuna registrada em `docs/pesquisa-mercado.md` § Q6 |
| 10 | `physicalType` fora do contrato | depende do dialeto do sink; prometer tipo que muda entre DuckDB e Postgres seria promessa não cumprida | — |
| 11 | Etapa 5 troca B3 por Banco Central | ver "O achado da noite" | — |
| 12 | Não derrubei o processo na porta 8420 | o diretório de trabalho dele é o checkout principal, e `servidor.py status` o classifica como "DE OUTRO" | ver abaixo |

## Precisa do Alex

| # | O quê | Como desbloqueia |
|---|---|---|
| 1 | **Cron Schedule do `mydata-cron` nunca foi definido** — a primeira carga não rodou e o banco de produção provavelmente está vazio | painel do Railway, ou disparar pela tela de Execuções. Sugerido `0 11 * * *`: a CVM republica de manhã |
| 2 | **Processo órfão na porta 8420** — PID 19468, `cwd=/Users/acamerini/dev/cvm-financas`, subido com `uvicorn` direto. O checkout principal está em `8a57cc3`, sete commits atrás, então ele serve código anterior a toda a camada de apresentação | conferir e derrubar. É exatamente o caso que o `CLAUDE.md` descreve: pior que estar fora do ar, porque parece no ar. Bloqueou a verificação de tela da etapa 4b |
| 3 | **Preço: falar com a B3, ou desistir** | os termos vedam redistribuição. Sem autorização, preço só existe como uso interno |
| 4 | **`ticker` e `segmento_listagem` na API pública** | vieram da B3. Antes da etapa 8: retirar do escopo público, ou obter autorização |
| 5 | **Ler a ODbL na íntegra** antes de abrir ao público | a licença dos datasets da CVM é ODbL; falta saber se o *share-alike* alcança a API derivada e qual licença declarar para ela |
| 6 | Nada foi para o GitHub | `git push origin claude/mydata-handoff-3b2cc1:main` — dispara deploy |
| 7 | Teto de gasto no Railway (*Usage Limits*), com alerta em 75% | valor é decisão dele; é a rede de segurança final da etapa 8 |

## Evidência

### Etapa 1 — o merge fechado

```
$ .venv/bin/python -m pytest -q
242 passed in 28.52s
```

```
$ git log --oneline --graph -6
*   233093e O scrap entra no MyData com a história inteira
|\
| * d6edc88 Document brapi.dev's underlying data sources and update frequency
| * f2ba7a9 Add brapi_client: full API client for brapi.dev
| * 72083e9 Add CLAUDE.md scaffold documenting empty repo state
| * 8253872 Initial commit
* 0b12a18 As specs entram no repositório, inclusive a que já foi executada
```

### Etapa 3 — o teste de decisão

Quatro perguntas encadeadas, mais uma regra, resolvendo os cinco casos do meio.
Íntegra em `docs/fundacao-de-dados.md` § 2.

| Caso | Onde mora |
|---|---|
| P/L da Petrobras — indicador calculado | **MyData**, campo calculado |
| Score de qualidade do BolsIA | **App** — os pesos são juízo dele |
| Calendário de dividendos, só o BolsIA usa | **MyData** — nº de consumidores não entra na conta |
| Cópia local de `empresa` | **Cache** com validade, nunca fonte |
| CNPJ de registro cancelado, pedido por terceiro | **MyData** — o critério é a origem, não a demanda interna |

### Etapa 4 — contrato e original

```
$ .venv/bin/python -m pytest -q
245 passed in 26.52s
```

Três testes novos: o contrato mostra as duas origens de `denom_social` com a
precedência que decide; toda regra de qualidade declara se impede publicação;
classe inexistente devolve 404 com código nomeado.

```
$ npm run build
dist/assets/apresentacao-Cq3dGtRR.js   31.35 kB │ gzip: 9.17 kB
✓ built in 522ms
```

Verificação de tela pendente — ver "Precisa do Alex" nº 2.
