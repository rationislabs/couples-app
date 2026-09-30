"""Checks for the Tonight page: the deal respects mood and distance, and each
verb writes to the same table its own page uses.

    ./.venv/bin/python test_home.py
"""
import datetime as dt
import pathlib
import sys

from sqlmodel import Session, select                              # noqa: E402

from ledger_app.pages.home import HOME_AT, MOOD_TYPES, HomeState        # noqa: E402
from ledger_app.core.models import (ConvoQuestion, CookLog, DateEntry,  # noqa: E402
                               Place, WatchState)
from ledger_app.core.state import ENGINE                                # noqa: E402


def seed() -> list[tuple[type, int]]:
    """Places in two cities, one with no coordinates, and two tops so the
    outfit has something to change between. Enough for every check on an empty
    database. Returns (model, id) pairs, for cleanup by id."""
    from ledger_app.core.models import Garment
    lat, lon = HOME_AT
    rows = [Place(name="zz-home-test near", city="zz-city-a", tags="restaurant",
                  lat=lat, lon=lon, maps_url="https://example.com/"),
            Place(name="zz-home-test far", city="zz-city-b", tags="park",
                  lat=lat + 5, lon=lon, maps_url="https://example.com/"),
            Place(name="zz-home-test unplaced", city="zz-city-b", tags="cafe",
                  maps_url="https://example.com/"),
            Garment(name="zz-home-test top 1", slot="top"),
            Garment(name="zz-home-test top 2", slot="top"),
            Garment(name="zz-home-test bottom", slot="bottom")]
    with Session(ENGINE) as s:
        s.add_all(rows)
        s.commit()
        return [(type(r), r.id) for r in rows]


def unseed(made: list[tuple[type, int]]) -> None:
    with Session(ENGINE) as s:
        for model, i in made:
            s.delete(s.get(model, i))
        s.commit()


def fresh(**kw):
    st = HomeState(_reflex_internal_init=True)
    for k, v in kw.items():
        setattr(st, k, v)
    st.load()
    return st


def test_deals_every_card_always():
    """The order is asserted, not just the set: the view indexes cards[0] as the
    large one and cards[1:] as the row beneath, so a reordering silently moves
    the wrong thing into the hero slot."""
    st = fresh()
    kinds = [c.kind for c in st.cards]
    assert kinds == ["place", "cook", "ask", "play", "watch"], kinds
    for c in st.cards:
        assert c.title, f"{c.kind} card has no title"
        assert c.verb, f"{c.kind} card has no verb"


def test_mood_restricts_place_types():
    """A mood must only ever offer a place carrying one of its types."""
    for mood, wanted in MOOD_TYPES.items():
        if not wanted:
            continue
        st = fresh(mood=mood, near_only=False)
        place = st._place
        if not place:
            continue
        got = [t.strip() for t in place["types"].split(",")]
        assert any(t in wanted for t in got), f"{mood} offered {got}"


def test_nearby_only_bounds_distance():
    """A radius bounds the places whose distance is known.

    It used to bound the deal outright, which is the same sentence only if
    every place has coordinates. Many do not, so the two can differ by more
    than half the wishlist. A place with no
    location is now dealt and labelled rather than dropped.
    """
    st = fresh(mood="surprise us", near_only=True)
    km = st._place.get("km") if st._place else None
    if km and km != "distance unknown":
        assert int(km.split()[0]) <= 60, st._place


def test_deal_again_changes_the_seed():
    st = fresh()
    before = st.seed
    st.deal()
    assert st.seed == before + 1


def test_place_verb_writes_visit_and_log():
    st = fresh(mood="surprise us", near_only=False)
    place = dict(st._place)
    if not place:
        return
    with Session(ENGINE) as s:
        before = len(s.exec(select(DateEntry)).all())
    st.done("place")
    try:
        with Session(ENGINE) as s:
            p = s.get(Place, place["id"])
            assert p.visited, "place not marked visited"
            entries = s.exec(select(DateEntry)).all()
            assert len(entries) == before + 1
            mine = [e for e in entries if e.place_id == place["id"]]
            assert mine and mine[-1].went_on == dt.date.today()
    finally:                                    # leave the database as found
        with Session(ENGINE) as s:
            p = s.get(Place, place["id"])
            p.visited = False
            s.add(p)
            for e in s.exec(select(DateEntry)).all():
                if e.place_id == place["id"] and e.went_on == dt.date.today():
                    s.delete(e)
            s.commit()


def test_ask_verb_marks_the_question_asked():
    st = fresh()
    q = dict(st._question)
    if not q:
        return
    st.done("ask")
    try:
        with Session(ENGINE) as s:
            assert s.get(ConvoQuestion, q["id"]).asked
    finally:
        with Session(ENGINE) as s:
            row = s.get(ConvoQuestion, q["id"])
            row.asked = False
            s.add(row)
            s.commit()


def test_watch_verb_advances_one_episode():
    st = fresh()
    w = dict(st._watch)
    if not w:
        return
    with Session(ENGINE) as s:
        before = s.get(WatchState, w["id"]).current_episode or 0
    st.done("watch")
    try:
        with Session(ENGINE) as s:
            assert s.get(WatchState, w["id"]).current_episode == before + 1
    finally:
        with Session(ENGINE) as s:
            row = s.get(WatchState, w["id"])
            row.current_episode = before or None
            row.episodes_played = max(0, (row.episodes_played or 1) - 1)
            s.add(row)
            s.commit()


