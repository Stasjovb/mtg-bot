# Rust ETB-trigger emission audit

Audit of how ETB-triggered abilities fire in the **Python** engine
today and what infrastructure (if any) the **Rust** engine has to
emit them. Predicts the shape of the next cross-engine divergence
(forecast: **CE19**, the trigger-emitter / event-dispatch path) and
lays out the substrate-prep + per-Effect work needed to wire ETB
triggers in Rust.

This doc is **doc-only** — no code changes here. It is a pre-stage
for the planned ETB-triggers probe + closure slices.

Companion docs:
- [`docs/ORDER_SENSITIVE_SURFACES.md`](ORDER_SENSITIVE_SURFACES.md)
  §2-3, §"CE8 (predicted)" (renumbered CE19 post-CE18). Predicts
  this exact surface as the next CE candidate.
- [`docs/RUST_BF_ITERATION_AUDIT.md`](RUST_BF_ITERATION_AUDIT.md)
  §"CE8 — when Rust grows a `dispatch_event` / trigger emitter"
  (same prediction, with file:line maps for the inline-resolution
  status quo).
- [`docs/RUST_EFFECT_RNG_AUDIT.md`](RUST_EFFECT_RNG_AUDIT.md) —
  audit pattern this doc mirrors (Section breakdown +
  per-site checklist + closure-slice scope estimate).

---

## Section 1: Summary

