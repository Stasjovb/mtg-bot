"""Tests for the first Stellar Sights restoration batch: utility
lands with straightforward activated abilities (Strip Mine,
Terrain Generator, Petrified Field, Ancient Tomb, Grove of the
Burnwillows, Mana Confluence)."""

from mtg_bot import legal_moves
from mtg_bot.actions import (
    ActivateAbility, apply_action, auto_tap_for_cost, can_pay_cost,
    drain_stack,
    resolve_top_of_stack,
)
from mtg_bot.agents import Agent, RandomAgent
from mtg_bot.cards import BASIC_LANDS, STELLAR_SIGHTS_LANDS, parse_mana_cost
from mtg_bot.effects import (
    DealDamageToControllerAndAddMana,
    DestroyTargetLand,
    GrantLifeToEachOpponent,
    PutBasicLandFromHandOntoBattlefieldTapped,
    ReturnTargetLandFromGraveyardToHand,
)
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.turn import Step


class _PickFirstAgent(Agent):
    def choose_target(self, state, player_id, legal_targets):
        return legal_targets[0] if legal_targets else None

    def choose_sacrifice(self, state, player_id, legal_ids):
        return legal_ids[0] if legal_ids else None


def _new_state():
    state = GameState()
    state.players.append(Player(id=0, agent=_PickFirstAgent()))
    state.players.append(Player(id=1, agent=_PickFirstAgent()))
    state.active_player_idx = 0
    state.priority_player_idx = 0
    state.step = Step.PRECOMBAT_MAIN
    return state


def _put(state, printing, owner_id=0):
    obj = state.new_object(printing, owner_id, Zone.BATTLEFIELD)
    state.battlefield.append(obj)
    return obj


# -----------------------
# Ancient Tomb
# -----------------------


def test_ancient_tomb_mana_ability_adds_cc_and_damages_controller():
    state = _new_state()
    tomb = _put(state, STELLAR_SIGHTS_LANDS["Ancient Tomb"])
    apply_action(state, 0, ActivateAbility(source_id=tomb.id, ability_index=0))
    # 2 damage to controller; 2 colorless in pool.
    assert state.players[0].life == 18
    assert len(state.players[0].mana_pool) == 2
    assert all(c.color == "C" for c in state.players[0].mana_pool)
    assert tomb.tapped


def test_ancient_tomb_effect_describe():
    e = DealDamageToControllerAndAddMana(damage=2, produces=(("C", 2),))
    d = e.describe()
    assert "damage" in d and "{C}{C}" in d


# -----------------------
# Mana Confluence
# -----------------------


def test_mana_confluence_pay_life_for_any_color():
    state = _new_state()
    conf = _put(state, STELLAR_SIGHTS_LANDS["Mana Confluence"])
    apply_action(state, 0, ActivateAbility(source_id=conf.id, ability_index=0))
    assert state.players[0].life == 19
    assert len(state.players[0].mana_pool) == 1
    assert state.players[0].mana_pool[0].color == "any"


def test_mana_confluence_not_legal_when_would_kill_you():
    state = _new_state()
    conf = _put(state, STELLAR_SIGHTS_LANDS["Mana Confluence"])
    state.players[0].life = 1  # paying 1 would reduce to 0
    actions = legal_moves(state)
    assert not any(
        isinstance(a, ActivateAbility) and a.source_id == conf.id
        for a in actions
    )


# -----------------------
# Grove of the Burnwillows
# -----------------------


def test_grove_of_the_burnwillows_produces_c_r_and_g():
    """Oracle has TWO mana abilities — {T}: Add {C} and {T}: Add {R} or
    {G}. Both colors plus C are advertised in ``produces``."""
    g = STELLAR_SIGHTS_LANDS["Grove of the Burnwillows"]
    assert g.produces == frozenset({"C", "R", "G"})


