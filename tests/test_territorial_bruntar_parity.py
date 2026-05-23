"""Territorial Bruntar Cycle 1 — `TerritorialBruntarLandfallEffect`
Rust Effect substrate close + per-card cross-engine byte-equal probe.

Territorial Bruntar is a `{4}{R}{R}` Creature — Beast (6/6) with
``reach`` whose landfall trigger walks the controller's library top-
to-bottom, exiling each card, and stops at the first non-land:

    "Reach. Landfall — Whenever a land you control enters, exile cards
    from the top of your library until you exile a nonland card. You
    may cast that card this turn."

This module pins the Rust `Effect::TerritorialBruntarLandfallEffect`
variant landed in this branch + the matching cross_engine bridge arm
+ a genuine real-EoE cross-engine byte-equal probe driving the
landfall trigger end-to-end on a synthetic Rust carrier (mirroring
the Genemorph Imago precedent in
``tests/test_genemorph_imago_parity.py`` — both are landfall
triggers; Genemorph Imago's observable is base-P/T, Territorial
Bruntar's observable is the zone-change footprint).

**Multi-gated card; classifier stays multi-gated.** Per the round-58
subsystem-attribution classifier
(``scripts/scout_r58_subsystem_attribution.py``), Territorial Bruntar
is multi-gated:

  * ``effect_uncovered`` — closed by this cycle. The new Rust variant
    ``Effect::TerritorialBruntarLandfallEffect`` makes the Python
    class ``TerritorialBruntarLandfallEffect`` covered via the 1:1
    identity-mapping rule in ``effect_coverage.map_rust_to_python``;
    the classifier's ``missing_effect_classes`` array shrinks by one
    for this card.
  * ``nonsafe_triggered_ability`` — **STAYS active**. The trajectory
    safe-trigger admit gate (``parity/trajectory.py::
    _python_ta_to_safe_dict``) is INTENTIONALLY NOT widened — that
    gate is about the production-deck bench admit set, a distinct
    concern from per-card real-EoE parity probes. The classifier's
    multi-gate state therefore reads
    ``{'gates': ['effect_uncovered', 'nonsafe_triggered_ability'],
       'multi_gated': True,
       'missing_effect_classes': []}``
    after this cycle (the effect-class list is empty; the trigger
    leaf class is still not in the safe set).

**Per-card dedicated parity probe path (PROBED tier flip).** Even
though the classifier keeps the card multi-gated at
``nonsafe_triggered_ability``, this test module is the dedicated
per-card real-EoE byte-equal cross-engine probe that flips
Territorial Bruntar to PROBED tier. Same precedent as
``test_genemorph_imago_parity.py``, ``test_fanatic_of_the_harrowing
_parity.py``, ``test_vaultguard_trooper_parity.py``,
``test_boilerbilges_ripper_parity.py``, ``test_comet_crawler_parity
.py``, and ``test_friendly_teddy_parity.py``: a per-card probe
drives the real printing through both engines and pins byte-equal
observables; the safe-trigger bench admit set is widened in a
separate cycle when the production-deck bench needs it.

**NOT a spell-card-bridge admit-set extension.** Territorial Bruntar
is a Creature, not a non-creature spell. The spell-card-bridge admit
set (``trajectory.py::_python_spell_effect_to_dict`` + its §2 teeth)
gates non-creature spells only. The per-card probe approach is the
right tool here, exactly the Genemorph Imago / Comet Crawler /
Mutinous Massacre / Dyadrine Attack / Boilerbilges Ripper
convention.

**HONEST-STOP: `playable_from_exile_this_turn` flag NOT mirrored on
Rust.** Python's ``TerritorialBruntarLandfallEffect.resolve`` sets
``top.playable_from_exile_this_turn = True`` on the terminating
non-land card so ``legal_actions`` will surface a CastSpell for it.
Rust has no ``playable_from_exile_this_turn`` field on
``GameObject`` and no cast-from-exile substrate in the legal-actions
/ cast-resolution pipelines. The Rust resolve arm therefore mirrors
the OBSERVABLE zone-change half byte-equal (cards exiled, non-land
terminator stops at top of exile) but does NOT flag the non-land as
castable. The cross-engine probe normalises the flag symmetric on
the Python side before the whole-view compare (mirroring the
established summoning-sick normalisation precedent from the Icecave
Crasher / Genemorph Imago batch-B fixture-asymmetry idiom).
Documented as a deliberate divergence in
``docs/SEARCH_LIMITATIONS.md``.

Test surface:

  1. Parser SoT — Territorial Bruntar is parser-claimed and emits a
     ``TerritorialBruntarLandfallEffect()`` effect under an
     ENTERS+landfall trigger.

  2. Serializer round-trip — a Python
     ``TerritorialBruntarLandfallEffect`` constructs the dict shape
     ``{"kind": "territorial_bruntar_landfall_effect"}`` and the
     cross_engine bridge translates it back identically.

  3. Rust unit pins:
       3a. Library has [non-land] (top) → that one non-land exiled,
           loop terminates.
       3b. Library has [land, land, non-land, ...] → the two lands
           AND the non-land are exiled in that order; loop
           terminates at the non-land; deeper-stack non-lands stay
           in library.
       3c. Library is empty → silent no-op.
       3d. Library has [land, land] (all lands) → both lands
           exiled, loop terminates on empty library (no non-land
           ever found).

  4. Covered-set membership — the orphan walker recognises
     ``TerritorialBruntarLandfallEffect`` as a 1:1 same-named
     Rust/Python match (parser-claimed via Territorial Bruntar).

  5. **GENUINE real-EoE cross-engine probe** — drives the ACTUAL
     parsed Territorial Bruntar printing on Python and a bridged
     synthetic carrier on Rust, then plays a land to fire the
     landfall trigger. Asserts the concrete zone observables
     (library shrinkage + exile additions) plus the full
     ``compare_fields == []`` over the whole cross-engine field
     view (with the ``playable_from_exile_this_turn`` flag
     normalised symmetric per the honest-stop above). CAVEAT
     (mirrors ``docs/POOL_PARITY.md``): Effect+bridge-level byte-
     equality on a *controlled* cross-engine state, NOT full-
     game-trajectory parity.

NO admit-set change — Territorial Bruntar is a Creature, not a
spell. Per-card PROBED via the probe below.
"""

