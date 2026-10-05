"""Shared shell: palette, the tab bar every page carries, and two widgets
used by more than one page."""
import functools
import random
from datetime import date
from typing import Callable

import reflex as rx

from .profile import toggle as profile_toggle

ACCENT = "orange"

# Names, because nobody remembers that Macedonia is MK. The database keeps the
# ISO-2 code; every surface shows the name. Scoped to Europe plus the places
# these lists actually reach rather than all 249 codes, which would make the
# dropdown unusable.
COUNTRIES = {
    "AL": "Albania", "AD": "Andorra", "AT": "Austria", "BY": "Belarus",
    "BE": "Belgium", "BA": "Bosnia and Herzegovina", "BG": "Bulgaria",
    "HR": "Croatia", "CY": "Cyprus", "CZ": "Czechia", "DK": "Denmark",
    "EE": "Estonia", "FI": "Finland", "FR": "France", "DE": "Germany",
    "GR": "Greece", "HU": "Hungary", "IS": "Iceland", "IE": "Ireland",
    "IT": "Italy", "LV": "Latvia", "LI": "Liechtenstein", "LT": "Lithuania",
    "LU": "Luxembourg", "MT": "Malta", "MD": "Moldova", "MC": "Monaco",
    "ME": "Montenegro", "NL": "Netherlands", "MK": "North Macedonia",
    "NO": "Norway", "PL": "Poland", "PT": "Portugal", "RO": "Romania",
    "SM": "San Marino", "RS": "Serbia", "SK": "Slovakia", "SI": "Slovenia",
    "ES": "Spain", "SE": "Sweden", "CH": "Switzerland", "TR": "Turkey",
    "UA": "Ukraine", "GB": "United Kingdom", "VA": "Vatican City",
    "AU": "Australia", "BR": "Brazil", "CA": "Canada", "CN": "China",
    "EG": "Egypt", "IN": "India", "IL": "Israel", "JP": "Japan",
    "MA": "Morocco", "MX": "Mexico", "NZ": "New Zealand", "SG": "Singapore",
    "KR": "South Korea", "TH": "Thailand", "AE": "United Arab Emirates",
    "US": "United States", "VN": "Vietnam", "ZA": "South Africa",
}
NAME_TO_CODE = {v: k for k, v in COUNTRIES.items()}
NO_COUNTRY = "— none —"


def country_name(code: str) -> str:
    """Code to name, falling back to the code itself so an unmapped country is
    still visible rather than blank."""
    if not code or code in ("unsorted", "ideas"):
        return code or ""
    return COUNTRIES.get(code.upper(), code)


def country_code(name: str) -> str:
    if not name or name == NO_COUNTRY:
        return ""
    return NAME_TO_CODE.get(name, name.upper()[:2])


# Country reads as colour first. Pin a hue per ISO-2 code here if you like;
# anything unpinned gets a deterministic one from the cycle.
HUES: dict[str, str] = {}
_CYCLE = ["#F2A93B", "#3FB6A8", "#E2503F", "#8E7CC3", "#7C8CA8"]

# Medium gets the same treatment as country: the chip wears the colour that the
# rows are keyed by, so the filter row needs no label above it.
MEDIUM_HUES = {"Anime": "#F2A93B", "Anime film": "#E2503F",
               "Movie": "#3FB6A8", "TV": "#8E7CC3"}


def medium_hue(label: str) -> str:
    return MEDIUM_HUES.get(label, "#2C456B")


def filter_row(label: str, chips: rx.Component, tail: rx.Component | None = None) -> rx.Component:
    """One row of filters with its name on the same line, not stacked above it.

    Four unlabelled chip rows at the same weight were unreadable; naming them
    inline costs one column and no vertical space.
    """
    return rx.hstack(
        rx.text(label, size="1", style={"color": "var(--dim)", "minWidth": "4.25rem",
                                        "flex": "0 0 4.25rem", "paddingTop": "0.18rem"}),
        rx.box(chips, class_name="filter-row", width="100%"),
        *( [tail] if tail is not None else [] ),
        width="100%", align="start", spacing="2",
    )


def choice_row(label: str, current: rx.Var, on_pick, options) -> rx.Component:
    """A filter row of mutually exclusive chips. `options` is [(key, text)];
    the handler is expected to clear the filter when the held key comes back."""
    return filter_row(label, rx.hstack(
        *[chip(text, current == key, on_pick(key)) for key, text in options],
        spacing="2"))


