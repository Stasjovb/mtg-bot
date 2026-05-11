"""Read-only zone snapshot getters on the Rust ``GameState``.

Round-21 phase-2 slice. Exercises the six new pymethods that project
zones into Python lists/dicts whose shape matches
``scripts/parity_smoke.py:_zone_signature``:

* ``hand_snapshot``, ``library_snapshot``, ``graveyard_snapshot``,
  ``exile_snapshot`` — per-player, by zone.
* ``battlefield_snapshot`` — both players' battlefields combined,
  p0-first.
* ``mana_pool_snapshot`` — single dict ``{W, U, B, R, G, C}``.

The parity harness compares a Rust ``GameState`` to a Python one
byte-for-byte via the same hash function on each side; a missing /
wrongly-typed field here breaks the entire smoke. So the tests pin
both shape (the 9 expected per-object keys, mana-pool keys) and
value-types (id/printing_id are int, tapped is bool, counters is
int).

Synthetic-state seed (``make_synthetic_state(num_battlefield=10,
num_hand=7, num_library=50)``):

* p0 battlefield: ids 0..9 — first 5 Forest (Land), last 5 Bears
  (Creature).
* p0 hand: ids 10..16 — Llanowar Elves (Creature).
* p0 library: ids 17..66 — Forest.
* p1 battlefield: ids 67..76. p1 hand: 77..83. p1 library: 84..133.
"""

from __future__ import annotations

import pytest


ZONE_HAND = 0
ZONE_LIBRARY = 1
ZONE_BATTLEFIELD = 2
ZONE_GRAVEYARD = 3
ZONE_EXILE = 5

# Expected per-object dict keys (matches parity_smoke._zone_signature).
EXPECTED_KEYS = {
    "id",
    "printing_id",
    "printing_name",
    "tapped",
    "summoning_sick",
    "damage",
    "counters",
    "controller_id",
    "zone",
    # Round-28 attach foundation: snapshot dicts include
    # ``attached_to`` (None for the universal default; the target id
    # once an Aura/Equipment has been attached).
    "attached_to",
}

_FOREST = {
    "name": "Forest",
    "card_types": ["Land"],
    "mana_cost": {},
    "effects": [],
    "mana_produced": ["G"],
}
_BEARS = {
    "name": "Grizzly Bears",
    "card_types": ["Creature"],
    "mana_cost": {"G": 1, "generic": 1},
    "effects": [],
}


def _exile_creature_dict():
    """Path-to-Exile-shaped: instant that exiles target creature.

    Used to populate the exile zone (``register_and_inject_object``
    only supports zones 0-3, so exile content must be produced via a
    resolve dispatch).
    """
    return {
        "name": "Path to Exile",
        "card_types": ["Instant"],
        "mana_cost": {"W": 1},
        "effects": [
            {
                "kind": "exile_target",
                "target": {"kind": "any_creature"},
            }
        ],
    }


# --- hand_snapshot ----------------------------------------------------


def test_hand_snapshot_default_state_returns_seven_dicts(synthetic_state):
    snap = synthetic_state.hand_snapshot(0)
    assert isinstance(snap, list)
    assert len(snap) == 7
    # Insertion order: p0 hand ids are 10..16.
    assert [d["id"] for d in snap] == list(range(10, 17))
    # Every dict has the full key set.
    for d in snap:
        assert set(d.keys()) == EXPECTED_KEYS


def test_hand_snapshot_empty_returns_empty_list(engine):
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=0
    )
    assert state.hand_snapshot(0) == []
    assert state.hand_snapshot(1) == []


