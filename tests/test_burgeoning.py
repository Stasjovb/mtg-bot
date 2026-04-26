"""Tests for Burgeoning ({G}) — Special Guests enchantment.

Oracle: Whenever an opponent plays a land, you may put a land card
from your hand onto the battlefield.
"""

from mtg_bot.actions import PlayLand, apply_action, drain_stack
from mtg_bot.agents import Agent, RandomAgent
from mtg_bot.cards import BASIC_LANDS, SPECIAL_GUESTS_EOE
from mtg_bot.effects import (
    OptionalPutLandFromHandOntoBattlefield,
    TriggeredAbility,
)
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.turn import fire_opponent_plays_land_triggers


class _PickFirst(Agent):
    """Always accepts optional effects and picks the first option."""

    def choose_card_from_library(self, state, player_id, option_ids):
        return option_ids[0] if option_ids else None


class _Declines(Agent):
    """Declines any optional card pick."""

    def choose_card_from_library(self, state, player_id, option_ids):
        return None


def _new_state(p0_agent=None, p1_agent=None):
    state = GameState()
    state.players.append(
        Player(id=0, agent=p0_agent or RandomAgent())
    )
    state.players.append(
        Player(id=1, agent=p1_agent or RandomAgent())
    )
    return state


def _give_burgeoning(state: GameState, controller_id: int):
    obj = state.new_object(
        SPECIAL_GUESTS_EOE["Burgeoning"], controller_id, Zone.BATTLEFIELD,
    )
    state.battlefield.append(obj)
    return obj


def _give_land_in_hand(state: GameState, player_id: int, land_name: str):
    p = state.player_by_id(player_id)
    land = state.new_object(BASIC_LANDS[land_name], player_id, Zone.HAND)
    p.hand.append(land)
    return land


def test_burgeoning_is_wired_up():
    card = SPECIAL_GUESTS_EOE["Burgeoning"]
    assert card.mana_cost_str == "{G}"
    assert "Enchantment" in card.card_types
    assert len(card.triggered_abilities) == 1
    trig = card.triggered_abilities[0]
    assert trig.trigger == "opponent_plays_land"
    assert isinstance(trig.effect, OptionalPutLandFromHandOntoBattlefield)


def test_opponent_plays_land_fires_burgeoning_under_controller():
    """Player 0 owns Burgeoning; Player 1 plays a land; Player 0 is
    prompted to drop a Forest from hand."""
    state = _new_state(p0_agent=_PickFirst())
    _give_burgeoning(state, controller_id=0)
    forest = _give_land_in_hand(state, 0, "Forest")

    # Simulate the firing that actions.play_land would trigger.
    fire_opponent_plays_land_triggers(state, land_controller_id=1)
    drain_stack(state)

    # Forest should now be on the battlefield under P0's control.
    assert forest in state.battlefield
    assert forest.controller_id == 0
    assert forest.zone == Zone.BATTLEFIELD
    assert forest.tapped is False  # basic lands enter untapped


def test_burgeoning_controller_own_land_drop_does_not_trigger():
    """Only OPPONENT land-plays trigger Burgeoning — the controller's
    own lands don't."""
    state = _new_state(p0_agent=_PickFirst())
    _give_burgeoning(state, controller_id=0)
    forest = _give_land_in_hand(state, 0, "Forest")

    # P0 plays a land themselves — Burgeoning shouldn't fire for P0.
    fire_opponent_plays_land_triggers(state, land_controller_id=0)
    drain_stack(state)

    assert forest not in state.battlefield
    assert forest.zone == Zone.HAND


def test_agent_declining_is_legal():
    """Agent returning None to the may-clause leaves hand untouched."""
    state = _new_state(p0_agent=_Declines())
    _give_burgeoning(state, controller_id=0)
    forest = _give_land_in_hand(state, 0, "Forest")

    fire_opponent_plays_land_triggers(state, land_controller_id=1)
    drain_stack(state)

    assert forest in state.player_by_id(0).hand
    assert forest not in state.battlefield


def test_no_lands_in_hand_does_nothing():
    """Trigger fires but the effect silently does nothing when the
    controller has no land cards in hand."""
    state = _new_state(p0_agent=_PickFirst())
    _give_burgeoning(state, controller_id=0)

    fire_opponent_plays_land_triggers(state, land_controller_id=1)
    drain_stack(state)

    assert not any(o.printing.is_land for o in state.battlefield)


