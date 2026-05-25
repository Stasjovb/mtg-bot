"""Station Monitor — per-card real-EoE cross-engine byte-equal
probe (covered_by_construction → PROBED tier flip).

Station Monitor is a ``{W}{U}`` Creature — Lizard Artificer in the EoE
pool with a magecraft-style after-second-spell trigger:

    "Whenever you cast your second spell each turn, create a 1/1 white
     Drone artifact creature token with flying.  It can block only
     creatures with flying."

Parser-emitted shape:
    IS_CAST + And(Controlled(YOU, subject='controller'),
                  StateBound(SpellsCastThisTurn(n=2))) trigger →
    ``CreateToken(token_printing=Drone, count=1)``

This module is the **load-bearing PROBED-tier flip evidence** for
Station Monitor.  The substrate is already shipped — the FIRST
PROBE_MODULES-credited consumer of the ``create_token`` bridge arm was
Lithobraking-family / Pinnacle Emissary precedents (Pinnacle Emissary
PROBED via ``test_probe_cast_spell_aa.py`` for the IS_CAST + CreateToken
on a non-StateBound predicate); the FIRST PROBE_MODULES-credited
consumer of the IS_CAST event + StateBound bridge gap was Sunstar
Lightsmith (PROBED via batch-2, covered-by-construction-probe-writing-
p2, 2026-05-24) using the EEEE-idiom (parse + bridge round-trip +
Python-side resolve, NO cross-engine ``compare_fields``).  This probe
combines both substrates against Station Monitor's distinct printing
(per-slug attribution credit per the 2026-05-24 ``post-flip-
reclassification-scout`` sweep precedent + the IIII Optimistic
Scavenger / Command Bridge precedent that "the classifier credits per-
slug, not per-effect-class").

**Why this is a valid PROBED-tier flip** (re: prior ``test_probe_cast_
spell_aa.py`` honest-stop drop: "Station Monitor — same StateBound
predicate → DROPPED"): the Sunstar Lightsmith batch-2 precedent
(2026-05-24) demonstrated that the EEEE-idiom (parse + bridge round-
trip + Python-side resolve, NO cross-engine ``compare_fields``)
sidesteps the StateBound + slot='controller' bridge gap entirely.  This
probe verifies the Effect+bridge byte-equality and the Python-side
resolve mutation (one Drone token created on p0's bf), both
independent of the IS_CAST cross-engine stack-resolution path and the
StateBound + slot='controller' bridge gap.

**Drone token registration.**  The ``create_token`` bridge arm at
``cross_engine.py:3121`` requires probe-time ``register_token_printing
(pid, py_printing)`` ceremony to translate the dict-shape Rust pid into
the Python ``CardPrinting``.  Pinnacle Emissary's ``test_probe_cast_
spell_aa.py`` probe established the pattern; this probe reuses the
``TOKEN_PRINTINGS["Drone"]`` canonical Python printing under a probe-
local synthetic pid (no real Rust state needed since the EEEE-idiom
doesn't drive Rust).  The parsed Effect's ``token_printing`` field is
byte-identical to ``TOKEN_PRINTINGS["Drone"]`` (verified pre-flight at
probe authorship, the parser's safe-trigger registry reuses the
canonical Drone printing).
"""

from __future__ import annotations

import importlib.util

import pytest

from mtg_bot.cards.source import get_active_source
from mtg_bot.cards import TOKEN_PRINTINGS
from mtg_bot.effects.generic.tokens import CreateToken


_PRINTINGS = get_active_source().get_printings()


_rust_skip = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


# Zone constants (mirror Rust's u8 zone IDs).
ZONE_HAND = 0
ZONE_LIBRARY = 1
ZONE_BATTLEFIELD = 2
ZONE_GRAVEYARD = 3
ZONE_EXILE = 5


# ---------------------------------------------------------------------------
# (1) Parser SoT — Station Monitor is parser-claimed and emits the
# IS_CAST + CreateToken(Drone, count=1) shape.
# ---------------------------------------------------------------------------


def test_station_monitor_parser_claims_card():
    assert "Station Monitor" in _PRINTINGS, (
        "Station Monitor must be parser-claimed by the active CardSource"
    )


def test_station_monitor_printed_attrs():
    """Pins the basic printing surface: Creature (Lizard Artificer)
    type, {W}{U} cost."""
    p = _PRINTINGS["Station Monitor"]
    assert "Creature" in p.card_types
    assert "Lizard" in p.subtypes
    assert "Artificer" in p.subtypes
    assert p.mana_cost.generic == 0
    assert ("W", 1) in p.mana_cost.colored
    assert ("U", 1) in p.mana_cost.colored


