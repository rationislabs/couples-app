#!/usr/bin/env python3
"""Tag tracks with Last.fm tags, then work out which of your playlists each one
sounds like.

    ./hearth/.venv/bin/python vibe_tag.py --tags            # fetch, cached
    ./hearth/.venv/bin/python vibe_tag.py --profile         # what each playlist is made of
    ./hearth/.venv/bin/python vibe_tag.py --vibes --apply   # label every track
    ./hearth/.venv/bin/python vibe_tag.py --suggest Whiskey # tracks that belong there

Needs `LASTFM_API_KEY` in `.env` — last.fm/api/account/create, read-only calls
need the key alone (no signing, no user auth).

Why this shape: Spotify serves this app no genres and no audio features, so the
objective signal comes from Last.fm. What a "vibe" *means* is not in Last.fm
either — it is in your 78 playlists, which are 2440 tracks you already sorted by
hand. So a vibe is defined as "resembles the tag profile of playlist X", learned
from your own filing rather than invented.
"""
from __future__ import annotations

import json
import math
import os
import pathlib
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter

from sqlmodel import Session, create_engine, select      # noqa: E402
from hearth.core.models import Playlist, PlaylistTrack, Track   # noqa: E402
from hearth.core.paths import db_path, json_dir  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parents[2]
ENGINE = create_engine(f"sqlite:///{db_path()}")
CACHE = json_dir() / "lastfm-cache.json"
CACHE.parent.mkdir(parents=True, exist_ok=True)     # json/ is gitignored, so absent on a clone
API = "https://ws.audioscrobbler.com/2.0/"
APPLY = "--apply" in sys.argv
TOP_TAGS = 8          # per track; beyond this the tail is noise
MIN_TAG_COUNT = 10    # Last.fm returns a 0-100 count; below this is one person's opinion
MIN_PROFILE_TRACKS = 8
"""A playlist needs this many *tagged* tracks before it gets a profile.
`Brutalize` had 1 of 30 tagged and still produced a confident-looking
progressive-metal profile — one song deciding what a 30-song playlist means."""

# Playlists named after a band or an instrument are collections, not vibes. Left
# in the vocabulary they swallow every track by that artist regardless of mood.
# Lowercased playlist names; add your own.
NOT_A_VIBE = {"my shazam tracks"}

# Tags that describe cataloguing rather than sound. They dominate raw tag lists
# and make every playlist look alike, so they never reach a profile.
STOP_TAGS = {
    "seen live", "favorites", "favourites", "favorite songs", "spotify",
    "albums i own", "vinyl", "my music", "awesome", "love", "beautiful",
    "favorite", "best", "good", "great", "songs", "music", "male vocalists",
    "female vocalists", "under 2000 listeners", "usa", "american", "british",
    "german", "swedish", "canadian", "australian", "polish", "japanese",
    "10s", "00s", "90s", "80s", "70s", "60s", "50s", "20s",
    "2010s", "2000s", "1990s", "1980s", "1970s", "1960s",
}


def env(key: str) -> str:
    if v := os.environ.get(key):
        return v
    f = HERE / ".env"
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1].strip()
    return ""


def load_cache() -> dict:
    return json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}


def save_cache(c: dict) -> None:
    CACHE.write_text(json.dumps(c, indent=0, ensure_ascii=False, sort_keys=True),
                     encoding="utf-8")


def call(method: str, **params) -> dict:
    key = env("LASTFM_API_KEY")
    if not key:
        sys.exit("no LASTFM_API_KEY in .env — get one at last.fm/api/account/create")
    q = urllib.parse.urlencode({**params, "method": method, "api_key": key,
                                "format": "json", "autocorrect": "1"})
    for attempt in range(4):
        try:
            req = urllib.request.Request(API + "?" + q,
                                         headers={"User-Agent": "hearth/1.0"})
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503):
                time.sleep(2 * (attempt + 1))
                continue
            raise
        except (urllib.error.URLError, TimeoutError):
            time.sleep(2 * (attempt + 1))
    return {}


def clean_track_name(name: str) -> str:
    """Strip Spotify's release furniture before asking Last.fm.

    197 of 2440 names carry something like " - Remastered 2009", which Last.fm's
    autocorrect does not undo — they would all fall through to the weaker
    artist-level tags for no reason.
    """
    n = re.sub(r"\s*-\s*(?:\d{4}\s+)?(?:Remaster(?:ed)?|Remastered Version|"
               r"Radio Edit|Single Version|Album Version|Mono|Stereo|Live|"
               r"Bonus Track|Deluxe(?: Edition)?)(?:\s+\d{4})?\s*$", "", name,
               flags=re.I)
    n = re.sub(r"\s*[\(\[](?:feat\.?|ft\.?|with)\s[^\)\]]*[\)\]]", "", n, flags=re.I)
    n = re.sub(r"\s*[\(\[](?:Live|Remaster(?:ed)?[^\)\]]*|\d{4}\s+Remaster[^\)\]]*)"
               r"[\)\]]\s*$", "", n, flags=re.I)
    return n.strip() or name.strip()


