# Codebase Concerns

**Analysis Date:** 2026-08-26
**Mapped commit:** `27b5f96`

## Tech Debt

**Pipeline CVM legado: removido, não mais uma preocupação ativa.**
- Estado anterior (2026-08-16): `src/cvm_financas/` coexistia com `app/motor`.
- Estado atual: removido em `edbe034` (2026-08-16) — código morto confirmado (não copiado no `Dockerfile`, não instalado por `requisitos.txt`, não importado por `app/`); as sete armadilhas já estavam reimplementadas declarativamente em `app/seed_fontes.py`. `app/motor/` é o único caminho de ingestão.
- Resíduo local, não um problema de repositório: `src/cvm_financas/__pycache__` e `src/cvm_financas.egg-info` continuam no disco deste checkout (bytecode/artefato de build antigos, não rastreados pelo git — `git ls-files src/cvm_financas` não lista nada). Sem impacto funcional; `rm -rf` limpa se incomodar.

**Seed extenso como fonte de configuração:**
- Issue: `app/seed_fontes.py` (1.497 linhas) concentra definições de fontes, classes, views, calculados e agendamentos para CVM, BCB e B3.
- Impact: revisão e evolução são difíceis; um erro no seed pode mudar versões/DDL/gold no boot.
- Fix approach: mudanças devem ser idempotentes, cobertas por testes de seed/DDL e verificadas com `migrar --seed` antes do deploy.

**Trabalho de dedup de bronze por conteúdo, parado em stash desde antes de 2026-08-23:**
- Issue: `git stash list` mostra `stash@{0}: On main: wip: dedup bronze por conteudo` (commit-base `83808b8`, criado entre `ac8026c` e `7687417`, portanto anterior a toda a onda de commits de 06–23/08). Nunca foi retomado.
- Conteúdo do stash: `app/migracoes.py` ganha a migração `0018_bronze_por_conteudo`, que separa `bronze_captura` (evento de captura, com URL/proveniência) de uma nova tabela `bronze_blob` (conteúdo endereçado por `sha256`, chave primária, imutável por trigger própria). `app/motor/ingestao.py` ajusta `gravar_bronze` para gravar o payload em `bronze_blob` e a captura apenas referenciar o hash. Resolveria a questão 4 do §14 (dois mapeamentos sobre o mesmo arquivo duplicando bytes).
- Impact: nenhum código em `app/` hoje referencia `bronze_blob` — `grep -rn "bronze_blob" app/ tests/` não retorna nada; a ideia só existe no stash. O trabalho não afeta o estado atual do banco, mas fica invisível para quem não sabe que o stash existe (não aparece em `git log`, não há branch nem issue apontando para ele).
- Motivo do bloqueio, segundo o handoff: uma `DependencyException` do DuckDB durante a migração — não há vestígio disso em código ou teste hoje (a migração nunca chegou a rodar em CI/local o suficiente para deixar rastro), então o diagnóstico exato precisa ser refeito ao retomar.
- Fix approach: antes de aplicar, decidir se `stash pop` ainda é seguro (checar se `app/migracoes.py`/`app/motor/ingestao.py` divergiram desde `83808b8` — não divergiram até `27b5f96`, conferido por diff de contexto), reproduzir a `DependencyException` isoladamente (provavelmente ordem de `DROP`/`ALTER` num teste DuckDB in-memory) antes de tentar de novo, e cobrir com teste que grava duas capturas do mesmo conteúdo por mapeamentos diferentes.

**API grande em módulos centrais:**
- `app/api/main.py` cresceu para aproximadamente 1.516 linhas (era ~1.414); `app/api/admin.py` continua em aproximadamente 933.
- Impact: alterações em auth, erro, static serving ou contratos podem afetar muitas superfícies; exige teste de integração direcionado.

## Known Risks / Bugs

