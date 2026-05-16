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


def test_simple_creature_filter_still_rejects_remnant_elemental():
    """Remnant Elemental shares the same landfall+pump_self trigger
    shape as Icecave Crasher but pairs it with a Reach keyword, which
    is outside today's :data:`_SAFE_KEYWORDS` set. The trigger gate
    admits the trigger; the keyword gate still drops the printing.
    Pins the descope so future widening of the safe-keyword set
    surfaces here.
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import (
        _printing_is_bridge_simple_creature,
        _python_ta_to_safe_dict,
    )

    src = OracleParserCardSource()
    remnant = src.get_printings().get("Remnant Elemental")
    if remnant is None:
        # Parser hasn't claimed it yet — descope rationale still
        # applies, but there's nothing to assert against.
        return
    # Trigger-side gate admits the +2/+0 landfall pump.
    assert len(remnant.triggered_abilities) == 1
    assert _python_ta_to_safe_dict(remnant.triggered_abilities[0]) is not None
    # Whole-printing gate still rejects on the Reach keyword.
    assert _printing_is_bridge_simple_creature(remnant) is False


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


def test_python_ta_to_safe_dict_rejects_dies_event_with_non_surveil_effect():
    """The DIES event gate is narrower than the ENTERS gate — only the
    surveil leaf is in the safe set under DIES (no DIES+draw_cards /
    +gain_life / +scry_n entries today). A DIES+IsSelf+DrawCards
    trigger must be rejected because the corresponding triple isn't
    in :data:`_SAFE_TRIGGERS`. Pins the per-event safe-effect-kinds
    table so a future DIES extension is a single edit at the
    safe-set source.
    """
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.predicates import IsSelf, Event
    from mtg_bot.effects.generic.draw_mill import DrawCards
    from mtg_bot.parity.trajectory import _python_ta_to_safe_dict

    ta = TriggeredAbility(
        event=Event.DIES,
        predicate=IsSelf(),
        effect=DrawCards(amount=1),
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


def test_python_ta_to_safe_dict_rejects_attacks_event_with_non_surveil_effect():
    """The ATTACKS event gate is narrower than the ENTERS gate — only
    the surveil leaf is in the safe set under ATTACKS (no ATTACKS+
    draw_cards / +gain_life / +scry_n entries today). An ATTACKS+
    IsSelf+DrawCards trigger must be rejected because the
    corresponding triple isn't in :data:`_SAFE_TRIGGERS`. Mirrors the
    round-42 DIES+non-surveil reject-path test exactly.
    """
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.predicates import IsSelf, Event
    from mtg_bot.effects.generic.draw_mill import DrawCards
    from mtg_bot.parity.trajectory import _python_ta_to_safe_dict

    ta = TriggeredAbility(
        event=Event.ATTACKS,
        predicate=IsSelf(),
        effect=DrawCards(amount=1),
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
