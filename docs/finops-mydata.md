# FinOps do mydata

Data-base: 2026-11-01. Fontes: `railway usage projects --project mydata`
(fatura por serviço), `railway metrics` (série de memória de 14 dias) e
`/sys/fs/cgroup/memory.stat` do container Postgres de produção, lido por
`railway ssh`, somente leitura.

## 1. Fatura real

| Período | Projeto mydata | Postgres: memória | Postgres: CPU | Postgres: volume + backup | Demais serviços |
|---|---|---|---|---|---|
| 14/08–14/09 | $22,08 | $13,40 | $6,25 | $0,74 | $1,69 |
| 14/09–14/10 | $25,78 | $16,46 | $5,34 | $0,90 | $2,78 |
| 14/10–01/11 (18,6 de 31 dias) | $12,71 (ritmo ≈ $21/mês) | $10,30 | $0,05 | $0,60 | $1,55 |
| 14/10–10/11 (27,9 de 31 dias, parcial; F1 desde 02/11) | $16,19 | $12,71 | $0,10 | $0,91 | $2,24 |

O mydata é 58 % do workspace no período corrente ($12,71 de $21,86). O
workspace já passou do soft limit de $15, e o Railway estima $38,69 para o
fechamento. "Demais serviços" inclui `mcp` e `semente-id`, que rodam no mesmo
projeto Railway mas são outros sistemas.

**O ofensor é a memória do Postgres: 65–81 % da conta do projeto.** CPU, disco
e backup somados não chegam a $1,10/mês.

## 2. Diagnóstico: a memória cobrada é cache de arquivo, não Postgres

`memory.stat` do container, em 2026-11-02 01:40 UTC:

| Componente | Bytes | O que é |
|---|---|---|
| `file` | 2.489 MB | cache de página do kernel (inclui `shmem`) |
| └ `shmem` | 169 MB | `shared_buffers` (128 MB) + memória compartilhada |
| `anon` | 33 MB | memória privada dos processos Postgres |
| `kernel` | 44 MB | estruturas do kernel |
| **total cobrado** | **2.566 MB** | `memory.current` |

O Postgres precisa de cerca de 250 MB. O resto, cerca de 2,3 GB, é o kernel
guardando em cache as páginas do banco que já foram lidas. Esse cache é
descartável, mas o Railway cobra memória por `memory.current`, e o limite do
serviço está em 24 GB. Sem pressão de memória, o kernel não devolve nada.

A série de 14 dias mostra o mecanismo. A memória sobe de 1,6 para 2,0 GB ao
longo da semana, cai para 0,25 GB em 25/10 (cache descartado), e volta a
2 GB em três dias. O pico de 4,1 GB em 01/11 foi esta sessão: `pg_dump`,
varreduras de dimensionamento e `VACUUM FULL`.

Consequência direta: **apagar dado quase não muda a conta.** O volume custa
cerca de $0,15/GB·mês, então os 988 MB liberados hoje valem cerca de $0,15 por
mês. Sem limite de memória, o cache cresce até o tamanho do conjunto que é
lido. O que derruba a conta é limitar a memória do serviço.

## 3. O que já foi feito

| Quando | O quê | Ganho medido |
|---|---|---|
| 2026-09-29 | `ANALYZE` antes do `calcular` e UPDATE de janela sem laço aninhado (`82b70e2`) | CPU do Postgres de $5–6/mês para cerca de $0,08/mês (−99 %). As 16–44 h por pregão sumiram. A leitura escopada (`b948320`) **não** entrou em `main`: está só na branch `escopo-calcular`, e a leitura do `calcular` segue integral |
| 2026-09-29 | Trava por dataset+janela e reaper de execuções abandonadas (`6b64310`) | Sem execução duplicada nem presa. Era o que empilhava `calcular` |
| 2026-10-31 | Cron: só o 404 (feriado, sem arquivo) deixa de consumir o teto de janelas; timeout e 5xx continuam consumindo. Resposta não-JSON tenta de novo (`9e428f0`, `b9efabe`, `d42ac1c`) | Operacional. Acaba com o reprocessamento em cascata depois de feriado |
| 2026-11-01 | `ANALYZE` de `fato_conta`, `fato_negociacao` e `dim_instrumento` | Estatística corrigida (`fato_conta` estava com `n_live_tup = 0` desde o restart de 10/09) |
| 2026-11-01 | `VACUUM FULL fato_conta` | 1.363 MB → 375 MB, banco 3.445 MB → 2.456 MB, digital de gold idêntica. Cerca de $0,15/mês direto; reduz o teto do cache |
| 2026-11-02 | **F1: limite de 1 GB de memória no Postgres** | Memória cobrada de 2.566 MB para 811 MB na hora. Pelo menos −$6,6/mês esperado |
| 2026-11-08 | **F2: limite de 500 MB** (`memoryBytes: 500_000_000`), `max_connections` 500→50, `effective_cache_size` 4 GB→256 MB, restart do Postgres (`pg_postmaster_start_time()` = 2026-11-09 01:29 UTC). Sono (`sleepApplication`) ligado no `mydata` e no `mcp`; `semente-id` segue sempre ligado (é o login). `railway.ts` alinhado no mesmo dia | Esperado mais −$5/mês na época; o ritmo medido mostra cerca de −$2,6 (ver §5). O sono **não** rende nada enquanto o coletor do console rodar (ver "Achados de 2026-11-08") |

