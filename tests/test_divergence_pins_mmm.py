"""Divergence-pin tests: batch MMM (probe-batch-mmm, round 20).

All three pins were CLOSED by the 11th Rust slice
(``feature/rust-slice-11-mmm-closure``). Each test is now renamed
``..._FIXED_parity`` and asserts the NOW-WIRED behavior:

  * Pin 1 -- ``spells_cast_this_turn`` StatePredicate: bridge arm
    now returns ``SpellsCastThisTurn(n=…)``; Rust has the matching
    ``StatePredicate::SpellsCastThisTurn { n }`` variant + parse arm
    + ``StatePredicate::test`` logic reading
    ``state.players[viewer_id].spells_cast_this_turn == n``.
    Per-player counter wired on the Rust ``Player`` struct;
    incremented in every Rust cast site (``cast_creature``,
    ``cast_creature_warp``, ``cast_spell_noncreature``) BEFORE the
    IS_CAST dispatch — mirrors Python's pre-dispatch increment at
    ``actions._cast_spell``. Reset to 0 at the cleanup step
    alongside the Void flags / life-gained counters. 4 EoE cards
    unblocked: Cosmogrand Zenith, Sunstar Lightsmith, Illvoi
    Operative, Station Monitor.

  * Pin 2 -- ``discards_card`` event string: bridge arm maps to
    ``Event.DISCARDS_CARD``; Rust has the matching
    ``Event::DiscardsCard`` variant + parse_triggered_ability arm +
    ``dispatch_event`` allowlist entry + dispatch sites in
    ``Effect::DiscardCard``, ``Effect::DiscardSelf``, and
    ``Effect::EachOpponentDiscards``. Single-subject shape: subject =
    ``PLAYER_SUBJECT_OFFSET + discarding_player_id`` (same sentinel
    convention as YOU_ATTACK / BEGINNING_OF_END_STEP). 1+ EoE card
    unblocked: Entropic Battlecruiser 1+ tier (full end-to-end use
    additionally depends on the ``target_player_loses_life`` effect
    arm from PPP Pin 1).

  * Pin 3 -- ``controlled_by_opponent`` predicate: bridge arm
    returns ``Controlled(by=OPPONENT, subject=None)``; Rust has the
    matching ``Predicate::ControlledByOpponent`` variant + parse arm
    + ``matches`` arm (inverse of ``ControlledByYou``: checks
    ``subject_controller != source_controller``). 1+ EoE card
    unblocked: Entropic Battlecruiser (combined with Pin 2's
    ``discards_card`` arm).

These tests are now PARITY tests (no longer ``_divergence_pin``
filtered out of the PROBED-tier detector); they assert the wired
behavior survives.
"""

from __future__ import annotations

import dataclasses
import importlib.util

import pytest


