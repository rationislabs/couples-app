"""Structural checks on assets/ledger.css.

These exist because of a real failure: the bubbly block sat at the end of the
file, and a script that rebuilt the tail from the generated marker onward
deleted it silently. Nobody noticed for two sessions, and a commit message
claimed it had been kept while it was not in the tree.

    ./.venv/bin/python test_css.py
"""
import pathlib
import re
import sys

CSS = pathlib.Path(__file__).resolve().parents[1] / "ledger_app" / "assets" / "ledger.css"
BEGIN = "/* == GENERATED: page ramps."
END = "/* == END GENERATED == */"


def text():
    return CSS.read_text()


def test_braces_balance():
    t = text()
    assert t.count("{") == t.count("}"), "unbalanced braces"


def test_the_generated_region_is_the_end_of_the_file():
    """Anything written after it is one careless rewrite from being deleted."""
    t = text().rstrip()
    assert t.endswith(END), "something was appended after the generated region"
    assert t.index(BEGIN) < t.index(END)


def test_the_generated_region_holds_only_page_ramps():
    t = text()
    body = t[t.index(BEGIN):t.index(END)]
    rules = re.findall(r"^([.#@][^\s{]*)", body, re.M)
    assert rules, "no rules found in the generated region"
    for r in rules:
        assert r.startswith(".page-"), f"{r} does not belong in the generated block"


def test_the_bubbly_block_is_present():
    """It was lost once."""
    t = text()
    assert "BUBBLY" in t, "the bubbly block is gone again"
    assert ".tonight-card { border-radius" in t


def test_the_container_width_targets_the_element_that_carries_it():
    """Radix puts max-width on .rt-ContainerInner. Overriding .rt-Container
    changes nothing, which is exactly what happened the first time."""
    t = text()
    assert "--container-4: 1440px" in t, "the width token was not raised"
    assert "max-width: none; width: 100%;\n  padding-left" not in t, \
        "the old no-op .rt-Container override is back"


def test_no_page_still_sets_container_padding_inline():
    """An inline padding on rx.container beats every gutter rule here."""
    import pathlib as _p
    # rglob: the package is split into core/ and pages/, a flat glob misses both
    for f in (_p.Path(__file__).resolve().parents[1] / "ledger_app" / "ledger_app").rglob("*.py"):
        assert 'padding="1.75rem 1.5rem"' not in f.read_text(), f.name


def test_the_navbar_breaks_out_of_the_container():
    """The container caps at 1440px, so cancelling its gutter only reached the
    container's edges, not the window's. The bar has to break out."""
    t = text()
    nav = t[t.index(".nav {"):t.index("}", t.index(".nav {"))]
    assert "margin-inline: calc(50% - 50vw)" in nav, \
        "the navbar is back inside the container's width"
    assert "width: 100vw" in nav, \
        "a negative margin moves an edge; it does not stretch the box"
    assert "position: sticky" in nav

    # An inline width on the hstack beats all of the above, silently.
    import pathlib as _p
    ui = (_p.Path(__file__).resolve().parents[1] / "ledger_app" / "ledger_app" / "core" / "ui.py").read_text()
    bar = ui[ui.index("def navbar("):ui.index("def chip(")]
    code = "\n".join(l for l in bar.split("\n")
                     if not l.lstrip().startswith("#"))
    assert 'width="100%"' not in code, "navbar has an inline width again"


def test_the_navbar_emoji_turn_over_daily():
    """Same five all day, a different five tomorrow, and the navbar reads the
    state var rather than a string frozen into the cached build."""
    from datetime import date, timedelta
    from ledger_app.core.ui import daily_emoji
    d = date(2000, 1, 1)
    assert daily_emoji(d) == daily_emoji(d)
    assert len(set(daily_emoji(d))) == 5
    week = {daily_emoji(d + timedelta(n)) for n in range(7)}
    assert len(week) == 7, "the set did not change from day to day"
    assert "NavState.emoji" in (pathlib.Path(__file__).resolve().parents[1] / "ledger_app"
                                / "ledger_app" / "core" / "ui.py").read_text()


def test_every_paged_table_has_prev_next_above_and_below():
    """Two pairs per paged table, so a long page never needs scrolling back up.
    Rendered rather than grepped: catalog_table is one function drawing two tables."""
    from ledger_app import ledger_app as L
    from ledger_app.pages import convo, dates, music, recipes
    # convo's question card carries a Prev/Next pair of its own
    for name, page, want in (("library", L.index, 2),
                             ("convo", convo.page, 3), ("dates", dates.page, 2),
                             ("recipes", recipes.index, 2), ("music", music.page, 2)):
        js = str(page().render())
        assert js.count('"Prev"') == js.count('"Next"') == want, name


def test_the_phone_menu_lists_every_tab_and_marks_this_page():
    """Below 48em the tabs fold into a menu. Every tab has to be in it, the page
    you are on is the one marked, and each entry navigates through on_select —
    an rx.link child under as_child crashed the page the moment it opened."""
    from ledger_app.core.ui import TABS
    from ledger_app.pages import convo
    js = str(convo.page().render())
    assert js.count("nav-menu-item room-") == len(TABS)
    assert js.count("nav-menu-item room-private on") == 1
    menu = js[js.index("nav-menu-item"):]
    assert menu.count("onSelect") >= len(TABS), "a menu entry lost its navigation"

def test_every_block_sits_above_the_generated_region():
    t = text()
    for name in (".nav {", ".toast {", ".question-card {", ".verdicts button",
                 ".tonight-card {"):
        assert name in t, f"{name} missing"
        assert t.index(name) < t.index(BEGIN), f"{name} is below the generated region"


if __name__ == "__main__":
    for fn in (test_braces_balance,
               test_the_generated_region_is_the_end_of_the_file,
               test_the_generated_region_holds_only_page_ramps,
               test_the_bubbly_block_is_present,
               test_the_container_width_targets_the_element_that_carries_it,
               test_no_page_still_sets_container_padding_inline,
               test_the_navbar_breaks_out_of_the_container,
               test_the_navbar_emoji_turn_over_daily,
               test_every_paged_table_has_prev_next_above_and_below,
               test_the_phone_menu_lists_every_tab_and_marks_this_page,
               test_every_block_sits_above_the_generated_region):
        fn()
        print(f"  ok  {fn.__name__}")
    print("css checks passed")
