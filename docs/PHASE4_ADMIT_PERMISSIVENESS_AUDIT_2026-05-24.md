# Phase 4 admit-predicate permissiveness audit (2026-05-24)

**Lane**: `feature/phase4-admit-permissiveness-audit-p1` (Worker B
parallel-agent campaign; audit-only, docs-only landing).

## Motivation

The just-prior Singularity Rupture lane
(`feature/singularity-rupture-cycle-1-substrate-p1`, honest-stop
`b9bfafb6`) surfaced a load-bearing finding: the Phase 4 multi-target
admit predicate at `src/mtg_bot/parity/trajectory.py:6177-6189`
includes a permissive `not slot_kinds` branch that admits ANY
`max_t > 1, min_t in (0, 1), empty slot_kinds, not X-cost` printing
— NOT just the graveyard-source shapes the docstring narrates. Scout
for Survivors and Pull Through the Weft already exercise this branch
through their `(0, 3)` / `(0, 2)` `graveyard_creature` shapes;
Singularity Rupture's `(0, 8)` `target_kind=player` shape ALSO fits
through the empty-slot_kinds disjunct (its `target_slot_kinds()`
returns `()` because the bespoke effect doesn't override the default).

So landing JUST a Rust `Effect::SingularityRupture` variant + bridge
+ serializer leaf would AUTO-GROW the admit set 39→40 — directly
producing a PROBED flip via the §2 auto-grow teeth, but violating the
"substrate-only-stays-declined" invariant the prior lane was
operating under.

The campaign question this audit answers: **how many OTHER
BLOCKED-tier cards sit in the same place** — documented as "needs
multi-cycle subsystem work" but actually one Effect-variant landing
away from auto-growing the admit set?

## Method (verify-first, mechanical)

For each card in the live single-gated `effect_uncovered` set
(`scripts/scout_r58_subsystem_attribution.py` re-run on this HEAD —
the brief's 8-card candidate list is **stale** by 2026-05-22/23
flips; the live single-gated count is now 3):

1. Read the parser-emitted `spell_effect` Python class.
2. Identify `(min_t, max_t)`, `slot_kinds`, X-cost flag, `targets`
   attr, `warp_cost`, `kicker_cost`, `room_halves`.
3. Walk `_printing_is_bridge_simple_spell` (`trajectory.py:5897-6241`)
   to determine which admit-phase predicate matches the shape.
4. Cross-check `_spell_effect_is_covered_and_bridged` + the
   round-trip serializer `_python_spell_effect_to_dict` to determine
   whether the missing-Effect-variant gate is the ONLY remaining
   gate, or whether additional substrate (multi-slot binder, per-mode
   targeted-leaf allowlist, modal cast-time binder, X-value channel,
   etc.) is also needed.

## Stale-candidate accounting (brief's 8-card list vs. live HEAD)

The brief asked about 8 candidates from
`docs/SUBSYSTEM_BLOCKED_LEVERAGE_INVENTORY.md` §3. Verify-first
attribution on this HEAD (`62bb1d94`) re-ran via
`scout_r58_subsystem_attribution.py`:

| Brief candidate | Tier today | Note |
|---|---|---|
| Mutinous Massacre | PROBED | Flipped via control-change-UEOT C1-4 (`feature/control-change-ueot-cycle-4-p1`, 2026-05-22). Live admit predicate returns True at this HEAD; pinned in `_PHASE1_ADMITTED_AT_THIS_HEAD`. |
| Systems Override | PROBED | Flipped via control-change-UEOT C5 (2026-05-22). Live admit predicate returns True. |
| Vengeful Possession | PROBED | Flipped via the Threaten-core decomposition (2026-05-22). Live admit predicate returns True. |
| Zero Point Ballad | PROBED | Flipped via X-value subsystem (2026-05-22). Live admit predicate returns True. |
| Devastating Onslaught | PROBED | Flipped via the X-cost + token-copy Cycle 1 lane (2026-05-22). Live admit predicate returns True. |
| Terminal Velocity | PROBED | Flipped via the field-free unit Effect lane (2026-05-22). Live admit predicate returns True. |
| Coordinated Clobbering | BLOCKED single-gated EU | Stays declined — see §1 below. |
| Archenemy's Charm | BLOCKED single-gated EU | Stays declined — see §3 below. |

**Net stale entries: 6 of 8.** The brief's list pre-dated the
2026-05-22/23 closure wave. Only Coordinated Clobbering, Singularity
Rupture, and Archenemy's Charm remain in the single-gated
`effect_uncovered` bucket today.

## Per-card audit verdicts (the 3 live candidates)

Columns: live `spell_effect` Python class, target shape
`(min_t, max_t, or_both?, slot_kinds, X)`, admit-predicate verdict,
remaining-substrate scope estimate.

### 1. Coordinated Clobbering — STAYS-DECLINED-OTHER-GATE

| | |
|---|---|
| Live `spell_effect` | `CoordinatedClobberingEffect` (`effects/bespoke.py:2358`) |
| Shape | `(2, 3)`, `slot_kinds=("creature", "my_creature", "my_creature")`, no X, no warp/kicker |
| Phase match | NONE. Phase 1 fails (max_t≠1). Phase 2 fails (max_t=3, not 2; slot_kinds mismatch). Phase 3 fails (not (0,0)). Phase 4 fails (`len(slot_kinds)=3 == max_t=3` BUT `len(set(slot_kinds))=2`, AND `slot_kinds[0]="creature"` not in `("graveyard_creature",)`). Phase 5 fails (not (0,1)). |
| Verdict | **stays-declined-other-gate.** Even with a hypothetical `Effect::CoordinatedClobberingEffect` Rust variant + bridge + serializer leaf landed, the target-grammar gate positively rejects this shape. Auto-grow NOT possible. |
| Remaining substrate | New Phase-6 admit arm for the heterogeneous `(min_t, max_t)` mixed-kind 3-slot grammar — opponent-creature mandatory slot + 1-2 friendly-untapped-creature slots — plus the corresponding cross-engine 3-slot binding substrate (StackItem must carry 3 target ids; cast-time picker must respect `min_t < max_t` with the optional-tail slot). The existing 2-slot Phase 2 grammar (Diplomatic Relations) is the nearest precedent but does NOT generalize to the optional-tail shape. **Estimated 2-3 cycles.** |

### 2. Singularity Rupture — AUTO-GROW-READY (the exemplar; already documented by Worker B 2026-05-24)

| | |
|---|---|
| Live `spell_effect` | `SingularityRuptureEffect` (`effects/bespoke.py:1599`) |
| Shape | `(0, 8)`, `slot_kinds=()` (default — bespoke doesn't override), no X, no warp/kicker, no `printing.targets` attr |
| Phase match | **Phase 4 — the permissive `not slot_kinds` branch.** `max_t=8 > 1`, `min_t=0 in (0, 1)`, `not slot_kinds`, `not _printing_is_x_cost`. The predicate at `trajectory.py:6177-6189` accepts this shape today. |
| Verdict | **auto-grow.** The only remaining gate is the covered+bridged tooth (`SingularityRuptureEffect` is NOT covered) + the round-trip-or-bail tooth (no serializer leaf). Landing a `Effect::SingularityRupture` Rust variant + bridge arm + reverse-serializer leaf flips Singularity Rupture ADMITTED 39→40 via the §2 auto-grow teeth. |
| Remaining substrate | (a) Rust `Effect::SingularityRupture` variant + parse arm + to_pydict arm + resolve arm. (b) Cross-engine bridge dict→Python arm. (c) Reverse-serializer `_leaf` arm in `trajectory.py`. **CAVEAT — multi-target player binding.** The Python resolve at `bespoke.py:1630-1667` consumes `targets: tuple[Target, ...]` (a list of `("player", id)` pairs bound at cast time by `_PickFirstLegalTargetAgent`). Rust's `StackItem` has NO multi-player-id field today (`chosen_mode_idxs` is the only multi-pick precedent, scoped to mode indices, not player ids). The minimal byte-equal closure requires either (a) deterministic-all resolve-time self-scan over `state.players` (mirrors Scout for Survivors / Pull Through the Weft's resolve-time self-scan precedent — both engines mill every non-lost player including controller, byte-equal under the `_PickFirstLegalTargetAgent` deterministic-all subset-pick), OR (b) a new `StackItem.target_player_ids: Vec<u8>` field + cast-time multi-pick binder. **Option (a) is the clean path** — it requires NO new StackItem field, just a resolve arm. Worker B's prior 3-cycle estimate (`SEARCH_LIMITATIONS.md` §3 "Multi-target player binding substrate") explicitly argued for option (b); on re-examination option (a) is the structural sibling of the Phase-4 graveyard self-scan that's already shipped. **Estimated 1 cycle** under option (a). |
| Action | Documented by Worker B's honest-stop `b9bfafb6` (`SEARCH_LIMITATIONS.md` §3 entries). NOT shipped in this audit lane — the brief explicitly leaves the Singularity Rupture flip as a follow-up dispatch (the audit's question is whether OTHER cards share this auto-grow shape; the answer is: no new ones). |

