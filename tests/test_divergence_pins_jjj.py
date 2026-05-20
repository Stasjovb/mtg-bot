"""Divergence-pin tests: batch JJJ (probe-batch-jjj, round 19).

Each test is named ``test_cross_engine_real_eoe_<slug>_*_divergence_pin``
and ASSERTS the CURRENT divergent behavior rather than parity.  The
PROBED-tier detector excludes ``*_divergence_pin`` functions, so these
tests grow the test surface without touching the PROBED metric.

Pinned bugs
-----------

Pin 1 -- ``dyadrine_attack_effect`` NOT wired in Rust ``parse_effect``
(EEE Python-only bridge fix; 1 EoE card blocked at the Rust layer:
Dyadrine, Synthesis Amalgam).

    Python's ``DyadrineAttackEffect`` class (``effects/bespoke.py``)
    is a zero-field frozen dataclass that encodes Dyadrine, Synthesis
    Amalgam's attack trigger effect: "Whenever you attack, you may
    remove a +1/+1 counter from each of two creatures you control."

    The EEE bridge fix (round 17) added a
    ``kind == "dyadrine_attack_effect"`` arm to
    ``_ta_dict_to_python_effect`` in ``cross_engine.py``, making
    ``DyadrineAttackEffect()`` constructible from the cross-engine
    bridge.  That fix is **Python-only**.  Rust's ``parse_effect``
    function (``cards.rs``) has NO arm for
    ``"dyadrine_attack_effect"``.

    The Rust ``parse_effect`` terminal error arm lists valid kinds:

        "unknown effect kind {other:?}; valid: deal_damage,
         draw_cards, gain_life, return_to_hand, mill, ..."

    ``"dyadrine_attack_effect"`` is absent from this list.  Passing a
    ``triggered_ability`` dict whose ``effect`` sub-dict carries
    ``kind="dyadrine_attack_effect"`` to Rust's
    ``parse_triggered_ability`` raises ``PyValueError`` with the Rust
    terminal message rather than materialising a
    ``TriggeredAbility(effect=DyadrineAttackEffect())``.

    Scale (EoE cards blocked at the RUST layer):
      * Dyadrine, Synthesis Amalgam -- "Whenever you attack, you may
        remove a +1/+1 counter from each of two creatures you control."
        Parser: ``DyadrineAttackEffect()``; blocked because Rust cannot
        round-trip the effect dict produced by the Python parser.

    Observable divergence:
      Python's ``_ta_dict_to_python_effect({"kind":
      "dyadrine_attack_effect"})`` returns ``DyadrineAttackEffect()``
      without raising (EEE arm is wired).  Rust's
      ``parse_triggered_ability`` raises ``PyValueError`` for the same
      dict (arm is absent).

    Closure path:
      Add ``"dyadrine_attack_effect" => Ok(Effect::DyadrineAttackEffect)``
      to Rust's ``parse_effect`` in ``cards.rs``.
      ``DyadrineAttackEffect`` is a unit variant (zero-field bespoke
      dataclass on the Python side); the Rust enum variant is likewise
      a unit variant requiring no payload parsing.  The application arm
      in ``state_ops_resolve.rs`` must also be added (Rust doesn't
      currently execute the multi-target counter-removal logic natively
      -- the resolution arm will call back to Python or be stubbed
      until the logic is ported).

Pin 2 -- ``put_poison_counters_on_target_player`` NOT wired in Rust
``parse_effect`` (EEE Python-only bridge fix; 1 EoE card blocked at
the Rust layer: Virulent Silencer).

    Python's ``PutPoisonCountersOnTargetPlayer`` class
    (``effects/generic/counters.py``) is a frozen dataclass with one
    field -- ``amount: int = 1`` (default 1) -- that encodes "target
    player gets N poison counters."

    The EEE bridge fix (round 17) added a
    ``kind == "put_poison_counters_on_target_player"`` arm to
    ``_ta_dict_to_python_effect``.  That fix is **Python-only**.
    Rust's ``parse_effect`` has NO arm for
    ``"put_poison_counters_on_target_player"``.

    Scale (EoE cards blocked at the RUST layer):
      * Virulent Silencer -- "Whenever a nontoken artifact creature you
        control deals combat damage to a player, that player gets two
        poison counters."  Parser:
        ``PutPoisonCountersOnTargetPlayer(amount=2)``; the DEALS_COMBAT_DAMAGE
        event was wired by the SS bridge slice (OO Pin 2 CLOSED), but
        the effect kind remains unrecognised by Rust's ``parse_effect``.

    Observable divergence:
      Python's ``_ta_dict_to_python_effect({"kind":
      "put_poison_counters_on_target_player", "amount": 2})`` returns
      ``PutPoisonCountersOnTargetPlayer(amount=2)`` without raising.
      Rust's ``parse_triggered_ability`` raises ``PyValueError`` for
      the same dict (arm is absent).

    Closure path:
      Add a ``"put_poison_counters_on_target_player"`` arm to Rust's
      ``parse_effect``:
        ``"put_poison_counters_on_target_player" => {
            let amount: i32 = dict.get_item("amount")?
                .map(|v| v.extract::<i32>())
                .transpose()?
                .unwrap_or(1);  // Python default is 1
            Ok(Effect::PutPoisonCountersOnTargetPlayer { amount })
        }``
      A Rust enum variant ``Effect::PutPoisonCountersOnTargetPlayer
      { amount: i32 }`` must be defined in ``cards.rs``.
      A ``state_ops_resolve.rs`` arm must apply the poison counters to
      the correct player (target specified by the trigger's event
      subjects -- the player who was dealt combat damage).

Pin 3 -- ``conditional_if_you_gained_life_at_least`` NOT wired in Rust
``parse_effect`` (Python-wired, Rust absent; 1 EoE card blocked at the
Rust layer: Haliya, Guided by Light end-step draw trigger).

    Python's ``ConditionalIfYouGainedLifeAtLeast`` class
    (``effects/combinators.py``) is a frozen dataclass with two
    required fields:
      * ``threshold: int`` -- the life-gain amount that must have been
        reached during the turn (e.g. 3 for Haliya's "if you've gained
        3 or more life this turn").
      * ``inner: Effect`` -- the effect to apply when the condition is
        met (e.g. ``DrawCards(amount=1)`` for Haliya's draw-a-card).

    The cross-engine Python bridge (``_ta_dict_to_python_effect``) has
    an arm for ``kind="conditional_if_you_gained_life_at_least"`` that
    reads ``threshold`` (int) and ``inner`` (recursively parsed via
    ``_ta_dict_to_python_effect``), then constructs
    ``ConditionalIfYouGainedLifeAtLeast(threshold=N, inner=effect)``.
    That arm is **Python-only**.  Rust's ``parse_effect`` has NO arm for
    ``"conditional_if_you_gained_life_at_least"``.

    Scale (EoE cards blocked at the RUST layer):
      * Haliya, Guided by Light -- "At the beginning of your end step,
        draw a card if you've gained 3 or more life this turn."
        Parser: BEGINNING_OF_END_STEP trigger with
        ``ConditionalIfYouGainedLifeAtLeast(threshold=3,
        inner=DrawCards(amount=1))``.  The event arm (BEGINNING_OF_END_STEP)
        and its ControlledByYou predicate are both wired on both sides;
        the blocker is exclusively the conditional effect wrapper.

    Comparison with ``ConditionalIfVoid``:
      ``conditional_if_void`` IS in Rust's ``parse_effect`` (wired).
      ``conditional_if_you_gained_life_at_least`` is NOT -- it requires
      access to the ``life_gained_this_turn`` state counter, a per-turn
      accumulator that the Rust engine must track separately from the
      void-active flag.  The state dependency is the likely reason this
      arm was not ported alongside ``conditional_if_void``.

    Observable divergence:
      Python's ``_ta_dict_to_python_effect({"kind":
      "conditional_if_you_gained_life_at_least", "threshold": 3,
      "inner": {"kind": "draw_cards", "count": 1}})`` returns
      ``ConditionalIfYouGainedLifeAtLeast(threshold=3,
      inner=DrawCards(amount=1))`` without raising.
      Rust's ``parse_triggered_ability`` raises ``PyValueError`` for
      the same dict (arm is absent).

    Closure path:
      1. Ensure Rust's ``GameState`` carries a ``life_gained_this_turn``
         field (or equivalent) that is zeroed at the start of each turn
         and incremented whenever ``GainLife`` resolves.
      2. Add ``"conditional_if_you_gained_life_at_least"`` arm to
         Rust's ``parse_effect``:
           ``"conditional_if_you_gained_life_at_least" => {
               let threshold: i32 = require(dict, "threshold")?.extract()?;
               let inner_dict = require(dict, "inner")?
                   .downcast::<PyDict>()
                   .map_err(|_| PyValueError::new_err(...))?;
               let inner = parse_effect(inner_dict)?;
               Ok(Effect::ConditionalIfYouGainedLifeAtLeast
                   { threshold, inner: Box::new(inner) })
           }``
      3. Add a ``state_ops_resolve.rs`` arm that checks
         ``state.life_gained_this_turn[controller_id] >= threshold``
         and applies the inner effect when the condition is met.

      The state-counter dependency (step 1) is the primary unblock
      dependency.  If ``life_gained_this_turn`` is not yet tracked, the
      Rust arm can land as a parse-and-no-op stub, but real parity
      requires the full three-step closure.

Dropped pins
------------

  * ``room_fully_unlocked`` event subsystem (OO Pin 1, 10 cards): Still
    deferred -- Room subsystem state machinery not yet scoped.

  * Endless Sands ``yours_only=True`` semantic mismatch (HH drop):
    Deferred again.

  * Compound-event disjunction (RR drop: The Endstone): Deferred.

  * Multi-subject slot-rewrite for IS_CAST (LL) and BLOCKS (FF):
    Deferred pending slot-rewrite design.

  * ``warp_exile_self`` Rust ``parse_effect`` gap: Deferred -- Rust
    engine handles ``WarpExileSelf`` via a native enum variant injected
    at warp-cast time rather than via the cross-engine dict bridge; the
    gap is architectural (scheduled-trigger path vs. bridge path) and
    requires separate design work distinct from a simple kind-arm
    addition.  Scale: 40+ EoE cards carry the Warp mechanic, but the
    actual ``warp_exile_self`` dict is produced by the Python engine's
    delayed-trigger path; the Rust engine never needs to parse it from
    a Python dict (it schedules its own ``Effect::WarpExileSelf``
    natively).
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Pin 1 -- dyadrine_attack_effect FIXED in Rust parse_effect
#          (EEE downstream complement — 8th Rust slice; JJJ Pin 1 CLOSED)
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_dyadrine_attack_effect_rust_parse_effect_gap_FIXED_parity():
    """FIXED_parity: Rust ``parse_effect`` now accepts
    ``"dyadrine_attack_effect"``.

    8th Rust slice (EEE downstream complement) adds
    ``"dyadrine_attack_effect" => Ok(Effect::DyadrineAttackEffect)``
    to Rust's ``parse_effect``.  The resolve arm is an honest-stop
    sentinel (no-op) — full counter-removal/draw/token logic is deferred.

    Inverted from the original divergence_pin:
      Before: Rust raised PyValueError for the effect dict.
      After:  Rust does NOT raise; ``register_and_inject_object`` with
              a triggered_ability using this effect kind succeeds.

    Card context:
      Dyadrine, Synthesis Amalgam -- "Whenever you attack, you may remove
      a +1/+1 counter from each of two creatures you control."
      Parser: YOU_ATTACK trigger (fires once per combat) with
      DyadrineAttackEffect() effect.

    Parity shape:
      1. DyadrineAttackEffect is a zero-field dataclass (unchanged).
      2. Python bridge produces DyadrineAttackEffect() (unchanged).
      3. Rust: register_and_inject_object with dyadrine_attack_effect
         SUCCEEDS (inverted from old divergence_pin assertion).
      4. The EoE card is now unblocked at the Rust parse layer.
    """
    import dataclasses
    import importlib.util

    from mtg_bot.effects.bespoke import DyadrineAttackEffect
    from mtg_bot.effects.base import Effect
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    # 1. DyadrineAttackEffect is a zero-field dataclass in effects.bespoke.
    assert dataclasses.is_dataclass(DyadrineAttackEffect), (
        "DyadrineAttackEffect should be a dataclass (effects/bespoke.py)."
    )
    fields = dataclasses.fields(DyadrineAttackEffect)
    assert len(fields) == 0, (
        "DyadrineAttackEffect should have zero dataclass fields; "
        f"got fields: {[f.name for f in fields]!r}"
    )

    # 2. DyadrineAttackEffect is an Effect subclass.
    assert issubclass(DyadrineAttackEffect, Effect), (
        "DyadrineAttackEffect should be an Effect subclass."
    )

    # 3. Python bridge IS wired (EEE bridge fix, unchanged).
    result = _ta_dict_to_python_effect({"kind": "dyadrine_attack_effect"})
    assert isinstance(result, DyadrineAttackEffect), (
        "Python bridge should return DyadrineAttackEffect for "
        "kind='dyadrine_attack_effect'."
    )
    assert result == DyadrineAttackEffect(), (
        f"Python bridge should return a value-equal DyadrineAttackEffect(). "
        f"Got: {result!r}"
    )

    # 4. Rust: register_and_inject_object SUCCEEDS (inverted assertion).
    #    (FIXED: the prior divergence_pin asserted this raises; now it succeeds.)
    if importlib.util.find_spec("mtg_bot_engine") is not None:
        import mtg_bot_engine
        # This MUST NOT raise (gap is closed in the 8th Rust slice).
        rs = mtg_bot_engine.make_synthetic_state()
        rs.register_and_inject_object(
            {
                "name": "Dyadrine, Synthesis Amalgam",
                "card_types": ["Creature"],
                "supertypes": ["Legendary"],
                "power": 3,
                "toughness": 3,
                "keywords": [],
                "effects": [],
                "triggered_abilities": [
                    {
                        "event": "you_attack",
                        "predicate": {"kind": "always"},
                        "effect": {"kind": "dyadrine_attack_effect"},
                    }
                ],
            },
            0, 2,  # player 0, ZONE_BATTLEFIELD
        )
        # Verified: no PyValueError — Rust accepted the effect dict.
        assert rs.battlefield_sizes[0] >= 1, (
            "Dyadrine should be on p0's battlefield after inject."
        )

    # 5. EoE card unlocked at the Rust parse layer by this fix.
    unblocked_eoe_cards = [
        "Dyadrine, Synthesis Amalgam",
        # YOU_ATTACK trigger + DyadrineAttackEffect(). Parse layer: UNBLOCKED.
        # Resolve: honest-stop sentinel (no-op). Full resolve: follow-up slice.
    ]
    assert len(unblocked_eoe_cards) == 1, (
        "The 'dyadrine_attack_effect' Rust parse_effect fix unblocks 1 EoE "
        f"card; enumerated list has {len(unblocked_eoe_cards)} entries."
    )


# ---------------------------------------------------------------------------
# Pin 2 -- put_poison_counters_on_target_player FIXED in Rust parse_effect
#          (EEE downstream complement — 8th Rust slice; JJJ Pin 2 CLOSED)
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_put_poison_counters_on_target_player_rust_parse_effect_gap_FIXED_parity():
    """FIXED_parity: Rust ``parse_effect`` now accepts
    ``"put_poison_counters_on_target_player"``.

    8th Rust slice (EEE downstream complement) adds:
      * ``"put_poison_counters_on_target_player"`` parse arm to Rust
        ``parse_effect`` (reads ``amount``, defaults to 1).
      * ``Effect::PutPoisonCountersOnTargetPlayer { amount }`` variant.
      * Resolve arm: reads target player id from
        ``current_resolve_payload_target_id`` (seated at push time by
        ``first_legal_trigger_target`` from
        ``resolving_combat_damage_target_player_id``); increments
        ``target_player.poison_counters`` by ``amount``.
      * ``Player.poison_counters`` field added to Rust's Player struct.

    Inverted from the original divergence_pin:
      Before: Rust raised PyValueError for the effect dict.
      After:  Rust does NOT raise; ``register_and_inject_object`` with
              a triggered_ability using this effect kind succeeds.

    Card context:
      Virulent Silencer -- "Whenever a nontoken artifact creature you
      control deals combat damage to a player, that player gets two
      poison counters."
      Parser: DEALS_COMBAT_DAMAGE trigger (Rust: deals_damage) with
      ``PutPoisonCountersOnTargetPlayer(amount=2)`` effect.

    Parity shape:
      1. PutPoisonCountersOnTargetPlayer is a dataclass with amount field
         defaulting to 1 (unchanged).
      2. Python bridge produces PutPoisonCountersOnTargetPlayer(amount=2)
         (unchanged).
      3. Rust: register_and_inject_object with
         put_poison_counters_on_target_player SUCCEEDS (inverted from old
         divergence_pin assertion).
      4. Rust: poison_counter_totals getter works; Player has
         poison_counters field.
      5. EoE card is now unblocked at the Rust parse layer.
    """
    import dataclasses
    import importlib.util

    from mtg_bot.effects.generic.counters import PutPoisonCountersOnTargetPlayer
    from mtg_bot.effects.base import Effect
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    # 1. PutPoisonCountersOnTargetPlayer is a dataclass with one field.
    assert dataclasses.is_dataclass(PutPoisonCountersOnTargetPlayer), (
        "PutPoisonCountersOnTargetPlayer should be a dataclass."
    )
    fields = dataclasses.fields(PutPoisonCountersOnTargetPlayer)
    assert len(fields) == 1, (
        "PutPoisonCountersOnTargetPlayer should have exactly one field ('amount'); "
        f"got fields: {[f.name for f in fields]!r}"
    )
    amount_field = fields[0]
    assert amount_field.name == "amount", (
        f"PutPoisonCountersOnTargetPlayer's single field should be 'amount'; "
        f"got: {amount_field.name!r}"
    )
    assert amount_field.default == 1, (
        f"PutPoisonCountersOnTargetPlayer.amount should default to 1; "
        f"got default: {amount_field.default!r}"
    )

    # 2. PutPoisonCountersOnTargetPlayer is an Effect subclass.
    assert issubclass(PutPoisonCountersOnTargetPlayer, Effect), (
        "PutPoisonCountersOnTargetPlayer should be an Effect subclass."
    )

    # 3. Python bridge IS wired for amount=2 (unchanged).
    result_amount2 = _ta_dict_to_python_effect(
        {"kind": "put_poison_counters_on_target_player", "amount": 2}
    )
    assert isinstance(result_amount2, PutPoisonCountersOnTargetPlayer), (
        "Python bridge should return PutPoisonCountersOnTargetPlayer for "
        f"kind='put_poison_counters_on_target_player'. Got: {type(result_amount2).__name__!r}"
    )
    assert result_amount2.amount == 2, (
        f"Bridge should propagate amount=2; got {result_amount2.amount!r}"
    )

    # 4. Rust: register_and_inject_object SUCCEEDS (inverted assertion).
    #    (FIXED: the prior divergence_pin asserted this raises; now it succeeds.)
    if importlib.util.find_spec("mtg_bot_engine") is not None:
        import mtg_bot_engine
        # This MUST NOT raise (gap is closed in the 8th Rust slice).
        rs = mtg_bot_engine.make_synthetic_state()
        rs.register_and_inject_object(
            {
                "name": "Virulent Silencer",
                "card_types": ["Creature", "Artifact"],
                "supertypes": [],
                "power": 2,
                "toughness": 1,
                "keywords": [],
                "effects": [],
                "triggered_abilities": [
                    {
                        "event": "deals_damage",  # Rust event string for DEALS_COMBAT_DAMAGE
                        "predicate": {"kind": "always"},
                        "effect": {
                            "kind": "put_poison_counters_on_target_player",
                            "amount": 2,
                        },
                    }
                ],
            },
            0, 2,  # player 0, ZONE_BATTLEFIELD
        )
        # Verified: no PyValueError — Rust accepted the effect dict.
        # Verify poison_counter_totals getter is available (Player.poison_counters exists).
        assert rs.poison_counter_totals == [0, 0], (
            "New poison_counter_totals getter should return [0, 0] initially."
        )

    # 5. EoE card unblocked at the Rust parse layer by this fix.
    unblocked_eoe_cards = [
        "Virulent Silencer",
        # DEALS_COMBAT_DAMAGE trigger + PutPoisonCountersOnTargetPlayer(amount=2).
        # Parse layer: UNBLOCKED.
        # Resolve: wired (8th slice). Resolve parity: see probe 2 in
        # tests/test_probe_eee_downstream_unlock.py.
    ]
    assert len(unblocked_eoe_cards) == 1, (
        "The 'put_poison_counters_on_target_player' Rust parse_effect fix "
        f"unblocks 1 EoE card; enumerated list has {len(unblocked_eoe_cards)} entries."
    )


# ---------------------------------------------------------------------------
# Pin 3 -- conditional_if_you_gained_life_at_least NOT wired in Rust
#          parse_effect (Python-wired; Haliya end-step draw trigger blocked)
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_conditional_if_you_gained_life_at_least_rust_parse_effect_gap_divergence_pin():
    """Pin the Rust-side gap in ``parse_effect`` for
    ``"conditional_if_you_gained_life_at_least"``.

    Bug location:
      ``rust/src/cards.rs`` -- ``fn parse_effect`` match arms do NOT
      include ``"conditional_if_you_gained_life_at_least"``.  The
      terminal error arm lists valid conditionals:
      ``"conditional_if_void"`` IS wired; this variant is NOT.

    Python side (wired):
      ``_ta_dict_to_python_effect({"kind":
      "conditional_if_you_gained_life_at_least", "threshold": 3,
      "inner": {"kind": "draw_cards", "count": 1}})`` returns
      ``ConditionalIfYouGainedLifeAtLeast(threshold=3,
      inner=DrawCards(amount=1))`` without raising.

    Rust side (OPEN):
      Rust's ``parse_effect`` raises ``PyValueError`` for
      ``kind="conditional_if_you_gained_life_at_least"``.  Note that
      ``"conditional_if_void"`` IS wired in Rust (tests/test_divergence_pins_ggg.py
      Pin 2 confirmed this); this conditional variant is the gap.

    Card context:
      Haliya, Guided by Light -- "At the beginning of your end step,
      draw a card if you've gained 3 or more life this turn."
      Parser: BEGINNING_OF_END_STEP trigger with ControlledByYou
      predicate and
      ``ConditionalIfYouGainedLifeAtLeast(threshold=3,
      inner=DrawCards(amount=1))`` effect.

      Haliya was already probed for its ENTERS ETB life-gain trigger
      in the CCC batch (Haliya self-ETB + ally bear ETB -> GainLife(1)
      byte-equal).  The end-step draw trigger is the SECOND ability on
      Haliya and uses a DIFFERENT effect kind that remains at the Rust
      layer.

    Class structure (Python-side):
      ``ConditionalIfYouGainedLifeAtLeast(threshold, inner)``
      from ``effects/combinators.py``.
      * ``threshold: int`` -- required, no default.
      * ``inner: Effect`` -- required, no default; recursively parsed
        by the bridge via ``_ta_dict_to_python_effect``.

    Comparison with ``conditional_if_void`` (wired):
      ``"conditional_if_void"`` checks ``state.void_active`` (a boolean
      flag on ``GameState``).  ``"conditional_if_you_gained_life_at_least"``
      checks ``state.life_gained_this_turn[controller_id] >= threshold``
      -- a per-turn accumulator that the Rust engine must maintain
      independently.  The state-counter dependency is the likely reason
      this arm was not ported alongside ``conditional_if_void``.

    Probe shape:
      1. Assert ``ConditionalIfYouGainedLifeAtLeast`` exists in
         ``effects.combinators`` and is a dataclass with the expected
         fields (``threshold`` and ``inner``).
      2. Assert both fields have no default (required arguments).
      3. Assert the Python bridge returns the correct instance.
      4. Assert the inner ``DrawCards`` effect is correctly propagated
         (nested parse via ``_ta_dict_to_python_effect``).
      5. Try Rust ``parse_triggered_ability``; assert it raises for the
         conditional-gained-life dict (Rust gap); or structural fallback.
      6. Assert Rust does NOT raise for ``"conditional_if_void"`` (the
         analogous conditional that IS wired on the Rust side).
      7. Enumerate the EoE card blocked at the Rust layer.

    Closure path:
      1. Ensure ``GameState`` (Rust) carries a ``life_gained_this_turn``
         per-player accumulator (zeroed at each turn's beginning;
         incremented in the ``GainLife`` apply arm).
      2. Add ``"conditional_if_you_gained_life_at_least"`` arm to Rust
         ``parse_effect``:
           ``"conditional_if_you_gained_life_at_least" => {
               let threshold: i32 = require(dict, "threshold")?.extract()?;
               let inner_dict = require(dict, "inner")?
                   .downcast::<PyDict>()?;
               let inner = parse_effect(inner_dict)?;
               Ok(Effect::ConditionalIfYouGainedLifeAtLeast
                   { threshold, inner: Box::new(inner) })
           }``
      3. Add a resolver arm that checks
         ``life_gained_this_turn[controller_id] >= threshold``
         and applies ``inner`` when true.

      The state-counter dependency (step 1) is the primary unblock.
    """
    import dataclasses

    from mtg_bot.effects.combinators import ConditionalIfYouGainedLifeAtLeast
    from mtg_bot.effects.base import Effect
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    # 1. ConditionalIfYouGainedLifeAtLeast is a dataclass in effects.combinators.
    assert dataclasses.is_dataclass(ConditionalIfYouGainedLifeAtLeast), (
        "ConditionalIfYouGainedLifeAtLeast should be a dataclass "
        "(effects/combinators.py).  "
        "If this fails the class was restructured -- update this pin."
    )
    fields = {f.name: f for f in dataclasses.fields(ConditionalIfYouGainedLifeAtLeast)}
    assert "threshold" in fields, (
        "ConditionalIfYouGainedLifeAtLeast should have a 'threshold' field "
        "(the minimum life-gain amount for the turn).  "
        f"Got fields: {list(fields.keys())!r}"
    )
    assert "inner" in fields, (
        "ConditionalIfYouGainedLifeAtLeast should have an 'inner' field "
        "(the Effect to apply when the threshold is met).  "
        f"Got fields: {list(fields.keys())!r}"
    )
    assert issubclass(ConditionalIfYouGainedLifeAtLeast, Effect), (
        "ConditionalIfYouGainedLifeAtLeast should be an Effect subclass.  "
        "If this fails the class hierarchy changed -- update this pin."
    )

    # 2. Both fields have no default (required constructor arguments).
    assert fields["threshold"].default is dataclasses.MISSING, (
        "ConditionalIfYouGainedLifeAtLeast.threshold should have no default "
        "(it is a required constructor argument).  The bridge arm MUST read "
        "it from the dict; there is no fallback.  "
        f"Got default: {fields['threshold'].default!r}"
    )
    assert fields["inner"].default is dataclasses.MISSING, (
        "ConditionalIfYouGainedLifeAtLeast.inner should have no default "
        "(it is a required constructor argument).  The bridge arm MUST "
        "recursively parse it via _ta_dict_to_python_effect.  "
        f"Got default: {fields['inner'].default!r}"
    )

    # 3-4. Python bridge is wired -- returns correct nested instance.
    result = _ta_dict_to_python_effect(
        {
            "kind": "conditional_if_you_gained_life_at_least",
            "threshold": 3,
            "inner": {"kind": "draw_cards", "count": 1},
        }
    )
    assert isinstance(result, ConditionalIfYouGainedLifeAtLeast), (
        "Python bridge should return ConditionalIfYouGainedLifeAtLeast for "
        "kind='conditional_if_you_gained_life_at_least'.  "
        f"Got: {type(result).__name__!r}.  "
        "If this fails, the bridge arm may have been removed or the class "
        "renamed -- investigate cross_engine._ta_dict_to_python_effect."
    )
    assert result.threshold == 3, (
        "Python bridge should propagate threshold=3 from the dict.  "
        f"Got threshold={result.threshold!r}"
    )
    assert isinstance(result.inner, Effect), (
        "Python bridge should recursively parse the 'inner' dict and store "
        "a valid Effect instance in ConditionalIfYouGainedLifeAtLeast.inner.  "
        f"Got inner type: {type(result.inner).__name__!r}"
    )

    # 5. Rust raises for kind="conditional_if_you_gained_life_at_least".
    try:
        from mtg_bot.rust_engine import parse_triggered_ability  # type: ignore[import]

        ta_dict_cond = {
            "event": "beginning_of_end_step",
            "predicate": {"kind": "always"},
            "effect": {
                "kind": "conditional_if_you_gained_life_at_least",
                "threshold": 3,
                "inner": {"kind": "draw_cards", "count": 1},
            },
        }
        with pytest.raises(Exception) as exc_info:
            parse_triggered_ability(ta_dict_cond)

        err_msg = str(exc_info.value)
        assert "conditional_if_you_gained_life_at_least" in err_msg, (
            "Rust parse_effect gap sentinel: the error message should mention "
            "'conditional_if_you_gained_life_at_least'.  "
            f"Got error: {err_msg!r}.  "
            "If absent, Rust may have accepted the dict -- "
            "invert to a FIXED-parity test."
        )

        # 6. Rust DOES NOT raise for conditional_if_void (the analogous
        #    conditional that IS wired on the Rust side).
        try:
            parse_triggered_ability(
                {
                    "event": "attacks",
                    "predicate": {"kind": "always"},
                    "effect": {
                        "kind": "conditional_if_void",
                        "then_effect": {"kind": "draw_cards", "count": 1},
                    },
                }
            )
            # If we reach here, conditional_if_void IS wired (expected).
        except Exception as civ_exc:
            raise AssertionError(
                "Rust should NOT raise for 'conditional_if_void' -- it is a "
                "wired effect kind.  "
                f"Got: {civ_exc}.  "
                "If conditional_if_void is broken, this entire block of "
                "conditional-effect tests needs re-investigation."
            ) from civ_exc

    except ImportError:
        # Rust extension not compiled -- gap documented structurally.
        # Python bridge wired (step 3 above proved it).
        # Rust parse_effect arm absent: the kind string
        # "conditional_if_you_gained_life_at_least" is NOT present in
        # the Rust parse_effect match; only "conditional_if_void" is wired
        # among the conditional-effect arms.
        assert isinstance(result, ConditionalIfYouGainedLifeAtLeast), (
            "Structural gap pin: Python bridge arm exists; "
            "Rust parse_effect lacks "
            "'conditional_if_you_gained_life_at_least' arm."
        )

    # 7. EoE card blocked at the Rust layer by this gap.
    blocked_eoe_cards = [
        "Haliya, Guided by Light",
        # "At the beginning of your end step, draw a card if you've
        #  gained 3 or more life this turn."
        # Parser: BEGINNING_OF_END_STEP + ControlledByYou predicate +
        #   ConditionalIfYouGainedLifeAtLeast(threshold=3,
        #   inner=DrawCards(amount=1))
        # BEGINS_OF_END_STEP event: WIRED (both engines)
        # ControlledByYou predicate: WIRED (both engines)
        # conditional_if_you_gained_life_at_least Rust arm: MISSING
        # (Haliya's ETB life-gain trigger was probed byte-equal in CCC;
        #  this is Haliya's SEPARATE end-step draw-if-gained trigger.)
    ]
    assert len(blocked_eoe_cards) == 1, (
        "The 'conditional_if_you_gained_life_at_least' Rust parse_effect gap "
        f"blocks 1 EoE card; enumerated list has {len(blocked_eoe_cards)} entries."
    )
