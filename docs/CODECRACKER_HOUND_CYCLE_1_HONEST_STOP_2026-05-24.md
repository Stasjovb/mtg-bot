# Codecracker Hound Cycle 1 substrate — verify-first honest-stop (2026-05-24)

**Lane:** `feature/codecracker-hound-cycle-1-substrate-honest-stop-p1`
(Worker A in the 2026-05-24 post-scout dispatch).

**Trigger.** Today's multi-gated-tail tractability scout
(`fdc3b8d6`, ships `docs/MULTI_GATED_TAIL_TRACTABILITY_SCOUT_2026-05-24.md`)
ranked Codecracker Hound as the #1 multi-cycle closure candidate
(22,144 17lands decks, est. ~3 cycles). The scout's C1 substrate spec
called for a new `Effect::LookAtTopTwoSplitHandGraveyard` Rust variant
plus an "agent-driven 2-card destinations PendingDecision" — described
as a novel 4-state choice space ("card1 → hand or graveyard? card2 →
hand or graveyard?") with no existing sibling-amortization channel.

Per the dispatch's §9 honest-stop protocol, the load-bearing prereq is
a verify-first against the LIVE tree (mirrors today's Singularity
Rupture / Archenemy's Charm verify-first lessons: labels lie, scopes
get miscalled). The verify-first finds the scout's C1 spec **materially
diverges from the live `.resolve()` body and from the existing sibling
Rust substrate** on two load-bearing axes; ship a docs-only
honest-stop instead of forcing a C1 commit on a misread spec.

## TL;DR

The scout's "novel agent-driven 2-card destinations PendingDecision
(4-state choice space)" is **wrong on two load-bearing axes**:

1. **Choice arity is 2-state, not 4-state.** The live Python class
   `LookAtTopTwoSplitHandGraveyard.resolve` at
   `src/mtg_bot/effects/generic/library_lookat.py:159-222` asks the
   agent **one** binary question (`choose_surveil` on `examined[0]`
   only); the second card is automatically routed to whichever zone
   the first was not. The decision channel is "which of the two
   examined cards goes to hand" — semantically a single id-pick from
   a 2-element set, NOT a per-card destination assignment with a
   4-state cross-product.

2. **Sibling Rust substrate already exists.** The scout claims the
   2-card destinations PendingDecision is novel and that the
   amortization is uncertain ("Cycles 3 if the PendingDecision shape
   is novel, 2 if it amortizes against an existing decision
   channel"). The live Rust tree at
   `rust/src/state.rs:1816-1820` already ships
   `PendingDecision::PickCardFromExaminedChoice { source_obj_id,
   controller, cards: Vec<GameObject> }` plus
   `submit_pick_card_decision(chosen_id)` (rust/src/cards.rs +
   state_ops_resolve.rs:6366-6394) for the
   `LookTopNPutOneInHandRestToGraveyard` family (Commune with Evil
   n=4; **Codecracker Hound at n=2 was explicitly called out as a
   real consumer** of this bridge arm — see
   `src/mtg_bot/parity/cross_engine.py:4901-4978`). At n=2,
   `PickCardFromExaminedChoice` IS the choice channel Codecracker
   Hound's resolution semantically calls for — pick 1 of 2 examined
   ids to hand, the other to graveyard. No novel decision substrate
   is required; the existing channel suffices modulo a small
   semantic gap on the `reveal_to_all` rider (see §3 below).

The verify-first scope-call: Codecracker Hound's `effect_uncovered`
gate is **NOT closed by adding a parallel
`Effect::LookAtTopTwoSplitHandGraveyard` variant** with a fresh
PendingDecision. The cleaner closure shape is to **migrate
`LookAtTopTwoSplitHandGraveyard` to a deprecated alias of
`LookTopNPutOneInHandRestToGraveyard(n=2)`** at the Python primitive
level (parser-side recognizer redirect; engine-class merge), then
exercise the existing Rust + bridge + PendingDecision channel
end-to-end. That migration is parser/engine surgery, not a fresh Rust
variant — a different cycle shape than the scout described, and
small enough that a sibling C1+C2 cycle pair may not even be the
right factoring.

## What the live tree actually shows

### Python primitive (`src/mtg_bot/effects/generic/library_lookat.py:159-222`)

```python
@dataclass(frozen=True)
class LookAtTopTwoSplitHandGraveyard(Effect):
    """Look at the top two cards of your library; put one into your
    hand, the other into your graveyard.

    Matches Codecracker Hound's ETB. The agent's choice via
    choose_surveil decides which pile each card goes to (surveil=True
    means graveyard, False means hand — mirrors the surveil semantics).
    """

    def resolve(self, state, controller_id, targets=()):
        p = state.player_by_id(controller_id)
        if not p.library:
            return
        examined = p.library[:2]
        if len(examined) == 1:
            # one-card fallback: top card → hand
            ...
            return
        # Two cards; pick the one to send to hand.
        if p.agent is None:
            hand_card = examined[0]; gy_card = examined[1]
        else:
            hand_card = examined[0]
            if p.agent.choose_surveil(state, p.id, hand_card.id):
                # Agent says "mill this one" → swap
                hand_card = examined[1]; gy_card = examined[0]
            else:
                gy_card = examined[1]
        # move hand_card to hand, gy_card to graveyard
```

Key observables (matters for the scope-call):

1. **The agent decision is a single binary `choose_surveil` on the
   top card.** The bottom card's destination is fully determined by
   the top card's choice. There is no per-card destination assignment.
2. **The decision is synchronous (no `PendingDecision` push).** The
   Python `.resolve()` consumes the agent decision inline — there is
   no Rust-style yield-and-resume shape on the Python side. The Rust
   substrate would naturally push a `PendingDecision` to match the
   yield-and-resume convention; the existing
   `PickCardFromExaminedChoice` ALREADY does this.
3. **`reveal_to_all` is NOT called on the hand card.** Compare with
   `LookTopNPutOneInHandRestToGraveyard.resolve` at
   `src/mtg_bot/effects/generic/library_lookat.py:245-291` which
   DOES call `reveal_to_all(state, hand_card)`. This is the one
   observable difference between the two primitives.

### Parser (`src/mtg_bot/cards/parser/effects.py:1315-1327, 5419-5425`)

```python
_LOOK_TOP_TWO_SPLIT_HAND_GRAVEYARD = re.compile(
    r"^look at the top two cards of your library\. "
    r"Put one into your hand and the other into your graveyard$"
)
# ...
if _LOOK_TOP_TWO_SPLIT_HAND_GRAVEYARD.match(phrase) is not None:
    return LookAtTopTwoSplitHandGraveyard()
```

Per the parser CLAUDE.md "two literals whose strings differ only in a
parameter → merge into one regex" rule, this two-sentence literal is
already a candidate for migration into the parameterized
`_LOOK_TOP_N_PUT_ONE_IN_HAND_REST_TO_GRAVEYARD_GAIN_M_LIFE` family.
Codecracker Hound's printed text "put one into your hand and the
other into your graveyard" at n=2 is the canonical n=2 special case
of "put one of them into your hand and the rest into your
graveyard" — the same primitive with the cosmetic "the other"
sentence wording for n=2. (Recognizing this collapse means the parser
already has 90% of the closure shape; the engine class merge is the
gating substrate.)

### Rust sibling substrate (already on main)

* **Variant.** `Effect::LookTopNPutOneInHandRestToGraveyard { n: i32 }`
  (`rust/src/cards.rs:3744-3761` parse + `to_pydict` + resolve at
  `state_ops_resolve.rs:6366-6394`).
* **PendingDecision.** `PendingDecision::PickCardFromExaminedChoice {
  source_obj_id, controller, cards: Vec<GameObject> }` at
  `rust/src/state.rs:1816-1820` plus `submit_pick_card_decision`
  dispatcher.
* **Bridge arm.** `cross_engine.py:4901-4978` translates dict-shape
  `{"kind": "look_top_n_put_one_in_hand_rest_to_graveyard", "n": 2}`
  to the Python primitive. **Codecracker Hound at n=2 is EXPLICITLY
  named as a real consumer of this bridge arm** in the in-tree
  comment.

### Codecracker Hound's admit-gate state (probed live)

```
NAME: Codecracker Hound
IS BRIDGE-ADMITTED: False
```

Codecracker Hound is positively declined by
`_printing_is_bridge_simple_spell` today. The decline is driven by
the `warp_cost + nonsafe_triggered_ability` gates per the scout's
attribution (the `effect_uncovered` gate is effectively already
addressable via the n=2 reuse — see §3 below). The substrate-only
invariant the dispatch asked for (Codecracker Hound STAYS DECLINED
post-Cycle-1) is the CURRENT state — no flip risk during the
honest-stop.

## §3 — Why "ship a parallel `Effect::LookAtTopTwoSplitHand
Graveyard` variant + fresh 2-card PendingDecision" is the WRONG C1
shape

If the dispatch's C1 spec were taken at face value, the worker would:

1. Add `Effect::LookAtTopTwoSplitHandGraveyard` field-free unit
   variant + parse + `to_pydict` arm.
2. Add a fresh `PendingDecision::TwoCardDestinationsChoice` (or
   similar) with a 4-element submit space.
3. Resolve arm pushes the new PendingDecision; submit dispatcher
   routes both cards to their per-card destinations.

This would ship a NEW PendingDecision shape that is
**observationally equivalent** to the existing
`PickCardFromExaminedChoice` at the n=2 special case — the two
primitives differ only in:

* `LookAtTopTwoSplitHand` does NOT call `reveal_to_all` on the
  chosen card; `LookTopN...RestToGraveyard` DOES.
* The Python class names differ; the Rust variant names would
  differ; the decision-channel name would differ.

Shipping the parallel substrate would:

1. **Duplicate the choice channel.** Two `PendingDecision` variants
   that wrap the same "pick 1 of 2 examined card ids" semantics, one
   carrying a `Vec<GameObject>` payload and one a 4-element
   destinations payload that compresses to the same 2-of-2 choice.
2. **Land a 4-state submit space when only 2 are reachable.** The
   "both to hand" / "both to graveyard" cells of the per-card
   destinations cross-product are unreachable from the printed
   text ("put one into your hand and the other into your
   graveyard" — the cardinalities are fixed at 1+1, not 0+2/2+0).
3. **Block parser collapse.** Keeping
   `LookAtTopTwoSplitHandGraveyard` as a separate engine class
   blocks the parser CLAUDE.md-mandated literal-to-parameterized
   collapse against
   `_LOOK_TOP_N_PUT_ONE_IN_HAND_REST_TO_GRAVEYARD_GAIN_M_LIFE`.

## §4 — What the right closure shape actually looks like

The cleaner closure for Codecracker Hound's `effect_uncovered` gate
is a **migration** at the Python primitive level, NOT a fresh Rust
variant:

* **C1 (parser/engine surgery, ~1 cycle):** Migrate the two-sentence
  surface to the existing parameterized
  `LookTopNPutOneInHandRestToGraveyard(n=2)` primitive. Delete the
  `_LOOK_TOP_TWO_SPLIT_HAND_GRAVEYARD` literal; widen the
  parameterized recognizer to also match the n=2 "the other into
  your graveyard" cosmetic sentence form OR fold the engine class
  `LookAtTopTwoSplitHandGraveyard` into an alias of
  `LookTopNPutOneInHandRestToGraveyard(n=2)` (preserving the
  `reveal_to_all` distinction by passing a `reveal_chosen: bool =
  True` kwarg, defaulting True for Commune with Evil and False for
  Codecracker Hound). Update affected tests; the per-card real-EoE
  probe shape inherits directly from the Commune-with-Evil
  precedent.
* **C2 (admit gate widen + admit-set pin bump, ~1 cycle):** Widen
  `_python_ta_to_safe_dict` to admit the 9th ENTERS+IsSelf leaf
  effect (now serializable end-to-end via the n=2 reuse). Bump the
  admit-set pin from 43 → 44.
* **C3 (admit-set pin verify + per-card real-EoE probe + warp-cast
  lifecycle, ~1 cycle):** Real-EoE Codecracker Hound cross-engine
  probe with warp-cast lifecycle + normal-cast lifecycle.

This is materially the same 3-cycle total cost the scout estimated,
but **C1 is parser/engine surgery** instead of a fresh Rust variant
+ PendingDecision. Sibling-amortization is materially better:
existing Rust substrate + bridge + PendingDecision are reused
verbatim; the work is at the Python primitive merge layer.

**Alternative if the `reveal_to_all` distinction is load-bearing:**
keep `LookAtTopTwoSplitHandGraveyard` as a separate Python class,
but route its Rust mirror through the EXISTING
`PickCardFromExaminedChoice` channel (no new PendingDecision
variant). A new Rust `Effect::LookAtTopTwoSplitHandGraveyard` UNIT
variant whose resolve arm pushes
`PickCardFromExaminedChoice` with `cards=examined[:2]` and whose
submit dispatcher branches on the variant tag at decision-drain time
to skip the reveal_to_all and route popped order to graveyard. Still
~1 cycle, still no new PendingDecision shape.

**Either path beats the spec the scout described.** The spec's
"agent-driven 2-card destinations PendingDecision (4-state choice
space)" is novel substrate that the printed text doesn't actually
need.

## §5 — Why ship this as docs-only honest-stop today

Per the dispatch's §9 honest-stop protocol (verbatim):

> if the verify-first finds Codecracker Hound's `.resolve()` body
> is materially different from the scout's spec (e.g. agent-driven
> destinations turn out to actually be deterministic-first under
> the harness convention, OR the 2-card grouping needs heavy
> stack/library substrate not yet shipped), STOP, push docs-only
> honest-stop, do NOT merge.

The verify-first finds the live `.resolve()` body uses a single
binary `choose_surveil` decision (2-state, not 4-state) and that the
sibling Rust substrate (`PickCardFromExaminedChoice`) already exists
and explicitly lists Codecracker Hound at n=2 as a real consumer.
Both axes of the scout's spec are materially miscalled. Forcing a
C1 commit on the misread spec would ship a duplicate PendingDecision
variant and block the parser CLAUDE.md-mandated collapse.

This document is the closure marker per the same shape as today's
prior honest-stops (`d9d21881` Singularity Rupture cycle-1-p2;
`2199f172` Singularity Rupture cycle-1-p1; `7ad85ea9` Archenemy's
Charm cycle-1-p2; `8f8bc77b` Archenemy's Charm cycle-1-p4).

## §6 — Refined deliverable shape for the next dispatch

If the next Codecracker Hound dispatch wants to ship the closure as
3 cycles total, the recommended shape:

* **Codecracker Hound C1 (parser/engine merge + Rust mirror via
  existing PendingDecision, ~1 cycle).**
  Decide between (a) primitive merge (fold
  `LookAtTopTwoSplitHandGraveyard` → alias of
  `LookTopNPutOneInHandRestToGraveyard(n=2, reveal_chosen=False)`)
  or (b) parallel variant routed through existing
  `PickCardFromExaminedChoice` PendingDecision. (a) is the
  parser-CLAUDE-faithful path; (b) preserves observability symmetry
  with the `reveal_to_all` rider. Either ships in ~1 cycle.
* **Codecracker Hound C2 (admit-gate widen + admit-set pin bump,
  ~1 cycle).** Widen `_python_ta_to_safe_dict` to admit the 9th
  ENTERS+IsSelf leaf effect; bump admit-set pin 43 → 44 (or 45 if
  Worker B's parallel sweep also bumps the pin).
* **Codecracker Hound C3 (per-card real-EoE probe + warp-cast
  lifecycle + warp+nonsafe_triggered admit-gate validation,
  ~1 cycle).** Real-EoE probe pinning byte-equal cross-engine
  resolution under both warp-cast and normal-cast lifecycles. The
  warp-cast lifecycle is the load-bearing piece — it composes with
  the warp-cost substrate (Phase 1+1.5+2+3 shipped, paid sibling).

**Recommendation:** before the C1 dispatch ships, the next worker
should pick between path (a) and path (b) — either is sound, but
they imply different test surfaces. Path (a) requires updating the
~6 tests that reference `LookAtTopTwoSplitHandGraveyard`; path (b)
keeps those tests intact but adds a new Rust UNIT variant + bridge
arm. Path (a) is the more parser-CLAUDE-faithful and slightly
cheaper.

**Worker discount:** the warp_cost substrate (Phase 1+1.5+2+3 ships
the full warp-cast + warp-exile-resolve + cast-from-exile-on-later-
turn lifecycle), the `PickCardFromExaminedChoice` PendingDecision,
the `look_top_n_put_one_in_hand_rest_to_graveyard` bridge arm, and
the per-card real-EoE probe shape (`tests/test_possibility_
technician_parity.py`) all amortize.

## Cross-references

* **Live class:** `src/mtg_bot/effects/generic/library_lookat.py:159-222`
  (Python `LookAtTopTwoSplitHandGraveyard`).
* **Sibling class:** `src/mtg_bot/effects/generic/library_lookat.py:226-291`
  (Python `LookTopNPutOneInHandRestToGraveyard`).
* **Parser:** `src/mtg_bot/cards/parser/effects.py:1315-1327, 5419-5425`.
* **Rust sibling Effect + PendingDecision:** `rust/src/state.rs:1816-1820`
  + `state_ops_resolve.rs:6366-6394` + bridge arm at
  `src/mtg_bot/parity/cross_engine.py:4901-4978`.
* **Scout (parent):** `docs/MULTI_GATED_TAIL_TRACTABILITY_SCOUT_2026-05-24.md`
  §1 (Codecracker Hound). Scout commit `fdc3b8d6`.
* **Honest-stop shape precedents:** `d9d21881` (Singularity Rupture
  cycle-1-p2 docs-only), `2199f172` (cycle-1-p1),
  `7ad85ea9` / `8f8bc77b` (Archenemy's Charm cycle-1 docs-only),
  `7ef6e961` (Enduring Curiosity HONEST-STOP silent-no-op resolve).

## Sanity gates

Zero engine surface changes, zero src/ edits, zero rust/ edits — pure
docs landing. The substrate-only invariant the dispatch asked for
(Codecracker Hound STAYS DECLINED at the admit gate post-Cycle-1)
holds trivially: this branch ships no engine code, so the live
admit-gate state (`IS BRIDGE-ADMITTED: False`, probed live) is
unchanged from `main`.
