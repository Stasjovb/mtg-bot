"""Engine-resolve tests for parser-shape primitives in
``mtg_bot/effects/generic/exile.py`` and ``effects/generic/pump.py``
whose unit tests cover parsing but whose resolve early-returns and
describe-method branches still had coverage gaps.

Round J of the coverage chip-away series. Targets:

* ``WarpExileSelf`` — both source-None defensive returns: when
  ``state.resolving_source`` is None, and when the warp creature
  has left the battlefield between trigger and resolve (id no
  longer matches anything on the battlefield).
* ``ExileTargetAttackingCreatureUntilEndStep`` (Mystifying Maze)
  — describe + the target-not-on-battlefield resolve early
  return.
* ``ExileTargetCardFromGraveyard`` (DSK Ghost Vacuum) —
  ``requires_target`` and the wrong-kind early-return path.
* ``SetBasePTUntilEOT`` — the wrong-kind and target-not-on-
  battlefield early returns + ``legal_targets`` (these were
  uncovered because the existing tests pre-build target tuples
  and never exercise the legal-target enumeration).
* ``PumpSelfXPowerUEOT`` — source-None / X<=0 / describe.
* ``SwitchSourcePowerToughnessUEOT`` — source-None defensive
  return + describe.
"""

from __future__ import annotations


# ---------- WarpExileSelf ----------


def test_warp_exile_self_no_resolving_source_no_op():
    from mtg_bot.effects.generic.exile import WarpExileSelf
    from mtg_bot.game import GameState, Player

    state = GameState(
        players=[Player(id=0), Player(id=1)],
        resolving_source=None,
    )
    pre_log = len(state.log)
    WarpExileSelf().resolve(state, controller_id=0)
    assert len(state.log) == pre_log


def test_warp_exile_self_source_left_battlefield_no_op():
    """``resolving_source`` is a stale GameObject ref whose id no
    longer matches anything on the battlefield (countered / died /
    bounced between trigger and resolve)."""
    from mtg_bot.cards.base import make_creature
    from mtg_bot.effects.generic.exile import WarpExileSelf
    from mtg_bot.game import GameObject, GameState, Player, Zone

    bear_pr = make_creature("Bear", "{1}{G}", 2, 2)
    stale_ref = GameObject(
        id=42, printing=bear_pr, owner_id=0, controller_id=0,
        zone=Zone.GRAVEYARD,
    )
    state = GameState(
        players=[Player(id=0), Player(id=1)],
        battlefield=[],
        resolving_source=stale_ref,
    )
    pre_log = len(state.log)
    WarpExileSelf().resolve(state, controller_id=0)
    assert len(state.log) == pre_log
    assert state.battlefield == []


# ---------- ExileTargetAttackingCreatureUntilEndStep ----------


def test_exile_attacking_until_end_step_describe():
    from mtg_bot.effects.generic.exile import (
        ExileTargetAttackingCreatureUntilEndStep,
    )

    desc = ExileTargetAttackingCreatureUntilEndStep().describe()
    assert "exile target attacking creature" in desc
    assert "next end step" in desc
    assert "tapped" in desc


def test_exile_attacking_until_end_step_target_not_on_battlefield():
    """Target id doesn't match any battlefield object — defensive
    early return; no exile action, no delayed trigger."""
    from mtg_bot.effects.generic.exile import (
        ExileTargetAttackingCreatureUntilEndStep,
    )
    from mtg_bot.game import GameState, Player

    state = GameState(players=[Player(id=0), Player(id=1)])
    state.delayed_triggers.clear()  # ensure starting state
    eff = ExileTargetAttackingCreatureUntilEndStep()
    eff.resolve(state, controller_id=0, targets=(("creature", 999),))
    # No delayed trigger scheduled.
    assert state.delayed_triggers == []


def test_exile_attacking_until_end_step_no_targets():
    """No targets passed — early-return."""
    from mtg_bot.effects.generic.exile import (
        ExileTargetAttackingCreatureUntilEndStep,
    )
    from mtg_bot.game import GameState, Player

    state = GameState(players=[Player(id=0), Player(id=1)])
    state.delayed_triggers.clear()
    ExileTargetAttackingCreatureUntilEndStep().resolve(
        state, controller_id=0, targets=(),
    )
    assert state.delayed_triggers == []


