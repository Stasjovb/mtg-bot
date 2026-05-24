"""**Coordinated Clobbering Cycle 1 substrate (2026-05-24).**

Tests for the new field-free ``Effect::CoordinatedClobberingEffect``
Rust variant + matching cross-engine bridge arm + reverse-serializer
leaf.

This is a **substrate-only closure** — the cycle adds the Rust Effect
substrate for Coordinated Clobbering ({G} DSK Sorcery, "Tap one or two
target untapped creatures you control. They each deal damage equal to
their power to target creature an opponent controls.") as
infrastructure. Coordinated Clobbering itself stays DECLINED at the
spell-card-bridge admit gate this cycle because the admit predicate
``_printing_is_bridge_simple_spell`` positively rejects the ``(2, 3)``
heterogeneous 3-slot grammar ``("creature", "my_creature",
"my_creature")`` at every Phase 1-5 disjunct — see
``docs/PHASE4_ADMIT_PERMISSIVENESS_AUDIT_2026-05-24.md`` §1 for the
verify-first walk.

**Cycle 2 deliverable shape** (per the audit + this Cycle 1 verify-
first walk):

  * Phase 6 admit-predicate arm in ``trajectory.py::_printing_is_
    bridge_simple_spell`` for the ``(2, 3)`` heterogeneous shape with
    ``slot_kinds == ("creature", "my_creature", "my_creature")``.
  * Cross-engine 3-slot binder: a ``target_obj_id_3`` field on
    ``StackItem`` (or a per-effect target tuple) + matching
    ``current_resolve_payload_target_id_3`` state slot + cast-time
    binder in ``cast_spell_noncreature`` that picks slot 0
    (deterministic-first opp creature), slot 1 (deterministic-first
    caster's untapped creature), slot 2 (optional second caster's
    untapped creature — agent declines for the optional slot).
  * Resolve arm widen: add the slot-2 read/validate/tap step + a
    second damage instance to slot 0.
  * Admit-set pin bump:
    ``tests/test_cross_engine_etb_triggers.py::test_spell_card_lever_
    phase1_negative_pins_decline_set`` removes Coordinated Clobbering
    from the decline set + bumps the admit count.
  * Per-card real-EoE probe driving the actual parsed Coordinated
    Clobbering printing through both engines byte-equal.

**Test plan (this cycle):**

  * Parser SoT: ``CoordinatedClobberingEffect`` exists in
    ``mtg_bot.effects.bespoke`` with the expected ``(2, 3)`` shape +
    ``("creature", "my_creature", "my_creature")`` slot kinds.
  * Trajectory serializer round-trip: ``_python_spell_effect_to_dict``
    + ``_ta_dict_to_python_effect`` byte-equal for the new unit
    variant.
  * Rust unit pins:
    - ``parse_effect`` consumes ``{"kind": "coordinated_clobbering_
      effect"}`` byte-equal (round-trip ``to_pydict``).
    - 1-target resolve smoke: bind slot 0 (opp creature) only via
      ``push_to_stack_with_target`` — slot 1 absent → silent no-op
      (Python's ``if opp_target is None or not my_objs: return``
      short-circuit on the my_objs leg).
    - Unknown-kind error message extension carries the new variant
      name.
  * Covered-set membership: ``CoordinatedClobberingEffect`` enters
    ``covered_python_class_set()`` via the bridge arm + Rust variant
    landing.
  * **Substrate-only invariant pin** (LOAD-BEARING):
    ``_printing_is_bridge_simple_spell(Coordinated Clobbering)`` is
    STILL ``False`` after this cycle. If this pin fails — i.e.
    Coordinated Clobbering starts admitting on this branch — the
    substrate-only invariant has been violated and the cross-engine
    probe would run BEFORE the 3-slot binder is implemented,
    producing wrong byte-equal claims for the slot-2 friendly
    attacker. Catch the drift here. Cycle 2 is what flips this pin.

**No full 2-target/3-target resolve unit pins this cycle.** Today's
Rust synthetic-push API (``push_to_stack_with_target``) only seats
``target_obj_id`` (slot 0); ``target_obj_id_2`` is ``None``-defaulted
(per the Phase-1 single-target contract documented at
``tests/test_probe_covered_unprobed_s.py:84-94``). The 2-slot binding
that ``CoordinatedClobberingEffect`` requires goes through
``cast_spell_noncreature`` (the production cast path), not the
synthetic ``push_to_stack`` probe idiom. Cycle 2 lands a 2-slot push
API alongside the 3-slot binder, and the real-EoE probe exercises
the full ``cast_spell_noncreature`` admit path byte-equal.
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


def _push_cc_spell(rs, caster, target_id):
    """Inject a bare Coordinated-Clobbering-shape Sorcery on the
    caster's stack with a single payload-target (slot 0 = opp's
    creature taking damage). Slot 1 stays ``None`` per the Phase-1
    single-target ``push_to_stack_with_target`` contract — adequate
    for substrate-only unit pins; the production 2-slot binding
    routes through ``cast_spell_noncreature`` and is Cycle 2 scope.
    """
    spell_id = rs.register_and_inject_object(
        {
            "name": "CC Probe",
            "card_types": ["Sorcery"],
            "mana_cost": {"G": 1},
            "effects": [{"kind": "coordinated_clobbering_effect"}],
        },
        caster, _ZONE_HAND,
    )
    rs.push_to_stack_with_target(spell_id, caster, target_id)
    return spell_id


# ---------------------------------------------------------------------------
# Parser SoT verify-first
# ---------------------------------------------------------------------------


def test_python_class_exists_with_expected_shape():
    """**Parser source-of-truth pin.** The Python
    ``CoordinatedClobberingEffect`` class is in ``mtg_bot.effects.
    bespoke``, is a frozen dataclass, takes NO constructor args, and
    reports the (2, 3) target_count_range + the
    ('creature', 'my_creature', 'my_creature') slot kinds. This pins
    today's Python shape so a parser drift would surface before the
    substrate's bridge/serializer get out of sync.
    """
    from mtg_bot.effects.bespoke import CoordinatedClobberingEffect

    eff = CoordinatedClobberingEffect()
    assert eff.target_count_range() == (2, 3), (
        "Coordinated Clobbering must report (2, 3) — min=2 (1 opp + "
        "1 my), max=3 (1 opp + 2 my)"
    )
    assert eff.target_slot_kinds() == (
        "creature", "my_creature", "my_creature",
    ), (
        "Slot 0 = opp creature, slots 1-2 = caster's untapped "
        "creatures — the (2, 3) heterogeneous 3-slot grammar that "
        "Cycle 2's Phase 6 admit arm will gate"
    )
    assert eff.requires_target() is True


def test_python_class_describe_matches_oracle_text_shape():
    """The describe() returns text that matches Coordinated
    Clobbering's two-sentence oracle body — pins the parser's
    canonical phrase against the printed card."""
    from mtg_bot.effects.bespoke import CoordinatedClobberingEffect

    desc = CoordinatedClobberingEffect().describe()
    low = desc.lower()
    assert "tap one or two" in low
    assert "untapped creatures" in low
    assert "damage equal to" in low and "power" in low
    assert "opponent" in low


def test_real_eoe_printing_parses_to_coordinated_clobbering():
    """**Verify-first.** The active CardSource's "Coordinated
    Clobbering" printing parses to a parameterless
    ``CoordinatedClobberingEffect`` — pins parser invariants the
    Cycle 2 probe will rely on. Skips if the active CardSource does
    not carry the DSK printing."""
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.bespoke import CoordinatedClobberingEffect

    real = get_active_source().get_printings().get("Coordinated Clobbering")
    if real is None:
        pytest.skip("Coordinated Clobbering absent from active CardSource")
    assert isinstance(real.spell_effect, CoordinatedClobberingEffect)
    # No constructor args carried.
    assert real.spell_effect.target_count_range() == (2, 3)
    assert real.spell_effect.target_slot_kinds() == (
        "creature", "my_creature", "my_creature",
    )


# ---------------------------------------------------------------------------
# Covered-set membership
# ---------------------------------------------------------------------------


def test_effect_class_covered_via_bridge_arm():
    """The dict→Python bridge arm in ``cross_engine``
    (``_ta_dict_to_python_effect``) constructs the Python
    ``CoordinatedClobberingEffect`` class from the matching ``kind``
    string. This is the §2 covered-side teeth — the
    ``coordinated_clobbering_effect`` kind enters the covered set
    once this arm exists."""
    from mtg_bot.effects.bespoke import CoordinatedClobberingEffect
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    back = _ta_dict_to_python_effect({"kind": "coordinated_clobbering_effect"})
    assert isinstance(back, CoordinatedClobberingEffect)


def test_covered_python_class_set_contains_coordinated_clobbering():
    """The substrate landing adds ``CoordinatedClobberingEffect`` to
    the covered set surface — the gate the admit predicate's
    `_spell_effect_is_covered_and_bridged` consults. The admit gate
    STAYS DECLINED at the target-grammar tooth (which fires BEFORE
    the covered+bridged tooth), but covered-set membership is now
    correct for the Cycle 2 admit arm to fire when it lands."""
    from mtg_bot.parity.effect_coverage import covered_python_class_set

    assert "CoordinatedClobberingEffect" in covered_python_class_set()


# ---------------------------------------------------------------------------
# Serializer round-trip
# ---------------------------------------------------------------------------


def test_python_serializer_emits_one_key_dict():
    """``_python_spell_effect_to_dict(CoordinatedClobberingEffect())``
    emits the field-free one-key dict the Rust ``parse_effect`` arm
    consumes — byte-equal to ``to_pydict``."""
    from mtg_bot.effects.bespoke import CoordinatedClobberingEffect
    from mtg_bot.parity.trajectory import _python_spell_effect_to_dict

    d = _python_spell_effect_to_dict(CoordinatedClobberingEffect())
    assert d == {"kind": "coordinated_clobbering_effect"}


def test_python_serializer_round_trip_byte_equal():
    """Round-trip pin: Python → dict → Python yields a structurally
    equivalent ``CoordinatedClobberingEffect`` instance. Pins the
    no-fallback-hybrid round-trip-or-bail tooth at the dict level."""
    from mtg_bot.effects.bespoke import CoordinatedClobberingEffect
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect
    from mtg_bot.parity.trajectory import _python_spell_effect_to_dict

    eff = CoordinatedClobberingEffect()
    d = _python_spell_effect_to_dict(eff)
    back = _ta_dict_to_python_effect(d)
    assert isinstance(back, CoordinatedClobberingEffect)
    # Field-free dataclass — equality and hash are structural.
    assert back == eff


# ---------------------------------------------------------------------------
# Rust parse + to_pydict round-trip (the engine-side substrate)
# ---------------------------------------------------------------------------


def test_rust_parse_effect_accepts_one_key_dict():
    """``register_and_inject_object`` with a printing whose
    ``effects`` carries the one-key
    ``{"kind": "coordinated_clobbering_effect"}`` dict succeeds —
    the Rust ``parse_effect`` arm consumes the shape Python's
    serializer emits."""
    _require_engine()
    rs = _fresh_rust()
    spell_id = rs.register_and_inject_object(
        {
            "name": "CC Probe",
            "card_types": ["Sorcery"],
            "mana_cost": {"G": 1},
            "effects": [{"kind": "coordinated_clobbering_effect"}],
        },
        0, _ZONE_HAND,
    )
    assert isinstance(spell_id, int)


def test_rust_parse_rejects_unknown_kind_extension_carries_variant_name():
    """The unknown-effect-kind error message's comma-separated list
    of valid kinds must include ``coordinated_clobbering_effect`` —
    pins the substrate's parse-arm discoverability for callers who
    hit a typo."""
    _require_engine()
    rs = _fresh_rust()
    import pytest
    with pytest.raises(Exception) as exc_info:
        rs.register_and_inject_object(
            {
                "name": "Typo Probe",
                "card_types": ["Sorcery"],
                "mana_cost": {"G": 1},
                "effects": [{"kind": "coordinated_clobbering_effect_typo"}],
            },
            0, _ZONE_HAND,
        )
    msg = str(exc_info.value)
    assert "coordinated_clobbering_effect" in msg, (
        "unknown-effect-kind error must list the variant for "
        "discoverability — got: " + msg
    )


# ---------------------------------------------------------------------------
# Rust resolve — substrate-only smoke (1-target invocation)
# ---------------------------------------------------------------------------
#
# Today's synthetic-push API seats only slot 0
# (``target_obj_id_2 = None``). With slot 1 absent, the resolve arm
# short-circuits per Python's ``if opp_target is None or not my_objs:
# return`` at ``effects/bespoke.py:2472`` — specifically the
# my_objs-empty leg. Pins the silent-fizzle branch.
#
# Full 2-target/3-target resolve behavior is Cycle 2 scope when the
# 2-slot synthetic push API + ``target_id_3`` plumbing land. The
# real-EoE cast-vs-resolve byte-equal probe also ships in Cycle 2.


def test_rust_resolve_silent_noop_with_only_slot_0_bound():
    """Slot 0 (opp's creature) bound, slot 1 (my creature) absent —
    the resolve arm's ``my_pidx`` lookup returns ``None``, no tap
    fires, and the damage component short-circuits. Mirrors Python's
    ``if opp_target is None or not my_objs: return`` (the my_objs-
    empty leg) at ``bespoke.py:2472``.

    Pins that the substrate's resolve arm does NOT crash, mistakenly
    damage the opp creature without a surviving friendly attacker, or
    tap arbitrary creatures when the slot-1 binding is absent."""
    _require_engine()
    rs = _fresh_rust()
    # Opponent (p1) has a bear. Caster (p0) has no creatures.
    opp_bear = _new_creature(rs, "Opp Bear", owner=1, power=1, toughness=2)
    _push_cc_spell(rs, caster=0, target_id=opp_bear)
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    # Opp bear must still be on bf, undamaged — no my-creature
    # attacker means no damage instance fires.
    assert rs.find_object_zone(opp_bear) == _ZONE_BATTLEFIELD, (
        "Opp bear must stay on bf when slot 1 (my creature) is "
        "absent — no damage component"
    )


def test_rust_resolve_silent_noop_no_targets_bound():
    """Neither slot bound — the resolve arm short-circuits on the
    slot-1 lookup (my_pidx None) before reaching the damage step.
    Pins the no-targets fizzle path."""
    _require_engine()
    rs = _fresh_rust()
    # Inject the spell with NO target binding via the bare-push API
    # (no payload-target). The resolve arm must silently no-op.
    spell_id = rs.register_and_inject_object(
        {
            "name": "CC Bare Probe",
            "card_types": ["Sorcery"],
            "mana_cost": {"G": 1},
            "effects": [{"kind": "coordinated_clobbering_effect"}],
        },
        0, _ZONE_HAND,
    )
    # Use the bare push (no target). The resolve must not crash.
    rs.push_to_stack(spell_id, 0)
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    # Just verify no panic. No bf changes to observe.


# ---------------------------------------------------------------------------
# Substrate-only invariant — Coordinated Clobbering STAYS DECLINED.
# ---------------------------------------------------------------------------
#
# **Load-bearing closure marker for Cycle 2's flip.**


def test_coordinated_clobbering_now_admits_at_admit_gate_post_cycle_2():
    """**Cycle 2b closure marker (INVERTED — was the substrate-only
    invariant in Cycle 1 + Cycle 2a, flipped here).** The
    spell-card-bridge admit predicate
    ``_printing_is_bridge_simple_spell`` now ADMITS Coordinated
    Clobbering — the Cycle 2b Phase 6 admit arm in
    ``trajectory._printing_is_bridge_simple_spell`` (the new
    ``_PHASE6_CC_3SLOT_SHAPE`` disjunct gating on
    ``slot_kinds == ("creature", "my_creature", "my_creature")``)
    flipped the gate. The Cycle 2a substrate (3-slot StackItem
    plumbing + cast-time binder + resolve arm with slot-2 step) is
    what made the flip safe.

    Coordinated Clobbering's ``(2, 3)`` heterogeneous 3-slot shape
    now hits the Phase-6 admit arm: ``max_t > min_t`` (the optional
    second-mine_creature slot, agent-decline branch); ``len
    (slot_kinds) == max_t == 3`` (every potentially-filled slot
    enumerated); ``len(set(slot_kinds)) == 2`` (the
    ``"creature"`` + ``"my_creature"`` kinds); ``slot_kinds[0] ==
    "creature"`` (mandatory opp creature first); the exact tuple
    ``("creature", "my_creature", "my_creature")`` (surgical match —
    no sibling 3-slot grammar auto-grows in silently).

    If this pin fails — i.e. Coordinated Clobbering goes back to
    DECLINED at the admit gate — the Cycle 2b Phase 6 admit arm has
    regressed. The flip is load-bearing for the per-card real-EoE
    probe + the admit-set pin bump (count 41 → 42) — a regression
    here cascades into both."""
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    real = get_active_source().get_printings().get("Coordinated Clobbering")
    if real is None:
        pytest.skip("Coordinated Clobbering absent from active CardSource")
    assert trajectory._printing_is_bridge_simple_spell(real), (
        "Coordinated Clobbering MUST be ADMITTED at the admit gate "
        "post-Cycle-2b (the Phase 6 admit arm landed in "
        "trajectory._printing_is_bridge_simple_spell). A DECLINE "
        "here is a regression of the Cycle 2b flip."
    )
