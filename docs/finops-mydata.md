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

### F2. Baixar para 512 MB depois de 7 dias limpos com F1

- **Ganho:** mais cerca de −$5/mês. Memória do Postgres a no máximo $5/mês.
- **Aceite:** o mesmo de F1, por mais 7 dias.
- **Kill:** um OOM volta para 1 GB, sem segunda tentativa.

### F3. `calcular` sem regravar linha que não mudou — NO CÓDIGO em 2026-11-02, falta deploy e medição

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

### Não fazer por custo

- **Limpeza de silver (fato_conta não-latest, mercados fora de gold, opções
  vencidas):** cerca de 500 MB, cerca de $0,08/mês. Só se justifica por
  outra razão. Ver [análise de limpeza](analise-limpeza-dados.md).
- **Retenção de bronze:** 214 MB guardados. Irrelevante, e o ADR-10 proíbe.
- **Trocar o Postgres do Railway por serviço externo:** a regra de custo do
  projeto proíbe, e o problema é configuração, não plataforma.

## 5. Projeção

| Cenário | Postgres/mês | Projeto mydata/mês |
|---|---|---|
| Hoje (ritmo do período) | ≈ $18,5 | ≈ $21 |
| F1 (1 GB) | ≈ $11 | ≈ $13,5 |
| F1 + F2 (512 MB) | ≈ $6 | ≈ $8,5 |

Preço usado: o efetivo da fatura (memória ≈ $10/GB·mês, obtido de $10,30 em
18,6 dias com média de cerca de 1,66 GB). A projeção supõe que o cache enche
até o limite, e por isso é conservadora.

## 6. Como medir de novo

```bash
railway usage projects --project mydata --period current
railway metrics -p f6b2f799-fe75-459b-8fbb-acca54b36bec -e production -s Postgres --since 7d --memory
railway ssh -p f6b2f799-fe75-459b-8fbb-acca54b36bec -e production -s Postgres -- \
  sh -c 'grep -E "^(anon|file|shmem|kernel) " /sys/fs/cgroup/memory.stat; cat /sys/fs/cgroup/memory.max'
```
