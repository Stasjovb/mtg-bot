"""**Spacecraft Station substrate — Phase 3A Cycle 2 (Python admit
widen + Larval Scoutlander FLIP; 2026-05-25).**

Lane: ``feature/spacecraft-phase-3a-cycle-2-flip-p1``.

Cycle 2 of the Spacecraft Station substrate Phase 3A campaign per
``docs/SPACECRAFT_STATION_SUBSTRATE_PHASE_3_DESIGN.md`` (sub-phase
3A — Larval Scoutlander single-trigger zero-tier ETB carrier; 1
card, on top of the Phase-1 zero-ability + Phase-2 single-anthem
substrates that landed in commits ``e9a31c83`` (Phase 1 Cycle 3 flip)
and ``8675b274`` (Phase 2 Cycle 2 flip) and ``83d775cf`` (Phase 3A
Cycle 1 Rust substrate).

**Cycle 1 (Rust substrate landing, commit ``83d775cf``).**

  * New ``Effect::OptionalSacLandOrLanderForBasicLandRamp`` variant on
    ``rust/src/cards.rs::Effect`` + parse_effect + to_pydict + resolve
    arm.
  * Cross-engine bridge dict-to-Python arm
    ``cross_engine.py::_ta_dict_to_python_effect``.
  * Reverse-serializer leaf in
    ``trajectory.py::_python_ta_to_safe_dict`` (recognized; gated as
    dormant via the safe-kinds set).
  * Substrate-only invariant: Larval Scoutlander STAYED DECLINED at
    every admit predicate disjunct (the Python admit predicate didn't
    exist).

**Cycle 2 (this slice — Python admit + builder + FLIP).**

  * New helper :func:`_triggered_ability_is_phase_3_spacecraft_admitted`
    in ``src/mtg_bot/parity/trajectory.py`` — parametrized over the
    Phase-3A allowlists
    :data:`_PHASE_3A_SPACECRAFT_TRIGGER_EFFECT_CLASSES` (1 class) and
    :data:`_PHASE_3A_SPACECRAFT_TRIGGER_EVENT_SHAPES` (1 shape).
  * New admit predicate
    :func:`_printing_is_bridge_phase_3_trigger_spacecraft` (sibling
    of Phase-1's
    :func:`_printing_is_bridge_pure_station_spacecraft` and Phase-2's
    :func:`_printing_is_bridge_phase_2_static_anthem_spacecraft`).
  * New CardDef builder
    :func:`_phase_3_trigger_spacecraft_card_def`.
  * OR-chain disjunct registration in
    :func:`_filter_deck_to_bridge_supported` + builder routing in
    :func:`_printing_to_card_def`.
  * Larval Scoutlander admit-gate FLIP: DECLINED → ADMITTED.
  * C1 substrate-only invariant pin INVERTED in place (in
    ``tests/test_spacecraft_phase_3a_substrate_cycle_1.py``;
    renamed ``..._stays_declined_..._post_cycle_1`` →
    ``..._now_admits_..._post_cycle_2``).
  * Per-card real-EoE probe Scenarios A + B in
    ``tests/test_larval_scoutlander_parity.py`` (registered in
    ``scripts/measure_pool_parity.py::PROBE_MODULES``).
  * Decline-set bench check pins (the 4 remaining Phase-3 Spacecraft
    + The Eternity Elevator stay DECLINED).
  * Phase-1 + Phase-2 + MTL non-regression pins per design doc §6.7.

**Out of scope (Phase 3B / 3C).**

  * Sledge-Class Seedship FLIP (ATTACKS+IsSelf+OptionalPutCreatureFrom
    HandOntoBattlefield) — Phase 3B per design doc §7.2.
  * Synthesizer Labship + Entropic Battlecruiser + Infinite Guideline
    Station FLIPs — Phase 3C per design doc §7.3.
  * The Eternity Elevator — Phase 4 separately scoped.
"""

from __future__ import annotations

import importlib.util

import pytest


# Skip Rust-engine probes if the extension isn't built.
_rust_skip = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


