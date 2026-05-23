"""**Warping Wail Cycle 2 substrate (2026-05-22).**

Tests for the new ``Effect::CounterTargetSpell { filter_types:
Vec<String> }`` Rust variant schema widening + matching cross-engine
bridge arm + reverse-serializer leaf.

This is a **substrate-only closure** — the cycle widens the Rust
``Effect::CounterTargetSpell`` schema to carry ``filter_types``
mirroring Python's ``CounterTargetSpell.filter_types: frozenset[str]``.
Warping Wail itself stays DECLINED at the spell-card-bridge admit gate
because:

  - **Mode 1 (Cycle 1a, landed)**: ``ExileTargetCreatureWithPower
    OrToughnessAtMost(max_value=1)`` — landed in
    ``feature/warping-wail-substrate-cycle-1a``.
  - **Mode 2 (this cycle)**: ``CounterTargetSpell.filter_types =
    frozenset({"Sorcery"})`` — landed here.
  - **Mode 3 (future Cycle 3)**: token-AA bridge widen — Warping
    Wail's mint-a-1/1-colorless-creature-token-with-mana-ability
    mode still needs creature-token-with-activated-mana-ability
    bridge support.
  - **Cycle 4**: admit-gate widen for the ``(0, 1)``+
    ``or_both=False`` Phase-6 modal shape, per-mode binders, +
    cross-engine probe.

Real-EoE consumers unblocked by this Cycle 2 schema widening (per the
verify-first walk):

  - **Divert Disaster** — ``CounterTargetSpell(filter_types=frozenset(
    {"Instant", "Sorcery"}))``. Already in EoE pool.
  - **Unravel** — ``CounterTargetSpell(filter_types=frozenset(
    {"Instant", "Sorcery"}))``. Already in EoE pool.
  - **Warping Wail mode 2** — ``CounterTargetSpell(filter_types=
    frozenset({"Sorcery"}))``. Not yet flipping (3-mode card; Mode 3
    still needs token-AA + admit-gate widen).

See ``docs/SEARCH_LIMITATIONS.md`` "Warping Wail Cycle 2 substrate
LANDED" block for the 4-cycle decomposition rationale.

**Test plan:**

  - Bridge dict→Python: round-trip for empty + nonempty filter_types
    (and missing field → empty frozenset).
  - Bridge dict→Python: rejects non-string / empty-string entries
    loudly.
  - Reverse-serializer round-trip: ``_python_spell_effect_to_dict`` +
    ``_ta_dict_to_python_effect`` byte-equal for both empty and
    nonempty filter_types.
  - Rust parser pins:
      * variant parses with non-empty filter_types;
      * variant parses with empty filter_types (back-compat with
        bare unit-variant shape);
      * variant parses with omitted filter_types (back-compat);
      * parser rejects non-list filter_types loudly;
      * parser rejects empty-string entries loudly.
  - Rust to_pydict round-trip:
      * non-empty filter_types emits the field;
      * empty filter_types omits the field (byte-equal to pre-
        Cycle-2 round-trip).
  - Rust resolve arm:
      * non-empty filter_types counters a matching-type spell;
      * non-empty filter_types DECLINES a non-matching-type spell
        (silent fizzle);
      * empty filter_types counters any spell (back-compat);
      * filter_types interacts cleanly with the Phase-2
        uncounterability gates (a Sorcery-filter still skips an
        uncounterable Sorcery).
"""

from __future__ import annotations

import importlib.util

import pytest


def _require_engine():
    if importlib.util.find_spec("mtg_bot_engine") is None:
        pytest.skip("mtg_bot_engine PyO3 extension not installed")


_ZONE_BATTLEFIELD = 2
_ZONE_GRAVEYARD = 3


# ---------------------------------------------------------------------------
# Python class SoT verify-first
# ---------------------------------------------------------------------------


