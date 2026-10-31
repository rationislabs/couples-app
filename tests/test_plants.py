"""Checks for the plant tracker: due dates count correctly, the light-fit test
catches a plant in too dark a room, and watering clears the overdue state.

    ./.venv/bin/python test_plants.py
"""
import datetime as dt
import pathlib
import sys

from sqlmodel import Session, select                       # noqa: E402

import _db  # first: never the real hearth.db
_db.migrate()

from hearth.core.models import Plant                        # noqa: E402
from hearth.pages.plants import PlantState                   # noqa: E402
from hearth.core.state import ENGINE                        # noqa: E402

TODAY = dt.date.today()
MADE: list[int] = []


def make(**kw) -> int:
    with Session(ENGINE) as s:
        p = Plant(**kw)
        s.add(p)
        s.commit()
        s.refresh(p)
    MADE.append(p.id)
    return p.id


def cleanup():
    with Session(ENGINE) as s:
        for pid in MADE:
            row = s.get(Plant, pid)
            if row:
                s.delete(row)
        s.commit()
    MADE.clear()


def fresh() -> PlantState:
    st = PlantState(_reflex_internal_init=True)
    st.show = "all"
    st.load()
    return st


def row_for(st: PlantState, pid: int):
    return next(r for r in st.rows if r.id == pid)


def test_due_counts_forward_and_backward():
    late = make(name="zz-test-late", water_days=7,
                last_watered=TODAY - dt.timedelta(days=10))
    today = make(name="zz-test-today", water_days=7,
                 last_watered=TODAY - dt.timedelta(days=7))
    soon = make(name="zz-test-soon", water_days=7,
                last_watered=TODAY - dt.timedelta(days=2))
    none = make(name="zz-test-none")
    st = fresh()
    assert row_for(st, late).due == "overdue by 3d", row_for(st, late).due
    assert row_for(st, late).overdue
    assert row_for(st, today).due == "today"
    assert row_for(st, today).overdue, "due today must count as needing water"
    assert row_for(st, soon).due == "in 5d"
    assert not row_for(st, soon).overdue
    assert row_for(st, none).due == "no schedule", \
        "a plant with no interval must not look urgent"


def test_an_interval_never_watered_is_due_now():
    pid = make(name="zz-test-never", water_days=7)
    r = row_for(fresh(), pid)
    assert r.overdue and r.due == "never watered — water now", r.due


def test_light_fit_flags_a_dark_room():
    dark = make(name="zz-test-dark", room="bathroom",
                light_need="bright direct")          # bathroom is low
    ok = make(name="zz-test-ok", room="balcony",
              light_need="bright direct")            # balcony is bright direct
    fine = make(name="zz-test-fine", room="bedroom", light_need="medium")
    st = fresh()
    assert "too dark" in row_for(st, dark).fit, row_for(st, dark).fit
    assert row_for(st, ok).fit == "", row_for(st, ok).fit
    assert row_for(st, fine).fit == "", row_for(st, fine).fit


def test_watering_clears_overdue_and_counts():
    pid = make(name="zz-test-water", water_days=5,
               last_watered=TODAY - dt.timedelta(days=9))
    st = fresh()
    assert row_for(st, pid).overdue
    st.watered(pid)
    st.show = "all"
    st.load()
    assert row_for(st, pid).due == "in 5d", row_for(st, pid).due
    assert not row_for(st, pid).overdue
    with Session(ENGINE) as s:
        assert s.get(Plant, pid).watered_count == 1


def test_wishlist_is_separate_and_acquirable():
    pid = make(name="zz-test-want", wishlist=True, light_need="medium")
    st = PlantState(_reflex_internal_init=True)
    st.show = "owned"
    st.load()
    assert pid not in [r.id for r in st.rows], "wishlist leaked into owned"
    st.show = "wishlist"
    st.load()
    assert pid in [r.id for r in st.rows]
    assert row_for(st, pid).due == "", "a wishlist plant cannot be overdue"
    st.acquire(pid)
    with Session(ENGINE) as s:
        row = s.get(Plant, pid)
        assert not row.wishlist and row.acquired_on == TODAY


def test_water_all_due_only_touches_what_is_due():
    late = make(name="zz-test-bulk-late", water_days=3,
                last_watered=TODAY - dt.timedelta(days=9))
    early = make(name="zz-test-bulk-early", water_days=30,
                 last_watered=TODAY - dt.timedelta(days=1))
    st = fresh()
    st.water_all_due()
    with Session(ENGINE) as s:
        assert s.get(Plant, late).last_watered == TODAY
        assert s.get(Plant, early).last_watered == TODAY - dt.timedelta(days=1), \
            "watered a plant that was not due"


def test_health_reads_from_the_facts_already_known():
    """add health status to plant tracker". Derived, so it
    cannot drift out of date the way a stored column would."""
    from hearth.pages.plants import _health
    assert _health({"wishlist": True, "due_days": -99, "fit": "x"}) == ""
    assert _health({"wishlist": False, "due_days": -30, "fit": ""}) == "parched"
    assert _health({"wishlist": False, "due_days": -2, "fit": ""}) == "thirsty"
    # Thirst outranks light: one of them is fixable this minute.
    assert _health({"wishlist": False, "due_days": -2, "fit": "too dark"}) == "thirsty"
    assert _health({"wishlist": False, "due_days": 3, "fit": "too dark"}) == "wrong light"
    assert _health({"wishlist": False, "due_days": 3, "fit": ""}) == "thriving"
    assert _health({"wishlist": False, "due_days": None, "fit": ""}) == "thriving"


def test_a_human_override_beats_every_derived_signal():
    """Nothing derivable knows what the leaves look like, so the override wins
    outright rather than being blended in."""
    from hearth.pages.plants import _health
    r = {"wishlist": False, "due_days": -30, "fit": "too dark",
         "health_override": "sick"}
    assert _health(r) == "sick"
    r["health_override"] = ""
    assert _health(r) == "parched", "clearing the override must restore the derived one"
    # A wishlist plant has no health at all, override or not.
    assert _health({"wishlist": True, "due_days": -30, "fit": "",
                    "health_override": "dying"}) == ""


if __name__ == "__main__":
    try:
        for fn in (test_due_counts_forward_and_backward,
                   test_an_interval_never_watered_is_due_now,
                   test_light_fit_flags_a_dark_room,
                   test_watering_clears_overdue_and_counts,
                   test_wishlist_is_separate_and_acquirable,
                   test_water_all_due_only_touches_what_is_due,
                   test_health_reads_from_the_facts_already_known,
                   test_a_human_override_beats_every_derived_signal):
            fn()
            print(f"  ok  {fn.__name__}")
        print("plant checks passed")
    finally:
        cleanup()
