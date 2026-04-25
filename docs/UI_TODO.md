# UI Backlog

Items the user has agreed are worth doing but hasn't asked to build yet.
Captured here so they don't fall out of context across sessions.

Generated 2026-04-24, after the phase-tracker landed.

## Open

### #3 — Game seed + game-id readout

**What:** Once a game has been run, surface the seed (and the API
`game_id`) somewhere in the UI. Right now the seed sits in the form
input, which gets clobbered the moment the user types something else,
and the `game_id` is invisible.

**Why:** Reproducibility. If something interesting happens, you want to
re-run the same game, or share the URL. The `game_id` also helps when
debugging API calls in the browser devtools.

**Sketch:** small monospace readout in the scrubber row's right side,
e.g. `seed=42 · game=8f3c…d4a1`. Click-to-copy on each. Optional:
`/api/play` already accepts `seed=`; a "Permalink" button could build
`?seed=…&c1=…&c2=…&max_turns=…&granularity=…&reveal=…`.

### #4 — Engine-recommendation card thumbnails

**What:** The "Engine" panel renders text-only lines today. The
recommendations already carry `scryfall_id` (when known), so we have
everything we need to render a small card thumbnail next to each
suggested action — same treatment as the stack row.

**Why:** Consistency with the rest of the UI. Lets you visually
identify a recommended spell/permanent without reading the name.

**Sketch:** mirror the stack-item layout: 52×72px thumbnail + label +
score, all in one row. Falls back to the existing text-only mode when
`scryfall_id` is null. CSS already has `.stack-item-img` to crib from.

### #6 — Per-turn log grouping (collapsible turn sections)

**What:** Right now `#log-body` is a flat scrollable list. Long games
accumulate hundreds of entries.

**Why:** The per-step yellow highlight already shows "events this
step." Collapsible turn-N sections would let you skim the whole game
quickly and dive into a specific turn.

**Sketch:** infer turn boundaries from `log_since_last` rolling state
(or by attaching `turn_number` to each log entry on the server side
— small serialize change). Render `<details>` blocks per turn,
auto-open the turn matching the current snapshot.

### #8 — Effective P/T breakdown on hover

**What:** Today the hover preview shows the static Scryfall image. For
a creature whose `effective_power` differs from its printed power,
also show a breakdown like:

> 2/2 base (Wild Bear)  +2/+2 from Anthem  +1/+1 counters ×1  →  5/5

**Why:** Major debug tool for the bot work. When the bot picks an
unexpected attack, a glance at the hover would show whether it was
acting on a temporary buff, an Equipment, a static anthem, etc.

**Sketch:** requires more snapshot detail — currently only the rolled-up
`effective_*` and `keywords` are exposed; we'd need a per-source
breakdown. Could be opt-in on the snapshot to keep payload small.
Engine touch needed.

## Engine-side follow-ups (not pure UI)

### Replacement / grant provenance

**What:** Cards like Ragost grant subtypes ("your artifacts are also
Foods") and activated abilities to other permanents. The grantee
shows the granted property in the snapshot but doesn't know *who
granted it*.

**Why:** When debugging "why is this artifact a Food?", you currently
have to scan the whole battlefield for the grantor. Tracking
`(source_id, grant_kind)` per grant would let the UI display "→ Food
(Ragost)" on the affected card.

**Cost:** every grant site in `effects/` would need to record provenance.
Real refactor, deferred earlier; left here so it doesn't get lost.

### Wire `recommend.py` to the real `mtg_bot.search` engine

**What:** `mtg_bot/recommend.py` is a stub that returns legal-looking
actions with score 0.0 against a frozen response shape. The real
search engine lives at `mtg_bot/search/` (engine_adapter.py and
friends, built on a separate branch).

**Why:** The UI's "Engine" panel renders, but every recommendation
shows `+0.00`. Wiring it up turns the panel from a placeholder into a
real observability tool.

**Sketch:** replace the body of `recommend_from_snapshot` with a call
into `mtg_bot.search.engine_adapter` (or whatever the public surface
ends up being). Preserve the return shape — the UI tests in
`tests/test_recommend.py` lock down every field.
