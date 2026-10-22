#!/usr/bin/env bash
# Checks for setup.sh, run against a throwaway copy of the repo skeleton.
# The script is destructive on a real checkout, so nothing here runs it whole;
# these exercise the decisions that would ruin a laptop if they were wrong.
set -u
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/setup.sh"
fail=0

check() { if eval "$2"; then echo "  ok  $1"; else echo "  FAIL $1"; fail=1; fi; }

check "parses"                      "bash -n '$SRC'"
check "is executable"               "[ -x '$SRC' ]"
check "refuses unknown options"     "! bash -c 'set -e; source /dev/stdin --nope' < <(sed -n \"/^while \\[ \\\$# -gt 0 \\]/,/^done/p\" '$SRC') 2>/dev/null"
check "never overwrites an existing .env"  "grep -q 'not overwritten' '$SRC'"
check "never overwrites an existing db"    "grep -q 'left alone' '$SRC'"
check "seeds the home location into the migration" "grep -q 'LEDGER_HOME_LATLON=\"\${HOME_LATLON' '$SRC'"
check "chmods .env to 600"          "grep -q 'chmod 600' '$SRC'"
check "uses uv pip, never bare pip" "! grep -qE '(^|[^ ])\\bpip install' '$SRC' || grep -q 'uv pip install' '$SRC'"
# The closing heredoc *prints* those commands; it does not run them. Strip
# heredoc bodies before looking, or the check fails on its own help text.
code=$(sed "/cat <<'EOF'/,/^EOF$/d" "$SRC")
check "does not start the app" "! printf '%s' \"\$code\" | grep -qE '^[^#]*ledger\\.sh (start|dev|watch)'"
check "refuses to run without uv"   "grep -q 'uv not found' '$SRC'"

# Portability: no source file may hardcode a path that only exists on one box.
# A script once pointed at a /tmp scratch directory for weeks, which made it
# unrunnable anywhere else and one cleanup away from unrunnable here.
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
bad=$(grep -rnE '"/(tmp|home)/[^"]+"' --include='*.py' --include='*.sh' "$REPO" \
      2>/dev/null | grep -v '/\.venv/' | grep -v '/\.web/' \
      | grep -v 'test_setup.sh' || true)
check "no hardcoded /tmp or /home paths in source" "[ -z \"\$bad\" ]"
[ -n "$bad" ] && printf '       %s\n' "$bad"

# The --db restore goes through core/backup.py, which verifies the archive
# before it replaces anything: a truncated backup must not leave a broken
# ledger.db behind that the next run then keeps ("present, left alone").
# Runs only the Database step, against a throwaway directory.
tmp=$(mktemp -d)
block=$(sed -n '/^step "Database"/,/^step "Migrations"/p' "$SRC" | sed '$d')
# Its own bash process: errexit is ignored in a subshell run under `!`.
{ echo 'set -euo pipefail'
  echo 'step() { :; }; ok() { :; }; warn() { :; }'
  echo 'APP="$ROOT/ledger_app"; PY="$APP/.venv/bin/python"; DB="$LEDGER_DATA_DIR/ledger.db"'
  printf '%s\n' "$block"; } > "$tmp/db_step.sh"
run_db_step() {  # $1 = archive
  mkdir -p "$tmp/data"
  ROOT="$(dirname "$SRC")" LEDGER_DATA_DIR="$tmp/data" DB_ARCHIVE="$1" \
    bash "$tmp/db_step.sh" >/dev/null 2>&1
}
printf 'not a database' | gzip -c | head -c 20 > "$tmp/truncated.db.gz"
printf 'not a database' > "$tmp/plain.db"
check "uses the verified restore"           "printf '%s' \"\$block\" | grep -q 'ledger_app.core.backup restore'"
check "a truncated .gz fails the step"      "! run_db_step '$tmp/truncated.db.gz'"
check "and leaves no ledger.db behind"      "[ ! -e '$tmp/data/ledger.db' ]"
check "a plain non-database file fails too" "! run_db_step '$tmp/plain.db' && [ ! -e '$tmp/data/ledger.db' ]"
# A good archive given as a relative path restores (the step runs from ledger_app/).
"$(dirname "$SRC")/ledger_app/.venv/bin/python" -c "import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); c.execute('create table t(x)'); c.commit()" "$tmp/good.db"
gzip -c "$tmp/good.db" > "$tmp/good.db.gz"
check "a valid relative .gz restores" "(cd '$tmp' && run_db_step good.db.gz) && [ -s '$tmp/data/ledger.db' ]"
rm -rf "$tmp"

[ $fail -eq 0 ] && echo "setup checks passed" || echo "setup checks FAILED"
exit $fail
