"""Tests for ``mtg_bot.training.state_tokenizer``.

Covers:

- Output shapes / dtypes match the StructuredModel input contract.
- Viewer-relative encoding swaps controller codes and redacts the
  opponent's hand to anonymous slots.
- Action-history filter drops ``PassPriority`` + mana-ability
  ``ActivateAbility`` events.
- N=32 truncation keeps only the most-recent filtered actions.
- ``ACTION_KIND_VOCAB`` matches the structured_model's vocab size and
  the engine's action / decision class names.
"""

from __future__ import annotations

import random

import numpy as np

from mtg_bot.actions import (
    ActivateAbility,
    CastSpell,
    DeclareAttackers,
    PassPriority,
    PlayLand,
)
from mtg_bot.agents import RandomAgent
from mtg_bot.cards.source import get_active_source
from mtg_bot.game import GameObject, GameState, Player, StackItem, Zone
from mtg_bot.search.combat_decisions import AttackerDecision, BlockerDecision
from mtg_bot.search.resolution_decisions import (
    ResolutionCardFromLibraryDecision,
    ResolutionSurveilDecision,
    ResolutionTargetDecision,
)
from mtg_bot.simulate import setup_game
from mtg_bot.training.state_tokenizer import (
    ACTION_KIND_VOCAB,
    CONTROLLER_OPPONENT,
    CONTROLLER_VIEWER,
    DEFAULT_ACTION_HISTORY_N,
    PRINTING_NA,
    VARIANT_PRIVATE_CHOICE,
    ActionEvent,
    printing_id,
    tokenize_state,
)
from mtg_bot.training.structured_model import (
    ACTION_KIND_VOCAB_SIZE,
    EMB_FIELD_ACTION_KIND,
    EMB_FIELD_CONTROLLER,
    EMB_FIELD_PRINTING,
    EMB_FIELD_TARGET_PRINTING,
    EMB_FIELD_VARIANT,
    N_EMB_FIELDS,
    N_SCALAR_FIELDS,
    SCALAR_FIELD_PUBLIC_MASK,
    SCALAR_FIELD_TURN_OFFSET,
    TOKEN_TYPE_ACTION_EVENT,
    TOKEN_TYPE_GLOBAL,
    TOKEN_TYPE_HAND_OPPONENT,
    TOKEN_TYPE_HAND_VIEWER,
    TOKEN_TYPE_PERMANENT_OPPONENT,
    TOKEN_TYPE_PERMANENT_VIEWER,
    TOKEN_TYPE_STACK_ITEM,
)
from mtg_bot.turn import Step

from tests._test_decks import simple_test_decklists


# ---------------------------------------------------------------------
# Vocab consistency
# ---------------------------------------------------------------------


def test_action_kind_vocab_has_22_entries() -> None:
    assert len(ACTION_KIND_VOCAB) == 22


def test_action_kind_vocab_size_matches_structured_model() -> None:
    """NA + 22 kinds = 23. Pinned by both modules."""
    assert ACTION_KIND_VOCAB_SIZE == len(ACTION_KIND_VOCAB) + 1


def test_action_kind_vocab_ids_are_a_1_to_22_permutation() -> None:
    """Ids 1..22 are claimed exactly once each; 0 stays reserved for NA."""
    assert set(ACTION_KIND_VOCAB.values()) == set(range(1, 23))


def test_action_kind_vocab_covers_all_priority_and_decision_types() -> None:
    """Every Action subclass and every Decision class the engine
    surfaces must have an entry. If a new kind lands the test surfaces
    the gap immediately."""
    expected = {
        # 9 priority actions
        "PassPriority", "PlayLand", "CastSpell", "UnlockRoomHalf",
        "ActivateAbility", "ActivateStation", "TurnFaceUp",
        "DeclareAttackers", "DeclareBlockers",
        # 2 combat decisions
        "AttackerDecision", "BlockerDecision",
        # 11 resolution decisions
        "ResolutionTargetDecision", "ResolutionDiscardDecision",
        "ResolutionModeDecision", "ResolutionSacrificeDecision",
        "ResolutionXDecision", "ResolutionSurveilDecision",
        "ResolutionShockLifeDecision", "ResolutionCardFromLibraryDecision",
        "ResolutionCardFromOpponentHandDecision",
        "ResolutionYesNoDecision", "ResolutionDevourLandsDecision",
    }
    assert set(ACTION_KIND_VOCAB.keys()) == expected


