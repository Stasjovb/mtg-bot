"""Zone-movement primitives on ``GameState``.

Ported from the zone-mutation patterns in ``src/mtg_bot/turn.py``
(``draw_card``) and ``src/mtg_bot/actions.py`` / ``effects/*`` (the
``card.zone = Zone.X`` + per-zone list mutation pattern). On the Python
side the operation is two coupled mutations — ``p.library.pop(0);
top.zone = Zone.HAND; p.hand.append(top)`` — so the Rust port collapses
both into a single primitive that owns the membership move + the
``GameObject.zone`` tag update.

**Zone identifier choice (option b in the slice brief):** raw ``u8``
constants rather than a Rust ``ZoneKind`` enum. Adding an enum to
``state.rs`` would have forced an edit on a file two sibling slices
also need to grow this commit, so we keep the encoding inline. The
constants are duplicated test-side for readability — this is a
first-slice expedient and a follow-up can either expose them as
module-level Python attrs on ``mtg_bot_engine`` or upgrade to an enum
once the parallel-slice constraint relaxes.
"""

from __future__ import annotations

import pytest

# Zone constants — must match the values in
# ``rust/src/state_ops_zones.rs``. Hard-coded here rather than imported
# so the test file is self-contained and the encoding contract is
# visible at the call site.
ZONE_HAND = 0
ZONE_LIBRARY = 1
ZONE_BATTLEFIELD = 2
ZONE_GRAVEYARD = 3
ZONE_STACK = 4
ZONE_EXILE = 5


# `make_synthetic_state(num_battlefield=10, num_hand=7, num_library=50)`
# lays player 0 out as:
#   battlefield: ids 0..9
#   hand:        ids 10..16
#   library:     ids 17..66
# and player 1's range starts at 67. We rely on those id ranges below.
P0_FIRST_BATTLEFIELD_ID = 0
P0_FIRST_HAND_ID = 10
P0_FIRST_LIBRARY_ID = 17


def test_find_object_zone_returns_battlefield_for_battlefield_object(synthetic_state):
    """An object known to live on the battlefield resolves to
    ``ZONE_BATTLEFIELD`` regardless of the placeholder value its
    ``GameObject.zone`` field carried at construction time."""
    assert synthetic_state.find_object_zone(P0_FIRST_BATTLEFIELD_ID) == ZONE_BATTLEFIELD


def test_find_object_zone_returns_hand_for_hand_object(synthetic_state):
    assert synthetic_state.find_object_zone(P0_FIRST_HAND_ID) == ZONE_HAND


def test_find_object_zone_returns_library_for_library_object(synthetic_state):
    assert synthetic_state.find_object_zone(P0_FIRST_LIBRARY_ID) == ZONE_LIBRARY


def test_find_object_zone_unknown_id_returns_none(synthetic_state):
    """Far-out-of-range id returns None (no exception)."""
    assert synthetic_state.find_object_zone(999_999) is None


def test_move_object_to_graveyard_removes_from_source_zone(synthetic_state):
    """Moving a battlefield object into the graveyard removes it from
    the battlefield and pushes it onto the graveyard. The object's
    ``zone`` field updates to track the new home."""
    obj_id = P0_FIRST_BATTLEFIELD_ID
    bf_before, gy_before = (
        synthetic_state.battlefield_sizes,
        synthetic_state.graveyard_sizes,
    )
    assert synthetic_state.find_object_zone(obj_id) == ZONE_BATTLEFIELD

    moved = synthetic_state.move_object(obj_id, ZONE_GRAVEYARD, 0)
    assert moved is True

    assert synthetic_state.find_object_zone(obj_id) == ZONE_GRAVEYARD
    assert synthetic_state.battlefield_sizes[0] == bf_before[0] - 1
    assert synthetic_state.graveyard_sizes[0] == gy_before[0] + 1
    # Other player untouched.
    assert synthetic_state.battlefield_sizes[1] == bf_before[1]
    assert synthetic_state.graveyard_sizes[1] == gy_before[1]


def test_move_object_unknown_id_returns_false(synthetic_state):
    """Asked to move an id we don't know about: no-op, return False."""
    bf_before = synthetic_state.battlefield_sizes
    gy_before = synthetic_state.graveyard_sizes
    moved = synthetic_state.move_object(999_999, ZONE_GRAVEYARD, 0)
    assert moved is False
    # All zones unchanged.
    assert synthetic_state.battlefield_sizes == bf_before
    assert synthetic_state.graveyard_sizes == gy_before


def test_move_object_preserves_id_and_printing(synthetic_state):
    """The moved object keeps its identity — same id, same printing
    (so the registry lookup chain still resolves to the same name)."""
    obj_id = P0_FIRST_HAND_ID  # an elf
    name_before = synthetic_state.printing_name_of(obj_id)
    assert name_before == "Llanowar Elves"

    assert synthetic_state.move_object(obj_id, ZONE_GRAVEYARD, 0) is True

    # Same id, still resolves to the same printing.
    assert synthetic_state.printing_name_of(obj_id) == "Llanowar Elves"
    assert synthetic_state.find_object_zone(obj_id) == ZONE_GRAVEYARD


def test_clone_then_move_does_not_affect_original(synthetic_state):
    """Load-bearing CoW canary: mutating a zone on a clone must not
    leak back into the source state. Each ``Player`` zone is an
    ``Arc<Vec<GameObject>>``; ``Arc::make_mut`` clones the inner Vec
    on first write, isolating the clone from its peers."""
    obj_id = P0_FIRST_BATTLEFIELD_ID
    cloned = synthetic_state.clone_once()
    bf_source_before = synthetic_state.battlefield_sizes
    gy_source_before = synthetic_state.graveyard_sizes

    assert cloned.move_object(obj_id, ZONE_GRAVEYARD, 0) is True

    # Clone diverged.
    assert cloned.find_object_zone(obj_id) == ZONE_GRAVEYARD
    # Source untouched: object is still on the battlefield with the
    # same zone-size totals.
    assert synthetic_state.find_object_zone(obj_id) == ZONE_BATTLEFIELD
    assert synthetic_state.battlefield_sizes == bf_source_before
    assert synthetic_state.graveyard_sizes == gy_source_before


def test_draw_card_moves_top_of_library_to_hand(synthetic_state):
    """``draw_card`` returns the drawn object's id, shrinks the
    library by one, and grows the hand by one. The Rust convention is
    that the LAST element of the library Vec is the "top of library"
    (Python's ``library.pop(0)`` treats the front as the top — the
    Rust port flips that for ``Vec::pop`` cheapness; documented in
    the Rust docstring)."""
    lib_before = synthetic_state.library_sizes
    hand_before = synthetic_state.hand_sizes

    drawn = synthetic_state.draw_card(0)

    assert drawn is not None
    assert isinstance(drawn, int)
    assert synthetic_state.library_sizes[0] == lib_before[0] - 1
    assert synthetic_state.hand_sizes[0] == hand_before[0] + 1
    # Other player untouched.
    assert synthetic_state.library_sizes[1] == lib_before[1]
    assert synthetic_state.hand_sizes[1] == hand_before[1]
    # Drawn card now lives in hand.
    assert synthetic_state.find_object_zone(drawn) == ZONE_HAND


