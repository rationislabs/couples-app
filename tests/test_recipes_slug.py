"""Checks for recipe slugs: one recipe per slug, always.

    ledger_app/.venv/bin/python tests/test_recipes_slug.py

Edit, delete and "cooked" look a recipe up by its slug. "Chili" and "Chili!"
shared the slug `chili`, so a click on one acted on the other, and importing a
page whose title slugified the same replaced another recipe's ingredients.
"""
import asyncio
import sqlite3

import _db  # first: never the real ledger.db

from sqlmodel import Session, select  # noqa: E402

DB = _db.DATA / "ledger.db"
BEFORE = "7a1c0e5d2b44"


def test_migration_renames_duplicates_then_enforces_uniqueness():
    DB.unlink(missing_ok=True)
    _db.migrate(BEFORE)
    con = sqlite3.connect(DB)
    for name in ("Chili", "Chili!", "chili  "):
        con.execute("insert into recipe (name, slug, source_url, description, notes, created_at) "
                    "values (?, 'chili', '', '', '', '2026-01-01 00:00:00')", (name,))
    con.commit()
    con.close()
    _db.migrate()
    con = sqlite3.connect(DB)
    assert [r[0] for r in con.execute("select slug from recipe order by id")] == \
        ["chili", "chili-2", "chili-3"]
    try:
        con.execute("insert into recipe (name, slug, source_url, description, notes, created_at) "
                    "values ('x', 'chili', '', '', '', '2026-01-01 00:00:00')")
    except sqlite3.IntegrityError:
        pass
    else:
        raise AssertionError("a second 'chili' slug was accepted")
    con.close()


def test_unique_slug_and_import_never_reuses_another_recipe():
    from ledger_app.core.models import Recipe
    from ledger_app.core.state import ENGINE
    from ledger_app.pages import recipes as R

    with Session(ENGINE) as s:
        assert R.unique_slug(s, "Chili") == "chili-4"     # chili..chili-3 exist
        assert R.unique_slug(s, "Soup") == "soup"

    R.scrape = lambda url: {"name": "Chili", "description": "", "ingredients": ["1 onion"],
                            "steps": ["cook"], "minutes": None, "servings": None,
                            "partial": ""}
    st = R.RecipeState(_reflex_internal_init=True)
    st.new_url = "https://example.com/other-chili"
    asyncio.run(R.RecipeState.import_url.fn(st))
    with Session(ENGINE) as s:
        rows = s.exec(select(Recipe).where(Recipe.source_url == "https://example.com/other-chili")).all()
        assert len(rows) == 1 and rows[0].slug == "chili-4", [(r.slug, r.name) for r in rows]
        first = s.exec(select(Recipe).where(Recipe.slug == "chili")).one()
        assert first.source_url == "", "the existing 'chili' was overwritten"

    # Importing the same page again updates that recipe instead of adding one.
    st.new_url = "https://example.com/other-chili"
    asyncio.run(R.RecipeState.import_url.fn(st))
    with Session(ENGINE) as s:
        assert len(s.exec(select(Recipe).where(
            Recipe.source_url == "https://example.com/other-chili")).all()) == 1


def test_a_slug_taken_meanwhile_gets_the_next_one():
    # Two saves of one name at once both picked the same free slug; the second commit hit
    # the unique index and the import died with busy still set.
    from ledger_app.core.models import Recipe
    from ledger_app.core.state import ENGINE
    from ledger_app.pages import recipes as R

    real, calls = R.unique_slug, []

    def racing(s, name):
        calls.append(name)
        return "chili" if len(calls) == 1 else real(s, name)  # "chili" was just taken

    R.scrape = lambda url: {"name": "Chili", "description": "", "ingredients": [],
                            "steps": [], "minutes": None, "servings": None, "partial": ""}
    st = R.RecipeState(_reflex_internal_init=True)
    R.unique_slug = racing
    try:
        st.new_url = "https://example.com/third-chili"
        asyncio.run(R.RecipeState.import_url.fn(st))
        calls.clear()
        st.new_name, st.new_url = "Stew", ""
        R.RecipeState.add_blank.fn(st)
    finally:
        R.unique_slug = real
    assert not st.busy
    with Session(ENGINE) as s:
        third = s.exec(select(Recipe).where(Recipe.source_url == "https://example.com/third-chili")).one()
        assert third.slug.startswith("chili-"), third.slug
        assert s.exec(select(Recipe).where(Recipe.name == "Stew")).one().slug == "stew"


def test_a_failed_save_never_leaves_the_import_button_locked():
    from ledger_app.pages import recipes as R

    real = R._commit_with_free_slug

    def locked(write):
        raise R.IntegrityError("insert", {}, Exception("database is locked"))

    R.scrape = lambda url: {"name": "Stew", "description": "", "ingredients": [],
                            "steps": [], "minutes": None, "servings": None, "partial": ""}
    st = R.RecipeState(_reflex_internal_init=True)
    st.new_url = "https://example.com/stew"
    R._commit_with_free_slug = locked
    try:
        asyncio.run(R.RecipeState.import_url.fn(st))
    finally:
        R._commit_with_free_slug = real
    assert not st.busy and "could not save" in st.notice, st.notice


if __name__ == "__main__":
    for fn in (test_migration_renames_duplicates_then_enforces_uniqueness,
               test_unique_slug_and_import_never_reuses_another_recipe,
               test_a_slug_taken_meanwhile_gets_the_next_one,
               test_a_failed_save_never_leaves_the_import_button_locked):
        fn()
        print(f"  ok  {fn.__name__}")
    print("recipe slug checks passed")
