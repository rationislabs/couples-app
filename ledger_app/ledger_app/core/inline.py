"""Rating and notes, edited in place, one implementation for every table.

Everything should be consistent across the board, with no Edit button to
press first. Before this, each page validated its own rating: shops and books
took 1-5 stars, recipes 1-10, and some tables any integer at all. Four
tables had no rating, and the edit sat behind a toggle on every one of them.

Now every table takes the same 1-10 through `save`, renders the same two cells,
and writes on blur — leaving the field is the save. `game` and `place` spell the
column `note` rather than `notes`; migrations here are additive, so it is not
renamed, and `save` resolves whichever one the model has.
"""
from __future__ import annotations

import reflex as rx
from sqlmodel import Session


def _engine():
    """Lazy, like verdicts._engine(): state.py imports this module for the
    library, and a module-level `from .state import ENGINE` would be a cycle."""
    from .state import ENGINE
    return ENGINE

RATING_MAX = 10
NOTES_MAX = 500


def notes_attr(model) -> str:
    return "notes" if "notes" in model.model_fields else "note"


def save(model, row_id: int, field: str, raw: str) -> str:
    """Write one rating or note. Returns a notice for the page to show.

    Nothing is written on invalid input, and an unchanged value is not a write:
    on_blur fires every time focus leaves the cell, including when you only
    tabbed through it.
    """
    v = (raw or "").strip()
    if field == "rating":
        if v and not (v.isdigit() and 1 <= int(v) <= RATING_MAX):
            return f"a rating is 1 to {RATING_MAX}, not “{v}”"
        value, attr = (int(v) if v else None), "rating"
    elif field == "notes":
        value, attr = v[:NOTES_MAX], notes_attr(model)
    else:
        return ""
    with Session(_engine()) as s:
        row = s.get(model, row_id)
        if row is None or getattr(row, attr) == value:
            return ""
        setattr(row, attr, value)
        s.add(row)
        s.commit()
    if field == "rating":
        return f"rated {value}/{RATING_MAX}" if value else "rating cleared"
    return "note saved" if value else "note cleared"


def shown(rating) -> str:
    """How a rating reads in a row dict: "" for none, so the input starts empty."""
    return str(rating) if rating else ""


def rating_cell(value, on_blur, key) -> rx.Component:
    return rx.table.cell(
        rx.input(default_value=value, on_blur=on_blur, key=key,
                 type="number", min=1, max=RATING_MAX, placeholder="–",
                 aria_label=f"Rating, 1 to {RATING_MAX}",
                 size="1", class_name="inline-edit inline-rating"),
    )


def notes_cell(value, on_blur, key) -> rx.Component:
    return rx.table.cell(
        rx.input(default_value=value, on_blur=on_blur, key=key,
                 placeholder="notes", size="1", max_length=NOTES_MAX, aria_label="Notes",
                 class_name="inline-edit inline-notes"),
    )