def test_play_land_integrates_with_burgeoning():
    """End-to-end: an opponent's actual land play via PlayLand should
    trigger Burgeoning."""
    state = _new_state(p0_agent=_PickFirst(), p1_agent=RandomAgent())
    state.active_player_idx = 1  # P1's turn
    _give_burgeoning(state, controller_id=0)
    p1 = state.player_by_id(1)
    p1_forest = state.new_object(BASIC_LANDS["Forest"], 1, Zone.HAND)
    p1.hand.append(p1_forest)
    p0_forest = _give_land_in_hand(state, 0, "Forest")

    apply_action(state, 1, PlayLand(card_id=p1_forest.id))
    drain_stack(state)

    # P1's land played normally.
    assert p1_forest in state.battlefield
    assert p1_forest.controller_id == 1
    # Burgeoning dropped P0's forest too.
    assert p0_forest in state.battlefield
    assert p0_forest.controller_id == 0


def test_burgeoning_dropped_land_fires_landfall():
    """When Burgeoning puts a land onto the battlefield, landfall
    triggers on the controller's other permanents still fire."""
    # Craft a "landfall watcher" Enchantment using our plumbing: we
    # reuse the existing landfall trigger machinery — the simplest
    # probe is to check that a tap-counter sentinel flips when a
    # landfall-listening creature is in play. We use PutBasicLand-like
    # observers through the existing test harness by importing an
    # EoE creature that has a landfall trigger.
    from mtg_bot.cards import EOE_CREATURES

    landfaller = next(
        (p for p in EOE_CREATURES.values()
         if any(t.trigger == "landfall" for t in p.triggered_abilities)),
        None,
    )
    if landfaller is None:
        # No landfall creature in the pool — skip this integration
        # assertion; fire_landfall_triggers itself is already covered
        # by other tests.
        return

    state = _new_state(p0_agent=_PickFirst())
    _give_burgeoning(state, controller_id=0)
    watcher = state.new_object(landfaller, 0, Zone.BATTLEFIELD)
    state.battlefield.append(watcher)
    _give_land_in_hand(state, 0, "Forest")

    log_before = len(state.log)
    fire_opponent_plays_land_triggers(state, land_controller_id=1)
    drain_stack(state)
    new_log = state.log[log_before:]
    # Landfall should have fired — check for its message pattern.
    assert any("landfall" in line.lower() for line in new_log), new_log


def test_burgeoning_dropped_land_does_not_re_fire_opponent_plays_land():
    """Defensive: Burgeoning's effect calls fire_landfall_triggers, NOT
    fire_opponent_plays_land_triggers. With two Burgeonings (one per
    player) the chain should not recurse infinitely."""
    state = _new_state(p0_agent=_PickFirst(), p1_agent=_PickFirst())
    _give_burgeoning(state, controller_id=0)
    _give_burgeoning(state, controller_id=1)
    _give_land_in_hand(state, 0, "Forest")
    _give_land_in_hand(state, 1, "Forest")

    # P1 plays a land (externally) — should fire Burgeoning for P0,
    # which drops a Forest. That drop must NOT re-fire for P1's
    # Burgeoning.
    fire_opponent_plays_land_triggers(state, land_controller_id=1)
    drain_stack(state)

    # P0's Forest dropped. P1's Forest stayed in hand (no recursive
    # re-fire).
    p1 = state.player_by_id(1)
    assert any(o.controller_id == 0 and o.printing.name == "Forest"
               for o in state.battlefield)
    assert any(c.printing.name == "Forest" for c in p1.hand)


def test_trigger_description_lists_opponent_plays_land():
    trig = SPECIAL_GUESTS_EOE["Burgeoning"].triggered_abilities[0]
    desc = trig.describe()
    assert "opponent plays a land" in desc.lower()


def test_effect_describe_mentions_hand():
    eff = OptionalPutLandFromHandOntoBattlefield()
    desc = eff.describe()
    assert "land" in desc
    assert "hand" in desc


def test_effect_with_agent_none_does_nothing():
    """Belt-and-suspenders: if the controlling player has no agent, the
    optional effect silently skips (no crash, no hand change)."""
    state = _new_state()
    state.players[0] = Player(id=0, agent=None)
    forest = _give_land_in_hand(state, 0, "Forest")
    OptionalPutLandFromHandOntoBattlefield().resolve(state, 0, ())
    assert forest in state.player_by_id(0).hand