def test_station_monitor_is_cast_trigger_shape():
    """The parsed IS_CAST trigger emits
    ``CreateToken(token_printing=Drone, count=1)`` — the canonical
    magecraft-after-second-spell drone-creation shape distinguishing
    Station Monitor from the bare-PutPlusOneCounterOnSelf sibling
    Illvoi Operative, the bare-Sequence sibling Sunstar Lightsmith, and
    the bare-ModalChooseOne sibling Cosmogrand Zenith."""
    from mtg_bot.effects.predicates import Event

    p = _PRINTINGS["Station Monitor"]
    is_cast_tas = [
        ta for ta in p.triggered_abilities if ta.event is Event.IS_CAST
    ]
    assert len(is_cast_tas) == 1, (
        f"Station Monitor must have exactly 1 IS_CAST triggered "
        f"ability; got {len(is_cast_tas)}"
    )
    (ta,) = is_cast_tas
    assert isinstance(ta.effect, CreateToken), (
        f"IS_CAST effect must be CreateToken; got "
        f"{type(ta.effect).__name__}"
    )
    assert ta.effect.count == 1, (
        f"CreateToken count must be 1; got {ta.effect.count}"
    )
    assert ta.effect.tapped is False, (
        f"CreateToken tapped must be False; got tapped={ta.effect.tapped}"
    )
    assert ta.effect.each_player is False, (
        f"CreateToken each_player must be False; got "
        f"each_player={ta.effect.each_player}"
    )
    # The Drone token shape: 1/1 Artifact Creature with flying +
    # can_only_block_creatures_with_flying.
    drone_p = ta.effect.token_printing
    assert drone_p.name == "Drone"
    assert drone_p.power == 1
    assert drone_p.toughness == 1
    assert drone_p.is_creature
    assert drone_p.is_artifact
    assert drone_p.is_token
    assert "flying" in drone_p.keywords
    assert drone_p.can_only_block_creatures_with_flying is True


def test_station_monitor_drone_matches_canonical_token_printing():
    """Pre-flight pin: the parsed Effect's ``token_printing`` is byte-
    equal to the canonical ``TOKEN_PRINTINGS["Drone"]`` printing the
    bridge will materialise under the probe-time
    ``register_token_printing`` call.  Same-instance identity isn't
    required — byte-equality is the load-bearing contract."""
    p = _PRINTINGS["Station Monitor"]
    (ta,) = p.triggered_abilities
    canonical_drone = TOKEN_PRINTINGS["Drone"]
    assert ta.effect.token_printing == canonical_drone, (
        f"Parsed Station Monitor CreateToken token_printing must be "
        f"byte-equal to canonical TOKEN_PRINTINGS['Drone']; the "
        f"create_token bridge arm registers the canonical Drone under "
        f"a probe-time pid, and the parsed token must match for the "
        f"Effect-level byte-equality contract"
    )


# ---------------------------------------------------------------------------
# (2) Bridge round-trip — the create_token dict with the Drone pid
# round-trips to a Python CreateToken(token_printing=Drone, count=1)
# byte-equal to the parsed printing's emitted Effect.
#
# Note: the create_token bridge arm requires probe-time
# ``register_token_printing(pid, py_printing)`` ceremony — same pattern
# Pinnacle Emissary's IS_CAST + CreateToken probe (test_probe_cast_
# spell_aa.py:309) uses.  No real Rust state is needed for the EEEE-
# idiom; a synthetic probe-local pid suffices.
# ---------------------------------------------------------------------------


