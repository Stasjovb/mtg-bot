"""Cast-time target shapes: kicker-dependent targets (Tear Asunder) and
Overload's "target" -> "each" rewrite (Damn, Winds of Abandon)."""

from __future__ import annotations

from mtg_bot.actions import CastSpell, cast_time_effect
from mtg_bot.cards.parser.spell_cost_lines import (
    apply_overload,
    parse_alternative_cost_line,
)
from mtg_bot.cards.spell_costs import AlternativeCost
from mtg_bot.effects.combinators import IfConditionElse
from mtg_bot.effects.generic.cast_conditionals import (
    PermanentLeftYourControlThisTurn,
)
from mtg_bot.effects.generic.draw_mill import DrawCards
from mtg_bot.legal import legal_actions

from tests._spells_a_helpers import (
    ScriptedAgent,
    cast_and_resolve,
    cube,
    lands,
    new_game,
    put,
    to_hand,
    to_library,
)


def _casts(state, pid, card):
    return [
        a for a in legal_actions(state, pid)
        if isinstance(a, CastSpell) and a.card_id == card.id
    ]


# ---------- Tear Asunder ----------


def test_tear_asunder_unkicked_only_hits_artifacts_and_enchantments():
    state = new_game()
    lands(state, 0, "Forest", 2)
    elf = put(state, "Llanowar Elves", controller=1)
    ring = put(state, "Sol Ring", controller=1)
    effect = cube("Tear Asunder").spell_effect
    unkicked = cast_time_effect(effect, kicked=False)
    kicked = cast_time_effect(effect, kicked=True)
    assert unkicked.legal_targets(state, 0) == [("permanent", ring.id)]
    assert ("creature", elf.id) in kicked.legal_targets(state, 0)
    assert cast_time_effect(effect) is unkicked


def test_tear_asunder_kicked_exiles_a_creature():
    state = new_game()
    lands(state, 0, "Forest", 2)
    lands(state, 0, "Swamp", 2)
    elf = put(state, "Llanowar Elves", controller=1)
    tear = to_hand(state, "Tear Asunder")
    # Only a creature to hit: the unkicked cast has no legal target, the
    # kicked cast does.
    assert _casts(state, 0, tear) == [CastSpell(tear.id, kicked=True)]
    cast_and_resolve(state, 0, tear, kicked=True)
    assert elf in state.players[1].exile


# ---------- Overload ----------


def test_overload_line_parses_as_alternative_cost():
    assert parse_alternative_cost_line(
        "Overload {2}{W}{W} (You may cast this spell for its overload cost. "
        "If you do, change \"target\" in its text to \"each.\")"
    ) == AlternativeCost(mana="{2}{W}{W}", overload=True)
    assert "overload" in AlternativeCost(mana="{1}", overload=True).describe()


def test_damn_single_target_for_bb():
    state = new_game(ScriptedAgent(yes=False))
    lands(state, 0, "Swamp", 2)
    lands(state, 0, "Plains", 4)
    a = put(state, "Llanowar Elves", controller=1)
    b = put(state, "Elvish Mystic", controller=1)
    a.regeneration_shield = True
    cast_and_resolve(state, 0, to_hand(state, "Damn"))
    assert a in state.players[1].graveyard  # can't be regenerated
    assert b in state.battlefield


def test_damn_overloaded_destroys_each_creature():
    state = new_game(ScriptedAgent(yes=True))
    lands(state, 0, "Plains", 4)
    a = put(state, "Llanowar Elves", controller=1)
    b = put(state, "Elvish Mystic", controller=1)
    mine = put(state, "Birds of Paradise", controller=0)
    damn = to_hand(state, "Damn")
    # Overload is an alternative cost: the cast_for_free variant.
    assert _casts(state, 0, damn) == [CastSpell(damn.id, cast_for_free=True)]
    cast_and_resolve(state, 0, damn, cast_for_free=True)
    assert a not in state.battlefield and b not in state.battlefield
    assert mine not in state.battlefield
    assert state.stack == []


def test_winds_of_abandon_overload_exiles_each_opposing_creature():
    state = new_game(ScriptedAgent(yes=True))
    lands(state, 0, "Plains", 6)
    mine = put(state, "Birds of Paradise", controller=0)
    a = put(state, "Llanowar Elves", controller=1)
    b = put(state, "Elvish Mystic", controller=1)
    basics = [to_library(state, "Forest", owner=1) for _ in range(2)]
    cast_and_resolve(
        state, 0, to_hand(state, "Winds of Abandon"), cast_for_free=True,
    )
    assert mine in state.battlefield
    assert a in state.players[1].exile and b in state.players[1].exile
    assert all(c in state.battlefield and c.tapped for c in basics)


def test_winds_of_abandon_single_target():
    state = new_game(ScriptedAgent(yes=False))
    lands(state, 0, "Plains", 2)
    a = put(state, "Llanowar Elves", controller=1)
    basic = to_library(state, "Forest", owner=1)
    cast_and_resolve(state, 0, to_hand(state, "Winds of Abandon"))
    assert a in state.players[1].exile
    assert basic in state.battlefield


def test_apply_overload_rejects_unparseable_or_targeted_rewrite():
    text = "Draw a card.\nOverload {1}"
    assert apply_overload(
        DrawCards(amount=1), text, "X", lambda t, n: None,
    ) is None
    assert apply_overload(
        DrawCards(amount=1), "Draw a card.", "X", lambda t, n: None,
    ) == DrawCards(amount=1)


def test_non_cast_time_conditions_keep_their_shape():
    eff = IfConditionElse(
        condition=PermanentLeftYourControlThisTurn(),
        then_effect=DrawCards(amount=1),
    )
    assert eff.cast_time_shape(kicked=True, alt_cost_paid=True) is eff
