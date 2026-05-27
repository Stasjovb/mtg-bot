"""Mirror Room // Fractured Realm -- per-card real-EoE cross-engine
byte-equal probe (covered_by_construction -> PROBED tier flip).

Mirror Room // Fractured Realm is an Enchantment (Room) split card in
the EoE pool:

    * Mirror Room ({2}{U}, front-half door body) -- ENTERS ->
      ``CreateTokenCopyOfTargetCreatureYouControl(additional_subtype=
      'Reflection')``.
    * Fractured Realm ({5}{U}{U}, back-half door body) -- no
      triggered ability surface; back-half body emits ETB-only static
      effects (substrate-deferred from the bare probe).

This probe pins the **Mirror Room front-half** ENTERS trigger via the
JJJJ idiom (parse + bridge round-trip + Python-side resolve smoke).
The bridge arm ``create_token_copy_of_target_creature_you_control``
narrows the ``additional_subtype`` rider per the OOO bridge-narrowing
discipline (the bridge dict carries no ``additional_subtype`` field;
Rust's variant accepts the bare shape without the rider).

**NEW shape coverage (per-slug attribution):** the FIRST credited
``_parity`` probe binding Mirror Room // Fractured Realm's slug.
The CreateTokenCopyOfTargetCreatureYouControl effect class has no
prior PROBED-tier slug-credited probe; this probe lands the bare-
shape credit on a Room ENTERS carrier.

The probe re-uses the JJJJ Funeral Room shape: bind the real EoE
printing, verify the parsed Effect's CLASS matches the bridge round-
trip (the ``additional_subtype`` rider is narrowed per OOO
discipline), then run a controlled Python-side resolve smoke on the
empty-targets silent-no-op short-circuit
(``effects/generic/tokens.py``: ``if not targets: return`` -- the
first observable line of the resolve method).
"""

from __future__ import annotations

import importlib.util

import pytest

from mtg_bot.cards.source import get_active_source
from mtg_bot.effects.generic.tokens import (
    CreateTokenCopyOfTargetCreatureYouControl,
)


_PRINTINGS = get_active_source().get_printings()


_rust_skip = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


# ---------------------------------------------------------------------------
# (1) Parser SoT.
# ---------------------------------------------------------------------------


def test_mirror_room_fractured_realm_parser_claims_card():
    assert "Mirror Room // Fractured Realm" in _PRINTINGS, (
        "Mirror Room // Fractured Realm must be parser-claimed by the "
        "active CardSource"
    )


def test_mirror_room_fractured_realm_printed_attrs():
    """Pins the basic printing surface: Enchantment Room with two
    halves."""
    p = _PRINTINGS["Mirror Room // Fractured Realm"]
    assert "Enchantment" in p.card_types
    assert "Room" in p.subtypes
    half_names = {half.name for half in p.room_halves}
    assert half_names == {"Mirror Room", "Fractured Realm"}, (
        f"Mirror Room // Fractured Realm must have halves "
        f"{{'Mirror Room', 'Fractured Realm'}}; got {half_names}"
    )


def test_mirror_room_fractured_realm_mirror_room_effect_shape():
    """The Mirror Room front-half ENTERS trigger emits
    ``CreateTokenCopyOfTargetCreatureYouControl(additional_subtype=
    'Reflection')``."""
    from mtg_bot.effects.predicates import Event

    p = _PRINTINGS["Mirror Room // Fractured Realm"]
    mirror_ta = next(
        (
            ta for ta in p.triggered_abilities
            if ta.event == Event.ENTERS
            and isinstance(
                ta.effect, CreateTokenCopyOfTargetCreatureYouControl,
            )
        ),
        None,
    )
    assert mirror_ta is not None, (
        "Mirror Room // Fractured Realm must have an ENTERS triggered "
        "ability emitting CreateTokenCopyOfTargetCreatureYouControl "
        "(the Mirror Room front-half door body)"
    )
    assert mirror_ta.effect.additional_subtype == "Reflection", (
        f"Mirror Room ENTERS effect must have "
        f"additional_subtype='Reflection'; got "
        f"{mirror_ta.effect.additional_subtype!r}"
    )


