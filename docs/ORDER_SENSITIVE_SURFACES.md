# Order-sensitive surfaces — Python vs Rust audit

Research doc cataloguing every order-sensitive observable in the Python
engine, mapping each to its Rust counterpart, and flagging the ones
most likely to surface as the next CE\<n\> divergence once CE4
(battlefield ETB ordering) closes.

**Why this matters.** CE3 (library pop orientation) was found because
nothing in the smoke ever called `draw_card`. CE4 (battlefield ETB
ordering) was found because the smoke didn't have two players each
with a permanent on the battlefield. The pattern: divergences hide in
order-sensitive surfaces that aren't exercised by the current decision
scripts. This doc enumerates the surfaces so phase-5 probe selectors
can target them deliberately.

**Status legend.** For each surface:

- **CLEAN** — semantics match across engines, no probable divergence.
- **DIVERGENT** — known semantic mismatch, queued for a CE\<n\>.
- **DIVERGENT (closing)** — CE\<n\> is mid-closure in a parallel
  worktree; do not double-fix.
- **UNKNOWN** — could not determine from static reading; needs a
  probe.
- **BLOCKED-ON-GAP** — Rust side hasn't grown the surface yet; the
  Python side's order semantics will be reachable only after that gap
  closes.

Engine pointers below are absolute paths from the worktree root.

---

## 1. `state.battlefield` (centralized list vs per-player Vecs)

**Brief.** Python keeps battlefield as a single global list ordered by
ETB-timestamp across both players. Rust keeps battlefield as two
per-player `Arc<Vec<GameObject>>` zones with no centralized index;
ordering across players is fabricated at snapshot time.

**Python.**
`src/mtg_bot/game.py:2585` — `battlefield: list[GameObject]` on
`GameState`. Tail-append at `src/mtg_bot/actions.py:1124` (`_play_land`),
`src/mtg_bot/actions.py:3115` (`put_into_battlefield` — used by every
non-land permanent path), `src/mtg_bot/effects/bespoke.py:128 / 835 /
959`, `src/mtg_bot/effects/combinators.py:283`,
`src/mtg_bot/effects/generic/exile.py:943`,
`src/mtg_bot/effects/generic/search.py:162`,
`src/mtg_bot/effects/generic/zone_moves.py:305`. Removed by
`turn.move_off_battlefield` at `src/mtg_bot/turn.py:230` and
`src/mtg_bot/effects/generic/bounce.py:259`. Explicit ETB-timestamp
ALSO stamped on the object at `src/mtg_bot/actions.py:3050`
(`obj.etb_timestamp = state.next_timestamp; state.next_timestamp +=
1`) — but only on the `put_into_battlefield` path. **`_play_land`
does NOT stamp `etb_timestamp`** (lands keep the default `0` per
`src/mtg_bot/game.py:638`). Within-list order is the authoritative
ordering signal; the explicit timestamp is consumed only by
layered-effect callers (`effects/modifiers.py:606`) and the
info-set hash (`search/info_set.py:358`).

**Rust (pre-CE4 main).** `rust/src/state.rs:288` —
`pub battlefield: Zone` (= `Arc<Vec<GameObject>>`) per `Player`. No
centralized list, no `etb_timestamp` field on `GameObject`. Snapshot
fabrication at `rust/src/state_ops_snapshot.rs:183-190`: concatenates
p0's battlefield then p1's — so any interleaved-ETB scenario diverges
from Python's by-timestamp order.

**Rust (CE4 worktree, mid-closure).** `feature/ce4-bf-etb-order` adds
`GameObject.etb_timestamp: u32` plus a `GameState.next_etb_timestamp`
counter (`rust/src/state.rs` diff). Every bf-entry call site (move-
from-zone, cast-resolve, play-land, token creation, reanimation,
search-and-bf, manifest) stamps via
`crate::state::reserve_etb_timestamp(state)`. **NOT YET DONE in
CE4:** `battlefield_snapshot` and the fingerprint walk are NOT yet
modified to stable-sort by `etb_timestamp` — the field stamping is in
place but the reader still concatenates p0 then p1. CE4 closure will
plug that final stable-sort in `state_ops_snapshot.rs:battlefield_snapshot`
and the corresponding fingerprint emitter; that's the surface the
parallel agent is about to finish.

