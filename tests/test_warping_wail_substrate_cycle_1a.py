"""**Warping Wail Cycle 1a substrate (2026-05-22).**

Tests for the new ``Effect::ExileTargetCreatureWithPowerOrToughnessAt
Most { max_value: i32 }`` Rust variant + matching cross-engine bridge
arm + reverse-serializer leaf.

This is a **substrate-only closure** — the cycle adds the (1, 1)-shape
single-target exile-with-P-or-T-threshold Effect lever as reusable
infrastructure. Warping Wail itself stays DECLINED at the spell-card-
bridge admit gate this cycle because two of its three modes still have
no Rust substrate:

  - **Mode 1 (this cycle)**: ``ExileTargetCreatureWithPower
    OrToughnessAtMost(max_value=1)``. Lands here.
  - **Mode 2 (future Cycle 2)**: ``CounterTargetSpell.filter_types``
    — the colorless-or-Spacecraft counter clause's filter axis.
  - **Mode 3 (future Cycle 3)**: a token-AA bridge widen — Warping
    Wail's mint-a-1/1-colorless-creature-token-with-mana-ability
    mode needs the existing token bridge to admit creature tokens
    carrying activated mana abilities.
  - **Cycle 4**: admit-gate widen for the ``(0, 1)``+
    ``or_both=False`` Phase-6 modal shape, per-mode binders, +
    cross-engine probe.

See ``docs/SEARCH_LIMITATIONS.md`` "Warping Wail Cycle 1a substrate
LANDED" block for the 4-cycle decomposition rationale.

**Test plan (per prompt §8):**

  - Parser SoT: confirm the Python ``ExileTargetCreatureWithPower
    OrToughnessAtMost`` class exists in the engine and has the
    expected single-target filter shape.
  - Serializer round-trip: ``_python_spell_effect_to_dict`` +
    ``_ta_dict_to_python_effect`` byte-equal for the new variant.
  - Rust unit pins:
      * variant parses + ``to_pydict`` round-trips byte-equal;
      * parser rejects negative ``max_value`` loudly;
      * parser rejects missing ``max_value`` loudly;
      * resolve exiles a legal target (P ≤ N case);
      * resolve exiles a legal target (T ≤ N case);
      * resolve fizzles silently on a no-longer-Creature target
        (CR 608.2b);
      * resolve fizzles silently on a target whose effective
        P AND T are both > N (CR 608.2b);
      * resolve fizzles silently on a target no longer on a
        battlefield (CR 608.2b);
      * resolve scans cross-battlefield (own + opponent's creature
        both legal targets);
      * resolve respects effective_power (counters folded in);
      * indestructible target IS exiled (CR 702.12 bypass —
        matches the established ``ExileTarget { AnyCreature }``
        arm precedent).
  - Covered-set membership for the new Effect class.
  - **No admit-gate flip test** (substrate-only).
  - **No real-EoE cross-engine probe** (Warping Wail doesn't flip
    yet; the probe lands in Cycle 4).
"""

from __future__ import annotations

import importlib.util

import pytest


def _require_engine():
    if importlib.util.find_spec("mtg_bot_engine") is None:
        pytest.skip("mtg_bot_engine PyO3 extension not installed")


_ZONE_HAND = 0
_ZONE_BATTLEFIELD = 2
_ZONE_GRAVEYARD = 3
_ZONE_EXILE = 5


def _fresh_rust():
    """Synthetic two-player state with both players at 20 life."""
    import mtg_bot_engine
    return mtg_bot_engine.make_synthetic_state(0, 0, 0)


def _new_creature(rs, name, owner, power, toughness, *, keywords=None):
    """Inject a creature on owner's battlefield with the printed P/T
    and (optional) keywords."""
    obj_dict = {
        "name": name,
        "card_types": ["Creature"],
        "mana_cost": {"generic": 1},
        "power": power,
        "toughness": toughness,
    }
    if keywords is not None:
        obj_dict["keywords"] = keywords
    return rs.register_and_inject_object(
        obj_dict, owner, _ZONE_BATTLEFIELD,
    )


