# BLOCKED-RUST-EFFECT residue card plans (round 50, N2)

**Slice type:** docs-only scoping. No code touched (`rust/`, `src/`,
tests untouched; no `maturin`; no gate run needed — nothing built).
Read-only scout `scripts/scout_r50_residue_deck_counts.py` added per
the scout convention.

**Purpose.** Round 49's audit refresh established that ~14 rounds of
Rust-lane work were X-from-count matrix saturation with **0 real EoE
consumers**, NOT closures of the real residue. The campaign pivoted to
**real-card levers**. This doc converts the residue list from "names in
an audit" into ready-to-implement per-card specs so round 51's Rust
agent can close a real card fast instead of doing more surface
coverage.

**Inputs.** `docs/EOE_PROBE_READINESS_AUDIT.md` §round-49 refresh +
§2.6 + §round-19 residue tables; verbatim oracle text from
`data/edge_of_eternities.json`; deck counts from the 17lands EoE pool
`data/17lands/eoe_decks.json.gz` (129,996 draft-build records — the
raw build-record frequency; relative ranking is the signal, not the
absolute, and the ~5000 figure in CLAUDE.md is the dedup'd archetype
loader count, a different denominator).

---

## Headline finding (read this first)

**The audit's residue list is itself stale on at least one entry.**
Walking each residue card against the *live* `Effect` enum
(`rust/src/cards.rs` @ `34573868`) and the *live*
`_ta_dict_to_python_effect` arm inventory
(`src/mtg_bot/parity/cross_engine.py`):