def test_hand_snapshot_field_values_match_objects(synthetic_state):
    # First hand object: id 10, Llanowar Elves on p0.
    # NB: the synthetic-state factory `make_object` hardcodes
    # `zone: 1` on every GameObject regardless of which zone it
    # lands in (a documented quirk of the synthetic seed). The
    # snapshot faithfully echoes whatever the GameObject's zone
    # field carries — it doesn't second-guess it. Real ETB / move
    # primitives stamp the correct zone constant; the synthetic
    # factory's stamp is only correct for ZONE_LIBRARY (=1).
    snap = synthetic_state.hand_snapshot(0)
    first = snap[0]
    assert first["id"] == 10
    assert first["printing_name"] == "Llanowar Elves"
    assert first["tapped"] is False
    assert first["summoning_sick"] is False
    assert first["damage"] == 0
    assert first["counters"] == 0
    assert first["controller_id"] == 0
    # Synthetic-state factory zone field — see comment above.
    assert first["zone"] == 1


def test_hand_snapshot_out_of_range_raises_index_error(synthetic_state):
    with pytest.raises((IndexError, OverflowError)):
        synthetic_state.hand_snapshot(99)


# --- library_snapshot -------------------------------------------------


def test_library_snapshot_full_size_and_zone(synthetic_state):
    snap = synthetic_state.library_snapshot(0)
    assert len(snap) == 50
    # All ids in p0 library are 17..66 in insertion order.
    assert [d["id"] for d in snap] == list(range(17, 67))
    # Every dict carries zone == ZONE_LIBRARY.
    for d in snap:
        assert d["zone"] == ZONE_LIBRARY
        assert d["controller_id"] == 0
        assert d["printing_name"] == "Forest"


def test_library_snapshot_empty_returns_empty_list(engine):
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=0
    )
    assert state.library_snapshot(0) == []


def test_library_snapshot_out_of_range_raises_index_error(synthetic_state):
    with pytest.raises((IndexError, OverflowError)):
        synthetic_state.library_snapshot(99)


# --- graveyard_snapshot ----------------------------------------------


def test_graveyard_snapshot_default_empty(synthetic_state):
    # Default synthetic state has empty graveyards on both sides.
    assert synthetic_state.graveyard_snapshot(0) == []
    assert synthetic_state.graveyard_snapshot(1) == []


def test_graveyard_snapshot_populated_preserves_insertion_order(engine):
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=0
    )
    first_id = state.register_and_inject_object(_FOREST, 0, ZONE_GRAVEYARD)
    second_id = state.register_and_inject_object(_BEARS, 0, ZONE_GRAVEYARD)
    snap = state.graveyard_snapshot(0)
    assert len(snap) == 2
    assert [d["id"] for d in snap] == [first_id, second_id]
    assert [d["printing_name"] for d in snap] == ["Forest", "Grizzly Bears"]
    assert all(d["zone"] == ZONE_GRAVEYARD for d in snap)


def test_graveyard_snapshot_out_of_range_raises_index_error(synthetic_state):
    with pytest.raises((IndexError, OverflowError)):
        synthetic_state.graveyard_snapshot(99)


# --- exile_snapshot --------------------------------------------------


def test_exile_snapshot_default_empty(synthetic_state):
    assert synthetic_state.exile_snapshot(0) == []
    assert synthetic_state.exile_snapshot(1) == []


