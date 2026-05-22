"""Control-change-UEOT subsystem — Cycle 2 (gameplay-decision reroutes).

Spec: lane brief (2026-05-21). The Cycle 1 substrate (per-object
``controller_override`` field + ``effective_controller_id`` helper +
cleanup-step drain) landed in commit ``3bc47355`` without rewiring any
internal Rust read site through the helper. Cycle 2 reroutes the
**gameplay-decision** raw ``.controller`` read sites in
``rust/src/state_ops_legal.rs`` / ``state_ops_combat.rs`` /
``state_ops_cast.rs`` to consult ``effective_controller_id`` so a UEOT
control-grant (the future Mutinous Massacre / Systems Override mint
sites — Cycle 4) flips legal-target predicates, dynamic-P/T formula
resolution, lifelink credit, and Aura-host eligibility on the same turn.

Cycle 2 is **substrate-only**: every reroute is back-compat byte-
equivalent today (no live mint site exists yet, so
``controller_override.is_none()`` for every object in production, and
``effective_controller_id(o) == o.controller``). The tests below
demonstrate the rerouted decision-site flips its answer when an
override IS minted via the Cycle 1 Python primitive
``grant_control_change_ueot``, and reverts after the cleanup-step
drain.

**Scope of Cycle 2 reroutes** (kept narrow on purpose — see
``docs/SEARCH_LIMITATIONS.md`` §1):

- ``state_ops_legal.rs``:
  - ``BiosynthicBurstEffect`` legal-target predicate (Tractor Beam
    follow-up; "any creature you control" satisfiability).
  - ``PutChargeCountersOnTargetSpacecraftOrPlanetYouControl``
    legal-target predicate (Drill Too Deep mode 0).
  - ``DiplomaticRelationsEffect`` 2-slot satisfiability ("my creature
    / opp's creature" bucketing).
- ``state_ops_combat.rs``:
  - ``dynamic_base_pt_pub`` — both the subject's controller lookup AND
    the per-other-permanent "controlled by same player" predicate
    (Harmonious Grovestrider; "P = T = lands controlled by obj's
    controller").
  - ``battlefield_creature_controller`` — used by
    ``deal_combat_damage`` for lifelink credit and damage-source
    attribution.
- ``state_ops_cast.rs``:
  - Diplomatic Relations cast-time 2-slot target binding.
  - ``PutChargeCountersOnTargetSpacecraftOrPlanetYouControl`` cast-
    time target binding.
  - Additional-cost "creature you control" pick.
  - Aura cast-time ``yours_only`` host-eligibility filter.

**Kept raw on purpose** (NOT rerouted this cycle; logged in
``docs/SEARCH_LIMITATIONS.md``):

- ``state_ops_snapshot.rs`` / ``state_ops_fingerprint.rs`` — identity
  serialization MUST observe the printed/Aura-cached controller, NOT
  the transient override (the override is a separate snapshot key per
  Cycle 1).
- ``state_ops_sba.rs`` SBA destruction graveyard routing (lines 615 /
  694 / 699 / 776-782): the existing code routes corpses to the
  CONTROLLER's graveyard rather than the OWNER's (intentional first-
  slice deviation from CR 400.6, documented inline). Override-aware
  reroute would compound that gap; left as the existing zone-routing
  read until the "destination = owner not controller" slice lands.
- ``state_ops_resolve.rs`` source-controller multi-zone scans (~30+
  sites) — Cycle 2 left raw to keep the patch surface small; the bf
  branch of those scans would also be back-compat-equivalent reroutes
  but each one touches a different Effect arm. Carried to a follow-up
  if the C3 bridge round-trip or C4 mint sites exercise them.
- ``StackItem.controller`` reads (``state_ops_priority.rs``,
  ``state_ops_stack.rs``, ``state_ops_counterspell.rs:155``) — a
  separate field on a separate struct; UEOT override is a GameObject
  property, not a StackItem property. KEEP RAW.
- Constructor writes (``obj.controller = X`` in
  ``state_ops_cast.rs``, ``state_ops_zones.rs``, ``state_ops_sba.rs``
  Aura layer-2 swap, ``state_ops_decisions.rs``, ``state_ops_combat.rs``
  bf-swap, ``state_ops_resolve.rs`` reanimate/ETB) — WRITES, never
  reads; not in scope.

**Tests cover:**

1. Dynamic-P/T reroute (Harmonious Grovestrider):
   - Pre-grant: Grove on P0's bf with 0 lands → P=T=0.
   - P0 controls 3 Forests, P1 controls 0 → P=T=3 (counting P0's
     lands, since P0 controls the Grove).
   - Now P1 grants control of the Grove (UEOT) and ALSO P1 controls
     2 Mountains. P=T should flip to 2 (counting P1's lands, since
     P1 now controls the Grove via override) — NOT 5.
   - After cleanup drain: P=T reverts to 3 (P0's lands counted
     again).
2. Effective-controller helper round-trip through cleanup (sanity
   that the override is the path the rerouted reads consult).
3. Cleanup summary reports drain count when override was minted on
   a creature whose P/T was being rerouted-resolved.
"""

