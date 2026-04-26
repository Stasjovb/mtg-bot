"""Tests for Perigee Beckoner pump + Vaultguard Trooper discard-draw."""

from mtg_bot.actions import drain_stack, put_into_battlefield, resolve_top_of_stack
from mtg_bot.agents import Agent, RandomAgent
from mtg_bot.cards import (
    BASIC_LANDS,
    EOE_CREATURES,
    EOE_SPELLS,
    SYNTHETIC_CREATURES,
)
from mtg_bot.effects import DiscardHandThenDrawN
from mtg_bot.game import GameState, Player, Zone, effective_power
from mtg_bot.turn import run_beginning_of_end_step_triggers


class _PickFirstAgent(Agent):
    def choose_target(self, state, player_id, legal_targets):
        return legal_targets[0] if legal_targets else None


def _new_state(agent=None):
    state = GameState()
    state.players.append(Player(id=0, agent=agent or _PickFirstAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    return state


# -----------------------
# DiscardHandThenDrawN
# -----------------------


def test_discard_hand_then_draw_n_flow():
    state = _new_state()
    p = state.players[0]
    # Hand has 3 cards; library has 4 cards.
    for _ in range(3):
        c = state.new_object(BASIC_LANDS["Forest"], 0, Zone.HAND)
        p.hand.append(c)
    for _ in range(4):
        c = state.new_object(BASIC_LANDS["Plains"], 0, Zone.LIBRARY)
        p.library.append(c)
    DiscardHandThenDrawN(amount=2).resolve(state, 0, ())
    assert len(p.hand) == 2
    # Two new cards drawn from library.
    assert all(c.printing.name == "Plains" for c in p.hand)
    assert len(p.library) == 2


def test_discard_hand_then_draw_empty_hand():
    state = _new_state()
    p = state.players[0]
    for _ in range(2):
        c = state.new_object(BASIC_LANDS["Plains"], 0, Zone.LIBRARY)
        p.library.append(c)
    DiscardHandThenDrawN(amount=2).resolve(state, 0, ())
    # Drew 2 cards into empty hand.
    assert len(p.hand) == 2


def test_discard_hand_then_draw_empty_library():
    state = _new_state()
    p = state.players[0]
    c = state.new_object(BASIC_LANDS["Forest"], 0, Zone.HAND)
    p.hand.append(c)
    DiscardHandThenDrawN(amount=2).resolve(state, 0, ())
    assert len(p.hand) == 0
    assert c in p.graveyard


def test_discard_hand_then_draw_describe():
    text = DiscardHandThenDrawN(amount=2).describe()
    assert "2" in text
    assert "discard" in text


# -----------------------
# Vaultguard Trooper
# -----------------------


def test_vaultguard_trooper_fires_when_two_tapped_creatures():
    state = _new_state()
    state.active_player_idx = 0
    p = state.players[0]
    # Two tapped creatures on P0's side.
    vg = state.new_object(
        EOE_CREATURES["Vaultguard Trooper"], 0, Zone.BATTLEFIELD,
    )
    vg.tapped = True
    state.battlefield.append(vg)
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    bear.tapped = True
    state.battlefield.append(bear)
    # Hand: 2 cards. Library: 3 cards.
    for _ in range(2):
        c = state.new_object(BASIC_LANDS["Forest"], 0, Zone.HAND)
        p.hand.append(c)
    for _ in range(3):
        c = state.new_object(BASIC_LANDS["Plains"], 0, Zone.LIBRARY)
        p.library.append(c)
    run_beginning_of_end_step_triggers(state)
    drain_stack(state)
    # Hand discarded (2 cards to graveyard), drew 2 cards.
    assert len(p.hand) == 2
    assert all(c.printing.name == "Plains" for c in p.hand)


def test_vaultguard_trooper_skips_when_fewer_than_two_tapped():
    state = _new_state()
    state.active_player_idx = 0
    p = state.players[0]
    vg = state.new_object(
        EOE_CREATURES["Vaultguard Trooper"], 0, Zone.BATTLEFIELD,
    )
    vg.tapped = True
    state.battlefield.append(vg)
    # Only 1 tapped creature — under the threshold.
    c1 = state.new_object(BASIC_LANDS["Forest"], 0, Zone.HAND)
    p.hand.append(c1)
    drawn = state.new_object(BASIC_LANDS["Plains"], 0, Zone.LIBRARY)
    p.library.append(drawn)
    run_beginning_of_end_step_triggers(state)
    # Hand untouched.
    assert c1 in p.hand


# -----------------------
# Perigee Beckoner
# -----------------------


def test_perigee_beckoner_etb_pumps_target_creature():
    state = _new_state(_PickFirstAgent())
    target = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(target)
    beckoner = state.new_object(
        EOE_CREATURES["Perigee Beckoner"], 0, Zone.HAND,
    )
    state.players[0].hand.append(beckoner)
    put_into_battlefield(state, beckoner, controller_id=0)
    while state.stack:
        resolve_top_of_stack(state)
    # Target gets +2/+0 UEOT.
    assert effective_power(state, target) == 4  # bear 2 + 2


def test_perigee_beckoner_warp_cost_is_one_black():
    """Verify we corrected to the printed warp cost {1}{B}."""
    p = EOE_CREATURES["Perigee Beckoner"]
    assert p.warp_cost_str == "{1}{B}"


# -----------------------
# Vaultguard Trooper "may" decision (choose_yes_no)
# -----------------------


class _NoDiscardAgent(Agent):
    """Declines the optional discard."""

    def choose_yes_no(self, state, player_id, prompt):
        return False


def test_vaultguard_trooper_declined_by_yes_no_agent():
    """When the controller's agent says no to the optional discard,
    the hand stays intact and no cards are drawn."""
    state = _new_state(_NoDiscardAgent())
    state.active_player_idx = 0
    p = state.players[0]
    vg = state.new_object(
        EOE_CREATURES["Vaultguard Trooper"], 0, Zone.BATTLEFIELD,
    )
    vg.tapped = True
    state.battlefield.append(vg)
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    bear.tapped = True
    state.battlefield.append(bear)
    # Hand: 2 cards. Library: 3 cards.
    hand_cards = []
    for _ in range(2):
        c = state.new_object(BASIC_LANDS["Forest"], 0, Zone.HAND)
        p.hand.append(c)
        hand_cards.append(c)
    library_cards = []
    for _ in range(3):
        c = state.new_object(BASIC_LANDS["Plains"], 0, Zone.LIBRARY)
        p.library.append(c)
        library_cards.append(c)
    run_beginning_of_end_step_triggers(state)
    drain_stack(state)
    # Hand untouched, no cards drawn — exactly the cards we put in.
    assert p.hand == hand_cards
    assert p.library == library_cards
    # And nothing landed in the graveyard from this trigger.
    assert all(c not in p.graveyard for c in hand_cards)


def test_vaultguard_trooper_default_agent_says_yes():
    """Default ``Agent.choose_yes_no`` returns True, so an agent that
    doesn't override it preserves the existing "may → always yes"
    behavior — hand discarded, two cards drawn."""
    state = _new_state(_PickFirstAgent())
    state.active_player_idx = 0
    p = state.players[0]
    vg = state.new_object(
        EOE_CREATURES["Vaultguard Trooper"], 0, Zone.BATTLEFIELD,
    )
    vg.tapped = True
    state.battlefield.append(vg)
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    bear.tapped = True
    state.battlefield.append(bear)
    for _ in range(2):
        c = state.new_object(BASIC_LANDS["Forest"], 0, Zone.HAND)
        p.hand.append(c)
    for _ in range(3):
        c = state.new_object(BASIC_LANDS["Plains"], 0, Zone.LIBRARY)
        p.library.append(c)
    run_beginning_of_end_step_triggers(state)
    drain_stack(state)
    # Discarded the 2 Forests, drew 2 Plains.
    assert len(p.hand) == 2
    assert all(c.printing.name == "Plains" for c in p.hand)


def test_discard_hand_then_draw_n_declined():
    """Direct effect-level test — agent declines → hand untouched,
    no draw, no graveyard movement."""
    state = _new_state(_NoDiscardAgent())
    p = state.players[0]
    hand_card = state.new_object(BASIC_LANDS["Forest"], 0, Zone.HAND)
    p.hand.append(hand_card)
    library_card = state.new_object(BASIC_LANDS["Plains"], 0, Zone.LIBRARY)
    p.library.append(library_card)
    DiscardHandThenDrawN(amount=2).resolve(state, 0, ())
    assert p.hand == [hand_card]
    assert p.library == [library_card]
    assert hand_card not in p.graveyard
