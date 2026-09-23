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
    N_SCALAR_FIELDS_V2,
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
    # Default tokenizer schema is v2 (board / life state slots).
    assert out["token_scalars"].shape == (seq_len, N_SCALAR_FIELDS_V2)
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


def test_zones_populated_emit_their_tokens() -> None:
    """Cards in the viewer's graveyard / exile and the opponent's
    graveyard / exile each produce one token of the appropriate
    type."""
    from mtg_bot.training.structured_model import (
        TOKEN_TYPE_EXILE_OPPONENT, TOKEN_TYPE_EXILE_VIEWER,
        TOKEN_TYPE_GRAVEYARD_OPPONENT, TOKEN_TYPE_GRAVEYARD_VIEWER,
    )
    state = _empty_state()
    printings = get_active_source().get_printings()
    sample = next(iter(printings.values()))
    # Viewer graveyard + exile.
    state.players[0].graveyard.append(GameObject(
        id=100, printing=sample, owner_id=0, controller_id=0,
        zone=Zone.GRAVEYARD,
    ))
    state.players[0].exile.append(GameObject(
        id=101, printing=sample, owner_id=0, controller_id=0,
        zone=Zone.EXILE,
    ))
    # Opponent graveyard + exile.
    state.players[1].graveyard.append(GameObject(
        id=200, printing=sample, owner_id=1, controller_id=1,
        zone=Zone.GRAVEYARD,
    ))
    state.players[1].exile.append(GameObject(
        id=201, printing=sample, owner_id=1, controller_id=1,
        zone=Zone.EXILE,
    ))
    out = tokenize_state(state, viewer_id=0)
    types = out["token_type"].tolist()
    assert TOKEN_TYPE_GRAVEYARD_VIEWER in types
    assert TOKEN_TYPE_EXILE_VIEWER in types
    assert TOKEN_TYPE_GRAVEYARD_OPPONENT in types
    assert TOKEN_TYPE_EXILE_OPPONENT in types


def test_cast_spell_token_records_mana_cost_scalar() -> None:
    """CastSpell's source_printing.mana_cost.total / 10 lands in the
    mana_cost_paid scalar slot."""
    from mtg_bot.training.structured_model import SCALAR_FIELD_MANA_COST_PAID
    state = _empty_state()
    printings = get_active_source().get_printings()
    # Pick a non-land card with a known CMC > 0.
    spell_printing = next(
        p for name, p in printings.items()
        if "Land" not in p.card_types and p.mana_cost.total > 0
    )
    spell_card = GameObject(
        id=55, printing=spell_printing, owner_id=0, controller_id=0,
        zone=Zone.HAND,
    )
    state.players[0].hand.append(spell_card)
    ev = ActionEvent(
        action=CastSpell(card_id=55),
        state_snapshot=state, turn=1, step=Step.PRECOMBAT_MAIN,
        actor_player_id=0,
    )
    out = tokenize_state(state, viewer_id=0, recent_actions=[ev])
    action_rows = out["token_type"] == TOKEN_TYPE_ACTION_EVENT
    mana_paid = out["token_scalars"][action_rows, SCALAR_FIELD_MANA_COST_PAID][0]
    assert mana_paid > 0


def test_cast_spell_variants() -> None:
    """Each CastSpell modifier (kicked / warp / impending / free /
    room half) maps to a distinct variant id."""
    from mtg_bot.training.state_tokenizer import (
        VARIANT_CAST_FOR_FREE, VARIANT_IMPENDING, VARIANT_KICKED,
        VARIANT_NORMAL, VARIANT_ROOM_HALF_0, VARIANT_ROOM_HALF_1,
        VARIANT_WARP, _cast_variant,
    )
    assert _cast_variant(CastSpell(card_id=1)) == VARIANT_NORMAL
    assert _cast_variant(CastSpell(card_id=1, kicked=True)) == VARIANT_KICKED
    assert _cast_variant(CastSpell(card_id=1, use_warp=True)) == VARIANT_WARP
    assert _cast_variant(
        CastSpell(card_id=1, use_impending=True),
    ) == VARIANT_IMPENDING
    assert _cast_variant(
        CastSpell(card_id=1, cast_for_free=True),
    ) == VARIANT_CAST_FOR_FREE
    # Room half — output is either half-0 or half-1, deterministic.
    cv = _cast_variant(CastSpell(card_id=1, cast_room_half="X"))
    assert cv in (VARIANT_ROOM_HALF_0, VARIANT_ROOM_HALF_1)


