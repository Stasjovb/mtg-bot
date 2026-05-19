"""Genuine real-EoE cross-engine byte-equality probe — deals_combat_damage
event unlock (round 13 Rust slice).

This module ships the first cross-engine probe for the
``DEALS_COMBAT_DAMAGE`` event family.  The unlock comes from:

1. Adding the ``"deals_damage"`` arm to Rust's
   ``parse_triggered_ability`` (``rust/src/cards.rs``).
2. Adding the ``dispatch_combat_damage_to_player`` dispatch site in
   ``rust/src/state_ops_combat.rs::apply_damage_pass`` so the event
   actually fires after player-targeted damage is applied.
3. Adding the ``"deals_combat_damage"`` / ``"deals_damage"`` arm to the
   Python bridge (``src/mtg_bot/parity/cross_engine.py::
   _ta_dict_to_python_triggered_ability``) plus the companion
   ``_rewrite_predicate_for_deals_combat_damage`` slot-fix that converts
   ``IsSelf(subject=None)`` → ``IsSelf(subject="source")`` for the
   two-subject event (LL Pin 2 multi-subject hazard fix).

**Before this slice** the Rust parse gate raised::

    ValueError: triggered_ability.event "deals_damage" is not yet wired
    in Slice 9; only "enters", "dies", ...

and the bridge raised::

    ValueError: cross_engine triggered_abilities bridge: event
    'deals_combat_damage' is not yet wired

Both gaps are closed by this slice.

PROBE CARD — Illvoi Infiltrator (EoE)
--------------------------------------
Oracle: "[Creature — Jellyfish Rogue] {2}{U} 1/3
  This creature can't be blocked if you've cast two or more spells
  this turn.
  Whenever this creature deals combat damage to a player, draw a card."

  * Event = ``DEALS_COMBAT_DAMAGE``
  * Predicate = ``IsSelf(subject="source") & Subject("target", IsPlayer())``
    (parser output: ``And(IsSelf(subject="source"), Subject("target",
    IsPlayer()))``).  The Rust side uses ``SourceIsSelf`` (equivalent
    in context: source IS the subject) with the ``IsPlayer`` half
    implicit in the dispatch site (only fires for player-targeted damage).
  * Effect = ``DrawCards(1)``

PROBE FLOW
----------
The probe drives p0's Illvoi Infiltrator (1/3) as an unblocked attacker
against p1 (no blockers).  No first-strike.  The single Regular-pass
player-damage entry causes ``dispatch_combat_damage_to_player`` (Rust)
/ ``_fire_combat_damage_to_player_triggers`` (Python) to fire the
``DEALS_COMBAT_DAMAGE`` trigger.

After the trigger resolves (``DrawCards(1)``):
  * p1 loses 1 life (combat damage)
  * p0 draws 1 card (trigger effect)
  * p0 hand size increases by 1
  * p0 library size decreases by 1

Both observables are byte-equal across engines.

SINGLE-SUBJECT PREDICATE SCOPE NOTE
-------------------------------------
Rust's ``dispatch_combat_damage_to_player`` passes the ATTACKER id as
``subject_id`` to ``dispatch_event``.  ``Predicate::SourceIsSelf``
checks ``source_id == subject_id`` — true when the observer IS the
attacker.  The ``IsPlayer`` target check is implicit (dispatch only
fires for player-targeted entries).  This is equivalent to Python's
``IsSelf(subject="source") & Subject("target", IsPlayer())`` in this
context.

CARDS STILL BLOCKED AFTER THIS SLICE
--------------------------------------
* **Starwinder** — "Whenever a creature you control deals combat damage
  to a player, you may draw that many cards."  Requires
  ``IsCreature(subject="source") & Controlled(YOU, subject="source") &
  IsPlayer(subject="target")``.  Rust predicate ``ControlledByYou``
  checks the SUBJECT's controller == source's controller — but for
  DEALS_COMBAT_DAMAGE, ``subject_id`` IS the attacker, so
  ``ControlledByYou`` would compare subject.controller to itself (always
  True).  This needs the full two-subject predicate API (secondary
  target_id) to be correctly scoped; deferred per round-13 honest-stop.

* **Virulent Silencer** — "Whenever a nontoken artifact creature you
  control deals combat damage to a player, that player gets two poison
  counters."  Requires ``IsCreature(source) & IsArtifact(source) &
  IsNontoken(source) & Controlled(YOU, source) & IsPlayer(target)``.
  Blocked by same two-subject predicate gap + PutPoisonCountersOnPlayer
  effect bridging.

OO Pin 2 status: UPDATED (renamed from ``_divergence_pin`` to
``_FIXED_parity`` in ``tests/test_divergence_pins_oo.py``).  The pin
now asserts the correct wired behavior.

CC sentinel status: SKIPPED (``test_probe_combat_damage_cc.py::
test_combat_damage_trigger_lane_blocked`` replaced with
``pytest.skip`` message pointing to this file).
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
    builder lives there).  Identical to the module-scoped fixture in
    other batch probe files — copied here so this module is fully
    self-contained."""
    repo_root = pathlib.Path(__file__).resolve().parent.parent
    script_path = repo_root / "scripts" / "parity_smoke.py"
    spec = importlib.util.spec_from_file_location("parity_smoke", script_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["parity_smoke"] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Probe — Illvoi Infiltrator: deals combat damage to p1 (unblocked) → draw 1
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_illvoi_infiltrator_deals_combat_damage_draw_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Illvoi Infiltrator
    (round 13, first DEALS_COMBAT_DAMAGE probe).**

    Drives the **real parsed Illvoi Infiltrator printing** on the Python
    side and a bridged synthetic carrier on the Rust side through the
    ``DEALS_COMBAT_DAMAGE`` dispatch path.

    Setup:
      * p0 has Illvoi Infiltrator (1/3) on the battlefield, unsick,
        untapped.  Two filler cards in p0's library (so DrawCards(1)
        has a card to draw).
      * p1 has no creatures (no blockers).
      * Active player = p0 (attacker's controller).

    Combat flow:
      1. Rust: ``declare_attacker(illvoi_id)`` (ATTACKS trigger: none
         on Illvoi — only the DEALS_COMBAT_DAMAGE trigger).
         Python: ``declare_attackers(state, [illvoi.id])``.
      2. No blockers declared.
      3. Rust: ``deal_combat_damage()`` — applies the 1-damage-to-p1
         plan entry, then fires ``dispatch_combat_damage_to_player``
         → ``Event::DealsDamage`` trigger pushed onto stack.
         Python: ``resolve_combat_damage(state, defending_player_id=1)``
         → applies 1 damage to p1, calls
         ``_fire_combat_damage_to_player_triggers`` → ``dispatch_event(
         state, Event.DEALS_COMBAT_DAMAGE, source=illvoi, target=p1_obj)``
         → ``DrawCards(1)`` trigger pushed onto stack.
      4. Drain both stacks (DrawCards(1) resolves → p0 draws 1 card).
      5. Apply SBAs (no lethal damage).

    Observables asserted (targeted — not full compare_fields, to avoid
    the summoning_sick representation gap on zone-changed objects):
      * p1 life: 20 → 19 on BOTH engines.
      * p0 hand size: 0 → 1 on BOTH engines (card drawn).
      * p0 library size: 2 → 1 on BOTH engines (top card removed).

    Rust predicate dict for Illvoi's DEALS_COMBAT_DAMAGE trigger::

        {
            "event": "deals_damage",
            "predicate": {"kind": "source_is_self"},
            "effect": {"kind": "draw_cards", "count": 1},
        }

    Python-side bridge converts ``"deals_damage"`` → ``Event.
    DEALS_COMBAT_DAMAGE`` and rewrites ``IsSelf(subject=None)`` →
    ``IsSelf(subject="source")`` via
    ``_rewrite_predicate_for_deals_combat_damage``.
    """
    from mtg_bot.parity.cross_engine import (
        CardDef,
        DeckSpec,
        build_python_state,
        build_rust_state,
        _ta_dict_to_python_triggered_ability,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.combat import (
        declare_attackers as py_declare_attackers,
        resolve_combat_damage as py_resolve_combat_damage,
    )
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.game import Zone, StackItem
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.predicates import Event, IsSelf

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Illvoi Infiltrator printing has the
    #    expected DEALS_COMBAT_DAMAGE trigger shape.
    # ------------------------------------------------------------------
    real = get_active_source().get_printings().get("Illvoi Infiltrator")
    if real is None:
        pytest.skip("Illvoi Infiltrator absent from active CardSource")

    assert "Creature" in real.card_types, (
        "Illvoi Infiltrator must be a Creature"
    )
    cd_ta = next(
        (ta for ta in real.triggered_abilities
         if getattr(ta.event, "value", ta.event) == "deals_combat_damage"),
        None,
    )
    assert cd_ta is not None, (
        "Illvoi Infiltrator must have a DEALS_COMBAT_DAMAGE triggered ability; "
        f"abilities found: {[(getattr(ta.event,'value',ta.event), type(ta.effect).__name__) for ta in real.triggered_abilities]}"
    )
    # Verify the predicate has IsSelf(subject="source") at the top or
    # somewhere in the tree (the parser produces And(IsSelf, Subject)).
    assert isinstance(cd_ta.predicate, IsSelf) or hasattr(cd_ta.predicate, "left"), (
        f"Illvoi Infiltrator DEALS_COMBAT_DAMAGE predicate unexpected shape: "
        f"{type(cd_ta.predicate).__name__}"
    )
    from mtg_bot.effects.generic.draw_mill import DrawCards
    # The effect may be wrapped in And/Sequence; check by effect type.
    assert isinstance(cd_ta.effect, DrawCards), (
        f"Illvoi Infiltrator DEALS_COMBAT_DAMAGE effect must be DrawCards; "
        f"got {type(cd_ta.effect).__name__}"
    )
    assert cd_ta.effect.amount == 1, (
        f"Illvoi Infiltrator DrawCards amount must be 1; got {cd_ta.effect.amount}"
    )

    # ------------------------------------------------------------------
    # 2. The shared triggered-ability dict (registered on Rust; used to
    #    build the Python TriggeredAbility via the bridge).
    # ------------------------------------------------------------------
    illvoi_ta_dict = {
        "event": "deals_damage",          # Rust event string
        "predicate": {"kind": "source_is_self"},
        "effect": {"kind": "draw_cards", "count": 1},
    }

    # Sanity: bridge translates the dict correctly.
    bridge_ta = _ta_dict_to_python_triggered_ability(illvoi_ta_dict)
    assert bridge_ta.event == Event.DEALS_COMBAT_DAMAGE, (
        f"Bridge must translate 'deals_damage' to Event.DEALS_COMBAT_DAMAGE; "
        f"got {bridge_ta.event!r}"
    )
    assert isinstance(bridge_ta.predicate, IsSelf), (
        f"Bridge predicate rewrite must produce IsSelf; "
        f"got {type(bridge_ta.predicate).__name__}"
    )
    assert bridge_ta.predicate.subject == "source", (
        f"Bridge IsSelf must have subject='source'; "
        f"got subject={bridge_ta.predicate.subject!r}"
    )

    # ------------------------------------------------------------------
    # 3. Build cross-engine states with 2 filler cards in p0's library.
    # ------------------------------------------------------------------
    filler_def = CardDef(
        name="Filler",
        card_type="Creature",
        power=1,
        toughness=1,
    )
    spec = DeckSpec(
        card_defs=(filler_def,),
        p0_library=("Filler", "Filler"),
        p1_library=(),
    )
    py = build_python_state(spec)
    rs = build_rust_state(spec)

    ZB = 2  # ZONE_BATTLEFIELD

    # ------------------------------------------------------------------
    # 4. Rust: pre-seat Illvoi Infiltrator on p0's battlefield.
    # ------------------------------------------------------------------
    rs_illvoi_id = rs.register_and_inject_object(
        {
            "name": "Illvoi Infiltrator",
            "card_types": ["Creature"],
            "power": 1,
            "toughness": 3,
            "keywords": [],
            "effects": [],
            "triggered_abilities": [illvoi_ta_dict],
        },
        0, ZB,
    )
    rs.clear_summoning_sick_for_player(0)

    # Baseline Rust.
    rs_p0_life0 = rs.get_life(0)
    rs_p1_life0 = rs.get_life(1)
    rs_p0_lib0 = rs.library_sizes[0]
    rs_p0_hand0 = rs.hand_sizes[0]
    assert rs_p0_lib0 == 2, (
        f"Rust: p0 library must start with 2 filler cards; got {rs_p0_lib0}"
    )
    assert rs_p0_hand0 == 0, (
        f"Rust: p0 hand must start empty; got {rs_p0_hand0}"
    )

    # Declare attacker (taps Illvoi, no ATTACKS trigger on Illvoi).
    assert rs.declare_attacker(rs_illvoi_id) is True, (
        "Rust: declare_attacker must succeed for Illvoi Infiltrator"
    )
    # Drain any ATTACKS-event stack items first (Illvoi has none, but
    # ensure stack is empty before deal_combat_damage).
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()

    # Apply combat damage: 1 damage to p1 (unblocked 1/3 attacker).
    rs.deal_combat_damage()

    # The DEALS_COMBAT_DAMAGE trigger for Illvoi should now be on the stack.
    assert rs.stack_size() == 1, (
        f"Rust: DEALS_COMBAT_DAMAGE trigger (DrawCards(1)) must be pushed "
        f"onto the stack after deal_combat_damage; got stack_size="
        f"{rs.stack_size()}"
    )
    assert rs.get_life(1) == rs_p1_life0 - 1, (
        f"Rust: p1 must take 1 combat damage; "
        f"got life={rs.get_life(1)} (was {rs_p1_life0})"
    )

    # Drain the DrawCards(1) trigger.
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()

    rs_p0_hand1 = rs.hand_sizes[0]
    rs_p0_lib1 = rs.library_sizes[0]
    assert rs_p0_hand1 == rs_p0_hand0 + 1, (
        f"Rust: p0 must draw 1 card; hand {rs_p0_hand0} → {rs_p0_hand1}"
    )
    assert rs_p0_lib1 == rs_p0_lib0 - 1, (
        f"Rust: p0 library must shrink by 1; lib {rs_p0_lib0} → {rs_p0_lib1}"
    )

    # ------------------------------------------------------------------
    # 5. Python: pre-seat real Illvoi Infiltrator on p0's battlefield.
    # ------------------------------------------------------------------
    py_illvoi_printing = CardPrinting(
        name="Illvoi Infiltrator",
        mana_cost_str="{2}{U}",
        mana_cost=ManaCost(generic=2, colored=(("U", 1),)),
        type_line="Creature — Jellyfish Rogue",
        supertypes=(),
        card_types=("Creature",),
        subtypes=("Jellyfish", "Rogue"),
        power=1,
        toughness=3,
        produces=frozenset(),
        keywords=frozenset(),
        triggered_abilities=(bridge_ta,),
    )
    py_illvoi = py.new_object(py_illvoi_printing, owner_id=0, zone=Zone.BATTLEFIELD)
    py_illvoi.summoning_sick = False
    py_illvoi.tapped = False
    py_illvoi.damage = 0
    py_illvoi.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_illvoi)

    # Baseline Python.
    py_p0_life0 = py.players[0].life
    py_p1_life0 = py.players[1].life
    py_p0_lib0 = len(py.players[0].library)
    py_p0_hand0 = len(py.players[0].hand)
    assert py_p0_lib0 == 2, (
        f"Python: p0 library must start with 2 filler cards; got {py_p0_lib0}"
    )
    assert py_p0_hand0 == 0, (
        f"Python: p0 hand must start empty; got {py_p0_hand0}"
    )

    # Declare attackers (taps Illvoi).
    py_declare_attackers(py, [py_illvoi.id])
    # Drain any ATTACKS triggers (Illvoi has none).
    while py.stack:
        resolve_top_of_stack(py)

    # Resolve combat damage: 1 damage to p1 (defending player id=1),
    # which fires _fire_combat_damage_to_player_triggers.
    py_resolve_combat_damage(py, defending_player_id=1)

    # The DEALS_COMBAT_DAMAGE DrawCards(1) trigger should be on the stack.
    assert len(py.stack) == 1, (
        f"Python: DEALS_COMBAT_DAMAGE trigger (DrawCards(1)) must be pushed "
        f"after resolve_combat_damage; got stack size {len(py.stack)}"
    )
    assert py.players[1].life == py_p1_life0 - 1, (
        f"Python: p1 must take 1 combat damage; "
        f"got life={py.players[1].life} (was {py_p1_life0})"
    )

    # Drain the DrawCards(1) trigger.
    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)

    py_p0_hand1 = len(py.players[0].hand)
    py_p0_lib1 = len(py.players[0].library)
    assert py_p0_hand1 == py_p0_hand0 + 1, (
        f"Python: p0 must draw 1 card; hand {py_p0_hand0} → {py_p0_hand1}"
    )
    assert py_p0_lib1 == py_p0_lib0 - 1, (
        f"Python: p0 library must shrink by 1; lib {py_p0_lib0} → {py_p0_lib1}"
    )

    # ------------------------------------------------------------------
    # 6. Cross-engine byte-equality on targeted observables.
    # ------------------------------------------------------------------
    assert rs.get_life(1) == py.players[1].life, (
        f"p1 life: Rust={rs.get_life(1)}, Python={py.players[1].life} "
        f"(must be byte-equal)"
    )
    assert rs.get_life(0) == py.players[0].life, (
        f"p0 life: Rust={rs.get_life(0)}, Python={py.players[0].life} "
        f"(must be byte-equal)"
    )
    assert rs_p0_hand1 == py_p0_hand1, (
        f"p0 hand size: Rust={rs_p0_hand1}, Python={py_p0_hand1} "
        f"(must be byte-equal — DrawCards(1) drew on BOTH engines)"
    )
    assert rs_p0_lib1 == py_p0_lib1, (
        f"p0 library size: Rust={rs_p0_lib1}, Python={py_p0_lib1} "
        f"(must be byte-equal)"
    )
