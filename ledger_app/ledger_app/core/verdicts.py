"""Two people, one opinion each.

Read the docstring on `models.Verdict` for why this is a table and not two
columns. This module is the only thing that writes it, so the three-state
control behaves identically wherever it appears.

Nothing here knows about a page. A caller passes `kind` and a row id and gets
back a pair of controls; that is the whole interface.
"""
import os

import reflex as rx
from sqlmodel import Session, select

from .models import Verdict
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


# The people voting, named once in .env: LEDGER_PEOPLE="alex,sam". They are
# the keys stored in verdict.person, so renaming one orphans their votes.
PEOPLE = [p.strip().lower() for p in
          os.environ.get("LEDGER_PEOPLE", "me,you").split(",") if p.strip()]

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
            out[v.row_id][v.person] = v.value
    return out


def write(kind: str, row_id: int, person: str, value: str) -> None:
    """Set, or clear by setting the value already held.

    Clearing matters: "no opinion recorded" and "I could go either way" are
    different answers, and a control that cannot return to the first one
    turns every accidental click into a permanent preference.
    """
    if person not in PEOPLE or value not in VALUES:
        return
    with Session(_engine()) as s:
        row = s.exec(select(Verdict).where(
            Verdict.kind == kind, Verdict.row_id == row_id,
            Verdict.person == person)).first()
        if row is None:
            s.add(Verdict(person=person, kind=kind, row_id=row_id, value=value))
        elif row.value == value:
            s.delete(row)
        else:
            row.value = value
            s.add(row)
        s.commit()


def agreed(verdicts: dict[str, str]) -> bool:
    """Both said yes. The query the app could not answer before this table."""
    return all(verdicts.get(p) == UP for p in PEOPLE)


def summarise(verdicts: dict[str, str]) -> str:
    if agreed(verdicts):
        return "both yes"
    said = [p for p in PEOPLE if verdicts.get(p)]
    if not said:
        return ""
    return " · ".join(f"{p[0].upper()}{GLYPH[verdicts[p]]}" for p in said)


def control(verdicts, on_click) -> rx.Component:
    """Two rows of three buttons. `verdicts` is a Var holding {person: value}.

    `on_click` takes (person, value) and is built by the caller, which is what
    binds the row id — the page owns the event because it has to reload its own
    rows afterwards.
    """
    def one(person: str) -> rx.Component:
        return rx.hstack(
            rx.text(person[0].upper(), size="1",
                    style={"color": "var(--dim)", "width": "1rem"}),
            *[rx.button(
                GLYPH[v], size="1",
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

    return rx.vstack(*[one(p) for p in PEOPLE], spacing="1", align="start",
                     class_name="verdicts")


def unvoted_row(state) -> rx.Component:
    """One chip per person: only the rows they have not voted on yet, so the
    backlog of unanswered rows can be worked through. `state` needs `unvoted`
    and `set_unvoted`. A row leaves the list the moment its vote lands."""
    return choice_row("to vote", state.unvoted, state.set_unvoted,
                      [(p, p.capitalize()) for p in PEOPLE])

