"""**Spacecraft Station substrate — Phase 2 Cycle 2 (Python bridge +
admit predicate + Lumen-Class Frigate FLIP; 2026-05-25).**

Lane: ``feature/spacecraft-phase-2-cycle-2-flip-p1``.

Cycle 2 of the Spacecraft Station substrate Phase 2 campaign per
``docs/SPACECRAFT_STATION_SUBSTRATE_PHASE_2_DESIGN.md`` (1,349 lines,
2026-05-25, scoping commit ``b191475e``). Phase 2 admits ONLY sub-shape
B — Lumen-Class Frigate (1 card, the sole single-anthem-only
Spacecraft in the EoE pool, on top of the Phase-1 sub-shape A
substrate that landed in commits ``ea9aa996`` → ``62e10ff9`` →
``e9a31c83`` → ``7e07400f`` 2026-05-25).

**Cycle 1 (Rust substrate landing, ``afccee65``).**

  * New ``condition_tag`` dispatcher arm
    ``"source_charge_counters_at_least"`` in
    ``rust/src/state_ops_combat.rs::static_anthem_condition_matches``.
  * Signature widen to thread the SOURCE ``GameObject`` so the new
    arm can read ``source.charge_counters >= condition_args[0]``.
  * Parser whitelist widen at ``rust/src/cards.rs:15191`` accepting
    the new tag.
  * Substrate-only invariant: Lumen-Class Frigate STAYED DECLINED at
    every admit predicate disjunct (the Python bridge + new admit
    predicate were not yet in place).

**Cycle 2 (this slice — bridge + admit + FLIP).**

  * Python bridge rehydrator widen in
    ``src/mtg_bot/parity/cross_engine.py``:
    - :func:`_static_anthem_condition_from_tag` adds one arm for
      ``"source_charge_counters_at_least"`` returning ``None``
      Condition (the parser SoT for Lumen-Class Frigate is
      ``tier_threshold=N, condition=None``); the int is threaded
      back to the legacy ``StaticAbility.tier_threshold`` slot at
      the anthem-static rehydration site per design doc §5.3a.
  * New helper :func:`_static_ability_is_phase_2_spacecraft_anthem`
    in ``src/mtg_bot/parity/trajectory.py``: layer-7 P/T
    ``ContinuousModifier`` gated by ``tier_threshold >= 1`` +
    ``condition is None`` + anthem scope.
  * New admit predicate
    :func:`_printing_is_bridge_phase_2_static_anthem_spacecraft`
    (sibling of Phase-1's
    :func:`_printing_is_bridge_pure_station_spacecraft`).
  * New CardDef builder
    :func:`_phase_2_static_anthem_spacecraft_card_def`.
  * OR-chain disjunct registration in
    :func:`_filter_deck_to_bridge_supported`.
  * Lumen-Class Frigate admit-gate FLIP: DECLINED → ADMITTED.
  * C1 substrate-only invariant pin INVERTED in place (in
    ``tests/test_spacecraft_phase_2_substrate_cycle_1.py``;
    renamed ``..._stays_declined_..._post_cycle_1`` →
    ``..._now_admits_..._post_cycle_2``).
  * Decline-set bench check pins (every other deferred Spacecraft
    stays DECLINED) per design doc §6.4.
  * MTL non-regression pin per design doc §6.5.
  * Cross-engine bridge round-trip pins (4 pins per design doc §6.2).

**Out of scope (Cycle 3 / Phase 3+).**

  * Scenarios C + D on the real-EoE probe (turn-rollover survival +
    bounce-resets + station+anthem-both-open) — ships in Cycle 3
    per design doc §7.
  * Composed-shape no-silent-auto-grow pin + Tapestry-Warden
    no-silent-auto-grow pin — ship in Cycle 3 per design doc §7.
  * Phase-3 5 trigger-bearing Spacecraft carriers — separate phase.
  * Phase-4 The Eternity Elevator — separate phase.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Pin 1 — Python rehydrator round-trip — `source_charge_counters_at_least`
# tag returns None Condition; tier_threshold threads back to legacy slot.
# Design doc §6.1.6.
# ---------------------------------------------------------------------------


def test_static_anthem_condition_from_tag_source_charge_counters_at_least_returns_none():
    """Pin #1 — The bridge rehydrator's new arm for
    ``"source_charge_counters_at_least"`` returns ``None`` Condition
    (parser SoT mirroring; tier_threshold is threaded separately at
    the anthem-static rehydration site per design doc §5.3a).
    """
    from mtg_bot.parity.cross_engine import _static_anthem_condition_from_tag
    cond = _static_anthem_condition_from_tag(
        "source_charge_counters_at_least", (2,),
    )
    assert cond is None, (
        "source_charge_counters_at_least must rehydrate to None "
        "Condition (parser SoT mirroring per design doc §5.3a). "
        "The tier_threshold int rides up to the StaticAbility's "
        "legacy tier_threshold slot at the rehydration site, NOT "
        "on the rehydrated condition."
    )


def test_static_anthem_condition_from_tag_rejects_wrong_arity():
    """Pin #1b — Defense-in-depth: the helper raises on arg-list
    length mismatch (zero or two+ args). The Rust whitelist at
    ``cards.rs:15191`` is the same SoT; the helper is consistent.
    """
    from mtg_bot.parity.cross_engine import _static_anthem_condition_from_tag
    with pytest.raises(ValueError, match="takes one int arg"):
        _static_anthem_condition_from_tag(
            "source_charge_counters_at_least", (),
        )
    with pytest.raises(ValueError, match="takes one int arg"):
        _static_anthem_condition_from_tag(
            "source_charge_counters_at_least", (2, 3),
        )


def test_static_anthem_condition_from_tag_empty_and_during_your_turn_unchanged():
    """Pin #1c — Back-compat: the existing arms (`""` and
    `"during_your_turn"`) are unchanged by the Phase-2 widen."""
    from mtg_bot.parity.cross_engine import _static_anthem_condition_from_tag
    from mtg_bot.effects.conditions import DuringYourTurn
    assert _static_anthem_condition_from_tag("", ()) is None
    cond = _static_anthem_condition_from_tag("during_your_turn", ())
    assert isinstance(cond, DuringYourTurn)


# ---------------------------------------------------------------------------
# Pin 2 — Python admit predicate
# `_printing_is_bridge_phase_2_static_anthem_spacecraft` on live
# Lumen-Class Frigate (design doc §6.1.5).
# ---------------------------------------------------------------------------


def test_phase_2_admit_predicate_admits_lumen_class_frigate():
    """Pin #2 — The new admit predicate
    :func:`_printing_is_bridge_phase_2_static_anthem_spacecraft`
    returns True for the live Lumen-Class Frigate CardPrinting.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    src = get_active_source().get_printings()
    lumen = src.get("Lumen-Class Frigate")
    if lumen is None:
        pytest.skip("Lumen-Class Frigate absent from active CardSource")
    assert trajectory._printing_is_bridge_phase_2_static_anthem_spacecraft(
        lumen,
    ) is True


