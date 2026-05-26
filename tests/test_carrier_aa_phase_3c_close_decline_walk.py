"""Carrier-AA Phase 3C — decline-set walk close-out (§6.4 #25-27).

Closes the Phase 3C campaign per
``docs/CARRIER_AA_SUBSTRATE_PHASE_3_DESIGN.md`` §6.4 with three
load-bearing pins that codify the 7-card admit set + 23-card decline
residue + Phase 4+ deferral assertions over the live EoE pool:

* **#25 (live-printing parametrized walk over the 30-card Phase-2-
  residue).** Walks the same 30 carriers the Phase 2 §2.1 walk pinned
  and asserts EXACTLY the 7 expected admits and EXACTLY the 23
  expected declines after the Phase-3 sub-phases (3A: Mystifying
  Maze; 3B: Scavenger Grounds; 3C: Thespian's Stage) all land. This
  sibling sits alongside the existing
  ``test_carrier_aa_30_no_silent_auto_grow_admit_set_...`` walk at
  ``test_carrier_aa_phase_1_substrate_cycle_2.py:501`` — the C2 walk
  asserts the ADMIT side via the LAND-only predicate; THIS pin
  asserts both ADMIT and DECLINE sides on the **dispatcher**
  (``_printing_is_bridge_simple_carrier_aa_any``), which is the
  production OR-chain entry point per the Phase-4A keystone widen at
  commit ``a6fe7c9c``.

* **#26 (subsystem-attribution exhaustive pin).** Walks the FULL
  live EoE pool (not just the 30-card residue) and asserts EXACTLY
  7 LAND admits + 0 ARTIFACT admits. Confirms the Phase-3 positive
  set is exhaustive: no other EoE card pops into the Carrier-AA
  admit gate after the Phase-3 widens. Any future widen (Phase 4+
  multi-AA or per-rider) would surface here as a silent auto-grow.

* **#27 (Phase 4+ deferral assertions).** Every multi-AA Carrier-AA
  carrier + every rider-cluster card stays honestly DECLINED at the
  Phase-3-close admit gate. The 6 explicit Phase-4 / Phase-N
  carriers (Mirrorpool / Ghost Vacuum / Keys to the House /
  All-Fates Scroll / Haunted Screen / The Eternity Elevator) MUST
  decline on the dispatcher AND on both sub-predicates (LAND
  sibling + ARTIFACT sibling — the Phase-4A keystone substrate
  added the ARTIFACT predicate, and Phase 4B/C/D/E ship the per-card
  FLIPs). Honest decline at the dispatcher level is the Phase-3-
  close invariant; any Phase-4+ widen MUST flip this assertion in
  lockstep with the corresponding Phase-4 sub-phase landing.

The 30-card Phase-2-residue list mirrors the canonical roster used
by ``test_carrier_aa_30_no_silent_auto_grow_admit_set_*`` at
``test_carrier_aa_phase_1_substrate_cycle_2.py:551`` (the
admit-axis sibling — kept in lockstep here).
"""

from __future__ import annotations

import pytest


_CARRIER_AA_30_RESIDUE = (
    "All-Fates Scroll", "Ancient Tomb", "Atomic Microsizer",
    "Auxiliary Boosters", "Baseball Bat", "Blast Zone",
    "Contested War Zone", "Deserted Temple", "Ghost Vacuum",
    "Grove of the Burnwillows", "Haunted Screen",
    "Keys to the House", "Lavaclaw Reaches", "Lotus Field",
    "Meteor Crater", "Mirrorpool", "Mystifying Maze",
    "Nesting Grounds", "Petrified Field", "Pinnacle Starcage",
    "Reflecting Pool", "Robe of Stars", "Saw", "Scavenger Grounds",
    "Sliver Overlord", "Swarmyard", "Terrain Generator",
    "The Eternity Elevator", "Thespian's Stage",
    "Wandering Fumarole",
)

_PHASE_3_ADMIT_SET = (
    "Deserted Temple",
    "Mystifying Maze",
    "Petrified Field",
    "Scavenger Grounds",
    "Swarmyard",
    "Terrain Generator",
    "Thespian's Stage",
)

_PHASE_3_DECLINE_RESIDUE = tuple(
    sorted(set(_CARRIER_AA_30_RESIDUE) - set(_PHASE_3_ADMIT_SET))
)

