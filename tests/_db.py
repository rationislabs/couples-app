"""A throwaway database for one test file.

Import this before anything from ledger_app: state.py builds ENGINE at import
time from LEDGER_DATA_DIR, so the variable has to be set first.

    import _db            # first line after the stdlib imports
    _db.migrate()         # to head; or _db.migrate("c9d77a53878c")
"""
import atexit
import os
import pathlib
import shutil
import tempfile

DATA = pathlib.Path(tempfile.mkdtemp(prefix="couples-test-"))
atexit.register(shutil.rmtree, DATA, ignore_errors=True)
os.environ["LEDGER_DATA_DIR"] = str(DATA)
APP = pathlib.Path(__file__).resolve().parents[1] / "ledger_app"


def migrate(revision: str = "head") -> None:
    from alembic import command
    from alembic.config import Config
    cfg = Config(str(APP / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{DATA / 'ledger.db'}")
    command.upgrade(cfg, revision)
