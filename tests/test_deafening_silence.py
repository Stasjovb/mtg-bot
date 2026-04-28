"""Tests for Deafening Silence ({W}) — Special Guests enchantment.

Oracle: Each player can't cast more than one noncreature spell each turn.
"""

from mtg_bot.actions import CastSpell, apply_action
from mtg_bot.agents import RandomAgent
from mtg_bot.cards import BASIC_LANDS, SYNTHETIC_CREATURES
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.legal import legal_actions
from mtg_bot.turn import Step, run_cleanup_step

from mtg_bot.cards.source import get_active_source

_PRINTINGS = get_active_source().get_printings()


def _new_state():
    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    state.active_player_idx = 0
    state.priority_player_idx = 0
    state.step = Step.PRECOMBAT_MAIN
    return state


def _pile_mana(state: GameState, player_id: int, count: int):
    """Put `count` Forests on the battlefield under player_id untapped
    so any one-G cost spell is payable."""
    p = state.player_by_id(player_id)
    for _ in range(count):
        land = state.new_object(
            BASIC_LANDS["Forest"], player_id, Zone.BATTLEFIELD,
        )
        state.battlefield.append(land)


def _pile_white_mana(state: GameState, player_id: int, count: int):
    p = state.player_by_id(player_id)
    for _ in range(count):
        land = state.new_object(
            BASIC_LANDS["Plains"], player_id, Zone.BATTLEFIELD,
        )
        state.battlefield.append(land)


def _put_enchantment(state: GameState, player_id: int):
    obj = state.new_object(
        _PRINTINGS["Deafening Silence"], player_id,
        Zone.BATTLEFIELD,
    )
    state.battlefield.append(obj)
    return obj


def test_deafening_silence_is_wired_up():
    ds = _PRINTINGS["Deafening Silence"]
    assert ds.mana_cost_str == "{W}"
    assert "Enchantment" in ds.card_types
    assert ds.restricts_noncreature_spells_to_one_per_turn is True


def test_noncreature_cast_increments_counter():
    """Casting a non-creature spell bumps the per-turn counter; casting
    a creature does not."""
    state = _new_state()
    p = state.player_by_id(0)

    sorcery = next(card for card in _PRINTINGS.values() if card.is_sorcery)
    c = state.new_object(sorcery, 0, Zone.HAND)
    p.hand.append(c)
    # Put enough mana on board to cover any reasonable sorcery.
    _pile_mana(state, 0, 10)
    _pile_white_mana(state, 0, 10)
    for _ in range(10):
        # Additional UBR mana so we can cover arbitrary pips.
        for color_land in ("Island", "Swamp", "Mountain"):
            state.battlefield.append(state.new_object(
                BASIC_LANDS[color_land], 0, Zone.BATTLEFIELD,
            ))

    before = p.noncreature_spells_cast_this_turn
    apply_action(state, 0, CastSpell(card_id=c.id))
    assert p.noncreature_spells_cast_this_turn == before + 1


def test_creature_cast_does_not_increment_noncreature_counter():
    state = _new_state()
    p = state.player_by_id(0)
    creat = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.HAND,
    )
    p.hand.append(creat)
    _pile_mana(state, 0, 4)

    apply_action(state, 0, CastSpell(card_id=creat.id))
    assert p.noncreature_spells_cast_this_turn == 0


def test_counter_resets_at_cleanup():
    state = _new_state()
    p = state.player_by_id(0)
    p.noncreature_spells_cast_this_turn = 3
    run_cleanup_step(state)
    assert p.noncreature_spells_cast_this_turn == 0


def test_deafening_silence_blocks_second_noncreature_cast():
    """After casting one sorcery, Deafening Silence prevents a second
    noncreature cast in legal_actions."""
    state = _new_state()
    _put_enchantment(state, 0)
    p = state.player_by_id(0)
    # Already cast one noncreature this turn.
    p.noncreature_spells_cast_this_turn = 1
    # Put a sorcery in hand with plenty of mana.
    sorcery = next(card for card in _PRINTINGS.values() if card.is_sorcery)
    sorc_card = state.new_object(sorcery, 0, Zone.HAND)
    p.hand.append(sorc_card)
    _pile_mana(state, 0, 10)
    _pile_white_mana(state, 0, 10)
    for color_land in ("Island", "Swamp", "Mountain"):
        for _ in range(5):
            state.battlefield.append(state.new_object(
                BASIC_LANDS[color_land], 0, Zone.BATTLEFIELD,
            ))

    actions = legal_actions(state, 0)
    # No CastSpell for our sorcery should appear.
    assert not any(
        isinstance(a, CastSpell) and a.card_id == sorc_card.id
        for a in actions
    )


