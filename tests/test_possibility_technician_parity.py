"""Possibility Technician Cycle 1 — ``PossibilityTechnicianETBEffect``
Rust Effect substrate close + per-card cross-engine byte-equal probe.

Possibility Technician is a ``{2}{R}`` Creature — Kavu Artificer (3/3,
EoE — sourced from ``data/edge_of_eternities.json``) with an ETB+
observer body and a Warp keyword:

    "Whenever this creature or another Kavu you control enters, exile
    the top card of your library. For as long as that card remains
    exiled, you may play it if you control a Kavu."
    "Warp {1}{R} (You may cast this card from your hand for its warp
    cost. Exile this creature at the beginning of the next end step,
    then you may cast it from exile on a later turn.)"

This module pins the Rust ``Effect::PossibilityTechnicianETBEffect``
variant landed in this branch + the matching cross_engine bridge arm +
a genuine real-EoE cross-engine byte-equal probe driving the ENTERS+
IsSelf ETB trigger end-to-end on a synthetic Rust carrier (mirroring
the Territorial Bruntar / Boilerbilges Ripper precedent — both seat
the source printing directly on the bf for the probe and fire the
ETB-style trigger from the battlefield carrier).

**Multi-gated card; classifier stays multi-gated.** Per the round-58
subsystem-attribution classifier
(``scripts/scout_r58_subsystem_attribution.py``), Possibility
Technician is multi-gated across THREE gates:

  * ``effect_uncovered`` — closed by this cycle. The new Rust variant
    ``Effect::PossibilityTechnicianETBEffect`` makes the Python class
    ``PossibilityTechnicianETBEffect`` covered via the 1:1 identity-
    mapping rule in ``effect_coverage.map_rust_to_python``; the
    classifier's ``missing_effect_classes`` array shrinks by one for
    this card.
  * ``warp_cost`` — **STAYS open**. The Warp keyword is genuinely
    multi-cycle substrate — the cast-from-hand-for-warp-cost path
    through the cost-substitution pipeline, the exile-at-next-end-
    step delayed trigger, and the cast-from-exile-on-later-turn
    legal-actions surface together form a substrate the engine
    simply lacks today. Closing ``warp_cost`` is its own multi-cycle
    landing (the same status as Boilerbilges Ripper / Codecracker
    Hound — both Warp-keyword cards have their warp_cost gates open).
  * ``nonsafe_triggered_ability`` — **STAYS active**. The trajectory
    safe-trigger admit gate (``parity/trajectory.py::
    _python_ta_to_safe_dict``) is INTENTIONALLY NOT widened — that
    gate is about the production-deck bench admit set, a distinct
    concern from per-card real-EoE parity probes.

**Per-card dedicated parity probe path (PROBED tier flip).** Even
though the classifier keeps the card multi-gated at ``warp_cost`` +
``nonsafe_triggered_ability``, this test module is the dedicated
per-card real-EoE byte-equal cross-engine probe that flips Possibility
Technician to PROBED tier. Same precedent as
``test_boilerbilges_ripper_parity.py``,
``test_territorial_bruntar_parity.py``,
``test_fanatic_of_the_harrowing_parity.py``,
``test_terrapact_intimidator_parity.py``,
``test_splitskin_doll_parity.py``: a per-card probe drives the real
printing through both engines and pins byte-equal observables; the
safe-trigger bench admit set is widened in a separate cycle when the
production-deck bench needs it.

**Probe avoids the warp_cost gate.** The probe seats the source
printing directly on the battlefield (NOT via the warp-cast path)
and fires the ETB trigger from the battlefield carrier — exactly
the Boilerbilges Ripper / Codecracker Hound Warp-keyword probe
convention. Closing the warp_cost gate is its own multi-cycle
substrate landing.

**HONEST-STOP: ``play_from_exile_requires_kavu`` flag NOT mirrored on
Rust.** Python's ``PossibilityTechnicianETBEffect.resolve`` sets
``top.play_from_exile_requires_kavu = True`` on the exiled card so
``legal_actions`` will surface a CastSpell / PlayLand for it whenever
the controller currently controls at least one Kavu. Rust has no such
field on ``GameObject`` and no cast-from-exile-with-Kavu-gate
substrate in the legal-actions / cast-resolution pipelines. The Rust
resolve arm therefore mirrors the OBSERVABLE zone-change half byte-
equal (top card exiled, library shrinks by 1) but does NOT flag the
exiled card as castable. The cross-engine probe normalises the flag
symmetric on the Python side before the whole-view compare (mirroring
the Territorial Bruntar / ``playable_from_exile_this_turn``
honest-stop precedent). Documented as a deliberate divergence in
``docs/SEARCH_LIMITATIONS.md``.

**NOT a spell-card-bridge admit-set extension.** Possibility
Technician is a Creature, not a non-creature spell. The spell-card-
bridge admit set (``trajectory.py::_python_spell_effect_to_dict`` +
its §2 teeth) gates non-creature spells only. The per-card probe
approach is the right tool here, exactly the Boilerbilges Ripper /
Territorial Bruntar / Fanatic of the Harrowing / Terrapact
Intimidator convention.

Test surface:

  1. Parser SoT — Possibility Technician is parser-claimed and emits
     a ``PossibilityTechnicianETBEffect()`` effect under both ENTERS
     triggers (the compound-predicate two-arm layout for "this
     creature or another Kavu you control enters" — see
     ``cards/parser/triggers.py:_COMPOUND_PREDICATE_TRIGGER_PHRASES``).

  2. Serializer round-trip — a Python
     ``PossibilityTechnicianETBEffect`` and the dict shape
     ``{"kind": "possibility_technician_etb_effect"}`` round-trip
     through the cross_engine bridge identically; the Rust
     ``Effect::PossibilityTechnicianETBEffect`` → dict emits the
     one-key shape.

  3. Rust unit pins:
       3a. Library has [card_A, card_B] → exactly card_A is exiled,
           card_B stays in library.
       3b. Library is empty → silent no-op.
       3c. Library with multiple cards — only the top is exiled
           (single-card-pop semantics, NOT a Bruntar-style walk).

  4. Covered-set membership — the orphan walker recognises
     ``PossibilityTechnicianETBEffect`` as a 1:1 same-named
     Rust/Python match (parser-claimed via Possibility Technician).

  5. **GENUINE real-EoE cross-engine probe** — drives the ACTUAL
     parsed Possibility Technician printing on Python (pre-seated on
     p0's battlefield, NOT cast via warp/normal cost) and a bridged
     synthetic carrier on Rust, then fires the ENTERS+IsSelf ETB
     trigger. Asserts the concrete zone observables (library
     shrinkage by 1 + exile gains 1) plus the full
     ``compare_fields == []`` over the whole cross-engine field view
     (with the ``play_from_exile_requires_kavu`` flag normalised
     symmetric per the honest-stop above). CAVEAT (mirrors
     ``docs/POOL_PARITY.md``): Effect+bridge-level byte-equality on
     a *controlled* cross-engine state, NOT full-game-trajectory
     parity.

NO admit-set change — Possibility Technician is a Creature, not a
spell. Per-card PROBED via the probe below.
"""