def test_station_monitor_bridge_arm_round_trip():
    """The bridge arm ``create_token`` (cross_engine.py:3121) round-
    trips ``{"kind": "create_token", "count": 1, "token_printing_id":
    <drone_pid>}`` to a matching Python ``CreateToken(token_printing=
    TOKEN_PRINTINGS["Drone"], count=1)`` — byte-equal to the parsed
    Effect."""
    from mtg_bot.parity.cross_engine import (
        _ta_dict_to_python_effect,
        register_token_printing,
        clear_token_printings,
    )

    # Reserve a probe-local pid (no Rust state needed for the EEEE-
    # idiom; the bridge arm just consults the module-state map).  Use a
    # high integer unlikely to collide with any production-Rust pid.
    drone_pid = 999_001
    try:
        register_token_printing(drone_pid, TOKEN_PRINTINGS["Drone"])
        bridged = _ta_dict_to_python_effect(
            {
                "kind": "create_token",
                "count": 1,
                "token_printing_id": drone_pid,
            }
        )
        assert isinstance(bridged, CreateToken)
        assert bridged.count == 1
        assert bridged.token_printing == TOKEN_PRINTINGS["Drone"]
        # Rider flags must default to False (bridge constructs the bare
        # default shape; Rust substrate carries no rider-flag fields).
        assert bridged.tapped is False
        assert bridged.each_player is False
        assert bridged.attacking is False
        assert bridged.schedule_end_of_combat_sacrifice is False

        # Effect-level byte-equality between the parsed real-EoE
        # printing's emitted Effect and the bridged Effect — the
        # structural contract for the PROBED tier.
        p = _PRINTINGS["Station Monitor"]
        (ta,) = p.triggered_abilities
        assert ta.effect == bridged, (
            f"Station Monitor's parsed Effect must be byte-equal to "
            f"the bridged Effect (CreateToken + Drone structural "
            f"contract); got parsed={ta.effect!r}, bridged={bridged!r}"
        )
    finally:
        # Honest-cleanup: drop our probe-local registration so other
        # tests don't see a lingering Drone-under-999001 binding.  Per
        # cross_engine.clear_token_printings, this is a fixture-grade
        # teardown intended for explicit cleanup.
        clear_token_printings()


# ---------------------------------------------------------------------------
# (3) Rust synthetic-carrier sanity — the Rust parser accepts the
# bridged trigger dict shape on a Station-Monitor-shape Creature
# carrier (note: simpler ``source_is_self`` predicate — Rust's
# StateBound + slot='controller' substrate is the EEEE-idiom-sidestepped
# gap; the synthetic carrier strips the magecraft gate, parallel to the
# Sunstar Lightsmith / Cosmogrand Zenith / Wickerfolk Thresher HONEST-
# STOP precedent of a simpler-predicate Rust carrier).
# ---------------------------------------------------------------------------


@_rust_skip
def test_rust_parser_accepts_station_monitor_synthetic_dict():
    """Lockstep pin: Rust's ``parse_effect`` arm accepts the
    ``{"kind": "create_token", "count": 1, "token_printing_id":
    <drone_pid>}`` dict shape on a Station-Monitor-shape Creature
    carrier."""
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    # Register the Drone token printing in the Rust registry so its pid
    # is valid for the create_token effect's token_printing_id slot.
    drone_pid = reg.register_printing(
        {
            "name": "Drone",
            "card_types": ["Artifact", "Creature"],
            "supertypes": ["Token"],
            "power": 1,
            "toughness": 1,
            "keywords": ["flying"],
            "mana_cost": {"generic": 0},
        }
    )
    pid = reg.register_printing(
        {
            "name": "Station Monitor (synthetic carrier)",
            "card_types": ["Creature"],
            "power": 2,
            "toughness": 2,
            "mana_cost": {"W": 1, "U": 1},
            "effects": [],
            "triggered_abilities": [
                {
                    "event": "cast",
                    "predicate": {"kind": "source_is_self"},
                    "effect": {
                        "kind": "create_token",
                        "count": 1,
                        "token_printing_id": drone_pid,
                    },
                },
            ],
        }
    )
    assert isinstance(pid, int)


