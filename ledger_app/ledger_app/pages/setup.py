"""First run, and Settings afterwards: the two names and the home location.

The same form serves both routes. Secrets are not here on purpose: TMDB and
Spotify keys stay in .env, next to compose.yml, so no backup ever carries one.
"""
import os
from datetime import datetime

import reflex as rx

from ..core import household as H
from ..core.profile import ProfileState
from ..core.ui import navbar

class SetupState(rx.State):
    version: str = ""                   # read per request: pages compile at image build
    first: str = ""
    second: str = ""
    latlon: str = ""
    place: str = ""
    error: str = ""
    backup_status: str = ""

    @rx.event
    def load(self):
        names = H.names()
        self.first, self.second = names["1"], names["2"]
        home = H.home()
        self.latlon = f"{home[0]},{home[1]}" if home else ""
        self.place, self.error = "", ""
        self.backup_status = H.backup_status(datetime.now())
        self.version = os.environ.get("LEDGER_VERSION", "dev")

    @rx.event
    def set_first(self, v: str):
        self.first = v

    @rx.event
    def set_second(self, v: str):
        self.second = v

    @rx.event
    def set_latlon(self, v: str):
        self.latlon = v

    @rx.event
    def set_place(self, v: str):
        self.place = v

    @rx.event
    def find_place(self):
        """Optional lookup through OpenStreetMap Nominatim, the geocoder
        scripts/data/geocode_places.py already uses. Needs the internet."""
        from geopy.geocoders import Nominatim
        try:
            hit = Nominatim(user_agent="couples-app", timeout=5).geocode(self.place)
        except Exception as e:          # offline, rate limited, timed out
            self.error = f"Lookup failed ({e}). Type lat,lon instead."
            return
        if hit is None:
            self.error = f"Nothing found for {self.place!r}."
            return
        self.latlon, self.error = f"{hit.latitude:.4f},{hit.longitude:.4f}", ""

    @rx.event
    def save(self):
        try:
            latlon = H.parse_latlon(self.latlon)   # validate both before writing either
            H.set_names(self.first, self.second)
        except ValueError as e:
            self.error = str(e)
            return
        H.set_home(latlon)
        H.finish_setup()
        return [ProfileState.load, rx.redirect("/")]


def _form() -> rx.Component:
    return rx.vstack(
        rx.heading("Who lives here", size="5"),
        rx.text("Two names. Votes follow the person, so renaming later keeps them.", size="2"),
        rx.input(placeholder="First name", value=SetupState.first,
                 on_change=SetupState.set_first, width="100%"),
        rx.input(placeholder="Second name", value=SetupState.second,
                 on_change=SetupState.set_second, width="100%"),
        rx.heading("Home (optional)", size="4"),
        rx.text("Distances on Tonight and Dates are measured from here. "
                "Leave it blank to hide them.", size="2"),
        rx.hstack(
            rx.input(placeholder="City or address", value=SetupState.place,
                     on_change=SetupState.set_place, width="100%"),
            rx.button("Find", on_click=SetupState.find_place, variant="surface"),
            width="100%",
        ),
        rx.input(placeholder="lat,lon", value=SetupState.latlon,
                 on_change=SetupState.set_latlon, width="100%"),
        rx.cond(SetupState.error != "",
                rx.callout(SetupState.error, color_scheme="red", size="1")),
        rx.button("Save", on_click=SetupState.save),
        rx.text("TMDB and Spotify are optional; their keys go in .env. See the README.",
                size="1", style={"color": "var(--dim)"}),
        spacing="3", width="100%", max_width="28rem",
    )


def setup_page() -> rx.Component:
    return rx.container(_form(), size="2", padding="1.5rem")


def settings_page() -> rx.Component:
    return rx.container(
        navbar("/settings"),
        _form(),
        rx.text(SetupState.backup_status, size="1", style={"color": "var(--dim)"}),
        rx.text("Version ", SetupState.version, size="1", style={"color": "var(--dim)"}),
        size="2", padding="1.5rem",
    )
