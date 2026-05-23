"""Wickerfolk Thresher Cycle 1 — `PeekTopMayBattlefieldIfLandElseHand`
Rust Effect substrate close + per-card cross-engine byte-equal probe.

Wickerfolk Thresher is a `{3}{G}` Artifact Creature — Scarecrow (5/4)
whose Delirium attack trigger peeks the controller's library top and
routes the card to battlefield (if Land + agent says yes) or to hand
(everything else):

    "Delirium — Whenever this creature attacks, if there are four or
    more card types among cards in your graveyard, look at the top
    card of your library. If it's a land card, you may put it onto
    the battlefield. If you don't put the card onto the battlefield,
    put it into your hand."

This module pins the Rust `Effect::PeekTopMayBattlefieldIfLandElseHand`
variant landed in this branch + the matching cross_engine bridge arm
+ a genuine real-EoE / DSK cross-engine byte-equal probe driving the
ATTACKS trigger end-to-end on a synthetic Rust carrier (mirroring the
Comet Crawler / Territorial Bruntar / Boilerbilges Ripper precedent
— per-card real-printing probe with a synthetic Rust carrier that
shares the Effect class but uses a simpler trigger predicate, so the
Rust side doesn't need the state-predicate substrate to drive the
probe).

**Multi-gated card; classifier stays multi-gated.** Per the round-58
subsystem-attribution classifier
(``scripts/scout_r58_subsystem_attribution.py``), Wickerfolk Thresher
is multi-gated:

  * ``effect_uncovered`` — closed by this cycle. The new Rust variant
    ``Effect::PeekTopMayBattlefieldIfLandElseHand`` makes the Python
    class ``PeekTopMayBattlefieldIfLandElseHand`` covered via the 1:1
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
per-card real-EoE byte-equal cross-engine probe that flips Wickerfolk
Thresher to PROBED tier. Same precedent as
``test_territorial_bruntar_parity.py``,
``test_terrapact_intimidator_parity.py``,
``test_boilerbilges_ripper_parity.py``,
``test_comet_crawler_parity.py``, and
``test_fanatic_of_the_harrowing_parity.py``: a per-card probe
drives the real printing through both engines and pins byte-equal
observables on the no-agent branch; the safe-trigger bench admit set
is widened in a separate cycle when the production-deck bench needs
it.

**NOT a spell-card-bridge admit-set extension.** Wickerfolk Thresher
is an Artifact Creature, not a non-creature spell. The
spell-card-bridge admit set (``trajectory.py::
_python_spell_effect_to_dict`` + its §2 teeth) gates non-creature
spells only. The per-card probe approach is the right tool here,
exactly the Territorial Bruntar / Comet Crawler / Boilerbilges
Ripper convention.

**HONEST-STOP #1: agent-yes / land-onto-battlefield branch NOT
mirrored on Rust.** Python's
``PeekTopMayBattlefieldIfLandElseHand.resolve`` routes a Land top
card through ``put_into_battlefield`` if the controller has an agent
and that agent answers ``choose_yes_no(...) == True``; the land
enters the battlefield untapped, firing landfall + any other ETB
triggers. Rust has no agent surface and no library-to-battlefield-
with-ETB-fan-out substrate wired into the Effect dispatcher today;
this branch is honest-stopped (same shape as Boilerbilges Ripper /
Terrapact Intimidator agent gates — Cycle 1 lands ONLY the no-agent
mirror). The cross-engine probe drives BOTH engines with no agent
surface (Python's ``p.agent = None``), so byte-equal observables
hold on the no-agent path. Documented as a deliberate divergence in
``docs/SEARCH_LIMITATIONS.md``.

**HONEST-STOP #2: Delirium state-predicate substrate NOT mirrored on
Rust.** Python's real Wickerfolk Thresher trigger gate is
``And(IsSelf, StateBound(Delirium))`` — Delirium checks 4+ distinct
card types in the controller's graveyard. Rust has no
``StateBound`` predicate kind and no ``Delirium`` state predicate;
both would need substrate work outside this cycle's Effect-class
scope. The probe sidesteps this by giving the Rust synthetic carrier
a simpler ``source_is_self`` predicate (no Delirium gate); on the
Python side we seed the graveyard with 4+ card types so Delirium IS
satisfied and the real trigger fires. Both engines push the trigger
and resolve to library→hand on the no-agent path; the byte-equal
field-view compare sees the same graveyard contents + the same
library→hand zone change on both sides. This is exactly the
synthetic-carrier-shape-narrowing trick the Comet Crawler /
Territorial Bruntar precedent already uses.

Test surface:

  1. Parser SoT — Wickerfolk Thresher is parser-claimed and emits a
     ``PeekTopMayBattlefieldIfLandElseHand()`` effect under an
     ATTACKS trigger with ``And(IsSelf, StateBound(Delirium))``.

  2. Serializer round-trip — a Python
     ``PeekTopMayBattlefieldIfLandElseHand`` constructs the dict
     shape
     ``{"kind": "peek_top_may_battlefield_if_land_else_hand"}`` and
     the cross_engine bridge translates it back identically.

  3. Rust unit pins:
       3a. Library top is a Land → land moves to hand on no-agent
           branch (Rust mirrors the no-agent path; agent-yes / bf
           branch is honest-stopped).
       3b. Library top is a non-Land → non-land moves to hand.
       3c. Library is empty → silent no-op.

  4. Covered-set membership — the orphan walker recognises
     ``PeekTopMayBattlefieldIfLandElseHand`` as a 1:1 same-named
     Rust/Python match (parser-claimed via Wickerfolk Thresher).

  5. **GENUINE real-EoE / DSK cross-engine probe** — drives the
     ACTUAL parsed Wickerfolk Thresher printing on Python and a
     bridged synthetic carrier on Rust, then declares an attacker
     to fire the ATTACKS trigger. Asserts the concrete zone
     observables (library top moves to hand on BOTH engines) plus
     the full ``compare_fields == []`` over the whole cross-engine
     field view.

NO admit-set change — Wickerfolk Thresher is a Creature, not a
spell. Per-card PROBED via the probe below.
"""

