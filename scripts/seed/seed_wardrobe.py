#!/usr/bin/env python3
"""Placeholder wardrobe, so the outfit generator has something to deal.

Optional. There is no garment editor in the app yet, so this is the only way
to fill the wardrobe short of SQL.

Idempotent: every row is marked `placeholder=True` and matched by name, so
running this twice changes nothing, and clearing the placeholders once the real
wardrobe exists is one query:

    delete from garment where placeholder = 1

    ./hearth/.venv/bin/python scripts/seed/seed_wardrobe.py
"""
import pathlib
import sys


from sqlmodel import Session, select                       # noqa: E402

from hearth.core.models import Garment                      # noqa: E402
from hearth.core.state import ENGINE                        # noqa: E402

# (name, slot, season, formality, colour)
ITEMS = [
    ("Plain tee", "top", "warm", "casual", "white"),
    ("Striped tee", "top", "warm", "casual", "navy"),
    ("Oxford shirt", "top", "", "smart", "light blue"),
    ("Knit jumper", "top", "cold", "casual", "oatmeal"),
    ("Flannel shirt", "top", "cold", "casual", "green check"),
    ("Dark jeans", "bottom", "", "casual", "indigo"),
    ("Chinos", "bottom", "", "smart", "stone"),
    ("Shorts", "bottom", "warm", "casual", "khaki"),
    ("Corduroys", "bottom", "cold", "casual", "rust"),
    ("Denim jacket", "outer", "warm", "casual", "mid blue"),
    ("Wool coat", "outer", "cold", "smart", "charcoal"),
    ("Rain shell", "outer", "", "casual", "black"),
    ("White trainers", "shoes", "", "casual", "white"),
    ("Chelsea boots", "shoes", "cold", "smart", "brown"),
    ("Sandals", "shoes", "warm", "casual", "tan"),
    ("Watch", "accent", "", "", "steel"),
    ("Beanie", "accent", "cold", "casual", "grey"),
    ("Cap", "accent", "warm", "casual", "navy"),
]


def main() -> None:
    added = 0
    with Session(ENGINE) as s:
        for name, slot, season, formality, colour in ITEMS:
            if s.exec(select(Garment).where(Garment.name == name)).first():
                continue
            s.add(Garment(name=name, slot=slot, season=season,
                          formality=formality, colour=colour,
                          placeholder=True,
                          notes="placeholder — replace with the real thing"))
            added += 1
        s.commit()
        total = len(s.exec(select(Garment)).all())
    print(f"added {added} placeholder garments, {total} in the wardrobe")


if __name__ == "__main__":
    main()
