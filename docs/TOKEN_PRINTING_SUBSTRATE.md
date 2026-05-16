# Token-printing pre-registration substrate (Phase 6)

Round-49 N1 design doc + Phase 1 landing record.

This is the standing gate that blocks the entire `CreateToken`-shaped
EoE death/ETB cluster (Galactic Wayfarer, Edge Rover, Beamsaw
Prospector, Gravpack Monoist, Biomechan Engineer, Glacier Godmaw, …)
from the production-deck loader. It is the round-47-handoff
"Token-registration substrate for create_token rider variants"
longer-term item, scoped down into independently-shippable phases per
the campaign's substrate-only-landing discipline (round-37 DDDD /
round-43 / round-44 / round-47 / round-48 precedent).

---

## 1. How token printings flow today (manual per-probe)

### 1.1 The bridge arm (already exists, round-3 / round-21 / round-43)

`cross_engine._ta_dict_to_python_effect` has a `"create_token"` arm
(and a sister `"create_token_each_player"` arm). Rust's
`Effect::CreateToken { count, token_printing_id }` (rust/src/cards.rs:219)
carries a `token_printing_id: u32` that indexes the **Rust** `Registry`.
The Python side has no equivalent global registry, so the bridge
resolves the pid through a **module-global probe-time map**:

```python
# cross_engine.py
_TOKEN_PRINTING_BY_PID: dict[int, CardPrinting] = {}
def register_token_printing(pid: int, py_printing: CardPrinting) -> None: ...
def clear_token_printings() -> None: ...
```

The `create_token` arm does `_TOKEN_PRINTING_BY_PID[eff_dict["token_printing_id"]]`
and raises `KeyError` with a clear hint if the probe forgot to register.

### 1.2 The Rust registry pid model

`Registry.register_printing(dict)` (cards.rs:7172) is append-only:
`id = self.printings.len()`. So pids are assigned **sequentially in
registration order**. In `cross_engine.build_rust_state`, the loop
walks `spec.card_defs` in tuple order and registers each, building
`name_to_pid`. Token printings are **not** deck cards, so today they
are never in `card_defs` — a probe must register the token directly
on a fresh `Registry` and hardcode its pid.

### 1.3 The manual per-probe pattern (test_cross_engine_etb_triggers.py)

Every existing token-creation probe does this by hand:

```python
clear_token_printings()
soldier = make_token_creature(name=..., power=1, toughness=1, subtypes=("Soldier",))
register_token_printing(7, soldier)                       # pid 7 chosen by hand
e = _ta_dict_to_python_effect(
    {"kind": "create_token", "count": 1, "token_printing_id": 7})
```

The pid (`7`, `11`, …) is a magic constant the probe author picks; the
probe never builds a real matched game from a `DeckSpec`, it just
exercises the bridge arm in isolation. `test_rust_parser_accepts_
create_token_in_triggered_ability` separately pins that Rust's
`parse_triggered_ability` accepts a `create_token` effect referencing
a pre-registered inner-token pid.

**Nothing wires this into `setup_matched_game_from_real_decks`.** The
production-deck loader's gate is `_python_ta_to_safe_dict`, whose
elif-chain has arms for `DrawCards / GainLife / Scry / PumpSelfUntilEOT
/ Surveil / SelfMill` — **no `CreateToken` arm**. Every EoE
CreateToken carrier therefore returns `None` from the recognizer and
is dropped by `_printing_is_bridge_simple_creature`.

### 1.4 What the loader needs to seat token printings automatically

For the loader to admit a CreateToken carrier, four things must line
up deterministically (no hand-picked pid):

1. **`_python_ta_to_safe_dict` must recognize the carrier's
   `CreateToken` trigger** and emit a `{"kind": "create_token",
   "count": N, "token_printing_id": <pid>}` dict — but the pid is not
   known at recognizer time (it depends on the final `card_defs`
   tuple).
2. **The token printing must be registered in the Rust `Registry`**
   at a known position so `token_printing_id` is valid. Cleanest:
   add the token as an extra synthetic `CardDef` appended to
   `spec.card_defs` but **absent from both libraries** (registered,
   never drawn/played). Its pid = its index in `card_defs`.
