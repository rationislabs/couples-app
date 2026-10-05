"""Checks for the per-browser profile.

The server cannot tell the two people apart (one tailnet identity can cover
both phones), so the browser says who is holding it. Anything but "1" or "2"
must mean nobody, never a third person.

    ledger_app/.venv/bin/python tests/test_profile.py
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import _db  # noqa: E402
_db.migrate()

import reflex as rx                                         # noqa: E402

from ledger_app.core import household as H                      # noqa: E402
from ledger_app.core.profile import ProfileState                # noqa: E402

H.set_names("Alex", "Sam")


def profile():
    root = rx.State(_reflex_internal_init=True)
    return root.get_substate(ProfileState.get_full_name().split(".")[1:])


def test_load_reads_names_and_initials():
    p = profile()
    p.load()
    assert p.names == {"1": "Alex", "2": "Sam"}
    assert p.initials == {"1": "A", "2": "S"}


def test_stale_profile_is_nobody():
    p = profile()
    for stale in ("alex", "3", "0"):
        p.me = stale
        p.load()
        assert p.me == "", f"{stale!r} survived load"


async def test_a_vote_without_the_matching_profile_is_refused():
    """The buttons are disabled for the other person, but the handler must not
    trust that: a vote counts only for the person this browser selected."""
    from ledger_app.core import verdicts as V
    from ledger_app.pages.games import GameState
    root = rx.State(_reflex_internal_init=True)
    p = root.get_substate(ProfileState.get_full_name().split(".")[1:])
    g = root.get_substate(GameState.get_full_name().split(".")[1:])
    kind, row = "test-profile-kind", 777
    p.me = ""
    assert await V.write_as(g, kind, row, "1", V.UP) is False
    p.me = "2"
    assert await V.write_as(g, kind, row, "1", V.UP) is False
    assert V.read(kind, [row])[row] == {}
    p.me = "1"
    assert await V.write_as(g, kind, row, "1", V.UP) is True
    assert V.read(kind, [row])[row] == {"1": "up"}


def test_pick_accepts_only_a_slot():
    p = profile()
    p.pick("2")
    assert p.me == "2"
    p.pick("someone")
    assert p.me == "2"


if __name__ == "__main__":
    import asyncio
    for fn in (test_load_reads_names_and_initials, test_stale_profile_is_nobody,
               test_a_vote_without_the_matching_profile_is_refused,
               test_pick_accepts_only_a_slot):
        result = fn()
        if asyncio.iscoroutine(result):
            asyncio.run(result)
        print(f"  ok  {fn.__name__}")
    print("profile checks passed")
