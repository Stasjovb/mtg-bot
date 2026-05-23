"""Cross-engine parity probes for The Endstone.

**The Endstone Cycle 1 closure (2026-05-23).** ``{7}`` Legendary
Artifact (Edge of Eternities — EoE, set code ``eoe``, in the active
``OracleParserCardSource``). Oracle text::

    Whenever you play a land or cast a spell, draw a card.
    At the beginning of your end step, your life total becomes half
    your starting life total, rounded up.

The ``effect_uncovered`` + ``nonsafe_triggered_ability`` multi-gate
classifier blocker — the missing Effect class is
``SetLifeToHalfStartingRoundedUp`` (``effects/generic/life.py:51``).

The single-cycle substrate that makes this slice possible:

  1. **Rust ``Effect::SetLifeToHalfStartingRoundedUp``** — unit (no
     fields) variant in ``rust/src/cards.rs`` (the
     ``UntapTargetOtherPermanent`` / ``TapAnotherTargetCreature`` /
     ``ReturnAllCreaturesFromYourGraveyardToBattlefield`` unit-variant
     idiom), parse arm (``parse_effect``; round-trips the bare
     ``{"kind": "set_life_to_half_starting_rounded_up"}`` dict
     shape), ``to_pydict`` arm (emits ONLY ``kind``), and resolve
     arm in ``rust/src/state_ops_resolve.rs`` that locates the
     source-controller (5-zone walk) and sets that player's life to
     ``(STARTING_LIFE + 1) / 2`` (STARTING_LIFE constant is 20 on
     Rust, mirroring Python's ``Player.starting_life: int = 20``
     default; the standard 20-life format produces ``life == 10``
     post-resolve).
  2. **Bridge dict→Python arm** in
     ``cross_engine.py::_ta_dict_to_python_effect`` reconstructs the
     Python ``SetLifeToHalfStartingRoundedUp()`` from the one-key
     dict shape.
  3. **Coverage 1:1 identity mapping.** The new Rust variant name
     matches the Python class name 1:1, so
     ``effect_coverage.covered_python_class_set()`` auto-includes
     ``SetLifeToHalfStartingRoundedUp`` — closes the
     ``effect_uncovered`` classifier gate at the covered-set level.

**Multi-gated card; classifier multi-gate state stays True after the
cycle.** Per the round-58 subsystem-attribution classifier, The
Endstone is multi-gated on
``effect_uncovered + nonsafe_triggered_ability``. The cycle closes
the ``effect_uncovered`` gate (the
``SetLifeToHalfStartingRoundedUp`` Python class flips from
``missing_effect_classes`` to covered), but the
``nonsafe_triggered_ability`` gate KEEPS the card multi-gated at the
classifier level. The trajectory safe-trigger admit gate
(``parity/trajectory.py::_python_ta_to_safe_dict``) is INTENTIONALLY
NOT widened — the safe-trigger gate's event whitelist
(ENTERS/DIES/ATTACKS/BECOMES_TAPPED) does not admit The Endstone's
``BEGINNING_OF_END_STEP`` / ``PLAYS_LAND`` / ``IS_CAST`` triggers,
and widening it is a production-deck-bench admit-set concern
distinct from per-card real-EoE parity probes. **The card DOES move
to PROBED tier through the dedicated per-card real-EoE byte-equal
cross-engine probe below**, the same precedent as
Boilerbilges Ripper / Comet Crawler / Friendly Teddy / Genemorph
Imago / Fanatic of the Harrowing.

**Per-card parity probe path (NOT spell-card-bridge admit set).**
The Endstone is an Artifact (non-spell-resolved), not a non-creature
spell admitted through the spell-card-bridge admit set
(``trajectory.py::_python_spell_effect_to_dict`` + its §2 teeth).
The cross-engine probe uses the per-card dedicated parity-test
module convention (cf. ``test_friendly_teddy_parity.py``,
``test_genemorph_imago_parity.py``), driving the parsed The Endstone
printing through both engines on a shared shape and pinning
byte-equal observables.

**Probe drive — BEGINNING_OF_END_STEP.** The Endstone has THREE
triggered abilities: ``PLAYS_LAND``, ``IS_CAST`` (both
``DrawCards(amount=1)``), and ``BEGINNING_OF_END_STEP``
(``SetLifeToHalfStartingRoundedUp``). This cycle's Effect-class
substrate is exercised by the end-step trigger only — the
``DrawCards`` half is already covered. The probe drives both
engines to PHASE_END_STEP via ``advance_phase`` from
POSTCOMBAT_MAIN (which fires the ``BEGINNING_OF_END_STEP``
dispatch_event on the Rust side; Python's equivalent fires via the
``run_beginning_of_end_step_triggers`` path on phase entry).

**Probe drive — pre-seated lower life.** Setting life to 10 from
the default starting 20 is a NO-OP on the field view (the bare
``set_life_to_half_starting_rounded_up`` resolve writes 10, the
initial life IS 20, so the observable equality between engines is
trivially zero-deltaed at the default). The probe pre-seats BOTH
engines at p0.life = 5 / p1.life = 5 so the resolve has a real
deliverable to mirror byte-equal: only p0's life becomes 10 (the
source-controller); p1's life stays at 5.

**Observable byte-equality scope.** The harness's
``_build_field_view`` 8-tuple per zone object (printing_name,
tapped, summoning_sick, damage, net_counters, attached_to,
controller_id, id) is unaffected by life totals (life isn't in the
per-object 8-tuple). The probe pins life-total equality directly
(``py.players[0].life == rs.get_life(0) == 10``, ``...[1] == 5``)
AND a full-field-view ``compare_fields == []`` over the harness's
zone-state view (every zone, both players).

Coverage:

  - Parser SoT pin: parsed The Endstone printing has the
    BEGINNING_OF_END_STEP triggered ability with effect
    ``SetLifeToHalfStartingRoundedUp()``.
  - Bridge dict→Python round-trip: ``_ta_dict_to_python_effect``
    rebuilds a default-constructed ``SetLifeToHalfStartingRoundedUp``
    from the one-key dict.
  - Rust ``Effect::SetLifeToHalfStartingRoundedUp`` parse +
    to_pydict round-trip via ``register_printing`` (etb_effects
    readback).
  - Rust resolve-arm unit pins:
      * Basic life-setting from below-half (p0.life = 5 → 10).
      * Life-setting from above-half (p0.life = 18 → 10).
      * Source-controller-only — p1's life unchanged.
  - Effect-coverage class pin: ``SetLifeToHalfStartingRoundedUp`` is
    in the covered-by-rust set (the new Rust enum variant maps 1:1
    to the Python class via the identity rule in
    ``effect_coverage.map_rust_to_python``).
  - **GENUINE real-EoE cross-engine byte-equal probe** — drives the
    parsed The Endstone printing through Python + Rust engines:
      * p0's bf: real The Endstone (pre-seated, no cast path so no
        spurious DrawCards triggers fire during setup).
      * p0.life = 5, p1.life = 5 pre-seated on BOTH.
      * Both engines advance to PHASE_END_STEP; the end-step trigger
        fires + resolves on BOTH.
      * Post-resolve: p0.life == 10 (source-controller life raised
        to half-starting), p1.life == 5 (untouched).
      * ``compare_fields`` over the WHOLE field view = []
        (byte-equal zones + battlefield + everything).
"""

