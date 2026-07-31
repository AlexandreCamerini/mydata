#!/bin/sh
# Ponto de entrada único para todos os serviços do MyData no Railway.
#
# Web e cron rodam a mesma imagem e diferem por uma variável, não por dois
# Dockerfiles nem dois comandos escritos no painel. O papel é configuração,
# como o resto do sistema.
#
#   PORTAL_PAPEL=web   (padrão)  sobe a API e o front
#   PORTAL_PAPEL=cron            roda os agendamentos vencidos e termina
#
# `migrar --seed` roda antes dos dois: é idempotente por digest, então
# reaplicar configuração idêntica não cria versão nova, e o serviço nunca
# atende requisição contra schema desatualizado.
set -e

python -m app.cli migrar --seed

case "${PORTAL_PAPEL:-web}" in
  cron)
    # Processo curto: sobe, trabalha, morre. É o Railway que o acorda na
    # hora marcada — não há laço de espera consumindo memória entre execuções.
    exec python -m app.cli agendados
    ;;
  web)
    exec uvicorn app.api.main:app --host 0.0.0.0 --port "${PORT:-8000}"
    ;;
  *)
    echo "PORTAL_PAPEL desconhecido: '${PORTAL_PAPEL}'. Use 'web' ou 'cron'." >&2
    exit 64
    ;;
esac
