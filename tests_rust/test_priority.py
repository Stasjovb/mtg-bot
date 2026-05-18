"""Priority management primitives on the Rust ``GameState``.

Ported from Python's ``src/mtg_bot/game.py`` (the
``GameState.priority_player_idx`` field) and ``src/mtg_bot/turn.py``
(the priority-round mechanism). The Rust side keeps
``priority_player`` as a ``u8`` field on ``GameState`` (already
present from the foundation commit) and exposes Python-callable
getters / setters and pass-priority semantics in
``rust/src/state_ops_priority.rs``.

**Slice scope.**
- Pass-priority is a 2-player toggle: ``priority_player`` flips to
  the other player. Multi-player priority order (CR 800.4 / APNAP) is
  out of scope until/unless the engine grows past 2 players.
- Composition with phase advancement (the active player gets
  priority at the start of each step in CR 117.1a) is NOT
  implemented in this slice. ``advance_phase`` lives in
  ``state_ops_steps.rs`` and intentionally does NOT touch
  ``priority_player`` here. A future slice will integrate
  state_ops_priority + state_ops_steps so the active-player-gets-
  priority rule fires automatically. The
  ``test_priority_unaffected_by_phase_advance_in_this_slice`` test
  locks that boundary in.
- A priority "round" (both players pass with empty stack -> step
  ends per CR 117.4) is NOT modeled in this slice — it depends on a
  stack object which the Rust engine does not have yet.
"""

from __future__ import annotations

import pytest


def test_initial_priority_is_active_player(synthetic_state):
    """Fresh synthetic state: priority_player matches active_player
    (both start at 0)."""
    assert synthetic_state.active_player == 0
    assert synthetic_state.get_priority_player() == 0


def test_get_priority_player_returns_field(synthetic_state):
    """The getter just exposes the underlying u8 field."""
    assert synthetic_state.get_priority_player() == 0


def test_pass_priority_flips_to_other_player(synthetic_state):
    """`pass_priority` toggles priority from 0 to 1 in the 2-player
    model and returns the new value."""
    new_priority = synthetic_state.pass_priority()
    assert new_priority == 1
    assert synthetic_state.get_priority_player() == 1


def test_pass_priority_twice_returns_to_original(synthetic_state):
    """The pass-priority toggle is involutive: two passes return to
    the starting priority player."""
    synthetic_state.pass_priority()
    synthetic_state.pass_priority()
    assert synthetic_state.get_priority_player() == 0


def test_give_priority_to_explicit(synthetic_state):
    """`give_priority_to(player_id)` directly sets priority to the
    named player (skips the toggle semantics)."""
    synthetic_state.give_priority_to(1)
    assert synthetic_state.get_priority_player() == 1
    synthetic_state.give_priority_to(0)
    assert synthetic_state.get_priority_player() == 0


def test_give_priority_to_unknown_raises_value_error(synthetic_state):
    """Out-of-range player ids are rejected loudly (CR 800.4 doesn't
    apply here — we only have player ids 0 and 1)."""
    with pytest.raises(ValueError):
        synthetic_state.give_priority_to(2)
    with pytest.raises(ValueError):
        synthetic_state.give_priority_to(255)
    # State unchanged after the rejected calls.
    assert synthetic_state.get_priority_player() == 0


def test_pass_priority_does_not_affect_active_player(synthetic_state):
    """Active player and priority player are independent fields.
    Passing priority moves only `priority_player`; `active_player`
    stays put (only turn rollover via advance_phase from CLEANUP
    swaps active_player)."""
    starting_active = synthetic_state.active_player
    synthetic_state.pass_priority()
    assert synthetic_state.active_player == starting_active
    synthetic_state.pass_priority()
    assert synthetic_state.active_player == starting_active


def test_clone_preserves_priority(synthetic_state):
    """Clone copies the priority_player field (it's a u8 — by-value
    clone, no Arc/CoW involved)."""
    synthetic_state.give_priority_to(1)
    cloned = synthetic_state.clone_once()
    assert cloned.get_priority_player() == 1


def test_pass_priority_on_clone_does_not_affect_original(synthetic_state):
    """CoW canary: priority_player is a u8 on GameState, so a clone is
    a by-value copy of the field. Mutating priority on the clone must
    NOT bleed back into the original. (For Arc-backed zones this is
    where CoW would be load-bearing; for a plain u8 it's free, but
    the test still locks in that mutating-the-clone semantics is what
    callers expect.)"""
    cloned = synthetic_state.clone_once()
    cloned.pass_priority()
    assert cloned.get_priority_player() == 1
    assert synthetic_state.get_priority_player() == 0


def test_priority_unaffected_by_advance_phase_within_a_turn(synthetic_state):
    """Round-27 G15 closure (within-turn shape).

    CR 117.1a: at the start of each step, the active player gets
    priority. The Rust port models this at the TURN boundary only
    (CLEANUP -> UNTAP wrap); within-turn step advances do NOT touch
    `priority_player`. Mirrors Python's `simulate.py`: the priority
    loop owns within-step priority management; `state.priority_player_idx`
    is only directly mutated at turn rollover (line 213).

    Hands priority to the non-active player and advances a single
    step (UNTAP -> UPKEEP, no wrap). Priority stays put — the
    within-turn advance does not fire the CR 117.1a reset.
    """
    # Hand priority to the non-active player so we can detect any
    # accidental "active player gets priority" reset.
    synthetic_state.give_priority_to(1)
    assert synthetic_state.get_priority_player() == 1
    synthetic_state.advance_phase()  # UNTAP -> UPKEEP, no turn wrap
    # Priority did NOT reset to the active player (0). The reset
    # only fires on CLEANUP -> UNTAP wrap — see
    # ``test_advance_phase_full_lap_resets_priority_to_active_at_wrap``
    # and ``test_advance_phase_keeps_priority_player_in_sync_with_active``
    # for that path.
    assert synthetic_state.get_priority_player() == 1


