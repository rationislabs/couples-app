"""Shops worth going back to.

A bookmark folder remembers the address. This remembers *why* you kept the
place, which is the part that has evaporated by the next time you need it. So
`good_for` is the column the page is built around, not the URL — "good linen,
runs small" beats a five-star rating with no note attached.

`ships_here` earns its place for the same reason: the shop that looks perfect
until the customs line at checkout is a discovery you only want to make once.
"""
from __future__ import annotations

import dataclasses
import datetime as dt

import reflex as rx

from ..core.ui import header_cells, notice_toast
from ..core import inline as IN
from sqlmodel import Session, select

from ..core.models import Shop
from ..core.state import ENGINE

KINDS = ["clothing", "homeware", "furniture", "plants", "food", "beauty",
         "outdoor", "tech", "books", "gifts", "craft"]
KIND_HUE = {
    "clothing": "#E2503F", "homeware": "#F2A93B", "furniture": "#8A7DD8",
    "plants": "#6FBF73", "food": "var(--rose)", "beauty": "#3FB6A8",
    "outdoor": "#4F9D69", "tech": "#B9C6D8", "books": "#7C8CA8",
    "gifts": "#D98A3B", "craft": "#9B7BB8",
}
PRICE_BANDS = ["budget", "mid", "premium"]
NO_KIND = "— none —"


@dataclasses.dataclass
class ShopRow:
    id: int
    name: str
    url: str
    kind: str
    hue: str
    good_for: str
    rating: str
    price_band: str
    ships_here: bool
    country: str
    notes: str
    last_ordered: str
    order_count: str
    never_ordered: bool


