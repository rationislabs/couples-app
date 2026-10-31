"""Checks for HEARTH_DATA_DIR.

Unset, nothing moves — an existing install keeps its files where they are.
Set, the database, photos and caches all live under it, which is what lets
the container keep every byte of user data on one volume.

    hearth/.venv/bin/python tests/test_paths.py
"""
import os
import pathlib

import _db  # noqa: F401  (first: never the real hearth.db)

from hearth.core import paths

REPO = pathlib.Path(__file__).resolve().parents[1]


def test_unset_keeps_the_old_locations():
    os.environ.pop("HEARTH_DATA_DIR", None)
    os.environ.pop("HEARTH_BACKUP_DIR", None)
    assert paths.db_path() == REPO / "hearth" / "hearth.db"
    assert paths.gallery_dir() == REPO / "gallery"
    assert paths.json_dir() == REPO / "json"
    assert paths.backup_dir() == REPO / "backups"


def test_set_puts_all_data_under_it():
    os.environ["HEARTH_DATA_DIR"] = "/data"
    os.environ["HEARTH_BACKUP_DIR"] = "/backups"
    try:
        assert paths.db_path() == pathlib.Path("/data/hearth.db")
        assert paths.gallery_dir() == pathlib.Path("/data/gallery")
        assert paths.json_dir() == pathlib.Path("/data/json")
        assert paths.backup_dir() == pathlib.Path("/backups")
    finally:
        os.environ.pop("HEARTH_DATA_DIR")
        os.environ.pop("HEARTH_BACKUP_DIR")


def test_an_install_from_before_the_rename_keeps_its_data():
    """ledger.db and ledger-*.db.gz become hearth.db and hearth-*.db.gz, once."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        data, dest = pathlib.Path(tmp, "data"), pathlib.Path(tmp, "backups")
        data.mkdir(), dest.mkdir()
        (data / "ledger.db").write_text("db")
        (data / "ledger.db-wal").write_text("wal")
        (dest / "ledger-20261001-033000.db.gz").write_text("gz")
        os.environ["HEARTH_DATA_DIR"], os.environ["HEARTH_BACKUP_DIR"] = str(data), str(dest)
        try:
            assert paths.db_path().read_text() == "db"
            assert (data / "hearth.db-wal").read_text() == "wal"
            assert not (data / "ledger.db").exists()
            paths.backup_dir()
            assert [f.name for f in dest.iterdir()] == ["hearth-20261001-033000.db.gz"]
            (data / "ledger.db").write_text("stale")       # a new database is never replaced
            assert paths.db_path().read_text() == "db"
        finally:
            os.environ.pop("HEARTH_DATA_DIR")
            os.environ.pop("HEARTH_BACKUP_DIR")


if __name__ == "__main__":
    saved = {k: os.environ.get(k) for k in ("HEARTH_DATA_DIR", "HEARTH_BACKUP_DIR")}
    try:
        for fn in (test_unset_keeps_the_old_locations, test_set_puts_all_data_under_it,
                   test_an_install_from_before_the_rename_keeps_its_data):
            fn()
            print(f"  ok  {fn.__name__}")
        print("path checks passed")
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v