# ---------------------------------------------------------------------
# Shape / dtype invariants
# ---------------------------------------------------------------------


def _make_simple_engine(seed: int = 42) -> GameState:
    """Build a real engine state from the small test deck pool."""
    agents = [
        RandomAgent(rng=random.Random(seed)),
        RandomAgent(rng=random.Random(seed + 1)),
    ]
    return setup_game(
        agents, decks=simple_test_decklists(), seed=seed,
    )


def test_output_keys_and_dtypes_match_model_contract() -> None:
    engine = _make_simple_engine()
    out = tokenize_state(engine, viewer_id=0)
    assert set(out.keys()) == {
        "token_type", "token_emb_ids", "token_scalars", "attention_mask",
    }
    assert out["token_type"].dtype == np.int64
    assert out["token_emb_ids"].dtype == np.int64
    assert out["token_scalars"].dtype == np.float32
    assert out["attention_mask"].dtype == np.bool_


def test_output_shapes_match_model_input_contract() -> None:
    engine = _make_simple_engine()
    out = tokenize_state(engine, viewer_id=0)
    seq_len = out["token_type"].shape[0]
    assert out["token_type"].shape == (seq_len,)
    assert out["token_emb_ids"].shape == (seq_len, N_EMB_FIELDS)
    assert out["token_scalars"].shape == (seq_len, N_SCALAR_FIELDS)
    assert out["attention_mask"].shape == (seq_len,)


def test_attention_mask_is_all_true_for_real_tokens() -> None:
    """Tokenizer doesn't pad — every emitted row is a real token."""
    engine = _make_simple_engine()
    out = tokenize_state(engine, viewer_id=0)
    assert bool(out["attention_mask"].all())


def test_tokenizer_does_not_emit_cls() -> None:
    """Per §6: the model prepends its own CLS. The tokenizer's first
    emitted token must NOT be a CLS — TOKEN_TYPE_CLS=0 is reserved by
    the model and the tokenizer's first row should be the global
    summary token (TOKEN_TYPE_GLOBAL=1)."""
    engine = _make_simple_engine()
    out = tokenize_state(engine, viewer_id=0)
    assert out["token_type"][0] == TOKEN_TYPE_GLOBAL


# ---------------------------------------------------------------------
# Empty / minimal states
# ---------------------------------------------------------------------


def _empty_state(viewer_hand_size: int = 0, opp_hand_size: int = 0) -> GameState:
    """Construct a minimal valid GameState by hand. No battlefield,
    no stack, no permanents — just two players with the requested
    hand sizes. Library / graveyard / exile empty.
    """
    printings = get_active_source().get_printings()
    # Pick any printing for the hand fixture (real or basic).
    sample_printing = printings["Forest"] if "Forest" in printings else next(
        iter(printings.values())
    )
    p0_hand = [
        GameObject(
            id=10_000 + i, printing=sample_printing,
            owner_id=0, controller_id=0, zone=Zone.HAND,
        )
        for i in range(viewer_hand_size)
    ]
    p1_hand = [
        GameObject(
            id=20_000 + i, printing=sample_printing,
            owner_id=1, controller_id=1, zone=Zone.HAND,
        )
        for i in range(opp_hand_size)
    ]
    state = GameState(
        players=[
            Player(id=0, hand=p0_hand),
            Player(id=1, hand=p1_hand),
        ],
        battlefield=[],
        stack=[],
        active_player_idx=0,
        priority_player_idx=0,
        turn_number=1,
        step=Step.PRECOMBAT_MAIN,
    )
    return state


