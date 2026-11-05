#!/usr/bin/env bash
# correr.sh - atajos para Linux / Mac / Git Bash. Todo corre dentro de Docker.
#
#   scripts/correr.sh levantar      construye y levanta Postgres + scraper
#   scripts/correr.sh excel         genera salidas/excel/reporte_scraper_precios.xlsx
#   scripts/correr.sh estado        conteos de la base
#   scripts/correr.sh respaldar     guarda la base actual en db/datos/datos.sql
#   scripts/correr.sh psql          consola SQL de la base
#   scripts/correr.sh bajar         apaga los contenedores (los datos se quedan)
#   scripts/correr.sh <otro>        cualquier comando de main.py:
#                                   match tyco, crawl mech, enriquecer --forzar, listar...
set -euo pipefail

cd "$(dirname "$0")/.."
USUARIO="${DB_USER:-scraper}"
BASE="${DB_NAME:-scraper_precios}"
comando="${1:-ayuda}"
[ $# -gt 0 ] && shift

case "$comando" in
  ayuda)
    sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//'
    ;;
  levantar)
    docker compose up -d --build
    docker compose exec -T scraper python main.py estado
    ;;
  bajar)
    docker compose down
    ;;
  respaldar)
    docker compose exec -T postgres pg_dump -U "$USUARIO" -d "$BASE" \
      --data-only --column-inserts --no-owner --no-privileges -f /tmp/datos.sql
    docker compose cp postgres:/tmp/datos.sql db/datos/datos.sql
    docker compose exec -T scraper python -m db.limpiar_dump db/datos/datos.sql
    echo "Respaldo listo: db/datos/datos.sql (haz commit para guardarlo en el repo)"
    ;;
  psql)
    docker compose exec postgres psql -U "$USUARIO" -d "$BASE"
    ;;
  *)
    docker compose exec -T scraper python main.py "$comando" "$@"
    ;;
esac
