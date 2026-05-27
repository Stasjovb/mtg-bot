"""**Spacecraft Station substrate Phase 4 Cycle 2 (2026-05-26).**

Cycle 2 admit-gate FLIP tests for The Eternity Elevator per
``docs/SPACECRAFT_STATION_SUBSTRATE_PHASE_4_DESIGN.md`` §5 cycle
plan. Cycle 2 is Python-only (no Rust changes — the C1 substrate at
commit ``354588a5`` shipped the Rust ``Effect::
AddChargeCounterManaOfChosenColor`` variant + cross-engine bridge
arms).

Deliverables (Cycle 2 Python slice, per design doc §5):

  - ``_carrier_aa_phase_1_effect_classes`` widen: adds
    ``AddChargeCounterManaOfChosenColor`` (size 14 -> 15).
  - ``_aa_is_phase1_sub_shape_a`` AA-rider widen: lifts the
    ``tier_threshold > 0`` decline to admit AA[1]'s
    ``tier_threshold=20``. Negative ``tier_threshold`` stays declined
    as defense-in-depth.
  - ``_python_aa_to_safe_dict`` widen: emits ``tier_threshold`` on
    the AA dict (empty-omit when 0, mirror of the
    ``is_mana_ability`` / ``sorcery_speed`` empty-omit discipline).
  - ``_aa_dict_to_python_activated_ability`` widen: reads the
    ``tier_threshold`` key back from the AA dict (default 0; bool
    rejected per the Rust ``cards.rs:17875+`` type-strict mirror).
  - New ``_printing_is_bridge_phase_4_spacecraft_eternity_elevator``
    admit predicate.
  - New ``_eternity_elevator_card_def`` builder.
  - OR-chain registration in ``_filter_deck_to_bridge_supported``
    (admits The Eternity Elevator).
  - ``_printing_to_card_def`` dispatch arm.
  - ``scripts/measure_pool_parity.loader_admits`` sync (mirrors the
    canonical OR-chain).

Post-C2 admit set: PHASE_4_ADMITTED_SPACECRAFT = {"The Eternity
Elevator"} (size 1). The 7 Phase-1/2/3 Spacecraft admits stay
admitted; the Eternity Elevator FLIPS DECLINED -> ADMITTED.

ZERO Rust changes this cycle (C1 shipped the substrate).
ZERO per-card real-EoE probe this cycle (Cycle 3 ships the
``tests/test_the_eternity_elevator_parity.py`` real-EoE probe).
"""

from __future__ import annotations

import json

import pytest


# ---------------------------------------------------------------------------
# Eternity Elevator admit-gate FLIP — load-bearing C2 invariant
# ---------------------------------------------------------------------------


def _load_eternity_elevator():
    from mtg_bot.cards.parser_source import (
        _build_spacecraft_printing as build_spacecraft_printing,
    )

    with open("data/edge_of_eternities.json", encoding="utf-8") as f:
        raw_cards = json.load(f)
    raw = next(
        (c for c in raw_cards if c.get("name") == "The Eternity Elevator"),
        None,
    )
    assert raw is not None
    printing = build_spacecraft_printing(raw)
    assert printing is not None
    return printing


def test_eternity_elevator_admits_at_phase_4_predicate():
    """**Load-bearing FLIP pin.** The new Phase 4 admit predicate
    ``_printing_is_bridge_phase_4_spacecraft_eternity_elevator``
    admits The Eternity Elevator's live printing.
    """
    from mtg_bot.parity.trajectory import (
        _printing_is_bridge_phase_4_spacecraft_eternity_elevator,
    )

    printing = _load_eternity_elevator()
    assert (
        _printing_is_bridge_phase_4_spacecraft_eternity_elevator(printing)
        is True
    )


