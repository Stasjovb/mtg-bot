"""ModalChooseOne envelope — Cycle 1 (cast-time mode binding).

Spec: `docs/SEARCH_LIMITATIONS.md` "Spell-card-bridge — `ModalChooseOne`
envelope is a multi-round substrate effort" entry. This module covers
**Cycle 1** of the 6-slice plan: cast-time mode binding on the Rust
`StackItem`.

**Cycle 1 scope.** Per CR 601.2e, modal spells pick their mode at cast
time (BEFORE total-cost determination at 601.2f). Rust's pre-cycle
substrate (round-28 `Effect::ChooseOneMode { modes: Vec<Effect> }` at
`cards.rs:4296` + `PendingDecision::ChooseModeChoice` at `state.rs:1357`)
exclusively picks at resolve time via the decision-callback queue —
diverging from Python's cast-time pick on
`StackItem.chosen_modes` (`game.py:2342`).

Cycle 1 closes the cast-time half of the substrate:

* New `StackItem.chosen_mode_idx: Option<u8>` field
  (`state.rs:1124-ish`).
* New `StackItem::new_spell_with_targets_and_mode` constructor that
  carries the cast-time-bound mode pick.
* `cast_spell_noncreature` detects the modal shape
  (`Effect::ChooseOneMode` as the first effect) and binds the
  deterministic-first pick `Some(0)` onto the StackItem — mirroring
  Python's `_choose_modes_at_cast` no-agent fallback at
  `actions.py:1222-1223`.
* New `stack_top_chosen_mode_idx()` getter for cross-engine + test
  introspection.

**Cycle 1 does NOT** wire the resolve-arm consumer. The
`Effect::ChooseOneMode` resolve arm in `state_ops_resolve.rs:14832`
still pushes `PendingDecision::ChooseModeChoice` regardless of the
bound mode_idx. That's Cycle 2 (per-mode resolve dispatch). The
cast-time bind ships in isolation here so the substrate can be probed
+ pinned + cross-engine-bridged before the resolve-side widening
lands.

**Cycle 1 also does NOT** widen the `_printing_is_bridge_simple_spell`
admit predicate (Cycle 5) or add a reverse-serializer arm (Cycle 3).
Modal spells stay declined by the admit predicate today — a
substrate-only landing per the SEARCH_LIMITATIONS plan.
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
    """A 0-bf / 0-hand / 0-library state — everything is injected via
    `register_and_inject_object`."""
    import mtg_bot_engine
    return mtg_bot_engine.make_synthetic_state(0, 0, 0)


def _modal_spell_printing_dict(
    name="Synthetic Modal Spell",
    mana_cost=None,
    modes=None,
):
    """Build a registry-dict for a `ChooseOneMode`-wrapped instant.

    The modes default to two untargeted effects (DrawCards / GainLife)
    so cast-time binding can be exercised without also wiring the
    per-mode target-selection slice (Cycle 4 — deferred). Same shape
    `cards.rs::parse_effect`'s `"choose_one_mode"` arm reads at
    `cards.rs:9084` (recursive parse over `modes`).
    """
    if mana_cost is None:
        mana_cost = {"generic": 1}
    if modes is None:
        modes = [
            {"kind": "draw_cards", "count": 1},
            {"kind": "gain_life", "amount": 2},
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


def _plain_instant_printing_dict(name="Plain Draw Instant"):
    """A non-modal instant — first effect is NOT `ChooseOneMode`. The
    cast-time-bind detector must return `None` for this shape (the
    back-compat baseline; every existing non-modal spell stays
    untouched)."""
    return {
        "name": name,
        "mana_cost": {"generic": 1},
        "card_types": ["Instant"],
        "effects": [{"kind": "draw_cards", "count": 1}],
    }


# ---------------------------------------------------------------------------
# Stack getter surface — back-compat baselines
# ---------------------------------------------------------------------------


def test_stack_top_chosen_mode_idx_returns_none_on_empty_stack():
    """The new getter must be safe on an empty stack — same contract
    as the sibling `stack_top_target_id` (returns `None`, no panic).
    """
    _require_engine()
    state = _fresh_state()
    assert state.stack_size() == 0
    assert state.stack_top_chosen_mode_idx() is None


def test_stack_top_chosen_mode_idx_returns_none_for_non_modal_spell():
    """Casting a non-modal instant must leave
    `chosen_mode_idx == None` on the pushed StackItem. Back-compat
    baseline: every existing single-target / untargeted spell cast
    through `cast_spell_noncreature` stays bit-identical to its
    pre-cycle behavior — the field defaults `None`.
    """
    _require_engine()
    state = _fresh_state()
    spell_id = state.register_and_inject_object(
        _plain_instant_printing_dict(), 0, ZONE_HAND,
    )
    state.add_mana(0, "C", 1)
    ok = state.cast_spell_noncreature(spell_id, 0)
    assert ok is True
    assert state.stack_size() == 1
    # Non-modal: no mode bind.
    assert state.stack_top_chosen_mode_idx() is None
    # Sibling target getter is also None (no target on a draw-self
    # spell either).
    assert state.stack_top_target_id() is None


# ---------------------------------------------------------------------------
# Cast-time mode binding — the Cycle 1 surface
# ---------------------------------------------------------------------------


def test_cast_modal_spell_binds_mode_zero_deterministic_first():
    """Casting a modal instant (`ChooseOneMode` as first effect) must
    bind `chosen_mode_idx = Some(0)` onto the StackItem. Mirrors
    Python's `_choose_modes_at_cast` no-agent fallback at
    `actions.py:1222-1223` — `p.agent is None ⇒ return (0,)`.

    Rust's bench + cross-engine harness drive deterministic-first
    agents (the `_PickFirstLegalTargetAgent` campaign convention),
    so the cast-time pick matches Python's no-agent fallback byte-
    equal.
    """
    _require_engine()
    state = _fresh_state()
    spell_id = state.register_and_inject_object(
        _modal_spell_printing_dict(), 0, ZONE_HAND,
    )
    state.add_mana(0, "C", 1)
    ok = state.cast_spell_noncreature(spell_id, 0)
    assert ok is True
    assert state.stack_size() == 1
    # Cast-time bind: deterministic-first pick is mode 0.
    assert state.stack_top_chosen_mode_idx() == 0


def test_cast_modal_spell_with_three_modes_binds_first():
    """A 3-mode `ChooseOneMode` still binds index 0 — the
    deterministic-first pick is index-based and stable across mode
    count (Python's `_choose_modes_at_cast` returns `(0,)` regardless
    of `len(modes)`).
    """
    _require_engine()
    state = _fresh_state()
    spell_id = state.register_and_inject_object(
        _modal_spell_printing_dict(
            modes=[
                {"kind": "draw_cards", "count": 1},
                {"kind": "gain_life", "amount": 2},
                {"kind": "draw_cards", "count": 2},
            ],
        ),
        0, ZONE_HAND,
    )
    state.add_mana(0, "C", 1)
    ok = state.cast_spell_noncreature(spell_id, 0)
    assert ok is True
    assert state.stack_top_chosen_mode_idx() == 0


def test_cast_modal_spell_failed_cast_no_mode_bind():
    """A modal spell whose cast FAILS (insufficient mana) must NOT
    push a StackItem AND must NOT leak a mode bind. Transactional-
    shape contract: no mutation on the failed cast.
    """
    _require_engine()
    state = _fresh_state()
    spell_id = state.register_and_inject_object(
        _modal_spell_printing_dict(), 0, ZONE_HAND,
    )
    # No mana added — cast must fail.
    ok = state.cast_spell_noncreature(spell_id, 0)
    assert ok is False
    assert state.stack_size() == 0
    assert state.stack_top_chosen_mode_idx() is None


# ---------------------------------------------------------------------------
# Cast-time pick is visible across the cast → pre-resolve window
# ---------------------------------------------------------------------------


def test_cast_time_mode_idx_persists_until_resolve():
    """**Cycle 1 pin: the cast-time bind is durable.** Between cast
    and resolve, the StackItem's `chosen_mode_idx` stays readable
    via `stack_top_chosen_mode_idx`. No intermediate priority pass
    or SBA tick wipes it. This is the substrate's contract: a
    multi-step driver (declare attackers → resolve combat → resolve
    spell) reads the same bound mode on the way out.
    """
    _require_engine()
    state = _fresh_state()
    spell_id = state.register_and_inject_object(
        _modal_spell_printing_dict(), 0, ZONE_HAND,
    )
    state.add_mana(0, "C", 1)
    ok = state.cast_spell_noncreature(spell_id, 0)
    assert ok is True
    # Pre-resolve: no pending decision yet (the decision is pushed
    # DURING resolve, not at cast time — modes are picked at cast,
    # the resolve arm replays the pick).
    assert state.pending_decisions() == []
    # The cast-time bind is durable across an SBA tick.
    state.apply_sbas()
    assert state.stack_top_chosen_mode_idx() == 0


# ---------------------------------------------------------------------------
# Direct constructor exercise — for harness / synthetic-test callers
# ---------------------------------------------------------------------------


def test_push_to_stack_with_target_does_not_bind_mode_idx():
    """The synthetic `push_to_stack_with_target` helper
    (`state_ops_stack.rs:106-118`) routes through
    `new_spell_with_targets` (target-only — NO mode bind). Synthetic
    callers that want to seed both target AND mode would need a
    new helper; today none do (the production binding is
    `cast_spell_noncreature`-only).
    """
    _require_engine()
    state = _fresh_state()
    # Seed a battlefield creature so target binding has something to
    # point at.
    bear_id = state.register_and_inject_object(
        {
            "name": "Wild Bear",
            "mana_cost": {"generic": 1, "G": 1},
            "card_types": ["Creature"],
            "subtypes": ["Bear"],
            "power": 2,
            "toughness": 2,
        },
        0, ZONE_BATTLEFIELD,
    )
    # Inject a dummy spell object on the hand so its id is a valid
    # source for the synthetic push.
    spell_id = state.register_and_inject_object(
        _plain_instant_printing_dict(), 0, ZONE_HAND,
    )
    state.push_to_stack_with_target(spell_id, 0, bear_id)
    assert state.stack_size() == 1
    assert state.stack_top_target_id() == bear_id
    # Cycle 1 default: synthetic push does NOT seed mode bind.
    assert state.stack_top_chosen_mode_idx() is None
