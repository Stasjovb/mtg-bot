"""**Carrier-AA substrate Phase 3C Cycle 2 (2026-05-26).**

Tests for the Phase 3C Cycle 2 Rust slice landing per
``docs/CARRIER_AA_SUBSTRATE_PHASE_3_DESIGN.md`` §4.3 (Rust spec) +
§5.4 (Python bridge spec) + §6.3 (test plan, pins #20-23) + §7.3
(cycle plan).

Deliverables (Cycle 2 Rust slice, per design doc §4.3 + §7.3):

  - New Rust ``Effect::BecomesCopyOfTargetLand`` variant on
    ``cards.rs::Effect`` (unit variant, no fields) — Thespian's
    Stage's pilot effect (``{2}, {T}: This land becomes a copy of
    target land, except it has this ability.``).
  - ``parse_effect`` arm in ``cards.rs`` — ``"becomes_copy_of_target_
    land"`` unit-variant; extra keys silently dropped (sibling of the
    Phase-2a/2b/3A/3B unit-variant siblings).
  - ``to_pydict`` arm in ``cards.rs`` — emits ``{kind:
    "becomes_copy_of_target_land"}``.
  - Land-target fan-out arm in
    ``state_ops_legal.rs::activate_ability_dict`` — enumerates every
    battlefield ``GameObject`` with printing card_type Land on EITHER
    player's bf (CR 109.3 / 613: any controller).
  - Apply-time validator arm in ``state_ops_actions.rs`` — re-checks
    the chosen target's bf-presence + Land card-type.
  - Resolve arm in ``state_ops_resolve.rs`` — re-validates target,
    snapshots ``source.original_printing_id`` if None, builds a new
    CardPrinting derived from target's printing + retained own AAs,
    pushes it onto the in-state registry, mutates
    ``source.printing_id`` to the new id.
  - Cross-engine bridge arms in ``cross_engine.py`` — forward emit
    (``_python_aa_to_safe_dict`` adds a ``BecomesCopyOfTargetLand``
    arm) + reverse (``_ta_dict_to_python_effect`` adds a
    ``becomes_copy_of_target_land`` arm).
  - New state-side getters ``printing_subtypes_of`` +
    ``printing_aa_count_of`` on ``GameState`` for substrate-test
    verification of effective-* lookups through the indirect-via-
    registry path.

ZERO Python admit widen (Cycle 3 ships
``_carrier_aa_phase_1_effect_classes`` widen + the admit-set teeth
inversion). ZERO per-card probe (Cycle 4/5 ships the real-EoE
``tests/test_thespians_stage_parity.py``). ZERO new cost-shape
machinery — Thespian's Stage's ``{2}, {T}`` cost rides the existing
``{N}, {T}`` cost gate (Phase 1.5a shape).

This is a **substrate-only closure** — the cycle adds the new Rust
Effect variant + Land-target fan-out + cross-engine bridge as
reusable infrastructure. The pilot card (Thespian's Stage) STAYS
DECLINED at the production-deck admit gate post-Cycle-2 because:

  (a) Python's admit predicate
      ``_aa_is_phase1_sub_shape_a`` Effect-class gate doesn't yet
      include ``BecomesCopyOfTargetLand`` in
      ``_carrier_aa_phase_1_effect_classes`` (Cycle 3 ships that
      widen, per design doc §5.4).

**Verify-first findings (live tree, main ``2f084625``):**

  - C1 substrate landed at ``f5a2a1ce``: ``GameObject.original_
    printing_id: Option<u32>`` field present at ``state.rs:490``;
    snapshot-bridge arm present at ``state_ops_snapshot.rs:158``;
    zone-change reset hookup across 94 sites; per-construction-site
    default ``None`` audit complete (13 sites).
  - Phase-3B C1 (``51abfd78``) shipped the sibling
    ``Effect::ExileAllGraveyards`` arm; the Phase-3A C2 closure (the
    Mystifying Maze admit FLIP) at the time of C2 commit defines the
    sibling ``ExileTargetAttackingCreatureUntilEndStep`` arm as the
    Land-target fan-out shape precedent.
  - ``RegistryData`` (the in-state Arc-shared registry data) at
    ``cards.rs:11744`` previously had no ``push_printing`` — C2 adds
    one mirroring ``Registry::push_printing``'s builder-side sibling.
  - Land-target fan-out precedent: the Phase-2 / Phase-3A
    ``state_ops_legal.rs:3556``+ block enumerates targets through
    its ``ability.effect``-discriminated arms; C2 inserts the new
    ``BecomesCopyOfTargetLand`` Land-walk arm in the same cascade.

**Test plan (per design doc §6.3 pins #20-23, Cycle 2 substrate-only
slice):**

  - Parser SoT pin: confirm Python's ``BecomesCopyOfTargetLand`` class
    exists in ``effects.generic.become_type`` and is a frozen unit
    variant.
  - Rust unit pins: ``parse_effect`` arm via ``register_printing``
    round-trip + ``to_pydict`` arm via the bridge inverse + extra-
    keys-silently-dropped contract.
  - Cross-engine bridge pins: dict→Python reverse arm
    (``_ta_dict_to_python_effect``) + Python→dict forward arm
    (``_python_aa_to_safe_dict``) + symmetric round-trip via
    ``_aa_dict_to_python_activated_ability``.
  - Pin #20 (resolve arm): activate Stage's AA targeting a Mountain;
    Stage's ``printing_id`` mutates to a new registry entry derived
    from Mountain's printing + Stage's pre-copy AAs;
    ``original_printing_id = Some(stage_original)``.
  - Pin #21 (re-copy retention): a second activation targeting a
    Forest re-copies; the new printing carries Forest's AAs + Stage's
    ORIGINAL AAs (not the post-Mountain accumulated AAs).
  - Pin #22 (zone-change clears original_printing_id): if the Stage
    is sacrificed / destroyed / bounced, the object's
    ``original_printing_id`` is cleared to None — already wired in
    C1's zone-change reset audit; this pin asserts the round-trip
    through resolve→bf-leave.
  - Pin #23 (mana-ability auto-wire): the copied Mountain's
    ``{T}: Add {R}`` AA flows through transparently — the AA count
    of the Stage post-copy includes the Mountain's mana AA.
  - Substrate-only invariant pins: Thespian's Stage STAYS DECLINED
    at the admit gate + STAYS DECLINED at the production-deck loader
    filter post-Cycle-2 + ``_carrier_aa_phase_1_effect_classes``
    UNCHANGED (no ``BecomesCopyOfTargetLand`` admit).
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
    per side. Mirrors the Phase-3A/3B/3C-C1 sibling shared fixture."""
    return engine.make_synthetic_state()


