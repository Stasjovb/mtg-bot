"""Tests for TerminalVelocityEffect — "you may put an artifact or creature
card from your hand onto the battlefield" + haste + LTB-damage + end-step-sac.

Oracle text:
    You may put an artifact or creature card from your hand onto the
    battlefield. That permanent gains haste, "When this permanent leaves
    the battlefield, it deals damage equal to its mana value to each
    creature," and "At the beginning of your end step, sacrifice this
    permanent."

Resolution sequence (all exercised below):
1. Agent picks an artifact or creature from hand (or declines).
2. The card is moved from hand to the battlefield.
3. The card gains haste (UEOT continuous effect).
4. A LEAVES_BATTLEFIELD predicate trigger (UEOT) is registered that
   fires DealSelfMVDamageToEachCreature when the card leaves.
5. A SacrificeSourceDelayed delayed trigger is scheduled for the
   caster's next end step.
"""

from __future__ import annotations

from mtg_bot.agents import Agent, RandomAgent
from mtg_bot.cards import BASIC_LANDS, SYNTHETIC_CREATURES
from mtg_bot.cards.tokens import TOKEN_PRINTINGS
from mtg_bot.effects import DealSelfMVDamageToEachCreature, TerminalVelocityEffect
from mtg_bot.game import GameState, Player, Zone, effective_keywords
from mtg_bot.turn import Step, move_off_battlefield, run_cleanup_step

from mtg_bot.cards.source import get_active_source

_PRINTINGS = get_active_source().get_printings()

_TERMINAL_VELOCITY = _PRINTINGS["Terminal Velocity"]


# ------------------------------------------------------------------ helpers --


class _FirstCardAgent(Agent):
    """Always picks the first qualifying card from hand; always says yes."""

    def choose_card_from_hand(self, state, player_id, option_ids):
        return option_ids[0] if option_ids else None

    def choose_target(self, state, player_id, legal_targets):
        return legal_targets[0] if legal_targets else None

    def choose_sacrifice(self, state, player_id, legal_object_ids):
        return legal_object_ids[0] if legal_object_ids else 0

    def choose_yes_no(self, state, player_id, prompt):
        return True


class _DeclineAgent(Agent):
    """Always declines to put a card onto the battlefield."""

    def choose_card_from_hand(self, state, player_id, option_ids):
        return None  # decline

    def choose_target(self, state, player_id, legal_targets):
        return legal_targets[0] if legal_targets else None

    def choose_sacrifice(self, state, player_id, legal_object_ids):
        return legal_object_ids[0] if legal_object_ids else 0

    def choose_yes_no(self, state, player_id, prompt):
        return False