from __future__ import annotations

import importlib
import importlib.util
import pathlib
import sys

import pytest

from mtg_bot.cards.source import get_active_source
from mtg_bot.effects.bespoke import PossibilityTechnicianETBEffect


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
    ``test_territorial_bruntar_parity.py`` / ``test_fanatic_of_the_
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


# Canonical Possibility Technician dict shape consumed by Rust's
# ``register_and_inject_object`` to build a synthetic carrier with the
# same self-ENTERS triggered ability as the real parsed printing. The
# probe uses only the ``IsSelf`` arm — the Kavu-observer arm rides the
# same resolve substrate so a single arm suffices for the byte-equal
# observable.
_PT_PRINTING_DICT: dict = {
    "name": "Possibility Technician (synthetic carrier)",
    "card_types": ["Creature"],
    "subtypes": ["Kavu", "Artificer"],
    "power": 3,
    "toughness": 3,
    "mana_cost": {"generic": 2, "R": 1},
    "triggered_abilities": [
        {
            "event": "enters",
            "predicate": {"kind": "source_is_self"},
            "effect": {
                "kind": "possibility_technician_etb_effect",
            },
        },
    ],
}


# ---------------------------------------------------------------------------
# (1) Parser SoT — Possibility Technician is parser-claimed and emits
# the expected PossibilityTechnicianETBEffect under both ENTERS arms.
# ---------------------------------------------------------------------------


