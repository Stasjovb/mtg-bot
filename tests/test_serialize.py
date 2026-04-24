from mtg_bot.cards import BASIC_LANDS, SYNTHETIC_CREATURES
from mtg_bot.game import GameState, ManaCoin, Player, StackItem, Zone
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
    d = serialize_permanent(state, bear)
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
    assert d["keywords"] == []


def test_serialize_permanent_includes_keywords():
    from mtg_bot.cards import make_creature

    state = _fresh_state()
    flier_printing = make_creature("Sky Drake", "{2}{U}", 2, 2, keywords={"flying"})
    flier = state.new_object(flier_printing, owner_id=0, zone=Zone.BATTLEFIELD)
    state.battlefield.append(flier)
    d = serialize_permanent(state, flier)
    assert d["keywords"] == ["flying"]


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


# ------------------------------------------------------------------------
# Tier-1 state fields: mana pool, loyalty, stun, attached_to
# ------------------------------------------------------------------------


def test_serialize_mana_pool_captures_coins():
    state = _fresh_state()
    state.players[0].mana_pool.extend([
        ManaCoin(color="R"),
        ManaCoin(color="G"),
        ManaCoin(color="any", spend_restriction="artifact_spell"),
    ])
    data = serialize_state(state)
    pool = data["players"][0]["mana_pool"]
    assert pool == [
        {"color": "R", "spend_restriction": None},
        {"color": "G", "spend_restriction": None},
        {"color": "any", "spend_restriction": "artifact_spell"},
    ]


def test_serialize_mana_pool_empty_by_default():
    data = serialize_state(_fresh_state())
    assert data["players"][0]["mana_pool"] == []


def test_serialize_permanent_exposes_loyalty_counters():
    state = _fresh_state()
    bear = state.new_object(SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.BATTLEFIELD)
    bear.loyalty_counters = 4
    state.battlefield.append(bear)
    d = serialize_permanent(state, bear)
    assert d["loyalty_counters"] == 4
    # Wild Bear is not a planeswalker (no loyalty on its printing).
    assert d["is_planeswalker"] is False


def test_serialize_permanent_exposes_stun_counters():
    state = _fresh_state()
    bear = state.new_object(SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.BATTLEFIELD)
    bear.stun_counters = 2
    state.battlefield.append(bear)
    d = serialize_permanent(state, bear)
    assert d["stun_counters"] == 2


def test_serialize_permanent_counters_default_to_zero():
    state = _fresh_state()
    bear = state.new_object(SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.BATTLEFIELD)
    state.battlefield.append(bear)
    d = serialize_permanent(state, bear)
    assert d["loyalty_counters"] == 0
    assert d["stun_counters"] == 0
    assert d["attached_to"] is None


def test_serialize_permanent_attached_to_points_to_host():
    state = _fresh_state()
    host = state.new_object(SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.BATTLEFIELD)
    equip = state.new_object(SYNTHETIC_CREATURES["Sapling"], owner_id=0, zone=Zone.BATTLEFIELD)
    equip.attached_to = host.id
    state.battlefield.extend([host, equip])
    d = serialize_permanent(state, equip)
    assert d["attached_to"] == {"id": host.id, "name": "Wild Bear"}


def test_serialize_permanent_attached_to_missing_host_is_none():
    """If the host has already left the battlefield, attached_to resolves to
    None instead of a dangling pointer."""
    state = _fresh_state()
    equip = state.new_object(SYNTHETIC_CREATURES["Sapling"], owner_id=0, zone=Zone.BATTLEFIELD)
    equip.attached_to = 99999  # no such permanent on the battlefield
    state.battlefield.append(equip)
    d = serialize_permanent(state, equip)
    assert d["attached_to"] is None


# ------------------------------------------------------------------------
# Tier-2 state fields: poison, stack x_value/kicked/countered, target refs
# ------------------------------------------------------------------------


def test_serialize_player_poison_counters():
    state = _fresh_state()
    state.players[0].poison_counters = 4
    data = serialize_state(state)
    assert data["players"][0]["poison_counters"] == 4
    assert data["players"][1]["poison_counters"] == 0


def test_serialize_stack_item_includes_mana_cost():
    state = _fresh_state()
    # Wild Bear has cost "{1}{G}" in the synthetic registry.
    spell = state.new_object(SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.STACK)
    state.stack.append(StackItem(source=spell, controller_id=0))
    data = serialize_state(state)
    assert data["stack"][0]["mana_cost"] == "{1}{G}"


def test_serialize_stack_item_x_value_kicked_countered_defaults():
    state = _fresh_state()
    spell = state.new_object(SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.STACK)
    state.stack.append(StackItem(source=spell, controller_id=0))
    data = serialize_state(state)
    item = data["stack"][0]
    assert item["x_value"] == 0
    assert item["kicked"] is False
    assert item["countered"] is False


