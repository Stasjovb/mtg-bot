"""Divergence-pin tests: batch PPP (probe-batch-ppp, round 21).

Each test is named ``test_cross_engine_real_eoe_<slug>_*_divergence_pin``
and ASSERTS the CURRENT divergent behavior rather than parity.  The
PROBED-tier detector excludes ``*_divergence_pin`` functions, so these
tests grow the test surface without touching the PROBED metric.

Pinned bugs
-----------

Pin 1 -- ``target_player_loses_life`` effect kind NOT wired in the
Python cross-engine effect bridge (1 EoE card blocked:
Entropic Battlecruiser 1+ tier).

    Python's ``TargetPlayerLosesLife`` class
    (``effects/generic/life.py``) is a frozen dataclass with a single
    optional field ``amount: int = 1`` that encodes the "that player
    loses N life" oracle shape where the TARGET PLAYER is pre-fixed at
    dispatch time via ``fixed_targets`` in the triggered-ability
    plumbing.  This is DISTINCT from ``TargetOpponentLosesLife``
    (same file, line 521), which auto-picks the opponent at resolve
    time and IS wired in the bridge (``kind="target_opponent_loses_life"``
    arm at ``cross_engine.py``).

    The cross-engine effect bridge (``_ta_dict_to_python_effect`` at
    ``cross_engine.py``) has no arm for
    ``kind="target_player_loses_life"``.  Passing a dict with this kind
    causes the bridge to fall through to the terminal:

        raise ValueError(
            "cross_engine triggered_abilities bridge: unsupported "
            "effect kind 'target_player_loses_life' ..."
        )

    Rust-side gap (structural): Rust has no
    ``Effect::TargetPlayerLosesLife`` variant.  The Rust parser and
    resolve machinery only carry ``Effect::TargetOpponentLosesLife``
    (cards.rs:1047, resolve arm at state_ops_resolve.rs:5484).
    ``TargetPlayerLosesLife`` requires a pre-fixed target that the
    DISCARDS_CARD event plumbing wires in as the discarding player;
    that plumbing path doesn't yet exist on Rust.  Both the Python
    bridge gap AND the absent Rust variant must be closed before a
    cross-engine probe for Entropic Battlecruiser's 1+ tier is
    possible.

    Distinction between the two life-loss variants:
      * ``TargetOpponentLosesLife(amount)`` -- auto-picks the
        defending opponent; wired in bridge as
        ``"target_opponent_loses_life"``.
      * ``TargetPlayerLosesLife(amount)`` -- receives a pre-fixed
        target player (the discarding player for Entropic
        Battlecruiser's trigger) via ``fixed_targets`` in the
        dispatch call; NOT wired.

    Scale (EoE card blocked): 1.
      * Entropic Battlecruiser (1+ tier) -- "Whenever an opponent
        discards a card, they lose 3 life."
        Parser: ``Event.DISCARDS_CARD`` + ``Controlled(OPPONENT)``
        predicate; effect: ``TargetPlayerLosesLife(amount=3)`` with
        the discarding player pre-wired as the target via
        ``fixed_targets``.
        Note: this card is ALSO blocked by the ``discards_card``
        event gap (MMM Pin 2) and the ``controlled_by_opponent``
        predicate gap (MMM Pin 3); this pin focuses exclusively on
        the effect-class bridge gap.

    Observable divergence:
      ``_ta_dict_to_python_effect({"kind": "target_player_loses_life",
      "amount": 3})`` raises ``ValueError`` with message containing
      ``"target_player_loses_life"`` and ``"unsupported effect kind"``.
      The analogous ``_ta_dict_to_python_effect({"kind":
      "target_opponent_loses_life", "amount": 3})`` (the wired sibling)
      succeeds and returns ``TargetOpponentLosesLife(amount=3)``.

    Closure path:
      1. Add a ``kind == "target_player_loses_life"`` arm to
         ``_ta_dict_to_python_effect`` that reads ``amount`` (int,
         default 1) and returns ``TargetPlayerLosesLife(amount=amount)``.
      2. Add a Rust ``Effect::TargetPlayerLosesLife { amount: i32 }``
         variant (cards.rs), its ``parse_effect`` arm, and its resolve
         arm in ``state_ops_resolve.rs`` (mirrors the
         ``TargetOpponentLosesLife`` shape but reads
         ``fixed_targets[0]`` — the pre-wired discarding player —
         rather than deriving the opponent from the source controller).
      3. Wire ``fixed_targets`` population in the ``DISCARDS_CARD``
         dispatch path (``turn.py``) so the discarding player is
         available as ``targets[0]`` at resolve time.

Pin 2 -- ``put_plus_one_counter_on_target_creature`` effect kind NOT
wired in the Python cross-engine effect bridge (6 EoE cards blocked).

    Python's ``PutPlusOneCounterOnTargetCreature`` class
    (``effects/generic/counters.py``) is a frozen dataclass with
    fields ``amount: int = 1`` and ``attacking_only: bool = False``
    that encodes the "put N +1/+1 counter(s) on target creature" /
    "put a +1/+1 counter on target attacking creature" oracle shapes.
    Its ``__post_init__`` wires the ``targets`` tuple to a
    ``TargetSpec(IsCreature())`` or
    ``TargetSpec(IsCreature() & IsAttacking())`` slot depending on
    ``attacking_only``.

    The cross-engine effect bridge (``_ta_dict_to_python_effect`` at
    ``cross_engine.py``) has no arm for
    ``kind="put_plus_one_counter_on_target_creature"``.  The bridge
    carries the SIBLING ``put_plus_one_counter_on_creature_you_control``
    arm (``PutPlusOneCounterOnCreatureYouControl``) which restricts
    the target to own-side creatures; the bare "target creature" variant
    with no controller restriction is the gap.  The two are NOT
    interchangeable:

      * ``PutPlusOneCounterOnCreatureYouControl`` -- controller-side
        only (``IsCreature() & ControlledByYou()``); wired.
      * ``PutPlusOneCounterOnTargetCreature`` -- any creature / any
        attacking creature (no controller restriction beyond the
        ``attacking_only`` flag); NOT wired.

    Rust-side gap (structural): Rust has no
    ``Effect::PutPlusOneCounterOnTargetCreature`` variant; the closest
    Rust arm is ``PutPlusOneCounterOnCreatureYouControl { amount }``
    (cards.rs:815), which scans the source controller's own battlefield.
    The EoE cards above use "target creature" (unrestricted) or
    "target attacking creature", neither of which is the own-side-only
    shape.  A new Rust variant is required in addition to the Python
    bridge arm.

    Scale (EoE cards blocked): 6.
      * Drix Fatemaker -- "When this creature enters, put a +1/+1
        counter on target creature."
        effect=PutPlusOneCounterOnTargetCreature(amount=1),
        attacking_only=False
      * Mm'menon, Uthros Exile -- "Whenever another artifact you
        control enters, put a +1/+1 counter on target creature."
        effect=PutPlusOneCounterOnTargetCreature(amount=1),
        attacking_only=False
      * Optimistic Scavenger (Enchantment trigger) -- "Whenever an
        enchantment you control enters, put a +1/+1 counter on target
        creature."
        effect=PutPlusOneCounterOnTargetCreature(amount=1),
        attacking_only=False
      * Optimistic Scavenger (Room trigger) -- "Whenever a Room you
        control becomes fully unlocked, put a +1/+1 counter on target
        creature." (blocked also by the ROOM_FULLY_UNLOCKED event gap)
        effect=PutPlusOneCounterOnTargetCreature(amount=1),
        attacking_only=False
      * Surgical Suite // Hospital Room -- "Whenever you attack, put
        a +1/+1 counter on target attacking creature."
        effect=PutPlusOneCounterOnTargetCreature(amount=1),
        attacking_only=True
      * Shrewd Storyteller -- "At the beginning of your postcombat
        main phase, if this creature is tapped, put a +1/+1 counter
        on target creature." (blocked also by the
        beginning_of_postcombat_main event gap, Pin 3)
        effect=PutPlusOneCounterOnTargetCreature(amount=1),
        attacking_only=False

    Observable divergence:
      ``_ta_dict_to_python_effect({"kind":
      "put_plus_one_counter_on_target_creature", "amount": 1})``
      raises ``ValueError`` with message containing
      ``"put_plus_one_counter_on_target_creature"`` and
      ``"unsupported effect kind"``.  The analogous
      ``_ta_dict_to_python_effect({"kind":
      "put_plus_one_counter_on_creature_you_control", "amount": 1})``
      (the wired sibling) succeeds.

    Closure path:
      1. Add a ``kind == "put_plus_one_counter_on_target_creature"``
         arm to ``_ta_dict_to_python_effect`` that reads ``amount``
         (int, default 1) and ``attacking_only`` (bool, default
         False), then returns
         ``PutPlusOneCounterOnTargetCreature(amount=amount,
         attacking_only=attacking_only)``.
      2. Add a Rust ``Effect::PutPlusOneCounterOnTargetCreature
         { amount: i32, attacking_only: bool }`` variant (cards.rs),
         its ``parse_effect`` arm, and its resolve arm in
         ``state_ops_resolve.rs`` (scan battlefield for first creature
         matching the filter — any creature when ``attacking_only``
         is false, attacking creatures only otherwise).

Pin 3 -- ``beginning_of_postcombat_main`` event string NOT wired in
the Python cross-engine triggered-ability bridge (5 EoE cards blocked).

    Python's ``Event.BEGINNING_OF_POSTCOMBAT_MAIN`` enum member (value
    ``"beginning_of_postcombat_main"``) encodes "at the beginning of
    your postcombat main phase" triggers — the phase immediately
    following the end of combat step.  The string
    ``"beginning_of_postcombat_main"`` is NOT in the
    ``_ta_dict_to_python_triggered_ability`` event-string elif chain in
    ``cross_engine.py``; passing a triggered-ability dict with
    ``"event": "beginning_of_postcombat_main"`` causes the bridge to
    fall through to:

        raise ValueError(
            "cross_engine triggered_abilities bridge: event
            'beginning_of_postcombat_main' is not yet wired"
        )

    Rust-side gap (structural): Rust has no event variant corresponding
    to ``BEGINNING_OF_POSTCOMBAT_MAIN``; the Rust ``Event`` enum
    (``cards.rs``) and ``dispatch_event`` allowlist
    (``state_ops_resolve.rs``) do not include it.  Both the Python
    bridge gap AND the absent Rust event machinery must be closed
    before real cross-engine probes for these cards are possible.

    The "survivor" trio pattern:
      The three "survivor" creature cards (Savior of the Small,
      Cautious Survivor, Defiant Survivor) all share the predicate
      composition ``And(And(Controlled(YOU), IsSelf), Source(IsTapped))``
      -- "at the beginning of your postcombat main phase, if this
      creature is tapped".  The same predicate shape is used by
      House Cartographer and Shrewd Storyteller.  The tapped-source
      predicate (``Source(IsTapped())``) IS wired in the Python
      predicate bridge; the ONLY blocker for all 5 is the unwired
      event string.

    Scale (EoE cards blocked): 5.
      * Savior of the Small -- "At the beginning of your postcombat
        main phase, if this creature is tapped, return target creature
        card from your graveyard to your hand."
        effect=ReturnCreatureFromYourGraveyardToHand
      * Cautious Survivor -- "At the beginning of your postcombat
        main phase, if this creature is tapped, you gain 2 life."
        effect=GainLife(amount=2)
      * Defiant Survivor -- "At the beginning of your postcombat
        main phase, if this creature is tapped, manifest dread twice."
        effect=ManifestDread(count=2)
      * House Cartographer -- "At the beginning of your postcombat
        main phase, if this creature is tapped, ..."
        effect=HouseCartographerSurvivalEffect (bespoke)
      * Shrewd Storyteller -- "At the beginning of your postcombat
        main phase, if this creature is tapped, put a +1/+1 counter
        on target creature."
        effect=PutPlusOneCounterOnTargetCreature(amount=1)
        (also blocked by the put_plus_one_counter_on_target_creature
        bridge gap, Pin 2)

    Observable divergence:
      ``_ta_dict_to_python_triggered_ability({"event":
      "beginning_of_postcombat_main", ...})`` raises ``ValueError``
      with message containing ``"beginning_of_postcombat_main"`` and
      ``"not yet wired"``.
      The analogous call with ``{"event": "beginning_of_end_step",
      ...}`` (a wired event) succeeds.

    Closure path:
      Add ``elif event_str == "beginning_of_postcombat_main":
          event = Event.BEGINNING_OF_POSTCOMBAT_MAIN``
      to the event-string elif chain in
      ``_ta_dict_to_python_triggered_ability``.
      Full end-to-end parity additionally requires the Rust
      ``Event::BeginningOfPostcombatMain`` variant, its
      ``parse_triggered_ability`` arm, and a ``dispatch_event``
      dispatch site at the Python postcombat-main step entry point
      in ``turn.py``.

Dropped pins
------------

  * Room_fully_unlocked (OO Pin 1, 10 cards): deferred -- Room subsystem
    not yet scoped.

  * would_create_token (UU Pin 2): preemptive structural guard, deferred.

  * DrawCardsByConditionMultiplier (GGG Pin 3 / AAA Pin 3): deferred --
    Condition serialization not yet designed.

  * MMM Pins 1+2+3 (spells_cast_this_turn / discards_card /
    controlled_by_opponent): still open from round 20; not re-pinned here.

  * DDD Pins 1+2+3 (SurveyMechanActivationEffect /
    ExileTopXOfLibraryMayPlayThisTurn /
    SearchLibraryForEquipmentToBattlefield): still deferred.

  * Persistent: Equip lane attached_to=None, Endless Sands yours_only,
    MovePlusOneCounter false-positive, Cast LIFO-ordering,
    compound-event disjunction.
"""

