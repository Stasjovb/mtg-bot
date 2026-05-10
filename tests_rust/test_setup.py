"""``make_state`` — Rust GameState construction from a caller-supplied
registry + per-player zone contents.

Round-23 phase-2 slice. ``make_state`` is the parity-unlocking
primitive: the parity smoke harness can build matching Python AND
Rust ``GameState``s from the same deck list, then diff their
``fingerprint()`` digests.

The function takes a populated ``Registry`` handle and per-player
printing-id lists for the library + (optional) hand. Caller's order
is preserved exactly (no shuffle, no mulligan). All other zones
(battlefield, graveyard, exile, stack) start empty. Life=20,
turn_number=1, active_player=0, phase=0 (PHASE_UNTAP).
"""

from __future__ import annotations

import pytest


ZONE_HAND = 0
ZONE_LIBRARY = 1


# --- helpers ---------------------------------------------------------


def _forest():
    return {
        "name": "Forest",
        "card_types": ["Land"],
        "mana_cost": {},
        "effects": [],
        "mana_produced": ["G"],
    }


def _bears():
    return {
        "name": "Grizzly Bears",
        "card_types": ["Creature"],
        "mana_cost": {"G": 1, "generic": 1},
        "effects": [],
        "power": 2,
        "toughness": 2,
    }


def _two_card_registry(engine):
    """Fresh Registry with Forest (id=0) and Grizzly Bears (id=1)."""
    reg = engine.Registry()
    fid = reg.register_printing(_forest())
    bid = reg.register_printing(_bears())
    assert fid == 0 and bid == 1
    return reg


# --- 1. basic build --------------------------------------------------


def test_make_state_basic_returns_correct_zone_sizes(engine):
    reg = _two_card_registry(engine)
    state = engine.make_state(reg, [0, 0, 1], [1])
    # p0 library has 3, p1 library has 1; hands are empty.
    assert state.library_sizes == [3, 1]
    assert state.hand_sizes == [0, 0]


def test_make_state_basic_preserves_caller_order(engine):
    """Caller-provided printing-id order survives end-to-end."""
    reg = _two_card_registry(engine)
    # Forest, Forest, Bears for p0; Bears for p1.
    state = engine.make_state(reg, [0, 0, 1], [1])
    lib_p0 = state.library_snapshot(0)
    assert [d["printing_id"] for d in lib_p0] == [0, 0, 1]
    assert [d["printing_name"] for d in lib_p0] == [
        "Forest",
        "Forest",
        "Grizzly Bears",
    ]


# --- 2. hand specification ------------------------------------------


def test_make_state_with_hand_populates_hand_zone(engine):
    reg = _two_card_registry(engine)
    state = engine.make_state(
        reg, [0, 1], [1, 0], p0_hand_printing_ids=[0]
    )
    # p0: 2 in library, 1 in hand. p1: 2 in library, 0 in hand.
    assert state.library_sizes == [2, 2]
    assert state.hand_sizes == [1, 0]
    hand_p0 = state.hand_snapshot(0)
    assert len(hand_p0) == 1
    assert hand_p0[0]["printing_name"] == "Forest"
    assert hand_p0[0]["zone"] == ZONE_HAND


def test_make_state_both_hands_populated(engine):
    reg = _two_card_registry(engine)
    state = engine.make_state(
        reg,
        [0, 0],
        [1, 1],
        p0_hand_printing_ids=[1],
        p1_hand_printing_ids=[0, 0],
    )
    assert state.hand_sizes == [1, 2]
    assert state.library_sizes == [2, 2]


# --- 3. out-of-range printing_id raises -----------------------------


def test_make_state_library_out_of_range_raises(engine):
    reg = _two_card_registry(engine)  # len == 2
    with pytest.raises(ValueError, match="printing_id 5 not in registry"):
        engine.make_state(reg, [0, 5], [1])


def test_make_state_hand_out_of_range_raises(engine):
    reg = _two_card_registry(engine)
    with pytest.raises(ValueError, match="printing_id 99 not in registry"):
        engine.make_state(reg, [0], [1], p0_hand_printing_ids=[99])