def test_eternity_elevator_admits_at_canonical_or_chain():
    """**End-to-end OR-chain pin.** The canonical
    ``_filter_deck_to_bridge_supported`` admit gate admits The
    Eternity Elevator (the FLIP fires through the OR-chain disjunct
    landed at trajectory.py).
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import _filter_deck_to_bridge_supported

    src = OracleParserCardSource()
    prints = src.get_printings()
    names, defs = _filter_deck_to_bridge_supported(
        ["The Eternity Elevator"],
        prints,
    )
    assert names == ["The Eternity Elevator"], (
        "Eternity Elevator must pass the production deck filter; "
        f"got names={names}"
    )
    assert len(defs) == 1
    assert defs[0].name == "The Eternity Elevator"
    assert defs[0].card_type == "Artifact"
    assert defs[0].subtypes == ("Spacecraft",)
    assert defs[0].supertypes == ("Legendary",)
    assert defs[0].station_threshold is None
    assert len(defs[0].activated_abilities) == 2


def test_eternity_elevator_admits_at_loader_admits_helper():
    """**Helper-vs-canonical mirror pin.** The pool-parity
    ``loader_admits`` helper now admits The Eternity Elevator (the
    C2 widen synced the helper with the canonical gate).
    """
    from scripts.measure_pool_parity import loader_admits

    printing = _load_eternity_elevator()
    assert loader_admits(printing) is True


def test_eternity_elevator_card_def_shape():
    """The Phase-4 CardDef builder emits the expected shape — Legendary
    Artifact Spacecraft with 2 round-tripped AAs, no
    station_threshold, no stationed_keywords.
    """
    from mtg_bot.parity.trajectory import (
        _eternity_elevator_card_def,
        _printing_to_card_def,
    )

    printing = _load_eternity_elevator()
    card_def = _eternity_elevator_card_def(printing)
    assert card_def is not None
    assert card_def.name == "The Eternity Elevator"
    assert card_def.card_type == "Artifact"
    assert card_def.subtypes == ("Spacecraft",)
    assert card_def.supertypes == ("Legendary",)
    # Non-animating: station_threshold stays at the default None on
    # the CardDef so the forward-emit arm in
    # _spec_card_to_printing_dict omits the registry key.
    assert card_def.station_threshold is None
    assert card_def.stationed_keywords == ()
    # Multi-AA round-trip — 2 AAs both serialize.
    assert len(card_def.activated_abilities) == 2
    aa0_dict, aa1_dict = card_def.activated_abilities
    # AA[0] — basic {T}: Add {C}{C}{C}. Mana-ability, no tier gate.
    assert aa0_dict["cost"] == {"tap_self": True}
    assert aa0_dict["effect"] == {
        "kind": "add_mana_to_pool",
        "color": "C",
        "amount": 3,
    }
    assert aa0_dict["is_mana_ability"] is True
    assert "tier_threshold" not in aa0_dict, (
        "Empty-omit discipline: tier_threshold=0 omits the key"
    )
    # AA[1] — 20+ tier-gated {T}: Add X mana of any one color.
    assert aa1_dict["cost"] == {"tap_self": True}
    assert aa1_dict["effect"] == {
        "kind": "add_charge_counter_mana_of_chosen_color",
    }
    assert aa1_dict["is_mana_ability"] is True
    assert aa1_dict["tier_threshold"] == 20

    # _printing_to_card_def dispatches to the same builder — round-
    # trip the full dispatcher.
    cd_via_dispatch = _printing_to_card_def(printing)
    assert cd_via_dispatch.name == card_def.name
    assert cd_via_dispatch.card_type == card_def.card_type
    assert cd_via_dispatch.activated_abilities == card_def.activated_abilities


# ---------------------------------------------------------------------------
# Phase 4 admit-set walk — no-silent-auto-grow
# ---------------------------------------------------------------------------


def test_phase_4_admit_set_is_exactly_the_eternity_elevator():
    """**No-silent-auto-grow pin.** Walks the full EoE pool through
    the new Phase 4 admit predicate; the admit set must be
    EXACTLY {The Eternity Elevator}.

    A regression here would mean the Phase 4 admit-set bump silently
    auto-admitted some other printing — the load-bearing invariant
    of design doc §1.

    Per the design doc §1.3 walk: The Eternity Elevator is the SOLE
    ``station_threshold=None`` carrier in the live 22-Spacecraft EoE
    set. Every other Spacecraft has an integer station_threshold and
    flows through Phase 1/2/3.
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import (
        _printing_is_bridge_phase_4_spacecraft_eternity_elevator,
    )

    src = OracleParserCardSource()
    prints = src.get_printings()
    admits = []
    for name, p in prints.items():
        try:
            if _printing_is_bridge_phase_4_spacecraft_eternity_elevator(p):
                admits.append(name)
        except Exception:
            # Defense-in-depth — a malformed printing must NOT count
            # as an admit (mirrors the loader_admits exception
            # envelope at measure_pool_parity.py).
            pass
    assert sorted(admits) == ["The Eternity Elevator"], (
        "Spacecraft Phase 4 C2 no-silent-auto-grow invariant: the "
        f"Phase-4 admit predicate must admit ONLY The Eternity "
        f"Elevator in the live EoE pool. Got admits={admits}."
    )