# ---------------------------------------------------------------------------
# Parser SoT verify-first
# ---------------------------------------------------------------------------


def test_python_becomes_copy_of_target_land_class_exists():
    """**Parser source-of-truth pin.** Python's
    ``BecomesCopyOfTargetLand`` class is in ``effects.generic.
    become_type``, a frozen dataclass with no constructor args. Two
    zero-arg instances compare equal (frozen dataclass __eq__ default).
    """
    from mtg_bot.effects.base import Effect
    from mtg_bot.effects.generic.become_type import BecomesCopyOfTargetLand

    eff = BecomesCopyOfTargetLand()
    assert isinstance(eff, Effect)
    assert eff == BecomesCopyOfTargetLand()


# ---------------------------------------------------------------------------
# Cross-engine bridge arm pins (dict <-> Python)
# ---------------------------------------------------------------------------


def test_bridge_arm_becomes_copy_of_target_land():
    """Bridge arm constructs ``BecomesCopyOfTargetLand()`` from a
    single-key dict (no fields)."""
    from mtg_bot.effects.generic.become_type import BecomesCopyOfTargetLand
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    back = _ta_dict_to_python_effect(
        {"kind": "becomes_copy_of_target_land"},
    )
    assert isinstance(back, BecomesCopyOfTargetLand)


def test_bridge_arm_becomes_copy_of_target_land_extra_keys_ignored():
    """Bridge arm silently ignores extra dict keys (unit-variant contract;
    mirrors the Rust ``parse_effect`` extra-keys-silently-dropped
    convention).
    """
    from mtg_bot.effects.generic.become_type import BecomesCopyOfTargetLand
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    back = _ta_dict_to_python_effect({
        "kind": "becomes_copy_of_target_land",
        "spurious_field": 99,
    })
    assert isinstance(back, BecomesCopyOfTargetLand)