# ---------------------------------------------------------------------------
# Pin 1 — Python admit predicate
# `_printing_is_bridge_phase_3_trigger_spacecraft` on live Larval
# Scoutlander (design doc §6.2 #8).
# ---------------------------------------------------------------------------


def test_phase_3a_admit_predicate_admits_larval_scoutlander():
    """Pin #1 — The new admit predicate
    :func:`_printing_is_bridge_phase_3_trigger_spacecraft` returns
    True for the live Larval Scoutlander CardPrinting.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    src = get_active_source().get_printings()
    larval = src.get("Larval Scoutlander")
    if larval is None:
        pytest.skip("Larval Scoutlander absent from active CardSource")
    assert trajectory._printing_is_bridge_phase_3_trigger_spacecraft(
        larval,
    ) is True


def test_phase_3a_trigger_helper_accepts_larval_scoutlander_etb_shape():
    """Pin #1b — The helper
    :func:`_triggered_ability_is_phase_3_spacecraft_admitted` returns
    True for the live ETB trigger on Larval Scoutlander.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    src = get_active_source().get_printings()
    larval = src.get("Larval Scoutlander")
    if larval is None:
        pytest.skip("Larval Scoutlander absent from active CardSource")
    assert len(larval.triggered_abilities) == 1
    (ta,) = larval.triggered_abilities
    assert trajectory._triggered_ability_is_phase_3_spacecraft_admitted(
        ta,
    ) is True


# ---------------------------------------------------------------------------
# Pin 2 — Loader end-to-end admit on the live Larval Scoutlander
# (design doc §6.2 + §5.5 FLIP marker).
# ---------------------------------------------------------------------------


def test_larval_scoutlander_admits_at_deck_filter_post_cycle_2():
    """Pin #2 — **THE FLIP (loader site).** The deck-level filter
    admits Larval Scoutlander AND emits a CardDef carrying the
    expected Phase-3A ``triggered_abilities`` shape.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    src = get_active_source().get_printings()
    if "Larval Scoutlander" not in src:
        pytest.skip("Larval Scoutlander absent from active CardSource")
    filtered_names, card_defs = trajectory._filter_deck_to_bridge_supported(
        ["Larval Scoutlander"], src,
    )
    assert filtered_names == ["Larval Scoutlander"], (
        "THE FLIP — Larval Scoutlander must ADMIT at the deck-level "
        f"filter post-Cycle-2. Got filtered_names={filtered_names!r}."
    )
    assert len(card_defs) == 1
    cd = card_defs[0]
    assert cd.name == "Larval Scoutlander"
    assert cd.card_type == "Artifact"
    assert "Spacecraft" in cd.subtypes
    assert cd.station_threshold == 7
    assert tuple(cd.stationed_keywords) == ("flying",)
    assert cd.power == 3
    assert cd.toughness == 3
    assert cd.mana_cost_generic == 2
    assert cd.mana_cost_colored == (("G", 1),)
    assert cd.triggered_abilities == (
        {
            "event": "enters",
            "predicate": {"kind": "source_is_self"},
            "effect": {
                "kind": "optional_sac_land_or_lander_for_basic_land_ramp",
                "land_count": 2,
            },
        },
    )


# ---------------------------------------------------------------------------
# Pin 3 — Bench-aggregate admit-set count bumps Spacecraft 2 → 3
# (design doc §6.4 + §6.6 #21).
# ---------------------------------------------------------------------------


def test_admit_set_size_bumps_to_3_spacecraft_post_cycle_2():
    """Pin #3 — **Admit-set count bump.** Pre-Phase-3C-C4 admitted
    Spacecraft were Galvanizing Sawship (Phase 1) + Lumen-Class Frigate
    (Phase 2) + Larval Scoutlander (Phase 3A) + Sledge-Class Seedship
    (Phase 3B) + Synthesizer Labship (Phase 3C C2) + Entropic
    Battlecruiser (Phase 3C C3). Post-Phase-3C-Cycle-4 (2026-05-26;
    this campaign slice; **PHASE 3 CLOSED**) exactly SEVEN Spacecraft
    admit at the deck-level filter: + Infinite Guideline Station
    (Phase 3C C4 — the FINAL Phase-3 trigger-leg flip via the new
    ``CreateTokenPerMulticoloredPermanent`` +
    ``DrawCardPerMulticoloredPermanent`` Effect classes). Bench-
    aggregate cross-check walks every printing in the active source.
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
    ], (
        "Admit-set count bump: exactly SEVEN Spacecraft must admit at "
        "the deck-level filter post-Phase-3C-Cycle-4 (PHASE 3 CLOSED) — "
        "Galvanizing Sawship (Phase-1) + Lumen-Class Frigate (Phase-2) "
        "+ Larval Scoutlander (Phase-3A ETB) + Sledge-Class Seedship "
        "(Phase-3B ATTACKS) + Synthesizer Labship (Phase-3C C2 "
        "BEGINNING_OF_COMBAT tier-gate) + Entropic Battlecruiser "
        "(Phase-3C C3 ATTACKS + DISCARDS_CARD tier-1 gate) + Infinite "
        "Guideline Station (Phase-3C C4 ETB CreateTokenPerMulticolored "
        "Permanent + ATTACKS DrawCardPerMulticoloredPermanent). Got: "
        f"{sorted(admitted_spacecraft)!r}."
    )