def test_python_class_carries_filter_types_field():
    """**Parser source-of-truth pin.** The Python ``CounterTargetSpell``
    class carries ``filter_types: frozenset[str]`` defaulting to the
    empty frozenset. Cycle 2 widens the Rust schema to mirror this
    field; the Python side is the source of truth."""
    from mtg_bot.effects.generic.stack_control import CounterTargetSpell

    eff_default = CounterTargetSpell()
    assert eff_default.filter_types == frozenset()

    eff_sorcery = CounterTargetSpell(filter_types=frozenset({"Sorcery"}))
    assert eff_sorcery.filter_types == frozenset({"Sorcery"})

    eff_disaster = CounterTargetSpell(
        filter_types=frozenset({"Instant", "Sorcery"})
    )
    assert eff_disaster.filter_types == frozenset({"Instant", "Sorcery"})


# ---------------------------------------------------------------------------
# Bridge dict → Python (cross_engine arm)
# ---------------------------------------------------------------------------


def test_bridge_threads_filter_types_warping_wail_mode2():
    """Warping Wail mode 2's ``frozenset({"Sorcery"})`` round-trips
    dict → Python correctly."""
    from mtg_bot.effects.generic.stack_control import CounterTargetSpell
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {"kind": "counter_target_spell", "filter_types": ["Sorcery"]}
    )
    assert isinstance(e, CounterTargetSpell)
    assert e.filter_types == frozenset({"Sorcery"})


def test_bridge_threads_filter_types_divert_disaster():
    """Divert Disaster / Unravel's ``frozenset({"Instant", "Sorcery"})``
    round-trips dict → Python correctly."""
    from mtg_bot.effects.generic.stack_control import CounterTargetSpell
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {
            "kind": "counter_target_spell",
            "filter_types": ["Instant", "Sorcery"],
        }
    )
    assert isinstance(e, CounterTargetSpell)
    assert e.filter_types == frozenset({"Instant", "Sorcery"})


def test_bridge_rejects_non_string_filter_types_entry():
    """The bridge mirrors Rust's parse-arm contract: each
    ``filter_types`` entry must be a non-empty string. Non-string
    surfaces as ValueError."""
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    with pytest.raises(ValueError, match="non-empty strings"):
        _ta_dict_to_python_effect(
            {"kind": "counter_target_spell", "filter_types": [42]}
        )


def test_bridge_rejects_empty_string_filter_types_entry():
    """The bridge rejects empty-string entries loudly — mirrors
    Rust's parse-arm contract."""
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    with pytest.raises(ValueError, match="non-empty strings"):
        _ta_dict_to_python_effect(
            {"kind": "counter_target_spell", "filter_types": [""]}
        )


# ---------------------------------------------------------------------------
# Reverse-serializer round-trip (_python_spell_effect_to_dict)
# ---------------------------------------------------------------------------


def test_python_serializer_round_trip_empty_filter_types():
    """Empty filter_types round-trips to bare ``{"kind":
    "counter_target_spell"}`` (back-compat with every pre-Cycle-2
    construction). Reverse + bridge re-construct an equal
    ``CounterTargetSpell()`` instance."""
    from mtg_bot.effects.generic.stack_control import CounterTargetSpell
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect
    from mtg_bot.parity.trajectory import _python_spell_effect_to_dict

    eff = CounterTargetSpell()
    d = _python_spell_effect_to_dict(eff)
    assert d == {"kind": "counter_target_spell"}
    back = _ta_dict_to_python_effect(d)
    assert isinstance(back, CounterTargetSpell)
    assert back.filter_types == frozenset()
    assert back == eff


def test_python_serializer_round_trip_warping_wail_mode2():
    """Warping Wail mode 2's ``frozenset({"Sorcery"})`` round-trips
    byte-equal through ``_python_spell_effect_to_dict`` →
    ``_ta_dict_to_python_effect``."""
    from mtg_bot.effects.generic.stack_control import CounterTargetSpell
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect
    from mtg_bot.parity.trajectory import _python_spell_effect_to_dict

    eff = CounterTargetSpell(filter_types=frozenset({"Sorcery"}))
    d = _python_spell_effect_to_dict(eff)
    assert d == {
        "kind": "counter_target_spell",
        "filter_types": ["Sorcery"],
    }
    back = _ta_dict_to_python_effect(d)
    assert isinstance(back, CounterTargetSpell)
    assert back.filter_types == frozenset({"Sorcery"})
    assert back == eff


