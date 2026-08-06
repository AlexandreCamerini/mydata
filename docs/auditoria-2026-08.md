# Auditoria de leitura — MyData, 2026-08-03

Auditoria somente-leitura. Nenhum código foi alterado. Todas as afirmações
saem de comando executado, com a saída colada. O que não foi possível
verificar está marcado como tal.

**Ponto de observação:** o clone local está em `8a57cc3`, **67 commits atrás**
de `origin/main`. A auditoria trata `origin/main` como a verdade e lê por
`git show origin/main:<caminho>`, sem tocar na árvore.

---

## Veredito

1. **Nada se perdeu.** Dois candidatos foram investigados até o fim; os dois
   chegaram a `origin/main` por outro caminho.
2. O backlog está **muito à frente** do que o clone local mostra: a camada de
   apresentação existe, o formulário de classe existe, e entraram fontes de
   mercado que não estavam previstas.
3. O front quadruplicou — de 12 para 31 arquivos, de 1.915 para 8.493 linhas.
4. **Achado mais grave:** nenhum. O mais relevante é operacional — trabalhar a
   partir de um clone 67 commits atrás produziu, nesta mesma sessão, um
   diagnóstico inteiro sobre premissas falsas.
5. Com a árvore sincronizada: **486 testes verdes em 117s** e **build do front
   limpo**. Nenhuma afirmação desta auditoria ficou por verificar.

---

## 1. Algo se perdeu?

**Não.** Dois candidatos, ambos resolvidos.

### Candidato A — branch remota não mesclada

```
$ git branch -a --no-merged origin/main
  remotes/origin/railway/fix-deploy-784ea0

$ git log --oneline origin/main..origin/railway/fix-deploy-784ea0
3e34513 fix: use BOOL_OR for boolean columns in sql_vista_resolvida
        autor: railway-app[bot]   data: 2026-08-01   app/motor/ddl.py
```

A correção troca `MAX` por `BOOL_OR` ao agregar coluna booleana na vista
resolvida — `max(boolean)` não existe no Postgres, embora o DuckDB aceite.

**Chegou por outro caminho:**

```
$ git show origin/main:app/motor/ddl.py | rg -c "BOOL_OR"
2
$ git show origin/main:app/motor/ddl.py | rg -c "MAX\(CASE"
0
```

Alarme falso. A branch é resíduo; o conteúdo está em `main`.

### Candidato B — commit pendurado

```
$ git fsck --lost-found
dangling commit 57d1c9810a37b34b21549e78830db8e5f50d839f

$ git log -1 57d1c98
57d1c98  2026-08-03  WIP on claude/mydata-handoff-3b2cc1
         app/seed_cvm.py | 12 +++---  tests/test_multifonte.py | 28 ++++
```

Corrige um defeito real: a precedência era declarada com a chave da **fonte**
(`"b3"`) e é casada contra `origem_dataset`, que é a chave do **mapeamento**
(`"b3_listadas"`). Nome que não casa cai para o fim da fila sem erro — sintoma
invisível.

**Chegou por outro caminho:**

```
$ rg -c 'precedencia=\["b3"\]'          → 0
$ rg -c 'precedencia=\["b3_listadas"\]' → 5
$ rg -c "test_precedencia_nomeia_mapeamento_e_nao_fonte" → 1
```

A correção e o teste que a protege estão em `origin/main`.

### O que não é problema

| Verificação | Resultado |
|---|---|
| `git worktree list` | 3 worktrees, **todas sem alteração não commitada** |
| `git stash list` | vazio |
| `git log --all --not origin/main` | 1 commit (candidato A, resolvido) |
| Árvore local | 1 arquivo não rastreado, **byte a byte idêntico** ao de `origin/main` |
| `docs/fundacao-de-dados.md` | **existe** em `origin/main` — o ponteiro do `CLAUDE.md` global está íntegro |

Arquivos apagados em `origin/main` (`git log --diff-filter=D`): apenas
reestruturação do `src/brapi_client/` e a remoção de `web/tsconfig.tsbuildinfo`,
que é artefato de build. Nenhuma perda.

---

## 2. O que a aplicação é hoje

### Inventário (`origin/main`)

| Área | Arquivos | Linhas |
|---|---|---|
| `app/` | 31 | 9.688 |
| `web/src/` | 31 | 8.493 |
| `tests/` | 31 | 7.442 |
| `docs/` | 9 | 2.600 |
| `scripts/` | 4 | 493 |

