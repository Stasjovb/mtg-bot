"""Tests for the layer-7b set-base-P/T continuous effect.

Covers:
- SetBasePTUntilEOT and SetBasePTConditionalUntilEOT effect classes
- GameState.grant_set_base_pt_ueot registry helper
- Layer ordering: set-base (7b) then bonus (7c) then counters (7d)
- EOT expiry via run_cleanup_step
- Genemorph Imago parser parity and not in bespoke table
- Integration: landfall trigger fires and SetBasePTConditionalUntilEOT resolves
"""

from __future__ import annotations

import pytest

from mtg_bot.agents import Agent
from mtg_bot.cards import SYNTHETIC_CREATURES
from mtg_bot.cards.source import get_active_source
from mtg_bot.effects.generic import SetBasePTUntilEOT, SetBasePTConditionalUntilEOT
from mtg_bot.game import (
    GameState, Player, Zone,
    effective_power, effective_toughness,
)
from mtg_bot.turn import run_cleanup_step


_PRINTINGS = get_active_source().get_printings()


class _PickFirstAgent(Agent):
    def choose_target(self, state, player_id, legal_targets):
        return legal_targets[0] if legal_targets else None


def _new_state():
    state = GameState()
    state.players.append(Player(id=0, agent=_PickFirstAgent()))
    state.players.append(Player(id=1, agent=_PickFirstAgent()))
    state.active_player_idx = 0
    return state


def _put(state, printing, owner_id=0):
    obj = state.new_object(printing, owner_id, Zone.BATTLEFIELD)
    state.battlefield.append(obj)
    return obj


# ─────────────────────────────────────────────
# grant_set_base_pt_ueot helper
# ─────────────────────────────────────────────


def test_grant_set_base_pt_ueot_writes_registry_entry():
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"])
    state.grant_set_base_pt_ueot(
        source_id=bear.id, target_id=bear.id, power=3, toughness=3,
    )
    assert len(state.continuous_effects) == 1
    ce = state.continuous_effects[0]
    assert ce.layer == 7
    assert ce.sublayer == 1
    assert ce.kind == "set_base_pt"
    assert ce.params == (3, 3)
    assert ce.expires_at == "cleanup"


def test_grant_set_base_pt_ueot_drives_effective_pt():
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"])
    state.grant_set_base_pt_ueot(
        source_id=bear.id, target_id=bear.id, power=3, toughness=3,
    )
    # Registry entry is the sole source of truth for the layer-7b read.
    assert effective_power(state, bear) == 3
    assert effective_toughness(state, bear) == 3


def test_grant_set_base_pt_ueot_missing_target_still_writes_registry():
    state = _new_state()
    # No exception — registry entry is written regardless; the read path
    # is target-id-keyed so an entry for a nonexistent id is just inert.
    state.grant_set_base_pt_ueot(
        source_id=99, target_id=99, power=3, toughness=3,
    )
    assert len(state.continuous_effects) == 1


# ─────────────────────────────────────────────
# Layer-7b: set-base overrides printed P/T
# ─────────────────────────────────────────────


def test_set_base_pt_overrides_printed_pt():
    """Set 3/3 base on a 2/2 bear → effective P/T becomes 3/3."""
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"])
    # Bear is 2/2 printed.
    assert effective_power(state, bear) == 2
    assert effective_toughness(state, bear) == 2

    state.grant_set_base_pt_ueot(
        source_id=bear.id, target_id=bear.id, power=3, toughness=3,
    )
    assert effective_power(state, bear) == 3
    assert effective_toughness(state, bear) == 3


# ─────────────────────────────────────────────
# Layer ordering: 7b then 7c then 7d
# ─────────────────────────────────────────────


def test_plus_one_counter_stacks_on_top_of_set_base_pt():
    """Layer 7d (+1/+1 counters) stacks on top of 7b (set base P/T).

    A 2/2 bear with a 3/3 set-base-PT and a +1/+1 counter → 4/4.
    """
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"])
    state.grant_set_base_pt_ueot(
        source_id=bear.id, target_id=bear.id, power=3, toughness=3,
    )
    bear.plus_one_counters = 1
    assert effective_power(state, bear) == 4
    assert effective_toughness(state, bear) == 4


def test_pump_bonus_stacks_on_top_of_set_base_pt():
    """Layer 7c (temp pump bonus) stacks on top of 7b (set base P/T).

    A 2/2 bear with a 3/3 set-base-PT and a +1/+0 temp pump → 4/3.
    """
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"])
    state.grant_set_base_pt_ueot(
        source_id=bear.id, target_id=bear.id, power=3, toughness=3,
    )
    bear.temp_power_bonus = 1
    assert effective_power(state, bear) == 4
    assert effective_toughness(state, bear) == 3


# ─────────────────────────────────────────────
# EOT expiry
# ─────────────────────────────────────────────


def test_set_base_pt_expires_at_cleanup():
    """Cleanup step expires the registry entry → bear returns to 2/2."""
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"])
    state.grant_set_base_pt_ueot(
        source_id=bear.id, target_id=bear.id, power=3, toughness=3,
    )
    assert effective_power(state, bear) == 3

    run_cleanup_step(state)
    assert effective_power(state, bear) == 2
    assert effective_toughness(state, bear) == 2


# ─────────────────────────────────────────────
# SetBasePTUntilEOT effect class
# ─────────────────────────────────────────────


def test_set_base_pt_until_eot_requires_target():
    assert SetBasePTUntilEOT(power=3, toughness=3).requires_target()


