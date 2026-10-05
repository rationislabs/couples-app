"""The two people and the household's settings.

Every read and write of `User` and `Household` goes through here. People are
fixed slots, "1" and "2" (user ids 1 and 2), because the app is for exactly
two people. Components are compiled once, when the image is built, so pages
are laid out per slot and read the names from state: a name is data, not
structure.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from geopy.distance import geodesic
from sqlmodel import Session

from .models import Household, User

SLOTS = ("1", "2")
STALE_AFTER = timedelta(hours=48)


def _engine():
    """Imported on use: state imports verdicts, which imports this module."""
    from .state import ENGINE
    return ENGINE


def settings() -> Household:
    with Session(_engine()) as s:
        return s.get(Household, 1) or Household(id=1)


def names() -> dict[str, str]:
    with Session(_engine()) as s:
        return {slot: (s.get(User, int(slot)) or User()).display_name for slot in SLOTS}


def set_names(first: str, second: str) -> None:
    a, b = first.strip(), second.strip()
    if not a or not b:
        raise ValueError("Both names are needed.")
    if a.lower() == b.lower():
        raise ValueError("The two names must be different.")
    with Session(_engine()) as s:
        for slot, name in zip(SLOTS, (a, b)):
            user = s.get(User, int(slot)) or User(id=int(slot))
            user.display_name = name
            s.add(user)
        s.commit()


def parse_latlon(text: str) -> tuple[float, float] | None:
    """'48.2, 16.37' -> (48.2, 16.37). Blank means no home location."""
    if not text.strip():
        return None
    try:
        lat, lon = (float(x) for x in text.split(","))
    except ValueError:
        raise ValueError("Write the location as lat,lon, for example 48.2,16.37.") from None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError("Latitude must be between -90 and 90, longitude between -180 and 180.")
    return lat, lon


def set_home(latlon: tuple[float, float] | None) -> None:
    with Session(_engine()) as s:
        h = s.get(Household, 1) or Household(id=1)
        h.home_lat, h.home_lon = latlon if latlon else (None, None)
        s.add(h)
        s.commit()


def home() -> tuple[float, float] | None:
    h = settings()
    if h.home_lat is None or h.home_lon is None:
        return None
    return h.home_lat, h.home_lon


def distance_km(origin, lat, lon) -> float | None:
    """None when there is no home or the place has no coordinates."""
    if origin is None or lat is None or lon is None:
        return None
    return geodesic(origin, (lat, lon)).km


def finish_setup() -> None:
    with Session(_engine()) as s:
        h = s.get(Household, 1) or Household(id=1)
        h.setup_done = True
        s.add(h)
        s.commit()


def setup_redirect(route: str, setup_done: bool) -> str | None:
    """Where a page load should go instead, or None to stay."""
    if route == "/setup":
        return "/" if setup_done else None
    return None if setup_done else "/setup"


def backup_warning(now: datetime) -> str:
    """The banner text, or "" when the last backup is fine and recent."""
    h = settings()
    if h.last_backup_ok is False:
        return f"Last backup failed: {h.last_backup_error or 'unknown error'}"
    if h.last_backup_at is None:
        return "No backup has run yet."
    if now - h.last_backup_at > STALE_AFTER:
        return f"No backup since {h.last_backup_at:%Y-%m-%d %H:%M}."
    return ""


def backup_status(now: datetime) -> str:
    """One line for Settings."""
    warning = backup_warning(now)
    if warning:
        return warning
    return f"Last backup {settings().last_backup_at:%Y-%m-%d %H:%M}, verified."
