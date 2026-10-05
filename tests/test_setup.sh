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

# The --db restore path must handle both a .gz and a plain file.
tmp=$(mktemp -d)
printf 'x' > "$tmp/plain.db"; gzip -c "$tmp/plain.db" > "$tmp/arch.db.gz"
case "$tmp/arch.db.gz" in *.gz) gunzip -c "$tmp/arch.db.gz" > "$tmp/out1" ;; esac
case "$tmp/plain.db"   in *.gz) : ;; *) cp "$tmp/plain.db" "$tmp/out2" ;; esac
check "restores a .gz backup"   "[ -s '$tmp/out1' ]"
check "restores a plain file"   "[ -s '$tmp/out2' ]"
rm -rf "$tmp"

[ $fail -eq 0 ] && echo "setup checks passed" || echo "setup checks FAILED"
exit $fail
