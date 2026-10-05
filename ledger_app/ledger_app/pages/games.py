"""Games you play together.

Separate from Place because these have no country, no coordinates and a URL
instead of a map link.
The Tonight page deals from this table, preferring whatever you have played
least, so a list that grows keeps working without any change there.
"""
from __future__ import annotations

import dataclasses
import datetime as dt

import reflex as rx

from ..core.ui import choice_row, notice_toast
from sqlmodel import Session, select

from ..core.models import Game
from ..core.state import ENGINE
from ..core import inline as IN
from ..core import verdicts as V

KINDS = ["board", "detective", "couples", "party", "video", "card", "mobile"]
KIND_HUE = {"board": "var(--mustard)", "detective": "#8A7DD8",
            "couples": "#C43A6E", "party": "var(--teal)",
            "video": "#6FBF73", "card": "var(--steel)",
            # a category, not a section — the phone games sit with the rest
            "mobile": "#4FA3C7"}


@dataclasses.dataclass
class GameRow:
    id: int
    name: str
    url: str
    kind: str
    hue: str
    players: str
    note: str
    rating: str
    played: str
    last: str
    spicy: bool
    remote: bool
    verdicts: dict[str, str]


class GameState(rx.State):
    _games: list[dict] = []
    _verdicts: dict[str, dict[str, str]] = {}
    unvoted: str = ""             # a person: only the games they have not voted on
    tried_filter: str = ""        # "" = all, "yes" = played at least once, "no" = never
    notice: str = ""
    edit_mode: bool = False
    kind_filter: str = ""
    remote_only: bool = False

    new_name: str = ""
    new_url: str = ""
    new_kind: str = ""

    @rx.event
    def set_inline(self, row_id: int, field: str, value: str):
        """Rating or note, on blur. The column is `note` here; core/inline.py
        resolves that, so the call reads the same as every other table's."""
        msg = IN.save(Game, row_id, field, value)
        if msg:
            self.notice = msg
            if not msg.startswith("a rating is"):
                key = "note" if field == "notes" else field
                v = value.strip()
                self._games = [{**g, key: v} if g["id"] == row_id else g
                               for g in self._games]

    @rx.event
    def load(self):
        with Session(ENGINE) as s:
            self._games = [{
                "id": g.id, "name": g.name, "url": g.url, "kind": g.kind,
                "players": g.players, "note": g.note, "spicy": g.spicy,
                "rating": IN.shown(g.rating),
                "remote": g.remote_ok, "played": g.played_count,
                "last": g.last_played.isoformat() if g.last_played else "",
            } for g in s.exec(select(Game)).all() if not g.dismissed]
        self._games.sort(key=lambda r: (-r["played"], r["name"].lower()))
        self._read_verdicts()

    def _read_verdicts(self):
        self._verdicts = {str(k): v for k, v in
                          V.read("game", [g["id"] for g in self._games]).items()}

    def _held(self, row_id: int) -> dict[str, str]:
        """Every person is always a key: the control reads verdicts[person]."""
        got = self._verdicts.get(str(row_id), {})
        return {p: got.get(p, "") for p in V.PEOPLE}

    def _matches(self) -> list[dict]:
        return [g for g in self._games
                if (not self.kind_filter or g["kind"] == self.kind_filter)
                and (not self.remote_only or g["remote"])
                and (not self.tried_filter
                     or (g["played"] > 0) == (self.tried_filter == "yes"))
                and (not self.unvoted or not self._held(g["id"])[self.unvoted])]

    @rx.var
    def rows(self) -> list[GameRow]:
        return [GameRow(
            id=g["id"], name=g["name"], url=g["url"], kind=g["kind"],
            hue=KIND_HUE.get(g["kind"], "var(--rule)"), players=g["players"],
            note=g["note"], rating=g["rating"], played=str(g["played"]) if g["played"] else "",
            last=g["last"], spicy=g["spicy"], remote=g["remote"],
            verdicts=self._held(g["id"]),
        ) for g in self._matches()]

    @rx.var
    def summary(self) -> str:
        if not self._games:
            return "no games yet"
        played = sum(1 for g in self._games if g["played"])
        return f"{len(self._games)} games, {played} played"

    @rx.var
    def kind_rows(self) -> list[dict[str, str]]:
        from collections import Counter
        c = Counter(g["kind"] for g in self._games if g["kind"])
        return [{"name": k, "count": str(n), "hue": KIND_HUE.get(k, "var(--rule)"),
                 "on": self.kind_filter == k} for k, n in sorted(c.items())]

    @rx.var
    def kind_options(self) -> list[str]:
        return KINDS

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
    def set_kind_filter(self, k: str):
        self.kind_filter = "" if k == self.kind_filter else k

    @rx.event
    def toggle_remote(self):
        self.remote_only = not self.remote_only

    @rx.event
    async def set_verdict(self, row_id: int, person: str, value: str):
        if await V.write_as(self, "game", row_id, person, value):
            self._read_verdicts()

    @rx.event
    def set_unvoted(self, person: str):
        self.unvoted = "" if person == self.unvoted else person

    @rx.event
    def set_tried(self, v: str):
        self.tried_filter = "" if v == self.tried_filter else v

    @rx.event
    def toggle_edit(self):
        self.edit_mode = not self.edit_mode

    @rx.event
    def add_game(self):
        name = self.new_name.strip()
        if not name:
            self.notice = "a game needs a name"
            return
        with Session(ENGINE) as s:
            s.add(Game(name=name, url=self.new_url.strip(),
                       kind=self.new_kind if self.new_kind in KINDS else ""))
            s.commit()
        self.new_name = self.new_url = self.new_kind = ""
        self.load()
        self.notice = f"added {name}"

    @rx.event
    def edit_game(self, gid: int, field: str, value: str):
        v = value.strip()
        with Session(ENGINE) as s:
            g = s.get(Game, gid)
            if not g:
                return
            if field == "name" and not v:
                self.notice = "a game needs a name"
                return
            if field == "kind":
                g.kind = v if v in KINDS else ""
            else:
                setattr(g, field, v)
            s.add(g)
            s.commit()
        self.load()

    @rx.event
    def played(self, gid: int):
        """Same write the Tonight card makes, so the count is one number."""
        with Session(ENGINE) as s:
            g = s.get(Game, gid)
            if g:
                g.played_count += 1
                g.last_played = dt.date.today()
                s.add(g)
                s.commit()
        self.load()

    @rx.event
    def toggle_flag(self, gid: int, field: str):
        with Session(ENGINE) as s:
            g = s.get(Game, gid)
            if g:
                setattr(g, field, not getattr(g, field))
                s.add(g)
                s.commit()
        self.load()

    @rx.event
    def remove(self, gid: int):
        with Session(ENGINE) as s:
            g = s.get(Game, gid)
            if g:
                g.dismissed = True      # tombstone, so a re-import cannot undo it
                s.add(g)
                s.commit()
        self.load()
        self.notice = "removed"


