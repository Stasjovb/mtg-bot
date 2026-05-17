# Sothera, the Supervoid — verify-first residue investigation

**Slice family:** `feature/docs-sothera-residue` (docs-only — no gate
regression possible; gate run to confirm clean).
**Live HEAD at investigation:** `8a2a8d84` (`git rev-parse HEAD` on
`main`, `Merge feature/fix-cfi1-depressurize-counters … gate 1514`).
**Source of truth:** Python `src/mtg_bot/` — the card's *actual parsed
card + resolve bodies*, NOT the triage prose. Every claim below is
verified against the live tree at `8a2a8d84`; the triage docs
(`EFFECT_UNCOVERED_TIERC_CLOSEST_TO_A.md` etc.) are cross-checked, not
trusted.

This doc is a **RECOMMENDATION ONLY**. It does NOT mutate
`docs/residue_worklist.json` (that file is orchestrator-resync-owned /
fenced — the next post-merge cron resync applies the recommended entry
after review). It also does NOT touch `docs/POOL_PARITY.md`,
`docs/SUBSYSTEM_ROADMAP.md`, or `docs/EOE_PROBE_READINESS_AUDIT.md`.

---

## 0. The carried obligation

"Sothera, the Supervoid" has been carried for ~5 orchestrator cycles in
the STALENESS-SENTINEL narrative as *"still flagged for the next residue
re-walk, genuinely_missing-shaped, 2,108 decks, NOT yet a worklist
entry"* (`docs/HANDOFF_CONTINUOUS_PIPELINE.md` §1/§3/§3a;
`docs/SUBSYSTEM_ROADMAP.md` cycle-2…6 folds;
`docs/EOE_PROBE_READINESS_AUDIT.md` ~line 321). It is an honest-residue
obligation that was flagged but never discharged into the
machine-readable worklist. This investigation discharges it with
verify-first ground truth.

---

## 1. The card (Scryfall ground truth)

`data/edge_of_eternities.json`:

- **Name:** Sothera, the Supervoid
- **Type:** Legendary Enchantment
- **Mana:** `{2}{B}{B}`
- **Oracle:**
  > Whenever a creature you control dies, each opponent chooses a
  > creature they control and exiles it.
  >
  > At the beginning of your end step, if a player controls no
  > creatures, sacrifice Sothera, then put a creature card exiled with
  > it onto the battlefield under your control with two additional
  > +1/+1 counters on it.

---

## 2. The exact Effect signature(s) — Python source of truth

Parsed live at `8a2a8d84` via
`OracleParserCardSource().get_printings()["Sothera, the Supervoid"]`.
The printing carries **two triggered abilities, no static / activated
abilities, no `spell_effect`, no `warp_cost`, not an Aura, not a
creature** (`is_enchantment=True`, `spell_effect=None`,
`warp_cost=None`, `is_aura=False`, `static_abilities=()`,
`activated_abilities=()`):

### TA 0 — the DIES trigger

```
TriggeredAbility(
    event=Event.DIES,
    predicate=And(Subject(IsCreature()), Controlled(by=YOU)),
    effect=EachOpponentExilesOwnCreature(link_to_source=True),
)
```

`EachOpponentExilesOwnCreature` is a bespoke Python `Effect` subclass in
`src/mtg_bot/effects/generic/opponent_punishers.py`. With
`link_to_source=True` every exiled object is tagged
`GameObject.exiled_by_source = state.resolving_source.id` so the sibling
end-step ability can later locate "a creature card exiled with it".

### TA 1 — the end-step recall + self-sac

```
TriggeredAbility(
    event=Event.BEGINNING_OF_END_STEP,
    predicate=And(Controlled(by=YOU),
                  StateBound(AnyPlayerControlsNoCreatures())),
    effect=Sequence(effects=(
        ReanimateOneExiledWithSourceWithCounters(counter_amount=2),
        SacrificeSelfPreservingExileLink(),
    )),
)
```

Both inner effects are bespoke Python `Effect` subclasses in
`src/mtg_bot/effects/generic/exile.py`.

### Why it is currently uncovered — the exact mechanism

It is a **3-class exile-link-bookkeeping composite** whose joint
correctness depends on a bespoke Python-only sub-substrate that has **no
Rust analogue at all**:

1. **`EachOpponentExilesOwnCreature(link_to_source=True)`** — per-opponent
   independent-choice exile; on link, writes
   `GameObject.exiled_by_source = source.id`.
2. **`ReanimateOneExiledWithSourceWithCounters(counter_amount=2)`** —
   walks every player's exile for `exiled_by_source == resolving_source.id`
   filtered to creatures, controller picks ONE, `put_into_battlefield`
   with +2 +1/+1 counters, and *clears the link on the recalled card*.
