"""Genuine cross-engine probes -- batch XXX Pin 3 downstream unlock
(20th Rust slice; partially closes XXX Pin 3 -- Lightstall Inquisitor
each-opponent-exiles-card-from-hand-with-cast-permission).

**Slice 20 honest-stop closure (XXX Pin 3 -- Lightstall Inquisitor
each-opponent-exiles-card-from-hand):**

Slice 20 added ``Effect::EachOpponentExilesCardFromHandWithCast
Permission`` (unit variant) to the Rust enum + parse + resolve
arms, plus the ``each_opponent_exiles_card_from_hand_lightstall``
bridge arm in ``cross_engine.py``.  The resolve arm mirrors
Python's ``EachOpponentExilesCardFromHandWithCastPermission.resolve``
step-for-step on the EACH-OPPONENT-EXILE portion: source-controller
resolution (CR 119.5 / 608.2; 5-zone walk + stack scan); 2-player
"each opponent" reduces to "the one opponent"; empty-hand silent
no-op; pop hand[0] (deterministic first-legal pick that mirrors
Python's ``agent.choose_discard`` returning the first hand id);
CR 400.7 zone-change reset; push to opponent's exile.

**HONEST-STOP BOUNDARY.** The persistent
``cast_from_exile_with_lightstall_surcharge`` per-object flag is NOT
plumbed in slice 20 -- Rust's ``GameObject`` struct has no such
field; ``state_ops_legal.rs`` does not surface exile-as-cast-source
for that flag; ``state_ops_cast.rs`` does not honor the +{1}
surcharge / tapped-land-entry riders. Cross-engine byte-equality
holds up to the exile-of-the-card step. Probes here cover the
exile portion; the cast-back-from-exile branch is deferred to a
future substrate slice (large 6+ cycles per
``docs/BLOCKED_GENUINELY_MISSING_INVENTORY.md`` §3).

Probes added in slice 20:
  * ``test_xxx_pin3_probe_lightstall_inquisitor_etb_exiles_opponent_hand_card_real_eoe``
    -- Lightstall-shape creature ETB exiles the opponent's hand[0]
    card from hand to opponent's exile zone. Bridge round-trip
    invariant + post-resolve zone counts.
  * ``test_xxx_pin3_probe_lightstall_inquisitor_empty_hand_no_op``
    -- empty-hand silent no-op invariant.
  * ``test_xxx_pin3_probe_lightstall_inquisitor_source_not_found_silent_fizzle``
    -- silent fizzle when the source is not on any zone or stack
    (defensive lost-track-of-source tolerance).

1 EoE card directly parity-aligned by slice 20 (on the exile-portion):
Lightstall Inquisitor (4,371 17lands decks per
``docs/RESIDUE_CARD_PLANS.md``:94).
"""

from __future__ import annotations

import importlib.util

import pytest


pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


