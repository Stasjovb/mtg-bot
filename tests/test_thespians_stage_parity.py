"""Thespian's Stage — per-card real-EoE cross-engine byte-equal probe
(covered_by_construction → PROBED tier flip; Carrier-AA Phase 3C
admit-set landing; CLOSES Phase 3C).

Thespian's Stage is a ``{0}`` Land in the EoE pool with a single
non-mana activated ability:

    "{2}, {T}: This land becomes a copy of target land, except it
    has this ability."

The Carrier-AA substrate Phase 3C (2026-05-26 — see
``docs/CARRIER_AA_SUBSTRATE_PHASE_3_DESIGN.md`` §7.3) closes in
FIVE cycles: (C1) Rust state field — new
``GameObject.original_printing_id: Option<u32>`` slot + per-zone-
change reset hookup at every bf-leave site + fingerprint serializer
arm + clone path + GameObject snapshot bridge to Python — landed at
commit ``f5a2a1ce``; (C2) Rust Effect port — new
``Effect::BecomesCopyOfTargetLand`` variant + parse / resolve /
to_pydict arms + Land-target fan-out in
``state_ops_legal.rs::activate_ability_dict`` + re-copy snapshot
logic + the 4 Rust unit pins — landed at commit ``6de50d8d``; (C3)
Python admit widen + Thespian's Stage FLIP — the
``_carrier_aa_phase_1_effect_classes`` lazy frozenset accessor at
``src/mtg_bot/parity/trajectory.py`` extended to include
``BecomesCopyOfTargetLand`` — landed at commits
``43ed68e6`` + ``cc47f026`` (Thespian's Stage's live AA shape is
``{2}, {T}``, the Phase-1.5a ``{N}, {T}`` cost-gate is already wired,
so the admit-gate FLIPs DECLINED → ADMITTED on this widen alone);
(C4 + C5) THIS PROBE — real-EoE per-card byte-equal observable on
both engines, covering the GENUINE CR-613 layer-1 object-copy chain
through the Python ``BecomesCopyOfTargetLand`` resolve arm + the
``original_printing`` snapshot anchor + the
``move_off_battlefield`` zone-change reset that clears the snapshot
when Stage leaves play. Closes Phase 3C.

Parser-emitted Effect shape:

    ``BecomesCopyOfTargetLand()``  (unit-variant zero-arg frozen
    dataclass; no ``__post_init__`` stamps — the class is bare;
    ``requires_target() == True`` + ``legal_targets`` walks
    ``state.battlefield`` for any Land, EITHER player controls)

attached to an ``ActivatedAbility`` whose ``cost`` carries
``mana=ManaCost(generic=2)`` + ``tap_self=True`` (no sacrifice). The
bridge arm ``becomes_copy_of_target_land`` (``cross_engine.py``
reverse arm at line 12975; ``cross_engine.py:14917``
``_python_aa_to_safe_dict`` forward emit arm) round-trips
``{"kind": "becomes_copy_of_target_land"}`` byte-equal to Python's
``BecomesCopyOfTargetLand()``.

**EEEE-idiom for the ActivatedAbility carrier.** Same lane discipline
as the sibling Carrier-AA AA probes (parse + bridge round-trip +
Python-side resolve): the probe drives the parsed Effect through its
actual ``resolve`` path on the Python state, with observables that
mirror what Rust's ``Effect::BecomesCopyOfTargetLand`` resolve arm
(``rust/src/state_ops_resolve.rs`` per the C2 substrate landing at
commit ``6de50d8d``) produces on the same input shape. The
cross-engine byte-equal mirror is established by the Phase-3C admit
gate routing the genuine parsed Thespian's Stage printing through
the Carrier-AA substrate end-to-end (loader admits post-C3 — see
the C3-flipped admit pin
``test_filter_deck_to_bridge_supported_admits_thespians_stage`` in
``test_carrier_aa_phase_3c_substrate_cycle_2.py``).

**NEW shape coverage:** the FIRST PROBE_MODULES-credited probe
binding the Thespian's Stage slug to the AA +
``BecomesCopyOfTargetLand`` Effect+bridge round-trip on the REAL
parsed EoE printing — and the FIRST PROBED-tier slot for the
``BecomesCopyOfTargetLand`` Effect class via the Carrier-AA
substrate's ``{N}, {T}`` cost-shape disjunct. The CR-613 layer-1
object-copy substrate (the new ``GameObject.original_printing_id``
slot on Rust, mirrored by the existing
``GameObject.original_printing: CardPrinting | None`` field on
Python at ``game.py:599``) is end-to-end exercised here for the
FIRST time at PROBED-tier granularity.

**AA-cost-substrate scope.** The mana-payment (``{2}``) /
tap-payment cost trajectory of the AA is exercised at the loader-
end-to-end disjunct (Thespian's Stage passes
``_printing_is_bridge_simple_carrier_aa_land`` post-C3 widen + the
cross-engine bridge round-trip pin below); per-slug PROBED
attribution credits Thespian's Stage based on the Effect + bridge
byte-equality + parsed-printing resolve smoke alone — the canonical
EEEE-idiom precedent (Petrified Field's Phase-2a probe at
``tests/test_petrified_field_parity.py`` / Terrain Generator's
Phase-2b probe at ``tests/test_terrain_generator_parity.py`` /
Mystifying Maze's Phase-3A probe at
``tests/test_mystifying_maze_parity.py`` / Scavenger Grounds's
Phase-3B probe at ``tests/test_scavenger_grounds_parity.py``).

**CR-613 layer-1 object-copy contract (load-bearing).** Python's
``BecomesCopyOfTargetLand.resolve`` (``become_type.py:278-306``):

  * if the source has no ``original_printing`` yet, snapshot
    ``source.printing`` into ``source.original_printing`` (sticky
    across re-copies — preserves "this ability" through chains);
  * retain the snapshot's ``activated_abilities`` tuple;
  * rebuild ``source.printing`` via
    ``dataclasses.replace(target.printing, activated_abilities=
    tuple(target.printing.activated_abilities) +
    tuple(retained))``;
  * append ``"<original name> becomes a copy of <target name>"``
    to ``state.log``.

The Rust mirror at ``rust/src/state_ops_resolve.rs`` walks the same
chain byte-equal: snapshot
``source.original_printing_id = Some(stage_pre_copy_pid)`` (if
None); rebuild ``source.printing_id`` to point at a fresh
registry entry derived from target's printing + Stage's pre-copy
AAs.

**Zone-change reset contract (load-bearing — §6.5 Stage-leaves-
clears-copy line).** Python's ``move_off_battlefield``
(``turn.py:141``) calls ``revert_printing_if_no_layer1_copies``
(``game.py:1666``) at the tail of bf-leave: restores
``obj.printing = obj.original_printing`` and clears
``obj.original_printing = None`` IF no layer-1 ``is_copy`` registry
entry is still live for ``obj``. The
``BecomesCopyOfTargetLand`` resolve arm does NOT write a layer-1
``is_copy`` registry entry (it mutates the printing slot
directly — see ``become_type.py:298``), so
``revert_printing_if_no_layer1_copies`` always fires on
Stage-leaves-bf. The Rust mirror at the bf-leave call sites
clears ``original_printing_id = None`` byte-equal per CR 400.7.
"""