def test_possibility_technician_parser_claims_card():
    assert "Possibility Technician" in _PRINTINGS, (
        "Possibility Technician must be parser-claimed by the active "
        "CardSource"
    )


def test_possibility_technician_printed_attrs():
    """Pins the basic printing surface (cost, type, P/T, warp cost).

    Warp is modeled as a printing-level ``warp_cost`` attribute (a
    ManaCost) rather than as a string in ``keywords`` — the
    ``parser/printing_keywords.py:_parse_warp_line`` extracts the
    cost from the printed "Warp {N}{C}..." reminder text and stores
    it as a parsed ManaCost. Pinning the presence of ``warp_cost`` is
    the load-bearing signal that this is the Warp-keyword card the
    probe is intentionally NOT closing the gate for.
    """
    p = _PRINTINGS["Possibility Technician"]
    assert p.mana_cost_str == "{2}{R}"
    assert "Creature" in p.card_types
    assert "Kavu" in p.subtypes
    assert p.power == 3
    assert p.toughness == 3
    # Warp cost present (the gate the probe is NOT closing — see
    # SEARCH_LIMITATIONS.md).
    assert p.warp_cost is not None, (
        "Possibility Technician must carry a parsed warp_cost — the "
        "warp_cost gate is intentionally left open this cycle"
    )


def test_possibility_technician_two_enters_triggers_emit_bespoke_effect():
    """The compound-predicate two-arm layout produces TWO
    ``TriggeredAbility`` entries — both on ``Event.ENTERS``, both with
    a parameterless ``PossibilityTechnicianETBEffect()``. Arm-1 is
    ``IsSelf()``; arm-2 is ``Subject(None, HasSubtype("Kavu")) &
    Controlled(YOU) & ~IsSelf()``.

    Pin the shape so a parser drift is caught here, not silently
    downstream in the cross-engine probe.
    """
    from mtg_bot.effects.predicates import (
        Controlled, Event, IsSelf, Subject, YOU,
    )
    from mtg_bot.effects.object_predicates import HasSubtype

    p = _PRINTINGS["Possibility Technician"]
    enters_tas = [
        ta for ta in p.triggered_abilities if ta.event is Event.ENTERS
    ]
    assert len(enters_tas) == 2, (
        f"Possibility Technician must have exactly 2 ENTERS triggered "
        f"abilities (the compound-predicate two-arm layout for "
        f"'this creature or another Kavu you control enters'); "
        f"got {len(enters_tas)}"
    )
    # Both arms must share the same field-free effect class.
    for ta in enters_tas:
        assert isinstance(ta.effect, PossibilityTechnicianETBEffect), (
            f"ENTERS arm effect must be PossibilityTechnicianETBEffect; "
            f"got {type(ta.effect).__name__}"
        )
        # Field-free unit dataclass — equality with a fresh instance.
        assert ta.effect == PossibilityTechnicianETBEffect()

    # Arm-1 is the self-ETB (IsSelf predicate, no Subject wrapper).
    self_arms = [
        ta for ta in enters_tas if isinstance(ta.predicate, IsSelf)
    ]
    # Arm-2 is the Kavu-observer (predicate has a Subject + Controlled +
    # ~IsSelf composition — produced by ``&`` chaining in
    # ``_COMPOUND_PREDICATE_TRIGGER_PHRASES``).
    other_arms = [
        ta for ta in enters_tas if not isinstance(ta.predicate, IsSelf)
    ]
    assert len(self_arms) == 1, (
        f"exactly one ENTERS arm must use IsSelf; got {len(self_arms)}"
    )
    assert len(other_arms) == 1, (
        f"exactly one ENTERS arm must use the Kavu-observer composite; "
        f"got {len(other_arms)}"
    )


# ---------------------------------------------------------------------------
# (2) Serializer round-trip — Python class -> Rust-shape dict ->
# Python class. Validates the cross_engine bridge arm landed in this
# branch (``_ta_dict_to_python_effect`` ->
# ``possibility_technician_etb_effect`` arm) round-trips the unit
# variant without field drift.
# ---------------------------------------------------------------------------


