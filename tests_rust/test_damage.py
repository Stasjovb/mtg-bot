"""Damage primitives on the Rust ``GameState``.

Ported from ``tests/test_combat.py`` and the per-creature ``damage``
field in ``src/mtg_bot/game.py`` (``GameObject.damage: int = 0``)
plus the end-of-turn cleanup in ``src/mtg_bot/turn.py`` that zeroes
``obj.damage`` on every battlefield permanent (CR 514.2 — "Damage
wears off").

Scope: a single per-instance ``i16`` accumulating damage marker on
``GameObject``. The primitives in this slice are the read / write /
clear / batch-clear operations every higher layer (combat, direct
damage spells, pingers, end-of-turn cleanup) needs from the engine.

**Lethal-damage SBA enforcement is out of scope (CR 704.5h).** This
slice reports raw marked damage; "damage >= toughness => destroy"
is a state-based action that needs an SBA loop on the Rust side
(future slice). Until then, callers can ask
``is_damage_at_least(obj_id, threshold)`` if they want the boolean
form against an externally-supplied threshold.

**Stepping-stone for is_lethal: ``is_damage_at_least``.** ``GameObject``
does not yet carry a base toughness — a sibling agent is wiring
``base_toughness`` onto ``CardPrinting`` in the bridge-ext slice this
round. So the lethal-damage helper exposed here is the threshold
form ``is_damage_at_least(obj_id, threshold)`` which a future slice
trivially specializes into ``is_lethal(obj_id) == is_damage_at_least(
obj_id, base_toughness)`` once the bridge lands. Keeping this on
the schedule today (vs deferring to the bridge slice) gets the read
shape right and surfaces the obvious follow-up by name.

The CoW canary lives in
``test_deal_damage_on_clone_does_not_affect_original`` —
load-bearing assertion that ``Arc::make_mut`` was used correctly
on the per-zone Vec when applying damage. Symmetric with the
canaries in ``test_tap.py`` and ``test_counters.py``.
"""

from __future__ import annotations

import pytest


# `make_synthetic_state(num_battlefield=10, num_hand=7, num_library=50)`
# lays player 0 out as:
#   battlefield: ids 0..9
#   hand:        ids 10..16
#   library:     ids 17..66
# and player 1's range starts at 67. We rely on these id ranges below.
P0_FIRST_BATTLEFIELD_ID = 0
P0_BATTLEFIELD_LAST_ID = 9
P0_FIRST_HAND_ID = 10
P0_FIRST_LIBRARY_ID = 17
P1_FIRST_BATTLEFIELD_ID = 67


def test_object_starts_with_zero_damage(synthetic_state):
    """Fresh synthetic objects come up with `damage == 0` (mirrors
    `GameObject.damage: i16 = 0` default in `rust/src/state.rs`)."""
    for obj_id in range(P0_FIRST_BATTLEFIELD_ID, P0_FIRST_BATTLEFIELD_ID + 10):
        assert synthetic_state.get_damage(obj_id) == 0


def test_get_damage_returns_value(synthetic_state):
    """After dealing damage, `get_damage` reads back the accumulated
    marker. Smallest end-to-end check that read and write touch the
    same field."""
    obj_id = P0_FIRST_BATTLEFIELD_ID
    synthetic_state.deal_damage(obj_id, 3)
    assert synthetic_state.get_damage(obj_id) == 3


def test_get_damage_unknown_id_returns_none(synthetic_state):
    """Reading damage off an id that doesn't exist anywhere returns
    `None`. Matches the read-side `is_tapped` / `get_counters`
    convention of distinguishing 'not found' from a real value."""
    assert synthetic_state.get_damage(999_999) is None


def test_deal_damage_increments(synthetic_state):
    """`deal_damage(obj_id, n)` adds n to the marked damage. Two
    successive deals of (2, 3) accumulate to 5 — damage is additive,
    not absolute (CR 120.3, multiple sources mark separately)."""
    obj_id = P0_FIRST_BATTLEFIELD_ID
    assert synthetic_state.deal_damage(obj_id, 2) is True
    assert synthetic_state.deal_damage(obj_id, 3) is True
    assert synthetic_state.get_damage(obj_id) == 5


