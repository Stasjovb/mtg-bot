"""Spacecraft Station substrate Phase 1 — Cycle 3 (FLIP) pins.

**Lane.** ``feature/spacecraft-phase-1-cycle-3-flip-p1`` (2026-05-25).

Cycle 3 of the Spacecraft Station substrate Phase 1 campaign per
``docs/SPACECRAFT_STATION_SUBSTRATE_PHASE_1_DESIGN.md`` §5 (Python
bridge round-trip + admit predicate + OR-chain registration + FLIP).
Builds atop Cycle 1's substrate Part A (commit ``ea9aa996``) +
Cycle 2's substrate Part B (commit ``62e10ff9``):

  * C1 — ``CardPrinting.station_threshold`` / ``stationed_keywords``
    Rust fields + parse arm + ``is_stationed_predicate`` helper.
  * C2 — ``Action::ActivateStation`` resolver + sorcery-speed legal-
    action emitter + ``is_creature_now`` extension +
    ``battlefield_has_keyword`` fold of ``stationed_keywords``.

C3 deliverables (this slice):

1. **Python bridge forward emit** —
   :func:`mtg_bot.parity.cross_engine._spec_card_to_printing_dict`
   conditional emits ``station_threshold`` + ``stationed_keywords``
   onto the Rust registry dict, mirroring the
   ``cost_reductions`` / ``warp_cost`` back-compat-omit-when-default
   precedent.
2. **Python bridge reverse arm** —
   :func:`mtg_bot.parity.cross_engine._card_def_to_python_printing`
   threads ``station_threshold`` + ``stationed_keywords`` onto the
   materialized Python ``CardPrinting``.
3. **New ``CardDef`` fields** — ``station_threshold: int | None`` +
   ``stationed_keywords: tuple[str, ...]`` on
   :class:`mtg_bot.parity.cross_engine.CardDef`.
4. **New admit predicate** —
   :func:`mtg_bot.parity.trajectory._printing_is_bridge_pure_station_
   spacecraft` (sibling of ``_printing_is_bridge_pure_cost_reduction_
   creature`` / ``_pure_warp_creature``).
5. **New CardDef builder** —
   :func:`mtg_bot.parity.trajectory._station_spacecraft_card_def`
   (sibling of ``_carrier_aa_land_card_def``).
6. **OR-chain registration** in
   :func:`mtg_bot.parity.trajectory._filter_deck_to_bridge_supported`
   (the FLIP).

**THE FLIP.** Cycle 3 inverts the C1 invariant pins #7 + #8 and the
C2 invariant pin #6 in-place — Galvanizing Sawship was DECLINED
post-C1+C2; post-C3 it is ADMITTED through the new dedicated
predicate (the live ``_printing_is_bridge_simple_creature`` STILL
declines it on the ``card_types==('Artifact',)`` + the load-bearing
``if printing.station_threshold: return False`` guards — only the
NEW disjunct lights it up). The C3 bench-aggregate check confirms
exactly ONE Spacecraft now admits (Sawship); the other 21 stay
declined under the strict no-abilities + ``station_threshold is not
None`` gate (verify-first walk against the live 22-Spacecraft set
in the EoE pool, 21 carry abilities + The Eternity Elevator has
``threshold=None``).

C4 (after this slice) ships the per-card real-EoE probe (Scenarios
A/B/C across the charge-counter axis: un-stationed / partial /
fully-stationed-and-attacking) per design doc §6.3.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Pin 1 — Bridge forward emit (CardDef -> registry dict)
# ---------------------------------------------------------------------------


def test_spec_card_to_printing_dict_emits_station_threshold_and_keywords():
    """Pin #1 — Bridge forward emit.

    A CardDef carrying ``station_threshold=3`` + ``stationed_keywords=
    ('flying', 'haste')`` (Galvanizing-Sawship-shape) emits a Rust
    registry dict with both keys present at the expected values.
    Mirrors the cost-reduction Phase 1 emit precedent — sorted lowercase
    string list for keywords, plain int for threshold.
    """
    from mtg_bot.parity.cross_engine import CardDef, _spec_card_to_printing_dict

    card = CardDef(
        name="Test Sawship Shape",
        card_type="Artifact",
        mana_cost_generic=5,
        mana_cost_colored=(("R", 1),),
        subtypes=("Spacecraft",),
        power=6,
        toughness=5,
        station_threshold=3,
        stationed_keywords=("flying", "haste"),
    )
    pd = _spec_card_to_printing_dict(card)
    assert pd["station_threshold"] == 3, (
        "C3 forward emit must thread station_threshold through to the "
        f"registry dict; got {pd.get('station_threshold')!r}"
    )
    assert pd["stationed_keywords"] == ["flying", "haste"], (
        "C3 forward emit must thread stationed_keywords as a sorted "
        f"list of lowercase strings; got {pd.get('stationed_keywords')!r}"
    )


def test_spec_card_to_printing_dict_omits_station_keys_for_default_carddef():
    """Pin #1b — Back-compat: a default CardDef (every pre-C3 fixture)
    omits both ``station_threshold`` and ``stationed_keywords`` keys
    from the emitted registry dict. The Rust parse arm maps the
    absent keys to ``Option::None`` / ``Vec::new()`` (see
    ``rust/src/cards.rs:15908,15944``), which is bit-identical to
    pre-C3 behavior for every non-Spacecraft printing."""
    from mtg_bot.parity.cross_engine import CardDef, _spec_card_to_printing_dict

    card = CardDef(
        name="Test Vanilla Creature",
        card_type="Creature",
        mana_cost_generic=1,
        mana_cost_colored=(("G", 1),),
        power=2,
        toughness=2,
    )
    pd = _spec_card_to_printing_dict(card)
    assert "station_threshold" not in pd, (
        "Pre-C3 back-compat — default CardDef must NOT emit "
        f"station_threshold; got {pd.get('station_threshold')!r}"
    )
    assert "stationed_keywords" not in pd, (
        "Pre-C3 back-compat — default CardDef must NOT emit "
        f"stationed_keywords; got {pd.get('stationed_keywords')!r}"
    )


# ---------------------------------------------------------------------------
# Pin 2 — Bridge reverse arm (CardDef -> Python CardPrinting)
# ---------------------------------------------------------------------------


def test_card_def_to_python_printing_threads_station_threshold():
    """Pin #2 — Bridge reverse arm.

    A CardDef carrying ``station_threshold=3`` +
    ``stationed_keywords=('flying', 'haste')`` materializes to a
    Python ``CardPrinting`` whose ``station_threshold == 3`` and
    ``stationed_keywords == frozenset({'flying', 'haste'})`` —
    mirroring the live parser's storage shape.
    """
    from mtg_bot.parity.cross_engine import CardDef, _card_def_to_python_printing

    card = CardDef(
        name="Test Sawship Shape",
        card_type="Artifact",
        mana_cost_generic=5,
        mana_cost_colored=(("R", 1),),
        subtypes=("Spacecraft",),
        power=6,
        toughness=5,
        station_threshold=3,
        stationed_keywords=("flying", "haste"),
    )
    py = _card_def_to_python_printing(card)
    assert py.station_threshold == 3
    assert py.stationed_keywords == frozenset({"flying", "haste"})


def test_card_def_to_python_printing_defaults_for_pre_c3_carddef():
    """Pin #2b — Back-compat: a default CardDef materializes to a
    Python ``CardPrinting`` with ``station_threshold=None`` +
    ``stationed_keywords=frozenset()`` — bit-identical to pre-C3
    for every non-Spacecraft fixture."""
    from mtg_bot.parity.cross_engine import CardDef, _card_def_to_python_printing

    card = CardDef(
        name="Test Vanilla Creature",
        card_type="Creature",
        mana_cost_generic=1,
        mana_cost_colored=(("G", 1),),
        power=2,
        toughness=2,
    )
    py = _card_def_to_python_printing(card)
    assert py.station_threshold is None
    assert py.stationed_keywords == frozenset()


# ---------------------------------------------------------------------------
# Pin 3 — Admit predicate positive (Galvanizing Sawship admits)
# ---------------------------------------------------------------------------


def test_printing_is_bridge_pure_station_spacecraft_admits_galvanizing_sawship():
    """Pin #3 — The new admit predicate admits the live Galvanizing
    Sawship printing (the SOLE Phase-1 admit, post-verify-first walk).

    Pre-C3: the predicate did not exist and Sawship was DECLINED at
    every disjunct of ``_filter_deck_to_bridge_supported``. Post-C3:
    the new predicate at
    :func:`mtg_bot.parity.trajectory._printing_is_bridge_pure_station_
    spacecraft` returns True on the live Sawship printing — the
    positive half of THE FLIP.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    src = get_active_source().get_printings()
    sawship = src.get("Galvanizing Sawship")
    if sawship is None:
        pytest.skip("Galvanizing Sawship absent from active CardSource")

    assert trajectory._printing_is_bridge_pure_station_spacecraft(sawship), (
        "Galvanizing Sawship must ADMIT through the new C3 dedicated "
        "Spacecraft admit predicate post-FLIP. If False, the predicate "
        "is over-narrow or the live Sawship shape regressed."
    )


