#!/usr/bin/env bash
# Run the Reflex media ledger.
# Usage: ./ledger.sh {start|dev|stop|restart|restart-dev|watch|status|check|open|logs}
#   start = prod build, dev = hot reload. Both bind loopback only.
set -euo pipefail
umask 077   # ledger.db, backups and photos are private: owner-only
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
PORT="${PORT:-3100}"
URL="http://localhost:$PORT/"
LOG="$DIR/reflex.log"

port_pid(){ ss -ltnp 2>/dev/null | grep -F ":$PORT " | grep -o "pid=[0-9]*" | head -1 | cut -d= -f2 || true; }
held(){ ss -ltn 2>/dev/null | awk -v p=":$PORT" '$4 ~ p"$"' | grep -q .; }
# Only a process of this checkout is the app: it runs from ledger_app/ or from
# its .venv. Anything else on the port (another copy, another program) is left
# alone; ss shows no pid at all for another user's process.
ours(){ [ "$(readlink "/proc/$1/cwd" 2>/dev/null)" = "$DIR" ] \
        || tr '\0' ' ' < "/proc/$1/cmdline" 2>/dev/null | grep -qF "$DIR/"; }
app_pid(){ local p; p="$(port_pid)"; if [ -n "$p" ] && ours "$p"; then echo "$p"; fi; }
other(){ local p; p="$(port_pid)"; echo "port $PORT is held by another program${p:+ (pid $p)}; $1"; }
# The app runs in its own process group (setsid below): in dev the port is held
# by Vite, and the backend and reflex itself are siblings no port leads to.
# Stopping the group stops all of it. A group whose leader is not ours (an app
# started before setsid) only loses the process on the port.
halt(){ local g; g="$(ps -o pgid= -p "$1" | tr -d ' ')"
        if [ -n "$g" ] && ours "$g"; then kill -INT -- "-$g"; else kill -INT "$1"; fi 2>/dev/null || true; }
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
    p="$(app_pid)"
    if [ -n "$p" ]; then
      if serving; then echo "already running"; echo "$URL"; t="$(tailnet_url)" && echo "$t"; exit 0; fi
      echo "port $PORT held by pid $p but not serving — stopping it"; halt "$p"; sleep 2
    elif held; then other "set PORT to a free one"; exit 1; fi
    ( cd "$DIR" && : > "$LOG" && exec setsid nohup ./.venv/bin/reflex run --env prod --single-port --frontend-port "$PORT" --backend-host 127.0.0.1 >"$LOG" 2>&1 ) &
    echo "building (prod builds the frontend)…"
    for _ in $(seq 1 15); do
      sleep 4
      if serving; then echo "started"; echo "$URL"; t="$(tailnet_url)" && echo "$t"; exit 0; fi
    done
    echo "failed to start — last lines of $LOG:"; tail -8 "$LOG"; exit 1 ;;
  stop)
    p="$(app_pid)"
    if [ -n "$p" ]; then halt "$p"; echo "stopped"
    elif held; then other "not stopping it"
    else echo "not running"; fi ;;
  dev)
    # Vite binds loopback through the dev script rxconfig.py sets; the check
    # after start below catches it if that ever stops holding.
    p="$(app_pid)"
    if [ -n "$p" ]; then
      if serving; then echo "already running"; echo "$URL"; exit 0; fi
      echo "port $PORT held by pid $p — stopping it"; halt "$p"; sleep 2
    elif held; then other "set PORT to a free one"; exit 1; fi
    # Pin the dev backend port here rather than in rxconfig.py: prod refuses to
    # start when both ports are set and differ, and dev needs them to differ.
    ( cd "$DIR" && : > "$LOG" && exec setsid nohup ./.venv/bin/reflex run --frontend-port "$PORT" --backend-host 127.0.0.1 --backend-port 8100 >"$LOG" 2>&1 ) &
    echo "starting dev (hot reload)…"
    for _ in $(seq 1 20); do
      sleep 3
      if serving; then
        echo "started"; echo "$URL"
        ss -ltn 2>/dev/null | awk -v p=":$PORT" '$4 ~ p"$" {print $4}' | grep -qE '^(0\.0\.0\.0|\*|\[::\]):' \
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
    p="$(app_pid)"
    if [ -n "$p" ] && serving; then echo "running (pid $p)"; echo "$URL"
    elif [ -n "$p" ]; then echo "pid $p on $PORT but not serving — ./ledger.sh restart"
    elif held; then other "this app is not running"
    else echo "not running"; fi ;;
  open) "$0" start >/dev/null || exit 1; xdg-open "$URL" >/dev/null 2>&1 & echo "$URL" ;;
  logs) tail -n "${2:-40}" "$LOG" ;;
  *) echo "usage: ${0##*/} {start|dev|stop|restart|restart-dev|watch|status|check|open|logs}"; exit 2 ;;
esac
