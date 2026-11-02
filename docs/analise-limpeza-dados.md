# Análise de limpeza e síntese de dados antigos

Medido em 2026-11-01 num clone local da produção (pg_dump → Postgres 18,
`scripts/explain-calcular.sh`) e no catálogo da produção (somente leitura).
Dimensionamento: [`scripts/dimensionar-limpeza.sql`](../scripts/dimensionar-limpeza.sql).

**Critério de aceite** de qualquer limpeza: a digital de todas as vistas gold
(`gold_*` e as 3.108 versões `gold_*_vN`) fica idêntica antes e depois. Foi
testado no clone apagando de verdade dentro de uma transação desfeita no fim
(`md5` ordenado de cada vista, antes × depois).

## Resultado

| # | Candidato | Ganho | Digital de gold | Veredito |
|---|---|---|---|---|
| 0 | Bloat de UPDATE integral em `fato_negociacao`, `fato_conta`, `dim_instrumento` | **≈ 2,0 GB** de 3,4 GB | não toca dado | Fazer. Depende de janela de lock |
| A | `fato_conta` com `is_latest = false` ou `ordem_exerc <> 'ÚLTIMO'` (470.606 linhas) | ≈ 132 MB (≈ 50 % da tabela) | 3.094 vistas iguais | Seguro para gold. Só dura se a carga parar de gravar |
| B | `fato_negociacao` fora de 010/070/080 (64.622 linhas) | ≈ 25 MB | 3.094 vistas iguais | Seguro para gold. Mesma ressalva de A |
| C | Opções vencidas (795.769 linhas: 714 mil < 90 d, 81 mil 90 d–1 ano) | ≈ 348 MB, crescendo por pregão | **muda `gold_opcoes` em todas as 456 versões** | Não fazer sem o consumidor. Quebra `/v1/opcoes/{ticker}?pregao=` histórico |
| D | Operacionais: `uso_chave_api` minuto (4.070), `console_coleta` > 30 d (4.719), `sessao_admin` expirada (9) | < 5 MB | não lido por gold | Fazer por higiene, não por espaço |
| E | Bronze duplicado entre datasets (13 arquivos: proventos ações/dinheiro, `cvm_dfp`/`cvm_dfp_empresa`) | 3,9 MB | — | Não fazer. Bronze é imutável (ADR-10), ganho irrelevante |
| F | `log_execucao.cfg_snapshot` (43 distintos em 552) | 286 kB | — | Não vale o código |

As 14 vistas que deram nulo (`gold_demonstracoes_v1..v3`, `gold_empresa_v1..v6`,
`gold_indicadores_v7..v8`, `gold_itr_trimestre_v1..v3`) estavam vazias antes e
continuaram vazias depois.

## 0. Bloat: o ganho é aqui, e não exige decisão sobre dado

| Tabela | Produção (total) | Clone recém-restaurado | Sobra |
|---|---|---|---|
| `fato_negociacao` | 1.672 MB | 688 MB | ≈ 984 MB |
| `fato_conta` | 1.363 MB | 376 MB | ≈ 987 MB |
| `dim_instrumento` | 129 MB | 72 MB | ≈ 57 MB |

O restore reescreve as tabelas compactas. A diferença é espaço de tupla morta
que o `VACUUM` comum marca como livre mas não devolve ao disco.

### Diagnóstico na produção (2026-11-02, `ANALYZE` rodado nas três tabelas)

Configuração: autovacuum ligado, tudo no default, nenhuma `reloption`. Nenhuma
transação, slot de replicação ou transação preparada segurando o horizonte do
vacuum. `shared_buffers` = 128 MB. O clone usa 1 GB, então os tempos do
`explain-calcular.sh` saem otimistas.

| Tabela | Heap | Dado estimado | Vazio estimado | Escrita desde o restart (10/09) |
|---|---|---|---|---|
| `fato_negociacao` | 1.314 MB | 555 MB | 58 % | 459 mil INSERT, **13,7 milhões de UPDATE** (2 % HOT), 25 autovacuums |
| `fato_conta` | 1.088 MB | 280 MB | 74 % | nenhuma, 0 autovacuum, 120 mil tuplas mortas |
| `dim_instrumento` | 87 MB | 50 MB | 43 % | 35 mil INSERT, 2,7 milhões de UPDATE, 29 autovacuums |

"Dado estimado" é linhas × largura média de `pg_stats`, sem os índices, que
têm bloat próprio. Para medir exato existe `pgstattuple` na imagem, mas não
está instalado, e instalar é mudança na produção.

O que isso diz:

- **`n_live_tup = 0` em `fato_conta` não era autovacuum quebrado.** O Postgres
  reiniciou em 10/09, e um restart sem desligamento limpo zera as estatísticas
  acumuladas. Desde então `fato_conta` não recebeu escrita, o que segue a
  agenda: o ITR roda dia 15 de fev/mai/ago/nov e a DFP em 1º de abril. Sem
  contador, o autovacuum nunca a visitou. O `ANALYZE` corrigiu a contagem.
  As "120 mil mortas" estimadas pela amostra eram na verdade 3.806, segundo o
  `VACUUM FULL` (item 2 da ordem recomendada).