# ---------------------------------------------------------------------------
# Pin 4 — Admit predicate REJECTS Eternity Elevator (Phase-4 honest-stop)
# ---------------------------------------------------------------------------


def test_printing_is_bridge_pure_station_spacecraft_declines_eternity_elevator():
    """Pin #4 — The Eternity Elevator (``station_threshold=None``,
    activated abilities for Phase 4) stays DECLINED at the new
    predicate — design doc §3 explicitly defers Phase-4
    non-animating Spacecraft.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    src = get_active_source().get_printings()
    elevator = src.get("The Eternity Elevator")
    if elevator is None:
        pytest.skip("The Eternity Elevator absent from active CardSource")

    assert not trajectory._printing_is_bridge_pure_station_spacecraft(
        elevator
    ), (
        "The Eternity Elevator must STAY DECLINED at the new C3 "
        "Spacecraft admit predicate — station_threshold is None, "
        "activated_abilities non-empty, Phase 4 only."
    )


# ---------------------------------------------------------------------------
# Pin 5 — No silent auto-grow on the 7 deferred Spacecraft + 14 other live ones
# ---------------------------------------------------------------------------


def test_no_silent_auto_grow_on_other_spacecraft_post_c3():
    """Pin #5 — No-silent-auto-grow walk: every live Spacecraft in
    the active CardSource OTHER than Galvanizing Sawship stays
    DECLINED at the new C3 predicate. This is the bench-aggregate
    cross-check: exactly ONE Spacecraft admits post-FLIP (Sawship);
    every other Spacecraft carries at least one static / triggered /
    activated ability that the Phase-1 ``§2`` teeth reject, or
    ``station_threshold is None`` (The Eternity Elevator).

    Verify-first walk against the live EoE 22-Spacecraft pool
    confirmed Galvanizing Sawship is the ONLY zero-ability
    single-gated Spacecraft (every other carrier has at least one
    co-gate that Phase 1 explicitly defers to Phase 2 / 3 / 4 per
    design doc §3).
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    src = get_active_source().get_printings()
    admitted = []
    for name, p in src.items():
        if "Spacecraft" not in p.subtypes:
            continue
        if trajectory._printing_is_bridge_pure_station_spacecraft(p):
            admitted.append(name)
    assert admitted == ["Galvanizing Sawship"], (
        "C3 invariant: exactly ONE Spacecraft printing must admit "
        "through _printing_is_bridge_pure_station_spacecraft post-"
        f"FLIP — Galvanizing Sawship. Got: {sorted(admitted)!r}. "
        "Any extra admit is a silent auto-grow honest-stop."
    )