# ---------------------------------------------------------------------------
# Round-9 composition slice: priority + stack.
#
# When BOTH players consecutively pass priority while the stack is
# non-empty, the top stack item resolves (CR 117.4 / 117.5). This
# slice exposes ``complete_priority_round()`` as the priority-round-
# completion primitive: caller decides both players have passed, then
# invokes this method.
#
# **Scope (pop-only stepping-stone).** This method does NOT dispatch
# the resolved item's effects. It pops the top stack item, returns
# its dict, and resets priority to ``active_player`` (CR 117.1c — the
# AP gets priority after a spell or ability resolves). Real effect
# dispatch is the job of ``resolve_top_of_stack`` in
# ``state_ops_resolve.rs`` — a future composition slice can chain
# them together once the cross-file file-isolation rule relaxes.
#
# **Cross-file private-method friction.** This slice WANTS to call
# ``resolve_top_of_stack`` from ``state_ops_resolve.rs``, but that
# method is private to its module's pyclass impl block and the slice
# rules forbid touching that file. Per the recurring inlining
# pattern (5+ instances across slices: round-7 counterspell inlined
# move_object, round-8 resolve-effects inlined draw_card, etc.), the
# pragmatic call here is to inline a *minimal* version: pop + reset
# priority, no effect dispatch. This keeps the slice surface small
# and lets the real-effect path stay solely in ``state_ops_resolve``.
# ---------------------------------------------------------------------------


def test_complete_priority_round_with_empty_stack_returns_none(synthetic_state):
    """Empty stack -> ``complete_priority_round()`` returns ``None``
    and is a no-op on stack/priority. Mirrors the empty-stack
    convention of ``pop_top_of_stack`` / ``resolve_top_of_stack``."""
    assert synthetic_state.is_stack_empty() is True
    result = synthetic_state.complete_priority_round()
    assert result is None
    assert synthetic_state.is_stack_empty() is True


def test_complete_priority_round_with_nonempty_stack_returns_popped_item_dict(
    synthetic_state,
):
    """Stack has one item -> ``complete_priority_round()`` returns the
    popped item as a dict ({source_obj_id, controller}) and the stack
    shrinks by 1."""
    synthetic_state.push_to_stack(42, 0)
    assert synthetic_state.stack_size() == 1
    result = synthetic_state.complete_priority_round()
    assert isinstance(result, dict)
    assert result == {"source_obj_id": 42, "controller": 0}
    assert synthetic_state.stack_size() == 0
    assert synthetic_state.is_stack_empty() is True


def test_complete_priority_round_passes_priority_to_active_player(synthetic_state):
    """After a stack item resolves (or in this slice's stepping-stone
    shape, after the top is popped), priority returns to the active
    player (CR 117.1c). Even if priority was the non-active player at
    the time of the round-completion, it resets to AP."""
    synthetic_state.push_to_stack(9, 1)
    # Hand priority to the non-active player (player 1) before
    # completing the round, so we can detect the post-resolution reset.
    synthetic_state.give_priority_to(1)
    assert synthetic_state.get_priority_player() == 1
    synthetic_state.complete_priority_round()
    assert synthetic_state.get_priority_player() == synthetic_state.active_player
    assert synthetic_state.get_priority_player() == 0  # active_player == 0 in synth.


def test_complete_priority_round_does_not_advance_phase(synthetic_state):
    """Resolving a stack item does NOT advance the phase. Phase /
    step is the job of ``advance_phase`` from
    ``state_ops_steps.rs``; the priority-round-completion primitive
    just unwinds one stack item."""
    starting_phase = synthetic_state.current_phase()
    synthetic_state.push_to_stack(11, 0)
    synthetic_state.complete_priority_round()
    assert synthetic_state.current_phase() == starting_phase


def test_complete_priority_round_with_multi_item_stack_pops_only_top(synthetic_state):
    """Push A then B (B on top). ``complete_priority_round()`` pops
    only the TOP (B); A is still on the stack. Returns B's dict."""
    synthetic_state.push_to_stack(100, 0)  # A (bottom)
    synthetic_state.push_to_stack(200, 1)  # B (top)
    assert synthetic_state.stack_size() == 2
    result = synthetic_state.complete_priority_round()
    assert result == {"source_obj_id": 200, "controller": 1}
    assert synthetic_state.stack_size() == 1
    # A is still on top.
    top = synthetic_state.peek_top_of_stack()
    assert top == {"source_obj_id": 100, "controller": 0}


def test_clone_then_complete_priority_round_does_not_affect_original(synthetic_state):
    """CoW canary: completing a priority round on a clone unwinds the
    clone's stack and resets the clone's priority. The original's
    stack and priority must be untouched."""
    synthetic_state.push_to_stack(55, 0)
    synthetic_state.give_priority_to(1)
    cloned = synthetic_state.clone_once()
    cloned.complete_priority_round()
    # Clone: stack drained, priority reset to active player (0).
    assert cloned.stack_size() == 0
    assert cloned.get_priority_player() == 0
    # Original: untouched.
    assert synthetic_state.stack_size() == 1
    assert synthetic_state.get_priority_player() == 1


# ---------------------------------------------------------------------------
# Bridge slice: ``active_player_idx`` + ``priority_player_idx`` Python-property
# getters.
#
# Mirrors Python's ``GameState.active_player_idx`` and
# ``GameState.priority_player_idx`` dataclass fields (see
# ``src/mtg_bot/game.py:2587-2588``). These are read as PLAIN
# ATTRIBUTES (no parens) on the Python side, so the Rust bridge must
# expose them via ``#[getter]`` rather than as method calls. The
# ``scripts/parity_smoke.py:hash_state`` consumer reads both this way.
# ---------------------------------------------------------------------------


def test_active_player_idx_initial_is_zero(synthetic_state):
    """Fresh synthetic state has active_player == 0; the property
    alias reflects that."""
    assert synthetic_state.active_player_idx == 0


def test_priority_player_idx_matches_get_priority_player(synthetic_state):
    """``priority_player_idx`` is a property alias for the existing
    ``get_priority_player()`` pymethod; they must always agree."""
    assert synthetic_state.priority_player_idx == synthetic_state.get_priority_player()
    synthetic_state.give_priority_to(1)
    assert synthetic_state.priority_player_idx == synthetic_state.get_priority_player()


def test_property_aliases_are_not_callable(synthetic_state):
    """Both aliases are ``#[getter]`` properties — reading is plain
    attribute access. Calling them as methods raises ``TypeError``
    because an ``int`` (the property's value) isn't callable."""
    with pytest.raises(TypeError):
        synthetic_state.active_player_idx()
    with pytest.raises(TypeError):
        synthetic_state.priority_player_idx()


def test_active_player_idx_reflects_cleanup_wraparound(synthetic_state):
    """``advance_phase`` swaps the active player on CLEANUP -> UNTAP.
    The property alias must see the new active player after the wrap."""
    # Walk advance_phase forward until the active player flips. The
    # synthetic state starts on UNTAP; the cleanup-wrap swap happens
    # when advance_phase ticks past CLEANUP.
    starting_active = synthetic_state.active_player_idx
    for _ in range(20):  # bounded loop; cleanup is hit well before 20 steps.
        synthetic_state.advance_phase()
        if synthetic_state.active_player_idx != starting_active:
            break
    assert synthetic_state.active_player_idx == 1 - starting_active