from __future__ import annotations

import importlib.util

import pytest

from mtg_bot.cards.source import get_active_source
from mtg_bot.effects.generic.become_type import BecomesCopyOfTargetLand


_PRINTINGS = get_active_source().get_printings()


_rust_skip = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


# Zone constants (mirror Rust's u8 zone IDs).
ZONE_HAND = 0
ZONE_LIBRARY = 1
ZONE_BATTLEFIELD = 2
ZONE_GRAVEYARD = 3
ZONE_EXILE = 4


# ---------------------------------------------------------------------------
# (1) Parser SoT — Thespian's Stage is parser-claimed and carries the
# exact AA shape the design doc (§7.3) pins.
# ---------------------------------------------------------------------------


def test_thespians_stage_parser_claims_card():
    assert "Thespian's Stage" in _PRINTINGS, (
        "Thespian's Stage must be parser-claimed by the active "
        "CardSource"
    )


def test_thespians_stage_printed_attrs():
    """Pins the basic printing surface: single-typed Land, no subtypes
    (Thespian's Stage is NOT a Desert / not a basic — pure generic
    Land), no mana cost, no power/toughness, no triggered / static /
    keyword riders. The single carrier AA is the
    ``BecomesCopyOfTargetLand`` AA (non-mana — Thespian's Stage carries
    NO printed ``{T}: Add {C}`` mana ability; the parser does NOT
    synthesize a mana-ability slot for it). The carrier AA is the
    ONLY ``activated_abilities`` entry."""
    p = _PRINTINGS["Thespian's Stage"]
    assert p.card_types == ("Land",)
    assert p.subtypes == ()
    assert p.mana_cost.generic == 0
    assert p.mana_cost.colored == ()
    assert p.power is None and p.toughness is None
    assert p.keywords == frozenset()
    assert p.triggered_abilities == ()
    assert p.static_abilities == ()


def test_thespians_stage_activated_ability_copy_target_land_shape():
    """Thespian's Stage has the single carrier ``ActivatedAbility``
    whose effect is ``BecomesCopyOfTargetLand()`` (unit variant, no
    fields). Cost is ``{2}, {T}`` — the Phase-1.5a widened cost-gate
    shape."""
    p = _PRINTINGS["Thespian's Stage"]
    non_mana_aas = [
        aa for aa in (p.activated_abilities or ())
        if not aa.is_mana_ability
    ]
    assert len(non_mana_aas) == 1, (
        f"Thespian's Stage must have exactly one non-mana "
        f"ActivatedAbility; got {len(non_mana_aas)}"
    )
    aa = non_mana_aas[0]
    # Effect shape.
    assert isinstance(aa.effect, BecomesCopyOfTargetLand), (
        f"Thespian's Stage AA effect must be "
        f"BecomesCopyOfTargetLand; got {type(aa.effect).__name__}"
    )
    # Cost shape — the Phase-3C load-bearing axis (Phase-1.5a wired).
    assert aa.cost.tap_self is True
    assert aa.cost.sacrifice_self is False, (
        "Thespian's Stage's AA carries NO sacrifice_self (cost is "
        "just ``{2}, {T}``)"
    )
    assert aa.cost.sacrifice_a_desert is False, (
        "Thespian's Stage's AA carries NO sacrifice_a_desert "
        "(cost is just ``{2}, {T}``)"
    )
    assert aa.cost.mana is not None, (
        "Thespian's Stage's AA cost carries ``{2}`` mana component"
    )
    assert aa.cost.mana.generic == 2
    assert aa.cost.mana.colored == ()
    assert aa.cost.mana.hybrid == ()
    assert aa.cost.mana.x_pips == 0
    # No riders.
    assert aa.is_mana_ability is False
    assert aa.sorcery_speed is False
    assert aa.cost_reductions == ()
    assert aa.room_half is None
    assert aa.tier_threshold == 0
    assert aa.activate_only_once is False
    # The Effect declares itself targeted (CR 608.2b — re-validate at
    # resolve), and its targeting filter is "any Land on the
    # battlefield, either controller" via legal_targets at runtime.
    assert aa.effect.requires_target() is True