def test_phase_3a_admit_set_is_exactly_three_phase_3_carriers_post_cycle_2():
    """Pin #3b — Subsystem-attribution: exactly FIVE EoE printings
    pass :func:`_printing_is_bridge_phase_3_trigger_spacecraft`
    under the Phase-3C-Cycle-4 7-class / 4-shape allowlist (Larval
    Scoutlander + Sledge-Class Seedship + Synthesizer Labship +
    Entropic Battlecruiser + Infinite Guideline Station). The
    Phase-3C-Cycle-4 admit set is exhaustive AND positively
    exclusive of every other Spacecraft. **PHASE 3 CLOSED** — the
    only Phase-3-eligible Spacecraft (The Eternity Elevator) fails
    on ``activated_abilities`` (Phase 4 territory).
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    src = get_active_source().get_printings()
    phase_3_admit = sorted(
        name for name, p in src.items()
        if trajectory._printing_is_bridge_phase_3_trigger_spacecraft(p)
    )
    assert phase_3_admit == [
        "Entropic Battlecruiser",
        "Infinite Guideline Station",
        "Larval Scoutlander",
        "Sledge-Class Seedship",
        "Synthesizer Labship",
    ], (
        "Phase-3C-Cycle-4 admit set must be exactly Larval Scoutlander + "
        "Sledge-Class Seedship + Synthesizer Labship + Entropic "
        "Battlecruiser + Infinite Guideline Station (PHASE 3 CLOSED); got "
        f"{phase_3_admit!r}. Any other admit is a silent auto-grow "
        "honest-stop — verify the Phase-3C-Cycle-4 allowlist (7 Effect "
        "classes + 4 (event, predicate) shapes) hasn't been widened "
        "accidentally."
    )


# ---------------------------------------------------------------------------
# Pin 4 — Decline-set bench check against the 3 remaining Phase-3C
# Spacecraft + The Eternity Elevator (design doc §6.6 #19-20;
# Sledge-Class Seedship promoted out of this set post-Phase-3B-C2).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "card_name,decline_reason",
    [
        (
            "The Eternity Elevator",
            "activated_abilities + station_threshold=None (Phase 4)",
        ),
    ],
)
def test_phase_3a_predicate_declines_each_deferred_spacecraft(
    card_name, decline_reason,
):
    """Pin #4 — Per design doc §6.6 #19 decline-set walk. **PHASE 3
    CLOSED** — only The Eternity Elevator remains DECLINED at the
    Phase-3C-Cycle-4 admit predicate (Infinite Guideline Station is
    promoted out of this decline set post-Phase-3C-Cycle-4 —
    2026-05-26; see the INVERTED admit-side invariant pin
    ``test_synthesizer_labship_admits_at_phase_3_admit_gate_post_cycle_2``
    in test_spacecraft_phase_3c_substrate_cycle_1.py). The Eternity
    Elevator depends on the parallel Carrier-AA Phase 1+ campaign
    landing the non-token-AA bridge round-trip (Phase 4 territory).
    Silent auto-grow honest-stop.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    src = get_active_source().get_printings()
    p = src.get(card_name)
    if p is None:
        pytest.skip(f"{card_name} absent from active CardSource")
    assert not trajectory._printing_is_bridge_phase_3_trigger_spacecraft(p), (
        f"{card_name} must stay DECLINED at the Phase-3A admit predicate "
        f"(decline reason: {decline_reason}). If True, a Phase-N co-gate "
        "slipped through — silent auto-grow honest-stop."
    )


