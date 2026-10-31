"""Where the app keeps its data.

HEARTH_DATA_DIR puts the database, the photos and the API caches in one
directory; the container sets it to /data, its volume. Unset, every path is
where it has always been, so an existing install does not move.

Read on every call, not at import, so a test or a script can set the variable
after this module is loaded.
"""
import os
import pathlib

APP = pathlib.Path(__file__).resolve().parents[2]    # hearth/
ROOT = APP.parent                                    # the repo root


def _data() -> pathlib.Path | None:
    d = os.environ.get("HEARTH_DATA_DIR")
    return pathlib.Path(d) if d else None


def db_path() -> pathlib.Path:
    d = _data()
    db = d / "hearth.db" if d else APP / "hearth.db"
    if not db.exists():
        _adopt_ledger_db(db)
    return db


def _adopt_ledger_db(db: pathlib.Path) -> None:
    """Before the rename to Hearth the database was ledger.db, and a host
    install kept it in ledger_app/, which a git pull leaves behind. Move it
    (with its -wal and -shm) once, so an update never opens an empty one."""
    for old in (db.with_name("ledger.db"), ROOT / "ledger_app" / "ledger.db"):
        if old.exists():
            for suffix in ("", "-wal", "-shm"):
                src = pathlib.Path(f"{old}{suffix}")
                if src.exists():
                    os.replace(src, f"{db}{suffix}")
            return


def gallery_dir() -> pathlib.Path:
    d = _data()
    return d / "gallery" if d else ROOT / "gallery"


def json_dir() -> pathlib.Path:
    d = _data()
    return d / "json" if d else ROOT / "json"


def backup_dir() -> pathlib.Path:
    d = pathlib.Path(os.environ.get("HEARTH_BACKUP_DIR", ROOT / "backups"))
    # backups from before the rename take the new prefix, so pruning, verify
    # and restore keep seeing them
    for old in d.glob("ledger-*.db.gz"):
        new = old.with_name("hearth-" + old.name.removeprefix("ledger-"))
        if not new.exists():
            os.replace(old, new)
    return d


def secrets_dir() -> pathlib.Path:
    """Where a script may save a secret it was handed at run time (a rotated
    refresh token) when there is no .env: the container has none."""
    return _data() or APP


def atomic_write_text(path: pathlib.Path, text: str, mode: int = 0o600) -> None:
    """Write via a temp file and os.replace, so a crash mid-write never leaves
    the file half-written."""
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)