def test_serialize_stack_item_exposes_x_kicked_countered_when_set():
    state = _fresh_state()
    spell = state.new_object(SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.STACK)
    state.stack.append(StackItem(
        source=spell, controller_id=0,
        x_value=3, kicked=True, countered=True,
    ))
    data = serialize_state(state)
    item = data["stack"][0]
    assert item["x_value"] == 3
    assert item["kicked"] is True
    assert item["countered"] is True


def test_serialize_stack_targets_resolve_to_names():
    state = _fresh_state()
    bear = state.new_object(SYNTHETIC_CREATURES["Wild Bear"], owner_id=1, zone=Zone.BATTLEFIELD)
    state.battlefield.append(bear)
    spell = state.new_object(SYNTHETIC_CREATURES["Sapling"], owner_id=0, zone=Zone.STACK)
    state.stack.append(StackItem(
        source=spell, controller_id=0,
        targets=(("creature", bear.id), ("player", 1)),
    ))
    data = serialize_state(state)
    targets = data["stack"][0]["targets"]
    assert targets[0] == {"kind": "creature", "id": bear.id, "name": "Wild Bear"}
    assert targets[1] == {"kind": "player", "id": 1, "name": "Player 1"}


def test_serialize_stack_targets_resolve_stack_items():
    """A counter-spell style target: point at another stack item."""
    state = _fresh_state()
    victim_src = state.new_object(SYNTHETIC_CREATURES["Wild Bear"], owner_id=1, zone=Zone.STACK)
    state.stack.append(StackItem(source=victim_src, controller_id=1))
    counter_src = state.new_object(SYNTHETIC_CREATURES["Sapling"], owner_id=0, zone=Zone.STACK)
    state.stack.append(StackItem(
        source=counter_src, controller_id=0,
        targets=(("spell", victim_src.id),),
    ))
    data = serialize_state(state)
    counter_item = data["stack"][1]
    assert counter_item["targets"][0] == {
        "kind": "spell", "id": victim_src.id, "name": "Wild Bear",
    }


def test_serialize_permanent_blocked_by_is_list_of_ids():
    state = _fresh_state()
    attacker = state.new_object(SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.BATTLEFIELD)
    b1 = state.new_object(SYNTHETIC_CREATURES["Sapling"], owner_id=1, zone=Zone.BATTLEFIELD)
    b2 = state.new_object(SYNTHETIC_CREATURES["Sapling"], owner_id=1, zone=Zone.BATTLEFIELD)
    attacker.attacking = True
    attacker.blocked_by = [b1.id, b2.id]
    state.battlefield.extend([attacker, b1, b2])
    d = serialize_permanent(state, attacker)
    assert d["blocked_by"] == [b1.id, b2.id]


def test_serialize_permanent_blocked_by_defaults_empty():
    state = _fresh_state()
    bear = state.new_object(SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.BATTLEFIELD)
    state.battlefield.append(bear)
    d = serialize_permanent(state, bear)
    assert d["blocked_by"] == []


def test_serialize_permanent_attacking_defender_points_at_next_opponent():
    state = _fresh_state()
    attacker = state.new_object(SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.BATTLEFIELD)
    attacker.attacking = True
    state.battlefield.append(attacker)
    d = serialize_permanent(state, attacker)
    assert d["attacking_defender"] == {"kind": "player", "id": 1, "name": "Player 1"}


def test_serialize_permanent_attacking_defender_is_none_if_not_attacking():
    state = _fresh_state()
    bear = state.new_object(SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.BATTLEFIELD)
    state.battlefield.append(bear)
    d = serialize_permanent(state, bear)
    assert d["attacking_defender"] is None


def test_serialize_permanent_attacking_defender_skips_dead_opponent():
    """If the next player in turn order has already lost, the attack routes
    to the next alive one."""
    state = _fresh_state()
    # 3 players; player 1 is dead, so P0 attacks should point at P2.
    state.players.append(Player(id=2))
    state.players[1].has_lost = True
    attacker = state.new_object(SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.BATTLEFIELD)
    attacker.attacking = True
    state.battlefield.append(attacker)
    d = serialize_permanent(state, attacker)
    assert d["attacking_defender"] == {"kind": "player", "id": 2, "name": "Player 2"}


def test_serialize_stack_targets_unknown_id_is_nameless():
    state = _fresh_state()
    spell = state.new_object(SYNTHETIC_CREATURES["Sapling"], owner_id=0, zone=Zone.STACK)
    state.stack.append(StackItem(
        source=spell, controller_id=0,
        targets=(("creature", 99999),),
    ))
    data = serialize_state(state)
    assert data["stack"][0]["targets"][0] == {
        "kind": "creature", "id": 99999, "name": None,
    }