def test_deal_damage_unknown_id_returns_false(synthetic_state):
    """Dealing damage to an id that isn't in any zone returns False
    rather than raising — mirrors the silent-no-op pattern that
    `tap_object` and `set_counters` use for the same scenario
    (object already left the relevant zone)."""
    assert synthetic_state.deal_damage(999_999, 3) is False


def test_deal_damage_negative_amount_raises_value_error(synthetic_state):
    """Per the project's "fail loud" convention (mirrors `gain_life`
    and `add_mana` in earlier slices), a negative `amount` to
    `deal_damage` is a caller bug rather than a request to heal —
    raises `ValueError`. `amount = 0` is allowed and is a true no-op."""
    obj_id = P0_FIRST_BATTLEFIELD_ID
    with pytest.raises(ValueError):
        synthetic_state.deal_damage(obj_id, -1)
    # 0 is allowed as a no-op.
    assert synthetic_state.deal_damage(obj_id, 0) is True
    assert synthetic_state.get_damage(obj_id) == 0


def test_clear_damage_zeroes(synthetic_state):
    """`clear_damage(obj_id)` zeroes the per-object damage marker.
    The end-of-turn cleanup step (CR 514.2) uses this to wear off
    damage on every battlefield permanent. Returns `True` on hit,
    `False` on unknown id."""
    obj_id = P0_FIRST_BATTLEFIELD_ID
    synthetic_state.deal_damage(obj_id, 4)
    assert synthetic_state.get_damage(obj_id) == 4
    assert synthetic_state.clear_damage(obj_id) is True
    assert synthetic_state.get_damage(obj_id) == 0
    # Unknown id is a silent False, symmetric with the rest of the
    # not-found convention.
    assert synthetic_state.clear_damage(999_999) is False


def test_clear_damage_for_player_zeroes_only_their_objects(synthetic_state):
    """`clear_damage_for_player(player_id)` walks one player's
    battlefield and zeroes each permanent's damage marker. The other
    player's permanents must not be touched — needed for any future
    "remove all damage from creatures you control" effect (Heroic
    Intervention / Make a Stand etc.) and as a building block for
    the per-player end-of-turn pass."""
    p0_obj = P0_FIRST_BATTLEFIELD_ID
    p1_obj = P1_FIRST_BATTLEFIELD_ID
    synthetic_state.deal_damage(p0_obj, 3)
    synthetic_state.deal_damage(p1_obj, 4)
    assert synthetic_state.get_damage(p0_obj) == 3
    assert synthetic_state.get_damage(p1_obj) == 4
    synthetic_state.clear_damage_for_player(0)
    assert synthetic_state.get_damage(p0_obj) == 0
    # Player 1's marked damage must be untouched.
    assert synthetic_state.get_damage(p1_obj) == 4


def test_clear_damage_for_all_objects(synthetic_state):
    """`clear_all_damage()` is the wholesale end-of-turn cleanup form
    — mirrors the `for obj in state.battlefield: obj.damage = 0` loop
    in `src/mtg_bot/turn.py` cleanup. Walks both players' battlefields
    and zeroes every damage marker in one call."""
    p0_obj = P0_FIRST_BATTLEFIELD_ID
    p0_obj2 = P0_FIRST_BATTLEFIELD_ID + 1
    p1_obj = P1_FIRST_BATTLEFIELD_ID
    synthetic_state.deal_damage(p0_obj, 1)
    synthetic_state.deal_damage(p0_obj2, 2)
    synthetic_state.deal_damage(p1_obj, 3)
    synthetic_state.clear_all_damage()
    assert synthetic_state.get_damage(p0_obj) == 0
    assert synthetic_state.get_damage(p0_obj2) == 0
    assert synthetic_state.get_damage(p1_obj) == 0


