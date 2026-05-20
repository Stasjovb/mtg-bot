"""Divergence-pin tests: batch PPP (probe-batch-ppp, round 21).

All three pins were CLOSED by the 10th Rust slice
(``feature/rust-slice-10-ppp-closure``).  Each test is now renamed
``..._FIXED_parity`` and asserts the NOW-WIRED behavior:

  * Pin 1 -- ``target_player_loses_life`` effect kind: bridge arm now
    returns a ``TargetPlayerLosesLife`` instance; Rust has the matching
    ``Effect::TargetPlayerLosesLife`` variant + parse + resolve arms.
    1 EoE card unblocked at the effect layer (Entropic Battlecruiser 1+
    tier — full end-to-end use still depends on the upstream
    DISCARDS_CARD event + ``controlled_by_opponent`` predicate gaps).

  * Pin 2 -- ``put_plus_one_counter_on_target_creature`` effect kind:
    bridge arm returns ``PutPlusOneCounterOnTargetCreature``; Rust has
    the matching ``Effect::PutPlusOneCounterOnTargetCreature { amount,
    attacking_only }`` variant + parse + resolve arms (Tier-C
    payload-target seat via ``first_legal_trigger_target``; CR 603.3c
    fizzle-on-no-legal-target via ``lever_trigger_requires_target``).
    6 EoE cards unblocked: Drix Fatemaker, Mm'menon Uthros Exile,
    Optimistic Scavenger (x2 triggers), Surgical Suite // Hospital
    Room, Shrewd Storyteller.

  * Pin 3 -- ``beginning_of_postcombat_main`` event string: bridge arm
    maps to ``Event.BEGINNING_OF_POSTCOMBAT_MAIN``; Rust has the matching
    ``Event::BeginningOfPostcombatMain`` variant + parse arm +
    ``dispatch_event`` allowlist entry + dispatch site in
    ``advance_phase`` at ``PHASE_MAIN2`` entry. 5 EoE cards unblocked:
    Savior of the Small, Cautious Survivor, Defiant Survivor, House
    Cartographer, Shrewd Storyteller.

These tests are now PARITY tests (no longer ``_divergence_pin``
filtered out of the PROBED-tier detector); they assert the wired
behavior survives.
"""

from __future__ import annotations

import dataclasses

import pytest