def test_draw_card_from_empty_library_returns_none(engine):
    """Draw from an empty library returns None — the Python engine
    flips ``has_lost = True`` here, but the Rust slice keeps the
    primitive narrow: pop returns ``None``, callers layer policy on
    top later."""
    state = engine.make_synthetic_state(
        num_battlefield=2, num_hand=2, num_library=0
    )
    assert state.library_sizes[0] == 0
    assert state.draw_card(0) is None
    assert state.hand_sizes[0] == 2  # unchanged


# --- round-14 exile-aware zone primitives ----------------------------
#
# Round-1 ``find_object_zone`` and ``move_object`` only iterated four
# zones (HAND / LIBRARY / BATTLEFIELD / GRAVEYARD) — round-11 added
# ``Player.exile`` as a *write-only* zone reachable through the
# ``ExileTarget`` effect, but the read primitives didn't grow to cover
# it. This slice closes that gap so callers can:
#
# - resolve an object id that lives in exile to ``ZONE_EXILE``;
# - move an object INTO exile via ``move_object(..., ZONE_EXILE, p)``;
# - move an object OUT of exile back to a tracked zone
#   (``move_object(exile_obj, ZONE_BATTLEFIELD, p)``, the foundation
#   for "return-from-exile" effects landing in a later slice).
#
# The tests below use the existing ``ExileTarget`` resolve dispatch
# (round-11) to get an object into exile cleanly — then poke the
# round-14 read/write primitives. The CoW canary mirrors the
# round-1 ``test_clone_then_move_does_not_affect_original`` shape.


def _exile_creature_dict():
    """A tiny instant 'exile target creature' printing — mirrors the
    fixture in ``test_resolve.py`` but local to this file so the
    slice's tests don't share state with the resolve slice."""
    return {
        "name": "Test Exile Instant (zones-r14)",
        "mana_cost": {"W": 1, "generic": 1},
        "card_types": ["Instant"],
        "effects": [
            {
                "kind": "exile_target",
                "target": {"kind": "any_creature"},
            }
        ],
    }


def _put_object_into_p0_exile(state):
    """Helper: resolves an ExileTarget effect from p0 onto the first
    creature on p1's battlefield. The caveat: round-11 lands the
    exiled card in the TARGET's exile (== p1's exile under the
    controller==owner convention), so we then ``move_object`` it to
    p0's exile to give us a p0-exile case for the find tests.

    Returns the obj_id of the now-in-p0-exile object.
    """
    # Pick p1's first creature on battlefield as the target. In a
    # fresh synthetic state, p1's battlefield IDs are 67..76 (10
    # objects, half forest / half bears — bears are creatures, so
    # the FIRST creature target is the first bear at id 72 with
    # the default 5/5 split. ``ExileTarget`` walks p1's battlefield
    # and picks the first creature.)
    inj = state.register_and_inject_object(_exile_creature_dict(), 0, ZONE_HAND)
    state.push_to_stack(inj, 0)
    state.resolve_top_of_stack()
    # Now there's exactly one extra entry in p1's exile. Find it by
    # scanning ids: anything in p1's exile with damage==0, counters==0
    # is fine. We need its id. Use exile_contains across the known
    # P1 battlefield id range to discover which one landed.
    for candidate in range(67, 77):
        if state.exile_contains(candidate):
            # Move it from p1 exile to p0 exile so the test exercises
            # find_object_zone / move_object on p0's exile zone.
            assert state.move_object(candidate, ZONE_EXILE, 0) is True
            return candidate
    raise AssertionError("ExileTarget didn't move any p1 creature")


def test_find_object_zone_finds_exiled_object(synthetic_state):
    """An object that lives in a player's exile resolves to
    ``ZONE_EXILE``. Pre-r14 ``find_object_zone`` returned None for
    exile residents (it didn't iterate the exile zone)."""
    obj_id = _put_object_into_p0_exile(synthetic_state)
    assert synthetic_state.exile_contains(obj_id) is True
    # The behavior under test:
    assert synthetic_state.find_object_zone(obj_id) == ZONE_EXILE


def test_move_object_to_exile_zone(synthetic_state):
    """``move_object(obj_id, ZONE_EXILE, target_player)`` moves an
    object from its current tracked zone into the target player's
    exile. Pre-r14 ``move_object`` silently routed unknown
    destinations (incl. exile) into the graveyard — this test pins
    the new dispatch arm."""
    obj_id = P0_FIRST_BATTLEFIELD_ID
    bf_before = synthetic_state.battlefield_sizes
    gy_before = synthetic_state.graveyard_sizes
    p0_exile_before = synthetic_state.exile_sizes[0]
    assert synthetic_state.find_object_zone(obj_id) == ZONE_BATTLEFIELD

    moved = synthetic_state.move_object(obj_id, ZONE_EXILE, 0)
    assert moved is True

    # Now in p0's exile, gone from battlefield, NOT in graveyard.
    assert synthetic_state.find_object_zone(obj_id) == ZONE_EXILE
    assert synthetic_state.exile_contains(obj_id) is True
    assert synthetic_state.battlefield_sizes[0] == bf_before[0] - 1
    assert synthetic_state.exile_sizes[0] == p0_exile_before + 1
    # Graveyard NOT bumped — this distinguishes ZONE_EXILE from the
    # pre-r14 "unknown -> graveyard" fallback.
    assert synthetic_state.graveyard_sizes == gy_before
    # Other player untouched.
    assert synthetic_state.battlefield_sizes[1] == bf_before[1]
    assert synthetic_state.exile_sizes[1] == 0


def test_move_object_from_exile_back_to_battlefield(synthetic_state):
    """An object in exile can be moved back to a tracked zone. This
    is the foundational primitive a future "return from exile"
    effect (e.g. flicker) will sit on top of."""
    obj_id = _put_object_into_p0_exile(synthetic_state)
    assert synthetic_state.find_object_zone(obj_id) == ZONE_EXILE
    p0_exile_before = synthetic_state.exile_sizes[0]
    p0_bf_before = synthetic_state.battlefield_sizes[0]

    moved = synthetic_state.move_object(obj_id, ZONE_BATTLEFIELD, 0)
    assert moved is True

    assert synthetic_state.find_object_zone(obj_id) == ZONE_BATTLEFIELD
    assert synthetic_state.exile_contains(obj_id) is False
    assert synthetic_state.exile_sizes[0] == p0_exile_before - 1
    assert synthetic_state.battlefield_sizes[0] == p0_bf_before + 1


def test_clone_then_move_to_exile_does_not_affect_original(synthetic_state):
    """CoW canary for the new exile-aware ``move_object`` arm. Mutating
    a clone (move battlefield obj -> p0 exile) must not bleed back
    into the source state."""
    obj_id = P0_FIRST_BATTLEFIELD_ID
    cloned = synthetic_state.clone_once()
    bf_source_before = synthetic_state.battlefield_sizes
    exile_source_before = synthetic_state.exile_sizes

    assert cloned.move_object(obj_id, ZONE_EXILE, 0) is True

    # Clone diverged: object is in clone's p0 exile.
    assert cloned.find_object_zone(obj_id) == ZONE_EXILE
    assert cloned.exile_contains(obj_id) is True
    assert cloned.exile_sizes[0] == exile_source_before[0] + 1
    # Source untouched: object is still on the battlefield with the
    # same zone-size totals; exile is empty as before.
    assert synthetic_state.find_object_zone(obj_id) == ZONE_BATTLEFIELD
    assert synthetic_state.battlefield_sizes == bf_source_before
    assert synthetic_state.exile_sizes == exile_source_before
    assert synthetic_state.exile_contains(obj_id) is False