def test_priority_player_idx_toggles_with_pass_priority(synthetic_state):
    """``priority_player_idx`` reflects ``pass_priority`` toggles —
    mirrors the existing ``get_priority_player()`` flip test."""
    assert synthetic_state.priority_player_idx == 0
    synthetic_state.pass_priority()
    assert synthetic_state.priority_player_idx == 1
    synthetic_state.pass_priority()
    assert synthetic_state.priority_player_idx == 0


# ---------------------------------------------------------------------------
# Cross-feature edge cases — priority × {stack, steps, cast, activate,
# legal-decisions, snapshot, fingerprint, clone-CoW}.
#
# These tests pin the CURRENT (slice-period) behavior at the intersection
# of the priority primitive with each adjacent primitive. Several of them
# pin *deliberate non-composition* (the slice docstring at the top of
# this file says the "both players pass → step ends" rule and the
# "active player gets priority after each spell/ability" rule are NOT
# wired up yet) — when a future slice integrates the two, those tests
# will need to be updated. The intent of each one is called out inline.
# ---------------------------------------------------------------------------


PHASE_UNTAP = 0
PHASE_UPKEEP = 1
PHASE_DRAW = 2
PHASE_MAIN1 = 3
PHASE_BEGIN_COMBAT = 4
PHASE_DECLARE_ATTACKERS = 5
PHASE_DECLARE_BLOCKERS = 6
PHASE_COMBAT_DAMAGE = 7
PHASE_END_COMBAT = 8
PHASE_MAIN2 = 9
PHASE_END_STEP = 10
PHASE_CLEANUP = 11


def test_pass_priority_alone_does_not_advance_step_or_resolve(synthetic_state):
    """Round-27 G3 closure (primitive-layer invariant).

    Even after the priority + composition layer lands,
    ``pass_priority`` itself remains a pure toggle that increments
    ``consecutive_passes``. The step does NOT auto-end when two
    passes happen in sequence at the PRIMITIVE layer — that's the
    composer's job (``complete_step_via_priority_round``). Pinning
    this primitive/composer separation so a future "smart
    pass_priority" refactor surfaces deliberately."""
    assert synthetic_state.current_phase() == PHASE_UNTAP
    assert synthetic_state.is_stack_empty() is True
    synthetic_state.pass_priority()
    synthetic_state.pass_priority()
    # Step is unchanged; priority is back to where it started; the
    # counter shows two consecutive passes.
    assert synthetic_state.current_phase() == PHASE_UNTAP
    assert synthetic_state.get_priority_player() == 0
    assert synthetic_state.get_consecutive_passes() == 2


def test_complete_step_via_priority_round_advances_step_when_stack_empty(
    synthetic_state,
):
    """Round-27 G3 closure (composer, empty-stack leg — CR 117.4).

    When both players pass in succession with an empty stack, the
    current step ends. The composer ``complete_step_via_priority_round``
    routes both passes + ``advance_phase`` in one call and returns
    ``True`` to signal the step advanced."""
    assert synthetic_state.current_phase() == PHASE_UNTAP
    assert synthetic_state.is_stack_empty() is True
    advanced = synthetic_state.complete_step_via_priority_round()
    assert advanced is True
    # Phase ticked one step forward (UNTAP -> UPKEEP).
    assert synthetic_state.current_phase() == PHASE_UPKEEP
    # Counter reset (advance_phase is a non-pass mutation).
    assert synthetic_state.get_consecutive_passes() == 0


def test_complete_step_via_priority_round_resolves_top_when_stack_nonempty(
    synthetic_state,
):
    """Round-27 G3 closure (composer, non-empty-stack leg — CR 117.4).

    When both players pass with a non-empty stack, the top resolves
    INSTEAD of the step ending. The composer returns ``False`` to
    signal "no step advance — more priority rounds happen", priority
    resets to the active player (CR 117.1c), and the stack item is
    popped."""
    starting_phase = synthetic_state.current_phase()
    synthetic_state.push_to_stack(42, 0)
    assert synthetic_state.stack_size() == 1
    advanced = synthetic_state.complete_step_via_priority_round()
    assert advanced is False
    # Stack drained, step unchanged, priority reset to active player.
    assert synthetic_state.stack_size() == 0
    assert synthetic_state.current_phase() == starting_phase
    assert synthetic_state.get_priority_player() == synthetic_state.active_player
    assert synthetic_state.get_consecutive_passes() == 0


def test_complete_step_via_priority_round_with_multi_item_stack_pops_only_top(
    synthetic_state,
):
    """Round-27 G3 closure (composer, multi-item stack).

    Push A then B (B on top). Composer pops only the TOP (B); A
    stays on the stack. Returns ``False`` (resolution leg). Mirrors
    the pop-only stepping-stone shape of ``complete_priority_round``
    — real effect dispatch is still the job of ``resolve_top_of_stack``
    in ``state_ops_resolve.rs`` (cross-file private-method friction)."""
    synthetic_state.push_to_stack(100, 0)
    synthetic_state.push_to_stack(200, 1)
    assert synthetic_state.stack_size() == 2
    advanced = synthetic_state.complete_step_via_priority_round()
    assert advanced is False
    assert synthetic_state.stack_size() == 1
    # A is still on top.
    top = synthetic_state.peek_top_of_stack()
    assert top == {"source_obj_id": 100, "controller": 0}


def test_complete_step_via_priority_round_resets_priority_to_active_after_resolution(
    synthetic_state,
):
    """Round-27 G3 closure (CR 117.1c — composer resolution leg).

    Even when priority was on the NON-active player at the time
    both-passes is invoked, the composer's stack-resolution leg
    resets priority to the active player. Mirrors the same reset
    contract that the existing ``complete_priority_round`` primitive
    pins for the pop-only stepping-stone."""
    synthetic_state.push_to_stack(9, 1)
    # Hand priority to the non-active player BEFORE the composer
    # call so we can detect the post-resolution reset. The composer's
    # two internal pass_priority calls will flip it 1 -> 0 -> 1, then
    # the resolution leg resets to active_player (0).
    synthetic_state.give_priority_to(1)
    assert synthetic_state.get_priority_player() == 1
    synthetic_state.complete_step_via_priority_round()
    assert synthetic_state.get_priority_player() == synthetic_state.active_player
    assert synthetic_state.get_priority_player() == 0


