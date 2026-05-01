"""Engine-resolve tests for ``TapAndStunUpToOneTargetCreature``.

Meat Locker's door trigger ("tap up to one target creature and put two
stun counters on it") is parsed onto this class, but no test exercises
the resolve path that taps + stuns the chosen creature. These tests
cover the happy path (untapped + tapped variants), the no-target
silent no-op, the wrong-target-kind defensive bail, and the
missing-target defensive bail."""

from __future__ import annotations

from mtg_bot.cards import SYNTHETIC_CREATURES
from mtg_bot.effects import TapAndStunUpToOneTargetCreature
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.turn import Step


def _new_state():
    state = GameState()
    state.players.append(Player(id=0, agent=None))
    state.players.append(Player(id=1, agent=None))
    state.active_player_idx = 0
    state.priority_player_idx = 0
    state.step = Step.PRECOMBAT_MAIN
    return state


def _put_creature(state, name="Wild Bear", owner_id=0):
    obj = state.new_object(
        SYNTHETIC_CREATURES[name], owner_id=owner_id, zone=Zone.BATTLEFIELD,
    )
    state.battlefield.append(obj)
    return obj


def test_resolve_taps_and_stuns_untapped_creature():
    """Happy path: an untapped creature gets tapped and gains two
    stun counters."""
    state = _new_state()
    bear = _put_creature(state)
    assert not bear.tapped
    assert bear.stun_counters == 0

    TapAndStunUpToOneTargetCreature().resolve(
        state, 0, (("creature", bear.id),),
    )

    assert bear.tapped
    assert bear.stun_counters == 2
    assert any(
        "tapped" in line and "stun" in line for line in state.log
    )


def test_resolve_already_tapped_creature_only_stuns():
    """If the target is already tapped, the resolve doesn't double-tap
    but still adds the stun counters (Meat Locker is friend-or-foe)."""
    state = _new_state()
    bear = _put_creature(state)
    bear.tapped = True

    TapAndStunUpToOneTargetCreature().resolve(
        state, 0, (("creature", bear.id),),
    )

    assert bear.tapped  # remains tapped
    assert bear.stun_counters == 2


def test_resolve_custom_stun_amount_honored():
    """The dataclass param ``stun_amount`` flows through to the
    counter add (default is 2; verify a non-default value works)."""
    state = _new_state()
    bear = _put_creature(state)

    TapAndStunUpToOneTargetCreature(stun_amount=3).resolve(
        state, 0, (("creature", bear.id),),
    )

    assert bear.stun_counters == 3


def test_resolve_no_targets_is_silent_noop():
    """The 'up to one' shape allows zero-target casts. A no-target
    resolution must not crash."""
    state = _new_state()
    bear = _put_creature(state)

    TapAndStunUpToOneTargetCreature().resolve(state, 0, ())

    assert not bear.tapped
    assert bear.stun_counters == 0


def test_resolve_wrong_target_kind_is_noop():
    """If the target slot is not 'creature' the resolve bails before
    touching the battlefield."""
    state = _new_state()
    bear = _put_creature(state)

    TapAndStunUpToOneTargetCreature().resolve(
        state, 0, (("permanent", bear.id),),
    )

    assert not bear.tapped
    assert bear.stun_counters == 0


def test_resolve_missing_target_id_is_noop():
    """An ID that no longer exists on the battlefield is a silent
    no-op (the creature died between cast and resolve)."""
    state = _new_state()

    TapAndStunUpToOneTargetCreature().resolve(
        state, 0, (("creature", 999_999),),
    )
    # No exception, no log line about tapping.
    assert not any("tapped" in line for line in state.log)


def test_legal_targets_includes_any_creature():
    """Friend-or-foe, tapped-or-untapped: every creature on the
    battlefield is a legal target."""
    state = _new_state()
    own_bear = _put_creature(state, owner_id=0)
    opp_bear = _put_creature(state, owner_id=1)
    opp_bear.tapped = True

    legal = TapAndStunUpToOneTargetCreature().legal_targets(state, 0)
    target_ids = {tid for _, tid in legal}
    assert own_bear.id in target_ids
    assert opp_bear.id in target_ids


def test_target_count_range_is_zero_to_one():
    """``up to one`` shape: optional target slot."""
    eff = TapAndStunUpToOneTargetCreature()
    assert eff.requires_target() is False
    assert eff.target_count_range() == (0, 1)


def test_describe_text_mentions_amount():
    desc = TapAndStunUpToOneTargetCreature(stun_amount=2).describe()
    assert "tap" in desc.lower()
    assert "2" in desc
    assert "stun" in desc.lower()
