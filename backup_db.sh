#!/usr/bin/env bash
# Nightly backup of ledger.db and the photos, for a host install's timer.
# The logic is ledger_app/core/backup.py, shared with the container.
#
#   ./backup_db.sh            # write one backup, prune old ones, mirror gallery/
#   ./backup_db.sh --verify   # prove the newest backup restores
#
# Env: LEDGER_BACKUP_DIR (default ./backups), LEDGER_BACKUP_KEEP (default 30).
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$DIR/ledger_app/.venv/bin/python"
if [ "${1:-}" = "--verify" ]; then exec "$PY" -m ledger_app.core.backup verify; fi
exec "$PY" -m ledger_app.core.backup backup