def test_consecutive_passes_increments_on_each_pass(synthetic_state):
    """Round-27 G3 closure (counter increment).

    Each ``pass_priority`` invocation bumps ``consecutive_passes`` by
    one. Pinning the increment so a future refactor that switches the
    counter to a different shape (e.g. computed from history) keeps
    the same single-call surface."""
    assert synthetic_state.get_consecutive_passes() == 0
    synthetic_state.pass_priority()
    assert synthetic_state.get_consecutive_passes() == 1
    synthetic_state.pass_priority()
    assert synthetic_state.get_consecutive_passes() == 2
    synthetic_state.pass_priority()
    assert synthetic_state.get_consecutive_passes() == 3


def test_consecutive_passes_resets_on_non_pass_action(synthetic_state):
    """Round-27 G3 closure (counter reset on non-pass mutation).

    Any non-pass action breaks the consecutive-pass streak. Walk
    through the four reset paths: explicit `give_priority_to`,
    `advance_phase`, `cast_creature`, and `apply_action` with a
    non-pass arm (ActivateAbility). All four must drop the counter
    back to 0."""
    # give_priority_to resets.
    synthetic_state.pass_priority()
    synthetic_state.pass_priority()
    assert synthetic_state.get_consecutive_passes() == 2
    synthetic_state.give_priority_to(0)
    assert synthetic_state.get_consecutive_passes() == 0

    # advance_phase resets.
    synthetic_state.pass_priority()
    assert synthetic_state.get_consecutive_passes() == 1
    synthetic_state.advance_phase()
    assert synthetic_state.get_consecutive_passes() == 0

    # cast_creature resets.
    synthetic_state.pass_priority()
    assert synthetic_state.get_consecutive_passes() == 1
    synthetic_state.add_mana(0, "G", 1)
    assert synthetic_state.cast_creature(10, 0) is True
    assert synthetic_state.get_consecutive_passes() == 0

    # apply_action(ActivateAbility) resets.
    synthetic_state.pass_priority()
    assert synthetic_state.get_consecutive_passes() == 1
    synthetic_state.apply_action(
        {"kind": "activate_ability", "source_id": 0, "ability_index": 0}
    )
    assert synthetic_state.get_consecutive_passes() == 0


def test_complete_priority_round_resets_consecutive_passes(synthetic_state):
    """Round-27 G3 closure (round-9 composer also resets counter).

    The older ``complete_priority_round`` primitive (pop-only
    stepping-stone) is on the same composition path as the new
    ``complete_step_via_priority_round`` for the non-empty-stack leg.
    Both reset the counter so a subsequent priority round starts
    fresh."""
    synthetic_state.push_to_stack(55, 0)
    synthetic_state.pass_priority()
    synthetic_state.pass_priority()
    assert synthetic_state.get_consecutive_passes() == 2
    result = synthetic_state.complete_priority_round()
    assert result == {"source_obj_id": 55, "controller": 0}
    assert synthetic_state.get_consecutive_passes() == 0


def test_complete_priority_round_resolves_top_instead_of_advancing_step(
    synthetic_state,
):
    """Composition pin (priority × stack × steps): with a non-empty
    stack, completing the priority round pops the top entry rather
    than advancing the step. Mirrors CR 117.4 — the stack-resolution
    leg of "both players have passed" runs BEFORE the step-end leg.
    Locks in that the priority-round primitive picks the right leg
    based on the stack-empty predicate."""
    starting_phase = synthetic_state.current_phase()
    synthetic_state.push_to_stack(99, 1)
    assert synthetic_state.stack_size() == 1
    result = synthetic_state.complete_priority_round()
    # Stack item popped; phase unchanged (no step advance).
    assert result == {"source_obj_id": 99, "controller": 1}
    assert synthetic_state.stack_size() == 0
    assert synthetic_state.current_phase() == starting_phase


def test_legal_decisions_for_priority_holder_emits_pass_priority(synthetic_state):
    """Cross-feature with legal-decisions: the active player (= priority
    holder by default in the synthetic seed) sees PassPriority as the
    first legal action. Pins the contract that whoever currently holds
    priority always has *some* legal decision, and that decision is
    always PassPriority at index 0 (Python `legal.py:178`)."""
    assert synthetic_state.active_player == synthetic_state.get_priority_player() == 0
    actions = synthetic_state.legal_decisions(0)
    kinds = [a["kind"] for a in actions]
    assert kinds[0] == "pass_priority"


def test_legal_decisions_for_non_priority_player_still_emits_pass_priority(
    synthetic_state,
):
    """Cross-feature with legal-decisions — DOCUMENTED QUIRK.

    Python's ``legal.py:180-181`` short-circuits to ``[PassPriority]``
    when the caller doesn't have priority — the only action a
    non-priority player can take is to ... pass priority (which is
    semantically a no-op for them but legal CR-wise). The Rust
    enumerator mirrors that: ask ``legal_decisions(non_priority_idx)``
    on a state where the other player has priority and you still get
    back the singleton ``[pass_priority]`` list, not an empty list.

    This is the parity-locked surface that ``test_legal.py``'s
    ``test_legal_decisions_priority_off_emits_only_pass_priority``
    already pins from the legal-decisions side. We pin it again here
    from the priority side so a future refactor of the priority
    primitive that wants to change "off-priority → no actions" notices
    that this is intentional Python parity, not a bug."""
    # Flip priority away from p0 (synthetic active+priority=0).
    synthetic_state.pass_priority()
    assert synthetic_state.get_priority_player() == 1
    # Ask p0 (the now-non-priority player) what's legal.
    actions = synthetic_state.legal_decisions(0)
    kinds = [a["kind"] for a in actions]
    assert kinds == ["pass_priority"]


def test_cast_spell_resets_priority_to_active(synthetic_state):
    """Round-27 G4 closure (priority × cast — CR 117.1c).

    After a spell is cast, the active player gets priority. The Rust
    ``cast_creature`` primitive fuses the Python "push to stack ->
    resolve" sequence into a single mutation (no-stack semantics —
    see the primitive's docstring), so the "after cast" priority
    reset happens at the end of the primitive on success.

    P0_FIRST_HAND_ID == 10 (Llanowar Elves, cost {G}) per the
    synthetic seed; we give priority to player 1 BEFORE the cast so
    the post-cast reset is observable (priority moves 1 -> 0)."""
    elf_id = 10
    synthetic_state.add_mana(0, "G", 1)
    synthetic_state.give_priority_to(1)
    assert synthetic_state.get_priority_player() == 1
    assert synthetic_state.cast_creature(elf_id, 0) is True
    # Priority reset to the active player (0). Also breaks any
    # in-flight pass streak.
    assert synthetic_state.get_priority_player() == synthetic_state.active_player
    assert synthetic_state.get_priority_player() == 0
    assert synthetic_state.get_consecutive_passes() == 0


