# External Integrations

**Analysis Date:** 2026-08-16
**Mapped commit:** `cce3c61`

## APIs & External Services

**CVM Dados Abertos:**
- Fonte canônica de DFP/ITR e cadastro de companhias.
- URLs, encoding `latin-1`, separador `;`, regex de arquivos e mapeamentos vivem como configuração em `app/seed_cvm.py`.
- Downloads HTTP são executados por `app/motor/download.py`; o ZIP/CSV capturado é guardado em bronze com hash e URL por `app/motor/ingestao.py`.

**B3:**
- Endpoint JSON de companhias listadas em `app/seed_cvm.py`, paginado por `app/motor/paginacao.py`; `codeCVM` liga a companhia B3 à CVM.
- COTAHIST diário e cadastro consolidado de instrumentos entram como fontes configuradas para `fato_negociacao`/`dim_instrumento`; o contrato documentado os trata como uso pessoal em `docs/fontes-terceiros.md` e `docs/arquitetura.md`.

**Banco Central (SGS):**
- Séries públicas CDI, Selic, IPCA e câmbio são declaradas no seed em `app/seed_cvm.py` e carregadas pelo transporte HTTP JSON.

**brapi.dev:**
- Cliente REST isolado em `src/brapi_client/client.py`, com exceções específicas em `src/brapi_client/exceptions.py`.
- É dependência de terceiro/agregador, não a origem oficial das classes principais; as decisões de uso e limites estão em `docs/fontes-terceiros.md`.

## Data Storage

**PostgreSQL:**
- Banco de produção, conectado por `DATABASE_URL` e implementado por `SinkPostgres` em `app/sinks.py`.
- Migrações portáveis ficam em `app/migracoes.py`; operações específicas de Postgres, como triggers e PL/pgSQL, ficam em `so_postgres`.
- `COPY` para tabela temporária `_stg_carga` e upsert em lote aceleram ingestões.

**DuckDB:**
- `SinkDuckDB` em `app/sinks.py` é fallback local e backend padrão dos testes.
- Pode usar `:memory:` ou `PORTAL_DUCKDB`; não é o banco de produção.

**Bronze:**
- Arquivo oficial é armazenado como binário na tabela de captura, não em volume/disco, conforme `app/migracoes.py` e `docs/arquitetura.md`.

## Authentication & Identity

**Consumidores da API:**
- Chaves de API são emitidas por `app/api/auth.py`/`app/cli.py`, armazenadas como hash e limitadas por quota e escopo de classe.
- Rotas `/v1` usam `X-API-Key` via dependência `exigir_chave` em `app/api/main.py`; `PORTAL_API_ABERTA=1` é exceção de desenvolvimento.

**Administração:**
- `PORTAL_ADMIN_TOKEN`/`X-Admin-Token` protegem escrita administrativa em `app/api/admin.py`.
- Navegador usa sessão em cookie e passkeys WebAuthn; registro/desafio/verificação estão em `app/api/acesso.py` e `app/api/auth.py`.

## Monitoring & Observability

- Não há SDK externo de erro/analytics/metrics.
- Logs vão para stdout via `logging` no CLI e módulos do motor.
- Execuções, fases, frescor, quotas e impressão digital de gold são persistidos no banco por `app/motor/observabilidade.py`, `app/motor/verificacao.py` e `app/repositorio.py`.
- Railway usa `/health` em `railway.json`; acessibilidade é verificada sob demanda pelo comando `npm run a11y`.

## CI/CD & Deployment

**Hosting:**
- Railway constrói `Dockerfile`, inicia `scripts/entrada.sh` e usa `/health` como healthcheck.
- `PORTAL_PAPEL=web` inicia Uvicorn; `PORTAL_PAPEL=cron` aplica migração/seed e executa `python -m app.cli agendados`.

**CI pipeline:**
- Nenhum workflow GitHub Actions ou configuração CI foi encontrado no checkout.
- Validação é explicitamente executável por `pytest -q`, `npm run build`, `npm test` e `npm run a11y`.

## Environment Configuration

- Desenvolvimento usa `.env` local ignorado, DuckDB e `PORTAL_API_ABERTA` opcional.
- Produção espera variáveis no painel Railway; nenhum segredo deve entrar no repositório.
- CORS é negado por omissão e configurado por lista explícita em `PORTAL_ORIGENS`.

## Webhooks & Callbacks

- Nenhum webhook externo de entrada/saída foi encontrado.
- O cron do Railway é o disparador externo de processo; a decisão de vencimento do agendamento é feita internamente em `app/agenda.py`.

---

*Integration audit: 2026-08-16*
