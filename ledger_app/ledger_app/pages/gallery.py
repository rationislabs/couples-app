"""Gallery: photos you upload, shown on the Tonight page.

 Uploads only — the SD card is never read. It holds
~32,000 images across its year folders, every one of them would 404 the moment
the card is unplugged, and a gallery that large needs an index this app does not
want. You pick what goes in; the app only ever shows what you put there.

Storage is the directory Reflex already serves at /_upload, repointed at the
repo's gallery/ in rxconfig.py. No table: with a cap of 100 the directory *is*
the index, and a table would be a second copy that could disagree with it.

gallery/ is gitignored and copied nightly by backup_db.sh, which never deletes
from its copy — so a photo removed here is still recoverable from backups/gallery/
if it survived one night.
"""
from __future__ import annotations

import pathlib
import re

import reflex as rx
from PIL import Image, ImageOps

from ..core.ui import notice_toast

MAX_PHOTOS = 100
UPLOAD_ID = "gallery_upload"          # rx.upload ids must be literals, not state
THUMBS = "thumbs"                     # a sub-directory, so it is never listed as a photo
THUMB_PX = 480
# No HEIC: Pillow cannot open it without a plugin, and only Safari can display it.
ACCEPT = {"image/jpeg": [".jpg", ".jpeg"], "image/png": [".png"],
          "image/webp": [".webp"], "image/gif": [".gif"]}
EXTS = {e for exts in ACCEPT.values() for e in exts}

# Pillow refuses images over ~179 MP as a decompression-bomb guard, and warns past
# 89 MP. One of the first five photos is 108 MP, and 200 MP phone cameras exist.
# Uploads come only from the two of you over the tailnet, so the guard protects
# against nobody here; lifted to a ceiling well above any real camera.
Image.MAX_IMAGE_PIXELS = 400_000_000


def _dir() -> pathlib.Path:
    d = rx.get_upload_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d


def _photos() -> list[pathlib.Path]:
    """Newest first. Top level only, so thumbs/ is not a photo."""
    return sorted((p for p in _dir().iterdir()
                   if p.is_file() and p.suffix.lower() in EXTS),
                  key=lambda p: p.stat().st_mtime, reverse=True)


def _thumb(p: pathlib.Path) -> str:
    """Upload-relative path of a 480px thumbnail, made the first time it is needed.

    A phone photo is 3-18 MB; one of the first five was 18. At the cap that is
    hundreds of MB on a page that is mostly opened on a phone over the tailnet.
    Named after the whole filename, so a.jpg and a.png cannot share a thumbnail.
    """
    t = p.parent / THUMBS / f"{p.name}.jpg"
    if not t.exists() or t.stat().st_mtime < p.stat().st_mtime:
        t.parent.mkdir(exist_ok=True)
        with Image.open(p) as im:
            # JPEG only: decode at a reduced scale instead of expanding all 108 MP
            # (~324 MB) to throw most of it away. A no-op for other formats.
            im.draft("RGB", (THUMB_PX * 2, THUMB_PX * 2))
            im = ImageOps.exif_transpose(im)   # phones store rotation in EXIF
            im.thumbnail((THUMB_PX, THUMB_PX))
            im.convert("RGB").save(t, "JPEG", quality=82)
    return f"{THUMBS}/{t.name}"


def _safe_name(raw: str) -> str:
    """The uploaded name, stripped of any directory part, never overwriting."""
    base = re.sub(r"[^A-Za-z0-9._-]+", "_",
                  pathlib.Path(raw or "photo").name).lstrip(".") or "photo"
    stem, suffix = pathlib.Path(base).stem, pathlib.Path(base).suffix
    p, n = _dir() / base, 1
    while p.exists():
        p, n = _dir() / f"{stem}-{n}{suffix}", n + 1
    return p.name


