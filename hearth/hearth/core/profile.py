"""Who is using this browser, and the two names to show.

Kept in the browser's localStorage, not the database: the tailnet is the only
login and one identity can cover both people's devices, so the server cannot
know who is holding the phone. The header toggle switches in one tap, because
one phone shared by both people is a supported case. This is the honour
system, on purpose.
"""
from datetime import datetime

import reflex as rx

from . import household as H


class ProfileState(rx.State):
    me: str = rx.LocalStorage("", name="couples_me", sync=True)   # name kept from before the rename: the browser remembers who you are under it
    names: dict[str, str] = {s: "" for s in H.SLOTS}
    initials: dict[str, str] = {s: s for s in H.SLOTS}
    backup_warning: str = ""

    @rx.event
    def load(self):
        self.names = H.names()
        self.initials = {s: (n[:1].upper() or s) for s, n in self.names.items()}
        self.backup_warning = H.backup_warning(datetime.now())
        if self.me not in H.SLOTS:     # cleared, or a value from an older build
            self.me = ""

    @rx.event
    def gate(self, route: str):
        """First on_load of every page: fresh names, and /setup until it is done."""
        self.load()
        target = H.setup_redirect(route, H.settings().setup_done)
        if target:
            return rx.redirect(target)

    @rx.event
    def pick(self, slot: str):
        if slot in H.SLOTS:
            self.me = slot


def toggle() -> rx.Component:
    """Both names in the header; the highlighted one is who votes."""
    def one(slot: str) -> rx.Component:
        return rx.button(
            ProfileState.names[slot], size="1",
            variant=rx.cond(ProfileState.me == slot, "solid", "surface"),
            on_click=ProfileState.pick(slot),
        )
    return rx.hstack(*[one(s) for s in H.SLOTS], spacing="1", class_name="profile-toggle")