def test_python_aa_to_safe_dict_forward_arm_round_trips_thespians_stage_shape():
    """**Forward emit pin.** A synthetic Thespian's-Stage-shape
    ``ActivatedAbility`` serializes through ``_python_aa_to_safe_dict``
    to a dict carrying:

      * ``cost``: ``{"tap_self": True, "mana": {"generic": 2}}``
      * ``effect``: ``{"kind": "becomes_copy_of_target_land"}``

    Cycle-2 substrate-only: this round-trip succeeds, but
    ``_aa_is_phase1_sub_shape_a`` still declines Thespian's Stage's
    AA on the Effect-class gate (C3 ships the widen).
    """
    from mtg_bot.effects.base import ActivatedAbility, ActivationCost
    from mtg_bot.effects.generic.become_type import BecomesCopyOfTargetLand
    from mtg_bot.cards.base import ManaCost
    from mtg_bot.parity.cross_engine import (
        _aa_dict_to_python_activated_ability,
        _python_aa_to_safe_dict,
    )

    aa = ActivatedAbility(
        cost=ActivationCost(
            tap_self=True,
            mana=ManaCost(generic=2),
        ),
        effect=BecomesCopyOfTargetLand(),
    )
    d = _python_aa_to_safe_dict(aa)
    assert d is not None, (
        "Thespian's Stage AA shape must round-trip through the bridge "
        "floor — Cycle 2 widens the forward emit even though the "
        "admit predicate keeps it DECLINED."
    )
    assert d["cost"]["tap_self"] is True
    assert d["cost"]["mana"] == {"generic": 2}
    assert d["effect"] == {"kind": "becomes_copy_of_target_land"}
    # Reverse round-trip — byte-equal at the dataclass __eq__ surface.
    back = _aa_dict_to_python_activated_ability(d)
    assert back == aa


# ---------------------------------------------------------------------------
# Rust unit pins — parse + register
# ---------------------------------------------------------------------------


def test_rust_register_carrier_aa_thespians_stage_shape():
    """**Rust parse arm pin (design doc §6.3 #20 — parse half).**
    ``register_printing`` accepts a non-token Land carrier with
    ``activated_abilities=[{cost: {tap_self: True, mana: {generic: 2}},
    effect: {kind: becomes_copy_of_target_land}}]``. The pid is
    returned and ``get_printing_name`` echoes the name.
    """
    _require_engine()
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing({
        "name": "Test Thespian's Stage",
        "card_types": ["Land"],
        "mana_cost": {},
        "activated_abilities": [
            {
                "cost": {"tap_self": True, "mana": {"generic": 2}},
                "effect": {"kind": "becomes_copy_of_target_land"},
            }
        ],
    })
    assert reg.get_printing_name(pid) == "Test Thespian's Stage"


def test_rust_register_becomes_copy_of_target_land_extra_dict_keys_silently_dropped():
    """Unit-variant contract: ``becomes_copy_of_target_land`` parse
    arm silently drops extra dict keys (no field validation; sibling
    of the Phase-2a/2b/3A/3B unit-variant parse arms).
    """
    _require_engine()
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing({
        "name": "Test Stage With Extras",
        "card_types": ["Land"],
        "mana_cost": {},
        "activated_abilities": [
            {
                "cost": {"tap_self": True, "mana": {"generic": 2}},
                "effect": {
                    "kind": "becomes_copy_of_target_land",
                    "spurious_field": 42,
                },
            }
        ],
    })
    assert reg.get_printing_name(pid) == "Test Stage With Extras"


# ---------------------------------------------------------------------------
# Rust resolve arm pins — BecomesCopyOfTargetLand semantics
# ---------------------------------------------------------------------------


def _synthetic_thespians_stage_dict():
    """Minimal Thespian's-Stage-shape Land printing dict for the Rust
    Registry."""
    return {
        "name": "Synthetic Thespian's Stage",
        "card_types": ["Land"],
        "mana_cost": {},
        "activated_abilities": [
            {
                "cost": {"tap_self": True, "mana": {"generic": 2}},
                "effect": {"kind": "becomes_copy_of_target_land"},
                "is_mana_ability": False,
            }
        ],
    }