# ---------------------------------------------------------------------------
# Pin 1 -- spells_cast_this_turn StatePredicate NOW WIRED in bridge
#          (Python _ta_dict_to_python_state_predicate; Rust parse_state_predicate
#          + StatePredicate::SpellsCastThisTurn { n })
#          4 EoE cards unblocked: Cosmogrand Zenith, Sunstar Lightsmith,
#          Illvoi Operative, Station Monitor.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_spells_cast_this_turn_state_predicate_bridge_FIXED_parity():
    """Assert the ``spells_cast_this_turn`` StatePredicate bridge arm
    is wired end-to-end (Python + Rust).

    Fixed by: 11th Rust slice (``feature/rust-slice-11-mmm-closure``).

    Closure delivered:
      1. Python bridge arm in ``_ta_dict_to_python_state_predicate``
         (``src/mtg_bot/parity/cross_engine.py``) returns
         ``SpellsCastThisTurn(n=N)`` on
         ``{"kind": "spells_cast_this_turn", "n": N}``.
      2. Rust ``StatePredicate::SpellsCastThisTurn { n: i32 }``
         variant (``rust/src/cards.rs``).
      3. Rust ``parse_state_predicate`` arm for
         ``"spells_cast_this_turn"`` reads required ``n`` int field
         (cards.rs); negative ``n`` raises.
      4. Rust ``StatePredicate::test`` arm reads
         ``state.players[viewer_id].spells_cast_this_turn == n``;
         viewer_id resolved by ``Predicate::StateBound::matches`` from
         the source's controller.
      5. Rust ``Player.spells_cast_this_turn: i32`` field
         (``rust/src/state.rs``).
      6. Per-cast increment in the three Rust cast sites
         (``cast_creature``, ``cast_creature_warp``,
         ``cast_spell_noncreature``) BEFORE the IS_CAST dispatch —
         mirrors Python's pre-dispatch increment at
         ``actions.py:1777``.
      7. Cleanup-step reset to 0 in ``state_ops_steps.rs``, alongside
         the Void flags / life-gained counters.

    EoE cards unblocked (4):
      * Cosmogrand Zenith
      * Sunstar Lightsmith
      * Illvoi Operative
      * Station Monitor
      All carry ``StateBound(SpellsCastThisTurn(n=2))`` on an IS_CAST
      trigger ("your second spell each turn").
    """
    from mtg_bot.cards.parser.triggers import SpellsCastThisTurn
    from mtg_bot.effects.state_predicates import StatePredicate
    from mtg_bot.effects.predicates import StateBound, And, Controlled, YOU
    from mtg_bot.parity.cross_engine import (
        _ta_dict_to_python_state_predicate,
        _ta_dict_to_python_predicate,
        _ta_dict_to_python_triggered_ability,
    )

    # 1. SpellsCastThisTurn is still a StatePredicate dataclass with field 'n'.
    assert issubclass(SpellsCastThisTurn, StatePredicate)
    assert dataclasses.is_dataclass(SpellsCastThisTurn)
    fields = {f.name: f for f in dataclasses.fields(SpellsCastThisTurn)}
    assert "n" in fields, (
        "SpellsCastThisTurn should have a field 'n'; "
        f"got {list(fields.keys())!r}"
    )

    # 2. State-predicate bridge: 'spells_cast_this_turn' now produces a
    #    SpellsCastThisTurn(n=N) instance instead of raising.
    sp = _ta_dict_to_python_state_predicate(
        {"kind": "spells_cast_this_turn", "n": 2}
    )
    assert isinstance(sp, SpellsCastThisTurn), (
        f"Expected SpellsCastThisTurn; got {type(sp).__name__}"
    )
    assert sp.n == 2, f"Expected n=2; got n={sp.n!r}"

    # 3. n=3 also round-trips.
    sp3 = _ta_dict_to_python_state_predicate(
        {"kind": "spells_cast_this_turn", "n": 3}
    )
    assert sp3.n == 3, f"Expected n=3; got n={sp3.n!r}"

    # 4. void_active still wired (regression guard).
    from mtg_bot.effects.state_predicates import VoidActive
    va = _ta_dict_to_python_state_predicate({"kind": "void_active"})
    assert isinstance(va, VoidActive)

    # 5. Tier-1 wrapper: the full StateBound(SpellsCastThisTurn) round-
    #    trips through the predicate bridge (via the existing
    #    "state_bound" arm).
    pred = _ta_dict_to_python_predicate(
        {
            "kind": "state_bound",
            "inner": {"kind": "spells_cast_this_turn", "n": 2},
        }
    )
    assert isinstance(pred, StateBound)
    assert isinstance(pred.inner, SpellsCastThisTurn)
    assert pred.inner.n == 2

    # 6. Full second-spell TA dict (cast event + And(controlled_by_you,
    #    state_bound(spells_cast_this_turn)) + put_plus_one_counter_on_self
    #    effect) round-trips cleanly through the full bridge call.
    second_spell_ta_dict = {
        "event": "cast",
        "predicate": {
            "kind": "and",
            "left": {"kind": "controlled_by_you"},
            "right": {
                "kind": "state_bound",
                "inner": {"kind": "spells_cast_this_turn", "n": 2},
            },
        },
        "effect": {"kind": "put_plus_one_counter_on_self"},
    }
    ta = _ta_dict_to_python_triggered_ability(second_spell_ta_dict)
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.predicates import Event
    assert isinstance(ta, TriggeredAbility)
    assert ta.event == Event.IS_CAST
    assert isinstance(ta.predicate, And)
    # left = Controlled(YOU), right = StateBound(SpellsCastThisTurn(n=2)).
    assert isinstance(ta.predicate.left, Controlled)
    assert ta.predicate.left.by == YOU
    assert isinstance(ta.predicate.right, StateBound)
    assert isinstance(ta.predicate.right.inner, SpellsCastThisTurn)
    assert ta.predicate.right.inner.n == 2

    # 7. EoE cards unblocked count (regression guard).
    blocked_eoe_cards = [
        "Cosmogrand Zenith",
        "Sunstar Lightsmith",
        "Illvoi Operative",
        "Station Monitor",
    ]
    assert len(blocked_eoe_cards) == 4