**Comparação do token de admin não normaliza espaço em branco antes de `hmac.compare_digest`:**
- Evidence: `app/api/auth.py:33-42` (`admin_ok`) compara `valor` (do cabeçalho `X-Admin-Token`, do cookie legado, ou — via `app/api/main.py:1415-1438`, rota `POST /entrar` — do campo `token` de um formulário `urlencoded` parseado com `parse_qs`) diretamente contra `os.getenv("PORTAL_ADMIN_TOKEN")`, sem `.strip()` nem qualquer normalização de nenhum dos dois lados. `tests/test_deploy.py:72-73` verifica que `PORTAL_ADMIN_TOKEN` não está vazio usando `.strip()`, mas só para essa checagem de presença — o valor usado em produção pela comparação real não passa por esse strip.
- Impact: um token colado com espaço/quebra de linha à frente ou atrás — seja no valor submetido pelo formulário de login, seja na variável de ambiente definida no painel do Railway (ex.: copiado de um arquivo com newline final) — falha a comparação byte-a-byte e devolve "Token inválido.", sem nenhuma pista de que a causa é whitespace e não o valor em si. Houve um relato de falha de login administrativo em produção recentemente com essa hipótese como suspeita mais provável; não foi confirmada, e este é o ponto de código exato onde a falta de normalização tornaria essa hipótese possível.
- Fix approach: `valor.strip()` (e, se a variável for definida por arquivo/CI, `esperado.strip()`) antes do `compare_digest`; ou validar/normalizar na leitura da env var, uma vez, em vez de em cada request.

**Anomalia de ponteiro de branch em `main`: não reprodutível no estado atual.**
- Contexto verificado (2026-08-26): checado `git log --oneline -20`, `git reflog show HEAD/main/origin/main` (histórico completo, não só as últimas entradas) e `git fsck --unreachable --no-reflogs`. `main` e `origin/main` estão sincronizados em `27b5f96`, sem push forçado, sem entrada de `reset`/`rebase` em nenhum reflog local. `git fsck` encontra 3 commits dangling, mas são resíduo de auto-stash antigo (`WIP on claude/mydata-handoff-3b2cc1` / `index on ...`, base `9aabd31`) e um commit isolado de `railway-app[bot]` ("fix: use BOOL_OR for boolean columns") — nenhum corresponde a uma cadeia de 5 commits que teria caído da ponta de `main`.
- Verdict: se o evento de fast-forward reverso aconteceu, ele não deixou rastro neste checkout hoje — `main` local está à frente do que qualquer reflog capturado sugere ter sido perdido, e nada está inalcançável a partir de `origin/main`. Tratar como resolvido/não reproduzido; não é necessário investigar mais a menos que reapareça (nesse caso, capturar `git reflog` e `git fsck` **no momento do incidente**, antes de qualquer novo fetch/pull apagar a evidência por expiração do reflog).

**CVM não é fonte estável de layout:**
- Risk: mudança de encoding, colunas, nomes de arquivo, escala ou valores de `ORDEM_EXERC` pode produzir carga incompleta/errada.
- Current mitigation: colunas obrigatórias, regex, regras declarativas em `app/seed_fontes.py` e fixtures sintéticas.
- Safe change: adicionar fixture do novo layout e regra bloqueadora antes de liberar ingestão.

**Ausência de gates automatizados: fechada.**
- Estado anterior (2026-08-16): sem CI, sem formatter/linter, sem coverage.
- Estado atual: `.github/workflows/ci.yml` (commit `de14195`) roda a suíte Python duas vezes (DuckDB, depois Postgres via serviço `postgres:16` com `PORTAL_TESTE_POSTGRES`) e o build+teste do front (`npm run build`, `npm test`) em todo push. Comando padronizado para `python -m pytest -q` em `27b5f96` — sem esse `-m`, `app/` não entra em `sys.path` (não está em `src/`) e a suíte falha por import. Ainda não há linter/formatter nem threshold de coverage configurados.

## Security Considerations

**Backup do bronze: risco aceito conscientemente, não ausência por omissão.**
- Risk: `bronze_captura` é "a única cópia que não dá para reconstruir" (`CLAUDE.md`) — a URL da CVM é endereço mutável, então uma perda de volume sem backup é perda permanente.
- Estado medido em produção (2026-08-16, RELATORIO-NOITE.md): `railway postgres pitr status` retornou `enabled: false` — não há backup contínuo (PITR) do Postgres de produção. Custo de habilitar é baixo (proporcional à escrita: ~4,9 MB/dia medidos, não ao volume total de 50 GB provisionados). O volume em si não é mais uma preocupação (a hipótese de "cresce sem parar" do mapeamento anterior era especulativa; com número, décadas de margem no provisionamento atual).
- Decisão: Alex optou por não habilitar PITR agora, risco de perda total aceito conscientemente. Reabrir se a taxa de escrita mudar de ordem de grandeza (nova fonte de alto volume, aumento de frequência) ou se o apetite a risco mudar — não é um item pendente de implementação, é uma decisão já tomada com números na mesa.