# ---------------------------------------------------------------------------
# Adjacent-regression — Phase 1/2/3 Spacecraft admit sets unchanged
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name", [
        "Galvanizing Sawship",
    ],
)
def test_phase_1_spacecraft_admits_unchanged(name):
    """**Adjacent-regression pin.** The Phase 1 zero-ability
    Spacecraft admit set is unchanged at Phase 4 C2 close —
    Galvanizing Sawship stays admitted at
    ``_printing_is_bridge_pure_station_spacecraft``.
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import (
        _printing_is_bridge_pure_station_spacecraft,
    )

    src = OracleParserCardSource()
    p = src.get_printings()[name]
    assert _printing_is_bridge_pure_station_spacecraft(p) is True


@pytest.mark.parametrize(
    "name", [
        "Lumen-Class Frigate",
    ],
)
def test_phase_2_spacecraft_admits_unchanged(name):
    """**Adjacent-regression pin.** The Phase 2 static-anthem
    Spacecraft admit set is unchanged at Phase 4 C2 close —
    Lumen-Class Frigate stays admitted at
    ``_printing_is_bridge_phase_2_static_anthem_spacecraft``.
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import (
        _printing_is_bridge_phase_2_static_anthem_spacecraft,
    )

    src = OracleParserCardSource()
    p = src.get_printings()[name]
    assert _printing_is_bridge_phase_2_static_anthem_spacecraft(p) is True


@pytest.mark.parametrize(
    "name", [
        "Larval Scoutlander",
        "Sledge-Class Seedship",
        "Synthesizer Labship",
        "Entropic Battlecruiser",
        "Infinite Guideline Station",
    ],
)
def test_phase_3_spacecraft_admits_unchanged(name):
    """**Adjacent-regression pin.** The Phase 3 trigger-bearing
    Spacecraft admit set is unchanged at Phase 4 C2 close — all 5
    Phase-3 admits stay admitted at
    ``_printing_is_bridge_phase_3_trigger_spacecraft``.
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import (
        _printing_is_bridge_phase_3_trigger_spacecraft,
    )

    src = OracleParserCardSource()
    p = src.get_printings()[name]
    assert _printing_is_bridge_phase_3_trigger_spacecraft(p) is True


def test_phase_4_predicate_declines_every_animating_spacecraft():
    """**No-silent-auto-grow pin (negative).** The new Phase 4 admit
    predicate must DECLINE every animating Spacecraft (the 7 Phase
    1/2/3 admits + every multi-gated Spacecraft). The Phase-4
    sibling is non-animating-only — admitting an animating shape
    would be a silent auto-grow on the Phase 1/2/3 axis.
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import (
        _printing_is_bridge_phase_4_spacecraft_eternity_elevator,
    )

    src = OracleParserCardSource()
    prints = src.get_printings()
    spacecraft = [
        (name, p) for name, p in prints.items()
        if "Spacecraft" in (p.subtypes or ())
    ]
    assert len(spacecraft) >= 22, (
        "Verify-first guard: expected at least 22 Spacecraft in the "
        f"EoE pool (live count); got {len(spacecraft)}"
    )
    for name, p in spacecraft:
        if p.station_threshold is not None:
            # Animating — must DECLINE at the Phase 4 predicate.
            assert (
                _printing_is_bridge_phase_4_spacecraft_eternity_elevator(p)
                is False
            ), (
                f"Spacecraft Phase 4 C2 negative-invariant: animating "
                f"Spacecraft {name!r} (station_threshold="
                f"{p.station_threshold}) must DECLINE at the Phase 4 "
                f"predicate — Phase-4 is non-animating-only."
            )


# ---------------------------------------------------------------------------
# Carrier-AA Phase 4A admit sets unchanged (per-AA gate widen is
# additive; no other carrier's per-AA shape includes the new Effect
# class so no spillover admit)
# ---------------------------------------------------------------------------


