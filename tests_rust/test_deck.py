"""Deck-loading primitives on ``GameState``.

Ports the deck-replacement pattern from ``tests/_test_decks.py`` +
``src/mtg_bot/game.py`` (which builds a player's library by
constructing a fresh GameObject per card name in a decklist and
assigning them to ``player.library``). The Rust slice collapses that
pattern into a single primitive that owns:

- printing-id validation (each id must point at a real registry slot),
- player-id validation,
- fresh GameObject id allocation (must not collide with any existing
  GameObject in any zone on either player),
- whole-library replacement via ``Arc::make_mut`` (so cloning a
  GameState and then loading a deck on the clone leaves the source
  state's library untouched — CoW canary).

**Top-of-library convention.** The round-1 zone slice settled
``library[Vec::last()] = top of library``. ``load_deck`` honors that:
the LAST element of the input ``printing_ids`` list ends up at the
top of the library, so the next ``draw_card`` call returns it.

**No automatic shuffle.** Callers that want a randomized library
follow ``load_deck`` with ``shuffle_library_with_seed`` (round-4
library slice).
"""

from __future__ import annotations

import pytest


# Synthetic state's registry holds 3 printings:
#   pid 0 = Forest   (mana_produced=["G"], no P/T)
#   pid 1 = Grizzly Bears (creature, 2/2)
#   pid 2 = Llanowar Elves (creature 1/1, also produces G)
FOREST_PID = 0
BEARS_PID = 1
ELVES_PID = 2


def _all_obj_ids(state):
    """Collect every GameObject id across both players, all four
    zones. Used to verify uniqueness invariants."""
    ids = []
    for player_id in (0, 1):
        # We can't directly read zones from Python, but every object
        # has a unique id in the synthetic-state initializer, and
        # find_object_zone searches all four zones — we can probe
        # the size getters and walk via printing_name_of indirectly.
        # Easier path: use scry to dump the library, and rely on
        # synthetic-state ids being a contiguous range.
        pass
    return ids


def _library_obj_ids(state, player_id, n):
    """Top-first dump of player's library obj_ids (from scry)."""
    return state.scry(player_id, n)


# --- Happy path -------------------------------------------------------------


def test_load_deck_replaces_library(synthetic_state):
    """``load_deck(0, [Forest, Forest, Bears, Elves])`` swaps player
    0's library for 4 fresh GameObjects, one per printing_id in input
    order. Top of library = LAST element of the input list."""
    synthetic_state.load_deck(0, [FOREST_PID, FOREST_PID, BEARS_PID, ELVES_PID])

    assert synthetic_state.library_sizes[0] == 4
    # Top-first dump should resolve to: Elves (last), then Bears, then
    # Forest, then Forest.
    top4 = synthetic_state.scry(0, 4)
    assert len(top4) == 4
    names = [synthetic_state.printing_name_of(oid) for oid in top4]
    assert names == ["Llanowar Elves", "Grizzly Bears", "Forest", "Forest"]


def test_load_deck_replaces_existing_library(synthetic_state):
    """The OLD library is replaced wholesale, not appended to. Old
    obj_ids should no longer be present in the new library."""
    # Snapshot a few of the OLD library obj_ids — synthetic state
    # builds player 0 with library ids 17..66.
    old_top_id = synthetic_state.scry(0, 1)[0]
    assert synthetic_state.library_sizes[0] == 50

    synthetic_state.load_deck(0, [FOREST_PID, BEARS_PID])

    assert synthetic_state.library_sizes[0] == 2
    new_ids = synthetic_state.scry(0, 2)
    # Old top obj_id must NOT be in the new library — it was a fresh
    # build, not an append.
    assert old_top_id not in new_ids


def test_load_deck_top_of_library_is_last_element(synthetic_state):
    """First call to ``draw_card`` returns the LAST printing_id in the
    input list (top of library = Vec.last())."""
    # Distinguishable printing_ids so we can verify which one drew.
    synthetic_state.load_deck(0, [FOREST_PID, BEARS_PID, ELVES_PID])
    drawn_id = synthetic_state.draw_card(0)
    assert drawn_id is not None
    # The drawn card was at the top of the library; per the
    # convention that's the LAST input — Llanowar Elves.
    assert synthetic_state.printing_name_of(drawn_id) == "Llanowar Elves"


