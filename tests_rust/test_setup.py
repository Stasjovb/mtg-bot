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


# --- 11. optional seeded library shuffle ----------------------------
#
# `shuffle_seed=None` (default) preserves caller order; `shuffle_seed=s`
# runs an in-Rust xorshift64 Fisher-Yates over each player's library,
# with p1's seed derived from s via golden-ratio xor so p0/p1 get
# independent permutations. Hands are NEVER shuffled (caller-controlled
# order, matches the Python "draw after shuffle" semantics).


def _big_registry(engine, n=32):
    """Fresh registry with `n` distinct Forest-shaped printings — each
    given a unique name so per-printing-id positions are individually
    distinguishable in the library order."""
    reg = engine.Registry()
    for i in range(n):
        pid = reg.register_printing({
            "name": f"Forest_{i}",
            "card_types": ["Land"],
            "mana_cost": {},
            "effects": [],
            "mana_produced": ["G"],
        })
        assert pid == i
    return reg


def test_make_state_no_shuffle_seed_preserves_order(engine):
    """Backward compat: shuffle_seed omitted (None) -> library order
    matches the caller's input list exactly."""
    reg = _big_registry(engine, n=16)
    deck = list(range(16))
    state = engine.make_state(reg, deck, deck)
    lib_p0 = [d["printing_id"] for d in state.library_snapshot(0)]
    lib_p1 = [d["printing_id"] for d in state.library_snapshot(1)]
    assert lib_p0 == deck
    assert lib_p1 == deck


def test_make_state_shuffle_seed_changes_order(engine):
    """A non-trivial library + a real seed produces an order different
    from the input. (With 16! permutations, an identity shuffle is
    astronomically unlikely.)"""
    reg = _big_registry(engine, n=16)
    deck = list(range(16))
    state = engine.make_state(reg, deck, deck, shuffle_seed=42)
    lib_p0 = [d["printing_id"] for d in state.library_snapshot(0)]
    lib_p1 = [d["printing_id"] for d in state.library_snapshot(1)]
    assert lib_p0 != deck
    assert lib_p1 != deck
    # Permutation invariant — no duplication / loss.
    assert sorted(lib_p0) == deck
    assert sorted(lib_p1) == deck


def test_make_state_shuffle_seed_is_deterministic(engine):
    """Same seed twice -> identical shuffled order."""
    reg = _big_registry(engine, n=20)
    deck = list(range(20))
    state_a = engine.make_state(reg, deck, deck, shuffle_seed=12345)
    state_b = engine.make_state(reg, deck, deck, shuffle_seed=12345)
    lib_a0 = [d["printing_id"] for d in state_a.library_snapshot(0)]
    lib_b0 = [d["printing_id"] for d in state_b.library_snapshot(0)]
    lib_a1 = [d["printing_id"] for d in state_a.library_snapshot(1)]
    lib_b1 = [d["printing_id"] for d in state_b.library_snapshot(1)]
    assert lib_a0 == lib_b0
    assert lib_a1 == lib_b1
    # Fingerprint also matches end-to-end.
    assert state_a.fingerprint() == state_b.fingerprint()


def test_make_state_different_shuffle_seeds_differ(engine):
    """Different seeds -> different shuffled orders (high probability)."""
    reg = _big_registry(engine, n=20)
    deck = list(range(20))
    state_a = engine.make_state(reg, deck, deck, shuffle_seed=1)
    state_b = engine.make_state(reg, deck, deck, shuffle_seed=2)
    lib_a0 = [d["printing_id"] for d in state_a.library_snapshot(0)]
    lib_b0 = [d["printing_id"] for d in state_b.library_snapshot(0)]
    assert lib_a0 != lib_b0


def test_make_state_shuffle_p0_p1_independent(engine):
    """Same starting library on both sides + same seed -> p0 and p1
    libraries land in DIFFERENT orders because the implementation
    derives a separate p1 seed via golden-ratio xor."""
    reg = _big_registry(engine, n=24)
    deck = list(range(24))
    state = engine.make_state(reg, deck, deck, shuffle_seed=42)
    lib_p0 = [d["printing_id"] for d in state.library_snapshot(0)]
    lib_p1 = [d["printing_id"] for d in state.library_snapshot(1)]
    assert lib_p0 != lib_p1
    # Both must still be permutations of the original deck.
    assert sorted(lib_p0) == deck
    assert sorted(lib_p1) == deck


