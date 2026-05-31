"""Starfield Vocalist — per-card real-EoE cross-engine byte-equal probe
(blocked_subsystem_gated → PROBED tier flip).

Starfield Vocalist is a ``{3}{U}`` Creature — Human Bard (3/4, warp
{1}{U}) in the EoE pool carrying ONE static ability:

    "If a triggered ability of a permanent you control triggers, that
     ability triggers an additional time."

Parser-emitted shape (verified by ``test_starfield_vocalist_static_shape``):
    ``StaticAbility(scope="self",
        replacement_effect=ReplacementEffect(
            event_pattern=EventPattern(event=TRIGGERED_ABILITY_TRIGGERS),
            transform=AddInstances(delta=1)))``

This module is the PROBED-tier flip evidence for Starfield Vocalist and
a PROBE_MODULES-credited consumer of the Phase-5 ReplacementEffect-
static substrate. It is a SIBLING of Exalted Sunborn
(``test_exalted_sunborn_parity.py``): the SAME substrate (Rust
``StaticReplacement`` parse + bridge ``static_replacements`` field +
forward emit + reverse arm) carries this card's distinct
``(triggered_ability_triggers, add_instances, 1)`` triple.

**Established bridge + Python-resolve idiom (the Rust trigger-fire site
is honest-stopped).** Unlike Exalted Sunborn's
``would_create_token`` × ``MultiplyCount`` shape — which HAS a live Rust
resolve-arm consumer (``token_creation_count_multiplier``) — the
``triggered_ability_triggers`` + ``AddInstances`` shape has NO Rust
resolve consumer this phase: Rust's triggered-ability fire path doesn't
read a per-controller trigger-instance multiplier, and adding one
touches every trigger-emission site (high blast-radius). That Rust
resolve-arm wiring is HONEST-STOPPED to a later slice (documented in
``docs/SEARCH_LIMITATIONS.md``). The PROBED-tier flip rides on the SAME
idiom the Cosmogrand Zenith / Sunstar Lightsmith probes use: parser SoT
+ bridge round-trip (the ``static_replacements`` triple → registry dict
→ Rust parse + reverse → Python StaticAbility, byte-equal) + Python-side
resolve smoke (the genuine printing drives ``etb_trigger_multiplier`` →
2). Both the bridge byte-equality and the Python-side ×2 are
independent of any Rust resolve-arm trigger-fire path.
"""

from __future__ import annotations

import importlib.util

import pytest

from mtg_bot.cards.source import get_active_source
from mtg_bot.effects.modifiers import (
    AddInstances,
    EventPattern,
    ReplacementEffect,
)
from mtg_bot.effects.predicates import Event


_PRINTINGS = get_active_source().get_printings()


_rust_skip = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


ZONE_BATTLEFIELD = 2


# ---------------------------------------------------------------------------
# (1) Parser SoT.
# ---------------------------------------------------------------------------


def test_starfield_vocalist_parser_claims_card():
    assert "Starfield Vocalist" in _PRINTINGS, (
        "Starfield Vocalist must be parser-claimed by the active "
        "CardSource"
    )


def test_starfield_vocalist_printed_attrs():
    p = _PRINTINGS["Starfield Vocalist"]
    assert "Creature" in p.card_types
    assert "Human" in p.subtypes
    assert p.power == 3
    assert p.toughness == 4
    assert p.mana_cost.generic == 3
    assert p.mana_cost.colored == (("U", 1),)


def test_starfield_vocalist_static_shape():
    """The parsed printing carries exactly one StaticAbility whose
    ``replacement_effect`` is ``ReplacementEffect(
    TRIGGERED_ABILITY_TRIGGERS, AddInstances(1))`` — the extra-trigger
    shape (distinct from the MultiplyCount doublers)."""
    p = _PRINTINGS["Starfield Vocalist"]
    assert len(p.static_abilities) == 1
    (sa,) = p.static_abilities
    re = sa.replacement_effect
    assert re is not None
    assert re.event_pattern.event is Event.TRIGGERED_ABILITY_TRIGGERS
    assert re.transform == AddInstances(delta=1)
    assert re.scope_filter is None
    assert re.event_pattern.subject_filters == ()


# ---------------------------------------------------------------------------
# (2) Bridge round-trip — genuine printing → CardDef → registry dict →
# reverse → Python StaticAbility, byte-equal.
# ---------------------------------------------------------------------------


def test_starfield_vocalist_card_def_carries_static_replacement():
    from mtg_bot.parity.trajectory import _starfield_vocalist_card_def

    cd = _starfield_vocalist_card_def(_PRINTINGS["Starfield Vocalist"])
    assert cd is not None
    assert cd.static_replacements == (
        ("triggered_ability_triggers", "add_instances", 1),
    )


def test_starfield_vocalist_bridge_round_trip_byte_equal():
    from mtg_bot.parity.cross_engine import (
        _card_def_to_python_printing,
        _spec_card_to_printing_dict,
    )
    from mtg_bot.parity.trajectory import _starfield_vocalist_card_def

    cd = _starfield_vocalist_card_def(_PRINTINGS["Starfield Vocalist"])
    registry_dict = _spec_card_to_printing_dict(cd)
    assert registry_dict["static_replacements"] == [
        {
            "event": "triggered_ability_triggers",
            "transform_kind": "add_instances",
            "transform_param": 1,
        },
    ]
    rehydrated = _card_def_to_python_printing(cd)
    [sa] = rehydrated.static_abilities
    assert sa.replacement_effect == ReplacementEffect(
        event_pattern=EventPattern(
            event=Event.TRIGGERED_ABILITY_TRIGGERS
        ),
        transform=AddInstances(delta=1),
    )


