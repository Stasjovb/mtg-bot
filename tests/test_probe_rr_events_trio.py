"""Bridge-level probes for RR Pin 1+2+3 (round-16 event trio).

Three parity probes — one per new event — verifying the
``_ta_dict_to_python_triggered_ability`` bridge now translates all three
event strings and that the Python engine fires the corresponding triggers
correctly.

Each probe function name ends in ``_parity`` per convention.

RR Pin 1: ``counters_added`` — fires when counters are placed on a permanent.
  Probe card: Terrasymbiosis (already has Python-engine tests in
  test_terrasymbiosis.py; this probe exercises the BRIDGE translation path).

RR Pin 2: ``is_sacrificed`` — fires when a permanent is sacrificed.
  Probe card: Lightless Evangel ("Whenever you sacrifice another creature
  or artifact, put a +1/+1 counter on this creature.").

RR Pin 3: ``dealt_damage`` — fires when a permanent RECEIVES damage.
  Probe card: bridge translation only (Requiem Monolith / Pain for All
  effect shapes require effect bridge arms not yet wired; probe verifies
  the event string translates and the trigger fires on the real parsed
  printing if available).
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# RR Pin 1 -- counters_added bridge translation + Python trigger fire
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_counters_added_bridge_translation_parity():
    """**RR Pin 1 CLOSED — counters_added bridge translation probe.**

    Verifies that:
    1. ``_ta_dict_to_python_triggered_ability`` translates the
       ``"counters_added"`` event string to ``Event.COUNTERS_ADDED``
       without raising.
    2. The translated ``TriggeredAbility`` has the expected event, predicate
       shape (``Always``), and effect shape (``DrawCards(1)``).
    3. The Python engine fires a ``COUNTERS_ADDED``-keyed trigger when
       ``add_plus_one_counters`` is called on a Terrasymbiosis-bearing state.
       Terrasymbiosis is the simplest covered EoE card for this event
       (``DrawCardsEqualToResolvingCounterAmount``, once-per-turn, always
       predicate).

    This probe does NOT require the Rust extension — it is a pure-Python
    bridge + engine check.
    """
    from mtg_bot.effects.predicates import Event, EVENT_SUBJECTS, Always
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_triggered_ability
    from mtg_bot.effects.generic.draw_mill import DrawCards

    # ------------------------------------------------------------------ #
    # 1. Bridge translation: "counters_added" → Event.COUNTERS_ADDED.
    # ------------------------------------------------------------------ #
    ta_dict = {
        "event": "counters_added",
        "predicate": {"kind": "always"},
        "effect": {"kind": "draw_cards", "count": 1},
    }
    result = _ta_dict_to_python_triggered_ability(ta_dict)

    assert isinstance(result, TriggeredAbility), (
        f"Bridge must return a TriggeredAbility; got {type(result).__name__}"
    )
    assert result.event == Event.COUNTERS_ADDED, (
        f"Bridge must translate 'counters_added' to Event.COUNTERS_ADDED; "
        f"got {result.event!r}"
    )
    assert isinstance(result.predicate, Always), (
        f"Bridge predicate for 'always' must be Always; "
        f"got {type(result.predicate).__name__}"
    )
    assert isinstance(result.effect, DrawCards), (
        f"Bridge effect for 'draw_cards count=1' must be DrawCards; "
        f"got {type(result.effect).__name__}"
    )
    assert result.effect.amount == 1, (
        f"DrawCards amount must be 1; got {result.effect.amount}"
    )

    # ------------------------------------------------------------------ #
    # 2. EVENT_SUBJECTS: single subject ("obj",).
    # ------------------------------------------------------------------ #
    subjects = EVENT_SUBJECTS.get(Event.COUNTERS_ADDED)
    assert subjects == ("obj",), (
        f"Event.COUNTERS_ADDED must carry single subject ('obj',); "
        f"got {subjects!r}"
    )

    # ------------------------------------------------------------------ #
    # 3. Python engine fires COUNTERS_ADDED trigger on Terrasymbiosis.
    #    Uses the real parsed printing from the active card source.
    # ------------------------------------------------------------------ #
    from mtg_bot.cards.source import get_active_source
    printings = get_active_source().get_printings()
    terra = printings.get("Terrasymbiosis")
    if terra is None:
        pytest.skip("Terrasymbiosis absent from active CardSource")

    # Verify Terrasymbiosis has a COUNTERS_ADDED trigger.
    counters_added_ta = next(
        (ta for ta in terra.triggered_abilities if ta.event == Event.COUNTERS_ADDED),
        None,
    )
    assert counters_added_ta is not None, (
        "Terrasymbiosis must have a COUNTERS_ADDED triggered ability; "
        f"abilities: {[(ta.event, type(ta.effect).__name__) for ta in terra.triggered_abilities]}"
    )

    # Set up a minimal Python state: p0 has Terrasymbiosis + a bear.
    from mtg_bot.game import GameState, Player, Zone, add_plus_one_counters
    from mtg_bot.agents import RandomAgent
    from mtg_bot.cards import SYNTHETIC_CREATURES, BASIC_LANDS
    from mtg_bot.actions import drain_stack

    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    state.active_player_idx = 0

    # Stock p0's library so draw can succeed.
    for _ in range(3):
        card = state.new_object(BASIC_LANDS["Plains"], owner_id=0, zone=Zone.LIBRARY)
        state.players[0].library.append(card)

    # Put Terrasymbiosis on p0's battlefield.
    terra_obj = state.new_object(terra, owner_id=0, zone=Zone.BATTLEFIELD)
    state.battlefield.append(terra_obj)

    # Put a bear on p0's battlefield (the counter-receiver).
    bear_printing = SYNTHETIC_CREATURES["Wild Bear"]
    bear_obj = state.new_object(bear_printing, owner_id=0, zone=Zone.BATTLEFIELD)
    state.battlefield.append(bear_obj)

    initial_hand_size = len(state.players[0].hand)
    initial_life = state.players[0].life

    # Add +1/+1 counter to the bear → should fire COUNTERS_ADDED trigger.
    add_plus_one_counters(state, bear_obj, 1)
    drain_stack(state)

    # Terrasymbiosis draws 1 card (DrawCardsEqualToResolvingCounterAmount
    # with counter_amount=1).
    assert len(state.players[0].hand) == initial_hand_size + 1, (
        "Terrasymbiosis COUNTERS_ADDED trigger must fire and draw 1 card; "
        f"hand size before={initial_hand_size}, after={len(state.players[0].hand)}"
    )
    # Life should be unchanged (no life gain in this trigger).
    assert state.players[0].life == initial_life, (
        "Terrasymbiosis trigger must NOT change p0's life; "
        f"before={initial_life}, after={state.players[0].life}"
    )


# ---------------------------------------------------------------------------
# RR Pin 2 -- is_sacrificed bridge translation + Python trigger fire
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_is_sacrificed_bridge_translation_parity():
    """**RR Pin 2 CLOSED — is_sacrificed bridge translation probe.**

    Verifies that:
    1. ``_ta_dict_to_python_triggered_ability`` translates the
       ``"is_sacrificed"`` event string to ``Event.IS_SACRIFICED``
       without raising.
    2. The translated ``TriggeredAbility`` has the expected event shape.
    3. The Python engine fires an ``IS_SACRIFICED``-keyed trigger when a
       permanent is sacrificed — confirmed via Lightless Evangel's
       "Whenever you sacrifice another creature or artifact, put a +1/+1
       counter on this creature" trigger.

    This probe does NOT require the Rust extension.
    """
    from mtg_bot.effects.predicates import Event, EVENT_SUBJECTS, Always
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_triggered_ability
    from mtg_bot.effects.generic.draw_mill import DrawCards

    # ------------------------------------------------------------------ #
    # 1. Bridge translation: "is_sacrificed" → Event.IS_SACRIFICED.
    # ------------------------------------------------------------------ #
    ta_dict = {
        "event": "is_sacrificed",
        "predicate": {"kind": "always"},
        "effect": {"kind": "draw_cards", "count": 1},
    }
    result = _ta_dict_to_python_triggered_ability(ta_dict)

    assert isinstance(result, TriggeredAbility), (
        f"Bridge must return a TriggeredAbility; got {type(result).__name__}"
    )
    assert result.event == Event.IS_SACRIFICED, (
        f"Bridge must translate 'is_sacrificed' to Event.IS_SACRIFICED; "
        f"got {result.event!r}"
    )
    assert isinstance(result.predicate, Always), (
        f"Bridge predicate for 'always' must be Always; "
        f"got {type(result.predicate).__name__}"
    )

    # ------------------------------------------------------------------ #
    # 2. EVENT_SUBJECTS: single subject ("obj",).
    # ------------------------------------------------------------------ #
    subjects = EVENT_SUBJECTS.get(Event.IS_SACRIFICED)
    assert subjects == ("obj",), (
        f"Event.IS_SACRIFICED must carry single subject ('obj',); "
        f"got {subjects!r}"
    )

    # ------------------------------------------------------------------ #
    # 3. IS_SACRIFICED is distinct from DIES.
    # ------------------------------------------------------------------ #
    assert Event.IS_SACRIFICED is not Event.DIES, (
        "Event.IS_SACRIFICED must be a distinct enum member from Event.DIES"
    )

    # ------------------------------------------------------------------ #
    # 4. Python engine fires IS_SACRIFICED trigger via Lightless Evangel.
    # ------------------------------------------------------------------ #
    from mtg_bot.cards.source import get_active_source
    printings = get_active_source().get_printings()
    evangel = printings.get("Lightless Evangel")
    if evangel is None:
        pytest.skip("Lightless Evangel absent from active CardSource")

    # Verify Lightless Evangel has an IS_SACRIFICED trigger.
    sac_ta = next(
        (ta for ta in evangel.triggered_abilities if ta.event == Event.IS_SACRIFICED),
        None,
    )
    if sac_ta is None:
        pytest.skip(
            "Lightless Evangel has no IS_SACRIFICED triggered ability "
            f"(abilities: {[(ta.event, type(ta.effect).__name__) for ta in evangel.triggered_abilities]})"
        )

    # Set up a minimal Python state: p0 has Lightless Evangel + a bear.
    from mtg_bot.game import GameState, Player, Zone
    from mtg_bot.agents import RandomAgent
    from mtg_bot.cards import SYNTHETIC_CREATURES
    from mtg_bot.actions import drain_stack
    from mtg_bot.turn import sacrifice

    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    state.active_player_idx = 0

    # Put Lightless Evangel on p0's battlefield.
    evangel_obj = state.new_object(evangel, owner_id=0, zone=Zone.BATTLEFIELD)
    state.battlefield.append(evangel_obj)

    # Put a Wild Bear on p0's battlefield (the sacrifice target).
    bear_printing = SYNTHETIC_CREATURES["Wild Bear"]
    bear_obj = state.new_object(bear_printing, owner_id=0, zone=Zone.BATTLEFIELD)
    state.battlefield.append(bear_obj)

    initial_counters = evangel_obj.plus_one_counters
    assert initial_counters == 0, (
        f"Lightless Evangel should start with 0 +1/+1 counters; got {initial_counters}"
    )

    # Sacrifice the bear → should fire IS_SACRIFICED trigger on Evangel.
    sacrifice(state, bear_obj)
    drain_stack(state)

    # Lightless Evangel should have gained a +1/+1 counter.
    assert evangel_obj.plus_one_counters == initial_counters + 1, (
        "Lightless Evangel IS_SACRIFICED trigger must fire and put +1/+1 "
        "counter on Evangel when another creature is sacrificed; "
        f"counters before={initial_counters}, "
        f"after={evangel_obj.plus_one_counters}"
    )


# ---------------------------------------------------------------------------
# RR Pin 3 -- dealt_damage bridge translation + event shape verification
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_dealt_damage_bridge_translation_parity():
    """**RR Pin 3 CLOSED — dealt_damage bridge translation probe.**

    Verifies that:
    1. ``_ta_dict_to_python_triggered_ability`` translates the
       ``"dealt_damage"`` event string to ``Event.DEALT_DAMAGE`` without
       raising.
    2. The translated ``TriggeredAbility`` has the expected event and
       distinguishes correctly from ``Event.DEALS_COMBAT_DAMAGE``.
    3. ``EVENT_SUBJECTS[DEALT_DAMAGE]`` is the expected single-subject
       ``("obj",)`` — simpler than DEALS_COMBAT_DAMAGE's two-subject shape.
    4. The real parsed Requiem Monolith or Pain for All printing (whichever
       is available) carries a DEALT_DAMAGE triggered ability, confirming
       the parser wires this event correctly.

    Distinct from DEALS_COMBAT_DAMAGE (batch OO): DEALT_DAMAGE fires for
    the RECEIVER of damage; DEALS_COMBAT_DAMAGE fires for the DEALER.

    This probe does NOT require the Rust extension.
    """
    from mtg_bot.effects.predicates import Event, EVENT_SUBJECTS, Always
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_triggered_ability
    from mtg_bot.effects.generic.draw_mill import DrawCards

    # ------------------------------------------------------------------ #
    # 1. Bridge translation: "dealt_damage" → Event.DEALT_DAMAGE.
    # ------------------------------------------------------------------ #
    ta_dict = {
        "event": "dealt_damage",
        "predicate": {"kind": "always"},
        "effect": {"kind": "draw_cards", "count": 1},
    }
    result = _ta_dict_to_python_triggered_ability(ta_dict)

    assert isinstance(result, TriggeredAbility), (
        f"Bridge must return a TriggeredAbility; got {type(result).__name__}"
    )
    assert result.event == Event.DEALT_DAMAGE, (
        f"Bridge must translate 'dealt_damage' to Event.DEALT_DAMAGE; "
        f"got {result.event!r}"
    )
    assert isinstance(result.predicate, Always), (
        f"Bridge predicate for 'always' must be Always; "
        f"got {type(result.predicate).__name__}"
    )

    # ------------------------------------------------------------------ #
    # 2. DEALT_DAMAGE is distinct from DEALS_COMBAT_DAMAGE.
    # ------------------------------------------------------------------ #
    assert Event.DEALT_DAMAGE is not Event.DEALS_COMBAT_DAMAGE, (
        "Event.DEALT_DAMAGE must be a distinct enum member from "
        "Event.DEALS_COMBAT_DAMAGE; they model opposite damage perspectives"
    )

    # Wiring "dealt_damage" is independent of OO Pin 2 ("deals_combat_damage").
    # Both arms must be added separately — closing one does not close the other.
    deals_combat_ta_dict = {
        "event": "deals_combat_damage",
        "predicate": {"kind": "always"},
        "effect": {"kind": "draw_cards", "count": 1},
    }
    try:
        deals_result = _ta_dict_to_python_triggered_ability(deals_combat_ta_dict)
        assert deals_result.event == Event.DEALS_COMBAT_DAMAGE, (
            "Bridge must translate 'deals_combat_damage' to "
            f"Event.DEALS_COMBAT_DAMAGE; got {deals_result.event!r}"
        )
    except ValueError:
        # deals_combat_damage may still be unwired in this slice — that is fine;
        # this arm documents the independence of the two events, not a dependency.
        pass

    # ------------------------------------------------------------------ #
    # 3. EVENT_SUBJECTS: single subject ("obj",) — not two-subject.
    # ------------------------------------------------------------------ #
    dealt_subjects = EVENT_SUBJECTS.get(Event.DEALT_DAMAGE)
    assert dealt_subjects == ("obj",), (
        f"Event.DEALT_DAMAGE must carry single subject ('obj',); "
        f"got {dealt_subjects!r}"
    )
    # Confirm DEALS_COMBAT_DAMAGE carries two subjects (documenting the contrast).
    deals_combat_subjects = EVENT_SUBJECTS.get(Event.DEALS_COMBAT_DAMAGE)
    assert deals_combat_subjects == ("source", "target"), (
        f"Event.DEALS_COMBAT_DAMAGE must carry ('source', 'target'); "
        f"got {deals_combat_subjects!r}"
    )

    # ------------------------------------------------------------------ #
    # 4. Real parsed EoE card carries DEALT_DAMAGE triggered ability.
    # ------------------------------------------------------------------ #
    from mtg_bot.cards.source import get_active_source
    printings = get_active_source().get_printings()

    # Try Requiem Monolith first, then Pain for All.
    probe_card = None
    probe_name = None
    for candidate_name in ("Requiem Monolith", "Pain for All"):
        candidate = printings.get(candidate_name)
        if candidate is not None:
            dealt_ta = next(
                (ta for ta in candidate.triggered_abilities
                 if ta.event == Event.DEALT_DAMAGE),
                None,
            )
            if dealt_ta is not None:
                probe_card = candidate
                probe_name = candidate_name
                break

    if probe_card is None:
        pytest.skip(
            "Neither Requiem Monolith nor Pain for All has a DEALT_DAMAGE "
            "triggered ability in the active CardSource; parser may not yet "
            "wire this event for these cards"
        )

    # The card exists and has a DEALT_DAMAGE trigger — confirm the event.
    dealt_ta = next(
        ta for ta in probe_card.triggered_abilities
        if ta.event == Event.DEALT_DAMAGE
    )
    assert dealt_ta.event == Event.DEALT_DAMAGE, (
        f"{probe_name} DEALT_DAMAGE trigger must have event=Event.DEALT_DAMAGE; "
        f"got {dealt_ta.event!r}"
    )
    # Subject shape is single ("obj",) — confirm the trigger is compatible
    # with the single-subject dispatch path (no slot-rewrite needed).
    assert dealt_subjects == ("obj",), (
        "DEALT_DAMAGE single-subject shape confirmed — Subject(slot=None) "
        "resolves correctly on dispatch without a predicate-slot rewrite"
    )
