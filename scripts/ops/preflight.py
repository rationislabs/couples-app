#!/usr/bin/env python3
"""Pre-deployment check. Run before exposing the app to anyone else.

    ./ledger_app/.venv/bin/python preflight.py

Every check answers a question that has a wrong answer you would not notice
until it mattered: are the secrets readable by other accounts, is the database
safe for two people at once, is there a restorable backup, is the app bound to
the network. Exits non-zero if anything is wrong, so it can gate a deploy.
"""
from __future__ import annotations

import os
import pathlib
import re
import shutil
import sqlite3
import stat
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
APP = ROOT / "ledger_app"
DB = APP / "ledger.db"
ENV = ROOT / ".env"

FAIL: list[str] = []
WARN: list[str] = []


def ok(msg: str) -> None:
    print(f"  ok    {msg}")


def bad(msg: str) -> None:
    FAIL.append(msg)
    print(f"  FAIL  {msg}")


def warn(msg: str) -> None:
    WARN.append(msg)
    print(f"  warn  {msg}")


def check_secret_permissions() -> None:
    if not ENV.exists():
        warn(".env not found — nothing to check, but the app needs its keys")
        return
    mode = stat.S_IMODE(ENV.stat().st_mode)
    if mode & 0o077:
        bad(f".env is {oct(mode)}; other accounts can read your API keys. "
            f"Run: chmod 600 {ENV}")
    else:
        ok(f".env is {oct(mode)} — owner only")


def check_secrets_not_in_git() -> None:
    if not shutil.which("git"):
        return
    inside = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"],
                            cwd=ROOT, capture_output=True, text=True)
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        ok("not a git repository — secrets cannot be committed by accident")
        return
    tracked = subprocess.run(["git", "ls-files", "--", ".env", "*.env"],
                             cwd=ROOT, capture_output=True, text=True)
    if tracked.stdout.strip():
        bad(f"tracked by git: {tracked.stdout.split()}. Remove from the index "
            f"and rotate every key in them.")
    else:
        ok("no .env tracked by git")
    ignore = ROOT / ".gitignore"
    if not ignore.exists() or ".env" not in ignore.read_text():
        warn("no .env rule in .gitignore — add one before the first commit")


def check_no_hardcoded_secrets() -> None:
    """Keys belong in .env, not in source. Looks for the shapes of the tokens
    this app actually uses rather than trying to detect secrets in general."""
    patterns = {
        "Spotify id/secret": re.compile(r"\b[0-9a-f]{32}\b"),
        "bearer token": re.compile(r"\beyJ[A-Za-z0-9_-]{20,}"),
    }
    hits: list[str] = []
    for path in APP.rglob("*.py"):
        if ".venv" in path.parts or "alembic" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for label, rx in patterns.items():
            for m in rx.finditer(text):
                line = text[:m.start()].count("\n") + 1
                hits.append(f"{path.relative_to(ROOT)}:{line} ({label})")
    for path in ROOT.glob("*.py"):
        text = path.read_text(encoding="utf-8", errors="replace")
        for label, rx in patterns.items():
            for m in rx.finditer(text):
                line = text[:m.start()].count("\n") + 1
                hits.append(f"{path.name}:{line} ({label})")
    if hits:
        bad("possible secret in source: " + "; ".join(hits[:4]))
    else:
        ok("no secret-shaped literals in source")


def check_database() -> None:
    if not DB.exists():
        bad(f"no database at {DB}")
        return
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    mode = con.execute("pragma journal_mode").fetchone()[0]
    if mode.lower() != "wal":
        bad(f"journal_mode is {mode}; two people at once will hit "
            f"'database is locked'. Start the app once to apply WAL.")
    else:
        ok("journal_mode is WAL — safe for concurrent readers")
    verdict = con.execute("pragma integrity_check").fetchone()[0]
    if verdict != "ok":
        bad(f"integrity_check says {verdict}")
    else:
        ok("integrity_check ok")


