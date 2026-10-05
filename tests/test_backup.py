"""Checks for core/backup.py.

A backup job that reports success without proving the file restores is how
you find out at the worst moment, so every write is verified, and every
failure path here must refuse rather than half-work.

    ledger_app/.venv/bin/python tests/test_backup.py
"""
import gzip
import os
import pathlib
import sqlite3
import sys
from datetime import datetime, timedelta

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import _db  # noqa: E402
_db.migrate()

from ledger_app.core import backup as B                         # noqa: E402

DB = _db.DATA / "ledger.db"
DEST = _db.DATA / "backups"
os.environ["LEDGER_BACKUP_DIR"] = str(DEST)
T0 = datetime(2026, 10, 1, 3, 30)


def test_write_then_verify():
    out = B.write(DB, DEST, "ledger-20261001-033000.db")
    assert out.name == "ledger-20261001-033000.db.gz"
    assert B.verify(out).startswith("verified ")


def test_a_corrupt_file_fails_verification():
    bad = DEST / "ledger-19990101-000000.db.gz"
    with gzip.open(bad, "wb") as g:
        g.write(b"this is not a database")
    try:
        B.verify(bad)
    except B.BackupError:
        pass
    else:
        raise AssertionError("verify accepted garbage")
    finally:
        bad.unlink()


def test_prune_keeps_the_newest_and_leaves_the_other_kind():
    for i in range(4):
        B.write(DB, DEST, f"ledger-2026090{i}-033000.db")
        B.write(DB, DEST, f"ledger-prestart-2026090{i}-120000.db")
    B.prune(DEST, B.NIGHTLY, 2)
    nightly = sorted(p.name for p in DEST.glob(B.NIGHTLY))
    assert nightly[-2:] == ["ledger-20260903-033000.db.gz", "ledger-20261001-033000.db.gz"]
    assert len(nightly) == 2
    assert len(list(DEST.glob(B.PRESTART))) == 4, "pruning nightlies touched prestart files"


def test_gallery_mirror_keeps_deleted_photos_and_skips_thumbs():
    src = _db.DATA / "gallery"
    (src / "thumbs").mkdir(parents=True, exist_ok=True)
    (src / "a.jpg").write_bytes(b"a")
    (src / "b.jpg").write_bytes(b"b")
    (src / "thumbs" / "a.jpg").write_bytes(b"t")
    B.mirror_gallery(src, DEST / "gallery")
    (src / "b.jpg").unlink()
    live, kept = B.mirror_gallery(src, DEST / "gallery")
    assert (live, kept) == (1, 2)
    assert not (DEST / "gallery" / "thumbs").exists()


def test_nightly_records_success():
    ok, msg = B.nightly(T0 + timedelta(days=1))
    assert ok, msg
    con = sqlite3.connect(DB)
    row = con.execute("select last_backup_ok, last_backup_error from household").fetchone()
    con.close()
    assert row == (1, "")


def test_restore_refuses_a_bad_file():
    bad = DEST / "truncated.db.gz"
    bad.write_bytes(gzip.compress(DB.read_bytes())[:200])
    before = DB.read_bytes()
    try:
        B.restore(bad, DB)
    except B.BackupError:
        pass
    else:
        raise AssertionError("restore accepted a truncated file")
    assert DB.read_bytes() == before, "the current database was touched"
    bad.unlink()


def test_restore_keeps_the_current_database_aside():
    good = B.write(DB, DEST, "ledger-20261002-033000.db")
    aside = B.restore(good, DB)
    assert aside.name == "ledger.db.before-restore" and aside.exists()
    assert B.verify(good)
    aside.unlink()


def test_restore_twice_never_overwrites_the_first_aside():
    original = DB.read_bytes()
    good = B.write(DB, DEST, "ledger-20261003-033000.db")
    a1 = B.restore(good, DB)
    restored = DB.read_bytes()
    a2 = B.restore(good, DB)
    assert a1 != a2 and a1.exists() and a2.exists()
    assert a1.read_bytes() == original, "the first aside was overwritten"
    assert a2.read_bytes() == restored
    a1.unlink(); a2.unlink()


def test_failed_write_leaves_no_partial_file():
    real = B.shutil.copyfileobj
    def boom(src, dst, *a, **k):
        dst.write(b"partial")           # `out` now exists on disk
        raise OSError("disk full")
    B.shutil.copyfileobj = boom
    try:
        B.write(DB, DEST, "ledger-20261004-033000.db")
    except OSError:
        pass
    else:
        raise AssertionError("write swallowed the OSError")
    finally:
        B.shutil.copyfileobj = real
    assert not list(DEST.glob("ledger-20261004-*.db.gz")), "partial backup left behind"


if __name__ == "__main__":
    for fn in (test_write_then_verify, test_a_corrupt_file_fails_verification,
               test_prune_keeps_the_newest_and_leaves_the_other_kind,
               test_gallery_mirror_keeps_deleted_photos_and_skips_thumbs,
               test_nightly_records_success, test_restore_refuses_a_bad_file,
               test_restore_keeps_the_current_database_aside,
               test_restore_twice_never_overwrites_the_first_aside,
               test_failed_write_leaves_no_partial_file):
        fn()
        print(f"  ok  {fn.__name__}")
    print("backup checks passed")
