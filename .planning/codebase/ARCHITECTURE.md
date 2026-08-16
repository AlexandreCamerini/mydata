# Architecture

**Analysis Date:** 2026-08-16
**Mapped commit:** `cce3c61`

## Pattern Overview

**Overall:** Monólito full-stack metadata-driven, com API pública, console administrativo, apresentação pública e worker/cron no mesmo serviço/container.

**Key Characteristics:**
- A classe de informação e seus datasets são configuração persistida; DDL e gold são consequências (`app/motor/ddl.py`, `app/motor/publicacao.py`).
- Bronze é imutável; silver, calculados e gold são derivados e recomputáveis.
- Um `Sink` oferece a mesma operação para Postgres e DuckDB.
- Frontend tem duas entradas: administração (`web/src/main.tsx`) e apresentação (`web/src/apresentacao/main.tsx`).

## Layers

**Transport/API:**
- Purpose: autenticar, validar parâmetros, expor dados/proveniência e servir frontend.
- Contains: `app/api/main.py`, `app/api/admin.py`, `app/api/auth.py`, `app/api/acesso.py`, `app/api/proveniencia.py`.
- Depends on: `repositorio`, `motor`, `sinks`.

**Control plane/catalog:**
- Purpose: armazenar fontes, datasets, classes, atributos, calculados, regras, agendamentos, chaves e publicações.
- Contains: `app/repositorio.py`, `app/migracoes.py`, `app/seed_fontes.py`.
- Used by: API, ingestão, DDL, publicação e CLI.

**Data engine:**
- Purpose: baixar, capturar, parsear, carregar, calcular, validar e publicar.
- Contains: `app/motor/download.py`, `parsing.py`, `ingestao.py`, `calculados.py`, `qualidade.py`, `ddl.py`, `publicacao.py`, `paginacao.py`, `observabilidade.py`.
- Depends on: configuração do catálogo e `Sink`; não deve depender de nomes de fonte específicos.

**Persistence:**
- Purpose: traduzir tipos/placeholders e executar transações, staging, consultas e upserts.
- Contains: `app/sinks.py`.

**Presentation:**
- Purpose: console do operador e leitura navegável para consumidor humano.
- Contains: `web/src/telas/`, `web/src/apresentacao/`, `web/src/ui.tsx`, `web/src/objetos.tsx`.
- Depends on: endpoints FastAPI, OpenAPI e sessão/chave conforme a superfície.

**Legacy package:**
- Purpose: entregável independente para ingestão CVM com pandas e schema próprio.
- Contains: `src/cvm_financas/`.
- Coexists with portal tests, mas não é a camada usada pelo motor metadata-driven de `app/`.

## Data Flow

**HTTP de leitura:**

1. FastAPI inicia pelo lifecycle em `app/api/main.py` e chama `bootstrap.preparar`.
2. Rota `/v1/*` resolve `X-API-Key`/sessão, quota e escopo.
3. Handler consulta gold/catalog via `Sink` e `repositorio`.
4. `app/api/proveniencia.py` e helpers de `main.py` acrescentam captura, linhagem, ETag e headers de quota.
5. FastAPI devolve JSON; `web/src/api.ts` ou `web/src/apresentacao/api.ts` traduz estados de carregamento/erro.

**Ingestão/publicação:**

1. Railway/CLI executa `scripts/entrada.sh` ou `python -m app.cli ingerir ...`.
2. `app/motor/ingestao.py` lê configuração do dataset, baixa a fonte e grava captura bronze com SHA-256.
3. `app/motor/parsing.py` interpreta transporte, regex, encoding, tipos e campos declarados.
4. `Sink.carregar_em_lote` usa staging e upsert pela chave natural.
5. `app/motor/calculados.py` materializa derivados declarados; `qualidade.py` avalia regras.
6. Se não bloqueado, `app/motor/publicacao.py` recria/promove gold e registra versão/fases.

**State Management:**
- Estado durável é banco; sessão admin é linha em `sessao_admin` + cookie.
- Configuração é versionada/append-only por `versao`, `vigente` e `vigente_chave`.
- Captura bronze nunca é sobrescrita; recomputação parte dela sem rede (`app/motor/ingestao.py`).

## Key Abstractions

**Classe de informação:**
- Representa o que consumidor pergunta (`empresa`, `demonstracao_financeira`, `negociacao_b3`, etc.).
- `cfg_classe`/`cfg_atributo` orientam DDL, gold, escopo e contrato.

**Dataset/fonte:**
- Descreve transporte, URL, colunas de origem, chave natural e política de versão.
- Novas fontes devem entrar em `cfg_*`/seed, não como ramo novo do motor.

**Sink:**
- Protocol em `app/sinks.py`; factories selecionam `SinkPostgres` ou `SinkDuckDB`.

**Publicação:**
- Vistas/ponteiros de gold são versionados e reversíveis em `app/motor/publicacao.py`.

## Entry Points

- `app/api/main.py:app` - aplicação FastAPI/Uvicorn.
- `scripts/entrada.sh` - entrada Railway para web ou cron.
- `app/cli.py` - comandos `migrar`, `ingerir`, `agendados`, `recomputar`, `verificar`, `chave`, `status`.
- `src/cvm_financas/cli.py` - entry point instalado `cvm-ingest` do pacote legado.
- `web/src/main.tsx` e `web/src/apresentacao/main.tsx` - raízes React.

## Error Handling

**Strategy:** erros de domínio sobem como exceções até fronteiras de API/CLI; API normaliza `HTTPException` em `{erro:{codigo,mensagem,detalhe}}`.

**Patterns:**
- Falhas de parsing/qualidade são registradas na execução e podem bloquear publicação.
- `app/cli.py` transforma `ErroIngestao` em código de saída; agendamentos isolam falhas por dataset.
- Frontend humaniza 401/429/5xx em `web/src/apresentacao/api.ts` e exibe estados explícitos.

## Cross-Cutting Concerns

- Logging/medição: `app/motor/observabilidade.py`.
- Proveniência: `app/api/proveniencia.py`, `app/motor/contrato.py`, colunas de origem nas vistas.
- Segurança: `app/api/auth.py`, `app/api/acesso.py`, CORS/configuração em `app/api/main.py`.
- Integridade: triggers Postgres para bronze, regras declarativas de qualidade e `verificacao.impressao_digital`.

---

*Architecture analysis: 2026-08-16*