def test_cast_spell_failure_does_not_touch_priority(synthetic_state):
    """Round-27 G4 closure (failed-cast no-op contract).

    A cast that fails its precondition gate (insufficient mana, wrong
    type, unknown obj_id, etc.) returns ``False`` without mutating
    state. Priority must stay where the caller put it — the reset
    only fires on a SUCCESSFUL cast. Pinning the failure-path no-op
    so future cast slices don't accidentally fire the reset before
    validating preconditions."""
    elf_id = 10
    # **G7 mid-game STATE_EQ closure-flip (auto-tap-from-lands).** The
    # failed-cast no-op (priority untouched only on a SUCCESSFUL cast)
    # is unchanged, but "don't add mana" no longer makes the cast fail
    # — the synthetic state's 5 untapped Forests now auto-tap to pay
    # (byte-mirroring Python's ``_cast_spell`` -> ``auto_tap_for_
    # cost``). Tap every p0 land so the cast genuinely fails its mana
    # gate, then the failure-path priority no-op still holds,
    # new-code-is-right.
    for o in synthetic_state.battlefield_snapshot():
        if o["controller_id"] == 0 and o["printing_name"] == "Forest":
            synthetic_state.tap_object(o["id"])
    # No mana, no land headroom — the cast fails at the pay gate.
    synthetic_state.give_priority_to(1)
    assert synthetic_state.get_priority_player() == 1
    assert synthetic_state.cast_creature(elf_id, 0) is False
    # Priority untouched on failure.
    assert synthetic_state.get_priority_player() == 1


def test_activate_mana_ability_resets_priority_to_active(synthetic_state):
    """Round-27 G4 closure (priority × activate — CR 117.1c).

    Mirror of the cast-spell pin: activating a mana ability resets
    priority to the active player. CR 117.7b clarifies mana abilities
    don't use the stack at all (they resolve immediately) — the
    "after the ability resolves" moment is right at the end of the
    primitive's mutation phase.

    Source id 0 is a Forest on p0's battlefield in the synthetic
    seed; ability index 0 is its tap-for-{G} mana ability."""
    synthetic_state.give_priority_to(1)
    assert synthetic_state.get_priority_player() == 1
    synthetic_state.apply_action(
        {"kind": "activate_ability", "source_id": 0, "ability_index": 0}
    )
    # Priority reset to active player (0); pass streak (if any) broken.
    assert synthetic_state.get_priority_player() == synthetic_state.active_player
    assert synthetic_state.get_priority_player() == 0
    assert synthetic_state.get_consecutive_passes() == 0


def test_advance_phase_full_lap_resets_priority_to_active_at_wrap(synthetic_state):
    """Round-27 G15 closure (priority × steps, lap-scale — CR 117.1a).

    Walking ALL 12 phases (UNTAP → ... → CLEANUP → UNTAP) fires the
    CLEANUP -> UNTAP wrap exactly once. On that wrap, ``active_player``
    flips AND ``priority_player`` resets to the new active player.
    Within-turn step advances (the other 11 of the 12) do NOT touch
    priority — only the wrap.

    Seed: active=0, priority=1 (give_priority_to). After the wrap:
    active=1, priority=1 (reset to new active). Same value before
    and after the wrap, but the path differs — to make the post-wrap
    state-machine observable, we additionally check that an
    in-between advance leaves the manually-set priority alone."""
    # Stash priority on the non-active player so the within-turn
    # advances are observed not touching it.
    synthetic_state.give_priority_to(1)
    assert synthetic_state.get_priority_player() == 1
    starting_active = synthetic_state.active_player
    # 11 within-turn advances: priority stays at 1, active stays put.
    for i in range(11):
        synthetic_state.advance_phase()
        assert synthetic_state.get_priority_player() == 1, (
            f"priority reset on within-turn advance at phase "
            f"{synthetic_state.current_phase()} (iter {i}) — should "
            "only reset on CLEANUP -> UNTAP wrap"
        )
        assert synthetic_state.active_player == starting_active
    # 12th advance: CLEANUP -> UNTAP wrap. active flips; priority
    # resets to NEW active player.
    synthetic_state.advance_phase()
    assert synthetic_state.active_player == 1 - starting_active
    assert synthetic_state.get_priority_player() == synthetic_state.active_player


def test_pass_priority_on_clone_does_not_mutate_original_step(synthetic_state):
    """CoW canary (priority × steps × clone): mutating both the
    clone's priority AND the clone's phase must not bleed back into
    the original's priority or phase. Combines the two scalar fields
    into one canary so the "by-value u8 fields don't share storage"
    invariant is pinned across the priority↔step pair, not just one
    at a time."""
    synthetic_state.set_phase(PHASE_MAIN1)
    starting_phase = synthetic_state.current_phase()
    starting_prio = synthetic_state.get_priority_player()
    cloned = synthetic_state.clone_once()
    cloned.pass_priority()
    cloned.set_phase(PHASE_DECLARE_ATTACKERS)
    # Clone moved on both axes.
    assert cloned.get_priority_player() == 1 - starting_prio
    assert cloned.current_phase() == PHASE_DECLARE_ATTACKERS
    # Original untouched on both axes.
    assert synthetic_state.get_priority_player() == starting_prio
    assert synthetic_state.current_phase() == starting_phase


def test_fingerprint_changes_when_priority_player_differs(synthetic_state):
    """Cross-feature with fingerprint: ``priority_player_idx`` is a
    component of ``hash_state``'s digest (see ``test_fingerprint.py``
    module docstring's ``parts`` recipe — element index 3). Two
    states identical except for priority must produce different
    fingerprints. Pins the priority-axis sensitivity of the digest so
    parity_smoke trajectories with different priority holders never
    silently hash-collide."""
    fp_before = synthetic_state.fingerprint()
    synthetic_state.pass_priority()
    fp_after = synthetic_state.fingerprint()
    assert fp_before != fp_after
    # And toggling back recovers the original digest (priority is the
    # only thing that changed).
    synthetic_state.pass_priority()
    assert synthetic_state.fingerprint() == fp_before


