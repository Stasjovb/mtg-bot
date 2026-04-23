"""Tests for Orbital Plunge's excess-damage Lander rider."""

from mtg_bot.agents import RandomAgent
from mtg_bot.cards import (
    EOE_SPELLS,
    SYNTHETIC_CREATURES,
    TOKEN_PRINTINGS,
)
from mtg_bot.effects import (
    DealDamageToTargetCreatureWithExcessLanderRider,
)
from mtg_bot.game import GameState, Player, Zone


def _new_state():
    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    return state


def test_orbital_plunge_excess_damage_creates_lander():
    """Target Wild Bear (2/2). Plunge deals 6 — 4 excess → Lander token."""
    state = _new_state()
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear)
    effect = DealDamageToTargetCreatureWithExcessLanderRider(amount=6)
    effect.resolve(state, 0, (("creature", bear.id),))
    assert bear.damage == 6
    landers = [
        o for o in state.battlefield
        if o.printing.name == "Lander" and o.controller_id == 0
    ]
    assert len(landers) == 1


def test_orbital_plunge_no_excess_no_lander():
    """Against a larger creature, the 6 damage is absorbed; no Lander."""
    state = _new_state()
    # Use a creature with ≥6 toughness: Wall of Stone (0/5). Actually we
    # need ≥6; use Great Wurm (6/6).
    wurm = state.new_object(
        SYNTHETIC_CREATURES["Great Wurm"], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(wurm)
    effect = DealDamageToTargetCreatureWithExcessLanderRider(amount=6)
    effect.resolve(state, 0, (("creature", wurm.id),))
    assert wurm.damage == 6
    landers = [
        o for o in state.battlefield
        if o.printing.name == "Lander" and o.controller_id == 0
    ]
    assert landers == []


def test_orbital_plunge_prior_damage_counts_toward_lethal():
    """Bear (2/2) already has 1 damage. 6 more → excess is 5, not 4."""
    state = _new_state()
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD,
    )
    bear.damage = 1
    state.battlefield.append(bear)
    effect = DealDamageToTargetCreatureWithExcessLanderRider(amount=6)
    effect.resolve(state, 0, (("creature", bear.id),))
    assert bear.damage == 7
    landers = [
        o for o in state.battlefield
        if o.printing.name == "Lander" and o.controller_id == 0
    ]
    assert len(landers) == 1


def test_orbital_plunge_no_target_noop():
    state = _new_state()
    effect = DealDamageToTargetCreatureWithExcessLanderRider(amount=6)
    effect.resolve(state, 0, ())  # no crash, no Lander


def test_orbital_plunge_wrong_kind_noop():
    state = _new_state()
    effect = DealDamageToTargetCreatureWithExcessLanderRider(amount=6)
    effect.resolve(state, 0, (("player", 0),))


def test_orbital_plunge_missing_target_still_applies_damage_noop():
    """Target id not on battlefield: no Lander (obj is None → excess=0).
    The _apply_damage helper silently no-ops when the creature is gone."""
    state = _new_state()
    effect = DealDamageToTargetCreatureWithExcessLanderRider(amount=6)
    effect.resolve(state, 0, (("creature", 9999),))
    landers = [o for o in state.battlefield if o.printing.name == "Lander"]
    assert landers == []


def test_orbital_plunge_describe():
    text = DealDamageToTargetCreatureWithExcessLanderRider(amount=6).describe()
    assert "6" in text
    assert "Lander" in text


def test_orbital_plunge_legal_targets_includes_all_creatures():
    state = _new_state()
    ally = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(ally)
    enemy = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(enemy)
    effect = DealDamageToTargetCreatureWithExcessLanderRider(amount=6)
    legal = effect.legal_targets(state, 0)
    ids = {t[1] for t in legal}
    assert ally.id in ids
    assert enemy.id in ids


def test_orbital_plunge_card_printing_wired():
    plunge = EOE_SPELLS["Orbital Plunge"]
    assert isinstance(
        plunge.spell_effect,
        DealDamageToTargetCreatureWithExcessLanderRider,
    )
    assert plunge.spell_effect.amount == 6