def test_empty_state_produces_only_the_global_token() -> None:
    state = _empty_state()
    out = tokenize_state(state, viewer_id=0)
    assert out["token_type"].shape == (1,)
    assert out["token_type"][0] == TOKEN_TYPE_GLOBAL


def test_single_permanent_emits_two_tokens() -> None:
    """Global + one permanent = 2 tokens."""
    state = _empty_state()
    printings = get_active_source().get_printings()
    forest = printings["Forest"]
    obj = GameObject(
        id=42, printing=forest, owner_id=0, controller_id=0,
        zone=Zone.BATTLEFIELD,
    )
    state.battlefield.append(obj)
    out = tokenize_state(state, viewer_id=0)
    assert out["token_type"].shape == (2,)
    assert out["token_type"][0] == TOKEN_TYPE_GLOBAL
    assert out["token_type"][1] == TOKEN_TYPE_PERMANENT_VIEWER


def test_full_hand_emits_one_token_per_card() -> None:
    state = _empty_state(viewer_hand_size=7)
    out = tokenize_state(state, viewer_id=0)
    # Global + 7 hand tokens.
    assert out["token_type"].shape == (8,)
    hand_tokens = out["token_type"][1:]
    assert all(t == TOKEN_TYPE_HAND_VIEWER for t in hand_tokens.tolist())


def test_stack_with_one_spell_emits_a_stack_token() -> None:
    state = _empty_state()
    printings = get_active_source().get_printings()
    sample = next(iter(printings.values()))
    spell_obj = GameObject(
        id=99, printing=sample, owner_id=0, controller_id=0,
        zone=Zone.STACK,
    )
    state.stack.append(
        StackItem(source=spell_obj, controller_id=0, targets=()),
    )
    out = tokenize_state(state, viewer_id=0)
    # Global + stack item.
    assert out["token_type"].shape == (2,)
    assert out["token_type"][1] == TOKEN_TYPE_STACK_ITEM


# ---------------------------------------------------------------------
# Viewer-relativeness
# ---------------------------------------------------------------------


def test_controller_codes_swap_with_viewer() -> None:
    """A permanent controlled by player 0 should encode as
    ``CONTROLLER_VIEWER`` from viewer=0's perspective and
    ``CONTROLLER_OPPONENT`` from viewer=1's."""
    state = _empty_state()
    printings = get_active_source().get_printings()
    forest = printings["Forest"]
    state.battlefield.append(GameObject(
        id=42, printing=forest, owner_id=0, controller_id=0,
        zone=Zone.BATTLEFIELD,
    ))
    out0 = tokenize_state(state, viewer_id=0)
    out1 = tokenize_state(state, viewer_id=1)
    # Token index 1 is the permanent.
    assert out0["token_type"][1] == TOKEN_TYPE_PERMANENT_VIEWER
    assert out1["token_type"][1] == TOKEN_TYPE_PERMANENT_OPPONENT
    assert out0["token_emb_ids"][1, EMB_FIELD_CONTROLLER] == CONTROLLER_VIEWER
    assert out1["token_emb_ids"][1, EMB_FIELD_CONTROLLER] == CONTROLLER_OPPONENT


def test_opponent_hand_emits_anonymous_tokens_with_correct_cardinality() -> None:
    """From the non-owner viewer's perspective the opponent's hand is
    hidden: tokens with token_type=TOKEN_TYPE_HAND_OPPONENT,
    printing=NA, public_mask=0. Cardinality matches actual hand size.
    """
    state = _empty_state(opp_hand_size=4)
    out = tokenize_state(state, viewer_id=0)
    # Global + 4 anonymous opp-hand tokens.
    assert out["token_type"].shape == (5,)
    opp_tokens = out["token_type"][1:]
    assert all(t == TOKEN_TYPE_HAND_OPPONENT for t in opp_tokens.tolist())
    # Every printing slot is NA.
    assert (out["token_emb_ids"][1:, EMB_FIELD_PRINTING] == PRINTING_NA).all()
    # public_mask is 0 for every opp-hand row.
    assert (out["token_scalars"][1:, SCALAR_FIELD_PUBLIC_MASK] == 0.0).all()


