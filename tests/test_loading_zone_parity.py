"""Loading Zone — per-card real-EoE cross-engine byte-equal probe
(blocked_subsystem_gated → PROBED tier flip).

Loading Zone is a ``{3}{G}`` Enchantment (warp {G}) in the EoE pool
carrying ONE static ability:

    "If one or more +1/+1 counters would be put on a creature or
     Spacecraft you control, twice that many are put on it instead."

Parser-emitted shape (verified by ``test_loading_zone_static_shape``):
    ``StaticAbility(scope="self",
        replacement_effect=ReplacementEffect(
            event_pattern=EventPattern(event=WOULD_PLACE_COUNTER),
            transform=MultiplyCount(factor=2)))``

This module is the PROBED-tier flip evidence for Loading Zone and a
PROBE_MODULES-credited consumer of the Phase-5 ReplacementEffect-static
substrate. It is a SIBLING of Exalted Sunborn and Starfield Vocalist:
the SAME substrate (Rust ``StaticReplacement`` parse + bridge
``static_replacements`` field + forward emit + reverse arm) carries
this card's distinct ``(would_place_counter, multiply_count, 2)``
triple. It shares the ``MultiplyCount(2)`` transform with Exalted
Sunborn but on the ``WOULD_PLACE_COUNTER`` event.

**Established bridge + Python-resolve idiom (the Rust counter-placement
sites are honest-stopped).** Unlike Exalted Sunborn's
``would_create_token`` × ``MultiplyCount`` — which HAS a live Rust
resolve-arm consumer — the ``would_place_counter`` × ``MultiplyCount``
shape has NO single Rust resolve consumer this phase: Rust places +1/+1
counters at several scattered arms (``AddCounters`` AnyCreature,
``PutPlusOneCounterOnTargetCreature``,
``PutPlusOneCounterOnOpponentsCreature``,
``PutPlusOneCounterOnEachCreatureYouControl``, …), each with its own
``obj.counters.saturating_add`` site. Folding a per-controller doubler
into every counter-placement arm is high-blast-radius and HONEST-
STOPPED to a later slice (documented in ``docs/SEARCH_LIMITATIONS.md``).
The PROBED-tier flip rides on the established parse-SoT + bridge
round-trip + Python-side-resolve idiom (same as Cosmogrand Zenith): the
``static_replacements`` triple round-trips byte-equal AND the genuine
printing drives ``add_plus_one_counters`` → 2 on the Python side.
"""

from __future__ import annotations

import importlib.util

import pytest

from mtg_bot.cards.base import CardPrinting, ManaCost
from mtg_bot.cards.source import get_active_source
from mtg_bot.effects.modifiers import (
    EventPattern,
    MultiplyCount,
    ReplacementEffect,
)
from mtg_bot.effects.predicates import Event


_PRINTINGS = get_active_source().get_printings()


_rust_skip = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


ZONE_BATTLEFIELD = 2


def _vanilla_bear() -> CardPrinting:
    """A vanilla 2/2 Bear — the +1/+1-counter recipient Loading Zone's
    doubler multiplies (a creature you control)."""
    return CardPrinting(
        name="Loading Zone Probe Bear",
        mana_cost_str="",
        mana_cost=ManaCost(generic=1, colored=()),
        type_line="Creature — Bear",
        supertypes=(),
        card_types=("Creature",),
        subtypes=("Bear",),
        power=2,
        toughness=2,
        produces=frozenset(),
        triggered_abilities=(),
    )


# ---------------------------------------------------------------------------
# (1) Parser SoT.
# ---------------------------------------------------------------------------


def test_loading_zone_parser_claims_card():
    assert "Loading Zone" in _PRINTINGS, (
        "Loading Zone must be parser-claimed by the active CardSource"
    )


def test_loading_zone_printed_attrs():
    p = _PRINTINGS["Loading Zone"]
    assert "Enchantment" in p.card_types
    assert p.power is None
    assert p.toughness is None
    assert p.mana_cost.generic == 3
    assert p.mana_cost.colored == (("G", 1),)


def test_loading_zone_static_shape():
    """The parsed printing carries exactly one StaticAbility whose
    ``replacement_effect`` is ``ReplacementEffect(WOULD_PLACE_COUNTER,
    MultiplyCount(2))`` — the counter-doubler shape."""
    p = _PRINTINGS["Loading Zone"]
    assert len(p.static_abilities) == 1
    (sa,) = p.static_abilities
    re = sa.replacement_effect
    assert re is not None
    assert re.event_pattern.event is Event.WOULD_PLACE_COUNTER
    assert re.transform == MultiplyCount(factor=2)
    assert re.scope_filter is None
    assert re.event_pattern.subject_filters == ()


# ---------------------------------------------------------------------------
# (2) Bridge round-trip — genuine printing → CardDef → registry dict →
# reverse → Python StaticAbility, byte-equal.
# ---------------------------------------------------------------------------


def test_loading_zone_card_def_carries_static_replacement():
    from mtg_bot.parity.trajectory import _loading_zone_card_def

    cd = _loading_zone_card_def(_PRINTINGS["Loading Zone"])
    assert cd is not None
    assert cd.card_type == "Enchantment"
    assert cd.static_replacements == (
        ("would_place_counter", "multiply_count", 2),
    )


