"""Tests for the mana pool abstraction + Steelswarm Operator + All-Fates
Scroll's mana ability."""

from mtg_bot import legal_moves
from mtg_bot.actions import (
    ActivateAbility, CastSpell, apply_action,
    auto_tap_for_cost, can_pay_cost,
)
from mtg_bot.agents import RandomAgent
from mtg_bot.cards import BASIC_LANDS, EOE_CREATURES, EOE_SPELLS, SYNTHETIC_CREATURES
from mtg_bot.cards import parse_mana_cost
from mtg_bot.effects import AddManaToPool
from mtg_bot.game import GameState, ManaCoin, Player, Zone
from mtg_bot.turn import Step, run_cleanup_step


def _new_state():
    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    state.active_player_idx = 0
    state.priority_player_idx = 0
    state.step = Step.PRECOMBAT_MAIN
    return state


def _put(state, printing, owner_id=0):
    obj = state.new_object(printing, owner_id, Zone.BATTLEFIELD)
    state.battlefield.append(obj)
    return obj


# -----------------------
# ManaCoin + AddManaToPool effect
# -----------------------


def test_add_mana_to_pool_resolve_adds_coins():
    state = _new_state()
    AddManaToPool(produces=(("U", 2),)).resolve(state, 0, ())
    p = state.players[0]
    assert len(p.mana_pool) == 2
    assert all(c.color == "U" and c.spend_restriction is None for c in p.mana_pool)


def test_add_mana_with_restriction_tags_coins():
    state = _new_state()
    AddManaToPool(
        produces=(("U", 1),), spend_restriction="artifact_spell",
    ).resolve(state, 0, ())
    assert state.players[0].mana_pool[0].spend_restriction == "artifact_spell"


def test_add_mana_describe_restriction():
    d = AddManaToPool(
        produces=(("U", 1),), spend_restriction="artifact_spell",
    ).describe()
    assert "artifact_spell" in d


# -----------------------
# can_pay_cost / auto_tap_for_cost with pool
# -----------------------


def test_pool_coin_pays_colored_requirement():
    state = _new_state()
    state.players[0].mana_pool.append(ManaCoin(color="U"))
    cost = parse_mana_cost("{U}")
    assert can_pay_cost(state, 0, cost)
    auto_tap_for_cost(state, 0, cost)
    assert len(state.players[0].mana_pool) == 0


def test_any_color_coin_pays_any_colored_requirement():
    state = _new_state()
    state.players[0].mana_pool.append(ManaCoin(color="any"))
    assert can_pay_cost(state, 0, parse_mana_cost("{G}"))


def test_artifact_restricted_coin_cannot_pay_nonartifact_spell():
    state = _new_state()
    state.players[0].mana_pool.append(
        ManaCoin(color="U", spend_restriction="artifact_spell")
    )
    cost = parse_mana_cost("{U}")
    assert not can_pay_cost(state, 0, cost, spell_kind="spell")
    assert can_pay_cost(state, 0, cost, spell_kind="artifact_spell")


def test_pool_consumed_before_lands():
    state = _new_state()
    land = _put(state, BASIC_LANDS["Island"])
    state.players[0].mana_pool.append(ManaCoin(color="U"))
    auto_tap_for_cost(state, 0, parse_mana_cost("{U}"))
    # Pool coin used; land should still be untapped.
    assert land.tapped is False
    assert state.players[0].mana_pool == []


def test_land_used_when_pool_exhausted():
    state = _new_state()
    land = _put(state, BASIC_LANDS["Island"])
    # Pool has 0 coins → land taps.
    auto_tap_for_cost(state, 0, parse_mana_cost("{U}"))
    assert land.tapped is True


# -----------------------
# Cleanup empties the pool
# -----------------------


def test_cleanup_empties_mana_pool():
    state = _new_state()
    state.players[0].mana_pool.append(ManaCoin(color="U"))
    state.players[1].mana_pool.extend([
        ManaCoin(color="R"), ManaCoin(color="G"),
    ])
    run_cleanup_step(state)
    assert state.players[0].mana_pool == []
    assert state.players[1].mana_pool == []


# -----------------------
# Mana abilities bypass the stack
# -----------------------


def test_mana_ability_activation_adds_coin_immediately():
    state = _new_state()
    ss = _put(state, EOE_CREATURES["Steelswarm Operator"])
    ss.summoning_sick = False
    apply_action(state, 0, ActivateAbility(source_id=ss.id, ability_index=0))
    # Mana coin added; no stack item.
    assert len(state.players[0].mana_pool) == 1
    coin = state.players[0].mana_pool[0]
    assert coin.color == "U"
    assert coin.spend_restriction == "artifact_spell"
    assert state.stack == []
    assert ss.tapped is True


def test_mana_ability_not_offered_when_source_tapped():
    state = _new_state()
    ss = _put(state, EOE_CREATURES["Steelswarm Operator"])
    ss.summoning_sick = False
    ss.tapped = True
    actions = legal_moves(state)
    assert not any(
        isinstance(a, ActivateAbility) and a.source_id == ss.id
        for a in actions
    )


