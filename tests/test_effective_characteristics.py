"""The effective card-type and color reads (CR 613 layers 4 and 5):
``game.effective_card_types`` / ``has_card_type`` / ``is_artifact_now`` /
``effective_colors`` and the readers routed through them
(``docs/EFFECTIVE_CHARACTERISTICS_DESIGN.md``). Card-level behaviour lives
in ``tests/test_roto_karn_lattice.py``."""

from __future__ import annotations

from dataclasses import replace

import pytest

from mtg_bot.cards.base import HandCardFilter, ManaCost, make_artifact, make_aura
from mtg_bot.effects.generic.card_flow import CardFilter
from mtg_bot.game import (
    LAYER4_ADDABLE_CARD_TYPES,
    ManaCoin,
    Zone,
    clear_departure_card_types,
    effective_card_types,
    effective_colors,
    has_card_type,
    is_artifact_now,
    is_creature_now,
    normalize_added_card_type,
    snapshot_departure_card_types,
    sync_creature_type_cache,
)

from tests._roto_p5_helpers import make_state, place, printing, vanilla

# Mycosynth Lattice's three printing fields on a synthetic artifact (the
# card itself is parsed in tests/test_roto_karn_lattice.py).
LATTICE = replace(
    make_artifact("Test Lattice", "{6}"),
    all_permanents_gain_card_type="Artifact",
    all_objects_colorless=True,
    mana_spendable_as_any_color=True,
)
# Karn, the Great Creator's static on a synthetic artifact.
KARN_LOCK = replace(
    make_artifact("Test Karn Lock", "{4}"),
    locks_opponents_activated_abilities_of=("Artifact",),
)


# ---------------------------------------------------------------------------
# effective_card_types / has_card_type
# ---------------------------------------------------------------------------


def test_printed_types_without_type_changing_effects():
    state = make_state()
    forest = place(state, 0, "Forest")
    bear = place(state, 0, vanilla(2, 2))
    assert effective_card_types(state, forest) is forest.printing.card_types
    assert effective_card_types(state, bear) is bear.printing.card_types
    assert has_card_type(state, forest, "Land")
    assert not has_card_type(state, forest, "Artifact")
    assert not has_card_type(state, forest, "Enchantment")


def test_off_battlefield_objects_keep_printed_types_under_lattice():
    state = make_state()
    place(state, 0, LATTICE)
    for zone in (Zone.HAND, Zone.LIBRARY, Zone.GRAVEYARD, Zone.EXILE):
        card = place(state, 0, "Forest", zone)
        assert effective_card_types(state, card) == ("Land",)
        assert not is_artifact_now(state, card)


def test_registry_add_type_entries_add_artifact():
    state = make_state()
    forest = place(state, 0, "Forest")
    state.add_continuous_effect(
        source_id=forest.id, layer=4, kind="add_type", target_id=forest.id,
        params=("artifact",),
    )
    assert effective_card_types(state, forest) == ("Land", "Artifact")
    # Two entries for the same type don't duplicate it.
    state.add_continuous_effect(
        source_id=forest.id, layer=4, kind="add_type", target_id=forest.id,
        params=("Artifact",),
    )
    assert effective_card_types(state, forest) == ("Land", "Artifact")


def test_only_artifact_and_creature_can_be_added():
    assert LAYER4_ADDABLE_CARD_TYPES == {"Artifact", "Creature"}
    assert normalize_added_card_type("artifact") == "Artifact"
    assert normalize_added_card_type("CREATURE") == "Creature"
    with pytest.raises(ValueError, match="only"):
        normalize_added_card_type("land")
    state = make_state()
    forest = place(state, 0, "Forest")
    with pytest.raises(ValueError):
        state.add_continuous_effect(
            source_id=forest.id, layer=4, kind="add_type",
            target_id=forest.id, params=("enchantment",),
        )


def test_creature_ness_comes_from_is_creature_now():
    state = make_state()
    ring = place(state, 0, "Sol Ring")
    assert not has_card_type(state, ring, "Creature")
    ring.permanent_is_creature = True
    assert effective_card_types(state, ring) == ("Artifact", "Creature")
    assert has_card_type(state, ring, "Creature")
    # An impending-style suppression removes a printed Creature type.
    bear = place(state, 0, vanilla(2, 2))
    bear.impending_active = True
    assert effective_card_types(state, bear) == ()
    assert not has_card_type(state, bear, "Creature")


