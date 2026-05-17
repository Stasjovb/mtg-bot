"""Error / overflow / edge-path tests for ``mtg_bot.training.action_encoding``.

The existing ``test_action_encoding`` / ``test_action_encoding_canonical``
suites drive real games and assert round-trip fidelity on the *common*
paths. Random self-play almost never produces the cap-overflow and
"referenced object not present" branches, so the encoder/decoder error
paths (``EncodingOverflowError`` / ``IllegalSlotError`` raises and the
v2 zone-sort branches for graveyard/exile) were uncovered.

These tests build a real engine state from ``setup_game`` and then
deterministically place cards into the zones / construct decisions that
exercise each error branch, asserting the *specific* exception and that
its message names the offending cap or field. That's a behavioral
contract — callers (``legal_action_mask``, the NN policy head) rely on
overflow being a distinct, swallow-able exception type vs.
``IllegalSlotError`` being raised by ``decode`` on an unfilled slot.
"""

from __future__ import annotations

import dataclasses
import random

import pytest

from mtg_bot.actions import (
    ActivateAbility,
    ActivateStation,
    CastSpell,
    PassPriority,
    PlayLand,
    TurnFaceUp,
    UnlockRoomHalf,
)
from mtg_bot.agents import RandomAgent
from mtg_bot.search.combat_decisions import BlockerDecision
from mtg_bot.simulate import setup_game
from mtg_bot.training import action_encoding as ae
from mtg_bot.training.action_encoding import (
    ACTION_VOCAB_SIZE,
    EXILE_CAP,
    GRAVEYARD_CAP,
    HAND_SIZE_CAP,
    SLOT_CAST_FROM_EXILE_BASE,
    SLOT_CAST_FROM_GY_BASE,
    SLOT_CAST_FROM_LIBRARY_TOP,
    SLOT_LAND_FROM_EXILE_BASE,
    SLOT_LAND_FROM_GY_BASE,
    EncodingOverflowError,
    IllegalSlotError,
    decode,
    encode,
)
from tests._test_decks import simple_test_decklists


def _engine(seed: int = 0):
    """A real engine state (not the adapter) — enough for the
    priority-window encode/decode paths under test here."""
    return setup_game(
        [RandomAgent(rng=random.Random(seed + 1)),
         RandomAgent(rng=random.Random(seed + 2))],
        decks=simple_test_decklists(), seed=seed,
    )


def _clone(card, new_id: int):
    """A real ``GameObject`` cloned from an existing in-state card with
    a fresh id — avoids hand-constructing the dataclass (which would
    have to track every required field)."""
    return dataclasses.replace(card, id=new_id)


# ---------------------------------------------------------------------
# _find_card_zone: card not in any viewer zone -> EncodingOverflowError
# ---------------------------------------------------------------------


def test_playland_unknown_card_raises_overflow() -> None:
    s = _engine()
    p0 = s.players[0].id
    with pytest.raises(EncodingOverflowError, match="not found in viewer"):
        encode(PlayLand(card_id=999999), s, p0)


def test_castspell_unknown_card_raises_overflow() -> None:
    s = _engine()
    p0 = s.players[0].id
    with pytest.raises(EncodingOverflowError, match="not found in viewer"):
        encode(CastSpell(card_id=999999), s, p0)


# ---------------------------------------------------------------------
# PlayLand / CastSpell from graveyard & exile (positional families) +
# their cap-overflow branches. Real self-play rarely casts from gy/exile.
# ---------------------------------------------------------------------


