# Covered-by-construction probe-writing lane — saturation report (2026-05-25)

## Headline

The bare-bridge-clean Effect-class probe-writing lane (batches 1-13;
~62 cards flipped `covered_by_construction → PROBED` over 13 batches
across 2026-05-24 → 2026-05-25) is **effectively saturated** at PROBED
381 / covered_by_construction 38 / BLOCKED-SG 56 / pool 475.

Batch 13 was the last bare-bridge-clean batch under the established
EEEE-idiom (parse + bridge round-trip + Python-side resolve, NO
cross-engine `compare_fields`; per-slug attribution credits a PROBED
slot per-printing via the module-scope `_PRINTINGS = get_active_source(
).get_printings()` idiom).  It shipped **2 probes**:

  * **Plaza of Heroes** — Land (Stellar Sights reprint, 0 17lands
    decks).  Binds AA[0]'s bare colorless-mana `AddManaToPool(
    produces=(('C', 1),), spend_restriction=None)`.  Per-slug
    attribution flips the WHOLE 4-AA slug via AA[0]'s bridge-clean
    half (AA[1]/[2] have spend_restriction; AA[3] has granted_keywords
    pump — both bridge-drop riders).
  * **Rust Harvester** — Artifact Creature — Robot ({R}, 0 17lands
    decks).  Binds AA[0]'s `Sequence(PutPlusOneCounterOnSelf,
    DealDamageEqualToSourcePowerAnyTarget)`.  The HH-blocked
    `exile_artifact_from_graveyard` cost rider is sidestepped by the
    EEEE-idiom (Effect resolve only, no cost surface exercised).

After batch 13: **+2 PROBED / -2 covered_by_construction** (PROBED
379 → 381; covered_by_construction 40 → 38; BLOCKED-SG 56 unchanged;
pool total 475 unchanged).

## Per-card scout — the remaining 38 covered_by_construction cards

Each of the 38 cards was checked for bare-bridge-clean byte-equality
against `_ta_dict_to_python_effect` round-trip.  None pass cleanly
under the established per-Effect-class precedent.  Categorised by
**rider class** (the specific bridge-drop reason):

### A. BecomeLandCreatureUEOT (creature-lands) — 9 cards

BLOCKED per the batch-8 HH directive: `BecomeLandCreatureUEOT` is
listed as a blocked Effect class (per the HH-module skip-list at
`tests/test_probe_activated_abilities_hh.py:67-71`).  The
`become_land_creature_ueot` bridge arm exists, but the
`granted_keywords` / `unblockable` / `granted_subtype` /
`granted_activated_abilities` / `granted_triggered_abilities` riders
all drop on round-trip.

  - Celestial Colonnade  (flying, vigilance)
  - Creeping Tar Pit     (unblockable=True)
  - Hissing Quagmire     (deathtouch)
  - Inkmoth Nexus        (flying, infect)
  - Lumbering Falls      (hexproof)
  - Needle Spires        (double strike)
  - Raging Ravine        (attacks-counter triggered ability rider)
  - Shambling Vent       (lifelink)
  - Stirring Wildwood    (reach)

### B. PumpTargetCreatureUntilEOT / PumpSelfUntilEOT with granted_keywords — 8 cards

BLOCKED per the HH directive: "granted_keywords on pump arms blocked"
(`tests/test_probe_activated_abilities_hh.py:89-90`).

  - Cult Healer           (PumpSelfUntilEOT lifelink, Room ETB rider)
  - Dual-Sun Technique    (PumpTargetCreatureUntilEOT double strike + draw rider)
  - Flesh Burrower        (PumpTargetCreatureUntilEOT deathtouch attacks rider)
  - Give In to Violence   (PumpTargetCreatureUntilEOT lifelink +2/+2)
  - Hand That Feeds       (PumpSelfUntilEOT menace + Delirium predicate)
  - Horrid Vigor          (PumpTargetCreatureUntilEOT indestructible + deathtouch)
  - Kavaron Turbodrone    (PumpTargetCreatureUntilEOT haste — HH-blocked example)
  - Rig for War           (PumpTargetCreatureUntilEOT reach + first strike)
  - Violent Urge          (PumpTargetCreatureUntilEOT first strike)

### C. AddManaToPool with spend_restriction or multi-color batch — 4 cards

The `add_mana_to_pool` bridge arm is **scalar-only** (single
`color`/`amount` per Effect; multi-color batched mint is "Rust
substrate would need schema bump first" per
`src/mtg_bot/parity/cross_engine.py:7386-7398`).  The bridge has no
`spend_restriction` field translation (per Mana Confluence probe's
explicit disclaimer at `tests/test_mana_confluence_parity.py:99-101`).

  - Crystal Quarry        (multi-color batched WUBRG mint)
  - Power Depot           (spend_restriction='artifact_spell')
  - Steelswarm Operator   (spend_restriction='artifact_spell' / 'artifact_activation')
  - (Plaza of Heroes AA[1]/[2] also fall here; AA[0] is the
    bridge-clean half this batch probed.)

### D. Bridge arm absent (Python class with no Rust counterpart's bridge dispatch) — 7 cards

Effect class is coverage-listed (Python class → Rust variant exists),
but the bridge `_ta_dict_to_python_effect` arm is unimplemented (would
need a slice landing first).

  - Clammy Prowler        (GrantUnblockableUEOT — no `grant_unblockable_ueot` arm)
  - Vanish from Sight     (OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary — no arm)
  - Let's Play a Game     (mode-0 PumpCreaturesOpponentsControlUntilEOT — no arm)
  - Temporal Intervention (TargetOpponentDiscardsCasterChoice — bridge produces
                           TargetOpponentDiscards (count=1) instead, not byte-equal)
  - Unnerving Grasp       (ReturnTargetCreatureToOwnersHand — bridge produces
                           parent class `Bounce`, not byte-equal)
  - Requiem Monolith      (GrantTriggeredAbilityUEOT — no arm)
  - Dawnsire, Sunstar Dreadnought (Spacecraft Station-gated; tier_threshold=10;
                                   also no `deal_damage_to_target_creature` arm)

### E. Narrowed-form Effects (bridge produces bare/unrestricted form) — 4 cards

The bridge constructs the bare/unrestricted variant; the parser-emit
narrowed form (with min_power / tapped_only / untapped_only /
nonbasic_only / target-filter rider) drops on round-trip.

  - Split Up              (DestroyAllCreatures tapped_only=True / untapped_only=True modes)
  - Restricted Office // Lecture Hall (DestroyAllCreatures min_power=3 + Room subsystem)
  - Dust Bowl             (DestroyTargetLand nonbasic_only=True + ObjectAnd-filtered target)
  - Lithobraking          (CreateToken Lander w/ AA + OptionalSacArtifactForEffect wrapper)

### F. CreateToken with bridge-arm `register_token_printing` ceremony scoped out — 3 cards

Per the JJJJ Funeral Room half-coverage precedent
(`tests/test_cosmogrand_zenith_parity.py:47-61` documents the
convention): EEEE-idiom-style Python-resolve-only probes
**intentionally skip** the `create_token` bridge arm's
`register_token_printing(pid, py_printing)` ceremony.  Cards whose
ONLY emitted Effect is CreateToken (no other bridge-clean mode to
fall back to) stay covered.

  - Weapons Manufacturing (only Effect is CreateToken w/ complex predicate)
  - Sami, Ship's Engineer (ConditionalOnTappedCreatures wrapping
                           CreateToken with tapped=True rider — also Effect-level mismatch)
  - Grand Entryway // Elegant Rotunda (Room + CreateToken Glimmer)

### G. Room / Spacecraft / Aura subsystems — 3 cards

  - Mirror Room // Fractured Realm (Room subsystem)
  - Duskmourn's Domination         (Aura — emits 0 Effects, only attached_grants riders)
  - (Restricted Office overlaps category E + Room — counted there.)

### H. Deafening Silence — synthetic-CardDef probe deliberately not registered

Per the prior PROBE_MODULES skip-rationale at
`scripts/measure_pool_parity.py:1271-1292`:
`test_deafening_silence_parity.py`'s probe drives a SYNTHETIC
`CardDef(name="Deafening Silence", ...)` carrier through the bridge,
NOT the live parsed printing via `get_printings()`.  Flipping
honestly would need a per-probe rewrite to bind the live printing
first — deferred to a separate lane.

## Net session yield (batches 1-13)

| Metric                       | pre-batch-1 (2026-05-23) | post-batch-13 (2026-05-25) | Delta |
|------------------------------|--------:|--------:|------:|
| PROBED                       | ~319    | 381     | +62   |
| covered_by_construction      | ~100    | 38      | -62   |
| BLOCKED-SG (subsystem-gated) | 56      | 56      | 0     |
| Pool total                   | 475     | 475     | 0     |

The lane closed ~62 covered_by_construction slugs via the per-slug
attribution precedent + EEEE-idiom (parse + bridge round-trip +
Python-side resolve).  Plaza of Heroes + Rust Harvester are the
**LAST bare-bridge-clean cards** in the pool under this idiom.

## Recommended next direction

The remaining 38 covered_by_construction cards all carry **structural
bridge-drop riders** that cannot be flipped under the established
per-slug attribution precedent without either:

  1. **Rust schema bumps** for the rider fields (e.g.,
     `BecomeLandCreatureUEOT.granted_keywords`,
     `AddManaToPool.spend_restriction`,
     `PumpTargetCreatureUntilEOT.granted_keywords`,
     `DestroyAllCreatures.tapped_only`/`min_power`,
     `DestroyTargetLand.nonbasic_only`).  Each rider closure ships as
     a separate Rust schema bump + bridge arm widen + per-card probe.
     Per-card yield: ~1-5 cards per slice; per-slice cost: medium
     (Rust + bridge + probe + parity tests).
  2. **Pivot to the major BLOCKED-SG subsystems** (the long blocked
     tail).  The deck-count leverage signal favours these for
     volume:

     | Subsystem | #cards | decks(tot) | 1gate | decks(1g) | Tractability |
     |---|---:|---:|---:|---:|---|
     | **Carrier activated abilities**          | 30 | 34,470 |  0 |     0 | sprawling |
     | **Non-safe triggered ability**           | 20 | 53,848 |  0 |     0 | diffuse |
     | **Effect-uncovered**                     | 45 | 76,035 |  0 |     0 | diffuse |
     | Station / Spacecraft                     |  8 | 41,281 |  1 | 5,938 | sprawling |
     | Static / layered abilities               |  8 | 15,558 |  2 |     0 | sprawling |
     | Cost-reduction substrate                 |  1 | 13,165 |  1 | 13,165| medium |
     | warp_cost (declined cost-mechanic)       |  3 |  8,903 |  0 |     0 | medium |
     | Non-basic land substrate                 |  2 |  7,688 |  2 | 7,688 | medium |
     | Kicker / Impending cost                  |  1 |  6,090 |  0 |     0 | medium |
     | Aura-attachment substrate                |  3 |  2,783 |  0 |     0 | sprawling |
     | Planeswalker loyalty                     |  1 |  2,311 |  0 |     0 | sprawling |
     | Rooms / doors                            |  3 |      0 |  0 |     0 | sprawling |

### Recommendation: **Carrier-AA substrate widening**

The largest still-blocked subsystem at 30 cards / 34,470 17lands
decks (the second-highest cumulative deck-count signal after the
sprawling "Effect-uncovered" residue, but the latter is diffuse —
no single substrate widen unlocks multiple cards).  Carrier-AA
widening has structural unity: every BLOCKED-SG Carrier-AA card
shares the same loader-admit-gate question (does the production
deck loader's `_printing_is_bridge_*` predicate accept the AA list
shape, or does it §2-decline on the activated-abilities non-emptiness
check?).  A single substrate widen here could unblock multiple slugs
under a unified admit gate.

Sibling already-PROBED cards (Plaza of Heroes, Mana Confluence,
Cascading Cataracts, High Market, Eldrazi Temple, Adagia, Sunken
Citadel, Sami's Curiosity) all PROBED via the bare-bridge-clean
per-slug idiom; Carrier-AA widening would target the broader pool
of cards with **non-mana** AAs (Sami's Curiosity-style ETB / on-
attack / activated-pump cards).

Alternative pivot: **Aura-attachment substrate widening** (3 cards
/ 2,783 decks, the smaller substrate but a self-contained
subsystem).  Or the **Cost-reduction substrate** (1 card / 13,165
decks — single-card high-leverage slice).

## Related precedents

  - **HH-module skip list** at
    `tests/test_probe_activated_abilities_hh.py:50-99`: the
    canonical "what's blocked per directive" reference (Equipment,
    BecomeLandCreatureUEOT, granted_keywords on pump arms, several
    cost mechanics).
  - **Mana Confluence probe** at
    `tests/test_mana_confluence_parity.py:99-101`: the canonical
    spend_restriction-blocked precedent.
  - **Cosmogrand Zenith probe** at
    `tests/test_cosmogrand_zenith_parity.py:47-61`: the canonical
    create_token-bridge-arm-scoped-out (JJJJ half-coverage)
    precedent.
  - **Blazemire Verge probe** at
    `tests/test_blazemire_verge_parity.py`: the canonical
    parser-emit dual-AA AddManaToPool precedent (sibling to Plaza
    of Heroes AA[0]).
  - **Conductive Machete probe** at
    `tests/test_conductive_machete_parity.py`: the canonical
    Sequence-composer composite Effect precedent (sibling to Rust
    Harvester AA[0]'s 2-arm composite).
  - **Subsystem leverage analysis** at `docs/SUBSYSTEM_ROADMAP.md`:
    the data-driven "which subsystem next" instrument that the
    BLOCKED-SG breakout table above reads from.

## Operational note

The 2-probe shipment in batch 13 is a **deliberate small batch**
sized to confirm saturation rather than starve the lane.  The
preceding batch (batch 12, 5 probes) had already documented "the
bare-bridge-clean candidate pool may be exhausted" — batch 13 is
the confirmatory landing.  Subsequent campaigns should NOT plan
another covered_by_construction-probe-writing batch under this
idiom; the next probe-writing campaign should attack one of the
recommended pivots above.