def test_face_down_permanent_is_only_a_creature():
    state = make_state()
    ring = place(state, 0, "Sol Ring")
    ring.face_down = True
    assert effective_card_types(state, ring) == ("Creature",)
    assert not is_artifact_now(state, ring)
    assert effective_colors(state, ring) == frozenset()
    place(state, 1, LATTICE)
    assert effective_card_types(state, ring) == ("Creature", "Artifact")
    # Off the battlefield the (stale) face-down flag doesn't apply.
    ring.zone = Zone.GRAVEYARD
    assert effective_card_types(state, ring) == ("Artifact",)


def test_phased_out_lattice_adds_nothing():
    state = make_state()
    lattice = place(state, 0, LATTICE)
    forest = place(state, 1, "Forest")
    lattice.phased_out = True
    assert not is_artifact_now(state, forest)
    assert effective_colors(state, forest) == frozenset()  # a land: colorless


# ---------------------------------------------------------------------------
# Last-known types on departure and the creature cache
# ---------------------------------------------------------------------------


def test_departure_snapshot_only_when_types_differ():
    state = make_state()
    forest = place(state, 0, "Forest")
    assert not snapshot_departure_card_types(state, forest)
    assert forest.lki_card_types is None
    place(state, 0, LATTICE)
    assert snapshot_departure_card_types(state, forest)
    forest.zone = Zone.GRAVEYARD
    assert effective_card_types(state, forest) == ("Land", "Artifact")
    # A second snapshot (an outer caller already holds one) is refused.
    assert not snapshot_departure_card_types(state, forest)
    clear_departure_card_types(forest)
    assert effective_card_types(state, forest) == ("Land",)


def test_sync_creature_type_cache_follows_the_registry():
    state = make_state()
    ring = place(state, 0, "Sol Ring")
    other = place(state, 0, "Sol Ring")
    entry = state.add_continuous_effect(
        source_id=ring.id, layer=4, kind="add_type", target_id=ring.id,
        params=("creature",),
    )
    ring.permanent_is_creature = True
    other.permanent_is_creature = True
    sync_creature_type_cache(state, {other.id})
    assert ring.permanent_is_creature and not other.permanent_is_creature
    state.continuous_effects.remove(entry)
    sync_creature_type_cache(state, set())
    assert ring.permanent_is_creature
    sync_creature_type_cache(state)
    assert not ring.permanent_is_creature


def test_leaving_the_battlefield_drops_the_creature_cache():
    from mtg_bot.turn import move_off_battlefield

    state = make_state()
    ring = place(state, 0, "Sol Ring")
    state.add_continuous_effect(
        source_id=ring.id, layer=4, kind="add_type", target_id=ring.id,
        params=("creature",), expires_at="cleanup",
    )
    ring.permanent_is_creature = True
    move_off_battlefield(state, ring, destination="hand")
    assert not ring.permanent_is_creature
    assert not is_creature_now(ring)


# ---------------------------------------------------------------------------
# effective_colors
# ---------------------------------------------------------------------------


def test_colors_unchanged_without_color_changing_effects():
    state = make_state()
    bolt = place(state, 0, "Lightning Bolt", Zone.HAND)
    assert effective_colors(state, bolt) == frozenset({"R"})


def test_lattice_colorless_applies_to_every_zone_and_the_stack():
    state = make_state()
    place(state, 0, LATTICE)
    bolt = place(state, 0, "Lightning Bolt", Zone.HAND)
    assert effective_colors(state, bolt) == frozenset()
    bolt.zone = Zone.STACK
    assert effective_colors(state, bolt) == frozenset()


# ---------------------------------------------------------------------------
# Filters routed through the game object
# ---------------------------------------------------------------------------


def test_card_filter_matches_card_reads_effective_colors_and_types():
    state = make_state()
    elf = place(state, 0, vanilla(1, 1, cost="{G}"), Zone.LIBRARY)
    green = CardFilter(any_types=("Creature",), color="G")
    assert green.matches(elf.printing)
    assert green.matches_card(state, elf)
    place(state, 0, LATTICE)
    assert green.matches(elf.printing)  # a bare printing: printed colors
    assert not green.matches_card(state, elf)
    # Types: a battlefield land under Lattice is an artifact.
    forest = place(state, 1, "Forest")
    arts = CardFilter(any_types=("Artifact",))
    assert not arts.matches(forest.printing)
    assert arts.matches_card(state, forest)
    perms = CardFilter(any_types=("Permanent",))
    assert perms.matches_card(state, forest)