# ---------- ExileTargetCardFromGraveyard ----------


def test_exile_target_card_from_graveyard_requires_target():
    from mtg_bot.effects.generic.exile import ExileTargetCardFromGraveyard

    assert ExileTargetCardFromGraveyard().requires_target() is True


def test_exile_target_card_from_graveyard_wrong_kind_no_op():
    from mtg_bot.cards.base import make_creature
    from mtg_bot.effects.generic.exile import ExileTargetCardFromGraveyard
    from mtg_bot.game import GameObject, GameState, Player, Zone

    bear_pr = make_creature("Bear", "{1}{G}", 2, 2)
    bear = GameObject(id=1, printing=bear_pr, owner_id=0, controller_id=0,
                      zone=Zone.GRAVEYARD)
    p0 = Player(id=0)
    p0.graveyard.append(bear)
    state = GameState(players=[p0, Player(id=1)])
    ExileTargetCardFromGraveyard().resolve(
        state, 0, (("not_card_in_graveyard", bear.id),),
    )
    # Wrong-kind tuple → no exile.
    assert bear in p0.graveyard
    assert bear not in p0.exile


def test_exile_target_card_from_graveyard_no_targets():
    from mtg_bot.effects.generic.exile import ExileTargetCardFromGraveyard
    from mtg_bot.game import GameState, Player

    state = GameState(players=[Player(id=0), Player(id=1)])
    ExileTargetCardFromGraveyard().resolve(state, 0, ())
    # No state change — log + zones untouched.
    assert state.players[0].exile == []


# ---------- SetBasePTUntilEOT legal_targets + wrong-kind / target-gone ----------


def test_set_base_pt_legal_targets_includes_battlefield_creatures():
    from mtg_bot.cards.base import make_artifact, make_creature
    from mtg_bot.effects.generic import SetBasePTUntilEOT
    from mtg_bot.game import GameObject, GameState, Player, Zone

    bear_pr = make_creature("Bear", "{1}{G}", 2, 2)
    bear = GameObject(id=1, printing=bear_pr, owner_id=0, controller_id=0,
                      zone=Zone.BATTLEFIELD)
    arti_pr = make_artifact("Bauble", "{1}")
    arti = GameObject(id=2, printing=arti_pr, owner_id=0, controller_id=0,
                      zone=Zone.BATTLEFIELD)
    state = GameState(
        players=[Player(id=0), Player(id=1)],
        battlefield=[bear, arti],
    )
    eff = SetBasePTUntilEOT(power=3, toughness=3)
    legal = eff.legal_targets(state, 0)
    ids = {tid for kind, tid in legal if kind == "creature"}
    assert bear.id in ids
    assert arti.id not in ids


def test_set_base_pt_resolve_wrong_kind_no_op():
    from mtg_bot.cards.base import make_creature
    from mtg_bot.effects.generic import SetBasePTUntilEOT
    from mtg_bot.game import GameObject, GameState, Player, Zone

    bear_pr = make_creature("Bear", "{1}{G}", 2, 2)
    bear = GameObject(id=1, printing=bear_pr, owner_id=0, controller_id=0,
                      zone=Zone.BATTLEFIELD)
    state = GameState(
        players=[Player(id=0), Player(id=1)],
        battlefield=[bear],
    )
    SetBasePTUntilEOT(power=3, toughness=3).resolve(
        state, 0, (("permanent", bear.id),),  # wrong kind
    )
    # No layer-7b entry written.
    assert all(
        ce.layer != 7 or ce.kind != "set_base_pt"
        for ce in state.continuous_effects
    )


def test_set_base_pt_resolve_target_not_on_battlefield_no_op():
    from mtg_bot.effects.generic import SetBasePTUntilEOT
    from mtg_bot.game import GameState, Player

    state = GameState(players=[Player(id=0), Player(id=1)])
    SetBasePTUntilEOT(power=3, toughness=3).resolve(
        state, 0, (("creature", 999),),
    )
    assert state.continuous_effects == []


# ---------- PumpSelfXPowerUEOT ----------


