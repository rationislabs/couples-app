#!/usr/bin/env python3
"""Tag every saved place with what kind of place it is.

    ./.venv/bin/python categorize_places.py --dry-run   # measure, change nothing
    ./.venv/bin/python categorize_places.py             # write `tags`

Keyword matching over the name, the Google Maps list it came from and your note.
Rows you have edited by hand (tag_source == "manual") are never touched, so a
re-run after the patterns improve keeps your corrections.
"""
from __future__ import annotations

import pathlib
import sys
from collections import Counter

from sqlmodel import Session, create_engine, select

from hearth.core.models import Place            # noqa: E402
from hearth.core.paths import db_path  # noqa: E402
from hearth.core.place_types import classify     # noqa: E402

APP = pathlib.Path(__file__).resolve().parents[2] / "hearth"
ENGINE = create_engine(f"sqlite:///{db_path()}")


def main() -> int:
    dry = "--dry-run" in sys.argv
    per_type: Counter = Counter()
    tagged = kept = 0
    unmatched: list[str] = []

    with Session(ENGINE) as s:
        places = [p for p in s.exec(select(Place)).all() if not p.dismissed]
        for p in places:
            if p.tag_source == "manual":
                kept += 1
                continue
            types = classify(p.name, p.list_name, p.note)
            if types:
                tagged += 1
                per_type.update(types)
            else:
                unmatched.append(p.name)
            if not dry:
                p.tags = ",".join(types)
                p.tag_source = "auto" if types else ""
                s.add(p)
        if not dry:
            s.commit()

    n = len(places)
    print(f"{tagged}/{n} tagged = {tagged / n:.0%}"
          f"   ({kept} left alone as manual, {len(unmatched)} unmatched)")
    print(f"tags applied: {sum(per_type.values())}, "
          f"multi-tagged places: {sum(per_type.values()) - tagged}")
    print("\nper type:")
    for t, c in per_type.most_common():
        print(f"  {c:5} {t}")
    print(f"\nunmatched sample: {unmatched[:12]}")
    if dry:
        print("\n--dry-run: nothing written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
