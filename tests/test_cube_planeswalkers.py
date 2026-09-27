"""Engine + parse tests for the cube planeswalker bucket.

Covers The Wandering Emperor, Elspeth Storm Slayer, Jace Wielder of
Mysteries, Narset Parter of Veils, Teferi Time Raveler and Minsc & Boo,
plus the no-partial-claim rule for planeswalkers whose loyalty bodies the
grammar can't parse, and CR 120.3c damage to planeswalkers.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from mtg_bot.actions import (
    ActivateAbility,
    CastSpell,
    _activate_ability,
    put_into_battlefield,
    resolve_top_of_stack,
)
from mtg_bot.agents import RandomAgent
from mtg_bot.cards import BASIC_LANDS
from mtg_bot.cards.base import make_creature, make_instant, make_sorcery
from mtg_bot.cards.parser_source import OracleParserCardSource
from mtg_bot.effects.generic import DealDamageAnyTarget, DrawCards
from mtg_bot.game import GameState, Player, Zone, effective_keywords
from mtg_bot.legal import legal_actions
from mtg_bot.turn import (
    Step,
    draw_card,
    draw_n_cards,
    run_cleanup_step,
    run_untap_step,
    state_based_actions,
    win_the_game,
)

_SOURCE = OracleParserCardSource(pool="cube")
_P = _SOURCE.get_printings()

_BUCKET = (
    "The Wandering Emperor",
    "Elspeth, Storm Slayer",
    "Jace, Wielder of Mysteries",
    "Narset, Parter of Veils",
    "Teferi, Time Raveler",
    "Minsc & Boo, Timeless Heroes",
)


@dataclass
class _Agent(RandomAgent):
    """Deterministic agent: fixed yes/no, first-or-scripted picks."""

    yes: bool = True
    target_pick: object = "first"
    library_pick: object = None
    sac_pick: object = None
    rng_seed: int = 0
    picks_seen: list = field(default_factory=list)

    def choose_yes_no(self, state, player_id, prompt):
        return self.yes

    def choose_target(self, state, player_id, legal_targets):
        self.picks_seen.append(list(legal_targets))
        if self.target_pick == "first":
            return legal_targets[0] if legal_targets else None
        if self.target_pick is None:
            return None
        return self.target_pick

    def choose_card_from_library(self, state, player_id, option_ids):
        if self.library_pick in option_ids:
            return self.library_pick
        return option_ids[0] if option_ids else None

    def choose_sacrifice(self, state, player_id, legal_object_ids):
        if self.sac_pick in legal_object_ids:
            return self.sac_pick
        return legal_object_ids[0]


def _state(active: int = 0) -> GameState:
    s = GameState()
    s.players.append(Player(id=0, agent=_Agent()))
    s.players.append(Player(id=1, agent=_Agent()))
    s.active_player_idx = active
    s.priority_player_idx = active
    s.step = Step.PRECOMBAT_MAIN
    return s


def _put(state, printing, pid):
    obj = state.new_object(printing, pid, Zone.HAND)
    put_into_battlefield(state, obj, controller_id=pid)
    return obj


def _creature(name="Bear", power=2, toughness=2, cost="{1}{G}", **kw):
    return make_creature(name, cost, power, toughness, **kw)


def _library(state, pid, n, printing=None):
    printing = printing or BASIC_LANDS["Forest"]
    p = state.player_by_id(pid)
    for _ in range(n):
        c = state.new_object(printing, pid, Zone.LIBRARY)
        p.library.append(c)
    return p.library


def _ability_index(walker, printed: int) -> int:
    """Index of the loyalty ability printed as ``printed`` (+1 -> 1,
    -3 -> -3)."""
    signed = -printed
    for i, a in enumerate(walker.printing.activated_abilities):
        if a.cost.loyalty == signed:
            return i
    raise AssertionError(f"no {printed} ability on {walker.printing.name}")


def _activate(state, pid, walker, printed: int, *, resolve=True):
    _activate_ability(state, pid, walker.id, _ability_index(walker, printed))
    if resolve:
        resolve_top_of_stack(state)
        state_based_actions(state)


# ---------------------------------------------------------------------------
# Claim / parse shape
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", _BUCKET)
def test_bucket_planeswalker_is_claimed(name):
    assert name in _SOURCE.claimed_names
    p = _P[name]
    assert p.is_planeswalker
    assert all(a.sorcery_speed for a in p.activated_abilities)


@pytest.mark.parametrize("name", [
    "Wrenn and Six",
    "Oko, Thief of Crowns",
    "Chandra, Torch of Defiance",
])
def test_unparseable_loyalty_body_leaves_walker_unclaimed(name):
    """No partial claims: a walker whose loyalty bodies the grammar can't
    parse is not shipped with its abilities stripped."""
    assert name not in _SOURCE.claimed_names


def test_tezzeret_still_claims_all_three_abilities():
    p = _P["Tezzeret, Cruel Captain"]
    assert sorted(a.cost.loyalty for a in p.activated_abilities) == [0, 3, 7]


def test_wandering_emperor_shape():
    p = _P["The Wandering Emperor"]
    assert p.type_line == "Legendary Planeswalker"
    assert p.subtypes == ()
    assert "flash" in p.keywords
    assert p.loyalty_abilities_at_instant_speed_if_entered_this_turn
    assert sorted(a.cost.loyalty for a in p.activated_abilities) == [-1, 1, 2]


# ---------------------------------------------------------------------------
# Jace, Wielder of Mysteries
# ---------------------------------------------------------------------------


def test_jace_static_wins_instead_of_drawing_from_empty_library():
    s = _state()
    _put(s, _P["Jace, Wielder of Mysteries"], 0)
    draw_card(s, 0)
    assert s.winner_id == 0
    assert s.player_by_id(1).has_lost
    assert not s.player_by_id(0).has_lost


def test_empty_library_draw_still_loses_without_jace():
    s = _state()
    _put(s, _P["Jace, Wielder of Mysteries"], 1)  # opponent's Jace
    draw_card(s, 0)
    assert s.player_by_id(0).has_lost
    state_based_actions(s)
    assert s.winner_id == 1


def test_jace_plus_one_mills_target_player_then_draws():
    s = _state()
    jace = _put(s, _P["Jace, Wielder of Mysteries"], 0)
    _library(s, 0, 5)
    _library(s, 1, 5)
    s.player_by_id(0).agent.target_pick = ("player", 1)
    _activate(s, 0, jace, +1)
    assert len(s.player_by_id(1).graveyard) == 2
    assert len(s.player_by_id(0).hand) == 1
    assert jace.loyalty_counters == 5


def test_jace_minus_eight_wins_when_library_ends_empty():
    s = _state()
    jace = _put(s, _P["Jace, Wielder of Mysteries"], 0)
    jace.loyalty_counters = 9
    _library(s, 0, 7)
    _activate(s, 0, jace, -8)
    assert len(s.player_by_id(0).hand) == 7
    assert s.winner_id == 0


def test_jace_minus_eight_no_win_with_cards_left():
    s = _state()
    jace = _put(s, _P["Jace, Wielder of Mysteries"], 0)
    jace.loyalty_counters = 9
    _library(s, 0, 10)
    _activate(s, 0, jace, -8)
    assert s.winner_id is None
    assert len(s.player_by_id(0).library) == 3


def test_jace_minus_eight_win_beats_pending_empty_library_loss():
    """Jace dies to his own -8 (SBA before resolution), so the static is
    gone: the short draw records the empty-library loss, but the win in
    the same resolution comes first (CR 704.5b is an SBA)."""
    s = _state()
    jace = _put(s, _P["Jace, Wielder of Mysteries"], 0)
    jace.loyalty_counters = 8
    _library(s, 0, 3)
    _activate(s, 0, jace, -8, resolve=False)
    state_based_actions(s)  # Jace at 0 loyalty -> graveyard
    assert jace not in s.battlefield
    resolve_top_of_stack(s)
    state_based_actions(s)
    assert s.winner_id == 0
    assert not s.player_by_id(0).has_lost


def test_win_the_game_is_noop_once_game_over():
    s = _state()
    s.winner_id = 1
    win_the_game(s, 0, reason="late")
    assert s.winner_id == 1


def test_win_the_game_noop_for_player_who_lost_otherwise():
    s = _state()
    s.player_by_id(0).has_lost = True
    s.player_by_id(0).lost_reason = "life total <= 0"
    win_the_game(s, 0, reason="x")
    assert s.winner_id is None


# ---------------------------------------------------------------------------
# Narset, Parter of Veils
# ---------------------------------------------------------------------------


def test_narset_caps_opponent_draws_at_one_per_turn():
    s = _state()
    _put(s, _P["Narset, Parter of Veils"], 0)
    _library(s, 1, 5)
    _library(s, 0, 5)
    draw_n_cards(s, 1, 3)
    assert len(s.player_by_id(1).hand) == 1
    # Narset's controller is unaffected.
    draw_n_cards(s, 0, 3)
    assert len(s.player_by_id(0).hand) == 3


def test_narset_cap_resets_each_turn_and_blocks_empty_library_loss():
    s = _state()
    _put(s, _P["Narset, Parter of Veils"], 0)
    _library(s, 1, 1)
    draw_card(s, 1)
    # Second draw can't happen, so it isn't a draw from an empty library.
    draw_card(s, 1)
    assert not s.player_by_id(1).has_lost
    run_cleanup_step(s)
    assert s.player_by_id(1).cards_drawn_this_turn == 0
    draw_card(s, 1)
    assert s.player_by_id(1).has_lost


def _narset_library(s):
    lib = s.player_by_id(0).library
    bolt = s.new_object(make_instant("Zap", "{R}", DrawCards(amount=1)), 0, Zone.LIBRARY)
    bear = s.new_object(_creature(), 0, Zone.LIBRARY)
    land = s.new_object(BASIC_LANDS["Island"], 0, Zone.LIBRARY)
    rite = s.new_object(make_sorcery("Rite", "{1}", DrawCards(amount=1)), 0, Zone.LIBRARY)
    deep = s.new_object(BASIC_LANDS["Swamp"], 0, Zone.LIBRARY)
    lib.extend([bear, bolt, land, rite, deep])
    return bear, bolt, land, rite, deep


def test_narset_minus_two_takes_noncreature_nonland_rest_bottom():
    s = _state()
    narset = _put(s, _P["Narset, Parter of Veils"], 0)
    bear, bolt, land, rite, deep = _narset_library(s)
    s.player_by_id(0).agent.library_pick = rite.id
    _activate(s, 0, narset, -2)
    p = s.player_by_id(0)
    assert p.hand == [rite]
    assert p.library[0] is deep
    assert set(map(id, p.library[1:])) == {id(bear), id(bolt), id(land)}
    assert narset.loyalty_counters == 3


def test_narset_minus_two_offers_only_matching_cards():
    s = _state()
    narset = _put(s, _P["Narset, Parter of Veils"], 0)
    bear, bolt, land, rite, deep = _narset_library(s)
    s.player_by_id(0).agent.library_pick = bear.id  # not offered
    _activate(s, 0, narset, -2)
    assert s.player_by_id(0).hand == [bolt]


def test_narset_minus_two_may_decline():
    s = _state()
    narset = _put(s, _P["Narset, Parter of Veils"], 0)
    _narset_library(s)
    s.player_by_id(0).agent.yes = False
    _activate(s, 0, narset, -2)
    assert s.player_by_id(0).hand == []
    assert len(s.player_by_id(0).library) == 5


# ---------------------------------------------------------------------------
# Teferi, Time Raveler
# ---------------------------------------------------------------------------


def _opp_priority(s):
    """P0's main phase, stack non-empty-free, P1 holds priority."""
    s.priority_player_idx = 1