def test_creature_casts_always_allowed():
    """Even with DS in play and the noncreature counter maxed, creatures
    are still castable."""
    state = _new_state()
    _put_enchantment(state, 0)
    p = state.player_by_id(0)
    p.noncreature_spells_cast_this_turn = 5  # already over quota
    creat = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.HAND,
    )
    p.hand.append(creat)
    _pile_mana(state, 0, 4)

    actions = legal_actions(state, 0)
    assert any(
        isinstance(a, CastSpell) and a.card_id == creat.id for a in actions
    )


def test_first_noncreature_cast_is_still_legal():
    """DS only blocks the SECOND noncreature cast each turn, not the
    first one."""
    state = _new_state()
    _put_enchantment(state, 0)
    p = state.player_by_id(0)
    assert p.noncreature_spells_cast_this_turn == 0
    sorcery = next(card for card in _PRINTINGS.values() if card.is_sorcery)
    sorc_card = state.new_object(sorcery, 0, Zone.HAND)
    p.hand.append(sorc_card)
    _pile_mana(state, 0, 10)
    _pile_white_mana(state, 0, 10)
    for color_land in ("Island", "Swamp", "Mountain"):
        for _ in range(5):
            state.battlefield.append(state.new_object(
                BASIC_LANDS[color_land], 0, Zone.BATTLEFIELD,
            ))

    actions = legal_actions(state, 0)
    assert any(
        isinstance(a, CastSpell) and a.card_id == sorc_card.id
        for a in actions
    )


def test_restriction_applies_globally_to_all_players():
    """Oracle says 'each player', not 'you' — DS under an opponent's
    control still restricts you."""
    state = _new_state()
    _put_enchantment(state, 1)  # DS under OPPONENT's control
    p = state.player_by_id(0)
    p.noncreature_spells_cast_this_turn = 1
    sorcery = next(card for card in _PRINTINGS.values() if card.is_sorcery)
    sorc_card = state.new_object(sorcery, 0, Zone.HAND)
    p.hand.append(sorc_card)
    _pile_mana(state, 0, 10)
    _pile_white_mana(state, 0, 10)
    for color_land in ("Island", "Swamp", "Mountain"):
        for _ in range(5):
            state.battlefield.append(state.new_object(
                BASIC_LANDS[color_land], 0, Zone.BATTLEFIELD,
            ))

    actions = legal_actions(state, 0)
    assert not any(
        isinstance(a, CastSpell) and a.card_id == sorc_card.id
        for a in actions
    )


def test_find_card_by_id_handles_library_top_and_missing():
    """Defensive paths in legal._find_card_by_id: look up a card on the
    library top (cast-from-top flows), and return None for an
    unknown id."""
    from mtg_bot.legal import _find_card_by_id

    state = _new_state()
    p = state.player_by_id(0)
    c = state.new_object(
        BASIC_LANDS["Forest"], 0, Zone.LIBRARY,
    )
    p.library.append(c)
    # Library-top hit.
    assert _find_card_by_id(state, 0, c.id) is c
    # Unknown id — None branch.
    assert _find_card_by_id(state, 0, 999_999) is None


def test_no_restriction_without_deafening_silence():
    """Without the enchantment in play, noncreature casts are
    uncapped even if the counter is already high."""
    state = _new_state()
    p = state.player_by_id(0)
    p.noncreature_spells_cast_this_turn = 3  # high, but no DS in play
    sorcery = next(card for card in _PRINTINGS.values() if card.is_sorcery)
    sorc_card = state.new_object(sorcery, 0, Zone.HAND)
    p.hand.append(sorc_card)
    _pile_mana(state, 0, 10)
    _pile_white_mana(state, 0, 10)
    for color_land in ("Island", "Swamp", "Mountain"):
        for _ in range(5):
            state.battlefield.append(state.new_object(
                BASIC_LANDS[color_land], 0, Zone.BATTLEFIELD,
            ))

    actions = legal_actions(state, 0)
    assert any(
        isinstance(a, CastSpell) and a.card_id == sorc_card.id
        for a in actions
    )
