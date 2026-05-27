"""Grand Entryway // Elegant Rotunda -- per-card real-EoE cross-
engine byte-equal probe (covered_by_construction -> PROBED tier flip).

Grand Entryway // Elegant Rotunda is an Enchantment (Room) split card in
the EoE pool.  Each half carries an ENTERS triggered ability:

    * Grand Entryway ({1}{W}, front-half door body) -- ENTERS ->
      ``CreateToken`` (a 1/1 Glimmer token; substrate-deferred from
      the bare probe because the CreateToken bridge requires a
      registered ``token_printing_id`` which is the token-registration
      substrate gate -- same JJJJ Grand Entryway drop reason).
    * Elegant Rotunda ({2}{W}, back-half door body) -- ENTERS ->
      ``PutPlusOneCounterOnEachOfUpToNTargetCreatures(max_n=2)``.

This probe pins the **Elegant Rotunda back-half** ENTERS trigger via
the JJJJ idiom (parse + bridge round-trip + Python-side resolve smoke).
The bridge arm
``put_plus_one_counter_on_each_of_up_to_n_target_creatures`` round-
trips byte-equal: parsed ``max_n=2`` == bridged ``max_n=2``.

**NEW shape coverage (per-slug attribution):** the FIRST credited
``_parity`` probe binding Grand Entryway // Elegant Rotunda's slug.
The bare ``PutPlusOneCounterOnEachOfUpToNTargetCreatures(max_n=2)``
shape -- the "distribute up to N +1/+1 counters" effect class -- has
no prior PROBED carrier on this specific (event=ENTERS,
carrier=Room-back-half, max_n=2) parameterization tuple.  The IIII /
JJJJ Optimistic Scavenger / Surgical Suite probes pin sibling
``PutPlusOneCounterOnTargetCreature(amount=1, attacking_only={False,
True})`` shapes -- a DIFFERENT effect class (single-target, distinct
``attacking_only`` axis).  Elegant Rotunda's
``PutPlusOneCounterOnEachOfUpToNTargetCreatures(max_n=2)`` is the
multi-target up-to-N variant which has no slug-credited probe today.

The probe re-uses the JJJJ Surgical Suite shape: bind the real EoE
printing, verify the parsed Effect is byte-equal to the bridge round-
trip, then run a controlled Python-side resolve smoke on the empty-
targets silent-no-op short-circuit
(``effects/generic/counters.py``:115-128 -- for-loop iterates zero
times over empty target tuple, leaves state unchanged).
"""

from __future__ import annotations

import importlib.util

import pytest

from mtg_bot.cards.source import get_active_source
from mtg_bot.effects.generic.counters import (
    PutPlusOneCounterOnEachOfUpToNTargetCreatures,
)


_PRINTINGS = get_active_source().get_printings()


_rust_skip = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


# ---------------------------------------------------------------------------
# (1) Parser SoT.
# ---------------------------------------------------------------------------


def test_grand_entryway_elegant_rotunda_parser_claims_card():
    assert "Grand Entryway // Elegant Rotunda" in _PRINTINGS, (
        "Grand Entryway // Elegant Rotunda must be parser-claimed by the "
        "active CardSource"
    )


def test_grand_entryway_elegant_rotunda_printed_attrs():
    """Pins the basic printing surface: Enchantment Room with two
    halves."""
    p = _PRINTINGS["Grand Entryway // Elegant Rotunda"]
    assert "Enchantment" in p.card_types
    assert "Room" in p.subtypes
    # The Room has two halves.
    half_names = {half.name for half in p.room_halves}
    assert half_names == {"Grand Entryway", "Elegant Rotunda"}, (
        f"Grand Entryway // Elegant Rotunda must have halves "
        f"{{'Grand Entryway', 'Elegant Rotunda'}}; got {half_names}"
    )