from __future__ import annotations

import importlib
import importlib.util
import pathlib
import sys

import pytest


def _require_engine():
    if importlib.util.find_spec("mtg_bot_engine") is None:
        pytest.skip("mtg_bot_engine PyO3 extension not installed")


_rust_skip = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


ZONE_HAND = 0
ZONE_LIBRARY = 1
ZONE_BATTLEFIELD = 2
ZONE_GRAVEYARD = 3

# Phase constants mirroring rust/src/state_ops_steps.rs:96-115.
PHASE_POSTCOMBAT_MAIN = 9
PHASE_END_STEP = 10


# ---------------------------------------------------------------------------
# (1) Parser SoT — The Endstone is parser-claimed and emits the
# expected BEGINNING_OF_END_STEP triggered ability + the
# SetLifeToHalfStartingRoundedUp effect.
# ---------------------------------------------------------------------------


def test_real_endstone_end_step_trigger_is_set_life_to_half():
    """**Verify-first.** The live parser maps The Endstone's
    end-step trigger to ``SetLifeToHalfStartingRoundedUp()`` (a
    parameterless frozen dataclass). Pin the shape so a parser
    drift is caught here, not silently downstream in the cross-
    engine probe. Also pins the printing surface (cost, supertype,
    type, the OTHER two triggered abilities)."""
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.generic.life import SetLifeToHalfStartingRoundedUp
    from mtg_bot.effects.predicates import Event

    p = get_active_source().get_printings().get("The Endstone")
    if p is None:
        pytest.skip("The Endstone absent from active CardSource")
    assert "Artifact" in p.card_types
    assert "Legendary" in p.supertypes
    assert p.mana_cost_str == "{7}"
    # Three triggered abilities: PLAYS_LAND + IS_CAST (both DrawCards)
    # + BEGINNING_OF_END_STEP (SetLifeToHalfStartingRoundedUp).
    assert len(p.triggered_abilities) == 3, (
        f"The Endstone must have exactly 3 triggered abilities; "
        f"got {len(p.triggered_abilities)}"
    )
    end_step_tas = [
        ta for ta in p.triggered_abilities
        if ta.event is Event.BEGINNING_OF_END_STEP
    ]
    assert len(end_step_tas) == 1, (
        f"The Endstone must have exactly 1 BEGINNING_OF_END_STEP "
        f"triggered ability; got {len(end_step_tas)}"
    )
    ta = end_step_tas[0]
    assert isinstance(ta.effect, SetLifeToHalfStartingRoundedUp), (
        f"end-step trigger effect must be "
        f"SetLifeToHalfStartingRoundedUp; got {type(ta.effect).__name__}"
    )
    # Field-free unit dataclass — equality with a fresh
    # default-constructed instance.
    assert ta.effect == SetLifeToHalfStartingRoundedUp()