Do [plano de setembro](plano-custos-armazenamento-mydata.md), conferido
contra `main` em 2026-11-02: A2 (perfil e correção do plano) e a trava do B1
(advisory lock) estão feitos. Estão **parciais**: A3 (só a escrita é
escopada; a leitura integral), A4, A5, B1 (sem índice único parcial em
`log_execucao` nem status `pulada`) e B2 (só o reaper de 72 h do cron, sem
timeout por fase, heartbeat nem reconciliação no boot). Não existem no
código: C1 (`hash_conteudo`), C2 (pular payload idêntico), D2 (`razao_sla`) e
a tabela de triagem do `cvm_itr` (B3).

## 4. Plano

Ordenado por dólar economizado por hora de trabalho.

### F1. Limite de memória de 1 GB no serviço Postgres — APLICADO em 2026-11-02 00:30 (São Paulo)

**Execução:** `serviceInstanceLimitsUpdate(memoryGB: 1)` pela API do Railway
(`railway api`). Entrou no ar sem redeploy e sem reiniciar o Postgres:
`pg_postmaster_start_time()` continuou 2026-09-10 11:10 UTC. O cgroup passou
para `memory.max` = 1 GB e `memory.current` caiu de 2.566 MB para 811 MB em
20 s (`file` de 2.489 para 756 MB; `anon` estável em 33 MB). Vistas gold
responderam normalmente. Declarado em `.railway/railway.ts`
(`Postgres.deploy.limitOverride`), e `railway config plan` não propõe mais
reverter.

**Achado no caminho:** o `railway.ts` estava defasado. Um `apply` teria
apagado 10 variáveis de produção: as nove `CONSOLE_*` do serviço `mydata` e
`PORTAL_MAX_JANELAS_POR_DISPARO` do `mydata-cron`. Agora estão declaradas com
`preserve()`. O plan só mostra o resíduo conhecido de `restartPolicyType`.

**Linha de base para o aceite:** fase `calcular` do `b3_cotahist` entre 84 e
98 s nas 10 últimas execuções publicadas (122 s no pior caso). As próximas
noites rodam recuperação de 5 pregões por disparo (backlog de 20/10 a 30/10),
o que testa o limite sob carga.

Plano original:

- **Ganho:** a memória do Postgres passa de cerca de $16,6/mês para no máximo
  $10/mês. **Pelo menos −$6,6/mês**, cerca de 30 % do projeto.
- **Como:** painel do Railway → serviço Postgres → Settings → Resource
  Limits → Memory = 1 GB. Se o projeto estiver sob o IaC (`railway.ts`, em
  outro repositório), declarar lá para o próximo `apply` não desfazer.
  Precisa de redeploy do serviço, que reinicia o Postgres: cerca de 30 s de
  indisponibilidade. Fazer fora da janela do cron.
- **Por que é seguro:** a necessidade real é de cerca de 250 MB (anon + shmem
  + kernel). Sob limite, o kernel descarta cache antes de chegar a matar
  processo. O efeito colateral é mais leitura de disco quando uma página sai
  do cache.
- **Onde quebra:** se uma consulta precisar de mais de 750 MB de memória
  privada, o Postgres leva OOM kill e reinicia, sem perder dado (WAL). O
  candidato é sort ou hash grande na `calcular`. Com `work_mem` de 4 MB e
  `maintenance_work_mem` de 64 MB, isso fica longe.
- **Aceite (7 dias):** `pg_postmaster_start_time()` igual ao do pós-deploy
  (nenhum OOM); duração da fase `calcular` do `b3_cotahist` no máximo 2× a de
  antes, em `log_fase`; memória média ≤ 1 GB em `railway metrics`.
