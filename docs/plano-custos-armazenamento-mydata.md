# Plano de otimização de custo, armazenamento e frescor — mydata

Data-base: 2026-09-04. Escopo: `~/dev/mydata`, produção em `mydata.semente.dev` (Railway, Postgres). Fonte dos números: `log_execucao` e catálogo do Postgres de produção (somente leitura), `docs/contrato-consumidor.md`, `app/seed_fontes.py`.

---

## 1. Resumo executivo

O problema central não é custo. É contrato quebrado.

- `negociacao_b3` declara `sla_horas = 96` em `app/seed_fontes.py` e expõe isso publicamente em `GET /v1/meta/frescor`. A última publicação bem-sucedida é anterior a 27/08; hoje é 04/09. Idade do dado > 190h contra SLA de 96h — mais de 2× o limite que o próprio sistema anuncia.
- O consumidor afetado é o MCP serviço (`mcp.semente.dev`), cujas onze tools de opções e setups alimentam decisão de trade em near-real-time. Boris+ (`b3-agente`) e Portal MCP consomem a mesma classe.
- Causa: a fase `calcular` de `b3_cotahist` (`app/motor/calculados.py`) recomputa `fato_negociacao` inteira a cada pregão. Pior execução: 81.361.105 ms (22h36) para 734.526 linhas — 9 linhas/s. Esse throughput não é explicado por volume; é explicado por forma de escrita (hipótese: UPDATE por linha ou loop Python, ver A2). Combinado com cron diário (`59 23 * * 1-5`) e ausência de trava de concorrência, produziu 4 execuções presas em `recomputando` (27/08, 28/08, 01/09, 02/09) e zero publicações desde então.
- O achado #2 (deadlock `cvm_itr`, 80% de falha via cron) é o mesmo defeito estrutural — sem trava por dataset+janela — visto por outro dataset.

Reordenação de prioridade resultante:

| Prioridade | Critério | Itens |
|---|---|---|
| P0 | Violação de SLA ativa contra consumidor de decisão | A1–A5 |
| P1 | Risco operacional confirmado em produção | B1–B3 |
| P2 | Redução de CPU/tempo (carga integral vs. incremental) | C1–C3 |
| P3 | Sem urgência (retenção, índices, ergonomia de API) | Seções 3 e 4 |

Armazenamento (2.470 MB de 50.000 MB, 4,9%) não justifica nenhuma ação agora. Seção 3 define o critério objetivo de quando revisitar.

---

## 2. Plano de ação priorizado

Cada item: problema → por que importa → fix → risco/esforço → agente e justificativa → critério de aceite.

Nenhum item usa `ecc:security-reviewer`: nada aqui toca autenticação, chave de API ou escopo de consumidor. Se A1 ou B1 exigirem credencial nova de banco, aí sim acionar.

### P0 — Restabelecer `negociacao_b3` dentro do SLA

#### A1. Destravar produção hoje (intervenção manual, antes de qualquer código)

- Problema: 4 execuções em `recomputando` sem processo vivo por trás (o container Railway já reiniciou desde 27/08). O motor provavelmente trata status não-terminal como "em andamento" e o cron seguinte ou empilha ou pula.
- Por que importa: enquanto essas linhas existirem, nenhuma correção de código publica nada. É pré-requisito de tudo.
- Fix:
  1. Confirmar que não há backend Postgres ativo para essas execuções (`pg_stat_activity` filtrado por `application_name`/query contendo `fato_negociacao`). Se houver, `pg_cancel_backend`, não `pg_terminate_backend`, primeiro.
  2. Marcar as 4 execuções como `abortada` (ou o status terminal de falha que `log_execucao` já usa), com `erro = 'abortada manualmente 2026-09-04: fase calcular sem término, ver plano'`.
  3. Rodar uma execução única de `b3_cotahist` para a janela pendente, fora do cron, em horário sem outro dataset agendado, e acompanhar com `pg_stat_activity` até a fase `calcular`. Se ela ultrapassar 2h, cancelar — a correção A2/A3 é obrigatória antes de tentar de novo.
  4. Verificar `GET /v1/meta/frescor` reportando `negociacao_b3` com `idade_horas < 96`.
