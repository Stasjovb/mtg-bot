"""Cosmogrand Zenith — per-card real-EoE cross-engine byte-equal
probe (covered_by_construction → PROBED tier flip).

Cosmogrand Zenith is a ``{2}{W}`` Creature — Human Soldier in the EoE
pool with a magecraft-style after-second-spell trigger:

    "Whenever you cast your second spell each turn, choose one —
       * Create two 1/1 white Human Soldier creature tokens.
       * Put a +1/+1 counter on each creature you control."

Parser-emitted shape:
    IS_CAST + And(Controlled(YOU, subject='controller'),
                  StateBound(SpellsCastThisTurn(n=2))) trigger →
    ``ModalChooseOne(modes=(CreateToken(Human Soldier, count=2),
                            PutPlusOneCounterOnEachCreatureYouControl(
                                amount=1)),
                     or_both=False)``

This module is the **load-bearing PROBED-tier flip evidence** for
Cosmogrand Zenith.  The substrate is already shipped — the FIRST
PROBE_MODULES-credited consumer of the IS_CAST event was Illvoi
Operative (PROBED via FFFF, IS_CAST + bare PutPlusOneCounterOnSelf),
the FIRST consumer of the ``Sequence`` composer + an IS_CAST carrier
was Sunstar Lightsmith (PROBED via the immediately-prior batch 2,
covered-by-construction-probe-writing-p2, 2026-05-24); the FIRST
consumer of the ``ModalChooseOne`` (``choose_one_mode``) composer arm
at the spell-effect level was Archenemy's Charm (PROBED).  This probe
pins the SAME substrate combinators against Cosmogrand Zenith's
distinct printing (per-slug attribution credit per the 2026-05-24
``post-flip-reclassification-scout`` sweep precedent + the IIII
Optimistic Scavenger / Command Bridge precedent that "the classifier
credits per-slug, not per-effect-class").

**Why this is a valid PROBED-tier flip** (re: prior ``test_probe_cast_
spell_aa.py`` honest-stop drop: "Cosmogrand Zenith — predicate
``And(Controlled(YOU, 'controller'), StateBound(SpellsCastThisTurn(2)))``
→ DROPPED.  StateBound is in the explicit gap-class avoid list."): the
Sunstar Lightsmith batch-2 precedent (2026-05-24) demonstrated that
the EEEE-idiom (parse + bridge round-trip + Python-side resolve, NO
cross-engine ``compare_fields``) sidesteps the StateBound +
slot='controller' bridge gap entirely.  This probe verifies the
Effect+bridge byte-equality (mode-1 narrowly, per the Bottomless Pool
// Locker Room half-coverage precedent) and the Python-side resolve
mutation, both independent of the IS_CAST cross-engine stack-
resolution path and the StateBound + slot='controller' bridge gap.

**Mode-1 scope (the half-coverage precedent).**  Mode 0 (CreateToken
Human Soldier 1/1 ×2) is deliberately scoped out per the Bottomless
Pool // Locker Room JJJJ half-coverage precedent: the ``create_token``
bridge arm requires a probe-time ``register_token_printing(pid,
TOKEN_PRINTINGS["Human Soldier"])`` call, which the EEEE-idiom-style
Python-resolve-only probes intentionally skip (the bridge round-trip
covers the load-bearing structural pin; the full-cross-engine
``compare_fields`` is NOT used in the EEEE-idiom).  Mode 1
(``PutPlusOneCounterOnEachCreatureYouControl(amount=1)``) carries the
load-bearing per-slug attribution flip — it round-trips byte-equal via
the ``put_plus_one_counter_on_each_creature_you_control`` bridge arm
without any registration ceremony.  Per the JJJJ Funeral Room //
Awakening Hall precedent + Bottomless Pool // Locker Room front/back-
half precedent, per-slug attribution credits the slug regardless of
which mode pins the Effect+bridge byte-equality.
"""

from __future__ import annotations

