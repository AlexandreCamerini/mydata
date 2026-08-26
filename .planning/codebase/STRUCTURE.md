# Codebase Structure

**Analysis Date:** 2026-08-26
**Mapped commit:** `27b5f96`

## Directory Layout

```text
cvm-financas/
├── app/                    # portal MyData: API, catálogo, motor e persistência
│   ├── api/                # rotas públicas, admin, auth, acesso, proveniência, métricas
│   └── motor/               # ingestão, parsing, DDL, calculados, correlação, contrato,
│                             # custo, credenciais, verificação, qualidade, gold
├── src/                     # brapi_client (cliente REST isolado) — pacote legado removido
├── web/                     # React/Vite/TypeScript; admin e apresentação, um `dist/` só
├── scripts/                 # entrada Railway, servidor local, demo e carga histórica
├── tests/                   # pytest, fixtures sintéticas CVM e testes de API/motor
├── docs/                    # arquitetura, contratos, deploy, auditorias e decisões
├── .github/workflows/       # CI (push): pytest DuckDB+Postgres, build/test do front
├── .claude/skills/          # skills do projeto (dados-cvm: armadilhas da CVM)
├── .planning/codebase/      # este mapa gerado pelo GSD
├── dados/                   # DuckDB local (gitignored; dev/demo, não deploy)
├── Dockerfile               # build frontend + runtime Python
├── requisitos.txt           # dependências runtime do portal
├── pyproject.toml           # pacote cvm-financas, extras e pytest
└── railway.json              # builder/deploy/healthcheck Railway
```

## Directory Purposes

**`app/`:**
- Código ativo do portal. `app/api/main.py` concentra lifecycle, rotas `/v1`, static serving e autenticação de leitura.
- `app/api/admin.py` concentra o router `/admin/api`; `app/api/acesso.py` implementa passkeys/sessões; `app/api/metricas.py` é a DSL de indicadores fundamentalistas (`cfg_metrica`).
- `app/motor/` é o núcleo genérico. Além do pipeline de ingestão (`download.py` → `parsing.py` → `ingestao.py` → `calculados.py` → `qualidade.py` → `publicacao.py`), contém serviços derivados da configuração: `contrato.py` (contrato publicado, subconjunto de ODCS), `correlacao.py` (junção declarada entre classes), `custo.py` (medição física/financeira por execução), `credenciais.py` (resolução de `credencial_ref`), `verificacao.py` (digest de reprodutibilidade), `nucleos.py` (funções numéricas puras, ex. inversão de Black-Scholes para volatilidade implícita).
- `app/agenda.py` é o avaliador de expressão cron, usado por `cmd_agendados` do CLI e pela rota `/frescor`.
- `app/bootstrap.py` prepara o banco no boot (migração + DDL + ponteiros de gold), separado de `migracoes` para evitar ciclo de import.
- `app/seed_fontes.py` é a exceção deliberada: configuração da CVM/B3/BCB como dados, não como código do motor.

**`src/`:**
- `src/brapi_client/` é cliente REST isolado, não acoplado à API portal. É o único conteúdo restante em `src/` — o pacote legado `src/cvm_financas` (ingestão pandas, CLI `cvm-ingest`, `sql/schema_postgres.sql`) foi removido do repositório (commit `edbe034`, "Remove o pipeline CVM legado"). `pyproject.toml` ainda declara `[tool.setuptools.packages.find] where = ["src"]`, que hoje só encontra `brapi_client`.

**`web/`:**
- `web/src/telas/` contém console admin: classes, fontes, datasets, carga, qualidade, chaves, acesso, catálogo e API.
- `web/src/telas/Api.tsx` é um console OpenAPI zero-dependência (reescrito; a versão anterior usava o pacote `swagger-ui`, removido por completo). Lê `/openapi.json` em runtime, agrupa rotas por tag e oferece formulário de teste ao vivo para cada uma.
- `web/src/apresentacao/` contém busca, empresa, demonstrações, indicadores, negociação, arquivos e operação.
- `web/src/ui.tsx`, `objetos.tsx`, `api.ts` e `apresentacao/api.ts` concentram primitives, tipos, chamadas e regras de visualização.
- `web/vite.config.ts` define duas entradas de build (`index.html` admin, `apresentacao.html` apresentação) para o mesmo `dist/`, e proxy de dev para `/admin/api`, `/v1` e `/openapi.json` (este último adicionado para a tela API funcionar em `vite dev`, não só no build servido pelo FastAPI).

**`tests/`:**
- Fixtures compartilhadas em `tests/conftest.py` geram ZIP/CSV no layout real da CVM.
- Testes de integração API/motor usam `SinkDuckDB` em memória por padrão e podem usar `PORTAL_TESTE_POSTGRES`.

**`docs/`:**
- `docs/arquitetura.md` é a fonte de ADRs e riscos (ADR-10 a ADR-21+); `docs/contrato-consumidor.md` é a fronteira com consumidores; `docs/deploy-railway.md` descreve operação.

**`.github/workflows/`:**
- `ci.yml` roda em todo push: job `test` instala `-e ".[dev]"` e roda `python -m pytest -q` duas vezes (DuckDB por padrão, depois com `PORTAL_TESTE_POSTGRES` apontando para o serviço `postgres:16` do job); job `front` roda `npm ci`, `npm run build` e `npm test` em `web/`.