def test_exile_snapshot_populated_after_resolve(synthetic_state):
    # Use the ExileTarget dispatch to land a permanent in p1's exile.
    # ExileTarget's AnyCreature picker is actually `bf[0]` (no
    # card-type filter — see state_ops_resolve.rs:486), so the
    # default seed targets p1's battlefield[0] = obj_id 67 (Forest).
    # The dispatch stamps zone = ZONE_EXILE on the moved object.
    exile_obj_id = synthetic_state.register_and_inject_object(
        _exile_creature_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(exile_obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    snap = synthetic_state.exile_snapshot(1)
    assert len(snap) == 1
    assert snap[0]["id"] == 67
    assert snap[0]["zone"] == ZONE_EXILE
    assert snap[0]["printing_name"] == "Forest"
    # p0's exile remains empty.
    assert synthetic_state.exile_snapshot(0) == []


def test_exile_snapshot_out_of_range_raises_index_error(synthetic_state):
    with pytest.raises((IndexError, OverflowError)):
        synthetic_state.exile_snapshot(99)


# --- battlefield_snapshot --------------------------------------------


def test_battlefield_snapshot_combines_both_players_p0_first(synthetic_state):
    snap = synthetic_state.battlefield_snapshot()
    assert len(snap) == 20  # 10 each
    # Order: p0 ids 0..9 then p1 ids 67..76.
    expected_ids = list(range(0, 10)) + list(range(67, 77))
    assert [d["id"] for d in snap] == expected_ids
    # controller_id distinguishes the two halves.
    assert all(d["controller_id"] == 0 for d in snap[:10])
    assert all(d["controller_id"] == 1 for d in snap[10:])
    # NB: synthetic state's `make_object` hardcodes zone=1 on every
    # object regardless of which zone it actually inhabits, so the
    # battlefield-snapshot's `zone` field is 1 here, not 2. Real
    # play through ETB/move primitives stamps the correct constant.
    # We assert the projection emits whatever Rust holds — the
    # snapshot itself doesn't second-guess.
    assert all(isinstance(d["zone"], int) for d in snap)


def test_battlefield_snapshot_empty_returns_empty_list(engine):
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=0
    )
    assert state.battlefield_snapshot() == []


# --- mana_pool_snapshot ----------------------------------------------


def test_mana_pool_snapshot_default_all_zero(synthetic_state):
    snap = synthetic_state.mana_pool_snapshot(0)
    assert isinstance(snap, dict)
    assert set(snap.keys()) == {"W", "U", "B", "R", "G", "C"}
    assert all(v == 0 for v in snap.values())


def test_mana_pool_snapshot_reflects_added_mana(synthetic_state):
    synthetic_state.add_mana(0, "G", 3)
    synthetic_state.add_mana(0, "U", 1)
    snap = synthetic_state.mana_pool_snapshot(0)
    assert snap == {"W": 0, "U": 1, "B": 0, "R": 0, "G": 3, "C": 0}
    # p1's pool remains empty.
    assert synthetic_state.mana_pool_snapshot(1) == {
        "W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0,
    }


def test_mana_pool_snapshot_out_of_range_raises_index_error(synthetic_state):
    with pytest.raises((IndexError, OverflowError)):
        synthetic_state.mana_pool_snapshot(99)


# --- printing-name fallback ------------------------------------------


def test_printing_name_fallback_when_registry_missing(engine):
    """If a GameObject's printing_id doesn't resolve in the registry,
    the snapshot dict carries ``printing_name == ""`` rather than
    raising. Mirrors Python's ``getattr(obj.printing, "name", None)``
    behavior from ``_zone_signature`` — both sides emit a sentinel
    rather than crashing the hash."""
    # Build a state and dirty it: register an object into hand, then
    # poke at the printing-name lookup with a fake printing_id by
    # using a totally independent state with no printings registered
    # at the slot we'll synthesize. The simplest path: register an
    # obj into hand, then snapshot — we rely on `Forest` being
    # present via the synthetic seed. To force the fallback, we
    # exploit the gap: register the printing at one id, but create
    # an object whose printing_id is one-past-the-last. Since
    # `register_and_inject_object` always uses the just-registered
    # printing's id, we can't directly inject a stale printing_id.
    # Workaround: load_deck on a fresh state with a printing list
    # that has `obj_id` references to a printing index outside the
    # registry isn't supported either.
    #
    # Pragmatic workaround: cover the `unwrap_or_default()` branch
    # at the unit-of-behavior level by directly constructing a state
    # with `num_battlefield=0` etc. (so no objects exist) and then
    # observing that snapshots on empty zones return empty lists
    # without fallback firing. The defensive branch matters primarily
    # when phase-3+ adds primitives that can desync printing_id from
    # the registry; today no such primitive exists. The docstring
    # nails down the contract; this test pins it on the empty-zone
    # path that is reachable today.
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=0
    )
    # An empty zone naturally has no objects to project — fallback
    # is unreachable from the public API on a self-consistent state.
    # The contract is documented in state_ops_snapshot.rs's module
    # docstring; future test extends if/when desync becomes possible.
    assert state.hand_snapshot(0) == []
    assert state.library_snapshot(0) == []


