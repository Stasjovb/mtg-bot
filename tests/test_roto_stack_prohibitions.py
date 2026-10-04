"""Roto P1 prohibitions: the "choose a card name" family (Pithing Needle,
Phyrexian Revoker, Disruptor Flute, Meddling Mage), "can't cast ...
this turn" (Silence, Orim's Chant, Ranger-Captain of Eos), High Noon and
Lavinia, Azorius Renegade."""

from __future__ import annotations

from mtg_bot.actions import (
    ActivateAbility,
    CastSpell,
    _sac_for_mana_sources,
    apply_action,
    apply_cost_reductions,
    put_into_battlefield,
    resolve_top_of_stack,
)
from mtg_bot.cards.parser.roto_stack import parse_roto_stack_effect, parse_roto_stack_line
from mtg_bot.combat import eligible_attackers
from mtg_bot.creature_casting_ub import can_cast_now
from mtg_bot.effects.generic.roto_stack import (
    CantCastSpellsThisTurn,
    CreaturesCantAttackThisTurn,
)
from mtg_bot.game import Zone
from mtg_bot.legal import legal_actions
from mtg_bot.roto_restrictions import (
    CastProhibition,
    choose_card_name_as_enters,
    max_x_allowed,
    nameable_card_names,
)
from mtg_bot.turn import run_cleanup_step

from tests._roto_helpers import (
    ScriptedAgent,
    agent,
    arena,
    printing,
    put,
    to_graveyard,
    to_hand,
    to_library,
)


def _lands(state, name, n, pid=0):
    return [put(state, printing(name), pid) for _ in range(n)]


def _legal(state, pid):
    state.priority_player_idx = pid
    return legal_actions(state, pid)


def _cast(state, pid, card, **kw):
    state.priority_player_idx = pid
    apply_action(state, pid, CastSpell(card.id, **kw))


def _drain(state):
    while state.stack:
        resolve_top_of_stack(state)


class _Names(ScriptedAgent):
    """Picks a named option from ``choose_mode``."""

    def __init__(self, name):
        super().__init__()
        self.name = name

    def choose_mode(self, state, player_id, options):
        return options.index(self.name) if self.name in options else 0


def _enter_naming(state, card_name, name, pid=0):
    state.players[pid].agent = _Names(name)
    card = to_hand(state, printing(card_name), pid)
    state.players[pid].hand.remove(card)
    card.zone = Zone.STACK
    put_into_battlefield(state, card, pid)
    card.summoning_sick = False
    state.players[pid].agent = ScriptedAgent()
    return card


def _activations(state, obj, pid):
    return [
        a for a in _legal(state, pid)
        if isinstance(a, ActivateAbility) and a.source_id == obj.id
    ]


# ---------------------------------------------------------------------
# Names offered
# ---------------------------------------------------------------------


def test_nameable_names_are_the_opponents_cards():
    state = arena()
    to_library(state, printing("Lightning Bolt"), 1)
    to_hand(state, printing("Sol Ring"), 1)
    to_graveyard(state, printing("Wasteland"), 1)
    put(state, printing("Mother of Runes"), 1)
    to_hand(state, printing("Brainstorm"), 0)  # ours: not offered
    assert nameable_card_names(state, 0, nonland=False) == [
        "Lightning Bolt", "Mother of Runes", "Sol Ring", "Wasteland",
    ]
    assert "Wasteland" not in nameable_card_names(state, 0, nonland=True)


def test_name_choice_with_nothing_to_name():
    state = arena()
    needle = _enter_naming(state, "Pithing Needle", "anything")
    assert needle.chosen_card_name is None
    choose_card_name_as_enters(state, put(state, printing("Sol Ring"), 0), 0)


# ---------------------------------------------------------------------
# Pithing Needle / Phyrexian Revoker / Disruptor Flute
# ---------------------------------------------------------------------


def test_pithing_needle_stops_non_mana_abilities_only():
    state = arena(active=1)
    land = put(state, printing("Wasteland"), 1)
    ring = put(state, printing("Sol Ring"), 1)
    put(state, printing("Mox Sapphire"), 1)
    assert _activations(state, land, 1)
    needle = _enter_naming(state, "Pithing Needle", "Wasteland")
    assert needle.chosen_card_name == "Wasteland"
    acts = _activations(state, land, 1)
    abilities = land.printing.activated_abilities
    assert all(abilities[a.ability_index].is_mana_ability for a in acts)
    assert _activations(state, ring, 1)


def test_phyrexian_revoker_stops_mana_abilities_too():
    state = arena(active=1)
    ring = put(state, printing("Sol Ring"), 1)
    revoker = _enter_naming(state, "Phyrexian Revoker", "Sol Ring")
    assert revoker.chosen_card_name == "Sol Ring"
    assert not _activations(state, ring, 1)