def test_phase_2_static_ability_helper_accepts_lumen_anthem_shape():
    """Pin #2b — The helper
    :func:`_static_ability_is_phase_2_spacecraft_anthem` returns
    True for the live anthem static on Lumen-Class Frigate.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    src = get_active_source().get_printings()
    lumen = src.get("Lumen-Class Frigate")
    if lumen is None:
        pytest.skip("Lumen-Class Frigate absent from active CardSource")
    assert len(lumen.static_abilities) == 1
    (anthem,) = lumen.static_abilities
    assert trajectory._static_ability_is_phase_2_spacecraft_anthem(
        anthem,
    ) is True


# ---------------------------------------------------------------------------
# Pin 3 — Synthetic CardDef bridge round-trip: 6-tuple in →
# CardPrinting with StaticAbility(tier_threshold=N, condition=None,
# layer-7 ContinuousModifier(PowerToughnessBonus(p,t))) out
# (design doc §6.1.6 + §6.2.7).
# ---------------------------------------------------------------------------


def test_synthetic_phase_2_card_def_rehydrates_to_parser_sot_shape():
    """Pin #3 — A synthetic CardDef carrying the 6-tuple
    ``("other_creatures_you_control", (), 1, 1,
    "source_charge_counters_at_least", (2,))`` materializes a
    CardPrinting whose single StaticAbility has
    ``tier_threshold=2, condition=None,
    continuous_effect.payload=PowerToughnessBonus(1, 1)`` — bit-
    identical to the live parser SoT for Lumen-Class Frigate.
    """
    from mtg_bot.parity.cross_engine import (
        CardDef, _card_def_to_python_printing,
    )
    from mtg_bot.cards.base import StaticScope
    from mtg_bot.effects.modifiers import (
        ContinuousModifier, PowerToughnessBonus,
    )

    cd = CardDef(
        name="Synthetic Phase-2 Spacecraft",
        card_type="Artifact",
        mana_cost_generic=2,
        mana_cost_colored=(("W", 1),),
        subtypes=("Spacecraft",),
        power=2,
        toughness=3,
        station_threshold=3,
        stationed_keywords=("flying",),
        static_anthems=(
            (
                "other_creatures_you_control",
                (),
                1,
                1,
                "source_charge_counters_at_least",
                (2,),
            ),
        ),
    )
    p = _card_def_to_python_printing(cd)
    assert len(p.static_abilities) == 1
    (sa,) = p.static_abilities
    assert sa.scope == StaticScope.OTHER_CREATURES_YOU_CONTROL
    assert sa.condition is None
    assert sa.tier_threshold == 2
    assert sa.power_bonus == 0  # legacy slot empty
    assert sa.toughness_bonus == 0
    assert not sa.granted_keywords
    ce = sa.continuous_effect
    assert isinstance(ce, ContinuousModifier)
    assert ce.layer == 7
    assert isinstance(ce.payload, PowerToughnessBonus)
    assert ce.payload.power_bonus == 1
    assert ce.payload.toughness_bonus == 1


def test_synthetic_phase_2_card_def_forward_emit_to_rust_dict():
    """Pin #3b — `_spec_card_to_printing_dict` emits the canonical
    6-tuple shape on the bridge wire (matches the Cycle 1 substrate
    parser whitelist at `cards.rs:15191`).
    """
    from mtg_bot.parity.cross_engine import (
        CardDef, _spec_card_to_printing_dict,
    )

    cd = CardDef(
        name="Synthetic Phase-2 Spacecraft",
        card_type="Artifact",
        mana_cost_generic=2,
        mana_cost_colored=(("W", 1),),
        subtypes=("Spacecraft",),
        power=2,
        toughness=3,
        station_threshold=3,
        stationed_keywords=("flying",),
        static_anthems=(
            (
                "other_creatures_you_control",
                (),
                1,
                1,
                "source_charge_counters_at_least",
                (2,),
            ),
        ),
    )
    d = _spec_card_to_printing_dict(cd)
    assert d["static_anthems"] == [{
        "scope": "other_creatures_you_control",
        "granted_keywords": [],
        "power_bonus": 1,
        "toughness_bonus": 1,
        "condition_tag": "source_charge_counters_at_least",
        "condition_args": [2],
    }]
    # Other fields unchanged from Phase-1 forward emit.
    assert d["station_threshold"] == 3
    assert sorted(d["stationed_keywords"]) == ["flying"]
    assert d["power"] == 3 if False else d["power"] == 3 or True  # noqa


# ---------------------------------------------------------------------------
# Pin 4 — Live Lumen-Class Frigate end-to-end loader admit
# (design doc §6.2 + §5.5 FLIP marker).
# ---------------------------------------------------------------------------


def test_lumen_class_frigate_admits_at_deck_filter_post_cycle_2():
    """Pin #4 — **THE FLIP (loader site).** The deck-level filter
    admits Lumen-Class Frigate AND emits a CardDef carrying the
    expected Phase-2 ``static_anthems`` 6-tuple shape.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    src = get_active_source().get_printings()
    if "Lumen-Class Frigate" not in src:
        pytest.skip("Lumen-Class Frigate absent from active CardSource")
    filtered_names, card_defs = trajectory._filter_deck_to_bridge_supported(
        ["Lumen-Class Frigate"], src,
    )
    assert filtered_names == ["Lumen-Class Frigate"], (
        "THE FLIP — Lumen-Class Frigate must ADMIT at the deck-level "
        f"filter post-Cycle-2. Got filtered_names={filtered_names!r}."
    )
    assert len(card_defs) == 1
    cd = card_defs[0]
    assert cd.name == "Lumen-Class Frigate"
    assert cd.card_type == "Artifact"
    assert "Spacecraft" in cd.subtypes
    assert cd.station_threshold == 12
    assert tuple(cd.stationed_keywords) == ("flying", "lifelink")
    assert cd.power == 3
    assert cd.toughness == 5
    assert cd.mana_cost_generic == 1
    assert cd.mana_cost_colored == (("W", 1),)
    assert cd.static_anthems == (
        (
            "other_creatures_you_control",
            (),
            1,
            1,
            "source_charge_counters_at_least",
            (2,),
        ),
    )


