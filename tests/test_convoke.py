"""Convoke (CR 702.51) tests via Vote Out.

Vote Out is {3}{B}, sorcery, "destroy target creature", with Convoke.
Each untapped creature the controller taps pays {1} or one mana of
that creature's color.

Coverage:
- payable purely from convoke (4 creatures, 1 black) → no mana spent
- partial convoke (2 creatures pay 2 generic; remaining {1}{B} paid
  from lands)
- prefer-color: a black creature pays the {B} pip; a green creature
  pays generic
- creature already tapped not eligible
- summoning-sick creatures CAN convoke (CR 702.51 doesn't gate on
  sickness — convoke isn't an activated ability)
- agent declines convoke → spell pays full cost from lands/pool
- convoke + sac-for-mana on the same Scion-like source are mutually
  exclusive on a single cast (tapping for convoke prevents the
  ability's tap cost)
- without the convoke flag, a non-convoke spell ignores the agent's
  pick and pays full cost
"""

from __future__ import annotations

from mtg_bot.actions import (
    CastSpell, apply_action, can_pay_cost, resolve_top_of_stack,
)
from mtg_bot.agents import Agent
from mtg_bot.cards import BASIC_LANDS, EOE_SPELLS, SYNTHETIC_CREATURES
from mtg_bot.cards.base import (
    ActivatedAbility, ActivationCost, CardPrinting, ManaCost,
    parse_mana_cost,
)
from mtg_bot.effects.generic import AddManaToPool
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.legal import legal_actions
from mtg_bot.turn import Step


class _PickFirstAgent(Agent):
    def choose_target(self, state, player_id, legal_targets):
        # Prefer opponent creatures so a Vote Out cast doesn't blow up
        # the convoke creatures we want to inspect post-cast.
        for kind, tid in legal_targets:
            if kind == "creature":
                obj = next(
                    (o for o in state.battlefield if o.id == tid), None,
                )
                if obj is not None and obj.controller_id != player_id:
                    return (kind, tid)
        return legal_targets[0] if legal_targets else None

    def choose_convoke_creatures(
        self, state, player_id, candidates,
        remaining_generic, remaining_colored,
    ):
        return list(candidates)


class _NoConvokeAgent(_PickFirstAgent):
    def choose_convoke_creatures(
        self, state, player_id, candidates,
        remaining_generic, remaining_colored,
    ):
        return []


# Synthetic Eldrazi Scion: 1/1 colorless creature with
# "{T}, Sacrifice this: Add {C}". Used to pin convoke + sac-for-mana
# mutual exclusion on a single cast.
_SCION = CardPrinting(
    name="Scion (test)",
    mana_cost_str="",
    mana_cost=ManaCost(),
    type_line="Creature — Eldrazi Scion",
    supertypes=(),
    card_types=("Creature",),
    subtypes=("Eldrazi", "Scion"),
    power=1,
    toughness=1,
    activated_abilities=(
        ActivatedAbility(
            cost=ActivationCost(tap_self=True, sacrifice_self=True),
            effect=AddManaToPool(produces=(("C", 1),)),
            is_mana_ability=True,
        ),
    ),
)


def _new_state(p0_agent=None, p1_agent=None):
    state = GameState()
    state.players.append(Player(id=0, agent=p0_agent or _PickFirstAgent()))
    state.players.append(Player(id=1, agent=p1_agent or _PickFirstAgent()))
    state.active_player_idx = 0
    state.priority_player_idx = 0
    state.step = Step.PRECOMBAT_MAIN
    return state


def _put(state, printing, owner_id=0):
    obj = state.new_object(printing, owner_id, Zone.BATTLEFIELD)
    state.battlefield.append(obj)
    return obj


def _hand(state, printing, owner_id=0):
    p = state.players[owner_id]
    obj = state.new_object(printing, owner_id, Zone.HAND)
    p.hand.append(obj)
    return obj


def test_vote_out_has_convoke():
    assert EOE_SPELLS["Vote Out"].has_convoke is True


