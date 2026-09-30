"""Conversation starters.

Two filter axes, because one is not enough to find a usable question: who you
are asking (`audience`) and how exposed the answer makes them (`depth`). Both
chip rows narrow the same list, so "couples" plus "deep" is one click each.

Removal is a tombstone rather than a delete:
import_convo.py rebuilds this table, so a hard delete would come back.
"""
from __future__ import annotations

import dataclasses
import random

import reflex as rx

from ..core.ui import notice_toast, pager
from sqlmodel import Session, select

from ..core.models import ConvoQuestion
from ..core.state import ENGINE

PAGE_SIZE = 30
AUDIENCES = ["new-people", "dating", "couples", "long-distance", "friends",
             "life", "love", "self", "childhood", "philosophy", "journal",
             "funny", "would-you-rather", "never-have-i-ever", "this-or-that"]
DEPTHS = ["light", "medium", "deep"]
DEPTH_HUE = {"light": "var(--teal)", "medium": "var(--mustard)",
             "deep": "var(--vermilion)"}
AUD_HUE = {
    "new-people": "#3FB6A8", "dating": "#E2503F", "couples": "#C43A6E",
    "friends": "#F2A93B", "life": "#8A7DD8", "love": "#E2503F",
    "self": "#B9C6D8", "long-distance": "#C43A6E", "childhood": "#F2A93B",
    "philosophy": "#8A7DD8",
    "journal": "#3FB6A8", "funny": "#3FB6A8",
    "would-you-rather": "#7C8CA8", "never-have-i-ever": "#7C8CA8",
    "this-or-that": "#7C8CA8",
}


@dataclasses.dataclass
class QRow:
    id: int
    ordinal: str
    text: str
    audience: str
    aud_hue: str
    depth: str
    depth_hue: str
    asked: bool