# ---------------------------------------------------------------------------
# Pin 6 — Admit predicate decline-set against the deferred Spacecraft (per design doc §6.4)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "card_name,decline_reason",
    [
        ("Lumen-Class Frigate", "static_abilities"),
        ("Larval Scoutlander", "triggered_abilities"),
        ("Sledge-Class Seedship", "triggered_abilities"),
        ("Synthesizer Labship", "triggered_abilities"),
        ("Entropic Battlecruiser", "triggered_abilities"),
        ("Infinite Guideline Station", "triggered_abilities (Phase 3C C4)"),
        ("The Eternity Elevator", "activated_abilities + None threshold"),
    ],
)
def test_predicate_declines_each_deferred_spacecraft(card_name, decline_reason):
    """Pin #6 — Per design doc §6.4 decline-set walk. Each of the 7
    deferred Spacecraft carriers (the §3 design doc census) stays
    DECLINED at the C3 admit predicate.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    src = get_active_source().get_printings()
    p = src.get(card_name)
    if p is None:
        pytest.skip(f"{card_name} absent from active CardSource")
    assert not trajectory._printing_is_bridge_pure_station_spacecraft(p), (
        f"{card_name} must stay DECLINED at the C3 admit predicate "
        f"(decline reason: {decline_reason}). If True, a Phase-N "
        f"co-gate slipped through — silent auto-grow honest-stop."
    )


# ---------------------------------------------------------------------------
# Pin 7 — INVERTED C1 invariant pin #7 — Sawship now ADMITS at admit gate
# ---------------------------------------------------------------------------


def test_galvanizing_sawship_now_admits_at_admit_gate_post_cycle_3():
    """Pin #7 — **THE FLIP.** C1 invariant pin #7
    (``test_galvanizing_sawship_stays_declined_at_admit_gate_post_
    cycle_1`` at ``test_spacecraft_phase_1_substrate_cycle_1.py:400``)
    is INVERTED in-place here.

    Pre-C3: Sawship was DECLINED at the deck-level filter (every
    OR-disjunct rejected it — ``_printing_is_bridge_simple_creature``
    via the ``card_types==('Artifact',)`` gate AND the load-bearing
    ``if printing.station_threshold: return False`` guard at
    ``trajectory.py:4698``).

    Post-C3: the NEW dedicated disjunct
    :func:`_printing_is_bridge_pure_station_spacecraft` admits the
    Sawship. The simple-creature predicate STILL declines it (the
    guard at line 4698 stays load-bearing — Sawship's Artifact
    card-type also continues to disqualify it from the creature arm),
    but the deck-level filter routes through the new disjunct.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    src = get_active_source().get_printings()
    sawship = src.get("Galvanizing Sawship")
    if sawship is None:
        pytest.skip("Galvanizing Sawship absent from active CardSource")

    # The simple-creature predicate STILL rejects the Sawship
    # (load-bearing guard at trajectory.py:4698 unchanged this cycle).
    assert trajectory._printing_is_bridge_simple_creature(sawship) is False, (
        "Galvanizing Sawship must STILL be declined at the simple-"
        "creature admit gate post-C3 — the new disjunct does NOT "
        "drop the load-bearing station_threshold guard on the "
        "simple-creature predicate. Only the new dedicated disjunct "
        "is the routing site."
    )
    # The deck-level filter NOW admits the Sawship — through the new
    # dedicated disjunct.
    filtered_names, card_defs = trajectory._filter_deck_to_bridge_supported(
        ["Galvanizing Sawship"], src,
    )
    assert filtered_names == ["Galvanizing Sawship"], (
        "THE FLIP — Galvanizing Sawship must ADMIT at the deck-level "
        "filter post-C3. Got "
        f"filtered_names={filtered_names!r}."
    )
    assert len(card_defs) == 1
    cd = card_defs[0]
    assert cd.name == "Galvanizing Sawship"
    assert cd.card_type == "Artifact"
    assert "Spacecraft" in cd.subtypes
    assert cd.station_threshold == 3
    # stationed_keywords is sorted-canonical-tuple on the CardDef
    assert tuple(cd.stationed_keywords) == ("flying", "haste")
    assert cd.power == 6
    assert cd.toughness == 5
    assert cd.mana_cost_generic == 5
    assert cd.mana_cost_colored == (("R", 1),)


