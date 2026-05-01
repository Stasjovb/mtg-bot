"""Tests for Sothera, the Supervoid — dies-exile-opponent and end-step
reanimate effects.

The DIES trigger ("each opponent chooses a creature they control and
exiles it") now decomposes into the generic
``EachOpponentExilesOwnCreature(link_to_source=True)`` primitive (in
``effects/generic.py``) via the unified parser grammar; the bespoke
``SotheraExileOpponentCreatureEffect`` was deleted in
audit-per-opponent-choice.

The end-step reanimate ("if a player controls no creatures, sacrifice
Sothera, then put a creature card exiled with it onto the battlefield
under your control with two additional +1/+1 counters on it") now
decomposes into ``Sequence(ReanimateOneExiledWithSourceWithCounters(
counter_amount=2), SacrificeSelfPreservingExileLink())`` plus the
``StateBound(AnyPlayerControlsNoCreatures())`` intervening-if gate
(audit-sothera-foundfootage); the bespoke
``SotheraEndStepReanimateEffect`` was deleted in the same change.
"""

from mtg_bot.actions import drain_stack
from mtg_bot.agents import Agent, RandomAgent
from mtg_bot.cards import SYNTHETIC_CREATURES
from mtg_bot.effects import (
    EachOpponentExilesOwnCreature,
    ReanimateOneExiledWithSourceWithCounters,
    SacrificeSelfPreservingExileLink,
)
from mtg_bot.effects.combinators import Sequence
from mtg_bot.effects.predicates import StateBound
from mtg_bot.effects.state_predicates import AnyPlayerControlsNoCreatures
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.turn import destroy, run_beginning_of_end_step_triggers
from tests._etb_helpers import _legacy_or_inferred_key, _matches_legacy_key

from mtg_bot.cards.source import get_active_source

_PRINTINGS = get_active_source().get_printings()


class _PickFirstAgent(Agent):
    def choose_sacrifice(self, state, player_id, legal_ids):
        return legal_ids[0] if legal_ids else None

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


# -----------------------
# Dies observer effect
# -----------------------


def test_dies_observer_exiles_opponent_creature():
    state = _new_state()
    sothera = _put(state, _PRINTINGS["Sothera, the Supervoid"])
    enemy = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=1)
    state.resolving_source = sothera
    try:
        EachOpponentExilesOwnCreature(link_to_source=True).resolve(
            state, 0, (),
        )
    finally:
        state.resolving_source = None
    assert enemy not in state.battlefield
    assert enemy.exiled_by_source == sothera.id
    assert enemy in state.players[1].exile


def test_dies_observer_skips_controller():
    """Each opponent — not controller — chooses their creature."""
    state = _new_state()
    sothera = _put(state, _PRINTINGS["Sothera, the Supervoid"])
    own = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    state.resolving_source = sothera
    try:
        EachOpponentExilesOwnCreature(link_to_source=True).resolve(
            state, 0, (),
        )
    finally:
        state.resolving_source = None
    # Own creature untouched.
    assert own in state.battlefield


def test_dies_observer_describe():
    d = EachOpponentExilesOwnCreature(link_to_source=True).describe()
    assert "opponent" in d and "exile" in d


# -----------------------
# Integration: creature dies → observer fires
# -----------------------


def test_creature_dies_triggers_observer_via_pipeline():
    state = _new_state()
    sothera = _put(state, _PRINTINGS["Sothera, the Supervoid"])
    enemy = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=1)
    my_bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    destroy(state, my_bear)
    drain_stack(state)
    assert enemy not in state.battlefield


# -----------------------
# End-step reanimate
# -----------------------


def test_end_step_does_nothing_if_all_players_have_creatures():
    state = _new_state()
    sothera = _put(state, _PRINTINGS["Sothera, the Supervoid"])
    _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=1)
    run_beginning_of_end_step_triggers(state)
    assert sothera in state.battlefield