def test_unlock_room_half_records_variant() -> None:
    """UnlockRoomHalf picks a room-half variant id deterministically."""
    from mtg_bot.actions import UnlockRoomHalf as _U
    from mtg_bot.training.state_tokenizer import (
        VARIANT_ROOM_HALF_0, VARIANT_ROOM_HALF_1,
    )
    state = _empty_state()
    ev = ActionEvent(
        action=_U(card_id=10, half_name="South Door"),
        state_snapshot=state, turn=1, step=Step.PRECOMBAT_MAIN,
        actor_player_id=0,
    )
    out = tokenize_state(state, viewer_id=0, recent_actions=[ev])
    rows = out["token_type"] == TOKEN_TYPE_ACTION_EVENT
    v = out["token_emb_ids"][rows, EMB_FIELD_VARIANT][0]
    assert v in (VARIANT_ROOM_HALF_0, VARIANT_ROOM_HALF_1)


def test_activate_ability_non_mana_is_kept() -> None:
    """Non-land sources don't trigger the mana-ability filter."""
    from mtg_bot.actions import ActivateAbility
    state = _empty_state()
    printings = get_active_source().get_printings()
    non_land = next(
        p for name, p in printings.items() if "Land" not in p.card_types
    )
    state.battlefield.append(GameObject(
        id=33, printing=non_land,
        owner_id=0, controller_id=0, zone=Zone.BATTLEFIELD,
    ))
    ev = ActionEvent(
        action=ActivateAbility(source_id=33, ability_index=0),
        state_snapshot=state, turn=1, step=Step.PRECOMBAT_MAIN,
        actor_player_id=0,
    )
    out = tokenize_state(state, viewer_id=0, recent_actions=[ev])
    types = out["token_type"].tolist()
    assert TOKEN_TYPE_ACTION_EVENT in types


def test_activate_station_records_crew_target() -> None:
    """ActivateStation puts the crew creature's printing in the
    target slot."""
    from mtg_bot.actions import ActivateStation
    from mtg_bot.training.state_tokenizer import TARGET_KIND_PERMANENT
    from mtg_bot.training.structured_model import EMB_FIELD_TARGET_KIND
    state = _empty_state()
    printings = get_active_source().get_printings()
    sample = next(iter(printings.values()))
    state.battlefield.append(GameObject(
        id=44, printing=sample, owner_id=0, controller_id=0,
        zone=Zone.BATTLEFIELD,
    ))
    state.battlefield.append(GameObject(
        id=45, printing=sample, owner_id=0, controller_id=0,
        zone=Zone.BATTLEFIELD,
    ))
    ev = ActionEvent(
        action=ActivateStation(spacecraft_id=44, crew_id=45),
        state_snapshot=state, turn=1, step=Step.PRECOMBAT_MAIN,
        actor_player_id=0,
    )
    out = tokenize_state(state, viewer_id=0, recent_actions=[ev])
    rows = out["token_type"] == TOKEN_TYPE_ACTION_EVENT
    assert (
        out["token_emb_ids"][rows, EMB_FIELD_TARGET_KIND][0]
        == TARGET_KIND_PERMANENT
    )


def test_turn_face_up_action() -> None:
    from mtg_bot.actions import TurnFaceUp
    state = _empty_state()
    printings = get_active_source().get_printings()
    sample = next(iter(printings.values()))
    state.battlefield.append(GameObject(
        id=77, printing=sample, owner_id=0, controller_id=0,
        zone=Zone.BATTLEFIELD,
    ))
    ev = ActionEvent(
        action=TurnFaceUp(card_id=77),
        state_snapshot=state, turn=1, step=Step.PRECOMBAT_MAIN,
        actor_player_id=0,
    )
    out = tokenize_state(state, viewer_id=0, recent_actions=[ev])
    rows = out["token_type"] == TOKEN_TYPE_ACTION_EVENT
    kind = out["token_emb_ids"][rows, EMB_FIELD_ACTION_KIND][0]
    assert kind == ACTION_KIND_VOCAB["TurnFaceUp"]


def test_resolution_x_decision_records_x_in_mana_scalar() -> None:
    from mtg_bot.search.resolution_decisions import ResolutionXDecision
    from mtg_bot.training.structured_model import SCALAR_FIELD_MANA_COST_PAID
    state = _empty_state()
    ev = ActionEvent(
        action=ResolutionXDecision(x_value=5),
        state_snapshot=state, turn=1, step=Step.PRECOMBAT_MAIN,
        actor_player_id=0,
    )
    out = tokenize_state(state, viewer_id=0, recent_actions=[ev])
    rows = out["token_type"] == TOKEN_TYPE_ACTION_EVENT
    paid = out["token_scalars"][rows, SCALAR_FIELD_MANA_COST_PAID][0]
    assert paid == 0.5


