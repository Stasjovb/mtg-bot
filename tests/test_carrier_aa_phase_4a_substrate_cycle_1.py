"""**Carrier-AA substrate Phase 4A Cycle 1 (2026-05-26).**

Tests for the Phase 4A Cycle 1 Python-only substrate landing per
``docs/CARRIER_AA_SUBSTRATE_PHASE_4_DESIGN.md`` §4A.1 + §5.2 + §5.3 +
§6.1 + §7.1 + §10.1.

Deliverables (Cycle 1 Python-only slice — keystone of the Phase 4
multi-AA wave):

  - Widen :func:`_printing_is_bridge_simple_carrier_aa_land` from
    STRICT single-AA (``len(aas) != 1: return False``) to multi-AA
    all-or-nothing per-AA walk (every AA must independently pass
    :func:`_aa_is_phase1_sub_shape_a`).
  - Add Artifact-typed sibling predicate
    :func:`_printing_is_bridge_simple_carrier_aa_artifact` — same per-
    AA + bridge-floor gates as the Land sibling, plus the multi-AA
    widen, plus an empty-``subtypes`` guard (no Equipment / Vehicle /
    Spacecraft / Food / Treasure overlap; those are Phase N).
  - Add :func:`_printing_is_bridge_simple_carrier_aa_any` top-level
    dispatcher; ``_filter_deck_to_bridge_supported`` OR-chain calls
    the dispatcher instead of the Land predicate directly.
  - Add :func:`_carrier_aa_artifact_card_def` builder sibling; the
    Land builder widens to iterate all AAs into the bridge dict
    tuple.

This is a **substrate-only landing** — ZERO admit-set delta:

  - All 6 Phase-1-3 Carrier-AA admits (Swarmyard / Deserted Temple /
    Petrified Field / Terrain Generator / Mystifying Maze / Scavenger
    Grounds) STILL ADMIT post-Cycle-1 (no regression — every one is
    single-AA and Land-typed, so the multi-AA widen leaves their
    admit decision bit-identical).
  - All 4 Phase-4 multi-AA carriers (Mirrorpool / Ghost Vacuum / Keys
    to the House / All-Fates Scroll) STAY DECLINED post-Cycle-1:
      * Mirrorpool: 2 AAs, both Effect classes
        (``CopyTargetInstantOrSorceryYouControl`` +
        ``CreateTokenCopyOfTargetCreatureYouControl``) not in the
        Phase-3 admit set; declines on per-AA Effect-class teeth.
        Phase 4B lands the FLIP.
      * Ghost Vacuum: 2 AAs; AA[1] carries ``sorcery_speed=True``
        (rider teeth); both Effect classes
        (``ExileTargetCardFromGraveyard`` +
        ``PutEachCreatureCardExiledWith...``) not in the admit set.
        Phase 4C lands the FLIP.
      * Keys to the House: 2 AAs; AA[1] carries
        ``sorcery_speed=True``; both Effect classes
        (``SearchLibraryForCard`` +
        ``LockOrUnlockDoorOfTargetRoomYouControl``) not in the admit
        set. Phase 4D lands the FLIP.
      * All-Fates Scroll: 2 AAs; AA[0] carries ``is_mana_ability=
        True`` (rider teeth); both Effect classes (``AddManaToPool``
        + ``DrawCardsByConditionMultiplier``) not in the admit set.
        Phase 4E lands the FLIP.

The substrate widen is admit-set-neutral by design — the per-AA
Effect-class teeth + AA-rider teeth still decline every Phase-4
carrier without the corresponding Phase-4B/C/D/E widen.

**Verify-first findings (live tree at session start):**

  - ``_aa_is_phase1_sub_shape_a`` lives at ``trajectory.py:9000`` —
    cost gate (Phase 3B widen — bare ``{T}`` / ``{N}, {T}`` /
    ``sacrifice_self`` / ``sacrifice_a_desert`` axes admit) + AA-
    level rider gate (Phase 1: no ``is_mana_ability``,
    ``sorcery_speed``, ``cost_reductions``, ``room_half``,
    ``tier_threshold``, ``activate_only_once``) + Effect-class gate
    (Phase 3 admit set: ``RegenerateTargetCreature``,
    ``UntapTargetLand``, ``ReturnTargetLandFromGraveyardToHand``,
    ``PutBasicLandFromHandOntoBattlefieldTapped``,
    ``ExileTargetAttackingCreatureUntilEndStep`` + delayed-trigger
    siblings, ``ExileAllGraveyards``).
  - ``_printing_is_bridge_simple_carrier_aa_land`` lived at
    ``trajectory.py:9171`` with ``len(aas) != 1: return False`` —
    Phase 4A widens this to multi-AA all-or-nothing.
  - The 4 Phase-4 carriers all carry ``n_aa=2`` per live verify-
    first walk; no riders at the printing level beyond the multi-AA
    shape (no keywords / triggers / statics / spell_effect / warp /
    kicker / impending / room_halves / loyalty / cost_reductions /
    station_threshold / dynamic_pt / ward / PT).
  - 3 of 4 Phase-4 carriers are Artifact, not Land — Phase 4A.2
    sibling Artifact predicate is required for their card-type
    admit.
"""

from __future__ import annotations

import pytest