def test_loading_zone_bridge_round_trip_byte_equal():
    from mtg_bot.parity.cross_engine import (
        _card_def_to_python_printing,
        _spec_card_to_printing_dict,
    )
    from mtg_bot.parity.trajectory import _loading_zone_card_def

    cd = _loading_zone_card_def(_PRINTINGS["Loading Zone"])
    registry_dict = _spec_card_to_printing_dict(cd)
    assert registry_dict["static_replacements"] == [
        {
            "event": "would_place_counter",
            "transform_kind": "multiply_count",
            "transform_param": 2,
        },
    ]
    rehydrated = _card_def_to_python_printing(cd)
    [sa] = rehydrated.static_abilities
    assert sa.replacement_effect == ReplacementEffect(
        event_pattern=EventPattern(event=Event.WOULD_PLACE_COUNTER),
        transform=MultiplyCount(factor=2),
    )


# ---------------------------------------------------------------------------
# (3) Rust synthetic-carrier parse sanity.
# ---------------------------------------------------------------------------


@_rust_skip
def test_rust_parser_accepts_loading_zone_static_replacement_dict():
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Loading Zone (synthetic carrier)",
            "card_types": ["Enchantment"],
            "mana_cost": {"generic": 3, "G": 1},
            "static_replacements": [
                {
                    "event": "would_place_counter",
                    "transform_kind": "multiply_count",
                    "transform_param": 2,
                },
            ],
        }
    )
    assert isinstance(pid, int)


# ---------------------------------------------------------------------------
# (4) GENUINE real-EoE cross-engine probe — drives the ACTUAL parsed
# Loading Zone printing through the Python-side ``add_plus_one_counters``
# (the WOULD_PLACE_COUNTER dispatch), verifying the ×2 counter-doubling
# contract (place 1 → 2 land on a creature the controller controls),
# paired with the bridge round-trip byte-equality.
# ---------------------------------------------------------------------------


@_rust_skip
def test_cross_engine_real_eoe_loading_zone_counter_doubling_parity():
    """**GENUINE real-EoE cross-engine probe — Loading Zone
    WOULD_PLACE_COUNTER × MultiplyCount(2). PROBED-tier flip
    (blocked_subsystem_gated → PROBED).**

    Drives the genuine parsed Loading Zone printing through:

      * **Bridge round-trip** (Rust parse + reverse): the
        ``static_replacements`` triple round-trips byte-equal to the
        parser-SoT ``ReplacementEffect(WOULD_PLACE_COUNTER,
        MultiplyCount(2))``.
      * **Python-side resolve** (the live dispatch): with the genuine
        Loading Zone on p0's battlefield, ``add_plus_one_counters(state,
        bear, 1)`` places 2 counters (the ×2 doubling); with no Loading
        Zone it places 1.

    **Established idiom (Rust resolve-arm honest-stopped).** The
    ``would_place_counter`` × ``MultiplyCount`` shape has no single Rust
    resolve consumer this phase — Rust places +1/+1 counters at several
    scattered arms, each with its own add site; folding a doubler into
    every one is honest-stopped (see ``docs/SEARCH_LIMITATIONS.md``).
    The PROBED flip uses the parse-SoT + bridge round-trip + Python-side
    resolve idiom (same as Cosmogrand Zenith), pinning the Effect+bridge
    byte-equality + the live ×2 counter count independent of any Rust
    counter-placement path.

    **Shared transform with Exalted Sunborn.** Loading Zone reuses the
    ``MultiplyCount(2)`` EventTransform Exalted Sunborn pins, on the
    distinct ``WOULD_PLACE_COUNTER`` event — demonstrating the substrate
    amortizes the transform across events.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec,
        _card_def_to_python_printing,
        _spec_card_to_printing_dict,
        build_python_state,
    )
    from mtg_bot.parity.trajectory import _loading_zone_card_def
    from mtg_bot.game import Zone, add_plus_one_counters

    real = _PRINTINGS.get("Loading Zone")
    if real is None:
        pytest.skip("Loading Zone absent from active CardSource")

    # Bridge round-trip byte-equality.
    cd = _loading_zone_card_def(real)
    registry_dict = _spec_card_to_printing_dict(cd)
    assert registry_dict["static_replacements"] == [
        {
            "event": "would_place_counter",
            "transform_kind": "multiply_count",
            "transform_param": 2,
        },
    ]
    rehydrated = _card_def_to_python_printing(cd)
    [sa] = rehydrated.static_abilities
    assert sa.replacement_effect == ReplacementEffect(
        event_pattern=EventPattern(event=Event.WOULD_PLACE_COUNTER),
        transform=MultiplyCount(factor=2),
    )

    # Python-side resolve smoke — genuine printing drives ×2 counters.
    st = build_python_state(
        DeckSpec(card_defs=(), p0_library=(), p1_library=())
    )
    lz = st.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    st.battlefield.append(lz)
    bear = st.new_object(_vanilla_bear(), owner_id=0, zone=Zone.BATTLEFIELD)
    bear.summoning_sick = False
    st.battlefield.append(bear)
    placed = add_plus_one_counters(st, bear, 1)
    assert placed == 2, (
        f"Loading Zone must double place-1 → 2 counters; got {placed}"
    )
    assert bear.plus_one_counters == 2, (
        f"Bear must carry 2 +1/+1 counters after doubling; got "
        f"{bear.plus_one_counters}"
    )

    # Negative control: no Loading Zone → place 1, not doubled.
    st2 = build_python_state(
        DeckSpec(card_defs=(), p0_library=(), p1_library=())
    )
    bear2 = st2.new_object(_vanilla_bear(), owner_id=0, zone=Zone.BATTLEFIELD)
    bear2.summoning_sick = False
    st2.battlefield.append(bear2)
    placed2 = add_plus_one_counters(st2, bear2, 1)
    assert placed2 == 1, (
        f"With no Loading Zone, place-1 must stay 1; got {placed2}"
    )
    assert bear2.plus_one_counters == 1
