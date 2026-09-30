"""Recipes: an index, a full recipe per page, and a week planner that generates
a shopping list.

Recipes live only in the database, so ./backup_db.sh is their only backup.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from html import unescape as html_unescape

import reflex as rx
from sqlmodel import Session, delete, select

from ..core.models import (CookLog, MealPlan, Recipe, RecipeIngredient, RecipeStep,
                     RecipeTag, RecipeTagLink)
from ..core.state import ENGINE
from ..core import inline as IN
from ..core import verdicts as V

PAGE_SIZE = 20


@dataclasses.dataclass
class PlanSlot:
    """Typed because rx.foreach cannot walk a nested plain dict."""
    iso: str
    slot: str
    label: str
    recipe: str
    text: str


@dataclasses.dataclass
class PlanDay:
    iso: str
    label: str
    today: str
    slots: list[PlanSlot]
SLOTS = ["breakfast", "lunch", "dinner"]
UNITS = {"g", "kg", "ml", "l", "tsp", "tbsp", "cup", "cups", "clove", "cloves",
         "can", "cans", "tin", "tins", "slice", "slices", "pinch", "bunch",
         "stick", "sticks", "piece", "pieces", "oz", "lb"}
FRACTIONS = {"½": 0.5, "⅓": 1 / 3, "⅔": 2 / 3, "¼": 0.25, "¾": 0.75, "⅛": 0.125}


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s or "recipe"


def fmt_minutes(m: int | None) -> str:
    if not m:
        return ""
    return f"{m // 60}h {m % 60:02d}m" if m >= 60 else f"{m}m"


def parse_line(line: str) -> tuple[float | None, str, str]:
    """Split "400 g chuck roast" into (400.0, "g", "chuck roast").

    Best effort only. `line` stays authoritative — this exists so the shopping
    list can add two recipes' 400g together, and it declines rather than guesses.
    """
    t = line.strip()
    for ch, val in FRACTIONS.items():
        t = t.replace(ch, f" {val} ")
    m = re.match(r"^\s*(\d+\s+\d+/\d+|\d+/\d+|\d*\.?\d+)\s*(.*)$", t)
    if not m:
        return None, "", line.strip()
    raw, rest = m.group(1), m.group(2).strip()
    try:
        if " " in raw:                       # "1 1/2"
            whole, frac = raw.split()
            n, d = frac.split("/")
            qty = float(whole) + float(n) / float(d)
        elif "/" in raw:
            n, d = raw.split("/")
            qty = float(n) / float(d)
        else:
            qty = float(raw)
    except (ValueError, ZeroDivisionError):
        return None, "", line.strip()
    unit = ""
    parts = rest.split()
    if parts and parts[0].lower().rstrip(".") in UNITS:
        unit = parts[0].lower().rstrip(".")
        parts = parts[1:]
    return qty, unit, " ".join(parts)


# ---- schema.org import ----------------------------------------------------
def iso_minutes(s: str) -> int | None:
    m = re.match(r"^P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?", s or "")
    if not m or not any(m.groups()):
        return None
    d, h, mi = (int(x or 0) for x in m.groups())
    return d * 1440 + h * 60 + mi or None


def _recipe_objects(node):
    """Walk any JSON-LD shape and yield every object typed Recipe."""
    if isinstance(node, list):
        for n in node:
            yield from _recipe_objects(n)
    elif isinstance(node, dict):
        t = node.get("@type") or ""
        types = t if isinstance(t, list) else [t]
        if "Recipe" in types:
            yield node
        for v in node.values():
            yield from _recipe_objects(v)


def _instructions(raw) -> list[str]:
    out: list[str] = []
    if isinstance(raw, str):
        out = [p.strip() for p in re.split(r"(?:\r?\n)+|(?<=[.!?])\s{2,}", raw)]
    elif isinstance(raw, list):
        for step in raw:
            if isinstance(step, str):
                out.append(step)
            elif isinstance(step, dict):
                if step.get("@type") == "HowToSection":
                    out += _instructions(step.get("itemListElement"))
                else:
                    out.append(step.get("text") or step.get("name") or "")
    return [re.sub(r"\s+", " ", s).strip() for s in out if s and s.strip()]


def _meta(html: str, *keys: str) -> str:
    for k in keys:
        m = re.search(
            r'<meta[^>]+(?:property|name)=["\']' + re.escape(k)
            + r'["\'][^>]+content=["\'](.*?)["\']', html, re.S | re.I)
        if not m:
            m = re.search(
                r'<meta[^>]+content=["\'](.*?)["\'][^>]+(?:property|name)=["\']'
                + re.escape(k) + r'["\']', html, re.S | re.I)
        if m:
            return re.sub(r"\s+", " ", html_unescape(m.group(1))).strip()
    return ""


def scrape(url: str) -> dict:
    """Pull a recipe out of a page's schema.org JSON-LD.

    Most recipe sites publish it because Google requires it for rich results.
    When a page has none, fall back to its title and meta description so the
    recipe can still be created with its link — an import that refuses outright
    loses the URL you just pasted, which is the one thing you cannot retype.
    """
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9"})
    with urllib.request.urlopen(req, timeout=25) as r:
        html = r.read().decode("utf-8", "replace")
    for block in re.findall(
            r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', html, re.S | re.I):
        try:
            data = json.loads(block.strip())
        except json.JSONDecodeError:
            continue
        for rec in _recipe_objects(data):
            ings = rec.get("recipeIngredient") or rec.get("ingredients") or []
            y = rec.get("recipeYield")
            y = y[0] if isinstance(y, list) and y else y
            ym = re.search(r"\d+", str(y or ""))
            desc = rec.get("description") or _meta(html, "og:description", "description")
            return {
                "name": (rec.get("name") or "").strip(),
                "description": re.sub(r"\s+", " ", str(desc)).strip()[:400],
                "ingredients": [str(i).strip() for i in ings if str(i).strip()],
                "steps": _instructions(rec.get("recipeInstructions")),
                "minutes": iso_minutes(rec.get("totalTime") or "")
                           or iso_minutes(rec.get("cookTime") or ""),
                "servings": int(ym.group()) if ym else None,
                "partial": "",
            }
    title = _meta(html, "og:title", "twitter:title")
    if not title:
        m = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
        title = re.sub(r"\s+", " ", html_unescape(m.group(1))).strip() if m else ""
    return {
        "name": title,
        "description": _meta(html, "og:description", "description")[:400],
        "ingredients": [], "steps": [], "minutes": None, "servings": None,
        "partial": "no schema.org recipe on that page — name and link saved, "
                   "ingredients and steps are yours to fill in",
    }


def shopping_from(s: Session, recipe_ids: list[int]) -> list[dict[str, str]]:
    """Merge several recipes' ingredients into one list.

    Two recipes each wanting 400 g flour produce one 800 g line. A line whose
    quantity did not parse is carried through verbatim rather than dropped —
    "salt to taste" belongs on the list even though it cannot be added up.
    """
    names = {r.id: r.name for r in s.exec(select(Recipe)).all()}
    summed: dict[tuple[str, str], float] = {}
    whose: dict[tuple[str, str], set[str]] = {}
    plain: dict[str, list[str]] = {}
    for rid in recipe_ids:
        for ing in s.exec(select(RecipeIngredient)
                          .where(RecipeIngredient.recipe_id == rid)).all():
            if ing.qty and ing.item:
                k = (ing.item.lower(), ing.unit)
                summed[k] = summed.get(k, 0) + ing.qty
                whose.setdefault(k, set()).add(names.get(rid, ""))
            else:
                plain.setdefault(ing.line, []).append(names.get(rid, ""))
    out = [{"what": " ".join(x for x in (f"{qty:g}", unit, item) if x),
            "for": ", ".join(sorted(whose[(item, unit)]))}
           for (item, unit), qty in sorted(summed.items())]
    out += [{"what": line, "for": ", ".join(sorted(set(rs)))}
            for line, rs in sorted(plain.items())]
    return out


# ---- state ----------------------------------------------------------------
class RecipeState(rx.State):
    _recipes: list[dict] = []
    _verdicts: dict[str, dict[str, str]] = {}
    search: str = ""
    sel_tags: list[str] = []
    unvoted: str = ""             # a person: only the recipes they have not voted on
    tried_filter: str = ""        # "" = all, "yes" = cooked at least once, "no" = never
    page: int = 0
    notice: str = ""
    busy: bool = False
    new_name: str = ""
    new_url: str = ""
    edit_mode: bool = False

    # detail page
    cur: dict[str, str] = {}
    cur_ingredients: list[str] = []
    cur_steps: list[str] = []
    draft_ingredients: str = ""
    draft_steps: str = ""
    editing: bool = False

    # planner
    week_offset: int = 0
    week_days: list[PlanDay] = []
    shopping: list[dict[str, str]] = []

    # ---- loading ----------------------------------------------------------
    @rx.event
    def load(self):
        with Session(ENGINE) as s:
            tags = {t.id: t.name for t in s.exec(select(RecipeTag)).all()}
            by_recipe: dict[int, list[str]] = {}
            for l in s.exec(select(RecipeTagLink)).all():
                if l.tag_id in tags:
                    by_recipe.setdefault(l.recipe_id, []).append(tags[l.tag_id])
            cooked: dict[int, list[dt.date]] = {}
            for c in s.exec(select(CookLog)).all():
                cooked.setdefault(c.recipe_id, []).append(c.cooked_on)
            rows = []
            for r in s.exec(select(Recipe)).all():
                dates = sorted(cooked.get(r.id, []))
                rows.append({
                    "name": r.name, "slug": r.slug, "url": r.source_url,
                    "tags": ", ".join(sorted(by_recipe.get(r.id, []))),
                    "tag_list": sorted(by_recipe.get(r.id, [])),
                    "cooked": len(dates),
                    "last_cooked": dates[-1].isoformat() if dates else "—",
                    "id": r.id, "rating": IN.shown(r.rating), "notes": r.notes or "",
                    # was a five-star string; "☆" * (5 - rating) renders empty once the
                    # scale goes past 5, so this is the number out of ten.
                    "time": fmt_minutes(r.total_minutes),
                    "servings": str(r.servings or ""),
                    "description": r.description or "",
                    "minutes_raw": str(r.total_minutes or ""),
                })
        self._recipes = sorted(rows, key=lambda x: x["name"].lower())
        self._read_verdicts()

    def _read_verdicts(self):
        self._verdicts = {str(k): v for k, v in
                          V.read("recipe", [r["id"] for r in self._recipes]).items()}

    @rx.event
    def load_detail(self):
        """Reads the `slug` var Reflex derives from the /recipes/[slug] route."""
        with Session(ENGINE) as s:
            r = s.exec(select(Recipe).where(Recipe.slug == self.slug)).first()
            if not r:
                self.cur, self.cur_ingredients, self.cur_steps = {}, [], []
                return
            ings = s.exec(select(RecipeIngredient)
                          .where(RecipeIngredient.recipe_id == r.id)).all()
            steps = s.exec(select(RecipeStep)
                           .where(RecipeStep.recipe_id == r.id)).all()
            n = len(s.exec(select(CookLog).where(CookLog.recipe_id == r.id)).all())
            tags = {t.id: t.name for t in s.exec(select(RecipeTag)).all()}
            mine = [tags[l.tag_id] for l in s.exec(select(RecipeTagLink)
                    .where(RecipeTagLink.recipe_id == r.id)).all() if l.tag_id in tags]
            self.cur = {
                "name": r.name, "slug": r.slug, "url": r.source_url,
                "time": fmt_minutes(r.total_minutes),
                "servings": str(r.servings or ""), "notes": r.notes,
                "id": r.id, "rating": IN.shown(r.rating),
                "description": r.description or "",
                "tags": ", ".join(sorted(mine)),
                # was a five-star string; "☆" * (5 - rating) renders empty once the
                    # scale goes past 5, so this is the number out of ten.
                    "stars": f"{r.rating}/10" if r.rating else "",
                "cooked": str(n),
            }
            self.cur_ingredients = [i.line for i in sorted(ings, key=lambda x: x.sort_order)]
            self.cur_steps = [x.text for x in sorted(steps, key=lambda x: x.sort_order)]
        self.draft_ingredients = "\n".join(self.cur_ingredients)
        self.draft_steps = "\n".join(self.cur_steps)
        self.editing = False

    # ---- derived ----------------------------------------------------------
    @rx.var
    def tag_names(self) -> list[str]:
        return sorted({t for r in self._recipes for t in r["tag_list"]})

    @rx.var
    def rows(self) -> list[dict]:
        q = self.search.strip().lower()
        out = [r for r in self._recipes
               if (not q or q in r["name"].lower() or q in r["tags"].lower())
               and (not self.sel_tags or set(self.sel_tags) <= set(r["tag_list"]))
               and (not self.tried_filter
                    or (r["cooked"] > 0) == (self.tried_filter == "yes"))]
        held = lambda r: self._verdicts.get(str(r["id"]), {})
        return [{**r, **{f"verdict_{p}": held(r).get(p, "") for p in V.PEOPLE}}
                for r in out if not self.unvoted or not held(r).get(self.unvoted)]

    @rx.var
    def page_rows(self) -> list[dict]:
        start = self.page * PAGE_SIZE
        return self.rows[start:start + PAGE_SIZE]

    @rx.var
    def last_page(self) -> int:
        return max(0, (len(self.rows) - 1) // PAGE_SIZE)

    @rx.var
    def page_label(self) -> str:
        n = len(self.rows)
        if not n:
            return "nothing yet"
        lo = self.page * PAGE_SIZE + 1
        return f"{lo}-{min(lo + PAGE_SIZE - 1, n)} of {n}"

    @rx.var
    def recipe_names(self) -> list[str]:
        return ["—"] + [r["name"] for r in self._recipes]

    # ---- mutations --------------------------------------------------------
    @rx.event
    def set_new_url(self, v: str):
        self.new_url = v

    @rx.event
    def set_new_name(self, v: str):
        self.new_name = v

    @rx.event
    def set_draft_ingredients(self, v: str):
        self.draft_ingredients = v

    @rx.event
    def set_draft_steps(self, v: str):
        self.draft_steps = v

    @rx.event
    def toggle_editing(self):
        self.editing = not self.editing

    @rx.event
    def toggle_edit(self):
        self.edit_mode = not self.edit_mode

    @rx.event
    def set_inline(self, row_id: int, field: str, value: str):
        """Rating or notes, on blur, from the list or the detail page."""
        msg = IN.save(Recipe, row_id, field, value)
        if msg:
            self.notice = msg
            if not msg.startswith("a rating is"):
                self.load()
                if self.cur:
                    self.load_detail()

    @rx.event
    def edit_recipe(self, slug: str, field: str, value: str):
        """Inline edit from the index, one handler per column."""
        v = value.strip()
        with Session(ENGINE) as s:
            r = s.exec(select(Recipe).where(Recipe.slug == slug)).first()
            if not r:
                return
            if field == "name":
                if not v:
                    self.notice = "a recipe needs a name"
                    return
                r.name = v[:120]
            elif field == "description":
                r.description = v[:400]
            elif field == "source_url":
                r.source_url = v
            elif field in ("total_minutes", "servings"):   # rating: set_inline
                if v and not v.isdigit():
                    self.notice = f"{v} is not a number"
                    return
                n = int(v) if v else None
                setattr(r, field, n)
            elif field == "tags":
                wanted = {t.strip() for t in v.split(",") if t.strip()}
                known = {t.name: t for t in s.exec(select(RecipeTag)).all()}
                s.exec(delete(RecipeTagLink).where(RecipeTagLink.recipe_id == r.id))
                for name in wanted:
                    if name not in known:
                        known[name] = RecipeTag(name=name)
                        s.add(known[name])
                        s.flush()
                    s.add(RecipeTagLink(recipe_id=r.id, tag_id=known[name].id))
            s.add(r)
            s.commit()
        self.load()
        self.notice = f"{field} = {v or '—'}"

    @rx.event
    def toggle_tag(self, t: str):
        self.sel_tags = ([x for x in self.sel_tags if x != t]
                         if t in self.sel_tags else self.sel_tags + [t])
        self.page = 0

    @rx.event
    def set_search(self, v: str):
        self.search, self.page = v, 0

    @rx.event
    def set_verdict(self, row_id: int, person: str, value: str):
        V.write("recipe", row_id, person, value)
        self._read_verdicts()
        self.page = min(self.page, self.last_page)

    @rx.event
    def set_unvoted(self, person: str):
        self.unvoted = "" if person == self.unvoted else person
        self.page = 0

    @rx.event
    def set_tried(self, v: str):
        self.tried_filter = "" if v == self.tried_filter else v
        self.page = 0

    @rx.event
    def next_page(self):
        self.page = min(self.page + 1, self.last_page)

    @rx.event
    def prev_page(self):
        self.page = max(0, self.page - 1)

    @rx.event
    def log_cooked(self, slug: str):
        with Session(ENGINE) as s:
            r = s.exec(select(Recipe).where(Recipe.slug == slug)).first()
            if r:
                s.add(CookLog(recipe_id=r.id))
                s.commit()
        self.load()
        self.notice = f"logged a cook of “{slug}”"

    @rx.event
    def delete_recipe(self, slug: str):
        with Session(ENGINE) as s:
            r = s.exec(select(Recipe).where(Recipe.slug == slug)).first()
            if not r:
                return
            for model, col in ((RecipeIngredient, RecipeIngredient.recipe_id),
                               (RecipeStep, RecipeStep.recipe_id),
                               (RecipeTagLink, RecipeTagLink.recipe_id),
                               (CookLog, CookLog.recipe_id),
                               (MealPlan, MealPlan.recipe_id)):
                s.exec(delete(model).where(col == r.id))
            s.delete(r)
            s.commit()
        self.load()
        self.notice = "deleted"

    @rx.event
    def add_blank(self):
        name = self.new_name.strip()
        if not name:
            return
        with Session(ENGINE) as s:
            if s.exec(select(Recipe).where(Recipe.name == name)).first():
                self.notice = f"“{name}” already exists"
                return
            s.add(Recipe(name=name, slug=slugify(name), source_url=self.new_url.strip()))
            s.commit()
        self.new_name = self.new_url = ""
        self.load()
        self.notice = f"added “{name}”"

    @rx.event(background=True)
    async def import_url(self):
        """Pull name, ingredients, steps and times out of a recipe page."""
        async with self:
            if self.busy or not self.new_url.strip():
                return
            self.busy, self.notice = True, "reading the page…"
            url = self.new_url.strip()
        try:
            got = scrape(url)
        except urllib.error.HTTPError as e:
            # 403 from Cloudflare-fronted sites is common; the link is still
            # worth keeping, so save it rather than losing what you pasted
            got = {"name": "", "description": "", "ingredients": [], "steps": [],
                   "minutes": None, "servings": None,
                   "partial": f"the site refused the request (HTTP {e.code}) — "
                              "link saved, paste the ingredients in yourself"}
        except Exception as e:
            async with self:
                self.busy, self.notice = False, f"could not reach that page: {e}"
            return
        name = (self.new_name.strip() or got["name"]
                or urllib.parse.urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]
                   .replace("-", " ").title() or url)[:120]
        with Session(ENGINE) as s:
            r = s.exec(select(Recipe).where(Recipe.slug == slugify(name))).first()
            if not r:
                r = Recipe(name=name, slug=slugify(name))
            r.source_url = url
            r.total_minutes = got["minutes"] or r.total_minutes
            r.servings = got["servings"] or r.servings
            r.description = got["description"] or r.description
            s.add(r)
            s.flush()
            if got["ingredients"]:
                s.exec(delete(RecipeIngredient).where(RecipeIngredient.recipe_id == r.id))
                s.exec(delete(RecipeStep).where(RecipeStep.recipe_id == r.id))
            for i, line in enumerate(got["ingredients"]):
                qty, unit, item = parse_line(line)
                s.add(RecipeIngredient(recipe_id=r.id, sort_order=i, line=line,
                                       qty=qty, unit=unit, item=item))
            for i, text in enumerate(got["steps"]):
                s.add(RecipeStep(recipe_id=r.id, sort_order=i, text=text))
            s.commit()
        async with self:
            self.busy, self.new_name, self.new_url = False, "", ""
            self.load()
            self.notice = got["partial"] or (
                f"imported “{name}” — {len(got['ingredients'])} ingredients, "
                f"{len(got['steps'])} steps")

    @rx.event
    def save_detail(self):
        """One textarea per section, one line per row. Simpler than per-row
        widgets and it round-trips exactly what you see."""
        with Session(ENGINE) as s:
            r = s.exec(select(Recipe).where(Recipe.slug == self.slug)).first()
            if not r:
                return
            s.exec(delete(RecipeIngredient).where(RecipeIngredient.recipe_id == r.id))
            s.exec(delete(RecipeStep).where(RecipeStep.recipe_id == r.id))
            for i, line in enumerate(x.strip() for x in self.draft_ingredients.splitlines()):
                if line:
                    qty, unit, item = parse_line(line)
                    s.add(RecipeIngredient(recipe_id=r.id, sort_order=i, line=line,
                                           qty=qty, unit=unit, item=item))
            for i, text in enumerate(x.strip() for x in self.draft_steps.splitlines()):
                if text:
                    s.add(RecipeStep(recipe_id=r.id, sort_order=i, text=text))
            s.commit()
        self.load_detail()
        self.notice = "saved"

    @rx.event
    def set_description(self, value: str):
        with Session(ENGINE) as s:
            r = s.exec(select(Recipe).where(Recipe.slug == self.slug)).first()
            if r:
                r.description = value.strip()[:400]
                s.add(r)
                s.commit()
        self.load()
        self.load_detail()

    @rx.event
    def set_tags(self, value: str):
        """Comma-separated, replacing whatever was there."""
        wanted = {t.strip() for t in value.split(",") if t.strip()}
        with Session(ENGINE) as s:
            r = s.exec(select(Recipe).where(Recipe.slug == self.slug)).first()
            if not r:
                return
            known = {t.name: t for t in s.exec(select(RecipeTag)).all()}
            s.exec(delete(RecipeTagLink).where(RecipeTagLink.recipe_id == r.id))
            for name in wanted:
                if name not in known:
                    known[name] = RecipeTag(name=name)
                    s.add(known[name])
                    s.flush()
                s.add(RecipeTagLink(recipe_id=r.id, tag_id=known[name].id))
            s.commit()
        self.load()
        self.load_detail()

    # ---- planner ----------------------------------------------------------
    @rx.var
    def week_label(self) -> str:
        m = self._monday()
        return f"{m.strftime('%d %b')} — {(m + dt.timedelta(days=6)).strftime('%d %b %Y')}"

    def _monday(self) -> dt.date:
        today = dt.date.today()
        return today - dt.timedelta(days=today.weekday()) + dt.timedelta(weeks=self.week_offset)

    @rx.event
    def load_plan(self):
        """Plan and shopping list are loaded, not computed.

        As @rx.var they only recomputed when `week_offset` changed, so a written
        plan row never reached the page — the classic stale-computed-var trap for
        a var whose real input is the database.
        """
        m = self._monday()
        week = [m + dt.timedelta(days=i) for i in range(7)]
        with Session(ENGINE) as s:
            names = {r.id: r.name for r in s.exec(select(Recipe)).all()}
            plans = {(p.day, p.slot): p for p in s.exec(select(MealPlan)).all()}
            days = []
            for d in week:
                slots = [PlanSlot(iso=d.isoformat(), slot=slot, label=slot,
                                  recipe=(names.get(plans[(d, slot)].recipe_id, "—")
                                          if (d, slot) in plans else "—"),
                                  text=(plans[(d, slot)].text if (d, slot) in plans else ""))
                         for slot in SLOTS]
                days.append(PlanDay(iso=d.isoformat(), label=d.strftime("%a %d %b"),
                                    today="yes" if d == dt.date.today() else "",
                                    slots=slots))
            ids = [p.recipe_id for (day, _slot), p in plans.items()
                   if day in week and p.recipe_id]
            self.week_days = days
            self.shopping = shopping_from(s, ids) if ids else []

    @rx.event
    def shift_week(self, by: int):
        self.week_offset += by
        self.load_plan()

    def _slot_row(self, s, day: dt.date, slot: str) -> MealPlan:
        row = s.exec(select(MealPlan).where(MealPlan.day == day)
                     .where(MealPlan.slot == slot)).first()
        return row or MealPlan(day=day, slot=slot)

    @rx.event
    def plan_recipe(self, iso: str, slot: str, name: str):
        day = dt.date.fromisoformat(iso)
        with Session(ENGINE) as s:
            r = s.exec(select(Recipe).where(Recipe.name == name)).first()
            p = self._slot_row(s, day, slot)
            p.recipe_id = r.id if r else None
            if not p.recipe_id and not p.text:
                if p.id:
                    s.delete(p)          # an empty slot is no row at all
                s.commit()
                self.load_plan()
                return
            s.add(p)
            s.commit()
        self.load_plan()

    @rx.event
    def plan_note(self, iso: str, slot: str, text: str):
        day = dt.date.fromisoformat(iso)
        with Session(ENGINE) as s:
            p = self._slot_row(s, day, slot)
            p.text = text.strip()
            if not p.recipe_id and not p.text:
                if p.id:
                    s.delete(p)
                s.commit()
                self.load_plan()
                return
            s.add(p)
            s.commit()
        self.load_plan()


# ---- pages ----------------------------------------------------------------
def _subnav(active: str) -> rx.Component:
    from ..core.ui import ACCENT
    def link(label: str, href: str) -> rx.Component:
        on = href == active
        return rx.link(label, href=href, size="1", underline="none",
                       weight="bold" if on else "regular",
                       color_scheme=ACCENT if on else "gray")
    return rx.hstack(link("All recipes", "/recipes"), rx.text("·", color_scheme="gray"),
                     link("Meal plan", "/meal-plan"), spacing="2", align="center")


def _row(r: rx.Var) -> rx.Component:
    from ..core.ui import ACCENT
    return rx.table.row(
        rx.table.cell(V.control({p: r[f"verdict_{p}"] for p in V.PEOPLE},
                                lambda person, value: RecipeState.set_verdict(
                                    r["id"], person, value))),
        rx.table.row_header_cell(
            rx.cond(
                RecipeState.edit_mode,
                rx.input(default_value=r["name"], size="1", width="100%",
                         on_blur=RecipeState.edit_recipe(r["slug"], "name"),
                         key=f"{r['slug']}-name"),
                rx.link(r["name"], href=f"/recipes/{r['slug']}", size="2",
                        underline="hover"),
            ),
        ),
        rx.table.cell(
            rx.cond(
                RecipeState.edit_mode,
                rx.input(default_value=r["tags"], size="1", width="100%",
                         placeholder="comma separated",
                         on_blur=RecipeState.edit_recipe(r["slug"], "tags"),
                         key=f"{r['slug']}-tags"),
                rx.text(r["tags"], size="1", style={"color": "var(--dim)"}),
            ),
        ),
        rx.table.cell(
            rx.cond(
                RecipeState.edit_mode,
                rx.input(default_value=r["minutes_raw"], size="1", width="4.5rem",
                         type="number", placeholder="min",
                         on_blur=RecipeState.edit_recipe(r["slug"], "total_minutes"),
                         key=f"{r['slug']}-total_minutes"),
                rx.text(r["time"], size="1"),
            ),
        ),
        rx.table.cell(rx.text(r["cooked"], size="1",
                              style={"font_variant_numeric": "tabular-nums"})),
        rx.table.cell(rx.text(r["last_cooked"], size="1", color_scheme="gray")),
        # Editable in place, the same shape shops.py uses. The detail page had the only input, which is not
        # where the other tables put theirs.
        IN.rating_cell(r["rating"], RecipeState.set_inline(r["id"], "rating"),
                       key=f"{r['slug']}-rating"),
        IN.notes_cell(r["notes"], RecipeState.set_inline(r["id"], "notes"),
                      key=f"{r['slug']}-notes"),
        rx.table.cell(
            rx.cond(
                RecipeState.edit_mode,
                rx.input(default_value=r["description"], size="1", width="100%",
                         on_blur=RecipeState.edit_recipe(r["slug"], "description"),
                         key=f"{r['slug']}-description"),
                rx.text(r["description"], class_name="prose",
                        style={"fontSize": "0.85rem"}),
            ),
        ),
        rx.table.cell(
            rx.hstack(
                rx.button("Cooked it", on_click=RecipeState.log_cooked(r["slug"]),
                          size="1", variant="soft"),
                rx.cond(r["url"] != "",
                        rx.link("source ↗", href=r["url"], size="1", is_external=True),
                        rx.fragment()),
                spacing="2", align="center",
            ),
        ),
    )


def index() -> rx.Component:
    from ..core.ui import ACCENT, chip, choice_row, navbar, pager
    return rx.container(
        rx.vstack(
            navbar("/recipes"),
            rx.hstack(rx.heading("Recipes", size="7"), rx.spacer(), _subnav("/recipes"),
                      width="100%", align="end"),
            rx.hstack(
                rx.input(placeholder="Recipe URL — imports ingredients and steps",
                         value=RecipeState.new_url,
                         on_change=RecipeState.set_new_url, width="24rem"),
                rx.input(placeholder="name (optional)", value=RecipeState.new_name,
                         on_change=RecipeState.set_new_name, width="12rem"),
                rx.button("Import", on_click=RecipeState.import_url, size="1",
                          color_scheme=ACCENT, loading=RecipeState.busy),
                rx.button("Add empty", on_click=RecipeState.add_blank, size="1",
                          variant="outline"),
                rx.button(rx.cond(RecipeState.edit_mode, "Done", "Edit"),
                          on_click=RecipeState.toggle_edit, size="1",
                          variant=rx.cond(RecipeState.edit_mode, "solid", "surface")),
                spacing="2", align="center", wrap="wrap", width="100%",
            ),
            rx.text(RecipeState.notice, size="1", color_scheme="gray"),
            rx.divider(),
            rx.hstack(
                rx.input(placeholder="Search…", value=RecipeState.search,
                         on_change=RecipeState.set_search, width="16rem"),
                rx.spacer(),
                rx.text(RecipeState.page_label, size="1", color_scheme="gray"),
                rx.button("Prev", on_click=RecipeState.prev_page, size="1", variant="outline",
                          disabled=RecipeState.page == 0),
                rx.button("Next", on_click=RecipeState.next_page, size="1", variant="outline",
                          disabled=RecipeState.page >= RecipeState.last_page),
                width="100%", align="center",
            ),
            choice_row("cooked", RecipeState.tried_filter, RecipeState.set_tried,
                       [("yes", "Cooked"), ("no", "Not yet")]),
            V.unvoted_row(RecipeState),
            rx.hstack(
                rx.foreach(RecipeState.tag_names,
                           lambda t: chip(t, RecipeState.sel_tags.contains(t),
                                          RecipeState.toggle_tag(t))),
                wrap="wrap", spacing="1",
            ),
            rx.box(
                rx.table.root(
                    rx.table.header(rx.table.row(*[
                        rx.table.column_header_cell(x) for x in
                        ("Us", "Name", "Tags", "Time", "Cooked", "Last", "Rating", "Notes",
                         "Description", "")])),
                    rx.table.body(rx.foreach(RecipeState.page_rows, _row)),
                    variant="surface", size="1",
                    # Radix tables are width:100%, so on a phone they compress to fit and the
                    # overflow_x wrapper never scrolls — the width comes out of the columns
                    # instead. A floor below 48em makes the wrapper scroll, which is the
                    # ordinary phone table. Tiers: initial, xs 30em, sm 48em, md, lg.
                    min_width=["34rem", "34rem", "auto", "auto", "auto"],
                ),
                width="100%", overflow_x="auto",
            ),
            pager(RecipeState),
            spacing="4", width="100%",
        ),
        size="4", padding="1.5rem",
    )


def detail() -> rx.Component:
    from ..core.ui import ACCENT, navbar
    return rx.container(
        rx.vstack(
            navbar("/recipes"),
            rx.cond(
                RecipeState.cur,
                rx.vstack(
                    rx.hstack(
                        rx.link("‹ Recipes", href="/recipes", size="1"),
                        rx.spacer(), _subnav(""),
                        width="100%", align="center",
                    ),
                    rx.heading(RecipeState.cur["name"], size="7"),
                    rx.hstack(
                        rx.text(f"{RecipeState.cur['servings']} servings", size="1"),
                        rx.text("·", color_scheme="gray"),
                        rx.text(RecipeState.cur["time"], size="1"),
                        rx.text("·", color_scheme="gray"),
                        rx.text(RecipeState.cur["stars"], size="1", color_scheme=ACCENT),
                        rx.text("·", color_scheme="gray"),
                        rx.text(f"cooked {RecipeState.cur['cooked']}x", size="1"),
                        rx.spacer(),
                        rx.button("Cooked it",
                                  on_click=RecipeState.log_cooked(RecipeState.cur["slug"]),
                                  size="1", variant="soft"),
                        rx.button(rx.cond(RecipeState.editing, "Done", "Edit"),
                                  on_click=RecipeState.toggle_editing,
                                  size="1", variant="outline"),
                        width="100%", align="center", spacing="2", wrap="wrap",
                    ),
                    rx.hstack(
                        # Was five rx.foreach buttons. foreach hands the lambda a
                        # Var, not a Python int, so rate() received a Var and no
                        # rating ever persisted — 0 of 6 recipes were rated. This
                        # is the same input shops.py uses, and the scale is 1-10
                        # to match it.
                        rx.input(default_value=RecipeState.cur["rating"],
                                 size="1", width="4rem", type="number",
                                 min=1, max=10, placeholder="1-10",
                                 key=RecipeState.cur["slug"],
                                 on_blur=RecipeState.set_inline(
                                     RecipeState.cur["id"], "rating")),
                        rx.text("rate 1-10", size="1", color_scheme="gray"),
                        rx.spacer(),
                        rx.cond(RecipeState.cur["url"] != "",
                                rx.link("source ↗", href=RecipeState.cur["url"],
                                        size="1", is_external=True),
                                rx.fragment()),
                        width="100%", align="center", spacing="1",
                    ),
                    rx.hstack(
                        rx.input(placeholder="tags, comma separated",
                                 default_value=RecipeState.cur["tags"], size="1",
                                 on_blur=RecipeState.set_tags, width="20rem"),
                        align="center",
                    ),
                    rx.cond(
                        RecipeState.editing,
                        rx.text_area(placeholder="what this is",
                                     default_value=RecipeState.cur["description"],
                                     on_blur=RecipeState.set_description, rows="3",
                                     width="100%"),
                        rx.cond(
                            RecipeState.cur["description"] != "",
                            rx.text(RecipeState.cur["description"], class_name="prose"),
                            rx.fragment(),
                        ),
                    ),
                    rx.divider(),
                    rx.cond(
                        RecipeState.editing,
                        rx.grid(
                            rx.vstack(
                                rx.text("Ingredients — one per line", size="1",
                                        color_scheme="gray"),
                                rx.text_area(value=RecipeState.draft_ingredients,
                                             on_change=RecipeState.set_draft_ingredients,
                                             rows="16", width="100%"),
                                width="100%", spacing="1",
                            ),
                            rx.vstack(
                                rx.text("Steps — one per line", size="1",
                                        color_scheme="gray"),
                                rx.text_area(value=RecipeState.draft_steps,
                                             on_change=RecipeState.set_draft_steps,
                                             rows="16", width="100%"),
                                width="100%", spacing="1",
                            ),
                            columns="2", spacing="4", width="100%",
                        ),
                        rx.grid(
                            rx.vstack(
                                rx.heading("Ingredients", size="4"),
                                rx.foreach(RecipeState.cur_ingredients,
                                           lambda i: rx.text(i, size="2")),
                                spacing="1", align="start",
                            ),
                            rx.vstack(
                                rx.heading("Steps", size="4"),
                                rx.foreach(RecipeState.cur_steps, lambda s, i: rx.text(
                                    f"{i + 1}. {s}", size="2",
                                    style={"line_height": "1.6"})),
                                spacing="2", align="start",
                            ),
                            columns="2", spacing="6", width="100%",
                        ),
                    ),
                    rx.cond(
                        RecipeState.editing,
                        rx.button("Save", on_click=RecipeState.save_detail, size="1",
                                  color_scheme=ACCENT),
                        rx.fragment(),
                    ),
                    rx.text(RecipeState.notice, size="1", color_scheme="gray"),
                    spacing="3", width="100%", align="start",
                ),
                rx.vstack(
                    rx.heading("Not found", size="6"),
                    rx.link("‹ back to recipes", href="/recipes", size="2"),
                    spacing="2",
                ),
            ),
            spacing="4", width="100%",
        ),
        size="4", padding="1.5rem",
    )


def _plan_slot(s: rx.Var) -> rx.Component:
    return rx.hstack(
        rx.text(s.label, size="1", style={"color": "var(--dim)", "minWidth": "5rem",
                                          "flex": "0 0 5rem"}),
        rx.select(RecipeState.recipe_names, value=s.recipe, size="1", width="17rem",
                  on_change=lambda v: RecipeState.plan_recipe(s.iso, s.slot, v)),
        rx.input(placeholder="or a note — eating out, leftovers", default_value=s.text,
                 size="1", width="18rem",
                 on_blur=lambda v: RecipeState.plan_note(s.iso, s.slot, v)),
        width="100%", align="center", spacing="2",
    )


def _plan_day(d: rx.Var) -> rx.Component:
    from ..core.ui import ACCENT
    return rx.box(
        rx.vstack(
            rx.text(d.label, size="2",
                    weight=rx.cond(d.today != "", "bold", "medium"),
                    style={"color": rx.cond(d.today != "", "var(--mustard)",
                                            "var(--bone)")}),
            rx.foreach(d.slots, _plan_slot),
            spacing="1", width="100%", align="start",
        ),
        class_name="block", width="100%",
    )


def planner() -> rx.Component:
    from ..core.ui import ACCENT, navbar
    return rx.container(
        rx.vstack(
            navbar("/recipes"),
            rx.hstack(rx.heading("Meal plan", size="7"), rx.spacer(),
                      _subnav("/meal-plan"), width="100%", align="end"),
            rx.hstack(
                rx.button("‹", on_click=RecipeState.shift_week(-1), size="1",
                          variant="outline"),
                rx.text(RecipeState.week_label, size="2", weight="medium"),
                rx.button("›", on_click=RecipeState.shift_week(1), size="1",
                          variant="outline"),
                rx.button("This week", on_click=RecipeState.shift_week(0), size="1",
                          variant="ghost"),
                spacing="2", align="center",
            ),
            rx.vstack(rx.foreach(RecipeState.week_days, _plan_day),
                      width="100%", spacing="2"),
            rx.divider(),
            rx.heading("Shopping list", size="4"),
            rx.cond(
                RecipeState.shopping,
                rx.vstack(
                    rx.foreach(RecipeState.shopping, lambda i: rx.hstack(
                        rx.text("☐", color_scheme="gray"),
                        rx.text(i["what"], size="2"),
                        rx.spacer(),
                        rx.text(i["for"], size="1", color_scheme="gray"),
                        width="100%", align="center", spacing="2",
                    )),
                    width="100%", spacing="1",
                ),
                rx.text("Plan a recipe and its ingredients show up here.", size="1",
                        color_scheme="gray"),
            ),
            spacing="4", width="100%", align="start",
        ),
        size="4", padding="1.5rem",
    )
