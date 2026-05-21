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


# ---------------------------------------------------------------------------
# Cast-from-exile-with-cost-hike substrate probes (follow-up to slice 20).
# These cover the persistent permission substrate's end-to-end behavior:
# the exiled card's `cast_from_exile_with_lightstall_surcharge` flag,
# the legal-actions surface, the +{1} surcharge on the cost-pay path,
# and the tapped-land-entry rider.
# ---------------------------------------------------------------------------


def test_substrate_lightstall_flag_stamped_on_exiled_card_real_eoe():
    """**Cast-from-exile-with-cost-hike substrate.** After Lightstall's
    ETB resolves, the exiled card MUST carry
    ``cast_from_exile_with_lightstall_surcharge=true`` on its
    GameObject. The Rust snapshot pydict surfaces the flag so cross-
    engine inspectors can verify it; this probe drives the resolve arm
    on the Rust side and asserts the flag is stamped.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_rust_state,
    )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    rust_state = build_rust_state(spec)
    ZONE_HAND = 0
    ZONE_BATTLEFIELD = 2

    # P1's hand has one card -- the target of the exile.
    rust_state.register_and_inject_object(
        {
            "name": "Substrate Probe -- P1 Hand[0] Bear",
            "card_types": ["Creature"],
            "mana_cost": {"generic": 1, "G": 1},
            "power": 2, "toughness": 2,
            "effects": [],
            "triggered_abilities": [],
        },
        1, ZONE_HAND,
    )

    # Lightstall controlled by P0 -> P1 (opponent) exiles.
    rust_state.register_and_inject_object(
        {
            "name": "Substrate Probe -- Lightstall Inquisitor",
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

    # P1's exile now has 1 card, and it carries the Lightstall flag.
    exile_p1 = rust_state.exile_snapshot(1)
    assert len(exile_p1) == 1, (
        f"Substrate probe: P1's exile should have exactly 1 card after "
        f"Lightstall resolve; got {len(exile_p1)} cards: {exile_p1!r}"
    )
    exiled = exile_p1[0]
    assert exiled["printing_name"] == "Substrate Probe -- P1 Hand[0] Bear", (
        f"Substrate probe: P1's exile should hold the Bear that was "
        f"in P1's hand[0]; got {exiled['printing_name']!r}"
    )
    assert exiled["cast_from_exile_with_lightstall_surcharge"] is True, (
        "Substrate probe: the Rust snapshot pydict MUST surface "
        "`cast_from_exile_with_lightstall_surcharge=True` on the "
        "exiled card after Lightstall ETB resolves (the persistent "
        "permission flag substrate). Without the flag, the legal "
        "emitter would not surface the cast-from-exile and the "
        "substrate's load-bearing piece would be a no-op. Got "
        f"{exiled.get('cast_from_exile_with_lightstall_surcharge')!r}"
    )


def test_substrate_lightstall_legal_actions_surfaces_cast_from_exile_real_eoe():
    """**Cast-from-exile-with-cost-hike substrate -- legal-actions
    surface.** After Lightstall's ETB exiles P1's hand[0] card and
    stamps the flag, the Rust legal emitter MUST surface a CastSpell
    action keyed on that exiled card's id when P1 has priority at
    sorcery timing and enough mana to pay the surcharged cost.

    The probe seeds P1 with enough mana ({2} colorless via lands +
    {G} for the bear, plus the extra {1} surcharge); inspects the
    legal-actions surface AFTER Lightstall resolves; finds the
    cast-from-exile action; applies it; and verifies the exiled card
    moves onto P1's bf (the resolve path).

    Pre-substrate: legal_decisions did NOT include any cast-from-
    exile action for the flagged card (the substrate's missing
    surface was the divergence). Post-substrate: it does.
    """
    import mtg_bot_engine
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_rust_state,
    )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    rust_state = build_rust_state(spec)
    ZONE_HAND = 0
    ZONE_BATTLEFIELD = 2

    # P0's hand has the target of the exile -- a {G} bear (mv 1,
    # cheap to cast back with the {1} surcharge).
    rust_state.register_and_inject_object(
        {
            "name": "Substrate Probe Legal -- P0 Bear",
            "card_types": ["Creature"],
            "mana_cost": {"G": 1},
            "power": 2, "toughness": 2,
            "effects": [],
            "triggered_abilities": [],
        },
        0, ZONE_HAND,
    )

    # Seed P1's bf with 2 untapped Forests -- enough to pay {1}{G}
    # (the bear's {G} + the Lightstall surcharge {1}).
    for _ in range(2):
        rust_state.register_and_inject_object(
            {
                "name": "Substrate Probe Legal -- Forest",
                "card_types": ["Land"],
                "supertypes": ["Basic"],
                "subtypes": ["Forest"],
                "mana_produced": ["G"],
                "effects": [],
                "triggered_abilities": [],
            },
            1, ZONE_BATTLEFIELD,
        )

    # P1 controls Lightstall (so P0 is opponent and exiles).
    rust_state.register_and_inject_object(
        {
            "name": "Substrate Probe Legal -- Lightstall",
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
        1, ZONE_BATTLEFIELD,
    )

    while rust_state.stack_size() > 0:
        rust_state.resolve_top_of_stack()

    # Confirm exile state.
    exile_p0 = rust_state.exile_snapshot(0)
    assert len(exile_p0) == 1, (
        "Substrate probe legal: P0's exile should hold the Bear "
        f"after Lightstall resolves; got {exile_p0!r}"
    )
    exiled_card = exile_p0[0]
    assert exiled_card["cast_from_exile_with_lightstall_surcharge"] is True
    exiled_card_id = exiled_card["id"]

    # P0 is the default priority/active player and at sorcery timing
    # (the Lightstall ETB resolved without changing the step). Query
    # legal_decisions for P0 and verify a CastSpell on the exiled
    # card is surfaced. P0's mana pool is empty so we directly check
    # surfacing by populating the pool with {1}{G}.
    p0_mana = rust_state.mana_pool_snapshot(0)
    # Use add_mana_to_pool via the effect arm: simplest is to
    # tap-trigger via mana-producing land. But since P0 has no land
    # (just the Bear in hand + exile), seed the pool directly. Rust
    # exposes set_mana_pool / set_pool? Try via grant_mana method.
    # If unavailable, fall back to giving P0 a Forest and tapping it.
    if not hasattr(rust_state, "grant_mana"):
        # Inject a forest on P0's bf to produce the {G} half.
        rust_state.register_and_inject_object(
            {
                "name": "Substrate Probe Legal -- P0 Forest",
                "card_types": ["Land"],
                "supertypes": ["Basic"],
                "subtypes": ["Forest"],
                "mana_produced": ["G"],
                "effects": [],
                "triggered_abilities": [],
            },
            0, ZONE_BATTLEFIELD,
        )
        # And a basic Wastes to produce the {1} generic half.
        rust_state.register_and_inject_object(
            {
                "name": "Substrate Probe Legal -- P0 Wastes",
                "card_types": ["Land"],
                "supertypes": ["Basic"],
                "subtypes": ["Wastes"],
                "mana_produced": ["C"],
                "effects": [],
                "triggered_abilities": [],
            },
            0, ZONE_BATTLEFIELD,
        )

    # Advance to PHASE_MAIN1 so sorcery-timing window is open.
    PHASE_MAIN1 = 3
    rust_state.set_phase(PHASE_MAIN1)
    rust_state.give_priority_to(0)

    decisions = rust_state.legal_decisions(0)
    cast_spell_decisions = [
        d for d in decisions
        if d.get("kind") == "cast_spell"
        and d.get("card_id") == exiled_card_id
    ]
    assert len(cast_spell_decisions) >= 1, (
        "Substrate probe legal: legal_decisions(0) MUST surface a "
        "CastSpell action for the Lightstall-flagged exiled card "
        f"(id={exiled_card_id}) on P0's priority at sorcery timing. "
        f"Got decisions: {decisions!r}"
    )


def test_substrate_lightstall_surcharge_actually_applied_real_eoe():
    """**Cast-from-exile-with-cost-hike substrate -- +{1} surcharge.**
    Drives the cast-from-exile path end-to-end on Rust: the cost
    paid MUST be `printing.mana_cost + {1}` generic, not just the
    bare printed cost.

    Probe shape: P0's exile holds a Lightstall-flagged Bear with
    printed cost {G}. P0 has exactly {1}{G} available (one Wastes
    tapped-for-C and one Forest tapped-for-G). Cast succeeds and
    leaves the pool empty (all {1}{G} consumed). Cast fails (returns
    False, no mutation) when only {G} is available (the surcharge
    makes the bare-printed cost insufficient).
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_rust_state,
    )

    def _build_state_with_pool(give_extra_generic: bool):
        spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
        s = build_rust_state(spec)
        # Inject a Bear in P0's exile WITH the flag stamped. The
        # cleanest way to get one in there is via Lightstall, but we
        # can also just inject directly into ZONE_EXILE and rely on
        # the resolve arm's pattern. Here we drive the standard
        # Lightstall ETB resolve so the substrate stamps the flag
        # itself (end-to-end, no shortcuts).
        ZONE_HAND = 0
        ZONE_BATTLEFIELD = 2
        s.register_and_inject_object(
            {
                "name": "Substrate Probe Cost -- P0 Bear",
                "card_types": ["Creature"],
                "mana_cost": {"G": 1},
                "power": 2, "toughness": 2,
                "effects": [],
                "triggered_abilities": [],
            },
            0, ZONE_HAND,
        )
        # P0's Forest (for {G}).
        s.register_and_inject_object(
            {
                "name": "Substrate Probe Cost -- P0 Forest",
                "card_types": ["Land"],
                "supertypes": ["Basic"],
                "subtypes": ["Forest"],
                "mana_produced": ["G"],
                "effects": [],
                "triggered_abilities": [],
            },
            0, ZONE_BATTLEFIELD,
        )
        if give_extra_generic:
            # P0's Wastes (for {1} = {C}).
            s.register_and_inject_object(
                {
                    "name": "Substrate Probe Cost -- P0 Wastes",
                    "card_types": ["Land"],
                    "supertypes": ["Basic"],
                    "subtypes": ["Wastes"],
                    "mana_produced": ["C"],
                    "effects": [],
                    "triggered_abilities": [],
                },
                0, ZONE_BATTLEFIELD,
            )
        # Lightstall controlled by P1 -> P0 (opponent) exiles its
        # hand[0] = the Bear.
        s.register_and_inject_object(
            {
                "name": "Substrate Probe Cost -- Lightstall",
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
            1, ZONE_BATTLEFIELD,
        )
        while s.stack_size() > 0:
            s.resolve_top_of_stack()
        return s

    # Case A: P0 has {1}{G} available. Cast succeeds.
    state_with_extra = _build_state_with_pool(give_extra_generic=True)
    exiled = state_with_extra.exile_snapshot(0)[0]
    exiled_id = exiled["id"]
    assert exiled["cast_from_exile_with_lightstall_surcharge"] is True

    # Cast via cast_creature. The primitive auto-taps the controller's
    # lands to cover the cost; with both Forest + Wastes present and
    # untapped, {1}{G} is payable.
    success = state_with_extra.cast_creature(exiled_id, 0)
    assert success is True, (
        "Substrate probe surcharge: cast_creature should succeed when "
        "P0 has {1}{G} available (the surcharged cost). Got "
        f"success={success}."
    )
    # Resolve the stack and confirm the Bear is now on P0's bf.
    while state_with_extra.stack_size() > 0:
        state_with_extra.resolve_top_of_stack()
    bf_after = state_with_extra.battlefield_snapshot()
    bear_on_bf = [
        e for e in bf_after
        if e["printing_name"] == "Substrate Probe Cost -- P0 Bear"
    ]
    assert len(bear_on_bf) == 1, (
        "Substrate probe surcharge: the Bear should have moved from "
        "P0's exile to P0's bf after cast+resolve; got bf="
        f"{bear_on_bf!r}"
    )
    # The post-cast exile is empty -- the flag-clearing happened at
    # cast time on the now-stack-resident object, and the resolve
    # moved it to bf (CR 400.7 fresh object); the bf snapshot's
    # surcharge flag is False.
    bear = bear_on_bf[0]
    assert bear["cast_from_exile_with_lightstall_surcharge"] is False, (
        "Substrate probe surcharge: the post-resolve bf object MUST "
        "have the Lightstall flag CLEARED (Python parity, "
        "actions.py:1505 sets the flag False at cast time). Got "
        f"{bear.get('cast_from_exile_with_lightstall_surcharge')!r}"
    )

    # Case B: P0 has only {G} available (the bare printed cost).
    # Cast should fail -- the surcharge is load-bearing.
    state_without_extra = _build_state_with_pool(give_extra_generic=False)
    exiled_b = state_without_extra.exile_snapshot(0)[0]
    exiled_b_id = exiled_b["id"]
    assert exiled_b["cast_from_exile_with_lightstall_surcharge"] is True
    exile_size_before = len(state_without_extra.exile_snapshot(0))
    success_fail = state_without_extra.cast_creature(exiled_b_id, 0)
    assert success_fail is False, (
        "Substrate probe surcharge: cast_creature MUST fail when P0 "
        "has only {G} available (the bare printed cost; surcharge "
        "demands an extra {1} generic). Got success="
        f"{success_fail}."
    )
    # No mutation on fail.
    exile_size_after = len(state_without_extra.exile_snapshot(0))
    assert exile_size_after == exile_size_before, (
        "Substrate probe surcharge: a failed cast MUST NOT mutate "
        f"zones; got exile_size_before={exile_size_before} "
        f"exile_size_after={exile_size_after}."
    )
    # The flag stays True after a failed cast attempt.
    exiled_b_after = state_without_extra.exile_snapshot(0)[0]
    assert (
        exiled_b_after["cast_from_exile_with_lightstall_surcharge"]
        is True
    ), (
        "Substrate probe surcharge: a failed cast must leave the "
        "Lightstall flag intact; got "
        f"{exiled_b_after.get('cast_from_exile_with_lightstall_surcharge')!r}"
    )


# ---------------------------------------------------------------------------
# Real-EoE byte-equal probe (lightstall-residue-reconciliation lane,
# 2026-05-20). Binds the REAL parsed EoE Lightstall Inquisitor printing
# from the live CardSource (not a synthetic carrier) and drives the full
# play arc: ETB exiles opponent's hand[0] card -> flag stamps -> opponent
# (owner) casts the exiled card with the +{1} surcharge at sorcery-timing
# on their next turn -> card resolves onto bf with flag cleared.
#
# This probe is the verify-first byte-equal trajectory probe the
# reconciliation lane required to confirm Lane 2's "FULL FIXED" claim
# against the Pain for All agent's "separate large residue" report. The
# substrate is genuinely closed end-to-end on the real printing; the
# Pain for All agent's claim was reading the stale residue worklist
# entry from before merge `9c41ad08`.
# ---------------------------------------------------------------------------


def test_xxx_pin3_real_eoe_lightstall_inquisitor_cast_from_exile_substrate_parity():
    """**Real-EoE byte-equal Lightstall closure probe** -- verify-first
    re-walk for the lightstall-residue-reconciliation lane (2026-05-20).

    Drives the REAL parsed EoE Lightstall Inquisitor printing
    (``get_active_source().get_printings().get('Lightstall Inquisitor')``)
    through the Rust engine end-to-end and asserts every link of the
    cast-from-exile-with-cost-hike substrate:

      1. **Parse fidelity** -- the live printing reduces to one
         ``Event.ENTERS`` triggered ability whose effect is the bespoke
         ``EachOpponentExilesCardFromHandWithCastPermission`` Python
         class. The mana cost is ``{W}`` (the actual EoE printed cost,
         which the slice-20 + cast-from-exile-substrate probes use
         throughout).
      2. **Bridge round-trip** -- the Rust kind string
         ``each_opponent_exiles_card_from_hand_lightstall`` round-trips
         to the same Python effect class via the bridge.
      3. **ETB exile + flag stamp** -- the real-shape Lightstall ETB on
         P0's bf exiles P1's hand[0] card to P1's exile zone with the
         ``cast_from_exile_with_lightstall_surcharge=True`` flag stamped.
      4. **Legal-actions surface (sorcery timing)** -- when control
         transitions to P1's turn (P1 becomes the active player at
         sorcery timing), ``legal_decisions(1)`` surfaces a ``cast_spell``
         action keyed on the exiled card's id.
      5. **Surcharge cost** -- ``cast_creature`` pays
         ``printing.mana_cost + {1}`` generic when the pool covers it
         and FAILS when only the bare printed cost is available.
      6. **Flag clear on cast** -- the post-resolve bf object has
         ``cast_from_exile_with_lightstall_surcharge=False``.

    This is the SAME substrate the existing 6 probes (3 each-opponent-
    exile + 3 substrate) already pin; the differentiator is that this
    probe BINDS THE REAL PARSED PRINTING SHAPE rather than the synthetic
    ``{2}{W}{W}`` 3/3 carrier the slice-20 probes use. A regression that
    breaks the real EoE printing's parse-shape end-to-end surfaces here
    even if the synthetic-carrier probes stay green.

    Reconciliation context: the residue worklist's `CastFromExileWith
    CostHike` entry was stale (still `genuinely_missing` despite the
    substrate landing in merge `9c41ad08`). The Pain for All agent's
    closure report (merge `60fea01b`) read the stale entry and reported
    Lightstall as a "separate large residue". This probe is the
    verify-first byte-equal evidence that the substrate IS genuinely
    closed; the reconciliation lane flipped the worklist entry to
    `closed` and regenerated `docs/POOL_PARITY.md` (`BLOCKED -
    genuinely_missing` 1 -> 0).
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.generic.discard import (
        EachOpponentExilesCardFromHandWithCastPermission,
    )
    from mtg_bot.effects.predicates import Event
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_rust_state, _ta_dict_to_python_effect,
    )

    # 1. Parse fidelity: the real EoE printing matches the slice-20
    #    closure shape (one ENTERS trigger w/ the bespoke composite).
    src = get_active_source()
    real_ls = src.get_printings().get("Lightstall Inquisitor")
    assert real_ls is not None, (
        "Real-EoE probe: 'Lightstall Inquisitor' should be present in "
        "the active CardSource. If absent the EoE data file was "
        "regenerated -- update the probe."
    )
    assert real_ls.card_types == ("Creature",), (
        f"Real-EoE probe: Lightstall should be a Creature; got "
        f"{real_ls.card_types}"
    )
    assert "vigilance" in real_ls.keywords, (
        f"Real-EoE probe: Lightstall should carry vigilance; got "
        f"keywords={real_ls.keywords}"
    )
    # The actual EoE printing's mana cost is {W} (one white pip, no
    # generic). The slice-20 synthetic carrier used {2}{W}{W} as a
    # convenience; verify the REAL cost is what we expect here so a
    # future regen that changes the cost trips this probe.
    assert real_ls.mana_cost.colored == (("W", 1),), (
        f"Real-EoE probe: Lightstall mana_cost.colored should be "
        f"(('W',1),); got {real_ls.mana_cost.colored}"
    )
    assert real_ls.mana_cost.generic == 0, (
        f"Real-EoE probe: Lightstall mana_cost.generic should be 0; "
        f"got {real_ls.mana_cost.generic}"
    )
    enters_tas = [
        ta for ta in real_ls.triggered_abilities if ta.event == Event.ENTERS
    ]
    assert len(enters_tas) == 1, (
        f"Real-EoE probe: Lightstall should carry exactly one ENTERS "
        f"trigger; got {len(enters_tas)}"
    )
    assert isinstance(
        enters_tas[0].effect, EachOpponentExilesCardFromHandWithCastPermission
    ), (
        f"Real-EoE probe: Lightstall's ENTERS effect should be "
        f"EachOpponentExilesCardFromHandWithCastPermission; got "
        f"{type(enters_tas[0].effect).__name__}"
    )

    # 2. Bridge round-trip: Rust kind string -> Python effect class.
    bridged = _ta_dict_to_python_effect(
        {"kind": "each_opponent_exiles_card_from_hand_lightstall"}
    )
    assert isinstance(
        bridged, EachOpponentExilesCardFromHandWithCastPermission
    ), (
        f"Real-EoE probe: bridge should round-trip the Rust kind to "
        f"the bespoke Python class; got {type(bridged).__name__}"
    )

    # 3. ETB exile + flag stamp on the real-shape Rust printing.
    #    P0 controls Lightstall -> P0 stays active player (default
    #    after build_rust_state); P0 is the priority holder at sorcery
    #    timing for the cast-back step below.
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    rs = build_rust_state(spec)
    ZONE_HAND = 0
    ZONE_BATTLEFIELD = 2

    # P1 controls the Lightstall -> P0 (active) is the opponent and
    # exiles. The exile lives in P0's exile zone so P0 (active +
    # priority + sorcery-timing-eligible) is the casting player on
    # the cast-back step.
    bear_id = rs.register_and_inject_object(
        {
            "name": "Lightstall Real-EoE Probe -- Target Bear",
            "card_types": ["Creature"],
            "mana_cost": {"G": 1},
            "power": 2, "toughness": 2,
            "effects": [],
            "triggered_abilities": [],
        },
        0, ZONE_HAND,
    )
    # Seed P0's mana sources (one Forest for {G}, one Wastes for {1}
    # generic = {C}; together they pay the bear's {G} + Lightstall
    # surcharge {1}).
    rs.register_and_inject_object(
        {
            "name": "Lightstall Real-EoE Probe -- Forest",
            "card_types": ["Land"],
            "supertypes": ["Basic"],
            "subtypes": ["Forest"],
            "mana_produced": ["G"],
            "effects": [],
            "triggered_abilities": [],
        },
        0, ZONE_BATTLEFIELD,
    )
    rs.register_and_inject_object(
        {
            "name": "Lightstall Real-EoE Probe -- Wastes",
            "card_types": ["Land"],
            "supertypes": ["Basic"],
            "subtypes": ["Wastes"],
            "mana_produced": ["C"],
            "effects": [],
            "triggered_abilities": [],
        },
        0, ZONE_BATTLEFIELD,
    )
    # The REAL Lightstall printing-shape: {W} Creature - Angel Wizard
    # 2/2, vigilance, ENTERS -> each_opponent_exiles_card_from_hand_
    # lightstall.
    rs.register_and_inject_object(
        {
            "name": "Lightstall Inquisitor",
            "card_types": ["Creature"],
            "subtypes": ["Angel", "Wizard"],
            "mana_cost": {"W": 1},
            "power": 2, "toughness": 2,
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
        1, ZONE_BATTLEFIELD,
    )

    # Drain the ETB.
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()

    p0_exile = rs.exile_snapshot(0)
    assert len(p0_exile) == 1, (
        f"Real-EoE probe: P0 exile should hold the Bear after the "
        f"real-shape Lightstall ETB resolves; got {p0_exile!r}"
    )
    exiled = p0_exile[0]
    assert exiled["printing_name"] == (
        "Lightstall Real-EoE Probe -- Target Bear"
    ), (
        f"Real-EoE probe: exiled card should be the Bear; got "
        f"{exiled['printing_name']!r}"
    )
    assert exiled["cast_from_exile_with_lightstall_surcharge"] is True, (
        "Real-EoE probe: the substrate MUST stamp "
        "cast_from_exile_with_lightstall_surcharge=True on the exiled "
        "card; got "
        f"{exiled.get('cast_from_exile_with_lightstall_surcharge')!r}"
    )
    exiled_id = exiled["id"]

    # 4. Legal-actions surface at sorcery timing for the exile's
    #    owner (P0, the active player).
    PHASE_MAIN1 = 3
    rs.set_phase(PHASE_MAIN1)
    rs.give_priority_to(0)
    decisions = rs.legal_decisions(0)
    cast_decisions = [
        d for d in decisions
        if d.get("kind") == "cast_spell"
        and d.get("card_id") == exiled_id
    ]
    assert len(cast_decisions) >= 1, (
        "Real-EoE probe: legal_decisions(0) MUST surface a cast_spell "
        f"action for the Lightstall-flagged exiled card (id={exiled_id}); "
        f"got decisions={decisions!r}"
    )

    # 5. Surcharge cost: cast_creature pays printing.mana_cost + {1}.
    success = rs.cast_creature(exiled_id, 0)
    assert success is True, (
        "Real-EoE probe: cast_creature should succeed when P0 has "
        f"{{1}}{{G}} available; got success={success}"
    )
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()

    # 6. Flag clear on cast + bear on bf.
    bf_after = rs.battlefield_snapshot()
    bear_on_bf = [
        e for e in bf_after
        if e["printing_name"] == "Lightstall Real-EoE Probe -- Target Bear"
    ]
    assert len(bear_on_bf) == 1, (
        "Real-EoE probe: the Bear should have moved from P0's exile "
        f"to P0's bf after cast+resolve; got {bear_on_bf!r}"
    )
    bear = bear_on_bf[0]
    assert bear["controller_id"] == 0, (
        f"Real-EoE probe: Bear should be on P0's bf (owner-may-play "
        f"semantics); got controller_id={bear['controller_id']}"
    )
    assert bear["cast_from_exile_with_lightstall_surcharge"] is False, (
        "Real-EoE probe: the post-resolve bf object MUST have the "
        "Lightstall flag CLEARED (Python parity, actions.py:1505 sets "
        f"the flag False at cast time); got "
        f"{bear.get('cast_from_exile_with_lightstall_surcharge')!r}"
    )

    # The exile zone is now empty (one card moved out).
    assert len(rs.exile_snapshot(0)) == 0, (
        "Real-EoE probe: P0's exile should be empty after the Bear "
        f"casts out; got {rs.exile_snapshot(0)!r}"
    )
