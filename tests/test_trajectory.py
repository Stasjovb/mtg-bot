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


# ---------------------------------------------------------------------------
# Phase 6 round-16 (closes infrastructure gap #3): RealGameCombatAgent
# unit tests.
# ---------------------------------------------------------------------------


def test_combat_agent_invalid_strategy_rejected():
    """Defensive: only the documented strategies are supported."""
    from mtg_bot.parity.trajectory import RealGameCombatAgent

    with pytest.raises(ValueError, match="strategy="):
        RealGameCombatAgent(strategy="charge_blindly")


def test_combat_agent_default_strategy_is_attack_all():
    """Default strategy is `attack_all`."""
    from mtg_bot.parity.trajectory import RealGameCombatAgent

    agent = RealGameCombatAgent()
    assert agent.strategy == "attack_all"


def test_combat_agent_no_attack_picks_no_attackers():
    """``"no_attack"`` returns ``[]`` regardless of bf state."""
    from mtg_bot.parity.trajectory import (
        RealGameCombatAgent,
        setup_matched_game,
    )

    spec = _vanilla_60_deckspec(shared_rng_seed=42)
    py_state, _ = setup_matched_game(spec)
    agent = RealGameCombatAgent(strategy="no_attack")
    assert agent.pick_attackers(py_state) == []
    assert agent.pick_blocks(py_state) == []


def test_combat_agent_attack_all_picks_no_blocks():
    """``"attack_all"`` returns blocks=[] even when defender has
    creatures (the strategy doesn't block)."""
    from mtg_bot.parity.trajectory import (
        RealGameCombatAgent,
        setup_matched_game,
    )

    spec = _vanilla_60_deckspec(shared_rng_seed=42)
    py_state, _ = setup_matched_game(spec)
    agent = RealGameCombatAgent(strategy="attack_all")
    # Empty bf — no attackers, no blocks.
    assert agent.pick_attackers(py_state) == []
    assert agent.pick_blocks(py_state) == []


def test_combat_agent_drive_combat_phase_wrong_step_rejected():
    """``drive_combat_phase`` requires step=DECLARE_ATTACKERS."""
    from mtg_bot.parity.trajectory import (
        RealGameCombatAgent,
        drive_combat_phase,
        setup_matched_game,
    )

    spec = _vanilla_60_deckspec(shared_rng_seed=42)
    py_state, rust_state = setup_matched_game(spec)
    agent = RealGameCombatAgent(strategy="no_attack")
    # Fresh state is at step=UNTAP, not DECLARE_ATTACKERS.
    with pytest.raises(ValueError, match="DECLARE_ATTACKERS"):
        drive_combat_phase(py_state, rust_state, agent)