- **Degradação:** se houver OOM, subir para 2 GB (ainda abaixo dos ~2 GB
  médios de hoje) e medir `anon` em `memory.stat` durante a `calcular`.

### Resultado do F1 (semana de 04/11 a 08/11): aceite FALHOU no `calcular`

Fonte: [relatórios diários](relatorios-finops/), coletados por
`scripts/finops-checagem.sh`.

- **Memória e OOM:** passou. Foram 5 dias sem OOM nem reinício, e
  `memory.current` ficou entre 91 % e 100 % do teto. O F1 funciona como teto
  de custo, mas não reduz o consumo para baixo do teto: o cache sempre ocupa
  o que sobra.
- **`calcular` do `b3_cotahist`:** falhou. As medições foram 574,7, 570,5,
  614,3 e 626,2 s, contra um aceite de no máximo cerca de 196 s (2× os 84–98 s
  de antes do F1). A falha foi nas quatro medições, com tendência de piora.
  O gargalo é leitura: sob 1 GB, `file` ocupa de 900 a 944 MB.
- **Causa provável da leitura fora da rodada,** levantada em 09/11: o Boris+
  chamava `/v1/opcoes/{ticker}/vencimentos` a cada poucos minutos, e cada
  chamada fazia seq scan de 1,3 GB em `fato_negociacao` (ver achados
  abaixo). Isso explica o salto da média de memória num sábado sem pregão.
  Também deve competir por cache e I/O com o `calcular`. O índice
  `ix_fato_negociacao_4`, de 09/11, eliminou essa varredura.

### F2. Baixar para 500 MB — aplicado em 2026-11-08 sem a pré-condição, REVERTIDO em 2026-11-09

O F2 dependia do aceite do F1 ("o mesmo de F1, por mais 7 dias"), e o F1
falhou no `calcular`. O relatório de 08/11 recomendava não aplicar o F2
enquanto o `calcular` estivesse acima de 2× o aceite. A sessão de 08/11
aplicou mesmo assim (teto de 500 MB, `max_connections` 50,
`effective_cache_size` 256 MB) e não registrou essa pré-condição.

**Risco sob 500 MB:** a memória que o kernel não pode descartar é de cerca
de 205 MB fixos (`anon` + `shmem`). Até três workers de autovacuum com
`maintenance_work_mem` de 64 MB somam 192 MB. São cerca de 440 MB contra um
teto de 500 MB, e o OOM fica plausível justamente no `calcular`. O primeiro
pregão novo processado sob o teto é o de **terça 10/11, por volta de
06:00 UTC**. O cron de segunda 09/11 só roda BCB, porque a janela de sexta
já foi publicada.

**Revertido em 2026-11-09, por volta de 03:45 UTC** (`update-service`
`limits.memoryGB: 1`, liberado pelo Alex). `memory.max` voltou a
999.997.440, sem reinício: o postmaster seguiu o de 01:29 UTC.
`effective_cache_size` passou de 256 para 768 MB (`ALTER SYSTEM` +
`pg_reload_conf()`), valor coerente com o teto de 1 GB. `max_connections`
fica em 50: estava superdimensionado (500) e não pesa na conta. O
`railway.ts` voltou a declarar `1_000_000_000`, e `railway config plan` só
acusa o resíduo de `restartPolicyType`.

- **Ganho, se der certo:** cerca de −$2,6/mês, medido em 10/11 (§5). A
  estimativa original, de −$5, supunha o cache sempre no teto de 1 GB, mas
  o médio pago é de 0,76 GB.
- **Pré-condição para tentar de novo:** `calcular` abaixo de cerca de 400 s
  (2× o aceite) em 3 noites úteis seguidas sob 1 GB. Contagem: 11/11 =
  394,2 s, 12/11 ≈ 392 s, 13/11 ≈ 408 s. **A contagem provavelmente
  quebrou na 3ª noite** (12 e 13/11 estimados pelo log, ver §5). Recomeça
  depois do QW7.
- **Kill:** um OOM volta para 1 GB (`memoryBytes: 1_000_000_000` no
  `railway.ts`, e `limits.memoryGB: 1` na API, que aplica na hora), sem
  segunda tentativa.
- **O que não é efeito do F2:** a lentidão de `/v1/opcoes/{ticker}/vencimentos`
  já existia em 03/11 sob 1 GB (ver achados abaixo). Ela piora sob 500 MB
  porque lê mais do disco, mas a causa é falta de índice, e voltar para 1 GB
  não a resolve.

