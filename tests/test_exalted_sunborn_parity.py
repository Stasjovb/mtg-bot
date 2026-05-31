"""Exalted Sunborn — per-card real-EoE cross-engine byte-equal probe
(blocked_subsystem_gated → PROBED tier flip).

Exalted Sunborn is a ``{3}{W}{W}`` Creature — Angel Wizard (4/5, flying
+ lifelink, warp {1}{W}) in the EoE pool carrying ONE static ability:

    "If you would create one or more tokens, create twice that many
     tokens instead."

Parser-emitted shape (verified by ``test_exalted_sunborn_static_shape``):
    ``StaticAbility(scope="self",
        replacement_effect=ReplacementEffect(
            event_pattern=EventPattern(event=WOULD_CREATE_TOKEN),
            transform=MultiplyCount(factor=2)))``

This module is the **load-bearing PROBED-tier flip evidence** for
Exalted Sunborn and the FIRST PROBE_MODULES-credited consumer of the
Phase-5 ReplacementEffect-static substrate (Rust
``StaticReplacement`` + ``static_replacements`` field + parse + the
``token_creation_count_multiplier`` resolve-arm consumer wired into
``Effect::CreateToken``; bridge ``CardDef.static_replacements`` field +
forward emit + reverse arm).

**Why this is the STRONGEST form (full cross-engine count parity).**
Unlike the EEEE-idiom Python-resolve-only siblings (Starfield Vocalist
/ Loading Zone, whose Rust resolve sites are honest-stopped), Exalted
Sunborn's ``would_create_token`` × ``MultiplyCount`` shape HAS a live
Rust resolve-arm consumer this phase — so this probe drives the genuine
parsed printing through BOTH engines' token-creation count path and
asserts the post-replacement count is byte-equal: a single
``CreateToken(count=1)`` under an Exalted Sunborn the controller
controls mints exactly TWO tokens on BOTH engines, and ONE token when
no Exalted Sunborn is present (the negative control).

The warp_cost the printing also carries ({1}{W}) is NOT engaged by this
probe — the probe drives the static replacement effect directly, the
same way the Equipment-AA + Sliver Overlord closures proved the warp
gate doesn't block a probe that drives the Effect directly. The static
replacement is the load-bearing surface; warp is a separate cast-time
subsystem the probe doesn't exercise.
"""

from __future__ import annotations

import importlib.util

import pytest

from mtg_bot.cards.base import CardPrinting, ManaCost
from mtg_bot.cards.source import get_active_source
from mtg_bot.effects.generic.tokens import CreateToken
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


# Zone constants (mirror Rust's u8 zone IDs).
ZONE_HAND = 0
ZONE_LIBRARY = 1
ZONE_BATTLEFIELD = 2
ZONE_GRAVEYARD = 3
ZONE_EXILE = 5


def _robot_token_printing() -> CardPrinting:
    """A vanilla 2/2 Robot token printing, the token Exalted Sunborn's
    doubler multiplies (the token printing is irrelevant to the
    doubling — any printing exercises the count path)."""
    return CardPrinting(
        name="Robot Token (Exalted Sunborn probe)",
        mana_cost_str="",
        mana_cost=ManaCost(generic=0, colored=()),
        type_line="Artifact Creature — Robot",
        supertypes=("Token",),
        card_types=("Artifact", "Creature"),
        subtypes=("Robot",),
        power=2,
        toughness=2,
        produces=frozenset(),
        triggered_abilities=(),
    )


# ---------------------------------------------------------------------------
# (1) Parser SoT — Exalted Sunborn is parser-claimed and emits the
# single WOULD_CREATE_TOKEN × MultiplyCount(2) replacement static.
# ---------------------------------------------------------------------------


def test_exalted_sunborn_parser_claims_card():
    assert "Exalted Sunborn" in _PRINTINGS, (
        "Exalted Sunborn must be parser-claimed by the active CardSource"
    )


