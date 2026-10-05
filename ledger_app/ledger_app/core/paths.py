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