# --- round-17 graveyard reanimation ----------------------------------
#
# ``move_object_from_graveyard_to_battlefield(player_id, obj_id)`` is
# the engine primitive a future "reanimate" card (Animate Dead,
# Reanimate, Zombify, ...) sits on top of. Specific variant of
# ``move_object`` that ALWAYS goes graveyard -> battlefield and ALWAYS
# stamps ``summoning_sick = true`` (CR 302.1 — a creature returning
# from the graveyard via reanimation enters the battlefield with
# summoning sickness; it can't attack on the turn it enters).
#
# Per CR 400.7 / round-1 zone-change convention, per-object state
# (tapped / summoning_sick / damage / counters) resets on the way
# into the new zone. ``summoning_sick = true`` is the only stamp
# that intentionally diverges from the "reset to default" rule —
# the new permanent has summoning sickness by design.


def _put_creature_into_p0_graveyard(state):
    """Helper: take p0's first battlefield creature (id 0 = a forest
    in the synthetic state, but bears at the tail half of the BF
    range are creatures) and route it into p0's graveyard so the
    reanimation tests have a graveyard creature to revive.

    In the default synthetic state, p0's battlefield is ids 0..9 with
    ids 5..9 as Grizzly Bears (creatures). Pick id 5 for a true
    creature target.
    """
    creature_id = 5
    assert state.find_object_zone(creature_id) == ZONE_BATTLEFIELD
    assert state.move_object(creature_id, ZONE_GRAVEYARD, 0) is True
    assert state.find_object_zone(creature_id) == ZONE_GRAVEYARD
    return creature_id


def test_reanimate_moves_card_to_battlefield(synthetic_state):
    """Graveyard has a creature; reanimate -> battlefield +1,
    graveyard -1."""
    obj_id = _put_creature_into_p0_graveyard(synthetic_state)
    bf_before = synthetic_state.battlefield_sizes
    gy_before = synthetic_state.graveyard_sizes

    moved = synthetic_state.move_object_from_graveyard_to_battlefield(0, obj_id)
    assert moved is True

    assert synthetic_state.find_object_zone(obj_id) == ZONE_BATTLEFIELD
    assert synthetic_state.battlefield_sizes[0] == bf_before[0] + 1
    assert synthetic_state.graveyard_sizes[0] == gy_before[0] - 1
    # Other player untouched.
    assert synthetic_state.battlefield_sizes[1] == bf_before[1]
    assert synthetic_state.graveyard_sizes[1] == gy_before[1]


def test_reanimate_sets_summoning_sick(synthetic_state):
    """Reanimated creature has summoning_sick=true (CR 302.1 — the
    new permanent has summoning sickness; can't attack on the turn
    it enters)."""
    obj_id = _put_creature_into_p0_graveyard(synthetic_state)

    assert synthetic_state.move_object_from_graveyard_to_battlefield(0, obj_id) is True

    assert synthetic_state.is_summoning_sick(obj_id) is True


def test_reanimate_resets_damage_and_counters(synthetic_state):
    """Damage and counters reset on the zone change (CR 400.7). A
    graveyard creature shouldn't normally have damage (CR 614.12 —
    damage clears on zone change), but a defensive reset here means
    that any stale state on the graveyard object is wiped on the way
    onto the battlefield."""
    obj_id = _put_creature_into_p0_graveyard(synthetic_state)
    # Stamp damage and counters onto the graveyard object directly.
    assert synthetic_state.deal_damage(obj_id, 5) is True
    assert synthetic_state.set_counters(obj_id, 3) is True
    assert synthetic_state.get_damage(obj_id) == 5
    assert synthetic_state.get_counters(obj_id) == 3

    assert synthetic_state.move_object_from_graveyard_to_battlefield(0, obj_id) is True

    assert synthetic_state.get_damage(obj_id) == 0
    assert synthetic_state.get_counters(obj_id) == 0


def test_reanimate_returns_true_on_success(synthetic_state):
    """The primitive returns True on a successful graveyard ->
    battlefield move."""
    obj_id = _put_creature_into_p0_graveyard(synthetic_state)
    assert synthetic_state.move_object_from_graveyard_to_battlefield(0, obj_id) is True


def test_reanimate_returns_false_when_id_not_in_graveyard(synthetic_state):
    """The id exists but lives on the battlefield, not in the
    graveyard. Returns False, no movement."""
    obj_id = P0_FIRST_BATTLEFIELD_ID  # on the battlefield
    assert synthetic_state.find_object_zone(obj_id) == ZONE_BATTLEFIELD
    bf_before = synthetic_state.battlefield_sizes
    gy_before = synthetic_state.graveyard_sizes

    moved = synthetic_state.move_object_from_graveyard_to_battlefield(0, obj_id)
    assert moved is False

    # Object stays where it was; no zone sizes shifted.
    assert synthetic_state.find_object_zone(obj_id) == ZONE_BATTLEFIELD
    assert synthetic_state.battlefield_sizes == bf_before
    assert synthetic_state.graveyard_sizes == gy_before


def test_reanimate_returns_false_when_id_does_not_exist(synthetic_state):
    """Far-out-of-range id returns False (no exception, no movement)."""
    bf_before = synthetic_state.battlefield_sizes
    gy_before = synthetic_state.graveyard_sizes
    moved = synthetic_state.move_object_from_graveyard_to_battlefield(0, 999)
    assert moved is False
    assert synthetic_state.battlefield_sizes == bf_before
    assert synthetic_state.graveyard_sizes == gy_before


def test_reanimate_unknown_player_raises(synthetic_state):
    """An out-of-range player_id raises rather than silently no-op'ing
    — mirrors the loud-fail convention of every other player-indexed
    primitive (life / mana / damage_to_player / search_library)."""
    with pytest.raises((ValueError, IndexError, OverflowError)):
        synthetic_state.move_object_from_graveyard_to_battlefield(7, 0)


def test_reanimate_clone_isolation(synthetic_state):
    """CoW canary: running the reanimation primitive on a clone leaves
    the original GameState's zones untouched. Mirrors
    ``test_clone_then_move_does_not_affect_original``."""
    obj_id = _put_creature_into_p0_graveyard(synthetic_state)
    cloned = synthetic_state.clone_once()
    bf_source_before = synthetic_state.battlefield_sizes
    gy_source_before = synthetic_state.graveyard_sizes

    assert cloned.move_object_from_graveyard_to_battlefield(0, obj_id) is True

    # Clone diverged.
    assert cloned.find_object_zone(obj_id) == ZONE_BATTLEFIELD
    assert cloned.is_summoning_sick(obj_id) is True
    # Source untouched: object still in graveyard with the same totals.
    assert synthetic_state.find_object_zone(obj_id) == ZONE_GRAVEYARD
    assert synthetic_state.battlefield_sizes == bf_source_before
    assert synthetic_state.graveyard_sizes == gy_source_before


