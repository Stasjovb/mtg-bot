# Multi-gated tail tractability scout (2026-05-24)

**Lane:** `feature/multi-gated-tail-tractability-scout-2026-05-24-p1`
(Worker A in the 2026-05-24 parallel-agent dispatch).

**Trigger.** Today's session shipped three substrate closures — Singularity
Rupture (`31c823c8`), Warping Wail Cycle 4 (`8e47c1bf`), Coordinated
Clobbering Cycle 2b (`ef9abb8d`) — plus a 12-card measurement-attribution
sweep (`a9829787`, COVERED → PROBED). Worker B was simultaneously in
flight on Archenemy's Charm, which when it lands will close the last
single-gated `effect_uncovered` card and drain the cheap single-gated
lane. This scout's question: **with the single-gated frontier bottoming
out, what is the cheapest tractable closure in the 65-card BLOCKED-
subsystem multi-gated tail, and is any of them a 1-cycle closure on the
sibling-substrate shapes that today's closures shipped?**

## TL;DR

**No 1-cycle closures exist on the multi-gated tail.** Every shipped
substrate today (resolve-time self-scan, Phase-4 per-mode binder admit,
Phase-6 3-slot grammar, modal envelope, Eldrazi-Scion creature-token-AA
bridge) is narrowly admit-gated and does NOT compose with the multi-gated
cards' OTHER gates (carrier-activated-abilities, station-spacecraft,
non-safe triggered ability, warp+static, etc.). All five sibling
precedents shipped today close specific shapes that the multi-gated tail
does not match.

**Live single-gated row (12 cards) is all DEFERRED / honest-stop / in
flight:** 5 cost_reduction (DEFERRED — guaranteed cross-engine
divergence), 2 nonbasic_land (DEFERRED — clone + activated-abilities
substrates), 1 station_spacecraft (DEFERRED — §2-decline), 1 unclassified
(DEFERRED — Leyline of Mutation, two new substrates needed for 0-deck
leverage), 2 static_layered (Soulrager / Wickerfolk — NOT in EoE snapshot,
need data refresh), and Archenemy's Charm (4,498 decks; **Worker B in
flight 2026-05-24**).

**Loader-admits sanity check on the 65 BLOCKED cards: 0 are
loader-admitted.** The 2026-05-24 post-flip reclassification scout
(`a9829787`) already confirmed the admit-gate is in sync with the metric
helper and no measurement-attribution gap remains in the BLOCKED tier.

**Recommendation:** the multi-gated tail is genuinely multi-cycle
territory. Worker B's Archenemy's Charm flip + the 12-card sweep is the
high-leverage work for today. **Next Worker A dispatch should pivot to
either (a) a fresh substrate cycle in the X-value or control-change-UEOT
families (both have shipped C1-C5 substrate and have demonstrated
amortization across multiple cards) or (b) the highest-leverage
multi-cycle candidate from the ranking below.** The ranking is by total
closure scope, NOT by 1-cycle tractability — no candidate is 1-cycle.

## Live snapshot (re-run of `scripts/scout_r58_subsystem_attribution.py`)

```
# subsystem-gated attribution — 65 cards
subsystem                                  #cards  1gate  multi  decks(tot)  decks(1g)
Cost-reduction substrate                        5      5      0       53648      53648
Non-basic land substrate                        2      2      0        7688       7688
warp_cost (declined cost-mechanic)              6      0      6       39844          0
Kicker / Impending cost                         1      0      1        6090          0
Static / layered abilities                      9      2      7       21051          0
Station / Spacecraft                            8      1      7       41281       5938
Aura-attachment substrate                       3      0      3        2783          0
Rooms / doors                                   3      0      3           0          0
Planeswalker loyalty                            1      0      1        2311          0
Carrier activated abilities                    30      0     30       34470          0
Effect-uncovered                               49      1     48      109449       4286
Unclassified (residual)                         1      1      0           0          0
Non-safe triggered ability                     23      0     23       82976          0
```

Reconcile: 65 = 12 single-gated + 53 multi-gated. Sum of per-subsystem
single-gated equals 12. (The inventory's "13 single-gated" claim is
stale — it counted Singularity Rupture and/or Warping Wail before today's
closures landed.)

## What today's shipped substrates actually admit