def test_python_serializer_round_trip_divert_disaster_sorted():
    """Divert Disaster's ``frozenset({"Instant", "Sorcery"})``
    serializes to a SORTED list (frozenset iteration order is
    unstable — sort for deterministic round-trip). Bridge re-
    constructs the same frozenset; Python equality is order-
    insensitive."""
    from mtg_bot.effects.generic.stack_control import CounterTargetSpell
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect
    from mtg_bot.parity.trajectory import _python_spell_effect_to_dict

    eff = CounterTargetSpell(
        filter_types=frozenset({"Instant", "Sorcery"})
    )
    d = _python_spell_effect_to_dict(eff)
    # Sorted: ["Instant", "Sorcery"] — deterministic.
    assert d == {
        "kind": "counter_target_spell",
        "filter_types": ["Instant", "Sorcery"],
    }
    back = _ta_dict_to_python_effect(d)
    assert back == eff


def test_python_serializer_bails_on_empty_string_entry():
    """Defensive: if a CounterTargetSpell somehow carries an empty
    string in filter_types, the serializer bails (returns None)
    rather than emitting a dict the Rust parser would reject."""
    from mtg_bot.effects.generic.stack_control import CounterTargetSpell
    from mtg_bot.parity.trajectory import _python_spell_effect_to_dict

    eff = CounterTargetSpell(filter_types=frozenset({""}))
    assert _python_spell_effect_to_dict(eff) is None


# ---------------------------------------------------------------------------
# Rust unit pins — parse + to_pydict
# ---------------------------------------------------------------------------


def test_rust_variant_parses_with_filter_types():
    """The Rust ``Effect::CounterTargetSpell { filter_types }``
    variant parses with the new ``filter_types`` list-of-strings
    field."""
    _require_engine()
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Test Sorcery Counter",
            "card_types": ["Instant"],
            "mana_cost": {"U": 1},
            "effects": [
                {
                    "kind": "counter_target_spell",
                    "filter_types": ["Sorcery"],
                }
            ],
        }
    )
    effects = [dict(e) for e in reg.get_printing_effects(pid)]
    assert effects[0] == {
        "kind": "counter_target_spell",
        "filter_types": ["Sorcery"],
    }


def test_rust_variant_parses_with_omitted_filter_types_backcompat():
    """Back-compat: omitting ``filter_types`` parses to the empty-
    Vec "any spell" shape — byte-identical to every pre-Cycle-2
    round-trip."""
    _require_engine()
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Test Bare Counter",
            "card_types": ["Instant"],
            "mana_cost": {"U": 1},
            "effects": [{"kind": "counter_target_spell"}],
        }
    )
    effects = [dict(e) for e in reg.get_printing_effects(pid)]
    # Bare round-trip — no filter_types key emitted.
    assert effects[0] == {"kind": "counter_target_spell"}


def test_rust_variant_parses_with_empty_filter_types():
    """Empty list parses to the empty-Vec shape, byte-equivalent to
    the omitted case."""
    _require_engine()
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Test Empty Filter Counter",
            "card_types": ["Instant"],
            "mana_cost": {"U": 1},
            "effects": [
                {
                    "kind": "counter_target_spell",
                    "filter_types": [],
                }
            ],
        }
    )
    effects = [dict(e) for e in reg.get_printing_effects(pid)]
    # Empty filter_types serializes back to the bare unit-variant.
    assert effects[0] == {"kind": "counter_target_spell"}


def test_rust_variant_rejects_non_list_filter_types():
    """Non-list filter_types is rejected at parse time loudly."""
    _require_engine()
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    with pytest.raises(Exception):
        reg.register_printing(
            {
                "name": "Test Bad Filter",
                "card_types": ["Instant"],
                "mana_cost": {"U": 1},
                "effects": [
                    {
                        "kind": "counter_target_spell",
                        "filter_types": "Sorcery",  # str, not list
                    }
                ],
            }
        )


