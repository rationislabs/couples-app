"""Plant tracker.

Every other page in this app is a catalogue: it lists what you have. This one
is about an obligation that comes back, so the column that matters is not what
you own but what is overdue today. The table sorts by that and nothing else by
default.

Two things it works out for you rather than storing:

  * when the next watering is due, from the interval and the last date;
  * whether a plant is in a room that gets the light it wants, which is the
    failure that kills houseplants quietly over months rather than visibly in a
    week.

Wishlist plants are rows in the same table with `wishlist` set. They carry the
light and water they will need, so the question "where would this even go" is
answerable before buying rather than after.
"""
from __future__ import annotations

import dataclasses
import datetime as dt

import reflex as rx

from ..core.ui import header_cells, notice_toast
from sqlmodel import Session, select

from ..core.models import Plant
from ..core.state import ENGINE
from ..core import inline as IN

# Ordered darkest to brightest. The index is what makes "is this room bright
# enough" a comparison rather than a lookup table of every pairing.
LIGHT_LEVELS = ["low", "medium", "bright indirect", "bright direct"]
LIGHT_HUE = {"low": "#8998B1", "medium": "#3FB6A8",
             "bright indirect": "#F2A93B", "bright direct": "#E87668"}

# Rooms and the best light they offer. Edit this list as the flat changes; it is
# deliberately code rather than a table because it is a property of the home,
# not of any plant.
ROOM_LIGHT: dict[str, str] = {
    "living room": "bright indirect",
    "bedroom": "medium",
    "kitchen": "bright indirect",
    "bathroom": "low",
    "hallway": "low",
    "balcony": "bright direct",
    "office": "medium",
}
ROOMS = ["— unplaced —"] + sorted(ROOM_LIGHT)


AUTO_HEALTH = "— auto —"
HEALTH_STATES = ["thriving", "wrong light", "thirsty", "parched", "sick", "dying"]


def health_options() -> list[str]:
    return [AUTO_HEALTH] + HEALTH_STATES


def _health(r: dict) -> str:
    """One word for how a plant is doing, from the two facts already known.

    Order matters: a plant in the wrong light that is also three weeks unwatered
    is thirsty first, because that is the one you can fix this minute.
    """
    if r["wishlist"]:
        return ""
    # A human looking at the leaves beats any derivation, so the override wins
    # outright rather than being blended in.
    if r.get("health_override"):
        return r["health_override"]
    if r["due_days"] is not None and r["due_days"] < -7:
        return "parched"
    if r["due_days"] is not None and r["due_days"] < 0:
        return "thirsty"
    if r["fit"]:
        return "wrong light"
    return "thriving"


def _health_hue(r: dict) -> str:
    return {"parched": "var(--vermilion)", "thirsty": "var(--mustard)",
            "wrong light": "#8A7DD8", "thriving": "var(--good)",
            "sick": "var(--vermilion)", "dying": "var(--rose)"}.get(_health(r), "")


@dataclasses.dataclass
class PlantRow:
    id: int
    name: str
    species: str
    room: str
    light_need: str
    light_hue: str
    water_every: str
    last_watered: str
    due: str                  # "overdue by 3 days", "today", "in 5 days"
    due_days: int             # negative means overdue; used for colour
    overdue: bool
    fit: str                  # "" when fine, otherwise what is wrong
    # "add health status to plant tracker". Derived, not stored: every signal
    # it needs is already here, and a column you have to remember to update is
    # a column that is wrong by the second week.
    health: str               # thriving | thirsty | parched | wrong light | sick | dying
    health_hue: str
    health_override: str      # "" when the derived status is being used
    health_note: str
    notes: str
    rating: str
    watered_count: str
    wishlist: bool


