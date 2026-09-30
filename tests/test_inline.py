"""Checks for core/inline.py — rating and notes, in place, on every table.

    ledger_app/.venv/bin/python tests/test_inline.py

One save path serves ten tables, so a regression here is a regression
everywhere. Rows are created with a zz-inline- prefix and deleted by id in a
finally, never by kind or table: an earlier cleanup scoped by kind deleted real
verdicts along with its own.
"""
import sys

from sqlmodel import Session, select

from ledger_app.core import inline as IN
from ledger_app.core.models import Game, Shop, Title, WatchState
from ledger_app.core.state import ENGINE, LedgerState

made: list = []


def make(model, **kw):
    with Session(ENGINE) as s:
        row = model(**kw)
        s.add(row)
        s.commit()
        s.refresh(row)
        made.append((model, row.id))
        return row.id


def get(model, rid):
    with Session(ENGINE) as s:
        return s.get(model, rid)


def test_rating_is_one_to_ten_and_bad_values_write_nothing():
    sid = make(Shop, name="zz-inline-shop", rating=3)
    for bad in ("0", "11", "x", "-1", "5.5"):
        assert IN.save(Shop, sid, "rating", bad).startswith("a rating is"), bad
        assert get(Shop, sid).rating == 3, f"{bad!r} overwrote a good value"
    assert IN.save(Shop, sid, "rating", "10") == "rated 10/10"
    assert get(Shop, sid).rating == 10
    assert IN.save(Shop, sid, "rating", "") == "rating cleared"
    assert get(Shop, sid).rating is None


def test_an_unchanged_value_is_not_a_write():
    """on_blur fires whenever focus leaves the cell, including tabbing through."""
    sid = make(Shop, name="zz-inline-same", rating=7)
    assert IN.save(Shop, sid, "rating", "7") == ""
    assert IN.save(Shop, sid, "rating", " 7 ") == ""


def test_note_and_notes_resolve_to_whichever_column_exists():
    gid = make(Game, name="zz-inline-game")
    assert IN.notes_attr(Game) == "note" and IN.notes_attr(Shop) == "notes"
    assert IN.save(Game, gid, "notes", "  phone only  ") == "note saved"
    assert get(Game, gid).note == "phone only"
    long = "x" * (IN.NOTES_MAX + 50)
    IN.save(Game, gid, "notes", long)
    assert len(get(Game, gid).note) == IN.NOTES_MAX


def test_a_missing_row_or_unknown_field_does_nothing():
    assert IN.save(Shop, 10**9, "rating", "5") == ""
    sid = make(Shop, name="zz-inline-field")
    assert IN.save(Shop, sid, "name", "hijacked") == ""
    assert get(Shop, sid).name == "zz-inline-field"


def test_bump_episode_writes_once_and_does_not_raise():
    """It called self._load(), the module-level row loader, not a method — an
    AttributeError on every click since the first commit, raised after the
    write, so each click added an episode and then showed an error."""
    tid = make(Title, name="zz-inline-title", medium="tv")
    st = LedgerState(_reflex_internal_init=True)
    st.bump_episode("zz-inline-title")
    st.bump_episode("zz-inline-title")
    with Session(ENGINE) as s:
        w = s.exec(select(WatchState).where(WatchState.title_id == tid)).one()
        made.append((WatchState, w.id))
        assert (w.current_episode, w.episodes_played) == (2, 2)
    assert st.notice == "zz-inline-title → E2"


if __name__ == "__main__":
    fns = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    try:
        for fn in fns:
            fn()
            print(f"  ok  {fn.__name__}")
    finally:
        with Session(ENGINE) as s:
            for model, rid in reversed(made):
                row = s.get(model, rid)
                if row is not None:
                    s.delete(row)
            s.commit()
    print("inline checks passed")
    sys.exit(0)