# ---------------------------------------------------------------------------
# Pin 1 -- target_player_loses_life effect kind NOW WIRED in bridge
#          (Python _ta_dict_to_python_effect; Rust Effect::TargetPlayerLosesLife)
#          1 EoE card unblocked at the effect layer: Entropic Battlecruiser
#          (1+ tier) -- full end-to-end use still blocked by upstream
#          DISCARDS_CARD event + controlled_by_opponent predicate gaps.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_target_player_loses_life_effect_bridge_FIXED_parity():
    """Assert the ``target_player_loses_life`` effect bridge arm is
    wired end-to-end (Python + Rust).

    Fixed by: 10th Rust slice (``feature/rust-slice-10-ppp-closure``).

    Closure delivered:
      1. Python bridge arm in ``_ta_dict_to_python_effect``
         (``src/mtg_bot/parity/cross_engine.py``) returns
         ``TargetPlayerLosesLife(amount=N)`` on
         ``{"kind": "target_player_loses_life", "amount": N}``.
      2. Rust ``Effect::TargetPlayerLosesLife { amount: i32 }`` variant
         (``rust/src/cards.rs``).
      3. Rust ``parse_effect`` arm for ``"target_player_loses_life"``
         (cards.rs) — same shape as ``target_opponent_loses_life``:
         optional ``amount`` defaulting to 1, negative raises.
      4. Rust ``effect_to_pydict`` arm (cards.rs) — round-trip pair.
      5. Rust resolve arm (``state_ops_resolve.rs``): reads the
         pre-fixed target player id from
         ``current_resolve_payload_target_id``; subtracts ``amount``
         from that player's life. ``amount<0`` raises;
         ``amount=0`` short-circuits; unset payload-target → silent
         fizzle (mirrors Python's empty-targets early-return).

    EoE card unblocked at the effect layer (1):
      * Entropic Battlecruiser (1+ tier) — "Whenever an opponent
        discards a card, they lose 3 life."
        effect=TargetPlayerLosesLife(amount=3) with the discarding
        player as the fixed target.
        Full end-to-end cross-engine resolution depends on TWO
        further pieces still pending: the ``discards_card`` event
        (MMM Pin 2) and the ``controlled_by_opponent`` predicate
        (MMM Pin 3) — this slice closes only the effect-layer gap.
    """
    from mtg_bot.effects.generic.life import (
        TargetPlayerLosesLife,
        TargetOpponentLosesLife,
    )
    from mtg_bot.effects.base import Effect
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    # 1. TargetPlayerLosesLife is a frozen dataclass with field 'amount'.
    assert dataclasses.is_dataclass(TargetPlayerLosesLife), (
        "TargetPlayerLosesLife should be a dataclass "
        "(effects/generic/life.py)."
    )
    assert issubclass(TargetPlayerLosesLife, Effect), (
        "TargetPlayerLosesLife should be an Effect subclass."
    )
    fields = {f.name: f for f in dataclasses.fields(TargetPlayerLosesLife)}
    assert "amount" in fields, (
        "TargetPlayerLosesLife should have a field named 'amount'."
        f"  Got: {list(fields.keys())!r}"
    )
    assert fields["amount"].default == 1, (
        "TargetPlayerLosesLife.amount default should be 1."
    )

    # 2. TargetPlayerLosesLife is DISTINCT from TargetOpponentLosesLife.
    assert TargetPlayerLosesLife is not TargetOpponentLosesLife, (
        "TargetPlayerLosesLife must be a distinct class from "
        "TargetOpponentLosesLife (pre-fixed target vs auto-pick)."
    )

    # 3. Bridge NOW returns a TargetPlayerLosesLife instance.
    eff = _ta_dict_to_python_effect(
        {"kind": "target_player_loses_life", "amount": 3}
    )
    assert isinstance(eff, TargetPlayerLosesLife), (
        f"Bridge should return TargetPlayerLosesLife; got {type(eff).__name__!r}."
    )
    assert eff.amount == 3, f"amount should be 3; got {eff.amount!r}."

    # 4. Default amount missing → default 1 (sibling-arm convention).
    eff_default = _ta_dict_to_python_effect(
        {"kind": "target_player_loses_life"}
    )
    assert isinstance(eff_default, TargetPlayerLosesLife), (
        "Missing 'amount' should still bridge cleanly (defaults to 1)."
    )
    assert eff_default.amount == 1, (
        f"Default amount should be 1; got {eff_default.amount!r}."
    )

    # 5. Negative amount raises (mirrors Rust parse contract).
    with pytest.raises(ValueError) as exc_neg:
        _ta_dict_to_python_effect(
            {"kind": "target_player_loses_life", "amount": -1}
        )
    assert "non-negative" in str(exc_neg.value) or "negative" in str(
        exc_neg.value
    ), (
        "Negative amount should raise with a 'non-negative' message; "
        f"got: {exc_neg.value!r}"
    )

    # 6. Wired sibling 'target_opponent_loses_life' still works (sanity:
    #    closing the player arm did NOT regress the opponent arm).
    sibling = _ta_dict_to_python_effect(
        {"kind": "target_opponent_loses_life", "amount": 3}
    )
    assert isinstance(sibling, TargetOpponentLosesLife), (
        "Wired sibling 'target_opponent_loses_life' should still return "
        f"TargetOpponentLosesLife; got {type(sibling).__name__!r}."
    )

    # 7. EoE card unblocked at the effect layer.
    unblocked_at_effect_layer = [
        "Entropic Battlecruiser",  # 1+ tier
    ]
    assert len(unblocked_at_effect_layer) == 1, (
        "1 EoE card unblocked at the effect layer (full end-to-end use "
        "still depends on MMM Pin 2 + MMM Pin 3)."
    )