_PHASE_4_DEFERRAL_CARRIERS = (
    "Mirrorpool",
    "Ghost Vacuum",
    "Keys to the House",
    # All-Fates Scroll was here pre-Phase-4E-C2; Phase 4E C2's partial-
    # FLIP (2026-05-26) widens the per-AA admit predicate so the
    # Artifact-typed sub-predicate + dispatcher now PASS. The card
    # STAYS DECLINED at the cross-engine builder gate via the "any"
    # color teeth at the bridge floor; full FLIP defers to Phase 4E
    # C2.5 (Rust ManaPool "any" coin substrate). See
    # `tests/test_carrier_aa_phase_4e_substrate_cycle_2.py` for the
    # partial-FLIP teeth-trace pin set.
    "Haunted Screen",
    "The Eternity Elevator",
)

# Phase 4E C2 partial-FLIP carriers — pass the per-AA admit predicate
# + Artifact sub-predicate + dispatcher; STAY DECLINED at the cross-
# engine builder gate (the "any" color teeth in the bridge floor's
# AddManaToPool forward arm).
_PHASE_4E_C2_BUILDER_DECLINE_CARRIERS = (
    "All-Fates Scroll",
)


# ---------------------------------------------------------------------------
# §6.4 #25 — live-printing parametrized walk (admit + decline sides)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("card_name", _PHASE_3_ADMIT_SET)
def test_phase_3c_close_dispatcher_admits_each_carrier_aa_admit(card_name):
    """**§6.4 #25 (admit-axis parametrized walk).** Every card in the
    Phase-3-close 7-card admit set passes the production
    ``_printing_is_bridge_simple_carrier_aa_any`` dispatcher. The
    dispatcher delegates to the LAND sibling (the Phase-3-close
    admits are all Land carriers).

    Mirrors the Phase-2 admit-side pin
    ``test_carrier_aa_30_no_silent_auto_grow_admit_set_swarmyard_plus_
    deserted_temple_plus_petrified_field_plus_terrain_generator_plus_
    mystifying_maze_plus_scavenger_grounds_plus_thespians_stage`` at
    ``test_carrier_aa_phase_1_substrate_cycle_2.py:501``, but
    parametrized per-card on the **dispatcher** (the production OR-
    chain entry point per the Phase-4A keystone substrate at commit
    ``a6fe7c9c``)."""
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity import trajectory as traj

    ps = OracleParserCardSource().get_printings()
    assert card_name in ps, (
        f"{card_name} must be parser-claimed by the active CardSource"
    )
    p = ps[card_name]
    assert traj._printing_is_bridge_simple_carrier_aa_any(p) is True, (
        f"{card_name} must ADMIT at the Carrier-AA dispatcher post-"
        f"Phase-3-close. A regression in the dispatcher or in either "
        f"sub-predicate (LAND / ARTIFACT) would flip this assertion."
    )


@pytest.mark.parametrize("card_name", _PHASE_3_DECLINE_RESIDUE)
def test_phase_3c_close_dispatcher_declines_each_phase_2_residue(card_name):
    """**§6.4 #25 (decline-axis parametrized walk).** Every card in
    the Phase-3-close decline residue declines at the production
    ``_printing_is_bridge_simple_carrier_aa_any`` dispatcher OR
    declines at the cross-engine builder gate (the Phase 4E C2
    partial-FLIP teeth).

    Decline-reason taxonomy (per the design doc §6.4 #27 deferral
    framing + Phase 4E C2's partial-FLIP teeth):
      * Phase 4+ multi-AA carriers (Mirrorpool / Ghost Vacuum / Keys
        to the House / Haunted Screen / The Eternity Elevator) —
        decline on the multi-AA per-AA Effect-class + AA-rider teeth
        (sorcery_speed) at the dispatcher per the Phase-4A C1
        substrate at commit ``a6fe7c9c``;
      * All-Fates Scroll — passes the dispatcher post-Phase 4E C2's
        partial-FLIP widen but STAYS DECLINED at the cross-engine
        builder gate via the "any" color teeth in the bridge floor's
        ``AddManaToPool`` forward arm. Phase 4E C2.5 (Rust ManaPool
        "any" coin substrate) closes the gap.
      * Phase N cost-shape declines (Reflecting Pool / Meteor Crater
        / Grove of the Burnwillows / Lotus Field / Ancient Tomb /
        Nesting Grounds / Blast Zone / Lavaclaw Reaches / Wandering
        Fumarole / Contested War Zone / Pinnacle Starcage /
        Auxiliary Boosters / Baseball Bat) — decline on colored /
        x-pip / pay_life / sacrifice_another_* / activate_only_once
        cost-bool gates at the dispatcher;
      * Phase N rider-cluster declines (Sliver Overlord / Robe of
        Stars / Saw / Atomic Microsizer) — decline on
        non-Carrier-AA Effect class teeth at the dispatcher.

    Any flip on a card in this list MUST land in lockstep with the
    corresponding Phase-4+ substrate widen — a silent flip surfaces
    here as a test failure."""
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity import trajectory as traj

    ps = OracleParserCardSource().get_printings()
    assert card_name in ps, (
        f"{card_name} must be parser-claimed by the active CardSource"
    )
    p = ps[card_name]
    # Phase 4E C2 partial-FLIP exception path — All-Fates Scroll
    # passes the dispatcher (the per-AA admit gate widens) but
    # declines at the cross-engine builder gate (the bridge floor's
    # "any" color teeth in AddManaToPool forward arm).
    if card_name in _PHASE_4E_C2_BUILDER_DECLINE_CARRIERS:
        assert traj._printing_is_bridge_simple_carrier_aa_any(p) is True, (
            f"{card_name} must PASS the Carrier-AA dispatcher post-"
            f"Phase 4E C2's partial-FLIP widens (per-AA gate lifted "
            f"is_mana_ability + AddManaToPool Effect-class teeth)"
        )
        # But the cross-engine builder gate honest-declines on the
        # "any" teeth.
        assert traj._carrier_aa_artifact_card_def(p) is None, (
            f"{card_name} must DECLINE at the cross-engine builder "
            f"gate (the 'any' color teeth in the bridge floor's "
            f"AddManaToPool forward arm). Phase 4E C2.5 closes the "
            f"Rust ManaPool 'any' coin substrate gap."
        )
    else:
        assert traj._printing_is_bridge_simple_carrier_aa_any(p) is False, (
            f"{card_name} must DECLINE at the Carrier-AA dispatcher "
            f"post-Phase-3-close. A silent admit-gate auto-grow would "
            f"flip this assertion — any Phase-4+ widen MUST update "
            f"this parametrized walk in lockstep."
        )


