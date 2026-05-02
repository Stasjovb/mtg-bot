"""Engine-resolve tests for ``UntapTargetOtherPermanent``.

Nanoform Sentinel's "untap another target permanent" trigger only had
parser-shape coverage (test_parser_effects_batch18.py) and a describe
test. This file covers the resolve body's defensive branches plus the
``legal_targets`` filter that excludes the source and untapped
permanents.
"""

from __future__ import annotations

from mtg_bot.cards import SYNTHETIC_CREATURES
from mtg_bot.effects.generic import UntapTargetOtherPermanent
from mtg_bot.game import GameState, Player, Zone


def _new_state():
    state = GameState()
    state.players.append(Player(id=0, agent=None))
    state.players.append(Player(id=1, agent=None))
    state.active_player_idx = 0
    state.priority_player_idx = 0
    return state


def _put(state, name, owner_id=0, tapped=False):
    obj = state.new_object(
        SYNTHETIC_CREATURES[name],
        owner_id=owner_id, zone=Zone.BATTLEFIELD,
    )
    obj.controller_id = owner_id
    obj.tapped = tapped
    state.battlefield.append(obj)
    return obj


def test_resolve_untaps_tapped_target():
    state = _new_state()
    src = _put(state, "Battlefield Recruit")
    tgt = _put(state, "Stalwart Knight", tapped=True)
    state.resolving_source = src

    UntapTargetOtherPermanent().resolve(
        state, 0, (("permanent", tgt.id),),
    )

    assert tgt.tapped is False
    assert any("Stalwart Knight is untapped" in line for line in state.log)


def test_resolve_no_op_no_targets():
    state = _new_state()
    tgt = _put(state, "Stalwart Knight", tapped=True)
    state.resolving_source = _put(state, "Battlefield Recruit")

    UntapTargetOtherPermanent().resolve(state, 0, ())

    assert tgt.tapped is True
    assert state.log == []


def test_resolve_no_op_wrong_target_kind():
    state = _new_state()
    src = _put(state, "Battlefield Recruit")
    tgt = _put(state, "Stalwart Knight", tapped=True)
    state.resolving_source = src

    UntapTargetOtherPermanent().resolve(
        state, 0, (("creature", tgt.id),),
    )

    # Body bails on kind mismatch — target stays tapped.
    assert tgt.tapped is True
    assert state.log == []


def test_resolve_no_op_missing_target_id():
    state = _new_state()
    src = _put(state, "Battlefield Recruit")
    state.resolving_source = src

    UntapTargetOtherPermanent().resolve(
        state, 0, (("permanent", 999_999),),
    )

    assert state.log == []


def test_resolve_no_op_target_already_untapped():
    state = _new_state()
    src = _put(state, "Battlefield Recruit")
    tgt = _put(state, "Stalwart Knight", tapped=False)
    state.resolving_source = src

    UntapTargetOtherPermanent().resolve(
        state, 0, (("permanent", tgt.id),),
    )

    assert tgt.tapped is False
    # No log line because the body bails before logging.
    assert state.log == []


def test_legal_targets_excludes_source_and_untapped():
    state = _new_state()
    src = _put(state, "Battlefield Recruit", tapped=True)
    untapped_other = _put(state, "Stalwart Knight", tapped=False)
    tapped_other = _put(state, "Sky Sentinel", tapped=True)
    state.resolving_source = src

    legal = UntapTargetOtherPermanent().legal_targets(state, 0)
    target_ids = {tid for _, tid in legal}

    assert tapped_other.id in target_ids
    assert untapped_other.id not in target_ids
    # Source is tapped but excluded by id-equality check.
    assert src.id not in target_ids


def test_legal_targets_with_no_source_treats_id_as_minus_one():
    """Defensive branch: no resolving_source → ``source_id = -1``,
    so every tapped permanent is legal (no permanent has id -1)."""
    state = _new_state()
    a = _put(state, "Battlefield Recruit", tapped=True)
    b = _put(state, "Stalwart Knight", tapped=True)
    state.resolving_source = None

    legal = UntapTargetOtherPermanent().legal_targets(state, 0)
    target_ids = {tid for _, tid in legal}

    assert a.id in target_ids
    assert b.id in target_ids


def test_describe_text():
    desc = UntapTargetOtherPermanent().describe()
    assert "untap" in desc
    assert "another target permanent" in desc
