"""Cube spells-B: Escape (cast from the graveyard + exile N other cards),
named counters ("with a corpse counter on it"), and the "if that creature
would leave the battlefield, exile it instead" rider — From the
Catacombs' pieces (its "You take the initiative." needs the initiative
substrate, so the card itself isn't claimed on this branch)."""

from __future__ import annotations

import dataclasses

import pytest

from mtg_bot.actions import CastSpell, apply_action, resolve_top_of_stack
from mtg_bot.alt_casting import escape_payable
from mtg_bot.cards import SYNTHETIC_CREATURES, parse_mana_cost
from mtg_bot.cards.base import LoseLife, Sequence
from mtg_bot.cards.parser.card_flow_grammar import parse_card_flow_effect
from mtg_bot.cards.parser.source import OracleParserCardSource
from mtg_bot.cards.parser.spell_builder import _casting_keyword_fields
from mtg_bot.effects.generic.card_flow import CardFilter
from mtg_bot.effects.generic.reanimation import ReturnCardFromGraveyardToBattlefield
from mtg_bot.game import Zone, set_named_counters
from mtg_bot.legal import legal_actions
from mtg_bot.turn import move_off_battlefield
from tests._spells_b_helpers import ScriptedAgent, add, add_lands, make_state

CREATURE = CardFilter(any_types=("Creature",))


def _creature(state, pid, name, zone=Zone.BATTLEFIELD):
    obj = state.new_object(SYNTHETIC_CREATURES[name], pid, zone)
    p = state.player_by_id(pid)
    if zone == Zone.BATTLEFIELD:
        obj.summoning_sick = False
        state.battlefield.append(obj)
    else:
        p.graveyard.append(obj)
    return obj


def test_escape_line_and_catacombs_blocker():
    assert _casting_keyword_fields(
        "Escape—{3}{B}{B}, Exile five other cards from your graveyard."
    ) == {
        "escape_cost": parse_mana_cost("{3}{B}{B}"),
        "escape_cost_str": "{3}{B}{B}", "escape_exile_count": 5,
    }
    assert _casting_keyword_fields(
        "Escape—{1}, Exile many other cards from your graveyard."
    ) is None
    # Everything but "You take the initiative." parses here.
    assert "From the Catacombs" not in OracleParserCardSource(pool="cube").get_printings()


def test_reanimate_with_counter_exile_rider_and_extra_effect():
    eff = parse_card_flow_effect(
        "put target creature card from a graveyard onto the battlefield under "
        "your control with a corpse counter on it. You lose 2 life. If that "
        "creature would leave the battlefield, exile it instead of putting it "
        "anywhere else"
    )
    assert eff == Sequence(effects=(
        ReturnCardFromGraveyardToBattlefield(
            card_filter=CREATURE, with_counter="corpse",
            exile_if_it_would_leave=True,
        ),
        LoseLife(amount=2),
    ))
    state = make_state()
    bear = _creature(state, 1, "Wild Bear", Zone.GRAVEYARD)
    eff.resolve(state, 0, (("graveyard_card", bear.id),))
    assert bear in state.battlefield and bear.controller_id == 0
    assert bear.named_counters == (("corpse", 1),)
    assert state.players[0].life == 18
    # Dies -> exiled instead (no graveyard stop), counters gone.
    move_off_battlefield(state, bear, destination="graveyard")
    assert bear in state.players[1].exile
    assert not bear.exile_instead_of_leaving


def test_exile_instead_on_bounce_paths():
    from mtg_bot.effects.generic.bounce import ReturnUpToNTargetCreaturesToOwnersHands
    from mtg_bot.effects.generic.targets_helpers import _bounce_to_hand
    from mtg_bot.effects.generic.zone_moves import (
        OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary,
    )

    state = make_state()
    a = _creature(state, 1, "Wild Bear")
    b = _creature(state, 1, "Stone Ogre")
    c = _creature(state, 1, "Raging Goblin")
    for o in (a, b, c):
        o.exile_instead_of_leaving = True
    _bounce_to_hand(state, a)
    ReturnUpToNTargetCreaturesToOwnersHands(max_n=1).resolve(
        state, 0, (("creature", b.id),),
    )
    OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary().resolve(
        state, 0, (("permanent", c.id),),
    )
    exile = state.players[1].exile
    assert a in exile and b in exile and c in exile
    assert state.players[1].hand == [] and state.players[1].library == []


def test_named_counters_accumulate_and_reset_on_reanimation():
    state = make_state()
    bear = _creature(state, 0, "Wild Bear", Zone.GRAVEYARD)
    set_named_counters(bear, "corpse", 3)
    assert bear.named_counters == (("corpse", 3),)
    ReturnCardFromGraveyardToBattlefield(card_filter=CREATURE).resolve(
        state, 0, (("graveyard_card", bear.id),),
    )
    assert bear.named_counters == ()


def _escape_card(state, pid):
    """Demonic Tutor with a synthetic escape cost (the only real escape
    spell in the pool, From the Catacombs, isn't claimable yet)."""
    card = add(state, pid, "Demonic Tutor", Zone.GRAVEYARD)
    card.printing = dataclasses.replace(
        card.printing, escape_cost=parse_mana_cost("{1}{B}"),
        escape_cost_str="{1}{B}", escape_exile_count=2,
    )
    return card


def test_escape_cast_exiles_others_and_returns_to_graveyard():
    state = make_state()
    card = _escape_card(state, 0)
    add(state, 0, "Island", Zone.LIBRARY)
    add_lands(state, 0, "Swamp", 2)
    assert not escape_payable(state, 0, card)
    assert CastSpell(card.id, use_escape=True) not in legal_actions(state, 0)
    looting = add(state, 0, "Faithless Looting", Zone.GRAVEYARD)
    others = [add(state, 0, "Forest", Zone.GRAVEYARD) for _ in range(2)]
    assert escape_payable(state, 0, card)
    assert CastSpell(card.id, use_escape=True) in legal_actions(state, 0)
    apply_action(state, 0, CastSpell(card.id, use_escape=True))
    p = state.players[0]
    assert all(o in p.exile for o in others)
    assert looting in p.graveyard  # flashback cards are kept
    resolve_top_of_stack(state)
    assert card in p.graveyard  # an escaped sorcery isn't exiled
    assert len(p.hand) == 1


def test_escape_instant_speed_only_for_instants():
    from mtg_bot.turn import Step

    state = make_state(step=Step.UPKEEP)
    card = _escape_card(state, 0)
    for _ in range(2):
        add(state, 0, "Forest", Zone.GRAVEYARD)
    add_lands(state, 0, "Swamp", 2)
    assert CastSpell(card.id, use_escape=True) not in legal_actions(state, 0)
    card.printing = dataclasses.replace(
        card.printing, card_types=("Instant",), type_line="Instant",
    )
    assert CastSpell(card.id, use_escape=True) in legal_actions(state, 0)
