"""Music: one card per playlist, mirrored from Spotify.

Read-only for now. `spotify_sync.py` writes the tables; nothing here writes
back to Spotify, so nothing on this page can damage an account.

Vibe tagging is a placeholder — the column exists and the button says so.
"""
from __future__ import annotations

import dataclasses
from collections import Counter

import reflex as rx

from ..core.ui import notice_toast, pager
from sqlmodel import Session, select

from ..core import sync_io
from ..core.models import Playlist, PlaylistTrack, Track
from ..core.state import ENGINE

# Most playlists are exactly 30 tracks, so a card shows 30 and only the larger
# ones paginate.
CARD_SIZE = 30


@dataclasses.dataclass
class TrackRow:
    """Typed: rx.foreach cannot walk a nested plain dict."""
    id: int
    pos: str
    name: str
    artists: str
    album: str
    year: str
    genres: str
    vibe: str
    score: str
    tags: str


@dataclasses.dataclass
class Card:
    id: int
    name: str
    count: str
    owner: str
    label: str
    first: str
    last: str
    open: str
    top_tags: str
    tracks: list[TrackRow]


class MusicState(rx.State):
    _playlists: list[dict] = []
    _tracks: dict[int, list[dict]] = {}
    pages: dict[str, int] = {}
    open_cards: list[str] = []
    staged: str = ""
    """Which playlist has a previewed push. Apply is refused for anything else,
    so a write always follows a diff you have seen."""
    push_count: str = "10"
    search: str = ""
    # "Add playlist builder and playlist reworking", "Add
    # playlist generator based on mood or vibes".
    build_vibes: list[str] = []
    build_size: str = "30"
    build_name: str = ""
    _built: list[dict] = []
    page: int = 0
    notice: str = ""
    busy: bool = False
    job_log: str = ""

    @rx.event
    def load(self):
        with Session(ENGINE) as s:
            lists = [p for p in s.exec(select(Playlist)).all() if not p.dismissed]
            tracks = {t.id: t for t in s.exec(select(Track)).all()}
            by_list: dict[int, list[dict]] = {}
            for m in s.exec(select(PlaylistTrack)).all():
                t = tracks.get(m.track_id)
                if not t:
                    continue
                by_list.setdefault(m.playlist_id, []).append({
                    "id": t.id, "pos": m.position, "name": t.name,
                    "artists": t.artists, "album": t.album,
                    "year": str(t.year or ""), "genres": t.genres,
                    "vibe": t.vibe, "tags": t.tags,
                    "score": f"{t.vibe_score:.2f}" if t.vibe_score else "",
                })
            for v in by_list.values():
                v.sort(key=lambda x: x["pos"])
            self._playlists = [{"id": p.id, "name": p.name, "owner": p.owner,
                                "count": len(by_list.get(p.id, []))}
                               for p in sorted(lists, key=lambda x: x.name.lower())]
            self._tracks = by_list

    # ---- derived ----------------------------------------------------------
    @rx.var
    def summary(self) -> str:
        n = sum(p["count"] for p in self._playlists)
        big = sum(1 for p in self._playlists if p["count"] > CARD_SIZE)
        return (f"{len(self._playlists)} playlists, {n} track slots, "
                f"{big} longer than {CARD_SIZE}")

    @rx.var
    def cards(self) -> list[Card]:
        q = self.search.strip().lower()
        out = []
        for p in self._playlists:
            rows = self._tracks.get(p["id"], [])
            # searching opens what it finds: a hit inside a collapsed card is
            # invisible otherwise
            opened = str(p["id"]) in self.open_cards or bool(q)
            counts: Counter = Counter()
            for r in rows:
                for tag in (x for x in r["tags"].split(", ") if x):
                    counts[tag] += 1
            top = ", ".join(t for t, _n in counts.most_common(4))
            if q and q not in p["name"].lower() and not any(
                    q in r["name"].lower() or q in r["artists"].lower() for r in rows):
                continue
            pages = max(1, (len(rows) + CARD_SIZE - 1) // CARD_SIZE)
            page = min(max(self.pages.get(str(p["id"]), 0), 0), pages - 1)
            window = rows[page * CARD_SIZE:(page + 1) * CARD_SIZE]
            out.append(Card(
                id=p["id"], name=p["name"], count=str(p["count"]), owner=p["owner"],
                open="yes" if opened else "", top_tags=top,
                label=(f"{page * CARD_SIZE + 1}–{page * CARD_SIZE + len(window)}"
                       f" of {len(rows)}" if pages > 1 else ""),
                first="yes" if page == 0 else "",
                last="yes" if page >= pages - 1 else "",
                tracks=([TrackRow(id=r["id"], pos=str(r["pos"] + 1), name=r["name"],
                                  artists=r["artists"], album=r["album"],
                                  year=r["year"], genres=r["genres"], vibe=r["vibe"],
                                  score=r["score"], tags=r["tags"])
                         for r in window] if opened else []),
            ))
        return out

    # ---- the builder --------------------------------------------------
    @rx.var
    def vibe_options(self) -> list[str]:
        seen: dict[int, str] = {}
        for rows in self._tracks.values():
            for r in rows:
                if r["vibe"]:
                    seen[r["id"]] = r["vibe"]
        from collections import Counter
        return [v for v, _n in Counter(seen.values()).most_common(40)]

    @rx.var
    def built_rows(self) -> list[TrackRow]:
        lo = self.page * CARD_SIZE
        return [TrackRow(id=r["id"], pos=str(lo + i + 1), name=r["name"],
                         artists=r["artists"], album=r["album"], year=r["year"],
                         genres=r["genres"], vibe=r["vibe"], score=r["score"],
                         tags=r["tags"])
                for i, r in enumerate(self._built[lo:lo + CARD_SIZE])]

    @rx.var
    def last_page(self) -> int:
        return max(0, (len(self._built) - 1) // CARD_SIZE)

    @rx.var
    def page_label(self) -> str:
        lo = self.page * CARD_SIZE
        return f"{lo + 1}–{min(lo + CARD_SIZE, len(self._built))} of {len(self._built)}"

    @rx.event
    def next_page(self):
        self.page = min(self.page + 1, self.last_page)

    @rx.event
    def prev_page(self):
        self.page = max(self.page - 1, 0)

    @rx.var
    def build_summary(self) -> str:
        if not self._built:
            return ""
        mins = sum(1 for _ in self._built) * 3.5 / 60
        return f"{len(self._built)} tracks, roughly {mins:.1f} hours"

    @rx.var
    def build_command(self) -> str:
        """The push is a CLI step on purpose.

        Creating a Spotify playlist needs a write-scoped token and several
        network calls. Doing that inside an event handler means a click can
        half-create a playlist and leave it there, with no way to tell from the
        page whether it worked. The app picks the tracks — which is the part
        that needed building — and the existing, reviewed script sends them.
        """
        if not self._built:
            return ""
        name = (self.build_name or "Ledger mix").replace('"', "")
        return f'./ledger_app/.venv/bin/python spotify_push.py --new "{name}" --apply'

    @rx.event
    def toggle_build_vibe(self, vibe: str):
        self.build_vibes = ([v for v in self.build_vibes if v != vibe]
                            if vibe in self.build_vibes
                            else self.build_vibes + [vibe])

    @rx.event
    def set_build_size(self, v: str):
        self.build_size = v

    @rx.event
    def set_build_name(self, v: str):
        self.build_name = v

    @rx.event
    def build(self):
        """Pick tracks matching the chosen vibes, best-scoring first.

        Deduplicated by track id: a track on two playlists is one track, and
        counting it twice would flatter whatever you play most.
        """
        wanted = set(self.build_vibes)
        seen: dict[int, dict] = {}
        for rows in self._tracks.values():
            for r in rows:
                if wanted and r["vibe"] not in wanted:
                    continue
                seen.setdefault(r["id"], r)
        pool = list(seen.values())
        pool.sort(key=lambda r: -float(r["score"] or 0))
        try:
            n = max(1, min(200, int(self.build_size)))
        except ValueError:
            n = 30
        self._built = pool[:n]
        self.page = 0
        self.notice = (f"built {len(self._built)} tracks"
                       if self._built else "nothing matches those vibes")

    @rx.event
    def clear_build(self):
        self._built = []
        self.build_vibes = []
        self.page = 0

    @rx.var
    def vibe_counts(self) -> list[dict[str, int | str]]:
        """Top vibes across every track, not per playlist.

        2,392 of 2,440 tracks carry a vibe and until now it was only ever
        visible one row at a time, so the shape of the collection — what this
        library actually sounds like — was in the database and nowhere on the
        page. Twelve bars, because the tail is long and a bar you cannot read
        is not a data point.
        """
        # Deduplicated by track id: _tracks is keyed per playlist and 2,440
        # tracks fill 3,008 slots, so counting rows counts the ones on two
        # playlists twice and flatters whatever you play most.
        seen: dict[int, str] = {}
        for rows in self._tracks.values():
            for r in rows:
                if r["vibe"]:
                    seen[r["id"]] = r["vibe"]
        c: Counter = Counter(seen.values())
        return [{"vibe": v, "n": n} for v, n in c.most_common(12)]

    @rx.var
    def vibe_total(self) -> str:
        n = len({r["id"] for rows in self._tracks.values() for r in rows
                 if r["vibe"]})
        shown = sum(int(d["n"]) for d in self.vibe_counts)
        return f"top 12 vibes · {shown} of {n} tagged tracks"

    # ---- events -----------------------------------------------------------
    @rx.event
    def set_search(self, v: str):
        self.search = v

    @rx.event
    def toggle_card(self, pid: int):
        k = str(pid)
        self.open_cards = ([x for x in self.open_cards if x != k]
                           if k in self.open_cards else self.open_cards + [k])

    @rx.event
    def open_all(self):
        self.open_cards = [str(p["id"]) for p in self._playlists]

    @rx.event
    def close_all(self):
        self.open_cards = []

    @rx.event
    def card_next(self, pid: int):
        k = str(pid)
        self.pages = {**self.pages, k: self.pages.get(k, 0) + 1}

    @rx.event
    def card_prev(self, pid: int):
        k = str(pid)
        self.pages = {**self.pages, k: max(0, self.pages.get(k, 0) - 1)}

    @rx.event(background=True)
    async def refresh_spotify(self):
        async with self:
            if self.busy:
                return
            self.busy, self.notice = True, "reading Spotify…"
        ok, out = sync_io.run([str(sync_io.APP / ".venv/bin/python"),
                               str(sync_io.SCRIPTS / "data" / "spotify_sync.py"),
                               "--sync", "--apply"], sync_io.ROOT, timeout=1800)
        async with self:
            self.busy = False
            self.job_log = out
            self.load()
            self.notice = ("refreshed from Spotify" if ok
                           else "sync failed — see the log")

    @rx.var
    def tag_summary(self) -> str:
        rows = [t for p in self._playlists for t in self._tracks.get(p["id"], [])]
        tagged = len({t["id"] for t in rows if t["tags"]})
        vibed = len({t["id"] for t in rows if t["vibe"]})
        return f"{tagged} tagged, {vibed} with a vibe"

    @rx.event(background=True)
    async def tag_vibes(self):
        """Fetch Last.fm tags, then label every track with the playlist it most
        resembles. Slow on a cold cache: one request per track at 5/sec."""
        async with self:
            if self.busy:
                return
            self.busy, self.notice = True, "fetching Last.fm tags…"
        py = str(sync_io.APP / ".venv/bin/python")
        script = str(sync_io.SCRIPTS / "data" / "vibe_tag.py")
        ok, out = sync_io.run([py, script, "--tags"], sync_io.ROOT, timeout=3600)
        if not ok:
            async with self:
                self.busy, self.job_log = False, out
                self.notice = "tagging failed — see the log"
            return
        async with self:
            self.notice = "scoring tracks against your playlists…"
        ok2, out2 = sync_io.run([py, script, "--vibes", "--apply"],
                                sync_io.ROOT, timeout=900)
        async with self:
            self.busy = False
            self.job_log = f"{out}\n\n{out2}"
            self.load()
            self.notice = "vibes updated" if ok2 else "scoring failed — see the log"

    @rx.event
    def set_push_count(self, v: str):
        self.push_count = v

    @rx.event(background=True)
    async def preview_push(self, name: str):
        async with self:
            if self.busy:
                return
            self.busy, self.notice = True, f"previewing an append to {name}…"
        ok, out = sync_io.run([str(sync_io.APP / ".venv/bin/python"),
                               str(sync_io.SCRIPTS / "data" / "spotify_push.py"),
                               "--add", name, "--count", self.push_count],
                              sync_io.ROOT, timeout=300)
        async with self:
            self.busy, self.job_log = False, out
            self.staged = name if ok else ""
            self.notice = (f"previewed {name} — press Apply to write it"
                           if ok else "preview failed — see the log")

    @rx.event(background=True)
    async def apply_push(self):
        """Append only, and only to the playlist you just previewed."""
        async with self:
            if self.busy or not self.staged:
                self.notice = "preview a playlist first"
                return
            name = self.staged
            self.busy, self.notice = True, f"appending to {name}…"
        ok, out = sync_io.run([str(sync_io.APP / ".venv/bin/python"),
                               str(sync_io.SCRIPTS / "data" / "spotify_push.py"),
                               "--add", name, "--count", self.push_count, "--apply"],
                              sync_io.ROOT, timeout=600)
        async with self:
            self.busy, self.job_log, self.staged = False, out, ""
            self.notice = (f"appended to {name} — refresh from Spotify to re-sync"
                           if ok else "append failed — see the log")

    @rx.event(background=True)
    async def suggest_for(self, name: str):
        """What else in the library fits this playlist. The curation primitive."""
        async with self:
            if self.busy:
                return
            self.busy, self.notice = True, f"finding tracks that fit {name}…"
        ok, out = sync_io.run([str(sync_io.APP / ".venv/bin/python"),
                               str(sync_io.SCRIPTS / "data" / "vibe_tag.py"), "--suggest", name],
                              sync_io.ROOT, timeout=300)
        async with self:
            self.busy, self.job_log = False, out
            self.notice = f"suggestions for {name}" if ok else "no suggestions — see the log"


# ---- page -----------------------------------------------------------------
def _track_row(t: rx.Var) -> rx.Component:
    return rx.hstack(
        rx.text(t.pos, size="1", class_name="tnum",
                style={"color": "var(--dim)", "minWidth": "1.6rem",
                       "flex": "0 0 1.6rem", "textAlign": "right"}),
        rx.vstack(
            rx.text(t.name, size="2"),
            rx.hstack(
                rx.text(t.artists, size="1", style={"color": "var(--dim)"}),
                rx.cond(t.tags != "",
                        rx.text(t.tags, size="1", style={"color": "var(--rule)"}),
                        rx.fragment()),
                spacing="2", align="baseline", wrap="wrap",
            ),
            spacing="0", align="start",
        ),
        rx.spacer(),
        rx.cond(t.vibe != "",
                rx.text(t.vibe, size="1", style={"color": "var(--mustard)",
                                                 "whiteSpace": "nowrap"}),
                rx.fragment()),
        rx.cond(t.score != "",
                rx.text(t.score, size="1", class_name="tnum",
                        style={"color": "var(--dim)"}),
                rx.fragment()),
        rx.text(t.year, size="1", class_name="tnum", style={"color": "var(--dim)"}),
        width="100%", align="center", spacing="2", class_name="row-place",
    )


def _card(c: rx.Var) -> rx.Component:
    return rx.box(
        rx.vstack(
            rx.hstack(
                rx.text(rx.cond(c.open != "", "▾", "▸"), size="2",
                        style={"color": "var(--mustard)", "width": "0.9rem"}),
                rx.text(c.name, class_name="block-head"),
                rx.spacer(),
                rx.text(c.count, size="1", class_name="tnum",
                        style={"color": "var(--dim)"}),
                on_click=MusicState.toggle_card(c.id),
                width="100%", align="baseline", spacing="2",
                style={"cursor": "pointer", "userSelect": "none"},
            ),
            rx.hstack(
                rx.cond(
                    c.top_tags != "",
                    rx.text(c.top_tags, size="1", style={"color": "var(--rule)"}),
                    rx.fragment(),
                ),
                rx.spacer(),
                rx.button("Suggest", on_click=MusicState.suggest_for(c.name),
                          size="1", variant="ghost",
                          style={"color": "var(--steel)"}),
                rx.button("Preview add", on_click=MusicState.preview_push(c.name),
                          size="1", variant="ghost",
                          style={"color": "var(--steel)"}),
                width="100%", align="center", spacing="2",
            ),
            rx.cond(
                c.open != "",
                rx.vstack(rx.foreach(c.tracks, _track_row), width="100%", spacing="0"),
                rx.fragment(),
            ),
            rx.cond(
                (c.label != "") & (c.open != ""),
                rx.hstack(
                    rx.button("‹", on_click=MusicState.card_prev(c.id), size="1",
                              variant="surface", disabled=c.first != ""),
                    rx.spacer(),
                    rx.text(c.label, size="1", class_name="tnum",
                            style={"color": "var(--dim)"}),
                    rx.spacer(),
                    rx.button("›", on_click=MusicState.card_next(c.id), size="1",
                              variant="surface", disabled=c.last != ""),
                    width="100%", align="center",
                ),
                rx.fragment(),
            ),
            spacing="2", width="100%", align="start",
        ),
        class_name="block", width="100%",
    )



def _vibe_chart() -> rx.Component:
    """The only aggregate view in the app, on the only page with enough rows to
    earn one.

    Horizontal bars, not vertical: the categories are phrases — "Golden Hour
    Glow", "Burnin' Rubber" — and rotated labels under a vertical chart are a
    thing you tilt your head at rather than read.
    """
    return rx.cond(
        MusicState.vibe_counts,
        rx.box(
            rx.hstack(
                rx.text("What this sounds like", class_name="block-head"),
                rx.spacer(),
                rx.text(MusicState.vibe_total, size="1", class_name="tnum",
                        style={"color": "var(--dim)"}),
                width="100%", align="end",
            ),
            rx.recharts.bar_chart(
                rx.recharts.bar(data_key="n", fill="#F2A93B", radius=2,
                                bar_size=13),
                rx.recharts.x_axis(type_="number", tick_line=False,
                                   axis_line=False),
                rx.recharts.y_axis(data_key="vibe", type_="category",
                                   width=118, tick_line=False,
                                   axis_line=False, interval=0),
                rx.recharts.graphing_tooltip(),
                data=MusicState.vibe_counts,
                layout="vertical",
                height=290, width="100%",
                margin={"top": 8, "right": 12, "bottom": 0, "left": 0},
            ),
            class_name="block", width="100%",
        ),
        rx.fragment(),
    )


def _builder() -> rx.Component:
    """Pick a mood, get a playlist.

    The two notes — "playlist builder" and "playlist generator based on mood or
    vibes" — are one screen: choosing which tracks is the whole job, and the
    vibe is how you choose. 2,392 of 2,440 tracks already carry one.
    """
    return rx.vstack(
        rx.hstack(
            rx.heading("Build a playlist", size="5", class_name="block-head"),
            rx.spacer(),
            rx.text(MusicState.build_summary, size="1", class_name="tnum",
                    style={"color": "var(--dim)"}),
            width="100%", align="end",
        ),
        rx.hstack(
            rx.input(placeholder="Name it", value=MusicState.build_name,
                     on_change=MusicState.set_build_name, width="14rem"),
            rx.input(placeholder="how many", value=MusicState.build_size,
                     on_change=MusicState.set_build_size, width="7rem"),
            rx.button("Build", on_click=MusicState.build, size="2"),
            rx.button("Clear", on_click=MusicState.clear_build, size="2",
                      variant="ghost"),
            spacing="2", align="center", wrap="wrap", width="100%",
        ),
        rx.text("Pick the vibes it should be made of. Nothing selected means "
                "the whole library.", size="1", style={"color": "var(--dim)"}),
        rx.hstack(
            rx.foreach(
                MusicState.vibe_options,
                lambda v: rx.button(
                    v, size="1",
                    variant=rx.cond(MusicState.build_vibes.contains(v),
                                    "solid", "surface"),
                    on_click=MusicState.toggle_build_vibe(v)),
            ),
            spacing="2", wrap="wrap", class_name="filter-row", width="100%",
        ),
        rx.cond(
            MusicState.built_rows,
            rx.vstack(
                pager(MusicState),
                rx.box(
                    rx.table.root(
                        rx.table.header(rx.table.row(*[
                            rx.table.column_header_cell(x) for x in
                            ("#", "Track", "Artists", "Vibe", "Fit")])),
                        rx.table.body(rx.foreach(MusicState.built_rows, _built_row)),
                        variant="surface", size="1",
                        # Radix tables are width:100%, so on a phone they compress to fit and the
                        # overflow_x wrapper never scrolls — the width comes out of the columns
                        # instead. A floor below 48em makes the wrapper scroll, which is the
                        # ordinary phone table. Tiers: initial, xs 30em, sm 48em, md, lg.
                        min_width=["34rem", "34rem", "auto", "auto", "auto"],
                    ),
                    width="100%", overflow_x="auto",
                ),
                pager(MusicState),
                # The push is deliberately a command you run, not a button you
                # click — see MusicState.build_command.
                rx.text("To send it to Spotify:", size="1",
                        style={"color": "var(--dim)"}),
                rx.code(MusicState.build_command, size="1"),
                spacing="2", width="100%", align="start",
            ),
            rx.fragment(),
        ),
        spacing="3", width="100%", align="start", class_name="block",
    )


def _built_row(t: rx.Var) -> rx.Component:
    return rx.table.row(
        rx.table.cell(rx.text(t.pos, size="1", class_name="tnum",
                              style={"color": "var(--dim)"})),
        rx.table.row_header_cell(rx.text(t.name, size="2")),
        rx.table.cell(rx.text(t.artists, size="1",
                              style={"color": "var(--steel)"})),
        rx.table.cell(rx.cond(t.vibe != "",
                              rx.badge(t.vibe, size="1"), rx.fragment())),
        rx.table.cell(rx.text(t.score, size="1", class_name="tnum",
                              style={"color": "var(--dim)"})),
    )


def page() -> rx.Component:
    from ..core.ui import navbar
    return rx.container(
        rx.vstack(
            navbar("/music"),
            rx.hstack(
                rx.heading("Music", size="7"),
                rx.spacer(),
                rx.vstack(
                    rx.text(MusicState.summary, size="1", class_name="tnum",
                            style={"color": "var(--dim)"}),
                    rx.text(MusicState.tag_summary, size="1", class_name="tnum",
                            style={"color": "var(--dim)"}),
                    spacing="0", align="end",
                ),
                width="100%", align="end",
            ),
            _builder(),
            rx.hstack(
                rx.input(placeholder="Search playlists, tracks, artists",
                         value=MusicState.search,
                         on_change=MusicState.set_search, width="20rem"),
                rx.spacer(),
                rx.button("Refresh from Spotify", on_click=MusicState.refresh_spotify,
                          size="1", variant="surface", loading=MusicState.busy),
                rx.button("Expand all", on_click=MusicState.open_all, size="1",
                          variant="ghost", style={"color": "var(--steel)"}),
                rx.button("Collapse all", on_click=MusicState.close_all, size="1",
                          variant="ghost", style={"color": "var(--steel)"}),
                rx.button("Tag vibes", on_click=MusicState.tag_vibes, size="1",
                          variant="surface"),
                rx.input(value=MusicState.push_count,
                         on_change=MusicState.set_push_count, width="3.5rem",
                         size="1", type="number"),
                rx.cond(
                    MusicState.staged != "",
                    rx.button(f"Apply to {MusicState.staged}",
                              on_click=MusicState.apply_push, size="1",
                              color_scheme="orange", loading=MusicState.busy),
                    rx.fragment(),
                ),
                # wraps on a phone: unwrapped, both inputs were squeezed to 2px
                # and Tag vibes ran past the edge of a 390px screen
                width="100%", align="center", spacing="3", wrap="wrap",
            ),
            notice_toast(MusicState.notice),
            _vibe_chart(),
            rx.cond(
                MusicState.job_log != "",
                rx.box(rx.text(MusicState.job_log, size="1",
                               style={"whiteSpace": "pre-line",
                                      "fontFamily": "ui-monospace, monospace",
                                      "color": "var(--steel)"}),
                       class_name="block", width="100%",
                       style={"maxHeight": "9rem", "overflowY": "auto"}),
                rx.fragment(),
            ),
            # three across pushed the page 90px past a phone screen
            rx.grid(rx.foreach(MusicState.cards, _card),
                    columns=rx.breakpoints(initial="1", sm="2", md="3"),
                    spacing="3",
                    width="100%"),
            spacing="4", width="100%", align="start",
        ),
        size="4",
    )
