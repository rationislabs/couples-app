#!/usr/bin/env python3
"""Add places to the Date Tracking wishlist, from a pasted list or from Takeout.

    ./ledger_app/.venv/bin/python import_places.py                      # dry run
    ./ledger_app/.venv/bin/python import_places.py --apply
    ./ledger_app/.venv/bin/python import_places.py --csv ~/Downloads --lists
    ./ledger_app/.venv/bin/python import_places.py --csv ~/Downloads --apply

Google Takeout is the only route that yields a whole saved list with its URLs.
Select `Saved` in Takeout and you get one CSV per list (`Title,Note,URL`); point
`--csv` at the folder or a single file. `--country` marks every row in that run.

A `maps.app.goo.gl` short link resolves to a canonical `/maps/place/...` URL whose
path carries the place name — no API key, no login, no browser. The canonical URL
is what gets stored: short links depend on shortener infrastructure Google has
been retiring, the long form does not.

Idempotent by place name. Re-running adopts new lines and leaves the rest alone.
"""
from __future__ import annotations

import csv
import io
import json
import pathlib
import re
import sys
import time
import urllib.parse
import urllib.request
import zipfile

from sqlmodel import Session, create_engine, select      # noqa: E402
from ledger_app.core.models import Place                      # noqa: E402

HERE = pathlib.Path(__file__).resolve().parents[2]
ENGINE = create_engine(f"sqlite:///{HERE / 'ledger_app' / 'ledger.db'}")
INBOX = HERE / "places-inbox.txt"
COUNTRIES = HERE / "json" / "place-countries.json"   # list name -> ISO-2
TAKEOUT = HERE / "takeout"                  # where every export lives
DOWNLOADS = pathlib.Path("~/Downloads").expanduser()
APPLY = "--apply" in sys.argv


def _arg(flag: str) -> str:
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else ""
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/126.0 Safari/537.36")


def name_from_canonical(url: str) -> str:
    """The place name out of a canonical `/maps/place/<City>,+<Name>,+…` URL.

    No network: the resolved URL already carries the truth. A one-field path is
    a pin with no name, so the whole field is the best available label.
    """
    m = re.search(r"/maps/place/([^/]+)", url or "")
    if not m:
        return ""
    parts = [p.strip() for p in
             urllib.parse.unquote(m.group(1).replace("+", " ")).split(",")]
    name = parts[1] if len(parts) > 1 and parts[1] else parts[0]
    # A pin on an unnamed plot puts an address here — "Mill Road 78",
    # "Springfield 71123". Those end in a house number or a postcode, while a
    # real name does not ("7burger", "220 Degrees", "3D Blacklight Minigolf"
    # all start with theirs). Reject the address so a hand label can win.
    return "" if re.search(r"\s\d[\d/ -]*$", name) else name


def resolve(url: str) -> tuple[str, str]:
    """Follow a short link. Returns (place name, canonical url)."""
    req = urllib.request.Request(url, headers={"User-Agent": UA}, method="HEAD")
    with urllib.request.urlopen(req, timeout=25) as r:
        final = r.url
    canonical = final.split("?")[0]
    return name_from_canonical(canonical), canonical


def parse_inbox() -> list[tuple[str, str, str, str]]:
    """(list name, label, url, country) per entry.

    A bare heading names the list. A `country: XX` line sets the ISO-2 marker for
    everything after it, so one file can hold several countries.
    """
    out, current, country = [], "Unsorted", ""
    for raw in INBOX.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"(?i)^country\s*:\s*([A-Za-z]{2})$", line)
        if m:
            country = m.group(1).upper()
            continue
        if not line.startswith("->"):
            current = line
            continue
        body = line[2:].strip()
        # a trailing "[AT]" overrides the running country for this one entry
        # a trailing "[AT]" overrides the running country for one entry; "[--]"
        # means the entry is an activity, not a place, so it gets none
        m = re.search(r"\s\[(--|[A-Za-z]{2})\](?=\s*$|\s*:|\s+https?://)", body)
        row_country = country
        if m:
            tag = m.group(1)
            row_country = "" if tag == "--" else tag.upper()
            body = (body[:m.start()] + body[m.end():]).strip()
        m = re.search(r"https?://\S+", body)
        url = m.group(0) if m else ""
        label = body[:m.start()].strip(" :—-") if m else body
        out.append((current, label, url, row_country))
    return out