def test_teferi_static_stops_opponent_instants_off_sorcery_timing():
    s = _state()
    _put(s, _P["Teferi, Time Raveler"], 0)
    _put(s, BASIC_LANDS["Mountain"], 1)
    zap = s.new_object(make_instant("Zap", "{R}", DrawCards(amount=1)), 1, Zone.HAND)
    s.player_by_id(1).hand.append(zap)
    _opp_priority(s)
    assert not any(isinstance(a, CastSpell) for a in legal_actions(s, 1))


def test_opponent_instants_castable_without_teferi():
    s = _state()
    _put(s, BASIC_LANDS["Mountain"], 1)
    zap = s.new_object(make_instant("Zap", "{R}", DrawCards(amount=1)), 1, Zone.HAND)
    s.player_by_id(1).hand.append(zap)
    _opp_priority(s)
    assert CastSpell(zap.id) in legal_actions(s, 1)


def test_teferi_controller_keeps_instant_speed():
    s = _state(active=1)
    _put(s, _P["Teferi, Time Raveler"], 0)
    _put(s, BASIC_LANDS["Mountain"], 0)
    zap = s.new_object(make_instant("Zap", "{R}", DrawCards(amount=1)), 0, Zone.HAND)
    s.player_by_id(0).hand.append(zap)
    s.priority_player_idx = 0
    assert CastSpell(zap.id) in legal_actions(s, 0)