class GalleryState(rx.State):
    photos: list[dict[str, str]] = []     # {"name": ..., "thumb": ...}
    notice: str = ""

    @rx.var
    def count(self) -> int:
        return len(self.photos)

    @rx.var
    def full(self) -> bool:
        return len(self.photos) >= MAX_PHOTOS

    @rx.var
    def count_label(self) -> str:
        return f"{len(self.photos)} of {MAX_PHOTOS}"

    def _refresh(self):
        out = []
        for p in _photos():
            try:
                thumb = _thumb(p)
            except Exception:          # unreadable image: show the original, not a hole
                thumb = p.name
            out.append({"name": p.name, "thumb": thumb})
        self.photos = out

    @rx.event
    def load(self):
        self._refresh()
        if self.full:
            self.notice = (f"The gallery is full — {MAX_PHOTOS} photos. "
                           "Delete some to make room for new ones.")

    @rx.event
    async def upload(self, files: list[rx.UploadFile]):
        room = MAX_PHOTOS - len(_photos())
        saved = skipped_full = skipped_type = 0
        for f in files:
            if pathlib.Path(f.name or "").suffix.lower() not in EXTS:
                skipped_type += 1
                continue
            if saved >= room:
                skipped_full += 1
                continue
            (_dir() / _safe_name(f.name)).write_bytes(await f.read())
            saved += 1
        self._refresh()
        parts = [f"added {saved} photo{'s' * (saved != 1)}"]
        if skipped_type:
            parts.append(f"{skipped_type} not a JPEG, PNG, WebP or GIF")
        if skipped_full:
            parts.append(f"{skipped_full} left out — the gallery holds {MAX_PHOTOS}. "
                         "Delete some to make room")
        elif self.full:
            parts.append(f"that fills it: {MAX_PHOTOS} of {MAX_PHOTOS}")
        self.notice = "; ".join(parts)
        return rx.clear_selected_files(UPLOAD_ID)

    @rx.event
    def delete(self, name: str):
        d = _dir().resolve()
        p = (d / name).resolve()
        if p.parent != d or not p.is_file():   # never anything outside gallery/
            return
        p.unlink()
        (d / THUMBS / f"{p.name}.jpg").unlink(missing_ok=True)
        self._refresh()
        self.notice = f"deleted {name}"


def _tile(p: rx.Var) -> rx.Component:
    return rx.box(
        rx.link(
            rx.image(src=rx.get_upload_url(p["thumb"]), alt=p["name"],
                     loading="lazy", class_name="gallery-thumb"),
            href=rx.get_upload_url(p["name"]), is_external=True,
        ),
        rx.icon_button(rx.icon("x", size=12), size="1", variant="soft",
                       color_scheme="red", class_name="gallery-del",
                       aria_label="Delete photo",
                       on_click=GalleryState.delete(p["name"])),
        class_name="gallery-tile",
    )


def section() -> rx.Component:
    return rx.vstack(
        rx.hstack(
            rx.heading("Gallery", size="5", as_="h2", class_name="block-head"),
            rx.spacer(),
            rx.text(GalleryState.count_label, size="1", class_name="gallery-count"),
            width="100%", align="end",
        ),
        rx.cond(
            GalleryState.full,
            rx.callout(f"The gallery is full — {MAX_PHOTOS} photos. Delete some "
                       "before adding more.", icon="triangle_alert",
                       color_scheme="orange", size="1", width="100%"),
            rx.vstack(
                # The trigger sits outside the dropzone: a click inside it opens
                # the file picker, so a button in there would do both.
                rx.upload(
                    rx.text("Drop photos here, or click to choose", size="1"),
                    id=UPLOAD_ID, accept=ACCEPT, multiple=True,
                    max_files=MAX_PHOTOS, class_name="gallery-drop", width="100%",
                ),
                rx.hstack(
                    rx.foreach(rx.selected_files(UPLOAD_ID),
                               lambda f: rx.text(f, size="1", class_name="gallery-count")),
                    wrap="wrap", spacing="2",
                ),
                rx.button("Upload", size="1",
                          on_click=GalleryState.upload(
                              rx.upload_files(upload_id=UPLOAD_ID))),
                spacing="2", width="100%", align="start",
            ),
        ),
        rx.cond(
            GalleryState.count > 0,
            rx.grid(rx.foreach(GalleryState.photos, _tile),
                    columns=rx.breakpoints(initial="2", sm="3", lg="5"),
                    spacing="2", width="100%"),
            rx.text("No photos yet.", size="1", class_name="gallery-count"),
        ),
        notice_toast(GalleryState.notice),
        spacing="3", width="100%", align="start",
    )