def test_phase_3a_predicate_declines_galvanizing_sawship():
    """Pin #4b — The Phase-1 sub-shape A pilot (Galvanizing Sawship,
    zero abilities) MUST be declined by the Phase-3A predicate.
    Sawship admits via the Phase-1 sibling disjunct, NOT the Phase-3
    one. Confirms the three disjuncts are positively-exclusive.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    src = get_active_source().get_printings()
    p = src.get("Galvanizing Sawship")
    if p is None:
        pytest.skip("Galvanizing Sawship absent from active CardSource")
    assert not trajectory._printing_is_bridge_phase_3_trigger_spacecraft(p), (
        "Galvanizing Sawship must STAY DECLINED at the Phase-3A admit "
        "predicate (it carries zero triggered_abilities; the Phase-3 "
        "predicate REQUIRES at least one). Sawship admits via the "
        "Phase-1 _printing_is_bridge_pure_station_spacecraft sibling."
    )


def test_phase_3a_predicate_declines_lumen_class_frigate():
    """Pin #4c — The Phase-2 pilot (Lumen-Class Frigate, single-static
    anthem) MUST be declined by the Phase-3A predicate. Lumen admits
    via the Phase-2 sibling disjunct, NOT the Phase-3 one. Confirms
    the disjuncts are positively-exclusive.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    src = get_active_source().get_printings()
    p = src.get("Lumen-Class Frigate")
    if p is None:
        pytest.skip("Lumen-Class Frigate absent from active CardSource")
    assert not trajectory._printing_is_bridge_phase_3_trigger_spacecraft(p), (
        "Lumen-Class Frigate must STAY DECLINED at the Phase-3A admit "
        "predicate (it carries a static_ability; the Phase-3 predicate "
        "REQUIRES empty static_abilities). Lumen admits via the Phase-2 "
        "_printing_is_bridge_phase_2_static_anthem_spacecraft sibling."
    )


# ---------------------------------------------------------------------------
# Pin 5 — Phase 1 + Phase 2 + MTL non-regression (design doc §6.7).
# ---------------------------------------------------------------------------


def test_phase_1_galvanizing_sawship_still_admits_post_cycle_2():
    """Pin #5 — **Phase 1 non-regression.** Galvanizing Sawship (the
    Phase-1 pilot zero-ability Spacecraft) STILL admits at the
    Phase-1 gate post-Cycle-2.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    src = get_active_source().get_printings()
    sawship = src.get("Galvanizing Sawship")
    if sawship is None:
        pytest.skip("Galvanizing Sawship absent from active CardSource")
    assert trajectory._printing_is_bridge_pure_station_spacecraft(
        sawship,
    ) is True, (
        "Galvanizing Sawship must STILL admit at the Phase-1 gate "
        "post-Cycle-2 (Phase 1 non-regression)."
    )


def test_phase_2_lumen_class_frigate_still_admits_post_cycle_2():
    """Pin #5b — **Phase 2 non-regression.** Lumen-Class Frigate (the
    Phase-2 pilot single-anthem Spacecraft) STILL admits at the
    Phase-2 gate post-Cycle-2.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    src = get_active_source().get_printings()
    lumen = src.get("Lumen-Class Frigate")
    if lumen is None:
        pytest.skip("Lumen-Class Frigate absent from active CardSource")
    assert trajectory._printing_is_bridge_phase_2_static_anthem_spacecraft(
        lumen,
    ) is True, (
        "Lumen-Class Frigate must STILL admit at the Phase-2 gate "
        "post-Cycle-2 (Phase 2 non-regression)."
    )