def test_possibility_technician_effect_dict_to_python_round_trip():
    """Rust-shape dict → Python ``PossibilityTechnicianETBEffect`` via
    ``_ta_dict_to_python_effect`` reconstructs a default-constructed
    instance. Bridge arm is the lever flip — without it, a Rust→Python
    triggered-ability translation would raise on the unknown kind."""
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    d = {"kind": "possibility_technician_etb_effect"}
    rebuilt = _ta_dict_to_python_effect(d)
    assert isinstance(rebuilt, PossibilityTechnicianETBEffect), (
        f"dict→Python bridge must round-trip to "
        f"PossibilityTechnicianETBEffect; got {type(rebuilt).__name__}"
    )
    # Field-free unit dataclass; equality with a fresh instance.
    assert rebuilt == PossibilityTechnicianETBEffect()


@_rust_skip
def test_possibility_technician_rust_effect_to_pydict_round_trip():
    """Rust ``Effect::PossibilityTechnicianETBEffect`` → dict emits
    the expected one-key shape. Drives the round-trip through
    ``Registry.register_printing`` (the parse path) +
    ``get_printing_etb_effects`` (the ``effect_to_pydict`` readback).
    Field-free unit-variant idiom — no other keys in the dict."""
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Possibility Technician Round-trip",
            "card_types": ["Creature"],
            "power": 3,
            "toughness": 3,
            "mana_cost": {"generic": 2, "R": 1},
            "etb_effects": [
                {"kind": "possibility_technician_etb_effect"},
            ],
        }
    )
    effs = reg.get_printing_etb_effects(pid)
    assert len(effs) == 1, f"expected 1 etb_effect, got {len(effs)}"
    eff = effs[0]
    assert eff["kind"] == "possibility_technician_etb_effect"
    # Field-free unit variant — no other keys.
    assert set(eff.keys()) == {"kind"}, (
        f"unit-variant to_pydict must emit ONLY 'kind'; got keys "
        f"{sorted(eff.keys())}"
    )


# ---------------------------------------------------------------------------
# (3) Rust unit pins — drive the new Rust variant via
# register_and_inject_object + push_to_stack (the synthetic-test
# cast-without-cost pipeline that mirrors the Boilerbilges Ripper /
# Fanatic of the Harrowing precedent), and assert the zone-change
# observables on the Rust side directly. Three scenarios: top-card
# exile, empty-library no-op, single-pop semantics.
# ---------------------------------------------------------------------------


def _fresh_rust_state():
    import mtg_bot_engine
    return mtg_bot_engine.make_synthetic_state(0, 0, 0)


def _inject_filler_card(rs, owner: int, name_suffix: str, zone: int) -> int:
    """Inject a vanilla Instant filler into ``owner``'s ``zone``.
    Returns the object id."""
    return rs.register_and_inject_object(
        {
            "name": f"PT Filler {name_suffix}",
            "card_types": ["Instant"],
            "mana_cost": {"R": 1},
        },
        owner,
        zone,
    )


def _inject_pt_in_hand(rs, owner: int = 0) -> int:
    """Inject a Possibility-Technician-shape creature into ``owner``'s
    HAND. The caller then casts by ``rs.push_to_stack(pt_id, owner);
    rs.resolve_top_of_stack()`` — the synthetic-test cast-without-cost
    pipeline (mirrors Boilerbilges Ripper / Fanatic of the Harrowing).
    This drives the standard spell-resolution pipeline that lands the
    permanent on the bf AND fires its ETB trigger automatically, while
    BYPASSING the warp_cost cost-payment path."""
    return rs.register_and_inject_object(
        _PT_PRINTING_DICT,
        owner,
        ZONE_HAND,
    )


def _cast_pt_and_resolve_all(rs, pt_id: int, controller: int = 0):
    """Cast the Possibility Technician from ``controller``'s HAND via
    the standard spell-resolution pipeline (push_to_stack + drain).
    The cast resolves Possibility Technician onto bf AND queues the
    ETB trigger; the trigger then resolves into the Cycle 1 exile-
    top-of-library body."""
    rs.push_to_stack(pt_id, controller)
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()