from __future__ import annotations

import importlib
import importlib.util
import pathlib
import sys

import pytest

from mtg_bot.cards.source import get_active_source
from mtg_bot.effects.bespoke import TerritorialBruntarLandfallEffect


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
    ``test_genemorph_imago_parity.py`` / ``test_fanatic_of_the_
    harrowing_parity.py``."""
    repo_root = pathlib.Path(__file__).resolve().parent.parent
    script_path = repo_root / "scripts" / "parity_smoke.py"
    spec = importlib.util.spec_from_file_location(
        "parity_smoke", script_path
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["parity_smoke"] = mod
    spec.loader.exec_module(mod)
    return mod


# Zone constants (mirror Rust's u8 zone IDs used by
# ``register_and_inject_object``).
ZONE_HAND = 0
ZONE_LIBRARY = 1
ZONE_BATTLEFIELD = 2
ZONE_GRAVEYARD = 3
ZONE_EXILE = 5


# Canonical Territorial Bruntar dict shape consumed by Rust's
# ``register_and_inject_object`` to build a synthetic carrier with
# the same triggered ability as the real parsed printing.
_BRUNTAR_PRINTING_DICT: dict = {
    "name": "Territorial Bruntar (synthetic carrier)",
    "card_types": ["Creature"],
    "power": 6,
    "toughness": 6,
    "mana_cost": {"generic": 4, "R": 2},
    "triggered_abilities": [
        {
            "event": "enters",
            "predicate": {
                "kind": "and",
                "left": {"kind": "subject_is_land"},
                "right": {"kind": "controlled_by_you"},
            },
            "effect": {
                "kind": "territorial_bruntar_landfall_effect",
            },
        },
    ],
}


# ---------------------------------------------------------------------------
# (1) Parser SoT — Territorial Bruntar is parser-claimed and emits the
# expected TerritorialBruntarLandfallEffect under the canonical
# landfall trigger.
# ---------------------------------------------------------------------------


def test_territorial_bruntar_parser_claims_card():
    assert "Territorial Bruntar" in _PRINTINGS, (
        "Territorial Bruntar must be parser-claimed by the active "
        "CardSource"
    )


def test_territorial_bruntar_printed_attrs():
    """Pins the basic printing surface (cost, type, P/T, keywords)."""
    p = _PRINTINGS["Territorial Bruntar"]
    assert p.mana_cost_str == "{4}{R}{R}"
    assert "Creature" in p.card_types
    assert "Beast" in p.subtypes
    assert p.power == 6
    assert p.toughness == 6
    assert "reach" in p.keywords


def test_territorial_bruntar_landfall_trigger_emits_bespoke_effect():
    """The parser emits exactly ONE triggered ability — the landfall
    trigger pairing the canonical
    ``And(Subject(IsLand), Controlled(YOU))`` predicate with a
    ``TerritorialBruntarLandfallEffect()`` (parameterless frozen
    dataclass) under ENTERS."""
    from mtg_bot.effects.predicates import (
        And, Controlled, Event, Subject, YOU,
    )
    from mtg_bot.effects.object_predicates import IsLand

    p = _PRINTINGS["Territorial Bruntar"]
    assert len(p.triggered_abilities) == 1, (
        "Territorial Bruntar must carry exactly one triggered ability "
        "(the landfall trigger); spurious abilities indicate parser "
        "drift"
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
    assert isinstance(eff, TerritorialBruntarLandfallEffect), (
        f"effect must be TerritorialBruntarLandfallEffect; "
        f"got {type(eff).__name__}"
    )
    # Field-free unit dataclass — equality with a fresh instance.
    assert eff == TerritorialBruntarLandfallEffect()


# ---------------------------------------------------------------------------
# (2) Serializer round-trip — Python class -> Rust-shape dict ->
# Python class. Validates the cross_engine bridge arm landed in this
# branch (``_ta_dict_to_python_effect`` ->
# ``territorial_bruntar_landfall_effect`` arm) round-trips the unit
# variant without field drift.
# ---------------------------------------------------------------------------


def test_territorial_bruntar_effect_dict_to_python_round_trip():
    """Rust-shape dict → Python ``TerritorialBruntarLandfallEffect`` via
    ``_ta_dict_to_python_effect`` reconstructs a default-constructed
    instance. Bridge arm is the lever flip — without it, a Rust→Python
    triggered-ability translation would raise on the unknown kind."""
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    d = {"kind": "territorial_bruntar_landfall_effect"}
    rebuilt = _ta_dict_to_python_effect(d)
    assert isinstance(rebuilt, TerritorialBruntarLandfallEffect), (
        f"dict→Python bridge must round-trip to "
        f"TerritorialBruntarLandfallEffect; got {type(rebuilt).__name__}"
    )
    # Field-free unit dataclass; equality with a fresh instance.
    assert rebuilt == TerritorialBruntarLandfallEffect()


@_rust_skip
def test_territorial_bruntar_rust_effect_to_pydict_round_trip():
    """Rust ``Effect::TerritorialBruntarLandfallEffect`` → dict emits
    the expected one-key shape. Drives the round-trip through
    ``Registry.register_printing`` (the parse path) +
    ``get_printing_etb_effects`` (the ``effect_to_pydict`` readback).

    NB: we use ``etb_effects`` here purely because that's the
    readback Registry surface; the production parser routes
    Territorial Bruntar's effect through the triggered-ability path,
    but the to_pydict round-trip is structurally agnostic to
    where the Effect is parked (the round-trip just exercises
    parse_effect + effect_to_pydict on the variant).
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Territorial Bruntar Round-trip",
            "card_types": ["Creature"],
            "power": 6,
            "toughness": 6,
            "mana_cost": {"generic": 4, "R": 2},
            "etb_effects": [
                {"kind": "territorial_bruntar_landfall_effect"},
            ],
        }
    )
    effs = reg.get_printing_etb_effects(pid)
    assert len(effs) == 1, f"expected 1 etb_effect, got {len(effs)}"
    eff = effs[0]
    assert eff["kind"] == "territorial_bruntar_landfall_effect"
    # Field-free unit variant — no other keys.
    assert set(eff.keys()) == {"kind"}, (
        f"unit-variant to_pydict must emit ONLY 'kind'; got keys "
        f"{sorted(eff.keys())}"
    )