# ---------------------------------------------------------------------------
# (2) Serializer round-trip — dict → Python class. The bridge arm is
# the Rust→Python translation lever; without it, a Rust to_pydict
# emission could not rebuild the Python class.
# ---------------------------------------------------------------------------


def test_endstone_effect_dict_to_python_round_trip():
    """Rust-shape dict → Python ``SetLifeToHalfStartingRoundedUp`` via
    ``_ta_dict_to_python_effect`` reconstructs a default-constructed
    instance. Bridge arm is the lever flip — without it, a
    Rust→Python triggered-ability translation would raise on the
    unknown kind."""
    from mtg_bot.effects.generic.life import SetLifeToHalfStartingRoundedUp
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    d = {"kind": "set_life_to_half_starting_rounded_up"}
    rebuilt = _ta_dict_to_python_effect(d)
    assert isinstance(rebuilt, SetLifeToHalfStartingRoundedUp), (
        f"dict→Python bridge must round-trip to "
        f"SetLifeToHalfStartingRoundedUp; got {type(rebuilt).__name__}"
    )
    # Field-free unit dataclass; equality with a fresh instance.
    assert rebuilt == SetLifeToHalfStartingRoundedUp()


@_rust_skip
def test_endstone_rust_effect_to_pydict_round_trip():
    """Rust ``Effect::SetLifeToHalfStartingRoundedUp`` → dict emits
    the expected one-key shape. Drives the round-trip through
    ``Registry.register_printing`` (the parse path) +
    ``get_printing_etb_effects`` (the ``effect_to_pydict``
    readback). Using ``etb_effects`` instead of
    ``triggered_abilities`` because the Registry exposes an
    ``effect_to_pydict``-walking getter for the former but not the
    latter; the parse + serialize arms being exercised are identical
    (both walk ``parse_effect`` then ``effect_to_pydict`` on the
    same ``Effect`` variant)."""
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Endstone Round-trip",
            "card_types": ["Artifact"],
            "supertypes": ["Legendary"],
            "mana_cost": {"generic": 7},
            "etb_effects": [
                {"kind": "set_life_to_half_starting_rounded_up"},
            ],
        }
    )
    effs = reg.get_printing_etb_effects(pid)
    assert len(effs) == 1, f"expected 1 etb_effect, got {len(effs)}"
    eff = effs[0]
    assert eff["kind"] == "set_life_to_half_starting_rounded_up"
    # Field-free unit variant — no other keys.
    assert set(eff.keys()) == {"kind"}, (
        f"unit-variant to_pydict must emit ONLY 'kind'; got keys "
        f"{sorted(eff.keys())}"
    )