def test_combat_agent_attack_all_block_smallest_assignment_pairing():
    """`pick_blocks` for `attack_all_block_smallest` pairs each attacker
    with the smallest available blocker, one blocker per attacker.

    Constructs an in-memory bf with two attacking creatures (p0) and
    two blockers (p1, different sizes); asserts the small blocker
    pairs with the lower-id attacker, the bigger blocker with the
    higher-id attacker.
    """
    from mtg_bot.parity.trajectory import (
        RealGameCombatAgent,
        setup_matched_game,
    )

    spec = _vanilla_60_deckspec(shared_rng_seed=42)
    py_state, _ = setup_matched_game(spec)

    # Build a synthetic bf: two p0 attackers (Bears 2/2) + two p1
    # blockers (Bears 2/2 + a 3/3 Big Bear). Use the Python new_object
    # path directly.
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.game import Zone

    bears = CardPrinting(
        name="Grizzly Bears",
        mana_cost_str="",
        mana_cost=ManaCost(),
        type_line="Creature — Bear",
        supertypes=(),
        card_types=("Creature",),
        subtypes=("Bear",),
        power=2,
        toughness=2,
        produces=frozenset(),
        keywords=frozenset(),
    )
    big_bear = CardPrinting(
        name="Big Bear",
        mana_cost_str="",
        mana_cost=ManaCost(),
        type_line="Creature — Bear",
        supertypes=(),
        card_types=("Creature",),
        subtypes=("Bear",),
        power=3,
        toughness=3,
        produces=frozenset(),
        keywords=frozenset(),
    )

    def _add_creature(state, printing, controller):
        obj = state.new_object(printing, owner_id=controller, zone=Zone.BATTLEFIELD)
        obj.summoning_sick = False
        obj.tapped = False
        obj.attacking = False
        obj.blocking = False
        obj.etb_timestamp = state.next_timestamp
        state.next_timestamp += 1
        state.battlefield.append(obj)
        return obj

    atk_a = _add_creature(py_state, bears, controller=0)
    atk_b = _add_creature(py_state, bears, controller=0)
    blk_small = _add_creature(py_state, bears, controller=1)
    blk_big = _add_creature(py_state, big_bear, controller=1)

    # Mark both p0 creatures as attacking (simulates post-declare-
    # attackers state, what pick_blocks would see at DECLARE_BLOCKERS).
    atk_a.attacking = True
    atk_b.attacking = True

    agent = RealGameCombatAgent(strategy="attack_all_block_smallest")
    assignments = agent.pick_blocks(py_state)
    # Two attackers, two blockers — one block per attacker.
    assert len(assignments) == 2
    # Assignment shape: [blocker_id, attacker_id].
    assignment_dict = {b: a for b, a in assignments}
    # Smaller blocker (bears 2/2) should pair with lower-id attacker
    # (atk_a). Bigger blocker pairs with atk_b.
    # The agent walks attackers in id-sort order and assigns the
    # smallest UNUSED blocker.
    assert assignment_dict[int(blk_small.id)] == int(atk_a.id)
    assert assignment_dict[int(blk_big.id)] == int(atk_b.id)


def test_combat_agent_block_smallest_more_attackers_than_blockers():
    """When defender has fewer blockers than attackers, the lower-id
    attackers get blocked first; remaining attackers go through
    unblocked (no assignment for them)."""
    from mtg_bot.parity.trajectory import (
        RealGameCombatAgent,
        setup_matched_game,
    )
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.game import Zone

    spec = _vanilla_60_deckspec(shared_rng_seed=42)
    py_state, _ = setup_matched_game(spec)

    bears = CardPrinting(
        name="Grizzly Bears",
        mana_cost_str="",
        mana_cost=ManaCost(),
        type_line="Creature — Bear",
        supertypes=(),
        card_types=("Creature",),
        subtypes=("Bear",),
        power=2,
        toughness=2,
        produces=frozenset(),
        keywords=frozenset(),
    )

    def _add_creature(state, printing, controller):
        obj = state.new_object(printing, owner_id=controller, zone=Zone.BATTLEFIELD)
        obj.summoning_sick = False
        obj.tapped = False
        obj.attacking = False
        obj.blocking = False
        obj.etb_timestamp = state.next_timestamp
        state.next_timestamp += 1
        state.battlefield.append(obj)
        return obj

    atk_a = _add_creature(py_state, bears, controller=0)
    atk_b = _add_creature(py_state, bears, controller=0)
    atk_c = _add_creature(py_state, bears, controller=0)
    blk_only = _add_creature(py_state, bears, controller=1)
    atk_a.attacking = True
    atk_b.attacking = True
    atk_c.attacking = True

    agent = RealGameCombatAgent(strategy="attack_all_block_smallest")
    assignments = agent.pick_blocks(py_state)
    # Only one assignment — the single blocker pairs with the
    # lowest-id attacker (atk_a).
    assert len(assignments) == 1
    assert assignments[0] == [int(blk_only.id), int(atk_a.id)]


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


# ---------------------------------------------------------------------------
# Round-17 enhancement (production-decklists slice): unit tests for the
# three new RealGameCombatAgent strategies.
#
# All three new strategies operate on a synthetic in-memory bf so the
# tests stay tight and don't depend on the multi-turn trajectory walk.
# ---------------------------------------------------------------------------


