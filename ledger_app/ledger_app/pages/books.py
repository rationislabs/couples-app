"""Books, on four shelves.

The shelf is the whole page: "want to buy" is a shopping list, "read" is a
record, and the two in between are the only states a book is actually in. One
button walks a row forward through them, because the thing you do on this page
is move a book one step, not fill in a form.

`notes` matters for the same reason it does on /shops — six months later the
title alone does not tell you why you photographed it in a bookshop.
"""
from __future__ import annotations

import dataclasses
import datetime as dt

import reflex as rx

from ..core.ui import notice_toast
from ..core import inline as IN
from sqlmodel import Session, select

from ..core.models import Book
from ..core.state import ENGINE

# Order is the journey, and every list in this file relies on it.
SHELVES = ["want to buy", "want to read", "reading", "read"]
SHELF_HUE = {
    "want to buy": "#F2A93B",   # mustard: something to act on
    "want to read": "#7C8CA8",  # dim on purpose — the someday pile
    "reading": "#3FB6A8",       # teal, same "in progress" it means elsewhere
    "read": "#5FBE8C",          # the only green in the app: done
}
KINDS = ["baking", "cooking", "drinks", "art", "fiction", "reference"]
KIND_HUE = {
    "baking": "#D98A3B", "cooking": "#C43A6E", "drinks": "#8A7DD8",
    "art": "#E2503F", "fiction": "#9B7BB8", "reference": "#B9C6D8",
}
NO_KIND = "— none —"


@dataclasses.dataclass
class BookRow:
    id: int
    name: str
    author: str
    shelf: str
    shelf_hue: str
    next_shelf: str
    kind: str
    kind_hue: str
    rating: str
    notes: str
    url: str
    finished_on: str


