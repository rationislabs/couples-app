"""Checks for scripts/seed/seed_demo.py: made-up data, and only into an empty ledger.

    ledger_app/.venv/bin/python tests/test_seed_demo.py
"""
import importlib.util
import os
import pathlib
import subprocess
import sys

import _db  # first: never the real ledger.db
_db.migrate()

from sqlmodel import Session, select  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/seed/seed_demo.py"
spec = importlib.util.spec_from_file_location("seed_demo", SCRIPT)
seed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seed)


def test_fills_an_empty_ledger():
    from ledger_app.core import household
    from ledger_app.core.models import Place, Recipe, RecipeStep

    seed.main()
    assert household.names() == {"1": "Alex", "2": "Sam"}
    assert household.settings().setup_done and household.home() == seed.VIENNA
    with Session(seed.ENGINE) as s:
        assert len(s.exec(select(Recipe)).all()) == len(seed.RECIPES)
        assert len(s.exec(select(Place)).all()) == len(seed.PLACES)
        assert s.exec(select(RecipeStep)).first() is not None


def test_never_twice_and_never_into_a_real_ledger():
    try:
        seed.main()
    except SystemExit as e:
        assert "not empty" in str(e)
    else:
        raise AssertionError("seeded a ledger that already had data")
    env = {k: v for k, v in os.environ.items() if k != "LEDGER_DATA_DIR"}
    out = subprocess.run([sys.executable, str(SCRIPT)], env=env, capture_output=True, text=True)
    assert out.returncode != 0 and "LEDGER_DATA_DIR" in out.stderr


if __name__ == "__main__":
    for fn in (test_fills_an_empty_ledger, test_never_twice_and_never_into_a_real_ledger):
        fn()
        print(f"  ok  {fn.__name__}")
    print("demo seed checks passed")