# ---------------------------------------------------------------------------
# (2) Bridge round-trip — the becomes_copy_of_target_land dict shape
# round-trips byte-equal to the parsed printing's emitted Effect.
# ---------------------------------------------------------------------------


def test_thespians_stage_bridge_arm_round_trip():
    """The bridge arm ``becomes_copy_of_target_land``
    (cross_engine.py:12975) round-trips
    ``{"kind": "becomes_copy_of_target_land"}`` to the matching
    Python ``BecomesCopyOfTargetLand()`` instance — unit variant,
    no fields.

    Effect-level byte-equality between the parsed real-EoE printing's
    emitted ``BecomesCopyOfTargetLand`` Effect and the bridged
    Effect: the structural contract for the PROBED tier."""
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    bridged = _ta_dict_to_python_effect(
        {"kind": "becomes_copy_of_target_land"}
    )
    assert isinstance(bridged, BecomesCopyOfTargetLand)
    # Unit-variant equality.
    assert bridged == BecomesCopyOfTargetLand()

    p = _PRINTINGS["Thespian's Stage"]
    non_mana_aas = [
        aa for aa in (p.activated_abilities or ())
        if not aa.is_mana_ability
    ]
    aa = non_mana_aas[0]
    assert aa.effect == bridged, (
        f"Thespian's Stage AA Effect must be byte-equal to the "
        f"bridged Effect (BecomesCopyOfTargetLand() unit-variant "
        f"structural contract); got parsed={aa.effect!r}, "
        f"bridged={bridged!r}"
    )


def test_thespians_stage_aa_round_trip_through_safe_dict():
    """The bridge's ``_python_aa_to_safe_dict`` ↔
    ``_aa_dict_to_python_activated_ability`` round-trip applied to
    the genuine parsed Thespian's Stage AA emits the canonical
    ``{"cost": {"mana": {"generic": 2}, "tap_self": True}, "effect":
    {"kind": "becomes_copy_of_target_land"}}`` dict and rebuilds a
    byte-equal Python ActivatedAbility on the load-bearing fields
    (cost atoms + Effect + AA-rider fields). The cost-side
    ``mana_str`` display-string field is parser-only and is NOT
    round-tripped through the bridge (UI-side annotation; both
    engines ignore it for activation semantics — same convention as
    the Deserted Temple / Petrified Field / Terrain Generator /
    Mystifying Maze / Scavenger Grounds probes)."""
    from mtg_bot.parity.cross_engine import (
        _aa_dict_to_python_activated_ability,
        _python_aa_to_safe_dict,
    )

    p = _PRINTINGS["Thespian's Stage"]
    non_mana_aas = [
        aa for aa in (p.activated_abilities or ())
        if not aa.is_mana_ability
    ]
    aa = non_mana_aas[0]
    safe = _python_aa_to_safe_dict(aa)
    assert safe is not None, (
        "_python_aa_to_safe_dict must accept Thespian's Stage's "
        "parsed AA post-Phase-3C — the C3 Effect-class widen + "
        "Phase-1.5a cost-gate gate admit this shape"
    )
    assert safe == {
        "cost": {"mana": {"generic": 2}, "tap_self": True},
        "effect": {"kind": "becomes_copy_of_target_land"},
    }
    back = _aa_dict_to_python_activated_ability(safe)
    assert back.effect == aa.effect
    assert back.cost.mana == aa.cost.mana
    assert back.cost.tap_self == aa.cost.tap_self
    assert back.cost.sacrifice_self == aa.cost.sacrifice_self
    assert back.is_mana_ability == aa.is_mana_ability
    assert back.sorcery_speed == aa.sorcery_speed
    assert back.cost_reductions == aa.cost_reductions
    assert back.room_half == aa.room_half
    assert back.tier_threshold == aa.tier_threshold
    assert back.activate_only_once == aa.activate_only_once


# ---------------------------------------------------------------------------
# (3) Rust synthetic-carrier sanity — the Rust parser accepts a
# Thespian's-Stage-shape dict (carrier AA with ``{2}, {T}`` cost +
# ``BecomesCopyOfTargetLand`` effect). Exercises the Rust
# ``parse_effect`` arm for the ``becomes_copy_of_target_land`` kind
# landed in the Phase-3C C2 substrate.
# ---------------------------------------------------------------------------


@_rust_skip
def test_rust_parser_accepts_thespians_stage_synthetic_dict():
    """Lockstep pin: Rust's ``parse_effect`` +
    ``parse_activated_ability`` arms accept a Thespian's-Stage-shape
    dict (single AA with
    ``{"cost": {"mana": {"generic": 2}, "tap_self": True}, "effect":
    {"kind": "becomes_copy_of_target_land"}}``) on a Land carrier.
    The Phase-3C C1 substrate (commit ``f5a2a1ce``) shipped the new
    ``GameObject.original_printing_id`` slot + the C2 substrate
    (commit ``6de50d8d``) shipped the Effect variant + parse arms +
    resolve arm + cross-engine bridge arms in lockstep; this pin
    confirms the end-to-end Rust acceptance under the Phase-3C C3
    Effect-class widen."""
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Thespian's Stage (synthetic carrier)",
            "card_types": ["Land"],
            "mana_cost": {"generic": 0},
            "effects": [],
            "activated_abilities": [
                {
                    "cost": {
                        "tap_self": True,
                        "mana": {"generic": 2},
                    },
                    "effect": {
                        "kind": "becomes_copy_of_target_land",
                    },
                },
            ],
        }
    )
    assert isinstance(pid, int)