class BookState(rx.State):
    _books: list[dict] = []
    notice: str = ""
    edit_mode: bool = False
    shelf_filter: str = ""
    kind_filter: str = ""
    search: str = ""

    new_name: str = ""
    new_author: str = ""
    new_kind: str = ""
    new_shelf: str = "want to buy"

    @rx.event
    def load(self):
        with Session(ENGINE) as s:
            rows = [x for x in s.exec(select(Book)).all() if not x.dismissed]
        self._books = [{
            "id": x.id, "name": x.name, "author": x.author, "shelf": x.shelf,
            "kind": x.kind, "rating": x.rating or 0, "notes": x.notes,
            "url": x.url,
            "finished_on": x.finished_on.isoformat() if x.finished_on else "",
        } for x in rows]
        # Shelf order first, so the page reads as the journey it is; then
        # author, because a shelf is browsed by who wrote what.
        self._books.sort(key=lambda r: (_shelf_index(r["shelf"]),
                                        r["author"].lower(), r["name"].lower()))

    def _matches(self) -> list[dict]:
        q = self.search.strip().lower()
        return [r for r in self._books
                if (not q or q in r["name"].lower() or q in r["author"].lower()
                    or q in r["notes"].lower())
                and (not self.shelf_filter or r["shelf"] == self.shelf_filter)
                and (not self.kind_filter or r["kind"] == self.kind_filter)]

    @rx.var
    def rows(self) -> list[BookRow]:
        return [BookRow(
            id=r["id"], name=r["name"], author=r["author"], shelf=r["shelf"],
            shelf_hue=SHELF_HUE.get(r["shelf"], "var(--rule)"),
            next_shelf=_next_shelf(r["shelf"]),
            kind=r["kind"], kind_hue=KIND_HUE.get(r["kind"], "var(--rule)"),
            rating=str(r["rating"]) if r["rating"] else "",
            notes=r["notes"], url=r["url"], finished_on=r["finished_on"],
        ) for r in self._matches()]

    @rx.var
    def summary(self) -> str:
        if not self._books:
            return "no books yet"
        from collections import Counter
        c = Counter(r["shelf"] for r in self._books)
        bits = [f"{c[s]} {s}" for s in SHELVES if c.get(s)]
        return f"{len(self._books)} books · " + " · ".join(bits)

    @rx.var
    def shelf_rows(self) -> list[dict[str, str]]:
        """Every shelf, always, even the empty ones — a shelf with nothing on
        it is information, and a chip row that changes length as you filter is
        a moving target."""
        from collections import Counter
        c = Counter(r["shelf"] for r in self._books)
        return [{"name": s, "count": str(c.get(s, 0)),
                 "hue": SHELF_HUE[s], "on": self.shelf_filter == s}
                for s in SHELVES]

    @rx.var
    def kind_rows(self) -> list[dict[str, str]]:
        from collections import Counter
        c = Counter(r["kind"] for r in self._books if r["kind"])
        return [{"name": k, "count": str(n), "hue": KIND_HUE.get(k, "var(--rule)"),
                 "on": self.kind_filter == k} for k, n in c.most_common()]

    @rx.var
    def kind_options(self) -> list[str]:
        return [NO_KIND] + KINDS

    @rx.var
    def shelf_options(self) -> list[str]:
        return SHELVES

    @rx.var
    def unread_count(self) -> int:
        """Bought and never opened is the number this page exists to shame."""
        return sum(1 for r in self._books if r["shelf"] == "want to read")

    # ---- events -----------------------------------------------------------
    @rx.event
    def set_new_name(self, v: str):
        self.new_name = v

    @rx.event
    def set_new_author(self, v: str):
        self.new_author = v

    @rx.event
    def set_new_kind(self, v: str):
        self.new_kind = v

    @rx.event
    def set_new_shelf(self, v: str):
        self.new_shelf = v

    @rx.event
    def set_search(self, v: str):
        self.search = v

    @rx.event
    def set_shelf_filter(self, s: str):
        self.shelf_filter = "" if s == self.shelf_filter else s

    @rx.event
    def set_kind_filter(self, k: str):
        self.kind_filter = "" if k == self.kind_filter else k

    @rx.event
    def clear_filters(self):
        self.shelf_filter = self.kind_filter = self.search = ""

    @rx.event
    def toggle_edit(self):
        self.edit_mode = not self.edit_mode

    @rx.event
    def add_book(self):
        name = self.new_name.strip()
        if not name:
            self.notice = "a book needs a title"
            return
        with Session(ENGINE) as s:
            if s.exec(select(Book).where(Book.name == name)).first():
                self.notice = f"{name} is already on a shelf"
                return
            s.add(Book(name=name, author=self.new_author.strip(),
                       shelf=self.new_shelf if self.new_shelf in SHELVES
                       else "want to buy",
                       kind="" if self.new_kind in ("", NO_KIND) else self.new_kind))
            s.commit()
        self.new_name = self.new_author = self.new_kind = ""
        self.load()
        self.notice = f"added {name}"

    @rx.event
    def set_inline(self, row_id: int, field: str, value: str):
        """Rating or notes, on blur. core/inline.py does the checking."""
        msg = IN.save(Book, row_id, field, value)
        if msg:
            self.notice = msg
            if not msg.startswith("a rating is"):
                v = value.strip()
                new = (int(v) if v else 0) if field == "rating" else v
                self._books = [{**r, field: new} if r["id"] == row_id else r
                               for r in self._books]

    @rx.event
    def edit_book(self, bid: int, field: str, value: str):
        v = value.strip()
        with Session(ENGINE) as s:
            x = s.get(Book, bid)
            if not x:
                return
            if field == "name":
                if not v:
                    self.notice = "a book needs a title"
                    return
                x.name = v
            # rating moved to set_inline / core/inline.py (1-10)
            elif field == "kind":
                x.kind = "" if v == NO_KIND else v
            elif field == "shelf":
                if v not in SHELVES:
                    return
                _set_shelf(x, v)
            elif field == "url":
                if v and not v.startswith(("http://", "https://")):
                    v = "https://" + v
                x.url = v
            else:
                setattr(x, field, v)
            s.add(x)
            s.commit()
        self.load()
        self.notice = ""

    @rx.event
    def advance(self, bid: int):
        """One step along the shelf order. The only action this page needs a
        button for: bought it, started it, finished it."""
        with Session(ENGINE) as s:
            x = s.get(Book, bid)
            if not x:
                return
            nxt = _next_shelf(x.shelf)
            if nxt == x.shelf:
                return
            _set_shelf(x, nxt)
            s.add(x)
            s.commit()
            moved = f"{x.name} → {nxt}"
        self.load()
        self.notice = moved

    @rx.event
    def remove(self, bid: int):
        with Session(ENGINE) as s:
            x = s.get(Book, bid)
            if x:
                x.dismissed = True
                s.add(x)
                s.commit()
        self.load()
        self.notice = "removed"


