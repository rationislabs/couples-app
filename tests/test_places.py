"""One check for the mood picker: country scoping, multi-select types, and
visited exclusion all actually narrow the pool.

    ./.venv/bin/python test_places.py
"""
import pathlib
import sys

from sqlmodel import Session, select                        # noqa: E402

import _db  # first: never the real ledger.db
_db.migrate()

from ledger_app.core.models import Place                         # noqa: E402
from ledger_app.core.place_types import GROUPS, TYPES, classify  # noqa: E402
from ledger_app.core.state import ENGINE                         # noqa: E402

ANYWHERE = "anywhere"


def seed() -> list[int]:
    """Two types in one country and a third elsewhere, so every check has rows
    to narrow on an empty database. Returns the ids, for cleanup by id."""
    with Session(ENGINE) as s:
        made = [Place(name=f"zz-place-test {tag}", country=c, tags=tag,
                      maps_url="https://example.com/")
                for c, tag in (("FR", "restaurant"), ("FR", "cafe"), ("DE", "park"))]
        s.add_all(made)
        s.commit()
        return [p.id for p in made]


def unseed(ids: list[int]) -> None:
    with Session(ENGINE) as s:
        for i in ids:
            s.delete(s.get(Place, i))
        s.commit()


def places():
    with Session(ENGINE) as s:
        return [{"name": p.name, "country": p.country, "url": p.maps_url,
                 "visited": p.visited,
                 "tag_list": [t for t in p.tags.split(",") if t]}
                for p in s.exec(select(Place)).all() if not p.dismissed]


def pool(rows, country="FR", types=(), been=frozenset()):
    """Mirrors DateState.unvisited."""
    return [p for p in rows
            if p["name"] not in been and not p["visited"] and p["url"]
            and (country == ANYWHERE or p["country"] == country)
            and (not types or any(t in types for t in p["tag_list"]))]


def test_taxonomy_is_self_consistent():
    assert len(TYPES) == len(set(TYPES)), "duplicate type across groups"
    for g, ts in GROUPS.items():
        assert ts, f"empty group {g}"
    with Session(ENGINE) as s:
        for p in s.exec(select(Place)).all():
            for t in [x for x in p.tags.split(",") if x]:
                assert t in TYPES, f"{p.name} carries unknown type {t}"


def test_country_scoping_narrows():
    rows = places()
    everywhere = pool(rows, country=ANYWHERE)
    fr = pool(rows, country="FR")
    assert fr, "no pickable places in FR"
    assert len(fr) < len(everywhere), "country scope did not narrow anything"
    assert {p["country"] for p in fr} == {"FR"}


def test_types_multi_select_is_a_union():
    rows = places()
    only_rest = pool(rows, types=("restaurant",))
    only_cafe = pool(rows, types=("cafe",))
    both = pool(rows, types=("restaurant", "cafe"))
    assert only_rest and only_cafe, "expected both types present in FR"
    # union, not intersection: adding a type can only widen the pool
    assert len(both) >= max(len(only_rest), len(only_cafe))
    assert len(both) <= len(only_rest) + len(only_cafe)
    names = {p["name"] for p in both}
    assert {p["name"] for p in only_rest} <= names
    assert {p["name"] for p in only_cafe} <= names


def test_group_selection_covers_its_types():
    rows = places()
    for g, ts in GROUPS.items():
        whole = {p["name"] for p in pool(rows, country=ANYWHERE, types=tuple(ts))}
        for t in ts:
            assert {p["name"] for p in
                    pool(rows, country=ANYWHERE, types=(t,))} <= whole


def test_visited_is_excluded():
    rows = places()
    before = pool(rows, country=ANYWHERE)
    assert before, "nothing pickable at all"
    target = before[0]["name"]
    after = pool(rows, country=ANYWHERE, been={target})
    assert target not in {p["name"] for p in after}
    assert len(after) == len(before) - 1
    # the visited flag does the same job as the date log
    flagged = [dict(p, visited=p["name"] == target) for p in rows]
    assert target not in {p["name"] for p in pool(flagged, country=ANYWHERE)}


def test_classifier_is_stable_and_known():
    for name, want in (("Blue Door Cafe", "cafe"),
                       ("Mario's Restaurant", "restaurant"),
                       ("Crystal Cave", "cave"),
                       ("City Park", "park"),
                       ("Vintage & Second Hand", "vintage")):
        got = classify(name)
        assert want in got, f"{name} -> {got}, wanted {want}"
        assert all(t in TYPES for t in got)


if __name__ == "__main__":
    ids = seed()
    try:
        for fn in (test_taxonomy_is_self_consistent, test_country_scoping_narrows,
                   test_types_multi_select_is_a_union,
                   test_group_selection_covers_its_types,
                   test_visited_is_excluded, test_classifier_is_stable_and_known):
            fn()
            print(f"  ok  {fn.__name__}")
    finally:
        unseed(ids)
    print("place checks passed")