- Risco/esforço: baixo esforço, risco médio (é escrita em `log_execucao` de produção). Não executar dentro de transação longa; três UPDATEs pontuais.
- Agente: sessão manual, sem agente. É decisão operacional sobre estado de produção com escrita direta no Postgres; não é tarefa de código e exige o Alex validando cada comando antes de rodar. O SQL de limpeza pode passar por `ecc:database-reviewer` antes, mas a execução é humana.
- Aceite: `SELECT count(*) FROM log_execucao WHERE status='recomputando'` = 0; `/v1/meta/frescor` mostra `negociacao_b3` dentro do SLA; execução manual registrada com `delta_linhas > 0`.

#### A2. Perfilar a fase `calcular` de `b3_cotahist` antes de redesenhar

- Problema: 734.526 linhas em 81.361.105 ms = 9,03 linhas/s. Uma window function particionada sobre 734k linhas em Postgres leva segundos, não horas. Os 835 MB para 734k linhas (≈1,14 KB/linha) também são anômalos para uma tabela de negociação — sugere colunas calculadas largas ou, mais provável, dead tuples acumulados por UPDATE integral repetido a cada recompute.
- Por que importa: se a causa for forma de escrita (UPDATE linha a linha, loop Python sobre cursor, commit por linha, índice ausente em `(chave_natural, data_pregao)`), escopar a partição (A3) reduz o problema mas não o resolve — e o custo continuará crescendo ~20k linhas/pregão.
- Fix: rodar `calcular` de `b3_cotahist` contra cópia local (DuckDB ou Postgres local restaurado de dump) com `EXPLAIN (ANALYZE, BUFFERS)` nas queries emitidas e `cProfile`/`py-spy` no processo. Entregável: lista das 3 maiores fontes de tempo, com percentual, e o diff mínimo que as elimina (tipicamente: trocar loop por `UPDATE ... FROM (SELECT ... OVER (PARTITION BY ...)) AS calc WHERE ...` set-based, uma transação por fase, índice composto).
- Risco/esforço: 2–4h de profiling; risco nulo (não toca produção).
- Agente: `ecc:performance-optimizer`. O item é literalmente encontrar onde vão 22h de runtime num processo Python+SQL; é profiling de gargalo, não decisão de arquitetura nem revisão de schema. Sai daqui com evidência para A3 e A5, não com opinião.
- Aceite: relatório de profiling com tempo por query/função; reprodução local do gargalo; fase `calcular` integral (sem escopo ainda) abaixo de 10 min em cópia local com o fix mínimo aplicado.

#### A3. Recompute escopado por partição × janela de lookback em `app/motor/calculados.py`

- Problema: a fase recalcula toda a história de todos os tickers a cada pregão. Como um pregão COTAHIST toca praticamente todos os instrumentos ativos, escopar só por ticker afetado não basta — o escopo tem de ser bidimensional: `chave ∈ delta` **e** `data_pregao ≥ min(data_delta) − lookback`, onde `lookback` é a maior janela usada por qualquer campo derivado (ex.: se há média de 200 pregões, lookback = 200 pregões da chave, não 200 dias-calendário).
- Por que importa: é o que permite que o cron diário termine em minutos e que `negociacao_b3` respeite 96h de forma estável — e que sobre folga para apertar o SLA se o MCP serviço precisar (ver D3).
- Fix:
  1. Declarar `lookback` como metadado de cada campo calculado (no mesmo lugar onde o campo é definido, não hard-coded na fase), com `lookback_efetivo = max(lookbacks)` da tabela.
  2. A fase recebe o conjunto `delta` (chaves + `min_data`) da fase silver — o motor já sabe `delta_linhas`, falta passar as chaves.
  3. Computar em CTE: `SELECT ... OVER (PARTITION BY chave ORDER BY data_pregao)` restrito a `chave IN delta AND data_pregao >= min_data − lookback_efetivo`, gravar só onde `data_pregao >= min_data` (as linhas de lookback são lidas, não escritas).
  4. Manter caminho `--integral` explícito para reapresentação/reprocessamento total, como flag de execução, não como default.
  5. Regra de degradação: se `delta` for vazio, a fase é no-op e loga isso; se `delta` > 50% das chaves, cair para integral (evita CTE gigantesca com `IN` de dezenas de milhares de valores — usar tabela temporária de chaves, não literal).