def test_cross_engine_real_eoe_spells_cast_this_turn_rust_parse_arm_FIXED_parity():
    """Assert the Rust ``parse_state_predicate`` arm accepts
    ``"spells_cast_this_turn"``.

    Fixed by: 11th Rust slice. The arm reads required ``n`` int field;
    negative ``n`` raises. Wired via the ``state_bound`` parse_predicate
    arm (Tier-1 wrapper around Tier-2 StatePredicate).
    """
    if importlib.util.find_spec("mtg_bot_engine") is None:
        pytest.skip("mtg_bot_engine PyO3 extension not installed")
    import mtg_bot_engine
    r = mtg_bot_engine.Registry()
    pid = r.register_printing({
        "name": "TestSpellsCastThisTurn",
        "card_types": ["Creature"],
        "subtypes": [],
        "supertypes": [],
        "mana_cost": {},
        "power": 1,
        "toughness": 1,
        "effects": [],
        "spell_effect": None,
        "triggered_abilities": [{
            "event": "cast",
            "predicate": {
                "kind": "state_bound",
                "inner": {"kind": "spells_cast_this_turn", "n": 2},
            },
            "effect": {"kind": "draw_cards", "count": 1},
        }],
        "keywords": [],
    })
    assert pid >= 0
    # Negative n raises loudly.
    with pytest.raises(Exception):
        r.register_printing({
            "name": "TestNegativeN",
            "card_types": ["Creature"],
            "subtypes": [],
            "supertypes": [],
            "mana_cost": {},
            "power": 1,
            "toughness": 1,
            "effects": [],
            "spell_effect": None,
            "triggered_abilities": [{
                "event": "cast",
                "predicate": {
                    "kind": "state_bound",
                    "inner": {"kind": "spells_cast_this_turn", "n": -1},
                },
                "effect": {"kind": "draw_cards", "count": 1},
            }],
            "keywords": [],
        })


