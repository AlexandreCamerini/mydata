# Backlog do mydata

Data-base: 2026-11-08. Consolida o que está aberto em
[finops-mydata.md](finops-mydata.md),
[plano-custos-armazenamento-mydata.md](plano-custos-armazenamento-mydata.md),
[contrato-consumidor.md](contrato-consumidor.md) e
[arquitetura.md §14](arquitetura.md#14-questões-em-aberto). O detalhe de cada
item mora no documento de origem; aqui fica só a ordem e o critério de pronto.

**Critério de ordem:** valor (dólar, risco evitado ou consumidor destravado)
dividido por esforço. Quick win = até 30 min, sem deploy de código e sem
janela de manutenção.

**Dono:** `Claude` executa daqui; `Alex` é painel, decisão ou credencial;
`outro repo` vira linha em [contrato-consumidor.md](contrato-consumidor.md),
não edição a partir daqui.

---

## 0. Urgente — consumidor quebrado

| # | Item | Valor | Esforço | Dono | Pronto quando |
|---|---|---|---|---|---|
| U1 ✅ | **Índice `(ticker_objeto, dt_pregao)` em `negociacao_b3`.** Criado em produção com `CONCURRENTLY` em 09/11 02:56 UTC; a consulta caiu de 24 s para 36–500 ms. Declaração na classe e correção do motor (o índice único deixa de ser refeito à toa) mergeadas no [PR #9](https://github.com/AlexandreCamerini/mydata/pull/9) | Destrava o Boris+ e elimina seq scans de 1,3 GB que enchiam o cache | feito | Claude | Falta conferir 24 h de log `http` sem 499 nessa rota |
| U2 ✅ | **Voltar o Postgres para 1 GB (reverter o F2).** Feito em 09/11 por volta de 03:45 UTC, sem reinício: `memory.max` = 1 GB, `effective_cache_size` = 768 MB, `railway.ts` com `1_000_000_000`. O F2 só volta com `calcular` < 400 s em 3 noites úteis (QW7) | Evita OOM no `calcular` de terça | feito | Claude (`update-service` liberado pelo Alex) | — |

## 1. Quick wins

Feitos em 08–09/11: QW1, QW2, QW3 e o primeiro ponto do QW5. O resultado
está em [finops-mydata.md](finops-mydata.md#achados-de-2026-11-08).

| # | Item | Valor | Esforço | Dono | Pronto quando |
|---|---|---|---|---|---|
| QW1 ✅ | **Deriva do IaC.** `.railway/railway.ts` declara `memoryBytes: 1_000_000_000` no Postgres e não declara o sono do `mydata`. O próximo `railway config apply` desfaz o teto de 512 MB e o sono de 08/11 | Protege −US$ 5/mês do F2 | 15 min | Claude | `railway.ts` com 512 MB e `sleepApplication` no `mydata`; `railway config plan` sem diff além do resíduo conhecido de `restartPolicyType`. O `mcp` não está no `railway.ts`: registrar isso no comentário, não inventar declaração |
| QW2 ✅ | **Registrar 08/11 em `finops-mydata.md`.** Teto de 512 MB, `max_connections` 500→50, `effective_cache_size` 4 GB→256 MB, sono no `mydata` e no `mcp`, restart do Postgres. Corrigir a contagem do F2: entrou um dia antes dos 7 dias do F1, então o aceite de 7 dias vai de 08/11 a 15/11 | Documento volta a ser fonte de verdade | 15 min | Claude | Seção 3 e F2 atualizados, projeção da seção 5 marcada com o cenário em vigor |
| QW3 ✅ | **Conferir se o sono acontece.** Resultado: não dorme. O coletor do console (`CONSOLE_COLETOR=1`, a cada 5 min) mantém o `mydata` ativo e acorda o `mcp`. Decisão pendente: tirar o coletor do processo web ou aceitar que o sono não rende (~$0,6/mês). `pg_stat_activity` agrupado por `application_name`/`client_addr` com `state_change`, mais métricas e logs do `mydata` e do `mcp`. Conexão de pool viva conta como tráfego e impede o sono | Valida a economia do sono antes de esperar a fatura | 15 min | Claude | Ou os dois serviços aparecem dormindo nas métricas, ou a conexão que os segura está identificada com origem |
| QW4 | **Ler o primeiro pregão novo depois das mudanças** (terça 10/11, cron de 06:00 UTC; o de segunda só roda BCB). Medir `pg_postmaster_start_time()`, o `calcular` do `b3_cotahist` em `log_fase` contra 575–626 s (F1) e o aceite de 196 s, e o pico de memória | Primeira medição com o índice novo e sem a varredura do Boris+ | 15 min | Checagem agendada (`mydata-finops-checagem-diaria`, renovada para terças) | Números no relatório de `docs/relatorios-finops/`. OOM → U2 imediato |
| QW5 ✅ | **F3 medido pela checagem diária:** razão UPDATE/INSERT por noite caiu de cerca de 30 para 9,5 (n = 3). F3 concluído | — | feito | — | — |
| QW6 | **Alerta e limite de gasto.** Decidir antes se é no workspace ou no projeto: o `finops-mydata.md` usa o workspace (soft US$ 15, hard US$ 50, estimativa US$ 38,69 com outros projetos); o alerta de US$ 10 sugerido no handoff só faz sentido no nível do projeto, no workspace ele dispara na hora | Rede de proteção contra regressão de custo | 5 min | Alex (painel) | `railway usage limit status` com soft acima do ritmo esperado e um alerta que dispara de verdade quando passar |
| QW7 | **Decidir o caminho do `calcular`.** O aceite do F1 falhou: 671 s em 10/11, 3,4× o aceite e pior que na semana (575–626 s). Primeiro, separar o `effective_cache_size`: `EXPLAIN` dos statements do `calcular` sob `'4GB'` e sob `'768MB'`; se o plano mudar, voltar para 4 GB e remedir. Depois, mergear `escopo-calcular` (`b948320`, leitura escopada, exige A4 verde em Postgres) ou subir a 2 GB e remedir | É o que destrava o F2 (cerca de −$2,5/mês, não −$5: ver ganhos medidos) | 30 min a checagem; 2–4 h se mergear | Claude a checagem; Alex decide o resto | `calcular` < 400 s em 3 noites úteis |
| QW8 | **Chaves de consumidor, lado de cá.** Reemitir a chave do MCP serviço com escopo `setups`; revogar `dadbd4b0` assim que o BolsIA confirmar a `f00b4554` | Destrava `/v1/setups` para o MCP; tira uma chave sobrando do ar | 10 min | Alex decide, Claude executa | Linhas correspondentes em `contrato-consumidor.md` marcadas como resolvidas |
| QW9 | **Higiene do git.** Branches remotas já contidas em `main` (conferido em 08/11 com `git branch -r --merged origin/main`): `plano-calcular`, `trava-e-recuperacao`, `claude/mydata-handoff-3b2cc1`, `claude/remote-control-d97624`, `claude/vanity-engineering-review-911d2b`. Worktrees paradas: `vanity-engineering-review-911d2b` e `vibrant-stonebraker-910d98` (HEAD destacado). **Não** mergeadas, olhar antes de apagar: `affectionate-meitner-95c32a`, `bronze-captura-da-rodada`, `escopo-calcular` (QW7), `fix-path-prompt-mcp`, `worktree-async-singing-mccarthy`, `worktree-fase4-fechamento-contrato` | Ruído a menos | 10 min | Claude, com confirmação item a item | Só o que está em `--merged` é apagado sem pergunta; cada não mergeada tem destino decidido (merge, descarte ou manter) |

Próximos passos: QW4 na terça 10/11 de manhã (checagem agendada); QW6 e QW7 quando você puder abrir o painel.

---

## 2. Médio esforço (horas)

Acrescentados em 09/11, a partir dos [relatórios diários](relatorios-finops/):

- **M6. Código de saída do cron:** o processo devolve 1 quando qualquer dataset falha, e o Railway marca CRASHED. Foram 3 alertas falsos em 5 noites (feriado com 404, SGS instável), que escondem um OOM real. Proposta: devolver 0 quando pelo menos um dataset publicou e reservar 1 para falha de infraestrutura (as falhas já ficam em `log_execucao`). Esforço de 1 h; dono: Claude.
- **M8. Coletor do console, origem `railway`:** desde o boot de 09/11, `AttributeError: 'NoneType' object has no attribute 'get'` (`app/console/`). Não é FinOps; diagnosticar quando mexer no console.
- **M7. F3-bis em `dim_instrumento`:** cerca de 89 mil UPDATEs por noite para cerca de 350 INSERTs. Mesmo critério do F3. Esforço de 1–2 h; dono: Claude.

| # | Item | Valor | Esforço | Dono | Depende de |
|---|---|---|---|---|---|
| M1 | **Não fazer `VACUUM FULL` de `fato_negociacao`** (revisto em 09/11). O autovacuum segura as tuplas mortas (82–265 mil) sozinho. Antes de qualquer decisão, medir `pg_total_relation_size`; acima de 350 mil mortas, `VACUUM (ANALYZE)` manual | Evita lock exclusivo sob teto de memória | 10 min de medição | Claude | Tamanho em disco das 3 tabelas no relatório semanal |
| M2 | **D2 — `razao_sla` e severidade em `GET /v1/meta/frescor`.** Aditivo, contrato atual intacto | O MCP serviço pode bloquear tools de opções com dado vencido | 2 h | Claude | — |
| M3 | **Fechar o B1.** Índice único parcial em `log_execucao` e status `pulada` | Execução duplicada fica impossível no banco, não só pela advisory lock | 2–3 h | Claude | — |
| M4 | **B3 — triagem das falhas do `cvm_itr`.** Tabela de causa por execução | Sabe-se se é dado, rede ou defeito | 2 h | Claude | — |
| M5 | **Retenção de backup do volume** (~1,8 GB em média) | Centavos por mês: só vale se o painel já mostrar custo de backup | 15 min de leitura + decisão | Alex (painel) | Fatura de dezembro |

---

## 3. Grande esforço (dias)

| # | Item | Valor | Dono |
|---|---|---|---|
| G1 | **B2 + D1** — timeout por fase, heartbeat, reconciliação no boot e alerta de frescor por execução presa | Teria evitado as execuções presas de agosto e setembro | Claude |
| G2 | **C1 + C2** — dedupe por `hash_conteudo` no silver e pular payload bronze idêntico | Menos CPU e menos escrita em carga integral repetida | Claude |
| G3 | **A4 + A5** — teste de equivalência escopado == integral e revisão de schema, índices e bloat de `fato_negociacao` | Pré-requisito para qualquer escopo novo no `calcular` | Claude |

---

## 4. Decisões abertas (sem esforço de código até decidir)

| # | Decisão | Onde |
|---|---|---|
| D-1 | SLA de 96 h de `negociacao_b3` é o certo? (D3) | [plano-custos §4](plano-custos-armazenamento-mydata.md) |
| D-2 | Questões em aberto 2 a 5 — multi-tenant, gate sobre linha publicada, bronze duplicado entre mapeamentos, mapeamento que lê demais. Nenhuma tem caso concreto hoje; manter aberta até ter | [arquitetura §14](arquitetura.md#14-questões-em-aberto) |
| D-3 | Corte do `MYDATA_BASE_URL` do BolsIA para `mydata.semente.dev` | [contrato-consumidor](contrato-consumidor.md#pendências-de-negociação) |

## 5. Dependem de outro repositório

Registrados em [contrato-consumidor.md](contrato-consumidor.md#pendências-de-negociação);
não se edita daqui.

- BolsIA: emitir a chave contra o Postgres de produção e adotar a `f00b4554`.
- Boris+: confirmar que Yahoo, brapi e o COTAHIST paralelo foram desligados;
  definir `B3_OBSERVABILIDADE_CHAVE` no Railway do `b3agente`.

---

## 6. Não fazer

Do [finops-mydata.md](finops-mydata.md#não-fazer-por-custo) e da sessão de
08/11:

- Mexer em `shared_buffers`/`work_mem` "para economizar": já estão no mínimo
  útil (128 MB / 4 MB) e não movem a conta. Quem corta é o teto do container.
- Pôr `semente-id` para dormir: é o provedor de login; ~US$ 0,7/mês não paga
  atrasar todo login.
- Unir os três serviços web: US$ 1–1,5/mês não paga o retrabalho.
- Trocar o Postgres do Railway por serviço externo (Neon etc.): a regra de
  custo do projeto proíbe e o problema era configuração.
- Limpar silver ou bronze por custo: ~US$ 0,08/mês, e o ADR-10 proíbe tocar
  bronze.
- Reiniciar o Postgres perto das 06:00 UTC.
- Usar `redeploy` esperando código novo: ele reaproveita o build da última
  implantação.
