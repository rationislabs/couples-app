#!/usr/bin/env bash
# Set this repository up on a machine that has never run it.
#
#   ./setup.sh
#   ./setup.sh --db /tmp/hearth-20260101.db.gz
#   ./setup.sh --home "48.85,2.35" --host mybox.example.ts.net
#   ./setup.sh --no-apt
#
# Options:
#   --db PATH     restore this backup (.gz or plain) into hearth/hearth.db
#   --home LAT,LON  seed the home location of a new database. Without it the first-run page asks.
#   --host NAME   write HEARTH_ALLOWED_HOST into .env: this box's <name>.<tailnet>.ts.net.
#                 Without it the app refuses pages served from the tailnet name.
#   --no-apt      skip the system packages
#
# What this cannot do for you, because neither is in the repository:
#   - hearth.db  — gitignored personal data; starts empty, or restore a backup
#   - .env       — gitignored API keys; the template is copied for you to fill
#   - json/      — gitignored API caches; rebuilt as the scripts run
#   - gallery/   — gitignored photos; uploaded through the app
#
# Idempotent. Every step checks whether it is already done, so re-running after
# fixing one failure does not redo the rest.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP="$ROOT/hearth"
DB="$APP/hearth.db"
VENV="$APP/.venv"
PY="$VENV/bin/python"

DB_ARCHIVE=""
HOME_LATLON=""
ALLOWED_HOST=""
DO_APT=1
while [ $# -gt 0 ]; do
  case "$1" in
    --db) DB_ARCHIVE="$(realpath -- "${2:?--db needs a path}")"; shift 2 ;;
    --home) HOME_LATLON="${2:?--home needs \"lat,lon\"}"; shift 2 ;;
    --host) ALLOWED_HOST="${2:?--host needs a tailnet name}"; shift 2 ;;
    --no-apt) DO_APT=0; shift ;;
    -h|--help) sed -n '2,22p' "$0"; exit 0 ;;
    *) echo "unknown option: $1"; exit 2 ;;
  esac
done

step() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }
ok()   { printf '    ok   %s\n' "$1"; }
warn() { printf '    !!   %s\n' "$1"; }

# --- 1. system packages ------------------------------------------------------
# poppler-utils and tesseract are only needed to re-run the OCR importers; the
# app itself does not touch them. They are installed anyway because finding out
# later means stopping halfway through an import.
if [ "$DO_APT" = 1 ]; then
  step "System packages"
  missing=""
  for p in poppler-utils tesseract-ocr sqlite3 ufw; do
    dpkg -s "$p" >/dev/null 2>&1 || missing="$missing $p"
  done
  if [ -n "$missing" ]; then
    echo "    need:$missing"
    sudo apt install -y $missing
  else
    ok "all present"
  fi
fi

# --- 2. uv -------------------------------------------------------------------
step "uv"
if command -v uv >/dev/null 2>&1; then
  ok "$(uv --version)"
else
  warn "uv not found — install it, then re-run:"
  echo "      curl -LsSf https://astral.sh/uv/install.sh | sh"
  exit 1
fi

# --- 3. virtualenv -----------------------------------------------------------
# The venv is uv-managed and has no pip inside it, so anything that expects
# `.venv/bin/pip` will fail. Use `uv pip` with VIRTUAL_ENV set.
step "Python environment"
if [ -x "$PY" ]; then
  ok "venv exists ($("$PY" -V))"
else
  ( cd "$APP" && uv venv .venv --python 3.12 )   # as CI and the image; uv otherwise takes the newest installed
  ok "created $VENV"
fi
( cd "$APP" && VIRTUAL_ENV="$VENV" uv pip install -q -r requirements.txt )
( cd "$APP" && VIRTUAL_ENV="$VENV" uv pip install -q --no-deps -e . )   # backup_db.sh runs python -m hearth.core.backup
ok "requirements installed"

# --- 4. secrets --------------------------------------------------------------
step "Secrets"
if [ -f "$ROOT/.env" ]; then
  ok ".env already present (not overwritten)"
else
  install -m 600 /dev/null "$ROOT/.env"
  cat "$ROOT/.env.example" >> "$ROOT/.env"
  chmod 600 "$ROOT/.env"
  warn "created .env from the template — fill in the values before first run"
fi
[ "$(stat -c %a "$ROOT/.env")" = "600" ] || chmod 600 "$ROOT/.env"

# --- 5. database -------------------------------------------------------------
# Never `cp hearth.db` from a running app: under WAL a plain copy can catch a
# live transaction and misses the -wal sidecar, producing a file that opens
# cleanly and restores corrupt. backup_db.sh uses the online backup API.
step "Database"
if [ -f "$DB" ]; then
  ok "hearth.db present, left alone"