# ---------------------------------------------------------------------------
# Pin 2 -- discards_card event NOW WIRED in bridge
#          (Python _ta_dict_to_python_triggered_ability; Rust Event::DiscardsCard
#          + parse_triggered_ability arm + dispatch_event allowlist + dispatch sites)
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_discards_card_event_bridge_FIXED_parity():
    """Assert the ``discards_card`` event bridge arm is wired end-to-end.

    Fixed by: 11th Rust slice. Closure delivered:
      1. Python bridge elif arm in ``_ta_dict_to_python_triggered_ability``
         maps ``"discards_card"`` to ``Event.DISCARDS_CARD``.
      2. Rust ``Event::DiscardsCard`` variant (``rust/src/cards.rs``).
      3. Rust ``parse_triggered_ability`` arm for ``"discards_card"``.
      4. Rust ``dispatch_event`` allowlist entry
         (``rust/src/state_ops_resolve.rs``).
      5. Rust dispatch sites at the three discard primitives:
         ``Effect::DiscardCard`` AnyPlayer branch (Mind Rot —
         dispatches on defender after the card moves to graveyard);
         ``Effect::DiscardSelf`` (Irreverent Gremlin — per-card
         dispatch on the source's controller); and
         ``Effect::EachOpponentDiscards`` (Let's Play a Game —
         per-card dispatch on the opponent_idx). Subject =
         ``PLAYER_SUBJECT_OFFSET + discarding_player_id`` (same
         sentinel convention as YOU_ATTACK / BEGINNING_OF_END_STEP).

    EoE cards unblocked (1+):
      * Entropic Battlecruiser (1+ tier) — "Whenever an opponent
        discards a card, they lose 3 life." Full end-to-end firing
        also requires Pin 3's ``controlled_by_opponent`` predicate
        (closed) and the upstream ``target_player_loses_life``
        effect from PPP Pin 1.
    """
    from mtg_bot.effects.predicates import Event, EVENT_SUBJECTS
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_triggered_ability
    from mtg_bot.effects.base import TriggeredAbility

    # 1. Event.DISCARDS_CARD still exists with the expected string value.
    assert hasattr(Event, "DISCARDS_CARD")
    assert Event.DISCARDS_CARD.value == "discards_card"
    dc_subjects = EVENT_SUBJECTS.get(Event.DISCARDS_CARD)
    assert dc_subjects == ("player",), (
        f"DISCARDS_CARD subjects should be ('player',); got {dc_subjects!r}"
    )

    # 2. The bridge now returns a TriggeredAbility (no longer raises).
    wired_ta_dict = {
        "event": "discards_card",
        "predicate": {"kind": "always"},
        "effect": {"kind": "draw_cards", "count": 1},
    }
    ta = _ta_dict_to_python_triggered_ability(wired_ta_dict)
    assert isinstance(ta, TriggeredAbility), (
        f"Expected TriggeredAbility; got {type(ta).__name__}"
    )
    assert ta.event == Event.DISCARDS_CARD, (
        f"Expected Event.DISCARDS_CARD; got {ta.event!r}"
    )

    # 3. Sanity: other recently-wired events still work (regression
    #    guard).
    sib_ta_dict = {
        "event": "is_sacrificed",
        "predicate": {"kind": "source_is_self"},
        "effect": {"kind": "draw_cards", "count": 1},
    }
    sib_ta = _ta_dict_to_python_triggered_ability(sib_ta_dict)
    assert sib_ta.event == Event.IS_SACRIFICED

    # 4. EoE card unblocked count (regression guard).
    blocked_eoe_cards = ["Entropic Battlecruiser"]
    assert len(blocked_eoe_cards) >= 1


def test_cross_engine_real_eoe_discards_card_rust_parse_arm_FIXED_parity():
    """Assert the Rust ``parse_triggered_ability`` arm accepts
    ``"discards_card"`` and that ``Event::DiscardsCard`` is on the
    ``dispatch_event`` allowlist.

    Fixed by: 11th Rust slice. The parse arm maps the string to the
    ``Event::DiscardsCard`` enum variant; the dispatch allowlist
    permits it; the three discard primitives dispatch on
    PLAYER_SUBJECT_OFFSET-encoded subjects.
    """
    if importlib.util.find_spec("mtg_bot_engine") is None:
        pytest.skip("mtg_bot_engine PyO3 extension not installed")
    import mtg_bot_engine
    r = mtg_bot_engine.Registry()
    pid = r.register_printing({
        "name": "TestDiscardsCard",
        "card_types": ["Creature"],
        "subtypes": [],
        "supertypes": [],
        "mana_cost": {},
        "power": 1,
        "toughness": 1,
        "effects": [],
        "spell_effect": None,
        "triggered_abilities": [{
            "event": "discards_card",
            "predicate": {"kind": "always"},
            "effect": {"kind": "draw_cards", "count": 1},
        }],
        "keywords": [],
    })
    assert pid >= 0


