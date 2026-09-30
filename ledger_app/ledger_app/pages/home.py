"""Tonight — the front door.

Every other page is a catalogue: it shows you what you own. This one is the
only page that makes a decision. It deals four things for the evening and each
one carries a verb, because the whole app collected 2,500 rows and recorded
almost nothing being done with them. The counters at the top exist to make that
gap visible rather than comfortable.

Nothing here is new data. It draws on the same tables the other pages edit, so
marking something done from here shows up there and vice versa.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import random

import reflex as rx

from ..core.ui import notice_toast
from . import gallery as GL
from geopy.distance import geodesic
from sqlmodel import Session, select

from ..core.models import (ConvoQuestion, CookLog, DateEntry, Game, Garment, Genre,
                     Place, Recipe, Title, TitleGenre, WatchState)
from ..core.state import ENGINE, HOME as HOME_AT


MOODS = ["out to eat", "adventure", "culture", "stay in", "surprise us"]
ALL_CITIES = "every city"
# "any distance" is the only setting that shows the 836 places with no
# coordinates alongside the 638 that have them.
RADII = ["5 km", "15 km", "30 km", "60 km", "any distance"]

# The same five moods, mapped onto genres. "surprise us" is empty, meaning no
# restriction, exactly as it is for places. Genre names are the ones actually in
# the database, checked rather than guessed — a mood that maps to a genre nobody
# tagged would silently deal nothing.
MOOD_GENRES = {
    "out to eat": ["Comedy", "Reality", "Family", "TV Movie"],
    "adventure":  ["Action", "Adventure", "Action & Adventure", "Shonen",
                   "Sports", "Thriller"],
    "culture":    ["Drama", "History", "Historical", "Mystery", "Crime",
                   "Romance", "Seinen"],
    "stay in":    ["Animation", "Fantasy", "Sci-Fi", "Sci-Fi & Fantasy",
                   "Science Fiction", "Supernatural", "Comedy"],
    "surprise us": [],
}

MOOD_TYPES = {
    "out to eat": ["restaurant", "cafe", "bar", "dessert", "deli"],
    "adventure":  ["hike", "gorge", "cave", "climb", "bike", "ski", "lake", "beach"],
    "culture":    ["museum", "castle", "church", "theatre", "garden", "viewpoint"],
    "stay in":    ["at-home"],
    "surprise us": [],
}


@dataclasses.dataclass
class Card:
    kind: str          # place | cook | ask | watch
    title: str
    detail: str
    meta: str
    href: str
    verb: str          # what the button says
    empty: bool


class HomeState(rx.State):
    mood: str = "surprise us"
    near_only: bool = True
    # Places without coordinates are common, so
    # the old `km > 60` test did not filter them out, it hid them. radius_km is
    # the control that constant should always have been; 0 means "any".
    radius_km: int = 60
    city: str = ""            # "" = every city
    include_spicy: bool = False   # off by default; this page sits open
    seed: int = 0
    notice: str = ""

    _cities: list[str] = []
    _geo_known: int = 0
    _geo_total: int = 0

    _place: dict = {}
    _recipe: dict = {}
    _question: dict = {}
    _watch: dict = {}
    _watch_narrowed: bool = False
    _outfit: list[dict] = []
    _game: dict = {}
    _recent: list[dict] = []
    _stats: dict = {}

    # ---- loading ----------------------------------------------------------
    @rx.event
    def load(self):
        """Everything the page shows, read in one pass. Deliberately an event
        and not a computed var: computed vars that read the database go stale
        because Reflex only recomputes them when a tracked var changes."""
        with Session(ENGINE) as s:
            places = [p for p in s.exec(select(Place)).all() if not p.dismissed]
            self._cities = sorted({p.city for p in places if p.city})
            self._geo_total = len(places)
            self._geo_known = sum(1 for p in places if p.lat is not None)
            been = {e.place_id for e in s.exec(select(DateEntry)).all()
                    if e.place_id}
            recipes = s.exec(select(Recipe)).all()
            cooked = {c.recipe_id for c in s.exec(select(CookLog)).all()}
            questions = [q for q in s.exec(select(ConvoQuestion)).all()
                         if not q.dismissed]
            titles = {t.id: t for t in s.exec(select(Title)).all()}
            # Genre names per title, so the watch pick can answer to the mood
            # the same way the place pick does.
            gname = {g.id: g.name for g in s.exec(select(Genre)).all()}
            title_genres: dict[int, set[str]] = {}
            for tg in s.exec(select(TitleGenre)).all():
                title_genres.setdefault(tg.title_id, set()).add(
                    gname.get(tg.genre_id, ""))
            watching = [w for w in s.exec(select(WatchState)).all()
                        if w.state == "watching"]
            wardrobe = [g for g in s.exec(select(Garment)).all()
                        if not g.dismissed]
            games = [g for g in s.exec(select(Game)).all()
                     if not g.dismissed and (self.include_spicy or not g.spicy)]
            self._recent = self._recent_rows(s, titles)

        rng = random.Random(self.seed)

        # --- something to wear, one garment per slot
        #
        # Season comes from the month rather than a control: nobody wants to
        # tell an app it is October. Formality is left open because "smart" is
        # a decision about the evening, not about the wardrobe.
        month = dt.date.today().month
        season = "warm" if 4 <= month <= 9 else "cold"
        self._outfit = []
        for slot in ("top", "bottom", "outer", "shoes", "accent"):
            fits = [g for g in wardrobe
                    if g.slot == slot and g.season in ("", season)]
            # An empty slot is skipped, not faked: no coat in July is correct.
            if not fits:
                continue
            g = rng.choice(fits)
            self._outfit.append({
                "slot": slot, "name": g.name, "colour": g.colour,
                "placeholder": "yes" if g.placeholder else "",
            })

        # --- a place, filtered by mood and optionally by distance
        wanted = MOOD_TYPES.get(self.mood, [])
        pool = []
        for p in places:
            if p.visited or p.id in been or not p.maps_url:
                continue
            types = [t for t in p.tags.split(",") if t]
            if wanted and not any(t in wanted for t in types):
                continue
            km = (geodesic(HOME_AT, (p.lat, p.lon)).km
                  if p.lat is not None and p.lon is not None else None)
            if self.city and (p.city or "") != self.city:
                continue
            # > A place with no coordinates is unknown, not far away. Dropping it
            # > here is what made "within 60 km" quietly mean "of the 43% we
            # > geocoded". Unknowns stay in the pool and say so on the card.
            #
            # Reversed later. Keeping unknowns meant "within 15 km" offered
            # places in other countries, because most places had no lat/lon
            # and most were abroad. An unknown distance is
            # not usable as a suggestion for tonight, whatever it is in theory.
            # A radius now means a radius; without one, unknowns are still in.
            # The real fix is geocoding: scripts/data/geocode_places.py.
            if (self.near_only and self.radius_km and self.mood != "stay in"
                    and (km is None or km > self.radius_km)):
                continue
            pool.append({"id": p.id, "name": p.name, "url": p.maps_url,
                         "city": p.city, "country": p.country,
                         "types": ", ".join(types) or "untagged",
                         "km": f"{km:.0f} km" if km is not None
                         else "distance unknown"})
        self._place = rng.choice(pool) if pool else {}

        # --- something to cook, preferring one never cooked
        fresh = [r for r in recipes if r.id not in cooked] or recipes
        r = rng.choice(fresh) if fresh else None
        self._recipe = ({"id": r.id, "name": r.name, "slug": r.slug,
                         "detail": r.description or "no description saved",
                         "mins": (f"{r.total_minutes} min" if r.total_minutes
                                  else "")} if r else {})

        # --- a question, preferring ones never asked
        unasked = [q for q in questions if not q.asked] or questions
        q = rng.choice(unasked) if unasked else None
        self._question = ({"id": q.id, "text": q.text,
                           "detail": f"{q.audience} · {q.depth}"} if q else {})

        # --- what you are already part-way through
        rows = []
        for w in watching:
            t = titles.get(w.title_id)
            if not t:
                continue
            at = []
            if w.current_season:
                at.append(f"S{w.current_season}")
            if w.current_episode:
                at.append(f"E{w.current_episode}")
            rows.append({"id": w.id, "name": t.name,
                         "genres": title_genres.get(t.id, set()),
                         "at": "".join(at) or "not started",
                         "of": (f"of {t.episodes} episodes" if t.episodes else ""),
                         "medium": t.medium})
        rows.sort(key=lambda x: x["name"].lower())
        # Mood narrows; it never empties. A mood nothing matches falls back to
        # the whole pool rather than dealing an empty card, because "nothing to
        # watch" is a lie when there are 423 titles.
        wanted_g = set(MOOD_GENRES.get(self.mood, []))
        if wanted_g:
            fits = [r for r in rows if r["genres"] & wanted_g]
            self._watch_narrowed = bool(fits)
            rows = fits or rows
        else:
            self._watch_narrowed = False
        self._watch = rng.choice(rows) if rows else {}

        # --- something to play, preferring what you have played least
        if games:
            fewest = min(g.played_count for g in games)
            pick = rng.choice([g for g in games if g.played_count == fewest])
            self._game = {"id": pick.id, "name": pick.name, "url": pick.url,
                          "note": pick.note,
                          "meta": " · ".join(x for x in (pick.kind, pick.players)
                                             if x),
                          "played": pick.played_count}
        else:
            self._game = {}

        self._stats = {
            "places": str(len(places)),
            "visited": str(sum(1 for p in places if p.visited) + len(been)),
            "watching": str(len(rows)),
            "pool": str(len(pool)),
        }

    @staticmethod
    def _recent_rows(s: Session, titles: dict) -> list[dict]:
        """The last few things actually done, newest first. This is the reward
        for pressing the buttons, so it goes on the same screen as them."""
        out = []
        for e in s.exec(select(DateEntry)).all():
            place = s.get(Place, e.place_id) if e.place_id else None
            out.append({"when": e.went_on.isoformat(),
                        "what": (place.name if place else e.place_text) or "a date",
                        "kind": "went"})
        for c in s.exec(select(CookLog)).all():
            r = s.get(Recipe, c.recipe_id)
            out.append({"when": c.cooked_on.isoformat(),
                        "what": r.name if r else "a recipe", "kind": "cooked"})
        out.sort(key=lambda x: x["when"], reverse=True)
        return out[:6]

    # ---- derived ----------------------------------------------------------
    @rx.var
    def cards(self) -> list[Card]:
        p, r, q, w = self._place, self._recipe, self._question, self._watch
        g = self._game
        return [
            Card(kind="place",
                 title=p.get("name", "Nothing matches that mood"),
                 detail=p.get("types", "Widen the mood, or turn off nearby only."),
                 meta=" · ".join(x for x in (p.get("km", ""), p.get("city", "")) if x),
                 href=p.get("url", "/dates"), verb="We went",
                 empty=not p),
            Card(kind="cook",
                 title=r.get("name", "No recipes saved yet"),
                 detail=r.get("detail", "Add one from a link on the Recipes page."),
                 meta=r.get("mins", ""),
                 href=f"/recipes/{r['slug']}" if r else "/recipes",
                 verb="We cooked it", empty=not r),
            Card(kind="ask",
                 title=q.get("text", "No questions left"),
                 detail=q.get("detail", "Import more on the Convo Starter page."),
                 meta="", href="/convo", verb="We talked about it", empty=not q),
            Card(kind="play",
                 title=g.get("name", "No games saved"),
                 detail=g.get("note", "Add one on the Games page."),
                 meta=g.get("meta", ""), href=g.get("url", "/games"),
                 verb="We played it", empty=not g),
            Card(kind="watch",
                 title=w.get("name", "Nothing in progress"),
                 detail=w.get("of", "Mark something as watching in the library."),
                 # Says whether the mood actually narrowed the pick, so a
                 # suggestion that ignored the mood does not look like one that
                 # answered it.
                 meta=" · ".join(x for x in (
                     w.get("at", ""),
                     "fits the mood" if self._watch_narrowed else "") if x),
                 href="/library",
                 verb="Watched one more", empty=not w),
        ]

    @rx.var
    def outfit(self) -> list[dict[str, str]]:
        return self._outfit

    @rx.var
    def outfit_note(self) -> str:
        if not self._outfit:
            return "Nothing in the wardrobe yet — run scripts/seed/seed_wardrobe.py."
        fake = sum(1 for g in self._outfit if g["placeholder"])
        if fake == len(self._outfit):
            return "All placeholders. Replace them with the real thing."
        if fake:
            return f"{fake} still a placeholder"
        return ""

    @rx.var
    def headline(self) -> str:
        return {"out to eat": "Go eat something",
                "adventure": "Get out of town",
                "culture": "Go look at something",
                "stay in": "Stay in",
                "surprise us": "Tonight"}.get(self.mood, "Tonight")

    @rx.var
    def scale_line(self) -> str:
        st = self._stats
        if not st:
            return ""
        return (f"{st.get('visited', '0')} of {st.get('places', '0')} places visited"
                f" · {st.get('pool', '0')} match right now"
                f" · {st.get('watching', '0')} series on the go")

    @rx.var
    def moods(self) -> list[str]:
        return MOODS

    @rx.var
    def recent(self) -> list[dict[str, str]]:
        return self._recent

    @rx.var
    def has_recent(self) -> bool:
        return bool(self._recent)

    # ---- events -----------------------------------------------------------
    @rx.event
    def set_mood(self, m: str):
        self.mood = m
        self.seed += 1
        self.notice = ""
        return HomeState.load

    @rx.event
    def toggle_spicy(self):
        self.include_spicy = not self.include_spicy
        self.seed += 1
        return HomeState.load

    @rx.var
    def city_options(self) -> list[str]:
        return [ALL_CITIES] + self._cities

    @rx.var
    def city_label(self) -> str:
        return self.city or ALL_CITIES

    @rx.var
    def radius_label(self) -> str:
        """Must equal one of RADII exactly, or the select renders unset."""
        return f"{self.radius_km} km" if self.radius_km else "any distance"

    @rx.var
    def coverage(self) -> str:
        """Says out loud how much of the wishlist a distance filter can see.

        Without this the filter looks authoritative on data it does not have.
        """
        unknown = self._geo_total - self._geo_known
        if not unknown:
            return ""
        if self.radius_km:
            return (f"{unknown} of {self._geo_total} places have no location yet "
                    f"and are excluded by a distance filter")
        return f"{unknown} of {self._geo_total} places have no location yet"

    @rx.event
    def toggle_near(self):
        self.near_only = not self.near_only
        self.seed += 1
        return HomeState.load

    @rx.event
    def set_radius(self, label: str):
        """Takes the option text. 0 km means "any", which is the only setting
        that shows the places with no coordinates alongside the rest."""
        digits = "".join(c for c in str(label) if c.isdigit())
        self.radius_km = int(digits) if digits else 0
        self.near_only = self.radius_km > 0
        self.seed += 1
        return HomeState.load

    @rx.event
    def set_city(self, name: str):
        self.city = "" if name in ("", ALL_CITIES) else name
        self.seed += 1
        return HomeState.load

    @rx.event
    def deal(self):
        self.seed += 1
        self.notice = ""
        return HomeState.load

    @rx.event
    def done(self, kind: str):
        """Close the loop. Each card writes to the same table its own page uses,
        so the record is one thing, not a copy."""
        today = dt.date.today()
        with Session(ENGINE) as s:
            if kind == "place" and self._place:
                p = s.get(Place, self._place["id"])
                if p:
                    p.visited = True
                    s.add(p)
                    s.add(DateEntry(place_id=p.id, went_on=today))
                    self.notice = f"logged {p.name}"
            elif kind == "cook" and self._recipe:
                s.add(CookLog(recipe_id=self._recipe["id"], cooked_on=today))
                self.notice = f"logged {self._recipe['name']}"
            elif kind == "ask" and self._question:
                q = s.get(ConvoQuestion, self._question["id"])
                if q:
                    q.asked = True
                    s.add(q)
                    self.notice = "marked asked"
            elif kind == "play" and self._game:
                row = s.get(Game, self._game["id"])
                if row:
                    row.played_count += 1
                    row.last_played = today
                    s.add(row)
                    self.notice = f"logged {row.name}"
            elif kind == "watch" and self._watch:
                w = s.get(WatchState, self._watch["id"])
                if w:
                    w.current_episode = (w.current_episode or 0) + 1
                    w.episodes_played = (w.episodes_played or 0) + 1
                    w.last_played = dt.datetime.now()
                    s.add(w)
                    self.notice = f"{self._watch['name']} → E{w.current_episode}"
            s.commit()
        self.seed += 1
        return HomeState.load


# ---------------------------------------------------------------------------
# View. The place card is deliberately larger than the other three: the whole
# page exists to answer "where are we going", and four identical boxes would
# say all four questions weigh the same.
# ---------------------------------------------------------------------------
KIND_HUE = {"place": "var(--mustard)", "cook": "var(--vermilion)",
            "ask": "var(--teal)", "play": "#6FBF73", "watch": "#8A7DD8"}
KIND_WORD = {"place": "go", "cook": "cook", "ask": "ask", "play": "play",
             "watch": "watch"}


def _card(c: rx.Var, big: bool = False) -> rx.Component:
    hue = KIND_HUE_VAR(c.kind)
    return rx.box(
        rx.vstack(
            rx.hstack(
                rx.text(KIND_WORD_VAR(c.kind), size="1",
                        style={"color": hue, "fontFamily": "'Archivo Narrow', sans-serif",
                               "fontWeight": "700", "letterSpacing": "0.04em"}),
                rx.spacer(),
                rx.cond(c.meta != "",
                        rx.text(c.meta, size="1", class_name="tnum",
                                style={"color": "var(--steel)"}),
                        rx.fragment()),
                width="100%", align="center",
            ),
            rx.cond(
                c.empty,
                rx.text(c.title, size="4",
                        style={"color": "var(--steel)", "fontFamily": "Newsreader, serif"}),
                rx.link(
                    rx.text(c.title,
                            style={"fontFamily": "Newsreader, serif",
                                   "fontWeight": "400", "lineHeight": "1.15",
                                   "color": "var(--bone)",
                                   "fontSize": "1.9rem" if big else "1.25rem"}),
                    href=c.href, is_external=False, underline="none",
                ),
            ),
            rx.text(c.detail, size="1",
                    style={"color": "var(--dim)", "maxWidth": "52ch"}),
            rx.spacer(),
            rx.hstack(
                rx.button(c.verb, on_click=HomeState.done(c.kind), size="2",
                          disabled=c.empty,
                          style={"background": hue, "color": "var(--ink)",
                                 "fontWeight": "700"}),
                rx.link(rx.text("see all", size="1",
                                style={"color": "var(--dim)"}),
                        href=c.href, underline="none"),
                spacing="3", align="center",
            ),
            spacing="2", align="start", height="100%", width="100%",
        ),
        # Only the things that vary stay inline. Everything static moved to
        # .tonight-card, because an inline style beats the stylesheet and this
        # card was the one surface no theme could reach.
        class_name="tonight-card",
        style={"borderLeft": f"3px solid {hue}",
               "minHeight": "12rem" if big else "10.5rem"},
        width="100%",
    )


def KIND_HUE_VAR(kind: rx.Var) -> rx.Var:
    return rx.match(kind, *[(k, v) for k, v in KIND_HUE.items()], "var(--rule)")


def KIND_WORD_VAR(kind: rx.Var) -> rx.Var:
    return rx.match(kind, *[(k, v) for k, v in KIND_WORD.items()], "")


def _outfit_section() -> rx.Component:
    """What to wear, dealt with everything else.

    Its own section rather than a sixth card, because an outfit is five things
    at once and a card holds one. It re-deals with the rest of the page, so
    "Deal again" answers the whole evening rather than part of it.
    """
    def piece(g: rx.Var) -> rx.Component:
        return rx.vstack(
            rx.text(g["slot"], size="1",
                    style={"color": "var(--dim)", "letterSpacing": "0.04em",
                           "fontFamily": "'Archivo Narrow', sans-serif",
                           "textTransform": "uppercase"}),
            rx.text(g["name"], size="2", weight="bold"),
            rx.hstack(
                rx.text(g["colour"], size="1", style={"color": "var(--steel)"}),
                rx.cond(g["placeholder"] != "",
                        rx.badge("placeholder", size="1",
                                 style={"background": "transparent",
                                        "border": "1px dashed var(--rule)",
                                        "color": "var(--dim)"}),
                        rx.fragment()),
                spacing="2", align="center",
            ),
            spacing="1", align="start", class_name="outfit-piece",
        )

    return rx.vstack(
        rx.hstack(
            rx.heading("What to wear", size="5", class_name="block-head"),
            rx.spacer(),
            rx.cond(HomeState.outfit_note != "",
                    rx.text(HomeState.outfit_note, size="1",
                            style={"color": "var(--dim)"}),
                    rx.fragment()),
            width="100%", align="end",
        ),
        rx.cond(
            HomeState.outfit,
            rx.hstack(rx.foreach(HomeState.outfit, piece),
                      spacing="4", wrap="wrap", align="start", width="100%"),
            rx.text("No clothes yet. Run scripts/seed/seed_wardrobe.py for "
                    "placeholders.", class_name="prose"),
        ),
        spacing="3", width="100%", align="start", class_name="block",
    )


def _mood_chip(m: rx.Var) -> rx.Component:
    on = HomeState.mood == m
    return rx.button(
        m, size="2", variant=rx.cond(on, "solid", "surface"),
        on_click=HomeState.set_mood(m),
        class_name="mood-chip",
        style={"margin": "0", "fontWeight": "600",
               "background": rx.cond(on, "var(--bone)", "transparent"),
               "border": rx.cond(on, "1px solid var(--bone)",
                                 "1px solid var(--rule)"),
               "color": rx.cond(on, "var(--ink)", "var(--steel)")},
    )


def _log_line(e: rx.Var) -> rx.Component:
    return rx.hstack(
        rx.text(e["when"], size="1", class_name="tnum",
                style={"color": "var(--dim)", "width": "6rem"}),
        rx.text(e["kind"], size="1",
                style={"color": "var(--steel)", "width": "4rem"}),
        rx.text(e["what"], size="1", style={"color": "var(--bone)"}),
        spacing="2", align="center", width="100%",
    )


def page() -> rx.Component:
    from ..core.ui import navbar
    return rx.container(
        rx.vstack(
            navbar("/"),
            rx.hstack(
                rx.vstack(
                    rx.heading(HomeState.headline, size="8",
                               style={"fontFamily": "Newsreader, serif",
                                      "fontWeight": "400"}),
                    rx.text(HomeState.scale_line, size="1", class_name="tnum",
                            style={"color": "var(--dim)"}),
                    spacing="1", align="start",
                ),
                rx.spacer(),
                rx.button("Deal again", on_click=HomeState.deal, size="3",
                          variant="surface"),
                width="100%", align="end",
            ),
            rx.hstack(
                rx.foreach(HomeState.moods, _mood_chip),
                rx.select(RADII, value=HomeState.radius_label,
                          on_change=HomeState.set_radius, size="2",
                          width="7.5rem"),
                rx.select(HomeState.city_options, value=HomeState.city_label,
                          on_change=HomeState.set_city, size="2",
                          width="10rem"),
                rx.cond(
                    HomeState.coverage != "",
                    rx.text(HomeState.coverage, size="1",
                            style={"color": "var(--dim)"}),
                    rx.fragment(),
                ),
                rx.button(rx.cond(HomeState.include_spicy,
                                  "spicy games on", "spicy games off"),
                          size="2", variant="ghost",
                          on_click=HomeState.toggle_spicy,
                          style={"margin": "0",
                                 "color": rx.cond(HomeState.include_spicy,
                                                  "#C43A6E", "var(--dim)")}),
                spacing="2", align="center", wrap="wrap",
                class_name="filter-row", width="100%",
            ),
            notice_toast(HomeState.notice),
            _card(HomeState.cards[0], big=True),
            rx.grid(
                _card(HomeState.cards[1]),
                _card(HomeState.cards[2]),
                _card(HomeState.cards[3]),
                _card(HomeState.cards[4]),
                columns={"initial": "1", "sm": "2", "lg": "4"},
                spacing="4", width="100%",
            ),
            _outfit_section(),
            GL.section(),
            rx.cond(
                HomeState.has_recent,
                rx.vstack(
                    rx.text("Lately", size="2",
                            style={"fontFamily": "'Archivo Narrow', sans-serif",
                                   "fontWeight": "700", "color": "var(--steel)"}),
                    rx.foreach(HomeState.recent, _log_line),
                    spacing="1", align="start", width="100%",
                    style={"borderTop": "1px solid var(--rule)",
                           "paddingTop": "1rem", "marginTop": "0.5rem"},
                ),
                rx.fragment(),
            ),
            spacing="4", width="100%", align="start",
        ),
        size="4",
        on_mount=[HomeState.load, GL.GalleryState.load],
    )
