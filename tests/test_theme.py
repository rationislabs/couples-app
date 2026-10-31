"""Per-page surface tints, and the check that they still carry text.

An earlier design capped surface hue rotation at ±20°. That cap was measured
by rotating hue at constant HLS *lightness*, which is not luminance: the green
channel carries 0.7152 of the weight, so a rotation moves the plate's luminance
and the contrast with it. Re-solve lightness per hue and the cap disappears —
contrast depends on luminance alone, so a luminance-matched rotation holds
every foreground ratio to within 0.06 of the base plate at any hue.

This file is the only place the tinted hexes exist. `python test_theme.py`
prints the CSS block for hearth.css; pytest asserts the tints stay legible.
"""
import colorsys

# The base ramp, from hearth.css :root. Surfaces only — the meaning channel
# (--mustard, --good, --vermilion, --teal) is never rotated.
# Ordered darkest to lightest; test_the_ramp_stays_a_ramp depends on that.
# --ink2 and --edge are the two literals hearth.css was passing to Radix's
# --gray-2 and --gray-6 by hand; they are named here so they rotate too.
RAMP = {"--ink": "#0A1626", "--ink2": "#0D1A2C", "--plate": "#12213A",
        "--plate2": "#1E3050", "--plate3": "#27395C", "--rule": "#2C456B",
        "--edge": "#35507A"}

# Everything that is ever drawn on a plate.
FOREGROUND = {"--bone": "#E8EDF5", "--dim": "#8998B1", "--good": "#5FBE8C",
              "--mustard": "#F2A93B", "--teal": "#3FB6A8"}

# Emitted as `.page-*`, not `.room-*`: rooms carry voice, density and the
# signature hue, pages carry the surface ramp, and "lobby" is both a room and a
# page, so the two namespaces have to stay apart.
# One hue per page, not per room: /books wants burgundy while /library and
# /music share its room. Hues sit off the §1.1 meaning table where there was
# room to move; /plants at 150 and /games at 128 sit near --good's 148 on
# purpose, since at plate luminance they read as a dark surface, not a badge.
# Nine, not twelve: /household folded /plants, /shops, /travel and /games
# into one page, which takes the green that /plants had — it is the section of
# the four with anything alive in it.
PAGE_HUES = {"lobby": 236, "library": 218, "books": 338, "music": 278,
             "dates": 205, "convo": 258, "recipes": 18,
             "household": 150}


def _unhex(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def luminance(rgb):
    c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in rgb]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def ratio(a, b):
    la, lb = luminance(_unhex(a)), luminance(_unhex(b))
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def rotate(base, hue):
    """`base` at `hue`, same saturation, lightness re-solved to match luminance."""
    _, _, sat = colorsys.rgb_to_hls(*_unhex(base))
    target = luminance(_unhex(base))
    lo, hi = 0.0, 1.0
    for _ in range(60):  # ponytail: bisection, exact enough at 8-bit output
        mid = (lo + hi) / 2
        if luminance(colorsys.hls_to_rgb(hue / 360, mid, sat)) < target:
            lo = mid
        else:
            hi = mid
    rgb = colorsys.hls_to_rgb(hue / 360, (lo + hi) / 2, sat)
    return "#%02X%02X%02X" % tuple(round(x * 255) for x in rgb)


def page_ramp(page):
    return {token: rotate(base, PAGE_HUES[page]) for token, base in RAMP.items()}


def test_every_page_surface_carries_text():
    for page in PAGE_HUES:
        plate = page_ramp(page)["--plate"]
        assert ratio(plate, "#E8EDF5") >= 7.0, f"{page}: bone on plate"
        assert ratio(plate, "#8998B1") >= 4.5, f"{page}: dim on plate"


def test_rotation_holds_contrast_to_the_base_plate():
    """The whole premise: tinting is free as long as luminance is matched."""
    for page in PAGE_HUES:
        plate = page_ramp(page)["--plate"]
        for name, fg in FOREGROUND.items():
            drift = abs(ratio(plate, fg) - ratio(RAMP["--plate"], fg))
            assert drift < 0.1, f"{page}: {name} drifted {drift:.2f}"


def test_the_ramp_stays_a_ramp():
    """Hover fills must stay lighter than the surface they sit on."""
    for page in PAGE_HUES:
        r = page_ramp(page)
        steps = [luminance(_unhex(r[t])) for t in RAMP]
        assert steps == sorted(steps), f"{page}: ramp out of order"


if __name__ == "__main__":
    for fn in (test_every_page_surface_carries_text,
               test_rotation_holds_contrast_to_the_base_plate,
               test_the_ramp_stays_a_ramp):
        fn()
        print(f"  ok  {fn.__name__}")
    print("theme checks passed\n")
    for page in PAGE_HUES:
        decls = " ".join(f"{k}: {v};" for k, v in page_ramp(page).items())
        print(f".page-{page} {{ {decls} }}")