def test_fingerprint_changes_when_step_differs_independent_of_priority(
    synthetic_state,
):
    """Cross-feature with fingerprint: ``step`` is the second element
    of ``hash_state``'s ``parts`` tuple (after ``turn_number``). Two
    states identical except for phase produce different fingerprints,
    AND that sensitivity is independent of priority — set the same
    priority on both, change only the phase, the digests must differ.
    Pins the step-axis sensitivity of the digest."""
    # Pin priority so the only delta is phase.
    synthetic_state.give_priority_to(1)
    synthetic_state.set_phase(PHASE_MAIN1)
    fp_main1 = synthetic_state.fingerprint()
    synthetic_state.set_phase(PHASE_MAIN2)
    fp_main2 = synthetic_state.fingerprint()
    assert fp_main1 != fp_main2
    # Priority is still 1 — pure phase delta.
    assert synthetic_state.get_priority_player() == 1


def test_priority_player_idx_snapshot_property_agrees_after_each_pass(
    synthetic_state,
):
    """Snapshot getter parity: the ``priority_player_idx`` property
    alias must agree with the underlying ``get_priority_player()``
    method at EVERY step of a multi-pass walk. Mirrors the
    ``priority_player_idx`` and ``get_priority_player()`` contract
    locked in by ``test_priority_player_idx_matches_get_priority_player``,
    but pins the agreement across N consecutive transitions (not just
    one). Cheap canary for any future refactor that splits the property
    getter off into a separately-cached pathway."""
    for _ in range(5):
        synthetic_state.pass_priority()
        assert (
            synthetic_state.priority_player_idx
            == synthetic_state.get_priority_player()
        )


# --- CE2 closure regression -----------------------------------------
#
# Round-28 / Phase 5 CE2 closure: ``apply_action({"kind":
# "pass_priority"})`` is a TRUE NO-OP — it does NOT flip
# ``priority_player`` and does NOT bump ``consecutive_passes``. Mirrors
# Python's ``apply_action(PassPriority)`` which is literally a
# ``return`` (src/mtg_bot/actions.py:990-991). Priority management is
# owned by the composer ``complete_step_via_priority_round`` and by
# the ``pass_priority`` primitive when callers drive it directly.
#
# These tests pin the new no-op behavior on both directions (p0 passes,
# p1 passes) so a future regression that re-introduces the toggle
# surfaces here loudly.


def test_apply_action_pass_priority_noop_for_p0(synthetic_state):
    """**CE2 closure**: when p0 holds priority and applies
    PassPriority via ``apply_action``, ``priority_player`` stays at
    0. The arm is a pure no-op."""
    assert synthetic_state.get_priority_player() == 0
    synthetic_state.apply_action({"kind": "pass_priority"})
    assert synthetic_state.get_priority_player() == 0


def test_apply_action_pass_priority_noop_for_p1(synthetic_state):
    """**CE2 closure**: when p1 holds priority and applies
    PassPriority via ``apply_action``, ``priority_player`` stays at
    1. The arm is a pure no-op — symmetric with the p0 case."""
    synthetic_state.give_priority_to(1)
    assert synthetic_state.get_priority_player() == 1
    synthetic_state.apply_action({"kind": "pass_priority"})
    assert synthetic_state.get_priority_player() == 1


def test_apply_action_pass_priority_noop_does_not_bump_counter(synthetic_state):
    """**CE2 closure**: ``apply_action({"kind": "pass_priority"})``
    does NOT advance the ``consecutive_passes`` counter. The counter
    only advances when callers invoke the ``pass_priority`` primitive
    directly OR when the composer drives it.

    Mirrors Python (no equivalent counter exists on the Python side,
    so the apply_action arm is bit-for-bit a no-op). Composer-driven
    paths still increment the counter — that contract is pinned by
    ``test_consecutive_passes_increments_on_each_pass`` above."""
    assert synthetic_state.get_consecutive_passes() == 0
    for _ in range(5):
        synthetic_state.apply_action({"kind": "pass_priority"})
    assert synthetic_state.get_consecutive_passes() == 0
    # Sanity: the primitive still increments. We're pinning the
    # apply_action path's no-op semantics, not breaking the primitive.
    synthetic_state.pass_priority()
    assert synthetic_state.get_consecutive_passes() == 1


def test_apply_action_pass_priority_noop_preserves_active_player(synthetic_state):
    """**CE2 closure**: ``apply_action({"kind": "pass_priority"})`` is
    a pure no-op — ``active_player`` is unchanged. Combined with the
    priority-unchanged pin above, this proves the arm leaves the
    state byte-identical on the priority axis. Mirrors invariant I8
    (active and priority player are independent fields)."""
    starting_active = synthetic_state.active_player
    starting_priority = synthetic_state.get_priority_player()
    synthetic_state.apply_action({"kind": "pass_priority"})
    assert synthetic_state.active_player == starting_active
    assert synthetic_state.get_priority_player() == starting_priority


def test_apply_action_pass_priority_noop_preserves_fingerprint(synthetic_state):
    """**CE2 closure**: PassPriority via ``apply_action`` is a true
    no-op — the parity fingerprint is byte-identical before and
    after. Pins the digest stability so future refactors that
    accidentally mutate a non-fingerprinted field (e.g. flip a
    visibility flag) surface here.

    Note: ``consecutive_passes`` is NOT in the fingerprint (per
    invariant I25), so even if the counter were mistakenly bumped, the
    digest would stay stable. The companion test
    ``test_apply_action_pass_priority_noop_does_not_bump_counter``
    catches the counter-mutation case."""
    fp_before = synthetic_state.fingerprint()
    synthetic_state.apply_action({"kind": "pass_priority"})
    fp_after = synthetic_state.fingerprint()
    assert fp_before == fp_after


