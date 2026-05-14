"""Unit tests for :mod:`mtg_bot.parity.trajectory`.

Covers ``setup_matched_game`` happy-path and error/edge cases. The
test_trajectory_parity.py module exercises the broader cross-engine
trajectory behavior; this file focuses on the helper's own surface
(seed-precedence rules, validation, mulligan-not-implemented gate).

Skips when the Rust extension isn't built — same policy as the rest of
the parity test suite.
"""

from __future__ import annotations

import importlib.util

import pytest


pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


def _vanilla_60_deckspec(seed=42, shared_rng_seed=None):
    """Local copy of the test_trajectory_parity helper.

    Kept inline so this file is independently runnable / movable.
    """
    from mtg_bot.parity.cross_engine import CardDef, DeckSpec

    forest = CardDef(name="Forest", card_type="Land", mana_produced=("G",))
    bears = CardDef(
        name="Grizzly Bears",
        card_type="Creature",
        mana_cost_generic=1,
        mana_cost_colored=(("G", 1),),
        power=2,
        toughness=2,
    )
    library = ("Forest",) * 24 + ("Grizzly Bears",) * 36
    return DeckSpec(
        card_defs=(forest, bears),
        p0_library=library,
        p1_library=library,
        shared_rng_seed=shared_rng_seed,
    )


def test_returns_two_states_with_seven_card_hands():
    """Happy path: 60-card spec + ``shared_rng_seed`` returns matched
    states with seven-card hands and 53-card libraries each side."""
    from mtg_bot.parity.trajectory import setup_matched_game

    spec = _vanilla_60_deckspec(shared_rng_seed=42)
    py_state, rust_state = setup_matched_game(spec)
    assert len(py_state.players[0].hand) == 7
    assert len(py_state.players[1].hand) == 7
    assert len(py_state.players[0].library) == 53
    assert len(py_state.players[1].library) == 53
    assert rust_state.hand_sizes == [7, 7]
    assert rust_state.library_sizes == [53, 53]


def test_seed_kwarg_applies_when_deckspec_unset():
    """When the DeckSpec carries no ``shared_rng_seed`` and the caller
    passes ``seed=N``, the helper rebuilds the spec with that seed.
    Equivalent to constructing the DeckSpec with ``shared_rng_seed=N``."""
    from mtg_bot.parity.cross_engine import compare_fields, parity_smoke
    from mtg_bot.parity.cross_engine import build_python_field_view
    from mtg_bot.parity.trajectory import setup_matched_game

    spec_no_seed = _vanilla_60_deckspec()  # shared_rng_seed=None
    spec_with_seed = _vanilla_60_deckspec(shared_rng_seed=42)

    py_a, rust_a = setup_matched_game(spec_no_seed, seed=42)
    py_b, rust_b = setup_matched_game(spec_with_seed)

    ps = parity_smoke()
    # The two setups should produce identical Python hand/library
    # sequences because the seed is the only random input.
    a_view = build_python_field_view(py_a)
    b_view = build_python_field_view(py_b)
    assert a_view["hand_p0"] == b_view["hand_p0"]
    assert a_view["library_p0"] == b_view["library_p0"]
    # And cross-engine parity holds on each.
    assert compare_fields(a_view, ps._build_field_view(rust_a)) == []
    assert compare_fields(b_view, ps._build_field_view(rust_b)) == []


def test_seed_kwarg_does_not_override_existing_shared_rng_seed():
    """When the DeckSpec already pins ``shared_rng_seed``, the
    convenience ``seed=`` kwarg is ignored (the explicit field wins).
    """
    from mtg_bot.parity.cross_engine import build_python_field_view
    from mtg_bot.parity.trajectory import setup_matched_game

    spec = _vanilla_60_deckspec(shared_rng_seed=99)
    # Pass a different ``seed`` — should be ignored because the spec
    # already pins seed=99.
    py_a, _ = setup_matched_game(spec, seed=42)
    py_b, _ = setup_matched_game(spec)  # no seed kwarg
    a_view = build_python_field_view(py_a)
    b_view = build_python_field_view(py_b)
    # Both setups built with seed=99 → identical hands.
    assert a_view["hand_p0"] == b_view["hand_p0"]


def test_mulligans_true_default_agent_is_no_op_keep():
    """Round-14 closure of gap #2: ``mulligans=True`` with no agent
    supplied defaults to a ``target_hand_size=7`` agent that always
    keeps the initial 7. The post-state is byte-equivalent to the
    ``mulligans=False`` path on the same DeckSpec + seed.
    """
    from mtg_bot.parity.trajectory import setup_matched_game
    from mtg_bot.parity.cross_engine import build_python_field_view, parity_smoke

    spec = _vanilla_60_deckspec(shared_rng_seed=42)
    py_a, rust_a = setup_matched_game(spec, mulligans=False)
    py_b, rust_b = setup_matched_game(spec, mulligans=True)

    a_view = build_python_field_view(py_a)
    b_view = build_python_field_view(py_b)
    assert a_view["hand_p0"] == b_view["hand_p0"]
    assert a_view["hand_p1"] == b_view["hand_p1"]
    assert a_view["library_p0"] == b_view["library_p0"]
    assert a_view["library_p1"] == b_view["library_p1"]

    # Post-state is parity-clean on both engines.
    ps = parity_smoke()
    from mtg_bot.parity.cross_engine import compare_fields
    assert compare_fields(b_view, ps._build_field_view(rust_b)) == []