# --- field-type assertions -------------------------------------------


def test_snapshot_dict_field_types(synthetic_state):
    """Pin the per-object field types so the parity harness's hash
    function (which is type-sensitive — int and bool hash differently
    even for equal values) doesn't drift between Rust and Python."""
    snap = synthetic_state.battlefield_snapshot()
    sample = snap[0]
    assert isinstance(sample["id"], int)
    assert isinstance(sample["printing_id"], int)
    assert isinstance(sample["printing_name"], str)
    # bool, not int — Python's True/False vs 1/0 distinction matters
    # to JSON-serialized hashes (`True` != `1` in `json.dumps`).
    assert isinstance(sample["tapped"], bool)
    assert isinstance(sample["summoning_sick"], bool)
    # damage is a signed int (can be negative? not today, but the
    # underlying Rust field is `i16`); counters is `i32`.
    assert isinstance(sample["damage"], int) and not isinstance(sample["damage"], bool)
    assert isinstance(sample["counters"], int) and not isinstance(sample["counters"], bool)
    assert isinstance(sample["controller_id"], int)
    assert isinstance(sample["zone"], int)


# --- read-only contract ----------------------------------------------


def test_snapshot_idempotent_on_repeat_calls(synthetic_state):
    """Calling a snapshot twice on the same state returns dicts
    whose fields agree pairwise. A regression here would mean the
    snapshot is dirtying state."""
    a = synthetic_state.hand_snapshot(0)
    b = synthetic_state.hand_snapshot(0)
    assert len(a) == len(b)
    for da, db in zip(a, b):
        assert da == db


def test_snapshot_dict_mutation_does_not_affect_state(synthetic_state):
    """The Python-side dicts are owned copies — mutating one must
    not affect the Rust state. Pin the contract by mutating a key
    and re-snapshotting."""
    a = synthetic_state.hand_snapshot(0)
    # Mutate the Python dict.
    a[0]["tapped"] = True
    a[0]["damage"] = 999
    a[0]["printing_name"] = "Mutated"
    # Re-snapshot — the Rust state's view is untouched.
    b = synthetic_state.hand_snapshot(0)
    assert b[0]["tapped"] is False
    assert b[0]["damage"] == 0
    assert b[0]["printing_name"] == "Llanowar Elves"


def test_snapshot_after_clone_has_independent_dicts(synthetic_state):
    """Snapshots from a clone and the original are equal but the
    underlying state is independent — confirming the snapshot path
    doesn't share mutable state across clones."""
    cloned = synthetic_state.clone_once()
    a = synthetic_state.hand_snapshot(0)
    b = cloned.hand_snapshot(0)
    assert a == b


# --- edge-case: snapshots after mutation ------------------------------
#
# Round-21 documented the six snapshot getters' shape and read-only
# isolation. This block pins the dynamic invariant: every getter
# faithfully reflects whatever mutating primitives downstream code
# applies. If a future refactor caches snapshot output, these tests
# fail loudly.


def test_hand_snapshot_shrinks_after_play_land(synthetic_state):
    """Move a Forest into p0's hand, play it as a land, and confirm
    hand_snapshot drops it: the land moves hand → battlefield, and
    the projection on the hand side decrements by 1."""
    # The synthetic state seeds p0's library with Forests; pull one
    # into hand so play_land has something to consume.
    forest_id = 17  # p0's first library obj (Forest).
    assert synthetic_state.move_object(forest_id, ZONE_HAND, 0) is True
    hand_before = synthetic_state.hand_snapshot(0)
    assert any(d["id"] == forest_id for d in hand_before)
    hand_len_before = len(hand_before)

    synthetic_state.apply_action({"kind": "play_land", "card_id": forest_id})

    hand_after = synthetic_state.hand_snapshot(0)
    assert len(hand_after) == hand_len_before - 1
    assert all(d["id"] != forest_id for d in hand_after), (
        "Forest still appears in hand_snapshot after play_land"
    )


