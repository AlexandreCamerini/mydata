-- dimensionar-limpeza.sql — quanto ocupa cada candidato a limpeza ou síntese.
--
-- SOMENTE LEITURA: tudo roda numa transação READ ONLY desfeita no fim. Nada
-- é apagado, nada é reescrito. Postgres apenas (usa pg_* e pg_column_size).
--
-- Onde rodar: de preferência no clone de scripts/explain-calcular.sh — as
-- seções 2 e 3 varrem fato_conta e fato_negociacao inteiras (~2 GB de I/O),
-- e em produção isso compete com o cron. Em produção, fora da janela do cron:
--   railway run -- bash -c 'psql "$DATABASE_PUBLIC_URL" -f scripts/dimensionar-limpeza.sql'
--
-- Critério de "não afeta as análises": toda limpeza de silver tem de deixar a
-- digital de gold igual (`python -m app.cli verificar` antes e depois).

\set ON_ERROR_STOP on
\pset footer off
BEGIN READ ONLY;
SET LOCAL statement_timeout = '10min';

\echo '== 1. Tabelas: tamanho, linhas vivas e mortas (bloat de UPDATE integral)'
SELECT relname                                         AS tabela,
       pg_size_pretty(pg_total_relation_size(relid))   AS total,
       n_live_tup                                      AS vivas,
       n_dead_tup                                      AS mortas,
       round(100.0 * n_dead_tup / nullif(n_live_tup + n_dead_tup, 0), 1) AS pct_mortas,
       last_autovacuum::date                           AS ult_autovacuum
FROM pg_stat_user_tables
ORDER BY pg_total_relation_size(relid) DESC
LIMIT 25;

\echo '== 2. fato_conta: o que gold_demonstracoes nunca lê (is_latest=false ou ordem_exerc<>ÚLTIMO)'
SELECT is_latest,
       ordem_exerc,
       count(*)                                        AS linhas,
       pg_size_pretty(sum(pg_column_size(f.*)))        AS bytes_linha
FROM fato_conta f
GROUP BY 1, 2
ORDER BY 1 DESC, 2;

\echo '== 2b. fato_conta: peso das colunas texto-original (_txt) e repetidas por linha'
SELECT pg_size_pretty(sum(pg_column_size(vl_conta_txt)))  AS vl_conta_txt,
       pg_size_pretty(sum(pg_column_size(denom_cia)))     AS denom_cia,
       pg_size_pretty(sum(pg_column_size(ds_conta)))      AS ds_conta,
       pg_size_pretty(sum(pg_column_size(fonte_arquivo))) AS fonte_arquivo
FROM fato_conta;

\echo '== 3. fato_negociacao por recorte: gold lê só 010 (à vista) e 070/080 (opções)'
SELECT CASE WHEN tp_mercado = '010' THEN '010 a vista (gold_cotacoes)'
            WHEN tp_mercado IN ('070', '080') THEN '070/080 opcoes (gold_opcoes)'
            ELSE tp_mercado || ' fora de gold' END       AS recorte,
       count(*)                                        AS linhas,
       pg_size_pretty(sum(pg_column_size(n.*)))        AS bytes_linha
FROM fato_negociacao n
GROUP BY 1
ORDER BY 2 DESC;

\echo '== 3b. Opções vencidas, por idade do vencimento (servidas por /v1/opcoes?pregao=)'
-- Atributo `data` é texto ISO (motor.ddl); nulo e vazio caem em "sem data".
SELECT CASE WHEN nullif(dt_vencimento, '') IS NULL THEN '9 sem data'
            WHEN dt_vencimento::date >= current_date THEN '0 viva'
            WHEN dt_vencimento::date >= current_date - 90 THEN '1 vencida < 90 d'
            WHEN dt_vencimento::date >= current_date - 365 THEN '2 vencida 90 d-1 ano'
            ELSE '3 vencida > 1 ano' END                 AS idade,
       count(*)                                        AS linhas,
       pg_size_pretty(sum(pg_column_size(n.*)))        AS bytes_linha