class PlantState(rx.State):
    _plants: list[dict] = []
    notice: str = ""
    edit_mode: bool = False
    show: str = "owned"            # owned | wishlist | all
    room_filter: str = ""
    due_only: bool = False

    new_name: str = ""
    new_species: str = ""
    new_room: str = ""
    new_light: str = ""
    new_days: str = ""
    new_wishlist: bool = False

    # ---- loading ----------------------------------------------------------
    @rx.event
    def load(self):
        today = dt.date.today()
        with Session(ENGINE) as s:
            rows = [p for p in s.exec(select(Plant)).all() if not p.dismissed]
        out = []
        for p in rows:
            due_days = self._due_days(p, today)
            out.append({
                "id": p.id, "name": p.name, "species": p.species,
                "room": p.room, "light_need": p.light_need,
                "water_days": p.water_days,
                "last_watered": p.last_watered.isoformat() if p.last_watered else "",
                "watered_count": p.watered_count, "notes": p.notes,
                "rating": IN.shown(p.rating),
                "wishlist": p.wishlist, "due_days": due_days,
                "health_override": p.health_override,
                "health_note": p.health_note,
                "fit": self._fit(p),
            })
        # overdue first, then soonest due, then name. A plant with no interval
        # set sorts last rather than pretending to be urgent.
        out.sort(key=lambda r: (r["wishlist"],
                                999 if r["due_days"] is None else r["due_days"],
                                r["name"].lower()))
        self._plants = out

    @staticmethod
    def _due_days(p: Plant, today: dt.date) -> int | None:
        if not p.water_days:
            return None
        if not p.last_watered:
            return 0  # an interval with no watering logged is due now, not "no schedule"
        return p.water_days - (today - p.last_watered).days

    @staticmethod
    def _fit(p: Plant) -> str:
        """What is wrong with where this plant is standing, in one phrase."""
        if p.wishlist and not p.room:
            return ""
        if not p.room or p.room == "— unplaced —":
            return "no room set"
        if not p.light_need:
            return ""
        room_light = ROOM_LIGHT.get(p.room)
        if room_light is None:
            return ""
        want = LIGHT_LEVELS.index(p.light_need)
        got = LIGHT_LEVELS.index(room_light)
        if got < want:
            return f"{p.room} is too dark"
        if got > want + 1:
            return f"{p.room} may be too bright"
        return ""

    # ---- derived ----------------------------------------------------------
    def _matches(self) -> list[dict]:
        rows = self._plants
        if self.show == "owned":
            rows = [r for r in rows if not r["wishlist"]]
        elif self.show == "wishlist":
            rows = [r for r in rows if r["wishlist"]]
        if self.room_filter:
            rows = [r for r in rows if r["room"] == self.room_filter]
        if self.due_only:
            rows = [r for r in rows
                    if r["due_days"] is not None and r["due_days"] <= 0]
        return rows

    @rx.var
    def rows(self) -> list[PlantRow]:
        out = []
        for r in self._matches():
            d = r["due_days"]
            if r["wishlist"]:
                due, overdue = "", False
            elif d is None:
                due, overdue = "no schedule", False
            elif d < 0:
                due, overdue = f"overdue by {-d}d", True
            elif d == 0:
                due, overdue = ("today" if r["last_watered"] else "never watered — water now"), True
            else:
                due, overdue = f"in {d}d", False
            out.append(PlantRow(
                id=r["id"], name=r["name"], species=r["species"],
                room=r["room"] or "—", light_need=r["light_need"],
                light_hue=LIGHT_HUE.get(r["light_need"], "var(--rule)"),
                water_every=f"every {r['water_days']}d" if r["water_days"] else "",
                last_watered=r["last_watered"], due=due,
                due_days=0 if d is None else d, overdue=overdue,
                fit=r["fit"], health=_health(r), health_hue=_health_hue(r),
                health_override=r["health_override"],
                health_note=r["health_note"], notes=r["notes"], rating=r["rating"],
                watered_count=str(r["watered_count"] or ""),
                wishlist=r["wishlist"],
            ))
        return out

    @rx.var
    def summary(self) -> str:
        owned = [r for r in self._plants if not r["wishlist"]]
        want = len(self._plants) - len(owned)
        due = sum(1 for r in owned
                  if r["due_days"] is not None and r["due_days"] <= 0)
        bits = [f"{len(owned)} plants"]
        if due:
            bits.append(f"{due} need water")
        if want:
            bits.append(f"{want} on the wishlist")
        return " · ".join(bits) if owned or want else "nothing yet"

    @rx.var
    def trouble(self) -> str:
        bad = [r for r in self._plants if r["fit"] and not r["wishlist"]]
        return f"{len(bad)} in the wrong light" if bad else ""

    @rx.var
    def room_rows(self) -> list[dict[str, str]]:
        from collections import Counter
        c = Counter(r["room"] for r in self._plants if r["room"])
        return [{"name": room, "count": str(c.get(room, 0)),
                 "light": ROOM_LIGHT[room], "on": self.room_filter == room}
                for room in sorted(ROOM_LIGHT)]

    @rx.var
    def light_options(self) -> list[str]:
        return LIGHT_LEVELS

    @rx.var
    def room_options(self) -> list[str]:
        return ROOMS

    # ---- events -----------------------------------------------------------
    @rx.event
    def set_new_name(self, v: str):
        self.new_name = v

    @rx.event
    def set_new_species(self, v: str):
        self.new_species = v

    @rx.event
    def set_new_room(self, v: str):
        self.new_room = v

    @rx.event
    def set_new_light(self, v: str):
        self.new_light = v

    @rx.event
    def set_new_days(self, v: str):
        self.new_days = v

    @rx.event
    def toggle_new_wishlist(self):
        self.new_wishlist = not self.new_wishlist

    @rx.event
    def set_show(self, v: str | list[str]):
        self.show = v[0] if isinstance(v, list) else v

    @rx.event
    def set_room_filter(self, r: str):
        self.room_filter = "" if r == self.room_filter else r

    @rx.event
    def toggle_due_only(self):
        self.due_only = not self.due_only

    @rx.event
    def toggle_edit(self):
        self.edit_mode = not self.edit_mode

    @rx.event
    def add_plant(self):
        name = self.new_name.strip()
        if not name:
            self.notice = "a plant needs a name"
            return
        days = self.new_days.strip()
        if days and not days.isdecimal():
            self.notice = f"'{days}' is not a number of days"
            return
        with Session(ENGINE) as s:
            s.add(Plant(
                name=name, species=self.new_species.strip(),
                room="" if self.new_room in ("", "— unplaced —") else self.new_room,
                light_need=self.new_light if self.new_light in LIGHT_LEVELS else "",
                water_days=int(days) if days else None,
                wishlist=self.new_wishlist,
                acquired_on=None if self.new_wishlist else dt.date.today(),
            ))
            s.commit()
        self.new_name = self.new_species = self.new_days = ""
        self.new_room = self.new_light = ""
        self.load()
        self.notice = f"added {name}"

    @rx.event
    def set_health(self, pid: int, state: str):
        """Empty, or "auto", hands the plant back to the derived status."""
        value = "" if state in ("", AUTO_HEALTH) else state
        with Session(ENGINE) as s:
            p = s.get(Plant, pid)
            if p:
                p.health_override = value
                s.add(p)
                s.commit()
        self.load()
        self.notice = f"{'cleared' if not value else value}"

    @rx.event
    def set_health_note(self, pid: int, note: str):
        with Session(ENGINE) as s:
            p = s.get(Plant, pid)
            if p:
                p.health_note = note.strip()
                s.add(p)
                s.commit()
        self.load()

    @rx.event
    def watered(self, pid: int):
        """The whole point of the page. Sets today and clears the notice, so the
        row moves out of the overdue block immediately."""
        with Session(ENGINE) as s:
            p = s.get(Plant, pid)
            if p:
                p.last_watered = dt.date.today()
                p.watered_count += 1
                s.add(p)
                s.commit()
        self.load()

    @rx.event
    def water_all_due(self):
        """One press after going round with the watering can."""
        today = dt.date.today()
        done = 0
        with Session(ENGINE) as s:
            for r in self._matches():
                if r["wishlist"] or r["due_days"] is None or r["due_days"] > 0:
                    continue
                p = s.get(Plant, r["id"])
                if p:
                    p.last_watered = today
                    p.watered_count += 1
                    s.add(p)
                    done += 1
            s.commit()
        self.load()
        self.notice = f"watered {done}" if done else "nothing was due"

    @rx.event
    def set_inline(self, row_id: int, field: str, value: str):
        """Rating or notes, on blur. core/inline.py does the checking."""
        msg = IN.save(Plant, row_id, field, value)
        if msg:
            self.notice = msg
            if not msg.startswith("a rating is"):
                v = value.strip()
                self._plants = [{**r, field: v} if r["id"] == row_id else r
                                for r in self._plants]

    @rx.event
    def edit_plant(self, pid: int, field: str, value: str):
        v = value.strip()
        with Session(ENGINE) as s:
            p = s.get(Plant, pid)
            if not p:
                return
            if field == "name":
                if not v:
                    self.notice = "a plant needs a name"
                    return
                p.name = v
            elif field == "water_days":
                if v and not v.isdecimal():
                    self.notice = f"'{v}' is not a number of days"
                    return
                p.water_days = int(v) if v else None
            elif field == "last_watered":
                try:
                    p.last_watered = dt.date.fromisoformat(v) if v else None
                except ValueError:
                    self.notice = f"'{v}' is not a date — use YYYY-MM-DD"
                    return
            elif field == "room":
                p.room = "" if v == "— unplaced —" else v
            elif field == "light_need":
                p.light_need = v if v in LIGHT_LEVELS else ""
            else:
                setattr(p, field, v)
            s.add(p)
            s.commit()
        self.load()
        self.notice = ""

    @rx.event
    def acquire(self, pid: int):
        """Off the wishlist and into the flat."""
        with Session(ENGINE) as s:
            p = s.get(Plant, pid)
            if p:
                p.wishlist = False
                p.acquired_on = dt.date.today()
                s.add(p)
                s.commit()
        self.load()
        self.notice = "moved off the wishlist"

    @rx.event
    def remove(self, pid: int):
        with Session(ENGINE) as s:
            p = s.get(Plant, pid)
            if p:
                p.dismissed = True
                s.add(p)
                s.commit()
        self.load()
        self.notice = "removed"