# ---------------------------------------------------------------------------
# Audit regressions: pin the "Burgeoning-put land fires landfall but does
# NOT re-fire the opponent-plays-land chain" rule with a deterministic
# landfall watcher (Remnant Elemental, +2/+0 until end of turn on landfall).
# These complement the conditional skip in
# test_burgeoning_dropped_land_fires_landfall above by guaranteeing a
# concrete observable assertion regardless of whether EOE_CREATURES still
# happens to contain a landfall card.
# ---------------------------------------------------------------------------


def test_burgeoning_dropped_land_fires_landfall_observable():
    """Audit: when Burgeoning's effect resolves, the dropped land *must*
    fire landfall on existing landfall watchers. We pin this with
    Remnant Elemental's +2/+0 landfall pump — observable on
    ``temp_power_bonus``."""
    from mtg_bot.cards import EOE_CREATURES

    state = _new_state(p0_agent=_PickFirst())
    _give_burgeoning(state, controller_id=0)
    elem = state.new_object(
        EOE_CREATURES["Remnant Elemental"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(elem)
    _give_land_in_hand(state, 0, "Forest")

    # Sanity: nothing has pumped the watcher yet.
    assert elem.temp_power_bonus == 0

    fire_opponent_plays_land_triggers(state, land_controller_id=1)
    drain_stack(state)

    # Burgeoning dropped P0's Forest -> landfall fired -> +2/+0.
    assert elem.temp_power_bonus == 2


def test_burgeoning_drop_does_not_double_fire_landfall():
    """Audit: Burgeoning's dropped land must fire landfall *exactly
    once*. Regression guard against accidentally calling
    fire_landfall_triggers twice (once from the effect, once from a
    cascading opponent-plays-land path)."""
    from mtg_bot.cards import EOE_CREATURES

    state = _new_state(p0_agent=_PickFirst())
    _give_burgeoning(state, controller_id=0)
    elem = state.new_object(
        EOE_CREATURES["Remnant Elemental"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(elem)
    _give_land_in_hand(state, 0, "Forest")

    fire_opponent_plays_land_triggers(state, land_controller_id=1)
    drain_stack(state)

    # +2 (one fire), not +4 (double fire).
    assert elem.temp_power_bonus == 2


def test_burgeoning_chain_terminates_with_mutual_burgeonings():
    """Audit: stress the no-chain rule with two Burgeonings (one per
    side) and a land in each player's hand. P1 plays one land via
    actions.play_land; the resulting cascade must terminate cleanly
    with exactly one Burgeoning-drop on P0's side and zero on P1's
    side (P0's drop is a *put*, not a *play*, so it does not re-trigger
    P1's Burgeoning)."""
    state = _new_state(p0_agent=_PickFirst(), p1_agent=_PickFirst())
    state.active_player_idx = 1
    _give_burgeoning(state, controller_id=0)
    _give_burgeoning(state, controller_id=1)
    p1 = state.player_by_id(1)
    p1_forest = state.new_object(BASIC_LANDS["Forest"], 1, Zone.HAND)
    p1.hand.append(p1_forest)
    _give_land_in_hand(state, 0, "Forest")
    p0_extra = _give_land_in_hand(state, 0, "Plains")
    p1_extra = state.new_object(BASIC_LANDS["Plains"], 1, Zone.HAND)
    p1.hand.append(p1_extra)

    apply_action(state, 1, PlayLand(card_id=p1_forest.id))
    drain_stack(state)

    # P1's actual play landed.
    assert p1_forest in state.battlefield
    # P0's Burgeoning fired and dropped exactly one land.
    p0_lands_on_bf = [
        o for o in state.battlefield
        if o.controller_id == 0 and o.printing.is_land
    ]
    assert len(p0_lands_on_bf) == 1
    # P1's Burgeoning did NOT fire from P0's drop — P1 still has
    # *both* extra hand cards (no recursive drop).
    assert p1_extra in p1.hand
    assert p0_extra in state.player_by_id(0).hand or p0_extra in p0_lands_on_bf
    # And no land has entered P1's side beyond the one they actually played.
    p1_lands_on_bf = [
        o for o in state.battlefield
        if o.controller_id == 1 and o.printing.is_land
    ]
    assert len(p1_lands_on_bf) == 1
