# Search and engine limitations / known correctness gaps

This document tracks places where our search or engine deliberately
diverges from optimal play or strict CR conformance, with the
rationale, the failure mode, and the conditions under which it would
matter.

These are NOT bugs to fix on a deadline — they're tracked here so
they don't get rediscovered every few months as "wait, that's broken"
and so we have a clear record of WHY each shortcut was taken.

---

## 1. Combat damage assignment is ordered (outdated CR)

**Location**: `src/mtg_bot/combat.py:_resolve_damage_step` (around line 419).

**What we do today**: when an attacker is blocked by multiple blockers,
the engine assigns damage in `attacker.blocked_by` iteration order,
applying lethal-before-next-blocker for all but the last blocker.
The last blocker absorbs all remaining damage (or it goes to the
player if the attacker has trample).

**Why this is wrong under current CR**: modern MTG rules let the
attacking player assign damage across blockers however they want —
no required order, no "must assign lethal before next." The attacker
can split a 5/5's damage as 1+1+3 across three blockers if they
choose.

**Failure mode**: the bot may "trade" creatures suboptimally. A 5/5
attacker into three 2/2 blockers should be able to deal 2+2+1 to kill
two and leave one wounded. Our engine forces 2+3+0 (kill first, dump
rest into second).

**When it matters**: rarely in early-training — neither side is
playing well enough for damage assignment subtlety to matter.
Increasingly important once the model is strong and combat is the
deciding factor in close games.

**Fix scope when prioritized**:
- Replace the in-order assignment with a damage-distribution
  decision per multi-blocker attacker
