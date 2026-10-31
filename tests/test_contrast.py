"""Text colours pass WCAG AA (4.5:1) on every surface text sits on.

--dim is the secondary text colour on every page; --vermilion and --rose are
also used as text (plant health, the spicy toggle, chips). Each is checked
against the page (--ink), cards (--plate) and raised rows (--plate2), and no
hex copy of a value they replaced may survive to escape this check.

    ./.venv/bin/python test_contrast.py
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1] / "hearth"
CSS = (ROOT / "assets" / "hearth.css").read_text()
SURFACES = ("--ink", "--plate", "--plate2")
TEXT = ("--dim", "--vermilion", "--rose")


def token(name: str) -> str:
    m = re.search(rf"{name}:\s*(#[0-9A-Fa-f]{{6}})", CSS)
    assert m, f"{name} is not defined as a hex colour"
    return m.group(1)


def ratio(a: str, b: str) -> float:
    def lum(h: str) -> float:
        c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
        return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_text_colours_pass_aa_on_every_surface():
    for t in TEXT:
        for s in SURFACES:
            r = ratio(token(t), token(s))
            assert r >= 4.5, f"{t} on {s}: {r:.2f}:1"


# Values the tokens above replaced. A hex copy of one in a chip, bar or map
# colour escapes the token, and the check above with it.
RETIRED = ("#C43A6E", "#E2503F", "#7C8CA8")


def test_no_copy_of_a_retired_value_survives():
    hits = [f"{p.name}:{n}" for p in sorted((ROOT / "hearth").rglob("*.py"))
            for n, line in enumerate(p.read_text().splitlines(), 1)
            if any(h in line.upper() for h in RETIRED)]
    assert not hits, hits


if __name__ == "__main__":
    for fn in (test_text_colours_pass_aa_on_every_surface, test_no_copy_of_a_retired_value_survives):
        fn()
        print(f"  ok  {fn.__name__}")
    print("contrast checks passed")