### F3. `calcular` sem regravar linha que não mudou — CONCLUÍDO (medido de 05 a 07/11)

**Resultado:** a razão UPDATE/INSERT por noite útil caiu de cerca de 30 para
9,5 (n = 3), ou seja, três vezes menos escrita. O efeito no tempo do
`calcular` foi nenhum, porque o gargalo é leitura. O bloat ficou sob
controle sem intervenção: as tuplas mortas oscilaram entre 82 mil e 265 mil,
e o autovacuum devolveu o valor sozinho em ciclo de cerca de 2 dias.
**`VACUUM FULL` de `fato_negociacao` não se justifica:** ele exige lock
exclusivo e espaço para a cópia, e é a operação mais arriscada sob teto de
memória. Antes de decidir, medir `pg_total_relation_size`. Se as tuplas
mortas passarem de 350 mil, rodar `VACUUM (ANALYZE)` manual, não FULL.
Próximo candidato na mesma linha: `dim_instrumento`, com cerca de 89 mil
UPDATEs por noite para cerca de 350 INSERTs (F3-bis).

Texto original do plano, mantido como histórico:

- **Feito:** o UPDATE de campo de janela ganhou
  `alvo.<campo> IS DISTINCT FROM origem.valor_calculado` (`app/motor/calculados.py`).
  Escalar e numérico ficam de fora de propósito: já são recortados pelas
  capturas novas (coluna nula, sempre distinta) e o escalar reavaliaria a
  subconsulta correlacionada duas vezes. Testes em `tests/test_plano_calcular.py`:
  recomputar sem dado novo deixa a tabela idêntica e toca 0 linhas (5 por
  campo antes da mudança), e a junção por chave continua igualdade comum.
- **Falta:** deploy; medir `n_tup_upd` de `fato_negociacao` em uns dias; só
  então `VACUUM FULL fato_negociacao` e `dim_instrumento`. A suíte em Postgres
  roda no CI.
- **Problema original:** 13,7 milhões de UPDATEs em `fato_negociacao` desde 10/09, para
  459 mil inserções. Cada linha é regravada cerca de 30 vezes, com 2 % de
  HOT. Isso gera WAL, I/O e um bloat de 58 % que puxa páginas para o cache.
- **Fix:** `UPDATE … WHERE (novo) IS DISTINCT FROM (atual)` nos UPDATEs de
  janela, com teste de equivalência em DuckDB e Postgres. Depois,
  `VACUUM FULL fato_negociacao` e `dim_instrumento` (cerca de −800 MB).
- **Ganho em dólar:** pequeno direto (menos de $0,20/mês). Com F1/F2 em vigor,
  o efeito aparece como menos leitura de disco sob o limite. **Prioridade
  menor que F1.**

### F4. Orçamento e alerta

- O soft limit do workspace ($15) já foi ultrapassado; a estimativa é $38,69.
  Ou o limite está errado, ou o alerta não está sendo lido. Depois de F1,
  ajustar o soft limit para o novo patamar (cerca de $25 no workspace) e
  manter o hard limit em $50.
- **Aceite:** `railway usage limit status` com soft acima do ritmo
  esperado, e um alerta disparado de verdade quando passar.
- **Nível do limite (pendente, 2026-11-08):** os valores acima são do
  workspace, que inclui outros projetos. Um alerta de $10 só faz sentido no
  nível do projeto `mydata` (projeção de cerca de $8,5 com F2). No workspace,
  ele dispararia na hora.

### Achados de 2026-11-08

Medido em produção entre 01:30 e 02:40 UTC de 09/11, logo depois do restart:
`pg_stat_activity`, métricas de 2 h e logs `http`/`network-flow` do Railway.

**1. O sono não acontece, e não vai acontecer do jeito que está.** Em 2 h, a
memória mínima do `mydata` foi 53 MB e a do `mcp` 63 MB — nunca zero, então
nenhum dos dois dormiu. Causas, por evidência:

- `CONSOLE_COLETOR=1` liga, dentro do processo do `mydata`, um laço que a
  cada 5 min (`INTERVALO_ENVELOPES_S`) chama `GET /observabilidade` das
  origens com `requests` (`app/console/origens.py`). O log do `mcp` mostra
  exatamente isso: `python-requests` a cada 5 min, das 01:31 às 02:36. O
  coletor mantém o próprio `mydata` com tráfego de saída e acorda o `mcp`.
