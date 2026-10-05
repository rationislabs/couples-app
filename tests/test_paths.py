"""Checks for LEDGER_DATA_DIR.

Unset, nothing moves — an existing install keeps its files where they are.
Set, the database, photos and caches all live under it, which is what lets
the container keep every byte of user data on one volume.

    ledger_app/.venv/bin/python tests/test_paths.py
"""
import os
import pathlib

from ledger_app.core import paths

REPO = pathlib.Path(__file__).resolve().parents[1]


def test_unset_keeps_the_old_locations():
    os.environ.pop("LEDGER_DATA_DIR", None)
    os.environ.pop("LEDGER_BACKUP_DIR", None)
    assert paths.db_path() == REPO / "ledger_app" / "ledger.db"
    assert paths.gallery_dir() == REPO / "gallery"
    assert paths.json_dir() == REPO / "json"
    assert paths.backup_dir() == REPO / "backups"


def test_set_puts_all_data_under_it():
    os.environ["LEDGER_DATA_DIR"] = "/data"
    os.environ["LEDGER_BACKUP_DIR"] = "/backups"
    try:
        assert paths.db_path() == pathlib.Path("/data/ledger.db")
        assert paths.gallery_dir() == pathlib.Path("/data/gallery")
        assert paths.json_dir() == pathlib.Path("/data/json")
        assert paths.backup_dir() == pathlib.Path("/backups")
    finally:
        os.environ.pop("LEDGER_DATA_DIR")
        os.environ.pop("LEDGER_BACKUP_DIR")


if __name__ == "__main__":
    saved = {k: os.environ.get(k) for k in ("LEDGER_DATA_DIR", "LEDGER_BACKUP_DIR")}
    try:
        for fn in (test_unset_keeps_the_old_locations, test_set_puts_all_data_under_it):
            fn()
            print(f"  ok  {fn.__name__}")
        print("path checks passed")
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v
