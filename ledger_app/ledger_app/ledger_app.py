"""Media Ledger — Reflex app."""
import reflex as rx

from .core import models  # noqa: F401  (so `reflex db makemigrations` sees the tables)
from .pages.recipes import RecipeState
from .core.state import LedgerState
from .pages import dates as D
from .pages import music as M
from .pages import travel as T
from .pages import convo as C
from .pages import home as H
from .pages import games as G
from .pages import plants as PL
from .pages import shops as SH
from .pages import books as BK
from .pages import recipes as R
from .pages import household as HH
from .core import verdicts as V
from .core import backup as BKP
from .core.profile import ProfileState
from .pages import setup as SU
from .core import inline as IN
from .core.ui import ACCENT, chip, choice_row, filter_row, navbar, themed, notice_toast, pager

# Four numeric columns — seasons, on season, on episode, episodes — were one
# fact, "how far in are we", spread across four cells you had to read together
# and divide in your head. They are now a single Progress cell: a bar for the
# proportion, a line for the bookmark. The inline editors for all four survive
# inside it, so nothing became read-only. Sorting stays on current_episode,
# which is what you were sorting by when you clicked any of the four.
COLUMNS = [
    # (sort key, label, desktop width). The width used to be ten nth-child
    # rules in ledger.css, renumbered by hand every time this list changed;
    # forgetting silently gave one column another's width. Now each column
    # states its own, as a Reflex responsive prop: auto below 62em, where the
    # table scrolls, fixed above. Sums to 100.
    # "Us" is not sortable: sort_key is compared against a row key, and the
    # verdict lives across two of them.
    ("", "Us", "11%"),
    ("name", "Title", "14%"),
    ("medium", "Medium", "6%"),
    ("lists", "Lists", "8%"),
    ("genres", "Genres", "9%"),
    ("current_episode", "Progress", "11%"),
    ("last_played", "Last played", "7%"),
    ("release_date", "Release", "6%"),
    ("description", "Description", "16%"),
    ("rating", "Rating", "4%"),
    ("notes", "Notes", "8%"),
]


def num_cell(r: rx.Var, field: str, raw_key: str, shown_key: str) -> rx.Component:
    """Read-only text, or a small number box while editing."""
    return rx.table.cell(
        rx.cond(
            LedgerState.edit_mode,
            rx.input(default_value=r[raw_key], size="1", width="4.2rem",
                     placeholder="—", type="number",
                     on_blur=LedgerState.set_number(field, r["name"]),
                     key=f"{r['name']}-{field}"),
            rx.text(r[shown_key], size="1",
                    style={"font_variant_numeric": "tabular-nums"}),
        ),
    )


def progress_cell(r: rx.Var) -> rx.Component:
    """One cell for how far in you are.

    Read mode is a bar plus "S2 · E7  7/12". Edit mode is the same four number
    boxes as before, laid out in one row: hiding an editor to tidy a table is
    how a column becomes unreachable on a phone.
    """
    def box(field: str, raw_key: str, ph: str) -> rx.Component:
        return rx.input(default_value=r[raw_key], size="1", width="3.4rem",
                        placeholder=ph, type="number",
                        on_blur=LedgerState.set_number(field, r["name"]),
                        key=f"{r['name']}-{field}")

    return rx.table.cell(
        rx.cond(
            LedgerState.edit_mode,
            rx.hstack(
                box("seasons", "seasons_raw", "S"),
                box("current_season", "current_raw", "on S"),
                box("current_episode", "current_ep_raw", "on E"),
                box("episodes", "episodes_raw", "played"),
                spacing="1", wrap="wrap",
            ),
            rx.vstack(
                # A zero-width bar on a row with no totals would read as "none
                # watched" rather than "not known", so it only appears when
                # there is a real proportion behind it.
                rx.cond(
                    # page_rows is list[dict[str, str]]: every value arrives as a
                    # string Var, so the test is against "0", not 0.
                    r["progress_pct"] != "0",
                    rx.progress(value=r["progress_pct"].to(int), max=100, size="1",
                                color_scheme=ACCENT, width="100%"),
                    rx.fragment(),
                ),
                rx.text(r["progress_label"], size="1", class_name="tnum",
                        style={"color": "var(--steel)", "whiteSpace": "nowrap"}),
                spacing="1", align="start", width="100%",
            ),
        ),
    )