### 3. Archenemy's Charm — STAYS-DECLINED-OTHER-GATE (multi-gate cascade)

| | |
|---|---|
| Live `spell_effect` | `ModalChooseOne(modes=[..., ..., ...])` — 3-mode envelope (`effects/combinators.py`) |
| Shape | `(1, 2)`, `slot_kinds=()`, no X, no warp/kicker (default empty from `ModalChooseOne`) |
| Phase match | **Phase 4 — the permissive `not slot_kinds` branch.** `max_t=2 > 1`, `min_t=1 in (0, 1)`, `not slot_kinds`, `not _printing_is_x_cost`. The predicate accepts this shape today. |
| Per-card emit | Walked via `card_effect_classes`: `{ModalChooseOne, ExileTargetCreature, ReturnUpToNCreaturesFromYourGraveyardToHand, PutPlusOneCountersAndGrantKeywordsUEOTOnTargetCreatureYouControl}`. Three of the four are covered; ONLY `PutPlusOneCountersAndGrantKeywordsUEOTOnTargetCreatureYouControl` (mode 3) is uncovered. |
| Verdict | **stays-declined-other-gate.** Two gates beyond the missing Effect class block auto-grow: (a) the per-mode targeted-leaf binder allowlist (`is_recognized_targeted_mode_leaf` at `rust/src/state_ops_cast.rs:2368`) is hardcoded to 5 variants — `DestroyTargetArtifact`, `PumpTargetArtifactOrCreatureUntilEOT`, `DealDamageToTargetTappedCreature`, `PutChargeCountersOnTargetSpacecraftOrPlanetYouControl`, `ReturnTargetArtifactCardFromYourGraveyardToHand`. None of Archenemy's Charm's modes (`ExileTargetCreature` for mode 1, `ReturnUpToNCreaturesFromYourGraveyardToHand` for mode 0/2, and the missing `PutPlusOneCounters...` for mode 3) is on the list. (b) The corresponding per-mode resolve binder logic in the same file needs new match arms. Landing JUST the missing Effect variant without the binder allowlist widen would round-trip OK but the live cast pipeline would fail to bind targets correctly. |
| Remaining substrate | Mode-3 `Effect::PutPlusOneCountersAndGrantKeywordsUEOTOnTargetCreatureYouControl` variant + bridge + serializer + parser arm. PLUS the per-mode binder allowlist + match arms for at least Archenemy's Charm modes 0/1/2. PLUS the `legal_targets`-aware multi-target return arm for `ReturnUpToN*` modes (the existing graveyard-creature multi-target self-scan is the structural sibling). **Estimated 3-4 cycles** per prior `SEARCH_LIMITATIONS.md` characterization (next-tractable-substrate hexad §2.6). |