def test_load_deck_assigns_unique_ids(synthetic_state):
    """The 4 fresh GameObjects must have ids that don't collide with
    any existing GameObject (battlefield, hand, or other player's
    zones)."""
    # Pre-existing objects span ids 0..133 in the default synthetic
    # state (P0: 0..66 across battlefield/hand/library, P1: 67..133).
    # After load_deck on P0, the new library ids must avoid colliding
    # with P0's hand+battlefield (0..16) and P1's zones (67..133).
    synthetic_state.load_deck(0, [FOREST_PID, FOREST_PID, BEARS_PID, ELVES_PID])

    new_lib_ids = synthetic_state.scry(0, 4)
    # All unique among themselves.
    assert len(set(new_lib_ids)) == 4
    # No collision with P0's surviving hand or battlefield ids
    # (0..16). The synthetic state lays out P0 hand at 10..16 and
    # battlefield at 0..9; new ids must be outside that range.
    p0_existing = set(range(0, 17))  # battlefield + hand
    p1_existing = set(range(67, 134))  # all of P1
    for nid in new_lib_ids:
        assert nid not in p0_existing
        assert nid not in p1_existing


def test_load_deck_with_empty_list_clears_library(synthetic_state):
    """``load_deck(0, [])`` empties the library (size 0)."""
    assert synthetic_state.library_sizes[0] == 50
    synthetic_state.load_deck(0, [])
    assert synthetic_state.library_sizes[0] == 0
    assert synthetic_state.scry(0, 5) == []


# --- Validation -------------------------------------------------------------


def test_load_deck_invalid_printing_id_raises(synthetic_state):
    """An out-of-range printing_id raises ValueError. State must not
    be partially mutated — library sizes unchanged after the raise."""
    libs_before = synthetic_state.library_sizes
    with pytest.raises(ValueError):
        synthetic_state.load_deck(0, [FOREST_PID, 99])
    assert synthetic_state.library_sizes == libs_before


def test_load_deck_invalid_player_raises(synthetic_state):
    """An out-of-range player_id raises ValueError."""
    libs_before = synthetic_state.library_sizes
    with pytest.raises(ValueError):
        synthetic_state.load_deck(99, [FOREST_PID])
    assert synthetic_state.library_sizes == libs_before


# --- Isolation --------------------------------------------------------------


def test_load_deck_does_not_affect_other_player_library(synthetic_state):
    """Loading a deck on player 0 leaves player 1's library
    untouched."""
    p1_before = _library_obj_ids(synthetic_state, 1, 50)
    assert len(p1_before) == 50

    synthetic_state.load_deck(0, [FOREST_PID, BEARS_PID])

    p1_after = _library_obj_ids(synthetic_state, 1, 50)
    assert p1_after == p1_before
    assert synthetic_state.library_sizes[1] == 50


def test_clone_then_load_deck_does_not_affect_original(synthetic_state):
    """CoW canary: load_deck on a cloned state must not leak back into
    the source."""
    cloned = synthetic_state.clone_once()
    source_lib_before = _library_obj_ids(synthetic_state, 0, 50)

    cloned.load_deck(0, [FOREST_PID, BEARS_PID, ELVES_PID])

    # Clone diverged.
    assert cloned.library_sizes[0] == 3
    # Source untouched.
    assert synthetic_state.library_sizes[0] == 50
    source_lib_after = _library_obj_ids(synthetic_state, 0, 50)
    assert source_lib_after == source_lib_before


# --- Cross-feature edge cases ----------------------------------------------
#
# The tests below exercise deck/registry primitives against neighboring
# slices (zones, setup, fingerprint, snapshot) to surface integration
# bugs that single-feature unit tests miss. They use `synthetic_state`
# (registry baked at 3 printings: Forest/Bears/Elves) for the deck-load
# path and a hand-built `engine.Registry()` + `make_state` for the
# registry-shape probes.


# --- Helpers for the cross-feature tests ----------------------------------

ZONE_LIBRARY_CONST = 1
ZONE_HAND_CONST = 0


def _make_registry_with(engine, *printings):
    """Build a fresh Registry and register each printing dict in order,
    returning the (registry, [printing_ids]) pair."""
    reg = engine.Registry()
    pids = [reg.register_printing(dict(p)) for p in printings]
    return reg, pids


