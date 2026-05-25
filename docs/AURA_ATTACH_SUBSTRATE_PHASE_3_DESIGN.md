Generated 2026-05-25 (post `spacecraft-station-substrate-phase-1-design-p1`,
merge `35be45bb`). **Design only — NO production / `_SAFE_*` / Rust
change in this slice; no gate run needed** (docs + read-only scout
against the live tree). This doc scopes the **Aura attach substrate
Phase 3+** as the LAST unscoped major DEFERRED row from
`docs/COVERED_BY_CONSTRUCTION_PROBE_WRITING_SATURATION_2026-05-25.md`'s
recommended-pivot table — 3 cards / 2,783 17lands decks (Chorale of
the Void, Cracked Skull, Sporogenic Infection), all multi-gated S4
triggered-effect Auras whose `attached_to`-reading damage / attack
event Effect halves are unbridged today. Every file:line below is
verified live against main at the worktree fork point.

> **Relationship to `docs/AURA_ATTACHMENT_SUBSTRATE_PLAN.md`.** That
> doc (round-61 → round-83) is the round-by-round substrate plan with
> Phase 1 / 2 / 2.5 / 3 / 4-S3 closures and the per-card multi-cycle
> walks. **This doc supersedes its multi-card residue framing as the
> campaign-level entry point for the LAST 3 cards**: same Phase-3+
> scope as the plan §3.5 "Remaining Phase 4 follow-ups" + §2026-05-21
> verify-first walk findings (sections 992-1069 of the plan), but
> explicitly framed as the warp-campaign-equivalent (Phase 3a / 3b /
> 3c sequencing, per-card cycle counts mirroring CH / MTL / AV
> precedent, and the multi-cycle campaign scope confirmed by the
> 2026-05-21 walk). The per-section file:line specs in the plan §3
> Phase 4 (Chorale's `SacrificeSelfUnlessVoidActive` substrate, the
> S3 token-supertype-override) remain authoritative for already-
> landed pieces; this doc is the campaign-scoping entry point for
> future agents picking up the residue cold.

# Aura attach substrate Phase 3+ — campaign scoping doc (sub-shape S4: 3 cards / 2,783 17lands decks)

## 0. Executive summary

The Aura attachment subsystem at live HEAD `35be45bb` has **Phase 1**
(static-keyword + set-base-PT Auras), **Phase 2 / 2.5** (control-
changing + Lignify-reader-fold), **Phase 3 / S4 Pain for All closure**
(the FIRST triggered-Aura admitted end-to-end), and **Phase 4 S3
Moonlit Meditation closure** (token-supertype-override) all LANDED.
The remaining gap is the **3 multi-gated S4 triggered-effect Aura
carriers** the round-61 scope split out:

| Card | 17lands decks | Long-pole trigger | Tail trigger (Rust+bridge shipped, admit-set-only) |
|---|---:|---|---|
| **Chorale of the Void** | **2,783** | `ATTACKS+IsHost(subject="attacker")+ReanimateTargetCreatureCardFromDefendersGraveyard` | `BEGINNING_OF_END_STEP+ControlledByYou+SacrificeSelfUnlessVoidActive` |
| **Cracked Skull** | 0 (650+ from elsewhere) | `ENTERS+IsSelf+TargetOpponentLookHandMayDiscard` | `DEALT_DAMAGE+IsHost+DestroyEnchantedPermanent` |
| **Sporogenic Infection** | 0 (~500 from elsewhere) | `ENTERS+IsSelf+TargetOpponentSacrificesCreatureOtherThanEnchanted` | `DEALT_DAMAGE+IsHost+DestroyEnchantedPermanent` |

