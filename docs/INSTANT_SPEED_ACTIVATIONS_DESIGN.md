# Instant-speed activated abilities of permanents — design note

Branch `feature/roto-instant-activations` (off `feature/roto-integration`
@ `65a8ce1c`), 2026-10-03. Written before the code change.

## The rule

CR 117.1b: a player may activate an activated ability any time they have
priority. CR 602.5 lets the ability or a rule narrow that:

| Restriction | Source | How the engine models it |
|---|---|---|
| "Activate only as a sorcery." (CR 602.5d) and the keyword abilities whose rules say the same: Equip (702.6a), Reconfigure (702.151a), Saddle (702.171a), Level up (702.87a) | printed rider / keyword rule | `ActivatedAbility.sorcery_speed = True` (the parser sets it for every one of these; audited below) |
| Loyalty abilities (CR 606.3): sorcery timing, one loyalty activation per permanent per turn | rule | `sorcery_speed = True` on every planeswalker ability + the per-walker `loyalty_activation_available` gate. The Wandering Emperor's "you may activate her loyalty abilities any time you could cast an instant" (while she entered this turn) lifts the timing half only |
| "Activate only during your turn." | printed rider | `activate_only_during_your_turn` |
| "Activate only once each turn." (combined with "during your turn" on Vivi Ornitier) | printed rider | `roto_mana.OnceEachTurnCost` cost atom |
| "Activate only once." / Exhaust (702.177) / Boast (702.142: attacked this turn, once each turn) | printed rider / keyword | `activate_only_once`, `exhaust`, `boast` |
| "Activate only if <condition>." (602.5b) | printed rider | `activate_only_if` and the `ActivationCost.requires_*` gates |
| "Activate only as an instant." | printed rider | no narrowing beyond "has priority" (`activate_only_as_instant` only keeps the ability out of mid-payment sacrifice-for-mana) |
| "Activate only during combat" / "during your upkeep" / "before blockers are declared" | — | **No card in any pool (`all`, `cube`, `roto`, the EoE dumps) prints one.** The parser has no recognizer for them, so such a line stays unparsed and the card unclaimed (a decline test pins this); nothing is silently dropped |

Every other non-mana activated ability of a permanent is legal whenever its
controller has priority (subject to its costs and targets as today).

**Mana abilities keep their existing handling** (scope decision): explicit
mana abilities that live in `activated_abilities` are still offered as
`ActivateAbility` only in a sorcery window, and automatic payment keeps using
`produces`. CR 605.3a would allow them at any priority; that stays the
documented cube-lands shortcut #1 in `docs/SEARCH_LIMITATIONS.md`.

Special actions are unchanged: `UnlockRoomHalf` and `ActivateStation` are
sorcery-timing by rule; `TurnFaceUp` keeps its documented sorcery-window
approximation.

## Where the gate was

