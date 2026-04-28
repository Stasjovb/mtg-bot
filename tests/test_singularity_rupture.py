"""Tests for Singularity Rupture: wrath + multi-target mill-half."""

from mtg_bot.agents import RandomAgent
from mtg_bot.cards import BASIC_LANDS, SYNTHETIC_CREATURES
from mtg_bot.effects import SingularityRuptureEffect
from mtg_bot.game import GameState, Player, Zone

from mtg_bot.cards.source import get_active_source

_PRINTINGS = get_active_source().get_printings()


def _new_state_with_libraries():
    state = GameState()
    p0 = Player(id=0, agent=RandomAgent())
    p1 = Player(id=1, agent=RandomAgent())
    state.players.append(p0)
    state.players.append(p1)
    for _ in range(10):
        c = state.new_object(BASIC_LANDS["Plains"], 0, Zone.LIBRARY)
        p0.library.append(c)
    for _ in range(7):
        c = state.new_object(BASIC_LANDS["Plains"], 1, Zone.LIBRARY)
        p1.library.append(c)
    return state


def test_singularity_rupture_destroys_all_creatures():
    state = _new_state_with_libraries()
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear)
    opp_bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(opp_bear)
    SingularityRuptureEffect().resolve(state, 0, ())
    assert bear not in state.battlefield
    assert opp_bear not in state.battlefield


def test_singularity_rupture_single_target_mills_half():
    state = _new_state_with_libraries()
    # Target only P1 (library 7 → mill 3, remainder 4).
    SingularityRuptureEffect().resolve(state, 0, (("player", 1),))
    p1 = state.players[1]
    assert len(p1.library) == 4
    assert len(p1.graveyard) == 3


def test_singularity_rupture_multi_target_each_mills_half():
    state = _new_state_with_libraries()
    SingularityRuptureEffect().resolve(
        state, 0, (("player", 0), ("player", 1)),
    )
    p0 = state.players[0]
    p1 = state.players[1]
    # P0: 10 → mill 5, leaving 5.
    assert len(p0.library) == 5
    # P1: 7 → mill 3, leaving 4.
    assert len(p1.library) == 4


def test_singularity_rupture_no_target_no_mill():
    state = _new_state_with_libraries()
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear)
    SingularityRuptureEffect().resolve(state, 0, ())
    # Bear destroyed, but no player milled.
    assert bear not in state.battlefield
    p0 = state.players[0]
    p1 = state.players[1]
    assert len(p0.library) == 10
    assert len(p1.library) == 7


def test_singularity_rupture_odd_library_rounds_down():
    state = _new_state_with_libraries()
    # P1 library is 7 cards → floor(7/2) = 3 milled.
    SingularityRuptureEffect().resolve(state, 0, (("player", 1),))
    assert len(state.players[1].graveyard) == 3


def test_singularity_rupture_zero_library_no_crash():
    state = _new_state_with_libraries()
    state.players[1].library.clear()
    SingularityRuptureEffect().resolve(state, 0, (("player", 1),))
    assert state.players[1].library == []


def test_singularity_rupture_skips_non_player_kind():
    state = _new_state_with_libraries()
    SingularityRuptureEffect().resolve(
        state, 0, (("creature", 999),),  # wrong kind
    )
    # No mill happens.
    assert len(state.players[0].library) == 10


def test_singularity_rupture_skips_lost_player():
    state = _new_state_with_libraries()
    state.players[1].has_lost = True
    SingularityRuptureEffect().resolve(state, 0, (("player", 1),))
    # Lost player isn't milled.
    assert len(state.players[1].graveyard) == 0


def test_singularity_rupture_skips_unknown_player_id():
    state = _new_state_with_libraries()
    # Should not crash.
    SingularityRuptureEffect().resolve(state, 0, (("player", 999),))


def test_singularity_rupture_target_count_range():
    effect = SingularityRuptureEffect()
    min_t, max_t = effect.target_count_range()
    assert min_t == 0
    assert max_t >= 2


def test_singularity_rupture_legal_targets_includes_all_living_players():
    state = _new_state_with_libraries()
    legal = SingularityRuptureEffect().legal_targets(state, 0)
    player_ids = {t[1] for t in legal}
    assert player_ids == {0, 1}


def test_singularity_rupture_describe():
    text = SingularityRuptureEffect().describe()
    assert "destroy all creatures" in text
    assert "mill" in text


def test_singularity_rupture_card_printing():
    s = _PRINTINGS["Singularity Rupture"]
    assert isinstance(s.spell_effect, SingularityRuptureEffect)
