"""Checks for two-person verdicts.

The point of the table is that "no opinion recorded" and "either way" are
different answers, and that one person's answer is not the other's. Both are
easy to lose in a control that only toggles, so both are asserted here.

    ./.venv/bin/python test_verdicts.py
"""
import os
import pathlib
import sys

os.environ["LEDGER_PEOPLE"] = "alex,sam"   # before verdicts reads it

from sqlmodel import Session, select                       # noqa: E402

from ledger_app.core import verdicts as V                       # noqa: E402
from ledger_app.core.models import Verdict                      # noqa: E402
from ledger_app.core.state import ENGINE                        # noqa: E402

# Tests share one database, so this kind is unique to this file.
KIND = "test-verdict-kind"
ROW = 424242


def cleanup():
    with Session(ENGINE) as s:
        for v in s.exec(select(Verdict).where(Verdict.kind == KIND)).all():
            s.delete(v)
        s.commit()


def held():
    return V.read(KIND, [ROW])[ROW]


def test_nothing_recorded_is_not_the_same_as_either_way():
    assert held() == {}, "test kind was not clean"
    V.write(KIND, ROW, "alex", V.MID)
    assert held() == {"alex": "mid"}
    assert V.summarise({}) == "", "no opinion must render as nothing"
    assert V.summarise({"alex": "mid"}) != ""


def test_each_person_holds_their_own_answer():
    V.write(KIND, ROW, "alex", V.UP)
    V.write(KIND, ROW, "sam", V.DOWN)
    assert held() == {"alex": "up", "sam": "down"}


def test_clicking_the_held_value_clears_it():
    V.write(KIND, ROW, "alex", V.UP)
    assert held()["alex"] == "up"
    V.write(KIND, ROW, "alex", V.UP)
    assert "alex" not in held(), "a second click must clear, not stick"


def test_both_yes_is_the_only_thing_that_counts_as_agreement():
    V.write(KIND, ROW, "alex", V.UP)
    V.write(KIND, ROW, "sam", V.UP)
    assert V.agreed(held()) is True
    assert V.summarise(held()) == "both yes"
    V.write(KIND, ROW, "sam", V.MID)
    assert V.agreed(held()) is False


def test_an_unknown_person_or_value_is_refused():
    before = held()
    V.write(KIND, ROW, "someone-else", V.UP)
    V.write(KIND, ROW, "alex", "sideways")
    assert held() == before, "write accepted something outside its vocabulary"


def test_read_of_an_empty_page_is_not_a_query():
    assert V.read(KIND, []) == {}


def test_every_voting_table_filters_by_vote_and_by_done():
    """Library, recipes, games and places, in memory: rows and verdicts are set
    on the state, nothing is written."""
    import reflex as rx
    from ledger_app.core.state import LedgerState
    from ledger_app.pages.dates import DateState
    from ledger_app.pages.games import GameState
    from ledger_app.pages.recipes import RecipeState
    root = rx.State(_reflex_internal_init=True)
    sub = lambda S: root.get_substate(S.get_full_name().split(".")[1:])
    votes = {"1": {"alex": V.UP}, "2": {"sam": V.DOWN}}

    g = sub(GameState)
    g._games = [{"id": i, "kind": "", "remote": False, "played": int(i == 3)}
                for i in (1, 2, 3)]
    g._verdicts = votes
    ids = lambda: [r["id"] for r in g._matches()]
    g.set_unvoted("alex");  assert ids() == [2, 3]
    g.set_tried("yes");      assert ids() == [3]
    g.set_unvoted("alex");  g.set_tried("yes")

    r = sub(RecipeState)
    r._recipes = [{"id": i, "name": f"r{i}", "tags": "", "tag_list": [], "cooked": int(i == 1)}
                  for i in (1, 2, 3)]
    r._verdicts = votes
    ids = lambda: [x["id"] for x in r.rows]
    r.set_unvoted("sam");  assert ids() == [1, 3]
    r.set_tried("yes");      assert ids() == [1]
    r.set_tried("no");       assert ids() == [3]
    r.set_unvoted("sam");  r.set_tried("no")

    d = sub(DateState)
    d._places = [{"id": i, "name": f"p{i}", "list": "", "country": "AT", "url": "",
                  "tag_list": [], "visited": i == 2, "km": None, "city": ""}
                 for i in (1, 2, 3)]
    d._log, d._verdicts = [], votes
    ids = lambda: [x["id"] for x in d._matches()]
    d.set_tried("no");       assert ids() == [1, 3]
    d.set_unvoted("alex");  assert ids() == [3]
    d.set_tried("no");       d.set_unvoted("alex")

    lib = sub(LedgerState)
    lib._rows = [{"id": 10**9 + i, "name": f"t{i}", "watch_state": s}
                 for i, s in enumerate(("watched", "watching", "unwatched"))]
    lib.set_tried("watching")
    assert [x["watch_state"] for x in lib._matches()] == ["watching"]
    lib.clear_filters()
    assert len(lib._matches()) == 3

if __name__ == "__main__":
    cleanup()
    try:
        for fn in (test_nothing_recorded_is_not_the_same_as_either_way,
                   test_each_person_holds_their_own_answer,
                   test_clicking_the_held_value_clears_it,
                   test_both_yes_is_the_only_thing_that_counts_as_agreement,
                   test_an_unknown_person_or_value_is_refused,
                   test_read_of_an_empty_page_is_not_a_query,
                   test_every_voting_table_filters_by_vote_and_by_done):
            cleanup()
            fn()
            print(f"  ok  {fn.__name__}")
        print("verdict checks passed")
    finally:
        cleanup()