def _make_creature(state, *, name, power, toughness, controller, keywords=()):
    """Build a vanilla Creature CardPrinting + materialize on bf.

    Helper used by the round-17 strategy unit tests. Wraps the
    ``new_object`` + ``state.battlefield.append`` sequence with the
    standard "no sickness, untapped, no damage, fresh ETB timestamp"
    initialization.
    """
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.game import Zone

    printing = CardPrinting(
        name=name,
        mana_cost_str="",
        mana_cost=ManaCost(),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=power,
        toughness=toughness,
        produces=frozenset(),
        keywords=frozenset(keywords),
    )
    obj = state.new_object(printing, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    obj.tapped = False
    obj.attacking = False
    obj.blocking = False
    obj.etb_timestamp = state.next_timestamp
    state.next_timestamp += 1
    state.battlefield.append(obj)
    return obj


def test_combat_agent_attack_unblockable_only_filters_to_evasion():
    """``"attack_with_unblockable_creatures_only"`` only declares
    attackers carrying an evasion keyword."""
    from mtg_bot.parity.trajectory import (
        RealGameCombatAgent,
        setup_matched_game,
    )

    spec = _vanilla_60_deckspec(shared_rng_seed=42)
    py_state, _ = setup_matched_game(spec)

    # Three p0 creatures: a vanilla, a flier, an unblockable.
    grunt = _make_creature(
        py_state, name="Bear Grunt", power=2, toughness=2, controller=0,
    )
    flier = _make_creature(
        py_state, name="Bear Falcon", power=2, toughness=2, controller=0,
        keywords=("flying",),
    )
    sneaky = _make_creature(
        py_state, name="Bear Spy", power=2, toughness=2, controller=0,
        keywords=("unblockable",),
    )

    agent = RealGameCombatAgent(
        strategy="attack_with_unblockable_creatures_only",
    )
    attackers = agent.pick_attackers(py_state)
    assert int(grunt.id) not in attackers
    assert int(flier.id) in attackers
    assert int(sneaky.id) in attackers
    # Empty blocks regardless.
    assert agent.pick_blocks(py_state) == []


def test_combat_agent_attack_unblockable_only_with_no_evasion_returns_empty():
    """No evasion creatures on bf → no attackers."""
    from mtg_bot.parity.trajectory import (
        RealGameCombatAgent,
        setup_matched_game,
    )

    spec = _vanilla_60_deckspec(shared_rng_seed=42)
    py_state, _ = setup_matched_game(spec)
    _make_creature(
        py_state, name="Bear Grunt", power=2, toughness=2, controller=0,
    )
    agent = RealGameCombatAgent(
        strategy="attack_with_unblockable_creatures_only",
    )
    assert agent.pick_attackers(py_state) == []


def test_combat_agent_block_with_largest_able_pairs_largest_first():
    """``"block_with_largest_able"`` assigns the LARGEST blocker to
    the lowest-id attacker first (mirror of the smallest selector).
    """
    from mtg_bot.parity.trajectory import (
        RealGameCombatAgent,
        setup_matched_game,
    )

    spec = _vanilla_60_deckspec(shared_rng_seed=42)
    py_state, _ = setup_matched_game(spec)

    atk_a = _make_creature(
        py_state, name="Bear A", power=2, toughness=2, controller=0,
    )
    atk_b = _make_creature(
        py_state, name="Bear B", power=2, toughness=2, controller=0,
    )
    blk_small = _make_creature(
        py_state, name="Bear Small", power=1, toughness=1, controller=1,
    )
    blk_big = _make_creature(
        py_state, name="Bear Big", power=4, toughness=4, controller=1,
    )
    atk_a.attacking = True
    atk_b.attacking = True

    agent = RealGameCombatAgent(strategy="block_with_largest_able")
    assignments = agent.pick_blocks(py_state)
    assert len(assignments) == 2
    by_blocker = {b: a for b, a in assignments}
    # Largest blocker (4/4 Bear Big) pairs with the LOWEST-id attacker.
    assert by_blocker[int(blk_big.id)] == int(atk_a.id)
    assert by_blocker[int(blk_small.id)] == int(atk_b.id)


def test_combat_agent_optimal_no_loss_attack_avoids_losing_attackers():
    """``"optimal_no_loss_attack"`` only attacks if no defender creature
    can kill the attacker on the back-block.

    Setup: p0 has a 3/3 (safe — defender's biggest is a 2/2) and a 2/2
    (unsafe — defender's 2/2 can trade up). Strategy should declare
    only the 3/3.
    """
    from mtg_bot.parity.trajectory import (
        RealGameCombatAgent,
        setup_matched_game,
    )

    spec = _vanilla_60_deckspec(shared_rng_seed=42)
    py_state, _ = setup_matched_game(spec)

    safe = _make_creature(
        py_state, name="Bear Tank", power=3, toughness=3, controller=0,
    )
    unsafe = _make_creature(
        py_state, name="Bear Cub", power=2, toughness=2, controller=0,
    )
    _make_creature(
        py_state, name="Defender Bear", power=2, toughness=2, controller=1,
    )

    agent = RealGameCombatAgent(strategy="optimal_no_loss_attack")
    attackers = agent.pick_attackers(py_state)
    assert int(safe.id) in attackers
    assert int(unsafe.id) not in attackers
    # No blocks regardless.
    assert agent.pick_blocks(py_state) == []


def test_combat_agent_optimal_no_loss_attack_no_defender_creatures_attacks_all():
    """When defender has no creatures, every eligible attacker is safe
    (vacuously no blocker can trade). All eligible attackers declare.
    """
    from mtg_bot.parity.trajectory import (
        RealGameCombatAgent,
        setup_matched_game,
    )

    spec = _vanilla_60_deckspec(shared_rng_seed=42)
    py_state, _ = setup_matched_game(spec)

    a = _make_creature(
        py_state, name="Bear A", power=1, toughness=1, controller=0,
    )
    b = _make_creature(
        py_state, name="Bear B", power=2, toughness=2, controller=0,
    )

    agent = RealGameCombatAgent(strategy="optimal_no_loss_attack")
    attackers = agent.pick_attackers(py_state)
    assert sorted(attackers) == sorted([int(a.id), int(b.id)])


# ---------------------------------------------------------------------------
# Round-17 enhancement: production-deck loader unit tests.
#
# Cover the loader's happy path + filter behavior + validation surface.
# The trajectory tests in test_trajectory_parity.py exercise the
# end-to-end real-EoE-deck → matched-game flow.
# ---------------------------------------------------------------------------


def test_load_production_deck_returns_card_name_list():
    """load_production_deck(0) returns the first deck's card-name list."""
    from mtg_bot.parity.trajectory import load_production_deck

    cards = load_production_deck(0)
    assert isinstance(cards, list)
    # 17lands EoE decks are 40 cards (sealed deck size).
    assert len(cards) == 40
    assert all(isinstance(c, str) for c in cards)


def test_load_production_deck_negative_archetype_rejected():
    """archetype < 0 raises IndexError."""
    from mtg_bot.parity.trajectory import load_production_deck

    with pytest.raises(IndexError, match="out of range"):
        load_production_deck(-1)


def test_load_production_deck_oversized_archetype_rejected():
    """archetype >= len(pool) raises IndexError."""
    from mtg_bot.parity.trajectory import load_production_deck

    with pytest.raises(IndexError, match="out of range"):
        load_production_deck(10**9)


def test_load_production_deck_missing_pool_raises():
    """A nonexistent deck pool path raises FileNotFoundError."""
    import pathlib
    from mtg_bot.parity.trajectory import load_production_deck

    with pytest.raises(FileNotFoundError, match="not found"):
        load_production_deck(0, deck_pool_path=pathlib.Path("/nonexistent/x.json.gz"))


def test_production_deck_to_deckspec_filters_unsupported_cards():
    """Cards that don't pass the bridge-support filter are dropped from
    the per-player libraries, but the union card_defs registry only
    contains bridge-supported names."""
    from mtg_bot.parity.trajectory import (
        load_production_deck,
        production_deck_to_deckspec,
    )

    cards = load_production_deck(0)
    spec = production_deck_to_deckspec(cards, shared_rng_seed=42)
    # All card_defs are basic Lands or vanilla Creatures (the only two
    # bridge-supported shapes).
    for cd in spec.card_defs:
        assert cd.card_type in ("Land", "Creature")
        if cd.card_type == "Creature":
            assert cd.power is not None
            assert cd.toughness is not None
        if cd.card_type == "Land":
            # Basic lands carry exactly one mana_produced color.
            assert len(cd.mana_produced) == 1


def test_production_deck_to_deckspec_pads_to_target_size():
    """Short decks pad with the configured basic land to pad_to_size."""
    from mtg_bot.parity.trajectory import (
        load_production_deck,
        production_deck_to_deckspec,
    )

    cards = load_production_deck(0)
    spec = production_deck_to_deckspec(
        cards, shared_rng_seed=42, pad_to_size=60, pad_with="Forest",
    )
    assert len(spec.p0_library) == 60
    assert len(spec.p1_library) == 60


def test_production_deck_to_deckspec_no_padding_when_pad_to_size_zero():
    """pad_to_size=0 keeps the post-filter library size as-is."""
    from mtg_bot.parity.trajectory import (
        load_production_deck,
        production_deck_to_deckspec,
    )

    cards = load_production_deck(0)
    spec = production_deck_to_deckspec(
        cards, shared_rng_seed=42, pad_to_size=0,
    )
    # Post-filter size (no padding) — almost always less than 40 since
    # the filter drops most cards.
    assert len(spec.p0_library) <= 40
    assert len(spec.p0_library) > 0


def test_production_deck_to_deckspec_invalid_pad_with_rejected():
    """pad_with that doesn't resolve to a basic land raises ValueError."""
    from mtg_bot.parity.trajectory import (
        load_production_deck,
        production_deck_to_deckspec,
    )

    cards = load_production_deck(0)
    with pytest.raises(ValueError, match="basic land"):
        production_deck_to_deckspec(
            cards, shared_rng_seed=42, pad_with="Definitely Not A Card",
        )


def test_production_deck_to_deckspec_mirror_match_default():
    """When p1 names is None, p1 receives p0's filtered library."""
    from mtg_bot.parity.trajectory import (
        load_production_deck,
        production_deck_to_deckspec,
    )

    cards = load_production_deck(0)
    spec = production_deck_to_deckspec(cards, shared_rng_seed=42)
    assert spec.p0_library == spec.p1_library


def test_production_deck_to_deckspec_asymmetric_decks():
    """When p1 names differ, the libraries can diverge (asymmetric)."""
    from mtg_bot.parity.trajectory import (
        load_production_deck,
        production_deck_to_deckspec,
    )

    p0_cards = load_production_deck(0)
    p1_cards = load_production_deck(1)
    spec = production_deck_to_deckspec(
        p0_cards, p1_cards, shared_rng_seed=42,
    )
    # The decks may filter to identical shapes by coincidence on the
    # very-restrictive bridge filter (lots of basic lands), but the
    # union card_defs should at least be valid.
    assert len(spec.card_defs) >= 1
    assert len(spec.p0_library) == 60
    assert len(spec.p1_library) == 60


def test_setup_matched_game_from_real_decks_parity_clean():
    """End-to-end smoke: real EoE deck → matched states with byte-equal
    field views."""
    from mtg_bot.parity.cross_engine import (
        build_python_field_view,
        compare_fields,
        parity_smoke,
    )
    from mtg_bot.parity.trajectory import (
        load_production_deck,
        setup_matched_game_from_real_decks,
    )

    cards = load_production_deck(0)
    py_state, rust_state = setup_matched_game_from_real_decks(
        cards, shared_rng_seed=42,
    )
    py_view = build_python_field_view(py_state)
    rust_view = parity_smoke()._build_field_view(rust_state)
    divs = compare_fields(py_view, rust_view)
    assert divs == [], (
        f"production-deck setup diverges: "
        f"{[(d.field, d.py_value, d.rust_value) for d in divs]}"
    )
    # 7-card opening hands.
    assert len(py_view["hand_p0"]) == 7
    assert len(py_view["hand_p1"]) == 7
    # 53-card libraries (60 - 7 dealt).
    assert len(py_view["library_p0"]) == 53
    assert len(py_view["library_p1"]) == 53
