"""Checks on how pages load their data.

Each page loaded twice: once from add_page's on_load and again from an
on_mount on the page itself. And /dates showed Travel without loading it, while
/household loaded Travel without showing it. Both are visible only in the
browser, so they are pinned here against the registrations.

    ./.venv/bin/python test_pages.py
"""
import pathlib
import re

SRC = pathlib.Path(__file__).resolve().parents[1] / "ledger_app" / "ledger_app"


def registration(route: str) -> str:
    text = (SRC / "ledger_app.py").read_text()
    m = re.search(r'themed_page\([^)]*route="' + re.escape(route) + r'".*?\)\n', text, re.S)
    assert m, route
    return m.group(0)


def test_no_page_also_loads_on_mount():
    pages = [SRC / "ledger_app.py", *sorted((SRC / "pages").glob("*.py"))]
    hits = [f"{p.name}:{n}" for p in pages
            for n, line in enumerate(p.read_text().splitlines(), 1) if "on_mount=" in line]
    assert not hits, f"on_load already loads these pages: {hits}"


def test_travel_loads_where_it_is_shown():
    assert "TravelState.load" in registration("/dates")
    assert "TravelState.load" not in registration("/household")


if __name__ == "__main__":
    for fn in (test_no_page_also_loads_on_mount, test_travel_loads_where_it_is_shown):
        fn()
        print(f"  ok  {fn.__name__}")
    print("page checks passed")
