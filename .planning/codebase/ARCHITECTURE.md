# Architecture

**Analysis Date:** 2026-08-26
**Mapped commit:** `27b5f96`

## System Overview

```text
┌─────────────────────────────────────────────────────────────────────┐
│                    FastAPI process (Railway, 1 serviço)              │
├───────────────────────┬───────────────────────┬──────────────────────┤
│   `/v1/*` público      │  `/admin/api/*`        │   `/admin` estático   │
│  `app/api/main.py`     │  `app/api/admin.py`    │  `web/dist` (build)   │
│  auth por X-API-Key    │  auth por sessão/token │  React admin + apres.│
└───────────┬────────────┴───────────┬────────────┴──────────┬────────┘
            │                        │                        │
            ▼                        ▼                        ▼
┌─────────────────────────────────────────────────────────────────────┐
│              Control plane / catálogo declarativo                    │
│   `app/repositorio.py`, `app/migracoes.py`, `app/seed_fontes.py`     │
│   cfg_classe · cfg_atributo · cfg_fonte · cfg_dataset · cfg_regra_*   │
│   cfg_correlacao · cfg_tarifa · cfg_metrica · cfg_agendamento         │
└───────────┬────────────────────────────────────────────────┬────────┘
            │                                                  │
            ▼                                                  ▼
┌─────────────────────────────┐          ┌──────────────────────────────┐
│      Data engine             │          │   Serviços de domínio         │
│      `app/motor/`             │          │   `app/motor/contrato.py`     │
│  download → parsing →         │          │   `app/motor/correlacao.py`   │
│  ingestao → calculados →      │◄────────►│   `app/motor/custo.py`        │
│  qualidade → publicacao       │          │   `app/motor/verificacao.py`  │
│  `nucleos.py` (matemática)    │          │   `app/api/metricas.py`       │
└───────────────┬───────────────┘          └───────────────┬──────────────┘
                │                                            │
                ▼                                            ▼
┌─────────────────────────────────────────────────────────────────────┐
│                  Persistence — `app/sinks.py` (Protocol)             │
│              `SinkPostgres` (produção) · `SinkDuckDB` (dev/teste)     │
│  bronze_captura (imutável) → silver tipada → gold (vistas versionadas)│
└─────────────────────────────────────────────────────────────────────┘
```

## Component Responsibilities

| Component | Responsibility | File |
|-----------|----------------|------|
| API pública | Autentica `X-API-Key`, valida parâmetros, serve `/v1/*` e proveniência | `app/api/main.py` |
| API admin | Router `/admin/api`, CRUD de configuração, execuções, chaves, catálogo | `app/api/admin.py` |
| Métricas fundamentalistas | DSL `cfg_metrica`, pivô sobre `gold_demonstracoes` | `app/api/metricas.py` |
| Autenticação/acesso | Chaves de API, passkeys, sessão admin | `app/api/auth.py`, `app/api/acesso.py` |
| Proveniência | Anexa captura/linhagem/ETag às respostas | `app/api/proveniencia.py` |
| Catálogo/config | Fontes, datasets, classes, atributos, regras, agendamentos | `app/repositorio.py`, `app/migracoes.py`, `app/seed_fontes.py` |
| Bootstrap | Migração + DDL + ponteiros de gold no boot, idempotente | `app/bootstrap.py` |
| Agendamento | Avaliador de expressão cron sem dependência nova | `app/agenda.py` |
| Ingestão | Download, captura bronze com SHA-256, carga em lote | `app/motor/download.py`, `app/motor/ingestao.py` |
| Parsing | Transporte (CSV/JSON/largura fixa), regex, encoding, tipos | `app/motor/parsing.py` |
| Campos calculados | Materializa expressões SQL declaradas no catálogo | `app/motor/calculados.py` |
| Núcleos numéricos | Funções puras que expressão SQL não cobre (ex.: IV/Black-Scholes) | `app/motor/nucleos.py` |
| Qualidade | Avalia regras declarativas, pode bloquear publicação | `app/motor/qualidade.py` |
| DDL | Gera/verifica tabelas a partir de `cfg_classe`/`cfg_atributo` | `app/motor/ddl.py` |
| Publicação | Cria/promove/reverte vistas e ponteiros de gold, versionado | `app/motor/publicacao.py` |
| Contrato | Monta o contrato publicado de uma classe (subconjunto de ODCS), nunca grava | `app/motor/contrato.py` |
| Correlação | Junção declarada entre classes (`cfg_correlacao`), executada com escopo | `app/motor/correlacao.py` |
| Credenciais | Resolve `credencial_ref` para variável de ambiente; segredo nunca em `cfg_*` | `app/motor/credenciais.py` |
| Custo | Mede bytes/linhas por execução e deriva custo por `cfg_tarifa` | `app/motor/custo.py` |
| Verificação | Digest (linhas, sha256) de gold para provar reproduzibilidade do recomputo | `app/motor/verificacao.py` |
| Observabilidade | Logging/medição estruturado das execuções | `app/motor/observabilidade.py` |
| Persistência | Protocol comum para Postgres e DuckDB, staging e upsert | `app/sinks.py` |
| CLI operacional | `migrar`, `ingerir`, `agendados`, `recomputar`, `verificar`, `chave`, `status` | `app/cli.py` |
| Admin (React) | Console do operador: classes, fontes, datasets, carga, qualidade, chaves, acesso, catálogo, API | `web/src/telas/` |
| Apresentação (React) | Leitura navegável para consumidor humano | `web/src/apresentacao/` |

## Pattern Overview

**Overall:** Monólito full-stack metadata-driven, com API pública, console administrativo, apresentação pública e worker/cron no mesmo serviço/container Railway.

**Key Characteristics:**
- A classe de informação e seus datasets são configuração persistida; DDL, contrato e gold são consequências (`app/motor/ddl.py`, `app/motor/contrato.py`, `app/motor/publicacao.py`).
- Bronze é imutável; silver, calculados e gold são derivados e recomputáveis — `app/motor/verificacao.py` prova que o recomputo reproduz o estado.
- Um `Sink` (Protocol) oferece a mesma operação para Postgres e DuckDB.
- Junção entre classes é dado, não SQL escrito por quem consome (`app/motor/correlacao.py`, `cfg_correlacao`).
- Segredo nunca entra em configuração versionada: `cfg_fonte.credencial_ref` aponta para variável de ambiente (`app/motor/credenciais.py`).
- Frontend tem duas entradas de build: administração (`web/src/main.tsx`) e apresentação (`web/src/apresentacao/main.tsx`), no mesmo `web/dist`.
- A tela de API do admin (`web/src/telas/Api.tsx`) é um console OpenAPI zero-dependência: lê `/openapi.json` em runtime e documenta + testa cada rota ao vivo — não há geração estática nem pacote de terceiro (ver "Anti-Patterns").
- O pacote legado `src/cvm_financas` foi removido (commit `edbe034`); só `src/brapi_client/` permanece em `src/`, isolado e não acoplado ao motor.

## Layers

**Transport/API:**
- Purpose: autenticar, validar parâmetros, expor dados/proveniência e servir frontend.
- Location: `app/api/`
- Contains: `main.py` (rotas `/v1`, lifecycle, static serving), `admin.py` (router `/admin/api`), `auth.py`, `acesso.py` (passkeys/sessão), `proveniencia.py`, `metricas.py` (DSL de indicadores).
- Depends on: `bootstrap`, `repositorio`, `motor`, `sinks`.

**Control plane/catalog:**
- Purpose: armazenar fontes, datasets, classes, atributos, calculados, regras, correlações, tarifas, agendamentos, chaves e publicações.
- Location: raiz de `app/`
- Contains: `repositorio.py`, `migracoes.py`, `seed_fontes.py`, `bootstrap.py`.
- Used by: API, ingestão, DDL, publicação, correlação, custo e CLI.

**Data engine:**
- Purpose: baixar, capturar, parsear, carregar, calcular, validar e publicar.
- Location: `app/motor/`
- Contains: `download.py`, `parsing.py`, `ingestao.py`, `calculados.py`, `nucleos.py`, `qualidade.py`, `ddl.py`, `publicacao.py`, `paginacao.py`, `observabilidade.py`.
- Depends on: configuração do catálogo e `Sink`; não deve depender de nomes de fonte específicos (fonte nova é linha em `cfg_*`).

**Domain services (metadata-derived):**
- Purpose: montar leituras derivadas da configuração sem gravar estado novo — contrato, correlação, custo e verificação são todos "consequência", nunca fonte.
- Location: `app/motor/contrato.py`, `app/motor/correlacao.py`, `app/motor/custo.py`, `app/motor/credenciais.py`, `app/motor/verificacao.py`, `app/api/metricas.py`.
- Depends on: catálogo (`cfg_*`) e `Sink`.

**Scheduling:**
- Purpose: decidir se um agendamento está vencido, sem depender da frequência do processo que acorda.
- Location: `app/agenda.py`
- Used by: `app/cli.py cmd_agendados`, `app/api/admin.py` (leitura de `/frescor`).

**Persistence:**
- Purpose: traduzir tipos/placeholders e executar transações, staging, consultas e upserts.
- Location: `app/sinks.py`
- Contains: Protocol `Sink`, `SinkPostgres`, `SinkDuckDB`.

**Presentation:**
- Purpose: console do operador e leitura navegável para consumidor humano.
- Location: `web/src/telas/`, `web/src/apresentacao/`, `web/src/ui.tsx`, `web/src/objetos.tsx`.
- Depends on: endpoints FastAPI, `/openapi.json` (tela API) e sessão/chave conforme a superfície.

**Isolated client package:**
- Purpose: cliente REST para brapi, empacotado separadamente do motor.
- Location: `src/brapi_client/`
- Coexists with: pacote instalável `cvm-financas` (`pyproject.toml`), mas não é a camada do motor metadata-driven de `app/`. É a única coisa que resta em `src/` — o pacote legado `cvm_financas` foi removido.

## Data Flow

### Primary Request Path (leitura HTTP)

1. FastAPI inicia pelo lifecycle em `app/api/main.py:ciclo`, que chama `bootstrap.preparar` (migração + DDL + ponteiros de gold, idempotente).
2. Rota `/v1/*` resolve `X-API-Key`/sessão, quota e escopo (`app/api/auth.py`, `app/api/acesso.py`).
3. Handler consulta gold/catálogo via `Sink` e `repositorio`; rotas de correlação/contrato/métricas chamam `app/motor/correlacao.py`, `app/motor/contrato.py` ou `app/api/metricas.py`.
4. `app/api/proveniencia.py` e helpers de `main.py` acrescentam captura, linhagem, ETag e headers de quota.
5. FastAPI devolve JSON; `web/src/api.ts` ou `web/src/apresentacao/api.ts` traduz estados de carregamento/erro.

### Ingestão/publicação

1. Railway/CLI executa `scripts/entrada.sh` ou `python -m app.cli ingerir ...`; `app/cli.py cmd_agendados` usa `app/agenda.py` para decidir o que está vencido.
2. `app/motor/ingestao.py` lê configuração do dataset, resolve credencial via `app/motor/credenciais.py` quando a fonte exige, baixa a fonte e grava captura bronze com SHA-256.
3. `app/motor/parsing.py` interpreta transporte, regex, encoding, tipos e campos declarados.
4. `Sink.carregar_em_lote` usa staging e upsert pela chave natural.
5. `app/motor/calculados.py` materializa derivados declarados (SQL) e `app/motor/nucleos.py` resolve os que exigem método iterativo (ex.: volatilidade implícita); `qualidade.py` avalia regras.
6. `app/motor/custo.py` mede bytes/linhas da execução e grava relatório físico/financeiro.
7. Se não bloqueado, `app/motor/publicacao.py` recria/promove gold e registra versão/fases.

### Verificação/recomputo

1. `python -m app.cli recomputar` dropa e reconstrói silver/gold a partir do bronze, sem rede.
2. `app/motor/verificacao.py` reduz gold a um par `(linhas, sha256)` antes e depois; divergência gera código de saída 3.
3. `python -m app.cli verificar` imprime a digital atual sem mexer em nada.

### Console de API (admin)

1. `web/src/telas/Api.tsx` monta ao carregar a tela e faz `fetch("/openapi.json")`.
2. Agrupa operações por tag, resolve `$ref` de um nível e colapsa `anyOf` opcional do Pydantic v2 para exibir tipo legível.
3. Cada operação expande para formulário de parâmetros/corpo e executa a chamada real (`fetch` com `credentials: "same-origin"`); rotas `/admin/api/*` usam a sessão do navegador, rotas que exigem `X-API-Key` usam a chave colada na tela.

**State Management:**
- Estado durável é banco; sessão admin é linha em `sessao_admin` + cookie.
- Configuração é versionada/append-only por `versao`, `vigente` e `vigente_chave`.
- Captura bronze nunca é sobrescrita; recomputação parte dela sem rede (`app/motor/ingestao.py`, `app/motor/verificacao.py`).
- Estado de UI da tela API (`Api.tsx`) é local ao componente (chave de API em memória, resposta da última chamada); nada é persistido no cliente.

## Key Abstractions

**Classe de informação:**
- Representa o que consumidor pergunta (`empresa`, `demonstracao_financeira`, `negociacao_b3`, etc.).
- `cfg_classe`/`cfg_atributo` orientam DDL, gold, escopo e contrato.

**Dataset/fonte:**
- Descreve transporte, URL, colunas de origem, chave natural e política de versão.
- Novas fontes devem entrar em `cfg_*`/seed, não como ramo novo do motor.

**Correlação declarada:**
- `cfg_correlacao` define quais classes se juntam, por quais atributos e com que cardinalidade; sem linha correspondente a travessia é recusada. Nunca há inferência (`app/motor/correlacao.py`).

**Contrato:**
- Montado sob demanda a partir de `cfg_atributo`, `cfg_coluna`, `cfg_campo_calculado` e `cfg_regra_qualidade`; nunca gravado — evitaria uma segunda declaração do mesmo fato (`app/motor/contrato.py`).

**Credencial por referência:**
- `cfg_fonte.credencial_ref` guarda o nome da variável de ambiente, nunca o segredo (`app/motor/credenciais.py`).

**Sink:**
- Protocol em `app/sinks.py`; factories selecionam `SinkPostgres` ou `SinkDuckDB`.

**Publicação:**
- Vistas/ponteiros de gold são versionados e reversíveis em `app/motor/publicacao.py`.

**Impressão digital (verificação):**
- Par `(linhas, sha256)` de gold, comparável entre execuções; ignora o rótulo de publicação de propósito (`app/motor/verificacao.py`).

## Entry Points

- `app/api/main.py:app` - aplicação FastAPI/Uvicorn; monta `admin.router` em `/admin/api` e static em `/admin`.
- `scripts/entrada.sh` - entrada Railway para web ou cron.
- `app/cli.py` - comandos `migrar`, `ingerir`, `agendados`, `recomputar`, `verificar`, `chave`, `status`.
- `web/src/main.tsx` e `web/src/apresentacao/main.tsx` - raízes React (dois `rollupOptions.input` em `web/vite.config.ts`: `index.html` e `apresentacao.html`).
- `.github/workflows/ci.yml` - pipeline de CI (push): testes Python contra DuckDB e Postgres, build + teste do frontend.

## Architectural Constraints

- **Threading:** processo único ASGI (uvicorn); sem worker pool próprio — paralelismo de ingestão é por execução de dataset, não por thread interna.
- **Global state:** `app.state.sink` é a única instância de `Sink` por processo, criada no lifespan (`app/api/main.py:ciclo`); CLI cria seu próprio `Sink` por invocação.
- **Serviço único:** API pública, admin e static do front compartilham processo e deploy — decisão de custo Railway, não limitação técnica. Ver `CLAUDE.md` (regra de custo).
- **Sem geração de cliente:** o console de API não gera SDK nem tipos a partir do OpenAPI; é leitura + execução ao vivo, não codegen.

## Anti-Patterns

### Dependência de terceiro para o que o próprio backend já publica

**What happens:** a primeira versão da tela de API (`web/src/telas/Api.tsx`) embutia o pacote `swagger-ui`, que precisou de dois remendos por incompatibilidade com React 19 (cópia duplicada de React, `createRoot` ausente) e inflou o bundle do admin em 15×.
**Why it's wrong:** o `/openapi.json` que o FastAPI já gera contém tudo que a tela precisa (rotas, parâmetros, schemas); um pacote de terceiro genérico paga o custo de cobrir a especificação inteira para usar uma fração dela.
**Do this instead:** parser próprio, pequeno, que cobre só o que este OpenAPI de fato usa (parâmetros de rota/query/header, corpo com `$ref` de um nível) — `web/src/telas/Api.tsx`. Documentação e teste vêm da mesma fonte (`/openapi.json`), então nunca desalinham do que está de fato exposto.

### Tabela de domínio escrita à mão

**What happens:** criar `CREATE TABLE` de domínio numa migração em vez de declarar a classe.
**Why it's wrong:** a tabela física é consequência da classe (`cfg_classe`/`cfg_atributo` → `app/motor/ddl.py`); uma tabela escrita à mão diverge do catálogo e quebra recomputo/verificação.
**Do this instead:** declarar a classe/atributo em configuração (via `app/seed_fontes.py` ou rota admin) e deixar `motor.ddl` gerar o DDL.

## Error Handling

**Strategy:** erros de domínio sobem como exceções até fronteiras de API/CLI; API normaliza `HTTPException` em `{erro:{codigo,mensagem,detalhe}}`.

**Patterns:**
- Falhas de parsing/qualidade são registradas na execução e podem bloquear publicação.
- `app/cli.py` transforma `ErroIngestao` em código de saída; agendamentos isolam falhas por dataset; `recomputar` usa código de saída 3 especificamente para divergência de digital.
- `RequestValidationError` tem tratamento dedicado para `/v1/chaves` em `app/api/main.py:tratar_validacao`, para devolver mensagem de domínio em vez do erro genérico do Pydantic.
- Frontend humaniza 401/429/5xx em `web/src/apresentacao/api.ts` e exibe estados explícitos; a tela API (`Api.tsx`) mostra status HTTP bruto e corpo formatado por chamada, sem reinterpretar o erro.

## Cross-Cutting Concerns

**Logging:** `app/motor/observabilidade.py`.
**Validation:** Pydantic nas rotas FastAPI; regras declarativas de qualidade em `app/motor/qualidade.py`.
**Authentication:** `app/api/auth.py` (chave de API/quota/escopo), `app/api/acesso.py` (passkeys/sessão admin), CORS/configuração em `app/api/main.py`.
**Proveniência:** `app/api/proveniencia.py`, `app/motor/contrato.py`, colunas de origem nas vistas.
**Integridade:** triggers Postgres para bronze, regras declarativas de qualidade, `app/motor/verificacao.py`.
**Self-documentation da API:** `app/api/main.py` e `app/api/admin.py` carregam docstring e `description=` em `Query`/`Path` para quase toda rota — o `/openapi.json` resultante é a única fonte que alimenta a tela de API do admin; documentar a rota é o mesmo trabalho que alimentar o console de teste.

---

*Architecture analysis: 2026-08-26*
