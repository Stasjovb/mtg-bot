# Subsystem-blocked tier — leverage inventory + closure sequence

A focused, current-snapshot **synthesis** of the BLOCKED-subsystem-gated
tier (143 cards post-warp_cost-Phase-3, the **only** non-empty BLOCKED
tier on `docs/POOL_PARITY.md` after the 2026-05-19/20 massive-closure
session). This doc is **not the authoritative living roadmap** —
`docs/SUBSYSTEM_ROADMAP.md` is that, with its full cycle-by-cycle
orchestrator history. This doc is the short "what should I grind next,
why, in what order" reference.

**Snapshot HEAD:** post-`feature/warp-cost-phase-3` merge (round-83,
2026-05-20: 3 warp single-gated cards flipped PROBED, blocked tier
146→143). Predecessor was `62222ffe` (post-tractor-beam cast-time
auto-resolve, post-static-abilities Phase 3, post-Aura Phase 3/S4,
post-dauntless-scrapbot closure).
**Source data:** `scripts/scout_r58_subsystem_attribution.py` (re-runnable;
the same attribution helper `measure_pool_parity` imports, so this doc
and `POOL_PARITY.md` cannot disagree on the count).
**Tier under analysis:** `BLOCKED — subsystem-gated / Effect-uncovered`
(146 cards). The other two BLOCKED tiers were both driven to **0** this
session — see `docs/BLOCKED_GENUINELY_MISSING_INVENTORY.md` for the
historical itemization (genuinely_missing 2→0 via Pain for All + cast-
from-exile substrate; blocked_non_effect 2→0 via Tractor Beam + Dauntless
Scrapbot).

## 0. This session's progress summary (2026-05-19/20)

The session that started after `ce564786` (the original inventory)
shipped ~22 substrate / closure merges. The original inventory's top-5
recommendations are now overwhelmingly **executed**, not pending.

### Top-5-recommendations status (from `ce564786`)

| Original rec | Status | Closure commit(s) |
|---|---|---|
| (1) Static / layered abilities — close 8 single-gated | **PARTIAL** — Phases 1+2+3 SHIPPED; 4 of 8 single-gated cards closed (Tannuk Steadfast Second, Frenzied Baloth, Brightspear Zealot, Cloudsculpt Technician, Gravblade Heavy) | `3a7c483c` Phase 1 / `9ccefe08` Phase 2 / `ddd93684` Phase 3 |
| (2) Dynamic-P/T formula — Harmonious Grovestrider | **PARTIAL** — substrate LANDED; Grovestrider PROBED end-to-end; ward-rider on real printing kept it loader-gated, but the formula-substrate single-gate it cited is closed | `6a8b6402` |
| (3) Aura Phase 2 (S2 control-changing) | **SHIPPED** — Duskmourn admit + Tractor Beam reduce | `643163c6`, plus S2 extension `d4ceecc5` (Tractor Beam) |
| (4) Aura Phase 3 (S4 triggered) | **SHIPPED** — Pain for All admit substrate end-to-end | `35ede8b0` |
| (5) Effect-uncovered per-card drain | continuing (probe batches AAAA-GGGG landed in parallel; +11 PROBED) | `5063e8e3`, `93ea4057`, `1a06d714`, … `7c66225e` |

### Other major closures this session

* **Pain for All** (`60fea01b`) — closed last BLOCKED-genuinely_missing
  Aura residue via S4 substrate.
* **Tractor Beam** (`d4ceecc5` + `62222ffe`) — closed last
  BLOCKED-blocked_non_effect Aura residue + bench-admit relaxed at cast
  time.
* **Dauntless Scrapbot** (`3af7edea`) — closed last
  BLOCKED-blocked_non_effect carrier (`ExileEachOpponentsGraveyard`).
* **Lightstall Inquisitor** (`9c41ad08` + `00d01937`) — cast-from-exile
  substrate end-to-end + worklist reconciliation.
* **Aura Phase 2 S2.5** (`46d8d393`) — layer-7b set-base-PT reader fold
  (Lignify-shape Auras).