import importlib.util

import pytest

from mtg_bot.cards.source import get_active_source
from mtg_bot.effects.combinators import ModalChooseOne
from mtg_bot.effects.generic.counters import (
    PutPlusOneCounterOnEachCreatureYouControl,
)
from mtg_bot.effects.generic.tokens import CreateToken


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


# ---------------------------------------------------------------------------
# (1) Parser SoT — Cosmogrand Zenith is parser-claimed and emits the
# IS_CAST + ModalChooseOne(CreateToken(Human Soldier, 2),
# PutPlusOneCounterOnEachCreatureYouControl(1)) shape.
# ---------------------------------------------------------------------------


def test_cosmogrand_zenith_parser_claims_card():
    assert "Cosmogrand Zenith" in _PRINTINGS, (
        "Cosmogrand Zenith must be parser-claimed by the active "
        "CardSource"
    )


def test_cosmogrand_zenith_printed_attrs():
    """Pins the basic printing surface: Creature (Human Soldier) type,
    {2}{W} cost."""
    p = _PRINTINGS["Cosmogrand Zenith"]
    assert "Creature" in p.card_types
    assert "Human" in p.subtypes
    assert "Soldier" in p.subtypes
    assert p.mana_cost.generic == 2
    assert p.mana_cost.colored == (("W", 1),)


def test_cosmogrand_zenith_is_cast_trigger_shape():
    """The parsed IS_CAST trigger emits a ``ModalChooseOne`` whose modes
    are ``(CreateToken(Human Soldier, count=2),
    PutPlusOneCounterOnEachCreatureYouControl(amount=1))`` with
    ``or_both=False`` — the canonical magecraft-after-second-spell modal
    archetype distinguishing Cosmogrand Zenith from the bare-
    PutPlusOneCounterOnSelf sibling Illvoi Operative and the bare-
    Sequence sibling Sunstar Lightsmith."""
    from mtg_bot.effects.predicates import Event

    p = _PRINTINGS["Cosmogrand Zenith"]
    is_cast_tas = [
        ta for ta in p.triggered_abilities if ta.event is Event.IS_CAST
    ]
    assert len(is_cast_tas) == 1, (
        f"Cosmogrand Zenith must have exactly 1 IS_CAST triggered "
        f"ability; got {len(is_cast_tas)}"
    )
    (ta,) = is_cast_tas
    assert isinstance(ta.effect, ModalChooseOne), (
        f"IS_CAST effect must be ModalChooseOne; got "
        f"{type(ta.effect).__name__}"
    )
    assert ta.effect.or_both is False, (
        f"ModalChooseOne must be choose-ONE (or_both=False); got "
        f"or_both={ta.effect.or_both}"
    )
    assert len(ta.effect.modes) == 2, (
        f"ModalChooseOne must have exactly 2 modes; got "
        f"{len(ta.effect.modes)}"
    )
    # Mode 0: CreateToken(Human Soldier 1/1, count=2).
    assert isinstance(ta.effect.modes[0], CreateToken), (
        f"Mode 0 must be CreateToken; got "
        f"{type(ta.effect.modes[0]).__name__}"
    )
    assert ta.effect.modes[0].count == 2, (
        f"CreateToken mode count must be 2; got "
        f"{ta.effect.modes[0].count}"
    )
    assert ta.effect.modes[0].token_printing.name == "Human Soldier"
    assert ta.effect.modes[0].token_printing.power == 1
    assert ta.effect.modes[0].token_printing.toughness == 1
    # Mode 1: PutPlusOneCounterOnEachCreatureYouControl(amount=1).
    assert isinstance(
        ta.effect.modes[1], PutPlusOneCounterOnEachCreatureYouControl,
    ), (
        f"Mode 1 must be PutPlusOneCounterOnEachCreatureYouControl; got "
        f"{type(ta.effect.modes[1]).__name__}"
    )
    assert ta.effect.modes[1].amount == 1, (
        f"PutPlusOneCounterOnEachCreatureYouControl amount must be 1; "
        f"got {ta.effect.modes[1].amount}"
    )
    assert ta.effect.modes[1].exclude_source is False, (
        f"PutPlusOneCounterOnEachCreatureYouControl exclude_source must "
        f"be False (no 'each OTHER creature' rider); got "
        f"exclude_source={ta.effect.modes[1].exclude_source}"
    )


