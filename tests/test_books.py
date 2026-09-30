"""Checks for the books page: the shelf walk stamps and clears the finish date,
the last shelf is a terminus, filters compose, and every computed var is read
at least once.

    ./.venv/bin/python test_books.py

Rows are named with a "zz-book-test" prefix and deleted at the end: the suite
shares one database and a leftover row has broken another page's test before.
"""
import datetime as dt
import pathlib
import sys

from sqlmodel import Session, select                     # noqa: E402

from ledger_app.pages.books import BookState, SHELVES          # noqa: E402
from ledger_app.core.models import Book                       # noqa: E402
from ledger_app.core.state import ENGINE                      # noqa: E402

PREFIX = "zz-book-test"
MADE: list[int] = []


def make(**kw) -> int:
    kw.setdefault("name", f"{PREFIX}-{len(MADE)}")
    with Session(ENGINE) as s:
        x = Book(**kw)
        s.add(x)
        s.commit()
        s.refresh(x)
    MADE.append(x.id)
    return x.id


def cleanup():
    with Session(ENGINE) as s:
        for bid in MADE:
            row = s.get(Book, bid)
            if row:
                s.delete(row)
        s.commit()
    MADE.clear()


def fresh() -> BookState:
    st = BookState(_reflex_internal_init=True)
    st.load()
    return st


def test_advance_walks_the_shelves_in_order():
    bid = make(shelf="want to buy")
    st = fresh()
    for expected in SHELVES[1:]:
        st.advance(bid)
        with Session(ENGINE) as s:
            assert s.get(Book, bid).shelf == expected, expected


def test_read_is_a_terminus_not_a_loop():
    bid = make(shelf="read")
    st = fresh()
    st.advance(bid)
    with Session(ENGINE) as s:
        assert s.get(Book, bid).shelf == "read", "read wrapped around"


def test_finishing_stamps_today_and_moving_back_clears_it():
    bid = make(shelf="reading")
    st = fresh()
    st.advance(bid)
    with Session(ENGINE) as s:
        assert s.get(Book, bid).finished_on == dt.date.today()
    st.edit_book(bid, "shelf", "want to read")
    with Session(ENGINE) as s:
        row = s.get(Book, bid)
        assert row.shelf == "want to read"
        assert row.finished_on is None, "finish date outlived the read state"


def test_duplicate_title_is_refused():
    make(name=f"{PREFIX}-dupe")
    st = fresh()
    st.new_name = f"{PREFIX}-dupe"
    st.add_book()
    with Session(ENGINE) as s:
        n = len(s.exec(select(Book).where(Book.name == f"{PREFIX}-dupe")).all())
    assert n == 1, f"{n} rows with the same title"
    assert "already" in st.notice


def test_rating_rejects_out_of_range():
    """1-10, through core/inline.py like every table. This was
    1-5 via edit_book; 9 is valid now, so the out-of-range case is 11."""
    bid = make()
    st = fresh()
    st.set_inline(bid, "rating", "11")
    with Session(ENGINE) as s:
        assert s.get(Book, bid).rating is None
    st.set_inline(bid, "rating", "9")
    with Session(ENGINE) as s:
        assert s.get(Book, bid).rating == 9


def test_filters_narrow_and_compose():
    make(name=f"{PREFIX}-a", shelf="read", kind="baking")
    make(name=f"{PREFIX}-b", shelf="read", kind="drinks")
    make(name=f"{PREFIX}-c", shelf="want to buy", kind="baking")
    st = fresh()
    st.set_shelf_filter("read")
    names = {r.name for r in st.rows}
    assert f"{PREFIX}-c" not in names
    st.set_kind_filter("baking")
    names = {r.name for r in st.rows}
    assert f"{PREFIX}-a" in names and f"{PREFIX}-b" not in names
    st.clear_filters()
    assert {f"{PREFIX}-a", f"{PREFIX}-b", f"{PREFIX}-c"} <= {r.name for r in st.rows}


def test_remove_is_a_tombstone():
    bid = make()
    st = fresh()
    st.remove(bid)
    with Session(ENGINE) as s:
        assert s.get(Book, bid).dismissed, "row was hard deleted"
    st.load()
    assert bid not in [r.id for r in st.rows]


def test_every_computed_var_evaluates():
    """Building the page does not evaluate a single @rx.var; only reading them
    does, and a broken one otherwise surfaces in the browser."""
    make(shelf="want to read", kind="art", rating=5)
    st = fresh()
    for n in ("rows", "summary", "shelf_rows", "kind_rows", "kind_options",
              "shelf_options", "unread_count"):
        getattr(st, n)
    assert len(st.shelf_rows) == len(SHELVES), "a shelf chip went missing"
    assert st.unread_count >= 1


if __name__ == "__main__":
    try:
        for fn in (test_advance_walks_the_shelves_in_order,
                   test_read_is_a_terminus_not_a_loop,
                   test_finishing_stamps_today_and_moving_back_clears_it,
                   test_duplicate_title_is_refused,
                   test_rating_rejects_out_of_range,
                   test_filters_narrow_and_compose,
                   test_remove_is_a_tombstone,
                   test_every_computed_var_evaluates):
            fn()
            print(f"  ok  {fn.__name__}")
        print("book checks passed")
    finally:
        cleanup()
