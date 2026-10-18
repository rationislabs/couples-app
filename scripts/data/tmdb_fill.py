#!/usr/bin/env python3
"""Fill missing descriptions from TMDB, for every title that lacks one.

Dry run by default; nothing is written without --apply.

    ./.venv/bin/python tmdb_fill.py            # show what it would do
    ./.venv/bin/python tmdb_fill.py --apply    # write the confident matches
    ./.venv/bin/python tmdb_fill.py --review   # only list the ambiguous ones

Covers anime, anime films, movies and TV. Series are searched against /search/tv
first and films against /search/movie, each falling back to the other, because
anime in particular is split across both.

Matching is deliberately conservative. Many titles carry no year ("Predator",
"Contact"), and TMDB returns several plausible candidates for each. A wrong
synopsis is worse than a blank cell, so anything uncertain is left alone and
reported for you to resolve.

Data from TMDB. This product uses the TMDB API but is not endorsed or certified by TMDB.
"""
from __future__ import annotations

import datetime as dt
import difflib, json, os, pathlib, re, sys, time, urllib.parse, urllib.request

from sqlmodel import Session, create_engine, select
from ledger_app.core.models import Genre, Title, TitleGenre  # noqa: E402
from ledger_app.core.paths import db_path, json_dir  # noqa: E402

APP = pathlib.Path(__file__).resolve().parents[2] / "ledger_app"
ENGINE = create_engine(f"sqlite:///{db_path()}")
APPLY = "--apply" in sys.argv
REVIEW_ONLY = "--review" in sys.argv
CAP = 300
CACHE = json_dir() / "tmdb-cache.json"     # saves repeat API calls
AMBIG = json_dir() / "tmdb-ambiguous.json"  # candidates the app asks you to pick from
CACHE.parent.mkdir(parents=True, exist_ok=True)                 # json/ is gitignored, so absent on a clone

def load_cache() -> dict:
    return json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}

def genre_maps() -> dict[int, str]:
    out = {}
    for kind in ("movie", "tv"):
        url = f"https://api.themoviedb.org/3/genre/{kind}/list?language=en"
        req = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {token()}", "accept": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as r:
            for g in json.load(r).get("genres", []):
                out[g["id"]] = g["name"]
    return out

def token() -> str:
    if t := os.environ.get("TMDB_READ_TOKEN"):     # the container passes keys this way
        return t
    env = APP.parent / ".env"
    for line in (env.read_text(encoding="utf-8").splitlines() if env.exists() else []):
        if line.startswith("TMDB_READ_TOKEN="):
            return line.split("=", 1)[1].strip()
    sys.exit("no TMDB_READ_TOKEN in the environment or .env")

GENRES: dict[int, str] = {}
norm = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())
strip_year = lambda s: re.sub(r"\s*\(\d{4}\)\s*$", "", s)

def _hit(path: str, **params) -> list[dict]:
    url = f"https://api.themoviedb.org/3{path}?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token()}", "accept": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r).get("results", [])

def search(name: str, medium: str) -> tuple[list[dict], str | None]:
    m = re.search(r"^(.*?)\s*\((\d{4})\)\s*$", name)
    query, year = (m.group(1), m.group(2)) if m else (name, None)
    order = ["movie", "tv"] if medium in ("movie", "anime-film") else ["tv", "movie"]
    out: list[dict] = []
    for kind in order:
        p = {"query": query, "include_adult": "false"}
        if year:
            p["year" if kind == "movie" else "first_air_date_year"] = year
        try:
            res = _hit(f"/search/{kind}", **p)
        except Exception:
            res = []
        for r in res:
            r["_title"] = r.get("title") or r.get("name") or ""
            r["_year"] = ((r.get("release_date") or r.get("first_air_date") or "") or "")[:4]
            r["_orig"] = r.get("original_title") or r.get("original_name") or ""
            r["_votes"] = r.get("vote_count") or 0
            r["_kind"] = kind
        out += res
        if any(norm(r["_title"]) == norm(strip_year(name)) for r in res):
            break          # good enough; do not spend a second request
    return out, year

