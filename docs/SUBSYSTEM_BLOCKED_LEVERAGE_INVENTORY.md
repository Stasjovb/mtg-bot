# Subsystem-blocked tier — leverage inventory + closure sequence

A focused, current-snapshot **synthesis** of the BLOCKED-subsystem-gated
tier (142 cards post-dynamic-pt-cosmogoyf-closure, the **only**
non-empty BLOCKED tier on `docs/POOL_PARITY.md` after the
2026-05-19/20 massive-closure session). This doc is **not the
authoritative living roadmap** — `docs/SUBSYSTEM_ROADMAP.md` is
that, with its full cycle-by-cycle orchestrator history. This doc
is the short "what should I grind next, why, in what order"
reference.

**Snapshot HEAD:** post-`feature/dynamic-pt-cosmogoyf` merge (round-84,
2026-05-20: Cosmogoyf flipped PROBED on the SAME dispatch table
substrate as round-78 Grovestrider; blocked tier 143→142).
Predecessor was `7a3a0fc9` (post-Mechan Shieldmate closure / Phase
3.5 static abilities — round-82).
**Source data:** `scripts/scout_r58_subsystem_attribution.py` (re-runnable;
the same attribution helper `measure_pool_parity` imports, so this doc
and `POOL_PARITY.md` cannot disagree on the count).
**Tier under analysis:** `BLOCKED — subsystem-gated / Effect-uncovered`
(146 cards). The other two BLOCKED tiers were both driven to **0** this
session — see `docs/BLOCKED_GENUINELY_MISSING_INVENTORY.md` for the
historical itemization (genuinely_missing 2→0 via Pain for All + cast-
from-exile substrate; blocked_non_effect 2→0 via Tractor Beam + Dauntless
Scrapbot).

### Inventory refresh + ground-truth audit (2026-05-21,
`feature/inventory-refresh-and-close-p1`)

**Headline post-refresh:** `scout_r58_subsystem_attribution` reports
**110 subsystem-gated** cards (down from the doc's body text of 128) /
**35 single-gated** (down from 53). `docs/POOL_PARITY.md` at this HEAD
reports **PROBED 279 / covered 86 / BLOCKED-subsystem 110**. The
inventory-body wording below (§0, §2 table, §3, §4, §6, §7) was
written against the `post-emergency-eject` HEAD (PROBED 269 /
BLOCKED-subsystem 118) and pre-dates the **Aura Phase 4 S3
Moonlit-Meditation closure** (`b226fbf4`: `GameObject.token_supertype_
override` + `moonlit_token_substitution` helper + loader admit widen
+ `3dc1719d` slug-credit delegator) and the four single-card
Effect-uncovered cycles that followed (`Close Encounter` cycle 2,
`Scout for Survivors`, `Scour for Scrap` slice + cycle 2,
`probe-modules-scanner-fix` audit). Per-row deltas vs the body text:

  * **Aura-attachment substrate** — now `3 cards, 0 single-gated`
    (was `7/1/633`). Moonlit Meditation PROBED; the 3 multi-gated
    residue (Chorale of the Void, Cracked Skull, Sporogenic
    Infection) remains.
  * **Effect-uncovered** — now `82 cards, 12 single-gated` (was
    `94/24/103349`). 12 cycles of per-card closures landed across
    the session.
  * **Static / layered abilities** — unchanged (`9/2/0`; the 2
    single-gated Soulrager / Wickerfolk are still EoE-snapshot-
    absent honest-stops).
  * **Non-basic land substrate** — unchanged (`13/13/8893`).
  * **All other rows** — unchanged.

**Per-card audit:** scanned the `subsystem_attribution` cards dict
against the live `classify_pool` tiering for every card the body
text claims as BLOCKED-single-gated. Confirmed-stale references
all point at **Moonlit Meditation** (now PROBED, the Aura row's
single-gated count dropped 1→0). Spot-checked Close Encounter,
Scout for Survivors, Scour for Scrap, Frantic Strength, Shardmage's
Rescue, Duskmourn's Domination, Tractor Beam, Pain for All,
Dauntless Scrapbot, Lightstall Inquisitor, Cut Propulsion,
Shattered Wings, Emergency Eject, Cosmogoyf — all PROBED or
COVERED today (no new cruft surfaced for them; their body-text
mentions are historical-narrative closures).

**Part-2 candidate walk (honest-stop):** The 12 single-gated
`effect_uncovered` candidates were each scoped against the §3
1-cycle slice shape (field-free or small-field unit Effect variant
+ parse + to_pydict + resolve + bridge leaf + admit widen). All 12
are multi-cycle when their substrate is honestly accounted for:

  * `Darkness` (43 decks, `PreventAllCombatDamageThisTurn`) —
    forbidden territory; concurrent
    `feature/darkness-cycle-1-p1` agent owns the substrate.
  * `Coordinated Clobbering` / `Mutinous Massacre` /
    `Systems Override` / `Vengeful Possession` (control-change-
    UEOT carriers) — `ThreatenTargetCreatureUEOT` /
    `controller_override` is the in-flight forbidden-territory
    substrate.
  * `Zero Point Ballad` (6041 decks) — X-value substrate + reanimation
    conditional, multi-cycle.
  * `Singularity Rupture` (5046 decks) — destroy-all + dynamic mill,
    multi-cycle.
  * `Archenemy's Charm` (4286 decks) — modal-3 with UEOT-keyword-grant
    leaf substrate (no Rust mirror today).
  * `Devastating Onslaught` (2218 decks) — X-token-copies + delayed
    sac substrate.
  * `Pull Through the Weft` (2235 decks) — 2-target nonland +
    2-target land grav-to-bf substrate, multi-cycle.
  * `Terminal Velocity` (630 decks) — multi-cycle bespoke.
  * `Warping Wail` (23 decks) — single Effect variant gap
    (`ExileTargetCreatureWithPowerOrToughnessAtMost`) BUT
    `ModalChooseOne` composer's spell-card `_leaf` table is
    missing arms for `CounterTargetSpell` AND `CreateToken`
    (only the trigger-side path admits `CreateToken` today; the
    Eldrazi Scion token's activated ability is an additional pid-
    seating concern in the spell-card admit path). Multi-cycle.

  No single 1-cycle close shipped. The doc cruft cleanup is the
  full deliverable of this lane.

### Inventory refresh (2026-05-24,
`feature/inventory-refresh-2026-05-24-p1`)

**Trigger:** today's Phase-4-permissiveness audit
(`64080991`, `docs/PHASE4_ADMIT_PERMISSIVENESS_AUDIT_2026-05-24.md`)
discovered that §3's candidate enumeration was stale by the
2026-05-22/23 closure wave — 6 of 8 candidates (Mutinous Massacre,
Systems Override, Vengeful Possession, Zero Point Ballad,
Devastating Onslaught, Terminal Velocity) had already flipped
PROBED, leaving the audit-time single-gated `effect_uncovered` set
at just 3 cards (Archenemy's Charm, Coordinated Clobbering,
Singularity Rupture). The audit recommended this refresh.
Subsequently today: **Singularity Rupture closed** (`31c823c8`;
resolve-time self-scan option-(a) per the audit; admit set 39 → 40;
PROBED 286 → 287; ~5,046 17lands decks BLOCKED → PROBED). And
**Warping Wail Cycle 4 closed** (`8e47c1bf`; per-mode binder
admit-gate flip + 3 cross-engine probes; ~23 17lands decks BLOCKED
→ PROBED). Live single-gated `effect_uncovered` is now **2 cards**
(Archenemy's Charm and Coordinated Clobbering; Singularity Rupture
gone with today's closure, Warping Wail gone with C4).

**Headline post-refresh:** `scout_r58_subsystem_attribution` reports
**66 subsystem-gated** cards (down from the 2026-05-21 refresh's
110, down further from older §0 / §2 body wording of 128) /
**13 single-gated** (down from 35 / 53). `docs/POOL_PARITY.md` at
this HEAD reports **PROBED 287 / covered 122 / BLOCKED-subsystem 66
/ pool total 475**. Per-row deltas vs. the 2026-05-21 refresh
body (which read PROBED 279 / BLOCKED-subsystem 110):

  * **Effect-uncovered** — now `50 cards, 2 single-gated` (was
    `82/12` in the 2026-05-21 refresh; `94/24` in the deeper body).
    The 2026-05-22/23 closure wave + today's Singularity Rupture and
    Warping Wail closures account for the drop. Live single-gated
    members: **Archenemy's Charm** (multi-gate cascade per-mode
    binder allowlist + missing mode-3 Effect variant + multi-target
    return arm; 3-4 cycles per audit §3 — **but see the 2026-05-24
    `archenemys-charm-cycle-1-substrate-p4` honest-stop finding in
    `docs/SEARCH_LIMITATIONS.md`**: the substrate-only-stays-declined
    invariant is unachievable because the Mode 2 substrate landing
    flips the covered+bridged tooth on its own. The closure should
    re-scope to a single-cycle flip — Mode 2 Effect substrate +
    per-mode binder allowlist widen + Mode 1 resolve-time
    multi-target self-scan — riding the same Phase-4 `not slot_kinds`
    permissive disjunct + admit-set pin bump pattern Singularity
    Rupture used today; ~4,286 17lands decks BLOCKED → PROBED in a
    single cycle) and **Coordinated Clobbering** (heterogeneous
    `(2, 3)` 3-slot grammar — positively rejected by the
    target-grammar gate before the covered+bridged tooth fires;
    needs a NEW Phase-6 admit arm; 2-3 cycles per audit §1).
  * **Warp_cost** — now `6/0/0` (was `7/0/0`). Multi-gated tail of
    6 remains; Warping Wail's prior `(1, 0)` modal `or_both=False`
    shape closed via Cycle 4's per-mode binder allowlist widen +
    the Eldrazi-Scion token-AA bridge widen from Cycle 3.
  * **Non-basic land substrate** — now `2/2/7,688` (was `13/13/8,893`
    in the 2026-05-21 refresh). Cathedral of War closed in round-N
    (`714bde69` Cathedral of War Cycle 1 — keyword-colorless tapped
    mana-only land bridge predicate); the 10 Duskmourn painlands
    closed via `744d67cf` (Non-basic land substrate Phase 2 —
    Duskmourn conditional painlands). Single-gated residue: Echoing
    Deeps + Secluded Starforge (clone substrate + activated-abilities
    substrate respectively).
  * **Static / layered abilities** — unchanged (`9/2/0`; the 2
    single-gated Soulrager / Wickerfolk are still EoE-snapshot-
    absent honest-stops).
  * **Aura-attachment substrate** — unchanged (`3/0/0`; 3 multi-gated
    residue Chorale of the Void / Cracked Skull / Sporogenic Infection
    each waiting on Effect-uncovered + nonsafe-trigger event bridges).
  * **Carrier activated abilities** — now `30 cards, 0 single-gated`
    (was `32/0/0`). Drop tracks effect-uncovered closures that
    co-resolved AA-multi-gated cards (Burgeoning, Osseous Sticktwister,
    Blade of the Swarm — all PROBED via dedicated per-card probes
    closing the effect_uncovered gate; their classifier carrier-AA
    multi-gate stays True but the card itself is PROBED).
  * **Non-safe triggered ability** — now `23 cards, 0 single-gated`
    (down from a higher prior value as the effect-uncovered closure
    chain drained multi-gated combinations). Co-blocker row only.
  * **All other rows** — minor or unchanged drift.

**Live single-gated by subsystem (the canonical "what to grind"
column, 13 cards):**

| Subsystem | Single-gated members |
|---|---|
| `cost_reduction` | Fungal Colossus, Gigastorm Titan, Lashwhip Predator, Sami Wildcat Captain, Uthros Psionicist (5) |
| `nonbasic_land_substrate` | Echoing Deeps, Secluded Starforge (2) |
| `static_abilities_layered` | Rampaging Soulrager, Wildfire Wickerfolk (2) |
| `effect_uncovered` | Archenemy's Charm, Coordinated Clobbering (2) |
| `station_spacecraft` | Galvanizing Sawship (1) |
| `unclassified` | Leyline of Mutation (1) |

All 13 single-gated cards have **0 17lands decks** at this HEAD —
the EoE-pool single-gate-leverage frontier has effectively bottomed
out. The remaining `decks(1g) = 4,286` row total tracks the
Archenemy's Charm + Coordinated Clobbering pair (the only
single-gated effect_uncovered members) at 4,286 cumulative — but per
the live attribution snapshot above those two also read 0 individual
deck count. (The aggregate column above continues to display the
historical row total from the scout's cumulative summary; the
per-card breakdown is what the live single-gated count actually
covers.) The implication: every remaining single-gated closure is
substrate-cost paid against effectively-zero in-pool leverage. The
campaign's deck-leverage signal now lives **entirely in the
multi-gated tail** (53 multi-gated cards; Cost-reduction's
53,648-deck single-gated row is the only large remaining named
single-gated row, and it's documented DEFERRED per §5 — admitting
any of the 5 ships a guaranteed cross-engine divergence).

**Per-card audit (today's two closures):**

  * **Singularity Rupture** (5,046 17lands decks). Closed via
    resolve-time self-scan option (a) per the audit's §3 verdict —
    bespoke `Effect::SingularityRuptureEffect` Rust variant + parse
    arm + `to_pydict` arm + resolve arm + cross-engine bridge dict→
    Python arm + reverse-serializer `_leaf` arm. Mirrors Scout for
    Survivors / Pull Through the Weft's deterministic-all self-scan
    pattern — no new `StackItem.target_player_ids` field required.
    The §3 candidate-list entry (line 685) and the §3 caveat block
    (lines 714-732) are historical-narrative; Singularity Rupture is
    now PROBED.
  * **Warping Wail Cycle 4** (~23 17lands decks). Closed via the
    `feature/warping-wail-cycle-4-flip-p1` lane — per-mode binder
    admit-gate flip + the Cycle-3 token-AA bridge widen (creature
    tokens with sac-self mana abilities, i.e. Eldrazi Scion) + 3
    new cross-engine probes. The §3 candidate-list entry (line 686)
    is historical-narrative; Warping Wail is now PROBED.

**Body wording NOT rewritten by this lane.** §0, §1 (headline),
§2 (subsystem table), §3 (per-lever sections), §4 (closure
sequence), §5 (substrates explicitly OFF the top-5), §6 (new
sub-gates revealed), §7 (cross-references) all continue to read
against the 2026-05-21-refresh body (`110/35`) or earlier
(`128/53`). Per the precedent established by the 2026-05-21 refresh
section above (lines 27-103), this delta-section is the canonical
"what does the body actually mean today" overlay; older row counts
in the body text below should be interpreted as historical
narrative anchored at their dated HEADs. The body's claim that
"the substrate's been built — remainder is per-card" is the
load-bearing live claim and remains correct.

**Cross-references for this refresh:**

  * `docs/PHASE4_ADMIT_PERMISSIVENESS_AUDIT_2026-05-24.md` — today's
    Phase-4 permissiveness audit (the trigger).
  * Singularity Rupture closure: commit `31c823c8` (merge);
    `c156aac2` (Rust substrate); `cf0446f6` (admit-set pin bump +
    real-EoE probe + regen docs).
  * Warping Wail Cycle 4: commit `8e47c1bf` (merge); `170f1e2b`
    (admit-gate flip closure Python + Rust); `535118a3` (admit-set
    pin updates + 3 cross-engine probes); `9c51412e` (SEARCH_
    LIMITATIONS Cycle 4 documentation).

### Post-flip reclassification scout (2026-05-24,
`feature/post-flip-reclassification-scout-2026-05-24-p1`)

**Trigger:** today's flip cadence (Singularity Rupture admit 39 →
40, Warping Wail Cycle 4 admit 40 → 41, Coordinated Clobbering
Cycle 2b admit 41 → 42) re-walked the BLOCKED tier looking for
free-PROBED candidates the bumps had silently enabled.

**Audit method.** Three checks (mirroring the 2026-05-21
`loader-admits-attribution-sweep` + `tannuk-frenzied-baloth-probes`
playbook):

  1. **`loader_admits` disjunct sync** — walked all disjuncts of the
     canonical `trajectory._filter_deck_to_bridge_supported` admit
     gate vs `scripts/measure_pool_parity.loader_admits`. **Result:
     fully in sync** (13 disjuncts both sides; today's Phase-6 CC
     3-slot + Phase-4 modal widens both fold into the existing
     `_printing_is_bridge_simple_spell` shape, no new top-level
     disjunct).
  2. **Per-card admit walk on BLOCKED tier** — for each of the 65
     BLOCKED-subsystem-gated cards, queried `loader_admits(printing)`
     AND `_printing_is_bridge_simple_spell(printing)`. **Result: 0
     BLOCKED cards return True for either.** The Phase-6 / Phase-4
     widens stayed surgical — no silent admit-gate auto-grow beyond
     the explicit per-card pins.
  3. **PROBE_MODULES registration sweep** — scanned every
     `tests/test_*.py` file for `def test_cross_engine_real_eoe_<...>
     _parity` functions with a live `get_printings().get("<Card>")`
     binding. **Result: 12 dedicated probe modules unregistered**,
     each crediting a card currently classified COVERED. Same shape
     as the 2026-05-21 loader-admits-attribution-sweep — a pure
     measurement-attribution gap (the probes exist + pass; the
     `PROBE_MODULES` tuple was never updated when they landed).