def test_end_step_sacrifices_sothera_and_reanimates_when_player_creatureless():
    state = _new_state()
    sothera = _put(state, _PRINTINGS["Sothera, the Supervoid"])
    # P0 controls no creatures (only Sothera — an enchantment).
    # P1 controls a Wild Bear.
    enemy = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=1)
    # Mark the bear exiled-by-Sothera (simulating earlier dies trigger).
    enemy.exiled_by_source = sothera.id
    state.battlefield.remove(enemy)
    enemy.zone = Zone.EXILE
    state.players[1].exile.append(enemy)
    # Now P1 controls no creatures. End-step fires.
    run_beginning_of_end_step_triggers(state)
    drain_stack(state)
    # Sothera sacrificed.
    assert sothera not in state.battlefield
    # Bear reanimated under P0's control with +1/+1 counters.
    assert enemy in state.battlefield
    assert enemy.controller_id == 0
    assert enemy.plus_one_counters == 2


def test_sothera_printing_metadata():
    s = _PRINTINGS["Sothera, the Supervoid"]
    assert "Legendary" in s.supertypes
    triggers = {_legacy_or_inferred_key(ab) for ab in s.triggered_abilities}
    assert "your_creature_or_artifact_dies" in triggers
    assert "beginning_of_end_step" in triggers


def test_sothera_dies_trigger_decomposes_to_generic_primitive():
    """The DIES trigger no longer wires the bespoke
    ``SotheraExileOpponentCreatureEffect``; the unified parser claims
    "Whenever a creature you control dies, each opponent chooses a
    creature they control and exiles it." through
    ``_parse_predicate_trigger_phrase`` for the trigger and the new
    ``each opponent chooses a creature they control and exiles it``
    regex for the body, producing
    ``EachOpponentExilesOwnCreature(link_to_source=True)``."""
    from mtg_bot.effects.predicates import Event

    s = _PRINTINGS["Sothera, the Supervoid"]
    dies = [
        ta for ta in s.triggered_abilities if ta.event == Event.DIES
    ]
    assert len(dies) == 1
    assert dies[0].effect == EachOpponentExilesOwnCreature(
        link_to_source=True,
    )


def test_sothera_end_step_trigger_decomposes_to_generic_primitives():
    """The end-step trigger ("if a player controls no creatures,
    sacrifice Sothera, then put a creature card exiled with it onto
    the battlefield under your control with two additional +1/+1
    counters on it") now decomposes into a Sequence of two generic
    primitives plus the AnyPlayerControlsNoCreatures intervening-if
    gate. The bespoke ``SotheraEndStepReanimateEffect`` was deleted in
    audit-sothera-foundfootage."""
    from mtg_bot.effects.predicates import Event

    s = _PRINTINGS["Sothera, the Supervoid"]
    end_step = [
        ta for ta in s.triggered_abilities
        if ta.event == Event.BEGINNING_OF_END_STEP
    ]
    assert len(end_step) == 1
    ability = end_step[0]
    # The intervening-if gate is composed onto the trigger predicate
    # via predicate-AND; the gate predicate is
    # ``StateBound(AnyPlayerControlsNoCreatures())``.
    from mtg_bot.effects.predicates import And
    assert isinstance(ability.predicate, And)
    has_state_bound = (
        (
            isinstance(ability.predicate.right, StateBound)
            and isinstance(
                ability.predicate.right.inner,
                AnyPlayerControlsNoCreatures,
            )
        )
        or (
            isinstance(ability.predicate.left, StateBound)
            and isinstance(
                ability.predicate.left.inner,
                AnyPlayerControlsNoCreatures,
            )
        )
    )
    assert has_state_bound
    # The body is Sequence(Reanimate..., SacrificeSelfPreservingExileLink).
    assert isinstance(ability.effect, Sequence)
    assert len(ability.effect.effects) == 2
    assert isinstance(
        ability.effect.effects[0],
        ReanimateOneExiledWithSourceWithCounters,
    )
    assert ability.effect.effects[0].counter_amount == 2
    assert isinstance(
        ability.effect.effects[1], SacrificeSelfPreservingExileLink,
    )


# -----------------------
# AnyPlayerControlsNoCreatures gate predicate
# -----------------------


