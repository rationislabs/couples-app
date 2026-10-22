#!/usr/bin/env bash
# The container refuses to start without its tailnet name: without it every page is refused
# with a bare "Invalid host header", which nothing in the logs would explain.
#
#     bash tests/test_entrypoint.sh
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fail=0
check() { if eval "$2"; then echo "  ok  $1"; else echo "  FAIL $1"; fail=1; fi; }

out=$(env -u LEDGER_ALLOWED_HOST sh "$ROOT/docker/entrypoint.sh" serve 2>&1); code=$?
check "serve without LEDGER_ALLOWED_HOST stops" "[ $code -ne 0 ]"
check "and says which setting is missing" "printf '%s' \"\$out\" | grep -q LEDGER_ALLOWED_HOST"
check "other commands do not need it" "[ \"\$(env -u LEDGER_ALLOWED_HOST sh '$ROOT/docker/entrypoint.sh' echo hi)\" = hi ]"

[ $fail -eq 0 ] && echo "entrypoint checks passed" || echo "entrypoint checks FAILED"
exit $fail