* **Python `legal._legal_actions_core`** returned early at non-sorcery timing
  (`if not sorcery_timing: ... return`) *before* the battlefield
  activated-ability block, so outside an empty-stack main phase of your own
  turn no battlefield `ActivateAbility` was ever offered. Two narrow
  exceptions sat in front of that return: `_instant_speed_loyalty_activations`
  (The Wandering Emperor) and P1's `roto_restrictions.
  instant_speed_spell_targeting_activations` (abilities whose targets are
  spells, simple costs only — Glen Elendra Guardian).
* **Search capability check** `search/_player_capabilities.
  _has_instant_speed_activatable` returned only P1's special case, so the
  adapter's capability auto-pass (SEARCH_LIMITATIONS #3) treated every other
  activation as unavailable off sorcery timing.
* **Rust `state_ops_legal.rs::legal_decisions`** returned `Ok(actions)` at
  `if !is_sorcery_timing` before PlayLand, sorcery casts and the whole
  `ActivateAbility` emission block. Rust's `sorcery_speed` field was
  data-carrying only (never checked) because every emission sat behind the
  outer gate.

## Priority windows (unchanged)

The rules engine gives priority in every step except untap and cleanup
(`turn.STEPS_WITH_PRIORITY`), on both players' turns, and after every
resolution (`simulate.priority_loop`); `MtgGameStateAdapter` mirrors it.
Instants already use all of these windows, and activations now use the same
ones. The search adapter skips some windows for efficiency — capability
auto-pass (#3), active-player phase prune of own upkeep/draw/beginning of
combat/end with an empty stack (#6), empty-combat skip (#9), opponent's
postcombat main skip (#10), dead-main-1 skip (#11). These are documented
search heuristics, not legality, and apply to activations exactly as to
instants; this change does not touch them. The capability auto-pass is
taught the new rule (below) so it stops hiding activations.

## The change

1. **Python.** The battlefield activated-ability block becomes
   `legal.battlefield_ability_activations(state, player_id, *,
   sorcery_timing, first_only=False)`, called in *both* exits of
   `_legal_actions_core` (at sorcery timing in its old position, so the
   action order there — and every seeded trajectory that only uses sorcery
   windows — is unchanged). A single per-ability timing predicate
   `activation_timing_permits(state, obj, ability, sorcery_timing=...)`
   holds the rule: at sorcery timing everything passes; otherwise mana
   abilities don't, `sorcery_speed` abilities don't (except a walker under
   The Wandering Emperor's permission), everything else does. All existing
   per-ability gates (costs, targets, once/exhaust/boast/only-if/your-turn,
   loyalty once-per-turn) run for every window. `_instant_speed_loyalty_
   activations` and P1's `instant_speed_spell_targeting_activations` (+ its
   `_targets_spells_only` / `_simple_cost` helpers) are deleted — the
   general rule subsumes both, including the stack-targeting abilities with
   non-simple costs P1 excluded.
2. **Search.** `_has_instant_speed_activatable` calls the same enumerator
   with `sorcery_timing=False, first_only=True` — the exact legal answer,
   no second copy of the gates. The capability cache is per decision moment
   (invalidated on every `apply()`), so exactness costs one short-circuiting
   walk of the player's permanents per priority moment.
3. **Rust.** The `ActivateAbility` emission block moves into a helper called
   from the non-sorcery return and from its old position. The helper gates
   `is_mana_ability || sorcery_speed || walker` on sorcery timing. Rust has
   no Wandering Emperor and no `activate_only_*` / exhaust / boast fields;
   no AA the bridge admits today carries one (checked over the EoE pool),
   and `parity.cross_engine._python_aa_to_safe_dict` is made to decline
   such AAs explicitly so a future admit can't silently drop a timing
   rider. Cross-engine `LEGAL_SET_EQ` then holds in every window the
   shadow/parity harnesses drive.
4. **Codec / NN.** No change. `ActivateAbility` encodes as
   `(own battlefield position, ability_index)`, independent of timing, so no
   slot moves and no `action_encoding_version` bump is needed. Existing
   checkpoints load and run unchanged; their policy priors on those slots in
   the newly opened windows were never trained (the slots were always masked
   there), so search visit counts carry those decisions until the next
   training cycle sees them. Cube nets don't exist yet; EoE nets don't
   transfer to the cube anyway.
5. **Cards.** Tinder Wall's "target creature it's blocking" gets a target
   filter and the card is claimed. Behavioural tests activate Maze of Ith,
   Cephalid Illusionist, Nomads en-Kor, Blight Mamba, Sundial of the
   Infinite, Ranger-Captain of Eos, High Noon and Glen Elendra Guardian in
   the windows they exist for, plus a representative set of already-claimed
   cards whose instant-speed abilities were hidden by the old gate.

## Audit of timing riders (precondition for widening)

Widening is only safe if no claimed card carries a timing restriction the
engine ignores (previously harmless, since everything was sorcery-timed).
A scan of every claimed printing in `all` + `roto` (369 cards with activated
abilities, 379 non-mana abilities) found every "Activate only as a
sorcery", Equip, Reconfigure, Saddle, Level up and loyalty ability flagged
`sorcery_speed`, both "Activate only during your turn" cards flagged, and no
other timing phrase in any pool. Granted abilities (The Dominion Bracelet's
quoted ability) go through the same activated grammar.

## Perf

More legal actions at more priority points widen search and defeat
capability auto-pass whenever a player has an activatable ability. Measured
before/after with `scripts/scout_instant_activation_branching.py`
(numbers in `docs/BENCHMARKING_FINDINGS.md` and the branch report). No
legality-changing pruning is added.

## Known risk (pre-existing class)

`RandomAgent` never passes while a non-pass action exists, so a free,
repeatable, non-sorcery ability (Nomads en-Kor's `{0}`, roto only) lets it
hold priority forever. Sorcery-speed `{0}` equips (Lightning Greaves,
Shuko) already loop it across resolutions today. Not addressed here (it is
an agent behaviour, not a rule).
