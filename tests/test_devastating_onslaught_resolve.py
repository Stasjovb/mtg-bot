"""Engine-resolve tests for ``CreateXTokensOfTargetPermanentWithHasteEndStepSac``.

The parser-shape tests in ``tests/test_parser_effects_batch16.py`` cover
recognition of Devastating Onslaught's three-sentence body, but no test
exercises the resolve path that mints X token copies, grants haste UEOT,
and schedules end-step sacrifices. These tests run the effect against
synthetic battlefield fixtures and verify:

- token-copy creation count == ``state.resolving_x_value``;
- each minted token uses the target's printing;
- each token has temporary ``haste`` until end of turn;
- a ``SacrificeSourceDelayed`` delayed trigger is scheduled per token.
"""

from __future__ import annotations

from mtg_bot.agents import Agent
from mtg_bot.cards import SYNTHETIC_CREATURES
from mtg_bot.effects.generic import (
    CreateXTokensOfTargetPermanentWithHasteEndStepSac,
    SacrificeSourceDelayed,
)
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.turn import Step


class _NoopAgent(Agent):
    pass


def _new_state() -> GameState:
    state = GameState()
    state.players.append(Player(id=0, agent=_NoopAgent()))
    state.players.append(Player(id=1, agent=_NoopAgent()))
    state.active_player_idx = 0
    state.priority_player_idx = 0
    state.step = Step.PRECOMBAT_MAIN
    state.turn_number = 1
    return state


def _put(state, printing, owner_id=0):
    obj = state.new_object(printing, owner_id, Zone.BATTLEFIELD)
    state.battlefield.append(obj)
    return obj


def test_resolve_creates_x_token_copies_of_target():
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)

    state.resolving_x_value = 3
    CreateXTokensOfTargetPermanentWithHasteEndStepSac().resolve(
        state, controller_id=0, targets=(("permanent", bear.id),),
    )

    copies = [
        o for o in state.battlefield
        if o.id != bear.id and o.printing is bear.printing
    ]
    assert len(copies) == 3
    assert all(c.controller_id == 0 for c in copies)


def test_resolve_grants_haste_via_continuous_effect():
    """Each minted token must be the recipient of an
    ``ApplyEffect(GrantKeywords({"haste"}), EndOfTurn())`` write — surfaces
    as a layer-6/grant_keyword continuous effect entry per token."""
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)

    state.resolving_x_value = 2
    CreateXTokensOfTargetPermanentWithHasteEndStepSac().resolve(
        state, 0, (("permanent", bear.id),),
    )
    copies = [
        o for o in state.battlefield
        if o.id != bear.id and o.printing is bear.printing
    ]
    assert len(copies) == 2

    from mtg_bot.game import effective_keywords
    for c in copies:
        assert "haste" in effective_keywords(state, c)


def test_resolve_schedules_sacrifice_delayed_trigger_per_token():
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)

    state.resolving_x_value = 4
    CreateXTokensOfTargetPermanentWithHasteEndStepSac().resolve(
        state, 0, (("permanent", bear.id),),
    )
    copies = [
        o for o in state.battlefield
        if o.id != bear.id and o.printing is bear.printing
    ]
    sac_triggers = [
        t for t in state.delayed_triggers
        if isinstance(t.get("effect"), SacrificeSourceDelayed)
    ]
    assert len(sac_triggers) == len(copies) == 4
    scheduled_source_ids = {t["source_id"] for t in sac_triggers}
    assert scheduled_source_ids == {c.id for c in copies}
    # All scheduled to fire at the current turn's end step.
    assert all(t["fire_at_turn"] == state.turn_number for t in sac_triggers)
    assert all(t["controller_id"] == 0 for t in sac_triggers)


def test_resolve_zero_x_creates_no_tokens():
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    pre_count = len(state.battlefield)

    state.resolving_x_value = 0
    CreateXTokensOfTargetPermanentWithHasteEndStepSac().resolve(
        state, 0, (("permanent", bear.id),),
    )
    assert len(state.battlefield) == pre_count
    assert state.delayed_triggers == []


def test_resolve_no_targets_is_noop():
    state = _new_state()
    pre_count = len(state.battlefield)
    state.resolving_x_value = 3
    CreateXTokensOfTargetPermanentWithHasteEndStepSac().resolve(
        state, 0, (),
    )
    assert len(state.battlefield) == pre_count
    assert state.delayed_triggers == []


def test_resolve_missing_target_is_noop():
    state = _new_state()
    pre_count = len(state.battlefield)
    state.resolving_x_value = 3
    CreateXTokensOfTargetPermanentWithHasteEndStepSac().resolve(
        state, 0, (("permanent", 999_999),),
    )
    assert len(state.battlefield) == pre_count
    assert state.delayed_triggers == []


def test_legal_targets_includes_own_artifacts_and_creatures_only():
    state = _new_state()
    own_creature = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    opp_creature = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=1)

    legal = (
        CreateXTokensOfTargetPermanentWithHasteEndStepSac()
        .legal_targets(state, controller_id=0)
    )
    legal_ids = {tid for _, tid in legal}
    assert own_creature.id in legal_ids
    assert opp_creature.id not in legal_ids


def test_describe_text_mentions_x_haste_and_sacrifice():
    text = CreateXTokensOfTargetPermanentWithHasteEndStepSac().describe()
    assert "X" in text
    assert "haste" in text.lower()
    assert "sacrifice" in text.lower()


def test_resolve_logs_count_and_target_name():
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)

    state.resolving_x_value = 5
    CreateXTokensOfTargetPermanentWithHasteEndStepSac().resolve(
        state, 0, (("permanent", bear.id),),
    )
    assert any(
        "Devastating Onslaught creates 5 copies of Wild Bear" in line
        for line in state.log
    )