def _synthetic_mountain_dict():
    """Minimal Mountain-shape basic Land printing dict. Carries a
    single mana-ability ``{T}: Add {R}`` synthesized via
    ``mana_produced=["R"]`` (the Rust bridge auto-prepends one
    ActivatedAbility per produced color — see
    ``apply_mana_produced_bridge``). The synthesized AA flows
    through the copy effect alongside the Stage's retained own
    copy AA, giving 2 total post-copy.
    """
    return {
        "name": "Synthetic Mountain",
        "card_types": ["Land"],
        "subtypes": ["Mountain"],
        "supertypes": ["Basic"],
        "mana_cost": {},
        "mana_produced": ["R"],
    }


def _synthetic_forest_dict():
    """Minimal Forest-shape basic Land printing dict — sibling to the
    Mountain shape but with green mana and Forest subtype. Used for
    the re-copy retention pin (a second activation pivots the copy
    target from Mountain to Forest). Same auto-synthesized mana-AA
    via ``mana_produced=["G"]``.
    """
    return {
        "name": "Synthetic Forest",
        "card_types": ["Land"],
        "subtypes": ["Forest"],
        "supertypes": ["Basic"],
        "mana_cost": {},
        "mana_produced": ["G"],
    }


def test_resolve_becomes_copy_of_target_land_mutates_printing_and_snapshots_original(
    engine, synthetic_state,
):
    """**Design doc §6.3 #20 — resolve arm pin.** Set up: Thespian's
    Stage on p0 bf; opponent Mountain on p1 bf. Activate Stage's AA
    targeting the Mountain; resolve.

    Expected post-resolve:
      * Stage's ``original_printing_id`` is ``Some(stage_pre_copy_pid)``.
      * Stage's ``printing_id`` mutates to a fresh registry entry
        derived from Mountain's printing.
      * ``printing_subtypes_of(stage_id)`` returns
        ``["Mountain"]`` (the copied subtypes flow through).
      * ``printing_aa_count_of(stage_id)`` returns 2 (Mountain's
        mana AA + Stage's pre-copy own AA = 1 + 1).
      * The post-copy printing's name is the Mountain's name (the
        target's full printing flows through, not just AAs).
    """
    # Inject the Stage on p0's bf.
    stage_id = synthetic_state.register_and_inject_object(
        _synthetic_thespians_stage_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(stage_id, False)
    # Inject a Mountain on p1's bf (opponent — the copy target).
    mountain_id = synthetic_state.register_and_inject_object(
        _synthetic_mountain_dict(), 1, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(mountain_id, False)

    # Snapshot the Stage's pre-copy printing_id from the bf snapshot.
    bf_pre = synthetic_state.battlefield_snapshot()
    stage_pre = next(o for o in bf_pre if o["id"] == stage_id)
    stage_pre_printing_id = stage_pre["printing_id"]
    assert stage_pre["original_printing_id"] is None, (
        "Pre-copy: original_printing_id slot must default to None"
    )

    # Pay {2} mana.
    synthetic_state.add_mana(0, "C", 2)
    # Activate Stage's AA with target = mountain_id.
    synthetic_state.apply_action({
        "kind": "activate_ability",
        "source_id": stage_id,
        "ability_index": 0,
        "target_creature_id": mountain_id,
    })
    assert synthetic_state.stack_size() == 1
    # Resolve — fires the new Effect::BecomesCopyOfTargetLand arm.
    synthetic_state.resolve_top_of_stack()
    assert synthetic_state.is_stack_empty()

    # Post-state: Stage's snapshot.
    bf_post = synthetic_state.battlefield_snapshot()
    stage_post = next(o for o in bf_post if o["id"] == stage_id)
    # original_printing_id should now be Some(stage_pre_printing_id).
    assert stage_post["original_printing_id"] == stage_pre_printing_id, (
        f"Stage's original_printing_id should snapshot the pre-copy "
        f"printing_id={stage_pre_printing_id}; got "
        f"{stage_post['original_printing_id']}"
    )
    # Stage's printing_id should NOW point at a new entry (NOT the
    # pre-copy id, and NOT the Mountain's printing_id — it's a fresh
    # registry mint).
    assert stage_post["printing_id"] != stage_pre_printing_id, (
        "Stage's printing_id should change after BecomesCopyOfTargetLand "
        "resolves — got unchanged id"
    )
    # The post-copy printing's name is the Mountain's name.
    assert synthetic_state.printing_name_of(stage_id) == "Synthetic Mountain", (
        f"Post-copy Stage name should be 'Synthetic Mountain'; got "
        f"{synthetic_state.printing_name_of(stage_id)!r}"
    )
    # Post-copy subtypes contain "Mountain" (the target's land
    # subtype flows through).
    subtypes = synthetic_state.printing_subtypes_of(stage_id)
    assert "Mountain" in subtypes, (
        f"Post-copy Stage subtypes must include 'Mountain'; got {subtypes}"
    )
    # AA count = target's AAs + Stage's original own AAs = 1 + 1 = 2.
    aa_count = synthetic_state.printing_aa_count_of(stage_id)
    assert aa_count == 2, (
        f"Post-copy Stage should carry target's mana AA + original "
        f"copy-AA (2 total); got {aa_count}"
    )


def test_resolve_becomes_copy_re_copy_retention_uses_original_not_post_copy(
    engine, synthetic_state,
):
    """**Design doc §6.3 #21 — re-copy retention pin.** A second
    activation targeting a DIFFERENT Land re-copies the Stage. The
    new printing's AAs are the NEW target's AAs + the Stage's
    ORIGINAL pre-copy AAs (NOT the already-accumulated post-Mountain
    AAs).

    Set up: Stage on p0 bf (copy AA), Mountain on p1 bf, Forest on
    p1 bf. Activate Stage targeting Mountain → resolve. Then
    activate Stage AGAIN targeting Forest → resolve. The Stage's
    post-re-copy AA count should be 2 (Forest's mana AA + Stage's
    pre-copy copy AA) — NOT 3 (Forest + Mountain + copy) and NOT
    1 (Forest only, losing the copy AA).
    """
    stage_id = synthetic_state.register_and_inject_object(
        _synthetic_thespians_stage_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(stage_id, False)
    mountain_id = synthetic_state.register_and_inject_object(
        _synthetic_mountain_dict(), 1, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(mountain_id, False)
    forest_id = synthetic_state.register_and_inject_object(
        _synthetic_forest_dict(), 1, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(forest_id, False)

    # Pre-copy: capture the Stage's printing_id (the snapshot anchor).
    bf_pre = synthetic_state.battlefield_snapshot()
    stage_pre = next(o for o in bf_pre if o["id"] == stage_id)
    stage_original_pid = stage_pre["printing_id"]
    # The Stage starts untapped — copy AA has tap_self=True.
    # First activation: target Mountain.
    synthetic_state.add_mana(0, "C", 2)
    synthetic_state.apply_action({
        "kind": "activate_ability",
        "source_id": stage_id,
        "ability_index": 0,
        "target_creature_id": mountain_id,
    })
    synthetic_state.resolve_top_of_stack()
    # Sanity: post-Mountain-copy AA count = 2 (Mountain mana + own copy AA).
    assert synthetic_state.printing_aa_count_of(stage_id) == 2

    # Untap the Stage (the {T} cost tapped it during cost-pay) so the
    # second activation is legal under the SAME copy-AA infrastructure.
    synthetic_state.untap_object(stage_id)

    # Second activation: target Forest. The Stage's printing
    # post-Mountain-copy includes Mountain's AAs + the Stage's own
    # copy AA — the copy AA is at index 1 now (the Mountain's mana AA
    # is at index 0; the retained Stage AA was appended). Find the
    # copy-effect AA index via the ability list.
    # Both the cost {2}{T} and the copy AA are the SAME shape as the
    # original Stage AA, so the apply path accepts it with the
    # ability_index pointing at the post-copy slot.
    bf_mid = synthetic_state.battlefield_snapshot()
    stage_mid = next(o for o in bf_mid if o["id"] == stage_id)
    assert stage_mid["original_printing_id"] == stage_original_pid, (
        "Re-copy must preserve the original_printing_id snapshot"
    )
    # Find the copy AA's ability_index on the post-Mountain-copy
    # printing — Mountain's mana AA is at index 0; the retained
    # Stage copy AA is at index 1.
    synthetic_state.add_mana(0, "C", 2)
    synthetic_state.apply_action({
        "kind": "activate_ability",
        "source_id": stage_id,
        "ability_index": 1,
        "target_creature_id": forest_id,
    })
    synthetic_state.resolve_top_of_stack()

    # Post-re-copy: AA count = Forest's mana AA + Stage's ORIGINAL
    # copy AA = 1 + 1 = 2. NOT 3 (no accumulation across re-copies)
    # and NOT 1 (the copy AA isn't lost on re-copy).
    assert synthetic_state.printing_aa_count_of(stage_id) == 2, (
        f"Post-re-copy Stage should carry target's AA + ORIGINAL "
        f"copy AA (2 total); accumulation would yield 3, AA-loss "
        f"would yield 1. Got "
        f"{synthetic_state.printing_aa_count_of(stage_id)}"
    )
    # Subtypes post-re-copy: Forest (NOT Mountain — the new target's
    # subtypes overwrite via the printing replace).
    subtypes = synthetic_state.printing_subtypes_of(stage_id)
    assert "Forest" in subtypes, (
        f"Post-re-copy Stage subtypes must include 'Forest'; got {subtypes}"
    )
    assert "Mountain" not in subtypes, (
        f"Post-re-copy Stage subtypes must NOT include 'Mountain' "
        f"(superseded by Forest copy); got {subtypes}"
    )
    # Snapshot anchor unchanged across re-copy.
    bf_post = synthetic_state.battlefield_snapshot()
    stage_post = next(o for o in bf_post if o["id"] == stage_id)
    assert stage_post["original_printing_id"] == stage_original_pid, (
        "Re-copy must NOT mutate the original_printing_id snapshot"
    )


def test_resolve_becomes_copy_silent_fizzle_no_target(
    engine, synthetic_state,
):
    """**Resolve arm — silent fizzle (CR 608.2b).** If no target is
    bound on the StackItem (``current_resolve_payload_target_id ==
    None``), the resolve arm silently fizzles — NO printing mutation,
    NO snapshot mint.

    Mirrors Python's `if source is None or not targets: return`
    early-return at `become_type.py:285-286`.
    """
    stage_id = synthetic_state.register_and_inject_object(
        _synthetic_thespians_stage_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(stage_id, False)

    # Snapshot pre-fizzle printing_id.
    bf_pre = synthetic_state.battlefield_snapshot()
    stage_pre = next(o for o in bf_pre if o["id"] == stage_id)
    stage_pre_pid = stage_pre["printing_id"]
    assert stage_pre["original_printing_id"] is None

    # Activate without a target.
    synthetic_state.add_mana(0, "C", 2)
    synthetic_state.apply_action({
        "kind": "activate_ability",
        "source_id": stage_id,
        "ability_index": 0,
        # No target_creature_id — substrate-fallback path drives the
        # no-target-seated → silent-fizzle flow at resolve.
    })
    synthetic_state.resolve_top_of_stack()

    # Post-state: printing_id unchanged, original_printing_id still None.
    bf_post = synthetic_state.battlefield_snapshot()
    stage_post = next(o for o in bf_post if o["id"] == stage_id)
    assert stage_post["printing_id"] == stage_pre_pid, (
        "Silent fizzle must not mutate Stage's printing_id"
    )
    assert stage_post["original_printing_id"] is None, (
        "Silent fizzle must not mint the original_printing_id snapshot"
    )


def test_resolve_becomes_copy_target_off_bf_silent_fizzle(
    engine, synthetic_state,
):
    """**Design doc §6.3 #22 — target left bf between activation +
    resolve (CR 608.2b silent fizzle).** If the chosen Land target
    leaves a battlefield between cost-pay and resolve, the
    re-validation walks both bfs, finds no match, and silently
    fizzles — NO printing mutation, NO snapshot mint.

    This stresses the CR 608.2b re-validation path on the resolve
    arm. Set up: Stage + Mountain on opposite bfs. Activate Stage
    targeting Mountain → cost-pays. Force the Mountain off the
    battlefield (move to its controller's graveyard) BEFORE resolve.
    Resolve. Stage's snapshot stays default-None; printing_id
    unchanged.

    (The full zone-change-clears-original_printing_id reset pin —
    Stage leaves bf AFTER a successful copy — is design doc §6.3
    Cycle 4/5 scope per C1's pin note: "Cycle 4's per-card probe
    asserts the full reset semantics on a real Thespian's-Stage-
    leaves-bf line".)
    """
    stage_id = synthetic_state.register_and_inject_object(
        _synthetic_thespians_stage_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(stage_id, False)
    mountain_id = synthetic_state.register_and_inject_object(
        _synthetic_mountain_dict(), 1, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(mountain_id, False)

    # Snapshot pre-state.
    bf_pre = synthetic_state.battlefield_snapshot()
    stage_pre = next(o for o in bf_pre if o["id"] == stage_id)
    stage_pre_pid = stage_pre["printing_id"]

    # Activate the copy AA targeting Mountain (cost-pays; Stage taps).
    synthetic_state.add_mana(0, "C", 2)
    synthetic_state.apply_action({
        "kind": "activate_ability",
        "source_id": stage_id,
        "ability_index": 0,
        "target_creature_id": mountain_id,
    })
    assert synthetic_state.stack_size() == 1

    # Force the Mountain off the battlefield BEFORE resolve (CR
    # 608.2b — target legality re-checked at resolve). ``move_object``
    # is the test-helper zone-mover.
    synthetic_state.move_object(mountain_id, ZONE_GRAVEYARD, 1)

    # Resolve. The Stage's resolve arm re-checks bf-presence,
    # finds nothing, silently fizzles.
    synthetic_state.resolve_top_of_stack()
    assert synthetic_state.is_stack_empty()

    # Post-state: Stage's printing_id unchanged, snapshot still None.
    bf_post = synthetic_state.battlefield_snapshot()
    stage_post = next(o for o in bf_post if o["id"] == stage_id)
    assert stage_post["printing_id"] == stage_pre_pid, (
        "Silent fizzle (target left bf) must not mutate Stage's "
        "printing_id"
    )
    assert stage_post["original_printing_id"] is None, (
        "Silent fizzle (target left bf) must not mint the snapshot"
    )


# ---------------------------------------------------------------------------
# Substrate-only invariant pins — Thespian's Stage STAYS DECLINED
# ---------------------------------------------------------------------------


def test_thespians_stage_stays_declined_post_substrate_cycle_2():
    """**Substrate-only invariant — Thespian's Stage STAYS DECLINED
    post-Cycle-2.** The Rust Effect variant + Land-target fan-out +
    cross-engine bridge arms all landed at C2; the Python admit-set
    widen + per-card probe ship in C3/C4. The production-deck admit
    predicate ``_printing_is_bridge_simple_carrier_aa_land``
    therefore STILL declines Thespian's Stage post-C2.
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import (
        _printing_is_bridge_simple_carrier_aa_land,
    )

    ps = OracleParserCardSource().get_printings()
    ts = ps["Thespian's Stage"]
    # Substrate-only invariant: STAYS DECLINED.
    assert not _printing_is_bridge_simple_carrier_aa_land(ts), (
        "Thespian's Stage should STAY DECLINED post-Phase-3C-Cycle-2 "
        "(Effect-class admit-set widen + per-card probe ship in C3/C4)."
    )


def test_phase_1_effect_classes_unchanged_post_substrate_cycle_2():
    """**Effect-class admit set UNCHANGED.** Cycle 2 does NOT widen
    the Python Effect-class allowlist; that's Cycle 3's deliverable.
    Confirm ``BecomesCopyOfTargetLand`` is NOT in the set
    post-Cycle-2.
    """
    from mtg_bot.effects.generic.become_type import BecomesCopyOfTargetLand
    from mtg_bot.parity.trajectory import _carrier_aa_phase_1_effect_classes

    classes = _carrier_aa_phase_1_effect_classes()
    assert BecomesCopyOfTargetLand not in classes, (
        "BecomesCopyOfTargetLand should NOT be in the admit set "
        "post-Phase-3C-Cycle-2 (Cycle 3 ships the widen)."
    )