This doc scopes the substrate's **Phase 3+** as the **sub-shape S4
triggered-effect on `attached_to` event** sub-shape: triggered Auras
whose Effect resolve consults `source.attached_to` (either to filter
the trigger event itself via `IsHost`, or — for ATTACKS — to filter
which attacker the source's host is identified with). Phase 3+
explicitly **does not** reopen Phase 1/2/2.5 (static keyword / set-
base-PT / control-changing) and does not subsume Phase 4 S3
replacement riders (already CLOSED for Moonlit Meditation).

Estimated campaign scope (per the round-83 plan §6 calibration
against the warp_cost campaign + the 2026-05-21 verify-first walk's
≥2-cycles-per-card finding): **~5-7 Rust cycles total for Phase 3+**
— 1 admit-set widen + 1 per-card Effect-port cycle for each of the
3 cards (mirroring the per-card cycle counts the CH / MTL / AV
multi-cycle closures + Phase 3 Pain for All / Phase 4 S3 Moonlit
closures executed today). Phase 3+ pilot = **Cracked Skull ETB**
(the smallest of the three new Effect ports per the walk's
"cheapest follow-on candidate" finding).

## 1. Background — why this substrate, why now

### 1.1 What landed in Phases 1 / 2 / 2.5 / 3 / 4

`docs/AURA_ATTACHMENT_SUBSTRATE_PLAN.md` itemizes the
phase-by-phase closures. The live HEAD state confirmed by the
read-only walk in §1.3:

- **Phase 1 (S1 static)** — `_printing_is_bridge_simple_aura` admits
  static-keyword Auras (Frantic Strength / Shardmage's Rescue).
  Phase-2 widen adds `flash` to `_AURA_SAFE_EXTRA_KEYWORDS` per the
  symmetric-drop precedent (`trajectory.py:1412-1414`).
- **Phase 2 (S2 control-changing)** — `attached_grants_control` +
  `attached_grants_lose_abilities` flags + Rust `move_aura_post_resolve`
  attach arm + layer-2 controller flip + layer-6 lose-abilities reader
  fold. Duskmourn's Domination + Tractor Beam admitted at the loader.
- **Phase 2.5 (S2.5 Lignify-shape reader fold)** —
  `attached_sets_base_pt` reader walks attached Auras with the
  highest `etb_timestamp` (no new field; piggybacks the existing
  monotonic counter). Lignify-shape declined at the loader pending
  a separate slice for `attached_grants_subtype` (layer-4 add subtype).
- **Phase 3 (S4 first triggered admit — Pain for All)** —
  `_aura_triggers_are_phase3_safe` Phase-3 safe set lit at
  `trajectory.py:7440-7529` with three shapes:
  1. `ENTERS+IsSelf+TapEnchantedPermanent` (Tractor Beam).
  2. `ENTERS+IsSelf+PainForAllETBEffect` (Pain for All ETB).
  3. `DEALT_DAMAGE+IsHost+PainForAllDamageEchoEffect` (Pain for All
     damage echo).
  Rust `Effect::PainForAllETBEffect` + `Effect::PainForAllDamageEchoEffect`
  + `Predicate::IsHost { subject: Option<String> }` all shipped.
  Pain for All flows end-to-end byte-equal.
- **Phase 4 first deliverable (Chorale `SacrificeSelfUnlessVoidActive`
  substrate)** — Rust `Effect::SacrificeSelfUnlessVoidActive` at
  `cards.rs:4910` + bridge arm + resolve arm + the two engine-wide
  Void flags (`permanent_left_battlefield_this_turn` /
  `spell_warped_this_turn`). Chorale's EoT half is **admit-set-only**
  at the loader gate.
- **Phase 4 S3 (Moonlit Meditation closure)** —
  `GameObject.token_supertype_override: bool` +
  `moonlit_token_substitution` helper + per-player
  `created_tokens_this_turn` slot + loader admit widen. CLOSED
  (`b226fbf4` + `3dc1719d`, 2026-05-21).

### 1.2 The remaining gap — sub-shape S4 multi-gated triggered Auras

Per `docs/SUBSYSTEM_BLOCKED_LEVERAGE_INVENTORY.md` §6 lines
2035-2125 (the 2026-05-21 verify-first walk), the 3 carriers each
have **one shipped tail trigger** (admit-set-only) + **one
uncovered long-pole trigger** that needs a NEW Rust `Effect`
variant. The walk's findings (single source of truth for the
per-card scope):

- **Chorale of the Void** — ATTACKS+IsHost(attacker)+Reanimate is
  the long pole. **NO Rust `Effect::Reanimate…DefendersGraveyard`**
  variant exists; only `Effect::ReanimateOneExiledWithSourceWithCounters`
  (`rust/src/cards.rs:4478`, exile-not-graveyard target). Needs:
  (a) new `target_kind="graveyard_creature"` enumerated across
  opponent graveyards; (b) put-into-bf-tapped-and-attacking
  primitive; (c) `IsHost(subject="attacker")` predicate-subject
  slot expansion in the admit gate (the slot exists Rust-side at
  `cards.rs:9037` but isn't admitted by `_aura_triggers_are_phase3_safe`
  yet). EoT half (`SacrificeSelfUnlessVoidActive`) admit-set-only.
- **Cracked Skull** — ENTERS+IsSelf+`TargetOpponentLookHand
  MayDiscard` is the long pole. **NO Rust `Effect` variant**.
  Python class involves (a) one-way-reveal substrate (`reveal_to`
  per-card from `actions.py`); (b) `may`-gate via
  `Agent.choose_yes_no` (sibling-shape precedent:
  `PendingDecision::TapPermanentChoice` at `cards.rs:4187+`); (c)
  agent-driven directed-discard target choice. DEALT_DAMAGE half
  (`DestroyEnchantedPermanent` + `IsHost`) admit-set-only.
- **Sporogenic Infection** — ENTERS+IsSelf+`TargetOpponent
  SacrificesCreatureOtherThanEnchanted` is the long pole. **NO
  Rust `Effect` variant**. Python class targets `("player", id)`,
  reads the target's battlefield, filter-excludes the host
  (`state.resolving_source.attached_to`), and routes through the
  TARGET opponent's own `Agent.choose_sacrifice` (NOT the
  caster's). DEALT_DAMAGE half shipped as Cracked Skull's;
  admit-set-only.

The trigger event the long-pole Effect fires on is the unifying
sub-shape (S4) — every long pole resolves an Effect that consults
`source.attached_to`, either directly (`DestroyEnchantedPermanent`,
`TargetOpponentSacrificesCreatureOtherThanEnchanted`) or via the
ATTACKS-subject channel (`ReanimateTargetCreatureCardFromDefendersGraveyard`
uses `IsHost(subject="attacker")` to identify which combat attacker
the source's host is).

### 1.3 Verify-first walk (2026-05-25, this slice)

Direct walk against live HEAD `35be45bb` (read-only):

**(a) Live printings via `OracleParserCardSource().get_printings()`:**

```text
Chorale of the Void     is_aura=True  {3}{B}  Enchantment Aura
  TriggeredAbility(ATTACKS, IsHost(subject='attacker'),
                   ReanimateTargetCreatureCardFromDefendersGraveyard())
  TriggeredAbility(BEGINNING_OF_END_STEP, Controlled(YOU, None),
                   SacrificeSelfUnlessVoidActive())
Cracked Skull           is_aura=True  {2}{B}  Enchantment Aura
  TriggeredAbility(ENTERS, IsSelf(None),
                   TargetOpponentLookHandMayDiscard())
  TriggeredAbility(DEALT_DAMAGE, IsHost(None),
                   DestroyEnchantedPermanent())
Sporogenic Infection    is_aura=True  {1}{B}  Enchantment Aura
  TriggeredAbility(ENTERS, IsSelf(None),
                   TargetOpponentSacrificesCreatureOtherThanEnchanted())
  TriggeredAbility(DEALT_DAMAGE, IsHost(None),
                   DestroyEnchantedPermanent())
```

All three are pure Auras: empty `static_abilities`,
`activated_abilities`; `attached_grants_control =
attached_grants_lose_abilities = False`; no `attached_sets_base_pt`,
no `attached_grants_keywords`, no `attached_grants_subtype`. **The
ONLY blocking surface is the triggered_abilities tuple.**

**(b) Phase 1+2 substrate landed live (positive verification):**

`grep "_AURA_SAFE_EXTRA_KEYWORDS\|aura_grants_control\|aura_grants_lose_abilities"
src/` returns:

- `parity/cross_engine.py:425-426` (`CardDef.aura_grants_control` /
  `aura_grants_lose_abilities` dataclass fields).
- `parity/cross_engine.py:13606-13609` (registry-dict emit arms).
- `parity/cross_engine.py:14715-14716`
  (`_card_def_to_python_printing` reconstruction → `attached_grants_*`).
- `parity/cross_engine.py:14950-14997`
  (`read_rust_printing_aura_fields` reverse projection).
- `parity/trajectory.py:1412-1414` (`_AURA_SAFE_EXTRA_KEYWORDS` set).
- `parity/trajectory.py:9806-9807`
  (`_printing_to_card_def` aura arm reading the live
  `attached_grants_*`).

Phase 2 S2 is LIVE; Phase 1 substrate is LIVE.

**(c) Phase 3 admit gate live:**

`_aura_triggers_are_phase3_safe(triggered_abilities)` at
`trajectory.py:7440-7529` admits exactly the 3 Pain-for-All-plus-
Tractor-Beam shapes (§1.1). For each of the 3 Phase-3+ carriers it
returns `False` (the FIRST trigger fails the shape check); the
loader at `_printing_is_bridge_simple_aura:7765-7767` therefore
declines admission. Confirmed live via:

```text
Chorale of the Void            triggers_safe=False  loader_admits=False
Cracked Skull                  triggers_safe=False  loader_admits=False
Sporogenic Infection           triggers_safe=False  loader_admits=False
Pain for All                   triggers_safe=True   loader_admits=True  ← positive control
```

**(d) Effect / predicate dependency inventory (Rust + bridge):**

| Long-pole Effect | Rust variant | Bridge arm | Status |
|---|---|---|---|
| `ReanimateTargetCreatureCardFromDefendersGraveyard` | absent | absent | **Phase 3+ Phase A (Chorale)** |
| `TargetOpponentLookHandMayDiscard` | absent | absent | **Phase 3+ Phase B (Cracked Skull)** |
| `TargetOpponentSacrificesCreatureOtherThanEnchanted` | absent | absent | **Phase 3+ Phase C (Sporogenic)** |
| Tail Effect | Rust variant | Bridge arm | Status |
| `SacrificeSelfUnlessVoidActive` | `cards.rs:4910` | `cross_engine.py:8745` | LANDED (Phase 4 first deliverable) |
| `DestroyEnchantedPermanent` | `cards.rs:4169` | `cross_engine.py:6594` | LANDED |
| Tail predicate / event | Rust | Bridge | Status |
| `IsHost { subject: Option<String> }` | `cards.rs:9037` | `cards.rs:16382-16401` | LANDED (Phase 3 Pain for All) |
| `Predicate::ControlledByYou` | `cards.rs:6130` | LANDED | LANDED |
| `Event::BeginningOfEndStep` | `cards.rs:5843` | dispatch wired | LANDED |
| `Event::DealtDamage` | `cards.rs:5962` | dispatch wired | LANDED |
| `Event::Attacks` | (verify in Phase A; existing combat-trigger dispatch likely covers) | | TBD verify-first |

The two tail Effects + IsHost + the two tail events are all
shipped Rust+bridge. **Phase 3+ closure is gated by the 3 new Effect
ports, not by tail-side substrate.**

### 1.4 Seam where Phase 3+ builds on Phase 2

The Phase-2 substrate (S2 control-changing) is **orthogonal** to
the Phase-3+ trigger-event surface — the 3 carriers don't carry
`attached_grants_control` or `attached_grants_lose_abilities`, and
Phase 2's attach-side machinery (Rust `move_aura_post_resolve`
stamping `attached_to = Some(host_id)`) is the LOAD-BEARING
prerequisite Phase 3+ rides:

- `IsHost::matches` (Rust) reads `source.attached_to` and returns
  `false` when `None`. With Phase 2's stamping in place, the predicate
  returns `true` on the firing turn for the dealt-damage half (per
  Phase 3 Pain for All closure). Phase 3+ inherits this for the new
  Effects' damage half (DEALT_DAMAGE + IsHost shape; admit-set-only).
- `Effect::DestroyEnchantedPermanent::resolve` reads
  `source.attached_to` and destroys it (`state_ops_resolve.rs:14292`).
  Phase 2's attach is what makes this non-no-op.
- The new Phase 3+ Effects' resolve arms ALL read `source.attached_to`
  (Sporogenic excludes the host from sac options;
  `TargetOpponentLookHandMayDiscard` doesn't directly need
  `attached_to` but its ETB shape is gated by `IsSelf` on the Aura
  source — the source side IS the resolved Aura).

**The seam = `state.resolving_source.attached_to` (Python) and
the `source.attached_to` accessor (Rust)**, both of which Phase 2's
attach arm populates. Phase 3+ adds NO new attach-side machinery;
it ports the consuming Effect resolves cross-engine.

## 2. Sub-shape S4 scope — triggered-effect Aura where the trigger resolves an Effect that reads `attached_to`

Verified live against `OracleParserCardSource` at main `35be45bb`
(§1.3 walk):

| Card | live parsed long-pole trigger | tail trigger (admit-set-only) | 17lands decks |
|---|---|---|---:|
| **Chorale of the Void** | `ATTACKS + IsHost(subject="attacker") + ReanimateTargetCreatureCardFromDefendersGraveyard()` | `BEGINNING_OF_END_STEP + Controlled(YOU, None) + SacrificeSelfUnlessVoidActive()` | 2,783 |
| **Cracked Skull** | `ENTERS + IsSelf(None) + TargetOpponentLookHandMayDiscard()` | `DEALT_DAMAGE + IsHost(None) + DestroyEnchantedPermanent()` | 0 (positive-control) |
| **Sporogenic Infection** | `ENTERS + IsSelf(None) + TargetOpponentSacrificesCreatureOtherThanEnchanted()` | `DEALT_DAMAGE + IsHost(None) + DestroyEnchantedPermanent()` | 0 (positive-control) |

**Phase 3+ deck total: 2,783 17lands decks** (Chorale carries the
entire deck-count signal — Cracked Skull and Sporogenic are 0-deck
in the EoE 17lands pool but ARE in the EoE card pool, so they're
positive-control admits the bench loader must round-trip).

All three carriers' sub-shape S4 commonality:

- The trigger event fires on a per-permanent event keyed by
  `attached_to`: `Event.ENTERS` (the Aura's own ETB after attach —
  Phase 2 already stamps `attached_to`); `Event.DEALT_DAMAGE` with
  `IsHost` (the host receiving damage); `Event.ATTACKS` with
  `IsHost(subject="attacker")` (the host attacking).
- The Effect resolve reads `source.attached_to` (directly:
  `DestroyEnchantedPermanent`, `TargetOpponentSacrificesCreatureOtherThanEnchanted`;
  indirectly: `TargetOpponentLookHandMayDiscard` via the source-is-
  Aura context; `ReanimateTargetCreatureCardFromDefendersGraveyard`
  via the ATTACKS-subject channel).
- `once_per_turn=False` on every shape (Aura triggers fire each
  occurrence — Phase 3 Pain for All gate-shape precedent).

The Phase-3+ admit-set widen adds three new event-predicate-effect
shapes (one per card's long pole), PLUS — for the leverage realization
to land — two admit-set widens for tail-side shapes already shipped
Rust+bridge:

| Phase | New admit shape | What flips |
|---|---|---|
| **Phase 3+ A** (Chorale) | `ATTACKS + IsHost(subject="attacker") + ReanimateTargetCreatureCardFromDefendersGraveyard` | Long pole. Also widens the IsHost subject-slot admit set to accept `"attacker"`. |
| **Phase 3+ B** (Cracked Skull) | `ENTERS + IsSelf + TargetOpponentLookHandMayDiscard` | Long pole. |
| **Phase 3+ C** (Sporogenic) | `ENTERS + IsSelf + TargetOpponentSacrificesCreatureOtherThanEnchanted` | Long pole. |
| **Tail-X1** (all 3) | `DEALT_DAMAGE + IsHost(subject=None) + DestroyEnchantedPermanent` | Cracked Skull + Sporogenic admit-set-only. |
| **Tail-X2** (Chorale) | `BEGINNING_OF_END_STEP + Controlled(YOU, None) + SacrificeSelfUnlessVoidActive` | Chorale admit-set-only. |

Tail-X1 + Tail-X2 ride on top of whichever Phase A/B/C cycle their
host card closes — the all-or-nothing
`_aura_triggers_are_phase3_safe` gate refuses to admit a card whose
OTHER trigger isn't in the safe set, so the tails CANNOT flip cards
alone (per the walk's "Common admit-set widen these 3 cards share"
finding).

## 3. Out-of-scope (deferred to Phase 4+ / S5+)

The following are explicitly **NOT** in Phase 3+'s scope. The
guardrail (the `_aura_triggers_are_phase3_safe` positive-allowlist
gate) positively rejects each so they cannot reach the Phase-3+
admit path:

### 3.1 Phase 4 / S5+ — non-Pain-for-All non-S4-this-doc bespoke triggers

The four declined Aura families NOT in this doc's set:

- **Meltstrider's Resolve** —
  `ENTERS+IsSelf+EnchantedCreatureFightsTargetEffect`
  (the slice-19 honest-stop). Already substrated Rust-side as
  `Effect::EnchantedCreatureFightsTarget` (LANDED slice-19);
  pending a separate slice for the bench-driven probe.
- **Tractor Beam** — admitted today at the loader (Phase-2-S2-
  extension joint-shape gate via the `attached_grants_control AND
  attached_prevents_untap` admit at `trajectory.py:7808-7820`); not
  declined-by-Phase-3 — this card lives on the Phase 2 side.
- **Moonlit Meditation** — CLOSED 2026-05-21 (Phase 4 S3,
  `b226fbf4` + `3dc1719d`).
- **Pain for All** — CLOSED 2026-05-20 (Phase 3, `35ede8b0`).

### 3.2 Multi-source Aura interactions (S5+, future)

Aura attach against an Aura — e.g. Auras that enchant other Auras
— is not in the EoE pool today and is explicitly Phase 5+ if/when
admitted. Phase 3+ inherits Phase 2's single-attached-host
assumption.

### 3.3 Aura re-attach (CR 613.7d)

Aura re-attach (when an Aura's host leaves and the Aura re-attaches
mid-game) is documented in the substrate plan as a Phase 3+ follow-
up (`AURA_ATTACHMENT_SUBSTRATE_PLAN.md:714-716`). No live carrier
in the 3-card set triggers re-attach (Auras to graveyard on host-
loss is Phase 1 SBA today). Out of Phase 3+ scope.

### 3.4 Effect-uncovered closure on OTHER (non-Aura) carriers

The 45 / 76,035 "Effect-uncovered" residue per the saturation
report's BLOCKED-SG breakout table is a **diffuse**
substrate-widen lane — no single Effect widen unlocks multiple
cards. The 3 Effect ports Phase 3+ lands DO contribute to that
residue (each port is an Effect closure), but the Phase 3+
campaign attacks the Aura-attachment row specifically; the wider
Effect-uncovered residue is a separate roadmap row.

## 4. Rust-side spec — the new Effect variants + admit-set wiring

### 4.1 Three new `Effect` variants

**File:** `rust/src/cards.rs`. Append to the `Effect` enum
(declared near `cards.rs:4100+`), alongside the existing Aura-
relational variants (`DestroyEnchantedPermanent` at `:4169`,
`PainForAllETBEffect` at `:8069`,
`SacrificeSelfUnlessVoidActive` at `:4910`):

```rust
/// **Aura Phase 3+ Phase A — Chorale of the Void.**
/// "Whenever enchanted creature attacks, put target creature card
/// from defending player's graveyard onto the battlefield under
/// your control tapped and attacking."
///
/// Mirrors Python's
/// `ReanimateTargetCreatureCardFromDefendersGraveyard`
/// (`src/mtg_bot/effects/generic/graveyard.py:474-554`).
///
/// **Resolve semantics.** Reads the chosen target (the new
/// `target_kind="graveyard_creature"` — §4.2) → locate the card in
/// SOME opponent's graveyard → remove → put-into-bf-tapped-and-
/// attacking under the resolving controller. The bench's combat-
/// damage loop reads `obj.attacking` and uses the in-progress
/// combat phase's defender id (single-defender semantics — 2-player
/// mode matches the printed "defending player" exactly).
///
/// **Targeting substrate.** The new `target_kind` enumerated by
/// `legal_targets` is the union of every opponent's graveyard
/// creature cards. New `PendingDecision::GraveyardCardChoice`
/// (mirrors `PendingDecision::TapPermanentChoice` shape) — agent
/// answers with the chosen card id.
///
/// **Honest-stop today.** If `source.attached_to == None` (Aura
/// without host — Phase 2 honest-stop), the parent trigger doesn't
/// fire because `IsHost(subject="attacker")` returns false; no
/// resolve. If the chosen card has already left the graveyard
/// between target-pick and resolve, silently no-op (Python parity:
/// `if card is None: continue`).
ReanimateTargetCreatureCardFromDefendersGraveyard,

/// **Aura Phase 3+ Phase B — Cracked Skull.**
/// "Look at target opponent's hand. You may choose a nonland card
/// from it. That player discards that card."
///
/// Mirrors Python's `TargetOpponentLookHandMayDiscard`
/// (`src/mtg_bot/effects/generic/discard.py:298-391`).
///
/// **Resolve semantics.** Target = `("player", id)` — an opponent.
/// Step 1 (look): every card in target's hand becomes `publicly_known_to`
/// the caster (one-way reveal — new `reveal_to` primitive on
/// `GameObject` / hand-card representation). Step 2 (may): caster's
/// agent answers `choose_yes_no` ("force discard?"). Step 3 (if
/// yes, options non-empty): caster's agent answers
/// `choose_card_from_opponent_hand` to pick the nonland card →
/// target discards.
///
/// **Decision substrate.** New `PendingDecision::MayDiscardChoice`
/// (the `may`-gate) + new `PendingDecision::OpponentHandCardChoice`
/// (the directed-discard pick). Sibling-shape precedent:
/// `PendingDecision::TapPermanentChoice` at `cards.rs:4187+`
/// (Command Bridge slice).
///
/// **One-way reveal substrate.** New `GameObject.publicly_known_to:
/// HashSet<PlayerId>` field on hand cards (or per-card `revealed_to`
/// bitfield — implementation choice during Phase B). Mirrors
/// Python's `reveal_to(c, controller_id)` at
/// `src/mtg_bot/actions.py` (one-way visibility table).
TargetOpponentLookHandMayDiscard,

/// **Aura Phase 3+ Phase C — Sporogenic Infection.**
/// "Target opponent sacrifices a creature of their choice other
/// than enchanted creature."
///
/// Mirrors Python's
/// `TargetOpponentSacrificesCreatureOtherThanEnchanted`
/// (`src/mtg_bot/effects/generic/opponent_punishers.py:68-144`).
///
/// **Resolve semantics.** Target = `("player", id)` — an opponent.
/// Compute `excluded_id = source.attached_to` (the Aura's host).
/// Enumerate target's bf creatures filter-excluding excluded_id.
/// Route through the TARGET opponent's `Agent.choose_sacrifice`
/// (NOT the caster's — distinguishing feature vs.
/// `EachOpponentSacrificesCreature` which routes per-opponent on
/// each opponent's agent). Sacrifice the chosen object.
///
/// **Decision substrate.** Reuses
/// `PendingDecision::SacrificeChoice` (already shipped for
/// `EachOpponentSacrificesCreature` and per-opponent forced
/// sacrifices). NEW: the `excluded_object_id: Option<u32>` slot on
/// the pending decision (excluded from the choice set) — the host's
/// id, threaded from `source.attached_to`.
///
/// **Filter difference vs. `EachOpponentSacrificesCreature`.** The
/// nontoken filter is NOT applied here (printed text: "a creature
/// of their choice", not "a nontoken creature").
TargetOpponentSacrificesCreatureOtherThanEnchanted,
```

### 4.2 New `target_kind="graveyard_creature"` (Chorale prerequisite)

**File:** `rust/src/cards.rs` (`Target` / `TargetKind` enum at
`cards.rs:~3800+`). Mirror Python's
`("graveyard_creature", id)` shape:

```rust
/// **Aura Phase 3+ Phase A.** Target = a creature card in SOME
/// opponent's graveyard (the resolving controller's opponent in
/// 2-player; multi-opponent extends naturally). Used by
/// `ReanimateTargetCreatureCardFromDefendersGraveyard`. Mirrors
/// Python's `("graveyard_creature", id)` tuple at
/// `effects/generic/graveyard.py:514`.
GraveyardCreature(u32),
```

`legal_targets` for the Effect:

```rust
Effect::ReanimateTargetCreatureCardFromDefendersGraveyard => {
    let mut out = Vec::new();
    for p in state.players.iter() {
        if p.id == controller_id { continue; }
        for c in p.graveyard.iter() {
            // is_creature reader walks the card's printing
            if c.printing(&state.registry).is_creature() {
                out.push(Target::GraveyardCreature(c.id));
            }
        }
    }
    out
}
```

### 4.3 Resolve arms (`rust/src/state_ops_resolve.rs`)

**Phase A — Reanimate-from-defenders-graveyard:**

```rust
Effect::ReanimateTargetCreatureCardFromDefendersGraveyard => {
    let Some(Target::GraveyardCreature(target_id)) = targets.first().copied() else {
        return; // honest-stop: no target chosen
    };
    // Locate the card in some opponent's graveyard.
    let mut card_opt = None;
    for p in state.players.iter_mut() {
        if let Some(idx) = p.graveyard.iter().position(|c| c.id == target_id) {
            card_opt = Some((p.id, p.graveyard.remove(idx)));
            break;
        }
    }
    let Some((from_pid, mut card)) = card_opt else { return; }; // honest-stop: card gone
    state.log.push(format!(
        "{} returns from P{}'s graveyard under P{} tapped and attacking",
        card.printing(&state.registry).name(), from_pid, controller_id,
    ));
    put_into_battlefield(state, &mut card, controller_id);
    card.tapped = true;
    card.attacking = true;
    card.summoning_sick = false;
    // Insert into battlefield (engine-specific mechanics here).
}
```

**Phase B — Look at hand + may-discard:**

```rust
Effect::TargetOpponentLookHandMayDiscard => {
    let Some(Target::Player(target_pid)) = targets.first().copied() else { return; };
    let target = state.player_by_id_mut(target_pid);
    if target.has_lost { return; }
    // Step 1: one-way reveal (every card in target's hand → publicly_known_to controller_id).
    for c in target.hand.iter_mut() {
        c.publicly_known_to.insert(controller_id);
    }
    let options: Vec<u32> = target.hand.iter()
        .filter(|c| !c.printing(&state.registry).is_land())
        .map(|c| c.id).collect();
    if options.is_empty() {
        state.log.push(format!(
            "P{} has no nonland cards — directed discard declines silently",
            target_pid,
        ));
        return;
    }
    // Step 2: the may-gate.
    let confirm = enqueue_pending_decision(
        state, controller_id,
        PendingDecision::MayDiscardChoice {
            prompt: format!("Force P{} to discard a nonland card?", target_pid),
        },
    );
    if !confirm { return; } // honest-stop on "no"
    // Step 3: directed-discard target choice.
    let chosen_id = enqueue_pending_decision(
        state, controller_id,
        PendingDecision::OpponentHandCardChoice { from: target_pid, options },
    );
    discard_specific_card(state, target_pid, chosen_id);
    state.log.push(format!(
        "P{} chooses P{}'s card for the may-discard", controller_id, target_pid,
    ));
}
```

**Phase C — Target opponent sacrifices a creature other than host:**

```rust
Effect::TargetOpponentSacrificesCreatureOtherThanEnchanted => {
    let Some(Target::Player(target_pid)) = targets.first().copied() else { return; };
    let target = state.player_by_id(target_pid);
    if target.has_lost { return; }
    // Excluded id: the Aura's host.
    let source = state.resolving_source(); // current Effect's source object
    let excluded_id = source.attached_to;
    let legal: Vec<u32> = state.battlefield.iter()
        .filter(|o|
            o.controller_id == target_pid
            && o.printing(&state.registry).is_creature()
            && Some(o.id) != excluded_id
        )
        .map(|o| o.id).collect();
    if legal.is_empty() { return; }
    // Routes through the TARGET opponent's agent, not the caster's.
    let chosen_id = enqueue_pending_decision_for(
        state, target_pid,
        PendingDecision::SacrificeChoice { options: legal, excluded_object_id: excluded_id },
    );
    sacrifice_inline(state, chosen_id);
    state.log.push(format!(
        "P{} sacrifices {} (Sporogenic Infection)", target_pid, chosen_id,
    ));
}
```

### 4.4 Three new parse + to_pydict arms

Each Effect variant gets its own `parse_effect` and `effect_to_pydict`
arm in `rust/src/cards.rs::parse_effect` (~`:11900+` for the existing
Aura-relational arms — `pain_for_all_etb` at `:8069`,
`destroy_enchanted_permanent` at `:12307`). Wire tokens
(stable bridge-side strings, NOT Python class names):

| Effect variant | Rust wire token | Bridge arm consumer |
|---|---|---|
| `ReanimateTargetCreatureCardFromDefendersGraveyard` | `"reanimate_target_creature_card_from_defenders_graveyard"` | `cross_engine.py::_ta_dict_to_python_effect` |
| `TargetOpponentLookHandMayDiscard` | `"target_opponent_look_hand_may_discard"` | `cross_engine.py::_ta_dict_to_python_effect` |
| `TargetOpponentSacrificesCreatureOtherThanEnchanted` | `"target_opponent_sacrifices_creature_other_than_enchanted"` | `cross_engine.py::_ta_dict_to_python_effect` |

All three are unit variants with no fields → simple `{"kind": "<token>"}`
emit (matches the `pain_for_all_etb` / `sacrifice_self_unless_void_active`
emit pattern).

### 4.5 New `Event::Attacks` trigger dispatch (verify-first in Phase A)

The combat-trigger dispatch site for ATTACKS already routes the
attacker's id as `subject_id` (sibling-shape: equipment "whenever
equipped creature attacks" — though no live Equipment Effect uses
this yet). **Verify-first step in Phase A cycle:** confirm
`cards.rs:5843`-area combat trigger dispatch fires Aura ATTACKS
triggers with `subject_id = attacker.id` and that
`IsHost::matches(source, attacker.id)` resolves correctly (returns
`true` iff `source.attached_to == attacker.id`). If the dispatch
omits Aura triggers from ATTACKS today, Phase A adds an Aura-side
ATTACKS scan to the combat-trigger fan-out (mirrors how DEALT_DAMAGE
fan-out already includes Aura-on-host sources for the Pain for All
closure).

### 4.6 New decision-pump pending variants

Three new `PendingDecision` variants (`rust/src/state_decision.rs` or
the equivalent decision-pump module):

```rust
/// **Aura Phase 3+ Phase A.**
GraveyardCardChoice {
    options: Vec<u32>,  // candidate graveyard-creature ids
},

/// **Aura Phase 3+ Phase B.**
MayDiscardChoice {
    prompt: String,
},

/// **Aura Phase 3+ Phase B.**
OpponentHandCardChoice {
    from: u8,           // owning player id (reveal source)
    options: Vec<u32>,  // candidate hand-card ids
},
```

The existing `PendingDecision::SacrificeChoice` is extended with the
`excluded_object_id: Option<u32>` slot for Phase C.

## 5. Python bridge spec — round-trip the three new shapes byte-equal

### 5.1 `_ta_dict_to_python_effect` reverse arms

**File:** `src/mtg_bot/parity/cross_engine.py`. The existing arms for
`pain_for_all_etb` / `destroy_enchanted_permanent` (at
`cross_engine.py:8351` / `:6594`) are the precedent shape — unit
Effect constructors. Append the three new arms:

```python
elif kind == "reanimate_target_creature_card_from_defenders_graveyard":
    from mtg_bot.effects.generic.graveyard import (
        ReanimateTargetCreatureCardFromDefendersGraveyard,
    )
    return ReanimateTargetCreatureCardFromDefendersGraveyard()

elif kind == "target_opponent_look_hand_may_discard":
    from mtg_bot.effects.generic.discard import (
        TargetOpponentLookHandMayDiscard,
    )
    return TargetOpponentLookHandMayDiscard()

elif kind == "target_opponent_sacrifices_creature_other_than_enchanted":
    from mtg_bot.effects.generic.opponent_punishers import (
        TargetOpponentSacrificesCreatureOtherThanEnchanted,
    )
    return TargetOpponentSacrificesCreatureOtherThanEnchanted()
```

### 5.2 `_python_ta_to_safe_dict_aura_phase3` widen — emit arms

**File:** `src/mtg_bot/parity/trajectory.py`, lines 7532-7626 — the
single canonical emitter for Phase-3-admit-clean TriggeredAbility
shapes. Phase 3+ widens it with FIVE new branches (3 long-pole + 2
tails sharing the chokepoint):

```python
if isinstance(ta.effect, ReanimateTargetCreatureCardFromDefendersGraveyard):
    # Phase 3+ Phase A shape: ATTACKS + IsHost(subject="attacker") +
    # Reanimate-from-defenders-graveyard.
    return {
        "event": "attacks",
        "predicate": {"kind": "is_host", "subject": "attacker"},
        "effect": {
            "kind": "reanimate_target_creature_card_from_defenders_graveyard",
        },
        "once_per_turn": False,
    }
if isinstance(ta.effect, TargetOpponentLookHandMayDiscard):
    # Phase 3+ Phase B shape: ENTERS + IsSelf + look-hand-may-discard.
    return {
        "event": "enters",
        "predicate": {"kind": "source_is_self"},
        "effect": {"kind": "target_opponent_look_hand_may_discard"},
        "once_per_turn": False,
    }
if isinstance(ta.effect, TargetOpponentSacrificesCreatureOtherThanEnchanted):
    # Phase 3+ Phase C shape: ENTERS + IsSelf + opponent-sacs-creature-
    # other-than-host.
    return {
        "event": "enters",
        "predicate": {"kind": "source_is_self"},
        "effect": {
            "kind": "target_opponent_sacrifices_creature_other_than_enchanted",
        },
        "once_per_turn": False,
    }
# Phase 3+ Tail-X1: DEALT_DAMAGE + IsHost + DestroyEnchantedPermanent
# (Cracked Skull + Sporogenic).
if isinstance(ta.effect, DestroyEnchantedPermanent):
    return {
        "event": "dealt_damage",
        "predicate": {"kind": "is_host"},
        "effect": {"kind": "destroy_enchanted_permanent"},
        "once_per_turn": False,
    }
# Phase 3+ Tail-X2: BEGINNING_OF_END_STEP + Controlled(YOU) +
# SacrificeSelfUnlessVoidActive (Chorale EoT half).
if isinstance(ta.effect, SacrificeSelfUnlessVoidActive):
    return {
        "event": "beginning_of_end_step",
        "predicate": {"kind": "controlled_by_you"},
        "effect": {"kind": "sacrifice_self_unless_void_active"},
        "once_per_turn": False,
    }
```

### 5.3 `_aura_triggers_are_phase3_safe` admit-set widen

**File:** `src/mtg_bot/parity/trajectory.py`, lines 7440-7529.
**The gate widens MUST land in the SAME slice as each long-pole
Effect port** — the all-or-nothing gate refuses partial admission.
Phase 3+ cycle plan (§7) sequences Tail-X1 and Tail-X2 with the
LAST card's Phase cycle so they don't widen the gate while a card
still has an uncovered Effect.

Five new admit shapes (mirrors §5.2's emitter list):

```python
# Phase 3+ admit shape 4: Chorale of the Void ATTACKS half.
if (
    ta.event is Event.ATTACKS
    and isinstance(ta.predicate, IsHost)
    and ta.predicate.subject == "attacker"   # NEW subject-slot value
    and isinstance(ta.effect, ReanimateTargetCreatureCardFromDefendersGraveyard)
):
    continue
# Phase 3+ admit shape 5: Cracked Skull ETB half.
if (
    ta.event is Event.ENTERS
    and isinstance(ta.predicate, IsSelf)
    and ta.predicate.subject is None
    and isinstance(ta.effect, TargetOpponentLookHandMayDiscard)
):
    continue
# Phase 3+ admit shape 6: Sporogenic Infection ETB half.
if (
    ta.event is Event.ENTERS
    and isinstance(ta.predicate, IsSelf)
    and ta.predicate.subject is None
    and isinstance(ta.effect, TargetOpponentSacrificesCreatureOtherThanEnchanted)
):
    continue
# Phase 3+ Tail-X1: shared DEALT_DAMAGE + IsHost + Destroy tail.
if (
    ta.event is Event.DEALT_DAMAGE
    and isinstance(ta.predicate, IsHost)
    and ta.predicate.subject is None
    and isinstance(ta.effect, DestroyEnchantedPermanent)
):
    continue
# Phase 3+ Tail-X2: Chorale EoT void-sustain tail.
if (
    ta.event is Event.BEGINNING_OF_END_STEP
    and isinstance(ta.predicate, Controlled)
    and ta.predicate.by is _Controller.YOU
    and ta.predicate.subject is None
    and isinstance(ta.effect, SacrificeSelfUnlessVoidActive)
):
    continue
```

### 5.4 `_printing_is_bridge_simple_aura` — no edit (the chokepoint already calls phase3-safe)

The loader admit predicate at `trajectory.py:7629-7924` already
gates triggered Auras through `_aura_triggers_are_phase3_safe`
(lines 7765-7767). **Phase 3+ DOES NOT touch the loader admit
predicate** — it widens the safe-set helper and adds emitter arms,
and the loader naturally admits whatever the helper passes.

This is the canonical chokepoint discipline from the Phase 3
substrate plan (§3.3): the Phase-3 gate is "the single canonical
chokepoint going forward" (`AURA_ATTACHMENT_SUBSTRATE_PLAN.md:758-760`).

### 5.5 `compare_fields` parity coverage for the new fields

Phase 3+ adds NO new CardDef fields — the long-pole Effects are
unit variants (no parameters), they fit the existing
`triggered_abilities` tuple-of-dicts CardDef field, and the new
`PendingDecision` variants are decision-pump state (not CardDef
state). The `compare_fields` parity walk inherits without
modification from Phase 3 (Pain for All) and Phase 4 first-
deliverable (Chorale `SacrificeSelfUnlessVoidActive`).

## 6. Filter guardrail — admit only the Phase-3+ S4 shapes

Phase 3+ does NOT introduce a new admit predicate (§5.4). The
`_aura_triggers_are_phase3_safe` gate is the §2 positive-allowlist
predicate. Phase 3+'s teeth:

- Five new admit branches (§5.3) — each is a tight (event,
  predicate-class, predicate-subject, effect-class) tuple match. No
  field beyond those four is permitted to be load-bearing.
- The `_python_ta_to_safe_dict_aura_phase3` emitter (§5.2) raises
  `ValueError` for any effect NOT in the safe set — matches the
  §2 round-83 honest-stop discipline.
- The Rust parse arm hard-errors on unknown wire tokens (per the
  cost-reduction Phase 1 / warp Phase 2 precedent).

The all-or-nothing gate's discipline (the §2 "no fallback hybrid"
rule per `feedback_no_fallback_hybrids.md`): adding the safe shape
for a tail half without the matching long-pole port WOULD admit
nothing (every Phase-3+ carrier has BOTH halves, so its
all-or-nothing gate stays closed). This is exactly the desired
behavior — the gate's correctness across the campaign hinges on
landing the Tail-X1/X2 widens at the SAME slice as the last card's
long-pole.

## 7. Test plan

### 7.1 Substrate unit pins (Rust `#[test]` module per Effect)

For each new Effect variant (§4.1), one Rust test module:

1. **Phase A: `tests/rust/test_reanimate_from_defenders_graveyard.rs`** —
   parse + to_pydict round-trip; resolve with a populated opponent
   graveyard → card removed from gy, placed on bf under resolving
   controller, tapped+attacking, summoning_sick=false; resolve with
   empty graveyard → silent no-op; resolve with target card already
   moved → silent no-op; resolve under `source.attached_to=None`
   (parent trigger gated by IsHost-attacker — no resolve fires —
   defensive pin).
2. **Phase B: `tests/rust/test_target_opponent_look_hand_may_discard.rs`** —
   parse + to_pydict round-trip; resolve with target's hand nonempty
   → all hand cards stamped `publicly_known_to=caster`; resolve →
   may-gate `no` → silent no-op log; resolve → may-gate `yes` →
   directed-discard pick → chosen card to graveyard; resolve with
   target's hand all-lands → silent no-op log (no may-gate dispatched).
3. **Phase C: `tests/rust/test_target_opponent_sacrifices_other_than_host.rs`** —
   parse + to_pydict round-trip; resolve with `attached_to=host_id`
   and target controls host + 2 other creatures → only the 2 others
   are choice options; resolve with target controls ONLY host →
   silent no-op; resolve with `attached_to=None` → no exclusion
   (defensive pin — gated by parent trigger).
4. **Decision-pump pins** (one per new `PendingDecision` variant) —
   the agent path-pins mirroring `PendingDecision::TapPermanentChoice`
   precedent.
5. **`IsHost(subject="attacker")` admit pin** — predicate-subject-
   slot widen test: a synthetic CardDef carrying the
   `ATTACKS+IsHost(subject="attacker")+Reanimate…` trigger flows
   through `parse_predicate` → `Predicate::IsHost{subject: Some("attacker".into())}`
   → emit → consume in `compare_fields` byte-equal.

### 7.2 Cross-engine bridge round-trip pins

6. `_ta_dict_to_python_effect({"kind": "reanimate_target_creature_card_from_defenders_graveyard"})`
   returns `ReanimateTargetCreatureCardFromDefendersGraveyard()` (and
   the inverse round-trip in `_python_ta_to_safe_dict_aura_phase3` is
   byte-equal).
7. Same for `TargetOpponentLookHandMayDiscard` /
   `TargetOpponentSacrificesCreatureOtherThanEnchanted`.
8. **Action-set invariance pin** (the all-or-nothing gate teeth):
   `_aura_triggers_are_phase3_safe` is `True` for each of the 3
   carriers' FULL `triggered_abilities` tuple iff BOTH halves are
   in the safe set; partial safe-set widens (long pole without tail,
   or tail without long pole) keep the gate `False`.

### 7.3 Real-EoE per-card probes

A `tests/test_parity_smoke.py` probe per carrier (insert IMMEDIATELY
ABOVE the `# === PHASE5_PROBES_INSERT_ABOVE_THIS_LINE ===` sentinel),
each driving the **actual live printing** (resolved via
`OracleParserCardSource`, NOT a synthetic CardDef — round-46
real-EoE-signal discipline). Each probe asserts byte-equal mirror
on both engines through:

- **Chorale of the Void probe** (`test_chorale_of_the_void_parity.py`):
  (a) cast Aura → attach to opponent's creature → opponent attacks
  with that creature → trigger fires → graveyard-target choice
  → reanimated card lands tapped+attacking; (b) end-step with Void
  active → no sacrifice; end-step with Void inactive → Aura
  sacrificed. The bench's `attack_all` strategy may not naturally
  fire the ATTACKS trigger from the opponent's host's attack — the
  probe MUST use a scripted picker (`tests/parity/_picker_shims.py`)
  that drives the host's attack so the reanimate path is exercised.
- **Cracked Skull probe** (`test_cracked_skull_parity.py`): (a) cast
  Aura → ETB resolves → caster sees hand → may-gate `yes` → discard;
  (b) cast Aura with target's hand all-lands → silent decline; (c)
  attached host receives damage → Aura destroys host.
- **Sporogenic Infection probe** (`test_sporogenic_infection_parity.py`):
  (a) cast Aura → opponent's bf has 2 creatures besides host → ETB
  forces target to pick one of the non-host creatures to sac; (b)
  opponent's bf has ONLY host → silent no-op; (c) attached host
  receives damage → Aura destroys host.

**Bench-strategy reduction-trigger coverage note:** the bench's
default strategy may not naturally drive every probe-required line
(especially Chorale's "opponent attacks with our enchanted host"
shape, which requires Phase 2 control-grant inversion that Chorale
itself doesn't carry — the host is opponent-controlled if we
targeted an opponent's creature; Phase 2 doesn't apply because
Chorale doesn't grant control). Each probe's picker scripts the
specific line; the SL entries (§9) note "real-EoE bench-strategy
coverage is probe-driven, not organic" — matches the warp_cost
Phase 3 finding that "measurement-attribution fixes" were the real
unblock.

### 7.4 Decline-set bench check + no-silent-auto-grow pin

A negative-set bench check at the loader filter:

9. `_printing_is_bridge_simple_aura(<live Chorale>) == False`
   pre-Phase-A. Post-Phase-A: `== True`.
10. Same per-card for Cracked Skull / Sporogenic Infection (the
    Phase-B / Phase-C gates).
11. **No-silent-auto-grow pin** (the §2 "silent no-op pipeline runs
    are pipeline bugs" discipline per
    `feedback_silent_noop_pipelines.md`): a test asserts the EXACT
    set of EoE Aura printings admitted by
    `_printing_is_bridge_simple_aura` post-Phase-3+ closure is
    `{<Phase 1 S1 carriers>} ∪ {Tractor Beam, Pain for All, Moonlit,
    Duskmourn's Domination, Chorale, Cracked Skull, Sporogenic}` —
    no extra Aura silently admitted via under-attribution. Pinned
    per-phase so each Phase A/B/C cycle reads the expected admit-set
    delta off the previous cycle's pinned baseline.
12. **Subsystem-attribution pin:** exactly 3 EoE Aura printings flip
    PROBED (`subsystem-gated` → `byte-equal`) over the campaign:
    Chorale (Phase A), Cracked Skull (Phase B), Sporogenic
    Infection (Phase C). +2,783 deck delta concentrated on Chorale.

## 8. Estimated cycle count

Per the per-card multi-cycle precedent (round-83 plan §6 +
Pain for All Phase 3 closure + Phase 4 S3 Moonlit closure: 1
Effect port + 1 admit-set + 1 real-EoE probe = ~2-3 cycles per card
on top of the shared decision-pump landings):

| Cycle | Owner | Deliverable |
|---:|---|---|
| 1 | Rust agent | **Phase A substrate landing:** `Effect::ReanimateTargetCreatureCardFromDefendersGraveyard` + `Target::GraveyardCreature` + `PendingDecision::GraveyardCardChoice` + put-into-bf-tapped-and-attacking primitive + ATTACKS-trigger Aura-side dispatch (verify-first; widen if missing) + `IsHost(subject="attacker")` admit-set teeth. **Sole Rust slice this round** (`.pyd` race rule). |
| 2 | Python/bench agent | **Phase A bridge + admit + probe.** `_ta_dict_to_python_effect` arm + `_python_ta_to_safe_dict_aura_phase3` widen + `_aura_triggers_are_phase3_safe` widen + Chorale real-EoE probe + Tail-X2 admit (EoT sustain). +2,783-deck flip. |
| 3 | Rust agent | **Phase B substrate landing:** `Effect::TargetOpponentLookHandMayDiscard` + `PendingDecision::MayDiscardChoice` + `PendingDecision::OpponentHandCardChoice` + one-way-reveal substrate (`GameObject.publicly_known_to` or per-card `revealed_to` bitfield). Sole Rust slice this round. |
| 4 | Python/bench agent | **Phase B bridge + admit + probe.** `_ta_dict_to_python_effect` arm + emitter widen + `_aura_triggers_are_phase3_safe` widen (Phase B shape only — Tail-X1 NOT yet widened because Sporogenic hasn't landed) + Cracked Skull real-EoE probe. Cracked Skull flips PROBED (0-deck signal — positive control). |
| 5 | Rust agent | **Phase C substrate landing:** `Effect::TargetOpponentSacrificesCreatureOtherThanEnchanted` + `PendingDecision::SacrificeChoice.excluded_object_id` slot widen. Sole Rust slice this round. |
| 6 | Python/bench agent | **Phase C bridge + admit + probe (campaign closure).** `_ta_dict_to_python_effect` arm + emitter widen + `_aura_triggers_are_phase3_safe` widen (Phase C + Tail-X1 BOTH) + Sporogenic real-EoE probe + no-silent-auto-grow regression pin (§7.4 pin 11). Sporogenic flips PROBED. |
| 7 | Doc agent (rolling) | SEARCH_LIMITATIONS.md entries (§9) + per-cycle pool parity regen + `residue_worklist.json` per-phase closure stamps + Phase-3+-complete worklog. |

**Estimated total: ~5-7 cycles for Phase 3+ campaign closure**,
mirroring the round-83 verify-first walk's "≥2 cycles per card"
finding. The Phase A cycle MAY spill to 2 Rust rounds if the
ATTACKS-trigger Aura-side dispatch is missing today (verify-first
step §4.5) or if the cross-graveyard target enumeration surfaces
multi-opponent edge cases. The Tail-X1/X2 widens are intentionally
sequenced into the last bench cycle of each long-pole Effect (so
each tail widens IN THE SAME slice as the card whose long-pole
unlocks it).

**Campaign total: ~7 cycles** to close all 3 cards / 2,783 decks,
slightly cheaper than the cost-reduction campaign's projected 10
cycles (no `Condition`-grammar port required; the new substrate
is pure Effect-resolve + decision-pump, which has well-established
precedent from Phase 3 Pain for All + Phase 4 S3 Moonlit). The
Tail-X1/X2 widens are zero-cycle riders (one-line gate edits).

## 9. SEARCH_LIMITATIONS.md entries (land WITH each phase cycle)

Three entries (one per Phase A / B / C), each landing with the
phase's Python-side bench cycle:

1. **Phase A (Chorale) — `IsHost(subject="attacker")` admit-set
   slot widened narrow-scope.** Location:
   `trajectory.py::_aura_triggers_are_phase3_safe` Phase-A admit
   branch. Why OK: the gate is a tight (event=ATTACKS, predicate-
   class=IsHost, predicate-subject="attacker", effect-class=Reanimate…)
   match; any wider `IsHost(subject="attacker")` shape (e.g. with a
   different effect or different event) stays declined. Failure mode:
   a future Aura carrying `ATTACKS+IsHost(attacker)+<different
   effect>` would NOT be silently admitted — the gate's tuple match
   refuses the unknown effect. Fix-scope: per-Aura phase-extension
   slice. Impact: +1 card (Chorale) / +2,783 17lands decks, 0
   strength cost.
2. **Phase B (Cracked Skull) — one-way reveal substrate scope.**
   Location: `state_ops_resolve.rs::Effect::TargetOpponentLookHand
   MayDiscard` + the new `publicly_known_to` GameObject field. Why
   OK: Rust mirrors Python's `reveal_to` primitive 1:1 (one-way
   visibility, hand cards become known to caster only). Failure
   mode: future Effects exposing OPPONENT's hand to a non-caster
   player (e.g. team-multiplayer reveal) would need a multi-target
   reveal_to widen. Fix-scope: trivial generalization once a carrier
   ships. Impact: +1 card (Cracked Skull) / 0 17lands decks, 0
   strength cost. **Bench-strategy coverage caveat:** probe-driven,
   not organic (per §7.3 picker note).
3. **Phase C (Sporogenic) — target-opponent-sacrifices-other-than-X
   substrate scope.** Location: `state_ops_resolve.rs::Effect::
   TargetOpponentSacrificesCreatureOtherThanEnchanted` + the new
   `PendingDecision::SacrificeChoice.excluded_object_id` slot. Why
   OK: target opponent's `Agent.choose_sacrifice` consumes the
   options list with the host excluded, byte-equal with Python's
   `legal = [... for o in state.battlefield if o.id != excluded_id]`.
   Failure mode: future Effects with multi-permanent exclusion (e.g.
   "other than enchanted creature and equipped creature") would need
   the slot generalized to `excluded_object_ids: Vec<u32>`. Fix-scope:
   one-line slot widen + emitter widen when first multi-exclusion
   carrier ships. Impact: +1 card (Sporogenic Infection) / 0 17lands
   decks, 0 strength cost.

## 10. Rejected alternatives

### 10.1 Land all 3 Effect ports in one Rust slice

**Rejected.** Each long-pole Effect carries its own decision-pump
substrate (Phase A: graveyard-card-choice; Phase B: may-gate +
opponent-hand-card-choice + one-way-reveal substrate; Phase C:
target-routed sacrifice with excluded-id slot). Folding them into
one Rust slice would be a single ~1500-line PR with three new
`PendingDecision` variants, a new `Target` variant, and three new
Effect resolves — too large to review safely; would block forever
on the first sub-piece's hot-path regression. The phase-split
mirrors the round-83 Phase 3 Pain for All + Phase 4 S3 Moonlit
precedent of one Effect per slice.

### 10.2 Ship Tail-X1 / Tail-X2 admit-set widens as a single bench-only round

**Rejected.** The all-or-nothing
`_aura_triggers_are_phase3_safe` gate refuses to admit a card
whose OTHER trigger isn't in the safe set, so widening Tail-X1
(`DEALT_DAMAGE+IsHost+DestroyEnchantedPermanent`) and Tail-X2
(`BEGINNING_OF_END_STEP+ControlledByYou+SacrificeSelfUnlessVoidActive`)
alone flips NO cards — every Phase-3+ carrier has its tail
PLUS an uncovered long pole. Per the round-83 plan §6 finding
("Common admit-set widen these 3 cards share … cannot flip any of
the 3 cards because each card's OTHER trigger surface carries an
uncovered Effect"), the widens must ride a card-closing Effect
slice for their leverage to realize. Rejected as a no-op step.

### 10.3 Implement `EnchantedCreatureFightsTargetEffect` /
**Meltstrider's Resolve closure in Phase 3+**

**Rejected — out of substrate scope.** Meltstrider's Resolve is in
the residue worklist (`AuraShapeFight-MeltstridersResolve`, formerly
`blocked_genuinely_missing`, now CLOSED at the Effect-level
honest-stop in slice-19 — `EnchantedCreatureFightsTargetEffect`
shipped Rust+bridge). Its closure is a SEPARATE bench-driven slice
that does NOT belong to the S4-triggered-on-`attached_to`-event
sub-shape this doc scopes — Meltstrider's `EnchantedCreatureFights`
trigger is a one-shot ETB-fight (CR 701.12 "fight"), not a
DEALT_DAMAGE-on-host loop. The Effect was already shipped; pending
the bench probe slice. Phase 3+ doesn't fold it in.

### 10.4 Implement Phase 4 S3 replacement-rider shapes (rooms / lands)

**Rejected — already CLOSED.** Moonlit Meditation flipped PROBED
2026-05-21 via `b226fbf4` (`GameObject.token_supertype_override` +
`moonlit_token_substitution`) + `3dc1719d` (slug-credit delegator).
The S3 replacement-rider scope is OUT of Phase 3+ scope — Phase 3+
strictly attacks the S4 triggered-effect Aura tail.

### 10.5 Widen `_printing_is_bridge_simple_aura` directly (skip the helper)

**Rejected — the anti-pattern (round-38-E5 / count-chasing).**
Deleting the `_aura_triggers_are_phase3_safe` gate at line 7766
and naively widening the loader admit predicate would admit ALL
triggered Auras into the bench WITHOUT the substrate, immediately
shipping a guaranteed divergence: Python applies the trigger;
Rust drops the Effect with the unknown-token hard-error at registry
build (loud failure, but moves the failure from runtime divergence
to load-time crash). The §2 discipline ("no silent guaranteed
divergence") is preserved by the all-or-nothing helper-gate
indirection — Phase 3+ inherits that.

## 11. Acceptance / sign-off

Phase 3+ is complete and ready to merge to `main` when:

1. All ~12 pins (§7.1-§7.4) pass on the parity gate after each
   phase cycle.
2. The 3 real-EoE probes (§7.3) pass byte-equal through the
   long-pole-trigger paths on both engines.
3. The decline-set / no-silent-auto-grow regression pin (§7.4 pin
   11) confirms +3 cards admitted, 0 spillover.
4. All 3 SEARCH_LIMITATIONS.md entries (§9) land alongside their
   phase's Python-side cycle.
5. `.pyd` rebuilt clean; the parity gate
   (`tests/test_parity_smoke.py + test_cross_engine_etb_triggers.py
   + test_trajectory_parity.py + test_trajectory.py +
   test_measure_pool_parity.py`) stays green.
6. `docs/residue_worklist.json` Aura S4 entries flip:
   - `Chorale-attacks-reanimate` → `closed`
   - `CrackedSkull-etb-may-discard` → `closed`
   - `SporogenicInfection-etb-target-sac` → `closed`
7. `docs/SUBSYSTEM_BLOCKED_LEVERAGE_INVENTORY.md` Aura-attachment
   row updates: "3 multi-gated tail" → "**CLOSED** — all S4
   triggered carriers admitted end-to-end".

## 12. Cross-references

- `docs/AURA_ATTACHMENT_SUBSTRATE_PLAN.md` — round-by-round plan
  (Phases 1 / 2 / 2.5 / 3 / 4-S3 LANDED); §3 Phase 4 specifies
  the `SacrificeSelfUnlessVoidActive` substrate (LANDED) +
  Tail-X2 admit dependency. The 2026-05-21 verify-first walk
  (lines 1005-1069) is the source of truth for the per-card scope
  this doc scopes.
- `docs/SUBSYSTEM_BLOCKED_LEVERAGE_INVENTORY.md` §6 lines
  2035-2125 — the 3-card S4 multi-gated composition row + the
  per-card verify-first walk findings.
- `docs/COVERED_BY_CONSTRUCTION_PROBE_WRITING_SATURATION_2026-05-25.md`
  — the saturation report identifying Aura-attachment as the LAST
  unscoped major DEFERRED row (3 cards / 2,783 decks); this doc
  closes that scoping gap.
- `docs/COST_REDUCTION_SUBSTRATE_PHASE_1_DESIGN.md` — campaign-
  scoping format precedent (the gold-standard 13-section template
  this doc mirrors).
- `docs/WARP_COST_PHASE1_DESIGN.md` — multi-cycle Rust substrate
  sequencing precedent.
- `docs/BLOCKED_GENUINELY_MISSING_INVENTORY.md` — historical context
  for the Aura `genuinely_missing` tier (now empty); the Phase 3+
  campaign does NOT reopen that tier — it closes the S4 multi-
  gated `subsystem-gated` residue.
- `docs/SEARCH_LIMITATIONS.md` — locked-in SL entries for Phase 1 /
  2 / 3 / 4-S3 Aura substrate; Phase 3+ appends three more (§9).
- `src/mtg_bot/effects/generic/graveyard.py:474-554` — Python
  `ReanimateTargetCreatureCardFromDefendersGraveyard` (live source
  of truth for Phase A's resolve semantics).
- `src/mtg_bot/effects/generic/discard.py:298-391` — Python
  `TargetOpponentLookHandMayDiscard` (live source of truth for
  Phase B's resolve semantics).
- `src/mtg_bot/effects/generic/opponent_punishers.py:68-144` —
  Python `TargetOpponentSacrificesCreatureOtherThanEnchanted`
  (live source of truth for Phase C's resolve semantics).
- `src/mtg_bot/parity/trajectory.py:7440-7529` —
  `_aura_triggers_are_phase3_safe` (the §2 canonical chokepoint
  Phase 3+ widens).
- `src/mtg_bot/parity/trajectory.py:7532-7626` —
  `_python_ta_to_safe_dict_aura_phase3` (the matching emitter Phase
  3+ widens lock-step).
- `src/mtg_bot/parity/trajectory.py:7629-7924` —
  `_printing_is_bridge_simple_aura` (the loader admit predicate;
  Phase 3+ does NOT touch — it widens the helper the predicate
  calls).
- `rust/src/cards.rs:4169` — `Effect::DestroyEnchantedPermanent`
  (Tail-X1 dependency, LANDED).
- `rust/src/cards.rs:4910` — `Effect::SacrificeSelfUnlessVoidActive`
  (Tail-X2 dependency, LANDED).
- `rust/src/cards.rs:9037` — `Predicate::IsHost { subject:
  Option<String> }` (Phase A subject-slot dependency, LANDED).
- `rust/src/cards.rs:5843` / `:5962` — `Event::BeginningOfEndStep`
  / `Event::DealtDamage` dispatch (Tail dependencies, LANDED).
- `rust/src/state_ops_resolve.rs:14292,15923` —
  `DestroyEnchantedPermanent` / `SacrificeSelfUnlessVoidActive`
  resolve arms (LANDED).

## 13. Regenerating the enumeration

```
PYTHONPATH=src ../../mtg-bot/.venv-py313/Scripts/python.exe -c "
from mtg_bot.cards.parser import OracleParserCardSource
from mtg_bot.parity.trajectory import (
    _printing_is_bridge_simple_aura,
    _aura_triggers_are_phase3_safe,
)
src = OracleParserCardSource()
ps = src.get_printings()
for name in [
    'Chorale of the Void', 'Cracked Skull', 'Sporogenic Infection',
    'Pain for All',  # positive control
]:
    p = ps[name]
    safe = _aura_triggers_are_phase3_safe(p.triggered_abilities or ())
    admit = _printing_is_bridge_simple_aura(p)
    print(f'{name:<30} triggers_safe={safe!s:<5}  loader_admits={admit!s}')
"
```

reproduces the live decline state for the 3 carriers (`triggers_safe=False`
/ `loader_admits=False`) + Pain for All as positive control
(`triggers_safe=True` / `loader_admits=True`) — the exact baseline
Phase 3+ flips card-by-card. The per-card trigger surface
(`p.triggered_abilities`) is the structural enumeration §1.3 walks;
the `_aura_triggers_are_phase3_safe` chokepoint is the canonical
admit oracle the campaign extends.
