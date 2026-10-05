"""Date tracking: places you want to go, and the dates you actually went on.

`✓ went` promotes a wishlist place into the log, dated today. The place stays on
the wishlist — you go back to the good ones.

Google Maps import is not wired up yet. `Place.source` already distinguishes
`maps` from `manual` so an import can adopt rows without a migration.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import pathlib

import reflex as rx
from sqlmodel import Session, delete, select

from ..core import sync_io
from ..core import inline as IN
from ..core import verdicts as V
from ..core.models import DateEntry, Place
from ..core.state import ENGINE
from ..core import household as HH

from ..core.place_types import GROUPS, GROUP_HUE, TYPES, type_hue
from . import travel as T
from ..core.ui import (COUNTRIES, NO_COUNTRY, choice_row, country_code, country_hue, country_name,
                      notice_toast, pager)

DECK_PEEK = 10             # rows per list before "N more"
ANYWHERE = "anywhere"

RADII = [10, 25, 50, 100]      # km presets; 0 means no distance limit
ANY_CITY = "any city"



def build_map(rows: list[dict], centre: tuple[float, float] | None) -> tuple[str, int]:
    """Return (html, pin_count) for an inline Leaflet map.

    Returns markup rather than writing a file, and the iframe takes it through
    `srcdoc`. Earlier versions wrote places_map.html into assets/, which the
    Reflex dev watcher watches: every filter change rewrote 163 KB there and
    triggered a full recompile, so the server went unreachable in a loop. It
    also had to be written twice, because assets/ is only copied into the
    served tree at compile time. No file means neither problem, and it behaves
    the same in dev, in prod and behind a Tailscale proxy.
    """
    import json

    pins = [{"a": round(r["lat"], 5), "o": round(r["lon"], 5),
             "n": r["name"], "u": r["url"],
             "t": ", ".join(r["tag_list"]) or "untagged",
             "c": r["city"], "k": r["km"], "b": 1 if r["visited"] else 0}
            for r in rows if r.get("lat") is not None]

    doc = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="https://unpkg.com/leaflet.markercluster@1.5.3/dist/leaflet.markercluster.js"></script>
<style>
  html,body,#map{height:100%;margin:0;background:#0A1626}
  .leaflet-container{background:#0A1626;font-family:Archivo,system-ui,sans-serif}
  /* CARTO's dark basemap now needs an API key and watermarks every tile, so
     these are plain OpenStreetMap tiles, inverted. Only the tile pane is
     filtered, so pins and popups keep their real colours. */
  .leaflet-tile-pane{filter:invert(1) hue-rotate(185deg) brightness(.78)
                            contrast(.92) saturate(.55)}
  .leaflet-control-attribution{background:#12213A!important;color:#7C8CA8!important}
  .leaflet-control-attribution a{color:#B9C6D8!important}
  .leaflet-popup-content-wrapper{background:#12213A;color:#E8EDF5;border-radius:2px}
  .leaflet-popup-tip{background:#12213A}
  .leaflet-popup-content a{color:#F2A93B}
  /* MarkerCluster.Default.css is deliberately not loaded: it ships green,
     yellow and blue blobs that mean nothing here and collide with the three
     accents that do carry meaning. */
  .cl{background:#12213A;border:1px solid #F2A93B;color:#E8EDF5;border-radius:2px;
      font:600 11px Archivo,system-ui,sans-serif;text-align:center;
      line-height:28px;box-shadow:0 2px 6px rgba(4,9,18,.55)}
  .cl-done{border-color:#5FBE8C}
</style></head><body><div id="map"></div><script>
const pins = __PINS__, home = __HOME__;
const map = L.map('map', {scrollWheelZoom:true}).setView(home || [20,0], home ? 9 : 2);
L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
  attribution:'&copy; OpenStreetMap contributors', maxZoom:19}).addTo(map);
if (home) L.circleMarker(home, {radius:7,color:'#E8EDF5',weight:2,fillColor:'#E8EDF5',
  fillOpacity:1}).addTo(map).bindPopup('Home');
// Visited was drawn dim grey, which read as "faded out" rather than "been
// there". Green is the one colour in this app that means done.
const DONE = '#5FBE8C', TODO = '#F2A93B';
const group = L.markerClusterGroup({
  maxClusterRadius: 45, showCoverageOnHover: false,
  spiderfyOnMaxZoom: true, disableClusteringAtZoom: 15,
  iconCreateFunction: c => {
    const kids = c.getAllChildMarkers();
    const allDone = kids.every(m => m.options.been);
    return L.divIcon({html:`<div>${kids.length}</div>`,
      className:'cl' + (allDone ? ' cl-done' : ''),
      iconSize:L.point(30,30)});
  }
}).addTo(map);
for (const p of pins) {
  const hue = p.b ? DONE : TODO;
  L.circleMarker([p.a,p.o], {radius:6,color:hue,weight:1.5,been:!!p.b,
    fillColor:hue,fillOpacity:p.b?0.9:0.55})
   .bindPopup(`<b>${p.n}</b><br>${p.t}<br>${p.c} ${p.k}` +
              (p.u?`<br><a href="${p.u}" target="_blank">open in Maps</a>`:''))
   .addTo(group);
}
if (pins.length) map.fitBounds(group.getBounds().pad(0.15));
</script></body></html>"""
    doc = doc.replace("__PINS__", json.dumps(pins, separators=(",", ":"))
                      ).replace("__HOME__", json.dumps(list(centre) if centre else None))
    return doc, len(pins)


@dataclasses.dataclass
class PlaceRow:
    """Typed on purpose: rx.foreach cannot iterate a nested plain dict."""
    id: int
    name: str
    url: str
    been: str
    country: str
    hue: str
    label: str
    rating: str
    list_name: str
    country_pick: str
    tags: str
    tag_list: list[str]
    visited: bool
    city: str
    km: str
    verdicts: dict[str, str]


PAGE_SIZE = 25