**Rotação de segredo em produção, e a superfície de exposição que a motivou:**
- Em 2026-08-16, `PORTAL_ADMIN_TOKEN` foi rotacionado em produção porque o valor antigo apareceu na tela durante um diagnóstico com `railway variables --kv` (comando que imprime valores de variável em claro no terminal). O valor novo foi setado via stdin, sem exposição, e o serviço redeployou (`8b4c79b7`).
- Recommendation: evitar `railway variables --kv` (ou equivalente que imprime segredo em claro) em sessões com output logado/compartilhado; preferir setar por stdin/arquivo sem eco. Nenhuma mudança de código resolve isso — é disciplina operacional — mas vale registrar porque é o mesmo token cuja comparação (`admin_ok`) não normaliza whitespace: um valor colado a partir de um terminal/log que introduziu quebra de linha na cópia é exatamente o cenário que o item de "Known Risks" acima descreve.

**Segredos e superfícies de desenvolvimento:**
- Risk: `PORTAL_API_ABERTA=1` libera `/v1`; ausência de `PORTAL_ADMIN_TOKEN` deixa admin aberto em dev.
- Current mitigation: `tests/test_deploy.py` (commit `aca7b89`) falha o deploy se `PORTAL_API_ABERTA` estiver ativa ou `PORTAL_ADMIN_TOKEN` estiver vazio/ausente em produção — guarda automatizada, não só documentação.
- Recommendation: como notado acima, essa checagem usa `.strip()` só para validar presença, não para normalizar o valor efetivamente comparado em `admin_ok`; considerar se vale unificar.

**Passkey e recuperação de acesso:**
- Risk: perda do único autenticador pode bloquear o administrador; `PORTAL_ACESSO_LEGADO=1` reabre token como saída de emergência.
- Current mitigation: sessões no servidor, desafios de uso único, origem/RP ID e possibilidade de registrar segundo autenticador em `app/api/acesso.py`.
- Safe change: testar sempre registro, login, revogação, expiração e recuperação em `tests/test_acesso.py`; não persistir credencial em frontend/localStorage.

**COTAHIST/cadastro B3:**
- Risk: dados B3 têm restrição de redistribuição documentada (Termos de Uso proíbem "distribuição").
- Current mitigation: classes e contrato identificam uso pessoal e escopo por chave; `docs/fontes-terceiros.md` registra a decisão; `tests/test_api_opcoes.py` (commit `aca7b89`) tem regressão explícita de que `ticker`/`segmento_listagem` não vazam pelo escopo público.
- Recommendation: não expor essas vistas como classe pública nem tratar agregador brapi como origem oficial sem nova decisão. A decisão de negócio sobre publicar isso na etapa 8 continua aberta — não é lacuna de código, é decisão pendente do Alex.

**BRAPI_TOKEN: fechado, não é mais uma superfície de risco ativa.**
- Estado anterior: pendência registrada como "a razão original já não existe" (mapa ticker→empresa foi resolvido sem o brapi — `b3_listadas` já traz `codeCVM`/`issuingCompany` no mesmo registro). Fechado em `ccf9349` (2026-08-16).
- Estado atual: `src/brapi_client/` continua no repositório e é referenciado por `app/seed_fontes.py` e `app/motor/credenciais.py`, mas sem carga ativa hoje — `BRAPI_TOKEN` não precisa ser definido. Único uso pendente de decisão: dividendos (cadência/escopo ainda em aberto, `docs/fontes-terceiros.md`).

## Performance Bottlenecks

**Carga:**
- `app/sinks.py` documenta que upsert linha a linha era cerca de 300 linhas/s e staging/COPY chega a aproximadamente 9.300 linhas/s.
- O staging temporário é ponto crítico: manter a chave natural, `_ord` e descarte da tabela ao alterar carga em lote.