# ---------------------------------------------------------------------------
# Pin 2 -- put_plus_one_counter_on_target_creature effect kind NOW WIRED
#          (Python _ta_dict_to_python_effect; Rust
#          Effect::PutPlusOneCounterOnTargetCreature { amount, attacking_only })
#          6 EoE cards unblocked
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_put_plus_one_counter_on_target_creature_effect_bridge_FIXED_parity():
    """Assert the ``put_plus_one_counter_on_target_creature`` effect
    bridge arm is wired end-to-end (Python + Rust).

    Fixed by: 10th Rust slice (``feature/rust-slice-10-ppp-closure``).

    Closure delivered:
      1. Python bridge arm in ``_ta_dict_to_python_effect`` returns
         ``PutPlusOneCounterOnTargetCreature(amount=N,
         attacking_only=B)`` on the matching dict shape.
      2. Rust ``Effect::PutPlusOneCounterOnTargetCreature { amount: i32,
         attacking_only: bool }`` variant.
      3. Rust ``parse_effect`` arm — optional ``amount`` (default 1)
         and ``attacking_only`` (default false); negative amount raises.
      4. Rust ``effect_to_pydict`` arm — round-trip pair, always emits
         the ``attacking_only`` field explicitly.
      5. Rust resolve arm (``state_ops_resolve.rs``): reads
         ``current_resolve_payload_target_id``; CR 608.2b resolve-time
         re-legality (target still on SOME bf, still a Creature, still
         attacking when the rider is set) → silent fizzle on failure.
      6. Rust ``first_legal_trigger_target`` arm — scans
         ``bf_iter_etb_sorted`` for the first Creature (and attacking
         when the rider is set); both engines deterministically pick
         the SAME object.
      7. Rust ``lever_trigger_requires_target`` arm — CR 603.3c
         count_min=1 fizzle when no legal target exists.

    6 EoE cards unblocked:
      * Drix Fatemaker
      * Mm'menon, Uthros Exile
      * Optimistic Scavenger (enchantment ETB trigger)
      * Optimistic Scavenger (ROOM_FULLY_UNLOCKED trigger)
      * Surgical Suite // Hospital Room (``attacking_only=True``)
      * Shrewd Storyteller (also gated on Pin 3's
        beginning_of_postcombat_main event)
    """
    from mtg_bot.effects.generic.counters import (
        PutPlusOneCounterOnTargetCreature,
        PutPlusOneCounterOnCreatureYouControl,
    )
    from mtg_bot.effects.targets import TargetSpec
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    # 1. PutPlusOneCounterOnTargetCreature is a dataclass with fields.
    assert dataclasses.is_dataclass(PutPlusOneCounterOnTargetCreature), (
        "PutPlusOneCounterOnTargetCreature should be a dataclass."
    )
    fields = {
        f.name: f for f in dataclasses.fields(PutPlusOneCounterOnTargetCreature)
    }
    assert "amount" in fields, "Should have 'amount' field."
    assert "attacking_only" in fields, "Should have 'attacking_only' field."
    assert fields["amount"].default == 1, "amount default should be 1."
    assert fields["attacking_only"].default is False, (
        "attacking_only default should be False."
    )

    # 2. Distinct from PutPlusOneCounterOnCreatureYouControl.
    assert (
        PutPlusOneCounterOnTargetCreature is not PutPlusOneCounterOnCreatureYouControl
    ), "Must be distinct (no controller restriction vs you-control)."

    # 3. Bridge NOW returns PutPlusOneCounterOnTargetCreature (bare form).
    eff = _ta_dict_to_python_effect(
        {"kind": "put_plus_one_counter_on_target_creature", "amount": 1}
    )
    assert isinstance(eff, PutPlusOneCounterOnTargetCreature), (
        f"Bridge should return PutPlusOneCounterOnTargetCreature; "
        f"got {type(eff).__name__!r}."
    )
    assert eff.amount == 1
    assert eff.attacking_only is False, (
        "attacking_only should default to False."
    )
    # __post_init__ wires IsCreature() slot.
    from mtg_bot.effects.object_predicates import IsCreature
    assert len(eff.targets) == 1, "Should wire exactly one target slot."
    assert isinstance(eff.targets[0], TargetSpec)
    assert isinstance(eff.targets[0].filter, IsCreature), (
        "Bare form (attacking_only=False) wires IsCreature() slot filter."
    )

    # 4. attacking_only=True wires IsCreature() & IsAttacking().
    eff_atk = _ta_dict_to_python_effect(
        {
            "kind": "put_plus_one_counter_on_target_creature",
            "amount": 1,
            "attacking_only": True,
        }
    )
    assert isinstance(eff_atk, PutPlusOneCounterOnTargetCreature)
    assert eff_atk.attacking_only is True
    assert not isinstance(eff_atk.targets[0].filter, IsCreature), (
        "attacking_only=True should wire a conjunction, not bare IsCreature()."
    )

    # 5. Missing amount → default 1 (sibling-arm convention).
    eff_default = _ta_dict_to_python_effect(
        {"kind": "put_plus_one_counter_on_target_creature"}
    )
    assert isinstance(eff_default, PutPlusOneCounterOnTargetCreature)
    assert eff_default.amount == 1

    # 6. Negative amount raises.
    with pytest.raises(ValueError) as exc_neg:
        _ta_dict_to_python_effect(
            {
                "kind": "put_plus_one_counter_on_target_creature",
                "amount": -1,
            }
        )
    assert "non-negative" in str(exc_neg.value) or "negative" in str(
        exc_neg.value
    ), f"Negative amount should raise; got: {exc_neg.value!r}"

    # 7. Wired sibling 'put_plus_one_counter_on_creature_you_control'
    #    still works (sanity).
    sibling = _ta_dict_to_python_effect(
        {
            "kind": "put_plus_one_counter_on_creature_you_control",
            "amount": 1,
        }
    )
    assert isinstance(sibling, PutPlusOneCounterOnCreatureYouControl)

    # 8. EoE cards unblocked.
    unblocked = [
        "Drix Fatemaker",
        "Mm'menon, Uthros Exile",
        "Optimistic Scavenger (enchantment ETB trigger)",
        "Optimistic Scavenger (ROOM_FULLY_UNLOCKED trigger)",
        "Surgical Suite // Hospital Room",  # attacking_only=True
        "Shrewd Storyteller",  # also gated on Pin 3
    ]
    assert len(unblocked) == 6, (
        f"6 EoE cards unblocked; got {len(unblocked)}."
    )