# ---------------------------------------------------------------------------
# G7 Slice S3 — priority / response windows (the new surface).
#
# **Verify-first finding (G7_S3_VERIFY_FINDING.md): CLEAN-VERIFY
# NO-OP.** The design-doc S3 hypothesized a cast-time priority-reset
# fix; S1 (`5803aea7`) ALREADY landed the correct stack-semantics
# reset. The brief's quoted docstring ("a future stack-using cast
# slice will need to re-think when the reset fires") existed only
# PRE-S1 (`6b3e5565^`) — S1 deleted it and resolved the open
# question. The cast-push `priority_player = active_player`
# (`state_ops_cast.rs:633`) is REDUNDANT (the adapter loop's
# `_reset_priority_to_active()` at `rust_engine_adapter.py:511`
# overwrites it with the byte-equal Python `_next_alive(active)`
# target right after `apply_action` returns, before any compare
# point), NOT divergent. NO `rust/src/` change.
#
# These pins are the design-named S3 DELIVERABLE: the first
# engine-level exercise of a REAL nested response window —
# a permanent (creature) spell sitting on the Rust stack across a
# priority round while the opponent responds with an instant. This
# surface NEVER existed cross-engine before S1 (no spell ever sat on
# the Rust stack long enough for an opponent response). They lock:
#   (a) the creature cast pushes a StackItem, does NOT atomic-resolve;
#   (b) the opponent's instant-speed response window emits the
#       CastSpell via `legal_decisions` WHILE the permanent spell is
#       on the stack (I46 two-pass — the instant-speed pass is gated
#       per-card on `is_instant || has_flash`, run BEFORE the
#       sorcery-timing `stack.is_empty()` gate, so a spell on the
#       stack does NOT suppress the response);
#   (c) the response goes on TOP (LIFO) and resolves FIRST, then the
#       permanent spell resolves and lands — byte-mirroring Python's
#       `simulate.py:priority_loop:254-267` resolve-LIFO;
#   (d) the post-resolution priority reset lands on the active player
#       via the `_next_alive`-equivalent — byte-equal to Python's
#       `simulate.py:266-267` (`priority_idx = _next_alive(state,
#       state.active_player_idx)` after each resolution).
# ---------------------------------------------------------------------------

# Phase constant — mirrors ``rust/src/state_ops_steps.rs`` (PHASE_MAIN1
# is the precombat main phase; the synthetic seed defaults to it for
# the sorcery-timing-eligible window, matching ``test_cast.py``).
_PHASE_MAIN1 = 3
# Zone constant — mirrors ``rust/src/state_ops_zones.rs``.
_ZONE_HAND = 0
_ZONE_BATTLEFIELD = 2
_ZONE_GRAVEYARD = 3
_ZONE_STACK = 4  # G7 S5a: the spell-stack-source-zone store.
# Synthetic seed: p0 hand[0] is a Llanowar Elves ({G} creature).
_P0_ELF_ID = 10


def _response_instant_dict():
    """A no-effects Instant — the opponent's response spell. It needs
    no effect (we assert the priority/resolution SEQUENCE + LIFO
    ordering, not an effect observable); the bare Instant routes
    through `cast_spell_noncreature` and post-resolves hand ->
    graveyard. Mirrors ``test_counterspell._vanilla_dict`` /
    ``test_cast.py``'s instant fixtures."""
    return {
        "name": "S3 Response Instant",
        "card_types": ["Instant"],
        "mana_cost": {"generic": 1},
        "effects": [],
    }


def test_s3_permanent_spell_sits_on_stack_opponent_gets_response_window(
    synthetic_state,
):
    """S3 deliverable (a)+(b), G7 S5a closure-flip: a creature spell
    cast by p0 SITS on the stack (no atomic resolve — the S1/S3
    contract; S5a re-homes the spell hand → the stack-object store so
    ``find_object_zone`` reports ``ZONE_STACK``, byte-Python
    ``card.zone = Zone.STACK``), and p1's response window emits an
    instant-speed CastSpell via `legal_decisions(1)` WHILE the creature
    spell is on the stack. This is the I46 two-pass instant-speed
    emission composing with a non-empty stack — the surface that did
    not exist pre-S1.

    **Byte-equal priority-window model (the verify-first-confirmed
    sequence).** A response window opens for p1 only when priority is
    PASSED to p1 — exactly Python's `simulate.py:priority_loop`: after
    p0's cast (a non-pass action) the loop resets priority to the
    active player (p0, `:282`); p0 then passes (single in-round pass),
    and `:271-273` moves priority to `_next_alive((0+1)%2)` = p1.
    `legal_decisions` correctly bails to bare PassPriority for an
    OFF-priority caller (`state_ops_legal.rs:1199-1201`, byte-faithful
    to Python `legal.py:180-181`); the response emission is gated on
    p1 actually HOLDING priority. So the test models the loop's
    priority hand-off (give_priority_to(1) is the
    `_next_alive`-equivalent the adapter loop / Python loop performs)
    rather than querying p1 off-priority."""
    synthetic_state.set_phase(_PHASE_MAIN1)
    # p1's response instant in hand.
    resp_id = synthetic_state.register_and_inject_object(
        _response_instant_dict(), 1, _ZONE_HAND
    )
    # p0 casts the creature -> StackItem, NOT resolved. The cast-push
    # reset (and the adapter loop's post-non-pass-action reset) put
    # priority on the active player p0 — byte-equal to Python
    # `simulate.py:282`.
    synthetic_state.add_mana(0, "G", 1)
    assert synthetic_state.cast_creature(_P0_ELF_ID, 0) is True
    assert synthetic_state.stack_size() == 1
    assert synthetic_state.is_stack_empty() is False
    assert synthetic_state.find_object_zone(_P0_ELF_ID) == _ZONE_STACK, (
        "S5a contract: the creature spell sits on the stack-object "
        "store (zone == ZONE_STACK, off-hand — byte-Python "
        "card.zone=Zone.STACK), NOT atomic-resolved to the battlefield"
    )
    assert synthetic_state.get_priority_player() == 0, (
        "post-cast priority is the active player (p0) — Python "
        "simulate.py:282 post-non-pass-action reset"
    )
    # Off-priority caller (p1) correctly bails to bare PassPriority —
    # the byte-faithful Python `legal.py:180-181` priority gate. This
    # is NOT the response window yet.
    p1_offpri = synthetic_state.legal_decisions(1)
    assert [a["kind"] for a in p1_offpri] == ["pass_priority"], (
        "off-priority p1 must see ONLY PassPriority (byte-equal to "
        "Python legal.py:180-181); the response window has not opened"
    )

    # The priority loop passes priority to p1 (p0 passes -> Python
    # `simulate.py:271-273` `_next_alive((0+1)%2)`). NOW the response
    # window is open with the permanent spell still on the stack.
    synthetic_state.give_priority_to(1)
    synthetic_state.add_mana(1, "C", 1)
    p1_legal = synthetic_state.legal_decisions(1)
    cast_actions = [a for a in p1_legal if a["kind"] == "cast_spell"]
    assert any(a["card_id"] == resp_id for a in cast_actions), (
        "S3 response window broken: with p1 HOLDING priority, the "
        "opponent's instant-speed CastSpell must be emitted while a "
        "permanent spell is on the stack — the I46 instant-speed pass "
        "must NOT be suppressed by the non-empty stack (it is gated "
        "per-card on is_instant||flash, NOT the sorcery-timing "
        "stack.is_empty() short-circuit at state_ops_legal.rs:1450)"
    )
    # PassPriority is always offered (the opponent may decline to
    # respond — CR 117.3a).
    assert any(a["kind"] == "pass_priority" for a in p1_legal)


