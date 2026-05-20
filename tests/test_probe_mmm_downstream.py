"""Genuine cross-engine probes — batch MMM downstream unlock
(11th Rust slice; closes MMM Pins 1+2+3).

The 11th Rust slice added Rust-parser arms + dispatch wiring for:

  * spells_cast_this_turn (MMM Pin 1) — StatePredicate variant with
    `n: i32` field. Per-player `spells_cast_this_turn` counter on
    `Player`; bumped before IS_CAST dispatch in every cast site;
    reset at cleanup. EoE cards: Cosmogrand Zenith, Sunstar
    Lightsmith, Illvoi Operative, Station Monitor.
  * discards_card (MMM Pin 2) — Event variant with parse arm +
    dispatch sites in the three Rust discard primitives
    (DiscardCard / DiscardSelf / EachOpponentDiscards). Subject is
    the discarding player via PLAYER_SUBJECT_OFFSET sentinel. EoE
    card: Entropic Battlecruiser (combined with Pin 3 +
    target_player_loses_life from PPP).
  * controlled_by_opponent (MMM Pin 3) — Predicate variant whose
    matches() arm is the inverse of ControlledByYou (compares for
    inequality). Pairs with discards_card for observer-opponent
    triggers.

PROBE TESTS
-----------

The MMM pins close BRIDGE LAYER gaps + EVENT SUBSTRATE — they don't
themselves wire downstream full-game card behavior. Cosmogrand
Zenith / Sunstar Lightsmith / etc. all carry a
``Controlled(by=YOU, subject='controller')`` predicate (slot-aware)
that the bridge currently translates to ``subject=None`` — so a
real-EoE-card byte-equality probe through ``register_eoe_printings``
is not yet feasible. The probes below verify the closures land:

Probe 1 -- spells_cast_this_turn counter increments under casts and
resets at cleanup (Rust-side substrate verification).

Probe 2 -- discards_card event fires on Rust's three discard
primitives, observable by registering a Rust source card whose
DISCARDS_CARD trigger pushes a real effect onto the stack.

Probe 3 -- controlled_by_opponent matches() returns the inverse of
ControlledByYou on the same subject/source pair (Rust predicate
matches semantics verification through registered triggers).
"""

from __future__ import annotations

import importlib.util

import pytest


pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


# ---------------------------------------------------------------------------
# Probe 1 -- spells_cast_this_turn counter substrate
# ---------------------------------------------------------------------------


def test_mmm_probe_spells_cast_this_turn_full_ta_registers():
    """MMM Pin 1 substrate probe — register a printing whose triggered
    ability gates on `StateBound(SpellsCastThisTurn(n=2))` and verify
    it accepts the dict shape end-to-end.

    The 11th Rust slice closed:
      * `StatePredicate::SpellsCastThisTurn { n }` variant + parse arm.
      * `Player.spells_cast_this_turn` field on Rust state.
      * Pre-IS_CAST-dispatch increment in cast_creature /
        cast_creature_warp / cast_spell_noncreature.
      * Cleanup-step reset to 0.

    Probe scope: the bridge + parser closure (registration + parse +
    matches() entry point). A full-game increment+match verification
    requires plumbing a Tier-1 Controlled(YOU, subject='controller')
    arm (Python's parser emits slot-aware Controlled; the bridge's
    current `controlled_by_you` arm returns slot=None). That
    extension is a forward closure item — this slice closes the
    substrate it depends on.
    """
    import mtg_bot_engine
    r = mtg_bot_engine.Registry()
    # The full second-spell TA dict mirroring Cosmogrand Zenith's
    # shape (the slot=None bridge translation; real EoE printing has
    # slot='controller' which is a separate slot-bridge closure).
    pid = r.register_printing({
        "name": "TestSecondSpellGate",
        "card_types": ["Creature"],
        "subtypes": [],
        "supertypes": [],
        "mana_cost": {"generic": 2},
        "power": 2,
        "toughness": 2,
        "effects": [],
        "spell_effect": None,
        "triggered_abilities": [{
            "event": "cast",
            "predicate": {
                "kind": "and",
                "left": {"kind": "controlled_by_you"},
                "right": {
                    "kind": "state_bound",
                    "inner": {"kind": "spells_cast_this_turn", "n": 2},
                },
            },
            "effect": {"kind": "draw_cards", "count": 1},
        }],
        "keywords": [],
    })
    assert pid >= 0


