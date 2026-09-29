Diagnóstico — retenção de dados históricos e padrão de carga (integral vs. incremental)
mydata · complementa o estudo de redução de custos de 2026-09-04

Metodologia: ao contrário do estudo anterior (só código, sem produção), este usa dado real. Acesso ao Railway autorizado explicitamente para esta tarefa — CLI já autenticado (`alexandre.camerini@gmail.com`), projeto `mydata` vinculado. Consultas somente-leitura direto no Postgres de produção via `DATABASE_PUBLIC_URL` do serviço Postgres, executadas em 2026-09-04. Nenhuma credencial foi impressa nesta conversa; as queries rodaram via `railway run -- bash -c 'psql "$DATABASE_PUBLIC_URL" ...'`, que injeta a variável sem expô-la em texto.

Resumo executivo

A pergunta "cargas integrais ou incrementais" tem resposta diferente por dataset — o motor já registra `linhas_silver` (total processado) e `delta_linhas` (efetivamente novo) por execução, então isto não é estimativa, é medição direta de produção. Achado mais grave: não é um problema de eficiência abstrata, é uma falha operacional ativa — o pipeline diário do `b3_cotahist` está atrasado agora, com 4 execuções presas em `recomputando` sem nunca publicar, porque uma única fase de cálculo já levou 22,6 horas contra um cron diário. Retenção de histórico, por outro lado, não é urgente: o banco usa 2,47 GB de um volume de 50 GB (≈5%).

1. Cargas integrais vs. incrementais, por dataset (dado real, últimos ~35 dias de operação)

| Dataset | Execuções cron | % das linhas processadas que eram delta real | Classificação |
|---|---|---|---|
| b3_cotahist | 17 | 94,4% | Incremental de verdade — cada dia carrega essencialmente só o pregão do dia |
| cvm_dfp | 1 (anual) | 65,8% | Incremental na primeira carga; sem histórico suficiente para julgar recorrência |
| b3_proventos_dinheiro | 2 | ~1,5–49% (oscila) | Parcialmente incremental, mas alto ruído entre execuções |
| cvm_cadastro | 6 (semanal) | 16,0% | Majoritariamente reload — 84% do processamento é redundante toda semana |
| cvm_itr | 2 publicadas de 10 tentativas | 8,2% | Reload quase integral, e falha 80% das vezes (ver seção 3) |
| b3_instrumentos | 17 (diário) | 6,9% | Reload quase integral — 2.662.014 linhas processadas para 182.958 linhas realmente novas |
| b3_listadas | 6 (semanal) | 16,7% | Majoritariamente reload |
| bcb_cambio_usd / cdi / ipca / selic_meta | 24 (diário) | 4,2–4,5% | Reload integral, mas datasets pequenos (centenas de linhas) — custo irrelevante |
| cvm_dfp_empresa | 1 (anual) | 0,0% | Reload total sem nenhuma linha nova detectada |

Leitura correta deste número: baixo % de delta não significa necessariamente desperdício de rede ou de I/O de captura — o bronze já deduplica por hash (achado do estudo anterior), então o download redundante em si é o único custo real de banda em muitos casos. O desperdício de processamento genuíno está em reprocessar `linhas_silver` inteiras (parse + upsert + qualidade) quando a maior parte já existia — isso consome CPU/tempo mesmo quando o upsert final é barato. `b3_instrumentos`, `cvm_cadastro`, `b3_listadas` e `cvm_dfp_empresa` são os candidatos reais a virar delta desde a captura (fonte permitindo) em vez de reload seguido de upsert.

2. O achado crítico: a fase "calcular" já estourou o ciclo de 24h do cron (confirmado, não hipotético)

Isto eleva o achado 3 do estudo de código anterior ("campo de janela sempre recomputado sobre a tabela inteira") de hipótese para incidente medido. Execução mais lenta já registrada:

- Dataset: `b3_cotahist`, janela `2026-08-20`, gatilho `cron`.
- Início: 2026-08-21 06:03:54. Fim: 2026-08-22 04:40:08. Duração total: ~22h36min.
- Fase `baixar`: 1,4s. Fase `carregar`: 2,2s. Fase `calcular`: **81.361.105 ms = 22h 36min** (99,99% do tempo total). Fase `validar`: 2,5s. Fase `publicar`: 6,0s.
- Volume da fase problemática: 20.268 linhas carregadas (100% delta, carga em si é incremental) — mas o cálculo de campo de janela relê `fato_negociacao` inteira (835 MB, 734.526 linhas hoje e crescendo ~19-20 mil linhas/pregão).

