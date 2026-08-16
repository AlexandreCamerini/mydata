# Technology Stack

**Analysis Date:** 2026-08-16
**Mapped commit:** `cce3c61`

## Languages

**Primary:**
- Python 3.10+ - API FastAPI, CLI, motor de ingestão, sinks, migrações e seed em `app/`.
- TypeScript/TSX - frontend React em `web/src/`.

**Secondary:**
- SQL - migrações renderizadas para Postgres/DuckDB, DDL metadata-driven e vistas em `app/migracoes.py`, `app/motor/ddl.py` e `app/seed_fontes.py`.
- Shell - entrada Docker/Railway em `scripts/entrada.sh`.
- HTML/CSS - páginas estáticas e estilos do frontend em `web/`.

## Runtime

**Backend:**
- Python 3.12-slim em produção (`Dockerfile`); código declara compatibilidade com Python `>=3.10` em `pyproject.toml`.
- Uvicorn serve `app.api.main:app`.

**Frontend:**
- Node 24 Alpine apenas no estágio de build do `Dockerfile`.
- Browser executa o bundle Vite estático servido pelo FastAPI.

**Package managers:**
- `pip`/setuptools para o pacote Python; `requisitos.txt` é o runtime enxuto do portal e `pyproject.toml` define o pacote `cvm-financas` e extras.
- npm com `web/package-lock.json` para o frontend.

## Frameworks

**Core:**
- FastAPI + Uvicorn - HTTP, OpenAPI, lifecycle e serving de estáticos (`app/api/main.py`).
- Pydantic 2 - modelos de payload administrativo (`app/api/admin.py`).
- React 19 + Vite 7 + TypeScript 5.7 - duas superfícies do portal (`web/src/App.tsx`, `web/src/apresentacao/App.tsx`).
- Tailwind 4 via `@tailwindcss/vite` e CSS próprio em `web/src/index.css`/`web/src/temas.css`.

**Testing:**
- pytest - suíte Python em `tests/`.
- Vitest 4 - testes de regras e objetos em `web/src/*.test.ts` e `web/src/apresentacao/regras.test.ts`.
- axe CLI - auditoria de acessibilidade via script `a11y` em `web/package.json`.

## Key Dependencies

- `psycopg[binary]` - conexão Postgres e `COPY` de staging em `app/sinks.py`.
- DuckDB - sink local/teste e fallback quando `DATABASE_URL` não existe; importado sob demanda em `app/sinks.py`.
- `requests` - downloads de CVM/B3/BCB e cliente separado `src/brapi_client/`.
- `webauthn` - passkeys e verificação de registro/autenticação em `app/api/acesso.py`.
- `pandas` - pipeline legado `src/cvm_financas/`; não faz parte do runtime enxuto do portal.
- `react`/`react-dom` - UI administrativa e apresentação pública.

## Configuration

**Environment:**
- Variáveis documentadas em `.env.example`: `DATABASE_URL`, `PORTAL_DUCKDB`, `PORT`, `PORTAL_ADMIN_TOKEN`, `PORTAL_ACESSO_LEGADO`, `PORTAL_API_ABERTA`, `PORTAL_MIGRAR_NO_BOOT`, `PORTAL_URL_PUBLICA` e `PORTAL_ORIGENS`.
- O sink escolhe Postgres quando há `DATABASE_URL`; caso contrário usa arquivo DuckDB (`app/sinks.py`).

**Build/deploy:**
- `Dockerfile` faz build multi-stage do frontend e copia `web/dist` para a imagem Python.
- `railway.json` usa builder Docker, healthcheck `/health` e `scripts/entrada.sh` como start command.
- `web/vite.config.ts` e `web/tsconfig.json` definem o build TypeScript/Vite.

## Platform Requirements

**Development:**
- Python com dependências de `requisitos.txt` e `pyproject.toml`; Node/npm para build/teste do frontend.
- DuckDB permite execução local sem banco externo; `scripts/servidor.py` padroniza a porta local 8420.

**Production:**
- Um serviço/container no Railway roda API, frontend e, em outro papel, cron de ingestão.
- Postgres do Railway é o banco de produção; o filesystem do container é tratado como efêmero.

---

*Stack analysis: 2026-08-16*