def test_teferi_plus_one_lets_sorceries_be_cast_at_instant_speed():
    s = _state()
    teferi = _put(s, _P["Teferi, Time Raveler"], 0)
    _put(s, BASIC_LANDS["Mountain"], 0)
    rite = s.new_object(make_sorcery("Rite", "{R}", DrawCards(amount=1)), 0, Zone.HAND)
    s.player_by_id(0).hand.append(rite)
    _activate(s, 0, teferi, +1)
    # Opponent's turn: P0 holds priority off sorcery timing.
    s.active_player_idx = 1
    s.priority_player_idx = 0
    s.step = Step.END
    acts = legal_actions(s, 0)
    assert acts.count(CastSpell(rite.id)) == 1
    # Sorcery timing: offered once (no duplicate from both blocks).
    s.active_player_idx = 0
    s.step = Step.PRECOMBAT_MAIN
    assert legal_actions(s, 0).count(CastSpell(rite.id)) == 1
    # Expires at the controller's next untap step.
    run_untap_step(s)
    s.active_player_idx = 1
    s.step = Step.END
    assert CastSpell(rite.id) not in legal_actions(s, 0)


def test_teferi_minus_three_bounces_and_draws():
    s = _state()
    teferi = _put(s, _P["Teferi, Time Raveler"], 0)
    bear = _put(s, _creature(), 1)
    land = _put(s, BASIC_LANDS["Forest"], 1)
    _library(s, 0, 2)
    _activate(s, 0, teferi, -3)
    agent = s.player_by_id(0).agent
    offered = agent.picks_seen[-1]
    assert ("creature", bear.id) in offered
    assert not any(t[1] == land.id for t in offered)
    assert bear in s.player_by_id(1).hand
    assert len(s.player_by_id(0).hand) == 1


