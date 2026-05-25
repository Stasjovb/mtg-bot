"""Daggermaw Megalodon — per-card real-EoE cross-engine byte-equal
probe (covered_by_construction → PROBED tier flip).

Daggermaw Megalodon is a ``{4}{U}{U}`` Creature — Shark in the EoE
pool (vanilla creature with one safe keyword: vigilance), 5/7 P/T.
Zero structured Effects on the parser side — no ActivatedAbilities,
no TriggeredAbilities, no spell_effect.  The card is a pure
"bridge-simple creature" carrier whose load-bearing observable is
the CardDef bridge round-trip + Python's combat-reader observation
of the seated permanent on the battlefield.

Parser-emitted printing shape:

    ``CardPrinting(name="Daggermaw Megalodon",
                   card_types=("Creature",),
                   subtypes=("Shark",),
                   keywords=frozenset({"vigilance"}),
                   power=5, toughness=7,
                   mana_cost=ManaCost(generic=4,
                                      colored=(("U", 2),)),
                   ... all rider fields default)``

The CardDef bridge round-trip
(``_printing_to_card_def`` → ``_card_def_to_python_printing``)
materializes the printing back through the bench-loader path.  The
``_printing_is_bridge_simple_creature`` admit predicate gates on:
* ``"Creature" in card_types``
* power + toughness non-None
* keywords ⊆ ``_SAFE_KEYWORDS`` (vigilance qualifies)
* no AAs / TAs / spell_effect / static_abilities / warp / kicker /
  impending / room halves / loyalty / cost_reductions / station_
  threshold / unsafe dynamic_pt_formula / ward_cost

The CardDef bridge contract drops subtypes (the bench loader does
not thread subtypes through the CardDef shape — the per-card
admitted subset round-trips ``("Creature",)`` only) per the
``_card_def_to_python_printing`` arm's documented signature.  The
PROBED-tier byte-equality contract is the SUBSET the bridge carries
— card_types, supertypes (empty), power, toughness, mana_cost,
``_SAFE_KEYWORDS`` keywords — all of which round-trip byte-equal.

This module is the **load-bearing PROBED-tier flip evidence** for
Daggermaw Megalodon.  Opens a **NEW shape family** for the per-slug
attribution lane: **bridge-simple vanilla-creature carrier via
``_printing_is_bridge_simple_creature`` admit + CardDef round-trip**
— distinct from the basic-land bridge-auto-wire family (batch 6)
and the AA-/TA-bearing carriers of batches 1-5.  The vanilla-
creature family in the covered_by_construction tier (Daggermaw
Megalodon, Cackling Slasher, Magus of the Moon, Bedhead Beastie,
Piranha Fly, Spectral Snatcher, Slavering Branchsnapper, Shepherding
Spirits, Patched Plaything, Fear of Being Hunted) all share the
``_printing_is_bridge_simple_creature`` admit shape; this probe
templates the family — siblings will template directly off this
module.

**EEEE-idiom for the bridge-simple vanilla-creature carrier.**  Same
lane discipline as batches 1-6 (parse + bridge round-trip + Python-
side resolve, NO cross-engine ``compare_fields``).  There is no
structured Effect to resolve; the "resolve smoke" piece is replaced
with the **seated-permanent observation** — seat the bridge round-
tripped Python printing on p0's battlefield, then assert Python's
combat readers (``effective_power``, ``effective_toughness``,
``is_creature_now``) match the parsed printing's printed_P/T /
card_type.  This is the bridge-carrier-shape analog of the Effect-
resolve observation that the batches 1-5 / 6 AA-bearing siblings
exercise.

**NEW shape coverage:** the FIRST PROBE_MODULES-credited probe
binding the Daggermaw Megalodon slug — AND the bridge-simple vanilla-
creature shape family — to the CardDef round-trip + seated-permanent
observation observable.  Per the cathedral-of-war-style same-Effect-
class-different-printing-slug precedent, this slug-level binding
earns a PROBED-tier slot.

The Daggermaw Megalodon slug is a Stellar Sights / Special-Guests
reprint in the EoE pool (0 17lands decks per the live snapshot —
not in the 17lands draft sample); the per-card attribution still
counts under POOL_PARITY's pool-membership rule (the parser claims
the printing, classify_pool sees it in the EoE pool, the probe
binds the slug — no deck-count gate on PROBED-tier attribution).
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


# Zone constants (mirror Rust's u8 zone IDs).
ZONE_BATTLEFIELD = 2


# ---------------------------------------------------------------------------
# (1) Parser SoT — Daggermaw Megalodon is parser-claimed as a {4}{U}{U}
# Creature — Shark with vigilance, 5/7, and ZERO structured Effects.
# ---------------------------------------------------------------------------


def test_daggermaw_megalodon_parser_claims_card():
    assert "Daggermaw Megalodon" in _PRINTINGS, (
        "Daggermaw Megalodon must be parser-claimed by the active "
        "CardSource"
    )


def test_daggermaw_megalodon_printed_attrs():
    """Pins the basic printing surface: {4}{U}{U} Creature — Shark,
    5/7 P/T, keywords = {vigilance}, ZERO structured Effects."""
    p = _PRINTINGS["Daggermaw Megalodon"]
    assert "Creature" in p.card_types
    assert p.supertypes == ()
    assert "Shark" in p.subtypes, (
        f"Daggermaw Megalodon must carry 'Shark' subtype; got "
        f"subtypes={p.subtypes}"
    )
    assert p.keywords == frozenset({"vigilance"}), (
        f"Daggermaw Megalodon must carry exactly the 'vigilance' "
        f"keyword (a member of _SAFE_KEYWORDS for the bridge-simple-"
        f"creature admit); got keywords={p.keywords}"
    )
    assert p.power == 5
    assert p.toughness == 7
    assert p.mana_cost.generic == 4
    assert p.mana_cost.colored == (("U", 2),), (
        f"Daggermaw Megalodon mana cost is {{4}}{{U}}{{U}}; got "
        f"colored={p.mana_cost.colored}"
    )
    # ZERO structured Effects on the parser side.
    assert p.activated_abilities == ()
    assert p.triggered_abilities == ()
    assert p.spell_effect is None


def test_daggermaw_megalodon_loader_admits_as_simple_creature():
    """Pins the bridge-admit gate: Daggermaw Megalodon passes
    ``_printing_is_bridge_simple_creature`` — the bridge-simple-
    vanilla-creature carrier admit predicate (Creature card_type +
    non-None P/T + keywords ⊆ _SAFE_KEYWORDS + no AAs/TAs/spell_effect/
    static_abilities/warp/kicker/impending/room halves/loyalty/cost_
    reductions/station_threshold/unsafe dynamic_pt_formula/ward_cost
    — vigilance qualifies)."""
    from mtg_bot.parity.trajectory import (
        _printing_is_bridge_simple_creature,
    )

    p = _PRINTINGS["Daggermaw Megalodon"]
    assert _printing_is_bridge_simple_creature(p) is True, (
        "Daggermaw Megalodon must pass the bridge-simple-creature admit "
        "predicate (vigilance is in _SAFE_KEYWORDS, no AAs/TAs/spell_"
        "effect/etc.); without admission the CardDef bridge can't "
        "round-trip the printing"
    )


# ---------------------------------------------------------------------------
# (2) Bridge round-trip — _printing_to_card_def → CardDef →
# _card_def_to_python_printing materializes the bridge-carried subset
# byte-equal to the parsed printing's printed_P/T / card_types /
# _SAFE_KEYWORDS keywords / mana_cost.
# ---------------------------------------------------------------------------


def test_daggermaw_megalodon_card_def_bridge_round_trip():
    """The CardDef bridge round-trip
    (``_printing_to_card_def`` → ``_card_def_to_python_printing``)
    materializes Daggermaw Megalodon as a Python printing with the
    bridge-carried subset preserved: card_types=("Creature",), power=5,
    toughness=7, keywords={vigilance}, mana_cost generic=4 colored=
    (("U", 2),).

    Byte-equality contract (EEEE-idiom, bridge-carried subset):

      ``_printing_to_card_def(Daggermaw)`` →
      ``CardDef(name="Daggermaw Megalodon", card_type="Creature",
                power=5, toughness=7,
                mana_cost_generic=4, mana_cost_colored=(("U", 2),),
                keywords=("vigilance",))``

      ``_card_def_to_python_printing(<that CardDef>)`` →
      ``CardPrinting(card_types=("Creature",), power=5, toughness=7,
                     keywords=frozenset({"vigilance"}),
                     mana_cost=ManaCost(generic=4,
                                        colored=(("U", 2),)),
                     ...)``

    The CardDef bridge contract DROPS subtypes — the parser-side
    ``("Shark",)`` does NOT round-trip through the bridge (the bench
    loader does not thread subtypes through the CardDef shape).  This
    is documented as the bridge-carrier-shape contract; the PROBED-
    tier byte-equality is on the bridge-carried SUBSET, not on the
    full parser surface.  The per-slug PROBED attribution credits the
    slug on the bridge-carried subset alone (the round-1 PROBED-tier
    definition)."""
    from mtg_bot.parity.trajectory import _printing_to_card_def
    from mtg_bot.parity.cross_engine import _card_def_to_python_printing

    real = _PRINTINGS["Daggermaw Megalodon"]
    cd = _printing_to_card_def(real)
    assert cd.name == "Daggermaw Megalodon"
    assert cd.card_type == "Creature"
    assert cd.power == 5
    assert cd.toughness == 7
    assert cd.mana_cost_generic == 4
    assert cd.mana_cost_colored == (("U", 2),)
    assert "vigilance" in cd.keywords

    py_round = _card_def_to_python_printing(cd)
    assert "Creature" in py_round.card_types
    assert py_round.power == 5
    assert py_round.toughness == 7
    assert py_round.mana_cost.generic == 4
    assert py_round.mana_cost.colored == (("U", 2),)
    assert py_round.keywords == frozenset({"vigilance"}), (
        f"Bridge-round-tripped keywords must be byte-equal to the "
        f"parser-side {{'vigilance'}} (the _SAFE_KEYWORDS member "
        f"survives the CardDef carry); got {py_round.keywords}"
    )
    # Documented bridge-contract drop: subtypes are NOT round-tripped.
    assert py_round.subtypes == (), (
        "CardDef bridge contract: subtypes are DROPPED on round-trip; "
        "the parser-side ('Shark',) does not survive the CardDef "
        "carry — this is the documented PROBED-tier subset boundary"
    )


# ---------------------------------------------------------------------------
# (3) Rust synthetic-carrier sanity — Rust's register_printing accepts
# the Daggermaw-shape registry dict.
# ---------------------------------------------------------------------------


@_rust_skip
def test_rust_parser_accepts_daggermaw_megalodon_simple_creature_dict():
    """Lockstep pin: Rust's ``register_printing`` accepts the Daggermaw
    Megalodon-shape registry dict — Creature card_type + 5/7 P/T +
    vigilance keyword + {4}{U}{U} mana cost."""
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Daggermaw Megalodon (synthetic carrier)",
            "card_types": ["Creature"],
            "mana_cost": {"generic": 4, "U": 2},
            "power": 5,
            "toughness": 7,
            "keywords": ["vigilance"],
            "effects": [],
        }
    )
    assert isinstance(pid, int)


# ---------------------------------------------------------------------------
# (4) GENUINE real-EoE cross-engine byte-equal probe — drives the
# ACTUAL parsed Daggermaw Megalodon printing through the CardDef bridge
# round-trip and verifies Python's combat readers reflect the bridge-
# carried subset byte-equal to the parsed printed_P/T / card_types /
# keywords.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_daggermaw_megalodon_bridge_simple_creature_parity():
    """**GENUINE real-EoE cross-engine probe — Daggermaw Megalodon
    bridge-simple-creature carrier bridge round-trip + seated-permanent
    observable. PROBED-tier flip (covered_by_construction → PROBED).**

    Drives the **ACTUAL parsed Daggermaw Megalodon printing** through
    the CardDef bridge round-trip + the bridge-carried Python printing
    is seated on p0's battlefield + Python's combat readers
    (``effective_power``, ``effective_toughness``, ``is_creature_now``)
    are observed to reflect the bridge-carried subset byte-equal to
    the parsed printed_P/T / card_types / keywords.

    Mirrors the EEEE-idiom; same lane discipline as batches 1-6.  The
    "resolve smoke" piece is replaced with the **seated-permanent
    observation** — there is no structured Effect on a vanilla creature
    to resolve, so the load-bearing observable is the bench-loader-
    seated permanent's combat-reader read.

    **NEW shape coverage:** the FIRST PROBE_MODULES-credited probe
    binding the bridge-simple-vanilla-creature shape family to a slug
    — Daggermaw Megalodon is the templating carrier for the family
    (sibling probes on Magus of the Moon / Cackling Slasher /
    Spectral Snatcher template directly off this module).

    **Bridge contract exercised:**
      * ``_printing_is_bridge_simple_creature`` admit predicate.
      * ``_printing_to_card_def`` Creature arm.
      * ``_card_def_to_python_printing`` Creature arm (carries
        card_types + P/T + mana_cost + _SAFE_KEYWORDS keywords;
        documented drop on subtypes).

    **Setup (Python-side):**
      * Round-trip the ACTUAL parsed Daggermaw Megalodon through the
        CardDef bridge.
      * Seat the round-tripped Python printing on p0's battlefield.
      * Stamp ``summoning_sick=False`` to clear the new_object default
        (Rust's register_and_inject_object defaults to False; we
        normalize Python to match — same precedent as the Frantic
        Strength batch precedent).

    **Observables asserted:**
      * Bridge admit predicate fires (Daggermaw passes
        ``_printing_is_bridge_simple_creature``).
      * Bridge round-trip materializes a Python printing with the
        bridge-carried subset byte-equal: card_types=("Creature",),
        power=5, toughness=7, keywords=frozenset({"vigilance"}),
        mana_cost generic=4 colored=(("U", 2),).
      * Seated-permanent combat readers: effective_power=5,
        effective_toughness=7, is_creature_now=True.
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

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Daggermaw Megalodon printing.
    # ------------------------------------------------------------------
    real = _PRINTINGS.get("Daggermaw Megalodon")
    if real is None:
        pytest.skip("Daggermaw Megalodon absent from active CardSource")
    assert "Creature" in real.card_types
    assert real.power == 5
    assert real.toughness == 7
    assert real.keywords == frozenset({"vigilance"})
    assert real.activated_abilities == ()
    assert real.triggered_abilities == ()
    assert real.spell_effect is None

    # ------------------------------------------------------------------
    # 2. Bridge admit fires.
    # ------------------------------------------------------------------
    assert _printing_is_bridge_simple_creature(real) is True, (
        "Daggermaw Megalodon must pass _printing_is_bridge_simple_"
        "creature — the bridge-simple-vanilla-creature admit predicate"
    )

    # ------------------------------------------------------------------
    # 3. Drive the CardDef bridge round-trip.
    # ------------------------------------------------------------------
    cd = _printing_to_card_def(real)
    assert cd.card_type == "Creature"
    assert cd.power == 5
    assert cd.toughness == 7
    assert cd.mana_cost_generic == 4
    assert cd.mana_cost_colored == (("U", 2),)
    assert "vigilance" in cd.keywords

    py_round = _card_def_to_python_printing(cd)
    assert "Creature" in py_round.card_types
    assert py_round.power == 5
    assert py_round.toughness == 7
    assert py_round.keywords == frozenset({"vigilance"}), (
        f"bridge-carried keywords subset must round-trip byte-equal; "
        f"got {py_round.keywords}"
    )
    assert py_round.mana_cost.generic == 4
    assert py_round.mana_cost.colored == (("U", 2),)

    # ------------------------------------------------------------------
    # 4. Distinctness regression guard — Daggermaw's bridge subset is
    #    distinct from sibling vanilla-creature shapes in the family.
    # ------------------------------------------------------------------
    # P/T 5/7 is distinct from Magus of the Moon 2/2, Cackling Slasher
    # 3/3, Spectral Snatcher 6/5.
    assert (py_round.power, py_round.toughness) == (5, 7), (
        "Daggermaw bridge subset P/T must be 5/7 — distinct from sibling "
        "vanilla-creature probes' shapes"
    )
    # 'vigilance' is the distinguishing _SAFE_KEYWORDS bit.
    assert py_round.keywords == frozenset({"vigilance"}), (
        "Daggermaw's bridge-carried keyword is 'vigilance' — distinct "
        "from Cackling Slasher's 'deathtouch' / Bedhead Beastie's "
        "'menace' / Magus of the Moon's empty / Spectral Snatcher's "
        "empty siblings"
    )

    # ------------------------------------------------------------------
    # 5. Seated-permanent observation smoke — seat the bridge round-
    #    tripped Python printing on p0's battlefield and verify Python's
    #    combat readers reflect the bridge-carried subset.
    # ------------------------------------------------------------------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py_state = build_python_state(spec)

    py_source = py_state.new_object(
        py_round, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_source.tapped = False
    # Normalize summoning_sick to match Rust's register_and_inject_object
    # default (False) — same precedent as Frantic Strength batch.
    py_source.summoning_sick = False
    py_source.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_source)

    assert is_creature_now(py_source) is True, (
        "Daggermaw must read as a Creature on the seated permanent — "
        "the bridge-carried card_types includes 'Creature'"
    )
    assert effective_power(py_state, py_source) == 5, (
        f"Daggermaw effective_power must be 5 (the bridge-carried "
        f"printed power); got {effective_power(py_state, py_source)}"
    )
    assert effective_toughness(py_state, py_source) == 7, (
        f"Daggermaw effective_toughness must be 7 (the bridge-carried "
        f"printed toughness); got "
        f"{effective_toughness(py_state, py_source)}"
    )