- Factored search-side decision: per attacker with N blockers,
  expose N-1 "how much to N-th blocker" decisions (the last one is
  forced — assign whatever's left)
- Engine `_resolve_damage_step` honors the assignment instead of
  computing it
- Tests pinning: assigning 1/1/3 across three blockers vs default
  2/3/0; trample interaction; deathtouch (1-damage-counts-as-lethal)
  interaction

**Impact estimate**: ~5-10% strength gain in mid/late training.
Negligible during early training.

---

## 2. Combat blocker assignment is factored (joint-pattern coverage)

**Location**: `src/mtg_bot/search/combat_decisions.py`,
`src/mtg_bot/search/engine_adapter.py` (`expose_combat_decisions=True`).

**What we do today**: declare-blockers is decomposed per-blocker.
Each blocker chooses independently from `[block attacker A, block
attacker B, ..., don't block]`. Search sees a depth-M tree of width
N+1, NOT a single 1296-way decision.

**Why this is sometimes wrong**: per-blocker decisions break the
coupling between blockers. "Block attacker A with blockers B and C
together to safely trade" requires search to discover the joint
pattern through MCTS visits. With a small iteration budget, the
search can prefer locally-good but jointly-bad blocking patterns.

**Failure mode**: example — opp attacks with a 5/5; defender has two
2/3 blockers. Optimal play: chump-block with one (cheaper trade),
take 5 damage to face. Sub-optimal jointly-correct: double-block
with both (use both blockers, kill the 5/5, lose both blockers).
Factored search may pick the joint-bad pattern that splits the
difference (one blocker blocks, other passes — same as chump but
explored sub-optimally because UCB1 picks each independently).

**Mitigation in place**:
- Tree-reuse across choose() calls (commit `5f1a202`) keeps
  block-assignment subtrees warm across decisions
- PUCT prior from the trained policy biases toward typical good
  joint patterns once the model has learned them
- Forced-move shortcut handles trivial cases (only one blocker)

**When it matters**: at very tight per-choose budgets (e.g., samples=1
nodes=50). At our production budget (samples=4 nodes=200 = 800 iters)
combined with PUCT prior, the factored search reaches reasonable
coverage. As model trains, the prior compensates for factoring loss.

**Fix scope if needed**: introduce a "block group" decision type
that lets search bind multiple blockers at once. Big refactor; not
worth it now.

**Impact estimate**: probably <5% strength gain even in late training.
Below the noise floor against the ordered-damage-assignment fix.

---

## 3. Opp priority auto-pass via capability hash

**Location** (planned, in `feature/opp-capability-autopass` branch
as of 2026-05-04): `MtgGameStateAdapter.legal_decisions` short-circuits
to `[PassPriority()]` when the non-active player's capability set is
empty. The capability set is computed once and re-validated by hashing
`(opp.hand, opp.mana_available, opp.untapped_permanents_with_abilities)`
and only recomputing on hash mismatch.

**Why this is sometimes wrong**: the hash inputs don't capture every
state change that could affect the opp's possible actions. Specifically:

| Edge case | Why missed | Bot misbehavior |
|---|---|---|
| Continuous effect from opp grants opp new instant-speed access (Vedalken Orrery, Teferi Mage of Zhalfir grants them flash) | Hash doesn't depend on continuous-effects layer | Bot auto-passes when opp could have cast a (now-flash) creature |
| Cost-reduction effect lands mid-turn (Goblin Electromancer ETBs from active player's spell → opp's instants get cheaper) | Hash uses raw mana_available, not effective costs | Bot auto-passes when opp could afford something whose cost just got reduced |
| Continuous effect grants opp permanent a new activated ability (rare) | Hash doesn't enumerate continuous-effect-granted abilities | Bot auto-passes when opp could activate the granted ability |
| Effect makes opp spells castable from a new zone (Yawgmoth's Will → graveyard cast; very rare in current pool) | We don't model graveyard-cast capability fully here | Bot auto-passes when opp could cast from graveyard |
| Mana-cost change via card-type change (e.g., color-changing effect altering hybrid cost availability) | Hash uses face-value cost, not derived | Bot auto-passes if a now-castable cost wasn't recognized |

**Failure mode**: bot passes priority when opp had a meaningful
action available. Opp gets the play; bot didn't get to consider it.
Note this is conservative-WRONG — the bot's miss is "didn't take a
chance to act" — never "took an illegal action" or "made an
impossible play."

**When it matters**: very rare in the current EoE pool + synthetic
G/R deck. Common enough in formats with lots of cost-reduction or
flash-granting effects (Modern, Legacy, Commander) that this would
need to be tightened up before the bot enters those formats.

**Mitigation**: the hash is conservative — it includes more state
than strictly needed. False negatives (capability claimed empty
when it isn't) are the dangerous case; false positives (hash says
"changed" when capability actually didn't) just trigger an
unnecessary recompute. We err toward the latter.

**Acceptable for**: training (bot sees millions of games; rare
mis-plays don't shift the policy gradient).

**NOT acceptable for**: tournament play, real-money matches, "bot
plays one game live" scenarios where every decision matters.

**Fix scope if/when needed**:
- Include continuous-effect "grants opp instant-speed" predicates in the hash
- Track effective costs (cost-reduction-aware mana check) instead of raw mana
- Specifically scan for `ContinuousEffect` types known to affect opp action availability
- Add a config flag `--no-opp-capability-autopass` for matches where strict play matters

**Impact estimate**: currently +20-35% per-game self-play
throughput. Strength cost in mis-played positions: negligible at
current model strength + EoE-only pool.

---

## Tracked but not in this doc

Things tracked elsewhere that you might also want to know about:

- **PIMC's visit-aggregation bug** (workaround in writer-side filter,
  permanent fix is ISMCTS migration which is mostly done)
- **CoW `_fork_if_shared` historical issues** (fixed by the cleanup-
  step fork added in `feature/cast-not-castable-rootcause`)
- **Engine "hangs" turned out to be slow-tail games** (see
  `docs/hang_triage_2026_05_03.md`)
- **EventPattern.subject_filters originally not hashable** (fixed by
  `feature/event-pattern-hashable`)
- **belief-weighted determinizer needs trained policy to be useful**
  (shelved until model is trained enough — see worklog 2026-05-04)
- **Coverage gate at 95.10%** with main typically running 95.15-95.20%

---

## Adding a new entry

When you take a deliberate shortcut (heuristic, approximation,
incomplete CR conformance), add a section here with:
- Where in the code (file:line)
- What the shortcut is
- Why it's OK (or which scenarios make it not-OK)
- Failure mode
- Fix scope estimate
- Impact estimate (perf gain or strength cost)