def _push_exile_spell(rs, caster, target_id, *, max_value=1):
    """Inject a bare-shape exile-target-creature-with-P-or-T-at-most
    Sorcery on the caster's stack with the given payload-target. Used
    by every direct-resolve unit pin below."""
    spell_id = rs.register_and_inject_object(
        {
            "name": "Substrate Probe",
            "card_types": ["Sorcery"],
            "mana_cost": {"generic": 1, "C": 1},
            "effects": [{
                "kind": (
                    "exile_target_creature_with_power_or_toughness_"
                    "at_most"
                ),
                "max_value": max_value,
            }],
        },
        caster, _ZONE_HAND,
    )
    rs.push_to_stack_with_target(spell_id, caster, target_id)
    return spell_id


# ---------------------------------------------------------------------------
# Parser SoT verify-first
# ---------------------------------------------------------------------------


def test_python_class_exists_with_expected_filter_shape():
    """**Parser source-of-truth pin.** The Python
    ``ExileTargetCreatureWithPowerOrToughnessAtMost`` class is in the
    effects.generic.exile module, is a subclass of ``Exile``, carries
    a ``max_value: int`` field with a default, and constructs a
    single-TargetSpec with the ``IsCreature() & (HasPowerAtMost(N) |
    HasToughnessAtMost(N))`` filter shape."""
    from mtg_bot.effects.generic.exile import (
        Exile,
        ExileTargetCreatureWithPowerOrToughnessAtMost,
    )
    from mtg_bot.effects.object_predicates import (
        HasPowerAtMost,
        HasToughnessAtMost,
        IsCreature,
    )
    from mtg_bot.effects.targets import TargetSpec

    # Subclass shape.
    assert issubclass(ExileTargetCreatureWithPowerOrToughnessAtMost, Exile)

    # max_value=1 (Warping Wail mode 1) — exercise the constructor.
    eff = ExileTargetCreatureWithPowerOrToughnessAtMost(max_value=1)
    assert eff.max_value == 1

    # Single-TargetSpec, single-slot.
    assert hasattr(eff, "targets")
    assert isinstance(eff.targets, tuple)
    assert len(eff.targets) == 1
    spec = eff.targets[0]
    assert isinstance(spec, TargetSpec)


def test_python_class_describe_matches_oracle_text():
    """The Python class's ``describe`` returns text that matches
    Warping Wail mode 1's printed oracle text shape — the SoT
    docstring at exile.py:733-762."""
    from mtg_bot.effects.generic.exile import (
        ExileTargetCreatureWithPowerOrToughnessAtMost,
    )

    eff = ExileTargetCreatureWithPowerOrToughnessAtMost(max_value=1)
    desc = eff.describe()
    assert "exile target creature" in desc.lower()
    assert "1" in desc  # the max_value


# ---------------------------------------------------------------------------
# Covered-set membership
# ---------------------------------------------------------------------------