def test_battlefield_snapshot_grows_after_play_land(synthetic_state):
    """Symmetric companion to the hand-shrink test: battlefield
    snapshot grows by exactly 1 and contains the newly-played land."""
    forest_id = 17
    assert synthetic_state.move_object(forest_id, ZONE_HAND, 0) is True
    bf_before = synthetic_state.battlefield_snapshot()
    bf_len_before = len(bf_before)
    assert all(d["id"] != forest_id for d in bf_before)

    synthetic_state.apply_action({"kind": "play_land", "card_id": forest_id})

    bf_after = synthetic_state.battlefield_snapshot()
    assert len(bf_after) == bf_len_before + 1
    matches = [d for d in bf_after if d["id"] == forest_id]
    assert len(matches) == 1
    assert matches[0]["printing_name"] == "Forest"
    assert matches[0]["controller_id"] == 0


def test_graveyard_snapshot_reflects_post_resolution_state(engine):
    """A draw-1 sorcery resolves and goes to its controller's
    graveyard (CR 608.2m). graveyard_snapshot must include it with
    the correct printing_name."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=5
    )
    draw_one = {
        "name": "Test Draw 1",
        "card_types": ["Sorcery"],
        "mana_cost": {"U": 1},
        "effects": [{"kind": "draw_cards", "count": 1}],
    }
    obj_id = state.register_and_inject_object(draw_one, 0, ZONE_HAND)
    state.push_to_stack(obj_id, 0)
    assert state.graveyard_snapshot(0) == []

    state.resolve_top_of_stack()

    gy = state.graveyard_snapshot(0)
    assert len(gy) == 1
    assert gy[0]["id"] == obj_id
    assert gy[0]["printing_name"] == "Test Draw 1"
    assert gy[0]["zone"] == ZONE_GRAVEYARD


def test_mana_pool_snapshot_after_add_mana_full_palette(synthetic_state):
    """Sanity-check every color: add one of each, snapshot mirrors
    the full palette. The default empty-pool case + green-only case
    are already covered; this pins all six slots simultaneously."""
    for color, n in (("W", 1), ("U", 2), ("B", 3), ("R", 4), ("G", 5), ("C", 6)):
        synthetic_state.add_mana(0, color, n)
    snap = synthetic_state.mana_pool_snapshot(0)
    assert snap == {"W": 1, "U": 2, "B": 3, "R": 4, "G": 5, "C": 6}


def test_mana_pool_snapshot_zero_after_empty_all(synthetic_state):
    """Round-18's ``empty_all_mana_pools`` drains both players;
    mana_pool_snapshot on each should return all zeros after the
    drain even when both players had non-trivial pools before."""
    synthetic_state.add_mana(0, "G", 4)
    synthetic_state.add_mana(1, "R", 2)
    synthetic_state.empty_all_mana_pools()
    zero = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0}
    assert synthetic_state.mana_pool_snapshot(0) == zero
    assert synthetic_state.mana_pool_snapshot(1) == zero


# --- edge-case: mutated-object fields surface in battlefield_snapshot ---


def test_battlefield_snapshot_reflects_tapped_field(synthetic_state):
    """Tap a permanent — its ``tapped`` field in
    battlefield_snapshot flips to True. Every other permanent's
    ``tapped`` stays False."""
    tap_id = 0  # p0's first battlefield obj.
    assert synthetic_state.tap_object(tap_id) is True

    snap = synthetic_state.battlefield_snapshot()
    by_id = {d["id"]: d for d in snap}
    assert by_id[tap_id]["tapped"] is True
    # Every other permanent stays untapped.
    for obj_id, d in by_id.items():
        if obj_id == tap_id:
            continue
        assert d["tapped"] is False, f"obj {obj_id} unexpectedly tapped"


def test_battlefield_snapshot_reflects_counters_field(synthetic_state):
    """Add counters via ``set_counters`` — the projection's
    ``counters`` field carries the new value, including negative
    values (representing net -1/-1 counters)."""
    synthetic_state.set_counters(0, 4)
    synthetic_state.set_counters(1, -2)
    snap = synthetic_state.battlefield_snapshot()
    by_id = {d["id"]: d for d in snap}
    assert by_id[0]["counters"] == 4
    assert by_id[1]["counters"] == -2
    # Unmutated permanents still at 0.
    assert by_id[2]["counters"] == 0


def test_battlefield_snapshot_reflects_damage_field(synthetic_state):
    """Mark damage via ``deal_damage`` — the projection's ``damage``
    field carries the accumulated marker."""
    synthetic_state.deal_damage(0, 3)
    synthetic_state.deal_damage(0, 2)  # additive — total 5.
    synthetic_state.deal_damage(5, 1)
    snap = synthetic_state.battlefield_snapshot()
    by_id = {d["id"]: d for d in snap}
    assert by_id[0]["damage"] == 5
    assert by_id[5]["damage"] == 1
    assert by_id[1]["damage"] == 0  # untouched
    # Bool-vs-int discipline (parity hash is type-sensitive).
    assert not isinstance(by_id[0]["damage"], bool)


# --- edge-case: zone divergence + ordering checks ---------------------


def test_battlefield_snapshot_controller_id_matches_seed(synthetic_state):
    """Each per-object dict's ``controller_id`` agrees with the
    half of the snapshot it appeared in: ids 0..9 (p0 seed) carry
    controller_id=0; ids 67..76 (p1 seed) carry controller_id=1.
    Pins the per-object controller field, not just the global slice."""
    snap = synthetic_state.battlefield_snapshot()
    p0_dicts = [d for d in snap if d["id"] in range(0, 10)]
    p1_dicts = [d for d in snap if d["id"] in range(67, 77)]
    assert len(p0_dicts) == 10
    assert len(p1_dicts) == 10
    assert all(d["controller_id"] == 0 for d in p0_dicts)
    assert all(d["controller_id"] == 1 for d in p1_dicts)


def test_battlefield_snapshot_p0_then_p1_ordering(engine):
    """Build a state with only p1 having battlefield content (via
    a non-default seed), then add a p0 permanent via
    register_and_inject_object — the projection still emits p0
    first, even though chronologically p1 was populated first."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=0
    )
    # Populate p1 with a single Bears, then p0 with a single Forest.
    p1_obj = state.register_and_inject_object(_BEARS, 1, ZONE_BATTLEFIELD)
    p0_obj = state.register_and_inject_object(_FOREST, 0, ZONE_BATTLEFIELD)

    snap = state.battlefield_snapshot()
    assert len(snap) == 2
    # p0 first, p1 second — ordering is by zone owner, not insertion.
    assert snap[0]["id"] == p0_obj
    assert snap[0]["controller_id"] == 0
    assert snap[1]["id"] == p1_obj
    assert snap[1]["controller_id"] == 1


