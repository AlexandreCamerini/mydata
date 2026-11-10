#!/usr/bin/env bash
# Checagem diária de FinOps do mydata em produção. SOMENTE LEITURA.
# Precisa do `railway` logado e de rede (o ssh não funciona dentro do sandbox).
# Uso: scripts/finops-checagem.sh            (imprime o relatório bruto)
set -uo pipefail
P=f6b2f799-fe75-459b-8fbb-acca54b36bec
E=production
filtra() { grep -v -E "update cache|OAuth token|SSH key|agent tooling|railway setup agent|^$"; }

echo "## data: $(date '+%F %T %z')"
echo "## deploys mydata";      railway deployment list -s mydata      -e $E 2>&1 | filtra | sed -n 2,4p
echo "## deploys mydata-cron"; railway deployment list -s mydata-cron -e $E 2>&1 | filtra | sed -n 2,4p
echo "## health";              curl -s -m 20 https://mydata.acamerini.app/health; echo
echo "## memoria 1d";          railway metrics -p $P -e $E -s Postgres --since 1d --memory 2>&1 | filtra | tail -3
echo "## memoria 7d";          railway metrics -p $P -e $E -s Postgres --since 7d --memory 2>&1 | filtra | tail -3
echo "## fatura";              railway usage projects --project mydata --period current 2>&1 | filtra | sed -n 3,12p
echo "## limite do workspace"; railway usage limit status 2>&1 | filtra | tail -8

REMOTO=$(cat <<'SH'
Q() { psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tA -F" | " -c "$1"; }
echo "# postmaster_start (utc)"; Q "select pg_postmaster_start_time() at time zone 'utc'"
echo "# cgroup memory.max"; cat /sys/fs/cgroup/memory.max
grep -E "^(anon|file|shmem|kernel) " /sys/fs/cgroup/memory.stat
echo "# pg_stat: tabela | ins | upd | hot_upd | live | dead"
Q "select relname, n_tup_ins, n_tup_upd, n_tup_hot_upd, n_live_tup, n_dead_tup from pg_stat_user_tables where relname in ('fato_negociacao','dim_instrumento','fato_conta') order by 1"
echo "# calcular b3_cotahist: janela | terminado (BRT) | segundos"
Q "select e.janela, to_char(e.terminado_em at time zone 'America/Sao_Paulo','MM-DD HH24:MI'), round(f.duracao_ms/1000.0,1) from log_execucao e join log_fase f on f.execucao_id=e.id where e.dataset_chave='b3_cotahist' and f.fase='calcular' and e.status='publicado' order by e.terminado_em desc limit 8"
echo "# ultimas execucoes: dataset | janela | status | terminado (BRT)"
Q "select dataset_chave, janela, status, to_char(terminado_em at time zone 'America/Sao_Paulo','MM-DD HH24:MI') from log_execucao order by terminado_em desc limit 14"
echo "# falhas/bloqueios nas ultimas 48h"
Q "select dataset_chave, janela, status, left(coalesce(erro,''),120) from log_execucao where status in ('falha','bloqueada') and terminado_em > now() - interval '48 hours' order by terminado_em desc"
SH
)
B64=$(printf '%s' "$REMOTO" | base64 | tr -d '\n')
echo "## banco (ssh, somente SELECT)"
railway ssh -p $P -e $E -s Postgres -- sh -c "echo $B64 | base64 -d | sh" 2>&1 | filtra