def choose(name: str, res: list[dict], year: str | None, medium: str = ""):
    """Pick a result, or explain why nothing is confident enough.

    For anime the medium itself disambiguates: an anime "Paprika" or "Redline" is
    the Japanese one, not the eight same-named live-action films. That is a fact
    about the row, not a guess about the title.
    """
    if not res:
        return None, "no results"
    if medium in ("anime", "anime-film"):
        ja = [r for r in res if r.get("original_language") == "ja"]
        if ja:
            res = ja
    bare = strip_year(name)
    exact = [r for r in res if norm(r["_title"]) == norm(bare)]
    if year:
        dated = [r for r in exact if r["_year"] == year] or [r for r in res if r["_year"] == year]
        if len(dated) == 1:
            return dated[0], "title+year"
        if dated:
            return dated[0], "year, first of several"
    if len(exact) == 1:
        return exact[0], "exact title, single match"
    if exact:
        withtext = [r for r in exact if (r.get("overview") or "").strip()]
        if len(withtext) == 1:
            return withtext[0], "exact title, one has a synopsis"
        # vote dominance: the Casablanca you mean has orders of magnitude more
        # votes than the other five films called Casablanca. Measured, not assumed.
        ranked = sorted(exact, key=lambda r: r["_votes"], reverse=True)
        if ranked[0]["_votes"] >= 200 and ranked[0]["_votes"] >= 5 * max(1, ranked[1]["_votes"]):
            return ranked[0], f"vote dominance ({ranked[0]['_votes']} vs {ranked[1]['_votes']})"
        yrs = ", ".join(f"{r['_year'] or '?'}:{r['_votes']}" for r in ranked[:4])
        return None, f"{len(exact)} same-title candidates ({yrs})"

    # near-miss titles: "Heavenly Delusion" is listed as "Tengoku Daimakyo",
    # "The Super Cube" as "Super Cube". Accept only when one candidate is clearly
    # closest and the rest are not.
    def score(r):
        a, b = norm(bare), norm(r["_title"])
        c = norm(r.get("_orig") or "")
        best = max(difflib.SequenceMatcher(None, a, b).ratio(),
                   difflib.SequenceMatcher(None, a, c).ratio() if c else 0)
        if a and (a in b or b in a):
            best = max(best, 0.90)
        return best
    scored = sorted(((score(r), r) for r in res), key=lambda x: -x[0])
    if scored and scored[0][0] >= 0.72:
        top, second = scored[0], (scored[1] if len(scored) > 1 else (0, None))
        if top[0] - second[0] >= 0.08 or len(scored) == 1:
            return top[1], f"near title match ({top[0]:.2f})"
    return None, f"no exact title match (best: {res[0]['_title']} {res[0]['_year'] or '?'})"

def dates_pass() -> None:
    """Fill `release_date` for anything that may not be out yet.

        ./.venv/bin/python tmdb_fill.py --dates
        ./.venv/bin/python tmdb_fill.py --dates --apply

    Scoped to titles with no date and either no year or a year from last year
    on, because "is this out yet" is only a live question for those. A 1959 film
    does not need a lookup to answer it.
    """
    global GENRES
    GENRES = genre_maps()
    cutoff = dt.date.today().year - 1
    every = "--all" in sys.argv
    with Session(ENGINE) as s:
        todo = [(t.name, t.medium) for t in s.exec(select(Title)).all()
                if t.release_date is None
                and (every or t.year is None or t.year >= cutoff)]
    scope = "titles with no date" if every else "titles that could still be unreleased"
    print(f"{'APPLY' if APPLY else 'DRY RUN'} — {len(todo)} {scope}")

    found, unknown = [], []
    for i, (name, medium) in enumerate(todo, 1):
        try:
            res, year = search(name, medium)
            pick, why = choose(name, res, year, medium)
        except Exception as e:
            unknown.append((name, str(e)[:50])); continue
        raw = (pick or {}).get("release_date") or (pick or {}).get("first_air_date") or ""
        try:
            when = dt.date.fromisoformat(raw)
        except ValueError:
            unknown.append((name, why if not pick else "TMDB has no date yet")); continue
        found.append((name, when, pick["_title"]))
        time.sleep(0.05)
        if i % 40 == 0: print(f"  …{i}/{len(todo)}")

    today = dt.date.today()
    ahead = sorted((w, n) for n, w, _ in found if w > today)
    print(f"\ndated {len(found)}, no date {len(unknown)}")
    if ahead:
        print(f"\nnot out yet ({len(ahead)}):")
        for when, name in ahead:
            print(f"  {when}  {name}")
    if unknown:
        print(f"\nno date from TMDB ({len(unknown)}) — type one in on the page:")
        for name, why in unknown[:12]:
            print(f"  {name[:38]:40s} {why[:44]}")
    if not APPLY:
        print("\nNothing written. Re-run with --apply."); return

    cache = load_cache()
    with Session(ENGINE) as s:
        for name, when, _match in found:
            t = s.exec(select(Title).where(Title.name == name)).first()
            if not t:
                continue
            t.release_date = when
            s.add(t)
            cache.setdefault(name, {})["release_date"] = when.isoformat()
        s.commit()
    CACHE.write_text(json.dumps(cache, indent=2, ensure_ascii=False, sort_keys=True),
                     encoding="utf-8")
    print(f"\nwrote {len(found)} dates to the database and {CACHE.name}.")


