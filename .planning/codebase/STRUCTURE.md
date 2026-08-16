# Codebase Structure

**Analysis Date:** 2026-08-16
**Mapped commit:** `cce3c61`

## Directory Layout

```text
Datamart/
├── app/                    # portal MyData: API, catálogo, motor e persistência
│   ├── api/                # rotas públicas, admin, auth, acesso e proveniência
│   └── motor/              # ingestão, parsing, DDL, calculados, qualidade, gold
├── src/                    # pacote legado cvm_financas e cliente brapi
├── web/                    # React/Vite/TypeScript; admin e apresentação
├── scripts/                # entrada Railway, servidor local, demo e carga histórica
├── tests/                  # pytest, fixtures sintéticas CVM e testes de API/motor
├── docs/                   # arquitetura, contratos, deploy, auditorias e decisões
├── .planning/codebase/     # este mapa gerado pelo GSD
├── Dockerfile              # build frontend + runtime Python
├── requisitos.txt          # dependências runtime do portal
├── pyproject.toml          # pacote cvm-financas, extras e pytest
└── railway.json            # builder/deploy/healthcheck Railway
```

## Directory Purposes

**`app/`:**
- Código ativo do portal. `app/api/main.py` concentra lifecycle, rotas `/v1`, static serving e autenticação de leitura.
- `app/api/admin.py` concentra o router `/admin/api`; `app/api/acesso.py` implementa passkeys/sessões.
- `app/motor/` é o núcleo genérico; `app/seed_fontes.py` é a exceção deliberada de configuração da CVM como dados.

**`src/`:**
- `src/cvm_financas/` é o pacote original de ingestão pandas, CLI `cvm-ingest` e `sql/schema_postgres.sql`.
- `src/brapi_client/` é cliente REST isolado, não acoplado à API portal.

**`web/`:**
- `web/src/telas/` contém console admin: classes, fontes, datasets, carga, qualidade, chaves, acesso, catálogo e API.
- `web/src/apresentacao/` contém busca, empresa, demonstrações, indicadores, negociação, arquivos e operação.
- `web/src/ui.tsx`, `objetos.tsx`, `api.ts` e `apresentacao/api.ts` concentram primitives, tipos, chamadas e regras de visualização.

**`tests/`:**
- Fixtures compartilhadas em `tests/conftest.py` geram ZIP/CSV no layout real da CVM.
- Testes de integração API/motor usam `SinkDuckDB` em memória por padrão e podem usar `PORTAL_TESTE_POSTGRES`.

**`docs/`:**
- `docs/arquitetura.md` é a fonte de ADRs e riscos; `docs/contrato-consumidor.md` é a fronteira com consumidores; `docs/deploy-railway.md` descreve operação.

## Key File Locations

**Entry points:**
- `app/api/main.py` - FastAPI app e rotas.
- `app/cli.py` - comandos operacionais.
- `scripts/entrada.sh` - web/cron no Railway.
- `web/src/main.tsx`, `web/src/apresentacao/main.tsx` - entradas React.

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
- `app/repositorio.py`, `app/migracoes.py`, `app/sinks.py` - catálogo, schema e banco.
- `app/seed_fontes.py` - fontes/datasets/classes/views de CVM, B3 e BCB.

**Testing:**
- `tests/test_api.py`, `tests/test_api_opcoes.py`, `tests/test_acesso.py` - superfícies HTTP e acesso.
- `tests/test_motor.py`, `tests/test_multifonte.py`, `tests/test_recomputo.py`, `tests/test_gerador_ddl.py` - pipeline/contrato/DDL.
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
- Nova rota pública: `app/api/main.py`; rota administrativa: `app/api/admin.py`; atualizar tipos/cliente em `web/src/api.ts` quando aplicável.
- Nova tela admin: `web/src/telas/`; nova tela de apresentação: `web/src/apresentacao/`; regras puras devem ser extraídas para `objetos.tsx`/módulo testável.
- Novo comportamento de segurança/acesso: manter `app/api/auth.py`/`acesso.py` como fontes compartilhadas, incluindo testes de regressão em `tests/test_acesso.py`.

---

*Structure analysis: 2026-08-16*
