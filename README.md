# Couples App

A self-hosted ledger for two people: what to watch, read, cook, play and talk
about, where to go, and what the plants need. Reflex over SQLite, one database
file, no accounts.

It ships empty. There is no sample data; everything you see is what you add.

## Pages

| Route | What it holds |
|---|---|
| `/` | Tonight: one place, one recipe, one question, one game and one show, dealt as cards, plus an outfit and a photo gallery |
| `/library` | Films, series and anime, with watch progress and optional TMDB descriptions |
| `/books` | Four shelves: want to buy, want to read, reading, read |
| `/recipes`, `/meal-plan` | Recipes with ingredients and steps, a cook log and a weekly plan |
| `/dates` | Places you want to go, a map, the log of dates you went on, and trips |
| `/music` | Spotify playlists mirrored locally, tagged by vibe via Last.fm |
| `/convo` | Conversation questions, one at a time, filtered by audience and depth |
| `/household` | Plants and watering, shops worth remembering, games |

Most tables carry a per-person want-to-try vote, a 1-10 rating and notes,
edited in place.

## Setup

Needs Linux, Python 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
./setup.sh --home "48.8566,2.3522"     # your own lat,lon; see ./setup.sh --help
./ledger.sh start                      # prod build on 127.0.0.1:3000
```

`setup.sh` creates the venv, copies `.env.example` to `.env`, builds an empty
database and runs `scripts/ops/preflight.py`. Then edit `.env`:

- `LEDGER_PEOPLE`: the two people voting, e.g. `alex,sam`
- `LEDGER_HOME_LATLON`: where distances are measured from
- API keys, only if you use the matching importers (TMDB, Spotify, Last.fm)

`./ledger.sh` also has `stop`, `restart`, `status`, `logs`, `check` (bind
address) and `watch` (rebuild on save).

## No login, by design

The app has no authentication. It binds to loopback only and is meant to be
reached over [Tailscale](https://tailscale.com/) with `tailscale serve`, so the
tailnet is the login. Do not put it on the open internet. `./ledger.sh check`
and `scripts/ops/preflight.py` verify the bind address, firewall and backups.

## Adding data

Everything can be typed into the app. For bulk loads:

| Script | Input |
|---|---|
| `scripts/import/import_places.py` | Google Takeout saved-list CSVs, or a pasted list of Maps links |
| `scripts/import/import_convo.py` | `csv/convo.csv`: `ordinal,text,audience,depth` |
| `scripts/data/spotify_sync.py` | your Spotify playlists (needs Spotify keys) |
| `scripts/data/tmdb_fill.py` | fills missing library descriptions from TMDB |
| `scripts/data/geocode_places.py`, `categorize_places.py` | coordinates and types for saved places |

Each script's docstring has its full usage. `csv/`, `json/` (API caches) and
`gallery/` are gitignored.

## Backups

`./backup_db.sh` writes a verified, compressed copy of `ledger.db` to
`backups/` using SQLite's online backup API. Never `cp` the database while the
app runs: under WAL the copy can miss the newest writes.

## Tests

No pytest. Each test file is a plain script, run from the repo root:

```bash
for f in tests/test_*.py; do ledger_app/.venv/bin/python "$f" || echo "FAIL $f"; done
bash tests/test_watch.sh
bash tests/test_setup.sh
```

The tests share the app's database. Each one creates its own rows and deletes
them by id afterwards.

## Schema changes

Alembic, through `reflex db makemigrations` and `reflex db migrate`. Keep
migrations additive, and run `./backup_db.sh` before migrating a database you
care about.

---

Descriptions, genres and years come from TMDB. This product uses the TMDB API
but is not endorsed or certified by TMDB.
