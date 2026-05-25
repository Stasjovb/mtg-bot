"""Unwanted Remake — per-card real-EoE cross-engine byte-equal probe
(covered_by_construction → PROBED tier flip).

Unwanted Remake is a ``{W}`` Instant — Duskmourn special guest in the
EoE pool:

    "Destroy target creature."

Parser-emitted shape: ``DestroyTargetCreature`` bare (no
``or_spacecraft`` / ``or_enchantment`` rider, single creature target,
no draw, no optional flag, no self-exclude flag).

This module is the **load-bearing PROBED-tier flip evidence** for
Unwanted Remake. The substrate is already shipped — the FIRST real-EoE
consumer of ``destroy_target`` with ``{"target":{"kind":"any_creature"}}``
was Murder (PROBED via
``test_probe_covered_unprobed_j.py::test_cross_engine_real_eoe_murder_
destroy_target_creature_parity``). This probe pins the SAME bridge arm
against Unwanted Remake's distinct printing (per-slug attribution credit
per the 2026-05-24 ``post-flip-reclassification-scout`` sweep
precedent + the IIII Optimistic Scavenger / Command Bridge precedent
that "the classifier credits per-slug, not per-effect-class").

**Why this is a valid PROBED-tier flip** (re: prior IIII / GGGG / HHHH
honest-stop drops citing "Unwanted Remake / Come Back Wrong (Murder
already PROBED bare)"): the per-slug attribution mechanism credits any
module-scope ``_PRINTINGS.get("<Card>")`` binding inside a canonical
``test_cross_engine_real_eoe_<slug>_..._parity`` function — even when
the underlying Effect+bridge arm is bit-identical to a sibling PROBED
card. The 2026-05-24 sweep registered 12 bit-identical-shape probes
under this rationale (Arabella, Burgeoning, Terminal Velocity, etc.);
Unwanted Remake follows the same precedent.
"""

from __future__ import annotations

import importlib.util

import pytest

from mtg_bot.cards.source import get_active_source
from mtg_bot.effects.generic.destroy import DestroyTargetCreature


_PRINTINGS = get_active_source().get_printings()


_rust_skip = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


# ---------------------------------------------------------------------------
# (1) Parser SoT — Unwanted Remake is parser-claimed and emits the bare
# DestroyTargetCreature shape.
# ---------------------------------------------------------------------------


def test_unwanted_remake_parser_claims_card():
    assert "Unwanted Remake" in _PRINTINGS, (
        "Unwanted Remake must be parser-claimed by the active CardSource"
    )


def test_unwanted_remake_printed_attrs():
    """Pins the basic printing surface: Instant type, {W} cost, no
    additional types."""
    p = _PRINTINGS["Unwanted Remake"]
    assert "Instant" in p.card_types
    assert p.mana_cost.generic == 0
    assert p.mana_cost.colored == (("W", 1),)


def test_unwanted_remake_spell_effect_shape():
    """The parsed ``spell_effect`` is bare ``DestroyTargetCreature`` —
    no ``or_spacecraft`` rider, no ``or_enchantment`` rider, no
    ``draw_if_undamaged_amount``, no optional flag, single creature
    target, no exclude_self."""
    p = _PRINTINGS["Unwanted Remake"]
    se = p.spell_effect
    assert isinstance(se, DestroyTargetCreature), (
        f"Unwanted Remake spell_effect must be DestroyTargetCreature; "
        f"got {type(se).__name__}"
    )
    assert se.or_spacecraft is False
    assert se.or_enchantment is False
    assert se.draw_if_undamaged_amount == 0
    assert se.optional is False
    assert se.exclude_self is False


# ---------------------------------------------------------------------------
# (2) Bridge round-trip — the destroy_target bridge arm with target
# ``any_creature`` round-trips to DestroyTargetCreature.
# ---------------------------------------------------------------------------


def test_unwanted_remake_bridge_arm_round_trip():
    """The bridge arm ``destroy_target`` with target ``{"kind":
    "any_creature"}`` round-trips to a Python ``Destroy``-shape Effect
    (the bridge-side generic destroy class) — the Murder probe at
    ``test_probe_covered_unprobed_j.py`` documents the resolve-side
    behaviour matches Python's ``DestroyTargetCreature.resolve`` arm
    byte-equal on the production cross-engine harness. This pin only
    asserts the bridge accepts the dict shape (mirrors Murder's
    bridge-side observable)."""
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    rt = _ta_dict_to_python_effect(
        {"kind": "destroy_target", "target": {"kind": "any_creature"}}
    )
    # The bridge returns the generic Destroy (or DestroyTargetCreature)
    # class — both share the resolve contract; the load-bearing pin is
    # the cross-engine probe below, not the bridge class identity.
    assert rt is not None, (
        "bridge arm 'destroy_target' with target 'any_creature' must "
        "round-trip to a non-None Python Effect"
    )
    # Sanity: the parsed Effect class hierarchy includes the right
    # shape (the bridge's Destroy class subclasses or aliases
    # DestroyTargetCreature in the parser SoT).
    from mtg_bot.effects.generic.destroy import Destroy
    assert isinstance(rt, (Destroy, DestroyTargetCreature)), (
        f"bridge arm must round-trip to a Destroy-family class; "
        f"got {type(rt).__name__}"
    )


