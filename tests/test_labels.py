"""Controls a screen reader can name.

The vote buttons were bare glyphs (▲ ● ▼) and the rating and notes inputs had
only a placeholder, so each read as "button" or "edit text".

    ./.venv/bin/python test_labels.py
"""
import reflex as rx

import _db  # noqa: F401  (first: never the real hearth.db)

from hearth.core import inline as IN, verdicts as V        # noqa: E402


def controls(c, kind, out):
    if isinstance(c, kind):
        out.append(c)
    for k in getattr(c, "children", []) or []:
        if isinstance(k, rx.Component):
            controls(k, kind, out)
    return out


def labelled(c) -> bool:
    return getattr(c, "aria_label", None) is not None or "aria-label" in str(c.render())


def text_of(c) -> str:
    if type(c).__name__ == "Bare":
        return str(c.contents).strip('"` ')
    return "".join(text_of(k) for k in getattr(c, "children", []) or [] if isinstance(k, rx.Component))


def test_no_table_column_is_unnamed():
    from hearth.pages import convo, dates, household
    Head = type(rx.table.column_header_cell(""))
    for page in (convo.page, dates.page, household.page):
        blank = [h for h in controls(page(), Head, []) if not text_of(h)]
        assert not blank, f"{page.__module__}: {len(blank)} unnamed column header(s)"


def test_the_toast_region_is_there_before_its_message():
    """A live region inserted with its message already in it is often not
    announced; the region must exist empty, and the message arrive inside it."""
    from hearth.core.ui import notice_toast
    top = notice_toast(rx.Var.create("")).render()
    assert any("aria-live" in p for p in top["props"]), \
        f"the live region is inside the condition: {top['name']} {top['props']}"


def test_every_vote_button_has_a_name():
    tree = V.control(rx.Var.create({"1": "", "2": ""}), lambda p, v: rx.console_log(v))
    buttons = controls(tree, type(rx.button("")), [])
    assert len(buttons) == 6 and all(labelled(b) for b in buttons), len(buttons)


def test_rating_and_notes_inputs_have_names():
    for cell in (IN.rating_cell("", rx.console_log("x"), "k"), IN.notes_cell("", rx.console_log("x"), "k")):
        inputs = controls(cell, type(rx.input()), [])
        assert inputs and all(labelled(i) for i in inputs), cell


if __name__ == "__main__":
    for fn in (test_the_toast_region_is_there_before_its_message, test_no_table_column_is_unnamed, test_every_vote_button_has_a_name, test_rating_and_notes_inputs_have_names):
        fn()
        print(f"  ok  {fn.__name__}")
    print("label checks passed")