def clean_title(t: str) -> str:
    """Takeout titles arrive with the author's own punctuation: surrounding
    quotes, leading and trailing dashes, doubled spaces."""
    t = re.sub(r"\s+", " ", t).strip()
    # Only a matching surrounding pair comes off. str.strip() would eat one end
    # of a name that quotes something inside it — Power Haus "the gym".
    for open_q, close_q in (('"', '"'), ("\u201c", "\u201d"), ("\u201e", "\u201c"), ("'", "'")):
        if len(t) > 1 and t.startswith(open_q) and t.endswith(close_q):
            t = t[1:-1].strip()
    return re.sub(r"^[-\u2013\u2014\s]+|[-\u2013\u2014\s]+$", "", t).strip()


def country_for(list_name: str, fallback: str) -> str:
    """`place-countries.json` maps a saved list to a country, because one list
    per country is how these are kept. An exact match wins, then a
    case-insensitive one, then --country."""
    if not COUNTRIES.exists():
        return fallback
    table = json.loads(COUNTRIES.read_text(encoding="utf-8"))
    if list_name in table:
        return table[list_name].upper()
    lower = {k.lower(): v for k, v in table.items()}
    return lower.get(list_name.lower(), fallback).upper()


def adopt_downloads(dest: pathlib.Path) -> list[pathlib.Path]:
    """Move any Takeout zip out of ~/Downloads into the takeout folder.

    One home for every export, so a refresh never reads a half-moved download
    and old exports stay next to each other.
    """
    if not DOWNLOADS.is_dir() or dest.resolve() == DOWNLOADS.resolve():
        return []
    dest.mkdir(parents=True, exist_ok=True)
    moved = []
    for f in sorted(DOWNLOADS.glob("*.zip")):
        if not f.name.lower().startswith("takeout"):
            continue
        target = dest / f.name
        if target.exists():
            target = dest / f"{f.stem}-{int(f.stat().st_mtime)}{f.suffix}"
        f.rename(target)
        moved.append(target)
    return moved


def _zip_csvs(z: pathlib.Path) -> list[tuple[str, str]]:
    with zipfile.ZipFile(z) as zf:
        names = [n for n in zf.namelist()
                 if n.lower().endswith(".csv") and "/saved/" in n.lower()]
        if not names:
            names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        return [(pathlib.PurePosixPath(n).stem, zf.read(n).decode("utf-8-sig"))
                for n in names]


def _csv_sources(target: pathlib.Path) -> list[tuple[str, str]]:
    """(list name, csv text) from a folder, one CSV, or one or more Takeout zips.

    Reading zips in place removes the unzip step, which is the step that gets
    skipped and leaves a stale folder beside a fresh download. Every zip is read,
    not just the newest: Takeout splits a large export into parts, and the CSVs
    can be in any of them. When two parts carry the same list, the longer copy
    wins.
    """
    if target.is_dir():
        for f in adopt_downloads(target):
            print(f"  moved {f.name} out of ~/Downloads")
        csvs = sorted(target.glob("*.csv")) + sorted(target.glob("**/Saved/*.csv"))
        out = [(f.stem, f.read_text(encoding="utf-8-sig")) for f in csvs]
        zips = [f for f in sorted(target.glob("*.zip"))
                if f.name.lower().startswith("takeout")]
        for z in zips:
            found = _zip_csvs(z)
            print(f"  {z.name}: {len(found)} lists")
            out += found
        best: dict[str, str] = {}
        for name, text in out:
            if name not in best or len(text) > len(best[name]):
                best[name] = text
        return sorted(best.items())
    if target.suffix == ".zip":
        return _zip_csvs(target)
    return [(target.stem, target.read_text(encoding="utf-8-sig"))]


