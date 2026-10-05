"""Checks for the people-as-ids migration (7a1c0e5d2b44).

Every vote must land on the right person, and a vote nobody can be matched to
must stop the migration before it changes anything. Each check builds its own
database at the previous revision, so they run in any order.

    ledger_app/.venv/bin/python tests/test_migration.py
"""
import os
import pathlib
import sqlite3
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import _db  # noqa: E402

DB = _db.DATA / "ledger.db"
BEFORE = "c9d77a53878c"


def fresh_at_before(votes=(), garments=()):
    DB.unlink(missing_ok=True)
    _db.migrate(BEFORE)
    con = sqlite3.connect(DB)
    for person, kind, row_id, value in votes:
        con.execute("insert into verdict (person, kind, row_id, value, updated_at) "
                    "values (?, ?, ?, ?, '2026-01-01 00:00:00')", (person, kind, row_id, value))
    for name, owner in garments:
        con.execute("insert into garment (name, owner, slot, season, formality, colour, "
                    "notes, placeholder, dismissed) "
                    "values (?, ?, 'top', '', 'casual', '', '', 0, 0)",
                    (name, owner))
    con.commit()
    con.close()


def rows(sql):
    con = sqlite3.connect(DB)
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


def test_votes_and_owners_land_on_the_right_person():
    os.environ["LEDGER_PEOPLE"] = "alex,sam"
    try:
        fresh_at_before(votes=[("alex", "title", 1, "up"), ("sam", "title", 1, "down")],
                        garments=[("Tee", "sam"), ("Scarf", "")])
        _db.migrate()
    finally:
        del os.environ["LEDGER_PEOPLE"]
    assert rows("select id, display_name from user order by id") == [(1, "Alex"), (2, "Sam")]
    assert rows("select user_id, value from verdict order by user_id") == [(1, "up"), (2, "down")]
    assert rows("select name, owner_id from garment order by name") == [("Scarf", None), ("Tee", 2)]
    assert rows("select setup_done from household") == [(1,)]


def test_default_names_without_env_still_map():
    """The old code voted as "me"/"you" when LEDGER_PEOPLE was unset."""
    fresh_at_before(votes=[("me", "game", 7, "up"), ("you", "game", 7, "mid")])
    _db.migrate()
    names = dict(rows("select id, display_name from user"))
    assert set(names.values()) == {"Me", "You"}
    by_name = {names[u]: v for u, v in rows("select user_id, value from verdict")}
    assert by_name == {"Me": "up", "You": "mid"}


def test_an_unknown_name_refuses_and_changes_nothing():
    os.environ["LEDGER_PEOPLE"] = "alex,sam"
    try:
        fresh_at_before(votes=[("alex", "title", 1, "up"), ("jo", "title", 1, "down")])
        try:
            _db.migrate()
        except RuntimeError as e:
            assert "jo" in str(e)
        else:
            raise AssertionError("migration accepted a vote from an unknown person")
    finally:
        del os.environ["LEDGER_PEOPLE"]
    assert rows("select version_num from alembic_version") == [(BEFORE,)]
    assert rows("select person from verdict order by person") == [("alex",), ("jo",)]
    assert not rows("select name from sqlite_master where name = 'household'")


def test_a_fresh_install_gets_two_empty_people_and_no_setup():
    DB.unlink(missing_ok=True)
    _db.migrate()
    assert rows("select id, display_name from user order by id") == [(1, ""), (2, "")]
    assert rows("select setup_done, home_lat, home_lon from household") == [(0, None, None)]


def test_home_location_carries_over_and_0_0_means_none():
    os.environ["LEDGER_HOME_LATLON"] = "48.2,16.37"
    try:
        fresh_at_before()
        _db.migrate()
    finally:
        del os.environ["LEDGER_HOME_LATLON"]
    assert rows("select home_lat, home_lon from household") == [(48.2, 16.37)]
    os.environ["LEDGER_HOME_LATLON"] = "0,0"
    try:
        fresh_at_before()
        _db.migrate()
    finally:
        del os.environ["LEDGER_HOME_LATLON"]
    assert rows("select home_lat, home_lon from household") == [(None, None)]


if __name__ == "__main__":
    for fn in (test_votes_and_owners_land_on_the_right_person,
               test_default_names_without_env_still_map,
               test_an_unknown_name_refuses_and_changes_nothing,
               test_a_fresh_install_gets_two_empty_people_and_no_setup,
               test_home_location_carries_over_and_0_0_means_none):
        fn()
        print(f"  ok  {fn.__name__}")
    print("migration checks passed")
