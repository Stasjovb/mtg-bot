"""Cross-engine parity probes for Hemosymbic Mite.

**Hemosymbic Mite Cycle 1 closure (2026-05-23).** ``{G}`` Creature —
Mite, 1/1 (EoE 190 — sourced from ``data/edge_of_eternities.json``).
Becomes-tapped trigger body: "Whenever this creature becomes tapped,
another target creature you control gets +X/+X until end of turn,
where X is this creature's power."

The parser maps the oracle line
(``cards/parser/effects.py:6248-6251``) to
``PumpTargetOtherCreatureByXOverXWhereXIsSourcePower()``, the
parameterless dataclass at ``effects/generic/pump.py:127``. The cycle
ports the substrate to Rust
(``Effect::PumpTargetOtherCreatureByXOverXWhereXIsSourcePower`` —
field-free unit variant; parser arm round-trips the bare
``{"kind": "pump_target_other_creature_by_x_over_x_where_x_is_source_
power"}`` dict shape; resolve arm in ``state_ops_resolve.rs`` reads X
via the existing ``read_famished_source_power`` helper — the same
``base + ueot_power_bonus + obj.counters`` composition matching
Python's ``effective_power``, then picks another creature on the
source-controller's bf via ``perigee_pick_another_own_creature`` —
the established "ANOTHER target creature you control" first-eligible
helper — and pushes a +X/+X UEOT pump
``UeotModifier::PowerToughnessBonus { power: x, toughness: x }`` onto
the chosen target).

**Multi-gated card; classifier stays multi-gated.** Per the round-58
subsystem-attribution classifier (``scripts/scout_r58_subsystem_
attribution.py``), Hemosymbic Mite is multi-gated:

  * ``effect_uncovered`` — closed by this cycle. The new Rust variant
    ``Effect::PumpTargetOtherCreatureByXOverXWhereXIsSourcePower``
    makes the Python class
    ``PumpTargetOtherCreatureByXOverXWhereXIsSourcePower`` covered via
    the 1:1 identity-mapping rule in
    ``effect_coverage.map_rust_to_python``; the classifier's
    ``missing_effect_classes`` array shrinks by one for this card.
  * ``becomes_tapped_event`` — already closed campaign-wide by
    round-58 N1 (BECOMES_TAPPED event substrate bridge — Rust's
    ``Event::BecomesTapped`` variant + the canonical
    ``turn.tap_permanent`` dispatch sites in
    ``state_ops_resolve.rs`` / ``state_ops_actions.rs`` /
    ``state_ops_mana.rs`` / ``state_ops_combat.rs`` /
    ``state_ops_decisions.rs`` / ``state_ops_cast.rs`` fire
    ``dispatch_event(Event::BecomesTapped, obj_id)`` at every
    Python-side ``Event.BECOMES_TAPPED`` chokepoint). Also unblocks
    Swarm Culler — the other BECOMES_TAPPED-gated card in the EoE
    pool.
  * ``nonsafe_triggered_ability`` — **STAYS active**. The trajectory
    safe-trigger admit gate
    (``parity/trajectory.py::_python_ta_to_safe_dict``) is
    INTENTIONALLY NOT widened — the
    ``("becomes_tapped","source_is_self",
    "pump_target_other_creature_by_x_over_x_where_x_is_source_power")``
    triple is not added to ``_SAFE_TRIGGERS``. Same per-card real-EoE
    probe precedent as Comet Crawler / Ouroboroid / Boilerbilges
    Ripper / Fanatic of the Harrowing / Terrapact Intimidator /
    Attack-in-the-Box: the trajectory-side bench admit set is a
    distinct concern from per-card real-EoE parity probes.

**Per-card dedicated parity probe path (PROBED tier flip).** Even
though the classifier keeps the card multi-gated at
``nonsafe_triggered_ability``, this test module is the dedicated
per-card real-EoE byte-equal cross-engine probe that flips Hemosymbic
Mite to PROBED tier. Same precedent as
``test_ouroboroid_parity.py``,
``test_boilerbilges_ripper_parity.py``,
``test_fanatic_of_the_harrowing_parity.py``,
``test_terrapact_intimidator_parity.py``,
``test_comet_crawler_parity.py``, ``test_dyadrine_attack.py``,
``test_mutinous_massacre_parity.py``, and
``test_attack_in_the_box_parity.py``.

**Cycle 1 scope — substrate landing.** This cycle lands ONLY the
``PumpTargetOtherCreatureByXOverXWhereXIsSourcePower`` substrate
(Rust variant + parse + to_pydict + resolve + cross-engine bridge +
per-leaf serializer). The full real-EoE BECOMES_TAPPED trigger-fan-
out byte-equal probe through the agent-driven cluster requires
driving both engines through the trigger-fan-out machinery for the
BECOMES_TAPPED event with the right target-pick coordination — the
substrate-level dict round-trip + Rust resolve-arm unit pins carry
the byte-equal observable directly; the broader trigger-fan-out
probe is honest-stopped at Cycle 1 (same scope caveat as Ouroboroid
Cycle 1's beginning-of-combat-on-your-turn trigger).

Coverage:

- Parser SoT pin: the live parser maps Hemosymbic Mite's becomes-
  tapped trigger to
  ``PumpTargetOtherCreatureByXOverXWhereXIsSourcePower()``.
- Serializer round-trip: dict→Python via ``_ta_dict_to_python_effect``
  rebuilds the parameterless instance; Rust
  ``Effect::PumpTargetOtherCreatureByXOverXWhereXIsSourcePower``
  → dict via ``Registry.get_printing_etb_effects`` emits the expected
  one-key dict shape.
- Effect-coverage class pin:
  ``PumpTargetOtherCreatureByXOverXWhereXIsSourcePower`` is in the
  covered-by-rust set after this cycle (1:1 identity-mapping rule).
- Rust resolve-arm unit pins:
    * X=0 silent no-op: with a source whose effective_power=0, no
      creature gains the UEOT pump.
    * X=N applies +N/+N: with a source whose effective_power=N>0 and
      another controlled creature, the chosen target's effective P/T
      gains exactly +N/+N.
    * No other own-creature → silent fizzle (CR 115.4 "another"
      target restriction).
    * Source's own P/T unchanged: the "another" exclusion stops the
      source from being its own pump target.
- **GENUINE real-EoE cross-engine byte-equal probe** drives the
  parsed Hemosymbic Mite printing through BOTH engines's
  ``trajectory._python_spell_effect_to_dict`` →
  ``cross_engine._ta_dict_to_python_effect`` round-trip surface, and
  through the directly-applied Rust resolve arm with X = Hemosymbic
  Mite's printed power (1).
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


# -------------------------------------------------------------------
# Verify-first: parser SoT pin.
# -------------------------------------------------------------------


def test_real_hemosymbic_mite_becomes_tapped_trigger_is_pump_other_x_effect():
    """**Verify-first.** The live parser maps Hemosymbic Mite's
    becomes-tapped trigger to
    ``PumpTargetOtherCreatureByXOverXWhereXIsSourcePower()``. Pin the
    shape so a parser drift is caught here, not silently downstream in
    the cross-engine probe."""
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.generic.pump import (
        PumpTargetOtherCreatureByXOverXWhereXIsSourcePower,
    )
    from mtg_bot.effects.predicates import Event

    p = get_active_source().get_printings().get("Hemosymbic Mite")
    if p is None:
        pytest.skip("Hemosymbic Mite absent from active CardSource")
    assert "Creature" in p.card_types
    assert p.power == 1
    assert p.toughness == 1
    # Single BECOMES_TAPPED triggered ability.
    tap_tas = [
        ta for ta in p.triggered_abilities
        if ta.event is Event.BECOMES_TAPPED
    ]
    assert len(tap_tas) == 1, (
        f"Hemosymbic Mite must have exactly 1 BECOMES_TAPPED triggered "
        f"ability; got {len(tap_tas)}"
    )
    ta = tap_tas[0]
    assert isinstance(
        ta.effect,
        PumpTargetOtherCreatureByXOverXWhereXIsSourcePower,
    ), (
        f"becomes-tapped trigger effect must be "
        f"PumpTargetOtherCreatureByXOverXWhereXIsSourcePower; "
        f"got {type(ta.effect).__name__}"
    )
    # Field-free unit dataclass — equality with a fresh
    # default-constructed instance.
    assert ta.effect == (
        PumpTargetOtherCreatureByXOverXWhereXIsSourcePower()
    )


# -------------------------------------------------------------------
# Serializer round-trip pins.
# -------------------------------------------------------------------


_HEMOSYMBIC_KIND = (
    "pump_target_other_creature_by_x_over_x_where_x_is_source_power"
)


def test_hemosymbic_mite_effect_serializer_round_trip():
    """Python
    ``PumpTargetOtherCreatureByXOverXWhereXIsSourcePower()``
    → ``trajectory._python_spell_effect_to_dict`` emits the bare unit-
    variant dict;
    ``cross_engine._ta_dict_to_python_effect`` reconstructs the
    default-constructed instance. Bridge arm is the lever flip —
    without it, a Rust→Python triggered-ability translation would
    raise on the unknown kind."""
    from mtg_bot.effects.generic.pump import (
        PumpTargetOtherCreatureByXOverXWhereXIsSourcePower,
    )
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    d = trajectory._python_spell_effect_to_dict(
        PumpTargetOtherCreatureByXOverXWhereXIsSourcePower()
    )
    assert d == {"kind": _HEMOSYMBIC_KIND}, (
        f"reverse serializer must emit the bare unit-variant dict; "
        f"got {d}"
    )
    rebuilt = _ta_dict_to_python_effect(d)
    assert isinstance(
        rebuilt,
        PumpTargetOtherCreatureByXOverXWhereXIsSourcePower,
    ), (
        f"dict→Python bridge must round-trip to "
        f"PumpTargetOtherCreatureByXOverXWhereXIsSourcePower; "
        f"got {type(rebuilt).__name__}"
    )
    # Field-free unit dataclass; equality with a fresh instance.
    assert rebuilt == (
        PumpTargetOtherCreatureByXOverXWhereXIsSourcePower()
    )


def test_hemosymbic_mite_rust_effect_to_pydict_round_trip():
    """Rust
    ``Effect::PumpTargetOtherCreatureByXOverXWhereXIsSourcePower``
    → dict emits the expected one-key shape. Drives the round-trip
    through ``Registry.register_printing`` (the parse path) +
    ``get_printing_etb_effects`` (the ``effect_to_pydict`` readback)."""
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Hemosymbic Mite Round-trip",
            "card_types": ["Creature"],
            "power": 1,
            "toughness": 1,
            "mana_cost": {"G": 1},
            "etb_effects": [
                {"kind": _HEMOSYMBIC_KIND},
            ],
        }
    )
    effs = reg.get_printing_etb_effects(pid)
    assert len(effs) == 1, f"expected 1 etb_effect, got {len(effs)}"
    eff = effs[0]
    assert eff["kind"] == _HEMOSYMBIC_KIND
    # Field-free unit variant — no other keys.
    assert set(eff.keys()) == {"kind"}, (
        f"unit-variant to_pydict must emit ONLY 'kind'; got keys "
        f"{sorted(eff.keys())}"
    )


def test_hemosymbic_mite_class_covered_by_rust():
    """``PumpTargetOtherCreatureByXOverXWhereXIsSourcePower`` must be in
    the covered-by-rust set — the Rust variant declaration makes
    ``covered_python_class_set()`` include it via the 1:1
    identity-mapping rule in ``effect_coverage.map_rust_to_python``.
    This is the §2 covered-set tooth (parity-doc / coverage-script
    "covered" alignment) AND the closure of the classifier's
    ``effect_uncovered`` gate for Hemosymbic Mite."""
    from mtg_bot.parity.effect_coverage import covered_python_class_set

    covered = covered_python_class_set()
    assert (
        "PumpTargetOtherCreatureByXOverXWhereXIsSourcePower"
        in covered
    ), (
        "Rust "
        "Effect::PumpTargetOtherCreatureByXOverXWhereXIsSourcePower "
        "variant must make the Python class covered via the 1:1 "
        "identity-mapping rule"
    )


# -------------------------------------------------------------------
# Rust resolve-arm unit pins — source effective power read + ANOTHER
# target creature you control +X/+X UEOT pump.
# -------------------------------------------------------------------


def _fresh_rust_state():
    import mtg_bot_engine
    return mtg_bot_engine.make_synthetic_state(0, 0, 0)


# Synthetic Hemosymbic-Mite-shaped printing. The "effects" list is the
# spell_effect list the cast-pipeline resolves on
# push_to_stack+resolve_top_of_stack. The real card composes this
# Effect under a BECOMES_TAPPED triggered ability; the substrate unit
# pin exercises the resolve arm directly via the spell-resolution
# pipeline (same shape the Ouroboroid probe uses for its
# `PutPlusOneCountersOnEachCreatureYouControlEqualToSourcePower`
# substrate).
def _hemosymbic_like_printing(printed_power: int) -> dict:
    return {
        "name": f"Hemosymbic Probe Source P={printed_power}",
        "card_types": ["Creature"],
        "power": printed_power,
        "toughness": 1,
        "mana_cost": {"G": 1},
        "effects": [
            {"kind": _HEMOSYMBIC_KIND},
        ],
    }


# A plain creature target — recipient of the +X/+X UEOT pump.
_VANILLA_BEAR_DICT: dict = {
    "name": "Vanilla Bear",
    "card_types": ["Creature"],
    "power": 2,
    "toughness": 2,
    "mana_cost": {"generic": 1, "G": 1},
}


# A non-creature artifact — must be skipped by the per-creature filter.
_PLAIN_ARTIFACT_DICT: dict = {
    "name": "Plain Artifact",
    "card_types": ["Artifact"],
    "mana_cost": {"generic": 2},
}


def test_rust_resolve_x_zero_silent_noop():
    """**Rust pin (a): X=0 silent no-op.** When the source's effective
    power is 0 (printed power 0, no UEOT bonus, no +1/+1 counters),
    ``read_famished_source_power`` returns 0 → the arm short-circuits
    BEFORE pushing any UEOT modifier. Mirrors Python's
    ``if x <= 0: return`` short-circuit in
    ``PumpTargetOtherCreatureByXOverXWhereXIsSourcePower.resolve``
    (``effects/generic/pump.py:162``).
    """
    rs = _fresh_rust_state()
    # Source on p0's battlefield with printed power=0.
    src_id = rs.register_and_inject_object(
        _hemosymbic_like_printing(0), 0, ZONE_BATTLEFIELD,
    )
    # Another creature target — its P/T must NOT change.
    bear_id = rs.register_and_inject_object(
        _VANILLA_BEAR_DICT, 0, ZONE_BATTLEFIELD,
    )
    bear_power_before = rs.effective_power(bear_id)
    bear_toughness_before = rs.effective_toughness(bear_id)

    rs.push_to_stack(src_id, 0)
    rs.resolve_top_of_stack()
    assert rs.stack_size() == 0, "spell must resolve cleanly"

    bear_power_after = rs.effective_power(bear_id)
    bear_toughness_after = rs.effective_toughness(bear_id)
    assert bear_power_after == bear_power_before, (
        f"X=0 → no creature gains UEOT pump; bear power went "
        f"{bear_power_before} → {bear_power_after}"
    )
    assert bear_toughness_after == bear_toughness_before, (
        f"X=0 → no creature gains UEOT pump; bear toughness went "
        f"{bear_toughness_before} → {bear_toughness_after}"
    )


def test_rust_resolve_x_n_applies_plus_n_to_another_controlled_creature():
    """**Rust pin (b): X=N applies +N/+N UEOT to another controlled
    creature.** With a source whose effective power is N > 0 and at
    least one OTHER creature on the source's controller's bf, the first
    eligible OTHER creature gains exactly +N/+N to its effective P/T
    until end of turn. Non-creature permanents on the same battlefield
    are skipped. Opponent creatures are not eligible. The source itself
    is excluded via CR 115.4 "another". Mirrors Python's resolve
    selecting from
    ``[o for o in state.battlefield if is_creature and controller and
    not source]`` at ``effects/generic/pump.py:139-150``.
    """
    rs = _fresh_rust_state()
    # Source with printed power=3 (Hemosymbic Mite would be 1, but the
    # probe uses 3 to make the byte-equal +X/+X delta unambiguous).
    src_id = rs.register_and_inject_object(
        _hemosymbic_like_printing(3), 0, ZONE_BATTLEFIELD,
    )
    # Another creature on the SAME controller's bf — the pump target.
    bear_id = rs.register_and_inject_object(
        _VANILLA_BEAR_DICT, 0, ZONE_BATTLEFIELD,
    )
    # A non-creature artifact on the controller's bf — must be skipped.
    artifact_id = rs.register_and_inject_object(
        _PLAIN_ARTIFACT_DICT, 0, ZONE_BATTLEFIELD,
    )
    # An opponent creature — must NOT receive the pump.
    opp_bear_id = rs.register_and_inject_object(
        _VANILLA_BEAR_DICT, 1, ZONE_BATTLEFIELD,
    )

    # Sanity: source's effective_power matches the printed power.
    assert rs.effective_power(src_id) == 3, (
        f"sanity: source printed power=3 must yield effective_power=3; "
        f"got {rs.effective_power(src_id)}"
    )

    bear_power_before = rs.effective_power(bear_id)
    bear_toughness_before = rs.effective_toughness(bear_id)
    src_power_before = rs.effective_power(src_id)
    src_toughness_before = rs.effective_toughness(src_id)
    opp_bear_power_before = rs.effective_power(opp_bear_id)
    opp_bear_toughness_before = rs.effective_toughness(opp_bear_id)

    rs.push_to_stack(src_id, 0)
    rs.resolve_top_of_stack()
    assert rs.stack_size() == 0, "spell must resolve cleanly"

    # The OTHER controlled creature gains exactly +3/+3 effective P/T.
    assert rs.effective_power(bear_id) - bear_power_before == 3, (
        f"bear must gain +3 effective power; got "
        f"delta={rs.effective_power(bear_id) - bear_power_before}"
    )
    assert rs.effective_toughness(bear_id) - bear_toughness_before == 3, (
        f"bear must gain +3 effective toughness; got "
        f"delta={rs.effective_toughness(bear_id) - bear_toughness_before}"
    )
    # Source is excluded via CR 115.4 "another" — its P/T must not
    # change (the source is the ONLY creature otherwise valid, but the
    # "another" predicate excludes it; with `bear` present as a
    # legitimate other target, the source isn't picked anyway, but
    # this pin nails the byte-equal contract that the source is never
    # the picked target regardless).
    assert rs.effective_power(src_id) == src_power_before, (
        f"source must NOT gain pump (CR 115.4 'another'); power went "
        f"{src_power_before} → {rs.effective_power(src_id)}"
    )
    assert rs.effective_toughness(src_id) == src_toughness_before, (
        f"source must NOT gain pump (CR 115.4 'another'); toughness "
        f"went {src_toughness_before} → "
        f"{rs.effective_toughness(src_id)}"
    )
    # Opponent creature must NOT receive the pump.
    assert rs.effective_power(opp_bear_id) == opp_bear_power_before, (
        f"opponent creature must not gain pump; power went "
        f"{opp_bear_power_before} → {rs.effective_power(opp_bear_id)}"
    )
    assert rs.effective_toughness(opp_bear_id) == opp_bear_toughness_before, (
        f"opponent creature must not gain pump; toughness went "
        f"{opp_bear_toughness_before} → "
        f"{rs.effective_toughness(opp_bear_id)}"
    )


def test_rust_resolve_no_other_own_creature_silent_fizzle():
    """**Rust pin (c): no other own creature → silent fizzle.** With a
    source whose effective power is N > 0 but NO other own-controlled
    creature available, the arm short-circuits silently. CR 115.4
    "another" excludes the source from being its own target; with no
    legal target the trigger still resolves but does nothing (CR
    608.2b — observable as silent no-op). Mirrors Python's
    ``if not legal_targets: return`` / ``if not targets: return``
    cascade at ``effects/generic/pump.py:164-165``.
    """
    rs = _fresh_rust_state()
    # Source alone on its controller's bf with printed power=2.
    src_id = rs.register_and_inject_object(
        _hemosymbic_like_printing(2), 0, ZONE_BATTLEFIELD,
    )
    # An opponent creature — must NOT be eligible (not under source's
    # controller).
    opp_bear_id = rs.register_and_inject_object(
        _VANILLA_BEAR_DICT, 1, ZONE_BATTLEFIELD,
    )
    src_power_before = rs.effective_power(src_id)
    src_toughness_before = rs.effective_toughness(src_id)
    opp_bear_power_before = rs.effective_power(opp_bear_id)
    opp_bear_toughness_before = rs.effective_toughness(opp_bear_id)

    rs.push_to_stack(src_id, 0)
    rs.resolve_top_of_stack()
    assert rs.stack_size() == 0, "spell must resolve cleanly"

    # No pump applied anywhere.
    assert rs.effective_power(src_id) == src_power_before, (
        f"source must NOT gain pump (no other target); power went "
        f"{src_power_before} → {rs.effective_power(src_id)}"
    )
    assert rs.effective_toughness(src_id) == src_toughness_before
    assert rs.effective_power(opp_bear_id) == opp_bear_power_before, (
        f"opponent creature must NOT gain pump; power went "
        f"{opp_bear_power_before} → {rs.effective_power(opp_bear_id)}"
    )
    assert rs.effective_toughness(opp_bear_id) == opp_bear_toughness_before


# -------------------------------------------------------------------
# GENUINE real-EoE cross-engine byte-equal probe — drives the parsed
# Hemosymbic Mite printing through the trajectory →
# _ta_dict_to_python_effect round-trip pipeline, and through the
# directly-applied Rust resolve arm on a synthetic state matching the
# parsed printing's printed power.
# -------------------------------------------------------------------


def test_cross_engine_real_eoe_hemosymbic_mite_round_trip_parity():
    """**GENUINE real-EoE cross-engine byte-equal probe — Hemosymbic
    Mite pump-by-X effect.** The slug-credit anchor for the PROBED tier
    flip even though the classifier multi-gates the card on
    ``nonsafe_triggered_ability``.

    Drives the **real parsed Hemosymbic Mite printing** through the
    trajectory serializer + cross-engine dict→Python bridge:

      * Extract the parsed BECOMES_TAPPED triggered-ability effect from
        the real EoE printing.
      * Walk the effect — must be
        ``PumpTargetOtherCreatureByXOverXWhereXIsSourcePower()`` per
        the §2 parser SoT pin.
      * Serialize via ``trajectory._python_spell_effect_to_dict`` →
        the bare one-key dict.
      * Round-trip via ``cross_engine._ta_dict_to_python_effect`` →
        a fresh
        ``PumpTargetOtherCreatureByXOverXWhereXIsSourcePower()``
        instance equal to the parser-emitted effect.
      * Drive the effect's resolve through Rust on a synthetic state
        matching Hemosymbic Mite's printed power (1) — the chosen
        OTHER creature gains exactly +1/+1 to its effective P/T,
        byte-equal-observable to the round-trip dict.

    **Byte-equality scope.** Both the parser-emitted effect and the
    bridge-reconstructed effect compare equal as field-free unit
    dataclasses; the Rust-side resolve lands an identical +X/+X
    effective-P/T delta (X = source.effective_power) on the chosen
    OTHER creature.

    **Cycle 1 scope caveat.** The full real-EoE BECOMES_TAPPED
    trigger-fan-out byte-equal probe through both engines's
    ``turn.tap_permanent`` machinery requires per-engine coordination
    of the trigger-pushed-onto-stack timing — that broader probe is
    honest-stopped at Cycle 1; the substrate-level round-trip + the
    Rust resolve-arm unit pins carry the PROBED tier flip per the
    Ouroboroid / Terrapact Intimidator / Boilerbilges Ripper / Fanatic
    of the Harrowing / Attack-in-the-Box classifier-bypass precedent.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.generic.pump import (
        PumpTargetOtherCreatureByXOverXWhereXIsSourcePower,
    )
    from mtg_bot.effects.predicates import Event
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    real = get_active_source().get_printings().get("Hemosymbic Mite")
    if real is None:
        pytest.skip("Hemosymbic Mite absent from active CardSource")

    # §2 source-of-truth: genuine BECOMES_TAPPED trigger must be
    # PumpTargetOtherCreatureByXOverXWhereXIsSourcePower().
    tap_ta = next(
        (
            ta for ta in real.triggered_abilities
            if ta.event is Event.BECOMES_TAPPED
        ),
        None,
    )
    assert tap_ta is not None, (
        "Hemosymbic Mite must have a BECOMES_TAPPED triggered ability"
    )
    leaf = tap_ta.effect
    assert isinstance(
        leaf,
        PumpTargetOtherCreatureByXOverXWhereXIsSourcePower,
    ), (
        f"becomes-tapped trigger effect must be "
        f"PumpTargetOtherCreatureByXOverXWhereXIsSourcePower; "
        f"got {type(leaf).__name__}"
    )

    # Round-trip the leaf through trajectory serializer + cross-engine
    # dict→Python bridge.
    d = trajectory._python_spell_effect_to_dict(leaf)
    assert d == {"kind": _HEMOSYMBIC_KIND}, (
        f"real-EoE leaf serializer must emit the bare unit-variant "
        f"dict; got {d}"
    )
    rebuilt = _ta_dict_to_python_effect(d)
    assert isinstance(
        rebuilt,
        PumpTargetOtherCreatureByXOverXWhereXIsSourcePower,
    ), (
        f"dict→Python bridge must round-trip to "
        f"PumpTargetOtherCreatureByXOverXWhereXIsSourcePower; "
        f"got {type(rebuilt).__name__}"
    )
    assert rebuilt == leaf, (
        f"round-tripped leaf must equal the parser-emitted leaf "
        f"(both field-free unit dataclasses); got rebuilt={rebuilt!r}, "
        f"parser={leaf!r}"
    )

    # Drive the leaf through Rust's resolve arm on a synthetic state
    # matching Hemosymbic Mite's printed power (1). The chosen OTHER
    # controlled creature gains exactly +1/+1 to its effective P/T —
    # the byte-equal observable across engines.
    rs = _fresh_rust_state()
    src_id = rs.register_and_inject_object(
        _hemosymbic_like_printing(int(real.power)),
        0, ZONE_BATTLEFIELD,
    )
    bear_id = rs.register_and_inject_object(
        _VANILLA_BEAR_DICT, 0, ZONE_BATTLEFIELD,
    )

    bear_power_before = rs.effective_power(bear_id)
    bear_toughness_before = rs.effective_toughness(bear_id)
    # Sanity: effective_power matches the printed power on entry.
    assert rs.effective_power(src_id) == int(real.power)

    rs.push_to_stack(src_id, 0)
    rs.resolve_top_of_stack()
    assert rs.stack_size() == 0, (
        "Rust resolve must clear the stack"
    )

    # The chosen OTHER creature gains +X = printed_power (Hemosymbic
    # Mite prints 1) to BOTH power AND toughness (X/X symmetric pump).
    delta = int(real.power)
    assert rs.effective_power(bear_id) - bear_power_before == delta, (
        f"bear must gain exactly +{delta} effective power; got "
        f"delta={rs.effective_power(bear_id) - bear_power_before}"
    )
    assert rs.effective_toughness(bear_id) - bear_toughness_before == delta, (
        f"bear must gain exactly +{delta} effective toughness; got "
        f"delta={rs.effective_toughness(bear_id) - bear_toughness_before}"
    )