from __future__ import annotations

import dataclasses

import pytest


# ---------------------------------------------------------------------------
# Pin 1 -- target_player_loses_life effect kind NOT wired in bridge
#          (Python _ta_dict_to_python_effect, no Rust variant)
#          1 EoE card blocked: Entropic Battlecruiser (1+ tier)
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_target_player_loses_life_effect_bridge_gap_divergence_pin():
    """Pin the effect bridge gap for ``target_player_loses_life``.

    Bug location (Python bridge):
      ``src/mtg_bot/parity/cross_engine.py`` --
      ``_ta_dict_to_python_effect`` has no arm for
      ``kind="target_player_loses_life"``.  All unrecognised kinds fall
      through to the terminal:

          raise ValueError(
              "cross_engine triggered_abilities bridge: unsupported "
              "effect kind 'target_player_loses_life' ..."
          )

    Bug location (Rust layer -- structural):
      ``rust/src/cards.rs`` has no ``Effect::TargetPlayerLosesLife``
      variant.  Only ``Effect::TargetOpponentLosesLife`` exists (wired
      at cards.rs:1047, resolved at state_ops_resolve.rs:5484); the
      pre-fixed-target variant needed for Entropic Battlecruiser's
      DISCARDS_CARD trigger is absent.

    Distinctness from the wired sibling:
      * ``TargetOpponentLosesLife(amount)`` -- auto-picks the
        defending opponent at resolve time; wired in bridge as
        ``"target_opponent_loses_life"``.
      * ``TargetPlayerLosesLife(amount)`` -- receives a pre-fixed
        target player (the discarding player) via ``fixed_targets``
        at dispatch; NOT wired.

    EoE card blocked (1):
      * Entropic Battlecruiser (1+ tier) -- "Whenever an opponent
        discards a card, they lose 3 life."
        effect=TargetPlayerLosesLife(amount=3) with the discarding
        player as the fixed target.
        Note: also blocked by the ``discards_card`` event gap (MMM
        Pin 2) and the ``controlled_by_opponent`` predicate gap (MMM
        Pin 3); this pin targets the effect-class layer specifically.

    Probe shape:
      1. Assert ``TargetPlayerLosesLife`` is a frozen dataclass with
         one field ``amount: int = 1``.
      2. Assert ``TargetPlayerLosesLife`` is DISTINCT from
         ``TargetOpponentLosesLife`` (different class objects, different
         resolve semantics: pre-fixed vs auto-picked).
      3. Assert the bridge raises ``ValueError`` for
         ``kind="target_player_loses_life"`` (pin the gap).
      4. Assert the error message contains
         ``"target_player_loses_life"`` and ``"unsupported effect
         kind"``.
      5. Assert the wired sibling ``"target_opponent_loses_life"``
         does NOT raise (sanity: symmetric arm is present).
      6. Enumerate the EoE card blocked by this gap.

    Closure path:
      Add a ``kind == "target_player_loses_life"`` arm to
      ``_ta_dict_to_python_effect`` that reads ``amount`` (default 1)
      and returns ``TargetPlayerLosesLife(amount=amount)``.  Rust
      counterpart: add ``Effect::TargetPlayerLosesLife { amount }``
      variant + parse arm + resolve arm (reads pre-fixed target from
      ``fixed_targets[0]``).
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
        "(effects/generic/life.py).  "
        "If this fails the class was restructured -- update this pin."
    )
    assert issubclass(TargetPlayerLosesLife, Effect), (
        "TargetPlayerLosesLife should be an Effect subclass.  "
        "If this fails the class hierarchy changed."
    )
    fields = {f.name: f for f in dataclasses.fields(TargetPlayerLosesLife)}
    assert "amount" in fields, (
        "TargetPlayerLosesLife should have a field named 'amount' (int, "
        "the number of life the target player loses).  "
        f"Got fields: {list(fields.keys())!r}"
    )
    assert fields["amount"].default == 1, (
        "TargetPlayerLosesLife.amount default should be 1 "
        "(mirrors TargetOpponentLosesLife's default convention).  "
        f"Got default: {fields['amount'].default!r}"
    )
    inst = TargetPlayerLosesLife(amount=3)
    assert inst.amount == 3, (
        f"TargetPlayerLosesLife(amount=3).amount should be 3; "
        f"got {inst.amount!r}"
    )

    # 2. TargetPlayerLosesLife is DISTINCT from TargetOpponentLosesLife.
    assert TargetPlayerLosesLife is not TargetOpponentLosesLife, (
        "TargetPlayerLosesLife must be a distinct class from "
        "TargetOpponentLosesLife.  The pre-fixed-target variant "
        "receives the discarding player via fixed_targets; the "
        "auto-picked variant derives the opponent from the source "
        "controller at resolve time.  Closing the opponent bridge "
        "arm does NOT close the player gap."
    )

    # 3-4. Bridge raises ValueError for the unwired effect kind.
    unwired_eff_dict = {"kind": "target_player_loses_life", "amount": 3}
    with pytest.raises(ValueError) as exc_info:
        _ta_dict_to_python_effect(unwired_eff_dict)

    err_msg = str(exc_info.value)
    assert "target_player_loses_life" in err_msg, (
        "Bridge gap sentinel: the ValueError message should mention "
        "'target_player_loses_life' so the gap is immediately "
        "identifiable.  "
        f"Got message: {err_msg!r}"
    )
    assert "unsupported effect kind" in err_msg, (
        "Bridge gap sentinel: the ValueError should contain "
        "'unsupported effect kind' confirming the "
        "_ta_dict_to_python_effect dispatcher produced this error.  "
        f"Got message: {err_msg!r}"
    )

    # 5. Sanity: the wired sibling 'target_opponent_loses_life' does NOT
    #    raise.  This confirms the bridge has the symmetric arm and
    #    that closing it did NOT accidentally close the player variant.
    try:
        sibling = _ta_dict_to_python_effect(
            {"kind": "target_opponent_loses_life", "amount": 3}
        )
        assert isinstance(sibling, TargetOpponentLosesLife), (
            "Wired sibling 'target_opponent_loses_life' should return "
            "a TargetOpponentLosesLife instance; "
            f"got {type(sibling).__name__!r}."
        )
        assert sibling.amount == 3, (
            f"Wired sibling amount should be 3; got {sibling.amount!r}."
        )
    except ValueError as e:
        raise AssertionError(
            "Sanity: 'target_opponent_loses_life' is a wired effect "
            "kind and should NOT raise ValueError -- "
            f"got: {e}"
        ) from e

    # 6. EoE card blocked by this gap.
    blocked_eoe_cards = [
        "Entropic Battlecruiser",
        # 1+ tier: "Whenever an opponent discards a card, they lose 3
        # life."  effect=TargetPlayerLosesLife(amount=3).
        # The discarding player is the fixed target (pre-wired at
        # dispatch time via fixed_targets, not chosen by the caster).
        # Also blocked by: MMM Pin 2 (discards_card event gap) and
        # MMM Pin 3 (controlled_by_opponent predicate gap).
    ]
    assert len(blocked_eoe_cards) == 1, (
        "The 'target_player_loses_life' effect bridge gap blocks 1 "
        "EoE card (Entropic Battlecruiser 1+ tier).  "
        f"Enumerated list has {len(blocked_eoe_cards)} entries."
    )


# ---------------------------------------------------------------------------
# Pin 2 -- put_plus_one_counter_on_target_creature effect kind NOT wired in
#          bridge (Python _ta_dict_to_python_effect, no Rust variant)
#          6 EoE cards blocked: Drix Fatemaker, Mm'menon Uthros Exile,
#          Optimistic Scavenger (x2 triggers), Surgical Suite // Hospital
#          Room, Shrewd Storyteller
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_put_plus_one_counter_on_target_creature_effect_bridge_gap_divergence_pin():
    """Pin the effect bridge gap for
    ``put_plus_one_counter_on_target_creature``.

    Bug location (Python bridge):
      ``src/mtg_bot/parity/cross_engine.py`` --
      ``_ta_dict_to_python_effect`` has no arm for
      ``kind="put_plus_one_counter_on_target_creature"``.  The bridge
      carries the SIBLING arm
      ``"put_plus_one_counter_on_creature_you_control"``
      (``PutPlusOneCounterOnCreatureYouControl``), which restricts
      targets to own-side creatures.  The bare "any target creature"
      / "target attacking creature" variant with no controller
      restriction is the gap.

    Bug location (Rust layer -- structural):
      ``rust/src/cards.rs`` has no
      ``Effect::PutPlusOneCounterOnTargetCreature`` variant.  The
      closest Rust arm is
      ``Effect::PutPlusOneCounterOnCreatureYouControl { amount }``
      (cards.rs:815), which scans the source controller's OWN
      battlefield.  The EoE cards above use unrestricted "target
      creature" or "target attacking creature" — not the own-side-only
      shape.

    Distinctness from the wired sibling:
      * ``PutPlusOneCounterOnCreatureYouControl(amount)`` --
        restricts to ``IsCreature() & ControlledByYou()``; wired as
        ``"put_plus_one_counter_on_creature_you_control"``.
      * ``PutPlusOneCounterOnTargetCreature(amount, attacking_only)``
        -- ``IsCreature()`` (or ``IsCreature() & IsAttacking()`` when
        ``attacking_only=True``); no controller restriction; NOT
        wired.

    EoE cards blocked (6):
      * Drix Fatemaker -- "When this creature enters, put a +1/+1
        counter on target creature." (attacking_only=False)
      * Mm'menon, Uthros Exile -- "Whenever another artifact you
        control enters, put a +1/+1 counter on target creature."
        (attacking_only=False)
      * Optimistic Scavenger (Enchantment ETB trigger) -- "Whenever
        an enchantment you control enters, put a +1/+1 counter on
        target creature." (attacking_only=False)
      * Optimistic Scavenger (ROOM_FULLY_UNLOCKED trigger) -- "Whenever
        a Room you control becomes fully unlocked, put a +1/+1 counter
        on target creature." (attacking_only=False; also blocked by the
        ROOM_FULLY_UNLOCKED event gap, OO Pin 1)
      * Surgical Suite // Hospital Room -- "Whenever you attack, put a
        +1/+1 counter on target attacking creature." (attacking_only=True)
      * Shrewd Storyteller -- "At the beginning of your postcombat main
        phase, if this creature is tapped, put a +1/+1 counter on
        target creature." (attacking_only=False; also blocked by the
        beginning_of_postcombat_main event gap, Pin 3)

    Probe shape:
      1. Assert ``PutPlusOneCounterOnTargetCreature`` is a dataclass
         with fields ``amount`` and ``attacking_only``.
      2. Assert ``attacking_only=False`` default wires an
         ``IsCreature()`` slot filter (unrestricted).
      3. Assert ``attacking_only=True`` wires an
         ``IsCreature() & IsAttacking()`` slot filter.
      4. Assert ``PutPlusOneCounterOnTargetCreature`` is DISTINCT from
         ``PutPlusOneCounterOnCreatureYouControl``.
      5. Assert the bridge raises ``ValueError`` for
         ``kind="put_plus_one_counter_on_target_creature"`` (pin the
         gap).
      6. Assert the error message contains
         ``"put_plus_one_counter_on_target_creature"`` and
         ``"unsupported effect kind"``.
      7. Assert the wired sibling
         ``"put_plus_one_counter_on_creature_you_control"`` does NOT
         raise (sanity).
      8. Enumerate the 6 EoE cards blocked.

    Closure path:
      Add a ``kind == "put_plus_one_counter_on_target_creature"``
      arm that reads ``amount`` (default 1) and ``attacking_only``
      (default False), then returns
      ``PutPlusOneCounterOnTargetCreature(amount=amount,
      attacking_only=attacking_only)``.  Rust counterpart: new
      ``Effect::PutPlusOneCounterOnTargetCreature { amount: i32,
      attacking_only: bool }`` variant + parse arm + resolve arm
      (scan battlefield for first matching creature).
    """
    from mtg_bot.effects.generic.counters import (
        PutPlusOneCounterOnTargetCreature,
        PutPlusOneCounterOnCreatureYouControl,
    )
    from mtg_bot.effects.base import Effect
    from mtg_bot.effects.targets import TargetSpec
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    # 1. PutPlusOneCounterOnTargetCreature is a dataclass with
    #    fields 'amount' and 'attacking_only'.
    assert dataclasses.is_dataclass(PutPlusOneCounterOnTargetCreature), (
        "PutPlusOneCounterOnTargetCreature should be a dataclass "
        "(effects/generic/counters.py).  "
        "If this fails the class was restructured -- update this pin."
    )
    fields = {f.name: f for f in dataclasses.fields(PutPlusOneCounterOnTargetCreature)}
    assert "amount" in fields, (
        "PutPlusOneCounterOnTargetCreature should have an 'amount' field "
        "(the number of +1/+1 counters to add).  "
        f"Got fields: {list(fields.keys())!r}"
    )
    assert "attacking_only" in fields, (
        "PutPlusOneCounterOnTargetCreature should have an 'attacking_only' "
        "field (True = Hospital Room half: target attacking creature only).  "
        f"Got fields: {list(fields.keys())!r}"
    )
    assert fields["amount"].default == 1, (
        "PutPlusOneCounterOnTargetCreature.amount default should be 1.  "
        f"Got default: {fields['amount'].default!r}"
    )
    assert fields["attacking_only"].default is False, (
        "PutPlusOneCounterOnTargetCreature.attacking_only default should "
        "be False (the bare 'target creature' form, not 'target attacking "
        "creature').  "
        f"Got default: {fields['attacking_only'].default!r}"
    )

    # 2. attacking_only=False wires a single IsCreature slot (unrestricted).
    bare = PutPlusOneCounterOnTargetCreature(amount=1, attacking_only=False)
    assert len(bare.targets) == 1, (
        "PutPlusOneCounterOnTargetCreature(attacking_only=False) should "
        "wire exactly one TargetSpec slot.  "
        f"Got {len(bare.targets)} slots."
    )
    bare_spec = bare.targets[0]
    assert isinstance(bare_spec, TargetSpec), (
        "The single slot should be a TargetSpec instance.  "
        f"Got {type(bare_spec).__name__!r}."
    )
    # The filter should accept a creature (IsCreature() check).
    from mtg_bot.effects.object_predicates import IsCreature, IsAttacking
    assert isinstance(bare_spec.filter, IsCreature), (
        "attacking_only=False: slot filter should be IsCreature() (bare, "
        "no IsAttacking conjunction).  "
        f"Got filter type: {type(bare_spec.filter).__name__!r}."
    )

    # 3. attacking_only=True wires an IsCreature() & IsAttacking() slot.
    attacking = PutPlusOneCounterOnTargetCreature(amount=1, attacking_only=True)
    assert len(attacking.targets) == 1, (
        "PutPlusOneCounterOnTargetCreature(attacking_only=True) should "
        "wire exactly one TargetSpec slot.  "
        f"Got {len(attacking.targets)} slots."
    )
    atk_spec = attacking.targets[0]
    # The filter must not be a bare IsCreature (it is a conjunction).
    assert not isinstance(atk_spec.filter, IsCreature), (
        "attacking_only=True: slot filter should NOT be a bare IsCreature(); "
        "it should be an IsCreature() & IsAttacking() conjunction.  "
        f"Got filter type: {type(atk_spec.filter).__name__!r}."
    )

    # 4. DISTINCT from PutPlusOneCounterOnCreatureYouControl.
    assert PutPlusOneCounterOnTargetCreature is not PutPlusOneCounterOnCreatureYouControl, (
        "PutPlusOneCounterOnTargetCreature must be a distinct class from "
        "PutPlusOneCounterOnCreatureYouControl.  The 'you control' variant "
        "restricts targets to own-side creatures; the 'target creature' "
        "variant admits any creature (or any attacking creature).  "
        "Closing the 'you control' bridge arm does NOT close this gap."
    )

    # 5-6. Bridge raises ValueError for the unwired effect kind.
    unwired_eff_dict = {"kind": "put_plus_one_counter_on_target_creature", "amount": 1}
    with pytest.raises(ValueError) as exc_info:
        _ta_dict_to_python_effect(unwired_eff_dict)

    err_msg = str(exc_info.value)
    assert "put_plus_one_counter_on_target_creature" in err_msg, (
        "Bridge gap sentinel: the ValueError message should mention "
        "'put_plus_one_counter_on_target_creature' so the gap is "
        "immediately identifiable.  "
        f"Got message: {err_msg!r}"
    )
    assert "unsupported effect kind" in err_msg, (
        "Bridge gap sentinel: the ValueError should contain "
        "'unsupported effect kind' confirming the "
        "_ta_dict_to_python_effect dispatcher produced this error.  "
        f"Got message: {err_msg!r}"
    )

    # attacking_only=True variant also raises (same gap).
    with pytest.raises(ValueError) as exc_attacking:
        _ta_dict_to_python_effect({
            "kind": "put_plus_one_counter_on_target_creature",
            "amount": 1,
            "attacking_only": True,
        })
    err_attacking = str(exc_attacking.value)
    assert "put_plus_one_counter_on_target_creature" in err_attacking, (
        "attacking_only=True variant should also raise with the gap message.  "
        f"Got: {err_attacking!r}"
    )

    # 7. Sanity: wired sibling 'put_plus_one_counter_on_creature_you_control'
    #    does NOT raise.
    try:
        sibling = _ta_dict_to_python_effect({
            "kind": "put_plus_one_counter_on_creature_you_control",
            "amount": 1,
        })
        assert isinstance(sibling, PutPlusOneCounterOnCreatureYouControl), (
            "Wired sibling should return a "
            "PutPlusOneCounterOnCreatureYouControl instance; "
            f"got {type(sibling).__name__!r}."
        )
    except ValueError as e:
        raise AssertionError(
            "Sanity: 'put_plus_one_counter_on_creature_you_control' is a "
            "wired effect kind and should NOT raise ValueError -- "
            f"got: {e}"
        ) from e

    # 8. EoE cards blocked by this gap.
    blocked_eoe_cards = [
        "Drix Fatemaker",
        # "When this creature enters, put a +1/+1 counter on target
        # creature." attacking_only=False.
        "Mm'menon, Uthros Exile",
        # "Whenever another artifact you control enters, put a +1/+1
        # counter on target creature." attacking_only=False.
        "Optimistic Scavenger (enchantment ETB trigger)",
        # "Whenever an enchantment you control enters, put a +1/+1
        # counter on target creature." attacking_only=False.
        "Optimistic Scavenger (ROOM_FULLY_UNLOCKED trigger)",
        # "Whenever a Room you control becomes fully unlocked, put a
        # +1/+1 counter on target creature." attacking_only=False.
        # (also blocked by OO Pin 1: ROOM_FULLY_UNLOCKED event gap)
        "Surgical Suite // Hospital Room",
        # "Whenever you attack, put a +1/+1 counter on target
        # attacking creature." attacking_only=True.
        "Shrewd Storyteller",
        # "At the beginning of your postcombat main phase, if this
        # creature is tapped, put a +1/+1 counter on target creature."
        # attacking_only=False.  (also blocked by Pin 3:
        # beginning_of_postcombat_main event gap)
    ]
    assert len(blocked_eoe_cards) == 6, (
        "The 'put_plus_one_counter_on_target_creature' effect bridge gap "
        "blocks 6 EoE cards.  "
        f"Enumerated list has {len(blocked_eoe_cards)} entries.  "
        "Update the list if new cards are found or the count changes."
    )


# ---------------------------------------------------------------------------
# Pin 3 -- beginning_of_postcombat_main event string NOT wired in the
#          Python cross-engine triggered-ability bridge
#          5 EoE cards blocked: Savior of the Small, Cautious Survivor,
#          Defiant Survivor, House Cartographer, Shrewd Storyteller
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_beginning_of_postcombat_main_event_bridge_gap_divergence_pin():
    """Pin the bridge gap for the ``beginning_of_postcombat_main`` event
    string in ``_ta_dict_to_python_triggered_ability``.

    Bug location (Python bridge):
      ``src/mtg_bot/parity/cross_engine.py`` --
      ``_ta_dict_to_python_triggered_ability``'s event-string elif chain
      does NOT include ``"beginning_of_postcombat_main"``.  Passing a
      triggered-ability dict with this event causes the bridge to fall
      through to:

          raise ValueError(
              "cross_engine triggered_abilities bridge: event
              'beginning_of_postcombat_main' is not yet wired"
          )

    Rust-side gap (structural):
      The Rust ``Event`` enum (``rust/src/cards.rs``) has no
      ``BeginningOfPostcombatMain`` (or equivalent) variant.  The
      Rust ``dispatch_event`` allowlist
      (``state_ops_resolve.rs``) likewise does not include it.

    The "survivor" predicate pattern:
      All 5 blocked EoE cards share the predicate
      ``And(And(Controlled(YOU), IsSelf), Source(IsTapped()))`` --
      "at the beginning of your postcombat main phase, if this creature
      is tapped."  The ``Source(IsTapped())`` predicate IS wired in the
      Python predicate bridge (``kind="source_is_tapped"`` arm).  The
      SOLE blocker for all 5 cards is the unwired event string.

    Scale (EoE cards blocked): 5.
      * Savior of the Small -- effect=ReturnCreatureFromYourGraveyardToHand
      * Cautious Survivor -- effect=GainLife(amount=2)
      * Defiant Survivor -- effect=ManifestDread(count=2)
      * House Cartographer -- effect=HouseCartographerSurvivalEffect
      * Shrewd Storyteller -- effect=PutPlusOneCounterOnTargetCreature
        (also blocked by Pin 2: put_plus_one_counter_on_target_creature
        effect bridge gap)

    Probe shape:
      1. Assert ``Event.BEGINNING_OF_POSTCOMBAT_MAIN`` exists in the
         Python enum and has the expected string value.
      2. Assert the bridge raises ``ValueError`` for
         ``event="beginning_of_postcombat_main"`` (pin the gap).
      3. Assert the error message contains
         ``"beginning_of_postcombat_main"`` and ``"not yet wired"``.
      4. Assert a wired event (``"beginning_of_end_step"``) does NOT
         raise (sanity).
      5. Assert a second wired adjacent event
         (``"beginning_of_combat"``) also does NOT raise (further
         sanity: the phase-boundary event family is otherwise well
         wired).
      6. Assert the full Shrewd Storyteller TA dict fails at the EVENT
         layer (this pin) rather than the effect layer (Pin 2), since
         the event is checked first in the bridge.
      7. Enumerate the 5 EoE cards blocked.

    Closure path:
      Add ``elif event_str == "beginning_of_postcombat_main":
          event = Event.BEGINNING_OF_POSTCOMBAT_MAIN``
      to the event-string elif chain.  Full end-to-end parity
      additionally requires the Rust ``Event::BeginningOfPostcombatMain``
      variant, its ``parse_triggered_ability`` arm, and a
      ``dispatch_event`` dispatch site at the Python postcombat-main
      step entry in ``turn.py``.
    """
    from mtg_bot.effects.predicates import Event
    from mtg_bot.parity.cross_engine import (
        _ta_dict_to_python_triggered_ability,
    )
    from mtg_bot.effects.base import TriggeredAbility

    # 1. Event.BEGINNING_OF_POSTCOMBAT_MAIN exists in the Python enum.
    assert hasattr(Event, "BEGINNING_OF_POSTCOMBAT_MAIN"), (
        "Event.BEGINNING_OF_POSTCOMBAT_MAIN should be a member of the "
        "Event enum (effects/predicates.py).  "
        "If this fails the enum member was renamed -- update this pin."
    )
    assert isinstance(Event.BEGINNING_OF_POSTCOMBAT_MAIN, Event), (
        "Event.BEGINNING_OF_POSTCOMBAT_MAIN should be an Event enum instance."
    )
    assert Event.BEGINNING_OF_POSTCOMBAT_MAIN.value == "beginning_of_postcombat_main", (
        "Event.BEGINNING_OF_POSTCOMBAT_MAIN.value should be "
        "'beginning_of_postcombat_main'; "
        f"got {Event.BEGINNING_OF_POSTCOMBAT_MAIN.value!r}"
    )

    # 2-3. Bridge raises ValueError for the unwired event.
    unwired_ta_dict = {
        "event": "beginning_of_postcombat_main",
        "predicate": {"kind": "always"},
        "effect": {"kind": "draw_cards", "count": 1},
    }
    with pytest.raises(ValueError) as exc_info:
        _ta_dict_to_python_triggered_ability(unwired_ta_dict)

    err_msg = str(exc_info.value)
    assert "beginning_of_postcombat_main" in err_msg, (
        "Bridge gap sentinel: the ValueError message should mention "
        "'beginning_of_postcombat_main' so the gap is immediately "
        "identifiable.  "
        f"Got message: {err_msg!r}.  "
        "If 'beginning_of_postcombat_main' is absent, the error-arm "
        "message changed -- update this assertion."
    )
    assert "not yet wired" in err_msg, (
        "Bridge gap sentinel: the ValueError should contain 'not yet wired' "
        "(from the terminal event-elif fallthrough).  "
        f"Got message: {err_msg!r}.  "
        "If the message changed, update this assertion."
    )

    # 4. Sanity: wired event 'beginning_of_end_step' does NOT raise.
    try:
        r_bes = _ta_dict_to_python_triggered_ability({
            "event": "beginning_of_end_step",
            "predicate": {"kind": "always"},
            "effect": {"kind": "draw_cards", "count": 1},
        })
        assert isinstance(r_bes, TriggeredAbility), (
            "Wired event 'beginning_of_end_step' should produce a "
            f"TriggeredAbility; got {type(r_bes).__name__}."
        )
        assert r_bes.event == Event.BEGINNING_OF_END_STEP, (
            "'beginning_of_end_step' should translate to "
            f"Event.BEGINNING_OF_END_STEP; got {r_bes.event!r}."
        )
    except ValueError as e:
        raise AssertionError(
            "Sanity: 'beginning_of_end_step' is a wired event and should "
            f"NOT raise ValueError -- got: {e}"
        ) from e

    # 5. Sanity: wired adjacent event 'beginning_of_combat' also
    #    does NOT raise.
    try:
        r_bc = _ta_dict_to_python_triggered_ability({
            "event": "beginning_of_combat",
            "predicate": {"kind": "always"},
            "effect": {"kind": "draw_cards", "count": 1},
        })
        assert isinstance(r_bc, TriggeredAbility), (
            "Wired event 'beginning_of_combat' should produce a "
            f"TriggeredAbility; got {type(r_bc).__name__}."
        )
        assert r_bc.event == Event.BEGINNING_OF_COMBAT, (
            "'beginning_of_combat' should translate to "
            f"Event.BEGINNING_OF_COMBAT; got {r_bc.event!r}."
        )
    except ValueError as e:
        raise AssertionError(
            "Sanity: 'beginning_of_combat' is a wired event and should "
            f"NOT raise ValueError -- got: {e}"
        ) from e

    # 6. Shrewd Storyteller full TA dict -- the event-layer error fires
    #    BEFORE the effect-layer error (Pin 2), since event is parsed
    #    first.  This confirms Pin 3 is the outer blocker for this card.
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
    with pytest.raises(ValueError) as shrewd_exc:
        _ta_dict_to_python_triggered_ability(shrewd_ta_dict)

    shrewd_err = str(shrewd_exc.value)
    assert "beginning_of_postcombat_main" in shrewd_err, (
        "Shrewd Storyteller full TA dict should fail with the event-gap "
        "error ('beginning_of_postcombat_main' not yet wired) since the "
        "event is parsed before the effect.  "
        f"Got error: {shrewd_err!r}.  "
        "If the error mentions 'put_plus_one_counter_on_target_creature' "
        "instead, the bridge changed parse order -- update both Pin 2 and "
        "Pin 3 accordingly."
    )
    assert "not yet wired" in shrewd_err, (
        "Shrewd Storyteller full TA error should contain 'not yet wired' "
        "(the event-elif fallthrough message).  "
        f"Got error: {shrewd_err!r}."
    )

    # 7. EoE cards blocked by this gap.
    blocked_eoe_cards = [
        "Savior of the Small",
        # "At the beginning of your postcombat main phase, if this
        # creature is tapped, return target creature card from your
        # graveyard to your hand."
        # effect=ReturnCreatureFromYourGraveyardToHand
        "Cautious Survivor",
        # "At the beginning of your postcombat main phase, if this
        # creature is tapped, you gain 2 life."
        # effect=GainLife(amount=2)
        "Defiant Survivor",
        # "At the beginning of your postcombat main phase, if this
        # creature is tapped, manifest dread twice."
        # effect=ManifestDread(count=2)
        "House Cartographer",
        # "At the beginning of your postcombat main phase, if this
        # creature is tapped, ..."
        # effect=HouseCartographerSurvivalEffect (bespoke)
        "Shrewd Storyteller",
        # "At the beginning of your postcombat main phase, if this
        # creature is tapped, put a +1/+1 counter on target creature."
        # effect=PutPlusOneCounterOnTargetCreature (also blocked by
        # Pin 2)
    ]
    assert len(blocked_eoe_cards) == 5, (
        "The 'beginning_of_postcombat_main' event bridge gap blocks 5 "
        "EoE cards.  "
        f"Enumerated list has {len(blocked_eoe_cards)} entries.  "
        "Update the list if new cards are found or the count changes."
    )
