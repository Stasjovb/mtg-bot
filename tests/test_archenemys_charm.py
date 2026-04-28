"""Tests for Archenemy's Charm — full three-mode oracle text.

Audit-found bug: the prior printing shipped only mode 0 (exile target
creature). This module exercises all three modes plus the new helpers
(``ReturnUpToNCreaturesFromYourGraveyardToHand`` and
``PutPlusOneCountersAndGrantKeywordsUEOTOnTargetCreatureYouControl``)
and the broadened ``ModalChooseOne.target_count_range`` upper bound.
"""

from mtg_bot.agents import Agent, RandomAgent
from mtg_bot.cards import SYNTHETIC_CREATURES
from mtg_bot.effects import (
    ExileTargetCreature,
    ModalChooseOne,
    PutPlusOneCountersAndGrantKeywordsUEOTOnTargetCreatureYouControl,
    ReturnUpToNCreaturesFromYourGraveyardToHand,
)
from mtg_bot.game import GameState, Player, Zone

from mtg_bot.cards.source import get_active_source

_PRINTINGS = get_active_source().get_printings()


class _ModeAgent(Agent):
    """Test agent that picks a fixed mode and returns ``picks`` legal
    targets in order from each pool. ``picks=None`` returns the first
    legal target each time."""

    def __init__(self, mode_idx: int, picks=None):
        self.mode_idx = mode_idx
        self.picks = list(picks) if picks is not None else None

    def choose_mode(self, state, player_id, mode_descriptions):
        return self.mode_idx

    def choose_target(self, state, player_id, legal_targets):
        if self.picks is not None:
            while self.picks:
                want = self.picks.pop(0)
                if want is None:
                    return None
                for t in legal_targets:
                    if t == want:
                        return t
            return None
        return legal_targets[0] if legal_targets else None


def _new_state(agent=None):
    state = GameState()
    state.players.append(Player(id=0, agent=agent or RandomAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    return state


# -------------------------------------------------------------
# Mode 0 — Exile target creature
# -------------------------------------------------------------


def test_archenemys_charm_mode_0_exiles_target_creature():
    state = _new_state(_ModeAgent(mode_idx=0))
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear)

    spell = _PRINTINGS["Archenemy's Charm"]
    spell.spell_effect.resolve(state, 0, (("creature", bear.id),))

    # Bear should be exiled (off the battlefield, in opponent's exile).
    assert bear not in state.battlefield
    assert bear in state.players[1].exile
    assert bear.zone == Zone.EXILE


# -------------------------------------------------------------
# Mode 1 — Return one or two creature cards from your graveyard
# -------------------------------------------------------------


def test_archenemys_charm_mode_1_returns_two_from_graveyard():
    state = _new_state(_ModeAgent(mode_idx=1))
    p = state.players[0]
    bear_a = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.GRAVEYARD,
    )
    bear_b = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.GRAVEYARD,
    )
    p.graveyard.extend([bear_a, bear_b])

    spell = _PRINTINGS["Archenemy's Charm"]
    spell.spell_effect.resolve(
        state, 0,
        (
            ("graveyard_creature", bear_a.id),
            ("graveyard_creature", bear_b.id),
        ),
    )

    assert bear_a in p.hand
    assert bear_b in p.hand
    assert bear_a not in p.graveyard
    assert bear_b not in p.graveyard
    assert bear_a.zone == Zone.HAND
    assert bear_b.zone == Zone.HAND


def test_archenemys_charm_mode_1_returns_just_one_when_only_one_exists():
    state = _new_state(_ModeAgent(mode_idx=1))
    p = state.players[0]
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.GRAVEYARD,
    )
    p.graveyard.append(bear)

    spell = _PRINTINGS["Archenemy's Charm"]
    spell.spell_effect.resolve(
        state, 0, (("graveyard_creature", bear.id),),
    )

    assert bear in p.hand
    assert bear not in p.graveyard


# -------------------------------------------------------------
# Mode 2 — Two +1/+1 counters AND lifelink UEOT
# -------------------------------------------------------------


def test_archenemys_charm_mode_2_grants_counters_and_lifelink():
    state = _new_state(_ModeAgent(mode_idx=2))
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear)

    assert bear.plus_one_counters == 0
    assert "lifelink" not in bear.temp_keywords

    spell = _PRINTINGS["Archenemy's Charm"]
    spell.spell_effect.resolve(state, 0, (("creature", bear.id),))

    assert bear.plus_one_counters == 2
    assert "lifelink" in bear.temp_keywords


# -------------------------------------------------------------
# ModalChooseOne plumbing surfaces multi-target range correctly
# -------------------------------------------------------------


def test_archenemys_charm_modal_target_count_range_is_one_to_two():
    """Mode 1 needs (1, 2) targets; modes 0/2 need exactly 1. Union of
    all-targeted modes => (min over all, max over all) = (1, 2)."""
    spell = _PRINTINGS["Archenemy's Charm"]
    effect = spell.spell_effect
    assert isinstance(effect, ModalChooseOne)
    assert effect.requires_target() is True
    assert effect.target_count_range() == (1, 2)


