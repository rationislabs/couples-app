"""Checks for spotify_sync.py that need no network.

A playlist deleted in Spotify stayed here forever, and a 429 with a
Retry-After of hours slept for hours inside a sync the app was waiting on.

    ./.venv/bin/python test_spotify.py
"""
import io
import pathlib
import sys
import urllib.error

sys.argv = [sys.argv[0]]           # the script reads --apply from argv at import
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts" / "data"))
import spotify_sync as S                                     # noqa: E402
from sqlmodel import Session, select                         # noqa: E402

from ledger_app.core.models import Playlist, PlaylistTrack, Track  # noqa: E402


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


if __name__ == "__main__":
    for fn in (test_a_playlist_gone_from_spotify_is_removed_with_its_tracks,
               test_a_long_rate_limit_stops_instead_of_sleeping):
        fn()
        print(f"  ok  {fn.__name__}")
    print("spotify checks passed")
