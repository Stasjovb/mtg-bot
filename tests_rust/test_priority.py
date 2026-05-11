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
    # Don't add mana — the cast will fail at the pay_mana_cost gate.
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