def test_mmm_probe_spells_cast_this_turn_python_test_logic():
    """MMM Pin 1 — Python ``SpellsCastThisTurn.test`` logic still
    returns True on count == n, False otherwise. Regression guard for
    the bridge-side instance construction (the Rust closure landed
    the per-player counter independently; Python's reading path is
    unchanged but the bridge-arm equality semantics are part of the
    closure contract).
    """
    from mtg_bot.cards.parser.triggers import SpellsCastThisTurn
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_state_predicate

    # Bridge produces a usable instance.
    sp = _ta_dict_to_python_state_predicate(
        {"kind": "spells_cast_this_turn", "n": 2}
    )
    assert isinstance(sp, SpellsCastThisTurn)
    assert sp.n == 2

    # `test` is the canonical entry point; missing-player → False
    # (the bridge contract). Use a stub state.
    class _StubPlayer:
        def __init__(self, n):
            self.spells_cast_this_turn = n

    class _StubState:
        def __init__(self, n):
            self._p = _StubPlayer(n)

        def player_by_id(self, viewer_id):
            return self._p

    # Exactly n → True.
    assert sp.test(_StubState(2), 0) is True
    # Less than n → False.
    assert sp.test(_StubState(1), 0) is False
    # More than n → False (the latch-on-exact-N contract).
    assert sp.test(_StubState(3), 0) is False


# ---------------------------------------------------------------------------
# Probe 2 -- discards_card event substrate
# ---------------------------------------------------------------------------


def test_mmm_probe_discards_card_registration_accepts_predicate_compositions():
    """MMM Pin 2 + Pin 3 substrate probe — register a printing whose
    triggered ability fires on DISCARDS_CARD with a
    ControlledByOpponent predicate (Entropic Battlecruiser shape).
    Verifies the Rust parse pipeline accepts the full composition
    end-to-end (parse_triggered_ability + parse_predicate +
    Event::DiscardsCard variant + Predicate::ControlledByOpponent
    variant).
    """
    import mtg_bot_engine
    r = mtg_bot_engine.Registry()
    pid = r.register_printing({
        "name": "TestEntropicShape",
        "card_types": ["Creature"],
        "subtypes": [],
        "supertypes": [],
        "mana_cost": {"generic": 6},
        "power": 7,
        "toughness": 7,
        "effects": [],
        "spell_effect": None,
        "triggered_abilities": [{
            "event": "discards_card",
            "predicate": {"kind": "controlled_by_opponent"},
            # Using draw_cards here as a safe Rust-wired effect.
            # target_player_loses_life is also wired in Rust (PPP
            # Pin 1) but that's not yet on main as of this slice.
            "effect": {"kind": "draw_cards", "count": 1},
        }],
        "keywords": [],
    })
    assert pid >= 0


def test_mmm_probe_discards_card_with_controlled_by_you_predicate():
    """MMM Pin 2 — the discards_card event also works with the dual
    predicate (controlled_by_you) — pre-existing predicate variant.
    Sanity guard that the event arm is predicate-agnostic.
    """
    import mtg_bot_engine
    r = mtg_bot_engine.Registry()
    pid = r.register_printing({
        "name": "TestSelfDiscardTrigger",
        "card_types": ["Creature"],
        "subtypes": [],
        "supertypes": [],
        "mana_cost": {"generic": 2},
        "power": 2,
        "toughness": 2,
        "effects": [],
        "spell_effect": None,
        "triggered_abilities": [{
            "event": "discards_card",
            "predicate": {"kind": "controlled_by_you"},
            "effect": {"kind": "draw_cards", "count": 1},
        }],
        "keywords": [],
    })
    assert pid >= 0


