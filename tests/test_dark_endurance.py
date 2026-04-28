"""Tests for Dark Endurance — the conditional cost-reduction rider.

Oracle text:
    This spell costs {1} less to cast if it targets a blocking creature.
    Target creature gets +2/+0 and gains indestructible until end of turn.

Modeled as a ``CostReduction(amount=1, condition=
"target_is_blocking_creature")``.  Evaluated against the chosen target
in the cast pipeline (and optimistically — "is there ANY blocker that
could be picked?" — in ``legal_actions`` so the affordability gate
doesn't reject the spell when the discount could legally apply).
"""

from mtg_bot.actions import (
    CastSpell, _cast_spell, apply_cost_reductions, resolve_top_of_stack,
)
from mtg_bot.agents import Agent, RandomAgent
from mtg_bot.cards import BASIC_LANDS, SYNTHETIC_CREATURES, ManaCost
from mtg_bot.combat import declare_attackers, declare_blockers
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.legal import legal_actions
from mtg_bot.turn import Step

from mtg_bot.cards.source import get_active_source

_PRINTINGS = get_active_source().get_printings()


class _PickAgent(Agent):
    """Minimal agent: always picks a designated target id when present in
    the legal-targets list, otherwise picks the first option. Used to
    deterministically steer Dark Endurance's target choice in tests.
    """

    def __init__(self, prefer_target_id: int | None = None):
        self.prefer_target_id = prefer_target_id

    def choose_target(self, state, player_id, legal_targets):
        if not legal_targets:
            return None
        if self.prefer_target_id is not None:
            for t in legal_targets:
                if t[1] == self.prefer_target_id:
                    return t
        return legal_targets[0]


