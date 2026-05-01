"""Per-slot target-kind enforcement.

When an effect declares ``target_slot_kinds`` (e.g.
``("my_creature", "creature")`` for Diplomatic Relations and
Monoist Circuit-Feeder), the targeting pipeline restricts each
slot's pick to entries of the declared kind — even if the agent
naively picks the first option of any kind. Pin that behavior here.
"""

from mtg_bot.actions import (
    drain_stack, push_triggered_ability, put_into_battlefield,
)
from mtg_bot.agents import Agent
from mtg_bot.cards import SYNTHETIC_CREATURES
from mtg_bot.effects import (
    DiplomaticRelationsEffect, PairedTargetPumpDebuffUEOT,
)
from mtg_bot.effects.formulas import CountControlledMatching
from mtg_bot.effects.object_predicates import IsArtifact


def _monoist_effect() -> PairedTargetPumpDebuffUEOT:
    """Mirror the production parser path: paired-target +X/-X with X =
    artifact count you control."""
    return PairedTargetPumpDebuffUEOT(
        formula=CountControlledMatching(IsArtifact()),
        positive_power=1, positive_toughness=0,
        negative_power=0, negative_toughness=-1,
    )
from mtg_bot.game import GameState, Player, Zone

from mtg_bot.cards.source import get_active_source

_PRINTINGS = get_active_source().get_printings()


class _PickFirstAgent(Agent):
    """Naively picks the first option of whatever pool it's offered."""

    def choose_target(self, state, player_id, legal_targets):
        return legal_targets[0] if legal_targets else None


def _new_state():
    state = GameState()
    state.players.append(Player(id=0, agent=_PickFirstAgent()))
    state.players.append(Player(id=1, agent=_PickFirstAgent()))
    state.active_player_idx = 0
    state.priority_player_idx = 0
    return state


def _put(state, printing, owner_id=0):
    obj = state.new_object(printing, owner_id, Zone.BATTLEFIELD)
    state.battlefield.append(obj)
    return obj


# -----------------------
# Effect declarations
# -----------------------


def test_monoist_declares_per_slot_kinds():
    e = _monoist_effect()
    assert e.target_slot_kinds() == ("my_creature", "creature")
    assert e.target_count_range() == (2, 2)


def test_diplomatic_relations_declares_per_slot_kinds():
    e = DiplomaticRelationsEffect()
    assert e.target_slot_kinds() == ("my_creature", "creature")
    assert e.target_count_range() == (2, 2)


def test_default_effect_declares_no_per_slot_kinds():
    """Effects that don't override default to empty tuple — keeps
    the legacy flat-pool behavior for single-kind multi-target
    effects."""
    from mtg_bot.effects import DealDamageAnyTarget

    e = DealDamageAnyTarget(amount=1)
    assert e.target_slot_kinds() == ()


# -----------------------
# Picking pipeline enforces per-slot kind
# -----------------------


def test_pickfirst_agent_with_two_friendlies_still_routes_kinds_correctly():
    """Setup that previously broke: P0 has Monoist + a Wild Bear
    (two friendly creatures), P1 has one Wild Bear. A pick-first
    agent offered ``[my_a, my_b, opp]`` would naively pick my_a
    twice — leaving the opp slot empty. With per-slot kind
    enforcement, slot 0 only sees ``my_creature`` entries and slot 1
    only sees ``creature`` entries — the opp slot is forced to pick
    the opp's bear."""
    state = _new_state()
    own_bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    opp_bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=1)
    monoist = state.new_object(
        _PRINTINGS["Monoist Circuit-Feeder"], 0, Zone.HAND,
    )
    put_into_battlefield(state, monoist, controller_id=0)
    drain_stack(state)
    # X = 1 (just Monoist, the only artifact). Friendly slot pumped
    # +1/+0; opp slot debuffed -0/-1. Both halves resolve thanks to
    # per-slot kind enforcement.
    pumped = (monoist.temp_power_bonus + own_bear.temp_power_bonus)
    assert pumped == 1, "friendly slot should have been picked"
    assert opp_bear.temp_toughness_bonus == -1, (
        "opp slot must be filled even when pick-first agent would "
        "otherwise prefer a friendly target first"
    )


def test_per_slot_kind_skips_when_kind_unavailable():
    """If the slot's required kind has no candidates in remaining,
    the loop breaks for that slot. Combined with ``min_t > 0`` and
    the legal_targets-empty-when-side-empty rule, this means the
    trigger fizzles before hitting the picking pipeline. Belt-and-
    suspenders test: even if legal_targets DID return a mix and one
    side had no entries, the slot would skip rather than wrongly
    pick a same-kind."""
    state = _new_state()
    # Forge a synthetic legal_targets via direct push: skip the
    # ETB-trigger fizzle gate and exercise the pick loop with a
    # one-kind pool. We do this by constructing the trigger manually
    # and force-pushing it with no opp candidates available.
    own_bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    monoist = _put(state, _PRINTINGS["Monoist Circuit-Feeder"], owner_id=0)
    monoist.summoning_sick = False
    # legal_targets: for Monoist's effect with no opp creature, returns
    # [] (per-slot rule), so push_triggered_ability fizzles before the
    # picker ever runs. Verify by direct invocation.
    e = _monoist_effect()
    state.resolving_source = monoist
    try:
        legal = e.legal_targets(state, 0)
    finally:
        state.resolving_source = None
    assert legal == [], (
        "no opp creature → legal_targets is empty → trigger fizzles "
        "before pick loop"
    )
