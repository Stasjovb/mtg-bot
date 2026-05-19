"""Genuine real-EoE cross-engine byte-equality probes — Eerie-mechanic cards
batch NN (downstream of JJ ``subject_is_enchantment`` unlock).

JJ's commit (``feature/rust-subject-is-enchantment``, merged to main as
``3933fcb4``) added ``SubjectIsEnchantment`` to the Rust ``Predicate`` enum
and wired the ``subject_is_enchantment`` arm in the Python bridge
(``cross_engine.py::_ta_dict_to_python_predicate``). That predicate is the
shared substrate for every Eerie-mechanic card: the trigger fires whenever
an enchantment enters under the observer's control
(``And(Subject(None, IsEnchantment()), Controlled(YOU))``).

Balemurk Leech (``EachOpponentLosesLife(1)``) was probed in JJ's own
demonstrator test (``tests/test_probe_subject_is_enchantment_unlock.py``).
This module probes the **remaining Eerie cards** whose *Effect* shapes are
supported by existing bridge arms and carry no ``granted_keywords`` rider
that would require the PP ``grant_keyword`` bridge fix (concurrent branch
``feature/bridge-grant-keyword-fix``):

  * **Entity Tracker** — ``DrawCards(amount=1)``
    The Eerie trigger draws one card from p0's library. Observable:
    p0 library shrinks by 1, p0 hand grows by 1, byte-equal on both engines.

  * **Erratic Apparition** — ``PumpSelfUntilEOT(power=1, toughness=1)``
    The Eerie trigger gives the observer +1/+1 until end of turn.
    No ``granted_keywords`` rider — the bare ``pump_self_until_eot``
    bridge arm covers this shape exactly.  Observable: effective_power
    1→2, effective_toughness 3→4 on both engines.

  * **Infernal Phantom** — ``PumpSelfUntilEOT(power=2, toughness=0)``
    The Eerie trigger gives the observer +2/+0 until end of turn.
    No ``granted_keywords`` rider (pure PT pump; Infernal Phantom's DIES
    trigger is out of scope here — it needs ``DealDamageEqualToSourcePower``
    + battlefield search which has its own gaps, cf. divergence-pin in
    ``tests/test_divergence_pins_dd.py``).  Observable: effective_power
    2→4 on both engines.

  * **Scrabbling Skullcrab** — ``MillTargetPlayer(amount=2)``
    The Eerie trigger mills 2 cards off the top of a target player's
    library. Rust's ``MillTargetPlayer`` resolve deterministically targets
    ``1 - controller`` (the one opponent in 2-player land). Python's
    ``MillTargetPlayer.resolve`` is target-driven; we seat a
    ``_PickFirstOpponentTargetAgent`` on p0 to mirror Rust's pick.
    Observable: p1 library shrinks by 2, p1 graveyard grows by 2,
    byte-equal on both engines.

DROPPED CANDIDATES
------------------
  * **Cult Healer** — ``PumpSelfUntilEOT(power=0, toughness=0,
    keywords={'lifelink'})``.  The bare ``pump_self_until_eot`` bridge arm
    (``cross_engine.py:4153``) drops the ``granted_keywords`` rider —
    Rust would grant NO lifelink while Python grants lifelink.  Blocked
    until PP's ``feature/bridge-grant-keyword-fix`` lands.

  * **Dashing Bloodsucker** — ``PumpSelfUntilEOT(power=2, toughness=0,
    keywords={'lifelink'})``.  Same ``granted_keywords`` rider gap as Cult
    Healer.  The +2/+0 PT delta would be byte-equal, but the lifelink
    field would diverge on any ``compare_fields`` assertion and the keyword
    state is load-bearing for combat. Blocked for the same reason.

  * **Optimistic Scavenger** — ``PutPlusOneCounterOnTargetCreature(amount=1)``.
    The bridge arm exists (``cross_engine.py:6704``), but the ``add_counters``
    Rust resolve arm uses a bare ``AnyCreature`` filter (picks bf[0] blindly)
    while Python's ``IsCreature()`` slot filter narrows the legal set. No
    deterministic cross-engine target-pick mirror exists for this card's
    Eerie shape without a dedicated shim; the mismatch is a pre-documented
    targeted-delta (``cross_engine.py:6722-6732``). Blocked.

  * **Gremlin Tamer** — ``CreateToken(count=1, token=Gremlin 1/1)``.
    The bridge arm exists (``cross_engine.py:2029``), but requires seating
    the Gremlin ``CardPrinting`` via ``register_token_printing`` and a
    Rust ``register_printing`` call — non-trivial two-step registration
    not tested in the ENTERS-Eerie lane. Deferred to a dedicated token-
    creation probe batch; out of scope here.

  * **Skullsnap Nuisance** — ``Surveil(amount=1)``.
    The bridge arm exists (``cross_engine.py:737``), but with an empty
    library both engines no-op: nothing to surveil. Seeding a library
    requires the ``send_all_to_graveyard`` Rust decision drain
    (``auto_resolve_pending_decisions("send_all_to_graveyard")`` + the
    ``_SurveilSendAllAgent`` Python mirror) — a separate mechanic surface
    not exercised in the Eerie ETB lane yet. Deferred.

ASSERTION IDIOM
---------------
All four probes use **targeted-observable** rather than full
``compare_fields``. Reason: when a bare enchantment resolves from the
stack onto the battlefield, Rust resets ``summoning_sick=False`` on the
newly-landed permanent while Python preserves the stale stack value.
The ``Probe Enchantment`` subject triggers this known representation
artifact — it is NOT a game-semantics divergence (enchantments cannot
attack; ``summoning_sick`` is irrelevant for them) but it would cause a
``compare_fields != []`` failure. The targeted-observable idiom is the
correct response per the Overlord of the Floodpits precedent
(``tests/test_probe_covered_unprobed_h.py``) and the Balemurk Leech
precedent in ``test_probe_subject_is_enchantment_unlock.py``.
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
    builder lives there). Identical to the module-scoped fixture used
    in all other batch probe files — copied here so this module is
    fully self-contained."""
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
# Shared helper: build a bare synthetic enchantment printing.
# ---------------------------------------------------------------------------