def parse_csv(target: pathlib.Path, fallback: str) -> list[tuple[str, str, str, str]]:
    """Takeout's `Saved/<list>.csv`: Title, Note, URL. The file name is the list."""
    out = []
    for list_name, text in _csv_sources(target):
        country = country_for(list_name, fallback)
        for row in csv.DictReader(io.StringIO(text)):
            title = clean_title(row.get("Title") or "")
            if not title:
                continue
            out.append((list_name, title, (row.get("URL") or "").strip(), country))
    return out


def main() -> None:
    csv_target = _arg("--csv") or (str(TAKEOUT) if
                                   ("--lists" in sys.argv or "--takeout" in sys.argv)
                                   else "")
    if "--lists" in sys.argv and csv_target:
        # what is in the export, and which lists still need a country
        table = json.loads(COUNTRIES.read_text(encoding="utf-8")) if COUNTRIES.exists() else {}
        lower = {k.lower(): v for k, v in table.items()}
        rows = parse_csv(pathlib.Path(csv_target).expanduser(), "")
        seen: dict[str, int] = {}
        for list_name, *_ in rows:
            seen[list_name] = seen.get(list_name, 0) + 1
        print(f"{len(seen)} lists, {len(rows)} places\n")
        for name, n in sorted(seen.items(), key=lambda x: -x[1]):
            cc = table.get(name) or lower.get(name.lower()) or ""
            print(f"  {n:5d}  {name:36s} {cc or '← no country in place-countries.json'}")
        return

    if csv_target:
        entries = parse_csv(pathlib.Path(csv_target).expanduser(),
                            _arg("--country").upper())
        print(f"reading {csv_target}")
    else:
        entries = parse_inbox()
    print(f"{'APPLY' if APPLY else 'DRY RUN'} — {len(entries)} entries")
    resolved, failed = [], []
    for list_name, label, url, country in entries:
        name, canonical, note = label, url, ""
        if "goo.gl" in url:
            try:
                got, canonical = resolve(url)
            except Exception as e:
                failed.append((list_name, url, f"{type(e).__name__}: {e}"))
                continue
            time.sleep(0.3)
            # The resolved name wins. A hand label kept winning here, which is
            # how a row named after a city ended up linking to a pizzeria in
            # it: the row named a city, the link went to a restaurant. The label is
            # still worth keeping, as a note.
            if got:
                name, note = got, (label if label and label != got else "")
            elif label:
                name = label
        if not name:
            failed.append((list_name, url, "no name and no label"))
            continue
        resolved.append((list_name, name, canonical, country, note))

    by_list: dict[str, int] = {}
    for l, _n, _u, _c, _t in resolved:
        by_list[l] = by_list.get(l, 0) + 1
    print(f"resolved {len(resolved)}, failed {len(failed)}\n")
    for l in sorted(by_list):
        names = [f"{n}  [{c}]" if c else n for gl, n, _, c, _t in resolved if gl == l]
        print(f"  {l} ({by_list[l]})")
        for n in names:
            print(f"      {n}")
    if failed:
        print("\nfailed:")
        for l, u, why in failed:
            print(f"  {l:22s} {u[:44]:46s} {why[:60]}")

    if not APPLY:
        print("\nNothing written. Re-run with --apply.")
        return

    added = skipped = 0
    with Session(ENGINE) as s:
        for list_name, name, url, country, note in resolved:
            existing = s.exec(select(Place).where(Place.name == name)).first()
            if existing and existing.dismissed:
                # you removed it on purpose; a refresh does not argue
                skipped += 1
                continue
            if existing:
                # a re-run is how a country gets backfilled onto rows imported
                # before the marker existed
                if country and not existing.country:
                    existing.country = country
                    s.add(existing)
                skipped += 1
                continue
            s.add(Place(name=name, list_name=list_name, maps_url=url, country=country,
                        note=note,
                        source="maps" if "google.com/maps" in url else "manual"))
            added += 1
        s.commit()
    print(f"\nadded {added} places, {skipped} already there")


if __name__ == "__main__":
    main()
