"""Travel planning.

Scaffolding, deliberately. A trip is a name, a country, a date range and notes;
that is enough to start filing the ideas you already have without guessing at an
itinerary model you have not asked for yet.

What it is built to grow into, and why the shape is this and not more:
`Place` already holds 1488 rows with a country, so a trip's shortlist should be
*selected from* those rather than retyped. That link needs a join table and a
picker, which is a real feature rather than a placeholder, so it is not here.
"""
from __future__ import annotations

import dataclasses
import datetime as dt

import reflex as rx
from sqlmodel import Session, select

from ..core.models import Place, Trip
from ..core.state import ENGINE
from ..core.ui import (COUNTRIES, NO_COUNTRY, header_cells, country_code, country_hue,
                  country_name, notice_toast)


@dataclasses.dataclass
class TripRow:
    id: int
    name: str
    country: str
    hue: str
    when: str
    nights: str
    status: str
    notes: str
    places: str


class TravelState(rx.State):
    _trips: list[dict] = []
    notice: str = ""
    edit_mode: bool = False

    new_name: str = ""
    new_country: str = ""
    new_start: str = ""
    new_end: str = ""

    @rx.event
    def load(self):
        today = dt.date.today()
        with Session(ENGINE) as s:
            places = [p for p in s.exec(select(Place)).all() if not p.dismissed]
            by_country: dict[str, int] = {}
            for p in places:
                if p.country:
                    by_country[p.country] = by_country.get(p.country, 0) + 1
            rows = []
            for t in s.exec(select(Trip)).all():
                nights = ((t.end_on - t.start_on).days
                          if t.start_on and t.end_on else None)
                rows.append({
                    "id": t.id, "name": t.name, "country": t.country,
                    "start": t.start_on.isoformat() if t.start_on else "",
                    "end": t.end_on.isoformat() if t.end_on else "",
                    "nights": str(nights) if nights is not None else "",
                    "notes": t.notes,
                    "status": ("past" if t.end_on and t.end_on < today
                               else "planned" if t.start_on else "idea"),
                    "places": str(by_country.get(t.country, 0)),
                    "sort": t.start_on or dt.date(9999, 1, 1),
                })
            self._trips = sorted(rows, key=lambda r: r["sort"])
        if not self.new_start:
            self.new_start = dt.date.today().isoformat()

    @rx.var
    def rows(self) -> list[TripRow]:
        return [TripRow(
            id=r["id"], name=r["name"], country=country_name(r["country"]),
            hue=country_hue(r["country"]),
            when=(f"{r['start']} → {r['end']}" if r["start"] and r["end"]
                  else r["start"] or "no dates yet"),
            nights=(f"{r['nights']} nights" if r["nights"] else ""),
            status=r["status"], notes=r["notes"], places=r["places"],
        ) for r in self._trips]

    @rx.var
    def summary(self) -> str:
        if not self._trips:
            return "no trips yet"
        planned = sum(1 for t in self._trips if t["status"] == "planned")
        return f"{len(self._trips)} trips, {planned} with dates"

    @rx.var
    def country_options(self) -> list[str]:
        return [NO_COUNTRY] + sorted(COUNTRIES.values())

    # ---- events -----------------------------------------------------------
    @rx.event
    def set_new_name(self, v: str):
        self.new_name = v

    @rx.event
    def set_new_country(self, v: str):
        self.new_country = v

    @rx.event
    def set_new_start(self, v: str):
        self.new_start = v

    @rx.event
    def set_new_end(self, v: str):
        self.new_end = v

    @rx.event
    def toggle_edit(self):
        self.edit_mode = not self.edit_mode

    @staticmethod
    def _date(v: str):
        try:
            return dt.date.fromisoformat(v.strip()) if v.strip() else None
        except ValueError:
            return "bad"

    @rx.event
    def add_trip(self):
        name = self.new_name.strip()
        if not name:
            self.notice = "a trip needs a name"
            return
        start, end = self._date(self.new_start), self._date(self.new_end)
        if start == "bad" or end == "bad":
            self.notice = "dates must be YYYY-MM-DD"
            return
        if start and end and end < start:
            self.notice = "the end is before the start"
            return
        with Session(ENGINE) as s:
            if s.exec(select(Trip).where(Trip.name == name)).first():
                self.notice = f"{name} already exists"
                return
            s.add(Trip(name=name, country=country_code(self.new_country),
                       start_on=start, end_on=end))
            s.commit()
        self.new_name = self.new_end = ""
        self.load()
        self.notice = f"added {name}"

    @rx.event
    def edit_trip(self, tid: int, field: str, value: str):
        v = value.strip()
        with Session(ENGINE) as s:
            t = s.get(Trip, tid)
            if not t:
                return
            if field == "name":
                if not v:
                    self.notice = "a trip needs a name"
                    return
                t.name = v
            elif field == "country":
                t.country = country_code(v)
            elif field == "notes":
                t.notes = v
            elif field in ("start_on", "end_on"):
                d = self._date(v)
                if d == "bad":
                    self.notice = f"{v} is not a date — use YYYY-MM-DD"
                    return
                setattr(t, field, d)
            s.add(t)
            s.commit()
        self.load()

    @rx.event
    def delete_trip(self, tid: int):
        with Session(ENGINE) as s:
            t = s.get(Trip, tid)
            if t:
                s.delete(t)          # no importer recreates trips, so a real delete
                s.commit()
        self.load()
        self.notice = "removed"