# ---------------------------------------------------------------------------
# (3) Rust resolve-arm unit pins — basic life-setting + source-
# controller-only + above-half / below-half symmetry.
# ---------------------------------------------------------------------------


def _fresh_rust_state():
    import mtg_bot_engine

    return mtg_bot_engine.make_synthetic_state(0, 0, 0)


def _inject_endstone_carrier(rs, owner: int = 0) -> int:
    """Inject a synthetic The-Endstone-shape Artifact on owner's
    battlefield carrying the BEGINNING_OF_END_STEP trigger →
    SetLifeToHalfStartingRoundedUp effect. Returns the object id.

    Mirrors the parsed Python printing's relevant triggered ability
    only — the two DrawCards triggers are unrelated to the
    SetLifeToHalfStartingRoundedUp substrate and are exercised
    separately by the existing DrawCards arm.
    """
    return rs.register_and_inject_object(
        {
            "name": "The Endstone Carrier",
            "card_types": ["Artifact"],
            "supertypes": ["Legendary"],
            "mana_cost": {"generic": 7},
            "triggered_abilities": [
                {
                    "event": "beginning_of_end_step",
                    "predicate": {"kind": "controlled_by_you"},
                    "effect": {
                        "kind": "set_life_to_half_starting_rounded_up",
                    },
                },
            ],
        },
        owner,
        ZONE_BATTLEFIELD,
    )


@_rust_skip
def test_rust_resolve_set_life_to_half_from_below_half_raises_to_10():
    """Source-controller's life starts at 5 (below 10 = half
    starting). The end-step trigger fires and the resolve arm
    raises p0's life to 10. p1's life is unchanged."""
    rs = _fresh_rust_state()
    rs.set_life(0, 5)
    rs.set_life(1, 5)
    _inject_endstone_carrier(rs, owner=0)
    # Advance from POSTCOMBAT_MAIN to END_STEP — this fires the
    # ``dispatch_event(BeginningOfEndStep)`` which pushes the
    # trigger onto the stack.
    rs.set_phase(PHASE_POSTCOMBAT_MAIN)
    rs.advance_phase()
    assert rs.step == "END", (
        f"after advance_phase from POSTCOMBAT_MAIN, step must be "
        f"END; got {rs.step}"
    )
    assert rs.stack_size() == 1, (
        f"BeginningOfEndStep dispatch must push exactly one trigger; "
        f"got stack_size={rs.stack_size()}"
    )
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
        rs.apply_sbas_until_quiescent()
    assert rs.life_totals[0] == 10, (
        f"source-controller's life must be set to 10 "
        f"(half of starting 20, rounded up); got {rs.life_totals[0]}"
    )
    assert rs.life_totals[1] == 5, (
        f"non-source-controller's life must be unchanged at 5; "
        f"got {rs.life_totals[1]}"
    )


@_rust_skip
def test_rust_resolve_set_life_to_half_from_above_half_lowers_to_10():
    """Source-controller's life starts at 18 (above 10). The
    end-step trigger fires and the resolve arm LOWERS p0's life to
    10 — the effect SETS life (not ``gain_life``), so it works
    bidirectionally. p1's life is unchanged."""
    rs = _fresh_rust_state()
    rs.set_life(0, 18)
    rs.set_life(1, 18)
    _inject_endstone_carrier(rs, owner=0)
    rs.set_phase(PHASE_POSTCOMBAT_MAIN)
    rs.advance_phase()
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
        rs.apply_sbas_until_quiescent()
    assert rs.life_totals[0] == 10, (
        f"source-controller's life must be SET to 10 (effect is "
        f"set-life, not gain/lose); got {rs.life_totals[0]}"
    )
    assert rs.life_totals[1] == 18, (
        f"non-source-controller's life must be unchanged at 18; "
        f"got {rs.life_totals[1]}"
    )