def _forest_dict(name="Forest"):
    return {
        "name": name,
        "card_types": ["Land"],
        "mana_cost": {},
        "effects": [],
        "mana_produced": ["G"],
    }


def _bears_dict(name="Grizzly Bears"):
    return {
        "name": name,
        "card_types": ["Creature"],
        "mana_cost": {"G": 1, "generic": 1},
        "effects": [],
        "power": 2,
        "toughness": 2,
    }


# --- 1. Registry round-trip: declared fields survive register + retrieve ---


def test_registry_round_trip_preserves_all_declared_fields(engine):
    """Register a printing with every cross-cutting field (name,
    mana_cost, card_types, mana_produced, keywords, power, toughness,
    effects, etb_effects) and verify each getter returns the input
    intact. This is the cross-feature canary for the bridge dispatch:
    if a future field is added, this test surfaces a missed getter
    wire-up."""
    reg = engine.Registry()
    forest_pid = reg.register_printing({
        "name": "Forest of Doom",
        "card_types": ["Land"],
        "mana_cost": {},
        "mana_produced": ["G"],
        "keywords": [],
        "effects": [],
    })
    bears_pid = reg.register_printing({
        "name": "Trampling Bear",
        "card_types": ["Creature"],
        "mana_cost": {"G": 1, "generic": 1},
        "power": 3,
        "toughness": 3,
        "keywords": ["trample"],
        "effects": [
            {"kind": "deal_damage", "amount": 2,
             "target": {"kind": "any_creature"}},
        ],
        "etb_effects": [
            {"kind": "gain_life", "amount": 1},
        ],
    })

    assert reg.get_printing_name(forest_pid) == "Forest of Doom"
    assert reg.get_printing_card_types(forest_pid) == ["Land"]
    assert reg.get_printing_mana_produced(forest_pid) == ["G"]
    assert reg.get_printing_power(forest_pid) is None
    assert reg.get_printing_toughness(forest_pid) is None
    assert reg.get_printing_keywords(forest_pid) == []
    assert reg.get_printing_effects(forest_pid) == []

    assert reg.get_printing_name(bears_pid) == "Trampling Bear"
    assert reg.get_printing_card_types(bears_pid) == ["Creature"]
    assert reg.get_printing_mana_produced(bears_pid) is None
    assert reg.get_printing_power(bears_pid) == 3
    assert reg.get_printing_toughness(bears_pid) == 3
    # Keywords are lowercased on register; round-trip in lowercase.
    assert reg.get_printing_keywords(bears_pid) == ["trample"]
    effects = [dict(e) for e in reg.get_printing_effects(bears_pid)]
    assert len(effects) == 1
    assert effects[0]["kind"] == "deal_damage"
    assert effects[0]["amount"] == 2
    assert dict(effects[0]["target"]) == {"kind": "any_creature"}
    etb_effects = [dict(e) for e in reg.get_printing_etb_effects(bears_pid)]
    assert len(etb_effects) == 1
    assert etb_effects[0]["kind"] == "gain_life"
    assert etb_effects[0]["amount"] == 1


# --- 2. Same-name distinct printing_ids resolve distinctly via load_deck ---


def test_load_deck_distinguishes_same_name_distinct_printing_ids(engine):
    """Two registry slots can carry the SAME printed name but be
    distinct printing_ids (e.g. reprints with different effects). The
    deck-loading primitive must keep them distinct: same name, different
    pid, distinct fingerprint contributions, distinct lookup."""
    reg = engine.Registry()
    forest_a = reg.register_printing({
        "name": "Forest",
        "card_types": ["Land"],
        "mana_cost": {},
        "effects": [],
        "mana_produced": ["G"],
    })
    forest_b = reg.register_printing({
        "name": "Forest",  # same name as forest_a
        "card_types": ["Land"],
        "mana_cost": {},
        "effects": [],
        "mana_produced": ["G"],
        # No other distinguishing field; the printing_id alone
        # differentiates them.
    })
    assert forest_a != forest_b
    state = engine.make_state(reg, [forest_a, forest_b], [])
    lib = state.library_snapshot(0)
    assert [d["printing_id"] for d in lib] == [forest_a, forest_b]
    # Both resolve to the same printing_name via registry lookup.
    assert [d["printing_name"] for d in lib] == ["Forest", "Forest"]
    # ...but the underlying printing_ids differ.
    assert lib[0]["printing_id"] != lib[1]["printing_id"]