def test_modal_choose_one_filters_targets_for_chosen_mode():
    """When the cast pipeline collected targets for mode 1
    (graveyard_creature picks), choosing mode 0 — which only accepts
    battlefield creatures — must fizzle silently rather than crash."""
    state = _new_state(_ModeAgent(mode_idx=0))
    p = state.players[0]
    gy_card = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.GRAVEYARD,
    )
    p.graveyard.append(gy_card)

    spell = _PRINTINGS["Archenemy's Charm"]
    # Pass a graveyard_creature target but pick exile-creature mode.
    spell.spell_effect.resolve(
        state, 0, (("graveyard_creature", gy_card.id),),
    )
    # No creatures on the battlefield + wrong target kind => fizzle.
    assert gy_card in p.graveyard


# -------------------------------------------------------------
# Component effects — direct unit tests
# -------------------------------------------------------------


def test_return_up_to_n_from_graveyard_legal_targets_creature_only():
    state = _new_state()
    p = state.players[0]
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.GRAVEYARD,
    )
    p.graveyard.append(bear)
    # Non-creature card in graveyard should not appear.
    spell = state.new_object(_PRINTINGS["Plasma Bolt"], 0, Zone.GRAVEYARD)
    p.graveyard.append(spell)

    effect = ReturnUpToNCreaturesFromYourGraveyardToHand(max_n=2)
    legal = effect.legal_targets(state, 0)
    assert ("graveyard_creature", bear.id) in legal
    assert ("graveyard_creature", spell.id) not in legal


def test_return_up_to_n_from_graveyard_no_targets_is_noop():
    state = _new_state()
    effect = ReturnUpToNCreaturesFromYourGraveyardToHand(max_n=2)
    effect.resolve(state, 0, ())
    # No crash, no state change.
    assert state.players[0].hand == []


def test_return_up_to_n_from_graveyard_describe_mentions_max_n():
    text = ReturnUpToNCreaturesFromYourGraveyardToHand(max_n=2).describe()
    assert "2" in text
    assert "graveyard" in text


def test_return_up_to_n_from_graveyard_skips_wrong_kind_and_dupes():
    state = _new_state()
    p = state.players[0]
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.GRAVEYARD,
    )
    p.graveyard.append(bear)
    effect = ReturnUpToNCreaturesFromYourGraveyardToHand(max_n=2)
    # Duplicate IDs and a wrong-kind tuple — should still only return
    # the bear once and not crash on the wrong kind.
    effect.resolve(
        state, 0,
        (
            ("graveyard_creature", bear.id),
            ("graveyard_creature", bear.id),
            ("creature", 999),
        ),
    )
    assert p.hand.count(bear) == 1


def test_return_up_to_n_from_graveyard_missing_id_is_noop():
    state = _new_state()
    effect = ReturnUpToNCreaturesFromYourGraveyardToHand(max_n=2)
    effect.resolve(state, 0, (("graveyard_creature", 4242),))
    assert state.players[0].hand == []


def test_pump_with_counters_describe_includes_keyword():
    effect = PutPlusOneCountersAndGrantKeywordsUEOTOnTargetCreatureYouControl(
        amount=2, granted_keywords=frozenset({"lifelink"}),
    )
    text = effect.describe()
    assert "+1/+1" in text
    assert "lifelink" in text


def test_pump_with_counters_no_target_is_noop():
    state = _new_state()
    effect = PutPlusOneCountersAndGrantKeywordsUEOTOnTargetCreatureYouControl(
        amount=2, granted_keywords=frozenset({"lifelink"}),
    )
    effect.resolve(state, 0, ())
    # No crash.


def test_pump_with_counters_wrong_kind_is_noop():
    state = _new_state()
    effect = PutPlusOneCountersAndGrantKeywordsUEOTOnTargetCreatureYouControl(
        amount=2, granted_keywords=frozenset({"lifelink"}),
    )
    effect.resolve(state, 0, (("graveyard_creature", 1),))


def test_pump_with_counters_missing_target_is_noop():
    state = _new_state()
    effect = PutPlusOneCountersAndGrantKeywordsUEOTOnTargetCreatureYouControl(
        amount=2, granted_keywords=frozenset({"lifelink"}),
    )
    effect.resolve(state, 0, (("creature", 9999),))


def test_pump_with_counters_you_control_only_filter():
    state = _new_state()
    own = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(own)
    opp = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(opp)
    effect = PutPlusOneCountersAndGrantKeywordsUEOTOnTargetCreatureYouControl(
        amount=2, granted_keywords=frozenset({"lifelink"}),
        you_control_only=True,
    )
    legal = effect.legal_targets(state, 0)
    assert ("creature", own.id) in legal
    assert ("creature", opp.id) not in legal


def test_pump_with_counters_no_keywords_skips_keyword_log():
    """describe() and resolve() handle the empty-keywords case
    (covers the conditional log/describe branches)."""
    state = _new_state()
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear)
    effect = PutPlusOneCountersAndGrantKeywordsUEOTOnTargetCreatureYouControl(
        amount=1, granted_keywords=frozenset(),
    )
    text = effect.describe()
    assert "lifelink" not in text
    effect.resolve(state, 0, (("creature", bear.id),))
    assert bear.plus_one_counters == 1
    assert "lifelink" not in bear.temp_keywords
