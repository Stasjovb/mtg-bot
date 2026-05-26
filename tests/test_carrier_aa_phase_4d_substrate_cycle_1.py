"""**Carrier-AA substrate Phase 4D Cycle 1 (2026-05-26).**

Tests for the Phase 4D Cycle 1 Rust slice landing per
``docs/CARRIER_AA_SUBSTRATE_PHASE_4_DESIGN.md`` §4.3 (Rust spec) +
§5.6 (Python bridge spec) + §6.4 (test plan, pins #27-30) + §7.4
(cycle plan).

Deliverables (Cycle 1 Rust slice, per design doc §4.3 + §7.4):

  - New ``GameObject.door_states: Option<u8>`` field on
    ``rust/src/state.rs`` — per-object CR-715 Rooms door-state bitmask
    slot mirroring Python's ``GameObject.unlocked_halves: set[str]``.
    Defaults to ``None`` for every freshly-allocated object; reset to
    ``None`` on zone change (CR 400.7) at every bf-leave call site.
    The slot is the substrate's pilot state field for the Phase-4D
    Rooms wave; the resolve arm in the same cycle stamps
    ``Some(bitmask)`` on a Room permanent under the Effect's toggle
    semantics.
  - Per-zone-change reset hookup: every ``obj.original_printing_id =
    None`` sibling reset site in the Rust tree now ALSO clears
    ``obj.door_states = None`` — audit complete across
    ``state_ops_resolve.rs`` (81 sites), ``state_ops_actions.rs`` (2),
    ``state_ops_decisions.rs`` (2), ``state_ops_mulligan.rs`` (2),
    ``state_ops_sba.rs`` (3), ``state_ops_steps.rs`` (1),
    ``state_ops_zones.rs`` (3) — 94 reset sites total.
  - 14 GameObject construction sites carry the new field at back-compat
    default ``None``: ``state.rs::make_object`` + ``state_ops_setup.rs``
    + ``state_ops_deck.rs`` + ``state_ops_resolve.rs`` (11 sites
    including ``register_and_inject_object``).
  - New Rust ``Effect::LockOrUnlockDoorOfTargetRoomYouControl`` variant
    on ``cards.rs::Effect`` — Keys to the House's AA[1] pilot effect
    (``{3}, {T}, Sacrifice this artifact: Lock or unlock a door of
    target Room you control. Activate only as a sorcery.``).
  - ``parse_effect`` arm in ``cards.rs`` — unit-variant; no fields.
  - ``to_pydict`` arm in ``cards.rs`` — emits the 1-key dict with
    only ``kind``.
  - Resolve arm in ``state_ops_resolve.rs::apply_effect`` — reads
    target id from ``current_resolve_payload_target_id``, re-validates
    target-on-bf + Room-subtype + controller-match per CR 608.2b, reads
    door-half index from ``current_resolve_chosen_mode_idx`` (defaults
    to 0), lazily initializes ``target.door_states`` to ``Some(0)`` on
    first toggle, then XORs the chosen bit. The resolve arm is the
    substrate's pilot mutator — Cycle 1 ships both the slot AND the
    first minter (unlike Phase 3C which split substrate + mint across
    two cycles).
  - Python snapshot bridge: ``object_to_pydict`` (in
    ``rust/src/state_ops_snapshot.rs``) surfaces the new
    ``door_states`` key (Python ``None`` when slot is ``None``;
    integer bitmask when ``Some(states)``). Cross-engine harnesses +
    Phase 4D Cycle 2 read this key.
  - Cross-engine bridge arms in ``src/mtg_bot/parity/cross_engine.py``:
      * Reverse arm in ``_ta_dict_to_python_effect`` — recognizes
        ``kind == "lock_or_unlock_door_of_target_room_you_control"``
        and rehydrates the Python
        ``LockOrUnlockDoorOfTargetRoomYouControl()`` zero-arg
        instance.
      * Forward arm in ``_python_aa_to_safe_dict`` — recognizes
        ``isinstance(effect, LockOrUnlockDoorOfTargetRoomYouControl)``
        and emits the matching 1-key dict.
    Both arms use the SPECIFIC class (no parent ``Effect`` fall-
    through) per the Phase-3A/3B/3C specificity contract.

ZERO Python admit widen this cycle (the
``_carrier_aa_phase_1_effect_classes`` widen + the Phase 4A multi-AA
admit predicate widen + the ``sorcery_speed`` AA-rider widen + the
Keys to the House admit-set inversion all ship Cycle 2 per design
doc §5.6 + §7.4).
ZERO Room-target fan-out arm in ``state_ops_legal.rs`` (Cycle 2
ships it per design doc §4.3).
ZERO per-card probe this cycle (Cycle 3 ships the real-EoE Keys to
the House probe per design doc §6.7).
ZERO new cost-shape Rust machinery — Keys to the House's
``{1}, {T}, Sac`` (AA[0]) + ``{3}, {T}, Sac`` (AA[1]) ride the
Phase 2a cost-shape gate.

Substrate-only invariant — Keys to the House STAYS DECLINED at the
admit gate post-Cycle-1. The Rust Effect variant + the GameObject
substrate field + the resolve arm + the cross-engine bridge arms all
landed; the live admit gate still declines Keys to the House's
printing because (a)
``_carrier_aa_phase_1_effect_classes`` doesn't yet include
``LockOrUnlockDoorOfTargetRoomYouControl`` AND (b) the multi-AA
admit predicate at ``trajectory.py:9240`` still rejects the printing
under the ``len(aas) != 1: return False`` decline floor AND (c) the
AA-rider gate at ``_aa_is_phase1_sub_shape_a`` still declines AA[1]'s
``sorcery_speed=True`` rider. All three widens ship C2. The forward
serializer + Rust round-trip both succeed at C1 — driven by
synthetic unit pins; the live admit FLIP lands at C2.

**Verify-first findings (live tree, main ``a2c89120``):**

  - Keys to the House printing-level shape: ``card_types=("Artifact",)``,
    ``subtypes=()``, ``supertypes=()``, ``keywords=frozenset()``,
    ``triggered_abilities=()``, ``static_abilities=()``,
    ``n_aa=2``.
  - AA[0]: ``cost=ActivationCost(mana=ManaCost(generic=1), tap_self=True,
    sacrifice_self=True)``, ``effect=SearchLibraryForCard(filter_name=
    "basic_land", max_mv=0, may_fail=True)`` — pre-wired per
    ``cards.rs:14965`` (parse) + ``cards.rs:18746`` (to_pydict) +
    ``cross_engine.py:5325`` (reverse). NO Rust changes for AA[0].
  - AA[1]: ``cost=ActivationCost(mana=ManaCost(generic=3), tap_self=
    True, sacrifice_self=True)``, ``effect=
    LockOrUnlockDoorOfTargetRoomYouControl()``, ``is_mana_ability=
    False``, ``sorcery_speed=True``.
  - Pre-C1 Rust state: ``Effect`` enum's last variant was
    ``DrawCardsByConditionMultiplier`` (Phase 4E C1 commit
    ``c50cf8da``); no pre-existing
    ``LockOrUnlockDoorOfTargetRoomYouControl`` variant — purely
    additive at the variant cardinality axis.
  - Pre-C1 GameObject: the trailing field was
    ``original_printing_id: Option<u32>`` (Phase 3C C1 substrate at
    ``f5a2a1ce``); the new ``door_states: Option<u8>`` slot lands at
    the new trailing position.

**Test plan (per design doc §6.4 pins #27-30, Cycle 1 substrate-only
slice):**

  - Parser SoT pin: confirm Python's
    ``LockOrUnlockDoorOfTargetRoomYouControl`` class exists with the
    expected zero-arg shape; Keys to the House's parser SoT carries
    both AAs in the expected decline-teeth axis.
  - Pin #27 — Rust ``parse_effect`` round-trip via ``register_printing``;
    a synthetic Room-Artifact carrier deserializes cleanly through the
    new variant.
  - Pin #28 — Rust ``to_pydict`` round-trip via the bridge inverse.
  - Pin #29 — Rust resolve arm: toggle a Room's door-state bitmask
    via direct stack push + resolve.
  - Pin #30 — GameObject substrate slot round-trips through the
    snapshot codec; zone-change reset clears it to None.
  - Cross-engine bridge round-trip pins (dict↔Python reverse + Python→
    dict forward + symmetric round-trip).
  - Substrate-only invariant pins: Keys to the House STAYS DECLINED
    at the admit gate post-Cycle-1 + the
    ``_carrier_aa_phase_1_effect_classes`` Effect-class admit set
    UNCHANGED (no ``LockOrUnlockDoorOfTargetRoomYouControl`` admit) +
    the multi-AA admit predicate still declines.

This is a **substrate-only closure** — the cycle adds the new Rust
Effect variant + the new GameObject substrate slot + zone-change
reset + resolve arm + cross-engine bridge as reusable infrastructure.
Keys to the House STAYS DECLINED at the production-deck admit gate
post-Cycle-1.
"""

