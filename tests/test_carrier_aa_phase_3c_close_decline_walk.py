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
    "All-Fates Scroll",
    "Haunted Screen",
    "The Eternity Elevator",
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
    the 23-card Phase-3-close decline residue (the 30-card Phase-2
    residue minus the 7-card Phase-3 admit set) declines at the
    production ``_printing_is_bridge_simple_carrier_aa_any``
    dispatcher.

    These 23 cards split into two structural decline reasons (per
    the design doc §6.4 #27 deferral framing):
      * Phase 4+ multi-AA carriers (Mirrorpool / Ghost Vacuum / Keys
        to the House / All-Fates Scroll / Haunted Screen / The
        Eternity Elevator) — decline on the multi-AA per-AA
        Effect-class + AA-rider teeth (sorcery_speed,
        is_mana_ability) per the Phase-4A C1 substrate at commit
        ``a6fe7c9c``;
      * Phase N cost-shape declines (Reflecting Pool / Meteor Crater
        / Grove of the Burnwillows / Lotus Field / Ancient Tomb /
        Nesting Grounds / Blast Zone / Lavaclaw Reaches / Wandering
        Fumarole / Contested War Zone / Pinnacle Starcage /
        Auxiliary Boosters / Baseball Bat) — decline on colored /
        x-pip / pay_life / sacrifice_another_* / activate_only_once
        cost-bool gates;
      * Phase N rider-cluster declines (Sliver Overlord / Robe of
        Stars / Saw / Atomic Microsizer) — decline on
        non-Carrier-AA Effect class teeth.

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
    assert traj._printing_is_bridge_simple_carrier_aa_any(p) is False, (
        f"{card_name} must DECLINE at the Carrier-AA dispatcher post-"
        f"Phase-3-close. A silent admit-gate auto-grow would flip "
        f"this assertion — any Phase-4+ widen MUST update this "
        f"parametrized walk in lockstep."
    )


# ---------------------------------------------------------------------------
# §6.4 #26 — subsystem-attribution exhaustive pin over the full EoE pool
# ---------------------------------------------------------------------------


def test_phase_3c_close_carrier_aa_land_admit_set_is_exhaustive_over_eoe_pool():
    """**§6.4 #26 (subsystem-attribution exhaustive pin — LAND axis).**
    Walks the FULL live EoE pool and asserts EXACTLY the 7-card
    Phase-3-close admit set passes
    ``_printing_is_bridge_simple_carrier_aa_land``. No other EoE
    printing slips through.

    The Phase-3-close positive set is exhaustive over the live EoE
    pool — any Phase-4+ widen (multi-AA admit predicate, per-rider
    cost-shape widen, new Effect-class admit) would surface here as
    a silent auto-grow."""
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity import trajectory as traj

    ps = OracleParserCardSource().get_printings()
    admits = sorted(
        name
        for name, p in ps.items()
        if traj._printing_is_bridge_simple_carrier_aa_land(p)
    )
    assert admits == list(_PHASE_3_ADMIT_SET), (
        f"Phase 3C C5 subsystem-attribution pin violated. "
        f"_printing_is_bridge_simple_carrier_aa_land must admit "
        f"EXACTLY the 7-card Phase-3-close set "
        f"{list(_PHASE_3_ADMIT_SET)}, got {admits}. A silent auto-"
        f"grow indicates a Phase-4+ widen landed without inverting "
        f"this assertion — investigate before merging."
    )


def test_phase_3c_close_carrier_aa_artifact_admit_set_is_empty_over_eoe_pool():
    """**§6.4 #26 (subsystem-attribution exhaustive pin — ARTIFACT
    axis).** Walks the FULL live EoE pool and asserts EXACTLY 0
    cards pass ``_printing_is_bridge_simple_carrier_aa_artifact``.
    The Phase-4A keystone substrate (commit ``a6fe7c9c``) added the
    ARTIFACT sibling predicate as substrate-only landing — ZERO live
    EoE cards admit on it at Phase-3 close.

    Phase 4B/4C/4D/4E ship per-card FLIPs that flip individual
    Artifact carriers (Ghost Vacuum / Keys to the House / All-Fates
    Scroll); each FLIP MUST update this assertion in lockstep."""
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity import trajectory as traj

    ps = OracleParserCardSource().get_printings()
    admits = sorted(
        name
        for name, p in ps.items()
        if traj._printing_is_bridge_simple_carrier_aa_artifact(p)
    )
    assert admits == [], (
        f"Phase 3C C5 subsystem-attribution ARTIFACT axis pin "
        f"violated. _printing_is_bridge_simple_carrier_aa_artifact "
        f"must admit ZERO live EoE cards at Phase-3 close (it's "
        f"substrate-only landing per Phase-4A C1 at commit "
        f"``a6fe7c9c``); got {admits}. Any Phase-4 sub-phase widen "
        f"that admits an Artifact carrier MUST flip this assertion "
        f"in lockstep."
    )


def test_phase_3c_close_dispatcher_admit_set_is_exhaustive_over_eoe_pool():
    """**§6.4 #26 (subsystem-attribution exhaustive pin — DISPATCHER
    axis).** Walks the FULL live EoE pool and asserts EXACTLY the
    7-card Phase-3-close admit set passes the production OR-chain
    dispatcher ``_printing_is_bridge_simple_carrier_aa_any``.

    Sibling of the LAND-only walk above — exercises the dispatcher
    rather than the bare sibling predicate. The two MUST agree post-
    Phase-3-close (LAND admits = 7, ARTIFACT admits = 0, dispatcher
    admits = LAND ∪ ARTIFACT = 7); any divergence indicates the
    dispatcher delegation broke."""
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity import trajectory as traj

    ps = OracleParserCardSource().get_printings()
    admits = sorted(
        name
        for name, p in ps.items()
        if traj._printing_is_bridge_simple_carrier_aa_any(p)
    )
    assert admits == list(_PHASE_3_ADMIT_SET), (
        f"Phase 3C C5 dispatcher exhaustive-walk pin violated. "
        f"_printing_is_bridge_simple_carrier_aa_any must admit "
        f"EXACTLY the 7-card Phase-3-close set "
        f"{list(_PHASE_3_ADMIT_SET)}, got {admits}. The dispatcher "
        f"delegates LAND ∪ ARTIFACT; a silent admit-set growth on "
        f"either sub-predicate surfaces here."
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


def test_phase_3c_close_admit_set_size_matches_design_doc():
    """**§6.4 #27 (Phase-3-close size invariant).** The Phase-3-close
    admit set carries EXACTLY 7 cards — matches the design doc §6.4
    #26 expected positive set. A silent size delta (either direction)
    is a campaign-tracker bug.

    The 7-card admit set tracks the design doc §10.3 acceptance
    item 7 ("the 26-card decline-set walk confirms exactly the
    7-card admit set"); this pin is the size-axis sibling."""
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity import trajectory as traj

    ps = OracleParserCardSource().get_printings()
    admit_count = sum(
        1 for p in ps.values()
        if traj._printing_is_bridge_simple_carrier_aa_any(p)
    )
    assert admit_count == 7, (
        f"Phase 3C close admit-set size invariant violated: expected "
        f"exactly 7 cards, got {admit_count}. The design doc §6.4 "
        f"#26 positive set is exhaustive over the live EoE pool at "
        f"Phase-3 close."
    )