- **`fato_conta` está parada até 15/11.** Um `VACUUM FULL` antes do ITR deixa
  um ganho de cerca de 800 MB que dura. O lock bloqueia por alguns minutos as
  rotas que leem demonstrações. Fora isso o custo é zero.
- **`fato_negociacao` reescreve cada linha cerca de 30 vezes.** São 13,7
  milhões de UPDATEs para 459 mil inserções. O autovacuum acompanha (0
  mortas), então o espaço liberado é reaproveitado e o arquivo fica estável em
  cerca de 2× o dado. Um `VACUUM FULL` agora encolhe, mas o arquivo volta a
  crescer até esse patamar enquanto a `calcular` regravar linha sem mudar
  valor. Ali o conserto é o código: `UPDATE … WHERE novo IS DISTINCT FROM
  atual`, e só depois a reescrita.

Opções de reescrita, com o custo de cada uma:

- `VACUUM FULL` por tabela: devolve tudo, mas segura `ACCESS EXCLUSIVE` (API e
  cron bloqueados naquela tabela) e precisa de espaço livre igual ao tamanho
  final da tabela, até cerca de 600 MB. Tem de rodar fora da janela do cron.
- `pg_repack`/`pg_squeeze`: não travam, mas não estão na imagem. Ficam fora
  pela regra de custo.

## A e B: seguros para gold, mas o recomputo desfaz

`python -m app.cli recomputar` reconstrói silver a partir do bronze. Um
`DELETE` em silver volta na próxima recomputação, e o `verificar` passa
(gold é igual), o que esconde que a limpeza foi desfeita. Para durar, a
regra tem de estar na carga, como configuração:

- A: `CHAVE_NATURAL_CONTA` inclui `versao` e `ordem_exerc`
  (`app/seed_fontes.py:233`), então toda reapresentação e todo comparativo
  PENÚLTIMO acumulam. O [plano de custos](plano-custos-armazenamento-mydata.md)
  diz o contrário, e está errado. Filtrar `ordem_exerc = 'ÚLTIMO'` na carga
  perde uma informação: o valor do ano anterior como reapresentado no
  comparativo do ano seguinte. Hoje nenhuma vista lê isso, e ele continua no
  bronze.
- B: filtrar `tp_mercado` na carga do COTAHIST contraria o "sem filtro na
  carga" do ADR-18/20. O argumento a favor: o bronze já guarda o arquivo
  oficial intacto, e silver é cópia descartável. O ADR precisa ser reescrito,
  não contornado.

Ganho somado de A + B: cerca de 157 MB. Vale menos que o bloat e mexe em
princípio declarado. Ordem certa: depois do item 0, e com ADR.

## C: opções vencidas são decisão do consumidor

É o único candidato que muda resultado, porque `gold_opcoes` serve cadeia
histórica por `?pregao=`. Também é o que mais cresce: 714 mil linhas
venceram nos últimos 90 dias. Uma síntese que mantém a análise possível seria
guardar só o último pregão de cada série vencida, ou agregados por
vencimento, e remover o resto. Isso é contrato com o BolsIA e vai para
[contrato-consumidor.md](contrato-consumidor.md). Não é decisão deste repo.

## Ordem recomendada

1. ~~`ANALYZE` + diagnóstico do autovacuum na produção~~ feito em 2026-11-02.
2. ~~`VACUUM FULL fato_conta` antes do ITR de 15/11~~ feito em 2026-11-01
   às 22:33 (horário de São Paulo), sem nenhuma carga em andamento. Levou
   13,7 s com `lock_timeout` de 10 s. `fato_conta` foi de 1.363 MB para 375 MB
   (heap de 1.088 para 275 MB, índices de 275 para 100 MB). O banco foi de
   3.445 MB para 2.456 MB. A digital por soma de hash de linha de
   `fato_conta`, `gold_demonstracoes`, `gold_itr_trimestre`,
   `gold_indicadores` e `gold_empresa` ficou idêntica antes e depois, com a
   mesma contagem de linhas. O vacuum achou só 3.806 versões removíveis: as
   "120 mil mortas" eram superestimativa da amostra do `ANALYZE`, e o vazio
   era página livre de cargas antigas.
3. Reduzir os UPDATEs sem mudança de valor na `calcular` (código, com teste).
4. Só depois disso, `VACUUM FULL` de `fato_negociacao` e `dim_instrumento`.
   Cerca de 800 MB, e só dura com o item 3.
5. D como rotina de retenção no próprio cron.
6. A/B só com ADR. C só com resposta do consumidor.

## O que ficou de fora

- Medido no clone, que reflete a produção no momento do dump. Os tamanhos de
  linha de A/B/C são `pg_column_size` (bytes de linha, sem índice). O ganho em
  disco depois do rewrite é um pouco maior por causa dos índices.
- Volume do Railway (`postgres-volume`): 5.816 MB de 50.000 MB usados antes
  do `VACUUM FULL`. Isso dá cerca de 2,4 GB acima do tamanho do banco
  (WAL e arquivos do cluster), e essa diferença não foi investigada.