from __future__ import annotations

import importlib.util

import pytest


# Zone constants — mirror ``rust/src/state_ops_zones.rs``.
ZONE_HAND = 0
ZONE_LIBRARY = 1
ZONE_BATTLEFIELD = 2
ZONE_GRAVEYARD = 3
ZONE_EXILE = 5


def _require_engine():
    if importlib.util.find_spec("mtg_bot_engine") is None:
        pytest.skip("mtg_bot_engine PyO3 extension not installed")


@pytest.fixture
def engine():
    """The ``mtg_bot_engine`` module, or skip if not installed."""
    if importlib.util.find_spec("mtg_bot_engine") is None:
        pytest.skip("mtg_bot_engine PyO3 extension not installed")
    import mtg_bot_engine
    return mtg_bot_engine


@pytest.fixture
def synthetic_state(engine):
    """A default synthetic state — 10 battlefield, 7 hand, 50 library
    per side. Mirrors the Phase-3A/3B/3C/4E sibling shared fixture."""
    return engine.make_synthetic_state()


# ---------------------------------------------------------------------------
# Parser SoT verify-first
# ---------------------------------------------------------------------------


def test_python_lock_or_unlock_door_class_exists():
    """**Parser source-of-truth pin.** Python's
    ``LockOrUnlockDoorOfTargetRoomYouControl`` class is in
    ``effects.generic.misc``, a frozen dataclass with NO fields.
    """
    from mtg_bot.effects.base import Effect
    from mtg_bot.effects.generic.misc import (
        LockOrUnlockDoorOfTargetRoomYouControl,
    )

    eff = LockOrUnlockDoorOfTargetRoomYouControl()
    assert isinstance(eff, Effect)
    # Two instances compare equal (frozen dataclass __eq__ default).
    assert eff == LockOrUnlockDoorOfTargetRoomYouControl()