@_rust_skip
def test_rust_resolve_direct_apply_via_etb_on_p1_carrier_sets_p1_life():
    """The carrier is on p1's bf with the effect on its ``etb_effects``
    list (direct apply path, bypassing the trigger machinery and the
    Controlled(YOU)-vs-active-player gating). The resolve arm walks
    the 5-zone source-locator and finds the carrier on p1's bf →
    sets p1's life to 10. p0's life is unchanged.

    Pins the source-controller resolution (5-zone walk) on its own
    — without it the resolve arm would either default to
    active_player or to a hardcoded p0. The trigger-driven path on
    the OTHER tests (carrier on p0, source-controller=p0) covers the
    Controlled(YOU)+active_player gating; this test isolates the
    resolve arm's source-controller-from-bf-walk gate.
    """
    rs = _fresh_rust_state()
    rs.set_life(0, 5)
    rs.set_life(1, 5)
    # Carrier with the effect on etb_effects (no trigger gating).
    rs.register_and_inject_object(
        {
            "name": "Endstone Direct-Apply Carrier",
            "card_types": ["Artifact"],
            "supertypes": ["Legendary"],
            "mana_cost": {"generic": 7},
            "etb_effects": [
                {"kind": "set_life_to_half_starting_rounded_up"},
            ],
        },
        1,  # owner = p1 → controller = p1
        ZONE_HAND,
    )
    # Find the carrier and move bf → triggers etb dispatch.
    # Easiest: register on hand then move_object to bf to fire ETB.
    hand_ids = [e["id"] for e in rs.hand_snapshot(1)]
    assert len(hand_ids) == 1
    carrier_id = hand_ids[0]
    rs.move_object(carrier_id, ZONE_BATTLEFIELD, 1)
    rs.apply_sbas_until_quiescent()
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
        rs.apply_sbas_until_quiescent()
    assert rs.life_totals[1] == 10, (
        f"source-controller p1's life must be set to 10; "
        f"got {rs.life_totals[1]}"
    )
    assert rs.life_totals[0] == 5, (
        f"non-source-controller p0's life must be unchanged at 5; "
        f"got {rs.life_totals[0]}"
    )


# ---------------------------------------------------------------------------
# (4) Effect-coverage class pin — the new Rust variant makes the
# Python class covered via the 1:1 identity-mapping rule.
# ---------------------------------------------------------------------------


def test_set_life_to_half_starting_rounded_up_class_covered_by_rust():
    """``SetLifeToHalfStartingRoundedUp`` must be in the covered-by-
    rust set — the Rust ``Effect::SetLifeToHalfStartingRoundedUp``
    variant declaration makes ``covered_python_class_set()`` include
    it via the 1:1 identity-mapping rule in
    ``effect_coverage.map_rust_to_python``. This is the §2 covered-
    set tooth (parity-doc / coverage-script "covered" alignment)
    AND the closure of the classifier's ``effect_uncovered`` gate
    for The Endstone."""
    from mtg_bot.parity.effect_coverage import (
        collect_python_effect_vocab,
        collect_rust_effect_variants,
        covered_python_class_set,
    )

    py_classes, _examples, _n = collect_python_effect_vocab()
    assert "SetLifeToHalfStartingRoundedUp" in py_classes, (
        "The Endstone must surface SetLifeToHalfStartingRoundedUp in "
        "the parser-walked Python effect vocab"
    )
    rust_variants = collect_rust_effect_variants()
    assert "SetLifeToHalfStartingRoundedUp" in rust_variants, (
        "the new Rust Effect variant must be discoverable by the "
        "cards.rs text parser"
    )
    covered = covered_python_class_set()
    assert "SetLifeToHalfStartingRoundedUp" in covered, (
        "the new Rust variant pairs 1:1 with the parser-claimed "
        "Python class (no override / RUST_AHEAD_OF_POOL allowlist "
        "needed)"
    )