def test_lavaclaw_reaches_x_pump_no_source_no_op():
    from mtg_bot.effects.generic.pump import PumpSelfXPowerUEOT
    from mtg_bot.game import GameState, Player

    state = GameState(
        players=[Player(id=0), Player(id=1)], resolving_source=None,
    )
    pre_log = len(state.log)
    PumpSelfXPowerUEOT().resolve(state, controller_id=0)
    assert len(state.log) == pre_log


def test_lavaclaw_reaches_x_pump_x_zero_no_op():
    """``state.resolving_x_value <= 0`` early-returns without
    bumping power."""
    from mtg_bot.cards.base import make_creature
    from mtg_bot.effects.generic.pump import PumpSelfXPowerUEOT
    from mtg_bot.game import GameObject, GameState, Player, Zone

    bear_pr = make_creature("Lavaclaw-ish", "{1}{R}", 2, 2)
    src = GameObject(id=1, printing=bear_pr, owner_id=0, controller_id=0,
                     zone=Zone.BATTLEFIELD)
    state = GameState(
        players=[Player(id=0), Player(id=1)],
        battlefield=[src],
        resolving_source=src,
    )
    state.resolving_x_value = 0
    PumpSelfXPowerUEOT().resolve(state, controller_id=0)
    # No power bump applied.
    assert src.temp_power_bonus == 0


def test_lavaclaw_reaches_x_pump_describe():
    from mtg_bot.effects.generic.pump import PumpSelfXPowerUEOT

    desc = PumpSelfXPowerUEOT().describe()
    assert "+X/+0" in desc
    assert "until end of turn" in desc


def test_lavaclaw_reaches_x_pump_resolve_applies_bump():
    """Source-on-battlefield + X>0 path — bumps temp_power_bonus by X."""
    from mtg_bot.cards.base import make_creature
    from mtg_bot.effects.generic.pump import PumpSelfXPowerUEOT
    from mtg_bot.game import GameObject, GameState, Player, Zone

    bear_pr = make_creature("Lavaclaw-ish", "{1}{R}", 2, 2)
    src = GameObject(id=1, printing=bear_pr, owner_id=0, controller_id=0,
                     zone=Zone.BATTLEFIELD)
    state = GameState(
        players=[Player(id=0), Player(id=1)],
        battlefield=[src],
        resolving_source=src,
    )
    state.resolving_x_value = 3
    PumpSelfXPowerUEOT().resolve(state, controller_id=0)
    assert src.temp_power_bonus == 3


# ---------- SwitchSourcePowerToughnessUEOT ----------


def test_switch_source_pt_no_source_no_op():
    from mtg_bot.effects.generic.pump import SwitchSourcePowerToughnessUEOT
    from mtg_bot.game import GameState, Player

    state = GameState(
        players=[Player(id=0), Player(id=1)], resolving_source=None,
    )
    SwitchSourcePowerToughnessUEOT().resolve(state, controller_id=0)
    # No registry entry written.
    assert all(ce.kind != "switch_pt" for ce in state.continuous_effects)


def test_switch_source_pt_describe():
    from mtg_bot.effects.generic.pump import SwitchSourcePowerToughnessUEOT

    desc = SwitchSourcePowerToughnessUEOT().describe()
    assert "switch" in desc
    assert "power and toughness" in desc
    assert "until end of turn" in desc


def test_switch_source_pt_writes_layer_7_sublayer_4_entry():
    """Source-on-battlefield path — writes a layer-7 sublayer-4
    ``switch_pt`` registry entry sourced by the source."""
    from mtg_bot.cards.base import make_creature
    from mtg_bot.effects.generic.pump import SwitchSourcePowerToughnessUEOT
    from mtg_bot.game import GameObject, GameState, Player, Zone

    pr = make_creature("Wandering Fumarole-ish", "{R}{U}", 1, 4)
    src = GameObject(id=1, printing=pr, owner_id=0, controller_id=0,
                     zone=Zone.BATTLEFIELD)
    state = GameState(
        players=[Player(id=0), Player(id=1)],
        battlefield=[src],
        resolving_source=src,
    )
    SwitchSourcePowerToughnessUEOT().resolve(state, controller_id=0)
    matching = [
        ce for ce in state.continuous_effects
        if ce.layer == 7 and ce.kind == "switch_pt"
        and ce.target_id == src.id
    ]
    assert len(matching) == 1
    assert matching[0].sublayer == 4
    assert matching[0].expires_at == "cleanup"