- **Mechanozoa is NOT BLOCKED-RUST-EFFECT.** Its exact ETB
  ("tap target artifact or creature an opponent controls and put a
  stun counter on it") is `Effect::TapTargetOpponentPermanentAndStunIt`
  (`cards.rs:2412`, **round-30 stun-counter substrate**) and is
  **already bridge-wired** (`cross_engine.py:3168`,
  `tap_target_opponent_permanent_and_stun_it`). Python sibling
  `TapTargetOpponentPermanentAndStunIt` at
  `effects/generic/tap.py:217`. The audit's §2.6 / §round-19 "no
  StunCounter substrate in Rust — Confirmed BLOCKED-RUST-EFFECT" line
  predates round-30 and was never re-checked. Mechanozoa's only
  remaining blocker is the **`warp_cost`** keyword on the card (a
  §2-declined cost-mechanic class) gating the *production-deck loader
  admit* — NOT the Effect arm. It belongs in BLOCKED-FILTER (warp), not
  BLOCKED-RUST-EFFECT. A direct synthetic/real ETB cross-engine probe
  for the bare ETB shape is droppable today with **zero new Rust**.
  **This is the single highest-value finding in this slice** and feeds
  the round-51 recommendation below.

- **Warmaker Gunship's ETB Effect is fully substrated too.** "deals
  damage equal to the number of artifacts you control to target
  creature an opponent controls" is exactly
  `Effect::DealDamageToOpponentCreatureByArtifactCount`
  (`cards.rs:1333`, round-32) and bridge-wired
  (`cross_engine.py:6326`). The residual blocker is **not the Effect
  arm** — it is the `Station` ability + `Spacecraft` artifact type
  (the trigger is "When this Spacecraft enters"). That is a
  Station/Spacecraft-subsystem admit, not a new Rust Effect. It should
  be reclassified out of the BLOCKED-RUST-EFFECT *effect* bucket into a
  Station-subsystem bucket.

Net: of the ~17 names carried as BLOCKED-RUST-EFFECT residue, **2
(Mechanozoa, Warmaker Gunship) have their Effect arm already shipped on
both engines** and are mis-bucketed; the true new-Rust-Effect residue
is **~15 distinct asks**, of which only a small minority are
bridge-correct to close as a single bespoke Effect slice.

---

## Residue overview — full real-card-coverage worklist

Ranked by 17lands deck count (real-impact proxy). "Bridge-correct?" =
can BOTH engines model this card *identically* via a single bespoke
Effect arm + bridge arm, with no deferred subsystem and no silent
mistranslation (§2 discipline).

| Card | Decks | Effect shape needed | Blocked on | Bridge-correct to close? | Effort |
| --- | ---: | --- | --- | --- | --- |
| **Mechanozoa** | 21779 | *(none — `TapTargetOpponentPermanentAndStunIt` shipped r30 + bridged)* | `warp_cost` filter admit only (NOT an Effect gap) | **n/a — already substrated**; reclassify to BLOCKED-FILTER | 0 (probe drop) |
| **Command Bridge** | 24522 | `SacrificeSelfUnlessYouTapAPermanent` (land-ETB) | land-ETB trigger path + tap-a-permanent cost decision; mana-land | **NO** — needs cost-style decision subsystem + land-ETB | multi-round |
| **Perigee Beckoner** | 21131 | `GrantDiesReturnTriggerAndPumpUntilEOT` | nested-trigger-grant substrate (grants a NEW triggered ability to the target) + `warp_cost` | **NO** — nested-ability-grant subsystem | multi-round |
| **Dauntless Scrapbot** | 18378 | `ExileEachOpponentGraveyardThenCreateLander` | exile-each-graveyard substrate + Lander token-registration (round-49 N1 lane) | **NO** — token-registration-loader-gated | multi-round |
| **Tractor Beam** | 16285 | `TapEnchantedThenControlSwapNoUntap` (Aura) | Aura `attached_to` end-to-end + control-swap + don't-untap | **NO** — Aura-attachment subsystem | multi-round |
| **Meltstrider's Resolve** | 15259 | `Effect::EnchantedCreatureFightsTarget` (Aura) | Aura `attached_to` routed end-to-end (`cards.rs:1240` deferred note) | **NO** — Aura-attachment subsystem (SEARCH_LIMITATIONS.md) | multi-round |
| **Monoist Circuit-Feeder** | 14727 | `TwoSubjectPumpAndDebuffByArtifactCount` | two simultaneous mobile targets (one yours +X/+0, one theirs -0/-X) | **YES** (with first-slice deterministic targets) | 1 round |
| **Faller's Faithful** | 14108 | `DestroyTargetThenDrawIfUndamaged` | damage-this-turn ledger neither engine maintains for this | **NO** — needs per-object damaged-this-turn tracking | multi-round |
| **Pulsar Squadron Ace** | 10271 | `LookTop5RevealSpacecraftElseCounterOnSelf` | `LookAtTopNRevealOrCounter` exists (`cards.rs:2152`); needs Spacecraft sub-mode + bottom-random | **PARTIAL** — substrate exists, sub-mode param | 1–2 rounds |
| **Extinguisher Battleship** | 6237 | `Sequence(DestroyTargetNoncreature, DamageEachCreature(4))` | component arms exist; needs bridge arms + Station/Spacecraft admit | **PARTIAL** — Effect composes; Station gates the card | 1 round (effect) |
| **Warmaker Gunship** | 5926 | *(none — `DealDamageToOpponentCreatureByArtifactCount` shipped r32 + bridged)* | `Station` ability + `Spacecraft` type admit (NOT an Effect gap) | **n/a — already substrated**; reclassify to Station-subsystem | 0 (effect) |
| **Mightform Harmonizer** | 5759 | `Effect::DoubleTargetPowerUntilEOT` driven by landfall | new Effect arm + landfall predicate (Subject substrate) + `warp_cost` | **PARTIAL** — Effect is clean; landfall+warp gate the card | 1 round (effect) |
| **Astelli Reclaimer** | 4565 | `ReturnNoncreatureNonlandFromGYWithMVLEManaSpent` | X = mana spent to cast self → needs cast-cost tracking subsystem + `warp_cost` | **NO** — cast-cost-paid ledger subsystem | multi-round |
| **Lightstall Inquisitor** | 4371 | `EachOpponentExilesFromHandMayPlayCostHike` | exile-from-opponent-hand + grant-may-play + cost-increase + land-tapped | **NO** — play-from-exile permission subsystem | multi-round |
| **Pain for All** | 4367 | `Effect::EnchantedDealsDamageThenPropagate` (Aura) | Aura `attached_to` + self-replicating damage trigger | **NO** — Aura-attachment + damage-feedback subsystem | multi-round |
| **Roving Actuator** | 3400 | `VoidExileFromGYCopyAndCastForFree` | Void condition exists (`cards.rs:2045`); cast-copy-for-free still new Rust | **NO** — cast-from-exile-copy subsystem | multi-round |
| **Famished Worldsire** | 2324 | `LookTopXByPowerPutLandsTapped` (X = self power) | look-X-by-source-power + selective-put-lands-tapped; `Ward`/`Devour` riders | **PARTIAL** — Effect is derivable; X-by-power plumbing + Devour gate | 1–2 rounds |

**Worklist size:** 17 carried names. **2 mis-bucketed** (Mechanozoa,
Warmaker Gunship — Effect arms already shipped + bridged; reclassify).
Of the remaining 15 true new-Rust-Effect asks: **1 cleanly
bridge-correct to close in a single round (Monoist Circuit-Feeder)**;
**3 partial (Effect itself is clean but the card is gated by a separate
subsystem — Extinguisher Battleship, Mightform Harmonizer,
Famished Worldsire)**; **11 deferred-subsystem-blocked**, by subsystem:

- **Aura `attached_to` end-to-end (3):** Tractor Beam, Meltstrider's
  Resolve, Pain for All. `cards.rs:1240` already documents this as the
  deferred Fight follow-up; closing Aura-attach unblocks all 3 plus the
  round-19 §2.6 Aura tail.
- **Cast/cost subsystem (3):** Astelli Reclaimer (mana-spent ledger),
  Lightstall Inquisitor (play-from-exile-with-cost-hike permission),
  Roving Actuator (cast-copy-for-free from exile).
- **Nested-ability-grant (1):** Perigee Beckoner (grants a *new* DIES
  trigger onto the target).
- **Damage-this-turn ledger (1):** Faller's Faithful.
- **Token-registration / exile-each-GY (1):** Dauntless Scrapbot
  (round-49 N1's token-registration substrate lane).
- **Land-ETB + cost-decision (1):** Command Bridge.
- **(Pulsar Squadron Ace counted under "partial" — substrate present,
  needs a sub-mode parameter + bottom-random ordering.)**

---

## Detailed plans — top 3 (ranked: bridge-correctness tractability × deck-count impact)

Ranking note: deck count alone would put Command Bridge (24522) and
Perigee Beckoner (21131) on top, but both are deferred-subsystem-blocked
(NOT bridge-correct to close as a single Effect slice) and are honestly
ranked OUT of the top-3 with the reason stated. Mechanozoa (21779) is
excluded because its Effect is already shipped — the right action there
is a probe-drop, not an Effect slice (covered as Bonus below). The top 3
are the highest deck-count cards that are bridge-correct to close (or
whose Effect arm is clean even if a separate subsystem gates the full
card), ordered by closeability.

### #1 — Monoist Circuit-Feeder  (decks=14727)  — RECOMMENDED round-51 pick

**Oracle (verbatim, `data/edge_of_eternities.json`):**
> `[Artifact Creature — Nautilus] {4}{B}{B}`
> Flying
> When this creature enters, until end of turn, target creature you
> control gets +X/+0 and target creature an opponent controls gets
> -0/-X, where X is the number of artifacts you control.

**Why #1.** Highest deck count among cards that are bridge-correct to
close as a single bespoke Effect slice. The X-from-artifact-count
denominator read is the *exact* plumbing the saturated damage row
proves generalizes (round-32 `DealDamageToOpponentCreatureByArtifactCount`
reads the same denominator). The only genuinely new shape is the
**two-subject simultaneous pump+debuff with a shared X**. No Aura, no
cast-cost, no nested trigger, no land-ETB, no damage ledger — both
engines already have until-EOT P/T modification and the artifact-count
walk. Bridge-correct: yes.

**`Effect` shape.** New unit variant (X is dynamic, computed at resolve;
no payload — mirrors the round-32→49 X-from-count unit-variant schema
convention):

```rust
/// **BLOCKED-RUST-EFFECT slice — Monoist Circuit-Feeder ETB.**
/// Until end of turn: a creature the source-controller controls gets
/// +X/+0; a creature an opponent controls gets -0/-X; X = number of
/// artifacts the source-controller controls (clamp >= 0; X==0 ->
/// silent no-op, matching the round-32..49 X-from-count zero
/// short-circuit). Mirrors Python's
/// `PumpYoursAndDebuffOpponentByArtifactCountUntilEOT`.
TwoSubjectPumpAndDebuffByArtifactCount,
```

**Rust sketch.**

- *parse_effect arm* (`match kind` near the other
  `*_by_artifact_count` arms, ~`cards.rs:4478` block): on
  `"two_subject_pump_and_debuff_by_artifact_count"` →
  `Ok(Effect::TwoSubjectPumpAndDebuffByArtifactCount)`. Unit variant —
  no field reads (copy the round-49
  `gain_life_equal_to_your_life_total` parse arm shape verbatim, swap
  the literal).
- *to_dict arm* (`~cards.rs:6808` block): emit
  `d.set_item("kind", "two_subject_pump_and_debuff_by_artifact_count")`.
  No other keys (round-trip dict-shape consistency convention).
- *resolve arm* (`state_ops_resolve.rs`, beside the
  `GainLifeEqualToYourLifeTotal` arm @ `~4238`):
  1. Source-controller resolution via the standard 5-zone + stack scan
     (copy the `'outer_sc_glyl` block from
     `state_ops_resolve.rs:4243-4271` verbatim — silent fizzle if
     source untrackable; the X must read from the source's *actual*
     controller, not active player).
  2. `let x = artifact_count_for(controller)` — reuse the existing
     artifact-count helper the round-32
     `DealDamageToOpponentCreatureByArtifactCount` resolve arm uses
     (grep `DealDamageToOpponentCreatureByArtifactCount =>` in
     `state_ops_resolve.rs` and lift its denominator read — file
     isolation: re-derive a private `fn` in the resolve module rather
     than cross-importing, per the file-isolation rule).
  3. `if x <= 0 { return Ok(()); }` (zero short-circuit).
  4. Pick the source-side target = FIRST creature on `controller`'s
     battlefield (smallest Vec index); pick the opponent-side target =
     FIRST creature on `1 - controller`'s battlefield. Same
     first-creature-on-bf deterministic scan
     `FightTargetCreatureWithTargetCreature` (`cards.rs:1194-1203`) and
     `PumpTargetCreatureUntilEOT` use. Either side missing → that side
     is a silent no-op (the other side still applies — the oracle uses
     two independent "target" clauses, NOT "up to one"; if no legal
     target exists the ability still resolves the half that has one,
     CR 608.2c).
  5. Apply an until-EOT P/T modifier to each chosen object. Reuse the
     existing until-EOT pump mechanism (`PumpTargetCreatureUntilEOT`'s
     resolve arm in `state_ops_resolve.rs` shows the exact
     `until_eot_pt` push shape — source side: `+x/+0`; opponent side:
     `+0/-x`). Cleanup at end of turn is already handled by the
     existing until-EOT modifier expiry path.

**Python class.** `class PumpYoursAndDebuffOpponentByArtifactCountUntilEOT(Effect)`
in `src/mtg_bot/effects/generic/pump.py` (sibling to the existing
`PumpTargetCreatureUntilEOT` family — that file already owns the
until-EOT P/T machinery; check `effects/generic/` for the exact pump
module name, it is the one defining `PumpTargetCreatureUntilEOT`).
Unit-shape `@dataclass(frozen=True)` with no constructor args (X is
dynamic — mirrors round-45/49 unit-shape convention). `resolve(self,
state, controller_id, targets=())`: `x = max(0, artifacts you
control)`; `if x <= 0: return`; pick first own creature → apply
`+x/+0` until EOT; pick first opponent creature → apply `+0/-x` until
EOT; `state.log.append(...)`. Mirror the deterministic-first-creature
target selection the Python `FightTargetCreatureWithTargetCreature` /
pump classes use so the engines stay byte-equal.

**Bridge arm sketch** (`_ta_dict_to_python_effect`, IMMEDIATELY ABOVE
`# === PHASE5_BRIDGE_ARMS_INSERT_ABOVE_THIS_LINE ===` @
`cross_engine.py:7535`):

```python
if kind == "two_subject_pump_and_debuff_by_artifact_count":
    # BLOCKED-RUST-EFFECT slice — Monoist Circuit-Feeder ETB.
    # Unit variant; X dynamic (artifacts controller controls,
    # clamped >=0). Mirrors round-32 damage-by-artifact-count's
    # denominator read on a two-subject until-EOT pump+debuff
    # apply substrate. Bridge translator ignores all other keys.
    from mtg_bot.effects.generic.pump import (
        PumpYoursAndDebuffOpponentByArtifactCountUntilEOT,
    )
    return PumpYoursAndDebuffOpponentByArtifactCountUntilEOT()
```

**Pin plan.**

- **Rust regression pins** (in the Rust test module that covers the
  other X-from-count substrates — `rust/src/` cargo tests or the
  `tests/test_parity_smoke.py` Rust-driven pins, whichever the
  round-49 `gain_life_equal_to_your_life_total` slice used; match that
  precedent): 4–6 pins — X=0 silent no-op; X=N pumps own first
  creature +N/+0; debuffs opponent first creature +0/-N; only-own-side
  target present (opp-side no-op, own-side still applies); only-opp-side
  target present; cross-controller resolve (flicker re-ETB while other
  seat active — X reads source-controller's artifacts, not active
  player's).
- **Cross-engine bridge pins** (3–5, IMMEDIATELY ABOVE
  `# === PHASE5_BRIDGE_PIN_TESTS_INSERT_ABOVE_THIS_LINE ===` at EOF of
  `tests/test_cross_engine_etb_triggers.py`): dict-shape round-trip
  (`{"kind": "two_subject_pump_and_debuff_by_artifact_count"}` →
  Python class → identical state delta); X=0; X=3 both sides;
  one-sided.
- **Real-EoE probe** (IMMEDIATELY ABOVE
  `# === PHASE5_PROBES_INSERT_ABOVE_THIS_LINE ===` at EOF of
  `tests/test_parity_smoke.py`): `test_cross_engine_real_eoe_monoist_circuit_feeder_etb_two_subject_pump_debuff_by_artifact_count_parity`
  — load the real Monoist Circuit-Feeder printing from
  `data/edge_of_eternities.json`, give the source-controller K
  artifacts + a creature, give the opponent a creature, resolve the
  ETB on both engines, assert byte-equal state. This is a REAL EoE
  consumer (14727 decks) — no synthetic-only fallback needed (unlike
  the round-45/47/48/49 0-consumer matrix slices).

**§2 bridge-correctness audit.** Both engines model this identically:
both have until-EOT P/T modification with end-of-turn expiry; both have
the artifact-count board scan (round-32 proved it bridge-correct on the
damage substrate). The only divergence risk is **target selection
order** — mitigated by both sides using the same first-creature-on-bf
deterministic scan (the established campaign convention for
no-decision-callback target picks; `cards.rs:1194-1203` precedent).
Note `Monoist Circuit-Feeder` carries no `warp_cost`/`station`/Aura
rider — the ETB is the whole card's relevant behavior, so closing this
Effect closes the card for the production-deck loader (subject to the
loader's creature-feature allowlist, which `flying` already passes —
`_SAFE_KEYWORDS`). **No silent-mistranslation risk.** Bridge-correct:
**YES**.

**Effort:** 1 round (3–4 commits: Rust variant+arms; Python class;
bridge arm + pins; real-EoE probe). Same shape and cadence as the
round-32→49 X-from-count slices, with one genuinely new but
self-contained apply substrate (two-subject until-EOT pump+debuff).

---

### #2 — Extinguisher Battleship (effect half)  (decks=6237)

**Oracle (verbatim):**
> `[Artifact — Spacecraft] {8}`
> When this Spacecraft enters, destroy target noncreature permanent.
> Then this Spacecraft deals 4 damage to each creature.
> Station (Tap another creature you control: …) — `5+ | Flying, trample`

**Why #2 (and why "effect half").** The ETB *effect* is a pure
composition of arms that **already exist on both engines**:
`Effect::DestroyTargetNonlandPermanent` (`cards.rs:635`),
`Effect::DamageEachCreature` (`cards.rs:145`), `Effect::Sequence`
(`cards.rs:872`). The round-19 audit (§ line 508) flagged exactly this:
"All component arms substrated! … Conservatively kept in
BLOCKED-RUST-EFFECT for now." The new work is **two missing bridge arms**
(`destroy_target_nonland_permanent`, `damage_each_creature`) + a
`sequence` composition probe — NOT a new Rust Effect. (Note the oracle
says "noncreature permanent"; `DestroyTargetNonlandPermanent` is the
closest existing arm — verify the target filter matches; if it must be
"noncreature" specifically, that filter param is the only genuinely-new
Rust, ~10 LOC on the existing destroy arm.)

**Caveat that keeps it at #2 not #1.** The full *card* is gated by the
**`Station` ability + `Spacecraft` artifact type** (the trigger is
"When this Spacecraft enters" and the card is unplayable in the
production-deck loader without Station/Spacecraft admit). So this slice
closes the **Effect/bridge arm** and lands a synthetic + real-EoE ETB
probe, but the card stays loader-gated on Station until that subsystem
lands. Still high value: it converts a §2.6 BLOCKED-RUST-EFFECT entry
to PROBED via cheap bridge arms, and the AOE-damage + targeted-destroy
sequence is a reusable shape.

**Effect shape.** No new variant — `Effect::Sequence(vec![
Effect::DestroyTargetNonlandPermanent{...}, Effect::DamageEachCreature{
amount: 4 } ])`. (If "noncreature" filter precision is required: add a
`noncreature: bool` field or a new `DestroyTargetNoncreaturePermanent`
variant — that is the only candidate new Rust, and it is a
~15-LOC target-filter sibling of the existing destroy arm.)

**Rust sketch.** No parse/to_dict/resolve *Effect* changes if the
existing `DestroyTargetNonlandPermanent` filter is acceptable for the
EoE card pool (Extinguisher Battleship is the only "noncreature
permanent" destroyer in EoE; in practice the only noncreature nonland
permanents are artifacts/enchantments, so nonland≈noncreature for this
pool — document the approximation in `SEARCH_LIMITATIONS.md` if you
take it). The work is the two bridge arms below + a Sequence-composition
probe.

**Python class.** None new — compose the existing
`DestroyTargetNonlandPermanent` + `DamageEachCreature` Python effects
under the existing `Sequence` combinator
(`src/mtg_bot/effects/combinators.py`).

**Bridge arm sketch.** Two new arms above the sentinel:
`if kind == "destroy_target_nonland_permanent": return
DestroyTargetNonlandPermanent(...)` and `if kind ==
"damage_each_creature": return DamageEachCreature(amount=d["amount"])`.
`sequence` is already wired. Then the composed dict
`{"kind": "sequence", "effects": [..., ...]}` round-trips end to end.

**Pin plan.** Rust pins: destroy-then-AOE order (CR — destroy resolves
fully before the 4-damage; a creature destroyed cannot also be hit).
Bridge pins: each new arm round-trips; the Sequence composition
round-trips. Real-EoE probe: synthetic ETB driver (the card is
Station-gated so a full game probe needs the Station subsystem — use
the round-17 Fight synthetic-driver precedent) asserting byte-equal
state after the destroy+AOE.

**§2 bridge-correctness audit.** The Effect composes bridge-correct
arms; both engines run Sequence in PendingDecision-safe order (the
round-36/37/41 Sequence/IfYouDo PendingDecision fixes already hardened
this path). **The only silent-mistranslation risk is the
nonland-vs-noncreature target filter** — flag explicitly: if you ship
with `DestroyTargetNonlandPermanent`, document the
nonland≈noncreature-for-EoE-pool approximation in
`SEARCH_LIMITATIONS.md` (per the project rule on deliberate
divergences). Bridge-correct: **YES for the Effect**; the full card is
**Station-subsystem-gated** (out of scope of an Effect slice).

**Effort:** 1 round for the Effect/bridge arms + synthetic probe. Full
card requires the separate Station/Spacecraft subsystem (multi-round,
not this slice).

---

### #3 — Mightform Harmonizer (effect half)  (decks=5759)

**Oracle (verbatim):**
> `[Creature — Insect Druid] {2}{G}{G}`
> Landfall — Whenever a land you control enters, double the power of
> target creature you control until end of turn.
> Warp {2}{G}

**Why #3.** The audit names the missing Rust arm precisely
(§round-19 line 504, §2.6 line 902):
`Effect::DoubleTargetPowerUntilEOT` — "no Rust arm. Confirmed." The
Effect itself is **clean and bridge-correct**: double-the-power
until-EOT is a simple multiplicative until-EOT P/T modifier both
engines can model identically (Python already has until-EOT P/T;
`DoubleTargetPowerUntilEOT` is a one-class addition). It is a recurring
shape — the round-19 §2.6 "LandfallWithComplexEffect" bucket lists
Mightform Harmonizer as one of 5 cards, and this Effect is its
distinguishing arm.

**Caveat keeping it at #3.** The *card* is gated by two separate
subsystems: the **landfall predicate** (the `Predicate::Subject`
substrate — review-gated on `feature/etb-subject-substrate`, §3 rank 2)
and **`warp_cost`** (a §2-declined cost-mechanic). So this slice ships
the `DoubleTargetPowerUntilEOT` Effect arm + bridge arm + synthetic
"double power" cross-engine probe (driven directly, not via the
landfall trigger), unblocking the *effect half* of the
LandfallWithComplexEffect bucket. The card flips to PROBED only once
the landfall predicate substrate is merged; warp gates the
production-deck-loader admit independently.

**Effect shape.**

```rust
/// **BLOCKED-RUST-EFFECT slice — DoubleTargetPowerUntilEOT.**
/// Target creature the source-controller controls gets +P/+0 until
/// end of turn, where P = that creature's CURRENT power at resolve
/// (doubling = add a copy of current power). First-slice target =
/// first creature on the source-controller's bf. Drives Mightform
/// Harmonizer's landfall effect (predicate is the etb-subject
/// substrate's job). Mirrors Python's `DoubleTargetPowerUntilEOT`.
DoubleTargetPowerUntilEOT,
```

**Rust sketch.** parse/to_dict: unit-variant, copy the round-49
`gain_life_equal_to_your_life_total` arm shape, literal
`"double_target_power_until_eot"`. resolve (`state_ops_resolve.rs`):
source-controller 5-zone+stack scan (same `'outer_sc_*` block); pick
first creature on controller's bf; read its *current effective power*
P (use the same effective-power accessor `FightTargetCreatureWithTargetCreature`
uses @ `cards.rs:1214`); push an until-EOT `+P/+0` modifier (doubling =
add current power as a temp boost — CR 701 "double power" sets it to
2×current, which equals current + current; the additive-until-EOT
encoding both engines already share makes this byte-equal). Empty bf →
silent fizzle.

**Python class.** `class DoubleTargetPowerUntilEOT(Effect)` in the
until-EOT pump module (same file as
`PumpYoursAndDebuffOpponentByArtifactCountUntilEOT` from plan #1 —
`effects/generic/pump.py`). Unit-shape. `resolve`: first own creature;
`p = effective power`; apply `+p/+0` until EOT; log.

**Bridge arm sketch.** Above the sentinel:
`if kind == "double_target_power_until_eot": from
mtg_bot.effects.generic.pump import DoubleTargetPowerUntilEOT; return
DoubleTargetPowerUntilEOT()`.

**Pin plan.** Rust pins: P=0 (no-op-ish, still resolves); P=3 →
+3/+0; cross-controller resolve; empty bf fizzle; interaction with an
existing +1/+1 counter (double reads *effective* power including
counters — pin that the doubling reads post-counter power, matching CR
and Python). Bridge pins (3–5): dict round-trip; P=3; counter
interaction. Real-EoE probe: synthetic driver (landfall predicate not
yet merged) — `test_cross_engine_real_eoe_mightform_harmonizer_double_power_until_eot_parity`
loading the real printing and driving the Effect directly (round-17
Fight synthetic-driver precedent), asserting byte-equal.

**§2 bridge-correctness audit.** The Effect is bridge-correct — both
engines encode until-EOT P/T additively and read effective power
identically (the campaign already relies on this for Fight and pump).
**Silent-mistranslation risk:** the "double" must read *effective*
power (post-counters, post-other-until-EOT-boosts) at resolve, not base
power — pin it explicitly so a base-power Rust read can't silently
diverge. The full *card* is **landfall-predicate-substrate-gated +
warp-gated** (both §3 / §2-declined) — out of scope of an Effect slice;
this slice closes the Effect arm only and is honest about the residual
gates. Bridge-correct: **YES for the Effect**; card flips to PROBED only
post-etb-subject-substrate merge.

**Effort:** 1 round for the Effect/bridge arm + synthetic probe.

---

### Bonus (zero-Rust, highest ROI of all) — Mechanozoa probe drop

Mechanozoa (decks=**21779**, the 2nd-highest deck count in the entire
residue) needs **no new Rust and no new bridge arm** — both shipped
round-30. The only action is to **drop a real-EoE ETB cross-engine
probe** for the existing `tap_target_opponent_permanent_and_stun_it`
arm and **reclassify Mechanozoa out of BLOCKED-RUST-EFFECT** in
`EOE_PROBE_READINESS_AUDIT.md` (it is `warp_cost`-filter-blocked for
the production-deck loader, NOT Effect-blocked). This is a ~1-commit,
zero-build (the .pyd already has the arm), highest-confidence slice.
**Recommended as a co-pick for round 51** alongside Monoist
Circuit-Feeder if a second cheap slice is wanted — but note it touches
tests + the audit doc, so it is a Python-lane / docs slice, NOT a Rust
build slice (it must not race the Rust agent's .pyd).

---

## Round-51 recommendation

**Single best real-card Rust lever: Monoist Circuit-Feeder**
(`TwoSubjectPumpAndDebuffByArtifactCount`). It is the highest-deck-count
card (14727) that is **fully bridge-correct to close in one round as a
self-contained bespoke Effect**, with a **real EoE consumer** (so its
real-EoE probe is genuine, not synthetic-only — unlike every
round-45→49 matrix slice). It reuses the proven artifact-count
denominator plumbing and the established first-creature deterministic
target convention; the only genuinely new shape is a two-subject
until-EOT pump+debuff, which composes cleanly from existing until-EOT
P/T machinery. This is exactly the "real-card lever, not surface
coverage" the campaign pivoted to.

**Co-pick (optional, separate lane):** the Mechanozoa probe-drop +
audit reclassification — zero-build, ~1 commit, closes the
2nd-highest-deck-count residue name for free and corrects a stale audit
entry. Assign to the Python/docs lane so it does not contend the Rust
.pyd build.

**Do NOT pick (despite high deck counts) and why:** Command Bridge
(24522 — land-ETB + cost-decision subsystem), Perigee Beckoner (21131 —
nested-ability-grant), Dauntless Scrapbot (18378 — token-registration),
Tractor Beam / Meltstrider's Resolve / Pain for All (Aura-attachment).
These are deferred-subsystem-blocked; attempting them as a single Effect
slice would force a silent-mistranslation shortcut, violating §2.

**Forward flag for the audit:** `EOE_PROBE_READINESS_AUDIT.md` should
reclassify **Mechanozoa** (Effect shipped r30 + bridged → BLOCKED-FILTER
on `warp_cost`) and **Warmaker Gunship** (Effect shipped r32 + bridged →
BLOCKED on Station/Spacecraft subsystem, not Effect). The round-19 §2.6
"no StunCounter substrate / X-from-artifact-count needs its own arm"
lines are stale post round-30/32. This is the same staleness class the
round-34 and round-49 refreshes flagged — strengthens the round-19 cron
proposal (auto-diff Effect-variant inventory against the audit headline
on every `main` merge).
