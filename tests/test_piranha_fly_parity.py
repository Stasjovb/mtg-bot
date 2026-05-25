"""Piranha Fly — per-card real-EoE cross-engine byte-equal probe
(covered_by_construction → PROBED tier flip).

Piranha Fly is a ``{1}{U}`` Creature — Fish Insect in the EoE pool,
2/1 P/T with one safe keyword: flying.  Vanilla in the bridge-carrier
sense — no ActivatedAbilities, no TriggeredAbilities, no spell_effect.

Templates directly on the batch-7 sibling
``test_bedhead_beastie_parity.py`` — bit-identical bridge-carrier shape
contract; the per-slug attribution distinction is the printing
identity (Piranha Fly={1}{U} 2/1 flying, Bedhead={4}{R}{R} 5/6 menace,
Daggermaw={4}{U}{U} 5/7 vigilance) + the flying-keyword subset variant.

**EEEE-idiom for the bridge-simple vanilla-creature carrier.**  Same
lane discipline as batches 1-7 (parse + bridge round-trip + Python-
side seated-permanent observation, NO cross-engine ``compare_fields``).

**NEW shape coverage:** binds the Piranha Fly slug to the flying-
keyword variant of the bridge-simple-vanilla-creature family — the
FIRST PROBE_MODULES-credited probe for this slug AND the FIRST flying-
keyword binding under the family templated by batch 7 (the batch-7
Daggermaw/Magus/Cackling/Spectral/Bedhead siblings exercised
vigilance/empty/deathtouch/empty/menace respectively).  Per the
cathedral-of-war-style same-Effect-class-different-printing-slug
precedent, each keyword variant earns a PROBED-tier slot.

Piranha Fly is a Stellar Sights / Special-Guests reprint in the EoE
pool (0 17lands decks per the live snapshot — not in the 17lands draft
sample); the per-card attribution still counts under POOL_PARITY's
pool-membership rule (the parser claims the printing, classify_pool
sees it in the EoE pool, the probe binds the slug — no deck-count
gate on PROBED-tier attribution).
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


def test_piranha_fly_parser_claims_card():
    assert "Piranha Fly" in _PRINTINGS, (
        "Piranha Fly must be parser-claimed by the active CardSource"
    )


def test_piranha_fly_printed_attrs():
    """Pins the basic printing surface: {1}{U} Creature — Fish Insect,
    2/1 P/T, keywords = {flying}, ZERO structured Effects."""
    p = _PRINTINGS["Piranha Fly"]
    assert "Creature" in p.card_types
    assert p.supertypes == ()
    assert p.keywords == frozenset({"flying"}), (
        f"Piranha Fly must carry exactly 'flying' keyword (a member of "
        f"_SAFE_KEYWORDS for the bridge-simple-creature admit); got "
        f"keywords={p.keywords}"
    )
    assert p.power == 2
    assert p.toughness == 1
    assert p.mana_cost.generic == 1
    assert p.mana_cost.colored == (("U", 1),)
    assert p.activated_abilities == ()
    assert p.triggered_abilities == ()
    assert p.spell_effect is None


def test_piranha_fly_loader_admits_as_simple_creature():
    """Pins the bridge-admit gate: Piranha Fly passes
    ``_printing_is_bridge_simple_creature`` (Creature + non-None P/T +
    flying ∈ _SAFE_KEYWORDS + no AAs/TAs/spell_effect)."""
    from mtg_bot.parity.trajectory import (
        _printing_is_bridge_simple_creature,
    )

    p = _PRINTINGS["Piranha Fly"]
    assert _printing_is_bridge_simple_creature(p) is True


def test_piranha_fly_card_def_bridge_round_trip():
    """The CardDef bridge round-trip materializes Piranha Fly as a
    Python printing with the bridge-carried subset preserved:
    card_types=("Creature",), power=2, toughness=1,
    keywords=frozenset({"flying"}), mana_cost generic=1 colored=
    (("B", 1),).  Subtypes are documented-drop on round-trip per the
    CardDef bridge contract."""
    from mtg_bot.parity.trajectory import _printing_to_card_def
    from mtg_bot.parity.cross_engine import _card_def_to_python_printing

    real = _PRINTINGS["Piranha Fly"]
    cd = _printing_to_card_def(real)
    assert cd.name == "Piranha Fly"
    assert cd.card_type == "Creature"
    assert cd.power == 2
    assert cd.toughness == 1
    assert cd.mana_cost_generic == 1
    assert cd.mana_cost_colored == (("U", 1),)
    assert "flying" in cd.keywords

    py_round = _card_def_to_python_printing(cd)
    assert "Creature" in py_round.card_types
    assert py_round.power == 2
    assert py_round.toughness == 1
    assert py_round.mana_cost.generic == 1
    assert py_round.mana_cost.colored == (("U", 1),)
    assert py_round.keywords == frozenset({"flying"})


@_rust_skip
def test_rust_parser_accepts_piranha_fly_simple_creature_dict():
    """Lockstep pin: Rust's ``register_printing`` accepts the Piranha
    Fly-shape registry dict — Creature card_type + 2/1 P/T + flying
    keyword + {1}{U} mana cost."""
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Piranha Fly (synthetic carrier)",
            "card_types": ["Creature"],
            "mana_cost": {"generic": 1, "U": 1},
            "power": 2,
            "toughness": 1,
            "keywords": ["flying"],
            "effects": [],
        }
    )
    assert isinstance(pid, int)


def test_cross_engine_real_eoe_piranha_fly_bridge_simple_creature_flying_parity():
    """**GENUINE real-EoE cross-engine probe — Piranha Fly bridge-
    simple-creature flying variant. PROBED-tier flip
    (covered_by_construction → PROBED).**

    Drives the **ACTUAL parsed Piranha Fly printing** through the
    CardDef bridge round-trip + seated-permanent observation.  Mirrors
    the EEEE-idiom; same lane discipline as batches 1-6 + the batch-7
    sibling probes.

    **NEW shape coverage:** binds the Piranha Fly slug to the flying-
    keyword variant of the bridge-simple-vanilla-creature family.
    Distinct from the batch-7 Daggermaw Megalodon (vigilance) /
    Cackling Slasher (deathtouch) / Magus of the Moon (empty) /
    Spectral Snatcher (empty) / Bedhead Beastie (menace) per-keyword
    variants — flying is the FIRST flying-keyword binding under the
    family.
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

    real = _PRINTINGS.get("Piranha Fly")
    if real is None:
        pytest.skip("Piranha Fly absent from active CardSource")
    assert "Creature" in real.card_types
    assert real.power == 2
    assert real.toughness == 1
    assert real.keywords == frozenset({"flying"})
    assert real.activated_abilities == ()
    assert real.triggered_abilities == ()
    assert real.spell_effect is None

    assert _printing_is_bridge_simple_creature(real) is True

    cd = _printing_to_card_def(real)
    py_round = _card_def_to_python_printing(cd)
    assert py_round.power == 2
    assert py_round.toughness == 1
    assert py_round.keywords == frozenset({"flying"})

    # Distinctness regression guard — flying is distinct from sibling
    # keyword bindings under the family.
    assert py_round.keywords == frozenset({"flying"}), (
        "Piranha Fly's bridge-carried keyword is 'flying' — distinct "
        "from Daggermaw (vigilance) / Cackling Slasher (deathtouch) / "
        "Bedhead Beastie (menace) / Magus / Spectral (empty) siblings"
    )
    assert (py_round.power, py_round.toughness) == (2, 1)

    # Seated-permanent observation.
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
    assert effective_power(py_state, py_source) == 2
    assert effective_toughness(py_state, py_source) == 1