# ---------------------------------------------------------------------------
# (3) Rust unit pins — drive the new Rust variant via
# register_and_inject_object + the existing landfall-trigger pathway,
# and assert the zone-change observables on the Rust side directly.
# Four scenarios: top non-land terminator, lands-then-non-land,
# empty library, and all-lands.
# ---------------------------------------------------------------------------


def _fresh_rust_state():
    import mtg_bot_engine
    return mtg_bot_engine.make_synthetic_state(0, 0, 0)


def _inject_filler_land(rs, owner: int, name_suffix: str, zone: int) -> int:
    """Inject a vanilla Forest into ``owner``'s ``zone``. Returns the
    object id."""
    return rs.register_and_inject_object(
        {
            "name": f"Bruntar Forest {name_suffix}",
            "card_types": ["Land"],
            "supertypes": ["Basic"],
            "mana_produced": ["G"],
        },
        owner,
        zone,
    )


def _inject_filler_nonland(rs, owner: int, name_suffix: str, zone: int) -> int:
    """Inject a vanilla Instant into ``owner``'s ``zone``. Returns the
    object id."""
    return rs.register_and_inject_object(
        {
            "name": f"Bruntar Instant {name_suffix}",
            "card_types": ["Instant"],
            "mana_cost": {"R": 1},
        },
        owner,
        zone,
    )