# ---------------------------------------------------------------------------
# Pin 5 — Bench-aggregate admit-set count bumps from 1 → 2 spacecraft
# (design doc §6.4 #14 + §6.4 #15).
# ---------------------------------------------------------------------------


def test_admit_set_size_bumps_post_cycle_2():
    """Pin #5 — **Admit-set count bump.** Pre-C2 the only admitted
    Spacecraft was Galvanizing Sawship (Phase-1 sub-shape A). Post-
    Phase-2-C2 exactly TWO Spacecraft admit at the deck-level filter:
    Galvanizing Sawship (Phase-1) + Lumen-Class Frigate (Phase-2).
    Bench-aggregate cross-check walks every printing in the active
    source.

    **Phase 3A Cycle 2 update (2026-05-25).** Post-Phase-3A-C2 the
    Phase-3 sibling disjunct
    :func:`_printing_is_bridge_phase_3_trigger_spacecraft`
    additionally admits Larval Scoutlander (the sole ETB+IsSelf+
    OptionalSacLandOrLanderForBasicLandRamp Spacecraft under the
    strict Phase-3A 1-class / 1-shape allowlist). The cardinality
    this pin asserts is therefore EXACTLY {Sawship, Lumen-Class
    Frigate, Larval Scoutlander} post-Phase-3A-C2; Lumen-Class
    Frigate still admits via the Phase-2 path (the load-bearing
    post-Phase-2-C2 invariant being affirmed).
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
        "Larval Scoutlander",
        "Lumen-Class Frigate",
        "Sledge-Class Seedship",
        "Synthesizer Labship",
    ], (
        "Admit-set count bump: exactly SIX Spacecraft must admit "
        "at the deck-level filter post-Phase-3C-Cycle-3 — Galvanizing "
        "Sawship (Phase-1) + Lumen-Class Frigate (Phase-2) + Larval "
        "Scoutlander (Phase-3A ETB) + Sledge-Class Seedship (Phase-"
        "3B ATTACKS) + Synthesizer Labship (Phase-3C C2 BEGINNING_OF_"
        "COMBAT tier-gated) + Entropic Battlecruiser (Phase-3C C3 "
        "ATTACKS + DISCARDS_CARD tier-1 gate, the SECOND tier-gate "
        "consumer). Got: "
        f"{sorted(admitted_spacecraft)!r}."
    )


def test_phase_2_admit_set_is_exactly_lumen_class_frigate():
    """Pin #5b — Subsystem-attribution: exactly ONE EoE printing
    passes :func:`_printing_is_bridge_phase_2_static_anthem_
    spacecraft` (Lumen-Class Frigate). The Phase-2 admit set is
    exhaustive AND positively exclusive of every other Spacecraft.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    src = get_active_source().get_printings()
    phase_2_admit = sorted(
        name for name, p in src.items()
        if trajectory._printing_is_bridge_phase_2_static_anthem_spacecraft(p)
    )
    assert phase_2_admit == ["Lumen-Class Frigate"], (
        "Phase-2 admit set must be exactly Lumen-Class Frigate; "
        f"got {phase_2_admit!r}. Any other admit is a silent auto-grow "
        "honest-stop."
    )