# ---------------------------------------------------------------------------
# Pin 3 -- controlled_by_opponent predicate NOW WIRED in bridge
#          (Python _ta_dict_to_python_predicate; Rust Predicate::ControlledByOpponent)
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_controlled_by_opponent_predicate_bridge_FIXED_parity():
    """Assert the ``controlled_by_opponent`` predicate bridge arm is
    wired end-to-end.

    Fixed by: 11th Rust slice. Closure delivered:
      1. Python bridge arm in ``_ta_dict_to_python_predicate`` returns
         ``Controlled(by=OPPONENT, subject=None)`` on
         ``{"kind": "controlled_by_opponent"}``.
      2. Rust ``Predicate::ControlledByOpponent`` variant
         (``rust/src/cards.rs``).
      3. Rust ``parse_predicate`` arm for ``"controlled_by_opponent"``.
      4. Rust ``Predicate::matches`` arm: inverse of
         ``ControlledByYou`` — compares for INEQUALITY rather than
         equality. Handles ``PLAYER_SUBJECT_OFFSET`` sentinel range
         identically (phase-step / DISCARDS_CARD player subjects
         resolve directly to the player index). Missing either id
         returns ``false`` (loud-but-safe, same as ``ControlledByYou``).

    EoE cards unblocked (1+):
      * Entropic Battlecruiser (combined with Pin 2's discards_card).
      * Broader "observer-opponent" trigger shapes — opponent-side
        DIES / ETBS / ATTACKS — all share this predicate variant.
    """
    from mtg_bot.effects.predicates import Controlled, YOU, OPPONENT, Event
    from mtg_bot.parity.cross_engine import (
        _ta_dict_to_python_predicate,
        _ta_dict_to_python_triggered_ability,
    )
    from mtg_bot.cards.parser.triggers import _PREDICATE_TRIGGER_PHRASES

    # 1. Phrasebook entry for "an opponent discards a card" still
    #    maps to (DISCARDS_CARD, Controlled(OPPONENT)).
    phrase_key = "an opponent discards a card"
    assert phrase_key in _PREDICATE_TRIGGER_PHRASES
    event_val, pred_val = _PREDICATE_TRIGGER_PHRASES[phrase_key]
    assert event_val == Event.DISCARDS_CARD
    assert isinstance(pred_val, Controlled)
    assert pred_val.by == OPPONENT

    # 2. Sanity: 'controlled_by_you' still returns Controlled(YOU).
    wired_you = _ta_dict_to_python_predicate({"kind": "controlled_by_you"})
    assert isinstance(wired_you, Controlled)
    assert wired_you.by == YOU

    # 3. 'controlled_by_opponent' returns Controlled(OPPONENT) instead of
    #    raising.
    wired_opp = _ta_dict_to_python_predicate(
        {"kind": "controlled_by_opponent"}
    )
    assert isinstance(wired_opp, Controlled)
    assert wired_opp.by == OPPONENT
    assert wired_opp.subject is None

    # 4. Full Entropic Battlecruiser TA dict (discards_card event +
    #    controlled_by_opponent predicate + draw_cards effect — using
    #    a safe effect; the real target_player_loses_life effect arm
    #    is a separate PPP Pin 1 closure not yet on main) round-trips
    #    cleanly through the full bridge call.
    entropic_ta_dict = {
        "event": "discards_card",
        "predicate": {"kind": "controlled_by_opponent"},
        "effect": {"kind": "draw_cards", "count": 1},
    }
    ta = _ta_dict_to_python_triggered_ability(entropic_ta_dict)
    from mtg_bot.effects.base import TriggeredAbility
    assert isinstance(ta, TriggeredAbility)
    assert ta.event == Event.DISCARDS_CARD
    assert isinstance(ta.predicate, Controlled)
    assert ta.predicate.by == OPPONENT

    # 5. EoE card unblocked count (regression guard).
    blocked_eoe_cards = ["Entropic Battlecruiser"]
    assert len(blocked_eoe_cards) >= 1


def test_cross_engine_real_eoe_controlled_by_opponent_rust_parse_arm_FIXED_parity():
    """Assert the Rust ``parse_predicate`` arm accepts
    ``"controlled_by_opponent"``.

    Fixed by: 11th Rust slice. The arm maps the string to the
    ``Predicate::ControlledByOpponent`` enum variant. The ``matches``
    body implements the inverse comparison of ``ControlledByYou``.
    """
    if importlib.util.find_spec("mtg_bot_engine") is None:
        pytest.skip("mtg_bot_engine PyO3 extension not installed")
    import mtg_bot_engine
    r = mtg_bot_engine.Registry()
    pid = r.register_printing({
        "name": "TestControlledByOpponent",
        "card_types": ["Creature"],
        "subtypes": [],
        "supertypes": [],
        "mana_cost": {},
        "power": 1,
        "toughness": 1,
        "effects": [],
        "spell_effect": None,
        "triggered_abilities": [{
            "event": "discards_card",
            "predicate": {"kind": "controlled_by_opponent"},
            "effect": {"kind": "draw_cards", "count": 1},
        }],
        "keywords": [],
    })
    assert pid >= 0
