#!/usr/bin/env python3
"""Load convo.csv into the `convoquestion` table for the Conversation page.

    ./.venv/bin/python import_convo.py [convo.csv]

Columns: ordinal,text,audience,depth. depth is light, medium or deep; audience
is one of AUDIENCES below. Other values load untagged, with a warning. Wipes and rebuilds `convoquestion` only,
carrying across the rows you removed in the app (matched on text).
"""
from __future__ import annotations

import csv
import pathlib
import sys
from collections import Counter

from sqlmodel import Session, create_engine, delete, select

from ledger_app.core.models import ConvoQuestion  # noqa: E402
from ledger_app.core.paths import db_path  # noqa: E402

APP = pathlib.Path(__file__).resolve().parents[2] / "ledger_app"
ENGINE = create_engine(f"sqlite:///{db_path()}")
AUDIENCES = {"new-people", "dating", "couples", "long-distance", "friends",
             "life", "love", "self", "childhood", "philosophy", "journal",
             "funny", "would-you-rather", "never-have-i-ever", "this-or-that"}
DEPTHS = {"light", "medium", "deep"}


def main() -> int:
    path = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else pathlib.Path(__file__).resolve().parents[2] / "csv" / "convo.csv")
    if not path.exists():
        print(f"no such file: {path}")
        return 2

    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            text = (r.get("text") or "").strip()
            if not text:
                continue
            aud = (r.get("audience") or "").strip().lower()
            dep = (r.get("depth") or "").strip().lower()
            ordv = (r.get("ordinal") or "").strip()
            rows.append(dict(
                ordinal=int(ordv) if ordv.isdigit() else None,
                text=text,
                audience=aud if aud in AUDIENCES else "",
                depth=dep if dep in DEPTHS else "",
            ))
    if not rows:
        print("parsed 0 questions")
        return 1
    untagged = [r["text"] for r in rows if not r["audience"] or not r["depth"]]
    if untagged:
        print(f"warning: {len(untagged)} rows with a missing or unknown audience or depth, "
              f"first: {untagged[0][:60]}")

    with Session(ENGINE) as s:
        dropped = {q.text for q in s.exec(select(ConvoQuestion)).all()
                   if q.dismissed}
        s.exec(delete(ConvoQuestion))
        for r in rows:
            s.add(ConvoQuestion(**r, dismissed=r["text"] in dropped))
        s.commit()
        n = len(s.exec(select(ConvoQuestion)).all())
    print(f"wrote {n} questions, {len(dropped)} still removed")
    print(" audience:", dict(Counter(r["audience"] for r in rows)))
    print(" depth:   ", dict(Counter(r["depth"] for r in rows)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