**Closure shipped.** Registered all 12 unregistered probe modules in
`PROBE_MODULES`. Each flipped its carrier COVERED → PROBED in the
metric. Net delta: **PROBED 287 → 299 (+12)**, **covered_by_
construction 123 → 111 (-12)**, BLOCKED-subsystem-gated unchanged at
65, pool total 475 unchanged. The 12 carriers, with origin commit:

  | Card | Probe module | Original closure |
  |---|---|---|
  | Coordinated Clobbering | `test_coordinated_clobbering_parity.py` | `ef9abb8d` (today, Cycle 2b) |
  | Warping Wail | `test_warping_wail_cycle_4_cross_engine.py` | `8e47c1bf` (today, Cycle 4) |
  | Arabella, Abandoned Doll | `test_arabella_abandoned_doll_parity.py` | `9c6b285c` (2026-05-23) |
  | Boilerbilges Ripper | `test_boilerbilges_ripper_parity.py` | `3e7ded06` (2026-05-22) |
  | Burgeoning | `test_burgeoning_parity.py` | `22801b36` (2026-05-23) |
  | Comet Crawler | `test_comet_crawler_parity.py` | `95423db0` (2026-05-22) |
  | Fanatic of the Harrowing | `test_fanatic_of_the_harrowing_parity.py` | `22fe18f0` (2026-05-23) |
  | Osseous Sticktwister | `test_osseous_sticktwister_parity.py` | `3e9eb260` (2026-05-23) |
  | Terminal Velocity | `test_terminal_velocity_parity.py` | `13ee8db5` (2026-05-22) |
  | Terrapact Intimidator | `test_terrapact_intimidator_parity.py` | `d3e9de5e` (2026-05-23) |
  | The Endstone | `test_endstone_parity.py` | `d39124bb` (2026-05-23) |
  | Vaultguard Trooper | `test_vaultguard_trooper_parity.py` | `23ec7e5d` (2026-05-23) |

**Engine surface change: NONE.** Zero edits to `rust/`, zero edits to
`src/mtg_bot/parity/trajectory.py` or any production module. The
sweep is pure metric-attribution: each probe was ALREADY landed +
passing; only `scripts/measure_pool_parity.PROBE_MODULES` was stale.

**Honest-stop bound.** No further free PROBED candidates surfaced
by the registration sweep. The 13 remaining COVERED-but-loader-
admitted non-land carriers (Bedhead Beastie, Cackling Slasher,
Daggermaw Megalodon, Deafening Silence, Duskmourn's Domination,
Fear of Being Hunted, Friendly Teddy, Magus of the Moon, Patched
Plaything, Piranha Fly, Shepherding Spirits, Slavering
Branchsnapper, Spectral Snatcher) each lack a dedicated `*_parity`
probe entirely (not an unregistered probe; a genuinely-absent
probe). The remaining COVERED-admitted land carriers (5 basic lands
+ Cathedral of War, the 10 Duskmourn painlands) are each
land-substrate carriers without a per-card byte-equal probe; the
land bridge runs auto-untap symmetric-drop. Each of these is the
same shape as the 2026-05-21 tannuk-baloth lane — writing a
real-EoE byte-equal probe per card — but is a real probe-authoring
lane, not a free reclassification. Honest-stopped at the
registration sweep.

### Post-AC-flip attribution sweep (2026-05-24,
`feature/post-ac-flip-attribution-sweep-p1`)

**Trigger:** the Archenemy's Charm BLOCKED → PROBED flip (merge
`7088c9bd`) shipped `tests/test_archenemys_charm_parity.py` (three
canonical `test_cross_engine_real_eoe_archenemys_charm_mode_{0,1,2}
_..._parity` functions, each driving the live EoE printing through
the bridge) but did not also update `scripts/measure_pool_parity.
PROBE_MODULES`. Identical shape to the prior `feature/post-flip-
reclassification-scout-2026-05-24-p1` 12-card sweep: a pure
measurement-attribution gap — the probe exists + passes; only the
registry was stale.

**Audit method.** Same playbook as the prior 12-card sweep:

  1. **PROBE_MODULES registration sweep** — enumerated the
     `PROBE_MODULES` tuple, listed all `tests/test_*_parity.py`
     files, computed the diff, and per-candidate ran the script's
     own `_probe_module_probed_cards` predicate (top-level
     `def test_cross_engine_real_eoe_<...>_parity` with an in-body
     `get_active_source().get_printings().get("<Card>")` binding
     on a live pool name). **Result: 1 unregistered probe module
     credits a live COVERED card** —
     `tests/test_archenemys_charm_parity.py` → `Archenemy's Charm`
     (currently COVERED at this HEAD).
  2. **Atomic Microsizer / BLOCKED-tier inconsistency check
     (bonus)** — the probe at `tests/test_atomic_microsizer_
     parity.py` IS unregistered AND the card is currently
     BLOCKED-subsystem-gated, which would have been the auditing
     red flag. **Cleared as honest:** the function body is
     `@pytest.mark.skip` (multi-cycle scaffold) with a
     `raise NotImplementedError` body — explicitly NOT a live
     probe yet, so the BLOCKED classification is correct. The
     skip reason cross-references the multi-cycle substrate
     scope in `docs/SEARCH_LIMITATIONS.md`.

**Closure shipped.** Registered the AC probe module. Flipped
Archenemy's Charm COVERED → PROBED in the metric. Net delta:

  * **PROBED 299 → 300 (+1)**
  * **covered_by_construction 112 → 111 (-1)**
  * BLOCKED-subsystem-gated unchanged at 64
  * pool total 475 unchanged

**Engine surface change: NONE.** Zero edits to `rust/`, zero
edits to `src/mtg_bot/parity/trajectory.py` or any production
module. Pure metric-attribution close — the AC probe was already
landed + passing (10/10 at this HEAD).

**Inconsistency surfaced (NOT closed in this sweep).** Six
per-card parity modules that landed since the prior sweep emit a
canonical `test_cross_engine_real_eoe_<slug>_parity` function but
do NOT satisfy the script's
`_probe_module_probed_cards` predicate because they bind the live
printing via a MODULE-LEVEL cached form
(`_PRINTINGS = get_active_source().get_printings()` at module
scope, then `_PRINTINGS.get("<Card>")` inside the probe function
body) — the predicate scans only the BOUNDED function body, so
the cached form is OUTSIDE the body it sees and the probe is not
credited even though it correctly drives the real parsed
printing. The six modules + their carrier cards (each currently
classified COVERED-by-construction, not flipped here):

  | Probe module | Card | Classification |
  |---|---|---|
  | `test_blade_of_the_swarm_parity.py` | Blade of the Swarm | COVERED |
  | `test_deafening_silence_parity.py` | Deafening Silence | COVERED |
  | `test_genemorph_imago_parity.py` | Genemorph Imago | COVERED |
  | `test_possibility_technician_parity.py` | Possibility Technician | COVERED |
  | `test_territorial_bruntar_parity.py` | Territorial Bruntar | COVERED |
  | `test_atomic_microsizer_parity.py` | Atomic Microsizer | BLOCKED-SG (probe is `@pytest.mark.skip` scaffold — body is `raise NotImplementedError`) |

Closing this would be either a separate **predicate-shape**
follow-up (widen `_probe_module_probed_cards` to also match the
module-level cached binding pattern — a real change to the
metric's evidence rule, not a registration sweep) or a
**per-probe rewrite** (inline the
`get_active_source().get_printings().get("<Card>")` call inside
each probe function body to match the existing predicate). Five
of the six (excluding Atomic Microsizer, the explicit scaffold)
would then flip COVERED → PROBED on registration. Surfaced here
as an honest-stop; the original scope of THIS sweep is the
strict-predicate-matching free flips, of which Archenemy's Charm
was the only one.

**Cross-references for this sweep:**

  * Archenemy's Charm closure: commit `7088c9bd` (merge);
    `b6a4b861` (Mode 2 Effect substrate + per-mode binder
    allowlist widen — Python + Rust engine half); `cb8ef5ed`
    (admit-set pin bump 41 → 42 + declined-modals pin updates +
    per-card real-EoE probe); `173fe19a` (regen POOL_PARITY.md +
    RUST_EFFECT_COVERAGE.md post-flip).
  * Precedent: `22a0457d` / `a9829787` (2026-05-24 — 12-card
    sweep this lane mirrors).

### Probe-module predicate widen (2026-05-24,
`feature/probe-module-predicate-widen-p1`)

**Trigger:** the prior `feature/post-ac-flip-attribution-sweep-p1`
section above surfaced — but deliberately did not close — a
predicate-shape inconsistency in
`scripts/measure_pool_parity._probe_module_probed_cards`: four
per-card parity modules hoist the printings dict to module scope
(`_PRINTINGS = get_active_source().get_printings()` at the top of
the file) and call `_PRINTINGS.get("<Card>")` inside the canonical
`test_cross_engine_real_eoe_<slug>_parity` function body. The
predicate's bounded body-scan never sees the `get_printings()` call
(it lives outside the function body), so the probes were silently
undercounted. This lane closes that gap.

**Implementation.** Widened `_probe_module_probed_cards` to ALSO
AST-walk the module: pass 1 records every module-level `Assign`
whose RHS is exactly `get_active_source().get_printings()` (or bare
`get_printings()`) and whose target(s) are `Name` nodes — those are
the printings-dict bindings; pass 2 walks each top-level
`*_parity` function body and credits `<bound>.get("Card")` Call
nodes + `<bound>["Card"]` Subscript nodes against the live pool.
The original body-scoped regex scan stays unchanged — both detectors
union into the same return set. The integrity guard test
`test_probe_module_synthetic_nonprobe_is_not_counted` continues to
pass because the widen recognizes ONLY the bare printings-dict
shape: a module-level
`_X = get_printings().get("Card")` is a per-card extraction (not a
dict binding), so the negative-control case-(4) is still correctly
excluded.

**Closure shipped.** Four per-card parity modules registered in
`PROBE_MODULES`; all four flipped COVERED → PROBED via the widened
predicate. Net delta:

  * **PROBED 300 → 304 (+4)**
  * **covered_by_construction 111 → 107 (-4)**
  * BLOCKED-subsystem-gated unchanged at 64
  * pool total 475 unchanged

The four carriers (each currently classified COVERED-by-construction
pre-widen, flipped here):

  | Probe module | Card | Pattern |
  |---|---|---|
  | `test_blade_of_the_swarm_parity.py` | Blade of the Swarm | `_PRINTINGS.get("Blade of the Swarm")` |
  | `test_genemorph_imago_parity.py` | Genemorph Imago | `_PRINTINGS.get("Genemorph Imago")` |
  | `test_possibility_technician_parity.py` | Possibility Technician | `_PRINTINGS.get("Possibility Technician")` |
  | `test_territorial_bruntar_parity.py` | Territorial Bruntar | `_PRINTINGS.get("Territorial Bruntar")` |

**Engine surface change: NONE.** Zero edits to `rust/`, zero edits
to `src/mtg_bot/parity/trajectory.py` or any production module. Pure
metric-attribution close — all four parity probes pass at this HEAD
(verified pre- and post-widen, 10/10/10/12 = 42 tests; unchanged).

**Honest-stop on Deafening Silence (the prior sweep mis-bucketed
it).** The prior `post-ac-flip-attribution-sweep` table listed
`test_deafening_silence_parity.py` alongside the four cached-binding
modules — but the actual shape is different. The Deafening Silence
parity function
(`test_cross_engine_real_eoe_deafening_silence_noncreature_block_parity`)
drives a SYNTHETIC `CardDef(name="Deafening Silence",
restricts_noncreature_spells_to_one_per_turn=True, ...)` carrier
through the bridge — it does NOT bind the live parsed printing via
`get_printings()` at all. The three
`get_active_source().get_printings().get("Deafening Silence")`
bindings in the file live in non-`*_parity` setup tests
(`test_real_deafening_silence_printing_has_restriction_flag`,
`test_deafening_silence_passes_bridge_admit_gate`,
`test_deafening_silence_passes_measure_pool_parity_loader_admits`),
all of which are correctly outside the credited `*_parity` body. The
module-scope-binding widen above (and the body-scoped scan) both
correctly fail to credit it. Flipping Deafening Silence honestly
would require either (a) a separate widen recognizing
`CardDef(name="<Card>", ...)` synthetic-carrier-driven probes as
parity probes — riskier because it would credit any `*_parity`
module that mentions a real pool card name inside a `CardDef`
constructor, expanding the inclusion bar materially — or (b) a
per-probe rewrite to bind the real printing via `get_printings()`
first (and assert it carries the relevant flag) before driving the
synthetic carrier. Deferred to a separate lane; the predicate
contract for THIS sweep is strict module-scope-cached-binding
matching, of which Deafening Silence is honestly not a member.

**Atomic Microsizer** stays correctly excluded: explicit
`@pytest.mark.skip` + `raise NotImplementedError` multi-cycle
scaffold per `docs/SEARCH_LIMITATIONS.md`.

**Sanity-gate runs (this lane):**

  * `tests/test_measure_pool_parity.py` — 31/31 passed (registry-
    consistency + the four
    `test_probe_module_synthetic_nonprobe_is_not_counted` /
    `test_tierc_synthetic_nonbar_probe_is_not_counted` integrity
    guards all still hold).
  * The four newly-credited probe modules — 42/42 passed
    (Blade 10, Genemorph 10, Possibility 10, Territorial 12).
  * The two correctly-excluded modules — 14/14 passed (Deafening
    Silence 13 — synthetic-CardDef-driven, Atomic Microsizer 7 +
    1 skip — `@pytest.mark.skip` scaffold body).
  * Spot-check of unaffected probe modules — Singularity Rupture
    11/11, Warping Wail Cycle 4 4/4, Coordinated Clobbering parity
    6/6, Archenemy's Charm parity 10/10 (all unchanged).

**Cross-references for this sweep:**

  * Predicate-shape inconsistency surfaced: prior section above
    (`feature/post-ac-flip-attribution-sweep-p1`, `2a8919d2`).
  * Precedent registration sweeps: `22a0457d` / `a9829787`
    (12-card sweep), `2a8919d2` (AC sweep).

### Post-MTL-flip + CH-C3 probe-modules sweep (2026-05-24,
`feature/post-mtl-flip-probe-modules-sweep-p1`)

**Trigger:** the just-landed Codecracker Hound Cycle 3 (`6f99bf45`)
+ Memorial Team Leader Cycle 2 (`f94fa44d`) tier flips each shipped a
new dedicated `tests/test_<card>_parity.py` probe module. Both
committing agents reported they registered their modules in
`PROBE_MODULES`; this sweep verifies the claim race-free post-merge
and audits the wider `tests/test_*_parity.py` surface for any
remaining unregistered probe modules that the
`_probe_module_probed_cards` predicate (with the 2026-05-24
`5f53835c` module-scope-binding widen) would credit.

**Audit method** (mirrors `a9829787` / `2a8919d2` / `5f53835c` prior
sweeps): enumerate `PROBE_MODULES` (currently 90 path entries; 30 are
the canonical `test_<card>_parity.py` shape), enumerate
`tests/test_*_parity.py` files (47 on disk), compute the diff (17
unregistered), and per-candidate run
`scripts.measure_pool_parity._probe_module_probed_cards` against the
live EoE pool to see what cards (if any) each unregistered module
would credit.

**Confirmed in-sync** for both today's tier-flip carriers:

  * `test_codecracker_hound_parity.py` — registered (PROBE_MODULES
    line 1121 per `6f99bf45`); credits "Codecracker Hound" via the
    module-scope `_PRINTINGS = get_active_source().get_printings()` +
    in-body `_PRINTINGS.get("Codecracker Hound")` binding the
    2026-05-24 `5f53835c` widen recognizes. Pool classifier counts CH
    at PROBED.
  * `test_memorial_team_leader_parity.py` — registered (PROBE_MODULES
    line 1142 per `f94fa44d`); credits "Memorial Team Leader" via the
    in-body `get_active_source().get_printings().get("Memorial Team
    Leader")` binding the original body-scoped scan recognizes.
    Pool classifier counts MTL at PROBED.