def test_phase_3a_predicate_declines_memorial_team_leader():
    """Pin #5c — **MTL non-regression.** The Phase-3A Spacecraft admit
    predicate must positively reject Memorial Team Leader — MTL has
    no ``Spacecraft`` subtype + no ``station_threshold`` + carries an
    anthem under ``DuringYourTurn`` (not a Phase-3 trigger). The
    ``"Spacecraft" not in subtypes`` short-circuit at the first clause
    closes the loop without inspecting the trigger's shape.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    src = get_active_source().get_printings()
    mtl = src.get("Memorial Team Leader")
    if mtl is None:
        pytest.skip("Memorial Team Leader absent from active CardSource")
    assert not trajectory._printing_is_bridge_phase_3_trigger_spacecraft(mtl), (
        "Memorial Team Leader must be REJECTED by the new Phase-3A "
        "Spacecraft admit predicate (not a Spacecraft; carries no "
        "Phase-3-allowlisted trigger)."
    )


def test_phase_4_warp_anthem_predicate_still_admits_memorial_team_leader():
    """Pin #5d — MTL still admits via the Phase-4 warp+anthem
    disjunct. The Phase-3A substrate landing must not regress MTL's
    existing admit-gate path.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    src = get_active_source().get_printings()
    mtl = src.get("Memorial Team Leader")
    if mtl is None:
        pytest.skip("Memorial Team Leader absent from active CardSource")
    assert trajectory._printing_is_bridge_static_anthem_pt_conditional_warp_creature(
        mtl,
    ) is True, (
        "MTL must STILL admit via the Phase-4 warp+anthem disjunct "
        "(unchanged post-Phase-3A substrate landing)."
    )


# ---------------------------------------------------------------------------
# Pin 6 — No-silent-auto-grow synthetic pins (design doc §6.6 #22-25).
# ---------------------------------------------------------------------------


def test_phase_3a_predicate_rejects_extra_effect_class_synthetic():
    """Pin #6 — No-silent-auto-grow (extra Effect class). A synthetic
    Spacecraft carrying an ETB+IsSelf trigger whose Effect class is
    NOT in :data:`_PHASE_3A_SPACECRAFT_TRIGGER_EFFECT_CLASSES` (e.g.,
    a raw ``DrawCards(count=3)``) is rejected by the predicate.
    """
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.generic.draw_mill import DrawCards
    from mtg_bot.effects.predicates import Event, IsSelf
    from mtg_bot.parity import trajectory

    p = CardPrinting(
        name="Synthetic Spacecraft (extra effect class)",
        mana_cost_str="{2}{G}",
        mana_cost=ManaCost(generic=2, colored=(("G", 1),)),
        type_line="Artifact — Spacecraft",
        supertypes=(),
        card_types=("Artifact",),
        subtypes=("Spacecraft",),
        power=3,
        toughness=3,
        produces=frozenset(),
        station_threshold=7,
        stationed_keywords=frozenset({"flying"}),
        triggered_abilities=(
            TriggeredAbility(
                event=Event.ENTERS,
                predicate=IsSelf(),
                effect=DrawCards(amount=3),
            ),
        ),
    )
    assert not trajectory._printing_is_bridge_phase_3_trigger_spacecraft(p), (
        "Synthetic Spacecraft with DrawCards(3) trigger must be "
        "REJECTED — DrawCards is NOT in the Phase-3B Effect-class "
        "allowlist {OptionalSacLandOrLanderForBasicLandRamp, "
        "OptionalPutCreatureFromHandOntoBattlefield}."
    )


