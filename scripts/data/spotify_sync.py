#!/usr/bin/env python3
"""Mirror Spotify playlists and their tracks into the ledger database.

    ./ledger_app/.venv/bin/python spotify_sync.py --auth      # once, opens a browser
    ./ledger_app/.venv/bin/python spotify_sync.py --whoami
    ./ledger_app/.venv/bin/python spotify_sync.py --sync      # dry run
    ./ledger_app/.venv/bin/python spotify_sync.py --sync --apply

Authorization Code flow. The refresh token goes into `.env`; development-mode
apps expire it after 180 days, so `--auth` has to be re-run about twice a year.

Read-only. Nothing here writes to Spotify — creating and editing playlists is a
separate script, so a sync can never damage an account.
"""
from __future__ import annotations

import base64
import http.server
import json
import pathlib
import secrets
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime

from sqlmodel import Session, create_engine, delete, select   # noqa: E402
from ledger_app.core.models import Playlist, PlaylistTrack, Track  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parents[2]
ENV = HERE / ".env"
ENGINE = create_engine(f"sqlite:///{HERE / 'ledger_app' / 'ledger.db'}")
APPLY = "--apply" in sys.argv
API = "https://api.spotify.com/v1"

# The modify scopes exist for spotify_push.py. This script still issues no write
# calls — but note the guarantee moved: it used to be enforced by the token
# lacking the scope, and is now enforced only by this file containing no writes.
SCOPES = ("playlist-read-private playlist-read-collaborative "
          "user-library-read user-top-read "
          "playlist-modify-private playlist-modify-public")


def env() -> dict:
    out = {}
    if ENV.exists():
        for line in ENV.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
    return out


def set_env(key: str, value: str) -> None:
    lines = ENV.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        if line.startswith(f"{key}="):
            lines[i] = f"{key}={value}"
            break
    else:
        lines.append(f"{key}={value}")
    ENV.write_text("\n".join(lines) + "\n", encoding="utf-8")


def basic_auth() -> str:
    e = env()
    raw = f"{e['SPOTIFY_CLIENT_ID']}:{e['SPOTIFY_CLIENT_SECRET']}".encode()
    return base64.b64encode(raw).decode()