* **Multi-Aura set-base-PT timestamp interleaving** (`959d0766`) — CR
  613.3b ordering for stacked set-PT Auras.
* **Static abilities Phase 2** (`9ccefe08`) —
  `grants_creature_spells_uncounterable` flag (Frenzied Baloth).
* **Static abilities Phase 3** (`ddd93684`) — SELF-scope conditional
  bonus (Brightspear Zealot + Cloudsculpt + Gravblade Heavy).
* **House Cartographer** (`ef8e9d0c`) — bespoke survival effect closed.
* **Sothera + Requiem Monolith** (`5f56ac56`) — 6-Effect-variant slice.
* **Roving Actuator** (`444ae155`) — slice 18 ETB substrate.
* **Meltstrider's Resolve** (`9155ea5c`) — slice 19 Aura-Fight scaffold.
* **All 3 broader-archetype residual axes closed** (`5bca387a` and
  predecessors) — cumulative 23/1500 → 0 divergences; v13 post-session
  resweep (`3e37882f`) 300/300 PASS regression-verifies every substrate.

### POOL_PARITY headline before → after this session

```
                                                  ce564786  →  62222ffe  →  post-warp-P3
PROBED                                                221         232          235
covered-by-construction                                95          97           97
BLOCKED — genuinely_missing                             3           0            0
BLOCKED — blocked_non_effect                            2           0            0
BLOCKED — subsystem-gated                             154         146          143
```

Subsystem-gated dropped by 11 total; **both itemized BLOCKED tiers
reached 0**. The 143 tail is now the *only* non-empty BLOCKED tier.
Round-83 (2026-05-20: warp_cost Phase 3) flipped Red Tiger Mechan,
Bygone Colossus, Timeline Culler → PROBED on the existing Phase 1/1.5/2
substrate via two measurement-attribution fixes (loader_admits widen +
`_parity`-named probe aliases).

## 1. Headline (current state)

* **143 cards** are subsystem-gated; **68 single-gated**, **75 multi-gated**
  (post warp_cost Phase 3 round-83: the 3 single-gated warp cards — Red
  Tiger Mechan, Bygone Colossus, Timeline Culler — flipped to PROBED).
  The 75 multi-gated total is unchanged.
* **15 taxonomy gates** in the scout's `_gates_for_loader_card`. Of
  those, **13 currently bind ≥1 card** — `BECOMES_TAPPED event` /
  `Planeswalker loyalty` / `Rooms / doors` / `Kicker / Impending` bind
  cards but **0 single-gated**; `Carrier activated abilities` and
  `Non-safe triggered ability` bind 30 / 43 cards but **0 single-gated**.
  These are co-blocker rows, not levers.
* A card may trip multiple gates; `#cards` does NOT sum to 146. The
  honest leverage column remains `decks(1g)`.

## 2. Subsystems by closure leverage (refreshed)

Columns are independent. **Tractability** is the roadmap classification;
**Closure scope** is this doc's per-substrate cost estimate, **revised**
to reflect what substrate already exists post-session.

