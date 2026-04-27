"""Tests for Perigee Beckoner's ETB granted dies-rider.

Oracle: "When this creature enters, until end of turn, another target
creature you control gets +2/+0 and gains 'When this creature dies,
return it to the battlefield tapped under its owner's control.'"

Wired via ``PumpTargetCreatureUntilEOT.granted_triggered_ability`` —
the rider lives in ``temp_triggered_abilities`` until cleanup, and
``_fire_dies_triggers`` walks that tuple alongside printed dies-triggers.
"""

from mtg_bot.agents import RandomAgent
from mtg_bot.cards import EOE_CREATURES, SYNTHETIC_CREATURES
from mtg_bot.effects import (
    PerigeeBeckonerDiesReturnTappedEffect,
    PumpTargetCreatureUntilEOT,
    TriggeredAbility,
)
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.turn import (
    _fire_dies_triggers,
    move_off_battlefield,
    run_cleanup_step,
)
from tests._etb_helpers import _legacy_or_inferred_key, _matches_legacy_key


def _new_state():
    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    return state


def _put(state, printing, owner_id=0):
    obj = state.new_object(printing, owner_id, Zone.BATTLEFIELD)
    state.battlefield.append(obj)
    return obj


def _grant_dies_rider(state, target):
    """Wire the granted dies-rider onto ``target`` directly (bypasses the
    Perigee Beckoner ETB target-selection so tests don't depend on
    agent/stack interactions)."""
    granted = TriggeredAbility(
        trigger="dies",
        effect=PerigeeBeckonerDiesReturnTappedEffect(),
    )
    PumpTargetCreatureUntilEOT(
        power_bonus=2, toughness_bonus=0,
        you_control_only=True,
        exclude_self=True,
        granted_triggered_ability=granted,
    ).resolve(state, target.controller_id, (("creature", target.id),))


def test_granted_dies_rider_returns_creature_tapped():
    """Granted creature dies → comes back tapped under its owner's
    control."""
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    _grant_dies_rider(state, bear)
    from mtg_bot.game import effective_triggered_abilities
    granted_only = [
        ab for ab in effective_triggered_abilities(state, bear)
        if ab not in bear.printing.triggered_abilities
    ]
    assert len(granted_only) == 1
    assert bear.temp_power_bonus == 2

    # Send it to the graveyard (simulates lethal damage / destroy).
    move_off_battlefield(state, bear, destination="graveyard")

    # The rider fired during _fire_dies_triggers and put the bear back
    # on the battlefield, tapped, under its owner's control.
    assert bear in state.battlefield
    assert bear.zone == Zone.BATTLEFIELD
    assert bear.tapped is True
    assert bear.controller_id == 0
    assert bear not in state.players[0].graveyard


def test_owners_control_not_casters_control():
    """The returned creature comes back under its OWNER's control, not
    under the Perigee-Beckoner-controller's. If an opponent's creature
    somehow received the rider (e.g. opponent's creature with our grant),
    it would still go to its owner — but the standard wiring restricts
    targets to creatures-you-control. Test the resolve's owner-routing
    directly by grant + move on a creature owned by P1."""
    state = _new_state()
    # The pump's you_control_only restricts targeting to caster's
    # creatures, but the BESPOKE effect's resolve is what enforces
    # owner-routing. Test that resolve directly.
    enemy_bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=1)
    granted = TriggeredAbility(
        trigger="dies",
        effect=PerigeeBeckonerDiesReturnTappedEffect(),
    )
    enemy_bear.temp_triggered_abilities = (granted,)
    move_off_battlefield(state, enemy_bear, destination="graveyard")
    assert enemy_bear in state.battlefield
    assert enemy_bear.controller_id == 1  # owner = P1
    assert enemy_bear.tapped is True


