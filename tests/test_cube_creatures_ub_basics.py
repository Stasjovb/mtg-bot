"""U/B cube creatures, simple shapes: Dark Confidant's reveal-and-lose
life, MV-capped tutors (Spellseeker / Trinket Mage), "other creatures
get -N/-N", hand-activated creature abilities (Harvester of Misery),
"... Tap it." (Iron-Shield Elf), the exile-N-cards-from-graveyard cost
and player-or-planeswalker combat trigger (Psychic Frog), and the
min-blockers evasion (Troll of Khazad-dum)."""

from __future__ import annotations

from mtg_bot.actions import (
    ActivateAbility,
    DeclareBlockers,
    apply_action,
    drain_stack,
)
from mtg_bot.cards.base import make_creature
from mtg_bot.cards.parser.activated import _parse_activation_cost
from mtg_bot.cards.parser.cube_creatures_ub import (
    parse_ub_creature_line,
    parse_ub_effect,
    parse_ub_trigger_phrase,
)
from mtg_bot.cards.parser.effects import _parse_effect
from mtg_bot.combat import declare_attackers
from mtg_bot.effects.combinators import MayDo, Sequence
from mtg_bot.effects.generic.card_flow import SearchLibrary
from mtg_bot.effects.generic.cube_creatures_ub import (
    RevealTopCardToHandLoseLifeEqualMV,
    TapSelf,
)
from mtg_bot.effects.generic.mass_effects import PumpAllCreaturesUEOT
from mtg_bot.effects.predicates import Event
from mtg_bot.game import Zone, effective_keywords, effective_power
from mtg_bot.legal import legal_actions
from mtg_bot.turn import Step, run_beginning_of_upkeep_triggers
from tests._spells_b_helpers import (
    PRINTINGS,
    add,
    add_lands,
    make_state,
)


def _names(zone):
    return [c.printing.name for c in zone]


# ---------------------------------------------------------------- Dark Confidant


def test_confidant_phrase_and_printing():
    eff = parse_ub_effect(
        "reveal the top card of your library and put that card into your "
        "hand. You lose life equal to its mana value"
    )
    assert eff == RevealTopCardToHandLoseLifeEqualMV()
    bob = PRINTINGS["Dark Confidant"]
    assert bob.triggered_abilities[0].event is Event.BEGINNING_OF_UPKEEP
    assert "mana value" in eff.describe()


def test_confidant_upkeep_reveal_costs_life():
    state = make_state(step=Step.UPKEEP)
    add(state, 0, "Dark Confidant", Zone.BATTLEFIELD)
    add(state, 0, "Griselbrand", Zone.LIBRARY)
    run_beginning_of_upkeep_triggers(state)
    drain_stack(state)
    p = state.players[0]
    assert _names(p.hand) == ["Griselbrand"]
    assert p.life == 12
    # Empty library: nothing revealed, no life lost.
    run_beginning_of_upkeep_triggers(state)
    drain_stack(state)
    assert p.life == 12


# ---------------------------------------------------------------- tutors


def test_mv_capped_tutors_parse():
    seek = _parse_effect(
        "you may search your library for an instant or sorcery card with "
        "mana value 2 or less, reveal it, put it into your hand, then shuffle"
    )
    assert isinstance(seek, MayDo) and isinstance(seek.inner, SearchLibrary)
    assert seek.inner.card_filter.max_mv == 2
    trinket = _parse_effect(
        "search your library for an artifact card with mana value 1 or less, "
        "reveal that card, put it into your hand, then shuffle"
    )
    assert trinket.card_filter.max_mv == 1 and trinket.reveal
    assert "Spellseeker" in PRINTINGS and "Trinket Mage" in PRINTINGS


def test_trinket_mage_fetches_only_cheap_artifacts():
    state = make_state()
    add(state, 0, "Sol Ring", Zone.LIBRARY)
    add(state, 0, "Mind Stone", Zone.LIBRARY)
    trinket = PRINTINGS["Trinket Mage"].triggered_abilities[0].effect
    trinket.resolve(state, 0, ())
    assert _names(state.players[0].hand) == ["Sol Ring"]


# ---------------------------------------------------------------- Harvester


def test_other_creatures_get_excludes_the_source():
    eff = _parse_effect("other creatures get -2/-2 until end of turn")
    assert eff == PumpAllCreaturesUEOT(power=-2, toughness=-2, exclude_source=True)
    assert eff.describe() == "other creatures get -2/-2 until end of turn"
    state = make_state()
    harvester = add(state, 0, "Harvester of Misery", Zone.BATTLEFIELD)
    bear = add(state, 1, "Dark Confidant", Zone.BATTLEFIELD)
    state.resolving_source = harvester
    eff.resolve(state, 0, ())
    state.resolving_source = None
    assert effective_power(state, harvester) == 5
    assert effective_power(state, bear) == 0


def test_harvester_hand_ability_discards_itself():
    printing = PRINTINGS["Harvester of Misery"]
    assert len(printing.hand_activated_abilities) == 1
    assert printing.hand_activated_abilities[0].cost.discard_self
    state = make_state()
    add_lands(state, 0, "Swamp", 2)
    card = add(state, 0, "Harvester of Misery", Zone.HAND)
    victim = add(state, 1, "Dark Confidant", Zone.BATTLEFIELD)
    act = ActivateAbility(source_id=card.id, ability_index=0)
    assert act in legal_actions(state, 0)
    apply_action(state, 0, act)
    drain_stack(state)
    assert _names(state.players[0].graveyard) == ["Harvester of Misery"]
    assert victim not in state.battlefield