def test_is_damage_at_least_with_toughness_helper(synthetic_state):
    """`is_damage_at_least(obj_id, threshold)` is the threshold form
    of the lethal-damage check. Returns `Some(true)` when the
    object's marked damage is >= threshold, `Some(false)` when it
    is below, and `None` if no object exists with that id.

    Threshold form (vs full `is_lethal`) is the stepping-stone until
    `CardPrinting.base_toughness` lands in a parallel sibling slice
    — see this file's docstring."""
    obj_id = P0_FIRST_BATTLEFIELD_ID
    # No damage yet: threshold of 1 says "not at least 1".
    assert synthetic_state.is_damage_at_least(obj_id, 1) is False
    # threshold of 0 is trivially true (0 >= 0).
    assert synthetic_state.is_damage_at_least(obj_id, 0) is True
    synthetic_state.deal_damage(obj_id, 2)
    assert synthetic_state.is_damage_at_least(obj_id, 2) is True
    assert synthetic_state.is_damage_at_least(obj_id, 3) is False
    # Unknown id returns None (not found is distinct from a boolean).
    assert synthetic_state.is_damage_at_least(999_999, 1) is None


def test_clone_preserves_damage(synthetic_state):
    """A clone of the state — the same `Clone` impl MCTS exercises on
    every node expansion — carries damage values forward. They live
    inside `Arc<Vec<GameObject>>` and ride the refcount bump."""
    obj_id = P0_FIRST_BATTLEFIELD_ID
    synthetic_state.deal_damage(obj_id, 3)
    snapshot = synthetic_state.clone_once()
    assert snapshot.get_damage(obj_id) == 3


def test_deal_damage_on_clone_does_not_affect_original(synthetic_state):
    """**CoW canary.** The whole point of `Arc<Vec<GameObject>>` zones
    is that two live clones of a GameState observe independent
    mutations. Dealing damage on one clone must NOT visibly mutate
    the same object on the other — `Arc::make_mut` should clone the
    inner Vec on the first mutation while another reference is live.

    Same load-bearing invariant as
    `test_counter_change_on_clone_does_not_affect_original` but for
    the damage field. If this fails every CoW assumption downstream
    is broken."""
    obj_id = P0_FIRST_BATTLEFIELD_ID
    # Original starts at 0; baseline assertion before any mutation.
    assert synthetic_state.get_damage(obj_id) == 0
    other = synthetic_state.clone_once()
    assert other.get_damage(obj_id) == 0
    # Mutate ONLY the clone.
    assert other.deal_damage(obj_id, 5) is True
    assert other.get_damage(obj_id) == 5
    # Original must NOT see the change.
    assert synthetic_state.get_damage(obj_id) == 0, (
        "CoW broken: dealing damage on clone leaked into original"
    )
    # Symmetric direction: mutating the original after the clone
    # diverges should not retroactively touch the clone.
    assert synthetic_state.deal_damage(obj_id, 2) is True
    assert synthetic_state.get_damage(obj_id) == 2
    assert other.get_damage(obj_id) == 5
    # And clear_damage on the clone must not retroactively zero the
    # original.
    assert other.clear_damage(obj_id) is True
    assert other.get_damage(obj_id) == 0
    assert synthetic_state.get_damage(obj_id) == 2


# -----------------------------------------------------------------
# `deal_damage_to_player` — direct life mutation primitive.
#
# Distinct from `deal_damage` (above), which targets a `GameObject`
# and accumulates onto its per-instance damage marker. This variant
# subtracts directly from `Player.life` and is the building block
# for: combat damage to a defending player, burn-spell damage to a
# player, "deals damage to each opponent" effects, etc.
#
# Lives in the damage slice (rather than life slice) because it's a
# damage-source primitive — the call site is "this thing deals N
# damage to player P", not "player P loses N life arbitrarily".
# The current implementation collapses the two operations (Rust
# rules-text fidelity for damage→life-loss arrives in a later slice
# once replacement effects + lifelink-like routing land), but the
# named entry point for "damage to player" exists today so callers
# don't have to know the simplification.
# -----------------------------------------------------------------