def test_cleanup_clears_rider_then_death_does_not_fire():
    """After end-of-turn cleanup, the granted trigger is gone; a
    next-turn death does NOT fire the return-tapped rider."""
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    _grant_dies_rider(state, bear)
    from mtg_bot.game import effective_triggered_abilities
    granted_pre = [
        ab for ab in effective_triggered_abilities(state, bear)
        if ab not in bear.printing.triggered_abilities
    ]
    assert granted_pre  # present pre-cleanup
    run_cleanup_step(state)
    granted_post = [
        ab for ab in effective_triggered_abilities(state, bear)
        if ab not in bear.printing.triggered_abilities
    ]
    assert granted_post == []
    # Now kill it; should go to graveyard normally and stay there.
    move_off_battlefield(state, bear, destination="graveyard")
    assert bear not in state.battlefield
    assert bear in state.players[0].graveyard


def test_perigee_beckoner_printing_wires_granted_rider():
    """The card printing's ETB effect carries the granted dies-rider."""
    pb = EOE_CREATURES["Perigee Beckoner"]
    assert len(pb.triggered_abilities) == 1
    etb = pb.triggered_abilities[0]
    assert _matches_legacy_key(etb, "etb")
    eff = etb.effect
    assert isinstance(eff, PumpTargetCreatureUntilEOT)
    assert eff.power_bonus == 2
    assert eff.you_control_only
    assert eff.exclude_self
    assert eff.granted_triggered_ability is not None
    assert eff.granted_triggered_ability.trigger == "dies"
    assert isinstance(
        eff.granted_triggered_ability.effect,
        PerigeeBeckonerDiesReturnTappedEffect,
    )


def test_rider_resolve_no_source_noop():
    """Defensive: if resolving_source isn't set, the resolve bails out
    cleanly without raising."""
    state = _new_state()
    state.resolving_source = None
    # No exception, no state change.
    PerigeeBeckonerDiesReturnTappedEffect().resolve(state, 0, ())


def test_rider_resolve_source_not_in_graveyard_noop():
    """If the dying object has been moved out of its owner's graveyard
    (e.g. exiled by a replacement), the rider doesn't try to fish it
    out of nowhere."""
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    state.resolving_source = bear  # but bear is on battlefield, not gy
    PerigeeBeckonerDiesReturnTappedEffect().resolve(state, 0, ())
    # No-op: bear stays on battlefield, nothing duplicated.
    assert bear in state.battlefield
    assert sum(1 for o in state.battlefield if o is bear) == 1


def test_rider_resolve_token_does_not_return():
    """Tokens cease to exist on death (rule 704.5d) — even if a token
    somehow has the granted rider, the return-tapped resolve is a
    clean no-op."""
    state = _new_state()
    # Create a token-like object: use any token printing if available,
    # else simulate by setting is_token via the printing dataclass —
    # we use a Soldier token from the token registry.
    from mtg_bot.cards.tokens import TOKEN_PRINTINGS
    soldier = state.new_object(
        TOKEN_PRINTINGS["Human Soldier"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(soldier)
    state.resolving_source = soldier
    PerigeeBeckonerDiesReturnTappedEffect().resolve(state, 0, ())
    # Token printing — no return.
    assert state.players[0].graveyard == []
    # Soldier is still on the battlefield; rider didn't move it.
    assert soldier in state.battlefield


def test_rider_describe():
    d = PerigeeBeckonerDiesReturnTappedEffect().describe()
    assert "tapped" in d
    assert "owner" in d


def test_pump_legal_targets_excludes_self_when_flag_set():
    """exclude_self filter wires through the ETB target picker — the
    Perigee-Beckoner source itself isn't in legal_targets."""
    state = _new_state()
    pb = _put(state, EOE_CREATURES["Perigee Beckoner"], owner_id=0)
    other = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    eff = PumpTargetCreatureUntilEOT(
        power_bonus=2, toughness_bonus=0,
        you_control_only=True, exclude_self=True,
    )
    state.resolving_source = pb
    legal = eff.legal_targets(state, 0)
    state.resolving_source = None
    ids = {tid for kind, tid in legal}
    assert pb.id not in ids
    assert other.id in ids