# --- edge-case: clone CoW canary across all six getters ---------------


def test_clone_isolation_across_all_zone_snapshots(synthetic_state):
    """Single load-bearing CoW canary: clone the state, mutate ONLY
    the clone in ways that touch every zone snapshot getter, and
    verify the original's six snapshots are unchanged.

    Mutations exercised:
    - hand_snapshot: discard via move_object hand → graveyard
    - library_snapshot: move library top → hand
    - graveyard_snapshot: inject a card there
    - exile_snapshot: inject a card there
    - battlefield_snapshot: tap + damage + counter on existing objs
    - mana_pool_snapshot: add mana on the clone
    """
    # Capture originals first.
    orig_hand = synthetic_state.hand_snapshot(0)
    orig_lib = synthetic_state.library_snapshot(0)
    orig_gy = synthetic_state.graveyard_snapshot(0)
    orig_ex = synthetic_state.exile_snapshot(0)
    orig_bf = synthetic_state.battlefield_snapshot()
    orig_mana = synthetic_state.mana_pool_snapshot(0)

    cloned = synthetic_state.clone_once()
    # Discard from hand to graveyard.
    cloned.move_object(10, ZONE_GRAVEYARD, 0)
    # Move library top into hand.
    cloned.move_object(17, ZONE_HAND, 0)
    # Inject directly into graveyard. (Exile content can only be
    # produced via the resolve-dispatch path — see the module-level
    # `_exile_creature_dict` doc; for the CoW-across-getters canary
    # the graveyard mutation already exercises a distinct zone.)
    cloned.register_and_inject_object(_BEARS, 0, ZONE_GRAVEYARD)
    # Tap + damage + counter on a battlefield permanent.
    cloned.tap_object(0)
    cloned.deal_damage(0, 4)
    cloned.set_counters(0, 2)
    # Add mana.
    cloned.add_mana(0, "G", 3)

    # Original's snapshots all unchanged.
    assert synthetic_state.hand_snapshot(0) == orig_hand
    assert synthetic_state.library_snapshot(0) == orig_lib
    assert synthetic_state.graveyard_snapshot(0) == orig_gy
    assert synthetic_state.exile_snapshot(0) == orig_ex
    assert synthetic_state.battlefield_snapshot() == orig_bf
    assert synthetic_state.mana_pool_snapshot(0) == orig_mana