# ---------------------------------------------------------------------------
# (3) Rust synthetic-carrier parse sanity.
# ---------------------------------------------------------------------------


@_rust_skip
def test_rust_parser_accepts_starfield_vocalist_static_replacement_dict():
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Starfield Vocalist (synthetic carrier)",
            "card_types": ["Creature"],
            "subtypes": ["Human", "Bard"],
            "power": 3,
            "toughness": 4,
            "mana_cost": {"generic": 3, "U": 1},
            "static_replacements": [
                {
                    "event": "triggered_ability_triggers",
                    "transform_kind": "add_instances",
                    "transform_param": 1,
                },
            ],
        }
    )
    assert isinstance(pid, int)


# ---------------------------------------------------------------------------
# (4) GENUINE real-EoE cross-engine probe — drives the ACTUAL parsed
# Starfield Vocalist printing through the Python-side
# ``etb_trigger_multiplier`` (the TRIGGERED_ABILITY_TRIGGERS dispatch),
# verifying the +1 extra-instance contract (a permanent the controller
# controls fires its triggered ability TWICE), paired with the bridge
# round-trip byte-equality.
# ---------------------------------------------------------------------------


@_rust_skip
def test_cross_engine_real_eoe_starfield_vocalist_extra_trigger_parity():
    """**GENUINE real-EoE cross-engine probe — Starfield Vocalist
    TRIGGERED_ABILITY_TRIGGERS + AddInstances(1). PROBED-tier flip
    (blocked_subsystem_gated → PROBED).**

    Drives the genuine parsed Starfield Vocalist printing through:

      * **Bridge round-trip** (Rust parse + reverse): the
        ``static_replacements`` triple round-trips byte-equal to the
        parser-SoT ``ReplacementEffect(TRIGGERED_ABILITY_TRIGGERS,
        AddInstances(1))``.
      * **Python-side resolve** (the live dispatch): with the genuine
        Starfield Vocalist on p0's battlefield,
        ``etb_trigger_multiplier(state, 0)`` returns 2 (one base +1
        extra instance); with no Starfield Vocalist it returns 1.

    **Established idiom (Rust resolve-arm honest-stopped).** The
    ``triggered_ability_triggers`` + ``AddInstances`` shape has no Rust
    resolve-arm consumer this phase (the trigger-fire site is scattered;
    wiring a per-controller instance multiplier there touches every
    trigger-emission site — honest-stopped, see
    ``docs/SEARCH_LIMITATIONS.md``). The PROBED flip uses the
    parse-SoT + bridge round-trip + Python-side-resolve idiom (same as
    Cosmogrand Zenith), which pins the Effect+bridge byte-equality + the
    live ×2 instance count independent of any Rust trigger-fire path.

    **NEW shape coverage:** the FIRST PROBE_MODULES-credited consumer of
    the ``AddInstances`` EventTransform (Exalted Sunborn / Loading Zone
    use ``MultiplyCount``) and of the ``TRIGGERED_ABILITY_TRIGGERS``
    replacement event.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec,
        _card_def_to_python_printing,
        _spec_card_to_printing_dict,
        build_python_state,
    )
    from mtg_bot.parity.trajectory import _starfield_vocalist_card_def
    from mtg_bot.game import Zone, etb_trigger_multiplier

    real = _PRINTINGS.get("Starfield Vocalist")
    if real is None:
        pytest.skip("Starfield Vocalist absent from active CardSource")

    # Bridge round-trip byte-equality.
    cd = _starfield_vocalist_card_def(real)
    registry_dict = _spec_card_to_printing_dict(cd)
    assert registry_dict["static_replacements"] == [
        {
            "event": "triggered_ability_triggers",
            "transform_kind": "add_instances",
            "transform_param": 1,
        },
    ]
    rehydrated = _card_def_to_python_printing(cd)
    [sa] = rehydrated.static_abilities
    assert sa.replacement_effect == ReplacementEffect(
        event_pattern=EventPattern(
            event=Event.TRIGGERED_ABILITY_TRIGGERS
        ),
        transform=AddInstances(delta=1),
    )

    # Python-side resolve smoke — genuine printing drives ×2 instances.
    st = build_python_state(
        DeckSpec(card_defs=(), p0_library=(), p1_library=())
    )
    src = st.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    src.summoning_sick = False
    st.battlefield.append(src)
    assert etb_trigger_multiplier(st, 0) == 2, (
        "Starfield Vocalist must add +1 trigger instance (×2 total) for "
        "its controller"
    )

    # Negative control: no Starfield Vocalist → base 1 instance.
    st2 = build_python_state(
        DeckSpec(card_defs=(), p0_library=(), p1_library=())
    )
    assert etb_trigger_multiplier(st2, 0) == 1, (
        "With no Starfield Vocalist the trigger multiplier must be 1 "
        "(no extra instance)"
    )