3. **`SacrificeSelfPreservingExileLink()`** — sets a one-shot
   `state.suppress_exiled_by_source_on_leave_for = source.id` flag
   immediately before sacrificing, so the engine's
   `_release_exiled_until_leaves` on-leave hook does NOT race the OTHER
   still-tagged cards back to their owners when Sothera leaves the
   battlefield (the printed text does not return them). The
   recall-first / sac-second ordering inside the `Sequence` is itself
   load-bearing for the same reason.

The composite therefore needs, in Rust: (a) three new `Effect::`
variants, (b) a `GameObject.exiled_by_source` source-link field on the
exile zone, (c) a `_release_exiled_until_leaves`-equivalent on-leave
auto-return hook, and (d) a one-shot `suppress_…_on_leave_for`
suppression flag the sac arm sets. None of (a)–(d) exists in the Rust
engine.

---

## 3. Ground-truth coverage check at `8a2a8d84`

`scripts/measure_effect_coverage.collect_rust_effect_variants()` →
**118 live Rust `Effect::` variants**. `split_bridge_arm_blocks()` /
the `_ta_dict_to_python_effect` arm scan → **128 wired bridge arms**.

| Python primitive | Rust `Effect::` variant? | Bridge arm? |
|---|---|---|
| `EachOpponentExilesOwnCreature` | **NO** (no `EachOpponentExiles*`; closest are `EachOpponentDiscards`, `EachOpponentSacrificesCreature`, `ExileEachOpponentsGraveyard` — all different effects) | **NO** |
| `ReanimateOneExiledWithSourceWithCounters` | **NO** (zero `Reanimate*` variants anywhere in the enum) | **NO** |
| `SacrificeSelfPreservingExileLink` | **NO** (`SacrificeSelf` exists but does NOT preserve/suppress the exile link) | **NO** |

Additional verify-first facts:

- The printed name **"Sothera"** appears **nowhere** in
  `src/mtg_bot/parity/cross_engine.py` (no Pulsar-shaped wired arm
  naming the card → no `name_in_arm_ack` is needed).
- None of the three plan-named effects, nor their acronym-aware
  snake_case forms (`each_opponent_exiles_own_creature`,
  `reanimate_one_exiled_with_source_with_counters`,
  `sacrifice_self_preserving_exile_link`), is a live Rust variant or a
  live bridge `kind`.
- The trajectory `_SAFE_TRIGGERS` allowlist cannot admit it either: it
  only carries simple single-effect `attacks/dies/enters/becomes_tapped`
  triggers with `_SAFE_EFFECT_KEYS` leaves (`create_token`,
  `draw_cards`, `gain_life`, `mill`, `scry_n`, `surveil`,
  `pump_self_until_eot`, `put_plus_one_counter_on_self`). Sothera's DIES
  effect is not a safe leaf and its predicate is `creature you control`
  (not `source_is_self`); its end-step `Sequence` is not even a
  `_SAFE_TRIGGERS` family. Loader-gated, correctly.

---

## 4. Real 17lands deck count — verified

Established scout method (`scripts/scout_r50_residue_deck_counts.py` —
distinct deck records in `data/17lands/eoe_decks.json.gz` whose `cards`
list contains the card name):

- Pool: **129,996 deck records**.
- Records containing "Sothera, the Supervoid": **2,108**.
- Distinct `(draft_id, build_index)` archetypes: **2,108** (identical —
  the record-level and archetype-level counts agree).

**The carried 2,108 figure is correct at live HEAD.**

---

## 5. Does any planned substrate reach it?

Checked against the three live planned-substrate design docs and the
trajectory allowlists:

- **spell-card-bridge Phase 1 / Phase 2**
  (`docs/SPELL_CARD_BRIDGE_PHASE1_DESIGN.md`) — admits single- /
  two-target *instant-and-sorcery spell effects*. Sothera has
  `spell_effect = None` (it is a Legendary Enchantment whose entire
  function is two triggered abilities). **Does not reach it.** The doc
  does not mention Sothera or any of its three primitives.
- **warp Phase 2** (`docs/WARP_COST_PHASE2_DESIGN.md`) — a 2-clause
  guardrail widening that admits **exactly one** card (Timeline Culler).
  Sothera has `warp_cost = None`. **Does not reach it.**