Consequência operacional já em curso: o cron do `b3_cotahist` roda `59 23 * * 1-5` (23:59 em dias úteis). Com a fase de cálculo levando mais de 22h, a execução de um dia ainda está rodando quando a próxima já deveria começar. O histórico confirma: 4 execuções cron consecutivas (27/08, 28/08 status incerto, 01/09, 02/09) ficaram em status `recomputando` e nunca chegaram a `publicado` — o pipeline diário de cotação está atualmente atrasado em produção, não é um risco futuro.

Prioridade real, em ordem: isto é o item #1 de todo o diagnóstico (custo e correção), à frente de qualquer coisa levantada no estudo anterior. Escopar a leitura da window function à partição afetada (já sugerido, mantendo a correção do flag `is_latest` para reapresentações) deixa de ser otimização e passa a ser correção de um pipeline que não está terminando dentro do próprio ciclo.

3. Falha de execução: cvm_itr com 80% de taxa de erro, e um deadlock real confirmado

`cvm_itr` teve 8 execuções `falha` em 10 tentativas via cron, e 1 falha adicional via `replay` com erro `DeadlockDetected: deadlock detected` — isto confirma empiricamente o achado 8 do estudo anterior (disparo sem trava contra concorrência), que lá era descrito como "risco teórico, não confirmado como incidente". Agora está confirmado: houve corrida real entre duas execuções do mesmo dataset+janela (`cvm_itr`, janela `2026`, execuções id 24 e 26, sobrepostas entre 06:17:39 e 07:31:00 do dia 04/08). A trava contra execução concorrente (checar `log_execucao` por status "em andamento" antes de aceitar novo disparo, ou advisory lock do Postgres) sobe de prioridade "risco a mitigar" para "causa confirmada de falha recorrente".

As outras falhas registradas são majoritariamente transitórias e não indicam bug: `RuntimeError 404` ao baixar `COTAHIST_D05082026.ZIP` (arquivo do dia ainda não publicado pela B3 no momento da tentativa manual) e `JSONDecodeError` em `b3_proventos_dinheiro` (resposta não-JSON da fonte, cobre o "modo silencioso" já mapeado no achado 1 anterior).

4. Retenção de dados históricos: não é urgente hoje, mas a política ainda não existe

Números reais de produção:

- Banco de dados total: 2.470 MB, contra um volume provisionado de 50.000 MB — ocupação de aproximadamente 4,9%. O estudo anterior levantou isto como preocupação com base em projeção de código; na prática, há folga grande.
- `bronze_captura`: 114 MB em disco (comprimido) para ~667 MB de payload lógico somado — taxa de compressão TOAST de ~5,8x. Reter o bruto é barato hoje.
- Maior consumidor de bronze: `b3_instrumentos`, 575 MB de payload lógico em 17 capturas (17 janelas distintas — cada dia é um snapshot completo, não incremental na origem).
- As duas maiores tabelas do banco não são bronze, são gold: `fato_conta` (1.363 MB, 939.428 linhas reais via `COUNT(*)` — a estatística `n_live_tup` do Postgres está desatualizada, não rode ANALYZE-dependent sizing sem conferir) e `fato_negociacao` (835 MB, 734.526 linhas). O tamanho por linha (~1,1–1,5 KB) é alto para dado tabular — vale investigar largura de coluna/schema, não é característica de acúmulo de versão: `politica_versao` é `max_versao` nessas tabelas, ou seja, o motor já mantém só a versão mais recente por chave natural, não empilha histórico de reapresentação como linhas extras.

Recomendação de retenção, dado que é dado regulatório (CVM/B3): não purgar bronze agora. A CVM permite reapresentação de demonstrações financeiras (achado do estudo anterior, já confirmado no código: `calculados.py` trata isso explicitamente), e a folga de volume (95% livre) remove a urgência financeira de qualquer purga. Definir uma política de retenção continua sendo boa prática de governança — mas não é o gargalo de custo real deste projeto. Se o crescimento seguir o ritmo atual de `b3_cotahist` (~20 mil linhas/pregão em `fato_negociacao`, tabela que já cresceu para 835 MB), vale reavaliar em 6-12 meses, não agora.

O que muda em relação à lista "o que coletar" do estudo anterior

Os itens abaixo, antes marcados como dado faltante, já estão respondidos por esta rodada: tamanho e crescimento do volume Postgres, contagem de execuções por dataset/mês, instrumentação de duração por fase (o campo já existe em `log_fase.duracao_ms`, só não era consultado), taxa de execuções concorrentes. Seguem realmente pendentes, e exigem acesso fora do banco: fatura Railway em R$ (a CLI não expõe billing; precisa do painel), `EXPLAIN ANALYZE` das queries específicas (não rodado aqui para não competir por I/O com o banco de produção enquanto o `b3_cotahist` pode estar processando).

