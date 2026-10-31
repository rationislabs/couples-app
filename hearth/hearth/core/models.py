"""Hearth schema.

One shared title catalogue; lists, progress and watch state hang off it. A single
user today, but the shape extends to several without a migration.

Plain SQLModel, not rx.Model: rx.Model is deprecated as of Reflex 0.9.2 and is
removed in 1.0.0. Foreign keys are plain int columns joined explicitly in queries,
so nothing here depends on undocumented relationship behaviour.
"""
from datetime import date, datetime
from typing import Optional

from sqlalchemy import Index
from sqlmodel import Field, SQLModel



class User(SQLModel, table=True):
    """One of the two people. Ids 1 and 2 are the app's two slots; the
    people-as-ids migration and /setup keep exactly those two rows."""
    id: Optional[int] = Field(default=None, primary_key=True)
    display_name: str = ""
    is_admin: bool = False


class Household(SQLModel, table=True):
    """The one row of settings that are not secrets. Secrets stay in .env so
    no backup ever carries one. Read and written only through core/household.py."""
    id: Optional[int] = Field(default=None, primary_key=True)
    home_lat: Optional[float] = None
    home_lon: Optional[float] = None
    setup_done: bool = False
    last_backup_at: Optional[datetime] = None
    last_backup_ok: Optional[bool] = None
    last_backup_error: str = ""


class Verdict(SQLModel, table=True):
    """One person's opinion of one row.

    Every other opinion in this schema — Place.visited, Shop.rating — is a
    single value that silently means "ours". A per-person want-to-try needs
    somewhere to put the person, and with one user row there was nowhere else.

    One table rather than a column per person per table, because the same
    question is wanted on the library, recipes, games and places. `kind` names the table the
    row lives in; there is no foreign key, deliberately, because a constraint
    per kind is five constraints that all say the same thing.

    `value` is up | mid | down. A missing row means no opinion, which is not
    the same as `mid` — "I could go either way" and "never asked" look
    identical in a two-state control, and distinguishing them is the point.
    """
    # One verdict per person per row.
    __table_args__ = (
        Index("ix_verdict_unique", "user_id", "kind", "row_id", unique=True),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)                 # 1 or 2, the two slots
    kind: str = Field(index=True)                   # title|idea|recipe|game|place
    row_id: int = Field(index=True)
    value: str = ""                                 # up|mid|down
    updated_at: datetime = Field(default_factory=datetime.now)


class Title(SQLModel, table=True):
    """A show, film or series. Deduplicated across every list it appears in."""
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    medium: str = Field(default="anime", index=True)   # anime|anime-film|movie|tv
    source: str = Field(default="manual", index=True)
    episodes: Optional[int] = None      # None = unknown; 0 from the API means unknown too
    seasons: Optional[int] = None
    year: Optional[int] = None
    release_date: Optional[date] = None
    """Full release date where TMDB has one. The year alone cannot answer "is
    this out yet", which is the question an unreleased title raises."""
    description: str = ""               # max 300 chars, enforced on write
    alt_title: str = ""                 # original-language title, when it differs
    rating: Optional[int] = Field(default=None, index=True)
    """1-10, or None for no opinion. Matches recipe, shop and book, which
    are all 1-10 INTEGER — one scale across the app."""
    notes: str = ""


class ListDef(SQLModel, table=True):
    """A named list, grouped on the page by `section`."""
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    kind: str = Field(default="media", index=True)
    section: str = ""        # "Anime" / "Movies" / "TV Shows"
    sort_order: int = 0
    owner_user_id: Optional[int] = Field(default=None, foreign_key="user.id", index=True)


class Membership(SQLModel, table=True):
    """Which list a title sits in. One row per (title, list)."""
    id: Optional[int] = Field(default=None, primary_key=True)
    title_id: int = Field(foreign_key="title.id", index=True)
    list_id: int = Field(foreign_key="listdef.id", index=True)


class Genre(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)


