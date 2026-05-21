"""ModalChooseOne envelope — Cycle 2 (per-mode resolve dispatch).

Spec: `docs/SEARCH_LIMITATIONS.md` "Spell-card-bridge — `ModalChooseOne`
envelope is a multi-round substrate effort" entry. This module covers
**Cycle 2** of the 6-slice plan: at resolve time, when the
`Effect::ChooseOneMode` arm sees a cast-time-bound mode index
(`state.current_resolve_chosen_mode_idx == Some(idx)`), dispatch
directly to `modes[idx]` instead of pushing
`PendingDecision::ChooseModeChoice`.

**Cycle 2 scope.** Closes the resolve-side half of the cast-time mode
binding substrate. The resolve arm at
`state_ops_resolve.rs::Effect::ChooseOneMode` now reads the transient
`current_resolve_chosen_mode_idx` slot (swapped in by
`resolve_top_of_stack` / `_pause` from `StackItem.chosen_mode_idx`):

* `Some(idx)` ⇒ apply `modes[idx]` directly via
  `apply_effect_pub_with_controller`. No PendingDecision is pushed.
  Mirrors Python's `ModalChooseOne.resolve` cast-time-replay branch
  at `combinators.py:1213-1215`.
* `None` ⇒ the pre-cycle `PendingDecision::ChooseModeChoice` push
  stays intact. Back-compat path for plain `push_to_stack` (no
  cast-time bind) + future nested-as-trigger ChooseOneMode pushes.

**Cycle 2 does NOT** widen the `_printing_is_bridge_simple_spell`
admit predicate (Cycle 5) or add a reverse-serializer arm (Cycle 3).
Modal spells stay declined by the admit predicate today — the
substrate-only landing per the SEARCH_LIMITATIONS plan.

**Honest probe pattern.** Tests drive the cast → resolve flow on
synthetic modal printings whose modes are observable side-effects
(GainLife — touching `life_totals`). Cross-engine byte-equality
probes are deferred to Cycle 6 because the admit predicate widening
(Cycle 5) must land first.
"""

from __future__ import annotations

import importlib

import pytest

ZONE_HAND = 0
ZONE_BATTLEFIELD = 2


def _require_engine():
    if importlib.util.find_spec("mtg_bot_engine") is None:
        pytest.skip("mtg_bot_engine PyO3 extension not installed")


def _fresh_state():
    import mtg_bot_engine
    return mtg_bot_engine.make_synthetic_state(0, 0, 0)


def _modal_spell_printing_dict(
    name="Synthetic Modal Spell",
    mana_cost=None,
    modes=None,
):
    """Build a registry-dict for a `ChooseOneMode`-wrapped instant
    with two untargeted observable side-effect modes by default."""
    if mana_cost is None:
        mana_cost = {"generic": 1}
    if modes is None:
        modes = [
            {"kind": "gain_life", "amount": 3},
            {"kind": "gain_life", "amount": 7},
        ]
    return {
        "name": name,
        "mana_cost": mana_cost,
        "card_types": ["Instant"],
        "effects": [
            {
                "kind": "choose_one_mode",
                "modes": modes,
            },
        ],
    }


def _spell_with_explicit_modes(mode_dicts):
    return _modal_spell_printing_dict(modes=mode_dicts)


# ---------------------------------------------------------------------------
# Cast-time-bound dispatch: mode 0 applied directly, no PendingDecision
# ---------------------------------------------------------------------------


def test_resolve_cast_time_bound_dispatches_mode_zero_directly():
    """A modal spell cast through `cast_spell_noncreature` binds
    `chosen_mode_idx = Some(0)`. At resolve, the arm dispatches
    directly to `modes[0]` via `apply_effect_pub_with_controller`
    and pushes NO `PendingDecision::ChooseModeChoice`.

    Concrete check: mode 0 is GainLife(3) — life jumps +3 with no
    intermediate decision. Mode 1 is GainLife(7) — never applied.
    """
    _require_engine()
    state = _fresh_state()
    spell_id = state.register_and_inject_object(
        _spell_with_explicit_modes([
            {"kind": "gain_life", "amount": 3},
            {"kind": "gain_life", "amount": 7},
        ]),
        0, ZONE_HAND,
    )
    state.add_mana(0, "C", 1)
    life_before = state.life_totals[0]
    ok = state.cast_spell_noncreature(spell_id, 0)
    assert ok is True
    assert state.stack_top_chosen_mode_idx() == 0
    state.resolve_top_of_stack()
    # Mode 0 applied → +3 life. No PendingDecision left over.
    assert state.life_totals[0] == life_before + 3
    assert state.pending_decisions() == []
    # Stack drained (spell resolved).
    assert state.stack_size() == 0