## Net audit finding

**Auto-grow-ready cards beyond the already-documented Singularity
Rupture exemplar: 0.**

The Phase 4 permissive-disjunct ALSO captures Archenemy's Charm
ModalChooseOne (1, 2) empty-slot_kinds shape — that's a second
auto-grow shape consumer at the predicate level — BUT Archenemy's
Charm carries an additional gate cascade (per-mode binder allowlist
+ missing mode-3 Effect variant + multi-target return arm) that
keeps it declined past the predicate. The "one substrate landing
away" framing doesn't apply.

Coordinated Clobbering trips the target-grammar gate before the
covered+bridged gate fires; even a hypothetical Effect variant
wouldn't change its admit status.

**Singularity Rupture remains the only known card whose substrate
landing would flip it ADMITTED via the Phase 4 permissive disjunct
in one cycle.** That finding was already surfaced + documented by
Worker B's prior honest-stop (`b9bfafb6`) and the
`SEARCH_LIMITATIONS.md` §3 "Substrate-p1 verify-first correction
(2026-05-24)" entries. This audit confirms no OTHER cards share that
property today.

## Substrate-coverage observation (the secondary finding)

The flip wave 2026-05-21..23 closed 6 of the brief's 8 candidates
(Mutinous Massacre, Systems Override, Vengeful Possession, Zero
Point Ballad, Devastating Onslaught, Terminal Velocity) in a tight
3-day window via independent per-card slices. The
`SUBSYSTEM_BLOCKED_LEVERAGE_INVENTORY.md` §3 candidate enumeration
is stale; the next inventory refresh should regenerate the
single-gated `effect_uncovered` list against the
`scout_r58_subsystem_attribution` live output (3 cards today, not
12).