def test_deal_damage_to_player_subtracts_life(synthetic_state):
    """`deal_damage_to_player(player_id, amount)` subtracts `amount`
    from that player's life total. Fresh synthetic state starts both
    players at life=20; dealing 5 to player 0 leaves them at 15."""
    assert synthetic_state.get_life(0) == 20
    synthetic_state.deal_damage_to_player(0, 5)
    assert synthetic_state.get_life(0) == 15


def test_deal_damage_to_player_zero_amount_no_op(synthetic_state):
    """`amount = 0` is a true no-op (life unchanged). Symmetric with
    the `deal_damage` zero-amount semantics on the GameObject form
    and the `gain_life` / `lose_life` zero-amount semantics in the
    life slice."""
    assert synthetic_state.get_life(0) == 20
    synthetic_state.deal_damage_to_player(0, 0)
    assert synthetic_state.get_life(0) == 20


def test_deal_damage_to_player_negative_raises(synthetic_state):
    """A negative `amount` is a caller bug — raises ValueError per
    the project's "fail loud" convention (mirrors `gain_life`,
    `lose_life`, and `deal_damage`)."""
    with pytest.raises(ValueError):
        synthetic_state.deal_damage_to_player(0, -1)
    # Life is unchanged after the failed call.
    assert synthetic_state.get_life(0) == 20


def test_deal_damage_to_player_unknown_player_raises(synthetic_state):
    """`player_id` outside [0, 1] raises — matches the life-slice
    `check_player_id` contract."""
    with pytest.raises((ValueError, IndexError)):
        synthetic_state.deal_damage_to_player(99, 1)


def test_deal_damage_to_player_can_take_life_below_zero(synthetic_state):
    """No clamping at zero — the engine reports raw life totals;
    "loss at <=0 is a game-loss" is a state-based action handled at
    a higher layer (CR 704.5a). Same rule as `lose_life` in the life
    slice."""
    assert synthetic_state.get_life(0) == 20
    synthetic_state.deal_damage_to_player(0, 25)
    assert synthetic_state.get_life(0) == -5


def test_deal_damage_to_player_does_not_affect_other_player(synthetic_state):
    """Dealing damage to player 0 must not touch player 1's life
    total, and vice versa."""
    assert synthetic_state.get_life(0) == 20
    assert synthetic_state.get_life(1) == 20
    synthetic_state.deal_damage_to_player(0, 7)
    assert synthetic_state.get_life(0) == 13
    assert synthetic_state.get_life(1) == 20
    synthetic_state.deal_damage_to_player(1, 3)
    assert synthetic_state.get_life(0) == 13
    assert synthetic_state.get_life(1) == 17


def test_clone_then_deal_damage_to_player_does_not_affect_original(
    synthetic_state,
):
    """CoW canary for the player-life path. `Player` lives by-value
    inside `GameState.players: [Player; 2]` (not behind an Arc), so
    a `GameState.clone()` deep-copies each Player struct and `life`
    is a Copy field — mutating life on one clone must not bleed into
    the other. Symmetric with the analogous canary in
    `test_life.py::test_modify_one_clone_does_not_affect_other`."""
    assert synthetic_state.get_life(0) == 20
    other = synthetic_state.clone_once()
    assert other.get_life(0) == 20
    # Mutate ONLY the clone.
    other.deal_damage_to_player(0, 4)
    assert other.get_life(0) == 16
    # Original must NOT see the change.
    assert synthetic_state.get_life(0) == 20, (
        "CoW broken: deal_damage_to_player on clone leaked into original"
    )
    # Symmetric direction: mutating original after divergence does
    # not retroactively touch the clone.
    synthetic_state.deal_damage_to_player(0, 2)
    assert synthetic_state.get_life(0) == 18
    assert other.get_life(0) == 16