# ---- page -----------------------------------------------------------------
def _row(t: rx.Var) -> rx.Component:
    return rx.table.row(
        rx.table.cell(rx.box(class_name="hue", style={"background": t.hue,
                                                      "minHeight": "1.1rem"}),
                      style={"width": "8px", "padding": "0 0 0 6px"}),
        rx.table.row_header_cell(
            rx.cond(
                TravelState.edit_mode,
                rx.input(default_value=t.name, size="1", width="100%",
                         key=f"{t.id}-name",
                         on_blur=TravelState.edit_trip(t.id, "name")),
                rx.text(t.name, size="2"),
            ),
        ),
        rx.table.cell(
            rx.cond(
                TravelState.edit_mode,
                rx.select(TravelState.country_options, value=t.country, size="1",
                          width="100%", key=f"{t.id}-country",
                          on_change=TravelState.edit_trip(t.id, "country")),
                rx.text(t.country, size="1", style={"color": "var(--steel)"}),
            ),
        ),
        rx.table.cell(rx.text(t.when, size="1", class_name="tnum",
                              style={"whiteSpace": "nowrap"})),
        rx.table.cell(rx.text(t.nights, size="1", class_name="tnum",
                              style={"color": "var(--dim)"})),
        rx.table.cell(
            rx.text(t.status, size="1",
                    style={"color": rx.cond(t.status == "planned", "var(--mustard)",
                                            "var(--dim)")}),
        ),
        rx.table.cell(rx.text(t.places, size="1", class_name="tnum",
                              style={"color": "var(--dim)"})),
        rx.table.cell(
            rx.cond(
                TravelState.edit_mode,
                rx.input(default_value=t.notes, size="1", width="100%",
                         key=f"{t.id}-notes", placeholder="notes",
                         on_blur=TravelState.edit_trip(t.id, "notes")),
                rx.text(t.notes, class_name="prose", style={"fontSize": "0.85rem"}),
            ),
        ),
        rx.table.cell(
            rx.cond(TravelState.edit_mode,
                    rx.button("Remove", on_click=TravelState.delete_trip(t.id),
                              size="1", variant="ghost", color_scheme="red"),
                    rx.fragment()),
        ),
        class_name="row-place",
    )


def section(heading: str = "5") -> rx.Component:
    """This page's body, with no container and no navbar.

    /household stacks four of these. /travel held 1 trip and
    does not need a tab of its own, so the route redirects and this is all that
    survived of page().
    """
    return rx.vstack(
        rx.hstack(
            rx.heading("Travel", size=heading, as_="h2"),
            rx.spacer(),
            rx.text(TravelState.summary, size="1", class_name="tnum",
                    style={"color": "var(--dim)"}),
            width="100%", align="end",
        ),
        rx.hstack(
            rx.input(placeholder="Trip", value=TravelState.new_name,
                     on_change=TravelState.set_new_name, width="14rem"),
            rx.select(TravelState.country_options, value=TravelState.new_country,
                      placeholder="Country",
                      on_change=TravelState.set_new_country, width="11rem"),
            rx.input(placeholder="start YYYY-MM-DD", value=TravelState.new_start,
                     on_change=TravelState.set_new_start, width="9rem"),
            rx.input(placeholder="end YYYY-MM-DD", value=TravelState.new_end,
                     on_change=TravelState.set_new_end, width="9rem"),
            rx.button("Add trip", on_click=TravelState.add_trip, size="2"),
            rx.spacer(),
            rx.button(rx.cond(TravelState.edit_mode, "Done", "Edit"),
                      on_click=TravelState.toggle_edit, size="1",
                      variant=rx.cond(TravelState.edit_mode, "solid", "surface")),
            width="100%", align="center", spacing="2", wrap="wrap",
        ),
        notice_toast(TravelState.notice),
        rx.cond(
            TravelState.rows,
            rx.box(
                rx.table.root(
                    rx.table.header(rx.table.row(*[
                        *header_cells("~Colour", "Trip", "Country", "When", "Length", "Status",
                                      "Places", "Notes", "~Actions")])),
                    rx.table.body(rx.foreach(TravelState.rows, _row)),
                    variant="surface", size="1",
                ),
                width="100%", overflow_x="auto",
            ),
            rx.text("No trips yet. Add one above — a name is enough, dates can "
                    "come later.", class_name="prose"),
        ),
        rx.text("Places counts the wishlist entries you already have in that "
                "country. Picking specific places into a trip comes next.",
                size="1", style={"color": "var(--dim)"}),
        spacing="4", width="100%", align="start",
    )
