"""Ledger state: loads every title once, then filters/sorts/pages in Python.

A few hundred rows is small enough to hold server-side and slice per request, so the wire
only ever carries the 20 rows actually on screen. `_rows` is a backend-only var
(leading underscore) and is never serialised to the frontend.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime

import reflex as rx
from sqlalchemy import event
from sqlmodel import Session, create_engine, select

from . import sync_io
from .ui import medium_hue
from . import verdicts as V
from . import inline as IN
from .models import Genre, ListDef, Membership, Title, TitleGenre, WatchState, Progress

from .paths import atomic_write_text, db_path

ENGINE = create_engine(f"sqlite:///{db_path()}")


# ---------------------------------------------------------------------------
# SQLite for more than one reader.
#
# The default rollback journal takes a write lock over the whole database, so a
# second person loading a page while the first saves an edit gets
# "database is locked". WAL lets readers carry on during a write, which is the
# difference between this working for two people and not.
#
# journal_mode is a persistent property of the file, so it survives restarts;
# it is set on every connection anyway, because a file restored from backup may
# not carry it. busy_timeout is per connection and has to be set every time.
# ---------------------------------------------------------------------------
@event.listens_for(ENGINE, "connect")
def _sqlite_pragmas(dbapi_connection, _record):
    cur = dbapi_connection.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA busy_timeout=5000")     # wait, do not fail, on a lock
    cur.execute("PRAGMA foreign_keys=ON")       # 12 tables declare them
    cur.execute("PRAGMA synchronous=NORMAL")    # safe under WAL, much faster
    cur.close()

PAGE_SIZE = 20
MEDIA_LABELS = {"anime": "Anime", "anime-film": "Anime film", "movie": "Movie", "tv": "TV"}


def _list_label(l) -> str:
    """Unique per list. Every section has a 'Watchlist'; without the prefix
    they collapse into one filter chip."""
    return f"{l.section} / {l.name}" if l.section else l.name


def _load() -> list[dict]:
    """One pass over the DB into plain dicts."""
    with Session(ENGINE) as s:
        lists = {l.id: l for l in s.exec(select(ListDef)).all()}
        genres = {g.id: g.name for g in s.exec(select(Genre)).all()}
        by_title_lists: dict[int, list[str]] = {}
        for m in s.exec(select(Membership)).all():
            l = lists[m.list_id]
            label = _list_label(l)
            by_title_lists.setdefault(m.title_id, []).append(label)
        by_title_genres: dict[int, list[str]] = {}
        for tg in s.exec(select(TitleGenre)).all():
            by_title_genres.setdefault(tg.title_id, []).append(genres[tg.genre_id])
        watch = {w.title_id: w for w in s.exec(select(WatchState)).all()}
        prog = {p.title_id: p.marker for p in s.exec(select(Progress)).all()}

        decks: dict[str, list[dict]] = {}
        titles_by_id = {t.id: t for t in s.exec(select(Title)).all()}
        members: dict[int, list[int]] = {}
        for m in s.exec(select(Membership)).all():
            members.setdefault(m.list_id, []).append(m.title_id)
        for l in sorted(lists.values(), key=lambda x: (x.kind, x.section, x.sort_order)):
            group = l.section
            names = sorted((titles_by_id[i].name for i in members.get(l.id, [])), key=str.lower)
            decks.setdefault(group, []).append({"name": l.name, "titles": names})
        for g in decks:
            decks[g].sort(key=lambda c: -len(c["titles"]))

        rows = []
        for t in s.exec(select(Title)).all():
            w = watch.get(t.id)
            eps = w.episodes_played if w and w.episodes_played else None
            rows.append({
                "id": t.id,
                "name": t.name,
                "medium": t.medium,
                "medium_label": MEDIA_LABELS.get(t.medium, t.medium),
                "medium_hue": medium_hue(MEDIA_LABELS.get(t.medium, t.medium)),
                "lists": sorted(by_title_lists.get(t.id, [])),
                "genres": sorted(by_title_genres.get(t.id, [])),
                "episodes": eps,
                # Title.episodes is the total; `episodes` above is how many of
                # them have been played. Both are needed to say "7 of 12", and
                # only the played count was being carried.
                "total_episodes": t.episodes,
                "seasons": t.seasons,
                "current_season": w.current_season if w else None,
                "current_episode": w.current_episode if w else None,
                "watch_state": w.state if w else "unwatched",
                "progress": prog.get(t.id, ""),
                "last_played": w.last_played.date().isoformat() if (w and w.last_played) else "",
                "description": t.description or "",
                "rating": t.rating, "notes": t.notes or "",
                "year": t.year,
                "release_date": t.release_date.isoformat() if t.release_date else "",
                # Not out yet means one of two things: a date still in the
                # future, or membership of the list you keep for exactly this.
                # "has no date" is not one of them — 380 titles have no date.
                "unreleased": bool(t.release_date and t.release_date > date.today())
                or any("not yet" in l.lower() for l in by_title_lists.get(t.id, [])),
                "decade": f"{(t.year//10)*10}s" if t.year else "",
            })
        ids = {_list_label(l): l.id for l in lists.values()}
        return rows, decks, ids



def _progress_pct(r: dict) -> int:
    """How far in, 0-100. Zero when there is nothing to divide by — an unknown
    total is not the same as no progress, and the label says which."""
    played, total = r.get("episodes"), r.get("total_episodes")
    if not played or not total:
        return 0
    return max(0, min(100, round(100 * played / total)))


def _progress_label(r: dict) -> str:
    """The four numeric columns as one line: where you are, out of how many.

    Season and episode say where the bookmark is; played/total says how much of
    the thing is behind you. They are different questions and the row was
    spreading both across four cells you had to read together.
    """
    played, total = r.get("episodes"), r.get("total_episodes")
    cs, ce = r.get("current_season"), r.get("current_episode")
    here = " · ".join(x for x in (f"S{cs}" if cs else "",
                                  f"E{ce}" if ce else "") if x)
    if played and total:
        out = f"{played}/{total}"
    elif played:
        out = f"{played} watched"
    elif total:
        out = f"0/{total}"
    else:
        out = ""
    return "  ".join(x for x in (here, out) if x) or "—"

class LedgerState(rx.State):
    """Everything the library view needs."""

    _rows: list[dict] = []          # backend-only: full catalogue, native types
    _decks: dict[str, list[dict]] = {}
    _list_ids: dict[str, int] = {}
    loaded: bool = False
    open_sections: list[str] = []
    edit_mode: bool = False
    new_title: str = ""
    new_list: str = ""
    notice: str = ""
    busy: bool = False
    job_log: str = ""
    card_pages: dict[str, int] = {}
    _ambig: dict[str, dict] = {}    # backend-only: TMDB candidates awaiting a pick
    amb_index: int = 0

    search: str = ""
    sel_media: list[str] = []
    sel_genres: list[str] = []
    sel_decades: list[str] = []
    sel_lists: list[str] = []
    show_all_genres: bool = False
    only_unreleased: bool = False
    unvoted: str = ""             # a person: only the titles they have not voted on
    tried_filter: str = ""        # "" = all, else a watch state: watched|watching|unwatched
    sort_key: str = "name"
    sort_desc: bool = False
    page: int = 0

    # ---- loading ----------------------------------------------------------
    @rx.event
    def load(self):
        self._rows, self._decks, self._list_ids = _load()
        self.loaded = True

    # ---- derived ----------------------------------------------------------
    def _matches(self) -> list[dict]:
        q = self.search.strip().lower()
        out = self._rows
        if q:
            out = [r for r in out if q in r["name"].lower()]
        if self.sel_media:
            out = [r for r in out if r["medium"] in self.sel_media]
        if self.sel_genres:
            out = [r for r in out if any(g in self.sel_genres for g in r["genres"])]
        if self.sel_decades:
            out = [r for r in out if r["decade"] in self.sel_decades]
        if self.sel_lists:
            out = [r for r in out if any(l in self.sel_lists for l in r["lists"])]
        if self.only_unreleased:
            out = [r for r in out if r["unreleased"]]
        if self.tried_filter:
            out = [r for r in out if r["watch_state"] == self.tried_filter]
        if self.unvoted:
            held = V.read("title", [r["id"] for r in out])
            out = [r for r in out if not held.get(r["id"], {}).get(self.unvoted)]
        k = self.sort_key
        # Missing values sort last in BOTH directions. Returning (is_null, value)
        # and reversing flips the null flag too, which floated every "—" to the top.
        blank = -1 if self.sort_desc else 1
        def key(r):
            if k == "episodes":
                return (blank if r["episodes"] is None else 0, r["episodes"] or 0)
            if k == "seasons":
                return (blank if r["seasons"] is None else 0, r["seasons"] or 0)
            if k == "current_season":
                return (blank if r["current_season"] is None else 0, r["current_season"] or 0)
            if k == "current_episode":
                return (blank if r["current_episode"] is None else 0, r["current_episode"] or 0)
            if k == "medium":
                return (0, r["medium"])
            if k == "lists":
                return (0, ", ".join(r["lists"]))
            if k == "genres":
                return (0, ", ".join(r["genres"]))
            if k == "last_played":
                return (blank if r["last_played"] == "" else 0, r["last_played"])
            if k == "release_date":
                return (blank if not r["release_date"] else 0, r["release_date"])
            if k == "description":
                return (blank if not r["description"] else 0, r["description"].lower())
            if k == "rating":
                return (blank if not r["rating"] else 0, r["rating"] or 0)
            if k == "notes":
                return (blank if not r["notes"] else 0, r["notes"].lower())
            return (0, r["name"].lower())
        return sorted(out, key=key, reverse=self.sort_desc)

    @rx.var
    def total(self) -> int:
        return len(self._matches())

    @rx.var
    def page_rows(self) -> list[dict[str, str]]:
        """Only the visible page, flattened to strings for the frontend."""
        rows = self._matches()[self.page * PAGE_SIZE:(self.page + 1) * PAGE_SIZE]
        held = V.read("title", [r["id"] for r in rows])
        return [{
            "id": str(r["id"]),
            # Want-to-try, per person. Same table and control as every other
            # page — see verdicts.py.
            **{f"verdict_{p}": held.get(r["id"], {}).get(p, "") for p in V.PEOPLE},
            "name": r["name"],
            "medium": r["medium"],
            "medium_label": r["medium_label"],
            "medium_hue": r["medium_hue"],
            "lists": ", ".join(r["lists"]) or "—",
            "genres": ", ".join(r["genres"]) or "—",
            "seasons": str(r["seasons"]) if r["seasons"] else "—",
            "seasons_raw": str(r["seasons"] or ""),
            "current_season": str(r["current_season"]) if r["current_season"] else "—",
            "current_raw": str(r["current_season"] or ""),
            "current_episode": str(r["current_episode"]) if r["current_episode"] else "—",
            "current_ep_raw": str(r["current_episode"] or ""),
            "episodes": r["progress"] or (str(r["episodes"]) if r["episodes"] else "—"),
            "episodes_raw": str(r["episodes"] or ""),
            "progress_pct": str(_progress_pct(r)),
            "progress_label": _progress_label(r),
            "last_played": r["last_played"] or "—",
            "release_date": r["release_date"] if r["unreleased"] else "",
            "release_raw": r["release_date"],
            "unreleased": "yes" if r["unreleased"] else "",
            "description": r["description"] or "—",
            "description_raw": r["description"],
            "rating": IN.shown(r["rating"]),
            "notes": r["notes"],
        } for r in rows]

    @rx.event
    async def set_verdict(self, row_id: str, person: str, value: str):
        if await V.write_as(self, "title", int(row_id), person, value):
            self.load()
            # under the "to vote" filter the row just left the list
            self.page = min(self.page, self.last_page)

    @rx.event
    def set_unvoted(self, person: str):
        self.unvoted = "" if person == self.unvoted else person
        self.page = 0

    @rx.event
    def set_tried(self, v: str):
        self.tried_filter = "" if v == self.tried_filter else v
        self.page = 0

    @rx.event
    def set_inline(self, row_id: str, field: str, value: str):
        """Rating or notes, on blur. Row ids arrive as strings, like set_verdict's."""
        msg = IN.save(Title, int(row_id), field, value)
        if msg:
            self.notice = msg
            if not msg.startswith("a rating is"):
                self.load()

    @rx.var
    def page_label(self) -> str:
        n = self.total
        if n == 0:
            return "no matches"
        lo = self.page * PAGE_SIZE + 1
        hi = min((self.page + 1) * PAGE_SIZE, n)
        return f"{lo}–{hi} of {n}"

    @rx.var
    def last_page(self) -> int:
        return max(0, (self.total - 1) // PAGE_SIZE)

    @rx.var
    def decade_names(self) -> list[str]:
        """Decades, newest first — a year filter with 11 chips instead of 100."""
        return sorted({r["decade"] for r in self._rows if r["decade"]}, reverse=True)

    @rx.var
    def genre_names(self) -> list[str]:
        return sorted({g for r in self._rows for g in r["genres"]})

    @rx.var
    def genre_shown(self) -> list[str]:
        """The 14 commonest genres, then the rest on request. 34 chips at once
        was a wall you had to read rather than scan."""
        if self.show_all_genres:
            return self.genre_names
        counts: dict[str, int] = {}
        for r in self._rows:
            for g in r["genres"]:
                counts[g] = counts.get(g, 0) + 1
        top = sorted(counts, key=lambda g: (-counts[g], g))[:14]
        return sorted(set(top) | set(self.sel_genres))

    @rx.var
    def genre_more(self) -> str:
        hidden = len(self.genre_names) - len(self.genre_shown)
        return f"{hidden} more" if hidden > 0 else ""

    @rx.var
    def list_names(self) -> list[str]:
        return sorted({l for r in self._rows for l in r["lists"]})

    @rx.var
    def medium_keys(self) -> list[str]:
        return ["anime", "anime-film", "movie", "tv"]

    @rx.var
    def unreleased_label(self) -> str:
        n = len([r for r in self._rows if r["unreleased"]])
        return f"not out yet ({n})" if n else "not out yet"

    @rx.var
    def library_summary(self) -> str:
        by: dict[str, int] = {}
        for r in self._rows:
            by[r["medium_label"]] = by.get(r["medium_label"], 0) + 1
        return f"{len(self._rows)} titles: " + ", ".join(
            f"{v} {k.lower()}" for k, v in sorted(by.items(), key=lambda x: -x[1]))

    @rx.var
    def medium_chips(self) -> list[dict[str, str]]:
        """Label, underlying key and hue together, so the chip can wear the
        colour the table rows are keyed by."""
        return [{"key": k, "label": MEDIA_LABELS[k], "hue": medium_hue(MEDIA_LABELS[k])}
                for k in self.medium_keys]

    def _deck(self, group: str) -> list[dict[str, str]]:
        """Cards for one section, each showing only its current page."""
        out = []
        for card in self._decks.get(group, []):
            key = f"{group}|{card['name']}"
            total = len(card["titles"])
            pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
            pg = min(max(self.card_pages.get(key, 0), 0), pages - 1)
            lo, hi = pg * PAGE_SIZE, min((pg + 1) * PAGE_SIZE, total)
            out.append({
                "key": key,
                "name": card["name"],
                "count": str(total),
                "body": "\n".join(card["titles"][lo:hi]) or "empty",
                "label": f"{lo + 1}–{hi} of {total}" if pages > 1 else "",
                "paged": "1" if pages > 1 else "",
                "first": "1" if pg == 0 else "",
                "last": "1" if pg >= pages - 1 else "",
            })
        return out

    @rx.var
    def deck_anime(self) -> list[dict[str, str]]:
        return self._deck("Anime")

    @rx.var
    def deck_movies(self) -> list[dict[str, str]]:
        return self._deck("Movies")

    @rx.var
    def deck_tv(self) -> list[dict[str, str]]:
        return self._deck("TV Shows")

    @rx.var
    def all_list_labels(self) -> list[str]:
        """Every list, including empty ones — you must be able to move into them."""
        return sorted(self._list_ids.keys())

    # ---- mutations --------------------------------------------------------
    def _title_id(self, s: Session, name: str) -> int | None:
        t = s.exec(select(Title).where(Title.name == name)).first()
        return t.id if t else None

    @rx.var
    def in_progress(self) -> list[dict[str, str]]:
        """Series you are part-way through. A 12-column table can tell you that
        a show exists; only this can tell you where you stopped."""
        out = []
        for r in self._rows:
            if r.get("watch_state") != "watching":
                continue
            se, ep = r.get("current_season"), r.get("current_episode")
            at = (f"S{se}" if se else "") + (f"E{ep}" if ep else "")
            out.append({"name": r["name"], "at": at or "not started",
                        "medium": r["medium_label"], "hue": r["medium_hue"],
                        "of": (f" of {r['episodes']}" if r.get("episodes")
                               else "")})
        return sorted(out, key=lambda x: x["name"].lower())

    @rx.var
    def in_progress_label(self) -> str:
        n = len(self.in_progress)
        return f"{n} on the go" if n else ""

    @rx.event
    def bump_episode(self, name: str):
        """One click for the commonest edit there is: you watched another one."""
        with Session(ENGINE) as s:
            t = s.exec(select(Title).where(Title.name == name)).first()
            if not t:
                return
            w = s.exec(select(WatchState).where(WatchState.title_id == t.id)).first()
            if not w:
                w = WatchState(user_id=1, title_id=t.id, state="watching")
            w.current_episode = (w.current_episode or 0) + 1
            w.episodes_played = (w.episodes_played or 0) + 1
            w.last_played = datetime.now()
            ep = w.current_episode     # read before commit: commit expires w, and
            s.add(w)                   # touching it after the session closes raises
            s.commit()                 # DetachedInstanceError.
        # Was self._load(), which is the module-level row loader, not a method —
        # an AttributeError on every click since the first commit, raised *after*
        # the write, so each click added an episode and then showed an error.
        self.load()
        self.notice = f"{name} → E{ep}"

    @rx.event
    def set_number(self, field: str, name: str, raw: str):
        """Inline edit of a numeric cell. Blank clears the value.

        `seasons` lives on Title (a property of the show); `current_season` and
        `episodes` are per-user progress and live on WatchState.
        """
        raw = (raw or "").strip()
        if raw and not raw.isdecimal():
            self.notice = f"“{raw}” is not a number"
            return
        val = int(raw) if raw else None
        with Session(ENGINE) as s:
            t = s.exec(select(Title).where(Title.name == name)).first()
            if not t:
                return
            if field == "seasons":
                t.seasons = val
                s.add(t)
            else:
                w = s.exec(select(WatchState).where(WatchState.title_id == t.id)).first()
                if not w:
                    w = WatchState(user_id=1, title_id=t.id, state="unwatched")
                if field == "current_season":
                    w.current_season = val
                elif field == "current_episode":
                    w.current_episode = val
                elif field == "episodes":
                    w.episodes_played = val or 0
                s.add(w)
            s.commit()
        self.load()
        self.notice = f"{name}: {field.replace('_', ' ')} = {raw or '—'}"

    @rx.event
    def set_description(self, name: str, raw: str):
        """Inline edit of the description. Hard-capped at 300 characters."""
        text = (raw or "").strip()[:300]
        with Session(ENGINE) as s:
            t = s.exec(select(Title).where(Title.name == name)).first()
            if not t:
                return
            t.description = text
            s.add(t)
            s.commit()
        self.load()
        self.notice = f"{name}: description {len(text)}/300 chars" if text else f"{name}: description cleared"

    @rx.event
    def set_new_title(self, value: str):
        self.new_title = value

    @rx.event
    def set_new_list(self, value: str):
        self.new_list = value

    @rx.event
    def toggle_edit(self):
        self.edit_mode = not self.edit_mode
        self.notice = "pick a list on any row, or remove it" if self.edit_mode else ""

    @rx.event
    def move_title(self, name: str, dest: str):
        """Move a title to another list. One transaction, then reload."""
        list_id = self._list_ids.get(dest)
        if list_id is None:
            self.notice = f"unknown list: {dest}"
            return
        with Session(ENGINE) as s:
            tid = self._title_id(s, name)
            if tid is None:
                self.notice = f"not found: {name}"
                return
            for m in s.exec(select(Membership).where(Membership.title_id == tid)).all():
                s.delete(m)
            s.add(Membership(title_id=tid, list_id=list_id))
            state = {"Watched": "watched", "Watching": "watching"}.get(dest.split(" / ")[-1], "unwatched")
            for w in s.exec(select(WatchState).where(WatchState.title_id == tid)).all():
                w.state = state
                s.add(w)
            s.commit()
        self.load()
        self.notice = f"moved “{name}” to {dest}"

    @rx.event
    def remove_title(self, name: str):
        with Session(ENGINE) as s:
            tid = self._title_id(s, name)
            if tid is None:
                return
            for model in (Membership, TitleGenre, WatchState, Progress):
                for r in s.exec(select(model).where(model.title_id == tid)).all():
                    s.delete(r)
            t = s.get(Title, tid)
            if t:
                s.delete(t)
            s.commit()
        self.load()
        self.notice = f"removed “{name}”"

    @rx.event
    def add_title(self):
        name = self.new_title.strip()
        dest = self.new_list or (self.all_list_labels[0] if self.all_list_labels else "")
        if not name:
            self.notice = "enter a title first"
            return
        list_id = self._list_ids.get(dest)
        if list_id is None:
            self.notice = "pick a destination list"
            return
        with Session(ENGINE) as s:
            if s.exec(select(Title).where(Title.name == name)).first():
                self.notice = f"“{name}” is already tracked"
                return
            medium = ("movie" if dest.startswith("Movies")
                      else "tv" if dest.startswith("TV Shows") else "anime")
            t = Title(name=name, medium=medium, source="manual")
            s.add(t); s.commit(); s.refresh(t)
            s.add(Membership(title_id=t.id, list_id=list_id))
            state = {"Watched": "watched", "Watching": "watching"}.get(dest.split(" / ")[-1], "unwatched")
            s.add(WatchState(user_id=1, title_id=t.id, state=state))
            s.commit()
        self.new_title = ""
        self.load()
        self.notice = f"added “{name}” to {dest}"

    @rx.event
    def set_progress(self, name: str, marker: str):
        with Session(ENGINE) as s:
            tid = self._title_id(s, name)
            if tid is None:
                return
            row = s.exec(select(Progress).where(Progress.title_id == tid)).first()
            if marker.strip():
                if row:
                    row.marker = marker
                    s.add(row)
                else:
                    s.add(Progress(user_id=1, title_id=tid, marker=marker))
            elif row:
                s.delete(row)
            s.commit()
        self.load()

    @rx.var
    def amb_count(self) -> int:
        return len(self._ambig)

    @rx.var
    def amb_name(self) -> str:
        names = sorted(self._ambig)
        return names[self.amb_index] if names and self.amb_index < len(names) else ""

    @rx.var
    def amb_position(self) -> str:
        return f"{self.amb_index + 1} of {len(self._ambig)}" if self._ambig else ""

    @rx.var
    def amb_why(self) -> str:
        e = self._ambig.get(self.amb_name) or {}
        return f"{e.get('medium', '')} — {e.get('why', '')}" if e else ""

    @rx.var
    def amb_candidates(self) -> list[dict]:
        return (self._ambig.get(self.amb_name) or {}).get("candidates", [])

    @rx.var
    def amb_options(self) -> list[dict[str, str]]:
        """One flat row per candidate: everything the card renders, as strings."""
        out = []
        for c in self.amb_candidates:
            head = c["title"]
            if c.get("orig") and c["orig"] != c["title"]:
                head += f"  ({c['orig']})"
            out.append({
                "head": head,
                "meta": "  ·  ".join(x for x in (c.get("year") or "?", c.get("kind", ""),
                                                 f"{c.get('votes', 0)} votes",
                                                 ", ".join(c.get("genres") or [])) if x),
                "overview": c.get("overview") or "(no synopsis)",
            })
        return out

    # ---- TMDB ambiguity queue ---------------------------------------------
    @rx.event
    def load_ambiguous(self):
        """Read the candidates tmdb_fill.py could not choose between."""
        f = sync_io.DATA / "tmdb-ambiguous.json"
        self._ambig = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
        self.amb_index = 0

    def _drop_ambig(self):
        """Drop the current title from the file as it is now, not from this
        tab's copy: another tab or a tmdb_fill.py run may have changed it."""
        name = self.amb_name
        f = sync_io.DATA / "tmdb-ambiguous.json"
        now = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
        self._ambig = {k: v for k, v in now.items() if k != name}
        atomic_write_text(f, json.dumps(self._ambig, indent=2, ensure_ascii=False,
                                        sort_keys=True), mode=0o644)
        self.amb_index = min(self.amb_index, max(0, len(self._ambig) - 1))

    @rx.event
    def amb_pick(self, i: int):
        """Apply one candidate through tmdb_fill's own writer, so a hand pick and
        an automatic match land identically — database and cache together."""
        sys.path.insert(0, str(sync_io.SCRIPTS / "data"))
        from tmdb_fill import write_picked

        name, cands = self.amb_name, self.amb_candidates
        if not name or i >= len(cands):
            return
        c = cands[i]
        alt = c["orig"] if c["orig"] and c["orig"] != c["title"] else ""
        write_picked([(name, c["title"], c["year"], c["kind"], c["overview"],
                       "picked by hand", alt, c["genres"])])
        self._drop_ambig()
        self._rows, self._decks, self._list_ids = _load()
        self.notice = f"“{name}” → {c['title']} ({c['year'] or '?'})"

    @rx.event
    def amb_skip(self):
        if self._ambig:
            self.amb_index = (self.amb_index + 1) % len(self._ambig)

    @rx.event
    def amb_leave_blank(self):
        name = self.amb_name
        self._drop_ambig()
        self.notice = f"left “{name}” blank"

    # ---- TMDB enrichment, via tmdb_fill.py --------------------------------
    async def _tmdb(self, apply: bool):
        """Fill descriptions, genres and years. tmdb_fill.py writes the database
        and tmdb-cache.json, so a later rebuild keeps what it found."""
        async with self:
            if self.busy:
                return
            self.busy = True
            self.job_log = "querying TMDB…"
        cmd = [str(sync_io.APP / ".venv/bin/python"), str(sync_io.SCRIPTS / "data" / "tmdb_fill.py")]
        if apply:
            cmd.append("--apply")
        ok, out = await sync_io.arun(cmd, sync_io.APP, timeout=900)
        async with self:
            self.busy = False
            self.job_log = out
            if ok and apply:
                self._rows, self._decks, self._list_ids = _load()
                self.notice = "filled from TMDB"
            elif not ok:
                self.notice = "TMDB fill failed — see the log"
            self.load_ambiguous()

    @rx.event(background=True)
    async def preview_tmdb(self):
        await self._tmdb(apply=False)

    @rx.event(background=True)
    async def sync_from_tmdb(self):
        await self._tmdb(apply=True)

    # ---- events -----------------------------------------------------------
    @rx.event
    def toggle_unreleased(self):
        self.only_unreleased = not self.only_unreleased
        self.page = 0

    @rx.event
    def set_release(self, name: str, value: str):
        """A date TMDB does not have yet, typed in by hand. Blank clears it."""
        v = value.strip()
        when = None
        if v:
            try:
                when = date.fromisoformat(v)
            except ValueError:
                self.notice = f"{v} is not a date — use YYYY-MM-DD"
                return
        with Session(ENGINE) as s:
            t = s.exec(select(Title).where(Title.name == name)).first()
            if not t:
                return
            t.release_date = when
            s.add(t)
            s.commit()
        self.load()
        self.notice = f"{name}: {v or 'date cleared'}"

    @rx.event
    def toggle_genres_expanded(self):
        self.show_all_genres = not self.show_all_genres

    @rx.event
    def toggle_section(self, name: str):
        self.open_sections = ([x for x in self.open_sections if x != name]
                              if name in self.open_sections else self.open_sections + [name])

    @rx.event
    def card_next(self, key: str):
        self.card_pages = {**self.card_pages, key: self.card_pages.get(key, 0) + 1}

    @rx.event
    def card_prev(self, key: str):
        self.card_pages = {**self.card_pages, key: max(0, self.card_pages.get(key, 0) - 1)}

    @rx.event
    def set_search(self, value: str):
        self.search = value
        self.page = 0

    @rx.event
    def toggle_medium(self, m: str):
        self.sel_media = [x for x in self.sel_media if x != m] if m in self.sel_media else self.sel_media + [m]
        self.page = 0

    @rx.event
    def toggle_decade(self, d: str):
        self.sel_decades = ([x for x in self.sel_decades if x != d]
                            if d in self.sel_decades else self.sel_decades + [d])
        self.page = 0

    @rx.event
    def toggle_genre(self, g: str):
        self.sel_genres = [x for x in self.sel_genres if x != g] if g in self.sel_genres else self.sel_genres + [g]
        self.page = 0

    @rx.event
    def toggle_list(self, l: str):
        self.sel_lists = [x for x in self.sel_lists if x != l] if l in self.sel_lists else self.sel_lists + [l]
        self.page = 0

    @rx.event
    def sort_by(self, k: str):
        self.sort_desc = not self.sort_desc if self.sort_key == k else False
        self.sort_key = k
        self.page = 0

    @rx.event
    def next_page(self):
        self.page = min(self.page + 1, self.last_page)

    @rx.event
    def prev_page(self):
        self.page = max(self.page - 1, 0)

    @rx.event
    def clear_filters(self):
        self.search = ""
        self.sel_media = []
        self.sel_genres = []
        self.sel_decades = []
        self.sel_lists = []
        self.only_unreleased = False
        self.unvoted = ""
        self.tried_filter = ""
        self.page = 0