from mtg_bot.cards.parser.source import OracleParserCardSource
from mtg_bot.parity.trajectory import (
    _aa_is_phase1_sub_shape_a,
    _carrier_aa_artifact_card_def,
    _carrier_aa_land_card_def,
    _printing_is_bridge_simple_carrier_aa_any,
    _printing_is_bridge_simple_carrier_aa_artifact,
    _printing_is_bridge_simple_carrier_aa_land,
)


# ---------------------------------------------------------------------------
# Live-EoE invariant pins -- Phase-1-3 carriers STILL ADMIT (no regression)
# ---------------------------------------------------------------------------


PHASE_1_3_ADMITTED_LAND_CARRIERS = (
    "Swarmyard",
    "Deserted Temple",
    "Petrified Field",
    "Terrain Generator",
    "Mystifying Maze",
    "Scavenger Grounds",
    # Phase 3C C3 (Worker A, 2026-05-26) adds Thespian's Stage via the
    # ``BecomesCopyOfTargetLand`` Effect-class admit widen (the Phase-3
    # frontier closes at 7 admits; Phase 4+ multi-AA carriers stay
    # declined per the per-AA gate teeth).
    "Thespian's Stage",
    # **Phase 4B C4 (2026-05-26).** Adds Mirrorpool via the full Option
    # A FLIP. C3 shipped the AA[0] Rust spell-copy substrate at
    # ``e5cd1c18``; C4 widens
    # ``_carrier_aa_phase_1_effect_classes`` with
    # ``CopyTargetInstantOrSorceryYouControl`` + lands the
    # ``_python_aa_to_safe_dict`` forward arm + reverse arm. Combined
    # with the C2 widen for AA[1] (``CreateTokenCopyOfTargetCreature
    # YouControl``), BOTH per-AA Effect classes admit, and Mirrorpool's
    # printing-level admit FLIPs DECLINED → ADMITTED at the multi-AA
    # all-or-nothing gate. First Phase-4 multi-AA carrier to FULLY
    # FLIP end-to-end.
    "Mirrorpool",
)

# Phase 4D C2 (2026-05-26) FLIPs Keys to the House DECLINED → ADMITTED
# via the combined Effect-class widen
# (``LockOrUnlockDoorOfTargetRoomYouControl`` + ``SearchLibraryForCard``)
# + the ``sorcery_speed`` AA-rider widen. Keys to the House is an
# Artifact-typed carrier, so it lands on the Artifact sibling, not the
# Land sibling. Tracked separately from the Land admit set; folded into
# the loader-side admit walk via the Artifact builder.
PHASE_1_3_ADMITTED_ARTIFACT_CARRIERS = (
    "Keys to the House",
)


@pytest.fixture(scope="module")
def printings():
    """Live-EoE printings dict (verify-first source of truth)."""
    return OracleParserCardSource().get_printings()


@pytest.mark.parametrize("name", PHASE_1_3_ADMITTED_LAND_CARRIERS)
def test_phase_1_3_land_carrier_still_admits_post_widen(name, printings):
    """**Phase-4A no-regression pin -- Phase-1-3 Land admits unchanged.**

    Every Phase-1-3 Carrier-AA Land admit (Swarmyard / Deserted Temple
    / Petrified Field / Terrain Generator / Mystifying Maze / Scavenger
    Grounds) is single-AA (n_aa=1) — the multi-AA widen from
    ``len(aas) != 1`` to ``len(aas) >= 1 AND all per-AA pass`` leaves
    their admit decision bit-identical because every one was already a
    single-AA all-pass case under the strict predicate.
    """
    p = printings[name]
    assert _printing_is_bridge_simple_carrier_aa_land(p), (
        f"{name} should STILL ADMIT post-Phase-4A widen (no regression)"
    )
    assert _printing_is_bridge_simple_carrier_aa_any(p), (
        f"{name} should ADMIT via the new dispatcher"
    )


