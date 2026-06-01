"""Tezzeret, Cruel Captain — per-card real-EoE cross-engine byte-equal
probe (blocked_subsystem_gated → PROBED tier flip).

Tezzeret, Cruel Captain is a ``{3}`` Legendary Planeswalker — Tezzeret
(starting loyalty 4) in the EoE pool. Printed oracle text:

    "Whenever an artifact you control enters, put a loyalty counter on
    Tezzeret."
    "0: Untap target artifact or creature. If it's an artifact
    creature, put a +1/+1 counter on it."
    "−3: Search your library for an artifact card with mana value 1 or
    less, reveal it, put it into your hand, then shuffle."
    "−7: You get an emblem with '...'."

**Scope of this probe (the loyalty-GAIN trigger substrate).** This
module is the load-bearing PROBED-tier flip evidence for Tezzeret,
Cruel Captain — the LAST non-Duskmourn BLOCKED card in the campaign
(non-DSK 314/315 → 315/315 = 100%). It probes the substrate BOTH
engines model end-to-end:

  * the ``is_planeswalker`` / ``loyalty=4`` printing surface,
  * the loyalty-GAIN triggered ability
    (``PutLoyaltyCounterOnSelf(amount=1)``) — both engines now carry
    the matching Effect (Rust ``Effect::PutLoyaltyCounterOnSelf`` +
    parser ``put_loyalty_counter_on_self`` arm + bridge reverse arm;
    Python ``PutLoyaltyCounterOnSelf``), with the ``loyalty_counters``
    GameObject slot snapshot-surfaced + the walker-at-0 SBA on both
    sides.

The probe drives the loyalty-gain effect through BOTH engines'
resolve paths and asserts byte-equal post-resolve loyalty (4 → 5),
plus parser SoT + bridge round-trip byte-equality of the parsed
real-EoE printing's emitted Effect.

**What stays deferred (HONEST-STOP, documented in
docs/SEARCH_LIMITATIONS.md).** The three loyalty-ACTIVATED abilities
(0 / −3 / −7) and the −7 EMBLEM are NOT probed by this module:

  * The PYTHON parser deliberately STRIPS loyalty-activation lines
    (``planeswalker_builder.py`` ``_LOYALTY_ACTIVATION_PREFIX``) —
    Python does not yet model loyalty-ability activation (no
    pay/add-loyalty cost atom, no sorcery-speed once-per-turn-per-
    walker activation gate, no emblem object). RUST already carries
    the full loyalty-COST activation substrate
    (``ActivationCost.loyalty`` signed cost + emission gate +
    ``loyalty_activated_this_turn`` once-per-turn-per-walker ledger +
    SBA), but the asymmetry means a cross-engine activation probe is
    not byte-equal-buildable on the Python side today.
  * The −7 emblem has no emblem-object substrate on either engine.

This is the planeswalker-loyalty-GAIN slice: the loyalty-counter
field + the loyalty-gain trigger + starting-loyalty/SBA are byte-equal
across engines; the loyalty-ABILITY activation + emblem remain
Python-substrate work (see docs/SEARCH_LIMITATIONS.md). A characterized
partial that ships the planeswalker-loyalty-gain substrate is the WIN
per the campaign's honest-stop policy.

The predicate-gated artifact-ETB FIRING path (the real trigger fires
on "an artifact you control enters", a separate trajectory surface) is
deferred per the synthetic-only-when-event-firing-cascades precedent
(Sunstar Lightsmith's IS_CAST firing parallel) — this probe drives the
effect's resolve directly on both engines, the same EEEE-idiom (parse
+ bridge round-trip + per-engine resolve, no full-trajectory event
firing) that PROBED Sunstar Lightsmith / Illvoi Operative.
"""

from __future__ import annotations

import importlib.util

import pytest

from mtg_bot.cards.source import get_active_source
from mtg_bot.effects.generic.counters import PutLoyaltyCounterOnSelf
from mtg_bot.effects.predicates import Event


_PRINTINGS = get_active_source().get_printings()

_rust_skip = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)

# Zone constants (mirror Rust's u8 zone IDs).
ZONE_BATTLEFIELD = 2