from __future__ import annotations

import importlib
import importlib.util
import pathlib
import sys

import pytest

from mtg_bot.cards.source import get_active_source
from mtg_bot.effects.generic.library_lookat import (
    PeekTopMayBattlefieldIfLandElseHand,
)


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
    ``test_territorial_bruntar_parity.py`` /
    ``test_comet_crawler_parity.py``."""
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


# Canonical Wickerfolk Thresher synthetic carrier dict consumed by
# Rust's ``register_and_inject_object``. NOTE: the predicate is the
# simpler ``source_is_self`` (NOT the real ``IsSelf + StateBound(
# Delirium)`` shape) — Rust has no ``StateBound`` / ``Delirium``
# substrate; the synthetic carrier deliberately strips the Delirium
# gate so the trigger fires unconditionally on attack. The Python
# side uses the REAL parsed printing (with Delirium gate); the probe
# seeds Python's graveyard with 4+ card types so the gate fires on
# Python too. See the module docstring "HONEST-STOP #2" block.
_THRESHER_PRINTING_DICT: dict = {
    "name": "Wickerfolk Thresher (synthetic carrier)",
    "card_types": ["Artifact", "Creature"],
    "power": 5,
    "toughness": 4,
    "mana_cost": {"generic": 3, "G": 1},
    "triggered_abilities": [
        {
            "event": "attacks",
            "predicate": {"kind": "source_is_self"},
            "effect": {
                "kind": "peek_top_may_battlefield_if_land_else_hand",
            },
        },
    ],
}


# ---------------------------------------------------------------------------
# (1) Parser SoT — Wickerfolk Thresher is parser-claimed and emits the
# expected PeekTopMayBattlefieldIfLandElseHand under the Delirium-gated
# ATTACKS trigger.
# ---------------------------------------------------------------------------


def test_wickerfolk_thresher_parser_claims_card():
    assert "Wickerfolk Thresher" in _PRINTINGS, (
        "Wickerfolk Thresher must be parser-claimed by the active "
        "CardSource"
    )


def test_wickerfolk_thresher_printed_attrs():
    """Pins the basic printing surface (cost, type, P/T)."""
    p = _PRINTINGS["Wickerfolk Thresher"]
    assert p.mana_cost_str == "{3}{G}"
    assert "Artifact" in p.card_types
    assert "Creature" in p.card_types
    assert "Scarecrow" in p.subtypes
    assert p.power == 5
    assert p.toughness == 4


def test_wickerfolk_thresher_attacks_trigger_emits_peek_route_effect():
    """The parser emits exactly ONE triggered ability — the Delirium-
    gated ATTACKS trigger pairing ``And(IsSelf, StateBound(Delirium))``
    with a ``PeekTopMayBattlefieldIfLandElseHand()`` (parameterless
    frozen dataclass)."""
    from mtg_bot.effects.predicates import And, Event, IsSelf, StateBound
    from mtg_bot.effects.state_predicates import Delirium

    p = _PRINTINGS["Wickerfolk Thresher"]
    assert len(p.triggered_abilities) == 1, (
        "Wickerfolk Thresher must carry exactly one triggered ability "
        "(the Delirium attack trigger); spurious abilities indicate "
        "parser drift"
    )
    ta = p.triggered_abilities[0]
    assert ta.event is Event.ATTACKS, (
        f"trigger must dispatch on ATTACKS; got {ta.event}"
    )
    pred = ta.predicate
    assert isinstance(pred, And), (
        f"predicate must be And; got {type(pred).__name__}"
    )
    assert isinstance(pred.left, IsSelf), (
        f"left branch must be IsSelf; got {type(pred.left).__name__}"
    )
    assert isinstance(pred.right, StateBound), (
        f"right branch must be StateBound; got {type(pred.right).__name__}"
    )
    assert isinstance(pred.right.inner, Delirium), (
        f"StateBound inner must be Delirium; "
        f"got {type(pred.right.inner).__name__}"
    )
    eff = ta.effect
    assert isinstance(eff, PeekTopMayBattlefieldIfLandElseHand), (
        f"effect must be PeekTopMayBattlefieldIfLandElseHand; "
        f"got {type(eff).__name__}"
    )
    # Field-free unit dataclass — equality with a fresh instance.
    assert eff == PeekTopMayBattlefieldIfLandElseHand()


# ---------------------------------------------------------------------------
# (2) Serializer round-trip — Python class -> Rust-shape dict ->
# Python class. Validates the cross_engine bridge arm landed in this
# branch (``_ta_dict_to_python_effect`` ->
# ``peek_top_may_battlefield_if_land_else_hand`` arm) round-trips the
# unit variant without field drift.
# ---------------------------------------------------------------------------


def test_wickerfolk_thresher_effect_dict_to_python_round_trip():
    """Rust-shape dict → Python ``PeekTopMayBattlefieldIfLandElseHand``
    via ``_ta_dict_to_python_effect`` reconstructs a default-
    constructed instance. Bridge arm is the lever flip — without it,
    a Rust→Python triggered-ability translation would raise on the
    unknown kind."""
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    d = {"kind": "peek_top_may_battlefield_if_land_else_hand"}
    rebuilt = _ta_dict_to_python_effect(d)
    assert isinstance(rebuilt, PeekTopMayBattlefieldIfLandElseHand), (
        f"dict→Python bridge must round-trip to "
        f"PeekTopMayBattlefieldIfLandElseHand; "
        f"got {type(rebuilt).__name__}"
    )
    # Field-free unit dataclass; equality with a fresh instance.
    assert rebuilt == PeekTopMayBattlefieldIfLandElseHand()


@_rust_skip
def test_wickerfolk_thresher_rust_effect_to_pydict_round_trip():
    """Rust ``Effect::PeekTopMayBattlefieldIfLandElseHand`` → dict
    emits the expected one-key shape. Drives the round-trip through
    ``Registry.register_printing`` (the parse path) +
    ``get_printing_etb_effects`` (the ``effect_to_pydict`` readback).

    NB: we use ``etb_effects`` here purely because that's the
    readback Registry surface; the production parser routes
    Wickerfolk Thresher's effect through the triggered-ability path,
    but the to_pydict round-trip is structurally agnostic to
    where the Effect is parked (the round-trip just exercises
    parse_effect + effect_to_pydict on the variant).
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Wickerfolk Thresher Round-trip",
            "card_types": ["Artifact", "Creature"],
            "power": 5,
            "toughness": 4,
            "mana_cost": {"generic": 3, "G": 1},
            "etb_effects": [
                {"kind": "peek_top_may_battlefield_if_land_else_hand"},
            ],
        }
    )
    effs = reg.get_printing_etb_effects(pid)
    assert len(effs) == 1, f"expected 1 etb_effect, got {len(effs)}"
    eff = effs[0]
    assert eff["kind"] == "peek_top_may_battlefield_if_land_else_hand"
    # Field-free unit variant — no other keys.
    assert set(eff.keys()) == {"kind"}, (
        f"unit-variant to_pydict must emit ONLY 'kind'; got keys "
        f"{sorted(eff.keys())}"
    )