def test_phase_3a_predicate_rejects_extra_trigger_count_synthetic():
    """Pin #6b — No-silent-auto-grow (extra trigger count). A
    synthetic Spacecraft carrying 3 triggers is rejected (the
    ``len > 2`` short-circuit; design doc §6.6 #24).
    """
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.combinators import (
        OptionalSacLandOrLanderForBasicLandRamp,
    )
    from mtg_bot.effects.predicates import Event, IsSelf
    from mtg_bot.parity import trajectory

    eff = OptionalSacLandOrLanderForBasicLandRamp(land_count=2)
    p = CardPrinting(
        name="Synthetic Spacecraft (3 triggers)",
        mana_cost_str="{2}{G}",
        mana_cost=ManaCost(generic=2, colored=(("G", 1),)),
        type_line="Artifact — Spacecraft",
        supertypes=(),
        card_types=("Artifact",),
        subtypes=("Spacecraft",),
        power=3,
        toughness=3,
        produces=frozenset(),
        station_threshold=7,
        stationed_keywords=frozenset({"flying"}),
        triggered_abilities=tuple(
            TriggeredAbility(
                event=Event.ENTERS, predicate=IsSelf(), effect=eff,
            )
            for _ in range(3)
        ),
    )
    assert not trajectory._printing_is_bridge_phase_3_trigger_spacecraft(p), (
        "Synthetic Spacecraft with 3 triggers must be REJECTED (the "
        "``len > 2`` no-silent-auto-grow gate; no EoE Spacecraft "
        "carries >2 triggers)."
    )


def test_phase_3a_predicate_rejects_tapestry_warden_flag_synthetic():
    """Pin #6c — No-silent-auto-grow (Tapestry Warden flag). A
    synthetic Spacecraft carrying a Phase-3 trigger AND
    ``grants_toughness_as_station_power_for_creatures_you_control=
    True`` is rejected (design doc §3.5 asymmetry; §6.6 #25).
    """
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.combinators import (
        OptionalSacLandOrLanderForBasicLandRamp,
    )
    from mtg_bot.effects.predicates import Event, IsSelf
    from mtg_bot.parity import trajectory

    eff = OptionalSacLandOrLanderForBasicLandRamp(land_count=2)
    p = CardPrinting(
        name="Synthetic Tapestry-Warden Spacecraft",
        mana_cost_str="{2}{G}",
        mana_cost=ManaCost(generic=2, colored=(("G", 1),)),
        type_line="Artifact — Spacecraft",
        supertypes=(),
        card_types=("Artifact",),
        subtypes=("Spacecraft",),
        power=3,
        toughness=3,
        produces=frozenset(),
        station_threshold=7,
        stationed_keywords=frozenset({"flying"}),
        triggered_abilities=(
            TriggeredAbility(
                event=Event.ENTERS, predicate=IsSelf(), effect=eff,
            ),
        ),
        grants_toughness_as_station_power_for_creatures_you_control=True,
    )
    assert not trajectory._printing_is_bridge_phase_3_trigger_spacecraft(p), (
        "Synthetic Tapestry-Warden Spacecraft must be REJECTED (the "
        "Tapestry Warden flag positively rejects per design doc §3.5)."
    )