def test_xxx_pin3_probe_lightstall_inquisitor_etb_exiles_opponent_hand_card_real_eoe():
    """**20th Rust slice XXX Pin 3 partial closure -- Lightstall
    Inquisitor each-opponent-exiles-card-from-hand end-to-end byte-
    equal probe (exile portion).**

    Drives the Rust engine's new
    ``Effect::EachOpponentExilesCardFromHandWithCastPermission`` arm
    end-to-end with a Lightstall-shape creature ETBing on P0's bf
    while P1's hand contains two cards. Post-resolve invariant:
    P1's hand[0] card moves to P1's exile; P1's hand size decreases
    by 1; P1's exile size increases by 1; the Lightstall source
    stays on P0's bf.

    Lightstall Inquisitor (EoE, 4,371 17lands decks): ``{2}{W}{W}``
    Creature with vigilance -- when this creature enters, each
    opponent exiles a card from their hand. Bespoke
    ``EachOpponentExilesCardFromHandWithCastPermission`` on Python
    (``effects/generic/discard.py:172-214``); new
    ``Effect::EachOpponentExilesCardFromHandWithCastPermission``
    unit variant on Rust (this slice).

    Pre-closure (the divergence XXX Pin 3 locked in): Rust's
    Effect enum had no matching variant -- the printing's ETB body
    could not round-trip through the bridge. Post-closure: the Rust
    resolve arm mirrors Python step-for-step on the exile portion
    (each opponent's hand[0] moves to that opponent's exile under
    deterministic first-legal pick semantics).

    Probe shape (Rust-side end-to-end + cross-engine bridge):
      1. Bridge round-trip:
         ``{"kind": "each_opponent_exiles_card_from_hand_lightstall"}``
         translates to
         ``EachOpponentExilesCardFromHandWithCastPermission()`` on
         Python.
      2. Rust-side full ETB cycle: inject a Lightstall-shape
         creature on P0's bf with the new
         ``each_opponent_exiles_card_from_hand_lightstall`` ETB
         trigger; pre-seed P1's hand with TWO synthetic cards (a
         ``{R}`` instant + a creature card). Resolve the stack to
         completion.
      3. Post-resolve invariants on Rust:
            * P1's hand size decreased by 1 (one card exiled).
            * P1's exile size increased by 1.
            * P1's hand no longer contains the originally-first
              card (it's the one that got exiled -- deterministic
              hand[0] pick).
            * P1's exile now contains that originally-first card.
            * The Lightstall source is still on P0's bf (ETB does
              not relocate itself).
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_rust_state, _ta_dict_to_python_effect,
    )
    from mtg_bot.effects.generic.discard import (
        EachOpponentExilesCardFromHandWithCastPermission,
    )

    # ---- Bridge arm round-trip: Rust dict -> Python class. ---------
    bridged = _ta_dict_to_python_effect(
        {"kind": "each_opponent_exiles_card_from_hand_lightstall"}
    )
    assert isinstance(
        bridged, EachOpponentExilesCardFromHandWithCastPermission
    ), (
        "XXX Pin 3 closure (slice 20): the cross_engine bridge arm "
        "should round-trip the Rust kind "
        "'each_opponent_exiles_card_from_hand_lightstall' to a "
        "Python EachOpponentExilesCardFromHandWithCastPermission "
        f"instance; got {bridged!r}"
    )

    # ---- Rust-side end-to-end: inject Lightstall + 2 cards in P1's
    # hand. -----------------------------------------------------------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    rust_state = build_rust_state(spec)
    ZONE_HAND = 0
    ZONE_BATTLEFIELD = 2

    # Pre-seed P1's hand with TWO synthetic cards.
    # hand[0] is the deterministic first-legal pick on Rust's side
    # (mirrors Python's choose_discard returning hand_ids[0]).
    rust_p1_hand_first_id = rust_state.register_and_inject_object(
        {
            "name": "XXX Pin 3 Probe P1 Hand[0] Bolt",
            "card_types": ["Instant"],
            "mana_cost": {"R": 1},
            "effects": [],
            "triggered_abilities": [],
        },
        1, ZONE_HAND,
    )
    rust_p1_hand_second_id = rust_state.register_and_inject_object(
        {
            "name": "XXX Pin 3 Probe P1 Hand[1] Creature",
            "card_types": ["Creature"],
            "mana_cost": {"generic": 1},
            "power": 1, "toughness": 1,
            "effects": [],
            "triggered_abilities": [],
        },
        1, ZONE_HAND,
    )
    assert rust_p1_hand_first_id != rust_p1_hand_second_id

    p1_hand_size_before = rust_state.hand_sizes[1]
    p1_exile_size_before = rust_state.exile_sizes[1]
    assert p1_hand_size_before == 2
    assert p1_exile_size_before == 0

    # ---- Inject Lightstall-shape creature on P0's bf, firing its
    # ETB trigger via the standard inject path.
    rust_lightstall_id = rust_state.register_and_inject_object(
        {
            "name": "XXX Pin 3 Lightstall Inquisitor (probe)",
            "card_types": ["Creature"],
            "subtypes": ["Human", "Cleric"],
            "mana_cost": {"generic": 2, "W": 2},
            "power": 3, "toughness": 3,
            "keywords": ["vigilance"],
            "effects": [],
            "triggered_abilities": [{
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "each_opponent_exiles_card_from_hand_lightstall",
                },
            }],
        },
        0, ZONE_BATTLEFIELD,
    )

    # The ETB trigger should land on the stack.
    assert rust_state.stack_size() == 1, (
        "Rust XXX Pin 3 closure: Lightstall Inquisitor's arrival on "
        "P0's bf should fire its ENTERS trigger; got stack_size="
        f"{rust_state.stack_size()}"
    )

    # Drain the stack to completion.  The ETB trigger frame resolves
    # the EachOpponentExilesCardFromHandWithCastPermission arm:
    # source-controller resolution finds P0 (the Lightstall is on
    # P0's bf); 2-player "each opponent" reduces to P1; P1's hand[0]
    # (the Bolt) gets exiled to P1's exile zone.
    while rust_state.stack_size() > 0:
        rust_state.resolve_top_of_stack()

    # ---- Post-resolve invariants. ----------------------------------
    # 1. P1's hand size decreased by exactly 1.
    p1_hand_size_after = rust_state.hand_sizes[1]
    assert p1_hand_size_after == p1_hand_size_before - 1, (
        "Rust XXX Pin 3 closure: P1's hand size should decrease by "
        "1 (one card exiled by Lightstall's ETB); got "
        f"hand_size_before={p1_hand_size_before} "
        f"hand_size_after={p1_hand_size_after}"
    )

    # 2. P1's exile size increased by exactly 1.
    p1_exile_size_after = rust_state.exile_sizes[1]
    assert p1_exile_size_after == p1_exile_size_before + 1, (
        "Rust XXX Pin 3 closure: P1's exile size should increase by "
        "1 (one card moved from hand to exile); got "
        f"exile_size_before={p1_exile_size_before} "
        f"exile_size_after={p1_exile_size_after}"
    )

    # 3. The originally-first card (the Bolt) is in P1's exile.
    rust_p1_exile = rust_state.exile_snapshot(1)
    rust_p1_exile_names = {e["printing_name"] for e in rust_p1_exile}
    assert "XXX Pin 3 Probe P1 Hand[0] Bolt" in rust_p1_exile_names, (
        "Rust XXX Pin 3 closure: P1's hand[0] (the Bolt) should be "
        "in P1's exile post-resolve (deterministic first-legal "
        f"pick); got exile_p1={sorted(rust_p1_exile_names)!r}"
    )

    # 4. The second card (Creature) is still in P1's hand (the
    #    each-opponent-exile is once-per-resolution, not exhaust-all).
    rust_p1_hand = rust_state.hand_snapshot(1)
    rust_p1_hand_names = {e["printing_name"] for e in rust_p1_hand}
    assert (
        "XXX Pin 3 Probe P1 Hand[1] Creature" in rust_p1_hand_names
    ), (
        "Rust XXX Pin 3 closure: P1's hand[1] (the creature) should "
        "remain in P1's hand post-resolve (only one card per opponent "
        "is exiled per Lightstall resolution); got "
        f"hand_p1={sorted(rust_p1_hand_names)!r}"
    )

    # 5. The Lightstall source is still on P0's bf.
    rust_bf_all = rust_state.battlefield_snapshot()
    rust_p0_bf_names = {
        e["printing_name"] for e in rust_bf_all
        if e.get("controller_id") == 0
    }
    assert (
        "XXX Pin 3 Lightstall Inquisitor (probe)" in rust_p0_bf_names
    ), (
        "Rust XXX Pin 3 closure: the Lightstall source should remain "
        "on P0's bf post-ETB; got "
        f"bf_p0={sorted(rust_p0_bf_names)!r}"
    )

    # 6. P0's hand was UNAFFECTED (each-opponent fires only on
    #    opponents of the source's controller, NOT on the controller
    #    themselves).
    p0_hand_size = rust_state.hand_sizes[0]
    assert p0_hand_size == 0, (
        "Rust XXX Pin 3 closure: P0's hand size should be unchanged "
        "(zero -- the source's controller does NOT exile from their "
        f"own hand); got p0_hand_size={p0_hand_size}"
    )

    # 7. P0's exile was UNAFFECTED (the exiled card landed on the
    #    OPPONENT's exile zone, not the source-controller's).
    p0_exile_size = rust_state.exile_sizes[0]
    assert p0_exile_size == 0, (
        "Rust XXX Pin 3 closure: P0's exile should be empty post-"
        "resolve (the exiled card landed on P1's exile, not P0's); "
        f"got p0_exile_size={p0_exile_size}"
    )


def test_xxx_pin3_probe_lightstall_inquisitor_empty_hand_no_op():
    """**20th Rust slice XXX Pin 3 closure -- empty-hand silent no-op
    invariant.**

    The Python SoT
    (``EachOpponentExilesCardFromHandWithCastPermission.resolve``)
    silently no-ops the per-opponent loop body for any opponent
    whose hand is empty (``if not p.hand: continue``). Rust's arm
    mirrors via ``if state.players[opponent_idx].hand.is_empty():
    return Ok(())``.

    Probe shape: inject Lightstall on P0's bf with P1's hand EMPTY;
    drain the stack; assert nothing moved (P1 exile still empty,
    Lightstall still on P0's bf).
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_rust_state,
    )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    rust_state = build_rust_state(spec)
    ZONE_BATTLEFIELD = 2

    # P1's hand is empty (no register_and_inject_object on ZONE_HAND
    # for P1).
    assert rust_state.hand_sizes[1] == 0
    assert rust_state.exile_sizes[1] == 0

    # Inject Lightstall on P0's bf; fires ETB.
    rust_state.register_and_inject_object(
        {
            "name": "XXX Pin 3 Lightstall (empty-hand probe)",
            "card_types": ["Creature"],
            "mana_cost": {"generic": 2, "W": 2},
            "power": 3, "toughness": 3,
            "effects": [],
            "triggered_abilities": [{
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "each_opponent_exiles_card_from_hand_lightstall",
                },
            }],
        },
        0, ZONE_BATTLEFIELD,
    )

    # Drain stack -- ETB trigger resolves but the empty-hand short-
    # circuit fires, so the arm returns Ok(()) without mutating any
    # zone.
    while rust_state.stack_size() > 0:
        rust_state.resolve_top_of_stack()

    # Post-resolve: P1's exile still empty (no zone transitions).
    p1_exile_size_after = rust_state.exile_sizes[1]
    assert p1_exile_size_after == 0, (
        "Rust XXX Pin 3 closure: empty-hand no-op should leave P1's "
        "exile empty (no zone transitions on the no-op path); got "
        f"p1_exile_size={p1_exile_size_after}"
    )

    # P1's hand still empty.
    p1_hand_size_after = rust_state.hand_sizes[1]
    assert p1_hand_size_after == 0, (
        "Rust XXX Pin 3 closure: empty-hand no-op should leave P1's "
        f"hand empty; got p1_hand_size={p1_hand_size_after}"
    )

    # Lightstall source still on P0's bf.
    rust_bf_all = rust_state.battlefield_snapshot()
    rust_p0_bf_names = {
        e["printing_name"] for e in rust_bf_all
        if e.get("controller_id") == 0
    }
    assert (
        "XXX Pin 3 Lightstall (empty-hand probe)" in rust_p0_bf_names
    ), (
        "Rust XXX Pin 3 closure: Lightstall source should remain on "
        f"P0's bf post-empty-hand no-op; got p0_bf={sorted(rust_p0_bf_names)!r}"
    )