def test_resolution_discard_finds_card_in_hand() -> None:
    """ResolutionDiscardDecision looks up the discarded card via id
    and records its printing as the target."""
    from mtg_bot.search.resolution_decisions import (
        ResolutionDiscardDecision,
    )
    state = _empty_state()
    printings = get_active_source().get_printings()
    sample = next(iter(printings.values()))
    state.players[0].hand.append(GameObject(
        id=88, printing=sample, owner_id=0, controller_id=0,
        zone=Zone.HAND,
    ))
    ev = ActionEvent(
        action=ResolutionDiscardDecision(card_id=88),
        state_snapshot=state, turn=1, step=Step.PRECOMBAT_MAIN,
        actor_player_id=0,
    )
    out = tokenize_state(state, viewer_id=0, recent_actions=[ev])
    rows = out["token_type"] == TOKEN_TYPE_ACTION_EVENT
    target = out["token_emb_ids"][rows, EMB_FIELD_TARGET_PRINTING][0]
    assert target != PRINTING_NA


def test_resolution_sacrifice_records_target() -> None:
    from mtg_bot.search.resolution_decisions import (
        ResolutionSacrificeDecision,
    )
    state = _empty_state()
    printings = get_active_source().get_printings()
    sample = next(iter(printings.values()))
    state.battlefield.append(GameObject(
        id=300, printing=sample, owner_id=0, controller_id=0,
        zone=Zone.BATTLEFIELD,
    ))
    ev = ActionEvent(
        action=ResolutionSacrificeDecision(object_id=300),
        state_snapshot=state, turn=1, step=Step.PRECOMBAT_MAIN,
        actor_player_id=0,
    )
    out = tokenize_state(state, viewer_id=0, recent_actions=[ev])
    rows = out["token_type"] == TOKEN_TYPE_ACTION_EVENT
    assert out["token_emb_ids"][rows, EMB_FIELD_TARGET_PRINTING][0] != PRINTING_NA


def test_resolution_mode_yes_no_shock_devour_emit_action_tokens() -> None:
    """Mode / YesNo / ShockLife / DevourLands resolutions all emit a
    token with their action_kind. These mostly carry no target
    information; we just exercise the branches."""
    from mtg_bot.search.resolution_decisions import (
        ResolutionDevourLandsDecision, ResolutionModeDecision,
        ResolutionShockLifeDecision, ResolutionYesNoDecision,
    )
    state = _empty_state()
    actions = [
        ResolutionModeDecision(mode_index=0),
        ResolutionYesNoDecision(yes=True),
        ResolutionYesNoDecision(yes=False),
        ResolutionShockLifeDecision(pay=True),
        ResolutionDevourLandsDecision(land_ids=()),
    ]
    events = [
        ActionEvent(action=a, state_snapshot=state, turn=1,
                    step=Step.PRECOMBAT_MAIN, actor_player_id=0)
        for a in actions
    ]
    out = tokenize_state(state, viewer_id=0, recent_actions=events)
    n_action = int((out["token_type"] == TOKEN_TYPE_ACTION_EVENT).sum())
    assert n_action == len(events)


def test_resolution_card_from_opponent_hand_records_target() -> None:
    """Thoughtseize-style pick is public to both seats."""
    from mtg_bot.search.resolution_decisions import (
        ResolutionCardFromOpponentHandDecision,
    )
    state = _empty_state()
    printings = get_active_source().get_printings()
    sample = next(iter(printings.values()))
    state.players[1].hand.append(GameObject(
        id=999, printing=sample, owner_id=1, controller_id=1,
        zone=Zone.HAND,
    ))
    ev = ActionEvent(
        action=ResolutionCardFromOpponentHandDecision(card_id=999),
        state_snapshot=state, turn=1, step=Step.PRECOMBAT_MAIN,
        actor_player_id=0,
    )
    out = tokenize_state(state, viewer_id=0, recent_actions=[ev])
    rows = out["token_type"] == TOKEN_TYPE_ACTION_EVENT
    assert out["token_emb_ids"][rows, EMB_FIELD_TARGET_PRINTING][0] != PRINTING_NA
    # And from the opposite viewer.
    out2 = tokenize_state(state, viewer_id=1, recent_actions=[ev])
    rows2 = out2["token_type"] == TOKEN_TYPE_ACTION_EVENT
    assert out2["token_emb_ids"][rows2, EMB_FIELD_TARGET_PRINTING][0] != PRINTING_NA


