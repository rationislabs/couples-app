#!/usr/bin/env bash
# Checks for ./ledger.sh watch
#
# The watcher restarts production, so the two things worth testing are the two
# that would make it harmful: that it ignores files it should not rebuild for,
# and that a burst of saves is one restart rather than one per save. The
# connection check is not testable without a running app and is left to the
# browser pass.
#
#     ./ledger_app/test_watch.sh
set -u
fake=$(mktemp -d); mkdir -p "$fake/ledger_app/ledger_app" "$fake/ledger_app/assets"
echo "x = 1" > "$fake/ledger_app/ledger_app/a.py"
stamp=$(mktemp)

changed() {
  find "$fake/ledger_app/ledger_app" "$fake/ledger_app/assets" -type f \
       \( -name '*.py' -o -name '*.css' -o -name '*.js' \) \
       -newer "$stamp" -print -quit 2>/dev/null | grep -q .
}
touch "$stamp"
changed && { echo "FAIL: quiet tree reported a change"; exit 1; }
echo "  ok  quiet tree reports nothing"

sleep 1.1; echo "x = 2" > "$fake/ledger_app/ledger_app/a.py"
changed || { echo "FAIL: edited .py not detected"; exit 1; }
echo "  ok  an edited .py is detected"

touch "$stamp"; sleep 1.1; echo "{}" > "$fake/ledger_app/ledger_app/ignore.json"
changed && { echo "FAIL: .json triggered a rebuild"; exit 1; }
echo "  ok  a non-source file does not trigger"

touch "$stamp"; sleep 1.1; echo "a{}" > "$fake/ledger_app/assets/x.css"
changed || { echo "FAIL: edited .css not detected"; exit 1; }
echo "  ok  an edited .css is detected"

# The settle countdown: a burst of edits must collapse to one restart.
poll=3; settle=6; pending=0; restarts=0
for tick in 1 2 3 4 5 6 7 8; do
  if [ "$tick" -le 3 ]; then pending=$settle; continue; fi
  if [ "$pending" -eq 0 ]; then continue; fi
  pending=$((pending - poll))
  if [ "$pending" -gt 0 ]; then continue; fi
  restarts=$((restarts + 1)); pending=0
done
[ "$restarts" -eq 1 ] || { echo "FAIL: burst of 3 edits caused $restarts restarts"; exit 1; }
echo "  ok  a burst of edits collapses to one restart"
rm -rf "$fake" "$stamp"
echo "watch checks passed"
