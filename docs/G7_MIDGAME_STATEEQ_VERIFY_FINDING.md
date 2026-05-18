# G7 mid-game STATE_EQ — verify-first finding + the auto-tap-from-lands engine fix

> **Status: CLOSED (the identified frontier) + honest-stop (the next
> distinct divergence pinned).** Lane: `feature/g7-midgame-stateeq`
> off `main` @ `cf994e47`. This doc is the verify-first diagnosis +
> fix record for the post-S1/S4 mid-game STATE_EQ frontier the
> orchestrator's bake-in probe surfaced (arch2/s1 @ step 273;
> arch5/s0 @ step 322). Cross-refs: `docs/RUST_STACK_RESOLUTION_
> DESIGN.md` (the G7 owner doc), `docs/SEARCH_LIMITATIONS.md` G7
> notes, `tests/test_rust_shadow_bakein.py::
> test_g7_midgame_cast_autotap_closed_then_s1_spellstack_zone_surfaced`.

## 1. The frontier (orchestrator probe)

Post-S1 (`5803aea7`) + S4 (`78e963c1`), the `rust_shadow` bake-in on
real 17lands production decks ran materially DEEPER than the original
C4 (which tripped at the first cast ~step 143). Two decks reproduced a
NEW mid-game STATE_EQ:

- `arch=2, seed=1` → STATE_EQ at step **273** (`Galactic Wayfarer`
  obj 9, `{2}{G}`)
- `arch=5, seed=0` → STATE_EQ at step **322** (`Icecave Crasher`
  obj 12)

Divergence shape: `hand_p0`, `mana_pool_p0`, `battlefield`, `stack`
all diverging.

## 2. Verify-first diagnosis — class (c), genuine engine bug

**Bisected** (instrumented `drive_shadow_game_to_terminal`): the
diverging step is a `CastSpell(card_id=9)` decision. Both engines
emit it in their legal set (LEGAL_SET_EQ passes — both account for
auto-tap headroom). After the apply:

- **Python** (`_cast_spell`): removed the spell from `p.hand`, spent
  mana, pushed a `StackItem` — the spell is on the stack.
- **Rust** (`apply_action` → `cast_creature`): a **complete silent
  no-op** — spell still in hand, mana NOT spent (`G:1` still
  floating), stack empty.

**Divergence direction CONFIRMED INVERTED from the orchestrator's
read:** Python casts the creature; Rust does NOT. (Verified against
`rust_shadow._assert_state_eq`'s `(field, py_value, rust_value)`
compare order.)

**Root cause (file:line).** The three stack-push cast primitives —
`cast_creature` / `cast_creature_warp` / `cast_spell_noncreature`
(`rust/src/state_ops_cast.rs`) — paid the cost STRICTLY from the
floating `mana_pool` via the local `pay_mana_cost`, returning
`Ok(false)` (a silent no-op) when the pool alone could not cover it.
The Rust legal emitter is **PERMISSIVE**: `auto_tap_headroom_pool`
(`state_ops_legal.rs:622`) / `can_pay_cost` (`state_ops_mana.rs:460`)
offer a `CastSpell` whenever floating pool **plus auto-tappable
lands** could pay — exactly Python's `can_pay_cost`
(`actions.py:336-403`). But Python's `_cast_spell` then ACTUALLY pays
via `auto_tap_for_cost` (`actions.py:919-986`, called at `:1662`):
consume floating pool first, then tap lands for the remainder. Rust's
apply path had **no auto-tap**. So a production-deck cast whose cost
needs land-tapping (pool alone short — here `{2}{G}` with `G:1`
floating + 2 untapped Forests) was emitted-legal then **silently
dropped** by apply. The documented Rust model is "permissive in
`legal`, strict in apply" (`state_ops_legal.rs:614-619`) — correct
for `ActivateAbility` (the random driver taps lands via separate
`ActivateAbility` decisions there) but **wrong for `CastSpell`**,
where Python's `_cast_spell` auto-taps atomically (there is no
separate decision).

**Reproduces under `cross_engine.step_both`** (the 4-file CE5-bridged
path) **identically** — `step_both` also calls `rust_state.apply_
action(cast_spell)` with no pre-tap, and Rust silently no-ops while
Python casts (CE5 then drains Python's stack, leaving the
hand/mana/battlefield/stack divergence). So this is a **genuine Rust
engine bug, NOT a `rust_shadow` driver / lockstep bug** (it is not
class a/b). The 4-file core gate stays green only because its
scenarios pre-populate the Rust pool / use pool-payable casts.

## 3. The fix (engine — new-code-is-right)

`state_ops_cast.rs` grows a free fn `auto_tap_pay_for_cost(state,
idx, cost)` that **byte-mirrors Python `auto_tap_for_cost`**:

1. Each colored requirement, in Python's `ManaCost.colored`
   iteration order (alphabetical by symbol — **B, G, R, U, W**;
   `cards.parse_mana_cost` sorts the pairs), is paid from the
   matching floating-pool slot FIRST, then by tapping untapped
   controller lands that produce that color (battlefield order,
   `[:need]`).
2. Generic (`cost.generic`) is paid from the remaining floating
   pool (deterministic `C→W→U→B→R→G` drain), then by tapping the
   remaining untapped lands `[:generic_need]`.