**Predicate-shape gap surfaced** (the load-bearing finding, deferred
to a follow-up lane): of the 17 unregistered `*_parity.py` files, 4
match the canonical `test_cross_engine_real_eoe_<slug>_parity`
function-name shape (and would be either redundant or honest-stopped)
and **10 carry genuine real-EoE cross-engine byte-equal probes that
use a non-canonical function-name suffix** the predicate's regex
(`_PROBE_FN_HEADER_RE`) does not currently match. The probes EXIST
and PASS at this HEAD; only the predicate would need to widen to
credit them.

Three new naming-pattern variants beyond today's two widens:

  * **`*_round_trip` suffix** (6 modules; all COVERED → would FLIP
    PROBED on a predicate widen recognizing the suffix):
    | Module | Card | Cross-engine fn name |
    |---|---|---|
    | `test_attack_in_the_box_parity.py` | Attack-in-the-Box | `test_cross_engine_real_eoe_attack_in_the_box_schedule_self_sac_round_trip` |
    | `test_hemosymbic_mite_parity.py` | Hemosymbic Mite | `test_cross_engine_real_eoe_hemosymbic_mite_round_trip` |
    | `test_ouroboroid_parity.py` | Ouroboroid | `test_cross_engine_real_eoe_ouroboroid_round_trip` |
    | `test_splitskin_doll_parity.py` | Splitskin Doll | `test_cross_engine_real_eoe_splitskin_doll_round_trip` |
    | `test_swarm_culler_parity.py` | Swarm Culler | `test_cross_engine_real_eoe_swarm_culler_round_trip` |
    | `test_terrasymbiosis_parity.py` | Terrasymbiosis | `test_cross_engine_real_eoe_terrasymbiosis_round_trip` |

  * **`*_byte_equal` suffix** (1 module; COVERED → would FLIP PROBED):
    | Module | Card | Cross-engine fn name |
    |---|---|---|
    | `test_enduring_curiosity_parity.py` | Enduring Curiosity | `test_cross_engine_real_eoe_enduring_curiosity_silent_noop_byte_equal` |

  * **Missing `_eoe_` infix** (1 module; COVERED → would FLIP PROBED):
    | Module | Card | Cross-engine fn name |
    |---|---|---|
    | `test_friendly_teddy_parity.py` | Friendly Teddy | `test_cross_engine_real_friendly_teddy_dies_trigger_parity` |

  * **Bench-probe shape** (1 module; COVERED → would FLIP PROBED via
    a different widen entirely — sibling to the existing in-file
    shockland-bench probe `test_r60_genuine_real_eoe_shockland_byte_
    equal_through_bench` which is currently uncredited; both bench
    probes were renamed to the canonical `..._through_bench_parity`
    suffix by `feature/cathedral-of-war-probe-rename-p1` and the
    Cathedral module was registered in `PROBE_MODULES`, flipping
    Cathedral of War COVERED -> PROBED):
    | Module | Card | Cross-engine fn name |
    |---|---|---|
    | `test_cathedral_of_war_parity.py` | Cathedral of War | `test_cross_engine_real_eoe_cathedral_of_war_through_bench_parity` |

  * **Wickerfolk Thresher** (`test_wickerfolk_thresher_parity.py`) is
    a DSK card (`test_cross_engine_real_dsk_wickerfolk_thresher_attack
    _nonland_top_parity`), not EoE pool — out of scope for the EoE
    classifier even if the predicate widened on the `_dsk_` infix.

Each of the 8 EoE candidates above is currently classified
**COVERED-by-construction** (not PROBED) — i.e. every Python
`Effect` they emit is in the covered-class set, but no
predicate-credited probe pins THAT card. Registering the modules
**without** widening the predicate would NOT flip them — the
predicate would still return the empty set for each. The closure path
is one of:

  (a) Widen `_PROBE_FN_HEADER_RE` to a broader function-name regex —
      e.g. accept `_round_trip` / `_byte_equal` / `(real|real_eoe)`
      variants alongside the canonical `_parity`. Riskier because it
      expands the inclusion bar; the integrity-guard test
      `test_probe_module_synthetic_nonprobe_is_not_counted` would
      need a new negative-control case per accepted suffix.
  (b) Per-probe rename (rename each cross-engine function to the
      canonical `..._parity` suffix). Lower-risk, narrowly scoped to
      the 8 modules; preserves the strict predicate contract.
  (c) For Cathedral of War specifically, a third widen recognizing
      the bench-probe shape (sibling to the in-file shockland probe
      precedent) — distinct from (a) / (b) and likely deferred.

This sweep deliberately does NOT close the gap (per the campaign's
"don't widen the predicate without an integrity-guard test case"
discipline). Recommended follow-up: a single lane that picks (b) for
the 8 candidates (cheaper + safer than a predicate widen), regenerates
`docs/POOL_PARITY.md`, and credits the 8 cards in one closure.

