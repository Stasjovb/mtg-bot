"""Tests for the new ``GrantActivatedAbility`` / ``GrantTriggeredAbility``
registry primitives.

Covers:

- registry-write correctness for self-target (no ``targets`` tuple,
  uses ``state.resolving_source``);
- registry-write correctness for explicit-target via ``targets``;
- ``ApplyEffect(..., EndOfTurn())`` correctly causes the entry to
  expire at cleanup (read-path returns the granted ability before
  cleanup, empty after);
- defensive no-ops (no ability, no resolving source / no target);
- ``Permanent`` lifetime persists past cleanup.
"""

from mtg_bot.agents import RandomAgent
from mtg_bot.cards import SYNTHETIC_CREATURES
from mtg_bot.effects import (
    ActivatedAbility,
    ActivationCost,
    DrawCards,
    GrantActivatedAbility,
    GrantTriggeredAbility,
    TriggeredAbility,
)
from mtg_bot.effects.combinators import ApplyEffect
from mtg_bot.effects.durations import EndOfTurn, Permanent
from mtg_bot.game import (
    GameState, Player, Zone,
    effective_activated_abilities, effective_triggered_abilities,
)
from mtg_bot.turn import run_cleanup_step


def _new_state():
    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    return state


def _put(state, printing, owner_id=0):
    obj = state.new_object(printing, owner_id, Zone.BATTLEFIELD)
    state.battlefield.append(obj)
    return obj


# ---------------------------------------------------------------------
# GrantActivatedAbility
# ---------------------------------------------------------------------


def test_grant_activated_self_target_writes_registry_entry():
    """No ``targets`` tuple → falls back to ``state.resolving_source``.
    Writes a layer-6 ``grant_activated_ability`` registry entry with
    ``expires_at=None``."""
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    ab = ActivatedAbility(
        cost=ActivationCost(), effect=DrawCards(amount=1),
    )
    state.resolving_source = bear
    try:
        GrantActivatedAbility(ability=ab).resolve(state, 0, ())
    finally:
        state.resolving_source = None
    entries = [
        ce for ce in state.continuous_effects
        if ce.layer == 6 and ce.kind == "grant_activated_ability"
    ]
    assert len(entries) == 1
    entry = entries[0]
    assert entry.target_id == bear.id
    assert entry.source_id == bear.id
    assert entry.params == (ab,)
    assert entry.expires_at is None
    # Read path picks it up.
    assert ab in effective_activated_abilities(state, bear)


def test_grant_activated_explicit_target_writes_registry_entry():
    """``targets`` tuple → registry entry targets that object; source_id
    is still the resolving source so leave-play scoping works."""
    state = _new_state()
    artifact = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    target = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=1)
    ab = ActivatedAbility(
        cost=ActivationCost(), effect=DrawCards(amount=1),
    )
    state.resolving_source = artifact
    try:
        GrantActivatedAbility(ability=ab).resolve(
            state, 0, (("creature", target.id),),
        )
    finally:
        state.resolving_source = None
    entries = [
        ce for ce in state.continuous_effects
        if ce.layer == 6 and ce.kind == "grant_activated_ability"
    ]
    assert len(entries) == 1
    entry = entries[0]
    assert entry.target_id == target.id
    assert entry.source_id == artifact.id
    assert ab in effective_activated_abilities(state, target)
    assert ab not in effective_activated_abilities(state, artifact)


def test_grant_activated_apply_effect_end_of_turn_expires_at_cleanup():
    """``ApplyEffect(GrantActivatedAbility, EndOfTurn())`` rewrites the
    entry's lifetime to ``"cleanup"``; the read-path picks it up
    pre-cleanup and drops it post-cleanup."""
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    ab = ActivatedAbility(
        cost=ActivationCost(), effect=DrawCards(amount=1),
    )
    state.resolving_source = bear
    try:
        ApplyEffect(
            inner=GrantActivatedAbility(ability=ab),
            ends_at=EndOfTurn(),
        ).resolve(state, 0, ())
    finally:
        state.resolving_source = None
    pre = [
        a for a in effective_activated_abilities(state, bear)
        if a not in bear.printing.activated_abilities
    ]
    assert ab in pre
    entries = [
        ce for ce in state.continuous_effects
        if ce.layer == 6 and ce.kind == "grant_activated_ability"
    ]
    assert len(entries) == 1
    assert entries[0].expires_at == "cleanup"
    run_cleanup_step(state)
    post = [
        a for a in effective_activated_abilities(state, bear)
        if a not in bear.printing.activated_abilities
    ]
    assert post == []


def test_grant_activated_permanent_lifetime_survives_cleanup():
    """No ApplyEffect wrap → ``expires_at=None`` (permanent); the entry
    persists across cleanup steps."""
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    ab = ActivatedAbility(
        cost=ActivationCost(), effect=DrawCards(amount=1),
    )
    state.resolving_source = bear
    try:
        GrantActivatedAbility(ability=ab).resolve(state, 0, ())
    finally:
        state.resolving_source = None
    run_cleanup_step(state)
    assert ab in effective_activated_abilities(state, bear)


def test_grant_activated_apply_effect_permanent_alias():
    """Default ``ApplyEffect(...)`` (no ends_at) is the ``Permanent``
    duration — same as no wrapping."""
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    ab = ActivatedAbility(
        cost=ActivationCost(), effect=DrawCards(amount=1),
    )
    state.resolving_source = bear
    try:
        ApplyEffect(
            inner=GrantActivatedAbility(ability=ab),
            ends_at=Permanent(),
        ).resolve(state, 0, ())
    finally:
        state.resolving_source = None
    entries = [
        ce for ce in state.continuous_effects
        if ce.layer == 6 and ce.kind == "grant_activated_ability"
    ]
    assert entries[0].expires_at is None


