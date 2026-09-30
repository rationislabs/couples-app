#!/usr/bin/env bash
# Run the Reflex media ledger.
# Usage: ./ledger.sh {start|dev|stop|restart|restart-dev|watch|status|check|open|logs}
#   start = prod build, dev = hot reload. Both bind loopback only.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIR="$ROOT/ledger_app"

# Machine-specific settings live in .env, but the app reads them from the
# environment (rxconfig.py vite_allowed_hosts, state.py HOME_AT). Nothing else
# bridges the two, so setup.sh writing them to .env had no effect without this
# and the app fell back to a default Vite answers 403 to.
# Only LEDGER_* is exported: the API keys stay out of the app's
# environment, which never reads them.
if [ -f "$ROOT/.env" ]; then
  set -a; . <(grep -E '^LEDGER_[A-Z_]+=' "$ROOT/.env"); set +a
fi
PORT="${PORT:-3000}"
URL="http://localhost:$PORT/"
LOG="$DIR/reflex.log"

port_pid(){ ss -ltnp 2>/dev/null | grep -F ":$PORT " | grep -o "pid=[0-9]*" | head -1 | cut -d= -f2 || true; }
serving(){ curl -s -o /dev/null --max-time 3 -w "%{http_code}" "$URL" 2>/dev/null | grep -q 200; }

# The address to open from a phone. The app binds 127.0.0.1 on purpose, so the
# tailnet name only reaches it once `tailscale serve` proxies the port — see
# README.md, "No login, by design". Silent until that exists, rather than printing a URL
# that answers nothing. Only prod prints it: dev bakes ws://localhost/_event
# into the frontend, which on a phone means the phone.
tailnet_url(){
  tailscale serve status 2>/dev/null | grep -q "127.0.0.1:$PORT" || return 1
  local n
  n="$(tailscale status --json 2>/dev/null | grep -m1 '"DNSName"' | cut -d'"' -f4)"
  [ -n "$n" ] && echo "https://${n%.}/"
}