def header_cell(key: str, label: str, width: str = "auto") -> rx.Component:
    return rx.table.column_header_cell(
        rx.hstack(
            rx.text(label, size="1", weight="medium"),
            rx.cond(
                LedgerState.sort_key == key,
                rx.text(rx.cond(LedgerState.sort_desc, "▼", "▲"), size="1",
                        color_scheme=ACCENT),
                rx.fragment(),
            ),
            spacing="1", align="center",
        ),
        on_click=LedgerState.sort_by(key),
        width=["auto", "auto", "auto", width, width],
        style={"cursor": "pointer", "white_space": "nowrap"},
    )


def row(r: rx.Var) -> rx.Component:
    return rx.table.row(
        # Want-to-try, per person, and the same control every
        # other table uses. It was a hover card here, which a phone cannot open.
        rx.table.cell(
            V.control({p: r[f"verdict_{p}"] for p in V.PEOPLE},
                      lambda person, value: LedgerState.set_verdict(
                          r["id"], person, value)),
        ),
        rx.table.row_header_cell(
            rx.hstack(
                rx.text(r["name"], size="2"),
                rx.cond(
                    LedgerState.edit_mode,
                    rx.button("×", on_click=LedgerState.remove_title(r["name"]),
                              size="1", variant="ghost", color_scheme="red"),
                    rx.fragment(),
                ),
                spacing="1", align="center",
            ),
        ),
        rx.table.cell(
            rx.hstack(
                rx.box(class_name="hue", style={"background": r["medium_hue"],
                                                "minHeight": "0.9rem"}),
                rx.text(r["medium_label"], size="1", style={"color": "var(--steel)"}),
                spacing="2", align="center",
            ),
        ),
        rx.table.cell(
            rx.cond(
                LedgerState.edit_mode,
                rx.select(LedgerState.all_list_labels, value=r["lists"], size="1",
                          on_change=LedgerState.move_title(r["name"])),
                rx.text(r["lists"], size="1"),
            ),
        ),
        rx.table.cell(rx.text(r["genres"], size="1", color_scheme="gray")),
        progress_cell(r),
        rx.table.cell(rx.text(r["last_played"], size="1", color_scheme="gray")),
        rx.table.cell(
            rx.cond(
                LedgerState.edit_mode,
                rx.input(default_value=r["release_raw"], size="1", width="7.5rem",
                         placeholder="YYYY-MM-DD",
                         on_blur=LedgerState.set_release(r["name"]),
                         key=f"{r['name']}-release"),
                # only a future date earns space: the Year column already says
                # when everything else came out
                rx.cond(
                    r["unreleased"] != "",
                    rx.text(r["release_date"], size="1", class_name="tnum",
                            style={"color": "var(--mustard)", "whiteSpace": "nowrap"}),
                    rx.fragment(),
                ),
            ),
        ),
        rx.table.cell(
            rx.cond(
                LedgerState.edit_mode,
                rx.input(default_value=r["description_raw"], size="1", max_length=300,
                         placeholder="description (max 300)",
                         on_blur=LedgerState.set_description(r["name"]),
                         key=f"{r['name']}-desc"),
                rx.text(r["description"], size="1", color_scheme="gray",
                        class_name="lib-desc"),
            ),
            style={"min_width": "22rem", "max_width": "34rem",
                   "white_space": "normal", "vertical_align": "top"},
        ),
        IN.rating_cell(r["rating"], LedgerState.set_inline(r["id"], "rating"),
                       key=f"{r['id']}-rating"),
        IN.notes_cell(r["notes"], LedgerState.set_inline(r["id"], "notes"),
                      key=f"{r['id']}-notes"),
    )


def candidate(o: rx.Var, i: rx.Var) -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.text(o["head"], weight="bold", size="2"),
            rx.text(o["meta"], size="1", color_scheme="gray"),
            rx.text(o["overview"], size="1",
                    style={"white_space": "normal", "line_height": "1.5"}),
            rx.button("Use this", on_click=LedgerState.amb_pick(i), size="1",
                      color_scheme=ACCENT),
            spacing="2", align="start", width="100%",
        ),
        size="1",
    )


