"""Checks for pages/gallery.py — uploads, the 100-photo cap, and delete.

    ledger_app/.venv/bin/python tests/test_gallery.py

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

from ledger_app.pages import gallery as G             # noqa: E402

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
    st.load()
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
    st.load()
    assert "full" in st.notice


def test_delete_stays_inside_the_gallery():
    st = fresh()
    upload(st, ("keep.jpg", jpeg()), ("gone.jpg", jpeg()))
    st.delete("../test_gallery.py")
    st.delete("thumbs")
    assert st.count == 2
    st.delete("gone.jpg")
    assert st.count == 1 and not (TMP / "gone.jpg").exists()
    assert not (TMP / "thumbs" / "gone.jpg.jpg").exists()


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
