"""Checks for number fields: a character that looks like a digit is refused
with a notice, never a crash.

    ledger_app/.venv/bin/python tests/test_numbers.py

str.isdigit() is True for "²" and "①", which int() then rejects with
ValueError inside the event handler. isdecimal() is what int() accepts.
"""
import pathlib
import re

import _db  # first: never the real ledger.db

_db.migrate()

from sqlmodel import Session  # noqa: E402

from ledger_app.core import inline as IN  # noqa: E402
from ledger_app.core.models import Game  # noqa: E402
from ledger_app.core.state import ENGINE  # noqa: E402
from ledger_app.pages.home import HomeState  # noqa: E402

APP = pathlib.Path(__file__).resolve().parents[1] / "ledger_app" / "ledger_app"


def test_superscript_rating_is_a_notice():
    with Session(ENGINE) as s:
        g = Game(name="zz-number-game")
        s.add(g)
        s.commit()
        gid = g.id
    msg = IN.save(Game, gid, "rating", "²")
    assert "rating is 1" in msg, msg


def test_radius_label_with_superscript():
    st = HomeState(_reflex_internal_init=True)
    HomeState.set_radius.fn(st, "²5 km")
    assert st.radius_km == 5


def test_no_isdigit_left_before_int():
    left = [f"{p.relative_to(APP)}:{i}" for p in APP.rglob("*.py")
            for i, line in enumerate(p.read_text().splitlines(), 1)
            if re.search(r"\.isdigit\(\)", line)]
    assert not left, left


if __name__ == "__main__":
    for fn in (test_superscript_rating_is_a_notice, test_radius_label_with_superscript,
               test_no_isdigit_left_before_int):
        fn()
        print(f"  ok  {fn.__name__}")
    print("number checks passed")