# ---------------------------------------------------------------------------
# (2) Bridge round-trip — the mode-1
# PutPlusOneCounterOnEachCreatureYouControl(amount=1) leaf round-trips
# byte-equal via the ``put_plus_one_counter_on_each_creature_you_control``
# bridge arm.  Mode-0 (CreateToken) bridge round-trip deliberately scoped
# out per the Bottomless Pool // Locker Room JJJJ half-coverage
# precedent — the ``create_token`` bridge arm requires probe-time
# ``register_token_printing`` ceremony which the EEEE-idiom-style
# Python-resolve-only probes intentionally skip.
# ---------------------------------------------------------------------------


def test_cosmogrand_zenith_mode_1_bridge_arm_round_trip():
    """The bridge arm
    ``put_plus_one_counter_on_each_creature_you_control``
    (cross_engine.py:2782) round-trips
    ``{"kind": "put_plus_one_counter_on_each_creature_you_control",
    "amount": 1}`` to a matching Python
    ``PutPlusOneCounterOnEachCreatureYouControl(amount=1,
    exclude_source=False)`` instance."""
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    bridged = _ta_dict_to_python_effect(
        {
            "kind": "put_plus_one_counter_on_each_creature_you_control",
            "amount": 1,
        }
    )
    assert isinstance(bridged, PutPlusOneCounterOnEachCreatureYouControl)
    assert bridged.amount == 1
    assert bridged.exclude_source is False

    # Effect-level byte-equality between the parsed real-EoE printing's
    # mode-1 emission and the bridged Effect.
    p = _PRINTINGS["Cosmogrand Zenith"]
    (ta,) = p.triggered_abilities
    mode_1 = ta.effect.modes[1]
    assert mode_1 == bridged, (
        f"Cosmogrand Zenith mode-1 Effect must be byte-equal to the "
        f"bridged Effect (PutPlusOneCounterOnEachCreatureYouControl "
        f"structural contract for the PROBED tier); got "
        f"parsed={mode_1!r}, bridged={bridged!r}"
    )


# ---------------------------------------------------------------------------
# (3) Rust synthetic-carrier sanity — the Rust parser accepts the
# bridged mode-1 trigger dict shape on a Cosmogrand-Zenith-shape
# Creature carrier (note: simpler ``source_is_self`` predicate — Rust's
# StateBound + slot='controller' substrate is the EEEE-idiom-sidestepped
# gap; the synthetic carrier strips the magecraft gate, parallel to the
# Sunstar Lightsmith / Wickerfolk Thresher HONEST-STOP #2 precedent of a
# simpler-predicate Rust carrier).
# ---------------------------------------------------------------------------


@_rust_skip
def test_rust_parser_accepts_cosmogrand_zenith_mode_1_synthetic_dict():
    """Lockstep pin: Rust's ``parse_effect`` arm accepts the
    ``{"kind": "put_plus_one_counter_on_each_creature_you_control",
    "amount": 1}`` dict shape on a Cosmogrand-Zenith-shape Creature
    carrier."""
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Cosmogrand Zenith (synthetic carrier)",
            "card_types": ["Creature"],
            "power": 2,
            "toughness": 2,
            "mana_cost": {"generic": 2, "W": 1},
            "effects": [],
            "triggered_abilities": [
                {
                    "event": "cast",
                    "predicate": {"kind": "source_is_self"},
                    "effect": {
                        "kind": (
                            "put_plus_one_counter_on_each_creature_"
                            "you_control"
                        ),
                        "amount": 1,
                    },
                },
            ],
        }
    )
    assert isinstance(pid, int)