def test_rust_variant_rejects_empty_string_entry():
    """Empty-string entries are rejected at parse time loudly."""
    _require_engine()
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    with pytest.raises(Exception):
        reg.register_printing(
            {
                "name": "Test Empty Str Filter",
                "card_types": ["Instant"],
                "mana_cost": {"U": 1},
                "effects": [
                    {
                        "kind": "counter_target_spell",
                        "filter_types": [""],
                    }
                ],
            }
        )


# ---------------------------------------------------------------------------
# Rust resolve arm — filter_types gate
# ---------------------------------------------------------------------------


def test_rust_resolve_filter_matches_counters_sorcery():
    """``filter_types=["Sorcery"]`` counters a Sorcery on the stack."""
    _require_engine()
    import mtg_bot_engine

    state = mtg_bot_engine.make_synthetic_state(0, 0, 0)
    # Push a Sorcery on the stack (controlled by P1, the opponent).
    sorcery_dict = {
        "name": "Test Sorcery",
        "mana_cost": {"generic": 1, "R": 1},
        "card_types": ["Sorcery"],
        "effects": [{"kind": "draw_cards", "count": 1}],
    }
    sorcery_id = state.register_and_inject_stack_spell(sorcery_dict, 1)
    # counter_spell primitive is the round-7 primitive; the new
    # filter_types gate is exercised via the Effect-resolve path
    # through register_and_inject_stack_spell + a counter spell
    # ALSO on the stack. We test the primitive's counter behavior
    # directly with the same effect logic via the Effect path:
    # push our own counterspell on top.
    counter_dict = {
        "name": "Test Sorcery Counter",
        "mana_cost": {"U": 2},
        "card_types": ["Instant"],
        "effects": [
            {
                "kind": "counter_target_spell",
                "filter_types": ["Sorcery"],
            }
        ],
    }
    state.register_and_inject_stack_spell(counter_dict, 0)
    # Resolve top of stack (our counterspell).
    state.resolve_top_of_stack()
    # The Sorcery should have been countered → moved to its
    # controller's graveyard (player 1's graveyard).
    stack_obj_ids = [
        item["source_obj_id"] for item in state.dump_stack()
    ] if hasattr(state, "dump_stack") else []
    # Use find_object_zone to confirm the spell left the stack.
    assert state.find_object_zone(sorcery_id) == _ZONE_GRAVEYARD, (
        "Sorcery (matching filter_types) must be countered → "
        f"graveyard; got zone={state.find_object_zone(sorcery_id)}"
    )


def test_rust_resolve_filter_declines_instant_when_filter_is_sorcery():
    """``filter_types=["Sorcery"]`` does NOT counter an Instant on
    the stack — silent fizzle when no admissible target."""
    _require_engine()
    import mtg_bot_engine

    state = mtg_bot_engine.make_synthetic_state(0, 0, 0)
    instant_dict = {
        "name": "Test Instant",
        "mana_cost": {"R": 1},
        "card_types": ["Instant"],
        "effects": [{"kind": "draw_cards", "count": 1}],
    }
    instant_id = state.register_and_inject_stack_spell(instant_dict, 1)
    counter_dict = {
        "name": "Test Sorcery-Only Counter",
        "mana_cost": {"U": 2},
        "card_types": ["Instant"],
        "effects": [
            {
                "kind": "counter_target_spell",
                "filter_types": ["Sorcery"],
            }
        ],
    }
    state.register_and_inject_stack_spell(counter_dict, 0)
    state.resolve_top_of_stack()
    # The Instant should still be on the stack (silent fizzle —
    # filter_types didn't match). find_object_zone returns the
    # ZONE_STACK constant for stack residents.
    # ZONE_STACK = 4 per the Rust constants.
    ZONE_STACK = 4
    assert state.find_object_zone(instant_id) == ZONE_STACK, (
        "Instant (not matching filter_types=['Sorcery']) must NOT "
        "be countered; expected stack zone, got "
        f"{state.find_object_zone(instant_id)}"
    )