# ---------------------------------------------------------------------------
# (1) Parser SoT — Tezzeret is parser-claimed and emits the
# Planeswalker(loyalty=4) + ENTERS/PutLoyaltyCounterOnSelf shape.
# ---------------------------------------------------------------------------


def test_tezzeret_parser_claims_card():
    assert "Tezzeret, Cruel Captain" in _PRINTINGS, (
        "Tezzeret, Cruel Captain must be parser-claimed by the active "
        "CardSource"
    )


def test_tezzeret_printed_planeswalker_surface():
    """Pins the basic printing surface: Legendary Planeswalker —
    Tezzeret, {3} cost, loyalty 4, no P/T."""
    p = _PRINTINGS["Tezzeret, Cruel Captain"]
    assert p.is_planeswalker is True
    assert "Planeswalker" in p.card_types
    assert p.is_legendary is True
    assert "Tezzeret" in p.subtypes
    assert p.loyalty == 4
    assert p.mana_cost.generic == 3
    assert p.mana_cost.colored == ()
    assert p.power is None
    assert p.toughness is None


def test_tezzeret_loyalty_gain_trigger_shape():
    """The parsed printing emits exactly one ENTERS triggered ability
    whose effect is ``PutLoyaltyCounterOnSelf(amount=1)`` — the
    loyalty-gain "whenever an artifact you control enters" rider. The
    three loyalty-ACTIVATED abilities (0 / −3 / −7) are deliberately
    stripped by ``planeswalker_builder.py`` (Python does not model
    loyalty-ability activation), so ``activated_abilities`` is empty."""
    p = _PRINTINGS["Tezzeret, Cruel Captain"]
    enters_tas = [
        ta for ta in p.triggered_abilities if ta.event is Event.ENTERS
    ]
    assert len(enters_tas) == 1, (
        f"Tezzeret must emit exactly 1 ENTERS triggered ability; got "
        f"{len(enters_tas)}"
    )
    (ta,) = enters_tas
    assert isinstance(ta.effect, PutLoyaltyCounterOnSelf), (
        f"ENTERS effect must be PutLoyaltyCounterOnSelf; got "
        f"{type(ta.effect).__name__}"
    )
    assert ta.effect.amount == 1, (
        f"PutLoyaltyCounterOnSelf amount must be 1; got "
        f"{ta.effect.amount}"
    )
    # Loyalty-activated abilities are stripped (deferred Python
    # substrate) — the printing carries none.
    assert p.activated_abilities == (), (
        "Tezzeret's loyalty-activated abilities (0/−3/−7) must be "
        "stripped — Python does not model loyalty-ability activation"
    )


# ---------------------------------------------------------------------------
# (2) Bridge round-trip — the put_loyalty_counter_on_self dict round-
# trips byte-equal to the parsed printing's emitted Effect.
# ---------------------------------------------------------------------------


def test_tezzeret_bridge_arm_round_trip():
    """The bridge arm ``put_loyalty_counter_on_self`` translates
    ``{"kind": "put_loyalty_counter_on_self", "amount": 1}`` to the
    matching Python ``PutLoyaltyCounterOnSelf(amount=1)``, and that is
    byte-equal to the parsed real-EoE printing's emitted Effect."""
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    bridged = _ta_dict_to_python_effect(
        {"kind": "put_loyalty_counter_on_self", "amount": 1}
    )
    assert isinstance(bridged, PutLoyaltyCounterOnSelf)
    assert bridged.amount == 1

    # Default-handling: amount omitted defaults to 1 (mirrors Rust's
    # parse_effect default + Python's dataclass default).
    bridged_default = _ta_dict_to_python_effect(
        {"kind": "put_loyalty_counter_on_self"}
    )
    assert isinstance(bridged_default, PutLoyaltyCounterOnSelf)
    assert bridged_default.amount == 1

    # Negative amount raises on the bridge (mirrors Rust's contract).
    with pytest.raises(ValueError, match=r"must be non-negative"):
        _ta_dict_to_python_effect(
            {"kind": "put_loyalty_counter_on_self", "amount": -1}
        )

    # Effect-level byte-equality between the parsed real-EoE printing's
    # emitted Effect and the bridged Effect — the structural contract
    # for the PROBED tier.
    p = _PRINTINGS["Tezzeret, Cruel Captain"]
    (ta,) = [
        t for t in p.triggered_abilities if t.event is Event.ENTERS
    ]
    assert ta.effect == bridged, (
        "Tezzeret's parsed Effect must be byte-equal to the bridged "
        "Effect (PutLoyaltyCounterOnSelf structural contract)"
    )