def test_playland_from_graveyard_and_exile_positions() -> None:
    s = _engine()
    p = s.players[0]
    # Move a couple of hand cards into gy and exile.
    gy_card = p.hand.pop()
    ex_card = p.hand.pop()
    p.graveyard.append(gy_card)
    p.exile.append(ex_card)

    gy_slot = encode(PlayLand(card_id=gy_card.id), s, p.id)
    assert gy_slot == SLOT_LAND_FROM_GY_BASE + 0
    assert decode(gy_slot, s, p.id) == PlayLand(card_id=gy_card.id)

    ex_slot = encode(PlayLand(card_id=ex_card.id), s, p.id)
    assert ex_slot == SLOT_LAND_FROM_EXILE_BASE + 0
    assert decode(ex_slot, s, p.id) == PlayLand(card_id=ex_card.id)


def test_playland_graveyard_overflow_raises() -> None:
    s = _engine()
    p = s.players[0]
    p.graveyard.clear()
    # Fill graveyard past the cap; the (cap)-th card overflows.
    base = p.hand[0]
    for i in range(GRAVEYARD_CAP + 1):
        p.graveyard.append(_clone(base, 10_000 + i))
    overflow_card = p.graveyard[GRAVEYARD_CAP]
    with pytest.raises(EncodingOverflowError, match="GRAVEYARD_CAP"):
        encode(PlayLand(card_id=overflow_card.id), s, p.id)


def test_castspell_exile_overflow_raises() -> None:
    s = _engine()
    p = s.players[0]
    p.exile.clear()
    base = p.hand[0]
    for i in range(EXILE_CAP + 1):
        p.exile.append(_clone(base, 20_000 + i))
    overflow_card = p.exile[EXILE_CAP]
    with pytest.raises(EncodingOverflowError, match="EXILE_CAP"):
        encode(CastSpell(card_id=overflow_card.id), s, p.id)


def test_castspell_hand_overflow_raises() -> None:
    s = _engine()
    p = s.players[0]
    base = s.players[1].hand[0]
    p.hand.clear()
    for i in range(HAND_SIZE_CAP + 1):
        p.hand.append(_clone(base, 30_000 + i))
    overflow_card = p.hand[HAND_SIZE_CAP]
    with pytest.raises(EncodingOverflowError, match="HAND_SIZE_CAP"):
        encode(CastSpell(card_id=overflow_card.id), s, p.id)


def test_castspell_from_graveyard_free_and_warp_variants() -> None:
    """Cast-from-graveyard has a 2-variant axis: free (Weftwalking)
    vs. the normal path which means warp-cast (Timeline Culler).
    Decode must round-trip both."""
    s = _engine()
    p = s.players[0]
    gy_card = p.hand.pop()
    p.graveyard.append(gy_card)

    free_slot = encode(
        CastSpell(card_id=gy_card.id, cast_for_free=True), s, p.id,
    )
    assert decode(free_slot, s, p.id) == CastSpell(
        card_id=gy_card.id, cast_for_free=True,
    )

    normal_slot = encode(CastSpell(card_id=gy_card.id), s, p.id)
    # Decode of the normal gy variant rebuilds it as a warp cast.
    decoded = decode(normal_slot, s, p.id)
    assert decoded == CastSpell(card_id=gy_card.id, use_warp=True)


def test_castspell_from_exile_free_variant_round_trips() -> None:
    s = _engine()
    p = s.players[0]
    ex_card = p.hand.pop()
    p.exile.append(ex_card)
    free_slot = encode(
        CastSpell(card_id=ex_card.id, cast_for_free=True), s, p.id,
    )
    assert decode(free_slot, s, p.id) == CastSpell(
        card_id=ex_card.id, cast_for_free=True,
    )


def test_castspell_from_library_top_round_trips() -> None:
    s = _engine()
    p = s.players[0]
    top = p.library[0]
    slot = encode(CastSpell(card_id=top.id), s, p.id)
    assert slot == SLOT_CAST_FROM_LIBRARY_TOP
    assert decode(slot, s, p.id) == CastSpell(card_id=top.id)


# ---------------------------------------------------------------------
# Battlefield-sourced decisions whose source id is absent.
# ---------------------------------------------------------------------