def test_viewer_sees_own_hand_with_real_printings() -> None:
    state = _empty_state(viewer_hand_size=3)
    out = tokenize_state(state, viewer_id=0)
    # Global + 3 visible hand tokens.
    hand_rows = out["token_emb_ids"][1:]
    # Real printing ids (non-NA) for every viewer-hand card.
    assert (hand_rows[:, EMB_FIELD_PRINTING] != PRINTING_NA).all()
    # public_mask = 1 for viewer hand.
    assert (out["token_scalars"][1:, SCALAR_FIELD_PUBLIC_MASK] == 1.0).all()


# ---------------------------------------------------------------------
# Action history filter + N truncation
# ---------------------------------------------------------------------


def _land_action_event(state: GameState, turn: int = 1) -> ActionEvent:
    """Build a PlayLand ActionEvent — passes the §3 filter."""
    # Find a land in player 0's hand if any; otherwise fabricate one.
    state_pre = state
    if state.players and state.players[0].hand:
        land_id = state.players[0].hand[0].id
    else:
        land_id = 9999
    return ActionEvent(
        action=PlayLand(card_id=land_id),
        state_snapshot=state_pre,
        turn=turn,
        step=Step.PRECOMBAT_MAIN,
        actor_player_id=0,
    )


def _pass_priority_event(state: GameState) -> ActionEvent:
    return ActionEvent(
        action=PassPriority(),
        state_snapshot=state,
        turn=1,
        step=Step.PRECOMBAT_MAIN,
        actor_player_id=0,
    )


def _mana_ability_event(state: GameState, source_id: int) -> ActionEvent:
    """Activate a land's mana ability — should be filtered out."""
    return ActionEvent(
        action=ActivateAbility(source_id=source_id, ability_index=0),
        state_snapshot=state,
        turn=1,
        step=Step.PRECOMBAT_MAIN,
        actor_player_id=0,
    )


def test_pass_priority_events_are_filtered() -> None:
    state = _empty_state()
    events = [_pass_priority_event(state) for _ in range(5)]
    out = tokenize_state(state, viewer_id=0, recent_actions=events)
    # No action tokens emitted — only the global token.
    assert out["token_type"].shape == (1,)


def test_mana_ability_events_are_filtered() -> None:
    """ActivateAbility on a Forest is treated as a mana ability and
    dropped."""
    state = _empty_state()
    printings = get_active_source().get_printings()
    forest = printings["Forest"]
    land_obj = GameObject(
        id=42, printing=forest, owner_id=0, controller_id=0,
        zone=Zone.BATTLEFIELD,
    )
    state.battlefield.append(land_obj)
    # Activate ability on the land (a mana ability heuristically).
    events = [_mana_ability_event(state, source_id=42)]
    out = tokenize_state(state, viewer_id=0, recent_actions=events)
    # Global + permanent only — the mana ability was filtered.
    action_tokens = [
        t for t in out["token_type"].tolist()
        if t == TOKEN_TYPE_ACTION_EVENT
    ]
    assert action_tokens == []


def test_interleaved_filter_keeps_only_real_actions() -> None:
    """Mix of strategic + filtered actions — only strategic land."""
    state = _empty_state(viewer_hand_size=1)
    pass_ev = _pass_priority_event(state)
    land_ev = _land_action_event(state, turn=1)
    events = [pass_ev, pass_ev, land_ev, pass_ev, land_ev, pass_ev]
    out = tokenize_state(state, viewer_id=0, recent_actions=events)
    action_tokens = [
        t for t in out["token_type"].tolist()
        if t == TOKEN_TYPE_ACTION_EVENT
    ]
    assert len(action_tokens) == 2  # two land-play events


def test_n_truncation_keeps_only_last_n_filtered_actions() -> None:
    """With 50 strategic events and N=32, we keep the LAST 32."""
    state = _empty_state(viewer_hand_size=1)
    events = [_land_action_event(state, turn=i + 1) for i in range(50)]
    out = tokenize_state(state, viewer_id=0, recent_actions=events, n=32)
    action_tokens = [
        t for t in out["token_type"].tolist()
        if t == TOKEN_TYPE_ACTION_EVENT
    ]
    assert len(action_tokens) == 32