class ShopState(rx.State):
    _shops: list[dict] = []
    notice: str = ""
    edit_mode: bool = False
    kind_filter: str = ""
    band_filter: str = ""
    ships_only: bool = False
    unordered_only: bool = False
    min_rating: int = 0
    search: str = ""

    new_name: str = ""
    new_url: str = ""
    new_kind: str = ""
    new_good_for: str = ""

    @rx.event
    def load(self):
        with Session(ENGINE) as s:
            rows = [x for x in s.exec(select(Shop)).all() if not x.dismissed]
        self._shops = [{
            "id": x.id, "name": x.name, "url": x.url, "kind": x.kind,
            "good_for": x.good_for, "rating": x.rating or 0,
            "price_band": x.price_band, "ships_here": x.ships_here,
            "country": x.country, "notes": x.notes,
            "last_ordered": x.last_ordered.isoformat() if x.last_ordered else "",
            "order_count": x.order_count,
        } for x in rows]
        # best first, then most ordered from, then name
        self._shops.sort(key=lambda r: (-r["rating"], -r["order_count"],
                                        r["name"].lower()))

    def _matches(self) -> list[dict]:
        q = self.search.strip().lower()
        return [r for r in self._shops
                if (not q or q in r["name"].lower()
                    or q in r["good_for"].lower() or q in r["notes"].lower())
                and (not self.kind_filter or r["kind"] == self.kind_filter)
                and (not self.band_filter or r["price_band"] == self.band_filter)
                and (not self.ships_only or r["ships_here"])
                and (not self.unordered_only or not r["order_count"])
                and r["rating"] >= self.min_rating]

    @rx.var
    def rows(self) -> list[ShopRow]:
        return [ShopRow(
            id=r["id"], name=r["name"], url=r["url"], kind=r["kind"],
            hue=KIND_HUE.get(r["kind"], "var(--rule)"), good_for=r["good_for"],
            rating=str(r["rating"]) if r["rating"] else "",
            price_band=r["price_band"], ships_here=r["ships_here"],
            country=r["country"], notes=r["notes"],
            last_ordered=r["last_ordered"],
            order_count=str(r["order_count"]) if r["order_count"] else "",
            # "add ones not ordered from yet to distinguish". An empty cell
            # read as missing data; this says which it is.
            never_ordered=not r["order_count"],
        ) for r in self._matches()]

    @rx.var
    def summary(self) -> str:
        if not self._shops:
            return "nothing saved yet"
        ordered = sum(1 for r in self._shops if r["order_count"])
        blocked = sum(1 for r in self._shops if not r["ships_here"])
        bits = [f"{len(self._shops)} shops", f"{ordered} ordered from"]
        if blocked:
            bits.append(f"{blocked} do not ship here")
        return " · ".join(bits)

    @rx.var
    def undescribed(self) -> int:
        """Rows with no note. The whole point of the page is that note, so an
        unfilled one is worth nagging about."""
        return sum(1 for r in self._shops if not r["good_for"].strip())

    @rx.var
    def kind_rows(self) -> list[dict[str, str]]:
        from collections import Counter
        c = Counter(r["kind"] for r in self._shops if r["kind"])
        return [{"name": k, "count": str(n), "hue": KIND_HUE.get(k, "var(--rule)"),
                 "on": self.kind_filter == k} for k, n in c.most_common()]

    @rx.var
    def band_rows(self) -> list[dict[str, str]]:
        from collections import Counter
        c = Counter(r["price_band"] for r in self._shops if r["price_band"])
        return [{"name": b, "count": str(c.get(b, 0)), "on": self.band_filter == b}
                for b in PRICE_BANDS if c.get(b)]

    @rx.var
    def kind_options(self) -> list[str]:
        return [NO_KIND] + KINDS

    @rx.var
    def band_options(self) -> list[str]:
        return [NO_KIND] + PRICE_BANDS

    @rx.var
    def rating_label(self) -> str:
        return f"{self.min_rating}+ of 10" if self.min_rating else "any rating"

    # ---- events -----------------------------------------------------------
    @rx.event
    def set_new_name(self, v: str):
        self.new_name = v

    @rx.event
    def set_new_url(self, v: str):
        self.new_url = v

    @rx.event
    def set_new_kind(self, v: str):
        self.new_kind = v

    @rx.event
    def set_new_good_for(self, v: str):
        self.new_good_for = v

    @rx.event
    def set_search(self, v: str):
        self.search = v

    @rx.event
    def set_kind_filter(self, k: str):
        self.kind_filter = "" if k == self.kind_filter else k

    @rx.event
    def set_band_filter(self, b: str):
        self.band_filter = "" if b == self.band_filter else b

    @rx.event
    def toggle_ships(self):
        self.ships_only = not self.ships_only

    @rx.event
    def toggle_unordered(self):
        self.unordered_only = not self.unordered_only

    @rx.event
    def set_inline(self, row_id: int, field: str, value: str):
        """Rating or notes, on blur. core/inline.py does the checking."""
        msg = IN.save(Shop, row_id, field, value)
        if msg:
            self.notice = msg
            if not msg.startswith("a rating is"):
                v = value.strip()
                new = (int(v) if v else 0) if field == "rating" else v
                self._shops = [{**r, field: new} if r["id"] == row_id else r
                               for r in self._shops]

    @rx.event
    def cycle_rating(self):
        """One button, four states: any -> 6+ -> 8+ -> 10 -> any. Nobody
        filters at "1 out of 10"."""
        # rescaled with ratings (1-5 stars -> 1-10): 3/4/5 stars were 6/8/10
        self.min_rating = {0: 6, 6: 8, 8: 10, 10: 0}.get(self.min_rating, 0)

    @rx.event
    def clear_filters(self):
        self.kind_filter = self.band_filter = self.search = ""
        self.ships_only = False
        self.unordered_only = False
        self.min_rating = 0

    @rx.event
    def toggle_edit(self):
        self.edit_mode = not self.edit_mode

    @rx.event
    def add_shop(self):
        name = self.new_name.strip()
        if not name:
            self.notice = "a shop needs a name"
            return
        url = self.new_url.strip()
        if url and not url.startswith(("http://", "https://")):
            url = "https://" + url
        with Session(ENGINE) as s:
            if s.exec(select(Shop).where(Shop.name == name)).first():
                self.notice = f"{name} is already saved"
                return
            s.add(Shop(name=name, url=url,
                       kind="" if self.new_kind in ("", NO_KIND) else self.new_kind,
                       good_for=self.new_good_for.strip()))
            s.commit()
        self.new_name = self.new_url = self.new_kind = self.new_good_for = ""
        self.load()
        self.notice = f"added {name}"

    @rx.event
    def edit_shop(self, sid: int, field: str, value: str):
        v = value.strip()
        with Session(ENGINE) as s:
            x = s.get(Shop, sid)
            if not x:
                return
            if field == "name":
                if not v:
                    self.notice = "a shop needs a name"
                    return
                x.name = v
            elif field == "url":
                if v and not v.startswith(("http://", "https://")):
                    v = "https://" + v
                x.url = v
            # rating moved to set_inline / core/inline.py (1-10)
            elif field == "kind":
                x.kind = "" if v == NO_KIND else v
            elif field == "price_band":
                x.price_band = "" if v == NO_KIND else v
            else:
                setattr(x, field, v)
            s.add(x)
            s.commit()
        self.load()
        self.notice = ""

    @rx.event
    def ordered(self, sid: int):
        with Session(ENGINE) as s:
            x = s.get(Shop, sid)
            if x:
                x.order_count += 1
                x.last_ordered = dt.date.today()
                s.add(x)
                s.commit()
        self.load()

    @rx.event
    def toggle_ships_here(self, sid: int):
        with Session(ENGINE) as s:
            x = s.get(Shop, sid)
            if x:
                x.ships_here = not x.ships_here
                s.add(x)
                s.commit()
        self._shops = [{**r, "ships_here": not r["ships_here"]}
                       if r["id"] == sid else r for r in self._shops]

    @rx.event
    def remove(self, sid: int):
        with Session(ENGINE) as s:
            x = s.get(Shop, sid)
            if x:
                x.dismissed = True
                s.add(x)
                s.commit()
        self.load()
        self.notice = "removed"


