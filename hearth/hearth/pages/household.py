"""Household: the four routes that did not earn a tab.

/plants, /shops and /games held six rows between
them and cost four tabs, 59 table calls and four files. The theme had
already called them one room — "a page with one row in it does not need a
personality" — and the navigation never followed. This is the page that
follows it.

The four old routes still resolve; they redirect here (hearth.py), because
a phone has them bookmarked.
"""
import reflex as rx

from . import games as G
from . import plants as PL
from . import shops as SH
from ..core.ui import navbar


def _apartment_map() -> rx.Component:
    """Placeholder. Interactive eventually, above
    the plants section, because the rooms here are the rooms plant.room already
    names.

    No floor plan exists yet, so this is an empty box rather than a fictional
    flat. A real one (a SweetHome3D export, say) replaces it; clickable rooms
    filtering the plants below is the reason it sits above them.
    """
    return rx.vstack(
        rx.hstack(
            rx.heading("Apartment", size="5", as_="h2", class_name="block-head"),
            rx.spacer(),
            rx.text("placeholder", size="1",
                    style={"color": "var(--dim)"}),
            width="100%", align="end",
        ),
        rx.box(
            rx.text("Floor plan not drawn yet.", weight="bold", size="2"),
            rx.text("Export one (SweetHome3D works) and it goes here, and "
                    "clicking a room filters the plants below it.",
                    class_name="prose", style={"fontSize": "0.85rem"}),
            class_name="block", width="100%",
            style={"minHeight": "8rem"},
        ),
        spacing="3", width="100%", align="start",
    )

# Order is by how often a thing needs doing, not alphabetical: a plant wants
# water weekly, a trip happens once a year.
SECTIONS = [("plants", "Plants", PL.section),
            ("shops", "Shopping", SH.section),
            ("games", "Games", G.section)]


def page() -> rx.Component:
    return rx.container(
        rx.vstack(
            navbar("/household"),
            rx.heading("Household", size="7"),
            # above the plants section
            rx.box(_apartment_map(), id="apartment", width="100%",
                   class_name="household-section"),
            *[rx.box(section(), id=anchor, width="100%",
                     class_name="household-section")
              for anchor, _, section in SECTIONS],
            spacing="6", width="100%", align="start",
        ),
        size="4",
    )