# ---------------------------------------------------------------------------
# (3) Rust synthetic-carrier sanity — the Rust parser accepts the
# bridged loyalty-gain trigger dict on a Tezzeret-shape Planeswalker
# carrier (simpler ``source_is_self`` predicate — the real
# "artifact you control enters" predicate's firing is its own surface).
# ---------------------------------------------------------------------------


@_rust_skip
def test_rust_parser_accepts_tezzeret_synthetic_dict():
    """Lockstep pin: Rust's ``parse_effect`` arm accepts the
    ``{"kind": "put_loyalty_counter_on_self", "amount": 1}`` dict on a
    Tezzeret-shape Planeswalker carrier with a ``starting_loyalty`` 4
    seed and an ENTERS trigger."""
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Tezzeret, Cruel Captain (synthetic carrier)",
            "card_types": ["Planeswalker"],
            "supertypes": ["Legendary"],
            "subtypes": ["Tezzeret"],
            "mana_cost": {"generic": 3},
            "starting_loyalty": 4,
            "effects": [],
            "triggered_abilities": [
                {
                    "event": "enters",
                    "predicate": {"kind": "source_is_self"},
                    "effect": {
                        "kind": "put_loyalty_counter_on_self",
                        "amount": 1,
                    },
                },
            ],
        }
    )
    assert isinstance(pid, int)


# ---------------------------------------------------------------------------
# (4) GENUINE real-EoE cross-engine byte-equal probe — drives the
# loyalty-gain Effect through BOTH engines' resolve paths and asserts
# byte-equal post-resolve loyalty (4 → 5).
# ---------------------------------------------------------------------------