def test_rust_resolve_filter_matches_either_in_disjunction():
    """``filter_types=["Instant", "Sorcery"]`` (Divert Disaster /
    Unravel shape) counters BOTH an Instant target and a Sorcery
    target — disjunctive intersection."""
    _require_engine()
    import mtg_bot_engine

    # Test the Sorcery leg.
    state = mtg_bot_engine.make_synthetic_state(0, 0, 0)
    sorcery_dict = {
        "name": "Test Sorcery",
        "mana_cost": {"generic": 1, "R": 1},
        "card_types": ["Sorcery"],
    }
    sorcery_id = state.register_and_inject_stack_spell(sorcery_dict, 1)
    counter_dict = {
        "name": "Test Divert Disaster",
        "mana_cost": {"generic": 1, "U": 1},
        "card_types": ["Instant"],
        "effects": [
            {
                "kind": "counter_target_spell",
                "filter_types": ["Instant", "Sorcery"],
            }
        ],
    }
    state.register_and_inject_stack_spell(counter_dict, 0)
    state.resolve_top_of_stack()
    assert state.find_object_zone(sorcery_id) == _ZONE_GRAVEYARD, (
        "Sorcery (matching disjunctive filter) must be countered"
    )

    # Test the Instant leg (fresh state).
    state2 = mtg_bot_engine.make_synthetic_state(0, 0, 0)
    instant_dict = {
        "name": "Test Instant",
        "mana_cost": {"R": 1},
        "card_types": ["Instant"],
    }
    instant_id = state2.register_and_inject_stack_spell(instant_dict, 1)
    state2.register_and_inject_stack_spell(counter_dict, 0)
    state2.resolve_top_of_stack()
    assert state2.find_object_zone(instant_id) == _ZONE_GRAVEYARD, (
        "Instant (matching disjunctive filter) must be countered"
    )


def test_rust_resolve_empty_filter_types_counters_any_spell():
    """Empty filter_types ("any spell" — back-compat shape) counters
    ANY spell, including a Creature spell. Byte-identical to the
    pre-Cycle-2 behavior."""
    _require_engine()
    import mtg_bot_engine

    state = mtg_bot_engine.make_synthetic_state(0, 0, 0)
    creature_dict = {
        "name": "Test Creature",
        "mana_cost": {"generic": 1, "G": 1},
        "card_types": ["Creature"],
        "power": 2,
        "toughness": 2,
    }
    creature_id = state.register_and_inject_stack_spell(creature_dict, 1)
    counter_dict = {
        "name": "Test Any-Spell Counter",
        "mana_cost": {"generic": 1, "U": 1},
        "card_types": ["Instant"],
        "effects": [{"kind": "counter_target_spell"}],
    }
    state.register_and_inject_stack_spell(counter_dict, 0)
    state.resolve_top_of_stack()
    assert state.find_object_zone(creature_id) == _ZONE_GRAVEYARD, (
        "Creature (empty filter_types = any) must be countered"
    )


def test_rust_resolve_filter_skips_uncounterable_match():
    """Cycle-2 filter_types gate composes with the Phase-2
    uncounterability gates: a Sorcery that ALSO carries
    ``spell_is_uncounterable=true`` is skipped — both gates fire,
    silent fizzle when no other admissible target exists."""
    _require_engine()
    import mtg_bot_engine

    state = mtg_bot_engine.make_synthetic_state(0, 0, 0)
    uncounterable_sorcery = {
        "name": "Test Uncounterable Sorcery",
        "mana_cost": {"generic": 1, "R": 1},
        "card_types": ["Sorcery"],
        "spell_is_uncounterable": True,
    }
    sorcery_id = state.register_and_inject_stack_spell(
        uncounterable_sorcery, 1,
    )
    counter_dict = {
        "name": "Test Sorcery Counter",
        "mana_cost": {"U": 2},
        "card_types": ["Instant"],
        "effects": [
            {
                "kind": "counter_target_spell",
                "filter_types": ["Sorcery"],
            }
        ],
    }
    state.register_and_inject_stack_spell(counter_dict, 0)
    state.resolve_top_of_stack()
    # Sorcery still on the stack — uncounterability gate fired,
    # filter_types matched but the uncounterability check fizzled
    # the counter.
    ZONE_STACK = 4
    assert state.find_object_zone(sorcery_id) == ZONE_STACK, (
        "Uncounterable Sorcery must stay on the stack despite "
        "matching filter_types"
    )
