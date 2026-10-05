"""Backups: write, verify, prune, mirror the photos, restore.

One module for the container's nightly task, the start-up backup, the
`restore` command and backup_db.sh on a host install, so they cannot drift.

SQLite's online backup API, not a file copy: under WAL a raw copy can catch
the database mid-transaction and miss the -wal sidecar, giving a file that
looks fine and restores corrupt. The source is opened read-only so a backup
can never be what corrupts it.

    python -m ledger_app.core.backup backup          # nightly: database and photos
    python -m ledger_app.core.backup prestart        # before migrating: database only
    python -m ledger_app.core.backup verify [FILE]   # newest nightly when no FILE
    python -m ledger_app.core.backup restore FILE    # the app must be stopped
"""
from __future__ import annotations

import asyncio
import gzip
import os
import pathlib
import shutil
import sqlite3
import sys
import tempfile
from contextlib import closing
from datetime import datetime, timedelta

from . import paths

# Tables that must never be empty. Empty here because a new install has no
# data; add "place", "title" and the like once yours hold rows you would miss.
MUST_HAVE: tuple[str, ...] = ()
ALSO_COUNT = ("place", "title", "convoquestion", "recipe")

NIGHTLY = "ledger-[0-9]*.db.gz"        # ledger-20261001-033000.db.gz, backup_db.sh's old names too
PRESTART = "ledger-prestart-*.db.gz"
PRESTART_KEEP = 5


class BackupError(Exception):
    pass


def _stamp(now: datetime) -> str:
    return now.strftime("%Y%m%d-%H%M%S")


def verify(gz: pathlib.Path) -> str:
    """Decompress to a temp file and prove it opens. One-line summary, or BackupError."""
    with tempfile.TemporaryDirectory() as tmp:
        raw = pathlib.Path(tmp) / "check.db"
        try:
            with gzip.open(gz, "rb") as g, open(raw, "wb") as f:
                shutil.copyfileobj(g, f)
        except (OSError, EOFError) as e:
            raise BackupError(f"{gz.name}: cannot decompress ({e})") from None
        with closing(sqlite3.connect(f"file:{raw}?mode=ro", uri=True)) as con:
            try:
                verdict = con.execute("pragma integrity_check").fetchone()[0]
            except sqlite3.DatabaseError as e:
                raise BackupError(f"{gz.name}: not a database ({e})") from None
            if verdict != "ok":
                raise BackupError(f"{gz.name}: integrity_check said {verdict}")
            counts: dict[str, int] = {}
            for table in MUST_HAVE + ALSO_COUNT:
                try:
                    counts[table] = con.execute(f"select count(*) from {table}").fetchone()[0]
                except sqlite3.Error:
                    counts[table] = -1          # table absent
    empty = [t for t in MUST_HAVE if counts.get(t, 0) <= 0]
    if empty:
        raise BackupError(f"{gz.name}: empty or missing {', '.join(empty)}")
    return f"verified {gz.name}: " + ", ".join(f"{k}={v}" for k, v in counts.items() if v >= 0)


def write(db: pathlib.Path, dest: pathlib.Path, name: str) -> pathlib.Path:
    """Online-backup `db` to dest/<name>.gz, then verify it. A file that fails
    verification is deleted, so a bad backup never sits among good ones."""
    if not db.exists():
        raise BackupError(f"no database at {db}")
    dest.mkdir(parents=True, exist_ok=True)
    out = dest / f"{name}.gz"
    try:
        with tempfile.TemporaryDirectory(dir=dest) as tmp:
            raw = pathlib.Path(tmp) / name
            with closing(sqlite3.connect(f"file:{db}?mode=ro", uri=True)) as src, \
                 closing(sqlite3.connect(raw)) as dst:
                src.backup(dst)
            with open(raw, "rb") as f, gzip.open(out, "wb") as g:
                shutil.copyfileobj(f, g)
        verify(out)
    except BaseException:
        out.unlink(missing_ok=True)     # never leave a partial file that sorts as the newest
        raise
    return out


def prune(dest: pathlib.Path, pattern: str, keep: int) -> list[pathlib.Path]:
    """Delete all but the `keep` newest files matching `pattern`. Names carry
    the timestamp, so name order is age order."""
    files = sorted(dest.glob(pattern), reverse=True)
    for old in files[keep:]:
        old.unlink()
    return files[keep:]


def mirror_gallery(src: pathlib.Path, dest: pathlib.Path) -> tuple[int, int]:
    """Copy new and changed photos; never delete. A mirror, not a snapshot per
    night: 30 copies of 100 phone photos would be tens of GB. A photo removed
    in the app stays here, so freeing space under the cap is recoverable.
    thumbs/ is skipped; the app regenerates it. Returns (live, kept)."""
    if not src.is_dir():
        return 0, 0
    shutil.copytree(src, dest, dirs_exist_ok=True, ignore=shutil.ignore_patterns("thumbs"))
    live = sum(1 for p in src.iterdir() if p.is_file())
    kept = sum(1 for p in dest.iterdir() if p.is_file())
    if kept < live:
        raise BackupError(f"gallery copy short: {kept} of {live} photos")
    return live, kept


def record(db: pathlib.Path, ok: bool, error: str = "", now: datetime | None = None) -> None:
    """Write the outcome where the app shows it (Settings and the header
    banner). Skipped when there is no database yet, and before the migration
    that creates `household` — the start-up backup runs before migrating."""
    if not db.exists():
        return
    try:
        with closing(sqlite3.connect(db)) as con, con:
            con.execute(
                "update household set last_backup_at = ?, last_backup_ok = ?, "
                "last_backup_error = ? where id = 1",
                ((now or datetime.now()).isoformat(sep=" "), ok, error))
    except sqlite3.Error:
        pass