def test_mulligan_agent_with_mulligans_false_rejected():
    """Defensive: passing an agent without mulligans=True is a likely
    caller bug — raise loudly rather than silently ignoring it."""
    from mtg_bot.parity.trajectory import setup_matched_game, MulliganDeterministicAgent

    spec = _vanilla_60_deckspec(shared_rng_seed=42)
    agent = MulliganDeterministicAgent(target_hand_size=6)
    with pytest.raises(ValueError, match="mulligan_agent supplied"):
        setup_matched_game(spec, mulligans=False, mulligan_agent=agent)


def test_mulligans_true_with_non_default_opening_hand_size_rejected():
    """The mulligan path requires opening_hand_size=7 (London rule)."""
    from mtg_bot.parity.trajectory import setup_matched_game

    spec = _vanilla_60_deckspec(shared_rng_seed=42)
    with pytest.raises(ValueError, match="opening_hand_size=7"):
        setup_matched_game(spec, mulligans=True, opening_hand_size=6)


def test_mulligan_agent_invalid_target_hand_size_rejected():
    """Defensive: target_hand_size must be in [0, 7]."""
    from mtg_bot.parity.trajectory import MulliganDeterministicAgent

    with pytest.raises(ValueError, match="target_hand_size must be in"):
        MulliganDeterministicAgent(target_hand_size=8)
    with pytest.raises(ValueError, match="target_hand_size must be in"):
        MulliganDeterministicAgent(target_hand_size=-1)


def test_mulligan_agent_unsupported_bottom_strategy_rejected():
    """Defensive: only bottom_strategy='first' is implemented."""
    from mtg_bot.parity.trajectory import MulliganDeterministicAgent

    with pytest.raises(ValueError, match="bottom_strategy"):
        MulliganDeterministicAgent(bottom_strategy="last")


def test_negative_opening_hand_size_rejected():
    """Defensive: negative hand size is a programming bug, not a
    silently-coerced no-op."""
    from mtg_bot.parity.trajectory import setup_matched_game

    spec = _vanilla_60_deckspec(shared_rng_seed=42)
    with pytest.raises(ValueError, match="opening_hand_size must be >= 0"):
        setup_matched_game(spec, opening_hand_size=-1)


def test_opening_hand_size_zero_skips_draws():
    """``opening_hand_size=0`` matches Phase 5's pre-draw shape — no
    draws fired, hands empty, libraries full."""
    from mtg_bot.parity.trajectory import setup_matched_game

    spec = _vanilla_60_deckspec(shared_rng_seed=42)
    py_state, rust_state = setup_matched_game(spec, opening_hand_size=0)
    assert len(py_state.players[0].hand) == 0
    assert len(py_state.players[1].hand) == 0
    assert len(py_state.players[0].library) == 60
    assert rust_state.hand_sizes == [0, 0]
    assert rust_state.library_sizes == [60, 60]


def test_oversized_opening_hand_rejected():
    """Asking for more cards than the library has surfaces as
    ``ValueError`` at the helper, not as an ``IndexError`` deep in
    the draw loop."""
    from mtg_bot.parity.cross_engine import CardDef, DeckSpec
    from mtg_bot.parity.trajectory import setup_matched_game

    forest = CardDef(name="Forest", card_type="Land", mana_produced=("G",))
    spec = DeckSpec(
        card_defs=(forest,),
        p0_library=("Forest",) * 5,
        p1_library=("Forest",) * 5,
        shared_rng_seed=42,
    )
    with pytest.raises(ValueError, match="smaller than opening_hand_size"):
        setup_matched_game(spec, opening_hand_size=7)


def test_no_seed_no_shuffle_path():
    """With neither ``seed=`` nor ``shared_rng_seed`` set, libraries
    stay in deck-list order (no shuffle on either engine). The path
    still produces parity-clean states."""
    from mtg_bot.parity.cross_engine import CardDef, DeckSpec, compare_fields, parity_smoke
    from mtg_bot.parity.cross_engine import build_python_field_view
    from mtg_bot.parity.trajectory import setup_matched_game

    forest = CardDef(name="Forest", card_type="Land", mana_produced=("G",))
    bears = CardDef(
        name="Grizzly Bears",
        card_type="Creature",
        mana_cost_generic=1,
        mana_cost_colored=(("G", 1),),
        power=2,
        toughness=2,
    )
    spec = DeckSpec(
        card_defs=(forest, bears),
        p0_library=("Forest",) * 7 + ("Grizzly Bears",) * 3,
        p1_library=("Forest",) * 7 + ("Grizzly Bears",) * 3,
    )
    py_state, rust_state = setup_matched_game(spec)
    py_view = build_python_field_view(py_state)
    rust_view = parity_smoke()._build_field_view(rust_state)
    assert compare_fields(py_view, rust_view) == []
    # All seven Forests should be on top of the unshuffled lib → all
    # in the opening hand on both sides.
    assert all(t[0] == "Forest" for t in py_view["hand_p0"])
