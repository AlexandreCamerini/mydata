#!/usr/bin/env bash
#
# explain-calcular.sh — mede, num CLONE local do banco de produção, por que a
# fase `calcular` do b3_cotahist leva horas (§9.22 do plano do ecossistema).
#
#   1. sobe um Postgres 16 descartável em Docker (porta 55432, volume próprio);
#   2. copia a produção com pg_dump (SÓ LEITURA na produção), usando o
#      DATABASE_PUBLIC_URL do serviço Postgres injetado pelo `railway run` —
#      o valor nunca aparece na tela nem em argumento;
#   3. restaura no clone e roda ANALYZE;
#   4. executa a fase `calcular` do motor contra o clone, para a última captura
#      do b3_cotahist, com cada UPDATE trocado por EXPLAIN (ANALYZE, BUFFERS)
#      dentro de uma transação que é DESFEITA no fim;
#   5. grava planos e tempos em $SAIDA (padrão: ${TMPDIR}/mydata-explain/).
#
# Produção: só `pg_dump`. Nada é escrito lá. O dump fica fora do repo
# (${TMPDIR}/mydata-explain) e é apagado, com o clone, por --limpar.
#
# Uso:
#   bash scripts/explain-calcular.sh              # tudo
#   bash scripts/explain-calcular.sh --sem-dump   # reusa o clone já restaurado
#   bash scripts/explain-calcular.sh --limpar     # derruba o container e o volume
#   CAMPOS=log_retorno bash scripts/explain-calcular.sh --sem-dump   # só um campo
set -euo pipefail

PROJETO_ID="f6b2f799-fe75-459b-8fbb-acca54b36bec"
AMB="${RAILWAY_AMBIENTE:-production}"
CONT="mydata-clone-explain"
VOL="mydata-clone-explain-vol"
PORTA=55432
CLONE_DSN="postgresql://postgres:clone@localhost:$PORTA/mydata"
BASE="${TMPDIR:-/tmp}/mydata-explain"
SAIDA="${SAIDA:-$BASE/explain-$(date +%Y%m%d-%H%M)}"
DUMP="${DUMP:-$BASE/mydata-prod.dump}"

SEM_DUMP=0
for a in "$@"; do
  case "$a" in
    --sem-dump) SEM_DUMP=1 ;;
    --limpar) docker rm -f "$CONT" >/dev/null 2>&1 || true; docker volume rm "$VOL" >/dev/null 2>&1 || true
              rm -f "$DUMP"; echo "clone e dump removidos"; exit 0 ;;
    -h|--help) sed -n '2,24p' "$0"; exit 0 ;;
    *) echo "argumento desconhecido: $a" >&2; exit 2 ;;
  esac
done

say(){ printf '\n\033[1m== %s ==\033[0m\n' "$*"; }
ok(){ printf '  \033[32m[OK]\033[0m %s\n' "$*"; }
die(){ printf '  \033[31m[X]\033[0m %s\n' "$*" >&2; exit 1; }

cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.."
[[ -f app/motor/calculados.py ]] || die "rode a partir de ~/dev/mydata"
for c in docker railway pg_dump pg_restore; do command -v $c >/dev/null || die "$c não encontrado"; done
[[ -x .venv/bin/python ]] || die ".venv do mydata não encontrado"
mkdir -p "$SAIDA" "$(dirname "$DUMP")"

say "1/5 · Postgres descartável em Docker"
if ! docker ps --format '{{.Names}}' | grep -qx "$CONT"; then
  docker run -d --name "$CONT" -p "$PORTA:5432" -v "$VOL:/var/lib/postgresql/data" \
    -e POSTGRES_PASSWORD=clone -e POSTGRES_DB=mydata postgres:16 \
    -c shared_buffers=1GB -c work_mem=64MB -c maintenance_work_mem=512MB >/dev/null \
    || die "docker run falhou"
fi
for i in $(seq 1 30); do docker exec "$CONT" pg_isready -U postgres >/dev/null 2>&1 && break; sleep 2; done
ok "clone em localhost:$PORTA"
echo "  (config do clone: shared_buffers=1GB; a produção pode ter outra — compare com SHOW ALL lá se o tempo divergir)"

