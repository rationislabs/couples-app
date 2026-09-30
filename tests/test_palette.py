"""Checks for the command palette's matcher.

The matcher lives in assets/keys.js because the palette navigates with a plain
href and must not round-trip. That puts it outside every other test in this
directory, so this file runs it under node instead of reimplementing it — a
second copy of a ranking function is a second thing to get wrong.
"""
import json
import pathlib
import re
import shutil
import subprocess
import sys

KEYS = pathlib.Path(__file__).resolve().parents[1] / "ledger_app" / "assets" / "keys.js"

# The IIFE keeps its own names, so the two functions are lifted out by source
# slice rather than imported. If either is renamed this fails loudly, which is
# the intent.
HARNESS = """
%s
%s
const PLACES = %s;
const queries = %s;
console.log(JSON.stringify(queries.map((q) => matches(q).map((p) => p[0]))));
"""


def _slice(src: str, name: str) -> str:
    start = src.index(f"function {name}(")
    depth, i = 0, src.index("{", start)
    for j in range(i, len(src)):
        depth += (src[j] == "{") - (src[j] == "}")
        if depth == 0:
            return src[start:j + 1]
    raise AssertionError(f"{name} never closes")


def run(*queries):
    src = KEYS.read_text()
    places = src[src.index("const PLACES = ["):src.index("];", src.index("const PLACES = [")) + 2]
    js = HARNESS % (_slice(src, "score"), _slice(src, "matches"),
                    places.split("=", 1)[1].strip().rstrip(";"),
                    json.dumps(list(queries)))
    p = subprocess.run(["node", "-e", js], capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


def test_empty_query_lists_everything_in_order():
    assert run("")[0][0] == "Tonight"
    assert len(run("")[0]) == 13


def test_subsequence_beats_substring():
    """"cnv" is not a substring of Conversation. It still has to find it."""
    assert run("cnv")[0][0] == "Conversation"


def test_exact_prefix_wins_over_a_scattered_hit():
    """"boo" is a prefix of Books; a scattered hit must rank below it."""
    assert run("boo")[0][0] == "Books"


def test_a_hint_can_match_when_the_name_cannot():
    """Nothing is called Watering. The Plants hint says it."""
    hits = run("watering")[0]
    assert hits and hits[0] == "Plants"


def test_nonsense_matches_nothing():
    assert run("zzzz")[0] == []


def test_a_verb_outranks_a_place_at_the_same_score():
    """On a page where the button exists, doing the
    thing beats navigating to where the thing is."""
    src = KEYS.read_text()
    places = src[src.index("const PLACES = ["):src.index("];", src.index("const PLACES = [")) + 2]
    js = HARNESS % (_slice(src, "score"), _slice(src, "matches"),
                    places.split("=", 1)[1].strip().rstrip(";"),
                    json.dumps(["next"]))
    js = js.replace("matches(q)", 'matches(q, [["Next", {verb: ["next"]}, "on this page"]])')
    out = subprocess.run(["node", "-e", js], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout)[0][0] == "Next"


def test_every_verb_label_is_lowercase_and_trimmed():
    """findButton compares against a trimmed, lowercased textContent, so a
    label with a capital in it would never match and would fail silently."""
    src = KEYS.read_text()
    block = src[src.index("const VERBS = ["):src.index("];", src.index("const VERBS = ["))]
    labels = [lab
              for group in re.findall(r'\["[^"]*",\s*\[([^\]]*)\]', block)
              for lab in re.findall(r'"([^"]+)"', group)]
    assert len(labels) >= 11, f"only found {len(labels)} verb labels"
    for lab in labels:
        assert lab == lab.strip().lower(), f"{lab!r} can never match a button"


def test_every_target_is_a_real_route():
    from ledger_app.core import ui
    src = KEYS.read_text()
    block = src[src.index("const PLACES = ["):src.index("];", src.index("const PLACES = ["))]
    hrefs = [ln.split('"')[3] for ln in block.split("\n") if ln.strip().startswith('["')]
    known = set(ui.PAGE_TINTS) | {"/meal-plan", "/recipes/[slug]"}
    for h in hrefs:
        assert h.split("#")[0] in known, f"{h} is not a registered route"


if __name__ == "__main__":
    if not shutil.which("node"):
        print("node not found; palette checks skipped")
        sys.exit(0)
    for fn in (test_empty_query_lists_everything_in_order,
               test_subsequence_beats_substring,
               test_exact_prefix_wins_over_a_scattered_hit,
               test_a_hint_can_match_when_the_name_cannot,
               test_nonsense_matches_nothing,
               test_a_verb_outranks_a_place_at_the_same_score,
               test_every_verb_label_is_lowercase_and_trimmed,
               test_every_target_is_a_real_route):
        fn()
        print(f"  ok  {fn.__name__}")
    print("palette checks passed")