def test_teferi_minus_three_up_to_one_may_choose_no_target():
    s = _state()
    teferi = _put(s, _P["Teferi, Time Raveler"], 0)
    bear = _put(s, _creature(), 1)
    _library(s, 0, 2)
    s.player_by_id(0).agent.target_pick = None
    _activate(s, 0, teferi, -3)
    assert bear in s.battlefield
    assert len(s.player_by_id(0).hand) == 1


# ---------------------------------------------------------------------------
# The Wandering Emperor
# ---------------------------------------------------------------------------


def test_emperor_has_flash():
    s = _state(active=1)
    for _ in range(4):
        _put(s, BASIC_LANDS["Plains"], 0)
    emp = s.new_object(_P["The Wandering Emperor"], 0, Zone.HAND)
    s.player_by_id(0).hand.append(emp)
    s.priority_player_idx = 0
    s.step = Step.DECLARE_ATTACKERS
    assert CastSpell(emp.id) in legal_actions(s, 0)


def test_emperor_loyalty_at_instant_speed_only_the_turn_she_entered():
    s = _state(active=1)
    s.step = Step.DECLARE_BLOCKERS
    s.priority_player_idx = 0
    emp = _put(s, _P["The Wandering Emperor"], 0)
    attacker = _put(s, _creature(), 1)
    attacker.tapped = True
    acts = [a for a in legal_actions(s, 0) if isinstance(a, ActivateAbility)]
    assert {a.ability_index for a in acts} == {0, 1, 2}
    # Once per turn still applies.
    _activate(s, 0, emp, -1)
    assert not [
        a for a in legal_actions(s, 0) if isinstance(a, ActivateAbility)
    ]
    # Next turn she no longer entered this turn: sorcery timing only.
    s.turn_number += 1
    s.loyalty_activated_this_turn.clear()
    assert not [
        a for a in legal_actions(s, 0) if isinstance(a, ActivateAbility)
    ]


def test_emperor_instant_speed_respects_loyalty_and_targets():
    s = _state(active=1)
    s.step = Step.END
    s.priority_player_idx = 0
    emp = _put(s, _P["The Wandering Emperor"], 0)
    emp.loyalty_counters = 1
    acts = {
        a.ability_index for a in legal_actions(s, 0)
        if isinstance(a, ActivateAbility)
    }
    # -2 unaffordable; +1 (up to one target) and -1 offered.
    assert acts == {_ability_index(emp, +1), _ability_index(emp, -1)}
    emp.loyalty_counters = 3
    acts = {
        a.ability_index for a in legal_actions(s, 0)
        if isinstance(a, ActivateAbility)
    }
    # -2 needs a tapped creature to target.
    assert _ability_index(emp, -2) not in acts


def test_emperor_plus_one_counter_and_first_strike():
    s = _state()
    emp = _put(s, _P["The Wandering Emperor"], 0)
    bear = _put(s, _creature(), 0)
    _activate(s, 0, emp, +1)
    assert bear.plus_one_counters == 1
    assert "first strike" in effective_keywords(s, bear)
    run_cleanup_step(s)
    assert "first strike" not in effective_keywords(s, bear)
    assert bear.plus_one_counters == 1
    assert emp.loyalty_counters == 4


def test_emperor_plus_one_fizzles_on_illegal_target():
    s = _state()
    emp = _put(s, _P["The Wandering Emperor"], 0)
    bear = _put(s, _creature(), 0)
    _activate(s, 0, emp, +1, resolve=False)
    s.battlefield.remove(bear)
    resolve_top_of_stack(s)
    assert bear.plus_one_counters == 0


def test_emperor_minus_one_samurai_token():
    s = _state()
    emp = _put(s, _P["The Wandering Emperor"], 0)
    _activate(s, 0, emp, -1)
    tokens = [o for o in s.battlefield if o.printing.name == "Samurai"]
    assert len(tokens) == 1
    tok = tokens[0]
    assert (tok.printing.power, tok.printing.toughness) == (2, 2)
    assert "vigilance" in tok.printing.keywords
    assert "Token" in tok.printing.supertypes


def test_emperor_minus_two_exiles_tapped_creature_and_gains_life():
    s = _state()
    emp = _put(s, _P["The Wandering Emperor"], 0)
    untapped = _put(s, _creature("Untapped"), 1)
    tapped = _put(s, _creature("Tapped"), 1)
    tapped.tapped = True
    _activate(s, 0, emp, -2)
    offered = s.player_by_id(0).agent.picks_seen[-1]
    assert offered == [("creature", tapped.id)]
    assert tapped in s.player_by_id(1).exile
    assert untapped in s.battlefield
    assert s.player_by_id(0).life == 22