# ---- page -----------------------------------------------------------------
def _row(p: rx.Var) -> rx.Component:
    return rx.table.row(
        rx.table.cell(
            rx.box(class_name="hue",
                   style={"background": p.light_hue, "minHeight": "1.1rem"}),
            style={"width": "8px", "padding": "0 0 0 6px"},
        ),
        rx.table.row_header_cell(
            rx.cond(
                PlantState.edit_mode,
                rx.input(default_value=p.name, size="1", width="100%",
                         key=f"{p.id}-name",
                         on_blur=PlantState.edit_plant(p.id, "name")),
                rx.vstack(
                    rx.text(p.name, size="2"),
                    rx.cond(p.species != "",
                            rx.text(p.species, size="1",
                                    style={"color": "var(--dim)",
                                           "fontStyle": "italic"}),
                            rx.fragment()),
                    spacing="0", align="start",
                ),
            ),
        ),
        rx.table.cell(
            rx.cond(
                PlantState.edit_mode,
                rx.select(health_options(),
                          value=rx.cond(p.health_override != "",
                                        p.health_override, AUTO_HEALTH),
                          size="1", width="100%",
                          on_change=lambda v: PlantState.set_health(p.id, v)),
                rx.cond(
                    p.health != "",
                    rx.hstack(
                        rx.badge(p.health, size="1",
                                 style={"background": p.health_hue,
                                        "color": "var(--ink)"}),
                        rx.cond(p.health_override != "",
                                rx.text("set", size="1",
                                        style={"color": "var(--dim)"}),
                                rx.fragment()),
                        spacing="1", align="center",
                    ),
                    rx.fragment(),
                ),
            ),
            style={"whiteSpace": "nowrap"},
        ),
        rx.table.cell(
            rx.cond(
                PlantState.edit_mode,
                rx.select(PlantState.room_options,
                          value=rx.cond(p.room != "—", p.room, "— unplaced —"),
                          size="1", width="100%", key=f"{p.id}-room",
                          on_change=PlantState.edit_plant(p.id, "room")),
                rx.vstack(
                    rx.text(p.room, size="1", style={"color": "var(--steel)"}),
                    rx.cond(p.fit != "",
                            rx.text(p.fit, size="1",
                                    style={"color": "var(--vermilion)"}),
                            rx.fragment()),
                    spacing="0", align="start",
                ),
            ),
        ),
        rx.table.cell(
            rx.cond(
                PlantState.edit_mode,
                rx.select(PlantState.light_options, value=p.light_need, size="1",
                          width="100%", key=f"{p.id}-light",
                          on_change=PlantState.edit_plant(p.id, "light_need")),
                rx.cond(p.light_need != "",
                        rx.badge(p.light_need,
                                 style={"background": p.light_hue,
                                        "color": "var(--ink)"}),
                        rx.fragment()),
            ),
        ),
        rx.table.cell(
            rx.cond(
                PlantState.edit_mode,
                rx.input(default_value=p.water_every, size="1", width="5rem",
                         placeholder="days", key=f"{p.id}-days",
                         on_blur=PlantState.edit_plant(p.id, "water_days")),
                rx.text(p.water_every, size="1", class_name="tnum",
                        style={"color": "var(--dim)"}),
            ),
        ),
        rx.table.cell(
            rx.cond(
                PlantState.edit_mode,
                rx.input(default_value=p.last_watered, size="1", width="7rem",
                         placeholder="YYYY-MM-DD", key=f"{p.id}-last",
                         on_blur=PlantState.edit_plant(p.id, "last_watered")),
                rx.text(p.last_watered, size="1", class_name="tnum",
                        style={"color": "var(--dim)"}),
            ),
        ),
        rx.table.cell(
            rx.text(p.due, size="1", class_name="tnum",
                    style={"color": rx.cond(p.overdue, "var(--vermilion)",
                                            "var(--steel)"),
                           "fontWeight": rx.cond(p.overdue, "700", "400"),
                           "whiteSpace": "nowrap"}),
        ),
        IN.rating_cell(p.rating, PlantState.set_inline(p.id, "rating"),
                       key=f"{p.id}-rating"),
        IN.notes_cell(p.notes, PlantState.set_inline(p.id, "notes"),
                      key=f"{p.id}-notes"),
        rx.table.cell(
            rx.hstack(
                rx.cond(
                    p.wishlist,
                    rx.button("Got it", on_click=PlantState.acquire(p.id),
                              size="1", variant="surface"),
                    rx.button("Watered", on_click=PlantState.watered(p.id),
                              size="1",
                              variant=rx.cond(p.overdue, "solid", "surface")),
                ),
                rx.cond(PlantState.edit_mode,
                        rx.button("Remove", size="1", variant="ghost",
                                  color_scheme="red",
                                  on_click=PlantState.remove(p.id)),
                        rx.fragment()),
                spacing="1", align="center",
            ),
            style={"whiteSpace": "nowrap"},
        ),
    )