# ---- page -----------------------------------------------------------------
def _row(r: rx.Var) -> rx.Component:
    return rx.table.row(
        rx.table.cell(rx.box(class_name="hue",
                             style={"background": r.hue, "minHeight": "1.1rem"}),
                      style={"width": "8px", "padding": "0 0 0 6px"}),
        rx.table.row_header_cell(
            rx.cond(
                ShopState.edit_mode,
                rx.input(default_value=r.name, size="1", width="100%",
                         key=f"{r.id}-name",
                         on_blur=ShopState.edit_shop(r.id, "name")),
                rx.cond(r.url != "",
                        rx.link(r.name, href=r.url, is_external=True, size="2"),
                        rx.text(r.name, size="2")),
            ),
        ),
        rx.table.cell(
            rx.cond(
                ShopState.edit_mode,
                rx.select(ShopState.kind_options, value=r.kind, size="1",
                          width="100%", key=f"{r.id}-kind",
                          on_change=ShopState.edit_shop(r.id, "kind")),
                rx.cond(r.kind != "",
                        rx.badge(r.kind, style={"background": r.hue,
                                                "color": "var(--ink)"}),
                        rx.fragment()),
            ),
        ),
        rx.table.cell(
            rx.cond(
                ShopState.edit_mode,
                rx.input(default_value=r.good_for, size="1", width="100%",
                         placeholder="what they are good at",
                         key=f"{r.id}-good",
                         on_blur=ShopState.edit_shop(r.id, "good_for")),
                rx.cond(
                    r.good_for != "",
                    rx.text(r.good_for, class_name="prose",
                            style={"fontSize": "0.82rem"}),
                    rx.text("no note yet", size="1",
                            style={"color": "var(--dim)", "fontStyle": "italic"}),
                ),
            ),
        ),
        IN.rating_cell(r.rating, ShopState.set_inline(r.id, "rating"),
                       key=f"{r.id}-rating"),
        IN.notes_cell(r.notes, ShopState.set_inline(r.id, "notes"),
                      key=f"{r.id}-notes"),
        rx.table.cell(
            rx.cond(
                ShopState.edit_mode,
                rx.select(ShopState.band_options, value=r.price_band, size="1",
                          width="100%", key=f"{r.id}-band",
                          on_change=ShopState.edit_shop(r.id, "price_band")),
                rx.text(r.price_band, size="1", style={"color": "var(--steel)"}),
            ),
        ),
        rx.table.cell(
            rx.button(
                rx.cond(r.ships_here, "ships here", "does not ship"),
                on_click=ShopState.toggle_ships_here(r.id), size="1",
                variant="surface",
                color_scheme=rx.cond(r.ships_here, "green", "red"),
            ),
            style={"whiteSpace": "nowrap"},
        ),
        rx.table.cell(
            rx.vstack(
                rx.cond(
                    r.never_ordered,
                    rx.badge("never ordered", size="1",
                             style={"background": "transparent",
                                    "border": "1px dashed var(--rule)",
                                    "color": "var(--dim)"}),
                    rx.text(r.order_count, size="1", class_name="tnum",
                            style={"color": "var(--mustard)"}),
                ),
                rx.text(r.last_ordered, size="1", style={"color": "var(--dim)"}),
                spacing="0", align="start",
            ),
            style={"whiteSpace": "nowrap"},
        ),
        rx.table.cell(
            rx.hstack(
                rx.button("Ordered", on_click=ShopState.ordered(r.id), size="1",
                          variant="surface"),
                rx.cond(ShopState.edit_mode,
                        rx.button("Remove", size="1", variant="ghost",
                                  color_scheme="red",
                                  on_click=ShopState.remove(r.id)),
                        rx.fragment()),
                spacing="1", align="center",
            ),
            style={"whiteSpace": "nowrap"},
        ),
    )