def _keep() -> int:
    try:
        return max(1, int(os.environ.get("LEDGER_BACKUP_KEEP") or 30))
    except ValueError:
        return 30


def nightly(now: datetime | None = None) -> tuple[bool, str]:
    """Database and photos, then the outcome recorded. Never raises: the
    caller is a loop that has to survive a bad night and try the next one."""
    now = now or datetime.now()
    db, dest = paths.db_path(), paths.backup_dir()
    try:
        out = write(db, dest, f"ledger-{_stamp(now)}.db")
        prune(dest, NIGHTLY, _keep())
        live, kept = mirror_gallery(paths.gallery_dir(), dest / "gallery")
    except Exception as e:      # noqa: BLE001 — any failure is recorded, see docstring
        record(db, False, str(e), now)
        return False, f"backup FAILED: {e}"
    record(db, True, "", now)
    return True, f"wrote {out.name}; gallery {live} live, {kept} kept"


def prestart(now: datetime | None = None) -> str:
    """Before every start, so the database an update migrates can be got back.
    Raises on failure: the container must not migrate without it."""
    now = now or datetime.now()
    db, dest = paths.db_path(), paths.backup_dir()
    if not db.exists():
        return "no database yet; nothing to back up"
    out = write(db, dest, f"ledger-prestart-{_stamp(now)}.db")
    prune(dest, PRESTART, PRESTART_KEEP)
    # Not recorded: the banner and due_at_start() track the nightly backup
    # (database AND photos). Recording here would clear a "failed" banner on
    # every restart and stop a machine that is off at 03:30 ever catching up.
    return f"wrote {out.name}"


def restore(gz: pathlib.Path, db: pathlib.Path) -> pathlib.Path:
    """Replace `db` with the backup in `gz`. Verifies first, and moves the
    current database (and its -wal) to <db>.before-restore so a wrong choice
    can be undone. Returns that path. The app must be stopped."""
    verify(gz)
    aside = db.with_name(db.name + ".before-restore")
    if aside.exists() or pathlib.Path(f"{aside}-wal").exists():
        aside = db.with_name(f"{db.name}.before-restore-{_stamp(datetime.now())}")
        if aside.exists() or pathlib.Path(f"{aside}-wal").exists():
            raise BackupError(f"{aside.name} already exists; move it away and retry")
    if db.exists():
        shutil.move(db, aside)
    wal = pathlib.Path(f"{db}-wal")
    if wal.exists():
        shutil.move(wal, pathlib.Path(f"{aside}-wal"))
    pathlib.Path(f"{db}-shm").unlink(missing_ok=True)
    with gzip.open(gz, "rb") as g, open(db, "wb") as f:
        shutil.copyfileobj(g, f)
    return aside


def seconds_until(at: str, now: datetime) -> float:
    """Seconds from `now` to the next HH:MM. Exactly HH:MM means tomorrow."""
    hour, minute = (int(x) for x in at.split(":"))
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


def due_at_start(db: pathlib.Path, now: datetime) -> bool:
    """A backup at start-up when the last one failed, never ran, or is over a
    day old: covers a fresh install and a machine that was off at 03:30."""
    try:
        with closing(sqlite3.connect(f"file:{db}?mode=ro", uri=True)) as con:
            at, ok = con.execute(
                "select last_backup_at, last_backup_ok from household where id = 1").fetchone()
        return not ok or at is None or now - datetime.fromisoformat(at) > timedelta(hours=24)
    except (sqlite3.Error, TypeError, ValueError):
        return True


def backup_at() -> str:
    """LEDGER_BACKUP_AT when it is a valid HH:MM, else 03:30 with a warning, so
    a typo cannot kill the loop."""
    v = os.environ.get("LEDGER_BACKUP_AT", "03:30")
    try:
        h, m = v.split(":")
        if len(h) == 2 and len(m) == 2 and 0 <= int(h) <= 23 and 0 <= int(m) <= 59:
            return v
    except ValueError:
        pass
    print(f"LEDGER_BACKUP_AT={v!r} is not HH:MM; using 03:30")
    return "03:30"


async def nightly_loop() -> None:
    """Lifespan task. Runs only when LEDGER_BACKUP_SCHEDULE=1, which the image
    sets, so a host install keeps its own systemd timer instead of backing up
    twice. One backend worker (no Redis) means one loop."""
    if os.environ.get("LEDGER_BACKUP_SCHEDULE") != "1":
        return
    if due_at_start(paths.db_path(), datetime.now()):
        print((await asyncio.to_thread(nightly))[1])
    while True:
        await asyncio.sleep(seconds_until(backup_at(), datetime.now()))
        print((await asyncio.to_thread(nightly))[1])


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else "backup"
    try:
        if cmd == "backup":
            ok, msg = nightly()
            print(msg)
            return 0 if ok else 1
        if cmd == "prestart":
            print(prestart())
            return 0
        if cmd == "verify":
            files = sorted(paths.backup_dir().glob(NIGHTLY))
            target = pathlib.Path(argv[1]) if len(argv) > 1 else (files[-1] if files else None)
            if target is None:
                raise BackupError(f"no backups to verify in {paths.backup_dir()}")
            print(verify(target))
            return 0
        if cmd == "restore" and len(argv) == 2:
            aside = restore(pathlib.Path(argv[1]), paths.db_path())
            print(f"restored {argv[1]}; the previous database is at {aside}")
            return 0
    except BackupError as e:
        print(f"backup FAILED: {e}", file=sys.stderr)
        return 1
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