Plano de ação recomendado, por urgência

1. Corrigir a fase `calcular` do `b3_cotahist` antes do próximo pregão — o pipeline já está atrasado; risco crescente de a fila nunca mais alcançar o dia corrente enquanto `fato_negociacao` continuar crescendo ~20 mil linhas/pregão. Escopar a leitura da window function à partição de chaves afetadas quando não houver retroação.
2. Adicionar trava contra execução concorrente do mesmo dataset+janela — causou pelo menos 1 deadlock confirmado em `cvm_itr`.
3. Investigar a taxa de falha de 80% em `cvm_itr` via cron — mesmo descontando o deadlock, sobra falha recorrente não explicada nesta rodada (seria o próximo passo: ler o campo `erro` das 7 falhas restantes, não coletado aqui por limite de escopo).
4. Reduzir reload redundante em `b3_instrumentos`, `cvm_cadastro` e `b3_listadas` — só compensa depois do item 1, já que o custo de CPU desses datasets é ordens de grandeza menor que o da fase `calcular` do cotahist.
5. Retenção de bronze: sem ação agora; revisitar quando o volume passar de ~30-40% de ocupação ou em 6 meses, o que vier primeiro.

Correção do item 1 (2026-09-28, ainda não implantada). O `UPDATE` dos campos de janela (`app/motor/calculados.py`, função `aplicar`) lia `fato_negociacao` inteira na subconsulta da função de janela (`FROM {tabela}`), uma vez por campo (`log_retorno`, `hv21`, `hv63`), mesmo quando a escrita já estava recortada às linhas da carga. Agora, quando o campo declara `retroage=False` e a carga entra no fim da série (`_carga_no_fim`: o menor `dt_pregao` da carga ≥ o maior já existente), a leitura se restringe a (a) partições presentes na carga e (b) dentro delas, às linhas a partir do N-ésimo pregão distinto anterior à carga, onde N sai da configuração do campo (`alcance_para_tras`: 1 para `lag`, 20 e 62 para as molduras de `hv21`/`hv63`). Partição sem N linhas dentro desse corte (papel ilíquido) é lida inteira, e com menos de N pregões na tabela não há corte de data; as duas coisas mantêm o resultado exato. Os filtros são comparações simples (`dt_pregao >= corte`, `codneg = valor`, em `UNION ALL`), para o Postgres poder usar os índices da classe. Com retroação, carga fora de ordem, nulo na ordenação ou na partição da carga, ou alcance que não se deriva da configuração (`lead`, `row_number`, agregado sem moldura, `RANGE`, `FOLLOWING`, `OVER` escrito à mão, subconsulta), o caminho integral de antes continua valendo. Ressalva: a igualdade exata vale para partições com ordem total. `ordena_por=dt_pregao` com `particao_por=codneg` não desempata contratos a termo do mesmo `codneg` no mesmo pregão (distintos só por `prazo_termo`); para essas linhas o valor já era arbitrário no caminho integral, e o escopado pode escolher outro. Corrigir isso é decisão de configuração (`app/seed_fontes.py`), não do motor. Equivalência linha a linha contra o caminho integral e contra o recálculo do zero em `tests/test_leitura_escopada.py`. Estimativa para um pregão típico (~20 mil linhas novas): `log_retorno` passa de ~735 mil para ~40 mil linhas lidas; `hv21` para ~420 mil; `hv63` continua lendo quase tudo enquanto a tabela tiver menos de 63 pregões (hoje ~37) e cai para ~550 mil com 100 pregões — ou seja, o ganho em volume lido cresce com o histórico, não é imediato. Num banco local DuckDB com 760 mil linhas sintéticas o `calcular` inteiro das três janelas leva menos de 1 s nos dois caminhos: só o volume lido não explica 16–44 h, e o que falta medir em produção é o plano do `UPDATE` no Postgres (`EXPLAIN (ANALYZE, BUFFERS)`) e a sobreposição de execuções — `cmd_agendados` decide se está vencido pela última execução `publicado`, então uma execução ainda em `recomputando` não impede a próxima (item 2, ainda sem trava).

Aviso obrigatório: este diagnóstico não envolveu nenhuma ação de escrita, migração ou alteração em produção — só leitura via `SELECT`. Nenhuma credencial do Railway foi exposta nesta conversa ou gravada em arquivo de texto puro.
