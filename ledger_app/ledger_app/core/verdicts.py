"""Two people, one opinion each.

Read the docstring on `models.Verdict` for why this is a table and not two
columns. This module is the only thing that writes it, so the three-state
control behaves identically wherever it appears.

Nothing here knows about a page. A caller passes `kind` and a row id and gets
back a pair of controls; that is the whole interface.
"""
import reflex as rx
from sqlmodel import Session, select

from .models import Verdict
from .household import SLOTS
from .profile import ProfileState
from .ui import choice_row

def _engine():
    """Imported on use, not at module load.

    state.py needs this module for the library's verdict column, and this
    module needs state.ENGINE — importing it at the top makes that a cycle.
    Deferring it here fixes it for every caller rather than making each one
    import late.
    """
    from .state import ENGINE
    return ENGINE


# The two slots, "1" and "2" — user ids. Names live in the user table and
# reach components through ProfileState (core/profile.py), so renaming a
# person is a database write and keeps every vote.
PEOPLE = SLOTS

UP, MID, DOWN = "up", "mid", "down"
VALUES = [UP, MID, DOWN]
GLYPH = {UP: "▲", MID: "●", DOWN: "▼"}
HUE = {UP: "var(--good)", MID: "var(--dim)", DOWN: "var(--vermilion)"}


def read(kind: str, row_ids: list[int]) -> dict[int, dict[str, str]]:
    """{row_id: {person: value}} for one page's worth of rows, in one query."""
    if not row_ids:
        return {}
    out: dict[int, dict[str, str]] = {r: {} for r in row_ids}
    with Session(_engine()) as s:
        rows = s.exec(select(Verdict).where(Verdict.kind == kind)).all()
    for v in rows:
        if v.row_id in out:
            out[v.row_id][str(v.user_id)] = v.value
    return out


def write(kind: str, row_id: int, person: str, value: str) -> None:
    """Set, or clear by setting the value already held.

    Clearing matters: "no opinion recorded" and "I could go either way" are
    different answers, and a control that cannot return to the first one
    turns every accidental click into a permanent preference.
    """
    if person not in PEOPLE or value not in VALUES:
        return
    uid = int(person)
    with Session(_engine()) as s:
        row = s.exec(select(Verdict).where(
            Verdict.kind == kind, Verdict.row_id == row_id,
            Verdict.user_id == uid)).first()
        if row is None:
            s.add(Verdict(user_id=uid, kind=kind, row_id=row_id, value=value))
        elif row.value == value:
            s.delete(row)
        else:
            row.value = value
            s.add(row)
        s.commit()


async def write_as(state: rx.State, kind: str, row_id: int, person: str, value: str) -> bool:
    """Write only the vote of the person selected in this browser. The other
    row's buttons are disabled, but a handler must not trust the client."""
    me = (await state.get_state(ProfileState)).me
    if person != me:
        return False
    write(kind, row_id, person, value)
    return True


def agreed(verdicts: dict[str, str]) -> bool:
    """Both said yes. The query the app could not answer before this table."""
    return all(verdicts.get(p) == UP for p in PEOPLE)


def summarise(verdicts: dict[str, str], names: dict[str, str]) -> str:
    if agreed(verdicts):
        return "both yes"
    said = [p for p in PEOPLE if verdicts.get(p)]
    if not said:
        return ""
    return " · ".join(f"{(names.get(p) or p)[:1].upper()}{GLYPH[verdicts[p]]}" for p in said)


def control(verdicts, on_click) -> rx.Component:
    """Two rows of three buttons, one row per person. `verdicts` is a Var
    holding {slot: value}. Only the row of the person selected in the header
    is clickable; the other row shows their answer.

    `on_click` takes (person, value) and is built by the caller, which is what
    binds the row id — the page owns the event because it has to reload its own
    rows afterwards.
    """
    def one(person: str) -> rx.Component:
        mine = ProfileState.me == person
        return rx.hstack(
            rx.text(ProfileState.initials[person], size="1",
                    style={"color": "var(--dim)", "width": "1rem"}),
            *[rx.button(
                GLYPH[v], size="1",
                disabled=~mine,
                variant=rx.cond(verdicts[person] == v, "solid", "surface"),
                on_click=on_click(person, v),
                style={"color": rx.cond(verdicts[person] == v,
                                        "var(--ink)", HUE[v]),
                       "background": rx.cond(verdicts[person] == v,
                                             HUE[v], "transparent"),
                       "minWidth": "1.8rem", "padding": "0 0.35rem"},
              ) for v in VALUES],
            spacing="1", align="center",
        )

    return rx.vstack(
        *[one(p) for p in PEOPLE],
        rx.cond(ProfileState.me == "",
                rx.text("Pick your name at the top to vote.", size="1",
                        style={"color": "var(--dim)"})),
        spacing="1", align="start", class_name="verdicts")


def unvoted_row(state) -> rx.Component:
    """One chip per person: only the rows they have not voted on yet, so the
    backlog of unanswered rows can be worked through. `state` needs `unvoted`
    and `set_unvoted`. A row leaves the list the moment its vote lands."""
    return choice_row("to vote", state.unvoted, state.set_unvoted,
                      [(p, ProfileState.names[p]) for p in PEOPLE])
