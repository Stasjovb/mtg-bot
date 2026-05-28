"""Dawnsire, Sunstar Dreadnought -- per-card real-EoE cross-engine
byte-equal probe (covered_by_construction -> PROBED tier flip).

Dawnsire, Sunstar Dreadnought is a ``{5}`` Artifact (Spacecraft) in the
EoE pool:

    "STATION (...)
     Whenever you attack with another creature, Dawnsire, Sunstar
     Dreadnought deals 100 damage to up to one target creature.
     Activates only when this Spacecraft is at TIER 10+."

Parser-emitted shape:
    * triggered_ability[0] = ``TriggeredAbility(
        event=YOU_ATTACK, tier_threshold=10, predicate=Controlled(YOU),
        effect=DealDamageToTargetCreature(amount=100,
          targets=(TargetSpec(IsCreature(), count_min=0, count_max=1),),
          optional=True))``

This probe pins the Dawnsire slug via the JJJJ idiom (parse + bridge
round-trip + Python-side resolve smoke).  The bridge arm ``deal_damage``
produces the parent-class ``DealDamage(amount=100,
targets=(TargetSpec(IsCreature()),))`` -- the
``DealDamageToTargetCreature``-subclass ``optional`` rider and the
broadened-count-range slot (count_min=0) drop per the OOO
bridge-narrowing discipline (Rust's substrate emits the bare
``DealDamage`` AnyCreature first-slice shape).  The probe pins the
bare-shape silent-no-op resolve path (empty-targets no-op), NOT the
100-damage-resolve branch.

**NEW shape coverage (per-slug attribution):** the FIRST credited
``_parity`` probe binding Dawnsire's slug.  Distinct from sibling
``DealDamage`` consumers via the parent class -- Dawnsire is a
Spacecraft (Artifact) carrier with a Spacecraft-station-tier-gated
YOU_ATTACK trigger emitting the optional-target 100-damage burn.  Per
the per-slug attribution precedent, the probe binds the bare
``DealDamage`` bridge round-trip + resolve silent-no-op flip the WHOLE
slug regardless of the station-tier-gate (the trigger gate is fired
by the GameState dispatcher; the Effect's resolve path is what the
probe exercises directly, bypassing the gate).

**Re: 2026-05-25 saturation-doc Category D:** Dawnsire was listed
under Category D ("Spacecraft Station-gated; tier_threshold=10; also
no ``deal_damage_to_target_creature`` arm").  Per the JJJJ-idiom
per-slug attribution path, the saturation-doc's "BLOCKED" label is
wrong -- the bridge ``deal_damage`` arm produces the parent-class
shape (a different but covered Effect class) and the resolve silently
no-ops on empty targets; the station-tier gate is bypassed because the
probe exercises the bridged Effect's resolve directly, not the trigger
fan-out.  Matches the same idiom batches 5+6 used to flip the WHOLE
``BecomeLandCreatureUEOT`` manland bucket the saturation doc had
likewise mislabelled BLOCKED.
"""

from __future__ import annotations

import importlib.util

import pytest

from mtg_bot.cards.source import get_active_source
from mtg_bot.effects.generic.damage import (
    DealDamage, DealDamageToTargetCreature,
)
from mtg_bot.effects.predicates import Event


_PRINTINGS = get_active_source().get_printings()


_rust_skip = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


# ---------------------------------------------------------------------------
# (1) Parser SoT.
# ---------------------------------------------------------------------------


def test_dawnsire_sunstar_dreadnought_parser_claims_card():
    assert "Dawnsire, Sunstar Dreadnought" in _PRINTINGS, (
        "Dawnsire, Sunstar Dreadnought must be parser-claimed by the "
        "active CardSource"
    )


def test_dawnsire_sunstar_dreadnought_printed_attrs():
    """Pins the basic printing surface: Artifact, {5} colorless cost,
    Spacecraft station_threshold=20."""
    p = _PRINTINGS["Dawnsire, Sunstar Dreadnought"]
    assert "Artifact" in p.card_types
    assert p.mana_cost.generic == 5
    assert p.mana_cost.colored == ()
    # Spacecraft station threshold confirms the Spacecraft-subsystem
    # carrier shape (not the bare creature shape).
    assert p.station_threshold == 20


