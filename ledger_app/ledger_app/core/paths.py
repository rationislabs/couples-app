"""Where the app keeps its data.

LEDGER_DATA_DIR puts the database, the photos and the API caches in one
directory; the container sets it to /data, its volume. Unset, every path is
where it has always been, so an existing install does not move.

Read on every call, not at import, so a test or a script can set the variable
after this module is loaded.
"""
import os
import pathlib

APP = pathlib.Path(__file__).resolve().parents[2]    # ledger_app/
ROOT = APP.parent                                    # the repo root


def _data() -> pathlib.Path | None:
    d = os.environ.get("LEDGER_DATA_DIR")
    return pathlib.Path(d) if d else None


def db_path() -> pathlib.Path:
    d = _data()
    return d / "ledger.db" if d else APP / "ledger.db"


def gallery_dir() -> pathlib.Path:
    d = _data()
    return d / "gallery" if d else ROOT / "gallery"


def json_dir() -> pathlib.Path:
    d = _data()
    return d / "json" if d else ROOT / "json"


def backup_dir() -> pathlib.Path:
    return pathlib.Path(os.environ.get("LEDGER_BACKUP_DIR", ROOT / "backups"))


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