def _kind_chip(k: rx.Var) -> rx.Component:
    return rx.button(
        rx.hstack(rx.text(k["name"], size="1"),
                  rx.text(k["count"], size="1", class_name="tnum",
                          style={"opacity": "0.6"}),
                  spacing="1", align="center"),
        size="1", variant=rx.cond(k["on"], "solid", "surface"),
        on_click=ShopState.set_kind_filter(k["name"]),
        style={"margin": "0", "borderRadius": "2px",
               "background": rx.cond(k["on"], k["hue"], "transparent"),
               "border": rx.cond(k["on"], "1px solid var(--bone)",
                                 "1px solid var(--rule)"),
               "color": rx.cond(k["on"], "var(--ink)", "var(--steel)")},
    )


def _band_chip(b: rx.Var) -> rx.Component:
    return rx.button(
        rx.hstack(rx.text(b["name"], size="1"),
                  rx.text(b["count"], size="1", class_name="tnum",
                          style={"opacity": "0.6"}),
                  spacing="1", align="center"),
        size="1", variant=rx.cond(b["on"], "solid", "surface"),
        on_click=ShopState.set_band_filter(b["name"]),
        style={"margin": "0", "borderRadius": "2px",
               "background": rx.cond(b["on"], "var(--teal)", "transparent"),
               "border": rx.cond(b["on"], "1px solid var(--teal)",
                                 "1px solid var(--rule)"),
               "color": rx.cond(b["on"], "var(--ink)", "var(--steel)")},
    )