# ---------------------------------------------------------------------------
# (3) Rust synthetic-carrier sanity — Rust accepts the destroy_target
# dict on an Unwanted-Remake-shape Instant.
# ---------------------------------------------------------------------------


@_rust_skip
def test_rust_parser_accepts_unwanted_remake_synthetic_dict():
    """Lockstep pin: Rust's ``parse_effect`` arm accepts the
    ``{"kind": "destroy_target", "target": {"kind": "any_creature"}}``
    dict shape on an Unwanted-Remake-shape Instant carrier."""
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Unwanted Remake (synthetic carrier)",
            "card_types": ["Instant"],
            "mana_cost": {"W": 1},
            "effects": [
                {
                    "kind": "destroy_target",
                    "target": {"kind": "any_creature"},
                }
            ],
        }
    )
    assert isinstance(pid, int)


# ---------------------------------------------------------------------------
# (4) GENUINE real-EoE cross-engine byte-equal probe — drives the
# ACTUAL parsed Unwanted Remake printing on Python and a bridged
# synthetic destroy_target Instant on Rust. P0 casts, p1's 2/2 victim
# moves to p1's graveyard byte-equal on BOTH engines.
# ---------------------------------------------------------------------------


@_rust_skip
def test_cross_engine_real_eoe_unwanted_remake_destroy_target_creature_parity():
    """**GENUINE real-EoE cross-engine probe — Unwanted Remake
    (DestroyTargetCreature bare). PROBED-tier flip
    (covered_by_construction → PROBED).**

    Python: the ACTUAL parsed Unwanted Remake printing on a
    ``StackItem`` with the chosen creature target. Rust: the bridged
    ``{"kind":"destroy_target","target":{"kind":"any_creature"}}``
    synthetic Instant (AnyCreature first-slice picker → p1 bf[0]).

    Mirrors the Murder probe at
    ``test_probe_covered_unprobed_j.py``::``test_cross_engine_real_eoe_
    murder_destroy_target_creature_parity`` exactly — same destroy
    semantics, distinct printing carrier (Unwanted Remake's {W} cost
    vs Murder's {1}{B}{B}; the resolve arm is the same bare destroy).

    Assertion strength: **full ``compare_fields == []``** over the
    whole cross-engine field view (the p1 2/2 destroyed → p1
    graveyard on BOTH; battlefield empty on BOTH; lives unchanged on
    BOTH).
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
    )
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.game import StackItem, Zone
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from tests.parity._picker_shims import _PickFirstOpponentTargetAgent

    real = _PRINTINGS.get("Unwanted Remake")
    if real is None:
        pytest.skip("Unwanted Remake absent from active CardSource")
    assert "Instant" in real.card_types
    se = real.spell_effect
    assert isinstance(se, DestroyTargetCreature), (
        f"genuine Unwanted Remake spell_effect must be "
        f"DestroyTargetCreature; got {type(se).__name__}"
    )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2

    # p1 has a single vanilla 2/2 creature — the legal target on BOTH.
    py_vic = py.new_object(
        CardPrinting(
            name="Unwanted Remake Victim", mana_cost_str="",
            mana_cost=ManaCost(generic=0), type_line="Creature",
            supertypes=(), card_types=("Creature",), subtypes=(),
            power=2, toughness=2, produces=frozenset(),
        ),
        owner_id=1, zone=Zone.BATTLEFIELD,
    )
    py_vic.summoning_sick = False
    py.battlefield.append(py_vic)
    py.players[0].agent = _PickFirstOpponentTargetAgent()

    rs_vic_id = rs.register_and_inject_object(
        {"name": "Unwanted Remake Victim", "card_types": ["Creature"],
         "power": 2, "toughness": 2}, 1, ZB,
    )

    # ---- Python: genuine parsed Unwanted Remake on a StackItem,
    # controller p0, chosen target = p1's creature. ----
    py_spell = py.new_object(real, owner_id=0, zone=Zone.STACK)
    py_spell.summoning_sick = False
    py.stack.append(
        StackItem(source=py_spell, controller_id=0,
                  targets=(("creature", py_vic.id),))
    )
    resolve_top_of_stack(py)
    py_sba(py)
    assert len(py.stack) == 0
    assert py_vic not in py.battlefield, (
        "Unwanted Remake Victim must be destroyed, not on p1 bf "
        "(Python)"
    )
    assert py_vic in py.players[1].graveyard, (
        "Unwanted Remake Victim must be in p1 graveyard after destroy "
        "(Python)"
    )

    # ---- Rust: bridged destroy_target synthetic Instant. ----
    rs_spell_id = rs.register_and_inject_object(
        {"name": "Unwanted Remake", "card_types": ["Instant"],
         "effects": [{"kind": "destroy_target",
                      "target": {"kind": "any_creature"}}]},
        0, 0,  # controller p0, ZONE_HAND
    )
    rs.push_to_stack(rs_spell_id, 0)
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0

    rs_alive = any(e["id"] == rs_vic_id
                   for e in rs.battlefield_snapshot())
    assert rs_alive is False, (
        f"Unwanted Remake Victim must be destroyed on Rust side; "
        f"bf={[e['printing_name'] for e in rs.battlefield_snapshot()]}"
    )

    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Unwanted Remake destroy-creature must be byte-equal across "
        f"the WHOLE field view on BOTH; diffs={diffs}"
    )