- Risco/esforço: 1–2 dias. Risco médio: campo derivado que dependa de linha fora do lookback declarado produz valor divergente silenciosamente — por isso A4 é bloqueante.
- Agente: `anthropic-skills:data-llm-architect`. É decisão de contrato de pipeline (incremental vs. full, granularidade do delta, lookback como metadado, regra de fallback) — exatamente o domínio da skill própria do Alex para arquitetura de dado; a implementação SQL resultante vai para revisão em A5.
- Aceite: fase `calcular` de um pregão normal < 5 min em produção; `log_execucao` registra `modo=escopado|integral` e tamanho do delta; A4 verde.

#### A4. Teste de equivalência escopado == integral, antes de A3 tocar produção

- Problema: não existe teste que prove que recompute parcial produz o mesmo `fato_negociacao` que o recompute total.
- Por que importa: a classe alimenta decisão de trade; divergência silenciosa num campo de janela é pior que atraso, porque não aparece em `/v1/meta/frescor`.
- Fix: fixture com ~5 tickers × ~300 pregões sintéticos em DuckDB cobrindo bordas (ticker novo sem histórico, ticker sem negociação em dias intermediários, reapresentação alterando linha antiga dentro e fora do lookback). Teste: rodar integral, snapshot; aplicar delta de 1 pregão escopado sobre estado anterior; comparar tabela inteira campo a campo. Segundo teste: reapresentação fora do lookback deve forçar integral (regra de degradação de A3).
- Risco/esforço: 0,5–1 dia. Sem risco.
- Agente: `ecc:tdd-guide`. O fix de A3 não deve existir sem esse teste vermelho antes; o item é escrever a cobertura que trava o comportamento, e a skill é a que impõe red→green antes de mexer no motor.
- Aceite: os dois testes passam em DuckDB e em Postgres (CI roda contra ambos, dado que `ON CONFLICT ... WHERE` e window functions têm semântica ligeiramente diferente entre os dois).

#### A5. Revisão de schema, índices e bloat de `fato_negociacao`

- Problema: 1,14 KB/linha; recompute integral reescreve todas as linhas a cada execução → dead tuples, índices inchados, autovacuum atrasado. Pode ser parte relevante das 22h (cada UPDATE sobre página cheia de tuplas mortas custa mais).
- Fix: medir `n_dead_tup`, `n_live_tup`, `last_autovacuum` em `pg_stat_user_tables`; `pgstattuple` se a extensão estiver disponível no Railway; `VACUUM (ANALYZE)` após A1; avaliar `VACUUM FULL` ou `pg_repack` numa janela combinada (lock exclusivo — só com o Alex ciente). Garantir índice composto `(chave_natural, data_pregao)` e que a query de A3 o usa (`EXPLAIN` sem Seq Scan na partição escopada). Mesma inspeção em `fato_conta` (1,45 KB/linha, mesmo padrão via `cvm_itr`), com prioridade menor.
- Risco/esforço: 2–4h. `VACUUM FULL` é a única operação com risco (lock), fica opcional.
- Agente: `ecc:database-reviewer`. Bloat, autovacuum, plano de execução e índice composto são revisão de Postgres, não de Python; é o agente que lê `EXPLAIN` e `pg_stat_*` como primeira língua.
- Aceite: `n_dead_tup / n_live_tup < 0,2` após vacuum; plano de A3 usa Index Scan; tamanho de `fato_negociacao` registrado antes/depois.

### P1 — Risco operacional confirmado