def test_phase_1_3_admits_unchanged_full_walk(printings):
    """**Phase-4A no-silent-auto-grow pin -- live LOADER-SIDE admit
    set tracks each phase's widens.**

    The LOADER-SIDE admit gate is the cross-engine CardDef builder
    (:func:`_carrier_aa_land_card_def` /
    :func:`_carrier_aa_artifact_card_def`) — these return a non-None
    CardDef iff the printing both (a) passes the admit predicate AND
    (b) every AA round-trips through the bridge floor. The Phase-4E
    C2 partial-FLIP widens the predicate-level admit set (the per-AA
    Effect-class + ``is_mana_ability`` rider gates lift), but the
    bridge floor's new "any" color teeth in
    :func:`_python_aa_to_safe_dict`'s ``AddManaToPool`` forward arm
    keeps the LOADER-SIDE admit set unchanged at the 7-card Phase-1-3
    baseline (the loader-side admit gate is what
    ``_filter_deck_to_bridge_supported`` actually consults, NOT the
    predicate alone — see the predicate-vs-builder split contract in
    :func:`trajectory._carrier_aa_land_card_def`'s docstring).

    The PREDICATE-level admit set may silently auto-grow under the
    C2 widens because the new ``AddManaToPool`` Effect-class admit
    matches several live EoE mana-ability lands (Crystal Quarry +
    Eldrazi Temple + Gemstone Caverns + Sunken Citadel — none of
    which are Carrier-AA candidates the bridge can round-trip end-
    to-end). Each declines at the BUILDER gate (the bridge floor's
    "any" decline + ``spend_restriction`` decline + multi-pair
    decline) so the loader's admit-set stays at the 7-card baseline.

    Sweeps the entire live EoE printing pool checking BOTH the
    predicate-level admit (which can grow) AND the loader-side admit
    via the builder (which must stay at baseline).
    """
    from mtg_bot.parity.trajectory import (
        _carrier_aa_artifact_card_def,
        _carrier_aa_land_card_def,
    )

    # Loader-side admit gate (what the cross-engine bridge actually
    # consults via the OR-chain in _filter_deck_to_bridge_supported).
    loader_land_admits = sorted(
        name for name, p in printings.items()
        if _carrier_aa_land_card_def(p) is not None
    )
    loader_artifact_admits = sorted(
        name for name, p in printings.items()
        if _carrier_aa_artifact_card_def(p) is not None
    )
    # Phase 4E C2.5 (2026-05-26): The "any" coin substrate landed in
    # Rust ManaPool; Gemstone Caverns (the only EoE Land whose AA[0]
    # uses produces=(("any", 1),)) FLIPs at the cross-engine LAND
    # builder gate. The Land admit set grows from 7 → 8.
    # Subsequent single-card Land FLIPs (refreshed at the Grove closure,
    # 2026-05-31): Mirrorpool (Phase 4B C4), Meteor Crater + Reflecting
    # Pool + Ancient Tomb (each P4 C2), and Grove of the Burnwillows
    # (the Sequence-IN-AA admit). The loader-side Land admit set is now
    # the 7-card Phase-3 baseline + these 6 single-card FLIPs.
    expected_land_admits = sorted(
        set(PHASE_1_3_ADMITTED_LAND_CARRIERS)
        | {
            "Gemstone Caverns",
            "Mirrorpool",
            "Meteor Crater",
            "Reflecting Pool",
            "Ancient Tomb",
            "Grove of the Burnwillows",
        }
    )
    assert set(loader_land_admits) == set(expected_land_admits), (
        f"LOADER-SIDE Land admit set diverged from the post-Grove "
        f"baseline; got {loader_land_admits}, expected "
        f"{expected_land_admits} (Gemstone Caverns + Mirrorpool + "
        f"Meteor Crater + Reflecting Pool + Ancient Tomb + Grove FLIPs)"
    )
    # Phase 4E C2.5 FULL FLIP: All-Fates Scroll's AA[0] AddManaToPool
    # 'any' forward arm admits at C2.5; the cross-engine builder
    # ADMITS the printing end-to-end.
    #
    # Combined: loader-side Artifact admit set =
    #   {Ghost Vacuum, Keys to the House, All-Fates Scroll} post-C2.5.
    expected_artifact_admits = sorted(
        set(PHASE_1_3_ADMITTED_ARTIFACT_CARRIERS)
        | {"Ghost Vacuum", "All-Fates Scroll"}
    )
    assert set(loader_artifact_admits) == set(
        expected_artifact_admits
    ), (
        f"Phase-4E-C2.5 LOADER-SIDE Artifact admit set: expected "
        f"{expected_artifact_admits} (Ghost Vacuum + Keys to the House "
        f"+ All-Fates Scroll FLIPs); got {loader_artifact_admits}"
    )


# ---------------------------------------------------------------------------
# Phase-4 carrier DECLINE pins -- 4 multi-AA carriers STAY DECLINED
# ---------------------------------------------------------------------------


PHASE_4_DECLINED_CARRIERS: tuple[str, ...] = (
    # **Phase 4B C4 (2026-05-26).** Mirrorpool (was here pre-Phase-4B-C4
    # as the LAST remaining Phase-4 multi-AA decline) FLIPS DECLINED →
    # ADMITTED end-to-end at C4. C3 shipped the AA[0] Rust spell-copy
    # substrate at ``e5cd1c18``; C4 ships the Python admit widen for
    # ``CopyTargetInstantOrSorceryYouControl`` +
    # ``_python_aa_to_safe_dict`` forward arm + ``_ta_dict_to_python_
    # effect`` reverse arm. With the C2 widen for AA[1] already in
    # place, BOTH per-AA Effect classes are now in the admit set —
    # Mirrorpool's printing-level admit FLIPs under the multi-AA
    # all-or-nothing contract. Mirrorpool is now in
    # ``PHASE_1_3_ADMITTED_LAND_CARRIERS`` above.
    # Ghost Vacuum (4C target) was here pre-Phase-4C-C2; the Phase 4C
    # C2 combined widen (Effect-class adds ExileTargetCardFromGraveyard
    # + PutEachCreatureCardExiledWith...; AA-rider lifts sorcery_speed)
    # FLIPs the printing DECLINED → ADMITTED end-to-end.
    # Keys to the House (4D target) was here pre-Phase-4D-C2; the
    # Phase 4D Cycle 2 widen (Effect-class set adds
    # ``LockOrUnlockDoorOfTargetRoomYouControl`` + ``SearchLibraryFor
    # Card``, AA-rider gate lifts ``sorcery_speed=True``) FLIPs the
    # printing DECLINED → ADMITTED end-to-end. See
    # :data:`PHASE_1_3_ADMITTED_ARTIFACT_CARRIERS` for the new admit
    # set entry, and the C2 admit-pin walk at
    # :func:`test_keys_to_the_house_admits_at_artifact_admit_predicate_post_4d_c2`.
    # All-Fates Scroll (4E target) was here pre-C2; Phase 4E C2's
    # partial-FLIP widens the per-AA admit predicate (Effect-class +
    # is_mana_ability rider) so the predicate now PASSES. The card
    # still STAYS DECLINED at the cross-engine builder gate (the
    # "any" color teeth at the bridge floor; Phase 4E C2.5 follow-
    # up cycle closes the gap). See
    # :func:`test_all_fates_scroll_partial_flip_post_c2_widens` for
    # the inverted invariant.
    # Ghost Vacuum (4C target) was here pre-Phase-4C-C2; Phase 4C
    # C2 FLIPs it DECLINED -> ADMITTED at the production-deck admit
    # gate (the Effect-class admit set widens to include
    # ExileTargetCardFromGraveyard +
    # PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYourControl;
    # the sorcery_speed AA-rider gate at cross_engine.py:14798 is
    # lifted; the Rust ActivatedAbility struct gains a sorcery_speed
    # slot + parse arm). See
    # :func:`test_ghost_vacuum_admit_post_4c_c2_widens` for the
    # inverted invariant.
)