**Parity status.** DIVERGENT (closing) — CE4 in flight on
`ce4-bf-etb-order`.

**Probe to keep surfacing here.** After CE4 lands: a multi-turn smoke
that interleaves p0+p1 ETBs across turns (which `multi_turn_selector`
already exists at `src/mtg_bot/parity/cross_engine.py` per the
phase-5 multi-turn merge), then specifically asserts that
`state.battlefield_snapshot` returns the SAME objects across engines
under non-trivial ETB interleavings (one ETB on p0, one on p1, one
on p0 again).

**Hidden land trap.** Even with CE4 stamping everywhere, **Python's
own `_play_land` never bumps `etb_timestamp`** (see actions.py:1084-
1124). All lands stay at timestamp 0, distinguished only by
their position in the centralized list. If CE4's Rust stamping
DOES bump on `play_land`, the per-object timestamps diverge from
Python's even though the rendered order may match.  Phase-5 probe
should compare not just snapshot order but also per-object
`etb_timestamp` values once the field becomes observable in the
snapshot dict.

---

## 2. `state.stack` (LIFO + APNAP within simultaneous triggers)

**Brief.** Spell + ability stack. Top = LAST element of the list.
Within a single dispatch event, triggers go on the stack in
battlefield-iteration × ability-index order, NOT APNAP-sorted
(documented intentional simplification — `RUST_PARITY_PLAN.md:28-30`).

**Python.** `src/mtg_bot/game.py:2586` —
`stack: list[StackItem]`. Push via `state.stack.append(...)` at
`src/mtg_bot/actions.py:1759, 2337, 3263`. Pop at
`src/mtg_bot/actions.py:2655` (`resolve_top_of_stack`). Dispatcher
`dispatch_event` at `src/mtg_bot/actions.py:3346-3399` iterates
`permanents = list(state.battlefield)` (snapshot AT dispatch entry,
so newly-ETB'd permanents during the same event don't observe their
own event) × `enumerate(source.printing.triggered_abilities)` and
pushes each match via `push_triggered_ability`. **Single-controller
queue makes APNAP moot in practice** is correct as long as
`state.battlefield`'s order itself happens to put all the active
player's permanents first — which is timestamp-order, NOT
controller-grouped. So a state where p0 (active) and p1
(non-active) have alternating ETB timestamps WILL emit triggers in
non-APNAP order. Per CR 603.3b the APNAP-controller order matters
for which trigger resolves first — the engine bakes in the WRONG
order if active-player triggers aren't actually first in
`state.battlefield`.

**Rust.** `rust/src/state.rs:625` — `pub stack: Vec<StackItem>`.
Push/pop in `rust/src/state_ops_stack.rs:57, 89`. LIFO matches. Rust
**does not have a `dispatch_event` analog**: triggered abilities are
fired as inline `apply_effect` calls during stack resolution
(`rust/src/state_ops_resolve.rs:4987-4999` — ETB effects iterated
from `printing.etb_effects` and applied directly, not pushed onto
the stack). So Rust currently has NO trigger-on-stack at all for
ETB; the order question is moot because there's no stack ordering
to compare on. **Once Rust grows a `dispatch_event` equivalent**,
matching Python's
"`state.battlefield` order × `enumerate(ability_index)`" iteration
is required for parity, AND mismatched APNAP semantics will surface
the same way.

**Parity status.** Stack mechanics (push/pop/LIFO) CLEAN. Trigger-
emission ordering BLOCKED-ON-GAP (Rust has no trigger emitter yet);
when Rust grows one, expect a high-priority CE entry.