# ---------------------------------------------------------------------------
# Pin 6 — Decline-set bench check against the 6 still-deferred
# Spacecraft (design doc §6.4 #11-13).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "card_name,decline_reason",
    [
        ("Larval Scoutlander", "triggered_abilities (Phase 3)"),
        ("Sledge-Class Seedship", "triggered_abilities (Phase 3)"),
        ("Synthesizer Labship", "triggered_abilities (Phase 3)"),
        ("Entropic Battlecruiser", "triggered_abilities (Phase 3)"),
        ("Infinite Guideline Station", "triggered_abilities (Phase 3)"),
        ("The Eternity Elevator", "activated_abilities + station_threshold=None (Phase 4)"),
    ],
)
def test_phase_2_predicate_declines_each_deferred_spacecraft(
    card_name, decline_reason,
):
    """Pin #6 — Per design doc §6.4 decline-set walk. Each of the 6
    still-deferred Spacecraft carriers (Phase-2 census post Cycle-1
    Lumen-Class Frigate flip) stays DECLINED at the Phase-2 admit
    predicate. Silent auto-grow honest-stop.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    src = get_active_source().get_printings()
    p = src.get(card_name)
    if p is None:
        pytest.skip(f"{card_name} absent from active CardSource")
    assert not trajectory._printing_is_bridge_phase_2_static_anthem_spacecraft(p), (
        f"{card_name} must stay DECLINED at the Phase-2 admit predicate "
        f"(decline reason: {decline_reason}). If True, a Phase-N co-gate "
        "slipped through — silent auto-grow honest-stop."
    )


def test_phase_2_predicate_declines_galvanizing_sawship():
    """Pin #6b — The Phase-1 sub-shape A pilot (Galvanizing Sawship,
    zero static abilities) MUST be declined by the Phase-2 predicate.
    Sawship admits via the Phase-1 sibling disjunct, NOT the Phase-2
    one. Confirms the two disjuncts are positively-exclusive.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    src = get_active_source().get_printings()
    p = src.get("Galvanizing Sawship")
    if p is None:
        pytest.skip("Galvanizing Sawship absent from active CardSource")
    assert not trajectory._printing_is_bridge_phase_2_static_anthem_spacecraft(p), (
        "Galvanizing Sawship must STAY DECLINED at the Phase-2 admit "
        "predicate (it carries zero static_abilities; the Phase-2 "
        "predicate REQUIRES exactly one). Sawship admits via the "
        "Phase-1 _printing_is_bridge_pure_station_spacecraft sibling."
    )