Contra o clone local (67 commits atrás): `app/` 24→31, `web/src/` 12→31,
`tests/` 15→31.

### Front — as duas camadas existem

**Apresentação** (`web/src/apresentacao/`, não existia no clone local):
`Busca`, `Empresa`, `Ficha`, `Demonstracoes`, `Indicadores`, `Negociacao`,
`Operador`, `Arquivos`, mais `api.ts` e `regras.test.ts`.

**Administração** — 13 telas (eram 8):

| Tela | Linhas | Escreve |
|---|---|---|
| `DatasetForm` | 590 | sim |
| `ClasseForm` | 452 | sim |
| `Classes` | 402 | leitura |
| `Acesso` | 303 | sim |
| `Execucoes` | 294 | sim |
| `Gestao` | 290 | leitura |
| `Calculados` | 286 | sim |
| `Carga` | 212 | leitura |
| `Chaves` | 212 | sim |
| `Fontes` | 165 | sim |
| `Datasets` | 160 | leitura |
| `Qualidade` | 140 | leitura |
| `Catalogo` | 119 | leitura |

`ClasseForm` e `DatasetForm` existem e escrevem: **criar classe de informação
pela interface deixou de ser promessa e virou tela.**

### Superfície HTTP

57 rotas declaradas no código, 23 sob `/v1`. Produção publica **52 caminhos**
em `openapi.json`, com `servers` apontando para `https://mydata.acamerini.app`.
A diferença de 5 é compatível com rotas marcadas `include_in_schema=False`;
não foi confirmada rota a rota.

Entraram em `/v1` desde o clone local: `cotacoes/{ticker}`,
`opcoes/{ticker}`, `opcoes/{ticker}/vencimentos`, `correlacoes/{chave}`,
`capturas/{id}`, `capturas/{id}/arquivo`, `empresas/{cd_cvm}/resumo`,
`meta/contrato`, `meta/carga`, `meta/correlacoes`, `meta/execucoes`.

### Fontes e classes configuradas

`b3`, `b3_cotahist`, `b3_instrumentos`, `b3_listadas`, `b3_serie_historica`,
`bcb`, `brapi`, `cvm`, `cvm_cadastro`, `cvm_dfp`, `cvm_dfp_empresa`,
`cvm_itr` — mais as classes `demonstracao_financeira`, `empresa`,
`empresa_demonstracoes` e as vistas `gold_cotacoes`, `gold_demonstracoes`,
`gold_indicadores`, `gold_itr_trimestre`, `gold_opcoes`.

### Verificação dinâmica — feita após `git pull --ff-only`

```
$ git log --oneline -1
ffb17c9 Redesenho da apresentação, camada de acesso e o cadastro de instrumentos da B3

$ .venv/bin/python -m pytest -q
486 passed in 116.94s (0:01:56)
```

**486 testes, nenhuma falha.** Contra os 199 do clone anterior — a suíte mais
que dobrou junto com o código.

O build falhou na primeira tentativa, por `node_modules` desatualizado nesta
máquina — não por defeito no código. `vitest ^4.1.10` estava declarado em
`web/package.json` e ausente da instalação local; o `Dockerfile` roda `npm ci`
antes do build, e o deploy em produção havia concluído. Após `npm install`:

```
$ npm run build
✓ 57 modules transformed
dist/assets/apresentacao-BHGdiWnU.js    48,93 kB │ gzip: 14,30 kB
dist/assets/admin-C57j7tIB.js           83,43 kB │ gzip: 21,06 kB
dist/assets/index-ElIvK6DV.js          209,07 kB │ gzip: 65,48 kB
✓ built in 673ms
```

Os dois pontos de entrada — `index.html` e `apresentacao.html` — saem em
bundles separados: a apresentação pública não carrega o código do admin.

### Dependências que entraram desde `8a57cc3`

| Onde | O quê | Por quê |
|---|---|---|
| `requisitos.txt`, `pyproject.toml` | `webauthn>=2.0` | passkey ([ADR-19](arquitetura.md)) |
| `web/package.json` | `vitest ^4.1.10` + script `test` | o front ganhou teste unitário — `regras.test.ts`, `objetos.test.ts` |
| `web/package.json` | `a11y` passa a varrer 6 rotas na porta 8420 | antes era uma rota só, na 8000 |

