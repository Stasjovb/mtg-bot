"""Tests for Sliver Overlord ({W}{U}{B}{R}{G}) — Special Guests creature.

Oracle:
  {3}: Search your library for a Sliver card, reveal that card, put it
       into your hand, then shuffle.
  {3}: Gain control of target Sliver. (This effect lasts indefinitely.)
"""

from mtg_bot.agents import Agent, RandomAgent
from mtg_bot.cards import (
    SPECIAL_GUESTS_EOE, SYNTHETIC_CREATURES, TOKEN_PRINTINGS, make_creature,
)
from mtg_bot.effects import (
    GainControlOfTargetSliverPermanently, SearchLibraryForCard,
)
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.turn import run_cleanup_step


class _PickFirst(Agent):
    def choose_card_from_library(self, state, player_id, option_ids):
        return option_ids[0] if option_ids else None


def _new_state(p0_agent=None, p1_agent=None):
    state = GameState()
    state.players.append(Player(id=0, agent=p0_agent or RandomAgent()))
    state.players.append(Player(id=1, agent=p1_agent or RandomAgent()))
    return state


# A synthetic Sliver printing for library-side tests — the main EoE
# pool has no non-token Slivers to tutor.
_BLADE_SLIVER = make_creature(
    "Blade Sliver", "{2}{R}", 2, 2, subtypes=("Sliver",),
)


def test_sliver_overlord_is_wired_up():
    so = SPECIAL_GUESTS_EOE["Sliver Overlord"]
    assert so.mana_cost_str == "{W}{U}{B}{R}{G}"
    assert "Legendary" in so.supertypes
    assert "Sliver" in so.subtypes and "Mutant" in so.subtypes
    assert so.power == 7 and so.toughness == 7
    assert len(so.activated_abilities) == 2
    # First is tutor, second is gain-control.
    assert isinstance(
        so.activated_abilities[0].effect, SearchLibraryForCard
    )
    assert so.activated_abilities[0].effect.filter_name == "sliver"
    assert isinstance(
        so.activated_abilities[1].effect, GainControlOfTargetSliverPermanently
    )


def test_search_library_sliver_filter_matches_sliver_subtype():
    """The 'sliver' filter added to SearchLibraryForCard matches any
    printing with the Sliver subtype."""
    eff = SearchLibraryForCard(filter_name="sliver")
    assert eff._matches(_BLADE_SLIVER)
    # Non-Sliver creature does not match.
    assert not eff._matches(SYNTHETIC_CREATURES["Wild Bear"])


def test_tutor_fetches_sliver_from_library():
    state = _new_state(p0_agent=_PickFirst())
    p = state.player_by_id(0)
    # Mix one Sliver into an otherwise-non-Sliver library.
    p.library.append(state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.LIBRARY,
    ))
    sliver = state.new_object(_BLADE_SLIVER, 0, Zone.LIBRARY)
    p.library.append(sliver)
    p.library.append(state.new_object(
        SYNTHETIC_CREATURES["Sapling"], 0, Zone.LIBRARY,
    ))

    tutor = SPECIAL_GUESTS_EOE["Sliver Overlord"].activated_abilities[0]
    tutor.effect.resolve(state, 0, ())
    assert sliver in p.hand
    assert sliver not in p.library


def test_tutor_fails_gracefully_when_no_sliver_in_library():
    state = _new_state(p0_agent=_PickFirst())
    p = state.player_by_id(0)
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.LIBRARY,
    )
    p.library.append(bear)

    tutor = SPECIAL_GUESTS_EOE["Sliver Overlord"].activated_abilities[0]
    tutor.effect.resolve(state, 0, ())
    # Library unchanged; hand empty.
    assert bear in p.library
    assert bear not in p.hand


def test_gain_control_takes_target_sliver():
    state = _new_state()
    # P1's Sliver token on the battlefield.
    s = state.new_object(TOKEN_PRINTINGS["Sliver"], 1, Zone.BATTLEFIELD)
    state.battlefield.append(s)
    assert s.controller_id == 1

    eff = GainControlOfTargetSliverPermanently()
    assert eff.legal_targets(state, 0) == [("creature", s.id)]
    eff.resolve(state, 0, (("creature", s.id),))
    assert s.controller_id == 0


def test_gain_control_persists_past_cleanup():
    """Unlike temporary steal effects, this one does NOT revert at
    cleanup."""
    state = _new_state()
    state.active_player_idx = 0
    s = state.new_object(TOKEN_PRINTINGS["Sliver"], 1, Zone.BATTLEFIELD)
    state.battlefield.append(s)

    GainControlOfTargetSliverPermanently().resolve(
        state, 0, (("creature", s.id),)
    )
    run_cleanup_step(state)
    assert s.controller_id == 0, (
        "control should persist (no temp_original_controller_id set)"
    )


def test_gain_control_own_sliver_is_noop():
    state = _new_state()
    s = state.new_object(TOKEN_PRINTINGS["Sliver"], 0, Zone.BATTLEFIELD)
    state.battlefield.append(s)
    GainControlOfTargetSliverPermanently().resolve(
        state, 0, (("creature", s.id),)
    )
    assert s.controller_id == 0
    assert any("no change" in line for line in state.log)


def test_gain_control_legal_targets_exclude_non_slivers():
    state = _new_state()
    sliver = state.new_object(
        TOKEN_PRINTINGS["Sliver"], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(sliver)
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear)

    eff = GainControlOfTargetSliverPermanently()
    legal = eff.legal_targets(state, 0)
    assert ("creature", sliver.id) in legal
    assert ("creature", bear.id) not in legal


def test_gain_control_defensive_paths():
    """Empty targets, wrong kind, non-existent target, target not a
    Sliver: all return silently."""
    state = _new_state()
    eff = GainControlOfTargetSliverPermanently()
    eff.resolve(state, 0, ())
    eff.resolve(state, 0, (("player", 0),))
    eff.resolve(state, 0, (("creature", 999_999),))
    # Target exists but isn't a Sliver.
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear)
    eff.resolve(state, 0, (("creature", bear.id),))
    assert bear.controller_id == 1


def test_gain_control_effect_describe_mentions_sliver():
    assert "Sliver" in GainControlOfTargetSliverPermanently().describe()