def test_set_base_pt_until_eot_target_count_range():
    assert SetBasePTUntilEOT(power=3, toughness=3).target_count_range() == (1, 1)


def test_set_base_pt_until_eot_resolve_sets_base():
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"])
    SetBasePTUntilEOT(power=3, toughness=3).resolve(
        state, 0, (("creature", bear.id),)
    )
    assert effective_power(state, bear) == 3
    assert effective_toughness(state, bear) == 3


def test_set_base_pt_until_eot_resolve_noop_no_targets():
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"])
    SetBasePTUntilEOT(power=3, toughness=3).resolve(state, 0, ())
    assert effective_power(state, bear) == 2  # unchanged


def test_set_base_pt_until_eot_describe():
    d = SetBasePTUntilEOT(power=3, toughness=3).describe()
    assert "3/3" in d
    assert "base power and toughness" in d
    assert "until end of turn" in d


# ─────────────────────────────────────────────
# SetBasePTConditionalUntilEOT effect class
# ─────────────────────────────────────────────


def test_set_base_pt_conditional_requires_target():
    eff = SetBasePTConditionalUntilEOT(
        default_power=3, default_toughness=3,
        land_threshold=6, upgrade_power=6, upgrade_toughness=6,
    )
    assert eff.requires_target()


def test_set_base_pt_conditional_below_threshold_uses_default():
    """With fewer than 6 lands → 3/3 base applied."""
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"])
    # 3 lands for controller 0.
    land = _PRINTINGS["Forest"]
    for _ in range(3):
        _put(state, land, owner_id=0)

    eff = SetBasePTConditionalUntilEOT(
        default_power=3, default_toughness=3,
        land_threshold=6, upgrade_power=6, upgrade_toughness=6,
    )
    eff.resolve(state, 0, (("creature", bear.id),))
    assert effective_power(state, bear) == 3
    assert effective_toughness(state, bear) == 3


def test_set_base_pt_conditional_at_threshold_uses_upgrade():
    """With exactly 6 lands → 6/6 base applied."""
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"])
    land = _PRINTINGS["Forest"]
    for _ in range(6):
        _put(state, land, owner_id=0)

    eff = SetBasePTConditionalUntilEOT(
        default_power=3, default_toughness=3,
        land_threshold=6, upgrade_power=6, upgrade_toughness=6,
    )
    eff.resolve(state, 0, (("creature", bear.id),))
    assert effective_power(state, bear) == 6
    assert effective_toughness(state, bear) == 6


def test_set_base_pt_conditional_describe():
    eff = SetBasePTConditionalUntilEOT(
        default_power=3, default_toughness=3,
        land_threshold=6, upgrade_power=6, upgrade_toughness=6,
    )
    d = eff.describe()
    assert "3/3" in d
    assert "6/6" in d
    assert "6" in d  # land threshold


# ─────────────────────────────────────────────
# Parser parity — Genemorph Imago
# ─────────────────────────────────────────────


def test_genemorph_imago_parser_claims_card():
    from mtg_bot.cards.parser.source import OracleParserCardSource
    parser = OracleParserCardSource()
    printings = parser.get_printings()
    assert "Genemorph Imago" in printings


def test_genemorph_imago_printed_stats():
    m = _PRINTINGS["Genemorph Imago"]
    assert m.power == 1
    assert m.toughness == 3
    assert m.mana_cost_str == "{G}{U}"


def test_genemorph_imago_has_flying():
    m = _PRINTINGS["Genemorph Imago"]
    assert "flying" in m.keywords


def test_genemorph_imago_has_landfall_trigger_with_set_base_pt():
    from mtg_bot.effects.generic import SetBasePTConditionalUntilEOT
    m = _PRINTINGS["Genemorph Imago"]
    landfall_effects = [
        ab.effect for ab in m.triggered_abilities
        if isinstance(ab.effect, SetBasePTConditionalUntilEOT)
    ]
    assert len(landfall_effects) == 1
    eff = landfall_effects[0]
    assert eff.default_power == 3
    assert eff.default_toughness == 3
    assert eff.land_threshold == 6
    assert eff.upgrade_power == 6
    assert eff.upgrade_toughness == 6


# ─────────────────────────────────────────────
# Integration: landfall fires and resolves
# ─────────────────────────────────────────────


def test_genemorph_landfall_trigger_fires_on_land_entry():
    """When a land enters under Genemorph Imago's controller, the
    landfall trigger fires and the target creature gets base 3/3."""
    from mtg_bot.actions import drain_stack, put_into_battlefield
    from mtg_bot.game import Zone

    state = _new_state()
    imago = _put(state, _PRINTINGS["Genemorph Imago"], owner_id=0)
    imago.summoning_sick = False

    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)

    # Put a land for controller 0 onto the battlefield — this fires the
    # ENTERS event which dispatches predicate-style landfall triggers.
    land = _PRINTINGS["Forest"]
    land_obj = state.new_object(land, 0, Zone.BATTLEFIELD)
    put_into_battlefield(state, land_obj, 0)
    drain_stack(state)

    # PickFirstAgent targets the first legal creature — either the bear
    # or imago should have 3/3 base P/T set via the layer-7b registry.
    affected = [
        o for o in state.battlefield
        if any(
            ce.layer == 7 and ce.sublayer == 1 and ce.kind == "set_base_pt"
            and ce.target_id == o.id and ce.params == (3, 3)
            for ce in state.continuous_effects
        )
    ]
    assert len(affected) == 1