def section(heading: str = "5") -> rx.Component:
    """This page's body, with no container and no navbar.

    /household stacks four of these. /shops held 1 shop and
    does not need a tab of its own, so the route redirects and this is all that
    survived of page().
    """
    return rx.vstack(
        rx.hstack(
            rx.heading("Shopping", size=heading, as_="h2"),
            rx.spacer(),
            rx.vstack(
                rx.text(ShopState.summary, size="1", class_name="tnum",
                        style={"color": "var(--dim)"}),
                rx.cond(
                    ShopState.undescribed > 0,
                    rx.text(ShopState.undescribed.to_string()
                            + " with no note on what they are good for",
                            size="1", style={"color": "var(--mustard)"}),
                    rx.fragment(),
                ),
                spacing="0", align="end",
            ),
            width="100%", align="end",
        ),

        rx.hstack(
            rx.input(placeholder="Shop", value=ShopState.new_name,
                     on_change=ShopState.set_new_name, width="11rem"),
            rx.input(placeholder="website", value=ShopState.new_url,
                     on_change=ShopState.set_new_url, width="13rem"),
            rx.select(ShopState.kind_options, value=ShopState.new_kind,
                      placeholder="Kind",
                      on_change=ShopState.set_new_kind, width="9rem"),
            rx.input(placeholder="what they are good at",
                     value=ShopState.new_good_for,
                     on_change=ShopState.set_new_good_for, width="16rem"),
            rx.button("Add", on_click=ShopState.add_shop, size="2"),
            rx.spacer(),
            rx.button(rx.cond(ShopState.edit_mode, "Done", "Edit"),
                      on_click=ShopState.toggle_edit, size="1",
                      variant=rx.cond(ShopState.edit_mode, "solid", "surface")),
            width="100%", align="center", spacing="2", wrap="wrap",
        ),

        rx.hstack(
            rx.input(placeholder="Search name or notes",
                     value=ShopState.search,
                     on_change=ShopState.set_search, width="16rem"),
            rx.button(ShopState.rating_label, size="1",
                      variant=rx.cond(ShopState.min_rating > 0,
                                      "solid", "surface"),
                      on_click=ShopState.cycle_rating),
            rx.button(rx.cond(ShopState.ships_only,
                              "ships here only", "anywhere"),
                      size="1",
                      variant=rx.cond(ShopState.ships_only, "solid", "surface"),
                      on_click=ShopState.toggle_ships),
            rx.button(rx.cond(ShopState.unordered_only,
                              "never ordered", "all shops"),
                      size="1",
                      variant=rx.cond(ShopState.unordered_only, "solid", "surface"),
                      on_click=ShopState.toggle_unordered),
            rx.button("Clear", size="1", variant="ghost",
                      on_click=ShopState.clear_filters),
            spacing="2", align="center", class_name="filter-row", wrap="wrap",
        ),
        rx.hstack(
            rx.text("Kind", size="1",
                    style={"color": "var(--dim)", "minWidth": "3.5rem",
                           "flex": "0 0 3.5rem", "paddingTop": "0.18rem"}),
            rx.box(rx.hstack(rx.foreach(ShopState.kind_rows, _kind_chip),
                             spacing="2", wrap="wrap"),
                   class_name="filter-row", width="100%"),
            width="100%", align="start", spacing="2",
        ),
        rx.cond(
            ShopState.band_rows,
            rx.hstack(
                rx.text("Price", size="1",
                        style={"color": "var(--dim)", "minWidth": "3.5rem",
                               "flex": "0 0 3.5rem", "paddingTop": "0.18rem"}),
                rx.box(rx.hstack(rx.foreach(ShopState.band_rows, _band_chip),
                                 spacing="2", wrap="wrap"),
                       class_name="filter-row", width="100%"),
                width="100%", align="start", spacing="2",
            ),
            rx.fragment(),
        ),

        notice_toast(ShopState.notice),
        rx.cond(
            ShopState.rows,
            rx.box(
                rx.table.root(
                    rx.table.header(rx.table.row(*[
                        *header_cells("~Colour", "Shop", "Kind", "Good for", "Rating", "Notes",
                                      "Price", "Delivery", "Orders", "~Actions")])),
                    rx.table.body(rx.foreach(ShopState.rows, _row)),
                    variant="surface", size="1",
                    # Radix tables are width:100%, so on a phone they compress to fit and the
                    # overflow_x wrapper never scrolls — the width comes out of the columns
                    # instead. A floor below 48em makes the wrapper scroll, which is the
                    # ordinary phone table. Tiers: initial, xs 30em, sm 48em, md, lg.
                    min_width=["34rem", "34rem", "auto", "auto", "auto"],
                ),
                width="100%", overflow_x="auto",
            ),
            rx.text("Nothing matches. Add a shop above, or clear the "
                    "filters.", class_name="prose"),
        ),
        rx.text("Sorted by your rating, then by how often you have ordered. "
                "The note on what a shop is good at is the point of the "
                "row — the address you could have bookmarked.",
                size="1", style={"color": "var(--dim)"}),
        spacing="4", width="100%", align="start",
    )
