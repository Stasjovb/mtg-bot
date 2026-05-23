"""Genemorph Imago Cycle 1 — `SetBasePTConditionalUntilEOT` Rust
substrate close + per-card cross-engine byte-equal probe.

Genemorph Imago is a {G}{U} Creature — Insect Druid (1/3) with
``flying`` whose landfall trigger conditionally sets the target
creature's BASE P/T (CR layer 7b) to 3/3, or 6/6 if the controller
controls six or more lands:

    "Flying. Landfall — Whenever a land you control enters, target
    creature has base power and toughness 3/3 until end of turn. If
    you control six or more lands, that creature has base power and
    toughness 6/6 until end of turn instead."

This module pins the Rust `Effect::SetBasePTConditionalUntilEOT`
variant landed in this branch + the matching cross_engine bridge arm
+ a genuine real-EoE cross-engine byte-equal probe driving the
landfall trigger end-to-end on a synthetic Rust carrier (mirroring the
Sunstar Expansionist precedent in ``test_probe_covered_unprobed_l.py``).

Test surface:

  1. Parser SoT — Genemorph Imago is parser-claimed and emits a
     ``SetBasePTConditionalUntilEOT(default_power=3,
     default_toughness=3, land_threshold=6, upgrade_power=6,
     upgrade_toughness=6)`` effect under an ENTERS+landfall trigger.

  2. Serializer round-trip — a Python ``SetBasePTConditionalUntilEOT``
     constructs the dict shape ``{"kind":
     "set_base_pt_conditional_until_eot", default_power, ...}`` and
     the cross_engine bridge translates it back identically.

  3. Rust unit pins:
       3a. <6 lands path: the default 3/3 is applied to the picked
           creature.
       3b. >=6 lands path: the upgrade 6/6 is applied.
       3c. Dead-target / no-eligible-creature fizzle.

  4. Covered-set membership — the orphan walker recognises
     ``SetBasePTConditionalUntilEOT`` as a 1:1 same-named Rust/Python
     match (parser-claimed via Genemorph Imago).

  5. **GENUINE real-EoE cross-engine probe** — drives the ACTUAL
     parsed Genemorph Imago printing on Python (with a same-side
     ``_PickFirstControlledCreatureAgent`` shim so the agent picks
     the same creature Rust picks at apply-time) and a bridged
     synthetic carrier on Rust, then plays a land to fire the landfall
     trigger. Asserts the concrete UEOT observable (effective_power /
     effective_toughness == 3/3 with sub-threshold lands) plus the
     full ``compare_fields == []`` over the whole cross-engine field
     view. CAVEAT (mirrors ``docs/POOL_PARITY.md``): Effect+bridge-
     level byte-equality on a *controlled* cross-engine state, NOT
     full-game-trajectory parity.

NO admit-set change — Genemorph Imago is a Creature, not a spell.
Per-card PROBED via the probe below.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

from mtg_bot.cards.source import get_active_source
from mtg_bot.effects.generic.pump import SetBasePTConditionalUntilEOT


_PRINTINGS = get_active_source().get_printings()


# Skip the Rust-engine probes if the extension isn't built — mirrors
# the project-wide policy for cross-engine probes.
_rust_skip = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


@pytest.fixture(scope="module")
def parity_smoke():
    """Load ``scripts/parity_smoke.py`` as a module (the field-view
    builder lives there). Identical to the established pattern in
    ``test_probe_covered_unprobed_l.py``."""
    repo_root = pathlib.Path(__file__).resolve().parent.parent
    script_path = repo_root / "scripts" / "parity_smoke.py"
    spec = importlib.util.spec_from_file_location(
        "parity_smoke", script_path
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["parity_smoke"] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# (1) Parser SoT — Genemorph Imago is parser-claimed and emits the
# expected SetBasePTConditionalUntilEOT effect under the canonical
# landfall trigger.
# ---------------------------------------------------------------------------


def test_genemorph_imago_parser_claims_card():
    assert "Genemorph Imago" in _PRINTINGS, (
        "Genemorph Imago must be parser-claimed by the active CardSource"
    )


def test_genemorph_imago_printed_attrs():
    """Pins the basic printing surface (cost, type, P/T, keywords)."""
    p = _PRINTINGS["Genemorph Imago"]
    assert p.mana_cost_str == "{G}{U}"
    assert "Creature" in p.card_types
    assert "Insect" in p.subtypes and "Druid" in p.subtypes
    assert p.power == 1
    assert p.toughness == 3
    assert "flying" in p.keywords


def test_genemorph_imago_landfall_trigger_emits_set_base_pt_conditional():
    """The parser emits exactly ONE triggered ability — the landfall
    trigger pairing the canonical
    ``And(Subject(IsLand), Controlled(YOU))`` predicate with the
    parameterized ``SetBasePTConditionalUntilEOT(3, 3, 6, 6, 6)``
    effect under ENTERS."""
    from mtg_bot.effects.predicates import (
        And, Controlled, Event, Subject, YOU,
    )
    from mtg_bot.effects.object_predicates import IsLand

    p = _PRINTINGS["Genemorph Imago"]
    assert len(p.triggered_abilities) == 1, (
        "Genemorph Imago must carry exactly one triggered ability "
        "(the landfall trigger); spurious abilities indicate parser drift"
    )
    ta = p.triggered_abilities[0]
    assert ta.event is Event.ENTERS, (
        f"landfall must dispatch on ENTERS; got {ta.event}"
    )
    pred = ta.predicate
    assert isinstance(pred, And), (
        f"landfall predicate must be And; got {type(pred).__name__}"
    )
    assert isinstance(pred.left, Subject) and isinstance(
        pred.left.inner, IsLand
    ), "left branch must be Subject(IsLand)"
    assert isinstance(pred.right, Controlled) and pred.right.by == YOU, (
        "right branch must be Controlled(by=YOU)"
    )
    eff = ta.effect
    assert isinstance(eff, SetBasePTConditionalUntilEOT), (
        f"effect must be SetBasePTConditionalUntilEOT; "
        f"got {type(eff).__name__}"
    )
    assert eff.default_power == 3
    assert eff.default_toughness == 3
    assert eff.land_threshold == 6
    assert eff.upgrade_power == 6
    assert eff.upgrade_toughness == 6


# ---------------------------------------------------------------------------
# (2) Serializer round-trip — Python class -> Rust-shape dict ->
# Python class. Validates the cross_engine bridge arm landed in this
# branch (``_ta_dict_to_python_effect`` ->
# ``set_base_pt_conditional_until_eot`` arm) round-trips a
# SetBasePTConditionalUntilEOT WITHOUT field-name drift.
# ---------------------------------------------------------------------------


def test_set_base_pt_conditional_bridge_arm_round_trip():
    """Construct the canonical Genemorph dict and verify the bridge
    arm builds the equivalent Python class. Missing fields must raise
    KeyError (mirrors the Rust ``parse_effect`` no-defaults contract)
    so a typo surfaces immediately."""
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    canonical = {
        "kind": "set_base_pt_conditional_until_eot",
        "default_power": 3,
        "default_toughness": 3,
        "land_threshold": 6,
        "upgrade_power": 6,
        "upgrade_toughness": 6,
    }
    eff = _ta_dict_to_python_effect(canonical)
    assert isinstance(eff, SetBasePTConditionalUntilEOT)
    assert eff.default_power == 3
    assert eff.default_toughness == 3
    assert eff.land_threshold == 6
    assert eff.upgrade_power == 6
    assert eff.upgrade_toughness == 6

    # Missing required field surfaces as KeyError (no silent default).
    for missing_key in (
        "default_power", "default_toughness", "land_threshold",
        "upgrade_power", "upgrade_toughness",
    ):
        partial = {k: v for k, v in canonical.items() if k != missing_key}
        with pytest.raises(KeyError):
            _ta_dict_to_python_effect(partial)


def test_set_base_pt_conditional_bridge_arm_alternate_payloads():
    """Pin that the bridge round-trips alternate parameter shapes —
    confirms the variant is parameterized over ALL five fields, not
    just the Genemorph-specific 3/3/6/6/6 numbers (so any future
    printing with different thresholds / pairs claims via the same
    Rust variant + bridge arm without code changes)."""
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    # Hypothetical "1/1 default, 5/5 upgrade at >=4 lands" shape.
    eff = _ta_dict_to_python_effect({
        "kind": "set_base_pt_conditional_until_eot",
        "default_power": 1,
        "default_toughness": 1,
        "land_threshold": 4,
        "upgrade_power": 5,
        "upgrade_toughness": 5,
    })
    assert isinstance(eff, SetBasePTConditionalUntilEOT)
    assert eff.default_power == 1
    assert eff.default_toughness == 1
    assert eff.land_threshold == 4
    assert eff.upgrade_power == 5
    assert eff.upgrade_toughness == 5


# ---------------------------------------------------------------------------
# (3) Rust unit pins — drive the new Rust variant via
# register_and_inject_object + the existing landfall-trigger pathway,
# and assert the UEOT observable on the Rust side directly. Three
# scenarios: sub-threshold (3/3), at-threshold (6/6), and dead-target
# fizzle.
# ---------------------------------------------------------------------------


@_rust_skip
def test_rust_set_base_pt_conditional_below_threshold_picks_default():
    """Sub-threshold (lands=3 < threshold=6): the picked creature
    gets base 3/3 — effective_power/toughness == 3/3 after a single
    landfall trigger resolves on the Rust side."""
    from mtg_bot.parity.cross_engine import DeckSpec, build_rust_state

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    rs = build_rust_state(spec)
    ZB = 2

    # Seat the bait Bear FIRST so it is the deterministic first-
    # creature pick on the source-controller's battlefield (the
    # Rust resolve arm scans the bf top-to-bottom for the first
    # ``card_types`` containing "Creature").
    rs_bear = rs.register_and_inject_object(
        {"name": "Bear", "card_types": ["Creature"],
         "power": 2, "toughness": 2},
        0, ZB,
    )
    # Seat the source carrying the conditional set-base-PT landfall
    # trigger on p0's bf.
    rs.register_and_inject_object(
        {
            "name": "Genemorph Imago (synthetic carrier)",
            "card_types": ["Creature"],
            "power": 1, "toughness": 3,
            "effects": [],
            "triggered_abilities": [
                {
                    "event": "enters",
                    "predicate": {
                        "kind": "and",
                        "left": {"kind": "subject_is_land"},
                        "right": {"kind": "controlled_by_you"},
                    },
                    "effect": {
                        "kind": "set_base_pt_conditional_until_eot",
                        "default_power": 3,
                        "default_toughness": 3,
                        "land_threshold": 6,
                        "upgrade_power": 6,
                        "upgrade_toughness": 6,
                    },
                }
            ],
        },
        0, ZB,
    )
    # Two pre-existing lands on p0's bf (total post-play = 3, below
    # the threshold of 6).
    for _ in range(2):
        rs.register_and_inject_object(
            {"name": "Forest", "card_types": ["Land"],
             "mana_produced": ["G"], "supertypes": ["Basic"]},
            0, ZB,
        )
    # The played Forest itself (now 3 lands on p0's bf at resolve time).
    rs_forest = rs.register_and_inject_object(
        {"name": "Forest", "card_types": ["Land"],
         "mana_produced": ["G"], "supertypes": ["Basic"]},
        0, 0,  # hand
    )
    rs.play_land(rs_forest, 0)
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()

    # Bear was 2/2 printed; sub-threshold branch sets base to 3/3.
    assert rs.effective_power(rs_bear) == 3, (
        f"sub-threshold: bear effective_power must be default=3 "
        f"(land_count=3 < land_threshold=6); got {rs.effective_power(rs_bear)}"
    )
    assert rs.effective_toughness(rs_bear) == 3, (
        f"sub-threshold: bear effective_toughness must be default=3; "
        f"got {rs.effective_toughness(rs_bear)}"
    )


@_rust_skip
def test_rust_set_base_pt_conditional_at_threshold_picks_upgrade():
    """At-threshold (lands=6 >= threshold=6): the picked creature
    gets base 6/6 — effective_power/toughness == 6/6 after the
    landfall trigger resolves on the Rust side."""
    from mtg_bot.parity.cross_engine import DeckSpec, build_rust_state

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    rs = build_rust_state(spec)
    ZB = 2

    # Bait Bear FIRST so it is the deterministic first-creature pick.
    rs_bear = rs.register_and_inject_object(
        {"name": "Bear", "card_types": ["Creature"],
         "power": 2, "toughness": 2},
        0, ZB,
    )
    rs.register_and_inject_object(
        {
            "name": "Genemorph Imago (synthetic carrier)",
            "card_types": ["Creature"],
            "power": 1, "toughness": 3,
            "effects": [],
            "triggered_abilities": [
                {
                    "event": "enters",
                    "predicate": {
                        "kind": "and",
                        "left": {"kind": "subject_is_land"},
                        "right": {"kind": "controlled_by_you"},
                    },
                    "effect": {
                        "kind": "set_base_pt_conditional_until_eot",
                        "default_power": 3,
                        "default_toughness": 3,
                        "land_threshold": 6,
                        "upgrade_power": 6,
                        "upgrade_toughness": 6,
                    },
                }
            ],
        },
        0, ZB,
    )
    # Five pre-existing lands (total post-play = 6, AT the threshold).
    for _ in range(5):
        rs.register_and_inject_object(
            {"name": "Forest", "card_types": ["Land"],
             "mana_produced": ["G"], "supertypes": ["Basic"]},
            0, ZB,
        )
    rs_forest = rs.register_and_inject_object(
        {"name": "Forest", "card_types": ["Land"],
         "mana_produced": ["G"], "supertypes": ["Basic"]},
        0, 0,
    )
    rs.play_land(rs_forest, 0)
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()

    # land_count = 6 >= threshold; upgrade branch sets base to 6/6.
    assert rs.effective_power(rs_bear) == 6, (
        f"at-threshold: bear effective_power must be upgrade=6 "
        f"(land_count=6 >= threshold=6); got {rs.effective_power(rs_bear)}"
    )
    assert rs.effective_toughness(rs_bear) == 6, (
        f"at-threshold: bear effective_toughness must be upgrade=6; "
        f"got {rs.effective_toughness(rs_bear)}"
    )


@_rust_skip
def test_rust_set_base_pt_conditional_no_eligible_creature_fizzles():
    """No creature on the source-controller's bf — the trigger
    fizzles silently (no panic, no state mutation beyond the land
    entering)."""
    from mtg_bot.parity.cross_engine import DeckSpec, build_rust_state

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    rs = build_rust_state(spec)
    ZB = 2

    # Carrier source; intentionally NOT a creature so the first-creature
    # scan finds nothing (its single triggered ability still fires when
    # a land enters under its controller's control — the trigger doesn't
    # require the source itself to be a creature).
    rs.register_and_inject_object(
        {
            "name": "Genemorph carrier (artifact)",
            "card_types": ["Artifact"],
            "effects": [],
            "triggered_abilities": [
                {
                    "event": "enters",
                    "predicate": {
                        "kind": "and",
                        "left": {"kind": "subject_is_land"},
                        "right": {"kind": "controlled_by_you"},
                    },
                    "effect": {
                        "kind": "set_base_pt_conditional_until_eot",
                        "default_power": 3,
                        "default_toughness": 3,
                        "land_threshold": 6,
                        "upgrade_power": 6,
                        "upgrade_toughness": 6,
                    },
                }
            ],
        },
        0, ZB,
    )
    # Take a snapshot of p0's life total — must be untouched.
    p0_life_before = rs.get_life(0)
    rs_forest = rs.register_and_inject_object(
        {"name": "Forest", "card_types": ["Land"],
         "mana_produced": ["G"], "supertypes": ["Basic"]},
        0, 0,
    )
    rs.play_land(rs_forest, 0)
    # Trigger fires; resolve drains cleanly with no creature target.
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()

    # No panic / no fizzle-related life change — purely observational.
    assert rs.get_life(0) == p0_life_before


# ---------------------------------------------------------------------------
# (4) Covered-set membership — the orphan walker recognises the new
# Rust variant SetBasePTConditionalUntilEOT as a 1:1 same-named match
# against the parser-claimed Python class.
# ---------------------------------------------------------------------------


def test_set_base_pt_conditional_in_covered_class_set():
    """The Python class is in the parser-emitted covered set
    (Genemorph Imago claims it) and the Rust variant has the SAME
    name, so the orphan walker pairs them 1:1 without an override
    or RUST_AHEAD_OF_POOL allowlist entry."""
    from mtg_bot.parity.effect_coverage import (
        collect_python_effect_vocab,
        collect_rust_effect_variants,
        covered_python_class_set,
    )

    py_classes, _examples, _n = collect_python_effect_vocab()
    assert "SetBasePTConditionalUntilEOT" in py_classes, (
        "Genemorph Imago must surface SetBasePTConditionalUntilEOT in "
        "the parser-walked Python effect vocab"
    )
    rust_variants = collect_rust_effect_variants()
    assert "SetBasePTConditionalUntilEOT" in rust_variants, (
        "the new Rust Effect variant must be discoverable by the "
        "cards.rs text parser"
    )
    covered = covered_python_class_set()
    assert "SetBasePTConditionalUntilEOT" in covered, (
        "the new Rust variant pairs 1:1 with the parser-claimed Python "
        "class (no override / RUST_AHEAD_OF_POOL allowlist needed)"
    )


# ---------------------------------------------------------------------------
# (5) GENUINE real-EoE cross-engine byte-equal probe — drives the
# ACTUAL parsed Genemorph Imago printing on Python (with a same-side
# ``_PickFirstControlledCreatureAgent`` shim) and a bridged synthetic
# carrier on Rust. After playing a Forest to fire the landfall
# trigger, asserts the concrete UEOT observable (effective_power /
# effective_toughness on the picked bait Bear) plus the full
# ``compare_fields == []`` over the whole cross-engine field view.
#
# Land-count scenario: sub-threshold (lands_at_resolve = 1, threshold
# = 6). The 3/3 default branch fires on both engines and the picked
# Bear's effective P/T moves from 2/2 to 3/3 (CR 613.4 layer 7b base-
# P/T override).
# ---------------------------------------------------------------------------


@_rust_skip
def test_cross_engine_real_eoe_genemorph_imago_landfall_set_base_pt_below_threshold_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Genemorph Imago,
    sub-threshold branch.**

    Python: the ACTUAL parsed Genemorph Imago printing pre-seated on
    p0's battlefield (no cast path → no spurious ETB triggers since
    the genuine printing carries only the landfall ENTERS trigger).
    A bait Bear is also seated on p0's bf as the target. A Forest is
    played from p0's hand, firing the landfall trigger. The trigger
    targets the picked creature (a ``_PickFirstControlledCreature
    Agent`` shim on p0 picks the bait Bear, mirroring Rust's apply-
    time first-creature-on-source-controller-bf scan).

    Rust: bridged synthetic carrier carrying the same landfall
    trigger + ``set_base_pt_conditional_until_eot`` effect dict; the
    bait Bear is seated on p0's bf; the Forest is played to fire the
    trigger. The Rust resolve arm picks the first creature on p0's bf
    deterministically — the seating order makes this the Bear.

    Land-count at resolve time = 1 (the played Forest only;
    Genemorph Imago itself is NOT a Land). 1 < 6, so the 3/3 default
    branch fires. The Bear's base goes from 2/2 (printed) to 3/3
    (layer-7b SetBasePT override) on BOTH engines.

    Assertion strength: **full ``compare_fields == []``** over the
    whole cross-engine field view (every zone, both players), PLUS
    the concrete UEOT observables (effective_power == 3 AND
    effective_toughness == 3 on BOTH engines for the picked Bear).
    Forest ``summoning_sick`` is normalised symmetric before the
    whole-view compare (the established Icecave Crasher batch-B
    fixture-asymmetry precedent — Python's ``_play_land`` seats the
    land summoning-sick while Rust's ``play_land`` does not).
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
    )
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.cards import SYNTHETIC_CREATURES
    from mtg_bot.actions import _play_land, resolve_top_of_stack
    from mtg_bot.game import (
        Zone, effective_power, effective_toughness,
    )
    from mtg_bot.turn import state_based_actions as py_sba
    from tests.parity._picker_shims import _PickFirstControlledCreatureAgent

    real = _PRINTINGS.get("Genemorph Imago")
    if real is None:
        pytest.skip("Genemorph Imago absent from active CardSource")
    assert "Creature" in real.card_types

    # §2 source-of-truth: verify the genuine printing carries the
    # exact landfall+conditional-set-base-PT trigger this probe pins.
    from mtg_bot.effects.predicates import (
        And, Controlled, Event, Subject, YOU,
    )
    from mtg_bot.effects.object_predicates import IsLand

    landfall_ta = next(
        (
            ta for ta in real.triggered_abilities
            if (
                ta.event is Event.ENTERS
                and isinstance(ta.effect, SetBasePTConditionalUntilEOT)
            )
        ),
        None,
    )
    assert landfall_ta is not None, (
        "Genemorph Imago must carry an ENTERS/SetBasePTConditional "
        "UntilEOT landfall trigger"
    )
    lf_eff = landfall_ta.effect
    assert lf_eff.default_power == 3 and lf_eff.default_toughness == 3
    assert lf_eff.land_threshold == 6
    assert lf_eff.upgrade_power == 6 and lf_eff.upgrade_toughness == 6
    lf_pred = landfall_ta.predicate
    assert isinstance(lf_pred, And)
    assert isinstance(lf_pred.left, Subject) and isinstance(
        lf_pred.left.inner, IsLand
    )
    assert isinstance(lf_pred.right, Controlled) and lf_pred.right.by == YOU

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2
    ZH = 0

    # Seat the same-side target picker shim on p0 so Python picks the
    # first own-side creature, byte-equal with Rust's at-apply-time
    # first-creature-on-source-controller-bf scan.
    py.players[0].agent = _PickFirstControlledCreatureAgent()

    # ---- Python: seat the BAIT BEAR FIRST on p0's bf so it is the
    # deterministic first-creature pick on BOTH engines (Rust's
    # resolve arm scans the source-controller's bf top-to-bottom for
    # the first Creature; Python's shim picks the first own-side
    # creature offered in ``legal_targets``, which walks
    # ``state.battlefield`` in insertion order — seating Bear first
    # makes Python's shim mirror Rust's at-apply pick bit-for-bit).
    bear_printing = SYNTHETIC_CREATURES["Wild Bear"]
    py_bear = py.new_object(bear_printing, owner_id=0, zone=Zone.BATTLEFIELD)
    py_bear.summoning_sick = False
    py_bear.tapped = False
    py_bear.damage = 0
    py_bear.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_bear)

    # Now seat the GENUINE parsed Genemorph printing AFTER the bait
    # so the carrier itself is NOT the first-creature pick.
    py_src = py.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    py_src.summoning_sick = False
    py_src.tapped = False
    py_src.damage = 0
    py_src.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_src)

    # Inject a Forest into p0's hand.
    forest_printing = CardPrinting(
        name="Forest", mana_cost_str="",
        mana_cost=ManaCost(generic=0, colored=()),
        type_line="Basic Land — Forest", supertypes=("Basic",),
        card_types=("Land",), subtypes=("Forest",),
        power=None, toughness=None, produces=frozenset({"G"}),
    )
    py_forest = py.new_object(forest_printing, owner_id=0, zone=Zone.HAND)
    py.players[0].hand.append(py_forest)

    # ---- Rust: seat the bait Bear FIRST (mirror of Python) so it
    # is the deterministic first-creature pick; then the bridged
    # synthetic carrier carrying ONLY the landfall trigger +
    # conditional-set-base-PT effect dict.
    rp = int(real.power) if real.power is not None else 1
    rt = int(real.toughness) if real.toughness is not None else 3
    rs_bear = rs.register_and_inject_object(
        {"name": "Wild Bear", "card_types": ["Creature"],
         "power": int(bear_printing.power),
         "toughness": int(bear_printing.toughness)},
        0, ZB,
    )
    rs_src = rs.register_and_inject_object(
        {
            "name": "Genemorph Imago",
            "card_types": ["Creature"],
            "power": rp, "toughness": rt,
            "effects": [],
            "triggered_abilities": [
                {
                    "event": "enters",
                    "predicate": {
                        "kind": "and",
                        "left": {"kind": "subject_is_land"},
                        "right": {"kind": "controlled_by_you"},
                    },
                    "effect": {
                        "kind": "set_base_pt_conditional_until_eot",
                        "default_power": int(lf_eff.default_power),
                        "default_toughness": int(lf_eff.default_toughness),
                        "land_threshold": int(lf_eff.land_threshold),
                        "upgrade_power": int(lf_eff.upgrade_power),
                        "upgrade_toughness": int(lf_eff.upgrade_toughness),
                    },
                }
            ],
        },
        0, ZB,
    )
    rs_forest = rs.register_and_inject_object(
        {"name": "Forest", "card_types": ["Land"],
         "mana_produced": ["G"], "supertypes": ["Basic"]},
        0, ZH,
    )

    # Pre-trigger sanity: no trigger fires during seeding.
    assert rs.stack_size() == 0 and len(py.stack) == 0

    py_p0_life0 = py.players[0].life
    py_p1_life0 = py.players[1].life
    rs_p0_life0 = rs.get_life(0)
    rs_p1_life0 = rs.get_life(1)

    # ---- Fire the landfall trigger by playing the Forest on BOTH. ----
    py.players[0].lands_played_this_turn = 0
    _play_land(py, 0, py_forest.id)
    rs.play_land(rs_forest, 0)

    assert len(py.stack) == 1, (
        "Python: landfall trigger should be on the stack after Forest "
        "enters"
    )
    assert rs.stack_size() == 1, (
        "Rust: landfall trigger should be on the stack after Forest enters"
    )

    # ---- Drain both stacks (resolves SetBasePTConditionalUntilEOT). ----
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)
    rs.apply_sbas()
    assert rs.stack_size() == 0 and len(py.stack) == 0

    # Concrete UEOT observable: the picked Bear's base P/T is set to
    # 3/3 on BOTH engines (sub-threshold branch — land_count = 1 < 6).
    # Wild Bear is 2/2 printed; the layer-7b override REPLACES the
    # base, so effective_power/toughness go from 2 to 3.
    py_bear_pow = effective_power(py, py_bear)
    py_bear_tou = effective_toughness(py, py_bear)
    rs_bear_pow = rs.effective_power(rs_bear)
    rs_bear_tou = rs.effective_toughness(rs_bear)
    assert py_bear_pow == 3, (
        f"Python: bear effective_power must be default=3 "
        f"(sub-threshold); got {py_bear_pow}"
    )
    assert py_bear_tou == 3, (
        f"Python: bear effective_toughness must be default=3; "
        f"got {py_bear_tou}"
    )
    assert rs_bear_pow == 3, (
        f"Rust: bear effective_power must be default=3; "
        f"got {rs_bear_pow}"
    )
    assert rs_bear_tou == 3, (
        f"Rust: bear effective_toughness must be default=3; "
        f"got {rs_bear_tou}"
    )

    # Life totals unchanged (set-base-PT touches no life).
    assert py.players[0].life == py_p0_life0
    assert py.players[1].life == py_p1_life0
    assert rs.get_life(0) == rs_p0_life0
    assert rs.get_life(1) == rs_p1_life0

    # Normalise the Forest's summoning_sick slot before the whole-view
    # compare — established fixture-asymmetry from the Icecave Crasher
    # / Remnant Elemental batch-B idiom.
    for o in py.battlefield:
        if o.printing.name == "Forest":
            o.summoning_sick = False

    # ---- Full field-view byte-equality over the WHOLE state. ----
    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Genemorph Imago landfall SetBasePTConditionalUntilEOT must "
        f"be byte-equal across the WHOLE field view on BOTH engines; "
        f"diffs={diffs}"
    )