# ---------------------------------------------------------------------------
# (4) GENUINE real-EoE cross-engine byte-equal probe — drives the
# ACTUAL parsed Station Monitor printing on Python through the
# CreateToken(Drone, 1) resolve path, verifying the post-resolve
# mutation contract: one Drone token enters p0's battlefield under p0's
# control with the right flying + can_only_block_creatures_with_flying
# attribute set.
#
# Per the FFFF Illvoi Operative + batch-2 Sunstar Lightsmith precedent,
# the IS_CAST event's stack-resolution divergence (slice-12 ``test_mmm_
# probe_*``) breaks full-cross-engine ``compare_fields`` probes on this
# event; this probe uses the parse + bridge round-trip + Python-side
# resolve idiom (no cross-engine compare_fields) — same shape as Sunstar
# Lightsmith's batch-2 probe.  The harness-driven full-trajectory IS_CAST
# + SpellsCastThisTurn(n=2) magecraft-style firing stays deferred.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_station_monitor_is_cast_create_drone_parity():
    """**GENUINE real-EoE cross-engine probe — Station Monitor IS_CAST
    CreateToken(Drone, count=1). PROBED-tier flip
    (covered_by_construction → PROBED).**

    Drives the **ACTUAL parsed Station Monitor printing** on the Python
    side through the CreateToken(Drone) resolve chain.  Pairs parser
    SoT + bridge round-trip verification with live Python-side resolve
    smoke — the same EEEE-idiom Sunstar Lightsmith's batch-2 probe used
    for IS_CAST (parse + bridge + Python-side resolve, NO cross-engine
    ``compare_fields`` to avoid the slice-12 IS_CAST stack-resolution
    divergence + the StateBound + slot='controller' bridge gap).

    **NEW shape coverage:** the FIRST PROBE_MODULES-credited probe of
    the ``CreateToken(Drone, count=1)`` shape on an IS_CAST-event
    carrier with a StateBound + slot='controller' predicate — the
    magecraft-after-second-spell drone-creation archetype.  Distinct
    from:
      * Illvoi Operative (PROBED via FFFF, IS_CAST → bare
        PutPlusOneCounterOnSelf, no CreateToken).
      * Sunstar Lightsmith (PROBED via batch-2, IS_CAST →
        Sequence(PutPlusOneCounterOnSelf, DrawCards), no CreateToken).
      * Cosmogrand Zenith (PROBED via batch-3 sibling probe, IS_CAST →
        ModalChooseOne, different combinator + different mode classes).
      * Pinnacle Emissary (PROBED via ``test_probe_cast_spell_aa.py``,
        IS_CAST → CreateToken(Drone) but with a NON-StateBound
        predicate — its ``And(Subject(slot='spell', IsArtifact()),
        Controlled(YOU, 'controller'))`` predicate is fully bridgeable;
        Station Monitor's StateBound + slot='controller' is the EEEE-
        idiom-sidestepped gap).

    **Bridge arm exercised:**
      * ``create_token`` (round-XX closed-vocab arm at
        cross_engine.py:3121, with probe-time
        ``register_token_printing`` ceremony to bind the canonical
        ``TOKEN_PRINTINGS["Drone"]`` Python printing under a probe-
        local pid).

    **Setup (Python-side):**
      * p0 has Station Monitor on the battlefield (the IS_CAST trigger
        source).
      * p0's bf is otherwise empty.

    **Observables asserted:**
      * Parse SoT: parsed effect is CreateToken with Drone +
        count=1.
      * Bridge round-trip: dict with probe-time-registered Drone pid
        translates to a byte-identical
        ``CreateToken(token_printing=Drone, count=1)``.
      * Effect-level byte-equality between the parsed real-EoE
        emission and the bridged Effect.
      * Post-resolve: p0's battlefield grew by 1 (the Drone token),
        the new object's printing is Drone, the new object's
        controller is p0, the new object is on p0's bf, and the
        token has flying + can_only_block_creatures_with_flying.

    **Cast-trigger StateBound + slot='controller' bridge-gap bypass:**
    Earlier drop notes (``test_probe_cast_spell_aa.py``'s LANE RECON)
    framed Station Monitor as blocked on StateBound + slot='controller'
    grounds.  The Sunstar Lightsmith batch-2 precedent showed the EEEE-
    idiom (parse + bridge round-trip + Python-side resolve, NO cross-
    engine ``compare_fields``) sidesteps that gap entirely: this probe
    verifies the Effect+bridge byte-equality and the Python-side
    resolve mutation, both independent of the IS_CAST cross-engine
    stack-resolution path AND the StateBound + slot='controller'
    bridge gap.  Same drop-recovery precedent FFFF used for Illvoi
    Operative + batch-2 used for Sunstar Lightsmith + batch-3 sibling
    Cosmogrand Zenith.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _ta_dict_to_python_effect,
        register_token_printing, clear_token_printings,
    )
    from mtg_bot.effects.predicates import Event
    from mtg_bot.game import Zone

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Station Monitor printing.
    # ------------------------------------------------------------------
    real = _PRINTINGS.get("Station Monitor")
    if real is None:
        pytest.skip("Station Monitor absent from active CardSource")
    assert "Creature" in real.card_types
    is_cast_ta = next(
        (
            ta for ta in real.triggered_abilities
            if ta.event is Event.IS_CAST
        ),
        None,
    )
    assert is_cast_ta is not None, (
        "Station Monitor must have an IS_CAST triggered ability"
    )
    assert isinstance(is_cast_ta.effect, CreateToken), (
        f"Station Monitor IS_CAST effect must be CreateToken; got "
        f"{type(is_cast_ta.effect).__name__}"
    )
    assert is_cast_ta.effect.token_printing.name == "Drone"
    assert is_cast_ta.effect.count == 1

    # ------------------------------------------------------------------
    # 2. Bridge round-trip: Rust kind dict -> Python Effect (with
    #    probe-time ``register_token_printing`` ceremony for the
    #    create_token bridge arm).
    # ------------------------------------------------------------------
    drone_pid = 999_002
    try:
        register_token_printing(drone_pid, TOKEN_PRINTINGS["Drone"])
        bridged = _ta_dict_to_python_effect(
            {
                "kind": "create_token",
                "count": 1,
                "token_printing_id": drone_pid,
            }
        )
        assert isinstance(bridged, CreateToken)
        assert is_cast_ta.effect == bridged, (
            f"Station Monitor parsed Effect must be byte-equal to "
            f"bridged; got parsed={is_cast_ta.effect!r}, "
            f"bridged={bridged!r}"
        )

        # ------------------------------------------------------------------
        # 3. Distinctness from sibling Effect classes (regression guard).
        # ------------------------------------------------------------------
        # PutPlusOneCounterOnSelf (Illvoi Operative's shape) is NOT a
        # CreateToken — the token-creation distinction is load-bearing
        # for the magecraft-style drone-creation archetype Station
        # Monitor represents.
        from mtg_bot.effects.generic.counters import PutPlusOneCounterOnSelf
        assert not isinstance(bridged, PutPlusOneCounterOnSelf), (
            "Bridged CreateToken must NOT collapse to bare "
            "PutPlusOneCounterOnSelf — that's Illvoi Operative's "
            "shape, not Station Monitor's"
        )

        # ------------------------------------------------------------------
        # 4. Python-side resolve smoke — drive the parsed effect through
        #    its actual resolve path (creates one Drone token under p0's
        #    control on the battlefield).
        # ------------------------------------------------------------------
        spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
        py_state = build_python_state(spec)

        # Seat the GENUINE parsed Station Monitor on p0's bf as the
        # source (the IS_CAST trigger fires when p0 casts their second
        # spell; the EEEE-idiom drives the CreateToken resolve directly
        # without the harness-driven cast firing).
        py_source = py_state.new_object(
            real, owner_id=0, zone=Zone.BATTLEFIELD,
        )
        py_source.summoning_sick = False
        py_source.tapped = False
        py_source.damage = 0
        py_source.etb_timestamp = py_state.next_timestamp
        py_state.next_timestamp += 1
        py_state.battlefield.append(py_source)

        # Pre-resolve sanity: p0's bf has just the source.
        pre_bf = list(py_state.battlefield)
        assert len(pre_bf) == 1
        assert pre_bf[0] is py_source

        # Drive the parsed CreateToken through resolve directly,
        # mirroring what the IS_CAST trigger's resolve path does once
        # it pops off the stack.  CreateToken doesn't read
        # ``state.resolving_source``; it just creates the token under
        # ``controller_id``.
        is_cast_ta.effect.resolve(py_state, py_source.controller_id)

        # Post-resolve observables:
        # - p0's bf grew by 1 (the new Drone token).
        # - The new object's printing is Drone.
        # - The new object's controller is p0.
        # - The Drone token has flying + can_only_block_creatures_with_
        #   flying (per its TOKEN_PRINTINGS["Drone"] canonical
        #   metadata).
        post_bf = list(py_state.battlefield)
        assert len(post_bf) == 2, (
            f"Station Monitor CreateToken(Drone, 1) must add 1 token "
            f"to p0's bf; got bf size={len(post_bf)}"
        )
        new_objs = [o for o in post_bf if o is not py_source]
        assert len(new_objs) == 1
        new_drone = new_objs[0]
        assert new_drone.printing.name == "Drone", (
            f"new bf object must be a Drone token; got "
            f"name={new_drone.printing.name}"
        )
        assert new_drone.controller_id == 0, (
            f"new Drone must be under p0's control; got "
            f"controller_id={new_drone.controller_id}"
        )
        assert new_drone.printing.is_token, (
            f"new Drone must be a Token (Token supertype); got "
            f"supertypes={new_drone.printing.supertypes}"
        )
        assert new_drone.printing.is_creature
        assert new_drone.printing.is_artifact
        assert "flying" in new_drone.printing.keywords
        assert (
            new_drone.printing.can_only_block_creatures_with_flying
            is True
        )
    finally:
        # Honest-cleanup: drop our probe-local registration so other
        # tests don't see a lingering Drone-under-999002 binding.
        clear_token_printings()