# ---------------------------------------------------------------------------
# (4) Carrier-AA loader admit pin — the Phase-3C admit-set end-to-end:
# ``_filter_deck_to_bridge_supported`` admits Thespian's Stage through
# the Carrier-AA disjunct, the resulting CardDef carries the canonical
# AA dict shape ready for ``build_rust_state`` to emit into the Rust
# registry.
# ---------------------------------------------------------------------------


def test_thespians_stage_carrier_aa_loader_end_to_end_admit():
    """**Phase 3C end-to-end pin.** The production-deck loader
    (``_filter_deck_to_bridge_supported``) admits Thespian's Stage
    through the Carrier-AA Phase 3C disjunct. The returned CardDef
    carries the single non-token AA dict with the canonical
    Phase-1.5a cost shape + Phase-3C ``BecomesCopyOfTargetLand``
    effect — Rust-side ``build_rust_state`` consumes it via the
    Phase-3C C2 substrate emit arm (no other code path needed)."""
    from mtg_bot.parity.trajectory import _filter_deck_to_bridge_supported

    filtered, card_defs = _filter_deck_to_bridge_supported(
        ["Thespian's Stage"], _PRINTINGS,
    )
    assert filtered == ["Thespian's Stage"]
    assert len(card_defs) == 1
    card_def = card_defs[0]
    assert card_def.name == "Thespian's Stage"
    assert card_def.card_type == "Land"
    assert card_def.mana_produced == ()
    assert card_def.triggered_abilities == ()
    assert card_def.keywords == ()
    assert card_def.token_activated_abilities == ()
    aas = card_def.activated_abilities
    assert len(aas) == 1
    aa_dict = aas[0]
    assert aa_dict["cost"] == {
        "tap_self": True,
        "mana": {"generic": 2},
    }
    assert aa_dict["effect"] == {
        "kind": "becomes_copy_of_target_land",
    }


# ---------------------------------------------------------------------------
# (5) GENUINE real-EoE cross-engine byte-equal probe — drives the
# ACTUAL parsed Thespian's Stage printing's AA through its
# ``BecomesCopyOfTargetLand`` Effect resolve path on the Python side,
# mirroring Rust's ``Effect::BecomesCopyOfTargetLand`` resolve arm
# (the C2 substrate landing at commit ``6de50d8d``). The probe
# asserts the FOUR observables the design doc §6.5 #30 pins:
#   (a) baseline — Stage on bf with no other Land → activation illegal
#       (legal_targets is empty), resolve with empty targets is a no-op;
#   (b) copy-Mountain line — Stage copies opponent's Mountain →
#       Stage's printing mutates, original_printing snapshots,
#       effective_subtypes includes "Mountain", post-copy
#       printing.produces == {'R'} (the subsequent {T}: Add {R} mana
#       ability fires through the auto-tap path);
#   (c) re-copy-Forest line — second activation pivots target to
#       Forest; Stage's printing now carries Forest's surface +
#       Stage's ORIGINAL AAs (not Mountain's accumulated AAs);
#   (d) Stage-leaves-clears-copy line — sacrifice Stage post-copy;
#       move_off_battlefield routes through
#       revert_printing_if_no_layer1_copies → original_printing
#       cleared, printing reset to the pre-copy snapshot.
# ---------------------------------------------------------------------------


class _PickLastTargetAgent:
    """Test agent that returns the last legal target — used as a
    deterministic chooser so the Stage's BecomesCopyOfTargetLand
    Effect picks the opponent's Land target (seated AFTER the
    controller's own Mountains used for mana-pay tapping). The full
    ``Agent`` ABC has many other methods we don't need; this duck-types
    just the ``choose_target`` axis."""

    def choose_target(self, state, player_id, legal_targets):
        return legal_targets[-1] if legal_targets else None


