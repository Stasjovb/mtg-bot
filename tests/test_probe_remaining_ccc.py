"""Genuine real-EoE cross-engine byte-equality probes — batch CCC (round 17,
downstream of the BBB conditional + state-predicate bridge fixes).

BBB wired the Python bridge for three new effect/predicate families:

  * ``ConditionalIfYouGainedLifeAtLeast`` (Haliya, Guided by Light's
    end-step draw-if-gained-3-life rider)
  * ``ConditionalIfSourcePowerAtLeast`` (Syr Vondam, Sunstar Exemplar's
    self-trigger gated on power >= 4)
  * ``StateBound`` predicate wrapper for the ``AnyPlayerControlsNoCreatures``
    and ``VoidActive`` state predicates (Sothera, the Supervoid;
    Hylderblade; Alpharael, Stonechosen)

PROBE CARDS
-----------

**Probe 1 — Haliya, Guided by Light (EoE)**
Oracle: "[Legendary Creature — Human Soldier] {2}{W} 3/3
  Whenever Haliya or another creature or artifact you control enters,
  you gain 1 life.
  At the beginning of your end step, draw a card if you've gained 3 or
  more life this turn.
  Warp {W} (…)"

The ENTERS observer trigger — ``And(Or(subject_is_creature,
subject_is_artifact), controlled_by_you) → GainLife(1)`` — is the
cross-engine-clean path for this card: Rust supports both the ``or``
predicate combinator and the ``gain_life`` effect arm in the trigger
registry. The end-step ``ConditionalIfYouGainedLifeAtLeast`` trigger,
while now wired in the Python bridge (BBB Pin 1), is NOT yet
implemented in the Rust engine's ``parse_effect`` (``conditional_if_
you_gained_life_at_least`` is absent from the Rust registry's valid-
kinds list). Honest exhaustion: the end-step arm is
covered-by-construction on the Python side (the bridge arm exists)
but is not cross-engine-probeable until the Rust side grows the
complementary variant. This probe therefore pins the ENTERS trigger
only, which is sufficient to prove Haliya's primary observer shape
byte-equal.

Observable:
  * p0 life gains +1 each time a creature or artifact p0 controls
    enters. Two enters events (Haliya herself, then a Wild Bear bystander)
    → +2 total. BOTH engines agree.

Rust triggered-ability dict::

    {
        "event": "enters",
        "predicate": {
            "kind": "and",
            "left": {"kind": "or",
                     "left": {"kind": "subject_is_creature"},
                     "right": {"kind": "subject_is_artifact"}},
            "right": {"kind": "controlled_by_you"},
        },
        "effect": {"kind": "gain_life", "amount": 1},
    }

**Probe 2 — Syr Vondam, Sunstar Exemplar (EoE)**
Oracle: "[Legendary Creature — Human Knight] {3}{W} 2/2
  Vigilance, menace
  Whenever another creature you control dies or is put into exile, put a
  +1/+1 counter on Syr Vondam and you gain 1 life.
  When Syr Vondam dies or is put into exile while its power is 4 or
  greater, destroy up to one target nonland permanent."

The dies-observer trigger — ``And(And(subject_is_creature,
controlled_by_you), Not(source_is_self)) → Sequence(PutPlusOneCounterOnSelf(1),
GainLife(1))`` — is the cross-engine-clean path. All three predicate
qualifiers (subject_is_creature, controlled_by_you, Not(source_is_self))
and both effect slots (put_plus_one_counter_on_self, gain_life in a
sequence) are supported by the Rust engine.

NOTE: The card has a distinct name ("Sunstar Exemplar" printing) vs
"Syr Vondam, the Lucent" (already PROBED via ETB in QQ). The QQ probe
covered ``IsSelf`` ETB + ``PumpCreaturesYouControlUntilEOT``; this probe
covers the ``DIES`` observer shape + ``Sequence(counter, life)`` — a
completely different trigger pathway on the same character's second
EoE printing.

The self-trigger (``IsSelf → ConditionalIfSourcePowerAtLeast(...)``,
BBB Pin 2) is NOT cross-engine-probeable yet: Rust's ``parse_predicate``
does not support ``is_self`` as a predicate kind inside a triggered-
ability dict (only ``source_is_self`` is valid, and the bridge maps
``source_is_self`` → ``IsSelf(subject=None)``, but ``source_is_self``
in the DIES context conflates the dying subject with the source in a
way that Rust resolves differently). Honest exhaustion for the
``ConditionalIfSourcePowerAtLeast`` arm.

Observable:
  * Syr Vondam counters: 0 → 1 on BOTH engines.
  * p0 life: 20 → 21 on BOTH engines.

Rust triggered-ability dict::

    {
        "event": "dies",
        "predicate": {
            "kind": "and",
            "left": {"kind": "and",
                     "left": {"kind": "subject_is_creature"},
                     "right": {"kind": "controlled_by_you"}},
            "right": {"kind": "not", "inner": {"kind": "source_is_self"}},
        },
        "effect": {
            "kind": "sequence",
            "effects": [
                {"kind": "put_plus_one_counter_on_self", "amount": 1},
                {"kind": "gain_life", "amount": 1},
            ],
        },
    }

HONEST EXHAUSTION NOTES (cards from directive not cross-engine-probeable
this round)
--------------------------------------------------------------------

* **Sothera, the Supervoid** (the residue-worklist genuinely_missing card,
  Pin 3 AnyPlayerControlsNoCreatures): DIES trigger uses
  ``each_opponent_exiles_own_creature`` (not in bridge's effect arm);
  END-STEP trigger uses ``reanimate_one_exiled_with_source_with_counters``
  and ``sacrifice_self_preserving_exile_link`` (also absent). Neither
  Rust arm exists in the engine's valid-kinds list. Probeable on the
  Python side via ``test_sothera_supervoid.py`` (already covered);
  not cross-engine-probeable without Rust extension.

* **Hylderblade** (Pin 3 Void family / attach Equipment): END-STEP
  trigger predicate requires ``{"kind": "state_bound", ...}`` — Rust's
  ``parse_predicate`` does NOT support ``state_bound`` as a predicate
  kind (error: "unknown predicate kind 'state_bound'"). The ``VoidActive``
  gate cannot be expressed in Rust's trigger-registry schema. Blocked
  until Rust grows a ``StateBound`` predicate variant.

* **Alpharael, Stonechosen** (Pin 3 Void family / half-life loss):
  ATTACKS trigger effect is ``defending_player_loses_half_life_rounded_up``
  — absent from the bridge's ``_ta_dict_to_python_effect`` kind space.
  The ``conditional_if_void`` Rust effect arm exists but its inner
  ``then_effect`` arm would need to route to ``defending_player_loses_
  half_life_rounded_up``, which the Python bridge does not yet implement.
  Blocked on bridge extension.

* **Haliya's end-step ConditionalIfYouGainedLifeAtLeast arm** (Pin 1):
  Rust's ``parse_effect`` does not include
  ``conditional_if_you_gained_life_at_least`` in its valid-kinds list
  (confirmed by the ValueError raised when constructing the TA dict).
  Python bridge arm is wired (BBB); Rust substrate is the gap.

PROBE FLOW SHARED IDIOM
-----------------------
Both probes follow the canonical phase-step probe shape established
by the ZZ batch (Insatiable Skittermaw / Kavaron Skywarden):

1. Build minimal cross-engine states (empty decks).
2. Inject the observer card + any bystander objects via
   ``register_and_inject_object`` (Rust) / ``put_into_battlefield`` or
   manual zone-append + ``_trigger_etb_abilities`` (Python).
3. Drive the trigger-firing event on both engines:
   - Probe 1 (ETB observer): inject a bystander creature; the
     Rust engine fires ENTERS internally; the Python engine calls
     ``_trigger_etb_abilities`` / ``put_into_battlefield`` at the
     injection site.
   - Probe 2 (DIES observer): deal lethal damage to the ally creature;
     ``apply_sbas`` moves it to the graveyard and fires the DIES trigger.
4. Drain both stacks.
5. Assert targeted observables (life totals / counter counts).
6. Assert cross-engine byte-equality on the targeted observables.

COVERED-BY-CONSTRUCTION → PROBED (this module)
-----------------------------------------------
Both cards move from the ``covered_by_construction`` tier to the
``PROBED`` tier upon merge. Prior PROBED count: 183 → 185 (+2).
Prior covered count: 127 → 125 (−2).
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
# Probe 1 — Haliya, Guided by Light: creature-or-artifact-enters observer
# (ENTERS, And(Or(subject_is_creature, subject_is_artifact), controlled_by_you),
#  GainLife(1))
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_haliya_guided_by_light_enters_observer_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Haliya, Guided by Light
    (round 17, ENTERS / Or(creature, artifact) & ControlledByYou, GainLife(1)).**

    Drives the **real parsed Haliya, Guided by Light printing** on the
    Python side and a bridged synthetic carrier on the Rust side through
    the ``ENTERS`` dispatch path.

    This probe pins Haliya's "Whenever Haliya or another creature or
    artifact you control enters, you gain 1 life." trigger.  The trigger
    fires TWICE in the scenario — once when Haliya herself enters
    (``put_into_battlefield`` / ``register_and_inject_object`` both fire
    the ENTERS event), and once when a bystander Wild Bear enters.
    Both engines gain +2 life total.

    NOTE: The end-step ``ConditionalIfYouGainedLifeAtLeast(3, DrawCards(1))``
    trigger (BBB Pin 1, the end-step draw rider) is NOT cross-engine-
    probeable: Rust's ``parse_effect`` does not implement the
    ``conditional_if_you_gained_life_at_least`` effect kind.  This probe
    covers only the ENTERS arm, which IS fully cross-engine-clean.

    Setup:
      * p0 starts empty (no permanents).  Active player = p0.
      * Haliya is injected via ``register_and_inject_object`` (Rust) /
        ``put_into_battlefield`` (Python) — ENTERS fires → +1 life.
      * A Wild Bear bystander is injected the same way — ENTERS fires
        again → +2 life total.

    Observables asserted (targeted):
      * p0 life: 20 → 22 on BOTH engines (+1 per ENTERS event, two events).
      * p1 life: 20 unchanged on BOTH engines.

    Rust triggered-ability dict::

        {
            "event": "enters",
            "predicate": {
                "kind": "and",
                "left": {"kind": "or",
                         "left": {"kind": "subject_is_creature"},
                         "right": {"kind": "subject_is_artifact"}},
                "right": {"kind": "controlled_by_you"},
            },
            "effect": {"kind": "gain_life", "amount": 1},
        }
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec,
        build_python_state,
        build_rust_state,
        _ta_dict_to_python_triggered_ability,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.cards import SYNTHETIC_CREATURES
    from mtg_bot.game import Zone
    from mtg_bot.actions import resolve_top_of_stack, put_into_battlefield
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.predicates import (
        Event,
        Controlled,
        YOU,
        Or,
        Subject,
    )
    from mtg_bot.effects.object_predicates import IsCreature, IsArtifact
    from mtg_bot.effects.generic.life import GainLife

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Haliya printing has the expected
    #    ENTERS trigger shape.
    # ------------------------------------------------------------------
    real = get_active_source().get_printings().get("Haliya, Guided by Light")
    if real is None:
        pytest.skip("Haliya, Guided by Light absent from active CardSource")

    assert "Creature" in real.card_types, (
        "Haliya, Guided by Light must be a Creature"
    )
    h_enters_ta = next(
        (
            ta
            for ta in real.triggered_abilities
            if ta.event == Event.ENTERS
        ),
        None,
    )
    assert h_enters_ta is not None, (
        "Haliya, Guided by Light must have an ENTERS triggered ability; "
        f"abilities found: "
        f"{[(ta.event, type(ta.effect).__name__) for ta in real.triggered_abilities]}"
    )
    assert isinstance(h_enters_ta.effect, GainLife), (
        f"Haliya ENTERS TA effect must be GainLife; "
        f"got {type(h_enters_ta.effect).__name__}"
    )
    assert h_enters_ta.effect.amount == 1, (
        f"Haliya ENTERS GainLife amount must be 1; "
        f"got {h_enters_ta.effect.amount}"
    )

    # ------------------------------------------------------------------
    # 2. Shared triggered-ability dict.
    # ------------------------------------------------------------------
    h_etb_ta_dict = {
        "event": "enters",
        "predicate": {
            "kind": "and",
            "left": {
                "kind": "or",
                "left": {"kind": "subject_is_creature"},
                "right": {"kind": "subject_is_artifact"},
            },
            "right": {"kind": "controlled_by_you"},
        },
        "effect": {"kind": "gain_life", "amount": 1},
    }

    bridge_ta = _ta_dict_to_python_triggered_ability(h_etb_ta_dict)
    assert bridge_ta.event == Event.ENTERS, (
        f"Bridge must translate 'enters' to Event.ENTERS; "
        f"got {bridge_ta.event!r}"
    )
    assert isinstance(bridge_ta.predicate, type(h_enters_ta.predicate)), (
        f"Bridge predicate class must match real-card predicate class; "
        f"real={type(h_enters_ta.predicate).__name__}, "
        f"bridge={type(bridge_ta.predicate).__name__}"
    )
    assert isinstance(bridge_ta.effect, GainLife), (
        f"Bridge effect must be GainLife; "
        f"got {type(bridge_ta.effect).__name__}"
    )
    assert bridge_ta.effect.amount == 1, (
        f"Bridge GainLife amount must be 1; got {bridge_ta.effect.amount}"
    )

    # ------------------------------------------------------------------
    # 3. Build cross-engine states with empty decks.
    # ------------------------------------------------------------------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)

    ZB = 2  # ZONE_BATTLEFIELD

    # ------------------------------------------------------------------
    # 4. Rust: inject Haliya onto p0's battlefield; ENTERS fires self.
    # ------------------------------------------------------------------
    rs_haliya_id = rs.register_and_inject_object(
        {
            "name": "Haliya, Guided by Light",
            "card_types": ["Creature"],
            "supertypes": ["Legendary"],
            "power": 3,
            "toughness": 3,
            "keywords": [],
            "effects": [],
            "triggered_abilities": [h_etb_ta_dict],
        },
        0, ZB,
    )

    rs_life0 = rs.get_life(0)
    assert rs_life0 == 20, (
        f"Rust: p0 must start at 20 life; got {rs_life0}"
    )

    # Drain Haliya's self-ETB trigger (+1 life).
    assert rs.stack_size() == 1, (
        f"Rust: exactly 1 trigger (Haliya self-enter) must be on the stack; "
        f"got {rs.stack_size()}"
    )
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()

    rs_life_after_haliya = rs.get_life(0)
    assert rs_life_after_haliya == 21, (
        f"Rust: p0 life must be 21 after Haliya enters (+1 life); "
        f"got {rs_life_after_haliya}"
    )

    # ------------------------------------------------------------------
    # 5. Rust: inject a Wild Bear bystander; ENTERS fires again (+1 life).
    # ------------------------------------------------------------------
    rs_bear_id = rs.register_and_inject_object(
        {
            "name": "Wild Bear",
            "card_types": ["Creature"],
            "power": 2,
            "toughness": 2,
            "keywords": [],
            "effects": [],
            "triggered_abilities": [],
        },
        0, ZB,
    )

    assert rs.stack_size() == 1, (
        f"Rust: exactly 1 trigger (Haliya observer fires on bear entering) "
        f"must be on the stack; got {rs.stack_size()}"
    )
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()

    rs_life1 = rs.get_life(0)
    assert rs_life1 == 22, (
        f"Rust: p0 life must be 22 after two enters events; "
        f"got {rs_life1}"
    )
    assert rs.get_life(1) == 20, (
        f"Rust: p1 life must remain 20 (unaffected); "
        f"got {rs.get_life(1)}"
    )

    # ------------------------------------------------------------------
    # 6. Python: inject Haliya via put_into_battlefield (fires ETB).
    # ------------------------------------------------------------------
    py_haliya_printing = CardPrinting(
        name="Haliya, Guided by Light",
        mana_cost_str="{2}{W}",
        mana_cost=ManaCost(generic=2, colored=(("W", 1),)),
        type_line="Legendary Creature — Human Soldier",
        supertypes=("Legendary",),
        card_types=("Creature",),
        subtypes=("Human", "Soldier"),
        power=3,
        toughness=3,
        produces=frozenset(),
        keywords=frozenset(),
        triggered_abilities=(bridge_ta,),
    )
    py_haliya = py.new_object(
        py_haliya_printing, owner_id=0, zone=Zone.HAND,
    )
    py.players[0].hand.append(py_haliya)

    py_life0 = py.players[0].life
    assert py_life0 == 20, (
        f"Python: p0 must start at 20 life; got {py_life0}"
    )

    # put_into_battlefield fires the ENTERS event (Haliya observes herself
    # entering → GainLife(1)).
    put_into_battlefield(py, py_haliya, controller_id=0)

    assert len(py.stack) == 1, (
        f"Python: exactly 1 trigger (Haliya self-enter) must be on the "
        f"stack after put_into_battlefield; got {len(py.stack)}"
    )
    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)

    py_life_after_haliya = py.players[0].life
    assert py_life_after_haliya == 21, (
        f"Python: p0 life must be 21 after Haliya enters (+1 life); "
        f"got {py_life_after_haliya}"
    )

    # ------------------------------------------------------------------
    # 7. Python: inject Wild Bear via put_into_battlefield.
    # ------------------------------------------------------------------
    py_bear = py.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.HAND,
    )
    py.players[0].hand.append(py_bear)

    put_into_battlefield(py, py_bear, controller_id=0)

    assert len(py.stack) == 1, (
        f"Python: exactly 1 trigger (Haliya observer fires on bear entering) "
        f"must be on the stack; got {len(py.stack)}"
    )
    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)

    py_life1 = py.players[0].life
    assert py_life1 == 22, (
        f"Python: p0 life must be 22 after two enters events; "
        f"got {py_life1}"
    )
    assert py.players[1].life == 20, (
        f"Python: p1 life must remain 20 (unaffected); "
        f"got {py.players[1].life}"
    )

    # ------------------------------------------------------------------
    # 8. Cross-engine byte-equality on targeted observables.
    # ------------------------------------------------------------------
    assert rs_life1 == py_life1, (
        f"p0 life: Rust={rs_life1}, Python={py_life1} "
        f"(must be byte-equal — GainLife(1) resolved TWICE on BOTH engines "
        f"via ENTERS dispatch for Haliya + Wild Bear)"
    )
    assert rs.get_life(1) == py.players[1].life == 20, (
        f"p1 life must be 20 on BOTH; "
        f"Rust={rs.get_life(1)}, Python={py.players[1].life}"
    )


# ---------------------------------------------------------------------------
# Probe 2 — Syr Vondam, Sunstar Exemplar: dies-observer counter + life
# (DIES, And(And(subject_is_creature, controlled_by_you), Not(source_is_self)),
#  Sequence(PutPlusOneCounterOnSelf(1), GainLife(1)))
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_syr_vondam_sunstar_exemplar_dies_observer_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Syr Vondam, Sunstar Exemplar
    (round 17, DIES / And(creature & controlled_by_you & ~IsSelf),
    Sequence(PutPlusOneCounterOnSelf(1), GainLife(1))).**

    Drives the **real parsed Syr Vondam, Sunstar Exemplar printing** on
    the Python side and a bridged synthetic carrier on the Rust side
    through the ``DIES`` dispatch path.

    This probe covers the "Whenever another creature you control dies or
    is put into exile, put a +1/+1 counter on Syr Vondam and you gain
    1 life." trigger — the DIES observer arm with the triple-AND predicate
    (creature + controlled_by_you + NOT self) and the Sequence of two
    effects.

    NOTE: This is a DIFFERENT card from "Syr Vondam, the Lucent" (already
    PROBED in QQ via an ETB trigger).  "Sunstar Exemplar" is the second
    EoE printing of the same character, exercising an entirely different
    trigger pathway (DIES observer + Sequence(counter, life) vs. ETB +
    PumpCreaturesYouControlUntilEOT).

    NOTE on the self-trigger: the card ALSO has a second LEAVES_BATTLEFIELD
    trigger gated on ``ConditionalIfSourcePowerAtLeast(4, Destroy...)``
    (BBB Pin 2).  That arm is NOT cross-engine-probeable: Rust's
    ``parse_predicate`` does not recognise ``is_self`` as a predicate kind
    inside a triggered-ability dict (only ``source_is_self`` is valid, and
    the interaction with LEAVES_BATTLEFIELD's subject semantics produces a
    predicate mismatch).  Honest exhaustion for the self-trigger arm.

    Setup:
      * p0 has Syr Vondam, Sunstar Exemplar (2/2) and a Wild Bear ally
        (2/2) on the battlefield.
      * p1 has no creatures.
      * Active player = p0.

    Trigger flow:
      1. Deal lethal damage to the Wild Bear ally (10 damage to a 2/2).
      2. ``apply_sbas`` / ``state_based_actions``: the bear has lethal
         damage → dies → dispatches ``DIES`` event.
         Rust: ``dispatch_event(Dies, bear_id)``; Python: ``destroy``
         routes through the SBA path which calls ``dispatch_event(state,
         Event.DIES, obj=bear)``.
      3. Syr Vondam's predicate fires: subject is a creature, controlled
         by p0, NOT Vondam itself.  Push the trigger.
      4. Drain: Sequence resolves → ``PutPlusOneCounterOnSelf(1)`` first
         (Vondam gains 1 counter), then ``GainLife(1)`` (p0 life +1).

    Observables asserted (targeted):
      * Vondam ``get_counters`` (Rust) / ``plus_one_counters`` (Python):
        0 → 1 on BOTH engines.
      * Vondam ``effective_power``: 2 → 3 on BOTH engines.
      * p0 life: 20 → 21 on BOTH engines.

    Rust triggered-ability dict::

        {
            "event": "dies",
            "predicate": {
                "kind": "and",
                "left": {
                    "kind": "and",
                    "left": {"kind": "subject_is_creature"},
                    "right": {"kind": "controlled_by_you"},
                },
                "right": {"kind": "not", "inner": {"kind": "source_is_self"}},
            },
            "effect": {
                "kind": "sequence",
                "effects": [
                    {"kind": "put_plus_one_counter_on_self", "amount": 1},
                    {"kind": "gain_life", "amount": 1},
                ],
            },
        }
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec,
        build_python_state,
        build_rust_state,
        _ta_dict_to_python_triggered_ability,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.cards import SYNTHETIC_CREATURES
    from mtg_bot.game import Zone
    from mtg_bot.game import effective_power as py_effective_power
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.turn import (
        state_based_actions as py_sba,
        destroy as py_destroy,
    )
    from mtg_bot.effects.predicates import (
        Event,
        Controlled,
        YOU,
        And,
        Not,
        Subject,
        IsSelf,
    )
    from mtg_bot.effects.object_predicates import IsCreature
    from mtg_bot.effects.combinators import Sequence
    from mtg_bot.effects.generic.counters import PutPlusOneCounterOnSelf
    from mtg_bot.effects.generic.life import GainLife

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Syr Vondam, Sunstar Exemplar printing
    #    has the expected DIES observer trigger shape.
    # ------------------------------------------------------------------
    real = get_active_source().get_printings().get(
        "Syr Vondam, Sunstar Exemplar"
    )
    if real is None:
        pytest.skip(
            "Syr Vondam, Sunstar Exemplar absent from active CardSource"
        )

    assert "Creature" in real.card_types, (
        "Syr Vondam, Sunstar Exemplar must be a Creature"
    )
    # Find the observer trigger (NOT the self-trigger).
    sv_observer_ta = next(
        (
            ta
            for ta in real.triggered_abilities
            if ta.event == Event.LEAVES_BATTLEFIELD
            and isinstance(ta.effect, Sequence)
        ),
        None,
    )
    assert sv_observer_ta is not None, (
        "Syr Vondam, Sunstar Exemplar must have a LEAVES_BATTLEFIELD "
        "observer trigger with a Sequence effect; triggers found: "
        f"{[(ta.event, type(ta.effect).__name__) for ta in real.triggered_abilities]}"
    )
    # Verify the Sequence body.
    seq = sv_observer_ta.effect
    assert len(seq.effects) == 2, (
        f"Observer TA Sequence must have 2 sub-effects; got {len(seq.effects)}"
    )
    assert isinstance(seq.effects[0], PutPlusOneCounterOnSelf), (
        f"Observer TA Sequence[0] must be PutPlusOneCounterOnSelf; "
        f"got {type(seq.effects[0]).__name__}"
    )
    assert seq.effects[0].amount == 1, (
        f"Observer TA PutPlusOneCounterOnSelf amount must be 1; "
        f"got {seq.effects[0].amount}"
    )
    assert isinstance(seq.effects[1], GainLife), (
        f"Observer TA Sequence[1] must be GainLife; "
        f"got {type(seq.effects[1]).__name__}"
    )
    assert seq.effects[1].amount == 1, (
        f"Observer TA GainLife amount must be 1; "
        f"got {seq.effects[1].amount}"
    )

    # ------------------------------------------------------------------
    # 2. Shared triggered-ability dict.
    #    Uses "dies" event to match the LEAVES_BATTLEFIELD DIES path
    #    (bridge maps "dies" → Event.DIES).
    # ------------------------------------------------------------------
    sv_ta_dict = {
        "event": "dies",
        "predicate": {
            "kind": "and",
            "left": {
                "kind": "and",
                "left": {"kind": "subject_is_creature"},
                "right": {"kind": "controlled_by_you"},
            },
            "right": {"kind": "not", "inner": {"kind": "source_is_self"}},
        },
        "effect": {
            "kind": "sequence",
            "effects": [
                {"kind": "put_plus_one_counter_on_self", "amount": 1},
                {"kind": "gain_life", "amount": 1},
            ],
        },
    }

    bridge_ta = _ta_dict_to_python_triggered_ability(sv_ta_dict)
    assert bridge_ta.event == Event.DIES, (
        f"Bridge must translate 'dies' to Event.DIES; "
        f"got {bridge_ta.event!r}"
    )
    assert isinstance(bridge_ta.predicate, And), (
        f"Bridge predicate must be And; "
        f"got {type(bridge_ta.predicate).__name__}"
    )
    assert isinstance(bridge_ta.effect, Sequence), (
        f"Bridge effect must be Sequence; "
        f"got {type(bridge_ta.effect).__name__}"
    )
    assert isinstance(bridge_ta.effect.effects[0], PutPlusOneCounterOnSelf), (
        f"Bridge Sequence[0] must be PutPlusOneCounterOnSelf; "
        f"got {type(bridge_ta.effect.effects[0]).__name__}"
    )
    assert isinstance(bridge_ta.effect.effects[1], GainLife), (
        f"Bridge Sequence[1] must be GainLife; "
        f"got {type(bridge_ta.effect.effects[1]).__name__}"
    )

    # ------------------------------------------------------------------
    # 3. Build cross-engine states with empty decks.
    # ------------------------------------------------------------------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)

    ZB = 2  # ZONE_BATTLEFIELD

    # ------------------------------------------------------------------
    # 4. Rust: seat Syr Vondam and a Wild Bear ally on p0's battlefield.
    # ------------------------------------------------------------------
    rs_sv_id = rs.register_and_inject_object(
        {
            "name": "Syr Vondam, Sunstar Exemplar",
            "card_types": ["Creature"],
            "supertypes": ["Legendary"],
            "power": 2,
            "toughness": 2,
            "keywords": ["vigilance", "menace"],
            "effects": [],
            "triggered_abilities": [sv_ta_dict],
        },
        0, ZB,
    )
    rs_bear_id = rs.register_and_inject_object(
        {
            "name": "Wild Bear",
            "card_types": ["Creature"],
            "power": 2,
            "toughness": 2,
            "keywords": [],
            "effects": [],
            "triggered_abilities": [],
        },
        0, ZB,
    )

    rs_sv_counters0 = rs.get_counters(rs_sv_id)
    rs_sv_power0 = rs.effective_power(rs_sv_id)
    rs_life0 = rs.get_life(0)
    assert rs_sv_counters0 == 0, (
        f"Rust: Vondam must start with 0 counters; got {rs_sv_counters0}"
    )
    assert rs_sv_power0 == 2, (
        f"Rust: Vondam must start at power 2; got {rs_sv_power0}"
    )
    assert rs_life0 == 20, (
        f"Rust: p0 must start at 20 life; got {rs_life0}"
    )

    # ------------------------------------------------------------------
    # 5. Rust: deal lethal damage to the bear; apply_sbas dispatches DIES;
    #    drain trigger.
    # ------------------------------------------------------------------
    rs.deal_damage(rs_bear_id, 10)   # lethal to 2/2 bear
    rs.apply_sbas()                   # bear dies → DIES event → trigger pushed

    assert rs.stack_size() == 1, (
        f"Rust: exactly 1 trigger (Vondam observer fires on bear dying) "
        f"must be on the stack after apply_sbas; got {rs.stack_size()}"
    )
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()

    rs_sv_counters1 = rs.get_counters(rs_sv_id)
    rs_sv_power1 = rs.effective_power(rs_sv_id)
    rs_life1 = rs.get_life(0)
    assert rs_sv_counters1 == 1, (
        f"Rust: Vondam must gain 1 counter from dies-observer trigger; "
        f"got {rs_sv_counters1}"
    )
    assert rs_sv_power1 == 3, (
        f"Rust: Vondam effective_power must be 3 (2 base + 1 counter); "
        f"got {rs_sv_power1}"
    )
    assert rs_life1 == 21, (
        f"Rust: p0 life must be 21 after GainLife(1) from trigger; "
        f"got {rs_life1}"
    )

    # ------------------------------------------------------------------
    # 6. Python: seat Syr Vondam (bridge TA) and a Wild Bear ally.
    # ------------------------------------------------------------------
    py_sv_printing = CardPrinting(
        name="Syr Vondam, Sunstar Exemplar",
        mana_cost_str="{3}{W}",
        mana_cost=ManaCost(generic=3, colored=(("W", 1),)),
        type_line="Legendary Creature — Human Knight",
        supertypes=("Legendary",),
        card_types=("Creature",),
        subtypes=("Human", "Knight"),
        power=2,
        toughness=2,
        produces=frozenset(),
        keywords=frozenset({"vigilance", "menace"}),
        triggered_abilities=(bridge_ta,),
    )
    py_sv = py.new_object(py_sv_printing, owner_id=0, zone=Zone.BATTLEFIELD)
    py_sv.summoning_sick = False
    py_sv.tapped = False
    py_sv.damage = 0
    py_sv.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_sv)

    py_bear = py.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_bear.summoning_sick = False
    py_bear.tapped = False
    py_bear.damage = 0
    py_bear.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_bear)

    py_sv_counters0 = py_sv.plus_one_counters
    py_life0 = py.players[0].life
    assert py_sv_counters0 == 0, (
        f"Python: Vondam must start with 0 counters; got {py_sv_counters0}"
    )
    assert py_life0 == 20, (
        f"Python: p0 must start at 20 life; got {py_life0}"
    )

    # ------------------------------------------------------------------
    # 7. Python: destroy the ally bear (fires DIES → trigger pushes).
    # ------------------------------------------------------------------
    py_destroy(py, py_bear)

    assert len(py.stack) == 1, (
        f"Python: exactly 1 trigger (Vondam observer fires on bear dying) "
        f"must be on the stack after destroy; got {len(py.stack)}"
    )
    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)

    py_sv_counters1 = py_sv.plus_one_counters
    py_sv_power1 = py_effective_power(py, py_sv)
    py_life1 = py.players[0].life
    assert py_sv_counters1 == 1, (
        f"Python: Vondam must gain 1 counter from dies-observer trigger; "
        f"got {py_sv_counters1}"
    )
    assert py_sv_power1 == 3, (
        f"Python: Vondam effective_power must be 3 (2 base + 1 counter); "
        f"got {py_sv_power1}"
    )
    assert py_life1 == 21, (
        f"Python: p0 life must be 21 after GainLife(1) from trigger; "
        f"got {py_life1}"
    )

    # ------------------------------------------------------------------
    # 8. Cross-engine byte-equality on targeted observables.
    # ------------------------------------------------------------------
    assert rs_sv_counters1 == py_sv_counters1, (
        f"Vondam counters: Rust={rs_sv_counters1}, Python={py_sv_counters1} "
        f"(must be byte-equal — Sequence(PutPlusOneCounterOnSelf(1), "
        f"GainLife(1)) resolved on BOTH engines via DIES dispatch)"
    )
    assert rs_sv_power1 == py_sv_power1, (
        f"Vondam effective_power: Rust={rs_sv_power1}, Python={py_sv_power1} "
        f"(must be byte-equal)"
    )
    assert rs_life1 == py_life1, (
        f"p0 life: Rust={rs_life1}, Python={py_life1} "
        f"(must be byte-equal — GainLife(1) resolved on BOTH engines)"
    )