- **Tier-C target-seating sub-substrate**
  (`docs/TIERC_TARGET_SEATING_SUBSTRATE_DESIGN.md`) — admits
  `ATTACKS`/`ENTERS` + `source_is_self` + *targeted* single-trigger
  cards (Sunset Saboteur, Exosuit Savior). Sothera's triggers are
  `DIES` (predicate = creature you control, not source_is_self,
  non-targeted) and `BEGINNING_OF_END_STEP` (a `Sequence`, not a single
  targeted leaf). **Does not reach it.**
- **A known idiom / `_SAFE_*` widening** — ruled out in §3 (not a safe
  leaf; composite `Sequence`; non-self predicate; end-step family).

**No planned substrate reaches Sothera.** It is a true
permanent-residue card until/unless a dedicated bespoke Rust slice
ships the 3-variant + exile-link-bookkeeping sub-substrate. This matches
(and independently re-verifies, from the Python source rather than the
prose) the triage docs' ✗ "EXCLUDED — not reachable by any planned
substrate" classification, but the *reason* is now established from the
parsed card, not inherited.

---

## 6. Verdict

**`genuinely_missing`.** Verify-first ground truth at `8a2a8d84`:

- All three Python `Effect` primitives Sothera needs are bespoke
  Python-only — **zero Rust `Effect::` counterparts, zero bridge arms**.
- It is NOT reclassifiable: it is not `closed` (no shipped+bridged
  variant), and it is NOT `blocked_non_effect` (a `blocked_non_effect`
  entry requires the Effect arms to *already be shipped* in Rust and the
  blocker to be a non-Effect gate — here the Effect arms themselves are
  genuinely absent, so the blocker IS a new-Rust-Effect ask).
- It is a TRUE new-Rust-Effect ask (multi-class exile-link composite),
  so it belongs in the load-bearing "how far from parity"
  `genuinely_missing` count.
- 2,108 17lands decks (verified). No planned substrate reaches it.

**Recommendation: ADD a `genuinely_missing` worklist entry.** (NOT
recommend-against — the verify-first walk confirms genuine absence, not
coverage.)

---

## 7. Recommended schema-correct `residue_worklist.json` entry

To be applied by the orchestrator resync into `docs/residue_worklist.json`
`entries` (this slice does NOT apply it). One entry — the card has a
single coherent composite surface (the DIES exile arm and the end-step
recall+sac arm are not independently shippable; they share the
`exiled_by_source` linkage and the suppression flag, so a single entry
correctly models the residue, exactly like Lightstall Inquisitor's
*fused* composite is one ask even though the oracle has two clauses —
the difference is Lightstall has two SEPARATE `genuinely_missing` rows
for two genuinely independent unshipped arms; Sothera's two arms are
ONE inseparable exile-link substrate, so one row is correct):

```json
{
  "entry": "SotheraSupervoid-exile-link-composite",
  "card": "Sothera, the Supervoid",
  "claimed_missing_effect": "EachOpponentExilesOwnCreature",
  "aliases": [
    "EachOpponentExilesOwnCreature",
    "ReanimateOneExiledWithSourceWithCounters",
    "SacrificeSelfPreservingExileLink"
  ],
  "status": "genuinely_missing",
  "verified_absent_at_commit": "8a2a8d84",
  "note": "Legendary Enchantment, no spell_effect / warp_cost / Aura / static / activated. Two triggered abilities, both bespoke-Python-only: (1) Event.DIES (creature you control) -> EachOpponentExilesOwnCreature(link_to_source=True); (2) Event.BEGINNING_OF_END_STEP (you + AnyPlayerControlsNoCreatures) -> Sequence(ReanimateOneExiledWithSourceWithCounters(counter_amount=2), SacrificeSelfPreservingExileLink()). 3-class exile-link-bookkeeping composite: needs 3 new Rust Effect:: variants PLUS a GameObject.exiled_by_source source-link field, a _release_exiled_until_leaves-equivalent on-leave auto-return hook, and a one-shot suppress_..._on_leave_for flag the sac arm sets (recall-first/sac-second ordering load-bearing). Verified genuinely absent at 8a2a8d84 (verify-first residue investigation, OracleParserCardSource live parse): NONE of the 3 effects is in the live 118-variant Rust Effect:: enum (no EachOpponentExiles*, zero Reanimate*, SacrificeSelf exists but does not preserve the link); none resolves to a live bridge kind; printed name 'Sothera' in NO wired bridge arm (no name_in_arm_ack needed). 2,108 17lands decks (scout_r50 method, record-level == distinct-archetype). No planned substrate reaches it (spell-card-bridge needs spell_effect=None != None; warp P2 needs warp_cost; Tier-C target-seating needs ATTACKS/ENTERS source_is_self targeted; _SAFE_TRIGGERS cannot admit a Sequence/non-self-predicate). TRUE new-Rust-Effect ask; permanent-residue until a dedicated bespoke Rust slice. Discharges the ~5-cycle STALENESS-SENTINEL Sothera carry-forward."
}
```

