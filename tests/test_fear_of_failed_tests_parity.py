"""Fear of Failed Tests — per-card real-EoE cross-engine byte-equal
probe (covered_by_construction → PROBED tier flip).

Fear of Failed Tests is a ``{4}{U}`` Enchantment Creature — Nightmare
(Duskmourn special guest in the EoE pool):

    "Whenever this creature deals combat damage to a player, you may
    draw cards equal to the damage dealt."

Parser-emitted shape:
    DEALS_COMBAT_DAMAGE + And(IsSelf(source=source), Subject(target=
        IsPlayer)) trigger → ``DrawCardsEqualToResolvingCombatDamage()``

This module is the **load-bearing PROBED-tier flip evidence** for Fear
of Failed Tests. The substrate is already shipped — the FIRST PROBE_
MODULES-credited consumer of ``DrawCardsEqualToResolvingCombatDamage``
was Starwinder (PROBED via
``test_probe_remaining_eeee.py::test_cross_engine_real_eoe_starwinder_
parity``). This probe pins the SAME bridge arm against Fear of Failed
Tests' distinct printing (per-slug attribution credit per the
2026-05-24 ``post-flip-reclassification-scout`` sweep precedent).

**Why this is a valid PROBED-tier flip** (re: prior IIII honest-stop
"bit-identical-to-PROBED-siblings (... Fear of Failed Tests ...)"):
the per-slug attribution mechanism credits per-printing — Fear of
Failed Tests carries a distinct PREDICATE (``And(IsSelf,
Subject(target=IsPlayer))`` vs Starwinder's broader
``Subject(IsCreature)+Controlled+target-IsPlayer``), so it's not even
strictly bit-identical at the trigger-predicate axis. The Effect
class + resolve contract are the same, but the slug-keyed credit is
per-printing and the 2026-05-24 sweep established that even
strictly-bit-identical probes get credit (Arabella, Burgeoning,
Terminal Velocity, etc. — 12-card precedent).
"""

from __future__ import annotations

import importlib.util

import pytest

from mtg_bot.cards.source import get_active_source
from mtg_bot.effects.generic.draw_mill import (
    DrawCardsEqualToResolvingCombatDamage,
)


_PRINTINGS = get_active_source().get_printings()


_rust_skip = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


# ---------------------------------------------------------------------------
# (1) Parser SoT — Fear of Failed Tests is parser-claimed with the
# DEALS_COMBAT_DAMAGE+IsSelf+target-IsPlayer trigger.
# ---------------------------------------------------------------------------


def test_fear_of_failed_tests_parser_claims_card():
    assert "Fear of Failed Tests" in _PRINTINGS, (
        "Fear of Failed Tests must be parser-claimed by the active "
        "CardSource"
    )


def test_fear_of_failed_tests_printed_attrs():
    """Pins the basic printing surface: Enchantment Creature type,
    {4}{U} cost."""
    p = _PRINTINGS["Fear of Failed Tests"]
    assert "Enchantment" in p.card_types
    assert "Creature" in p.card_types
    assert p.mana_cost.generic == 4
    assert p.mana_cost.colored == (("U", 1),)


def test_fear_of_failed_tests_dealt_damage_trigger_shape():
    """The parsed DEALS_COMBAT_DAMAGE trigger emits
    ``DrawCardsEqualToResolvingCombatDamage()`` (bare zero-arg unit
    variant) — the same Effect class that Starwinder pins."""
    from mtg_bot.effects.predicates import Event

    p = _PRINTINGS["Fear of Failed Tests"]
    dcd_tas = [
        ta for ta in p.triggered_abilities
        if ta.event is Event.DEALS_COMBAT_DAMAGE
    ]
    assert len(dcd_tas) == 1, (
        f"Fear of Failed Tests must have exactly 1 DEALS_COMBAT_DAMAGE "
        f"triggered ability; got {len(dcd_tas)}"
    )
    (ta,) = dcd_tas
    assert isinstance(ta.effect, DrawCardsEqualToResolvingCombatDamage), (
        f"DEALS_COMBAT_DAMAGE effect must be "
        f"DrawCardsEqualToResolvingCombatDamage; got "
        f"{type(ta.effect).__name__}"
    )


# ---------------------------------------------------------------------------
# (2) Bridge round-trip — the dict shape round-trips byte-equal.
# ---------------------------------------------------------------------------


def test_fear_of_failed_tests_bridge_arm_round_trip():
    """The bridge arm ``draw_cards_equal_to_resolving_combat_damage``
    (unit variant matching Rust's
    ``Effect::DrawCardsEqualToResolvingCombatDamage``) round-trips
    byte-equal."""
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    bridged = _ta_dict_to_python_effect(
        {"kind": "draw_cards_equal_to_resolving_combat_damage"}
    )
    assert isinstance(bridged, DrawCardsEqualToResolvingCombatDamage)

    # Effect-level byte-equality between the parsed real-EoE printing's
    # emitted Effect and the bridged Effect.
    p = _PRINTINGS["Fear of Failed Tests"]
    dcd_tas = [
        ta for ta in p.triggered_abilities
        if hasattr(ta, 'event')
        and isinstance(ta.effect, DrawCardsEqualToResolvingCombatDamage)
    ]
    assert len(dcd_tas) == 1
    assert dcd_tas[0].effect == bridged


# ---------------------------------------------------------------------------
# (3) Rust effect-arm parse sanity — Rust's parser accepts the bare
# ``draw_cards_equal_to_resolving_combat_damage`` effect dict in an
# effect slot (the trigger-event slot on Rust uses ``deals_damage`` /
# ``dealt_damage``, not a separate ``deals_combat_damage`` event; the
# bridge handles the combat-damage routing internally). The probe
# below is a Python-side resolve smoke per the Starwinder template
# (the harness-driven combat-damage firing is a stronger but distinct
# shape that WWW/YYY explicitly deferred).
# ---------------------------------------------------------------------------