def clean(tags: list[dict]) -> list[str]:
    """Strongest tags first, cataloguing tags dropped."""
    out = []
    for t in tags:
        name = (t.get("name") or "").strip().lower()
        try:
            count = int(t.get("count") or 0)
        except (TypeError, ValueError):
            count = 0
        if not name or name in STOP_TAGS or count < MIN_TAG_COUNT:
            continue
        out.append(name)
    return out[:TOP_TAGS]


def fetch_tags() -> None:
    """Track tags first, artist tags as the fallback. Obscure tracks have none of
    their own, and an artist's tags are a decent stand-in; `tag_source` records
    which one a row actually got so the difference stays visible."""
    cache = load_cache()
    with Session(ENGINE) as s:
        rows = s.exec(select(Track)).all()
        todo = [t for t in rows if not t.tags and f"t:{t.id}" not in cache]
        print(f"{len(rows)} tracks, {len(todo)} still need tags "
              f"({len(cache)} cached)")

        for i, t in enumerate(todo, 1):
            artist = t.artists.split(",")[0].strip()
            key = f"t:{t.id}"
            got, source = [], "none"
            r = call("track.gettoptags", artist=artist,
                     track=clean_track_name(t.name))
            got = clean(((r.get("toptags") or {}).get("tag")) or [])
            if got:
                source = "track"
            else:
                ak = f"a:{artist.lower()}"
                if ak in cache:
                    got, source = cache[ak], "artist"
                else:
                    r = call("artist.gettoptags", artist=artist)
                    got = clean(((r.get("toptags") or {}).get("tag")) or [])
                    cache[ak] = got
                    source = "artist" if got else "none"
            cache[key] = got
            t.tags = ", ".join(got)
            t.tag_source = source
            s.add(t)
            time.sleep(0.2)                      # Last.fm asks for <5 req/sec
            if i % 50 == 0:
                s.commit()
                save_cache(cache)
                print(f"  …{i}/{len(todo)}")
        s.commit()
    save_cache(cache)
    with Session(ENGINE) as s:
        rows = s.exec(select(Track)).all()
        by = Counter(t.tag_source or "none" for t in rows)
        print(f"\ntagged: track {by['track']}, artist {by['artist']}, none {by['none']}")


def playlist_profiles(s: Session) -> tuple[dict[str, Counter], dict[str, float]]:
    """A playlist's profile is how often each tag appears across its tracks,
    weighted down by how common that tag is everywhere (plain TF-IDF). Without
    the IDF half, "rock" wins every playlist and nothing is distinguishable."""
    tracks = {t.id: t for t in s.exec(select(Track)).all()}
    lists = {p.id: p for p in s.exec(select(Playlist)).all() if not p.dismissed}
    members: dict[int, list[Track]] = {}
    for m in s.exec(select(PlaylistTrack)).all():
        t = tracks.get(m.track_id)
        if t and t.tags and m.playlist_id in lists:
            members.setdefault(m.playlist_id, []).append(t)

    doc_freq: Counter = Counter()
    for pid, ts in members.items():
        for tag in {x for t in ts for x in t.tags.split(", ") if x}:
            doc_freq[tag] += 1
    n = max(1, len(members))
    idf = {tag: math.log(n / (1 + df)) + 1 for tag, df in doc_freq.items()}

    profiles: dict[str, Counter] = {}
    skipped: list[tuple[str, int]] = []
    for pid, ts in members.items():
        name = lists[pid].name
        if name.lower() in NOT_A_VIBE:
            skipped.append((name, len(ts)))
            continue
        if len(ts) < MIN_PROFILE_TRACKS:
            skipped.append((name, len(ts)))
            continue
        c: Counter = Counter()
        for t in ts:
            for rank, tag in enumerate(x for x in t.tags.split(", ") if x):
                c[tag] += (1.0 / (1 + rank)) * idf.get(tag, 1.0)
        if c:
            profiles[name] = c
    playlist_profiles.skipped = skipped      # for the report, not the maths
    return profiles, idf


def vector(tags: list[str], idf: dict[str, float]) -> Counter:
    c: Counter = Counter()
    for rank, tag in enumerate(tags):
        c[tag] += (1.0 / (1 + rank)) * idf.get(tag, 1.0)
    return c


def cosine(a: Counter, b: Counter) -> float:
    if not a or not b:
        return 0.0
    dot = sum(v * b.get(k, 0.0) for k, v in a.items())
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