class DateState(rx.State):
    has_home: bool = False
    _places: list[dict] = []
    _log: list[dict] = []
    _verdicts: dict[str, dict[str, str]] = {}
    unvoted: str = ""                  # a person: only the places they have not voted on
    notice: str = ""
    job_log: str = ""
    busy: bool = False
    edit_mode: bool = False

    new_name: str = ""
    new_list: str = ""
    new_url: str = ""
    new_country: str = ""
    sel_countries: list[str] = []
    sel_types: list[str] = []          # multi-select: several moods at once
    tried_filter: str = ""             # "" = all, "yes" = been, "no" = not yet
    pick_country: str = ANYWHERE      # scope it from the picker
    show_map: bool = False
    map_pins: int = 0
    map_html: str = ""                 # the whole map, handed to iframe srcdoc
    max_km: int = 0                    # 0 = no limit
    sel_city: str = ""                 # "" = any city
    seed: int = 0
    search: str = ""
    page: int = 0
    sort_key: str = "name"
    sort_desc: bool = False
    hidden_count: int = 0

    entry_place: str = ""
    entry_date: str = ""
    entry_with: str = ""
    entry_note: str = ""

    @rx.event
    def set_inline(self, row_id: int, field: str, value: str):
        """Rating or note, on blur. Place spells it `note`, and the row dict
        carries it as "label"; core/inline.py resolves the column."""
        msg = IN.save(Place, row_id, field, value)
        if msg:
            self.notice = msg
            if not msg.startswith("a rating is"):
                # the note lives under two keys: "label" for the cell, "note"
                # for search. Update both or search matches stale text.
                keys = ("label", "note") if field == "notes" else (field,)
                v = value.strip()
                self._places = [{**r, **{k: v for k in keys}} if r["id"] == row_id
                                else r for r in self._places]

    @rx.event
    def load(self):
        home = HH.home()
        self.has_home = home is not None
        if not self.has_home:
            self.max_km = 0             # a radius chosen before the home was cleared
        with Session(ENGINE) as s:
            places = [p for p in s.exec(select(Place)).all() if not p.dismissed]
            hidden = len([1 for p in s.exec(select(Place)).all() if p.dismissed])
            names = {p.id: p.name for p in places}
            self._places = [{"id": p.id, "name": p.name, "list": p.list_name or "Unsorted",
                             "url": p.maps_url, "note": p.note, "source": p.source,
                             "country": p.country, "label": p.note,
                             "rating": IN.shown(p.rating),
                             "tags": p.tags, "visited": p.visited,
                             "tag_list": [t for t in p.tags.split(",") if t],
                             "city": p.city, "lat": p.lat, "lon": p.lon,
                             "km": (round(km, 1) if (km := HH.distance_km(home, p.lat, p.lon)) is not None else None)}
                            for p in sorted(places, key=lambda x: x.name.lower())]
            self._log = [{"id": e.id, "date": e.went_on.isoformat(),
                          "place": names.get(e.place_id) or e.place_text or "—",
                          "with": e.with_whom, "note": e.note,
                          "rating": e.rating or 0,
                          "stars": "★" * (e.rating or 0) + "☆" * (5 - (e.rating or 0))}
                         for e in sorted(s.exec(select(DateEntry)).all(),
                                         key=lambda x: x.went_on, reverse=True)]
            self.hidden_count = hidden
        self._read_verdicts()
        if not self.entry_date:
            self.entry_date = dt.date.today().isoformat()

    def _read_verdicts(self):
        self._verdicts = {str(k): v for k, v in
                          V.read("place", [p["id"] for p in self._places]).items()}

    def _held(self, row_id: int) -> dict[str, str]:
        """Every person is always a key: the control reads verdicts[person]."""
        got = self._verdicts.get(str(row_id), {})
        return {p: got.get(p, "") for p in V.PEOPLE}

    # ---- derived ----------------------------------------------------------
    @staticmethod
    def _bucket(p: dict) -> str:
        """Blank country means two different things: a place whose country we do
        not know, and an activity with no place at all."""
        if p["country"]:
            return p["country"]
        return "unsorted" if p["url"] else "ideas"

    def _matches(self) -> list[dict]:
        q = self.search.strip().lower()
        been = {e["place"] for e in self._log}
        out = [p for p in self._places
               if (not q or q in p["name"].lower() or q in p["list"].lower())
               and (not self.sel_countries or self._bucket(p) in self.sel_countries)
               and (not self.sel_types
                    or any(t in self.sel_types for t in p["tag_list"]))
               and (not self.tried_filter
                    or (p["visited"] or p["name"] in been) == (self.tried_filter == "yes"))
               and (not self.unvoted or not self._held(p["id"])[self.unvoted])
               and (not self.max_km
                    or (p["km"] is not None and p["km"] <= self.max_km))
               and (not self.sel_city or p["city"] == self.sel_city)]
        k = self.sort_key
        def key(p):
            if k == "list":
                return (p["list"].lower(), p["name"].lower())
            if k == "country":
                return (self._bucket(p), p["name"].lower())
            if k == "been":
                return ("a" if p["name"] in been else "z", p["name"].lower())
            return (p["name"].lower(),)
        return sorted(out, key=key, reverse=self.sort_desc)

    @rx.var
    def total(self) -> int:
        return len(self._matches())

    @rx.var
    def last_page(self) -> int:
        return max(0, (self.total - 1) // PAGE_SIZE)

    @rx.var
    def page_label(self) -> str:
        n = self.total
        if not n:
            return "no matches"
        lo = self.page * PAGE_SIZE + 1
        return f"{lo}–{min(lo + PAGE_SIZE - 1, n)} of {n}"

    @rx.var
    def page_rows(self) -> list[PlaceRow]:
        been = {e["place"] for e in self._log}
        rows = self._matches()[self.page * PAGE_SIZE:(self.page + 1) * PAGE_SIZE]
        return [PlaceRow(id=p["id"], name=p["name"], url=p["url"],
                         country=country_name(self._bucket(p)),
                         country_pick=(country_name(p["country"]) if p["country"]
                                       else NO_COUNTRY),
                         hue=country_hue(p["country"]),
                         label=p["label"], rating=p["rating"], list_name=p["list"],
                         tags=p["tags"], tag_list=p["tag_list"],
                         visited=p["visited"], city=p["city"],
                         km=(f"{p['km']:.0f} km" if p["km"] is not None else ""),
                         been="yes" if p["name"] in been else "",
                         verdicts=self._held(p["id"]))
                for p in rows]

    @rx.var
    def country_options(self) -> list[str]:
        """Names, not codes. Anything already in the data that is not in the map
        is appended so a place cannot lose its country by being edited."""
        used = {p["country"] for p in self._places if p["country"]}
        unmapped = sorted(c for c in used if c.upper() not in COUNTRIES)
        return [NO_COUNTRY] + sorted(COUNTRIES.values()) + unmapped

    @rx.var
    def list_options(self) -> list[str]:
        return sorted({p["list"] for p in self._places}, key=str.lower)

    @rx.var
    def country_hues(self) -> list[dict[str, str]]:
        codes = sorted({self._bucket(p) for p in self._places})
        return sorted(
            [{"code": c, "label": country_name(c), "hue": country_hue(c if len(c) == 2 else "")}
             for c in codes],
            key=lambda x: x["label"].lower())

    @rx.var
    def unvisited(self) -> list[dict]:
        """The picker's pool: places you have not been to, in the country you
        chose, matching whatever types are selected. Scoped by country on
        purpose — an unscoped pick offers a trattoria in Italy on a Tuesday."""
        been = {e["place"] for e in self._log}
        return [p for p in self._places
                if p["name"] not in been and not p["visited"] and p["url"]
                and (self.pick_country == ANYWHERE
                     or p["country"] == self.pick_country)
                and (not self.sel_types
                     or any(t in self.sel_types for t in p["tag_list"]))
                and (not self.max_km
                     or (p["km"] is not None and p["km"] <= self.max_km))
                and (not self.sel_city or p["city"] == self.sel_city)]

    @rx.var
    def suggestion(self) -> dict[str, str]:
        """One place you have not been to yet. The page's whole job in one row."""
        pool = self.unvisited
        if not pool:
            return {}
        p = pool[self.seed % len(pool)]
        return {"name": p["name"], "list": p["list"], "country": p["country"],
                "url": p["url"], "hue": country_hue(p["country"]),
                "country_name": country_name(p["country"]),
                "tags": ", ".join(p["tag_list"]) or "untagged",
                "km": (f"{p['km']:.0f} km away" if p["km"] is not None
                       else "distance unknown"),
                "city": p["city"],
                "left": str(len(pool))}

    @rx.event
    def set_search(self, v: str):
        self.search, self.page = v, 0

    @rx.event
    def sort_by(self, key: str):
        self.sort_desc = not self.sort_desc if self.sort_key == key else False
        self.sort_key = key

    @rx.event
    def next_page(self):
        self.page = min(self.page + 1, self.last_page)

    @rx.event
    def prev_page(self):
        self.page = max(0, self.page - 1)

    @rx.event
    def shuffle(self):
        self.seed += 1

    @rx.event
    def toggle_type(self, t: str):
        """Multi-select: several types stack, so "restaurant" plus "cafe" gives
        you both rather than replacing one with the other."""
        self.sel_types = ([x for x in self.sel_types if x != t]
                          if t in self.sel_types else self.sel_types + [t])
        self.page = 0

        if self.show_map:
            return DateState.refresh_map
    @rx.event
    def toggle_group(self, g: str):
        """One click for a whole mood: selects every type in the group, or
        clears them if they are all already on."""
        members = GROUPS.get(g, [])
        if all(m in self.sel_types for m in members):
            self.sel_types = [x for x in self.sel_types if x not in members]
        else:
            self.sel_types = self.sel_types + [m for m in members
                                               if m not in self.sel_types]
        self.page = 0

        if self.show_map:
            return DateState.refresh_map
    @rx.event
    def clear_types(self):
        self.sel_types = []
        self.page = 0

        if self.show_map:
            return DateState.refresh_map
    @rx.event
    def set_pick_country(self, v: str):
        self.pick_country = country_code(v) if v not in (ANYWHERE, "") else ANYWHERE
        self.seed += 1

    @rx.event
    def set_view(self, v: str | list[str]):
        """Table or map. Same rows either way — the map is a second view of the
        current filters, not a separate page with its own state.

        The union in the signature is not optional: rx.segmented_control passes
        `str | list[str]`, and Reflex rejects a narrower annotation at import.
        """
        picked = v[0] if isinstance(v, list) else v
        self.show_map = picked == "map"
        if self.show_map:
            return DateState.refresh_map

    @rx.event
    def toggle_map(self):
        """Regenerate on open and on every filter change while open, so what is
        pinned always equals what the filters say."""
        self.show_map = not self.show_map
        if self.show_map:
            return DateState.refresh_map

    @rx.event
    def refresh_map(self):
        if not self.show_map:
            self.map_html = ""          # do not ship markup nobody is looking at
            return
        self.map_html, self.map_pins = build_map(self._matches(), HH.home())

    @rx.event
    def set_max_km(self, km: int):
        self.max_km = 0 if km == self.max_km else km
        self.page = 0
        self.seed += 1

        if self.show_map:
            return DateState.refresh_map
    @rx.event
    def set_city(self, v: str):
        self.sel_city = "" if v == ANY_CITY else v
        self.page = 0
        self.seed += 1

        if self.show_map:
            return DateState.refresh_map
    @rx.event
    def set_tried(self, v: str):
        self.tried_filter = "" if v == self.tried_filter else v
        self.page = 0
        if self.show_map:
            return DateState.refresh_map

    @rx.event
    def set_unvoted(self, person: str):
        self.unvoted = "" if person == self.unvoted else person
        self.page = 0
        if self.show_map:
            return DateState.refresh_map

    @rx.event
    async def set_verdict(self, row_id: int, person: str, value: str):
        if await V.write_as(self, "place", row_id, person, value):
            self._read_verdicts()
            # under the "to vote" filter the row just left the list
            self.page = min(self.page, self.last_page)
            if self.show_map and self.unvoted:
                return DateState.refresh_map

            if self.show_map:
                return DateState.refresh_map
    @rx.event
    def toggle_visited(self, pid: int):
        """Patched in place: reloading re-read every place and rebuilt every
        distance, for one boolean."""
        with Session(ENGINE) as s:
            p = s.get(Place, pid)
            if not p:
                return
            p.visited = not p.visited
            new = p.visited
            s.add(p)
            s.commit()
        self._places = [{**row, "visited": new} if row["id"] == pid else row
                        for row in self._places]
        self.page = min(self.page, self.last_page)   # under the been filter it left
        if self.show_map:
            return DateState.refresh_map

    @rx.event
    def edit_tags(self, pid: int, value: str):
        """Hand-edit the types. Marks the row manual so categorize_places.py
        never overwrites your correction on a later run."""
        clean = [t.strip().lower() for t in value.split(",") if t.strip()]
        unknown = [t for t in clean if t not in TYPES]
        if unknown:
            self.notice = f"unknown type: {', '.join(unknown[:3])}"
            return
        with Session(ENGINE) as s:
            p = s.get(Place, pid)
            if p:
                p.tags = ",".join(clean)
                p.tag_source = "manual" if clean else ""
                s.add(p)
                s.commit()
        self.load()
        self.notice = ""

    @rx.event
    def went_suggestion(self):
        pool = self.unvisited
        if pool:
            return DateState.went(pool[self.seed % len(pool)]["id"])

    @rx.var
    def type_counts(self) -> list[dict[str, str]]:
        """Every type with how many places carry it, so an empty filter is
        visibly empty rather than mysteriously returning nothing."""
        from collections import Counter
        c: Counter = Counter()
        for p in self._places:
            c.update(p["tag_list"])
        return [{"name": t, "group": g, "count": str(c.get(t, 0)),
                 "hue": type_hue(t), "on": t in self.sel_types}
                for g, ts in GROUPS.items() for t in ts]

    @rx.var
    def group_rows(self) -> list[dict[str, str]]:
        return [{"name": g, "hue": GROUP_HUE.get(g, "var(--rule)"),
                 "on": all(t in self.sel_types for t in ts)}
                for g, ts in GROUPS.items()]

    @rx.var
    def sel_types_label(self) -> str:
        if not self.sel_types:
            return "any kind of place"
        return ", ".join(self.sel_types[:4]) + (
            f" +{len(self.sel_types) - 4}" if len(self.sel_types) > 4 else "")

    @rx.var
    def pick_country_label(self) -> str:
        return (ANYWHERE if self.pick_country == ANYWHERE
                else country_name(self.pick_country))

    @rx.var
    def pick_country_options(self) -> list[str]:
        """Only the countries you actually saved places in, plus anywhere."""
        codes = sorted({p["country"] for p in self._places if p["country"]})
        return [ANYWHERE] + [country_name(c) for c in codes]

    @rx.var
    def radius_rows(self) -> list[dict[str, str]]:
        return [{"label": f"\u2264{r} km", "km": str(r),
                 "on": self.max_km == r} for r in RADII]

    @rx.var
    def city_options(self) -> list[str]:
        """Only cities the geocoder actually resolved, largest first."""
        from collections import Counter
        c = Counter(p["city"] for p in self._places if p["city"])
        return [ANY_CITY] + [name for name, _ in c.most_common(40)]

    @rx.var
    def city_label(self) -> str:
        return self.sel_city or ANY_CITY

    @rx.var
    def geo_summary(self) -> str:
        n = sum(1 for p in self._places if p["km"] is not None)
        return f"{n} of {len(self._places)} placed on the map"

    @rx.var
    def untagged_count(self) -> int:
        return sum(1 for p in self._places if not p["tag_list"])

    @rx.var
    def country_names(self) -> list[str]:
        """Blank countries land under "—" so the ideas with no place stay reachable."""
        return sorted({p["country"] or "—" for p in self._places})

    @rx.var
    def log_rows(self) -> list[dict]:
        return self._log

    @rx.var
    def filter_summary(self) -> str:
        """The drawer label has to say what is hidden behind it, or closing it
        loses track of why the list is short."""
        n = (len(self.sel_countries) + len(self.sel_types)
             + (1 if self.max_km else 0) + (1 if self.sel_city else 0)
             + (1 if self.tried_filter else 0) + (1 if self.unvoted else 0))
        return f"Filters ({n})" if n else "Filters"

    @rx.var
    def map_gap(self) -> str:
        """The map's own blind spot, stated on the map.

        Geocoding stopped at the free tier, so a little under half of these
        have coordinates. The map silently drew the ones it had and said
        nothing about the rest, which makes it look like a complete picture of
        where you could go. It is not one.
        """
        rows = self._matches()
        placed = sum(1 for r in rows if r.get("lat") is not None)
        missing = len(rows) - placed
        if not missing:
            return ""
        return (f"{placed} of {len(rows)} placed. {missing} have no "
                f"coordinates and are not on this map.")

    @rx.var
    def place_count(self) -> str:
        """Top few countries by count. Naming all 22 wrapped to two lines and
        told you nothing you could not get from the chips."""
        real = [p for p in self._places if p["country"]]
        by: dict[str, int] = {}
        for p in real:
            by[p["country"]] = by.get(p["country"], 0) + 1
        top = sorted(by.items(), key=lambda x: -x[1])
        head = ", ".join(f"{v} in {k}" for k, v in top[:5])
        rest = len(top) - 5
        more = f" and {rest} more countries" if rest > 0 else ""
        return f"{len(real)} places across {len(by)} countries: {head}{more}"

    @rx.var
    def log_count(self) -> str:
        return f"{len(self._log)} logged"

    @rx.var
    def place_names(self) -> list[str]:
        return [p["name"] for p in self._places]

    # ---- setters, explicit because this build generates none --------------
    @rx.event
    def set_new_name(self, v: str):
        self.new_name = v

    @rx.event
    def set_new_list(self, v: str):
        self.new_list = v

    @rx.event
    def set_new_url(self, v: str):
        self.new_url = v

    @rx.event
    def set_new_country(self, v: str):
        self.new_country = v

    @rx.event
    def toggle_country(self, c: str):
        self.sel_countries = ([x for x in self.sel_countries if x != c]
                              if c in self.sel_countries else self.sel_countries + [c])
        self.page = 0

    @rx.event
    def set_entry_place(self, v: str):
        self.entry_place = v

    @rx.event
    def set_entry_date(self, v: str):
        self.entry_date = v

    @rx.event
    def set_entry_with(self, v: str):
        self.entry_with = v

    @rx.event
    def set_entry_note(self, v: str):
        self.entry_note = v

    @rx.event
    def toggle_edit(self):
        self.edit_mode = not self.edit_mode

    # ---- mutations --------------------------------------------------------
    @rx.event
    def add_place(self):
        name = self.new_name.strip()
        if not name:
            return
        with Session(ENGINE) as s:
            if s.exec(select(Place).where(Place.name == name)).first():
                self.notice = f"“{name}” is already on the list"
                return
            s.add(Place(name=name, list_name=self.new_list.strip(),
                        maps_url=self.new_url.strip(),
                        country=country_code(self.new_country), source="manual"))
            s.commit()
        self.new_name = self.new_url = ""
        self.load()
        self.notice = f"added “{name}”"

    @rx.event
    def delete_place(self, pid: int):
        """Hide, do not erase. The importer is add-only and idempotent by name,
        so a hard delete comes straight back on the next refresh."""
        with Session(ENGINE) as s:
            p = s.get(Place, pid)
            if p:
                p.dismissed = True
                s.add(p)
                s.commit()
                name = p.name
        self.load()
        self.notice = f"hid {name}"

    @rx.event
    def restore_hidden(self):
        with Session(ENGINE) as s:
            rows = [p for p in s.exec(select(Place)).all() if p.dismissed]
            for p in rows:
                p.dismissed = False
                s.add(p)
            s.commit()
        self.load()
        self.notice = f"restored {len(rows)} hidden"

    @rx.event
    def went(self, pid: int):
        """Promote a wishlist place into the log, dated today."""
        with Session(ENGINE) as s:
            p = s.get(Place, pid)
            if not p:
                return
            s.add(DateEntry(went_on=dt.date.today(), place_id=pid))
            s.commit()
            name = p.name
        self.load()
        self.notice = f"logged “{name}” for today — set the rating below"

    @rx.event
    def add_entry(self):
        """A date somewhere that was never on the wishlist."""
        try:
            day = dt.date.fromisoformat(self.entry_date.strip())
        except ValueError:
            self.notice = "date must be YYYY-MM-DD"
            return
        place = self.entry_place.strip()
        if not place:
            self.notice = "which place?"
            return
        with Session(ENGINE) as s:
            known = s.exec(select(Place).where(Place.name == place)).first()
            s.add(DateEntry(went_on=day, place_id=known.id if known else None,
                            place_text="" if known else place,
                            with_whom=self.entry_with.strip(), note=self.entry_note.strip()))
            s.commit()
        self.entry_place = self.entry_note = ""
        self.load()
        self.notice = f"logged “{place}”"

    @rx.event
    def edit_place(self, pid: int, field: str, value: str):
        """Inline edit of one wishlist cell. One handler for every column, so a
        new column does not need a new event."""
        v = value.strip()
        with Session(ENGINE) as s:
            p = s.get(Place, pid)
            if not p:
                return
            if field == "name":
                if not v:
                    self.notice = "a place needs a name"
                    return
                clash = s.exec(select(Place).where(Place.name == v)).first()
                if clash and clash.id != pid:
                    self.notice = f"{v} is already on the list"
                    return
                p.name = v       # the log points at the place by id, so this carries
            elif field == "country":
                p.country = country_code(v)
            elif field == "list":
                p.list_name = v
            # the note ("label") moved to set_inline / core/inline.py
            elif field == "url":
                p.maps_url = v
            s.add(p)
            s.commit()
            name = p.name
        self.load()
        self.notice = f"{name}: {field} = {v or '—'}"

    @rx.event
    def edit_entry(self, eid: int, field: str, value: str):
        v = value.strip()
        with Session(ENGINE) as s:
            e = s.get(DateEntry, eid)
            if not e:
                return
            if field == "date":
                try:
                    e.went_on = dt.date.fromisoformat(v)
                except ValueError:
                    self.notice = f"{v} is not a date — use YYYY-MM-DD"
                    return
            elif field == "place":
                known = s.exec(select(Place).where(Place.name == v)).first()
                e.place_id = known.id if known else None
                e.place_text = "" if known else v
            elif field == "with":
                e.with_whom = v
            elif field == "note":
                e.note = v
            s.add(e)
            s.commit()
        self.load()

    @rx.event
    def rate(self, eid: int, stars: int):
        with Session(ENGINE) as s:
            e = s.get(DateEntry, eid)
            if e:
                e.rating = stars
                s.add(e)
                s.commit()
        self.load()

    @rx.event
    def delete_entry(self, eid: int):
        with Session(ENGINE) as s:
            s.exec(delete(DateEntry).where(DateEntry.id == eid))
            s.commit()
        self.load()


    @rx.event(background=True)
    async def refresh_places(self):
        """Import from Takeout. Reads the newest Takeout*.zip in the folder, so
        there is no unzip step to forget."""
        async with self:
            if self.busy:
                return
            self.busy, self.notice = True, "reading Takeout…"
        ok, out = sync_io.run(
            [str(sync_io.APP / ".venv/bin/python"), str(sync_io.SCRIPTS / "import" / "import_places.py"),
             "--takeout", "--apply"],
            sync_io.ROOT, timeout=900)
        async with self:
            self.busy = False
            self.job_log = out
            self.load()
            self.notice = (out.strip().splitlines() or ["done"])[-1] if ok \
                else "import failed — see the log"


# ---- page -----------------------------------------------------------------
def _head(key: str, label: str, hide_on_phone: bool = False) -> rx.Component:
    # Reflex responsive display, five tiers: initial, xs 30em, sm 48em,
    # md 62em, lg 80em. "none" below 48em keeps the column out of a phone.
    extra = {"display": ["none", "none", "table-cell", "table-cell",
                         "table-cell"]} if hide_on_phone else {}
    return rx.table.column_header_cell(
        rx.hstack(
            rx.text(label, size="1", weight="medium"),
            rx.cond(DateState.sort_key == key,
                    rx.text(rx.cond(DateState.sort_desc, "▼", "▲"), size="1",
                            style={"color": "var(--mustard)"}),
                    rx.fragment()),
            spacing="1", align="center",
        ),
        on_click=DateState.sort_by(key),
        **extra,
        style={"cursor": "pointer", "whiteSpace": "nowrap"},
    )


def _tag_badge(t: rx.Var) -> rx.Component:
    return rx.badge(t, size="1", style={"background": "var(--plate2)",
                                        "color": "var(--steel)"})


def _place_row(p: rx.Var) -> rx.Component:
    return rx.table.row(
        rx.table.cell(rx.box(class_name="hue", style={"background": p.hue,
                                                      "minHeight": "1.1rem"}),
                      style={"width": "8px", "padding": "0 0 0 6px"}),
        rx.table.cell(V.control(p.verdicts, lambda person, value:
                                DateState.set_verdict(p.id, person, value))),
        rx.table.row_header_cell(
            rx.cond(
                DateState.edit_mode,
                rx.input(default_value=p.name, size="1", width="100%",
                         on_blur=DateState.edit_place(p.id, "name"),
                         key=f"{p.id}-name"),
                rx.cond(p.url != "",
                        rx.link(p.name, href=p.url, is_external=True, size="2"),
                        rx.text(p.name, size="2")),
            ),
        ),
        rx.table.cell(
            rx.cond(
                DateState.edit_mode,
                rx.select(DateState.country_options, value=p.country_pick, size="1",
                          width="100%", key=f"{p.id}-country",
                          on_change=DateState.edit_place(p.id, "country")),
                rx.text(p.country, size="1", style={"color": "var(--steel)"}),
            ),
        ),
        rx.table.cell(
            rx.cond(
                DateState.edit_mode,
                rx.select(DateState.list_options, value=p.list_name, size="1",
                          width="100%", key=f"{p.id}-list",
                          on_change=DateState.edit_place(p.id, "list")),
                rx.text(p.list_name, size="1", style={"color": "var(--dim)"}),
            ),
            # List repeats Country and Label is usually blank; together they
            # pushed Distance off the right edge of a phone.
            display=["none", "none", "table-cell", "table-cell", "table-cell"],
        ),
        IN.rating_cell(p.rating, DateState.set_inline(p.id, "rating"),
                       key=f"{p.id}-rating"),
        # "Label" was Place.note under another name. Shown on phones now:
        # the table scrolls instead of squeezing, so hiding it bought nothing.
        IN.notes_cell(p.label, DateState.set_inline(p.id, "notes"),
                      key=f"{p.id}-label"),
        rx.table.cell(
            rx.cond(
                DateState.edit_mode,
                rx.input(default_value=p.tags, size="1", width="100%",
                         placeholder="restaurant, cafe",
                         on_blur=DateState.edit_tags(p.id),
                         key=f"{p.id}-tags"),
                rx.hstack(rx.foreach(p.tag_list, _tag_badge),
                          spacing="1", wrap="wrap"),
            ),
        ),
        rx.table.cell(
            rx.vstack(
                rx.text(p.km, size="1", class_name="tnum",
                        style={"color": "var(--teal)", "whiteSpace": "nowrap"}),
                rx.text(p.city, size="1", style={"color": "var(--dim)"}),
                spacing="0", align="start",
            ),
        ),
        rx.table.cell(
            rx.button(
                rx.cond(p.visited | (p.been != ""), "✓ been", "— not yet"),
                on_click=DateState.toggle_visited(p.id), size="1",
                variant="surface",
                color_scheme=rx.cond(p.visited | (p.been != ""), "green", "gray"),
            ),
            style={"whiteSpace": "nowrap"},
        ),
        rx.table.cell(
            rx.hstack(
                rx.cond(
                    DateState.edit_mode,
                    rx.input(default_value=p.url, size="1", width="12rem",
                             placeholder="maps link",
                             on_blur=DateState.edit_place(p.id, "url"),
                         key=f"{p.id}-url"),
                    rx.fragment(),
                ),
                rx.button("Went", on_click=DateState.went(p.id), size="1",
                          variant="ghost"),
                rx.cond(DateState.edit_mode,
                        rx.button("Remove", on_click=DateState.delete_place(p.id),
                                  size="1", variant="ghost", color_scheme="red"),
                        rx.fragment()),
                spacing="1", align="center",
            ),
            style={"whiteSpace": "nowrap"},
        ),
        class_name="row-place",
    )


def _group_chip(g: rx.Var) -> rx.Component:
    return rx.button(
        g["name"], size="1",
        variant=rx.cond(g["on"], "solid", "surface"),
        on_click=DateState.toggle_group(g["name"]),
        style={"margin": "0", "borderRadius": "2px", "fontWeight": "700",
               "background": rx.cond(g["on"], g["hue"], "transparent"),
               "border": "1px solid " + g["hue"],
               "color": rx.cond(g["on"], "var(--ink)", "var(--steel)")},
    )


def _type_chip(t: rx.Var) -> rx.Component:
    return rx.button(
        rx.hstack(
            rx.text(t["name"], size="1"),
            rx.text(t["count"], size="1", class_name="tnum",
                    style={"opacity": "0.6"}),
            spacing="1", align="center",
        ),
        size="1", variant=rx.cond(t["on"], "solid", "surface"),
        on_click=DateState.toggle_type(t["name"]),
        disabled=t["count"] == "0",
        style={"margin": "0", "borderRadius": "2px",
               "background": rx.cond(t["on"], t["hue"], "transparent"),
               "border": rx.cond(t["on"], "1px solid " + t["hue"],
                                 "1px solid var(--rule)"),
               "color": rx.cond(t["on"], "var(--ink)", "var(--steel)")},
    )


def _radius_chip(r: rx.Var) -> rx.Component:
    return rx.button(
        r["label"], size="1",
        variant=rx.cond(r["on"], "solid", "surface"),
        on_click=DateState.set_max_km(r["km"].to(int)),
        style={"margin": "0", "borderRadius": "2px",
               "background": rx.cond(r["on"], "var(--teal)", "transparent"),
               "border": rx.cond(r["on"], "1px solid var(--teal)",
                                 "1px solid var(--rule)"),
               "color": rx.cond(r["on"], "var(--ink)", "var(--steel)")},
    )


def _where() -> rx.Component:
    """Distance from home and city. Both drop places with no coordinate: an
    unplaced row cannot answer "is it within 25km", so it is not pretended to."""
    return rx.hstack(
        rx.text("Distance", size="1",
                style={"color": "var(--dim)", "minWidth": "4.25rem",
                       "flex": "0 0 4.25rem", "paddingTop": "0.18rem"}),
        rx.box(
            rx.hstack(
                rx.cond(DateState.has_home, rx.foreach(DateState.radius_rows, _radius_chip)),
                rx.select(DateState.city_options, value=DateState.city_label,
                          size="1", on_change=DateState.set_city, width="11rem"),
                rx.cond(DateState.has_home,
                        rx.text(DateState.geo_summary, size="1", style={"color": "var(--dim)"})),
                spacing="2", align="center", wrap="wrap",
            ),
            class_name="filter-row", width="100%",
        ),
        width="100%", align="start", spacing="2",
    )


def _mood_filters() -> rx.Component:
    """Two levels: a group picks its whole set, a type picks just itself. Both
    stack, so you can take all of `adventure` and add `cafe` on top.

    Split out of _mood() so the phone can put exactly these rows in a drawer.
    Four chip rows is most of a 375px screen before any content appears.
    """
    return rx.vstack(
        rx.hstack(
            rx.text("Mood", size="1",
                    style={"color": "var(--dim)", "minWidth": "4.25rem",
                           "flex": "0 0 4.25rem", "paddingTop": "0.18rem"}),
            rx.box(rx.hstack(rx.foreach(DateState.group_rows, _group_chip),
                             spacing="2", wrap="wrap"),
                   class_name="filter-row", width="100%"),
            width="100%", align="start", spacing="2",
        ),
        rx.hstack(
            rx.text("Types", size="1",
                    style={"color": "var(--dim)", "minWidth": "4.25rem",
                           "flex": "0 0 4.25rem", "paddingTop": "0.18rem"}),
            rx.box(rx.hstack(rx.foreach(DateState.type_counts, _type_chip),
                             spacing="2", wrap="wrap"),
                   class_name="filter-row", width="100%"),
            width="100%", align="start", spacing="2",
        ),
        _where(),
        choice_row("been", DateState.tried_filter, DateState.set_tried,
                   [("yes", "Been"), ("no", "Not yet")]),
        V.unvoted_row(DateState),
        rx.hstack(
            rx.box(style={"minWidth": "4.25rem", "flex": "0 0 4.25rem"}),
            rx.button("Clear mood", size="1", variant="ghost",
                      on_click=DateState.clear_types),
            rx.text(DateState.untagged_count.to_string() + " still untagged",
                    size="1", style={"color": "var(--dim)"}),
            spacing="2", align="center", width="100%", class_name="filter-row",
        ),
        spacing="2", width="100%", align="start",
    )



def _map_block() -> rx.Component:
    """The map, and what it is not showing. Lifted out of the filter stack so
    the drawer on a phone carries chips and not a 560px iframe."""
    return rx.vstack(
        rx.cond(
            DateState.show_map,
            rx.box(
                # sandbox lets the Leaflet script run but denies it same-origin
                # access back to the app, which costs nothing here and keeps
                # inlined markup from reaching the page's state.
                rx.el.iframe(
                    # src_doc, not srcdoc: Reflex converts snake_case props to
                    # camelCase, and React only honours the attribute as
                    # `srcDoc`. Passing it lowercase compiles to `srcdoc`,
                    # which React drops — the iframe renders at full size and
                    # is completely blank.
                    src_doc=DateState.map_html,
                    sandbox="allow-scripts",
                    # A fixed 440px map is half a desktop window and most of a
                    # phone. Height follows the viewport between two sane ends.
                    style={"width": "100%",
                           "height": "clamp(320px, 58vh, 560px)", "border": "0"},
                ),
                rx.cond(
                    DateState.map_gap != "",
                    rx.callout.root(
                        rx.callout.text(DateState.map_gap),
                        size="1", variant="surface", color_scheme="orange",
                        style={"margin": "0.5rem", "width": "auto"},
                    ),
                    rx.fragment(),
                ),
                rx.text("Green pins are places you have already been.",
                        size="1", style={"color": "var(--dim)",
                                         "padding": "0.4rem 0.5rem 0.5rem"}),
                width="100%",
                style={"border": "1px solid var(--rule)",
                       "background": "var(--ink)"},
            ),
            rx.fragment(),
        ),
        width="100%", spacing="0",
    )



def _filter_drawer() -> rx.Component:
    """Phone only — hidden on desktop by the breakpoint in ledger.css, where the
    same rows stay inline. The chips are rendered twice, which costs about sixty
    buttons of markup and buys back most of a phone screen.
    """
    from ..core.ui import chip, filter_row
    return rx.box(
        rx.drawer.root(
            rx.drawer.trigger(
                rx.button(DateState.filter_summary, size="2", variant="surface",
                          width="100%"),
            ),
            rx.drawer.portal(
                rx.drawer.overlay(
                    style={"background": "rgba(4,9,18,.65)", "zIndex": "50"}),
                rx.drawer.content(
                    rx.vstack(
                        rx.drawer.handle(
                            style={"background": "var(--rule)", "height": "3px",
                                   "width": "2.5rem", "borderRadius": "2px",
                                   "margin": "0 auto 0.75rem"}),
                        _mood_filters(),
                        filter_row("country", rx.foreach(
                            DateState.country_hues,
                            lambda c: chip(c["label"],
                                           DateState.sel_countries.contains(c["code"]),
                                           DateState.toggle_country(c["code"]),
                                           hue=c["hue"]))),
                        rx.drawer.close(
                            rx.button("Done", size="2", width="100%"),
                            width="100%",
                        ),
                        spacing="3", width="100%", align="start",
                    ),
                    style={"background": "var(--plate)",
                           "borderTop": "1px solid var(--rule)",
                           "boxShadow": "var(--e3)",
                           "padding": "0.75rem 0.9rem 1.25rem",
                           "maxHeight": "80vh", "overflowY": "auto",
                           "zIndex": "51"},
                ),
            ),
            direction="bottom",
        ),
        # Phone only. Was a .filters-drawer/.filters-inline pair of CSS
        # rules that had to agree with each other; now each box states its
        # own visibility. Reflex first.
        display=["block", "block", "none", "none", "none"], width="100%",
    )


def _hero() -> rx.Component:
    """One unvisited place, offered. Shuffle asks for another."""
    s = DateState.suggestion
    return rx.cond(
        s,
        rx.box(
            rx.vstack(
                rx.text("Somewhere you have not been", size="1",
                        style={"color": "var(--dim)"}),
                rx.link(rx.heading(s["name"], class_name="hero-title"),
                        href=s["url"], is_external=True, underline="none"),
                rx.hstack(
                    rx.box(class_name="hue", style={"background": s["hue"],
                                                    "minHeight": "1rem"}),
                    rx.text(s["list"], size="2", style={"color": "var(--steel)"}),
                    rx.cond(s["country_name"] != "",
                            rx.text(s["country_name"], size="2",
                                    style={"color": "var(--steel)"}),
                            rx.fragment()),
                    rx.text(s["tags"], size="1",
                            style={"color": "var(--mustard)"}),
                    rx.text(s["km"], size="1", class_name="tnum",
                            style={"color": "var(--teal)"}),
                    rx.text(s["left"] + " to choose from", size="1",
                            class_name="tnum", style={"color": "var(--dim)"}),
                    rx.spacer(),
                    width="100%", align="center", spacing="3",
                ),
                rx.hstack(
                    rx.button("Pick another", on_click=DateState.shuffle, size="2"),
                    rx.button("Went here", on_click=DateState.went_suggestion,
                              size="2", variant="surface"),
                    rx.spacer(),
                    # one unit, so a wrap moves "in" down with its select
                    rx.hstack(
                        rx.text("in", size="1", style={"color": "var(--dim)"}),
                        rx.select(DateState.pick_country_options,
                                  value=DateState.pick_country_label, size="2",
                                  on_change=DateState.set_pick_country, width="10rem"),
                        spacing="2", align="center",
                    ),
                    # wraps on a phone: two buttons and a 10rem select do not fit 412px
                    spacing="2", align="center", width="100%", wrap="wrap",
                ),
                rx.text("mood: " + DateState.sel_types_label, size="1",
                        style={"color": "var(--dim)"}),
                spacing="3", align="start", width="100%",
            ),
            class_name="hero", width="100%",
        ),
        rx.box(
            rx.vstack(
                rx.text("Nothing matches that mood", class_name="hero-title"),
                rx.text("No unvisited place in " + DateState.pick_country_label
                        + " is tagged " + DateState.sel_types_label
                        + ". Widen the mood, switch country, or pick anywhere.",
                        class_name="prose"),
                rx.hstack(
                    rx.button("Clear mood", on_click=DateState.clear_types,
                              size="1", variant="surface"),
                    rx.select(DateState.pick_country_options,
                              value=DateState.pick_country_label, size="1",
                              on_change=DateState.set_pick_country, width="10rem"),
                    spacing="2", align="center",
                ),
                spacing="2", align="start",
            ),
            class_name="hero", width="100%",
        ),
    )


def _log_row(e: rx.Var) -> rx.Component:
    return rx.table.row(
        rx.table.row_header_cell(
            rx.cond(
                DateState.edit_mode,
                rx.input(default_value=e["date"], size="1", width="7.5rem",
                         on_blur=DateState.edit_entry(e["id"], "date"),
                         key=f"{e['id']}-date"),
                rx.text(e["date"], size="1", class_name="tnum",
                        style={"whiteSpace": "nowrap"}),
            ),
        ),
        rx.table.cell(
            rx.cond(
                DateState.edit_mode,
                rx.input(default_value=e["place"], size="1", width="100%",
                         on_blur=DateState.edit_entry(e["id"], "place"),
                         key=f"{e['id']}-place"),
                rx.text(e["place"], size="2"),
            ),
        ),
        rx.table.cell(
            rx.cond(
                DateState.edit_mode,
                rx.input(default_value=e["with"], size="1", width="7rem",
                         on_blur=DateState.edit_entry(e["id"], "with"),
                         key=f"{e['id']}-with"),
                rx.text(e["with"], size="1", style={"color": "var(--dim)"}),
            ),
        ),
        rx.table.cell(
            rx.hstack(
                rx.foreach([1, 2, 3, 4, 5], lambda n: rx.button(
                    n, on_click=DateState.rate(e["id"], n), size="1", variant="ghost",
                    style={"minWidth": "1.1rem", "padding": "0 0.15rem",
                           "color": rx.cond(e["rating"].to(int) >= n, "var(--mustard)",
                                            "var(--rule)")})),
                spacing="0", align="center",
            ),
        ),
        rx.table.cell(
            rx.cond(
                DateState.edit_mode,
                rx.input(default_value=e["note"], size="1", width="100%",
                         on_blur=DateState.edit_entry(e["id"], "note"),
                         key=f"{e['id']}-note"),
                rx.text(e["note"], class_name="prose", style={"fontSize": "0.9rem"}),
            ),
        ),
        rx.table.cell(
            rx.cond(DateState.edit_mode,
                    rx.button("Remove", on_click=DateState.delete_entry(e["id"]),
                              size="1", variant="ghost", color_scheme="red"),
                    rx.fragment()),
        ),
    )


def page() -> rx.Component:
    from ..core.ui import chip, filter_row, navbar
    return rx.container(
        rx.vstack(
            navbar("/dates"),
            rx.hstack(
                rx.heading("Dates", size="7"),
                rx.spacer(),
                rx.segmented_control.root(
                    rx.segmented_control.item("Table", value="table"),
                    rx.segmented_control.item("Map", value="map"),
                    value=rx.cond(DateState.show_map, "map", "table"),
                    on_change=DateState.set_view, size="2",
                ),
                width="100%", align="end",
            ),
            _hero(),
            _filter_drawer(),
            rx.box(_mood_filters(), display=["none", "none", "block", "block", "block"], width="100%"),
            rx.hstack(
                rx.text(DateState.place_count, size="1", class_name="tnum",
                        style={"color": "var(--steel)"}),
                rx.spacer(),
                rx.button("Refresh places", on_click=DateState.refresh_places,
                          size="1", variant="surface", loading=DateState.busy),
                rx.button(rx.cond(DateState.edit_mode, "Done", "Edit"),
                          on_click=DateState.toggle_edit, size="1",
                          variant=rx.cond(DateState.edit_mode, "solid", "surface")),
                width="100%", align="center", spacing="3",
            ),
            rx.box(
                filter_row("country", rx.foreach(
                    DateState.country_hues,
                    lambda c: chip(c["label"],
                                   DateState.sel_countries.contains(c["code"]),
                                   DateState.toggle_country(c["code"]),
                                   hue=c["hue"]))),
                display=["none", "none", "block", "block", "block"], width="100%",
            ),
            _map_block(),
            rx.hstack(
                rx.input(placeholder="Search places", value=DateState.search,
                         on_change=DateState.set_search, width="18rem"),
                rx.spacer(),
                rx.text(DateState.page_label, size="1", class_name="tnum",
                        style={"color": "var(--dim)"}),
                rx.button("Prev", on_click=DateState.prev_page, size="1", variant="surface",
                          disabled=DateState.page == 0),
                rx.button("Next", on_click=DateState.next_page, size="1", variant="surface",
                          disabled=DateState.page >= DateState.last_page),
                width="100%", align="center", spacing="3",
            ),
            notice_toast(DateState.notice),
            rx.cond(
                DateState.hidden_count > 0,
                rx.hstack(
                    rx.text(DateState.hidden_count.to_string() + " hidden, kept out of every refresh",
                            size="1", style={"color": "var(--dim)"}),
                    rx.button("Restore", on_click=DateState.restore_hidden, size="1",
                              variant="ghost", style={"color": "var(--steel)"}),
                    align="center", spacing="2",
                ),
                rx.fragment(),
            ),
            rx.cond(
                DateState.job_log != "",
                rx.box(rx.text(DateState.job_log, size="1",
                               style={"whiteSpace": "pre-line",
                                      "fontFamily": "ui-monospace, monospace",
                                      "color": "var(--steel)"}),
                       class_name="block", width="100%",
                       style={"maxHeight": "9rem", "overflowY": "auto"}),
                rx.fragment(),
            ),
            rx.cond(
                DateState.edit_mode,
                rx.hstack(
                    rx.input(placeholder="Place", value=DateState.new_name,
                             on_change=DateState.set_new_name, width="14rem"),
                    rx.input(placeholder="List", value=DateState.new_list,
                             on_change=DateState.set_new_list, width="10rem"),
                    rx.input(placeholder="Maps link", value=DateState.new_url,
                             on_change=DateState.set_new_url, width="16rem"),
                    rx.input(placeholder="AT", value=DateState.new_country,
                             on_change=DateState.set_new_country, width="4rem"),
                    rx.button("Add place", on_click=DateState.add_place, size="2"),
                    spacing="2", align="center", wrap="wrap", width="100%",
                ),
                rx.fragment(),
            ),
            rx.box(
                rx.table.root(
                    rx.table.header(rx.table.row(
                        rx.table.column_header_cell("", style={"width": "8px"}),
                        rx.table.column_header_cell("Us"),
                        _head("name", "Place"), _head("country", "Country"),
                        _head("list", "List", hide_on_phone=True),
                        rx.table.column_header_cell("Rating"),
                        rx.table.column_header_cell("Notes"),
                        rx.table.column_header_cell("Types"),
                        rx.table.column_header_cell("Distance"),
                        _head("been", "Been"),
                        rx.table.column_header_cell(""))),
                    rx.table.body(rx.foreach(DateState.page_rows, _place_row)),
                    variant="surface", size="1",
                    # Radix tables are width:100%, so on a phone they compress to fit and the
                    # overflow_x wrapper never scrolls — the width comes out of the columns
                    # instead. A floor below 48em makes the wrapper scroll, which is the
                    # ordinary phone table. Tiers: initial, xs 30em, sm 48em, md, lg.
                    min_width=["34rem", "34rem", "auto", "auto", "auto"],
                ),
                width="100%", overflow_x="auto",
            ),
            pager(DateState),
            rx.hstack(
                rx.text("Been there", class_name="block-head"),
                rx.spacer(),
                rx.text(DateState.log_count, size="1", class_name="tnum",
                        style={"color": "var(--dim)"}),
                width="100%", align="baseline",
                style={"borderTop": "1px solid var(--rule)", "paddingTop": "1rem"},
            ),
            rx.hstack(
                rx.input(placeholder="YYYY-MM-DD", value=DateState.entry_date,
                         on_change=DateState.set_entry_date, width="9rem", size="1"),
                rx.input(placeholder="Place", value=DateState.entry_place,
                         on_change=DateState.set_entry_place, width="14rem", size="1"),
                rx.input(placeholder="With", value=DateState.entry_with,
                         on_change=DateState.set_entry_with, width="8rem", size="1"),
                rx.input(placeholder="Note", value=DateState.entry_note,
                         on_change=DateState.set_entry_note, width="16rem", size="1"),
                rx.button("Log a date", on_click=DateState.add_entry, size="1",
                          variant="surface"),
                spacing="2", align="center", wrap="wrap", width="100%",
            ),
            rx.cond(
                DateState.log_rows,
                rx.box(
                    rx.table.root(
                        rx.table.body(rx.foreach(DateState.log_rows, _log_row)),
                        variant="ghost", size="1",
                    ),
                    width="100%", overflow_x="auto",
                ),
                rx.text("Press Went on a place above and it lands here.",
                        class_name="prose"),
            ),
            # A trip is a selection of places and
            # travel.py already counts wishlist places per country, so it
            # belongs next to the map rather than next to the watering can.
            rx.divider(margin_y="1rem"),
            T.section(),
            spacing="4", width="100%", align="start",
        ),
        size="4",
        on_mount=DateState.load,
    )