def test_cook_verb_logs_once():
    st = fresh()
    r = dict(st._recipe)
    if not r:
        return
    with Session(ENGINE) as s:
        before = len(s.exec(select(CookLog)).all())
    st.done("cook")
    try:
        with Session(ENGINE) as s:
            assert len(s.exec(select(CookLog)).all()) == before + 1
    finally:
        with Session(ENGINE) as s:
            logs = [c for c in s.exec(select(CookLog)).all()
                    if c.recipe_id == r["id"] and c.cooked_on == dt.date.today()]
            for c in logs:
                s.delete(c)
            s.commit()


def test_play_verb_increments_the_game():
    from ledger_app.core.models import Game
    st = fresh()
    g = dict(st._game)
    if not g:
        return
    with Session(ENGINE) as s:
        before = s.get(Game, g["id"]).played_count
    st.done("play")
    try:
        with Session(ENGINE) as s:
            assert s.get(Game, g["id"]).played_count == before + 1
    finally:
        with Session(ENGINE) as s:
            row = s.get(Game, g["id"])
            row.played_count = before
            s.add(row)
            s.commit()


# ---- nearby places -----------------------------------------
# The bug: home.py dropped every place with no coordinates when "near only" was
# on, so a distance filter silently hid most places instead of none of
# them. These assert the filter is honest about what it does not know.

def _home():
    from ledger_app.pages.home import HomeState
    st = HomeState(_reflex_internal_init=True)
    st.load()
    return st


def test_a_radius_excludes_places_with_no_coordinates():
    """This test previously asserted the opposite — that an unplaced place
    could still be dealt under a radius, on the grounds that unknown is not the
    same as far. In practice most places had no lat/lon and most were abroad,
    so "within 15 km" was offering other countries. A radius now means a
    radius; with no radius set, unknowns still deal.
    """
    from ledger_app.core.models import Place
    from ledger_app.core.state import ENGINE
    from sqlmodel import Session, select
    with Session(ENGINE) as s:
        unplaced = [p for p in s.exec(select(Place)).all()
                    if not p.dismissed and p.lat is None]
    assert unplaced, "no unplaced places left; this test has nothing to prove"
    unplaced_ids = {p.id for p in unplaced}

    st = _home()
    st.near_only, st.radius_km, st.mood = True, 5, "surprise us"
    seen = set()
    for _ in range(60):
        st.seed += 1
        st.load()
        if st._place:
            seen.add(st._place["id"])
    assert not (seen & unplaced_ids), \
        "a 5 km filter dealt a place with no coordinates"

    # ...and without a radius they are back, because unknown is still not far.
    st = _home()
    st.near_only, st.radius_km, st.mood = False, 0, "surprise us"
    seen = set()
    for _ in range(60):
        st.seed += 1
        st.load()
        if st._place:
            seen.add(st._place["id"])
    assert seen & unplaced_ids, "no radius set, but unplaced places were hidden"


def test_an_unplaced_place_says_so_rather_than_showing_blank():
    st = _home()
    st.radius_km = 0
    st.load()
    for _ in range(60):
        st.seed += 1
        st.load()
        if st._place and st._place["km"] == "distance unknown":
            return
    raise AssertionError("never dealt a place labelled 'distance unknown'")


def test_radius_label_is_always_one_of_the_options():
    from ledger_app.pages.home import RADII
    st = _home()
    for label in RADII:
        st.set_radius(label)
        assert st.radius_label in RADII, f"{label!r} round-trips to {st.radius_label!r}"


def test_city_filter_narrows_and_clears():
    st = _home()
    assert st.city_options[0] == "every city"
    assert len(st.city_options) > 1, "no cities to filter by"
    st.set_city(st.city_options[1])
    assert st.city != ""
    st.set_city("every city")
    assert st.city == ""


def test_an_outfit_is_one_garment_per_slot_at_most():
    """An empty slot is skipped, not faked — no coat
    in July is the right answer, not a missing card."""
    st = _home()
    slots = [g["slot"] for g in st.outfit]
    assert len(slots) == len(set(slots)), f"a slot was dealt twice: {slots}"
    assert set(slots) <= {"top", "bottom", "outer", "shoes", "accent"}


def test_the_outfit_respects_the_season():
    import datetime as _dt
    from ledger_app.core.models import Garment
    from ledger_app.core.state import ENGINE
    from sqlmodel import Session, select
    season = "warm" if 4 <= _dt.date.today().month <= 9 else "cold"
    with Session(ENGINE) as s:
        by_name = {g.name: g for g in s.exec(select(Garment)).all()}
    st = _home()
    for piece in st.outfit:
        g = by_name[piece["name"]]
        assert g.season in ("", season), f"{g.name} is {g.season} in {season}"


def test_dealing_again_can_change_the_outfit():
    st = _home()
    first = [g["name"] for g in st.outfit]
    seen = set()
    for _ in range(40):
        st.seed += 1
        st.load()
        seen.add(tuple(g["name"] for g in st.outfit))
    assert len(seen) > 1, f"outfit never changed across 40 deals: {first}"


if __name__ == "__main__":
    made = seed()
    try:
        for fn in (test_deals_every_card_always, test_mood_restricts_place_types,
                   test_nearby_only_bounds_distance, test_deal_again_changes_the_seed,
                   test_place_verb_writes_visit_and_log,
                   test_ask_verb_marks_the_question_asked,
                   test_watch_verb_advances_one_episode, test_cook_verb_logs_once,
                   test_play_verb_increments_the_game):
            fn()
            test_a_radius_excludes_places_with_no_coordinates()
        test_an_unplaced_place_says_so_rather_than_showing_blank()
        test_radius_label_is_always_one_of_the_options()
        test_city_filter_narrows_and_clears()
        print(f"  ok  {fn.__name__}")
        test_an_outfit_is_one_garment_per_slot_at_most()
        test_the_outfit_respects_the_season()
        test_dealing_again_can_change_the_outfit()
    finally:
        unseed(made)
    print("home checks passed")