def test_grant_activated_no_ability_noop():
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    state.resolving_source = bear
    try:
        GrantActivatedAbility(ability=None).resolve(state, 0, ())
    finally:
        state.resolving_source = None
    assert state.continuous_effects == []


def test_grant_activated_no_target_and_no_source_noop():
    """No targets and no resolving source → silent no-op."""
    state = _new_state()
    GrantActivatedAbility(
        ability=ActivatedAbility(
            cost=ActivationCost(), effect=DrawCards(amount=1),
        ),
    ).resolve(state, 0, ())
    assert state.continuous_effects == []


def test_grant_activated_target_missing_from_battlefield_noop():
    """``targets`` references an id not on the battlefield → no-op."""
    state = _new_state()
    state.resolving_source = None
    GrantActivatedAbility(
        ability=ActivatedAbility(
            cost=ActivationCost(), effect=DrawCards(amount=1),
        ),
    ).resolve(state, 0, (("creature", 999),))
    assert state.continuous_effects == []


def test_grant_activated_describe():
    eff = GrantActivatedAbility(ability=None)
    assert "activated ability" in eff.describe()


# ---------------------------------------------------------------------
# GrantTriggeredAbility
# ---------------------------------------------------------------------


def test_grant_triggered_self_target_writes_registry_entry():
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    trig = TriggeredAbility(
        trigger="etb", effect=DrawCards(amount=1),
    )
    state.resolving_source = bear
    try:
        GrantTriggeredAbility(ability=trig).resolve(state, 0, ())
    finally:
        state.resolving_source = None
    entries = [
        ce for ce in state.continuous_effects
        if ce.layer == 6 and ce.kind == "grant_triggered_ability"
    ]
    assert len(entries) == 1
    entry = entries[0]
    assert entry.target_id == bear.id
    assert entry.source_id == bear.id
    assert entry.params == (trig,)
    assert entry.expires_at is None
    assert trig in effective_triggered_abilities(state, bear)


def test_grant_triggered_explicit_target_writes_registry_entry():
    state = _new_state()
    artifact = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    target = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=1)
    trig = TriggeredAbility(
        trigger="etb", effect=DrawCards(amount=1),
    )
    state.resolving_source = artifact
    try:
        GrantTriggeredAbility(ability=trig).resolve(
            state, 0, (("creature", target.id),),
        )
    finally:
        state.resolving_source = None
    entries = [
        ce for ce in state.continuous_effects
        if ce.layer == 6 and ce.kind == "grant_triggered_ability"
    ]
    assert len(entries) == 1
    entry = entries[0]
    assert entry.target_id == target.id
    assert entry.source_id == artifact.id
    assert trig in effective_triggered_abilities(state, target)
    assert trig not in effective_triggered_abilities(state, artifact)


def test_grant_triggered_apply_effect_end_of_turn_expires_at_cleanup():
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    trig = TriggeredAbility(
        trigger="etb", effect=DrawCards(amount=1),
    )
    state.resolving_source = bear
    try:
        ApplyEffect(
            inner=GrantTriggeredAbility(ability=trig),
            ends_at=EndOfTurn(),
        ).resolve(state, 0, ())
    finally:
        state.resolving_source = None
    pre = [
        a for a in effective_triggered_abilities(state, bear)
        if a not in bear.printing.triggered_abilities
    ]
    assert trig in pre
    entries = [
        ce for ce in state.continuous_effects
        if ce.layer == 6 and ce.kind == "grant_triggered_ability"
    ]
    assert len(entries) == 1
    assert entries[0].expires_at == "cleanup"
    run_cleanup_step(state)
    post = [
        a for a in effective_triggered_abilities(state, bear)
        if a not in bear.printing.triggered_abilities
    ]
    assert post == []


def test_grant_triggered_permanent_lifetime_survives_cleanup():
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    trig = TriggeredAbility(
        trigger="etb", effect=DrawCards(amount=1),
    )
    state.resolving_source = bear
    try:
        GrantTriggeredAbility(ability=trig).resolve(state, 0, ())
    finally:
        state.resolving_source = None
    run_cleanup_step(state)
    assert trig in effective_triggered_abilities(state, bear)


def test_grant_triggered_no_ability_noop():
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    state.resolving_source = bear
    try:
        GrantTriggeredAbility(ability=None).resolve(state, 0, ())
    finally:
        state.resolving_source = None
    assert state.continuous_effects == []


def test_grant_triggered_no_target_and_no_source_noop():
    state = _new_state()
    GrantTriggeredAbility(
        ability=TriggeredAbility(
            trigger="etb", effect=DrawCards(amount=1),
        ),
    ).resolve(state, 0, ())
    assert state.continuous_effects == []


def test_grant_triggered_target_missing_from_battlefield_noop():
    state = _new_state()
    state.resolving_source = None
    GrantTriggeredAbility(
        ability=TriggeredAbility(
            trigger="etb", effect=DrawCards(amount=1),
        ),
    ).resolve(state, 0, (("creature", 999),))
    assert state.continuous_effects == []


def test_grant_triggered_describe():
    eff = GrantTriggeredAbility(ability=None)
    assert "triggered ability" in eff.describe()
