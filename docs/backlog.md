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

## 1. Quick wins

| # | Item | Valor | Esforço | Dono | Pronto quando |
|---|---|---|---|---|---|
| QW1 | **Deriva do IaC.** `.railway/railway.ts` declara `memoryBytes: 1_000_000_000` no Postgres e não declara o sono do `mydata`. O próximo `railway config apply` desfaz o teto de 512 MB e o sono de 08/11 | Protege −US$ 5/mês do F2 | 15 min | Claude | `railway.ts` com 512 MB e `sleepApplication` no `mydata`; `railway config plan` sem diff além do resíduo conhecido de `restartPolicyType`. O `mcp` não está no `railway.ts`: registrar isso no comentário, não inventar declaração |
| QW2 | **Registrar 08/11 em `finops-mydata.md`.** Teto de 512 MB, `max_connections` 500→50, `effective_cache_size` 4 GB→256 MB, sono no `mydata` e no `mcp`, restart do Postgres. Corrigir a contagem do F2: entrou um dia antes dos 7 dias do F1, então o aceite de 7 dias vai de 08/11 a 15/11 | Documento volta a ser fonte de verdade | 15 min | Claude | Seção 3 e F2 atualizados, projeção da seção 5 marcada com o cenário em vigor |
| QW3 | **Conferir se o sono acontece.** `pg_stat_activity` agrupado por `application_name`/`client_addr` com `state_change`, mais métricas e logs do `mydata` e do `mcp`. Conexão de pool viva conta como tráfego e impede o sono | Valida a economia do sono antes de esperar a fatura | 15 min | Claude | Ou os dois serviços aparecem dormindo nas métricas, ou a conexão que os segura está identificada com origem |
| QW4 | **Ler o primeiro cron sob 512 MB** (09/11, 06:00 UTC = 03:00 BRT). `pg_postmaster_start_time()` igual ao do restart de 08/11; duração da fase `calcular` do `b3_cotahist` em `log_fase` contra a linha de base de 84–98 s; memória no pico | Detecta OOM em 1 dia, não em 7 | 15 min, a partir de 09/11 ~06:30 UTC | Claude | Os três números registrados em `finops-mydata.md`. Se houve OOM: teto volta a 1 GB, sem segunda tentativa (regra do F2) |
| QW5 | **Linha de base do F3.** `n_tup_upd` e `n_tup_ins` de `fato_negociacao` agora, e de novo depois de 3 pregões | Destrava o `VACUUM FULL` (M1) | 10 min + 10 min | Claude | Razão UPD/INS por pregão caiu de ~30 para perto de 0 |
| QW6 | **Alerta e limite de gasto.** Decidir antes se é no workspace ou no projeto: o `finops-mydata.md` usa o workspace (soft US$ 15, hard US$ 50, estimativa US$ 38,69 com outros projetos); o alerta de US$ 10 sugerido no handoff só faz sentido no nível do projeto, no workspace ele dispara na hora | Rede de proteção contra regressão de custo | 5 min | Alex (painel) | `railway usage limit status` com soft acima do ritmo esperado e um alerta que dispara de verdade quando passar |
| QW7 | **Decidir o destino de `escopo-calcular`.** A leitura escopada (A3) nunca entrou em `main`; a CPU do Postgres já está em ~US$ 0,08/mês, então o ganho que sobra é latência, não custo | Fecha um "parcial" que confunde o plano | 5 min de decisão | Alex | A3 marcado como descartado (e a branch apagada) ou como item do nível 2 com motivo |
| QW8 | **Chaves de consumidor, lado de cá.** Reemitir a chave do MCP serviço com escopo `setups`; revogar `dadbd4b0` assim que o BolsIA confirmar a `f00b4554` | Destrava `/v1/setups` para o MCP; tira uma chave sobrando do ar | 10 min | Alex decide, Claude executa | Linhas correspondentes em `contrato-consumidor.md` marcadas como resolvidas |
| QW9 | **Higiene do git.** Branches remotas já contidas em `main` (conferido em 08/11 com `git branch -r --merged origin/main`): `plano-calcular`, `trava-e-recuperacao`, `claude/mydata-handoff-3b2cc1`, `claude/remote-control-d97624`, `claude/vanity-engineering-review-911d2b`. Worktrees paradas: `vanity-engineering-review-911d2b` e `vibrant-stonebraker-910d98` (HEAD destacado). **Não** mergeadas, olhar antes de apagar: `affectionate-meitner-95c32a`, `bronze-captura-da-rodada`, `escopo-calcular` (QW7), `fix-path-prompt-mcp`, `worktree-async-singing-mccarthy`, `worktree-fase4-fechamento-contrato` | Ruído a menos | 10 min | Claude, com confirmação item a item | Só o que está em `--merged` é apagado sem pergunta; cada não mergeada tem destino decidido (merge, descarte ou manter) |

Ordem de execução sugerida: QW1 → QW2 → QW3 hoje; QW4 e o primeiro ponto de
QW5 em 09/11 de manhã; QW6 e QW7 quando você puder abrir o painel.

---

## 2. Médio esforço (horas)

| # | Item | Valor | Esforço | Dono | Depende de |
|---|---|---|---|---|---|
| M1 | **`VACUUM FULL` de `fato_negociacao` e `dim_instrumento`** (fechamento do F3). Trava a tabela (`ACCESS EXCLUSIVE`): fazer fora do cron das 06:00 UTC e com o portal aceitando indisponibilidade da classe `negociacao_b3` por alguns minutos | ~−800 MB de disco, menos página quente disputando os 512 MB | 1 h | Claude, janela aprovada pelo Alex | QW5 confirmar que os UPDATEs pararam; QW4 sem OOM |
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