# -----------------------------------------------------------------
# Cross-feature edge cases — damage primitives interacting with
# Effect dispatch (apply_effect via resolve_top_of_stack), cleanup,
# fingerprint, and CoW.
#
# These tests don't introduce new primitives — they pin down the
# observable interactions between damage and the surrounding slices
# so a regression in either side (damage write shape, dispatch
# routing, fingerprint inputs, cleanup loop) fails here loudly. The
# coverage mirrors the "load-bearing canary" pattern in this file's
# original block: damage is a building block every other layer
# reaches for, and the interactions below are the call sites the
# rest of the engine actually exercises.
#
# Zone / id layout used below (mirrors the module-level constants):
#
#   p0 battlefield: 0..4 Forest (Land), 5..9 Bears (Creature)
#   p1 battlefield: 67..71 Forest (Land), 72..76 Bears (Creature)
#
# So `bf[5]` is the FIRST Creature on each side — load-bearing for
# the DealDamageAnyTarget round-20 quirk (the variant filters by
# card_types == Creature, so it skips the 5 Lands at bf[0..4] and
# damages bf[5]).
# -----------------------------------------------------------------


ZONE_HAND = 0
ZONE_BATTLEFIELD = 2


def _bombard_any_creature_dict(amount=3):
    """A deal-damage spell targeting AnyCreature — cross-feature
    fixture used to confirm the Effect-dispatch path stamps damage in
    the same per-object field that `deal_damage` writes to. Same
    shape as the `_bombard_dict` helper in `test_resolve.py`."""
    return {
        "name": "Test Bombard Cross-Feature",
        "card_types": ["Sorcery"],
        "mana_cost": {"R": 1, "generic": 2},
        "effects": [
            {
                "kind": "deal_damage",
                "amount": amount,
                "target": {"kind": "any_creature"},
            }
        ],
    }


def _bombard_any_player_dict(amount=3):
    """A deal-damage spell targeting AnyPlayer — used to confirm
    Effect-dispatch decrements life via the same path
    `deal_damage_to_player` and `get_life` agree on."""
    return {
        "name": "Test Bombard To Player",
        "card_types": ["Sorcery"],
        "mana_cost": {"R": 1, "generic": 2},
        "effects": [
            {
                "kind": "deal_damage",
                "amount": amount,
                "target": {"kind": "any_player"},
            }
        ],
    }


def _debris_field_crusher_dict(amount=2):
    """A deal_damage_any_target spell — round-20 Lightning-Bolt-shape.
    The variant intrinsically filters by Creature card_types, so on a
    defender bf laid out as [5 Lands, then Creatures] it skips bf[0..4]
    and picks bf[5]. Mirrors the helper in `test_resolve.py`."""
    return {
        "name": "Test Debris Cross-Feature",
        "card_types": ["Sorcery"],
        "mana_cost": {"R": 1, "generic": 2},
        "effects": [{"kind": "deal_damage_any_target", "amount": amount}],
    }


def _pyroclasm_dict(amount=2):
    """A damage_each_creature spell — Pyroclasm-shape. Hits every
    creature on every player's battlefield via a single Effect
    dispatch. Mirrors the helper in `test_resolve.py`."""
    return {
        "name": "Test Pyroclasm Cross-Feature",
        "card_types": ["Sorcery"],
        "mana_cost": {"R": 1, "generic": 1},
        "effects": [{"kind": "damage_each_creature", "amount": amount}],
    }


def _earthquake_dict(amount=2):
    """A damage_each_opponent spell — Earthquake-shape (life-only AOE).
    Mirrors the helper in `test_resolve.py`."""
    return {
        "name": "Test Earthquake Cross-Feature",
        "card_types": ["Sorcery"],
        "mana_cost": {"R": 1, "generic": 1},
        "effects": [{"kind": "damage_each_opponent", "amount": amount}],
    }


def _indestructible_creature_dict():
    """A vanilla creature printing with the ``indestructible`` keyword.
    Used here to confirm the damage write happens regardless — the
    indestructibility check is an SBA / destroy-time concern (CR
    702.12 + CR 704.5h), not a damage-write-time gate."""
    return {
        "name": "Test Stone Idol Cross-Feature",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 4},
        "effects": [],
        "power": 3,
        "toughness": 3,
        "keywords": ["indestructible"],
    }


