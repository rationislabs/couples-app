"""Checks for the TMDB pick queue (tmdb-ambiguous.json): no pick undoes another.

    ledger_app/.venv/bin/python tests/test_ambiguous.py

Each browser tab held its own copy of the queue and wrote it back whole, so a
pick in one tab (or a tmdb_fill.py run in between) brought back entries the
other had already dropped.
"""
import json
import os

import _db  # first: never the real ledger.db

_db.migrate()

from ledger_app.core import sync_io  # noqa: E402
from ledger_app.core.state import LedgerState  # noqa: E402

F = sync_io.DATA / "tmdb-ambiguous.json"


def entry():
    return {"candidates": [], "note": ""}


def tab():
    st = LedgerState(_reflex_internal_init=True)
    LedgerState.load_ambiguous.fn(st)
    return st


def drop(st, name):
    st.amb_index = sorted(st._ambig).index(name)
    st._drop_ambig()


def test_two_tabs_and_a_script_keep_each_others_changes():
    F.write_text(json.dumps({"Alpha": entry(), "Beta": entry()}))
    a, b = tab(), tab()
    # tmdb_fill.py adds a title while both tabs are open
    F.write_text(json.dumps({"Alpha": entry(), "Beta": entry(), "Gamma": entry()}))
    drop(a, "Alpha")
    drop(b, "Beta")
    assert sorted(json.loads(F.read_text())) == ["Gamma"], F.read_text()
    assert sorted(b._ambig) == ["Gamma"]


def test_the_write_is_atomic():
    F.write_text(json.dumps({"Alpha": entry()}))
    st = tab()
    seen = []
    real = os.replace
    os.replace = lambda a, b: (seen.append(str(b)), real(a, b))
    try:
        drop(st, "Alpha")
    finally:
        os.replace = real
    assert seen == [str(F)], seen


if __name__ == "__main__":
    for fn in (test_two_tabs_and_a_script_keep_each_others_changes, test_the_write_is_atomic):
        fn()
        print(f"  ok  {fn.__name__}")
    print("ambiguous queue checks passed")