def test_hand_card_filter_matches_card():
    state = make_state()
    bolt = place(state, 0, "Lightning Bolt", Zone.HAND)
    red_instants = HandCardFilter((("Instant", "R"),))
    assert red_instants.matches_card(state, bolt)
    place(state, 0, LATTICE)
    assert not red_instants.matches_card(state, bolt)
    assert HandCardFilter((("Instant", None),)).matches_card(state, bolt)


def test_card_type_or_subtype_filter_matches_card():
    from mtg_bot.effects.generic.cube_creatures_rmc import (
        CardTypeOrSubtypeFilter,
    )

    state = make_state()
    forest = place(state, 1, "Forest")
    f = CardTypeOrSubtypeFilter(types=("Artifact",))
    assert not f.matches_card(state, forest)
    place(state, 0, LATTICE)
    assert f.matches_card(state, forest)


def test_spell_cost_increase_reads_the_spells_effective_colors():
    from mtg_bot.creature_statics_wg import spell_cost_increase

    state = make_state()
    taxer = replace(
        make_artifact("Blue Tax", "{1}"),
        spell_cost_increases=((CardFilter(color="U"), 1),),
    )
    place(state, 1, taxer)
    brainstorm = place(state, 0, "Brainstorm", Zone.HAND)
    assert spell_cost_increase(state, brainstorm.printing, 0, card=brainstorm) == 1
    assert spell_cost_increase(state, brainstorm.printing, 0) == 1
    place(state, 1, LATTICE)
    assert spell_cost_increase(state, brainstorm.printing, 0, card=brainstorm) == 0


# ---------------------------------------------------------------------------
# Activation locks (Karn's opponents scope; suppressed sources)
# ---------------------------------------------------------------------------


def test_activation_lock_sources_without_abilities_lock_nothing():
    from mtg_bot.creature_statics_wg import activation_locked, any_activation_locks

    state = make_state()
    ring = place(state, 1, "Sol Ring")
    assert not any_activation_locks(state)
    karn = place(state, 0, KARN_LOCK)
    assert any_activation_locks(state)
    assert activation_locked(state, ring)
    karn.phased_out = True
    assert not activation_locked(state, ring)
    karn.phased_out = False
    state.add_continuous_effect(
        source_id=karn.id, layer=6, kind="lose_all_abilities", target_id=karn.id,
    )
    assert not activation_locked(state, ring)


def test_null_rod_style_lock_still_applies_to_everyone():
    from mtg_bot.creature_statics_wg import activation_locked

    state = make_state()
    rod = replace(
        make_artifact("Test Rod", "{2}"),
        locks_activated_abilities_of=("Artifact",),
    )
    place(state, 0, rod)
    mine = place(state, 0, "Sol Ring")
    forest = place(state, 1, "Forest")
    assert activation_locked(state, mine)
    assert not activation_locked(state, forest)
    place(state, 1, LATTICE)
    assert activation_locked(state, forest)


# ---------------------------------------------------------------------------
# "Spend mana as though it were mana of any color"
# ---------------------------------------------------------------------------


def test_any_color_spending_pays_pips_with_pool_coins_and_lands():
    from mtg_bot.actions import (
        auto_tap_for_cost,
        can_pay_cost,
        mana_spendable_as_any_color,
    )

    state = make_state()
    place(state, 0, "Island")
    assert not mana_spendable_as_any_color(state)
    assert not can_pay_cost(state, 0, ManaCost(colored=(("R", 1),)))
    place(state, 1, LATTICE)  # either player's Lattice works for both
    assert mana_spendable_as_any_color(state)
    assert can_pay_cost(state, 0, ManaCost(colored=(("R", 1),)))
    sources: list = []
    tapped = auto_tap_for_cost(
        state, 0, ManaCost(colored=(("R", 1),)), color_sources=sources,
    )
    assert len(tapped) == 1
    assert sources == [frozenset({"U"})]  # the mana spent was blue
    # Pool coins: an off-color coin pays a pip; {S} is never widened.
    state.players[0].mana_pool.append(ManaCoin(color="B"))
    sources = []
    auto_tap_for_cost(state, 0, ManaCost(colored=(("G", 1),)), color_sources=sources)
    assert state.players[0].mana_pool == [] and sources == [frozenset({"B"})]
    assert not can_pay_cost(state, 0, ManaCost(colored=(("S", 1),)))