# ---------------------------------------------------------------------------
# Elspeth, Storm Slayer
# ---------------------------------------------------------------------------


def test_elspeth_plus_one_soldier_is_doubled_by_her_static():
    s = _state()
    elspeth = _put(s, _P["Elspeth, Storm Slayer"], 0)
    _activate(s, 0, elspeth, +1)
    soldiers = [o for o in s.battlefield if o.printing.name == "Soldier"]
    assert len(soldiers) == 2
    assert all(o.controller_id == 0 for o in soldiers)


def test_elspeth_zero_counters_and_flying_until_your_next_turn():
    s = _state()
    elspeth = _put(s, _P["Elspeth, Storm Slayer"], 0)
    mine = _put(s, _creature(), 0)
    theirs = _put(s, _creature("Theirs"), 1)
    _activate(s, 0, elspeth, 0)
    assert mine.plus_one_counters == 1
    assert theirs.plus_one_counters == 0
    assert "flying" in effective_keywords(s, mine)
    run_cleanup_step(s)  # end of Elspeth's turn: still flying
    s.active_player_idx = 1
    run_untap_step(s)  # opponent's untap: still flying
    assert "flying" in effective_keywords(s, mine)
    s.active_player_idx = 0
    run_untap_step(s)  # controller's next turn: expires
    assert "flying" not in effective_keywords(s, mine)


def test_elspeth_minus_three_targets_opponent_mv_three_or_more():
    s = _state()
    elspeth = _put(s, _P["Elspeth, Storm Slayer"], 0)
    small = _put(s, _creature("Small", cost="{1}{G}"), 1)
    big = _put(s, _creature("Big", cost="{2}{G}"), 1)
    mine = _put(s, _creature("Mine", cost="{3}{W}"), 0)
    _activate(s, 0, elspeth, -3)
    offered = s.player_by_id(0).agent.picks_seen[-1]
    assert offered == [("creature", big.id)]
    assert big not in s.battlefield
    assert small in s.battlefield and mine in s.battlefield


# ---------------------------------------------------------------------------
# Minsc & Boo, Timeless Heroes
# ---------------------------------------------------------------------------


def _drain(s):
    while s.stack:
        resolve_top_of_stack(s)
        state_based_actions(s)


def test_minsc_etb_may_create_boo():
    s = _state()
    _put(s, _P["Minsc & Boo, Timeless Heroes"], 0)
    _drain(s)
    boo = [o for o in s.battlefield if o.printing.name == "Boo"]
    assert len(boo) == 1
    pr = boo[0].printing
    assert "Legendary" in pr.supertypes and "Hamster" in pr.subtypes
    assert {"trample", "haste"} <= pr.keywords
    assert (pr.power, pr.toughness) == (1, 1)


def test_minsc_etb_may_decline():
    s = _state()
    s.player_by_id(0).agent.yes = False
    _put(s, _P["Minsc & Boo, Timeless Heroes"], 0)
    _drain(s)
    assert not [o for o in s.battlefield if o.printing.name == "Boo"]


def test_minsc_upkeep_trigger_is_yours_only():
    from mtg_bot.effects.predicates import Event
    p = _P["Minsc & Boo, Timeless Heroes"]
    events = sorted(t.event.value for t in p.triggered_abilities)
    assert events == sorted([
        Event.ENTERS.value, Event.BEGINNING_OF_UPKEEP.value,
    ])
    from mtg_bot.turn import run_beginning_of_upkeep_triggers
    s = _state(active=1)
    minsc = s.new_object(p, 0, Zone.BATTLEFIELD)
    minsc.loyalty_counters = 3
    s.battlefield.append(minsc)
    s.step = Step.UPKEEP
    run_beginning_of_upkeep_triggers(s)
    assert not s.stack
    s.active_player_idx = 0
    run_beginning_of_upkeep_triggers(s)
    _drain(s)
    assert [o for o in s.battlefield if o.printing.name == "Boo"]


def test_minsc_plus_one_targets_trample_or_haste_creature():
    s = _state()
    s.player_by_id(0).agent.yes = False  # no Boo
    minsc = _put(s, _P["Minsc & Boo, Timeless Heroes"], 0)
    _drain(s)
    plain = _put(s, _creature("Plain"), 0)
    hasty = _put(s, _creature("Hasty", keywords={"haste"}), 1)
    _activate(s, 0, minsc, +1)
    offered = s.player_by_id(0).agent.picks_seen[-1]
    assert offered == [("creature", hasty.id)]
    assert hasty.plus_one_counters == 3
    assert plain.plus_one_counters == 0
    assert minsc.loyalty_counters == 4


