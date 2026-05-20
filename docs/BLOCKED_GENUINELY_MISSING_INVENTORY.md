# BLOCKED-genuinely_missing inventory + closure-scope estimates

Canonical focused inventory of the **6 EoE cards** currently in the
`BLOCKED — genuinely_missing` tier (`docs/POOL_PARITY.md`) — the cards
that need a brand-new Rust `Effect::` variant + parse + bridge before
they can be byte-equal cross-engine. This is the **post-flip long-tail
sequencing guide**: every other parity work is BLOCKED-non-effect (2
cards), BLOCKED-subsystem-gated (149 cards, see
`docs/SUBSYSTEM_ROADMAP.md`), or PROBED/covered (318 cards).

**Snapshot HEAD:** `e2f0539d` (main, 2026-05-19 post-XXX-Pin-2-merge).
**Source of truth:** `docs/residue_worklist.json` (the residue
worklist's per-card re-walk is the AUTHORITY on genuine Effect absence
— round-63 N5 verify-first re-walk at `e6f95002`). The 6 cards below
are the entirety of the load-bearing "how far from parity" residue.

**Total deck reach of this tier:** 53,927 decks (sum of the per-card
counts below; some decks contain multiple genuinely-missing cards, so
this is an upper bound on the union — closing the whole tier moves
fewer than 53,927 distinct decks but no more, see §Sequencing).

---

## At a glance

| Card | bespoke.py (or generic) class | LoC | 17lands decks | Substrate ask | Scope |
|---|---|---:|---:|---|---|
| Command Bridge | `effects/combinators.py::SacrificeSelfUnlessTapPermanent` | 95-168 | 24,522 | land-ETB-trigger plumbing + tap-a-permanent agent decision | medium (3-5) |
| Meltstrider's Resolve | `bespoke.py::EnchantedCreatureFightsTargetEffect` | 507-582 | 15,259 | Aura `attached_to` source-substitution + bare-Fight reuse | small (1-2) |
| Lightstall Inquisitor | `effects/generic/discard.py::EachOpponentExilesCardFromHandWithCastPermission` | 173-214 | 4,371 | persistent `cast_from_exile_with_lightstall_surcharge` flag + cost-hike legality | large (6+) |
| Pain for All | `bespoke.py::PainForAllETBEffect` + `::PainForAllDamageEchoEffect` | 352-463 | 4,367 | Aura `attached_to` damage source + dealt-damage event echo | medium (3-5) |
| Roving Actuator | `bespoke.py::RovingActuatorETBEffect` | 630-718 | 3,400 | exile-then-copy-then-cast-without-paying-cost subsystem | large (6+) |
| Sothera, the Supervoid | `effects/generic/exile.py::ReanimateOneExiledWithSourceWithCounters` + `::SacrificeSelfPreservingExileLink` + `effects/generic/opponent_punishers.py::EachOpponentExilesOwnCreature` | 149-217 / 1122-1216 / 1221-1273 | 2,108 | `GameObject.exiled_by_source` source-link + on-leave auto-return suppression + recall-first/sac-second ordering | large (6+) |

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

### 1. Command Bridge — 24,522 decks (HIGHEST leverage)

- **Bespoke class:** `src/mtg_bot/effects/combinators.py:95-168`
  (`SacrificeSelfUnlessTapPermanent`).
- **Real parse:** Land. `Event.ENTERS → SacrificeSelfUnlessTapPermanent`
  (the new ask) PLUS a separate `{T}: Add {color}` activated mana
  ability (already shipped through the `add_mana_to_pool` arm —
  `name_in_arm_ack` records the ack so the cron does not false-flag).
- **Effect variant needed:** `Effect::SacrificeSelfUnlessTapPermanent`
  (or sibling-named).
- **Substrate dependencies:**
  - Land-ETB-trigger plumbing through the Rust resolver — the existing
    Rust `Event::ENTERS` path is wired for creatures + a small fixed
    set of land-ETB shapes, but the "sacrifice this unless …" decision
    arm needs the engine's `untapped_permanent` choice contract added
    to the Rust decision menu (Python uses `choose_target` with kind
    `"untapped_permanent"`).
  - The agent-choice round-trip (no untapped permanent → forced sac;
    declined → sac; chosen → tap it) needs a Rust decision point that
    the Python side already drives.
- **Scope:** **medium (3-5 cycles).** No new persistent flag, but a
  new agent-decision contract surface in Rust. Sibling slot to the
  `add_mana_to_pool` arm pattern.
- **Per-deck leverage:** 24,522 decks × medium scope ≈ **the highest
  marginal-value closure in the tier** — common-rarity land, plays in
  ~19% of 17lands EoE decks.

### 2. Meltstrider's Resolve — 15,259 decks