def show_profiles(limit: int = 12) -> None:
    with Session(ENGINE) as s:
        profiles, _idf = playlist_profiles(s)
    if not profiles:
        sys.exit("no tags yet — run with --tags first")
    print(f"{len(profiles)} playlists with a tag profile\n")
    for name in sorted(profiles, key=lambda n: -sum(profiles[n].values()))[:limit]:
        top = ", ".join(t for t, _w in profiles[name].most_common(6))
        print(f"  {name[:26]:28s} {top}")
    if len(profiles) > limit:
        print(f"  … and {len(profiles) - limit} more")


def label_vibes() -> None:
    """Every track gets the playlist name its tags most resemble, plus the score.

    A track already sitting in a playlist is scored against every *other*
    playlist too — that is the point. A low best-score means "this fits nothing
    you have", which is a useful answer, not a failure.
    """
    with Session(ENGINE) as s:
        profiles, idf = playlist_profiles(s)
        if not profiles:
            sys.exit("no tags yet — run with --tags first")
        rows = [t for t in s.exec(select(Track)).all() if t.tags]
        print(f"{'APPLY' if APPLY else 'DRY RUN'} — scoring {len(rows)} tagged "
              f"tracks against {len(profiles)} playlists")
        hits: Counter = Counter()
        weak = 0
        for t in rows:
            v = vector([x for x in t.tags.split(", ") if x], idf)
            best, score = "", 0.0
            for name, prof in profiles.items():
                c = cosine(v, prof)
                if c > score:
                    best, score = name, c
            if score < 0.15:
                weak += 1
            hits[best] += 1
            if APPLY:
                t.vibe, t.vibe_score = best, round(score, 4)
                s.add(t)
        if APPLY:
            s.commit()
    print(f"\nweak matches (<0.15): {weak}")
    print("most common vibes:")
    for name, n in hits.most_common(12):
        print(f"  {n:5d}  {name}")
    if not APPLY:
        print("\nNothing written. Re-run with --apply.")


def suggest_rows(target: str, count: int = 20) -> tuple[str, list[tuple[float, object]]]:
    """(playlist name, [(score, Track)]) for tracks that fit but are not in it.

    Shared by the report and the push so both agree on what "suggested" means —
    a second implementation would eventually disagree with the one you reviewed.
    """
    with Session(ENGINE) as s:
        profiles, idf = playlist_profiles(s)
        match = [n for n in profiles if n.lower() == target.lower()] or \
                [n for n in profiles if target.lower() in n.lower()]
        if not match:
            raise KeyError(f"no playlist matching {target!r}")
        name = match[0]
        prof = profiles[name]
        lists = {p.id: p.name for p in s.exec(select(Playlist)).all()}
        pid = next(i for i, n in lists.items() if n == name)
        already = {m.track_id for m in s.exec(select(PlaylistTrack)
                                              .where(PlaylistTrack.playlist_id == pid)).all()}
        scored = []
        for t in s.exec(select(Track)).all():
            if t.id in already or not t.tags:
                continue
            c = cosine(vector([x for x in t.tags.split(", ") if x], idf), prof)
            scored.append((c, t))
        scored.sort(key=lambda x: -x[0])
        return name, scored[:count]


def suggest(target: str, count: int = 20) -> None:
    """Tracks from anywhere in the library that fit `target` better than most —
    excluding the ones already in it. This is the curation primitive."""
    with Session(ENGINE) as s:
        profiles, idf = playlist_profiles(s)
        match = [n for n in profiles if n.lower() == target.lower()] or \
                [n for n in profiles if target.lower() in n.lower()]
        if not match:
            sys.exit(f"no playlist matching {target!r}. "
                     f"Try one of: {', '.join(sorted(profiles)[:8])}")
        name = match[0]
        prof = profiles[name]
        lists = {p.id: p.name for p in s.exec(select(Playlist)).all()}
        pid = next(i for i, n in lists.items() if n == name)
        already = {m.track_id for m in s.exec(select(PlaylistTrack)
                                              .where(PlaylistTrack.playlist_id == pid)).all()}
        scored = []
        for t in s.exec(select(Track)).all():
            if t.id in already or not t.tags:
                continue
            c = cosine(vector([x for x in t.tags.split(", ") if x], idf), prof)
            scored.append((c, t))
        scored.sort(key=lambda x: -x[0])
    print(f"{name}: {len(already)} tracks now. Closest {count} not in it:\n")
    for c, t in scored[:count]:
        print(f"  {c:.3f}  {t.name[:34]:36s} {t.artists[:24]:26s} {t.tags[:34]}")


if __name__ == "__main__":
    if "--tags" in sys.argv:
        fetch_tags()
    elif "--profile" in sys.argv:
        show_profiles()
    elif "--vibes" in sys.argv:
        label_vibes()
    elif "--suggest" in sys.argv:
        i = sys.argv.index("--suggest")
        if i + 1 >= len(sys.argv):
            sys.exit("--suggest needs a playlist name")
        suggest(sys.argv[i + 1])
    else:
        print(__doc__)
