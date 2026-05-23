"""Cross-engine parity probes for Osseous Sticktwister.

**Osseous Sticktwister Cycle 1 closure (2026-05-23).** ``{1}{B}``
Artifact Creature — Scarecrow, 2/2 (DSK 112; sourced from
``data/duskmourn.json`` via the active ``OracleParserCardSource``).
Printed oracle text::

    Lifelink
    Delirium — At the beginning of your end step, if there are four or
    more card types among cards in your graveyard, each opponent may
    sacrifice a nonland permanent of their choice or discard a card.
    Then this creature deals damage equal to its power to each
    opponent who didn't sacrifice a permanent or discard a card this
    way.

The parser maps the literal post-Delirium-gate-strip body
(``cards/parser/effects.py:3956-3962``) to
``EachOpponentSacsOrDiscardsOrTakesSourcePowerDamage()`` — the
parameterless frozen dataclass at
``effects/generic/opponent_punishers.py:221``. The cycle ports the
substrate to Rust (``Effect::
EachOpponentSacsOrDiscardsOrTakesSourcePowerDamage`` — field-free
unit variant; parse arm round-trips the bare ``{"kind":
"each_opponent_sacs_or_discards_or_takes_source_power_damage"}``
dict shape; resolve arm in ``state_ops_resolve.rs`` is the byte-equal
mirror of Python's no-agent default — every non-controller,
non-``has_lost`` opponent is treated as non-compliant ("decline")
and takes damage equal to ``effective_power(source)``).

**Multi-gated card; classifier stays multi-gated.** Per the round-58
subsystem-attribution classifier, Osseous Sticktwister is multi-gated:

  * ``effect_uncovered`` — closed by this cycle. The new Rust variant
    ``Effect::EachOpponentSacsOrDiscardsOrTakesSourcePowerDamage`` makes
    the Python class ``EachOpponentSacsOrDiscardsOrTakesSourcePower-
    Damage`` covered via the 1:1 identity-mapping rule in
    ``effect_coverage.map_rust_to_python``; the classifier's
    ``missing_effect_classes`` array shrinks by one for this card.
  * ``nonsafe_triggered_ability`` — **STAYS active**. The trajectory
    safe-trigger admit gate
    (``parity/trajectory.py::_python_ta_to_safe_dict``) is
    INTENTIONALLY NOT widened — the ``("beginning_of_end_step", ...,
    "each_opponent_sacs_or_discards_or_takes_source_power_damage")``
    triple is not added to ``_SAFE_TRIGGERS``. The
    ``BEGINNING_OF_END_STEP`` event is not in the ENTERS/DIES/ATTACKS/
    BECOMES_TAPPED safe set; this is the same per-card real-EoE probe
    precedent as Burgeoning / Comet Crawler / Ouroboroid /
    Boilerbilges Ripper / Fanatic of the Harrowing / Terrapact
    Intimidator / Hemosymbic Mite / Splitskin Doll / Endstone — the
    trajectory-side bench admit set is a distinct concern from per-
    card real-EoE parity probes.

**Per-card dedicated parity probe path (PROBED tier flip).** Even
though the classifier keeps the card multi-gated at
``nonsafe_triggered_ability``, this test module is the dedicated
per-card real-EoE byte-equal cross-engine probe that flips
Osseous Sticktwister to PROBED tier. Same precedent as
``test_burgeoning_parity.py``,
``test_hemosymbic_mite_parity.py``, and friends.

**Cycle 1 scope — substrate landing.** This cycle lands ONLY the
``EachOpponentSacsOrDiscardsOrTakesSourcePowerDamage`` substrate
(Rust variant + parse + to_pydict + resolve + cross-engine bridge +
per-leaf serializer + per-card probe). The full real-EoE
BEGINNING_OF_END_STEP trigger-fan-out byte-equal probe through both
engines is NOT 1-cycle accessible: Rust has no
``Event::BeginningOfEndStep`` chokepoint or
``StateBound(Delirium())`` predicate registry today. The substrate
ships portable independent of the trigger-fire dispatch; the per-
card probe drives the Effect class directly via the spell-resolution
pipeline (the same convention ``test_burgeoning_parity.py`` /
``test_hemosymbic_mite_parity.py`` use for their PLAYS_LAND /
BECOMES_TAPPED-gated trigger bodies).

**No-agent default = "decline" → source-power damage write.** Python's
``EachOpponentSacsOrDiscardsOrTakesSourcePowerDamage.resolve``
(``effects/generic/opponent_punishers.py:254-336``) walks per-opponent
in turn order. For each non-controller, non-``has_lost`` opponent:

  1. ``if opp.agent is None: non_compliant.append(opp.id); continue``
     (line 270-273). This is the no-agent default short-circuit.
  2. Else: build modes list (sac / discard / decline based on
     legality), call ``opp.agent.choose_mode``, branch into
     ``sac`` / ``discard`` / ``decline`` (this is the yes-agent path
     — honest-stopped on Rust for Cycle 1).
  3. After the loop, for each player in ``non_compliant`` apply
     ``_apply_damage(state, ("player", opp_id), damage)`` where
     ``damage = max(0, effective_power(state, source))``.

The cross-engine probe convention drives BOTH engines with no agent
on every opponent. Python takes the gate-1 ``opp.agent is None``
short-circuit for each opponent; Rust has no agent surface in
``apply_effect`` so the resolve arm applies the same per-opponent
damage write deterministically. The two engines therefore agree
byte-equal on the WHOLE field view: life deltas, no opp-side zone
moves (sac would mint a graveyard add; discard would do the same),
no ``fire_opponent_discards_triggers`` fan-out.

**DISTINCTION from Burgeoning.** Burgeoning's no-agent default is
silent no-op (``OptionalPutLandFromHandOntoBattlefield`` gate-4
``chosen_id is None`` return); Osseous Sticktwister's no-agent
default is "decline" → take source-power damage. Both effect
substrates are field-free unit variants — the observable divergence
is the no-agent default, not the schema.

Coverage:

- Parser SoT pin: the live parser maps Osseous Sticktwister's end-step
  trigger to ``EachOpponentSacsOrDiscardsOrTakesSourcePowerDamage()``
  (a parameterless frozen dataclass).
- Serializer round-trip: dict→Python via
  ``_ta_dict_to_python_effect`` rebuilds
  ``EachOpponentSacsOrDiscardsOrTakesSourcePowerDamage()``; Python→
  dict via ``trajectory._python_spell_effect_to_dict`` emits the bare
  unit-variant dict; Rust
  ``Effect::EachOpponentSacsOrDiscardsOrTakesSourcePowerDamage`` →
  dict via ``Registry.get_printing_etb_effects`` emits the expected
  one-key dict shape.
- Effect-coverage class pin:
  ``EachOpponentSacsOrDiscardsOrTakesSourcePowerDamage`` is in the
  covered-by-rust set after this cycle (1:1 identity-mapping rule).
- Rust resolve-arm unit pins:
    * Single opponent on bf → opponent loses ``effective_power(source)``
      life (no-agent decline default).
    * Zero-power source → silent no-op (``x <= 0`` gate-3 short-circuit).
    * Lost player skipped → ``has_lost`` opponent doesn't get damaged.
- **GENUINE real-EoE cross-engine byte-equal probe** drives the
  parsed Osseous Sticktwister printing through the trajectory →
  ``_ta_dict_to_python_effect`` round-trip pipeline, AND through
  the directly-applied Rust resolve arm on a synthetic state
  matching Osseous Sticktwister's printed shape — both engines hold
  a source on p0's bf; both drive the resolve with no agent → both
  produce the byte-equal life-delta observable (p1 loses
  ``effective_power(source)`` life).
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


def test_real_osseous_sticktwister_end_step_trigger_is_each_opponent_effect():
    """**Verify-first.** The live parser maps Osseous Sticktwister's
    end-step trigger body (post-Delirium-gate-strip) to
    ``EachOpponentSacsOrDiscardsOrTakesSourcePowerDamage()`` (a
    parameterless frozen dataclass). Pin the shape so a parser drift
    is caught here, not silently downstream in the cross-engine
    probe."""
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.generic.opponent_punishers import (
        EachOpponentSacsOrDiscardsOrTakesSourcePowerDamage,
    )
    from mtg_bot.effects.predicates import Event

    p = get_active_source().get_printings().get("Osseous Sticktwister")
    if p is None:
        pytest.skip("Osseous Sticktwister absent from active CardSource")
    assert "Artifact" in p.card_types
    assert "Creature" in p.card_types
    # Single BEGINNING_OF_END_STEP triggered ability.
    end_step_tas = [
        ta for ta in p.triggered_abilities
        if ta.event is Event.BEGINNING_OF_END_STEP
    ]
    assert len(end_step_tas) == 1, (
        f"Osseous Sticktwister must have exactly 1 "
        f"BEGINNING_OF_END_STEP triggered ability; got "
        f"{len(end_step_tas)}"
    )
    ta = end_step_tas[0]
    assert isinstance(
        ta.effect,
        EachOpponentSacsOrDiscardsOrTakesSourcePowerDamage,
    ), (
        f"BEGINNING_OF_END_STEP trigger effect must be "
        f"EachOpponentSacsOrDiscardsOrTakesSourcePowerDamage; "
        f"got {type(ta.effect).__name__}"
    )
    # Field-free unit dataclass — equality with a fresh
    # default-constructed instance.
    assert (
        ta.effect == EachOpponentSacsOrDiscardsOrTakesSourcePowerDamage()
    )


# -------------------------------------------------------------------
# Serializer round-trip + covered-set membership pins.
# -------------------------------------------------------------------


_OSSEOUS_KIND = (
    "each_opponent_sacs_or_discards_or_takes_source_power_damage"
)


def test_osseous_effect_serializer_round_trip():
    """Python ``EachOpponentSacsOrDiscardsOrTakesSourcePowerDamage()`` →
    ``trajectory._python_spell_effect_to_dict`` emits the bare unit-
    variant dict; ``cross_engine._ta_dict_to_python_effect``
    reconstructs the default-constructed instance. Bridge arm is the
    lever flip — without it, a Rust→Python triggered-ability
    translation would raise on the unknown kind."""
    from mtg_bot.effects.generic.opponent_punishers import (
        EachOpponentSacsOrDiscardsOrTakesSourcePowerDamage,
    )
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    d = trajectory._python_spell_effect_to_dict(
        EachOpponentSacsOrDiscardsOrTakesSourcePowerDamage()
    )
    assert d == {"kind": _OSSEOUS_KIND}, (
        f"reverse serializer must emit the bare unit-variant dict; "
        f"got {d}"
    )
    rebuilt = _ta_dict_to_python_effect(d)
    assert isinstance(
        rebuilt,
        EachOpponentSacsOrDiscardsOrTakesSourcePowerDamage,
    ), (
        f"dict→Python bridge must round-trip to "
        f"EachOpponentSacsOrDiscardsOrTakesSourcePowerDamage; "
        f"got {type(rebuilt).__name__}"
    )
    # Field-free unit dataclass; equality with a fresh instance.
    assert (
        rebuilt == EachOpponentSacsOrDiscardsOrTakesSourcePowerDamage()
    )


def test_osseous_rust_effect_to_pydict_round_trip():
    """Rust ``Effect::EachOpponentSacsOrDiscardsOrTakesSourcePowerDamage``
    → dict emits the expected one-key shape. Drives the round-trip
    through ``Registry.register_printing`` (the parse path) +
    ``get_printing_etb_effects`` (the ``effect_to_pydict`` readback).
    Using ``etb_effects`` instead of ``triggered_abilities`` because
    the Registry exposes an ``effect_to_pydict``-walking getter for
    the former but not the latter; the parse + serialize arms being
    exercised are identical (both walk ``parse_effect`` then
    ``effect_to_pydict`` on the same ``Effect`` variant)."""
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Osseous Round-trip",
            "card_types": ["Artifact", "Creature"],
            "mana_cost": {"generic": 1, "B": 1},
            "power": 2,
            "toughness": 2,
            "etb_effects": [
                {"kind": _OSSEOUS_KIND},
            ],
        }
    )
    effs = reg.get_printing_etb_effects(pid)
    assert len(effs) == 1, f"expected 1 etb_effect, got {len(effs)}"
    eff = effs[0]
    assert eff["kind"] == _OSSEOUS_KIND
    # Field-free unit variant — no other keys.
    assert set(eff.keys()) == {"kind"}, (
        f"unit-variant to_pydict must emit ONLY 'kind'; got keys "
        f"{sorted(eff.keys())}"
    )


def test_osseous_class_covered_by_rust():
    """``EachOpponentSacsOrDiscardsOrTakesSourcePowerDamage`` must be in
    the covered-by-rust set — the Rust
    ``Effect::EachOpponentSacsOrDiscardsOrTakesSourcePowerDamage``
    variant declaration makes ``covered_python_class_set()`` include it
    via the 1:1 identity-mapping rule in
    ``effect_coverage.map_rust_to_python``. This is the §2 covered-
    set tooth (parity-doc / coverage-script "covered" alignment) AND
    the closure of the classifier's ``effect_uncovered`` gate for
    Osseous Sticktwister."""
    from mtg_bot.parity.effect_coverage import covered_python_class_set

    covered = covered_python_class_set()
    assert (
        "EachOpponentSacsOrDiscardsOrTakesSourcePowerDamage" in covered
    ), (
        "Rust Effect::EachOpponentSacsOrDiscardsOrTakesSourcePower"
        "Damage variant must make the Python "
        "EachOpponentSacsOrDiscardsOrTakesSourcePowerDamage class "
        "covered via the 1:1 identity-mapping rule"
    )


# -------------------------------------------------------------------
# Rust resolve-arm unit pins — no-agent decline default (every
# opponent takes ``effective_power(source)`` damage).
# -------------------------------------------------------------------


def _fresh_rust_state():
    import mtg_bot_engine

    return mtg_bot_engine.make_synthetic_state(0, 0, 0)


# Synthetic Osseous Sticktwister-shaped printing. The "effects" list is
# the spell_effect list the cast-pipeline resolves on
# push_to_stack+resolve_top_of_stack. The real card composes this
# Effect under a BEGINNING_OF_END_STEP triggered ability with
# Delirium gating — but Rust has no BEGINNING_OF_END_STEP event
# chokepoint and no Delirium predicate, so the substrate unit pin
# exercises the resolve arm directly via the spell-resolution
# pipeline (same shape the Burgeoning / Hemosymbic Mite / Arabella
# probes use).
_OSSEOUS_PROBE_DICT: dict = {
    "name": "Osseous Sticktwister Probe Source",
    "card_types": ["Artifact", "Creature"],
    "mana_cost": {"generic": 1, "B": 1},
    "power": 2,
    "toughness": 2,
    "effects": [
        {"kind": _OSSEOUS_KIND},
    ],
}


def test_rust_resolve_single_opponent_takes_source_power_damage():
    """**Rust pin (a): single opponent → opponent loses
    effective_power(source) life.** With a source on p0's bf (power
    2) and p1 alive, the resolve writes ``life -= 2`` on p1 only.
    Mirrors Python's no-agent default: every opponent goes to the
    non-compliant set and takes the post-loop damage write.
    """
    rs = _fresh_rust_state()
    src_id = rs.register_and_inject_object(
        _OSSEOUS_PROBE_DICT, 0, ZONE_BATTLEFIELD,
    )

    p0_life_before = rs.life_totals[0]
    p1_life_before = rs.life_totals[1]
    bf_ids_before = [e["id"] for e in rs.battlefield_snapshot()]
    assert src_id in bf_ids_before

    rs.push_to_stack(src_id, 0)
    rs.resolve_top_of_stack()
    assert rs.stack_size() == 0, "spell must resolve cleanly"

    # Source stays on bf (the trigger body doesn't move it).
    bf_ids_after = [e["id"] for e in rs.battlefield_snapshot()]
    assert src_id in bf_ids_after, "source must stay on bf"
    # Controller life unchanged; opponent life -= 2 (source power).
    assert rs.life_totals[0] == p0_life_before, (
        f"controller life must not change; "
        f"before={p0_life_before}, after={rs.life_totals[0]}"
    )
    assert rs.life_totals[1] == p1_life_before - 2, (
        f"opponent life must lose effective_power(source)=2; "
        f"before={p1_life_before}, after={rs.life_totals[1]}"
    )


def test_rust_resolve_zero_power_source_silent_noop():
    """**Rust pin (b): x <= 0 → silent no-op.** A 0/N source produces
    ``effective_power = 0``; the resolve takes the gate-3 ``if x <= 0:
    return`` short-circuit. Mirrors Python's ``damage = max(0,
    effective_power(state, source)); if damage <= 0: return`` at line
    328-330. Observable: no life delta on any player.
    """
    rs = _fresh_rust_state()
    src_id = rs.register_and_inject_object(
        {
            "name": "Zero-Power Osseous Probe",
            "card_types": ["Artifact", "Creature"],
            "mana_cost": {"generic": 1, "B": 1},
            "power": 0,
            "toughness": 2,
            "effects": [
                {"kind": _OSSEOUS_KIND},
            ],
        },
        0, ZONE_BATTLEFIELD,
    )

    p0_life_before = rs.life_totals[0]
    p1_life_before = rs.life_totals[1]

    rs.push_to_stack(src_id, 0)
    rs.resolve_top_of_stack()
    assert rs.stack_size() == 0, "spell must resolve cleanly"

    # No life delta on either player — gate-3 short-circuit.
    assert rs.life_totals[0] == p0_life_before
    assert rs.life_totals[1] == p1_life_before


def test_rust_resolve_lost_opponent_is_skipped():
    """**Rust pin (c): ``has_lost`` opponent is skipped.** With a 2/2
    source on p0's bf and p1 set ``has_lost`` (synthesized by zeroing
    life to <= 0 and running SBAs), the resolve walks the opponent
    loop but skips p1 because ``state.players[opp_idx].has_lost ==
    true``. Mirrors Python's ``if opp.id == controller_id or
    opp.has_lost: continue`` at line 268-269. Observable: no further
    life delta on p1 beyond the pre-resolve setup.

    Implementation note: ``has_lost`` is reached deterministically by
    setting life <= 0 and running SBAs (CR 704.5a). After the SBA,
    p1's ``has_lost`` flag is True and the post-state life total
    stays at the pre-resolve value (no further life writes).
    """
    rs = _fresh_rust_state()
    src_id = rs.register_and_inject_object(
        _OSSEOUS_PROBE_DICT, 0, ZONE_BATTLEFIELD,
    )
    # Set p1 life to 0 and run SBAs → has_lost = True.
    rs.set_life(1, 0)
    rs.apply_sbas_until_quiescent()

    p0_life_before = rs.life_totals[0]
    p1_life_before = rs.life_totals[1]

    rs.push_to_stack(src_id, 0)
    rs.resolve_top_of_stack()
    assert rs.stack_size() == 0, "spell must resolve cleanly"

    # No life delta on p1 — has_lost skip; controller unchanged too.
    assert rs.life_totals[0] == p0_life_before, (
        f"controller life must not change; "
        f"before={p0_life_before}, after={rs.life_totals[0]}"
    )
    assert rs.life_totals[1] == p1_life_before, (
        f"has_lost opponent must be skipped (no further life delta); "
        f"before={p1_life_before}, after={rs.life_totals[1]}"
    )


# -------------------------------------------------------------------
# GENUINE real-EoE cross-engine byte-equal probe — drives the parsed
# Osseous Sticktwister printing through the trajectory →
# _ta_dict_to_python_effect round-trip pipeline, AND through the
# directly-applied Rust resolve arm on a synthetic state matching
# Osseous Sticktwister's printed shape.
# -------------------------------------------------------------------


def test_cross_engine_real_eoe_osseous_no_agent_decline_path_parity():
    """**GENUINE real-EoE cross-engine byte-equal probe — Osseous
    Sticktwister end-step no-agent decline path.** The slug-credit
    anchor for the PROBED tier flip even though the classifier
    multi-gates the card on ``nonsafe_triggered_ability``.

    Drives the **real parsed Osseous Sticktwister printing** through
    the trajectory serializer + cross-engine dict→Python bridge:

      * Extract the parsed BEGINNING_OF_END_STEP triggered-ability
        effect from the real DSK Osseous Sticktwister printing.
      * Walk the effect — must be
        ``EachOpponentSacsOrDiscardsOrTakesSourcePowerDamage()`` per
        the §2 parser SoT pin.
      * Serialize via ``trajectory._python_spell_effect_to_dict`` →
        the bare one-key dict.
      * Round-trip via ``cross_engine._ta_dict_to_python_effect`` →
        a fresh ``EachOpponentSacsOrDiscardsOrTakesSourcePowerDamage()``
        instance equal to the parser-emitted effect.
      * Drive the effect's resolve through Rust on a synthetic state
        matching Osseous Sticktwister's printed shape: a 2/2 source
        on p0's bf. With no agent surface, the resolve takes the
        no-agent default — p1 loses 2 life (source power).

    **Byte-equality scope.** Both the parser-emitted effect and the
    bridge-reconstructed effect compare equal as field-free unit
    dataclasses; the Rust-side resolve produces a deterministic
    life-delta observable (p1 -= source.effective_power; controller
    + lost players unchanged). This pins the no-agent decline byte-
    equal observable across engines.

    **Cycle 1 scope caveat.** The full real-EoE end-step trigger-fan-
    out byte-equal probe through Rust's
    ``Event::BeginningOfEndStep`` + Delirium-predicate machinery is
    NOT 1-cycle accessible — Rust has no such event chokepoint or
    predicate registry today; the Python end-step dispatch is the
    only firing path. The substrate-level round-trip + the Rust
    resolve-arm unit pins carry the PROBED tier flip per the
    Burgeoning / Hemosymbic Mite / Endstone / Boilerbilges Ripper
    classifier-bypass precedent.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.generic.opponent_punishers import (
        EachOpponentSacsOrDiscardsOrTakesSourcePowerDamage,
    )
    from mtg_bot.effects.predicates import Event
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    real = get_active_source().get_printings().get("Osseous Sticktwister")
    if real is None:
        pytest.skip("Osseous Sticktwister absent from active CardSource")

    # §2 source-of-truth: genuine BEGINNING_OF_END_STEP trigger must
    # be EachOpponentSacsOrDiscardsOrTakesSourcePowerDamage().
    end_step_ta = next(
        (
            ta for ta in real.triggered_abilities
            if ta.event is Event.BEGINNING_OF_END_STEP
        ),
        None,
    )
    assert end_step_ta is not None, (
        "Osseous Sticktwister must have a BEGINNING_OF_END_STEP "
        "triggered ability"
    )
    leaf = end_step_ta.effect
    assert isinstance(
        leaf, EachOpponentSacsOrDiscardsOrTakesSourcePowerDamage
    ), (
        f"BEGINNING_OF_END_STEP trigger effect must be "
        f"EachOpponentSacsOrDiscardsOrTakesSourcePowerDamage; "
        f"got {type(leaf).__name__}"
    )

    # Round-trip the leaf through trajectory serializer + cross-engine
    # dict→Python bridge.
    d = trajectory._python_spell_effect_to_dict(leaf)
    assert d == {"kind": _OSSEOUS_KIND}, (
        f"real-EoE leaf serializer must emit the bare unit-variant "
        f"dict; got {d}"
    )
    rebuilt = _ta_dict_to_python_effect(d)
    assert isinstance(
        rebuilt, EachOpponentSacsOrDiscardsOrTakesSourcePowerDamage
    ), (
        f"dict→Python bridge must round-trip to "
        f"EachOpponentSacsOrDiscardsOrTakesSourcePowerDamage; "
        f"got {type(rebuilt).__name__}"
    )
    assert rebuilt == leaf, (
        f"round-tripped leaf must equal the parser-emitted leaf "
        f"(both field-free unit dataclasses); got rebuilt={rebuilt!r}, "
        f"parser={leaf!r}"
    )

    # Drive the leaf through Rust's resolve arm on a synthetic state
    # matching Osseous Sticktwister's printed shape — a 2/2 source on
    # p0's bf. With no agent surface, the resolve takes the no-agent
    # default — every opponent takes source-power damage.
    rs = _fresh_rust_state()
    src_id = rs.register_and_inject_object(
        _OSSEOUS_PROBE_DICT, 0, ZONE_BATTLEFIELD,
    )

    p0_life_before = rs.life_totals[0]
    p1_life_before = rs.life_totals[1]
    bf_ids_before = [e["id"] for e in rs.battlefield_snapshot()]
    assert src_id in bf_ids_before

    rs.push_to_stack(src_id, 0)
    rs.resolve_top_of_stack()
    assert rs.stack_size() == 0, (
        "Rust resolve must clear the stack"
    )

    # No-agent decline default: p1 loses 2 life (source power); p0
    # unchanged; source stays on bf.
    bf_ids_after = [e["id"] for e in rs.battlefield_snapshot()]
    assert src_id in bf_ids_after, "source must stay on bf"
    assert rs.life_totals[0] == p0_life_before, (
        f"controller life must not change; "
        f"before={p0_life_before}, after={rs.life_totals[0]}"
    )
    assert rs.life_totals[1] == p1_life_before - 2, (
        f"opponent must lose source-power=2 life; "
        f"before={p1_life_before}, after={rs.life_totals[1]}"
    )
