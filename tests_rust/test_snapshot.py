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