def test_stack_with_target_records_target_kind() -> None:
    """Stack item with a target ``(kind, id)`` records the kind."""
    from mtg_bot.training.state_tokenizer import TARGET_KIND_PLAYER
    from mtg_bot.training.structured_model import EMB_FIELD_TARGET_KIND
    state = _empty_state()
    printings = get_active_source().get_printings()
    sample = next(iter(printings.values()))
    spell_obj = GameObject(
        id=99, printing=sample, owner_id=0, controller_id=0,
        zone=Zone.STACK,
    )
    state.stack.append(StackItem(
        source=spell_obj, controller_id=0,
        targets=(("player", 1),),
    ))
    out = tokenize_state(state, viewer_id=0)
    # Stack token is the last one (after global).
    stack_row_idx = out["token_type"].tolist().index(TOKEN_TYPE_STACK_ITEM)
    assert (
        out["token_emb_ids"][stack_row_idx, EMB_FIELD_TARGET_KIND]
        == TARGET_KIND_PLAYER
    )


def test_pass_priority_token_via_make_action_token_is_tolerated() -> None:
    """The action-token builder's defensive PassPriority branch — the
    filter normally strips these, but the builder must not crash if
    called directly with one."""
    from mtg_bot.actions import PassPriority
    from mtg_bot.training.state_tokenizer import _make_action_token
    state = _empty_state()
    tt, emb, sc = _make_action_token(
        action=PassPriority(),
        state_at_action=state,
        action_turn=1, current_turn=1,
        viewer_id=0, actor_player_id=0,
        state_step=Step.PRECOMBAT_MAIN,
        n_printings_cap=320,
    )
    assert tt == TOKEN_TYPE_ACTION_EVENT


def test_step_id_for_none_returns_na() -> None:
    from mtg_bot.training.state_tokenizer import STEP_NA, _step_id
    assert _step_id(None) == STEP_NA


def test_step_id_unknown_step_returns_na() -> None:
    """An object that isn't an engine Step falls into ValueError path
    on STEP_ORDER.index → returns NA."""
    from mtg_bot.training.state_tokenizer import STEP_NA, _step_id
    assert _step_id("nonexistent-step") == STEP_NA


def test_mana_ability_filter_missing_source_keeps_action() -> None:
    """If the ActivateAbility's source_id isn't on the battlefield,
    we can't confirm it's a mana ability — keep the token."""
    from mtg_bot.actions import ActivateAbility
    from mtg_bot.training.state_tokenizer import _is_mana_ability
    state = _empty_state()
    action = ActivateAbility(source_id=9999, ability_index=0)
    assert _is_mana_ability(action, state) is False


def test_printing_id_unknown_name_returns_na() -> None:
    """A printing whose name isn't in the active source returns NA."""
    from mtg_bot.cards.base import ManaCost
    from mtg_bot.cards.base import CardPrinting as CP
    fake = CP(
        name="UNKNOWN-PRINTING-FOR-TEST",
        mana_cost_str="", mana_cost=ManaCost(),
        type_line="", supertypes=(), card_types=(), subtypes=(),
    )
    assert printing_id(fake) == PRINTING_NA


def test_declare_blockers_with_no_assignments_emits_one_token() -> None:
    """DeclareBlockers with no assignments doesn't go through the
    per-blocker expander — it lands as one defensive token."""
    from mtg_bot.actions import DeclareBlockers
    state = _empty_state()
    ev = ActionEvent(
        action=DeclareBlockers(assignments=()),
        state_snapshot=state, turn=1, step=Step.DECLARE_BLOCKERS,
        actor_player_id=0,
    )
    out = tokenize_state(state, viewer_id=0, recent_actions=[ev])
    rows = (out["token_type"] == TOKEN_TYPE_ACTION_EVENT).sum()
    assert rows == 1


def test_declare_attackers_with_no_attackers_emits_one_token() -> None:
    """Same defensive path for empty DeclareAttackers."""
    from mtg_bot.actions import DeclareAttackers
    state = _empty_state()
    ev = ActionEvent(
        action=DeclareAttackers(attacker_ids=frozenset()),
        state_snapshot=state, turn=1, step=Step.DECLARE_ATTACKERS,
        actor_player_id=0,
    )
    out = tokenize_state(state, viewer_id=0, recent_actions=[ev])
    rows = (out["token_type"] == TOKEN_TYPE_ACTION_EVENT).sum()
    assert rows == 1


def test_resolution_discard_finds_card_in_graveyard() -> None:
    """When the discarded card has already been moved to graveyard
    (post-effect snapshot), the fallback lookup still resolves the
    printing."""
    from mtg_bot.search.resolution_decisions import (
        ResolutionDiscardDecision,
    )
    state = _empty_state()
    printings = get_active_source().get_printings()
    sample = next(iter(printings.values()))
    state.players[0].graveyard.append(GameObject(
        id=4242, printing=sample, owner_id=0, controller_id=0,
        zone=Zone.GRAVEYARD,
    ))
    ev = ActionEvent(
        action=ResolutionDiscardDecision(card_id=4242),
        state_snapshot=state, turn=1, step=Step.PRECOMBAT_MAIN,
        actor_player_id=0,
    )
    out = tokenize_state(state, viewer_id=0, recent_actions=[ev])
    rows = out["token_type"] == TOKEN_TYPE_ACTION_EVENT
    assert out["token_emb_ids"][rows, EMB_FIELD_TARGET_PRINTING][0] != PRINTING_NA


