#!/usr/bin/env bash
# Builds the image and checks the container the way a stranger would run it.
# Needs Docker. Not part of tests/run.sh; CI runs it as its own step.
# Publishes on 127.0.0.1:3300, never 3000 — a real ledger may be running there.
#
#     tests/test_image.sh
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export IMAGE="${IMAGE:-couples-app:test}"
URL="http://127.0.0.1:3300"
fail=0
check() { if eval "$2"; then echo "  ok  $1"; else echo "  FAIL $1"; fail=1; fi; }

cd "$ROOT"
if [ -z "${SKIP_BUILD:-}" ]; then   # release.yml tests the image it then pushes
  docker build -q -t "$IMAGE" . >/dev/null || { echo "  FAIL image builds"; exit 1; }
  echo "  ok  image builds"
fi

# -p: a project name of its own, so `down -v` can never delete the volumes of a
# real `docker compose up` run from a folder that is also called couples-app.
DC="docker compose -p couples-app-test -f compose.test.yml"
trap '$DC down -v >/dev/null 2>&1' EXIT
$DC up -d >/dev/null
start=$(date +%s); code=""
while [ $(( $(date +%s) - start )) -lt 30 ]; do
  code=$(curl -s -o /dev/null -w '%{http_code}' "$URL/" || true)
  [ "$code" = 200 ] && break
  sleep 1
done
check "serves / within 30 s (the frontend was not rebuilt at start)" '[ "$code" = 200 ]'
check "backend answers /ping" '[ "$(curl -s -o /dev/null -w "%{http_code}" "$URL/ping")" = 200 ]'
check "bun is not in the runtime image" \
  '! docker run --rm --entrypoint sh "$IMAGE" -c "find / -xdev -name bun -type f 2>/dev/null | grep -q ."'
check "runs as a non-root user" '[ "$(docker run --rm --entrypoint id "$IMAGE" -u)" != 0 ]'
check "the frontend dials port 3000, not Reflex's default 8000" \
  '! docker run --rm --entrypoint sh "$IMAGE" -c "grep -rqs localhost:8000 .web"'
check "scripts find the venv the pages call" \
  'docker run --rm --entrypoint test "$IMAGE" -x /app/ledger_app/.venv/bin/python'
exit $fail
