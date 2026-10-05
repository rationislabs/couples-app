#!/bin/sh
# serve (default): back up, migrate, then start. A failed backup stops the
# start, so no update ever migrates a database it cannot give back.
#   docker compose run --rm app backup
#   docker compose run --rm app restore /backups/ledger-<stamp>.db.gz   (app stopped)
set -eu
case "${1:-serve}" in
  serve)   ;;
  backup)  exec python -m ledger_app.core.backup backup ;;
  restore) shift; exec python -m ledger_app.core.backup restore "$@" ;;
  *)       exec "$@" ;;
esac
python -m ledger_app.core.backup prestart
alembic upgrade head
exec python -m ledger_app.serve