**Probe to keep surfacing here.** Once Rust emits triggers onto the
stack: a smoke with TWO permanents, both with ETB triggers, ETB'd in
interleaved p0/p1 order — then asserts identical stack contents
post-resolve. Pre-emitter: probe state.stack length + stack[-1]
identity after a synthetic forced-push.

---

## 3. Triggered ability ordering (CR 603.3b APNAP)

**Brief.** When multiple triggered abilities trigger from the same
event, each player orders their triggers, then they go on the stack
in APNAP order (active player's first). Python does NOT do this —
plan-doc claim verified.

**Python.** `src/mtg_bot/actions.py:3346-3399` —
`for source in permanents: for ability_index, ability in
enumerate(source.printing.triggered_abilities): push_triggered_ability(...)`.
`permanents` is `list(state.battlefield)`. **No APNAP sort, no
intra-controller ordering choice.** The author comment in
`RUST_PARITY_PLAN.md:28-30` says "single-controller queue makes APNAP
moot in practice" — that's only true when all triggers happen to
come from one controller's permanents. In a real game where both
controllers have ETB-trigger permanents on the field, this is a
deliberate simplification. Should be in `SEARCH_LIMITATIONS.md`.

**Rust.** No trigger emitter; see Stack section above. BLOCKED-ON-GAP.

**Parity status.** Today: vacuously CLEAN (Rust has no triggers to
mis-order). Future: when Rust grows triggers, the question becomes
"does Rust's iteration order match Python's
state.battlefield-iteration order?" — which depends on CE4 closure
holding. If CE4 + a faithful Python-style dispatcher both land, this
surface stays CLEAN-but-wrong-per-CR.

**Probe to keep surfacing here.** Once Rust emits triggers: a probe
that ETBs (1) a p0 permanent with two trigger abilities and (2) a p1
permanent with one trigger ability, in interleaved timestamp order,
then walks the resulting stack and asserts identical contents.

---

## 4. Per-player exile zones

**Brief.** Each player has their own exile list. Order tracked by
tail-append. Order matters for "return from exile" effects with
multi-card riders (Oblivion-Ring-style return-the-exiled-card,
suspend-cast-when-last-counter-removed, Sothera's "recall
cards-exiled-with-this").

**Python.** `src/mtg_bot/game.py:Player.exile` (definition near line
2420, traced via grep). Tail-append in
`src/mtg_bot/turn.py:248` (LTB → exile path) and
`src/mtg_bot/effects/generic/exile.py:*` (every exile effect).
Remove via `p.exile.remove(card)` (search by identity). Cards
exiled-with-source carry `card.exiled_by_source: int` on the
GameObject (`game.py:561-583` doc); the recall function walks
`p.exile` and pulls every match.

**Rust.** `rust/src/state.rs:296` — `pub exile: Zone` per Player.
Tail-append via `Arc::make_mut(&mut player.exile).push(obj)` (used in
`state_ops_zones.rs:184` for ZONE_EXILE destinations and in every
exile-side effect arm in `state_ops_resolve.rs`).
`GameObject.exiled_with_source: Option<u32>`
(`rust/src/state.rs:81`) mirrors Python's `exiled_by_source`.
**Rust's `return_paired_exiles_for(src_id)` is a manual hook**, not
auto-fired by every bf-leaving primitive (per doc on
`exiled_with_source`) — that's a documented Rust simplification.

**Parity status.** Tail-append shape: CLEAN. Auto-fire-on-LTB:
DIVERGENT (Rust simplification, documented but not in a CE entry).
Order-of-recall WITHIN exile when multiple cards have the same source
id: UNKNOWN — the recall semantics in Python iterate
`for c in p.exile if c.exiled_by_source == src_id` (FIFO by exile-
position); Rust's equivalent iteration order depends on whether
`return_paired_exiles_for` (or its eventual auto-fire) preserves
that.

**Probe to keep surfacing here.** ETB an Oblivion-Ring-like
permanent that exiles two creatures across two turns, then LTB the
Oblivion-Ring source; assert both creatures return in the same
order across engines.

---

## 5. Per-player graveyard zones

**Brief.** Each player has their own graveyard list. Tail-append on
death/discard/spell-fizzle. Order matters for "top of graveyard"
effects (reanimation-targets-top, Brainstorm-style return,
graveyard-position scrying effects).

**Python.** `src/mtg_bot/game.py:Player.graveyard`. Tail-append at
`src/mtg_bot/turn.py:245` (LTB → graveyard path) plus every
discard / mill / sacrifice site (`effects/generic/discard.py:108,
effects/generic/draw_mill.py:*`, etc.). **No `graveyard.insert` and
no `graveyard.pop()` use anywhere** (grep-verified — no top-of-grave
position-dependent effects in the current pool). The order matters
ONLY for the policy slot mapping under `positional_v1` action
encoding (per `CLAUDE.md:243-247`), which the slot_fingerprint
workaround already defends against. Under `canonical_v2` action
encoding, graveyard order in the slot map is canonicalized away.

**Rust.** `rust/src/state.rs:289` — `pub graveyard: Zone` per
Player. Tail-append at `state_ops_sba.rs:250` (SBA destroy →
controller's graveyard) and every effect arm. No top-of-grave
read consumer.

**Parity status.** CLEAN today (no effect cares about grave
position) — but quietly observable through the policy slot map,
where any mismatch shows up as a different action-encoding mask.

**Probe to keep surfacing here.** Once two permanents die in the
same SBA pass — assert per-player graveyard order matches across
engines. **Note Rust's SBA collects victims by per-player walk
(`state_ops_sba.rs:138-186`) while Python's SBA walks
`state.battlefield` (centralized).** So when p0 + p1 each have a
lethal-damaged creature in the same pass, Rust may put one in p0's
graveyard and the other in p1's in a different relative order than
Python emits them. Specifically: Rust always processes p0's victims
before p1's (per-player iteration); Python's order depends on the
centralized battlefield's ETB-timestamp order, which can interleave.
Even though each goes to ITS OWN owner's graveyard so order WITHIN a
graveyard is preserved, any side-effect that depends on
"which dies first" (e.g. a death trigger's resulting stack-push
order) will diverge.

---

## 6. Hand order

**Brief.** Per-player hand list, tail-append on draw. Order matters
for: (a) "discard your hand" routes hand→grave in hand-order
(`effects/generic/discard.py:106 — hand.pop(0)`); (b) cleanup-step
hand-size discard pops from the END of hand
(`turn.py:988 — ap.hand.pop()`); (c) the policy slot map under
positional_v1.

**Python.** `src/mtg_bot/game.py:Player.hand`. Tail-append at
`turn.py:115` (`draw_card`) and several effect sites. Pop from front
in `effects/generic/discard.py:106`. Pop from back in `turn.py:988`
(cleanup discard) and `simulate.py:163`.

**Rust.** `rust/src/state.rs:286` — `pub hand: Zone` per Player.
Tail-append in `draw_card` (`state_ops_zones.rs:213`). Pop from back
in `enforce_hand_size_limit` (`state_ops_cleanup.rs:139-141`).
**Matches Python's hand.pop() at cleanup.** No discard-your-hand
effect in Rust yet (Effect coverage is partial; see
`RUST_EFFECT_COVERAGE.md`).

**Parity status.** CLEAN for cleanup-discard. BLOCKED-ON-GAP for
"discard your hand" effects (Rust doesn't model the effect yet).
Once Rust models `DiscardHandThenDrawN` and similar, the popping
order must match `hand.pop(0)` semantics — easy to get wrong if the
Rust dev writes `hand.pop()` reflexively.

**Probe to keep surfacing here.** Once a "discard your hand" effect
is in Rust: assert per-player graveyard contents post-discard match
across engines for a non-trivial hand size.

---

## 7. `mana_pool` ordering

**Brief.** Python tracks mana as `list[ManaCoin]` (each coin has a
color + optional restriction). Rust tracks as a 6-color `u8` struct.
Per RUST_PARITY_PLAN.md I1 this is "order-INSENSITIVE", but only
because the parity field-view normalizer translates Python's list
into a 6-color sorted-tuple signature
(`parity/cross_engine.py:467-498`).

**Python.** `game.py:2426` — `mana_pool: list[ManaCoin]`. Tail-append
on every mana ability resolve (`effects/generic/mana.py:61, 121, 216,
267`). Consumption order depends on `auto_tap_for_cost`'s greedy
matching in `actions.py:919+` — color-first then generic, by walk
order.

**Rust.** `state.rs:272` — `pub struct ManaPool { white, blue, ... }`
inline u8 counters. No order semantics at all.

**Parity status.** CLEAN at the parity-field-view layer because the
view normalizes both. **BUT** any mana-cost paying that depends on
*which specific coin* gets consumed (e.g. a coin with a
spend-restriction modifier) is invisible to the normalized view and
WILL diverge silently if and when restriction-tagged coins exist in
either engine. Today no engine emits restriction-tagged coins in
real games, but `ManaCoin` has the field
(`game.py:2426 / ManaCoin docstring`).

**Probe to keep surfacing here.** None needed today. If a card with
restricted-mana production lands in either engine, write a
restriction-tagged probe at that point.

---

## 8. Counters ordering

**Brief.** Per-object scalar in both engines today
(`GameObject.counters: int` in Python, `pub counters: i32` in Rust at
`state.rs:42`). Order moot.

**Python / Rust.** Both single-scalar. Multi-kind counters (loyalty,
time, -1/-1 distinct from +1/+1) live as separate fields on the Python
GameObject (`time_counters`, `loyalty_counters`,
`enters_with_minus_one_counters_from_hand_cast`); Rust doesn't yet
have them.

**Parity status.** CLEAN. Multi-kind: BLOCKED-ON-GAP (Rust hasn't
grown the distinct counter kinds — when it does, the question is
whether stamp-order matters; with scalar counts per kind, it
shouldn't).

**Probe to keep surfacing here.** None.

---

## 9. Tap order on a single permanent

**Brief.** Tap is a boolean per object (`tapped: bool` in both
engines). No order.

**Parity status.** CLEAN. Skip.

---

## 10. Damage assignment order on a single attacker

**Brief.** Per CR 510.1d, when a creature is blocked by multiple
creatures, the attacking player chooses the damage assignment order
during declare-blockers. Python does NOT plumb this player CHOICE —
it uses the order blockers were appended to `attacker.blocked_by`
(FIFO declare-blockers order). Rust likely does the same with
`self.blockers: Vec<(u32, u32)>`.

**Python.** `combat.py:266` —
`attacker.blocked_by.append(blocker_id)` during declare-blockers.
`combat.py:389, 405` — damage loop iterates blockers via
`[o for o in state.battlefield if o.id in attacker.blocked_by]`
which (a) iterates `state.battlefield` order (ETB-timestamp), then
(b) FILTERS to those whose id is in the `blocked_by` set. Result:
damage-iteration order is `state.battlefield order` filtered to
this attacker's blockers, NOT `blocked_by` append-order. This is
likely a Python bug — "first listed blocker takes damage first" is
the CR-correct semantic, but the iteration walks battlefield order
(ETB stamps), not declare-blockers order. Document as a
`SEARCH_LIMITATIONS.md` candidate if not already.

**Rust.** `state_ops_combat.rs:736` —
`self.blockers.push((attacker_id, blocker_id))`. Damage iteration at
`state_ops_combat.rs:962` walks `self.blockers` in push order. So
Rust IS using declare-blockers order — which is the CR-correct one,
NOT what Python does.

**Parity status.** DIVERGENT — high-priority candidate for the next
CE\<n\>. Python iterates battlefield, Rust iterates blockers vec.
Identical declare-blockers-by-FIFO + identical battlefield orders
will hide it; mismatched orders surface it as a damage-distribution
divergence.

**Probe to keep surfacing here.** A multi-block scenario: ETB three
blockers in a non-ETB-timestamp-matching declare-blockers order
(e.g. declare blockers in REVERSE bf order), then resolve combat
damage; assert per-blocker damage matches across engines.

---

## 11. Phase + step transitions

**Brief.** UNTAP / UPKEEP / DRAW / PRECOMBAT_MAIN / BEGINNING_OF_COMBAT /
DECLARE_ATTACKERS / DECLARE_BLOCKERS / COMBAT_DAMAGE / END_OF_COMBAT /
POSTCOMBAT_MAIN / END / CLEANUP — 12 phase/steps.

**Python.** `src/mtg_bot/turn.py:12-34` — `class Step(Enum)` + `STEP_ORDER` tuple.

**Rust.** `rust/src/state_ops_steps.rs:94-111` —
`PHASE_UNTAP / PHASE_UPKEEP / ... / PHASE_CLEANUP` u8 constants in
the same order. `advance_phase` fires same side-effects: empty mana
pool, untap on entry, summoning-sick clear, draw on entry to DRAW
(gated `turn_number != 1`), cleanup-step on entry to CLEANUP. Order
of cleanup sub-steps (514.1 discard → 514.2 damage clear → 514.3
UEOT clear) preserved in `cleanup_step_for_active_player`.

**Parity status.** CLEAN. Both engines fire the 12 phases in
matching order, and the within-phase side-effects fire in matching
sub-order.

**Probe to keep surfacing here.** None — pin already confirmed by
I20 / I18.

---

## 12. SBA order

**Brief.** 704.5 SBAs are checked in a fixed order, looped until
quiescent.

**Python.** `src/mtg_bot/turn.py:1146-1330` —
`_state_based_actions_pass` walks the 11 SBA categories per CR
order (704.5a player-life ≤0, 704.5c poison ≥10, 704.5i loyalty
=0, 704.5j legend rule, 704.5f / 704.5g destroyer SBAs, +1/+1 vs
-1/-1 cancellation, aura / equipment illegal-target,
saga chapter-count → grave). Loops via `state_based_actions` until
quiescent with cap 50.

**Rust.** `rust/src/state_ops_sba.rs:210-298` — `apply_sbas` walks
player-loss SBAs (704.5a/b folded together), then the destroyer
SBAs (704.5f → 704.5g via `collect_sba_victims`). 11-step coverage
is INCOMPLETE in Rust — only the 4 sub-cases listed have closure.
Looping via `apply_sbas_until_quiescent` with cap 100.

**Parity status.** CLEAN for the subset Rust models. BLOCKED-ON-GAP
for the rest (legend rule, +1/+1 vs -1/-1, aura-illegal-target,
saga, planeswalker-loyalty=0 → grave aren't in Rust yet). When
those land, the question is whether the cross-pass ordering matches
CR.

**Probe to keep surfacing here.** Two simultaneous lethal damages
across both players on the same SBA pass; assert death-order side-
effects (any death-trigger ordering, etc.) match. **Already
flagged in surface #5 above** — same probe surfaces both.

---

## Ranked priority list — most-probable next CE\<n\> divergences

The smoke harness currently exercises a small slice of the engine.
The CE entries so far (CE1-CE4) have all surfaced naturally as the
decision script grew. The next three to five entries are quasi-
predictable given this audit. Listed in descending order of
likelihood-to-surface-with-a-targeted-probe-soon.

### CE5 (predicted) — SBA victim collection order mismatch in two-player kills

When p0 and p1 each have a lethal-damaged creature in the same SBA
pass, Rust collects victims via per-player iteration
(`state_ops_sba.rs:138-186`: `for player in &self.players: for obj
in player.battlefield`), while Python iterates the centralized
`state.battlefield` ordered by ETB-timestamp. Concrete observable:
the death-trigger ordering on the resolved stack, AND the relative
order of two graveyard appends if the dying creatures share a
controller via control-change. After CE4 closes, the
battlefield-snapshot view will agree, but the SBA pass itself walks
each engine's NATIVE order, so the divergence persists.

**Probe selector.** Combat scenario: p0 has a 2/2 attacking, p1 has
two 1/1 blockers. p0's bear ETB'd between p1's two bears. Combat
deals 2 damage to p0's bear and lethal-distributes 1 to each
blocker. Assert the post-SBA per-player graveyard contents AND the
post-resolve `stack_snapshot` (which death triggers fire first)
match across engines.

### CE6 (predicted) — multi-block damage assignment order

Python walks `state.battlefield` filter-by-blocked_by; Rust walks
`self.blockers` in declare-blockers append order. Identical results
require the declare-blockers-append order to match
`state.battlefield` ETB-timestamp order, which is only true when
blockers are declared IN ETB ORDER. Real games rarely declare
blockers in ETB order — a defender's optimal block usually has
nothing to do with which blocker ETB'd first.

**Probe selector.** ETB three blockers across both players' turns
(so their ETB timestamps are non-contiguous), then declare them in
non-ETB order against a single attacker, resolve combat damage,
assert per-blocker `obj.damage` field matches across engines.

### CE7 (predicted) — exile recall order on Oblivion-Ring-style LTB

Both engines tail-append into exile, but the recall iteration order
diverges if Rust's eventual auto-fire of `return_paired_exiles_for`
walks `player.exile` in a different order than Python's
`for c in p.exile if c.exiled_by_source == src_id`. Right now Rust
requires a MANUAL `return_paired_exiles_for` call (documented at
`state.rs:67-73`), so the divergence is gated on Rust growing the
auto-fire hook.

**Probe selector.** ETB an exile-target-permanent-until-source-leaves
source on p0; have it exile a p0 creature, then a p1 creature, then
LTB the source. Assert per-player battlefield post-recall matches
(both creatures back, in identical relative order if they go to
adjacent positions per player).

### CE8 (predicted) — trigger emitter when Rust grows one

Rust currently has no `dispatch_event` — ETB triggers are applied
INLINE during stack resolution at
`state_ops_resolve.rs:4987-4999`. When Rust grows a trigger-on-
stack emitter, the first thing to verify is whether its
iteration order matches Python's `dispatch_event` walk of
`list(state.battlefield) × enumerate(triggered_abilities)`. This is
HIGH-likelihood to land as a CE entry the moment the emitter
exists.

**Probe selector.** Once trigger emitter lands: ETB two permanents
both with ETB triggers on different players, then assert post-ETB
stack contents match.

### CE9 (predicted, lower confidence) — `lands_entered_this_turn` and similar per-turn counters

Python tracks per-player turn-counters (`lands_entered_this_turn`,
`lands_played_this_turn`, `creatures_died_this_turn`,
`ability_resolutions_this_turn`, etc., per `game.py:2380-2747`).
Rust models a subset (`permanent_left_battlefield_this_turn`,
`spell_warped_this_turn` at `state.rs:653-658`). The
ETB-counter increment ordering is fine on its own (incremented
on enter), but cleanup-step reset ordering, and any divergence in
WHICH effects increment them, will surface as state-divergence on
turn boundaries. Lowest of the five because the counter primitives
are scalar (no order at the data level), only divergent if Rust
forgets to bump a counter where Python does.

**Probe selector.** Lands-played counter + landfall trigger: have
p0 play a land that's the second land that turn; assert
`lands_entered_this_turn` matches across engines after the turn-
boundary cleanup.

---

## What this doc is NOT

- Not a parity-bug fix doc — fixes happen in their own CE-numbered
  branches as they surface. This is targeting.
- Not exhaustive — Python's engine has ~3400 LoC in `game.py` alone;
  this audit covers only the explicitly-ordered observable surfaces
  the cross-engine field view emits. Internal-only orderings (e.g.
  log-buffer order, `continuous_effects` registry insertion order for
  layered-effect timestamps) are not in scope today because they
  don't reach the cross-engine snapshot.
- Not a CE\<n\> assignment — the parallel agent owning CE4 may close
  more than just battlefield ordering; specifics of CE5-CE9
  numbering are up to whoever lands the fixes.