def test_make_state_shuffle_does_not_touch_hand(engine):
    """Hand order survives the shuffle unchanged — even with a seed
    set, the hand is the caller's exact input order."""
    reg = _big_registry(engine, n=16)
    deck = list(range(16))
    hand = [3, 7, 1, 9]
    state = engine.make_state(
        reg, deck, deck,
        p0_hand_printing_ids=hand,
        p1_hand_printing_ids=hand,
        shuffle_seed=99,
    )
    hand_p0 = [d["printing_id"] for d in state.hand_snapshot(0)]
    hand_p1 = [d["printing_id"] for d in state.hand_snapshot(1)]
    assert hand_p0 == hand
    assert hand_p1 == hand


def test_make_state_shuffle_preserves_library_size(engine):
    """Library size is unchanged after shuffle — no duplication, no
    loss, no off-by-one."""
    reg = _big_registry(engine, n=30)
    deck = list(range(30))
    state = engine.make_state(reg, deck, deck, shuffle_seed=7)
    assert state.library_sizes == [30, 30]
    lib_p0 = [d["printing_id"] for d in state.library_snapshot(0)]
    lib_p1 = [d["printing_id"] for d in state.library_snapshot(1)]
    assert len(lib_p0) == 30
    assert len(lib_p1) == 30
    # Multiset invariant.
    assert sorted(lib_p0) == deck
    assert sorted(lib_p1) == deck


def test_make_state_shuffle_empty_library_noop(engine):
    """Empty library + shuffle_seed -> no error, still empty."""
    reg = _big_registry(engine, n=4)
    state = engine.make_state(reg, [], [], shuffle_seed=42)
    assert state.library_sizes == [0, 0]
    assert state.library_snapshot(0) == []
    assert state.library_snapshot(1) == []


def test_make_state_shuffle_single_card_library_noop(engine):
    """One-card library + shuffle_seed -> Fisher-Yates degenerates to
    a no-op, the card stays put."""
    reg = _big_registry(engine, n=4)
    state = engine.make_state(reg, [2], [3], shuffle_seed=99)
    lib_p0 = [d["printing_id"] for d in state.library_snapshot(0)]
    lib_p1 = [d["printing_id"] for d in state.library_snapshot(1)]
    assert lib_p0 == [2]
    assert lib_p1 == [3]


# --- 12. cross-feature edge cases -----------------------------------
#
# Coverage for the parity-load-bearing contract surface exercised by
# the 1000-game smoke harness: setup-side serialization stability,
# deterministic shuffle invariants, id-allocation order pinning, and
# initial-state defaults that the parity diff treats as load-bearing.


# Canonical "default args" make_state baseline — a Forest+Bears
# 2-card registry, a [0,0,1] / [1,1,0] deck, no hand, no shuffle.
# Locked-in fingerprint string acts as a regression detector for any
# drift in the setup-side serialization (zone object layout, default
# turn/phase/life/priority bytes, id allocation order, registry
# snapshot semantics). If this digest changes, either parity smoke
# breaks or the parity_smoke.py:hash_state recipe needs the same
# update on both sides of the bridge.
EXPECTED_MAKE_STATE_CANONICAL_DEFAULT_FP = "a1193453edec"


def test_make_state_canonical_default_fingerprint_pinned(engine):
    """Default-args make_state (no hands, no shuffle) on the canonical
    Forest+Bears registry produces the pinned baseline fingerprint.

    Regression-detect for setup-side serialization drift — if this
    drifts, the parity-smoke ``hash_state`` recipe and the Rust
    fingerprint serializer have diverged and the 1000-game smoke is
    no longer comparing like-for-like states.
    """
    reg = _two_card_registry(engine)
    state = engine.make_state(reg, [0, 0, 1], [1, 1, 0])
    assert state.fingerprint() == EXPECTED_MAKE_STATE_CANONICAL_DEFAULT_FP