def _new_state(p0_lands: int = 0, agent: Agent | None = None) -> GameState:
    state = GameState()
    state.players.append(Player(id=0, agent=agent or _PickAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    state.step = Step.PRECOMBAT_MAIN
    for _ in range(p0_lands):
        s = state.new_object(BASIC_LANDS["Swamp"], 0, Zone.BATTLEFIELD)
        state.battlefield.append(s)
    return state


def _put_creature(
    state: GameState, name: str, controller_id: int,
):
    obj = state.new_object(
        SYNTHETIC_CREATURES[name], controller_id, Zone.BATTLEFIELD,
    )
    obj.summoning_sick = False
    state.battlefield.append(obj)
    return obj


def _give_dark_endurance(state: GameState, controller_id: int):
    card = state.new_object(
        _PRINTINGS["Dark Endurance"], controller_id, Zone.HAND,
    )
    state.players[controller_id].hand.append(card)
    return card


# -----------------------------------------------------------------
# Printing wiring: the rider lives on the printing as a CostReduction.
# -----------------------------------------------------------------


def test_dark_endurance_printing_carries_blocking_cost_reduction():
    p = _PRINTINGS["Dark Endurance"]
    assert p.mana_cost == ManaCost(generic=1, colored=(("B", 1),))
    assert len(p.cost_reductions) == 1
    rule = p.cost_reductions[0]
    assert rule.condition == "target_is_blocking_creature"
    assert rule.amount == 1


# -----------------------------------------------------------------
# apply_cost_reductions: target context drives the discount.
# -----------------------------------------------------------------


def test_apply_cost_reductions_no_discount_when_target_is_attacker():
    state = _new_state()
    attacker = _put_creature(state, "Wild Bear", 1)  # P1's creature
    attacker.attacking = True  # currently attacking, NOT blocking
    base = ManaCost(generic=1, colored=(("B", 1),))
    out = apply_cost_reductions(
        _PRINTINGS["Dark Endurance"], state, 0, base,
        chosen_targets=(("creature", attacker.id),),
    )
    assert out == base


def test_apply_cost_reductions_discount_when_target_is_blocker():
    state = _new_state()
    blocker = _put_creature(state, "Wild Bear", 1)
    blocker.blocking = 99  # arbitrary attacker id; truthy → "is blocking"
    base = ManaCost(generic=1, colored=(("B", 1),))
    out = apply_cost_reductions(
        _PRINTINGS["Dark Endurance"], state, 0, base,
        chosen_targets=(("creature", blocker.id),),
    )
    assert out == ManaCost(generic=0, colored=(("B", 1),))


def test_apply_cost_reductions_optimistic_when_targets_unknown():
    """legal_actions calls without chosen_targets — the rule should
    apply if any blocker exists, since the caster could pick it."""
    state = _new_state()
    blocker = _put_creature(state, "Wild Bear", 1)
    blocker.blocking = 99
    base = ManaCost(generic=1, colored=(("B", 1),))
    out = apply_cost_reductions(
        _PRINTINGS["Dark Endurance"], state, 0, base,
    )
    assert out == ManaCost(generic=0, colored=(("B", 1),))


def test_apply_cost_reductions_optimistic_no_blockers_no_discount():
    state = _new_state()
    _put_creature(state, "Wild Bear", 1)  # not blocking
    base = ManaCost(generic=1, colored=(("B", 1),))
    out = apply_cost_reductions(
        _PRINTINGS["Dark Endurance"], state, 0, base,
    )
    assert out == base


# -----------------------------------------------------------------
# End-to-end cast: targeting an attacker pays full cost.
# -----------------------------------------------------------------


def test_cast_targeting_attacker_pays_full_cost():
    state = _new_state(p0_lands=2)  # exactly enough for full {1}{B}
    attacker = _put_creature(state, "Wild Bear", 1)
    attacker.attacking = True  # but NOT blocking
    card = _give_dark_endurance(state, 0)
    state.players[0].agent = _PickAgent(prefer_target_id=attacker.id)
    _cast_spell(state, 0, card.id)
    # Both swamps tapped → full {1}{B} paid.
    swamps = [
        o for o in state.battlefield
        if o.printing.name == "Swamp" and o.controller_id == 0
    ]
    assert all(s.tapped for s in swamps)
    # No "cost reduced" log line.
    assert not any("cost reduced" in line for line in state.log)


def test_cast_targeting_blocker_pays_one_less():
    state = _new_state(p0_lands=1)  # only ONE swamp → needs the discount
    blocker = _put_creature(state, "Wild Bear", 1)
    blocker.blocking = 99
    card = _give_dark_endurance(state, 0)
    state.players[0].agent = _PickAgent(prefer_target_id=blocker.id)
    _cast_spell(state, 0, card.id)
    # The lone swamp is tapped (paid {B}); discount removed the {1}.
    swamps = [
        o for o in state.battlefield
        if o.printing.name == "Swamp" and o.controller_id == 0
    ]
    assert len(swamps) == 1 and swamps[0].tapped
    assert any(
        "cost reduced by 1 (target_is_blocking_creature)" in line
        for line in state.log
    )
    # And the spell is on the stack with the blocker as the target.
    assert state.stack and state.stack[-1].source.id == card.id
    assert state.stack[-1].targets == (("creature", blocker.id),)


# -----------------------------------------------------------------
# Realistic flow: instant speed during the opposing combat block step.
# -----------------------------------------------------------------


def test_cast_at_instant_speed_during_opponent_block_step_gets_discount():
    """A typical Dark Endurance scenario: opponent attacks, you block,
    they wait, you pump-and-shield the blocker with Dark Endurance for
    {B} (instead of {1}{B}) thanks to the rider."""
    state = _new_state(p0_lands=1)
    # P0 has Dark Endurance in hand and only one Swamp. Hand the cast
    # path has to find the {1}-less discount or it can't cast at all.
    # P1 (active player) attacks with Wild Bear.
    state.active_player_idx = 1
    state.priority_player_idx = 0  # P0 has priority on P1's turn
    state.step = Step.DECLARE_BLOCKERS
    attacker = _put_creature(state, "Wild Bear", 1)
    blocker = _put_creature(state, "Forest Giant", 0)  # P0's blocker
    declare_attackers(state, [attacker.id])
    declare_blockers(state, {blocker.id: attacker.id})
    assert blocker.blocking == attacker.id
    # legal_actions should expose the spell since {B} is payable.
    card = _give_dark_endurance(state, 0)
    state.players[0].agent = _PickAgent(prefer_target_id=blocker.id)
    casts = [a for a in legal_actions(state, 0) if isinstance(a, CastSpell)]
    assert any(a.card_id == card.id for a in casts), (
        "Dark Endurance should be a legal cast at {B} when a friendly "
        "blocker exists and only one swamp is available."
    )
    _cast_spell(state, 0, card.id)
    # Resolve the spell off the stack and confirm the buff applied.
    resolve_top_of_stack(state)
    # Blocker gets +2/+0 and indestructible UEOT.
    from mtg_bot.game import effective_keywords
    assert "indestructible" in effective_keywords(state, blocker)
    assert blocker.temp_power_bonus == 2
    assert blocker.temp_toughness_bonus == 0


# -----------------------------------------------------------------
# legal_actions exposure: spell becomes legal at the reduced cost
# when the player can ONLY afford the reduced cost.
# -----------------------------------------------------------------


def test_legal_actions_exposes_cast_at_reduced_cost():
    state = _new_state(p0_lands=1)  # ONE swamp — only the reduced cost is payable
    blocker = _put_creature(state, "Wild Bear", 1)
    blocker.blocking = 99
    card = _give_dark_endurance(state, 0)
    casts = [a for a in legal_actions(state, 0) if isinstance(a, CastSpell)]
    assert any(a.card_id == card.id for a in casts), (
        "With a blocker on the field, the {1}-less discount should "
        "make Dark Endurance affordable at one swamp."
    )


def test_legal_actions_skips_cast_when_full_cost_unaffordable_and_no_blocker():
    state = _new_state(p0_lands=1)  # only ONE swamp, full cost is 2
    # Battlefield has a creature but it's NOT blocking — no discount.
    _put_creature(state, "Wild Bear", 1)
    card = _give_dark_endurance(state, 0)
    casts = [
        a for a in legal_actions(state, 0)
        if isinstance(a, CastSpell) and a.card_id == card.id
    ]
    assert not casts, (
        "Without a blocker on the field, the discount is unavailable "
        "and {1}{B} is unpayable from a single swamp."
    )


def test_legal_actions_exposes_cast_at_full_cost_when_no_blocker():
    state = _new_state(p0_lands=2)  # full cost payable
    _put_creature(state, "Wild Bear", 1)  # not blocking
    card = _give_dark_endurance(state, 0)
    casts = [
        a for a in legal_actions(state, 0)
        if isinstance(a, CastSpell) and a.card_id == card.id
    ]
    assert casts, "Spell should be castable at full cost regardless of blockers."
