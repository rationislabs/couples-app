"""Checks for pages/recipes.py scrape(): only web pages, and never more of
one than fits in memory.

    hearth/.venv/bin/python tests/test_recipes_import.py

urlopen also opens file:// and ftp:// URLs, and r.read() with no size reads
until the server stops: file:///dev/zero never stops.
"""
import io
import urllib.request

import _db  # noqa: F401  (first: never the real hearth.db)

from hearth.pages import recipes as R  # noqa: E402


def refuses(url):
    try:
        R.scrape(url)
    except ValueError as e:
        return str(e)
    raise AssertionError(f"{url} was fetched")


def test_only_http_and_https():
    assert "http" in refuses("file:///etc/passwd")
    assert "http" in refuses("ftp://example.com/r.html")
    assert "http" in refuses("javascript:alert(1)")


class Endless(io.RawIOBase):
    """A response body that never ends; counts what was read."""
    def __init__(self):
        self.read_bytes = 0

    def read(self, n=-1):
        n = 1 << 20 if n is None or n < 0 else n
        self.read_bytes += n
        return b"x" * n

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_page_size_is_capped():
    body = Endless()
    R._OPENER.open = lambda *a, **k: body
    try:
        assert "too large" in refuses("https://example.com/huge")
    finally:
        del R._OPENER.open
    assert body.read_bytes <= R.MAX_PAGE + 1, body.read_bytes


def test_a_redirect_must_stay_on_the_web():
    # urllib follows a redirect to ftp:// on its own.
    h = R._WebOnlyRedirect()
    req = urllib.request.Request("https://example.com/r")
    for target in ("ftp://example.com/r.html", "file:///etc/passwd"):
        try:
            h.redirect_request(req, None, 302, "Found", {}, target)
        except ValueError as e:
            assert "http" in str(e)
        else:
            raise AssertionError(f"followed a redirect to {target}")
    assert h.redirect_request(req, None, 302, "Found", {}, "https://example.com/r2") is not None


if __name__ == "__main__":
    for fn in (test_only_http_and_https, test_page_size_is_capped,
               test_a_redirect_must_stay_on_the_web):
        fn()
        print(f"  ok  {fn.__name__}")
    print("recipe import checks passed")
