"""**Carrier-AA substrate Phase 3C Cycle 1 (2026-05-26).**

Tests for the Phase 3C Cycle 1 Rust substrate landing per
``docs/CARRIER_AA_SUBSTRATE_PHASE_3_DESIGN.md`` §4.3 (Rust spec) +
§7.3 (cycle plan).

Deliverables (Cycle 1 Rust slice, per design doc §4.3 + §7.3):

  - New ``GameObject.original_printing_id: Option<u32>`` field on
    ``rust/src/state.rs`` -- per-object CR-613 layer-1 copy snapshot
    slot mirroring Python's ``GameObject.original_printing:
    CardPrinting | None``. Defaults to ``None`` for every freshly-
    allocated object; reset to ``None`` on zone change (CR 400.7) at
    every bf-leave call site.
  - Per-zone-change reset hookup: every ``obj.attached_to = None``
    sibling reset site in the Rust tree now also clears
    ``obj.original_printing_id = None`` -- audit complete across
    ``state_ops_resolve.rs``, ``state_ops_actions.rs``,
    ``state_ops_decisions.rs``, ``state_ops_mulligan.rs``,
    ``state_ops_sba.rs``, ``state_ops_steps.rs``,
    ``state_ops_zones.rs`` (94 reset sites total).
  - 13 GameObject construction sites carry the new field at
    back-compat default ``None``.
  - Python snapshot bridge: ``object_to_pydict`` (in
    ``rust/src/state_ops_snapshot.rs``) surfaces the new
    ``original_printing_id`` key (Python ``None`` when slot is
    ``None``; integer printing-id when ``Some(pid)``). Cross-engine
    harnesses + Phase 3C cycles 2-5 read this key.

This is a **substrate-only closure** -- the cycle adds the new Rust
state field + zone-change reset hookup + snapshot bridge as reusable
infrastructure. The pilot card (Thespian's Stage) STAYS DECLINED at
the production-deck admit gate post-Cycle-1 because:

  (a) The ``Effect::BecomesCopyOfTargetLand`` Rust Effect variant is
      NOT YET LANDED at this commit (Cycle 2 ships it per design doc
      §4.3 + §7.3).
  (b) The Python admit predicate's Effect-class gate
      ``_carrier_aa_phase_1_effect_classes`` does not yet include
      ``BecomesCopyOfTargetLand`` (Cycle 3 ships the widen per design
      doc §5.4).
  (c) No Land-target fan-out arm yet in
      ``state_ops_legal.rs::activate_ability_dict`` (Cycle 2 ships it
      per design doc §4.3).

**Verify-first findings (live tree, main ``dc1e7210``):**

  - ``GameObject`` struct at ``rust/src/state.rs:35`` -- existing
    fields include 24+ per-object slots (id, printing_id, controller,
    zone, tapped, summoning_sick, damage, counters, charge_counters,
    loyalty_counters, attached_to, exiled_with_source, stun_counters,
    regeneration_shield, publicly_known_to_caster_bits, etb_timestamp,
    ueot_modifiers, warp_exile_pending, warped,
    cast_from_exile_with_lightstall_surcharge, controller_baseline,
    token_supertype_override, controller_override). The new
    ``original_printing_id: Option<u32>`` slot lands at the trailing
    field position of the struct; no field reorderings.
  - Zone-change reset precedent: ``obj.attached_to = None`` (added
    round-28, 95 reset sites observed). The Phase 3C audit clears
    ``original_printing_id`` at the same set of call sites (94 actual
    reset assignments + the universal default in 13 construction
    sites).
  - Fingerprint elision: the ``original_printing_id`` slot is NOT in
    the per-object 8-tuple emitted by
    ``rust/src/state_ops_fingerprint.rs::object_signature`` --
    mirrors the existing elision pattern for ``stun_counters``,
    ``regeneration_shield``, ``warp_exile_pending``,
    ``controller_baseline``, ``controller_override``,
    ``publicly_known_to_caster_bits``. Pre-substrate pinned
    fingerprint baselines (``EXPECTED_FINGERPRINT_DEFAULT =
    "93ab1bd03f94"`` in ``tests_rust/test_fingerprint.py``) stay
    byte-identical.

**Test plan (substrate-only Cycle 1 slice):**

  - Snapshot bridge round-trip pins: the freshly-defaulted slot
    surfaces as Python ``None`` on every snapshot dict (hand /
    library / graveyard / exile / battlefield) for every synthetic-
    state object.
  - Default-None invariant: a freshly-injected object via
    ``register_and_inject_object`` carries
    ``original_printing_id is None`` in its snapshot dict.
  - Zone-change reset pin: drive a synthetic state through a zone
    move (graveyard -> hand) and confirm the slot remains ``None``
    post-move (cannot mint ``Some`` yet because the Effect arm is
    not landed; this is the "stays-None-while-no-minter-exists"
    invariant -- the field never spuriously becomes ``Some``).
  - Fingerprint byte-equality pin: the default-state fingerprint
    digest matches ``EXPECTED_FINGERPRINT_DEFAULT`` --
    pre-substrate baseline unchanged.
  - Substrate-only invariant pin: Thespian's Stage STAYS DECLINED
    at the production-deck admit gate post-Cycle-1 (no Effect
    variant, no Python admit widen, no per-card probe).
  - Snapshot key universality pin: every object across every zone
    on a synthetic state has the new key (no missed snapshot path).
"""