def test_exalted_sunborn_printed_attrs():
    p = _PRINTINGS["Exalted Sunborn"]
    assert "Creature" in p.card_types
    assert "Angel" in p.subtypes
    assert p.power == 4
    assert p.toughness == 5
    assert p.mana_cost.generic == 3
    assert p.mana_cost.colored == (("W", 2),)


def test_exalted_sunborn_static_shape():
    """The parsed printing carries exactly one StaticAbility whose
    ``replacement_effect`` is ``ReplacementEffect(WOULD_CREATE_TOKEN,
    MultiplyCount(2))`` — the canonical token-doubler shape."""
    p = _PRINTINGS["Exalted Sunborn"]
    assert len(p.static_abilities) == 1
    (sa,) = p.static_abilities
    re = sa.replacement_effect
    assert re is not None, (
        "Exalted Sunborn's static must carry a replacement_effect"
    )
    assert re.event_pattern.event is Event.WOULD_CREATE_TOKEN
    assert re.transform == MultiplyCount(factor=2)
    assert re.scope_filter is None
    assert re.event_pattern.subject_filters == ()


# ---------------------------------------------------------------------------
# (2) Bridge round-trip — the genuine printing routes through
# ``_printing_to_card_def`` → ``_spec_card_to_printing_dict`` → registry
# dict CARRYING the Phase-5 ``static_replacements`` shape; the inverse
# ``_card_def_to_python_printing`` rehydrates a Python StaticAbility
# whose replacement_effect matches the parser SoT byte-equal.
# ---------------------------------------------------------------------------


def test_exalted_sunborn_card_def_carries_static_replacement():
    """``_printing_to_card_def`` maps the genuine printing's
    WOULD_CREATE_TOKEN × MultiplyCount(2) static into the CardDef
    ``static_replacements`` triple shape."""
    from mtg_bot.parity.trajectory import _exalted_sunborn_card_def

    cd = _exalted_sunborn_card_def(_PRINTINGS["Exalted Sunborn"])
    assert cd is not None
    assert cd.static_replacements == (
        ("would_create_token", "multiply_count", 2),
    )


def test_exalted_sunborn_bridge_round_trip_byte_equal():
    """The CardDef ``static_replacements`` triple round-trips byte-equal:
    forward to the registry dict shape, inverse to a Python
    StaticAbility whose ``replacement_effect`` matches the parser SoT
    (WOULD_CREATE_TOKEN, MultiplyCount(2))."""
    from mtg_bot.parity.cross_engine import (
        _card_def_to_python_printing,
        _spec_card_to_printing_dict,
    )
    from mtg_bot.parity.trajectory import _exalted_sunborn_card_def

    cd = _exalted_sunborn_card_def(_PRINTINGS["Exalted Sunborn"])
    registry_dict = _spec_card_to_printing_dict(cd)
    assert registry_dict["static_replacements"] == [
        {
            "event": "would_create_token",
            "transform_kind": "multiply_count",
            "transform_param": 2,
        },
    ]
    rehydrated = _card_def_to_python_printing(cd)
    [sa] = rehydrated.static_abilities
    assert sa.replacement_effect == ReplacementEffect(
        event_pattern=EventPattern(event=Event.WOULD_CREATE_TOKEN),
        transform=MultiplyCount(factor=2),
    )


# ---------------------------------------------------------------------------
# (3) Rust synthetic-carrier parse sanity — the Rust parser accepts the
# bridged ``static_replacements`` dict on an Exalted-Sunborn-shape
# Creature carrier.
# ---------------------------------------------------------------------------


@_rust_skip
def test_rust_parser_accepts_exalted_sunborn_static_replacement_dict():
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Exalted Sunborn (synthetic carrier)",
            "card_types": ["Creature"],
            "subtypes": ["Angel", "Wizard"],
            "power": 4,
            "toughness": 5,
            "mana_cost": {"generic": 3, "W": 2},
            "static_replacements": [
                {
                    "event": "would_create_token",
                    "transform_kind": "multiply_count",
                    "transform_param": 2,
                },
            ],
        }
    )
    assert isinstance(pid, int)