def test_dealdamage_effect_stamps_same_damage_field_as_primitive(
    synthetic_state,
):
    """**Cross-feature with Effect dispatch.** The `DealDamage` Effect
    arm in `apply_effect` (state_ops_resolve.rs) must stamp the same
    per-object `damage` field that `deal_damage` writes to and
    `get_damage` reads from. Verifies the read/write surface stays
    coherent when damage arrives via spell resolution rather than via
    a direct primitive call. If this fails, the Effect arm forked the
    storage and downstream readers see stale zero."""
    target_obj_id = 67  # p1's bf[0] (Forest) — AnyCreature picks bf[0]
    assert synthetic_state.get_damage(target_obj_id) == 0

    spell_obj_id = synthetic_state.register_and_inject_object(
        _bombard_any_creature_dict(amount=4), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    # Damage appears via the same getter the primitive uses.
    assert synthetic_state.get_damage(target_obj_id) == 4
    # And the is_damage_at_least threshold helper agrees — the two
    # readers go through the same `read_damage` walker.
    assert synthetic_state.is_damage_at_least(target_obj_id, 4) is True
    assert synthetic_state.is_damage_at_least(target_obj_id, 5) is False


def test_dealdamage_to_player_via_effect_decrements_get_life(
    synthetic_state,
):
    """**Cross-feature with snapshot getter agreement.** A `DealDamage`
    Effect with `AnyPlayer` target decrements the defender's `life`
    field — the same field `get_life` and `life_totals` read. Pins
    the invariant that spell-dispatch life loss is observable through
    the snapshot surface (`life_totals`) and the scalar getter
    (`get_life`) alike, in lockstep with the `deal_damage_to_player`
    primitive."""
    assert synthetic_state.get_life(1) == 20
    assert synthetic_state.life_totals[1] == 20

    spell_obj_id = synthetic_state.register_and_inject_object(
        _bombard_any_player_dict(amount=5), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    # Both readers report the same post-resolve life.
    assert synthetic_state.get_life(1) == 15
    assert synthetic_state.life_totals[1] == 15
    # Active player (= controller) untouched — same isolation property
    # the primitive `deal_damage_to_player` shows.
    assert synthetic_state.get_life(0) == 20


def test_deal_damage_any_target_round_20_quirk_hits_first_creature_not_first_object(
    synthetic_state,
):
    """**Round-20 quirk** (load-bearing for `DealDamageAnyTarget`'s
    Lightning-Bolt shape). On the synthetic seed, p1's battlefield is
    `[Forest, Forest, Forest, Forest, Forest, Bears, ...]` — `bf[0]`
    is a Land, `bf[5]` is the first Creature. `DealDamageAnyTarget`
    filters by `card_types == Creature` intrinsically, so it skips
    bf[0..4] and lands on bf[5]. Distinct from `DealDamage{AnyCreature}`,
    which picks bf[0] unconditionally regardless of card type.
    Cross-feature with the damage primitive: the same `get_damage`
    reader confirms which obj_id took the hit and which ones didn't."""
    first_creature_id = 72  # p1 bf[5], first Bears
    first_land_id = 67  # p1 bf[0], first Forest
    assert synthetic_state.get_damage(first_creature_id) == 0
    assert synthetic_state.get_damage(first_land_id) == 0

    spell_obj_id = synthetic_state.register_and_inject_object(
        _debris_field_crusher_dict(amount=3), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    # First Creature took the hit; the 5 Forests at bf[0..4] are
    # untouched. Confirms the type filter via the same per-object
    # damage reader the primitive uses.
    assert synthetic_state.get_damage(first_creature_id) == 3
    for land_id in (67, 68, 69, 70, 71):
        assert synthetic_state.get_damage(land_id) == 0


def test_deal_damage_zero_amount_is_no_op_quirk(synthetic_state):
    """**Documenting the zero-amount quirk.** `deal_damage(obj, 0)`
    returns True on a found object (it's a successful no-op) and
    leaves the damage marker unchanged. This is the same shape every
    other "zero is fine, negative raises" primitive in the engine
    uses (gain_life, lose_life, add_mana, ...), but the documented
    contract is worth a pinned regression test on its own. Distinct
    from "object not found" (returns False) — see the unknown-id
    test in the original block."""
    obj_id = P0_FIRST_BATTLEFIELD_ID
    # Pre-load with damage so we can prove a 0-stamp doesn't reset it.
    assert synthetic_state.deal_damage(obj_id, 3) is True
    assert synthetic_state.get_damage(obj_id) == 3
    # Zero amount: successful no-op — returns True, damage unchanged.
    assert synthetic_state.deal_damage(obj_id, 0) is True
    assert synthetic_state.get_damage(obj_id) == 3, (
        "deal_damage(0) must not zero existing damage — that's the job "
        "of clear_damage / clear_all_damage"
    )


def test_deal_damage_to_indestructible_creature_still_stamps_damage(engine):
    """**Cross-feature with the indestructible keyword.** The damage
    primitive itself does NOT consult `card_types` or `keywords` —
    it stamps damage on any GameObject. Indestructibility is an SBA-
    time concern (CR 702.12: indestructible permanents ignore lethal
    damage and destroy effects; CR 704.5h: lethal-damage SBA), NOT a
    damage-write-time gate. Verifying this prevents a future "make
    indestructible silently suppress damage" regression that would
    break combat-damage tracking (the indestructible creature still
    takes damage, it just doesn't die from it)."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=1
    )
    indestructible_id = state.register_and_inject_object(
        _indestructible_creature_dict(), 1, ZONE_BATTLEFIELD
    )
    # Direct primitive: damage is stamped regardless of the keyword.
    assert state.deal_damage(indestructible_id, 7) is True
    assert state.get_damage(indestructible_id) == 7
    # And the threshold helper sees the same value — confirms there
    # is no implicit "indestructible -> clamp damage" path.
    assert state.is_damage_at_least(indestructible_id, 7) is True


def test_damage_each_creature_via_effect_marks_every_bf_creature_in_one_apply(
    synthetic_state,
):
    """**Cross-feature with Effect-dispatch AOE.** Resolving
    `DamageEachCreature` (Pyroclasm shape) marks `damage += amount`
    on every creature on BOTH players' battlefields in one
    `apply_effect` call. Lands on either side stay at zero. Pins the
    interaction between the per-object damage primitive and the AOE
    Effect arm — if the arm forked storage, only some of these
    creatures would show damage and the test would fail loudly."""
    creature_ids = (5, 6, 7, 8, 9, 72, 73, 74, 75, 76)
    land_ids = (0, 1, 2, 3, 4, 67, 68, 69, 70, 71)
    for cid in creature_ids:
        assert synthetic_state.get_damage(cid) == 0

    spell_obj_id = synthetic_state.register_and_inject_object(
        _pyroclasm_dict(amount=2), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    # All 5+5 creatures took 2 damage.
    for cid in creature_ids:
        assert synthetic_state.get_damage(cid) == 2
    # All 5+5 lands stay at zero — confirms the type filter.
    for lid in land_ids:
        assert synthetic_state.get_damage(lid) == 0


def test_damage_each_opponent_via_effect_only_damages_defender_not_active_player(
    synthetic_state,
):
    """**Cross-feature: AOE life loss.** `DamageEachOpponent` (life-
    only AOE — Earthquake-shape but to players only) damages every
    opponent's life total, NOT the controller's. Asymmetric vs
    `DamageEachCreature` (which is symmetric). Pinning this catches
    a regression where the opponent filter is dropped and the active
    player self-damages."""
    assert synthetic_state.active_player == 0
    p0_life_before = synthetic_state.get_life(0)
    p1_life_before = synthetic_state.get_life(1)

    spell_obj_id = synthetic_state.register_and_inject_object(
        _earthquake_dict(amount=4), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    # Active player (= controller) UNTOUCHED — the asymmetric AOE.
    assert synthetic_state.get_life(0) == p0_life_before
    # The one opponent (defender) lost `amount` life.
    assert synthetic_state.get_life(1) == p1_life_before - 4


def test_cleanup_step_clears_damage_stamped_by_both_primitive_and_effect(
    synthetic_state,
):
    """**Cross-feature with cleanup primitive.** Damage written via
    BOTH the direct primitive AND the Effect-dispatch path must clear
    in the same `cleanup_step_for_active_player` call. This pins the
    invariant that the cleanup loop reads the same per-object
    `damage` field both writers use — if storage forked, half the
    creatures would still show damage after cleanup."""
    # Stamp via primitive on a couple of p0 creatures.
    synthetic_state.deal_damage(5, 1)
    synthetic_state.deal_damage(6, 2)
    # Stamp via Effect dispatch on EVERY creature (Pyroclasm-3).
    spell_obj_id = synthetic_state.register_and_inject_object(
        _pyroclasm_dict(amount=3), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack()
    # Pre-cleanup: primitive-stamped creatures show 1+3 / 2+3, the
    # rest show 3.
    assert synthetic_state.get_damage(5) == 4
    assert synthetic_state.get_damage(6) == 5
    assert synthetic_state.get_damage(7) == 3
    assert synthetic_state.get_damage(72) == 3

    # One cleanup call clears every marker on both players' bf —
    # symmetric with `clear_all_damage` but routed through the
    # composition primitive cleanup uses.
    summary = synthetic_state.cleanup_step_for_active_player()
    # 10 creatures (5 p0 Bears + 5 p1 Bears) carried non-zero damage;
    # the 10 Forests on bf stayed at zero and aren't counted.
    assert summary["damage_cleared"] == 10

    # Every creature back to zero damage.
    for cid in (5, 6, 7, 8, 9, 72, 73, 74, 75, 76):
        assert synthetic_state.get_damage(cid) == 0


def test_dealdamage_on_clone_via_effect_does_not_affect_original(
    synthetic_state,
):
    """**CoW canary, Effect-dispatch flavor.** The original block's
    `test_deal_damage_on_clone_does_not_affect_original` covered the
    direct-primitive path; this companion confirms the same isolation
    holds when damage is written via `apply_effect` (resolve_top_of_stack).
    The clone's spell resolution must not leak the per-object damage
    write back to the original. If `Arc::make_mut` on the battlefield
    Vec inside the Effect arm regressed to a plain `Arc::clone`,
    both states would observe the damage and this test would fail."""
    target_obj_id = 67  # p1 bf[0]; AnyCreature picks the first object
    spell_obj_id = synthetic_state.register_and_inject_object(
        _bombard_any_creature_dict(amount=6), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    clone = synthetic_state.clone_once()

    # Resolve on the clone only.
    clone.resolve_top_of_stack()

    # Clone: spell resolved, damage stamped, stack drained.
    assert clone.get_damage(target_obj_id) == 6
    assert clone.is_stack_empty() is True
    # Original: untouched — same load-bearing invariant as the
    # primitive-flavored CoW canary above.
    assert synthetic_state.get_damage(target_obj_id) == 0, (
        "CoW broken: Effect-dispatch damage write on clone leaked "
        "into original"
    )
    assert synthetic_state.stack_size() == 1


def test_fingerprint_changes_when_damage_stamp_differs(synthetic_state):
    """**Cross-feature with fingerprint.** The canonical state-equality
    digest is what parity-smoke and the MCTS NN-eval cache key off.
    Two states differing only by a per-object damage stamp must
    produce DIFFERENT fingerprints — otherwise CoW-cloned positions
    with different combat damage histories would collide in the
    cache and corrupt evaluation."""
    obj_id = P0_FIRST_BATTLEFIELD_ID
    fp_before = synthetic_state.fingerprint()
    # Single per-object damage stamp.
    assert synthetic_state.deal_damage(obj_id, 2) is True
    fp_after = synthetic_state.fingerprint()
    assert fp_before != fp_after, (
        "fingerprint must change when a per-object damage stamp "
        "changes — otherwise CoW positions with different damage "
        "histories collide"
    )
    # Clearing the same damage returns to the original fingerprint —
    # confirms damage is the only differing field and the digest is
    # a pure function of state (deterministic round-trip).
    assert synthetic_state.clear_damage(obj_id) is True
    assert synthetic_state.fingerprint() == fp_before
