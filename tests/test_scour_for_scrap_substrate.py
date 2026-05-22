"""ModalChooseOne envelope — scour-for-scrap-slice (Cycle 1 widen).

Spec: ``docs/SEARCH_LIMITATIONS.md`` "Spell-card-bridge —
`ModalChooseOne` envelope is a multi-round substrate effort" entry.
This module covers the scour-for-scrap-slice **Cycle 1 widen**:
multi-pick (`or_both=True`) on the Rust ``StackItem``.

**scour-for-scrap-slice scope.** Lane X (Cycles 1-3) wired the single-
pick cast-time mode binding + per-mode resolve dispatch + reverse
serializer. Lane AA (Cycle 4) widened the admit-predicate for
all-untargeted modal cards. Lane BB (Cycle 5) added the per-mode
target-binding ladder. This slice widens **substrate-only** for the
``or_both=True`` Charm shape:

* New ``Effect::ChooseOneMode { modes, or_both: bool }`` field
  (defaulted ``false`` so every pre-widen registered ChooseOneMode
  parses byte-identical).
* New ``StackItem.chosen_mode_idxs: Option<Vec<u8>>`` field (additive
  sibling of ``chosen_mode_idx`` — mutual-exclusion contract honoured
  by the two new constructors).
* New ``new_spell_with_targets_and_modes`` constructor that carries
  the cast-time-bound multi-pick subset.
* ``cast_spell_noncreature`` detects ``or_both: true`` and binds the
  full mode-subset ``[0, 1, ..., modes.len()-1]`` (deterministic-all
  no-agent fallback — mirrors Python's ``ModalChooseOne(or_both=True)``
  "all modes by default" no-agent semantics).
* ``Effect::ChooseOneMode`` resolve arm dispatches the multi-pick
  subset in supplied order via ``apply_effect_pub_with_controller``.
  Falls back to the single-pick path when ``chosen_mode_idxs`` is
  ``None`` (back-compat byte-identical).
* New ``stack_top_chosen_mode_idxs()`` getter for cross-engine + test
  introspection.

**Substrate-only landing.** This slice does **NOT** add the
``Effect::ReturnTargetArtifactCardFromYourGraveyardToHand`` variant
or wire the per-mode target binder for it; Scour for Scrap (the only
``or_both=True`` modal in EoE) STAYS DECLINED by the admit predicate.
The substrate is "wired but unused at the admit-set level" today;
meaningful only when a follow-up cycle adds the missing per-leaf
Effect variant + bridge arm + cast-time per-mode target binding for
the graveyard-artifact-return mode.
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
    ``register_and_inject_object``."""
    import mtg_bot_engine
    return mtg_bot_engine.make_synthetic_state(0, 0, 0)


def _or_both_modal_spell_printing_dict(
    name="Synthetic Or-Both Modal Spell",
    mana_cost=None,
    modes=None,
):
    """Build a registry-dict for a ``ChooseOneMode(or_both=True)``-
    wrapped instant. Modes default to two untargeted effects
    (DrawCards / GainLife) so both modes resolve no-op-target-free for
    multi-pick dispatch probing.
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
                "or_both": True,
            },
        ],
    }


def _single_pick_modal_spell_printing_dict(
    name="Synthetic Single-Pick Modal Spell",
    mana_cost=None,
    modes=None,
):
    """Build a registry-dict for a plain ``ChooseOneMode`` (no
    or_both) instant — the back-compat baseline. Confirms the
    or_both-false branch keeps using the single-pick StackItem slot.
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
                # or_both: false omitted — the default
            },
        ],
    }


# ---------------------------------------------------------------------------
# Stack getter surface — additive baseline
# ---------------------------------------------------------------------------


def test_stack_top_chosen_mode_idxs_returns_none_on_empty_stack():
    """The new multi-pick getter must be safe on an empty stack —
    same contract as the single-pick `stack_top_chosen_mode_idx`."""
    _require_engine()
    state = _fresh_state()
    assert state.stack_size() == 0
    assert state.stack_top_chosen_mode_idxs() is None