def test_resolve_cast_time_bound_picks_mode_zero_not_mode_one():
    """Symmetric check: mode 0 is the no-op shape (GainLife 0), mode
    1 is the observable shape (GainLife 5). After cast → resolve,
    life is UNCHANGED — the bound mode is 0, mode 1 is NOT applied.
    This pins the directionality of the dispatch (we picked mode 0,
    not mode 1).
    """
    _require_engine()
    state = _fresh_state()
    spell_id = state.register_and_inject_object(
        _spell_with_explicit_modes([
            {"kind": "gain_life", "amount": 0},
            {"kind": "gain_life", "amount": 5},
        ]),
        0, ZONE_HAND,
    )
    state.add_mana(0, "C", 1)
    life_before = state.life_totals[0]
    ok = state.cast_spell_noncreature(spell_id, 0)
    assert ok is True
    state.resolve_top_of_stack()
    # Mode 0 (GainLife 0) → no change. Mode 1 was NOT applied.
    assert state.life_totals[0] == life_before
    assert state.pending_decisions() == []


# ---------------------------------------------------------------------------
# Fallback path: no cast-time bind → resolve-time PendingDecision intact
# ---------------------------------------------------------------------------


def test_resolve_without_cast_time_bind_pushes_pending_decision():
    """A modal-printing pushed via the bare `push_to_stack(...)`
    helper (NOT `cast_spell_noncreature`) leaves
    `chosen_mode_idx = None` on the StackItem. The resolver's
    `current_resolve_chosen_mode_idx` swap reads `None`, so the
    resolve arm falls back to the pre-cycle
    `PendingDecision::ChooseModeChoice` push.

    This pins the back-compat path: any non-cast-time-bound
    invocation of `Effect::ChooseOneMode` still routes through the
    decision-callback substrate exactly like the pre-Cycle-1 era.
    """
    _require_engine()
    state = _fresh_state()
    spell_id = state.register_and_inject_object(
        _modal_spell_printing_dict(), 0, ZONE_HAND,
    )
    # Push WITHOUT going through cast_spell_noncreature — no cast-
    # time mode bind.
    state.push_to_stack(spell_id, 0)
    assert state.stack_top_chosen_mode_idx() is None
    # Use the _pause variant so auto-resolve doesn't drain the
    # decision before we can observe it.
    state.resolve_top_of_stack_pause()
    pds = state.pending_decisions()
    assert len(pds) == 1
    assert pds[0]["kind"] == "ChooseModeChoice"
    assert pds[0]["source_obj_id"] == spell_id


# ---------------------------------------------------------------------------
# Auto-grow: a real-EoE-shaped modal spell resolves correctly
# ---------------------------------------------------------------------------


def test_resolve_three_mode_spell_dispatches_mode_zero():
    """A 3-mode modal spell cast through the production path resolves
    via mode 0 directly. The dispatch picks the bound idx, ignores
    the count of modes — same behavior as 2-mode but with a third
    option that must NOT be applied.
    """
    _require_engine()
    state = _fresh_state()
    spell_id = state.register_and_inject_object(
        _spell_with_explicit_modes([
            {"kind": "gain_life", "amount": 1},   # mode 0 — bound
            {"kind": "gain_life", "amount": 10},  # mode 1 — never
            {"kind": "gain_life", "amount": 100}, # mode 2 — never
        ]),
        0, ZONE_HAND,
    )
    state.add_mana(0, "C", 1)
    life_before = state.life_totals[0]
    ok = state.cast_spell_noncreature(spell_id, 0)
    assert ok is True
    assert state.stack_top_chosen_mode_idx() == 0
    state.resolve_top_of_stack()
    # Only mode 0 (+1 life) applied; modes 1 + 2 are NOT applied.
    assert state.life_totals[0] == life_before + 1


# ---------------------------------------------------------------------------
# Save/restore discipline: transient slot bracketed by resolver
# ---------------------------------------------------------------------------


def test_transient_mode_idx_restored_after_resolve():
    """`current_resolve_chosen_mode_idx` is save/set/restore-bracketed
    by the resolver — observable as `None` AFTER resolve completes.
    Driven by: cast + resolve a modal spell (sets + restores the
    transient slot via the resolver's swap), then push a NEW
    non-cast-time-bound modal item and resolve it through `_pause`.
    The second resolution must route via the FALLBACK PendingDecision
    path — proving the transient slot was restored to `None` (i.e.
    no leak across the resolution boundary, parallel to the existing
    `saved_target` discipline).
    """
    _require_engine()
    state = _fresh_state()
    # First spell: cast + resolve to exercise the resolver's swap.
    spell_a = state.register_and_inject_object(
        _modal_spell_printing_dict(), 0, ZONE_HAND,
    )
    state.add_mana(0, "C", 1)
    state.cast_spell_noncreature(spell_a, 0)
    state.resolve_top_of_stack()
    assert state.pending_decisions() == []
    # Second spell: plain push, NO cast-time bind. If the resolver
    # leaked the previous Some(0) bind, this would dispatch via the
    # cast-time-bind path; the correct restored-to-None state pushes
    # the PendingDecision instead.
    spell_b = state.register_and_inject_object(
        _modal_spell_printing_dict(name="Spell B"), 0, ZONE_HAND,
    )
    state.push_to_stack(spell_b, 0)
    state.resolve_top_of_stack_pause()
    pds = state.pending_decisions()
    assert len(pds) == 1
    assert pds[0]["kind"] == "ChooseModeChoice"
    assert pds[0]["source_obj_id"] == spell_b
