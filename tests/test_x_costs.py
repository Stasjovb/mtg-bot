"""Tests for X-cost spells: cost parsing, cast-time X choice, effect
resolution that reads X from state, and the "enters with X +1/+1 counters"
replacement.
"""

from mtg_bot.actions import (
    CastSpell,
    _choose_and_apply_x,
    _x_upper_bound,
    apply_action,
    resolve_top_of_stack,
)
from mtg_bot.agents import Agent, RandomAgent
from mtg_bot.cards import BASIC_LANDS, SYNTHETIC_CREATURES, ManaCost, parse_mana_cost
from mtg_bot.game import GameState, Player, StackItem, Zone, effective_keywords

from mtg_bot.cards.source import get_active_source

_PRINTINGS = get_active_source().get_printings()


# -----------------------
# ManaCost + parse_mana_cost: x_pips
# -----------------------


def test_parse_mana_cost_tracks_x_pips():
    assert parse_mana_cost("{X}").x_pips == 1
    assert parse_mana_cost("{X}{X}{R}").x_pips == 2
    assert parse_mana_cost("{2}{G}").x_pips == 0


def test_mana_cost_x_pips_defaults_to_zero():
    """Hand-constructed ManaCost (no x_pips argument) reads as 0."""
    c = ManaCost(generic=2, colored=(("G", 1),))
    assert c.x_pips == 0


# -----------------------
# RandomAgent.choose_x
# -----------------------


def test_random_agent_choose_x_returns_upper_bound():
    agent = RandomAgent()
    assert agent.choose_x(state=None, player_id=0, card_name="foo", upper_bound=4) == 4


def test_random_agent_choose_x_zero_when_no_mana():
    agent = RandomAgent()
    assert agent.choose_x(state=None, player_id=0, card_name="foo", upper_bound=0) == 0


# -----------------------
# _x_upper_bound + _choose_and_apply_x helpers
# -----------------------


def _state_with_lands(num_swamps: int = 0, num_forests: int = 0, num_plains: int = 0, agent=None):
    state = GameState()
    p = Player(id=0, agent=agent or RandomAgent())
    state.players.append(p)
    for _ in range(num_swamps):
        swamp = state.new_object(BASIC_LANDS["Swamp"], 0, Zone.BATTLEFIELD)
        state.battlefield.append(swamp)
    for _ in range(num_forests):
        forest = state.new_object(BASIC_LANDS["Forest"], 0, Zone.BATTLEFIELD)
        state.battlefield.append(forest)
    for _ in range(num_plains):
        plains = state.new_object(BASIC_LANDS["Plains"], 0, Zone.BATTLEFIELD)
        state.battlefield.append(plains)
    return state


def test_x_upper_bound_counts_available_generic():
    # 5 swamps; {X}{B} → 1 swamp for B, remaining 4 for X.
    state = _state_with_lands(num_swamps=5)
    assert _x_upper_bound(state, 0, parse_mana_cost("{X}{B}")) == 4


def test_x_upper_bound_with_double_x_pip():
    # 5 swamps + 1 forest for R... but {X}{X}{R} → can we pay?
    # 3 swamps + 1 mountain? Instead use 5 mountains.
    state = GameState()
    p = Player(id=0, agent=RandomAgent())
    state.players.append(p)
    for _ in range(5):
        m = state.new_object(BASIC_LANDS["Mountain"], 0, Zone.BATTLEFIELD)
        state.battlefield.append(m)
    # {X}{X}{R} with 5 mountains: 1 pays R, 4 left for 2X → X=2.
    assert _x_upper_bound(state, 0, parse_mana_cost("{X}{X}{R}")) == 2


def test_x_upper_bound_zero_when_base_cost_unpayable():
    # No lands at all — X=0 is still the answer (since the probe tests
    # X+1 ≥ 1, which fails for any spell with a non-zero base colored cost).
    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    assert _x_upper_bound(state, 0, parse_mana_cost("{X}{B}")) == 0