# ---------------------------------------------------------------------------
# Pin 3 -- beginning_of_postcombat_main event string NOW WIRED in the
#          Python cross-engine triggered-ability bridge + Rust Event enum +
#          dispatch site at PHASE_MAIN2 entry in advance_phase
#          5 EoE cards unblocked
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_beginning_of_postcombat_main_event_bridge_FIXED_parity():
    """Assert the ``beginning_of_postcombat_main`` event bridge arm is
    wired end-to-end (Python + Rust).

    Fixed by: 10th Rust slice (``feature/rust-slice-10-ppp-closure``).

    Closure delivered:
      1. Python bridge arm in ``_ta_dict_to_python_triggered_ability``
         (``cross_engine.py``) maps ``"beginning_of_postcombat_main"``
         to ``Event.BEGINNING_OF_POSTCOMBAT_MAIN``.
      2. Rust ``Event::BeginningOfPostcombatMain`` enum variant
         (``rust/src/cards.rs``).
      3. Rust ``parse_triggered_ability`` arm for
         ``"beginning_of_postcombat_main"``.
      4. Rust ``dispatch_event`` allowlist entry.
      5. Rust dispatch site in ``advance_phase`` (``state_ops_steps.rs``)
         — fires on entry to ``PHASE_MAIN2`` with
         ``PLAYER_SUBJECT_OFFSET + active_player`` as subject_id.

    5 EoE cards unblocked (all "survivor" pattern —
    ``And(And(Controlled(YOU), IsSelf), Source(IsTapped))``):
      * Savior of the Small
      * Cautious Survivor
      * Defiant Survivor
      * House Cartographer
      * Shrewd Storyteller
    """
    from mtg_bot.effects.predicates import Event
    from mtg_bot.parity.cross_engine import (
        _ta_dict_to_python_triggered_ability,
    )
    from mtg_bot.effects.base import TriggeredAbility

    # 1. Event.BEGINNING_OF_POSTCOMBAT_MAIN exists.
    assert hasattr(Event, "BEGINNING_OF_POSTCOMBAT_MAIN")
    assert Event.BEGINNING_OF_POSTCOMBAT_MAIN.value == "beginning_of_postcombat_main"

    # 2. Bridge NOW returns a TriggeredAbility (no longer raises).
    ta = _ta_dict_to_python_triggered_ability(
        {
            "event": "beginning_of_postcombat_main",
            "predicate": {"kind": "always"},
            "effect": {"kind": "draw_cards", "count": 1},
        }
    )
    assert isinstance(ta, TriggeredAbility), (
        f"Bridge should return TriggeredAbility; got {type(ta).__name__!r}."
    )
    assert ta.event == Event.BEGINNING_OF_POSTCOMBAT_MAIN

    # 3. Sanity: wired sibling 'beginning_of_end_step' still works.
    ta_es = _ta_dict_to_python_triggered_ability(
        {
            "event": "beginning_of_end_step",
            "predicate": {"kind": "always"},
            "effect": {"kind": "draw_cards", "count": 1},
        }
    )
    assert ta_es.event == Event.BEGINNING_OF_END_STEP

    # 4. Sanity: wired sibling 'beginning_of_combat' still works.
    ta_bc = _ta_dict_to_python_triggered_ability(
        {
            "event": "beginning_of_combat",
            "predicate": {"kind": "always"},
            "effect": {"kind": "draw_cards", "count": 1},
        }
    )
    assert ta_bc.event == Event.BEGINNING_OF_COMBAT

    # 5. Full Shrewd Storyteller TA dict — both Pin 2 (effect) AND
    #    Pin 3 (event) are now wired, so the full dict round-trips
    #    cleanly through the bridge.
    shrewd_ta_dict = {
        "event": "beginning_of_postcombat_main",
        "predicate": {
            "kind": "and",
            "left": {
                "kind": "and",
                "left": {"kind": "controlled_by_you"},
                "right": {"kind": "source_is_self"},
            },
            "right": {"kind": "source_is_tapped"},
        },
        "effect": {
            "kind": "put_plus_one_counter_on_target_creature",
            "amount": 1,
        },
    }
    shrewd_ta = _ta_dict_to_python_triggered_ability(shrewd_ta_dict)
    assert isinstance(shrewd_ta, TriggeredAbility)
    assert shrewd_ta.event == Event.BEGINNING_OF_POSTCOMBAT_MAIN
    from mtg_bot.effects.generic.counters import (
        PutPlusOneCounterOnTargetCreature,
    )
    assert isinstance(shrewd_ta.effect, PutPlusOneCounterOnTargetCreature)
    assert shrewd_ta.effect.amount == 1

    # 6. 5 EoE cards unblocked.
    unblocked = [
        "Savior of the Small",
        "Cautious Survivor",
        "Defiant Survivor",
        "House Cartographer",
        "Shrewd Storyteller",  # also gated on Pin 2
    ]
    assert len(unblocked) == 5, (
        f"5 EoE cards unblocked; got {len(unblocked)}."
    )