from __future__ import annotations

import importlib
import importlib.util

import pytest


ZONE_HAND = 0
ZONE_LIBRARY = 1
ZONE_BATTLEFIELD = 2


def _require_engine():
    if importlib.util.find_spec("mtg_bot_engine") is None:
        pytest.skip("mtg_bot_engine PyO3 extension not installed")


def _fresh_state():
    import mtg_bot_engine
    return mtg_bot_engine.make_synthetic_state(0, 0, 0)


def _grove_dict():
    """Synthetic Harmonious Grovestrider — dynamic-PT formula
    creature whose P/T = lands the *controller* controls. The Rust
    dispatch table at ``state_ops_combat.rs::dynamic_base_pt_pub``
    recognises ``"harmonious_grovestrider"``."""
    return {
        "name": "Harmonious Grovestrider",
        "mana_cost": {"generic": 3, "G": 2},
        "card_types": ["Creature"],
        "subtypes": ["Plant"],
        "power": 0,  # placeholder — dynamic-PT supersedes.
        "toughness": 0,
        "keywords": [],
        "dynamic_pt_formula": "harmonious_grovestrider",
    }


def _land_dict(name="Forest"):
    return {
        "name": name,
        "mana_cost": {},
        "card_types": ["Land"],
        "supertypes": ["Basic"],
        "subtypes": [],
        "keywords": [],
    }


# ---------------------------------------------------------------------------
# Dynamic-P/T reroute (state_ops_combat.rs::dynamic_base_pt_pub)
# ---------------------------------------------------------------------------


def test_grovestrider_dynamic_pt_flips_under_ueot_override():
    """The Cycle 2 reroute in ``dynamic_base_pt_pub`` consults
    ``effective_controller_id`` for BOTH the subject's controller
    lookup AND the per-other-permanent "controlled by same player"
    predicate. A Grovestrider on P0's bf normally reads P=T = (P0's
    land count). Grant UEOT control to P1 — P=T should switch to
    (P1's land count) because the effective controller is now P1.
    Drain the override at cleanup — P=T reverts to P0's land count.

    Substrate-only invariant: pre-grant the effective controller
    equals the printed controller, so the rerouted reads are byte-
    equivalent to pre-Cycle-2."""
    _require_engine()
    state = _fresh_state()
    # P0's Grove.
    grove_id = state.register_and_inject_object(
        _grove_dict(), 0, ZONE_BATTLEFIELD,
    )
    # P0 controls 3 Forests; P1 controls 2 Mountains. Distinct counts
    # so the flip is observable.
    for _ in range(3):
        state.register_and_inject_object(
            _land_dict("Forest"), 0, ZONE_BATTLEFIELD,
        )
    for _ in range(2):
        state.register_and_inject_object(
            _land_dict("Mountain"), 1, ZONE_BATTLEFIELD,
        )
    # Pre-grant: Grove's P=T = P0's land count = 3.
    assert state.effective_power(grove_id) == 3
    assert state.effective_toughness(grove_id) == 3
    # Mint UEOT override: P1 takes control of the Grove.
    assert state.grant_control_change_ueot(grove_id, 1) is True
    assert state.effective_controller_id(grove_id) == 1
    # POST-grant: Grove's P=T = P1's land count = 2 (NOT 3 — the
    # reroute now reads P1 as the controller and counts P1's lands).
    # This is the load-bearing assertion of the Cycle 2 reroute.
    assert state.effective_power(grove_id) == 2, (
        "dynamic_base_pt subject-controller reroute failed: "
        f"expected 2 (P1's lands), got {state.effective_power(grove_id)}"
    )
    assert state.effective_toughness(grove_id) == 2
    # Drain via cleanup: override is reset back to None; effective
    # controller reverts to P0; P=T should be 3 again.
    summary = state.cleanup_step_for_active_player()
    assert summary["controller_overrides_cleared"] == 1
    assert state.effective_controller_id(grove_id) == 0
    assert state.effective_power(grove_id) == 3, (
        "dynamic_base_pt post-cleanup-drain revert failed: "
        f"expected 3, got {state.effective_power(grove_id)}"
    )
    assert state.effective_toughness(grove_id) == 3