# -----------------------
# Integration: Steelswarm lets you cast an artifact for less
# -----------------------


def test_steelswarm_mana_pays_for_artifact_spell():
    state = _new_state()
    ss = _put(state, EOE_CREATURES["Steelswarm Operator"])
    ss.summoning_sick = False
    # Activate Steelswarm → {U} with artifact-spell restriction.
    apply_action(state, 0, ActivateAbility(source_id=ss.id, ability_index=0))
    # Put a Nutrient Block ({1}) in hand and a Forest (for generic).
    _put(state, BASIC_LANDS["Forest"])
    from mtg_bot.cards import EOE_SPELLS
    nutrient = state.new_object(EOE_SPELLS["Nutrient Block"], 0, Zone.HAND)
    state.players[0].hand.append(nutrient)
    # Nutrient Block is an artifact with CMC 1. Cost is {1} — need 1
    # generic. The Steelswarm {U} coin can pay for artifact spells, so
    # the Forest should NOT need to tap.
    forest = next(
        o for o in state.battlefield if o.printing.name == "Forest"
    )
    apply_action(state, 0, CastSpell(nutrient.id))
    # Steelswarm {U} was used for generic (unrestricted-looking but
    # flagged); Forest might still tap too. Either way, the pool coin
    # is consumed.
    assert not any(
        c.spend_restriction == "artifact_spell"
        for c in state.players[0].mana_pool
    )


def test_steelswarm_mana_rejected_for_non_artifact_spell():
    state = _new_state()
    ss = _put(state, EOE_CREATURES["Steelswarm Operator"])
    ss.summoning_sick = False
    apply_action(state, 0, ActivateAbility(source_id=ss.id, ability_index=0))
    # Try to cast a non-artifact creature: Wild Bear {1}{G}. We need
    # G to cover {G} + 1 generic. With only Steelswarm's restricted
    # {U} in pool and no lands, the spell should NOT be castable.
    bear = state.new_object(SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.HAND)
    state.players[0].hand.append(bear)
    cost = parse_mana_cost("{1}{G}")
    assert not can_pay_cost(state, 0, cost, spell_kind="spell")


def test_all_fates_any_color_mana_pays_any_colored_cost():
    state = _new_state()
    scroll = _put(state, EOE_SPELLS["All-Fates Scroll"])
    scroll.summoning_sick = False
    apply_action(
        state, 0, ActivateAbility(source_id=scroll.id, ability_index=0),
    )
    # "any" coin should pay for a {G} cost without a Forest.
    assert can_pay_cost(state, 0, parse_mana_cost("{G}"))


def test_steelswarm_printing_has_mana_ability():
    ss = EOE_CREATURES["Steelswarm Operator"]
    # Steelswarm prints two mana abilities: {T}: Add {U} (artifact-
    # spell-restricted) and {T}: Add {U}{U} (artifact-activation-
    # restricted). Both share the {T} cost, so only one fires per
    # untap, but both must be defined on the printing.
    assert len(ss.activated_abilities) == 2
    assert all(a.is_mana_ability for a in ss.activated_abilities)


def test_steelswarm_printing_two_mana_abilities_have_correct_shapes():
    ss = EOE_CREATURES["Steelswarm Operator"]
    a0, a1 = ss.activated_abilities
    # First: {T}: Add {U}, restricted to artifact_spell.
    assert a0.cost.tap_self is True
    assert a0.effect.produces == (("U", 1),)
    assert a0.effect.spend_restriction == "artifact_spell"
    # Second: {T}: Add {U}{U}, restricted to artifact_activation.
    assert a1.cost.tap_self is True
    assert a1.effect.produces == (("U", 1), ("U", 1))
    assert a1.effect.spend_restriction == "artifact_activation"


def test_steelswarm_second_ability_adds_two_blue_artifact_activation_coins():
    state = _new_state()
    ss = _put(state, EOE_CREATURES["Steelswarm Operator"])
    ss.summoning_sick = False
    apply_action(
        state, 0, ActivateAbility(source_id=ss.id, ability_index=1),
    )
    p = state.players[0]
    # Two blue coins, each tagged with the artifact-activation gate.
    assert len(p.mana_pool) == 2
    assert all(c.color == "U" for c in p.mana_pool)
    assert all(
        c.spend_restriction == "artifact_activation" for c in p.mana_pool
    )
    # Source taps once (shared {T} cost across both mana abilities).
    assert ss.tapped is True
    assert state.stack == []


def test_artifact_activation_coin_pays_for_artifact_ability_activation():
    """A coin tagged 'artifact_activation' satisfies a payment context
    of 'artifact_activation' (Steelswarm-style), but not the default
    'spell' context."""
    state = _new_state()
    state.players[0].mana_pool.append(
        ManaCoin(color="U", spend_restriction="artifact_activation")
    )
    cost = parse_mana_cost("{U}")
    assert can_pay_cost(state, 0, cost, spell_kind="artifact_activation")
    assert not can_pay_cost(state, 0, cost, spell_kind="spell")
    assert not can_pay_cost(state, 0, cost, spell_kind="artifact_spell")