**Other unregistered modules — correctly excluded:**

  * `test_atomic_microsizer_parity.py` — `@pytest.mark.skip` +
    `raise NotImplementedError` multi-cycle scaffold per
    `docs/SEARCH_LIMITATIONS.md`. Card stays BLOCKED-subsystem-gated
    (honest). Carried over from `2a8919d2`'s honest-stop list.
  * `test_deafening_silence_parity.py` — drives a SYNTHETIC
    `CardDef(name="Deafening Silence", ...)` carrier through the
    bridge (NOT the live parsed printing). Closing this honestly
    requires a separate synthetic-CardDef-by-name widen (riskier — see
    `5f53835c`'s deferral note above). Card stays COVERED.
  * `test_gravkill_parity.py` — credits Gravkill via the body-scoped
    `get_active_source().get_printings().get("Gravkill")` binding the
    existing predicate already matches. **Gravkill is ALREADY PROBED**
    via the sibling `test_probe_covered_unprobed_c.py` smoke-style
    probe (per `2a8919d2`'s audit). Registration would be pure
    metric-truthfulness (no PROBED delta) — the PPP / multi-target-
    phase4 precedent at line 891+ would credit it; deliberately NOT
    landed here to keep this lane docs-only per the spec.
  * `test_measure_pool_parity.py` — the predicate's own unit-test
    module; not a per-card probe.
  * `test_nonbasic_land_phase2_painland_parity.py` — pool-wide painland
    sweep (`get_printings()` returns the whole dict, no per-card
    `.get("X")` binding); not a `*_parity`-named per-card probe.
  * `test_rust_bridge_parity.py` — generic Rust-bridge round-trip
    suite (no per-card binding to a specific EoE pool name).
  * `test_trajectory_parity.py` — generic trajectory-side parity
    suite (no per-card binding).

**Net delta:** ZERO tier flips landed in this lane (docs-only
honest-stop). The 8 deferred candidates remain COVERED and would
flip PROBED on the follow-up lane (counts after that hypothetical
closure: PROBED 306 → 314, covered_by_construction 107 → 99).

**Sanity-gate runs (this lane):**

  * `tests/test_measure_pool_parity.py` — 31/31 passed (registry
    consistency + the four `*_synthetic_nonprobe_is_not_counted` /
    `*_synthetic_nonbar_probe_is_not_counted` integrity guards all
    hold post-CH-C3 + MTL-C2 merges).
  * `tests/test_memorial_team_leader_parity.py` — 13/13 passed
    (today's MTL C2 flip carrier).
  * `tests/test_codecracker_hound_parity.py` — 6/6 passed
    (today's CH C3 flip carrier).

**Cross-references for this sweep:**

  * Today's MTL C2 flip: `f94fa44d`.
  * Today's CH C3 flip: `6f99bf45`.
  * Precedent attribution sweeps today: `a9829787` (12-card),
    `2a8919d2` (AC), `5f53835c` (predicate widen, +4).
  * Predicate location:
    `scripts/measure_pool_parity._probe_module_probed_cards` +
    `_probe_module_probed_cards_via_module_scope_binding` +
    `_PROBE_FN_HEADER_RE` (function-name shape — the load-bearing
    bottleneck for the 8 deferred candidates).

## 0. This session's progress summary (2026-05-19/21)

The session that started after `ce564786` (the original inventory)
shipped ~22 substrate / closure merges. The original inventory's top-5
recommendations are now overwhelmingly **executed**, not pending. The
2026-05-21 loader_admits-attribution-sweep then closed a residual
measurement gap: the metric helper at
`scripts/measure_pool_parity.loader_admits` was only consulting 4 of
the 9 disjuncts in the real production-deck loader's bridge admit
gate. Folding the remaining 5 disjuncts in + 9 `_parity`-named
delegator probes flipped 9 cards BLOCKED → PROBED (the 5 shocklands +
Brightspear / Cloudsculpt / Gravblade / Mechan Shieldmate) with NO
engine changes — a pure measurement-attribution close, same shape as
the round-83 warp_cost Phase 3 close. The 2026-05-21
tannuk-frenzied-baloth-probes follow-up lane then closed the two
COVERED-pending carriers by writing the missing genuine real-EoE
cross-engine byte-equal probes: Tannuk Steadfast Second (effective-
keyword anthem haste-grant byte-equal on the genuine printing) and
Frenzied Baloth (`spell_is_uncounterable` self-flag + battlefield-
grant `grants_creature_spells_uncounterable` static byte-equal on the
genuine printing). Both flipped COVERED → PROBED, completing the
static-abilities Phase 1+2 measurement attribution.

### Audit lane (2026-05-21, post-probe-batches-HHHH-JJJJ): negative finding

The `feature/blocked-tier-stale-claim-audit` lane, run after the
post-loader_admits-sweep+tannuk-baloth-probes work, performed a
top-to-bottom audit of the 128-card BLOCKED-subsystem tail looking
for the same shape of measurement-attribution gaps that Lane F (Aura
flash widening, +2 PROBED) and Lane H (loader_admits disjunct sweep,
+9 PROBED + 2 COVERED honest-stops) had previously surfaced. The
audit covered:

1. **Loader admit predicate completeness** — all disjuncts of the
   real `trajectory._filter_deck_to_bridge_supported` admit gate are
   mirrored in `measure_pool_parity.loader_admits`. At the time of
   the audit there were 9 disjuncts (basic land, nonbasic mana land,
   pure warp creature, simple creature, simple spell, simple aura,
   simple static-anthem creature, simple uncounterable creature,
   simple static self-conditional creature); round-85's Phase-2
   non-basic-land closure (`feature/non-basic-land-slice`) added a
   10th disjunct (`_printing_is_bridge_simple_tapped_mana_land`,
   admitting the 5 EoE Planet lands) and wired it into
   `loader_admits` in the same commit, preserving the audit's
   "no missing disjuncts" invariant.

2. **`classify_pool` internal consistency** — no card is flagged
   BLOCKED-subsystem while simultaneously being (a) loader-admitted
   and (b) all-Effects-covered: 0 of 128 BLOCKED cards would have
   qualified for COVERED under the existing tier rules. The
   precedence is honest.

3. **Per-card spot-check of single-gated cards** — verified the
   genuine Rust-side absence for each named gate row:
   - Static / layered (2 single-gated: Rampaging Soulrager,
     Wildfire Wickerfolk) — both honest-stopped at
     `rust/src/cards.rs:6831` (Conditions `UnlockedDoorsAmongRoomsAtLeast`
     and `DeliriumActive` not in dispatch table); doc wording
     "not in EoE snapshot" is technically accurate (both come from
     `data/duskmourn.json`, not `data/edge_of_eternities.json`) but
     they ARE in the parity pool — closure requires a per-Condition
     Rust slice regardless.
   - Aura row (1 single-gated: Moonlit Meditation) — genuinely
     blocked at `trajectory.py:4855` on the
     `replaces_first_tokens_with_copies` rider; the per-player
     `created_tokens_this_turn` substrate landed `4dae568e`, but the
     supertype-override mechanism that gates the loader widen is
     still in flight on `feature/aura-supertype-override`.
   - Non-basic land row (18 → 13 single-gated, post round-85) —
     `_printing_is_bridge_nonbasic_mana_land` admits the 5 shocklands
     and the new sibling `_printing_is_bridge_simple_tapped_mana_land`
     (round-85) admits the 5 Planet lands (the parser-flattened
     `enters_tapped=True` mono-color shape; the bridge drops
     `enters_tapped` on both engines — round-39 Ward / round-60
     shockland symmetric-drop precedent). The remaining 13 carry
     painland (parser-structured conditional-tapped — a real
     cross-engine divergence) / clone (Echoing Deeps) / Exalted-static
     (Cathedral of War) / activated-abilities (Secluded Starforge)
     riders that are genuinely unbridged and stay DEFERRED.
   - Cost-reduction row (5 single-gated) — verified each printing
     carries a `cost_reductions` / `external_cost_reductions` tuple
     with no Rust counterpart (substrate documented DEFERRED).
   - Station / Spacecraft 1g (Galvanizing Sawship) — genuine
     spacecraft with `station_threshold=3`; documented DEFERRED.
   - Effect-uncovered 1g spot-check (10/24 sampled) — each emits a
     distinct Python Effect class with NO Rust variant
     (`grep` confirmed against `rust/src/state_ops_resolve.rs` +
     `rust/src/cards.rs`). The diffuse tail is real.

**Conclusion: no stale claims found in the inventory body or the
classifier.** The post-loader_admits-sweep+tannuk-baloth-probes state
is honest and tight — every BLOCKED card is genuinely blocked, every
classifier decision is internally consistent. (Subsequent 2026-05-21
unclassified-residual lane: the audit DID surface a doc-level
attribution gap — the scout's `_gates_for_loader_card` enumeration
only consulted structured `static_abilities` objects, not
printing-level bool flags like
``restricts_noncreature_spells_to_one_per_turn``, so Deafening
Silence was attributed `unclassified` rather than the more honest
`static_rule_text`. The unclassified-residual lane added the new
gate row and moved Deafening Silence; Leyline of Mutation's
`unclassified` attribution is confirmed-honest by the same hand
re-walk.) The only updates the
audit produced are doc-cosmetic refreshes: the §0 before→after
table now carries the post-probe-batches-HHHH-JJJJ column (PROBED
252 → 259), and the §3(2) Aura Phase 4 S3 row + §7 cross-ref are
updated to reflect that the `feature/aura-phase-4-s3` substrate
merged `4dae568e` (consumer wire-up still gated on the supertype-
override mechanism). Headline counts unchanged.

### Top-5-recommendations status (from `ce564786`)

| Original rec | Status | Closure commit(s) |
|---|---|---|
| (1) Static / layered abilities — close 8 single-gated | **PARTIAL** — Phases 1+2+3 SHIPPED; 6 of 8 single-gated cards PROBED (Brightspear Zealot, Cloudsculpt Technician, Gravblade Heavy, Mechan Shieldmate via loader_admits sweep; Tannuk Steadfast Second, Frenzied Baloth via the tannuk-frenzied-baloth-probes follow-up) | `3a7c483c` Phase 1 / `9ccefe08` Phase 2 / `ddd93684` Phase 3 / loader_admits sweep / tannuk-frenzied-baloth-probes |
| (2) Dynamic-P/T formula — Harmonious Grovestrider | **CLOSED** — substrate LANDED round-78; Grovestrider PROBED end-to-end (ward-rider on real printing kept it loader-gated, but the formula-substrate single-gate it cited is closed). Round-84 (`feature/dynamic-pt-cosmogoyf`) extended the SAME dispatch table with the `"cosmogoyf"` arm, flipping Cosmogoyf → PROBED. Single-gated Dynamic-P/T tier now 0. | `6a8b6402` (Grovestrider) + this lane (Cosmogoyf) |
| (3) Aura Phase 2 (S2 control-changing) | **SHIPPED** — Duskmourn admit + Tractor Beam reduce | `643163c6`, plus S2 extension `d4ceecc5` (Tractor Beam) |
| (4) Aura Phase 3 (S4 triggered) | **SHIPPED** — Pain for All admit substrate end-to-end | `35ede8b0` |
| (5) Effect-uncovered per-card drain | continuing (probe batches AAAA-IIII landed in parallel; +18 PROBED) | `5063e8e3`, `93ea4057`, `1a06d714`, … `7c66225e`, … `feature/probe-batch-hhhh`, `feature/probe-batch-iiii` |

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
                                                  ce564786  →  62222ffe  →  post-warp-P3  →  post-dyn-PT-cosmo  →  post-aura-P1-attr  →  post-loader-admits-sweep  →  post-tannuk-baloth-probes  →  post-probe-batches-HHHH-JJJJ  →  post-non-basic-land-P2  →  post-cut-propulsion  →  post-shattered-wings  →  post-emergency-eject
PROBED                                                221         232          235            236                 238                    250                              252                               259                            264                       266                       267                      269
covered-by-construction                                95          97           97             97                  98                     97                               95                                88                             89                        88                        88                       88
BLOCKED — genuinely_missing                             3           0            0              0                   0                      0                                 0                                 0                              0                         0                         0                        0
BLOCKED — blocked_non_effect                            2           0            0              0                   0                      0                                 0                                 0                              0                         0                         0                        0
BLOCKED — subsystem-gated                             154         146          143            142                 139                    128                               128                               128                            122                       121                       120                      118
```

**post-emergency-eject delta (this lane):** strict **+1 PROBED /
−1 BLOCKED-subsystem-gated** (Emergency Eject, 6,291 17lands
single-gated decks per the round-58 attribution scout). Note: the
post-shattered-wings column on the snapshot table above reads
``267 / 120`` (off-by-one from the canonical
``docs/POOL_PARITY.md`` at the same HEAD which reads ``268 / 119``
— a pre-existing measurement-drift carried over from the
shattered-wings landing); the canonical post-this-lane numbers
that match ``docs/POOL_PARITY.md`` at this HEAD are PROBED ``269``
/ BLOCKED-subsystem ``118``. Genuine
Rust substrate close following the same Lander-pid carrier shape
as Seedship Impact / Orbital Plunge: new
`Effect::EmergencyEjectEffect { token_printing_id }` single-pid
variant (`rust/src/cards.rs`) + parse arm + to_pydict arm;
resolve arm in `rust/src/state_ops_resolve.rs` beside the
Seedship Impact arm (cast-time-bound target via
`current_resolve_payload_target_id`; non-land filter re-checked
at resolve per CR 608.2b; indestructible-skip on the scan; DIES
creature-gated; LEAVES + token-cease drained); the
`current_resolve_payload_target_id` self-scan fallback for
synthetic-test no-target push. Three deviations from Seedship
Impact (load-bearing for parity): (1) filter widens from
artifact-OR-enchantment to non-land permanent; (2) **no MV
gate** — Lander rider is unconditional whenever the destroy
succeeds; (3) **Lander goes to the FORMER controller of the
destroyed permanent** (NOT the source-controller — captured
BEFORE destroy from `obj.controller`). `state_ops_legal.rs::
spell_targets_satisfiable` non-land-permanent + non-
indestructible arm; cast-time `is_emergency_eject` bind in
`state_ops_cast.rs` mirroring `is_seedship_impact`. Bridged via
`cross_engine.py` `emergency_eject_effect` (drops the pid,
constructs the field-free Python
`DestroyTargetNonlandPermanentWithLanderForController`) +
`trajectory.py::_python_spell_effect_to_dict` Lander-pid leaf
emitting symbolic `_token_card_def` (resolved by the seating
pass once `"emergency_eject_effect"` is added to
`_SPELL_TOKEN_PID_KINDS`) — the {2}{W} Emergency Eject Instant
auto-joins the spell-card-bridge admit set (10→11). 8 new
probes: 6 Rust pins (opp-artifact-destroy + Lander-for-opp,
creature-destroy + unconditional Lander, enchantment-destroy +
Lander, indestructible-survives + no-Lander, Land-filtered-out +
silent fizzle, deterministic-first-non-land-pick-skipping-Land),
1 auto-join admit-set pin, 1 GENUINE real-EoE cross-engine
byte-equal probe driving the parsed printing against a 3/3
mv-3 opponent creature → destroyed + Lander under p1 (former
controller) byte-equal on BOTH engines. Round-69 fixture
(`test_r69_max_turns_raise_is_parity_safe_and_recovers_timeout_signal`)
re-derived per its own re-derivation contract: arch=9 seed=1's
bench trajectory legitimately changed (it contains Emergency
Eject); the new fixture is arch=7 seed=0 (also a cap-25
FAIL_TIMEOUT that recovers to PASS at cap-60).

**post-shattered-wings delta (prior lane):** strict **+1 PROBED /
−1 BLOCKED-subsystem-gated** (Shattered Wings, 7,793 17lands
single-gated decks per the round-58 attribution scout). Genuine
Rust substrate close following the Cut Propulsion Tier-A precedent
(`feature/effect-uncovered-slice` / `e2e45b46`): new
`Effect::DestroyTargetArtifactEnchantmentOrFlyingCreature`
field-free unit variant (`rust/src/cards.rs`) + parse arm +
to_pydict arm; resolve arm in `rust/src/state_ops_resolve.rs`
beside the OrTapped sibling (cast-time-bound target via
`current_resolve_payload_target_id`; 3-way OR predicate
re-checked at resolve per CR 608.2b; flying leg reads EFFECTIVE
keywords via `battlefield_has_keyword`; indestructible-skip on
the scan; DIES creature-gated; LEAVES + token-cease drained);
`state_ops_legal.rs::spell_targets_satisfiable` 3-way OR arm;
bridge round-trip in `cross_engine.py` + the
`trajectory.py::_python_spell_effect_to_dict` reverse-serializer
adds two leaves (destroy + Surveil — the outer Sequence's
children) so the {2}{G} Shattered Wings Sorcery auto-joins the
spell-card-bridge admit set (6→9 across Cut Propulsion +
Shattered Wings). 7 new probes: 5 Rust pins (artifact / enchant /
flying-creature destroys + non-flying-creature silent fizzle +
indestructible-survives), 1 auto-join admit-set pin, 1 GENUINE
real-EoE cross-engine byte-equal probe driving the parsed
printing against a 2/2 flyer → destroyed → in graveyard
byte-equal on BOTH engines.

**post-cut-propulsion delta:** strict **+1 PROBED / −1
BLOCKED-subsystem-gated / −1 covered-by-construction** (Cut
Propulsion, 11,990 17lands single-gated decks). Genuine Rust
substrate close (Tier-A precedent — Biosynthic Burst / Focus
Fire / Diplomatic Relations): new `Effect::CutPropulsionEffect`
field-free unit variant + parse + to_pydict + resolve (effective-
power read with counters-inclusive formula; flying-doubler via
`battlefield_has_keyword`; saturating damage apply; receiver-
side DEALT_DAMAGE event dispatched). Bridged via `cross_engine.py`
`cut_propulsion_effect` + `trajectory.py` reverse-serializer
leaf — the {2}{R} Cut Propulsion Instant auto-joins the
spell-card-bridge admit set.

**post-non-basic-land-P2 delta (this lane):** strict **+5 PROBED /
−5 BLOCKED-subsystem-gated** (the 5 EoE Planet lands: Adagia,
Windswept Bastion / Evendo, Waking Haven / Kavaron, Memorial World /
Susur Secundi, Void Altar / Uthros, Titanic Godcore; total 7,617
17lands single-gated decks per the round-58 attribution scout). One
new admit disjunct (`_printing_is_bridge_simple_tapped_mana_land`)
plus 5 `_parity`-named PROBED-tier delegator probes. The 5 Planet
lands are 0-Effect cards admitted by the new disjunct; the
`_parity`-named delegators credit them PROBED-tier directly in the
same commit, so COVERED is unchanged. No engine changes; round-39
Ward / round-60 shockland symmetric-drop precedent (the bridge
drops `enters_tapped` on both engines so the bridged shape is
bit-equal; the parser dropped Station + the tier-gated activated
ability before either engine saw the printing — also symmetric).
Note: the prior `post-probe-batches-HHHH-JJJJ` snapshot column
recorded `COVERED=88 / BLOCKED=128` but the live POOL_PARITY at
the start of this lane was `COVERED=89 / BLOCKED=127` (off-by-one
COVERED↔BLOCKED drift in the historical column, undetected by the
round-tail audit lane). The post-this-lane snapshot is the
authoritative `264 / 89 / 122` row of the regenerated
`docs/POOL_PARITY.md`. Spec: `SEARCH_LIMITATIONS.md` "5 EoE Planet
lands admitted as plain untapped mono-color lands".

The tannuk-frenzied-baloth-probes lane delta is strict **+2 PROBED / −2 COVERED**: Tannuk Steadfast Second and Frenzied Baloth flipped COVERED → PROBED via the two new genuine-printing cross-engine byte-equal `_parity` probes. No engine changes, no subsystem-gated movement, no Effect-class movement.

The **post-probe-batches-HHHH-JJJJ** delta is strict **+7 PROBED / −7 COVERED** (probe batches HHHH `25d89e4c`, IIII `07718a2f`, JJJJ `a31b666c` landed `_parity` delegators that promoted covered cards to PROBED): Lightstall Inquisitor, Seriema, Optimistic Scavenger, Command Bridge (probe batch IIII), three Room cards (probe batch JJJJ via the triggered-ability surface delegators). No engine changes, no subsystem-gated movement. **The 128 subsystem-gated tail has been stable since the loader_admits sweep — this audit lane confirmed no further measurement-attribution gaps in the BLOCKED tier.**

The **post-unclassified-residual-attribution** lane delta (2026-05-21, this lane) is strict **+0 PROBED / +0 COVERED / +0/−0 BLOCKED-subsystem-gated** — the 122 subsystem-gated count is preserved. The lane is a SCOUT-side measurement-attribution close on the Unclassified residual: Deafening Silence (the only EoE printing that carries the parser-recognised ``restricts_noncreature_spells_to_one_per_turn`` bool) moved from the ``unclassified`` gate to a new named row ``static_rule_text`` (printing-level bool fields the Python parser already models but Rust does not mirror). Leyline of Mutation remains in ``unclassified`` (its parser TRULY does not surface either of its two oracle mechanics — opening-hand leyline + 5-color alternative-cost). The hand re-walk this row asked for is complete; both cards now carry a named substrate-cost characterisation in §5 and a divergence pin in ``docs/SEARCH_LIMITATIONS.md``. No engine changes, no Rust changes, no bridge changes — same Lane H / Lane Q precedent (the metric helper and the actual engine never disagreed; only the scout's taxonomy gained a row).

Subsystem-gated dropped by 26 total; **both itemized BLOCKED tiers
reached 0**. The 128 tail is now the *only* non-empty BLOCKED tier.
Round-83 (2026-05-20: warp_cost Phase 3) flipped Red Tiger Mechan,
Bygone Colossus, Timeline Culler → PROBED on the existing Phase 1/1.5/2
substrate via two measurement-attribution fixes (loader_admits widen +
`_parity`-named probe aliases). Round-84 (2026-05-20:
dynamic-pt-cosmogoyf) flipped Cosmogoyf → PROBED via a one-arm
extension to the existing round-78 dispatch table. Aura Phase 1
flash widening attribution close (2026-05-21) flipped Frantic Strength
+ Shardmage's Rescue → PROBED via the same measurement-attribution
shape. The 2026-05-21 loader_admits-attribution-sweep then folded the
5 remaining disjuncts of the real loader into the metric helper +
added 9 `_parity` aliases — 9 more cards flipped BLOCKED → PROBED
(Breeding Pool / Godless Shrine / Sacred Foundry / Stomping Ground /
Watery Grave / Brightspear Zealot / Cloudsculpt Technician /
Gravblade Heavy / Mechan Shieldmate; Tannuk Steadfast Second +
Frenzied Baloth honest-stopped at COVERED, then flipped to PROBED
by the tannuk-frenzied-baloth-probes follow-up the same day).

## 1. Headline (current state)

* **128 cards** are subsystem-gated; **53 single-gated**, **75 multi-gated**
  (post loader_admits-attribution-sweep 2026-05-21: 9 cards flipped
  BLOCKED → PROBED via measurement-attribution close — 5 shocklands +
  Brightspear / Cloudsculpt / Gravblade / Mechan Shieldmate; Tannuk
  Steadfast Second + Frenzied Baloth flipped BLOCKED → COVERED
  pending real-EoE cross-engine byte-equal helpers — see lever (1)
  below). The 75 multi-gated total is unchanged.
* **16 taxonomy gates** in the scout's `_gates_for_loader_card` (post
  2026-05-21 unclassified-residual attribution close — the new
  `Static rule-text (printing-level bool field, no Rust mirror)` row
  catches Deafening Silence's ``restricts_noncreature_spells_to_one_
  per_turn``; the existing 15 gates are unchanged). Of those,
  **14 currently bind ≥1 card** — `BECOMES_TAPPED event` /
  `Planeswalker loyalty` / `Rooms / doors` / `Kicker / Impending` bind
  cards but **0 single-gated**; `Carrier activated abilities` and
  `Non-safe triggered ability` bind 30 / 43 cards but **0 single-gated**.
  These are co-blocker rows, not levers.
* A card may trip multiple gates; `#cards` does NOT sum to 128. The
  honest leverage column remains `decks(1g)`.

## 2. Subsystems by closure leverage (refreshed)

Columns are independent. **Tractability** is the roadmap classification;
**Closure scope** is this doc's per-substrate cost estimate, **revised**
to reflect what substrate already exists post-session.

| Subsystem | #cards | 1gate | decks(1g) | Tractability | Closure scope | Status (post-session) |
|---|---:|---:|---:|---|---|---|
| Static / layered abilities | 9 | 2 | 0 | sprawling | small per remaining card (Phases 1+2+3+3.5 substrate built) | **PARTIAL** — round-82: Mechan Shieldmate CLOSED (Phase 3.5); 2026-05-21 loader_admits-attribution-sweep flipped Brightspear / Cloudsculpt / Gravblade / Mechan Shieldmate → PROBED + Tannuk / Frenzied Baloth → COVERED; 2026-05-21 tannuk-frenzied-baloth-probes follow-up flipped Tannuk + Frenzied Baloth COVERED → PROBED via genuine-printing cross-engine byte-equal helpers; 2 single-gated remain (Soulrager / Wickerfolk — not in EoE snapshot) |
| Non-basic land substrate | 13 | 13 | 8,893 | medium | 13 deferred behind sibling substrates (conditional-tapped / clone / Exalted / activated-abilities) | **PARTIAL** — 2026-05-21 loader_admits-attribution-sweep flipped the 5 shocklands → PROBED (round-60); 2026-05-21 non-basic-land Phase-2 (`feature/non-basic-land-slice`) flipped the 5 Planet lands (Adagia / Evendo / Kavaron / Susur Secundi / Uthros, 7,617 decks) → PROBED via the new `_printing_is_bridge_simple_tapped_mana_land` predicate + round-85 arch-65 bench probe + 5 `_parity`-named PROBED-tier delegators; 13 non-shockland non-Planet lands remain DEFERRED (10 Duskmourn painlands' parser-structured `enters_tapped_unless_any_player_life_at_most` is a real cross-engine divergence; Secluded Starforge / Cathedral of War / Echoing Deeps each behind activated-abilities / Exalted-static / clone substrates) |
| Cost-reduction substrate | 5 | 5 | 53,648 | medium | large (true Rust multi-round; Condition-grammar port) | DEFERRED (unchanged; `docs/COST_REDUCTION_SUBSTRATE_PLAN.md`) |
| warp_cost | 7 | 0 | 0 | medium | Phase 1/1.5/2/3 **SHIPPED** — 3 single-gated Phase-3 cards flipped to PROBED (round-83, 2026-05-20: `feature/warp-cost-phase-3`) | **CLOSED for single-gated** — 7 multi-gated tail remains (static/effect-uncovered co-gates) |
| Dynamic-P/T formula | 0 | 0 | 0 | medium | substrate landed `6a8b6402`; Grovestrider closed round-78; Cosmogoyf closed round-84 (this lane: cosmogoyf-arm extension on the SAME dispatch table) | **CLOSED for single-gated** — Emissary Escort honest-stopped Rust-side (different shape: printed-base + X-from-other-artifact-MV, not CDA-only; absent from EoE snapshot) |
| Station / Spacecraft | 8 | 1 | 5,938 | sprawling | large (§2-declined) | DEFERRED (unchanged) |
| Carrier activated abilities | 30 | 0 | 0 | sprawling | sprawling (per-card; 0 single-gated) | DEFERRED (unchanged) |
| Aura-attachment substrate | 3 | 0 | 0 | sprawling | Phase 1/2/2.5/3/4-S3 LANDED — single-gated count is now 0 (Moonlit Meditation flipped PROBED via `b226fbf4` token-supertype-override substrate + `3dc1719d` slug-credit delegator, 2026-05-21; verified by `scout_r58_subsystem_attribution` re-run for this refresh lane) | **CLOSED for single-gated** — 3 multi-gated tail remains (Chorale of the Void / Cracked Skull / Sporogenic Infection — each effect-uncovered + nonsafe-trig + Aura) |
| BECOMES_TAPPED event | 2 | 0 | 0 | contained | small (event bridge) — 0 single-gated | DEFERRED (unchanged) |
| Ward (declined) | dropped | — | — | medium | — | row gone from scout (0-binding) |
| Kicker / Impending | 1 | 0 | 0 | medium | medium — 0 single-gated | DEFERRED (unchanged) |
| Rooms / doors | 3 | 0 | 0 | sprawling | large — 0 single-gated, 0 decks | DEFERRED (unchanged) |
| Planeswalker loyalty | 1 | 0 | 0 | sprawling | large — 0 single-gated | DEFERRED (unchanged) |
| Effect-uncovered (diffuse tail) | 94 | 24 | 103,349 | diffuse | per-card | per-card lane continues |
| Non-safe triggered ability | 43 | 0 | 0 | diffuse | per-event-shape — 0 single-gated | DEFERRED (unchanged) |
| Static rule-text (printing-level bool) | 1 | 1 | 12 | medium | one-card slice (Rust bool + counter + filter mirror + bridge + new admit disjunct) | OPEN — Deafening Silence (2026-05-21 attribution split out of Unclassified; see §5 for rationale) |
| Unclassified (honest residual) | 1 | 1 | 0 | diffuse | per-card hand re-walk | OPEN — Leyline of Mutation (parser does not recognise either of its mechanics; see §5) |

**Reconciliation:** 128 subsystem-gated = 53 single-gated + 75
multi-gated; `1gate` column sums to 53 (post 2026-05-21 loader_admits-
attribution-sweep; the Static/layered-abilities row drops from 15/8/34526
to 9/2/0 — Brightspear / Cloudsculpt / Gravblade / Mechan Shieldmate
flipped to PROBED, Tannuk Steadfast Second + Frenzied Baloth flipped
to COVERED then PROBED via the same-day follow-up writing genuine-
printing cross-engine byte-equal helpers. The Non-basic-land row drops
from 23/23/34575 to
18/18/16510 — the 5 shocklands flipped to PROBED via the round-60
bench-probe pin. Post-Aura-Phase-1-flash-widening close 2026-05-21:
the Aura row at 4/1/633 — Frantic Strength + Shardmage's Rescue +
Duskmourn's Domination dropped out of subsystem-gated; only Moonlit
Meditation remains single-gated, on the un-shipped Phase 4 S3
consumer wire-up. Post-dynamic-pt-cosmogoyf round-84; the Dynamic-P/T
row is 0/0/0 — the substrate is fully closed end-to-end for the two
formulas present in the EoE snapshot (Grovestrider + Cosmogoyf); the
third sibling, Emissary Escort, is absent from the EoE snapshot AND
is honest-stopped Rust-side on a different per-formula shape.

## 3. The remaining highest-leverage levers (re-ranked)

Filtered to substrates that are **(a) named-and-bounded** and **(b) not
already fully closed**. Re-ranked by **decks(1g) ÷ remaining-closure-
scope** with the substrate already-paid-for discounts the session
introduced.

### (1) Static / layered abilities — Phase 3.5 SHIPPED (round 82, Mechan Shieldmate closure)

**Status: high-leverage named lever, near-complete.** Phases 1+2+3
SHIPPED (`3a7c483c` / `9ccefe08` / `ddd93684`); Phase 3.5 SHIPPED
round-82 (Mechan Shieldmate). 6 of the 8 originally-single-gated
cards are closed at metric-tier level: 4 PROBED (Brightspear /
Cloudsculpt / Gravblade / Mechan Shieldmate — all flipped to PROBED
by the 2026-05-21 loader_admits-attribution-sweep via thin `_parity`
delegators that re-use the existing `tests/test_static_layered_
abilities_phase3.py::test_real_eoe_byte_equal_*` cross-engine pins)
and 2 originally COVERED → PROBED (Tannuk Steadfast Second + Frenzied
Baloth — the 2026-05-21 loader_admits-attribution-sweep widened the
metric helper to admit them through the loader filter but they lacked
a genuine real-EoE cross-engine byte-equal helper; the static-anthem
Phase-1 / uncounterable Phase-2 modules already exercised SYNTHETIC
`CardDef` carriers, so the same-day tannuk-frenzied-baloth-probes
follow-up lane added the two missing genuine-printing probes
(`test_cross_engine_real_eoe_tannuk_steadfast_second_static_anthem_parity`
exercises the haste anthem grant byte-equal across both engines on the
genuine parsed printing;
`test_cross_engine_real_eoe_frenzied_baloth_static_uncounterable_parity`
exercises both `spell_is_uncounterable` and
`grants_creature_spells_uncounterable` byte-equal). The remaining
single-gated cards under this gate row are:

* **Rampaging Soulrager** — `UnlockedDoorsAmongRoomsAtLeast(2)`
  Condition. Not in the current EoE data snapshot. Would need a
  per-Condition Rust port riding the now-shipped Phase 3 + 3.5
  substrate. **~1 cycle of slice work**.
* **Wildfire Wickerfolk** — `DeliriumActive` Condition + a layer-6
  trample grant + a layer-7 +1/+1. Not in the current EoE data
  snapshot. ~1 cycle of slice work.

**Multi-gated 7 (unchanged):** Exalted Sunborn, Loading Zone, Memorial
Team Leader, Starfield Vocalist (warp+static); Lumen-Class Frigate
(Station+static); Nexus of Fate (effect-uncovered+nonsafe-trig+static);
Green Sun's Zenith (effect-uncovered+static).

* **Why it's still on the list:** the substrate's been built; each
  remaining card is now small scope, not the original medium-large.
* **Closure scope per remaining card:** small (existing layer
  machinery + 1 new Condition tag).
* **Sequencing:** the 2 remaining single-gated are blocked on an EoE
  snapshot refresh.

### (2) Aura-attachment substrate — Phase 4 only

Phases 1+2+2.5+3 SHIPPED. The Phase 1 flash widening
(``_AURA_SAFE_EXTRA_KEYWORDS = {"flash"}``) landed at round-79; the
**measurement-attribution close** landed at 2026-05-21
(`feature/aura-phase-1-flash-widening`, this lane). The lane verified-
first that the trajectory bridge predicate already admits Frantic
Strength + Shardmage's Rescue cleanly (the round-79 widen has been live
since the Aura-substrate Phase 2 first deliverable; both cards parse
clean: pure ``equipment_bonuses`` + a static ``flash`` keyword
symmetrically dropped on both bridge sides), then closed the two
attribution gaps:

  1. ``scripts/measure_pool_parity.loader_admits`` was missing the
     ``_printing_is_bridge_simple_aura`` disjunct — the trajectory
     predicate has 9 disjuncts but the metric helper only consulted 3
     (basic land + simple creature + warp). Adding the Aura disjunct
     flips a 0-Effect keyword-only Aura into the COVERED tier via the
     ``not eff_classes and admitted`` arm. Cross-cutting result:
     Duskmourn's Domination (Phase 2 S2 admit) ALSO flipped from
     BLOCKED → COVERED in the same fix (it was admitted by the real
     loader since round-79's sibling S2 widen but invisible to the
     metric for the identical reason).
  2. Added ``test_cross_engine_real_eoe_frantic_strength_parity`` +
     ``test_cross_engine_real_eoe_shardmage_s_rescue_parity`` to
     ``tests/test_parity_smoke.py`` mirroring the round-84 Cosmogoyf
     dynamic-PT idiom: round-trip the genuine parsed printing through
     ``_printing_to_card_def``, build matched ``DeckSpec`` states
     carrying the Aura + a vanilla bear filler, inject onto the
     battlefield via ``register_and_inject_object`` (Rust) /
     ``state.new_object`` (Python), attach via ``state.attach``
     (Rust) / ``obj.attached_to = host.id`` (Python), then assert
     ``effective_power(host) / effective_toughness(host)`` byte-equal
     cross-engine AND ``compare_fields == []`` over the WHOLE field
     view at the post-attach state. Both probes drive the genuine
     EoE printings end-to-end.

**+2 PROBED-tier cards (Frantic Strength + Shardmage's Rescue);
+1 COVERED-tier card (Duskmourn's Domination); -3 BLOCKED single-
gated.** Headline before → after: PROBED 236→238, byte-equal 333→336,
single-gated 67→64.

The 3-card subsystem-gated row's residue (refreshed 2026-05-21):

* **Single-gated 0** — Moonlit Meditation was the single-gated
  residue and is now PROBED (`b226fbf4` Aura Phase 4 S3 closure:
  `GameObject.token_supertype_override` + `moonlit_token_substitution`
  helper + loader admit widen + `3dc1719d` slug-credit delegator). The
  body wording below describing Moonlit as un-shipped / honest-stopped
  is **stale historical narrative** from a branch forked before
  `b226fbf4`; preserved here as cycle-history rather than current
  state. The Phase 4 S3 substrate consumer is wired end-to-end.
* **Multi-gated 3:** Chorale of the Void, Cracked Skull, Sporogenic
  Infection — all S4-shape, all multi-gated with effect-uncovered +
  nonsafe-trig + Aura. Phase 3 S4 substrate (`35ede8b0`) is the Aura
  half; per-card Effect-uncovered closures + nonsafe-trigger event
  bridges are the remaining halves.

Sibling lane 3 (`feature/aura-phase-4`) shipped Phase 4 first
deliverable at `6fa5ac9c` (Effect::SacrificeSelfUnlessVoidActive
substrate for Chorale of the Void's end-step trigger).
**`feature/aura-phase-4-s3` (2026-05-21) ships Phase 4 S3 substrate
landing for Moonlit Meditation** — Rust CardPrinting
``aura_replaces_first_tokens_with_copies`` field + per-player
``created_tokens_this_turn: [bool; 2]`` state slot + turn-cleanup
reset + bridge round-trip + per-token-arm flag flip. **Loader admit
stays declined** (the host-as-token swap mechanism in the Rust
CreateToken arm is the remaining honest-stop — needs a runtime-
registry append primitive OR a per-object Token-supertype override
mechanism, neither exists today). Live-EoE admit delta: +0 cards /
+0 decks; substrate-only landing in the slice-19 / Chorale-Effect
tradition.

* **Why it's still on the list:** the remaining Phase 4 S3 close-out
  is small (the substrate is now paid — the consumer wire-up is the
  CreateToken-arm Aura-consulting + host-printing-as-token swap +
  loader admit widen, ~6-10h estimate gated on the supertype-override
  mechanism), and 633 decks of single-gate leverage is real if small.
* **Closure scope:** small (Phase 4 S3 consumer wire-up on top of
  the now-paid substrate) + per-card S4 closures for the
  multi-gated residue (medium each, gated by Effect-uncovered lane
  progress).

#### Phase 3.5 closure note — Mechan Shieldmate (round-82, 2026-05-20)

Extended the Phase-3 substrate with:

* A third condition tag `controlled_artifact_entered_this_turn`
  in the dispatch table (Python + Rust + parse whitelist),
  reading a new per-Player counter
  `artifacts_entered_under_your_control_this_turn` bumped in
  `drain_pending_etb_dispatches` (the centralized bf-entry
  chokepoint) and reset at cleanup, mirroring Python.
* A layer-6 `RemoveKeyword` payload arm in
  `_static_ability_to_self_conditional_bonus` and the
  `removed_keywords` 6th tuple slot in `static_self_bonuses` /
  `StaticSelfBonus`. The Rust `battlefield_has_keyword` reader
  applies REMOVE folds AFTER the positive (printed + UEOT +
  aura-grant + anthem-grant + self-grant) hit — additive ADDs
  minus per-source REMOVEs — mirroring Python's post-walk
  `kws.discard(payload.keyword)`. Closes Mechan Shieldmate.

Section (1) remaining honest-stops post-Phase-3.5: Rampaging
Soulrager / Wildfire Wickerfolk — both absent from the current
EoE snapshot; would need an EoE refresh + per-Condition slice
(`UnlockedDoorsAmongRoomsAtLeast` / `DeliriumActive`
respectively).

### (3) Effect-uncovered diffuse tail — per-card lane

Not a substrate; per-card closures land 1 card at a time. The cheap
Tier-A single-card lane is **EXHAUSTED**. Cut Propulsion CLOSED
(round-86, 2026-05-21: `feature/effect-uncovered-slice` — Tier-A
shape with intrinsic flying-doubler, 11,990 17lands decks) +
Shattered Wings CLOSED (round-87, 2026-05-21:
`feature/shattered-wings-slice` — single-gated tier, 3-way OR
target filter Artifact OR Enchantment OR (Creature AND flying),
7,793 17lands decks; the outer `Sequence(destroy, Surveil 1)`
runs through the pre-shipped Effect::Sequence + Effect::Surveil
arms) + **Beyond the Quiet CLOSED** (round-88, 2026-05-21:
`feature/beyond-the-quiet-slice` — Effect-uncovered honest-stop
follow-on from the wrath-admit-widening lane; 4,698 17lands decks;
field-free wrath shape `Effect::ExileAllCreaturesAndSpacecraft`
with the Creature-OR-Spacecraft multi-type predicate; exile
bypasses indestructible, NO DIES dispatch per CR 700.4 — Beyond
the Quiet AUTO-JOINED the spell-card-bridge admit set via Lane
Y's existing Phase-3 `(0, 0)` wrath admit arm, no further
guardrail widening needed). **Ruinous Rampage closed 2026-05-21**
via `feature/modal-chooseone-cycle-4` (ModalChooseOne envelope
Cycle 4 — new `Effect::ExileAllArtifactsWithManaValueAtMost` Rust
variant + per-leaf serializer arms for `DealDamageEachOpponent`
and `ExileAllArtifactsWithManaValueAtMost` + admit-predicate widen
on the `(0, 0)`-shape all-untargeted ModalChooseOne path; 305
17lands decks). **Drill Too Deep + Reroute Systems closed
2026-05-21** via `feature/drill-too-deep-slice` (Lane DD —
ModalChooseOne envelope Cycle 6 — first per-mode-target
ModalChooseOne flip; new
`Effect::PutChargeCountersOnTargetSpacecraftOrPlanetYouControl
{ amount: i32 }` Rust variant + matching bridge arm +
trajectory `_leaf` table entry + the per-mode target binding
detector table extension in `cast_spell_noncreature` for the
Spacecraft-or-Planet filter; mode 1 = `DestroyTargetArtifact` was
already shipped on the Rust side, the slice added its missing
`_leaf` serializer entry; Untimely Malfunction co-admitted via the
new `destroy_target_artifact` leaf) AND
`feature/reroute-systems-slice-v2` (Lane EE — flipped Reroute
Systems (6,132 17lands decks) COVERED → PROBED via the per-mode
detector table widen + new
`Effect::DealDamageToTargetTappedCreature` + extended
`Effect::PumpTargetArtifactOrCreatureUntilEOT` with
`granted_keywords`). Combined admit-set growth **17 → 20**.
Then `feature/non-state-rs-tractable` (Effect-uncovered single-gated
tier — Exorcise close; Duskmourn {1}{W} Sorcery; Lane GG / state.rs
conflict-avoidance lane) flipped Exorcise COVERED → PROBED via the
new `Effect::ExorciseEffect` Rust unit variant + bridge arm +
reverse-serializer leaf + the file-local `read_doubling_power`
effective-power reader in the 3-way OR target filter (Artifact OR
Enchantment OR Creature-with-effective-power-4+ — structural sibling
of Shattered Wings's destroy-half filter, with two swaps: exile-not-
destroy per CR 702.12 and power-4-not-flying with the effective-
power read folding `obj.counters` + UEOT bonuses byte-equal with
Python's `effective_power`). Admit set **20 → 21**.
Remaining single-gated Effect-uncovered members: Archenemy's
Charm, Coordinated Clobbering, Darkness, Devastating Onslaught,
Pull Through the Weft, Singularity Rupture, Systems Override,
Terminal Velocity, Vengeful Possession, Warping Wail, Zero Point
Ballad (11). **Removed via in-flight closures (2026-05-21/22):**
Close Encounter (close-encounter-substrate + scour-for-scrap-cycle-2
admit-set re-anchor; PROBED ~16,098 decks); Scour for Scrap
(scour-for-scrap-cycle-2; PROBED ~6,434 decks); Scout for Survivors
(multi-target-admit-phase4; PROBED earlier); **Mutinous Massacre
(control-change-ueot-cycle-4-p1; PROBED 2026-05-22 via 4-cycle
closure of the control-change-UEOT subsystem triad, ~4,671 decks).**
The prior list's Emergency Eject + Invasive Maneuvers entries were
stale — both shipped upstream of this dated paragraph.

* **Per-card cost:** 1-3 cycles each — **caveat (2026-05-21)**:
  the next-wrath-substrate triad walk
  (`feature/next-wrath-substrate`) characterized Mutinous Massacre,
  Zero Point Ballad, and Singularity Rupture as **NOT** per-card
  Tier-A slices. Each requires NEW Rust subsystem work, not a
  field-free unit Effect variant in the Beyond-the-Quiet shape:
    * **Mutinous Massacre** — control-change-UEOT subsystem
      (per-object controller override + cleanup-step drain +
      every `o.controller_id` read site routed through an
      effective-controller helper; would also close Systems
      Override). Multi-cycle (3-5).
    * **Zero Point Ballad** — X-value tracking subsystem
      (`StackItem.x_value` + `current_resolve_x_value` bracket
      around resolve) + admit-predicate widen for X-cost spells
      + resolve-time `ChooseFromOwnedDestroyedThisResolve`
      decision push. Multi-cycle (3-4); shares C1 with
      Devastating Onslaught.
    * **Singularity Rupture** — `(0, K)` admit-arm widening for
      "any number of target X" + cross-engine deterministic-all
      subset-pick policy + bespoke `Effect::SingularityRupture`
      variant (NOT a `Sequence(DestroyAllCreatures,
      MillHalfTargetPlayersEach)` composition — verify-first
      2026-05-22 lane `feature/singularity-rupture-cycle-1-p1`
      surfaced that the Python SoT is a unified bespoke
      `SingularityRuptureEffect` class, not a Sequence). Also
      needs a **new multi-target player binding substrate**
      (StackItem `target_player_ids: Option<Vec<u8>>` field +
      `GameState.current_resolve_target_player_ids` transient +
      cast-time multi-pick arm) that does NOT yet exist. Mill is
      floor (rounded DOWN, not up). `legal_targets` includes the
      controller (deterministic-all subset → self-mill on every
      cast). Multi-cycle (**3**, revised up from prior 2-3
      guess). Full verify-first characterization at
      `docs/SEARCH_LIMITATIONS.md` §3 "Verify-first correction
      (2026-05-22)" subsection.

  Full characterization at
  `docs/SEARCH_LIMITATIONS.md` "Next-wrath-substrate triad
  characterization — all 3 candidates require new subsystem work,
  not a single per-card slice (HONEST-STOP, 2026-05-21)".

  **Further caveat (2026-05-21,
  `feature/next-tractable-substrate`)**: a verify-first walk of
  six remaining single-gated candidates — Devastating Onslaught,
  Close Encounter, Scout for Survivors, Systems Override,
  Archenemy's Charm, Scour for Scrap — found every one of the six
  requires multi-cycle subsystem work, not a per-card slice:
    * **Devastating Onslaught** shares Cycle 1 with Zero Point
      Ballad's X-value subsystem, plus needs token-copy substrate
      + delayed-trigger end-step sac. Multi-cycle (3-4).
    * **Close Encounter** needs a brand-new
      `resolving_additional_cost_choice_id` runtime state channel
      + cast-pipeline choice plumbing. Multi-cycle (2-3); 16,098
      decks (highest count among the six).
    * **Scout for Survivors** — **PROBED 2026-05-21**
      (`feature/multi-target-admit-phase4`). Closed via Phase 4
      multi-target admit-gate widen + new Rust
      `Effect::ReturnUpToNSmallCreaturesFromGraveyardWithCounters`
      variant + resolve-time self-scan (graveyard Vec order,
      per-card MV + running sum-MV budget, +1/+1 counter rider).
      The hexad-lane's "shared substrate unlocks Pull Through the
      Weft + Archenemy's Charm mode 2" claim DID NOT pan out under
      verify-first: Pull Through the Weft needs its own
      `ReturnUpToNNonlandPermanentCardsFromGraveyardToHand` Rust
      variant + parser surgery for its dropped lands clause (~3
      cycles), and Archenemy's Charm needs full 3-mode envelope +
      Mode-3 keyword-grant composition (~3-4 cycles). Scout was
      the only clean substrate-only flip; the other two remained
      DEFERRED with their own per-card slices required.
    * **Pull Through the Weft** — **PROBED 2026-05-22**
      (`feature/pull-through-the-weft-cycle-1-p1`). Closed in a
      single cycle (not the ~3 cycles estimated above; the parser
      surgery was already in place via the per-clause grammar at
      `parser/effects.py:1746-1782` so the lane only needed the
      Rust Effect variant + bridge + serializer + admit-gate
      consumer). Closed via new Rust
      `Effect::ReturnUpToNNonlandPermanentCardsFromGraveyardToHand
      { min_n, max_n }` variant + resolve-time self-scan
      (graveyard Vec order, nonland-permanent filter, max_n cap)
      + spell_targets_satisfiable arm + cross-engine bridge +
      Python reverse-serializer leaf. The Phase-4 multi-target
      admit predicate's `(0, 2)` / empty-slot_kinds shape already
      accepted uniform `graveyard_creature` slot kinds (legacy
      emit semantics per the Python class docstring), so Pull
      Through the Weft AUTO-JOINED the admit set the moment its
      Effect class entered the covered+bridged set (admit set
      24 → 25). The dropped lands clause is byte-equal-irrelevant
      under the cross-engine probe (neither engine attempts to
      return lands) — documented in `docs/SEARCH_LIMITATIONS.md`
      "Pull Through the Weft — second-clause parse-drop" entry. Per
      `docs/SEARCH_LIMITATIONS.md` "Multi-target Phase 4
      resolve-time self-scan" — the resolve-time self-scan is a
      documented deliberate divergence vs CR 601.2c cast-time
      binding (cross-engine harness's `_PickFirstLegalTargetAgent`
      makes the divergence unobservable; real-game multi-target
      pick freedom would require a `StackItem.target_obj_ids:
      Vec<u32>` follow-up).
    * **Systems Override** shares the control-change-UEOT
      subsystem with Mutinous Massacre (C1-C3 of the triad lane).
      Multi-cycle (3-5); +1 cycle for Spacecraft-conditional
      charge-counter rider.
    * **Archenemy's Charm** is a 3-mode ModalChooseOne; mode 2
      rides the multi-target return-to-hand substrate
      (shared with Scout for Survivors), mode 3 is bespoke
      composition. Multi-cycle (3-4).
    * **Scour for Scrap** needs Cycle 1 `chosen_modes:
      Option<u8>` → `Option<Vec<u8>>` widening + two new per-mode
      Effect variants. Multi-cycle (2-3).

  Full characterization at
  `docs/SEARCH_LIMITATIONS.md` "Next-tractable-substrate hexad
  characterization — all 6 candidates require multi-cycle
  subsystem work, not a single per-card slice (HONEST-STOP,
  2026-05-21)". Cross-candidate amortization summary in that
  entry's tail: cheapest-amortized lane is the multi-target
  admit-gate Phase 4 widen (3 candidates), followed by the
  control-change-UEOT lane (2 candidates).

  **Control-change-UEOT Cycle 1 landed (2026-05-21,
  `feature/control-change-ueot-cycle-1`).** Substrate-only:
  `controller_override: Option<u8>` on `GameObject` +
  `effective_controller_id` helper + cleanup-step drain +
  `grant_control_change_ueot(target_id, new_pid)` PyO3 method +
  per-object snapshot key. No live mint site yet — Cycle 2
  reroutes the raw `.controller` read sites; Cycle 3 wires the
  Python ↔ Rust bridge round-trip; Cycle 4 adds the Mutinous
  Massacre / Systems Override Effect variants that mint the
  override. Substrate landing is **back-compat byte-equivalent**
  on production self-play / cross-engine trajectories — every
  override defaults to `None`, the new snapshot key is `None`
  for every pre-substrate object, and `controller_overrides_cleared`
  in the cleanup-summary dict is `0` until Cycle 4 mints
  overrides. Full Cycle 1 entry at `docs/SEARCH_LIMITATIONS.md`
  §1 (Mutinous Massacre).

  **Control-change-UEOT Cycle 2 landed (2026-05-21,
  `feature/control-change-ueot-cycle-2-p1`).** Rerouted 10
  gameplay-decision raw `.controller` reads through
  `effective_controller_id` across `state_ops_legal.rs` (3
  legal-target predicates: BiosynthicBurst / Spacecraft-or-Planet-
  You-Control / Diplomatic-Relations) + `state_ops_combat.rs` (3:
  dynamic-P/T subject + per-permanent predicate +
  battlefield_creature_controller for lifelink) +
  `state_ops_cast.rs` (4: Diplomatic-Relations cast-bind +
  Spacecraft-Planet cast-bind + additional-cost creature-you-
  control + Aura `yours_only` host filter). Back-compat byte-
  equivalent (no live mint site yet, so every reroute returns
  `obj.controller` unchanged); the substrate is now in place for
  Cycle 4's Mutinous-Massacre / Systems-Override Effect variants
  to flip these decisions on the same turn the override mints.
  Kept raw on purpose: snapshot/fingerprint identity sites, SBA
  graveyard routing (CR 400.6 owner-vs-controller gap is
  orthogonal), state_ops_resolve.rs source-controller multi-zone
  scans (substrate-equivalent today since override never mints
  off-bf), StackItem.controller (different struct), and
  constructor writes. Full Cycle 2 audit at
  `docs/SEARCH_LIMITATIONS.md` §1.

  **X-value-subsystem Cycle 1 landed (2026-05-21,
  `feature/x-value-subsystem-cycle-1-p1`).** Substrate-only
  (parallel shape to control-change-UEOT C1):
  `StackItem.x_value: Option<i32>` field +
  `GameState.current_resolve_x_value: Option<i32>` transient slot
  + save → set → restore bracket in BOTH `resolve_top_of_stack`
  AND `resolve_top_of_stack_pause` + dedicated PyO3 getter
  `stack_top_x_value()` + synthetic-test setter
  `set_stack_top_x_value()`. Subsumes the prior
  `new_spell_with_targets_mode_and_addcost` constructor →
  `new_spell_with_targets_mode_addcost_and_x` (clean replacement,
  1 production call site, no-fallback-hybrid discipline). No live
  mint site yet — Cycle 2 wires the cast-pipeline X-cost detector
  (`mc.x_pips > 0` → pay-all-floating no-agent fallback +
  `StackItem.x_value` bind); Cycle 3 wires the
  `Effect::ZeroPointBallad` resolve arm (reads
  `current_resolve_x_value` to compute the toughness filter + life
  loss + conditional reanimation); Cycle 4 wires
  `Effect::DevastatingOnslaught` (X tokens that are copies +
  delayed-trigger end-step sac, sharing the same C1 substrate).
  Substrate landing is **back-compat byte-equivalent** on
  production self-play / cross-engine trajectories — every
  `x_value` defaults to `None`, the new transient defaults to
  `None`, the bracket is a no-op when source is `None`, and no
  Effect arm reads the transient yet. Both **Zero Point Ballad**
  (6,041 17lands decks) and **Devastating Onslaught** (2,238
  decks) share this C1 substrate per the prior next-tractable-
  substrate hexad characterization. Full Cycle 1 entry at
  `docs/SEARCH_LIMITATIONS.md` §2 (Zero Point Ballad).

  **X-value-subsystem Cycle 2 landed (2026-05-22,
  `feature/x-value-subsystem-cycle-2-p1`).** Verify-first walk
  surfaced that Rust's `cards::ManaCost` struct had NO `x_pips`
  field at all (`cards.rs:39-46` pre-Cycle-2 was bare `generic
  + 5-colored u8`) — so the cast pipeline couldn't even
  STRUCTURALLY detect an X-cost printing, the parser rejected
  the `"X"` key as unknown, and `mana_cost_to_pydict` never
  emitted it. The original C2 brief assumed this substrate
  existed and planned to ship the cast-pipeline detector +
  StackItem mint site + admit-predicate widen in one cycle;
  honest re-scope split that into C2 (foundational
  `cards::ManaCost.x_pips` substrate, this cycle) and C2.5
  (cast detector + admit widen, next cycle). Verify-first also
  surfaced that Zero Point Ballad's Python
  `ZeroPointBalladEffect` uses synchronous `p.agent.choose_target`
  for its X≥6 reanimation step — NOT a `PendingDecision` push —
  so the original C2 brief's `PendingDecision::ChooseFromOwned
  DestroyedThisResolve` scaffold has no parity counterpart and
  was dropped from this cycle (Cycle 3+ wires whatever
  resolve-time shape matches Python). Cycle 2 ships: (1)
  `cards::ManaCost.x_pips: u8` (back-compat default 0,
  mirrors Python's `ManaCost.x_pips: int = 0`); (2)
  `parse_mana_cost` accepts the `"X"` key; (3)
  `mana_cost_to_pydict` emits `"X"` when nonzero; (4) PyO3
  getter `Registry.get_printing_x_pips(id) -> u8`; (5) the
  three Lightstall +{1} surcharge struct literals preserve
  `x_pips` across surcharge (CR 601.2f); (6) updated
  `state_ops_mana.rs::can_pay_cost` SL doc framing the
  "x_pips ignored at can_pay_cost; Cycle 2.5+ folds it into
  generic before invocation" divergence. Substrate landing is
  **back-compat byte-equivalent** on production self-play /
  cross-engine trajectories — every existing printing's
  registry-dict omits the `"X"` key (`x_pips` defaults to 0),
  the emit side continues to omit the key for those printings,
  `can_pay_cost` ignores the new field (every existing call
  site passes a cost with `x_pips == 0`), and no admit-predicate
  flip lands (X-cost spells stay declined). The substrate is
  sufficient for Cycle 2.5 to wire the cast-pipeline X-cost
  detector + StackItem mint site as a purely additive change
  with no further `cards::ManaCost` extension required. Full
  Cycle 2 entry at `docs/SEARCH_LIMITATIONS.md` §2 (Zero Point
  Ballad).

  **X-value-subsystem Cycle 2.5 landed (2026-05-22,
  `feature/x-value-subsystem-cycle-2-5-p1`).** Composite cycle
  shipping the admit-predicate widen + first live mint site for
  `StackItem.x_value`. Part 1
  (`parity/trajectory.py::_printing_is_bridge_simple_spell`)
  drops the early `mc.x_pips > 0` reject and adds an
  `_printing_is_x_cost` local that each non-Phase-3 phase
  predicate (Phase 1 / 2 / 4 / 5) conjuncts on — only the
  Phase-3 wrath shape (`(0, 0)` no slot_kinds / no `targets`
  attr) admits an X-cost printing. The covered+bridged +
  round-trip-or-bail teeth keep Zero Point Ballad DECLINED
  (no `Effect::ZeroPointBallad` yet); admit-set delta is 0
  cards in C2.5. Part 2
  (`state_ops_cast.rs::cast_spell_noncreature` Delta-2 block)
  adds an additive X-cost detector branch: if
  `cost.x_pips > 0`, bind `bound_x_value = Some(0)` per the
  no-agent fallback (verify-first re-scope: Python's
  `_choose_and_apply_x` at `actions.py:529-549` returns 0 when
  `p.agent is None`; the cross-engine harness drives Python
  with `agent=None`, so X=0 is the byte-equal mirror — NOT
  max payable as the original C2.5 brief implied), fold
  `x_pips * x_value` into generic and zero `x_pips` before
  `auto_tap_pay_for_cost`, then thread `Some(x)` into the
  Cycle-1-prepared `new_spell_with_targets_mode_addcost_and_x`
  constructor. **Live-mint-site invariant changeover.** Non-X
  spells still push `StackItem.x_value = None` (regression
  invariant); X-cost spells now push `Some(0)` — the FIRST
  production code path that mints a non-None value into the
  Cycle 1 substrate field. CR 117.4 boundary (`Some(0)` ≠
  `None`) preserved by the `Option<i32>` storage shape. Tests:
  13 pins in `tests/test_x_value_subsystem_cycle2_5.py`. The
  `submit_choose_x_decision` callback the original brief
  proposed is **deferred** to C3+ — verify-first found no
  cross-engine consumer for agent-driven X today (the harness
  is no-agent). Full C2.5 entry at
  `docs/SEARCH_LIMITATIONS.md` §2 (Zero Point Ballad).

  **X-value-subsystem Cycle 3 landed (2026-05-22,
  `feature/x-value-subsystem-cycle-3-p1`).** First X-cost
  cross-engine close. Lands `Effect::ZeroPointBalladEffect`
  Rust unit variant + parse arm + `to_pydict` arm + resolve
  arm in `state_ops_resolve.rs` + cross-engine bridge arm in
  `cross_engine.py` + reverse serializer leaf in
  `trajectory.py`. The §2 auto-grow teeth fire positively
  (covered+bridged + round-trips + Phase-3 wrath shape from
  C2.5's admit-widen), flipping Zero Point Ballad COVERED →
  PROBED. Admit set 24 → 25; PROBED 279 → 280 on this branch
  (parallel sibling Mutinous Massacre C5 + Darkness C3
  branches add +2 each once they merge). Rust resolve arm
  mirrors Python's `effects/bespoke.py::ZeroPointBalladEffect`
  byte-equal: two-pass per-victim destroy (snapshot creature
  ids whose effective toughness <= X + caster-owned-victim-id
  subset; then per-victim destroy with indestructible skip,
  CR 400.7 zone reset, LEAVES+DIES+token-cease queued), lose
  X life, X>=6 reanimation tail walking caster's graveyard for
  the first caster-owned-victim creature card. Effective
  toughness is inline (printed + UEOT base override + counters
  + UEOT toughness bonus; mirrors the I76 recipe). The X>=6
  reanimation tail uses the deterministic-first convention;
  under the no-agent harness Python NEVER reanimates
  (`if candidates and p.agent is not None:` guard at
  `bespoke.py:1728`) AND Rust is dormant (X=0 mint per C2.5
  < 6). Tests: 10 pins in
  `tests/test_zero_point_ballad_parity.py` (5 synthetic-state
  Rust unit pins covering the X-dependent surface that the
  no-agent cross-engine harness cannot exercise + the genuine
  real-EoE byte-equal probe at X=0). The X-dependent action
  surface cross-engine parity is conditional on an agent-
  driven X picker landing on both engines — until then the
  X=0 cross-engine probe rides on vacuous-resolve byte-equal,
  documented as a deliberate harness limitation in
  `docs/SEARCH_LIMITATIONS.md` §2 (C3 LANDED block).
  **Darkness Cycle 1 landed (2026-05-21,
  `feature/darkness-cycle-1-p1`).** Substrate-only state-channel
  for the combat-damage prevention shape:
  `prevent_all_combat_damage_this_turn: bool` field on
  `GameState` (sibling of `permanent_left_battlefield_this_turn`
  and `spell_warped_this_turn`) +
  `grant_prevent_all_combat_damage_this_turn` PyO3 setter
  (idempotent set-to-true) + `prevent_all_combat_damage_this_turn`
  PyO3 `#[getter]` over the flag +
  `clear_prevent_all_combat_damage_this_turn` standalone drain
  primitive + cleanup-step inline drain (CR 514.3) +
  `prevent_all_combat_damage_drained: bool` cleanup-summary key.
  No combat-damage routing site reads the flag yet — Cycle 2
  reroutes `state_ops_combat.rs::apply_damage_pass` through the
  preventer; Cycle 3 adds the `Effect::PreventAllCombatDamage
  ThisTurn` parse / resolve / bridge arms + the admit-gate
  positive-emit widen + the PROBED flip on the 43-deck Darkness
  printing. Substrate landing is **back-compat byte-equivalent**
  on every production self-play / cross-engine trajectory — the
  flag defaults to `false` at every construction site (the
  `Clone` impl carries it forward; `make_state` /
  `make_synthetic_state` both default it), no read site consumes
  it, the field is NOT in the fingerprint (transient turn-scoped
  flag, same shape as the void flags), and the new summary key
  reads `false` on pre-Cycle-1 trajectories. Full Cycle 1 entry
  at `docs/SEARCH_LIMITATIONS.md` "Darkness — combat-damage
  prevention substrate missing on Rust". Independent of the
  control-change-UEOT lane — different state channel, different
  cleanup-step drain key, different mint shape; the two substrate
  landings amortize against `cleanup_step_for_active_player` as
  the shared CR-514.3-aggregator.

  **Darkness Cycle 2 landed (2026-05-21,
  `feature/darkness-cycle-2-p1`).** Combat-damage routing-point
  guard at the top of `state_ops_combat.rs::deal_combat_damage`:
  when `self.prevent_all_combat_damage_this_turn` is `true`, the
  function returns `Ok(())` BEFORE building the damage plan or
  calling `apply_damage_pass`. CR 615.4 — "if a damage event
  would be prevented entirely, it doesn't happen at all" — and
  the guard sits at the **single bottleneck** combat-damage
  routing site (`deal_combat_damage` is the sole combat-damage
  entry point and calls `apply_damage_pass` 1–3× per combat
  step), so one read covers all plan entries / triggers /
  lifelink / I32 slot writes. Substrate-only invariant: no
  production trajectory mints the flag today (Cycle 3's
  `Effect::PreventAllCombatDamageThisTurn` resolve arm is the
  production mint site), so the guard is a no-op on every
  pre-Cycle-3 cross-engine trajectory — **back-compat byte-
  equivalent** through the Cycle 2 landing. 13 routing-pin tests
  in `tests/test_darkness_cycle2.py` (flag-false back-compat
  byte-equal pin against the canonical 2/2-vs-defender combat
  scenario; flag-true zero-out for unblocked / blocked / multi-
  attacker / trample-spillover; flag-true no-fire pins for
  lifelink, DealsDamage trigger, DealtDamage trigger; flag-true
  does NOT suppress non-combat `deal_damage`; cleanup-drain
  restores combat next turn; flag-true leaves
  `resolving_combat_damage_amount` slot untouched; flag-true +
  no attackers clean no-op; CoW isolation invariant). Sanity
  gates: 16/16 Cycle 1 + 13/13 Cycle 2 + 721/721 cross-engine +
  636/636 parity smoke + rust engine smoke + rust bridge parity
  + control-change-ueot tests, zero new failures vs Cycle 1
  base. Cycle 3 still needs the Effect variant / bridge round-
  trip / admit widen / PROBED flip — see Search Limitations
  Darkness entry.

  **Darkness Cycle 3 landed (2026-05-22,
  `feature/darkness-cycle-3-p1`).** `Effect::PreventAllCombat
  DamageThisTurn` Rust field-free unit variant (`rust/src/
  cards.rs`) + parse arm `"prevent_all_combat_damage_this_turn"`
  + `to_pydict` arm + resolve arm in `state_ops_resolve.rs` (the
  PRODUCTION MINT SITE for the Cycle 1+2 substrate — a single
  bool flip on `state.prevent_all_combat_damage_this_turn`,
  byte-equal with Python's `PreventAllCombatDamageThisTurn.
  resolve` at `effects/generic/stack_control.py:266`). Cross-
  engine bridge arm in `src/mtg_bot/parity/cross_engine.py::
  _ta_dict_to_python_effect` constructs the field-free Python
  class. Reverse-serializer leaf in `src/mtg_bot/parity/
  trajectory.py::_python_spell_effect_to_dict::_leaf` emits
  `{"kind": "prevent_all_combat_damage_this_turn"}`. Darkness
  AUTO-JOINS the spell-card-bridge admit set via the existing
  Phase-3 `(0, 0)`-shape wrath admit arm (no admit-predicate
  widen needed — `target_count_range() == (0, 0)`, no
  `slot_kinds`, no `targets` attribute on the printing). The §2
  teeth all fire positively (covered+bridged AND round-trips), so
  the lever auto-grows the admit set 24 → 25. **PROBED 279 →
  280**; Darkness flips COVERED→PROBED at 43 17lands decks.
  Cross-engine pin proves the Cycle 3 → Cycle 1 flag flip → Cycle
  2 guard routing handoff: cast Darkness, resolve flips the flag,
  combat damage zeros out on BOTH engines, cleanup drains the
  flag, next turn's combat applies damage normally. The 3-cycle
  subsystem is LANDED end-to-end.
  **Control-change-UEOT Cycle 3 landed (2026-05-21,
  `feature/control-change-ueot-cycle-3-p1`).** Bridge round-trip
  plumbing — Python ↔ Rust closure for the per-object
  `controller_override` field. Inbound (the missing direction):
  `register_and_inject_object` gains an optional
  `controller_override` PyO3 kwarg (keyword-only, default `None`,
  back-compat byte-equal); `{0, 1}` pid validation raises
  `IndexError` BEFORE the registry extend (no partial state on
  reject). Python-side reciprocal in
  `src/mtg_bot/parity/cross_engine.py`:
  `python_controller_override(state, obj)` reads layer-2
  `"control_change"` entries off a Python `GameObject` (latest-
  timestamp wins; compared against
  `controller_id_before_any_aura_swap` baseline for the same-
  controller short-circuit) and returns the override pid or
  `None`. `inject_object_with_controller_override(...)` wraps
  the Rust inbound call. Round-trip pinned: Rust → dict → Rust
  is byte-identical for default-`None` AND survives byte-equal
  for `grant_control_change_ueot`-set overrides; the inbound
  kwarg path is semantically equivalent to inject-then-grant
  (pin test). Substrate-only invariant maintained: no live mint
  site yet (Cycle 4 wires Mutinous Massacre / Systems Override);
  every pre-Cycle 3 cross-engine trajectory stays byte-identical;
  override field stays out of the per-object fingerprint tuple
  (canary). 17 new tests in
  `tests/test_control_change_ueot_cycle3.py`; 1466/1466 PASS on
  the broad sanity gate (cycle 1 + cycle 3 + rust_engine_smoke +
  parity_smoke + rust_bridge_parity + aura_substrate_phase_4_s3
  + tractor_beam_control + aura phases 1/3_s4/4 + 5
  cross_engine_* test files); 77/77 PASS on trajectory_parity.
  Cycle 4 is now unblocked. Full Cycle 3 entry at
  `docs/SEARCH_LIMITATIONS.md` §1 (Mutinous Massacre).

  **Control-change-UEOT Cycle 4 landed (2026-05-22,
  `feature/control-change-ueot-cycle-4-p1`).** First live mint
  site: Mutinous Massacre (~4,671 17lands decks) flipped COVERED
  → PROBED via `Effect::MutinousMassacreEffect` field-free unit
  variant + resolve arm (destroy by parity + gain-control + untap
  + haste UEOT, the FIRST Rust call site that mints a non-None
  `controller_override`) + bridge round-trip + reverse-serializer
  leaf. Rust mirrors Python's no-agent default pick=0 / odd inside
  the resolve arm (Rust has no agent surface at `apply_effect`;
  the deterministic-first pattern is the byte-equal mirror —
  Python's `if p.agent is not None: pick = ... else: pick=0` at
  `bespoke.py:1303-1306`). The C1-C3 substrate composes uniformly:
  the cleanup-step drain reverts the stamped override back to
  `None` at end of turn (composed in `cleanup_step_for_active_player`
  alongside the round-27 `clear_ueot_modifiers_all` for haste).
  Admit set 24 → 25 (Mutinous Massacre AUTO-JOINS the Phase-3
  `(0, 0)` wrath admit shape; no admit-set widening needed per the
  §2 auto-grow teeth). 13 new tests in
  `tests/test_mutinous_massacre_parity.py` (parser SoT + serializer
  round-trip + admit-gate flip + covered-class pin + Rust resolve
  unit pins for the 8 closure scenarios + the GENUINE real-EoE
  cross-engine probe driving the parsed printing through both
  engines). **Systems Override (~4,775 17lands decks) DEFERRED to
  Cycle 5** per the lane brief's "if 1-cycle-feasible" honest-stop
  — Systems Override needs ALSO a new
  `Effect::SystemsOverrideEffect` variant + a
  `RemoveChargeCountersFromSourceDelayed` delayed-trigger Effect
  variant + extending the Rust `DelayedTrigger` end-step drain to
  dispatch non-WarpExileSelf effects (the Spacecraft-conditional
  charge-counter rider). Single-cycle land of both would compound
  the surface area beyond a reviewable slice. Full Cycle 4 entry
  at `docs/SEARCH_LIMITATIONS.md` §1 (Mutinous Massacre).

  **Control-change-UEOT Cycle 5 landed (2026-05-22,
  `feature/control-change-ueot-cycle-5-p1`).** Second live mint
  site: Systems Override (~4,775 17lands decks) flipped COVERED →
  PROBED via `Effect::SystemsOverrideEffect` field-free unit variant
  + resolve arm (single-target control-change + untap + haste UEOT
  + Spacecraft-conditional +10 charge counters + delayed-trigger
  schedule) + the new
  `Effect::RemoveChargeCountersFromSourceDelayed { amount: i32 }`
  variant + its resolve arm. **The G7 Class-C end-step drain
  composes uniformly without modification** —
  `push_triggered_ability` is generic over the `Effect` payload
  (no enum-arm gate), so the existing
  `run_delayed_end_step_triggers` machinery pushes the new variant
  onto the stack at PHASE_END_STEP entry exactly the same way it
  pushes `WarpExileSelf`. The resolve arm landing in `apply_effect`
  was the only substrate change needed; Systems Override is the
  SECOND non-WarpExileSelf consumer of the delayed-trigger drain.
  Admit set 25 → 26 (Systems Override AUTO-JOINS the Phase-1
  `(1, 1)` single-target admit shape; no admit-set widening needed
  per the §2 auto-grow teeth). 15 new tests in
  `tests/test_systems_override_parity.py` (parser SoT + 2 serializer
  round-trips + admit-gate flip + 2 covered-class pins +
  6 Rust resolve unit pins + cleanup-drain composition +
  silent-no-op + the GENUINE real-EoE cross-engine probe driving
  the parsed printing through both engines against an opponent-
  controlled Spacecraft, pinning the +10/-10 packet end-to-end).
  Loading Zone counter-doubling not yet mirrored in Rust (Loading
  Zone is BLOCKED in the EoE pool today; the literal +10 is
  byte-equal in its absence — deferred as a future micro-cycle).
  Full Cycle 5 entry at `docs/SEARCH_LIMITATIONS.md` §1 (Systems
  Override). Systems Override drops out of the single-gated EU
  list — the control-change-UEOT subsystem closes its EoE-pool
  consumers across C4 (Mutinous Massacre) + C5 (Systems Override);
  C6 is cross-set / agent-prompt extension only.

  **Devastating Onslaught Cycle 1 landed (2026-05-22,
  `feature/devastating-onslaught-cycle-1-p1`).** Second X-cost
  cross-engine close, immediate follow-on to Zero Point Ballad's
  X-value C3. Lands the
  `Effect::CreateXTokensOfTargetPermanentWithHasteEndStepSac`
  Rust unit variant + sibling `Effect::SacrificeSourceDelayed`
  delayed-trigger Effect + matching bridge arms + reverse
  serializer leaves + Phase-1 `(1, 1)`-shape X-cost admit widen.
  The admit set grows 25 → 26; PROBED 280 → 281 on this branch.
  Closes the pre-existing X-cost bench-loader baseline failure
  (Zero Point Ballad admit-gate-passing post C3 but crashing on
  `_parse_mana_cost_string` at bench loader time) by accepting
  the `{X}` symbol with 0-contribution-to-generic (mirrors
  Rust's no-agent X=0 fold-in semantics). Full entry at
  `docs/SEARCH_LIMITATIONS.md` §2 (Devastating Onslaught Cycle 1
  LANDED block).

  **Vengeful Possession Cycle 1 landed (2026-05-22,
  `feature/vengeful-possession-cycle-1-p1`).** First non-EoE
  consumer of the substrate: Vengeful Possession (DSK; `{2}{R}`
  Sorcery — "Gain control of target creature until end of turn.
  Untap it. It gains haste until end of turn. You may discard a
  card. If you do, draw a card."; ~0 17lands decks — uncommon
  Effect-uncovered closure surfaced by the Effect-uncovered next-5
  walk). Vengeful Possession is admitted into the EoE-aware test
  pool via the Effect-uncovered single-gated tier classifier
  (same admit class as Exorcise, which is also Duskmourn-source).
  Adds:
    * `Effect::ThreatenTargetCreatureUEOT` field-free unit variant
      + resolve arm (the generic Threaten core: read
      `current_resolve_payload_target_id`, creature-only filter,
      inline override-mint + same-controller short-circuit + untap
      + haste UEOT push). Mirrors the Cycle 4 / Cycle 5 inline
      shape but creature-only target filter (vs Systems Override's
      artifact-OR-creature filter).
    * Bridge arm `kind == "threaten_target_creature_ueot"` in
      `cross_engine.py::_ta_dict_to_python_effect`.
    * **Five new `_leaf` arms** in `trajectory.py::
      _python_spell_effect_to_dict` for the surrounding composite
      Effects — `ThreatenTargetCreatureUEOT`, `IfYouDo`, `MayDo`,
      `DiscardSelf`, `DrawCards`. All five were ALREADY Rust-
      covered AND bridged at this cycle's HEAD; the reverse-
      serializer table was the only missing piece. The Sequence
      composer's child-recurse + IfYouDo's do/then-recurse now
      serialize Vengeful Possession's full looter-rider tree
      byte-equal.

  PROBED 281 → 282 (Vengeful Possession); admit set 30 → 31.
  Vengeful Possession rides the Phase-1 `(1, 1)` single-target
  admit shape — the looter rider is untargeted, the threaten core
  takes one creature target. 11 new tests in
  `tests/test_vengeful_possession_parity.py` (parser SoT + 2
  serializer round-trips + admit-gate flip + covered-class pin +
  5 Rust resolve unit pins covering opponent-creature grant,
  own-target same-controller short-circuit, creature filter
  declining an artifact target, no-target silent no-op, cleanup
  drain + the GENUINE real-EoE cross-engine probe driving the
  parsed Vengeful Possession printing through the Rust resolve
  arm). Full Vengeful Possession Cycle 1 entry at
  `docs/SEARCH_LIMITATIONS.md` §1.

* **Pool-flip per cycle:** 1 card + its deck count.
* **Cumulative reach:** largest row but incremental cadence (C4+C5
  + Vengeful Possession Cycle 1 together flipped 3 cards across the
  three lanes).

### (4) Dynamic-P/T formula — **CLOSED** (round-84, 2026-05-20)

Substrate landed `6a8b6402` (round-78); Harmonious Grovestrider
closed end-to-end (now PROBED at
`tests/test_parity_smoke.py::*_harmonious_grovestrider_*`).
**Cosmogoyf closed round-84** (this lane: `feature/dynamic-pt-cosmogoyf`)
via the SAME dispatch table — added the `"cosmogoyf"` arm to
`state_ops_combat::dynamic_base_pt_pub` (P=N, T=N+1 where
N = controller's-exile-zone count; mirrors Python's
`game._dynamic_base_pt` arm verbatim) + widened the bridge admit
predicate (`trajectory._printing_is_bridge_simple_creature`) from a
single-key match to a module-level admit set
`_DYNAMIC_PT_FORMULA_ADMIT_SET = {"harmonious_grovestrider",
"cosmogoyf"}` so future formula slices land here with a one-key
addition. PROBED at
`tests/test_parity_smoke.py::test_cross_engine_real_eoe_cosmogoyf_dynamic_pt_parity`
(drives the GENUINE parsed EoE Cosmogoyf printing — round-46
real-EoE-signal discipline; Cosmogoyf has no ward / triggered /
activated / static abilities, so unlike Grovestrider the live
printing admits directly through the bridge without needing a
synthetic CardDef).

**Honest-stop:** `"emissary_escort"` formula key remains drop-at-
filter on the bridge AND honest-stopped in the Rust dispatch table.
Its shape is different from the two admitted CDA-only formulas —
Escort reads `printing.power` / `printing.toughness` and ADDS X
(greatest mana value among OTHER artifacts the controller controls);
the CDA-only `dynamic_pt_formula` arm this dispatch table covers
today sets the BASE from scratch. Emissary Escort's slice extends
the dispatch table when it lands; not in the current EoE snapshot,
so no immediate leverage.

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
| 1 | **Static / layered abilities — Mechan Shieldmate (Phase 3.5)** | (single card in the 8) | 1 | — | **CLOSED round-82 (2026-05-20)** — `feature/mechan-shieldmate-closure` |
| ~~2~~ | ~~**warp_cost Phase 3**~~ | ~~15,436~~ | — | — | **CLOSED round-83 (2026-05-20)** — `feature/warp-cost-phase-3`; +3 PROBED |
| ~~2~~ | ~~**Dynamic-P/T formula — Cosmogoyf**~~ | ~~small~~ | ~~1-2~~ | — | **CLOSED round-84 (2026-05-20)** — `feature/dynamic-pt-cosmogoyf`; +1 PROBED; one-arm extension to the round-78 dispatch table |
| ~~3~~ | ~~**Aura Phase 4 S3 — Moonlit Meditation**~~ | ~~633~~ | — | — | **CLOSED 2026-05-21** — substrate + consumer wire-up shipped (`b226fbf4` token-supertype-override + `3dc1719d` slug-credit delegator); Moonlit Meditation PROBED; Aura row single-gated count is now 0 |
| 4 | **Effect-uncovered per-card drain — next 3-5 cheap single-gated** | varies (~5-15k cumulative) | 3-5 | ~3,000 | Cheaper Tier-A lane exhausted; remainder is Tier-C |

**Sequencing rationale:**

* The original #1 (Static abilities) is **now small-cost-per-card** —
  the substrate cost was paid in the session. Mechan Shieldmate
  closed the last EoE single-gated card on the layer table (round-82).
* **warp_cost** moved up to #2 because its substrate was similarly paid
  for and the deck count was the largest among 1-2-cycle slices;
  closed round-83.
* **Dynamic-P/T formula** (Cosmogoyf) was the cheapest 1-cycle slice
  after Static + warp_cost both closed — the round-78 dispatch table
  was already paid for and Cosmogoyf added a single match arm +
  bridge admit-set widen. Closed round-84.
* **Aura Phase 4 — CLOSED 2026-05-21** (`b226fbf4` + `3dc1719d`).
  Moonlit Meditation PROBED; the historical "dropped to #4" framing
  is stale — the lever is fully closed for the single-gated tier.
* **Effect-uncovered lane** continues in parallel; pace is bounded by
  per-card Rust scope, not substrate availability.

## 5. Substrates explicitly OFF the top-5

* **Cost-reduction substrate (5 cards, 53,648 single-gate decks).**
  Highest single-gate deck count of any named row, but
  `docs/COST_REDUCTION_SUBSTRATE_PLAN.md` documents the bridge-correct
  realizable yield is **0 in any near-term clean slice** — admitting
  any of the 5 ships a guaranteed inter-engine divergence. Large
  multi-round Rust substrate. Keep deferred.
* **Non-basic land substrate remainder (13 cards, post round-85).**
  Behind sibling substrates (conditional-tapped — Duskmourn painlands;
  Station / activated — Secluded Starforge; clone — Echoing Deeps;
  Exalted-static — Cathedral of War). Not a clean slice. The 5
  Planet lands closed in round-85 (`feature/non-basic-land-slice`,
  `_printing_is_bridge_simple_tapped_mana_land`); the 5 shocklands
  closed in round-60. The remaining 13 are 8,893 cumulative decks
  (Secluded Starforge 7,570 + Cathedral of War 1,205 + Echoing Deeps
  118 + 10 zero-deck Duskmourn painlands).
* **Station / Spacecraft (8 cards, 5,938 decks).** Documented
  §2-decline; large substrate.
* **Carrier activated abilities (30 cards, 0 single-gated).** All
  multi-gated — closing this gate alone flips zero cards.
* **Non-safe triggered ability (43 cards, 0 single-gated).** Per-event-
  shape frontier; co-blocker row, not a lever.
* **Rooms / doors, Planeswalker loyalty, Kicker, BECOMES_TAPPED.** All
  have 0 single-gated members; closing the gate alone flips zero cards.
* **Static rule-text — Deafening Silence (1 card, 12 decks).** **2026-
  05-21 unclassified-residual hand re-walk** characterised this as a
  contained-medium named substrate, NOT a generic unknown: the
  printing carries
  ``restricts_noncreature_spells_to_one_per_turn=True`` (a recognised
  parser bool slot at ``src/mtg_bot/cards/base.py:843``), Python fully
  models the mechanic (per-player ``noncreature_spells_cast_this_turn``
  counter incremented in ``actions.py:1782``, reset at cleanup in
  ``turn.py:1106``, post-filter in ``legal.py:880-893``), but Rust
  carries NO mirror (the comment at ``rust/src/state.rs:972`` is
  explicit), the bridge has no round-trip for the printing bool, and
  no loader admit disjunct admits the printing shape. Closure scope is
  contained-medium: one new Rust ``CardPrinting`` bool slot + one new
  ``Player`` ``noncreature_spells_cast_this_turn: i32`` counter +
  per-cast increment in Rust's noncreature-cast primitives +
  cleanup-step reset + cast-time gate in Rust's legal-decisions
  emitter + bidirectional bridge round-trip of the bool + one new
  ``_printing_is_bridge_simple_cast_restriction_enchantment`` admit
  disjunct + one real-EoE byte-equal probe. Deferred at 12 decks of
  leverage — substantially below the §4 sequencing thresholds. The
  hand re-walk renames the gate ``unclassified → static_rule_text``;
  see `docs/SEARCH_LIMITATIONS.md` "Deafening Silence — Rust does not
  mirror the noncreature-cast restriction" for the divergence pin.
* **Unclassified — Leyline of Mutation (1 card, 0 decks).** **2026-
  05-21 unclassified-residual hand re-walk** confirmed the genuine
  residual: the printing has TWO mechanics oracle-side ("If this card
  is in your opening hand, you may begin the game with it on the
  battlefield." + "You may pay ``{W}{U}{B}{R}{G}`` rather than pay the
  mana cost for spells you cast.") and the parser surfaces NEITHER —
  the printing has no leyline / opening-hand-into-battlefield field,
  no alternative-cost field, no triggered/static/activated/spell
  Effects, no covered Rust counterpart, no bridge carrier. Closure
  requires TWO new substrates (sprawling each): the opening-hand
  leyline mechanic AND the alternative-cost system. Leverage is
  0 decks (the card has 0 17lands appearances). Honest-stopped
  here — the named substrates would each take multi-round campaigns
  with zero in-pool leverage payoff today. See
  `docs/SEARCH_LIMITATIONS.md` "Leyline of Mutation — leyline + alt-
  cost mechanics unparseable" for the divergence pin.

## 6. New sub-gates revealed this session

The substrate closures revealed (or made tractable) a handful of
sub-gates that the original `ce564786` inventory didn't surface:

* **Static abilities Phase 3.5 — keyword-removal layer-6 fold +
  `ControlledArtifactEnteredThisTurn` Condition.** Surfaced by Mechan
  Shieldmate honest-stop in the Phase 3 merge (`ddd93684`); lane 1 in
  flight.
* **Aura Phase 4 S3 — token-replacement-effect substrate. CLOSED
  2026-05-21** (`b226fbf4` + `3dc1719d`). Moonlit Meditation flipped
  PROBED via `GameObject.token_supertype_override` +
  `moonlit_token_substitution` helper + loader admit widen + slug-
  credit delegator. (The "only un-shipped Aura sub-shape" wording
  is stale historical narrative.)
* **Aura S4 multi-gate composition** — Chorale of the Void / Cracked
  Skull / Sporogenic Infection each need their Aura half (shipped
  `35ede8b0`) + Effect-uncovered closure + nonsafe-trigger event bridge.
  These are now exactly that cleanly-decomposed.
  * **Verify-first walk on `feature/aura-s4-multigate-walk-p1`
    (2026-05-21) — all 3 multi-cycle; honest-stop, no PROBED flip.**
    Per-card scope as resolved by direct inspection of the printings'
    `triggered_abilities` tuples + Rust `Effect` enum / bridge arm /
    `_aura_triggers_are_phase3_safe` Phase-3 safe set:
    * **Chorale of the Void** (2,783 17lands decks). Two triggers.
      (a) `Event.ATTACKS + IsHost(subject='attacker') +
      ReanimateTargetCreatureCardFromDefendersGraveyard`
      (`src/mtg_bot/effects/generic/graveyard.py:474-549`) —
      **NO Rust `Effect` variant**; only
      `Effect::ReanimateOneExiledWithSourceWithCounters` exists
      (`rust/src/cards.rs:4478`), which is a wholly different
      reanimate shape (exile, not defenders' graveyard). The Python
      class targets `("graveyard_creature", id)` across all
      opponent graveyards, brings the card on tapped-and-attacking
      under the resolving controller, requires a NEW target_kind
      in Rust + cross-graveyard target enumeration + put-into-
      battlefield-tapped-and-attacking primitive (`obj.attacking =
      True`, `obj.summoning_sick = False` — combat-loop reads
      `attacking`). Also `IsHost(subject='attacker')` is a NEW
      predicate-subject-slot shape not in the Phase-3 admit set
      (only `subject=None` is admitted today). (b)
      `Event.BEGINNING_OF_END_STEP + Controlled(_Controller.YOU,
      subject=None) + SacrificeSelfUnlessVoidActive` — Rust
      `Effect::SacrificeSelfUnlessVoidActive` IS shipped
      (`cards.rs:4186`), bridge arm IS shipped
      (`cross_engine.py:8745`), `Predicate::ControlledByYou` IS
      shipped (`cards.rs:6130`), `Event::BeginningOfEndStep`
      dispatch IS wired (`cards.rs:5843`); the EoT half is admit-
      set-only. **Total: ≥2 cycles** (one Rust slice for the
      ATTACKS reanimate Effect + target_kind + IsHost-attacker
      subject expansion; one admit-set + cross-engine probe
      cycle).
    * **Cracked Skull** (650+ 17lands decks). Two triggers. (a)
      `Event.ENTERS + IsSelf + TargetOpponentLookHandMayDiscard`
      (`src/mtg_bot/effects/generic/discard.py:298-380`) — **NO
      Rust `Effect` variant**. Python class involves the one-way-
      reveal substrate (`reveal_to` per-card), a `may`-gate via
      `Agent.choose_yes_no`, and an agent-driven directed-discard
      target choice. Multiple decision-pump surfaces (look-at-
      hand reveal, may-gate, nonland-card choice). (b)
      `Event.DEALT_DAMAGE + IsHost + DestroyEnchantedPermanent` —
      Rust `Effect::DestroyEnchantedPermanent` IS shipped
      (`cards.rs:3581`), bridge arm IS shipped
      (`cross_engine.py:6594`), `Predicate::IsHost` IS shipped,
      `Event::DealtDamage` dispatch IS wired (`cards.rs:5962`);
      the dealt_damage half is admit-set-only. **Total: ≥2
      cycles** (one Rust slice for look-at-hand Effect +
      may-gate decision + directed-discard agent path; one
      admit-set + cross-engine probe cycle).
    * **Sporogenic Infection** (~500 17lands decks). Two triggers.
      (a) `Event.ENTERS + IsSelf +
      TargetOpponentSacrificesCreatureOtherThanEnchanted`
      (`src/mtg_bot/effects/generic/opponent_punishers.py:68-144`)
      — **NO Rust `Effect` variant**. Python class targets a
      player ("player", id), excludes the Aura's host
      (`attached_to` lookup at resolve), and routes through the
      target opponent's own `Agent.choose_sacrifice` — a NEW
      target_kind=`("player", id)` for an Effect that reads the
      target's battlefield + filter-excludes the host. (b) Same
      `Event.DEALT_DAMAGE + IsHost + DestroyEnchantedPermanent`
      tail as Cracked Skull (admit-set-only). **Total: ≥2
      cycles** (one Rust slice for target-opponent-sacrifice-
      other-than-host Effect + agent-driven sac choice; one
      admit-set + cross-engine probe cycle).
  * **Common admit-set widen these 3 cards would need.** Two
    Phase-3-safe new shapes share the workload across the three
    cards: `Event.DEALT_DAMAGE + IsHost(subject=None) +
    DestroyEnchantedPermanent` (used by Cracked Skull and
    Sporogenic Infection) + `Event.BEGINNING_OF_END_STEP +
    Controlled(YOU) + SacrificeSelfUnlessVoidActive` (used by
    Chorale of the Void). Both have full Rust+bridge coverage
    today — the admit-set extension alone is tractable, but
    cannot flip any of the 3 cards because each card's OTHER
    trigger surface carries an uncovered Effect. The admit-set
    widen would only matter once the first uncovered Effect
    on each card lands.
  * **Cheapest next slice (deferred from this walk).** Look-at-
    target-opponent's-hand + may-discard (Cracked Skull's ETB) is
    arguably the smallest of the three new Effect ports — it
    has no new target_kind (target-player is already a Rust
    target shape via several spell Effects) and the decision-
    pump primitives (`PendingDecision`-style may-gate) have
    sibling-shape precedent in the Command Bridge tap-permanent
    cost-decision pump (`PendingDecision::TapPermanentChoice`,
    `cards.rs:4187+`). Multi-step but bounded; a Round-N+1
    candidate after the admit-set add lands the dealt_damage tail.
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
  Phases 1+2+2.5+3 LANDED, Phase 4 first-deliverable (`6fa5ac9c`)
  + Phase 4 S3 substrate (`4dae568e`) LANDED + Phase 4 S3 consumer
  wire-up + Moonlit Meditation loader admit widen **CLOSED**
  (`b226fbf4` token-supertype-override + `3dc1719d` slug-credit
  delegator, 2026-05-21).
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