#### B1. Trava de execução concorrente por (dataset, janela)

- Problema: sem trava, dois crons/execuções manuais sobre o mesmo dataset+janela rodam em paralelo. Já produziu `DeadlockDetected` em `cvm_itr` (execuções 24 e 26, sobrepostas 06:17:39–07:31:00 em 04/08) e é o que transformou uma fase lenta em 4 execuções presas em `b3_cotahist`.
- Por que importa: 80% de falha do `cvm_itr` via cron (8/10) — pelo menos 1 é essa causa, as outras 7 são B3. Sem trava, A3 pode até acelerar e ainda assim colidir com execução manual.
- Fix: duas camadas, ambas necessárias.
  1. Postgres: `pg_try_advisory_xact_lock(hashtext(dataset || ':' || janela))` no início da execução; se retornar `false`, registrar em `log_execucao` com status `pulada` e motivo `execução concorrente id=N` e sair com código 0 (cron não deve tratar como falha).
  2. Índice único parcial em `log_execucao (dataset, janela) WHERE status IN ('executando','recomputando')` como cinto de segurança — garante invariante mesmo se alguém contornar o advisory lock. Requer migração e limpeza prévia (A1).
  3. DuckDB local não tem advisory lock: fallback com `fcntl.flock` sobre arquivo em `$DATA_DIR/.lock/<dataset>-<janela>` atrás da mesma interface.
- Risco/esforço: 0,5–1 dia. Risco baixo; o índice parcial falha ruidosamente se houver estado inconsistente, o que é o comportamento desejado.
- Agente: `ecc:database-reviewer`. O núcleo é semântica de lock em Postgres (advisory xact vs. session, interação com pool de conexões do FastAPI, índice parcial como invariante) — errar aqui produz um lock que não solta ou que não trava; é o domínio do agente de banco, não do de Python.
- Aceite: teste de integração que dispara duas execuções do mesmo dataset+janela em paralelo e verifica exatamente uma `concluída` e uma `pulada`; zero `DeadlockDetected` em `log_execucao.erro` nos 30 dias seguintes.

#### B2. Timeout por fase e reconciliação de estado no boot

- Problema: status `recomputando` não é terminal e nada o expira. Container reiniciado (deploy no Railway, OOM, restart) deixa a execução órfã em estado "em andamento" para sempre. É a mecânica exata pela qual as 4 execuções ficaram presas sem ninguém saber por 8 dias.
- Fix:
  1. `timeout_s` por fase, configurável por dataset (default: `calcular` 2h, `silver` 1h, `captura` 30 min). Estouro → status `falha`, `erro='timeout fase X após Ns'`, `pg_cancel_backend` na própria conexão.
  2. Heartbeat: `log_execucao.atualizado_em` tocado a cada N segundos pela fase em andamento.
  3. No startup da aplicação: qualquer execução em status não-terminal com `atualizado_em` mais velho que `2 × timeout` da fase vira `abortada` com motivo `órfã no boot`. Isso substitui o passo manual de A1 daqui em diante.
- Risco/esforço: 1 dia. Risco baixo. Cuidado: timeout via `asyncio.wait_for` não cancela query síncrona em thread — precisa `statement_timeout` na sessão Postgres além do timeout Python.
- Agente: `ecc:python-reviewer`. É máquina de estados, tratamento de exceção, cancelamento e ciclo de vida de processo em Python — o valor está em não deixar exceção engolida nem status inconsistente entre thread e transação; revisão idiomática de Python é o fit, com o detalhe do `statement_timeout` explicitado na tarefa.
- Aceite: teste que mata a fase no meio (raise em callback) e verifica status terminal; teste de boot com execução órfã na fixture; nenhum status não-terminal com `atualizado_em` > 3h em produção após deploy.

#### B3. Triagem das 7 falhas não investigadas do `cvm_itr`