FROM fato_negociacao n
WHERE tp_mercado IN ('070', '080')
GROUP BY 1
ORDER BY 1;

\echo '== 4. Bronze por dataset: publicado (tamanho_bytes) x guardado (TOAST)'
SELECT dataset_chave,
       count(*)                                        AS capturas,
       pg_size_pretty(sum(tamanho_bytes))              AS publicado,
       pg_size_pretty(sum(pg_column_size(payload)))    AS guardado,
       min(janela)                                     AS primeira,
       max(janela)                                     AS ultima
FROM bronze_captura
GROUP BY 1
ORDER BY sum(pg_column_size(payload)) DESC;

\echo '== 4b. Bronze: mesmo arquivo guardado por mais de um dataset (questão aberta 4)'
SELECT sha256,
       string_agg(dataset_chave, ', ' ORDER BY dataset_chave) AS datasets,
       count(*)                                        AS copias,
       pg_size_pretty(sum(pg_column_size(payload)) - min(pg_column_size(payload))) AS sobra
FROM bronze_captura
GROUP BY sha256
HAVING count(*) > 1
ORDER BY sum(pg_column_size(payload)) DESC
LIMIT 10;

\echo '== 5. Tabelas operacionais que só crescem'
SELECT 'uso_chave_api minuto (so o minuto corrente conta)' AS item,
       count(*) FILTER (WHERE janela = 'minuto')       AS total,
       count(*) FILTER (WHERE janela = 'minuto'
                          AND balde < to_char(now() AT TIME ZONE 'UTC', 'YYYYMMDD')) AS sintetizavel
FROM uso_chave_api
UNION ALL
SELECT 'uso_chave_api dia (historico de uso por consumidor)',
       count(*) FILTER (WHERE janela = 'dia'), 0
FROM uso_chave_api
UNION ALL
SELECT 'uso_ip_emissao_chave (> 2 dias)',
       count(*), count(*) FILTER (WHERE balde < to_char(now() - interval '2 days', 'YYYYMMDD'))
FROM uso_ip_emissao_chave
UNION ALL
SELECT 'console_coleta (> 30 dias)',
       count(*), count(*) FILTER (WHERE quando < now() - interval '30 days')
FROM console_coleta
UNION ALL
SELECT 'sessao_admin expirada',
       count(*), count(*) FILTER (WHERE expira_em < now())
FROM sessao_admin
UNION ALL
SELECT 'fluxo_semente_id (> 1 dia)',
       count(*), count(*) FILTER (WHERE criado_em < now() - interval '1 day')
FROM fluxo_semente_id
UNION ALL
SELECT 'desafio_webauthn (> 1 dia)',
       count(*), count(*) FILTER (WHERE criado_em < now() - interval '1 day')
FROM desafio_webauthn
UNION ALL
SELECT 'log_execucao (> 12 meses)',
       count(*), count(*) FILTER (WHERE iniciado_em < now() - interval '12 months')
FROM log_execucao
UNION ALL
SELECT 'log_fase (> 12 meses)',
       count(*), count(*) FILTER (WHERE iniciado_em < now() - interval '12 months')
FROM log_fase
UNION ALL
SELECT 'relatorio_carga (> 12 meses)',
       count(*), count(*) FILTER (WHERE gerado_em < now() - interval '12 months')
FROM relatorio_carga;

\echo '== 5b. log_execucao.cfg_snapshot: quanto pesa e quantos são distintos'
SELECT count(*)                                         AS execucoes,
       count(DISTINCT md5(cfg_snapshot::text))          AS snapshots_distintos,
       pg_size_pretty(sum(pg_column_size(cfg_snapshot))) AS bytes_snapshot
FROM log_execucao;

\echo '== 5c. Execuções não terminais (estado preso, não dado)'
SELECT dataset_chave, status, count(*) AS n, min(iniciado_em) AS mais_antiga
FROM log_execucao
WHERE status NOT IN ('publicado', 'bloqueada', 'falha')
GROUP BY 1, 2
ORDER BY 4;

ROLLBACK;