def _new_state(agent=None):
    state = GameState()
    state.players.append(Player(id=0, agent=agent or _FirstCardAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    state.step = Step.PRECOMBAT_MAIN
    return state


def _put_battlefield(state, printing, controller_id, *, tapped=False):
    obj = state.new_object(
        printing, owner_id=controller_id, zone=Zone.BATTLEFIELD
    )
    obj.tapped = tapped
    state.battlefield.append(obj)
    return obj


def _make_hand_card(state, printing, owner_id):
    obj = state.new_object(printing, owner_id=owner_id, zone=Zone.HAND)
    state.players[owner_id].hand.append(obj)
    return obj


# ------------------------------------------------------------------ parser --


def test_terminal_velocity_parser_claim():
    from mtg_bot.cards.parser.source import OracleParserCardSource

    claimed = frozenset(OracleParserCardSource().claimed_names)
    assert "Terminal Velocity" in claimed


def test_terminal_velocity_engine_class_via_parser():
    from mtg_bot.cards.parser.source import OracleParserCardSource

    printings = OracleParserCardSource().get_printings()
    assert printings["Terminal Velocity"].spell_effect == TerminalVelocityEffect()


def test_terminal_velocity_is_sorcery_via_parser():
    from mtg_bot.cards.parser.source import OracleParserCardSource

    p = OracleParserCardSource().get_printings()["Terminal Velocity"]
    assert "Sorcery" in p.card_types


# ------------------------------------------------------------------ resolve --


def test_terminal_velocity_puts_creature_on_battlefield():
    """Resolving the effect puts the chosen creature card from hand onto
    the battlefield under the caster's control."""
    state = _new_state()
    bear_printing = SYNTHETIC_CREATURES["Wild Bear"]
    card = _make_hand_card(state, bear_printing, 0)
    p = state.players[0]
    assert card in p.hand
    TerminalVelocityEffect().resolve(state, 0, targets=())
    # Card moved from hand to battlefield.
    assert card not in p.hand
    assert card in state.battlefield
    assert card.controller_id == 0


def test_terminal_velocity_grants_haste_ueot():
    """The put permanent receives haste as a UEOT continuous effect."""
    state = _new_state()
    card = _make_hand_card(state, SYNTHETIC_CREATURES["Wild Bear"], 0)
    TerminalVelocityEffect().resolve(state, 0, targets=())
    assert card in state.battlefield
    assert "haste" in effective_keywords(state, card)


def test_terminal_velocity_haste_clears_at_cleanup():
    """Haste granted by Terminal Velocity expires at end-of-turn cleanup."""
    state = _new_state()
    card = _make_hand_card(state, SYNTHETIC_CREATURES["Wild Bear"], 0)
    TerminalVelocityEffect().resolve(state, 0, targets=())
    assert "haste" in effective_keywords(state, card)
    run_cleanup_step(state)
    assert "haste" not in effective_keywords(state, card)


def test_terminal_velocity_schedules_end_step_sac():
    """A delayed trigger is added for the caster's current end step."""
    state = _new_state()
    card = _make_hand_card(state, SYNTHETIC_CREATURES["Wild Bear"], 0)
    assert len(state.delayed_triggers) == 0
    TerminalVelocityEffect().resolve(state, 0, targets=())
    assert len(state.delayed_triggers) == 1
    entry = state.delayed_triggers[0]
    assert entry["source_id"] == card.id
    assert entry["controller_id"] == 0


def test_terminal_velocity_decline_noop():
    """When the agent declines (choose_card_from_hand returns None), the
    hand is unchanged and no delayed trigger is scheduled."""
    state = _new_state(agent=_DeclineAgent())
    bear_printing = SYNTHETIC_CREATURES["Wild Bear"]
    card = _make_hand_card(state, bear_printing, 0)
    p = state.players[0]
    TerminalVelocityEffect().resolve(state, 0, targets=())
    # Card stayed in hand.
    assert card in p.hand
    assert card not in state.battlefield
    assert len(state.delayed_triggers) == 0


def test_terminal_velocity_noop_if_no_qualifying_cards_in_hand():
    """If the hand contains only non-artifact, non-creature cards (e.g.,
    a land card), the effect is a silent no-op."""
    state = _new_state()
    # Put a land card in hand. No artifact or creature.
    land = state.new_object(
        BASIC_LANDS["Forest"], owner_id=0, zone=Zone.HAND
    )
    state.players[0].hand.append(land)
    TerminalVelocityEffect().resolve(state, 0, targets=())
    # Land stayed in hand, nothing on battlefield, no delayed trigger.
    assert land in state.players[0].hand
    assert not any(
        o for o in state.battlefield if o.controller_id == 0
    )
    assert len(state.delayed_triggers) == 0


def test_terminal_velocity_ltb_trigger_registered():
    """After resolving, the put permanent has a LEAVES_BATTLEFIELD UEOT
    trigger that will fire DealSelfMVDamageToEachCreature on departure."""
    from mtg_bot.effects.predicates import Event

    state = _new_state()
    card = _make_hand_card(state, SYNTHETIC_CREATURES["Wild Bear"], 0)
    TerminalVelocityEffect().resolve(state, 0, targets=())
    # There should be a UEOT continuous effect granting a triggered ability
    # on the card.
    ltb_grants = [
        ce for ce in state.continuous_effects
        if (
            getattr(ce, "kind", None) == "grant_triggered_ability"
            and ce.target_id == card.id
        )
    ]
    assert ltb_grants, "Expected a grant-triggered-ability UEOT entry for the card"
    ability = ltb_grants[0].params[0]
    assert ability.event == Event.LEAVES_BATTLEFIELD
    assert isinstance(ability.effect, DealSelfMVDamageToEachCreature)


def test_deal_self_mv_damage_to_each_creature_on_ltb():
    """When DealSelfMVDamageToEachCreature resolves, it deals the
    resolving_source's mana value as damage to every creature.

    A Wild Bear (MV = {1}{G} = 2) should deal 2 damage to each creature
    on the battlefield."""
    state = _new_state()
    # Two creatures on the battlefield; the departing card will deal
    # MV damage to both.
    c1 = _put_battlefield(state, SYNTHETIC_CREATURES["Wild Bear"], 0)  # 2/2
    c2 = _put_battlefield(state, SYNTHETIC_CREATURES["Wild Bear"], 1)  # 2/2
    # Simulate the resolving source being a Wild Bear card (MV = 2).
    departing = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.GRAVEYARD
    )
    state.resolving_source = departing
    DealSelfMVDamageToEachCreature().resolve(state, 0, targets=())
    # Each creature on the battlefield took 2 damage.
    assert c1.damage == 2
    assert c2.damage == 2
    state.resolving_source = None


def test_deal_self_mv_damage_noop_if_no_resolving_source():
    """No resolving_source → no damage, no error."""
    state = _new_state()
    c1 = _put_battlefield(state, SYNTHETIC_CREATURES["Wild Bear"], 0)
    state.resolving_source = None
    DealSelfMVDamageToEachCreature().resolve(state, 0, targets=())
    assert c1.damage == 0


def test_deal_self_mv_damage_noop_if_mv_zero():
    """A permanent with MV 0 deals no damage."""
    state = _new_state()
    c1 = _put_battlefield(state, SYNTHETIC_CREATURES["Wild Bear"], 0)
    # Create a token (MV 0) as the resolving source.
    token = state.new_object(
        TOKEN_PRINTINGS["Lander"], owner_id=0, zone=Zone.GRAVEYARD
    )
    state.resolving_source = token
    DealSelfMVDamageToEachCreature().resolve(state, 0, targets=())
    assert c1.damage == 0
    state.resolving_source = None


def test_terminal_velocity_describe():
    text = TerminalVelocityEffect().describe()
    assert "hand" in text
    assert "battlefield" in text
    assert "haste" in text
    assert "sacrifice" in text


def test_deal_self_mv_damage_describe():
    text = DealSelfMVDamageToEachCreature().describe()
    assert "mana value" in text
    assert "creature" in text
