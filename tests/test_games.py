"""Checks for the games list: the Tonight deal respects the spicy flag, prefers
what you have played least, and both 'played' paths write the same counter.

    ./.venv/bin/python test_games.py
"""
import pathlib
import sys

from sqlmodel import Session, select              # noqa: E402

from ledger_app.pages.games import GameState            # noqa: E402
from ledger_app.pages.home import HomeState             # noqa: E402
from ledger_app.core.models import Game                # noqa: E402
from ledger_app.core.state import ENGINE               # noqa: E402


def seed() -> list[int]:
    """Two ordinary games and one spicy one, so every check has rows to work
    with on an empty database. Returns the ids, for cleanup by id."""
    with Session(ENGINE) as s:
        made = [Game(name=f"zz-game-test {i}", kind="board", spicy=i == 2)
                for i in range(3)]
        s.add_all(made)
        s.commit()
        return [g.id for g in made]


def unseed(ids: list[int]) -> None:
    with Session(ENGINE) as s:
        for i in ids:
            s.delete(s.get(Game, i))
        s.commit()


def games():
    with Session(ENGINE) as s:
        return [g for g in s.exec(select(Game)).all() if not g.dismissed]


def test_spicy_is_excluded_from_tonight_by_default():
    spicy = [g.name for g in games() if g.spicy]
    assert spicy, "expected at least one spicy game to test with"
    for _ in range(25):
        st = HomeState(_reflex_internal_init=True)
        st.include_spicy = False
        st.load()
        assert st._game.get("name") not in spicy, st._game


def test_spicy_can_be_opted_into():
    """Equalises play counts first. The deal prefers the least-played game, so a
    spicy game that happens to be ahead on plays is legitimately unreachable —
    an earlier version of this test asserted otherwise and failed for a correct
    reason, which is worse than not testing it."""
    spicy = [g for g in games() if g.spicy]
    if not spicy:
        return
    with Session(ENGINE) as s:
        before = {g.id: g.played_count for g in s.exec(select(Game)).all()}
        for g in s.exec(select(Game)).all():
            g.played_count = 0
            s.add(g)
        s.commit()
    try:
        seen = set()
        for i in range(60):
            st = HomeState(_reflex_internal_init=True)
            st.include_spicy = True
            st.seed = i
            st.load()
            if st._game:
                seen.add(st._game["name"])
        assert any(g.name in seen for g in spicy), seen
    finally:
        with Session(ENGINE) as s:
            for g in s.exec(select(Game)).all():
                g.played_count = before.get(g.id, 0)
                s.add(g)
            s.commit()


def test_deal_prefers_least_played():
    rows = games()
    if len(rows) < 2:
        return
    target = rows[0]
    with Session(ENGINE) as s:
        row = s.get(Game, target.id)
        before = row.played_count
        row.played_count = 999          # make it the most played by far
        s.add(row)
        s.commit()
    try:
        for i in range(25):
            st = HomeState(_reflex_internal_init=True)
            st.include_spicy = True
            st.seed = i
            st.load()
            assert st._game.get("name") != target.name, \
                "dealt the most-played game"
    finally:
        with Session(ENGINE) as s:
            row = s.get(Game, target.id)
            row.played_count = before
            s.add(row)
            s.commit()


def test_both_played_buttons_write_the_same_counter():
    target = games()[0]
    with Session(ENGINE) as s:
        before = s.get(Game, target.id).played_count

    gs = GameState(_reflex_internal_init=True)
    gs.load()
    gs.played(target.id)
    with Session(ENGINE) as s:
        mid = s.get(Game, target.id).played_count
    assert mid == before + 1, (before, mid)

    hs = HomeState(_reflex_internal_init=True)
    hs.include_spicy = True
    hs.load()
    hs._game = {"id": target.id, "name": target.name}
    hs.done("play")
    with Session(ENGINE) as s:
        after = s.get(Game, target.id).played_count
        row = s.get(Game, target.id)
        row.played_count = before        # leave the database as found
        s.add(row)
        s.commit()
    assert after == before + 2, (before, after)


def test_remove_is_a_tombstone_the_seed_cannot_undo():
    target = games()[-1]
    gs = GameState(_reflex_internal_init=True)
    gs.load()
    gs.remove(target.id)
    try:
        with Session(ENGINE) as s:
            assert s.get(Game, target.id).dismissed
        assert target.name not in [g.name for g in games()]
    finally:
        with Session(ENGINE) as s:
            row = s.get(Game, target.id)
            row.dismissed = False
            s.add(row)
            s.commit()


if __name__ == "__main__":
    ids = seed()
    try:
        for fn in (test_spicy_is_excluded_from_tonight_by_default,
                   test_spicy_can_be_opted_into,
                   test_deal_prefers_least_played,
                   test_both_played_buttons_write_the_same_counter,
                   test_remove_is_a_tombstone_the_seed_cannot_undo):
            fn()
            print(f"  ok  {fn.__name__}")
    finally:
        unseed(ids)
    print("game checks passed")