def test_minsc_minus_two_sacrificed_hamster_deals_power_and_draws():
    s = _state()
    minsc = _put(s, _P["Minsc & Boo, Timeless Heroes"], 0)
    _drain(s)
    boo = next(o for o in s.battlefield if o.printing.name == "Boo")
    boo.plus_one_counters = 3  # power 4
    _library(s, 0, 6)
    agent = s.player_by_id(0).agent
    agent.target_pick = ("player", 1)
    agent.sac_pick = boo.id
    _activate(s, 0, minsc, -2)
    assert boo not in s.battlefield
    assert s.player_by_id(1).life == 16
    assert len(s.player_by_id(0).hand) == 4
    assert minsc.loyalty_counters == 1


def test_minsc_minus_two_non_hamster_does_not_draw():
    s = _state()
    s.player_by_id(0).agent.yes = False
    minsc = _put(s, _P["Minsc & Boo, Timeless Heroes"], 0)
    _drain(s)
    bear = _put(s, _creature(power=3, toughness=3), 0)
    _library(s, 0, 6)
    agent = s.player_by_id(0).agent
    agent.target_pick = ("player", 1)
    _activate(s, 0, minsc, -2)
    assert bear not in s.battlefield
    assert s.player_by_id(1).life == 17
    assert s.player_by_id(0).hand == []


def test_minsc_minus_two_without_creature_does_nothing():
    s = _state()
    s.player_by_id(0).agent.yes = False
    minsc = _put(s, _P["Minsc & Boo, Timeless Heroes"], 0)
    _drain(s)
    s.player_by_id(0).agent.target_pick = ("player", 1)
    _activate(s, 0, minsc, -2)
    assert s.player_by_id(1).life == 20


def test_minsc_minus_two_target_gone_no_damage_but_still_draws():
    s = _state()
    minsc = _put(s, _P["Minsc & Boo, Timeless Heroes"], 0)
    _drain(s)
    boo = next(o for o in s.battlefield if o.printing.name == "Boo")
    victim = _put(s, _creature("Victim"), 1)
    _library(s, 0, 3)
    agent = s.player_by_id(0).agent
    agent.target_pick = ("creature", victim.id)
    agent.sac_pick = boo.id
    _activate(s, 0, minsc, -2, resolve=False)
    s.battlefield.remove(victim)
    resolve_top_of_stack(s)
    assert len(s.player_by_id(0).hand) == 1


# ---------------------------------------------------------------------------
# CR 120.3c — damage to planeswalkers
# ---------------------------------------------------------------------------


def test_damage_to_planeswalker_removes_loyalty():
    s = _state()
    narset = _put(s, _P["Narset, Parter of Veils"], 1)
    DealDamageAnyTarget(amount=3).resolve(s, 0, (("planeswalker", narset.id),))
    assert narset.loyalty_counters == 2
    DealDamageAnyTarget(amount=2).resolve(s, 0, (("planeswalker", narset.id),))
    state_based_actions(s)
    assert narset not in s.battlefield


def test_cards_drawn_counter_tracks_draws():
    s = _state()
    _library(s, 0, 3)
    DrawCards(amount=2).resolve(s, 0)
    assert s.player_by_id(0).cards_drawn_this_turn == 2


# ---------------------------------------------------------------------------
# Jace, the Mind Sculptor
# ---------------------------------------------------------------------------


def test_jtms_plus_two_may_bottom_target_players_top_card():
    s = _state()
    jace = _put(s, _P["Jace, the Mind Sculptor"], 0)
    lib = _library(s, 1, 3)
    top = lib[0]
    s.player_by_id(0).agent.target_pick = ("player", 1)
    _activate(s, 0, jace, +2)
    assert s.player_by_id(1).library[-1] is top
    assert jace.loyalty_counters == 5


def test_jtms_plus_two_may_keep_on_top():
    s = _state()
    jace = _put(s, _P["Jace, the Mind Sculptor"], 0)
    lib = _library(s, 0, 3)
    top = lib[0]
    agent = s.player_by_id(0).agent
    agent.target_pick = ("player", 0)
    agent.yes = False
    _activate(s, 0, jace, +2)
    assert s.player_by_id(0).library[0] is top


def test_jtms_zero_is_brainstorm():
    s = _state()
    jace = _put(s, _P["Jace, the Mind Sculptor"], 0)
    _library(s, 0, 5)
    _activate(s, 0, jace, 0)
    p = s.player_by_id(0)
    assert len(p.hand) == 1
    assert len(p.library) == 4
    assert jace.loyalty_counters == 3


def test_jtms_minus_one_unsummons():
    s = _state()
    jace = _put(s, _P["Jace, the Mind Sculptor"], 0)
    bear = _put(s, _creature(), 1)
    _activate(s, 0, jace, -1)
    assert bear in s.player_by_id(1).hand


def test_jtms_ultimate_exiles_library_and_shuffles_hand_in():
    s = _state()
    jace = _put(s, _P["Jace, the Mind Sculptor"], 0)
    jace.loyalty_counters = 12
    _library(s, 1, 6)
    opp = s.player_by_id(1)
    for _ in range(2):
        c = s.new_object(BASIC_LANDS["Island"], 1, Zone.HAND)
        opp.hand.append(c)
    s.player_by_id(0).agent.target_pick = ("player", 1)
    _activate(s, 0, jace, -12)
    assert len(opp.exile) == 6
    assert opp.hand == []
    assert len(opp.library) == 2
    assert all(c.zone == Zone.LIBRARY for c in opp.library)