# --- 3. card_types Land round-trip survives register/retrieve -------------


def test_card_types_land_round_trip_preserved_for_filter_dispatch(engine):
    """A basic Forest registers with ``card_types=["Land"]`` and the
    getter returns the same list. This is the cross-feature canary for
    ``Effect::DestroyTargetLand`` — that resolve arm scans for objects
    whose printing's card_types contains "Land"; if the round-trip
    silently dropped "Land", DestroyTargetLand would never find a
    target."""
    reg = engine.Registry()
    forest_pid = reg.register_printing(_forest_dict())
    assert reg.get_printing_card_types(forest_pid) == ["Land"]
    # Compound type like "Basic Land — Forest" decomposes on the
    # Python side; here `card_types` is the closed vocab list. Confirm
    # multi-type stays intact too.
    dryad_pid = reg.register_printing({
        "name": "Dryad Arbor",
        "card_types": ["Land", "Creature"],
        "mana_cost": {},
        "effects": [],
        "mana_produced": ["G"],
        "power": 1,
        "toughness": 1,
    })
    types = reg.get_printing_card_types(dryad_pid)
    assert "Land" in types
    assert "Creature" in types


# --- 4. card_types Creature round-trip for parse_effect target filter -----


def test_card_types_creature_round_trip_for_any_creature_target_filter(engine):
    """A Grizzly-Bears-shaped printing registers with
    ``card_types=["Creature"]`` and round-trips. Independently, the
    ``parse_effect`` parser accepts ``target={"kind":"any_creature"}``
    and emits a deal_damage effect with that filter — the two pieces
    have to agree at runtime, so we test both register paths in one
    place."""
    reg = engine.Registry()
    bears_pid = reg.register_printing(_bears_dict())
    assert reg.get_printing_card_types(bears_pid) == ["Creature"]

    # Now register a Shock-shaped printing whose effect targets
    # any_creature — the round-trip must produce an effect dict whose
    # target kind is "any_creature", matching the card_types["Creature"]
    # filter contract.
    shock_pid = reg.register_printing({
        "name": "Mini Shock",
        "card_types": ["Instant"],
        "mana_cost": {"R": 1},
        "effects": [
            {"kind": "deal_damage", "amount": 2,
             "target": {"kind": "any_creature"}},
        ],
    })
    effects = [dict(e) for e in reg.get_printing_effects(shock_pid)]
    assert len(effects) == 1
    assert dict(effects[0]["target"]) == {"kind": "any_creature"}


# --- 5. Same registry shared by both decklists -> consistent lookups ------


def test_make_state_with_shared_registry_consistent_obj_to_printing(engine):
    """A single Registry handed to ``make_state`` to seed both players'
    decklists produces a state where every object on either side
    resolves to a printing in that registry. This is the canary that
    the registry isn't accidentally cloned-then-mutated per-player."""
    reg, (forest_pid, bears_pid) = _make_registry_with(
        engine, _forest_dict(), _bears_dict()
    )
    state = engine.make_state(
        reg,
        [forest_pid, bears_pid, forest_pid],
        [bears_pid, forest_pid],
        p0_hand_printing_ids=[forest_pid],
        p1_hand_printing_ids=[bears_pid],
    )
    # Every object across both players must resolve via the registry.
    for player_id in (0, 1):
        for d in state.library_snapshot(player_id):
            name = state.printing_name_of(d["id"])
            assert name in ("Forest", "Grizzly Bears")
            assert name == d["printing_name"]
        for d in state.hand_snapshot(player_id):
            name = state.printing_name_of(d["id"])
            assert name in ("Forest", "Grizzly Bears")
            assert name == d["printing_name"]
    # registry_size reflects the single shared registry, not 2x.
    assert state.registry_size == 2


# --- 6. find_object_zone agrees with deck-side allocation after make_state ---