# **Phase 4E C2.5 (2026-05-26) — partial-FLIP closure.** The Rust
# ManaPool "any" coin substrate landed; All-Fates Scroll FLIPs
# DECLINED → ADMITTED at the cross-engine builder gate. The tuple is
# now empty (kept here for parametrize-walk continuity).
PHASE_4_BUILDER_GATE_DECLINED_CARRIERS: tuple[str, ...] = ()


if PHASE_4_DECLINED_CARRIERS:
    @pytest.mark.parametrize("name", PHASE_4_DECLINED_CARRIERS)
    def test_phase_4_carrier_stays_declined_post_substrate(name, printings):
        """**Phase-4A substrate-only invariant -- carriers in the
        decline-set must STAY DECLINED.**

        Each Phase-4 carrier in this set must decline through ALL three
        Carrier-AA admit entry points (Land predicate, Artifact predicate,
        dispatcher).

        Post-Phase-4B-C4: the decline set is empty (Mirrorpool FLIPPED
        ADMITTED — see the inverted invariant
        ``test_mirrorpool_flips_admitted_at_full_admit_gate_post_c4``
        in ``test_carrier_aa_phase_4b_substrate_cycle_4.py``). This
        parametrized test only runs when the decline set is non-empty;
        when empty, the standalone empty-set sentinel below replaces it.
        """
        p = printings[name]
        assert not _printing_is_bridge_simple_carrier_aa_land(p), (
            f"{name} should STAY DECLINED on the Land predicate"
        )
        assert not _printing_is_bridge_simple_carrier_aa_artifact(p), (
            f"{name} should STAY DECLINED on the Artifact predicate"
        )
        assert not _printing_is_bridge_simple_carrier_aa_any(p), (
            f"{name} should STAY DECLINED on the dispatcher"
        )


def test_phase_4_declined_carriers_set_is_empty_post_4b_c4():
    """**Phase 4B C4 (2026-05-26) sentinel — Mirrorpool was the LAST
    Phase-4 multi-AA carrier in :data:`PHASE_4_DECLINED_CARRIERS`.**

    Post-C4 all four Phase-4 multi-AA carriers have FLIPPED end-to-end:
      * Ghost Vacuum (4C) — Phase 4C C2 (2026-05-26)
      * Keys to the House (4D) — Phase 4D C2 (2026-05-26)
      * All-Fates Scroll (4E) — Phase 4E C2 partial-FLIP at the
        predicate gate (still declines at the builder gate via "any"
        teeth — see
        :data:`PHASE_4_BUILDER_GATE_DECLINED_CARRIERS`).
      * Mirrorpool (4B) — Phase 4B C4 (2026-05-26).

    Sentinel — flips loudly if a future widen accidentally restores
    a Phase-4 multi-AA carrier to the decline-set without an
    accompanying inversion of this assertion + the FLIP test in
    ``test_carrier_aa_phase_4b_substrate_cycle_4.py``.
    """
    assert PHASE_4_DECLINED_CARRIERS == (), (
        f"Phase 4B C4 sentinel: PHASE_4_DECLINED_CARRIERS must be "
        f"empty post-Phase-4B-C4 (Mirrorpool FLIPped); got "
        f"{PHASE_4_DECLINED_CARRIERS!r}"
    )