# ---------------------------------------------------------------------------
# Teferi, Hero of Dominaria
# ---------------------------------------------------------------------------


def test_teferi_hod_plus_one_draws_and_untaps_two_lands_at_end_step():
    from mtg_bot.turn import run_delayed_end_step_triggers
    s = _state()
    teferi = _put(s, _P["Teferi, Hero of Dominaria"], 0)
    lands = [_put(s, BASIC_LANDS["Island"], 0) for _ in range(3)]
    for land in lands:
        land.tapped = True
    _library(s, 0, 2)
    _activate(s, 0, teferi, +1)
    assert len(s.player_by_id(0).hand) == 1
    assert all(land.tapped for land in lands)  # not until the end step
    s.step = Step.END
    run_delayed_end_step_triggers(s)
    while s.stack:
        resolve_top_of_stack(s)
    assert sum(1 for land in lands if not land.tapped) == 2


def test_teferi_hod_delayed_untap_fires_even_if_teferi_left():
    from mtg_bot.turn import run_delayed_end_step_triggers
    s = _state()
    teferi = _put(s, _P["Teferi, Hero of Dominaria"], 0)
    land = _put(s, BASIC_LANDS["Island"], 0)
    land.tapped = True
    _library(s, 0, 1)
    _activate(s, 0, teferi, +1)
    teferi.loyalty_counters = 0
    state_based_actions(s)
    assert teferi not in s.battlefield
    run_delayed_end_step_triggers(s)
    while s.stack:
        resolve_top_of_stack(s)
    assert not land.tapped


def test_teferi_hod_minus_three_tucks_third_from_top():
    s = _state()
    teferi = _put(s, _P["Teferi, Hero of Dominaria"], 0)
    bear = _put(s, _creature(), 1)
    land = _put(s, BASIC_LANDS["Forest"], 1)
    lib = _library(s, 1, 4)
    s.player_by_id(0).agent.target_pick = ("creature", bear.id)
    _activate(s, 0, teferi, -3)
    offered = s.player_by_id(0).agent.picks_seen[-1]
    assert not any(t[1] == land.id for t in offered)
    assert bear not in s.battlefield
    assert s.player_by_id(1).library[2] is bear
    assert bear.zone == Zone.LIBRARY
    assert len(lib) == 5


def test_teferi_hod_minus_three_short_library_goes_to_bottom():
    s = _state()
    teferi = _put(s, _P["Teferi, Hero of Dominaria"], 0)
    bear = _put(s, _creature(), 1)
    _library(s, 1, 1)
    s.player_by_id(0).agent.target_pick = ("creature", bear.id)
    _activate(s, 0, teferi, -3)
    assert s.player_by_id(1).library[-1] is bear


def test_teferi_hod_minus_three_token_ceases_to_exist():
    from mtg_bot.cards.base import make_token_creature
    s = _state()
    teferi = _put(s, _P["Teferi, Hero of Dominaria"], 0)
    tok = _put(s, make_token_creature("Germ", 0, 0), 1)
    tok.plus_one_counters = 1
    s.player_by_id(0).agent.target_pick = ("creature", tok.id)
    _activate(s, 0, teferi, -3)
    assert tok not in s.battlefield
    assert tok not in s.player_by_id(1).library


def test_teferi_hod_emblem_exiles_on_each_draw():
    s = _state()
    teferi = _put(s, _P["Teferi, Hero of Dominaria"], 0)
    teferi.loyalty_counters = 8
    bear = _put(s, _creature(), 1)
    wall = _put(s, _creature("Wall"), 1)
    _activate(s, 0, teferi, -8)
    assert len(s.emblems) == 1
    _library(s, 0, 3)
    # Two draws -> two triggers, each targeting when put on the stack
    # (both pick the first legal target; the second then fizzles).
    draw_n_cards(s, 0, 2)
    assert len(s.stack) == 2
    _drain(s)
    assert bear in s.player_by_id(1).exile
    assert wall in s.battlefield
    draw_card(s, 0)
    _drain(s)
    assert wall in s.player_by_id(1).exile
    # The opponent's draws don't trigger it.
    _library(s, 1, 2)
    draw_card(s, 1)
    assert not s.stack


# ---------------------------------------------------------------------------
# Dack Fayden
# ---------------------------------------------------------------------------


def test_dack_plus_one_target_player_draws_two_discards_two():
    s = _state()
    dack = _put(s, _P["Dack Fayden"], 0)
    _library(s, 1, 3)
    s.player_by_id(0).agent.target_pick = ("player", 1)
    s.player_by_id(1).agent = RandomAgent()
    _activate(s, 0, dack, +1)
    opp = s.player_by_id(1)
    assert opp.hand == [] and len(opp.graveyard) == 2
    assert dack.loyalty_counters == 4