class TitleGenre(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    title_id: int = Field(foreign_key="title.id", index=True)
    genre_id: int = Field(foreign_key="genre.id", index=True)


class Progress(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    """Where a user stopped, as free text: "s5 ep 3"."""
    user_id: int = Field(foreign_key="user.id", index=True)
    title_id: int = Field(foreign_key="title.id", index=True)
    marker: str = ""
    updated_at: datetime = Field(default_factory=datetime.now)


class WatchState(SQLModel, table=True):
    """Per-user watch status, independent of list membership."""
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    title_id: int = Field(foreign_key="title.id", index=True)
    state: str = "unwatched"     # unwatched|watching|watched
    episodes_played: int = 0
    last_played: Optional[datetime] = None
    current_season: Optional[int] = None    # season of the most recent play
    current_episode: Optional[int] = None


# ---------------------------------------------------------------------------
# Recipes. Their own tag table on purpose, so library genres and recipe tags
# never share rows.
# ---------------------------------------------------------------------------
class Recipe(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    slug: str = Field(index=True, unique=True)  # the /recipes/<slug> route
    source_url: str = ""
    servings: Optional[int] = None
    total_minutes: Optional[int] = None      # shown as "3h 20m"
    rating: Optional[int] = None             # 1-5
    description: str = ""                    # what it is, from the source page
    notes: str = ""                          # your own remarks
    created_at: datetime = Field(default_factory=datetime.now)


class RecipeIngredient(SQLModel, table=True):
    """One line as typed, plus a best-effort split so the shopping list can add
    quantities up. `line` is authoritative; the parsed fields are a convenience
    and may be null."""
    id: Optional[int] = Field(default=None, primary_key=True)
    recipe_id: int = Field(foreign_key="recipe.id", index=True)
    sort_order: int = 0
    line: str = ""
    qty: Optional[float] = None
    unit: str = ""
    item: str = ""


class RecipeStep(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    recipe_id: int = Field(foreign_key="recipe.id", index=True)
    sort_order: int = 0
    text: str = ""


class RecipeTag(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)


class RecipeTagLink(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    recipe_id: int = Field(foreign_key="recipe.id", index=True)
    tag_id: int = Field(foreign_key="recipetag.id", index=True)


class CookLog(SQLModel, table=True):
    """One row per time you cooked it. Times cooked is a count, not a column, so
    it cannot drift out of step with the dates."""
    id: Optional[int] = Field(default=None, primary_key=True)
    recipe_id: int = Field(foreign_key="recipe.id", index=True)
    cooked_on: date = Field(default_factory=date.today, index=True)
    note: str = ""


class MealPlan(SQLModel, table=True):
    """One slot on one day. `recipe_id` null with text set covers "eat out"."""
    id: Optional[int] = Field(default=None, primary_key=True)
    day: date = Field(index=True)
    slot: str = Field(default="dinner", index=True)   # breakfast | lunch | dinner
    recipe_id: Optional[int] = Field(default=None, foreign_key="recipe.id", index=True)
    text: str = ""


# ---------------------------------------------------------------------------
# Date tracking: places you want to go, and the dates you actually went on.
# ---------------------------------------------------------------------------
class Place(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    list_name: str = Field(default="", index=True)   # the Google Maps list it came from
    country: str = Field(default="", index=True)     # ISO-2: US, FR, DE… blank for an
                                                     # idea with no place attached
    maps_url: str = ""
    note: str = ""
    source: str = "manual"                            # manual | maps
    tags: str = Field(default="", index=True)
    """What kind of place it is, comma separated: "restaurant,cafe". Multi-valued
    because a cafe that serves dinner is honestly both, and the mood picker takes
    several types at once."""
    tag_source: str = ""                              # auto | manual
    """`auto` came from categorize_places.py and the next run may overwrite it;
    `manual` means you fixed it by hand, so the script leaves it alone."""
    lat: Optional[float] = None
    lon: Optional[float] = None
    city: str = Field(default="", index=True)
    geo_source: str = ""
    """`nominatim` when geocode_places.py accepted a match, `manual` if you fixed
    it. Blank means the geocoder was offered a result and rejected it as not
    trustworthy — deliberately no coordinate rather than a wrong one."""
    visited: bool = Field(default=False, index=True)
    """Been there. Separate from the DateEntry log, which only covers dates you
    actually wrote down; this is the cheap toggle for everything before that."""
    dismissed: bool = Field(default=False, index=True)
    """Soft delete. A refresh is add-only and idempotent by name, so a hard
    delete would be undone by the next import. This is the tombstone that makes
    "remove" stick."""
    created_at: datetime = Field(default_factory=datetime.now)
    rating: Optional[int] = Field(default=None, index=True)
    """1-10, or None for no opinion. Same scale as every other table."""


class DateEntry(SQLModel, table=True):
    """A date you went on. `place_id` links to the wishlist when it came from
    there; `place_text` carries anywhere that was never on a list."""
    id: Optional[int] = Field(default=None, primary_key=True)
    went_on: date = Field(default_factory=date.today, index=True)
    place_id: Optional[int] = Field(default=None, foreign_key="place.id", index=True)
    place_text: str = ""
    with_whom: str = ""
    rating: Optional[int] = None      # 1-5
    note: str = ""


# ---------------------------------------------------------------------------
# Music. Playlists and their tracks, mirrored from Spotify.
# ---------------------------------------------------------------------------
class Playlist(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    spotify_id: str = Field(index=True)
    name: str = Field(index=True)
    description: str = ""
    owner: str = ""
    public: bool = False
    collaborative: bool = False
    total_tracks: int = 0
    snapshot_id: str = ""
    """Spotify's version marker for a playlist. Send it with a write and the
    change is rejected if the playlist moved underneath you."""
    dismissed: bool = Field(default=False, index=True)
    synced_at: Optional[datetime] = None


class Track(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    spotify_id: str = Field(index=True)
    name: str = Field(index=True)
    artists: str = ""                 # joined, as displayed
    album: str = ""
    year: Optional[int] = None
    duration_ms: int = 0
    genres: str = ""                  # empty: Spotify no longer serves genres to this app
    tags: str = ""
    """Last.fm tags, comma separated, strongest first. The only objective signal
    left once Spotify withdrew audio-features and artist genres."""
    tag_source: str = ""              # track | artist | none
    vibe: str = Field(default="", index=True)
    """Which of your own playlists this track most resembles, by tag profile."""
    vibe_score: Optional[float] = None
    added_at: Optional[datetime] = None


class PlaylistTrack(SQLModel, table=True):
    """Position matters: a playlist is ordered, and a track can repeat."""
    id: Optional[int] = Field(default=None, primary_key=True)
    playlist_id: int = Field(foreign_key="playlist.id", index=True)
    track_id: int = Field(foreign_key="track.id", index=True)
    position: int = 0


# ---------------------------------------------------------------------------
# Travel. Scaffolding: a trip is a name, a country and a date range. Linking a
# trip to rows in `place` needs a join table and a picker, which is a feature
# rather than a placeholder, so it is deliberately absent.
# ---------------------------------------------------------------------------
class Trip(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    country: str = Field(default="", index=True)   # ISO-2, as on Place
    start_on: Optional[date] = None
    end_on: Optional[date] = None
    notes: str = ""
    created_at: datetime = Field(default_factory=datetime.now)


# ---------------------------------------------------------------------------
# Conversation starters. Two filter axes on purpose: who you are asking
# (`audience`) and how exposed the answer makes them (`depth`). The source
# article's own sections split by the asker's gender, which filters nothing.
# ---------------------------------------------------------------------------
class ConvoQuestion(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    ordinal: Optional[int] = Field(default=None, index=True)
    text: str = Field(index=True)
    audience: str = Field(default="", index=True)
    """new-people | dating | couples | friends | life | love | self | funny
    | would-you-rather | never-have-i-ever | this-or-that"""
    depth: str = Field(default="", index=True)      # light | medium | deep
    asked: bool = Field(default=False, index=True)
    dismissed: bool = Field(default=False, index=True)
    """Soft delete: the importer rebuilds this
    table, so a hard delete would come back on the next run."""


# ---------------------------------------------------------------------------
# Games. Things you play together rather than places you go, so they live apart
# from Place: no country, no coordinates, and a URL instead of a map link.
# ---------------------------------------------------------------------------
class Game(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    url: str = ""
    kind: str = Field(default="", index=True)
    """board | detective | couples | party | video"""
    players: str = ""                 # free text: "2-6", "1-12"
    note: str = ""
    remote_ok: bool = Field(default=True, index=True)
    """Playable with one of you elsewhere. The reason these were collected."""
    spicy: bool = Field(default=False, index=True)
    """Kept out of the Tonight rotation unless asked for. That page is the one
    left open on the kitchen table."""
    played_count: int = 0
    last_played: Optional[date] = None
    dismissed: bool = Field(default=False, index=True)


# ---------------------------------------------------------------------------
# Plants. Unlike the other catalogues this one is about a recurring obligation,
# so the interesting column is not what you own but what is overdue.
# ---------------------------------------------------------------------------
    rating: Optional[int] = Field(default=None, index=True)
    """1-10, or None for no opinion. Matches recipe, shop and book, which
    are all 1-10 INTEGER — one scale across the app."""
class Plant(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    species: str = ""
    room: str = Field(default="", index=True)
    light_need: str = Field(default="", index=True)
    """bright direct | bright indirect | medium | low. Compared against the
    light the room actually gets, so a plant in the wrong place is visible
    rather than slowly dying in a corner."""
    water_days: Optional[int] = None
    """Days between waterings. Null means you have not worked it out yet, which
    is different from zero."""
    last_watered: Optional[date] = None
    watered_count: int = 0
    fed_days: Optional[int] = None          # feeding interval, if you feed it
    last_fed: Optional[date] = None
    notes: str = ""
    wishlist: bool = Field(default=False, index=True)
    """Wanted, not owned. Same row shape: a wishlist plant already carries the
    light and water it will need, so deciding where to put it is not a second
    research job after it arrives."""
    acquired_on: Optional[date] = None
    # A human override for what the derived status cannot see. plants._health()
    # reads thirst and light from facts already in the row; nothing derivable
    # knows what the leaves look like. "" means "use the derived one".
    health_override: str = ""
    health_note: str = ""
    dismissed: bool = Field(default=False, index=True)
    rating: Optional[int] = Field(default=None, index=True)
    """1-10, or None for no opinion. Same scale as every other table."""


class Garment(SQLModel, table=True):
    """One item of clothing, for the random outfit generator.

    There was no clothing data in this database at all, so this is the model
    the generator needs rather than a guess at one: a slot, so an outfit is one
    of each; a season and a formality, because those are what make a suggestion
    wrong; and `owner`, because two people get dressed.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    owner_id: Optional[int] = None                  # 1 or 2, or None for shared
    slot: str = Field(default="top", index=True)    # top|bottom|outer|shoes|accent
    season: str = ""                                # ""=any | warm | cold
    formality: str = ""                             # ""=any | casual | smart
    colour: str = ""
    notes: str = ""
    placeholder: bool = Field(default=False, index=True)
    """A stand-in, not a real garment. Kept separate so a wardrobe that has
    been filled in properly can have them removed in one query."""
    dismissed: bool = Field(default=False, index=True)


# ---------------------------------------------------------------------------
# Shops. A bookmark folder remembers the address; this remembers why the place
# was worth keeping, which is the part you forget between orders.
# ---------------------------------------------------------------------------
    rating: Optional[int] = Field(default=None, index=True)
    """1-10, or None for no opinion. Same scale as every other table."""
class Shop(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    url: str = ""
    kind: str = Field(default="", index=True)
    """clothing | homeware | furniture | plants | food | beauty | outdoor
    | tech | books | gifts | craft"""
    good_for: str = ""
    """What this shop is actually good at. The reason the row exists: "good
    linen, runs small" is worth more six months later than a five-star rating
    with no note attached."""
    rating: Optional[int] = None            # 1-5, your own
    price_band: str = Field(default="", index=True)   # budget | mid | premium
    ships_here: bool = Field(default=True, index=True)
    """Delivers to you without customs grief. Set false for the ones that
    look perfect until checkout."""
    country: str = ""                       # where it ships from, ISO-2 or free text
    notes: str = ""
    last_ordered: Optional[date] = None
    order_count: int = 0
    dismissed: bool = Field(default=False, index=True)


class Book(SQLModel, table=True):
    """A book on one of four shelves.

    One `shelf` column rather than an `owned` flag crossed with a `read` flag:
    "want to buy" and "read" are two points on the same journey and a book is
    only ever standing at one of them. The two-axis version (owned yes/no ×
    unread/reading/read) is more truthful about a book you own and have not
    opened, and can be added later without losing a row — `shelf` maps onto it.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    author: str = Field(default="", index=True)
    shelf: str = Field(default="want to buy", index=True)
    """want to buy | want to read | reading | read"""
    kind: str = Field(default="", index=True)
    """baking | cooking | drinks | art | fiction | reference"""
    rating: Optional[int] = None            # 1-5, and only once it is read
    notes: str = ""
    """Why this one. Same reasoning as Shop.good_for: the reason you wanted it
    is the part that evaporates, not the title."""
    url: str = ""
    added_on: date = Field(default_factory=date.today)
    finished_on: Optional[date] = None
    dismissed: bool = Field(default=False, index=True)