| Today's closure | Shape shipped | Why it doesn't compose with multi-gated tail |
|---|---|---|
| Singularity Rupture (`31c823c8`) | Resolve-time self-scan, `Effect::SingularityRuptureEffect` field-free unit variant | Bespoke — closes Singularity Rupture ONLY. Reusable shape, but no other card has this Effect class (`grep` confirms 0 sharers). |
| Warping Wail Cycle 4 (`8e47c1bf`) | Per-mode binder admit-gate flip in ModalChooseOne envelope; Eldrazi-Scion creature-token-AA bridge widen | Per-mode binder is ModalChooseOne-specific. Eldrazi-Scion AA bridge is **token-only**, gated on EXACTLY `sacrifice_self` cost + `add_mana(C)`. None of the 30 Carrier-AA cards are tokens — all are real permanents (Lavaclaw Reaches, Mystifying Maze, Reflecting Pool, etc.). |
| Coordinated Clobbering Cycle 2b (`ef9abb8d`) | Phase-6 3-slot StackItem grammar + admit arm + per-card real-EoE probe | Closes the `(2, 3)` heterogeneous 3-slot grammar; no other card in the 65 has this slot-grammar shape. |
| Phase-4 modal admit / `not slot_kinds` permissive disjunct (Singularity Rupture + WW) | Modal envelope widen | Narrowly gated on the modal-chooseone admit predicate; the multi-gated effect_uncovered cards are not modal. |

The five sibling precedents the dispatch listed are real, but each
narrowly admits a specific shape. The 65-card multi-gated tail does not
share these shapes by inspection.

## Ranked top-5 multi-cycle candidates (closure-cost estimates)

Ranked by **decks ÷ cycles** with sibling-amortization discounts applied.
Per-card resolve bodies + gating shapes were verified via the source
walker (`mtg_bot.cards.source.get_active_source().get_printings()`) and
the live scout's per-card attribution dict (`gates`,
`missing_effect_classes`).

### #1 — Codecracker Hound (22,144 decks, ~3 cycles)

* **Gates:** `effect_uncovered + warp_cost + nonsafe_triggered_ability`.
* **Resolve body:** `TriggeredAbility(event=ENTERS, predicate=IsSelf,
  effect=LookAtTopTwoSplitHandGraveyard)`.
* **Closure scope:**
  * **C1:** New `Effect::LookAtTopTwoSplitHandGraveyard` Rust variant +
    parse + `to_pydict` + resolve + the agent-driven 2-card destinations
    choice (split between hand and graveyard) — this needs a new
    `PendingDecision` shape because both engines must make the same
    deterministic-first pick under the no-agent harness, but a real
    agent gets a per-card 2-way choice. Mirrors the sibling shape of
    today's CC C2a heterogeneous-slot grammar but for a non-spell
    decision channel.
  * **C2:** Add the trigger to the `_python_ta_to_safe_dict` safe-set
    (one new `_SAFE_TRIGGERS` entry + recognizer arm). Today's safe-set
    already admits ENTERS+IsSelf with 8 leaf effects (draw_cards /
    gain_life / scry_n / surveil / mill / create_token /
    create_token_tapped / return_target_permanent); a 9th leaf
    `look_at_top_two_split_hand_graveyard` is a single-line widen ONCE
    C1's PendingDecision shape lands.
  * **C3:** Admit-set pin bump + per-card real-EoE probe + cross-engine
    byte-equal driving the parsed printing through both engines (one
    warp-cast lifecycle + one normal-cast lifecycle).
* **Sibling discount:** warp_cost substrate is paid (Phase 1+1.5+2+3
  shipped); nonsafe_triggered_ability collapses automatically once the
  trigger admit lands; effect_uncovered is the only genuinely new piece.
  Cycles **3** if the PendingDecision shape is novel, **2** if it
  amortizes against an existing decision channel.

### #2 — Anticausal Vestige (6,900 decks, ~3 cycles)

* **Gates:** `effect_uncovered + warp_cost + nonsafe_triggered_ability`.
* **Resolve body:** `TriggeredAbility(event=LEAVES_BATTLEFIELD,
  predicate=IsHost, effect=AnticausalVestigeLeavesEffect)`.
* **Closure scope:**
  * **C1:** New `Effect::AnticausalVestigeLeavesEffect` Rust variant
    (bespoke). Per the inventory the Python class is non-trivial.
  * **C2:** Widen `_python_ta_to_safe_dict` event gate to admit
    `LEAVES_BATTLEFIELD` (currently ENTERS/DIES/ATTACKS/BECOMES_TAPPED
    only). This is a one-disjunct widen but it has §2 gating
    implications across every safe-trigger-using card.
  * **C3:** Admit-set pin + cross-engine probe + warp-cast lifecycle.