def test_grove_colored_activation_grants_life_to_each_opponent():
    """Activating the {T}: Add {R} or {G} mana ability resolves the
    bundled GrantLifeToEachOpponent(amount=1) rider — each opponent
    gains 1, controller's life unchanged."""
    state = _new_state()
    grove = _put(state, STELLAR_SIGHTS_LANDS["Grove of the Burnwillows"])
    # ability_index=1 is the colored mana ability with the rider.
    apply_action(
        state, 0, ActivateAbility(source_id=grove.id, ability_index=1),
    )
    drain_stack(state)
    assert grove.tapped
    assert state.players[1].life == 21
    assert state.players[0].life == 20


def test_grove_colorless_activation_does_not_grant_life():
    """Activating the {T}: Add {C} ability has NO lifegain rider —
    opponents stay at base life. Audit fix: previously the impl fired
    lifegain on every tap (becomes_tapped trigger), which over-fired
    on the {C} ability."""
    state = _new_state()
    grove = _put(state, STELLAR_SIGHTS_LANDS["Grove of the Burnwillows"])
    # ability_index=0 is the {T}: Add {C} mana ability (no rider).
    apply_action(
        state, 0, ActivateAbility(source_id=grove.id, ability_index=0),
    )
    drain_stack(state)
    assert grove.tapped
    assert state.players[1].life == 20  # NO lifegain
    assert state.players[0].life == 20


def test_grant_life_effect_describe():
    assert "each opponent" in GrantLifeToEachOpponent(amount=2).describe()


# -----------------------
# Strip Mine
# -----------------------


def test_strip_mine_destroys_target_land():
    state = _new_state()
    strip = _put(state, STELLAR_SIGHTS_LANDS["Strip Mine"])
    victim = _put(state, BASIC_LANDS["Forest"], owner_id=1)
    apply_action(
        state, 0, ActivateAbility(source_id=strip.id, ability_index=0),
    )
    while state.stack:
        resolve_top_of_stack(state)
    assert strip not in state.battlefield
    assert victim not in state.battlefield


def test_destroy_target_land_effect_legal_targets_lands_only():
    state = _new_state()
    land = _put(state, BASIC_LANDS["Forest"])
    from mtg_bot.cards import SYNTHETIC_CREATURES
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"])
    legal = DestroyTargetLand().legal_targets(state, 0)
    ids = {tid for _, tid in legal}
    assert land.id in ids
    assert bear.id not in ids


def test_destroy_target_land_nonbasic_only_variant():
    state = _new_state()
    basic = _put(state, BASIC_LANDS["Forest"])
    nonbasic = _put(state, STELLAR_SIGHTS_LANDS["Strip Mine"])
    legal = DestroyTargetLand(nonbasic_only=True).legal_targets(state, 0)
    ids = {tid for _, tid in legal}
    assert nonbasic.id in ids
    assert basic.id not in ids


# -----------------------
# Terrain Generator
# -----------------------


def test_terrain_generator_puts_basic_land_tapped():
    state = _new_state()
    tg = _put(state, STELLAR_SIGHTS_LANDS["Terrain Generator"])
    # Mana for {2}.
    for _ in range(2):
        _put(state, BASIC_LANDS["Mountain"])
    forest = state.new_object(BASIC_LANDS["Forest"], 0, Zone.HAND)
    state.players[0].hand.append(forest)
    apply_action(
        state, 0, ActivateAbility(source_id=tg.id, ability_index=0),
    )
    while state.stack:
        resolve_top_of_stack(state)
    assert forest in state.battlefield
    assert forest.tapped


def test_terrain_generator_no_basic_in_hand_is_noop():
    state = _new_state()
    PutBasicLandFromHandOntoBattlefieldTapped().resolve(state, 0, ())
    # No basics, nothing happens — logs may show it.


# -----------------------
# Petrified Field
# -----------------------