@pytest.mark.parametrize("name", PHASE_4_BUILDER_GATE_DECLINED_CARRIERS)
def test_phase_4_carrier_builder_gate_decline_post_c2(name, printings):
    """**Phase 4E C2 partial-FLIP invariant -- All-Fates Scroll
    admits at the per-AA admit predicate but STAYS DECLINED at the
    cross-engine builder gate.** The "any" color teeth in
    :func:`cross_engine._python_aa_to_safe_dict`'s ``AddManaToPool``
    forward arm honest-declines AA[0]; the builder
    :func:`_carrier_aa_artifact_card_def` returns None. The full FLIP
    defers to Phase 4E C2.5 (Rust ManaPool "any" coin substrate).
    """
    from mtg_bot.parity.trajectory import _carrier_aa_artifact_card_def

    p = printings[name]
    # Per-AA admit predicate: passes post-C2 widens.
    assert _printing_is_bridge_simple_carrier_aa_artifact(p), (
        f"{name} should PASS the Artifact-typed admit predicate "
        f"post-Phase-4E-C2 widens"
    )
    assert _printing_is_bridge_simple_carrier_aa_any(p), (
        f"{name} should PASS the admit dispatcher post-Phase-4E-C2 "
        f"widens"
    )
    # Cross-engine builder gate: STAYS DECLINED (the "any" teeth).
    assert _carrier_aa_artifact_card_def(p) is None, (
        f"{name} should STAY DECLINED at the cross-engine builder "
        f"gate via the 'any' color teeth in _python_aa_to_safe_dict "
        f"(Phase 4E C2.5 follow-up closes the Rust ManaPool 'any' "
        f"coin substrate gap)"
    )


def test_phase_4_carrier_per_aa_walk_declines_at_effect_class(printings):
    """**Per-AA decline-axis pin -- the teeth catching each carrier.**

    Confirms the EXACT per-AA decline mechanism documented in the
    design doc §2.2 verify-first walk: at least ONE AA on each Phase-4
    carrier independently fails :func:`_aa_is_phase1_sub_shape_a`.
    The multi-AA all-or-nothing contract therefore declines the
    printing as a whole — even if a sibling AA happens to pass post-
    partial widens.

    Co-asserts the printing-level rider gate passes for each
    carrier — i.e., the decline mechanism is per-AA, not printing-
    level (validates the §5.2 design claim that all 4 carriers
    decline at the Effect-class / AA-rider teeth, not the printing-
    level riders).

    Post-Phase-4E-C2 invariant: walks only :data:`PHASE_4_DECLINED_
    CARRIERS` (3 cards, All-Fates Scroll moved out post-C2 partial-
    FLIP). All-Fates Scroll's per-AA decline-axis pin lives at
    :func:`test_phase_4_carrier_builder_gate_decline_post_c2` instead.

    **Post-Phase-4B-C4 invariant — set is now empty.** Mirrorpool was
    the last Phase-4 multi-AA carrier in the decline set; the C4
    Python admit widen + bridge arms FLIP it ADMITTED end-to-end. The
    decline-set walk becomes a degenerate empty iteration; the
    standalone sentinel
    :func:`test_phase_4_declined_carriers_set_is_empty_post_4b_c4`
    asserts the emptiness invariant explicitly.
    """
    for name in PHASE_4_DECLINED_CARRIERS:
        p = printings[name]
        # Printing-level rider gate should pass for each (no
        # printing-level reason to decline -- the decline is purely
        # at the per-AA gate).
        assert not p.keywords, f"{name} has unexpected printing-level keywords"
        assert not p.triggered_abilities, (
            f"{name} has unexpected printing-level triggered abilities"
        )
        assert not p.static_abilities, (
            f"{name} has unexpected printing-level static abilities"
        )
        assert p.spell_effect is None, (
            f"{name} has unexpected printing-level spell_effect"
        )
        assert not p.cost_reductions, (
            f"{name} has unexpected printing-level cost_reductions"
        )
        # Per-AA walk: at least one AA fails sub-shape-A (multi-AA
        # all-or-nothing contract -- one decline declines the
        # printing). Pre-Phase-4B-C2 invariant was every-AA-declines;
        # post-C2's partial widen flips Mirrorpool AA[1] admit (AA[0]
        # keeps the printing declined).
        aas = tuple(p.activated_abilities or ())
        assert len(aas) >= 2, (
            f"{name} expected to have >=2 AAs (multi-AA carrier)"
        )
        per_aa_results = [
            (idx, _aa_is_phase1_sub_shape_a(aa)) for idx, aa in enumerate(aas)
        ]
        assert any(not passes for _, passes in per_aa_results), (
            f"{name} unexpectedly has every AA pass the per-AA gate "
            f"(per-AA results: {per_aa_results}) -- the multi-AA all-"
            f"or-nothing contract requires at least one AA to fail to "
            f"keep the printing declined"
        )


# ---------------------------------------------------------------------------
# Multi-AA admit-predicate substrate pins (synthetic)
# ---------------------------------------------------------------------------


def _synthetic_multi_aa_land_printing(printings, n_copies: int = 2):
    """Build a synthetic Land printing carrying ``n_copies`` copies of
    Petrified Field's single AA on it -- exercises the new multi-AA
    admit path with N>=2 AAs that each independently pass the per-AA
    gate.

    Returns a shallow-mutated copy of the live Petrified Field
    printing with ``activated_abilities`` replaced by an N-tuple of
    its first AA. All other fields (card_types, supertypes, no
    riders) stay byte-identical so the printing-level gate passes.
    """
    import dataclasses
    base = printings["Petrified Field"]
    aa = base.activated_abilities[0]
    return dataclasses.replace(
        base,
        activated_abilities=tuple(aa for _ in range(n_copies)),
    )