# ---------------------------------------------------------------------------
# §6.4 #26 — subsystem-attribution exhaustive pin over the full EoE pool
# ---------------------------------------------------------------------------


def test_phase_3c_close_carrier_aa_land_admit_set_is_exhaustive_over_eoe_pool():
    """**§6.4 #26 (subsystem-attribution exhaustive pin — LAND axis,
    LOADER-SIDE).** Walks the FULL live EoE pool and asserts EXACTLY
    the 7-card Phase-3-close admit set passes the cross-engine
    builder ``_carrier_aa_land_card_def`` (loader-side admit gate).

    Re-anchored to the loader-side admit gate at Phase 4E C2's
    partial-FLIP landing (2026-05-26). The predicate-level admit
    set may silently auto-grow under the C2 widens (the
    ``AddManaToPool`` Effect-class admit matches live EoE mana-
    ability lands like Crystal Quarry / Eldrazi Temple / Gemstone
    Caverns / Sunken Citadel that pass the per-AA predicate but
    decline at the bridge floor on multi-pair / spend_restriction /
    "any" teeth); the loader-side admit set is what
    ``_filter_deck_to_bridge_supported`` actually consults, NOT the
    predicate alone.

    The Phase-3-close LOADER-SIDE positive set is exhaustive over the
    live EoE pool — any Phase-4+ widen would surface here as a
    silent auto-grow."""
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity import trajectory as traj

    ps = OracleParserCardSource().get_printings()
    admits = sorted(
        name
        for name, p in ps.items()
        if traj._carrier_aa_land_card_def(p) is not None
    )
    assert admits == list(_PHASE_3_ADMIT_SET), (
        f"Phase 3C C5 subsystem-attribution LOADER-SIDE LAND pin "
        f"violated. _carrier_aa_land_card_def must admit EXACTLY "
        f"the 7-card Phase-3-close set {list(_PHASE_3_ADMIT_SET)}, "
        f"got {admits}. A silent auto-grow indicates a Phase-4+ "
        f"widen landed without inverting this assertion — "
        f"investigate before merging."
    )