def test_any_color_spending_prefers_exact_colors_first():
    from mtg_bot.actions import _can_pay_from

    state = make_state()
    place(state, 0, LATTICE)
    pool = [ManaCoin(color="U"), ManaCoin(color="R")]
    # {R}{U}: the exact coins are used; an off-color fallback isn't needed.
    assert _can_pay_from(state, ManaCost(colored=(("R", 1), ("U", 1))), pool, [])
    assert not _can_pay_from(
        state, ManaCost(colored=(("R", 1), ("U", 1)), generic=1), pool, [],
    )


def test_sac_for_mana_outputs_pay_any_pip_under_lattice():
    from mtg_bot.actions import _produces_satisfies

    assert not _produces_satisfies((("C", 1),), "R")
    assert _produces_satisfies((("C", 1),), "R", any_color=True)
    assert not _produces_satisfies((("C", 1),), "S", any_color=True)
    assert not _produces_satisfies((("C", 0),), "R", any_color=True)


def test_channel_life_mana_counts_colored_pips_under_lattice():
    from mtg_bot.effects.generic.roto_mana import life_mana_units_needed

    state = make_state()
    place(state, 0, LATTICE)
    # Without Channel's grant there is no life budget at all.
    assert life_mana_units_needed(
        state, 0, ManaCost(colored=(("R", 1),)), [], [],
    ) is None


# ---------------------------------------------------------------------------
# Face-down exile marker
# ---------------------------------------------------------------------------


def test_cards_leaving_exile_are_no_longer_face_down():
    from mtg_bot.effects.generic.cube_creatures_rmc import exile_card

    state = make_state()
    card = place(state, 0, "Sol Ring", Zone.HAND)
    state.players[0].hand.remove(card)
    exile_card(state, card, face_down_for=0)
    assert card.exiled_face_down
    other = place(state, 0, "Mox Sapphire", Zone.HAND)
    state.players[0].hand.remove(other)
    exile_card(state, other)
    assert not other.exiled_face_down


def test_memory_jar_exiles_face_down():
    state = make_state()
    place(state, 0, "Sol Ring", Zone.HAND)
    for _ in range(7):
        place(state, 0, "Island", Zone.LIBRARY)
        place(state, 1, "Island", Zone.LIBRARY)
    jar = printing("Memory Jar").activated_abilities[0].effect
    jar.resolve(state, 0, ())
    (exiled,) = state.players[0].exile
    assert exiled.exiled_face_down


# ---------------------------------------------------------------------------
# The per-game guard for battlefield-synthesized layered statics
# ---------------------------------------------------------------------------


def test_setup_game_records_whether_layered_statics_are_possible():
    from mtg_bot.agents import RandomAgent
    from mtg_bot.simulate import _game_has_layered_statics, setup_game

    state = setup_game(
        [RandomAgent(), RandomAgent()], decks=[["Forest"] * 10, ["Island"] * 10],
        seed=1, enable_mulligans=False,
    )
    assert state.layered_statics_possible is False
    assert state.clone().layered_statics_possible is False
    place(state, 0, LATTICE, Zone.LIBRARY)
    assert _game_has_layered_statics(state)
    # A state built without setup_game keeps the conservative default.
    assert make_state().layered_statics_possible is True


def test_sideboard_lattice_makes_layered_statics_possible():
    from mtg_bot.simulate import _game_has_layered_statics

    state = make_state()
    assert not _game_has_layered_statics(state)
    state.players[1].sideboard = (LATTICE,)
    assert _game_has_layered_statics(state)


def test_without_layered_statics_the_battlefield_isnt_scanned():
    from mtg_bot.actions import mana_spendable_as_any_color

    state = make_state()
    forest = place(state, 1, "Forest")
    bolt = place(state, 1, "Lightning Bolt", Zone.HAND)
    place(state, 0, LATTICE)
    assert is_artifact_now(state, forest) and mana_spendable_as_any_color(state)
    assert effective_colors(state, bolt) == frozenset()
    state.layered_statics_possible = False  # no such card in this game
    assert not is_artifact_now(state, forest)
    assert not mana_spendable_as_any_color(state)
    assert effective_colors(state, bolt) == frozenset({"R"})