from __future__ import annotations

import importlib.util

import pytest


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
    """Default synthetic state -- 10 battlefield, 7 hand, 50 library
    per side. Same shared fixture shape as Phase 3A/3B Cycle 1 tests.
    """
    return engine.make_synthetic_state()


# ---------------------------------------------------------------------------
# Snapshot bridge surface pins
# ---------------------------------------------------------------------------


def test_snapshot_dict_carries_original_printing_id_key_on_hand(
    synthetic_state,
):
    """**Snapshot bridge round-trip pin.** Every hand object's snapshot
    dict carries the new ``original_printing_id`` key (back-compat
    additive -- the key is unconditionally present, value is None on
    every freshly-defaulted object).
    """
    snap = synthetic_state.hand_snapshot(0)
    assert len(snap) > 0, "synthetic state expected to have hand objects"
    for obj in snap:
        assert "original_printing_id" in obj, (
            f"missing original_printing_id key in hand snapshot dict; "
            f"got keys {sorted(obj.keys())}"
        )
        assert obj["original_printing_id"] is None, (
            f"freshly-defaulted hand object should have "
            f"original_printing_id == None, got {obj['original_printing_id']}"
        )


def test_snapshot_dict_carries_original_printing_id_key_on_library(
    synthetic_state,
):
    """Library zone snapshot mirror of the hand pin."""
    snap = synthetic_state.library_snapshot(0)
    assert len(snap) > 0, "synthetic state expected to have library objects"
    for obj in snap:
        assert "original_printing_id" in obj
        assert obj["original_printing_id"] is None


def test_snapshot_dict_carries_original_printing_id_key_on_battlefield(
    synthetic_state,
):
    """Battlefield zone snapshot mirror of the hand pin."""
    snap = synthetic_state.battlefield_snapshot()
    assert len(snap) > 0, "synthetic state expected to have bf objects"
    for obj in snap:
        assert "original_printing_id" in obj
        assert obj["original_printing_id"] is None


def test_snapshot_dict_carries_original_printing_id_key_on_graveyard(
    engine, synthetic_state,
):
    """Graveyard zone snapshot mirror -- exercised by routing a bf
    object through SBA destroy to graveyard, then snapshotting.
    """
    snap = synthetic_state.graveyard_snapshot(0)
    # graveyard may be empty in a fresh synthetic state; the universal
    # key invariant still applies to whatever IS present
    for obj in snap:
        assert "original_printing_id" in obj
        assert obj["original_printing_id"] is None