def test_dack_minus_two_steals_artifact_permanently():
    from mtg_bot.cards.base import make_artifact
    s = _state()
    dack = _put(s, _P["Dack Fayden"], 0)
    rock = _put(s, make_artifact("Rock", "{2}"), 1)
    bear = _put(s, _creature(), 1)
    _activate(s, 0, dack, -2)
    offered = s.player_by_id(0).agent.picks_seen[-1]
    assert offered == [("permanent", rock.id)]
    assert rock.controller_id == 0
    run_cleanup_step(s)
    dack.loyalty_counters = 0
    state_based_actions(s)
    assert rock.controller_id == 0  # indefinite, survives Dack leaving
    assert bear.controller_id == 1


def test_dack_emblem_steals_permanents_your_spells_target():
    from mtg_bot.effects.generic import PumpTargetCreatureUntilEOT
    s = _state()
    dack = _put(s, _P["Dack Fayden"], 0)
    dack.loyalty_counters = 6
    _activate(s, 0, dack, -6)
    assert len(s.emblems) == 1
    bear = _put(s, _creature(), 1)
    _put(s, BASIC_LANDS["Mountain"], 0)
    pump = make_instant(
        "Giant Growth", "{R}",
        PumpTargetCreatureUntilEOT(power_bonus=1, toughness_bonus=1),
    )
    card = s.new_object(pump, 0, Zone.HAND)
    s.player_by_id(0).hand.append(card)
    s.player_by_id(0).agent.target_pick = ("creature", bear.id)
    from mtg_bot.actions import apply_action
    apply_action(s, 0, CastSpell(card.id))
    assert len(s.stack) == 2  # spell + emblem trigger
    _drain(s)
    assert bear.controller_id == 0
    # An opponent's spell doesn't trigger your emblem.
    _put(s, BASIC_LANDS["Mountain"], 1)
    card2 = s.new_object(pump, 1, Zone.HAND)
    s.player_by_id(1).hand.append(card2)
    s.player_by_id(1).agent.target_pick = ("creature", bear.id)
    s.active_player_idx = 1
    s.priority_player_idx = 1
    apply_action(s, 1, CastSpell(card2.id))
    assert len(s.stack) == 1


# ---------------------------------------------------------------------------
# Karn, Scion of Urza
# ---------------------------------------------------------------------------


def test_karn_plus_one_opponent_picks_card_other_exiled_with_silver():
    s = _state()
    karn = _put(s, _P["Karn, Scion of Urza"], 0)
    lib = _library(s, 0, 3)
    first, second = lib[0], lib[1]
    s.player_by_id(1).agent.library_pick = second.id
    _activate(s, 0, karn, +1)
    p = s.player_by_id(0)
    assert p.hand == [second]
    assert p.exile == [first]
    assert first.silver_counters == 1
    assert karn.loyalty_counters == 6


def test_karn_plus_one_with_one_or_zero_cards():
    s = _state()
    karn = _put(s, _P["Karn, Scion of Urza"], 0)
    lib = _library(s, 0, 1)
    only = lib[0]
    _activate(s, 0, karn, +1)
    assert s.player_by_id(0).hand == [only]
    assert s.player_by_id(0).exile == []
    s.loyalty_activated_this_turn.clear()
    _activate(s, 0, karn, +1)  # empty library: nothing happens
    assert s.player_by_id(0).hand == [only]


def test_karn_minus_one_returns_silver_card_only():
    s = _state()
    karn = _put(s, _P["Karn, Scion of Urza"], 0)
    p = s.player_by_id(0)
    plain = s.new_object(BASIC_LANDS["Forest"], 0, Zone.EXILE)
    silver = s.new_object(BASIC_LANDS["Island"], 0, Zone.EXILE)
    silver.silver_counters = 1
    p.exile.extend([plain, silver])
    _activate(s, 0, karn, -1)
    assert p.hand == [silver]
    assert silver.silver_counters == 0
    assert p.exile == [plain]
    s.loyalty_activated_this_turn.clear()
    _activate(s, 0, karn, -1)  # nothing eligible
    assert p.hand == [silver]


def test_karn_minus_two_construct_scales_with_artifacts():
    from mtg_bot.cards.base import make_artifact
    from mtg_bot.game import effective_power, effective_toughness
    s = _state()
    karn = _put(s, _P["Karn, Scion of Urza"], 0)
    _activate(s, 0, karn, -2)
    construct = next(
        o for o in s.battlefield if o.printing.name == "Construct"
    )
    assert construct.printing.is_artifact
    assert (effective_power(s, construct),
            effective_toughness(s, construct)) == (1, 1)
    _put(s, make_artifact("Rock", "{2}"), 0)
    _put(s, make_artifact("Opp Rock", "{2}"), 1)
    assert effective_power(s, construct) == 2
    state_based_actions(s)
    assert construct in s.battlefield