# ---------------------------------------------------------------------------
# (3) Rust unit pins — drive the new Rust variant via
# register_and_inject_object + the existing ATTACKS-trigger pathway,
# and assert the zone-change observables on the Rust side directly.
# Three scenarios: land top → hand (no-agent branch), non-land top →
# hand, empty library → silent no-op.
# ---------------------------------------------------------------------------


def _fresh_rust_state():
    import mtg_bot_engine
    return mtg_bot_engine.make_synthetic_state(0, 0, 0)


def _inject_filler_land(rs, owner: int, name_suffix: str, zone: int) -> int:
    """Inject a vanilla Forest into ``owner``'s ``zone``. Returns the
    object id."""
    return rs.register_and_inject_object(
        {
            "name": f"Thresher Forest {name_suffix}",
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
            "name": f"Thresher Instant {name_suffix}",
            "card_types": ["Instant"],
            "mana_cost": {"R": 1},
        },
        owner,
        zone,
    )


def _inject_thresher_on_bf(rs, owner: int = 0) -> int:
    return rs.register_and_inject_object(
        _THRESHER_PRINTING_DICT,
        owner,
        ZONE_BATTLEFIELD,
    )


@_rust_skip
def test_rust_resolve_land_top_goes_to_hand_no_agent_branch():
    """Library top is a Land — on the no-agent branch (Rust has no
    agent surface), the land moves to hand. Deeper cards stay in
    library.

    Note on registration order: ``register_and_inject_object`` pushes
    onto ``lib[0]`` (the TOP), so to build a library with top-to-
    bottom = [land, deeper-non-land] we register from bottom-to-top —
    deeper first, the top land LAST.
    """
    rs = _fresh_rust_state()

    # Build library in REVERSE (bottom first). Library top-to-bottom
    # = [land, deeper-non-land].
    p0_deeper_nonland = _inject_filler_nonland(
        rs, owner=0, name_suffix="deeper", zone=ZONE_LIBRARY,
    )
    p0_land_top = _inject_filler_land(
        rs, owner=0, name_suffix="top", zone=ZONE_LIBRARY,
    )

    thresher = _inject_thresher_on_bf(rs, owner=0)
    rs.clear_summoning_sick_for_player(0)

    lib_before = [e["id"] for e in rs.library_snapshot(0)]
    assert lib_before == [p0_land_top, p0_deeper_nonland], (
        f"library top-to-bottom mismatch pre-resolve; got {lib_before}"
    )
    hand_before = [e["id"] for e in rs.hand_snapshot(0)]
    assert hand_before == []

    # Declare attacker, drain the trigger.
    assert rs.declare_attacker(thresher) is True
    assert rs.stack_size() == 1, "ATTACKS trigger must push"
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()

    # The top land is now in hand; deeper non-land stays in library.
    lib_after = [e["id"] for e in rs.library_snapshot(0)]
    assert lib_after == [p0_deeper_nonland], (
        f"deeper non-land must stay in library; got {lib_after}"
    )
    hand_after = [e["id"] for e in rs.hand_snapshot(0)]
    assert hand_after == [p0_land_top], (
        f"top land must move to hand on no-agent branch; "
        f"got {hand_after}"
    )


