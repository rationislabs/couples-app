#!/usr/bin/env bash
# Nightly backup of ledger.db.
#
# Uses the SQLite online backup API, not cp: under WAL a raw file copy can catch
# the database mid-transaction and misses the -wal sidecar, giving you a file
# that looks fine and restores corrupt. The backup API is safe to run while the
# app is serving.
#
#   ./backup_db.sh            # write one backup, prune old ones
#   ./backup_db.sh --verify   # decompress the newest and prove it opens
#
# Env: LEDGER_BACKUP_DIR (default ./backups), LEDGER_BACKUP_KEEP (default 30).
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DB="$DIR/ledger_app/ledger.db"
PY_BIN="$DIR/ledger_app/.venv/bin/python"
DEST="${LEDGER_BACKUP_DIR:-$DIR/backups}"
KEEP="${LEDGER_BACKUP_KEEP:-30}"
STAMP="$(date +%Y%m%d-%H%M%S)"

die() { echo "backup FAILED: $*" >&2; exit 1; }

newest_gz() { ls -1t "$DEST"/ledger-*.db.gz 2>/dev/null | head -1; }

# Python's sqlite3 module rather than the sqlite3 CLI throughout: the binary is
# not installed on this machine, and a backup script that depends on something
# absent is not a backup script.
[ -x "$PY_BIN" ] || die "no interpreter at $PY_BIN"

verify() {
  local gz tmp
  gz="${1:-$(newest_gz)}"
  [ -n "$gz" ] && [ -f "$gz" ] || die "no backups to verify in $DEST"
  tmp="$(mktemp -t ledger-verify-XXXXXX.db)"
  # shellcheck disable=SC2064
  trap "rm -f '$tmp'" RETURN
  gunzip -c "$gz" > "$tmp" || die "could not decompress $gz"
  "$PY_BIN" "$DIR/scripts/ops/verify_backup.py" "$tmp" "$(basename "$gz")" \
    || die "verification of $(basename "$gz") failed"
}

if [ "${1:-}" = "--verify" ]; then verify; exit 0; fi

[ -f "$DB" ] || die "no database at $DB"
mkdir -p "$DEST"
OUT="$DEST/ledger-$STAMP.db"

"$PY_BIN" - "$DB" "$OUT" <<'PYBACKUP' || die "backup API errored"
import sqlite3
import sys

src, dst = sys.argv[1], sys.argv[2]
# read-only on the source so a backup can never be the thing that corrupts it
with sqlite3.connect(f"file:{src}?mode=ro", uri=True) as s, \
     sqlite3.connect(dst) as d:
    s.backup(d)
PYBACKUP

gzip -f "$OUT"
echo "wrote $(basename "$OUT").gz ($(du -h "$OUT.gz" | cut -f1))"

# Prove the thing we just wrote is restorable. A backup job that reports success
# without checking is how you find out at the worst possible moment.
verify "$OUT.gz"

# Prune, keeping the most recent KEEP files.
ls -1t "$DEST"/ledger-*.db.gz 2>/dev/null | tail -n +$((KEEP + 1)) \
  | while read -r old; do rm -f -- "$old" && echo "pruned $(basename "$old")"; done

echo "$(ls -1 "$DEST"/ledger-*.db.gz 2>/dev/null | wc -l) backups in $DEST"

# Photos. gallery/ is gitignored, so this is the only other copy of it. A mirror,
# not a snapshot per night: 30 dated copies of up to 100 phone photos would be
# tens of GB. No --delete, deliberately — a photo removed in the app stays in
# backups/gallery/, so deleting to make room under the cap is recoverable.
# thumbs/ is excluded; the app regenerates it from the originals.
GALLERY="$DIR/gallery"
if [ -d "$GALLERY" ]; then
  rsync -a --exclude 'thumbs/' "$GALLERY/" "$DEST/gallery/" \
    || die "gallery copy failed"
  live=$(find "$GALLERY" -maxdepth 1 -type f | wc -l)
  kept=$(find "$DEST/gallery" -maxdepth 1 -type f | wc -l)
  [ "$kept" -ge "$live" ] || die "gallery copy short: $kept of $live photos"
  echo "gallery: $live photos live, $kept kept in $DEST/gallery"
fi
