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
    # card_defs are basic Lands, bridge-simple Creatures, OR a
    # loader-SEATED token CardDef (round-49 vanilla-token / Phase 3a
    # round-53 ability-bearing-Lander substrate). Seated token defs
    # carry the ``Token`` supertype, are NEVER in either player's
    # library (registered for the pid only), and may be a non-creature
    # type (the Lander is ``Artifact``).
    lib_names = set(spec.p0_library) | set(spec.p1_library)
    for cd in spec.card_defs:
        is_seated_token = "Token" in (cd.supertypes or ())
        if is_seated_token:
            # A seated token printing — registered, never drawn.
            assert cd.name not in lib_names, (
                f"seated token {cd.name!r} must not be in any library"
            )
            continue
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
    # double-strike, haste. Round 45: reach. Phase 5 selectors: flying,
    # first strike. Plus menace / defender / indestructible (Phase 5
    # only — included in the safe set so multi-keyword EoE creatures
    # with these keep surviving the filter).
    expected_subset = {
        "flying", "vigilance", "lifelink", "trample", "haste",
        "deathtouch", "first strike", "double strike",
        "menace", "defender", "indestructible",
        "reach",
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


def test_safe_keywords_set_admits_reach():
    """Round-45 extension: ``"reach"`` is in the safe-keyword set.

    Pins the round-45 keyword extension. Both engines model reach
    identically as a blocker-side gate-opener in the flying-block
    legality check (Python ``combat.can_block``; Rust
    ``state_ops_combat::declare_blocker``); the trajectory probe
    ``test_reach_blocker_blocks_flying_attacker_parity`` exercises
    the byte-equal mutual-lethal trade.
    """
    from mtg_bot.parity.trajectory import _SAFE_KEYWORDS

    assert "reach" in _SAFE_KEYWORDS, (
        f"_SAFE_KEYWORDS regressed; round-45 extension missing 'reach' "
        f"(parity-clean per CR 702.17, exercised by "
        f"test_reach_blocker_blocks_flying_attacker_parity). "
        f"Current set: {sorted(_SAFE_KEYWORDS)}"
    )


def test_simple_creature_filter_admits_reach_creature():
    """A creature whose only keyword is ``"reach"`` passes the bridge-
    simple filter. Sister of
    :func:`test_simple_creature_filter_admits_safe_keyword_creature`
    pinning the round-45 extension on the production-deck loader path.
    """
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.parity.trajectory import (
        _printing_is_bridge_simple_creature,
    )

    reacher = CardPrinting(
        name="Synthetic Reacher",
        mana_cost_str="{1}{G}",
        mana_cost=ManaCost(generic=1, colored=(("G", 1),)),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=1,
        toughness=2,
        produces=frozenset(),
        keywords=frozenset({"reach"}),
    )
    assert _printing_is_bridge_simple_creature(reacher) is True


def test_simple_creature_filter_admits_flying_plus_reach_creature():
    """A creature carrying both ``"flying"`` and ``"reach"`` passes the
    bridge-simple filter — both keywords are in ``_SAFE_KEYWORDS`` post-
    round-45. Pins that the multi-keyword admit composes correctly
    (``frozenset.issubset`` over the safe set), so EoE creatures
    carrying reach alongside another safe keyword (e.g. multi-keyword
    standard-format cards) survive.
    """
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.parity.trajectory import (
        _printing_is_bridge_simple_creature,
    )

    flying_reacher = CardPrinting(
        name="Synthetic Flying Reacher",
        mana_cost_str="{2}{G}",
        mana_cost=ManaCost(generic=2, colored=(("G", 1),)),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=2,
        toughness=2,
        produces=frozenset(),
        keywords=frozenset({"flying", "reach"}),
    )
    assert _printing_is_bridge_simple_creature(flying_reacher) is True


def test_simple_creature_filter_rejects_reach_plus_unsafe_keyword():
    """A creature carrying ``"reach"`` PLUS an unsafe keyword (e.g.
    ``"flash"``) still fails the bridge-simple filter. Pins that
    admitting reach didn't loosen the gate on the unsafe direction —
    one unsafe keyword is enough to drop, regardless of how many safe
    keywords accompany it.
    """
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.parity.trajectory import (
        _printing_is_bridge_simple_creature,
    )

    reach_plus_flash = CardPrinting(
        name="Synthetic Reach Flasher",
        mana_cost_str="{2}{G}",
        mana_cost=ManaCost(generic=2, colored=(("G", 1),)),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=2,
        toughness=2,
        produces=frozenset(),
        keywords=frozenset({"reach", "flash"}),
    )
    assert _printing_is_bridge_simple_creature(reach_plus_flash) is False


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
    """A ``scry_n`` leaf under the DIES event is out of the safe set —
    rejected. (DIES carries surveil/gain_life/draw_cards today; scry_n
    is deliberately NOT in the DIES safe-effect-kinds tuple — no EoE
    consumer carries DIES+IsSelf+Scry. Repointed from the earlier
    DIES+draw_cards example, which the round-47 DIES+draw_cards slice
    converted to admit.)
    """
    from mtg_bot.parity.trajectory import _is_safe_trigger_dict

    assert not _is_safe_trigger_dict({
        "event": "dies",
        "predicate": {"kind": "source_is_self"},
        "effect": {"kind": "scry_n", "count": 1},
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


# ---------------------------------------------------------------------------
# Phase 6 carddef-triggers landfall extension (this slice).
#
# Adds the compound landfall predicate shape
# (``And(Subject(IsLand), Controlled(YOU))``) to the safe-trigger
# allowlist as the canonical sentinel kind
# ``"land_enters_controlled_by_you"``. The starter set's
# `(enters, source_is_self, ...)` triples stay in place; this
# extension adds `(enters, land_enters_controlled_by_you, gain_life)`
# and admits Eumidian Terrabotanist on the production-deck loader.
# ---------------------------------------------------------------------------


def test_safe_triggers_set_carries_landfall_gain_life_shape():
    """Pin the landfall extension entry — a future shrink would silently
    regress production-deck coverage of Eumidian Terrabotanist (the
    only EoE consumer this slice unblocks).
    """
    from mtg_bot.parity.trajectory import _SAFE_TRIGGERS

    assert (
        ("enters", "land_enters_controlled_by_you", "gain_life")
        in _SAFE_TRIGGERS
    )


def test_is_landfall_predicate_dict_admits_canonical_shape():
    """The landfall-predicate dict checker accepts the canonical
    ``and(subject_is_land, controlled_by_you)`` shape with the
    parser's left/right ordering.
    """
    from mtg_bot.parity.trajectory import _is_landfall_predicate_dict

    assert _is_landfall_predicate_dict({
        "kind": "and",
        "left": {"kind": "subject_is_land"},
        "right": {"kind": "controlled_by_you"},
    })


def test_is_landfall_predicate_dict_rejects_swapped_operand_order():
    """Operand ordering matters: the parser emits subject_is_land on
    the left and controlled_by_you on the right; the safe-trigger
    gate is strict on that ordering. A swapped variant is rejected
    until its own slice lands.
    """
    from mtg_bot.parity.trajectory import _is_landfall_predicate_dict

    assert not _is_landfall_predicate_dict({
        "kind": "and",
        "left": {"kind": "controlled_by_you"},
        "right": {"kind": "subject_is_land"},
    })


def test_is_landfall_predicate_dict_rejects_or_form():
    """An ``or`` compound — even with the same operands — is rejected.
    The starter landfall surface only covers AND.
    """
    from mtg_bot.parity.trajectory import _is_landfall_predicate_dict

    assert not _is_landfall_predicate_dict({
        "kind": "or",
        "left": {"kind": "subject_is_land"},
        "right": {"kind": "controlled_by_you"},
    })


def test_is_landfall_predicate_dict_rejects_extra_top_level_key():
    """Schema-strict: an extra key beyond {kind, left, right} is
    rejected so a future schema extension doesn't silently slip
    through the gate.
    """
    from mtg_bot.parity.trajectory import _is_landfall_predicate_dict

    assert not _is_landfall_predicate_dict({
        "kind": "and",
        "left": {"kind": "subject_is_land"},
        "right": {"kind": "controlled_by_you"},
        "negate": False,
    })


def test_is_safe_trigger_dict_admits_landfall_gain_life():
    """The full trigger-dict checker accepts a landfall+gain_life
    trigger built from the canonical compound predicate shape.
    """
    from mtg_bot.parity.trajectory import _is_safe_trigger_dict

    assert _is_safe_trigger_dict({
        "event": "enters",
        "predicate": {
            "kind": "and",
            "left": {"kind": "subject_is_land"},
            "right": {"kind": "controlled_by_you"},
        },
        "effect": {"kind": "gain_life", "amount": 1},
    })


def test_is_safe_trigger_dict_accepts_landfall_draw_cards():
    """Landfall+draw_cards is in the safe set as of the round-37 ZZ
    extension (this slice). Substrate is pre-positioned for any
    future bare landfall-draw printing; no EoE consumer is admitted
    today (Tannuk's draw rider is the bespoke second-time-bonus
    shape, not a bare ``DrawCards`` leaf), but the predicate-effect
    product is now structurally legal under the gate so the next
    slice landing such a card need not extend the allowlist again.
    """
    from mtg_bot.parity.trajectory import _is_safe_trigger_dict

    assert _is_safe_trigger_dict({
        "event": "enters",
        "predicate": {
            "kind": "and",
            "left": {"kind": "subject_is_land"},
            "right": {"kind": "controlled_by_you"},
        },
        "effect": {"kind": "draw_cards", "count": 1},
    })


def test_python_ta_to_safe_dict_round_trips_landfall_gain_life():
    """A Python ``TriggeredAbility`` carrying the parser-emitted
    landfall predicate (``And(Subject(IsLand), Controlled(YOU))``)
    + ``GainLife`` round-trips to the canonical compound dict shape.
    The result satisfies :func:`_is_safe_trigger_dict`.
    """
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.predicates import (
        And,
        Controlled,
        Event,
        Subject,
        YOU,
    )
    from mtg_bot.effects.object_predicates import IsLand
    from mtg_bot.effects.generic.life import GainLife
    from mtg_bot.parity.trajectory import (
        _is_safe_trigger_dict,
        _python_ta_to_safe_dict,
    )

    ta = TriggeredAbility(
        event=Event.ENTERS,
        predicate=And(
            left=Subject(slot=None, inner=IsLand()),
            right=Controlled(by=YOU, subject=None),
        ),
        effect=GainLife(amount=1),
    )
    d = _python_ta_to_safe_dict(ta)
    assert d == {
        "event": "enters",
        "predicate": {
            "kind": "and",
            "left": {"kind": "subject_is_land"},
            "right": {"kind": "controlled_by_you"},
        },
        "effect": {"kind": "gain_life", "amount": 1},
    }
    assert _is_safe_trigger_dict(d)


def test_python_ta_to_safe_dict_round_trips_landfall_with_draw_cards():
    """Landfall predicate + DrawCards effect is in the safe set as
    of this slice. The round-trip helper emits the canonical
    AND-nested predicate dict + bare draw_cards effect dict, and
    the result satisfies :func:`_is_safe_trigger_dict`.

    No EoE consumer is admitted today (Tannuk Memorial Ensign's
    draw is the bespoke second-time-bonus shape, not a bare
    ``DrawCards`` leaf); this test pins the substrate symmetry so
    a future EoE / standard-format landfall+draw printing lands
    cleanly without further allowlist surgery.
    """
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.predicates import (
        And,
        Controlled,
        Event,
        Subject,
        YOU,
    )
    from mtg_bot.effects.object_predicates import IsLand
    from mtg_bot.effects.generic.draw_mill import DrawCards
    from mtg_bot.parity.trajectory import (
        _is_safe_trigger_dict,
        _python_ta_to_safe_dict,
    )

    ta = TriggeredAbility(
        event=Event.ENTERS,
        predicate=And(
            left=Subject(slot=None, inner=IsLand()),
            right=Controlled(by=YOU, subject=None),
        ),
        effect=DrawCards(amount=1),
    )
    d = _python_ta_to_safe_dict(ta)
    assert d == {
        "event": "enters",
        "predicate": {
            "kind": "and",
            "left": {"kind": "subject_is_land"},
            "right": {"kind": "controlled_by_you"},
        },
        "effect": {"kind": "draw_cards", "count": 1},
    }
    assert _is_safe_trigger_dict(d)


def test_simple_creature_filter_admits_eumidian_terrabotanist():
    """End-to-end gate: the parser-emitted Eumidian Terrabotanist
    printing now passes :func:`_printing_is_bridge_simple_creature`.
    Pre-landfall-extension this returned False because the trigger
    predicate was unsafe; post-extension it's admitted, threading the
    creature into the production-deck loader.
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import (
        _printing_is_bridge_simple_creature,
    )

    src = OracleParserCardSource()
    eumidian = src.get_printings().get("Eumidian Terrabotanist")
    assert eumidian is not None, (
        "Eumidian Terrabotanist not in OracleParserCardSource — "
        "the parser dropped it; landfall-extension test cannot "
        "verify the production-deck unblock."
    )
    assert _printing_is_bridge_simple_creature(eumidian) is True


def test_simple_creature_filter_still_rejects_tannuk_memorial_ensign():
    """Tannuk shares the same landfall predicate as Eumidian but
    pairs it with the bespoke ``TannukEnsignLandfallEffect`` (deal
    damage + second-time-bonus draw). This slice intentionally
    leaves Tannuk on the cutting-room floor — it would need both a
    leaf-effect ``deal_damage_each_opponent`` arm AND a second-time-
    bonus state primitive. Pin the descope so future widening of
    the safe-trigger leaf set surfaces here.
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import (
        _printing_is_bridge_simple_creature,
    )

    src = OracleParserCardSource()
    tannuk = src.get_printings().get("Tannuk, Memorial Ensign")
    if tannuk is None:
        # Parser hasn't claimed it yet — descope rationale still
        # applies, but there's nothing to assert against.
        return
    assert _printing_is_bridge_simple_creature(tannuk) is False


def test_printing_to_card_def_carries_landfall_trigger_through():
    """Eumidian Terrabotanist's parsed printing converts to a CardDef
    whose ``triggered_abilities`` carries the canonical compound
    landfall dict shape — the same dict both engines' bridge arms
    consume.
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import _printing_to_card_def

    src = OracleParserCardSource()
    eumidian = src.get_printings()["Eumidian Terrabotanist"]
    cd = _printing_to_card_def(eumidian)
    assert cd.card_type == "Creature"
    assert cd.triggered_abilities == ({
        "event": "enters",
        "predicate": {
            "kind": "and",
            "left": {"kind": "subject_is_land"},
            "right": {"kind": "controlled_by_you"},
        },
        "effect": {"kind": "gain_life", "amount": 1},
    },)


# ---------------------------------------------------------------------------
# Phase 6 carddef-triggers landfall + pump_self_until_eot extension
# (this slice).
#
# Adds the SECOND safe leaf effect under the canonical landfall
# predicate: the bare ``pump_self_until_eot`` shape (``power_bonus``
# / ``toughness_bonus`` fields, no ``granted_keywords`` rider).
# Cross-engine bridge support landed in round 22 (cross-controller
# pump-self probe at commit 92ac9ec5). Admits Icecave Crasher
# (4/4 {3}{G}, Trample, "Landfall — +1/+0 UEOT") on the production-
# deck loader; sister Remnant Elemental (Reach, +2/+0 UEOT) carries
# the same effect shape but its Reach keyword stays outside today's
# `_SAFE_KEYWORDS` set.
# ---------------------------------------------------------------------------


def test_safe_triggers_set_carries_landfall_pump_self_shape():
    """Pin the landfall+pump_self_until_eot extension entry — a future
    shrink would silently regress production-deck coverage of Icecave
    Crasher (the EoE consumer this slice unblocks).
    """
    from mtg_bot.parity.trajectory import _SAFE_TRIGGERS

    assert (
        ("enters", "land_enters_controlled_by_you", "pump_self_until_eot")
        in _SAFE_TRIGGERS
    )


def test_safe_effect_keys_carries_pump_self_until_eot():
    """The effect-payload key whitelist gains the
    ``pump_self_until_eot`` arm with both ``power_bonus`` and
    ``toughness_bonus`` keys.
    """
    from mtg_bot.parity.trajectory import _SAFE_EFFECT_KEYS

    assert "pump_self_until_eot" in _SAFE_EFFECT_KEYS
    assert _SAFE_EFFECT_KEYS["pump_self_until_eot"] == frozenset(
        {"kind", "power_bonus", "toughness_bonus"}
    )


def test_is_safe_trigger_dict_admits_landfall_pump_self_until_eot():
    """The full trigger-dict checker accepts a landfall+pump_self
    trigger built from the canonical compound predicate shape and the
    bare ``power_bonus`` / ``toughness_bonus`` payload.
    """
    from mtg_bot.parity.trajectory import _is_safe_trigger_dict

    # Icecave Crasher's parser-emitted shape (+1/+0).
    assert _is_safe_trigger_dict({
        "event": "enters",
        "predicate": {
            "kind": "and",
            "left": {"kind": "subject_is_land"},
            "right": {"kind": "controlled_by_you"},
        },
        "effect": {
            "kind": "pump_self_until_eot",
            "power_bonus": 1,
            "toughness_bonus": 0,
        },
    })
    # Remnant Elemental's parser-emitted shape (+2/+0). The shape
    # itself passes the gate; the production-deck filter still drops
    # Remnant Elemental on its Reach keyword.
    assert _is_safe_trigger_dict({
        "event": "enters",
        "predicate": {
            "kind": "and",
            "left": {"kind": "subject_is_land"},
            "right": {"kind": "controlled_by_you"},
        },
        "effect": {
            "kind": "pump_self_until_eot",
            "power_bonus": 2,
            "toughness_bonus": 0,
        },
    })


def test_is_safe_trigger_dict_rejects_pump_self_under_source_is_self():
    """Pump_self under source_is_self is NOT in the safe set today —
    no clean EoE consumer (every non-landfall self-pump in EoE pairs
    with a granted-keywords rider or sits behind an activated
    ability). Pins the predicate-effect product gate from the OTHER
    direction: admitting an effect under landfall doesn't admit it
    under source_is_self.
    """
    from mtg_bot.parity.trajectory import _is_safe_trigger_dict

    assert not _is_safe_trigger_dict({
        "event": "enters",
        "predicate": {"kind": "source_is_self"},
        "effect": {
            "kind": "pump_self_until_eot",
            "power_bonus": 1,
            "toughness_bonus": 0,
        },
    })


def test_is_safe_trigger_dict_rejects_pump_self_with_extra_payload_key():
    """Schema-strict on the pump_self payload — an extra key beyond
    {kind, power_bonus, toughness_bonus} is rejected so a future
    schema extension (e.g. ``granted_keywords`` rider riding the
    same effect kind) doesn't silently slip through with the rider
    silently dropped on the cross-engine round trip.
    """
    from mtg_bot.parity.trajectory import _is_safe_trigger_dict

    assert not _is_safe_trigger_dict({
        "event": "enters",
        "predicate": {
            "kind": "and",
            "left": {"kind": "subject_is_land"},
            "right": {"kind": "controlled_by_you"},
        },
        "effect": {
            "kind": "pump_self_until_eot",
            "power_bonus": 1,
            "toughness_bonus": 0,
            "granted_keywords": ["haste"],
        },
    })


def test_python_ta_to_safe_dict_round_trips_landfall_pump_self():
    """A Python ``TriggeredAbility`` carrying the parser-emitted
    landfall predicate (``And(Subject(IsLand), Controlled(YOU))``)
    + bare ``PumpSelfUntilEOT`` round-trips to the canonical compound
    dict shape with ``power_bonus`` / ``toughness_bonus`` payload.
    The result satisfies :func:`_is_safe_trigger_dict`.
    """
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.predicates import (
        And,
        Controlled,
        Event,
        Subject,
        YOU,
    )
    from mtg_bot.effects.object_predicates import IsLand
    from mtg_bot.effects.generic.pump import PumpSelfUntilEOT
    from mtg_bot.parity.trajectory import (
        _is_safe_trigger_dict,
        _python_ta_to_safe_dict,
    )

    ta = TriggeredAbility(
        event=Event.ENTERS,
        predicate=And(
            left=Subject(slot=None, inner=IsLand()),
            right=Controlled(by=YOU, subject=None),
        ),
        effect=PumpSelfUntilEOT(power_bonus=1, toughness_bonus=0),
    )
    d = _python_ta_to_safe_dict(ta)
    assert d == {
        "event": "enters",
        "predicate": {
            "kind": "and",
            "left": {"kind": "subject_is_land"},
            "right": {"kind": "controlled_by_you"},
        },
        "effect": {
            "kind": "pump_self_until_eot",
            "power_bonus": 1,
            "toughness_bonus": 0,
        },
    }
    assert _is_safe_trigger_dict(d)


def test_python_ta_to_safe_dict_rejects_pump_self_with_granted_keywords():
    """A landfall+pump_self trigger that ALSO carries a non-empty
    ``granted_keywords`` rider is rejected. The Rust
    ``PumpSelfUntilEOT`` variant does NOT represent this rider, so
    admitting the trigger would silently drop the keyword grant on
    the round trip — a parity bug. Pins the rider-empty contract.
    No EoE landfall consumer carries the rider today (Icecave
    Crasher / Remnant Elemental both emit the bare shape) so this
    rejection isn't load-bearing on coverage; it's a defense
    against a future +X/+Y-and-gains-keyword landfall consumer
    slipping through.
    """
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.predicates import (
        And,
        Controlled,
        Event,
        Subject,
        YOU,
    )
    from mtg_bot.effects.object_predicates import IsLand
    from mtg_bot.effects.generic.pump import PumpSelfUntilEOT
    from mtg_bot.parity.trajectory import _python_ta_to_safe_dict

    ta = TriggeredAbility(
        event=Event.ENTERS,
        predicate=And(
            left=Subject(slot=None, inner=IsLand()),
            right=Controlled(by=YOU, subject=None),
        ),
        effect=PumpSelfUntilEOT(
            power_bonus=1,
            toughness_bonus=0,
            granted_keywords=frozenset({"haste"}),
        ),
    )
    assert _python_ta_to_safe_dict(ta) is None


def test_simple_creature_filter_admits_icecave_crasher():
    """End-to-end gate: the parser-emitted Icecave Crasher printing
    now passes :func:`_printing_is_bridge_simple_creature`. Pre-
    extension this returned False because the trigger predicate-
    effect cross was unsafe; post-extension it's admitted, threading
    Icecave Crasher into the production-deck loader.
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import (
        _printing_is_bridge_simple_creature,
    )

    src = OracleParserCardSource()
    icecave = src.get_printings().get("Icecave Crasher")
    assert icecave is not None, (
        "Icecave Crasher not in OracleParserCardSource — the parser "
        "dropped it; pump_self landfall extension test cannot verify "
        "the production-deck unblock."
    )
    assert _printing_is_bridge_simple_creature(icecave) is True


def test_simple_creature_filter_admits_remnant_elemental():
    """Remnant Elemental shares the same landfall+pump_self trigger
    shape as Icecave Crasher and pairs it with Reach. Pre-round-45
    this printing was the descope counterpart for the Icecave-Crasher
    admit (Reach was outside :data:`_SAFE_KEYWORDS`); the round-45
    extension admits ``"reach"`` as parity-clean (CR 702.17,
    ``test_reach_blocker_blocks_flying_attacker_parity``), and Remnant
    Elemental is now ADMITTED end-to-end.

    Pins the round-45 production-deck unblock — first EoE printing
    that flips from drop to admit specifically because of the reach
    extension.
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import (
        _printing_is_bridge_simple_creature,
        _python_ta_to_safe_dict,
    )

    src = OracleParserCardSource()
    remnant = src.get_printings().get("Remnant Elemental")
    if remnant is None:
        # Parser hasn't claimed it yet — admit rationale still
        # applies, but there's nothing to assert against.
        return
    # Trigger-side gate admits the +2/+0 landfall pump.
    assert len(remnant.triggered_abilities) == 1
    assert _python_ta_to_safe_dict(remnant.triggered_abilities[0]) is not None
    # Whole-printing gate now ADMITS post-round-45 (reach moved into
    # the safe set; the trigger and keyword gates both pass).
    assert _printing_is_bridge_simple_creature(remnant) is True


def test_printing_to_card_def_carries_landfall_pump_self_through():
    """Icecave Crasher's parsed printing converts to a CardDef whose
    ``triggered_abilities`` carries the canonical compound landfall
    dict shape with the bare pump_self payload — the same dict both
    engines' bridge arms consume.
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import _printing_to_card_def

    src = OracleParserCardSource()
    icecave = src.get_printings()["Icecave Crasher"]
    cd = _printing_to_card_def(icecave)
    assert cd.card_type == "Creature"
    assert "trample" in cd.keywords
    assert cd.triggered_abilities == ({
        "event": "enters",
        "predicate": {
            "kind": "and",
            "left": {"kind": "subject_is_land"},
            "right": {"kind": "controlled_by_you"},
        },
        "effect": {
            "kind": "pump_self_until_eot",
            "power_bonus": 1,
            "toughness_bonus": 0,
        },
    },)


def test_safe_triggers_set_carries_landfall_draw_cards_shape():
    """Pin the landfall+draw_cards extension entry (this slice). A
    future shrink would silently regress substrate coverage for any
    future EoE / standard-format bare landfall+draw printing — the
    extension is preventative today (no EoE consumer admitted; see
    docstring on the entry for why Tannuk's bespoke effect doesn't
    fit the bare-draw shape).
    """
    from mtg_bot.parity.trajectory import _SAFE_TRIGGERS

    assert (
        ("enters", "land_enters_controlled_by_you", "draw_cards")
        in _SAFE_TRIGGERS
    )


def test_is_safe_trigger_dict_rejects_landfall_draw_cards_with_extra_payload_key():
    """Schema-strict on the draw_cards payload under the landfall
    predicate too — same gate the source_is_self+draw_cards arm
    enforces. An extra key beyond {kind, count} is rejected so a
    future schema extension (e.g. an "each opponent" rider) doesn't
    silently slip through with the rider dropped on the cross-engine
    round trip. Mirrors the round-37 DDDD slice's pump_self
    extra-key reject-path test.
    """
    from mtg_bot.parity.trajectory import _is_safe_trigger_dict

    assert not _is_safe_trigger_dict({
        "event": "enters",
        "predicate": {
            "kind": "and",
            "left": {"kind": "subject_is_land"},
            "right": {"kind": "controlled_by_you"},
        },
        "effect": {
            "kind": "draw_cards",
            "count": 1,
            "each_opponent": True,
        },
    })


def test_simple_creature_filter_drops_tannuk_memorial_ensign_despite_landfall_draw_extension():
    """Pin that the landfall+draw_cards extension does NOT
    accidentally admit Tannuk, Memorial Ensign. Tannuk carries the
    canonical landfall predicate AND draws a card on second
    resolution per turn, but its parser-emitted effect is the
    bespoke ``TannukEnsignLandfallEffect`` (deal-damage-each-
    opponent + second-time-bonus draw composite) — NOT a bare
    ``DrawCards`` leaf. The gate must reject Tannuk's printing on
    the effect shape so the cross-engine bridge isn't asked to
    round-trip a class neither :func:`_python_ta_to_safe_dict` nor
    the dict-side bridge knows how to materialize.
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import _printing_is_bridge_simple_creature

    src = OracleParserCardSource()
    tannuk = src.get_printings()["Tannuk, Memorial Ensign"]
    # Sanity: Tannuk's printing carries the landfall predicate.
    assert len(tannuk.triggered_abilities) == 1
    assert type(tannuk.triggered_abilities[0].effect).__name__ == (
        "TannukEnsignLandfallEffect"
    )
    # The whole-printing gate still drops Tannuk — landfall+draw_cards
    # is in the safe set, but Tannuk's effect class is not the bare
    # DrawCards leaf the gate looks for.
    assert _printing_is_bridge_simple_creature(tannuk) is False


def test_filter_drops_dynamic_pt_formula_grovestrider():
    """Round-39 fix: Harmonious Grovestrider carries a
    ``dynamic_pt_formula`` (``*/*`` CDA — P/T each equal to lands
    controlled) that the CardDef bridge can't represent. The parser
    encodes the printed P/T as 0/0 placeholder; without the formula
    threaded across the bridge, Python materializes a literal 0/0
    creature on resolve and CR 704.5f SBA sends it to graveyard,
    while Rust keeps it on the battlefield (surfaced as
    ``cast_spell::graveyard_p0,battlefield`` in round-38 E1's bench
    smoke). The filter now rejects it so the cross-engine harness
    never sees the mistranslation. The card's real engine-side
    behavior (the ``harmonious_grovestrider`` arm in
    ``game._dynamic_base_pt``) is unaffected — only the bridge-
    crossing path is gated off.
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import _printing_is_bridge_simple_creature

    src = OracleParserCardSource()
    p = src.get_printings()["Harmonious Grovestrider"]
    assert p.dynamic_pt_formula == "harmonious_grovestrider"
    assert _printing_is_bridge_simple_creature(p) is False


def test_filter_drops_dynamic_pt_formula_cosmogoyf_emissary():
    """Sister cards to Grovestrider — both carry ``dynamic_pt_formula``
    placeholders that the bridge can't round-trip. Cosmogoyf (0/1
    placeholder; P=exile-count, T=exile-count+1) and Emissary Escort
    (1/2 with +X/+0 from greatest other-artifact MV) both leak the
    same bridge gap as Grovestrider. Drop them at the filter rather
    than ship them as 0/1 / 0/4 vanillas across the bridge.
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import _printing_is_bridge_simple_creature

    src = OracleParserCardSource()
    printings = src.get_printings()
    cosmogoyf = printings["Cosmogoyf"]
    assert cosmogoyf.dynamic_pt_formula == "cosmogoyf"
    assert _printing_is_bridge_simple_creature(cosmogoyf) is False
    emissary = printings["Emissary Escort"]
    assert emissary.dynamic_pt_formula == "emissary_escort"
    assert _printing_is_bridge_simple_creature(emissary) is False


def test_filter_drops_ward_cost_bearers():
    """Round-39 fix: the CardDef bridge doesn't carry ``ward_cost``,
    so any Ward-bearing creature bridges as a bare no-Ward creature
    on both engines. That's bit-equal under the bench's ``attack_all``
    strategy (the attacker never targets the warded creature), but
    a future targeted-spell trajectory probe would surface as a
    mystery divergence. Drop these at the filter today so the
    substrate stays honest. Lockstep with the
    ``dynamic_pt_formula`` drop above — Grovestrider carries BOTH
    (covered above); these are the bare-Ward sisters.
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import _printing_is_bridge_simple_creature

    src = OracleParserCardSource()
    printings = src.get_printings()
    # Pick at least one Ward-only creature (no other unsafe field) to
    # prove the ward_cost branch IS the rejecting check. Mouth of the
    # Storm and Famished Worldsire are the obvious candidates; both
    # are EoE creatures with ward but no triggered ability that would
    # already disqualify them.
    for name in ("Mouth of the Storm", "Famished Worldsire"):
        p = printings.get(name)
        if p is None:
            continue
        assert p.ward_cost is not None
        assert _printing_is_bridge_simple_creature(p) is False


def test_python_ta_to_safe_dict_preserves_landfall_draw_cards_count():
    """The draw_cards count round-trips as the parsed Python integer;
    the round-trip helper preserves the count value as-is. Pins the
    count payload field's typed-int contract so a future strict-
    validate-on-Rust-side doesn't surface as a bridge fault.
    """
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.predicates import (
        And,
        Controlled,
        Event,
        Subject,
        YOU,
    )
    from mtg_bot.effects.object_predicates import IsLand
    from mtg_bot.effects.generic.draw_mill import DrawCards
    from mtg_bot.parity.trajectory import _python_ta_to_safe_dict

    ta = TriggeredAbility(
        event=Event.ENTERS,
        predicate=And(
            left=Subject(slot=None, inner=IsLand()),
            right=Controlled(by=YOU, subject=None),
        ),
        effect=DrawCards(amount=2),
    )
    d = _python_ta_to_safe_dict(ta)
    assert d is not None
    assert d["effect"] == {"kind": "draw_cards", "count": 2}


# ---------------------------------------------------------------------------
# Phase 6 carddef-triggers surveil extension (round-42 slice).
#
# Adds two NEW entries to :data:`_SAFE_TRIGGERS`:
#   * ``("enters", "source_is_self", "surveil")``
#   * ``("dies", "source_is_self", "surveil")``
# Plus the ``"surveil"`` arm in :data:`_SAFE_EFFECT_KEYS`
# (single ``count`` payload key) and the bare-shape
# ``isinstance(eff, Surveil)`` recognizer in
# :func:`_python_ta_to_safe_dict` (gated on
# ``use_artifact_count=False`` so the Surveil-X variant doesn't
# silently degrade across the bridge).
#
# The DIES event is also wired into the per-trigger event gate
# (previously ENTERS-only) so Thawbringer / Wary Watchdog — both of
# whose surveil trigger pair carries BOTH events — round-trip
# cleanly. Without DIES support the whole printing would still be
# dropped because the bridge-simple filter requires EVERY trigger to
# round-trip.
#
# Cross-engine bridge support pre-existed:
#   * Rust ``Effect::Surveil { count: i32 }`` resolve arm at
#     ``state_ops_resolve.rs:2610-2649``; the auto-resolve default
#     ``keep_all_on_top`` terminal drain at
#     ``state_ops_resolve.rs:6832`` is invoked after every
#     triggered-ability resolve, so no agent setup is needed for the
#     trajectory walk.
#   * Python ``Surveil(amount, use_artifact_count)`` resolve arm at
#     ``effects/generic/library_lookat.py:569``; the
#     ``p.agent is None`` short-circuit at line 605 mirrors Rust's
#     keep_all_on_top default — every observed card stays on the
#     library top, graveyard unchanged.
#   * Bridge translator arm ``cross_engine._ta_dict_to_python_effect``
#     "surveil" since round 16 (the scry/surveil slice).
#
# Cards admitted on EoE today (3 net new):
#   * Thawbringer (4/2 {2}{G}, ENTERS+surveil 1 AND DIES+surveil 1)
#   * Wary Watchdog (3/1 {1}{G}, ENTERS+surveil 1 AND DIES+surveil 1)
#   * Wurmwall Sweeper (2/2 {2}, ENTERS+surveil 2)
# ---------------------------------------------------------------------------


def test_safe_triggers_set_carries_surveil_enters_shape():
    """Pin the ENTERS+source_is_self+surveil entry (this slice)."""
    from mtg_bot.parity.trajectory import _SAFE_TRIGGERS

    assert (
        ("enters", "source_is_self", "surveil") in _SAFE_TRIGGERS
    )


def test_safe_triggers_set_carries_surveil_dies_shape():
    """Pin the DIES+source_is_self+surveil entry (this slice). The
    DIES extension is the FIRST DIES entry in the safe set; admits
    Thawbringer / Wary Watchdog (both carry the trigger pair on
    enters AND dies).
    """
    from mtg_bot.parity.trajectory import _SAFE_TRIGGERS

    assert (
        ("dies", "source_is_self", "surveil") in _SAFE_TRIGGERS
    )


def test_safe_effect_keys_carries_surveil_count_payload():
    """The surveil arm carries a single ``count`` payload key (mirrors
    Rust's ``Effect::Surveil { count: i32 }`` variant). The Python
    ``Surveil.use_artifact_count`` flag is NOT in the safe payload
    keys — gated separately in :func:`_python_ta_to_safe_dict`.
    """
    from mtg_bot.parity.trajectory import _SAFE_EFFECT_KEYS

    assert _SAFE_EFFECT_KEYS["surveil"] == frozenset({"kind", "count"})


def test_is_safe_trigger_dict_admits_surveil_enters_shape():
    """Dict-side recognizer admits the canonical ENTERS+source_is_self
    +surveil dict shape with the bare ``count`` payload.
    """
    from mtg_bot.parity.trajectory import _is_safe_trigger_dict

    assert _is_safe_trigger_dict({
        "event": "enters",
        "predicate": {"kind": "source_is_self"},
        "effect": {"kind": "surveil", "count": 1},
    })


def test_is_safe_trigger_dict_admits_surveil_dies_shape():
    """Dict-side recognizer admits the DIES variant. Mirrors the ENTERS
    test above with a DIES event — both shapes are in the round-42
    safe set.
    """
    from mtg_bot.parity.trajectory import _is_safe_trigger_dict

    assert _is_safe_trigger_dict({
        "event": "dies",
        "predicate": {"kind": "source_is_self"},
        "effect": {"kind": "surveil", "count": 2},
    })


def test_is_safe_trigger_dict_rejects_surveil_with_extra_payload_key():
    """Schema-strict on the surveil payload — same gate the
    source_is_self+draw_cards arm enforces. An extra key beyond
    {kind, count} is rejected so a future schema extension (e.g. a
    ``use_artifact_count`` Surveil-X rider) doesn't silently slip
    through with the rider dropped on the cross-engine round trip.
    """
    from mtg_bot.parity.trajectory import _is_safe_trigger_dict

    assert not _is_safe_trigger_dict({
        "event": "enters",
        "predicate": {"kind": "source_is_self"},
        "effect": {
            "kind": "surveil",
            "count": 1,
            "use_artifact_count": True,
        },
    })


def test_is_safe_trigger_dict_rejects_surveil_under_landfall_predicate():
    """The predicate-effect product gate is strict — surveil under the
    canonical landfall compound predicate is NOT in today's safe set
    (no parser-emitted EoE consumer carries that shape). The dict
    recognizer rejects it even though both the surveil effect and
    the landfall predicate are individually in the safe set under
    OTHER products.
    """
    from mtg_bot.parity.trajectory import _is_safe_trigger_dict

    assert not _is_safe_trigger_dict({
        "event": "enters",
        "predicate": {
            "kind": "and",
            "left": {"kind": "subject_is_land"},
            "right": {"kind": "controlled_by_you"},
        },
        "effect": {"kind": "surveil", "count": 1},
    })


def test_python_ta_to_safe_dict_round_trips_surveil_enters():
    """Python ``TriggeredAbility`` carrying ENTERS+IsSelf+Surveil
    converts back to the canonical dict shape; the result satisfies
    :func:`_is_safe_trigger_dict`. Pins the Python ``Surveil.amount``
    → dict ``count`` translation (same convention as the round-16
    scry arm).
    """
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.predicates import IsSelf, Event
    from mtg_bot.effects.generic.library_lookat import Surveil
    from mtg_bot.parity.trajectory import (
        _is_safe_trigger_dict,
        _python_ta_to_safe_dict,
    )

    ta = TriggeredAbility(
        event=Event.ENTERS,
        predicate=IsSelf(),
        effect=Surveil(amount=2),
    )
    d = _python_ta_to_safe_dict(ta)
    assert d == {
        "event": "enters",
        "predicate": {"kind": "source_is_self"},
        "effect": {"kind": "surveil", "count": 2},
    }
    assert _is_safe_trigger_dict(d)


def test_python_ta_to_safe_dict_round_trips_surveil_dies():
    """Python ``TriggeredAbility`` carrying DIES+IsSelf+Surveil also
    round-trips. Closes the DIES event recognizer wired into
    :func:`_python_ta_to_safe_dict`'s event-string gate this slice.
    """
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.predicates import IsSelf, Event
    from mtg_bot.effects.generic.library_lookat import Surveil
    from mtg_bot.parity.trajectory import (
        _is_safe_trigger_dict,
        _python_ta_to_safe_dict,
    )

    ta = TriggeredAbility(
        event=Event.DIES,
        predicate=IsSelf(),
        effect=Surveil(amount=1),
    )
    d = _python_ta_to_safe_dict(ta)
    assert d == {
        "event": "dies",
        "predicate": {"kind": "source_is_self"},
        "effect": {"kind": "surveil", "count": 1},
    }
    assert _is_safe_trigger_dict(d)


def test_python_ta_to_safe_dict_rejects_surveil_with_use_artifact_count():
    """Surveil-X (``use_artifact_count=True``) is the variant the
    bridge does NOT model — Rust's ``Effect::Surveil { count: i32 }``
    carries only the fixed-count form. The recognizer must reject the
    X variant so it falls through to the filter drop path rather than
    silently degrading to a fixed surveil-N on cross-engine round
    trip. Mirrors the round-37 DDDD slice's PumpSelfUntilEOT
    granted_keywords reject-path test.
    """
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.predicates import IsSelf, Event
    from mtg_bot.effects.generic.library_lookat import Surveil
    from mtg_bot.parity.trajectory import _python_ta_to_safe_dict

    ta = TriggeredAbility(
        event=Event.ENTERS,
        predicate=IsSelf(),
        effect=Surveil(amount=1, use_artifact_count=True),
    )
    assert _python_ta_to_safe_dict(ta) is None


def test_python_ta_to_safe_dict_rejects_dies_event_with_non_surveil_or_gain_life_effect():
    """The DIES event gate is narrower than the ENTERS gate — only the
    surveil leaf (round-42), the gain_life leaf (round-47), and the
    draw_cards leaf (round-47 sister slice) are in the safe set under
    DIES. ``scry_n`` / ``pump_self_until_eot`` remain outside today. A
    DIES+IsSelf+Scry trigger must still be rejected because the
    corresponding triple isn't in :data:`_SAFE_TRIGGERS`. Pins the
    per-event safe-effect-kinds table so future DIES extensions remain
    single edits at the safe-set source. (Repointed from the earlier
    DIES+DrawCards example, which the round-47 DIES+draw_cards slice
    converted to admit.)
    """
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.predicates import IsSelf, Event
    from mtg_bot.effects.generic.library_lookat import Scry
    from mtg_bot.parity.trajectory import _python_ta_to_safe_dict

    ta = TriggeredAbility(
        event=Event.DIES,
        predicate=IsSelf(),
        effect=Scry(amount=1),
    )
    assert _python_ta_to_safe_dict(ta) is None


def test_simple_creature_filter_admits_surveil_etb_only_creature():
    """A bare-vanilla creature carrying only ENTERS+IsSelf+Surveil
    passes the bridge-simple filter end-to-end. Constructs the
    printing in-line (no Scryfall dependency) so the test pins the
    filter contract independent of any production-deck data churn.
    """
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.predicates import IsSelf, Event
    from mtg_bot.effects.generic.library_lookat import Surveil
    from mtg_bot.parity.trajectory import _printing_is_bridge_simple_creature

    printing = CardPrinting(
        name="ProbeSurveilBear",
        mana_cost_str="{1}{G}",
        mana_cost=ManaCost(generic=1, colored=(("G", 1),)),
        type_line="Creature - Bear",
        supertypes=(),
        card_types=("Creature",),
        subtypes=("Bear",),
        power=2,
        toughness=2,
        produces=frozenset(),
        triggered_abilities=(
            TriggeredAbility(
                event=Event.ENTERS,
                predicate=IsSelf(),
                effect=Surveil(amount=1),
            ),
        ),
    )
    assert _printing_is_bridge_simple_creature(printing) is True


def test_simple_creature_filter_admits_real_eoe_wary_watchdog():
    """Pin that Wary Watchdog (3/1 {1}{G}, ENTERS+surveil 1 AND
    DIES+surveil 1) — the canonical EoE consumer carrying BOTH the
    new ENTERS and DIES safe-trigger shapes — survives the production
    -deck filter. Pre-extension this card was rejected because the
    DIES+surveil trigger had no matching entry in
    :data:`_SAFE_TRIGGERS` and the recognizer's event gate rejected
    DIES outright; post-extension the gate accepts both, the
    recognizer round-trips both shapes, and the whole printing
    passes.
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import _printing_is_bridge_simple_creature

    src = OracleParserCardSource()
    watchdog = src.get_printings()["Wary Watchdog"]
    # Sanity: Watchdog carries the trigger pair this slice admits.
    assert len(watchdog.triggered_abilities) == 2
    events = sorted(ta.event.value for ta in watchdog.triggered_abilities)
    assert events == ["dies", "enters"]
    # Both triggers are bare Surveil(1).
    for ta in watchdog.triggered_abilities:
        assert type(ta.effect).__name__ == "Surveil"
        assert ta.effect.amount == 1
        assert ta.effect.use_artifact_count is False
    # Post-extension the whole printing passes the bridge filter.
    assert _printing_is_bridge_simple_creature(watchdog) is True


def test_simple_creature_filter_drops_skullsnap_nuisance_despite_surveil_extension():
    """Pin that the surveil extension does NOT accidentally admit
    Skullsnap Nuisance. Skullsnap carries surveil triggers, but
    BOTH of them are outside the round-42 safe set:
      * ENTERS predicate is a compound ``And`` (NOT bare IsSelf — the
        Skullsnap shape includes a tier/threshold condition).
      * The second trigger fires on ``ROOM_FULLY_UNLOCKED``, an event
        not in any safe-trigger entry.
    The whole-printing gate must reject Skullsnap so the cross-engine
    bridge isn't asked to round-trip trigger shapes it doesn't know
    how to materialize.
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import _printing_is_bridge_simple_creature

    src = OracleParserCardSource()
    skullsnap = src.get_printings()["Skullsnap Nuisance"]
    assert len(skullsnap.triggered_abilities) == 2
    # The whole-printing gate still drops Skullsnap on either
    # trigger's unsafe shape — the surveil-leaf bridging alone
    # doesn't compose with the compound / room-event predicate.
    assert _printing_is_bridge_simple_creature(skullsnap) is False


# ---------------------------------------------------------------------------
# Phase 6 carddef-triggers surveil ATTACKS extension (round-43 slice).
#
# Adds ONE new entry to :data:`_SAFE_TRIGGERS`:
#   * ``("attacks", "source_is_self", "surveil")``
# Plus widens the per-trigger event gate in
# :func:`_python_ta_to_safe_dict` from {ENTERS, DIES} to
# {ENTERS, DIES, ATTACKS}, and adds the ``"attacks"`` event-string
# emitter arm. The :data:`_SAFE_EFFECT_KEYS` table is unchanged from
# round-42 — the surveil arm's payload-key whitelist (``{"kind",
# "count"}``) is identical regardless of the dispatch event.
#
# Bridge support pre-existed in BOTH engines:
#   * Rust ATTACKS event dispatch via ``state_ops_combat.rs:684``
#     (Slice 7 of the carddef-triggers ramp).
#   * Python ATTACKS dispatch via ``combat.py:_fire_attacks_triggers``
#     (combat.py:196).
#   * Surveil leaf bridge arm at
#     ``cross_engine._ta_dict_to_python_effect`` "surveil" since round
#     16 (the scry/surveil slice); resolve arm contract is identical
#     to round-42's ENTERS/DIES surveil — keep_all_on_top default on
#     both engines, no agent setup required for the trajectory walk.
#
# No real-EoE consumer admitted today (substrate-only, sister of the
# round-37 DDDD landfall+draw slice's no-consumer extension).
# Fear of Surveillance (2/2 {1}{W}, Vigilance, ATTACKS+IsSelf+
# Surveil(1)) is the canonical EoE printing carrying the bare shape
# but is absent from the 17lands deck pool (low pick rate).
# Appendage Amalgam carries the same trigger but its ``Flash``
# keyword is outside today's :data:`_SAFE_KEYWORDS` set.
# ---------------------------------------------------------------------------


def test_safe_triggers_set_carries_surveil_attacks_shape():
    """Pin the ATTACKS+source_is_self+surveil entry (this slice). The
    THIRD event in the safe set after ENTERS (Slice 1) and DIES
    (round 42).
    """
    from mtg_bot.parity.trajectory import _SAFE_TRIGGERS

    assert (
        ("attacks", "source_is_self", "surveil") in _SAFE_TRIGGERS
    )


def test_is_safe_trigger_dict_admits_surveil_attacks_shape():
    """Dict-side recognizer admits the canonical ATTACKS+source_is_self
    +surveil dict shape with the bare ``count`` payload.
    """
    from mtg_bot.parity.trajectory import _is_safe_trigger_dict

    assert _is_safe_trigger_dict({
        "event": "attacks",
        "predicate": {"kind": "source_is_self"},
        "effect": {"kind": "surveil", "count": 1},
    })


def test_python_ta_to_safe_dict_round_trips_surveil_attacks():
    """Python ``TriggeredAbility`` carrying ATTACKS+IsSelf+Surveil
    converts back to the canonical dict shape; the result satisfies
    :func:`_is_safe_trigger_dict`. Closes the ATTACKS event recognizer
    wired into :func:`_python_ta_to_safe_dict`'s event-string gate
    this slice.
    """
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.predicates import IsSelf, Event
    from mtg_bot.effects.generic.library_lookat import Surveil
    from mtg_bot.parity.trajectory import (
        _is_safe_trigger_dict,
        _python_ta_to_safe_dict,
    )

    ta = TriggeredAbility(
        event=Event.ATTACKS,
        predicate=IsSelf(),
        effect=Surveil(amount=1),
    )
    d = _python_ta_to_safe_dict(ta)
    assert d == {
        "event": "attacks",
        "predicate": {"kind": "source_is_self"},
        "effect": {"kind": "surveil", "count": 1},
    }
    assert _is_safe_trigger_dict(d)


def test_python_ta_to_safe_dict_rejects_attacks_event_with_non_safe_effect():
    """Round-44 widens the ATTACKS arm to admit ``draw_cards`` and
    ``gain_life`` alongside round-43's ``surveil`` — but ``scry_n``
    remains OUT of the safe set under ATTACKS (no EoE consumer; see the
    round-44 ``_SAFE_TRIGGERS`` ATTACKS+draw_cards/gain_life docstring
    for the consumer survey). Pin the negative case so the recognizer's
    per-event narrowing under the ``elif ta.event is Event.ATTACKS``
    arm stays honest. Sister of the round-42 DIES+non-surveil reject-
    path test — both anchor the per-event narrowing.
    """
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.predicates import IsSelf, Event
    from mtg_bot.effects.generic.library_lookat import Scry
    from mtg_bot.parity.trajectory import _python_ta_to_safe_dict

    ta = TriggeredAbility(
        event=Event.ATTACKS,
        predicate=IsSelf(),
        effect=Scry(amount=1),
    )
    assert _python_ta_to_safe_dict(ta) is None


def test_python_ta_to_safe_dict_rejects_attacks_surveil_with_use_artifact_count():
    """Surveil-X under the ATTACKS event is also gated out (mirrors the
    round-42 ENTERS reject-path test). Rust's ``Effect::Surveil
    { count: i32 }`` carries only the fixed-count form regardless of
    dispatch event — gating the X variant at the recognizer keeps the
    bridge from silently degrading it on a hypothetical future
    ATTACKS+IsSelf+Surveil(X) printing.
    """
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.predicates import IsSelf, Event
    from mtg_bot.effects.generic.library_lookat import Surveil
    from mtg_bot.parity.trajectory import _python_ta_to_safe_dict

    ta = TriggeredAbility(
        event=Event.ATTACKS,
        predicate=IsSelf(),
        effect=Surveil(amount=1, use_artifact_count=True),
    )
    assert _python_ta_to_safe_dict(ta) is None


def test_simple_creature_filter_admits_attacks_surveil_only_creature():
    """A bare-vanilla creature carrying only ATTACKS+IsSelf+Surveil
    passes the bridge-simple filter end-to-end. Constructs the
    printing in-line (no Scryfall dependency) so the test pins the
    filter contract independent of any production-deck data churn.
    Mirrors the round-42 ETB-only surveil filter-admit test.
    """
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.predicates import IsSelf, Event
    from mtg_bot.effects.generic.library_lookat import Surveil
    from mtg_bot.parity.trajectory import _printing_is_bridge_simple_creature

    printing = CardPrinting(
        name="ProbeAttacksSurveilBear",
        mana_cost_str="{1}{W}",
        mana_cost=ManaCost(generic=1, colored=(("W", 1),)),
        type_line="Creature - Bear",
        supertypes=(),
        card_types=("Creature",),
        subtypes=("Bear",),
        power=2,
        toughness=2,
        produces=frozenset(),
        triggered_abilities=(
            TriggeredAbility(
                event=Event.ATTACKS,
                predicate=IsSelf(),
                effect=Surveil(amount=1),
            ),
        ),
    )
    assert _printing_is_bridge_simple_creature(printing) is True


def test_simple_creature_filter_admits_real_eoe_fear_of_surveillance():
    """Pin that Fear of Surveillance (1/2 {1}{W}, Vigilance, ATTACKS+
    IsSelf+Surveil(1)) — the canonical EoE consumer carrying the new
    safe-trigger shape this slice adds — survives the bridge-simple
    filter end-to-end. Pre-extension this card was rejected because
    the ATTACKS+IsSelf+Surveil trigger had no matching entry in
    :data:`_SAFE_TRIGGERS` and the recognizer's event gate rejected
    ATTACKS outright; post-extension the gate accepts ATTACKS, the
    recognizer round-trips the shape, and the whole printing passes.

    Note: Fear of Surveillance is in the Scryfall EoE set but ABSENT
    from the 17lands deck pool (data/17lands/eoe_decks.json.gz) — so
    the production-deck loader doesn't see it today. This test pins
    the filter contract directly off the Scryfall-parsed printing so
    the substrate is exercised regardless of deck-pool churn.
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import _printing_is_bridge_simple_creature

    src = OracleParserCardSource()
    printings = src.get_printings()
    assert "Fear of Surveillance" in printings, (
        "Fear of Surveillance no longer in the EoE Scryfall data; "
        "pick a different ATTACKS+IsSelf+Surveil consumer after "
        "re-scanning the set, or remove this test if the round-43 "
        "substrate is later subsumed by a broader event extension."
    )
    fos = printings["Fear of Surveillance"]
    # Sanity: Fear of Surveillance carries the trigger this slice admits.
    assert len(fos.triggered_abilities) == 1
    ta = fos.triggered_abilities[0]
    assert ta.event.value == "attacks"
    assert type(ta.effect).__name__ == "Surveil"
    assert ta.effect.amount == 1
    assert ta.effect.use_artifact_count is False
    # Post-extension the whole printing passes the bridge filter.
    assert _printing_is_bridge_simple_creature(fos) is True


def test_printing_to_card_def_carries_attacks_surveil_through():
    """Fear of Surveillance's parsed printing converts to a CardDef
    whose ``triggered_abilities`` tuple carries the canonical
    ATTACKS+surveil 1 dict shape — exactly what the cross_engine
    bridge arms on both engines consume.
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import _printing_to_card_def

    src = OracleParserCardSource()
    fos = src.get_printings()["Fear of Surveillance"]
    cd = _printing_to_card_def(fos)
    assert cd.card_type == "Creature"
    assert cd.power == 2
    assert cd.toughness == 2
    assert len(cd.triggered_abilities) == 1
    assert cd.triggered_abilities[0] == {
        "event": "attacks",
        "predicate": {"kind": "source_is_self"},
        "effect": {"kind": "surveil", "count": 1},
    }


def test_printing_to_card_def_carries_surveil_etb_through():
    """Wary Watchdog's parsed printing converts to a CardDef whose
    ``triggered_abilities`` tuple carries BOTH the ENTERS+surveil 1
    and DIES+surveil 1 canonical dict shapes — exactly what the
    cross_engine bridge arms on both engines consume.
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import _printing_to_card_def

    src = OracleParserCardSource()
    watchdog = src.get_printings()["Wary Watchdog"]
    cd = _printing_to_card_def(watchdog)
    assert cd.card_type == "Creature"
    assert cd.power == 3
    assert cd.toughness == 1
    # Both triggers land on the CardDef in dict-round-trip shape; the
    # ENTERS arm comes first in printing.triggered_abilities order, so
    # the dict tuple preserves that ordering.
    assert len(cd.triggered_abilities) == 2
    entries = sorted(
        cd.triggered_abilities, key=lambda d: d["event"],
    )
    assert entries == [
        {
            "event": "dies",
            "predicate": {"kind": "source_is_self"},
            "effect": {"kind": "surveil", "count": 1},
        },
        {
            "event": "enters",
            "predicate": {"kind": "source_is_self"},
            "effect": {"kind": "surveil", "count": 1},
        },
    ]


# ---------------------------------------------------------------------------
# Phase 6 carddef-triggers ATTACKS+draw_cards/gain_life extension
# (round-44 slice).
#
# Adds TWO new entries to :data:`_SAFE_TRIGGERS`:
#   * ``("attacks", "source_is_self", "draw_cards")``
#   * ``("attacks", "source_is_self", "gain_life")``
# Plus widens the ATTACKS arm of :func:`_python_ta_to_safe_dict`'s
# ``IsSelf`` branch from ``{"surveil"}`` (round 43) to
# ``{"surveil", "draw_cards", "gain_life"}``. The
# :data:`_SAFE_EFFECT_KEYS` table is unchanged from round-43 — the
# ``draw_cards`` / ``gain_life`` payload-key whitelists were defined
# in round 1 of Phase 6 and are event-agnostic.
#
# Bridge support pre-existed in BOTH engines:
#   * Rust ATTACKS event dispatch via ``state_ops_combat.rs:684``
#     (round-43 verification slice).
#   * Python ATTACKS dispatch via ``combat.py:_fire_attacks_triggers``
#     (combat.py:196).
#   * ``draw_cards`` / ``gain_life`` leaf bridge arms at
#     ``cross_engine._ta_dict_to_python_effect`` since round 1 of
#     Phase 6 carddef-triggers; both leaves are deterministic
#     (zone-move and scalar update respectively) so the resolve
#     contract is bit-equal across engines without any agent setup.
#
# No real-EoE consumer admitted today (substrate-only, sister of the
# round-43 ATTACKS+surveil slice's no-consumer extension). Survey via
# ``scripts/scout_archetype_admit_simulation.py`` (round-44 update)
# confirms zero EoE creatures carry the bare ATTACKS+IsSelf+
# DrawCards or ATTACKS+IsSelf+GainLife shape with all other gates
# clean.
# ---------------------------------------------------------------------------


def test_safe_triggers_set_carries_attacks_draw_cards_shape():
    """Pin the ATTACKS+source_is_self+draw_cards entry (this slice).
    The SECOND ATTACKS leaf in the safe set after round-43's
    surveil-ATTACKS.
    """
    from mtg_bot.parity.trajectory import _SAFE_TRIGGERS

    assert (
        ("attacks", "source_is_self", "draw_cards") in _SAFE_TRIGGERS
    )


def test_safe_triggers_set_carries_attacks_gain_life_shape():
    """Pin the ATTACKS+source_is_self+gain_life entry (this slice).
    The THIRD ATTACKS leaf in the safe set, sister to draw_cards
    above.
    """
    from mtg_bot.parity.trajectory import _SAFE_TRIGGERS

    assert (
        ("attacks", "source_is_self", "gain_life") in _SAFE_TRIGGERS
    )


def test_is_safe_trigger_dict_admits_attacks_draw_cards_shape():
    """Dict-side recognizer admits the canonical ATTACKS+source_is_self
    +draw_cards dict shape with the bare ``count`` payload (sister of
    the round-1 ENTERS+IsSelf+draw_cards admit).
    """
    from mtg_bot.parity.trajectory import _is_safe_trigger_dict

    assert _is_safe_trigger_dict({
        "event": "attacks",
        "predicate": {"kind": "source_is_self"},
        "effect": {"kind": "draw_cards", "count": 1},
    })


def test_is_safe_trigger_dict_admits_attacks_gain_life_shape():
    """Dict-side recognizer admits the canonical ATTACKS+source_is_self
    +gain_life dict shape with the bare ``amount`` payload.
    """
    from mtg_bot.parity.trajectory import _is_safe_trigger_dict

    assert _is_safe_trigger_dict({
        "event": "attacks",
        "predicate": {"kind": "source_is_self"},
        "effect": {"kind": "gain_life", "amount": 2},
    })


def test_python_ta_to_safe_dict_round_trips_attacks_draw_cards():
    """Python ``TriggeredAbility`` carrying ATTACKS+IsSelf+DrawCards
    converts back to the canonical dict shape; the result satisfies
    :func:`_is_safe_trigger_dict`. Closes the round-44 ATTACKS arm
    extension that adds ``draw_cards`` to the per-event safe-effect-
    kinds tuple alongside round-43's ``surveil``.
    """
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.predicates import IsSelf, Event
    from mtg_bot.effects.generic.draw_mill import DrawCards
    from mtg_bot.parity.trajectory import (
        _is_safe_trigger_dict,
        _python_ta_to_safe_dict,
    )

    ta = TriggeredAbility(
        event=Event.ATTACKS,
        predicate=IsSelf(),
        effect=DrawCards(amount=1),
    )
    d = _python_ta_to_safe_dict(ta)
    assert d == {
        "event": "attacks",
        "predicate": {"kind": "source_is_self"},
        "effect": {"kind": "draw_cards", "count": 1},
    }
    assert _is_safe_trigger_dict(d)


def test_python_ta_to_safe_dict_round_trips_attacks_gain_life():
    """Python ``TriggeredAbility`` carrying ATTACKS+IsSelf+GainLife
    converts back to the canonical dict shape; the result satisfies
    :func:`_is_safe_trigger_dict`. Sister to draw_cards above —
    pinned independently because the recognizer's effect-arm
    dispatch goes through a separate ``isinstance(eff, GainLife)``
    branch.
    """
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.predicates import IsSelf, Event
    from mtg_bot.effects.generic.life import GainLife
    from mtg_bot.parity.trajectory import (
        _is_safe_trigger_dict,
        _python_ta_to_safe_dict,
    )

    ta = TriggeredAbility(
        event=Event.ATTACKS,
        predicate=IsSelf(),
        effect=GainLife(amount=2),
    )
    d = _python_ta_to_safe_dict(ta)
    assert d == {
        "event": "attacks",
        "predicate": {"kind": "source_is_self"},
        "effect": {"kind": "gain_life", "amount": 2},
    }
    assert _is_safe_trigger_dict(d)


def test_is_safe_trigger_dict_rejects_attacks_scry_shape():
    """``scry_n`` is intentionally NOT in the ATTACKS+source_is_self
    safe set today — no EoE consumer carries the shape, and the
    PendingDecision substrate scry shares with surveil is already
    pinned by round-43's surveil-ATTACKS entry. Pin the negative
    case so a future ATTACKS+IsSelf+scry_n consumer surfacing in
    the pool requires an explicit allowlist edit.
    """
    from mtg_bot.parity.trajectory import _is_safe_trigger_dict

    assert not _is_safe_trigger_dict({
        "event": "attacks",
        "predicate": {"kind": "source_is_self"},
        "effect": {"kind": "scry_n", "count": 1},
    })


def test_simple_creature_filter_admits_attacks_draw_cards_only_creature():
    """A bare-vanilla creature carrying only ATTACKS+IsSelf+DrawCards
    passes the bridge-simple filter end-to-end (sister of the round-43
    ATTACKS+surveil-only filter-admit test). Constructs the printing
    in-line so the test pins the filter contract independent of any
    production-deck data churn.
    """
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.predicates import IsSelf, Event
    from mtg_bot.effects.generic.draw_mill import DrawCards
    from mtg_bot.parity.trajectory import _printing_is_bridge_simple_creature

    printing = CardPrinting(
        name="ProbeAttacksDrawBear",
        mana_cost_str="{1}{U}",
        mana_cost=ManaCost(generic=1, colored=(("U", 1),)),
        type_line="Creature - Bear",
        supertypes=(),
        card_types=("Creature",),
        subtypes=("Bear",),
        power=2,
        toughness=2,
        produces=frozenset(),
        triggered_abilities=(
            TriggeredAbility(
                event=Event.ATTACKS,
                predicate=IsSelf(),
                effect=DrawCards(amount=1),
            ),
        ),
    )
    assert _printing_is_bridge_simple_creature(printing) is True


def test_simple_creature_filter_admits_attacks_gain_life_only_creature():
    """A bare-vanilla creature carrying only ATTACKS+IsSelf+GainLife
    passes the bridge-simple filter end-to-end (sister of draw_cards
    above).
    """
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.predicates import IsSelf, Event
    from mtg_bot.effects.generic.life import GainLife
    from mtg_bot.parity.trajectory import _printing_is_bridge_simple_creature

    printing = CardPrinting(
        name="ProbeAttacksGainBear",
        mana_cost_str="{1}{W}",
        mana_cost=ManaCost(generic=1, colored=(("W", 1),)),
        type_line="Creature - Bear",
        supertypes=(),
        card_types=("Creature",),
        subtypes=("Bear",),
        power=2,
        toughness=2,
        produces=frozenset(),
        triggered_abilities=(
            TriggeredAbility(
                event=Event.ATTACKS,
                predicate=IsSelf(),
                effect=GainLife(amount=2),
            ),
        ),
    )
    assert _printing_is_bridge_simple_creature(printing) is True


def test_python_ta_to_safe_dict_rejects_attacks_draw_cards_with_extra_payload():
    """The :data:`_SAFE_EFFECT_KEYS` whitelist for ``draw_cards`` is
    ``{"kind", "count"}`` (round 1 starter). Adding any extra payload
    key (e.g. a hypothetical ``per_attack_modifier``) must fall out of
    the safe set — the bridge would silently drop it on round-trip.
    Pin the negative case at the dict-side recognizer.
    """
    from mtg_bot.parity.trajectory import _is_safe_trigger_dict

    assert not _is_safe_trigger_dict({
        "event": "attacks",
        "predicate": {"kind": "source_is_self"},
        "effect": {"kind": "draw_cards", "count": 1, "ghost_field": "x"},
    })


# ---------------------------------------------------------------------------
# Round-47 DIES+IsSelf+gain_life carddef-triggers extension.
#
# Adds one new entry to :data:`_SAFE_TRIGGERS`:
#   * ``("dies", "source_is_self", "gain_life")``
# Plus widens the DIES arm of :func:`_python_ta_to_safe_dict`'s
# ``IsSelf`` branch from ``{"surveil"}`` (round 42) to
# ``{"surveil", "gain_life"}``. The :data:`_SAFE_EFFECT_KEYS` table
# is unchanged from round-42 — the ``gain_life`` payload-key whitelist
# was defined in round 1 of Phase 6 and is event-agnostic.
#
# Bridge support pre-existed in BOTH engines:
#   * Rust DIES event dispatch (Slice 5 of carddef-triggers; verified
#     bit-equal by round-42's ENTERS+DIES surveil pair).
#   * Python DIES dispatch via ``effects.dispatch.fire_dies_triggers``.
#   * ``gain_life`` leaf bridge arm at
#     ``cross_engine._ta_dict_to_python_effect`` since round 1 of
#     Phase 6 carddef-triggers; resolves deterministically as a pure
#     scalar life-total update with no PendingDecision queue
#     interaction.
#
# No real-EoE consumer admitted today (substrate-only, sister of the
# round-44 ATTACKS+gain_life slice's no-consumer extension). The EoE
# death-triggers cluster is CreateToken-heavy; Edge Rover / Gravpack
# Monoist / Beamsaw Prospector all carry DIES+IsSelf+CreateToken
# which needs the token-printing pre-registration substrate the
# loader doesn't seat — a separate larger slice. The shape is a
# common one in the broader MTG card pool (Doomed Traveler-on-death
# variants, sac-outlet life-gain).
# ---------------------------------------------------------------------------


def test_safe_triggers_set_carries_dies_gain_life_shape():
    """Pin the DIES+source_is_self+gain_life entry (this slice).
    The SECOND DIES leaf in the safe set after round-42's surveil-DIES.
    """
    from mtg_bot.parity.trajectory import _SAFE_TRIGGERS

    assert (
        ("dies", "source_is_self", "gain_life") in _SAFE_TRIGGERS
    )


def test_is_safe_trigger_dict_admits_dies_gain_life_shape():
    """Dict-side recognizer admits the canonical DIES+source_is_self
    +gain_life dict shape with the bare ``amount`` payload (sister of
    the round-44 ATTACKS+gain_life admit).
    """
    from mtg_bot.parity.trajectory import _is_safe_trigger_dict

    assert _is_safe_trigger_dict({
        "event": "dies",
        "predicate": {"kind": "source_is_self"},
        "effect": {"kind": "gain_life", "amount": 2},
    })


def test_python_ta_to_safe_dict_round_trips_dies_gain_life():
    """Python ``TriggeredAbility`` carrying DIES+IsSelf+GainLife
    converts back to the canonical dict shape; the result satisfies
    :func:`_is_safe_trigger_dict`. Closes the round-47 DIES arm
    extension that adds ``gain_life`` to the per-event safe-effect-
    kinds tuple alongside round-42's ``surveil``.
    """
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.predicates import IsSelf, Event
    from mtg_bot.effects.generic.life import GainLife
    from mtg_bot.parity.trajectory import (
        _is_safe_trigger_dict,
        _python_ta_to_safe_dict,
    )

    ta = TriggeredAbility(
        event=Event.DIES,
        predicate=IsSelf(),
        effect=GainLife(amount=2),
    )
    d = _python_ta_to_safe_dict(ta)
    assert d == {
        "event": "dies",
        "predicate": {"kind": "source_is_self"},
        "effect": {"kind": "gain_life", "amount": 2},
    }
    assert _is_safe_trigger_dict(d)


def test_is_safe_trigger_dict_admits_dies_draw_cards_shape():
    """Converted from the round-47-gain_life slice's reject-path pin:
    ``draw_cards`` IS now in the DIES+source_is_self safe set (this
    slice — round-47 DIES+IsSelf+draw_cards, sister of the
    DIES+gain_life entry on the draw_cards axis). The dict-side
    recognizer admits the canonical DIES+source_is_self+draw_cards
    dict shape with the bare ``count`` payload — the exact round-37
    DDDD / round-44 reject->admit conversion pattern.
    """
    from mtg_bot.parity.trajectory import _is_safe_trigger_dict

    assert _is_safe_trigger_dict({
        "event": "dies",
        "predicate": {"kind": "source_is_self"},
        "effect": {"kind": "draw_cards", "count": 1},
    })


def test_is_safe_trigger_dict_rejects_dies_scry_shape():
    """``scry_n`` is intentionally NOT in the DIES+source_is_self safe
    set today — no consumer carries the shape, and gating it here
    keeps the per-event safe-effect-kinds matrix honest. The round-1
    ENTERS+scry_n entry stays in place under ENTERS; DIES+scry_n
    requires a separate slice.
    """
    from mtg_bot.parity.trajectory import _is_safe_trigger_dict

    assert not _is_safe_trigger_dict({
        "event": "dies",
        "predicate": {"kind": "source_is_self"},
        "effect": {"kind": "scry_n", "count": 1},
    })


def test_python_ta_to_safe_dict_rejects_dies_gain_life_with_extra_payload():
    """The :data:`_SAFE_EFFECT_KEYS` whitelist for ``gain_life`` is
    ``{"kind", "amount"}`` (round 1 starter). Adding any extra payload
    key (e.g. a hypothetical ``per_creature_modifier``) must fall out
    of the safe set — the bridge would silently drop it on round-trip.
    Pin the negative case at the dict-side recognizer.
    """
    from mtg_bot.parity.trajectory import _is_safe_trigger_dict

    assert not _is_safe_trigger_dict({
        "event": "dies",
        "predicate": {"kind": "source_is_self"},
        "effect": {"kind": "gain_life", "amount": 2, "ghost_field": "x"},
    })


def test_simple_creature_filter_admits_dies_gain_life_only_creature():
    """A bare-vanilla creature carrying only DIES+IsSelf+GainLife
    passes the bridge-simple filter end-to-end (sister of the round-44
    ATTACKS+gain_life-only filter-admit test). Constructs the printing
    in-line so the test pins the filter contract independent of any
    production-deck data churn.
    """
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.predicates import IsSelf, Event
    from mtg_bot.effects.generic.life import GainLife
    from mtg_bot.parity.trajectory import _printing_is_bridge_simple_creature

    printing = CardPrinting(
        name="ProbeDiesGainBear",
        mana_cost_str="{1}{W}",
        mana_cost=ManaCost(generic=1, colored=(("W", 1),)),
        type_line="Creature - Bear",
        supertypes=(),
        card_types=("Creature",),
        subtypes=("Bear",),
        power=2,
        toughness=2,
        produces=frozenset(),
        triggered_abilities=(
            TriggeredAbility(
                event=Event.DIES,
                predicate=IsSelf(),
                effect=GainLife(amount=2),
            ),
        ),
    )
    assert _printing_is_bridge_simple_creature(printing) is True


def test_simple_creature_filter_admits_dies_draw_cards_only_creature():
    """Converted from the round-47-gain_life slice's reject-path pin: a
    bare-vanilla creature carrying only DIES+IsSelf+DrawCards now passes
    the bridge-simple filter end-to-end (this slice — round-47
    DIES+IsSelf+draw_cards). Sister of
    ``test_simple_creature_filter_admits_dies_gain_life_only_creature``;
    constructs the printing in-line so the test pins the filter
    contract independent of any production-deck data churn.
    """
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.predicates import IsSelf, Event
    from mtg_bot.effects.generic.draw_mill import DrawCards
    from mtg_bot.parity.trajectory import _printing_is_bridge_simple_creature

    printing = CardPrinting(
        name="ProbeDiesDrawBear",
        mana_cost_str="{1}{U}",
        mana_cost=ManaCost(generic=1, colored=(("U", 1),)),
        type_line="Creature - Bear",
        supertypes=(),
        card_types=("Creature",),
        subtypes=("Bear",),
        power=2,
        toughness=2,
        produces=frozenset(),
        triggered_abilities=(
            TriggeredAbility(
                event=Event.DIES,
                predicate=IsSelf(),
                effect=DrawCards(amount=1),
            ),
        ),
    )
    assert _printing_is_bridge_simple_creature(printing) is True


def test_safe_triggers_set_carries_dies_draw_cards_shape():
    """Pin the new DIES+source_is_self+draw_cards entry (this slice).
    The THIRD DIES leaf in the safe set after round-42's surveil-DIES
    and the round-47 gain_life-DIES — closing the DIES leaf set to
    {surveil, gain_life, draw_cards}.
    """
    from mtg_bot.parity.trajectory import _SAFE_TRIGGERS

    assert ("dies", "source_is_self", "draw_cards") in _SAFE_TRIGGERS


def test_python_ta_to_safe_dict_round_trips_dies_draw_cards():
    """Python ``TriggeredAbility`` carrying DIES+IsSelf+DrawCards
    converts back to the canonical dict shape; the result satisfies
    :func:`_is_safe_trigger_dict`. Closes the round-47 DIES arm
    extension that adds ``draw_cards`` to the per-event safe-effect-
    kinds tuple alongside round-42's ``surveil`` + round-47's
    ``gain_life``. Sister of
    ``test_python_ta_to_safe_dict_round_trips_dies_gain_life``.
    """
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.predicates import IsSelf, Event
    from mtg_bot.effects.generic.draw_mill import DrawCards
    from mtg_bot.parity.trajectory import (
        _is_safe_trigger_dict,
        _python_ta_to_safe_dict,
    )

    ta = TriggeredAbility(
        event=Event.DIES,
        predicate=IsSelf(),
        effect=DrawCards(amount=1),
    )
    d = _python_ta_to_safe_dict(ta)
    assert d == {
        "event": "dies",
        "predicate": {"kind": "source_is_self"},
        "effect": {"kind": "draw_cards", "count": 1},
    }
    assert _is_safe_trigger_dict(d)


def test_python_ta_to_safe_dict_preserves_dies_draw_cards_count():
    """The DrawCards ``amount`` round-trips as the dict's ``count``
    field (Rust's spelling) for a non-unit draw count — pins the
    payload preservation, not just the shape. Mirrors the round-37
    DDDD landfall-draw count-preservation pin.
    """
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.predicates import IsSelf, Event
    from mtg_bot.effects.generic.draw_mill import DrawCards
    from mtg_bot.parity.trajectory import _python_ta_to_safe_dict

    ta = TriggeredAbility(
        event=Event.DIES,
        predicate=IsSelf(),
        effect=DrawCards(amount=3),
    )
    d = _python_ta_to_safe_dict(ta)
    assert d is not None
    assert d["effect"] == {"kind": "draw_cards", "count": 3}


def test_python_ta_to_safe_dict_rejects_dies_draw_cards_with_extra_payload():
    """The :data:`_SAFE_EFFECT_KEYS` whitelist for ``draw_cards`` is
    ``{"kind", "count"}`` (round-1 starter, event-agnostic). Adding any
    extra payload key must fall out of the safe set even now that
    DIES+draw_cards is admitted — the bridge would silently drop the
    extra field on round-trip. Pin the negative case at the dict-side
    recognizer; sister of
    ``test_python_ta_to_safe_dict_rejects_dies_gain_life_with_extra_payload``.
    """
    from mtg_bot.parity.trajectory import _is_safe_trigger_dict

    assert not _is_safe_trigger_dict({
        "event": "dies",
        "predicate": {"kind": "source_is_self"},
        "effect": {"kind": "draw_cards", "count": 1, "ghost_field": "x"},
    })


# ---------------------------------------------------------------------------
# Round-48 bench-admit-set slice: landfall+mill (admits real EoE card
# Icetill Explorer) + source_is_self+mill substrate (Seedship
# Broodtender stays dropped on its activated ability — reject-path pin).
# Mirrors the round-36 landfall+gain_life / round-37 landfall+pump_self
# test cluster pattern exactly; ``mill`` is a pure deterministic zone
# move with the cross-engine bridge arm already shipped round-16.
# ---------------------------------------------------------------------------


def test_safe_triggers_set_carries_landfall_mill_shape():
    """Pin the landfall+mill extension entry — a future shrink would
    silently regress production-deck coverage of Icetill Explorer (the
    real EoE consumer this slice admits). Sister of
    ``test_safe_triggers_set_carries_landfall_pump_self_shape``.
    """
    from mtg_bot.parity.trajectory import _SAFE_TRIGGERS

    assert (
        ("enters", "land_enters_controlled_by_you", "mill")
        in _SAFE_TRIGGERS
    )


def test_safe_triggers_set_carries_enters_self_mill_substrate_shape():
    """Pin the ENTERS+source_is_self+mill substrate entry. No real-EoE
    consumer admitted today (Seedship Broodtender is dropped on its
    activated ability); pre-positioned for any future bare
    "When ~ enters, mill N" creature.
    """
    from mtg_bot.parity.trajectory import _SAFE_TRIGGERS

    assert ("enters", "source_is_self", "mill") in _SAFE_TRIGGERS


def test_safe_effect_keys_carries_mill():
    """The effect-payload key whitelist gains the ``mill`` arm with the
    single ``count`` key (mirrors Rust's bare
    ``Effect::Mill { count: i32 }`` — no rider the bridge would
    silently drop). Sister of ``test_safe_effect_keys_carries_pump_self_until_eot``.
    """
    from mtg_bot.parity.trajectory import _SAFE_EFFECT_KEYS

    assert "mill" in _SAFE_EFFECT_KEYS
    assert _SAFE_EFFECT_KEYS["mill"] == frozenset({"kind", "count"})


def test_is_safe_trigger_dict_admits_landfall_mill():
    """The full trigger-dict checker accepts a landfall+mill trigger
    built from the canonical compound predicate shape and the bare
    ``count`` payload — Icetill Explorer's parser-emitted shape
    (mill 1).
    """
    from mtg_bot.parity.trajectory import _is_safe_trigger_dict

    assert _is_safe_trigger_dict({
        "event": "enters",
        "predicate": {
            "kind": "and",
            "left": {"kind": "subject_is_land"},
            "right": {"kind": "controlled_by_you"},
        },
        "effect": {"kind": "mill", "count": 1},
    })


def test_is_safe_trigger_dict_admits_enters_self_mill():
    """ENTERS+source_is_self+mill substrate entry — the dict-side gate
    admits the shape (the production-deck filter still drops the only
    EoE carrier, Seedship Broodtender, on its activated ability;
    asserted separately below).
    """
    from mtg_bot.parity.trajectory import _is_safe_trigger_dict

    assert _is_safe_trigger_dict({
        "event": "enters",
        "predicate": {"kind": "source_is_self"},
        "effect": {"kind": "mill", "count": 3},
    })


def test_is_safe_trigger_dict_rejects_mill_under_dies():
    """Mill under DIES is NOT in the safe set today — no EoE consumer
    carries it and no slice has shipped it. Pins the predicate-effect /
    event product gate from the negative direction (admitting ``mill``
    under ENTERS doesn't admit it under DIES). Sister of
    ``test_is_safe_trigger_dict_rejects_pump_self_under_source_is_self``.
    """
    from mtg_bot.parity.trajectory import _is_safe_trigger_dict

    assert not _is_safe_trigger_dict({
        "event": "dies",
        "predicate": {"kind": "source_is_self"},
        "effect": {"kind": "mill", "count": 1},
    })


def test_is_safe_trigger_dict_rejects_mill_with_extra_payload_key():
    """Schema-strict on the mill payload — an extra key beyond
    {kind, count} is rejected so a future schema extension riding the
    same effect kind doesn't silently slip through with the rider
    dropped on the cross-engine round trip. Sister of
    ``test_is_safe_trigger_dict_rejects_pump_self_with_extra_payload_key``.
    """
    from mtg_bot.parity.trajectory import _is_safe_trigger_dict

    assert not _is_safe_trigger_dict({
        "event": "enters",
        "predicate": {
            "kind": "and",
            "left": {"kind": "subject_is_land"},
            "right": {"kind": "controlled_by_you"},
        },
        "effect": {"kind": "mill", "count": 1, "ghost_field": "x"},
    })


def test_python_ta_to_safe_dict_round_trips_landfall_mill():
    """A Python ``TriggeredAbility`` carrying the parser-emitted
    landfall predicate (``And(Subject(IsLand), Controlled(YOU))``) +
    bare ``SelfMill`` round-trips to the canonical compound dict shape
    with a ``count`` payload (Python's ``amount`` -> Rust's ``count``
    spelling, same as the established surveil/draw arms). The result
    satisfies :func:`_is_safe_trigger_dict`.
    """
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.predicates import (
        And,
        Controlled,
        Event,
        Subject,
        YOU,
    )
    from mtg_bot.effects.object_predicates import IsLand
    from mtg_bot.effects.generic.library_lookat import SelfMill
    from mtg_bot.parity.trajectory import (
        _is_safe_trigger_dict,
        _python_ta_to_safe_dict,
    )

    ta = TriggeredAbility(
        event=Event.ENTERS,
        predicate=And(
            left=Subject(slot=None, inner=IsLand()),
            right=Controlled(by=YOU, subject=None),
        ),
        effect=SelfMill(amount=1),
    )
    d = _python_ta_to_safe_dict(ta)
    assert d is not None
    assert d == {
        "event": "enters",
        "predicate": {
            "kind": "and",
            "left": {"kind": "subject_is_land"},
            "right": {"kind": "controlled_by_you"},
        },
        "effect": {"kind": "mill", "count": 1},
    }
    assert _is_safe_trigger_dict(d)


def test_python_ta_to_safe_dict_round_trips_enters_self_mill():
    """A Python ``TriggeredAbility`` carrying ENTERS+IsSelf+SelfMill(N)
    round-trips to the bare ``{"kind": "mill", "count": N}`` dict and
    preserves the count. Substrate-only — pins the recognizer arm
    independent of any EoE consumer.
    """
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.predicates import IsSelf, Event
    from mtg_bot.effects.generic.library_lookat import SelfMill
    from mtg_bot.parity.trajectory import _python_ta_to_safe_dict

    ta = TriggeredAbility(
        event=Event.ENTERS,
        predicate=IsSelf(),
        effect=SelfMill(amount=3),
    )
    d = _python_ta_to_safe_dict(ta)
    assert d is not None
    assert d["effect"] == {"kind": "mill", "count": 3}
    assert d["predicate"] == {"kind": "source_is_self"}


def test_simple_creature_filter_admits_real_eoe_icetill_explorer():
    """End-to-end gate: the parser-emitted Icetill Explorer printing
    (2/4 {2}{G}{G}, "Landfall — Whenever a land you control enters,
    mill a card") now passes :func:`_printing_is_bridge_simple_creature`.
    Pre-extension this returned False (landfall+mill cross was unsafe);
    post-extension Icetill Explorer threads into the production-deck
    loader. Sister of ``test_simple_creature_filter_admits_icecave_crasher``.
    The real EoE card this slice admits.
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import (
        _printing_is_bridge_simple_creature,
        _python_ta_to_safe_dict,
    )

    src = OracleParserCardSource()
    icetill = src.get_printings().get("Icetill Explorer")
    assert icetill is not None, (
        "Icetill Explorer not in OracleParserCardSource — the parser "
        "dropped it; landfall+mill extension test cannot verify the "
        "production-deck unblock."
    )
    assert len(icetill.triggered_abilities) == 1
    assert _python_ta_to_safe_dict(icetill.triggered_abilities[0]) is not None
    assert _printing_is_bridge_simple_creature(icetill) is True


def test_simple_creature_filter_still_rejects_seedship_broodtender():
    """Reject-path pin: Seedship Broodtender is the only OTHER EoE
    SelfMill carrier (ENTERS+IsSelf+SelfMill(3)) but ALSO carries an
    activated ability — a declined silent-mistranslation class the
    production-deck loader doesn't seat. The source_is_self+mill
    substrate entry must NOT admit it: it stays correctly dropped at
    the ``activated_abilities`` gate. Pins the bridge-correctness
    discipline (handoff §2) — admitting the mill leaf doesn't relax
    the activated-abilities filter.
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import _printing_is_bridge_simple_creature

    src = OracleParserCardSource()
    seedship = src.get_printings().get("Seedship Broodtender")
    if seedship is None:
        # Parser hasn't claimed it yet — reject rationale still
        # applies, but there's nothing to assert against.
        return
    assert len(seedship.activated_abilities) >= 1, (
        "Seedship Broodtender expected to carry an activated ability; "
        "if the parser shape changed, re-derive the reject rationale."
    )
    assert _printing_is_bridge_simple_creature(seedship) is False


def test_printing_to_card_def_carries_landfall_mill_through():
    """Icetill Explorer's parsed printing converts to a CardDef whose
    ``triggered_abilities`` carries the canonical compound landfall
    dict shape with the bare ``mill`` payload — the same dict both
    engines' bridge arms consume. Sister of
    ``test_printing_to_card_def_carries_landfall_pump_self_through``.
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import _printing_to_card_def

    src = OracleParserCardSource()
    icetill = src.get_printings().get("Icetill Explorer")
    if icetill is None:
        return
    cd = _printing_to_card_def(icetill)
    assert cd.card_type == "Creature"
    assert cd.triggered_abilities == (
        {
            "event": "enters",
            "predicate": {
                "kind": "and",
                "left": {"kind": "subject_is_land"},
                "right": {"kind": "controlled_by_you"},
            },
            "effect": {"kind": "mill", "count": 1},
        },
    )


# ===== Round-59 N1 landfall+put_plus_one_counter_on_self pins =====
# The sole remaining Seedship Agrarian blocker (round-58 resync
# narrowed its non_effect_blocker to this one leaf). Mirrors the
# round-48 landfall+mill pin family exactly.


def test_safe_triggers_set_carries_landfall_put_plus_one_counter_shape():
    """Pin the landfall+put_plus_one_counter_on_self extension entry —
    a future shrink would silently regress production-deck coverage of
    Seedship Agrarian's TRIGGER-2 (the real EoE consumer this slice
    admits, closing its sole remaining blocker). Sister of
    ``test_safe_triggers_set_carries_landfall_mill_shape``.
    """
    from mtg_bot.parity.trajectory import _SAFE_TRIGGERS

    assert (
        ("enters", "land_enters_controlled_by_you",
         "put_plus_one_counter_on_self")
        in _SAFE_TRIGGERS
    )


def test_safe_effect_keys_carries_put_plus_one_counter_on_self():
    """The effect-payload key whitelist gains the
    ``put_plus_one_counter_on_self`` arm with the single ``amount``
    key (mirrors Rust's bare
    ``Effect::PutPlusOneCounterOnSelf { amount: i32 }`` to_dict at
    cards.rs:7179-7181 — the ``amount`` field name is IDENTICAL on
    both sides, no rider the bridge would silently drop). Sister of
    ``test_safe_effect_keys_carries_mill``.
    """
    from mtg_bot.parity.trajectory import _SAFE_EFFECT_KEYS

    assert "put_plus_one_counter_on_self" in _SAFE_EFFECT_KEYS
    assert _SAFE_EFFECT_KEYS["put_plus_one_counter_on_self"] == frozenset(
        {"kind", "amount"}
    )


def test_is_safe_trigger_dict_admits_landfall_put_plus_one_counter():
    """The full trigger-dict checker accepts a
    landfall+put_plus_one_counter_on_self trigger built from the
    canonical compound predicate shape and the bare ``amount``
    payload — Seedship Agrarian's parser-emitted trigger-2 shape
    (amount=1). Sister of
    ``test_is_safe_trigger_dict_admits_landfall_mill``.
    """
    from mtg_bot.parity.trajectory import _is_safe_trigger_dict

    assert _is_safe_trigger_dict({
        "event": "enters",
        "predicate": {
            "kind": "and",
            "left": {"kind": "subject_is_land"},
            "right": {"kind": "controlled_by_you"},
        },
        "effect": {"kind": "put_plus_one_counter_on_self", "amount": 1},
    })


def test_is_safe_trigger_dict_rejects_put_plus_one_counter_under_dies():
    """put_plus_one_counter_on_self under DIES is NOT in the safe set
    today — no EoE consumer carries it and no slice has shipped it.
    Pins the predicate-effect / event product gate from the negative
    direction: this slice admits the leaf ONLY under the landfall
    predicate, NOT under bare source_is_self or any other event.
    Sister of ``test_is_safe_trigger_dict_rejects_mill_under_dies``.
    """
    from mtg_bot.parity.trajectory import _is_safe_trigger_dict

    assert not _is_safe_trigger_dict({
        "event": "dies",
        "predicate": {"kind": "source_is_self"},
        "effect": {"kind": "put_plus_one_counter_on_self", "amount": 1},
    })
    # Also rejected under ENTERS+source_is_self (only the landfall
    # predicate admits this leaf this slice — the
    # ``("enters","source_is_self","put_plus_one_counter_on_self")``
    # triple is deliberately NOT in _SAFE_TRIGGERS).
    assert not _is_safe_trigger_dict({
        "event": "enters",
        "predicate": {"kind": "source_is_self"},
        "effect": {"kind": "put_plus_one_counter_on_self", "amount": 1},
    })


def test_is_safe_trigger_dict_rejects_put_plus_one_counter_extra_key():
    """Schema-strict on the put_plus_one_counter_on_self payload — an
    extra key beyond {kind, amount} is rejected so a future schema
    extension riding the same effect kind doesn't silently slip
    through with the rider dropped on the cross-engine round trip.
    Sister of
    ``test_is_safe_trigger_dict_rejects_mill_with_extra_payload_key``.
    """
    from mtg_bot.parity.trajectory import _is_safe_trigger_dict

    assert not _is_safe_trigger_dict({
        "event": "enters",
        "predicate": {
            "kind": "and",
            "left": {"kind": "subject_is_land"},
            "right": {"kind": "controlled_by_you"},
        },
        "effect": {
            "kind": "put_plus_one_counter_on_self",
            "amount": 1,
            "ghost_field": "x",
        },
    })


def test_python_ta_to_safe_dict_round_trips_landfall_put_plus_one_counter():
    """A Python ``TriggeredAbility`` carrying the parser-emitted
    landfall predicate (``And(Subject(IsLand), Controlled(YOU))``) +
    bare ``PutPlusOneCounterOnSelf`` round-trips to the canonical
    compound dict shape with an ``amount`` payload (the ``amount``
    field name is IDENTICAL on both engines — no count/amount spelling
    discrepancy unlike mill/scry/surveil). The result satisfies
    :func:`_is_safe_trigger_dict`. Sister of
    ``test_python_ta_to_safe_dict_round_trips_landfall_mill``.
    """
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.predicates import (
        And,
        Controlled,
        Event,
        Subject,
        YOU,
    )
    from mtg_bot.effects.object_predicates import IsLand
    from mtg_bot.effects.generic.counters import PutPlusOneCounterOnSelf
    from mtg_bot.parity.trajectory import (
        _is_safe_trigger_dict,
        _python_ta_to_safe_dict,
    )

    ta = TriggeredAbility(
        event=Event.ENTERS,
        predicate=And(
            left=Subject(slot=None, inner=IsLand()),
            right=Controlled(by=YOU, subject=None),
        ),
        effect=PutPlusOneCounterOnSelf(amount=1),
    )
    d = _python_ta_to_safe_dict(ta)
    assert d is not None
    assert d == {
        "event": "enters",
        "predicate": {
            "kind": "and",
            "left": {"kind": "subject_is_land"},
            "right": {"kind": "controlled_by_you"},
        },
        "effect": {"kind": "put_plus_one_counter_on_self", "amount": 1},
    }
    assert _is_safe_trigger_dict(d)


def test_python_ta_to_safe_dict_preserves_put_plus_one_counter_amount():
    """The recognizer preserves a non-default ``amount`` (a future
    "Landfall — put 2 +1/+1 counters on this creature" carrier would
    round-trip the count, not silently collapse to 1). Pins the
    scalar-fidelity contract independent of any EoE consumer.
    """
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.predicates import (
        And,
        Controlled,
        Event,
        Subject,
        YOU,
    )
    from mtg_bot.effects.object_predicates import IsLand
    from mtg_bot.effects.generic.counters import PutPlusOneCounterOnSelf
    from mtg_bot.parity.trajectory import _python_ta_to_safe_dict

    ta = TriggeredAbility(
        event=Event.ENTERS,
        predicate=And(
            left=Subject(slot=None, inner=IsLand()),
            right=Controlled(by=YOU, subject=None),
        ),
        effect=PutPlusOneCounterOnSelf(amount=2),
    )
    d = _python_ta_to_safe_dict(ta)
    assert d is not None
    assert d["effect"] == {
        "kind": "put_plus_one_counter_on_self",
        "amount": 2,
    }


def test_simple_creature_filter_admits_real_eoe_seedship_agrarian():
    """End-to-end gate: the parser-emitted Seedship Agrarian printing
    (3/3 {3}{G}, BECOMES_TAPPED->CreateToken(Lander) +
    "Landfall — Whenever a land you control enters, put a +1/+1
    counter on this creature") now passes
    :func:`_printing_is_bridge_simple_creature`. The BECOMES_TAPPED
    half was bridged round-58 N1; this slice closes the orthogonal
    landfall+put_plus_one_counter_on_self trigger-2 leaf — with BOTH
    triggers round-tripping the FULL card is byte-equal-admittable.
    The real EoE card this slice closes (its sole remaining blocker).
    Sister of ``test_simple_creature_filter_admits_real_eoe_icetill_explorer``.
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.effects.predicates import Event
    from mtg_bot.parity.trajectory import (
        _printing_is_bridge_simple_creature,
        _python_ta_to_safe_dict,
    )

    src = OracleParserCardSource()
    seedship = src.get_printings().get("Seedship Agrarian")
    assert seedship is not None, (
        "Seedship Agrarian not in OracleParserCardSource — the parser "
        "dropped it; the landfall+put_plus_one_counter_on_self "
        "extension test cannot verify the production-deck unblock."
    )
    assert len(seedship.triggered_abilities) == 2
    # BOTH triggers must individually round-trip (the safe-trigger
    # filter requires EVERY trigger to be safe — pre-r58 the
    # BECOMES_TAPPED trigger dropped the card; pre-r59 the landfall
    # trigger did).
    by_event = {
        t.event: t for t in seedship.triggered_abilities
    }
    assert Event.BECOMES_TAPPED in by_event
    assert Event.ENTERS in by_event
    assert _python_ta_to_safe_dict(by_event[Event.BECOMES_TAPPED]) is not None
    landfall_d = _python_ta_to_safe_dict(by_event[Event.ENTERS])
    assert landfall_d is not None
    assert landfall_d["effect"] == {
        "kind": "put_plus_one_counter_on_self",
        "amount": 1,
    }
    assert _printing_is_bridge_simple_creature(seedship) is True


def test_printing_to_card_def_carries_seedship_agrarian_both_triggers():
    """Seedship Agrarian's parsed printing converts to a CardDef whose
    ``triggered_abilities`` carries BOTH the BECOMES_TAPPED->create_token
    trigger (round-58) AND the canonical compound landfall dict shape
    with the bare ``put_plus_one_counter_on_self`` payload (this
    slice). Sister of
    ``test_printing_to_card_def_carries_landfall_mill_through``.
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import _printing_to_card_def

    src = OracleParserCardSource()
    seedship = src.get_printings().get("Seedship Agrarian")
    if seedship is None:
        return
    cd = _printing_to_card_def(seedship)
    assert cd.card_type == "Creature"
    assert len(cd.triggered_abilities) == 2
    landfall = [
        t for t in cd.triggered_abilities
        if t.get("effect", {}).get("kind")
        == "put_plus_one_counter_on_self"
    ]
    assert len(landfall) == 1, (
        "Seedship Agrarian CardDef must carry exactly one "
        "landfall+put_plus_one_counter_on_self trigger"
    )
    assert landfall[0] == {
        "event": "enters",
        "predicate": {
            "kind": "and",
            "left": {"kind": "subject_is_land"},
            "right": {"kind": "controlled_by_you"},
        },
        "effect": {"kind": "put_plus_one_counter_on_self", "amount": 1},
    }
    # The other trigger is the round-58 BECOMES_TAPPED->create_token
    # half (post-seating it carries a numeric token_printing_id; pre-
    # seating a symbolic _token_card_def — assert just the event/kind).
    bt = [
        t for t in cd.triggered_abilities
        if t.get("event") == "becomes_tapped"
    ]
    assert len(bt) == 1
    assert bt[0]["effect"]["kind"] == "create_token"


# ===== Round-49 N1 token-printing substrate (Phase 1) helper pins =====


def test_is_safe_trigger_dict_accepts_post_seating_create_token():
    """The POST-seating create_token dict
    ``{kind, count, token_printing_id}`` satisfies
    :func:`_is_safe_trigger_dict`. Pins the dict-side gate's
    create_token whitelist (mirrors
    ``test_python_ta_to_safe_dict_round_trips_enters_self_mill``).
    """
    from mtg_bot.parity.trajectory import _is_safe_trigger_dict

    assert _is_safe_trigger_dict({
        "event": "enters",
        "predicate": {"kind": "source_is_self"},
        "effect": {
            "kind": "create_token", "count": 1, "token_printing_id": 5,
        },
    })


def test_is_safe_trigger_dict_rejects_symbolic_and_rider_create_token():
    """The dict-side gate rejects (a) the PRE-seating symbolic shape
    (``_token_card_def`` is not in the create_token key whitelist) so
    a never-seated dict that leaked to a real engine build is caught,
    and (b) any create_token dict carrying a rider field
    (``tapped`` / ``each_player``) — Rust's two-field variant has no
    mirror, mirrors the Surveil-``use_artifact_count`` exclusion.
    """
    from mtg_bot.parity.trajectory import _is_safe_trigger_dict

    # Symbolic (un-seated) shape -> rejected.
    assert not _is_safe_trigger_dict({
        "event": "enters",
        "predicate": {"kind": "source_is_self"},
        "effect": {
            "kind": "create_token", "count": 1, "_token_card_def": object(),
        },
    })
    # Rider on the effect dict -> rejected.
    assert not _is_safe_trigger_dict({
        "event": "enters",
        "predicate": {"kind": "source_is_self"},
        "effect": {
            "kind": "create_token", "count": 1,
            "token_printing_id": 5, "tapped": True,
        },
    })


def test_seat_token_printings_noop_without_create_token_carrier():
    """``_seat_token_printings`` is a fast-path no-op (returns the
    SAME list object) when no card def carries a symbolic
    create_token trigger — every pre-round-49 production deck. Pins
    the back-compat guarantee.
    """
    from mtg_bot.parity.cross_engine import CardDef
    from mtg_bot.parity.trajectory import _seat_token_printings

    cds = [
        CardDef(name="Forest", card_type="Land", mana_produced=("G",)),
        CardDef(
            name="Grizzly Bears", card_type="Creature",
            mana_cost_generic=1, mana_cost_colored=(("G", 1),),
            power=2, toughness=2,
        ),
    ]
    out = _seat_token_printings(cds)
    assert out is cds, "no-create_token-carrier path must be a no-op"


def test_seat_token_printings_dedups_shared_token():
    """Two carriers printing the same-named token share ONE seated
    token CardDef + ONE pid (dedup by name). The token is appended
    AFTER all carriers; both carriers' triggers rewrite to the same
    numeric pid.
    """
    from mtg_bot.cards.base import make_token_creature
    from mtg_bot.parity.cross_engine import (
        CardDef, clear_token_printings, _TOKEN_PRINTING_BY_PID,
    )
    from mtg_bot.parity.trajectory import (
        _token_vanilla_card_def, _seat_token_printings,
    )

    clear_token_printings()
    try:
        robot = make_token_creature(
            name="Shared Robot", power=2, toughness=2,
            subtypes=("Robot",), artifact=True,
        )
        tcd = _token_vanilla_card_def(robot)

        def _maker(nm):
            return CardDef(
                name=nm, card_type="Creature", mana_cost_generic=2,
                power=1, toughness=1,
                triggered_abilities=(
                    {
                        "event": "enters",
                        "predicate": {"kind": "source_is_self"},
                        "effect": {
                            "kind": "create_token", "count": 1,
                            "_token_card_def": tcd,
                        },
                    },
                ),
            )

        forest = CardDef(
            name="Forest", card_type="Land", mana_produced=("G",)
        )
        seated = _seat_token_printings(
            [_maker("Maker A"), _maker("Maker B"), forest]
        )
        names = [c.name for c in seated]
        # Exactly ONE Shared Robot, appended after the makers + forest.
        assert names.count("Shared Robot") == 1
        assert names.index("Shared Robot") == len(names) - 1
        pid = names.index("Shared Robot")
        for nm in ("Maker A", "Maker B"):
            c = next(x for x in seated if x.name == nm)
            eff = c.triggered_abilities[0]["effect"]
            assert eff["token_printing_id"] == pid
            assert "_token_card_def" not in eff
        assert _TOKEN_PRINTING_BY_PID[pid].name == "Shared Robot"
    finally:
        clear_token_printings()


def test_printing_is_bridge_simple_creature_rejects_lander_cluster():
    """Phase 3a (round-53 N1) reject→admit conversion + the §2 decline
    ledger for the Lander cluster.

    Phase 1 (round-49) declined the ENTIRE high-deck-count Lander
    cluster because the Lander token's activated ability would silently
    vanish on the bridge (§2.3). The round-52 N1 Phase-3 precursor
    landed the ``token_activated_abilities`` substrate + bridge
    plumbing; Phase 3a (this round) adds
    ``_token_with_safe_activated_ability_card_def`` which ADMITS the
    bare Lander token (its ONLY activated ability is the bridge-correct
    ``{2},Sac:SearchLibraryForBasicLandTapped`` shape) and widens the
    DIES recognizer row with bare ``create_token``.

    **CONVERTED drop→admit** (the headline lever): Galactic Wayfarer
    (ENTERS+IsSelf+bare-Lander) + Beamsaw Prospector
    (DIES+IsSelf+bare-Lander) — see
    ``test_phase3a_lander_carriers_flip_drop_to_admit``.

    **STAY DECLINED — the §2 ledger** (each for a reason ORTHOGONAL to
    the Lander token now round-tripping; admitting any would be a §2
    silent-mistranslation):

      * **Edge Rover** — its CreateToken rider is ``each_player=True``.
        No loader recognizer / auto-registration arm for the
        each-player shape (Phase 5 in the design doc); the
        ``create_token_each_player`` Rust variant + bridge arm exist
        (round-43) but the recognizer gates ``each_player`` to its
        default. DECLINED → Phase 5.
      * **Biomechan Engineer** — the CARRIER has an activated ability
        (``activated_abilities`` non-empty). ``_printing_is_bridge_
        simple_creature`` declines any creature with a carrier
        activated ability campaign-wide (CardDef has no carrier-
        activated-ability field — it would silently vanish). The
        Lander rider itself round-trips; the carrier feature is the
        decline. DECLINED (carrier activated ability).
      * **Glacier Godmaw** — a SECOND triggered ability
        (``ENTERS + landfall-And + PumpCreaturesYouControlUntilEOT``
        with ``granted_keywords={haste,vigilance}``) does not
        round-trip through ``_python_ta_to_safe_dict`` (no bridge arm
        for mass-pump-with-granted-keywords). The filter requires
        EVERY trigger to round-trip; the Lander trigger does, the
        sibling does not. DECLINED (sibling un-bridged trigger).

    These three are the standing Phase-3a §2 declines. The remaining
    cluster members (Sunstar Expansionist And-StateBound predicate,
    Seedship Agrarian BECOMES_TAPPED event, Biotech Specialist
    IS_SACRIFICED sibling, Bioengineered Future non-creature →
    Phase 2) are covered by the dedicated decline pin below.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity.trajectory import _printing_is_bridge_simple_creature

    pr = get_active_source().get_printings()
    # Phase 3a CONVERTED these drop→admit.
    for name in ("Galactic Wayfarer", "Beamsaw Prospector"):
        c = pr.get(name)
        if c is None:
            continue
        assert _printing_is_bridge_simple_creature(c) is True, (
            f"{name} must FLIP drop→admit under Phase 3a "
            f"(bare Lander token now round-trips via "
            f"_token_with_safe_activated_ability_card_def)"
        )
    # These STAY DECLINED — each for a §2 reason orthogonal to the
    # Lander token round-tripping (see docstring ledger).
    for name in ("Edge Rover", "Biomechan Engineer", "Glacier Godmaw"):
        c = pr.get(name)
        if c is None:
            continue
        assert _printing_is_bridge_simple_creature(c) is False, (
            f"{name} must STAY DROPPED under Phase 3a "
            f"(§2 decline orthogonal to the Lander — see ledger)"
        )


def test_phase3a_lander_carriers_flip_drop_to_admit():
    """Phase 3a (round-53 N1) EoE-pool-delta ADMIT pin — the headline
    real-card lever.

    Galactic Wayfarer (Creature — Human Scout, "When ~ enters, create
    a Lander." — **33,469** of 129,996 17lands EoE decks) and Beamsaw
    Prospector (Creature — Human Artificer, "When ~ dies, create a
    Lander." — **24,310** decks) flip drop→admit:
    **57,779 cumulative 17lands decks**, the single largest token-
    substrate real-card lever after Phase 4's Gravpack Monoist.

    The flip is enabled by ``_token_with_safe_activated_ability_card_
    def`` admitting the bare ``Lander`` token (its ONLY activated
    ability is the round-52-precursor-verified bridge-correct
    ``{2},Sac:SearchLibraryForBasicLandTapped`` shape, emitted on the
    synthesized token CardDef via ``token_activated_abilities``) +ENTERS
    (round-49) / DIES (this round) ``create_token`` recognizer rows.

    NOTE the cumulative count (57,779) is BELOW the round-52-flagged
    "~88k+" naive estimate: that estimate summed the high-deck-count
    list before applying §2 per-carrier. The §2-honest admit set is
    exactly these two carriers — every other high-deck Lander carrier
    is declined for a reason orthogonal to the Lander (see
    ``test_printing_is_bridge_simple_creature_rejects_lander_cluster``
    + ``test_phase3a_lander_cluster_residue_stays_declined``).
    Coverage is NOT forced (brief §2 discipline).
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity.trajectory import (
        _printing_is_bridge_simple_creature,
        _python_ta_to_safe_dict,
    )

    pr = get_active_source().get_printings()

    gw = pr.get("Galactic Wayfarer")
    assert gw is not None, "Galactic Wayfarer must be in the EoE pool"
    assert _printing_is_bridge_simple_creature(gw) is True
    (gw_ta,) = gw.triggered_abilities
    gw_sd = _python_ta_to_safe_dict(gw_ta)
    assert gw_sd is not None
    assert gw_sd["event"] == "enters"
    assert gw_sd["predicate"] == {"kind": "source_is_self"}
    assert gw_sd["effect"]["kind"] == "create_token"
    assert gw_sd["effect"]["count"] == 1
    # Pre-seating symbolic form — the Lander token CardDef carries the
    # bridge-correct activated ability via token_activated_abilities.
    gw_tcd = gw_sd["effect"]["_token_card_def"]
    assert gw_tcd.name == "Lander"
    assert gw_tcd.card_type == "Artifact"
    assert gw_tcd.power is None and gw_tcd.toughness is None
    assert len(gw_tcd.token_activated_abilities) == 1
    gw_aa = gw_tcd.token_activated_abilities[0]
    assert gw_aa["cost"] == {"mana": {"generic": 2}, "sacrifice_self": True}
    assert gw_aa["effect"] == {
        "kind": "search_library_for_basic_land_tapped"
    }
    assert gw_aa["is_mana_ability"] is False

    bp = pr.get("Beamsaw Prospector")
    assert bp is not None, "Beamsaw Prospector must be in the EoE pool"
    assert _printing_is_bridge_simple_creature(bp) is True
    (bp_ta,) = bp.triggered_abilities
    bp_sd = _python_ta_to_safe_dict(bp_ta)
    assert bp_sd is not None
    assert bp_sd["event"] == "dies", (
        "Beamsaw Prospector is a DIES-trigger Lander carrier — Phase 3a "
        "widens the DIES recognizer row with bare create_token"
    )
    assert bp_sd["predicate"] == {"kind": "source_is_self"}
    assert bp_sd["effect"]["kind"] == "create_token"
    assert bp_sd["effect"]["count"] == 1
    assert bp_sd["effect"]["_token_card_def"].name == "Lander"


def test_phase3a_lander_cluster_residue_stays_declined():
    """Phase 3a §2-discipline pin: the lower-deck-count Lander-cluster
    residue STAYS DECLINED, each for a precise reason.

    These are the "do not force coverage" declines (brief §2). Each
    carrier's Lander token itself round-trips post-Phase-3a, but the
    carrier is declined for an ORTHOGONAL bridge-incorrectness:

      * **Sunstar Expansionist** (12,252 decks) — its CreateToken
        trigger predicate is ``And(IsSelf, StateBound(Opponent
        ControlsMoreLandsThanYou))``, a conditional StateBound shape
        with no recognizer arm (the create_token recognizer only
        handles the bare ``IsSelf`` predicate). Declined at the
        recognizer (``_python_ta_to_safe_dict`` returns None).
      * **Seedship Agrarian** (14,078 decks) — **ROUND-59 N1: FULLY
        CLOSED, NO LONGER DECLINED (asserted ADMITTED below).** Its
        FIRST trigger ``BECOMES_TAPPED + IsSelf + CreateToken(Lander)``
        round-trips byte-equal (round-58 N1 BECOMES_TAPPED event
        bridge). Its SECOND trigger ``Landfall — Whenever a land you
        control enters, put a +1/+1 counter on this creature`` =
        ``ENTERS / land_enters_controlled_by_you /
        PutPlusOneCounterOnSelf`` NOW also round-trips: round-59 N1
        added ``put_plus_one_counter_on_self`` to the landfall
        safe-leaf set (the one-line-widen sister of the round-48
        landfall+mill slice). With BOTH triggers round-tripping the
        WHOLE card is byte-equal-admittable
        (``_printing_is_bridge_simple_creature`` returns True). This
        carrier is retained in this pin's body as an INVERTED
        assertion (round-39/53/56/58 inversion precedent) — it now
        pins the ADMIT, not a decline. See
        ``docs/SEARCH_LIMITATIONS.md`` "BECOMES_TAPPED event bridge +
        landfall+put_plus_one_counter_on_self" for the full closure
        narrative.
      * **Biotech Specialist** (5,058 decks) — a SECOND trigger
        (``IS_SACRIFICED + And + DealDamageToTargetOpponent``) does
        not round-trip; the filter requires every trigger to. Declined
        on the sibling trigger.
      * **Bioengineered Future** (1,560 decks) — a non-creature
        (Enchantment). The loader creature-filter declines it; the
        bridge-simple non-creature path is Phase 2. Declined
        (non-creature → Phase 2).
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity.trajectory import (
        _printing_is_bridge_simple_creature,
        _python_ta_to_safe_dict,
    )

    pr = get_active_source().get_printings()

    se = pr.get("Sunstar Expansionist")
    if se is not None:
        assert _printing_is_bridge_simple_creature(se) is False
        # ta[0] is the Lander CreateToken under the And-StateBound
        # predicate → recognizer returns None.
        assert _python_ta_to_safe_dict(se.triggered_abilities[0]) is None, (
            "Sunstar Expansionist's CreateToken rides an "
            "And-StateBound predicate — must NOT round-trip"
        )

    sa = pr.get("Seedship Agrarian")
    if sa is not None:
        # ROUND-59 N1 FULLY CLOSES Seedship Agrarian — INVERTED from
        # the pre-r59 decline (round-39/53/56/58 inversion precedent:
        # a pin that asserted the BUG is inverted to assert correct
        # behavior once the bug is fixed). Pre-r58 the blocker was the
        # unbridged BECOMES_TAPPED event (r58 closed that, narrowing
        # the residual to the orthogonal landfall+1/+1 leaf); r59 N1
        # closes that sole remaining leaf (put_plus_one_counter_on_self
        # added to the landfall safe set). BOTH triggers now round-trip
        # byte-equal → the WHOLE card is admittable.
        assert _printing_is_bridge_simple_creature(sa) is True, (
            "ROUND-59 N1: Seedship Agrarian's BOTH triggers now "
            "round-trip byte-equal (trigger-1 BECOMES_TAPPED->Lander "
            "bridged r58; trigger-2 landfall->put_plus_one_counter_"
            "on_self admitted r59) — the whole card is admittable"
        )
        # Trigger 0: "Whenever this creature becomes tapped, create a
        # Lander token" — BECOMES_TAPPED + IsSelf + CreateToken
        # (round-58 event bridge).
        lander_ta = next(
            t for t in sa.triggered_abilities
            if getattr(getattr(t, "effect", None), "token_printing", None)
            is not None
            and t.effect.token_printing.name == "Lander"
        )
        lander_sd = _python_ta_to_safe_dict(lander_ta)
        assert lander_sd is not None, (
            "Seedship Agrarian's Lander trigger is "
            "BECOMES_TAPPED+IsSelf+CreateToken — round-trips byte-"
            "equal (round-58 BECOMES_TAPPED event bridge)"
        )
        assert lander_sd["event"] == "becomes_tapped"
        assert lander_sd["predicate"] == {"kind": "source_is_self"}
        assert lander_sd["effect"]["kind"] == "create_token"
        assert lander_sd["effect"]["_token_card_def"].name == "Lander"
        # Trigger 1: the landfall +1/+1 — ENTERS +
        # land_enters_controlled_by_you + PutPlusOneCounterOnSelf.
        # ROUND-59 N1: ``put_plus_one_counter_on_self`` is NOW a
        # landfall safe leaf, so this trigger round-trips to the
        # canonical compound dict shape with a bare ``amount`` payload
        # (inversion of the pre-r59 None assertion — it was pinning
        # the residual gap; now the gap is closed).
        landfall_ta = next(
            t for t in sa.triggered_abilities
            if type(t.effect).__name__ == "PutPlusOneCounterOnSelf"
        )
        landfall_sd = _python_ta_to_safe_dict(landfall_ta)
        assert landfall_sd is not None, (
            "ROUND-59 N1: Seedship Agrarian's landfall+"
            "PutPlusOneCounterOnSelf trigger NOW round-trips — "
            "put_plus_one_counter_on_self is a landfall safe leaf "
            "(closed the sole remaining Seedship blocker; was the "
            "post-r58 residual)"
        )
        assert landfall_sd["event"] == "enters"
        assert landfall_sd["predicate"] == {
            "kind": "and",
            "left": {"kind": "subject_is_land"},
            "right": {"kind": "controlled_by_you"},
        }
        assert landfall_sd["effect"] == {
            "kind": "put_plus_one_counter_on_self",
            "amount": 1,
        }

    bs = pr.get("Biotech Specialist")
    if bs is not None:
        assert _printing_is_bridge_simple_creature(bs) is False, (
            "Biotech Specialist has an IS_SACRIFICED+damage sibling "
            "trigger that does not round-trip — stays declined"
        )

    bf = pr.get("Bioengineered Future")
    if bf is not None:
        assert _printing_is_bridge_simple_creature(bf) is False, (
            "Bioengineered Future is a non-creature (Enchantment) — "
            "creature-filter declines it; Phase 2 territory"
        )


def test_phase4_gravpack_monoist_flips_drop_to_admit():
    """Phase 4 (round 50) EoE-pool-delta ADMIT pin — the reject→admit
    conversion of the round-49 Gravpack-Monoist reject assertion.

    Gravpack Monoist (Creature — Robot, flying; "When this creature
    dies, create a tapped 2/2 Robot token.") was DROPPED under Phase 1
    because its ``tapped=True`` create-token rider had no Rust mirror
    (``docs/TOKEN_PRINTING_SUBSTRATE.md`` §2.3 — the only Phase-1
    decline; its Robot token is already vanilla so there is no Phase-3
    Lander dependency). Phase 4 adds ``Effect::CreateTokenTapped`` + the
    ``create_token_tapped`` bridge/recognizer, flipping it drop→admit.
    This is the headline real-card lever of Phase 4 (~25,252 of
    129,996 17lands EoE decks run Gravpack Monoist).
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity.trajectory import (
        _printing_is_bridge_simple_creature,
        _python_ta_to_safe_dict,
    )

    pr = get_active_source().get_printings()
    gm = pr.get("Gravpack Monoist")
    assert gm is not None, "Gravpack Monoist must be in the EoE pool"
    # Carrier admits (flying ∈ _SAFE_KEYWORDS; single DIES+IsSelf
    # trigger round-trips via the create_token_tapped recognizer).
    assert _printing_is_bridge_simple_creature(gm) is True, (
        "Gravpack Monoist must FLIP drop→admit under Phase 4 "
        "(tapped vanilla Robot token — create_token_tapped sister "
        "variant closes the round-49 §2.3 tapped decline)"
    )
    # The DIES+IsSelf trigger recognizes as the tapped sister kind.
    (ta,) = gm.triggered_abilities
    sd = _python_ta_to_safe_dict(ta)
    assert sd is not None
    assert sd["event"] == "dies"
    assert sd["predicate"] == {"kind": "source_is_self"}
    assert sd["effect"]["kind"] == "create_token_tapped", (
        f"Gravpack Monoist's tapped Robot trigger must recognize as "
        f"create_token_tapped, got {sd['effect']['kind']!r}"
    )
    assert sd["effect"]["count"] == 1
    # Pre-seating symbolic form (numeric pid assigned by the loader's
    # _seat_token_printings pass; the token is the vanilla Robot 2/2).
    tcd = sd["effect"]["_token_card_def"]
    assert tcd.name == "Robot"
    assert (tcd.power, tcd.toughness) == (2, 2)
    assert tcd.subtypes == ("Robot",)
    assert "Artifact" in (tcd.card_type, *tcd.extra_card_types)


# ---------------------------------------------------------------------
# Round-51 N1 (round-50 N3 finding 1) — cross-game-safe
# _seat_token_printings regression pins.
#
# Round-50 N3's real multi-game Gravpack-Monoist bench validation
# surfaced a latent round-49 substrate bug: every game past the first
# for a token-carrier-bearing archetype raised
#   ValueError: register_token_printing: pid=N is already registered
#   to a DIFFERENT CardPrinting ('Robot')
# = 56/60 FAIL_EXCEPTION. The in-test probes missed it because they
# drive a SINGLE isolated game; _seat_token_printings registers into
# the cross-game module-global _TOKEN_PRINTING_BY_PID, and the token
# pid varies by seed (the per-game card_defs union ordering depends on
# the opening hand). Before the fix each game built a FRESH token
# CardPrinting object; the registry's identity-based conflicting-
# registration guard then raised on the 2nd+ game.
#
# These pins reproduce the exact gap: ≥2 games of a Gravpack-Monoist-
# bearing scenario across DIFFERENT seeds through the loader, asserting
# (a) no ValueError and (b) correct per-game bridge resolution.
# ---------------------------------------------------------------------


def test_r51_seat_token_printings_cross_game_varying_pid_no_conflict():
    """Unit-level cross-game pin: the SAME logical token seated across
    games at DIFFERENT pids (the seed-varying-union scenario) must NOT
    raise the conflicting-registration ValueError, and every game's
    registration must resolve the right printing.

    This is the deterministic core of round-50 N3 finding 1. Each
    "game" rebuilds the token CardDef FRESH (exactly what
    ``_token_vanilla_card_def`` does per loader invocation — a new,
    distinct-but-equal CardDef) and seats it behind a varying number of
    pad CardDefs so the token's list index (== its Rust-registry pid)
    differs game-to-game, including a game that reuses an earlier pid
    with a freshly-built token (the precise pre-fix crash: a new object
    colliding with a stale same-pid registration). Post-fix
    ``cross_engine.cached_token_printing`` keys by token SHAPE, so the
    registered object is identity-stable across games and the guard
    never fires.

    Round-57 N1 extension: this pin now ALSO asserts the round-51
    same-shape guarantee survives the round-57 cross-shape fix. The
    round-57 fix resets ONLY the ``pid -> CardPrinting`` map at every
    ``_seat_token_printings`` pass entry (a different-shape token can no
    longer collide with a prior game's stale same-pid entry — the
    round-56 N3 finding); it deliberately does NOT clear the shape-keyed
    cache, so the SAME logical token still resolves to the SAME
    identity-stable object across games. This pin captures each game's
    registered object directly and asserts cross-game object identity
    (the round-51 axis) independently of the now-per-game pid map (the
    round-57 axis). The sister cross-SHAPE multi-archetype axis is
    pinned by ``test_r57_unit_cross_shape_distinct_tokens_same_pid_no_
    conflict`` + ``test_r57_real_cross_shape_multi_archetype_no_registry_
    conflict``.
    """
    from mtg_bot.cards.base import make_token_creature
    from mtg_bot.parity.cross_engine import (
        CardDef, clear_token_printings, _TOKEN_PRINTING_BY_PID,
    )
    from mtg_bot.parity.trajectory import (
        _token_vanilla_card_def, _seat_token_printings,
    )

    clear_token_printings()
    try:
        def _one_game(n_pads: int):
            # Fresh token printing + fresh token CardDef every game —
            # this is the loader's per-invocation behavior.
            robot = make_token_creature(
                name="Robot", power=2, toughness=2,
                subtypes=("Robot",), artifact=True,
            )
            tcd = _token_vanilla_card_def(robot)
            carrier = CardDef(
                name="Gravpack-ish", card_type="Creature",
                mana_cost_generic=2, power=2, toughness=1,
                triggered_abilities=(
                    {
                        "event": "dies",
                        "predicate": {"kind": "source_is_self"},
                        "effect": {
                            "kind": "create_token_tapped", "count": 1,
                            "_token_card_def": tcd,
                        },
                    },
                ),
            )
            pads = [
                CardDef(name=f"Pad{i}", card_type="Land",
                        mana_produced=("G",))
                for i in range(n_pads)
            ]
            seated = _seat_token_printings(pads + [carrier])
            names = [c.name for c in seated]
            pid = names.index("Robot")
            # The carrier trigger was rewritten to the numeric pid and
            # the symbolic ref dropped — and the kind survives.
            eff = next(
                c for c in seated if c.name == "Gravpack-ish"
            ).triggered_abilities[0]["effect"]
            assert eff["kind"] == "create_token_tapped"
            assert eff["token_printing_id"] == pid
            assert "_token_card_def" not in eff
            # Capture THIS game's registered printing object directly
            # from the (post-round-57 per-game) pid map, so the round-51
            # same-shape identity guarantee can be asserted across games
            # even though the map is reset each seating pass.
            registered = _TOKEN_PRINTING_BY_PID[pid]
            assert registered.name == "Robot"
            return pid, registered

        # Three games. Pad count drives the deterministic token pid
        # (= token's index in the seated card_defs list). Games 1 & 3
        # use the same pad count -> SAME pid with a FRESH token
        # CardDef: the exact pre-fix "pid=N already registered to a
        # DIFFERENT CardPrinting" crash. Game 2 uses a different pad
        # count -> a DIFFERENT pid (the seed-varying-union scenario).
        # ``_one_game`` returns (pid, registered_printing_object) so the
        # round-51 same-shape identity guarantee can be checked even
        # though (round-57 N1) the pid map is now reset per seating
        # pass — the identity stability lives in the shape cache, which
        # survives the pid-map reset, NOT in stale pid-map entries.
        pid_a, obj_a = _one_game(2)
        pid_b, obj_b = _one_game(5)
        pid_c, obj_c = _one_game(2)
        assert pid_a == pid_c, (
            f"same pad count -> same pid (pre-fix this collided with a "
            f"fresh token object): got {pid_a} then {pid_c}"
        )
        assert pid_b != pid_a, (
            f"different pad count -> different pid (the seed-varying-"
            f"union scenario): got {pid_b} vs {pid_a}"
        )
        # ROUND-51 SAME-SHAPE CROSS-GAME GUARANTEE (the axis this pin
        # protects): the SAME logical token re-seated across games —
        # including at a SHIFTED pid (game 2) and at a REUSED pid with a
        # FRESH token CardDef (game 3 reuses game 1's pid) — must
        # resolve to the SAME identity-stable CardPrinting object every
        # game and never hit the conflicting-registration guard. This
        # holds via cross_engine.cached_token_printing's shape-keyed
        # cache, which the round-57 pid-map-only reset deliberately does
        # NOT clear, so the round-51 fix is intact post-round-57.
        assert obj_a is obj_b is obj_c, (
            "round-51: the same logical token across games must be ONE "
            "identity-stable CardPrinting object (shape cache survives "
            "the round-57 per-seating-pass pid-map reset); got "
            f"{id(obj_a):#x}/{id(obj_b):#x}/{id(obj_c):#x}"
        )
        for o in (obj_a, obj_b, obj_c):
            assert o.name == "Robot"
            assert (o.power, o.toughness) == (2, 2)
        # ROUND-57 N1 invariant: the pid map is now a PER-GAME artifact
        # (reset at every _seat_token_printings pass entry) — only the
        # LAST seating pass's pid is present, mapping to the SAME shared
        # Robot object. Earlier games' (now-dead) pids are gone: that is
        # exactly the cross-shape-collision fix (a later game's
        # DIFFERENT-shape token reusing pid_b can no longer collide with
        # a stale entry). The round-51 same-shape guarantee is unaffected
        # (it lives in the shape cache, asserted above), so this is a
        # corrected invariant, not a regression.
        assert _TOKEN_PRINTING_BY_PID.get(pid_c) is obj_c, (
            "round-57: the final seating pass's pid must resolve to the "
            "identity-stable Robot printing"
        )
        assert pid_b not in _TOKEN_PRINTING_BY_PID, (
            "round-57: the pid map is per-game (reset at pass entry); "
            "an earlier game's now-dead pid must NOT linger — that "
            "lingering was precisely what let a later different-shape "
            "token collide cross-archetype (round-56 N3 finding)"
        )
        robot_objs = {
            id(v) for v in _TOKEN_PRINTING_BY_PID.values()
            if v.name == "Robot"
        }
        assert len(robot_objs) == 1, (
            "the single surviving (current-game) Robot registration "
            f"maps to the one identity-stable object; got "
            f"{len(robot_objs)} distinct objects"
        )
    finally:
        clear_token_printings()


def test_r51_real_gravpack_archetype_multi_game_no_registry_conflict():
    """End-to-end multi-game pin reproducing the EXACT gap the in-test
    probes missed (round-50 N3 finding 1): drive ≥2 full games of a
    real Gravpack-Monoist-bearing 17lands archetype through
    :func:`setup_matched_game_from_real_decks` across DIFFERENT seeds,
    in one process, and assert (a) NO ``ValueError`` from the cross-
    game token registry and (b) correct per-game bridge resolution.

    Archetype 37 carries Gravpack Monoist x3 (round-50 N3 scout +
    ``docs/bench_trajectory_parity_smoke.md`` round-50 minimal repro:
    "archetype 37, seeds 0 and 1"). The bench's ``drive_one_game``
    calls exactly this entrypoint; pre-fix, seed-1 (game 2) raised
    ``ValueError: register_token_printing: pid=N is already registered
    to a DIFFERENT CardPrinting ('Robot')`` because the token's pid
    shifts with the seed-dependent union ordering and game 2 built a
    fresh, conflicting Robot printing — the 56/60 FAIL_EXCEPTION the
    single-game in-test probe could never surface. Post-fix the cached
    printing makes the registration cross-game identity-idempotent.

    Bridge-resolution check (per game, both seeds): the loader-
    materialized Gravpack Monoist's DIES trigger must resolve to a
    ``CreateToken`` whose ``token_printing`` is the right vanilla Robot
    (name "Robot", 2/2, ``tapped=True``) — i.e. the seeded bridge map
    resolved the per-game pid to the correct printing, not just "didn't
    raise".
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import clear_token_printings

    pr = get_active_source().get_printings()
    if pr.get("Gravpack Monoist") is None:
        pytest.skip("Gravpack Monoist absent from active CardSource")

    GRAVPACK_ARCHETYPE = 37  # carries Gravpack Monoist x3
    try:
        deck_names = trajectory.load_production_deck(
            archetype=GRAVPACK_ARCHETYPE
        )
    except (FileNotFoundError, IndexError):
        pytest.skip("17lands deck pool unavailable for archetype 37")
    assert "Gravpack Monoist" in deck_names, (
        "archetype 37 must carry Gravpack Monoist (round-50 N3 scout)"
    )

    clear_token_printings()
    try:
        # Drive 3 games across seeds 0, 1, 2 IN ONE PROCESS — exactly
        # the bench's multi-game loop. Pre-fix, the 2nd game onward
        # raised ValueError from the cross-game registry. We do NOT
        # clear the registry between games (the whole point: the loader
        # must be cross-game-safe on its own).
        for seed in (0, 1, 2):
            # No ValueError must escape here.
            py_state, rust_state = (
                trajectory.setup_matched_game_from_real_decks(
                    deck_names, shared_rng_seed=seed,
                )
            )
            # Bridge resolution: the seated Gravpack Monoist printing
            # (materialized into py_state by build_python_state through
            # the bridge map seeded this game) must carry the right
            # resolved tapped Robot token.
            gm_obj = next(
                (
                    o for o in (
                        list(py_state.players[0].library)
                        + list(py_state.players[0].hand)
                        + list(py_state.players[1].library)
                        + list(py_state.players[1].hand)
                    )
                    if o.printing.name == "Gravpack Monoist"
                ),
                None,
            )
            assert gm_obj is not None, (
                f"seed {seed}: Gravpack Monoist must be materialized "
                f"into a zone (it is admitted by the Phase-4 filter)"
            )
            trigs = gm_obj.printing.triggered_abilities
            assert trigs, (
                f"seed {seed}: materialized Gravpack Monoist must carry "
                f"its DIES trigger"
            )
            create_eff = trigs[0].effect
            tok = create_eff.token_printing
            assert tok is not None, (
                f"seed {seed}: the bridge map must have resolved the "
                f"per-game token pid to a real Robot printing"
            )
            assert tok.name == "Robot", (
                f"seed {seed}: resolved token printing must be Robot, "
                f"got {tok.name!r}"
            )
            assert (tok.power, tok.toughness) == (2, 2), (
                f"seed {seed}: resolved Robot must be 2/2, got "
                f"{tok.power}/{tok.toughness}"
            )
            assert create_eff.tapped is True, (
                f"seed {seed}: Gravpack Monoist makes a TAPPED Robot "
                f"(create_token_tapped sister kind)"
            )
    finally:
        clear_token_printings()


def test_r52_card_def_token_activated_abilities_back_compat_default():
    """Round-52 N1 (Phase-3 precursor): the new
    ``CardDef.token_activated_abilities`` field defaults to ``()`` so
    every pre-round-52 fixture is bit-identical — ``build_rust_state``
    omits the ``activated_abilities`` registry key and
    ``_card_def_to_python_printing`` materializes no extra abilities
    (modulo the orthogonal land mana-ability auto-wire, unchanged).
    """
    import dataclasses

    from mtg_bot.parity.cross_engine import (
        CardDef, _card_def_to_python_printing,
    )

    field_names = {f.name for f in dataclasses.fields(CardDef)}
    assert "token_activated_abilities" in field_names
    cd = CardDef(name="Bear", card_type="Creature", power=2, toughness=2)
    assert cd.token_activated_abilities == ()
    pyp = _card_def_to_python_printing(cd)
    # No land mana-ability auto-wire (it's a Creature) + no token
    # abilities -> empty activated_abilities tuple, exactly as before.
    assert pyp.activated_abilities == ()
    # Land auto-wire path is untouched by the new field.
    forest = CardDef(
        name="Forest", card_type="Land", mana_produced=("G",)
    )
    fp = _card_def_to_python_printing(forest)
    assert len(fp.activated_abilities) == 1
    assert fp.activated_abilities[0].is_mana_ability is True
    assert forest.token_activated_abilities == ()


def test_r52_real_lander_token_still_declined_substrate_only():
    """Round-52→53 contract pin: the vanilla-token helper
    ``_token_vanilla_card_def`` STILL declines the real EoE ``Lander``
    (it has an activated ability + no creature body), but Phase 3a's
    sibling ``_token_with_safe_activated_ability_card_def`` now ADMITS
    it (the §2-honest split — the vanilla path is unchanged; the
    ability-bearing-token path is the new gate).
    """
    from mtg_bot.cards.tokens import TOKEN_PRINTINGS
    from mtg_bot.parity.trajectory import (
        _token_vanilla_card_def,
        _token_with_safe_activated_ability_card_def,
    )

    real_lander = TOKEN_PRINTINGS["Lander"]
    assert len(real_lander.activated_abilities) == 1, (
        "real Lander must carry its {2},Sac ability (fixture sanity)"
    )
    # The vanilla gate is UNCHANGED — still declines the Lander.
    assert _token_vanilla_card_def(real_lander) is None, (
        "_token_vanilla_card_def must still decline the Lander "
        "(activated ability + non-creature body) — Phase 3a does NOT "
        "widen the vanilla gate; it adds a sibling."
    )
    # Phase 3a's sibling gate ADMITS the bare bridge-correct Lander.
    cd = _token_with_safe_activated_ability_card_def(real_lander)
    assert cd is not None, (
        "Phase 3a: the bare Lander (its ONLY activated ability is the "
        "bridge-correct {2},Sac:Search shape) must be ADMITTED by "
        "_token_with_safe_activated_ability_card_def"
    )
    assert cd.name == "Lander"
    assert cd.card_type == "Artifact"
    assert cd.supertypes == ("Token",)
    assert cd.power is None and cd.toughness is None
    assert len(cd.token_activated_abilities) == 1
    aa = cd.token_activated_abilities[0]
    assert aa["cost"] == {"mana": {"generic": 2}, "sacrifice_self": True}
    assert aa["effect"] == {"kind": "search_library_for_basic_land_tapped"}
    assert aa["is_mana_ability"] is False


def test_phase3a_token_with_safe_activated_ability_card_def_gate():
    """Phase 3a §2-strict gate pin: ``_token_with_safe_activated_
    ability_card_def`` admits ONLY the exact bridge-correct bare Lander
    and declines every per-disqualifier variant (the §2 silent-
    mistranslation boundary).
    """
    from mtg_bot.cards.base import (
        CardPrinting, ManaCost, ActivatedAbility, ActivationCost,
        parse_mana_cost, make_token_creature,
    )
    from mtg_bot.effects.generic.search import (
        SearchLibraryForBasicLandTapped,
    )
    from mtg_bot.effects.generic.draw_mill import DrawCards
    from mtg_bot.parity.trajectory import (
        _token_with_safe_activated_ability_card_def as F,
    )

    def _lander(**over):
        cost = over.pop(
            "cost",
            ActivationCost(
                mana=parse_mana_cost("{2}"), mana_str="{2}",
                sacrifice_self=True,
            ),
        )
        effect = over.pop("effect", SearchLibraryForBasicLandTapped())
        kw = dict(
            name="Lander", mana_cost_str="", mana_cost=ManaCost(),
            type_line="Token Artifact — Lander",
            supertypes=("Token",), card_types=("Artifact",),
            subtypes=("Lander",),
            activated_abilities=(
                ActivatedAbility(cost=cost, effect=effect),
            ),
        )
        kw.update(over)
        return CardPrinting(**kw)

    # Canonical bare Lander → ADMIT.
    ok = F(_lander())
    assert ok is not None and ok.card_type == "Artifact"
    assert ok.power is None and ok.toughness is None
    assert len(ok.token_activated_abilities) == 1

    # None → None.
    assert F(None) is None
    # A creature token (vanilla path's job) → declined here.
    assert F(make_token_creature("Robot", 2, 2, artifact=True)) is None
    # Wrong cost mana ({3} not {2}) → §2 decline.
    assert F(_lander(cost=ActivationCost(
        mana=parse_mana_cost("{3}"), sacrifice_self=True))) is None
    # Colored mana in cost → §2 decline.
    assert F(_lander(cost=ActivationCost(
        mana=parse_mana_cost("{1}{G}"), sacrifice_self=True))) is None
    # Missing sacrifice_self → §2 decline.
    assert F(_lander(cost=ActivationCost(
        mana=parse_mana_cost("{2}")))) is None
    # Extra cost component (tap_self) → §2 decline.
    assert F(_lander(cost=ActivationCost(
        mana=parse_mana_cost("{2}"), sacrifice_self=True,
        tap_self=True))) is None
    # Wrong effect (DrawCards) → §2 decline.
    assert F(_lander(effect=DrawCards(amount=1))) is None
    # count != 1 → §2 decline.
    assert F(_lander(
        effect=SearchLibraryForBasicLandTapped(count=2))) is None
    # Two activated abilities → §2 decline (must be exactly one).
    two = _lander()
    two = CardPrinting(
        name="Lander", mana_cost_str="", mana_cost=ManaCost(),
        type_line="Token Artifact — Lander", supertypes=("Token",),
        card_types=("Artifact",), subtypes=("Lander",),
        activated_abilities=(
            two.activated_abilities[0], two.activated_abilities[0],
        ),
    )
    assert F(two) is None
    # Keyword on the token → §2 decline.
    assert F(_lander(keywords=frozenset({"flying"}))) is None


def test_r52_synthetic_lander_card_def_round_trips_both_engines():
    """Round-52 N1: a synthetic token CardDef carrying the Lander
    ``{2},Sac:SearchLibraryForBasicLandTapped`` via
    ``token_activated_abilities`` round-trips through BOTH engines from
    ONE dict — Python ``_card_def_to_python_printing`` builds an
    ``ActivatedAbility`` byte-identical to the real authored Lander,
    and the Rust registry accepts the SAME dict via
    ``build_rust_state``. No Rust change (CE20
    ``activated_abilities`` substrate already on main).
    """
    import pytest

    from mtg_bot.parity.cross_engine import (
        CardDef, _card_def_to_python_printing, build_rust_state,
    )
    from mtg_bot.parity.trajectory import DeckSpec
    from mtg_bot.cards.tokens import TOKEN_PRINTINGS
    from mtg_bot.effects.generic.search import (
        SearchLibraryForBasicLandTapped,
    )

    lander_aa = {
        "cost": {"mana": {"generic": 2}, "sacrifice_self": True},
        "effect": {"kind": "search_library_for_basic_land_tapped"},
    }
    lander = CardDef(
        name="Lander",
        card_type="Artifact",
        supertypes=("Token",),
        subtypes=("Lander",),
        token_activated_abilities=(lander_aa,),
    )
    pyp = _card_def_to_python_printing(lander)
    py_aa = pyp.activated_abilities[0]
    real_aa = TOKEN_PRINTINGS["Lander"].activated_abilities[0]
    assert py_aa.cost.mana.generic == real_aa.cost.mana.generic == 2
    assert (
        py_aa.cost.sacrifice_self == real_aa.cost.sacrifice_self is True
    )
    assert isinstance(py_aa.effect, SearchLibraryForBasicLandTapped)
    assert py_aa.effect.count == real_aa.effect.count == 1
    assert py_aa.is_mana_ability is False

    pytest.importorskip("mtg_bot_engine")
    forest = CardDef(
        name="Forest", card_type="Land", mana_produced=("G",)
    )
    spec = DeckSpec(
        card_defs=(lander, forest),
        p0_library=("Forest",),
        p1_library=("Forest",),
    )
    rust_state = build_rust_state(spec)
    assert rust_state.registry_size == 2


def test_r57_unit_cross_shape_distinct_tokens_same_pid_no_conflict():
    """Round-57 N1 unit pin (round-56 N3 finding — the multi-distinct-
    token cross-archetype pid collision).

    Distinct from round-51 (``test_r51_seat_token_printings_cross_game_
    varying_pid_no_conflict``): round-51 re-seats the SAME token shape
    (Robot) across games at a varying pid — round-51's shape cache makes
    that identity-idempotent. This pin re-seats TWO DIFFERENT token
    shapes (a Robot 2/2 and a Lander 0/0 colorless artifact) and forces
    the SECOND game's Lander onto the EXACT pid the FIRST game's Robot
    occupied. Pre-fix: the module-global ``_TOKEN_PRINTING_BY_PID`` still
    holds game-1's pid->Robot, so game-2's
    ``register_token_printing(pid, Lander)`` hits the identity-conflict
    guard and raises ``ValueError`` (different shapes -> different cached
    objects -> a genuine different-printing-at-same-pid clash that
    round-51's shape cache cannot absorb). Post-fix:
    ``_seat_token_printings`` resets ONLY the pid map at pass entry, so
    game 2 sees a clean slot.

    The pid is forced to collide by giving each game a carrier list
    whose length puts the (single) token at the same list index:
      * Game 1: 1 carrier (Robot carrier) -> Robot pid = 1.
      * Game 2: 1 carrier (Lander carrier) -> Lander pid = 1  (== Robot's
        game-1 pid; the exact cross-shape clash).

    Asserts: (a) NO ValueError across the two sequential seating passes;
    (b) within EACH game the carrier trigger was rewritten to the
    correct numeric pid AND that pid resolves (via the bridge map) to
    the RIGHT shape (game 1 -> Robot 2/2; game 2 -> Lander artifact) —
    i.e. no within-game silent mis-resolution; (c) the round-51
    same-shape guarantee is independently still intact: re-seating the
    SAME Robot shape a third time still shares ONE identity-stable
    printing object (the shape cache is NOT cleared by the pid-map
    reset).
    """
    from mtg_bot.cards.base import make_token_creature
    from mtg_bot.parity.cross_engine import (
        CardDef, clear_token_printings, _TOKEN_PRINTING_BY_PID,
    )
    from mtg_bot.parity.trajectory import (
        _token_vanilla_card_def, _seat_token_printings,
    )

    def _robot_carrier():
        robot = make_token_creature(
            name="Robot", power=2, toughness=2,
            subtypes=("Robot",), artifact=True,
        )
        tcd = _token_vanilla_card_def(robot)
        return CardDef(
            name="RobotCarrier", card_type="Creature",
            mana_cost_generic=2, power=2, toughness=1,
            triggered_abilities=(
                {
                    "event": "dies",
                    "predicate": {"kind": "source_is_self"},
                    "effect": {
                        "kind": "create_token_tapped", "count": 1,
                        "_token_card_def": tcd,
                    },
                },
            ),
        ), tcd

    def _lander_carrier():
        # Lander: 0/0 colorless artifact token (NOT a creature) — a
        # genuinely different shape from the Robot. Built fresh per game
        # (the loader's per-invocation behavior).
        lander = CardDef(
            name="Lander", card_type="Artifact",
            supertypes=("Token",), subtypes=("Lander",),
        )
        return CardDef(
            name="LanderCarrier", card_type="Creature",
            mana_cost_generic=2, power=3, toughness=3,
            triggered_abilities=(
                {
                    "event": "enters",
                    "predicate": {"kind": "source_is_self"},
                    "effect": {
                        "kind": "create_token", "count": 1,
                        "_token_card_def": lander,
                    },
                },
            ),
        ), lander

    clear_token_printings()
    try:
        # --- Game 1: Robot carrier alone -> Robot pid == 1 ---
        rc, _rtcd = _robot_carrier()
        seated1 = _seat_token_printings([rc])
        names1 = [c.name for c in seated1]
        robot_pid = names1.index("Robot")
        assert robot_pid == 1, (
            f"single-carrier game -> token at index 1; got {robot_pid}"
        )
        rp = _TOKEN_PRINTING_BY_PID[robot_pid]
        assert rp.name == "Robot" and (rp.power, rp.toughness) == (2, 2)
        eff1 = next(
            c for c in seated1 if c.name == "RobotCarrier"
        ).triggered_abilities[0]["effect"]
        assert eff1["token_printing_id"] == robot_pid
        assert eff1["kind"] == "create_token_tapped"
        assert "_token_card_def" not in eff1

        # --- Game 2: Lander carrier alone -> Lander pid == 1 too.
        # Pre-fix this raises (pid=1 still holds game-1's Robot, a
        # DIFFERENT CardPrinting). Post-fix the pass-entry pid-map reset
        # clears the stale Robot first, so this is clean. ---
        lc, _ltcd = _lander_carrier()
        seated2 = _seat_token_printings([lc])  # MUST NOT raise
        names2 = [c.name for c in seated2]
        lander_pid = names2.index("Lander")
        assert lander_pid == robot_pid == 1, (
            f"the cross-shape collision requires Lander to land on the "
            f"same pid the prior game's Robot held; got Lander pid "
            f"{lander_pid} vs Robot pid {robot_pid}"
        )
        # Within game 2, that pid must now resolve to the LANDER (not a
        # stale Robot) — no within-game silent mis-resolution.
        lp = _TOKEN_PRINTING_BY_PID[lander_pid]
        assert lp.name == "Lander", (
            f"post-reset, pid {lander_pid} must resolve to this game's "
            f"Lander, not the prior game's stale Robot; got {lp.name!r}"
        )
        assert "Artifact" in (lp.card_types or ()) or lp.is_artifact, (
            f"resolved Lander must be the colorless-artifact shape; got "
            f"card_types={getattr(lp, 'card_types', None)!r}"
        )
        eff2 = next(
            c for c in seated2 if c.name == "LanderCarrier"
        ).triggered_abilities[0]["effect"]
        assert eff2["token_printing_id"] == lander_pid
        assert eff2["kind"] == "create_token"
        assert "_token_card_def" not in eff2
        # The stale Robot entry must be GONE (only this game's Lander
        # registered) — the pid map reflects only the current game.
        assert all(
            v.name != "Robot" for v in _TOKEN_PRINTING_BY_PID.values()
        ), (
            "after the cross-shape game, no stale Robot registration "
            "may survive in the per-game pid map"
        )

        # --- Game 3: re-seat the SAME Robot shape. Round-51 axis still
        # holds: identity-stable shape cache survived the pid-map reset,
        # so this shares ONE Robot CardPrinting object with game 1. ---
        rc3, _ = _robot_carrier()
        seated3 = _seat_token_printings([rc3])  # MUST NOT raise
        robot_pid3 = [c.name for c in seated3].index("Robot")
        rp3 = _TOKEN_PRINTING_BY_PID[robot_pid3]
        assert rp3.name == "Robot"
        assert rp3 is rp, (
            "round-51 same-shape cross-game guarantee must survive the "
            "round-57 pid-map reset: re-seating the SAME Robot shape "
            "must reuse the IDENTITY-STABLE cached printing object "
            "(the shape cache is deliberately NOT cleared by the "
            "pid-map-only reset)"
        )
    finally:
        clear_token_printings()


def test_r57_real_cross_shape_multi_archetype_no_registry_conflict():
    """Round-57 N1 end-to-end pin reproducing round-56 N3's EXACT gap:
    a raw multi-archetype bench sweep carrying ≥2 DISTINCT token shapes
    (Lander vs Robot) in one process must NOT raise the cross-archetype
    pid-collision ``ValueError`` — and each game must still resolve
    BOTH shapes correctly.

    Round-56 N3's minimal repro (``docs/bench_trajectory_parity_smoke.md``
    round-56 CENTRAL FINDING): the bench order
    ``[(37,s) for s in 0..5] + [(73,s) for s in 0..5]`` in one process,
    no ``clear_token_printings()`` between games. arch 37's union (size
    6) assigns Lander=pid6 / Robot=pid7; arch 73's union (size 7) wants
    Lander=pid7 / Robot=pid8, so arch-73's Lander lands on pid 7 where
    arch-37's Robot is still registered process-wide -> pre-fix
    ``ValueError: register_token_printing: pid=7 is already registered
    to a DIFFERENT CardPrinting ('Robot'); refusing to overwrite with
    'Lander'`` on the FIRST arch-73 game. The single-archetype /
    single-shape round-51 pin cannot surface it (it re-seats the SAME
    shape; the cross-ARCHETYPE clash needs two carriers of DIFFERENT
    shapes whose per-game union sizes differ by the right amount).

    Both archetypes carry Gravpack Monoist (DIES -> tapped Robot) AND
    a Lander carrier (arch 73 also carries Galactic Wayfarer
    ENTERS->Lander), so each game seats BOTH a Robot and a Lander
    token. Post-fix (pass-entry pid-map reset, shape cache preserved):
    every game runs clean and each game's per-game pid map resolves
    BOTH shapes to the right printing.

    Asserts, for every game in N3's exact order: (a) NO ``ValueError``
    from the cross-archetype registry; (b) the Robot carrier (Gravpack
    Monoist) resolves to a 2/2 TAPPED Robot AND the Lander carrier
    resolves to a Lander artifact — i.e. both shapes correct in the
    SAME game (no within-game silent mis-resolution despite the prior
    archetype's stale registrations).
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import clear_token_printings

    pr = get_active_source().get_printings()
    if pr.get("Gravpack Monoist") is None or pr.get(
        "Beamsaw Prospector"
    ) is None:
        pytest.skip(
            "Gravpack Monoist / Beamsaw Prospector absent from "
            "active CardSource"
        )

    ROBOT_AND_LANDER_ARCHS = (37, 73)  # both carry Robot + Lander
    try:
        decks = {
            a: trajectory.load_production_deck(archetype=a)
            for a in ROBOT_AND_LANDER_ARCHS
        }
    except (FileNotFoundError, IndexError):
        pytest.skip("17lands deck pool unavailable for archetypes 37/73")
    for a, dn in decks.items():
        assert "Gravpack Monoist" in dn, (
            f"archetype {a} must carry the Robot carrier Gravpack "
            f"Monoist (round-56 N3 scout)"
        )
        assert "Beamsaw Prospector" in dn, (
            f"archetype {a} must carry a Lander carrier (round-56 N3 "
            f"scout: arch {a} carries Beamsaw Prospector)"
        )

    # N3's EXACT bench order: all 6 seeds of arch 37, then all 6 seeds
    # of arch 73, one process, NO clear between games. Pre-fix this is
    # 6/12-clean-then-ValueError at (73, 0).
    order = (
        [(37, s) for s in range(6)] + [(73, s) for s in range(6)]
    )
    clear_token_printings()
    try:
        clean = 0
        for arch, seed in order:
            deck_names = decks[arch]
            # No ValueError must escape (the whole point: a raw
            # multi-archetype multi-distinct-token sweep must be safe).
            py_state, _rust_state = (
                trajectory.setup_matched_game_from_real_decks(
                    deck_names, shared_rng_seed=seed,
                )
            )
            clean += 1
            allobj = (
                list(py_state.players[0].library)
                + list(py_state.players[0].hand)
                + list(py_state.players[1].library)
                + list(py_state.players[1].hand)
            )

            # Robot axis: Gravpack Monoist -> 2/2 TAPPED Robot.
            gm = next(
                (o for o in allobj
                 if o.printing.name == "Gravpack Monoist"),
                None,
            )
            assert gm is not None, (
                f"arch {arch} seed {seed}: Gravpack Monoist must be "
                f"materialized (Phase-4 admitted)"
            )
            gm_eff = gm.printing.triggered_abilities[0].effect
            gm_tok = gm_eff.token_printing
            assert gm_tok is not None and gm_tok.name == "Robot", (
                f"arch {arch} seed {seed}: Gravpack Monoist must "
                f"resolve to a Robot printing, got "
                f"{None if gm_tok is None else gm_tok.name!r} — a "
                f"within-game mis-resolution despite the prior "
                f"archetype's stale registrations"
            )
            assert (gm_tok.power, gm_tok.toughness) == (2, 2)
            assert gm_eff.tapped is True, (
                f"arch {arch} seed {seed}: Gravpack Monoist makes a "
                f"TAPPED Robot (create_token_tapped)"
            )

            # Lander axis (the OTHER shape, same game): Beamsaw
            # Prospector -> Lander. Both shapes must resolve correctly
            # within the SAME game even though their pids differ
            # cross-archetype and a prior archetype's pids are stale.
            bp = next(
                (o for o in allobj
                 if o.printing.name == "Beamsaw Prospector"),
                None,
            )
            assert bp is not None, (
                f"arch {arch} seed {seed}: Beamsaw Prospector must be "
                f"materialized (Phase-3a admitted)"
            )
            bp_tok = bp.printing.triggered_abilities[0].effect.token_printing
            assert bp_tok is not None and bp_tok.name == "Lander", (
                f"arch {arch} seed {seed}: Beamsaw Prospector must "
                f"resolve to a Lander printing, got "
                f"{None if bp_tok is None else bp_tok.name!r} — the "
                f"cross-shape pid collision must NOT cross-wire the "
                f"two distinct token shapes"
            )

        assert clean == len(order), (
            f"every game in N3's exact cross-shape multi-archetype "
            f"order must run clean post-fix; got {clean}/{len(order)} "
            f"(pre-fix: 6/12 then ValueError at (73,0))"
        )
    finally:
        clear_token_printings()


# ===========================================================================
# Phase-6 non-basic-land substrate — PHASE 1 (round-60 N1)
# Spec: docs/NONBASIC_LAND_SUBSTRATE_PLAN.md §2/§3 (round-59 N2).
# Admit the 5 EoE pay-life shocklands as untapped dual-mana lands; the
# guardrail predicate MUST reject the other 18 non-basic-land-gated cards.
# These are the §2 Class-1 guardrail's teeth — the negative pins are the
# anti-count-chasing contract (round-38-E5 anti-pattern §2 prevents).
# ===========================================================================

# The 5 pay-life shocklands the live parser flattens to untapped dual
# `produces` (verified round-60 against OracleParserCardSource). Each maps
# to its sorted dual mana_produced tuple.
_R60_NONBASIC_SHOCKLANDS = {
    "Breeding Pool": ("G", "U"),
    "Watery Grave": ("B", "U"),
    "Stomping Ground": ("G", "R"),
    "Godless Shrine": ("B", "W"),
    "Sacred Foundry": ("R", "W"),
}

# The other 18 non-basic-land-gated cards the §2 guardrail MUST decline:
#  - 5 Planet lands: enters_tapped=True + Station + activated ability
#  - Secluded Starforge: no produces + 3 activated abilities
#  - Cathedral of War: enters_tapped=True + Exalted static + no mana
#  - Echoing Deeps: optional_copy_land_from_graveyard clone
#  - 10 conditional painlands: enters_tapped_unless_any_player_life_at_most=13
_R60_NONBASIC_DECLINE_18 = [
    "Kavaron, Memorial World",
    "Adagia, Windswept Bastion",
    "Susur Secundi, Void Altar",
    "Evendo, Waking Haven",
    "Uthros, Titanic Godcore",
    "Secluded Starforge",
    "Cathedral of War",
    "Echoing Deeps",
    "Abandoned Campground",
    "Bleeding Woods",
    "Etched Cornfield",
    "Lakeside Shack",
    "Murky Sewer",
    "Neglected Manor",
    "Peculiar Lighthouse",
    "Raucous Carnival",
    "Razortrap Gorge",
    "Strangled Cemetery",
]


@pytest.mark.parametrize("name", sorted(_R60_NONBASIC_SHOCKLANDS))
def test_r60_nonbasic_mana_land_admits_each_shockland(name):
    """`_printing_is_bridge_nonbasic_mana_land` accepts each of the 5
    EoE pay-life shocklands — the live parser flattens "pay 2 life or
    enter tapped" to a vanilla untapped dual, which the bridge carries
    byte-equal on both engines (round-39 Ward precedent; documented
    deliberate simplification in SEARCH_LIMITATIONS.md)."""
    from mtg_bot.cards.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import (
        _printing_is_bridge_nonbasic_mana_land,
    )

    by = OracleParserCardSource().get_printings()
    printing = by[name]
    assert _printing_is_bridge_nonbasic_mana_land(printing) is True
    # And it is genuinely non-basic (not double-counted by the basic arm).
    assert "Basic" not in printing.supertypes


@pytest.mark.parametrize("name", _R60_NONBASIC_DECLINE_18)
def test_r60_nonbasic_mana_land_declines_the_other_18(name):
    """The §2 guardrail's teeth: the predicate MUST reject every other
    non-basic-land-gated card — Planet lands (real `enters_tapped`
    inter-engine divergence + Station/AA §2 decline), Secluded
    Starforge (no produces + activated abilities), Cathedral of War
    (tapped + Exalted + no mana), Echoing Deeps (clone replacement),
    and the 10 Duskmourn-shape conditional painlands
    (`enters_tapped_unless_any_player_life_at_most`). Admitting any via
    a bare supertype-gate widen would ship silent mistranslation."""
    from mtg_bot.cards.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import (
        _printing_is_bridge_nonbasic_mana_land,
    )

    by = OracleParserCardSource().get_printings()
    assert _printing_is_bridge_nonbasic_mana_land(by[name]) is False


def test_r60_nonbasic_mana_land_exactly_five_pool_wide():
    """No OTHER non-basic land in the entire merged parser pool passes
    the guardrail — exactly the 5 shocklands, zero spillover. This pins
    the §2-Phase-2 "the guardrail's negative set is exhaustive" claim
    so a future pool regen that introduces a new mana-only nonbasic
    fails loudly here rather than silently widening the admit set."""
    from mtg_bot.cards.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import (
        _printing_is_bridge_nonbasic_mana_land,
    )

    by = OracleParserCardSource().get_printings()
    passers = sorted(
        nm for nm, p in by.items()
        if _printing_is_bridge_nonbasic_mana_land(p)
    )
    assert passers == sorted(_R60_NONBASIC_SHOCKLANDS), passers


@pytest.mark.parametrize(
    "name,expected_mana", sorted(_R60_NONBASIC_SHOCKLANDS.items()),
)
def test_r60_printing_to_card_def_shockland_is_untapped_dual(
    name, expected_mana,
):
    """`_printing_to_card_def(<shockland>)` → the EXACT shape the
    basic-land arm produces (a "Land" CardDef whose `mana_produced` is
    the sorted dual), just without the "Basic" supertype requirement.
    No CardDef field change, no Rust change — the per-color mana-ability
    auto-wire materializes two `{T}: Add <c>` on Python and a 2-element
    `mana_produced` Vec on Rust, byte-equal."""
    from mtg_bot.cards.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import _printing_to_card_def

    by = OracleParserCardSource().get_printings()
    cd = _printing_to_card_def(by[name])
    assert cd.name == name
    assert cd.card_type == "Land"
    assert cd.mana_produced == expected_mana
    # The shockland CardDef carries no creature/ability fields — it is
    # a pure mana source, structurally identical to a basic-land CardDef.
    assert cd.power is None and cd.toughness is None
    assert cd.triggered_abilities == ()
    assert cd.keywords == ()


def test_r60_nonbasic_shockland_admitted_by_production_loader():
    """End-to-end EoE-pool delta pin: the production-deck filter
    (`_filter_deck_to_bridge_supported`) now ADMITS all 5 shocklands
    where `main` dropped them — the drop→admit flip that unblocks
    +5 cards / +18,065 cumulative 17lands decks into the bench."""
    from mtg_bot.cards.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import _filter_deck_to_bridge_supported

    by = OracleParserCardSource().get_printings()
    deck = list(_R60_NONBASIC_SHOCKLANDS) + ["Forest", "Island"]
    filtered, defs = _filter_deck_to_bridge_supported(deck, by)
    for nm in _R60_NONBASIC_SHOCKLANDS:
        assert nm in filtered, (
            f"{nm} must be admitted by the production-deck loader "
            f"(round-60 phase-1 unblock); got {filtered}"
        )
    by_name = {d.name: d for d in defs}
    for nm, mana in _R60_NONBASIC_SHOCKLANDS.items():
        assert by_name[nm].card_type == "Land"
        assert by_name[nm].mana_produced == mana


def test_r60_nonbasic_decline_traps_not_admitted_by_loader():
    """The two highest-deck-count traps — Secluded Starforge (7,570
    decks, activated abilities) and Kavaron (2,493 decks,
    enters_tapped) — must NOT survive the production-deck filter. This
    is the loader-level §2 anti-count-chasing pin (the highest-value
    silent-mistranslation traps)."""
    from mtg_bot.cards.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import _filter_deck_to_bridge_supported

    by = OracleParserCardSource().get_printings()
    deck = ["Secluded Starforge", "Kavaron, Memorial World", "Forest"]
    filtered, _ = _filter_deck_to_bridge_supported(deck, by)
    assert "Secluded Starforge" not in filtered
    assert "Kavaron, Memorial World" not in filtered
    assert "Forest" in filtered  # control: a real basic still admits