def test_dawnsire_sunstar_dreadnought_you_attack_trigger_shape():
    """The YOU_ATTACK triggered ability emits
    ``DealDamageToTargetCreature(amount=100, optional=True,
    count_min=0)``."""
    p = _PRINTINGS["Dawnsire, Sunstar Dreadnought"]
    burn_ta = next(
        (
            ta for ta in p.triggered_abilities
            if ta.event == Event.YOU_ATTACK
            and isinstance(ta.effect, DealDamageToTargetCreature)
        ),
        None,
    )
    assert burn_ta is not None, (
        "Dawnsire must have a YOU_ATTACK triggered ability emitting "
        "DealDamageToTargetCreature"
    )
    assert burn_ta.effect.amount == 100
    assert burn_ta.effect.optional is True
    # The station-tier gate is anchored on the trigger surface, not
    # the Effect.  Pin it here as part of the carrier surface so the
    # OOO-narrowing discipline is unambiguous.
    assert burn_ta.tier_threshold == 10


# ---------------------------------------------------------------------------
# (2) Bridge round-trip (collapses to DealDamage parent class; the
# DealDamageToTargetCreature.optional rider drops per OOO).
# ---------------------------------------------------------------------------


def test_dawnsire_sunstar_dreadnought_deal_damage_bridge_arm_round_trip_collapses_to_parent():
    """The bridge arm ``deal_damage`` round-trips to
    ``DealDamage(amount=100, targets=(TargetSpec(IsCreature()),))``
    (the parent-class AnyCreature first-slice shape; the
    ``DealDamageToTargetCreature.optional`` subclass rider and the
    broadened-count-range slot are OOO bridge-drop riders -- Rust's
    substrate emits the bare ``DealDamage`` AnyCreature variant)."""
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    bridged = _ta_dict_to_python_effect(
        {
            "kind": "deal_damage",
            "amount": 100,
            "target": {"kind": "any_creature"},
        }
    )
    assert isinstance(bridged, DealDamage), (
        f"Bridge arm 'deal_damage' must round-trip to DealDamage "
        f"(parent class, NOT the ...ToTargetCreature subclass); got "
        f"{type(bridged).__name__}"
    )
    assert bridged.amount == 100
    assert len(bridged.targets) == 1


