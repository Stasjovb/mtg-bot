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
    """**Phase-4A no-silent-auto-grow pin -- live admit set unchanged.**

    The current 6-card Phase-1-3 Land admit set must remain the
    UNIQUE admit set post-Phase-4A on the Land sibling, and the
    Artifact sibling must admit ZERO live cards (the +0 admit-delta
    invariant per design doc §5.2 + §10.1).

    Sweeps the entire live EoE printing pool to ensure no card has
    silently flipped admit state under the widen.
    """
    land_admits = sorted(
        name for name, p in printings.items()
        if _printing_is_bridge_simple_carrier_aa_land(p)
    )
    artifact_admits = sorted(
        name for name, p in printings.items()
        if _printing_is_bridge_simple_carrier_aa_artifact(p)
    )
    assert set(land_admits) == set(PHASE_1_3_ADMITTED_LAND_CARRIERS), (
        f"Phase-4A admit set diverged from baseline; got {land_admits}, "
        f"expected {sorted(PHASE_1_3_ADMITTED_LAND_CARRIERS)}"
    )
    assert artifact_admits == [], (
        f"Phase-4A.2 Artifact sibling should admit ZERO live cards "
        f"(substrate-only — Phase 4C/4D/4E land the actual Artifact "
        f"admits); got {artifact_admits}"
    )


# ---------------------------------------------------------------------------
# Phase-4 carrier DECLINE pins -- 4 multi-AA carriers STAY DECLINED
# ---------------------------------------------------------------------------


PHASE_4_DECLINED_CARRIERS = (
    "Mirrorpool",            # 4B target (Land)
    "Ghost Vacuum",          # 4C target (Artifact)
    "Keys to the House",     # 4D target (Artifact)
    "All-Fates Scroll",      # 4E target (Artifact)
)


@pytest.mark.parametrize("name", PHASE_4_DECLINED_CARRIERS)
def test_phase_4_carrier_stays_declined_post_substrate(name, printings):
    """**Phase-4A substrate-only invariant -- 4 carriers STAY DECLINED.**

    Each Phase-4 carrier must decline through ALL three Carrier-AA
    admit entry points (Land predicate, Artifact predicate, dispatcher)
    post-Phase-4A-Cycle-1. The decline mechanism per card:

      * Mirrorpool: Land-typed; passes the multi-AA shape gate AND
        every printing-level rider check; declines at the per-AA
        Effect-class teeth (AA[0] ``CopyTargetInstantOrSorceryYouControl``
        + AA[1] ``CreateTokenCopyOfTargetCreatureYouControl`` are NOT
        in the Phase-3 Effect-class admit set). Phase 4B widens the
        Effect-class set and FLIPs Mirrorpool ADMITTED.
      * Ghost Vacuum: Artifact-typed; declines at the per-AA AA-rider
        teeth (AA[1] ``sorcery_speed=True`` rejected by
        :func:`_aa_is_phase1_sub_shape_a`) AND at the per-AA Effect-
        class teeth (both Effects not in admit set). Phase 4C widens
        ``sorcery_speed`` admit + adds the two Effect classes and
        FLIPs Ghost Vacuum ADMITTED.
      * Keys to the House: Artifact-typed; declines at the per-AA AA-
        rider teeth (AA[1] ``sorcery_speed=True``) AND Effect-class
        teeth. Phase 4D lands the FLIP.
      * All-Fates Scroll: Artifact-typed; declines at the per-AA AA-
        rider teeth (AA[0] ``is_mana_ability=True``) AND Effect-class
        teeth. Phase 4E lands the FLIP.
    """
    p = printings[name]
    assert not _printing_is_bridge_simple_carrier_aa_land(p), (
        f"{name} should STAY DECLINED on the Land predicate "
        f"post-Phase-4A-Cycle-1 (Phase 4B/C/D/E land the FLIP)"
    )
    assert not _printing_is_bridge_simple_carrier_aa_artifact(p), (
        f"{name} should STAY DECLINED on the Artifact predicate "
        f"post-Phase-4A-Cycle-1 (Phase 4B/C/D/E land the FLIP)"
    )
    assert not _printing_is_bridge_simple_carrier_aa_any(p), (
        f"{name} should STAY DECLINED on the dispatcher "
        f"post-Phase-4A-Cycle-1 (Phase 4B/C/D/E land the FLIP)"
    )