def test_choose_and_apply_x_clamps_to_upper_bound():
    """Agent returning more than available is clamped."""
    class GreedyAgent(Agent):
        def choose_x(self, state, player_id, card_name, upper_bound):
            return 99

    state = _state_with_lands(num_swamps=3, agent=GreedyAgent())
    card = state.new_object(_PRINTINGS["Zero Point Ballad"], 0, Zone.HAND)
    chosen = _choose_and_apply_x(state, 0, card, parse_mana_cost("{X}{B}"))
    assert chosen == 2  # 3 swamps: 1 for B, 2 for X


def test_choose_and_apply_x_clamps_negative_to_zero():
    class PessimistAgent(Agent):
        def choose_x(self, state, player_id, card_name, upper_bound):
            return -5

    state = _state_with_lands(num_swamps=3, agent=PessimistAgent())
    card = state.new_object(_PRINTINGS["Zero Point Ballad"], 0, Zone.HAND)
    chosen = _choose_and_apply_x(state, 0, card, parse_mana_cost("{X}{B}"))
    assert chosen == 0


# -----------------------
# End-to-end cast flow for X-cost spells
# -----------------------


def _cast_and_resolve(state, player_id, card):
    apply_action(state, player_id, CastSpell(card.id))
    resolve_top_of_stack(state)


def test_zero_point_ballad_destroys_small_creatures_loses_x_life():
    state = _state_with_lands(num_swamps=3)
    p = state.players[0]
    # Add opponent with a 1-toughness creature and a 3-toughness creature.
    p2 = Player(id=1, agent=RandomAgent())
    state.players.append(p2)
    weak = state.new_object(SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD)
    # Wild Bear is 2/2 — toughness 2 — should die at X=2.
    state.battlefield.append(weak)
    strong = state.new_object(SYNTHETIC_CREATURES["Spider Sentinel"], 1, Zone.BATTLEFIELD)
    # Spider Sentinel is 1/4 — toughness 4 — should survive at X=2.
    state.battlefield.append(strong)
    ballad = state.new_object(_PRINTINGS["Zero Point Ballad"], 0, Zone.HAND)
    p.hand.append(ballad)
    # RandomAgent returns upper_bound, which is 2 (3 swamps: 1 for B, 2 for X).
    _cast_and_resolve(state, 0, ballad)
    assert weak not in state.battlefield
    assert strong in state.battlefield
    assert p.life == 18  # lost X=2 life


def test_zero_point_ballad_x6_reanimates_creature():
    """With X=6, Zero Point Ballad destroys ≤6-toughness creatures AND
    returns a creature card put into a graveyard this way (from caster's
    graveyard) to the battlefield under their control."""
    state = _state_with_lands(num_swamps=7)  # enough for X=6 + {B}
    p = state.players[0]
    p.life = 30  # absorb 6 life loss without dying
    # Caster has one of their own creatures with toughness ≤ 6.
    bear = state.new_object(SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD)
    state.battlefield.append(bear)
    ballad = state.new_object(_PRINTINGS["Zero Point Ballad"], 0, Zone.HAND)
    p.hand.append(ballad)
    _cast_and_resolve(state, 0, ballad)
    # Bear was destroyed (left battlefield); under X≥6 clause it's returned.
    # The reanimated creature is the same card (same id), back on the bf.
    assert bear in state.battlefield
    assert bear.zone == Zone.BATTLEFIELD
    assert p.life == 24  # 30 - 6


def test_zero_point_ballad_x_below_6_leaves_creatures_in_graveyard():
    state = _state_with_lands(num_swamps=3)  # X=2
    p = state.players[0]
    bear = state.new_object(SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD)
    state.battlefield.append(bear)
    ballad = state.new_object(_PRINTINGS["Zero Point Ballad"], 0, Zone.HAND)
    p.hand.append(ballad)
    _cast_and_resolve(state, 0, ballad)
    assert bear not in state.battlefield
    assert bear in p.graveyard


