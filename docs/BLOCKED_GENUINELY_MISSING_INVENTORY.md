# BLOCKED-genuinely_missing inventory + closure-scope estimates

Canonical focused inventory of the **4 EoE cards** currently in the
`BLOCKED — genuinely_missing` tier (`docs/POOL_PARITY.md`) — the cards
that need a brand-new Rust `Effect::` variant + parse + bridge before
they can be byte-equal cross-engine. This is the **post-flip long-tail
sequencing guide**: every other parity work is BLOCKED-non-effect (2
cards), BLOCKED-subsystem-gated (149 cards, see
`docs/SUBSYSTEM_ROADMAP.md`), or PROBED/covered (320 cards).

**Snapshot HEAD:** post-slice-19-merge (2026-05-20).
**Source of truth:** `docs/residue_worklist.json` (the residue
worklist's per-card re-walk is the AUTHORITY on genuine Effect absence
— round-63 N5 verify-first re-walk at `e6f95002`). The 4 cards below
are the entirety of the load-bearing "how far from parity" residue.

**Slice 19 update (honest-stop substrate landing for Meltstrider's
Resolve).** Meltstrider's Resolve's Effect-level scaffolding shipped
(Rust `Effect::EnchantedCreatureFightsTarget` + parse + to_pydict +
bridge + honest-stop resolve arm) — `docs/residue_worklist.json`
flipped its status to `closed` with `reclassified_to: BLOCKED-SUBSYSTEM
(Aura attach substrate)`. The card now sits in the
`subsystem-gated / Effect-uncovered` tier under the
**Aura-attachment substrate** subsystem (per
`docs/AURA_ATTACHMENT_SUBSTRATE_PLAN.md`) rather than the
genuinely-missing tier. **Full byte-equality for the real Meltstrider's
Resolve card is NOT yet shipped — the broader Aura attach substrate
remains the deferred bottleneck.** See `docs/AURA_ATTACHMENT_SUBSTRATE_PLAN.md`
for the Phase 1-4 plan; the substrate is the **largest §2-declined
Rust multi-round substrate audited so far** (5-7 Rust-agent rounds
end-to-end). The same applies to Pain for All's scope estimate (#3
below): the **shared Aura attach substrate has NOT yet landed**, so
Pain for All's residual scope stays **medium** (NOT "small") — the
substrate-sharing flip only fires once Phase 1 of the substrate plan
ships.

**Total deck reach of this tier:** 35,368 decks (sum of the per-card
counts below: Command Bridge 24,522 + Lightstall Inquisitor 4,371 +
Pain for All 4,367 + Sothera 2,108). Some decks contain multiple
genuinely-missing cards, so this is an upper bound on the union —
closing the whole tier moves fewer than 35,368 distinct decks but
no more, see §Sequencing. Meltstrider's Resolve's 15,259 decks are
NOT in this tier; they're carried under the Aura subsystem in
`docs/POOL_PARITY.md`.

---

## At a glance