def test_n_truncation_keeps_the_most_recent_events() -> None:
    """When we feed unique action turns 1..40 and truncate to N=10,
    the kept events should be turns 31..40 (the recent tail)."""
    state = _empty_state(viewer_hand_size=1)
    state.turn_number = 41
    events = [_land_action_event(state, turn=i + 1) for i in range(40)]
    out = tokenize_state(state, viewer_id=0, recent_actions=events, n=10)
    # The turn_offset scalar carries (action_turn - current_turn) / 16
    # clamped to [-16, 0]. Older events get more negative offsets.
    # If we keep events 31..40 (turn_offset = -10, -9, ..., -1), the
    # smallest offset (most negative) should be -10/16. If the kept
    # events were 1..10 it would be -16/16 (clamped).
    state_tok_scalars = out["token_scalars"]
    action_rows = (
        out["token_type"] == TOKEN_TYPE_ACTION_EVENT
    )
    action_offsets = state_tok_scalars[action_rows, SCALAR_FIELD_TURN_OFFSET]
    assert action_offsets.shape[0] == 10
    # Smallest (most negative) offset should be -10/16 ≈ -0.625, NOT
    # -1.0 (which would be clamped from events further back).
    assert action_offsets.min() > -0.7  # -10/16 = -0.625


def test_default_n_is_32() -> None:
    """The roadmap §3 default is 32. Pinned by a module-level constant."""
    assert DEFAULT_ACTION_HISTORY_N == 32


# ---------------------------------------------------------------------
# Private-info redaction
# ---------------------------------------------------------------------


def test_surveil_decision_is_private_to_actor() -> None:
    """Surveil's mill-or-keep choice is private. The actor sees the
    real variant; the non-actor sees ``VARIANT_PRIVATE_CHOICE`` and
    public_mask=0."""
    state = _empty_state()
    ev = ActionEvent(
        action=ResolutionSurveilDecision(mill=True),
        state_snapshot=state,
        turn=1,
        step=Step.PRECOMBAT_MAIN,
        actor_player_id=0,
    )
    out_actor = tokenize_state(state, viewer_id=0, recent_actions=[ev])
    out_other = tokenize_state(state, viewer_id=1, recent_actions=[ev])
    # Find the action-token row in each.
    action_rows_actor = (
        out_actor["token_type"] == TOKEN_TYPE_ACTION_EVENT
    )
    action_rows_other = (
        out_other["token_type"] == TOKEN_TYPE_ACTION_EVENT
    )
    actor_variant = out_actor["token_emb_ids"][
        action_rows_actor, EMB_FIELD_VARIANT
    ][0]
    other_variant = out_other["token_emb_ids"][
        action_rows_other, EMB_FIELD_VARIANT
    ][0]
    assert other_variant == VARIANT_PRIVATE_CHOICE
    assert actor_variant != VARIANT_PRIVATE_CHOICE
    # public_mask differs.
    assert out_actor["token_scalars"][
        action_rows_actor, SCALAR_FIELD_PUBLIC_MASK
    ][0] == 1.0
    assert out_other["token_scalars"][
        action_rows_other, SCALAR_FIELD_PUBLIC_MASK
    ][0] == 0.0


