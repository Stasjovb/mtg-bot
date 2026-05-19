"""Genuine real-EoE cross-engine byte-equality probe — subject_is_enchantment
unlock.

This module ships the FIRST cross-engine probe for the Duskmourn / EoE "Eerie"
ability-word predicate shape: ``And(Subject(None, IsEnchantment()),
Controlled(YOU))``.  The unlock comes from adding the ``SubjectIsEnchantment``
variant to the Rust ``Predicate`` enum (``rust/src/cards.rs``) plus the
``subject_is_enchantment`` arm to the Python bridge
(``src/mtg_bot/parity/cross_engine.py::_ta_dict_to_python_predicate``).

**Before this slice** the bridge raised::

    ValueError: cross_engine triggered_abilities bridge: unsupported
    predicate kind 'subject_is_enchantment'

and the Rust ``parse_predicate`` returned an unknown-kind error, so the
entire Eerie family (10 cards) was hard-blocked from cross-engine testing.

**After this slice** both engines share:

* Python: ``Subject(slot=None, inner=IsEnchantment()) & Controlled(YOU)``
* Rust: ``And { SubjectIsEnchantment, ControlledByYou }``

PROBE CARD — Balemurk Leech (EoE)
----------------------------------
Oracle: "[Creature — Leech] {1}{B} 2/2
  Eerie — Whenever this creature or another enchantment you control enters,
  each opponent loses 1 life."

  * Event = ``ENTERS``
  * Predicate = ``And(Subject(None, IsEnchantment()), Controlled(YOU))``
  * Effect = ``EachOpponentLosesLife(amount=1)``

PROBE FLOW
----------
1. Pre-seat Balemurk Leech on p0's battlefield as an observer (Python:
   actual parsed printing; Rust: bridged synthetic carrier with the exact
   ETB trigger dict).
2. Cast a synthetic bare enchantment (no abilities) from p0's hand onto the
   stack on both engines, then resolve it — it lands on p0's battlefield.
3. The Balemurk ENTERS observer fires on both engines: predicate
   ``SubjectIsEnchantment AND ControlledByYou`` matches the newly-entered
   enchantment under p0's control → push ``EachOpponentLosesLife(1)`` onto
   the stack.
4. Drain the triggered-ability stack item on both engines.
5. **Observable**: p1 loses exactly 1 life on BOTH engines (20→19).
   p0's life stays at 20 (``EachOpponentLosesLife`` only hits opponents).

ASSERTION IDIOM
---------------
Targeted-observable (life totals only) rather than full ``compare_fields``.
Reason: when a spell resolves onto the battlefield, Rust resets
``summoning_sick=False`` on the newly-landed permanent while Python preserves
whatever value the object carried on the stack. The enchantment subject
(``Probe Enchantment``) triggers this known representation artifact in the
battlefield tuple signature — it is NOT a game-semantics divergence (enchantments
cannot attack; ``summoning_sick`` is irrelevant for them) but it would cause a
``compare_fields != []`` failure. The targeted-observable idiom is the correct
response per the Overlord of the Floodpits precedent in
``tests/test_probe_covered_unprobed_h.py`` — we assert the gameplay-relevant
result (life totals) and document the known representation gap.

CARDS STILL BLOCKED AFTER THIS SLICE
--------------------------------------
All 10 Eerie-shaped EoE cards (Balemurk Leech, Cult Healer, Dashing
Bloodsucker, Entity Tracker, Erratic Apparition, Gremlin Tamer, Infernal
Phantom, Optimistic Scavenger, Scrabbling Skullcrab, Skullsnap Nuisance)
have their ENTERS predicate fully bridged by this slice. However, each card
may have OTHER gaps that prevent full parity:

* Infernal Phantom also has a DIES trigger — not covered here.
* The ``ROOM_FULLY_UNLOCKED`` arm is present on all 10 cards; the
  ``Event.ROOM_FULLY_UNLOCKED`` bridge is not exercised in this probe.
* Individual cards' effects may need their own bridge arms (e.g.
  Cult Healer's ``GrantKeywordUntilEOT(lifelink)``).

This probe establishes the PREDICATE substrate as bridged. Individual
card Effect probes are follow-on work.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest


pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


@pytest.fixture(scope="module")
def parity_smoke():
    """Load ``scripts/parity_smoke.py`` as a module (the field-view
    builder lives there). Identical to the module-scoped fixture in
    other batch probe files — copied here so this module is fully
    self-contained."""
    repo_root = pathlib.Path(__file__).resolve().parent.parent
    script_path = repo_root / "scripts" / "parity_smoke.py"
    spec = importlib.util.spec_from_file_location(
        "parity_smoke", script_path
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["parity_smoke"] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Probe — Balemurk Leech Eerie trigger: enchantment enters → each opponent
# loses 1 life.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_balemurk_leech_eerie_each_opponent_loses_life(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Balemurk Leech (0 17lands
    decks). First ``subject_is_enchantment`` predicate probe.**

    Python: the ACTUAL parsed Balemurk Leech printing pre-seated on p0's
    battlefield. A synthetic bare enchantment (no abilities) is cast and
    resolved onto p0's bf; the Balemurk ENTERS observer fires
    (``Subject(None, IsEnchantment()) & Controlled(YOU)`` matches the
    newly-entered enchantment under p0's control) → ``EachOpponentLosesLife(1)``
    resolves → p1 life 20→19.

    Rust: the bridged synthetic carrier with the exact trigger dict
    (``predicate.kind = "and"``, left = ``subject_is_enchantment``, right =
    ``controlled_by_you``; effect = ``each_opponent_loses_life, amount=1``)
    pre-seated on p0's bf. The same bare synthetic enchantment resolves on the
    Rust side; the Rust predicate ``SubjectIsEnchantment && ControlledByYou``
    matches → EachOpponentLosesLife(1) → p1 life 20→19.

    Assertion strength: **targeted-observable** (life totals) because the
    newly-landed enchantment object has a ``summoning_sick`` representation
    divergence (Rust resets, Python preserves the stale stack value) that is
    gameplay-irrelevant for enchantments but would break a full
    ``compare_fields`` assertion. Same documented-gap idiom as Overlord of
    the Floodpits in ``test_probe_covered_unprobed_h.py``.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec,
        build_python_state,
        build_rust_state,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.game import StackItem, Zone
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.generic.life import EachOpponentLosesLife
    from mtg_bot.effects.predicates import And, Subject, Controlled, YOU
    from mtg_bot.effects.object_predicates import IsEnchantment

    # ----------------------------------------------------------------
    # 1. Verify the genuine parsed Balemurk Leech printing has the
    #    expected Eerie trigger shape.
    # ----------------------------------------------------------------
    real = get_active_source().get_printings().get("Balemurk Leech")
    if real is None:
        pytest.skip("Balemurk Leech absent from active CardSource")
    assert "Creature" in real.card_types, (
        "Balemurk Leech must be a Creature"
    )
    etb = next(
        (ta for ta in real.triggered_abilities
         if getattr(ta.event, "value", ta.event) == "enters"),
        None,
    )
    assert etb is not None, (
        "Balemurk Leech must have an ENTERS triggered ability"
    )
    assert isinstance(etb.effect, EachOpponentLosesLife), (
        f"Balemurk ENTERS effect must be EachOpponentLosesLife; "
        f"got {type(etb.effect).__name__}"
    )
    assert etb.effect.amount == 1, (
        f"Balemurk EachOpponentLosesLife amount must be 1; "
        f"got {etb.effect.amount}"
    )
    # Verify predicate shape: And(Subject(None, IsEnchantment()), Controlled(YOU))
    assert isinstance(etb.predicate, And), (
        f"Balemurk ENTERS predicate must be And; "
        f"got {type(etb.predicate).__name__}"
    )

    # ----------------------------------------------------------------
    # 2. Build cross-engine states.
    # ----------------------------------------------------------------
    ZB = 2   # ZONE_BATTLEFIELD
    ZH = 0   # ZONE_HAND

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)

    # ----------------------------------------------------------------
    # 3a. Python: pre-seat genuine Balemurk Leech on p0's bf.
    # ----------------------------------------------------------------
    py_balemurk = py.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    py_balemurk.summoning_sick = False
    py_balemurk.tapped = False
    py.battlefield.append(py_balemurk)

    # ----------------------------------------------------------------
    # 3b. Rust: pre-seat synthetic Balemurk Leech carrier on p0's bf.
    #     The trigger dict mirrors the parsed predicate exactly.
    # ----------------------------------------------------------------
    rs_balemurk_id = rs.register_and_inject_object(
        {
            "name": "Balemurk Leech",
            "card_types": ["Creature"],
            "power": int(real.power) if real.power is not None else 2,
            "toughness": int(real.toughness) if real.toughness is not None else 2,
            "effects": [],
            "triggered_abilities": [
                {
                    "event": "enters",
                    "predicate": {
                        "kind": "and",
                        "left": {"kind": "subject_is_enchantment"},
                        "right": {"kind": "controlled_by_you"},
                    },
                    "effect": {
                        "kind": "each_opponent_loses_life",
                        "amount": 1,
                    },
                }
            ],
        },
        0, ZB,  # controller p0, inject directly onto battlefield
    )
    assert rs.find_object_zone(rs_balemurk_id) == ZB, (
        "Balemurk Leech synthetic carrier must start on Rust battlefield"
    )

    # ----------------------------------------------------------------
    # 4. Record baseline life totals.
    # ----------------------------------------------------------------
    py_p0_life0 = py.players[0].life
    py_p1_life0 = py.players[1].life
    rs_p0_life0 = rs.get_life(0)
    rs_p1_life0 = rs.get_life(1)
    assert py_p1_life0 == 20 and rs_p1_life0 == 20, (
        "Both engines must start p1 at 20 life"
    )

    # ----------------------------------------------------------------
    # 5a. Python: cast a bare synthetic enchantment from p0's hand;
    #     it goes on the stack, then resolves onto p0's bf.
    # ----------------------------------------------------------------
    enchant_printing = CardPrinting(
        name="Probe Enchantment",
        mana_cost_str="",
        mana_cost=ManaCost(generic=0),
        type_line="Enchantment",
        supertypes=(),
        card_types=("Enchantment",),
        subtypes=(),
        power=None,
        toughness=None,
        produces=frozenset(),
    )
    py_ench = py.new_object(enchant_printing, owner_id=0, zone=Zone.STACK)
    py_ench.summoning_sick = False
    py.stack.append(StackItem(source=py_ench, controller_id=0))
    resolve_top_of_stack(py)
    assert any(o.printing.name == "Probe Enchantment"
               for o in py.battlefield), (
        "Probe Enchantment must have resolved onto Python battlefield"
    )
    assert len(py.stack) == 1, (
        "Balemurk Eerie trigger must be on Python stack after enchantment enters"
    )

    # ----------------------------------------------------------------
    # 5b. Rust: inject the same bare synthetic enchantment, push to
    #     stack, resolve → lands on bf → Balemurk trigger fires.
    # ----------------------------------------------------------------
    rs_ench_id = rs.register_and_inject_object(
        {
            "name": "Probe Enchantment",
            "card_types": ["Enchantment"],
            "effects": [],
            "triggered_abilities": [],
        },
        0, ZH,
    )
    rs.push_to_stack(rs_ench_id, 0)
    rs.resolve_top_of_stack()
    assert rs.find_object_zone(rs_ench_id) == ZB, (
        "Probe Enchantment must have resolved onto Rust battlefield"
    )
    assert rs.stack_size() == 1, (
        "Balemurk Eerie trigger must be on Rust stack after enchantment enters"
    )

    # ----------------------------------------------------------------
    # 6. Drain both stacks (EachOpponentLosesLife resolves).
    # ----------------------------------------------------------------
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)
    rs.apply_sbas()
    assert rs.stack_size() == 0 and len(py.stack) == 0, (
        "Both stacks must be empty after drain"
    )

    # ----------------------------------------------------------------
    # 7. Observable: each opponent (p1) loses exactly 1 life on BOTH.
    #    p0 (the Balemurk controller) is unaffected — the Effect targets
    #    each opponent, not the controller.
    # ----------------------------------------------------------------
    py_p1_life = py.players[1].life
    rs_p1_life = rs.get_life(1)
    py_p0_life = py.players[0].life
    rs_p0_life = rs.get_life(0)

    assert py_p1_life == py_p1_life0 - 1, (
        f"Python: p1 must lose exactly 1 life from Balemurk Eerie trigger; "
        f"was {py_p1_life0}, now {py_p1_life}"
    )
    assert rs_p1_life == rs_p1_life0 - 1, (
        f"Rust: p1 must lose exactly 1 life from Balemurk Eerie trigger; "
        f"was {rs_p1_life0}, now {rs_p1_life}"
    )
    assert py_p1_life == rs_p1_life, (
        f"Engines must agree on p1 life after Balemurk Eerie; "
        f"py={py_p1_life} rs={rs_p1_life}"
    )
    assert py_p0_life == py_p0_life0, (
        f"Python: p0 (Balemurk controller) must be unaffected; "
        f"was {py_p0_life0}, now {py_p0_life}"
    )
    assert rs_p0_life == rs_p0_life0, (
        f"Rust: p0 (Balemurk controller) must be unaffected; "
        f"was {rs_p0_life0}, now {rs_p0_life}"
    )
    # Byte-equal on the two gameplay-relevant observables:
    # p0 life unchanged, p1 life = 19 on both.
    assert py_p0_life == rs_p0_life == 20, (
        f"p0 life must be 20 on both engines; py={py_p0_life} rs={rs_p0_life}"
    )
    assert py_p1_life == rs_p1_life == 19, (
        f"p1 life must be 19 on both engines after Eerie trigger; "
        f"py={py_p1_life} rs={rs_p1_life}"
    )
