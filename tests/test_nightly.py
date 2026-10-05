"""Checks for the scheduled backup.

Nobody reads container logs, so a failure has to land where the header
banner can see it, and the loop has to survive it.

    ledger_app/.venv/bin/python tests/test_nightly.py
"""
import os
import sqlite3
import pathlib
import sys
from datetime import datetime, timedelta

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import _db  # noqa: E402
_db.migrate()

from ledger_app.core import backup as B                         # noqa: E402
from ledger_app.core import household as H                      # noqa: E402

DB = _db.DATA / "ledger.db"


def test_seconds_until():
    now = datetime(2026, 10, 1, 3, 0)
    assert B.seconds_until("03:30", now) == 30 * 60
    assert B.seconds_until("03:00", now) == 24 * 3600, "at the minute means tomorrow"
    assert B.seconds_until("02:00", now) == 23 * 3600


def test_failure_is_recorded_and_not_raised():
    blocker = _db.DATA / "not-a-dir"
    blocker.write_text("a file where the backups directory should be")
    os.environ["LEDGER_BACKUP_DIR"] = str(blocker)
    try:
        ok, msg = B.nightly(datetime(2026, 10, 1, 3, 30))
    finally:
        del os.environ["LEDGER_BACKUP_DIR"]
    assert ok is False and msg.startswith("backup FAILED")
    assert H.backup_warning(datetime(2026, 10, 1, 3, 31)).startswith("Last backup failed")


def test_due_at_start():
    now = datetime(2026, 10, 1, 12, 0)
    B.record(DB, True, "", now - timedelta(hours=2))
    assert B.due_at_start(DB, now) is False
    B.record(DB, True, "", now - timedelta(hours=30))
    assert B.due_at_start(DB, now) is True
    B.record(DB, False, "disk full", now - timedelta(hours=1))
    assert B.due_at_start(DB, now) is True
    with sqlite3.connect(DB) as con:
        con.execute("update household set last_backup_at = 'garbage', last_backup_ok = 1 where id = 1")
    assert B.due_at_start(DB, now) is True, "a corrupt timestamp means due, not a crash"


def test_backup_at_falls_back():
    old = os.environ.get("LEDGER_BACKUP_AT")
    try:
        for bad in ("0330", "25:00", "abc", "", "03:60"):
            os.environ["LEDGER_BACKUP_AT"] = bad
            assert B.backup_at() == "03:30", bad
        os.environ["LEDGER_BACKUP_AT"] = "06:15"
        assert B.backup_at() == "06:15"
    finally:
        if old is None:
            os.environ.pop("LEDGER_BACKUP_AT", None)
        else:
            os.environ["LEDGER_BACKUP_AT"] = old


def test_prestart_does_not_reset_the_banner():
    now = datetime(2026, 10, 1, 12, 0)
    B.record(DB, False, "disk full", now - timedelta(hours=1))
    os.environ["LEDGER_BACKUP_DIR"] = str(_db.DATA / "prestart-backups")
    try:
        B.prestart(now)
    finally:
        del os.environ["LEDGER_BACKUP_DIR"]
    assert H.backup_warning(now).startswith("Last backup failed")
    assert B.due_at_start(DB, now) is True


def test_banner_after_48_hours_only():
    at = datetime(2026, 10, 1, 3, 30)
    B.record(DB, True, "", at)
    assert H.backup_warning(at + timedelta(hours=47)) == ""
    assert H.backup_warning(at + timedelta(hours=49)).startswith("No backup since")


if __name__ == "__main__":
    for fn in (test_seconds_until, test_failure_is_recorded_and_not_raised,
               test_due_at_start, test_backup_at_falls_back, test_prestart_does_not_reset_the_banner,
               test_banner_after_48_hours_only):
        fn()
        print(f"  ok  {fn.__name__}")
    print("nightly checks passed")