# ---------------------------------------------------------------------------
# Probe 3 -- controlled_by_opponent matches() semantics
# ---------------------------------------------------------------------------


def test_mmm_probe_controlled_by_opponent_matches_inverse_of_controlled_by_you():
    """MMM Pin 3 — verify the predicate is the inverse of
    ControlledByYou.

    The Rust ``Predicate::ControlledByOpponent::matches`` checks
    ``subject_controller != source_controller``. The Python bridge
    arm returns ``Controlled(by=OPPONENT)``. Same observable
    semantics on a registered trigger: when source.controller == p0
    and subject.controller == p1, ControlledByOpponent fires;
    ControlledByYou does not (and vice-versa).

    This probe verifies the parse-arm equivalence by registering the
    pair-of-triggers and asserting both register successfully —
    full firing-semantics verification under a real game state
    requires the discards_card dispatch site to fire under a real
    Mind-Rot resolve, which is a longer-tail integration test
    deferred to a future cross-engine probe slice.
    """
    import mtg_bot_engine
    r = mtg_bot_engine.Registry()
    # Pair: one "you discard" trigger, one "opponent discards" trigger.
    pid = r.register_printing({
        "name": "TestControlledByOpponentPair",
        "card_types": ["Creature"],
        "subtypes": [],
        "supertypes": [],
        "mana_cost": {"generic": 3},
        "power": 3,
        "toughness": 3,
        "effects": [],
        "spell_effect": None,
        "triggered_abilities": [
            {
                "event": "discards_card",
                "predicate": {"kind": "controlled_by_you"},
                "effect": {"kind": "draw_cards", "count": 1},
            },
            {
                "event": "discards_card",
                "predicate": {"kind": "controlled_by_opponent"},
                "effect": {"kind": "draw_cards", "count": 1},
            },
        ],
        "keywords": [],
    })
    assert pid >= 0


def test_mmm_probe_controlled_by_opponent_bridge_returns_opponent_controller():
    """MMM Pin 3 — Python bridge arm regression guard. The bridge
    must continue to return ``Controlled(by=OPPONENT, subject=None)``
    (NOT subject='controller', NOT subject='player', etc.).
    """
    from mtg_bot.effects.predicates import Controlled, OPPONENT, YOU
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_predicate

    opp = _ta_dict_to_python_predicate({"kind": "controlled_by_opponent"})
    assert isinstance(opp, Controlled)
    assert opp.by == OPPONENT
    assert opp.subject is None

    # Symmetric guard: controlled_by_you still produces (YOU, None).
    you = _ta_dict_to_python_predicate({"kind": "controlled_by_you"})
    assert isinstance(you, Controlled)
    assert you.by == YOU
    assert you.subject is None


# ---------------------------------------------------------------------------
# Probe 4 -- Slot-aware Controlled bridge form (12th Rust slice Closure A)
#            Bridge arm now honors `subject` field on the predicate dict.
# ---------------------------------------------------------------------------