@_rust_skip
def test_rust_resolve_nonland_top_goes_to_hand():
    """Library top is a non-Land — moves to hand (the printed
    ``else`` branch in Python; no agent gate involved because
    is_land = False short-circuits the agent ask)."""
    rs = _fresh_rust_state()

    # Library top-to-bottom = [non-land, land].
    p0_deeper_land = _inject_filler_land(
        rs, owner=0, name_suffix="deeper", zone=ZONE_LIBRARY,
    )
    p0_nonland_top = _inject_filler_nonland(
        rs, owner=0, name_suffix="top", zone=ZONE_LIBRARY,
    )

    thresher = _inject_thresher_on_bf(rs, owner=0)
    rs.clear_summoning_sick_for_player(0)

    lib_before = [e["id"] for e in rs.library_snapshot(0)]
    assert lib_before == [p0_nonland_top, p0_deeper_land]

    assert rs.declare_attacker(thresher) is True
    assert rs.stack_size() == 1
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()

    # The non-land moved to hand; deeper land stays in library.
    lib_after = [e["id"] for e in rs.library_snapshot(0)]
    assert lib_after == [p0_deeper_land], (
        f"deeper land must stay in library; got {lib_after}"
    )
    hand_after = [e["id"] for e in rs.hand_snapshot(0)]
    assert hand_after == [p0_nonland_top], (
        f"top non-land must move to hand; got {hand_after}"
    )


