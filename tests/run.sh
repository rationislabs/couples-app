#!/usr/bin/env bash
# Every test, against a fresh migrated database in a temp directory, so a test
# run can never touch a real hearth.db. Exits non-zero if any test fails.
# test_image.sh needs Docker and runs on its own.
#
#     tests/run.sh
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${PY:-$ROOT/hearth/.venv/bin/python}"
export HEARTH_DATA_DIR; HEARTH_DATA_DIR="$(mktemp -d)"
export HEARTH_BACKUP_DIR; HEARTH_BACKUP_DIR="$(mktemp -d)"
trap 'rm -rf "$HEARTH_DATA_DIR" "$HEARTH_BACKUP_DIR"' EXIT
( cd "$ROOT/hearth" && "$PY" -m alembic upgrade head >/dev/null ) \
  || { echo "FAIL migrating a fresh database"; exit 1; }
fail=0
for t in "$ROOT"/tests/test_*.py; do
  echo "== $(basename "$t")"; "$PY" "$t" || fail=1
done
for t in "$ROOT"/tests/test_*.sh; do
  [ "$(basename "$t")" = test_image.sh ] && continue
  echo "== $(basename "$t")"; bash "$t" || fail=1
done
exit $fail