3. **The carrier's trigger dict's `token_printing_id` must equal that
   index.** So the loader must assign the token a deterministic
   `card_defs` slot and rewrite the carrier trigger to point at it.
4. **The Python `_TOKEN_PRINTING_BY_PID` map must carry
   `{pid: python_CardPrinting}`** before `build_python_state`
   materializes the carrier's triggered ability (the bridge resolves
   the pid during printing materialization).

The phased plan (§4) introduces a small loader-owned indirection
("token registry pass") that does (2)+(3)+(4) atomically from a
recognizer that emits a **symbolic** token reference, so the pid is
assigned exactly once when the union `card_defs` tuple is frozen.

---

## 2. The CreateToken rider shapes in the EoE pool

`scripts/scout_r49_create_token_shapes.py` walks every EoE printing's
parsed `triggered_abilities` for a `CreateToken`-family effect and
cross-references the 17lands deck pool (129,996 decks; the
HANDOFF "5000 archetypes" figure is stale). 34 EoE carriers carry a
CreateToken-family trigger. The rider-shape histogram:

```
26  count=1  each_player=False tapped=False attacking=False sched=False   <- the dominant shape
 3  count=2  each_player=False tapped=False attacking=False sched=False
 2  {} (CreateTokenAndAttachSelf — different class, no rider fields)
 1  count=1  tapped=True                                                  (Gravpack Monoist)
 1  count=1  each_player=True                                             (Edge Rover)
 1  CreateTokenPerMulticoloredPermanent  tapped=True
```

### 2.1 The fixed-single-token shape (Phase 1's target)

`event=ENTERS|DIES, predicate=IsSelf, CreateToken(count=1,
each_player=False, tapped=False, attacking=False,
schedule_end_of_combat_sacrifice=False)`. This is the
Doomed-Traveler / Wedgelight-Rammer "When ~ enters/dies, create one
fixed token" shape — the single most common CreateToken shape in
both EoE and the broader MTG pool. The bridge's existing
`create_token` arm carries **exactly** this rider profile
(`CreateToken(token_printing=…, count=…)`; all rider flags at
dataclass defaults — Rust's two-field variant has no mirror for
`tapped`/`each_player`/`attacking`/`sched`).

### 2.2 The token shapes the cluster produces