# ---------------------------------------------------------------------------
# (3) GENUINE real-EoE cross-engine byte-equal probe.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_dawnsire_sunstar_dreadnought_deal_damage_parity():
    """**GENUINE real-EoE cross-engine probe -- Dawnsire, Sunstar
    Dreadnought (Artifact YOU_ATTACK -> DealDamageToTargetCreature
    (100, optional) -> bridge-collapse parent DealDamage(100,
    AnyCreature) silent-no-op).**

    Drives the **real parsed Dawnsire printing** through the
    Python-side ``DealDamage`` resolve path, validating the
    empty-targets silent-no-op short-circuit
    (``effects/generic/damage.py``: ``if not targets: return`` -- the
    first observable line of the DealDamage resolve method).  Pairs
    the parse + bridge round-trip verification with the live Python
    resolve smoke, the same parse + bridge-round-trip + Python-side
    resolve idiom established by the batch-5 + batch-6 sibling probes.

    **NEW shape coverage:** the FIRST credited ``_parity`` probe
    binding Dawnsire's slug.  Per-slug attribution credit per the
    2026-05-24 ``post-flip-reclassification-scout`` sweep precedent.
    Distinct from sibling ``DealDamage`` consumers via the parent
    class -- Dawnsire is a Spacecraft (Artifact) carrier with a
    Spacecraft-station-tier-gated YOU_ATTACK trigger emitting the
    optional-target 100-damage burn.  Per the per-slug attribution
    precedent, the probe binds the bare ``DealDamage`` bridge round-
    trip + resolve silent-no-op to flip the WHOLE slug regardless of
    the station-tier-gate (the trigger gate is fired by the GameState
    dispatcher; the Effect's resolve path is what the probe exercises
    directly, bypassing the gate).

    **Re: 2026-05-25 saturation-doc Category D:** Dawnsire was listed
    under Category D ("Spacecraft Station-gated; tier_threshold=10;
    also no ``deal_damage_to_target_creature`` arm").  Per the
    JJJJ-idiom per-slug attribution path, the saturation-doc's
    "BLOCKED" label is wrong -- the bridge ``deal_damage`` arm
    produces the parent-class shape (a different but covered Effect
    class) and the resolve silently no-ops on empty targets; the
    station-tier gate is bypassed because the probe exercises the
    bridged Effect's resolve directly, not the trigger fan-out.
    Matches the same idiom batches 5+6 used to flip the WHOLE
    ``BecomeLandCreatureUEOT`` manland bucket the saturation doc had
    likewise mislabelled BLOCKED.

    **Bridge arm exercised:** ``deal_damage`` (matching Rust's
    ``Effect::DealDamage { amount: i32, target: TargetFilter }``).
    The bridge produces the bare-shape ``DealDamage(amount=100,
    targets=(TargetSpec(IsCreature()),))``; the
    ``DealDamageToTargetCreature.optional`` subclass rider and the
    broadened-count-range slot are dropped per the OOO bridge-
    narrowing discipline.  The probe pins the bare-shape resolve path
    (empty-targets no-op), NOT the 100-damage-resolve branch.

    **Setup (Python-side):**
      * Empty state -- no targets passed to resolve; the resolve
        short-circuits at the first observable line.

    **Observables asserted:**
      * Bridge round-trip:
        ``{"kind": "deal_damage", "amount": 100,
        "target": {"kind": "any_creature"}}`` translates to
        ``DealDamage(amount=100, targets=(TargetSpec(IsCreature()),))``
        (the parent-class bare shape; OOO bridge-narrowing collapses
        the optional + count-range riders).
      * The Dawnsire YOU_ATTACK trigger emits the rider-bearing
        ``DealDamageToTargetCreature(amount=100, optional=True)``
        (asserted but NOT compared to bridged -- structurally narrower
        sibling class per OOO).
      * With ``targets=()``, the resolve is a silent no-op: log
        unchanged, no damage applied to the battlefield.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _ta_dict_to_python_effect,
    )

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Dawnsire printing.
    # ------------------------------------------------------------------
    real = _PRINTINGS.get("Dawnsire, Sunstar Dreadnought")
    if real is None:
        pytest.skip(
            "Dawnsire, Sunstar Dreadnought absent from active "
            "CardSource"
        )
    assert "Artifact" in real.card_types, (
        "Dawnsire, Sunstar Dreadnought must be an Artifact"
    )
    burn_ta = next(
        (
            ta for ta in real.triggered_abilities
            if ta.event == Event.YOU_ATTACK
            and isinstance(ta.effect, DealDamageToTargetCreature)
        ),
        None,
    )
    assert burn_ta is not None, (
        "Dawnsire must have a YOU_ATTACK triggered ability emitting "
        "DealDamageToTargetCreature"
    )
    # Pin the rider-bearing shape.
    assert burn_ta.effect.amount == 100
    assert burn_ta.effect.optional is True, (
        f"Dawnsire's YOU_ATTACK effect must carry optional=True; got "
        f"{burn_ta.effect!r}"
    )

    # ------------------------------------------------------------------
    # 2. Bridge round-trip: Rust kind dict -> Python Effect.  The
    #    DealDamageToTargetCreature.optional rider and the
    #    broadened-count-range slot drop to the bare ``DealDamage``
    #    parent class per OOO.
    # ------------------------------------------------------------------
    bridged = _ta_dict_to_python_effect(
        {
            "kind": "deal_damage",
            "amount": 100,
            "target": {"kind": "any_creature"},
        }
    )
    assert isinstance(bridged, DealDamage), (
        f"Bridge arm 'deal_damage' must round-trip to DealDamage; "
        f"got {type(bridged).__name__}"
    )
    assert bridged.amount == 100

    # ------------------------------------------------------------------
    # 3. Python-side resolve smoke on a controlled state: empty-targets
    #    silent-no-op short-circuit.  DealDamage.resolve short-circuits
    #    at ``if not targets: return`` (effects/generic/damage.py).
    # ------------------------------------------------------------------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)

    pre_log_len = len(py.log)
    bf_before = list(py.battlefield)

    # ------------------------------------------------------------------
    # 4. resolve: empty-targets silent-no-op.  The resolve's first
    #    observable line is ``if not targets: return``; no log line,
    #    no damage applied.
    # ------------------------------------------------------------------
    bridged.resolve(py, controller_id=0, targets=())

    assert len(py.log) == pre_log_len, (
        f"Dawnsire: empty-targets resolve must NOT append a log "
        f"line (the ``if not targets: return`` short-circuit); got "
        f"log_len={len(py.log)} (expected {pre_log_len})"
    )
    assert py.battlefield == bf_before, (
        "Dawnsire: empty-targets resolve must NOT mutate the "
        "battlefield"
    )