**Cálculos de negociação:**
- `app/motor/nucleos.py` inclui Black-Scholes/solução iterativa; `app/seed_fontes.py` usa calculados e joins contra histórico.
- `web/src/apresentacao/Negociacao.tsx` (514 linhas) usa janela virtualizada para cadeias grandes; mudanças devem preservar a regra de não renderizar todos os contratos no DOM.

## Fragile Areas

**DDL metadata-driven:**
- Why fragile: tabela física, atributos, vistas e publicação precisam permanecer alinhados.
- Common failures: coluna órfã, atributo novo ausente, schema sem gold ou divergência de dialeto.
- Safe modification: usar prévia/divergências em `app/motor/ddl.py`/`app/api/admin.py`, testar `tests/test_gerador_ddl.py` e evitar DROP destrutivo.

**Multi-fonte e precedência:**
- Why fragile: identidade inclui `origem_dataset`, mas gold resolve por atributo; alterar precedência muda publicação sem nova captura.
- Safe modification: preservar `por_atributo`, testes em `tests/test_multifonte.py` e possibilidade de reverter publicação.

**Migração de dedup de bronze parada em stash (ver Tech Debt):**
- Why fragile: se alguém rodar `git stash pop` sem revisar o diff contra o `app/migracoes.py` atual, corre o risco de aplicar uma migração nunca validada contra a `DependencyException` que a bloqueou originalmente, potencialmente contra um banco de produção já mudado desde `83808b8`.
- Safe modification: revisar o diff completo (`git stash show -p stash@{0}`) e reproduzir a migração isolada em DuckDB in-memory antes de `stash pop`; não aplicar direto em produção.

**Porta/processos locais:**
- Why fragile: vários serviços ocupam portas na máquina.
- Safe modification: usar `scripts/servidor.py`, porta 8420 e nunca matar processo apenas pelo número da porta.

**API grande em módulos centrais:** ver Tech Debt.

## Scaling Limits

- Bronze binário em Postgres é simples e auditável; medido em produção (16 dias, 2026-08-16) em ~4,9 MB/dia, décadas de margem contra os 50 GB provisionados — não é mais um limite prático de curto/médio prazo, mas continua sem backup contínuo (ver Security Considerations).
- Um único serviço Railway hospeda API, frontend e cron; ingestão pesada pode competir por CPU/memória com requisições se o isolamento operacional não for respeitado.
- `dim_instrumento` é documentada como potencialmente grande (dezenas/centenas de milhares de instrumentos por fotografia); reter cada dia exige acompanhamento de volume.

## Test Coverage Gaps

- Não há E2E de navegador automatizado para login/passkey, redirecionamentos, apresentação pública e console admin. A verificação de tela e a auditoria `axe` das etapas 4b/7 ficaram pendentes desde o relatório de 02–03/08 e não há evidência de terem sido feitas depois.
- Build TypeScript não prova funcionamento de rede/rotas; `web/src/apresentacao/regras.test.ts` documenta defeitos que só apareceram olhando tela e aba de rede.
- A suíte roda nos dois dialetos em CI (`.github/workflows/ci.yml`) desde `de14195`, fechando a lacuna anterior de "Postgres só localmente quando disponível" — mas segue sem cobertura de deploy real (Railway), apenas de configuração local (`tests/test_deploy.py`).
- Nenhum teste cobre `bronze_blob`/dedup por conteúdo, porque esse código só existe no stash — se e quando for retomado, precisa de teste novo desde o início.
- Nenhum teste cobre normalização (ou ausência dela) de whitespace em `admin_ok`/`PORTAL_ADMIN_TOKEN` — seria um teste barato para fechar a lacuna descrita em Known Risks.

## Missing Critical Features / Open Decisions

- Reconciliação contábil é regra de qualidade, mas divergência originada na fonte ainda requer decisão do operador; não é correção automática.
- Preço B3 e a publicação de `ticker`/`segmento_listagem` como classe pública continuam decisão de negócio do Alex, não lacuna técnica (ver Security Considerations, COTAHIST/cadastro B3).
- Dividendos via brapi: cadência/escopo ainda sem decisão (única pendência viva do brapi).
- Retomar (ou descartar formalmente) o stash de dedup de bronze por conteúdo — hoje é trabalho invisível fora deste documento.

---

*Concerns audit: 2026-08-26*