def test_card_from_library_redacts_target_for_non_actor() -> None:
    """Tutor pick is private. Non-actor sees target_printing=NA +
    public_mask=0."""
    state = _empty_state()
    # Fabricate a printing-bearing card id in actor's library.
    printings = get_active_source().get_printings()
    tutored = next(iter(printings.values()))
    obj = GameObject(
        id=777, printing=tutored, owner_id=0, controller_id=0,
        zone=Zone.LIBRARY,
    )
    state.players[0].library.append(obj)
    ev = ActionEvent(
        action=ResolutionCardFromLibraryDecision(card_id=777),
        state_snapshot=state,
        turn=1,
        step=Step.PRECOMBAT_MAIN,
        actor_player_id=0,
    )
    out_actor = tokenize_state(state, viewer_id=0, recent_actions=[ev])
    out_other = tokenize_state(state, viewer_id=1, recent_actions=[ev])
    action_rows_actor = (
        out_actor["token_type"] == TOKEN_TYPE_ACTION_EVENT
    )
    action_rows_other = (
        out_other["token_type"] == TOKEN_TYPE_ACTION_EVENT
    )
    actor_target = out_actor["token_emb_ids"][
        action_rows_actor, EMB_FIELD_TARGET_PRINTING
    ][0]
    other_target = out_other["token_emb_ids"][
        action_rows_other, EMB_FIELD_TARGET_PRINTING
    ][0]
    # Actor knows the tutored card.
    assert actor_target != PRINTING_NA
    # Non-actor doesn't.
    assert other_target == PRINTING_NA
    # public_mask 0 for non-actor.
    assert out_other["token_scalars"][
        action_rows_other, SCALAR_FIELD_PUBLIC_MASK
    ][0] == 0.0


# ---------------------------------------------------------------------
# Action token expansion / coverage
# ---------------------------------------------------------------------


def test_declare_attackers_expands_to_one_token_per_attacker() -> None:
    """Per roadmap §3, declare-attackers tokens are emitted one per
    attacker (fixed per-token shape)."""
    state = _empty_state()
    printings = get_active_source().get_printings()
    creature_printing = next(iter(printings.values()))
    for cid in (1, 2, 3):
        state.battlefield.append(GameObject(
            id=cid, printing=creature_printing,
            owner_id=0, controller_id=0, zone=Zone.BATTLEFIELD,
        ))
    ev = ActionEvent(
        action=DeclareAttackers(attacker_ids=frozenset({1, 2, 3})),
        state_snapshot=state,
        turn=1,
        step=Step.DECLARE_ATTACKERS,
        actor_player_id=0,
    )
    out = tokenize_state(state, viewer_id=0, recent_actions=[ev])
    action_rows = [
        t for t in out["token_type"].tolist()
        if t == TOKEN_TYPE_ACTION_EVENT
    ]
    assert len(action_rows) == 3


def test_attacker_decision_token_carries_action_kind() -> None:
    """AttackerDecision shows up as its own action-kind vocab entry."""
    state = _empty_state()
    ev = ActionEvent(
        action=AttackerDecision(attacker_id=99, attack=True),
        state_snapshot=state,
        turn=1,
        step=Step.DECLARE_ATTACKERS,
        actor_player_id=0,
    )
    out = tokenize_state(state, viewer_id=0, recent_actions=[ev])
    action_rows = (
        out["token_type"] == TOKEN_TYPE_ACTION_EVENT
    )
    kind_id = out["token_emb_ids"][action_rows, EMB_FIELD_ACTION_KIND][0]
    assert kind_id == ACTION_KIND_VOCAB["AttackerDecision"]


def test_blocker_decision_carries_attacker_target_kind() -> None:
    state = _empty_state()
    printings = get_active_source().get_printings()
    creature_printing = next(iter(printings.values()))
    state.battlefield.append(GameObject(
        id=10, printing=creature_printing,
        owner_id=0, controller_id=0, zone=Zone.BATTLEFIELD,
    ))
    state.battlefield.append(GameObject(
        id=11, printing=creature_printing,
        owner_id=1, controller_id=1, zone=Zone.BATTLEFIELD,
    ))
    ev = ActionEvent(
        action=BlockerDecision(blocker_id=10, attacker_id=11),
        state_snapshot=state,
        turn=1,
        step=Step.DECLARE_BLOCKERS,
        actor_player_id=0,
    )
    out = tokenize_state(state, viewer_id=0, recent_actions=[ev])
    action_rows = (
        out["token_type"] == TOKEN_TYPE_ACTION_EVENT
    )
    kind_id = out["token_emb_ids"][action_rows, EMB_FIELD_ACTION_KIND][0]
    assert kind_id == ACTION_KIND_VOCAB["BlockerDecision"]