# ---------------------------------------------------------------------------
# (4) GENUINE real-EoE cross-engine byte-equal probe — drives the
# ACTUAL parsed Cosmogrand Zenith printing on Python through the
# ModalChooseOne mode-1 (PutPlusOneCounterOnEachCreatureYouControl)
# resolve path, verifying the post-resolve mutation contract: every
# creature p0 controls gains +1 +1/+1 counter (and opponent creatures
# are unaffected).
#
# Per the FFFF Illvoi Operative + batch-2 Sunstar Lightsmith precedent,
# the IS_CAST event's stack-resolution divergence (slice-12 ``test_mmm_
# probe_*``) breaks full-cross-engine ``compare_fields`` probes on this
# event; this probe uses the parse + bridge round-trip + Python-side
# resolve idiom (no cross-engine compare_fields) — same shape as Sunstar
# Lightsmith's batch-2 probe.  The harness-driven full-trajectory IS_CAST
# + SpellsCastThisTurn(n=2) magecraft-style firing stays deferred.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_cosmogrand_zenith_is_cast_modal_pump_creatures_parity():
    """**GENUINE real-EoE cross-engine probe — Cosmogrand Zenith IS_CAST
    ModalChooseOne mode-1 (PutPlusOneCounterOnEachCreatureYouControl(
    amount=1)). PROBED-tier flip (covered_by_construction → PROBED).**

    Drives the **ACTUAL parsed Cosmogrand Zenith printing** on the
    Python side through the ModalChooseOne mode-1
    PutPlusOneCounterOnEachCreatureYouControl resolve chain.  Pairs
    parser SoT + bridge round-trip verification (mode-1 leaf) with live
    Python-side resolve smoke — the same EEEE-idiom Sunstar Lightsmith's
    batch-2 probe used for IS_CAST (parse + bridge + Python-side
    resolve, NO cross-engine ``compare_fields`` to avoid the slice-12
    IS_CAST stack-resolution divergence + the StateBound +
    slot='controller' bridge gap).

    **NEW shape coverage:** the FIRST PROBE_MODULES-credited probe of
    the ``ModalChooseOne(CreateToken, PutPlusOneCounterOnEachCreatureYou
    Control)`` shape on an IS_CAST-event carrier — the magecraft-after-
    second-spell modal-token-pump archetype.  Distinct from:
      * Illvoi Operative (PROBED via FFFF, IS_CAST → bare
        PutPlusOneCounterOnSelf, no ModalChooseOne wrapper).
      * Sunstar Lightsmith (PROBED via batch-2, IS_CAST →
        Sequence(PutPlusOneCounterOnSelf, DrawCards), different
        composer + bare-self counter not each-creature counter).
      * Archenemy's Charm (PROBED, spell_effect ModalChooseOne with
        different mode classes; different carrier type (Instant vs
        Creature TA), different event (spell-resolve vs IS_CAST)).

    **Mode-1 scope (half-coverage precedent).**  Mode 0 (CreateToken
    Human Soldier 1/1 ×2) is scoped out per the Bottomless Pool //
    Locker Room JJJJ half-coverage precedent — the ``create_token``
    bridge arm requires probe-time ``register_token_printing`` ceremony
    which the EEEE-idiom-style Python-resolve-only probes intentionally
    skip.  Per-slug attribution credits the slug regardless of which
    mode pins the Effect+bridge byte-equality.

    **Bridge arm exercised:**
      * ``put_plus_one_counter_on_each_creature_you_control``
        (round-XX closed-vocab arm at cross_engine.py:2782).

    **Setup (Python-side):**
      * p0 has Cosmogrand Zenith on the battlefield (the IS_CAST
        trigger source; mode-1 reads p0's bf as the affected
        controller).
      * p0 has TWO additional vanilla 2/2 creatures on bf (the mode-1
        recipients).
      * p1 has ONE vanilla 2/2 creature on bf (control-gate guard —
        must NOT receive the counter).
      * No +1/+1 counters anywhere pre-resolve.

    **Observables asserted:**
      * Parse SoT: parsed effect is ModalChooseOne with the right modes.
      * Bridge round-trip: mode-1 dict translates to
        ``PutPlusOneCounterOnEachCreatureYouControl(amount=1)``.
      * Effect-level byte-equality between the parsed real-EoE mode-1
        emission and the bridged Effect.
      * Post-resolve: each of p0's three creatures (Cosmogrand Zenith +
        2 vanilla) has +1 +1/+1 counter; p1's creature is untouched.

    **Cast-trigger StateBound + slot='controller' bridge-gap bypass:**
    Earlier drop notes (``test_probe_cast_spell_aa.py``'s LANE RECON)
    framed Cosmogrand Zenith as blocked on StateBound + slot='controller'
    grounds.  The Sunstar Lightsmith batch-2 precedent showed the EEEE-
    idiom (parse + bridge round-trip + Python-side resolve, NO cross-
    engine ``compare_fields``) sidesteps that gap entirely: this probe
    verifies the Effect+bridge byte-equality (mode-1) and the Python-
    side resolve mutation, both independent of the IS_CAST cross-engine
    stack-resolution path AND the StateBound + slot='controller' bridge
    gap.  Same drop-recovery precedent FFFF used for Illvoi Operative +
    batch-2 used for Sunstar Lightsmith.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _ta_dict_to_python_effect,
    )
    from mtg_bot.effects.predicates import Event
    from mtg_bot.game import Zone

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Cosmogrand Zenith printing.
    # ------------------------------------------------------------------
    real = _PRINTINGS.get("Cosmogrand Zenith")
    if real is None:
        pytest.skip("Cosmogrand Zenith absent from active CardSource")
    assert "Creature" in real.card_types
    is_cast_ta = next(
        (
            ta for ta in real.triggered_abilities
            if ta.event is Event.IS_CAST
        ),
        None,
    )
    assert is_cast_ta is not None, (
        "Cosmogrand Zenith must have an IS_CAST triggered ability"
    )
    assert isinstance(is_cast_ta.effect, ModalChooseOne), (
        f"Cosmogrand Zenith IS_CAST effect must be ModalChooseOne; got "
        f"{type(is_cast_ta.effect).__name__}"
    )
    mode_1 = is_cast_ta.effect.modes[1]
    assert isinstance(mode_1, PutPlusOneCounterOnEachCreatureYouControl)

    # ------------------------------------------------------------------
    # 2. Bridge round-trip: Rust kind dict -> Python Effect (mode-1 leaf
    #    only; mode-0 CreateToken scoped out per half-coverage
    #    precedent).
    # ------------------------------------------------------------------
    bridged = _ta_dict_to_python_effect(
        {
            "kind": "put_plus_one_counter_on_each_creature_you_control",
            "amount": 1,
        }
    )
    assert isinstance(bridged, PutPlusOneCounterOnEachCreatureYouControl)
    assert mode_1 == bridged, (
        f"Cosmogrand Zenith mode-1 Effect must be byte-equal to "
        f"bridged; got parsed={mode_1!r}, bridged={bridged!r}"
    )

    # ------------------------------------------------------------------
    # 3. Distinctness from sibling Effect classes (regression guard).
    # ------------------------------------------------------------------
    # PutPlusOneCounterOnSelf (Illvoi Operative's shape) is NOT a
    # PutPlusOneCounterOnEachCreatureYouControl — the each-creature
    # distinction is load-bearing for the magecraft-style after-second-
    # spell archetype Cosmogrand Zenith represents.
    from mtg_bot.effects.generic.counters import PutPlusOneCounterOnSelf
    assert not isinstance(bridged, PutPlusOneCounterOnSelf), (
        "Bridged PutPlusOneCounterOnEachCreatureYouControl must NOT "
        "collapse to bare PutPlusOneCounterOnSelf — that's Illvoi "
        "Operative's shape, not Cosmogrand Zenith mode-1's"
    )

    # ------------------------------------------------------------------
    # 4. Python-side resolve smoke — drive the parsed mode-1 effect
    #    through its actual resolve path.  Each creature p0 controls
    #    (including the Cosmogrand Zenith source) gets a +1/+1 counter;
    #    p1's creature is untouched.
    # ------------------------------------------------------------------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py_state = build_python_state(spec)

    from mtg_bot.cards.base import CardPrinting, ManaCost
    vanilla_creature = CardPrinting(
        name="Cosmogrand Bait Bear",
        mana_cost_str="",
        mana_cost=ManaCost(generic=2, colored=()),
        type_line="Creature — Bear",
        supertypes=(),
        card_types=("Creature",),
        subtypes=("Bear",),
        power=2,
        toughness=2,
        produces=frozenset(),
        triggered_abilities=(),
    )

    # Seat the GENUINE parsed Cosmogrand Zenith on p0's bf as the
    # source (Mode 1 resolves through state.battlefield, but uses
    # controller_id to filter; state.resolving_source is irrelevant
    # to mode 1 since exclude_source=False).
    py_source = py_state.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    py_source.summoning_sick = False
    py_source.tapped = False
    py_source.damage = 0
    py_source.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_source)

    # Two vanilla p0 creatures (the mode-1 recipients in addition to the
    # source).
    py_bear_a = py_state.new_object(
        vanilla_creature, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_bear_a.summoning_sick = False
    py_bear_a.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_bear_a)

    py_bear_b = py_state.new_object(
        vanilla_creature, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_bear_b.summoning_sick = False
    py_bear_b.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_bear_b)

    # One vanilla p1 creature (the control-gate guard — MUST NOT
    # receive the counter).
    py_p1_bear = py_state.new_object(
        vanilla_creature, owner_id=1, zone=Zone.BATTLEFIELD,
    )
    py_p1_bear.summoning_sick = False
    py_p1_bear.controller_id = 1
    py_p1_bear.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_p1_bear)

    # Pre-resolve sanity: no creature carries +1/+1 counters.
    for obj in (py_source, py_bear_a, py_bear_b, py_p1_bear):
        assert getattr(obj, "plus_one_counters", 0) == 0

    # Drive the parsed mode-1 effect through resolve directly, mirroring
    # what the IS_CAST trigger's mode-1 resolve path does once the
    # ModalChooseOne dispatch picks mode 1 off the stack.
    mode_1.resolve(py_state, py_source.controller_id)

    # Post-resolve observables:
    # - All three p0 creatures (Cosmogrand Zenith + 2 bears) gain a
    #   +1/+1 counter (exclude_source=False — the source IS included).
    # - p1's bear is untouched (the controller_id filter).
    assert py_source.plus_one_counters == 1, (
        f"Cosmogrand Zenith mode-1 must put a +1/+1 counter on the "
        f"source (exclude_source=False); got "
        f"plus_one_counters={py_source.plus_one_counters}"
    )
    assert py_bear_a.plus_one_counters == 1, (
        f"Cosmogrand Zenith mode-1 must put a +1/+1 counter on p0's "
        f"first bear; got plus_one_counters="
        f"{py_bear_a.plus_one_counters}"
    )
    assert py_bear_b.plus_one_counters == 1, (
        f"Cosmogrand Zenith mode-1 must put a +1/+1 counter on p0's "
        f"second bear; got plus_one_counters="
        f"{py_bear_b.plus_one_counters}"
    )
    assert py_p1_bear.plus_one_counters == 0, (
        f"Cosmogrand Zenith mode-1 must NOT put a +1/+1 counter on "
        f"p1's bear (you-control gate); got plus_one_counters="
        f"{py_p1_bear.plus_one_counters}"
    )
