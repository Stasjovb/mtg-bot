"""Patched Plaything — per-card real-EoE cross-engine byte-equal probe
(covered_by_construction → PROBED tier flip).

Patched Plaything is a ``{2}{W}`` Artifact Creature — Toy in the EoE
pool, 4/3 P/T with one safe keyword: double strike.  Vanilla in the
bridge-carrier sense — no ActivatedAbilities, no TriggeredAbilities,
no spell_effect.

Templates directly on the batch-7 sibling
``test_bedhead_beastie_parity.py`` — bit-identical bridge-carrier shape
contract; the per-slug attribution distinction is the printing
identity (Patched Plaything={2}{W} 4/3 double strike, Artifact+Creature
multi-type) + the double-strike-keyword subset variant + the
**Artifact+Creature multi-type carrier** sub-shape.

**EEEE-idiom for the bridge-simple vanilla-creature carrier.**  Same
lane discipline as batches 1-7 (parse + bridge round-trip + Python-
side seated-permanent observation, NO cross-engine ``compare_fields``).

**NEW shape coverage:** binds the Patched Plaything slug to the
double-strike-keyword variant of the bridge-simple-vanilla-creature
family — the FIRST double-strike-keyword binding AND the FIRST
Artifact+Creature multi-type-carrier binding under the family.  The
parser-side ``card_types=("Artifact", "Creature")`` is documented-
drop on round-trip per the bare ``_printing_is_bridge_simple_creature``
arm's documented signature — the CardDef builds ``card_type="Creature"
+ extra_card_types=()`` (the Mechan-shape Artifact-Creature
extra_card_types threading is gated by the static-self-conditional
predicate, not the bare simple-creature arm), so the Artifact type is
symmetrically dropped on BOTH bridge sides.  Same precedent as the
batch-7 documented subtype drop (Daggermaw's "Shark" → empty).

Patched Plaything is a Stellar Sights / Special-Guests reprint in the
EoE pool (0 17lands decks per the live snapshot).
"""

from __future__ import annotations

import importlib.util

import pytest

from mtg_bot.cards.source import get_active_source


_PRINTINGS = get_active_source().get_printings()


_rust_skip = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


ZONE_BATTLEFIELD = 2


def test_patched_plaything_parser_claims_card():
    assert "Patched Plaything" in _PRINTINGS, (
        "Patched Plaything must be parser-claimed by the active "
        "CardSource"
    )


def test_patched_plaything_printed_attrs():
    """Pins the basic printing surface: {2}{W} Artifact Creature —
    Toy, 4/3 P/T, keywords = {double strike}, ZERO structured
    Effects."""
    p = _PRINTINGS["Patched Plaything"]
    assert "Creature" in p.card_types
    assert "Artifact" in p.card_types, (
        f"Patched Plaything must carry 'Artifact' card_type alongside "
        f"'Creature' (the multi-type sub-shape pin); got "
        f"card_types={p.card_types}"
    )
    assert p.supertypes == ()
    assert p.keywords == frozenset({"double strike"}), (
        f"Patched Plaything must carry exactly 'double strike' keyword "
        f"(a member of _SAFE_KEYWORDS for the bridge-simple-creature "
        f"admit); got keywords={p.keywords}"
    )
    assert p.power == 4
    assert p.toughness == 3
    assert p.mana_cost.generic == 2
    assert p.mana_cost.colored == (("W", 1),)
    assert p.activated_abilities == ()
    assert p.triggered_abilities == ()
    assert p.spell_effect is None


def test_patched_plaything_loader_admits_as_simple_creature():
    """Pins the bridge-admit gate: Patched Plaything passes
    ``_printing_is_bridge_simple_creature`` — the bare simple-creature
    arm accepts an Artifact-Creature card-type tuple (the predicate
    gates on ``"Creature" in card_types`` without a "Creature ONLY"
    exclusion; the multi-type carrier flows through, with the Artifact
    type symmetrically-dropped on bridge round-trip)."""
    from mtg_bot.parity.trajectory import (
        _printing_is_bridge_simple_creature,
    )

    p = _PRINTINGS["Patched Plaything"]
    assert _printing_is_bridge_simple_creature(p) is True