@_rust_skip
def test_rust_resolve_empty_library_silent_no_op():
    """Library is empty at trigger-resolve time — the resolve arm
    short-circuits with no state mutation."""
    rs = _fresh_rust_state()

    # Empty library on p0. Thresher on p0's bf.
    thresher = _inject_thresher_on_bf(rs, owner=0)
    rs.clear_summoning_sick_for_player(0)

    lib_before = [e["id"] for e in rs.library_snapshot(0)]
    assert lib_before == []
    hand_before = [e["id"] for e in rs.hand_snapshot(0)]
    assert hand_before == []
    p0_life_before = rs.get_life(0)

    assert rs.declare_attacker(thresher) is True
    assert rs.stack_size() == 1
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()

    # Library still empty; nothing moved to hand.
    lib_after = [e["id"] for e in rs.library_snapshot(0)]
    assert lib_after == []
    hand_after = [e["id"] for e in rs.hand_snapshot(0)]
    assert hand_after == []
    # No life change either (defense-in-depth — purely observational).
    assert rs.get_life(0) == p0_life_before


# ---------------------------------------------------------------------------
# (4) Covered-set membership — the orphan walker recognises the new
# Rust variant PeekTopMayBattlefieldIfLandElseHand as a 1:1 same-named
# match against the parser-claimed Python class.
# ---------------------------------------------------------------------------


def test_wickerfolk_thresher_class_covered_by_rust():
    """The Python class is in the parser-emitted covered set
    (Wickerfolk Thresher claims it) and the Rust variant has the
    SAME name, so the orphan walker pairs them 1:1 without an
    override or RUST_AHEAD_OF_POOL allowlist entry."""
    from mtg_bot.parity.effect_coverage import (
        collect_python_effect_vocab,
        collect_rust_effect_variants,
        covered_python_class_set,
    )

    py_classes, _examples, _n = collect_python_effect_vocab()
    assert "PeekTopMayBattlefieldIfLandElseHand" in py_classes, (
        "Wickerfolk Thresher must surface "
        "PeekTopMayBattlefieldIfLandElseHand in the parser-walked "
        "Python effect vocab"
    )
    rust_variants = collect_rust_effect_variants()
    assert "PeekTopMayBattlefieldIfLandElseHand" in rust_variants, (
        "the new Rust Effect variant must be discoverable by the "
        "cards.rs text parser"
    )
    covered = covered_python_class_set()
    assert "PeekTopMayBattlefieldIfLandElseHand" in covered, (
        "the new Rust variant pairs 1:1 with the parser-claimed "
        "Python class (no override / RUST_AHEAD_OF_POOL allowlist "
        "needed)"
    )


# ---------------------------------------------------------------------------
# (5) GENUINE real-EoE / DSK cross-engine byte-equal probe — drives
# the ACTUAL parsed Wickerfolk Thresher printing on Python and a
# bridged synthetic carrier on Rust. After declaring an attacker to
# fire the ATTACKS trigger, asserts the concrete zone observables
# (library top moves to hand on BOTH engines) plus the full
# ``compare_fields == []`` over the whole cross-engine field view.
#
# Scenario: library top-to-bottom = [non-land, deeper-non-land]
# (non-land top → hand path; avoids the agent-yes / land-onto-bf
# branch that's honest-stopped on the Rust side). Python's graveyard
# is seeded with 4 distinct card types (Artifact, Enchantment,
# Instant, Sorcery) so the Delirium predicate is satisfied and the
# real trigger fires. Rust's graveyard is seeded with the same 4
# cards for byte-equal field-view alignment (the synthetic carrier's
# ``source_is_self`` predicate fires unconditionally on attack — the
# Delirium gate is the Python-only side of the honest-stop).
# ---------------------------------------------------------------------------