def test_any_player_controls_no_creatures_true_when_one_player_empty():
    state = _new_state()
    # Only P1 controls a creature.
    _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=1)
    pred = AnyPlayerControlsNoCreatures()
    assert pred.test(state, 0) is True


def test_any_player_controls_no_creatures_true_when_both_empty():
    state = _new_state()
    pred = AnyPlayerControlsNoCreatures()
    assert pred.test(state, 0) is True


def test_any_player_controls_no_creatures_false_when_all_have_one():
    state = _new_state()
    _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=1)
    pred = AnyPlayerControlsNoCreatures()
    assert pred.test(state, 0) is False


def test_any_player_controls_no_creatures_skips_eliminated_players():
    state = _new_state()
    # P1 has lost — should be skipped from the "any player has zero"
    # check, otherwise an eliminated player would always satisfy the
    # gate trivially.
    state.players[1].has_lost = True
    _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    pred = AnyPlayerControlsNoCreatures()
    assert pred.test(state, 0) is False


# -----------------------
# ReanimateOneExiledWithSourceWithCounters
# -----------------------


def test_reanimate_picks_one_via_choose_target_and_adds_counters():
    state = _new_state()
    sothera = _put(state, _PRINTINGS["Sothera, the Supervoid"])
    # Tag two creature cards as exiled-by-Sothera in opponent's exile.
    bear1 = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.EXILE,
    )
    bear1.exiled_by_source = sothera.id
    bear2 = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.EXILE,
    )
    bear2.exiled_by_source = sothera.id
    state.players[1].exile.extend([bear1, bear2])
    state.resolving_source = sothera
    try:
        ReanimateOneExiledWithSourceWithCounters(counter_amount=2).resolve(
            state, 0, (),
        )
    finally:
        state.resolving_source = None
    # Exactly one of the two bears was recalled to P0's battlefield with
    # +2 +1/+1 counters; the other stays in P1's exile, still tagged.
    moved = [o for o in state.battlefield if o in (bear1, bear2)]
    remaining = [o for o in state.players[1].exile if o in (bear1, bear2)]
    assert len(moved) == 1
    assert len(remaining) == 1
    assert moved[0].controller_id == 0
    assert moved[0].plus_one_counters == 2
    # The recalled card lost its source-link; the other kept it.
    assert moved[0].exiled_by_source is None
    assert remaining[0].exiled_by_source == sothera.id


def test_reanimate_no_op_when_no_tagged_creature_in_exile():
    state = _new_state()
    sothera = _put(state, _PRINTINGS["Sothera, the Supervoid"])
    state.resolving_source = sothera
    try:
        ReanimateOneExiledWithSourceWithCounters(counter_amount=2).resolve(
            state, 0, (),
        )
    finally:
        state.resolving_source = None
    # No-op — Sothera still on the battlefield, no recall happened.
    assert sothera in state.battlefield


def test_reanimate_no_op_when_resolving_source_is_none():
    """Defensive: when the engine somehow loses the resolving_source
    handle, the recall is a no-op rather than crashing."""
    state = _new_state()
    # No resolving_source set; primitive must short-circuit cleanly.
    ReanimateOneExiledWithSourceWithCounters(counter_amount=2).resolve(
        state, 0, (),
    )


def test_reanimate_describe():
    d = ReanimateOneExiledWithSourceWithCounters(counter_amount=2).describe()
    assert "exiled with" in d
    assert "+1/+1" in d
    # No-counter variant collapses the rider out of the description.
    d_bare = ReanimateOneExiledWithSourceWithCounters(
        counter_amount=0,
    ).describe()
    assert "+1/+1" not in d_bare


# -----------------------
# SacrificeSelfPreservingExileLink + on-leave hook suppression
# -----------------------


def test_sacrifice_preserving_exile_link_no_op_when_source_none():
    """Defensive: when the engine has no resolving_source, the sac step
    short-circuits cleanly rather than crashing."""
    state = _new_state()
    SacrificeSelfPreservingExileLink().resolve(state, 0, ())


