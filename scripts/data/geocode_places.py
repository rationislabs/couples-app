#!/usr/bin/env python3
"""Fill in coordinates and city for saved places, via OpenStreetMap Nominatim.

    ./.venv/bin/python geocode_places.py --limit 20        # try 20, write them
    ./.venv/bin/python geocode_places.py --dry-run --limit 20
    ./.venv/bin/python geocode_places.py                   # everything missing

Deliberately conservative. An unconstrained Nominatim search on these names is
wrong roughly a third of the time — a cave name can come back as a
residential street in the capital, 150km from the real cave. A wrong coordinate in
a distance filter is worse than no coordinate, so two guards apply and anything
that fails them is left blank rather than guessed:

  1. the result's OSM class must be somewhere you can go (amenity, tourism,
     leisure, natural, historic, shop, ...) and not a region (place=hamlet,
     highway, boundary, landuse);
  2. if our own keyword classifier already decided what kind of place it is,
     OSM's type has to agree with it.

Resumable: rows that already have a coordinate are skipped, so it can be run in
batches and interrupted safely. Rows you fixed by hand (geo_source == "manual")
are never touched.
"""
from __future__ import annotations

import pathlib
import sys
from collections import Counter

from geopy.exc import GeocoderQuotaExceeded, GeocoderServiceError
from geopy.extra.rate_limiter import RateLimiter
from geopy.geocoders import Nominatim
from sqlmodel import Session, create_engine, select

from ledger_app.core.models import Place              # noqa: E402
from ledger_app.core.place_types import classify       # noqa: E402

APP = pathlib.Path(__file__).resolve().parents[2] / "ledger_app"
ENGINE = create_engine(f"sqlite:///{APP / 'ledger.db'}")

USER_AGENT = "media-ledger-personal/1.0 (single-user hobby project)"

# OSM classes that can be a place you go to.
POI_CLASS = {"amenity", "tourism", "leisure", "natural", "historic", "shop",
             "craft", "man_made", "waterway", "sport", "club", "office",
             "building", "landuse"}

# our type -> the OSM types that would corroborate it
CORROBORATE: dict[str, set[str]] = {
    "restaurant": {"restaurant", "fast_food", "pub", "bar", "biergarten", "food_court"},
    "cafe":       {"cafe", "bakery", "ice_cream", "coffee"},
    "bar":        {"bar", "pub", "biergarten", "nightclub", "brewery", "wine", "alcohol"},
    "dessert":    {"ice_cream", "bakery", "confectionery", "pastry", "chocolate"},
    "hike":       {"peak", "saddle", "ridge", "alpine_hut", "wilderness_hut",
                   "viewpoint", "trailhead", "path", "hut"},
    "gorge":      {"gorge", "ravine", "valley", "waterfall", "canyon", "cliff"},
    "cave":       {"cave_entrance", "cave"},
    "climb":      {"climbing", "climbing_adventure", "sports_centre", "cliff", "via_ferrata"},
    "bike":       {"bicycle", "cycling", "bicycle_rental", "path", "track", "sports_centre"},
    "ski":        {"piste", "ski", "ski_school", "ski_rental", "sports_centre", "resort"},
    "lake":       {"water", "lake", "reservoir", "pond", "bay"},
    "beach":      {"beach", "beach_resort", "shingle", "sand"},
    "thermal":    {"spa", "public_bath", "swimming_pool", "sauna", "hot_spring", "spa_resort"},
    "pool":       {"swimming_pool", "water_park", "swimming_area", "sports_centre"},
    "museum":     {"museum", "gallery", "artwork", "attraction", "exhibition_centre"},
    "castle":     {"castle", "fort", "ruins", "manor", "palace", "city_gate", "tower"},
    "church":     {"church", "cathedral", "chapel", "monastery", "place_of_worship",
                   "synagogue", "mosque", "shrine"},
    "theatre":    {"theatre", "opera_house", "arts_centre", "cinema", "nightclub",
                   "concert_hall", "music_venue", "events_venue", "stadium"},
    "park":       {"park", "garden", "nature_reserve", "forest", "wood",
                   "recreation_ground", "village_green", "island"},
    "garden":     {"garden", "botanical_garden", "greenhouse", "park", "allotments"},
    "viewpoint":  {"viewpoint", "tower", "attraction", "peak", "bridge",
                   "observatory", "communications_tower"},
    "zoo":        {"zoo", "aquarium", "theme_park", "attraction", "wildlife_park",
                   "animal_boarding"},
    "minigolf":   {"miniature_golf", "golf_course", "pitch", "sports_centre"},
    "gokart":     {"karting", "raceway", "track", "motorsport", "sports_centre"},
    "bowling":    {"bowling_alley", "sports_centre", "amusement_arcade"},
    "escape":     {"escape_game", "amusement_arcade", "attraction"},
    "arcade":     {"amusement_arcade", "trampoline_park", "adventure_park",
                   "attraction", "playground", "paintball"},
    "market":     {"marketplace", "market", "mall", "supermarket"},
    # retail and generic buckets: any real POI class is enough, so no type list
    "shop": set(), "vintage": set(), "deli": set(), "city": set(), "at-home": set(),
}