* **Sibling discount:** warp substrate is paid; the LEAVES_BATTLEFIELD
  event widen is genuinely new (no card has yet needed it).

### #3 — Memorial Team Leader (6,229 decks, ~2-3 cycles) — TIES with Starfield Vocalist + Exalted Sunborn + Loading Zone

* **Gates:** `warp_cost + static_abilities_layered`.
* **Resolve body:** `StaticAbility(scope=other_creatures_you_control,
  ContinuousModifier(layer=7, PowerToughnessBonus(p=1, t=0)),
  condition=DuringYourTurn())`.
* **Closure scope:** Static substrate Phase 1+2+3+3.5 has shipped, but
  the admitted shapes are narrow:
  * Phase 1: layer-6 keyword-only anthem grants (Tannuk).
  * Phase 2: `grants_creature_spells_uncounterable` flag (Frenzied
    Baloth).
  * Phase 3: SELF-scope conditional bonus (Brightspear / Cloudsculpt /
    Gravblade).
  * Phase 3.5: `controlled_artifact_entered_this_turn` Condition +
    layer-6 keyword removal (Mechan Shieldmate).
  * **Phase 4 (not shipped):** `other_creatures_you_control`-scope
    layer-7 P/T bonus with `DuringYourTurn()` condition. This is a
    NEW shape — different scope (Phase 3's SELF-scope vs Phase 4's
    OTHER), different layer (3.5's layer-6 keyword vs 4's layer-7 P/T),
    different condition (3.5's `controlled_artifact_entered_this_turn`
    vs 4's `DuringYourTurn`).
  * **Closure cost:** 1-2 cycles for the Phase 4 substrate
    (per-other-creature layer-7 reader + DuringYourTurn condition
    dispatcher) + 1 cycle for the warp-composition probe.
* **Sibling discount:** warp substrate is paid; the Phase-4 static
  substrate amortizes against Starfield Vocalist (5,822 decks; same
  warp+static gates, but its static is a `ReplacementEffect` on
  `TRIGGERED_ABILITY_TRIGGERS` — wholly different shape, no amortize),
  Exalted Sunborn (2,452 decks; `ReplacementEffect` on
  `WOULD_CREATE_TOKEN` — wholly different shape, no amortize), Loading
  Zone (859 decks; `ReplacementEffect` on `WOULD_PLACE_COUNTER` — no
  amortize). The warp+static row is **diffuse on the static half**
  despite being uniform on the warp half. Memorial Team Leader's
  Phase-4 anthem-other-scope-conditional substrate is its own slice.

### #4 — Lumen-Class Frigate (5,851 decks, ~2-3 cycles)

* **Gates:** `station_spacecraft + static_abilities_layered`.
* **Resolve body:** `StaticAbility(scope=other_creatures_you_control,
  ContinuousModifier(layer=7, PowerToughnessBonus(p=1, t=1)),
  tier_threshold=2), station_threshold=12`.
* **Closure scope:** Same Phase-4 substrate as Memorial Team Leader
  (anthem-other-scope-layer-7 P/T bonus) BUT with a
  `tier_threshold=2` Spacecraft-charge gate AND a `station_threshold=12`
  Spacecraft-only requirement. The Station/Spacecraft substrate is
  documented DEFERRED in the inventory (§2-declined, sprawling). Cycles
  estimate is high because it crosses two declined-substrate rows.

### #5 — Larval Scoutlander (17,718 decks, ~3-4 cycles)

* **Gates:** `effect_uncovered + station_spacecraft +
  nonsafe_triggered_ability`.
* **Resolve body:** `TriggeredAbility(event=ENTERS, predicate=IsSelf,
  effect=OptionalSacLandOrLanderForBasicLandRamp)` + `station_threshold=7`.
* **Closure scope:** New bespoke Effect + a "may"-gate decision
  channel + ramp-from-library substrate + the §5-deferred
  Station/Spacecraft substrate cost. The 17,718 decks figure is
  attractive but the closure crosses Station/Spacecraft, which is
  §2-declined.

## Why no card scores 1-cycle

Today's three substrate closures each landed by composing a NEW Rust
Effect variant + (typically) a new bridge arm + a new admit-set pin.
That's the unit of work. For a card to flip in 1 cycle on a SIBLING
substrate, the card's Effect class must already be Rust-covered. By
inspection of `missing_effect_classes` in the live scout:

* 1 of 65 cards has no missing Effect classes from its single-gated
  attribution (Memorial Team Leader / Starfield Vocalist / Exalted
  Sunborn / Loading Zone / Lumen-Class Frigate — the warp+static and
  station+static rows). These are **NOT 1-cycle** because each requires
  Phase-4 static-substrate work (a new scope+layer+condition triple not
  yet admitted).
* 64 of 65 cards have at least one missing Effect class. Each missing
  Effect class is a unique Rust variant — `grep` confirms ZERO Effect
  classes are shared across the 65 cards' `missing_effect_classes`
  rows. The diffuseness is real.

The Carrier-AA row (30 cards) is structurally DEFERRED: the
Carrier-AA bridge today is **token-only** (Lander shape, Eldrazi-Scion
shape) — `_token_with_safe_activated_ability_card_def` and the
Cycle-3 Warping Wail extension. Real permanent Carrier-AA cards
(Lavaclaw Reaches, Wandering Fumarole, Mystifying Maze, Reflecting Pool,
Meteor Crater, Nesting Grounds, Terrain Generator, Mirrorpool,
Thespian's Stage, Scavenger Grounds, Petrified Field, Deserted Temple,
Sliver Overlord, Grove of the Burnwillows, Swarmyard, Ancient Tomb,
plus 14 more) need a per-permanent Carrier-AA bridge that does NOT
exist today. The 2026-05-21 inventory documents this row as sprawling
DEFERRED.

## Recommended next Worker A dispatch

Per the dispatch's §9 honest-stop protocol: **the multi-gated tail is
genuinely multi-cycle territory, recommend pivoting.** Three specific
suggestions ranked by leverage-per-cycle:

1. **Codecracker Hound multi-cycle closure (22,144 decks, ~3 cycles).**
   The highest single-card leverage in the multi-gated tail. The C1
   PendingDecision-shape Effect substrate is the load-bearing piece;
   C2 and C3 are mechanical. The warp_cost composition is paid. The
   sibling shape closest to today's CC C2a is the heterogeneous
   slot-grammar for the LookAtTopTwo split decision.

2. **Phase-4 static-substrate closure for Memorial Team Leader (6,229
   decks, ~2 cycles).** This is the cheapest closure on the BLOCKED
   tier IF the Phase-4 static substrate amortizes across the four
   warp+static cards. The first ~70% of the static body (layer-7
   other-creature P/T bonus) covers Memorial Team Leader; the
   `DuringYourTurn` condition dispatcher is the remaining gate. The
   sibling discount: warp_cost substrate is paid.

3. **Anticausal Vestige (6,900 decks, ~3 cycles).** Closure widens the
   `_python_ta_to_safe_dict` event surface to LEAVES_BATTLEFIELD — a
   genuinely new sibling shape that future cards in this event family
   will amortize against (the inventory's §6 sub-gates surface lists
   this as a candidate sub-shape).

**Default recommendation:** Codecracker Hound. Highest single-card
leverage; the C1 substrate's PendingDecision shape is the load-bearing
piece; C2 and C3 are mechanical follow-on work; and the LookAtTopTwo
split shape is a meaningful sibling substrate that future cards
(`LookAtTopTwoSplitHandGraveyard` is novel today but cards in the
"split top-N to two zones" family are common across MTG sets — the
substrate will amortize at the cross-set boundary).

**Scope sanity:** today's session already shipped 3 substrate closures +
12-card sweep + (after Worker B lands) 1 more flip. That is well
within a heavy session. The right move is to consolidate the day's
gains, not force a 4th closure on a tail that has bottomed out for
1-cycle work.

## Cross-references

* Live scout: re-run
  `PYTHONPATH=src ../../mtg-bot/.venv-py313/Scripts/python.exe
  scripts/scout_r58_subsystem_attribution.py` (the source of truth).
* Today's closures: `31c823c8` (Singularity Rupture), `8e47c1bf`
  (Warping Wail C4), `ef9abb8d` (Coordinated Clobbering C2b),
  `a9829787` (post-flip reclassification scout).
* `docs/SUBSYSTEM_BLOCKED_LEVERAGE_INVENTORY.md` §§3-6 — the canonical
  per-subsystem closure plans (deferred rationale for cost_reduction /
  non-basic land / Station-Spacecraft / Carrier-AA / Rooms / Loyalty /
  Kicker).
* `docs/POOL_PARITY.md` — headline tier counts at this HEAD: PROBED
  299 / covered 111 / BLOCKED-subsystem 65 / pool total 475.