# ---------------------------------------------------------------------------
# Pin 8 — INVERTED C1 invariant pin #8 — admit-set bumps by 1 (count = 1)
# ---------------------------------------------------------------------------


def test_admit_set_size_bumps_post_cycle_3():
    """Pin #8 — **Admit-set count bump.** C1 invariant pin #8
    (``test_admit_set_size_unchanged_post_cycle_1`` at
    ``test_spacecraft_phase_1_substrate_cycle_1.py:463``) is
    INVERTED in-place here.

    Pre-C3: ZERO Spacecraft printings admitted through any disjunct
    of the deck-level filter. Post-C3: at least Galvanizing Sawship
    admits (Phase-1 sub-shape A — 5,938 17lands decks).

    **Phase 2 Cycle 2 update (2026-05-25).** Post-Phase-2-C2 the
    Phase-2 sibling disjunct
    :func:`_printing_is_bridge_phase_2_static_anthem_spacecraft`
    additionally admits Lumen-Class Frigate (1 card, ~37k 17lands
    decks). The cardinality this pin asserts is therefore EXACTLY
    {Sawship, Lumen-Class Frigate} post-Phase-2-C2; the post-Phase-
    1-C3 baseline set ({Sawship}) is still the load-bearing
    invariant being affirmed (Sawship still admits via the Phase-1
    path).

    **Phase 3A Cycle 2 update (2026-05-25).** Post-Phase-3A-C2 the
    Phase-3 sibling disjunct
    :func:`_printing_is_bridge_phase_3_trigger_spacecraft`
    additionally admits Larval Scoutlander (1 card, the sole
    single-trigger ETB+IsSelf+OptionalSacLandOrLanderForBasicLand
    Ramp Spacecraft per the strict Phase-3A 1-class / 1-shape
    allowlist). The cardinality this pin asserts is therefore
    EXACTLY {Sawship, Lumen-Class Frigate, Larval Scoutlander}
    post-Phase-3A-C2; Sawship still admits via the Phase-1 path
    (the load-bearing post-Phase-1-C3 invariant).

    Bench-aggregate cross-check: walks every printing in the active
    source, counts those that admit through the deck-level filter
    AND carry the Spacecraft subtype. Post-Phase-4-Cycle-2 the set is
    the FULL EoE Spacecraft EIGHT-card admit set -- the Phase 3
    seven-card baseline + The Eternity Elevator (the SOLE
    non-animating Spacecraft, admitted post-Phase-4-Cycle-2 via the
    new ``_printing_is_bridge_phase_4_spacecraft_eternity_elevator``
    OR-chain disjunct). Any OTHER Spacecraft admitting is a silent
    auto-grow honest-stop.

    **Phase 4 Cycle 2 update (2026-05-26).** Post-Phase-4-C2 the
    Phase-4 sibling disjunct
    :func:`_printing_is_bridge_phase_4_spacecraft_eternity_elevator`
    additionally admits The Eternity Elevator (1 card, the SOLE
    ``station_threshold=None`` non-animating multi-AA Spacecraft in
    the live 22-Spacecraft EoE set). **SPACECRAFT 8/8 admit-gate
    closed.** The C3 per-card real-EoE byte-equal probe
    ``test_the_eternity_elevator_parity.py`` lands the PROBED tier
    flip, completing SPACECRAFT CAMPAIGN FULL CLOSURE.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    src = get_active_source().get_printings()
    admitted_spacecraft = []
    for name, p in src.items():
        if "Spacecraft" not in p.subtypes:
            continue
        filtered, _ = trajectory._filter_deck_to_bridge_supported(
            [name], src,
        )
        if filtered:
            admitted_spacecraft.append(name)
    assert sorted(admitted_spacecraft) == [
        "Entropic Battlecruiser",
        "Galvanizing Sawship",
        "Infinite Guideline Station",
        "Larval Scoutlander",
        "Lumen-Class Frigate",
        "Sledge-Class Seedship",
        "Synthesizer Labship",
        "The Eternity Elevator",
    ], (
        "Admit-set count bump: exactly EIGHT Spacecraft must admit "
        "at the deck-level filter post-Phase-4-Cycle-2 (SPACECRAFT "
        "8/8 ADMIT-GATE CLOSED) -- Galvanizing Sawship (Phase-1 sub-"
        "shape A) + Lumen-Class Frigate (Phase-2 static-anthem) + "
        "Larval Scoutlander (Phase-3A trigger-bearing ETB) + Sledge-"
        "Class Seedship (Phase-3B trigger-bearing ATTACKS) + "
        "Synthesizer Labship (Phase-3C Cycle-2 BEGINNING_OF_COMBAT "
        "tier-gated) + Entropic Battlecruiser (Phase-3C Cycle-3 "
        "ATTACKS + DISCARDS_CARD tier-1 gate) + Infinite Guideline "
        "Station (Phase-3C Cycle-4 ETB CreateTokenPerMulticolored"
        "Permanent + ATTACKS DrawCardPerMulticoloredPermanent) + "
        "The Eternity Elevator (Phase-4 non-animating multi-AA with "
        "AddChargeCounterManaOfChosenColor + tier_threshold=20 "
        "AA[1]). Got: "
        f"{sorted(admitted_spacecraft)!r}."
    )


# ---------------------------------------------------------------------------
# Pin 9 — INVERTED C2 invariant pin #6 — Sawship admits at deck filter post-C2
# ---------------------------------------------------------------------------


def test_galvanizing_sawship_admits_at_deck_filter_post_cycle_3():
    """Pin #9 — **THE FLIP (mirror of C2 pin #6).** C2 invariant pin
    #6 (``test_galvanizing_sawship_stays_declined_at_admit_gate_post_
    cycle_2`` at ``test_spacecraft_phase_1_substrate_cycle_2.py:446``)
    is INVERTED in-place here. Cross-checks the deck-level filter +
    the bench-aggregate Spacecraft count in one pin to mirror C2's
    structure (which combined the per-card + bench-aggregate sibling
    in a single test).
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    src = get_active_source().get_printings()
    sawship = src.get("Galvanizing Sawship")
    if sawship is None:
        pytest.skip("Galvanizing Sawship absent from active CardSource")

    # Simple-creature predicate STILL declines.
    assert trajectory._printing_is_bridge_simple_creature(sawship) is False
    # Deck-level filter admits Sawship.
    filtered_names, card_defs = trajectory._filter_deck_to_bridge_supported(
        ["Galvanizing Sawship"], src,
    )
    assert filtered_names == ["Galvanizing Sawship"]
    assert len(card_defs) == 1
    assert card_defs[0].station_threshold == 3
    # Bench-aggregate sibling: exactly one Spacecraft admits.
    admitted_spacecraft = []
    for name, p in src.items():
        if "Spacecraft" not in p.subtypes:
            continue
        if trajectory._printing_is_bridge_pure_station_spacecraft(p):
            admitted_spacecraft.append(name)
    assert admitted_spacecraft == ["Galvanizing Sawship"]