- Problema: das 8 falhas em 10 crons, só o deadlock foi lido. Os outros 7 `erro` em `log_execucao` podem ser a mesma causa, timeout, parse de zip CVM, memória ou algo novo.
- Fix: `SELECT id, iniciado_em, fase, left(erro, 300) FROM log_execucao WHERE dataset='cvm_itr' AND status='falha' ORDER BY iniciado_em`, classificar em ≤ 4 buckets, abrir item de código só para bucket com ≥ 2 ocorrências. Se ≥ 5 forem deadlock/concorrência, B1 fecha o dataset; se forem timeout, A2/C1 fecham.
- Risco/esforço: 30 min, somente leitura.
- Agente: sessão manual, sem agente. É leitura de 7 mensagens de erro em produção e classificação por julgamento; delegar custa mais que fazer, e a saída é decisão de roteamento, não código.
- Aceite: tabela `causa → contagem → item deste plano que resolve` anexada a este documento.

### P2 — Redução de CPU/tempo (carga integral que deveria ser incremental)

#### C1. Dedupe por linha no silver via hash de conteúdo (cobre `cvm_itr`, `b3_instrumentos`, `cvm_cadastro`, `b3_listadas`)

- Problema: bronze deduplica por sha256 do payload inteiro; basta 1 byte diferente (data de geração, uma empresa nova) para o payload ser "novo" e o silver reprocessar tudo: parse + upsert + qualidade sobre 100% das linhas quando 6,9% (`b3_instrumentos`), 8,2% (`cvm_itr`), 16,0% (`cvm_cadastro`), 16,7% (`b3_listadas`) são delta real. `b3_instrumentos` é o caso extremo: 2.662.014 linhas processadas/dia para 182.958 novas no período.
- Por que importa: é onde está o tempo de CPU do cron fora do `b3_cotahist`; `cvm_itr` com 80% de falha sofre de reload integral de `fato_conta` (939.428 linhas, 1.363 MB) a cada execução — o mesmo padrão de bloat de A5.
- Fix:
  1. Coluna `hash_conteudo` (sha256 dos campos de negócio normalizados, excluindo timestamps de captura) em cada tabela silver.
  2. Upsert passa a ser `INSERT ... ON CONFLICT (chave_natural) DO UPDATE SET ... WHERE tabela.hash_conteudo IS DISTINCT FROM EXCLUDED.hash_conteudo`. Linha idêntica não gera escrita, não gera dead tuple, não entra no delta de `calcular`.
  3. `delta_linhas` passa a ser contado por `RETURNING` (ou `xmax = 0` para distinguir insert de update), e é esse conjunto que A3 recebe como escopo.
  4. Parse continua integral (é CPU barata e necessária para calcular o hash); o que se evita é a escrita e tudo a jusante.
- Risco/esforço: 1–2 dias para o mecanismo genérico + 0,5 dia por dataset. Risco: paridade DuckDB — `ON CONFLICT DO UPDATE ... WHERE` existe em ambos, mas testar; e a normalização do hash precisa ser determinística entre Python e SQL (calcular sempre em Python antes do insert, nunca em SQL, para não divergir entre engines).
- Agente: `anthropic-skills:data-llm-architect`. A decisão de granularidade do incremental (payload → documento → linha), o que entra ou não no hash, e como o delta flui para a fase seguinte é desenho de pipeline medallion — é a skill própria do Alex para isso e é a mesma que desenhou A3, o que mantém o contrato de delta coerente entre silver e calculados.
- Aceite: `linhas_silver` continua integral no log, mas nova métrica `linhas_escritas ≈ delta_linhas` (razão > 0,9) em `b3_instrumentos`, `cvm_cadastro`, `b3_listadas`, `cvm_itr` por 5 execuções consecutivas; tempo de silver de `b3_instrumentos` reduzido em ≥ 70%.

#### C2. Short-circuit quando o payload bronze é idêntico (cobre `cvm_dfp_empresa`, séries BCB)