def ambiguity_queue() -> rx.Component:
    """Titles TMDB matched more than one way. One at a time, you decide."""
    return rx.cond(
        LedgerState.amb_count > 0,
        rx.box(
            rx.vstack(
                rx.hstack(
                    rx.heading("TMDB needs your pick", size="4"),
                    rx.badge(LedgerState.amb_position, color_scheme=ACCENT),
                    rx.spacer(),
                    rx.button("Skip", on_click=LedgerState.amb_skip, size="1",
                              variant="soft"),
                    rx.button("Leave blank", on_click=LedgerState.amb_leave_blank,
                              size="1", variant="outline"),
                    width="100%", align="center", spacing="2",
                ),
                rx.text(LedgerState.amb_name, weight="bold", size="3"),
                rx.text(LedgerState.amb_why, size="1", color_scheme="gray"),
                rx.grid(rx.foreach(LedgerState.amb_options, candidate),
                        columns="3", spacing="3", width="100%"),
                spacing="2", width="100%", align="start",
            ),
            style={"padding": "0.8rem", "border": "1px solid var(--accent-8)",
                   "border_radius": "6px"},
            width="100%",
        ),
        rx.fragment(),
    )


def _progress_chip(r: rx.Var) -> rx.Component:
    """One series you are mid-way through, and the one edit you actually make."""
    return rx.hstack(
        rx.box(class_name="hue", style={"background": r["hue"],
                                        "minHeight": "1.6rem"}),
        rx.vstack(
            rx.text(r["name"], size="2", style={"color": "var(--bone)",
                                                "whiteSpace": "nowrap"}),
            rx.hstack(
                rx.text(r["at"], size="1", class_name="tnum",
                        style={"color": "var(--mustard)"}),
                rx.text(r["of"], size="1", class_name="tnum",
                        style={"color": "var(--dim)"}),
                spacing="1",
            ),
            spacing="0", align="start",
        ),
        rx.button("+1", on_click=LedgerState.bump_episode(r["name"]), size="1",
                  variant="surface", title="watched another episode",
                  style={"margin": "0"}),
        spacing="2", align="center",
        style={"background": "var(--plate)", "border": "1px solid var(--rule)",
               "padding": "0.4rem 0.6rem 0.4rem 0", "flexShrink": "0"},
    )


def continue_watching() -> rx.Component:
    return rx.cond(
        LedgerState.in_progress,
        rx.vstack(
            rx.hstack(
                rx.text("Carry on with", size="2",
                        style={"fontFamily": "'Archivo Narrow', sans-serif",
                               "fontWeight": "700", "color": "var(--steel)"}),
                rx.text(LedgerState.in_progress_label, size="1", class_name="tnum",
                        style={"color": "var(--dim)"}),
                spacing="2", align="center",
            ),
            rx.box(
                rx.hstack(rx.foreach(LedgerState.in_progress, _progress_chip),
                          spacing="2", align="stretch"),
                width="100%",
                style={"overflowX": "auto", "paddingBottom": "0.35rem"},
            ),
            spacing="2", width="100%", align="start",
        ),
        rx.fragment(),
    )


def filters() -> rx.Component:
    return rx.vstack(
        rx.hstack(
            rx.input(placeholder="Search titles", value=LedgerState.search,
                     on_change=LedgerState.set_search, width="18rem"),
            rx.button("Clear", on_click=LedgerState.clear_filters, size="1",
                      variant="ghost", style={"color": "var(--steel)"}),
            chip(LedgerState.unreleased_label, LedgerState.only_unreleased,
                 LedgerState.toggle_unreleased, hue="#F2A93B"),
            rx.spacer(),
            rx.text(LedgerState.page_label, size="1", class_name="tnum",
                    style={"color": "var(--dim)"}),
            rx.button("Prev", on_click=LedgerState.prev_page, size="1", variant="surface",
                      disabled=LedgerState.page == 0),
            rx.button("Next", on_click=LedgerState.next_page, size="1", variant="surface",
                      disabled=LedgerState.page >= LedgerState.last_page),
            width="100%", align="center", spacing="3",
        ),
        rx.box(
            filter_row("medium", rx.foreach(
                LedgerState.medium_chips,
                lambda m: chip(m["label"], LedgerState.sel_media.contains(m["key"]),
                               LedgerState.toggle_medium(m["key"]), hue=m["hue"]))),
            filter_row("genre", rx.foreach(
                LedgerState.genre_shown,
                lambda g: chip(g, LedgerState.sel_genres.contains(g),
                               LedgerState.toggle_genre(g), dashed=True)),
                tail=rx.cond(
                    LedgerState.genre_more != "",
                    rx.button(LedgerState.genre_more,
                              on_click=LedgerState.toggle_genres_expanded, size="1",
                              variant="ghost",
                              style={"color": "var(--steel)", "whiteSpace": "nowrap"}),
                    rx.button("fewer", on_click=LedgerState.toggle_genres_expanded,
                              size="1", variant="ghost",
                              style={"color": "var(--steel)"}),
                )),
            filter_row("decade", rx.foreach(
                LedgerState.decade_names,
                lambda d: chip(d, LedgerState.sel_decades.contains(d),
                               LedgerState.toggle_decade(d)))),
            filter_row("list", rx.foreach(
                LedgerState.list_names,
                lambda l: chip(l, LedgerState.sel_lists.contains(l),
                               LedgerState.toggle_list(l)))),
            choice_row("watched", LedgerState.tried_filter, LedgerState.set_tried,
                       [("watched", "Watched"), ("watching", "Watching"),
                        ("unwatched", "Not started")]),
            V.unvoted_row(LedgerState),
            class_name="filter-stack",
        ),
        width="100%", spacing="3",
    )