def test_unlock_room_source_not_on_battlefield_raises() -> None:
    s = _engine()
    p0 = s.players[0].id
    with pytest.raises(EncodingOverflowError, match="not in"):
        encode(UnlockRoomHalf(card_id=424242, half_name="X"), s, p0)


def test_activate_ability_source_not_on_battlefield_raises() -> None:
    s = _engine()
    p0 = s.players[0].id
    with pytest.raises(EncodingOverflowError, match="not in"):
        encode(ActivateAbility(source_id=424242, ability_index=0), s, p0)


def test_activate_station_spacecraft_not_present_raises() -> None:
    s = _engine()
    p0 = s.players[0].id
    with pytest.raises(EncodingOverflowError, match="not in"):
        encode(
            ActivateStation(spacecraft_id=424242, crew_id=1), s, p0,
        )


def test_turn_face_up_source_not_on_battlefield_raises() -> None:
    s = _engine()
    p0 = s.players[0].id
    with pytest.raises(EncodingOverflowError, match="not in"):
        encode(TurnFaceUp(card_id=424242), s, p0)


def test_activate_ability_index_overflow_raises() -> None:
    """Move a real card onto the battlefield and ask for an
    ability index past ``ABILITY_INDEX_CAP``."""
    s = _engine()
    p = s.players[0]
    perm = p.hand.pop()
    perm.controller_id = p.id
    s.battlefield.append(perm)
    with pytest.raises(EncodingOverflowError, match="ABILITY_INDEX_CAP"):
        encode(
            ActivateAbility(
                source_id=perm.id, ability_index=ae.ABILITY_INDEX_CAP,
            ),
            s, p.id,
        )


def test_unknown_decision_type_raises_overflow() -> None:
    s = _engine()
    p0 = s.players[0].id

    class WeirdDecision:
        pass

    with pytest.raises(EncodingOverflowError, match="don't know how to encode"):
        encode(WeirdDecision(), s, p0)


# ---------------------------------------------------------------------
# BlockerDecision encode: attacker id not in attacking creatures.
# ---------------------------------------------------------------------


def test_blocker_decision_attacker_not_attacking_raises() -> None:
    s = _engine()
    p0 = s.players[0].id
    with pytest.raises(EncodingOverflowError, match="not in attacking"):
        encode(BlockerDecision(blocker_id=1, attacker_id=999999), s, p0)


# ---------------------------------------------------------------------
# decode(): out-of-range slot + unfilled-position IllegalSlotError paths
# ---------------------------------------------------------------------


def test_decode_negative_slot_raises_illegal() -> None:
    s = _engine()
    p0 = s.players[0].id
    with pytest.raises(IllegalSlotError, match="not in"):
        decode(-1, s, p0)


def test_decode_too_large_slot_raises_illegal() -> None:
    s = _engine()
    p0 = s.players[0].id
    with pytest.raises(IllegalSlotError, match="not in"):
        decode(ACTION_VOCAB_SIZE, s, p0)


def test_decode_land_from_empty_graveyard_raises_illegal() -> None:
    s = _engine()
    p = s.players[0]
    p.graveyard.clear()
    with pytest.raises(IllegalSlotError, match="gy has 0"):
        decode(SLOT_LAND_FROM_GY_BASE, s, p.id)


def test_decode_land_from_empty_exile_raises_illegal() -> None:
    s = _engine()
    p = s.players[0]
    p.exile.clear()
    with pytest.raises(IllegalSlotError, match="exile has 0"):
        decode(SLOT_LAND_FROM_EXILE_BASE, s, p.id)


def test_decode_cast_from_empty_graveyard_raises_illegal() -> None:
    s = _engine()
    p = s.players[0]
    p.graveyard.clear()
    with pytest.raises(IllegalSlotError, match="gy has 0"):
        decode(SLOT_CAST_FROM_GY_BASE, s, p.id)