| Subsystem | #cards | 1gate | decks(1g) | Tractability | Closure scope | Status (post-session) |
|---|---:|---:|---:|---|---|---|
| Static / layered abilities | 15 | 8 | 34,526 | sprawling | small-medium per remaining card (Phases 1+2+3 substrate built) | **PARTIAL** — 4 of 8 single-gated closed; 4 remain (Mechan Shieldmate + 3 not in EoE snapshot) |
| Non-basic land substrate | 23 | 23 | 34,575 | medium | small-medium for ~5 cards realizable; 18 deferred behind sibling substrates | DEFERRED (unchanged) |
| Cost-reduction substrate | 5 | 5 | 53,648 | medium | large (true Rust multi-round; Condition-grammar port) | DEFERRED (unchanged; `docs/COST_REDUCTION_SUBSTRATE_PLAN.md`) |
| warp_cost | 7 | 0 | 0 | medium | Phase 1/1.5/2/3 **SHIPPED** — 3 single-gated Phase-3 cards flipped to PROBED (round-83, 2026-05-20: `feature/warp-cost-phase-3`) | **CLOSED for single-gated** — 7 multi-gated tail remains (static/effect-uncovered co-gates) |
| Dynamic-P/T formula | 1 | 1 | unknown | medium | small-medium per formula (substrate landed `6a8b6402`) | **PARTIAL** — Grovestrider closed; Cosmogoyf remains (different formula shape) |
| Station / Spacecraft | 8 | 1 | 5,938 | sprawling | large (§2-declined) | DEFERRED (unchanged) |
| Carrier activated abilities | 30 | 0 | 0 | sprawling | sprawling (per-card; 0 single-gated) | DEFERRED (unchanged) |
| Aura-attachment substrate | 7 | 4 | 633 | sprawling | Phase 1/2/2.5/3 LANDED; **Phase 4 only** (S3 token-replacement Moonlit Meditation 633 decks) | **PARTIAL** — sub-shape coverage near-complete; lane 3 in flight |
| BECOMES_TAPPED event | 2 | 0 | 0 | contained | small (event bridge) — 0 single-gated | DEFERRED (unchanged) |
| Ward (declined) | dropped | — | — | medium | — | row gone from scout (0-binding) |
| Kicker / Impending | 1 | 0 | 0 | medium | medium — 0 single-gated | DEFERRED (unchanged) |
| Rooms / doors | 3 | 0 | 0 | sprawling | large — 0 single-gated, 0 decks | DEFERRED (unchanged) |
| Planeswalker loyalty | 1 | 0 | 0 | sprawling | large — 0 single-gated | DEFERRED (unchanged) |
| Effect-uncovered (diffuse tail) | 94 | 24 | 103,349 | diffuse | per-card | per-card lane continues |
| Non-safe triggered ability | 43 | 0 | 0 | diffuse | per-event-shape — 0 single-gated | DEFERRED (unchanged) |
| Unclassified (honest residual) | 2 | 2 | 12 | diffuse | per-card hand re-walk | OPEN (unchanged — Deafening Silence + Leyline of Mutation) |

**Reconciliation:** 143 subsystem-gated = 68 single-gated + 75
multi-gated; `1gate` column sums to 68 (post-warp_cost Phase 3 round-83;
the warp_cost row is now 7/0/0 — only the multi-gated tail survives).

## 3. The remaining highest-leverage levers (re-ranked)

Filtered to substrates that are **(a) named-and-bounded** and **(b) not
already fully closed**. Re-ranked by **decks(1g) ÷ remaining-closure-
scope** with the substrate already-paid-for discounts the session
introduced.

### (1) Static / layered abilities — Phase 3.5 (Mechan Shieldmate) + EoE-refresh cards

**Status: highest-leverage remaining named lever.** Phases 1+2+3 SHIPPED
(`3a7c483c` / `9ccefe08` / `ddd93684`); 4 of the 8 originally-single-gated
cards are closed. The remaining single-gated cards under this gate row are:

* **Mechan Shieldmate** — `ControlledArtifactEnteredThisTurn` Condition
  + `RemoveKeyword(defender)` layer-6 payload. Sibling lane 1
  (`feature/mechan-shieldmate-closure`) is in flight; will add the
  Condition tag to the Phase-3 dispatch and the keyword-remove fold to
  the Rust layer-6 reader. **~1 cycle of slice work** on top of the
  shipped Phase-3 substrate.