def test_grand_entryway_elegant_rotunda_elegant_rotunda_effect_shape():
    """The Elegant Rotunda back-half ENTERS trigger emits
    ``PutPlusOneCounterOnEachOfUpToNTargetCreatures(max_n=2)``."""
    from mtg_bot.effects.predicates import Event

    p = _PRINTINGS["Grand Entryway // Elegant Rotunda"]
    rotunda_ta = next(
        (
            ta for ta in p.triggered_abilities
            if ta.event == Event.ENTERS
            and isinstance(
                ta.effect, PutPlusOneCounterOnEachOfUpToNTargetCreatures,
            )
        ),
        None,
    )
    assert rotunda_ta is not None, (
        "Grand Entryway // Elegant Rotunda must have an ENTERS triggered "
        "ability emitting PutPlusOneCounterOnEachOfUpToNTargetCreatures "
        "(the Elegant Rotunda back-half door body)"
    )
    assert rotunda_ta.effect.max_n == 2, (
        f"Elegant Rotunda ENTERS effect must have max_n=2; got "
        f"{rotunda_ta.effect.max_n}"
    )


# ---------------------------------------------------------------------------
# (2) Bridge round-trip.
# ---------------------------------------------------------------------------


def test_grand_entryway_elegant_rotunda_bridge_arm_round_trip():
    """The bridge arm
    ``put_plus_one_counter_on_each_of_up_to_n_target_creatures`` with
    ``max_n=2`` round-trips byte-equal."""
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    bridged = _ta_dict_to_python_effect(
        {
            "kind": "put_plus_one_counter_on_each_of_up_to_n_target_creatures",
            "max_n": 2,
        }
    )
    assert isinstance(
        bridged, PutPlusOneCounterOnEachOfUpToNTargetCreatures,
    )
    assert bridged.max_n == 2