def test_make_state_p1_library_out_of_range_raises(engine):
    reg = _two_card_registry(engine)
    with pytest.raises(ValueError, match="printing_id 2 not in registry"):
        engine.make_state(reg, [0], [2])


# --- 4. fresh ids non-collision -------------------------------------


def test_make_state_object_ids_unique_across_players(engine):
    reg = _two_card_registry(engine)
    state = engine.make_state(
        reg,
        [0, 0, 1],
        [1, 0],
        p0_hand_printing_ids=[0],
        p1_hand_printing_ids=[1, 1],
    )
    ids = []
    for player_id in (0, 1):
        ids.extend(d["id"] for d in state.library_snapshot(player_id))
        ids.extend(d["id"] for d in state.hand_snapshot(player_id))
    assert len(ids) == len(set(ids)), f"duplicate ids: {ids}"
    # Sequential from 0.
    assert sorted(ids) == list(range(len(ids)))


def test_make_state_id_allocation_order(engine):
    """p0 library, p0 hand, p1 library, p1 hand — in that order."""
    reg = _two_card_registry(engine)
    state = engine.make_state(
        reg,
        [0, 0],  # p0 library: ids 0, 1
        [1, 1],  # p1 library: starts after p0 hand
        p0_hand_printing_ids=[1],  # p0 hand: id 2
        p1_hand_printing_ids=[0],  # p1 hand: starts after p1 library
    )
    assert [d["id"] for d in state.library_snapshot(0)] == [0, 1]
    assert [d["id"] for d in state.hand_snapshot(0)] == [2]
    assert [d["id"] for d in state.library_snapshot(1)] == [3, 4]
    assert [d["id"] for d in state.hand_snapshot(1)] == [5]


# --- 5. per-object state is zeroed ----------------------------------


def test_make_state_per_object_state_zeroed(engine):
    reg = _two_card_registry(engine)
    state = engine.make_state(reg, [0, 1], [1, 0], p0_hand_printing_ids=[0])
    for player_id in (0, 1):
        for d in state.library_snapshot(player_id):
            assert d["tapped"] is False
            assert d["summoning_sick"] is False
            assert d["damage"] == 0
            assert d["counters"] == 0
        for d in state.hand_snapshot(player_id):
            assert d["tapped"] is False
            assert d["summoning_sick"] is False
            assert d["damage"] == 0
            assert d["counters"] == 0


def test_make_state_controller_matches_player(engine):
    reg = _two_card_registry(engine)
    state = engine.make_state(reg, [0], [1], p0_hand_printing_ids=[1])
    for d in state.library_snapshot(0):
        assert d["controller_id"] == 0
    for d in state.hand_snapshot(0):
        assert d["controller_id"] == 0
    for d in state.library_snapshot(1):
        assert d["controller_id"] == 1


def test_make_state_zone_stamps_correct(engine):
    """Library objects carry zone=ZONE_LIBRARY, hand objects ZONE_HAND."""
    reg = _two_card_registry(engine)
    state = engine.make_state(reg, [0, 1], [0], p0_hand_printing_ids=[1])
    for d in state.library_snapshot(0):
        assert d["zone"] == ZONE_LIBRARY
    for d in state.hand_snapshot(0):
        assert d["zone"] == ZONE_HAND


# --- 6. initial state defaults --------------------------------------


def test_make_state_initial_state_defaults(engine):
    reg = _two_card_registry(engine)
    state = engine.make_state(reg, [0], [1])
    assert state.turn_number == 1
    assert state.active_player_idx == 0
    assert state.priority_player_idx == 0
    assert state.life_totals == [20, 20]
    assert state.is_over() is False
    # Battlefield, graveyards start empty.
    assert state.battlefield_sizes == [0, 0]
    assert state.graveyard_snapshot(0) == []
    assert state.graveyard_snapshot(1) == []
    assert state.exile_snapshot(0) == []
    assert state.exile_snapshot(1) == []


# --- 7. empty libraries allowed -------------------------------------


def test_make_state_empty_libraries_valid(engine):
    reg = _two_card_registry(engine)
    state = engine.make_state(reg, [], [])
    assert state.library_sizes == [0, 0]
    assert state.hand_sizes == [0, 0]
    # State is still constructible — caller will handle deck-out.
    assert state.is_over() is False


