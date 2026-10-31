#!/usr/bin/env bash
# Files the app creates (hearth.db, backups, photos, the token file) are the
# household's private data: owner-only, not the default 0644, on a shared host
# and in the container alike.
#
#     bash tests/test_umask.sh
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fail=0
check() { if eval "$2"; then echo "  ok  $1"; else echo "  FAIL $1"; fail=1; fi; }

check "the container entrypoint sets umask 077" \
  "[ \"\$(sh '$ROOT/docker/entrypoint.sh' sh -c umask)\" = 0077 ]"
check "backup_db.sh sets umask 077 (the host's nightly timer)" \
  "grep -q '^umask 077' '$ROOT/backup_db.sh'"
check "hearth.sh sets umask 077 before starting anything" \
  "sed -n '1,/^PORT=/p' '$ROOT/hearth.sh' | grep -q '^umask 077'"

[ $fail -eq 0 ] && echo "umask checks passed" || echo "umask checks FAILED"
exit $fail