def test_carrier_aa_land_admits_unchanged_post_c2():
    """**Adjacent-regression pin.** The Carrier-AA Phase 1.5a + 2a + 3
    Land admit set is unchanged at Spacecraft Phase 4 C2 close.

    The Phase-4 widens don't touch the Land-typed Carrier-AA admit
    set — the new Effect class (``AddChargeCounterManaOfChosenColor``)
    has no Land-typed live consumer, the lifted ``tier_threshold``
    AA-rider gate has no Land-typed live consumer (no Land carrier in
    the EoE pool carries a tier_threshold>0 AA), so the Land admit
    count stays bit-identical to pre-C2.
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import (
        _printing_is_bridge_simple_carrier_aa_land,
    )

    src = OracleParserCardSource()
    prints = src.get_printings()
    admits = sorted(
        name for name, p in prints.items()
        if _printing_is_bridge_simple_carrier_aa_land(p)
    )
    # Pre-C2 baseline (post-Carrier-AA-Phase-3C-C3 close):
    #   Swarmyard + Deserted Temple + Petrified Field + Terrain
    #   Generator + Mystifying Maze + Scavenger Grounds + Thespian's
    #   Stage (Phase-3 admits) + Crystal Quarry + Eldrazi Temple +
    #   Gemstone Caverns + Sunken Citadel (off-set Carrier-AA Lands
    #   the predicate admits incidentally — full Carrier-AA admit
    #   sweep landed pre-C2). The Spacecraft Phase 4 C2 widens are
    #   admit-set-neutral on the Land sibling.
    assert "Swarmyard" in admits
    assert "Deserted Temple" in admits
    assert "Petrified Field" in admits
    assert "Terrain Generator" in admits
    assert "Mystifying Maze" in admits
    assert "Scavenger Grounds" in admits
    assert "Thespian's Stage" in admits
    # The Eternity Elevator must NOT show up here (different sibling).
    assert "The Eternity Elevator" not in admits


def test_carrier_aa_artifact_admits_unchanged_post_c2():
    """**Adjacent-regression pin.** The Carrier-AA Phase 4A.2
    Artifact admit set is unchanged at Spacecraft Phase 4 C2 close.

    The Phase-4 widens don't touch the Artifact-typed Carrier-AA
    admit set — the new Effect class has no non-Spacecraft Artifact-
    typed live consumer, the lifted ``tier_threshold`` AA-rider gate
    has no Artifact-typed live consumer either (the only
    tier_threshold>0 AA in the EoE pool is on The Eternity Elevator,
    which routes through the Phase-4 sibling, not the
    Carrier-AA-Artifact sibling). The Phase-4A.2 empty-subtypes guard
    rejects any Spacecraft-subtyped Artifact unchanged.
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import (
        _printing_is_bridge_simple_carrier_aa_artifact,
    )

    src = OracleParserCardSource()
    prints = src.get_printings()
    admits = sorted(
        name for name, p in prints.items()
        if _printing_is_bridge_simple_carrier_aa_artifact(p)
    )
    # Pre-C2 baseline (post-Carrier-AA-Phase-4C-C2 + 4D-C2 + 4E-C2
    # partial close): Ghost Vacuum + Keys to the House + All-Fates
    # Scroll (Phase 4C/4D/4E admits). The Eternity Elevator must NOT
    # show up here — the Spacecraft subtype rejects at the empty-
    # subtypes guard.
    assert "Ghost Vacuum" in admits
    assert "Keys to the House" in admits
    assert "All-Fates Scroll" in admits
    assert "The Eternity Elevator" not in admits, (
        "Spacecraft Phase 4 C2 invariant: The Eternity Elevator must "
        "route through the new Phase-4 Spacecraft sibling, NOT the "
        "Carrier-AA Phase-4A.2 Artifact sibling. The Artifact admit's "
        "empty-subtypes guard rejects the Spacecraft subtype "
        "unchanged at Phase 4 C2."
    )


# ---------------------------------------------------------------------------
# Bridge floor tier_threshold round-trip pins (synthetic + back-compat)
# ---------------------------------------------------------------------------


def test_python_aa_to_safe_dict_emits_tier_threshold_when_nonzero():
    """**Bridge-floor emit-arm pin.** ``_python_aa_to_safe_dict``
    emits the ``tier_threshold`` key on the AA dict when the AA's
    ``tier_threshold`` is non-zero. Empty-omit when 0 (back-compat
    with every pre-Phase-4-C2 serializer).
    """
    from mtg_bot.effects.base import ActivatedAbility, ActivationCost
    from mtg_bot.effects.generic.mana import (
        AddChargeCounterManaOfChosenColor,
    )
    from mtg_bot.parity.cross_engine import _python_aa_to_safe_dict

    # tier_threshold>0 — emitted.
    aa = ActivatedAbility(
        cost=ActivationCost(tap_self=True),
        effect=AddChargeCounterManaOfChosenColor(),
        is_mana_ability=True,
        tier_threshold=20,
    )
    d = _python_aa_to_safe_dict(aa)
    assert d is not None
    assert d["tier_threshold"] == 20

    # tier_threshold=0 — omitted (back-compat).
    aa0 = ActivatedAbility(
        cost=ActivationCost(tap_self=True),
        effect=AddChargeCounterManaOfChosenColor(),
        is_mana_ability=True,
        tier_threshold=0,
    )
    d0 = _python_aa_to_safe_dict(aa0)
    assert d0 is not None
    assert "tier_threshold" not in d0