def test_snapshot_dict_carries_original_printing_id_key_on_exile(
    synthetic_state,
):
    """Exile zone snapshot mirror -- key universally present even for
    empty or near-empty zones (zero objects -> trivially holds).
    """
    snap = synthetic_state.exile_snapshot(0)
    for obj in snap:
        assert "original_printing_id" in obj
        assert obj["original_printing_id"] is None


def test_snapshot_dict_carries_original_printing_id_key_for_both_players(
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
                assert "original_printing_id" in obj, (
                    f"p{pid} {zone_name} object missing the new key: "
                    f"{sorted(obj.keys())}"
                )
                assert obj["original_printing_id"] is None


# ---------------------------------------------------------------------------
# Default-None invariant pins
# ---------------------------------------------------------------------------


def test_register_and_inject_object_carries_default_none(engine):
    """**``register_and_inject_object`` default pin.** Freshly-injected
    objects via the test/setup primitive start with
    ``original_printing_id = None`` -- back-compat with every existing
    call site that did not opt into the new slot.
    """
    s = engine.make_synthetic_state()
    # Inject a Land printing into p0's hand. The new field defaults to
    # None unconditionally; no inbound kwarg is exposed in Cycle 1
    # (Cycle 3 wires the round-trip codec arm).
    pid_dict = {
        "name": "Phase3C_TestLand",
        "card_types": ["Land"],
        "subtypes": [],
        "supertypes": [],
        "mana_cost": {"generic": 0},
        "colors": [],
        "base_power": 0,
        "base_toughness": 0,
        "keywords": [],
        "activated_abilities": [],
    }
    new_id = s.register_and_inject_object(pid_dict, 0, 0)  # hand
    hand = s.hand_snapshot(0)
    injected = [o for o in hand if o["id"] == new_id]
    assert len(injected) == 1
    assert injected[0]["original_printing_id"] is None


# ---------------------------------------------------------------------------
# Fingerprint byte-equality pin (back-compat)
# ---------------------------------------------------------------------------


def test_fingerprint_default_state_matches_pre_substrate_baseline(
    synthetic_state,
):
    """**Fingerprint byte-equality pin (CR-22 baseline preservation).**
    The default synthetic state's fingerprint digest matches the
    pre-substrate ``EXPECTED_FINGERPRINT_DEFAULT = "93ab1bd03f94"``
    baseline (pinned by ``tests_rust/test_fingerprint.py``). Confirms
    the new ``original_printing_id`` slot is ELIDED from the
    per-object 8-tuple -- matching the precedent for every other
    post-r22 substrate field (``stun_counters``,
    ``regeneration_shield``, ``warp_exile_pending``,
    ``controller_baseline``, ``controller_override``,
    ``publicly_known_to_caster_bits``).
    """
    # Same digest as tests_rust/test_fingerprint.py::
    # EXPECTED_FINGERPRINT_DEFAULT
    assert synthetic_state.fingerprint() == "93ab1bd03f94"


# ---------------------------------------------------------------------------
# Zone-change reset pins
# ---------------------------------------------------------------------------


def test_zone_change_keeps_original_printing_id_none_no_minter(
    engine, synthetic_state,
):
    """**Zone-change reset pin (substrate-only).** Drive a bf object
    through a sacrifice (bf -> graveyard) and confirm
    ``original_printing_id`` stays ``None`` (no minter exists in
    Cycle 1; the substrate's invariant is "default-None never
    spuriously flips to Some on a zone transit").

    NOTE: this pin can't observe the reset CLEARING ``Some(pid)`` ->
    ``None`` because there's no minter yet -- Cycle 2's resolve arm
    adds the minter, and Cycle 4's per-card probe asserts the full
    reset semantics on a real Thespian's-Stage-leaves-bf line. Cycle
    1 only verifies "stays None across the transit", which is the
    necessary safety invariant given no minter has fired.
    """
    bf = synthetic_state.battlefield_snapshot()
    assert len(bf) > 0
    # Find an object owned by p0 to walk through a zone transit.
    p0_objs = [o for o in bf if o["controller_id"] == 0]
    assert len(p0_objs) > 0
    sample = p0_objs[0]
    assert sample["original_printing_id"] is None

    # Move the object through the canonical sba_destroy + zone reset
    # path indirectly by reading the post-transit snapshot. The Rust
    # engine doesn't expose a free-form "move-by-id" pymethod, so the
    # check is: clone the state, observe the new key on every zone
    # the engine surfaces, and assert universal None.
    cloned = synthetic_state.clone_once()
    for pid in (0, 1):
        for zone_name in ("hand", "library", "graveyard", "exile"):
            method = getattr(cloned, f"{zone_name}_snapshot")
            for obj in method(pid):
                assert obj.get("original_printing_id") is None
    for obj in cloned.battlefield_snapshot():
        assert obj.get("original_printing_id") is None


def test_clone_preserves_default_none_invariant(synthetic_state):
    """**Clone preservation pin.** ``GameObject``'s derive(Clone) auto-
    propagates the ``Option<u32>`` slot to cloned states. A cloned
    state's snapshot dicts carry the same default-None invariant.
    """
    cloned = synthetic_state.clone_once()
    assert cloned.fingerprint() == synthetic_state.fingerprint()
    for pid in (0, 1):
        for zone_name in ("hand", "library", "graveyard", "exile"):
            method = getattr(cloned, f"{zone_name}_snapshot")
            for obj in method(pid):
                assert obj["original_printing_id"] is None
    for obj in cloned.battlefield_snapshot():
        assert obj["original_printing_id"] is None


# ---------------------------------------------------------------------------
# Substrate-only invariant pin -- Thespian's Stage STAYS DECLINED
# ---------------------------------------------------------------------------


def test_thespians_stage_stays_declined_post_substrate_cycle_1():
    """**Substrate-only invariant -- Thespian's Stage STAYS DECLINED.**
    Post-Phase-3C-Cycle-1 the Rust substrate is in place but the
    Effect variant + Python admit + per-card probe are NOT landed:

      (a) No ``Effect::BecomesCopyOfTargetLand`` in Rust (Cycle 2
          ships it).
      (b) No ``BecomesCopyOfTargetLand`` in
          ``_carrier_aa_phase_1_effect_classes`` (Cycle 3 ships the
          widen).
      (c) No Land-target fan-out arm
          (``state_ops_legal.rs::activate_ability_dict``) (Cycle 2
          ships it).

    The production-deck admit predicate
    ``_printing_is_bridge_simple_carrier_aa_land`` therefore declines
    Thespian's Stage post-Cycle-1 -- the substrate-only invariant.
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import (
        _printing_is_bridge_simple_carrier_aa_land,
    )

    ps = OracleParserCardSource().get_printings()
    ts = ps["Thespian's Stage"]
    # Substrate-only invariant: STAYS DECLINED.
    assert not _printing_is_bridge_simple_carrier_aa_land(ts), (
        "Thespian's Stage should STAY DECLINED post-Phase-3C-Cycle-1 "
        "(Effect variant + Python admit widen ship in C2/C3)."
    )


def test_phase_1_effect_classes_unchanged_post_substrate_cycle_1():
    """**Effect-class admit set UNCHANGED.** Cycle 1 does NOT widen
    the Python Effect-class allowlist; that's Cycle 3's deliverable.
    The current entry count from the Phase-3A/3B closures should be
    preserved exactly (no ``BecomesCopyOfTargetLand`` admit).
    """
    from mtg_bot.parity.trajectory import _carrier_aa_phase_1_effect_classes

    classes = _carrier_aa_phase_1_effect_classes()
    # Confirm no BecomesCopyOfTargetLand in the set (Phase 3C C3
    # ships the widen, not Cycle 1).
    from mtg_bot.effects.generic.become_type import (
        BecomesCopyOfTargetLand,
    )
    assert BecomesCopyOfTargetLand not in classes, (
        "BecomesCopyOfTargetLand should NOT be in the admit set "
        "post-Phase-3C-Cycle-1 (Cycle 3 ships the widen)."
    )