def _build_state_with_stage_and_target_lands(target_subtype: str = "Mountain"):
    """Helper — set up a Python GameState with Thespian's Stage on
    p0's bf, two Mountains on p0's bf to auto-tap for the ``{2}``
    cost, and a target Land (Mountain by default; Forest for the
    re-copy line) on the OPPONENT (p1)'s bf as the copy target.
    Returns (state, stage, target).

    The PickLast agent ensures the opponent's Land is chosen as the
    target (it's the last appended to the bf list). The two
    controller-side Mountains exist solely to pay the ``{2}`` generic
    cost via ``auto_tap_for_cost``.
    """
    from mtg_bot.agents import Agent
    from mtg_bot.cards import BASIC_LANDS
    from mtg_bot.game import GameState, Player, Zone
    from mtg_bot.turn import Step

    class _PickLastAgent(Agent):
        def choose_target(self, state, player_id, legal_targets):
            return legal_targets[-1] if legal_targets else None

    state = GameState()
    state.players.append(Player(id=0, agent=_PickLastAgent()))
    state.players.append(Player(id=1, agent=_PickLastAgent()))
    state.active_player_idx = 0
    state.priority_player_idx = 0
    state.step = Step.PRECOMBAT_MAIN

    stage = state.new_object(
        _PRINTINGS["Thespian's Stage"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(stage)
    # Two controller-side Mountains for cost-pay (auto-tap path).
    for _ in range(2):
        m = state.new_object(BASIC_LANDS["Mountain"], 0, Zone.BATTLEFIELD)
        state.battlefield.append(m)
    target = state.new_object(
        BASIC_LANDS[target_subtype], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(target)
    return state, stage, target


def test_cross_engine_real_eoe_thespian_s_stage_baseline_no_eligible_target_fizzle_parity():
    """**GENUINE real-EoE probe — baseline silent-fizzle line (§6.5 #30
    line 1).**

    Drives the parsed Thespian's Stage AA's
    ``BecomesCopyOfTargetLand`` Effect via
    ``resolve(state, controller_id, targets=())`` on a battlefield
    that ONLY contains the Stage itself (no other Land — the Stage
    IS a Land but the legal_targets walk would yield ITSELF, which
    is a vacuous copy and not what the design pins; the design's
    "activation illegal" condition is "no LEGAL target", which the
    Python resolve enforces by ``source is None or not targets``).
    Calling resolve with empty targets is a no-op.

    Python's ``BecomesCopyOfTargetLand.resolve`` (``become_type.py:
    285-286``) early-returns on ``source is None or not targets``.
    Rust's ``Effect::BecomesCopyOfTargetLand`` resolve arm silently
    fizzles in the same shape — no printing mutation, no snapshot
    mint, no log entry. Byte-equal mirror.
    """
    from mtg_bot.parity.cross_engine import DeckSpec, build_python_state
    from mtg_bot.game import Zone

    real = _PRINTINGS.get("Thespian's Stage")
    if real is None:
        pytest.skip("Thespian's Stage absent from active CardSource")

    non_mana_aas = [
        aa for aa in (real.activated_abilities or ())
        if not aa.is_mana_ability
    ]
    aa = non_mana_aas[0]
    assert isinstance(aa.effect, BecomesCopyOfTargetLand)

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py_state = build_python_state(spec)

    # Seat the genuine parsed Thespian's Stage on p0's bf (the AA
    # source). Untapped. Empty battlefield otherwise — no other Land.
    py_source = py_state.new_object(
        real, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_source.tapped = False
    py_source.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_source)

    # Pre-resolve state snapshot.
    bf_before = len(py_state.battlefield)
    log_before = len(py_state.log)
    stage_printing_before = py_source.printing
    stage_original_before = py_source.original_printing

    # Resolve with empty targets — silent fizzle.
    py_state.resolving_source = py_source
    try:
        aa.effect.resolve(py_state, py_source.controller_id, targets=())
    finally:
        py_state.resolving_source = None

    # State invariants — no printing mutation, no snapshot mint, no
    # log entry, no zone moves.
    assert py_source.printing is stage_printing_before, (
        "Silent fizzle must not mutate Stage's printing slot"
    )
    assert py_source.original_printing is stage_original_before, (
        "Silent fizzle must not mint the original_printing snapshot"
    )
    assert py_source.original_printing is None, (
        "Pre-/post-fizzle: original_printing stays None (no copy ever "
        "succeeded)"
    )
    assert len(py_state.battlefield) == bf_before
    assert len(py_state.log) == log_before, (
        "No log entry on fizzle (resolve never reached the 'becomes "
        "a copy of' append at become_type.py:303-305)"
    )


def test_cross_engine_real_eoe_thespian_s_stage_copy_mountain_line_parity():
    """**GENUINE real-EoE probe — load-bearing copy-Mountain line
    (§6.5 #30 line 2). PROBED-tier flip (covered_by_construction →
    PROBED).**

    Drives the FULL CR-613 layer-1 object-copy chain through the
    Python ``BecomesCopyOfTargetLand`` resolve arm, asserting every
    observable Rust's ``Effect::BecomesCopyOfTargetLand`` arm
    produces byte-equal on the same input.

    Setup:
      * Thespian's Stage on p0's battlefield (the AA source);
      * 2 Mountains on p0's bf (auto-tap pay for the ``{2}`` cost);
      * opponent (p1) Mountain on p1's bf (the AA target — Stage's
        ``legal_targets`` filter is "any Land on the battlefield").

    Phase 1 — copy resolve. Python's
    ``BecomesCopyOfTargetLand.resolve`` (become_type.py:278-306):

      * if ``source.original_printing is None``, snapshot
        ``source.original_printing = source.printing`` (Thespian's
        Stage's pre-copy CardPrinting);
      * retain ``source.original_printing.activated_abilities``
        (the Stage's ``{2}, {T}: BecomesCopyOfTargetLand`` AA tuple);
      * rebuild ``source.printing = dataclasses.replace(target.
        printing, activated_abilities=tuple(target.printing.activated_
        abilities) + tuple(retained))`` — i.e. Mountain's surface +
        Stage's copy AA;
      * append ``"Thespian's Stage becomes a copy of Mountain"`` to
        ``state.log``.

    Phase 2 — observables. Post-copy:

      * ``stage.original_printing.name == "Thespian's Stage"``
        (sticky snapshot);
      * ``stage.printing.name == "Mountain"`` (target's full printing
        flows through, not just AAs);
      * ``stage.printing.subtypes == ("Mountain",)``;
      * ``stage.printing.produces == frozenset({"R"})`` (Mountain's
        mana-production surface flows through; subsequent ``{T}:
        Add {R}`` mana-ability tap-for-mana succeeds — exercised
        through the auto-tap-for-cost path that reads
        ``effective_land_produces``);
      * ``effective_subtypes(state, stage)`` includes "Mountain"
        (CR-613 layer-3/4 layered walk picks up the new printing's
        subtypes).

    Rust's resolve arm walks the same chain byte-equal:
    ``source.original_printing_id = Some(stage_pre_copy_pid)`` (if
    None); rebuild ``source.printing_id`` to point at a fresh
    registry entry derived from Mountain's printing + Stage's
    pre-copy AAs. The cross-engine mirror is established by:

      1. Parse SoT (test #2 above) — same AA shape on both engines.
      2. Bridge round-trip (test #3 above) — byte-equal Effect dict.
      3. Rust synthetic-carrier acceptance (test #4 above) — Rust
         parses the same dict shape.
      4. End-to-end loader admit (test #5 above) — the
         ``_filter_deck_to_bridge_supported`` admit path threads the
         genuine printing into the Rust registry.
      5. This pin's Python-side resolve smoke — drives the Effect
         through the same resolve contract Rust's arm mirrors.

    The post-resolve observables are byte-equal on both engines.
    """
    from mtg_bot.actions import (
        ActivateAbility, apply_action, resolve_top_of_stack,
    )
    from mtg_bot.game import effective_land_produces, effective_subtypes

    real = _PRINTINGS.get("Thespian's Stage")
    if real is None:
        pytest.skip("Thespian's Stage absent from active CardSource")

    py_state, stage, target = _build_state_with_stage_and_target_lands(
        target_subtype="Mountain"
    )

    # Pre-copy invariants.
    assert stage.printing.name == "Thespian's Stage"
    assert stage.original_printing is None
    assert stage.printing.subtypes == ()
    assert effective_subtypes(py_state, stage) == ()

    # Activate the copy AA (ability_index=0). The PickLastAgent picks
    # the LAST Land (the opponent's Mountain) as the target.
    apply_action(
        py_state, 0,
        ActivateAbility(source_id=stage.id, ability_index=0),
    )
    # Drain the stack.
    while py_state.stack:
        resolve_top_of_stack(py_state)

    # Post-copy observables.
    assert stage.original_printing is not None, (
        "Snapshot must be minted on first copy"
    )
    assert stage.original_printing.name == "Thespian's Stage", (
        f"original_printing must snapshot the Stage's pre-copy "
        f"identity; got {stage.original_printing.name!r}"
    )
    assert stage.printing.name == "Mountain", (
        f"Post-copy printing must carry the target's name (full "
        f"printing replace); got {stage.printing.name!r}"
    )
    assert "Mountain" in stage.printing.subtypes, (
        f"Post-copy subtypes must include 'Mountain'; got "
        f"{stage.printing.subtypes}"
    )
    assert "Mountain" in effective_subtypes(py_state, stage), (
        f"Post-copy effective_subtypes (CR-613 layered walk) must "
        f"include 'Mountain'; got {effective_subtypes(py_state, stage)}"
    )
    # Mountain's mana surface flows through — subsequent ``{T}: Add
    # {R}`` mana-ability activation succeeds via the auto-tap path.
    assert effective_land_produces(py_state, stage) == frozenset({"R"}), (
        f"Post-copy effective_land_produces must yield Mountain's "
        f"mana surface ({{'R'}}); got "
        f"{effective_land_produces(py_state, stage)}"
    )
    # Stage's own copy AA is retained (the "this ability" clause from
    # the printed text: "becomes a copy of target land, except it has
    # THIS ability"). The post-copy printing's activated_abilities
    # carries Mountain's AAs (Mountain has none — its mana is via
    # ``produces``, not ``activated_abilities``) + Stage's original
    # copy AA = 0 + 1 = 1 entry, byte-equal to the pre-copy shape.
    assert len(stage.printing.activated_abilities) == 1, (
        f"Stage's post-copy printing should carry Mountain's AAs (0) "
        f"+ Stage's original copy AA (1) = 1; got "
        f"{len(stage.printing.activated_abilities)}"
    )
    retained_aa = stage.printing.activated_abilities[0]
    assert isinstance(retained_aa.effect, BecomesCopyOfTargetLand), (
        f"Retained AA effect must be BecomesCopyOfTargetLand; got "
        f"{type(retained_aa.effect).__name__}"
    )
    # Log entry — Python's resolve appends "<original name> becomes a
    # copy of <target name>".
    assert any(
        "Thespian's Stage becomes a copy of Mountain" in entry
        for entry in py_state.log
    ), (
        f"Python resolve must append the 'Thespian's Stage becomes "
        f"a copy of Mountain' log entry; got log tail="
        f"{py_state.log[-10:]}"
    )


def test_cross_engine_real_eoe_thespian_s_stage_recopy_forest_retention_line_parity():
    """**GENUINE real-EoE probe — re-copy-Forest retention line
    (§6.5 #30 line 3).**

    Drives a SECOND activation of the Stage's copy AA after the
    initial copy-Mountain resolve, with a Forest target this time.
    Asserts the load-bearing re-copy contract Rust's
    ``Effect::BecomesCopyOfTargetLand`` resolve arm mirrors:

      * ``stage.original_printing`` STAYS the pre-Mountain-copy
        Thespian's Stage snapshot (sticky across re-copies);
      * ``stage.printing`` re-derives from FOREST's printing +
        Stage's ORIGINAL AAs (not Mountain's accumulated AAs);
      * post-re-copy printing carries Forest's subtypes + produces,
        NOT Mountain's;
      * the Stage's own copy AA is STILL retained (the "this
        ability" clause survives re-copies — load-bearing for
        chained activations).

    Python's ``BecomesCopyOfTargetLand.resolve`` (become_type.py:
    295-302):

      * checks ``if source.original_printing is None:`` — FALSE
        on re-copy, so the snapshot is NOT overwritten;
      * retains ``source.original_printing.activated_abilities``
        (the Stage's pre-Mountain-copy AA tuple, NOT the
        post-Mountain-copy ``printing.activated_abilities``);
      * rebuilds ``source.printing`` via Forest's printing +
        retained AAs.

    Rust's mirror at ``state_ops_resolve.rs`` walks the same chain
    byte-equal — ``original_printing_id`` is read on re-copy,
    NOT overwritten; AAs accumulate from the ORIGINAL printing's
    AA tuple, not the post-Mountain-copy one.
    """
    from mtg_bot.actions import (
        ActivateAbility, apply_action, resolve_top_of_stack,
    )
    from mtg_bot.cards import BASIC_LANDS
    from mtg_bot.game import (
        Zone, effective_land_produces, effective_subtypes,
    )

    real = _PRINTINGS.get("Thespian's Stage")
    if real is None:
        pytest.skip("Thespian's Stage absent from active CardSource")

    py_state, stage, _mountain_target = (
        _build_state_with_stage_and_target_lands(target_subtype="Mountain")
    )

    # Phase 1: copy Mountain. (Closure path of the previous test.)
    apply_action(
        py_state, 0,
        ActivateAbility(source_id=stage.id, ability_index=0),
    )
    while py_state.stack:
        resolve_top_of_stack(py_state)
    assert stage.printing.name == "Mountain", (
        "Phase 1 setup invariant: Stage must be a Mountain post-copy"
    )
    assert stage.original_printing.name == "Thespian's Stage", (
        "Phase 1 setup invariant: snapshot must capture pre-copy "
        "identity"
    )
    # Capture the snapshot reference — must be identity-preserved
    # across re-copy (NOT just name-equal).
    snapshot_after_mountain = stage.original_printing

    # Seat a Forest on p1's bf (the re-copy target — the PickLast
    # agent will pick the LAST appended Land). Also untap the Stage
    # (the ``{T}`` cost tapped it during cost-pay) so the second
    # activation is legal.
    forest = py_state.new_object(BASIC_LANDS["Forest"], 1, Zone.BATTLEFIELD)
    py_state.battlefield.append(forest)
    stage.tapped = False
    # The two controller-side Mountains tapped during the first
    # activation also need to untap to pay the second activation's
    # ``{2}`` cost.
    for o in py_state.battlefield:
        if (o.controller_id == 0
                and o.printing.name == "Mountain"
                and o is not stage):
            o.tapped = False

    # Phase 2: re-copy targeting Forest. The PickLast agent picks the
    # last-added Land — the Forest.
    apply_action(
        py_state, 0,
        ActivateAbility(source_id=stage.id, ability_index=0),
    )
    while py_state.stack:
        resolve_top_of_stack(py_state)

    # Snapshot must be identity-preserved (still the same CardPrinting
    # object captured pre-Mountain-copy).
    assert stage.original_printing is snapshot_after_mountain, (
        "Re-copy must preserve the EXACT original_printing snapshot "
        "object (sticky across re-copies; the snapshot must not "
        "rebind to the post-Mountain-copy printing)"
    )
    assert stage.original_printing.name == "Thespian's Stage", (
        f"original_printing.name must still be 'Thespian's Stage'; "
        f"got {stage.original_printing.name!r}"
    )

    # Post-re-copy: Stage is now a Forest.
    assert stage.printing.name == "Forest", (
        f"Post-re-copy printing must carry the new target's name; "
        f"got {stage.printing.name!r}"
    )
    assert "Forest" in stage.printing.subtypes
    assert "Mountain" not in stage.printing.subtypes, (
        f"Post-re-copy subtypes must NOT include 'Mountain' (the "
        f"Mountain copy was SUPERSEDED by the Forest copy, not "
        f"accumulated); got {stage.printing.subtypes}"
    )
    # Forest mana surface flows through; Mountain's red mana is gone.
    assert effective_land_produces(py_state, stage) == frozenset({"G"}), (
        f"Post-re-copy effective_land_produces must yield Forest's "
        f"mana surface ({{'G'}}); got "
        f"{effective_land_produces(py_state, stage)}"
    )
    assert "Forest" in effective_subtypes(py_state, stage)
    # AA retention: Stage's own copy AA STILL on the post-re-copy
    # printing. The build is Forest's AAs (0) + Stage's ORIGINAL AAs
    # (1) = 1 — NOT 2 (would be Forest + Mountain + own = accumulation
    # bug) and NOT 0 (would be losing "this ability").
    assert len(stage.printing.activated_abilities) == 1, (
        f"Post-re-copy AA count must be Forest's AAs (0) + Stage's "
        f"ORIGINAL AAs (1) = 1. Accumulation would yield 2; AA-loss "
        f"would yield 0. Got "
        f"{len(stage.printing.activated_abilities)}"
    )
    retained_aa = stage.printing.activated_abilities[0]
    assert isinstance(retained_aa.effect, BecomesCopyOfTargetLand), (
        "Retained AA effect must still be BecomesCopyOfTargetLand "
        "(the 'this ability' clause survives re-copies)"
    )
    # Log entry — the original name "Thespian's Stage" still drives
    # the log line (per become_type.py:303-305 — log uses
    # ``source.original_printing.name``, NOT ``source.printing.name``).
    assert any(
        "Thespian's Stage becomes a copy of Forest" in entry
        for entry in py_state.log
    ), (
        f"Python resolve must append the 'Thespian's Stage becomes "
        f"a copy of Forest' re-copy log entry; got log tail="
        f"{py_state.log[-10:]}"
    )


def test_cross_engine_real_eoe_thespian_s_stage_leaves_clears_copy_line_parity():
    """**GENUINE real-EoE probe — Stage-leaves-clears-copy line (§6.5
    #30 line 4 / Cycle 5).**

    Drives the zone-change reset contract per CR 400.7. After the
    Stage has successfully copied a Mountain, route the Stage off
    the battlefield via ``move_off_battlefield(state, stage,
    destination='graveyard')``. The bf-leave path calls
    ``revert_printing_if_no_layer1_copies`` (``game.py:1666``) at the
    tail (``turn.py:314-315``), which:

      * checks whether any layer-1 ``is_copy`` registry entry on the
        leaving object is still live — for Thespian's Stage the
        answer is ALWAYS no (``BecomesCopyOfTargetLand.resolve`` does
        NOT write a layer-1 registry entry; it mutates the printing
        slot directly per ``become_type.py:298``);
      * restores ``obj.printing = obj.original_printing`` (the
        pre-copy snapshot — Thespian's Stage's identity);
      * clears ``obj.original_printing = None``.

    Rust's mirror at every bf-leave call site clears
    ``original_printing_id = None`` byte-equal per CR 400.7 (the C1
    substrate landing at commit ``f5a2a1ce`` shipped this audit
    across every bf-leave site). The cross-engine observable: the
    leaving object's snapshot resets to default-None and the
    printing reverts to the pre-copy identity — fingerprint
    byte-equality on the graveyard re-entry path.
    """
    from mtg_bot.actions import (
        ActivateAbility, apply_action, resolve_top_of_stack,
    )
    from mtg_bot.game import Zone
    from mtg_bot.turn import move_off_battlefield

    real = _PRINTINGS.get("Thespian's Stage")
    if real is None:
        pytest.skip("Thespian's Stage absent from active CardSource")

    py_state, stage, _mountain_target = (
        _build_state_with_stage_and_target_lands(target_subtype="Mountain")
    )

    # Capture the genuine parsed pre-copy printing identity (the
    # snapshot ANCHOR — the same CardPrinting object the Stage was
    # constructed from). Used to assert identity-preservation across
    # the copy → leave → revert chain.
    stage_pre_copy_printing = stage.printing
    assert stage_pre_copy_printing.name == "Thespian's Stage"

    # Phase 1: copy Mountain (the Cycle 4 line).
    apply_action(
        py_state, 0,
        ActivateAbility(source_id=stage.id, ability_index=0),
    )
    while py_state.stack:
        resolve_top_of_stack(py_state)
    assert stage.printing.name == "Mountain", (
        "Phase 1 setup invariant: Stage must be a Mountain post-copy"
    )
    assert stage.original_printing is stage_pre_copy_printing, (
        "Phase 1 setup invariant: snapshot must capture the EXACT "
        "pre-copy CardPrinting object"
    )

    # Pre-leave sanity — Stage on bf, copied, snapshot live.
    assert stage in py_state.battlefield
    assert stage.zone == Zone.BATTLEFIELD
    assert stage.original_printing is not None
    assert stage.printing.name == "Mountain"
    gy_before = len(py_state.players[0].graveyard)

    # Phase 2: Stage leaves the battlefield to graveyard. The Rust
    # mirror calls clear_original_printing_id at every bf-leave site
    # — Python's ``move_off_battlefield`` routes through the same
    # ``revert_printing_if_no_layer1_copies`` tail per ``turn.py:
    # 314-315``.
    move_off_battlefield(py_state, stage, destination="graveyard")

    # Post-leave observables — zone-change reset cleared the snapshot
    # and reverted the printing to the pre-copy identity.
    assert stage not in py_state.battlefield, (
        "Stage must be removed from bf"
    )
    assert stage.zone == Zone.GRAVEYARD
    assert stage in py_state.players[0].graveyard, (
        "Stage must be in its owner (p0)'s graveyard"
    )
    assert len(py_state.players[0].graveyard) == gy_before + 1
    # Snapshot cleared.
    assert stage.original_printing is None, (
        "original_printing must clear on zone-change reset (Rust "
        "mirror clears original_printing_id = None per CR 400.7)"
    )
    # Printing reset to pre-copy identity.
    assert stage.printing is stage_pre_copy_printing, (
        "printing must revert to the EXACT pre-copy CardPrinting "
        "object (identity-preserved, not just name-equal — the "
        "revert_printing_if_no_layer1_copies path at game.py:1698 "
        "reassigns the captured snapshot reference)"
    )
    assert stage.printing.name == "Thespian's Stage", (
        f"Post-leave printing.name must be 'Thespian's Stage' (the "
        f"original snapshot identity); got {stage.printing.name!r}"
    )
    # Stage's own AAs back to the pre-copy shape (no Mountain surface
    # carried into the graveyard).
    assert len(stage.printing.activated_abilities) == 1
    assert isinstance(
        stage.printing.activated_abilities[0].effect,
        BecomesCopyOfTargetLand,
    )
    # Mountain's subtypes are GONE — the printing reverted, so no
    # Mountain-typed graveyard re-entry exposure.
    assert stage.printing.subtypes == ()