def test_make_state_same_seed_identical_fingerprints(engine):
    """Same shuffle_seed + same decks -> byte-identical fingerprints.

    Two completely-independent make_state invocations with the same
    seed must produce indistinguishable states end-to-end (not just
    matching library orders — the full serialized fingerprint must
    line up).
    """
    reg = _big_registry(engine, n=24)
    deck = list(range(24))
    fp_a = engine.make_state(reg, deck, deck, shuffle_seed=2026).fingerprint()
    fp_b = engine.make_state(reg, deck, deck, shuffle_seed=2026).fingerprint()
    assert fp_a == fp_b


def test_make_state_different_seeds_different_fingerprints(engine):
    """Different shuffle_seed values produce different fingerprints —
    entropy from the seed must mix all the way through to the digest,
    not just into the library order."""
    reg = _big_registry(engine, n=24)
    deck = list(range(24))
    fp_a = engine.make_state(reg, deck, deck, shuffle_seed=1).fingerprint()
    fp_b = engine.make_state(reg, deck, deck, shuffle_seed=2).fingerprint()
    fp_c = engine.make_state(reg, deck, deck, shuffle_seed=999_999).fingerprint()
    assert fp_a != fp_b
    assert fp_b != fp_c
    assert fp_a != fp_c


def test_make_state_p0_p1_independent_permutations_round23_contract(engine):
    """Round-23 golden-ratio-derivation contract: with the SAME deck
    on both sides and a single user-facing seed, p0 and p1 land in
    DIFFERENT permutations — the implementation derives p1's seed via
    ``s.wrapping_mul(0x9E3779B97F4A7C15)`` to decorrelate the two
    streams. Multiple seeds + multiple deck sizes for robustness."""
    reg = _big_registry(engine, n=32)
    deck = list(range(32))
    for seed in (1, 42, 12345, 0xDEAD_BEEF):
        state = engine.make_state(reg, deck, deck, shuffle_seed=seed)
        lib_p0 = [d["printing_id"] for d in state.library_snapshot(0)]
        lib_p1 = [d["printing_id"] for d in state.library_snapshot(1)]
        assert lib_p0 != lib_p1, f"p0/p1 collided at seed {seed}"
        # Both still valid permutations of the input deck.
        assert sorted(lib_p0) == deck
        assert sorted(lib_p1) == deck


def test_make_state_hand_order_pinned_by_explicit_argument(engine):
    """Hands are NEVER shuffled — caller-controlled order survives
    end-to-end even when ``shuffle_seed`` is set. Pin via an explicit
    hand argument with a distinctive (non-sorted, non-reversed)
    permutation that no shuffle would happen to land on."""
    reg = _big_registry(engine, n=16)
    deck = list(range(16))
    # A hand permutation that would be vanishingly unlikely to fall
    # out of any 7-element shuffle by chance.
    pinned_hand = [11, 3, 7, 0, 14, 1, 9]
    state = engine.make_state(
        reg, deck, deck,
        p0_hand_printing_ids=pinned_hand,
        p1_hand_printing_ids=pinned_hand,
        shuffle_seed=42,
    )
    hand_p0 = [d["printing_id"] for d in state.hand_snapshot(0)]
    hand_p1 = [d["printing_id"] for d in state.hand_snapshot(1)]
    assert hand_p0 == pinned_hand
    assert hand_p1 == pinned_hand


def test_make_state_object_id_allocation_order_round23_contract(engine):
    """Round-23 id-allocation contract: ids are issued sequentially
    starting from 0 in the order p0-library, p0-hand, p1-library,
    p1-hand. Snapshot getters expose those ids verbatim — pin the
    full sequence so any reordering shows up here, not later as a
    parity-smoke trajectory-divergence mystery."""
    reg = _two_card_registry(engine)
    state = engine.make_state(
        reg,
        [0, 0, 1, 0],          # p0 library: ids 0..3
        [1, 0, 1],             # p1 library: starts after p0 hand
        p0_hand_printing_ids=[1, 0],  # p0 hand: ids 4..5
        p1_hand_printing_ids=[0, 1, 0],
    )
    # p0 library, p0 hand, p1 library, p1 hand — in that order.
    assert [d["id"] for d in state.library_snapshot(0)] == [0, 1, 2, 3]
    assert [d["id"] for d in state.hand_snapshot(0)] == [4, 5]
    assert [d["id"] for d in state.library_snapshot(1)] == [6, 7, 8]
    assert [d["id"] for d in state.hand_snapshot(1)] == [9, 10, 11]
    # And the global id set is contiguous 0..N-1.
    all_ids = (
        [d["id"] for d in state.library_snapshot(0)]
        + [d["id"] for d in state.hand_snapshot(0)]
        + [d["id"] for d in state.library_snapshot(1)]
        + [d["id"] for d in state.hand_snapshot(1)]
    )
    assert all_ids == list(range(12))