def main() -> None:
    token()  # fail before any work; a hand pick from the app needs no token
    global GENRES
    GENRES = genre_maps()
    print(f"TMDB genre vocabulary: {len(GENRES)} genres")
    with Session(ENGINE) as s:
        have_genres = {tg.title_id for tg in s.exec(select(TitleGenre)).all()}
        todo = [(t.name, t.medium) for t in s.exec(select(Title)).all()
                if not t.description or not t.year or t.id not in have_genres]
    by_med: dict[str, int] = {}
    for _, m in todo: by_med[m] = by_med.get(m, 0) + 1
    print(f"{'APPLY' if APPLY else 'DRY RUN'} — {len(todo)} titles missing a description")
    print("  " + "  ".join(f"{k}={v}" for k, v in sorted(by_med.items())) + "\n")

    picked, skipped, failed = [], [], []
    for i, (name, medium) in enumerate(todo, 1):
        try:
            res, year = search(name, medium)
            pick, why = choose(name, res, year, medium)
        except Exception as e:
            failed.append((name, str(e)[:60])); continue
        if pick and (pick.get("overview") or "").strip():
            alt = pick.get("_orig") or ""
            if norm(alt) in (norm(pick["_title"]), norm(strip_year(name))):
                alt = ""
            picked.append((name, pick["_title"], pick["_year"], pick["_kind"],
                           pick["overview"].strip()[:CAP], why, alt,
                           [GENRES.get(g) for g in (pick.get("genre_ids") or []) if GENRES.get(g)]))
        elif pick:
            # still worth its genres and year even without a synopsis
            picked.append((name, pick["_title"], pick["_year"], pick["_kind"], "", "no synopsis",
                           pick.get("_orig") or "",
                           [GENRES.get(g) for g in (pick.get("genre_ids") or []) if GENRES.get(g)]))
        else:
            # strongest first: TMDB returns by popularity, which buries the
            # 3247-vote Ben-Hur under the 1824-vote remake.
            skipped.append((name, medium, why,
                            sorted(res, key=lambda r: -r["_votes"])[:6]))
        time.sleep(0.05)
        if i % 50 == 0: print(f"  …{i}/{len(todo)}")

    print(f"\nconfident matches : {len(picked)}")
    print(f"needs review      : {len(skipped)}")
    print(f"request errors    : {len(failed)}")
    hit_by_med: dict[str, int] = {}
    for n, *_ in picked:
        m = dict(todo)[n]; hit_by_med[m] = hit_by_med.get(m, 0) + 1
    if hit_by_med:
        print("  matched by medium: " + "  ".join(f"{k}={v}" for k, v in sorted(hit_by_med.items())))

    if not REVIEW_ONLY and picked:
        print("\nsample of what would be filled:")
        for n, mt, my, kind, _, why, alt, _g in picked[:10]:
            tag = f"  ⟨{alt[:18]}⟩" if alt else ""
            print(f"  {n[:34]:36s} -> {mt[:26]:28s} {my or '?':4s} {kind:5s} [{why}]{tag}")
        if len(picked) > 10: print(f"  … and {len(picked)-10} more")
    if skipped:
        print("\nleft blank for you to resolve:")
        for n, m, why, _c in skipped[:18]:
            print(f"  {n[:36]:38s} ({m}) {why}")
        if len(skipped) > 18: print(f"  … and {len(skipped)-18} more")

    AMBIG.write_text(json.dumps(
        {n: {"medium": m, "why": why,
             "candidates": [{"title": r["_title"], "year": r["_year"] or "",
                             "kind": r["_kind"], "votes": r["_votes"],
                             "orig": r.get("_orig") or "",
                             "overview": (r.get("overview") or "").strip()[:CAP],
                             "genres": [GENRES[g] for g in (r.get("genre_ids") or [])
                                        if g in GENRES]}
                            for r in cands]}
         for n, m, why, cands in skipped if cands},
        indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    print(f"wrote {AMBIG.name} — {sum(1 for _n, _m, _w, c in skipped if c)} titles await a pick")

    if not APPLY:
        print("\nNothing written. Re-run with --apply."); return
    write_picked(picked)
    print(f"\nwrote {len(picked)} titles to the database and {CACHE.name}.")

def write_picked(picked: list[tuple]) -> int:
    """Write matches to the database and the cache. Shared by the CLI run and
    by a pick made in the app, so both land identically."""
    cache = load_cache()
    with Session(ENGINE) as s:
        known = {g.name: g for g in s.exec(select(Genre)).all()}
        linked = {(tg.title_id, tg.genre_id) for tg in s.exec(select(TitleGenre)).all()}
        for name, _, myear, _, overview, _, alt, genres in picked:
            t = s.exec(select(Title).where(Title.name == name)).first()
            if not t:
                continue
            if overview: t.description = overview[:CAP]
            if alt: t.alt_title = alt[:120]
            if myear and not t.year:
                try: t.year = int(myear)
                except ValueError: pass
            s.add(t); s.flush()
            for g in genres:
                if g not in known:
                    known[g] = Genre(name=g); s.add(known[g]); s.flush()
                if (t.id, known[g].id) not in linked:
                    s.add(TitleGenre(title_id=t.id, genre_id=known[g].id))
                    linked.add((t.id, known[g].id))
            entry = cache.setdefault(name, {})
            if overview: entry["description"] = overview[:CAP]
            if alt: entry["alt_title"] = alt[:120]
            if myear: entry["year"] = myear
            if genres: entry["genres"] = sorted(set(genres))
        s.commit()
    CACHE.write_text(json.dumps(cache, indent=2, ensure_ascii=False, sort_keys=True),
                     encoding="utf-8")
    return len(picked)

if __name__ == "__main__":
    dates_pass() if "--dates" in sys.argv else main()