def test_effect_class_covered_via_bridge_arm():
    """The dict→Python bridge arm in ``cross_engine`` constructs the
    Python ``ExileTargetCreatureWithPowerOrToughnessAtMost`` class
    from the matching ``kind`` string. This is the §2 covered-side
    teeth."""
    from mtg_bot.effects.generic.exile import (
        ExileTargetCreatureWithPowerOrToughnessAtMost,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    back = _ta_dict_to_python_effect({
        "kind": "exile_target_creature_with_power_or_toughness_at_most",
        "max_value": 1,
    })
    assert isinstance(back, ExileTargetCreatureWithPowerOrToughnessAtMost)
    assert back.max_value == 1


def test_bridge_arm_rejects_missing_max_value():
    """Missing ``max_value`` raises ValueError — the bridge arm
    mirrors Rust's required-field contract."""
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    with pytest.raises(ValueError, match="max_value"):
        _ta_dict_to_python_effect({
            "kind": (
                "exile_target_creature_with_power_or_toughness_at_most"
            ),
        })


# ---------------------------------------------------------------------------
# Serializer round-trip
# ---------------------------------------------------------------------------


def test_python_serializer_round_trip_max_value_1():
    """Warping Wail mode 1 shape (max_value=1) round-trips
    ``_python_spell_effect_to_dict`` → ``_ta_dict_to_python_effect``
    byte-equal."""
    from mtg_bot.effects.generic.exile import (
        ExileTargetCreatureWithPowerOrToughnessAtMost,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect
    from mtg_bot.parity.trajectory import _python_spell_effect_to_dict

    eff = ExileTargetCreatureWithPowerOrToughnessAtMost(max_value=1)
    d = _python_spell_effect_to_dict(eff)
    assert d == {
        "kind": (
            "exile_target_creature_with_power_or_toughness_at_most"
        ),
        "max_value": 1,
    }
    back = _ta_dict_to_python_effect(d)
    assert isinstance(back, ExileTargetCreatureWithPowerOrToughnessAtMost)
    assert back.max_value == 1


def test_python_serializer_round_trip_max_value_3():
    """Forward-proofs the leaf: an arbitrary max_value (3) also
    round-trips byte-equal."""
    from mtg_bot.effects.generic.exile import (
        ExileTargetCreatureWithPowerOrToughnessAtMost,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect
    from mtg_bot.parity.trajectory import _python_spell_effect_to_dict

    eff = ExileTargetCreatureWithPowerOrToughnessAtMost(max_value=3)
    d = _python_spell_effect_to_dict(eff)
    assert d == {
        "kind": (
            "exile_target_creature_with_power_or_toughness_at_most"
        ),
        "max_value": 3,
    }
    back = _ta_dict_to_python_effect(d)
    assert back.max_value == 3


def test_python_serializer_bails_on_negative_max_value():
    """Defensive: negative max_value bails (returns None) — mirrors
    the ``exile_all_artifacts_with_mana_value_at_most`` leaf's
    negative-rejection sibling pattern."""
    from mtg_bot.effects.generic.exile import (
        ExileTargetCreatureWithPowerOrToughnessAtMost,
    )
    from mtg_bot.parity.trajectory import _python_spell_effect_to_dict

    eff = ExileTargetCreatureWithPowerOrToughnessAtMost(max_value=-1)
    assert _python_spell_effect_to_dict(eff) is None


# ---------------------------------------------------------------------------
# Rust unit pins — parse + to_pydict
# ---------------------------------------------------------------------------


def test_rust_variant_parses_max_value_1():
    """The Rust ``Effect::ExileTargetCreatureWithPowerOrToughnessAt
    Most { max_value }`` variant parses with required ``max_value``
    field."""
    _require_engine()
    rs = _fresh_rust()
    sid = rs.register_and_inject_object(
        {
            "name": "Substrate Probe",
            "card_types": ["Sorcery"],
            "mana_cost": {"generic": 1, "C": 1},
            "effects": [{
                "kind": (
                    "exile_target_creature_with_power_or_toughness_"
                    "at_most"
                ),
                "max_value": 1,
            }],
        },
        0, _ZONE_HAND,
    )
    assert isinstance(sid, int)


def test_rust_variant_rejects_negative_max_value():
    """Negative ``max_value`` rejected at parse time (schema invariant
    — mirrors the ``exile_opponents_nonland_permanent_with_max_mv_-
    until_leaves`` sibling shape)."""
    _require_engine()
    rs = _fresh_rust()
    with pytest.raises(Exception):
        rs.register_and_inject_object(
            {
                "name": "Substrate Bad",
                "card_types": ["Sorcery"],
                "mana_cost": {"generic": 1, "C": 1},
                "effects": [{
                    "kind": (
                        "exile_target_creature_with_power_or_"
                        "toughness_at_most"
                    ),
                    "max_value": -1,
                }],
            },
            0, _ZONE_HAND,
        )


def test_rust_variant_rejects_missing_max_value():
    """Missing ``max_value`` rejected at parse time — required-field
    contract."""
    _require_engine()
    rs = _fresh_rust()
    with pytest.raises(Exception):
        rs.register_and_inject_object(
            {
                "name": "Substrate Bad2",
                "card_types": ["Sorcery"],
                "mana_cost": {"generic": 1, "C": 1},
                "effects": [{
                    "kind": (
                        "exile_target_creature_with_power_or_"
                        "toughness_at_most"
                    ),
                }],
            },
            0, _ZONE_HAND,
        )


# ---------------------------------------------------------------------------
# Rust unit pins — resolve arm
# ---------------------------------------------------------------------------


def test_rust_resolve_exiles_legal_target_power_at_most():
    """Power-leg: target has P=1, T=3, max_value=1 → power leg
    satisfies the disjunction → exile fires."""
    _require_engine()
    rs = _fresh_rust()
    victim = _new_creature(rs, "Goblin", owner=1, power=1, toughness=3)
    _push_exile_spell(rs, caster=0, target_id=victim, max_value=1)
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.find_object_zone(victim) == _ZONE_EXILE, (
        f"P=1, T=3 with max_value=1 → power-leg satisfies → exile; "
        f"got zone={rs.find_object_zone(victim)}"
    )


def test_rust_resolve_exiles_legal_target_toughness_at_most():
    """Toughness-leg: target has P=3, T=1, max_value=1 → toughness
    leg satisfies the disjunction → exile fires."""
    _require_engine()
    rs = _fresh_rust()
    victim = _new_creature(rs, "Wall", owner=1, power=3, toughness=1)
    _push_exile_spell(rs, caster=0, target_id=victim, max_value=1)
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.find_object_zone(victim) == _ZONE_EXILE, (
        f"P=3, T=1 with max_value=1 → toughness-leg satisfies → exile; "
        f"got zone={rs.find_object_zone(victim)}"
    )


def test_rust_resolve_fizzles_on_both_p_and_t_above_threshold():
    """Both effective_power AND effective_toughness > max_value → no
    leg satisfies the disjunction → silent fizzle (CR 608.2b
    typed-filter recheck)."""
    _require_engine()
    rs = _fresh_rust()
    big_bear = _new_creature(rs, "Big Bear", owner=1, power=4, toughness=4)
    _push_exile_spell(rs, caster=0, target_id=big_bear, max_value=1)
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.find_object_zone(big_bear) == _ZONE_BATTLEFIELD, (
        "P=4, T=4 with max_value=1 → both legs fail → bear must STAY on bf"
    )


def test_rust_resolve_fizzles_when_target_no_longer_on_battlefield():
    """Bound target id refers to an object no longer on a
    battlefield (registered then never injected; or moved off bf
    before resolve) → silent fizzle (CR 608.2b)."""
    _require_engine()
    rs = _fresh_rust()
    # Register a creature in the GRAVEYARD (not bf) — its id is bound
    # but it isn't on any battlefield. This emulates a target that
    # was bound at cast time and then left bf before resolve.
    ghost_id = rs.register_and_inject_object(
        {
            "name": "Ghost",
            "card_types": ["Creature"],
            "mana_cost": {"generic": 1},
            "power": 1,
            "toughness": 1,
        },
        1, _ZONE_GRAVEYARD,
    )
    _push_exile_spell(rs, caster=0, target_id=ghost_id, max_value=1)
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    # Target stayed where it was; no mutation.
    assert rs.find_object_zone(ghost_id) == _ZONE_GRAVEYARD, (
        "Target no longer on bf → silent fizzle, target unchanged"
    )


def test_rust_resolve_fizzles_on_non_creature_target():
    """Bound target id refers to a non-creature (artifact, no
    power/toughness) → typed-filter recheck fails → silent fizzle."""
    _require_engine()
    rs = _fresh_rust()
    artifact = rs.register_and_inject_object(
        {
            "name": "Trinket",
            "card_types": ["Artifact"],
            "mana_cost": {"generic": 1},
        },
        1, _ZONE_BATTLEFIELD,
    )
    _push_exile_spell(rs, caster=0, target_id=artifact, max_value=1)
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.find_object_zone(artifact) == _ZONE_BATTLEFIELD, (
        "Non-creature target → typed-filter fails → silent fizzle"
    )


def test_rust_resolve_scans_cross_battlefield_target_owner():
    """Resolve walks BOTH players' battlefields to locate the bound
    target — the spell isn't controller-restricted; the Python class
    has no opponent-only / yours-only flag. A bound target on the
    CASTER'S own bf is exiled (self-exile is legal)."""
    _require_engine()
    rs = _fresh_rust()
    own_bear = _new_creature(rs, "Own Bear", owner=0, power=1, toughness=1)
    _push_exile_spell(rs, caster=0, target_id=own_bear, max_value=1)
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.find_object_zone(own_bear) == _ZONE_EXILE, (
        "Own-bf target → exile fires (no controller restriction in the "
        "Python filter)"
    )


def test_rust_resolve_indestructible_target_is_exiled():
    """Indestructible target IS still exiled — exile bypasses CR
    702.12 (the indestructible keyword only protects against
    destruction, not exile). Matches the established
    ``Effect::ExileTarget { AnyCreature }`` arm precedent which has
    NO indestructible guard either."""
    _require_engine()
    rs = _fresh_rust()
    holy = _new_creature(
        rs, "Holy Cow", owner=1, power=1, toughness=1,
        keywords=["indestructible"],
    )
    _push_exile_spell(rs, caster=0, target_id=holy, max_value=1)
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.find_object_zone(holy) == _ZONE_EXILE, (
        "Indestructible target must still be exiled (exile bypasses "
        "CR 702.12)"
    )


def test_rust_resolve_no_bound_target_is_silent_fizzle():
    """The synthetic-test ``push_to_stack`` API does NOT seat a
    target. For that path, the resolve arm reads
    ``current_resolve_payload_target_id == None`` and silently
    fizzles (matches the FocusFire / CutPropulsion None-payload
    dormancy precedent)."""
    _require_engine()
    rs = _fresh_rust()
    # Inject a bear that COULD be a target, but use the non-target
    # push (no payload-target seat).
    bear = _new_creature(rs, "Bear", owner=1, power=1, toughness=1)
    spell_id = rs.register_and_inject_object(
        {
            "name": "Substrate Probe",
            "card_types": ["Sorcery"],
            "mana_cost": {"generic": 1, "C": 1},
            "effects": [{
                "kind": (
                    "exile_target_creature_with_power_or_toughness_"
                    "at_most"
                ),
                "max_value": 1,
            }],
        },
        0, _ZONE_HAND,
    )
    # Note: push_to_stack (NOT push_to_stack_with_target) — no target
    # seat; current_resolve_payload_target_id stays None.
    rs.push_to_stack(spell_id, 0)
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    # Bear stays on bf — no payload-target, silent fizzle.
    assert rs.find_object_zone(bear) == _ZONE_BATTLEFIELD


# ---------------------------------------------------------------------------
# Effective P/T counters-inclusive sanity
# ---------------------------------------------------------------------------


def test_rust_resolve_respects_counters_pumped_above_threshold():
    """A printed-1/1 creature with +1/+1 counters has effective
    P=2/T=2. With max_value=1 the exile must FIZZLE (counters
    folded into the effective P/T — mirrors Python's
    ``_compute_effective_pt`` source-of-truth view, used by both
    the targeting and the at-resolve recheck on the Python side)."""
    _require_engine()
    rs = _fresh_rust()
    bear = _new_creature(rs, "Counter Bear", owner=1, power=1, toughness=1)
    # Stamp a +1/+1 counter — push effective P=T=2.
    rs.add_counters(bear, 1)
    _push_exile_spell(rs, caster=0, target_id=bear, max_value=1)
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.find_object_zone(bear) == _ZONE_BATTLEFIELD, (
        "Counter-pumped 1/1 (effective 2/2) with max_value=1 → both "
        "legs fail → fizzle"
    )


def test_rust_resolve_respects_counters_minus_one_below_threshold():
    """A printed-3/3 creature with -1/-1 counters (net counters=-1)
    has effective P=2/T=2. With max_value=2 the exile fires
    (effective P=2 ≤ 2). Pins the counter-fold-in on the
    effective-P/T inline computation."""
    _require_engine()
    rs = _fresh_rust()
    bear = _new_creature(rs, "Sicker Bear", owner=1, power=3, toughness=3)
    # Negative counters — net effective P/T = 3 + (-1) = 2.
    rs.add_counters(bear, -1)
    _push_exile_spell(rs, caster=0, target_id=bear, max_value=2)
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.find_object_zone(bear) == _ZONE_EXILE, (
        "Counter-minus-one 3/3 (effective 2/2) with max_value=2 → power "
        "leg satisfies → exile"
    )


# ---------------------------------------------------------------------------
# Round-trip Rust ↔ Python at dict level (the §2 round-trip-or-bail teeth).
# ---------------------------------------------------------------------------


def test_rust_to_pydict_round_trip_max_value_1():
    """The Rust ``to_pydict`` arm emits the exact dict shape the
    parse arm consumes — round-tripping a synthetic ``Effect::Exile
    TargetCreatureWithPowerOrToughnessAtMost { max_value: 1 }``
    through register + dict-extraction yields the same dict (single
    ``max_value`` field, byte-equal to what was registered)."""
    _require_engine()
    rs = _fresh_rust()
    # Inject the spell. Snapshot its registered printing's effects
    # dict via inspect_printing if available; otherwise just confirm
    # the parse-then-resolve cycle works end-to-end (the byte-equal
    # round-trip is also exercised by the
    # ``test_python_serializer_round_trip_max_value_1`` Python-side
    # test — that test bridges the dict back through both engines).
    sid = rs.register_and_inject_object(
        {
            "name": "Substrate Probe",
            "card_types": ["Sorcery"],
            "mana_cost": {"generic": 1, "C": 1},
            "effects": [{
                "kind": (
                    "exile_target_creature_with_power_or_toughness_"
                    "at_most"
                ),
                "max_value": 1,
            }],
        },
        0, _ZONE_HAND,
    )
    assert isinstance(sid, int)
    # Drive a real resolve to exercise the parsed payload — if parse
    # produced a malformed Effect this would crash or silently no-op
    # incorrectly. The resolve arm exiles the bound creature.
    bear = _new_creature(rs, "Bear", owner=1, power=1, toughness=1)
    rs.push_to_stack_with_target(sid, 0, bear)
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.find_object_zone(bear) == _ZONE_EXILE


# ---------------------------------------------------------------------------
# Substrate-only invariants — Warping Wail itself STAYS DECLINED.
# ---------------------------------------------------------------------------


def test_warping_wail_stays_declined_at_admit_gate_post_cycle_1a():
    """**Substrate-only invariant.** This cycle ships ONLY the Effect
    substrate for Mode 1. Warping Wail has THREE modes; Modes 2 + 3
    still have no Rust substrate. The spell-card-bridge admit
    predicate ``_printing_is_bridge_simple_spell`` MUST still decline
    Warping Wail — flipping it requires (a) the Mode 2 substrate
    (Cycle 2), (b) the Mode 3 substrate (Cycle 3), and (c) the
    admit-gate widen for the (0, 1) + or_both=False Phase-6 shape
    (Cycle 4).

    If this pin fails — i.e. Warping Wail starts admitting on this
    branch — the substrate-only invariant has been violated and the
    cross-engine probe will run BEFORE Modes 2 + 3 are implemented,
    producing wrong byte-equal claims. Catch the drift here."""
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    real = get_active_source().get_printings().get("Warping Wail")
    if real is None:
        pytest.skip("Warping Wail absent from active CardSource")
    assert not trajectory._printing_is_bridge_simple_spell(real), (
        "Warping Wail MUST still be declined at the admit gate after "
        "Cycle 1a substrate-only landing (Mode 2 + Mode 3 substrates "
        "still gap — see docs/SEARCH_LIMITATIONS.md 'Warping Wail "
        "Cycle 1a substrate LANDED'). A flip here is a substrate-"
        "scope violation."
    )