def test_synthetic_two_passing_aas_admits_at_multi_aa_widen(printings):
    """**Phase-4A multi-AA admit primitive lands.** A synthetic Land
    printing with TWO AAs that BOTH independently pass the per-AA
    sub-shape-A predicate admits at the new multi-AA admit gate.
    Under the pre-Phase-4A invariant (``len(aas) != 1``) this same
    printing DECLINED at the strict single-AA contract.
    """
    p = _synthetic_multi_aa_land_printing(printings, n_copies=2)
    assert len(p.activated_abilities) == 2
    assert all(_aa_is_phase1_sub_shape_a(aa) for aa in p.activated_abilities)
    assert _printing_is_bridge_simple_carrier_aa_land(p), (
        "synthetic 2-AA Land printing with both AAs passing sub-shape-A "
        "should ADMIT post-Phase-4A multi-AA widen"
    )


def test_synthetic_three_passing_aas_admits_at_multi_aa_widen(printings):
    """**Phase-4A multi-AA admit primitive scales to N=3.** The
    multi-AA contract is N>=1, not N==1 or N==2 — confirm the widen
    is unbounded on the ``len(aas)`` axis.
    """
    p = _synthetic_multi_aa_land_printing(printings, n_copies=3)
    assert len(p.activated_abilities) == 3
    assert _printing_is_bridge_simple_carrier_aa_land(p), (
        "synthetic 3-AA Land printing with all AAs passing sub-shape-A "
        "should ADMIT post-Phase-4A multi-AA widen"
    )


def test_synthetic_two_aas_one_failing_declines_at_per_aa_walk(printings):
    """**Phase-4A all-or-nothing contract -- decline regression.**

    A synthetic Land printing with one passing AA + one failing AA
    (here, the failing AA carries ``activate_only_once=True`` which is
    still in the AA-rider decline set post-Phase-4C-C2 -- the
    sorcery_speed axis used pre-C2 was lifted as the Ghost Vacuum
    admit teeth) must DECLINE under the all-or-nothing contract, even
    though the sibling AA passes.

    This is the §5.2 critical-contract-preservation invariant: the
    widen is strictly additive on the ``len(aas)`` axis; every per-AA
    gate stays bit-identical. A printing with N>=2 AAs where AA[i]
    fails the per-AA predicate still declines.
    """
    import dataclasses
    base = printings["Petrified Field"]
    passing_aa = base.activated_abilities[0]
    # Build a "failing" AA: same shape but with activate_only_once=True.
    # This is the AA-rider teeth path -- the per-AA gate rejects it.
    # **Phase 4C C2 + Phase 4D C2 (2026-05-26):** the prior failing
    # axis here was ``sorcery_speed=True``; the Phase-4C-C2 (Ghost
    # Vacuum) + Phase-4D-C2 (Keys to the House) widens lifted that
    # rider. The synthetic decline-rider axis swaps to
    # ``activate_only_once=True`` (Phase 5+ teeth — not lifted by any
    # current cycle).
    failing_aa = dataclasses.replace(passing_aa, activate_only_once=True)
    assert _aa_is_phase1_sub_shape_a(passing_aa)
    assert not _aa_is_phase1_sub_shape_a(failing_aa)
    p = dataclasses.replace(
        base,
        activated_abilities=(passing_aa, failing_aa),
    )
    assert not _printing_is_bridge_simple_carrier_aa_land(p), (
        "synthetic 2-AA Land printing with AA[1] failing the per-AA gate "
        "must DECLINE under the all-or-nothing contract"
    )


def test_zero_aa_printing_declines(printings):
    """**Phase-4A zero-AA edge case -- declines (not a carrier).**

    A printing with ``len(aas) == 0`` is not a Carrier-AA carrier and
    must decline regardless of any other gate. This guards the
    ``len(aas) == 0`` short-circuit at the top of the multi-AA walk.
    """
    import dataclasses
    base = printings["Petrified Field"]
    p = dataclasses.replace(base, activated_abilities=())
    assert not _printing_is_bridge_simple_carrier_aa_land(p), (
        "0-AA Land printing must decline (not a carrier)"
    )


# ---------------------------------------------------------------------------
# Artifact sibling predicate substrate pins (synthetic)
# ---------------------------------------------------------------------------


def _synthetic_artifact_carrier_from_land(printings, n_aas: int = 1):
    """Build a synthetic Artifact carrier from a passing Land AA.

    Returns a Petrified-Field-shaped printing with
    ``card_types=('Artifact',)`` instead of ``('Land',)`` and
    ``n_aas`` copies of the passing AA. Used to exercise the §5.3
    Artifact sibling predicate without depending on any live EoE
    Artifact carrier (the 3 Phase-4 Artifact candidates all decline
    on the per-AA Effect-class teeth at Phase 4A close).
    """
    import dataclasses
    base = printings["Petrified Field"]
    aa = base.activated_abilities[0]
    return dataclasses.replace(
        base,
        card_types=("Artifact",),
        activated_abilities=tuple(aa for _ in range(n_aas)),
    )


def test_artifact_sibling_admits_synthetic_single_aa_artifact(printings):
    """**Phase-4A.2 Artifact sibling -- happy path.** A synthetic
    Artifact printing with one sub-shape-A AA admits at the new
    Artifact sibling predicate; the Land sibling correctly rejects it
    (mutually exclusive on the ``card_types`` axis).
    """
    p = _synthetic_artifact_carrier_from_land(printings, n_aas=1)
    assert _printing_is_bridge_simple_carrier_aa_artifact(p)
    assert not _printing_is_bridge_simple_carrier_aa_land(p)
    assert _printing_is_bridge_simple_carrier_aa_any(p)