@_rust_skip
def test_rust_resolve_exiles_top_of_library():
    """Library top = filler card; the ETB resolves into exile-top-of-
    library. The top filler ends up in exile; deeper cards stay in
    library."""
    rs = _fresh_rust_state()

    # Build library bottom-first so the last-injected lands at lib[0]
    # (top). Library top-to-bottom = [top_filler, deeper_filler].
    p0_deeper = _inject_filler_card(
        rs, owner=0, name_suffix="deeper", zone=ZONE_LIBRARY,
    )
    p0_top = _inject_filler_card(
        rs, owner=0, name_suffix="top", zone=ZONE_LIBRARY,
    )

    pt = _inject_pt_in_hand(rs, owner=0)
    rs.clear_summoning_sick_for_player(0)

    lib_before = [e["id"] for e in rs.library_snapshot(0)]
    assert lib_before == [p0_top, p0_deeper], (
        f"library top-to-bottom mismatch pre-resolve; got {lib_before}"
    )
    exile_before = [e["id"] for e in rs.exile_snapshot(0)]
    assert exile_before == []

    _cast_pt_and_resolve_all(rs, pt, controller=0)

    # PT now on bf; top of library now exiled; deeper card stays in
    # library.
    bf_ids = [e["id"] for e in rs.battlefield_snapshot()]
    assert pt in bf_ids, "PT must be on bf post-cast"
    lib_after = [e["id"] for e in rs.library_snapshot(0)]
    assert lib_after == [p0_deeper], (
        f"deeper card must stay in library; got {lib_after}"
    )
    exile_after = [e["id"] for e in rs.exile_snapshot(0)]
    assert exile_after == [p0_top], (
        f"only the top card must be in exile; got {exile_after}"
    )


@_rust_skip
def test_rust_resolve_empty_library_silent_no_op():
    """Library is empty at ETB-resolve time — the resolve arm
    short-circuits to silent no-op. No state mutation beyond PT
    landing on bf."""
    rs = _fresh_rust_state()

    # Empty library on p0.
    pt = _inject_pt_in_hand(rs, owner=0)
    rs.clear_summoning_sick_for_player(0)

    lib_before = [e["id"] for e in rs.library_snapshot(0)]
    assert lib_before == []
    exile_before = [e["id"] for e in rs.exile_snapshot(0)]
    assert exile_before == []

    _cast_pt_and_resolve_all(rs, pt, controller=0)

    # PT on bf, library still empty, exile still empty.
    bf_ids = [e["id"] for e in rs.battlefield_snapshot()]
    assert pt in bf_ids, "PT must be on bf post-cast"
    lib_after = [e["id"] for e in rs.library_snapshot(0)]
    assert lib_after == []
    exile_after = [e["id"] for e in rs.exile_snapshot(0)]
    assert exile_after == []


@_rust_skip
def test_rust_resolve_only_top_exiled_not_a_walk():
    """Single-card-pop semantics: with a multi-card library, only the
    TOP card is exiled per fire (NOT a Territorial-Bruntar-style walk-
    until-non-land). Pin the distinguishing observable."""
    rs = _fresh_rust_state()

    # Library top-to-bottom = [card_A, card_B, card_C].
    p0_c = _inject_filler_card(
        rs, owner=0, name_suffix="C", zone=ZONE_LIBRARY,
    )
    p0_b = _inject_filler_card(
        rs, owner=0, name_suffix="B", zone=ZONE_LIBRARY,
    )
    p0_a = _inject_filler_card(
        rs, owner=0, name_suffix="A", zone=ZONE_LIBRARY,
    )

    pt = _inject_pt_in_hand(rs, owner=0)
    rs.clear_summoning_sick_for_player(0)

    lib_before = [e["id"] for e in rs.library_snapshot(0)]
    assert lib_before == [p0_a, p0_b, p0_c], (
        f"library top-to-bottom mismatch pre-resolve; got {lib_before}"
    )

    _cast_pt_and_resolve_all(rs, pt, controller=0)

    # Only the top (A) is exiled; B + C stay in library in order.
    lib_after = [e["id"] for e in rs.library_snapshot(0)]
    assert lib_after == [p0_b, p0_c], (
        f"deeper cards B + C must stay in library; got {lib_after}"
    )
    exile_after = [e["id"] for e in rs.exile_snapshot(0)]
    assert exile_after == [p0_a], (
        f"exactly the top card A must be exiled; got {exile_after}"
    )