@_rust_skip
def test_cross_engine_real_eoe_tezzeret_cruel_captain_loyalty_gain_parity():
    """**GENUINE real-EoE cross-engine probe — Tezzeret, Cruel Captain
    loyalty-gain ENTERS → PutLoyaltyCounterOnSelf(1). PROBED-tier flip
    (blocked_subsystem_gated → PROBED).**

    Drives the loyalty-GAIN effect through BOTH engines:

      * **Python:** seats the GENUINE parsed Tezzeret printing on p0's
        battlefield with ``loyalty_counters=4`` (the printed starting
        loyalty), sets ``resolving_source`` and resolves the parsed
        ENTERS effect → asserts ``loyalty_counters == 5``.
      * **Rust:** registers a Tezzeret-shape Planeswalker carrier with
        ``starting_loyalty=4`` + the bridged
        ``put_loyalty_counter_on_self`` ENTERS trigger, baselines
        loyalty to 4 via ``set_loyalty_counters`` (matching Python's
        printed seed), resolves the auto-pushed ENTERS trigger →
        asserts ``get_loyalty_counters == 5``.

    Both engines produce the byte-equal observable: loyalty 4 → 5.

    Also pins parser SoT + bridge round-trip byte-equality (the parsed
    real-EoE Effect == the bridged Effect), so the cross-engine
    equality is anchored on the ACTUAL parsed printing, not a synthetic
    stand-in.

    **Deferred (HONEST-STOP):** the three loyalty-ACTIVATED abilities
    (0/−3/−7) + the −7 emblem are out of scope — Python does not model
    loyalty-ability activation (parser strips the lines) and no emblem
    substrate exists on either engine. The predicate-gated
    artifact-ETB firing path is deferred per the synthetic-only-when-
    event-firing-cascades precedent (Sunstar Lightsmith parallel).
    See docs/SEARCH_LIMITATIONS.md.
    """
    import mtg_bot_engine  # noqa: F401  (gated by _rust_skip)

    from mtg_bot.parity.cross_engine import (
        DeckSpec,
        build_python_state,
        build_rust_state,
        _ta_dict_to_python_effect,
    )
    from mtg_bot.game import Zone

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Tezzeret printing + its loyalty-gain
    #    ENTERS trigger.
    # ------------------------------------------------------------------
    real = _PRINTINGS.get("Tezzeret, Cruel Captain")
    if real is None:
        pytest.skip("Tezzeret, Cruel Captain absent from active CardSource")
    assert real.is_planeswalker is True
    assert real.loyalty == 4
    enters_ta = next(
        (
            ta for ta in real.triggered_abilities
            if ta.event is Event.ENTERS
        ),
        None,
    )
    assert enters_ta is not None, (
        "Tezzeret must have an ENTERS triggered ability"
    )
    assert isinstance(enters_ta.effect, PutLoyaltyCounterOnSelf)

    # ------------------------------------------------------------------
    # 2. Bridge round-trip: Rust kind dict -> Python Effect, byte-equal
    #    to the parsed real-EoE emission.
    # ------------------------------------------------------------------
    bridged = _ta_dict_to_python_effect(
        {"kind": "put_loyalty_counter_on_self", "amount": 1}
    )
    assert isinstance(bridged, PutLoyaltyCounterOnSelf)
    assert enters_ta.effect == bridged, (
        f"Tezzeret parsed Effect must be byte-equal to bridged; got "
        f"parsed={enters_ta.effect!r}, bridged={bridged!r}"
    )

    # ------------------------------------------------------------------
    # 3. PYTHON-side resolve — seat the GENUINE parsed Tezzeret on p0's
    #    bf with loyalty 4, resolve the parsed loyalty-gain effect.
    # ------------------------------------------------------------------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py_state = build_python_state(spec)

    py_walker = py_state.new_object(
        real, owner_id=0, zone=Zone.BATTLEFIELD
    )
    py_walker.loyalty_counters = 4  # printed starting loyalty
    py_walker.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_walker)

    assert py_walker.loyalty_counters == 4
    py_state.resolving_source = py_walker
    enters_ta.effect.resolve(py_state, py_walker.controller_id)
    assert py_walker.loyalty_counters == 5, (
        f"Python: Tezzeret loyalty-gain must grow loyalty 4 -> 5; got "
        f"{py_walker.loyalty_counters}"
    )

    # ------------------------------------------------------------------
    # 4. RUST-side resolve — register a Tezzeret-shape Planeswalker
    #    carrier, baseline loyalty to 4, resolve the auto-pushed ENTERS
    #    trigger.
    # ------------------------------------------------------------------
    rust_state = build_rust_state(spec)
    walker_id = rust_state.register_and_inject_object(
        {
            "name": "Tezzeret, Cruel Captain",
            "card_types": ["Planeswalker"],
            "supertypes": ["Legendary"],
            "subtypes": ["Tezzeret"],
            "mana_cost": {"generic": 3},
            "starting_loyalty": 4,
            "effects": [],
            "triggered_abilities": [
                {
                    "event": "enters",
                    "predicate": {"kind": "source_is_self"},
                    "effect": {
                        "kind": "put_loyalty_counter_on_self",
                        "amount": 1,
                    },
                },
            ],
        },
        0,
        ZONE_BATTLEFIELD,
    )
    # Baseline loyalty to the printed starting loyalty (4), matching
    # Python's seed. ``register_and_inject_object`` does NOT seed
    # ``starting_loyalty`` (the ETB-seed helper runs on the cast/resolve
    # path, not raw inject), so we stamp it explicitly.
    rust_state.set_loyalty_counters(walker_id, 4)
    assert rust_state.get_loyalty_counters(walker_id) == 4

    # Resolve the auto-pushed self-ENTERS loyalty-gain trigger.
    assert rust_state.stack_size() == 1
    rust_state.resolve_top_of_stack()
    assert rust_state.stack_size() == 0
    rust_loyalty = rust_state.get_loyalty_counters(walker_id)
    assert rust_loyalty == 5, (
        f"Rust: Tezzeret loyalty-gain must grow loyalty 4 -> 5; got "
        f"{rust_loyalty}"
    )

    # ------------------------------------------------------------------
    # 5. CROSS-ENGINE byte-equality — both engines land on loyalty 5.
    # ------------------------------------------------------------------
    assert py_walker.loyalty_counters == rust_loyalty == 5, (
        f"Cross-engine loyalty must be byte-equal (both 5); got "
        f"python={py_walker.loyalty_counters}, rust={rust_loyalty}"
    )