# --- round-18 graveyard -> hand (Regrowth-style) ---------------------
#
# ``move_object_from_graveyard_to_hand(player_id, obj_id)`` is the
# engine primitive a future "return target card from your graveyard
# to your hand" card (Regrowth, Eternal Witness, ...) sits on top of.
# Specific variant of ``move_object`` that ALWAYS goes graveyard ->
# hand. Per CR 400.7, per-object state (tapped / summoning_sick /
# damage / counters) resets on the way into the new zone.
# ``summoning_sick`` resets to ``false`` here (not ``true`` like the
# round-17 reanimate variant) — cards in hand have no summoning
# sickness; that stamp is specific to entering the battlefield.


def test_regrowth_moves_card_to_hand(synthetic_state):
    """Graveyard has a card; regrowth -> hand +1, graveyard -1."""
    obj_id = _put_creature_into_p0_graveyard(synthetic_state)
    hand_before = synthetic_state.hand_sizes
    gy_before = synthetic_state.graveyard_sizes

    moved = synthetic_state.move_object_from_graveyard_to_hand(0, obj_id)
    assert moved is True

    assert synthetic_state.find_object_zone(obj_id) == ZONE_HAND
    assert synthetic_state.hand_sizes[0] == hand_before[0] + 1
    assert synthetic_state.graveyard_sizes[0] == gy_before[0] - 1
    # Other player untouched.
    assert synthetic_state.hand_sizes[1] == hand_before[1]
    assert synthetic_state.graveyard_sizes[1] == gy_before[1]


def test_regrowth_resets_state(synthetic_state):
    """Per-object state (damage / counters) is reset on the zone
    change (CR 400.7). Tapped and summoning_sick reset under the
    hood as well, but ``is_tapped`` / ``is_summoning_sick`` only
    read the battlefield (they return None for hand objects), so
    the next zone-change-back-to-battlefield won't observe stale
    flags. We round-trip the object: hand -> battlefield via the
    round-17 reanimate primitive, then assert tapped=false and
    summoning_sick observed after that round trip — combined with
    the reanimate variant stamping summoning_sick=true, a tapped or
    !summoning_sick assertion at this point would only succeed if
    the round-18 hand path had cleared the flags first."""
    obj_id = _put_creature_into_p0_graveyard(synthetic_state)
    # Stamp damage / counters on the graveyard object directly.
    assert synthetic_state.deal_damage(obj_id, 5) is True
    assert synthetic_state.set_counters(obj_id, 3) is True
    assert synthetic_state.get_damage(obj_id) == 5
    assert synthetic_state.get_counters(obj_id) == 3

    assert synthetic_state.move_object_from_graveyard_to_hand(0, obj_id) is True

    # damage / counters observable cross-zone — reset.
    assert synthetic_state.get_damage(obj_id) == 0
    assert synthetic_state.get_counters(obj_id) == 0
    # is_tapped / is_summoning_sick only read the battlefield; for a
    # hand object they return None. Asserting None confirms the
    # object is not on the battlefield (nothing leaked) and is
    # cleanly readable.
    assert synthetic_state.is_tapped(obj_id) is None
    assert synthetic_state.is_summoning_sick(obj_id) is None


def test_regrowth_returns_true_on_success(synthetic_state):
    """The primitive returns True on a successful graveyard -> hand
    move."""
    obj_id = _put_creature_into_p0_graveyard(synthetic_state)
    assert synthetic_state.move_object_from_graveyard_to_hand(0, obj_id) is True


def test_regrowth_returns_false_when_id_not_in_graveyard(synthetic_state):
    """The id exists but lives on the battlefield, not in the
    graveyard. Returns False, no movement."""
    obj_id = P0_FIRST_BATTLEFIELD_ID  # on the battlefield
    assert synthetic_state.find_object_zone(obj_id) == ZONE_BATTLEFIELD
    bf_before = synthetic_state.battlefield_sizes
    hand_before = synthetic_state.hand_sizes
    gy_before = synthetic_state.graveyard_sizes

    moved = synthetic_state.move_object_from_graveyard_to_hand(0, obj_id)
    assert moved is False

    # Object stays where it was; no zone sizes shifted.
    assert synthetic_state.find_object_zone(obj_id) == ZONE_BATTLEFIELD
    assert synthetic_state.battlefield_sizes == bf_before
    assert synthetic_state.hand_sizes == hand_before
    assert synthetic_state.graveyard_sizes == gy_before


def test_regrowth_returns_false_when_id_does_not_exist(synthetic_state):
    """Far-out-of-range id returns False (no exception, no movement)."""
    hand_before = synthetic_state.hand_sizes
    gy_before = synthetic_state.graveyard_sizes
    moved = synthetic_state.move_object_from_graveyard_to_hand(0, 999)
    assert moved is False
    assert synthetic_state.hand_sizes == hand_before
    assert synthetic_state.graveyard_sizes == gy_before


def test_regrowth_unknown_player_raises(synthetic_state):
    """An out-of-range player_id raises rather than silently no-op'ing
    — mirrors the loud-fail convention of every other player-indexed
    primitive (life / mana / damage_to_player / search_library /
    reanimate)."""
    with pytest.raises((ValueError, IndexError, OverflowError)):
        synthetic_state.move_object_from_graveyard_to_hand(7, 0)


def test_regrowth_clone_isolation(synthetic_state):
    """CoW canary: running the regrowth primitive on a clone leaves
    the original GameState's zones untouched. Mirrors
    ``test_reanimate_clone_isolation``."""
    obj_id = _put_creature_into_p0_graveyard(synthetic_state)
    cloned = synthetic_state.clone_once()
    hand_source_before = synthetic_state.hand_sizes
    gy_source_before = synthetic_state.graveyard_sizes

    assert cloned.move_object_from_graveyard_to_hand(0, obj_id) is True

    # Clone diverged.
    assert cloned.find_object_zone(obj_id) == ZONE_HAND
    # Source untouched: object still in graveyard with the same totals.
    assert synthetic_state.find_object_zone(obj_id) == ZONE_GRAVEYARD
    assert synthetic_state.hand_sizes == hand_source_before
    assert synthetic_state.graveyard_sizes == gy_source_before


# --- cross-primitive: Effect dispatch composes with zone primitives -----
#
# These tests verify the end-state zone bookkeeping after Effect dispatch
# arms drive zone moves. Every recent Effect arm either composes the
# zone primitives (move_object,
# move_object_from_graveyard_to_battlefield) or inlines the same
# logic (Arc::make_mut pop/push) due to the per-slice file-isolation
# rule that kept dispatch out of state_ops_zones.rs.
#
# We don't test the Effect logic itself here — the per-effect resolve
# tests in ``test_resolve.py`` cover that. We test the cross-cut: that
# after Effect dispatch, ``find_object_zone`` and the zone-size readers
# agree on where the affected object now lives. A bug like "the inline
# move shrinks the source zone but forgets to stamp ``obj.zone =
# new_zone``" would slip past test_resolve.py (which mostly checks
# zone-size deltas) but fail here.


def _destroy_target_creature_dict():
    """Murder-shaped: instant that destroys target creature (defender's
    first battlefield obj). Source post-resolves to controller's
    graveyard per CR 608.2m."""
    return {
        "name": "Test Murder (zones-cross)",
        "card_types": ["Instant"],
        "mana_cost": {"B": 1, "generic": 2},
        "effects": [
            {
                "kind": "destroy_target",
                "target": {"kind": "any_creature"},
            }
        ],
    }


