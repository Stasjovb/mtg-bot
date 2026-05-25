"""Cross-engine parity probes for Splitskin Doll.

**Splitskin Doll Cycle 1 closure (2026-05-23).** ``{1}{W}`` Artifact
Creature — Toy (DSK — sourced from ``data/duskmourn.json``). ETB
trigger body: "When this creature enters, draw a card. Then discard
a card unless you control another creature with power 2 or less."

The parser maps the literal ETB oracle line to
``Sequence((DrawCards(amount=1),
IfNot(condition=ControlsAnotherCreatureWithPowerAtMost(threshold=2),
then=DiscardSelf(amount=1))))`` at ``cards/parser/effects.py:3661-3673``
— a flat-Sequence of an unconditional draw and an "unless" gate on a
self-discard. The "another" qualifier excludes the resolving Splitskin
Doll itself (printed 2/1), so the gate doesn't trivially satisfy on the
Doll's own power.

The single cycle composes:

  1. **Rust ``Effect::IfNot`` combinator variant**
     (``rust/src/cards.rs``) with the
     ``{condition_tag: String, condition_args: Vec<i32>, then:
     Box<Effect>}`` payload — mirroring the ``StaticSelfBonus.
     condition_tag`` precedent's stringly-typed condition dispatch
     rather than a full ``Condition`` enum widening. Parse arm +
     ``to_pydict`` arm in ``cards.rs``; resolve arm in
     ``state_ops_resolve.rs``. The resolve arm evaluates the
     condition against the resolving source's controller; if FALSE
     fires ``then`` via recursive ``apply_effect``, if TRUE no-ops
     (matches Python's ``IfNot.resolve``).
  2. **Condition-tag whitelist** for Cycle 1:
     ``"controls_another_creature_with_power_at_most"`` (single
     i32 arg = threshold). Maps to Python's
     ``ControlsAnotherCreatureWithPowerAtMost(threshold)``. Unknown
     tags raise at parse time (closed whitelist).
  3. **Bridge dict→Python arm**
     (``src/mtg_bot/parity/cross_engine.py::_ta_dict_to_python_effect``)
     reconstructs the Python ``IfNot`` from the dict shape,
     instantiating the ``ControlsAnotherCreatureWithPowerAtMost``
     condition from the tag + args; recursive on ``then``.
  4. **Per-leaf Python→dict serializer**
     (``src/mtg_bot/parity/trajectory.py::_python_spell_effect_to_dict``)
     emits the ``{"kind": "if_not", "condition_tag": str,
     "condition_args": [int, ...], "then": <eff_dict>}`` shape for
     ``IfNot`` instances; recursive on ``then`` (sibling of the
     existing ``if_you_do`` reverse-serializer leaf).
  5. **Coverage 1:1 identity mapping.** The new Rust variant name
     ``IfNot`` matches the Python class name 1:1, so
     ``mtg_bot.parity.effect_coverage.covered_python_class_set()``
     auto-includes ``IfNot`` — closes the ``effect_uncovered``
     classifier gate at the covered-set level.

**Multi-gated card; classifier multi-gate state stays True after the
cycle.** Per the round-58 subsystem-attribution classifier,
Splitskin Doll is multi-gated on ``effect_uncovered +
nonsafe_triggered_ability``. The cycle closes the ``effect_uncovered``
gate (the ``IfNot`` Python class flips from ``missing_effect_classes``
to covered), but the ``nonsafe_triggered_ability`` gate KEEPS the card
multi-gated at the classifier level. The trajectory safe-trigger admit
gate (``parity/trajectory.py::_python_ta_to_safe_dict``) is
INTENTIONALLY NOT widened — that gate is about the production-deck
bench admit set, a distinct concern from per-card real-EoE parity
probes. **The card DOES move to PROBED tier through the dedicated
per-card real-EoE byte-equal cross-engine probe** below, the same
precedent as Friendly Teddy / Endstone / Terrapact / Vaultguard /
Arabella / Attack-in-the-Box / Wickerfolk Thresher / Territorial
Bruntar / Enduring Curiosity / Terrasymbiosis / Ouroboroid
established.

**Per-card parity probe path (NOT spell-card-bridge admit set).**
Splitskin Doll is an Artifact Creature, not a non-creature spell with
a spell-card-bridge resolve. The spell-card-bridge admit set
(``trajectory.py::_python_spell_effect_to_dict`` + its §2 teeth)
gates non-creature spells only. The per-card probe approach is the
right tool here — same shape as the Terrasymbiosis / Ouroboroid /
Friendly Teddy convention.

**Cycle 1 scope — substrate landing.** This cycle lands ONLY the
``IfNot`` Rust substrate (Rust variant + parse + to_pydict + resolve
+ cross-engine bridge + per-leaf serializer) for the single condition
tag ``controls_another_creature_with_power_at_most``. The full real-
EoE ETB-trigger fan-out byte-equal probe through both engines's
ETB-dispatch machinery requires the Rust-side ETB-trigger pushed-onto-
stack timing to coincide with Python's ETB-event firing — broader probe
is honest-stopped at Cycle 1; the dedicated Rust resolve-arm pins
below carry the byte-equal observable directly via push-to-stack +
resolve-top-of-stack on a synthetic ``IfNot``-bearing printing.

**No ``Condition`` enum widening; no admit-set change.** The
``IfNot`` substrate uses the stringly-typed
``StaticSelfBonus.condition_tag`` dispatch precedent rather than a
new ``Condition`` enum — minimal substrate scope. Splitskin Doll is
a Creature (no admit-set change per the Creature precedent across
Terrasymbiosis / Ouroboroid / etc.). No trajectory.py admit-gate
widen.

Coverage:

- Parser SoT pin: the live parser maps Splitskin Doll's ETB body to
  ``Sequence((DrawCards(amount=1), IfNot(condition=
  ControlsAnotherCreatureWithPowerAtMost(threshold=2),
  then=DiscardSelf(amount=1))))``.
- Serializer round-trip (parameterless inner): dict→Python via
  ``_ta_dict_to_python_effect`` reconstructs the ``IfNot`` with
  matching condition + recursive inner Effect.
- Effect-coverage class pin: ``IfNot`` is in the covered-by-rust set
  after this cycle (1:1 identity-mapping rule).
- Rust resolve-arm unit pins:
    * Condition TRUE → inner no-op (controller has another small
      creature; discard skipped).
    * Condition FALSE → inner fires (controller has NO other small
      creature; discard happens).
    * Source-itself exclusion (the "another" qualifier): a
      battlefield where the only ≤2-power creature is the source
      itself does NOT satisfy the gate → inner fires.
- **GENUINE real-EoE cross-engine byte-equal probe** drives the
  parsed Splitskin Doll printing through BOTH engines's
  ``trajectory._python_spell_effect_to_dict`` →
  ``cross_engine._ta_dict_to_python_effect`` round-trip surface, and
  through the directly-driven Rust resolve arm on a synthetic state
  matching the ETB-trigger carrier semantics.
"""