def test_vote_out_castable_with_only_creatures_no_lands():
    """4 untapped creatures (one black, three colorless-by-mana-cost
    standins) cover {3}{B}. No lands needed."""
    state = _new_state()
    p = state.players[0]
    # One black creature for the {B} pip.
    rat = _put(state, SYNTHETIC_CREATURES["Cemetery Rat"], 0)
    # Three not-summoning-sick non-black creatures pay {3} generic.
    bears = [_put(state, SYNTHETIC_CREATURES["Wild Bear"], 0) for _ in range(3)]
    for o in [rat] + bears:
        o.summoning_sick = False  # not required, but explicit
    # Opponent has a target.
    victim = _put(state, SYNTHETIC_CREATURES["Wild Bear"], 1)
    # Vote Out in hand, no lands.
    vo = _hand(state, EOE_SPELLS["Vote Out"], 0)
    # Affordability check sees convoke as payable.
    assert can_pay_cost(
        state, 0, EOE_SPELLS["Vote Out"].mana_cost, convoke=True,
    )
    # Cast and resolve.
    apply_action(state, 0, CastSpell(vo.id))
    resolve_top_of_stack(state)
    # All four creatures got tapped for convoke.
    assert rat.tapped
    assert all(b.tapped for b in bears)
    # Target destroyed.
    assert victim not in state.battlefield
    # No mana left over (cost fully paid by convoke).
    assert p.mana_pool == []


def test_vote_out_partial_convoke_remaining_paid_by_lands():
    """2 creatures pay {2}; remaining {1}{B} paid by Swamps."""
    state = _new_state()
    p = state.players[0]
    # 2 Swamps for the residual {1}{B}.
    swamps = [_put(state, BASIC_LANDS["Swamp"], 0) for _ in range(2)]
    # 2 non-black creatures (each pays {1} via convoke).
    bears = [_put(state, SYNTHETIC_CREATURES["Wild Bear"], 0) for _ in range(2)]
    victim = _put(state, SYNTHETIC_CREATURES["Wild Bear"], 1)
    vo = _hand(state, EOE_SPELLS["Vote Out"], 0)
    apply_action(state, 0, CastSpell(vo.id))
    resolve_top_of_stack(state)
    assert all(b.tapped for b in bears)
    # Both swamps tapped to cover {1}{B}.
    assert all(s.tapped for s in swamps)
    assert victim not in state.battlefield


def test_vote_out_color_match_pays_colored_pip_first():
    """A black creature pays the {B} pip; non-black creatures pay
    generic. With 1 black + 3 non-black, no lands needed."""
    state = _new_state()
    p = state.players[0]
    rat = _put(state, SYNTHETIC_CREATURES["Cemetery Rat"], 0)
    bears = [_put(state, SYNTHETIC_CREATURES["Wild Bear"], 0) for _ in range(3)]
    swamp = _put(state, BASIC_LANDS["Swamp"], 0)
    _put(state, SYNTHETIC_CREATURES["Wild Bear"], 1)
    vo = _hand(state, EOE_SPELLS["Vote Out"], 0)
    apply_action(state, 0, CastSpell(vo.id))
    resolve_top_of_stack(state)
    # Convoke covered the entire cost; the swamp shouldn't be tapped.
    assert not swamp.tapped
    assert rat.tapped
    assert all(b.tapped for b in bears)


def test_already_tapped_creature_not_eligible_for_convoke():
    """A tapped creature can't be convoked — only untapped creatures
    are candidates per CR 702.51."""
    state = _new_state()
    rat = _put(state, SYNTHETIC_CREATURES["Cemetery Rat"], 0)
    rat.tapped = True
    # Need to actually pay the cost from somewhere; add lands.
    swamps = [_put(state, BASIC_LANDS["Swamp"], 0) for _ in range(4)]
    _put(state, SYNTHETIC_CREATURES["Wild Bear"], 1)
    vo = _hand(state, EOE_SPELLS["Vote Out"], 0)
    apply_action(state, 0, CastSpell(vo.id))
    resolve_top_of_stack(state)
    # Rat stays tapped (it was already tapped — no double-tap).
    assert rat.tapped
    # All four swamps tapped: convoke had nothing to contribute.
    assert all(s.tapped for s in swamps)


