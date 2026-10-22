#!/bin/sh
# serve (default): back up, migrate, then start. A failed backup stops the
# start, so no update ever migrates a database it cannot give back.
#   docker compose run --rm app backup
#   docker compose run --rm app restore /backups/ledger-<stamp>.db.gz   (app stopped)
set -eu
umask 077   # ledger.db, backups and photos are private: owner-only
case "${1:-serve}" in
  serve)   ;;
  backup)  exec python -m ledger_app.core.backup backup ;;
  restore) shift; exec python -m ledger_app.core.backup restore "$@" ;;
  *)       exec "$@" ;;
esac
if [ -z "${LEDGER_ALLOWED_HOST:-}" ]; then
  echo "LEDGER_ALLOWED_HOST is not set: put couples.<your-tailnet>.ts.net in .env and pass it" >&2
  echo "to the app (see compose.yml). Without it every page is refused." >&2
  exit 1
fi
python -m ledger_app.core.backup prestart
alembic upgrade head
exec python -m ledger_app.serve