def test_decode_cast_from_empty_exile_raises_illegal() -> None:
    s = _engine()
    p = s.players[0]
    p.exile.clear()
    with pytest.raises(IllegalSlotError, match="exile has 0"):
        decode(SLOT_CAST_FROM_EXILE_BASE, s, p.id)


def test_decode_cast_from_library_top_empty_raises_illegal() -> None:
    s = _engine()
    p = s.players[0]
    p.library.clear()
    with pytest.raises(IllegalSlotError, match="library is empty"):
        decode(SLOT_CAST_FROM_LIBRARY_TOP, s, p.id)


def test_decode_cast_from_graveyard_warp_variant_round_trips() -> None:
    """The normal (non-free) gy decode variant builds a warp cast;
    exercise the explicit decode branch with a populated graveyard."""
    s = _engine()
    p = s.players[0]
    p.graveyard.clear()
    card = p.hand.pop()
    p.graveyard.append(card)
    # Normal variant = offset 0 (cast_for_free=False).
    decoded = decode(SLOT_CAST_FROM_GY_BASE, s, p.id)
    assert decoded == CastSpell(card_id=card.id, use_warp=True)


# ---------------------------------------------------------------------
# v2 (canonical) zone-sort branches for graveyard and exile.
# Real self-play rarely casts from gy/exile, so the v2 sort lines in
# _graveyard / _exile were uncovered.
# ---------------------------------------------------------------------


def test_v2_graveyard_sorted_by_canonical_key() -> None:
    """Under v2 the graveyard slot position comes from a
    canonical-sorted view, not raw engine order. Two graveyards that
    differ only by card.id permutation must map a given printing to
    the same slot."""
    s = _engine()
    p = s.players[0]
    p.graveyard.clear()
    src_a = p.hand[0]
    src_b = s.players[1].hand[0]
    pr_a = src_a.printing
    pr_b = src_b.printing
    assert pr_a.name != pr_b.name
    # Insert in non-sorted engine order: B (high id) then A (low id).
    card_b = _clone(src_b, 900)
    card_a = _clone(src_a, 100)
    p.graveyard.extend([card_b, card_a])

    name_first, name_second = sorted([pr_a.name, pr_b.name])
    first_card = card_a if pr_a.name == name_first else card_b

    slot_v2 = encode(PlayLand(card_id=first_card.id), s, p.id,
                      version=ae.ACTION_ENCODING_VERSION_V2)
    # v2 places the canonically-first printing at position 0.
    assert slot_v2 == SLOT_LAND_FROM_GY_BASE + 0
    assert decode(slot_v2, s, p.id,
                  version=ae.ACTION_ENCODING_VERSION_V2) == PlayLand(
        card_id=first_card.id,
    )


def test_v2_exile_sorted_by_canonical_key() -> None:
    s = _engine()
    p = s.players[0]
    p.exile.clear()
    src_a = p.hand[0]
    src_b = s.players[1].hand[0]
    pr_a = src_a.printing
    pr_b = src_b.printing
    card_b = _clone(src_b, 901)
    card_a = _clone(src_a, 101)
    p.exile.extend([card_b, card_a])

    name_first = sorted([pr_a.name, pr_b.name])[0]
    first_card = card_a if pr_a.name == name_first else card_b

    slot_v2 = encode(CastSpell(card_id=first_card.id), s, p.id,
                      version=ae.ACTION_ENCODING_VERSION_V2)
    assert slot_v2 == SLOT_CAST_FROM_EXILE_BASE + 0
    assert decode(slot_v2, s, p.id,
                  version=ae.ACTION_ENCODING_VERSION_V2) == CastSpell(
        card_id=first_card.id,
    )


def test_pass_priority_round_trips_on_engine_state() -> None:
    """Sanity anchor: the simplest path still works with a raw engine
    state (no adapter) input."""
    s = _engine()
    p0 = s.players[0].id
    assert decode(encode(PassPriority(), s, p0), s, p0) == PassPriority()