def test_phase_4_carrier_per_aa_walk_declines_at_effect_class(printings):
    """**Per-AA decline-axis pin -- the teeth catching each carrier.**

    Confirms the EXACT per-AA decline mechanism documented in the
    design doc §2.2 verify-first walk: every AA on every Phase-4
    carrier independently fails :func:`_aa_is_phase1_sub_shape_a`.
    The multi-AA all-or-nothing contract therefore declines the
    printing as a whole even if a sibling AA happened to pass.

    Co-asserts the printing-level rider gate passes for each
    carrier — i.e., the decline mechanism is per-AA, not printing-
    level (validates the §5.2 design claim that all 4 carriers
    decline at the Effect-class / AA-rider teeth, not the printing-
    level riders).
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
        # Per-AA walk: every AA fails sub-shape-A.
        aas = tuple(p.activated_abilities or ())
        assert len(aas) >= 2, (
            f"{name} expected to have >=2 AAs (multi-AA carrier)"
        )
        for idx, aa in enumerate(aas):
            assert not _aa_is_phase1_sub_shape_a(aa), (
                f"{name} AA[{idx}] unexpectedly passes the per-AA gate "
                f"(effect={type(aa.effect).__name__}, "
                f"is_mana={aa.is_mana_ability}, "
                f"sorcery_speed={aa.sorcery_speed})"
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
    (here, the failing AA carries ``sorcery_speed=True`` which is the
    AA-rider teeth) must DECLINE under the all-or-nothing contract,
    even though the sibling AA passes.

    This is the §5.2 critical-contract-preservation invariant: the
    widen is strictly additive on the ``len(aas)`` axis; every per-AA
    gate stays bit-identical. A printing with N>=2 AAs where AA[i]
    fails the per-AA predicate still declines.
    """
    import dataclasses
    base = printings["Petrified Field"]
    passing_aa = base.activated_abilities[0]
    # Build a "failing" AA: same shape but with sorcery_speed=True.
    # This is the AA-rider teeth path -- the per-AA gate rejects it.
    failing_aa = dataclasses.replace(passing_aa, sorcery_speed=True)
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
    """
    import dataclasses
    base = _synthetic_artifact_carrier_from_land(printings, n_aas=1)
    passing_aa = base.activated_abilities[0]
    failing_aa = dataclasses.replace(passing_aa, sorcery_speed=True)
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
    returns False for every Phase-4 carrier (Land sibling declines
    Mirrorpool on Effect-class teeth; Artifact sibling declines Ghost
    Vacuum / Keys / All-Fates on Effect-class + AA-rider teeth).
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
    """**Phase-4A no-regression pin -- single-AA Land builder unchanged.**

    Every Phase-1-3 single-AA Land admit still flattens to a CardDef
    with ``activated_abilities`` of length 1 (the multi-AA iteration
    widen is back-compat -- a 1-AA input yields a 1-element tuple).
    """
    for name in PHASE_1_3_ADMITTED_LAND_CARRIERS:
        p = printings[name]
        cd = _carrier_aa_land_card_def(p)
        assert cd is not None, f"{name} builder regressed to None"
        assert cd.card_type == "Land", f"{name} card_type drifted"
        assert len(cd.activated_abilities) == 1, (
            f"{name} should still flatten to 1 AA"
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
    # A Phase-4 Artifact carrier (Ghost Vacuum) declines at the
    # predicate, so the builder must return None.
    p = printings["Ghost Vacuum"]
    cd = _carrier_aa_artifact_card_def(p)
    assert cd is None


# ---------------------------------------------------------------------------
# Effect-class admit set UNCHANGED post-Cycle-1
# ---------------------------------------------------------------------------


def test_phase_1_effect_classes_unchanged_post_substrate_cycle_1():
    """**Phase-4A no-Effect-class-widen pin.** Cycle 1 does NOT widen
    the Effect-class allowlist -- that's Phase 4B/4C/4D/4E's
    deliverable. None of the Phase-4 Effect classes should be in the
    admit set post-Cycle-1.
    """
    from mtg_bot.parity.trajectory import _carrier_aa_phase_1_effect_classes

    classes = _carrier_aa_phase_1_effect_classes()

    # Confirm none of the Phase-4 Effect classes is in the admit set.
    from mtg_bot.effects.generic.stack_control import (
        CopyTargetInstantOrSorceryYouControl,
    )
    from mtg_bot.effects.generic.exile import (
        ExileTargetCardFromGraveyard,
    )

    assert CopyTargetInstantOrSorceryYouControl not in classes, (
        "CopyTargetInstantOrSorceryYouControl should NOT be in the "
        "admit set post-Phase-4A-Cycle-1 (Phase 4B ships the widen)"
    )
    assert ExileTargetCardFromGraveyard not in classes, (
        "ExileTargetCardFromGraveyard should NOT be in the admit set "
        "post-Phase-4A-Cycle-1 (Phase 4C ships the widen)"
    )
