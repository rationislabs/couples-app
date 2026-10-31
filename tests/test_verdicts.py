"""Checks for two-person verdicts.

The point of the table is that "no opinion recorded" and "either way" are
different answers, and that one person's answer is not the other's. Both are
easy to lose in a control that only toggles, so both are asserted here.
People are slots "1" and "2"; their names live in the user table.

    hearth/.venv/bin/python tests/test_verdicts.py
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import _db  # noqa: E402
_db.migrate()

from sqlmodel import Session, select                       # noqa: E402

from hearth.core import household as H                      # noqa: E402
from hearth.core import verdicts as V                       # noqa: E402
from hearth.core.models import Verdict                      # noqa: E402
from hearth.core.state import ENGINE                        # noqa: E402

KIND = "test-verdict-kind"
ROW = 424242
H.set_names("Alex", "Sam")
NAMES = H.names()


def cleanup():
    with Session(ENGINE) as s:
        for v in s.exec(select(Verdict).where(Verdict.kind == KIND)).all():
            s.delete(v)
        s.commit()


def held():
    return V.read(KIND, [ROW])[ROW]


def test_nothing_recorded_is_not_the_same_as_either_way():
    assert held() == {}, "test kind was not clean"
    V.write(KIND, ROW, "1", V.MID)
    assert held() == {"1": "mid"}
    assert V.summarise({}, NAMES) == "", "no opinion must render as nothing"
    assert V.summarise({"1": "mid"}, NAMES) != ""


def test_each_person_holds_their_own_answer():
    V.write(KIND, ROW, "1", V.UP)
    V.write(KIND, ROW, "2", V.DOWN)
    assert held() == {"1": "up", "2": "down"}


def test_clicking_the_held_value_clears_it():
    V.write(KIND, ROW, "1", V.UP)
    assert held()["1"] == "up"
    V.write(KIND, ROW, "1", V.UP)
    assert "1" not in held(), "a second click must clear, not stick"


def test_both_yes_is_the_only_thing_that_counts_as_agreement():
    V.write(KIND, ROW, "1", V.UP)
    V.write(KIND, ROW, "2", V.UP)
    assert V.agreed(held()) is True
    assert V.summarise(held(), NAMES) == "both yes"
    V.write(KIND, ROW, "2", V.MID)
    assert V.agreed(held()) is False


def test_an_unknown_person_or_value_is_refused():
    before = held()
    V.write(KIND, ROW, "someone-else", V.UP)
    V.write(KIND, ROW, "3", V.UP)
    V.write(KIND, ROW, "1", "sideways")
    assert held() == before, "write accepted something outside its vocabulary"


def test_read_of_an_empty_page_is_not_a_query():
    assert V.read(KIND, []) == {}


def test_every_voting_table_filters_by_vote_and_by_done():
    """Library, recipes, games and places, in memory: rows and verdicts are set
    on the state, nothing is written."""
    import reflex as rx
    from hearth.core.state import HearthState
    from hearth.pages.dates import DateState
    from hearth.pages.games import GameState
    from hearth.pages.recipes import RecipeState
    root = rx.State(_reflex_internal_init=True)
    sub = lambda S: root.get_substate(S.get_full_name().split(".")[1:])
    votes = {"1": {"1": V.UP}, "2": {"2": V.DOWN}}

    g = sub(GameState)
    g._games = [{"id": i, "kind": "", "remote": False, "played": int(i == 3)}
                for i in (1, 2, 3)]
    g._verdicts = votes
    ids = lambda: [r["id"] for r in g._matches()]
    g.set_unvoted("1");  assert ids() == [2, 3]
    g.set_tried("yes");      assert ids() == [3]
    g.set_unvoted("1");  g.set_tried("yes")

    r = sub(RecipeState)
    r._recipes = [{"id": i, "name": f"r{i}", "tags": "", "tag_list": [], "cooked": int(i == 1)}
                  for i in (1, 2, 3)]
    r._verdicts = votes
    ids = lambda: [x["id"] for x in r.rows]
    r.set_unvoted("2");  assert ids() == [1, 3]
    r.set_tried("yes");      assert ids() == [1]
    r.set_tried("no");       assert ids() == [3]
    r.set_unvoted("2");  r.set_tried("no")

    d = sub(DateState)
    d._places = [{"id": i, "name": f"p{i}", "list": "", "country": "AT", "url": "",
                  "tag_list": [], "visited": i == 2, "km": None, "city": ""}
                 for i in (1, 2, 3)]
    d._log, d._verdicts = [], votes
    ids = lambda: [x["id"] for x in d._matches()]
    d.set_tried("no");       assert ids() == [1, 3]
    d.set_unvoted("1");  assert ids() == [3]
    d.set_tried("no");       d.set_unvoted("1")

    lib = sub(HearthState)
    lib._rows = [{"id": 10**9 + i, "name": f"t{i}", "watch_state": s}
                 for i, s in enumerate(("watched", "watching", "unwatched"))]
    lib.set_tried("watching")
    assert [x["watch_state"] for x in lib._matches()] == ["watching"]
    lib.clear_filters()
    assert len(lib._matches()) == 3

def test_renaming_a_person_keeps_their_votes():
    V.write(KIND, ROW, "1", V.UP)
    H.set_names("Alexandra", "Sam")
    try:
        assert held() == {"1": "up"}
        assert V.summarise(held(), H.names()).startswith("A")
    finally:
        H.set_names("Alex", "Sam")


def test_a_second_tab_voting_at_the_same_moment_is_not_an_error():
    """Both tabs read "no vote yet", both insert: the unique index rejected the
    second with IntegrityError. The vote lands; the other tab's wins."""
    real = V.Session

    class Racing(real):
        raced = False

        def exec(self, stmt, *a, **k):
            res = super().exec(stmt, *a, **k)
            if Racing.raced or not hasattr(res, "first"):
                return res
            Racing.raced = True
            row = res.first()
            with real(ENGINE) as other:               # the other tab, in between
                other.add(Verdict(user_id=1, kind=KIND, row_id=ROW, value=V.DOWN))
                other.commit()

            class Done:
                def first(self_inner):
                    return row
            return Done()

    V.Session = Racing
    try:
        V.write(KIND, ROW, "1", V.UP)
    finally:
        V.Session = real
    assert held() == {"1": "up"}, held()


if __name__ == "__main__":
    cleanup()
    try:
        for fn in (test_nothing_recorded_is_not_the_same_as_either_way,
                   test_each_person_holds_their_own_answer,
                   test_clicking_the_held_value_clears_it,
                   test_both_yes_is_the_only_thing_that_counts_as_agreement,
                   test_an_unknown_person_or_value_is_refused,
                   test_read_of_an_empty_page_is_not_a_query,
                   test_renaming_a_person_keeps_their_votes,
                   test_every_voting_table_filters_by_vote_and_by_done,
                   test_a_second_tab_voting_at_the_same_moment_is_not_an_error):
            cleanup()
            fn()
            print(f"  ok  {fn.__name__}")
        print("verdict checks passed")
    finally:
        cleanup()