def test_phase_3a_predicate_rejects_composed_shape_synthetic():
    """Pin #6d — No-silent-auto-grow (composed shape — Phase-2 anthem
    AND Phase-3 trigger). A synthetic Spacecraft carrying BOTH a
    Phase-2 static-anthem AND a Phase-3 trigger is rejected (the
    ``if printing.static_abilities: return False`` clause; design
    doc §6.6 #22). Pins the predicate against accidental admission
    of any future composed-shape printing.
    """
    from mtg_bot.cards.base import CardPrinting, ManaCost, StaticScope
    from mtg_bot.effects.base import StaticAbility, TriggeredAbility
    from mtg_bot.effects.combinators import (
        OptionalSacLandOrLanderForBasicLandRamp,
    )
    from mtg_bot.effects.modifiers import (
        ContinuousModifier, PowerToughnessBonus,
    )
    from mtg_bot.effects.predicates import Event, IsSelf
    from mtg_bot.parity import trajectory

    eff = OptionalSacLandOrLanderForBasicLandRamp(land_count=2)
    anthem = StaticAbility(
        scope=StaticScope.OTHER_CREATURES_YOU_CONTROL,
        tier_threshold=2,
        condition=None,
        continuous_effect=ContinuousModifier(
            layer=7,
            payload=PowerToughnessBonus(power_bonus=1, toughness_bonus=1),
        ),
    )
    p = CardPrinting(
        name="Synthetic Composed-Shape Spacecraft",
        mana_cost_str="{2}{G}",
        mana_cost=ManaCost(generic=2, colored=(("G", 1),)),
        type_line="Artifact — Spacecraft",
        supertypes=(),
        card_types=("Artifact",),
        subtypes=("Spacecraft",),
        power=3,
        toughness=3,
        produces=frozenset(),
        station_threshold=7,
        stationed_keywords=frozenset({"flying"}),
        static_abilities=(anthem,),
        triggered_abilities=(
            TriggeredAbility(
                event=Event.ENTERS, predicate=IsSelf(), effect=eff,
            ),
        ),
    )
    assert not trajectory._printing_is_bridge_phase_3_trigger_spacecraft(p), (
        "Synthetic composed-shape (Phase-2 anthem + Phase-3 trigger) "
        "Spacecraft must be REJECTED (the static-abilities short-"
        "circuit at clause 4 — composed shapes are Phase-N widen)."
    )


def test_phase_3a_predicate_rejects_wrong_event_synthetic():
    """Pin #6e — No-silent-auto-grow (wrong event). A synthetic
    Spacecraft carrying a BEGINNING_OF_COMBAT+IsSelf+
    OptionalSacLandOrLanderForBasicLandRamp shape is rejected (the
    ``(BEGINNING_OF_COMBAT, IsSelf())`` event-shape tuple is NOT in
    the Phase-3B 2-shape allowlist — it would widen in Phase 3C with
    Synthesizer Labship's BEGINNING_OF_COMBAT trigger).

    NOTE (Phase 3B C2 update; this slice 2026-05-25): the pre-C2
    version of this pin used ATTACKS as the wrong-event test, but
    Phase 3B C2 admits ``(ATTACKS, IsSelf(subject=None))``, so this
    pin pivots to the next-still-rejecting event shape
    (BEGINNING_OF_COMBAT) per design doc §7.3 — the still-deferred
    Phase 3C event-shape.
    """
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.combinators import (
        OptionalSacLandOrLanderForBasicLandRamp,
    )
    from mtg_bot.effects.predicates import Event, IsSelf
    from mtg_bot.parity import trajectory

    eff = OptionalSacLandOrLanderForBasicLandRamp(land_count=2)
    p = CardPrinting(
        name="Synthetic BEGINNING_OF_COMBAT-trigger Spacecraft",
        mana_cost_str="{2}{G}",
        mana_cost=ManaCost(generic=2, colored=(("G", 1),)),
        type_line="Artifact — Spacecraft",
        supertypes=(),
        card_types=("Artifact",),
        subtypes=("Spacecraft",),
        power=3,
        toughness=3,
        produces=frozenset(),
        station_threshold=7,
        stationed_keywords=frozenset({"flying"}),
        triggered_abilities=(
            TriggeredAbility(
                event=Event.BEGINNING_OF_COMBAT,
                predicate=IsSelf(),
                effect=eff,
            ),
        ),
    )
    assert not trajectory._printing_is_bridge_phase_3_trigger_spacecraft(p), (
        "Synthetic BEGINNING_OF_COMBAT-trigger Spacecraft must be "
        "REJECTED ((BEGINNING_OF_COMBAT, IsSelf()) not in Phase-3B "
        "2-shape allowlist {(ENTERS, IsSelf()), (ATTACKS, "
        "IsSelf())}; Phase 3C widens the event-shapes table)."
    )