def test_cast_spell_from_stack_falls_back_to_stack_lookup() -> None:
    """When the cast spell's id isn't in any hand (already moved to
    stack), the fallback _find_object_printing finds it."""
    state = _empty_state()
    printings = get_active_source().get_printings()
    sample = next(iter(printings.values()))
    spell_obj = GameObject(
        id=1234, printing=sample, owner_id=0, controller_id=0,
        zone=Zone.STACK,
    )
    state.stack.append(
        StackItem(source=spell_obj, controller_id=0, targets=()),
    )
    ev = ActionEvent(
        action=CastSpell(card_id=1234),
        state_snapshot=state, turn=1, step=Step.PRECOMBAT_MAIN,
        actor_player_id=0,
    )
    out = tokenize_state(state, viewer_id=0, recent_actions=[ev])
    rows = out["token_type"] == TOKEN_TYPE_ACTION_EVENT
    assert out["token_emb_ids"][rows, EMB_FIELD_PRINTING][0] != PRINTING_NA


def test_play_land_from_stack_falls_back_to_stack_lookup() -> None:
    state = _empty_state()
    printings = get_active_source().get_printings()
    sample = next(iter(printings.values()))
    land_obj = GameObject(
        id=5555, printing=sample, owner_id=0, controller_id=0,
        zone=Zone.STACK,
    )
    state.stack.append(
        StackItem(source=land_obj, controller_id=0, targets=()),
    )
    ev = ActionEvent(
        action=PlayLand(card_id=5555),
        state_snapshot=state, turn=1, step=Step.PRECOMBAT_MAIN,
        actor_player_id=0,
    )
    out = tokenize_state(state, viewer_id=0, recent_actions=[ev])
    rows = out["token_type"] == TOKEN_TYPE_ACTION_EVENT
    assert out["token_emb_ids"][rows, EMB_FIELD_PRINTING][0] != PRINTING_NA


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


# ---------------------------------------------------------------------
# Scalar schema v2 (board / life state) vs v1 (legacy 3-slot row)
# ---------------------------------------------------------------------


def _creature_printing():
    """Pick a plain creature printing with printed P/T from the active
    source (deterministic: sorted by name)."""
    printings = get_active_source().get_printings()
    for name in sorted(printings):
        pr = printings[name]
        if (
            pr.is_creature
            and pr.power is not None
            and pr.toughness is not None
        ):
            return pr
    raise AssertionError("no creature printing in the active source")


def _board_state() -> tuple[GameState, "object"]:
    """A hand-built two-player state with: viewer at 14 life / 2
    poison, opp at 20 life; viewer controls a tapped, damaged creature
    with one +1/+1 counter that is not summoning sick, plus one
    untapped and one tapped Forest; opp controls one untapped Forest;
    viewer has 3 cards in hand + 30 in library, opp 5 in hand + 25 in
    library; one spell on the stack; turn 7, viewer active + priority.
    """
    from mtg_bot.training.structured_model import (
        SCALAR_FIELD_PUBLIC_MASK as _PM,  # noqa: F401 (readability)
    )
    printings = get_active_source().get_printings()
    forest = printings["Forest"]
    creature = _creature_printing()

    def _cards(base_id, printing, owner, n, zone):
        return [
            GameObject(
                id=base_id + i, printing=printing, owner_id=owner,
                controller_id=owner, zone=zone,
            )
            for i in range(n)
        ]

    p0 = Player(
        id=0, life=14, poison_counters=2,
        hand=_cards(10_000, forest, 0, 3, Zone.HAND),
        library=_cards(11_000, forest, 0, 30, Zone.LIBRARY),
    )
    p1 = Player(
        id=1, life=20,
        hand=_cards(20_000, forest, 1, 5, Zone.HAND),
        library=_cards(21_000, forest, 1, 25, Zone.LIBRARY),
    )
    crit = GameObject(
        id=1, printing=creature, owner_id=0, controller_id=0,
        zone=Zone.BATTLEFIELD, tapped=True, damage=2,
        summoning_sick=False, plus_one_counters=1,
    )
    land_untapped = GameObject(
        id=2, printing=forest, owner_id=0, controller_id=0,
        zone=Zone.BATTLEFIELD, tapped=False,
    )
    land_tapped = GameObject(
        id=3, printing=forest, owner_id=0, controller_id=0,
        zone=Zone.BATTLEFIELD, tapped=True,
    )
    opp_land = GameObject(
        id=4, printing=forest, owner_id=1, controller_id=1,
        zone=Zone.BATTLEFIELD, tapped=False,
    )
    spell_obj = GameObject(
        id=99, printing=creature, owner_id=1, controller_id=1,
        zone=Zone.STACK,
    )
    state = GameState(
        players=[p0, p1],
        battlefield=[crit, land_untapped, land_tapped, opp_land],
        stack=[StackItem(source=spell_obj, controller_id=1, targets=())],
        active_player_idx=0,
        priority_player_idx=0,
        turn_number=7,
        step=Step.PRECOMBAT_MAIN,
    )
    return state, creature