def country_hue(code: str) -> str:
    if not code:
        return "#2C456B"
    return HUES.get(code, _CYCLE[sum(map(ord, code)) % len(_CYCLE)])

# Nine tabs, not twelve. /plants, /shops, /travel and /games
# held seven rows between them and are now four sections of /household.
TABS = [("Tonight", "/"), ("Library", "/library"), ("Books", "/books"),
        ("Recipes", "/recipes"),
        ("Dates", "/dates"), ("Music", "/music"),
        ("Conversation", "/convo"),
        ("Household", "/household")]


# Single-codepoint emoji only: anything built from a ZWJ sequence or a variation
# selector would be split in half by sample().
EMOJI = ("🌙 🍜 🎮 📚 🌿 🍷 🎧 🔥 🌊 🍕 🎬 🐉 🌸 🍣 🧸 🎲 🌵 🍩 🚀 🦊 🍓 🎨 🪴 🐙 "
         "🌈 🍋 🎸 🧁 🌻 🦉 🍄 🎯 🐢 🌮 🎹 🪐 🍉 🦋 🧩 🍫 🌋 🐝 🎪 🥟 🦄 🍂 🐳 🍒 🦀 🍿").split()


def daily_emoji(day: date) -> str:
    """Five emoji seeded by the date, so both phones show the same set all day."""
    return "".join(random.Random(day.toordinal()).sample(EMOJI, 5))


class NavState(rx.State):
    # cache=False, and a var rather than a string baked into the page: prod
    # caches its build, so anything computed at compile time would never turn
    # over. Recomputed per event, which is five picks from fifty.
    @rx.var(cache=False)
    def emoji(self) -> str:
        return daily_emoji(date.today())


def navbar(active: str) -> rx.Component:
    """A real navigation bar, not a row of links.

    What was here before was an hstack of styled text with the whole
    appearance inline, which is why no page theme and no spike could reach it.
    Everything static is now in `.nav` in ledger.css; the only inline value
    left is the room's signature hue on the active tab, which varies per page
    and has to beat the stylesheet.

    Sticky, because nine tabs you have to scroll back up to reach is a list,
    not a bar. ⌘K is left to the `?` overlay; a hint sitting in the corner of
    every page is clutter the second you have learnt it.

    Below 62em the tabs give way to a menu ("the navbar
    becomes a hamburger"): a sideways-scrolling strip showed three of nine tabs
    on a phone, and nine tabs overflow any window under ~990px (measured: 74px
    past an 800px tablet). The bar names the page you are on instead, and each menu entry
    carries its own room's signature, so the list is also a key to the rooms.
    """
    def tab(label: str, href: str) -> rx.Component:
        on = href == active
        return rx.link(
            label, href=href, size="2", underline="none",
            class_name="nav-tab on" if on else "nav-tab",
            style={"background": "var(--signature, var(--mustard))"} if on else {},
        )

    def entry(label: str, href: str) -> rx.Component:
        # on_select, not an rx.link child: as_child needs a single element and
        # rx.link is not one, which crashed the page. _redirect is handled in
        # the browser, so this is a client-side navigation, tap or Enter alike.
        return rx.menu.item(
            label, on_select=rx.redirect(href),
            class_name=(f"nav-menu-item room-{ROOMS.get(href, 'lobby')}"
                        + (" on" if href == active else "")),
        )

    here = next((label for label, href in TABS if href == active), "Ledger")
    phone = ["block", "block", "block", "none", "none"]
    return rx.hstack(
        rx.link(
            rx.hstack(
                rx.box(class_name="nav-mark"),
                # On a phone the bar names the page, since the tabs are folded away.
                rx.text(here, class_name="nav-brand", display=phone),
                rx.text("Ledger", class_name="nav-brand",
                        display=["none", "none", "none", "block", "block"]),
                spacing="2", align="center",
            ),
            href="/", underline="none",
        ),
        rx.box(
            *[tab(label, href) for label, href in TABS],
            class_name="nav-tabs",
            display=["none", "none", "none", "flex", "flex"],
        ),
        rx.spacer(),
        profile_toggle(),
        rx.link(rx.icon("settings", size=18), href="/settings", aria_label="Settings",
                class_name="nav-settings"),
        rx.text(NavState.emoji, class_name="nav-emoji"),
        rx.box(
            rx.menu.root(
                rx.menu.trigger(
                    rx.icon_button(rx.icon("menu"), variant="surface", size="2",
                                   aria_label="Pages"),
                ),
                rx.menu.content(*[entry(label, href) for label, href in TABS],
                                align="end", class_name="nav-menu"),
            ),
            display=phone,
        ),
        # No inline width. It used to be width="100%", which is 100% of the
        # 1440px container — the bar reached the left edge via its negative
        # margin and stopped short on the right. The width is 100vw, in CSS,
        # where the breakout that needs it also lives.
        align="center", spacing="3",
        class_name="nav",
    )


