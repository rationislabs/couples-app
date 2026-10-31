#!/bin/sh
# serve (default): back up, migrate, then start. A failed backup stops the
# start, so no update ever migrates a database it cannot give back.
#   docker compose run --rm app backup
#   docker compose run --rm app restore /backups/hearth-<stamp>.db.gz   (app stopped)
set -eu
umask 077   # hearth.db, backups and photos are private: owner-only
case "${1:-serve}" in
  serve)   ;;
  backup)  exec python -m hearth.core.backup backup ;;
  restore) shift; exec python -m hearth.core.backup restore "$@" ;;
  *)       exec "$@" ;;
esac
if [ -z "${HEARTH_ALLOWED_HOST:-}" ]; then
  echo "HEARTH_ALLOWED_HOST is not set: put hearth.<your-tailnet>.ts.net in .env and pass it" >&2
  echo "to the app (see compose.yml). Without it every page is refused." >&2
  exit 1
fi
python -m hearth.core.backup prestart
alembic upgrade head
exec python -m hearth.serve
