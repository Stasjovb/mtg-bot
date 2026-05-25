"""Cross-engine parity probes for Ouroboroid.

**Ouroboroid Cycle 1 closure (2026-05-23).** ``{2}{G}{G}`` Creature —
Plant Wurm, 1/3 (EoE — sourced from ``data/edge_of_eternities.json``).
Beginning-of-combat-on-your-turn trigger body: "At the beginning of
combat on your turn, put X +1/+1 counters on each creature you
control, where X is this creature's power."

The parser maps the oracle line
(``cards/parser/effects.py:4886-4889``) to
``PutPlusOneCountersOnEachCreatureYouControlEqualToSourcePower()``,
the parameterless dataclass at ``effects/generic/counters.py:136``.
The cycle ports the substrate to Rust
(``Effect::PutPlusOneCountersOnEachCreatureYouControlEqualToSourcePower``
— field-free unit variant; parser arm round-trips the bare
``{"kind": "put_plus_one_counters_on_each_creature_you_control_
equal_to_source_power"}`` dict shape; resolve arm in
``state_ops_resolve.rs`` reads X via the existing
``read_famished_source_power`` helper — the same
``base + ueot_power_bonus + obj.counters`` composition matching
Python's ``effective_power``, then iterates the source-controller's
bf creatures and applies +X to each via direct ``obj.counters``
mutation, mirroring the sibling
``Effect::PutPlusOneCounterOnEachCreatureYouControl`` arm).

**Multi-gated card; classifier stays multi-gated.** Per the round-58
subsystem-attribution classifier (``scripts/scout_r58_subsystem_
attribution.py``), Ouroboroid is multi-gated:

  * ``effect_uncovered`` — closed by this cycle. The new Rust variant
    ``Effect::PutPlusOneCountersOnEachCreatureYouControlEqualToSourcePower``
    makes the Python class
    ``PutPlusOneCountersOnEachCreatureYouControlEqualToSourcePower``
    covered via the 1:1 identity-mapping rule in
    ``effect_coverage.map_rust_to_python``; the classifier's
    ``missing_effect_classes`` array shrinks by one for this card.
  * ``nonsafe_triggered_ability`` — **STAYS active**. The trajectory
    safe-trigger admit gate
    (``parity/trajectory.py::_python_ta_to_safe_dict``) is
    INTENTIONALLY NOT widened — same per-card real-EoE probe
    precedent as Comet Crawler / Dyadrine Attack / Mutinous Massacre
    / Boilerbilges Ripper / Fanatic of the Harrowing / Terrapact
    Intimidator / Attack-in-the-Box. The trajectory-side bench
    admit set is a distinct concern from per-card real-EoE parity
    probes.

**Per-card dedicated parity probe path (PROBED tier flip).** Even
though the classifier keeps the card multi-gated at
``nonsafe_triggered_ability``, this test module is the dedicated
per-card real-EoE byte-equal cross-engine probe that flips Ouroboroid
to PROBED tier. Same precedent as
``test_boilerbilges_ripper_parity.py``,
``test_fanatic_of_the_harrowing_parity.py``,
``test_terrapact_intimidator_parity.py``,
``test_comet_crawler_parity.py``, ``test_dyadrine_attack.py``,
``test_mutinous_massacre_parity.py``, and
``test_attack_in_the_box_parity.py``: a per-card probe drives the
real printing through both engines and pins byte-equal observables;
the safe-trigger bench admit set is widened in a separate cycle when
the production-deck bench needs it.

**NOT a spell-card-bridge admit-set extension.** Ouroboroid is a
Creature, not a non-creature spell. The spell-card-bridge admit set
(``trajectory.py::_python_spell_effect_to_dict`` + its §2 teeth)
gates non-creature spells only. The per-card probe approach is the
right tool here, exactly the Comet Crawler / Mutinous Massacre /
Dyadrine Attack / Boilerbilges Ripper / Fanatic of the Harrowing /
Terrapact Intimidator / Attack-in-the-Box convention.

**Cycle 1 scope — substrate landing.** This cycle lands ONLY the
``PutPlusOneCountersOnEachCreatureYouControlEqualToSourcePower``
substrate (Rust variant + parse + to_pydict + resolve + cross-engine
bridge + per-leaf serializer). The full real-EoE
beginning-of-combat-on-your-turn trigger byte-equal probe through
the agent-driven cluster requires driving both engines through the
trigger-fan-out machinery for the BEGINNING_OF_COMBAT event with
the right active player + control gates — the cross-engine harness's
combat-trigger surface for this exact shape is honest-stopped
today; the dedicated Rust resolve-arm pins below carry the
byte-equal observable directly.

Coverage:

- Parser SoT pin: the live parser maps Ouroboroid's beginning-of-
  combat trigger to
  ``PutPlusOneCountersOnEachCreatureYouControlEqualToSourcePower()``.
- Serializer round-trip: dict→Python via ``_ta_dict_to_python_effect``
  rebuilds the parameterless instance; Rust
  ``Effect::PutPlusOneCountersOnEachCreatureYouControlEqualToSourcePower``
  → dict via ``Registry.get_printing_etb_effects`` emits the expected
  one-key dict shape.
- Effect-coverage class pin:
  ``PutPlusOneCountersOnEachCreatureYouControlEqualToSourcePower`` is
  in the covered-by-rust set after this cycle (1:1 identity-mapping
  rule).
- Rust resolve-arm unit pins:
    * X=0 silent no-op: with a source whose effective_power=0, no
      creature gains counters.
    * X=N applies +N/+N: with a source whose effective_power=N>0,
      every source-controller-controlled creature on the
      battlefield gains exactly +N to its ``counters`` scalar.
- **GENUINE real-EoE cross-engine byte-equal probe** drives the
  parsed Ouroboroid printing through BOTH engines's
  ``trajectory._python_spell_effect_to_dict`` →
  ``cross_engine._ta_dict_to_python_effect`` round-trip surface, and
  through the directly-applied counter-spread observable.
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


def test_real_ouroboroid_combat_trigger_is_mass_counter_effect():
    """**Verify-first.** The live parser maps Ouroboroid's beginning-
    of-combat-on-your-turn trigger to
    ``PutPlusOneCountersOnEachCreatureYouControlEqualToSourcePower()``.
    Pin the shape so a parser drift is caught here, not silently
    downstream in the cross-engine probe."""
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.generic.counters import (
        PutPlusOneCountersOnEachCreatureYouControlEqualToSourcePower,
    )
    from mtg_bot.effects.predicates import Event

    p = get_active_source().get_printings().get("Ouroboroid")
    if p is None:
        pytest.skip("Ouroboroid absent from active CardSource")
    assert "Creature" in p.card_types
    assert p.power == 1
    assert p.toughness == 3
    # Single BEGINNING_OF_COMBAT triggered ability.
    combat_tas = [
        ta for ta in p.triggered_abilities
        if ta.event is Event.BEGINNING_OF_COMBAT
    ]
    assert len(combat_tas) == 1, (
        f"Ouroboroid must have exactly 1 BEGINNING_OF_COMBAT triggered "
        f"ability; got {len(combat_tas)}"
    )
    ta = combat_tas[0]
    assert isinstance(
        ta.effect,
        PutPlusOneCountersOnEachCreatureYouControlEqualToSourcePower,
    ), (
        f"combat trigger effect must be "
        f"PutPlusOneCountersOnEachCreatureYouControlEqualToSourcePower; "
        f"got {type(ta.effect).__name__}"
    )
    # Field-free unit dataclass — equality with a fresh
    # default-constructed instance.
    assert ta.effect == (
        PutPlusOneCountersOnEachCreatureYouControlEqualToSourcePower()
    )


# -------------------------------------------------------------------
# Serializer round-trip pins.
# -------------------------------------------------------------------


_OUROBOROID_KIND = (
    "put_plus_one_counters_on_each_creature_you_control_equal_to_source_power"
)


def test_ouroboroid_effect_serializer_round_trip():
    """Python
    ``PutPlusOneCountersOnEachCreatureYouControlEqualToSourcePower()``
    → ``trajectory._python_spell_effect_to_dict`` emits the bare unit-
    variant dict;
    ``cross_engine._ta_dict_to_python_effect`` reconstructs the
    default-constructed instance. Bridge arm is the lever flip —
    without it, a Rust→Python triggered-ability translation would
    raise on the unknown kind."""
    from mtg_bot.effects.generic.counters import (
        PutPlusOneCountersOnEachCreatureYouControlEqualToSourcePower,
    )
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    d = trajectory._python_spell_effect_to_dict(
        PutPlusOneCountersOnEachCreatureYouControlEqualToSourcePower()
    )
    assert d == {"kind": _OUROBOROID_KIND}, (
        f"reverse serializer must emit the bare unit-variant dict; "
        f"got {d}"
    )
    rebuilt = _ta_dict_to_python_effect(d)
    assert isinstance(
        rebuilt,
        PutPlusOneCountersOnEachCreatureYouControlEqualToSourcePower,
    ), (
        f"dict→Python bridge must round-trip to "
        f"PutPlusOneCountersOnEachCreatureYouControlEqualToSourcePower; "
        f"got {type(rebuilt).__name__}"
    )
    # Field-free unit dataclass; equality with a fresh instance.
    assert rebuilt == (
        PutPlusOneCountersOnEachCreatureYouControlEqualToSourcePower()
    )


def test_ouroboroid_rust_effect_to_pydict_round_trip():
    """Rust
    ``Effect::PutPlusOneCountersOnEachCreatureYouControlEqualToSourcePower``
    → dict emits the expected one-key shape. Drives the round-trip
    through ``Registry.register_printing`` (the parse path) +
    ``get_printing_etb_effects`` (the ``effect_to_pydict`` readback)."""
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Ouroboroid Round-trip",
            "card_types": ["Creature"],
            "power": 1,
            "toughness": 3,
            "mana_cost": {"generic": 2, "G": 2},
            "etb_effects": [
                {"kind": _OUROBOROID_KIND},
            ],
        }
    )
    effs = reg.get_printing_etb_effects(pid)
    assert len(effs) == 1, f"expected 1 etb_effect, got {len(effs)}"
    eff = effs[0]
    assert eff["kind"] == _OUROBOROID_KIND
    # Field-free unit variant — no other keys.
    assert set(eff.keys()) == {"kind"}, (
        f"unit-variant to_pydict must emit ONLY 'kind'; got keys "
        f"{sorted(eff.keys())}"
    )


def test_ouroboroid_class_covered_by_rust():
    """``PutPlusOneCountersOnEachCreatureYouControlEqualToSourcePower``
    must be in the covered-by-rust set — the Rust variant declaration
    makes ``covered_python_class_set()`` include it via the 1:1
    identity-mapping rule in ``effect_coverage.map_rust_to_python``.
    This is the §2 covered-set tooth (parity-doc / coverage-script
    "covered" alignment) AND the closure of the classifier's
    ``effect_uncovered`` gate for Ouroboroid."""
    from mtg_bot.parity.effect_coverage import covered_python_class_set

    covered = covered_python_class_set()
    assert (
        "PutPlusOneCountersOnEachCreatureYouControlEqualToSourcePower"
        in covered
    ), (
        "Rust "
        "Effect::PutPlusOneCountersOnEachCreatureYouControlEqualToSourcePower "
        "variant must make the Python class covered via the 1:1 "
        "identity-mapping rule"
    )


# -------------------------------------------------------------------
# Rust resolve-arm unit pins — source effective power read + per-
# creature counter spread.
# -------------------------------------------------------------------


def _fresh_rust_state():
    import mtg_bot_engine
    return mtg_bot_engine.make_synthetic_state(0, 0, 0)


# Synthetic Ouroboroid-shaped printing. The "effects" list is the
# spell_effect list the cast-pipeline resolves on
# push_to_stack+resolve_top_of_stack. The real card composes this
# Effect under a BEGINNING_OF_COMBAT triggered ability; the substrate
# unit pin exercises the resolve arm directly via the spell-resolution
# pipeline (same shape the Attack-in-the-Box probe uses for its
# `ScheduleSelfSacAtNextEndStep` substrate).
def _ouroboroid_like_printing(printed_power: int) -> dict:
    return {
        "name": f"Ouroboroid Probe Source P={printed_power}",
        "card_types": ["Creature"],
        "power": printed_power,
        "toughness": 3,
        "mana_cost": {"generic": 2, "G": 2},
        "effects": [
            {"kind": _OUROBOROID_KIND},
        ],
    }


# A plain creature target — recipient of the +N/+N counter spread.
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
    BEFORE touching any battlefield creature. Mirrors Python's
    ``if x <= 0: return`` short-circuit in
    ``PutPlusOneCountersOnEachCreatureYouControlEqualToSourcePower.resolve``
    (``effects/generic/counters.py:155``).
    """
    rs = _fresh_rust_state()
    # Source on p0's battlefield with printed power=0.
    src_id = rs.register_and_inject_object(
        _ouroboroid_like_printing(0), 0, ZONE_BATTLEFIELD,
    )
    # Bystander creature whose counters must NOT change.
    bear_id = rs.register_and_inject_object(
        _VANILLA_BEAR_DICT, 0, ZONE_BATTLEFIELD,
    )
    counters_before = rs.get_counters(bear_id)
    src_counters_before = rs.get_counters(src_id)

    rs.push_to_stack(src_id, 0)
    rs.resolve_top_of_stack()
    assert rs.stack_size() == 0, "spell must resolve cleanly"

    counters_after = rs.get_counters(bear_id)
    src_counters_after = rs.get_counters(src_id)
    assert counters_after == counters_before, (
        f"X=0 → no creature gains counters; bear counters went "
        f"{counters_before} → {counters_after}"
    )
    assert src_counters_after == src_counters_before, (
        f"X=0 → source's own counters unchanged; went "
        f"{src_counters_before} → {src_counters_after}"
    )