def test_endstone_classifier_effect_uncovered_gate_closed():
    """The round-58 subsystem-attribution classifier should report
    The Endstone with an EMPTY ``missing_effect_classes`` list
    after this cycle — proof the ``effect_uncovered`` gate is closed
    at the classifier level. The card stays multi-gated overall
    because ``nonsafe_triggered_ability`` is still in ``gates``;
    this test pins the effect-class closure specifically.

    NB: this is the canonical observable for "the Cycle 1
    effect_uncovered closure landed". The
    ``nonsafe_triggered_ability`` gate is deliberately NOT closed
    this cycle (no widen of ``_python_ta_to_safe_dict``), so the
    classifier's ``multi_gated`` flag stays ``True``."""
    repo_root = pathlib.Path(__file__).resolve().parent.parent
    scripts_dir = repo_root / "scripts"
    inserted = False
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
        inserted = True
    try:
        from scout_r58_subsystem_attribution import subsystem_attribution
        attr = subsystem_attribution()
    finally:
        if inserted:
            sys.path.remove(str(scripts_dir))
    row = attr["cards"].get("The Endstone")
    if row is None:
        pytest.skip("The Endstone absent from classifier output")
    # effect_uncovered gate must be CLOSED at the effect-class level:
    # the missing list should now be empty.
    assert row["missing_effect_classes"] == [], (
        f"Cycle 1 closure expected `missing_effect_classes == []`; "
        f"got {row['missing_effect_classes']}"
    )
    # But the card is still multi-gated overall (the
    # nonsafe_triggered_ability gate hasn't been widened this cycle).
    assert "nonsafe_triggered_ability" in row["gates"], (
        f"Cycle 1 intentionally keeps the nonsafe_triggered_ability "
        f"gate active; classifier `gates` = {row['gates']}"
    )


