"""Checks for pages/gallery.py — uploads, the 100-photo cap, and delete.

    hearth/.venv/bin/python tests/test_gallery.py

Runs against a throwaway directory, never the real gallery/: the upload dir is
repointed before anything imports reflex's upload module.
"""
import asyncio
import io
import os
import pathlib
import shutil
import sys
import tempfile

TMP = pathlib.Path(tempfile.mkdtemp(prefix="zz-gallery-"))
os.environ["REFLEX_UPLOADED_FILES_DIR"] = str(TMP)

import reflex as rx                                   # noqa: E402
from PIL import Image                                  # noqa: E402

import _db  # first: never the real hearth.db
_db.migrate()

from hearth.pages import gallery as G             # noqa: E402

assert rx.get_upload_dir() == TMP, "not the throwaway dir — refusing to run"


def jpeg(px=(1200, 900)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", px, (120, 60, 30)).save(buf, "JPEG")
    return buf.getvalue()


def upload(st, *named):
    files = [rx.UploadFile(file=io.BytesIO(data), path=pathlib.Path(name))
             for name, data in named]
    return asyncio.run(st.upload(files))


def fresh():
    for p in TMP.iterdir():
        shutil.rmtree(p) if p.is_dir() else p.unlink()
    st = G.GalleryState(_reflex_internal_init=True)
    asyncio.run(st.load())
    return st


def test_upload_makes_a_small_thumbnail():
    st = fresh()
    upload(st, ("a.jpg", jpeg((4000, 3000))))
    assert st.count == 1 and st.photos[0]["thumb"] == "thumbs/a.jpg.jpg"
    with Image.open(TMP / "thumbs" / "a.jpg.jpg") as im:
        assert max(im.size) <= G.THUMB_PX


def test_names_cannot_escape_or_overwrite():
    st = fresh()
    upload(st, ("../../outside.jpg", jpeg()), ("dup.jpg", jpeg()), ("dup.jpg", jpeg()))
    names = sorted(p.name for p in TMP.iterdir() if p.is_file())
    assert names == ["dup-1.jpg", "dup.jpg", "outside.jpg"], names
    assert not (TMP.parent / "outside.jpg").exists()


def test_non_images_are_refused():
    st = fresh()
    upload(st, ("notes.txt", b"hello"), ("x.heic", b"\x00"))
    assert st.count == 0 and "not a JPEG" in st.notice


def test_the_cap_holds_and_says_so():
    st = fresh()
    small = jpeg((40, 40))
    upload(st, *[(f"p{i}.jpg", small) for i in range(G.MAX_PHOTOS + 3)])
    assert st.count == G.MAX_PHOTOS and st.full
    assert "3 left out" in st.notice and "Delete some" in st.notice
    upload(st, ("one-more.jpg", small))
    assert st.count == G.MAX_PHOTOS, "went past the cap"
    asyncio.run(st.load())
    assert "full" in st.notice


def test_delete_stays_inside_the_gallery():
    st = fresh()
    upload(st, ("keep.jpg", jpeg()), ("gone.jpg", jpeg()))
    asyncio.run(st.delete("../test_gallery.py"))
    asyncio.run(st.delete("thumbs"))
    assert st.count == 2
    asyncio.run(st.delete("gone.jpg"))
    assert st.count == 1 and not (TMP / "gone.jpg").exists()
    assert not (TMP / "thumbs" / "gone.jpg.jpg").exists()


def test_a_name_that_is_only_an_extension_is_refused():
    """"..jpg" became "jpg": saved, never listed, and past the cap forever."""
    st = fresh()
    upload(st, ("..jpg", jpeg()), (".png", jpeg()))
    assert st.count == 0 and "not a JPEG" in st.notice, st.notice
    assert not [p for p in TMP.iterdir() if p.is_file()], list(TMP.iterdir())


def test_an_oversized_upload_is_refused():
    st = fresh()
    real = G.MAX_BYTES
    G.MAX_BYTES = 1000
    try:
        upload(st, ("big.jpg", jpeg((800, 800))))
    finally:
        G.MAX_BYTES = real
    assert st.count == 0 and "too large" in st.notice, st.notice


def test_thumbnails_are_made_off_the_event_loop():
    import threading
    st = fresh()
    upload(st, ("a.jpg", jpeg((40, 40))))
    for p in (TMP / "thumbs").iterdir():
        p.unlink()
    where, real = [], G._thumb
    G._thumb = lambda p: (where.append(threading.get_ident()), real(p))[1]
    try:
        asyncio.run(st.load())
    finally:
        G._thumb = real
    assert where and threading.get_ident() not in where, "thumbnails built on the loop thread"


def test_an_oversized_upload_is_refused_before_it_is_stored():
    # Starlette spools the whole multipart body to disk before the handler's
    # per-photo check runs; the cap has to sit in front of it.
    from starlette.responses import PlainTextResponse
    from starlette.testclient import TestClient

    reached = []

    async def backend(scope, receive, send):
        reached.append(scope["path"])
        while (await receive()).get("more_body"):  # reads the body, as the upload handler does
            pass
        await PlainTextResponse("ok")(scope, receive, send)

    real, G.MAX_REQUEST = G.MAX_REQUEST, 1000
    try:
        c = TestClient(G.capped_uploads(backend))
        assert c.post("/_upload", content=b"x" * 2000).status_code == 413
        # No Content-Length (a proxy may forward a body chunked): counted while it is read.
        assert c.post("/_upload", content=(b"x" * 400 for _ in range(4))).status_code == 413
        assert c.post("/_upload", content=(b"x" * 10 for _ in range(3))).status_code == 200
        assert c.post("/_upload", content=b"x" * 10).status_code == 200
        assert c.get("/_upload/photo.jpg").status_code == 200   # serving photos is not uploading
    finally:
        G.MAX_REQUEST = real
    assert reached == ["/_upload", "/_upload", "/_upload", "/_upload/photo.jpg"], reached


if __name__ == "__main__":
    fns = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    try:
        for fn in fns:
            fn()
            print(f"  ok  {fn.__name__}")
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
    print("gallery checks passed")
    sys.exit(0)