def test_summoning_sick_creature_can_convoke():
    """CR 702.51 doesn't gate on summoning sickness because tapping
    for convoke isn't an activated ability."""
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], 0)
    bear.summoning_sick = True
    swamps = [_put(state, BASIC_LANDS["Swamp"], 0) for _ in range(4)]
    _put(state, SYNTHETIC_CREATURES["Wild Bear"], 1)
    vo = _hand(state, EOE_SPELLS["Vote Out"], 0)
    apply_action(state, 0, CastSpell(vo.id))
    resolve_top_of_stack(state)
    assert bear.tapped
    # Only 3 of 4 swamps tapped (bear paid one generic via convoke).
    tapped_count = sum(1 for s in swamps if s.tapped)
    assert tapped_count == 3


def test_agent_declines_convoke_pays_full_cost_from_lands():
    """Agent returning [] from choose_convoke_creatures skips convoke
    entirely; the spell pays full {3}{B} from lands."""
    state = _new_state(p0_agent=_NoConvokeAgent())
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], 0)
    swamps = [_put(state, BASIC_LANDS["Swamp"], 0) for _ in range(4)]
    _put(state, SYNTHETIC_CREATURES["Wild Bear"], 1)
    vo = _hand(state, EOE_SPELLS["Vote Out"], 0)
    apply_action(state, 0, CastSpell(vo.id))
    resolve_top_of_stack(state)
    assert not bear.tapped
    assert all(s.tapped for s in swamps)


def test_vote_out_unplayable_with_no_creatures_or_lands():
    """No creatures, no lands → cost unpayable → not in legal actions."""
    state = _new_state()
    vo = _hand(state, EOE_SPELLS["Vote Out"], 0)
    _put(state, SYNTHETIC_CREATURES["Wild Bear"], 1)
    cast_acts = [
        a for a in legal_actions(state, 0)
        if isinstance(a, CastSpell) and a.card_id == vo.id
    ]
    assert cast_acts == []


def test_vote_out_convoke_makes_otherwise_unplayable_castable():
    """1 Swamp alone can't pay {3}{B}, but with 3 creatures it's
    castable: convoke contributes the missing {3}."""
    state = _new_state()
    swamp = _put(state, BASIC_LANDS["Swamp"], 0)
    bears = [_put(state, SYNTHETIC_CREATURES["Wild Bear"], 0) for _ in range(3)]
    _put(state, SYNTHETIC_CREATURES["Wild Bear"], 1)
    vo = _hand(state, EOE_SPELLS["Vote Out"], 0)
    cast_acts = [
        a for a in legal_actions(state, 0)
        if isinstance(a, CastSpell) and a.card_id == vo.id
    ]
    assert len(cast_acts) == 1


def test_convoke_and_scion_sac_mutually_exclusive_on_same_cast():
    """A Scion has "{T}, Sacrifice this: Add {C}". CR ordering:
    mana abilities fire at 601.2g (BEFORE convoke at 601.2h). The
    Scion's sac-for-mana activates first to help pay the cost, which
    sacrifices it — so it's no longer available for convoke. Either
    direction yields mutual exclusion: a single Scion contributes
    EITHER mana via sac OR a convoke pip, never both on the same cast.

    The runtime here exercises the sac-first half: Scion sacs into
    {C} that pays one generic, and the bears convoke the rest.
    """
    state = _new_state()
    scion = _put(state, _SCION, 0)
    scion.summoning_sick = False
    bears = [_put(state, SYNTHETIC_CREATURES["Wild Bear"], 0) for _ in range(3)]
    _put(state, SYNTHETIC_CREATURES["Wild Bear"], 1)
    vo = _hand(state, EOE_SPELLS["Vote Out"], 0)
    apply_action(state, 0, CastSpell(vo.id))
    # Scion sacrificed at 601.2g (no longer on the battlefield).
    assert scion not in state.battlefield
    # Bears were used for convoke at 601.2h.
    assert any(b.tapped for b in bears)


