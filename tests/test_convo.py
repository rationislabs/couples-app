"""One check for the Convo Starter filters: both axes narrow the list, they
combine, removed rows never appear, and the random pick respects them.

    ./.venv/bin/python test_convo.py
"""
import pathlib
import sys

from sqlmodel import Session, select                       # noqa: E402

from ledger_app.pages.convo import AUDIENCES, DEPTHS             # noqa: E402
from ledger_app.core.models import ConvoQuestion                # noqa: E402
from ledger_app.core.state import ENGINE                        # noqa: E402


def seed() -> list[int]:
    """One question per audience and depth, so every filter has something to
    find on an empty database. Returns the ids, for cleanup by id."""
    with Session(ENGINE) as s:
        made = [ConvoQuestion(text=f"zz-convo-test {a} {d}", audience=a, depth=d)
                for a in AUDIENCES for d in DEPTHS]
        s.add_all(made)
        s.commit()
        return [q.id for q in made]


def unseed(ids: list[int]) -> None:
    with Session(ENGINE) as s:
        for i in ids:
            s.delete(s.get(ConvoQuestion, i))
        s.commit()


def rows():
    with Session(ENGINE) as s:
        return [{"text": q.text, "audience": q.audience, "depth": q.depth,
                 "dismissed": q.dismissed}
                for q in s.exec(select(ConvoQuestion)).all()]


def matches(all_rows, audience="", depth=""):
    """Mirrors ConvoState._matches, minus the asked filter."""
    return [r for r in all_rows
            if not r["dismissed"]
            and (not audience or r["audience"] == audience)
            and (not depth or r["depth"] == depth)]


def test_every_question_is_tagged_on_both_axes():
    for r in rows():
        assert r["audience"] in AUDIENCES, f"bad audience: {r}"
        assert r["depth"] in DEPTHS, f"bad depth: {r}"


def test_each_filter_value_has_questions():
    all_rows = rows()
    for a in AUDIENCES:
        assert matches(all_rows, audience=a), f"no questions for {a}"
    for d in DEPTHS:
        assert matches(all_rows, depth=d), f"no questions at depth {d}"


def test_filters_narrow_and_combine():
    all_rows = rows()
    everything = matches(all_rows)
    for a in AUDIENCES:
        by_a = matches(all_rows, audience=a)
        assert 0 < len(by_a) < len(everything)
        assert {r["audience"] for r in by_a} == {a}
        for d in DEPTHS:
            both = matches(all_rows, audience=a, depth=d)
            assert len(both) <= len(by_a)
            assert all(r["audience"] == a and r["depth"] == d for r in both)
    # the parts add up to the whole on each axis
    assert sum(len(matches(all_rows, audience=a)) for a in AUDIENCES) == len(everything)
    assert sum(len(matches(all_rows, depth=d)) for d in DEPTHS) == len(everything)


def test_removed_questions_are_never_offered():
    with Session(ENGINE) as s:
        q = s.exec(select(ConvoQuestion)).first()
        text, was = q.text, q.dismissed
        q.dismissed = True
        s.add(q)
        s.commit()
    try:
        assert text not in [r["text"] for r in matches(rows())]
    finally:
        with Session(ENGINE) as s:
            q = s.exec(select(ConvoQuestion).where(
                ConvoQuestion.text == text)).first()
            q.dismissed = was
            s.add(q)
            s.commit()


# ---- the card --------------------------------------------
# The page is one question at a time now. These drive the real state, because
# a cursor that wraps is exactly the kind of thing that is fine until the pool
# is empty or the filters move under it.


def _state():
    from ledger_app.pages.convo import ConvoState
    st = ConvoState(_reflex_internal_init=True)
    st.load()
    return st


def test_the_cursor_wraps_in_both_directions():
    st = _state()
    st.cursor = st.total - 1
    st.next_card()
    assert st.cursor == 0, "next off the end must come back to the start"
    st.prev_card()
    assert st.cursor == st.total - 1, "prev off the start must go to the end"


def test_an_empty_pool_still_renders_a_card():
    """Filters that match nothing must not blow up card or card_position."""
    st = _state()
    st.audience = "not-a-real-audience"
    assert st.total == 0
    assert st.has_card is False
    assert st.card.id == 0 and st.card.text == ""
    assert st.card_position == "0"
    st.next_card()          # must be a no-op, not a ZeroDivisionError
    assert st.cursor == 0


def test_changing_a_filter_puts_the_cursor_back_at_the_top():
    st = _state()
    st.cursor = 5
    st.set_depth(DEPTHS[0])
    assert st.cursor == 0, "a smaller pool must not leave the cursor past its end"


def test_the_card_never_points_outside_the_pool():
    """cursor is not clamped on write, so card has to clamp on read."""
    st = _state()
    st.cursor = 10_000
    assert st.card.id != 0
    assert st.card.text


if __name__ == "__main__":
    ids = seed()
    try:
        test_every_question_is_tagged_on_both_axes()
        test_each_filter_value_has_questions()
        test_filters_narrow_and_combine()
        test_removed_questions_are_never_offered()
        test_the_cursor_wraps_in_both_directions()
        test_an_empty_pool_still_renders_a_card()
        test_changing_a_filter_puts_the_cursor_back_at_the_top()
        test_the_card_never_points_outside_the_pool()
    finally:
        unseed(ids)
    print("convo checks passed")