- Problema: `cvm_dfp_empresa` tem 0,0% de delta — reload total sem nenhuma linha nova — e as séries BCB (câmbio/cdi/ipca/selic) 4,2–4,5%. Se bronze já sabe que o sha256 é repetido, silver/calculados/qualidade não deveriam rodar.
- Fix: na fase captura, se o sha256 já existe em bronze **e** já foi aplicado no silver (guardar `sha256_aplicado` na execução que o processou), encerrar a execução com status `concluída`, `delta_linhas = 0`, motivo `payload idêntico a execução id=N`. O frescor deve contar isso como "verificado agora, sem mudança" — `idade_horas` zera, porque a fonte foi consultada e é a mesma; caso contrário `/v1/meta/frescor` reportaria dado "velho" que na verdade é atual.
- Risco/esforço: 2–4h. Risco baixo. Custo irrelevante nas séries BCB (centenas de linhas), mas é o mesmo código, sai de graça.
- Agente: `ecc:python-reviewer`. É fluxo de controle no motor (early return com estado consistente e log correto), sem decisão de arquitetura nova; a armadilha é o frescor — o revisor de Python é quem vai checar que `concluída sem delta` atualiza o carimbo de frescor.
- Aceite: execuções de `cvm_dfp_empresa` terminam em < 30 s quando o payload não mudou; `/v1/meta/frescor` reflete a verificação.

#### C3. Bloat de `fato_conta` e revisão de índices das tabelas gold

- Problema: 1.363 MB / 939.428 linhas; mesmo padrão de A5 causado pelo reload integral de `cvm_itr` (resolvido por C1). Só faz sentido depois de C1, senão o bloat volta.
- Fix: idem A5 aplicado a `fato_conta`; conferir índices usados pelas views gold servidas em `/v1` (as 4 classes do contrato).
- Risco/esforço: 2h. Baixo.
- Agente: `ecc:database-reviewer`, pelo mesmo motivo de A5.
- Aceite: bloat < 20%; nenhum Seq Scan nas queries das views das 4 classes com consumidor.

---

## 3. Otimização de armazenamento

Separado do plano de execução porque nada aqui é urgente: 2.470 MB de 50.000 MB (4,9%), TOAST comprimindo bronze ~5,8×. As duas maiores tabelas (`fato_conta`, `fato_negociacao`) são gold com `politica_versao=max_versao` — não empilham reapresentação, mantêm só a versão mais recente por chave natural. O custo real está em CPU (seção 2, C1/C2), não em bytes.

### 3.1 Datasets com captura full-snapshot

| Dataset | Delta real | Natureza da fonte | Ação na captura | Ação no silver |
|---|---|---|---|---|
| `b3_instrumentos` | 6,9% | Arquivo diário completo da B3, sem endpoint delta | Nenhuma — a fonte não oferece incremental | C1 (hash por linha) |
| `cvm_cadastro` | 16,0% | CSV semanal completo da CVM | Nenhuma | C1 |
| `b3_listadas` | 16,7% | Lista completa | Nenhuma | C1 |
| `cvm_dfp_empresa` | 0,0% | Derivado de DFP | C2 (short-circuit por sha256) | — |

"Virar incremental na captura" não é possível para essas fontes: B3 e CVM publicam snapshot, não diff. O incremental verdadeiro só existe a partir do silver, que é onde C1 atua. Isso significa que bronze continuará recebendo 1 snapshot completo por captura — decisão aceita, com o seguinte enquadramento:

- `b3_instrumentos`: 17 capturas = 575 MB lógicos ≈ 100 MB físicos com TOAST. 0,2% do volume. Não compensa delta-encoding de bronze (guardar só diff entre snapshots) — isso quebraria a propriedade "bronze é o bruto reproduzível" por 100 MB. Manter como está.
- `cvm_cadastro` e `b3_listadas`: proporcionalmente menores. Manter.
- Se um dia `b3_instrumentos` for problema, a única compactação que não fere o modelo é reter snapshot completo semanal e descartar os diários intermediários que não introduziram delta no silver (C1 é quem sabe dizer isso) — mas só quando o critério 3.2 disparar.

### 3.2 Retenção de bronze: não fazer nada agora

