"""The place taxonomy, shared by the categoriser and the Date page.

Two levels on purpose. `TYPES` are what a place is tagged with; `GROUPS` bundle
them into the coarse things you actually have a mood for, so "adventure" selects
hike, gorge, cave and climb in one click without the tags themselves being that
vague. A place carries several types: a cafe that serves dinner is both.
"""
from __future__ import annotations

import re

# group -> the types inside it, in the order they should appear
GROUPS: dict[str, list[str]] = {
    "food & drink": ["restaurant", "cafe", "bar", "dessert"],
    "adventure":    ["hike", "gorge", "cave", "climb", "bike", "ski"],
    "water":        ["lake", "beach", "thermal", "pool"],
    "culture":      ["museum", "castle", "church", "theatre"],
    "outdoors":     ["park", "garden", "viewpoint", "zoo"],
    "play":         ["minigolf", "gokart", "bowling", "escape", "arcade"],
    "shopping":     ["shop", "vintage", "deli"],
    "trip":         ["city", "market"],
    "at home":      ["at-home"],
}
TYPES: list[str] = [t for ts in GROUPS.values() for t in ts]
GROUP_OF: dict[str, str] = {t: g for g, ts in GROUPS.items() for t in ts}

GROUP_HUE = {
    "food & drink": "#E2503F", "adventure": "#F2A93B", "water": "#3FB6A8",
    "culture": "#8A7DD8", "outdoors": "#6FBF73", "play": "#C43A6E",
    "trip": "#B9C6D8", "shopping": "#D98A3B", "at home": "#7C8CA8",
}


def type_hue(t: str) -> str:
    return GROUP_HUE.get(GROUP_OF.get(t, ""), "var(--rule)")


# Keyword patterns per type, English only. Add words in your own language to
# the pattern for each type. Ordered loosely most-specific first; every pattern
# that matches contributes a tag.
PATTERNS: dict[str, str] = {
    "restaurant": r"restaurant|pizzer|pizza|steak|grill|bistro|tavern|burger|sushi|ramen"
                  r"|kebab|bbq|brasserie|falafel|pho\b|diner|eatery|kitchen",
    "cafe":       r"caf[eé]\b|coffee|espresso|teahouse|tea house|bakery|brunch",
    "bar":        r"\bbar\b|\bpub\b|brewery|beer|wine|cocktail|distiller|whisk",
    "dessert":    r"gelat|ice cream|dessert|chocolat|waffle|pancake|patisserie|donut",
    "hike":       r"\bhike|hiking|\btrail|summit|\bpeak\b|\bmount\b|\bhut\b",
    "gorge":      r"gorge|canyon|ravine|waterfall|\bfalls\b",
    "cave":       r"\bcave|grotto|catacomb",
    "climb":      r"climb|via ferrata|boulder|zipline|flying fox|rope course|adventure park",
    "bike":       r"bike trail|mountain ?bike|\bmtb\b|cycling|bikepark|downhill",
    "ski":        r"\bski\b|skiing|snowboard|piste|toboggan|sled",
    "lake":       r"\blake\b|reservoir|\bpond\b",
    "beach":      r"beach|\blido\b|sandbank",
    "thermal":    r"thermal|spa\b|\bbath|wellness|sauna|hot spring",
    "pool":       r"aquapark|waterpark|swimming|pool\b|water slide",
    "museum":     r"museum|gallery|exhibit|planetarium|aquarium",
    "castle":     r"castle|palace|fortress|\bruin|manor|\bfort\b",
    "church":     r"church|cathedral|basilica|abbey|monastery|chapel|synagog|mosque|temple",
    "theatre":    r"theat|opera|philharmon|concert|live music|arena|stadium|cinema|circus",
    "park":       r"\bpark\b|national park|forest|woods\b|island",
    "garden":     r"garden|botanic|arboretum|greenhouse",
    "viewpoint":  r"viewpoint|view point|panorama|\btower\b|\bbridge\b|lookout|gondola"
                  r"|cable car|funicular",
    "zoo":        r"\bzoo\b|wildlife park|safari|aviary|terrarium",
    "minigolf":   r"minigolf|mini golf|adventure golf|\bgolf\b|disc golf",
    "gokart":     r"\bkart\b|karting|gokart|go-kart|motorsport|racetrack",
    "bowling":    r"bowling|billiard|\bdarts\b",
    "escape":     r"escape room|escape game|exit game|mystery room",
    "arcade":     r"arcade|\bvr\b|virtual reality|laser tag|lasertag|paintball|trampolin"
                  r"|playroom|pinball",
    "city":       r"\bdaytrip\b|day trip|old town|\bsquare\b|city centre|downtown",
    "market":     r"market|bazaar|christmas market",
    "shop":       r"\bshop\b|\bstore\b|boutique|flagship|\bcomics\b|bookshop|bookstore"
                  r"|\bhome\b|\bdesign\b|fashion|jewell|optician|florist",
    "vintage":    r"second.?hand|vintage|antiqu|retro|thrift|used books",
    "deli":       r"butcher|farm shop|\bcheese\b|\bdeli\b|greengrocer|spirits",
    "at-home":    r"boardgame|board game|videogame|video game|\bchess\b|\bcards\b|\bpuzzle"
                  r"|\bcook\b|\bbake\b|movie night|picnic|stargaz|\bread\b|library"
                  r"|\bcraft\b|\bpaint\b|\bdraw\b|\brun\b|\byoga\b",
}
COMPILED = {t: re.compile(p, re.I) for t, p in PATTERNS.items()}


def classify(*fields: str) -> list[str]:
    """Every type whose pattern appears in any of the given fields."""
    blob = " ".join(f for f in fields if f)
    return [t for t in TYPES if t in COMPILED and COMPILED[t].search(blob)]