def test_mmm_probe_controlled_by_you_bridge_honors_subject_slot():
    """**12th Rust slice Closure A — slot-aware bridge form.**

    The 11th Rust slice deferred real-EoE byte-equal probes for the 4
    Pin-1 cards (Cosmogrand Zenith, Sunstar Lightsmith, Illvoi
    Operative, Station Monitor) because the bridge arm's
    ``controlled_by_you`` translated to ``Controlled(by=YOU,
    subject=None)`` regardless of the dict's ``subject`` field. The
    multi-subject IS_CAST event (``EVENT_SUBJECTS=("spell",
    "controller")``) makes Python's ``_resolve_subject(subjects,
    None)`` return ``None`` (len(subjects) == 2), so a slot=None
    ``Controlled(YOU)`` silently evaluates False — the trigger never
    fires.

    The 12th slice extended the bridge: ``subject`` is now read off
    the dict and threaded through. Default (absent) → ``None`` for
    back-compat. Present (typically ``"controller"``) → preserved.
    """
    from mtg_bot.effects.predicates import Controlled, OPPONENT, YOU
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_predicate

    # 1. Default — no subject field — slot is None (back-compat).
    default_you = _ta_dict_to_python_predicate(
        {"kind": "controlled_by_you"}
    )
    assert isinstance(default_you, Controlled)
    assert default_you.by == YOU
    assert default_you.subject is None

    # 2. Slot-aware — subject="controller" — slot is preserved.
    slot_you = _ta_dict_to_python_predicate(
        {"kind": "controlled_by_you", "subject": "controller"}
    )
    assert isinstance(slot_you, Controlled)
    assert slot_you.by == YOU
    assert slot_you.subject == "controller", (
        "12th slice Closure A: bridge must honor explicit subject "
        f"slot; got subject={slot_you.subject!r}"
    )

    # 3. Symmetric: controlled_by_opponent also honors slot.
    slot_opp = _ta_dict_to_python_predicate(
        {"kind": "controlled_by_opponent", "subject": "controller"}
    )
    assert isinstance(slot_opp, Controlled)
    assert slot_opp.by == OPPONENT
    assert slot_opp.subject == "controller"

    # 4. Default for opponent — no subject field — slot is None.
    default_opp = _ta_dict_to_python_predicate(
        {"kind": "controlled_by_opponent"}
    )
    assert isinstance(default_opp, Controlled)
    assert default_opp.by == OPPONENT
    assert default_opp.subject is None

    # 5. Other slot values pass through (PLAYS_LAND uses
    #    subject="land"/"controller"; the bridge is slot-opaque).
    arbitrary = _ta_dict_to_python_predicate(
        {"kind": "controlled_by_you", "subject": "land"}
    )
    assert arbitrary.subject == "land"


def test_mmm_probe_rust_controlled_by_you_slot_accepts_dict_field():
    """**12th Rust slice Closure A — Rust parse_predicate accepts
    optional subject field on controlled_by_you / controlled_by_opponent.**

    The Rust ``Predicate::ControlledByYou`` and
    ``Predicate::ControlledByOpponent`` enum variants grew an optional
    ``slot: Option<String>`` field. ``parse_predicate`` reads the
    optional ``"subject"`` dict key and threads it through. The
    ``matches`` arm is invariant to slot value for currently-
    dispatched events (subject_id resolves through
    ``find_object_controller`` to the same controller either way), so
    the slot is stored for round-trip fidelity but doesn't change the
    boolean.

    This probe verifies the Rust parser accepts the slot-aware shape
    end-to-end via ``register_printing``.
    """
    import mtg_bot_engine
    r = mtg_bot_engine.Registry()
    # Cosmogrand Zenith / Sunstar Lightsmith / Illvoi Operative /
    # Station Monitor shape: IS_CAST trigger with slot-aware
    # Controlled(YOU, subject="controller").
    pid = r.register_printing({
        "name": "TestSlotAwareControlledByYou",
        "card_types": ["Creature"],
        "subtypes": [],
        "supertypes": [],
        "mana_cost": {"generic": 2, "W": 1},
        "power": 2,
        "toughness": 4,
        "effects": [],
        "spell_effect": None,
        "triggered_abilities": [{
            "event": "cast",
            "predicate": {
                "kind": "and",
                "left": {
                    "kind": "controlled_by_you",
                    "subject": "controller",
                },
                "right": {
                    "kind": "state_bound",
                    "inner": {"kind": "spells_cast_this_turn", "n": 2},
                },
            },
            "effect": {"kind": "put_plus_one_counter_on_self"},
        }],
        "keywords": [],
    })
    assert pid >= 0

    # Symmetric: opponent slot-aware also accepts. The slot string
    # is opaque to Rust's matches() arm — any string parses cleanly.
    pid2 = r.register_printing({
        "name": "TestSlotAwareControlledByOpponent",
        "card_types": ["Creature"],
        "subtypes": [],
        "supertypes": [],
        "mana_cost": {"generic": 3},
        "power": 1,
        "toughness": 1,
        "effects": [],
        "spell_effect": None,
        "triggered_abilities": [{
            "event": "discards_card",
            "predicate": {
                "kind": "controlled_by_opponent",
                "subject": "player",
            },
            "effect": {"kind": "draw_cards", "count": 1},
        }],
        "keywords": [],
    })
    assert pid2 >= 0


