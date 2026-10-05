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
# The spec's "/ redirects to /setup" happens client-side, over the websocket,
# so curl cannot see it. The redirect rule is covered by test_setup_flow.py;
# here we only prove the route was compiled into the image.
check "/setup is a compiled route" '[ "$(curl -sL -o /dev/null -w "%{http_code}" "$URL/setup")" = 200 ]'
check "an unknown route is not served as 200" '[ "$(curl -sL -o /dev/null -w "%{http_code}" "$URL/no-such-route-xyz")" != 200 ]'
backup_seen=no
for _ in $(seq 1 30); do
  if $DC exec -T app sh -c 'ls /backups/ledger-2*.db.gz' >/dev/null 2>&1; then
    backup_seen=yes; break
  fi
  sleep 1
done
check "a fresh install backs itself up at start" '[ "$backup_seen" = yes ]'
check "compose.yml publishes no port" '! grep -qE "^[[:space:]]*ports:" compose.yml'
bad=$(mktemp -d); printf 'not a backup' > "$bad/bad.db.gz"; chmod -R a+rX "$bad"
check "restore rejects a bad file" \
  '! docker run --rm -v "$bad:/in:ro" "$IMAGE" restore /in/bad.db.gz >/dev/null 2>&1'
rm -rf "$bad"
envf=$(mktemp); printf 'TS_AUTHKEY=x\nTMDB_API_KEY=y\n' > "$envf"
check "compose.yml does not hand TS_AUTHKEY to the app" \
  'docker compose -f compose.yml --env-file "$envf" config --format json | python3 -c "import json,sys; e=json.load(sys.stdin)[\"services\"][\"app\"][\"environment\"]; sys.exit(not (\"TMDB_API_KEY\" in e and \"TS_AUTHKEY\" not in e))"'
rm -f "$envf"
exit $fail
