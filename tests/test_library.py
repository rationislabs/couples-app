"""Checks for the Library's TMDB queue: picking a candidate by hand writes it,
through tmdb_fill's own writer, to the title.

    ./.venv/bin/python test_library.py

Rows are named with a "zz-lib-test" prefix and deleted at the end.
"""
from sqlmodel import Session, select                     # noqa: E402

import _db  # first: never the real ledger.db
_db.migrate()

from ledger_app.core.models import Title, TitleGenre          # noqa: E402
from ledger_app.core.state import ENGINE, LedgerState         # noqa: E402

NAME = "zz-lib-test-dune"


def cleanup():
    with Session(ENGINE) as s:
        for t in s.exec(select(Title).where(Title.name == NAME)).all():
            for tg in s.exec(select(TitleGenre).where(TitleGenre.title_id == t.id)).all():
                s.delete(tg)
            s.flush()                    # links first: no ORM relationship orders them
            s.delete(t)
        s.commit()


def test_a_hand_pick_fills_the_title():
    with Session(ENGINE) as s:
        s.add(Title(name=NAME, medium="movie"))
        s.commit()
    st = LedgerState(_reflex_internal_init=True)
    st._ambig = {NAME: {"medium": "movie", "why": "two matches", "candidates": [
        {"title": "Dune", "orig": "", "year": "2021", "kind": "movie",
         "overview": "A desert planet.", "genres": ["Science Fiction"], "votes": 1}]}}
    st.amb_index = 0
    st.amb_pick(0)                       # raised ModuleNotFoundError: tmdb_fill
    with Session(ENGINE) as s:
        t = s.exec(select(Title).where(Title.name == NAME)).one()
        assert t.description == "A desert planet." and t.year == 2021, (t.description, t.year)


if __name__ == "__main__":
    try:
        for fn in (test_a_hand_pick_fills_the_title,):
            fn()
            print(f"  ok  {fn.__name__}")
        print("library checks passed")
    finally:
        cleanup()
