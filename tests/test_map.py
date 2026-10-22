"""Checks for pages/dates.py build_map(): place names are text, never markup.

    ledger_app/.venv/bin/python tests/test_map.py

Names, tags and cities come from Google Takeout and OpenStreetMap. Pasted into
the popup HTML or the inline <script> as-is, a name containing markup runs as
script inside the map.
"""
import _db  # noqa: F401  (first: never the real ledger.db)

from ledger_app.pages.dates import build_map  # noqa: E402

EVIL = "</script><img src=x onerror=alert(1)>"


def row(**kw):
    base = {"lat": 48.2, "lon": 16.37, "name": "Cafe", "url": "", "tag_list": [],
            "city": "Vienna", "km": 1.0, "visited": False}
    return {**base, **kw}


def test_names_cannot_close_the_script():
    html, n = build_map([row(name=EVIL, city=EVIL, tag_list=[EVIL])], None)
    assert n == 1
    assert html.count("</script>") == html.count("<script") , "a name closed the script tag"
    assert "\\u003c/script" in html


def test_popups_are_built_from_text_nodes():
    html, _ = build_map([row()], None)
    assert "textContent" in html
    assert "bindPopup(`" not in html, "popup still assembled as an HTML string"


def test_only_web_links_open():
    # javascript: must never become a link; a hand-entered http:// address still is one.
    html, _ = build_map([row(url="javascript:alert(1)")], None)
    assert "/^https?:\\/\\//" in html  # the guard is in the page script


if __name__ == "__main__":
    for fn in (test_names_cannot_close_the_script, test_popups_are_built_from_text_nodes,
               test_only_web_links_open):
        fn()
        print(f"  ok  {fn.__name__}")
    print("map checks passed")