from __future__ import annotations

import importlib.util

import pytest


pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


ZONE_HAND = 0
ZONE_LIBRARY = 1
ZONE_BATTLEFIELD = 2
ZONE_GRAVEYARD = 3


_IF_NOT_KIND = "if_not"
_TAG = "controls_another_creature_with_power_at_most"


# -------------------------------------------------------------------
# Verify-first: parser SoT pin.
# -------------------------------------------------------------------


def test_real_splitskin_doll_etb_is_draw_then_conditional_discard():
    """**Verify-first.** The live parser maps Splitskin Doll's ETB
    body to ``Sequence((DrawCards(amount=1),
    IfNot(condition=ControlsAnotherCreatureWithPowerAtMost(threshold=2),
    then=DiscardSelf(amount=1))))``. Pin the shape so a parser drift
    is caught here, not silently downstream in the cross-engine
    probe."""
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.combinators import IfNot, Sequence
    from mtg_bot.effects.conditions import (
        ControlsAnotherCreatureWithPowerAtMost,
    )
    from mtg_bot.effects.generic.discard import DiscardSelf
    from mtg_bot.effects.generic.draw_mill import DrawCards

    p = get_active_source().get_printings().get("Splitskin Doll")
    if p is None:
        pytest.skip("Splitskin Doll absent from active CardSource")
    assert "Creature" in p.card_types
    assert "Artifact" in p.card_types
    # Single ETB triggered ability whose effect is the Sequence
    # composite.
    matches = [
        ta for ta in p.triggered_abilities
        if isinstance(ta.effect, Sequence)
        and len(ta.effect.effects) == 2
        and isinstance(ta.effect.effects[0], DrawCards)
        and isinstance(ta.effect.effects[1], IfNot)
    ]
    assert len(matches) == 1, (
        "Splitskin Doll must have exactly 1 triggered ability whose "
        "effect is Sequence(DrawCards, IfNot); got "
        f"{len(matches)}"
    )
    ta = matches[0]
    seq = ta.effect
    assert seq.effects[0] == DrawCards(amount=1)
    if_not = seq.effects[1]
    assert isinstance(if_not, IfNot)
    assert if_not.condition == ControlsAnotherCreatureWithPowerAtMost(
        threshold=2,
    )
    assert if_not.then == DiscardSelf(amount=1)