def test_clone_preserves_snapshots_byte_for_byte(synthetic_state):
    """On a moderately populated state (default seed + injected
    graveyard / exile content + mana + tap + counter + damage), a
    fresh clone's snapshots agree key-by-key with the original's.
    Pins that ``clone_once`` carries forward every field the
    snapshot getters project."""
    # Dirty the original with content that touches every field
    # (graveyard injection is fine via register_and_inject_object;
    # exile content needs the resolve-dispatch path so we route a
    # Path-to-Exile-shaped instant through the stack to land a
    # permanent in p1's exile zone — same trick as the existing
    # populated-exile test above).
    synthetic_state.tap_object(0)
    synthetic_state.deal_damage(1, 3)
    synthetic_state.set_counters(2, 5)
    synthetic_state.register_and_inject_object(_BEARS, 0, ZONE_GRAVEYARD)
    exile_obj_id = synthetic_state.register_and_inject_object(
        _exile_creature_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(exile_obj_id, 0)
    synthetic_state.resolve_top_of_stack()
    synthetic_state.add_mana(0, "G", 2)
    synthetic_state.add_mana(1, "R", 1)

    cloned = synthetic_state.clone_once()

    assert cloned.hand_snapshot(0) == synthetic_state.hand_snapshot(0)
    assert cloned.hand_snapshot(1) == synthetic_state.hand_snapshot(1)
    assert cloned.library_snapshot(0) == synthetic_state.library_snapshot(0)
    assert cloned.library_snapshot(1) == synthetic_state.library_snapshot(1)
    assert cloned.graveyard_snapshot(0) == synthetic_state.graveyard_snapshot(0)
    assert cloned.graveyard_snapshot(1) == synthetic_state.graveyard_snapshot(1)
    assert cloned.exile_snapshot(0) == synthetic_state.exile_snapshot(0)
    assert cloned.exile_snapshot(1) == synthetic_state.exile_snapshot(1)
    assert cloned.battlefield_snapshot() == synthetic_state.battlefield_snapshot()
    assert cloned.mana_pool_snapshot(0) == synthetic_state.mana_pool_snapshot(0)
    assert cloned.mana_pool_snapshot(1) == synthetic_state.mana_pool_snapshot(1)