def chip(label: rx.Var, selected: rx.Var, on_click, dashed: bool = False,
         hue: rx.Var | str = "var(--rule)") -> rx.Component:
    """A filter that shows what it filters: when a hue is given the chip wears it,
    so the country chips and the colour bars on the rows are the same key."""
    tint = hue
    return rx.button(
        label,
        on_click=on_click,
        size="1",
        # NOT variant="ghost": Radix gives ghost buttons margin: -4px -8px to
        # optically align their label, which swallows the row gap and overlaps
        # every neighbouring chip by 10px. Surface has no such margin.
        variant="surface",
        style={"cursor": "pointer", "borderRadius": "2px",
               # Radix ghost buttons ship margin: -4px -8px to optically align
               # their label. In a chip row that swallows the gap and the chips
               # overlap by 10px, so it has to go.
               "margin": "0",
               "padding": "0.15rem 0.55rem",
               "fontWeight": "600",
               "border": rx.cond(selected, f"1px solid {tint}",
                                 "1px solid var(--rule)"),
               "borderStyle": "dashed" if dashed else "solid",
               "background": rx.cond(selected, tint, "transparent"),
               "color": rx.cond(selected, "var(--ink)", "var(--steel)")},
    )


def stub(title: str, route: str, note: str) -> rx.Component:
    return rx.container(
        rx.vstack(
            navbar(route),
            rx.heading(title, size="7"),
            rx.text(note, size="2", color_scheme="gray"),
            spacing="4", width="100%", align="start",
        ),
        size="4", padding="1.5rem",
    )


# ---------------------------------------------------------------------------
# The shell every page repeats by hand.
#
# Eleven pages open with the same container, the same navbar, the same
# heading-plus-summary row, and eight of them wrap the same table in the same
# scrolling box. That repetition is why the header drifts: /music and /plants
# grew a two-line summary, /dates grew a segmented control, and each one
# re-typed the surrounding hstack to get there.
#
# These are deliberately thin. They take the arguments the pages actually vary
# and nothing else — no slots "for later", no config for a padding that has
# never changed.
# ---------------------------------------------------------------------------
def stat(value: rx.Var | str, label: str = "") -> rx.Component:
    """A number and what it counts. Tabular, dim, and always the same size, so
    two pages' summaries line up instead of each picking their own."""
    return rx.hstack(
        rx.text(value, size="1", class_name="tnum", style={"color": "var(--steel)"}),
        *([rx.text(label, size="1", style={"color": "var(--dim)"})] if label else []),
        spacing="1", align="baseline",
    )


def page_shell(title: str, route: str, *children: rx.Component,
               aside: rx.Component | None = None,
               on_mount=None) -> rx.Component:
    """Container, navbar, title row, then whatever the page is.

    `aside` is the right-hand side of the title row — a summary line on most
    pages, a segmented control on /dates, two stacked lines on /music. Passing
    the component rather than a string is what lets all three share this.
    """
    kw = {"on_mount": on_mount} if on_mount is not None else {}
    return rx.container(
        rx.vstack(
            navbar(route),
            rx.hstack(
                rx.heading(title, size="7"),
                rx.spacer(),
                aside if aside is not None else rx.fragment(),
                width="100%", align="end",
            ),
            *children,
            spacing="4", width="100%", align="start",
        ),
        size="4", **kw,
    )


def notice_toast(message) -> rx.Component:
    """The one place a write says what it did.

    §3.4 asked for `rx.toast` on "every write that currently shows nothing".
    Measuring first: nothing was silent. All eleven states already carry a
    `notice: str`, 114 handlers set it, and every page already rendered it — as
    a line of small mustard text, inline, in the middle of the page, where it
    scrolled away with everything else.

    So this is not a new channel. It is the existing one, moved to a fixed
    corner, given elevation, and dismissed on a timer by `keys.js`, which
    watches the node rather than the state — the same DOM bridge the keyboard
    already uses. No handler changed; a toast the backend has to remember to
    dismiss is a toast that gets stuck.
    """
    return rx.cond(
        message != "",
        rx.box(rx.text(message, size="2"), class_name="toast", role="status",
               aria_live="polite"),
        rx.fragment(),
    )