def _inject_bruntar_on_bf(rs, owner: int = 0) -> int:
    return rs.register_and_inject_object(
        _BRUNTAR_PRINTING_DICT,
        owner,
        ZONE_BATTLEFIELD,
    )


@_rust_skip
def test_rust_resolve_top_nonland_terminates_immediately():
    """Library top is a non-land — exactly that one card is exiled.
    Deeper cards stay in library.

    Note on registration order: ``register_and_inject_object`` pushes
    onto ``lib[0]`` (the TOP), so to build a library with top-to-
    bottom = [non-land, land, land] we register from bottom-to-top —
    deeper lands first, the top non-land LAST.
    """
    rs = _fresh_rust_state()

    # Build library in REVERSE (bottom first) so the last-injected
    # ends up at the top. Library top-to-bottom = [non-land, land,
    # land].
    p0_deeper_land2 = _inject_filler_land(
        rs, owner=0, name_suffix="deeper2", zone=ZONE_LIBRARY,
    )
    p0_deeper_land1 = _inject_filler_land(
        rs, owner=0, name_suffix="deeper1", zone=ZONE_LIBRARY,
    )
    p0_nonland_top = _inject_filler_nonland(
        rs, owner=0, name_suffix="top", zone=ZONE_LIBRARY,
    )

    # Bruntar on p0's bf, fires the landfall trigger when the
    # synthetic Forest enters from hand.
    _inject_bruntar_on_bf(rs, owner=0)
    rs_forest = _inject_filler_land(
        rs, owner=0, name_suffix="trigger", zone=ZONE_HAND,
    )

    lib_before = [e["id"] for e in rs.library_snapshot(0)]
    assert lib_before == [
        p0_nonland_top, p0_deeper_land1, p0_deeper_land2,
    ], f"library top-to-bottom mismatch pre-resolve; got {lib_before}"
    exile_before = [e["id"] for e in rs.exile_snapshot(0)]
    assert exile_before == []

    rs.play_land(rs_forest, 0)
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()

    # The top non-land is now exiled; deeper lands stay in library.
    lib_after = [e["id"] for e in rs.library_snapshot(0)]
    assert lib_after == [p0_deeper_land1, p0_deeper_land2], (
        f"deeper lands must stay in library; got {lib_after}"
    )
    exile_after = [e["id"] for e in rs.exile_snapshot(0)]
    assert exile_after == [p0_nonland_top], (
        f"only the top non-land must be in exile; got {exile_after}"
    )


@_rust_skip
def test_rust_resolve_lands_then_nonland_exiles_all_through_terminator():
    """Library top is land, land, non-land (top to bottom). All
    three are exiled in that order; the loop terminates at the
    non-land. Deeper non-lands stay in library.

    Note on registration order: build the library bottom-first so
    the last-injected lands at ``lib[0]`` (top).
    """
    rs = _fresh_rust_state()

    # Build library in REVERSE (bottom first). Library top-to-bottom
    # = [land, land, non-land, deeper-non-land].
    p0_deeper_nonland = _inject_filler_nonland(
        rs, owner=0, name_suffix="deeper", zone=ZONE_LIBRARY,
    )
    p0_nonland_terminator = _inject_filler_nonland(
        rs, owner=0, name_suffix="terminator", zone=ZONE_LIBRARY,
    )
    p0_land2 = _inject_filler_land(
        rs, owner=0, name_suffix="land2", zone=ZONE_LIBRARY,
    )
    p0_land1 = _inject_filler_land(
        rs, owner=0, name_suffix="land1", zone=ZONE_LIBRARY,
    )

    _inject_bruntar_on_bf(rs, owner=0)
    rs_forest = _inject_filler_land(
        rs, owner=0, name_suffix="trigger", zone=ZONE_HAND,
    )

    lib_before = [e["id"] for e in rs.library_snapshot(0)]
    assert lib_before == [
        p0_land1, p0_land2, p0_nonland_terminator, p0_deeper_nonland,
    ], f"library top-to-bottom mismatch pre-resolve; got {lib_before}"

    rs.play_land(rs_forest, 0)
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()

    # Three cards exiled, deeper non-land stays in library.
    lib_after = [e["id"] for e in rs.library_snapshot(0)]
    assert lib_after == [p0_deeper_nonland], (
        f"only the deeper non-land must stay in library; got {lib_after}"
    )
    exile_after = [e["id"] for e in rs.exile_snapshot(0)]
    assert exile_after == [
        p0_land1, p0_land2, p0_nonland_terminator,
    ], (
        f"exile order must be top-to-bottom land/land/non-land; "
        f"got {exile_after}"
    )