def card(c: rx.Var) -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.hstack(
                rx.text(c["name"], weight="bold", size="2"),
                rx.spacer(),
                rx.text(c["count"], size="1", color_scheme="gray",
                        style={"font_variant_numeric": "tabular-nums"}),
                width="100%", align="center",
            ),
            rx.divider(),
            rx.text(c["body"], size="1", style={"white_space": "pre-line",
                                                "line_height": "1.7"}),
            rx.cond(
                c["paged"] != "",
                rx.hstack(
                    rx.button("‹", on_click=LedgerState.card_prev(c["key"]), size="1",
                              variant="outline", disabled=c["first"] != ""),
                    rx.spacer(),
                    rx.text(c["label"], size="1", color_scheme="gray",
                            style={"font_variant_numeric": "tabular-nums"}),
                    rx.spacer(),
                    rx.button("›", on_click=LedgerState.card_next(c["key"]), size="1",
                              variant="outline", disabled=c["last"] != ""),
                    width="100%", align="center",
                ),
                rx.fragment(),
            ),
            spacing="2", width="100%", align="start",
        ),
        size="1",
    )


def deck_section(name: str, cards: rx.Var, note: str) -> rx.Component:
    open_ = LedgerState.open_sections.contains(name)
    return rx.vstack(
        rx.hstack(
            rx.text(rx.cond(open_, "▾", "▸"), color_scheme=ACCENT, size="3"),
            rx.heading(name, size="4"),
            on_click=LedgerState.toggle_section(name),
            style={"cursor": "pointer", "user_select": "none"},
            align="center", spacing="2",
        ),
        rx.cond(
            open_,
            rx.vstack(
                rx.text(note, size="1", color_scheme="gray"),
                rx.grid(rx.foreach(cards, card), columns="3", spacing="3", width="100%"),
                spacing="2", width="100%",
            ),
            rx.fragment(),
        ),
        width="100%", spacing="2", align="start",
    )