def test_devastating_onslaught_creates_x_copies_with_haste_sac_at_end_step():
    from mtg_bot.turn import run_delayed_end_step_triggers

    state = _state_with_lands(num_plains=0, num_forests=0)
    # Build mountains for the payment (need 1 for R + 2X for X=2).
    p = state.players[0]
    for _ in range(5):
        m = state.new_object(BASIC_LANDS["Mountain"], 0, Zone.BATTLEFIELD)
        state.battlefield.append(m)
    # Put a creature to copy.
    original = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(original)
    onslaught = state.new_object(_PRINTINGS["Devastating Onslaught"], 0, Zone.HAND)
    p.hand.append(onslaught)
    # 5 mountains → 1 for R, 4 for 2X → X=2. 2 copies of Wild Bear.
    _cast_and_resolve(state, 0, onslaught)
    copies = [o for o in state.battlefield
              if o.printing.name == "Wild Bear" and o.id != original.id]
    assert len(copies) == 2
    # Copies have haste (so they can attack immediately despite summoning sick).
    for c in copies:
        assert "haste" in effective_keywords(state, c)
    # Delayed triggers scheduled to sac them at this turn's end step.
    assert len(state.delayed_triggers) == 2
    # Fire the end step — triggers go on the stack, then resolve.
    from mtg_bot.actions import resolve_top_of_stack
    run_delayed_end_step_triggers(state)
    assert len(state.stack) == 2
    while state.stack:
        resolve_top_of_stack(state)
    for c in copies:
        assert c not in state.battlefield


def test_broodguard_elite_enters_with_x_plus_one_counters():
    state = _state_with_lands(num_forests=5)
    p = state.players[0]
    broodguard = state.new_object(_PRINTINGS["Broodguard Elite"], 0, Zone.HAND)
    p.hand.append(broodguard)
    # 5 forests → 2 for {G}{G}, 3 left for X → X=3.
    _cast_and_resolve(state, 0, broodguard)
    assert broodguard in state.battlefield
    assert broodguard.plus_one_counters == 3


def test_dyadrine_enters_with_counters_equal_to_mana_spent():
    state = GameState()
    p = Player(id=0, agent=RandomAgent())
    state.players.append(p)
    # Dyadrine: {X}{G}{W}. Need a Forest + Plains + generic for X.
    # Use 3 Forests + 1 Plains. {G} = 1 forest, {W} = 1 plains, 2 left for X.
    # Except: Forests only make G and Plains only make W. So {X}{G}{W}:
    # 1 forest for G, 1 plains for W, 2 forests left for X. X=2.
    # Mana spent = X + 1 + 1 = 4, so 4 counters.
    for _ in range(3):
        f = state.new_object(BASIC_LANDS["Forest"], 0, Zone.BATTLEFIELD)
        state.battlefield.append(f)
    plains = state.new_object(BASIC_LANDS["Plains"], 0, Zone.BATTLEFIELD)
    state.battlefield.append(plains)
    dyadrine = state.new_object(
        _PRINTINGS["Dyadrine, Synthesis Amalgam"], 0, Zone.HAND
    )
    p.hand.append(dyadrine)
    _cast_and_resolve(state, 0, dyadrine)
    assert dyadrine in state.battlefield
    # X=2 (two free forests after paying G+W), generic=0, colored=(G:1, W:1).
    # mana_spent = 2 + 0 + 2 = 4.
    assert dyadrine.plus_one_counters == 4


def test_cast_spell_preserves_x_value_on_stack_item():
    state = _state_with_lands(num_swamps=4)
    p = state.players[0]
    ballad = state.new_object(_PRINTINGS["Zero Point Ballad"], 0, Zone.HAND)
    p.hand.append(ballad)
    apply_action(state, 0, CastSpell(ballad.id))
    item = state.stack[-1]
    # 4 swamps: 1 for B, 3 for X → X=3 chosen.
    assert item.x_value == 3
    assert isinstance(item, StackItem)


def test_resolving_x_value_reset_after_spell_resolution():
    state = _state_with_lands(num_swamps=3)
    p = state.players[0]
    ballad = state.new_object(_PRINTINGS["Zero Point Ballad"], 0, Zone.HAND)
    p.hand.append(ballad)
    _cast_and_resolve(state, 0, ballad)
    assert state.resolving_x_value == 0


def test_x_value_zero_for_nonx_spell():
    """Non-X spells end up with x_value=0 on the StackItem."""
    state = _state_with_lands(num_forests=2)
    p = state.players[0]
    bear = state.new_object(SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.HAND)
    p.hand.append(bear)
    apply_action(state, 0, CastSpell(bear.id))
    assert state.stack[-1].x_value == 0