| Card | bespoke.py (or generic) class | LoC | 17lands decks | Substrate ask | Scope |
|---|---|---:|---:|---|---|
| Command Bridge — CLOSED (slice 20) | `effects/combinators.py::SacrificeSelfUnlessTapPermanent` | 95-168 | 24,522 | land-ETB-trigger plumbing (already wired) + tap-a-permanent agent decision (PendingDecision::TapPermanentChoice landed) | n/a (CLOSED) |
| Lightstall Inquisitor | `effects/generic/discard.py::EachOpponentExilesCardFromHandWithCastPermission` | 173-214 | 4,371 | persistent `cast_from_exile_with_lightstall_surcharge` flag + cost-hike legality | large (6+) |
| Pain for All | `bespoke.py::PainForAllETBEffect` + `::PainForAllDamageEchoEffect` | 352-463 | 4,367 | Aura `attached_to` damage source + dealt-damage event echo (substrate-shared with Meltstrider's Resolve) | medium (3-5) |
| Sothera, the Supervoid | `effects/generic/exile.py::ReanimateOneExiledWithSourceWithCounters` + `::SacrificeSelfPreservingExileLink` + `effects/generic/opponent_punishers.py::EachOpponentExilesOwnCreature` | 149-217 / 1122-1216 / 1221-1273 | 2,108 | `GameObject.exiled_by_source` source-link + on-leave auto-return suppression + recall-first/sac-second ordering | large (6+) |

**Recently closed (now sitting in the Aura subsystem tier of
`docs/POOL_PARITY.md`):**

| Card | Closure slice | Substrate landed | Substrate deferred |
|---|---|---|---|
| Roving Actuator | 18th (slice 18) | `Effect::RovingActuatorETBEffect { max_mv: u8 }` + parse + resolve + bridge — Effect closed AND full game byte-equal under the short-circuit-the-stack shortcut | n/a (the short-circuit-the-stack shortcut closes the full card) |
| Meltstrider's Resolve | 19th (slice 19, honest-stop) | `Effect::EnchantedCreatureFightsTarget` unit variant + parse + to_pydict + bridge + honest-stop resolve arm (Effect-level closure) | Aura attach substrate Phases 1-2 per `docs/AURA_ATTACHMENT_SUBSTRATE_PLAN.md` — `attached_to` is never set on Rust Aura resolve today; the loader admits no Aura. Full byte-equal of the real card requires this substrate. |

Scope key (calibrated against this session's slices):

- **small (1-2 cycles)** — single new `Effect::` variant; reuses
  existing parse + bridge + resolve idioms; sibling-variant precedent
  available. Astelli Reclaimer (slice 16) was small-medium with the
  Famished Worldsire sibling precedent.
- **medium (3-5 cycles)** — new `Effect::` variant + needs a small new
  substrate (event-bridge, source-link tag, attached_to dereference)
  but no new persistent subsystem. House Cartographer's library-walk
  fits this bucket.
- **large (6+ cycles)** — new persistent flag / subsystem on
  GameObject or GameState that has to be honored across legal-action
  generation + cost-paying + cleanup. Lightstall's
  cast-from-exile-with-cost-hike is the canonical large.

---

## Per-card detail

### 1. Command Bridge — 24,522 decks — CLOSED (slice 20)

**Status:** CLOSED in the 20th Rust slice (2026-05-20). Full Effect-
level + cost-decision-pump closure shipped. `Effect::SacrificeSelf
UnlessTapPermanent` variant + parse + to_pydict + resolve + bridge all
shipped. New `PendingDecision::TapPermanentChoice` cost-decision
substrate landed (the "tap a permanent as alternative to sacrifice"
pump — re-usable by any future "sac unless tap X" shape). Land-ETB-
dispatch wiring was already in place (`move_from_hand_to_battlefield`
queues `pending_etb_dispatches` + drains, same path creature ETBs
take). No deferred substrate.

- **Bespoke class:** `src/mtg_bot/effects/combinators.py:95-168`
  (`SacrificeSelfUnlessTapPermanent`).
- **Real parse:** Land. `Event.ENTERS → SacrificeSelfUnlessTapPermanent`
  PLUS a separate `{T}: Add {color}` activated mana ability (already
  shipped through the `add_mana_to_pool` arm).
- **Effect variant LANDED (slice 20):**
  `Effect::SacrificeSelfUnlessTapPermanent` (unit variant; source +
  controller read from `state.resolving_source` at resolve time,
  mirroring the Python convention).
- **Substrate landed in slice 20:**
  - The Rust enum variant + parse + to_pydict + bridge arms ship the
    Effect-level closure.
  - Resolve arm in `state_ops_resolve.rs` locates the source on its
    controller's bf, builds the untapped-permanent candidate set
    (source excluded), short-circuits to sacrifice when empty, or
    pushes `PendingDecision::TapPermanentChoice` when non-empty.
  - New `PendingDecision::TapPermanentChoice` variant in `state.rs`
    + `submit_tap_permanent_decision(Option<u32>)` dispatcher in
    `state_ops_decisions.rs` (Some(id) -> tap that permanent, keep
    source; None -> decline, sacrifice source).
  - Auto-resolve strategies `"tap_permanent_decline"` (default-
    decline; matches Python's no-agent fallback) and
    `"tap_permanent_first"` (deterministic first-candidate tap for
    test fixtures).
  - Shared `sacrifice_source_for_tap_decline` helper on
    `state_ops_resolve.rs` (LTB / IS_SACRIFICED / token-cease
    triple-push reused across the empty-candidate fast path and
    the decline-via-submit path).
- **Per-deck leverage on FULL-card closure:** 24,522 decks
  unblocked at the Effect-and-cost-decision level. Land-ETB
  dispatch was already wired (`move_from_hand_to_battlefield`),
  so the full ETB resolves end-to-end without any deferred
  substrate. See `docs/residue_worklist.json` entry
  `CommandBridge-sacrifice-unless-tap`.

### 2. Meltstrider's Resolve — 15,259 decks — HONEST-STOP CLOSURE (slice 19)

**Status:** Effect-level scaffolding LANDED in slice 19; full byte-equal
of the real card still BLOCKED on the Aura attach substrate (now sitting
in the Aura-attachment subsystem tier of `docs/POOL_PARITY.md`, NOT
genuinely-missing).

- **Bespoke class:** `src/mtg_bot/effects/bespoke.py:507-582`
  (`EnchantedCreatureFightsTargetEffect`).
- **Real parse:** Aura. `Event.ENTERS → EnchantedCreatureFightsTarget
  Effect` ("enchanted creature fights up to one target creature an
  opponent controls"). The bare-bilateral
  `FightTargetCreatureWithTargetCreature` arm IS shipped + bridged
  (`name_in_arm_ack: fight_target_creature_with_target_creature`); the
  Aura-shape source-substitution was the genuine ask.
- **Effect variant LANDED (slice 19):** `Effect::EnchantedCreatureFightsTarget`
  (unit variant; Aura-shape; source fighter = the Aura's `attached_to`,
  read at resolve time).
- **Substrate landed in slice 19:**
  - The Rust enum variant + parse + to_pydict + bridge arms ship the
    Effect-level closure (round-trip dict-shape consistency).
  - Resolve arm in `state_ops_resolve.rs` reads `source.attached_to`
    and silently fizzles when None (the **honest-stop branch** — Rust
    today does NOT set `attached_to` on Aura resolution, so this is
    the byte-equal-with-Python branch for every Rust Aura under the
    current substrate; Python takes the same fizzle at
    `bespoke.py:546-548`).
  - The full simultaneous-damage logic IS shipped behind the honest-
    stop branch and exercised today via `state.attach(aura_id,
    host_id)` test primitive in `test_probe_yyy_downstream.py`.
- **Substrate STILL DEFERRED (the multi-round Aura attach plan):**
  - `CardDef` aura representation (`is_aura`, `aura_enchant_type`,
    `aura_yours_only`, `equipment_bonuses`, `attached_grants_*`).
  - Rust cast-time enchant-target decision (Auras pick their host
    at cast, CR 303.4 / 601.2c).
  - Rust Aura-resolution attach path (today only Equipment ETB sets
    `attached_to`).
  - CR 704.5n SBA (bury Aura with no legal host) + host-leave bury.
  - Bidirectional bridge arms for the aura fields.
  - Loader admit predicate `_printing_is_bridge_simple_aura`.
  - See `docs/AURA_ATTACHMENT_SUBSTRATE_PLAN.md` Phases 1-2 —
    estimated 5-7 Rust-agent rounds end-to-end; the **largest
    §2-declined Rust multi-round substrate** audited to date.
- **Substrate-thinness check (slice 19 task brief):** Re-verified
  DEEPER than the "small (1-2 cycles)" estimate that was in this
  inventory at slice-19 start. The verify-first re-walk in
  `docs/AURA_ATTACHMENT_SUBSTRATE_PLAN.md` §2 confirms full Aura
  attach is a sprawling multi-round substrate, not a one-off
  field-dereference. Slice 19's honest-stop closure ships the
  Effect-level scaffolding now and documents the multi-round
  follow-up; it does NOT spiral into the broader substrate.
- **Per-deck leverage on FULL-card closure:** 15,259 decks gated
  behind the multi-round Aura attach substrate (NOT a near-term
  win on top of slice 19). The Effect-level scaffolding makes the
  hot-path branch ready-to-flip when the substrate's Phase 1
  ships, but the *real-EoE* byte-equal game-trajectory still
  requires the full substrate.

### 3. Lightstall Inquisitor — 4,371 decks

- **Bespoke class:** `src/mtg_bot/effects/generic/discard.py:173-214`
  (`EachOpponentExilesCardFromHandWithCastPermission`).
- **Real parse:** ETB triggered ability. One bespoke composite Effect
  fusing both halves of the oracle text: each opponent exiles a card
  from hand + may play that card while exiled + {1} surcharge + tapped
  land entry.
- **Effect variants needed:** two genuinely_missing worklist entries
  for the same card:
  - `Effect::EachOpponentExilesFromHand` (the exile-from-hand half)
  - `Effect::CastFromExileWithCostHike` (the cast-from-exile half +
    {1} surcharge + tapped land entry rider)
  - In practice the real parse fuses them into ONE composite arm
    matching the Python — a single composite variant, not two
    independent ones.
- **Substrate dependencies:**
  - Persistent `cast_from_exile_with_lightstall_surcharge` flag on the
    `GameObject` for each exiled card — survives across turns, lives
    on the card while in exile, drives legal-actions to surface
    CastSpell/PlayLand from exile.
  - Cost-modification path: spell cast this way costs {1} more than
    its normal cost. Rust has no cost-hike-on-spell-resolve plumbing
    today.
  - Tapped-land-entry rider: a land played this way ETBs tapped — Rust
    has tapped-ETB plumbing for static "ETB tapped" lands but not the
    contextual "this play instance was via the surcharge route" path.
- **Scope:** **large (6+ cycles).** New persistent permission flag +
  new cost-modification subsystem + contextual-tap-on-entry rider.
  Per-opponent loop over hands (a fresh decision per opponent) is also
  a new decision-contract shape for Rust.
- **Per-deck leverage:** 4,371 decks × large scope = poor cycles
  ratio. Defer until the cast-from-exile substrate is needed by a
  second card (none currently in `genuinely_missing`).

### 4. Pain for All — 4,367 decks

- **Bespoke classes:** `src/mtg_bot/effects/bespoke.py:352-428`
  (`PainForAllETBEffect`) + `src/mtg_bot/effects/bespoke.py:432-463`
  (`PainForAllDamageEchoEffect`).
- **Real parse:** Aura. `Event.ENTERS → PainForAllETBEffect`
  ("enchanted creature deals damage equal to its power to any other
  target") AND `Event.DEALT_DAMAGE (enchanted_creature) →
  PainForAllDamageEchoEffect` ("Whenever enchanted creature is dealt
  damage, it deals that much damage to each opponent").
- **Effect variants needed:**
  - `Effect::EnchantedCreatureDealsPowerToAnyTarget` (ETB)
  - `Effect::OnEnchantedCreatureDealtDamageEchoToEachOpponent` (the
    damage-feedback subsystem)
- **Substrate dependencies:**
  - Same Aura `attached_to` source-substitution as Meltstrider's
    Resolve (#2). Slice 19's honest-stop landing shipped the
    *Effect-level scaffolding* for the Aura-shape Fight variant but
    NOT the broader Aura attach substrate that ALSO blocks Pain for
    All — `attached_to` is still never set on Rust Aura resolve, and
    the loader still admits no Aura. The Aura attach substrate
    (Phases 1-2 per `docs/AURA_ATTACHMENT_SUBSTRATE_PLAN.md`) remains
    the deferred bottleneck for both.
  - Dealt-damage event on the enchanted creature → trigger fires on
    the Aura. Rust's `Event::DEALT_DAMAGE` exists but doesn't
    fan out to riders attached via an Aura's `attached_to`. Needs a
    new "enchanting-permanent-fires-on-enchanted-creature-event" hook.
  - `state.resolving_combat_damage_amount` ledger that survives the
    DEALT_DAMAGE event into the rider's resolve.
- **Scope:** **medium (3-5 cycles)** — UNCHANGED post-slice-19. The
  "substrate-sharing flip from medium → small" depends on the **full
  Aura attach substrate** landing first (not the slice-19 honest-stop
  Effect-level scaffolding alone). Per the substrate plan that
  substrate is 5-7 Rust-agent rounds end-to-end; Pain for All's
  scope estimate stays medium until at least Phase 1 of that
  substrate ships.
- **Per-deck leverage:** 4,367 decks. Closure cost drops sharply
  ONLY if the broader Aura attach substrate lands (NOT slice 19's
  Effect-level scaffolding alone) — the substrate-sharing pattern
  binds at the substrate level, not the Effect level.

### 5. Roving Actuator — 3,400 decks — CLOSED (slice 18)

**Status:** CLOSED in the 18th Rust slice. Effect-level + full-card
byte-equal closure via the short-circuit-the-stack shortcut (Python
also short-circuits per `bespoke.py:683-711`). `Effect::RovingActuator
ETBEffect { max_mv: u8 }` variant + parse + to_pydict + resolve +
bridge all shipped. No deferred substrate. See `docs/residue_worklist.json`
entry `RovingActuator-cast-copy-half`.

### 6. Sothera, the Supervoid — 2,108 decks (LOWEST leverage)

- **Bespoke classes:** three composed primitives:
  - `effects/generic/opponent_punishers.py:149-217`
    (`EachOpponentExilesOwnCreature(link_to_source=True)`)
  - `effects/generic/exile.py:1122-1216`
    (`ReanimateOneExiledWithSourceWithCounters(counter_amount=2)`)
  - `effects/generic/exile.py:1221-1273`
    (`SacrificeSelfPreservingExileLink`)
- **Real parse:** Legendary Enchantment. Two triggered abilities:
  - `Event.DIES (creature you control) →
    EachOpponentExilesOwnCreature(link_to_source=True)`
  - `Event.BEGINNING_OF_END_STEP (intervening-if
    AnyPlayerControlsNoCreatures) →
    Sequence(ReanimateOneExiledWithSourceWithCounters(2),
             SacrificeSelfPreservingExileLink())`
- **Effect variants needed:** all 3 above as fresh Rust variants.
- **Substrate dependencies:**
  - `GameObject.exiled_by_source` source-link field (new persistent
    field on Rust's GameObject).
  - `_release_exiled_until_leaves`-equivalent on-leave auto-return
    hook in Rust (cards tagged with the source-link auto-return when
    the source leaves the battlefield).
  - `state.suppress_exiled_by_source_on_leave_for` one-shot flag that
    the sac arm sets to bypass the auto-return for the recall-first
    ordering.
  - `Sequence` composition ordering: recall first, sac second
    (load-bearing — the worklist explicitly records this).
  - `AnyPlayerControlsNoCreatures` intervening-if predicate (already
    in `_INTERVENING_IF_PHRASES` Python-side; Rust needs the same
    predicate).
- **Scope:** **large (6+ cycles).** 3 new Effect variants + a new
  persistent field on every GameObject + a new on-leave hook + a
  one-shot suppression flag + load-bearing ordering invariant. The
  most expensive closure in the tier by a wide margin.
- **Per-deck leverage:** 2,108 decks (lowest in tier) × largest
  scope = **worst marginal-value-per-cycle** of all 6. Defer.

---

## Substrate-sharing patterns

Post-slice-18/19, the remaining 4 genuinely-missing cards fall into 3
substrate families (Meltstrider's Resolve and Roving Actuator are now
closed at the Effect level; Meltstrider's still requires the Aura
attach substrate for full-game byte-equality and is tracked in the
Aura subsystem tier of `docs/POOL_PARITY.md`):

1. **Aura `attached_to` source-substitution (multi-round Rust
   substrate, NOT shipped):**
   - **Meltstrider's Resolve** — Effect-level scaffolding LANDED in
     slice 19 (honest-stop); full-card byte-equal still needs the
     Aura attach substrate (Phases 1-2). Listed under the Aura
     subsystem tier, NOT this tier.
   - **Pain for All (#3 below)** — still needs both the Aura attach
     substrate AND a new Aura-fires-on-enchanted-creature-DEALT_DAMAGE
     hook. The slice-19 Effect-level scaffolding did NOT pay down
     this substrate; Pain for All's scope stays **medium**.
   - The full Aura attach substrate is the **largest §2-declined Rust
     multi-round substrate** audited so far (5-7 Rust-agent rounds —
     see `docs/AURA_ATTACHMENT_SUBSTRATE_PLAN.md`). It is the shared
     long-pole for both cards.

2. **Land-ETB sacrifice-decision (medium substrate):**
   - **Command Bridge (#1)** — solitary in this tier today, but the
     `untapped_permanent` decision contract it requires is reusable
     by any future "sac unless tap" land (a common shape).

3. **Cast-from-exile-with-rider (large substrate, single consumer
   post-slice-18):**
   - **Lightstall Inquisitor (#2)** — persistent permission +
     cost-hike + tapped-land entry. Post-slice-18 there is no
     in-tier sibling (Roving Actuator closed via the short-circuit-
     the-stack shortcut, NOT a real free-cast pipeline). The
     substrate has no other consumer in the EoE pool today.

4. **Exile-source-link bookkeeping (large substrate, single consumer):**
   - **Sothera, the Supervoid (#4)** — solitary; substrate has no
     other consumer in the EoE pool today. Pure overhead.

---

## Recommended closure sequence

Ranked by **marginal-value-per-cycle (decks ÷ scope)**:

1. **Command Bridge (#1)** — medium scope + 24,522 decks (highest
   deck count in the tier post-slice-19). Genuinely a new
   agent-decision contract in Rust, not a primitive addition. The
   `untapped_permanent` decision substrate it lands is reusable.
   **#1 closure target now that Meltstrider's Resolve and Roving
   Actuator are closed.**

2. **Pain for All (#3)** — medium scope, BUT closure depends on the
   broader Aura attach substrate (NOT slice 19's Effect-level
   scaffolding alone — the substrate-sharing flip only fires once
   Phase 1 of the substrate plan ships). 4,367 decks. Consider
   bundling with a future Aura attach Phase 1+ slice.

3. **Lightstall Inquisitor (#2)** — large scope + 4,371 decks. The
   cast-from-exile permission substrate is heavy and currently has
   only this consumer. Defer until/unless a second card needing it
   surfaces.

4. **Sothera, the Supervoid (#4)** — large scope + 2,108 decks + no
   substrate reuse. **Pure tail.** Carry forward; close only when
   the rest of the tier is empty and the parity number lives or
   dies on this one card.

### Sequencing observations

- **Top-2 closure (Command Bridge + Pain for All)** ships 28,889
  decks of marginal coverage (24,522 + 4,367) — about 82% of the
  tier's deck reach for the medium-scope work.
- **Aura attach substrate is the binding constraint for Pain for
  All AND for the FULL byte-equal closure of Meltstrider's Resolve**
  (whose Effect-level scaffolding shipped in slice 19 but whose
  full-card byte-equality still needs the substrate). Landing
  Phase 1 unlocks both; the substrate is multi-round (5-7 Rust-
  agent rounds end-to-end).
- **Bottom-2 closure (Lightstall + Sothera) is 6,479 decks** for the
  most expensive work — defer indefinitely unless a substrate sibling
  appears.
- The 4-card tier represents **0.8% of the pool by count**; closing
  it shifts the headline `PROBED + covered` headline from 320/475
  (67.4%) toward 324/475 (68.2%) at the Effect+bridge level
  (assuming each closure picks up a probe).

---

## Caveats

- **Effect+bridge ≠ full-game-trajectory parity.** Closing all 4
  Effects does not by itself ship full-game byte-equality for these
  cards — see the headline caveat in `docs/POOL_PARITY.md`.
  Meltstrider's Resolve is the canonical example: slice 19 shipped
  the Effect-level scaffolding (so the worklist marks it `closed`
  with `reclassified_to: BLOCKED-SUBSYSTEM`), but the full-card
  byte-equality requires the broader Aura attach substrate that
  has NOT yet shipped.
- **Scope estimates are calibrated from this session's slices**:
  Astelli Reclaimer (slice 16) closed in 1 cycle (small-medium),
  Roving Actuator (slice 18) closed in 1 cycle via the short-
  circuit-the-stack shortcut, Meltstrider's Resolve (slice 19)
  shipped the Effect-level scaffolding via honest-stop with full
  byte-equality deferred to the Aura attach substrate.
  Lightstall's persistent-flag bucket is large-with-substrate-
  no-other-consumer. Re-estimate after each closure.
- **Deck counts are distinct-deck appearances in the 129,996-deck
  17lands EoE corpus.** Sum across cards double-counts decks that
  contain multiple genuinely-missing cards.
- **The "small (1-2 cycles)" estimate for Meltstrider's Resolve in
  the slice-19-start version of this doc was DEEPER than the
  verify-first re-walk revealed.** The verify-first re-walk in
  `docs/AURA_ATTACHMENT_SUBSTRATE_PLAN.md` §2 confirmed that "Aura
  `attached_to` source-substitution" is NOT a one-off field-deref
  — it requires the full multi-round Aura attach substrate
  (CardDef aura fields + cast-time enchant-target decision + Rust
  Aura-resolution attach + layered grants + CR 704.5n SBA + loader
  predicate). Slice 19's honest-stop discipline (ship the Effect-
  level scaffolding, document the substrate as deferred) handled
  this correctly; future "small scope" estimates against Aura-shape
  effects should re-anchor to the substrate plan before lane
  scoping.
- **The worklist is the source of truth.** If this doc and
  `docs/residue_worklist.json` disagree on a card's status, the
  worklist wins; refresh this doc by re-running through the same
  entries.