def test_artifact_sibling_admits_synthetic_multi_aa_artifact(printings):
    """**Phase-4A.2 Artifact sibling -- multi-AA happy path.** A
    synthetic Artifact printing with TWO sub-shape-A AAs admits at
    the Artifact sibling under the §5.2 + §5.3 multi-AA widen.
    """
    p = _synthetic_artifact_carrier_from_land(printings, n_aas=2)
    assert _printing_is_bridge_simple_carrier_aa_artifact(p)


def test_artifact_sibling_declines_when_subtypes_present(printings):
    """**Phase-4A.2 Artifact sibling -- subtype guard.** An Artifact
    printing with non-empty ``subtypes`` (e.g., Equipment / Vehicle /
    Spacecraft / Food / Treasure) must DECLINE. Phase 4 explicitly
    defers Equipment / Vehicle / Spacecraft / Food / Treasure rider
    clusters to Phase N per design doc §3.
    """
    import dataclasses
    p = _synthetic_artifact_carrier_from_land(printings, n_aas=1)
    p_with_subtype = dataclasses.replace(p, subtypes=("Equipment",))
    assert not _printing_is_bridge_simple_carrier_aa_artifact(p_with_subtype)


def test_artifact_sibling_declines_when_extra_card_type_present(printings):
    """**Phase-4A.2 Artifact sibling -- multi-card-type guard.** An
    Artifact-Creature overlap must DECLINE (Phase 4 doesn't admit
    multi-card-type carriers; the Artifact sibling is single-typed
    only -- mirrors the Land sibling's ``extra_card_types`` guard).
    """
    import dataclasses
    p = _synthetic_artifact_carrier_from_land(printings, n_aas=1)
    p_overlap = dataclasses.replace(p, card_types=("Artifact", "Creature"))
    assert not _printing_is_bridge_simple_carrier_aa_artifact(p_overlap)


def test_artifact_sibling_declines_when_non_artifact(printings):
    """**Phase-4A.2 Artifact sibling -- card-type guard.** A Land
    printing (no Artifact in card_types) must DECLINE the Artifact
    sibling — the predicates are mutually exclusive.
    """
    p = printings["Petrified Field"]
    assert "Artifact" not in p.card_types
    assert not _printing_is_bridge_simple_carrier_aa_artifact(p)


def test_artifact_sibling_declines_on_per_aa_walk_failure(printings):
    """**Phase-4A.2 Artifact sibling -- per-AA decline regression.** A
    synthetic Artifact carrier with one passing AA + one failing AA
    declines under the all-or-nothing contract; same shape as the
    Land sibling's decline regression.

    Post-Phase-4C-C2: the failing-AA axis switched from
    ``sorcery_speed=True`` (now admitted) to
    ``activate_only_once=True`` (still in the decline set).
    """
    import dataclasses
    base = _synthetic_artifact_carrier_from_land(printings, n_aas=1)
    passing_aa = base.activated_abilities[0]
    # **Phase 4C C2 + Phase 4D C2 (2026-05-26):** swap to
    # ``activate_only_once`` per the sibling Land-side rationale at
    # :func:`test_synthetic_two_aas_one_failing_declines_at_per_aa_walk`.
    failing_aa = dataclasses.replace(passing_aa, activate_only_once=True)
    p = dataclasses.replace(
        base,
        activated_abilities=(passing_aa, failing_aa),
    )
    assert not _printing_is_bridge_simple_carrier_aa_artifact(p)


# ---------------------------------------------------------------------------
# Dispatcher pins
# ---------------------------------------------------------------------------


def test_dispatcher_returns_true_for_land_admit(printings):
    """**Phase-4A.3 dispatcher -- Land admit path.** The dispatcher
    returns True for every Phase-1-3 Land admit (delegates to the
    Land sibling).
    """
    for name in PHASE_1_3_ADMITTED_LAND_CARRIERS:
        p = printings[name]
        assert _printing_is_bridge_simple_carrier_aa_any(p)


def test_dispatcher_returns_true_for_synthetic_artifact_admit(printings):
    """**Phase-4A.3 dispatcher -- Artifact admit path.** The dispatcher
    returns True for a synthetic Artifact carrier (delegates to the
    Artifact sibling).
    """
    p = _synthetic_artifact_carrier_from_land(printings, n_aas=1)
    assert _printing_is_bridge_simple_carrier_aa_any(p)


def test_dispatcher_returns_false_for_phase_4_decline(printings):
    """**Phase-4A.3 dispatcher -- decline path.** The dispatcher
    returns False for the 3 Phase-4 carriers in :data:`PHASE_4_
    DECLINED_CARRIERS` (Mirrorpool / Ghost Vacuum / Keys to the
    House). All-Fates Scroll moved to :data:`PHASE_4_BUILDER_GATE_
    DECLINED_CARRIERS` post-Phase 4E C2 partial-FLIP.
    """
    for name in PHASE_4_DECLINED_CARRIERS:
        p = printings[name]
        assert not _printing_is_bridge_simple_carrier_aa_any(p)


# ---------------------------------------------------------------------------
# Builder pins -- Land builder widens to iterate all AAs; Artifact builder lands
# ---------------------------------------------------------------------------