def test_phase_3c_close_carrier_aa_artifact_admit_set_is_empty_over_eoe_pool():
    """**§6.4 #26 (subsystem-attribution exhaustive pin — ARTIFACT
    axis, LOADER-SIDE).** Walks the FULL live EoE pool and asserts
    EXACTLY 0 cards admit at the cross-engine builder
    ``_carrier_aa_artifact_card_def`` (loader-side admit gate).

    Re-anchored to the loader-side admit gate at Phase 4E C2's
    partial-FLIP landing (2026-05-26). The Artifact admit predicate
    now passes All-Fates Scroll post-C2 widens, but the cross-engine
    builder STILL returns None on the "any" color teeth in the bridge
    floor's ``AddManaToPool`` forward arm — so the loader-side
    Artifact admit set stays empty at C2 close. Phase 4E C2.5 ships
    +1 (All-Fates Scroll FLIPs ADMITTED at the builder gate); Phase
    4C / 4D ship Ghost Vacuum + Keys to the House.

    Each loader-side FLIP MUST update this assertion in lockstep."""
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity import trajectory as traj

    ps = OracleParserCardSource().get_printings()
    admits = sorted(
        name
        for name, p in ps.items()
        if traj._carrier_aa_artifact_card_def(p) is not None
    )
    assert admits == [], (
        f"Phase 3C C5 subsystem-attribution LOADER-SIDE ARTIFACT axis "
        f"pin violated. _carrier_aa_artifact_card_def must admit ZERO "
        f"live EoE cards at Phase-3 close / Phase-4E C2 partial-FLIP; "
        f"got {admits}. Any Phase-4 sub-phase loader-side FLIP MUST "
        f"flip this assertion in lockstep."
    )


def test_phase_3c_close_dispatcher_admit_set_is_exhaustive_over_eoe_pool():
    """**§6.4 #26 (subsystem-attribution exhaustive pin — DISPATCHER
    axis, predicate-level).** Walks the FULL live EoE pool and
    asserts the predicate-level dispatcher
    ``_printing_is_bridge_simple_carrier_aa_any`` admits the 7 LAND
    Phase-3-close admits PLUS All-Fates Scroll (the Phase 4E C2
    partial-FLIP — passes the Artifact predicate sub-axis) PLUS the
    live EoE mana-ability lands the Phase 4E C2 Effect-class widen
    admits at the per-AA predicate (Crystal Quarry / Eldrazi Temple
    / Gemstone Caverns / Sunken Citadel — none of which are
    Carrier-AA admit targets; each declines at the cross-engine
    builder gate on multi-pair / spend_restriction / "any" / etc.
    teeth).

    The loader-side admit gate (the cross-engine builders) is what
    ``_filter_deck_to_bridge_supported`` actually consults; the
    predicate-level admit set may diverge from the loader-side set
    under the Phase 4E C2 partial-FLIP — see the LOADER-SIDE
    exhaustive pins above for the authoritative admit set."""
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity import trajectory as traj

    ps = OracleParserCardSource().get_printings()
    admits = sorted(
        name
        for name, p in ps.items()
        if traj._printing_is_bridge_simple_carrier_aa_any(p)
    )
    # Post-Phase-4E-C2 predicate-level expected set: the 7 LAND
    # Phase-3-close admits + All-Fates Scroll (C2 partial-FLIP) + 4
    # live EoE mana-ability lands the AddManaToPool Effect-class
    # widen admits at the per-AA predicate (each declines at the
    # cross-engine builder gate via the bridge floor teeth — see
    # the LOADER-SIDE pins above).
    expected_post_c2 = sorted(
        set(_PHASE_3_ADMIT_SET) | {
            "All-Fates Scroll",
            # Live EoE mana-ability lands that pass the per-AA gate
            # post-Phase-4E-C2 widens but decline at the builder.
            "Crystal Quarry",       # multi-pair WUBRG declines at bridge floor
            "Eldrazi Temple",       # AA[1] spend_restriction="colorless_eldrazi" declines
            "Gemstone Caverns",     # produces=("any", 1) declines on "any" teeth
            "Sunken Citadel",       # AA[0] produces=("any", 1) + subtypes=("Cave",)
        }
    )
    assert admits == expected_post_c2, (
        f"Phase 3C C5 dispatcher exhaustive-walk pin violated post-"
        f"Phase-4E-C2 partial-FLIP. Expected {expected_post_c2}, "
        f"got {admits}. The dispatcher delegates LAND ∪ ARTIFACT; "
        f"silent admit-set growth on either sub-predicate surfaces "
        f"here. NOTE: the predicate-level admit set is NOT the same "
        f"as the loader-side admit gate — see the LOADER-SIDE pins."
    )