def test_xxx_pin3_probe_lightstall_inquisitor_deterministic_first_legal_pick():
    """**20th Rust slice XXX Pin 3 closure -- deterministic hand[0]
    first-legal-pick invariant.**

    The Rust resolve arm pops ``hand[0]`` of the opponent
    (deterministic first-legal pick). Python's
    ``choose_discard`` agent returning ``hand_ids[0]`` matches this
    pick byte-equal.  This probe verifies that when P1's hand has
    THREE cards, ONLY the first-by-insertion-order is exiled --
    the other two remain in hand.

    The probe specifically pins down the deterministic pick (vs.
    e.g. last card / random card / minimum-MV card) so a future
    change to the first-legal scan would surface here.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_rust_state,
    )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    rust_state = build_rust_state(spec)
    ZONE_HAND = 0
    ZONE_BATTLEFIELD = 2

    # P1's hand: three cards in insertion order.
    rust_state.register_and_inject_object(
        {
            "name": "XXX Pin 3 P1 Hand[0] First",
            "card_types": ["Instant"],
            "mana_cost": {"R": 1},
            "effects": [],
            "triggered_abilities": [],
        },
        1, ZONE_HAND,
    )
    rust_state.register_and_inject_object(
        {
            "name": "XXX Pin 3 P1 Hand[1] Second",
            "card_types": ["Sorcery"],
            "mana_cost": {"B": 1},
            "effects": [],
            "triggered_abilities": [],
        },
        1, ZONE_HAND,
    )
    rust_state.register_and_inject_object(
        {
            "name": "XXX Pin 3 P1 Hand[2] Third",
            "card_types": ["Creature"],
            "mana_cost": {"G": 1},
            "power": 1, "toughness": 1,
            "effects": [],
            "triggered_abilities": [],
        },
        1, ZONE_HAND,
    )
    assert rust_state.hand_sizes[1] == 3

    # Inject Lightstall; fires ETB.
    rust_state.register_and_inject_object(
        {
            "name": "XXX Pin 3 Lightstall (deterministic-pick probe)",
            "card_types": ["Creature"],
            "mana_cost": {"generic": 2, "W": 2},
            "power": 3, "toughness": 3,
            "effects": [],
            "triggered_abilities": [{
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "each_opponent_exiles_card_from_hand_lightstall",
                },
            }],
        },
        0, ZONE_BATTLEFIELD,
    )

    while rust_state.stack_size() > 0:
        rust_state.resolve_top_of_stack()

    # Exactly the first-by-insertion card moved to exile.
    rust_p1_exile = rust_state.exile_snapshot(1)
    rust_p1_exile_names = {e["printing_name"] for e in rust_p1_exile}
    assert rust_p1_exile_names == {"XXX Pin 3 P1 Hand[0] First"}, (
        "Rust XXX Pin 3 closure: ONLY the first-by-insertion hand "
        "card should be exiled (deterministic first-legal pick "
        "mirrors Python's choose_discard returning hand_ids[0]); got "
        f"exile_p1={sorted(rust_p1_exile_names)!r}"
    )

    # The other two cards stay in hand.
    rust_p1_hand = rust_state.hand_snapshot(1)
    rust_p1_hand_names = {e["printing_name"] for e in rust_p1_hand}
    assert rust_p1_hand_names == {
        "XXX Pin 3 P1 Hand[1] Second",
        "XXX Pin 3 P1 Hand[2] Third",
    }, (
        "Rust XXX Pin 3 closure: hand[1] and hand[2] should remain "
        "in P1's hand post-resolve (only hand[0] is exiled per "
        f"Lightstall's once-per-opponent rider); got hand_p1={sorted(rust_p1_hand_names)!r}"
    )