def test_land_builder_iterates_all_aas_on_synthetic_multi_aa(printings):
    """**Phase-4A Land builder -- multi-AA iteration.** The Land
    builder serializes EVERY AA into the bridge dict tuple (no longer
    indexes [0] only). A synthetic 2-AA passing printing yields a
    CardDef with ``activated_abilities`` of length 2.
    """
    p = _synthetic_multi_aa_land_printing(printings, n_copies=2)
    cd = _carrier_aa_land_card_def(p)
    assert cd is not None
    assert cd.card_type == "Land"
    assert len(cd.activated_abilities) == 2, (
        f"Land builder expected to iterate all 2 AAs into the bridge "
        f"dict tuple; got {len(cd.activated_abilities)}"
    )


def test_land_builder_unchanged_for_phase_1_3_admits(printings):
    """**Phase-4A no-regression pin -- Land builder flattens each admit.**

    Every Phase-1-3 / 4B C4 Land admit flattens to a CardDef with
    ``activated_abilities`` of length matching the printing's AA count
    (single-AA carriers yield 1; the C4 multi-AA carrier Mirrorpool
    yields 2 via the Phase-4A multi-AA iteration widen — back-compat).
    """
    for name in PHASE_1_3_ADMITTED_LAND_CARRIERS:
        p = printings[name]
        cd = _carrier_aa_land_card_def(p)
        assert cd is not None, f"{name} builder regressed to None"
        assert cd.card_type == "Land", f"{name} card_type drifted"
        expected_n_aas = len(p.activated_abilities)
        assert len(cd.activated_abilities) == expected_n_aas, (
            f"{name} should flatten to {expected_n_aas} AAs (matching "
            f"the live printing's AA count); got "
            f"{len(cd.activated_abilities)}"
        )


def test_artifact_builder_builds_synthetic_artifact_card_def(printings):
    """**Phase-4A.2 Artifact builder -- happy path.** A synthetic
    Artifact carrier (one sub-shape-A AA) flattens via the new
    Artifact builder to a CardDef with ``card_type="Artifact"`` and
    every AA in the bridge dict tuple.
    """
    p = _synthetic_artifact_carrier_from_land(printings, n_aas=1)
    cd = _carrier_aa_artifact_card_def(p)
    assert cd is not None
    assert cd.card_type == "Artifact"
    assert len(cd.activated_abilities) == 1


def test_artifact_builder_iterates_all_aas(printings):
    """**Phase-4A.2 Artifact builder -- multi-AA iteration.** Sibling
    of the Land builder's multi-AA iteration pin.
    """
    p = _synthetic_artifact_carrier_from_land(printings, n_aas=2)
    cd = _carrier_aa_artifact_card_def(p)
    assert cd is not None
    assert cd.card_type == "Artifact"
    assert len(cd.activated_abilities) == 2


def test_artifact_builder_returns_none_when_predicate_rejects(printings):
    """**Phase-4A.2 Artifact builder -- predicate-gated.** The Artifact
    builder honest-declines (returns None) when the predicate rejects
    the printing -- mirrors the Land builder's defense-in-depth.
    """
    # A Phase-4 Artifact carrier that still declines at the predicate
    # post-Phase-4C-C2 + Phase-4D-C2 is needed. (Ghost Vacuum FLIPped
    # ADMITTED at Phase 4C C2; Keys to the House FLIPped ADMITTED at
    # Phase 4D C2.) Haunted Screen is the remaining Phase-N Artifact
    # carrier that declines on n_aa=3 + activate_only_once teeth
    # (Phase 5+ deferral).
    p = printings["Haunted Screen"]
    cd = _carrier_aa_artifact_card_def(p)
    assert cd is None


# ---------------------------------------------------------------------------
# Effect-class admit set UNCHANGED post-Cycle-1
# ---------------------------------------------------------------------------


def test_phase_1_effect_classes_unchanged_post_substrate_cycle_1():
    """**Phase-4A no-Effect-class-widen pin — Phase 4B C4 inverts.**

    Pre-Phase-4B-C4 this asserted ``CopyTargetInstantOrSorceryYouControl``
    NOT in the admit set as the next-pending Phase-4B sentinel. Phase 4B
    C4 (2026-05-26) lands the widen — the assertion inverts to ``IN
    the admit set`` post-C4 to track the actual frontier. The next
    pending sub-phase widen target is the cross-engine ``"any"`` color
    coin substrate (Phase 4E C2.5) at the bridge floor, NOT a new
    Effect-class admit-set entry — so the next sentinel landing point
    is no longer this file.
    """
    from mtg_bot.parity.trajectory import _carrier_aa_phase_1_effect_classes

    classes = _carrier_aa_phase_1_effect_classes()

    from mtg_bot.effects.generic.stack_control import (
        CopyTargetInstantOrSorceryYouControl,
    )

    # **Phase 4B C4 inversion (2026-05-26).** Was NOT-IN pre-C4;
    # IS-IN post-C4.
    assert CopyTargetInstantOrSorceryYouControl in classes, (
        "Phase 4B C4 invariant: CopyTargetInstantOrSorceryYouControl "
        "must BE in the admit set post-Phase-4B-C4 (the widen lands "
        "as part of the Mirrorpool full FLIP)."
    )