# ---------------------------------------------------------------------------
# (4) Covered-set membership — the orphan walker recognises the new
# Rust variant PossibilityTechnicianETBEffect as a 1:1 same-named
# match against the parser-claimed Python class.
# ---------------------------------------------------------------------------


def test_possibility_technician_class_covered_by_rust():
    """The Python class is in the parser-emitted covered set
    (Possibility Technician claims it) and the Rust variant has the
    SAME name, so the orphan walker pairs them 1:1 without an
    override or RUST_AHEAD_OF_POOL allowlist entry."""
    from mtg_bot.parity.effect_coverage import (
        collect_python_effect_vocab,
        collect_rust_effect_variants,
        covered_python_class_set,
    )

    py_classes, _examples, _n = collect_python_effect_vocab()
    assert "PossibilityTechnicianETBEffect" in py_classes, (
        "Possibility Technician must surface "
        "PossibilityTechnicianETBEffect in the parser-walked Python "
        "effect vocab"
    )
    rust_variants = collect_rust_effect_variants()
    assert "PossibilityTechnicianETBEffect" in rust_variants, (
        "the new Rust Effect variant must be discoverable by the "
        "cards.rs text parser"
    )
    covered = covered_python_class_set()
    assert "PossibilityTechnicianETBEffect" in covered, (
        "the new Rust variant pairs 1:1 with the parser-claimed "
        "Python class (no override / RUST_AHEAD_OF_POOL allowlist "
        "needed)"
    )


# ---------------------------------------------------------------------------
# (5) GENUINE real-EoE cross-engine byte-equal probe — drives the
# ACTUAL parsed Possibility Technician printing on Python and a bridged
# synthetic carrier on Rust. After firing the ENTERS+IsSelf ETB
# trigger, asserts the concrete zone observables (library shrinkage by
# 1 + exile gains 1) plus the full ``compare_fields == []`` over the
# whole cross-engine field view.
#
# Scenario: PT pre-seated on p0's bf on both engines (NOT cast via the
# warp/normal cost path — the warp_cost gate is intentionally NOT
# closed this cycle). p0's library is seeded with [top_filler,
# deeper_filler]. The ETB trigger is fired via dispatch_event on
# Python and apply_effect_pub-equivalent on Rust (via a synthetic-state
# cast-without-cost push_to_stack path that bypasses the warp cost).
#
# After resolve:
#   - top_filler is in p0's exile; deeper_filler stays in p0's library;
#   - PT stays on p0's bf;
#   - the ``play_from_exile_requires_kavu`` flag is normalised
#     symmetric before the whole-view compare.
# ---------------------------------------------------------------------------