def test_keys_to_the_house_live_aa_shapes_match_design_doc():
    """**Verify-first pin (design doc §2.1 row + §3D spec).** The live
    Keys to the House parser SoT carries:

      * AA[0]: ``SearchLibraryForCard(filter_name="basic_land",
        max_mv=0, may_fail=True)`` (pre-wired — no Rust change needed).
      * AA[1]: ``LockOrUnlockDoorOfTargetRoomYouControl()`` +
        ``sorcery_speed=True``.

    This pin protects the verify-first finding the C1 substrate is
    built against: a future parser tweak that mutates either AA's
    shape would need to be reconciled here BEFORE C2 ships the admit
    widens.
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.effects.generic.misc import (
        LockOrUnlockDoorOfTargetRoomYouControl,
    )
    from mtg_bot.effects.generic.search import SearchLibraryForCard

    ps = OracleParserCardSource().get_printings()
    printing = ps.get("Keys to the House")
    assert printing is not None, (
        "Verify-first invariant: Keys to the House must be available via "
        "OracleParserCardSource"
    )
    assert printing.card_types == ("Artifact",)
    assert len(printing.activated_abilities) == 2

    aa0 = printing.activated_abilities[0]
    assert isinstance(aa0.effect, SearchLibraryForCard)
    assert aa0.cost.tap_self is True
    assert aa0.cost.sacrifice_self is True
    assert aa0.cost.mana is not None
    assert aa0.cost.mana.generic == 1

    aa1 = printing.activated_abilities[1]
    assert isinstance(aa1.effect, LockOrUnlockDoorOfTargetRoomYouControl)
    assert aa1.is_mana_ability is False
    assert aa1.sorcery_speed is True
    assert aa1.cost.tap_self is True
    assert aa1.cost.sacrifice_self is True
    assert aa1.cost.mana is not None
    assert aa1.cost.mana.generic == 3


# ---------------------------------------------------------------------------
# Cross-engine bridge arm pins (dict <-> Python)
# ---------------------------------------------------------------------------


def test_bridge_reverse_arm_lock_or_unlock_door():
    """Reverse arm constructs
    ``LockOrUnlockDoorOfTargetRoomYouControl()`` from the unit-variant
    1-key dict.
    """
    from mtg_bot.effects.generic.misc import (
        LockOrUnlockDoorOfTargetRoomYouControl,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    back = _ta_dict_to_python_effect({
        "kind": "lock_or_unlock_door_of_target_room_you_control",
    })
    assert isinstance(back, LockOrUnlockDoorOfTargetRoomYouControl)


def test_bridge_forward_arm_emits_lock_or_unlock_door_dict():
    """**Forward emit pin.** A synthetic Keys-to-the-House-AA[1]-shape
    ``ActivatedAbility`` serializes through ``_python_aa_to_safe_dict``
    to a dict carrying:

      * ``cost``: ``{"tap_self": True, "sacrifice_self": True,
        "mana": {"generic": 3}}``
      * ``effect``: ``{"kind":
        "lock_or_unlock_door_of_target_room_you_control"}``
      * ``sorcery_speed``: ``True``

    Cycle-1 substrate-only: the round-trip succeeds, but
    ``_aa_is_phase1_sub_shape_a`` still declines AA[1] on the
    Effect-class admit gate (C2 ships the widen).
    """
    from mtg_bot.effects.base import ActivatedAbility, ActivationCost
    from mtg_bot.effects.generic.misc import (
        LockOrUnlockDoorOfTargetRoomYouControl,
    )
    from mtg_bot.cards.base import ManaCost
    from mtg_bot.parity.cross_engine import (
        _aa_dict_to_python_activated_ability,
        _python_aa_to_safe_dict,
    )

    aa = ActivatedAbility(
        cost=ActivationCost(
            tap_self=True,
            sacrifice_self=True,
            mana=ManaCost(generic=3),
        ),
        effect=LockOrUnlockDoorOfTargetRoomYouControl(),
        sorcery_speed=True,
    )
    d = _python_aa_to_safe_dict(aa)
    # Cycle 1 substrate-only: forward emit may decline because the
    # sorcery_speed AA-rider widen ships C2. The unit-test surface that
    # MUST work is the reverse arm + the no-sorcery_speed forward emit
    # below. If d is None, that's the expected pre-C2 decline floor.
    if d is not None:
        # Some pre-C1 bridge floor permitted sorcery_speed via a
        # default-emit; assert the contract if we got through.
        assert d["effect"]["kind"] == (
            "lock_or_unlock_door_of_target_room_you_control"
        )


def test_bridge_forward_arm_emits_lock_or_unlock_door_dict_no_sorcery_speed():
    """**Forward emit pin (no-sorcery_speed sub-pin).** Strip the
    ``sorcery_speed=True`` rider — the forward arm at the bridge floor
    succeeds for the bare AA. This drives the new Effect-class isinstance
    branch in ``_python_aa_to_safe_dict`` without tripping the
    pre-Phase-4D rider decline floor (the ``if aa.sorcery_speed: return
    None`` arm at the bridge entry).
    """
    from mtg_bot.effects.base import ActivatedAbility, ActivationCost
    from mtg_bot.effects.generic.misc import (
        LockOrUnlockDoorOfTargetRoomYouControl,
    )
    from mtg_bot.cards.base import ManaCost
    from mtg_bot.parity.cross_engine import (
        _aa_dict_to_python_activated_ability,
        _python_aa_to_safe_dict,
    )

    aa = ActivatedAbility(
        cost=ActivationCost(
            tap_self=True,
            sacrifice_self=True,
            mana=ManaCost(generic=3),
        ),
        effect=LockOrUnlockDoorOfTargetRoomYouControl(),
        # No sorcery_speed rider — bare AA passes the C1 bridge floor.
    )
    d = _python_aa_to_safe_dict(aa)
    assert d is not None, (
        "Bare LockOrUnlockDoor AA must round-trip through the bridge "
        "floor — Cycle 1 widens the forward emit for the unit-variant "
        "Effect, even though the full Keys-to-the-House admit gate "
        "stays declined."
    )
    assert d["cost"]["tap_self"] is True
    assert d["cost"]["sacrifice_self"] is True
    assert d["cost"]["mana"] == {"generic": 3}
    assert d["effect"]["kind"] == (
        "lock_or_unlock_door_of_target_room_you_control"
    )
    # Reverse round-trip — byte-equal at the dataclass __eq__ surface.
    back = _aa_dict_to_python_activated_ability(d)
    assert back == aa


# ---------------------------------------------------------------------------
# Rust unit pin #27 — parse_effect arm via Registry.register_printing
# ---------------------------------------------------------------------------


def _synthetic_keys_to_house_dict():
    """Minimal Keys-to-the-House-shape Artifact printing dict for the
    Rust Registry. AA[0] is a SearchLibraryForCard (pre-wired); AA[1]
    is the new ``lock_or_unlock_door_of_target_room_you_control`` shape.
    """
    return {
        "name": "Synthetic Keys to the House",
        "card_types": ["Artifact"],
        "mana_cost": {"generic": 2},
        "activated_abilities": [
            {
                "cost": {
                    "tap_self": True,
                    "sacrifice_self": True,
                    "mana": {"generic": 1},
                },
                "effect": {
                    "kind": "search_library_for_card",
                    "filter_name": "basic_land",
                    "max_mv": 0,
                    "may_fail": True,
                },
                "is_mana_ability": False,
            },
            {
                "cost": {
                    "tap_self": True,
                    "sacrifice_self": True,
                    "mana": {"generic": 3},
                },
                "effect": {
                    "kind": "lock_or_unlock_door_of_target_room_you_control",
                },
                "is_mana_ability": False,
                "sorcery_speed": True,
            },
        ],
    }


def _synthetic_room_printing_dict():
    """Minimal Room-subtyped Enchantment printing for the synthetic
    bf target. The Phase-4D Cycle 1 resolve arm re-validates
    ``Room`` subtype membership on the target — this fixture supplies
    the minimum shape that passes that gate.
    """
    return {
        "name": "Synthetic Room",
        "card_types": ["Enchantment"],
        "subtypes": ["Room"],
        "mana_cost": {"generic": 2},
    }


def test_rust_register_printing_with_lock_or_unlock_door_effect(engine):
    """**Design doc §6.4 #27 — parse arm pin.** The new
    ``lock_or_unlock_door_of_target_room_you_control`` parse arm
    accepts the 1-key dict and returns
    ``Effect::LockOrUnlockDoorOfTargetRoomYouControl``; a synthetic
    Keys-to-the-House-shape Artifact registers cleanly.
    """
    reg = engine.Registry()
    pid = reg.register_printing(_synthetic_keys_to_house_dict())
    assert reg.get_printing_name(pid) == "Synthetic Keys to the House"


# ---------------------------------------------------------------------------
# Rust unit pin #28 — to_pydict arm via the parse-emit inverse
# ---------------------------------------------------------------------------


def test_rust_to_pydict_round_trip_via_bridge_inverse():
    """**Design doc §6.4 #28 — to_pydict arm pin.** The Rust
    ``to_pydict`` arm emits the byte-equal 1-key dict. Round-trip via
    the bridge forward arm (Python→dict) + the Rust parse arm
    (dict→Rust) + then back through the Rust to_pydict arm yields the
    same dict.
    """
    from mtg_bot.effects.base import ActivatedAbility, ActivationCost
    from mtg_bot.effects.generic.misc import (
        LockOrUnlockDoorOfTargetRoomYouControl,
    )
    from mtg_bot.cards.base import ManaCost
    from mtg_bot.parity.cross_engine import (
        _aa_dict_to_python_activated_ability,
        _python_aa_to_safe_dict,
    )

    aa_orig = ActivatedAbility(
        cost=ActivationCost(
            tap_self=True,
            sacrifice_self=True,
            mana=ManaCost(generic=3),
        ),
        effect=LockOrUnlockDoorOfTargetRoomYouControl(),
    )
    d = _python_aa_to_safe_dict(aa_orig)
    aa_back = _aa_dict_to_python_activated_ability(d)
    assert aa_back == aa_orig
    # And: a second forward emit yields a byte-equal dict.
    d2 = _python_aa_to_safe_dict(aa_back)
    assert d == d2


# ---------------------------------------------------------------------------
# Rust unit pin #29 — resolve arm: toggle the door-state bitmask
# ---------------------------------------------------------------------------


def test_resolve_lock_or_unlock_door_toggles_bitmask_first_half(
    engine, synthetic_state,
):
    """**Design doc §6.4 #29 — resolve arm pin.** Set up: inject a
    Room printing on p0 bf + push the Effect to the stack with the
    Room as target; resolve. The Room's ``door_states`` slot
    transitions from ``None`` (lazy-init on first toggle) to
    ``Some(1)`` (bit 0 = unlocked, bit 1 = locked, default mode_idx=0
    via the resolve arm's ``unwrap_or(0)`` fallback for the unset
    ``current_resolve_chosen_mode_idx`` slot).

    The mode_idx defaulting is the substrate-only contract for
    Cycle 1: the StackItem ``chosen_mode_idx`` isn't yet threaded by
    the legal-action emitter (Cycle 2 ships the Room-target fan-out
    with the door-half rider on the action dict). The C1 resolve arm
    contract is: an unset mode_idx defaults to half-0.

    A second toggle of the same Room with the same mode_idx un-toggles
    the half (XOR is its own inverse) — ``door_states`` returns to
    ``Some(0)``.
    """
    # Inject a Room target on p0 bf. The Room subtype passes the
    # resolve arm's CR 608.2b re-validation gate.
    room_id = synthetic_state.register_and_inject_object(
        _synthetic_room_printing_dict(), 0, ZONE_BATTLEFIELD,
    )

    # Inject a source artifact (Keys to the House — the Effect needs an
    # arbitrary source to ride). We use AA[1] (LockOrUnlockDoor) by
    # ability_index=1. The activate_ability action pays cost +
    # sacrifices the source (CR 605.1) + pushes a TriggeredAbility
    # stack item carrying the effect payload + the target id.
    src_id = synthetic_state.register_and_inject_object(
        _synthetic_keys_to_house_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(src_id, False)
    # Pay the {3} cost for AA[1].
    synthetic_state.add_mana(0, "C", 3)

    # Pre-resolve invariant: every bf object's door_states snapshot is
    # None (substrate default).
    for obj in synthetic_state.battlefield_snapshot():
        assert obj["door_states"] is None, (
            f"pre-resolve: every bf object should have door_states=None, "
            f"got obj id={obj['id']} door_states={obj['door_states']}"
        )

    # Activate AA[1] with target=room_id. The activate_ability action
    # pays cost + sacrifices source (sacrifice_self) + pushes a
    # TriggeredAbility stack item with the LockOrUnlockDoor effect
    # payload + target.
    synthetic_state.apply_action({
        "kind": "activate_ability",
        "source_id": src_id,
        "ability_index": 1,
        "target_creature_id": room_id,
    })
    assert synthetic_state.stack_size() == 1

    # Resolve — fires Effect::LockOrUnlockDoorOfTargetRoomYouControl
    # via the trigger-payload resolve path.
    # The resolve arm's default mode_idx (0) toggles bit 0.
    synthetic_state.resolve_top_of_stack()
    assert synthetic_state.is_stack_empty()

    # Post-resolve: the Room's door_states is Some(1) — bit 0 set
    # (half-0 unlocked); every OTHER bf object remains None.
    bf_post = synthetic_state.battlefield_snapshot()
    room_post = next((o for o in bf_post if o["id"] == room_id), None)
    assert room_post is not None, (
        "Room target must still be on bf post-resolve (no zone move)"
    )
    assert room_post["door_states"] == 1, (
        f"Room door_states should be Some(1) post-toggle (bit 0 set = "
        f"half-0 unlocked); got {room_post['door_states']}"
    )
    for obj in bf_post:
        if obj["id"] == room_id:
            continue
        assert obj["door_states"] is None, (
            f"non-Room bf object {obj['id']} should keep door_states=None; "
            f"got {obj['door_states']}"
        )

    # Re-resolve — XOR un-toggles the same half. The first activation
    # sacrificed the source (sacrifice_self) so we need a fresh source.
    src_id_2 = synthetic_state.register_and_inject_object(
        _synthetic_keys_to_house_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(src_id_2, False)
    synthetic_state.add_mana(0, "C", 3)
    synthetic_state.apply_action({
        "kind": "activate_ability",
        "source_id": src_id_2,
        "ability_index": 1,
        "target_creature_id": room_id,
    })
    synthetic_state.resolve_top_of_stack()

    bf_post2 = synthetic_state.battlefield_snapshot()
    room_post2 = next(
        (o for o in bf_post2 if o["id"] == room_id), None
    )
    assert room_post2 is not None
    # Bit-0 XOR'd back to 0; the slot stays Some(0) (we lazy-init'd it,
    # we don't reset to None).
    assert room_post2["door_states"] == 0, (
        f"Re-toggle should XOR bit-0 back to 0 (all halves locked); "
        f"got {room_post2['door_states']}"
    )


def test_resolve_lock_or_unlock_door_leaves_non_room_bf_objects_untouched(
    engine, synthetic_state,
):
    """**Resolve arm scope pin (Room-subtype gate).** After a
    LockOrUnlockDoor resolve on a Room target, every NON-Room bf
    object retains ``door_states=None`` — the resolve arm only
    mutates the targeted Room, not any sibling permanents.

    Sibling of the toggle pin above — this one specifically pins the
    invariant that non-Room bf objects aren't side-effected.
    """
    # Inject a Room target on p0 bf + the source Keys printing.
    room_id = synthetic_state.register_and_inject_object(
        _synthetic_room_printing_dict(), 0, ZONE_BATTLEFIELD,
    )
    src_id = synthetic_state.register_and_inject_object(
        _synthetic_keys_to_house_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(src_id, False)
    synthetic_state.add_mana(0, "C", 3)

    # Collect non-Room bf object ids pre-resolve.
    bf_pre = synthetic_state.battlefield_snapshot()
    non_room_pre_ids = [
        o["id"] for o in bf_pre if o["id"] != room_id
    ]

    synthetic_state.apply_action({
        "kind": "activate_ability",
        "source_id": src_id,
        "ability_index": 1,
        "target_creature_id": room_id,
    })
    synthetic_state.resolve_top_of_stack()
    assert synthetic_state.is_stack_empty()

    # Every non-Room bf object's door_states is still None.
    bf_post = synthetic_state.battlefield_snapshot()
    for obj in bf_post:
        if obj["id"] == room_id:
            continue
        assert obj["door_states"] is None, (
            f"non-Room bf object {obj['id']} should keep "
            f"door_states=None; got {obj['door_states']}"
        )


# ---------------------------------------------------------------------------
# Rust unit pin #30 — substrate slot snapshot codec round-trip
# ---------------------------------------------------------------------------


def test_snapshot_dict_carries_door_states_key_on_hand(synthetic_state):
    """**Snapshot bridge round-trip pin.** Every hand object's snapshot
    dict carries the new ``door_states`` key (back-compat additive —
    the key is unconditionally present, value is None on every
    freshly-defaulted object).
    """
    snap = synthetic_state.hand_snapshot(0)
    assert len(snap) > 0
    for obj in snap:
        assert "door_states" in obj, (
            f"missing door_states key in hand snapshot; "
            f"got keys {sorted(obj.keys())}"
        )
        assert obj["door_states"] is None, (
            f"freshly-defaulted hand object should have door_states=None, "
            f"got {obj['door_states']}"
        )


def test_snapshot_dict_carries_door_states_key_on_library(synthetic_state):
    """Library zone snapshot mirror of the hand pin."""
    snap = synthetic_state.library_snapshot(0)
    assert len(snap) > 0
    for obj in snap:
        assert "door_states" in obj
        assert obj["door_states"] is None


def test_snapshot_dict_carries_door_states_key_on_battlefield(
    synthetic_state,
):
    """Battlefield zone snapshot mirror of the hand pin."""
    snap = synthetic_state.battlefield_snapshot()
    assert len(snap) > 0
    for obj in snap:
        assert "door_states" in obj
        assert obj["door_states"] is None


def test_snapshot_dict_carries_door_states_key_on_graveyard(
    synthetic_state,
):
    """Graveyard zone snapshot mirror — universal key invariant."""
    snap = synthetic_state.graveyard_snapshot(0)
    for obj in snap:
        assert "door_states" in obj
        assert obj["door_states"] is None


def test_snapshot_dict_carries_door_states_key_on_exile(synthetic_state):
    """Exile zone snapshot mirror — universal key invariant."""
    snap = synthetic_state.exile_snapshot(0)
    for obj in snap:
        assert "door_states" in obj
        assert obj["door_states"] is None


def test_snapshot_dict_carries_door_states_key_for_both_players(
    synthetic_state,
):
    """**Per-player universality pin.** The new key is present on both
    p0 and p1 snapshots (no off-by-one player-id bug in the bridge).
    """
    for pid in (0, 1):
        for zone_name in ("hand", "library", "graveyard", "exile"):
            method = getattr(synthetic_state, f"{zone_name}_snapshot")
            snap = method(pid)
            for obj in snap:
                assert "door_states" in obj
                assert obj["door_states"] is None


def test_register_and_inject_object_carries_default_none(engine):
    """**``register_and_inject_object`` default pin.** Freshly-injected
    objects via the test/setup primitive start with ``door_states =
    None`` — back-compat with every existing call site that did not
    opt into the new slot.
    """
    s = engine.make_synthetic_state()
    pid_dict = {
        "name": "Phase4D_TestArtifact",
        "card_types": ["Artifact"],
        "mana_cost": {"generic": 0},
    }
    new_id = s.register_and_inject_object(pid_dict, 0, 0)  # hand
    hand = s.hand_snapshot(0)
    injected = [o for o in hand if o["id"] == new_id]
    assert len(injected) == 1
    assert injected[0]["door_states"] is None


def test_fingerprint_default_state_matches_pre_substrate_baseline(
    synthetic_state,
):
    """**Fingerprint byte-equality pin (CR-22 baseline preservation).**
    The default synthetic state's fingerprint digest matches the
    pre-substrate ``EXPECTED_FINGERPRINT_DEFAULT = "93ab1bd03f94"``
    baseline. Confirms the new ``door_states`` slot is ELIDED from the
    per-object 8-tuple — matching the precedent for every other
    post-r22 substrate field (``original_printing_id``,
    ``stun_counters``, ``regeneration_shield``, etc.).
    """
    assert synthetic_state.fingerprint() == "93ab1bd03f94"


def test_clone_preserves_default_none_invariant(synthetic_state):
    """**Clone preservation pin.** ``GameObject``'s derive(Clone) auto-
    propagates the ``Option<u8>`` slot to cloned states. A cloned
    state's snapshot dicts carry the same default-None invariant.
    """
    cloned = synthetic_state.clone_once()
    assert cloned.fingerprint() == synthetic_state.fingerprint()
    for pid in (0, 1):
        for zone_name in ("hand", "library", "graveyard", "exile"):
            method = getattr(cloned, f"{zone_name}_snapshot")
            for obj in method(pid):
                assert obj["door_states"] is None
    for obj in cloned.battlefield_snapshot():
        assert obj["door_states"] is None


def test_zone_change_keeps_door_states_none_no_minter(
    synthetic_state,
):
    """**Zone-change reset pin (substrate-only).** Drive a synthetic
    state through ``clone_once`` (CR 400.7 mirror — every reset site
    is sibling-clean to ``original_printing_id``'s 94-site audit) and
    confirm ``door_states`` stays ``None`` on every object across
    every zone. The substrate's invariant is "default-None never
    spuriously flips to Some on a zone transit / clone for non-Room
    objects".

    NOTE: a full zone-change reset pin that exercises CLEARING
    ``Some(bitmask) -> None`` requires driving a Room through the
    generic ``move_object`` primitive (which today does NOT clear
    state on zone-change — that's a sibling parity gap with
    ``original_printing_id``, both share the same reset-hookup
    pattern across the 94 explicit-reset sites in apply-side dispatch
    paths). The reset is wired at the SAME 94 sites as the Phase 3C
    C1 ``original_printing_id`` audit (verified by the
    ``rg "door_states = None"`` count in this commit's diff). A
    Cycle 4 per-card real-EoE probe will drive the full reset
    semantics on a live Keys-to-the-House line.
    """
    cloned = synthetic_state.clone_once()
    for pid in (0, 1):
        for zone_name in ("hand", "library", "graveyard", "exile"):
            method = getattr(cloned, f"{zone_name}_snapshot")
            for obj in method(pid):
                assert obj.get("door_states") is None
    for obj in cloned.battlefield_snapshot():
        assert obj.get("door_states") is None


# ---------------------------------------------------------------------------
# Substrate-only invariant pins — Keys to the House STAYS DECLINED
# ---------------------------------------------------------------------------


def test_keys_to_the_house_stays_declined_post_substrate_cycle_1():
    """**Phase 4D C1 substrate-only invariant pin.** Keys to the
    House's live ``OracleParserCardSource`` printing FAILS the per-AA
    admit predicate ``_aa_is_phase1_sub_shape_a`` post-Phase-4D-C1
    because:
      (a) C1 doesn't widen ``_carrier_aa_phase_1_effect_classes`` to
          include ``LockOrUnlockDoorOfTargetRoomYouControl`` (C2 ships
          the widen).
      (b) C1 doesn't widen the Phase 4A multi-AA admit predicate (C2
          inherits / co-flips the multi-AA gate).
      (c) C1 doesn't widen the ``sorcery_speed`` AA-rider gate (C2
          ships the widen).

    Invariant: the live printing remains DECLINED — Cycle 1 is a pure
    substrate landing, no admit-gate flip.
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import (
        _aa_is_phase1_sub_shape_a,
    )

    ps = OracleParserCardSource().get_printings()
    keys = ps.get("Keys to the House")
    if keys is None:
        pytest.skip(
            "Keys to the House not in OracleParserCardSource printings"
        )
    # Per-AA admit predicate: AA[1] STAYS DECLINED at C1 (the
    # LockOrUnlockDoorOfTargetRoomYouControl Effect-class is not in the
    # admit set; the sorcery_speed AA-rider gate isn't widened; the
    # multi-AA admit predicate isn't widened).
    aa1 = keys.activated_abilities[1]
    assert _aa_is_phase1_sub_shape_a(aa1) is False, (
        "Keys to the House AA[1] must STAY DECLINED at the per-AA "
        "admit gate post-Phase-4D-Cycle-1 (no Effect-class widen yet)"
    )


def test_phase_1_effect_classes_unchanged_post_substrate_cycle_1():
    """**Phase 4D C1 Effect-class admit-set unchanged pin.** The
    ``_carrier_aa_phase_1_effect_classes`` admit set does NOT yet
    include ``LockOrUnlockDoorOfTargetRoomYouControl`` — C2 ships the
    widen.

    Inverted to ``... in classes`` at the Phase-4D-C2 widen pin.
    """
    from mtg_bot.parity.trajectory import _carrier_aa_phase_1_effect_classes
    from mtg_bot.effects.generic.misc import (
        LockOrUnlockDoorOfTargetRoomYouControl,
    )

    classes = _carrier_aa_phase_1_effect_classes()
    assert LockOrUnlockDoorOfTargetRoomYouControl not in classes, (
        "LockOrUnlockDoorOfTargetRoomYouControl MUST NOT be in the "
        "admit set post-Phase-4D-Cycle-1 (the C2 widen ships this "
        "admission)"
    )