def test_v2_width_matches_constant_and_v1_width_is_three() -> None:
    state, _ = _board_state()
    out2 = tokenize_state(state, viewer_id=0, scalar_schema_version=2)
    out1 = tokenize_state(state, viewer_id=0, scalar_schema_version=1)
    assert out2["token_scalars"].shape[1] == N_SCALAR_FIELDS_V2
    assert out1["token_scalars"].shape[1] == N_SCALAR_FIELDS == 3
    # Same token sequence either way; only the scalar width differs.
    assert (out1["token_type"] == out2["token_type"]).all()
    assert (out1["token_emb_ids"] == out2["token_emb_ids"]).all()


def test_v1_row_is_exactly_the_v2_prefix() -> None:
    """The v1 slots keep their indices and values under v2, so the
    schema-1 output is the schema-2 output's first three columns."""
    state, _ = _board_state()
    out2 = tokenize_state(state, viewer_id=0, scalar_schema_version=2)
    out1 = tokenize_state(state, viewer_id=0, scalar_schema_version=1)
    np.testing.assert_array_equal(
        out1["token_scalars"], out2["token_scalars"][:, :N_SCALAR_FIELDS],
    )


def test_v1_output_is_bit_identical_to_pre_schema_tokenizer() -> None:
    """Pin the exact schema-1 rows for a hand-built state. These are
    the values the pre-schema tokenizer emitted: global token
    ``[0, 0, 1]``, every permanent ``[0, 0, 1]``, viewer hand
    ``[0, 0, 1]``, opp hand ``[0, 0, 0]``, stack item
    ``[0, cost/10, 1]``."""
    state, creature = _board_state()
    out = tokenize_state(state, viewer_id=0, scalar_schema_version=1)
    sc = out["token_scalars"]
    tt = out["token_type"]
    # Global + 4 permanents + 3 viewer hand + 5 opp hand + 1 stack.
    assert sc.shape == (14, 3)
    assert sc[0].tolist() == [0.0, 0.0, 1.0]
    for i in range(1, 5):
        assert tt[i] in (TOKEN_TYPE_PERMANENT_VIEWER, TOKEN_TYPE_PERMANENT_OPPONENT)
        assert sc[i].tolist() == [0.0, 0.0, 1.0]
    for i in range(5, 8):
        assert tt[i] == TOKEN_TYPE_HAND_VIEWER
        assert sc[i].tolist() == [0.0, 0.0, 1.0]
    for i in range(8, 13):
        assert tt[i] == TOKEN_TYPE_HAND_OPPONENT
        assert sc[i].tolist() == [0.0, 0.0, 0.0]
    assert tt[13] == TOKEN_TYPE_STACK_ITEM
    assert sc[13, 0] == 0.0
    assert sc[13, 1] == np.float32(creature.mana_cost.total / 10.0)
    assert sc[13, 2] == 1.0


