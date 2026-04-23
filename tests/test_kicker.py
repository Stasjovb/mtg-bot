"""Tests for kicker mechanism + Consult the Star Charts."""

from mtg_bot.actions import (
    CastSpell,
    apply_action,
    resolve_top_of_stack,
)
from mtg_bot.agents import Agent, RandomAgent
from mtg_bot.cards import (
    BASIC_LANDS,
    EOE_SPELLS,
    SYNTHETIC_CREATURES,
    ManaCost,
    parse_mana_cost,
)
from mtg_bot.effects import ConsultTheStarChartsEffect
from mtg_bot.game import GameState, Player, StackItem, Zone
from mtg_bot.legal import legal_actions
from mtg_bot.turn import Step


class _TakeFirstAgent(Agent):
    def choose_card_from_library(self, state, player_id, option_ids):
        return option_ids[0] if option_ids else None

    def choose_target(self, state, player_id, legal_targets):
        return legal_targets[0] if legal_targets else None


def _new_state(lands: int = 0, library_size: int = 0, agent=None):
    state = GameState()
    p = Player(id=0, agent=agent or _TakeFirstAgent())
    state.players.append(p)
    state.players.append(Player(id=1, agent=RandomAgent()))
    state.step = Step.PRECOMBAT_MAIN
    for _ in range(lands):
        island = state.new_object(BASIC_LANDS["Island"], 0, Zone.BATTLEFIELD)
        state.battlefield.append(island)
    for _ in range(library_size):
        c = state.new_object(BASIC_LANDS["Forest"], 0, Zone.LIBRARY)
        p.library.append(c)
    return state


# -----------------------
# Kicker cost parsing + CardPrinting wiring
# -----------------------


def test_consult_printing_has_kicker_cost():
    p = EOE_SPELLS["Consult the Star Charts"]
    assert p.kicker_cost is not None
    assert p.kicker_cost == parse_mana_cost("{1}{U}")
    assert p.kicker_cost_str == "{1}{U}"


# -----------------------
# Legal actions expose kicked variants
# -----------------------


def test_legal_actions_include_kicked_when_payable():
    # Need 4 Islands to pay {1}{U} base + {1}{U} kicker.
    state = _new_state(lands=4, library_size=2)
    consult = state.new_object(
        EOE_SPELLS["Consult the Star Charts"], 0, Zone.HAND,
    )
    state.players[0].hand.append(consult)
    acts = [a for a in legal_actions(state, 0) if isinstance(a, CastSpell)]
    # Expect both an unkicked and a kicked option.
    assert any(a.kicked is False for a in acts)
    assert any(a.kicked is True for a in acts)


def test_legal_actions_skip_kicked_when_unpayable():
    # Only 2 Islands — can pay base but not kicker.
    state = _new_state(lands=2, library_size=2)
    consult = state.new_object(
        EOE_SPELLS["Consult the Star Charts"], 0, Zone.HAND,
    )
    state.players[0].hand.append(consult)
    acts = [a for a in legal_actions(state, 0) if isinstance(a, CastSpell)]
    # Only unkicked variant.
    assert all(a.kicked is False for a in acts if a.card_id == consult.id)


# -----------------------
# _cast_spell pays kicker + sets StackItem.kicked
# -----------------------


def test_cast_kicker_taps_extra_lands_and_marks_stack_item():
    state = _new_state(lands=4, library_size=2)
    consult = state.new_object(
        EOE_SPELLS["Consult the Star Charts"], 0, Zone.HAND,
    )
    state.players[0].hand.append(consult)
    apply_action(state, 0, CastSpell(consult.id, kicked=True))
    # All 4 Islands tapped.
    taps = sum(1 for o in state.battlefield if o.tapped)
    assert taps == 4
    # StackItem carries kicked=True.
    item = state.stack[-1]
    assert isinstance(item, StackItem)
    assert item.kicked is True


def test_cast_without_kicker_leaves_stack_item_kicked_false():
    state = _new_state(lands=4, library_size=2)
    consult = state.new_object(
        EOE_SPELLS["Consult the Star Charts"], 0, Zone.HAND,
    )
    state.players[0].hand.append(consult)
    apply_action(state, 0, CastSpell(consult.id))
    assert state.stack[-1].kicked is False


# -----------------------
# ConsultTheStarChartsEffect behaviour
# -----------------------


def test_consult_unkicked_picks_one_card():
    state = _new_state(lands=3, library_size=5)
    consult = state.new_object(
        EOE_SPELLS["Consult the Star Charts"], 0, Zone.HAND,
    )
    state.players[0].hand.append(consult)
    apply_action(state, 0, CastSpell(consult.id))
    resolve_top_of_stack(state)
    p = state.players[0]
    # 1 card in hand from Consult; 5 - 1 = 4 remaining in library
    # (original examined 3, kept 1, bottomed 2 — plus the 2 never
    # looked at still on top/bottom = 4 total).
    # Track by the specific card that moved: hand has one of the
    # first-3 cards. Library total = 4.
    assert len(p.library) == 4


def test_consult_kicked_picks_two_cards():
    state = _new_state(lands=3, library_size=5)
    consult = state.new_object(
        EOE_SPELLS["Consult the Star Charts"], 0, Zone.HAND,
    )
    state.players[0].hand.append(consult)
    # Need 2 more Islands to pay kicker. 3 currently; _cast_spell
    # will auto-tap so set 4 total.
    extra = state.new_object(BASIC_LANDS["Island"], 0, Zone.BATTLEFIELD)
    state.battlefield.append(extra)
    apply_action(state, 0, CastSpell(consult.id, kicked=True))
    resolve_top_of_stack(state)
    p = state.players[0]
    # With X=4 lands and kicker=True, examine top 4, keep 2, bottom 2.
    # Hand starts at 1 (the Consult card itself is gone to graveyard)
    # and gains 2. Library was 5 → now 3.
    # Actually Consult is in graveyard after resolve, so hand has only
    # the 2 kept cards.
    assert len([c for c in p.hand]) == 2
    assert len(p.library) == 3


def test_consult_with_zero_lands_no_op():
    state = _new_state(lands=0, library_size=5)
    effect = ConsultTheStarChartsEffect()
    p = state.players[0]
    effect.resolve(state, 0, ())
    # No lands → X=0, nothing happens.
    assert len(p.library) == 5
    assert p.hand == []


def test_consult_empty_library_no_op():
    state = _new_state(lands=3, library_size=0)
    effect = ConsultTheStarChartsEffect()
    effect.resolve(state, 0, ())


def test_consult_reads_resolving_kicked():
    state = _new_state(lands=3, library_size=5)
    effect = ConsultTheStarChartsEffect()
    state.resolving_kicked = True
    effect.resolve(state, 0, ())
    p = state.players[0]
    assert len(p.hand) == 2  # kicked → 2 cards kept


def test_consult_describe():
    text = ConsultTheStarChartsEffect().describe()
    assert "kicked" in text
    assert "X" in text


def test_resolving_kicked_reset_after_spell_resolution():
    state = _new_state(lands=4, library_size=5)
    consult = state.new_object(
        EOE_SPELLS["Consult the Star Charts"], 0, Zone.HAND,
    )
    state.players[0].hand.append(consult)
    apply_action(state, 0, CastSpell(consult.id, kicked=True))
    resolve_top_of_stack(state)
    assert state.resolving_kicked is False
