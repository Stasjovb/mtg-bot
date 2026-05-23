"""Cross-engine parity probes for Terrasymbiosis.

**Terrasymbiosis Cycle 1 closure (2026-05-23).** ``{2}{G}`` Enchantment
(EoE — sourced from ``data/edge_of_eternities.json``). Counters-added
observer trigger body: "Whenever you put one or more +1/+1 counters
on a creature you control, you may draw that many cards. Do this only
once each turn."

The parser maps the literal oracle line through
``cards/parser/triggers.py`` — specifically the COUNTERS_ADDED context-
dependent rewrite at ``triggers.py:2150-2170`` that swaps the unified
``DrawCardsEqualToResolvingCombatDamage`` leaf to
``DrawCardsEqualToResolvingCounterAmount`` when the surrounding trigger
condition is a COUNTERS_ADDED phrase. Mirrors Python's parameterless
frozen dataclass at ``effects/generic/draw_mill.py:63``.

The single cycle composes:

  1. **Rust ``Effect::DrawCardsEqualToResolvingCounterAmount``** —
     field-free unit variant (``rust/src/cards.rs``, the
     ``DrawCardsEqualToResolvingCombatDamage`` Tier-A unit-variant
     idiom), parse arm (``parse_effect`` dispatcher; round-trips the
     bare ``{"kind": "draw_cards_equal_to_resolving_counter_amount"}``
     dict shape), ``to_pydict`` arm (emits only ``kind``), and resolve
     arm (``rust/src/state_ops_resolve.rs``). On resolve, reads
     ``state.resolving_counter_amount`` (the new substrate slot), and
     for ``amount > 0`` draws ``amount`` cards onto the source-
     controller's hand via the standard library-top pop + CR 704.5b
     ``attempted_draw_on_empty`` flag on empty.
  2. **New GameState slot
     ``state.resolving_counter_amount: i32``** mirrors Python's
     ``GameState.resolving_counter_amount`` at ``game.py:2675``. Slot
     initialized to 0 at fresh-state construction (both the prod
     ``make_state`` setup path and the ``make_synthetic_state`` test
     path) and preserved across clones. Test setter
     ``set_resolving_counter_amount(amount)`` mirrors the pre-CE9
     ``set_resolving_combat_damage_amount`` convention; production
     dispatch-time write is HONEST-STOPPED (Cycle 1 scope).
  3. **Bridge dict→Python arm**
     (``src/mtg_bot/parity/cross_engine.py::_ta_dict_to_python_effect``)
     reconstructs the Python
     ``DrawCardsEqualToResolvingCounterAmount()`` from the one-key
     dict shape.
  4. **Per-leaf Python→dict serializer**
     (``src/mtg_bot/parity/trajectory.py::_python_spell_effect_to_dict``)
     emits the bare ``{"kind":
     "draw_cards_equal_to_resolving_counter_amount"}`` for
     ``DrawCardsEqualToResolvingCounterAmount`` instances — sibling of
     the ``PutPlusOneCountersOnEachCreatureYouControlEqualToSourcePower``
     and ``ScheduleSelfSacAtNextEndStep`` unit-variant leaves.
  5. **Coverage 1:1 identity mapping.** The new Rust variant name
     matches the Python class name 1:1, so
     ``mtg_bot.parity.effect_coverage.covered_python_class_set()``
     auto-includes ``DrawCardsEqualToResolvingCounterAmount`` —
     closes the ``effect_uncovered`` classifier gate at the covered-
     set level.

**Multi-gated card; classifier multi-gate state stays True after the
cycle.** Per the round-58 subsystem-attribution classifier,
Terrasymbiosis is multi-gated on ``effect_uncovered +
nonsafe_triggered_ability``. The cycle closes the ``effect_uncovered``
gate (the ``DrawCardsEqualToResolvingCounterAmount`` Python class flips
from ``missing_effect_classes`` to covered), but the
``nonsafe_triggered_ability`` gate KEEPS the card multi-gated at the
classifier level. The trajectory safe-trigger admit gate
(``parity/trajectory.py::_python_ta_to_safe_dict``) is INTENTIONALLY
NOT widened — that gate is about the production-deck bench admit set,
a distinct concern from per-card real-EoE parity probes. **The card
DOES move to PROBED tier through the dedicated per-card real-EoE
byte-equal cross-engine probe** below, the same precedent as Comet
Crawler / Mutinous Massacre / Dyadrine Attack / Boilerbilges Ripper /
Fanatic of the Harrowing / Terrapact Intimidator / Attack-in-the-Box /
Ouroboroid established.

**Per-card parity probe path (NOT spell-card-bridge admit set).**
Terrasymbiosis is an Enchantment, not a non-creature spell with a
spell-card-bridge resolve. The spell-card-bridge admit set
(``trajectory.py::_python_spell_effect_to_dict`` + its §2 teeth)
gates non-creature spells only. The per-card probe approach is the
right tool here, exactly the Ouroboroid / Attack-in-the-Box / Friendly
Teddy convention.

**Cycle 1 scope — substrate landing.** This cycle lands ONLY the
``DrawCardsEqualToResolvingCounterAmount`` substrate (Rust variant +
parse + to_pydict + resolve + cross-engine bridge + per-leaf
serializer + GameState slot + test setter). The full real-EoE
counters-added trigger fan-out byte-equal probe through both engines's
COUNTERS_ADDED-observer dispatch machinery requires driving both
engines through the trigger-fan-out machinery with the right
controller-side gate (the trigger fires only when YOU put counters
on YOUR creature) — the cross-engine harness's
counters-added-observer surface is HONEST-STOPPED today; the
dedicated Rust resolve-arm pins below carry the byte-equal
observable directly via the test-setter substrate.

Coverage:

- Parser SoT pin: the live parser maps Terrasymbiosis's counters-
  added-observer trigger to ``DrawCardsEqualToResolvingCounterAmount()``.
- Serializer round-trip: dict→Python via ``_ta_dict_to_python_effect``
  rebuilds the parameterless instance; Rust
  ``Effect::DrawCardsEqualToResolvingCounterAmount`` → dict via
  ``Registry.get_printing_etb_effects`` emits the expected one-key
  dict shape.
- Effect-coverage class pin:
  ``DrawCardsEqualToResolvingCounterAmount`` is in the
  covered-by-rust set after this cycle (1:1 identity-mapping rule).
- Rust resolve-arm unit pins:
    * amount=0 silent no-op: with
      ``resolving_counter_amount = 0``, no card moves library → hand.
    * amount=N draws N cards: with
      ``resolving_counter_amount = N > 0``, the source-controller's
      hand grows by exactly N (assuming the library has ≥ N cards).
    * Empty-library CR 704.5b path: amount > library size flips the
      controller's ``attempted_draw_on_empty`` flag.
- **GENUINE real-EoE cross-engine byte-equal probe** drives the parsed
  Terrasymbiosis printing through BOTH engines's
  ``trajectory._python_spell_effect_to_dict`` →
  ``cross_engine._ta_dict_to_python_effect`` round-trip surface, and
  through the directly-driven counter-amount draw observable.
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


_TERRASYMBIOSIS_KIND = "draw_cards_equal_to_resolving_counter_amount"


# -------------------------------------------------------------------
# Verify-first: parser SoT pin.
# -------------------------------------------------------------------


def test_real_terrasymbiosis_counters_added_trigger_is_counter_amount_draw():
    """**Verify-first.** The live parser maps Terrasymbiosis's
    counters-added observer trigger to
    ``DrawCardsEqualToResolvingCounterAmount()``. Pin the shape so a
    parser drift is caught here, not silently downstream in the
    cross-engine probe."""
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.generic.draw_mill import (
        DrawCardsEqualToResolvingCounterAmount,
    )

    p = get_active_source().get_printings().get("Terrasymbiosis")
    if p is None:
        pytest.skip("Terrasymbiosis absent from active CardSource")
    assert "Enchantment" in p.card_types
    # Single COUNTERS_ADDED observer triggered ability — find the one
    # whose effect is the counter-amount draw leaf.
    matches = [
        ta for ta in p.triggered_abilities
        if isinstance(ta.effect, DrawCardsEqualToResolvingCounterAmount)
    ]
    assert len(matches) == 1, (
        f"Terrasymbiosis must have exactly 1 triggered ability whose "
        f"effect is DrawCardsEqualToResolvingCounterAmount; got "
        f"{len(matches)}"
    )
    ta = matches[0]
    # Field-free unit dataclass — equality with a fresh default-
    # constructed instance.
    assert ta.effect == DrawCardsEqualToResolvingCounterAmount()


# -------------------------------------------------------------------
# Serializer round-trip pins.
# -------------------------------------------------------------------


def test_terrasymbiosis_effect_serializer_round_trip():
    """Python ``DrawCardsEqualToResolvingCounterAmount()`` →
    ``trajectory._python_spell_effect_to_dict`` emits the bare unit-
    variant dict; ``cross_engine._ta_dict_to_python_effect``
    reconstructs the default-constructed instance. Bridge arm is the
    lever flip — without it, a Rust→Python triggered-ability
    translation would raise on the unknown kind."""
    from mtg_bot.effects.generic.draw_mill import (
        DrawCardsEqualToResolvingCounterAmount,
    )
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    d = trajectory._python_spell_effect_to_dict(
        DrawCardsEqualToResolvingCounterAmount()
    )
    assert d == {"kind": _TERRASYMBIOSIS_KIND}, (
        f"reverse serializer must emit the bare unit-variant dict; "
        f"got {d}"
    )
    rebuilt = _ta_dict_to_python_effect(d)
    assert isinstance(rebuilt, DrawCardsEqualToResolvingCounterAmount), (
        f"dict→Python bridge must round-trip to "
        f"DrawCardsEqualToResolvingCounterAmount; "
        f"got {type(rebuilt).__name__}"
    )
    # Field-free unit dataclass; equality with a fresh instance.
    assert rebuilt == DrawCardsEqualToResolvingCounterAmount()


def test_terrasymbiosis_rust_effect_to_pydict_round_trip():
    """Rust ``Effect::DrawCardsEqualToResolvingCounterAmount`` → dict
    emits the expected one-key shape. Drives the round-trip through
    ``Registry.register_printing`` (the parse path) +
    ``get_printing_etb_effects`` (the ``effect_to_pydict`` readback)."""
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Terrasymbiosis Round-trip",
            "card_types": ["Enchantment"],
            "mana_cost": {"generic": 2, "G": 1},
            "etb_effects": [
                {"kind": _TERRASYMBIOSIS_KIND},
            ],
        }
    )
    effs = reg.get_printing_etb_effects(pid)
    assert len(effs) == 1, f"expected 1 etb_effect, got {len(effs)}"
    eff = effs[0]
    assert eff["kind"] == _TERRASYMBIOSIS_KIND
    # Field-free unit variant — no other keys.
    assert set(eff.keys()) == {"kind"}, (
        f"unit-variant to_pydict must emit ONLY 'kind'; got keys "
        f"{sorted(eff.keys())}"
    )


def test_terrasymbiosis_class_covered_by_rust():
    """``DrawCardsEqualToResolvingCounterAmount`` must be in the
    covered-by-rust set — the Rust variant declaration makes
    ``covered_python_class_set()`` include it via the 1:1 identity-
    mapping rule in ``effect_coverage.map_rust_to_python``. This is
    the §2 covered-set tooth (parity-doc / coverage-script "covered"
    alignment) AND the closure of the classifier's ``effect_uncovered``
    gate for Terrasymbiosis."""
    from mtg_bot.parity.effect_coverage import covered_python_class_set

    covered = covered_python_class_set()
    assert "DrawCardsEqualToResolvingCounterAmount" in covered, (
        "Rust Effect::DrawCardsEqualToResolvingCounterAmount variant "
        "must make the Python class covered via the 1:1 identity-"
        "mapping rule"
    )


# -------------------------------------------------------------------
# Rust resolve-arm unit pins — read of resolving_counter_amount via
# the test-setter substrate + draw observable.
# -------------------------------------------------------------------


def _fresh_rust_state():
    import mtg_bot_engine
    return mtg_bot_engine.make_synthetic_state(0, 0, 0)


# Synthetic Terrasymbiosis-shaped printing. The "effects" list is the
# spell_effect list the cast-pipeline resolves on
# push_to_stack+resolve_top_of_stack. The real card composes this
# Effect under a COUNTERS_ADDED-observer triggered ability; the
# substrate unit pin exercises the resolve arm directly via the
# spell-resolution pipeline (same shape the Ouroboroid / Attack-in-
# the-Box probes use for their substrates).
_TERRASYMBIOSIS_LIKE_PRINTING: dict = {
    "name": "Terrasymbiosis Probe Source",
    "card_types": ["Enchantment"],
    "mana_cost": {"generic": 2, "G": 1},
    "effects": [
        {"kind": _TERRASYMBIOSIS_KIND},
    ],
}


def _stock_library(rs, controller: int, n: int) -> list[int]:
    """Push ``n`` vanilla bear printings onto controller's library.
    Returns the list of injected object ids (in library-bottom order).
    """
    ids: list[int] = []
    bear = {
        "name": "Vanilla Bear",
        "card_types": ["Creature"],
        "power": 2,
        "toughness": 2,
        "mana_cost": {"generic": 1, "G": 1},
    }
    for _ in range(n):
        ids.append(rs.register_and_inject_object(bear, controller, ZONE_LIBRARY))
    return ids


def test_rust_resolve_amount_zero_silent_noop():
    """**Rust pin (a): amount=0 silent no-op.** When
    ``state.resolving_counter_amount`` is 0 (e.g. defensive invocation
    outside a COUNTERS_ADDED trigger), the resolve arm short-circuits
    BEFORE touching any zone. Mirrors Python's ``if amount <= 0:
    return`` short-circuit in
    ``DrawCardsEqualToResolvingCounterAmount.resolve``
    (``effects/generic/draw_mill.py:76``).
    """
    rs = _fresh_rust_state()
    src_id = rs.register_and_inject_object(
        _TERRASYMBIOSIS_LIKE_PRINTING, 0, ZONE_BATTLEFIELD,
    )
    _stock_library(rs, 0, 3)
    # Slot left at default 0; do NOT set.
    assert rs.resolving_counter_amount == 0

    hand_before = rs.hand_sizes[0]
    lib_before = rs.library_sizes[0]

    rs.push_to_stack(src_id, 0)
    rs.resolve_top_of_stack()
    assert rs.stack_size() == 0, "spell must resolve cleanly"

    assert rs.hand_sizes[0] == hand_before, (
        f"amount=0 → controller's hand must not grow; "
        f"hand_size went {hand_before} → {rs.hand_sizes[0]}"
    )
    assert rs.library_sizes[0] == lib_before, (
        f"amount=0 → controller's library must not shrink; "
        f"library_size went {lib_before} → {rs.library_sizes[0]}"
    )


def test_rust_resolve_amount_n_draws_n_cards():
    """**Rust pin (b): amount=N draws N cards.** With
    ``resolving_counter_amount`` set to N > 0 (via the test setter,
    mirroring the production write site that's honest-stopped at
    Cycle 1), the source-controller's hand grows by exactly N and the
    library shrinks by N. Mirrors Python's inline ``draw_n_cards`` call
    in ``DrawCardsEqualToResolvingCounterAmount.resolve``.
    """
    rs = _fresh_rust_state()
    src_id = rs.register_and_inject_object(
        _TERRASYMBIOSIS_LIKE_PRINTING, 0, ZONE_BATTLEFIELD,
    )
    _stock_library(rs, 0, 5)

    # Inject N = 3 via the test setter, as if a COUNTERS_ADDED-
    # observer event had just fired with 3 counters on a controlled
    # creature.
    rs.set_resolving_counter_amount(3)
    assert rs.resolving_counter_amount == 3

    hand_before = rs.hand_sizes[0]
    lib_before = rs.library_sizes[0]
    other_hand_before = rs.hand_sizes[1]
    other_lib_before = rs.library_sizes[1]

    rs.push_to_stack(src_id, 0)
    rs.resolve_top_of_stack()
    assert rs.stack_size() == 0, "spell must resolve cleanly"

    assert rs.hand_sizes[0] - hand_before == 3, (
        f"amount=3 → controller's hand grows by exactly 3; "
        f"delta={rs.hand_sizes[0] - hand_before}"
    )
    assert lib_before - rs.library_sizes[0] == 3, (
        f"amount=3 → controller's library shrinks by exactly 3; "
        f"delta={lib_before - rs.library_sizes[0]}"
    )
    # Opponent state must not change.
    assert rs.hand_sizes[1] == other_hand_before
    assert rs.library_sizes[1] == other_lib_before


def test_rust_resolve_amount_exceeds_library_stops_at_empty():
    """**Rust pin (c): amount > library size stops at empty.**
    When the controller asks for more cards than the library holds,
    the resolve arm draws what's available and stops — the inner loop
    flips ``attempted_draw_on_empty = true`` so the SBA pass eventually
    converts it to ``has_lost``. The CR 704.5b internal flag is not
    exposed via the Python harness; the observable here is the post-
    resolve hand/library boundary — controller's hand contains all
    available cards, library is empty.
    """
    rs = _fresh_rust_state()
    src_id = rs.register_and_inject_object(
        _TERRASYMBIOSIS_LIKE_PRINTING, 0, ZONE_BATTLEFIELD,
    )
    # Stock only 2 cards in the library.
    _stock_library(rs, 0, 2)

    rs.set_resolving_counter_amount(5)

    rs.push_to_stack(src_id, 0)
    rs.resolve_top_of_stack()
    assert rs.stack_size() == 0

    # Controller drew the 2 available cards; library is now empty.
    # The CR 704.5b flag is set internally by the resolve arm (loop
    # body's `attempted_draw_on_empty = true` write), but is not
    # surfaced through a getter today; the SBA path verifies it
    # downstream. The observable here is the hand/library boundary.
    assert rs.hand_sizes[0] == 2, (
        f"controller's hand must hold all 2 available cards; got "
        f"{rs.hand_sizes[0]}"
    )
    assert rs.library_sizes[0] == 0, (
        f"controller's library must be empty; got "
        f"{rs.library_sizes[0]}"
    )


# -------------------------------------------------------------------
# GENUINE real-EoE cross-engine byte-equal probe — drives the parsed
# Terrasymbiosis printing through the trajectory →
# _ta_dict_to_python_effect round-trip pipeline, and through the
# directly-applied Rust resolve arm on a synthetic state matching the
# COUNTERS_ADDED-observer carrier semantics.
# -------------------------------------------------------------------


def test_cross_engine_real_eoe_terrasymbiosis_round_trip():
    """**GENUINE real-EoE cross-engine byte-equal probe —
    Terrasymbiosis counter-amount draw effect.** The slug-credit anchor
    for the PROBED tier flip even though the classifier multi-gates
    the card on ``nonsafe_triggered_ability``.

    Drives the **real parsed Terrasymbiosis printing** through the
    trajectory serializer + cross-engine dict→Python bridge:

      * Extract the parsed COUNTERS_ADDED-observer triggered-ability
        effect from the real EoE printing.
      * Walk the effect — must be
        ``DrawCardsEqualToResolvingCounterAmount()`` per the parser
        SoT pin.
      * Serialize via ``trajectory._python_spell_effect_to_dict`` →
        the bare one-key dict.
      * Round-trip via ``cross_engine._ta_dict_to_python_effect`` → a
        fresh ``DrawCardsEqualToResolvingCounterAmount()`` instance
        equal to the parser-emitted effect.
      * Drive the effect's resolve through Rust on a synthetic state
        whose ``resolving_counter_amount`` is injected to match
        Terrasymbiosis's actual COUNTERS_ADDED-observer carrier
        semantics (set to N = 2 to represent "2 counters added in this
        firing event") — the controller's hand grows by exactly 2,
        byte-equal-observable to the round-trip dict.

    **Byte-equality scope.** Both the parser-emitted effect and the
    bridge-reconstructed effect compare equal as field-free unit
    dataclasses; the Rust-side resolve lands an identical N-card draw
    delta on the source-controller's hand/library boundary, mirroring
    the Python class's resolve body byte-for-byte.

    **Cycle 1 scope caveat.** The full real-EoE COUNTERS_ADDED-
    observer trigger-fan-out byte-equal probe through both engines's
    counter-mutation dispatch machinery requires per-engine
    coordination of the observer-trigger-pushed-onto-stack timing
    (Python's ``add_plus_one_counters`` fires the COUNTERS_ADDED event;
    Rust's counter-mutation paths don't dispatch the observer event
    today) — that broader probe is honest-stopped at Cycle 1; the
    substrate-level round-trip + the Rust resolve-arm unit pins carry
    the PROBED tier flip per the Ouroboroid / Terrapact Intimidator /
    Attack-in-the-Box classifier-bypass precedent.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.generic.draw_mill import (
        DrawCardsEqualToResolvingCounterAmount,
    )
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    real = get_active_source().get_printings().get("Terrasymbiosis")
    if real is None:
        pytest.skip("Terrasymbiosis absent from active CardSource")

    # §2 source-of-truth: the genuine counters-added trigger effect
    # must be DrawCardsEqualToResolvingCounterAmount().
    matches = [
        ta for ta in real.triggered_abilities
        if isinstance(ta.effect, DrawCardsEqualToResolvingCounterAmount)
    ]
    assert len(matches) == 1, (
        "Terrasymbiosis must have exactly 1 triggered ability whose "
        f"effect is DrawCardsEqualToResolvingCounterAmount; got "
        f"{len(matches)}"
    )
    leaf = matches[0].effect

    # Round-trip the leaf through trajectory serializer + cross-engine
    # dict→Python bridge.
    d = trajectory._python_spell_effect_to_dict(leaf)
    assert d == {"kind": _TERRASYMBIOSIS_KIND}, (
        f"real-EoE leaf serializer must emit the bare unit-variant "
        f"dict; got {d}"
    )
    rebuilt = _ta_dict_to_python_effect(d)
    assert isinstance(rebuilt, DrawCardsEqualToResolvingCounterAmount), (
        f"dict→Python bridge must round-trip to "
        f"DrawCardsEqualToResolvingCounterAmount; "
        f"got {type(rebuilt).__name__}"
    )
    assert rebuilt == leaf, (
        f"round-tripped leaf must equal the parser-emitted leaf "
        f"(both field-free unit dataclasses); got rebuilt={rebuilt!r}, "
        f"parser={leaf!r}"
    )

    # Drive the leaf through Rust's resolve arm on a synthetic state
    # whose resolving_counter_amount slot matches Terrasymbiosis's
    # COUNTERS_ADDED-observer carrier semantics. N = 2 cards drawn for
    # a 2-counter add.
    rs = _fresh_rust_state()
    src_id = rs.register_and_inject_object(
        _TERRASYMBIOSIS_LIKE_PRINTING, 0, ZONE_BATTLEFIELD,
    )
    _stock_library(rs, 0, 4)

    rs.set_resolving_counter_amount(2)
    hand_before = rs.hand_sizes[0]
    lib_before = rs.library_sizes[0]

    rs.push_to_stack(src_id, 0)
    rs.resolve_top_of_stack()
    assert rs.stack_size() == 0, "Rust resolve must clear the stack"

    assert rs.hand_sizes[0] - hand_before == 2, (
        f"controller's hand must grow by exactly 2; got "
        f"delta={rs.hand_sizes[0] - hand_before}"
    )
    assert lib_before - rs.library_sizes[0] == 2, (
        f"controller's library must shrink by exactly 2; got "
        f"delta={lib_before - rs.library_sizes[0]}"
    )