- **Bespoke class:** `src/mtg_bot/effects/bespoke.py:507-582`
  (`EnchantedCreatureFightsTargetEffect`).
- **Real parse:** Aura. `Event.ENTERS → EnchantedCreatureFightsTarget
  Effect` ("enchanted creature fights up to one target creature an
  opponent controls"). The bare-bilateral
  `FightTargetCreatureWithTargetCreature` arm IS shipped + bridged
  (`name_in_arm_ack: fight_target_creature_with_target_creature`); the
  Aura-shape source-substitution is the genuine ask.
- **Effect variant needed:** `Effect::EnchantedCreatureFightsTarget`
  (Aura-shape; source fighter = the Aura's `attached_to`, not the
  Aura itself).
- **Substrate dependencies:**
  - Aura `attached_to` → `state.resolving_source` substitution at
    resolve time. Rust already tracks Aura-attached pairs for static
    effects; this just needs to route the "source for damage
    computation" through `attached_to` when present.
  - Reuses the already-shipped bare-Fight damage application
    (`_apply_damage` path — both sides simultaneously, rule 701.12).
- **Scope:** **small (1-2 cycles).** Single new variant; reuses bare
  Fight resolve; the Aura `attached_to` dereference is the only new
  substrate touch. cards.rs already names this card in a deferred
  doc-comment ("Meltstrider's Resolve specifically as the Aura-shape
  follow-up") — the slot is pre-marked.
- **Per-deck leverage:** 15,259 decks × small scope = **best
  decks-per-cycle ratio in the tier** by a wide margin (~7-15k
  decks/cycle). Likely the #1 closure target unless Command Bridge
  is grouped with other land-ETB work.

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
    Resolve (#2). If #2 lands first, #4 reuses the substrate.
  - Dealt-damage event on the enchanted creature → trigger fires on
    the Aura. Rust's `Event::DEALT_DAMAGE` exists but doesn't
    fan out to riders attached via an Aura's `attached_to`. Needs a
    new "enchanting-permanent-fires-on-enchanted-creature-event" hook.
  - `state.resolving_combat_damage_amount` ledger that survives the
    DEALT_DAMAGE event into the rider's resolve.
- **Scope:** **medium (3-5 cycles).** No new persistent flag, but
  needs the new Aura-event-rider plumbing. Substrate-shared with #2
  (Aura `attached_to` source-substitution).
- **Per-deck leverage:** 4,367 decks. Closure cost drops sharply if
  #2 lands first (substrate-sharing).

### 5. Roving Actuator — 3,400 decks

- **Bespoke class:** `src/mtg_bot/effects/bespoke.py:630-718`
  (`RovingActuatorETBEffect`).
- **Real parse:** Void-conditional ETB ("If Void, exile up to one
  target instant or sorcery card with mana value 2 or less from your
  graveyard. Copy it. You may cast the copy without paying its mana
  cost.")
- **Effect variant needed:**
  `Effect::ExileGraveyardCastFromExile` (or
  `VoidExileFromGYCopyAndCastForFree` per the worklist alias). The
  Void condition itself shipped r29 as `ConditionalIfVoid` — only the
  exile-then-cast-copy-for-free half is the genuine ask.
- **Substrate dependencies:**
  - Cast-copy-without-paying-cost subsystem: Rust has no "cast a
    copy from exile, bypass mana cost, fresh targets" path today.
    Implies: a new "free cast" cost-payment mode + a copy GameObject
    (or a synthetic resolve of the spell_effect inline, matching the
    Python short-circuit at `bespoke.py:683-711`).
  - The Python implementation **short-circuits the stack** ("the copy
    doesn't go on the stack and can't be counterspelled — acceptable
    given the engine's lack of responses"). Rust can match this exact
    shortcut for byte-equality without implementing a real free-cast
    pipeline.
- **Scope:** **large (6+ cycles)** if a real free-cast pipeline is
  built; **medium (3-5 cycles)** if the short-circuit-the-stack
  shortcut is matched verbatim. Lane 3
  (`feature/rust-slice-18-roving-actuator`) is currently exploring
  this — update scope from that lane's findings.
- **Per-deck leverage:** 3,400 decks. If the short-circuit
  shortcut holds, marginal-value-per-cycle is competitive with
  Meltstrider's Resolve.

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

The 6 cards fall into 3 substrate families:

1. **Aura `attached_to` source-substitution (small/medium substrate):**
   - Meltstrider's Resolve (#2)
   - Pain for All (#4)
   - Closing #2 first lets #4 reuse the substrate; combined cost ≈ #2
     small + (#4 minus shared substrate) ≈ small + small.

2. **Land-ETB sacrifice-decision (medium substrate):**
   - Command Bridge (#1) — solitary in this tier today, but the
     `untapped_permanent` decision contract it requires is reusable
     by any future "sac unless tap" land (a common shape).

3. **Cast-from-exile-with-rider (large substrate):**
   - Lightstall Inquisitor (#3) — persistent permission + cost-hike
     + tapped-land entry; no current sibling.
   - Roving Actuator (#5) — cast-copy-from-exile for free; partial
     overlap (both need exile→legal-actions-surfaces-cast); diverges
     on the cost rider direction (hike vs free).
   - If the cast-from-exile permission-flag substrate is built once,
     both #3 and #5 can drop their substrate share. Combined cost ≈
     1 large + 2× (large minus shared substrate) ≈ large + medium +
     medium.

4. **Exile-source-link bookkeeping (large substrate, single consumer):**
   - Sothera, the Supervoid (#6) — solitary; substrate has no other
     consumer in the EoE pool today. Pure overhead.

---

## Recommended closure sequence

Ranked by **marginal-value-per-cycle (decks ÷ scope)**:

1. **Meltstrider's Resolve (#2)** — small scope + 15,259 decks +
   pre-marked slot in cards.rs doc-comment. Single highest-leverage
   close in the tier. Lands the Aura `attached_to`
   source-substitution substrate.

2. **Pain for All (#4)** — medium scope, but if #2 landed first the
   Aura substrate is paid; the remaining work (Aura-fires-on-enchanted-
   creature-DEALT_DAMAGE + damage-amount ledger) is closer to small.
   4,367 decks. Take #2 + #4 as a tandem.

3. **Command Bridge (#1)** — medium scope + 24,522 decks (highest
   deck count in the tier). The reason it's #3 not #1 is scope: it's
   genuinely a new agent-decision contract in Rust, not a primitive
   addition. But the per-deck leverage is enormous, and the
   `untapped_permanent` decision substrate it lands is reusable.

4. **Roving Actuator (#5)** — medium-scope IF the short-circuit-the-
   stack shortcut holds (currently being explored on Lane 3,
   `feature/rust-slice-18-roving-actuator`). 3,400 decks. If the
   lane's findings confirm the short-circuit, slot here; if a full
   free-cast pipeline is required, defer to #6's bucket.

5. **Lightstall Inquisitor (#3)** — large scope + 4,371 decks. The
   cast-from-exile permission substrate is heavy and currently has
   only this consumer. Defer until/unless a second card needing it
   surfaces (or it's batched with #5 if both share the new
   cast-from-exile substrate).

6. **Sothera, the Supervoid (#6)** — large scope + 2,108 decks + no
   substrate reuse. **Pure tail.** Carry forward; close only when
   the rest of the tier is empty and the parity number lives or
   dies on this one card.

### Sequencing observations

- **Top-3 closure (Meltstrider + Pain for All + Command Bridge)
  ships 44,148 decks of marginal coverage** (15,259 + 4,367 + 24,522)
  — about 82% of the tier's deck reach for the small-to-medium
  scope work.
- **The Aura substrate is the single highest-leverage substrate
  decision** — landing it (via #2) immediately compounds onto #4
  and unlocks any future Aura-rider card in the long tail.
- **Bottom-2 closure (Lightstall + Sothera) is 6,479 decks** for the
  most expensive work — defer indefinitely unless a substrate sibling
  appears.
- The 6-card tier represents **1.3% of the pool by count** but their
  closure is the load-bearing "true new-Rust-Effect ask" gap. Closing
  the top 3 moves the headline `PROBED + covered` from 318/475
  (66.9%) toward 321/475 (67.6%) at the Effect+bridge level (assuming
  each closure picks up a probe).

---

## Caveats

- **Effect+bridge ≠ full-game-trajectory parity.** Closing all 6
  Effects does not by itself ship full-game byte-equality for these
  cards — see the headline caveat in `docs/POOL_PARITY.md`.
- **Scope estimates are calibrated from this session's slices**:
  Astelli Reclaimer (slice 16) closed in 1 cycle (small-medium), the
  XXX Pin 2 Roving Actuator slice is in flight on Lane 3 (active
  measurement), Lightstall's persistent-flag bucket is large-with-
  substrate-no-other-consumer. Re-estimate after each closure.
- **Deck counts are distinct-deck appearances in the 129,996-deck
  17lands EoE corpus.** Sum across cards double-counts decks that
  contain multiple genuinely-missing cards (the upper bound on the
  union is 53,927; the true union is smaller).
- **Lane 3 may shrink #5's scope** if the short-circuit-the-stack
  shortcut byte-equals the Python implementation. Re-rank #5 once
  Lane 3 lands.
- **The worklist is the source of truth.** If this doc and
  `docs/residue_worklist.json` disagree on a card's status, the
  worklist wins; refresh this doc by re-running through the same
  entries.