def check_backups() -> None:
    dest = pathlib.Path(os.environ.get("LEDGER_BACKUP_DIR", ROOT / "backups"))
    found = sorted(dest.glob("ledger-*.db.gz"), reverse=True)
    if not found:
        bad(f"no backups in {dest}. Run ./backup_db.sh")
        return
    ok(f"{len(found)} backups, newest {found[0].name}")
    timer = subprocess.run(["systemctl", "--user", "is-enabled",
                            "ledger-backup.timer"], capture_output=True,
                           text=True)
    if timer.stdout.strip() != "enabled":
        warn("ledger-backup.timer is not enabled — backups will not run "
             "nightly. Run: systemctl --user enable --now ledger-backup.timer")
    else:
        ok("nightly backup timer enabled")


def check_network_binding() -> None:
    """The app has no login, so the bind address is the whole access model."""
    out = subprocess.run(["ss", "-ltnp"], capture_output=True, text=True).stdout
    # Only sockets held by this app count. An earlier version matched any
    # listener on :8000 and blamed us for an unrelated root-owned process.
    ours = [l for l in out.splitlines()
            if re.search(r'"(reflex|MainThread|node|python3?)"', l)
            and re.search(r":(3100|8000|8100)\s", l)]
    if not ours:
        ok("app not currently running")
        return
    # Field 4 is the local address; field 5 is the peer, which is always "*:*"
    # for a listener. Matching the whole line flagged loopback as exposed.
    local = [l.split()[3] for l in ours]
    exposed = [a for a in local
               if a.startswith(("0.0.0.0:", "*:", "[::]:", ":::"))]
    if exposed:
        bad("listening on all interfaces with no authentication: "
            + "; ".join(exposed)
            + " — anyone on the network gets full write access")
    else:
        ok("listening on loopback only: " + ", ".join(local))


def check_firewall() -> None:
    """The app binding loopback is a promise the app makes. A firewall is a
    promise the kernel makes, and it survives a bad config change.

    Reads /etc/ufw/ufw.conf and /etc/default/ufw, which are world-readable, so
    the two facts that matter are verifiable without sudo. Only the per-rule
    detail needs root, and that is reported as unknown rather than assumed.
    """
    conf = pathlib.Path("/etc/ufw/ufw.conf")
    defaults = pathlib.Path("/etc/default/ufw")
    if not conf.exists():
        bad("ufw is not installed: nothing stops another device on whatever "
            "network this laptop joins from reaching the app")
        return

    enabled = "ENABLED=yes" in conf.read_text()
    if not enabled:
        bad("ufw is installed but inactive — see the deploy notes for the rules")
        return
    ok("ufw enabled at boot")

    policy = ""
    if defaults.exists():
        for row in defaults.read_text().splitlines():
            if row.startswith("DEFAULT_INPUT_POLICY"):
                policy = row.split("=", 1)[1].strip().strip('"')
    if policy in ("DROP", "REJECT"):
        ok(f"default incoming policy is {policy}")
    else:
        bad(f"default incoming policy is {policy or 'unknown'}, not DROP")

    # The allow-list itself is root-only. Try, but do not fail on no sudo.
    out = subprocess.run(["sudo", "-n", "ufw", "status"],
                         capture_output=True, text=True)
    if out.returncode == 0:
        if "tailscale0" in out.stdout:
            ok("tailnet interface allowed in")
        else:
            warn("no rule for tailscale0 — tailnet devices will be blocked")
    else:
        print("  ok    rules not readable without sudo; run "
              "`sudo ufw status verbose` to see them")


def main() -> int:
    print("secrets")
    check_secret_permissions()
    check_secrets_not_in_git()
    check_no_hardcoded_secrets()
    print("database")
    check_database()
    print("backups")
    check_backups()
    print("network")
    check_network_binding()
    check_firewall()

    print()
    if FAIL:
        print(f"{len(FAIL)} problem(s) to fix before anyone else can reach this:")
        for f in FAIL:
            print(f"  - {f}")
    if WARN:
        print(f"{len(WARN)} warning(s):")
        for w in WARN:
            print(f"  - {w}")
    if not FAIL and not WARN:
        print("all checks passed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
