"""One h1 per page.

rx.heading renders an h1 unless told otherwise, so every section heading was a
second page title for a screen reader, and as_="p" is not a heading level
Radix accepts. Each page's component tree is walked: exactly one heading at h1,
every other one at h2-h6.

    ./.venv/bin/python test_headings.py
"""
import reflex as rx
from reflex.components.radix.themes.typography.heading import Heading

from ledger_app import ledger_app as L                        # noqa: E402
from ledger_app.pages import (books, convo, dates, home, household,  # noqa: E402
                              music, recipes, setup)

PAGES = {"/library": L.index, "/books": books.page, "/convo": convo.page,
         "/dates": dates.page, "/": home.page, "/household": household.page,
         "/music": music.page, "/recipes": recipes.index, "/meal-plan": recipes.planner,
         "/setup": setup.setup_page}
LEVELS = {"h2", "h3", "h4", "h5", "h6"}


def levels(c, out: list[str]) -> list[str]:
    if isinstance(c, Heading):
        a = getattr(c, "as_", None)
        out.append("h1" if a is None else str(getattr(a, "_js_expr", a)).strip('"'))
    for k in getattr(c, "children", []) or []:
        if isinstance(k, rx.Component):
            levels(k, out)
    if type(c).__name__ == "Foreach":
        levels(c.render(), out)
    return out


def test_every_page_has_one_h1():
    for route, page in PAGES.items():
        got = levels(page(), [])
        assert got.count("h1") == 1, f"{route}: {got}"
        assert set(got) - {"h1"} <= LEVELS, f"{route}: {got}"


def test_a_recipe_has_one_h1_and_its_sections_below_it():
    got = levels(recipes.detail(), [])
    # "Not found" is the other branch of the same title, never shown with it
    assert got.count("h1") == 2 and set(got) - {"h1"} <= LEVELS, got


if __name__ == "__main__":
    for fn in (test_every_page_has_one_h1, test_a_recipe_has_one_h1_and_its_sections_below_it):
        fn()
        print(f"  ok  {fn.__name__}")
    print("heading checks passed")