def toolbar(*fields: rx.Component) -> rx.Component:
    """The add-a-row form. Wraps, because on a phone it has to."""
    return rx.hstack(*fields, width="100%", align="center", spacing="2",
                     wrap="wrap", class_name="toolbar")


def empty_state(line: str, action: rx.Component | None = None) -> rx.Component:
    """What five pages currently do not have. A table header with nothing under
    it looks like a bug; a sentence saying the shelf is empty does not."""
    return rx.vstack(
        rx.text(line, class_name="prose"),
        action if action is not None else rx.fragment(),
        spacing="3", align="start", width="100%",
        style={"borderTop": "1px solid var(--rule-2)", "paddingTop": "1rem"},
    )


def pager(state) -> rx.Component:
    """Page label and Prev/Next, placed above and below every paged table so a
    long page does not need scrolling back up. Any state with page, last_page,
    page_label, prev_page and next_page fits."""
    return rx.hstack(
        rx.text(state.page_label, size="1", class_name="tnum",
                style={"color": "var(--dim)"}),
        rx.spacer(),
        rx.button("Prev", on_click=state.prev_page, size="1",
                  variant="surface", disabled=state.page == 0),
        rx.button("Next", on_click=state.next_page, size="1",
                  variant="surface", disabled=state.page >= state.last_page),
        width="100%", align="center",
    )


def data_table(columns: list[str], rows: rx.Var, row_fn,
               empty: rx.Component | None = None) -> rx.Component:
    """Header, body, and the horizontal scroll box that every table page wraps
    itself in. `empty` replaces the table when there are no rows at all."""
    table = rx.box(
        rx.table.root(
            rx.table.header(rx.table.row(
                *[rx.table.column_header_cell(c) for c in columns])),
            rx.table.body(rx.foreach(rows, row_fn)),
            variant="surface", size="1",
            # Radix tables are width:100%, so on a phone they compress to fit and the
            # overflow_x wrapper never scrolls — the width comes out of the columns
            # instead. A floor below 48em makes the wrapper scroll, which is the
            # ordinary phone table. Tiers: initial, xs 30em, sm 48em, md, lg.
            min_width=["34rem", "34rem", "auto", "auto", "auto"],
        ),
        width="100%", overflow_x="auto",
    )
    return table if empty is None else rx.cond(rows, table, empty)


# Room and page assignments: rooms first, then the page
# tints. Routes not listed fall back to the untinted base, so a new page is
# never broken by being forgotten here.
ROOMS = {
    "/": "lobby",
    "/library": "ledger", "/books": "ledger", "/music": "ledger",
    "/dates": "field",
    "/convo": "private",
    "/recipes": "household", "/recipes/[slug]": "household",
    "/meal-plan": "household", "/household": "household",
}
PAGE_TINTS = {
    "/": "lobby", "/library": "library", "/books": "books", "/music": "music",
    "/dates": "dates", "/convo": "convo",
    "/household": "household",
    # The three recipe views are one place and read as one.
    "/recipes": "recipes", "/recipes/[slug]": "recipes", "/meal-plan": "recipes",
}


def themed(page_fn: Callable[[], rx.Component], route: str) -> Callable[[], rx.Component]:
    """Wrap a page in the element its room and page classes hang off.

    Putting these classes on `page_shell` would have meant
    retrofitting eleven pages onto the shell first. They are custom properties:
    they inherit, so any ancestor will do. Wrapping at `add_page` themes all
    fourteen routes without opening a single page file, and leaves the shell
    retrofit as the separate piece of work it always was.
    """
    room, tint = ROOMS.get(route), PAGE_TINTS.get(route)
    if room is None and tint is None:
        return page_fn
    classes = " ".join(c for c in ("room", f"room-{room}" if room else "",
                                   f"page-{tint}" if tint else "") if c)

    @functools.wraps(page_fn)
    def wrapped() -> rx.Component:
        # Skeletons. `is_hydrated` is Reflex's own flag and is
        # false only until the socket connects, so this fires on a cold load or
        # a refresh and not on client-side navigation between routes. One wrap
        # here covers every page; no state gained a `loading` field.
        return rx.box(
            rx.skeleton(page_fn(), loading=~rx.State.is_hydrated),
            class_name=classes, width="100%",
        )

    return wrapped