def test_target_decision_records_target_printing() -> None:
    state = _empty_state()
    printings = get_active_source().get_printings()
    creature_printing = next(iter(printings.values()))
    state.battlefield.append(GameObject(
        id=7, printing=creature_printing,
        owner_id=1, controller_id=1, zone=Zone.BATTLEFIELD,
    ))
    ev = ActionEvent(
        action=ResolutionTargetDecision(target=("permanent", 7)),
        state_snapshot=state,
        turn=1,
        step=Step.PRECOMBAT_MAIN,
        actor_player_id=0,
    )
    out = tokenize_state(state, viewer_id=0, recent_actions=[ev])
    action_rows = (
        out["token_type"] == TOKEN_TYPE_ACTION_EVENT
    )
    target = out["token_emb_ids"][
        action_rows, EMB_FIELD_TARGET_PRINTING
    ][0]
    assert target != PRINTING_NA


def test_cast_spell_records_source_printing() -> None:
    state = _empty_state(viewer_hand_size=0)
    printings = get_active_source().get_printings()
    spell_printing = next(
        p for name, p in printings.items()
        if "Land" not in p.card_types
    )
    spell_card = GameObject(
        id=55, printing=spell_printing, owner_id=0, controller_id=0,
        zone=Zone.HAND,
    )
    state.players[0].hand.append(spell_card)
    ev = ActionEvent(
        action=CastSpell(card_id=55),
        state_snapshot=state,
        turn=1,
        step=Step.PRECOMBAT_MAIN,
        actor_player_id=0,
    )
    out = tokenize_state(state, viewer_id=0, recent_actions=[ev])
    action_rows = (
        out["token_type"] == TOKEN_TYPE_ACTION_EVENT
    )
    source = out["token_emb_ids"][
        action_rows, EMB_FIELD_PRINTING
    ][0]
    assert source != PRINTING_NA


# ---------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------


def test_none_state_raises() -> None:
    import pytest
    with pytest.raises(ValueError, match="state must not be None"):
        tokenize_state(None, viewer_id=0)


def test_unknown_viewer_id_raises() -> None:
    import pytest
    state = _empty_state()
    with pytest.raises(ValueError, match="not found in state"):
        tokenize_state(state, viewer_id=99)


def test_printing_id_for_none_returns_na() -> None:
    assert printing_id(None) == PRINTING_NA


def test_printing_id_caps_to_vocab_size() -> None:
    """A small ``n_printings_cap`` forces high ids into the modulo
    overflow bucket."""
    printings = get_active_source().get_printings()
    sample = next(iter(printings.values()))
    # Cap of 4 means valid ids are {0, 1, 2, 3} — overflow buckets
    # past id 3 into the range [1, 3].
    pid = printing_id(sample, n_printings_cap=4)
    assert 1 <= pid <= 3 or pid == PRINTING_NA


# ---------------------------------------------------------------------
# End-to-end smoke — real engine plays a few decisions
# ---------------------------------------------------------------------


def test_tokenize_real_engine_state_after_a_few_moves() -> None:
    """Plays a couple of decisions through MtgGameStateAdapter and
    confirms the tokenizer handles the resulting state shape."""
    from mtg_bot.search.engine_adapter import MtgGameStateAdapter

    engine = _make_simple_engine(seed=7)
    adapter = MtgGameStateAdapter(engine)
    # Drive a few decisions deterministically with a tactical default.
    for _ in range(5):
        if adapter.is_terminal():
            break
        decisions = list(adapter.legal_decisions())
        if not decisions:
            break
        adapter.apply(decisions[0])
    out0 = tokenize_state(engine, viewer_id=0)
    out1 = tokenize_state(engine, viewer_id=1)
    # Same seq_len from both perspectives (zone cardinality is symmetric
    # at this depth — hand visibility flips but total slot count holds).
    assert out0["token_type"].shape[0] == out1["token_type"].shape[0]