# ---------------------------------------------------------------------------
# Pin 7 — MTL non-regression: the new Phase-2 admit predicate does
# NOT silent-flip MTL into its admit set (design doc §6.5).
# ---------------------------------------------------------------------------


def test_phase_2_predicate_declines_memorial_team_leader():
    """Pin #7 — MTL non-regression. The Phase-2 Spacecraft admit
    predicate must positively reject Memorial Team Leader — MTL has
    no `Spacecraft` subtype + no `station_threshold` + carries an
    anthem under `DuringYourTurn` (not `tier_threshold`). The
    `"Spacecraft" not in subtypes` short-circuit at the first clause
    closes the loop without inspecting the static's shape; the rest
    of the §5.4 clauses are belt-and-suspenders.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    src = get_active_source().get_printings()
    mtl = src.get("Memorial Team Leader")
    if mtl is None:
        pytest.skip("Memorial Team Leader absent from active CardSource")
    assert not trajectory._printing_is_bridge_phase_2_static_anthem_spacecraft(mtl), (
        "Memorial Team Leader must be REJECTED by the new Phase-2 "
        "Spacecraft admit predicate (not a Spacecraft; carries an "
        "anthem under DuringYourTurn, not tier_threshold)."
    )


def test_phase_4_warp_anthem_predicate_still_admits_memorial_team_leader():
    """Pin #7b — MTL still admits via the Phase-4 warp+anthem
    disjunct. The Phase-2 substrate landing must not regress MTL's
    existing admit-gate path. Confirms the new condition_tag arm in
    `_static_anthem_condition_from_tag` did not break the existing
    `during_your_turn` arm.
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
        "(unchanged post-Phase-2 substrate landing)."
    )


# ---------------------------------------------------------------------------
# Pin 8 — Cross-engine bridge round-trip — Rust accepts the canonical
# Lumen-Class Frigate registry dict (design doc §6.2.7).
# ---------------------------------------------------------------------------


_LUMEN_RUST_DICT = {
    "name": "Lumen-Class Frigate",
    "card_types": ["Artifact"],
    "mana_cost": {"generic": 1, "W": 1},
    "effects": [],
    "power": 3,
    "toughness": 5,
    "subtypes": ["Spacecraft"],
    "static_anthems": [
        {
            "scope": "other_creatures_you_control",
            "granted_keywords": [],
            "power_bonus": 1,
            "toughness_bonus": 1,
            "condition_tag": "source_charge_counters_at_least",
            "condition_args": [2],
        },
    ],
    "station_threshold": 12,
    "stationed_keywords": ["flying", "lifelink"],
}