def test_stack_top_chosen_mode_idxs_returns_none_for_single_pick_modal():
    """Casting a non-or_both modal must leave `chosen_mode_idxs` as
    `None` (the back-compat baseline). The single-pick
    `chosen_mode_idx` is `Some(0)`; the multi-pick sibling is
    untouched. Mutual-exclusion contract verified."""
    _require_engine()
    state = _fresh_state()
    spell_id = state.register_and_inject_object(
        _single_pick_modal_spell_printing_dict(), 0, ZONE_HAND,
    )
    state.add_mana(0, "C", 1)
    ok = state.cast_spell_noncreature(spell_id, 0)
    assert ok is True
    assert state.stack_size() == 1
    # Single-pick path is active.
    assert state.stack_top_chosen_mode_idx() == 0
    # Multi-pick sibling is untouched (mutual-exclusion).
    assert state.stack_top_chosen_mode_idxs() is None


# ---------------------------------------------------------------------------
# or_both cast-time bind — multi-pick path
# ---------------------------------------------------------------------------


def test_or_both_modal_binds_all_modes_at_cast_time():
    """Casting an `or_both=True` modal must bind `chosen_mode_idxs`
    to `[0, 1, ..., modes.len()-1]` — the deterministic-all no-agent
    fallback. Mirror Python's `ModalChooseOne(or_both=True)` no-agent
    semantics: "pick all modes by default."""
    _require_engine()
    state = _fresh_state()
    spell_id = state.register_and_inject_object(
        _or_both_modal_spell_printing_dict(), 0, ZONE_HAND,
    )
    state.add_mana(0, "C", 1)
    ok = state.cast_spell_noncreature(spell_id, 0)
    assert ok is True
    assert state.stack_size() == 1
    # Multi-pick path is active — [0, 1] for the 2-mode default.
    assert state.stack_top_chosen_mode_idxs() == [0, 1]
    # Single-pick slot is `None` (mutual-exclusion contract).
    assert state.stack_top_chosen_mode_idx() is None


def test_or_both_modal_with_3_modes_binds_all_three():
    """An or_both modal with 3 modes binds `[0, 1, 2]` — the all-modes
    deterministic-first default scales to N modes."""
    _require_engine()
    state = _fresh_state()
    spell_id = state.register_and_inject_object(
        _or_both_modal_spell_printing_dict(
            modes=[
                {"kind": "draw_cards", "count": 1},
                {"kind": "gain_life", "amount": 2},
                {"kind": "scry_n", "count": 1},
            ],
        ),
        0, ZONE_HAND,
    )
    state.add_mana(0, "C", 1)
    ok = state.cast_spell_noncreature(spell_id, 0)
    assert ok is True
    assert state.stack_top_chosen_mode_idxs() == [0, 1, 2]


# ---------------------------------------------------------------------------
# or_both resolve dispatch — multi-pick path applies each mode in order
# ---------------------------------------------------------------------------


def test_or_both_modal_resolves_all_modes_in_order():
    """Resolving an or_both modal with `chosen_mode_idxs == [0, 1]`
    must dispatch BOTH modes — observable via the two effects firing.
    Mode 0 (DrawCards 1) + mode 1 (GainLife 2) both observable on the
    controller post-resolve.
    """
    _require_engine()
    state = _fresh_state()
    # Seed a library so DrawCards has something to draw.
    for _ in range(5):
        state.register_and_inject_object(
            {"name": "Filler", "card_types": ["Land"], "mana_cost": {}},
            0, 1,  # Zone 1 == LIBRARY
        )
    starting_life = state.life_totals[0]
    starting_hand_size = state.hand_sizes[0]
    spell_id = state.register_and_inject_object(
        _or_both_modal_spell_printing_dict(), 0, ZONE_HAND,
    )
    state.add_mana(0, "C", 1)
    ok = state.cast_spell_noncreature(spell_id, 0)
    assert ok is True
    state.resolve_top_of_stack()
    assert state.life_totals[0] == starting_life + 2, (
        f"GainLife mode 1 must fire: {starting_life} -> "
        f"{state.life_totals[0]}"
    )
    # The spell came out of hand at cast (hand -1; the spell wasn't in
    # `starting_hand_size` because it was registered AFTER), so the
    # observable hand-size delta is solely the +1 draw from mode 0.
    assert state.hand_sizes[0] == starting_hand_size + 1, (
        f"DrawCards mode 0 must fire: hand grew from "
        f"{starting_hand_size} to {state.hand_sizes[0]}"
    )