class ConvoState(rx.State):
    _all: list[dict] = []
    audience: str = ""            # "" = any
    depth: str = ""               # "" = any
    # "" | "unasked" | "asked". One var rather than two booleans, which
    # could both be set and then mean nothing.
    asked_filter: str = ""
    page: int = 0
    hidden: int = 0
    picked: str = ""
    picked_id: int = 0
    exhausted: bool = False
    picked_tags: str = ""
    notice: str = ""

    # The page is one question at a time. `cursor` walks the
    # filtered pool; the table is the archive behind it, not the page.
    cursor: int = 0
    browsing: bool = False
    search: str = ""

    @rx.event
    def load(self):
        with Session(ENGINE) as s:
            rows = s.exec(select(ConvoQuestion)).all()
            self.hidden = sum(1 for q in rows if q.dismissed)
            self._all = [{
                "id": q.id, "ordinal": str(q.ordinal or ""), "text": q.text,
                "audience": q.audience, "depth": q.depth, "asked": q.asked,
                "sort": q.ordinal if q.ordinal is not None else 10**9,
            } for q in rows if not q.dismissed]
        self._all.sort(key=lambda r: r["sort"])

    def _matches(self) -> list[dict]:
        q = self.search.strip().lower()
        return [r for r in self._all
                if (not q or q in r["text"].lower())
                and (not self.audience or r["audience"] == self.audience)
                and (not self.depth or r["depth"] == self.depth)
                and (not self.asked_filter
                     or (self.asked_filter == "asked") == bool(r["asked"]))]

    @rx.var
    def rows(self) -> list[QRow]:
        page = self._matches()[self.page * PAGE_SIZE:(self.page + 1) * PAGE_SIZE]
        return [QRow(
            id=r["id"], ordinal=r["ordinal"], text=r["text"],
            audience=r["audience"], aud_hue=AUD_HUE.get(r["audience"], "var(--rule)"),
            depth=r["depth"], depth_hue=DEPTH_HUE.get(r["depth"], "var(--rule)"),
            asked=r["asked"],
        ) for r in page]

    @rx.var
    def total(self) -> int:
        return len(self._matches())

    @rx.var
    def last_page(self) -> int:
        return max(0, (self.total - 1) // PAGE_SIZE)

    @rx.var
    def page_label(self) -> str:
        if not self.total:
            return "0"
        lo = self.page * PAGE_SIZE + 1
        hi = min((self.page + 1) * PAGE_SIZE, self.total)
        return f"{lo}–{hi} of {self.total}"

    # ---- the card ---------------------------------------------------------
    @rx.var
    def card(self) -> QRow:
        """The question on screen. An empty pool renders an empty card rather
        than a missing one, so the page never collapses to nothing."""
        pool = self._matches()
        if not pool:
            return QRow(id=0, ordinal="", text="", audience="", aud_hue="",
                        depth="", depth_hue="", asked=False)
        r = pool[min(self.cursor, len(pool) - 1)]
        return QRow(
            id=r["id"], ordinal=r["ordinal"], text=r["text"],
            audience=r["audience"], aud_hue=AUD_HUE.get(r["audience"], "var(--rule)"),
            depth=r["depth"], depth_hue=DEPTH_HUE.get(r["depth"], "var(--rule)"),
            asked=r["asked"],
        )

    @rx.var
    def card_position(self) -> str:
        return f"{min(self.cursor + 1, self.total)} of {self.total}" if self.total else "0"

    @rx.var
    def has_card(self) -> bool:
        return self.total > 0

    @rx.var
    def summary(self) -> str:
        if not self._all:
            return "empty — run import_convo.py"
        asked = sum(1 for q in self._all if q["asked"])
        return f"{len(self._all)} questions, {asked} asked"

    @rx.var
    def filter_label(self) -> str:
        bits = [b for b in (self.audience, self.depth) if b]
        return " · ".join(bits) if bits else "everything"

    # ---- events -----------------------------------------------------------
    @rx.event
    def set_audience(self, v: str):
        self.audience = "" if v == self.audience else v
        self.page = 0
        self.cursor = 0

    @rx.event
    def set_depth(self, v: str):
        self.depth = "" if v == self.depth else v
        self.page = 0
        self.cursor = 0

    @rx.event
    def set_asked_filter(self, which: str):
        """Clicking the active one clears it, so "all" needs no third button."""
        self.asked_filter = "" if self.asked_filter == which else which
        self.page = 0
        self.cursor = 0

    @rx.event
    def clear_filters(self):
        self.audience = self.depth = self.search = ""
        self.asked_filter = ""
        self.page = 0
        self.cursor = 0

    @rx.event
    def set_search(self, v: str):
        self.search = v
        self.cursor = 0
        self.page = 0

    @rx.event
    def next_card(self):
        """Wraps. 265 questions read one at a time is a deck, not a list, and a
        deck that stops at the end makes you reach for the mouse."""
        if self.total:
            self.cursor = (self.cursor + 1) % self.total

    @rx.event
    def prev_card(self):
        if self.total:
            self.cursor = (self.cursor - 1) % self.total

    @rx.event
    def toggle_browsing(self):
        self.browsing = not self.browsing

    @rx.event
    def mark_card_asked(self):
        qid = self.card.id
        if not qid:
            return
        self.toggle_asked(qid)
        self.notice = "marked asked"
        self.next_card()

    @rx.event
    def next_page(self):
        if self.page < self.last_page:
            self.page += 1

    @rx.event
    def prev_page(self):
        if self.page > 0:
            self.page -= 1

    @rx.event
    def pick(self):
        """One question from whatever the filters allow, unasked ones first.

        265 questions and none of them marked asked, because the picker never
        wrote the column it was drawing against — so it could offer the same
        one twice in a row and nothing on the page would ever move. Unasked
        first, falling back to the whole pool once they run out, which is the
        only point at which repeating is the right answer.
        """
        pool = self._matches()
        if not pool:
            self.picked = "nothing matches those filters"
            self.picked_tags = ""
            self.picked_id = 0
            return
        fresh = [q for q in pool if not q["asked"]]
        q = random.choice(fresh or pool)
        self.picked = q["text"]
        self.picked_tags = f"{q['audience']} · {q['depth']}"
        self.picked_id = q["id"]
        self.exhausted = not fresh

    @rx.event
    def mark_picked_asked(self):
        """The button that closes the loop. Drawing a question is not asking
        it, so this is a separate click rather than a side effect of pick()."""
        if not self.picked_id:
            return
        self.toggle_asked(self.picked_id)
        self.picked_id = 0
        return ConvoState.pick

    @rx.event
    def toggle_asked(self, qid: int):
        """One row written, one row patched. A full reload for a boolean made
        every click re-read 225 questions."""
        with Session(ENGINE) as s:
            q = s.get(ConvoQuestion, qid)
            if not q:
                return
            q.asked = not q.asked
            new = q.asked
            s.add(q)
            s.commit()
        self._all = [{**row, "asked": new} if row["id"] == qid else row
                     for row in self._all]

    @rx.event
    def remove(self, qid: int):
        with Session(ENGINE) as s:
            q = s.get(ConvoQuestion, qid)
            if q:
                q.dismissed = True
                s.add(q)
                s.commit()
        self.load()
        if self.page > self.last_page:
            self.page = self.last_page

    @rx.event
    def restore_all(self):
        with Session(ENGINE) as s:
            for q in s.exec(select(ConvoQuestion)).all():
                if q.dismissed:
                    q.dismissed = False
                    s.add(q)
            s.commit()
        self.load()


# ---- page -----------------------------------------------------------------
def _chip(label: str, active: rx.Var, hue: str, on_click) -> rx.Component:
    return rx.button(
        label, size="1", variant=rx.cond(active, "solid", "surface"),
        on_click=on_click,
        style={"background": rx.cond(active, hue, "transparent")},
    )


def _row(q: rx.Var) -> rx.Component:
    return rx.table.row(
        rx.table.cell(rx.text(q.ordinal, size="1", class_name="tnum",
                              style={"color": "var(--dim)"}),
                      style={"width": "5%"}),
        rx.table.row_header_cell(rx.text(q.text, size="2"),
                                 style={"width": "53%"}),
        rx.table.cell(
            rx.cond(q.audience != "",
                    rx.badge(q.audience, style={"background": q.aud_hue,
                                                "color": "var(--ink)"}),
                    rx.fragment()),
            style={"width": "16%"},
        ),
        rx.table.cell(
            rx.cond(q.depth != "",
                    rx.badge(q.depth, style={"background": q.depth_hue,
                                             "color": "var(--ink)"}),
                    rx.fragment()),
            style={"width": "10%"},
        ),
        rx.table.cell(
            rx.button(rx.cond(q.asked, "✓ asked", "— not yet"),
                      on_click=ConvoState.toggle_asked(q.id), size="1",
                      variant="surface",
                      color_scheme=rx.cond(q.asked, "green", "gray")),
            style={"width": "11%"},
        ),
        rx.table.cell(
            rx.button("✕", on_click=ConvoState.remove(q.id), size="1",
                      variant="surface", color_scheme="red",
                      title="remove — Restore all brings it back"),
            style={"width": "5%"},
        ),
    )


def page() -> rx.Component:
    from ..core.ui import navbar
    return rx.container(
        rx.vstack(
            navbar("/convo"),
            rx.hstack(
                rx.heading("Conversation", size="7"),
                rx.spacer(),
                rx.text(ConvoState.summary, size="1", class_name="tnum",
                        style={"color": "var(--dim)"}),
                width="100%", align="end",
            ),
            notice_toast(ConvoState.notice),

            # Questions consumed one at a time are an
            # essay's rhythm, not a table's. The card is the page; the
            # table is the archive, folded away below.
            #
            # Prev/Next are labelled exactly that because keys.js binds p and n
            # by button text, and the card sits above the table's own pager, so
            # the keyboard reaches the card first.
            rx.cond(
                ConvoState.has_card,
                rx.box(
                    rx.hstack(
                        rx.text(ConvoState.card_position, size="1",
                                class_name="tnum", style={"color": "var(--dim)"}),
                        rx.spacer(),
                        rx.cond(ConvoState.card.audience != "",
                                rx.badge(ConvoState.card.audience,
                                         style={"background": ConvoState.card.aud_hue,
                                                "color": "var(--ink)"}),
                                rx.fragment()),
                        rx.cond(ConvoState.card.depth != "",
                                rx.badge(ConvoState.card.depth,
                                         style={"background": ConvoState.card.depth_hue,
                                                "color": "var(--ink)"}),
                                rx.fragment()),
                        width="100%", align="center", spacing="2",
                    ),
                    rx.heading(ConvoState.card.text, as_="p",
                               class_name="question"),
                    rx.hstack(
                        rx.button("Prev", size="2", variant="surface",
                                  on_click=ConvoState.prev_card),
                        rx.button("Next", size="2", variant="surface",
                                  on_click=ConvoState.next_card),
                        rx.button(rx.cond(ConvoState.card.asked,
                                          "Asked already", "Mark asked"),
                                  size="2",
                                  variant=rx.cond(ConvoState.card.asked,
                                                  "surface", "solid"),
                                  on_click=ConvoState.mark_card_asked),
                        rx.spacer(),
                        rx.button("Surprise me", size="2", variant="ghost",
                                  on_click=ConvoState.pick),
                        width="100%", align="center", spacing="2", wrap="wrap",
                    ),
                    class_name="question-card", width="100%",
                ),
                rx.text("Nothing matches those filters.", class_name="prose"),
            ),

            # The random draw still exists; it is one button on the card now,
            # and this is where its answer lands.
            rx.cond(
                ConvoState.picked != "",
                rx.box(
                    rx.text("Drawn at random", size="1",
                            style={"color": "var(--dim)"}),
                    rx.heading(ConvoState.picked, as_="p", class_name="question"),
                    rx.text(ConvoState.picked_tags, size="1",
                            style={"color": "var(--dim)"}),
                    rx.hstack(
                        rx.cond(
                            ConvoState.picked_id > 0,
                            rx.button("Asked it", size="1",
                                      on_click=ConvoState.mark_picked_asked),
                            rx.fragment(),
                        ),
                        rx.button("Another", size="1", variant="surface",
                                  on_click=ConvoState.pick),
                        spacing="2", align="center",
                        style={"marginTop": "0.75rem"},
                    ),
                    rx.cond(
                        ConvoState.exhausted,
                        rx.text("every question in this filter has been asked — "
                                "repeating now", size="1",
                                style={"color": "var(--mustard)"}),
                        rx.fragment(),
                    ),
                    class_name="question-card", width="100%",
                ),
                rx.fragment(),
            ),

            rx.hstack(
                rx.text("Who", size="1",
                        style={"color": "var(--dim)", "width": "3.5rem"}),
                *[_chip(a, ConvoState.audience == a, AUD_HUE[a],
                        ConvoState.set_audience(a)) for a in AUDIENCES],
                spacing="2", align="center", class_name="filter-row", wrap="wrap",
                width="100%",
            ),
            rx.hstack(
                rx.text("Depth", size="1",
                        style={"color": "var(--dim)", "width": "3.5rem"}),
                *[_chip(d, ConvoState.depth == d, DEPTH_HUE[d],
                        ConvoState.set_depth(d)) for d in DEPTHS],
                rx.button("Not asked yet", size="1",
                          variant=rx.cond(ConvoState.asked_filter == "unasked",
                                          "solid", "surface"),
                          on_click=ConvoState.set_asked_filter("unasked")),
                rx.button("Asked", size="1",
                          variant=rx.cond(ConvoState.asked_filter == "asked",
                                          "solid", "surface"),
                          on_click=ConvoState.set_asked_filter("asked")),
                rx.spacer(),
                rx.button("Clear", size="1", variant="ghost",
                          on_click=ConvoState.clear_filters),
                spacing="2", align="center", class_name="filter-row", wrap="wrap",
                width="100%",
            ),

            # The archive. It is not the page any more, so it is not open
            # by default: 265 rows of questions you read one at a time is a
            # reference, and a reference is something you go and get.
            rx.hstack(
                rx.button(rx.cond(ConvoState.browsing,
                                  "Hide the list", "Browse all questions"),
                          size="1", variant="ghost",
                          on_click=ConvoState.toggle_browsing),
                rx.input(placeholder="Search questions",
                         value=ConvoState.search,
                         on_change=ConvoState.set_search, size="1",
                         width="14rem"),
                rx.text(ConvoState.filter_label, size="1",
                        style={"color": "var(--dim)"}),
                spacing="3", align="center", width="100%",
            ),
            rx.cond(
                ConvoState.browsing,
                rx.vstack(
                pager(ConvoState),
                rx.cond(
                    ConvoState.rows,
                    rx.box(
                        rx.table.root(
                            rx.table.header(rx.table.row(*[
                                rx.table.column_header_cell(x) for x in
                                ("#", "Question", "Who", "Depth", "Asked", "")])),
                            rx.table.body(rx.foreach(ConvoState.rows, _row)),
                            variant="surface", size="1",
                            # Radix tables are width:100%, so on a phone they compress to fit and the
                            # overflow_x wrapper never scrolls — the width comes out of the columns
                            # instead. A floor below 48em makes the wrapper scroll, which is the
                            # ordinary phone table. Tiers: initial, xs 30em, sm 48em, md, lg.
                            min_width=["34rem", "34rem", "auto", "auto", "auto"],
                        ),
                        width="100%", overflow_x="auto",
                    ),
                    rx.text("Nothing matches those filters.", class_name="prose"),
                ),
                pager(ConvoState),
                    spacing="3", width="100%", align="start",
                ),
                rx.fragment(),
            ),
            rx.cond(
                ConvoState.hidden > 0,
                rx.hstack(
                    rx.text(f"{ConvoState.hidden} removed", size="1",
                            style={"color": "var(--dim)"}),
                    rx.button("Restore all", size="1", variant="ghost",
                              on_click=ConvoState.restore_all),
                    spacing="2", align="center", class_name="filter-row",
                ),
                rx.fragment(),
            ),
            spacing="4", width="100%", align="start",
        ),
        size="4",
        on_mount=ConvoState.load,
    )