def token_request(data: dict) -> dict:
    req = urllib.request.Request(
        "https://accounts.spotify.com/api/token",
        data=urllib.parse.urlencode(data).encode(),
        headers={"Authorization": f"Basic {basic_auth()}",
                 "Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.load(r)


# ---- one-time consent ------------------------------------------------------
def authorize() -> None:
    e = env()
    state = secrets.token_urlsafe(16)
    url = "https://accounts.spotify.com/authorize?" + urllib.parse.urlencode({
        "client_id": e["SPOTIFY_CLIENT_ID"], "response_type": "code",
        "redirect_uri": e["SPOTIFY_REDIRECT_URI"], "scope": SCOPES,
        "state": state, "show_dialog": "false"})
    got: dict = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            got.update({k: v[0] for k, v in q.items()})
            ok = got.get("state") == state and "code" in got
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"<h2>Done. Close this tab.</h2>" if ok
                             else b"<h2>Authorisation failed.</h2>")

        def log_message(self, *a):
            pass

    port = int(urllib.parse.urlparse(e["SPOTIFY_REDIRECT_URI"]).port or 8888)
    server = http.server.HTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print("Open this URL and approve:\n")
    print(url + "\n")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    deadline = time.time() + 300
    while "code" not in got and time.time() < deadline:
        time.sleep(0.5)
    server.shutdown()
    if "code" not in got:
        sys.exit("no code received within 5 minutes")
    if got.get("state") != state:
        sys.exit("state mismatch — refusing the response")
    tok = token_request({"grant_type": "authorization_code", "code": got["code"],
                         "redirect_uri": e["SPOTIFY_REDIRECT_URI"]})
    set_env("SPOTIFY_REFRESH_TOKEN", tok["refresh_token"])
    print(f"refresh token stored in .env; scopes granted: {tok.get('scope', '?')}")


def access_token() -> str:
    e = env()
    if not e.get("SPOTIFY_REFRESH_TOKEN"):
        sys.exit("no SPOTIFY_REFRESH_TOKEN — run with --auth first")
    tok = token_request({"grant_type": "refresh_token",
                         "refresh_token": e["SPOTIFY_REFRESH_TOKEN"]})
    if tok.get("refresh_token"):          # Spotify sometimes rotates it
        set_env("SPOTIFY_REFRESH_TOKEN", tok["refresh_token"])
    return tok["access_token"]


# ---- reading ---------------------------------------------------------------
def get(path: str, token: str, **params):
    url = f"{API}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    for attempt in range(6):
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as ex:
            if ex.code == 429:
                # Spotify's rolling window; the header is authoritative
                wait = int(ex.headers.get("Retry-After", "2")) + 1
                print(f"    rate limited, waiting {wait}s")
                time.sleep(wait)
                continue
            raise
    raise RuntimeError(f"gave up on {path} after repeated 429s")


def paged(path: str, token: str, limit: int = 50, **params):
    """Walk an offset-paginated endpoint. 50 is the API maximum for these."""
    offset = 0
    while True:
        page = get(path, token, limit=limit, offset=offset, **params)
        for item in page.get("items", []):
            # /me/playlists returns null entries and partial objects for
            # playlists the account can see but not read. Skip rather than
            # crash on a missing key later.
            if item:
                yield item
        if not page.get("next"):
            return
        offset += limit


def whoami() -> None:
    token = access_token()
    me = get("/me", token)
    print(f"user: {me.get('display_name')}  id={me['id']}  country={me.get('country')}")
    print(f"followers: {(me.get('followers') or {}).get('total')}")
    lists = list(paged("/me/playlists", token))
    print(f"playlists visible: {len(lists)}")
    for p in lists[:12]:
        total = (p.get("items") or {}).get("total", 0)
        print(f"  {total:5d}  {(p.get('name') or '(unnamed)')[:44]:46s} "
              f"{'public' if p.get('public') else 'private'}")
    if len(lists) > 12:
        print(f"  … and {len(lists) - 12} more")
    sizes = sorted(((p.get("items") or {}).get("total", 0)) for p in lists)
    print(f"track counts: min {sizes[0]}, median {sizes[len(sizes)//2]}, max {sizes[-1]}")
    print(f"playlists over 30 tracks: {sum(1 for n in sizes if n > 30)}")


# Artist genres are not available to this app: /artists (batch) returns 403 and
# /artists/{id} returns "genres": null, alongside Spotify's
# withdrawal of audio-features and recommendations. Track.genres therefore stays
# empty and any vibe signal has to come from outside Spotify.


def sync() -> None:
    token = access_token()
    me = get("/me", token)
    print(f"{'APPLY' if APPLY else 'DRY RUN'} — reading playlists for {me['id']}")

    playlists = list(paged("/me/playlists", token))
    print(f"{len(playlists)} playlists\n")

    collected = []
    artist_ids: list[str] = []
    skipped = []
    for p in playlists:
        if not p.get("id"):
            continue
        try:
            # /items, not /tracks: the tracks sub-resource now returns 403, and
            # the parent object carries `items: {href, total}` where it used to
            # carry `tracks`.
            items = list(paged(f"/playlists/{p['id']}/items", token, limit=100))
        except urllib.error.HTTPError as e:
            # someone else's playlist, or a Spotify-generated one: readable in
            # the list, forbidden in detail
            skipped.append((p.get("name") or "(unnamed)",
                            (p.get("owner") or {}).get("id", "?"), e.code))
            continue
        tracks = []
        for pos, it in enumerate(items):
            # Three renames in one response family: the parent's `tracks` is
            # `items`, the sub-resource is /items not /tracks, and each entry
            # nests the track under `item` rather than `track`.
            t = it.get("item") or it.get("track") or {}
            if t.get("type") not in (None, "track"):
                continue                      # episodes live here too
            if not t.get("id"):
                continue          # local files and podcast episodes have no id
            artist_ids += [a["id"] for a in t.get("artists", [])]
            tracks.append({
                "pos": pos, "spotify_id": t["id"], "name": t["name"],
                "artists": ", ".join(a["name"] for a in t.get("artists", [])),
                "album": (t.get("album") or {}).get("name", ""),
                "year": ((t.get("album") or {}).get("release_date") or "")[:4],
                "duration_ms": t.get("duration_ms") or 0,
                "artist_ids": [a["id"] for a in t.get("artists", [])],
                "added_at": it.get("added_at") or "",
            })
        collected.append((p, tracks))
        print(f"  {len(tracks):5d}  {(p.get('name') or '(unnamed)')[:46]}")

    if skipped:
        print(f"\n{len(skipped)} not readable (owned elsewhere or "
              f"Spotify-generated):")
        for name, owner, code in skipped:
            print(f"  {code}  {name[:40]:42s} owner={owner}")

    print(f"\n{len(collected)} playlists, "
          f"{sum(len(t) for _p, t in collected)} track rows, "
          f"{len({a for _p, ts in collected for t in ts for a in t['artist_ids']})} artists")

    if not APPLY:
        print("\nNothing written. Re-run with --apply.")
        return

    with Session(ENGINE) as s:
        seen_playlists = []
        for p, tracks in collected:
            row = s.exec(select(Playlist)
                         .where(Playlist.spotify_id == p["id"])).first()
            if not row:
                row = Playlist(spotify_id=p["id"])
            if row.dismissed:
                continue          # hidden on purpose; a sync does not argue
            row.name = p["name"]
            row.description = p.get("description") or ""
            row.owner = (p.get("owner") or {}).get("id", "")
            row.public = bool(p.get("public"))
            row.collaborative = bool(p.get("collaborative"))
            row.total_tracks = len(tracks)
            row.snapshot_id = p.get("snapshot_id") or ""
            row.synced_at = datetime.now()
            s.add(row)
            s.flush()
            seen_playlists.append(row.id)

            s.exec(delete(PlaylistTrack).where(PlaylistTrack.playlist_id == row.id))
            for t in tracks:
                tr = s.exec(select(Track)
                            .where(Track.spotify_id == t["spotify_id"])).first()
                if not tr:
                    tr = Track(spotify_id=t["spotify_id"])
                tr.name = t["name"]
                tr.artists = t["artists"]
                tr.album = t["album"]
                try:
                    tr.year = int(t["year"]) if t["year"] else None
                except ValueError:
                    tr.year = None
                tr.duration_ms = t["duration_ms"]
                # left empty on purpose: see the note above artist genres
                if t["added_at"]:
                    try:
                        tr.added_at = datetime.fromisoformat(
                            t["added_at"].replace("Z", "+00:00")).replace(tzinfo=None)
                    except ValueError:
                        pass
                s.add(tr)
                s.flush()
                s.add(PlaylistTrack(playlist_id=row.id, track_id=tr.id,
                                    position=t["pos"]))
        s.commit()
        print(f"wrote {len(seen_playlists)} playlists, "
              f"{len(s.exec(select(Track)).all())} tracks")


if __name__ == "__main__":
    if "--auth" in sys.argv:
        authorize()
    elif "--whoami" in sys.argv:
        whoami()
    elif "--sync" in sys.argv:
        sync()
    else:
        print(__doc__)