| Token | Carriers (deck#) | Token shape | Bridge-tractable? |
|---|---|---|---|
| **Lander** | Galactic Wayfarer (33,469), Beamsaw Prospector (24,310), Edge Rover (15,271), Biomechan Engineer (15,038), Glacier Godmaw (16,323), … (9 carriers) | `Artifact — Lander`, **1 activated ability** (`{2}, Sac: SearchLibraryForBasicLandTapped`) | **NO** — token-activated-ability sub-substrate needed (Phase 3) |
| **Robot** | Wedgelight Rammer (6,674), Gravpack Monoist (25,252, but `tapped=True`), Eusocial Engineering, Mechan Assembler, … | `Artifact Creature — Robot`, **2/2 vanilla** | YES, but multi-card-type token + non-creature carrier needed |
| **Human Soldier** | Knight Luminary (24,020, **warp**), Honored Knight-Captain (10,470, **activated ability**) | `Creature — Human Soldier`, **1/1 vanilla** | YES (token is single-type vanilla); carriers blocked on other gates |
| **Glimmer** | Tunnel Surveyor (**0 decks**), Grand Entryway (0), Glimmerlight (0) | `Enchantment Creature — Glimmer`, **1/1 vanilla** | YES (multi-type vanilla token) |
| Gremlin / Drone / Insect / Sliver / Demon / Treasure / Munitions | various, low/zero deck# | mixed | per-shape |

### 2.3 What Phase 1 ADMITS and what it DECLINES (§2 silent-mistranslation discipline)

**ADMIT (Phase 1, the cross-engine-correct subset):**

- `ENTERS / IsSelf / CreateToken(count=1, all riders default)` on a
  bridge-simple **Creature** carrier, **token = a vanilla token**
  (non-None P/T, no keywords, no activated/triggered/static abilities;
  card-types may be multi — `Artifact Creature`, `Enchantment
  Creature`). This is the exact rider profile the existing
  `create_token` bridge arm round-trips bit-for-bit (both engines:
  `count` tokens, controller = trigger's resolved controller, all
  rider flags off). Rust's resolve arm carries the I81
  controller-of-effect fix; Python's `CreateToken.resolve` has always
  been correct on this surface. **Substrate-only landing today** (see
  §3).

**DECLINE (each is a silent-mistranslation path until its own phase):**

- **Non-vanilla token (`Lander`)** — the token printing carries an
  activated ability (`{2}, Sac: SearchLibraryForBasicLandTapped`).
  The token CardDef the loader synthesizes can't carry that ability
  through the bridge (CardDef has no activated-ability field; the
  `SearchLibraryForBasicLandTapped` effect + its library-search agent
  seating would have to round-trip too). Admitting a Lander whose
  activated ability silently vanishes on the bridge = exactly the
  §2 silent-mistranslation class. **DECLINED → Phase 3.** This is the
  reason Galactic Wayfarer / Beamsaw Prospector / Edge Rover /
  Biomechan Engineer / Glacier Godmaw — the entire high-deck-count
  Lander cluster — are NOT admitted by Phase 1.
- **`tapped=True` rider (Gravpack Monoist)** — Rust's
  `Effect::CreateToken { count, token_printing_id }` has **no
  `tapped` field**. Python's `CreateToken.tapped=True` would enter
  the token tapped; the bridge constructs the bare Rust variant which
  enters it untapped. Byte-divergent post-resolve `tapped` flag on
  the token object. **DECLINED → Phase 4** (needs a Rust
  `CreateTokenTapped` sister variant or a `tapped` field, mirroring
  the closed-vocab sister-variant convention).
- **`each_player=True` rider (Edge Rover)** — has a *separate*
  bridge arm (`create_token_each_player`) and Rust variant
  (`Effect::CreateTokenEachPlayer`), already shipped (round-43). But
  Edge Rover's token is **Lander** (non-vanilla) so it's double-blocked;
  and the loader-side recognizer + auto-registration for the
  each-player shape is its own phase. **DECLINED → Phase 5** (rides on
  Phase 3's Lander work + an each-player recognizer arm).
- **`count=2` (Overlord of the Mistmoors, Thrumming Hivepool)** —
  `count` IS carried by the bridge; these are blocked on OTHER gates
  (Overlord: 0 decks + ATTACKS-trigger sister; Thrumming Hivepool:
  non-creature + 2 static abilities). Not a mistranslation; just not
  Phase 1's carrier shape. Pre-positioned (the recognizer emits
  `count` verbatim).
- **`CreateTokenAndAttachSelf` / `CreateTokenPerMulticoloredPermanent`
  / `CreateTokenCopyOfTargetCreatureYouControl`** — different Python
  effect classes with no matching `create_token` rider profile;
  `CreateTokenCopyOf…` already has its own bridge arm (round-21
  cross-controller slice) but is target-pick-shaped (no loader agent
  seating). **DECLINED → out of this substrate's scope.**
- **Non-creature carriers (Wedgelight Rammer = `Artifact —
  Spacecraft`, Eusocial Engineering = `Enchantment`)** — the loader
  filter is creature-only. Wedgelight Rammer additionally has
  `station_threshold=9` (the **Station** subsystem, an entire
  unmodeled mechanic — admitting it would silently drop Station, a
  §2 violation) and a non-creature `power=3/toughness=4`. **DECLINED
  → Phase 2** (a separate "bridge-simple non-creature permanent"
  filter path that explicitly declines Station/room/loyalty rather
  than silently dropping them).

---

## 3. Why Phase 1 is substrate-only (the EoE-pool delta is empty today)

Cross-referencing §2.2 + §2.3 against the 17lands pool:

- Every **high-deck-count creature carrier** of the fixed-single-token
  shape produces a **Lander** token (non-vanilla → DECLINED §2.3) or
  carries a declined rider (`tapped=True` Gravpack Monoist) or a
  declined carrier feature (warp on Knight Luminary, activated
  ability on Honored Knight-Captain).
- The **only** clean creature carrier with a vanilla token + all
  other gates clean is **Tunnel Surveyor** (Glimmer 1/1, multi-type
  vanilla, ENTERS+IsSelf, single trigger, no warp/activated/etc.) —
  and Tunnel Surveyor appears in **0** of 129,996 17lands decks
  (it's a low-pick limited card, in the Scryfall EoE set but absent
  from the deck pool — the same situation round-43 hit with Fear of
  Surveillance and round-44/47 hit on their substrate-only landings).

So Phase 1 ships the substrate + recognizer + auto-registration +
synthetic cross-engine pins + a synthetic real-game probe + a
reject→admit conversion of the relevant reject-path pins, **admitting
zero real EoE cards today**. This is the documented round-37 DDDD /
round-43 / round-44 / round-47 (DIES+draw) / round-48 substrate-only
landing pattern. The real-card payoff lands in Phase 2/3 (below).
Shipping a Lander whose activated ability silently vanishes to clear
a deck-delta number would be precisely the round-38-E1 / §2 mistake
the campaign exists to avoid.

---

## 4. Phased implementation plan

Each phase is independently shippable and gate-green on its own.

### Phase 1 — fixed-single-vanilla-token substrate (THIS ROUND, round-49)

**Scope.** `ENTERS / IsSelf / CreateToken(count=N, no riders)` on a
bridge-simple creature carrier, token = vanilla (any card-types,
non-None P/T, no abilities/keywords).

**Mechanism.**
- New `_SAFE_TRIGGERS` entry `("enters", "source_is_self",
  "create_token")` + `_SAFE_EFFECT_KEYS["create_token"]`.
- New `_python_ta_to_safe_dict` arm: recognize a `CreateToken` whose
  `token_printing` is vanilla and whose riders are all default; emit
  a dict carrying a **symbolic** token reference
  (`{"kind": "create_token", "count": N, "_token_carddef": <CardDef>}`)
  — NOT a numeric pid yet. A new `_token_vanilla_card_def(printing)`
  builds the token CardDef from the token printing.
- New loader pass in `production_deck_to_deckspec`
  (`_seat_token_printings`): after the union `card_defs` dict is
  frozen, for every carrier CardDef carrying a symbolic create_token
  trigger, append the token CardDef to `card_defs` (deduped by name,
  absent from both libraries), compute its final pid (= its index in
  the `build_rust_state` registration order), rewrite the trigger
  dict to `{"kind": "create_token", "count": N,
  "token_printing_id": pid}`, and call
  `cross_engine.register_token_printing(pid, <python token printing>)`.
- `_printing_is_bridge_simple_creature` gains a vanilla-token check
  inside the existing triggered-ability loop (a CreateToken trigger
  whose token is non-vanilla → drop, same as any other unsafe TA).

**Landing.** Substrate-only (EoE-pool delta = 0, §3). 3–5 synthetic
cross-engine bridge pins + 1 synthetic real-game ENTERS+create_token
trajectory probe + reject-path pins (non-vanilla-token / tapped-rider
/ each-player-rider stay dropped). Pre-positions the cluster.

### Phase 2 — bridge-simple non-creature permanent filter path

Add `_printing_is_bridge_simple_noncreature_permanent` admitting
Artifact/Enchantment permanents that are otherwise bridge-clean,
**explicitly declining** `station_threshold` / `room_halves` /
`loyalty` / `dynamic_pt` rather than silently dropping them. This
admits non-creature CreateToken carriers (still gated on the token
being vanilla per Phase 1). Real-card delta still small until Phase 3
(most non-creature carriers also make Lander). Independent of Phase 3.

### Phase 3 — Lander-token-activated-ability sub-substrate (the big payoff)

The Lander token's `{2}, Sac: SearchLibraryForBasicLandTapped`
activated ability must round-trip cross-engine: CardDef gains an
optional `token_activated_abilities` field; the bridge threads it to
Rust's token printing; the `SearchLibraryForBasicLandTapped` effect
already has a cross-engine bridge arm (round-30 supertypes slice
references it) — verify its library-search agent seating on the
trajectory walk. **This is the phase that flips the real
high-deck-count cluster drop→admit:** Galactic Wayfarer (33,469),
Beamsaw Prospector (24,310), Edge Rover (15,271 — also needs Phase 5),
Biomechan Engineer, Glacier Godmaw, Bioengineered Future. Largest
single EoE-pool-delta lever in the whole substrate.

### Phase 4 — `tapped` rider sister variant

Rust `Effect::CreateTokenTapped { count, token_printing_id }` (or a
`tapped: bool` field per the closed-vocab sister-variant convention),
parse/to_dict/resolve arms, bridge arm, recognizer widening. Admits
Gravpack Monoist (25,252 decks — Robot token is already vanilla, so
this is a pure-Rust + recognizer slice once Phase 1 lands). High
deck-delta, medium scope (one Rust variant). One Rust agent.

### Phase 5 — `each_player` recognizer + auto-registration arm

`create_token_each_player` bridge arm + Rust variant already exist
(round-43). This phase adds the loader-side recognizer arm + the
each-player auto-registration. Admits Edge Rover (15,271) once Phase 3
lands (Edge Rover's token is Lander).

### Phase 6 — `count`/multi-token + Overlord/Thrumming-Hivepool tail

`count=2` is already carried by the bridge; this phase clears the
remaining non-IsSelf / non-ENTERS-DIES predicates (ATTACKS-trigger
Overlord, BEGINNING_OF_UPKEEP Thrumming Hivepool) — long-tail,
lowest leverage.

---

## 5. Phase 1 landing record (round-49 N1)

- Substrate: `("enters", "source_is_self", "create_token")` in
  `_SAFE_TRIGGERS`; `_SAFE_EFFECT_KEYS["create_token"]`;
  `_python_ta_to_safe_dict` create_token arm (vanilla-token + bare-rider
  gated); `_token_vanilla_card_def`; `_seat_token_printings` loader
  pass in `production_deck_to_deckspec`;
  `_printing_is_bridge_simple_creature` vanilla-token TA check.
- EoE-pool delta: **0 real cards** (substrate-only — every real
  high-deck-count carrier is Lander/declined; Tunnel Surveyor is the
  only clean consumer and is 0-deck). Pre-positions the cluster for
  Phase 2/3.
- Tests (+11, gate **1185 → 1196**):
  - 5 cross-engine bridge pins (`test_cross_engine_etb_triggers.py`):
    recognizer admits clean vanilla-token carrier (Tunnel Surveyor);
    declines non-vanilla Lander cluster (Galactic Wayfarer / Beamsaw
    Prospector); declines tapped/each_player/attacking riders;
    `_token_vanilla_card_def` per-disqualifier gate; loader-seating
    assigns the deterministic Rust-registry pid + bridge-map
    registration + Rust Registry accepts the seated dict.
  - 1 synthetic real-game cross-engine trajectory probe
    (`test_trajectory_parity.py::test_r49_carddef_create_token_fires_on_cast_parity`):
    loader-seated DeckSpec → cast a vanilla-Robot-token maker →
    on-stack ETB create_token → token spawns byte-equal on BOTH
    engines (post-drain field-view compare clean).
  - 5 helper pins (`test_trajectory.py`): `_is_safe_trigger_dict`
    accepts post-seating shape / rejects symbolic + rider shapes;
    `_seat_token_printings` no-op fast path + shared-token dedup;
    EoE-pool-delta reject pin (Lander cluster + Gravpack Monoist
    stay dropped — the reject-path Phase 3 will later convert).
- Recommended round-50 next phase: **Phase 4** (`tapped` rider sister
  variant — pure Rust + recognizer, flips Gravpack Monoist's 25,252
  decks drop→admit; its Robot token is already vanilla so it needs no
  Phase 3 work) OR **Phase 3** (Lander activated-ability sub-substrate
  — the largest cumulative delta but the biggest scope; one dedicated
  multi-round sub-campaign).