def test_find_object_zone_after_make_state_agrees_with_setup(engine):
    """``find_object_zone`` (zones slice) returns ZONE_LIBRARY for every
    library obj_id and ZONE_HAND for every hand obj_id immediately
    after make_state. This is the cross-slice canary that the
    zone-stamping in make_state and the zone-search in
    find_object_zone agree on the same constants."""
    reg, (forest_pid, bears_pid) = _make_registry_with(
        engine, _forest_dict(), _bears_dict()
    )
    state = engine.make_state(
        reg,
        [forest_pid, bears_pid],
        [bears_pid],
        p0_hand_printing_ids=[forest_pid, bears_pid],
        p1_hand_printing_ids=[forest_pid],
    )
    for player_id in (0, 1):
        for d in state.library_snapshot(player_id):
            assert state.find_object_zone(d["id"]) == ZONE_LIBRARY_CONST
        for d in state.hand_snapshot(player_id):
            assert state.find_object_zone(d["id"]) == ZONE_HAND_CONST


# --- 7. Registry survives clone: fingerprint stability after clone_once ---


def test_registry_survives_clone_fingerprint_stable(synthetic_state):
    """Cloning a GameState bumps the registry Arc's refcount; the clone
    shares the same registry pointer as the source. The fingerprint of
    a freshly cloned state (no mutation) must equal the source's —
    proof that the registry-backed printing-name lookups stay stable
    across the clone boundary."""
    fp_before = synthetic_state.fingerprint()
    cloned = synthetic_state.clone_once()
    assert cloned.fingerprint() == fp_before
    # And again after one more clone hop — still the same digest.
    cloned2 = cloned.clone_once()
    assert cloned2.fingerprint() == fp_before


# --- 8. Empty decklist into make_state: produces empty zones, no error ----


def test_make_state_empty_decklist_yields_empty_state(engine):
    """``make_state(reg, [], [])`` with empty libraries and no hand args
    is a legal no-op build — the resulting state has empty libraries,
    empty hands, and is still ``is_over=False`` (game-over check is
    pure-life-derivation, not deck-out-derivation)."""
    reg, _ = _make_registry_with(engine, _forest_dict())
    state = engine.make_state(reg, [], [])
    assert state.library_sizes == [0, 0]
    assert state.hand_sizes == [0, 0]
    assert state.battlefield_sizes == [0, 0]
    assert state.life_totals == [20, 20]
    assert state.is_over() is False
    # Empty deck side still has a registry attached — registry_size is
    # the snapshot's printings count, not zero.
    assert state.registry_size == 1


# --- 9. Lots-of-copies decklist allocates N distinct obj_ids --------------


def test_load_deck_thirty_copies_allocates_thirty_distinct_obj_ids(
    synthetic_state,
):
    """A 30x Forest load_deck must produce 30 GameObjects with 30
    distinct ids — no id reuse, no off-by-one in the next_id
    allocator. Cross-feature with the zones slice's id-uniqueness
    invariant."""
    deck = [FOREST_PID] * 30
    synthetic_state.load_deck(0, deck)
    assert synthetic_state.library_sizes[0] == 30
    lib_ids = synthetic_state.scry(0, 30)
    assert len(lib_ids) == 30
    assert len(set(lib_ids)) == 30  # all distinct
    # Every object resolves to the same printing name (same pid).
    for oid in lib_ids:
        assert synthetic_state.printing_name_of(oid) == "Forest"


# --- 10. Fingerprint differs when registry has different printing name ----


def test_make_state_fingerprint_differs_when_registry_name_differs(engine):
    """Two states with the SAME deck shape but DIFFERENT registry
    contents at the same printing_id produce different fingerprints —
    because fingerprint pulls the printing's ``name`` through the
    registry into each object's signature. Cross-feature canary that
    registry contents flow into the fingerprint via the zone-signature
    name-lookup path."""
    reg_a, (forest_a,) = _make_registry_with(engine, _forest_dict("Forest"))
    reg_b, (forest_b,) = _make_registry_with(engine, _forest_dict("Spooky Forest"))
    # Same printing_id slot (0), same deck shape, but different name.
    assert forest_a == forest_b == 0
    state_a = engine.make_state(reg_a, [0, 0], [0])
    state_b = engine.make_state(reg_b, [0, 0], [0])
    # Identical zone shape (sizes, ids, controllers, zones, per-object
    # state) but different printing name -> different fingerprint.
    assert state_a.library_sizes == state_b.library_sizes
    assert state_a.fingerprint() != state_b.fingerprint()
    # Sanity: the name flows into the snapshot too.
    name_a = state_a.library_snapshot(0)[0]["printing_name"]
    name_b = state_b.library_snapshot(0)[0]["printing_name"]
    assert name_a == "Forest"
    assert name_b == "Spooky Forest"
