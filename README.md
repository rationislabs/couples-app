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

## Run it with Docker

You need Docker with Compose v2.24 or later and a free [Tailscale](https://tailscale.com) account.
Every phone or laptop that should open the app joins the same tailnet. The tailnet needs MagicDNS and HTTPS Certificates enabled
(Tailscale admin console > DNS), or the `https://couples.<tailnet>.ts.net` address cannot get a certificate.

```bash
mkdir couples && cd couples
# download compose.yml and .env.example from this repository into this folder
cp .env.example .env && chmod 600 .env
# paste a Tailscale auth key into TS_AUTHKEY (admin console > Settings > Keys; not ephemeral)
docker compose up -d
```

Open `https://couples.<your-tailnet>.ts.net`. The first visit asks for your two names and,
optionally, your home location. Change either later under Settings (the gear icon). Do not
set `PORT`: the frontend is built for port 3000 inside the container, and another value breaks
the websocket.

**Who is voting.** The two names in the header choose who this browser votes as. One tap
switches, so a shared phone works. There is no password: your tailnet is the login, and the
app cannot tell two people on one device apart.

**Updating.** `docker compose pull && docker compose up -d`. Every start backs up the
database first (`ledger-prestart-*.db.gz`, the last five kept), then migrates it.

**Rolling back.** Downgrades are not automatic. Set `COUPLES_VERSION` in `.env` to the
version you came from, then restore the pre-start backup taken just before the update.

**Backups.** Every night at `LEDGER_BACKUP_AT` (default 03:30, in `TZ`) the app writes a
verified, compressed copy of the database and mirrors your photos into the `backups` volume.
`LEDGER_BACKUP_AT` must be `HH:MM` with two-digit hours (e.g. `03:30`); anything else falls
back to 03:30 with a warning in the logs. The last 30 nightly copies are kept. If a backup
fails, or none has run for 48 hours, the header says so. Point the `backups` volume at a
second disk or a synced folder: a backup on the same disk as the data does not survive that
disk. If you bind-mount a host folder instead of the named volume, it must be writable by
uid 10001.

**Restoring.**

```bash
docker compose stop app
docker compose run --rm app restore /backups/ledger-<stamp>.db.gz
docker compose up -d
```

The current database is kept as `ledger.db.before-restore`, so a wrong pick can be undone.

**Optional integrations.** TMDB, Spotify and Last.fm keys go in `.env`; they never enter the
database or a backup. `compose.yml` passes only these names from `.env` to the app:
`TMDB_API_KEY`, `TMDB_READ_TOKEN`, `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`,
`SPOTIFY_REDIRECT_URI`, `SPOTIFY_REFRESH_TOKEN`, `LASTFM_API_KEY`, `TZ`, `LEDGER_BACKUP_AT`
and `LEDGER_BACKUP_KEEP` (`TS_AUTHKEY` goes only to the Tailscale sidecar). A new key added to
`.env` must also be listed in the app's `environment:` in `compose.yml`. Spotify's one-time
`scripts/data/spotify_sync.py --auth` opens a browser, so run it from a checkout of this
repository on a machine with one, then copy the `SPOTIFY_REFRESH_TOKEN` it writes into the
`.env` next to `compose.yml`.

**Security note.** The container's root filesystem stays writable because Reflex writes
`__pycache__/*.pyc` under `/app` and `/app/ledger_app/.web/backend/upload_is_used`; your data
is still only in the data and backups volumes.

## Setup

Needs Linux, Python 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
./setup.sh --home "48.8566,2.3522"     # your own lat,lon; see ./setup.sh --help
./ledger.sh start                      # prod build on 127.0.0.1:3000
```

`setup.sh` creates the venv, copies `.env.example` to `.env`, builds an empty
database and runs `scripts/ops/preflight.py`. Then edit `.env`:

- The two names and the home location: the first page asks for them, and Settings changes them later.
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

On a host install (./setup.sh), ./backup_db.sh writes a verified, compressed copy of ledger.db to backups/; in Docker the app does this itself (see "Run it with Docker"). It uses SQLite's online backup API. Never `cp` the database while the
app runs: under WAL the copy can miss the newest writes.

## Tests

No pytest. Each test file is a plain script, run from the repo root:

```bash
tests/run.sh
```

Run `tests/run.sh`: it runs every test on a fresh temporary database, so nothing
touches your real data.

## Schema changes

Alembic, through `reflex db makemigrations` and `reflex db migrate`. Keep
migrations additive, and run `./backup_db.sh` before migrating a database you
care about.

---

Descriptions, genres and years come from TMDB. This product uses the TMDB API
but is not endorsed or certified by TMDB.