## Follow-up dispatch recommendations

1. **Singularity Rupture under option (a) — resolve-time self-scan**
   (estimated 1 cycle, NOT 3). Worker B's prior 3-cycle estimate
   assumed a `StackItem.target_player_ids: Vec<u8>` cast-time
   binding substrate. A re-examination against the Scout for
   Survivors / Pull Through the Weft self-scan precedent
   (graveyard-creature multi-target, no cast-time per-target
   binding, deterministic-all-via-self-scan resolve arm) suggests
   the player-target case is structurally identical and would close
   in one cycle. Recommended next dispatch.
2. **Coordinated Clobbering Phase 6 admit arm** (2-3 cycles). New
   heterogeneous 3-slot grammar predicate + cross-engine 3-slot
   binder. Higher cost than Singularity Rupture; sequence after.
3. **Archenemy's Charm full ModalChooseOne envelope** (3-4 cycles).
   The mode-3 Effect variant + per-mode binder allowlist widen +
   multi-target return arm. Per the existing inventory note, the
   amortized cost across modes is favorable BUT not single-cycle.
4. **Inventory refresh.**
   `SUBSYSTEM_BLOCKED_LEVERAGE_INVENTORY.md` §3's candidate list +
   reconciliation totals + per-subsystem `1gate`/`multi` columns
   should be re-derived against the current
   `scout_r58_subsystem_attribution` output (single-gated
   `effect_uncovered` is 3, not 12). Low-cost docs-only refresh.

## Cross-references

* `docs/SEARCH_LIMITATIONS.md` §3 "Substrate-p1 verify-first
  correction (2026-05-24)" — Worker B's exhaustive analysis of the
  Phase 4 permissive disjunct that motivated this audit lane.
* `docs/SUBSYSTEM_BLOCKED_LEVERAGE_INVENTORY.md` §3 (3) "Effect-
  uncovered diffuse tail — per-card lane" — the source candidate
  list, now stale.
* `docs/POOL_PARITY.md` — the PROBED tier listing that confirms 6
  of the brief's 8 candidates are already flipped.
* `src/mtg_bot/parity/trajectory.py:6177-6189` — the Phase 4
  permissive `not slot_kinds` disjunct (the load-bearing predicate
  arm).
* `tests/test_probe_spell_card_bridge_admitted.py:286-307` —
  `_PHASE1_ADMITTED_AT_THIS_HEAD` (39 cards) — the live admit-set
  pin this audit cross-validated against.

## Lane decision

**Docs-only landing.** No engine changes; no admit-set pin bump; no
new probe tests. Merge to main on green per the brief's "audit doc
would itself be valuable as a docs-only landing" path. Follow-up
dispatches for Singularity Rupture (option a, 1 cycle) and the
inventory refresh are recommended but out of scope for this lane.