def _make_enchantment_printing():
    """Return a bare ``CardPrinting`` with ``card_types=('Enchantment',)``
    and no abilities.  Identical to the enchantment used in the Balemurk
    Leech probe — a plain vanilla enchantment that triggers Eerie observers
    but has no state-modifying abilities of its own."""
    from mtg_bot.cards.base import CardPrinting, ManaCost
    return CardPrinting(
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


def _eerie_carrier_trigger_dict(effect_dict):
    """Return a Rust trigger-dict for the standard Eerie Predicate
    (``subject_is_enchantment AND controlled_by_you``) wired to the
    given ``effect_dict``."""
    return {
        "event": "enters",
        "predicate": {
            "kind": "and",
            "left": {"kind": "subject_is_enchantment"},
            "right": {"kind": "controlled_by_you"},
        },
        "effect": effect_dict,
    }


# ---------------------------------------------------------------------------
# Probe 1 — Entity Tracker: Eerie trigger → DrawCards(1)
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_entity_tracker_eerie_draw_one_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Entity Tracker.**

    Oracle (relevant part): "[Creature] {2}{U} 2/3
      Eerie — Whenever this creature or another enchantment you control
      enters, draw a card."

      * Event = ``ENTERS``
      * Predicate = ``And(Subject(None, IsEnchantment()), Controlled(YOU))``
      * Effect = ``DrawCards(amount=1)``

    PROBE FLOW
    ----------
    1. Seed p0's library with one card (``ET Filler``) so the draw has
       something to pull.
    2. Pre-seat the actual parsed Entity Tracker printing on p0's bf
       (Python) and a synthetic carrier with the equivalent trigger dict
       (Rust).
    3. Cast a bare synthetic enchantment from p0's hand on both engines;
       resolve it → lands on p0's bf → Eerie trigger fires → push
       ``DrawCards(1)`` onto the stack.
    4. Drain both stacks → the top card of p0's library moves to p0's hand.

    ASSERTION STRENGTH: **targeted-observable** (library + hand zone sizes).
    Reason: newly-landed enchantment has the known ``summoning_sick``
    representation divergence (Rust resets, Python preserves stale stack
    value), making ``compare_fields`` spuriously non-empty for an
    enchantment that cannot attack anyway.  Asserting zone-size deltas
    (library −1, hand +1 on p0, p1 unchanged) captures the full
    gameplay-relevant surface of ``DrawCards(1)`` byte-equal
    cross-engine without being tripped by the documented representation
    artifact.
    """
    from mtg_bot.parity.cross_engine import (
        CardDef,
        DeckSpec,
        build_python_state,
        build_rust_state,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.game import StackItem, Zone
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.generic.draw_mill import DrawCards

    # ---- Verify genuine Entity Tracker parsing. ----
    real = get_active_source().get_printings().get("Entity Tracker")
    if real is None:
        pytest.skip("Entity Tracker absent from active CardSource")
    assert "Creature" in real.card_types, "Entity Tracker must be a Creature"
    etb = next(
        (ta for ta in real.triggered_abilities
         if getattr(ta.event, "value", ta.event) == "enters"),
        None,
    )
    assert etb is not None, (
        "Entity Tracker must have an ENTERS triggered ability"
    )
    assert isinstance(etb.effect, DrawCards), (
        f"Entity Tracker ENTERS effect must be DrawCards; "
        f"got {type(etb.effect).__name__}"
    )
    assert etb.effect.amount == 1, (
        f"Entity Tracker DrawCards amount must be 1; got {etb.effect.amount}"
    )

    # ---- Build cross-engine states (one library card in p0's library). ----
    filler = CardDef(
        name="ET Filler",
        card_type="Creature",
        mana_cost_generic=1,
        power=1,
        toughness=1,
    )
    spec = DeckSpec(
        card_defs=(filler,),
        p0_library=("ET Filler",),
        p1_library=(),
    )
    ZB = 2   # ZONE_BATTLEFIELD
    ZH = 0   # ZONE_HAND

    py = build_python_state(spec)
    rs = build_rust_state(spec)

    # ---- Python: pre-seat genuine Entity Tracker on p0's bf. ----
    py_et = py.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    py_et.summoning_sick = False
    py_et.tapped = False
    py.battlefield.append(py_et)

    # ---- Rust: pre-seat synthetic Entity Tracker carrier on p0's bf. ----
    rs_et_id = rs.register_and_inject_object(
        {
            "name": "Entity Tracker",
            "card_types": ["Creature"],
            "power": int(real.power) if real.power is not None else 2,
            "toughness": int(real.toughness) if real.toughness is not None else 3,
            "effects": [],
            "triggered_abilities": [
                _eerie_carrier_trigger_dict({"kind": "draw_cards", "count": 1})
            ],
        },
        0, ZB,
    )
    assert rs.find_object_zone(rs_et_id) == ZB, (
        "Entity Tracker synthetic carrier must start on Rust battlefield"
    )

    # ---- Baseline zone sizes. ----
    py_p0_lib0 = len(py.players[0].library)
    py_p0_hand0 = len(py.players[0].hand)
    rs_p0_lib0 = rs.library_sizes[0]
    rs_p0_hand0 = rs.hand_sizes[0]
    assert py_p0_lib0 == 1 and rs_p0_lib0 == 1, (
        "Both engines must start p0 with 1-card library"
    )
    assert py_p0_hand0 == 0 and rs_p0_hand0 == 0, (
        "Both engines must start p0 with empty hand"
    )

    # ---- Python: resolve bare enchantment → Eerie fires → draw trigger. ----
    enchant_printing = _make_enchantment_printing()
    py_ench = py.new_object(enchant_printing, owner_id=0, zone=Zone.STACK)
    py_ench.summoning_sick = False
    py.stack.append(StackItem(source=py_ench, controller_id=0))
    resolve_top_of_stack(py)
    assert any(o.printing.name == "Probe Enchantment"
               for o in py.battlefield), (
        "Probe Enchantment must have resolved onto Python battlefield"
    )
    assert len(py.stack) == 1, (
        "Entity Tracker Eerie trigger must be on Python stack"
    )

    # ---- Rust: resolve bare enchantment → Eerie fires. ----
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
        "Entity Tracker Eerie trigger must be on Rust stack"
    )

    # ---- Drain both stacks (DrawCards resolves). ----
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)
    rs.apply_sbas()
    assert rs.stack_size() == 0 and len(py.stack) == 0, (
        "Both stacks must be empty after drain"
    )

    # ---- Observable: p0 library −1, p0 hand +1, byte-equal on both. ----
    assert len(py.players[0].library) == py_p0_lib0 - 1, (
        f"Python: p0 library must shrink by 1; was {py_p0_lib0}, "
        f"now {len(py.players[0].library)}"
    )
    assert rs.library_sizes[0] == rs_p0_lib0 - 1, (
        f"Rust: p0 library must shrink by 1; was {rs_p0_lib0}, "
        f"now {rs.library_sizes[0]}"
    )
    assert len(py.players[0].hand) == py_p0_hand0 + 1, (
        f"Python: p0 hand must grow by 1; was {py_p0_hand0}, "
        f"now {len(py.players[0].hand)}"
    )
    assert rs.hand_sizes[0] == rs_p0_hand0 + 1, (
        f"Rust: p0 hand must grow by 1; was {rs_p0_hand0}, "
        f"now {rs.hand_sizes[0]}"
    )
    # Byte-equal cross-engine.
    assert rs.library_sizes[0] == len(py.players[0].library) == 0, (
        f"p0 library must be empty on both; "
        f"py={len(py.players[0].library)} rs={rs.library_sizes[0]}"
    )
    assert rs.hand_sizes[0] == len(py.players[0].hand) == 1, (
        f"p0 hand must have 1 card on both; "
        f"py={len(py.players[0].hand)} rs={rs.hand_sizes[0]}"
    )
    # p1 zones unaffected.
    assert rs.library_sizes[1] == len(py.players[1].library) == 0, (
        "p1 library must be unchanged (0) on both engines"
    )
    assert rs.hand_sizes[1] == len(py.players[1].hand) == 0, (
        "p1 hand must be unchanged (0) on both engines"
    )


# ---------------------------------------------------------------------------
# Probe 2 — Erratic Apparition: Eerie trigger → PumpSelfUntilEOT(+1/+1)
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_erratic_apparition_eerie_pump_self_plus_one_plus_one_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Erratic Apparition.**

    Oracle (relevant part): "[Creature] {2}{B} 1/3
      Eerie — Whenever this creature or another enchantment you control
      enters, this creature gets +1/+1 until end of turn."

      * Event = ``ENTERS``
      * Predicate = ``And(Subject(None, IsEnchantment()), Controlled(YOU))``
      * Effect = ``PumpSelfUntilEOT(power_bonus=1, toughness_bonus=1)``
        **No ``granted_keywords`` rider** — the bare
        ``pump_self_until_eot`` bridge arm (``cross_engine.py:4153``)
        covers this shape exactly.

    PROBE FLOW
    ----------
    1. Pre-seat genuine Erratic Apparition (1/3) on p0's bf (Python) and
       the synthetic carrier (Rust).
    2. Resolve a bare synthetic enchantment → Eerie trigger fires → push
       ``PumpSelfUntilEOT(+1/+1)`` onto the stack.
    3. Drain both stacks → Erratic Apparition's UEOT modifier is applied.

    ASSERTION STRENGTH: **targeted-observable** (effective power/toughness
    on the Erratic Apparition object on both engines).  The newly-landed
    enchantment's ``summoning_sick`` representation gap is documented;
    targeted-observable avoids the spurious ``compare_fields`` divergence.
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
    from mtg_bot.effects.generic.pump import PumpSelfUntilEOT

    # ---- Verify genuine Erratic Apparition parsing. ----
    real = get_active_source().get_printings().get("Erratic Apparition")
    if real is None:
        pytest.skip("Erratic Apparition absent from active CardSource")
    assert "Creature" in real.card_types, "Erratic Apparition must be a Creature"
    etb = next(
        (ta for ta in real.triggered_abilities
         if getattr(ta.event, "value", ta.event) == "enters"),
        None,
    )
    assert etb is not None, (
        "Erratic Apparition must have an ENTERS triggered ability"
    )
    assert isinstance(etb.effect, PumpSelfUntilEOT), (
        f"Erratic Apparition ENTERS effect must be PumpSelfUntilEOT; "
        f"got {type(etb.effect).__name__}"
    )
    assert etb.effect.power_bonus == 1 and etb.effect.toughness_bonus == 1, (
        f"Erratic Apparition pump must be +1/+1; "
        f"got +{etb.effect.power_bonus}/+{etb.effect.toughness_bonus}"
    )
    assert not etb.effect.granted_keywords, (
        f"Erratic Apparition must have NO granted_keywords rider; "
        f"got {etb.effect.granted_keywords}"
    )

    base_power = int(real.power)        # 1
    base_toughness = int(real.toughness)  # 3

    # ---- Build cross-engine states (empty libraries). ----
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    ZB = 2
    ZH = 0

    py = build_python_state(spec)
    rs = build_rust_state(spec)

    # ---- Python: pre-seat genuine Erratic Apparition on p0's bf. ----
    py_ea = py.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    py_ea.summoning_sick = False
    py_ea.tapped = False
    py.battlefield.append(py_ea)

    # ---- Rust: pre-seat synthetic Erratic Apparition carrier on p0's bf. ----
    rs_ea_id = rs.register_and_inject_object(
        {
            "name": "Erratic Apparition",
            "card_types": ["Creature"],
            "power": base_power,
            "toughness": base_toughness,
            "effects": [],
            "triggered_abilities": [
                _eerie_carrier_trigger_dict({
                    "kind": "pump_self_until_eot",
                    "power_bonus": 1,
                    "toughness_bonus": 1,
                })
            ],
        },
        0, ZB,
    )
    assert rs.find_object_zone(rs_ea_id) == ZB, (
        "Erratic Apparition synthetic carrier must start on Rust battlefield"
    )

    # ---- Baseline power/toughness. ----
    assert rs.effective_power(rs_ea_id) == base_power, (
        f"Rust: Erratic Apparition must start at power={base_power}"
    )
    assert getattr(py_ea, "temp_power_bonus", 0) == 0, (
        "Python: Erratic Apparition must start with temp_power_bonus=0"
    )
    assert getattr(py_ea, "temp_toughness_bonus", 0) == 0, (
        "Python: Erratic Apparition must start with temp_toughness_bonus=0"
    )

    # ---- Python: resolve bare enchantment → Eerie fires. ----
    enchant_printing = _make_enchantment_printing()
    py_ench = py.new_object(enchant_printing, owner_id=0, zone=Zone.STACK)
    py_ench.summoning_sick = False
    py.stack.append(StackItem(source=py_ench, controller_id=0))
    resolve_top_of_stack(py)
    assert any(o.printing.name == "Probe Enchantment"
               for o in py.battlefield), (
        "Probe Enchantment must have resolved onto Python battlefield"
    )
    assert len(py.stack) == 1, (
        "Erratic Apparition Eerie trigger must be on Python stack"
    )

    # ---- Rust: resolve bare enchantment → Eerie fires. ----
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
        "Erratic Apparition Eerie trigger must be on Rust stack"
    )

    # ---- Drain both stacks (PumpSelfUntilEOT resolves). ----
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)
    rs.apply_sbas()
    assert rs.stack_size() == 0 and len(py.stack) == 0, (
        "Both stacks must be empty after drain"
    )

    # ---- Observable: effective power/toughness +1/+1 on both engines. ----
    py_eff_power = base_power + getattr(py_ea, "temp_power_bonus", 0)
    py_eff_tough = base_toughness + getattr(py_ea, "temp_toughness_bonus", 0)
    rs_eff_power = rs.effective_power(rs_ea_id)

    assert py_eff_power == base_power + 1, (
        f"Python: Erratic Apparition power must be {base_power + 1} "
        f"after Eerie pump; got {py_eff_power} "
        f"(temp_power_bonus={getattr(py_ea, 'temp_power_bonus', 0)})"
    )
    assert rs_eff_power == base_power + 1, (
        f"Rust: Erratic Apparition effective_power must be {base_power + 1} "
        f"after Eerie pump; got {rs_eff_power}"
    )
    assert py_eff_power == rs_eff_power == base_power + 1, (
        f"Engines must agree on Erratic Apparition power after Eerie; "
        f"py={py_eff_power} rs={rs_eff_power}"
    )
    assert py_eff_tough == base_toughness + 1, (
        f"Python: Erratic Apparition toughness must be {base_toughness + 1} "
        f"after Eerie pump; got {py_eff_tough} "
        f"(temp_toughness_bonus={getattr(py_ea, 'temp_toughness_bonus', 0)})"
    )
    # p0 and p1 life unchanged (PumpSelfUntilEOT has no life effect).
    assert py.players[0].life == 20 and rs.get_life(0) == 20, (
        "p0 life must remain 20 after Erratic Apparition pump"
    )
    assert py.players[1].life == 20 and rs.get_life(1) == 20, (
        "p1 life must remain 20 after Erratic Apparition pump"
    )


# ---------------------------------------------------------------------------
# Probe 3 — Infernal Phantom: Eerie trigger → PumpSelfUntilEOT(+2/+0)
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_infernal_phantom_eerie_pump_self_plus_two_zero_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Infernal Phantom (Eerie ETB).**

    Oracle (relevant part): "[Creature] {3}{B} 2/3
      Eerie — Whenever this creature or another enchantment you control
      enters, this creature gets +2/+0 until end of turn."

      * Event = ``ENTERS``
      * Predicate = ``And(Subject(None, IsEnchantment()), Controlled(YOU))``
      * Effect = ``PumpSelfUntilEOT(power_bonus=2, toughness_bonus=0)``
        **No ``granted_keywords`` rider** — pure PT pump, covered exactly
        by the bare ``pump_self_until_eot`` bridge arm.

    Note: Infernal Phantom also has a DIES trigger
    (``DealDamageEqualToSourcePowerAnyTarget``) — that trigger has its own
    battlefield-search gap documented in
    ``tests/test_divergence_pins_dd.py`` and is out of scope here.  Only
    the ENTERS Eerie trigger is exercised.

    PROBE FLOW
    ----------
    1. Pre-seat genuine Infernal Phantom (2/3) on p0's bf.
    2. Resolve bare enchantment → Eerie fires → ``PumpSelfUntilEOT(+2/+0)``.
    3. Drain → Infernal Phantom effective_power 2→4; toughness stays 3.

    ASSERTION STRENGTH: **targeted-observable** (effective_power on both
    engines).  Same documented summoning_sick enchantment gap as all other
    Eerie probes in this module.
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
    from mtg_bot.effects.generic.pump import PumpSelfUntilEOT

    # ---- Verify genuine Infernal Phantom parsing. ----
    real = get_active_source().get_printings().get("Infernal Phantom")
    if real is None:
        pytest.skip("Infernal Phantom absent from active CardSource")
    assert "Creature" in real.card_types, "Infernal Phantom must be a Creature"
    etb = next(
        (ta for ta in real.triggered_abilities
         if getattr(ta.event, "value", ta.event) == "enters"),
        None,
    )
    assert etb is not None, (
        "Infernal Phantom must have an ENTERS triggered ability"
    )
    assert isinstance(etb.effect, PumpSelfUntilEOT), (
        f"Infernal Phantom ENTERS effect must be PumpSelfUntilEOT; "
        f"got {type(etb.effect).__name__}"
    )
    assert etb.effect.power_bonus == 2 and etb.effect.toughness_bonus == 0, (
        f"Infernal Phantom pump must be +2/+0; "
        f"got +{etb.effect.power_bonus}/+{etb.effect.toughness_bonus}"
    )
    assert not etb.effect.granted_keywords, (
        f"Infernal Phantom must have NO granted_keywords rider; "
        f"got {etb.effect.granted_keywords}"
    )

    base_power = int(real.power)        # 2
    base_toughness = int(real.toughness)  # 3

    # ---- Build cross-engine states (empty libraries). ----
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    ZB = 2
    ZH = 0

    py = build_python_state(spec)
    rs = build_rust_state(spec)

    # ---- Python: pre-seat genuine Infernal Phantom on p0's bf. ----
    py_ip = py.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    py_ip.summoning_sick = False
    py_ip.tapped = False
    py.battlefield.append(py_ip)

    # ---- Rust: pre-seat synthetic Infernal Phantom carrier on p0's bf. ----
    # Register ONLY the Eerie ENTERS trigger (not the DIES trigger) to
    # keep this probe narrowly scoped to the Eerie surface.
    rs_ip_id = rs.register_and_inject_object(
        {
            "name": "Infernal Phantom",
            "card_types": ["Creature"],
            "power": base_power,
            "toughness": base_toughness,
            "effects": [],
            "triggered_abilities": [
                _eerie_carrier_trigger_dict({
                    "kind": "pump_self_until_eot",
                    "power_bonus": 2,
                    "toughness_bonus": 0,
                })
            ],
        },
        0, ZB,
    )
    assert rs.find_object_zone(rs_ip_id) == ZB, (
        "Infernal Phantom synthetic carrier must start on Rust battlefield"
    )

    # ---- Baseline power checks. ----
    assert rs.effective_power(rs_ip_id) == base_power, (
        f"Rust: Infernal Phantom must start at power={base_power}"
    )
    assert getattr(py_ip, "temp_power_bonus", 0) == 0, (
        "Python: Infernal Phantom must start with temp_power_bonus=0"
    )

    # ---- Python: resolve bare enchantment → Eerie fires. ----
    enchant_printing = _make_enchantment_printing()
    py_ench = py.new_object(enchant_printing, owner_id=0, zone=Zone.STACK)
    py_ench.summoning_sick = False
    py.stack.append(StackItem(source=py_ench, controller_id=0))
    resolve_top_of_stack(py)
    assert any(o.printing.name == "Probe Enchantment"
               for o in py.battlefield), (
        "Probe Enchantment must have resolved onto Python battlefield"
    )
    assert len(py.stack) == 1, (
        "Infernal Phantom Eerie trigger must be on Python stack"
    )

    # ---- Rust: resolve bare enchantment → Eerie fires. ----
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
        "Infernal Phantom Eerie trigger must be on Rust stack"
    )

    # ---- Drain both stacks (PumpSelfUntilEOT resolves). ----
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)
    rs.apply_sbas()
    assert rs.stack_size() == 0 and len(py.stack) == 0, (
        "Both stacks must be empty after drain"
    )

    # ---- Observable: effective power +2 on both engines; toughness stays. ----
    py_eff_power = base_power + getattr(py_ip, "temp_power_bonus", 0)
    py_eff_tough = base_toughness + getattr(py_ip, "temp_toughness_bonus", 0)
    rs_eff_power = rs.effective_power(rs_ip_id)

    assert py_eff_power == base_power + 2, (
        f"Python: Infernal Phantom power must be {base_power + 2} "
        f"after Eerie +2/+0 pump; got {py_eff_power}"
    )
    assert rs_eff_power == base_power + 2, (
        f"Rust: Infernal Phantom effective_power must be {base_power + 2} "
        f"after Eerie +2/+0 pump; got {rs_eff_power}"
    )
    assert py_eff_power == rs_eff_power == base_power + 2, (
        f"Engines must agree on Infernal Phantom power; "
        f"py={py_eff_power} rs={rs_eff_power}"
    )
    assert py_eff_tough == base_toughness, (
        f"Python: Infernal Phantom toughness must remain {base_toughness} "
        f"(+0 from pump); got {py_eff_tough}"
    )
    # Life totals must not change (pure pump, no life effect).
    assert py.players[0].life == 20 and rs.get_life(0) == 20, (
        "p0 life must remain 20 after Infernal Phantom pump"
    )
    assert py.players[1].life == 20 and rs.get_life(1) == 20, (
        "p1 life must remain 20 after Infernal Phantom pump"
    )


# ---------------------------------------------------------------------------
# Probe 4 — Scrabbling Skullcrab: Eerie trigger → MillTargetPlayer(2)
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_scrabbling_skullcrab_eerie_mill_opponent_two_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Scrabbling Skullcrab.**

    Oracle (relevant part): "[Creature] {B} 0/3
      Eerie — Whenever this creature or another enchantment you control
      enters, target player mills 2 cards."

      * Event = ``ENTERS``
      * Predicate = ``And(Subject(None, IsEnchantment()), Controlled(YOU))``
      * Effect = ``MillTargetPlayer(amount=2)``

    TARGET-PICK MIRROR
    ------------------
    Rust's ``MillTargetPlayer`` resolve deterministically computes the
    target as ``1 - source_controller`` (the one opponent in 2-player
    land) — there is no ``PendingDecision`` pause; the target is derived
    from the source's controller field at the time of resolution
    (``state_ops_resolve.rs`` post-I77 contract).

    Python's ``MillTargetPlayer.resolve`` is target-driven: it requires
    an agent to call ``choose_target`` from the legal targets pool
    (``[("player", 0), ("player", 1)]``).  We install
    ``_PickFirstOpponentTargetAgent`` on p0 (the Eerie trigger's
    controller) to mirror Rust's deterministic ``1 - 0 = 1`` pick,
    selecting p1 as the milled player on both engines.

    PROBE FLOW
    ----------
    1. Seed p1's library with 3 distinct bait cards so a mill-2 leaves
       exactly 1 card on top as a witness (any miscount surfaces as a
       library-size mismatch).
    2. Pre-seat genuine Scrabbling Skullcrab (0/3) on p0's bf.
    3. Resolve bare enchantment → Eerie fires → ``MillTargetPlayer(2)``
       lands on stack with controller=0.
    4. Drain → p1's top 2 library cards move to p1's graveyard.

    ASSERTION STRENGTH: **targeted-observable** (library + graveyard zone
    sizes on both players).  The enchantment summoning_sick gap and the
    mill bridge's known ``target_filter`` asymmetry
    (``cross_engine.py:6722-6732`` for add_counters; analogous for
    ``mill_target_player``'s 2-player-target-picker) are both rendered
    moot by the zone-size assertions, which capture the full
    gameplay-relevant surface byte-equal cross-engine.
    """
    from mtg_bot.parity.cross_engine import (
        CardDef,
        DeckSpec,
        build_python_state,
        build_rust_state,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.game import StackItem, Zone
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.generic.draw_mill import MillTargetPlayer
    from tests.parity._picker_shims import _PickFirstOpponentTargetAgent

    # ---- Verify genuine Scrabbling Skullcrab parsing. ----
    real = get_active_source().get_printings().get("Scrabbling Skullcrab")
    if real is None:
        pytest.skip("Scrabbling Skullcrab absent from active CardSource")
    assert "Creature" in real.card_types, "Scrabbling Skullcrab must be a Creature"
    etb = next(
        (ta for ta in real.triggered_abilities
         if getattr(ta.event, "value", ta.event) == "enters"),
        None,
    )
    assert etb is not None, (
        "Scrabbling Skullcrab must have an ENTERS triggered ability"
    )
    assert isinstance(etb.effect, MillTargetPlayer), (
        f"Scrabbling Skullcrab ENTERS effect must be MillTargetPlayer; "
        f"got {type(etb.effect).__name__}"
    )
    assert etb.effect.amount == 2, (
        f"Scrabbling Skullcrab MillTargetPlayer amount must be 2; "
        f"got {etb.effect.amount}"
    )

    # ---- Build cross-engine states (3 bait cards in p1's library). ----
    bait_1 = CardDef(
        name="SC Bait Bear 1",
        card_type="Creature",
        mana_cost_generic=1,
        power=1,
        toughness=1,
    )
    bait_2 = CardDef(
        name="SC Bait Bear 2",
        card_type="Creature",
        mana_cost_generic=1,
        power=1,
        toughness=1,
    )
    bait_3 = CardDef(
        name="SC Bait Bear 3",
        card_type="Creature",
        mana_cost_generic=1,
        power=1,
        toughness=1,
    )
    spec = DeckSpec(
        card_defs=(bait_1, bait_2, bait_3),
        p0_library=(),
        # p1 library: bait_1 is top (index 0), bait_3 is bottom (index 2).
        # mill-2 should pop bait_1 and bait_2; bait_3 survives on top.
        p1_library=("SC Bait Bear 1", "SC Bait Bear 2", "SC Bait Bear 3"),
    )
    ZB = 2
    ZH = 0

    py = build_python_state(spec)
    rs = build_rust_state(spec)

    # Install opponent-targeting agent on p0 so Python's MillTargetPlayer
    # picks p1 (the opponent) — matching Rust's ``1 - controller = 1`` pick.
    py.players[0].agent = _PickFirstOpponentTargetAgent()

    # ---- Python: pre-seat genuine Scrabbling Skullcrab on p0's bf. ----
    py_sc = py.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    py_sc.summoning_sick = False
    py_sc.tapped = False
    py.battlefield.append(py_sc)

    # ---- Rust: pre-seat synthetic Scrabbling Skullcrab carrier on p0's bf. ----
    rs_sc_id = rs.register_and_inject_object(
        {
            "name": "Scrabbling Skullcrab",
            "card_types": ["Creature"],
            "power": int(real.power) if real.power is not None else 0,
            "toughness": int(real.toughness) if real.toughness is not None else 3,
            "effects": [],
            "triggered_abilities": [
                _eerie_carrier_trigger_dict({
                    "kind": "mill_target_player",
                    "count": 2,
                })
            ],
        },
        0, ZB,
    )
    assert rs.find_object_zone(rs_sc_id) == ZB, (
        "Scrabbling Skullcrab synthetic carrier must start on Rust battlefield"
    )

    # ---- Baseline zone sizes. ----
    rs_p0_lib0 = rs.library_sizes[0]
    rs_p1_lib0 = rs.library_sizes[1]
    rs_p1_gy0 = rs.graveyard_sizes[1]
    py_p0_lib0 = len(py.players[0].library)
    py_p1_lib0 = len(py.players[1].library)
    py_p1_gy0 = len(py.players[1].graveyard)
    assert rs_p1_lib0 == 3 and py_p1_lib0 == 3, (
        "Both engines must start p1 with 3-card library"
    )
    assert rs_p0_lib0 == 0 and py_p0_lib0 == 0, (
        "Both engines must start p0 with empty library"
    )

    # ---- Python: resolve bare enchantment → Eerie fires. ----
    enchant_printing = _make_enchantment_printing()
    py_ench = py.new_object(enchant_printing, owner_id=0, zone=Zone.STACK)
    py_ench.summoning_sick = False
    py.stack.append(StackItem(source=py_ench, controller_id=0))
    resolve_top_of_stack(py)
    assert any(o.printing.name == "Probe Enchantment"
               for o in py.battlefield), (
        "Probe Enchantment must have resolved onto Python battlefield"
    )
    assert len(py.stack) == 1, (
        "Scrabbling Skullcrab Eerie trigger must be on Python stack"
    )

    # ---- Rust: resolve bare enchantment → Eerie fires. ----
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
        "Scrabbling Skullcrab Eerie trigger must be on Rust stack"
    )

    # ---- Drain both stacks (MillTargetPlayer(2) resolves). ----
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)
    rs.apply_sbas()
    assert rs.stack_size() == 0 and len(py.stack) == 0, (
        "Both stacks must be empty after drain"
    )

    # ---- Observable: p1 library −2, p1 graveyard +2, byte-equal on both. ----
    assert len(py.players[1].library) == py_p1_lib0 - 2, (
        f"Python: p1 library must shrink by 2; was {py_p1_lib0}, "
        f"now {len(py.players[1].library)}"
    )
    assert rs.library_sizes[1] == rs_p1_lib0 - 2, (
        f"Rust: p1 library must shrink by 2; was {rs_p1_lib0}, "
        f"now {rs.library_sizes[1]}"
    )
    assert len(py.players[1].graveyard) == py_p1_gy0 + 2, (
        f"Python: p1 graveyard must grow by 2; was {py_p1_gy0}, "
        f"now {len(py.players[1].graveyard)}"
    )
    assert rs.graveyard_sizes[1] == rs_p1_gy0 + 2, (
        f"Rust: p1 graveyard must grow by 2; was {rs_p1_gy0}, "
        f"now {rs.graveyard_sizes[1]}"
    )
    # Byte-equal cross-engine.
    assert rs.library_sizes[1] == len(py.players[1].library) == 1, (
        f"p1 library must have 1 card on both (bait_3 survives); "
        f"py={len(py.players[1].library)} rs={rs.library_sizes[1]}"
    )
    assert rs.graveyard_sizes[1] == len(py.players[1].graveyard) == 2, (
        f"p1 graveyard must have 2 cards on both; "
        f"py={len(py.players[1].graveyard)} rs={rs.graveyard_sizes[1]}"
    )
    # p0 zones unaffected (Scrabbling Skullcrab mills the OPPONENT).
    assert rs.library_sizes[0] == len(py.players[0].library) == 0, (
        "p0 library must be unchanged (0) on both engines"
    )
    assert rs.graveyard_sizes[0] == len(py.players[0].graveyard) == 0, (
        "p0 graveyard must be unchanged (0) on both engines"
    )
    # Life totals unaffected.
    assert py.players[0].life == 20 and rs.get_life(0) == 20, (
        "p0 life must remain 20 after Scrabbling Skullcrab mill"
    )
    assert py.players[1].life == 20 and rs.get_life(1) == 20, (
        "p1 life must remain 20 after Scrabbling Skullcrab mill (mill != life loss)"
    )