def test_revoker_locks_sac_for_mana_during_payment():
    state = arena(active=1)
    petal = put(state, printing("Lotus Petal"), 1)
    assert any(src is petal for src, _i, _p in _sac_for_mana_sources(state, 1))
    _enter_naming(state, "Phyrexian Revoker", "Lotus Petal")
    assert not any(src is petal for src, _i, _p in _sac_for_mana_sources(state, 1))


def test_disruptor_flute_taxes_and_locks_the_name():
    state = arena(active=1)
    to_hand(state, printing("Lightning Bolt"), 1)
    jace = put(state, printing("Jace, the Mind Sculptor"), 1)
    jace.loyalty_counters = 3
    _enter_naming(state, "Disruptor Flute", "Lightning Bolt")
    bolt = printing("Lightning Bolt")
    assert apply_cost_reductions(bolt, state, 1, bolt.mana_cost).generic == 3
    # Jace isn't named: still activatable.
    assert _activations(state, jace, 1)
    flute2 = _enter_naming(state, "Disruptor Flute", "Jace, the Mind Sculptor")
    assert flute2.chosen_card_name == "Jace, the Mind Sculptor"
    assert not _activations(state, jace, 1)


# ---------------------------------------------------------------------
# Meddling Mage
# ---------------------------------------------------------------------


def test_meddling_mage_forbids_casting_the_name():
    state = arena(active=1)
    bolt = to_hand(state, printing("Lightning Bolt"), 1)
    _lands(state, "Mountain", 1, 1)
    assert CastSpell(bolt.id) in _legal(state, 1)
    _enter_naming(state, "Meddling Mage", "Lightning Bolt")
    assert CastSpell(bolt.id) not in _legal(state, 1)
    # Nor can it be cast while an effect resolves.
    assert not can_cast_now(state, 1, bolt, free=True)
    # The Mage's controller can't cast it either.
    mine = to_hand(state, printing("Lightning Bolt"), 0)
    _lands(state, "Mountain", 1, 0)
    state.active_player_idx = 0
    assert CastSpell(mine.id) not in _legal(state, 0)


# ---------------------------------------------------------------------
# Silence / Orim's Chant / Ranger-Captain of Eos
# ---------------------------------------------------------------------


def test_silence_stops_opponent_casts_until_cleanup():
    state = arena(active=0)
    silence = to_hand(state, printing("Silence"))
    _lands(state, "Plains", 1)
    _cast(state, 0, silence)
    _drain(state)
    bolt = to_hand(state, printing("Lightning Bolt"), 1)
    _lands(state, "Mountain", 1, 1)
    assert CastSpell(bolt.id) not in _legal(state, 1)
    # Our own spells are fine.
    mine = to_hand(state, printing("Lightning Bolt"), 0)
    _lands(state, "Mountain", 1, 0)
    assert CastSpell(mine.id) in _legal(state, 0)
    run_cleanup_step(state)
    assert not state.emblems
    assert CastSpell(bolt.id) in _legal(state, 1)


def test_orims_chant_targets_a_player_and_kicked_stops_attacks():
    state = arena(active=1)
    attacker = put(state, printing("Mother of Runes"), 1)
    assert eligible_attackers(state, 1) == [attacker]
    chant = to_hand(state, printing("Orim's Chant"))
    _lands(state, "Plains", 2)
    agent(state, 0).targets = [("player", 1)]
    _cast(state, 0, chant, kicked=True)
    _drain(state)
    bolt = to_hand(state, printing("Lightning Bolt"), 1)
    _lands(state, "Mountain", 1, 1)
    assert CastSpell(bolt.id) not in _legal(state, 1)
    assert eligible_attackers(state, 1) == []


def test_orims_chant_unkicked_leaves_attacks_alone():
    state = arena(active=1)
    attacker = put(state, printing("Mother of Runes"), 1)
    chant = to_hand(state, printing("Orim's Chant"))
    _lands(state, "Plains", 1)
    agent(state, 0).targets = [("player", 1)]
    _cast(state, 0, chant)
    _drain(state)
    assert eligible_attackers(state, 1) == [attacker]


def test_ranger_captain_stops_noncreature_spells():
    state = arena(active=0)
    captain = put(state, printing("Ranger-Captain of Eos"), 0)
    acts = _activations(state, captain, 0)
    assert acts
    apply_action(state, 0, acts[0])
    _drain(state)
    assert captain in state.players[0].graveyard
    bolt = to_hand(state, printing("Lightning Bolt"), 1)
    mom = to_hand(state, printing("Mother of Runes"), 1)
    _lands(state, "Mountain", 1, 1)
    _lands(state, "Plains", 1, 1)
    state.active_player_idx = 1
    legal = _legal(state, 1)
    assert CastSpell(bolt.id) not in legal
    assert CastSpell(mom.id) in legal