def _shelf_index(shelf: str) -> int:
    return SHELVES.index(shelf) if shelf in SHELVES else len(SHELVES)


def _next_shelf(shelf: str) -> str:
    """The last shelf is a terminus, not a loop: a cycling button would walk
    "read" back to "want to buy" on a misclick and lose the finish date."""
    i = _shelf_index(shelf)
    return SHELVES[i + 1] if i + 1 < len(SHELVES) else shelf


def _set_shelf(x: Book, shelf: str) -> None:
    """Finishing stamps the date; moving back off `read` clears it, so the
    date never outlives the state it describes."""
    x.shelf = shelf
    if shelf == "read":
        x.finished_on = x.finished_on or dt.date.today()
    else:
        x.finished_on = None


# ---- page -----------------------------------------------------------------
def _row(r: rx.Var) -> rx.Component:
    return rx.table.row(
        rx.table.cell(rx.box(class_name="hue",
                             style={"background": r.shelf_hue,
                                    "minHeight": "1.1rem"}),
                      style={"width": "8px", "padding": "0 0 0 6px"}),
        rx.table.row_header_cell(
            rx.cond(
                BookState.edit_mode,
                rx.input(default_value=r.name, size="1", width="100%",
                         key=f"{r.id}-name",
                         on_blur=BookState.edit_book(r.id, "name")),
                rx.cond(r.url != "",
                        rx.link(r.name, href=r.url, is_external=True, size="2"),
                        rx.text(r.name, size="2")),
            ),
        ),
        rx.table.cell(
            rx.cond(
                BookState.edit_mode,
                rx.input(default_value=r.author, size="1", width="100%",
                         placeholder="author", key=f"{r.id}-author",
                         on_blur=BookState.edit_book(r.id, "author")),
                rx.text(r.author, size="1", style={"color": "var(--steel)"}),
            ),
        ),
        rx.table.cell(
            rx.cond(
                BookState.edit_mode,
                rx.select(BookState.shelf_options, value=r.shelf, size="1",
                          width="100%", key=f"{r.id}-shelf",
                          on_change=BookState.edit_book(r.id, "shelf")),
                rx.badge(r.shelf, style={"background": r.shelf_hue,
                                         "color": "var(--ink)",
                                         "whiteSpace": "nowrap"}),
            ),
        ),
        rx.table.cell(
            rx.cond(
                BookState.edit_mode,
                rx.select(BookState.kind_options, value=r.kind, size="1",
                          width="100%", key=f"{r.id}-kind",
                          on_change=BookState.edit_book(r.id, "kind")),
                rx.cond(r.kind != "",
                        rx.badge(r.kind, variant="outline",
                                 style={"color": r.kind_hue,
                                        "borderColor": r.kind_hue}),
                        rx.fragment()),
            ),
        ),
        IN.notes_cell(r.notes, BookState.set_inline(r.id, "notes"),
                      key=f"{r.id}-notes"),
        IN.rating_cell(r.rating, BookState.set_inline(r.id, "rating"),
                       key=f"{r.id}-rating"),
        rx.table.cell(
            rx.text(r.finished_on, size="1", class_name="tnum",
                    style={"color": "var(--dim)", "whiteSpace": "nowrap"}),
        ),
        rx.table.cell(
            rx.hstack(
                rx.cond(
                    r.next_shelf != r.shelf,
                    rx.button(r.next_shelf, on_click=BookState.advance(r.id),
                              size="1", variant="surface",
                              style={"whiteSpace": "nowrap"}),
                    rx.fragment(),
                ),
                rx.cond(BookState.edit_mode,
                        rx.button("Remove", size="1", variant="ghost",
                                  color_scheme="red",
                                  on_click=BookState.remove(r.id)),
                        rx.fragment()),
                spacing="1", align="center",
            ),
            style={"whiteSpace": "nowrap"},
        ),
    )


def _shelf_chip(s: rx.Var) -> rx.Component:
    return rx.button(
        rx.hstack(rx.text(s["name"], size="1"),
                  rx.text(s["count"], size="1", class_name="tnum",
                          style={"opacity": "0.6"}),
                  spacing="1", align="center"),
        size="1", variant=rx.cond(s["on"], "solid", "surface"),
        on_click=BookState.set_shelf_filter(s["name"]),
        style={"margin": "0", "borderRadius": "2px",
               "background": rx.cond(s["on"], s["hue"], "transparent"),
               "border": rx.cond(s["on"], "1px solid var(--bone)",
                                 "1px solid var(--rule)"),
               "color": rx.cond(s["on"], "var(--ink)", "var(--steel)")},
    )