def test_sacrifice_preserving_exile_link_no_op_when_already_off_battlefield():
    """When the source has already left the battlefield (an earlier
    sequence step destroyed it), the sac step is a no-op so the Sequence
    composition stays idempotent."""
    state = _new_state()
    sothera = _put(state, _PRINTINGS["Sothera, the Supervoid"])
    state.battlefield.remove(sothera)
    state.resolving_source = sothera
    try:
        SacrificeSelfPreservingExileLink().resolve(state, 0, ())
    finally:
        state.resolving_source = None
    # Suppression flag must NOT be armed (the source isn't on the
    # battlefield, so no leave event will fire and the flag would
    # leak past this resolve).
    assert state.suppress_exiled_by_source_on_leave_for is None


def test_sacrifice_preserving_exile_link_describe():
    d = SacrificeSelfPreservingExileLink().describe()
    assert "sacrifice" in d


def test_sacrifice_preserving_exile_link_suppresses_auto_return():
    """When the sac-with-suppression primitive runs, the on-leave hook
    must NOT auto-return the still-tagged exiled cards. Models the
    second step of Sothera's end-step Sequence: after the recall has
    pulled one creature out of exile, the sac step suppresses the
    auto-return for the OTHER tagged cards so they stay in exile."""
    state = _new_state()
    sothera = _put(state, _PRINTINGS["Sothera, the Supervoid"])
    leftover = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.EXILE,
    )
    leftover.exiled_by_source = sothera.id
    state.players[1].exile.append(leftover)
    state.resolving_source = sothera
    try:
        SacrificeSelfPreservingExileLink().resolve(state, 0, ())
    finally:
        state.resolving_source = None
    # Sothera was sacrificed.
    assert sothera not in state.battlefield
    # The tagged leftover stayed in exile (auto-return suppressed).
    assert leftover in state.players[1].exile
    # Suppression flag was consumed (one-shot).
    assert state.suppress_exiled_by_source_on_leave_for is None


def test_at_beginning_intervening_if_rejects_unknown_gate():
    """An ``At the beginning of <when>, if <gate>, <inner>.`` line whose
    gate phrase isn't in ``_INTERVENING_IF_PHRASES`` is rejected outright
    so we never silently drop the printed gate."""
    from mtg_bot.cards.parser.triggers import _parse_triggered_ability_line

    line = (
        "At the beginning of your end step, if pigs fly, draw a card."
    )
    assert _parse_triggered_ability_line(line, name="Whatever") is None


def test_at_beginning_intervening_if_rejects_unparseable_inner():
    """An ``At the beginning of <when>, if <gate>, <inner>.`` line whose
    inner effect doesn't parse is rejected outright (don't half-claim a
    trigger with a missing body)."""
    from mtg_bot.cards.parser.triggers import _parse_triggered_ability_line

    line = (
        "At the beginning of your end step, if a player controls no "
        "creatures, this is not an effect we know how to parse."
    )
    assert _parse_triggered_ability_line(line, name="Whatever") is None


def test_end_step_other_exiled_cards_stay_in_exile():
    """Belt-and-suspenders for the suppression contract: when Sothera's
    end-step trigger resolves with TWO creatures still in exile, the
    recall step picks one and the suppression-aware sac step keeps the
    other in exile — the bespoke surface text doesn't say all exiled
    cards return."""
    state = _new_state()
    sothera = _put(state, _PRINTINGS["Sothera, the Supervoid"])
    # P0 controls no creatures (only Sothera — an enchantment).
    bear_a = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.EXILE,
    )
    bear_a.exiled_by_source = sothera.id
    bear_b = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.EXILE,
    )
    bear_b.exiled_by_source = sothera.id
    state.players[1].exile.extend([bear_a, bear_b])
    run_beginning_of_end_step_triggers(state)
    drain_stack(state)
    # Sothera sacrificed; one bear recalled with counters; one stays
    # in exile.
    assert sothera not in state.battlefield
    moved = [o for o in state.battlefield if o in (bear_a, bear_b)]
    leftover = [
        o for o in state.players[1].exile if o in (bear_a, bear_b)
    ]
    assert len(moved) == 1
    assert moved[0].plus_one_counters == 2
    assert moved[0].controller_id == 0
    assert len(leftover) == 1
