"""Checks for spotify_sync.py that need no network.

A playlist deleted in Spotify stayed here forever, and a 429 with a
Retry-After of hours slept for hours inside a sync the app was waiting on.

    ./.venv/bin/python test_spotify.py
"""
import io
import os
import pathlib
import stat
import sys
import tempfile
import urllib.error

import _db  # first: never the real hearth.db

_db.migrate()

sys.argv = [sys.argv[0]]           # the script reads --apply from argv at import
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts" / "data"))
import spotify_sync as S                                     # noqa: E402
from sqlmodel import Session, select                         # noqa: E402

from hearth.core.models import Playlist, PlaylistTrack, Track  # noqa: E402


def test_a_playlist_gone_from_spotify_is_removed_with_its_tracks():
    with Session(S.ENGINE) as s:
        kept, gone = Playlist(spotify_id="zz-kept", name="kept"), Playlist(spotify_id="zz-gone", name="gone")
        t = Track(spotify_id="zz-track", name="song")
        s.add_all([kept, gone, t])
        s.flush()
        s.add_all([PlaylistTrack(playlist_id=kept.id, track_id=t.id, position=0),
                   PlaylistTrack(playlist_id=gone.id, track_id=t.id, position=0)])
        s.commit()
        assert S.forget_missing(s, {"zz-kept"}) == 1
        s.commit()
        assert [p.spotify_id for p in s.exec(select(Playlist)).all()] == ["zz-kept"]
        assert len(s.exec(select(PlaylistTrack)).all()) == 1
        assert s.exec(select(Track)).all(), "tracks stay: other playlists may hold them"


def test_a_long_rate_limit_stops_instead_of_sleeping():
    slept = []
    S.time.sleep = slept.append

    def limited(*a, **k):
        raise urllib.error.HTTPError("u", 429, "Too Many Requests", {"Retry-After": "3600"}, io.BytesIO())
    S.urllib.request.urlopen = limited
    try:
        S.get("/me", "token")
    except SystemExit as e:
        assert "again later" in str(e), e
    else:
        raise AssertionError("returned without data")
    assert not slept, f"slept {slept}"


def test_a_rotated_token_survives_without_a_dotenv():
    """The container has no .env: the rotated token goes under HEARTH_DATA_DIR
    and wins over the (now stale) SPOTIFY_REFRESH_TOKEN the container passed."""
    real_env = S.ENV
    S.ENV = pathlib.Path(tempfile.mkdtemp()) / ".env"          # absent
    os.environ["SPOTIFY_REFRESH_TOKEN"] = "old"
    try:
        S.set_env("SPOTIFY_REFRESH_TOKEN", "new")
        f = S.token_file()
        assert f.read_text().splitlines()[-1] == "new"
        assert stat.S_IMODE(f.stat().st_mode) == 0o600
        assert S.env()["SPOTIFY_REFRESH_TOKEN"] == "new"
    finally:
        S.ENV = real_env
        os.environ.pop("SPOTIFY_REFRESH_TOKEN", None)
        S.token_file().unlink(missing_ok=True)


def test_a_new_token_in_the_environment_beats_the_saved_rotation():
    """Re-authorised: the compose .env gets a fresh token. The file saved for the old one
    must not win over it forever."""
    real_env = S.ENV
    S.ENV = pathlib.Path(tempfile.mkdtemp()) / ".env"          # absent: the container
    os.environ["SPOTIFY_REFRESH_TOKEN"] = "old"
    try:
        S.set_env("SPOTIFY_REFRESH_TOKEN", "rotated")
        assert S.env()["SPOTIFY_REFRESH_TOKEN"] == "rotated"
        os.environ["SPOTIFY_REFRESH_TOKEN"] = "fresh"
        assert S.env()["SPOTIFY_REFRESH_TOKEN"] == "fresh"
    finally:
        S.ENV = real_env
        os.environ.pop("SPOTIFY_REFRESH_TOKEN", None)
        S.token_file().unlink(missing_ok=True)


def test_dotenv_is_rewritten_atomically_and_keeps_other_lines():
    real_env = S.ENV
    S.ENV = pathlib.Path(tempfile.mkdtemp()) / ".env"
    S.ENV.write_text("# keys\nTMDB_API_KEY=k\nSPOTIFY_REFRESH_TOKEN=old\n")
    S.token_file().write_text("older, from before there was a .env\n")
    replaced = []
    real_replace = S.os.replace
    S.os.replace = lambda a, b: (replaced.append(b), real_replace(a, b))
    try:
        S.set_env("SPOTIFY_REFRESH_TOKEN", "new")
        assert S.ENV.read_text() == "# keys\nTMDB_API_KEY=k\nSPOTIFY_REFRESH_TOKEN=new\n"
        assert replaced == [S.ENV], replaced
        assert not S.token_file().exists(), "a stale token file would win over .env"
    finally:
        S.os.replace = real_replace
        S.ENV = real_env


if __name__ == "__main__":
    for fn in (test_a_playlist_gone_from_spotify_is_removed_with_its_tracks,
               test_a_long_rate_limit_stops_instead_of_sleeping,
               test_a_rotated_token_survives_without_a_dotenv,
               test_a_new_token_in_the_environment_beats_the_saved_rotation,
               test_dotenv_is_rewritten_atomically_and_keeps_other_lines):
        fn()
        print(f"  ok  {fn.__name__}")
    print("spotify checks passed")