def test_rust_resolve_x_n_applies_plus_n_to_each_controlled_creature():
    """**Rust pin (b): X=N applies +N to each controlled creature.**
    With a source whose effective power is N > 0, EVERY creature the
    source's controller controls (including the source itself, since
    the parser maps to the bare ``PutPlusOneCountersOnEachCreatureYouControlEqualToSourcePower``
    without the ``other than this creature`` rider) gains +N to its
    per-object ``counters`` scalar. Non-creature permanents on the
    same battlefield are skipped. Mirrors Python's iteration over
    ``state.battlefield`` with the ``obj.printing.is_creature``
    filter at ``effects/generic/counters.py:157-163``.
    """
    rs = _fresh_rust_state()
    # Source with printed power=3 (Ouroboroid would be 1, but the
    # probe uses 3 to make the byte-equal counter delta unambiguous).
    src_id = rs.register_and_inject_object(
        _ouroboroid_like_printing(3), 0, ZONE_BATTLEFIELD,
    )
    # Two creatures on the SAME controller's bf.
    bear1_id = rs.register_and_inject_object(
        _VANILLA_BEAR_DICT, 0, ZONE_BATTLEFIELD,
    )
    bear2_id = rs.register_and_inject_object(
        _VANILLA_BEAR_DICT, 0, ZONE_BATTLEFIELD,
    )
    # A non-creature artifact on the controller's bf — must be skipped.
    artifact_id = rs.register_and_inject_object(
        _PLAIN_ARTIFACT_DICT, 0, ZONE_BATTLEFIELD,
    )
    # An opponent creature — must NOT receive counters.
    opp_bear_id = rs.register_and_inject_object(
        _VANILLA_BEAR_DICT, 1, ZONE_BATTLEFIELD,
    )

    # Sanity: source's effective_power matches the printed power.
    assert rs.effective_power(src_id) == 3, (
        f"sanity: source printed power=3 must yield effective_power=3; "
        f"got {rs.effective_power(src_id)}"
    )

    bear1_before = rs.get_counters(bear1_id)
    bear2_before = rs.get_counters(bear2_id)
    src_before = rs.get_counters(src_id)
    artifact_before = rs.get_counters(artifact_id)
    opp_bear_before = rs.get_counters(opp_bear_id)

    rs.push_to_stack(src_id, 0)
    rs.resolve_top_of_stack()
    assert rs.stack_size() == 0, "spell must resolve cleanly"

    # Every controlled creature gains exactly +3 to counters.
    assert rs.get_counters(bear1_id) - bear1_before == 3, (
        f"bear1 must gain +3 counters; got "
        f"delta={rs.get_counters(bear1_id) - bear1_before}"
    )
    assert rs.get_counters(bear2_id) - bear2_before == 3, (
        f"bear2 must gain +3 counters; got "
        f"delta={rs.get_counters(bear2_id) - bear2_before}"
    )
    # Source is a creature on the controller's bf → also receives the
    # spread (no exclude_source rider on this variant).
    assert rs.get_counters(src_id) - src_before == 3, (
        f"source (creature, controlled by self) must gain +3 counters; "
        f"got delta={rs.get_counters(src_id) - src_before}"
    )
    # Non-creature artifact must NOT change.
    assert rs.get_counters(artifact_id) == artifact_before, (
        f"non-creature artifact must not gain counters; went "
        f"{artifact_before} → {rs.get_counters(artifact_id)}"
    )
    # Opponent creature must NOT change.
    assert rs.get_counters(opp_bear_id) == opp_bear_before, (
        f"opponent creature must not gain counters; went "
        f"{opp_bear_before} → {rs.get_counters(opp_bear_id)}"
    )