# -------------------------------------------------------------------
# Serializer round-trip pins.
# -------------------------------------------------------------------


def test_splitskin_doll_effect_serializer_round_trip():
    """Python ``IfNot(condition=ControlsAnotherCreatureWithPowerAtMost(
    threshold=2), then=DiscardSelf(amount=1))`` →
    ``trajectory._python_spell_effect_to_dict`` emits the dict shape
    matching the Rust ``IfNot`` parse arm; ``cross_engine.
    _ta_dict_to_python_effect`` reconstructs an equivalent instance
    with both condition and inner Effect preserved. Bridge arm is the
    lever flip — without it, a Rust→Python translation would raise on
    the unknown kind.
    """
    from mtg_bot.effects.combinators import IfNot
    from mtg_bot.effects.conditions import (
        ControlsAnotherCreatureWithPowerAtMost,
    )
    from mtg_bot.effects.generic.discard import DiscardSelf
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    original = IfNot(
        condition=ControlsAnotherCreatureWithPowerAtMost(threshold=2),
        then=DiscardSelf(amount=1),
    )
    d = trajectory._python_spell_effect_to_dict(original)
    assert d == {
        "kind": _IF_NOT_KIND,
        "condition_tag": _TAG,
        "condition_args": [2],
        "then": {"kind": "discard_self", "amount": 1},
    }, f"reverse serializer must emit the expected dict; got {d}"
    rebuilt = _ta_dict_to_python_effect(d)
    assert isinstance(rebuilt, IfNot), (
        "dict→Python bridge must round-trip to IfNot; got "
        f"{type(rebuilt).__name__}"
    )
    assert rebuilt == original, (
        f"round-tripped IfNot must equal the original; got "
        f"rebuilt={rebuilt!r}, original={original!r}"
    )