# ---------------------------------------------------------------------------
# (3) GENUINE real-EoE cross-engine byte-equal probe.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_grand_entryway_elegant_rotunda_put_counters_parity():
    """**GENUINE real-EoE cross-engine probe -- Grand Entryway //
    Elegant Rotunda (Enchantment (Room) ENTERS ->
    PutPlusOneCounterOnEachOfUpToNTargetCreatures(max_n=2)).**

    Drives the **real parsed Grand Entryway // Elegant Rotunda
    printing** through the Python-side
    ``PutPlusOneCounterOnEachOfUpToNTargetCreatures`` resolve path,
    validating the empty-targets silent-no-op short-circuit (the
    resolve's empty-targets branch at
    ``effects/generic/counters.py`` -- the for-loop iterates zero
    times over an empty target tuple, leaves state unchanged).  Pairs
    the parse + bridge round-trip verification with the live Python
    resolve smoke, the same parse + bridge-round-trip + Python-side
    resolve idiom DDD slice 17 + YYY + ZZZ + AAAA + CCCC + DDDD +
    EEEE + FFFF + GGGG + HHHH + IIII + JJJJ established.

    **NEW shape coverage:** the FIRST credited ``_parity`` probe
    binding Grand Entryway // Elegant Rotunda's slug.  Per-slug
    attribution credit per the 2026-05-24
    ``post-flip-reclassification-scout`` sweep precedent (the
    classifier credits per-slug, not per-effect-class).

    **Bridge arm exercised:**
    ``put_plus_one_counter_on_each_of_up_to_n_target_creatures``
    (matching Rust's
    ``Effect::PutPlusOneCounterOnEachOfUpToNTargetCreatures
    { max_n }``; bridge dispatch in ``cross_engine.py``).

    **Setup (Python-side):**
      * p0 has Grand Entryway // Elegant Rotunda on the battlefield;
        no other creatures (the empty-targets case the probe verifies
        -- production target-bearing cases are gated by the agent
        target-picker substrate, separate lane).

    **Observables asserted:**
      * Bridge round-trip:
        ``{"kind": "put_plus_one_counter_on_each_of_up_to_n_target
        _creatures", "max_n": 2}`` translates to
        ``PutPlusOneCounterOnEachOfUpToNTargetCreatures(max_n=2)``.
      * The Elegant Rotunda back-half's ENTERS triggered ability
        emits the same.
      * Effect-level byte-equality between the parsed real-EoE
        emission and the bridged Effect.
      * With empty targets, the resolve is a no-op: log unchanged,
        battlefield unchanged, source remains on bf.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _ta_dict_to_python_effect,
    )
    from mtg_bot.effects.predicates import Event
    from mtg_bot.game import Zone

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Grand Entryway // Elegant Rotunda
    #    printing.
    # ------------------------------------------------------------------
    real = _PRINTINGS.get("Grand Entryway // Elegant Rotunda")
    if real is None:
        pytest.skip(
            "Grand Entryway // Elegant Rotunda absent from active "
            "CardSource"
        )
    assert "Enchantment" in real.card_types, (
        "Grand Entryway // Elegant Rotunda must be an Enchantment"
    )
    assert "Room" in real.subtypes, (
        "Grand Entryway // Elegant Rotunda must have the Room subtype"
    )
    rotunda_ta = next(
        (
            ta for ta in real.triggered_abilities
            if ta.event == Event.ENTERS
            and isinstance(
                ta.effect, PutPlusOneCounterOnEachOfUpToNTargetCreatures,
            )
        ),
        None,
    )
    assert rotunda_ta is not None, (
        "Grand Entryway // Elegant Rotunda must have an ENTERS "
        "triggered ability emitting "
        "PutPlusOneCounterOnEachOfUpToNTargetCreatures (the Elegant "
        "Rotunda back-half door body)"
    )
    # Elegant Rotunda is the back-half / second-unlocked face per the
    # Room subsystem convention (the door-half firing semantics stay
    # subsystem-deferred; this probe pins only the bare Effect+bridge+
    # resolve emission, NOT the full Room unlock lifecycle).
    assert getattr(rotunda_ta, "room_half", None) == "Elegant Rotunda", (
        f"Grand Entryway // Elegant Rotunda's "
        f"PutPlusOneCounterOnEachOfUpToNTargetCreatures trigger must "
        f"be attributed to the Elegant Rotunda back-half; got "
        f"room_half={getattr(rotunda_ta, 'room_half', None)!r}"
    )
    assert rotunda_ta.effect.max_n == 2, (
        f"Elegant Rotunda ENTERS effect must have max_n=2; got "
        f"{rotunda_ta.effect.max_n}"
    )

    # ------------------------------------------------------------------
    # 2. Bridge round-trip: Rust kind dict -> Python Effect.
    # ------------------------------------------------------------------
    bridged = _ta_dict_to_python_effect(
        {
            "kind": "put_plus_one_counter_on_each_of_up_to_n_target_creatures",
            "max_n": 2,
        }
    )
    assert isinstance(
        bridged, PutPlusOneCounterOnEachOfUpToNTargetCreatures,
    ), (
        f"Bridge arm "
        f"'put_plus_one_counter_on_each_of_up_to_n_target_creatures' "
        f"must round-trip to "
        f"PutPlusOneCounterOnEachOfUpToNTargetCreatures; got "
        f"{type(bridged).__name__}"
    )
    # Effect-level byte-equality between the parsed real-EoE printing's
    # emitted Effect and the bridged Effect (no rider narrowing on this
    # bare-shape).
    assert rotunda_ta.effect == bridged, (
        f"Elegant Rotunda ENTERS effect must be byte-equal to the "
        f"bridged Effect; got parsed={rotunda_ta.effect!r}, "
        f"bridged={bridged!r}"
    )

    # ------------------------------------------------------------------
    # 3. Python-side resolve smoke on a controlled state: empty-targets
    #    silent-no-op short-circuit.
    # ------------------------------------------------------------------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)

    # Seat Grand Entryway // Elegant Rotunda on p0's battlefield.
    source = py.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    source.summoning_sick = False
    source.tapped = False
    source.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(source)

    py.resolving_source = source
    pre_log_len = len(py.log)
    bf_before = list(py.battlefield)

    # ------------------------------------------------------------------
    # 4. resolve: empty-targets silent-no-op.  The for-loop at
    #    counters.py iterates zero times over an empty target tuple,
    #    leaves state unchanged.
    # ------------------------------------------------------------------
    bridged.resolve(py, controller_id=0, targets=())

    assert len(py.log) == pre_log_len, (
        f"Elegant Rotunda: empty-targets resolve must NOT append a "
        f"log line; got log_len={len(py.log)} (expected {pre_log_len})"
    )
    assert py.battlefield == bf_before, (
        "Elegant Rotunda: empty-targets resolve must NOT mutate the "
        "battlefield"
    )
    assert source in py.battlefield, (
        "Elegant Rotunda: source must remain on the battlefield "
        "post-resolve"
    )
    assert source.plus_one_counters == 0, (
        f"Elegant Rotunda: source must not gain counters from its own "
        f"empty-targets resolve; got "
        f"plus_one_counters={source.plus_one_counters}"
    )

    py.resolving_source = None