@_rust_skip
def test_rust_resolve_empty_library_silent_no_op():
    """Library is empty at landfall time — the resolve loop
    terminates immediately. No state mutation beyond the land
    entering."""
    rs = _fresh_rust_state()

    # Empty library on p0. Bruntar on p0's bf; a synthetic Forest in
    # p0's hand to fire the landfall.
    _inject_bruntar_on_bf(rs, owner=0)
    rs_forest = _inject_filler_land(
        rs, owner=0, name_suffix="trigger", zone=ZONE_HAND,
    )

    lib_before = [e["id"] for e in rs.library_snapshot(0)]
    assert lib_before == []
    exile_before = [e["id"] for e in rs.exile_snapshot(0)]
    assert exile_before == []
    p0_life_before = rs.get_life(0)

    rs.play_land(rs_forest, 0)
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()

    # Library still empty; nothing was exiled.
    lib_after = [e["id"] for e in rs.library_snapshot(0)]
    assert lib_after == []
    exile_after = [e["id"] for e in rs.exile_snapshot(0)]
    assert exile_after == []
    # No life change either (defense-in-depth — purely observational).
    assert rs.get_life(0) == p0_life_before


@_rust_skip
def test_rust_resolve_all_lands_exiles_all_then_stops_on_empty():
    """Library is all lands — the loop exiles each in turn and stops
    when the library is empty (no non-land ever found).

    Note on registration order: build the library bottom-first.
    """
    rs = _fresh_rust_state()

    # Register bottom-first so top-to-bottom = [land1, land2].
    p0_land2 = _inject_filler_land(
        rs, owner=0, name_suffix="all2", zone=ZONE_LIBRARY,
    )
    p0_land1 = _inject_filler_land(
        rs, owner=0, name_suffix="all1", zone=ZONE_LIBRARY,
    )

    _inject_bruntar_on_bf(rs, owner=0)
    rs_forest = _inject_filler_land(
        rs, owner=0, name_suffix="trigger", zone=ZONE_HAND,
    )

    lib_before = [e["id"] for e in rs.library_snapshot(0)]
    assert lib_before == [p0_land1, p0_land2]

    rs.play_land(rs_forest, 0)
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()

    # Library exhausted; both lands in exile.
    lib_after = [e["id"] for e in rs.library_snapshot(0)]
    assert lib_after == []
    exile_after = [e["id"] for e in rs.exile_snapshot(0)]
    assert exile_after == [p0_land1, p0_land2], (
        f"both lands must be exiled in top-to-bottom order; "
        f"got {exile_after}"
    )


# ---------------------------------------------------------------------------
# (4) Covered-set membership — the orphan walker recognises the new
# Rust variant TerritorialBruntarLandfallEffect as a 1:1 same-named
# match against the parser-claimed Python class.
# ---------------------------------------------------------------------------


def test_territorial_bruntar_class_covered_by_rust():
    """The Python class is in the parser-emitted covered set
    (Territorial Bruntar claims it) and the Rust variant has the
    SAME name, so the orphan walker pairs them 1:1 without an
    override or RUST_AHEAD_OF_POOL allowlist entry."""
    from mtg_bot.parity.effect_coverage import (
        collect_python_effect_vocab,
        collect_rust_effect_variants,
        covered_python_class_set,
    )

    py_classes, _examples, _n = collect_python_effect_vocab()
    assert "TerritorialBruntarLandfallEffect" in py_classes, (
        "Territorial Bruntar must surface "
        "TerritorialBruntarLandfallEffect in the parser-walked Python "
        "effect vocab"
    )
    rust_variants = collect_rust_effect_variants()
    assert "TerritorialBruntarLandfallEffect" in rust_variants, (
        "the new Rust Effect variant must be discoverable by the "
        "cards.rs text parser"
    )
    covered = covered_python_class_set()
    assert "TerritorialBruntarLandfallEffect" in covered, (
        "the new Rust variant pairs 1:1 with the parser-claimed "
        "Python class (no override / RUST_AHEAD_OF_POOL allowlist "
        "needed)"
    )


