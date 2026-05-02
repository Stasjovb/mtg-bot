# PR D retrospective — continuous-effect family migration

Originally written 2026-04-30 as a handoff for the next session. The
work is now done — what follows is the retrospective version, kept
as a pointer to the commits that landed and the remaining
follow-on architectural pieces. The original handoff text lived in
the repository's untracked `docs/PR_D_HANDOFF.md` (never committed
to `main`); this file replaces it.

## Outcome

The modifier-grammar pillar is fully landed. Both halves —
replacement effects (CR 614) and continuous effects (CR 613 layers)
— now flow through `mtg_bot.effects.modifiers` declarations on
`StaticAbility`. The 53-entry bespoke surface is closed (every
`_BESPOKE_*` and `_LITERAL_*_LINES` table is either retired or an
empty `{}` shell pending physical deletion in todo `2b8c4d76`).

## What landed

### Replacement-effect side (PRs A / B and follow-ons)

- **PR A (`9a6208c`)** — foundation. `effects/modifiers.py` defines
  `EventTransform` primitives (`MultiplyCount`, `AddToCount`,
  `AddInstances`, `Replace`, `Prevent`), `EventPattern`,
  `LayerPayload` variants (`GrantKeyword`, `RemoveKeyword`,
  `PowerToughnessBonus`, `AddSubtype`, `SetBasePowerToughness`),
  `ContinuousModifier`, `ReplacementEffect`,
  `dispatch_replacement(state, event, **)`. Five `WOULD_X` events
  added to `Event`. New `Agent.choose_replacement_order` for CR
  616.1 ordering.
- **PR B (`904b16f`)** — routes Quantum Riddler / Starfield Vocalist
  / Loading Zone / Nexus of Fate through the dispatcher; multiple
  Riddlers stack additively (CR-correct).
- **PR C (`0d06d34`)** — scaffolds `condition`,
  `replacement_effect`, `continuous_effect` slots on `StaticAbility`.
- **Name-collision rename (`68c56e3`)** —
  `mtg_bot.effects.modifiers.ContinuousEffect` →
  `ContinuousModifier`, leaving the runtime registry
  `mtg_bot.game.ContinuousEffect` undisturbed.
- **Synthesis paths retired** — all 5 of the original
  replacement-flag synthesis surfaces (token-doubling /
  counter-doubling / extra-ETB-trigger / hand-at-most-one-draw /
  shuffle-into-library-instead-of-graveyard) now ship as native
  `StaticAbility.replacement_effect` declarations. Reference cards:
  Exalted Sunborn, Loading Zone, Starfield Vocalist, Quantum
  Riddler, Nexus of Fate / Green Sun's Zenith.

### Continuous-effect side (the bulk of PR D)

- **`walk_continuous_modifiers`** in `effects/modifiers.py` is the
  consumer-facing dispatcher; consumed by `effective_keywords` and
  the layer-7c walker.
- **Layer-7c walker (`24d5038`)** — folds anthem-family
  `PowerToughnessBonus` contributions into `effective_power` /
  `effective_toughness`.
- **Layer-6 GrantKeyword synthesis (`f1b548d`)** — generic walker
  drives keyword grants from `ContinuousModifier` declarations.
- **Anthem family fully migrated** — every printing that previously
  carried hardcoded `power_bonus` / `toughness_bonus` /
  `granted_keywords` static-ability fields now declares
  `ContinuousModifier(layer=7c, payload=PowerToughnessBonus(...))`
  + `ContinuousModifier(layer=6, payload=GrantKeyword(...))`
  pieces.
- **Mechan Shieldmate** (`creature_builder.py:631-648`) — declares
  `StaticAbility(condition=ControlledArtifactEnteredThisTurn(),
  continuous_effect=ContinuousModifier(layer=6,
  payload=RemoveKeyword("defender")))`; the legacy
  `attack_bypass_if_artifact_entered_this_turn` flag and the
  `combat._can_attack_through_defender` helper are gone.
- **Illvoi Infiltrator** (`creature_builder.py:650-668`) —
  declares `StaticAbility(condition=AtLeastNSpellsCastThisTurn(2),
  continuous_effect=ContinuousModifier(layer=6,
  payload=CantBeBlocked()))`; the legacy
  `unblockable_if_two_spells_cast_this_turn` flag and the
  `combat`-side checks are gone. `CantBeBlocked` is a layer-6
  continuous gameplay-action restriction (distinct from a true
  keyword grant); `game.is_cant_be_blocked` walks
  `walk_continuous_modifiers` for the payload.

### Surface cleanup

- 8 `GameObject` / `CardPrinting` fields retired alongside the
  flag deletions.
- ~1,700 LOC of dead code removed across the sweep.
- The Python 3.11 + coverage.py segfault that dogged earlier work
  is fixed by switching to Python 3.13 + `sysmon`; see
  `docs/segfault-fix.md`.

## Remaining work (follow-on architectural pieces)

These are tracked in todos and surfaced by the 2026-05-02 tech-debt
audit, not part of PR D itself:

- **Todo `3c7f2a14`** — SELF-scope statics still on legacy fields.
  The PR-D migration was driven by the call sites with the most
  consumer pressure (anthem family, the two combat-shape gates).
  Other SELF-scope continuous-effect declarations still ride the
  hardcoded gate fields; mirroring the anthem migration's pattern
  on those is mechanical follow-on work.
- **Todo `8a4f1c92`** — split `effects/generic.py` (11,506 lines)
  into a `generic/` package.
- **Todo `5b9d4e72`** — migrate `StaticAbility`'s `requires_*` gate
  fields to the `Condition` slot (the same shape PR D used for
  Mechan / Illvoi).
- **Todo `6f5a8d3e`** — collapse the
  `Return*FromGraveyard*` family.
- **Todo `9e4d8b2f`** — type-line unification + closed-vocabulary
  types.
- **Todo `2b8c4d76`** — physically delete the empty `{}` shells of
  retired bespoke dispatch tables.

## Reference key

- `mtg_bot/effects/modifiers.py` — primitives, dispatcher, walker.
- `mtg_bot/effects/conditions.py` — gating-condition grammar
  (now with `ControlledArtifactEnteredThisTurn`,
  `AtLeastNSpellsCastThisTurn`, etc.).
- `mtg_bot/game.py` — `effective_keywords` /
  `effective_power` / `effective_toughness` /
  `is_cant_be_blocked` — all of which consult
  `walk_continuous_modifiers` after the legacy registry walk.
- `mtg_bot/cards/parser/creature_builder.py:570-668` — the
  five SELF-scope StaticAbility declaration sites that drove the
  migration.
- `mtg_bot/cards/parser/printing_keywords.py:351-463` — the
  literal-line recognizers that feed those call sites; their
  recognizer NAMES still match the printed-surface families
  but the docstrings now describe the ContinuousModifier shape
  the caller builds.
