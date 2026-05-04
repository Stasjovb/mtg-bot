"""Tests for ``mtg_bot.training.replay_decisions``: JSON
serialization round-trip for every ``Decision`` subclass that the
engine adapter can emit at a priority moment."""

from __future__ import annotations

import pytest

from mtg_bot.actions import (
    ActivateAbility,
    ActivateStation,
    CastSpell,
    DeclareAttackers,
    DeclareBlockers,
    PassPriority,
    PlayLand,
    TurnFaceUp,
    UnlockRoomHalf,
)
from mtg_bot.search.combat_decisions import AttackerDecision, BlockerDecision
from mtg_bot.search.resolution_decisions import (
    ResolutionCardFromLibraryDecision,
    ResolutionCardFromOpponentHandDecision,
    ResolutionDevourLandsDecision,
    ResolutionDiscardDecision,
    ResolutionModeDecision,
    ResolutionSacrificeDecision,
    ResolutionShockLifeDecision,
    ResolutionSurveilDecision,
    ResolutionTargetDecision,
    ResolutionXDecision,
    ResolutionYesNoDecision,
)
from mtg_bot.training.replay_decisions import (
    decision_from_json,
    decision_to_json,
)


@pytest.mark.parametrize("decision", [
    PassPriority(),
    PlayLand(card_id=12),
    CastSpell(card_id=7),
    CastSpell(
        card_id=11, use_warp=True, kicked=True, cast_for_free=True,
        use_impending=True, cast_room_half="Library",
    ),
    UnlockRoomHalf(card_id=33, half_name="Lab"),
    ActivateAbility(source_id=42, ability_index=1),
    ActivateStation(spacecraft_id=99, crew_id=100),
    TurnFaceUp(card_id=5),
    DeclareAttackers(attacker_ids=frozenset({3, 7, 9})),
    DeclareAttackers(attacker_ids=frozenset()),
    DeclareBlockers(assignments=((11, 3), (12, 3), (13, 7))),
    DeclareBlockers(assignments=()),
    AttackerDecision(attacker_id=4, attack=True),
    AttackerDecision(attacker_id=5, attack=False),
    BlockerDecision(blocker_id=8, attacker_id=3),
    BlockerDecision(blocker_id=9, attacker_id=None),
    ResolutionTargetDecision(target=("creature", 17)),
    ResolutionTargetDecision(target=("player", 0)),
    ResolutionTargetDecision(target=None),
    ResolutionDiscardDecision(card_id=22),
    ResolutionModeDecision(mode_index=2),
    ResolutionSacrificeDecision(object_id=18),
    ResolutionXDecision(x_value=4),
    ResolutionSurveilDecision(mill=True),
    ResolutionSurveilDecision(mill=False),
    ResolutionShockLifeDecision(pay=True),
    ResolutionShockLifeDecision(pay=False),
    ResolutionCardFromLibraryDecision(card_id=14),
    ResolutionCardFromLibraryDecision(card_id=None),
    ResolutionCardFromOpponentHandDecision(card_id=21),
    ResolutionYesNoDecision(yes=True),
    ResolutionYesNoDecision(yes=False),
    ResolutionDevourLandsDecision(land_ids=()),
    ResolutionDevourLandsDecision(land_ids=(101, 102, 103)),
])
def test_round_trip(decision):
    """Every concrete Decision subtype round-trips through JSON
    without losing any field."""
    encoded = decision_to_json(decision)
    decoded = decision_from_json(encoded)
    assert decoded == decision
    # Re-encode the decoded — JSON shape is canonical (idempotent
    # under round-trip).
    assert decision_to_json(decoded) == encoded


def test_round_trip_via_json_string():
    """The JSON shape is actually JSON-serializable end to end (no
    tuples / sets / frozenset leaking through)."""
    import json

    decisions = [
        PassPriority(),
        DeclareAttackers(attacker_ids=frozenset({3, 7})),
        DeclareBlockers(assignments=((11, 3), (12, 7))),
        ResolutionTargetDecision(target=("creature", 5)),
        ResolutionTargetDecision(target=None),
        ResolutionDevourLandsDecision(land_ids=(1, 2, 3)),
    ]
    for d in decisions:
        s = json.dumps(decision_to_json(d))
        round_tripped = decision_from_json(json.loads(s))
        assert round_tripped == d


def test_attacker_ids_serialized_as_sorted_list():
    """frozenset has no inherent order; serialization must be
    deterministic (sorted) so the same decision always produces the
    same JSON byte string."""
    a = DeclareAttackers(attacker_ids=frozenset({9, 3, 7}))
    encoded = decision_to_json(a)
    assert encoded["attacker_ids"] == [3, 7, 9]


def test_unknown_kind_raises():
    with pytest.raises(ValueError, match="unknown kind"):
        decision_from_json({"kind": "MysteryAction"})


def test_unsupported_decision_type_raises():
    with pytest.raises(TypeError, match="unsupported decision type"):
        decision_to_json("not a decision")