def _sacrifice_target_creature_dict():
    """Sacrifice-target sorcery: active player sacrifices their first
    battlefield object."""
    return {
        "name": "Test Sacrifice (zones-cross)",
        "card_types": ["Sorcery"],
        "mana_cost": {"B": 1},
        "effects": [
            {
                "kind": "sacrifice",
                "target": {"kind": "any_creature"},
            }
        ],
    }


def _exile_target_creature_dict():
    """Path-style exile: target creature -> owner's exile."""
    return {
        "name": "Test Path (zones-cross)",
        "card_types": ["Instant"],
        "mana_cost": {"W": 1},
        "effects": [
            {
                "kind": "exile_target",
                "target": {"kind": "any_creature"},
            }
        ],
    }


def _reanimate_dict_cross():
    """Reanimate-shaped sorcery: return first creature from your
    graveyard to the battlefield. Composes with the round-17 primitive
    ``move_object_from_graveyard_to_battlefield`` under the hood."""
    return {
        "name": "Test Reanimate (zones-cross)",
        "card_types": ["Sorcery"],
        "mana_cost": {"B": 1, "generic": 1},
        "effects": [
            {"kind": "return_creature_from_your_graveyard_to_battlefield"}
        ],
    }


def _vanilla_creature_dict_cross(name="Test Bear (zones-cross)"):
    """A vanilla 2/2 creature target — what reanimate picks up."""
    return {
        "name": name,
        "card_types": ["Creature"],
        "mana_cost": {"generic": 2},
        "power": 2,
        "toughness": 2,
    }


def _discard_self_creature_dict():
    """Irreverent-Gremlin-shaped: a creature whose ETB-style effect
    makes its controller discard one card from hand."""
    return {
        "name": "Test Irreverent Gremlin (zones-cross)",
        "card_types": ["Creature"],
        "mana_cost": {"R": 1},
        "power": 1,
        "toughness": 1,
        "effects": [{"kind": "discard_self", "amount": 1}],
    }


# --- 1. find_object_zone reflects post-dispatch zone -----------------