def test_s3_response_resolves_lifo_then_permanent_spell_lands(
    synthetic_state,
):
    """S3 deliverable (c), G7 S5a closure-flip: the opponent's
    response goes on TOP of the permanent spell and resolves FIRST
    (LIFO — CR 405.5 / `simulate.py:priority_loop:254-267` resolves
    the TOP item per completed pass round); then the permanent spell
    resolves and the creature lands on the battlefield. The
    nested-window resolution order is byte-equal to Python's stack
    discipline. **S5a baseline move:** while pending, the creature
    spell is on the stack-object store (``zone == ZONE_STACK``,
    off-hand — byte-Python ``card.zone=Zone.STACK``); pre-S5a the S1
    model kept it in the hand Vec."""
    synthetic_state.set_phase(_PHASE_MAIN1)
    resp_id = synthetic_state.register_and_inject_object(
        _response_instant_dict(), 1, _ZONE_HAND
    )
    bf_p0_before = synthetic_state.battlefield_sizes[0]
    gy_p1_before = synthetic_state.graveyard_sizes[1]

    # p0 casts creature (bottom of stack).
    synthetic_state.add_mana(0, "G", 1)
    assert synthetic_state.cast_creature(_P0_ELF_ID, 0) is True
    # p1 responds with the instant (top of stack — LIFO).
    synthetic_state.add_mana(1, "C", 1)
    assert (
        synthetic_state.cast_spell_noncreature(resp_id, 1) is True
    ), "the opponent's instant must cast onto the non-empty stack"
    assert synthetic_state.stack_size() == 2, (
        "nested window: response on TOP of the permanent spell "
        "(stack depth 2)"
    )
    # Creature still pending (NOT prematurely resolved by the response
    # cast) — on the stack-object store, off-hand (byte-Python).
    assert synthetic_state.find_object_zone(_P0_ELF_ID) == _ZONE_STACK
    assert synthetic_state.battlefield_sizes[0] == bf_p0_before

    # Resolve TOP (the response instant) first — LIFO.
    synthetic_state.resolve_top_of_stack()
    assert synthetic_state.stack_size() == 1, (
        "LIFO: the response (top) resolved first, the permanent spell "
        "remains on the stack"
    )
    assert synthetic_state.find_object_zone(resp_id) == _ZONE_GRAVEYARD
    assert synthetic_state.graveyard_sizes[1] == gy_p1_before + 1
    # Permanent spell still pending until ITS resolution — on the
    # stack-object store, off-hand (byte-Python card.zone=STACK).
    assert synthetic_state.find_object_zone(_P0_ELF_ID) == _ZONE_STACK
    assert synthetic_state.battlefield_sizes[0] == bf_p0_before

    # Resolve the permanent spell — the creature lands.
    synthetic_state.resolve_top_of_stack()
    assert synthetic_state.is_stack_empty() is True
    assert (
        synthetic_state.find_object_zone(_P0_ELF_ID) == _ZONE_BATTLEFIELD
    )
    assert synthetic_state.battlefield_sizes[0] == bf_p0_before + 1
    assert synthetic_state.is_summoning_sick(_P0_ELF_ID) is True, (
        "the permanent spell resolved through move_source_post_resolve "
        "(summoning-sick stamped at RESOLUTION, byte-equal to Python's "
        "put_into_battlefield) — NOT at cast time"
    )


def test_s3_post_resolution_priority_resets_to_active_player(
    synthetic_state,
):
    """S3 deliverable (d): after the response window resolves, the
    priority reset lands on the ACTIVE player — byte-equal to Python's
    `simulate.py:priority_loop:266-267`
    (`priority_idx = _next_alive(state, state.active_player_idx)`
    after each resolution). The Rust adapter loop owns this reset
    (`rust_engine_adapter.py:_reset_priority_to_active` at `:444`
    post-resolution / `:511` post-non-pass-action, both targeting
    `_next_alive_idx(active_player_idx)`); the cast-push reset in
    `cast_creature` is redundant, not divergent.

    This pins the *direction* of the reset at the engine boundary:
    the active player (p0) holds priority after the cast (the
    cast-push reset) AND after the resolution — proving the
    engine-side state the adapter loop reads is already byte-aligned
    with Python's post-action invariant (priority == active after a
    non-pass action / a resolution)."""
    synthetic_state.set_phase(_PHASE_MAIN1)
    assert synthetic_state.active_player == 0
    # Hand priority to the NON-active player first, so an accidental
    # missing reset would be detectable.
    synthetic_state.give_priority_to(1)
    assert synthetic_state.get_priority_player() == 1

    synthetic_state.add_mana(0, "G", 1)
    assert synthetic_state.cast_creature(_P0_ELF_ID, 0) is True
    # CR 117.1c / `simulate.py:274-282`: a non-pass action (the cast)
    # resets priority to the active player. The engine-side cast-push
    # reset fires here; the adapter loop's `_reset_priority_to_active`
    # (the byte-equal-to-Python authority) would set the same target.
    assert synthetic_state.get_priority_player() == 0, (
        "post-cast priority must be the active player (p0) — "
        "byte-equal to Python's post-non-pass-action reset "
        "simulate.py:282 `_next_alive(state.active_player_idx)`"
    )
    assert synthetic_state.active_player == 0, (
        "the cast must not perturb active_player (I8: priority and "
        "active are independent fields)"
    )

    # Resolve the permanent spell; CR 117.1c again — priority returns
    # to the active player after the resolution
    # (`simulate.py:266-267`). The synthetic state has no second
    # priority holder change here, so the post-resolution invariant is
    # "priority == active player" — assert it directly.
    synthetic_state.resolve_top_of_stack()
    assert synthetic_state.is_stack_empty() is True
    assert synthetic_state.get_priority_player() == 0, (
        "post-resolution priority must reset to the active player — "
        "byte-equal to Python simulate.py:266-267 "
        "`_next_alive(state.active_player_idx)`"
    )
