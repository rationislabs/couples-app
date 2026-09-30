/* Keyboard for a tool used daily.
 *
 * The bridge to Reflex is deliberately the DOM: these shortcuts find the real
 * button and click it, rather than duplicating page state in JavaScript. There
 * is one source of truth for what Prev does, and it is the Python event.
 */
(function () {
  const typing = (el) =>
    el && (/^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName) || el.isContentEditable);

  const search = () =>
    document.querySelector('input[placeholder*="earch" i], input[placeholder*="uche" i]');

  function clickByText(...labels) {
    const wanted = labels.map((l) => l.toLowerCase());
    for (const b of document.querySelectorAll("button")) {
      if (b.disabled) continue;
      const t = (b.textContent || "").trim().toLowerCase();
      if (wanted.some((w) => t === w)) { b.click(); return true; }
    }
    return false;
  }

  /* Row cursor. Rows are re-rendered by Reflex on every state change, so the
     cursor is tracked by index and re-resolved on each keypress instead of
     holding a stale element reference. */
  let cursor = -1;
  const rows = () => [...document.querySelectorAll(".rt-TableRoot tbody tr")];

  function moveTo(i) {
    const rs = rows();
    if (!rs.length) return;
    rs.forEach((r) => r.classList.remove("kbd-row"));
    cursor = Math.max(0, Math.min(i, rs.length - 1));
    const row = rs[cursor];
    row.classList.add("kbd-row");
    row.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }

  function openRow() {
    const rs = rows();
    if (cursor < 0 || !rs[cursor]) return;
    const link = rs[cursor].querySelector("a[href]");
    if (link) link.click();
  }


  /* ---------------------------------------------------------------------
     Command palette. Navigation only.

     Deliberately vanilla and deliberately not Reflex. Two daily users who
     know their own app arrive with intent, not with a tab in mind, and nine
     tabs serve filing rather than intent. Navigating is a plain href, so this
     needs no state, makes no round trip, and cannot leave the backend and the
     screen disagreeing. Verbs — water the fern, next question — are phase 2
     and are not here, because a second way to do everything is how an app
     rots.
     --------------------------------------------------------------------- */
  const PLACES = [
    ["Tonight", "/", "what to do, dealt as cards"],
    ["Library", "/library", "films and series, what we are part-way through"],
    ["Books", "/books", "the shelf walk"],
    ["Music", "/music", "playlists, tracks, the vibe chart"],
    ["Recipes", "/recipes", "what to cook"],
    ["Meal plan", "/meal-plan", "the week"],
    ["Dates", "/dates", "places, the map, what we have done"],
    ["Conversation", "/convo", "questions to ask"],
    ["Household", "/household", "plants, shops, games, travel"],
    ["Plants", "/household#plants", "watering"],
    ["Shopping", "/household#shops", "where to buy things"],
    ["Games", "/household#games", "something to play"],
    ["Travel", "/dates#travel", "trips"],
  ];

  /* Verbs.

     A verb is not a second implementation of anything: it finds the real
     button on the page and clicks it, which is what n, p, d and e have always
     done. So there is exactly one definition of what "Deal again" means and it
     is the Python event behind that button. A verb only appears in the palette
     when its button is actually on screen, which is why this list needs no
     route table and cannot offer something that would not work. */
  const VERBS = [
    ["Deal again", ["deal again", "pick another", "show another"]],
    ["Ask me one", ["ask me one", "surprise me"]],
    ["Mark asked", ["mark asked", "asked it"]],
    ["Next", ["next"]],
    ["Previous", ["prev"]],
    ["Water everything due", ["water all due"]],
    ["Edit rows", ["edit"]],
    ["Finish editing", ["done"]],
    ["Clear filters", ["clear"]],
    ["Browse all questions", ["browse all questions"]],
    ["Restore removed rows", ["restore all"]],
  ];

  function findButton(labels) {
    const wanted = labels.map((l) => l.toLowerCase());
    for (const b of document.querySelectorAll("button")) {
      if (b.disabled) continue;
      const txt = (b.textContent || "").trim().toLowerCase();
      if (wanted.some((w) => txt === w)) return b;
    }
    return null;
  }

  function availableVerbs() {
    return VERBS
      .filter(([, labels]) => findButton(labels))
      .map(([name, labels]) => [name, { verb: labels }, "on this page"]);
  }

  /* Subsequence match, not substring: "cnv" should find Conversation. Score is
     how tightly the letters land, so an exact prefix beats a scattered hit. */
  function score(needle, hay) {
    if (!needle) return 0;
    const h = hay.toLowerCase();
    let i = 0, prev = -1, gaps = 0;
    for (let j = 0; j < h.length; j += 1) {
      if (h[j] !== needle[i]) continue;
      if (prev >= 0) gaps += j - prev - 1;
      prev = j;
      i += 1;
      if (i === needle.length) return 1000 - gaps - hay.length;
    }
    return -1;
  }

  function matches(q, extra) {
    const n = q.trim().toLowerCase();
    /* Verbs first at equal score: if you are already on the page, doing the
       thing beats navigating to where the thing is. */
    return (extra || []).concat(PLACES)
      .map((p) => [Math.max(score(n, p[0]), score(n, p[2]) - 200), p])
      .filter(([s]) => s >= 0)
      .sort((a, b) => b[0] - a[0])
      .map(([, p]) => p);
  }

  let pal = null, picked = 0, shown = [];

  function paint() {
    const list = pal.querySelector(".pal-list");
    list.innerHTML = shown
      .map((p, i) =>
        '<li class="' + (i === picked ? "on" : "") + '">' +
        '<span class="pal-name"></span><span class="pal-hint"></span></li>')
      .join("");
    /* Titles are ours, not user input, but building the row with textContent
       keeps it that way if PLACES ever grows a database-backed entry. */
    [...list.children].forEach((li, i) => {
      li.querySelector(".pal-name").textContent = shown[i][0];
      li.querySelector(".pal-hint").textContent = shown[i][2];
      li.addEventListener("mousedown", (e) => { e.preventDefault(); go(i); });
    });
  }

  function go(i) {
    const p = shown[i];
    if (!p) return;
    closePalette();
    if (p[1] && p[1].verb) {
      /* Re-resolved at click time, not at open time: Reflex may have
         re-rendered the button out from under the palette while it was open. */
      const b = findButton(p[1].verb);
      if (b) b.click();
      return;
    }
    window.location.href = p[1];
  }

  function closePalette() {
    if (pal) pal.classList.remove("on");
  }

  function openPalette() {
    mountPalette();
    pal.classList.add("on");
    const input = pal.querySelector("input");
    input.value = "";
    shown = matches("", availableVerbs());
    picked = 0;
    paint();
    input.focus();
  }

  function mountPalette() {
    if (pal) return;
    pal = document.createElement("div");
    pal.id = "palette";
    pal.innerHTML =
      '<div class="panel"><input type="text" placeholder="Go to…" ' +
      'autocomplete="off" spellcheck="false"><ul class="pal-list"></ul></div>';
    pal.addEventListener("mousedown", (e) => {
      if (e.target === pal) closePalette();
    });
    const input = pal.querySelector("input");
    input.addEventListener("input", () => {
      shown = matches(input.value, availableVerbs());
      picked = 0;
      paint();
    });
    input.addEventListener("keydown", (e) => {
      if (e.key === "ArrowDown" || (e.key === "n" && e.ctrlKey)) {
        e.preventDefault(); picked = Math.min(picked + 1, shown.length - 1); paint();
      } else if (e.key === "ArrowUp" || (e.key === "p" && e.ctrlKey)) {
        e.preventDefault(); picked = Math.max(picked - 1, 0); paint();
      } else if (e.key === "Enter") {
        e.preventDefault(); go(picked);
      } else if (e.key === "Escape") {
        e.preventDefault(); closePalette();
      }
    });
    document.body.appendChild(pal);
  }


  /* ---------------------------------------------------------------------
     Toast dismissal.

     Reflex owns the node: it renders whenever `notice` is non-empty and
     removes it when the state clears it, which handlers mostly never do. So
     the timer lives here. Watching the DOM rather than the state means no
     handler had to change, and a toast can never get stuck because the
     backend forgot to retract it.
     --------------------------------------------------------------------- */
  let toastTimer = null;
  function freshenToast(el) {
    if (!el) return;
    el.classList.remove("gone");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.add("gone"), 4000);
  }

  function watchToasts() {
    const seen = new WeakMap();
    new MutationObserver(() => {
      const el = document.querySelector(".toast");
      if (!el) return;
      const text = el.textContent;
      if (seen.get(el) === text) return;   // same message, timer already running
      seen.set(el, text);
      freshenToast(el);
    }).observe(document.body, { childList: true, subtree: true, characterData: true });
  }

  const help = () => document.getElementById("kbd-help");

  document.addEventListener("keydown", (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
      e.preventDefault();
      if (pal && pal.classList.contains("on")) closePalette();
      else openPalette();
      return;
    }
    if (e.metaKey || e.ctrlKey || e.altKey) return;

    if (e.key === "Escape") {
      if (pal && pal.classList.contains("on")) { closePalette(); return; }
      const h = help();
      if (h && h.classList.contains("on")) { h.classList.remove("on"); return; }
      if (typing(document.activeElement)) document.activeElement.blur();
      return;
    }

    if (typing(document.activeElement)) return;   // never steal real typing

    switch (e.key) {
      case "/":
        { const s = search(); if (s) { e.preventDefault(); s.focus(); s.select(); } }
        return;
      case "?":
        { const h = help(); if (h) { e.preventDefault(); h.classList.toggle("on"); } }
        return;
      case "j": e.preventDefault(); moveTo(cursor + 1); return;
      case "k": e.preventDefault(); moveTo(cursor - 1); return;
      case "Enter": if (cursor >= 0) { e.preventDefault(); openRow(); } return;
      case "n": case "]":
        if (clickByText("next")) e.preventDefault();
        return;
      case "p": case "[":
        if (clickByText("prev")) e.preventDefault();
        return;
      case "d":
        if (clickByText("deal again", "pick another", "show another")) e.preventDefault();
        return;
      case "e":
        if (clickByText("edit", "done")) e.preventDefault();
        return;
      case "g":
        window.scrollTo({ top: 0, behavior: "smooth" });
        return;
    }
  });

  /* The overlay is injected rather than put in every page's Python: it is the
     same on all eight pages and has no state worth round-tripping. */
  function mountHelp() {
    if (document.getElementById("kbd-help")) return;
    const d = document.createElement("div");
    d.id = "kbd-help";
    d.innerHTML =
      '<div class="panel"><h3>Keyboard</h3><dl>' +
      "<dt>/</dt><dd>Search</dd>" +
      "<dt>j / k</dt><dd>Move down and up the rows</dd>" +
      "<dt>Enter</dt><dd>Open the row you are on</dd>" +
      "<dt>n / p</dt><dd>Next and previous page</dd>" +
      "<dt>d</dt><dd>Deal again</dd>" +
      "<dt>e</dt><dd>Edit rows</dd>" +
      "<dt>g</dt><dd>Back to top</dd>" +
      "<dt>\u2318K</dt><dd>Go anywhere</dd>" +
      "<dt>?</dt><dd>Show this</dd>" +
      "<dt>Esc</dt><dd>Close, or leave the search box</dd>" +
      "</dl></div>";
    d.addEventListener("click", () => d.classList.remove("on"));
    document.body.appendChild(d);
  }
  function boot() { mountHelp(); watchToasts(); }
  if (document.readyState === "loading")
    document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