# ---------------------------------------------------------------------------
# (4) GENUINE real-EoE cross-engine byte-equal probe — drives the ACTUAL
# parsed Exalted Sunborn printing through BOTH engines' token-creation
# count path and asserts the post-replacement count is byte-equal:
# create-1-token → BOTH engines mint 2; with no Exalted Sunborn → BOTH
# mint 1.
# ---------------------------------------------------------------------------


@_rust_skip
def test_cross_engine_real_eoe_exalted_sunborn_token_doubling_parity():
    """**GENUINE real-EoE cross-engine probe — Exalted Sunborn
    WOULD_CREATE_TOKEN × MultiplyCount(2). PROBED-tier flip
    (blocked_subsystem_gated → PROBED).**

    Drives the genuine parsed Exalted Sunborn printing through BOTH
    engines' token-creation count path:

      * **Rust:** registers the genuine printing's bridge dict (carrying
        ``static_replacements``), injects it on p0's battlefield, then
        resolves an ETB ``create_token`` (count=1). The
        ``token_creation_count_multiplier`` resolve-arm consumer folds
        the ×2 → p0's battlefield grows by TWO tokens.
      * **Python:** seats the genuine printing on p0's battlefield and
        resolves ``CreateToken(count=1)``; the ``dispatch_replacement``
        on WOULD_CREATE_TOKEN folds the ×2 → p0 gains TWO tokens.

    Both engines mint the SAME post-replacement count (2). The negative
    control (no Exalted Sunborn present) mints ONE on both — proving the
    doubling is gated on the carrier, not unconditional.

    **NEW shape coverage:** the FIRST PROBE_MODULES-credited probe of
    the ReplacementEffect-static family — a CR 614
    ``StaticAbility.replacement_effect`` driven cross-engine through a
    live resolve-arm count multiply. Distinct from every prior PROBED
    card (all ContinuousModifier / per-printing-flag / Effect-leaf
    shapes — none drove a replacement-static count transform).
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec,
        _spec_card_to_printing_dict,
        build_python_state,
        build_rust_state,
    )
    from mtg_bot.parity.trajectory import _exalted_sunborn_card_def
    from mtg_bot.game import Zone

    real = _PRINTINGS.get("Exalted Sunborn")
    if real is None:
        pytest.skip("Exalted Sunborn absent from active CardSource")

    cd = _exalted_sunborn_card_def(real)
    registry_dict = _spec_card_to_printing_dict(cd)

    # ------------------------------------------------------------------
    # Rust: inject Exalted Sunborn + an ETB that creates 1 token.
    # ------------------------------------------------------------------
    rs = build_rust_state(DeckSpec(card_defs=(), p0_library=(), p1_library=()))
    # Token printing -> pid 0 (first injection on the fresh registry).
    rs.register_and_inject_object(
        {
            "name": "Robot Token (Exalted Sunborn probe)",
            "card_types": ["Artifact", "Creature"],
            "subtypes": ["Robot"],
            "supertypes": ["Token"],
            "power": 2,
            "toughness": 2,
            "mana_cost": {"generic": 0},
            "effects": [],
        },
        0,
        ZONE_LIBRARY,
    )
    token_pid = 0
    # The genuine Exalted Sunborn, with an ETB that creates 1 token (the
    # ETB is a synthetic driver to exercise the count path; the
    # static_replacements ride on the genuine printing's bridge dict).
    es_dict = dict(registry_dict)
    es_dict["triggered_abilities"] = [
        {
            "event": "enters",
            "predicate": {"kind": "source_is_self"},
            "effect": {
                "kind": "create_token",
                "count": 1,
                "token_printing_id": token_pid,
            },
        },
    ]
    rs.register_and_inject_object(es_dict, 0, ZONE_BATTLEFIELD)
    rust_before = list(rs.battlefield_sizes)[0]
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rust_after = list(rs.battlefield_sizes)[0]
    rust_minted = rust_after - rust_before

    # ------------------------------------------------------------------
    # Python: seat genuine Exalted Sunborn + resolve CreateToken(1).
    # ------------------------------------------------------------------
    py_state = build_python_state(
        DeckSpec(card_defs=(), p0_library=(), p1_library=())
    )
    py_src = py_state.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    py_src.summoning_sick = False
    py_state.battlefield.append(py_src)
    py_before = len([o for o in py_state.battlefield if o.controller_id == 0])
    CreateToken(token_printing=_robot_token_printing(), count=1).resolve(
        py_state, 0
    )
    py_after = len([o for o in py_state.battlefield if o.controller_id == 0])
    py_minted = py_after - py_before

    # ------------------------------------------------------------------
    # Cross-engine byte-equal: BOTH engines mint exactly 2 tokens.
    # ------------------------------------------------------------------
    assert rust_minted == 2, (
        f"Rust Exalted Sunborn must double create-1 → mint 2; got "
        f"{rust_minted}"
    )
    assert py_minted == 2, (
        f"Python Exalted Sunborn must double create-1 → mint 2; got "
        f"{py_minted}"
    )
    assert rust_minted == py_minted, (
        f"Cross-engine token-count divergence: Rust minted "
        f"{rust_minted}, Python minted {py_minted}"
    )


@_rust_skip
def test_cross_engine_exalted_sunborn_negative_control_no_doubling():
    """Negative control: with NO Exalted Sunborn on the battlefield, a
    create-1-token mints exactly ONE on BOTH engines — the doubling is
    gated on the carrier's presence, not unconditional."""
    from mtg_bot.parity.cross_engine import (
        DeckSpec,
        build_python_state,
        build_rust_state,
    )
    from mtg_bot.game import Zone

    # Rust: a plain carrier (no static_replacements) creating 1 token.
    rs = build_rust_state(DeckSpec(card_defs=(), p0_library=(), p1_library=()))
    rs.register_and_inject_object(
        {
            "name": "Robot Token (neg control)",
            "card_types": ["Artifact", "Creature"],
            "subtypes": ["Robot"],
            "supertypes": ["Token"],
            "power": 2,
            "toughness": 2,
            "mana_cost": {"generic": 0},
            "effects": [],
        },
        0,
        ZONE_LIBRARY,
    )
    rs.register_and_inject_object(
        {
            "name": "Plain Carrier (neg control)",
            "card_types": ["Creature"],
            "power": 3,
            "toughness": 3,
            "mana_cost": {"generic": 2},
            "effects": [],
            "triggered_abilities": [
                {
                    "event": "enters",
                    "predicate": {"kind": "source_is_self"},
                    "effect": {
                        "kind": "create_token",
                        "count": 1,
                        "token_printing_id": 0,
                    },
                },
            ],
        },
        0,
        ZONE_BATTLEFIELD,
    )
    rust_before = list(rs.battlefield_sizes)[0]
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rust_minted = list(rs.battlefield_sizes)[0] - rust_before

    # Python: a plain bf (no Exalted Sunborn) resolving CreateToken(1).
    py_state = build_python_state(
        DeckSpec(card_defs=(), p0_library=(), p1_library=())
    )
    py_before = len([o for o in py_state.battlefield if o.controller_id == 0])
    CreateToken(token_printing=_robot_token_printing(), count=1).resolve(
        py_state, 0
    )
    py_minted = (
        len([o for o in py_state.battlefield if o.controller_id == 0])
        - py_before
    )

    assert rust_minted == 1, f"Rust neg-control must mint 1; got {rust_minted}"
    assert py_minted == 1, f"Python neg-control must mint 1; got {py_minted}"
    assert rust_minted == py_minted