elif [ -n "$DB_ARCHIVE" ]; then
  # Through core/backup.py, which proves the archive opens and holds data
  # before anything is written: a truncated copy must not become the
  # hearth.db that every later run then leaves alone.
  DB_ARCHIVE="$(realpath -- "$DB_ARCHIVE")"   # the restore runs from hearth/
  gz="$DB_ARCHIVE"
  case "$DB_ARCHIVE" in
    *.gz) ;;
    *) gz="$(mktemp --suffix=.db.gz)"; gzip -c "$DB_ARCHIVE" > "$gz" ;;
  esac
  if ( cd "$APP" && "$PY" -m hearth.core.backup restore "$gz" ); then
    ok "restored from $DB_ARCHIVE"
  else
    rm -f "$DB"
    warn "$DB_ARCHIVE did not verify; nothing restored"
    exit 1
  fi
  [ "$gz" = "$DB_ARCHIVE" ] || rm -f "$gz"
else
  warn "no hearth.db and no --db given. Starting empty."
  warn "To bring the real one across, on the old machine:"
  echo "      ./backup_db.sh && scp backups/hearth-<newest>.db.gz this-box:/tmp/"
  echo "      then: ./setup.sh --db /tmp/hearth-<newest>.db.gz"
fi

# --- 6. schema ---------------------------------------------------------------
step "Migrations"
# An existing install keeps its names and home in .env; the people-as-ids
# migration reads them from the environment, and HEARTH_PEOPLE wins there.
set -a; . <(grep -E '^HEARTH_(PEOPLE|HOME_LATLON)=' "$ROOT/.env" 2>/dev/null || true); set +a
( cd "$APP" && HEARTH_HOME_LATLON="${HOME_LATLON:-${HEARTH_HOME_LATLON:-}}" "$VENV/bin/reflex" db migrate )
# `python - <<EOF` has no __file__, so the path is an argument.
head="$("$PY" -c '
import sqlite3, sys
try:
    print(sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
          .execute("select version_num from alembic_version").fetchone()[0])
except Exception as exc:
    print(f"unreadable ({exc})")
' "$DB" 2>/dev/null || echo unknown)"
ok "schema at $head"

# --- 7. machine-specific -----------------------------------------------------
# HOME is the origin for every distance in the app: the Tonight radius filter
# and the /dates km columns both measure from it. Unset, distances are hidden
# and the first-run page asks for it.
step "Machine-specific settings"

# Appends only if the key is absent, so an .env copied from the old box is
# never rewritten by a flag typed out of habit.
set_env() {
  local key="$1" val="$2"
  if grep -q "^$key=" "$ROOT/.env" 2>/dev/null; then
    ok "$key already set in .env, left alone"
  else
    printf '%s="%s"\n' "$key" "$val" >> "$ROOT/.env"
    ok "$key written to .env"
  fi
}

[ -n "$ALLOWED_HOST" ] && set_env HEARTH_ALLOWED_HOST "$ALLOWED_HOST"

if ! grep -q "^HEARTH_ALLOWED_HOST=" "$ROOT/.env" 2>/dev/null; then
  warn "HEARTH_ALLOWED_HOST is not set — the app will refuse pages served from"
  warn "this box's tailnet name. Re-run with --host <name>.<tailnet>.ts.net."
fi

# --- gitignored extras -------------------------------------------------------
# None of these are in the repository and none are fatal. The app runs without
# every one of them; this says what each costs so the decision is informed.
step "Gitignored files"
report_missing() {
  local path="$1" size="$2" what="$3"
  if [ -e "$ROOT/$path" ]; then
    ok "$path present"
  else
    warn "$path missing${size:+ ($size)} — $what"
  fi
}
report_missing ".env" "" "API keys. Importers fail; the app itself does not use them"
report_missing "hearth/hearth.db" "" "all the data. Without it you get an empty but working app"
report_missing "json" "" "API caches. Created the first time a TMDB or Last.fm script runs"
report_missing "gallery" "≤100 photos" "the Tonight gallery. Upload photos from the app, or restore backups/gallery/"
if [ ! -e "$ROOT/backups" ]; then
  warn "backups/ missing — history only; the next ./backup_db.sh creates it"
fi

# --- 8. check ----------------------------------------------------------------
step "Preflight"
if "$PY" "$ROOT/scripts/ops/preflight.py"; then
  ok "preflight clean"
else
  warn "preflight reported problems — read them above before starting the app"
fi

step "Done"
cat <<'EOF'
    Start it:      ./hearth.sh start
    Bind check:    ./hearth.sh check      (expect: loopback only)
    Auto-restart:  ./hearth.sh watch      (rebuilds on save; holds while
                                           someone is connected)

    Then look at it in a browser. Several bugs on this project were invisible
    to every check except looking.
EOF