@_rust_skip
def test_cross_engine_real_dsk_wickerfolk_thresher_attack_nonland_top_parity(
    parity_smoke,
):
    """**GENUINE real-DSK cross-engine probe — Wickerfolk Thresher,
    non-land top → hand path with Delirium satisfied.**

    Python: the ACTUAL parsed Wickerfolk Thresher printing pre-
    seated on p0's battlefield (no cast path → no spurious ETB
    triggers since the genuine printing carries only the ATTACKS
    trigger). p0's library is seeded with top-to-bottom [non-land,
    deeper-non-land]; p0's graveyard is seeded with 4 distinct card
    types so the Delirium gate is satisfied. p0's agent is set to
    ``None`` so the agent-yes branch is honest-stopped consistent
    with Rust. Declaring an attacker fires the ATTACKS trigger; the
    Delirium gate passes; the resolve walks the no-agent branch and
    routes the top non-land to hand.

    Rust: bridged synthetic carrier carrying the same ATTACKS trigger
    + ``peek_top_may_battlefield_if_land_else_hand`` effect dict
    (with the simpler ``source_is_self`` predicate — see HONEST-STOP
    #2 in the module docstring); p0's library + graveyard are seeded
    identically. The declare-attacker fires the trigger
    unconditionally; resolve routes the top non-land to hand.

    Assertion strength: **full ``compare_fields == []``** over the
    whole cross-engine field view (every zone, both players), PLUS
    the concrete zone observables (library shrinkage by one + the
    top non-land in hand on BOTH engines).
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
    )
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.combat import declare_attackers as py_declare_attackers
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.game import Zone
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.predicates import And, Event, IsSelf, StateBound
    from mtg_bot.effects.state_predicates import Delirium

    real = _PRINTINGS.get("Wickerfolk Thresher")
    if real is None:
        pytest.skip("Wickerfolk Thresher absent from active CardSource")
    assert "Creature" in real.card_types

    # §2 source-of-truth: verify the genuine printing carries the
    # exact ATTACKS + And(IsSelf, StateBound(Delirium)) +
    # PeekTopMayBattlefieldIfLandElseHand trigger this probe pins.
    attacks_ta = next(
        (
            ta for ta in real.triggered_abilities
            if (
                ta.event is Event.ATTACKS
                and isinstance(
                    ta.effect, PeekTopMayBattlefieldIfLandElseHand
                )
            )
        ),
        None,
    )
    assert attacks_ta is not None, (
        "Wickerfolk Thresher must carry an ATTACKS/"
        "PeekTopMayBattlefieldIfLandElseHand trigger"
    )
    pred = attacks_ta.predicate
    assert isinstance(pred, And)
    assert isinstance(pred.left, IsSelf)
    assert isinstance(pred.right, StateBound)
    assert isinstance(pred.right.inner, Delirium)

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2
    ZH = 0
    ZL = 1
    ZG = 3

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

    # Four Delirium-counting card-type printings (Artifact,
    # Enchantment, Instant, Sorcery) — distinct CR 205.2a card
    # types so Delirium sees 4+ on Python's side.
    def _artifact_printing(name: str) -> CardPrinting:
        return CardPrinting(
            name=name,
            mana_cost_str="",
            mana_cost=ManaCost(generic=1, colored=()),
            type_line="Artifact",
            supertypes=(),
            card_types=("Artifact",),
            subtypes=(),
            power=None,
            toughness=None,
            produces=frozenset(),
            keywords=frozenset(),
        )

    def _enchantment_printing(name: str) -> CardPrinting:
        return CardPrinting(
            name=name,
            mana_cost_str="",
            mana_cost=ManaCost(generic=1, colored=()),
            type_line="Enchantment",
            supertypes=(),
            card_types=("Enchantment",),
            subtypes=(),
            power=None,
            toughness=None,
            produces=frozenset(),
            keywords=frozenset(),
        )

    def _sorcery_printing(name: str) -> CardPrinting:
        return CardPrinting(
            name=name,
            mana_cost_str="",
            mana_cost=ManaCost(generic=1, colored=()),
            type_line="Sorcery",
            supertypes=(),
            card_types=("Sorcery",),
            subtypes=(),
            power=None,
            toughness=None,
            produces=frozenset(),
            keywords=frozenset(),
        )

    # ---- Python: seat the genuine parsed Thresher on p0's bf;
    # seed p0's library with [non-land, deeper-non-land]; seed
    # graveyard with 4 distinct card types; no agent.
    py_thresher = py.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    py_thresher.summoning_sick = False
    py_thresher.tapped = False
    py_thresher.damage = 0
    py_thresher.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_thresher)

    # Python `new_object` allocates IDs in call order. To make IDs
    # align with Rust's registration order (graveyard 4 cards
    # first, then library 2 — Rust below registers in this exact
    # order, so allocate Python's objects in the same order).
    #
    # NB: Rust's `register_and_inject_object` for LIBRARY pushes
    # onto lib[0] (the TOP), so to build library top-to-bottom =
    # [nonland_top, deeper_nonland] we register from BOTTOM-to-top.
    # For graveyard, push order = append order (lower index =
    # earlier-added).
    py_gy_artifact = py.new_object(
        _artifact_printing("Thresher GY Artifact"),
        owner_id=0,
        zone=Zone.GRAVEYARD,
    )
    py_gy_enchantment = py.new_object(
        _enchantment_printing("Thresher GY Enchantment"),
        owner_id=0,
        zone=Zone.GRAVEYARD,
    )
    py_gy_instant = py.new_object(
        _instant_printing("Thresher GY Instant"),
        owner_id=0,
        zone=Zone.GRAVEYARD,
    )
    py_gy_sorcery = py.new_object(
        _sorcery_printing("Thresher GY Sorcery"),
        owner_id=0,
        zone=Zone.GRAVEYARD,
    )
    # Now allocate library objects bottom-first.
    py_lib_deeper_nonland = py.new_object(
        _instant_printing("Thresher Instant deeper"),
        owner_id=0,
        zone=Zone.LIBRARY,
    )
    py_lib_nonland_top = py.new_object(
        _instant_printing("Thresher Instant top"),
        owner_id=0,
        zone=Zone.LIBRARY,
    )
    # Normalise summoning_sick = False on all library cards (Python
    # default = True for cards-in-library; Rust default = False —
    # the established Icecave Crasher / Genemorph Imago batch-B
    # fixture-asymmetry idiom).
    for _obj in (py_lib_nonland_top, py_lib_deeper_nonland):
        _obj.summoning_sick = False
    # Also normalise summoning_sick = False on every graveyard card
    # (Python defaults graveyard cards to True; Rust defaults to
    # False).
    for _obj in (
        py_gy_artifact, py_gy_enchantment, py_gy_instant, py_gy_sorcery,
    ):
        _obj.summoning_sick = False
    # Library order top-to-bottom = list-prefix order.
    py.players[0].library.extend([
        py_lib_nonland_top,
        py_lib_deeper_nonland,
    ])
    py.players[0].graveyard.extend([
        py_gy_artifact, py_gy_enchantment,
        py_gy_instant, py_gy_sorcery,
    ])
    # Sanity: Delirium is satisfied on Python (4 distinct types).
    assert Delirium().test(py, 0) is True, (
        "Delirium must be satisfied with 4 distinct card types in "
        "graveyard"
    )
    # No agent on p0 — defensive default fires the no-agent / hand
    # branch at resolve time (library_lookat.py:332-355).
    py.players[0].agent = None

    # ---- Rust: seat the bridged synthetic Thresher carrier on p0's
    # bf; seed p0's library + graveyard identically.
    #
    # Library-injection order note: ``register_and_inject_object``
    # pushes onto ``lib[0]`` (the TOP). Graveyard order = append
    # order. Match Python's allocation order so IDs align across
    # engines: graveyard cards first (artifact, ench, instant,
    # sorcery), then library bottom-first (deeper, top).
    # Use the REAL printing's name on the Rust carrier so the
    # battlefield field-view tuple's name slot agrees byte-equal
    # with Python's actual parsed Thresher.
    thresher_carrier_for_probe = dict(_THRESHER_PRINTING_DICT)
    thresher_carrier_for_probe["name"] = real.name
    rs_thresher = rs.register_and_inject_object(
        thresher_carrier_for_probe, 0, ZB,
    )
    rs.clear_summoning_sick_for_player(0)
    rs_gy_artifact = rs.register_and_inject_object(
        {
            "name": "Thresher GY Artifact",
            "card_types": ["Artifact"],
            "mana_cost": {"generic": 1},
        },
        0, ZG,
    )
    rs_gy_enchantment = rs.register_and_inject_object(
        {
            "name": "Thresher GY Enchantment",
            "card_types": ["Enchantment"],
            "mana_cost": {"generic": 1},
        },
        0, ZG,
    )
    rs_gy_instant = rs.register_and_inject_object(
        {
            "name": "Thresher GY Instant",
            "card_types": ["Instant"],
            "mana_cost": {"generic": 1},
        },
        0, ZG,
    )
    rs_gy_sorcery = rs.register_and_inject_object(
        {
            "name": "Thresher GY Sorcery",
            "card_types": ["Sorcery"],
            "mana_cost": {"generic": 1},
        },
        0, ZG,
    )
    rs_lib_deeper_nonland = rs.register_and_inject_object(
        {
            "name": "Thresher Instant deeper",
            "card_types": ["Instant"],
            "mana_cost": {"R": 1},
        },
        0, ZL,
    )
    rs_lib_nonland_top = rs.register_and_inject_object(
        {
            "name": "Thresher Instant top",
            "card_types": ["Instant"],
            "mana_cost": {"R": 1},
        },
        0, ZL,
    )
    # Sanity: library top-to-bottom matches Python's order.
    rs_lib_check = [e["id"] for e in rs.library_snapshot(0)]
    assert rs_lib_check == [
        rs_lib_nonland_top, rs_lib_deeper_nonland,
    ], f"Rust library top-to-bottom mismatch pre-trigger; got {rs_lib_check}"
    # Sanity: graveyard order matches.
    rs_gy_check = [e["id"] for e in rs.graveyard_snapshot(0)]
    assert rs_gy_check == [
        rs_gy_artifact, rs_gy_enchantment,
        rs_gy_instant, rs_gy_sorcery,
    ], f"Rust graveyard mismatch pre-trigger; got {rs_gy_check}"

    # Pre-trigger sanity: no trigger fires during seeding.
    assert rs.stack_size() == 0 and len(py.stack) == 0

    # ---- Fire the ATTACKS trigger by declaring an attacker. ----
    py_declare_attackers(py, [py_thresher.id])
    assert len(py.stack) == 1, (
        "Python: ATTACKS trigger should be on the stack after "
        "Wickerfolk Thresher attacks (Delirium gate satisfied)"
    )
    assert rs.declare_attacker(rs_thresher) is True
    assert rs.stack_size() == 1, (
        "Rust: ATTACKS trigger should be on the stack after the "
        "Thresher carrier attacks"
    )

    # ---- Drain both stacks (resolves PeekTopMayBattlefieldIfLand
    # ElseHand). ----
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
    # Hand should now contain the top non-land.
    py_hand_ids = [o.id for o in py.players[0].hand]
    assert py_lib_nonland_top.id in py_hand_ids, (
        f"Python: top non-land must be in hand; "
        f"got hand={py_hand_ids}"
    )
    # Thresher still on bf.
    assert py_thresher in py.battlefield

    # ---- Rust observables. ----
    rs_lib_ids = [e["id"] for e in rs.library_snapshot(0)]
    assert rs_lib_ids == [rs_lib_deeper_nonland], (
        f"Rust: library must be [deeper_nonland] post-resolve; "
        f"got {rs_lib_ids}"
    )
    rs_hand_ids = [e["id"] for e in rs.hand_snapshot(0)]
    assert rs_lib_nonland_top in rs_hand_ids, (
        f"Rust: top non-land must be in hand; got hand={rs_hand_ids}"
    )
    # Thresher still on bf.
    rs_bf_ids = [e["id"] for e in rs.battlefield_snapshot()]
    assert rs_thresher in rs_bf_ids

    # ---- Full field-view byte-equality over the WHOLE state. ----
    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Wickerfolk Thresher ATTACKS PeekTopMayBattlefieldIfLand"
        f"ElseHand must be byte-equal across the WHOLE field view "
        f"on BOTH engines (no-agent / non-land-top → hand path); "
        f"diffs={diffs}"
    )