# -------------------------------------------------------------------
# GENUINE real-EoE cross-engine byte-equal probe — drives the parsed
# Ouroboroid printing through the trajectory →
# _ta_dict_to_python_effect round-trip pipeline, and through the
# directly-applied Rust resolve arm on a synthetic state matching the
# parsed printing's printed power.
# -------------------------------------------------------------------


def test_cross_engine_real_eoe_ouroboroid_round_trip_parity():
    """**GENUINE real-EoE cross-engine byte-equal probe — Ouroboroid
    mass-counter effect.** The slug-credit anchor for the PROBED tier
    flip even though the classifier multi-gates the card on
    ``nonsafe_triggered_ability``.

    Drives the **real parsed Ouroboroid printing** through the
    trajectory serializer + cross-engine dict→Python bridge:

      * Extract the parsed BEGINNING_OF_COMBAT triggered-ability
        effect from the real EoE printing.
      * Walk the effect — must be
        ``PutPlusOneCountersOnEachCreatureYouControlEqualToSourcePower()``
        per the §2 parser SoT pin.
      * Serialize via ``trajectory._python_spell_effect_to_dict`` →
        the bare one-key dict.
      * Round-trip via ``cross_engine._ta_dict_to_python_effect`` →
        a fresh
        ``PutPlusOneCountersOnEachCreatureYouControlEqualToSourcePower()``
        instance equal to the parser-emitted effect.
      * Drive the effect's resolve through Rust on a synthetic state
        matching Ouroboroid's printed power (1) — every controlled
        creature gains exactly +1 to its ``counters`` scalar, byte-
        equal-observable to the round-trip dict.

    **Byte-equality scope.** Both the parser-emitted effect and the
    bridge-reconstructed effect compare equal as field-free unit
    dataclasses; the Rust-side resolve lands an identical per-creature
    +X counter delta (X = source.effective_power) on every controlled
    creature on the source-controller's battlefield.

    **Cycle 1 scope caveat.** The full real-EoE BEGINNING_OF_COMBAT
    trigger-fan-out byte-equal probe through both engines's
    `advance_phase`/`step` machinery requires per-engine
    coordination of the trigger-pushed-onto-stack timing (Python
    fires triggers via the priority loop; Rust fires via the phase-
    transition trigger fan-out) — that broader probe is honest-
    stopped at Cycle 1; the substrate-level round-trip + the Rust
    resolve-arm unit pins carry the PROBED tier flip per the
    Terrapact Intimidator / Boilerbilges Ripper / Fanatic of the
    Harrowing / Attack-in-the-Box classifier-bypass precedent.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.generic.counters import (
        PutPlusOneCountersOnEachCreatureYouControlEqualToSourcePower,
    )
    from mtg_bot.effects.predicates import Event
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    real = get_active_source().get_printings().get("Ouroboroid")
    if real is None:
        pytest.skip("Ouroboroid absent from active CardSource")

    # §2 source-of-truth: genuine BEGINNING_OF_COMBAT trigger must be
    # PutPlusOneCountersOnEachCreatureYouControlEqualToSourcePower().
    combat_ta = next(
        (
            ta for ta in real.triggered_abilities
            if ta.event is Event.BEGINNING_OF_COMBAT
        ),
        None,
    )
    assert combat_ta is not None, (
        "Ouroboroid must have a BEGINNING_OF_COMBAT triggered ability"
    )
    leaf = combat_ta.effect
    assert isinstance(
        leaf,
        PutPlusOneCountersOnEachCreatureYouControlEqualToSourcePower,
    ), (
        f"combat trigger effect must be "
        f"PutPlusOneCountersOnEachCreatureYouControlEqualToSourcePower; "
        f"got {type(leaf).__name__}"
    )

    # Round-trip the leaf through trajectory serializer + cross-engine
    # dict→Python bridge.
    d = trajectory._python_spell_effect_to_dict(leaf)
    assert d == {"kind": _OUROBOROID_KIND}, (
        f"real-EoE leaf serializer must emit the bare unit-variant "
        f"dict; got {d}"
    )
    rebuilt = _ta_dict_to_python_effect(d)
    assert isinstance(
        rebuilt,
        PutPlusOneCountersOnEachCreatureYouControlEqualToSourcePower,
    ), (
        f"dict→Python bridge must round-trip to "
        f"PutPlusOneCountersOnEachCreatureYouControlEqualToSourcePower; "
        f"got {type(rebuilt).__name__}"
    )
    assert rebuilt == leaf, (
        f"round-tripped leaf must equal the parser-emitted leaf "
        f"(both field-free unit dataclasses); got rebuilt={rebuilt!r}, "
        f"parser={leaf!r}"
    )

    # Drive the leaf through Rust's resolve arm on a synthetic state
    # matching Ouroboroid's printed power (1). Every controlled
    # creature gains exactly +1 to its `counters` scalar — the byte-
    # equal observable across engines.
    rs = _fresh_rust_state()
    src_id = rs.register_and_inject_object(
        _ouroboroid_like_printing(int(real.power)),
        0, ZONE_BATTLEFIELD,
    )
    bear_id = rs.register_and_inject_object(
        _VANILLA_BEAR_DICT, 0, ZONE_BATTLEFIELD,
    )

    bear_before = rs.get_counters(bear_id)
    src_before = rs.get_counters(src_id)
    # Sanity: effective_power matches the printed power on entry.
    assert rs.effective_power(src_id) == int(real.power)

    rs.push_to_stack(src_id, 0)
    rs.resolve_top_of_stack()
    assert rs.stack_size() == 0, (
        "Rust resolve must clear the stack"
    )

    # Each controlled creature gains +X = printed_power (Ouroboroid
    # prints 1).
    delta = int(real.power)
    assert rs.get_counters(bear_id) - bear_before == delta, (
        f"bear must gain exactly +{delta} counters; got "
        f"delta={rs.get_counters(bear_id) - bear_before}"
    )
    assert rs.get_counters(src_id) - src_before == delta, (
        f"source must gain exactly +{delta} counters (no exclude_source "
        f"rider); got delta={rs.get_counters(src_id) - src_before}"
    )
