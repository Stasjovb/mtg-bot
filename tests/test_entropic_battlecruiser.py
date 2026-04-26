"""Tests for Entropic Battlecruiser + opponent-discards observer trigger."""

from mtg_bot.agents import Agent, RandomAgent
from mtg_bot.cards import (
    BASIC_LANDS,
    EOE_CREATURES,
    EOE_SPELLS,
    SYNTHETIC_CREATURES,
)
from mtg_bot.actions import drain_stack
from mtg_bot.combat import declare_attackers
from mtg_bot.effects import (
    DiscardSelf,
    EachOpponentDiscards,
    EachOpponentDiscardsOrLosesLife,
    TargetPlayerLosesLife,
)
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.turn import fire_opponent_discards_triggers


class _PickFirstAgent(Agent):
    def choose_discard(self, state, player_id, hand_card_ids):
        return hand_card_ids[0]


def _new_state(p0_agent=None, p1_agent=None):
    state = GameState()
    state.players.append(
        Player(id=0, agent=p0_agent or _PickFirstAgent())
    )
    state.players.append(
        Player(id=1, agent=p1_agent or _PickFirstAgent())
    )
    return state


# -----------------------
# TargetPlayerLosesLife
# -----------------------


def test_target_player_loses_life():
    state = _new_state()
    TargetPlayerLosesLife(amount=3).resolve(state, 0, (("player", 1),))
    assert state.players[1].life == 17


def test_target_player_loses_life_no_target_noop():
    state = _new_state()
    TargetPlayerLosesLife(amount=3).resolve(state, 0, ())
    assert state.players[1].life == 20


def test_target_player_loses_life_wrong_kind_noop():
    state = _new_state()
    TargetPlayerLosesLife(amount=3).resolve(state, 0, (("creature", 0),))


def test_target_player_loses_life_unknown_player_noop():
    state = _new_state()
    TargetPlayerLosesLife(amount=3).resolve(state, 0, (("player", 99),))


def test_target_player_loses_life_describe():
    assert "life" in TargetPlayerLosesLife(amount=3).describe()


# -----------------------
# EachOpponentDiscardsOrLosesLife
# -----------------------


def test_each_opp_discards_with_hand():
    state = _new_state()
    p1 = state.players[1]
    card = state.new_object(BASIC_LANDS["Forest"], 1, Zone.HAND)
    p1.hand.append(card)
    EachOpponentDiscardsOrLosesLife(life_if_cant=3).resolve(state, 0, ())
    assert card in p1.graveyard
    assert p1.life == 20


def test_each_opp_loses_life_if_cant_discard():
    state = _new_state()
    # P1's hand is empty.
    EachOpponentDiscardsOrLosesLife(life_if_cant=3).resolve(state, 0, ())
    assert state.players[1].life == 17


def test_each_opp_describe():
    text = EachOpponentDiscardsOrLosesLife(life_if_cant=3).describe()
    assert "3" in text


# -----------------------
# opponent_discards_a_card observer trigger firing
# -----------------------


def test_fire_opponent_discards_triggers_fires_entropic():
    """Entropic Battlecruiser at tier 1+ sees an opponent discard → life loss."""
    state = _new_state()
    bc = state.new_object(
        EOE_CREATURES["Entropic Battlecruiser"], 0, Zone.BATTLEFIELD,
    )
    bc.charge_counters = 1  # 1+ tier active
    state.battlefield.append(bc)
    fire_opponent_discards_triggers(state, discarding_player_id=1)
    assert state.players[1].life == 17


def test_fire_opponent_discards_triggers_tier_below_does_not_fire():
    state = _new_state()
    bc = state.new_object(
        EOE_CREATURES["Entropic Battlecruiser"], 0, Zone.BATTLEFIELD,
    )
    bc.charge_counters = 0  # below 1+ tier
    state.battlefield.append(bc)
    fire_opponent_discards_triggers(state, discarding_player_id=1)
    assert state.players[1].life == 20


def test_fire_opponent_discards_skips_same_player_permanents():
    """The trigger only fires for permanents controlled by players
    OTHER than the discarder."""
    state = _new_state()
    bc = state.new_object(
        EOE_CREATURES["Entropic Battlecruiser"], 0, Zone.BATTLEFIELD,
    )
    bc.charge_counters = 1
    state.battlefield.append(bc)
    # P0 is the discarder — bc is under P0, so no trigger.
    fire_opponent_discards_triggers(state, discarding_player_id=0)
    assert state.players[0].life == 20


def test_discard_self_fires_observer_trigger():
    """Full integration: DiscardSelf triggers Entropic's 1+ ability."""
    state = _new_state()
    bc = state.new_object(
        EOE_CREATURES["Entropic Battlecruiser"], 0, Zone.BATTLEFIELD,
    )
    bc.charge_counters = 1
    state.battlefield.append(bc)
    p1 = state.players[1]
    card = state.new_object(BASIC_LANDS["Forest"], 1, Zone.HAND)
    p1.hand.append(card)
    DiscardSelf(amount=1).resolve(state, 1, ())
    # P1 discarded — Entropic (P0) triggers → P1 loses 3 life.
    assert p1.life == 17


def test_each_opponent_discards_fires_observer_trigger():
    """Full integration: EachOpponentDiscards fires the observer."""
    state = _new_state()
    bc = state.new_object(
        EOE_CREATURES["Entropic Battlecruiser"], 0, Zone.BATTLEFIELD,
    )
    bc.charge_counters = 1
    state.battlefield.append(bc)
    p1 = state.players[1]
    card = state.new_object(BASIC_LANDS["Forest"], 1, Zone.HAND)
    p1.hand.append(card)
    EachOpponentDiscards(count=1).resolve(state, 0, ())
    assert p1.life == 17
    assert card in p1.graveyard


def test_entropic_battlecruiser_attack_trigger_cascades_life_loss():
    """Attack fires the untiered trigger → each opponent discards.
    If Entropic is also at 1+, that discard additionally fires the 1+
    trigger for +3 life loss. Stationed at 8+ it's both attacking and
    at 1+ tier."""
    state = _new_state()
    bc = state.new_object(
        EOE_CREATURES["Entropic Battlecruiser"], 0, Zone.BATTLEFIELD,
    )
    bc.charge_counters = 8  # stationed, also at 1+
    bc.summoning_sick = False
    state.battlefield.append(bc)
    p1 = state.players[1]
    card = state.new_object(BASIC_LANDS["Forest"], 1, Zone.HAND)
    p1.hand.append(card)
    declare_attackers(state, [bc.id])
    drain_stack(state)
    # P1 discarded 1 card (from attack trigger); 1+ trigger fires →
    # P1 loses 3 life.
    assert p1.life == 17
    assert card in p1.graveyard


def test_entropic_attack_trigger_empty_hand_loses_3_life():
    state = _new_state()
    bc = state.new_object(
        EOE_CREATURES["Entropic Battlecruiser"], 0, Zone.BATTLEFIELD,
    )
    bc.charge_counters = 8
    bc.summoning_sick = False
    state.battlefield.append(bc)
    # P1 has empty hand.
    declare_attackers(state, [bc.id])
    drain_stack(state)
    # Can't discard → loses 3 life (no 1+ trigger since no discard).
    assert state.players[1].life == 17


def test_entropic_printing_has_both_triggers():
    p = EOE_CREATURES["Entropic Battlecruiser"]
    triggers = {ab.trigger for ab in p.triggered_abilities}
    assert "opponent_discards_a_card" in triggers
    assert "attacks" in triggers