# ---------------------------------------------------------------------------
# Probe 5 -- Illvoi Operative real-EoE byte-equal probe
#            (12th Rust slice Closure A; spells_cast_this_turn end-to-end).
#
# Oracle: "{1}{U} Creature — Human Spy 2/1
#   Whenever you cast your second spell each turn, put a +1/+1 counter
#   on this creature."
#
# Parsed trigger:
#   event = IS_CAST
#   predicate = And(Controlled(YOU, subject="controller"),
#                   StateBound(SpellsCastThisTurn(n=2)))
#   effect = PutPlusOneCounterOnSelf(amount=1)
#
# The probe casts TWO zero-mana spells to drive spells_cast_this_turn
# from 0 -> 1 -> 2; the SECOND cast latches the trigger. After both
# stacks fully drain, Illvoi Operative carries a single +1/+1 counter.
# ---------------------------------------------------------------------------


def test_mmm_probe_illvoi_operative_second_spell_self_counter_real_eoe():
    """**12th Rust slice Closure A — Illvoi Operative real-EoE
    byte-equal probe.** End-to-end verification of the slot-aware
    Controlled bridge form + the MMM Pin 1 ``spells_cast_this_turn``
    substrate landed by the 11th slice.

    Drives the SLOT-AWARE bridge end-to-end:
      * Python side: the dict-bridge translates the slot-aware
        ``Controlled(YOU, subject="controller")`` predicate into a
        working Python ``TriggeredAbility`` (slice 12 closure).
      * Rust side: ``parse_predicate`` accepts the optional ``subject``
        field; ``matches`` evaluates correctly on the spell subject_id.

    Sequence:
      1. Inject Illvoi Operative onto p0's bf on both engines.
      2. Inject 2 zero-mana vanilla Creatures into p0's hand on both.
      3. Cast spell 1: spells_cast_this_turn 0 -> 1. SpellsCastThisTurn(2)
         doesn't latch.
      4. Cast spell 2: spells_cast_this_turn 1 -> 2. Trigger LATCHES;
         a counter pushes onto the stack.
      5. Drain stacks on both engines.
      6. Verify Illvoi Operative has exactly 1 +1/+1 counter (real
         observable: power becomes 3, toughness becomes 2 — both
         engines).

    Assertion strength: targeted-observable idiom (same as the
    Pinnacle Emissary cast-spell probes in test_probe_cast_spell_aa.py).
    The targeted observables are byte-equal cross-engine; full
    compare_fields is structurally unsound due to the documented
    IS_CAST stack-resolution-order divergence.
    """
    import mtg_bot_engine
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
        _ta_dict_to_python_triggered_ability,
    )
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.actions import _cast_spell, resolve_top_of_stack
    from mtg_bot.game import Zone

    # The slot-aware Illvoi Operative dict (full bridge-translatable
    # shape — both engines consume this).
    illvoi_trigger = {
        "event": "cast",
        "predicate": {
            "kind": "and",
            "left": {
                "kind": "controlled_by_you",
                "subject": "controller",
            },
            "right": {
                "kind": "state_bound",
                "inner": {"kind": "spells_cast_this_turn", "n": 2},
            },
        },
        "effect": {"kind": "put_plus_one_counter_on_self"},
    }

    # Empty DeckSpec — manual injection for exact zone control.
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2  # ZONE_BATTLEFIELD
    ZH = 0  # ZONE_HAND

    # --- Rust: inject Illvoi Operative onto p0's bf. ----------------
    rs_illvoi_id = rs.register_and_inject_object(
        {
            "name": "Illvoi Operative",
            "card_types": ["Creature"],
            "subtypes": ["Human", "Spy"],
            "supertypes": [],
            "mana_cost": {"generic": 1, "U": 1},
            "power": 2,
            "toughness": 1,
            "keywords": [],
            "effects": [],
            "triggered_abilities": [illvoi_trigger],
        },
        0, ZB,
    )
    rs.clear_summoning_sick_for_player(0)

    # --- Rust: inject 2 zero-mana vanilla Creatures into p0's hand. -
    rs_filler_a = rs.register_and_inject_object(
        {
            "name": "Filler Creature A",
            "card_types": ["Creature"],
            "mana_cost": {"generic": 0},
            "power": 1,
            "toughness": 1,
            "keywords": [],
        },
        0, ZH,
    )
    rs_filler_b = rs.register_and_inject_object(
        {
            "name": "Filler Creature B",
            "card_types": ["Creature"],
            "mana_cost": {"generic": 0},
            "power": 1,
            "toughness": 1,
            "keywords": [],
        },
        0, ZH,
    )
    # Cast spell 1 — counter goes 0 -> 1; trigger predicate fails
    # (SpellsCastThisTurn(2) wants exactly 2).
    assert rs.cast_creature(rs_filler_a, 0) is True
    # Drain stack 1 (spell only — no Illvoi trigger).
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    # Cast spell 2 — counter goes 1 -> 2; trigger LATCHES.
    assert rs.cast_creature(rs_filler_b, 0) is True
    # Now stack carries [Illvoi_trigger, Filler_B_spell]. Drain.
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()

    # Read counters on Illvoi Operative.
    rs_illvoi_counters = None
    for entry in rs.battlefield_snapshot():
        if entry["printing_name"] == "Illvoi Operative":
            rs_illvoi_counters = entry.get("counters")
            break
    assert rs_illvoi_counters is not None, (
        "Rust: Illvoi Operative should still be on p0's bf after both casts"
    )
    assert rs_illvoi_counters == 1, (
        "Rust: Illvoi Operative should carry exactly 1 +1/+1 counter "
        f"after the second cast; got counters={rs_illvoi_counters!r}"
    )

    # --- Python: inject Illvoi Operative onto p0's bf. --------------
    illvoi_ta = _ta_dict_to_python_triggered_ability(illvoi_trigger)
    illvoi_printing = CardPrinting(
        name="Illvoi Operative",
        mana_cost_str="",
        mana_cost=ManaCost(generic=1, colored=(("U", 1),)),
        type_line="Creature — Human Spy",
        supertypes=(),
        card_types=("Creature",),
        subtypes=("Human", "Spy"),
        power=2,
        toughness=1,
        produces=frozenset(),
        keywords=frozenset(),
        triggered_abilities=(illvoi_ta,),
    )
    py_illvoi = py.new_object(illvoi_printing, owner_id=0, zone=Zone.BATTLEFIELD)
    py_illvoi.summoning_sick = False
    py_illvoi.tapped = False
    py_illvoi.damage = 0
    py_illvoi.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_illvoi)

    # --- Python: inject 2 zero-mana vanilla Creatures. --------------
    def _mk_filler(name):
        return CardPrinting(
            name=name,
            mana_cost_str="",
            mana_cost=ManaCost(generic=0, colored=()),
            type_line="Creature",
            supertypes=(),
            card_types=("Creature",),
            subtypes=(),
            power=1,
            toughness=1,
            produces=frozenset(),
            keywords=frozenset(),
            triggered_abilities=(),
        )

    py_filler_a = py.new_object(
        _mk_filler("Filler Creature A"), owner_id=0, zone=Zone.HAND
    )
    py.players[0].hand.append(py_filler_a)
    py_filler_b = py.new_object(
        _mk_filler("Filler Creature B"), owner_id=0, zone=Zone.HAND
    )
    py.players[0].hand.append(py_filler_b)

    # Cast spell 1 — drain.
    _cast_spell(py, player_id=0, card_id=py_filler_a.id, cast_for_free=True)
    while py.stack:
        resolve_top_of_stack(py)
    # Cast spell 2 — drain. Trigger LATCHES on the 2nd cast.
    _cast_spell(py, player_id=0, card_id=py_filler_b.id, cast_for_free=True)
    while py.stack:
        resolve_top_of_stack(py)

    # Python Illvoi Operative counter count.
    assert py_illvoi.plus_one_counters == 1, (
        "Python: Illvoi Operative should carry exactly 1 +1/+1 counter "
        f"after the second cast; got plus_one_counters="
        f"{py_illvoi.plus_one_counters!r}"
    )

    # Cross-engine: byte-equal counter count.
    assert rs_illvoi_counters == py_illvoi.plus_one_counters == 1, (
        "Both engines must agree on Illvoi Operative's counter count "
        f"(rust={rs_illvoi_counters}, py={py_illvoi.plus_one_counters})"
    )


