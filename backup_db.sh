#!/usr/bin/env bash
# Nightly backup of hearth.db and the photos, for a host install's timer.
# The logic is hearth/core/backup.py, shared with the container.
#
#   ./backup_db.sh            # write one backup, prune old ones, mirror gallery/
#   ./backup_db.sh --verify   # prove the newest backup restores
#
# Env: HEARTH_BACKUP_DIR (default ./backups), HEARTH_BACKUP_KEEP (default 30).
set -euo pipefail
umask 077   # backups hold the whole ledger: owner-only
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$DIR/hearth/.venv/bin/python"
cd "$DIR/hearth"   # the package resolves from here
if [ "${1:-}" = "--verify" ]; then exec "$PY" -m hearth.core.backup verify; fi
exec "$PY" -m hearth.core.backup backup