def test_petrified_field_returns_land_from_graveyard():
    state = _new_state()
    pf = _put(state, STELLAR_SIGHTS_LANDS["Petrified Field"])
    card = state.new_object(BASIC_LANDS["Forest"], 0, Zone.GRAVEYARD)
    state.players[0].graveyard.append(card)
    apply_action(
        state, 0, ActivateAbility(source_id=pf.id, ability_index=0),
    )
    while state.stack:
        resolve_top_of_stack(state)
    assert card in state.players[0].hand
    assert pf not in state.battlefield


def test_return_land_effect_legal_targets_lands_only():
    state = _new_state()
    land = state.new_object(BASIC_LANDS["Forest"], 0, Zone.GRAVEYARD)
    state.players[0].graveyard.append(land)
    from mtg_bot.cards import SYNTHETIC_CREATURES
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.GRAVEYARD,
    )
    state.players[0].graveyard.append(bear)
    legal = ReturnTargetLandFromGraveyardToHand().legal_targets(state, 0)
    ids = {tid for _, tid in legal}
    assert land.id in ids
    assert bear.id not in ids


def test_return_land_no_target_is_noop():
    state = _new_state()
    ReturnTargetLandFromGraveyardToHand().resolve(state, 0, ())


def test_return_land_wrong_kind_is_noop():
    state = _new_state()
    ReturnTargetLandFromGraveyardToHand().resolve(
        state, 0, (("creature", 1),),
    )


# -----------------------
# Registry progress marker
# -----------------------


def test_deal_damage_and_mana_with_no_source_still_runs():
    """DealDamageToControllerAndAddMana tolerates no resolving_source
    (defensive path): damage + pool fill happen, but the log message
    falls back to a generic 'land' label."""
    state = _new_state()
    DealDamageToControllerAndAddMana(
        damage=1, produces=(("C", 1),),
    ).resolve(state, 0, ())
    assert state.players[0].life == 19
    assert len(state.players[0].mana_pool) == 1


def test_pay_life_cost_skipped_when_not_required():
    """When pay_life is 0, the cost is not applied."""
    state = _new_state()
    life_before = state.players[0].life
    tg = _put(state, STELLAR_SIGHTS_LANDS["Terrain Generator"])
    # Mana for {2}.
    for _ in range(2):
        _put(state, BASIC_LANDS["Mountain"])
    forest = state.new_object(BASIC_LANDS["Forest"], 0, Zone.HAND)
    state.players[0].hand.append(forest)
    apply_action(
        state, 0, ActivateAbility(source_id=tg.id, ability_index=0),
    )
    while state.stack:
        resolve_top_of_stack(state)
    assert state.players[0].life == life_before


def test_grove_trigger_has_describe():
    e = GrantLifeToEachOpponent()
    assert "opponent" in e.describe()


def test_return_target_land_from_graveyard_describe():
    d = ReturnTargetLandFromGraveyardToHand().describe()
    assert "land" in d and "graveyard" in d


def test_put_basic_from_hand_describe():
    d = PutBasicLandFromHandOntoBattlefieldTapped().describe()
    assert "basic land" in d and "tapped" in d


def test_destroy_target_land_describe_variants():
    assert "nonbasic" in DestroyTargetLand(nonbasic_only=True).describe()
    assert "nonbasic" not in DestroyTargetLand().describe()


def test_six_cards_restored_no_longer_stand_ins():
    """The six cards restored in this batch must no longer be
    built via make_colorless_land — they have real abilities now."""
    import pathlib

    src = pathlib.Path("src/mtg_bot/cards/stellar_sights.py").read_text(
        encoding="utf-8"
    )
    restored = [
        "Ancient Tomb", "Mana Confluence", "Grove of the Burnwillows",
        "Petrified Field", "Strip Mine", "Terrain Generator",
    ]
    for name in restored:
        assert f'"{name}": make_colorless_land(' not in src, (
            f"{name} still a colorless-land stand-in"
        )