if [[ $SEM_DUMP -eq 0 ]]; then
  say "2/5 · pg_dump da produção (só leitura; pode levar alguns minutos)"
  railway run --project "$PROJETO_ID" --environment "$AMB" --service Postgres -- bash -c \
    '[[ -n "${DATABASE_PUBLIC_URL:-}" ]] || { echo "Postgres sem DATABASE_PUBLIC_URL" >&2; exit 1; }
     exec pg_dump --format=custom --no-owner --no-privileges --dbname="$DATABASE_PUBLIC_URL" --file="$0"' "$DUMP" \
    || die "pg_dump falhou"
  ok "dump em $DUMP ($(du -h "$DUMP" | cut -f1))"

  say "3/5 · Restaurar no clone"
  pg_restore --no-owner --no-privileges --clean --if-exists --jobs=4 --dbname="$CLONE_DSN" "$DUMP" 2>"$SAIDA/restore.log" \
    || echo "  pg_restore terminou com avisos (ver $SAIDA/restore.log)"
  psql "$CLONE_DSN" -qc "ANALYZE" || die "ANALYZE falhou"
  ok "restaurado e analisado"
else
  say "2-3/5 · Reusando o clone existente"
fi

say "4/5 · Tamanhos e índices de fato_negociacao"
psql "$CLONE_DSN" -X -A -F ' | ' -c "
  SELECT pg_size_pretty(pg_total_relation_size('fato_negociacao')) AS total,
         pg_size_pretty(pg_relation_size('fato_negociacao')) AS tabela,
         (SELECT count(*) FROM fato_negociacao) AS linhas;" | tee "$SAIDA/tamanho.txt"
psql "$CLONE_DSN" -X -A -c "SELECT indexdef FROM pg_indexes WHERE tablename='fato_negociacao';" | tee "$SAIDA/indices.txt"

say "5/5 · EXPLAIN (ANALYZE, BUFFERS) de cada UPDATE da fase calcular, com ROLLBACK"
DATABASE_URL="$CLONE_DSN" SAIDA="$SAIDA" CAMPOS="${CAMPOS:-}" .venv/bin/python - <<'PY'
import os, time
from pathlib import Path

from app import repositorio as repo
from app.motor import calculados as calc
from app.sinks import criar_sink

saida = Path(os.environ["SAIDA"])
so = {c for c in os.environ.get("CAMPOS", "").split(",") if c}
sink = criar_sink()
assert sink.dialeto == "postgres", "o clone tem de ser Postgres"

ds = repo.dataset_vigente(sink, "b3_cotahist")
assert ds, "dataset b3_cotahist não encontrado no clone"
ultima = sink.um(f"SELECT max(captura_id) AS c FROM {ds['tabela_destino']}")["c"]
campos = repo.calculados_do(sink, ds["id"])
if so:
    campos = [c for c in campos if c["nome"] in so]
print(f"dataset {ds['chave']} → {ds['tabela_destino']}; captura {ultima}; "
      f"{len(campos)} campo(s): {', '.join(c['nome'] for c in campos)}")

relatorio = []
original = sink.executar

def explicar(sql, params=()):
    texto = sql.lstrip()
    if not texto.upper().startswith("UPDATE"):
        return original(sql, params)
    inicio = time.monotonic()
    linhas = sink.consultar("EXPLAIN (ANALYZE, BUFFERS, VERBOSE, FORMAT TEXT) " + sql, params)
    dur = time.monotonic() - inicio
    plano = "\n".join(next(iter(l.values())) for l in linhas)
    n = len(relatorio) + 1
    (saida / f"plano-{n:02d}.txt").write_text(f"-- {dur:.1f}s\n{sql}\n\n{plano}\n", encoding="utf-8")
    relatorio.append((n, dur, sql.split("SET", 1)[1].split("=", 1)[0].strip() if "SET" in sql else "?"))
    print(f"  UPDATE #{n} ({relatorio[-1][2]}): {dur:.1f}s — plano em plano-{n:02d}.txt")

class _Desfazer(Exception):
    """EXPLAIN ANALYZE executa o UPDATE de verdade; sair da transação por
    exceção faz o psycopg desfazer tudo no clone."""

sink.executar = explicar
try:
    with sink.transacao():
        calc.aplicar(sink, ds, campos, capturas=[ultima])
        raise _Desfazer
except _Desfazer:
    print("  transação desfeita no clone")

(saida / "resumo.txt").write_text(
    "\n".join(f"#{n}\t{d:.1f}s\t{c}" for n, d, c in relatorio) + "\n", encoding="utf-8")
print("resumo:", saida / "resumo.txt")
PY
ok "planos em $SAIDA — mande o resumo.txt e os planos dos campos lentos"
echo "  Para liberar o disco: bash scripts/explain-calcular.sh --limpar"