3. Each tapped land sets `tapped = true` and fires
   `Event::BecomesTapped` via the SAME post-borrow inline dispatch
   `tap_for_mana` uses (`state_ops_mana.rs:369-393`) — Python routes
   every tapped land through `turn.tap_permanent` which fires
   `Event.BECOMES_TAPPED` (`actions.py:981-985`).

Plan-then-commit: the helper plans the full payment before mutating;
an over-permissive emit (genuinely unpayable) degrades to the same
honest `Ok(false)` no-mutation bail the old pool-only `pay_mana_cost`
produced (NOT a partial spend — `feedback_no_fallback_hybrids`).
**Lands-only** (Python's `auto_tap_for_cost` AND `can_pay_cost` both
source from `_untapped_lands`, lands only; the Rust legal-side
`auto_tap_headroom_pool` is broader — also counting non-sick mana
creatures — which is a DISTINCT C1 axis,
`RUST_LEGAL_DECISIONS_MANA_AWARENESS_DESIGN.md`, out of scope and not
exercised by these repros). All three cast pay sites route through
the helper. The `ActivateAbility` pool-only `pay_mana_cost_pub` path
is intentionally unchanged (separate axis; the random driver taps
lands via separate `ActivateAbility` decisions there).

**Files touched:** `rust/src/state_ops_cast.rs` ONLY (+ the
`tests/test_rust_shadow_bakein.py` pin + this doc + the SL note).
Per CFI-1 a `state_ops_*.rs` touch does NOT fire the `cards.rs`
residue cadence. **A `.pyd` rebuild on `main` is owed (orchestrator's
— this lane is HARD-STOPped after merge).**

## 4. Result — frontier CLOSED, byte-equal land payment

At the trip step, with the fix, the cast now **succeeds
byte-perfectly**:

- The auto-tapped **land set is IDENTICAL** to Python's
  (`{26,59,23}` Forests for arch2/s1).
- `mana_pool_p0`, `battlefield`, `stack` all now MATCH.
- The post-cast divergence collapses from **4 fields** (hand + mana +
  battlefield + stack) to **1 field** (`hand_p0`).

## 5. The next distinct divergence (honest-stop — S5-region)

With the cast succeeding, the bake-in now surfaces the **S1/S4
spell-stack-source-zone divergence** — `hand_p0` ALONE:

- **Rust** keeps the cast spell's GameObject physically in the
  `hand` Vec with `zone=ZONE_HAND` while it is on the stack (so
  `take_source` / `find_source_printing_id` find it at resolve —
  `state_ops_resolve.rs:205-246`; this is the documented S1 design,
  `SEARCH_LIMITATIONS.md` G7-S1 note: *"card stays in hand, NO
  battlefield move"*).
- **Python**'s `_cast_spell` removes the card from `p.hand` and sets
  `card.zone=Zone.STACK` (`actions.py:1403`/`:1751`).

So `hand_p0` diverges (Rust's hand carries the stack-resident source
Python removed). This was **MASKED in the 4-file gate by CE5**
(`step_both` drains the stack after every `cast_spell` BEFORE the
compare, so the spell has resolved off-hand by compare time) and was
previously **unreachable in `rust_shadow`** because the no-auto-tap
bug failed the cast first.

**Diagnostic** (monkeypatched `_assert_state_eq` to ignore ONLY the
characterized `hand_p0` source-zone entry — characterization only,
NOT a shipped change): with the source-zone divergence hypothetically
resolved, arch2/s1 runs **273 → 281** and arch5/s0 runs **322 →
344**, then hits **LEGAL_SET_EQ** divergences (a C1-class legal-set
asymmetry / a combat-blocker emission) — clearly **S3/S5/C1-region**,
definitively out of this lane.

**Why honest-stop (not fixed here).** Re-homing the spell-stack
source zone requires touching `take_source` /
`find_source_printing_id` / `move_source_post_resolve` AND the
`hand_snapshot` surface — which is consumed by `rust_zone_view.py`
(the **codec slot source**), `rust_determinize.py`, `parity_smoke.py`
(the **4-file gate's field view**), and the legal emitter reads
`players[idx].hand.iter()` directly (3 sites) to emit `CastSpell`. A
high-blast-radius S1/S4 redesign that risks the 1532 baseline —
explicitly the S5-region work the brief scoped OUT ("Do NOT do
S5/S6/S7/S4b"). A precise honest-stop with the next divergence
pinned is the correct, disciplined outcome (S2/B1/S3/C4-G7
precedent); forcing the redesign here would be exactly the fragile
over-reach the brief warns against.

## 6. Follow-up (S5 / next slice owner)

The next owed slice for the non-warp-creature-deck frontier is the
**S1/S4 spell-stack-source-zone reconciliation**: make Rust remove
the cast spell from `hand` and place it stack-resident (re-home
`take_source` / `find_source_printing_id` / `move_source_post_
resolve` to a stack-source zone, and the `hand_snapshot` / codec-slot
/ legal-emit / determinizer surface accordingly), byte-mirroring
Python `card.zone = Zone.STACK` + `p.hand.remove(card)`
(`actions.py:1403`/`:1751`). Then the next frontier is the
LEGAL_SET_EQ axes the §5 diagnostic surfaced (C1/S3-region). This is
the S5-region successor; the G7 owner doc
(`RUST_STACK_RESOLUTION_DESIGN.md`) S5 section is the home for it.