def _kind_chip(k: rx.Var) -> rx.Component:
    return rx.button(
        rx.hstack(rx.text(k["name"], size="1"),
                  rx.text(k["count"], size="1", class_name="tnum",
                          style={"opacity": "0.6"}),
                  spacing="1", align="center"),
        size="1", variant=rx.cond(k["on"], "solid", "surface"),
        on_click=BookState.set_kind_filter(k["name"]),
        style={"margin": "0", "borderRadius": "2px",
               "background": rx.cond(k["on"], k["hue"], "transparent"),
               "border": rx.cond(k["on"], "1px solid var(--bone)",
                                 "1px solid var(--rule)"),
               "color": rx.cond(k["on"], "var(--ink)", "var(--steel)")},
    )


def page() -> rx.Component:
    # First page built on the shared shell in ui.py. The other eleven still
    # assemble their own container, navbar and title row by hand; retrofitting
    # them is a mechanical diff with no visible change, so it waits for a
    # session that can look at the result in a browser.
    from ..core.ui import data_table, empty_state, page_shell, toolbar
    return page_shell(
        "Books", "/books",

        toolbar(
            rx.input(placeholder="Title", value=BookState.new_name,
                     on_change=BookState.set_new_name, width="16rem"),
            rx.input(placeholder="Author", value=BookState.new_author,
                     on_change=BookState.set_new_author, width="12rem"),
            rx.select(BookState.kind_options, value=BookState.new_kind,
                      placeholder="Kind",
                      on_change=BookState.set_new_kind, width="9rem"),
            rx.select(BookState.shelf_options, value=BookState.new_shelf,
                      on_change=BookState.set_new_shelf, width="10rem"),
            rx.button("Add", on_click=BookState.add_book, size="2"),
            rx.spacer(),
            rx.button(rx.cond(BookState.edit_mode, "Done", "Edit"),
                      on_click=BookState.toggle_edit, size="1",
                      variant=rx.cond(BookState.edit_mode, "solid", "surface")),
        ),

        rx.hstack(
            rx.text("Shelf", size="1",
                    style={"color": "var(--dim)", "minWidth": "3.5rem",
                           "flex": "0 0 3.5rem", "paddingTop": "0.18rem"}),
            rx.box(rx.hstack(rx.foreach(BookState.shelf_rows, _shelf_chip),
                             spacing="2", wrap="wrap"),
                   class_name="filter-row", width="100%"),
            width="100%", align="start", spacing="2",
        ),
        rx.cond(
            BookState.kind_rows,
            rx.hstack(
                rx.text("Kind", size="1",
                        style={"color": "var(--dim)", "minWidth": "3.5rem",
                               "flex": "0 0 3.5rem", "paddingTop": "0.18rem"}),
                rx.box(rx.hstack(rx.foreach(BookState.kind_rows, _kind_chip),
                                 spacing="2", wrap="wrap"),
                       class_name="filter-row", width="100%"),
                width="100%", align="start", spacing="2",
            ),
            rx.fragment(),
        ),

        rx.hstack(
            rx.input(placeholder="Search title, author or note",
                     value=BookState.search,
                     on_change=BookState.set_search, width="16rem"),
            rx.button("Clear", size="1", variant="ghost",
                      on_click=BookState.clear_filters),
            spacing="2", align="center", class_name="filter-row", wrap="wrap",
        ),

        notice_toast(BookState.notice),

        data_table(
            ["", "Title", "Author", "Shelf", "Kind", "Why", "Rating",
             "Finished", ""],
            BookState.rows, _row,
            empty=empty_state("Nothing matches. Add a book above, or clear the "
                              "filters."),
        ),
        rx.text("Sorted by shelf, then author. The button on a row moves it "
                "one step: buy it, queue it, start it, finish it.",
                size="1", style={"color": "var(--dim)"}),

        aside=rx.text(BookState.summary, size="1", class_name="tnum",
                      style={"color": "var(--dim)"}),
        on_mount=BookState.load,
    )