CITY_KEYS = ("city", "town", "village", "municipality", "suburb", "county")
klass = lambda raw: raw.get("class") or raw.get("category") or ""


def pick(place: Place, results: list) -> tuple[object | None, str]:
    """The first result that clears both guards, or why nothing did."""
    if not results:
        return None, "no result"
    mine = classify(place.name, place.list_name, place.note)
    expected: set[str] = set()
    for m in mine:
        expected |= CORROBORATE.get(m, set())
    # a type we have no expectations for should not veto anything
    if mine and all(not CORROBORATE.get(m, set()) for m in mine):
        expected = set()

    for loc in results:
        raw = loc.raw
        if klass(raw) not in POI_CLASS:
            continue
        if expected and raw.get("type") not in expected:
            continue
        return loc, "ok"

    top = results[0].raw
    return None, f"rejected ({klass(top)}/{top.get('type')})"


def main() -> int:
    dry = "--dry-run" in sys.argv
    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])

    geolocator = Nominatim(user_agent=USER_AGENT, timeout=20)
    # 1 req/sec is Nominatim's published limit; the retries matter more, since a
    # single timeout over a 1400-request run should not end the job
    lookup = RateLimiter(geolocator.geocode, min_delay_seconds=1.1,
                         max_retries=3, error_wait_seconds=10.0,
                         swallow_exceptions=False)

    with Session(ENGINE) as s:
        todo = [p for p in s.exec(select(Place)).all()
                if not p.dismissed and p.lat is None
                and p.geo_source != "manual" and p.maps_url]
    todo.sort(key=lambda p: p.name.lower())
    if limit:
        todo = todo[:limit]
    print(f"{len(todo)} places to try, ~{len(todo) * 1.1 / 60:.0f} min at 1/sec\n",
          flush=True)

    stats: Counter = Counter()
    for i, p in enumerate(todo, 1):
        query = f"{p.name}, {p.country}" if p.country else p.name
        try:
            results = lookup(query, exactly_one=False, addressdetails=True,
                             limit=3,
                             country_codes=p.country.lower() or None) or []
        except (GeocoderQuotaExceeded, GeocoderServiceError) as e:
            print(f"  [{i}] SERVICE ERROR, stopping: {e}", flush=True)
            break
        except Exception as e:                       # noqa: BLE001
            stats["error"] += 1
            print(f"  [{i}] error {p.name[:38]}: {type(e).__name__}", flush=True)
            continue

        loc, why = pick(p, list(results))
        if loc is None:
            stats["rejected"] += 1
            if i % 25 == 0 or len(todo) <= 30:
                print(f"  [{i}] rej {p.name[:34]:36} {why}", flush=True)
            continue

        raw = loc.raw
        addr = raw.get("address", {})
        city = next((addr[k] for k in CITY_KEYS if addr.get(k)), "")
        stats["accepted"] += 1
        if i % 25 == 0 or len(todo) <= 30:
            print(f"  [{i}] OK  {p.name[:34]:36} "
                  f"{klass(raw)}/{raw.get('type')} {city} "
                  f"{loc.latitude:.4f},{loc.longitude:.4f}", flush=True)
        if not dry:
            with Session(ENGINE) as s:
                row = s.get(Place, p.id)
                if row and row.geo_source != "manual":
                    row.lat, row.lon = loc.latitude, loc.longitude
                    row.city = city
                    row.geo_source = "nominatim"
                    s.add(row)
                    s.commit()

    n = sum(stats.values()) or 1
    print(f"\naccepted {stats['accepted']} ({stats['accepted'] / n:.0%}), "
          f"rejected {stats['rejected']}, errors {stats['error']}")
    if dry:
        print("--dry-run: nothing written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