def test_make_state_one_empty_one_populated(engine):
    reg = _two_card_registry(engine)
    state = engine.make_state(reg, [], [0, 1])
    assert state.library_sizes == [0, 2]


# --- 8. None vs empty Vec for hand args -----------------------------


def test_make_state_hand_none_produces_empty(engine):
    reg = _two_card_registry(engine)
    state = engine.make_state(reg, [0], [1])
    # Both hand args omitted (default None).
    assert state.hand_sizes == [0, 0]


def test_make_state_hand_empty_list_produces_empty(engine):
    reg = _two_card_registry(engine)
    state = engine.make_state(
        reg, [0], [1], p0_hand_printing_ids=[], p1_hand_printing_ids=[]
    )
    assert state.hand_sizes == [0, 0]


def test_make_state_hand_none_and_empty_are_equivalent(engine):
    """None and [] produce the same fingerprint."""
    reg = _two_card_registry(engine)
    state_none = engine.make_state(reg, [0, 1], [1])
    state_empty = engine.make_state(
        reg, [0, 1], [1], p0_hand_printing_ids=[], p1_hand_printing_ids=[]
    )
    assert state_none.fingerprint() == state_empty.fingerprint()


# --- 9. fingerprint determinism -------------------------------------


def test_make_state_fingerprint_deterministic(engine):
    """Same inputs produce identical fingerprints across calls."""
    reg = _two_card_registry(engine)
    state_a = engine.make_state(
        reg, [0, 0, 1], [1, 1, 0], p0_hand_printing_ids=[0, 1]
    )
    state_b = engine.make_state(
        reg, [0, 0, 1], [1, 1, 0], p0_hand_printing_ids=[0, 1]
    )
    assert state_a.fingerprint() == state_b.fingerprint()


def test_make_state_fingerprint_differs_on_order(engine):
    """Different library order -> different fingerprint."""
    reg = _two_card_registry(engine)
    state_a = engine.make_state(reg, [0, 1], [1])
    state_b = engine.make_state(reg, [1, 0], [1])
    assert state_a.fingerprint() != state_b.fingerprint()


# --- 10. snapshot getters work --------------------------------------


def test_make_state_hand_snapshot_returns_correct_dicts(engine):
    reg = _two_card_registry(engine)
    state = engine.make_state(
        reg, [0], [1], p0_hand_printing_ids=[0, 1]
    )
    hand = state.hand_snapshot(0)
    assert len(hand) == 2
    # Per-object dict shape — same keys as the parity-smoke signature.
    expected_keys = {
        "id",
        "printing_id",
        "printing_name",
        "tapped",
        "summoning_sick",
        "damage",
        "counters",
        "controller_id",
        "zone",
    }
    for d in hand:
        assert set(d.keys()) == expected_keys
    assert [d["printing_name"] for d in hand] == ["Forest", "Grizzly Bears"]
    assert [d["printing_id"] for d in hand] == [0, 1]
    assert [d["zone"] for d in hand] == [ZONE_HAND, ZONE_HAND]


def test_make_state_library_snapshot_round_trips_printing_names(engine):
    reg = _two_card_registry(engine)
    state = engine.make_state(reg, [0, 1, 0, 1], [])
    lib = state.library_snapshot(0)
    assert [d["printing_name"] for d in lib] == [
        "Forest",
        "Grizzly Bears",
        "Forest",
        "Grizzly Bears",
    ]


# --- registry-snapshot freeze semantics -----------------------------


def test_make_state_registry_snapshot_is_frozen(engine):
    """Mutating the Python-side Registry after make_state doesn't
    affect the returned state's view of the printings."""
    reg = _two_card_registry(engine)
    state = engine.make_state(reg, [0, 1], [1])
    # After construction, register a third printing.
    new_id = reg.register_printing({
        "name": "Llanowar Elves",
        "card_types": ["Creature"],
        "mana_cost": {"G": 1},
        "effects": [],
        "mana_produced": ["G"],
        "power": 1,
        "toughness": 1,
    })
    assert new_id == 2
    # The state's registry_size reflects what was frozen at make_state
    # time, not the post-mutation builder.
    assert state.registry_size == 2