# ---------------------------------------------------------------------------
# §6.4 #27 — Phase 4+ deferral assertions
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("card_name", _PHASE_4_DEFERRAL_CARRIERS)
def test_phase_3c_close_phase_4_carrier_declines_on_both_sub_predicates_and_dispatcher(
    card_name,
):
    """**§6.4 #27 (Phase 4+ deferral assertions — per-carrier walk).**
    Every Phase-4 / Phase-N multi-AA Carrier-AA carrier
    (Mirrorpool / Ghost Vacuum / Keys to the House / All-Fates
    Scroll / Haunted Screen / The Eternity Elevator) declines on
    BOTH sub-predicates (LAND sibling + ARTIFACT sibling) AND on
    the dispatcher.

    The Phase-4A C1 keystone substrate at commit ``a6fe7c9c`` codifies
    the per-AA decline reasons:
      * Mirrorpool — declines on per-AA Effect-class teeth
        (CopyTargetInstantOrSorceryYouControl +
        CreateTokenCopyOfTargetCreatureYouControl not in the
        Phase-3-close 7-class admit set; Phase 4B widens);
      * Ghost Vacuum — declines on per-AA sorcery_speed AA-rider
        teeth (AA[1] sorcery_speed=True) + Effect-class teeth;
        Phase 4C widens;
      * Keys to the House — declines on per-AA sorcery_speed AA-
        rider teeth + Effect-class teeth; Phase 4D widens;
      * All-Fates Scroll — declines on per-AA is_mana_ability AA-
        rider teeth (AA[0] is_mana_ability=True) + Effect-class
        teeth; Phase 4E widens;
      * Haunted Screen — declines on n_aa=3 + activate_only_once
        AA-rider; Phase 5+ deferral;
      * The Eternity Elevator — declines on
        AddChargeCounterManaOfChosenColor Spacecraft-station-
        threshold-adjacent shape; Phase 5+ deferral.

    Any Phase-4 sub-phase FLIP MUST flip this assertion for the
    corresponding card in lockstep with the sub-phase's per-AA
    teeth widen."""
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity import trajectory as traj

    ps = OracleParserCardSource().get_printings()
    if card_name not in ps:
        pytest.skip(
            f"{card_name} absent from active CardSource — "
            f"expected for some EoE printings during pool refreshes"
        )
    p = ps[card_name]
    # Both sub-predicates must decline.
    assert traj._printing_is_bridge_simple_carrier_aa_land(p) is False, (
        f"{card_name} must DECLINE at the LAND sub-predicate "
        f"(_printing_is_bridge_simple_carrier_aa_land) at Phase 3C "
        f"close. A flip here would indicate a Phase-4+ admit-set "
        f"widen landed without updating this pin."
    )
    assert traj._printing_is_bridge_simple_carrier_aa_artifact(p) is False, (
        f"{card_name} must DECLINE at the ARTIFACT sub-predicate "
        f"(_printing_is_bridge_simple_carrier_aa_artifact) at Phase "
        f"3C close. A flip here would indicate a Phase-4+ Artifact "
        f"FLIP landed without updating this pin."
    )
    # Dispatcher must decline (delegation invariant).
    assert traj._printing_is_bridge_simple_carrier_aa_any(p) is False, (
        f"{card_name} must DECLINE at the dispatcher "
        f"(_printing_is_bridge_simple_carrier_aa_any) at Phase 3C "
        f"close. Honest decline at the dispatcher is the Phase-3-"
        f"close invariant."
    )


def test_phase_3c_close_loader_side_admit_set_size_matches_design_doc():
    """**§6.4 #27 (Phase-3-close LOADER-SIDE size invariant).** The
    LOADER-SIDE admit set carries EXACTLY 7 cards post-Phase-4E-C2 —
    matches the design doc §6.4 #26 expected positive set. A silent
    size delta (either direction) is a campaign-tracker bug.

    Re-anchored to the loader-side admit gate at Phase 4E C2's
    partial-FLIP landing (2026-05-26). The predicate-level admit
    set is +5 cards (All-Fates Scroll + Crystal Quarry / Eldrazi
    Temple / Gemstone Caverns / Sunken Citadel under the C2
    AddManaToPool widen), but all 5 decline at the cross-engine
    builder gate — the LOADER-SIDE set is what
    ``_filter_deck_to_bridge_supported`` consults.

    The 7-card LOADER-SIDE admit set tracks the design doc §10.3
    acceptance item 7 ("the 26-card decline-set walk confirms
    exactly the 7-card admit set"); this pin is the size-axis
    sibling."""
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity import trajectory as traj

    ps = OracleParserCardSource().get_printings()
    # LOADER-SIDE admit set: cards that produce a non-None CardDef
    # from EITHER the Land sibling OR the Artifact sibling.
    loader_admit_count = sum(
        1 for p in ps.values()
        if (
            traj._carrier_aa_land_card_def(p) is not None
            or traj._carrier_aa_artifact_card_def(p) is not None
        )
    )
    assert loader_admit_count == 7, (
        f"Phase 3C close LOADER-SIDE admit-set size invariant "
        f"violated: expected exactly 7 cards, got {loader_admit_count}. "
        f"The design doc §6.4 #26 positive set is exhaustive over the "
        f"live EoE pool at Phase-3 close / Phase-4E C2 partial-FLIP."
    )
