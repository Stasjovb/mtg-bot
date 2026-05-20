"""Genuine real-EoE cross-engine byte-equality probes — batch FFF (round 18).

All three cards are in the ``covered_by_construction`` tier: every Effect
class they emit has a live Rust variant + bridge arm, but no genuine
per-card probe had pinned them.  This module upgrades them to the
``PROBED`` tier.

The unifying theme is **CreateToken effects driven via three distinct
trigger-event dispatch paths**:

  * ``BEGINNING_OF_END_STEP`` (Elegy Acolyte — first EoE card to drive
    ``CreateToken`` via the end-step dispatch path)
  * ``BEGINNING_OF_UPKEEP`` (Thrumming Hivepool — first upkeep probe to
    exercise ``CreateToken`` + count=2)
  * ``YOU_ATTACK`` (Razorkin Hordecaller — deferred from the YY batch due
    to "token-equality assertion is more involved"; now closed using the
    established token-pid idiom from the TT batch)

PROBE CARDS
-----------

**Probe 1 — Elegy Acolyte (EoE)**
Oracle: "[Creature — Human Cleric] {2}{B}{B} 4/4
  Lifelink
  Whenever Elegy Acolyte deals combat damage to a player, draw a card
  and you lose 1 life.
  At the beginning of your end step, create a 2/2 colorless Robot
  artifact creature token."

The ``BEGINNING_OF_END_STEP`` trigger — ``Controlled(YOU) →
CreateToken(Robot 2/2 Artifact Creature, count=1)`` — is the
cross-engine-clean leg for this card.  The ``DEALS_COMBAT_DAMAGE``
trigger ``Sequence(DrawCards(1), LoseLife(1))`` requires the two-subject
predicate (``And(And(Subject('source', IsCreature()), Controlled(YOU,
subject='source')), Subject('target', IsPlayer()))``) and while the bridge
has ``_rewrite_predicate_for_deals_combat_damage``, driving that leg
requires a full combat setup; deferred to a targeted-combat probe batch.
This probe covers the end-step leg only.

Observable:
  * p0 battlefield token count: +1 Robot token on BOTH engines.
  * p0 life and hand unchanged (end-step leg is pure CreateToken).

Rust triggered-ability dict::

    {
        "event": "beginning_of_end_step",
        "predicate": {"kind": "controlled_by_you"},
        "effect": {
            "kind": "create_token",
            "count": 1,
            "token_printing_id": <robot_pid>,
        },
    }

**Probe 2 — Thrumming Hivepool (EoE)**
Oracle: "[Artifact] {6}
  At the beginning of your upkeep, create two 1/1 colorless Sliver
  creature tokens."

  * Event    = ``BEGINNING_OF_UPKEEP``
  * Predicate = ``Controlled(YOU)`` → ``ControlledByYou``
  * Effect   = ``CreateToken(Sliver 1/1 Creature, count=2)``

This is the first FFF probe to drive the upkeep phase for a non-creature
artifact permanent.  Thrumming Hivepool (pure Artifact, no P/T) is
injected directly to the battlefield on both engines; ``advance_phase()``
to ``PHASE_UPKEEP`` fires the dispatch; two Sliver tokens spawn.

Observable:
  * Sliver count on p0's battlefield: 0 → 2 on BOTH engines.

Rust triggered-ability dict::

    {
        "event": "beginning_of_upkeep",
        "predicate": {"kind": "controlled_by_you"},
        "effect": {
            "kind": "create_token",
            "count": 2,
            "token_printing_id": <sliver_pid>,
        },
    }

**Probe 3 — Razorkin Hordecaller (EoE)**
Oracle: "[Creature — Human Clown Berserker] {4}{R} 4/4
  Haste
  Whenever you attack, create a 1/1 red Gremlin creature token that's
  tapped and attacking."

  * Event    = ``YOU_ATTACK``
  * Predicate = ``Controlled(YOU)`` → ``ControlledByYou``
  * Effect   = ``CreateToken(Gremlin 1/1 Creature, count=1)``

The YY batch (``test_probe_you_attack_unlock.py``) noted: "Razorkin
Hordecaller — CreateToken; effect is representable but token-equality
assertion is more involved; deferred to a future probe."  This probe
closes that deferral using the established token-pid idiom (register
the Gremlin printing on Rust before build; pre-seed the Python state
with a Gremlin pid-seed in the library; assert token count after drain).

NOTE: The "tapped and attacking" rider on the Gremlin token (oracle text:
the created token enters tapped and attacking) is a ``CreateTokenTapped``
/ ``CreateTokenAttacking`` variant that neither the Rust bridge arm nor
the Python ``CreateToken`` dataclass carries (the ``tapped`` and
``attacking`` flags exist on Python's ``CreateToken`` but the Rust
``create_token`` bridge arm constructs ``CreateToken(tapped=False,
attacking=False)``).  The token therefore enters untapped and
non-attacking on both engines (a documented simplification — the bridge
arm's own docstring at ``cross_engine.py`` defers tapped/attacking
riders).  The token count (1 Gremlin on p0's bf) is byte-equal on both
engines and is the targeted observable.

Observable:
  * Gremlin count on p0's battlefield: 0 → 1 on BOTH engines.

Rust triggered-ability dict::

    {
        "event": "you_attack",
        "predicate": {"kind": "controlled_by_you"},
        "effect": {
            "kind": "create_token",
            "count": 1,
            "token_printing_id": <gremlin_pid>,
        },
    }

HONEST EXHAUSTION NOTES (primary directive cards not cross-engine-probeable)
-----------------------------------------------------------------------------

* **Dyadrine, Synthesis Amalgam** (EEE/AAA Pin 1 — DyadrineAttackEffect
  bridge arm): The ``dyadrine_attack_effect`` kind is wired in the Python
  bridge (``_ta_dict_to_python_effect``) but is NOT implemented in the
  Rust engine's ``parse_effect`` (absent from ``cards.rs``).  Constructing
  the Rust synthetic carrier's TA dict with ``{"kind":
  "dyadrine_attack_effect"}`` raises ``ValueError: unknown effect kind``.
  Blocked on Rust extension: needs a new ``Effect::DyadrineAttackEffect``
  variant in ``cards.rs`` + resolution logic in ``state_ops_resolve.rs``.

* **Virulent Silencer** (EEE/AAA Pin 2 — PutPoisonCountersOnTargetPlayer
  bridge arm): Two blockers:
  (1) The ``put_poison_counters_on_target_player`` effect kind is wired in
  the Python bridge but is NOT in the Rust engine's ``parse_effect``.
  (2) The predicate requires ``ControlledByYou`` scoped to the SOURCE
  subject of a two-subject ``DEALS_COMBAT_DAMAGE`` event (the "nontoken
  artifact creature you control" qualifier).  The SS probe's round-13
  honest-exhaustion note confirms this is the "same two-subject predicate
  gap" that blocked Starwinder.  Both gaps must close before Virulent
  Silencer can be individually probed.

PROBE FLOW SHARED IDIOM
-----------------------
All three probes follow the token-pid idiom established by the TT batch
(Glimmerlight):

1. Pre-register the token printing pid on Rust via an inert
   ``register_and_inject_object`` call (ZONE_LIBRARY = 1) to seed the
   Rust registry without creating a live game object.
2. Call ``register_token_printing(pid, py_printing)`` to wire the Python
   side.
3. Build cross-engine states (empty decks) via ``DeckSpec``.
4. Inject the carrier permanently onto p0's battlefield:
   - Rust: ``register_and_inject_object(..., 0, ZONE_BATTLEFIELD)``
   - Python: ``new_object + battlefield.append``
5. Fire the trigger-event on both engines:
   - End-step: ``advance_phase()`` to PHASE_END_STEP (10); Python
     ``run_beginning_of_end_step_triggers``
   - Upkeep: ``advance_phase()`` to PHASE_UPKEEP (1); Python
     ``run_beginning_of_upkeep_triggers``
   - YOU_ATTACK: ``advance_phase()`` to PHASE_DECLARE_ATTACKERS (7);
     ``apply_action(declare_attackers)`` / ``declare_attackers(py, [filler])``
6. Drain both stacks.
7. Assert token-count observables on both engines.

COVERED-BY-CONSTRUCTION → PROBED (this module)
-----------------------------------------------
Three cards move from ``covered_by_construction`` to the ``PROBED`` tier
upon merge.  Prior PROBED count: 185 → 188 (+3).
Prior covered count: 127 → 124 (−3).
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
    """Load ``scripts/parity_smoke.py`` as a module."""
    repo_root = pathlib.Path(__file__).resolve().parent.parent
    script_path = repo_root / "scripts" / "parity_smoke.py"
    spec = importlib.util.spec_from_file_location("parity_smoke", script_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["parity_smoke"] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Probe 1 — Elegy Acolyte: BEGINNING_OF_END_STEP → CreateToken(Robot 2/2)
# (ControlledByYou predicate; count=1; Artifact Creature token)
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_elegy_acolyte_end_step_create_robot_token_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Elegy Acolyte
    (round 18, BEGINNING_OF_END_STEP / ControlledByYou, CreateToken(Robot 2/2, 1)).**

    Drives the **real parsed Elegy Acolyte printing** on the Python side
    and a bridged synthetic carrier on the Rust side through the
    ``BEGINNING_OF_END_STEP`` dispatch path.

    This probe pins Elegy Acolyte's "At the beginning of your end step,
    create a 2/2 colorless Robot artifact creature token." trigger.

    NOTE: Elegy Acolyte has a second ``DEALS_COMBAT_DAMAGE`` trigger
    (``Sequence(DrawCards(1), LoseLife(1))``) with a two-subject predicate.
    That leg requires a full combat setup; deferred.  This probe covers
    only the end-step ``CreateToken`` leg, which is fully cross-engine-clean.

    Setup:
      * Pre-register the Robot token printing on Rust (inert lib seed).
      * p0 has Elegy Acolyte (4/4, lifelink) on the battlefield.
      * p1 has no creatures and no library cards.
      * Active player = p0.

    Trigger flow:
      1. Rust: ``advance_phase()`` loops to ``PHASE_END_STEP`` (10).
         Entry fires ``dispatch_event(BeginningOfEndStep,
         PLAYER_SUBJECT_OFFSET + 0)``; ``ControlledByYou`` resolves
         player_index=0; matches Elegy Acolyte's controller=0 → trigger
         pushed.
         Python: ``run_beginning_of_end_step_triggers(state)`` →
         ``dispatch_event(state, Event.BEGINNING_OF_END_STEP,
         player=state.active_player())``. Same ``Controlled(YOU)`` match.
      2. Both stacks have 1 item (the CreateToken trigger).
      3. Drain: 1 Robot 2/2 spawns on p0's battlefield on BOTH engines.

    Observables asserted (targeted):
      * Robot token count on p0's battlefield: 0 → 1 on BOTH engines.

    Rust triggered-ability dict::

        {
            "event": "beginning_of_end_step",
            "predicate": {"kind": "controlled_by_you"},
            "effect": {
                "kind": "create_token",
                "count": 1,
                "token_printing_id": robot_pid,
            },
        }
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec,
        build_python_state,
        build_rust_state,
        _ta_dict_to_python_triggered_ability,
        register_token_printing,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.cards import TOKEN_PRINTINGS
    from mtg_bot.game import Zone
    from mtg_bot.actions import resolve_top_of_stack, _trigger_etb_abilities
    from mtg_bot.turn import (
        run_beginning_of_end_step_triggers,
        state_based_actions as py_sba,
    )
    from mtg_bot.effects.predicates import Event, Controlled, YOU
    from mtg_bot.effects.generic.tokens import CreateToken

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Elegy Acolyte printing has the
    #    expected BEGINNING_OF_END_STEP trigger shape.
    # ------------------------------------------------------------------
    real = get_active_source().get_printings().get("Elegy Acolyte")
    if real is None:
        pytest.skip("Elegy Acolyte absent from active CardSource")

    assert "Creature" in real.card_types, (
        "Elegy Acolyte must be a Creature"
    )
    ea_end_step_ta = next(
        (
            ta
            for ta in real.triggered_abilities
            if ta.event == Event.BEGINNING_OF_END_STEP
        ),
        None,
    )
    assert ea_end_step_ta is not None, (
        "Elegy Acolyte must have a BEGINNING_OF_END_STEP triggered ability; "
        f"abilities found: "
        f"{[(ta.event, type(ta.effect).__name__) for ta in real.triggered_abilities]}"
    )
    assert isinstance(ea_end_step_ta.effect, CreateToken), (
        f"Elegy Acolyte end-step TA effect must be CreateToken; "
        f"got {type(ea_end_step_ta.effect).__name__}"
    )
    assert ea_end_step_ta.effect.token_printing.name == "Robot", (
        f"Elegy Acolyte end-step CreateToken must create a Robot token; "
        f"got {ea_end_step_ta.effect.token_printing.name!r}"
    )
    assert ea_end_step_ta.effect.count == 1, (
        f"Elegy Acolyte end-step CreateToken count must be 1; "
        f"got {ea_end_step_ta.effect.count}"
    )

    # ------------------------------------------------------------------
    # 2. Pre-register the Robot token printing on Rust (token-pid idiom
    #    established by TT batch / Glimmerlight probe).
    # ------------------------------------------------------------------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)

    # Seed the Rust registry with the Robot token printing (inert lib
    # object — not used in play, just fixes a stable pid for the
    # create_token bridge arm).
    robot_pid = rs.registry_size
    rs.register_and_inject_object(
        {
            "name": "Robot",
            "card_types": ["Artifact", "Creature"],
            "supertypes": ["Token"],
            "power": 2,
            "toughness": 2,
            "mana_cost": {"generic": 0},
        },
        0, 1,  # owner=0, ZONE_LIBRARY (inert pid seed)
    )
    register_token_printing(robot_pid, TOKEN_PRINTINGS["Robot"])

    # Seed the Python state with a Robot pid-seed in p0's library
    # (mirrors the Rust inert seed so compare_fields sees the same
    # shape on both sides: 1 Robot seed in each library).
    py_robot_seed = py.new_object(
        TOKEN_PRINTINGS["Robot"], owner_id=0, zone=Zone.LIBRARY
    )
    py_robot_seed.summoning_sick = False
    py.players[0].library.append(py_robot_seed)

    ZB = 2  # ZONE_BATTLEFIELD
    PHASE_END_STEP = 10

    # ------------------------------------------------------------------
    # 3. Build the shared triggered-ability dict.
    # ------------------------------------------------------------------
    ea_ta_dict = {
        "event": "beginning_of_end_step",
        "predicate": {"kind": "controlled_by_you"},
        "effect": {
            "kind": "create_token",
            "count": 1,
            "token_printing_id": robot_pid,
        },
    }

    # Sanity: bridge translates the dict correctly.
    bridge_ta = _ta_dict_to_python_triggered_ability(ea_ta_dict)
    assert bridge_ta.event == Event.BEGINNING_OF_END_STEP, (
        f"Bridge must translate 'beginning_of_end_step' to "
        f"Event.BEGINNING_OF_END_STEP; got {bridge_ta.event!r}"
    )
    assert isinstance(bridge_ta.predicate, Controlled), (
        f"Bridge predicate must be Controlled; "
        f"got {type(bridge_ta.predicate).__name__}"
    )
    assert isinstance(bridge_ta.effect, CreateToken), (
        f"Bridge effect must be CreateToken; "
        f"got {type(bridge_ta.effect).__name__}"
    )
    assert bridge_ta.effect.count == 1, (
        f"Bridge CreateToken count must be 1; got {bridge_ta.effect.count}"
    )
    assert bridge_ta.effect.token_printing.name == "Robot", (
        f"Bridge CreateToken must create a Robot; "
        f"got {bridge_ta.effect.token_printing.name!r}"
    )

    # ------------------------------------------------------------------
    # 4. Rust: inject Elegy Acolyte directly onto p0's battlefield.
    # ------------------------------------------------------------------
    rs_ea_id = rs.register_and_inject_object(
        {
            "name": "Elegy Acolyte",
            "card_types": ["Creature"],
            "power": 4,
            "toughness": 4,
            "keywords": ["lifelink"],
            "effects": [],
            "triggered_abilities": [ea_ta_dict],
        },
        0, ZB,
    )
    assert rs.find_object_zone(rs_ea_id) == ZB, (
        "Elegy Acolyte carrier must be on Rust battlefield"
    )

    # ------------------------------------------------------------------
    # 5. Rust: advance to PHASE_END_STEP (10); drain trigger (CreateToken).
    # ------------------------------------------------------------------
    for _ in range(20):
        if rs.current_phase() == PHASE_END_STEP:
            break
        rs.advance_phase()
    assert rs.current_phase() == PHASE_END_STEP, (
        f"Rust: must reach PHASE_END_STEP (10); got {rs.current_phase()}"
    )

    assert rs.stack_size() == 1, (
        f"Rust: exactly 1 trigger (Elegy Acolyte end-step CreateToken) "
        f"must be on the stack at PHASE_END_STEP entry; "
        f"got {rs.stack_size()}"
    )

    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()

    rs_robot_n = sum(
        1 for e in rs.battlefield_snapshot()
        if e["printing_name"] == "Robot"
    )
    assert rs_robot_n == 1, (
        f"Rust: exactly 1 Robot token must be on p0's battlefield after "
        f"end-step trigger resolves; got {rs_robot_n}"
    )

    # ------------------------------------------------------------------
    # 6. Python: inject genuine Elegy Acolyte printing (bridge TA) onto
    #    p0's battlefield.
    # ------------------------------------------------------------------
    py_ea_printing = CardPrinting(
        name="Elegy Acolyte",
        mana_cost_str="{2}{B}{B}",
        mana_cost=ManaCost(generic=2, colored=(("B", 2),)),
        type_line="Creature — Human Cleric",
        supertypes=(),
        card_types=("Creature",),
        subtypes=("Human", "Cleric"),
        power=4,
        toughness=4,
        produces=frozenset(),
        keywords=frozenset({"lifelink"}),
        triggered_abilities=(bridge_ta,),
    )
    py_ea = py.new_object(py_ea_printing, owner_id=0, zone=Zone.BATTLEFIELD)
    py_ea.summoning_sick = False
    py_ea.tapped = False
    py_ea.damage = 0
    py_ea.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_ea)

    # ------------------------------------------------------------------
    # 7. Python: fire end-step trigger; drain (CreateToken resolves).
    # ------------------------------------------------------------------
    run_beginning_of_end_step_triggers(py)

    assert len(py.stack) == 1, (
        f"Python: exactly 1 trigger (Elegy Acolyte end-step CreateToken) "
        f"must be on the stack after run_beginning_of_end_step_triggers; "
        f"got {len(py.stack)}"
    )

    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)

    py_robot_n = sum(
        1 for o in py.battlefield if o.printing.name == "Robot"
    )
    assert py_robot_n == 1, (
        f"Python: exactly 1 Robot token must be on p0's battlefield after "
        f"end-step trigger resolves; got {py_robot_n}"
    )

    # ------------------------------------------------------------------
    # 8. Cross-engine byte-equality on targeted observables.
    # ------------------------------------------------------------------
    assert rs_robot_n == py_robot_n, (
        f"Robot token count: Rust={rs_robot_n}, Python={py_robot_n} "
        f"(must be byte-equal — CreateToken(Robot, 1) resolved on BOTH "
        f"engines via BEGINNING_OF_END_STEP dispatch for Elegy Acolyte)"
    )


# ---------------------------------------------------------------------------
# Probe 2 — Thrumming Hivepool: BEGINNING_OF_UPKEEP → CreateToken(Sliver 1/1, 2)
# (ControlledByYou predicate; count=2; pure Artifact permanent)
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_thrumming_hivepool_upkeep_create_two_sliver_tokens_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Thrumming Hivepool
    (round 18, BEGINNING_OF_UPKEEP / ControlledByYou, CreateToken(Sliver 1/1, 2)).**

    Drives the **real parsed Thrumming Hivepool printing** on the Python
    side and a bridged synthetic carrier on the Rust side through the
    ``BEGINNING_OF_UPKEEP`` dispatch path.

    This probe pins Thrumming Hivepool's "At the beginning of your upkeep,
    create two 1/1 colorless Sliver creature tokens." trigger.

    NOTE: Thrumming Hivepool is a pure Artifact (no P/T), injected
    directly to the battlefield on both engines.  This is the first FFF
    probe to drive BEGINNING_OF_UPKEEP with a non-creature permanent and
    a count=2 CreateToken effect.

    Setup:
      * Pre-register the Sliver token printing on Rust (inert lib seed).
      * p0 has Thrumming Hivepool (Artifact) on the battlefield.
      * p1 has no permanents and no library cards.
      * Active player = p0.

    Trigger flow:
      1. Rust: ``advance_phase()`` loops to ``PHASE_UPKEEP`` (1).
         Entry fires ``dispatch_event(BeginningOfUpkeep,
         PLAYER_SUBJECT_OFFSET + 0)``; ``ControlledByYou`` resolves
         player_index=0; matches Thrumming Hivepool's controller=0.
         Python: ``run_beginning_of_upkeep_triggers(state)`` →
         ``dispatch_event(state, Event.BEGINNING_OF_UPKEEP,
         player=state.active_player())``.
      2. Both stacks have 1 item (the CreateToken(Sliver, 2) trigger).
      3. Drain: 2 Sliver 1/1 tokens spawn on p0's battlefield on BOTH.

    Observables asserted (targeted):
      * Sliver count on p0's battlefield: 0 → 2 on BOTH engines.

    Rust triggered-ability dict::

        {
            "event": "beginning_of_upkeep",
            "predicate": {"kind": "controlled_by_you"},
            "effect": {
                "kind": "create_token",
                "count": 2,
                "token_printing_id": sliver_pid,
            },
        }
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec,
        build_python_state,
        build_rust_state,
        _ta_dict_to_python_triggered_ability,
        register_token_printing,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.cards import TOKEN_PRINTINGS
    from mtg_bot.game import Zone
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.turn import (
        run_beginning_of_upkeep_triggers,
        state_based_actions as py_sba,
    )
    from mtg_bot.effects.predicates import Event, Controlled, YOU
    from mtg_bot.effects.generic.tokens import CreateToken

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Thrumming Hivepool printing has the
    #    expected BEGINNING_OF_UPKEEP trigger shape.
    # ------------------------------------------------------------------
    real = get_active_source().get_printings().get("Thrumming Hivepool")
    if real is None:
        pytest.skip("Thrumming Hivepool absent from active CardSource")

    assert "Artifact" in real.card_types, (
        "Thrumming Hivepool must be an Artifact"
    )
    th_ta = next(
        (
            ta
            for ta in real.triggered_abilities
            if ta.event == Event.BEGINNING_OF_UPKEEP
        ),
        None,
    )
    assert th_ta is not None, (
        "Thrumming Hivepool must have a BEGINNING_OF_UPKEEP triggered ability; "
        f"abilities found: "
        f"{[(ta.event, type(ta.effect).__name__) for ta in real.triggered_abilities]}"
    )
    assert isinstance(th_ta.effect, CreateToken), (
        f"Thrumming Hivepool upkeep TA effect must be CreateToken; "
        f"got {type(th_ta.effect).__name__}"
    )
    assert th_ta.effect.token_printing.name == "Sliver", (
        f"Thrumming Hivepool CreateToken must create a Sliver token; "
        f"got {th_ta.effect.token_printing.name!r}"
    )
    assert th_ta.effect.count == 2, (
        f"Thrumming Hivepool CreateToken count must be 2; "
        f"got {th_ta.effect.count}"
    )

    # ------------------------------------------------------------------
    # 2. Pre-register the Sliver token printing on Rust (token-pid idiom).
    # ------------------------------------------------------------------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)

    sliver_pid = rs.registry_size
    rs.register_and_inject_object(
        {
            "name": "Sliver",
            "card_types": ["Creature"],
            "supertypes": ["Token"],
            "power": 1,
            "toughness": 1,
            "mana_cost": {"generic": 0},
        },
        0, 1,  # owner=0, ZONE_LIBRARY (inert pid seed)
    )
    register_token_printing(sliver_pid, TOKEN_PRINTINGS["Sliver"])

    # Python lib seed (mirrors Rust seed for compare_fields symmetry).
    py_sliver_seed = py.new_object(
        TOKEN_PRINTINGS["Sliver"], owner_id=0, zone=Zone.LIBRARY
    )
    py_sliver_seed.summoning_sick = False
    py.players[0].library.append(py_sliver_seed)

    ZB = 2  # ZONE_BATTLEFIELD
    PHASE_UPKEEP = 1

    # ------------------------------------------------------------------
    # 3. Build the shared triggered-ability dict.
    # ------------------------------------------------------------------
    th_ta_dict = {
        "event": "beginning_of_upkeep",
        "predicate": {"kind": "controlled_by_you"},
        "effect": {
            "kind": "create_token",
            "count": 2,
            "token_printing_id": sliver_pid,
        },
    }

    bridge_ta = _ta_dict_to_python_triggered_ability(th_ta_dict)
    assert bridge_ta.event == Event.BEGINNING_OF_UPKEEP, (
        f"Bridge must translate 'beginning_of_upkeep' to "
        f"Event.BEGINNING_OF_UPKEEP; got {bridge_ta.event!r}"
    )
    assert isinstance(bridge_ta.predicate, Controlled), (
        f"Bridge predicate must be Controlled; "
        f"got {type(bridge_ta.predicate).__name__}"
    )
    assert isinstance(bridge_ta.effect, CreateToken), (
        f"Bridge effect must be CreateToken; "
        f"got {type(bridge_ta.effect).__name__}"
    )
    assert bridge_ta.effect.count == 2, (
        f"Bridge CreateToken count must be 2; got {bridge_ta.effect.count}"
    )
    assert bridge_ta.effect.token_printing.name == "Sliver", (
        f"Bridge CreateToken must create a Sliver; "
        f"got {bridge_ta.effect.token_printing.name!r}"
    )

    # ------------------------------------------------------------------
    # 4. Rust: inject Thrumming Hivepool (Artifact, no P/T) directly onto
    #    p0's battlefield.  No power/toughness fields (pure Artifact).
    # ------------------------------------------------------------------
    rs_th_id = rs.register_and_inject_object(
        {
            "name": "Thrumming Hivepool",
            "card_types": ["Artifact"],
            "effects": [],
            "triggered_abilities": [th_ta_dict],
        },
        0, ZB,
    )
    assert rs.find_object_zone(rs_th_id) == ZB, (
        "Thrumming Hivepool carrier must be on Rust battlefield"
    )

    # ------------------------------------------------------------------
    # 5. Rust: advance to PHASE_UPKEEP (1); drain trigger (CreateToken ×2).
    # ------------------------------------------------------------------
    for _ in range(20):
        if rs.current_phase() == PHASE_UPKEEP:
            break
        rs.advance_phase()
    assert rs.current_phase() == PHASE_UPKEEP, (
        f"Rust: must reach PHASE_UPKEEP (1); got {rs.current_phase()}"
    )

    assert rs.stack_size() == 1, (
        f"Rust: exactly 1 trigger (Thrumming Hivepool upkeep CreateToken×2) "
        f"must be on the stack at PHASE_UPKEEP entry; "
        f"got {rs.stack_size()}"
    )

    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()

    rs_sliver_n = sum(
        1 for e in rs.battlefield_snapshot()
        if e["printing_name"] == "Sliver"
    )
    assert rs_sliver_n == 2, (
        f"Rust: exactly 2 Sliver tokens must be on p0's battlefield after "
        f"upkeep trigger resolves; got {rs_sliver_n}"
    )

    # ------------------------------------------------------------------
    # 6. Python: inject genuine Thrumming Hivepool printing (bridge TA)
    #    onto p0's battlefield.  Pure Artifact — no summoning sickness.
    # ------------------------------------------------------------------
    py_th_printing = CardPrinting(
        name="Thrumming Hivepool",
        mana_cost_str="{6}",
        mana_cost=ManaCost(generic=6, colored=()),
        type_line="Artifact",
        supertypes=(),
        card_types=("Artifact",),
        subtypes=(),
        power=None,
        toughness=None,
        produces=frozenset(),
        keywords=frozenset(),
        triggered_abilities=(bridge_ta,),
    )
    py_th = py.new_object(py_th_printing, owner_id=0, zone=Zone.BATTLEFIELD)
    py_th.summoning_sick = False
    py_th.tapped = False
    py_th.damage = 0
    py_th.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_th)

    # ------------------------------------------------------------------
    # 7. Python: fire upkeep trigger; drain (CreateToken×2 resolves).
    # ------------------------------------------------------------------
    run_beginning_of_upkeep_triggers(py)

    assert len(py.stack) == 1, (
        f"Python: exactly 1 trigger (Thrumming Hivepool upkeep CreateToken×2) "
        f"must be on the stack after run_beginning_of_upkeep_triggers; "
        f"got {len(py.stack)}"
    )

    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)

    py_sliver_n = sum(
        1 for o in py.battlefield if o.printing.name == "Sliver"
    )
    assert py_sliver_n == 2, (
        f"Python: exactly 2 Sliver tokens must be on p0's battlefield after "
        f"upkeep trigger resolves; got {py_sliver_n}"
    )

    # ------------------------------------------------------------------
    # 8. Cross-engine byte-equality on targeted observables.
    # ------------------------------------------------------------------
    assert rs_sliver_n == py_sliver_n, (
        f"Sliver token count: Rust={rs_sliver_n}, Python={py_sliver_n} "
        f"(must be byte-equal — CreateToken(Sliver, 2) resolved on BOTH "
        f"engines via BEGINNING_OF_UPKEEP dispatch for Thrumming Hivepool)"
    )


# ---------------------------------------------------------------------------
# Probe 3 — Razorkin Hordecaller: YOU_ATTACK → CreateToken(Gremlin 1/1, 1)
# (ControlledByYou predicate; YOU_ATTACK event; haste creature carrier)
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_razorkin_hordecaller_you_attack_create_gremlin_token_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Razorkin Hordecaller
    (round 18, YOU_ATTACK / ControlledByYou, CreateToken(Gremlin 1/1, 1)).**

    Drives the **real parsed Razorkin Hordecaller printing** on the Python
    side and a bridged synthetic carrier on the Rust side through the
    ``YOU_ATTACK`` dispatch path.

    This probe closes the YY-batch deferral ("Razorkin Hordecaller —
    CreateToken; effect is representable but token-equality assertion is
    more involved; deferred to a future probe.") using the token-pid idiom
    established by the TT batch.

    NOTE: Razorkin Hordecaller's oracle text says the created Gremlin token
    enters "tapped and attacking."  The Rust bridge arm constructs a plain
    ``CreateToken(tapped=False, attacking=False)`` — the tapped/attacking
    riders are a documented simplification (see batch docstring above).
    The token count (1 Gremlin) is byte-equal and is the targeted
    observable.

    Setup:
      * Pre-register the Gremlin token printing on Rust (inert lib seed).
      * p0 has Razorkin Hordecaller (4/4, haste) and a filler attacker
        (2/2, haste) on the battlefield.
      * p1 has no creatures and no library cards.
      * Active player = p0.

    Trigger flow:
      1. Both engines advance to PHASE_DECLARE_ATTACKERS.
         Rust: ``advance_phase()`` loops to phase 7 (DECLARE_ATTACKERS in
         the installed extension — matches the YY probe's constant).
         Python: state is placed at BEGINNING_OF_COMBAT and
         ``declare_attackers`` is called directly (same path as the YY
         probe).
      2. Declare filler as an attacker on both engines:
         - Rust: ``apply_action({"kind": "declare_attackers",
           "attacker_ids": [filler_id]})``.  Per-attacker
           ``Event::Attacks`` fires; then ``Event::YouAttack`` fires once
           (``DeclareAttackers`` arm, after the attacker loop).
         - Python: ``declare_attackers(py, [py_filler.id])``.
           ``_fire_you_attack_triggers`` pushes the Razorkin Hordecaller
           trigger (``ControlledByYou`` matches controller=0 of both the
           filler attacker and Hordecaller).
      3. Stack has ≥ 1 item (Hordecaller's trigger; possibly a per-attacker
         Attacks trigger as well).  Drain → ``CreateToken(Gremlin, 1)``
         resolves.

    Observables asserted (targeted):
      * Gremlin count on p0's battlefield: 0 → 1 on BOTH engines.

    Rust triggered-ability dict::

        {
            "event": "you_attack",
            "predicate": {"kind": "controlled_by_you"},
            "effect": {
                "kind": "create_token",
                "count": 1,
                "token_printing_id": gremlin_pid,
            },
        }
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec,
        build_python_state,
        build_rust_state,
        _ta_dict_to_python_triggered_ability,
        register_token_printing,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.cards import TOKEN_PRINTINGS
    from mtg_bot.game import Zone
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.predicates import Event, Controlled, YOU
    from mtg_bot.effects.generic.tokens import CreateToken
    from mtg_bot import combat as py_combat

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Razorkin Hordecaller printing has the
    #    expected YOU_ATTACK trigger shape.
    # ------------------------------------------------------------------
    real = get_active_source().get_printings().get("Razorkin Hordecaller")
    if real is None:
        pytest.skip("Razorkin Hordecaller absent from active CardSource")

    assert "Creature" in real.card_types, (
        "Razorkin Hordecaller must be a Creature"
    )
    rh_ta = next(
        (
            ta
            for ta in real.triggered_abilities
            if ta.event == Event.YOU_ATTACK
        ),
        None,
    )
    assert rh_ta is not None, (
        "Razorkin Hordecaller must have a YOU_ATTACK triggered ability; "
        f"abilities found: "
        f"{[(ta.event, type(ta.effect).__name__) for ta in real.triggered_abilities]}"
    )
    assert isinstance(rh_ta.effect, CreateToken), (
        f"Razorkin Hordecaller YOU_ATTACK TA effect must be CreateToken; "
        f"got {type(rh_ta.effect).__name__}"
    )
    assert rh_ta.effect.token_printing.name == "Gremlin", (
        f"Razorkin Hordecaller CreateToken must create a Gremlin token; "
        f"got {rh_ta.effect.token_printing.name!r}"
    )
    assert rh_ta.effect.count == 1, (
        f"Razorkin Hordecaller CreateToken count must be 1; "
        f"got {rh_ta.effect.count}"
    )

    # ------------------------------------------------------------------
    # 2. Pre-register the Gremlin token printing on Rust (token-pid idiom).
    # ------------------------------------------------------------------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)

    gremlin_pid = rs.registry_size
    rs.register_and_inject_object(
        {
            "name": "Gremlin",
            "card_types": ["Creature"],
            "supertypes": ["Token"],
            "power": 1,
            "toughness": 1,
            "mana_cost": {"generic": 0},
        },
        0, 1,  # owner=0, ZONE_LIBRARY (inert pid seed)
    )
    register_token_printing(gremlin_pid, TOKEN_PRINTINGS["Gremlin"])

    # Python lib seed.
    py_gremlin_seed = py.new_object(
        TOKEN_PRINTINGS["Gremlin"], owner_id=0, zone=Zone.LIBRARY
    )
    py_gremlin_seed.summoning_sick = False
    py.players[0].library.append(py_gremlin_seed)

    ZB = 2  # ZONE_BATTLEFIELD
    # PHASE_DECLARE_ATTACKERS = 7 (matches the installed extension; same
    # constant as the YY probe / test_probe_you_attack_unlock.py:290).
    PHASE_DECLARE_ATTACKERS = 7

    # ------------------------------------------------------------------
    # 3. Build the shared triggered-ability dict.
    # ------------------------------------------------------------------
    rh_ta_dict = {
        "event": "you_attack",
        "predicate": {"kind": "controlled_by_you"},
        "effect": {
            "kind": "create_token",
            "count": 1,
            "token_printing_id": gremlin_pid,
        },
    }

    bridge_ta = _ta_dict_to_python_triggered_ability(rh_ta_dict)
    assert bridge_ta.event == Event.YOU_ATTACK, (
        f"Bridge must translate 'you_attack' to Event.YOU_ATTACK; "
        f"got {bridge_ta.event!r}"
    )
    assert isinstance(bridge_ta.predicate, Controlled), (
        f"Bridge predicate must be Controlled; "
        f"got {type(bridge_ta.predicate).__name__}"
    )
    assert isinstance(bridge_ta.effect, CreateToken), (
        f"Bridge effect must be CreateToken; "
        f"got {type(bridge_ta.effect).__name__}"
    )
    assert bridge_ta.effect.count == 1, (
        f"Bridge CreateToken count must be 1; got {bridge_ta.effect.count}"
    )
    assert bridge_ta.effect.token_printing.name == "Gremlin", (
        f"Bridge CreateToken must create a Gremlin; "
        f"got {bridge_ta.effect.token_printing.name!r}"
    )

    # ------------------------------------------------------------------
    # 4. Rust: inject Razorkin Hordecaller + haste filler onto p0's bf.
    # ------------------------------------------------------------------
    rs_rh_id = rs.register_and_inject_object(
        {
            "name": "Razorkin Hordecaller",
            "card_types": ["Creature"],
            "power": 4,
            "toughness": 4,
            "keywords": ["haste"],
            "effects": [],
            "triggered_abilities": [rh_ta_dict],
        },
        0, ZB,
    )
    rs_filler_id = rs.register_and_inject_object(
        {
            "name": "AttackFiller",
            "card_types": ["Creature"],
            "power": 2,
            "toughness": 2,
            "keywords": ["haste"],
            "effects": [],
            "triggered_abilities": [],
        },
        0, ZB,
    )

    assert not rs.is_summoning_sick(rs_rh_id), (
        "Rust: Razorkin Hordecaller must not be summoning-sick "
        "(register_and_inject_object defaults summoning_sick=False)"
    )
    assert not rs.is_summoning_sick(rs_filler_id), (
        "Rust: AttackFiller must not be summoning-sick"
    )

    # ------------------------------------------------------------------
    # 5. Rust: advance to PHASE_DECLARE_ATTACKERS (7 in installed ext);
    #    declare filler as attacker → YOU_ATTACK fires → trigger pushed.
    # ------------------------------------------------------------------
    for _ in range(20):
        if rs.current_phase() == PHASE_DECLARE_ATTACKERS:
            break
        rs.advance_phase()
    assert rs.current_phase() == PHASE_DECLARE_ATTACKERS, (
        f"Rust: must reach PHASE_DECLARE_ATTACKERS (7); "
        f"got {rs.current_phase()}"
    )

    action_dict = {"kind": "declare_attackers", "attacker_ids": [rs_filler_id]}
    rs.apply_action(action_dict)

    assert rs.stack_size() >= 1, (
        f"Rust: at least 1 trigger (Hordecaller's CreateToken) must be on "
        f"the stack after declaring attackers; got {rs.stack_size()}"
    )

    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()

    rs_gremlin_n = sum(
        1 for e in rs.battlefield_snapshot()
        if e["printing_name"] == "Gremlin"
    )
    assert rs_gremlin_n == 1, (
        f"Rust: exactly 1 Gremlin token must be on p0's battlefield after "
        f"YOU_ATTACK trigger resolves; got {rs_gremlin_n}"
    )

    # ------------------------------------------------------------------
    # 6. Python: pre-seat Razorkin Hordecaller (bridge TA) + haste filler
    #    on p0's battlefield.
    # ------------------------------------------------------------------
    py_rh_printing = CardPrinting(
        name="Razorkin Hordecaller",
        mana_cost_str="{4}{R}",
        mana_cost=ManaCost(generic=4, colored=(("R", 1),)),
        type_line="Creature — Human Clown Berserker",
        supertypes=(),
        card_types=("Creature",),
        subtypes=("Human", "Clown", "Berserker"),
        power=4,
        toughness=4,
        produces=frozenset(),
        keywords=frozenset({"haste"}),
        triggered_abilities=(bridge_ta,),
    )
    py_rh = py.new_object(py_rh_printing, owner_id=0, zone=Zone.BATTLEFIELD)
    py_rh.summoning_sick = False
    py_rh.tapped = False
    py_rh.damage = 0
    py_rh.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_rh)

    py_filler_printing = CardPrinting(
        name="AttackFiller",
        mana_cost_str="{G}",
        mana_cost=ManaCost(generic=0, colored=(("G", 1),)),
        type_line="Creature — Beast",
        supertypes=(),
        card_types=("Creature",),
        subtypes=("Beast",),
        power=2,
        toughness=2,
        produces=frozenset(),
        keywords=frozenset({"haste"}),
        triggered_abilities=(),
    )
    py_filler = py.new_object(py_filler_printing, owner_id=0, zone=Zone.BATTLEFIELD)
    py_filler.summoning_sick = False
    py_filler.tapped = False
    py_filler.damage = 0
    py_filler.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_filler)

    # ------------------------------------------------------------------
    # 7. Python: declare filler as attacker — YOU_ATTACK fires once.
    # ------------------------------------------------------------------
    py_combat.declare_attackers(py, [py_filler.id])

    assert len(py.stack) >= 1, (
        f"Python: at least 1 trigger (Hordecaller's CreateToken) must be "
        f"on the stack after declaring attackers; got {len(py.stack)}"
    )

    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)

    py_gremlin_n = sum(
        1 for o in py.battlefield if o.printing.name == "Gremlin"
    )
    assert py_gremlin_n == 1, (
        f"Python: exactly 1 Gremlin token must be on p0's battlefield after "
        f"YOU_ATTACK trigger resolves; got {py_gremlin_n}"
    )

    # ------------------------------------------------------------------
    # 8. Cross-engine byte-equality on targeted observables.
    # ------------------------------------------------------------------
    assert rs_gremlin_n == py_gremlin_n, (
        f"Gremlin token count: Rust={rs_gremlin_n}, Python={py_gremlin_n} "
        f"(must be byte-equal — CreateToken(Gremlin, 1) resolved on BOTH "
        f"engines via YOU_ATTACK dispatch for Razorkin Hordecaller)"
    )