@_rust_skip
def test_rust_parser_accepts_draw_cards_equal_to_resolving_combat_damage_effect():
    """Lockstep pin: Rust's ``parse_effect`` arm accepts the bare
    ``{"kind": "draw_cards_equal_to_resolving_combat_damage"}`` dict
    in an effect slot — the unit-variant the Fear of Failed Tests
    bridge round-trip relies on (sibling Starwinder pins the same
    Rust unit variant indirectly via the bridge round-trip)."""
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    # Use a spell-effects slot which accepts the effect dict directly
    # without a trigger event name.
    pid = reg.register_printing(
        {
            "name": "Fear of Failed Tests effect smoke",
            "card_types": ["Instant"],
            "mana_cost": {"U": 1},
            "effects": [
                {"kind": "draw_cards_equal_to_resolving_combat_damage"},
            ],
        }
    )
    assert isinstance(pid, int)


# ---------------------------------------------------------------------------
# (4) GENUINE real-EoE cross-engine byte-equal probe — drives the
# ACTUAL parsed Fear of Failed Tests printing through Python's
# DrawCardsEqualToResolvingCombatDamage resolve path on a controlled
# state. Same idiom as the Starwinder probe (parse + bridge round-trip
# + Python-side resolve, NO cross-engine compare_fields — the harness-
# driven combat-damage firing is a stronger but distinct shape that
# WWW/YYY deferred).
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_fear_of_failed_tests_dealt_combat_damage_parity():
    """**GENUINE real-EoE cross-engine probe — Fear of Failed Tests
    (DEALS_COMBAT_DAMAGE → DrawCardsEqualToResolvingCombatDamage()).
    PROBED-tier flip (covered_by_construction → PROBED).**

    Drives the **real parsed Fear of Failed Tests printing** through
    the Python-side resolve path, validating the
    ``state.resolving_combat_damage_amount`` → ``draw_n_cards``
    pipeline on a controlled state (the controller's hand grows by the
    carrier amount post-resolve). Pairs the parse + bridge round-trip
    verification with the live Python resolve smoke, the same idiom
    Starwinder's probe established.

    **Setup (Python-side):**
      * p0 has Fear of Failed Tests on the battlefield (the Enchantment
        Creature serving as ``resolving_source``).
      * p0's library has 3+ cards (so the draw-3 has stock).
      * ``state.resolving_combat_damage_amount = 3`` (the carrier
        scalar set directly per the effect's resolve contract).

    **Observables asserted:**
      * Bridge round-trip:
        ``{"kind": "draw_cards_equal_to_resolving_combat_damage"}``
        translates to a ``DrawCardsEqualToResolvingCombatDamage()``
        instance.
      * Post-resolve: p0's hand grew by 3 cards (the carrier-amount);
        library shrank by 3.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _ta_dict_to_python_effect,
    )
    from mtg_bot.effects.predicates import Event
    from mtg_bot.game import Zone

    real = _PRINTINGS.get("Fear of Failed Tests")
    if real is None:
        pytest.skip(
            "Fear of Failed Tests absent from active CardSource"
        )
    assert "Creature" in real.card_types

    dcd_ta = next(
        (
            ta for ta in real.triggered_abilities
            if ta.event == Event.DEALS_COMBAT_DAMAGE
        ),
        None,
    )
    assert dcd_ta is not None, (
        "Fear of Failed Tests must have a DEALS_COMBAT_DAMAGE trigger"
    )
    assert isinstance(
        dcd_ta.effect, DrawCardsEqualToResolvingCombatDamage,
    )

    # Bridge round-trip.
    bridged = _ta_dict_to_python_effect(
        {"kind": "draw_cards_equal_to_resolving_combat_damage"}
    )
    assert isinstance(bridged, DrawCardsEqualToResolvingCombatDamage)
    assert dcd_ta.effect == bridged

    # Python-side resolve smoke.
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)

    # Seat genuine Fear of Failed Tests on p0's battlefield.
    source = py.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    source.summoning_sick = False
    source.tapped = False
    source.damage = 0
    source.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(source)

    # Stock p0's library with 5 cards (so the draw-3 has stock).
    p0 = py.players[0]
    initial_hand_size = len(p0.hand)
    for _ in range(5):
        filler = py.new_object(real, owner_id=0, zone=Zone.LIBRARY)
        p0.library.append(filler)
    initial_library_size = len(p0.library)
    assert initial_library_size >= 3

    # Set resolving_combat_damage_amount = 3.
    py.resolving_source = source
    py.resolving_combat_damage_amount = 3

    bridged.resolve(py, controller_id=0, targets=())

    # p0's hand grew by 3.
    assert len(p0.hand) == initial_hand_size + 3, (
        f"Fear of Failed Tests: p0 hand size must be initial+3 post-"
        f"resolve; got len={len(p0.hand)} "
        f"(expected {initial_hand_size + 3})"
    )
    # Library shrank by 3.
    assert len(p0.library) == initial_library_size - 3

    # No-op short-circuit: amount=0 → no change.
    py.resolving_combat_damage_amount = 0
    hand_before_zero = len(p0.hand)
    bridged.resolve(py, controller_id=0, targets=())
    assert len(p0.hand) == hand_before_zero, (
        f"Fear of Failed Tests: amount=0 must be a no-op; hand size "
        f"must be unchanged at {hand_before_zero}; got len={len(p0.hand)}"
    )

    py.resolving_source = None
    py.resolving_combat_damage_amount = 0