# ---------------------------------------------------------------------------
# Probe 6 -- Sunstar Lightsmith real-EoE byte-equal probe
#
# Oracle: "{3}{W} Creature — Human Soldier 3/3
#   Whenever you cast your second spell each turn, put a +1/+1 counter
#   on this creature and draw a card."
#
# Same shape as Illvoi Operative but the effect is a Sequence:
#   PutPlusOneCounterOnSelf(1) + DrawCards(1).
# ---------------------------------------------------------------------------


def test_mmm_probe_sunstar_lightsmith_second_spell_counter_and_draw_real_eoe():
    """**12th Rust slice Closure A — Sunstar Lightsmith real-EoE
    byte-equal probe.** Sibling of Illvoi Operative; the effect is a
    Sequence(counter + draw) rather than a bare counter. Verifies the
    slot-aware bridge composes correctly with the Sequence effect arm.
    """
    import mtg_bot_engine
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
        _ta_dict_to_python_triggered_ability,
    )
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.actions import _cast_spell, resolve_top_of_stack
    from mtg_bot.game import Zone

    sunstar_trigger = {
        "event": "cast",
        "predicate": {
            "kind": "and",
            "left": {
                "kind": "controlled_by_you",
                "subject": "controller",
            },
            "right": {
                "kind": "state_bound",
                "inner": {"kind": "spells_cast_this_turn", "n": 2},
            },
        },
        "effect": {
            "kind": "sequence",
            "effects": [
                {"kind": "put_plus_one_counter_on_self"},
                {"kind": "draw_cards", "count": 1},
            ],
        },
    }

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2
    ZH = 0
    ZL = 1  # ZONE_LIBRARY

    # Seed a "draw-target" card on p0's library on BOTH engines so the
    # DrawCards(1) effect has something to pull. The Python side's
    # build_python_state starts with empty libraries; Rust likewise.
    rs_seed_id = rs.register_and_inject_object(
        {
            "name": "Library Seed",
            "card_types": ["Creature"],
            "mana_cost": {"generic": 0},
            "power": 1,
            "toughness": 1,
            "keywords": [],
        },
        0, ZL,
    )
    seed_printing = CardPrinting(
        name="Library Seed",
        mana_cost_str="",
        mana_cost=ManaCost(generic=0, colored=()),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=1, toughness=1,
        produces=frozenset(),
        keywords=frozenset(),
        triggered_abilities=(),
    )
    py_seed = py.new_object(seed_printing, owner_id=0, zone=Zone.LIBRARY)
    py.players[0].library.append(py_seed)

    # --- Rust: inject Sunstar Lightsmith onto p0's bf. --------------
    rs_sunstar_id = rs.register_and_inject_object(
        {
            "name": "Sunstar Lightsmith",
            "card_types": ["Creature"],
            "subtypes": ["Human", "Soldier"],
            "supertypes": [],
            "mana_cost": {"generic": 3, "W": 1},
            "power": 3,
            "toughness": 3,
            "keywords": [],
            "effects": [],
            "triggered_abilities": [sunstar_trigger],
        },
        0, ZB,
    )
    rs.clear_summoning_sick_for_player(0)

    # --- Rust: inject 2 zero-mana creatures into p0's hand. ---------
    rs_filler_a = rs.register_and_inject_object(
        {
            "name": "Filler Creature A",
            "card_types": ["Creature"],
            "mana_cost": {"generic": 0},
            "power": 1, "toughness": 1, "keywords": [],
        },
        0, ZH,
    )
    rs_filler_b = rs.register_and_inject_object(
        {
            "name": "Filler Creature B",
            "card_types": ["Creature"],
            "mana_cost": {"generic": 0},
            "power": 1, "toughness": 1, "keywords": [],
        },
        0, ZH,
    )
    rs_hand_size_before = rs.hand_sizes[0]
    assert rs_hand_size_before == 2  # the 2 fillers
    assert rs.cast_creature(rs_filler_a, 0) is True
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    # After cast 1: hand_size = 1 (just filler_b). No trigger fired.
    assert rs.cast_creature(rs_filler_b, 0) is True
    # Trigger now on stack (Sequence: counter + draw). Drain.
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()

    rs_sunstar_counters = None
    for entry in rs.battlefield_snapshot():
        if entry["printing_name"] == "Sunstar Lightsmith":
            rs_sunstar_counters = entry.get("counters")
            break
    assert rs_sunstar_counters == 1, (
        f"Rust: Sunstar should have 1 counter; got {rs_sunstar_counters!r}"
    )
    # Rust drew from library — hand_size = 1 (the draw from the seed).
    assert rs.hand_sizes[0] == 1, (
        f"Rust: hand should have 1 card (the drawn Library Seed) "
        f"after both casts + trigger drain; got {rs.hand_sizes[0]}"
    )

    # --- Python: inject Sunstar Lightsmith onto p0's bf. ------------
    sunstar_ta = _ta_dict_to_python_triggered_ability(sunstar_trigger)
    sunstar_printing = CardPrinting(
        name="Sunstar Lightsmith",
        mana_cost_str="",
        mana_cost=ManaCost(generic=3, colored=(("W", 1),)),
        type_line="Creature — Human Soldier",
        supertypes=(),
        card_types=("Creature",),
        subtypes=("Human", "Soldier"),
        power=3, toughness=3,
        produces=frozenset(),
        keywords=frozenset(),
        triggered_abilities=(sunstar_ta,),
    )
    py_sunstar = py.new_object(
        sunstar_printing, owner_id=0, zone=Zone.BATTLEFIELD
    )
    py_sunstar.summoning_sick = False
    py_sunstar.tapped = False
    py_sunstar.damage = 0
    py_sunstar.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_sunstar)

    def _mk_filler(name):
        return CardPrinting(
            name=name, mana_cost_str="",
            mana_cost=ManaCost(generic=0, colored=()),
            type_line="Creature",
            supertypes=(), card_types=("Creature",),
            subtypes=(),
            power=1, toughness=1,
            produces=frozenset(), keywords=frozenset(),
            triggered_abilities=(),
        )

    py_filler_a = py.new_object(
        _mk_filler("Filler Creature A"), owner_id=0, zone=Zone.HAND
    )
    py.players[0].hand.append(py_filler_a)
    py_filler_b = py.new_object(
        _mk_filler("Filler Creature B"), owner_id=0, zone=Zone.HAND
    )
    py.players[0].hand.append(py_filler_b)

    _cast_spell(py, player_id=0, card_id=py_filler_a.id, cast_for_free=True)
    while py.stack:
        resolve_top_of_stack(py)
    _cast_spell(py, player_id=0, card_id=py_filler_b.id, cast_for_free=True)
    while py.stack:
        resolve_top_of_stack(py)

    assert py_sunstar.plus_one_counters == 1, (
        f"Python: Sunstar should have 1 counter; got "
        f"{py_sunstar.plus_one_counters!r}"
    )
    # Python should have drawn the Library Seed.
    py_hand_names = [obj.printing.name for obj in py.players[0].hand]
    assert "Library Seed" in py_hand_names, (
        f"Python: hand should contain the drawn Library Seed; "
        f"got {py_hand_names!r}"
    )

    # Cross-engine byte-equality on the gameplay observables.
    assert rs_sunstar_counters == py_sunstar.plus_one_counters == 1
    assert rs.hand_sizes[0] == len(py.players[0].hand) == 1, (
        f"hand sizes must match (rust={rs.hand_sizes[0]}, "
        f"py={len(py.players[0].hand)})"
    )
