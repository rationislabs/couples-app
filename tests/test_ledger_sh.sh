#!/usr/bin/env bash
# Checks for ./ledger.sh and a port held by another program
#
# start, dev and stop used to kill whatever held $PORT, and took any page that
# answered 200 for this app. Another program on the port must survive every
# command, and start must refuse instead of reporting "already running".
#
#     tests/test_ledger_sh.sh
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
port=$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])')
www=$(mktemp -d); echo ok > "$www/index.html"
# A background job of a script ignores SIGINT; a real program does not, so restore it.
python3 -c 'import runpy, signal, sys
signal.signal(signal.SIGINT, signal.default_int_handler)
sys.argv = ["http.server", sys.argv[1], "--bind", "127.0.0.1", "--directory", sys.argv[2]]
runpy.run_module("http.server", run_name="__main__")' "$port" "$www" >/dev/null 2>&1 &
other=$!
trap 'kill "$other" 2>/dev/null; rm -rf "$www"' EXIT
for _ in $(seq 1 50); do curl -s -o /dev/null "http://127.0.0.1:$port/" && break; sleep 0.1; done

out=$(PORT=$port "$ROOT/ledger.sh" stop 2>&1); sleep 1
kill -0 "$other" 2>/dev/null || { echo "FAIL: stop killed another program: $out"; exit 1; }
echo "  ok  stop leaves another program on the port alone"

out=$(PORT=$port "$ROOT/ledger.sh" start 2>&1); code=$?
kill -0 "$other" 2>/dev/null || { echo "FAIL: start killed another program: $out"; exit 1; }
[ "$code" -ne 0 ] || { echo "FAIL: start took another program for the app: $out"; exit 1; }
echo "$out" | grep -q "another program" || { echo "FAIL: start did not say why: $out"; exit 1; }
echo "  ok  start refuses a port another program holds"

# rxconfig.py pins 3000; without the flag PORT never reaches Reflex.
[ "$(grep -c -- '--frontend-port "\$PORT"' "$ROOT/ledger.sh")" -eq 2 ] \
  || { echo "FAIL: start and dev must pass --frontend-port \"\$PORT\""; exit 1; }
echo "  ok  start and dev run Reflex on \$PORT"

# The app's own process, through a stand-in reflex in a throwaway checkout:
# start must return even when its output is captured, and stop must stop it.
kill "$other" 2>/dev/null; sleep 0.5
fake=$(mktemp -d); mkdir -p "$fake/ledger_app/.venv/bin"
cp "$ROOT/ledger.sh" "$fake/"
cat > "$fake/ledger_app/.venv/bin/reflex" <<'EOF'
#!/usr/bin/env bash
while [ $# -gt 0 ]; do [ "$1" = --frontend-port ] && port=$2; shift; done
exec python3 -m http.server "$port" --bind 127.0.0.1
EOF
chmod +x "$fake/ledger_app/.venv/bin/reflex"
trap 'kill "$other" 2>/dev/null; PORT=$port "$fake/ledger.sh" stop >/dev/null 2>&1; rm -rf "$www" "$fake"' EXIT
out=$(PORT=$port timeout 30 "$fake/ledger.sh" start 2>&1); code=$?
[ "$code" -eq 0 ] && echo "$out" | grep -q started \
  || { echo "FAIL: start did not return cleanly ($code): $out"; exit 1; }
echo "  ok  start returns with its output captured"
PORT=$port "$fake/ledger.sh" status | grep -q running || { echo "FAIL: status missed the app"; exit 1; }
PORT=$port "$fake/ledger.sh" stop >/dev/null; sleep 1
curl -s -o /dev/null --max-time 2 "http://127.0.0.1:$port/" && { echo "FAIL: stop left the app running"; exit 1; }
echo "  ok  status and stop find the app's own process"
echo "ledger.sh checks passed"
