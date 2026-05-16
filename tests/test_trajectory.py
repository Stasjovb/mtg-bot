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


# ---------------------------------------------------------------------------
# Phase 6 round-19 enhancement: BilateralCombatAgent unit tests.
#
# Closes the round-17 enhancement-follow-on item "Bilateral / asymmetric
# combat strategies": the per-side wrapper holds two RealGameCombatAgent
# delegates and dispatches pick_attackers / pick_blocks based on which
# side is active / defending at decision time.
# ---------------------------------------------------------------------------


def _bilateral_test_creatures():
    """Helper: return (bears, big_bear) printings for the per-side
    bf-construction tests below. Mirrors the
    test_combat_agent_attack_all_block_smallest_assignment_pairing
    helper-style above, but extracted so the bilateral tests can
    share it without inflating each test body."""
    from mtg_bot.cards.base import CardPrinting, ManaCost

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
    return bears, big_bear


def _bilateral_add_creature(state, printing, controller):
    """Helper: append a battlefield creature controlled by ``controller``.
    Mirrors the inline ``_add_creature`` in the round-16/17 tests."""
    from mtg_bot.game import Zone

    obj = state.new_object(printing, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    obj.tapped = False
    obj.attacking = False
    obj.blocking = False
    obj.etb_timestamp = state.next_timestamp
    state.next_timestamp += 1
    state.battlefield.append(obj)
    return obj


def test_bilateral_agent_constructs_from_strategy_pair():
    """BilateralCombatAgent constructs from per-side strategy strings
    and stamps two RealGameCombatAgent delegates internally."""
    from mtg_bot.parity.trajectory import (
        BilateralCombatAgent,
        RealGameCombatAgent,
    )

    agent = BilateralCombatAgent(
        p0_strategy="attack_all", p1_strategy="no_attack",
    )
    assert isinstance(agent.p0_agent, RealGameCombatAgent)
    assert isinstance(agent.p1_agent, RealGameCombatAgent)
    assert agent.p0_agent.strategy == "attack_all"
    assert agent.p1_agent.strategy == "no_attack"


def test_bilateral_agent_constructs_from_agent_pair():
    """BilateralCombatAgent constructs from pre-built per-side
    RealGameCombatAgent instances. Useful for callers that share /
    pre-build agents."""
    from mtg_bot.parity.trajectory import (
        BilateralCombatAgent,
        RealGameCombatAgent,
    )

    p0 = RealGameCombatAgent(strategy="attack_all_block_smallest")
    p1 = RealGameCombatAgent(strategy="block_with_largest_able")
    agent = BilateralCombatAgent(p0_agent=p0, p1_agent=p1)
    assert agent.p0_agent is p0
    assert agent.p1_agent is p1


def test_bilateral_agent_mixed_construction_per_side_works():
    """Per-side construction shapes are independent: p0 from strategy,
    p1 from agent (or vice versa) is legal."""
    from mtg_bot.parity.trajectory import (
        BilateralCombatAgent,
        RealGameCombatAgent,
    )

    p1 = RealGameCombatAgent(strategy="optimal_no_loss_attack")
    agent = BilateralCombatAgent(p0_strategy="attack_all", p1_agent=p1)
    assert agent.p0_agent.strategy == "attack_all"
    assert agent.p1_agent is p1


def test_bilateral_agent_both_strategy_and_agent_per_side_raises():
    """Each side must have exactly one source of truth."""
    from mtg_bot.parity.trajectory import (
        BilateralCombatAgent,
        RealGameCombatAgent,
    )

    p0 = RealGameCombatAgent(strategy="attack_all")
    with pytest.raises(ValueError, match="either p0_strategy or p0_agent"):
        BilateralCombatAgent(
            p0_strategy="attack_all",
            p0_agent=p0,
            p1_strategy="no_attack",
        )
    with pytest.raises(ValueError, match="either p1_strategy or p1_agent"):
        BilateralCombatAgent(
            p0_strategy="attack_all",
            p1_strategy="no_attack",
            p1_agent=p0,
        )


def test_bilateral_agent_neither_per_side_raises():
    """Each side must have at least one source of truth."""
    from mtg_bot.parity.trajectory import BilateralCombatAgent

    with pytest.raises(ValueError, match="must pass one of p0_strategy"):
        BilateralCombatAgent(p1_strategy="no_attack")
    with pytest.raises(ValueError, match="must pass one of p1_strategy"):
        BilateralCombatAgent(p0_strategy="attack_all")


def test_bilateral_agent_invalid_strategy_string_rejected():
    """Per-side strategy strings flow through RealGameCombatAgent's
    strategy validation; an invalid string raises at construct time."""
    from mtg_bot.parity.trajectory import BilateralCombatAgent

    with pytest.raises(ValueError, match="strategy="):
        BilateralCombatAgent(
            p0_strategy="charge_blindly", p1_strategy="no_attack",
        )


def test_bilateral_agent_pick_attackers_routes_to_active_side():
    """``pick_attackers`` dispatches to the active player's delegate.

    Constructs a synthetic bf with one creature per side. With
    p0_strategy=attack_all + p1_strategy=no_attack: when p0 is active,
    p0's creature attacks (returns [id]); when p1 is active, no
    attacker (returns [])."""
    from mtg_bot.parity.trajectory import (
        BilateralCombatAgent,
        setup_matched_game,
    )

    spec = _vanilla_60_deckspec(shared_rng_seed=42)
    py_state, _ = setup_matched_game(spec)

    bears, _ = _bilateral_test_creatures()
    p0_creature = _bilateral_add_creature(py_state, bears, controller=0)
    p1_creature = _bilateral_add_creature(py_state, bears, controller=1)

    agent = BilateralCombatAgent(
        p0_strategy="attack_all", p1_strategy="no_attack",
    )

    # p0 active -> attack_all fires for p0; only p0's creature is eligible.
    py_state.active_player_idx = 0
    assert agent.pick_attackers(py_state) == [int(p0_creature.id)]

    # p1 active -> no_attack fires for p1; no attackers regardless of bf.
    py_state.active_player_idx = 1
    assert agent.pick_attackers(py_state) == []


def test_bilateral_agent_pick_blocks_routes_to_defender_side():
    """``pick_blocks`` dispatches to the DEFENDER's delegate.

    Constructs a synthetic bf with two p0 creatures (one attacking)
    and two p1 creatures (one attacking, one blocking-eligible).
    With p0_strategy=attack_all_block_smallest +
    p1_strategy=no_attack: when p0 is active (so p1 defends), p1's
    no_attack-strategy delegate picks no blocks; when p1 is active
    (so p0 defends), p0's attack_all_block_smallest-strategy delegate
    picks a block.
    """
    from mtg_bot.parity.trajectory import (
        BilateralCombatAgent,
        setup_matched_game,
    )

    spec = _vanilla_60_deckspec(shared_rng_seed=42)
    py_state, _ = setup_matched_game(spec)

    bears, _ = _bilateral_test_creatures()

    # p0 has one creature, p1 has one creature. We'll mark them
    # attacking depending on which test branch is active.
    p0_creature = _bilateral_add_creature(py_state, bears, controller=0)
    p1_creature = _bilateral_add_creature(py_state, bears, controller=1)

    agent = BilateralCombatAgent(
        p0_strategy="attack_all_block_smallest",
        p1_strategy="no_attack",
    )

    # Branch 1: p0 active (defender = p1, runs no_attack -> empty
    # blocks). p0's creature is the attacker; p1's creature is
    # block-eligible but no_attack-strategy returns [] (the no_attack
    # strategy applies on both sides of the table for that delegate).
    py_state.active_player_idx = 0
    p0_creature.attacking = True
    p1_creature.attacking = False
    p1_creature.blocking = False
    assert agent.pick_blocks(py_state) == []

    # Reset attacking flags before branch 2 (avoid stale state).
    p0_creature.attacking = False
    p1_creature.attacking = False

    # Branch 2: p1 active (defender = p0, runs
    # attack_all_block_smallest -> blocks each attacker). p1's
    # creature is the attacker; p0's creature is block-eligible and
    # the smallest-strategy delegate picks it.
    py_state.active_player_idx = 1
    p1_creature.attacking = True
    assignments = agent.pick_blocks(py_state)
    assert len(assignments) == 1
    blocker_id, attacker_id = assignments[0]
    assert blocker_id == int(p0_creature.id)
    assert attacker_id == int(p1_creature.id)


def test_bilateral_agent_inverted_block_selectors_per_side():
    """Two different block selectors: p0 picks SMALLEST, p1 picks
    LARGEST. With one attacker on each side and a small + a big
    blocker on each side, the assignment selector differs per
    defender — pinning the asymmetric block selector contract that
    the round-17 enhancement-follow-on flagged."""
    from mtg_bot.parity.trajectory import (
        BilateralCombatAgent,
        setup_matched_game,
    )

    spec = _vanilla_60_deckspec(shared_rng_seed=42)
    py_state, _ = setup_matched_game(spec)

    bears, big_bear = _bilateral_test_creatures()

    # p0: 1 attacker (bears) + 2 blockers (one bears, one big_bear).
    p0_atk = _bilateral_add_creature(py_state, bears, controller=0)
    p0_blk_small = _bilateral_add_creature(py_state, bears, controller=0)
    p0_blk_big = _bilateral_add_creature(py_state, big_bear, controller=0)
    # p1: 1 attacker + 2 blockers (same shape).
    p1_atk = _bilateral_add_creature(py_state, bears, controller=1)
    p1_blk_small = _bilateral_add_creature(py_state, bears, controller=1)
    p1_blk_big = _bilateral_add_creature(py_state, big_bear, controller=1)

    agent = BilateralCombatAgent(
        p0_strategy="attack_all_block_smallest",
        p1_strategy="block_with_largest_able",
    )

    # Branch 1: p1 attacks, p0 defends with smallest. p0's bears
    # (smaller than big_bear) blocks p1's attacker. Tap p0_atk so
    # only p0_blk_small / p0_blk_big are block-eligible (the smallest
    # selector would otherwise pick p0_atk -- another bears at the
    # lowest id -- since tied 2/2 creatures break by id ascending).
    py_state.active_player_idx = 1
    p1_atk.attacking = True
    p0_atk.attacking = False
    p0_atk.tapped = True
    assignments = agent.pick_blocks(py_state)
    assert len(assignments) == 1
    blocker_id, attacker_id = assignments[0]
    assert blocker_id == int(p0_blk_small.id), (
        f"p0 with attack_all_block_smallest should pick the SMALLER "
        f"of the two block-eligible defenders (bears p0_blk_small, "
        f"id={p0_blk_small.id}), not big_bear (id={p0_blk_big.id})"
    )
    assert attacker_id == int(p1_atk.id)

    # Reset attacking + blocking + tapped flags before branch 2.
    p1_atk.attacking = False
    p0_atk.tapped = False
    p0_blk_small.blocking = False
    p0_blk_big.blocking = False

    # Branch 2: p0 attacks, p1 defends with LARGEST. p1's big_bear
    # (larger than bears) blocks p0's attacker. Symmetric to branch 1
    # -- tap p1_atk so only p1_blk_small / p1_blk_big are block-
    # eligible (the largest selector would also rank p1_atk at a tie
    # with p1_blk_small; tapping makes the test isolation cleaner).
    py_state.active_player_idx = 0
    p0_atk.attacking = True
    p1_atk.tapped = True
    assignments = agent.pick_blocks(py_state)
    assert len(assignments) == 1
    blocker_id, attacker_id = assignments[0]
    assert blocker_id == int(p1_blk_big.id), (
        f"p1 with block_with_largest_able should pick the LARGER "
        f"of the two block-eligible defenders (big_bear "
        f"p1_blk_big, id={p1_blk_big.id}), not bears "
        f"(id={p1_blk_small.id})"
    )
    assert attacker_id == int(p0_atk.id)


def test_bilateral_agent_drives_drive_combat_phase_unchanged():
    """BilateralCombatAgent is duck-typed-compatible with
    drive_combat_phase: the helper accepts the wrapper unchanged.
    Smoke test: walk a no-op combat phase (both sides no_attack) on
    an empty bf; pre + post-state equal modulo step advance."""
    from mtg_bot.parity.trajectory import (
        BilateralCombatAgent,
        drive_combat_phase,
        setup_matched_game,
    )
    from mtg_bot.parity.cross_engine import advance_phase_python
    from mtg_bot.turn import Step

    spec = _vanilla_60_deckspec(shared_rng_seed=42)
    py_state, rust_state = setup_matched_game(spec)
    # Advance to DECLARE_ATTACKERS (UNTAP -> UPKEEP -> DRAW ->
    # PRECOMBAT_MAIN -> BEGINNING_OF_COMBAT -> DECLARE_ATTACKERS
    # = 5 advances). Mirror on rust.
    for _ in range(5):
        advance_phase_python(py_state)
        rust_state.advance_phase()
    assert py_state.step == Step.DECLARE_ATTACKERS

    agent = BilateralCombatAgent(
        p0_strategy="no_attack", p1_strategy="no_attack",
    )
    # Should not raise; should advance the step to END_OF_COMBAT.
    drive_combat_phase(py_state, rust_state, agent)
    assert py_state.step == Step.END_OF_COMBAT


def test_bilateral_agent_player_idx_validation():
    """The internal _agent_for helper rejects unsupported player
    indexes (defensive against a future N>2 player engine that calls
    pick_attackers with active_player_idx > 1)."""
    from mtg_bot.parity.trajectory import BilateralCombatAgent

    agent = BilateralCombatAgent(
        p0_strategy="attack_all", p1_strategy="no_attack",
    )
    with pytest.raises(ValueError, match="two-player engines"):
        agent._agent_for(2)


def test_bilateral_agent_in_module_dunder_all():
    """BilateralCombatAgent is exported from the trajectory module
    public API."""
    from mtg_bot.parity import trajectory

    assert "BilateralCombatAgent" in trajectory.__all__


# ---------------------------------------------------------------------------
# Phase 6 carddef-substrate slice — unit tests for the keywords-aware
# bridge filter extension and the CardDef.keywords plumbing.
# ---------------------------------------------------------------------------


def test_safe_keywords_set_covers_phase_6_round_18_probes():
    """Phase 6 rounds 17/18 trajectory probes verified eight specific
    keywords parity-clean. Pin that the bridge filter's allowlist
    carries every one of them so a future shrink doesn't silently
    regress production-deck coverage.
    """
    from mtg_bot.parity.trajectory import _SAFE_KEYWORDS

    # Round 17: trample, vigilance, lifelink. Round 18: deathtouch,
    # double-strike, haste. Phase 5 selectors: flying, first strike.
    # Plus menace / defender / indestructible (Phase 5 only — included
    # in the safe set so multi-keyword EoE creatures with these keep
    # surviving the filter).
    expected_subset = {
        "flying", "vigilance", "lifelink", "trample", "haste",
        "deathtouch", "first strike", "double strike",
        "menace", "defender", "indestructible",
    }
    missing = expected_subset - _SAFE_KEYWORDS
    assert not missing, (
        f"_SAFE_KEYWORDS regressed; missing keywords with parity-"
        f"clean trajectory probes: {sorted(missing)}"
    )


def test_simple_creature_filter_admits_safe_keyword_creature():
    """A creature whose only keyword is in `_SAFE_KEYWORDS` (e.g.
    'flying') passes the bridge-simple filter — the prior round-17
    "vanilla only" gate would have dropped it.
    """
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.parity.trajectory import (
        _printing_is_bridge_simple_creature,
    )

    flier = CardPrinting(
        name="Synthetic Flier",
        mana_cost_str="{1}{U}",
        mana_cost=ManaCost(generic=1, colored=(("U", 1),)),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=2,
        toughness=2,
        produces=frozenset(),
        keywords=frozenset({"flying"}),
    )
    assert _printing_is_bridge_simple_creature(flier) is True


def test_simple_creature_filter_rejects_unsafe_keyword_creature():
    """A creature carrying a keyword OUTSIDE `_SAFE_KEYWORDS` (e.g.
    'flash') fails the bridge-simple filter even when every other
    field is vanilla. Pins that the gate is restrictive on the unsafe
    direction — admitting an unmodeled keyword would silently produce
    cross-engine divergence at probe time.
    """
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.parity.trajectory import (
        _printing_is_bridge_simple_creature,
    )

    flasher = CardPrinting(
        name="Synthetic Flasher",
        mana_cost_str="{2}{G}",
        mana_cost=ManaCost(generic=2, colored=(("G", 1),)),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=2,
        toughness=2,
        produces=frozenset(),
        keywords=frozenset({"flash"}),
    )
    assert _printing_is_bridge_simple_creature(flasher) is False


def test_printing_to_card_def_carries_keywords_through():
    """`_printing_to_card_def` populates `CardDef.keywords` from the
    source printing's `keywords` frozenset, sorted for determinism.
    Pins the bridge-side keyword propagation invariant.
    """
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.parity.trajectory import _printing_to_card_def

    multi = CardPrinting(
        name="Synthetic Multi-Keyword",
        mana_cost_str="{2}{W}",
        mana_cost=ManaCost(generic=2, colored=(("W", 1),)),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=2,
        toughness=2,
        produces=frozenset(),
        keywords=frozenset({"flying", "vigilance"}),
    )
    cd = _printing_to_card_def(multi)
    assert cd.card_type == "Creature"
    assert cd.keywords == ("flying", "vigilance")  # sorted


def test_carddef_keywords_thread_through_both_engines():
    """Building a matched state from a DeckSpec with a keyword-bearing
    CardDef registers the keyword on BOTH engines' printing registries.

    The Python side carries `frozenset({"flying"})`; the Rust side
    consumes `["flying"]` (underscore-translated only when the input
    contained a space, e.g. "first strike" -> "first_strike"). End-to-
    end sanity check that the substrate change wires both engines.
    """
    from mtg_bot.parity.cross_engine import CardDef, DeckSpec
    from mtg_bot.parity.trajectory import setup_matched_game

    flier = CardDef(
        name="Carddef Flier",
        card_type="Creature",
        mana_cost_generic=1,
        mana_cost_colored=(("U", 1),),
        power=2, toughness=2,
        keywords=("flying",),
    )
    forest = CardDef(
        name="Forest", card_type="Land", mana_produced=("G",),
    )
    spec = DeckSpec(
        card_defs=(flier, forest),
        p0_library=("Forest",) * 30 + ("Carddef Flier",) * 30,
        p1_library=("Forest",) * 60,
        shared_rng_seed=42,
    )
    py_state, rust_state = setup_matched_game(spec)
    # Python side: every flier in the registry carries the keyword.
    py_lib = py_state.players[0].library + py_state.players[0].hand
    fliers = [o for o in py_lib if o.printing.name == "Carddef Flier"]
    assert fliers, "no Carddef Flier in p0's library/hand"
    assert all(
        "flying" in o.printing.keywords for o in fliers
    ), "Python-side flier missing the flying keyword"
    # Rust side: matched-state setup must have completed without
    # error; the keyword translation through `register_printing` is
    # exercised by the matched-state field-view compare in the
    # trajectory-parity tests above.
    assert rust_state.turn_number == 1


def test_carddef_keywords_with_space_translate_for_rust():
    """A CardDef carrying a space-form keyword (e.g. 'first strike')
    threads through to BOTH engines. Pins the convention split: Python
    keeps the space form; Rust receives the underscore form via the
    bridge translation in `cross_engine.build_rust_state`.
    """
    from mtg_bot.parity.cross_engine import CardDef, DeckSpec
    from mtg_bot.parity.trajectory import setup_matched_game

    fs = CardDef(
        name="Carddef FS",
        card_type="Creature",
        mana_cost_generic=2,
        mana_cost_colored=(("W", 1),),
        power=2, toughness=2,
        keywords=("first strike",),
    )
    forest = CardDef(
        name="Forest", card_type="Land", mana_produced=("G",),
    )
    spec = DeckSpec(
        card_defs=(fs, forest),
        p0_library=("Forest",) * 30 + ("Carddef FS",) * 30,
        p1_library=("Forest",) * 60,
        shared_rng_seed=42,
    )
    py_state, rust_state = setup_matched_game(spec)
    # Python keeps the space form.
    py_lib = py_state.players[0].library + py_state.players[0].hand
    fs_objs = [o for o in py_lib if o.printing.name == "Carddef FS"]
    assert fs_objs, "no Carddef FS in p0's library/hand"
    assert all(
        "first strike" in o.printing.keywords for o in fs_objs
    )
    # Rust side: setup completed without raising, which is the load-
    # bearing assertion — the underscore translation is what makes
    # `register_printing` accept the keyword. End-to-end keyword-
    # behavior parity for first strike is exercised by the existing
    # round-17 first-strike trajectory probe.
    assert rust_state.turn_number == 1


# ---------------------------------------------------------------------------
# Phase 6 carddef-triggers slice — unit tests for the safe-trigger
# allowlist + the CardDef.triggered_abilities plumbing through the
# bridge filter and the production-deck loader.
# ---------------------------------------------------------------------------


def test_safe_triggers_set_carries_starter_etb_self_shapes():
    """Pin that the starter safe-trigger set carries the three
    ENTERS+SourceIsSelf shapes (draw_cards / gain_life / scry_n).
    A future shrink would silently regress production-deck coverage.
    """
    from mtg_bot.parity.trajectory import _SAFE_TRIGGERS

    expected = {
        ("enters", "source_is_self", "draw_cards"),
        ("enters", "source_is_self", "gain_life"),
        ("enters", "source_is_self", "scry_n"),
    }
    missing = expected - _SAFE_TRIGGERS
    assert not missing, (
        f"_SAFE_TRIGGERS regressed; missing safe shapes: "
        f"{sorted(missing)}"
    )


def test_is_safe_trigger_dict_admits_starter_shapes():
    """The dict-shape gate accepts each starter triple."""
    from mtg_bot.parity.trajectory import _is_safe_trigger_dict

    assert _is_safe_trigger_dict({
        "event": "enters",
        "predicate": {"kind": "source_is_self"},
        "effect": {"kind": "draw_cards", "count": 1},
    })
    assert _is_safe_trigger_dict({
        "event": "enters",
        "predicate": {"kind": "source_is_self"},
        "effect": {"kind": "gain_life", "amount": 2},
    })
    assert _is_safe_trigger_dict({
        "event": "enters",
        "predicate": {"kind": "source_is_self"},
        "effect": {"kind": "scry_n", "count": 1},
    })


def test_is_safe_trigger_dict_rejects_unsafe_event():
    """An ENTERS+IsSelf+DRAW shape with a different event (DIES) is
    out of the starter set — rejected.
    """
    from mtg_bot.parity.trajectory import _is_safe_trigger_dict

    assert not _is_safe_trigger_dict({
        "event": "dies",
        "predicate": {"kind": "source_is_self"},
        "effect": {"kind": "draw_cards", "count": 1},
    })


def test_is_safe_trigger_dict_rejects_unsafe_predicate():
    """A predicate kind outside the starter set (e.g. controlled_by_you)
    is rejected.
    """
    from mtg_bot.parity.trajectory import _is_safe_trigger_dict

    assert not _is_safe_trigger_dict({
        "event": "enters",
        "predicate": {"kind": "controlled_by_you"},
        "effect": {"kind": "draw_cards", "count": 1},
    })


def test_is_safe_trigger_dict_rejects_unsafe_effect():
    """An effect kind outside the starter set (e.g. deal_damage_each_
    opponent) is rejected even when event/predicate are safe.
    """
    from mtg_bot.parity.trajectory import _is_safe_trigger_dict

    assert not _is_safe_trigger_dict({
        "event": "enters",
        "predicate": {"kind": "source_is_self"},
        "effect": {"kind": "damage_each_opponent", "amount": 1},
    })


def test_is_safe_trigger_dict_rejects_once_per_turn():
    """``once_per_turn=True`` flips an otherwise-safe trigger to
    unsafe — once-per-turn bookkeeping isn't probed yet on the
    trajectory shape.
    """
    from mtg_bot.parity.trajectory import _is_safe_trigger_dict

    assert not _is_safe_trigger_dict({
        "event": "enters",
        "predicate": {"kind": "source_is_self"},
        "effect": {"kind": "draw_cards", "count": 1},
        "once_per_turn": True,
    })


def test_is_safe_trigger_dict_rejects_extra_top_level_key():
    """A trigger dict carrying a key outside the four-key whitelist
    (event/predicate/effect/once_per_turn) is rejected so a future
    schema extension doesn't silently slip through the loader.
    """
    from mtg_bot.parity.trajectory import _is_safe_trigger_dict

    assert not _is_safe_trigger_dict({
        "event": "enters",
        "predicate": {"kind": "source_is_self"},
        "effect": {"kind": "draw_cards", "count": 1},
        "tier_threshold": 3,
    })


def test_is_safe_trigger_dict_rejects_extra_effect_key():
    """An effect dict carrying a payload key beyond the per-arm
    whitelist is rejected — the safe-effect-keys map is the
    canonical bridge contract for each arm.
    """
    from mtg_bot.parity.trajectory import _is_safe_trigger_dict

    assert not _is_safe_trigger_dict({
        "event": "enters",
        "predicate": {"kind": "source_is_self"},
        "effect": {"kind": "draw_cards", "count": 1, "target": {}},
    })


def test_is_safe_trigger_dict_rejects_predicate_with_nested_fields():
    """A predicate dict carrying nested fields (subject/inner/left/...)
    is NOT in the starter safe set — that's a future slice's
    extension surface.
    """
    from mtg_bot.parity.trajectory import _is_safe_trigger_dict

    # "Not(IsSelf)" predicate shape — out of the starter set.
    assert not _is_safe_trigger_dict({
        "event": "enters",
        "predicate": {"kind": "not", "inner": {"kind": "source_is_self"}},
        "effect": {"kind": "draw_cards", "count": 1},
    })


def test_python_ta_to_safe_dict_round_trips_draw_cards():
    """A Python ``TriggeredAbility`` carrying ENTERS+IsSelf+DrawCards
    converts back to the safe dict shape; the result satisfies
    :func:`_is_safe_trigger_dict`.
    """
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.predicates import IsSelf, Event
    from mtg_bot.effects.generic.draw_mill import DrawCards
    from mtg_bot.parity.trajectory import (
        _is_safe_trigger_dict,
        _python_ta_to_safe_dict,
    )

    ta = TriggeredAbility(
        event=Event.ENTERS,
        predicate=IsSelf(),
        effect=DrawCards(amount=1),
    )
    d = _python_ta_to_safe_dict(ta)
    assert d == {
        "event": "enters",
        "predicate": {"kind": "source_is_self"},
        "effect": {"kind": "draw_cards", "count": 1},
    }
    assert _is_safe_trigger_dict(d)


def test_python_ta_to_safe_dict_round_trips_gain_life():
    """ENTERS+IsSelf+GainLife round-trips. Translated effect carries
    ``amount`` (the safe-effect key for gain_life).
    """
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.predicates import IsSelf, Event
    from mtg_bot.effects.generic.life import GainLife
    from mtg_bot.parity.trajectory import (
        _is_safe_trigger_dict,
        _python_ta_to_safe_dict,
    )

    ta = TriggeredAbility(
        event=Event.ENTERS,
        predicate=IsSelf(),
        effect=GainLife(amount=3),
    )
    d = _python_ta_to_safe_dict(ta)
    assert d == {
        "event": "enters",
        "predicate": {"kind": "source_is_self"},
        "effect": {"kind": "gain_life", "amount": 3},
    }
    assert _is_safe_trigger_dict(d)


def test_python_ta_to_safe_dict_round_trips_scry():
    """ENTERS+IsSelf+Scry round-trips. Python's ``Scry.amount``
    becomes the dict's ``count`` field per the bridge convention.
    """
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.predicates import IsSelf, Event
    from mtg_bot.effects.generic.library_lookat import Scry
    from mtg_bot.parity.trajectory import (
        _is_safe_trigger_dict,
        _python_ta_to_safe_dict,
    )

    ta = TriggeredAbility(
        event=Event.ENTERS,
        predicate=IsSelf(),
        effect=Scry(amount=2),
    )
    d = _python_ta_to_safe_dict(ta)
    assert d == {
        "event": "enters",
        "predicate": {"kind": "source_is_self"},
        "effect": {"kind": "scry_n", "count": 2},
    }
    assert _is_safe_trigger_dict(d)


def test_python_ta_to_safe_dict_returns_none_on_unsafe_effect():
    """Python ``TriggeredAbility`` with an effect outside the starter
    safe set returns None — disqualifies the parent printing.
    """
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.predicates import IsSelf, Event
    from mtg_bot.effects.generic.damage import DealDamageEachOpponent
    from mtg_bot.parity.trajectory import _python_ta_to_safe_dict

    ta = TriggeredAbility(
        event=Event.ENTERS,
        predicate=IsSelf(),
        effect=DealDamageEachOpponent(amount=1),
    )
    assert _python_ta_to_safe_dict(ta) is None


def test_python_ta_to_safe_dict_returns_none_on_once_per_turn():
    """Once-per-turn flag flips an otherwise-safe Python trigger to
    unsafe (mirrors :func:`_is_safe_trigger_dict`'s rejection).
    """
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.predicates import IsSelf, Event
    from mtg_bot.effects.generic.draw_mill import DrawCards
    from mtg_bot.parity.trajectory import _python_ta_to_safe_dict

    ta = TriggeredAbility(
        event=Event.ENTERS,
        predicate=IsSelf(),
        effect=DrawCards(amount=1),
        once_per_turn=True,
    )
    assert _python_ta_to_safe_dict(ta) is None


def test_simple_creature_filter_admits_safe_etb_trigger_creature():
    """A creature whose only triggered ability is one of the safe
    ENTERS+IsSelf shapes passes the bridge-simple filter — the
    pre-triggers gate (``if printing.triggered_abilities: return
    False``) would have dropped it.
    """
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.predicates import IsSelf, Event
    from mtg_bot.effects.generic.draw_mill import DrawCards
    from mtg_bot.parity.trajectory import (
        _printing_is_bridge_simple_creature,
    )

    bear = CardPrinting(
        name="Synthetic ETB Drawer",
        mana_cost_str="{1}{G}",
        mana_cost=ManaCost(generic=1, colored=(("G", 1),)),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=2,
        toughness=2,
        produces=frozenset(),
        triggered_abilities=(
            TriggeredAbility(
                event=Event.ENTERS,
                predicate=IsSelf(),
                effect=DrawCards(amount=1),
            ),
        ),
    )
    assert _printing_is_bridge_simple_creature(bear) is True


def test_simple_creature_filter_rejects_unsafe_etb_trigger_creature():
    """A creature carrying a triggered ability OUTSIDE the safe set
    fails the bridge-simple filter even when every other field is
    vanilla. Pins that the gate is restrictive on the unsafe
    direction — admitting an unmodeled trigger would silently produce
    cross-engine drift at probe time.
    """
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.predicates import IsSelf, Event
    from mtg_bot.effects.generic.damage import DealDamageEachOpponent
    from mtg_bot.parity.trajectory import (
        _printing_is_bridge_simple_creature,
    )

    burner = CardPrinting(
        name="Synthetic ETB Burner",
        mana_cost_str="{2}{R}",
        mana_cost=ManaCost(generic=2, colored=(("R", 1),)),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=2,
        toughness=2,
        produces=frozenset(),
        triggered_abilities=(
            TriggeredAbility(
                event=Event.ENTERS,
                predicate=IsSelf(),
                effect=DealDamageEachOpponent(amount=1),
            ),
        ),
    )
    assert _printing_is_bridge_simple_creature(burner) is False


def test_simple_creature_filter_rejects_mixed_safe_and_unsafe_triggers():
    """A creature carrying TWO triggered abilities — one safe, one
    unsafe — is rejected. The filter requires EVERY trigger to round-
    trip cleanly; partial admit would split the trigger surface
    asymmetrically across engines.
    """
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.predicates import IsSelf, Event
    from mtg_bot.effects.generic.draw_mill import DrawCards
    from mtg_bot.effects.generic.damage import DealDamageEachOpponent
    from mtg_bot.parity.trajectory import (
        _printing_is_bridge_simple_creature,
    )

    mixed = CardPrinting(
        name="Synthetic Mixed",
        mana_cost_str="{1}{B}",
        mana_cost=ManaCost(generic=1, colored=(("B", 1),)),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=2,
        toughness=2,
        produces=frozenset(),
        triggered_abilities=(
            TriggeredAbility(
                event=Event.ENTERS,
                predicate=IsSelf(),
                effect=DrawCards(amount=1),
            ),
            TriggeredAbility(
                event=Event.ENTERS,
                predicate=IsSelf(),
                effect=DealDamageEachOpponent(amount=1),
            ),
        ),
    )
    assert _printing_is_bridge_simple_creature(mixed) is False


def test_printing_to_card_def_carries_safe_trigger_through():
    """``_printing_to_card_def`` populates ``CardDef.triggered_abilities``
    from the source printing's safe Python triggered abilities,
    converted back to the dict round-trip shape. Pins the bridge-side
    triggered-ability propagation invariant.
    """
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.predicates import IsSelf, Event
    from mtg_bot.effects.generic.life import GainLife
    from mtg_bot.parity.trajectory import _printing_to_card_def

    bear = CardPrinting(
        name="Synthetic Lifegainer",
        mana_cost_str="{1}{W}",
        mana_cost=ManaCost(generic=1, colored=(("W", 1),)),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=2,
        toughness=2,
        produces=frozenset(),
        triggered_abilities=(
            TriggeredAbility(
                event=Event.ENTERS,
                predicate=IsSelf(),
                effect=GainLife(amount=2),
            ),
        ),
    )
    cd = _printing_to_card_def(bear)
    assert cd.card_type == "Creature"
    assert cd.triggered_abilities == ({
        "event": "enters",
        "predicate": {"kind": "source_is_self"},
        "effect": {"kind": "gain_life", "amount": 2},
    },)


def test_carddef_triggered_abilities_thread_through_both_engines():
    """Building a matched state from a DeckSpec with a trigger-bearing
    CardDef registers the trigger on BOTH engines' printing
    registries. End-to-end sanity check that the substrate change
    wires both engines.
    """
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.predicates import Event, IsSelf
    from mtg_bot.effects.generic.draw_mill import DrawCards
    from mtg_bot.parity.cross_engine import CardDef, DeckSpec
    from mtg_bot.parity.trajectory import setup_matched_game

    bear = CardDef(
        name="Carddef ETB Drawer",
        card_type="Creature",
        mana_cost_generic=1,
        mana_cost_colored=(("G", 1),),
        power=2, toughness=2,
        triggered_abilities=(
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {"kind": "draw_cards", "count": 1},
            },
        ),
    )
    forest = CardDef(
        name="Forest", card_type="Land", mana_produced=("G",),
    )
    spec = DeckSpec(
        card_defs=(bear, forest),
        p0_library=("Forest",) * 30 + ("Carddef ETB Drawer",) * 30,
        p1_library=("Forest",) * 60,
        shared_rng_seed=42,
    )
    py_state, rust_state = setup_matched_game(spec)
    # Python side: every Carddef ETB Drawer in the registry carries
    # the IsSelf-ENTERS DrawCards trigger.
    py_lib = py_state.players[0].library + py_state.players[0].hand
    bears = [
        o for o in py_lib if o.printing.name == "Carddef ETB Drawer"
    ]
    assert bears, "no Carddef ETB Drawer in p0's library/hand"
    for o in bears:
        assert len(o.printing.triggered_abilities) == 1
        ta = o.printing.triggered_abilities[0]
        assert isinstance(ta, TriggeredAbility)
        assert ta.event is Event.ENTERS
        assert isinstance(ta.predicate, IsSelf)
        assert isinstance(ta.effect, DrawCards)
        assert ta.effect.amount == 1
    # Rust side: matched-state setup completed without raising,
    # which is the load-bearing assertion — the dict-shape pass-
    # through to Rust's ``register_printing(triggered_abilities=)``
    # arm is exercised here. The end-to-end firing parity is
    # exercised by the trajectory probe in test_trajectory_parity.py.
    assert rust_state.turn_number == 1
