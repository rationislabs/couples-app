#!/usr/bin/env python3
"""Prove a backup file is restorable. Called by backup_db.sh.

    python verify_backup.py <path-to-db> <label>

Exits non-zero if the file fails integrity_check or is empty. An empty backup
that opens cleanly is worse than no backup, because it reports success.
"""
from __future__ import annotations

import sqlite3
import sys

# Tables that must never be empty. If a future import wipes one of these, the
# backup that captured the wipe should not pass verification silently. Empty
# here because a new install has no data; add "place", "title" and the like
# once yours hold rows you would miss.
MUST_HAVE: tuple[str, ...] = ()
ALSO_COUNT = ("place", "title", "convoquestion", "recipe")


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__, file=sys.stderr)
        return 2
    path, label = sys.argv[1], sys.argv[2]

    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    verdict = con.execute("pragma integrity_check").fetchone()[0]
    if verdict != "ok":
        print(f"{label}: integrity_check said {verdict}", file=sys.stderr)
        return 1

    counts: dict[str, int] = {}
    for table in MUST_HAVE + ALSO_COUNT:
        try:
            counts[table] = con.execute(
                f"select count(*) from {table}").fetchone()[0]
        except sqlite3.Error:
            counts[table] = -1              # table absent

    empty = [t for t in MUST_HAVE if counts.get(t, 0) <= 0]
    if empty:
        print(f"{label}: empty or missing {', '.join(empty)} — {counts}",
              file=sys.stderr)
        return 1

    print(f"verified {label}: integrity ok, "
          + ", ".join(f"{k}={v}" for k, v in counts.items() if v >= 0))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