# ---------------------------------------------------------------------------
# Pin 10 — Bridge round-trip via live Galvanizing Sawship
# ---------------------------------------------------------------------------


def test_galvanizing_sawship_round_trips_through_bridge():
    """Pin #10 — End-to-end bridge round-trip on the live Sawship
    printing: deck-filter materialization -> CardDef -> registry-dict
    -> Python CardPrinting all preserve the substrate payload.

    Drives the same path ``build_python_state`` uses to materialize
    Python printings during state construction: the C3 builder turns
    the printing into a CardDef, the C3 forward-emit turns the CardDef
    into a registry dict, and the C3 reverse-arm turns the CardDef
    back into a Python CardPrinting whose ``station_threshold`` /
    ``stationed_keywords`` match the source printing payload byte-
    for-byte (modulo the sorted-canonical keyword tuple ordering).
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import (
        _card_def_to_python_printing,
        _spec_card_to_printing_dict,
    )

    src = get_active_source().get_printings()
    sawship = src.get("Galvanizing Sawship")
    if sawship is None:
        pytest.skip("Galvanizing Sawship absent from active CardSource")

    # Step 1: deck-filter materialization.
    filtered_names, card_defs = trajectory._filter_deck_to_bridge_supported(
        ["Galvanizing Sawship"], src,
    )
    assert filtered_names == ["Galvanizing Sawship"]
    assert len(card_defs) == 1
    cd = card_defs[0]

    # Step 2: forward-emit (CardDef -> registry dict).
    pd = _spec_card_to_printing_dict(cd)
    assert pd["station_threshold"] == 3
    assert pd["stationed_keywords"] == ["flying", "haste"]
    assert pd["card_types"] == ["Artifact"]
    assert pd["subtypes"] == ["Spacecraft"]
    assert pd["power"] == 6
    assert pd["toughness"] == 5

    # Step 3: reverse-arm (CardDef -> Python CardPrinting). The
    # materialized printing must carry the SAME substrate payload as
    # the source printing.
    py = _card_def_to_python_printing(cd)
    assert py.station_threshold == sawship.station_threshold
    assert py.stationed_keywords == sawship.stationed_keywords
    assert py.power == sawship.power
    assert py.toughness == sawship.toughness
    assert "Spacecraft" in py.subtypes


# ---------------------------------------------------------------------------
# Pin 11 — Live Spacecraft pool walk vs admit predicate
# ---------------------------------------------------------------------------


def test_live_spacecraft_pool_admit_set_is_exactly_galvanizing_sawship():
    """Pin #11 — Walk every Spacecraft in the active CardSource;
    confirm exactly one (Galvanizing Sawship) admits at the C3
    predicate AND the others all decline.

    The bench-aggregate subsystem-attribution sibling of Pin #5 /
    Pin #8 — distinct from the parameterized §6.4 walk (Pin #6) in
    that this pin makes the cardinality assertion at the WHOLE-POOL
    scope (not just the §3 design doc census of 7 deferred carriers).
    The verify-first walk found 22 live Spacecraft printings; 21
    carry abilities (static / triggered / activated); The Eternity
    Elevator additionally carries ``station_threshold=None``. Only
    Galvanizing Sawship admits.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    src = get_active_source().get_printings()
    all_spacecraft = sorted(
        n for n, p in src.items() if "Spacecraft" in p.subtypes
    )
    assert "Galvanizing Sawship" in all_spacecraft, (
        "Verify-first invariant: Galvanizing Sawship must exist in "
        "the active CardSource — the C3 pilot."
    )
    admit_set = sorted(
        n for n in all_spacecraft
        if trajectory._printing_is_bridge_pure_station_spacecraft(src[n])
    )
    decline_set = sorted(
        n for n in all_spacecraft
        if not trajectory._printing_is_bridge_pure_station_spacecraft(src[n])
    )
    assert admit_set == ["Galvanizing Sawship"], (
        f"Whole-pool admit invariant: only Galvanizing Sawship admits. "
        f"Got admit_set={admit_set!r}; decline_set={decline_set!r}."
    )
    # Cross-check decline set partitions the whole pool exactly.
    assert sorted(admit_set + decline_set) == all_spacecraft