def test_convoke_excess_candidates_stops_when_cost_fully_paid():
    """Agent passes all 6 untapped creatures; only 4 pips of cost
    exist, so only 4 get tapped. Pin the early-break."""
    state = _new_state()
    rat = _put(state, SYNTHETIC_CREATURES["Cemetery Rat"], 0)
    bears = [_put(state, SYNTHETIC_CREATURES["Wild Bear"], 0) for _ in range(5)]
    _put(state, SYNTHETIC_CREATURES["Wild Bear"], 1)
    vo = _hand(state, EOE_SPELLS["Vote Out"], 0)
    apply_action(state, 0, CastSpell(vo.id))
    resolve_top_of_stack(state)
    # Cost is 4 pips; rat + first 3 bears tap. Last 2 bears stay untapped.
    tapped = [o for o in [rat] + bears if o.tapped]
    untapped = [o for o in [rat] + bears if not o.tapped]
    assert len(tapped) == 4
    assert len(untapped) == 2


class _DuplicatePickAgent(Agent):
    """Returns duplicate ids — pins the dedup branch in _apply_convoke."""
    def choose_target(self, state, player_id, legal_targets):
        for kind, tid in legal_targets:
            if kind == "creature":
                obj = next(
                    (o for o in state.battlefield if o.id == tid), None,
                )
                if obj is not None and obj.controller_id != player_id:
                    return (kind, tid)
        return legal_targets[0] if legal_targets else None

    def choose_convoke_creatures(
        self, state, player_id, candidates,
        remaining_generic, remaining_colored,
    ):
        return [candidates[0], candidates[0], candidates[0], candidates[0]]


def test_convoke_dedupes_duplicate_ids_from_agent():
    """If the agent returns the same id multiple times, only the
    first occurrence taps the creature; subsequent dupes are skipped."""
    state = _new_state(p0_agent=_DuplicatePickAgent())
    rat = _put(state, SYNTHETIC_CREATURES["Cemetery Rat"], 0)
    swamps = [_put(state, BASIC_LANDS["Swamp"], 0) for _ in range(4)]
    _put(state, SYNTHETIC_CREATURES["Wild Bear"], 1)
    vo = _hand(state, EOE_SPELLS["Vote Out"], 0)
    apply_action(state, 0, CastSpell(vo.id))
    resolve_top_of_stack(state)
    assert rat.tapped
    # Rat covered the {B} pip; remaining {3} comes from 3 swamps.
    tapped_swamps = sum(1 for s in swamps if s.tapped)
    assert tapped_swamps == 3


def test_convoke_max_contribution_with_already_zero_cost():
    """Edge case: can_pay_cost(convoke=True) on a zero cost short-
    circuits without scanning candidates."""
    state = _new_state()
    _put(state, SYNTHETIC_CREATURES["Cemetery Rat"], 0)
    assert can_pay_cost(state, 0, ManaCost(), convoke=True)


def test_non_convoke_spell_ignores_agent_convoke_pick():
    """A spell WITHOUT the convoke flag never calls
    ``choose_convoke_creatures``. Pin: a non-convoke {3}{B} sorcery
    pays from lands even when the player controls eligible creatures."""
    state = _new_state()
    bears = [_put(state, SYNTHETIC_CREATURES["Wild Bear"], 0) for _ in range(4)]
    swamps = [_put(state, BASIC_LANDS["Swamp"], 0) for _ in range(4)]
    _put(state, SYNTHETIC_CREATURES["Wild Bear"], 1)
    # Use Gravkill: {3}{B} instant, no convoke.
    gk = _hand(state, EOE_SPELLS["Gravkill"], 0)
    assert EOE_SPELLS["Gravkill"].has_convoke is False
    apply_action(state, 0, CastSpell(gk.id))
    resolve_top_of_stack(state)
    # No creatures tapped (no convoke).
    assert not any(b.tapped for b in bears)
    # All lands tapped.
    assert all(s.tapped for s in swamps)
