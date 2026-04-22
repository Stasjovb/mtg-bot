from mtg_bot.cards import BASIC_LANDS, SYNTHETIC_CREATURES
from mtg_bot.game import GameState, Player, StackItem, Zone
from mtg_bot.serialize import serialize_hand_card, serialize_permanent, serialize_state
from mtg_bot.simulate import simulate_game
from mtg_bot.turn import Step


def _fresh_state():
    state = GameState()
    state.players.append(Player(id=0))
    state.players.append(Player(id=1))
    return state


def test_serialize_permanent_captures_state():
    state = _fresh_state()
    bear = state.new_object(SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.BATTLEFIELD)
    bear.tapped = True
    bear.damage = 1
    bear.attacking = True
    state.battlefield.append(bear)
    d = serialize_permanent(bear)
    assert d["name"] == "Wild Bear"
    assert d["is_creature"] is True
    assert d["is_land"] is False
    assert d["tapped"] is True
    assert d["damage"] == 1
    assert d["attacking"] is True
    assert d["power"] == 2
    assert d["toughness"] == 2


def test_serialize_hand_card_has_basic_fields():
    state = _fresh_state()
    land = state.new_object(BASIC_LANDS["Forest"], owner_id=0, zone=Zone.HAND)
    d = serialize_hand_card(land)
    assert d["name"] == "Forest"
    assert d["type_line"] == "Basic Land — Forest"
    assert d["power"] is None
    assert d["toughness"] is None


def test_serialize_state_contains_players_and_stack():
    state = _fresh_state()
    state.step = Step.PRECOMBAT_MAIN
    bear = state.new_object(SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.HAND)
    state.players[0].hand.append(bear)
    # Put something on the stack
    spell = state.new_object(SYNTHETIC_CREATURES["Sapling"], owner_id=1, zone=Zone.STACK)
    state.stack.append(StackItem(source=spell, controller_id=1))

    data = serialize_state(state)

    assert data["turn_number"] == 1
    assert data["step"] == "precombat_main"
    assert len(data["players"]) == 2
    p0 = data["players"][0]
    assert p0["life"] == 20
    assert p0["hand_size"] == 1
    assert p0["hand"][0]["name"] == "Wild Bear"
    assert data["stack"][0]["name"] == "Sapling"
    assert data["is_over"] is False


def test_serialize_state_can_hide_hands():
    state = _fresh_state()
    state.step = Step.PRECOMBAT_MAIN
    bear = state.new_object(SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.HAND)
    state.players[0].hand.append(bear)
    data = serialize_state(state, reveal_hands=False)
    assert data["players"][0]["hand_size"] == 1
    assert data["players"][0]["hand"] == []


def test_serialize_state_with_step_none():
    state = _fresh_state()
    assert state.step is None
    data = serialize_state(state)
    assert data["step"] is None


def test_serialize_completed_game_has_winner():
    state = simulate_game(seed=0, max_turns=300)
    data = serialize_state(state)
    assert data["is_over"] is True
    assert (data["winner_id"] is not None) or data["is_draw"]
    # Log should have at least one event
    assert len(data["log"]) > 0