- **Python ETB-triggered card count (EoE pool):** **145** of 475
  printings carry at least one `TriggeredAbility(event=Event.ENTERS,
  ...)` (predicate-style). Total `Event.ENTERS` trigger entries:
  **152** (a handful of cards carry more than one). Legacy
  string-key `trigger="etb"` count: 0 (Phase 2 migrated all of them
  to the predicate path; see `actions.py:3415`'s comment).
- **Rust trigger-emission infrastructure today:** **NONE.** Rust has
  no `dispatch_event` analog, no `TriggeredAbility` data shape on
  `CardPrinting`, no `Event` enum, no `push_triggered_ability`, no
  trigger-queue state. The closest existing surface is
  `CardPrinting.etb_effects: Vec<Effect>` (`rust/src/cards.rs:1897`)
  which is fired **inline** at stack-resolution time
  (`state_ops_resolve.rs:5419-5431` and the `_pause` counterpart at
  `state_ops_resolve.rs:5483-5495`) — NOT pushed onto the stack as a
  separate StackItem, NOT predicated on an event, and only fires for
  the **just-cast** source (not for other permanents observing its
  arrival).
- **Top-level verdict: substrate-blocked.** Probing the surface
  today will surface CE19, but closing it is NOT a one-slice fix —
  it needs (a) a `TriggeredAbility` data shape, (b) an `Event` enum
  + predicate substrate, (c) a `dispatch_event` walker, (d) a
  trigger StackItem variant + push helper, and (e) fan-out from
  every ETB-stamping site already inventoried by CE4. Realistic
  scope: 1 substrate slice + N per-Effect slices.

---

## Section 2: Python ETB trigger emission

### 2.1 Data shape

`TriggeredAbility` lives at `src/mtg_bot/effects/base.py:679-758`.
The relevant fields for the ENTERS path:

```python
@dataclass(frozen=True)
class TriggeredAbility:
    trigger: str = ""               # legacy string-key (unused on ENTERS post-Phase-2)
    effect: "Effect | None" = None  # the payload Effect that fires
    requires_void: bool = False     # EoE "Void —" gate
    once_per_turn: bool = False     # ledger gate
    tier_threshold: int = 0         # EoE Spacecraft tier gate
    event: "Event | None" = None    # the predicate-path enum value
    predicate: "Predicate | None" = None  # the subject/state filter
    room_half: "str | None" = None  # DSK Rooms half gate
```

A card's triggered abilities live on `CardPrinting.triggered_abilities`
(tuple of `TriggeredAbility`). The Phase-2 migration (per
`src/mtg_bot/actions.py:3414-3417`) routes every ETB-family
trigger — "this enters", "landfall", "an artifact enters under
your control", "a Kavu enters", "an enchantment enters under your
control", etc. — through `event=Event.ENTERS` + a `predicate` that
filters which firings care about which subject. See
`src/mtg_bot/cards/parser/triggers.py:603-1266` for the mapping
table: oracle-text phrase → `(Event.ENTERS, predicate)`.

### 2.2 The dispatch site

`dispatch_event` is at `src/mtg_bot/actions.py:3283-3399`. The
ETB-specific helper that calls it:

```python
# src/mtg_bot/actions.py:3402-3421
def _trigger_etb_abilities(state: GameState, creature: "GameObject") -> None:
    ...
    dispatch_event(state, Event.ENTERS, label="enters", obj=creature)
```

`_trigger_etb_abilities` is called from exactly two sites in the
engine:

| # | Site | What enters |
|---|---|---|
| P-ETB-1 | `src/mtg_bot/actions.py:1139` (inside `_play_land`) | A land just played from hand |
| P-ETB-2 | `src/mtg_bot/actions.py:3130` (inside `put_into_battlefield`) | Every non-land permanent path (resolve, reanimation, search-and-bf, token creation, ManifestDread, copy effects, exile-recall) |

In addition, `turn.py:619` fires `dispatch_event(state, Event.ENTERS,
label="landfall", obj=new_land)` from one site OUTSIDE the standard
ETB path (a non-standard "land enters via grant" — see `turn.py:579`
docstring). All three paths converge on `dispatch_event`.

### 2.3 The walker

`dispatch_event` at `actions.py:3346-3399`:

```python
permanents = list(state.battlefield)       # snapshot, NOT live iter
if extra_observers:
    ...                                     # append off-bf observers (rare)
for source in permanents:
    for ability_index, ability in enumerate(
        source.printing.triggered_abilities
    ):
        if not ability.matches_event(event, subjects, source, state):
            continue
        ...                                 # combat-damage agg dedup, room_half gate
        firings = (
            etb_trigger_multiplier(state, source.controller_id)
            if event is _Event.ENTERS else 1
        )
        for _ in range(firings):
            push_triggered_ability(state, source=source, ability=ability,
                                   ability_index=ability_index, ...)
```

Key shape properties:

1. **Outer iteration: `list(state.battlefield)`** — Python's centralized
   battlefield (ETB-timestamp order). Snapshotted at dispatch entry so
   triggers that ETB new permanents during dispatch don't observe their
   own event in the same pass (the comment at `actions.py:3343-3345`
   makes this explicit).
2. **Inner iteration: `enumerate(source.printing.triggered_abilities)`**
   — fixed per-printing tuple, in declaration order.
3. **Predicate filter:** each `ability.matches_event` re-evaluates the
   predicate against the (event, subjects, source, state) tuple.
4. **`etb_trigger_multiplier`** lets cards like Panharmonicon-shape
   modifiers fire ETB-triggers N times (gated to `Event.ENTERS`
   only; other events fire once).
5. **No APNAP sort** — triggers go on the stack in source's
   `state.battlefield` index order, regardless of controller. CR
   603.3b technically requires APNAP; Python's "single-controller
   queue makes APNAP moot" simplification is documented in
   `RUST_PARITY_PLAN.md:28-30` and `ORDER_SENSITIVE_SURFACES.md` §3.

### 2.4 Stack push

`push_triggered_ability` is at `src/mtg_bot/actions.py:3172-3280`.
It:

1. Gates on `should_fire_trigger(state, source.id, ability_index,
   ability)` (once-per-turn ledger, tier_threshold, void).
2. Picks targets if `ability.effect.target_count_range()` requires
   them (via `ability.effect.legal_targets(...)` + controller's
   `agent.choose_target` loop, with per-slot `target_slot_kinds`).
3. If `fixed_targets` is provided (e.g. for "the player who was
   hit"), skips target selection.
4. Appends a `StackItem(source=source, controller_id=..., ability=ability,
   targets=targets, ...)` to `state.stack`.
5. Logs the trigger line.
6. Returns True on push, False on fizzle (no legal targets / gated
   off).

`StackItem.ability` (`game.py:StackItem` dataclass) carries the
`TriggeredAbility` reference; resolution at `actions.py:2655`+
walks `stack_item.ability.effect` to actually apply the effect.

### 2.5 Stack-push order under APNAP

Per CR 603.3b: each player orders their own simultaneous triggers,
then they go on the stack in APNAP order (active player's first).
Python's dispatcher does NEITHER — it walks
`list(state.battlefield)` in centralized timestamp order, regardless
of controller. Under CE4 (every bf entry gets a fresh strictly-
monotonic `etb_timestamp`), the active player's permanents are NOT
contiguous in the centralized list whenever both players ETB'd
permanents in interleaved order.

**Cross-reference to BF audit:** `RUST_BF_ITERATION_AUDIT.md` §4 ranks
this as the "CE8 substrate-blocked surface" — Python's emitter order
mirrors `state.battlefield`'s order, which CE4 already pinned to
ETB-timestamp. Rust's eventual emitter must walk
`bf_iter_etb_sorted(state)` (the CE5-introduced helper at
`rust/src/bf_iter.rs:61`) for the iteration to match.

### 2.6 EoE card pool count

Counted via `OracleParserCardSource().get_printings()` (475 EoE
printings + parser-emitted overrides):

- **Printings with at least one `Event.ENTERS` TriggeredAbility:**
  **145**
- **Total ENTERS TriggeredAbility entries:** **152**
- **Legacy string-key `trigger="etb"` printings:** 0 (post-Phase-2)

Spot-check examples (first 10 in iteration order):

```
Tezzeret, Cruel Captain
All-Fates Stalker
Astelli Reclaimer
Auxiliary Boosters
Banishing Light
Dockworker Drone
Exosuit Savior
Haliya, Guided by Light
Hardlight Containment
Honored Knight-Captain
```

So ~30% of EoE printings carry an ETB trigger. This is a **large**
surface — once Rust grows the emitter, ETB triggers will fire on
~roughly 1 in 3 bf entries during a typical game, and every fired
trigger is a potential cross-engine compare point.

---

## Section 3: Rust ETB trigger emission today

### 3.1 What Rust has: `etb_effects` (inline application)

`rust/src/cards.rs:1891-1897`:

```rust
/// "When ~ enters the battlefield" effects. Fire on any
/// permanent landing on the battlefield (creature, artifact,
/// enchantment, planeswalker). Empty Vec = no ETB. First-slice
/// scope: the effects fire IMMEDIATELY on entry, no separate
/// stack item — real MTG triggers them onto the stack and
/// resolves in priority order; that timing nuance is deferred.
pub etb_effects: Vec<Effect>,
```

The application sites are inside the stack-resolver, NOT at the
ETB-stamping sites:

| # | Site | When it fires |
|---|---|---|
| R-ETB-1 | `rust/src/state_ops_resolve.rs:5419-5431` (`resolve_top_of_stack`) | When the resolving stack item's source landed on the battlefield post-resolve (CR 608.2m + the round-9 gate) |
| R-ETB-2 | `rust/src/state_ops_resolve.rs:5483-5495` (`resolve_top_of_stack_pause`) | Identical to R-ETB-1 but without auto-resolving pending decisions |

The fire pattern at R-ETB-1:

```rust
// state_ops_resolve.rs:5419-5431
if post_resolve_zone == Some(ZONE_BATTLEFIELD) {
    let etb_effects: Vec<Effect> =
        match find_source_printing_id(self, top.source_obj_id) {
            Some(printing_id) => match self.registry.lookup(printing_id) {
                Some(printing) => printing.etb_effects.clone(),
                None => Vec::new(),
            },
            None => Vec::new(),
        };
    for effect in &etb_effects {
        apply_effect(self, effect, top.source_obj_id)?;
    }
}
```

This is **not** a triggered ability emitter. It's a per-source
"self-ETB effect" hatch with **four** Python-incompatible properties:

1. **Self-only.** Only fires for the source whose stack item is
   resolving — i.e. the just-cast creature's own ETB effects. **No
   other permanent on the battlefield observes the event**, so
   "when ANOTHER creature enters under your control" / "when an
   artifact enters under your control" / Kavu-shape / Panharmonicon-
   shape triggers DO NOT FIRE in Rust today, full stop.
2. **Inline, not on-stack.** No StackItem push, no response window,
   no priority round. Real MTG: ETB triggers stack on top of the
   permanent's spell resolution and resolve LIFO; effects observing
   them (counterspells targeting triggers — CR 701.5 — are illegal,
   but generic stack manipulation isn't). The inline shape means a
   probe that pushes an instant in response to an ETB trigger has
   nothing to push against.
3. **Cast path only.** The R-ETB-1 / R-ETB-2 gate is "did the source's
   stack item just resolve onto the battlefield". ETB effects do NOT
   fire on the non-cast entry paths: reanimation
   (`move_object_from_graveyard_to_battlefield` at
   `state_ops_zones.rs:319-352`), search-and-bf
   (`SearchLibraryForBasicLandTapped` resolve arm at
   `state_ops_resolve.rs:1437-1540`,
   `ReturnCreatureFromYourGraveyardToBattlefield` at
   `state_ops_resolve.rs:2047-2129`), token creation
   (`Effect::CreateToken` resolve arm), `move_object` to
   `ZONE_BATTLEFIELD` (the generic mover at
   `state_ops_zones.rs:227-247`), or ManifestDread face-down flip
   (when those land).
4. **No event predicate.** `etb_effects: Vec<Effect>` is a flat list
   of effects, not a list of `(predicate, effect)` pairs. There's no
   way to encode "trigger only when ANOTHER creature enters" or
   "trigger only when a LAND enters under your control".

### 3.2 What Rust does NOT have

Grep results across `rust/src/`:

| Concept | Rust today | Closest Python equivalent |
|---|---|---|
| `Event` enum (`Event::ENTERS`, `Event::DIES`, etc.) | **absent** | `src/mtg_bot/effects/predicates.py:Event` |
| `TriggeredAbility` struct | **absent** | `src/mtg_bot/effects/base.py:680` |
| `Predicate` trait/enum + `matches_event` | **absent** | `src/mtg_bot/effects/predicates.py` (`Subject`, `IsSelf`, `IsLand`, `Controlled`, etc.) |
| `CardPrinting.triggered_abilities` field | **absent** | `src/mtg_bot/cards/base.py:CardPrinting.triggered_abilities` (Phase 1.5+ tuple) |
| `dispatch_event` walker | **absent** | `src/mtg_bot/actions.py:3283-3399` |
| `push_triggered_ability` helper | **absent** | `src/mtg_bot/actions.py:3172-3280` |
| `StackItem::TriggeredAbility { ... }` variant | **absent** (only `StackItem { source_obj_id, controller }` at `state.rs:388-391`) | `src/mtg_bot/game.py:StackItem.ability` field |
| `should_fire_trigger` gate (once-per-turn / tier / void) | **absent** | `src/mtg_bot/turn.py:should_fire_trigger` |
| `etb_trigger_multiplier` (Panharmonicon-shape) | **absent** | `src/mtg_bot/turn.py:etb_trigger_multiplier` |
| `state.once_per_turn_fired` ledger | **absent** | `state.once_per_turn_fired: set[tuple[int, int]]` on Python `GameState` |

The Rust smoke-harness Python-side ALSO doesn't pass `etb_effects`
in its registry dicts today — see `cross_engine.py:370-384` (the
`printing_dict` keys are `name`, `card_types`, `mana_cost`,
`effects`, `mana_produced`, `power`, `toughness` only). So the
smoke harness has never exercised even the existing inline
`etb_effects` path; that surface is dead code from the smoke's
point of view.

### 3.3 What it would take to wire ETB triggers in Rust

Mapped onto the Python machinery in §2:

1. **`Event` enum.** Mirror `src/mtg_bot/effects/predicates.py:Event`
   — at minimum `ENTERS`, `DIES`, `ATTACKS`, `BLOCKS`,
   `DEALS_COMBAT_DAMAGE`, `CAST`, `RESOLVES`, `LEAVES`. First slice
   could ship `ENTERS` alone.
2. **`Predicate` enum.** Mirror the Python `Predicate` algebra (`Always`,
   `IsSelf`, `IsLand`, `IsArtifact`, `IsCreature`, `Controlled`,
   `Subject(..., Pred)`, `Pred & Pred`, `~Pred`, `HasSubtype(...)`).
   Closed-enum so the bridge surface validates at parse time.
3. **`TriggeredAbility` struct.** Add `event: Option<Event>`,
   `predicate: Option<Predicate>`, `effect: Effect`, plus the
   `requires_void: bool`, `once_per_turn: bool`,
   `tier_threshold: u32`, `room_half: Option<String>` gates from
   `effects/base.py:707-734`.
4. **`CardPrinting.triggered_abilities: Vec<TriggeredAbility>` field.**
   Add to `rust/src/cards.rs:1855-1898`; parse from the registry dict
   alongside `etb_effects` (which becomes a special case of "an
   `IsSelf` ENTERS trigger that fires the effect").
5. **`StackItem` variant for triggered abilities.** Today
   `StackItem` is `{ source_obj_id: u32, controller: u8 }`
   (`state.rs:388-391`). Add `triggered_ability: Option<...>` or
   move to a kind-enum `StackItem::Spell { ... } | StackItem::Trigger { source, ability_index, targets, ... }`.
6. **`push_triggered_ability` helper.** Mirror Python's
   `actions.py:3172-3280`. Includes target selection (the existing
   `state_ops_decisions.rs` pending-decision substrate can carry
   the picking; auto-resolve gives a deterministic default).
7. **`dispatch_event` walker.** Walk
   `bf_iter_etb_sorted(state)` ×
   `enumerate(source.printing.triggered_abilities)`; per-ability,
   re-check predicate; per-match, call `push_triggered_ability`.
8. **`should_fire_trigger` + `state.once_per_turn_fired` ledger.**
   Add the `(source_id, ability_index) -> bool` set to `GameState`
   plus its cleanup-step reset.
9. **Resolver dispatch for trigger stack items.** When a trigger
   item resolves, apply `stack_item.ability.effect` via the existing
   `apply_effect` path (the Effect closure is already in place — the
   trigger payload is just an Effect).
10. **Fan-out from every ETB-stamping site.** See §4. Every site
    that today calls `reserve_etb_timestamp` (or directly writes
    `obj.etb_timestamp = ...`) is a candidate dispatch_event site.

---

## Section 4: Cross-engine compatibility — every Rust ETB-stamping site is a missed trigger

Cross-reference of every Rust `reserve_etb_timestamp` / `etb_timestamp =`
site from the CE4 closure. For each, the column "Triggers fire?" lists
what fires today vs what SHOULD fire under a Python-faithful emitter.

| # | Site | File:line | Why an ETB happens here | Triggers fire today? | Should fire? |
|---|---|---|---|---|---|
| RS1 | `move_source_post_resolve` permanent path | `rust/src/state_ops_resolve.rs:300-302` | Post-resolve permanent placement after cast (CR 608.2m). Followed by the `etb_effects` inline-apply at `state_ops_resolve.rs:5419-5431`. | **Only the just-cast source's own `etb_effects` fire**, inline. No other permanent observes the event. | A `dispatch_event(ENTERS, obj=src)` walking ALL bf permanents × all their triggered_abilities. |
| RS2 | `SearchLibraryForBasicLandTapped` arm | `rust/src/state_ops_resolve.rs:1477, 1494` | Search-and-bf for a basic land tapped (Cultivate / Rampant Growth shape). | **NO** — `apply_effect` arms never call into `etb_effects` resolution. | dispatch_event ENTERS on the searched-up land. (Many landfall triggers in EoE pool key off this.) |
| RS3 | `ReturnCreatureFromYourGraveyardToBattlefield` arm | `rust/src/state_ops_resolve.rs:2103, 2118` | Reanimation. | **NO** | dispatch_event ENTERS on the reanimated creature. |
| RS4 | `CreateToken` allocator block | `rust/src/state_ops_resolve.rs:1287` (block-stamp for N tokens) | Token creation. | **NO** | dispatch_event ENTERS on each created token. |
| RS5 | Surveil-related ETB bump | `rust/src/state_ops_resolve.rs:3778` | Surveil-shape arm that puts something onto the battlefield. | **NO** | dispatch_event ENTERS on the placed object. |
| RS6 | `ReturnAllCreaturesFromYourGraveyardToBattlefield` block-stamp | `rust/src/state_ops_resolve.rs:4805, 4809` | Mass reanimation block. Reserves a contiguous timestamp range so each returned permanent gets a strictly-monotonic stamp. | **NO** | One dispatch_event ENTERS per returned permanent, in stamp order. **Order matters** — death/ETB chains can ripple. |
| RS7 | Exile-recall block on source LTB | `rust/src/state_ops_resolve.rs:5343, 5347` | `return_paired_exiles_for` (Oblivion-Ring-style auto-recall). Also a contiguous block. | **NO** | One dispatch_event ENTERS per recalled permanent. |
| RS8 | "+1 bump" arm | `rust/src/state_ops_resolve.rs:5567` | An Effect arm that adds a single ETB-stamped object. | **NO** | dispatch_event ENTERS. |
| RS9 | Generic `move_object` to battlefield | `rust/src/state_ops_zones.rs:232-233` | Catch-all zone-mover when target is `ZONE_BATTLEFIELD`. Many Effect arms route through this. | **NO** | dispatch_event ENTERS. |
| RS10 | `move_object_from_graveyard_to_battlefield` | `rust/src/state_ops_zones.rs:336, 354` | Reanimation primitive. | **NO** | dispatch_event ENTERS. |
| RS11 | Land play path | `rust/src/state_ops_cast.rs:205, 210` | `_play_land` equivalent (a counter bump rather than `reserve_etb_timestamp`, but the same write effect). | **NO** | dispatch_event ENTERS (label="enters" on cast-land path, or label="landfall" on grant-land path; both share the predicate-style ENTERS family in Python). |
| RS12 | ManifestDread face-down land | `rust/src/state_ops_decisions.rs:525, 540` | ManifestDread choice resolves: the chosen card flips face-down onto bf. | **NO** | dispatch_event ENTERS on the face-down permanent. |

**Gap summary:** **12 distinct bf-entry sites** in Rust today.
**Exactly one of them** (RS1) wires the partial inline `etb_effects`
hatch — and even that one only fires the source's OWN effects, not
other permanents' triggers observing the event. The other 11 sites
silently drop every trigger they should emit.

### 4.1 What Python does at each equivalent site

For sanity-check, Python's converse is:

- Every Python bf-entry path either calls
  `_trigger_etb_abilities(state, obj)` directly
  (`actions.py:1139`, `actions.py:3130`) or calls
  `put_into_battlefield` which then calls it.
- `dispatch_event(state, Event.ENTERS, ...)` is the single
  centralized walker.
- The 145-printing surface (Section 2.6) means ~30% of Python bf
  entries push at least one stack item.

So today, every Rust bf entry that Python would have emitted
triggers on is a silent drop. Under cross-engine smoke, the
divergence is invisible only because the smoke deckspec
deliberately avoids non-vanilla creatures — the moment one of the
145 ETB-trigger cards lands in a smoke deck, the divergence
surfaces.

---

## Section 5: Predicted CE shape (forecast CE19)

### 5.1 Concrete divergence scenario

Inject a creature with an "ETB: draw a card" trigger into both
engines' decks. Pick a freq>=2 EoE example: **All-Fates Stalker**
(spot-checked above) — actually has "When this creature enters,
each opponent gets <X>" or similar; a cleaner illustrative example
is the synthetic "ETB: draw a card" creature (carries one
`TriggeredAbility(event=Event.ENTERS, predicate=IsSelf(),
effect=DrawCards(1))`).

Cast the creature on turn 2 (drop a land + cast).

### 5.2 Python post-cast state (snapshot AFTER stack drains)

- The creature is on `p0.battlefield` (or wherever it was cast for).
- The ETB trigger pushed a `StackItem` (with the `DrawCards(1)`
  effect) right after the creature's spell resolved.
- The smoke harness's auto-resolve walks the stack: the trigger
  resolves, `p0.hand` size **grows by 1**.
- Post-drain: `state.stack` is empty, `state.battlefield` has the
  new creature, `state.players[0].hand` is 1 card larger.

### 5.3 Rust post-cast state (snapshot AFTER stack drains)

- The creature is on `state.players[0].battlefield` (CE4-correct).
- The `etb_effects: Vec<Effect>` inline-fires the `DrawCards(1)` at
  R-ETB-1 (state_ops_resolve.rs:5419), so for this specific
  IsSelf-only ENTERS pattern Rust actually does fire — IF the smoke
  harness passes `etb_effects: [DrawCards(1)]` in the registry
  dict.

So for the simplest "this creature ETBs: draw a card" probe with
predicate=`IsSelf()`, the divergence is **invisible** if the smoke
harness wires `etb_effects` — Rust's inline application produces
the same final state as Python's on-stack version.

### 5.4 The cleaner CE-surfacing probe

The probe that surfaces the divergence has to involve a trigger
whose source is **not** the just-cast permanent:

**Example A: Panharmonicon-shape "another creature enters"**

A pre-existing artifact on the battlefield with:
`TriggeredAbility(event=Event.ENTERS, predicate=Subject(None,
IsCreature()) & ~IsSelf() & Controlled(YOU), effect=DrawCards(1))`.

Then cast a vanilla creature.

- **Python:** `dispatch_event` walks the bf, finds the artifact's
  matching trigger, pushes a `DrawCards(1)` trigger onto the stack
  for the active player. Stack drains. `hand_p0` grows by 1.
- **Rust:** R-ETB-1 only fires the just-cast creature's OWN
  `etb_effects`. The artifact's "another creature enters" trigger
  has no path to fire. `hand_p0` does NOT grow.
- **Divergence at next snapshot:** `hand_p0` field differs by 1.

**Example B: Landfall**

Pre-existing creature on the bf with:
`TriggeredAbility(event=Event.ENTERS, predicate=Subject(None,
IsLand()) & Controlled(YOU), effect=DealDamageAnyTarget(1))`.

Play a land.

- **Python:** lands fire `_trigger_etb_abilities` from `_play_land`
  (`actions.py:1139`); the dispatcher fires the creature's landfall
  trigger; the trigger resolves and deals 1 to opponent.
- **Rust:** `_play_land`'s Rust counterpart (`state_ops_cast.rs:205`
  area) writes the ETB stamp but never calls a trigger walker.
  Opponent's life total does NOT decrease.
- **Divergence:** `life_p1` field differs.

### 5.5 Divergence axis classification

- **Single-axis** for the simplest Panharmonicon-shape probe (just
  `hand_p0`).
- **Multi-axis** for Landfall + on-stack-response probes:
  `life_p1` + `stack` length (Rust empty, Python had the trigger on
  it pre-resolve) + downstream effects.

Both surface CE19 cleanly. The simplest first probe is the
Panharmonicon-shape `hand_p0` size compare — one axis, one trigger,
deterministic.

---

## Section 6: Closure plan

### 6.1 Slice ordering

The closure is **substrate-prep-needed**, not one-slice. Suggested
sequence:

**Slice 1 — substrate (the big one).** Add the data shapes, dispatch
walker, and stack variant. Touches:

- `rust/src/cards.rs`:
  - Add `pub enum Event { Enters, Dies, Attacks, Blocks,
    DealsCombatDamage, Cast, Resolves, Leaves }` (mirror
    `src/mtg_bot/effects/predicates.py:Event`).
  - Add `pub enum Predicate { Always, IsSelf, IsLand, IsArtifact,
    IsCreature, IsEnchantment, Controlled(ControllerRel),
    Subject(Option<SubjectKey>, Box<Predicate>), And(Box<Predicate>,
    Box<Predicate>), Not(Box<Predicate>), HasSubtype(String), ... }`.
  - Add `pub struct TriggeredAbility { event: Option<Event>,
    predicate: Option<Predicate>, effect: Effect, requires_void:
    bool, once_per_turn: bool, tier_threshold: u32, room_half:
    Option<String> }`.
  - Add `pub triggered_abilities: Vec<TriggeredAbility>` field to
    `CardPrinting`. Parse from registry dict.
- `rust/src/state.rs`:
  - Replace `StackItem { source_obj_id, controller }` with a
    kind-enum: `enum StackItem { Spell { source_obj_id, controller
    }, Trigger { source_obj_id, controller, ability_index, targets,
    combat_damage_amount, ... } }`. **Or** add `kind: StackKind`
    discriminant + optional trigger fields (lower-churn).
  - Add `pub once_per_turn_fired: HashSet<(u32, u32)>` ledger.
- New file `rust/src/state_ops_triggers.rs`:
  - `pub fn dispatch_event(state: &mut GameState, event: Event,
    subject_id: u32, label: &str, ...) -> PyResult<()>`. Mirror
    of `actions.py:3283-3399`. Walks `bf_iter_etb_sorted(state)`.
  - `pub fn push_triggered_ability(state, source_id, ability_index,
    ability, targets, ...) -> PyResult<bool>`. Mirror of
    `actions.py:3172-3280`. Target selection routes through the
    existing `state_ops_decisions.rs` pending-decision substrate.
  - `pub fn should_fire_trigger(state, source_id, ability_index,
    ability) -> bool`. Mirror of `turn.py:should_fire_trigger`
    (once-per-turn ledger + tier_threshold + requires_void).
- `rust/src/state_ops_resolve.rs`:
  - Update `resolve_top_of_stack` and `_pause` to dispatch by
    `StackItem` kind: Spell items go through the existing path;
    Trigger items apply `stack_item.ability.effect` and pop.
- `rust/src/state_ops_cleanup.rs`:
  - Clear `state.once_per_turn_fired` at end-of-turn.

Estimated scope: **300-500 LOC** plus tests. Mostly mechanical mirror
of the Python machinery.

**Slice 2 — fire from every ETB-stamping site.** Replace the
existing inline `etb_effects` apply at R-ETB-1 / R-ETB-2 with a
`dispatch_event(ENTERS, obj=src)` call, and add the same call to
all 11 other sites in §4:

```rust
// after every `obj.etb_timestamp = reserve_etb_timestamp(state)`
// + push-to-bf-zone:
crate::state_ops_triggers::dispatch_event(
    state, Event::Enters, obj.id, "enters"
)?;
```

Each call point is ~3 LOC. Total: ~36 LOC across 12 sites + the 2
existing `etb_effects` sites refactored to use the same path.

**Slice 3+ — per-trigger-Effect coverage.** Each `TriggeredAbility`
predicate shape (IsSelf, Subject(None, IsLand) & Controlled(YOU),
Subject(None, IsArtifact()) & Controlled(YOU) & ~IsSelf(),
HasSubtype("Kavu"), etc.) needs predicate-evaluation code +
test fixtures. The EoE pool has ~10-15 distinct predicate templates
(per `cards/parser/triggers.py:603-1266` table). Each is a
small slice (~30-50 LOC + a smoke probe).

**Slice N — Panharmonicon-shape `etb_trigger_multiplier`** (if
there's a freq>=2 EoE card requiring it). Probably out-of-scope for
the first wave.

### 6.2 Cross-cutting concerns

1. **Order:** `dispatch_event` must walk `bf_iter_etb_sorted(state)`
   (CE5-introduced helper at `rust/src/bf_iter.rs:61`), NOT
   `state.players[0].battlefield` followed by
   `state.players[1].battlefield`. The helper is already documented
   as the "future trigger emitter" consumer at `bf_iter.rs:16`. Get
   this right in slice 1 — fixing it later means re-validating every
   smoke deckspec.
2. **APNAP:** Mirror Python's deliberate simplification — no APNAP
   sort. Pin in `docs/SEARCH_LIMITATIONS.md` (Python already has the
   pin per `RUST_PARITY_PLAN.md:28-30`).
3. **Self-observation snapshot:** Mirror Python's `permanents =
   list(state.battlefield)` snapshot at dispatch entry (so ETBs
   triggered by the dispatch don't observe their own event). Today
   Rust's inline R-ETB-1 application has the same effect because
   it fires per-stack-item, not per-emitter pass; the new walker
   must take a `let permanents: Vec<u32> = bf_iter_etb_sorted(state).iter().map(|o| o.id).collect();` snapshot.
4. **Smoke-harness registry-dict wiring:** `cross_engine.py:370-384`
   needs a new `triggered_abilities` key per printing, serialized
   to match the Rust parser. Otherwise probes can't actually
   exercise the new substrate.
5. **GameState clone semantics:** `once_per_turn_fired: HashSet`
   needs clone-on-write or just `Clone` — cheap either way.

### 6.3 Estimated total slice scope

- **Slice 1 (substrate):** ~300-500 LOC + ~150 LOC tests
- **Slice 2 (fan-out from 12 sites):** ~50 LOC + the existing
  `etb_effects` smoke harness wiring + ~50 LOC tests
- **Slice 3 (first per-Effect coverage — IsSelf-only ENTERS):**
  ~50 LOC + the first cross-engine probe (~50 LOC)
- **Slices 4-N (Panharmonicon-shape, landfall, artifact-enters,
  Kavu-enters, etc.):** ~30-50 LOC each × ~10-15 predicate shapes

**Realistic 1000-game-ready outlook:** 5-8 slices over 2-3 sessions
if no surprises. Most likely surprise: the `Predicate` algebra
needs a richer surface than the closed-enum approach (some EoE
parser predicates compose ad-hoc — `Subject(None, X) & Y &
~IsSelf()` is recursive). If `Predicate` ends up needing
`Box<dyn Trait>` or a more complex AST, slice 1 expands by ~100-200
LOC.

---

## Section 7: Probe recommendation

### 7.1 Concrete first-probe selector

The simplest CE19-surfacing probe is **Panharmonicon-shape**:
inject a pre-existing artifact on p0's battlefield carrying a
`TriggeredAbility(event=Event.ENTERS, predicate=Subject(None,
IsCreature()) & Controlled(p0) & ~IsSelf(),
effect=DrawCards(1))`. Then cast a vanilla creature in p0's hand
during step ~168 (mid-game) of the existing
`multi_blocker_deckspec` walk.

**Probe selector skeleton** (modeled on
`counterspell_selector` / `mass_removal_side_channel` in
`src/mtg_bot/parity/cross_engine.py`):

```python
def panharmonicon_etb_selector(side_channel):
    """Inject a pre-existing 'when another creature enters under your
    control, draw a card' artifact on p0's bf, then a vanilla
    creature spell into p0's hand. Cast it.

    Surfaces CE19: Rust's inline etb_effects only fires the just-cast
    source's own effects; the pre-existing artifact's "another creature
    enters" trigger never fires in Rust today.
    """
    inject_at_step = 168
    artifact_def = CardDef(
        name="Witness Drone",
        card_type="Artifact",
        triggered_abilities=[
            TriggeredAbility(
                event=Event.ENTERS,
                predicate=Subject(None, IsCreature()) & Controlled(YOU) & ~IsSelf(),
                effect=DrawCards(1),
            ),
        ],
        ...
    )
    bait_def = CardDef(name="Bait Bears", card_type="Creature", power=2, toughness=2, ...)
    ...
```

### 7.2 Expected behaviors

- **Pre-injection step 168:** clean walk (the existing
  `multi_blocker_deckspec` is byte-identical).
- **Post-inject + cast:** **Python's `hand_p0` grows by 1, Rust's
  does not.** Single-axis divergence on `hand_p0` field count.
- **Stack mid-resolve compare (between cast and full drain):**
  Python's `stack` has the trigger stacked on top of the creature
  spell (length 2); Rust's `stack` has only the creature spell
  (length 1) — multi-axis if probed mid-drain.

### 7.3 Acceptance pin

Once CE19 surfaces, the probe gets xfail-pinned the same way CE18
was pinned in `tests/test_parity_smoke.py`. The xfail is removed by
the closure slices in §6. **Invariant number:** if numbering
continues from CE18's I45, the CE19-closure invariant lands at I46
(or wherever the next gap-closure invariant runs); see
`PHASE5_STATUS.md` for the current ceiling.

### 7.4 What this probe does NOT surface

Out of scope for first-probe:

- **LtB triggers** — different event (Event.LEAVES) + different
  emitter site (the LTB primitives at
  `state_ops_resolve.rs::move_off_battlefield` etc.). Closes the same
  substrate but needs its own probe.
- **Combat-damage triggers** (CR 702.X triggered by `Event.DEALS_COMBAT_DAMAGE`).
  Touches the granted-damage-trigger family that already has a
  partial Python-side observer aggregator (`_fire_combat_damage_to_player_triggers`,
  `actions.py:3365-3370`).
- **Attack / block triggers** (`Event.ATTACKS`, `Event.BLOCKS`).
  Same substrate, different emitter sites.
- **Cast triggers** (`Event.CAST`). Need a different fan-out site
  (`state_ops_cast.rs` after a successful cast).

All four are slice-N follow-ups once the ENTERS substrate is
proven via the Panharmonicon probe.

---

## Appendix: Quick-reference site map

### Python emission sites

| ID | Site | Role |
|---|---|---|
| P-ETB-1 | `src/mtg_bot/actions.py:1139` (`_play_land`) | Land path |
| P-ETB-2 | `src/mtg_bot/actions.py:3130` (`put_into_battlefield`) | Every non-land permanent path |
| P-ETB-3 | `src/mtg_bot/turn.py:619` (out-of-band landfall) | Grant-land hook |

### Python dispatcher / pusher

- `dispatch_event` — `src/mtg_bot/actions.py:3283-3399`
- `_trigger_etb_abilities` — `src/mtg_bot/actions.py:3402-3421`
- `push_triggered_ability` — `src/mtg_bot/actions.py:3172-3280`

### Python data shapes

- `TriggeredAbility` — `src/mtg_bot/effects/base.py:680-758`
- `Event` enum — `src/mtg_bot/effects/predicates.py:Event`
- Phrase → predicate mapping — `src/mtg_bot/cards/parser/triggers.py:603-1266`

### Rust ETB-stamping sites (12 — see §4)

| ID | File:line | Path |
|---|---|---|
| RS1 | `state_ops_resolve.rs:300-302` | Spell resolve → permanent landing |
| RS2 | `state_ops_resolve.rs:1477, 1494` | SearchLibraryForBasicLandTapped |
| RS3 | `state_ops_resolve.rs:2103, 2118` | ReturnCreatureFromYourGraveyardToBattlefield |
| RS4 | `state_ops_resolve.rs:1287` | CreateToken block allocator |
| RS5 | `state_ops_resolve.rs:3778` | Surveil-shape arm bf-push |
| RS6 | `state_ops_resolve.rs:4805, 4809` | Mass-reanimation block |
| RS7 | `state_ops_resolve.rs:5343, 5347` | Exile recall block |
| RS8 | `state_ops_resolve.rs:5567` | "+1 bump" arm |
| RS9 | `state_ops_zones.rs:232-233` | Generic move_object → bf |
| RS10 | `state_ops_zones.rs:336, 354` | move_object_from_graveyard_to_battlefield |
| RS11 | `state_ops_cast.rs:205, 210` | _play_land equivalent |
| RS12 | `state_ops_decisions.rs:525, 540` | ManifestDread face-down flip |

### Rust inline `etb_effects` application (today's only "trigger" path)

- `resolve_top_of_stack` — `rust/src/state_ops_resolve.rs:5419-5431`
- `resolve_top_of_stack_pause` — `rust/src/state_ops_resolve.rs:5483-5495`

Both fire **only the just-cast source's own** `etb_effects`, inline,
no stack push, no event predicate, no observation by other permanents.
Section 3.1 covers the four Python-incompatible properties.

### Helpers ready to consume

- `bf_iter_etb_sorted(state)` — `rust/src/bf_iter.rs:61` (CE5
  closure introduced this; future-trigger-emitter is one of its
  documented consumers per the module docstring at lines 12-16).

---

## Slice 1 completion notice (landed)

`feature/etb-trigger-slice-1` shipped the substrate listed in §6.1:

- `Event` enum (`Enters` wired; `Dies` / `Cast` / `Attacks` /
  `DealsDamage` declared but parser raises loudly on register so
  callers can't stamp triggers that never fire) — `rust/src/cards.rs`.
- `Predicate` algebra: `Always`, `SourceIsSelf`, `SourceIsCreature`,
  `Not(Box<Predicate>)`, `And(Box<Predicate>, Box<Predicate>)`.
  Minimum to express the audit's §5.4 Example A Panharmonicon-shape
  probe (`SourceIsCreature AND NOT SourceIsSelf`) plus the canonical
  IsSelf-enters shape. Richer predicates (HasSubtype, IsLand, etc.)
  follow in Slice 3+.
- `TriggeredAbility { event, predicate, effect, once_per_turn }`
  struct + `CardPrinting.triggered_abilities: Vec<TriggeredAbility>`
  field (defaults to empty when the registry dict omits it —
  back-compat shape for every pre-Slice-1 caller).
- `StackItemKind` discriminant + `TriggerPayload { effect,
  ability_index }` on `StackItem` (lower-churn variant of the
  audit's enum proposal — pre-Slice-1 readers of
  `item.source_obj_id` / `item.controller` keep working unchanged).
- `dispatch_event(state, Event, subject_id)` walker
  (`rust/src/state_ops_resolve.rs`) — snapshots
  `bf_iter_etb_sorted(state)` at entry, walks every printing's
  triggered_abilities, evaluates predicate, pushes matching firings
  via `push_triggered_ability`. Slice 1 dispatches only `Enters`;
  the parser surface keeps that contract in lockstep.
- `push_triggered_ability` helper (same file).
- Once-per-turn ledger on `GameState.triggered_this_turn:
  HashSet<(u32, u32)>` (cleared at `cleanup_step_for_active_player`).
  Substrate-only in Slice 1 — no Slice 1 test fixture exercises the
  gate (the IsSelf shape fires at most once per permanent's life).
- One wiring point: `resolve_top_of_stack` (and `_pause` variant)
  fires `dispatch_event(Event::Enters, source_id)` AFTER the legacy
  inline `etb_effects` loop and AFTER popping the resolving spell's
  stack item. Pop-then-dispatch matters: the trigger goes on top of
  the now-empty stack and resolves LIFO on the next call to
  `resolve_top_of_stack`.

Slice 1 substrate smoke (`tests_rust/test_triggers.py`, 11 tests,
459 LOC): parser surface (defaults, valid kinds, raises on unwired
events / unknown predicates); end-to-end IsSelf draw on cast-resolve;
end-to-end Panharmonicon-shape "another creature enters" probe;
negative-case regression that "another creature" doesn't fire on
the source's own ETB; cleanup-step ledger clear shape.

**Out of scope for Slice 1 (queued for Slice 2+):**

- Fan-out from the other 11 ETB-stamping sites (§4). Today only the
  cast-and-resolve path (RS1) is wired.
- Bridging `etb_effects` into the predicate path (synthesize
  `TriggeredAbility { event=Enters, predicate=SourceIsSelf,
  effect=... }` per `etb_effects` entry at registry-load time, retire
  the inline hatch).
- Smoke-harness `cross_engine.py:370-384` registry-dict wiring —
  needs a `triggered_abilities` key so the harness can actually
  exercise the new substrate against the Python engine for CE19
  closure.
- Richer Predicate variants (HasSubtype, IsLand, IsArtifact,
  Controlled, Subject) — needed for landfall / artifact-enters /
  Kavu-shape predicates from `cards/parser/triggers.py:603-1266`.
- Target selection on triggers that need it (DealDamage with an
  AnyPlayer / AnyCreature target) — today the trigger resolver
  re-uses `apply_effect`'s deferred targeting (defending player /
  first defender bf object); Slice 4+ adds push-time target picking
  + fizzle check.
- Wider `Event` variant coverage (Dies, Cast, Attacks, DealsDamage).
- Panharmonicon-shape `etb_trigger_multiplier`.
- Combat-damage aggregator dedup.

LOC: ~715 production + ~459 tests.

---

## Slice 2 completion notice (landed)

`feature/etb-trigger-slice-2` shipped piece (1) of the Slice 1 prep
notes — fan out `dispatch_event(Event::Enters, ...)` to the 11 other
ETB-stamping sites in §4 — via a deferred-dispatch queue rather than
inline calls.

**Pattern** (`docs/RUST_PARITY_GAPS.md` I47): every bf-entry site
pushes the entered permanent's id onto
`GameState.pending_etb_dispatches: Vec<u32>` instead of dispatching
inline. The surrounding caller (the resolver in spell-resolve cases,
or the bf-entry primitive itself in standalone-method cases) drains
the queue via `state_ops_resolve::drain_pending_etb_dispatches` AFTER
the resolving slot leaves the stack. The deferred path keeps
`apply_effect` stack-quiet, so the resolver's `pop()` always drains
the resolving slot regardless of how many permanents entered.

**Sites wired**:

- RS2 `state_ops_resolve.rs` (`Effect::SearchLibraryForBasicLandTapped`)
- RS3 `state_ops_resolve.rs` (`Effect::ReturnCreatureFromYourGraveyardToBattlefield`)
- RS4 `state_ops_resolve.rs` (`Effect::CreateToken` block allocator; one push per token)
- RS5 `state_ops_resolve.rs` (`Effect::CreateTokenCopyOfTargetCreatureYouControl`)
- RS6 `state_ops_resolve.rs` (`Effect::ReturnAllCreaturesFromYourGraveyardToBattlefield` mass reanim)
- RS7 `state_ops_resolve.rs::return_paired_exiles_for` (signature flipped from `i32` to `PyResult<i32>`)
- RS8 `state_ops_resolve.rs::register_and_inject_object` (test fixture; bf-targets only)
- RS9 `state_ops_zones.rs::move_object` (signature flipped from `bool` to `PyResult<bool>`; bf-targets only)
- RS10 `state_ops_zones.rs::move_object_from_graveyard_to_battlefield`
- RS11 `state_ops_cast.rs::move_from_hand_to_battlefield` (routes `play_land` + `cast_creature` no-stack primitive)
- RS12 `state_ops_decisions.rs::resolve_manifest_dread_to_battlefield`

Plus the queue substrate itself: `GameState.pending_etb_dispatches`
field + `drain_pending_etb_dispatches` helper in `state_ops_resolve.rs`.

**Regression tests** in `tests_rust/test_triggers.py` (13 new RS-site
tests + 1 once-per-turn end-to-end test, on top of Slice 1's 11):
each RS-site has a self-ETB-draw probe verifying the trigger fires +
the controller draws a card; RS9 has an extra negative-case guard
pinning that non-bf moves stay silent; the once-per-turn ledger test
pins suppress + cleanup-reset.

**Rust gate**: 1902/1902 pass (vs Slice 1's 1885 baseline).

**Out of scope for Slice 2 (queued for Slice 3+):**

- Piece (2) from Slice 1's prep notes — bridge legacy `etb_effects`
  into the predicate path by synthesizing
  `TriggeredAbility { event=Enters, predicate=SourceIsSelf,
  effect=... }` per `etb_effects` entry at registry-load time, then
  retire the inline `etb_effects` hatch in `resolve_top_of_stack` /
  `_pause`. Slice 2 leaves the inline hatch in place — double-fire
  surface is dormant today (no EoE printing carries both shapes).
- Smoke-harness `cross_engine.py` registry-dict wiring for
  `triggered_abilities`.
- Richer Predicate variants (HasSubtype, IsLand, IsArtifact,
  Controlled, Subject).
- Wider Event variants (Dies, Cast, Attacks, DealsDamage).
- Panharmonicon-shape `etb_trigger_multiplier`.