def test_aa_dict_to_python_activated_ability_reads_tier_threshold():
    """**Bridge-floor parse-arm pin.**
    ``_aa_dict_to_python_activated_ability`` reads the
    ``tier_threshold`` key back when present, defaults to 0 when
    absent (back-compat), and raises on bool / non-int / negative
    (mirror of the Rust ``cards.rs:17865+`` type-strict checks).
    """
    from mtg_bot.parity.cross_engine import (
        _aa_dict_to_python_activated_ability,
    )

    base = {
        "cost": {"tap_self": True},
        "effect": {"kind": "add_charge_counter_mana_of_chosen_color"},
        "is_mana_ability": True,
    }
    # Key absent — defaults to 0.
    aa_default = _aa_dict_to_python_activated_ability(base)
    assert aa_default.tier_threshold == 0

    # Key present, int.
    aa_with = _aa_dict_to_python_activated_ability(
        {**base, "tier_threshold": 20},
    )
    assert aa_with.tier_threshold == 20

    # bool is NOT a valid tier_threshold (Rust type-strict mirror).
    with pytest.raises(ValueError):
        _aa_dict_to_python_activated_ability(
            {**base, "tier_threshold": True},
        )

    # Non-int.
    with pytest.raises(ValueError):
        _aa_dict_to_python_activated_ability(
            {**base, "tier_threshold": "20"},
        )

    # Negative — defense-in-depth (Rust parse arm rejects).
    with pytest.raises(ValueError):
        _aa_dict_to_python_activated_ability(
            {**base, "tier_threshold": -1},
        )


def test_aa_is_phase1_sub_shape_a_admits_tier_threshold_positive():
    """**Per-AA admit-gate widen pin.** ``_aa_is_phase1_sub_shape_a``
    admits ``tier_threshold > 0`` post-C2 (the C2 widen lifts the
    Phase-1 honest-stop).
    """
    from mtg_bot.effects.base import ActivatedAbility, ActivationCost
    from mtg_bot.effects.generic.mana import (
        AddChargeCounterManaOfChosenColor,
    )
    from mtg_bot.parity.trajectory import _aa_is_phase1_sub_shape_a

    aa = ActivatedAbility(
        cost=ActivationCost(tap_self=True),
        effect=AddChargeCounterManaOfChosenColor(),
        is_mana_ability=True,
        tier_threshold=20,
    )
    assert _aa_is_phase1_sub_shape_a(aa) is True

    # Negative tier_threshold still declines (defense-in-depth —
    # Rust parse arm rejects).
    aa_neg = ActivatedAbility(
        cost=ActivationCost(tap_self=True),
        effect=AddChargeCounterManaOfChosenColor(),
        is_mana_ability=True,
        tier_threshold=-1,
    )
    assert _aa_is_phase1_sub_shape_a(aa_neg) is False


def test_eternity_elevator_card_def_two_aas_round_trip_byte_equal():
    """**Builder + bridge floor round-trip pin.** The Eternity
    Elevator's CardDef carries 2 AA dicts; both round-trip through
    ``_aa_dict_to_python_activated_ability`` to byte-equal the live
    parser SoT AAs.
    """
    from mtg_bot.parity.cross_engine import (
        _aa_dict_to_python_activated_ability,
    )
    from mtg_bot.parity.trajectory import _eternity_elevator_card_def

    printing = _load_eternity_elevator()
    card_def = _eternity_elevator_card_def(printing)
    assert card_def is not None
    assert len(card_def.activated_abilities) == 2
    aa0_back = _aa_dict_to_python_activated_ability(
        card_def.activated_abilities[0],
    )
    aa1_back = _aa_dict_to_python_activated_ability(
        card_def.activated_abilities[1],
    )
    assert aa0_back == printing.activated_abilities[0]
    assert aa1_back == printing.activated_abilities[1]