def test_v2_permanent_slots_reflect_board_state() -> None:
    from mtg_bot.game import effective_power, effective_toughness
    from mtg_bot.training.structured_model import (
        SCALAR_FIELD_ATTACKING,
        SCALAR_FIELD_BLOCKING,
        SCALAR_FIELD_DAMAGE,
        SCALAR_FIELD_IS_CREATURE,
        SCALAR_FIELD_OTHER_COUNTERS,
        SCALAR_FIELD_POWER,
        SCALAR_FIELD_PT_COUNTERS,
        SCALAR_FIELD_SUMMONING_SICK,
        SCALAR_FIELD_TAPPED,
        SCALAR_FIELD_TOUGHNESS,
    )
    state, creature = _board_state()
    out = tokenize_state(state, viewer_id=0, scalar_schema_version=2)
    sc = out["token_scalars"]
    # Permanents are emitted sorted by id: creature(1), untapped
    # Forest(2), tapped Forest(3), opp Forest(4) at rows 1..4.
    crit = sc[1]
    obj = state.battlefield[0]
    assert crit[SCALAR_FIELD_TAPPED] == 1.0
    assert crit[SCALAR_FIELD_IS_CREATURE] == 1.0
    # P/T go through the engine's layer-7 helpers (the +1/+1 counter
    # is included), scaled by /8.
    assert crit[SCALAR_FIELD_POWER] == np.float32(
        effective_power(state, obj) / 8.0
    )
    assert crit[SCALAR_FIELD_TOUGHNESS] == np.float32(
        effective_toughness(state, obj) / 8.0
    )
    assert effective_power(state, obj) == creature.power + 1
    assert crit[SCALAR_FIELD_DAMAGE] == np.float32(2 / 8.0)
    assert crit[SCALAR_FIELD_PT_COUNTERS] == np.float32(1 / 4.0)
    assert crit[SCALAR_FIELD_OTHER_COUNTERS] == 0.0
    assert crit[SCALAR_FIELD_SUMMONING_SICK] == 0.0
    assert crit[SCALAR_FIELD_ATTACKING] == 0.0
    assert crit[SCALAR_FIELD_BLOCKING] == 0.0
    assert crit[SCALAR_FIELD_PUBLIC_MASK] == 1.0
    # Lands: not creatures, no P/T, tapped flag only.
    untapped_land, tapped_land = sc[2], sc[3]
    assert untapped_land[SCALAR_FIELD_TAPPED] == 0.0
    assert tapped_land[SCALAR_FIELD_TAPPED] == 1.0
    for row in (untapped_land, tapped_land):
        assert row[SCALAR_FIELD_IS_CREATURE] == 0.0
        assert row[SCALAR_FIELD_POWER] == 0.0
        assert row[SCALAR_FIELD_TOUGHNESS] == 0.0
        assert row[SCALAR_FIELD_SUMMONING_SICK] == 0.0


def test_v2_permanent_combat_and_summoning_sick_flags() -> None:
    from mtg_bot.training.structured_model import (
        SCALAR_FIELD_ATTACKING,
        SCALAR_FIELD_BLOCKING,
        SCALAR_FIELD_OTHER_COUNTERS,
        SCALAR_FIELD_SUMMONING_SICK,
    )
    state, _ = _board_state()
    obj = state.battlefield[0]
    obj.summoning_sick = True
    obj.attacking = True
    obj.blocking = 4
    obj.charge_counters = 2
    out = tokenize_state(state, viewer_id=0, scalar_schema_version=2)
    crit = out["token_scalars"][1]
    assert crit[SCALAR_FIELD_SUMMONING_SICK] == 1.0
    assert crit[SCALAR_FIELD_ATTACKING] == 1.0
    assert crit[SCALAR_FIELD_BLOCKING] == 1.0
    assert crit[SCALAR_FIELD_OTHER_COUNTERS] == np.float32(2 / 4.0)