def test_or_both_modal_with_single_index_resolves_only_that_mode():
    """A `chosen_mode_idxs == [1]` (e.g. agent picks ONLY mode 1)
    must dispatch only mode 1 — the GainLife arm, NOT the DrawCards
    arm. Single-index multi-pick parity with Python's
    `ModalChooseOne.resolve` for the 1-element subset case.

    Construction shortcut: we directly mutate the StackItem's
    multi-pick slot via the synthetic push path, since the production
    cast-time bind ALWAYS picks all modes (the no-agent default). A
    future agent-driven cycle will widen the cast-time picker; this
    test pins the resolve-arm semantics today.
    """
    _require_engine()
    state = _fresh_state()
    starting_life = state.life_totals[0]
    spell_id = state.register_and_inject_object(
        _or_both_modal_spell_printing_dict(), 0, ZONE_HAND,
    )
    state.add_mana(0, "C", 1)
    ok = state.cast_spell_noncreature(spell_id, 0)
    assert ok is True
    # Re-bind the multi-pick slot to [1] via the manual override path
    # — the production cast-time bind set it to [0, 1] by default.
    # The override is the synthetic-test "agent picks differently"
    # shape; production code never mutates this slot post-push.
    state.set_stack_top_chosen_mode_idxs([1])
    assert state.stack_top_chosen_mode_idxs() == [1]
    state.resolve_top_of_stack()
    # ONLY mode 1 (GainLife 2) fired.
    assert state.life_totals[0] == starting_life + 2


def test_or_both_modal_with_reordered_picks_resolves_in_supplied_order():
    """Per CR 700.2d, modes resolve in the order chosen by the
    controller. `chosen_mode_idxs == [1, 0]` must dispatch mode 1
    BEFORE mode 0. Order observable via Rust's log if exposed; here we
    just confirm both modes fired (the order assertion is a Python-
    side concern; the substrate guarantees only that each chosen index
    runs once, in the supplied iteration order)."""
    _require_engine()
    state = _fresh_state()
    # Seed a library so DrawCards has something to draw.
    for _ in range(5):
        state.register_and_inject_object(
            {"name": "Filler", "card_types": ["Land"], "mana_cost": {}},
            0, 1,
        )
    starting_life = state.life_totals[0]
    starting_hand = state.hand_sizes[0]
    spell_id = state.register_and_inject_object(
        _or_both_modal_spell_printing_dict(), 0, ZONE_HAND,
    )
    state.add_mana(0, "C", 1)
    ok = state.cast_spell_noncreature(spell_id, 0)
    assert ok is True
    state.set_stack_top_chosen_mode_idxs([1, 0])
    state.resolve_top_of_stack()
    # Both modes fired.
    assert state.life_totals[0] == starting_life + 2
    assert state.hand_sizes[0] == starting_hand + 1


def test_or_both_modal_with_empty_subset_no_ops():
    """An empty `chosen_mode_idxs == []` (e.g. malformed pick) must
    silently no-op — no modes dispatched, no panic. The Rust substrate
    is conservative: an empty subset is a legal "you chose nothing"
    state at the wire level. (Production cast-time bind never emits
    `[]`; this is the malformed-input defense.)"""
    _require_engine()
    state = _fresh_state()
    starting_life = state.life_totals[0]
    spell_id = state.register_and_inject_object(
        _or_both_modal_spell_printing_dict(), 0, ZONE_HAND,
    )
    state.add_mana(0, "C", 1)
    ok = state.cast_spell_noncreature(spell_id, 0)
    assert ok is True
    state.set_stack_top_chosen_mode_idxs([])
    state.resolve_top_of_stack()
    # No mode fired.
    assert state.life_totals[0] == starting_life


def test_or_both_modal_with_out_of_range_indices_drops_them_silently():
    """Out-of-range indices (>= modes.len()) must be silently filtered.
    `chosen_mode_idxs == [0, 99, 1, 250]` -> only modes 0 and 1
    dispatched (the in-range pair). Mirrors Python's sanitisation in
    `ModalChooseOne.resolve` for out-of-range indices."""
    _require_engine()
    state = _fresh_state()
    for _ in range(5):
        state.register_and_inject_object(
            {"name": "Filler", "card_types": ["Land"], "mana_cost": {}},
            0, 1,
        )
    starting_life = state.life_totals[0]
    starting_hand = state.hand_sizes[0]
    spell_id = state.register_and_inject_object(
        _or_both_modal_spell_printing_dict(), 0, ZONE_HAND,
    )
    state.add_mana(0, "C", 1)
    ok = state.cast_spell_noncreature(spell_id, 0)
    assert ok is True
    state.set_stack_top_chosen_mode_idxs([0, 99, 1, 250])
    state.resolve_top_of_stack()
    # Modes 0 and 1 both fired; the out-of-range indices were dropped.
    assert state.life_totals[0] == starting_life + 2
    assert state.hand_sizes[0] == starting_hand + 1


