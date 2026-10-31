#!/usr/bin/env python3
"""Made-up demo data, to try the app or take screenshots without a real ledger.

Two invented people (Alex and Sam, living in Vienna), a few recipes, places on the
dates map, games and plants. Only into an empty ledger in its own data folder:

    export HEARTH_DATA_DIR=/tmp/hearth-demo
    (cd hearth && .venv/bin/python -m alembic upgrade head)
    hearth/.venv/bin/python scripts/seed/seed_demo.py

It refuses without HEARTH_DATA_DIR (the default is the real hearth.db) and
refuses a ledger that already has people, recipes or places.
"""
import os
import sys
from datetime import date, timedelta

if not os.environ.get("HEARTH_DATA_DIR"):
    sys.exit("set HEARTH_DATA_DIR to a folder of its own: demo data never goes into the real ledger")

from sqlmodel import Session, select  # noqa: E402

from hearth.core import household  # noqa: E402
from hearth.core.models import (  # noqa: E402
    ConvoQuestion, DateEntry, Game, Place, Plant, Recipe, RecipeIngredient, RecipeStep, User,
)
from hearth.core.state import ENGINE  # noqa: E402

VIENNA = (48.2082, 16.3738)

# (name, slug, minutes, servings, description, ingredients, steps)
RECIPES = [
    ("Shakshuka", "shakshuka", 35, 2, "Eggs poached in a spiced tomato and pepper sauce.",
     ["1 onion", "2 red peppers", "400 g chopped tomatoes", "4 eggs", "1 tsp cumin", "feta"],
     ["Soften the onion and peppers.", "Add cumin and tomatoes; simmer 10 minutes.",
      "Make four wells, crack in the eggs, cover until set.", "Crumble feta on top."]),
    ("Mushroom risotto", "mushroom-risotto", 45, 2, "Creamy arborio rice with mixed mushrooms.",
     ["250 g mushrooms", "160 g arborio rice", "1 l vegetable stock", "50 g parmesan", "1 shallot"],
     ["Brown the mushrooms; set aside.", "Toast the rice with the shallot.",
      "Add stock a ladle at a time, stirring, about 18 minutes.",
      "Stir in mushrooms and parmesan."]),
    ("Kaiserschmarrn", "kaiserschmarrn", 25, 2, "Torn, caramelised pancake with plum compote.",
     ["3 eggs", "150 ml milk", "100 g flour", "2 tbsp sugar", "butter", "plum compote"],
     ["Whisk yolks, milk and flour; fold in the beaten whites.",
      "Fry in butter, flip in pieces, tear with two forks.",
      "Caramelise with sugar; serve with the compote."]),
]

# (name, tags, lat, lon, visited, rating)
PLACES = [
    ("Café Sperl", "cafe", 48.1997, 16.3618, True, 9),
    ("Naschmarkt stalls", "market,restaurant", 48.1987, 16.3638, True, 8),
    ("Prater Hauptallee", "park", 48.2121, 16.4157, False, None),
    ("Albertina", "museum", 48.2048, 16.3683, False, None),
    ("Kahlenberg lookout", "viewpoint,hike", 48.2770, 16.3330, True, 10),
    ("Brunnenmarkt", "market,deli", 48.2116, 16.3381, False, None),
    ("Donauinsel", "park,lake", 48.2280, 16.4120, False, None),
    ("Burgkino", "theatre", 48.2033, 16.3664, True, 7),
]

# (text, audience, depth)
QUESTIONS = [
    ("What is a small thing I do that makes your day better?", "couples", "light"),
    ("Which trip would you take again tomorrow?", "couples", "light"),
    ("What did you believe at twenty that you no longer do?", "life", "deep"),
]

# (name, kind, players, remote_ok)
GAMES = [
    ("Codenames Duet", "board", "2", False),
    ("Decrypto", "party", "3-8", True),
    ("Exit: The Abandoned Cabin", "detective", "1-4", False),
]

# (name, species, room, water_days, last watered days ago)
PLANTS = [
    ("Monty", "Monstera deliciosa", "living room", 7, 3),
    ("Fern", "Nephrolepis exaltata", "bathroom", 3, 4),
    ("Olive", "Olea europaea", "balcony", 10, 2),
]


def main() -> None:
    with Session(ENGINE) as s:
        named = s.exec(select(User).where(User.display_name != "")).first()  # the two slots always exist
        if named or s.exec(select(Recipe)).first() or s.exec(select(Place)).first():
            sys.exit("this ledger is not empty: demo data only goes into a new one")
    household.set_names("Alex", "Sam")
    household.set_home(VIENNA)
    household.finish_setup()
    today = date.today()
    with Session(ENGINE) as s:
        for name, slug, minutes, servings, description, ingredients, steps in RECIPES:
            r = Recipe(name=name, slug=slug, total_minutes=minutes, servings=servings,
                       description=description)
            s.add(r)
            s.flush()
            s.add_all(RecipeIngredient(recipe_id=r.id, sort_order=i, line=line)
                      for i, line in enumerate(ingredients))
            s.add_all(RecipeStep(recipe_id=r.id, sort_order=i, text=text)
                      for i, text in enumerate(steps))
        for name, tags, lat, lon, visited, rating in PLACES:
            # a maps link: the Tonight picker only offers places you can navigate to
            maps_url = f"https://www.google.com/maps/search/?api=1&query={lat},{lon}"
            s.add(Place(name=name, tags=tags, lat=lat, lon=lon, city="Vienna", country="AT",
                        maps_url=maps_url, list_name="Want to go",
                        visited=visited, rating=rating, geo_source="manual", tag_source="manual"))
        s.flush()
        sperl = s.exec(select(Place).where(Place.name == "Café Sperl")).one()
        s.add(DateEntry(went_on=today - timedelta(days=12), place_id=sperl.id, rating=5,
                        note="Melange and the Sunday papers"))
        s.add_all(Game(name=n, kind=k, players=p, remote_ok=r) for n, k, p, r in GAMES)
        s.add_all(ConvoQuestion(ordinal=i, text=q, audience=a, depth=d)
                  for i, (q, a, d) in enumerate(QUESTIONS, 1))
        s.add_all(Plant(name=n, species=sp, room=room, water_days=every,
                        last_watered=today - timedelta(days=ago))
                  for n, sp, room, every, ago in PLANTS)
        s.commit()
    print(f"demo ledger ready in {os.environ['HEARTH_DATA_DIR']}")


if __name__ == "__main__":
    main()