def test_make_state_initial_turn_phase_life_active_pinned(engine):
    """Pin every initial-state default the parity diff treats as
    load-bearing: life=20 both sides, active_player=0,
    priority_player=0, phase=PHASE_UNTAP (0), turn=1, not over."""
    reg = _two_card_registry(engine)
    state = engine.make_state(reg, [0, 0], [1, 1])
    assert state.life_totals == [20, 20]
    assert state.active_player_idx == 0
    assert state.priority_player_idx == 0
    assert state.current_phase() == 0  # PHASE_UNTAP
    assert state.turn_number == 1
    assert state.is_over() is False


def test_make_state_battlefield_graveyard_exile_empty_both_players(engine):
    """After make_state, every non-library/non-hand zone is empty on
    both sides — phase-2's parity smoke starts from this exact
    empty-board / fresh-hand state."""
    reg = _two_card_registry(engine)
    state = engine.make_state(
        reg,
        [0, 1, 0],
        [1, 0, 1],
        p0_hand_printing_ids=[0],
        p1_hand_printing_ids=[1],
    )
    assert state.battlefield_sizes == [0, 0]
    assert state.graveyard_snapshot(0) == []
    assert state.graveyard_snapshot(1) == []
    assert state.exile_snapshot(0) == []
    assert state.exile_snapshot(1) == []


def test_make_state_legal_decisions_emits_initial_choices(engine):
    """Cross-feature: a freshly-made-state at phase=PHASE_UNTAP has no
    sorcery-timing or activation choices yet — ``legal_decisions``
    emits exactly ``[PassPriority]`` for both players. Locks the
    setup-to-legal handoff (no stray choices accidentally seeded into
    the initial state)."""
    reg = _two_card_registry(engine)
    state = engine.make_state(
        reg,
        [0, 0, 1, 0, 1],
        [1, 0, 1, 1, 0],
        p0_hand_printing_ids=[0, 1],
        p1_hand_printing_ids=[1, 0],
    )
    # Priority holder sees just PassPriority — no PlayLand yet at
    # PHASE_UNTAP (sorcery-timing gate is closed).
    p0_actions = state.legal_decisions(0)
    assert [a["kind"] for a in p0_actions] == ["pass_priority"]
    # Off-priority caller also sees just PassPriority.
    p1_actions = state.legal_decisions(1)
    assert [a["kind"] for a in p1_actions] == ["pass_priority"]


def test_make_state_min_size_one_card_library_each_constructs_valid_state(engine):
    """Min-size deck (1 card per library) doesn't crash and produces
    a valid state — bottom edge of the deck-size range. Library
    sizes, id allocation, defaults, and ``legal_decisions`` all stay
    well-defined."""
    reg = _two_card_registry(engine)
    state = engine.make_state(reg, [0], [1])
    # Zone sizes.
    assert state.library_sizes == [1, 1]
    assert state.hand_sizes == [0, 0]
    assert state.battlefield_sizes == [0, 0]
    # Id allocation — only two objects, ids 0 and 1.
    assert [d["id"] for d in state.library_snapshot(0)] == [0]
    assert [d["id"] for d in state.library_snapshot(1)] == [1]
    # Defaults intact.
    assert state.life_totals == [20, 20]
    assert state.turn_number == 1
    assert state.current_phase() == 0
    assert state.is_over() is False
    # Fingerprint computes cleanly — 12 lowercase hex.
    fp = state.fingerprint()
    assert isinstance(fp, str) and len(fp) == 12
    # Legal-decisions handoff still works at the size floor.
    assert [a["kind"] for a in state.legal_decisions(0)] == ["pass_priority"]