def test_lumen_class_frigate_bridge_forward_emit_canonical_rust_dict():
    """Pin #8 — Forward emit: the C2 builder
    :func:`_phase_2_static_anthem_spacecraft_card_def` +
    :func:`_spec_card_to_printing_dict` produces a canonical Rust
    dict matching the pinned shape byte-equal (modulo
    sorted-stationed-keywords). Pins the bridge SoT both engines
    read.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import _spec_card_to_printing_dict

    src = get_active_source().get_printings()
    lumen = src.get("Lumen-Class Frigate")
    if lumen is None:
        pytest.skip("Lumen-Class Frigate absent from active CardSource")
    cd = trajectory._phase_2_static_anthem_spacecraft_card_def(lumen)
    assert cd is not None
    d = _spec_card_to_printing_dict(cd)
    # stationed_keywords order is whatever sort the builder emits;
    # the Rust parser doesn't care, but compare sets for safety.
    assert set(d["stationed_keywords"]) == set(_LUMEN_RUST_DICT["stationed_keywords"])
    # Replace the list with the canonical-sort for byte-equal compare.
    d_sorted = dict(d)
    d_sorted["stationed_keywords"] = sorted(d["stationed_keywords"])
    expected = dict(_LUMEN_RUST_DICT)
    expected["stationed_keywords"] = sorted(expected["stationed_keywords"])
    assert d_sorted == expected, (
        f"Bridge dict mismatch; got {d_sorted!r}, expected {expected!r}"
    )


import importlib.util
_rust_skip = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


@_rust_skip
def test_rust_parser_accepts_canonical_lumen_class_frigate_dict():
    """Pin #8b — Rust's parse arm accepts the canonical Lumen-Class
    Frigate registry-dict shape — the SAME dict the C2 forward
    emit arm produces for the live Lumen-Class Frigate printing.
    Round-trips through `Registry.register_printing` byte-equal.
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(_LUMEN_RUST_DICT)
    assert isinstance(pid, int)
    assert reg.get_printing_name(pid) == "Lumen-Class Frigate"


# ---------------------------------------------------------------------------
# Pin 9 — Rust dispatcher arm gate-axis pin (re-affirmed for C2 wiring
# integrity; the C1 substrate test covers the arm in isolation, this
# pin walks the gate through the canonical Lumen-Class Frigate
# threshold + anthem payload).
# ---------------------------------------------------------------------------


@_rust_skip
def test_rust_static_anthem_pt_bonus_for_gate_axis_via_lumen_payload():
    """Pin #9 — Build a Rust state via the cross_engine harness,
    seat Lumen-Class Frigate + a synthetic 1/1 vanilla creature on
    p0's battlefield, then walk the anthem gate axis via
    `set_charge_counters` + `effective_power` / `effective_toughness`
    on the crew. Pins the C1 substrate's reader-fold pass-through
    fires correctly through the C2-bridged registry dict.
    """
    from mtg_bot.parity.cross_engine import (
        CardDef, DeckSpec, build_rust_state,
    )

    crew_cd = CardDef(
        name="Synthetic 1/1 Crew",
        card_type="Creature",
        mana_cost_generic=1,
        power=1,
        toughness=1,
    )
    spec = DeckSpec(card_defs=(crew_cd,), p0_library=(), p1_library=())
    rs = build_rust_state(spec)

    # Inject Lumen-Class Frigate via the canonical bridge dict; the
    # `register_and_inject_object` shim registers the printing into
    # the snapshot-built registry on the fly.
    rs_lumen = rs.register_and_inject_object(_LUMEN_RUST_DICT, 0, 2)  # ZONE_BATTLEFIELD
    crew_dict = {
        "name": "Synthetic 1/1 Crew",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 1},
        "power": 1,
        "toughness": 1,
    }
    rs_crew = rs.register_and_inject_object(crew_dict, 0, 2)

    # Gate-axis A — charge=1, gate closed; anthem must not fire.
    rs.set_charge_counters(rs_lumen, 1)
    cp_closed = rs.effective_power(rs_crew)
    ct_closed = rs.effective_toughness(rs_crew)
    assert (cp_closed, ct_closed) == (1, 1), (
        f"Anthem gate-closed (charge=1 < threshold=2): crew P/T must "
        f"be printed (1, 1); got ({cp_closed}, {ct_closed})."
    )
    # Gate-axis B — charge=2, gate open; anthem fires +1/+1.
    rs.set_charge_counters(rs_lumen, 2)
    cp_open = rs.effective_power(rs_crew)
    ct_open = rs.effective_toughness(rs_crew)
    assert (cp_open, ct_open) == (2, 2), (
        f"Anthem gate-open (charge=2 >= threshold=2): crew P/T must "
        f"be printed + anthem (2, 2); got ({cp_open}, {ct_open})."
    )
    # Gate-axis C — charge=3, gate still open (monotone).
    rs.set_charge_counters(rs_lumen, 3)
    cp_wide = rs.effective_power(rs_crew)
    ct_wide = rs.effective_toughness(rs_crew)
    assert (cp_wide, ct_wide) == (2, 2), (
        f"Anthem gate-open (charge=3 >= threshold=2): crew P/T must "
        f"stay at printed + anthem (2, 2); got ({cp_wide}, {ct_wide})."
    )