# ---------------------------------------------------------------------------
# (5) GENUINE real-EoE cross-engine byte-equal probe — drives the
# parsed The Endstone printing through BOTH engines, advances to
# PHASE_END_STEP, and pins byte-equal full-field-view + life-total
# equality.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def parity_smoke():
    """Load ``scripts/parity_smoke.py`` as a module so the probe can
    call ``_build_field_view`` for the full cross-engine
    byte-equality compare — same fixture shape as
    ``tests/test_genemorph_imago_parity.py``,
    ``tests/test_friendly_teddy_parity.py``, etc."""
    repo_root = pathlib.Path(__file__).resolve().parent.parent
    script_path = repo_root / "scripts" / "parity_smoke.py"
    spec = importlib.util.spec_from_file_location(
        "parity_smoke", script_path
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["parity_smoke"] = mod
    spec.loader.exec_module(mod)
    return mod


@_rust_skip
def test_cross_engine_real_eoe_endstone_end_step_set_life_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine byte-equal probe — The
    Endstone end-step SetLifeToHalfStartingRoundedUp.**

    Drives the **real parsed The Endstone printing** through both
    engines:
      - p0's bf: real The Endstone (pre-seated, no cast path → no
        spurious DrawCards triggers fire during seeding because the
        IS_CAST + PLAYS_LAND triggers fire on cast / play_land
        events, neither of which fire during the seed).
      - p0.life = 5, p1.life = 5 pre-seated on BOTH (gives the
        end-step trigger a non-trivial deliverable to mirror — life
        changes from 5 to 10 on p0 only).
      - Both engines: advance to PHASE_END_STEP via the canonical
        phase-advance path that fires the
        ``BEGINNING_OF_END_STEP`` event dispatch.
      - Post-resolve on BOTH: p0.life == 10 (source-controller
        life raised to half-starting), p1.life == 5 (untouched).

    **Byte-equality scope.** The full ``compare_fields`` over the
    harness's field view is empty — every zone state agrees
    byte-equal across engines. Life totals are pinned directly
    (life isn't in the per-object field-view 8-tuple).
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.game import Zone
    from mtg_bot.turn import (
        state_based_actions as py_sba,
        run_beginning_of_end_step_triggers,
        Step,
    )
    from mtg_bot.effects.predicates import Event
    from mtg_bot.effects.generic.life import SetLifeToHalfStartingRoundedUp

    real = get_active_source().get_printings().get("The Endstone")
    if real is None:
        pytest.skip("The Endstone absent from active CardSource")

    # §2 source-of-truth: genuine BEGINNING_OF_END_STEP trigger
    # must be SetLifeToHalfStartingRoundedUp.
    end_step_ta = next(
        (
            ta for ta in real.triggered_abilities
            if ta.event is Event.BEGINNING_OF_END_STEP
        ),
        None,
    )
    assert end_step_ta is not None, (
        "The Endstone must have a BEGINNING_OF_END_STEP triggered "
        "ability"
    )
    assert isinstance(
        end_step_ta.effect, SetLifeToHalfStartingRoundedUp
    ), (
        f"end-step trigger must be SetLifeToHalfStartingRoundedUp; "
        f"got {type(end_step_ta.effect).__name__}"
    )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2

    # --- Python: real The Endstone pre-seated on p0's bf. Lower
    # both players' life to 5 so the end-step trigger has a real
    # observable to mirror.
    py_endstone = py.new_object(
        real, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_endstone.summoning_sick = False
    py_endstone.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_endstone)
    py.players[0].life = 5
    py.players[1].life = 5
    # No agent setup needed — SetLifeToHalfStartingRoundedUp has no
    # PendingDecision.
    py.players[0].agent = None
    py.players[1].agent = None

    # --- Rust: bridge a same-shape carrier onto p0's bf carrying
    # the end-step trigger only (the IS_CAST/PLAYS_LAND
    # `Controlled(YOU)` triggers are unrelated to this Cycle 1
    # substrate and are exercised separately by the DrawCards
    # bridge arm). The carrier's effect dict shape mirrors what
    # Python's bridge dict→Python arm round-trips.
    rs_endstone = rs.register_and_inject_object(
        {
            "name": "The Endstone",
            "card_types": list(real.card_types),
            "supertypes": list(real.supertypes),
            "mana_cost": {"generic": 7},
            "triggered_abilities": [
                {
                    "event": "beginning_of_end_step",
                    "predicate": {"kind": "controlled_by_you"},
                    "effect": {
                        "kind": "set_life_to_half_starting_rounded_up",
                    },
                },
            ],
        },
        0,
        ZB,
    )
    rs.set_life(0, 5)
    rs.set_life(1, 5)

    # ---- Pre-trigger sanity: nothing on either stack. The seed
    # didn't fire any spurious triggers.
    assert rs.stack_size() == 0 and len(py.stack) == 0

    # ---- Fire BEGINNING_OF_END_STEP on BOTH engines.
    #
    # **Rust:** advance from POSTCOMBAT_MAIN to END_STEP — this
    # fires ``dispatch_event(BeginningOfEndStep)`` which scans the
    # bf for matching predicate-style triggers and pushes them.
    rs.set_phase(PHASE_POSTCOMBAT_MAIN)
    rs.advance_phase()
    assert rs.step == "END", (
        f"Rust: after advance_phase, step must be END; "
        f"got {rs.step}"
    )
    assert rs.stack_size() == 1, (
        f"Rust: BeginningOfEndStep dispatch must push exactly one "
        f"trigger; got stack_size={rs.stack_size()}"
    )
    #
    # **Python:** ``run_beginning_of_end_step_triggers`` is the
    # canonical end-step trigger dispatcher (mirror of Rust's
    # ``dispatch_event(BeginningOfEndStep)``). It walks the
    # battlefield, matches BEGINNING_OF_END_STEP triggers under the
    # active-player Controlled(YOU) predicate, and pushes them to
    # the stack.
    py.active_player_idx = 0
    # Mirror Rust's phase transition: set Python's step to END so
    # the field-view step/phase comparison agrees byte-equal.
    py.step = Step.END
    run_beginning_of_end_step_triggers(py)
    assert len(py.stack) == 1, (
        f"Python: run_beginning_of_end_step_triggers must push "
        f"exactly one trigger; got stack_size={len(py.stack)}"
    )

    # ---- Drain both stacks. SetLifeToHalfStartingRoundedUp has
    # no PendingDecision; the resolve fires directly.
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
        rs.apply_sbas_until_quiescent()
    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)
    rs.apply_sbas()
    assert rs.stack_size() == 0 and len(py.stack) == 0

    # ---- Concrete observable: p0's life set to 10
    # (half-starting), p1's life untouched at 5.
    assert py.players[0].life == 10, (
        f"Python: source-controller p0 life must be set to 10; "
        f"got {py.players[0].life}"
    )
    assert py.players[1].life == 5, (
        f"Python: non-source-controller p1 life must be unchanged "
        f"at 5; got {py.players[1].life}"
    )
    assert rs.get_life(0) == 10, (
        f"Rust: source-controller p0 life must be set to 10; "
        f"got {rs.get_life(0)}"
    )
    assert rs.get_life(1) == 5, (
        f"Rust: non-source-controller p1 life must be unchanged "
        f"at 5; got {rs.get_life(1)}"
    )

    # ---- Full byte-equal field-view compare over the WHOLE state.
    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"The Endstone end-step SetLifeToHalfStartingRoundedUp must "
        f"be byte-equal across the WHOLE field view on BOTH engines; "
        f"diffs={diffs}"
    )