def test_patched_plaything_card_def_bridge_round_trip():
    """The CardDef bridge round-trip materializes Patched Plaything as
    a Python printing with the bridge-carried subset preserved:
    card_types=("Creature",) — Artifact dropped — power=4, toughness=3,
    keywords=frozenset({"double strike"}), mana_cost generic=2 colored=
    (("W", 1),).  The parser-side ``card_types=("Artifact", "Creature")``
    is symmetrically-dropped on round-trip: the bare simple-creature
    arm builds CardDef.card_type="Creature" with empty
    extra_card_types, so the Artifact type vanishes on BOTH bridge
    sides (same precedent as the batch-7 subtype drop)."""
    from mtg_bot.parity.trajectory import _printing_to_card_def
    from mtg_bot.parity.cross_engine import _card_def_to_python_printing

    real = _PRINTINGS["Patched Plaything"]
    cd = _printing_to_card_def(real)
    assert cd.name == "Patched Plaything"
    assert cd.card_type == "Creature"
    # Documented bridge-contract drop: the Artifact type does NOT
    # survive the bare simple-creature CardDef arm (extra_card_types
    # threading is gated by the static-self-conditional / token arms,
    # not the bare arm).
    assert cd.extra_card_types == (), (
        f"Bare simple-creature CardDef arm must yield empty "
        f"extra_card_types; got {cd.extra_card_types}"
    )
    assert cd.power == 4
    assert cd.toughness == 3
    assert cd.mana_cost_generic == 2
    assert cd.mana_cost_colored == (("W", 1),)
    assert "double strike" in cd.keywords

    py_round = _card_def_to_python_printing(cd)
    assert py_round.card_types == ("Creature",), (
        f"CardDef bridge contract: Patched Plaything's parser-side "
        f"('Artifact', 'Creature') is documented-drop on round-trip — "
        f"only ('Creature',) survives the bare simple-creature arm; "
        f"got {py_round.card_types}"
    )
    assert py_round.power == 4
    assert py_round.toughness == 3
    assert py_round.mana_cost.generic == 2
    assert py_round.mana_cost.colored == (("W", 1),)
    assert py_round.keywords == frozenset({"double strike"})


@_rust_skip
def test_rust_parser_accepts_patched_plaything_simple_creature_dict():
    """Lockstep pin: Rust's ``register_printing`` accepts the Patched
    Plaything-shape registry dict — Creature card_type + 4/3 P/T +
    double strike keyword + {2}{W} mana cost."""
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Patched Plaything (synthetic carrier)",
            "card_types": ["Creature"],
            "mana_cost": {"generic": 2, "W": 1},
            "power": 4,
            "toughness": 3,
            "keywords": ["double strike"],
            "effects": [],
        }
    )
    assert isinstance(pid, int)


def test_cross_engine_real_eoe_patched_plaything_bridge_simple_creature_double_strike_parity():
    """**GENUINE real-EoE cross-engine probe — Patched Plaything
    bridge-simple-creature double-strike variant (Artifact+Creature
    multi-type carrier). PROBED-tier flip
    (covered_by_construction → PROBED).**

    Drives the **ACTUAL parsed Patched Plaything printing** through
    the CardDef bridge round-trip + seated-permanent observation.
    Mirrors the EEEE-idiom; same lane discipline as batches 1-7.

    **NEW shape coverage:** binds the Patched Plaything slug to the
    double-strike-keyword variant of the bridge-simple-vanilla-creature
    family AND the FIRST Artifact+Creature multi-type-carrier sub-shape
    under the family.  Distinct from the batch-7
    Daggermaw/Magus/Cackling/Spectral/Bedhead variants AND from the
    batch-8 Piranha/Shepherding/Slavering siblings.  The
    Artifact-type drop on round-trip is documented (same precedent as
    the batch-7 subtype drop).
    """
    from mtg_bot.parity.trajectory import (
        _printing_is_bridge_simple_creature, _printing_to_card_def,
    )
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _card_def_to_python_printing,
    )
    from mtg_bot.game import (
        Zone, effective_power, effective_toughness, is_creature_now,
    )

    real = _PRINTINGS.get("Patched Plaything")
    if real is None:
        pytest.skip("Patched Plaything absent from active CardSource")
    assert "Creature" in real.card_types
    assert "Artifact" in real.card_types
    assert real.power == 4
    assert real.toughness == 3
    assert real.keywords == frozenset({"double strike"})
    assert real.activated_abilities == ()
    assert real.triggered_abilities == ()
    assert real.spell_effect is None

    assert _printing_is_bridge_simple_creature(real) is True

    cd = _printing_to_card_def(real)
    py_round = _card_def_to_python_printing(cd)
    assert py_round.card_types == ("Creature",)  # Artifact dropped.
    assert py_round.power == 4
    assert py_round.toughness == 3
    assert py_round.keywords == frozenset({"double strike"})

    # Distinctness regression guard.
    assert py_round.keywords == frozenset({"double strike"}), (
        "Patched Plaything's bridge-carried keyword is 'double strike' "
        "— distinct from sibling vigilance/deathtouch/menace/empty/"
        "flying/trample/haste keyword bindings under the family"
    )
    assert (py_round.power, py_round.toughness) == (4, 3)

    # Seated-permanent observation — the bridge round-tripped Python
    # printing reads as a Creature with effective P/T 4/3 (double strike
    # is a combat-time rider; the seated-permanent reader observes the
    # printed P/T directly, no static layered modifier required).
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py_state = build_python_state(spec)
    py_source = py_state.new_object(
        py_round, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_source.tapped = False
    py_source.summoning_sick = False
    py_source.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_source)

    assert is_creature_now(py_source) is True
    assert effective_power(py_state, py_source) == 4
    assert effective_toughness(py_state, py_source) == 3