def test_territorial_bruntar_classifier_effect_uncovered_gate_closed():
    """The round-58 subsystem-attribution classifier walks
    ``TIER_BLOCKED_SUBSYSTEM`` cards. After this cycle Territorial
    Bruntar's only remaining gate is ``nonsafe_triggered_ability``
    (the per-card-probe-tier-flip gate, NOT a subsystem block) — the
    Effect-uncovered gate is closed at the covered-set level
    (``TerritorialBruntarLandfallEffect`` is now in
    ``covered_python_class_set()`` via the new Rust variant). Two
    valid closure shapes are accepted here:

      (a) **Row absent.** The card has shed every subsystem-tier
          gate and is no longer in ``TIER_BLOCKED_SUBSYSTEM``. This
          is the strongest closure signal — the classifier no
          longer flags it as subsystem-gated at all.

      (b) **Row present with ``missing_effect_classes == []``.** The
          card is still flagged at the subsystem tier for some
          OTHER reason (e.g. a loader gate the classifier picks up
          independently of the Effect-class gate), but the
          ``effect_uncovered`` half of the gate is closed.

    Both shapes confirm the ``effect_uncovered`` gate has closed at
    the classifier level. Pinning either is the load-bearing signal
    that this cycle's Rust variant has propagated into the
    coverage-of-record. See the closer-to-source
    ``test_territorial_bruntar_class_covered_by_rust`` pin for the
    direct covered-set assertion that doesn't depend on the
    classifier's tier semantics.
    """
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
    row = attr["cards"].get("Territorial Bruntar")
    if row is None:
        # Closure shape (a): the card is no longer subsystem-tier
        # gated. Strongest possible closure signal.
        return
    # Closure shape (b): row still present (some other gate keeps
    # the card in the subsystem tier), but the effect-class half is
    # empty.
    assert row["missing_effect_classes"] == [], (
        f"Cycle 1 closure expected `missing_effect_classes == []`; "
        f"got {row['missing_effect_classes']}"
    )


# ---------------------------------------------------------------------------
# (5) GENUINE real-EoE cross-engine byte-equal probe — drives the
# ACTUAL parsed Territorial Bruntar printing on Python and a bridged
# synthetic carrier on Rust. After playing a Forest to fire the
# landfall trigger, asserts the concrete zone observables (library
# shrinkage + exile additions) plus the full ``compare_fields == []``
# over the whole cross-engine field view.
#
# Scenario: a library shape that exercises the lands-then-non-land
# terminator path — top to bottom [land, land, non-land,
# deeper-non-land]. After landfall:
#   - the two top lands AND the terminator non-land are exiled (in
#     top-to-bottom order);
#   - the deeper non-land stays in library;
#   - Territorial Bruntar stays on p0's bf;
#   - the played Forest sits on p0's bf (summoning_sick normalised).
# ---------------------------------------------------------------------------