def _room_chip(r: rx.Var) -> rx.Component:
    return rx.button(
        rx.hstack(
            rx.text(r["name"], size="1"),
            rx.text(r["count"], size="1", class_name="tnum",
                    style={"opacity": "0.6"}),
            spacing="1", align="center",
        ),
        size="1", variant=rx.cond(r["on"], "solid", "surface"),
        on_click=PlantState.set_room_filter(r["name"]),
        title="light here: " + r["light"],
        style={"margin": "0", "borderRadius": "2px",
               "background": rx.cond(r["on"], "var(--teal)", "transparent"),
               "border": rx.cond(r["on"], "1px solid var(--teal)",
                                 "1px solid var(--rule)"),
               "color": rx.cond(r["on"], "var(--ink)", "var(--steel)")},
    )


def section(heading: str = "5") -> rx.Component:
    """This page's body, with no container and no navbar.

    /household stacks four of these. /plants held 1 plant and
    does not need a tab of its own, so the route redirects and this is all that
    survived of page().
    """
    return rx.vstack(
        rx.hstack(
            rx.heading("Plant Tracker", size=heading, as_="h2"),
            rx.spacer(),
            rx.vstack(
                rx.text(PlantState.summary, size="1", class_name="tnum",
                        style={"color": "var(--dim)"}),
                rx.cond(PlantState.trouble != "",
                        rx.text(PlantState.trouble, size="1",
                                style={"color": "var(--vermilion)"}),
                        rx.fragment()),
                spacing="0", align="end",
            ),
            width="100%", align="end",
        ),

        rx.hstack(
            rx.input(placeholder="Plant", value=PlantState.new_name,
                     on_change=PlantState.set_new_name, width="11rem"),
            rx.input(placeholder="Species", value=PlantState.new_species,
                     on_change=PlantState.set_new_species, width="11rem"),
            rx.select(PlantState.room_options, value=PlantState.new_room,
                      placeholder="Room",
                      on_change=PlantState.set_new_room, width="9rem"),
            rx.select(PlantState.light_options, value=PlantState.new_light,
                      placeholder="Light",
                      on_change=PlantState.set_new_light, width="10rem"),
            rx.input(placeholder="water every N days",
                     value=PlantState.new_days,
                     on_change=PlantState.set_new_days, width="9rem"),
            rx.button(rx.cond(PlantState.new_wishlist,
                              "for the wishlist", "already have it"),
                      size="1", variant="surface",
                      on_click=PlantState.toggle_new_wishlist),
            rx.button("Add", on_click=PlantState.add_plant, size="2"),
            rx.spacer(),
            rx.button(rx.cond(PlantState.edit_mode, "Done", "Edit"),
                      on_click=PlantState.toggle_edit, size="1",
                      variant=rx.cond(PlantState.edit_mode, "solid", "surface")),
            width="100%", align="center", spacing="2", wrap="wrap",
        ),

        rx.hstack(
            rx.segmented_control.root(
                rx.segmented_control.item("Owned", value="owned"),
                rx.segmented_control.item("Wishlist", value="wishlist"),
                rx.segmented_control.item("All", value="all"),
                value=PlantState.show, on_change=PlantState.set_show,
                size="1",
            ),
            rx.button(rx.cond(PlantState.due_only,
                              "showing due only", "needs water"),
                      size="1",
                      variant=rx.cond(PlantState.due_only, "solid", "surface"),
                      on_click=PlantState.toggle_due_only),
            rx.button("Water everything due", size="1", variant="surface",
                      on_click=PlantState.water_all_due),
            spacing="2", align="center", class_name="filter-row", wrap="wrap",
        ),
        rx.hstack(
            rx.text("Room", size="1",
                    style={"color": "var(--dim)", "minWidth": "3.5rem",
                           "flex": "0 0 3.5rem", "paddingTop": "0.18rem"}),
            rx.box(
                rx.hstack(
                    rx.foreach(PlantState.room_rows, _room_chip),
                    rx.button("All", size="1", variant="ghost",
                              on_click=PlantState.set_room_filter("")),
                    spacing="2", wrap="wrap"),
                class_name="filter-row", width="100%",
            ),
            width="100%", align="start", spacing="2",
        ),

        notice_toast(PlantState.notice),
        rx.cond(
            PlantState.rows,
            rx.box(
                rx.table.root(
                    rx.table.header(rx.table.row(*[
                        *header_cells("~Colour", "Plant", "Health", "Room", "Light", "Water",
                                      "Last", "Due", "Rating", "Notes", "~Actions")])),
                    rx.table.body(rx.foreach(PlantState.rows, _row)),
                    variant="surface", size="1",
                ),
                width="100%", overflow_x="auto",
            ),
            rx.text("Nothing here yet. Add a plant above, or switch to the "
                    "wishlist.", class_name="prose"),
        ),
        rx.text("Light needs are matched against the room: a plant wanting "
                "more light than its room gets is flagged in the Room "
                "column. Edit ROOM_LIGHT in plants.py when the flat "
                "changes.", size="1", style={"color": "var(--dim)"}),
        spacing="4", width="100%", align="start",
    )