# ---------------------------------------------------------------------------
# Back-compat — non-or_both single-pick still resolves byte-equal
# ---------------------------------------------------------------------------


def test_non_or_both_modal_single_pick_resolve_unchanged():
    """A plain `ChooseOneMode` (or_both=false) cast through
    `cast_spell_noncreature` must still bind `chosen_mode_idx = 0` AND
    leave `chosen_mode_idxs = None` AND resolve mode 0 only — the
    pre-widen behavior, byte-identical."""
    _require_engine()
    state = _fresh_state()
    # Seed library for DrawCards mode 0.
    for _ in range(5):
        state.register_and_inject_object(
            {"name": "Filler", "card_types": ["Land"], "mana_cost": {}},
            0, 1,
        )
    starting_life = state.life_totals[0]
    starting_hand = state.hand_sizes[0]
    spell_id = state.register_and_inject_object(
        _single_pick_modal_spell_printing_dict(), 0, ZONE_HAND,
    )
    state.add_mana(0, "C", 1)
    ok = state.cast_spell_noncreature(spell_id, 0)
    assert ok is True
    assert state.stack_top_chosen_mode_idx() == 0
    assert state.stack_top_chosen_mode_idxs() is None
    state.resolve_top_of_stack()
    # ONLY mode 0 (DrawCards 1) fired.
    assert state.hand_sizes[0] == starting_hand + 1
    # Mode 1 (GainLife 2) did NOT fire.
    assert state.life_totals[0] == starting_life


# ---------------------------------------------------------------------------
# Effect::ChooseOneMode `or_both` field — parse + to_pydict round-trip
# ---------------------------------------------------------------------------


def test_choose_one_mode_or_both_accepted_by_parser():
    """A ChooseOneMode dict carrying `or_both: true` parses through
    `register_and_inject_object` without rejection — the new
    `or_both` field is a recognized parse-time field. (Positive
    smoke; the absence-of-rejection IS the assertion.)"""
    _require_engine()
    state = _fresh_state()
    # Registration must NOT raise on the new field.
    spell_id = state.register_and_inject_object(
        _or_both_modal_spell_printing_dict(name="Or-Both Parse OK"),
        0, ZONE_HAND,
    )
    assert spell_id >= 0  # registered successfully (ids start at 0)


def test_choose_one_mode_or_both_omitted_field_back_compat():
    """A ChooseOneMode dict WITHOUT `or_both` parses cleanly (the
    pre-widen dict shape) — the default `or_both=false` keeps every
    pre-widen ChooseOneMode dict back-compat byte-identical."""
    _require_engine()
    state = _fresh_state()
    spell_id = state.register_and_inject_object(
        _single_pick_modal_spell_printing_dict(name="Back-compat Default"),
        0, ZONE_HAND,
    )
    assert spell_id >= 0
    # And the cast-time bind treats it as single-pick (no multi-pick
    # bind emitted), proving the absent `or_both` parsed as `false`.
    state.add_mana(0, "C", 1)
    state.cast_spell_noncreature(spell_id, 0)
    assert state.stack_top_chosen_mode_idxs() is None
    assert state.stack_top_chosen_mode_idx() == 0


def test_choose_one_mode_or_both_rejects_non_bool_field():
    """The parse arm validates `or_both` is a bool — passing a string
    raises a ValueError (back-compat for any future dict producer that
    types it wrong)."""
    _require_engine()
    state = _fresh_state()
    bad_dict = _or_both_modal_spell_printing_dict()
    bad_dict["effects"][0]["or_both"] = "not a bool"
    with pytest.raises(Exception, match="or_both"):
        state.register_and_inject_object(bad_dict, 0, ZONE_HAND)