**`dados/`:**
- Arquivos `*.duckdb` de dev/demo (`demo.duckdb`, `mydata.duckdb`); gitignored, nunca é o armazenamento de produção (bronze mora em tabela Postgres, não em volume — ver ARCHITECTURE.md).

## Key File Locations

**Entry points:**
- `app/api/main.py` - FastAPI app e rotas `/v1`.
- `app/cli.py` - comandos operacionais.
- `scripts/entrada.sh` - web/cron no Railway.
- `web/src/main.tsx`, `web/src/apresentacao/main.tsx` - entradas React.
- `.github/workflows/ci.yml` - pipeline de CI.

**Configuration:**
- `.env.example` - contrato de variáveis.
- `pyproject.toml`, `requisitos.txt` - Python.
- `web/package.json`, `web/vite.config.ts`, `web/tsconfig.json` - frontend.
- `railway.json`, `Dockerfile` - deploy.

**Core logic:**
- `app/motor/ingestao.py` - orquestra captura → carga → calculados → qualidade → publicação.
- `app/motor/parsing.py` - transportes, regex, CSV, JSON e registros de largura fixa.
- `app/motor/ddl.py` - gera/verifica tabelas a partir de classes.
- `app/motor/publicacao.py` - ponteiros e versões gold.
- `app/motor/contrato.py`, `app/motor/correlacao.py`, `app/motor/custo.py`, `app/motor/credenciais.py`, `app/motor/verificacao.py` - serviços derivados da configuração (contrato, junção, custo, segredo, reprodutibilidade).
- `app/repositorio.py`, `app/migracoes.py`, `app/sinks.py` - catálogo, schema e banco.
- `app/agenda.py` - avaliador de cron para agendamentos.
- `app/seed_fontes.py` - fontes/datasets/classes/views de CVM, B3 e BCB.

**Testing:**
- `tests/test_api.py`, `tests/test_api_opcoes.py`, `tests/test_acesso.py` - superfícies HTTP e acesso.
- `tests/test_motor.py`, `tests/test_multifonte.py`, `tests/test_recomputo.py`, `tests/test_gerador_ddl.py`, `tests/test_correlacao.py`, `tests/test_credenciais.py`, `tests/test_nucleos.py` - pipeline/contrato/DDL/serviços derivados.
- `web/src/objetos.test.ts`, `web/src/apresentacao/regras.test.ts` - regras puras de UI.

## Naming Conventions

**Files:**
- Python e Markdown usam nomes descritivos em snake_case/kebab-case misturados por histórico (`app/motor/ingestao.py`, `docs/deploy-railway.md`).
- Componentes React usam PascalCase (`web/src/telas/ClasseForm.tsx`); testes usam `test_*.py` e `*.test.ts`.
- Arquivos de configuração importantes ficam na raiz (`README.md`, `CLAUDE.md`, `Dockerfile`).

**Code names:**
- Domínio e campos de dados em português (`fato_conta`, `vl_conta_norm`, `captura`); infraestrutura e APIs genéricas em inglês quando natural (`Sink`, `Request`, `StaticFiles`).
- Funções/variáveis Python usam snake_case; componentes/tipos TypeScript usam PascalCase e funções camelCase.

## Where to Add New Code

- Nova fonte/dataset/classe: configuração/seed em `app/seed_fontes.py` ou via rotas admin; não adicionar ramo específico no motor sem necessidade.
- Nova etapa genérica de dados: `app/motor/`, com teste em `tests/` e regra/observabilidade quando mudar publicação.
- Novo serviço derivado da configuração (algo que "monta, mas nunca grava"): seguir o padrão de `contrato.py`/`correlacao.py`/`custo.py` — ler `cfg_*` via `Sink`, nunca introduzir tabela nova de domínio.
- Nova rota pública: `app/api/main.py`; rota administrativa: `app/api/admin.py`; adicionar docstring e `description=` em `Query`/`Path` — é o que alimenta `/openapi.json` e, por consequência, a tela API do admin. Atualizar tipos/cliente em `web/src/api.ts` quando aplicável.
- Nova tela admin: `web/src/telas/`; nova tela de apresentação: `web/src/apresentacao/`; regras puras devem ser extraídas para `objetos.tsx`/módulo testável.
- Novo comportamento de segurança/acesso: manter `app/api/auth.py`/`acesso.py` como fontes compartilhadas, incluindo testes de regressão em `tests/test_acesso.py`.
- Não reintroduzir dependência de terceiro para o que o backend já publica (ex.: bibliotecas de UI para OpenAPI) sem justificar o ganho contra o custo de bundle — ver Anti-Patterns em ARCHITECTURE.md.

## Special Directories

**`dados/`:**
- Purpose: bancos DuckDB de desenvolvimento/demo.
- Generated: Yes (por `scripts/demo.py` e uso local).
- Committed: No (gitignored).

**`web/dist/`:**
- Purpose: build estático servido pelo FastAPI (`app/api/main.py`, `RAIZ_WEB`).
- Generated: Yes (`npm run build`, duas entradas: `index.html` admin, `apresentacao.html` apresentação).
- Committed: No (gitignored).

**`.claude/worktrees/`:**
- Purpose: worktree git paralelo usado por sessão de agente (`vibrant-stonebraker-910d98`), com cópia própria de `app/`, `web/`, `tests/` etc.
- Generated: Yes (git worktree).
- Committed: No — não faz parte da árvore de trabalho principal; ignorar ao mapear estrutura do repositório.

---

*Structure analysis: 2026-08-26*
