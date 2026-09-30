"""Checks for the shopping page: URLs are normalised, filters compose, rating
validation rejects nonsense, and removal is a tombstone.

    ./.venv/bin/python test_shops.py
"""
import datetime as dt
import pathlib
import sys

from sqlmodel import Session, select                     # noqa: E402

from ledger_app.core.models import Shop                       # noqa: E402
from ledger_app.pages.shops import ShopState                   # noqa: E402
from ledger_app.core.state import ENGINE                      # noqa: E402

MADE: list[int] = []


def make(**kw) -> int:
    with Session(ENGINE) as s:
        x = Shop(**kw)
        s.add(x)
        s.commit()
        s.refresh(x)
    MADE.append(x.id)
    return x.id


def cleanup():
    with Session(ENGINE) as s:
        for sid in MADE:
            row = s.get(Shop, sid)
            if row:
                s.delete(row)
        s.commit()
    MADE.clear()


def fresh() -> ShopState:
    st = ShopState(_reflex_internal_init=True)
    st.load()
    return st


def test_bare_domain_becomes_a_url():
    st = fresh()
    st.new_name = "zz-test-bare"
    st.new_url = "example.com/shop"
    st.add_shop()
    with Session(ENGINE) as s:
        row = s.exec(select(Shop).where(Shop.name == "zz-test-bare")).first()
        MADE.append(row.id)
        assert row.url == "https://example.com/shop", row.url


def test_duplicate_name_is_refused():
    make(name="zz-test-dupe")
    st = fresh()
    st.new_name = "zz-test-dupe"
    st.add_shop()
    assert "already saved" in st.notice, st.notice
    with Session(ENGINE) as s:
        n = len(s.exec(select(Shop).where(Shop.name == "zz-test-dupe")).all())
    assert n == 1, f"added a second row for the same name ({n})"


def test_rating_rejects_out_of_range():
    """1-10, through core/inline.py like every table. This was
    1-5 via edit_shop; 9 is valid now, so the out-of-range case is 11."""
    sid = make(name="zz-test-rating", rating=3)
    st = fresh()
    st.set_inline(sid, "rating", "11")
    assert "1 to 10" in st.notice
    with Session(ENGINE) as s:
        assert s.get(Shop, sid).rating == 3, "a bad value overwrote a good one"
    st.set_inline(sid, "rating", "9")
    with Session(ENGINE) as s:
        assert s.get(Shop, sid).rating == 9


def test_filters_narrow_and_compose():
    """Scoped to its own prefix. Every test shares one database, so matching on
    the generic zz-test- prefix picked up a row another test had left at five
    stars and failed for a reason that had nothing to do with filtering."""
    make(name="zzf-a", kind="clothing", rating=5, price_band="premium",
         ships_here=True, good_for="good linen")
    make(name="zzf-b", kind="clothing", rating=2, price_band="budget",
         ships_here=False)
    make(name="zzf-c", kind="plants", rating=5, price_band="mid",
         ships_here=True)
    st = fresh()
    ours = lambda: sorted(r.name for r in st.rows if r.name.startswith("zzf-"))

    st.kind_filter = "clothing"
    assert ours() == ["zzf-a", "zzf-b"], ours()
    st.min_rating = 5
    assert ours() == ["zzf-a"], ours()
    st.kind_filter = ""
    assert ours() == ["zzf-a", "zzf-c"], ours()
    st.min_rating = 0
    st.ships_only = True
    assert "zzf-b" not in ours(), "a shop that does not ship slipped through"
    st.ships_only = False
    st.search = "linen"
    assert ours() == ["zzf-a"], "search must look in the good_for note"
    st.clear_filters()
    assert len(ours()) == 3


def test_ordered_stamps_today_and_counts():
    sid = make(name="zz-test-order")
    st = fresh()
    st.ordered(sid)
    st.ordered(sid)
    with Session(ENGINE) as s:
        row = s.get(Shop, sid)
        assert row.order_count == 2
        assert row.last_ordered == dt.date.today()


def test_remove_is_a_tombstone():
    sid = make(name="zz-test-gone")
    st = fresh()
    st.remove(sid)
    with Session(ENGINE) as s:
        assert s.get(Shop, sid).dismissed, "row was hard deleted"
    st.load()
    assert sid not in [r.id for r in st.rows]


def test_never_ordered_filter_selects_only_unordered_shops():
    """update shopping table to include ones not ordered
    from yet to distinguish". An empty Orders cell read as missing data."""
    from ledger_app.pages.shops import ShopState
    st = ShopState(_reflex_internal_init=True)
    st.load()
    st.unordered_only = True
    for r in st.rows:
        assert r.never_ordered, f"{r.name} has orders but passed the filter"
        assert r.order_count == ""
    st.unordered_only = False
    assert len(st.rows) >= len([r for r in st.rows if r.never_ordered])


if __name__ == "__main__":
    try:
        for fn in (test_bare_domain_becomes_a_url, test_duplicate_name_is_refused,
                   test_rating_rejects_out_of_range, test_filters_narrow_and_compose,
                   test_ordered_stamps_today_and_counts, test_remove_is_a_tombstone,
                   test_never_ordered_filter_selects_only_unordered_shops):
            fn()
            print(f"  ok  {fn.__name__}")
        print("shop checks passed")
    finally:
        cleanup()