def index() -> rx.Component:
    return rx.container(
        rx.vstack(
            navbar("/library"),
            continue_watching(),
            rx.hstack(
                rx.heading("Media Library Ledger", size="7"),
                rx.spacer(),
                rx.text(LedgerState.library_summary, size="1", class_name="tnum",
                        style={"color": "var(--dim)"}),
                width="100%", align="end",
            ),
            rx.hstack(
                rx.button(rx.cond(LedgerState.edit_mode, "Done", "Edit"),
                          on_click=LedgerState.toggle_edit, size="1",
                          variant=rx.cond(LedgerState.edit_mode, "solid", "surface")),
                rx.text("|", style={"color": "var(--rule)"}),
                rx.button("Preview TMDB", on_click=LedgerState.preview_tmdb,
                          size="1", variant="surface", loading=LedgerState.busy),
                rx.button("Sync from TMDB", on_click=LedgerState.sync_from_tmdb,
                          size="1", variant="surface", loading=LedgerState.busy),
                width="100%", align="center", spacing="2", wrap="wrap",
            ),
            notice_toast(LedgerState.notice),
            ambiguity_queue(),
            rx.divider(),
            filters(),
            rx.cond(
                LedgerState.edit_mode,
                rx.hstack(
                    rx.input(placeholder="New title…", value=LedgerState.new_title,
                             on_change=LedgerState.set_new_title, width="16rem"),
                    rx.select(LedgerState.all_list_labels, value=LedgerState.new_list,
                              placeholder="destination list",
                              on_change=LedgerState.set_new_list, size="1"),
                    rx.button("Add", on_click=LedgerState.add_title, size="1",
                              color_scheme=ACCENT),
                    spacing="2", align="center",
                    style={"padding": "0.6rem", "border": "1px dashed var(--accent-8)",
                           "border_radius": "4px"},
                ),
                rx.fragment(),
            ),
            rx.box(
                rx.table.root(
                    rx.table.header(rx.table.row(*[header_cell(k, l, w) for k, l, w in COLUMNS])),
                    rx.table.body(rx.foreach(LedgerState.page_rows, row)),
                    variant="surface", size="1",
                    # Radix tables are width:100%, so on a phone they compress to fit and the
                    # overflow_x wrapper never scrolls — the width comes out of the columns
                    # instead. A floor below 48em makes the wrapper scroll, which is the
                    # ordinary phone table. Tiers: initial, xs 30em, sm 48em, md, lg.
                    min_width=["34rem", "34rem", "auto", "auto", "auto"],
                ),
                width="100%", overflow_x="auto", class_name="lib-table",
            ),
            pager(LedgerState),
            rx.divider(),
            deck_section("Anime", LedgerState.deck_anime,
                         "Anime series."),
            deck_section("Movies", LedgerState.deck_movies,
                         "Films. Anime films also appear under the Anime filter above."),
            deck_section("TV Shows", LedgerState.deck_tv,
                         "Live-action and Western animation series."),
            rx.text("Descriptions, genres and years from TMDB. This product uses the "
                    "TMDB API but is not endorsed or certified by TMDB.",
                    size="1", color_scheme="gray"),
            spacing="4", width="100%",
        ),
        size="4", padding="1.5rem",
        on_mount=LedgerState.load,
    )


app = rx.App(stylesheets=["/ledger.css"],
             # head_components, not `scripts`: rx.App has no scripts argument in
             # 0.9. defer keeps it from blocking the first paint.
             head_components=[rx.el.script(src="/keys.js", defer=True)])
# Nightly backup inside the app process (container only; see nightly_loop).
app.register_lifespan_task(BKP.nightly_loop)


def themed_page(component, route, **kw):
    """add_page, with the room and page classes on it, and the setup gate as
    the first on_load: fresh names for the header, and /setup until done."""
    loads = kw.pop("on_load", [])
    loads = loads if isinstance(loads, list) else [loads]
    app.add_page(themed(component, route), route=route,
                 on_load=[ProfileState.gate(route), *loads], **kw)


themed_page(index, route="/library", title="Media Library Ledger",
            on_load=[LedgerState.load, LedgerState.load_ambiguous])
themed_page(R.index, route="/recipes", title="Recipes", on_load=RecipeState.load)
themed_page(R.detail, route="/recipes/[slug]", title="Recipe",
            on_load=[RecipeState.load, RecipeState.load_detail])
themed_page(R.planner, route="/meal-plan", title="Meal plan",
            on_load=[RecipeState.load, RecipeState.load_plan])
themed_page(D.page, route="/dates", title="Date Tracking", on_load=D.DateState.load)
themed_page(M.page, route="/music", title="Music", on_load=M.MusicState.load)
themed_page(C.page, route="/convo", title="Conversation",
            on_load=C.ConvoState.load)
themed_page(HH.page, route="/household", title="Household",
            on_load=[PL.PlantState.load, SH.ShopState.load,
                     G.GameState.load, T.TravelState.load])

# Four routes were folded into /household. They still resolve, because
# a phone has them bookmarked; the anchor lands on the right section.
for _old, _anchor in (("/plants", "plants"), ("/shops", "shops"),
                      ("/games", "games")):
    app.add_page(rx.fragment, route=_old, title="Household",
                 on_load=rx.redirect(f"/household#{_anchor}"))

# Travel lives on /dates now.
app.add_page(rx.fragment, route="/travel", title="Travel",
             on_load=rx.redirect("/dates#travel"))
themed_page(BK.page, route="/books", title="Books",
            on_load=BK.BookState.load)
themed_page(H.page, route="/", title="Tonight",
            on_load=[H.HomeState.load, H.GL.GalleryState.load])
themed_page(SU.setup_page, route="/setup", title="Setup", on_load=SU.SetupState.load)
themed_page(SU.settings_page, route="/settings", title="Settings",
            on_load=SU.SetupState.load)