def test_zero_point_ballad_x6_reanimation_fizzles_without_caster_victim():
    """X≥6 with nothing caster-owned dying: no reanimation, no error."""
    state = _state_with_lands(num_swamps=7)
    p = state.players[0]
    p.life = 30
    # Opponent controls the only dying creature.
    p2 = Player(id=1, agent=RandomAgent())
    state.players.append(p2)
    opp_bear = state.new_object(SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD)
    state.battlefield.append(opp_bear)
    ballad = state.new_object(_PRINTINGS["Zero Point Ballad"], 0, Zone.HAND)
    p.hand.append(ballad)
    _cast_and_resolve(state, 0, ballad)
    # Opponent's bear died to the graveyard; caster owns nothing from
    # this destruction, so nothing comes back.
    assert opp_bear not in state.battlefield
    assert opp_bear in p2.graveyard
    assert p.life == 24  # still lost X=6 life


def test_zero_point_ballad_describe():
    from mtg_bot.effects import ZeroPointBalladEffect
    text = ZeroPointBalladEffect().describe()
    assert "toughness X" in text
    assert "6" in text


def test_devastating_onslaught_describe():
    from mtg_bot.effects import (
        CreateXTokensOfTargetPermanentWithHasteEndStepSac,
    )
    text = CreateXTokensOfTargetPermanentWithHasteEndStepSac().describe()
    assert "X tokens" in text
    assert "haste" in text


def test_devastating_onslaught_x_zero_noop():
    """Casting Devastating Onslaught with no mana beyond {R} means X=0;
    the effect is a no-op (no tokens created)."""
    from mtg_bot.effects import (
        CreateXTokensOfTargetPermanentWithHasteEndStepSac,
    )
    state = GameState()
    p = Player(id=0, agent=RandomAgent())
    state.players.append(p)
    original = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(original)
    # Resolving with x_value=0: no tokens created.
    state.resolving_x_value = 0
    effect = CreateXTokensOfTargetPermanentWithHasteEndStepSac()
    effect.resolve(state, 0, (("permanent", original.id),))
    # Only the original exists.
    copies = [o for o in state.battlefield
              if o.printing.name == "Wild Bear" and o.id != original.id]
    assert copies == []


def test_devastating_onslaught_no_target_returns_early():
    from mtg_bot.effects import (
        CreateXTokensOfTargetPermanentWithHasteEndStepSac,
    )
    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    state.resolving_x_value = 2
    effect = CreateXTokensOfTargetPermanentWithHasteEndStepSac()
    # No targets — no-op, no crash.
    effect.resolve(state, 0, ())


def test_devastating_onslaught_target_missing_returns_early():
    from mtg_bot.effects import (
        CreateXTokensOfTargetPermanentWithHasteEndStepSac,
    )
    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    state.resolving_x_value = 2
    effect = CreateXTokensOfTargetPermanentWithHasteEndStepSac()
    # Target id 999 doesn't exist on battlefield — no crash.
    effect.resolve(state, 0, (("permanent", 999),))


def test_choose_and_apply_x_no_agent_uses_zero():
    """Defensive: if a player has no agent, _choose_and_apply_x defaults X=0."""
    state = GameState()
    p = Player(id=0, agent=None)
    state.players.append(p)
    for _ in range(3):
        s = state.new_object(BASIC_LANDS["Swamp"], 0, Zone.BATTLEFIELD)
        state.battlefield.append(s)
    card = state.new_object(_PRINTINGS["Zero Point Ballad"], 0, Zone.HAND)
    assert _choose_and_apply_x(state, 0, card, parse_mana_cost("{X}{B}")) == 0


def test_devastating_onslaught_legal_targets():
    """Legal targets are artifacts + creatures controlled by the caster."""
    from mtg_bot.effects import (
        CreateXTokensOfTargetPermanentWithHasteEndStepSac,
    )
    state = GameState()
    p = Player(id=0, agent=RandomAgent())
    p2 = Player(id=1, agent=RandomAgent())
    state.players.append(p)
    state.players.append(p2)
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear)
    opp_bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(opp_bear)
    effect = CreateXTokensOfTargetPermanentWithHasteEndStepSac()
    legal = effect.legal_targets(state, 0)
    # Only the caster's bear is a legal target.
    assert legal == [("permanent", bear.id)]