---

## 3. Onde o backlog está

### Specs

| Spec | Linhas | Situação |
|---|---|---|
| `prompt-portal-dados-otimizado.md` | 174 | entregue (fases 1–5) |
| `prompt-hub-multifonte-otimizado.md` | 164 | entregue (etapas 0–7), ADR-11 a 17 |
| `prompt-apresentacao-otimizado.md` | 135 | **entregue** — `apresentacao/` e os dois formulários existem |
| `prompt-fonte-publica-otimizado.md` | 261 | entregue em parte — ADR-18, 20; `bcb`, `brapi`, COTAHIST no seed |
| `prompt-redesign-portal-otimizado.md` | 307 | entregue — commit `ffb17c9` "Redesenho da apresentação" |
| `prompt-fundacao-dados-otimizado.md` | 209 | entregue — `docs/fundacao-de-dados.md` existe |

Cobertura por teste não foi mapeada spec a spec: exigiria rodar a suíte.

### ADRs

Nove registrados em `docs/arquitetura.md`: ADR-10, 11, 12, 16, 17, 18, 19, 20,
21. Os cinco últimos são posteriores ao clone local:

- **ADR-18** — COTAHIST sob uso pessoal; a classe é negociação
- **ADR-19** — passkey ao lado do token, não no lugar
- **ADR-20** — cadastro de instrumentos como classe própria
- **ADR-21** — bronze comprimido pelo Postgres, não pela aplicação

### Questões em aberto

| # | Questão | Situação |
|---|---|---|
| 1 | Origem do mapa ticker → `cd_cvm` | **resolvida em silêncio** — `b3_listadas` no seed (10 ocorrências) e ADR-20; o texto da questão continua como se estivesse aberta |
| 2 | Multi-tenant | aberta |
| 3 | Gate sobre linha já publicada | aberta |
| 4 | Bronze duplicado entre mapeamentos | aberta — ADR-21 trata compressão, não duplicação |
| 5 | Mapeamento lê mais do que precisa | aberta |

### Testes que entraram

16 arquivos novos: `test_acesso`, `test_api_opcoes`, `test_brapi_client`,
`test_campo_numerico`, `test_correlacao`, `test_cotahist`, `test_credenciais`,
`test_escopo_da_escrita`, `test_fonte_bcb`, `test_instrumentos`,
`test_largura_fixa`, `test_migracao_incremental`, `test_nucleos`,
`test_relatorio_carga`, `test_sessao_admin`, mais `autenticador.py`.

---

## Achados

| Severidade | Achado | Evidência | Impacto | O que fazer |
|---|---|---|---|---|
| Média | Questão em aberto nº 1 resolvida sem baixa | `b3_listadas` no seed + ADR-20, texto inalterado | Leitor do documento acredita que falta a ligação ticker→`cd_cvm` | Fechar a questão citando o ADR |
| Média | Clone local 67 commits atrás | `git status -sb` | Diagnóstico feito sobre ele fica falso; ocorreu nesta sessão | **resolvido** — `git pull --ff-only`, suíte e build verdes |
| Baixa | Branch `railway/fix-deploy-784ea0` órfã | `--no-merged`, conteúdo já em `main` | Ruído; sugere trabalho pendente que não existe | Apagar a branch remota |
| Baixa | Commit pendurado `57d1c98` | `git fsck`, conteúdo já em `main` | Nenhum — some na próxima coleta | Nada |
| Baixa | 5 rotas no código sem correspondência óbvia no `openapi.json` | 57 no código, 52 publicadas | Provavelmente `include_in_schema=False` | Conferir rota a rota se importar |
| Informativa | `brapi` figura como fonte | `chave="brapi"` no seed | O produto existe para não pagar integrador, e `brapi` é um | Ler `docs/fontes-terceiros.md`, que provavelmente registra a decisão |
| Informativa | Duas worktrees paradas | `git worktree list`, ambas limpas | Consomem disco | Remover quando não forem mais usadas |

---

*Auditoria de leitura. As únicas ações executadas foram as autorizadas ao
final — `git pull --ff-only`, `pytest`, `npm install`, `npm run build` — e
estão registradas acima com a saída. Nenhum achado foi corrigido por ela.*