- O `mydata` também recebe tráfego de consumidor: o Boris+ consulta
  `/v1/opcoes` em rajadas, inclusive de madrugada.
- Conexões no Postgres: duas origens privadas, sempre `idle`, com
  `state_change` de minutos atrás.

Consequência: ligar o sono não tem custo, mas também não rende nada. Para
render, o coletor teria de sair do processo web (rodar como cron, por
exemplo) ou ter cadência acima de 10 min. O ganho seria pequeno (o `mydata`
custa cerca de 60 MB, ou cerca de $0,6/mês), e a decisão é do Alex.

**2. Incidente de consumidor, anterior às mudanças de hoje.**
`/v1/opcoes/{ticker}/vencimentos` levava de 18 a 20 s em 03–06/11 e já
batia no timeout de 20 s do Boris+ (status 499) em 06/11 e 07/11, ainda sob
1 GB. `EXPLAIN (ANALYZE, BUFFERS)` de
`SELECT max(dt_pregao) FROM gold_opcoes WHERE ticker_objeto = 'BBDC3'`:
**24,3 s**, `Parallel Seq Scan` em `fato_negociacao` (1.314 MB), 153.906
páginas lidas do disco, 484 mil linhas descartadas por worker para achar
8.014. Não há índice com `ticker_objeto`: os índices declarados em
`app/seed_fontes.py` são `(dt_pregao, isin, tp_mercado)`, `codneg` e
`dt_vencimento`. A correção é declarar `["ticker_objeto", "dt_pregao"]` na
classe (ADR-11: o índice nasce da classe, não de DDL à mão) e migrar. Com o
limite de 500 MB, a varredura cabe ainda menos no cache, então o problema
piora, mas não foi o limite que o criou.