def test_cant_cast_effect_edges():
    eff = CantCastSpellsThisTurn(who="target_player")
    state = arena()
    assert eff.requires_target()
    assert eff.legal_targets(state, 0) == [("player", 0), ("player", 1)]
    eff.resolve(state, 0, ())
    eff.resolve(state, 0, (("creature", 3),))
    assert not state.emblems
    assert CantCastSpellsThisTurn().legal_targets(state, 0) == []
    assert "target player" in eff.describe()
    assert "your opponents" in CantCastSpellsThisTurn().describe()
    assert CreaturesCantAttackThisTurn().describe().startswith("creatures")
    try:
        CastProhibition(who="nobody")
    except ValueError:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected ValueError")


# ---------------------------------------------------------------------
# High Noon
# ---------------------------------------------------------------------


def test_high_noon_one_spell_each_turn_and_its_sacrifice_ability():
    state = arena(active=0)
    noon = put(state, printing("High Noon"), 0)
    b1 = to_hand(state, printing("Lightning Bolt"))
    b2 = to_hand(state, printing("Lightning Bolt"))
    _lands(state, "Mountain", 2)
    agent(state, 0).targets = [("player", 1)]
    _cast(state, 0, b1)
    _drain(state)
    assert CastSpell(b2.id) not in _legal(state, 0)
    _lands(state, "Mountain", 5)
    acts = _activations(state, noon, 0)
    assert acts
    agent(state, 0).targets = [("player", 1)]
    apply_action(state, 0, acts[0])
    _drain(state)
    assert noon in state.players[0].graveyard
    assert state.players[1].life == 20 - 3 - 5


# ---------------------------------------------------------------------
# Lavinia, Azorius Renegade
# ---------------------------------------------------------------------


def test_lavinia_caps_noncreature_mana_value_by_lands():
    state = arena(active=1)
    put(state, printing("Lavinia, Azorius Renegade"), 0)
    walk = to_hand(state, printing("Time Walk"), 1)  # mana value 2
    _lands(state, "Island", 1, 1)
    to_hand(state, printing("Mother of Runes"), 1)
    assert CastSpell(walk.id) not in _legal(state, 1)
    _lands(state, "Island", 1, 1)
    assert CastSpell(walk.id) in _legal(state, 1)


def test_lavinia_caps_x():
    state = arena(active=1)
    put(state, printing("Lavinia, Azorius Renegade"), 0)
    chalice = to_hand(state, printing("Chalice of the Void"), 1)
    _lands(state, "Island", 4, 1)
    assert max_x_allowed(state, 1, chalice) == 2
    _lands(state, "Island", 1, 1)
    # Five lands: mana value 2X <= 5 -> X <= 2, though X = 2 affordable.
    assert max_x_allowed(state, 1, chalice) == 2
    agent(state, 1).x_value = 99
    _cast(state, 1, chalice)
    assert state.stack[0].x_value == 2
    # No cap for the Lavinia player or for non-X spells.
    assert max_x_allowed(state, 0, chalice) is None
    assert max_x_allowed(state, 1, to_hand(state, printing("Time Walk"), 1)) is None


def test_lavinia_counters_free_spells():
    state = arena(active=1)
    put(state, printing("Lavinia, Azorius Renegade"), 0)
    mox = to_hand(state, printing("Mox Sapphire"), 1)
    _cast(state, 1, mox)
    assert len(state.stack) == 2  # the Mox and Lavinia's trigger
    _drain(state)
    assert mox in state.players[1].graveyard


# ---------------------------------------------------------------------
# Grammar edges
# ---------------------------------------------------------------------


def test_prohibition_grammar_edges():
    card = {"name": "X"}
    assert parse_roto_stack_line(
        "Each opponent can't cast wombat spells with mana value greater than "
        "the number of lands that player controls.", card,
    ) is None
    assert parse_roto_stack_effect("your opponents can't cast wombat spells this turn") is None
    assert parse_roto_stack_effect("if this spell was kicked, frobnicate") is None
    assert parse_roto_stack_effect(
        "if this spell was kicked, destroy target creature"
    ) is None
    assert parse_roto_stack_effect(
        "if this spell was kicked, it deals 4 damage instead"
    ) is None
    # "It deals" after "Sacrifice this enchantment" is the activated-ability
    # grammar's (High Noon); a bare "it deals" phrase isn't ours.
    assert parse_roto_stack_effect("it deals 2 damage to any target") is None