@_rust_skip
def test_cross_engine_real_eoe_possibility_technician_etb_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Possibility Technician
    ETB exile-top-of-library path.**

    Python: the ACTUAL parsed Possibility Technician printing pre-
    seated on p0's battlefield (no cast path → bypasses both the warp
    cost path AND the normal cost path; the IsSelf-ENTERS trigger is
    fired by an explicit ``dispatch_event(Event.ENTERS, obj=pt)`` after
    seating). p0's library is seeded with top-to-bottom [top_filler,
    deeper_filler].

    Rust: bridged synthetic carrier carrying the same ENTERS+IsSelf
    trigger + ``possibility_technician_etb_effect`` effect dict; p0's
    library is seeded identically. The synthetic-test cast-without-
    cost push_to_stack path drives the trigger fire (bypasses the
    warp_cost gate).

    Assertion strength: **full ``compare_fields == []``** over the
    whole cross-engine field view (every zone, both players), PLUS
    the concrete zone observables (library shrinkage from 2 cards to
    1 card + exile additions of the top filler on BOTH engines).

    The exiled card's ``play_from_exile_requires_kavu`` flag is
    honest-stopped on the Rust side and normalised symmetric on the
    Python side before the whole-view compare (see
    SEARCH_LIMITATIONS.md). Possibility Technician's
    ``summoning_sick`` is normalised symmetric on both engines
    (Python's pre-seated bf object defaults to summoning-sick=True;
    Rust's ``register_and_inject_object`` defaults to False — same
    fixture-asymmetry idiom Icecave Crasher / Genemorph Imago
    batch-B handle).
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
    )
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.actions import dispatch_event, resolve_top_of_stack
    from mtg_bot.game import Zone
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.predicates import Event, IsSelf

    real = _PRINTINGS.get("Possibility Technician")
    if real is None:
        pytest.skip(
            "Possibility Technician absent from active CardSource"
        )
    assert "Creature" in real.card_types

    # §2 source-of-truth: verify the genuine printing carries the
    # self-ENTERS arm + PossibilityTechnicianETBEffect (the arm the
    # probe fires).
    self_etb_ta = next(
        (
            ta for ta in real.triggered_abilities
            if (
                ta.event is Event.ENTERS
                and isinstance(ta.predicate, IsSelf)
                and isinstance(ta.effect, PossibilityTechnicianETBEffect)
            )
        ),
        None,
    )
    assert self_etb_ta is not None, (
        "Possibility Technician must carry an ENTERS+IsSelf+"
        "PossibilityTechnicianETBEffect arm (one of the two ENTERS "
        "trigger arms emitted by the compound-predicate two-arm "
        "layout)"
    )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZH = 0
    ZL = 1

    # Synthetic vanilla filler printings on the Python side
    # (matching the Rust register_and_inject_object dicts byte-for-
    # byte).
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

    # ---- Probe strategy: seat PT in HAND on BOTH engines + drive
    # the cast via the synthetic-test push_to_stack pipeline (the
    # Boilerbilges Ripper / Fanatic of the Harrowing precedent). The
    # synthetic-test push_to_stack path BYPASSES the cost-payment
    # machinery — neither the normal {2}{R} cost NOR the warp_cost
    # gate is exercised. The resolve lands PT on bf AND queues the
    # ETB+IsSelf trigger; the trigger then resolves the exile-top-
    # of-library body.
    #
    # This is the established Warp-keyword-card-probe convention
    # (Boilerbilges Ripper / Codecracker Hound both inject in hand
    # and push_to_stack without invoking warp cost).
    #
    # ---- Python: seat the genuine parsed PT in p0's hand; seed
    # p0's library with [top_filler, deeper_filler] top-to-bottom.
    py_pt = py.new_object(real, owner_id=0, zone=Zone.HAND)
    py.players[0].hand.append(py_pt)

    # Allocate library objects bottom-first so IDs align with Rust's
    # register-bottom-first convention (Rust pushes onto lib[0]).
    py_lib_deeper = py.new_object(
        _instant_printing("PT Filler deeper"),
        owner_id=0,
        zone=Zone.LIBRARY,
    )
    py_lib_top = py.new_object(
        _instant_printing("PT Filler top"),
        owner_id=0,
        zone=Zone.LIBRARY,
    )
    # Normalise summoning_sick=False on library cards (Python's
    # new_object defaults summoning_sick=True for cards-in-library
    # while Rust's register_and_inject_object defaults to False — the
    # Territorial Bruntar / Icecave Crasher / Genemorph Imago
    # fixture-asymmetry idiom).
    for _obj in (py_lib_top, py_lib_deeper):
        _obj.summoning_sick = False
    py.players[0].library.extend([py_lib_top, py_lib_deeper])

    # ---- Rust: seat the bridged synthetic PT carrier in p0's hand;
    # seed p0's library identically.
    #
    # Library-injection order: ``register_and_inject_object`` pushes
    # onto ``lib[0]`` (the TOP), so to build a library with top-to-
    # bottom = [top, deeper] we register deeper FIRST, then top.
    # Use the REAL printing's name on the Rust carrier so the
    # battlefield field-view tuple's name slot agrees byte-equal with
    # Python's actual parsed PT (post-cast it'll be on the bf with
    # the matching name).
    pt_carrier_for_probe = dict(_PT_PRINTING_DICT)
    pt_carrier_for_probe["name"] = real.name
    rs_pt = rs.register_and_inject_object(
        pt_carrier_for_probe, 0, ZH,
    )
    rs_lib_deeper = rs.register_and_inject_object(
        {
            "name": "PT Filler deeper",
            "card_types": ["Instant"],
            "mana_cost": {"R": 1},
        },
        0, ZL,
    )
    rs_lib_top = rs.register_and_inject_object(
        {
            "name": "PT Filler top",
            "card_types": ["Instant"],
            "mana_cost": {"R": 1},
        },
        0, ZL,
    )
    rs.clear_summoning_sick_for_player(0)

    # Sanity: library top-to-bottom matches Python's order.
    rs_lib_check = [e["id"] for e in rs.library_snapshot(0)]
    assert rs_lib_check == [rs_lib_top, rs_lib_deeper], (
        f"Rust library top-to-bottom mismatch pre-trigger; got "
        f"{rs_lib_check}"
    )

    # Pre-cast sanity: no trigger fires during seeding (PT is in
    # hand, the library fillers are vanilla instants).
    assert rs.stack_size() == 0 and len(py.stack) == 0

    # ---- Fire the cast on BOTH (synthetic-test cast-without-cost
    # path). ----
    #
    # **Python.** Move PT from hand → bf manually (the cast-
    # resolution zone change). Fire ENTERS via ``dispatch_event``;
    # the IsSelf trigger queues on the stack with the
    # PossibilityTechnicianETBEffect bound; drain the stack to
    # resolve into the exile-top-of-library body. Mirrors the
    # Fanatic of the Harrowing / Boilerbilges Ripper Python-side
    # convention exactly.
    py.players[0].hand.remove(py_pt)
    py_pt.zone = Zone.BATTLEFIELD
    # summoning_sick=True matches the Rust cast-pipeline default
    # (CR 302.1 — permanents enter with summoning sickness).
    py_pt.summoning_sick = True
    py_pt.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_pt)
    dispatch_event(py, Event.ENTERS, label="enters", obj=py_pt)
    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)

    # **Rust.** Push PT onto the stack via ``push_to_stack`` (the
    # cast-without-cost synthetic-test pipeline). The spell-resolve
    # lands PT on bf, queues the ETB+IsSelf trigger, and the
    # trigger resolves into the Rust resolve arm. Avoids the
    # warp_cost gate AND the normal cost-payment gate by using the
    # low-level push API.
    rs.push_to_stack(rs_pt, 0)
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert len(py.stack) == 0 and rs.stack_size() == 0

    # ---- Python observables. ----
    # Library should be [deeper_filler] only.
    py_lib_ids = [o.id for o in py.players[0].library]
    assert py_lib_ids == [py_lib_deeper.id], (
        f"Python: library must be [deeper_filler] post-resolve; "
        f"got {py_lib_ids}"
    )
    # Exile should be [top_filler].
    py_exile_ids = [o.id for o in py.players[0].exile]
    assert py_exile_ids == [py_lib_top.id], (
        f"Python: exile must be [top_filler]; got {py_exile_ids}"
    )
    # PT still on bf.
    assert py_pt in py.battlefield

    # ---- Rust observables. ----
    rs_lib_ids = [e["id"] for e in rs.library_snapshot(0)]
    assert rs_lib_ids == [rs_lib_deeper], (
        f"Rust: library must be [deeper_filler] post-resolve; "
        f"got {rs_lib_ids}"
    )
    rs_exile_ids = [e["id"] for e in rs.exile_snapshot(0)]
    assert rs_exile_ids == [rs_lib_top], (
        f"Rust: exile must be [top_filler]; got {rs_exile_ids}"
    )
    # PT still on bf.
    rs_bf_ids = [e["id"] for e in rs.battlefield_snapshot()]
    assert rs_pt in rs_bf_ids

    # ---- Pre-compare normalisation (honest-stop + fixture-
    # asymmetry). ----
    # The ``play_from_exile_requires_kavu`` flag on the exiled top
    # card: Python sets it True; Rust has no such field. Reset the
    # Python side to its default-False so the cross-engine field view
    # aligns (the honest-stop documented in SEARCH_LIMITATIONS.md).
    for o in py.players[0].exile:
        if hasattr(o, "play_from_exile_requires_kavu"):
            o.play_from_exile_requires_kavu = False

    # ---- Full field-view byte-equality over the WHOLE state. ----
    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Possibility Technician ETB PossibilityTechnicianETBEffect "
        f"must be byte-equal across the WHOLE field view on BOTH "
        f"engines (with play_from_exile_requires_kavu normalised "
        f"symmetric); diffs={diffs}"
    )