def test_grovestrider_per_other_permanent_predicate_uses_effective():
    """The inner ``effective_controller_id(bf_obj) != controller``
    filter in ``dynamic_base_pt_pub``'s formula loop — counts ONLY
    lands whose effective controller equals the Grovestrider's
    effective controller.

    Mint two overrides:
    1. P1 takes control of one of P0's Forests (UEOT). That Forest's
       effective controller is now P1; should be counted toward P1's
       land tally, NOT P0's.
    2. P1 takes control of the Grovestrider (UEOT). Grove's
       effective controller = P1.

    With (1) + (2) active: P1 effectively controls 1 stolen Forest
    + 0 native lands; the Grove reads P=T=1 (NOT 3, NOT 2).
    """
    _require_engine()
    state = _fresh_state()
    grove_id = state.register_and_inject_object(
        _grove_dict(), 0, ZONE_BATTLEFIELD,
    )
    forest_ids = [
        state.register_and_inject_object(
            _land_dict("Forest"), 0, ZONE_BATTLEFIELD,
        )
        for _ in range(3)
    ]
    # Mint override on one Forest first — change-of-control of the
    # Forest itself flips THAT permanent's effective controller.
    assert state.grant_control_change_ueot(forest_ids[0], 1) is True
    # Then mint override on the Grove. Now BOTH the subject and one
    # of the candidate lands have effective_controller=1.
    assert state.grant_control_change_ueot(grove_id, 1) is True
    # Grove's effective controller = 1; lands whose effective
    # controller = 1: just the stolen Forest. P=T=1.
    assert state.effective_power(grove_id) == 1, (
        "dynamic_base_pt per-permanent predicate reroute failed: "
        f"expected 1 (only the stolen Forest counts for P1), got "
        f"{state.effective_power(grove_id)}"
    )
    assert state.effective_toughness(grove_id) == 1
    # Cleanup drains BOTH overrides.
    summary = state.cleanup_step_for_active_player()
    assert summary["controller_overrides_cleared"] == 2
    assert state.effective_controller_id(grove_id) == 0
    assert state.effective_controller_id(forest_ids[0]) == 0
    # P=T reverts to P0's 3 native Forests.
    assert state.effective_power(grove_id) == 3
    assert state.effective_toughness(grove_id) == 3


# ---------------------------------------------------------------------------
# Helper-direct reroute sanity (Cycle 1 helper, Cycle 2 plumbing)
# ---------------------------------------------------------------------------


def test_effective_controller_helper_round_trip_through_cleanup():
    """Belt-and-suspenders sanity that the helper round-trips through
    the cleanup-step drain: grant → effective flips → cleanup →
    effective reverts. This is the load-bearing read path that every
    Cycle 2 reroute consults. (Cycle 1 covers this via the standalone
    drain primitive; Cycle 2 re-asserts it through the SAME
    primitive that the rerouted decision-site reads now consult.)"""
    _require_engine()
    state = _fresh_state()
    bears_id = state.register_and_inject_object(
        {
            "name": "Bears",
            "mana_cost": {"generic": 1, "G": 1},
            "card_types": ["Creature"],
            "subtypes": ["Bear"],
            "power": 2,
            "toughness": 2,
            "keywords": [],
        },
        0,
        ZONE_BATTLEFIELD,
    )
    assert state.effective_controller_id(bears_id) == 0
    state.grant_control_change_ueot(bears_id, 1)
    assert state.effective_controller_id(bears_id) == 1
    summary = state.cleanup_step_for_active_player()
    assert summary["controller_overrides_cleared"] == 1
    assert state.effective_controller_id(bears_id) == 0


def test_cleanup_summary_counts_grove_override_drain():
    """When a UEOT override is minted on a Grovestrider mid-turn
    (the canonical Cycle 4 mint shape — Mutinous Massacre steals
    a creature with dynamic P/T), the cleanup summary surfaces a
    ``controller_overrides_cleared: 1`` count. The drain is a
    Cycle 1 invariant; this test composes with the Cycle 2 reroute
    so we know the value path (effective-controller-aware P/T) and
    the drain path (cleanup resets) compose."""
    _require_engine()
    state = _fresh_state()
    grove_id = state.register_and_inject_object(
        _grove_dict(), 0, ZONE_BATTLEFIELD,
    )
    state.register_and_inject_object(
        _land_dict("Forest"), 0, ZONE_BATTLEFIELD,
    )
    state.grant_control_change_ueot(grove_id, 1)
    summary = state.cleanup_step_for_active_player()
    assert summary["controller_overrides_cleared"] == 1
    # Sanity: no leftover override.
    assert state.effective_controller_id(grove_id) == 0