Bronze é indefinido por desenho — a CVM permite reapresentação e `is_latest` é flag, não corte. Nenhuma política de expurgo em bronze CVM, em nenhum cenário. Bronze B3 (`b3_instrumentos`, `b3_listadas`, COTAHIST) não tem a mesma justificativa regulatória, mas hoje não há motivo de custo para diferenciá-lo.

Critério objetivo de revisita (qualquer um dispara):

1. Uso do volume ≥ 40% (20.000 MB).
2. Bronze físico (`pg_total_relation_size` das tabelas bronze) ≥ 50% do banco.
3. Crescimento mensal medido em 3 meses consecutivos projetando 40% em < 12 meses. Referência atual: `fato_negociacao` cresce ~20k linhas/pregão ≈ 440k linhas/mês; com 1,14 KB/linha (que A5 deve reduzir) são ~500 MB/mês só nessa tabela — se A5 não reduzir a largura, o critério 3 dispara em ~6 meses. Isso é o argumento para A5 ser P0 e não P3.

Quando disparar: primeiro aplicar A5/C3 (bloat) e medir de novo; só depois discutir compactação de bronze B3 (3.1, último parágrafo). Registrar as três métricas mensalmente num job leve — pode ser uma regra em `app/motor/alertas.py` (seção 4) com severidade `info`.

---

## 4. Agilidade de dado recente para decisão

O sistema já tem os dois lados da transparência: `sla_horas` por classe em `app/seed_fontes.py` e `GET /v1/meta/frescor` reportando `idade_horas` contra ele. O que faltou foi o próprio mydata reagir ao seu sinal antes do consumidor. Quatro crons presos por 8 dias sem alerta é o custo de ter o termômetro sem o alarme.

### D1. Regra de alerta de frescor em `app/motor/alertas.py`

- Escopo: só classes com consumidor de produção declarado em `docs/contrato-consumidor.md` (`empresa`, `demonstracao_financeira`, `negociacao_b3`, `provento_b3`). As demais seguem sem alerta para não gerar ruído.
- Métrica: `razao_sla = idade_horas / sla_horas`, avaliada a cada execução do scheduler (não só ao fim de uma execução do dataset — senão a execução presa nunca dispara).
- Limiares (para `negociacao_b3`, SLA 96h):
  - `aviso` em 0,5 (48h) — equivale a um cron diário perdido; é acionável.
  - `crítico` em 0,8 (~77h) — ainda dá para intervir manualmente antes da violação.
  - `violação` em 1,0 (96h) — registro obrigatório em `log_execucao` ou tabela própria, para que a violação fique auditável, não só notificada.
- Segunda regra, independente da primeira: execução em status não-terminal com `atualizado_em` (heartbeat de B2) mais velho que `timeout` da fase → `crítico`. Teria disparado em 28/08 de manhã.
- Terceira regra: duas execuções do mesmo dataset+janela em status não-terminal → `crítico` (redundante com B1, mas detecta se B1 for contornado).
- Canal: o que `alertas.py` já usa. Se hoje só loga, o item inclui um canal que chega ao Alex (o que ele já usa nos outros projetos — não escolher aqui).
- Agente: `ecc:python-reviewer`. É regra de avaliação periódica com limiares e deduplicação de alerta (não disparar `aviso` a cada minuto enquanto a razão fica em 0,6) — lógica de Python idiomática sobre módulo existente; não há arquitetura nem SQL nova.
- Aceite: teste que simula `idade_horas` em 47h/49h/77h/97h e verifica exatamente qual severidade sai; teste de deduplicação; em produção, o alerta `aviso` de `negociacao_b3` dispara ao menos uma vez nos 30 dias seguintes (se nunca disparar, ou A3 está perfeito ou a regra está morta — checar).

### D2. Expor `razao_sla` e severidade em `GET /v1/meta/frescor`

