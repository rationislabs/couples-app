"""Checks for first run, Settings and the home location.

    ledger_app/.venv/bin/python tests/test_setup_flow.py
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import _db  # noqa: E402
_db.migrate()

from ledger_app.core import household as H                      # noqa: E402


def test_redirect_rule():
    assert H.setup_redirect("/", False) == "/setup"
    assert H.setup_redirect("/dates", False) == "/setup"
    assert H.setup_redirect("/setup", False) is None
    assert H.setup_redirect("/setup", True) == "/"
    assert H.setup_redirect("/dates", True) is None


def test_names_are_required_and_distinct():
    for a, b in (("", "Sam"), ("Alex", "  "), ("Alex", "alex")):
        try:
            H.set_names(a, b)
        except ValueError:
            continue
        raise AssertionError(f"accepted {a!r}, {b!r}")
    H.set_names(" Alex ", "Sam")
    assert H.names() == {"1": "Alex", "2": "Sam"}


def test_latlon_parsing():
    assert H.parse_latlon("") is None
    assert H.parse_latlon(" 48.2, 16.37 ") == (48.2, 16.37)
    for bad in ("48.2", "a,b", "1,2,3", "91,0", "0,181"):
        try:
            H.parse_latlon(bad)
        except ValueError:
            continue
        raise AssertionError(f"accepted {bad!r}")


def test_home_round_trip_and_clearing():
    H.set_home((48.2, 16.37))
    assert H.home() == (48.2, 16.37)
    assert round(H.distance_km(H.home(), 48.21, 16.37)) == 1
    H.set_home(None)
    assert H.home() is None
    assert H.distance_km(None, 48.21, 16.37) is None


def test_no_home_does_not_empty_tonight():
    """Tonight defaults to near_only with a 60 km radius. Without a home every
    distance is unknown, and the filter must switch off rather than drop all."""
    from ledger_app.pages.home import too_far
    assert too_far(None, None, True, 60, "out to eat") is False
    assert too_far((48.2, 16.37), None, True, 60, "out to eat") is True
    assert too_far((48.2, 16.37), 80.0, True, 60, "out to eat") is True
    assert too_far((48.2, 16.37), 10.0, True, 60, "out to eat") is False
    assert too_far((48.2, 16.37), 80.0, True, 60, "stay in") is False


def test_finish_setup_flips_the_gate():
    assert H.settings().setup_done is False
    H.finish_setup()
    assert H.setup_redirect("/", H.settings().setup_done) is None


if __name__ == "__main__":
    for fn in (test_redirect_rule, test_names_are_required_and_distinct,
               test_latlon_parsing, test_home_round_trip_and_clearing,
               test_no_home_does_not_empty_tonight, test_finish_setup_flips_the_gate):
        fn()
        print(f"  ok  {fn.__name__}")
    print("setup checks passed")