* **Rampaging Soulrager** / **Wildfire Wickerfolk** / **Tannuk Steadfast
  Second** (NB: the 8th name in the original list — Tannuk is *already*
  bridge-admitted by Phase 1 anthem-grant; the remaining 3 either are
  not in the current EoE snapshot or carry condition tags
  (`UnlockedDoorsAmongRoomsAtLeast` / `DeliriumActive`) outside the
  Phase-3 two-tag table. Each is a ~1 cycle slice that adds its tag.

**Multi-gated 7 (unchanged):** Exalted Sunborn, Loading Zone, Memorial
Team Leader, Starfield Vocalist (warp+static); Lumen-Class Frigate
(Station+static); Nexus of Fate (effect-uncovered+nonsafe-trig+static);
Green Sun's Zenith (effect-uncovered+static).

* **Why it's still high leverage:** the substrate's been built; each
  remaining card is now small-medium scope, not the original
  medium-large.
* **Closure scope per remaining card:** small-medium (existing layer
  machinery + 1 new Condition tag).
* **Sequencing:** Mechan Shieldmate (lane 1 in flight) first; per-
  Condition slices for Rampaging Soulrager / Wildfire Wickerfolk are
  blocked on an EoE snapshot refresh.

### (2) Aura-attachment substrate — Phase 4 only

Phases 1+2+2.5+3 SHIPPED. The 7-card subsystem-gated row's residue:

* **Single-gated 4:** Duskmourn's Domination, Frantic Strength, Moonlit
  Meditation, Shardmage's Rescue. Phase 2 S2 (`643163c6`) admits
  Duskmourn; Phase 1 admits Frantic Strength + Shardmage's Rescue if
  flash widening lands. **Moonlit Meditation (633 decks) needs Phase 4
  S3 replacement-effect substrate — the only un-shipped Aura phase.**
* **Multi-gated 3:** Chorale of the Void, Cracked Skull, Sporogenic
  Infection — all S4-shape, all multi-gated with effect-uncovered +
  nonsafe-trig + Aura. Phase 3 S4 substrate (`35ede8b0`) is the Aura
  half; per-card Effect-uncovered closures + nonsafe-trigger event
  bridges are the remaining halves.

Sibling lane 3 (`feature/aura-phase-4`) is in flight on Phase 4 S3
(Moonlit Meditation token-replacement).

* **Why it's still on the list:** the remaining Phase 4 phase is small-
  medium (token-replacement-effect substrate on top of the already-paid
  attach substrate), and 633 decks of single-gate leverage is real if
  small.
* **Closure scope:** small-medium (Phase 4 S3) + per-card S4 closures
  for the multi-gated residue (medium each, gated by Effect-uncovered
  lane progress).

### (3) Effect-uncovered diffuse tail — per-card lane

Not a substrate; per-card closures land 1 card at a time. The cheap
Tier-A single-card lane is **EXHAUSTED**. Remaining **24 single-gated**
members are Tier-C-ish (combat-shape divergence, larger Rust per card):
Archenemy's Charm, Beyond the Quiet, Close Encounter, Coordinated
Clobbering, Cut Propulsion, Darkness, Devastating Onslaught, Drill Too
Deep, Emergency Eject, Exorcise, Invasive Maneuvers, Mutinous Massacre,
Pull Through the Weft, Reroute Systems, Ruinous Rampage, Scour for
Scrap, Scout for Survivors, Shattered Wings, Singularity Rupture,
Systems Override, Terminal Velocity, Vengeful Possession, Warping Wail,
Zero Point Ballad.

* **Per-card cost:** 1-3 cycles each.
* **Pool-flip per cycle:** 1 card + its deck count.
* **Cumulative reach:** largest row but incremental cadence.

### (4) Dynamic-P/T formula — Cosmogoyf only

Substrate landed `6a8b6402`; Harmonious Grovestrider closed end-to-end
(now PROBED at `tests/test_parity_smoke.py::*_harmonious_grovestrider_*`).
Remaining single-gated: **Cosmogoyf** (different formula shape — card
type counting in graveyards). ~1-2 cycle slice on the same dispatch
table substrate (extend the Rust formula-key arm + bridge admit).

### (5) warp_cost remaining-3 — Phase 3 — **SHIPPED** (round-83, 2026-05-20)

Phase 1/1.5/2/3 **all SHIPPED**. The 3 Phase-3 cards — **Bygone Colossus,
Red Tiger Mechan, Timeline Culler** — flipped from
BLOCKED-subsystem-gated → PROBED on `feature/warp-cost-phase-3` (round-83,
2026-05-20). Phases 1+1.5+2 had already shipped the substrate end-to-end
(CardDef warp fields + Rust `CardPrinting.warp_cost` +
`Effect::WarpExileSelf` + `cast_creature_warp` life-debit + graveyard-warp
loop + the bridge filter widen at `trajectory.py:5552`); Phase 3 closed
the two measurement-attribution gaps that kept the 3 cards in the BLOCKED
tier:

1. `scripts/measure_pool_parity.py:loader_admits` did not consult
   `_printing_is_bridge_pure_warp_creature` — widened to include it,
   matching the production-deck loader.
2. The full warp lifecycle probes used `_byte_equal` suffixes invisible
   to the `_smoke_probed_cards` slug-keyed scanner — added 3 thin
   `_parity`-named delegators in `tests/test_parity_smoke.py` so each
   card earns PROBED credit via the canonical lifecycle byte-equality
   evidence.

Net: PROBED tier 232 → 235; warp_cost row 10/3/15,436 → 7/0/0
(multi-gated tail unchanged — Starfield Vocalist + Memorial Team Leader +
Exalted Sunborn + Loading Zone gated also on static_abilities; Codecracker
Hound + Anticausal Vestige + Possibility Technician also on
effect_uncovered+nonsafe_trigger). Bridging warp alone never flipped
those 7 — they need their **other** gate to land first.

**This was lever #2 in the §4 closure sequence; CLOSED.**

## 4. Recommended closure sequence (top 5, post-refresh)

Sorted by **decks(1g) ÷ cycles-remaining**, post-session-substrate:

| # | Lever | Decks(1g) | Cycles | Decks/cycle | Notes |
|---|---|---:|---:|---:|---|
| 1 | **Static / layered abilities — Mechan Shieldmate (Phase 3.5)** | (single card in the 8) | 1 | — | Sibling lane 1 in flight; substrate is paid for |
| ~~2~~ | ~~**warp_cost Phase 3**~~ | ~~15,436~~ | — | — | **CLOSED round-83 (2026-05-20)** — `feature/warp-cost-phase-3`; +3 PROBED |
| 2 | **Dynamic-P/T formula — Cosmogoyf** | small | 1-2 | — | Same dispatch table substrate; cheapest after Static |
| 3 | **Aura Phase 4 S3 — Moonlit Meditation** | 633 | 2-3 (token-replacement substrate) | ~210 | Sibling lane 3 in flight |
| 4 | **Effect-uncovered per-card drain — next 3-5 cheap single-gated** | varies (~5-15k cumulative) | 3-5 | ~3,000 | Cheaper Tier-A lane exhausted; remainder is Tier-C |

**Sequencing rationale:**

* The original #1 (Static abilities) is **now small-cost-per-card** —
  the substrate cost was paid in the session. Mechan Shieldmate
  closes the last EoE single-gated card on the layer table.
* **warp_cost moved up** to #2 because its substrate is similarly paid
  for and the deck count is the largest among 1-2-cycle slices.
* **Aura Phase 4 dropped to #4** because attach substrate is paid but
  S3 token-replacement is its own small substrate.
* **Effect-uncovered lane** continues in parallel; pace is bounded by
  per-card Rust scope, not substrate availability.

## 5. Substrates explicitly OFF the top-5

* **Cost-reduction substrate (5 cards, 53,648 single-gate decks).**
  Highest single-gate deck count of any named row, but
  `docs/COST_REDUCTION_SUBSTRATE_PLAN.md` documents the bridge-correct
  realizable yield is **0 in any near-term clean slice** — admitting
  any of the 5 ships a guaranteed inter-engine divergence. Large
  multi-round Rust substrate. Keep deferred.
* **Non-basic land substrate remainder (18 cards).** Behind sibling
  substrates (Station / activated / clone); not a clean slice.
* **Station / Spacecraft (8 cards, 5,938 decks).** Documented
  §2-decline; large substrate.
* **Carrier activated abilities (30 cards, 0 single-gated).** All
  multi-gated — closing this gate alone flips zero cards.
* **Non-safe triggered ability (43 cards, 0 single-gated).** Per-event-
  shape frontier; co-blocker row, not a lever.
* **Rooms / doors, Planeswalker loyalty, Kicker, BECOMES_TAPPED.** All
  have 0 single-gated members; closing the gate alone flips zero cards.
* **Unclassified (2 cards — Deafening Silence, Leyline of Mutation).**
  Owe a hand re-walk per `SUBSYSTEM_ROADMAP.md`; flagged for the next
  residue cadence, not a sequencing lever.

## 6. New sub-gates revealed this session

The substrate closures revealed (or made tractable) a handful of
sub-gates that the original `ce564786` inventory didn't surface:

* **Static abilities Phase 3.5 — keyword-removal layer-6 fold +
  `ControlledArtifactEnteredThisTurn` Condition.** Surfaced by Mechan
  Shieldmate honest-stop in the Phase 3 merge (`ddd93684`); lane 1 in
  flight.
* **Aura Phase 4 S3 — token-replacement-effect substrate.** Surfaced
  by Moonlit Meditation as the only un-shipped Aura sub-shape.
* **Aura S4 multi-gate composition** — Chorale of the Void / Cracked
  Skull / Sporogenic Infection each need their Aura half (shipped
  `35ede8b0`) + Effect-uncovered closure + nonsafe-trigger event bridge.
  These are now exactly that cleanly-decomposed.
* **warp_cost Phase 3 — CLOSED round-83 (2026-05-20).** The 3 Phase-3
  carriers (Bygone Colossus, Red Tiger Mechan, Timeline Culler) flipped
  to PROBED on `feature/warp-cost-phase-3`. The Phase 1/1.5/2 substrate
  was the real lift; Phase 3 turned out to be two measurement-
  attribution fixes (widen `loader_admits` to include
  `_printing_is_bridge_pure_warp_creature` + add 3 `_parity`-named probe
  aliases that delegate to the existing canonical lifecycle probes), not
  the "small grammar extension" the original Phase-3 scoping had
  anticipated. Honest finding: the substrate had already shipped end-
  to-end; only the metric-side wiring was missing.

None of these are wholly new subsystems; they are sub-shapes of
existing substrates that the session's substrate-builds clarified.

## 7. Cross-references

* **`docs/SUBSYSTEM_ROADMAP.md`** — authoritative living roadmap +
  full cycle-by-cycle history. Every claim here traces back to a row
  in the roadmap.
* **`docs/AURA_ATTACHMENT_SUBSTRATE_PLAN.md`** — 4-phase Aura plan;
  Phases 1+2+2.5+3 LANDED, Phase 4 (lane 3) in flight.
* **`docs/BLOCKED_GENUINELY_MISSING_INVENTORY.md`** — historical
  itemization of the now-empty genuinely_missing + blocked_non_effect
  tiers. Read together with this doc to understand how the residue
  was retired.
* **`docs/POOL_PARITY.md`** — headline tier table; this doc partitions
  its `subsystem-gated` row.
* **`docs/residue_worklist.json`** — per-card residue source of truth
  (21 closed entries, 0 genuinely_missing, 0 blocked_non_effect).
* **`docs/COST_REDUCTION_SUBSTRATE_PLAN.md`,
  `docs/WARP_COST_SUBSTRATE_PLAN.md`,
  `docs/NONBASIC_LAND_SUBSTRATE_PLAN.md`** — the §2 verify-first
  scoping audits referenced in §3-5.

## 8. Caveats

* **Effect+bridge ≠ full-game-trajectory parity.** Same headline caveat
  as `docs/POOL_PARITY.md`. The session's broader-archetype-sweep
  v13 resweep (`3e37882f`, 300/300 PASS, 0 divergences) is the
  strongest signal yet that the substrate work translates to real-game
  byte-equality on the loader-admitted subset, but it does not extend
  to the gated remainder (the loader-admit predicate is the gate).
* **Scope estimates are calibrated from cycles 1-15+ + this session's
  ~22 merges.** Re-estimate at each closure.
* **Deck counts** are 17lands EoE archetype-build appearances. The
  single-gate `decks(1g)` column is the honest leverage signal.
* **The scout is the source of truth.** Re-run
  `PYTHONPATH=src ../../mtg-bot/.venv-py313/Scripts/python.exe
  scripts/scout_r58_subsystem_attribution.py` to refresh; if this doc
  and the scout disagree, the scout wins, refresh this doc.