### Field rationale

- **`status`: `genuinely_missing`** — the load-bearing bucket; the
  Effect arms are genuinely absent (not shipped-but-gated → not
  `blocked_non_effect`; not shipped+bridged → not `closed`).
- **`aliases`** — all three plan-named effects listed; the LEXICAL arm
  walks them against the live Rust enum and (verified) none resolves, so
  the entry asserts genuine absence and does NOT self-contradict.
  `claimed_missing_effect` is the first/primary one (the DIES arm),
  matching the existing-entry convention (e.g. Lightstall Inquisitor).
- **`verified_absent_at_commit`: `8a2a8d84`** — the live HEAD at which
  genuine absence was re-verified (live enum + bridge + name-in-arm).
  SHA-shaped (8 hex). Required on `genuinely_missing`.
- **No `resolved_variant` / `shipped_variants` / `non_effect_blocker` /
  `name_in_arm_ack`** — those are for `closed` /
  `blocked_non_effect` / Pulsar-ack entries only; correctly omitted on
  a `genuinely_missing` entry per the round-55/56 schema.

---

## 8. Cron residue-consistency invariants checked

Simulated against `scripts/check_audit_coverage_staleness.py` at
`8a2a8d84` (loaded the module, ran the actual functions with the
proposed entry appended to the live `entries` list):

| Cron arm | Result for the proposed entry |
|---|---|
| **`parse_residue_worklist` schema** (status enum; non-empty `aliases`; no `resolved_variant` required since not `closed`; no `shipped_variants`/`non_effect_blocker` required since not `blocked_non_effect`) | **PASS** — valid `genuinely_missing` shape |
| **LEXICAL arm (round-54)** `compute_residue_staleness` — a `genuinely_missing` entry whose alias resolves to a live Rust variant is `residue_stale` | **PASS** — `resolve_residue_entry` → `resolved_variant=None`, `bridged=False`; no `residue_stale` row |
| **STRUCTURAL arm 5a (round-55)** — every `genuinely_missing` entry must carry a SHA-shaped `verified_absent_at_commit` | **PASS** — `8a2a8d84` present, SHA-shaped → no `residue_unverified` |
| **STRUCTURAL arm 5b (round-55, cadence)** — stamp stale if any commit after it touched `rust/src/cards.rs` / `cross_engine.py` | **PASS** — `commits_touching_trigger_paths_since("8a2a8d84")` == `0` (it IS HEAD) → no `residue_needs_reverify` |
| **STRUCTURAL arm 5c (round-55, non-lexical Pulsar catch)** — printed name in a live wired bridge arm | **PASS** — `_card_name_variants("Sothera, the Supervoid")` matched in **zero** bridge-arm blocks → no `residue_suspect_needs_reverify` / `residue_stale`; no `name_in_arm_ack` needed |
| **`blocked_non_effect` arm (round-56)** | **N/A** — entry is `genuinely_missing`, out of scope (correctly skipped) |
| **Cross-entry consistency (round-63)** `compute_card_status_consistency` — a card with rows MIXING `genuinely_missing` and a reclassified-out status is `residue_card_status_conflict` | **PASS** — "Sothera, the Supervoid" appears in **no other worklist entry**; single `genuinely_missing` row → no mix → no conflict row |
| **Internal self-contradiction** (the entry asserting absence while its own data proves presence) | **PASS** — no alias resolves; absence claim is internally consistent with the live tree |

The recommended entry is **internally consistent and clean across every
residue-consistency invariant the cron enforces** — adding it keeps the
staleness cron EXIT-0 in-sync (it adds exactly one to the honest
`genuinely_missing` count: 7 → 8 cards, all still genuinely absent).

---

## 9. Honest residue impact (informational — orchestrator owns the docs)

If the orchestrator applies this entry at the next resync, the honest
"how far from parity" `genuinely_missing` count moves **7 → 8 cards**
(the prior 7: Lightstall Inquisitor ×2 arms, Command Bridge, Astelli
Reclaimer, Pain for All, Meltstrider's Resolve, Roving Actuator — plus
Sothera). This is NOT a pool-coverage regression — it is the honest
*recognition* of a residue that was always there but carried only in
prose for ~5 cycles. The ~5-cycle STALENESS-SENTINEL Sothera
carry-forward is now discharged into the machine-readable worklist
shape; the sentinel narrative line ("still flagged for the next residue
re-walk, NOT yet a worklist entry") can be retired by the orchestrator
when it applies this entry.
