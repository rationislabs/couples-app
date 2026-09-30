#!/usr/bin/env python3
"""Write suggested tracks to Spotify. Dry run unless --apply.

    ./ledger_app/.venv/bin/python spotify_push.py --add Whiskey --count 10
    ./ledger_app/.venv/bin/python spotify_push.py --add Whiskey --count 10 --apply
    ./ledger_app/.venv/bin/python spotify_push.py --new "Whiskey v2" --from Whiskey --apply

Three rules this script will not break:

1. **Append only.** It never calls `PUT /playlists/{id}/tracks` (replace) and
   never DELETEs. Spotify has no undo and no version history, so a wrong replace
   is unrecoverable.
2. **Snapshot checked.** The playlist's `snapshot_id` is compared against the one
   stored at sync time; if the playlist moved since, it aborts and tells you to
   re-sync rather than writing into a changed target.
3. **--apply or nothing.** Every path prints exactly what it would send first.
"""
from __future__ import annotations

import json
import pathlib
import sys
import urllib.error
import urllib.parse
import urllib.request

from sqlmodel import Session, select                      # noqa: E402
import spotify_sync as SS                                 # noqa: E402
import vibe_tag as VT                                     # noqa: E402
from ledger_app.core.models import Playlist                    # noqa: E402

APPLY = "--apply" in sys.argv
BATCH = 100          # Spotify's hard cap per add request


def arg(flag: str, default: str = "") -> str:
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


def post(path: str, token: str, body: dict) -> dict:
    req = urllib.request.Request(
        SS.API + path, data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read()
        return json.loads(raw) if raw else {}


def require_write_scope(token: str) -> None:
    """Fail early and clearly rather than at the first write."""
    try:
        SS.get("/me", token)
    except urllib.error.HTTPError as e:
        sys.exit(f"token rejected ({e.code}) — re-run spotify_sync.py --auth")


def check_snapshot(s: Session, name: str, token: str) -> Playlist:
    row = s.exec(select(Playlist).where(Playlist.name == name)).first()
    if not row:
        sys.exit(f"{name!r} is not in the local database — run --sync first")
    live = SS.get(f"/playlists/{row.spotify_id}", token).get("snapshot_id", "")
    if row.snapshot_id and live and live != row.snapshot_id:
        sys.exit(f"{name!r} changed on Spotify since the last sync "
                 f"({row.snapshot_id[:12]}… -> {live[:12]}…). "
                 f"Re-run spotify_sync.py --sync --apply, then retry.")
    return row


def add_to(target: str, count: int) -> None:
    name, rows = VT.suggest_rows(target, count)
    if not rows:
        sys.exit(f"nothing to add to {name!r}")
    token = SS.access_token()
    require_write_scope(token)
    with Session(SS.ENGINE) as s:
        row = check_snapshot(s, name, token)
    print(f"{'APPLY' if APPLY else 'DRY RUN'} — append {len(rows)} tracks to {name!r}\n")
    for score, t in rows:
        print(f"  {score:.3f}  {t.name[:36]:38s} {t.artists[:26]:28s} {t.tags[:30]}")
    uris = [f"spotify:track:{t.spotify_id}" for _c, t in rows]
    if not APPLY:
        print(f"\nNothing sent. Re-run with --apply to append these {len(uris)}.")
        return
    sent = 0
    for i in range(0, len(uris), BATCH):
        chunk = uris[i:i + BATCH]
        post(f"/playlists/{row.spotify_id}/tracks", token, {"uris": chunk})
        sent += len(chunk)
    print(f"\nappended {sent} tracks to {name!r}. "
          f"Run spotify_sync.py --sync --apply to pick up the new snapshot.")


def new_from(new_name: str, source: str, count: int) -> None:
    """Create a fresh playlist from suggestions. The source is never touched —
    this is what "remake" means here, because a replace cannot be undone."""
    name, rows = VT.suggest_rows(source, count)
    token = SS.access_token()
    require_write_scope(token)
    me = SS.get("/me", token)["id"]
    print(f"{'APPLY' if APPLY else 'DRY RUN'} — create {new_name!r} "
          f"with {len(rows)} tracks modelled on {name!r}\n")
    for score, t in rows:
        print(f"  {score:.3f}  {t.name[:36]:38s} {t.artists[:26]}")
    if not APPLY:
        print("\nNothing sent. Re-run with --apply.")
        return
    made = post(f"/users/{urllib.parse.quote(me)}/playlists", token, {
        "name": new_name, "public": False,
        "description": f"Built from the tag profile of {name}. media-ledger."})
    pid = made["id"]
    uris = [f"spotify:track:{t.spotify_id}" for _c, t in rows]
    for i in range(0, len(uris), BATCH):
        post(f"/playlists/{pid}/tracks", token, {"uris": uris[i:i + BATCH]})
    print(f"\ncreated {new_name!r} ({pid}) with {len(uris)} tracks. "
          f"{name!r} was not modified.")


if __name__ == "__main__":
    n = int(arg("--count", "10"))
    if "--add" in sys.argv:
        add_to(arg("--add"), n)
    elif "--new" in sys.argv:
        src = arg("--from")
        if not src:
            sys.exit("--new needs --from <existing playlist>")
        new_from(arg("--new"), src, n)
    else:
        print(__doc__)