- Problema: o consumidor recebe `idade_horas` e `sla_horas` e tem de calcular; o MCP serviço, que serve decisão de trade, precisa de um campo pronto para gatear tool (`ok | degradado | violado`) sem reimplementar limiar.
- Fix: adicionar `razao_sla: float` e `estado: Literal['ok','aviso','critico','violado']` ao schema Pydantic da resposta, mesmos limiares de D1 (única fonte de verdade: função compartilhada em `alertas.py` chamada pelo endpoint). Aditivo, sem quebrar contrato; incluir `consumidores: list[str]` por classe é opcional e útil para o próprio Alex ver quem depende de quê.
- Agente: `ecc:fastapi-reviewer`. É mudança de contrato de API versionada com Pydantic — o risco é quebrar compatibilidade com três consumidores; o revisor de FastAPI é quem checa aditividade, tipos e que o schema OpenAPI publicado reflete o campo novo.
- Aceite: campos novos no OpenAPI; resposta antiga continua válida para cliente que ignora campos desconhecidos; teste de contrato.

### D3. O SLA de 96h para `negociacao_b3` é o SLA certo? (decisão do Alex)

- 96h é generoso para Boris+ (refresh semanal) e provavelmente inútil para as tools de opções do MCP serviço: série de negociação com 4 dias de idade não serve para setup de opção. O SLA declarado hoje diz "confie no dado" num momento em que a decisão de trade não deveria confiar.
- Mas apertar `sla_horas` antes de A1–A5 é declarar um contrato que o sistema não cumpre — pior que o atual.
- Ordem: fechar A1–A5 e B1–B2; medir por 10 pregões o tempo real do cron; então perguntar ao MCP serviço qual é a necessidade real (D+1 = ~30h contando cron 23:59 + processamento). Se for D+1, ajustar `sla_horas` de `negociacao_b3` em `app/seed_fontes.py` para 30–36h e os limiares de D1 seguem automaticamente.
- Agente: sessão manual, sem agente. É decisão de produto e negociação com consumidor externo; nenhuma skill do catálogo substitui o Alex nisso. A mudança de código resultante é uma linha.

---

## 5. O que fica fora do mydata

Regra de fronteira do projeto: dívida do lado do consumidor é registrada aqui para o Alex negociar, não vira tarefa neste repositório.

1. Boris+ / `b3-agente` ainda roda ingestão paralela própria de COTAHIST/Yahoo/brapi. Migração para consumir só o mydata está "parcial" — cliente existe, não há confirmação de que as fontes duplicadas foram desligadas. Consequência para o mydata: enquanto isso não for confirmado, não se sabe se Boris+ realmente depende de `negociacao_b3` ou se o fallback dele mascarou a violação de SLA da última semana. Ação: perguntar, não corrigir.
2. MCP serviço deve gatear suas tools de opções pelo `estado` de `/v1/meta/frescor` (D2). O mydata fornece o sinal; usar ou não é decisão deles. Se não gatearem, a próxima violação chega ao cliente final deles sem aviso.
3. Necessidade real de frescor do MCP serviço (D+1? intradiário?) — insumo para D3. Sem essa resposta, o mydata mantém 96h.
4. Contabilidade de quota do MCP serviço para os clientes dele (2.000/dia por cliente, 10.000 somados) é interna a ele; o mydata só garante 120/min · 20.000/dia para o serviço como um todo.
5. Portal MCP (`b-mcp.semente.dev`): nenhuma pendência conhecida. Fica listado para constar que foi considerado.

---

## 6. Nota de execução

Nenhum item deste plano é commitado ou pushado sem confirmação explícita do Alex antes de cada push. Push em `main` dispara auto-deploy no Railway, e um deploy no meio de uma execução do motor é exatamente o mecanismo que deixa execução órfã em `recomputando` (B2). Ordem operacional obrigatória: A1 (manual, em produção, sem código) → A2/A4 (local) → A3/A5/B1/B2 num único deploy combinado com o Alex, em horário sem cron agendado → observar 5 pregões → C1/C2/C3/D1/D2. D3 só depois de tudo.

Fora do escopo deste plano por não caber em nenhum agente do catálogo: nada. Todo item tem dono definido acima.