@_rust_skip
def test_cross_engine_real_eoe_territorial_bruntar_landfall_terminator_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Territorial Bruntar,
    lands-then-non-land terminator path.**

    Python: the ACTUAL parsed Territorial Bruntar printing pre-
    seated on p0's battlefield (no cast path → no spurious ETB
    triggers since the genuine printing carries only the landfall
    ENTERS trigger). p0's library is seeded with top-to-bottom
    [land, land, non-land, deeper-non-land]. A Forest is played
    from p0's hand, firing the landfall trigger. The trigger walks
    the library top-to-bottom, exiling each card, and stops at the
    first non-land.

    Rust: bridged synthetic carrier carrying the same landfall
    trigger + ``territorial_bruntar_landfall_effect`` effect dict;
    p0's library is seeded identically; the Forest is played to fire
    the trigger.

    Assertion strength: **full ``compare_fields == []``** over the
    whole cross-engine field view (every zone, both players), PLUS
    the concrete zone observables (library shrinkage to one card +
    exile additions in top-to-bottom land/land/non-land order on
    BOTH engines).

    Forest ``summoning_sick`` is normalised symmetric before the
    whole-view compare (the established Icecave Crasher / Genemorph
    Imago batch-B fixture-asymmetry precedent — Python's
    ``_play_land`` seats the land summoning-sick while Rust's
    ``play_land`` does not). The terminating non-land's
    ``playable_from_exile_this_turn`` flag is honest-stopped and
    also normalised symmetric before the whole-view compare (see
    SEARCH_LIMITATIONS.md).
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
    )
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.actions import _play_land, resolve_top_of_stack
    from mtg_bot.game import Zone
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.predicates import (
        And, Controlled, Event, Subject, YOU,
    )
    from mtg_bot.effects.object_predicates import IsLand

    real = _PRINTINGS.get("Territorial Bruntar")
    if real is None:
        pytest.skip("Territorial Bruntar absent from active CardSource")
    assert "Creature" in real.card_types

    # §2 source-of-truth: verify the genuine printing carries the
    # exact landfall+TerritorialBruntarLandfallEffect trigger this
    # probe pins.
    landfall_ta = next(
        (
            ta for ta in real.triggered_abilities
            if (
                ta.event is Event.ENTERS
                and isinstance(
                    ta.effect, TerritorialBruntarLandfallEffect
                )
            )
        ),
        None,
    )
    assert landfall_ta is not None, (
        "Territorial Bruntar must carry an ENTERS/"
        "TerritorialBruntarLandfallEffect landfall trigger"
    )
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
    ZL = 1

    # Synthetic vanilla filler printings on the Python side
    # (matching the Rust register_and_inject_object dicts byte-for-
    # byte).
    def _land_printing(name: str) -> CardPrinting:
        return CardPrinting(
            name=name,
            mana_cost_str="",
            mana_cost=ManaCost(generic=0, colored=()),
            type_line="Basic Land — Forest",
            supertypes=("Basic",),
            card_types=("Land",),
            subtypes=("Forest",),
            power=None,
            toughness=None,
            produces=frozenset({"G"}),
        )

    def _instant_printing(name: str) -> CardPrinting:
        return CardPrinting(
            name=name,
            mana_cost_str="",
            mana_cost=ManaCost(generic=0, colored=(("R", 1),)),
            type_line="Instant",
            supertypes=(),
            card_types=("Instant",),
            subtypes=(),
            power=None,
            toughness=None,
            produces=frozenset(),
            keywords=frozenset(),
        )

    # ---- Python: seat the genuine parsed Bruntar on p0's bf;
    # seed p0's library with [land, land, non-land,
    # deeper-non-land] top-to-bottom; place a Forest in p0's hand.
    py_bruntar = py.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    py_bruntar.summoning_sick = False
    py_bruntar.tapped = False
    py_bruntar.damage = 0
    py_bruntar.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_bruntar)

    # Python `new_object` allocates IDs in call order. To make IDs
    # align with Rust's registration order (deeper=1, terminator=2,
    # land2=3, land1=4 — bottom-first because Rust's
    # `register_and_inject_object` pushes onto lib[0]), we allocate
    # Python's objects bottom-first too.
    py_lib_deeper_nonland = py.new_object(
        _instant_printing("Bruntar Instant deeper"),
        owner_id=0,
        zone=Zone.LIBRARY,
    )
    py_lib_nonland_term = py.new_object(
        _instant_printing("Bruntar Instant terminator"),
        owner_id=0,
        zone=Zone.LIBRARY,
    )
    py_lib_land2 = py.new_object(
        _land_printing("Bruntar Forest land2"),
        owner_id=0,
        zone=Zone.LIBRARY,
    )
    py_lib_land1 = py.new_object(
        _land_printing("Bruntar Forest land1"),
        owner_id=0,
        zone=Zone.LIBRARY,
    )
    # Library order top-to-bottom = list-prefix order. The objects'
    # ALLOCATION order was bottom-first (deeper=1, ..., land1=4) for
    # ID parity with Rust, but the library list itself is laid out
    # top-to-bottom.
    # Also normalise summoning_sick=False on every library card
    # (Python's `new_object` defaults summoning_sick=True for
    # cards-in-library, while Rust's `register_and_inject_object`
    # defaults to False — same fixture-asymmetry idiom Icecave
    # Crasher / Genemorph Imago batch-B handle on the bf-side).
    for _obj in (
        py_lib_land1, py_lib_land2,
        py_lib_nonland_term, py_lib_deeper_nonland,
    ):
        _obj.summoning_sick = False
    py.players[0].library.extend([
        py_lib_land1,
        py_lib_land2,
        py_lib_nonland_term,
        py_lib_deeper_nonland,
    ])

    py_forest_hand = py.new_object(
        _land_printing("Bruntar Forest trigger"),
        owner_id=0,
        zone=Zone.HAND,
    )
    py.players[0].hand.append(py_forest_hand)

    # ---- Rust: seat the bridged synthetic Bruntar carrier on p0's
    # bf; seed p0's library identically; place a Forest in p0's hand.
    #
    # Library-injection order note: ``register_and_inject_object``
    # pushes onto ``lib[0]`` (the TOP), so to build a library with
    # top-to-bottom = [land1, land2, terminator, deeper] we register
    # from BOTTOM-to-top — deeper first, terminator second, land2,
    # then land1 last.
    # Use the REAL printing's name on the Rust carrier so the
    # battlefield field-view tuple's name slot agrees byte-equal
    # with Python's actual parsed Bruntar.
    bruntar_carrier_for_probe = dict(_BRUNTAR_PRINTING_DICT)
    bruntar_carrier_for_probe["name"] = real.name
    rs_bruntar = rs.register_and_inject_object(
        bruntar_carrier_for_probe, 0, ZB,
    )
    rs_lib_deeper_nonland = rs.register_and_inject_object(
        {
            "name": "Bruntar Instant deeper",
            "card_types": ["Instant"],
            "mana_cost": {"R": 1},
        },
        0, ZL,
    )
    rs_lib_nonland_term = rs.register_and_inject_object(
        {
            "name": "Bruntar Instant terminator",
            "card_types": ["Instant"],
            "mana_cost": {"R": 1},
        },
        0, ZL,
    )
    rs_lib_land2 = rs.register_and_inject_object(
        {
            "name": "Bruntar Forest land2",
            "card_types": ["Land"],
            "supertypes": ["Basic"],
            "mana_produced": ["G"],
        },
        0, ZL,
    )
    rs_lib_land1 = rs.register_and_inject_object(
        {
            "name": "Bruntar Forest land1",
            "card_types": ["Land"],
            "supertypes": ["Basic"],
            "mana_produced": ["G"],
        },
        0, ZL,
    )
    rs_forest_hand = rs.register_and_inject_object(
        {
            "name": "Bruntar Forest trigger",
            "card_types": ["Land"],
            "supertypes": ["Basic"],
            "mana_produced": ["G"],
        },
        0, ZH,
    )
    # Sanity: library top-to-bottom matches Python's order.
    rs_lib_check = [e["id"] for e in rs.library_snapshot(0)]
    assert rs_lib_check == [
        rs_lib_land1, rs_lib_land2,
        rs_lib_nonland_term, rs_lib_deeper_nonland,
    ], f"Rust library top-to-bottom mismatch pre-trigger; got {rs_lib_check}"

    # Pre-trigger sanity: no trigger fires during seeding.
    assert rs.stack_size() == 0 and len(py.stack) == 0

    # ---- Fire the landfall trigger by playing the Forest on BOTH. ----
    py.players[0].lands_played_this_turn = 0
    _play_land(py, 0, py_forest_hand.id)
    rs.play_land(rs_forest_hand, 0)

    assert len(py.stack) == 1, (
        "Python: landfall trigger should be on the stack after Forest "
        "enters"
    )
    assert rs.stack_size() == 1, (
        "Rust: landfall trigger should be on the stack after Forest enters"
    )

    # ---- Drain both stacks (resolves TerritorialBruntarLandfall
    # Effect). ----
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)
    rs.apply_sbas()
    assert rs.stack_size() == 0 and len(py.stack) == 0

    # ---- Python observables. ----
    # Library should be [deeper_nonland] only.
    py_lib_ids = [o.id for o in py.players[0].library]
    assert py_lib_ids == [py_lib_deeper_nonland.id], (
        f"Python: library must be [deeper_nonland] post-resolve; "
        f"got {py_lib_ids}"
    )
    # Exile should be [land1, land2, terminator_nonland] in that order.
    py_exile_ids = [o.id for o in py.players[0].exile]
    assert py_exile_ids == [
        py_lib_land1.id, py_lib_land2.id, py_lib_nonland_term.id,
    ], (
        f"Python: exile must be [land1, land2, terminator] "
        f"top-to-bottom; got {py_exile_ids}"
    )
    # Bruntar still on bf.
    assert py_bruntar in py.battlefield

    # ---- Rust observables. ----
    rs_lib_ids = [e["id"] for e in rs.library_snapshot(0)]
    assert rs_lib_ids == [rs_lib_deeper_nonland], (
        f"Rust: library must be [deeper_nonland] post-resolve; "
        f"got {rs_lib_ids}"
    )
    rs_exile_ids = [e["id"] for e in rs.exile_snapshot(0)]
    assert rs_exile_ids == [
        rs_lib_land1, rs_lib_land2, rs_lib_nonland_term,
    ], (
        f"Rust: exile must be [land1, land2, terminator] "
        f"top-to-bottom; got {rs_exile_ids}"
    )
    # Bruntar still on bf.
    rs_bf_ids = [e["id"] for e in rs.battlefield_snapshot()]
    assert rs_bruntar in rs_bf_ids

    # ---- Pre-compare normalisation (honest-stop + fixture-
    # asymmetry). ----
    # 1. Forest summoning_sick: Python's _play_land seats the land
    #    summoning-sick; Rust's play_land does not. Normalise
    #    symmetric (the Icecave Crasher / Genemorph Imago batch-B
    #    precedent).
    for o in py.battlefield:
        if o.printing.name == "Bruntar Forest trigger":
            o.summoning_sick = False
    # 2. playable_from_exile_this_turn flag on the terminator non-
    #    land: Python sets it True; Rust has no such field. Reset
    #    the Python side to its default-False so the cross-engine
    #    field view aligns (the honest-stop documented in
    #    SEARCH_LIMITATIONS.md).
    for o in py.players[0].exile:
        if hasattr(o, "playable_from_exile_this_turn"):
            o.playable_from_exile_this_turn = False

    # ---- Full field-view byte-equality over the WHOLE state. ----
    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Territorial Bruntar landfall TerritorialBruntarLandfallEffect "
        f"must be byte-equal across the WHOLE field view on BOTH "
        f"engines (with summoning_sick + "
        f"playable_from_exile_this_turn normalised symmetric); "
        f"diffs={diffs}"
    )