def test_hand_ability_line_requires_discard_this_card():
    assert parse_ub_creature_line(
        "{1}{B}, Discard this card: Draw a card.", "X",
    ).hand_abilities
    assert parse_ub_creature_line("{1}{B}: Draw a card.", "X") is None


# ---------------------------------------------------------------- Iron-Shield Elf


def test_self_sentence_then_tap_it():
    eff = parse_ub_effect(
        "this creature gains indestructible until end of turn. Tap it"
    )
    assert isinstance(eff, Sequence) and eff.effects[1] == TapSelf()
    assert parse_ub_effect("this creature frobnicates. Tap it") is None
    assert TapSelf().describe() == "tap this creature"


def test_iron_shield_elf_gains_indestructible_and_taps():
    state = make_state()
    elf = add(state, 0, "Iron-Shield Elf", Zone.BATTLEFIELD)
    add(state, 0, "Swamp", Zone.HAND)
    act = ActivateAbility(source_id=elf.id, ability_index=0)
    assert act in legal_actions(state, 0)
    apply_action(state, 0, act)
    drain_stack(state)
    assert elf.tapped
    assert "indestructible" in effective_keywords(state, elf)
    # A source that left the battlefield is not tapped.
    state.resolving_source = elf
    state.battlefield.remove(elf)
    TapSelf().resolve(state, 0, ())
    state.resolving_source = None


# ---------------------------------------------------------------- Psychic Frog


def test_exile_n_cards_cost_piece():
    cost = _parse_activation_cost("Exile three cards from your graveyard")
    assert cost.exile_cards_from_graveyard == 3
    assert "Exile 3 cards" in cost.describe()
    assert _parse_activation_cost("Exile eleventy cards from your graveyard") is None
    assert _parse_activation_cost(
        "Exile two cards from your graveyard, Exile two cards from your graveyard"
    ) is None


def test_psychic_frog_flying_costs_three_graveyard_cards():
    state = make_state()
    frog = add(state, 0, "Psychic Frog", Zone.BATTLEFIELD)
    for _ in range(2):
        add(state, 0, "Swamp", Zone.GRAVEYARD)
    act = ActivateAbility(source_id=frog.id, ability_index=1)
    assert act not in legal_actions(state, 0)
    add(state, 0, "Island", Zone.GRAVEYARD)
    assert act in legal_actions(state, 0)
    apply_action(state, 0, act)
    drain_stack(state)
    assert "flying" in effective_keywords(state, frog)
    assert state.players[0].graveyard == []
    assert len(state.players[0].exile) == 3


def test_psychic_frog_draws_on_player_combat_damage():
    event, pred = parse_ub_trigger_phrase(
        "this creature deals combat damage to a player or planeswalker"
    )
    assert event is Event.DEALS_COMBAT_DAMAGE
    state = make_state(step=Step.DECLARE_ATTACKERS)
    frog = add(state, 0, "Psychic Frog", Zone.BATTLEFIELD)
    add(state, 0, "Island", Zone.LIBRARY)
    declare_attackers(state, [frog.id])
    apply_action(state, 1, DeclareBlockers(assignments=()))
    from mtg_bot.combat import resolve_combat_damage

    resolve_combat_damage(state, 1)
    drain_stack(state)
    assert state.players[1].life == 19
    assert _names(state.players[0].hand) == ["Island"]


# ---------------------------------------------------------------- Troll


def test_min_blockers_line_and_block_legality():
    out = parse_ub_creature_line(
        "This creature can't be blocked except by three or more creatures.",
        "X",
    )
    assert out.fields == {"min_blockers": 3}
    assert PRINTINGS["Troll of Khazad-dûm"].min_blockers == 3
    assert PRINTINGS["Troll of Khazad-dûm"].hand_activated_abilities
    state = make_state(step=Step.DECLARE_ATTACKERS)
    troll = add(state, 0, "Troll of Khazad-dûm", Zone.BATTLEFIELD)
    bear = make_creature("Bear", "{1}{G}", 2, 2)
    blockers = []
    for _ in range(3):
        b = state.new_object(bear, owner_id=1, zone=Zone.BATTLEFIELD)
        b.summoning_sick = False
        state.battlefield.append(b)
        blockers.append(b)
    declare_attackers(state, [troll.id])
    apply_action(state, 1, DeclareBlockers(
        assignments=tuple((b.id, troll.id) for b in blockers[:2]),
    ))
    assert troll.blocked_by == []
    assert all(b.blocking is None for b in blockers)


def test_min_blockers_three_blockers_is_legal():
    state = make_state(step=Step.DECLARE_ATTACKERS)
    troll = add(state, 0, "Troll of Khazad-dûm", Zone.BATTLEFIELD)
    bear = make_creature("Bear", "{1}{G}", 2, 2)
    blockers = []
    for _ in range(3):
        b = state.new_object(bear, owner_id=1, zone=Zone.BATTLEFIELD)
        b.summoning_sick = False
        state.battlefield.append(b)
        blockers.append(b)
    declare_attackers(state, [troll.id])
    apply_action(state, 1, DeclareBlockers(
        assignments=tuple((b.id, troll.id) for b in blockers),
    ))
    assert len(troll.blocked_by) == 3


def test_exhaust_is_not_stripped_as_an_ability_word():
    # Exhaust (CR 702.177) restricts activation; stripping it like an
    # ability word would silently drop that restriction.
    from mtg_bot.cards.parser.activated import _parse_activated_ability_line

    assert _parse_activated_ability_line(
        "Exhaust — {U}, {T}: Draw three cards."
    ) is None
    assert _parse_activated_ability_line(
        "Metalcraft — {T}: Draw a card."
    ) is not None