# ---- page -----------------------------------------------------------------
def _row(g: rx.Var) -> rx.Component:
    return rx.table.row(
        rx.table.cell(rx.box(class_name="hue",
                             style={"background": g.hue, "minHeight": "1.1rem"}),
                      style={"width": "8px", "padding": "0 0 0 6px"}),
        rx.table.cell(V.control(g.verdicts, lambda person, value:
                                GameState.set_verdict(g.id, person, value))),
        rx.table.row_header_cell(
            rx.cond(
                GameState.edit_mode,
                rx.input(default_value=g.name, size="1", width="100%",
                         key=f"{g.id}-name",
                         on_blur=GameState.edit_game(g.id, "name")),
                rx.cond(g.url != "",
                        rx.link(g.name, href=g.url, is_external=True, size="2"),
                        rx.text(g.name, size="2")),
            ),
        ),
        rx.table.cell(
            rx.cond(
                GameState.edit_mode,
                rx.select(GameState.kind_options, value=g.kind, size="1",
                          width="100%", key=f"{g.id}-kind",
                          on_change=GameState.edit_game(g.id, "kind")),
                rx.text(g.kind, size="1", style={"color": "var(--steel)"}),
            ),
        ),
        rx.table.cell(
            rx.cond(
                GameState.edit_mode,
                rx.input(default_value=g.players, size="1", width="5rem",
                         placeholder="2-6", key=f"{g.id}-players",
                         on_blur=GameState.edit_game(g.id, "players")),
                rx.text(g.players, size="1", class_name="tnum",
                        style={"color": "var(--dim)"}),
            ),
        ),
        rx.table.cell(
            rx.hstack(
                rx.cond(g.remote,
                        rx.badge("remote", style={"background": "var(--plate2)",
                                                  "color": "var(--steel)"}),
                        rx.fragment()),
                rx.cond(g.spicy,
                        rx.badge("spicy", style={"background": "#C43A6E",
                                                 "color": "var(--ink)"}),
                        rx.fragment()),
                spacing="1", wrap="wrap",
            ),
        ),
        IN.rating_cell(g.rating, GameState.set_inline(g.id, "rating"),
                       key=f"{g.id}-rating"),
        IN.notes_cell(g.note, GameState.set_inline(g.id, "notes"),
                      key=f"{g.id}-note"),
        rx.table.cell(
            rx.vstack(
                rx.text(g.played, size="1", class_name="tnum",
                        style={"color": "var(--mustard)"}),
                rx.text(g.last, size="1", style={"color": "var(--dim)"}),
                spacing="0", align="start",
            ),
            style={"whiteSpace": "nowrap"},
        ),
        rx.table.cell(
            rx.hstack(
                rx.button("Played", on_click=GameState.played(g.id), size="1",
                          variant="surface"),
                rx.cond(
                    GameState.edit_mode,
                    rx.hstack(
                        rx.button("spicy", size="1", variant="ghost",
                                  on_click=GameState.toggle_flag(g.id, "spicy")),
                        rx.button("remote", size="1", variant="ghost",
                                  on_click=GameState.toggle_flag(g.id, "remote_ok")),
                        rx.button("Remove", size="1", variant="ghost",
                                  color_scheme="red",
                                  on_click=GameState.remove(g.id)),
                        spacing="1",
                    ),
                    rx.fragment(),
                ),
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
        on_click=GameState.set_kind_filter(k["name"]),
        style={"margin": "0", "borderRadius": "2px",
               "background": rx.cond(k["on"], k["hue"], "transparent"),
               "border": rx.cond(k["on"], "1px solid " + k["hue"].to(str),
                                 "1px solid var(--rule)"),
               "color": rx.cond(k["on"], "var(--ink)", "var(--steel)")},
    )


def section(heading: str = "5") -> rx.Component:
    """This page's body, with no container and no navbar.

    /household stacks four of these. /games held 4 games and
    does not need a tab of its own, so the route redirects and this is all that
    survived of page().
    """
    return rx.vstack(
        rx.hstack(
            rx.heading("Games", size=heading),
            rx.spacer(),
            rx.text(GameState.summary, size="1", class_name="tnum",
                    style={"color": "var(--dim)"}),
            width="100%", align="end",
        ),
        rx.hstack(
            rx.input(placeholder="Game", value=GameState.new_name,
                     on_change=GameState.set_new_name, width="14rem"),
            rx.input(placeholder="https://", value=GameState.new_url,
                     on_change=GameState.set_new_url, width="16rem"),
            rx.select(GameState.kind_options, value=GameState.new_kind,
                      placeholder="Kind",
                      on_change=GameState.set_new_kind, width="9rem"),
            rx.button("Add game", on_click=GameState.add_game, size="2"),
            rx.spacer(),
            rx.button(rx.cond(GameState.edit_mode, "Done", "Edit"),
                      on_click=GameState.toggle_edit, size="1",
                      variant=rx.cond(GameState.edit_mode, "solid", "surface")),
            width="100%", align="center", spacing="2", wrap="wrap",
        ),
        rx.hstack(
            rx.foreach(GameState.kind_rows, _kind_chip),
            rx.button("All", size="1", variant="ghost",
                      on_click=GameState.set_kind_filter("")),
            rx.button(rx.cond(GameState.remote_only,
                              "remote only", "any distance"),
                      size="1",
                      variant=rx.cond(GameState.remote_only, "solid", "surface"),
                      on_click=GameState.toggle_remote),
            spacing="2", align="center", class_name="filter-row", wrap="wrap",
        ),
        choice_row("played", GameState.tried_filter, GameState.set_tried,
                   [("yes", "Played"), ("no", "Not yet")]),
        V.unvoted_row(GameState),
        notice_toast(GameState.notice),
        rx.cond(
            GameState.rows,
            rx.box(
                rx.table.root(
                    rx.table.header(rx.table.row(*[
                        rx.table.column_header_cell(x) for x in
                        ("", "Us", "Game", "Kind", "Players", "", "Rating", "Note",
                         "Played", "")])),
                    rx.table.body(rx.foreach(GameState.rows, _row)),
                    variant="surface", size="1",
                    # Radix tables are width:100%, so on a phone they compress to fit and the
                    # overflow_x wrapper never scrolls — the width comes out of the columns
                    # instead. A floor below 48em makes the wrapper scroll, which is the
                    # ordinary phone table. Tiers: initial, xs 30em, sm 48em, md, lg.
                    min_width=["34rem", "34rem", "auto", "auto", "auto"],
                ),
                width="100%", overflow_x="auto",
            ),
            rx.text("Nothing matches. Add one above, or clear the filters.",
                    class_name="prose"),
        ),
        rx.text("Tonight deals whichever of these you have played least. "
                "Spicy ones stay out of that rotation unless you turn them "
                "on there.", size="1", style={"color": "var(--dim)"}),
        spacing="4", width="100%", align="start",
    )