case "${1:-status}" in
  start)
    if serving; then echo "already running"; echo "$URL"; t="$(tailnet_url)" && echo "$t"; exit 0; fi
    p="$(port_pid)"
    if [ -n "$p" ]; then echo "port $PORT held by pid $p but not serving — stopping it"; kill -INT "$p" 2>/dev/null || true; sleep 2; fi
    ( cd "$DIR" && : > "$LOG" && nohup ./.venv/bin/reflex run --env prod --single-port --backend-host 127.0.0.1 >"$LOG" 2>&1 & )
    echo "building (prod builds the frontend)…"
    for _ in $(seq 1 15); do
      sleep 4
      if serving; then echo "started"; echo "$URL"; t="$(tailnet_url)" && echo "$t"; exit 0; fi
    done
    echo "failed to start — last lines of $LOG:"; tail -8 "$LOG"; exit 1 ;;
  stop)
    p="$(port_pid)"
    if [ -n "$p" ]; then kill -INT "$p" 2>/dev/null || true; echo "stopped"; else echo "not running"; fi ;;
  dev)
    # Reflex generates .web/package.json with "dev": "react-router dev --host",
    # and --host makes Vite bind 0.0.0.0 — the whole LAN. There is no config
    # option for it (rx.Config has backend_host only), and the file is rewritten
    # on compile, so the flag is stripped here on every start.
    if serving; then echo "already running"; echo "$URL"; exit 0; fi
    p="$(port_pid)"
    if [ -n "$p" ]; then echo "port $PORT held by pid $p — stopping it"; kill -INT "$p" 2>/dev/null || true; sleep 2; fi
    PKG="$DIR/.web/package.json"
    [ -f "$PKG" ] && sed -i 's|"dev": "react-router dev --host"|"dev": "react-router dev"|' "$PKG" && echo "stripped --host from the dev script"
    # Pin the dev backend port here rather than in rxconfig.py: prod refuses to
    # start when both ports are set and differ, and dev needs them to differ.
    ( cd "$DIR" && : > "$LOG" && nohup ./.venv/bin/reflex run --backend-host 127.0.0.1 --backend-port 8100 >"$LOG" 2>&1 & )
    echo "starting dev (hot reload)…"
    for _ in $(seq 1 20); do
      sleep 3
      if serving; then
        # Deliberately NOT rewriting package.json here. Reflex re-reads that
        # file on every line of frontend output, so editing it while the app is
        # up truncates it under that reader and kills the process with
        # JSONDecodeError. The pre-start strip above is the only safe moment.
        echo "started"; echo "$URL"
        ss -ltnp 2>/dev/null | grep -F ":$PORT " | grep -q '0.0.0.0\|\*:' \
          && echo "WARNING: still bound to all interfaces — run ./ledger.sh check" \
          || echo "bound to loopback only"
        exit 0
      fi
    done
    echo "failed to start — last lines of $LOG:"; tail -8 "$LOG"; exit 1 ;;
  check)
    # Field 4 is the local address, field 5 the peer. A listener always prints
    # its peer as "0.0.0.0:*", so grepping the whole line reported loopback as
    # exposed. Only the local address decides.
    echo "listeners on $PORT:"
    ss -ltnp 2>/dev/null | grep -F ":$PORT " || echo "  none"
    local_addrs="$(ss -ltn 2>/dev/null | awk -v p=":$PORT" '$4 ~ p"$" {print $4}')"
    if [ -z "$local_addrs" ]; then
      echo "not running."
    elif printf '%s\n' "$local_addrs" | grep -qE '^(0\.0\.0\.0|\*|\[::\]):'; then
      echo "EXPOSED on: $local_addrs"
      echo "  reachable from the LAN with no authentication."
    else
      echo "loopback only: $local_addrs"
    fi ;;
  watch)
    # Production hot reload.
    #
    # Two things this must never do: restart once per keystroke, and restart
    # while someone is reading a page. Hence the settle timer and the
    # connection check — without the second one this trades a manual step for
    # dropping whoever is mid-page, which is worse than the problem.
    #
    # inotify-tools is not installed, so this polls. On a tree this size, at a
    # three second interval, that is not worth a dependency.
    # ponytail: polling; swap in inotifywait if the tree ever gets large.
    poll="${POLL:-3}"
    settle="${SETTLE:-6}"
    stamp="$(mktemp)"
    trap 'rm -f "$stamp"' EXIT
    pending=0
    echo "watching $DIR (poll ${poll}s, settle ${settle}s) — ctrl-c to stop"
    while true; do
      sleep "$poll"
      if find "$DIR/ledger_app" "$DIR/assets" -type f \
              \( -name '*.py' -o -name '*.css' -o -name '*.js' \) \
              -newer "$stamp" -print -quit 2>/dev/null | grep -q .; then
        touch "$stamp"
        if [ "$pending" -eq 0 ]; then echo "change detected; settling…"; fi
        pending="$settle"
        continue
      fi
      if [ "$pending" -eq 0 ]; then continue; fi
      pending=$((pending - poll))
      if [ "$pending" -gt 0 ]; then continue; fi
      if ! serving; then
        echo "not running — nothing to restart"
        pending=0
        continue
      fi
      clients="$(ss -tn state established "( sport = :$PORT )" 2>/dev/null \
                 | tail -n +2 | grep -c . || true)"
      if [ "${clients:-0}" -gt 0 ]; then
        echo "$clients client(s) connected — holding"
        pending="$settle"
        continue
      fi
      echo "restarting prod…"
      if "$0" restart; then touch "$stamp"; else echo "restart failed — ./ledger.sh logs"; fi
      pending=0
    done ;;
  restart) "$0" stop; sleep 2; "$0" start ;;
  restart-dev) "$0" stop; sleep 2; "$0" dev ;;
  status)
    if serving; then echo "running (pid $(port_pid))"; echo "$URL"
    else p="$(port_pid)"; [ -n "$p" ] && echo "pid $p on $PORT but not serving — ./ledger.sh restart" || echo "not running"; fi ;;
  open) "$0" start >/dev/null || exit 1; xdg-open "$URL" >/dev/null 2>&1 & echo "$URL" ;;
  logs) tail -n "${2:-40}" "$LOG" ;;
  *) echo "usage: ${0##*/} {start|dev|stop|restart|restart-dev|watch|status|check|open|logs}"; exit 2 ;;
esac