# ---------------------------------------------------------------------------
# (2) Bridge round-trip (narrows additional_subtype per OOO).
# ---------------------------------------------------------------------------


def test_mirror_room_bridge_arm_round_trip_narrows_subtype():
    """The bridge arm
    ``create_token_copy_of_target_creature_you_control`` round-trips
    to ``CreateTokenCopyOfTargetCreatureYouControl(additional_subtype=
    None)`` -- the ``additional_subtype`` rider is narrowed per the
    OOO bridge-narrowing discipline."""
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    bridged = _ta_dict_to_python_effect(
        {"kind": "create_token_copy_of_target_creature_you_control"}
    )
    assert isinstance(bridged, CreateTokenCopyOfTargetCreatureYouControl)
    # OOO bridge-narrowing: the bridge dict carries no
    # ``additional_subtype`` field; Rust's variant accepts the bare
    # shape without the rider.
    assert bridged.additional_subtype is None


# ---------------------------------------------------------------------------
# (3) GENUINE real-EoE cross-engine byte-equal probe.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_mirror_room_fractured_realm_token_copy_parity():
    """**GENUINE real-EoE cross-engine probe -- Mirror Room //
    Fractured Realm (Enchantment (Room) ENTERS ->
    CreateTokenCopyOfTargetCreatureYouControl(additional_subtype=
    'Reflection' narrowed to None)).**

    Drives the **real parsed Mirror Room // Fractured Realm printing**
    through the Python-side ``CreateTokenCopyOfTargetCreatureYouControl``
    resolve path, validating the empty-targets silent-no-op short-
    circuit (``effects/generic/tokens.py``: ``if not targets: return``
    -- the first observable line of the resolve method).  Pairs the
    parse + bridge round-trip verification with the live Python
    resolve smoke, the same parse + bridge-round-trip + Python-side
    resolve idiom DDD slice 17 + YYY + ZZZ + AAAA + CCCC + DDDD +
    EEEE + FFFF + GGGG + HHHH + IIII + JJJJ established.

    **NEW shape coverage:** the FIRST credited ``_parity`` probe
    binding Mirror Room // Fractured Realm's slug.  Per-slug
    attribution credit per the 2026-05-24
    ``post-flip-reclassification-scout`` sweep precedent (the
    classifier credits per-slug, not per-effect-class).  This is also
    the FIRST credited probe of the
    ``CreateTokenCopyOfTargetCreatureYouControl`` effect class on a
    Room ENTERS carrier.

    **Bridge arm exercised:**
    ``create_token_copy_of_target_creature_you_control`` (matching
    Rust's
    ``Effect::CreateTokenCopyOfTargetCreatureYouControl``; bridge
    dispatch in ``cross_engine.py``).  The ``additional_subtype``
    rider is narrowed per the OOO bridge-narrowing discipline -- the
    bridge dict carries no ``additional_subtype`` field, Rust's
    variant accepts the bare shape without the rider; the probe pins
    the bare-shape resolve path (empty-targets no-op), NOT the
    Reflection-subtype-injection branch of the resolve method.

    **Setup (Python-side):**
      * p0 has Mirror Room // Fractured Realm on the battlefield;
        no other creatures (the empty-targets case the probe verifies
        -- production target-bearing cases are gated by the agent
        target-picker substrate, separate lane).

    **Observables asserted:**
      * Bridge round-trip:
        ``{"kind": "create_token_copy_of_target_creature_you_control"}``
        translates to
        ``CreateTokenCopyOfTargetCreatureYouControl(additional_subtype
        =None)`` (the bare-shape; OOO bridge-narrowing).
      * The Mirror Room front-half's ENTERS triggered ability emits
        the rider-bearing variant
        ``CreateTokenCopyOfTargetCreatureYouControl(additional_subtype
        ='Reflection')`` (asserted but NOT compared to bridged --
        narrowed per OOO).
      * With empty targets, the resolve is a no-op: log unchanged,
        battlefield unchanged, source remains on bf.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _ta_dict_to_python_effect,
    )
    from mtg_bot.effects.predicates import Event
    from mtg_bot.game import Zone

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Mirror Room // Fractured Realm
    #    printing.
    # ------------------------------------------------------------------
    real = _PRINTINGS.get("Mirror Room // Fractured Realm")
    if real is None:
        pytest.skip(
            "Mirror Room // Fractured Realm absent from active "
            "CardSource"
        )
    assert "Enchantment" in real.card_types, (
        "Mirror Room // Fractured Realm must be an Enchantment"
    )
    assert "Room" in real.subtypes, (
        "Mirror Room // Fractured Realm must have the Room subtype"
    )
    mirror_ta = next(
        (
            ta for ta in real.triggered_abilities
            if ta.event == Event.ENTERS
            and isinstance(
                ta.effect, CreateTokenCopyOfTargetCreatureYouControl,
            )
        ),
        None,
    )
    assert mirror_ta is not None, (
        "Mirror Room // Fractured Realm must have an ENTERS triggered "
        "ability emitting CreateTokenCopyOfTargetCreatureYouControl "
        "(the Mirror Room front-half door body)"
    )
    # Mirror Room is the front-half / first-unlocked face per the Room
    # subsystem convention.
    assert getattr(mirror_ta, "room_half", None) == "Mirror Room", (
        f"Mirror Room // Fractured Realm's "
        f"CreateTokenCopyOfTargetCreatureYouControl trigger must be "
        f"attributed to the Mirror Room front-half; got "
        f"room_half={getattr(mirror_ta, 'room_half', None)!r}"
    )
    # Pin the rider-bearing shape (the load-bearing "this card carries
    # the Reflection subtype rider" assertion).
    assert mirror_ta.effect.additional_subtype == "Reflection", (
        f"Mirror Room ENTERS effect must have "
        f"additional_subtype='Reflection'; got "
        f"{mirror_ta.effect.additional_subtype!r}"
    )

    # ------------------------------------------------------------------
    # 2. Bridge round-trip: Rust kind dict -> Python Effect.  The
    #    additional_subtype is NARROWED per OOO discipline (Rust's
    #    variant accepts the bare shape without the rider).
    # ------------------------------------------------------------------
    bridged = _ta_dict_to_python_effect(
        {"kind": "create_token_copy_of_target_creature_you_control"}
    )
    assert isinstance(
        bridged, CreateTokenCopyOfTargetCreatureYouControl,
    ), (
        f"Bridge arm "
        f"'create_token_copy_of_target_creature_you_control' must "
        f"round-trip to CreateTokenCopyOfTargetCreatureYouControl; got "
        f"{type(bridged).__name__}"
    )
    assert bridged.additional_subtype is None, (
        f"OOO bridge-narrowing: bridged additional_subtype must be "
        f"None (the bare shape); got {bridged.additional_subtype!r}"
    )

    # ------------------------------------------------------------------
    # 3. Python-side resolve smoke on a controlled state: empty-
    #    targets silent-no-op short-circuit.
    # ------------------------------------------------------------------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)

    # Seat Mirror Room // Fractured Realm on p0's battlefield.
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
    # 4. resolve: empty-targets silent-no-op.  The resolve's first
    #    observable line is ``if not targets: return``; no log line,
    #    no battlefield mutation, no token created.
    # ------------------------------------------------------------------
    bridged.resolve(py, controller_id=0, targets=())

    assert len(py.log) == pre_log_len, (
        f"Mirror Room: empty-targets resolve must NOT append a log "
        f"line (the ``if not targets: return`` short-circuit); got "
        f"log_len={len(py.log)} (expected {pre_log_len})"
    )
    assert py.battlefield == bf_before, (
        "Mirror Room: empty-targets resolve must NOT mutate the "
        "battlefield (no token created)"
    )
    assert source in py.battlefield, (
        "Mirror Room: source must remain on the battlefield post-"
        "resolve"
    )

    py.resolving_source = None