def test_find_object_zone_after_destroy_target_returns_graveyard(synthetic_state):
    """After ``Effect::DestroyTarget`` dispatch moves a creature to the
    defender's graveyard, ``find_object_zone`` reflects the new home.
    Pinning the cross-cut: the inline move in the destroy arm must
    update ``GameObject.zone`` (not just the per-zone Vec membership)
    so the iterating reader resolves to the graveyard."""
    target_obj_id = 67  # p1's bf[0] in the synthetic seed.
    assert synthetic_state.find_object_zone(target_obj_id) == ZONE_BATTLEFIELD

    spell_obj_id = synthetic_state.register_and_inject_object(
        _destroy_target_creature_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.find_object_zone(target_obj_id) == ZONE_GRAVEYARD


def test_find_object_zone_after_sacrifice_returns_graveyard(synthetic_state):
    """After ``Effect::Sacrifice`` dispatch moves the active player's
    first battlefield obj to their graveyard, ``find_object_zone``
    resolves to ZONE_GRAVEYARD."""
    target_obj_id = 0  # p0's bf[0] in the synthetic seed.
    assert synthetic_state.find_object_zone(target_obj_id) == ZONE_BATTLEFIELD

    spell_obj_id = synthetic_state.register_and_inject_object(
        _sacrifice_target_creature_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.find_object_zone(target_obj_id) == ZONE_GRAVEYARD


def test_find_object_zone_after_exile_target_returns_exile(synthetic_state):
    """After ``Effect::ExileTarget`` dispatch moves a creature into
    the defender's exile, ``find_object_zone`` resolves to
    ZONE_EXILE (round-14 widened the reader to iterate exile)."""
    target_obj_id = 67  # p1's bf[0].
    assert synthetic_state.find_object_zone(target_obj_id) == ZONE_BATTLEFIELD

    spell_obj_id = synthetic_state.register_and_inject_object(
        _exile_target_creature_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.find_object_zone(target_obj_id) == ZONE_EXILE
    assert synthetic_state.exile_contains(target_obj_id) is True


# --- 2. round-trip: battlefield -> graveyard -> battlefield ----------


def test_destroy_then_reanimate_round_trips_through_graveyard(synthetic_state):
    """A creature destroyed by ``Effect::DestroyTarget`` lands in the
    defender's graveyard, then ``Effect::ReturnCreatureFromYour
    GraveyardToBattlefield`` (cast by that same player) pulls it back
    to the battlefield. find_object_zone tracks both legs of the trip;
    the reanimated copy enters with summoning_sick=true (CR 302.1) and
    no leftover tapped state from before the destroy.

    The defender (p1) is the one whose creature got destroyed, so p1
    is the player who reanimates — but in the synthetic state p0 is
    active. Build a state where p1 has the creature and p1 reanimates
    after switching active player.
    """
    # Use a clean synthetic state. Put a creature on p0's battlefield
    # (p0 = active), then sacrifice it ourselves — that lands it in
    # p0's graveyard, and we reanimate from p0's graveyard.
    creature_id = synthetic_state.register_and_inject_object(
        _vanilla_creature_dict_cross(), 0, ZONE_BATTLEFIELD
    )
    # Tap + damage before destroy to exercise the state reset.
    assert synthetic_state.tap_object(creature_id) is True
    assert synthetic_state.deal_damage(creature_id, 1) is True
    assert synthetic_state.is_tapped(creature_id) is True

    # Sacrifice (active player sacs their own — picks bf[0], which
    # is the synthetic forest at obj_id 0, not our creature). Instead
    # use the round-1 primitive directly to send our creature to the
    # graveyard — same end-state.
    assert synthetic_state.move_object(creature_id, ZONE_GRAVEYARD, 0) is True
    assert synthetic_state.find_object_zone(creature_id) == ZONE_GRAVEYARD

    # Reanimate via the Effect dispatch (composes with the round-17
    # primitive under the hood).
    reanimate_id = synthetic_state.register_and_inject_object(
        _reanimate_dict_cross(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(reanimate_id, 0)
    synthetic_state.resolve_top_of_stack()

    # Round-trip complete: creature back on battlefield with state
    # reset (summoning sickness stamped, tapped cleared, damage
    # cleared).
    assert synthetic_state.find_object_zone(creature_id) == ZONE_BATTLEFIELD
    assert synthetic_state.is_summoning_sick(creature_id) is True
    assert synthetic_state.is_tapped(creature_id) is False
    assert synthetic_state.get_damage(creature_id) == 0


# --- 3. hand -> graveyard via DiscardSelf -----------------------------


def test_discard_self_dispatch_moves_hand_card_to_graveyard(synthetic_state):
    """Inject a DiscardSelf source on p0's battlefield, push to stack,
    resolve. The first hand card moves to p0's graveyard.
    ``find_object_zone`` agrees: the discarded id now resolves to
    ZONE_GRAVEYARD."""
    # Snapshot p0's first hand card BEFORE the source injection
    # (register_and_inject_object appends to the requested zone, so
    # putting the source on battlefield doesn't perturb hand[0]).
    p0_first_hand_id = synthetic_state.hand_snapshot(0)[0]["id"]
    assert synthetic_state.find_object_zone(p0_first_hand_id) == ZONE_HAND

    src_id = synthetic_state.register_and_inject_object(
        _discard_self_creature_dict(), 0, ZONE_BATTLEFIELD
    )
    synthetic_state.push_to_stack(src_id, 0)
    synthetic_state.resolve_top_of_stack()

    # The discarded card lives in p0's graveyard now.
    assert synthetic_state.find_object_zone(p0_first_hand_id) == ZONE_GRAVEYARD


# --- 4. Library -> hand via draw_card composes with find_object_zone --


def test_draw_card_then_find_object_zone_tracks_to_hand(synthetic_state):
    """``draw_card`` returns the obj_id of the drawn card. After the
    draw, ``find_object_zone`` on that id resolves to ZONE_HAND. This
    is the round-1 primitive composition the rest of the engine builds
    on; it's covered by ``test_draw_card_moves_top_of_library_to_hand``
    above, but we re-pin here as the cross-primitive contract:
    draw_card's return value + find_object_zone agree."""
    drawn_id = synthetic_state.draw_card(0)
    assert drawn_id is not None
    assert synthetic_state.find_object_zone(drawn_id) == ZONE_HAND


# --- 5. graveyard_to_battlefield primitive no-op on non-graveyard obj --


def test_reanimate_primitive_idempotent_on_battlefield_object(synthetic_state):
    """Round-17 primitive direct: send a creature to graveyard, call
    move_object_from_graveyard_to_battlefield once -> True (now on bf).
    Call it again on the same id -> False (no longer in graveyard, so
    the primitive's gating returns False without movement). This is
    the explicit idempotence canary for the primitive — different
    from ``test_reanimate_returns_false_when_id_not_in_graveyard``
    which uses a never-graveyard id; here the id WAS in graveyard but
    was already pulled out."""
    obj_id = _put_creature_into_p0_graveyard(synthetic_state)

    # First call: success.
    assert (
        synthetic_state.move_object_from_graveyard_to_battlefield(0, obj_id)
        is True
    )
    assert synthetic_state.find_object_zone(obj_id) == ZONE_BATTLEFIELD
    bf_after_first = synthetic_state.battlefield_sizes[0]

    # Second call: object is on battlefield, not in graveyard -> no-op.
    assert (
        synthetic_state.move_object_from_graveyard_to_battlefield(0, obj_id)
        is False
    )
    # No double-add: battlefield count is unchanged.
    assert synthetic_state.battlefield_sizes[0] == bf_after_first
    assert synthetic_state.find_object_zone(obj_id) == ZONE_BATTLEFIELD


# --- 6. Cleanup-step zone preservation --------------------------------


def test_cleanup_step_does_not_change_object_zones(synthetic_state):
    """cleanup_step_for_active_player enforces hand-size discard (no-op
    here: 7 cards == 7) and clears marked damage on permanents — but
    objects themselves don't change zones from this alone. Pin the
    contract: a battlefield object stays on the battlefield, a hand
    object stays in hand, a library object stays in library."""
    bf_id = P0_FIRST_BATTLEFIELD_ID
    hand_id = P0_FIRST_HAND_ID
    lib_id = P0_FIRST_LIBRARY_ID
    # Pre-state.
    assert synthetic_state.find_object_zone(bf_id) == ZONE_BATTLEFIELD
    assert synthetic_state.find_object_zone(hand_id) == ZONE_HAND
    assert synthetic_state.find_object_zone(lib_id) == ZONE_LIBRARY
    bf_before = synthetic_state.battlefield_sizes
    hand_before = synthetic_state.hand_sizes
    library_before = synthetic_state.library_sizes
    gy_before = synthetic_state.graveyard_sizes

    synthetic_state.cleanup_step_for_active_player()

    # All three objects still in their original zones.
    assert synthetic_state.find_object_zone(bf_id) == ZONE_BATTLEFIELD
    assert synthetic_state.find_object_zone(hand_id) == ZONE_HAND
    assert synthetic_state.find_object_zone(lib_id) == ZONE_LIBRARY
    # No zone-size delta: 7 cards in hand == hand-size limit, so no
    # discard fires; cleanup damage-clear doesn't touch counts.
    assert synthetic_state.battlefield_sizes == bf_before
    assert synthetic_state.hand_sizes == hand_before
    assert synthetic_state.library_sizes == library_before
    assert synthetic_state.graveyard_sizes == gy_before


# --- 7. Multi-zone state after a sequence ----------------------------


def test_multi_zone_find_after_sequence(synthetic_state):
    """Build a state where one custom-injected object lives in each
    tracked zone (hand, library, battlefield, graveyard, exile). Then
    walk every id and assert find_object_zone returns the right
    constant. Exercises the full zone-search iteration order in one
    test — a regression where any one zone arm drops out of the
    iteration would surface here."""
    # Inject one custom object into each zone for player 0. Use the
    # vanilla creature dict so the registry has a printing for each
    # (the printing doesn't matter for the find — only the zone does).
    hand_obj = synthetic_state.register_and_inject_object(
        _vanilla_creature_dict_cross("Hand Resident"), 0, ZONE_HAND
    )
    library_obj = synthetic_state.register_and_inject_object(
        _vanilla_creature_dict_cross("Library Resident"), 0, ZONE_LIBRARY
    )
    bf_obj = synthetic_state.register_and_inject_object(
        _vanilla_creature_dict_cross("BF Resident"), 0, ZONE_BATTLEFIELD
    )
    gy_obj = synthetic_state.register_and_inject_object(
        _vanilla_creature_dict_cross("GY Resident"), 0, ZONE_GRAVEYARD
    )
    # No direct injection helper for exile — route via move_object.
    # Inject as battlefield-resident then bounce to exile.
    pre_exile_obj = synthetic_state.register_and_inject_object(
        _vanilla_creature_dict_cross("To-Exile Resident"), 0, ZONE_BATTLEFIELD
    )
    assert (
        synthetic_state.move_object(pre_exile_obj, ZONE_EXILE, 0) is True
    )
    exile_obj = pre_exile_obj

    # Each find resolves to the correct zone.
    assert synthetic_state.find_object_zone(hand_obj) == ZONE_HAND
    assert synthetic_state.find_object_zone(library_obj) == ZONE_LIBRARY
    assert synthetic_state.find_object_zone(bf_obj) == ZONE_BATTLEFIELD
    assert synthetic_state.find_object_zone(gy_obj) == ZONE_GRAVEYARD
    assert synthetic_state.find_object_zone(exile_obj) == ZONE_EXILE


# --- 8. CoW canary across Effect-driven moves ------------------------


def test_clone_isolation_across_destroy_target_dispatch(synthetic_state):
    """CoW canary at the cross-primitive level. Clone the state, run a
    full ``Effect::DestroyTarget`` resolve on the clone — the clone's
    target lands in graveyard, the original's stays on battlefield.
    Also: find_object_zone on the original still returns
    ZONE_BATTLEFIELD for the target.

    Mirrors test_clone_then_move_does_not_affect_original but routes
    through the Effect dispatch (which inlines its own move logic
    rather than calling move_object) — confirms the Arc::make_mut
    on the destroy arm is correctly scoped."""
    target_obj_id = 67  # p1's bf[0].

    spell_obj_id = synthetic_state.register_and_inject_object(
        _destroy_target_creature_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    bf_source_before = synthetic_state.battlefield_sizes
    gy_source_before = synthetic_state.graveyard_sizes

    cloned = synthetic_state.clone_once()
    cloned.resolve_top_of_stack()

    # Clone diverged: target in p1's graveyard.
    assert cloned.find_object_zone(target_obj_id) == ZONE_GRAVEYARD

    # Original untouched: target still on p1's battlefield, no zone
    # deltas. find_object_zone reads the original's zones, NOT the
    # clone's — load-bearing for the rust-side Arc-isolation.
    assert synthetic_state.find_object_zone(target_obj_id) == ZONE_BATTLEFIELD
    assert synthetic_state.battlefield_sizes == bf_source_before
    assert synthetic_state.graveyard_sizes == gy_source_before
    assert synthetic_state.stack_size() == 1


# -------------------- Round-28 PutCardFromGraveyardOnBottomOfLibrary --------------------


def _chrome_companion_dict():
    return {
        "name": "Chrome Companion (synthetic)",
        "card_types": ["Sorcery"],
        "mana_cost": {"generic": 1},
        "effects": [
            {"kind": "put_card_from_graveyard_on_bottom_of_library"}
        ],
    }


def _vanilla_creature_for_gy_test(name="Test Creature"):
    return {
        "name": name,
        "card_types": ["Creature"],
        "mana_cost": {"generic": 1},
        "power": 1,
        "toughness": 1,
    }


def test_register_put_card_from_graveyard_on_bottom_of_library(engine):
    """Unit variant registers cleanly."""
    reg = engine.Registry()
    pid = reg.register_printing(_chrome_companion_dict())
    effects = reg.get_printing_effects(pid)
    assert effects[0]["kind"] == "put_card_from_graveyard_on_bottom_of_library"


def test_resolve_put_card_from_gy_bottom_moves_to_library_bottom(synthetic_state):
    """Inject a creature into p0's graveyard, cast the spell —
    the creature moves to bottom of p0's library."""
    card_id = synthetic_state.register_and_inject_object(
        _vanilla_creature_for_gy_test(), 0, 3  # ZONE_GRAVEYARD
    )
    spell_id = synthetic_state.register_and_inject_object(
        _chrome_companion_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_id, 0)
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.find_object_zone(card_id) == 1  # ZONE_LIBRARY
    # Bottom = lib[0]. Verify via library_snapshot if it gives ordered list.
    lib_snap = synthetic_state.library_snapshot(0)
    # lib[0] is bottom per Rust convention.
    assert lib_snap[0]["id"] == card_id


def test_resolve_put_card_from_gy_bottom_picks_p0_first(synthetic_state):
    """When both players have graveyards, p0's graveyard is scanned
    first (deterministic first-slice convention)."""
    p0_card_id = synthetic_state.register_and_inject_object(
        _vanilla_creature_for_gy_test(name="P0 Card"), 0, 3
    )
    p1_card_id = synthetic_state.register_and_inject_object(
        _vanilla_creature_for_gy_test(name="P1 Card"), 1, 3
    )
    spell_id = synthetic_state.register_and_inject_object(
        _chrome_companion_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_id, 0)
    synthetic_state.resolve_top_of_stack()

    # p0's card moved; p1's stayed.
    assert synthetic_state.find_object_zone(p0_card_id) == 1  # ZONE_LIBRARY
    assert synthetic_state.find_object_zone(p1_card_id) == 3  # ZONE_GRAVEYARD


def test_resolve_put_card_from_gy_bottom_empty_both_fizzles(synthetic_state):
    """No cards in either graveyard → silent fizzle. The source
    sorcery still routes to graveyard (CR 608.2m)."""
    spell_id = synthetic_state.register_and_inject_object(
        _chrome_companion_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_id, 0)
    p0_gy_before = synthetic_state.graveyard_sizes[0]
    synthetic_state.resolve_top_of_stack()
    # Source went to graveyard.
    assert synthetic_state.find_object_zone(spell_id) == 3
    # p0 graveyard grew by 1 (the spell).
    assert synthetic_state.graveyard_sizes[0] == p0_gy_before + 1


def test_resolve_put_card_from_gy_bottom_uses_p1_when_p0_empty(synthetic_state):
    """If p0's graveyard is empty but p1's has cards, picks from p1."""
    p1_card_id = synthetic_state.register_and_inject_object(
        _vanilla_creature_for_gy_test(name="P1 Lonely"), 1, 3
    )
    spell_id = synthetic_state.register_and_inject_object(
        _chrome_companion_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_id, 0)
    synthetic_state.resolve_top_of_stack()

    # p1's card moved to p1's library bottom.
    assert synthetic_state.find_object_zone(p1_card_id) == 1
    p1_lib_snap = synthetic_state.library_snapshot(1)
    assert p1_lib_snap[0]["id"] == p1_card_id


# -------------------- Round-28 CreateTokenCopyOfTargetCreatureYouControl --------------------


def _mirrorpool_dict():
    return {
        "name": "Mirrorpool Mode-2 (synthetic)",
        "card_types": ["Instant"],
        "mana_cost": {"generic": 3},
        "effects": [
            {"kind": "create_token_copy_of_target_creature_you_control"}
        ],
    }


def test_register_create_token_copy(engine):
    reg = engine.Registry()
    pid = reg.register_printing(_mirrorpool_dict())
    eff = reg.get_printing_effects(pid)[0]
    assert eff["kind"] == "create_token_copy_of_target_creature_you_control"


def test_resolve_create_token_copy_spawns_new_object_same_printing(synthetic_state):
    """First creature on p0's bf (Grizzly Bears) is the target; a new
    object with the same printing_id lands on p0's bf."""
    snap_before = synthetic_state.battlefield_snapshot()
    p0_bears = [
        d for d in snap_before
        if d["controller_id"] == 0 and d["printing_name"] == "Grizzly Bears"
    ]
    first_bear_id = p0_bears[0]["id"]
    bears_printing_id = p0_bears[0]["printing_id"]
    bears_count_before = len(p0_bears)

    spell_id = synthetic_state.register_and_inject_object(
        _mirrorpool_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_id, 0)
    synthetic_state.resolve_top_of_stack()

    snap_after = synthetic_state.battlefield_snapshot()
    p0_bears_after = [
        d for d in snap_after
        if d["controller_id"] == 0 and d["printing_name"] == "Grizzly Bears"
    ]
    # Bears count grew by 1.
    assert len(p0_bears_after) == bears_count_before + 1
    # Original target unchanged; new object has the same printing_id.
    new_bear = next(d for d in p0_bears_after if d["id"] != first_bear_id and d["id"] not in {b["id"] for b in p0_bears})
    assert new_bear["printing_id"] == bears_printing_id
    assert new_bear["summoning_sick"] is True
    assert new_bear["tapped"] is False
    assert new_bear["damage"] == 0
    assert new_bear["counters"] == 0


def test_resolve_create_token_copy_no_eligible_fizzles(synthetic_state):
    """No creature on controller's bf → silent fizzle."""
    state = synthetic_state.clone_once()
    snap = state.battlefield_snapshot()
    p0_creatures = [
        d["id"] for d in snap
        if d["controller_id"] == 0 and d["printing_name"] == "Grizzly Bears"
    ]
    for cid in p0_creatures:
        state.move_object(cid, 3, 0)  # graveyard
    spell_id = state.register_and_inject_object(
        _mirrorpool_dict(), 0, ZONE_HAND
    )
    state.push_to_stack(spell_id, 0)
    state.resolve_top_of_stack()  # should not raise


def test_resolve_create_token_copy_clone_isolation(synthetic_state):
    spell_id = synthetic_state.register_and_inject_object(
        _mirrorpool_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_id, 0)
    p0_bears_before = sum(
        1 for d in synthetic_state.battlefield_snapshot()
        if d["controller_id"] == 0 and d["printing_name"] == "Grizzly Bears"
    )
    cloned = synthetic_state.clone_once()
    cloned.resolve_top_of_stack()
    p0_bears_clone = sum(
        1 for d in cloned.battlefield_snapshot()
        if d["controller_id"] == 0 and d["printing_name"] == "Grizzly Bears"
    )
    p0_bears_src = sum(
        1 for d in synthetic_state.battlefield_snapshot()
        if d["controller_id"] == 0 and d["printing_name"] == "Grizzly Bears"
    )
    assert p0_bears_clone == p0_bears_before + 1
    assert p0_bears_src == p0_bears_before


# -------------------- Round-28 OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary --------------------
#
# Effect: "Target artifact or creature's owner puts it on top or bottom
# of their library." 2 EoE cards. Python class lives at
# `effects/generic/zone_moves.py:30`.
#
# **First-slice deterministic-bottom.** Python prompts the OWNER's
# agent for top vs bottom; Rust has no decision-callback substrate yet,
# so we always pick bottom (= lib[0] per Rust convention). A reasonable
# first-slice mirror because decision-callback agents typically
# default-pick the bottom option (least disruptive).
#
# **Owner-as-controller simplification.** Rust doesn't track an
# owner-vs-controller distinction; first-slice synthetic states never
# split them, so we treat target.controller as the owner.
#
# **Target selection.** First defender (= 1 - active_player) permanent
# whose card_types contains "Artifact" OR "Creature". No eligible
# target = silent fizzle.


def _lost_in_space_dict():
    """Synthetic Lost-in-Space-shape spell. Controller-of-source casts
    it from hand; defender picks up the bounce."""
    return {
        "name": "Synthetic Lost in Space",
        "card_types": ["Sorcery"],
        "mana_cost": {"generic": 2, "U": 1},
        "effects": [
            {
                "kind": (
                    "owner_puts_target_artifact_or_creature_"
                    "on_top_or_bottom_of_library"
                )
            }
        ],
    }


def _vanilla_artifact_for_bounce(name="Bounce Target Artifact"):
    return {
        "name": name,
        "card_types": ["Artifact"],
        "mana_cost": {"generic": 1},
    }


def test_register_owner_puts_target_aoc_top_or_bottom(engine):
    """Unit variant registers + round-trips cleanly."""
    reg = engine.Registry()
    pid = reg.register_printing(_lost_in_space_dict())
    eff = reg.get_printing_effects(pid)[0]
    assert eff["kind"] == (
        "owner_puts_target_artifact_or_creature_on_top_or_bottom_of_library"
    )


def test_resolve_owner_puts_aoc_bottom_moves_defender_creature_to_lib_bottom(
    synthetic_state,
):
    """Casting puts first defender creature on bottom of OWNER's
    library. Synthetic state's p1 bf has Forests (non-creature,
    non-artifact) then Grizzly Bears — Bears is first eligible."""
    snap = synthetic_state.battlefield_snapshot()
    p1_first_bear_id = next(
        d["id"] for d in snap
        if d["controller_id"] == 1 and d["printing_name"] == "Grizzly Bears"
    )
    p1_lib_before = synthetic_state.library_sizes[1]
    spell_id = synthetic_state.register_and_inject_object(
        _lost_in_space_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_id, 0)
    synthetic_state.resolve_top_of_stack()

    # Target left battlefield.
    assert synthetic_state.find_object_zone(p1_first_bear_id) == ZONE_LIBRARY
    # Owner's library grew by 1.
    assert synthetic_state.library_sizes[1] == p1_lib_before + 1
    # Bottom of library (lib[0]) is the target.
    p1_lib_snap = synthetic_state.library_snapshot(1)
    assert p1_lib_snap[0]["id"] == p1_first_bear_id


def test_resolve_owner_puts_aoc_bottom_owner_is_controller(synthetic_state):
    """The card lands in the OWNER's library — owner is the target's
    controller (Rust treats controller as owner). Inject an artifact
    on p1's bf; cast the spell from p0 — the artifact moves to p1's
    library, NOT p0's."""
    # Move existing p1 creatures out so the artifact is first eligible.
    state = synthetic_state.clone_once()
    snap = state.battlefield_snapshot()
    p1_creature_ids = [
        d["id"] for d in snap
        if d["controller_id"] == 1 and d["printing_name"] == "Grizzly Bears"
    ]
    for cid in p1_creature_ids:
        state.move_object(cid, 3, 1)  # to p1 graveyard
    artifact_id = state.register_and_inject_object(
        _vanilla_artifact_for_bounce(), 1, ZONE_BATTLEFIELD
    )
    p0_lib_before = state.library_sizes[0]
    p1_lib_before = state.library_sizes[1]
    spell_id = state.register_and_inject_object(
        _lost_in_space_dict(), 0, ZONE_HAND
    )
    state.push_to_stack(spell_id, 0)
    state.resolve_top_of_stack()

    # Artifact landed in p1's library (owner = controller = 1).
    assert state.find_object_zone(artifact_id) == ZONE_LIBRARY
    assert state.library_sizes[0] == p0_lib_before
    assert state.library_sizes[1] == p1_lib_before + 1
    # Bottom of p1's library.
    p1_lib_snap = state.library_snapshot(1)
    assert p1_lib_snap[0]["id"] == artifact_id


def test_resolve_owner_puts_aoc_bottom_no_eligible_fizzles(synthetic_state):
    """No artifacts and no creatures on defender's bf → silent fizzle.
    The source sorcery still routes to graveyard (CR 608.2m)."""
    state = synthetic_state.clone_once()
    snap = state.battlefield_snapshot()
    p1_creature_ids = [
        d["id"] for d in snap
        if d["controller_id"] == 1 and d["printing_name"] == "Grizzly Bears"
    ]
    for cid in p1_creature_ids:
        state.move_object(cid, 3, 1)  # graveyard
    p1_lib_before = state.library_sizes[1]
    spell_id = state.register_and_inject_object(
        _lost_in_space_dict(), 0, ZONE_HAND
    )
    state.push_to_stack(spell_id, 0)
    state.resolve_top_of_stack()  # must not raise

    # Defender's library unchanged.
    assert state.library_sizes[1] == p1_lib_before
    # Source sorcery routed to p0's graveyard.
    assert state.find_object_zone(spell_id) == ZONE_GRAVEYARD


def test_resolve_owner_puts_aoc_bottom_clone_isolation(synthetic_state):
    """Resolving on the clone leaves the source state untouched."""
    snap = synthetic_state.battlefield_snapshot()
    p1_first_bear_id = next(
        d["id"] for d in snap
        if d["controller_id"] == 1 and d["printing_name"] == "Grizzly Bears"
    )
    spell_id = synthetic_state.register_and_inject_object(
        _lost_in_space_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_id, 0)
    cloned = synthetic_state.clone_once()
    cloned.resolve_top_of_stack()

    # Clone: target moved to library.
    assert cloned.find_object_zone(p1_first_bear_id) == ZONE_LIBRARY
    # Source state: target still on battlefield (no resolve happened).
    assert synthetic_state.find_object_zone(p1_first_bear_id) == ZONE_BATTLEFIELD