*Correção aplicada em 2026-11-09 02:56 UTC:* `CREATE INDEX CONCURRENTLY IF
NOT EXISTS ix_fato_negociacao_4 ON fato_negociacao (ticker_objeto,
dt_pregao)`. Levou 52 s, o índice está válido e ocupa 14 MB. Tem o mesmo
nome e a mesma definição que a classe passa a declarar (PR #9), então o
`migrar` do deploy só confirma que ele existe. Feito no boot, os 52 s
estourariam o healthcheck de 30 s. Medido depois:

- `max(dt_pregao)` BBDC3: de 24.330 ms para 500 ms a frio e 36 ms com cache;
- vencimentos BBDC3: 37 ms;
- PETR4, a maior cadeia, a frio: 2.811 ms.

**3. `n_tup_upd` de `fato_negociacao`:** 15.793.420 UPDATEs para 670.664
INSERTs, acumulados desde 10/09. A razão acumulada, de cerca de 23,5, não
mede o F3. A medida certa é o delta por noite, já feito pela checagem
diária: 9,5 (ver F3).

**4. Deploy do PR #9 (`71c6815`, 2026-11-09 03:22 UTC):** SUCCESS em 53 s.
O `migrar` do boot aplicou a classe `negociacao_b3` em cerca de 1 s, sem
refazer o índice único: `idx_scan` de `ux_fato_negociacao_identidade`
continuou em 4.076.310, e esse contador zeraria se o índice tivesse sido
recriado. `/health` respondeu 200, e o postmaster seguiu o de 01:29 UTC. No
mesmo boot, o coletor do console registrou `origem=railway ok=False`
(`AttributeError: 'NoneType' object has no attribute 'get'`); fica
registrado no backlog, fora do FinOps.

**5. Checagem de FinOps renovada:** a tarefa agendada
`mydata-finops-checagem-diaria` passou a rodar toda terça às 08:15 BRT, de
10/11 a 01/12, com a linha de base de 09/11 e com medição de tamanho das
tabelas e de 499 em `/v1/opcoes`.

### Não fazer por custo

- **Limpeza de silver (fato_conta não-latest, mercados fora de gold, opções
  vencidas):** cerca de 500 MB, cerca de $0,08/mês. Só se justifica por
  outra razão. Ver [análise de limpeza](analise-limpeza-dados.md).
- **Retenção de bronze:** 214 MB guardados. Irrelevante, e o ADR-10 proíbe.
- **Trocar o Postgres do Railway por serviço externo:** a regra de custo do
  projeto proíbe, e o problema é configuração, não plataforma.

## 5. Ganhos medidos (2026-11-10)

Calculados por `scripts/finops-ganhos.py` a partir das leituras datadas de
`railway usage projects` (relatórios diários e coleta de 10/11). O cálculo
usa o **ritmo**, a diferença entre duas leituras dividida pelo tempo, e
não o total acumulado: a fatura de 14/10–14/11 mistura 19 dias de antes
com 9 dias de depois do F1 e não serve de linha de base.

| Trecho | Dias | Projeto $/mês | Memória PG $/mês | GB médio implícito |
|---|---|---|---|---|
| 14/10 → 01/11 (pré-F1) | 18,6 | 20,77 | 16,83 | 1,68 |
| 04/11 → 08/11 (F1) | 3,9 | 11,22 | 7,66 | 0,77 |
| 08/11 → 10/11 (F1; F2 por cerca de 2 h, depois revertido) | 2,5 | 11,24 | 7,61 | 0,76 |
| **04/11 → 10/11 (F1)** | **6,4** | **11,23** | **7,64** | **0,76** |

**Cruzamento:** memória de $7,64/mês ÷ $10/GB·mês dá 0,76 GB, e o
`railway metrics` de 7 dias mede 0,82 GB médio. As duas fontes concordam,
com cerca de 8 % de folga.

**Ganhos, por origem:**

- **F1 (teto de 1 GB, 2026-11-02): −$9,55/mês no projeto** (−46 %) contra
  o ritmo pré-F1. Quase tudo é memória do Postgres (−$9,19/mês).
- **Correção do CPU do `calcular` (2026-09-29): cerca de −$5,3/mês.** O CPU
  do Postgres caiu de $5,34 na fatura de 14/09–14/10 para cerca de
  $0,10/mês. Já estava no ritmo pré-F1 deste período.
- **Os dois juntos, contra a última fatura fechada (14/09–14/10, $25,78):
  −$14,55/mês (−56 %).** O projeto roda hoje a cerca de **$11,2/mês**,
  numa janela de 6,4 dias. É uma faixa, não um ponto: a média diária de
  memória oscilou entre 741 e 1.004 MB na semana do F1, e com o cache
  sempre no teto de 1 GB o projeto chegaria a cerca de $13,6/mês.
- **Sessão de 08–10/11: cerca de $0/mês, e isso foi medido.** O ritmo de
  08→10/11 ($0,370/dia) é igual ao de 04→08/11 ($0,362/dia). O F2 durou
  cerca de 2 h, o sono do `mydata` e do `mcp` não acontece (coletor do
  console) e `max_connections` 500→50 tirou cerca de 20 MB de `shmem`
  (cerca de $0,20/mês). Os ganhos desta sessão não são em dólar:
  `/v1/opcoes/{ticker}/vencimentos` passou de 24 s e 499 para p50 de 49 ms
  e zero 499 em 332 chamadas do Boris+; o `railway.ts` deixou de ter
  deriva; e o motor deixou de refazer o índice único à toa.

**A meta de $7–8/mês não foi atingida.** Com a configuração atual, o
projeto fica entre cerca de $11 e $13,6/mês. Sobre o que faltaria:

- **F2 vale cerca de −$2,6/mês, não −$5:** hoje se paga 0,76 GB médio, e
  não 1 GB cheio. A 0,5 GB, a economia é (0,76 − 0,5) × $10. A estimativa
  antiga supunha cache sempre no teto.
- Com o F2, o projeto ficaria em cerca de $8,5/mês. Mas o F2 só volta com
  `calcular` < 400 s em 3 noites úteis. Estava em 671 s em 10/11; com o U3,
  foi a 394,2 s em 11/11 e ~392 s em 12/11, mas ~408 s em 13/11: a
  contagem provavelmente quebrou.
- O resto (`semente-id`, `mcp`, `mydata`, cron, volume e backup) soma cerca
  de $3,4/mês, sem alavanca grande.

**Projeção da primeira fatura limpa (14/11–14/12), no ritmo pós-F1:**
cerca de **$11,2** no projeto, com teto de cerca de $13,6 (Postgres cerca de $8,9: memória $7,6, volume
e backup $1,0, CPU e egress $0,3). A fatura de 14/10–14/11 vai fechar perto
de $17,3, porque mistura os dois regimes.

### `calcular` piorou para 671 s em 10/11, com causas que não dá para separar

Série sob 1 GB: 574,7 / 570,5 / 614,3 / 626,2 / **671,1 s** (aceite ≤ 196 s).
A tendência vinha em cerca de +12 s por noite útil, e o salto de 10/11 foi
de +44,9 s. A rodada de 10/11 difere das da semana do F1 em pelo menos três
pontos, e um ponto só não separa nenhum deles:

1. **`effective_cache_size`:** era 4 GB em todas as medições de 575–626 s,
   e desde 09/11 é 768 MB. É uma mudança de planner que ficou em vigor.
2. **Cache espremido:** o F2 reduziu o cache para cerca de 200 MB na noite
   de 08 para 09/11. O teto voltou a 1 GB às 03:45 UTC de 09/11, mas o
   cache precisa reaquecer.
3. **Índice `ix_fato_negociacao_4`:** é mais uma estrutura a manter em
   cerca de 126 mil UPDATEs não-HOT por noite. Isso pesa segundos, não
   45 s. `idx_scan` = 1.304 em 10/11, compatível com as chamadas do Boris+,
   e não com uso pelo `calcular`.

**Checagem feita em 2026-11-11, por volta de 00:30 UTC: o `effective_cache_size`
não é a causa.** O SQL que o `calcular` do `b3_cotahist` gera para a janela
2026-11-09 (captura 364) foi reproduzido a partir do código e da
configuração. Foram 7 statements, rodados com `EXPLAIN` sem ANALYZE, em
transação com ROLLBACK, uma vez sob `'4GB'` e outra sob `'768MB'`. **Os 7
planos saíram idênticos.** O `effective_cache_size` fica em 768 MB.

**Causa provável, medida:** `fato_negociacao` não tem índice em
`captura_id`. Os planos mostram 7 `Seq Scan on fato_negociacao` com
`Filter: (captura_id = 364)`: os 4 campos escalares e o lado `alvo` dos 3
campos de janela. Fora deles, ainda há:

- o SELECT paginado dos campos numéricos (`LIMIT 20000 OFFSET …`), 2
  consultas por onda × 3 ondas;
- o `_carga_no_fim`, um `min(...) WHERE captura_id IN` por campo de janela.

São até cerca de 16 varreduras completas para achar as 15.708 linhas da
carga. Uma delas, isolada, medida com `EXPLAIN (ANALYZE, BUFFERS)`: **24,5 s
e 155 mil páginas lidas do disco** (cerca de 1,2 GB), descartando 1,46
milhão de linhas. Na rodada real parte disso vem do cache, mas a ordem de
grandeza explica boa parte dos 671 s. Também explica a piora contínua: cada
pregão aumenta a tabela.

**U3 aplicado em 2026-11-11 00:38 UTC:** `CREATE INDEX CONCURRENTLY
ix_fato_negociacao_5 ON fato_negociacao (captura_id)`. Levou 48 s; o índice
é válido e ocupa 10 MB, sem reinício. A declaração na classe está no PR #12.
Depois dele, os 7 statements e o SELECT dos numéricos usam `Bitmap Index
Scan on ix_fato_negociacao_5`, e a mesma consulta caiu de 24,5 s para
**2,2 s** a frio.

**Linha de base por campo** (log do `mydata-cron`, rodada de 2026-11-10,
total de 671 s):

| Campo | Tipo | s | O índice alcança |
|---|---|---|---|
| `ticker_objeto` (inclui ANALYZE) | escalar | 32 | sim |
| `preco_objeto`, `taxa_livre_risco`, `hv21_objeto` | escalar | 25 + 27 + 26 | sim |
| `log_retorno`, `hv21`, `hv63` | janela | 130 + 154 + 121 | só o lado `alvo`; a subconsulta lê a tabela inteira por definição |
| `prazo_anos`, `volatilidade_implicita`, gregas | numérico | 52 + 54 + 51 | os 2 SELECTs por onda (cerca de 49 s por onda) |

**Estimativa (substitui a contagem de "até 16 varreduras"):** −250 a
−300 s, com o `calcular` entre cerca de 370 e 420 s. Os três campos de
janela, cerca de 330 s depois do índice, passam a ser o grosso da fase.
Abaixo disso, o caminho é a leitura escopada (`escopo-calcular`, QW7).
Confirma ou derruba no cron de 11/11 06:00 UTC.

**Resultado no cron de 2026-11-11 (janela 2026-11-10): `calcular` = 394,2 s
em `log_fase`**, contra 671,1 s (−277 s, −41 %). Ficou dentro da estimativa
e abaixo de 400 s: é a **1ª de 3 noites úteis** da pré-condição do F2.

| Campo | Tipo | 10/11 (s) | 11/11 (s) |
|---|---|---|---|
| `ticker_objeto` (inclui ANALYZE) | escalar | 32 | ~17 (por diferença) |
| `preco_objeto` / `taxa_livre_risco` / `hv21_objeto` | escalar | 25 / 27 / 26 | 2,8 / 3,6 / 3,1 |
| `log_retorno` / `hv21` / `hv63` | janela | 130 / 154 / 121 | 114,7 / 118,0 / 127,6 |
| `prazo_anos` / `volatilidade_implicita` / gregas | numérico | 52 / 54 / 51 | 2,2 / 2,9 / 2,2 |

Os tempos por campo são a diferença entre linhas consecutivas
`campo calculado aplicado` do log do `mydata-cron`. O `ticker_objeto` não
tem marca de início no log, então é o total de `log_fase` menos a soma dos
outros campos.

- **Escalares e numéricos:** de ~287 s para ~34 s. O índice resolveu o
  que alcançava.
- **Janela:** de ~405 s para ~360 s, ou 91 % da fase. A subconsulta lê
  `fato_negociacao` inteira por definição e cresce a cada pregão.
- **Folga de 6 s sobre os 400 s.** A série sob 1 GB subia cerca de +12 s
  por noite útil, puxada pelo crescimento da tabela, e é isso que os campos
  de janela ainda pagam. É provável que a 2ª ou a 3ª noite estoure. Se
  estourar, o próximo passo é a leitura escopada do QW7 (`escopo-calcular`,
  `b948320`), e não subir memória.
- **Sem efeito colateral:** Postgres sem reinício desde 09/11 01:29 UTC,
  `memory.max` 999997440, pico de 1021 MB em 24 h (anon ~30 MB, o resto
  cache), 7 cargas publicadas, sem falha em 48 h.

**Noites seguintes (estimadas pelo log do `mydata-cron`):** 12/11 ≈ 392 s,
13/11 ≈ **408 s**. A estimativa é o intervalo entre `aplicado: ticker_objeto`
e `aplicado: rho` (374,9 s e 391,0 s), mais os ~17 s do `ticker_objeto`
medidos em 11/11. O `log_fase` não foi lido porque o SSH ao Postgres estava
bloqueado pelo sandbox da sessão. Mesmo com ±5 s de erro, 13/11 passa de
400 s. A piora de +16 s em uma noite é a dos campos de janela, como previsto.
A contagem do F2 recomeça depois do QW7.

### Ocupação em 2026-11-13 (22:41 BRT)

Fontes: métricas e logs do Railway e `railway usage`. Sem SSH, não há
tamanho por tabela nem por camada.

| Item | Valor |
|---|---|
| Banco (`banco=` no log da carga) | 2.704,9 MB; +19 MB desde 11/11, cerca de +9–10 MB por noite útil |
| Volume do Postgres | 4,27 GB de 50 GB (8,5 %), pico de 4,50 GB em 24 h; ~1,5 GB além do banco (WAL e catálogo, não separado) |
| Projeção do motor | 5,4 GB em 12 meses |
| Bronze capturado por noite útil | `b3_instrumentos` 20,3 MB, `b3_proventos_*` 2,4 + 2,4 MB, `b3_cotahist` 0,5 MB, BCB ~1 MB |
| Memória do Postgres (24 h) | atual 997 MB, média 828 MB, pico no teto de 1 GB; sem reinício, OOM ou FATAL desde 11/11 |
| Memória do `mydata` / `mcp` | ~68–71 MB cada, nunca dormem (coletor do console, QW3) |
| CPU do Postgres | média 0,3 %, pico de 46 % no cron |
| Fatura 14/10–14/11 | US$ 17,42 até agora (Postgres US$ 14,92); fecha perto de US$ 18 |
| Ritmo atual | US$ 1,00 em 61,4 h entre 11/11 09:18 e 13/11 22:41, ou cerca de **US$ 11,9/mês** |

O banco cresce menos que o bronze capturado (cerca de 9 contra 27 MB por
noite). A hipótese é que captura com o mesmo hash não seja regravada; não
foi verificada. As métricas do Postgres mostram mínimo 0 em todas as
medidas ao mesmo tempo, o que foi tratado como falha de coleta: o log não
tem nenhum sinal de reinício.

## 6. Como medir de novo

```bash
railway usage projects --project mydata --period current
railway metrics -p f6b2f799-fe75-459b-8fbb-acca54b36bec -e production -s Postgres --since 7d --memory
railway ssh -p f6b2f799-fe75-459b-8fbb-acca54b36bec -e production -s Postgres -- \
  sh -c 'grep -E "^(anon|file|shmem|kernel) " /sys/fs/cgroup/memory.stat; cat /sys/fs/cgroup/memory.max'
```