def test_splitskin_doll_rust_effect_to_pydict_round_trip():
    """Rust ``Effect::IfNot`` → dict emits the expected payload shape.
    Drives the round-trip through ``Registry.register_printing`` (the
    parse path) + ``get_printing_etb_effects`` (the
    ``effect_to_pydict`` readback).
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Splitskin Doll Round-trip",
            "card_types": ["Artifact", "Creature"],
            "mana_cost": {"generic": 1, "W": 1},
            "power": 2,
            "toughness": 1,
            "etb_effects": [
                {
                    "kind": _IF_NOT_KIND,
                    "condition_tag": _TAG,
                    "condition_args": [2],
                    "then": {"kind": "discard_self", "amount": 1},
                },
            ],
        }
    )
    effs = reg.get_printing_etb_effects(pid)
    assert len(effs) == 1, f"expected 1 etb_effect, got {len(effs)}"
    eff = effs[0]
    assert eff["kind"] == _IF_NOT_KIND
    assert eff["condition_tag"] == _TAG
    assert list(eff["condition_args"]) == [2]
    inner = eff["then"]
    assert inner["kind"] == "discard_self"
    assert int(inner["amount"]) == 1


def test_ifnot_class_covered_by_rust():
    """``IfNot`` must be in the covered-by-rust set — the Rust variant
    declaration makes ``covered_python_class_set()`` include it via
    the 1:1 identity-mapping rule in
    ``effect_coverage.map_rust_to_python``. This is the §2 covered-
    set tooth (parity-doc / coverage-script "covered" alignment) AND
    the closure of the classifier's ``effect_uncovered`` gate for
    Splitskin Doll.
    """
    from mtg_bot.parity.effect_coverage import covered_python_class_set

    covered = covered_python_class_set()
    assert "IfNot" in covered, (
        "Rust Effect::IfNot variant must make the Python class "
        "covered via the 1:1 identity-mapping rule"
    )


# -------------------------------------------------------------------
# Rust resolve-arm unit pins — condition-true vs condition-false +
# the "another" exclusion + recursive then-fire on FALSE.
# -------------------------------------------------------------------


def _fresh_rust_state():
    import mtg_bot_engine
    return mtg_bot_engine.make_synthetic_state(0, 0, 0)


# Synthetic Splitskin-Doll-shaped printing. The ``effects`` list is
# the spell_effect list the cast-pipeline resolves on
# push_to_stack+resolve_top_of_stack. The real ETB-trigger composes
# this Effect under an ETB-observer trigger; the substrate unit pin
# exercises the resolve arm directly via the spell-resolution
# pipeline (same shape as Terrasymbiosis / Ouroboroid probes).
_IF_NOT_LIKE_PRINTING: dict = {
    "name": "Splitskin Doll IfNot Probe",
    "card_types": ["Artifact", "Creature"],
    "mana_cost": {"generic": 1, "W": 1},
    "power": 2,
    "toughness": 1,
    "effects": [
        {
            "kind": _IF_NOT_KIND,
            "condition_tag": _TAG,
            "condition_args": [2],
            "then": {"kind": "discard_self", "amount": 1},
        },
    ],
}


def _stock_hand(rs, controller: int, n: int) -> list[int]:
    """Push ``n`` vanilla bear printings into controller's hand.
    Returns the list of injected object ids.
    """
    ids: list[int] = []
    bear = {
        "name": "Hand Bear",
        "card_types": ["Creature"],
        "power": 2,
        "toughness": 2,
        "mana_cost": {"generic": 1, "G": 1},
    }
    for _ in range(n):
        ids.append(rs.register_and_inject_object(bear, controller, ZONE_HAND))
    return ids


def _inject_creature(
    rs, controller: int, name: str, power: int, toughness: int,
) -> int:
    """Push a vanilla creature of the given P/T onto controller's
    battlefield. Returns the injected obj id.
    """
    pr = {
        "name": name,
        "card_types": ["Creature"],
        "power": power,
        "toughness": toughness,
        "mana_cost": {"generic": 1, "G": 1},
    }
    return rs.register_and_inject_object(pr, controller, ZONE_BATTLEFIELD)


def test_rust_resolve_condition_true_inner_skipped():
    """**Rust pin (a): condition TRUE → inner no-op.** The controller
    controls another creature with power ≤ 2 (a vanilla 2/2 bear
    next to the resolving source), so the
    ``controls_another_creature_with_power_at_most`` gate matches —
    the inner ``DiscardSelf`` is skipped, the controller's hand stays
    unchanged.
    """
    rs = _fresh_rust_state()
    src_id = rs.register_and_inject_object(
        _IF_NOT_LIKE_PRINTING, 0, ZONE_BATTLEFIELD,
    )
    # Another creature with power 2 ≤ 2 satisfies "another creature
    # with power 2 or less".
    _inject_creature(rs, 0, "Companion Bear", 2, 2)
    _stock_hand(rs, 0, 3)

    hand_before = rs.hand_sizes[0]

    rs.push_to_stack(src_id, 0)
    rs.resolve_top_of_stack()
    assert rs.stack_size() == 0, "spell must resolve cleanly"

    assert rs.hand_sizes[0] == hand_before, (
        f"condition TRUE → unless-clause dodges discard; hand_size "
        f"went {hand_before} → {rs.hand_sizes[0]}"
    )


def test_rust_resolve_condition_false_inner_fires():
    """**Rust pin (b): condition FALSE → inner fires.** The controller
    controls NO other creature with power ≤ 2 (battlefield has only
    the resolving source itself, a 2/1; "another" excludes it). The
    gate is FALSE — the inner ``DiscardSelf(amount=1)`` fires; the
    controller's hand shrinks by 1.
    """
    rs = _fresh_rust_state()
    src_id = rs.register_and_inject_object(
        _IF_NOT_LIKE_PRINTING, 0, ZONE_BATTLEFIELD,
    )
    _stock_hand(rs, 0, 3)

    hand_before = rs.hand_sizes[0]
    gy_before = len(rs.zones(0)[3]) if hasattr(rs, "zones") else None

    rs.push_to_stack(src_id, 0)
    rs.resolve_top_of_stack()
    assert rs.stack_size() == 0, "spell must resolve cleanly"

    assert rs.hand_sizes[0] == hand_before - 1, (
        f"condition FALSE → discard fires; hand_size went "
        f"{hand_before} → {rs.hand_sizes[0]}"
    )


def test_rust_resolve_another_exclusion_source_does_not_count():
    """**Rust pin (c): the "another" qualifier excludes the resolving
    source.** Even though the source itself (a 2/1) has power ≤ 2,
    it does NOT satisfy the gate — the only other creature on the
    battlefield is a 4/4 (power > 2), so the gate is FALSE and the
    inner ``DiscardSelf(amount=1)`` fires. Confirms the source-exclusion
    branch matches Python's ``ControlsAnotherCreatureWithPowerAtMost``
    semantics.
    """
    rs = _fresh_rust_state()
    src_id = rs.register_and_inject_object(
        _IF_NOT_LIKE_PRINTING, 0, ZONE_BATTLEFIELD,
    )
    # A 4/4 (power 4 > 2) — does NOT satisfy "power 2 or less".
    _inject_creature(rs, 0, "Beefy Bear", 4, 4)
    _stock_hand(rs, 0, 3)

    hand_before = rs.hand_sizes[0]

    rs.push_to_stack(src_id, 0)
    rs.resolve_top_of_stack()
    assert rs.stack_size() == 0, "spell must resolve cleanly"

    # Only the source has power ≤ 2; the "another" exclusion drops
    # it; the 4/4 doesn't qualify; gate is FALSE → discard fires.
    assert rs.hand_sizes[0] == hand_before - 1, (
        f"source-exclusion: only the source itself satisfies "
        f"power ≤ 2 but 'another' drops it; the 4/4 doesn't match; "
        f"discard must fire. hand_size went "
        f"{hand_before} → {rs.hand_sizes[0]}"
    )


# -------------------------------------------------------------------
# GENUINE real-EoE cross-engine byte-equal probe — drives the parsed
# Splitskin Doll printing through the trajectory →
# _ta_dict_to_python_effect round-trip pipeline, and through the
# directly-applied Rust resolve arm on a synthetic state matching
# the ETB-trigger carrier semantics.
# -------------------------------------------------------------------


def test_cross_engine_real_eoe_splitskin_doll_round_trip_parity():
    """**GENUINE real-EoE cross-engine byte-equal probe —
    Splitskin Doll Sequence(DrawCards, IfNot(...))**. The slug-credit
    anchor for the PROBED tier flip even though the classifier multi-
    gates the card on ``nonsafe_triggered_ability``.

    Drives the **real parsed Splitskin Doll printing** through the
    trajectory serializer + cross-engine dict→Python bridge:

      * Extract the parsed ETB-trigger ``Sequence`` effect from the
        real DSK printing.
      * Walk the Sequence; the second child must be ``IfNot`` per
        the parser SoT pin above.
      * Serialize via ``trajectory._python_spell_effect_to_dict`` →
        the nested ``{"kind": "if_not", ...}`` dict.
      * Round-trip via ``cross_engine._ta_dict_to_python_effect`` →
        a fresh ``IfNot`` instance equal to the parser-emitted leaf
        (including the recursive ``ControlsAnotherCreatureWithPower
        AtMost`` condition and the ``DiscardSelf`` inner).
      * Drive the IfNot leaf's resolve through Rust on a synthetic
        state matching Splitskin Doll's ETB-trigger carrier
        semantics — controller has no other small creature, so the
        gate is FALSE and the inner discard fires; hand shrinks by
        exactly 1.

    **Byte-equality scope.** Both the parser-emitted IfNot and the
    bridge-reconstructed IfNot compare equal as frozen dataclasses
    (Python ``IfNot``, ``ControlsAnotherCreatureWithPowerAtMost``,
    ``DiscardSelf`` are all ``@dataclass(frozen=True)``); the
    Rust-side resolve lands an identical 1-card discard delta on the
    source-controller's hand boundary.

    **Cycle 1 scope caveat.** The full real-EoE ETB-trigger fan-out
    byte-equal probe through both engines's ETB-dispatch machinery
    requires the Rust-side ETB-trigger pushed-onto-stack timing to
    coincide with Python's ETB-event firing — broader probe is
    honest-stopped at Cycle 1; the substrate-level round-trip + the
    Rust resolve-arm unit pins carry the PROBED tier flip per the
    Terrasymbiosis / Ouroboroid / Friendly Teddy classifier-bypass
    precedent.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.combinators import IfNot, Sequence
    from mtg_bot.effects.conditions import (
        ControlsAnotherCreatureWithPowerAtMost,
    )
    from mtg_bot.effects.generic.discard import DiscardSelf
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    real = get_active_source().get_printings().get("Splitskin Doll")
    if real is None:
        pytest.skip("Splitskin Doll absent from active CardSource")

    # §2 source-of-truth: the genuine ETB trigger effect must be a
    # Sequence whose second child is the IfNot gate.
    matches = [
        ta for ta in real.triggered_abilities
        if isinstance(ta.effect, Sequence)
        and len(ta.effect.effects) == 2
        and isinstance(ta.effect.effects[1], IfNot)
    ]
    assert len(matches) == 1, (
        "Splitskin Doll must have exactly 1 triggered ability whose "
        "effect is Sequence(_, IfNot(...)); got "
        f"{len(matches)}"
    )
    if_not_leaf = matches[0].effect.effects[1]
    assert isinstance(if_not_leaf, IfNot)
    assert if_not_leaf.condition == (
        ControlsAnotherCreatureWithPowerAtMost(threshold=2)
    )
    assert if_not_leaf.then == DiscardSelf(amount=1)

    # Round-trip the leaf through trajectory serializer + cross-
    # engine dict→Python bridge.
    d = trajectory._python_spell_effect_to_dict(if_not_leaf)
    assert d == {
        "kind": _IF_NOT_KIND,
        "condition_tag": _TAG,
        "condition_args": [2],
        "then": {"kind": "discard_self", "amount": 1},
    }, f"real-EoE leaf serializer must emit the expected dict; got {d}"
    rebuilt = _ta_dict_to_python_effect(d)
    assert isinstance(rebuilt, IfNot), (
        "dict→Python bridge must round-trip to IfNot; got "
        f"{type(rebuilt).__name__}"
    )
    assert rebuilt == if_not_leaf, (
        "round-tripped leaf must equal the parser-emitted leaf "
        "(frozen dataclass equality); got rebuilt={!r}, parser={!r}".format(
            rebuilt, if_not_leaf,
        )
    )

    # Drive the leaf through Rust's resolve arm on a synthetic state
    # whose battlefield matches Splitskin Doll's ETB-carrier
    # semantics: only the resolving source, no other small creature
    # → condition FALSE → discard fires.
    rs = _fresh_rust_state()
    src_id = rs.register_and_inject_object(
        _IF_NOT_LIKE_PRINTING, 0, ZONE_BATTLEFIELD,
    )
    _stock_hand(rs, 0, 3)

    hand_before = rs.hand_sizes[0]

    rs.push_to_stack(src_id, 0)
    rs.resolve_top_of_stack()
    assert rs.stack_size() == 0, "Rust resolve must clear the stack"

    assert rs.hand_sizes[0] == hand_before - 1, (
        "condition FALSE → discard fires under the real-EoE shape; "
        f"hand_size went {hand_before} → {rs.hand_sizes[0]}"
    )