def test_v2_global_slots_reflect_life_and_zone_state() -> None:
    from mtg_bot.training.structured_model import (
        SCALAR_FIELD_IS_VIEWER_TURN,
        SCALAR_FIELD_OPP_HAND,
        SCALAR_FIELD_OPP_LANDS,
        SCALAR_FIELD_OPP_LIBRARY,
        SCALAR_FIELD_OPP_LIFE,
        SCALAR_FIELD_OPP_POISON,
        SCALAR_FIELD_OPP_UNTAPPED_LANDS,
        SCALAR_FIELD_STACK_SIZE,
        SCALAR_FIELD_TURN_NUMBER,
        SCALAR_FIELD_VIEWER_HAND,
        SCALAR_FIELD_VIEWER_HAS_PRIORITY,
        SCALAR_FIELD_VIEWER_LANDS,
        SCALAR_FIELD_VIEWER_LIBRARY,
        SCALAR_FIELD_VIEWER_LIFE,
        SCALAR_FIELD_VIEWER_POISON,
        SCALAR_FIELD_VIEWER_UNTAPPED_LANDS,
    )
    state, _ = _board_state()
    out = tokenize_state(state, viewer_id=0, scalar_schema_version=2)
    g = out["token_scalars"][0]
    assert out["token_type"][0] == TOKEN_TYPE_GLOBAL
    f32 = np.float32
    assert g[SCALAR_FIELD_VIEWER_LIFE] == f32(14 / 20.0)
    assert g[SCALAR_FIELD_OPP_LIFE] == f32(20 / 20.0)
    assert g[SCALAR_FIELD_VIEWER_POISON] == f32(2 / 10.0)
    assert g[SCALAR_FIELD_OPP_POISON] == 0.0
    assert g[SCALAR_FIELD_VIEWER_LIBRARY] == f32(30 / 40.0)
    assert g[SCALAR_FIELD_OPP_LIBRARY] == f32(25 / 40.0)
    assert g[SCALAR_FIELD_VIEWER_HAND] == f32(3 / 7.0)
    assert g[SCALAR_FIELD_OPP_HAND] == f32(5 / 7.0)
    assert g[SCALAR_FIELD_TURN_NUMBER] == f32(7 / 20.0)
    assert g[SCALAR_FIELD_VIEWER_UNTAPPED_LANDS] == f32(1 / 8.0)
    assert g[SCALAR_FIELD_VIEWER_LANDS] == f32(2 / 8.0)
    assert g[SCALAR_FIELD_OPP_UNTAPPED_LANDS] == f32(1 / 8.0)
    assert g[SCALAR_FIELD_OPP_LANDS] == f32(1 / 8.0)
    assert g[SCALAR_FIELD_STACK_SIZE] == f32(1 / 4.0)
    assert g[SCALAR_FIELD_IS_VIEWER_TURN] == 1.0
    assert g[SCALAR_FIELD_VIEWER_HAS_PRIORITY] == 1.0
    assert g[SCALAR_FIELD_PUBLIC_MASK] == 1.0
    # Flip the viewer: the sides swap and the turn / priority flags
    # drop to 0.
    out1 = tokenize_state(state, viewer_id=1, scalar_schema_version=2)
    g1 = out1["token_scalars"][0]
    assert g1[SCALAR_FIELD_VIEWER_LIFE] == f32(20 / 20.0)
    assert g1[SCALAR_FIELD_OPP_LIFE] == f32(14 / 20.0)
    assert g1[SCALAR_FIELD_OPP_POISON] == f32(2 / 10.0)
    assert g1[SCALAR_FIELD_VIEWER_LANDS] == f32(1 / 8.0)
    assert g1[SCALAR_FIELD_OPP_LANDS] == f32(2 / 8.0)
    assert g1[SCALAR_FIELD_IS_VIEWER_TURN] == 0.0
    assert g1[SCALAR_FIELD_VIEWER_HAS_PRIORITY] == 0.0


def test_v2_global_slots_are_clamped() -> None:
    from mtg_bot.training.structured_model import (
        SCALAR_FIELD_TURN_NUMBER,
        SCALAR_FIELD_VIEWER_LIFE,
        SCALAR_FIELD_VIEWER_POISON,
    )
    state, _ = _board_state()
    state.players[0].life = 200
    state.players[0].poison_counters = 15
    state.turn_number = 99
    g = tokenize_state(state, viewer_id=0, scalar_schema_version=2)[
        "token_scalars"
    ][0]
    assert g[SCALAR_FIELD_VIEWER_LIFE] == 3.0
    assert g[SCALAR_FIELD_VIEWER_POISON] == 1.0
    assert g[SCALAR_FIELD_TURN_NUMBER] == 1.0


def test_v2_non_permanent_tokens_have_zero_board_slots() -> None:
    """Hand / graveyard / exile / stack / action tokens keep their v1
    scalars and every appended v2 slot stays zero."""
    state, _ = _board_state()
    ev = _land_action_event(state, turn=7)
    out = tokenize_state(
        state, viewer_id=0, recent_actions=[ev], scalar_schema_version=2,
    )
    sc = out["token_scalars"]
    tt = out["token_type"]
    non_board = [
        i for i, t in enumerate(tt.tolist())
        if t not in (
            TOKEN_TYPE_GLOBAL, TOKEN_TYPE_PERMANENT_VIEWER,
            TOKEN_TYPE_PERMANENT_OPPONENT,
        )
    ]
    assert non_board  # hand / opp-hand / stack / action rows exist
    assert TOKEN_TYPE_ACTION_EVENT in tt.tolist()
    assert (sc[non_board, N_SCALAR_FIELDS:] == 0.0).all()


def test_default_schema_is_v2() -> None:
    state, _ = _board_state()
    out = tokenize_state(state, viewer_id=0)
    assert out["token_scalars"].shape[1] == N_SCALAR_FIELDS_V2


def test_unknown_scalar_schema_version_raises() -> None:
    import pytest
    state, _ = _board_state()
    with pytest.raises(ValueError, match="scalar_schema_version"):
        tokenize_state(state, viewer_id=0, scalar_schema_version=99)


def test_empty_state_v2_width_and_global_only() -> None:
    state = _empty_state()
    out = tokenize_state(state, viewer_id=0, scalar_schema_version=2)
    assert out["token_scalars"].shape == (1, N_SCALAR_FIELDS_V2)
