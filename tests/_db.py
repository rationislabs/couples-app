"""A throwaway database for one test file.

Import this before anything from hearth: state.py builds ENGINE at import
time from HEARTH_DATA_DIR, so the variable has to be set first.

    import _db            # first line after the stdlib imports
    _db.migrate()         # to head; or _db.migrate("c9d77a53878c")
"""
import atexit
import os
import pathlib
import shutil
import tempfile

DATA = pathlib.Path(tempfile.mkdtemp(prefix="hearth-test-"))
atexit.register(shutil.rmtree, DATA, ignore_errors=True)
os.environ["HEARTH_DATA_DIR"] = str(DATA)
APP = pathlib.Path(__file__).resolve().parents[1] / "hearth"


def migrate(revision: str = "head") -> None:
    from alembic import command
    from alembic.config import Config
    cfg = Config(str(APP / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{DATA / 'hearth.db'}")
    command.upgrade(cfg, revision)
