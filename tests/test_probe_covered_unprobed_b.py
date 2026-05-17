"""Genuine real-EoE cross-engine byte-equality probes — batch B.

CONTINUOUS-PIPELINE phase: convert high-deck-count
``covered-by-construction`` EoE cards into the **strongest parity-
evidence tier** (``PROBED byte-equal`` per ``docs/POOL_PARITY.md`` /
``scripts/measure_pool_parity.py``) via genuine real-EoE cross-engine
probes.

WHAT EACH PROBE ASSERTS (the strongest tier the harness cleanly
supports)
----------------------------------------------------------------------
Every probe in this module:

  * drives the **ACTUAL parsed EoE printing** on the Python side
    (``get_active_source().get_printings()[<card>]``) — NOT a synthetic
    stub — so it pins THE CARD, not merely a bridge arm;
  * drives the bridged synthetic carrier on the Rust side
    (``register_and_inject_object`` with the closed-vocab effect dict
    the production bridge round-trips);
  * asserts **full ``compare_fields(...) == []``** — byte-equality
    across the WHOLE cross-engine field view, the strongest
    Effect+bridge-level evidence — after a real EoE deck context
    (the carrier resolved end-to-end on both engines, the trigger
    fired, the stack drained).

This is the same canonical idiom the established genuine real-EoE
probes use (Depressurize ``test_parity_smoke.py``:66239; Seedship
Impact :65389; Galactic Wayfarer :35459; Perigee Beckoner :63882):
real parsed ``spell_effect`` / ``triggered_abilities`` on Python, a
bridged synthetic carrier on Rust, ``compare_fields == []`` on a
controlled real-EoE state.

> CAVEAT (mirrors ``docs/POOL_PARITY.md``): this is Effect+bridge-
> level byte-equality on a *controlled* cross-engine state, NOT
> full-game-trajectory parity. PROBED is the strongest evidence tier
> the campaign tracks; it is not a full random multi-turn game.

PARTITION DISCIPLINE (batch B — EVEN-ranked)
--------------------------------------------
The continuous pipeline runs a sibling agent on the disjoint batch A
(ODD-ranked) concurrently. This module owns **batch B = the
EVEN-ranked entries** (2nd, 4th, 6th, …) of the
covered-by-construction-but-unprobed card list, sorted by 17lands deck
count descending (computed read-only via
``scripts/measure_pool_parity.py`` /
``src/mtg_bot/parity/effect_coverage.py`` +
``data/17lands/eoe_decks.json.gz``). Every card below was
verify-first-confirmed at live HEAD to be (a) covered-by-construction,
(b) NOT already individually probed, (c) EVEN-ranked. The new
dedicated module (NOT ``tests/test_trajectory_parity.py`` /
``tests/test_probe_covered_unprobed_a.py`` — both owned by others)
avoids all collision.

The 6 cards pinned here (deck counts at the verify-first walk):

  | rank | card                  | decks  | shape                       |
  |-----:|-----------------------|-------:|-----------------------------|
  |   10 | Gravpack Monoist      | 25,252 | DIES → CreateToken (tapped) |
  |   12 | Beamsaw Prospector    | 24,310 | DIES → CreateToken (Lander) |
  |   14 | Icecave Crasher       | 22,108 | landfall → PumpSelfUEOT     |
  |   26 | Edge Rover            | 15,271 | DIES → CreateToken (eachpl) |
  |   72 | Luxknight Breacher    |  6,216 | ETB → +1/+1 per other       |
  |   84 | Remnant Elemental     |  3,948 | landfall → PumpSelfUEOT     |

DROPPED ON VERIFY (honest discipline):

  * **Sunstar Expansionist** (rank 40, 12,252) — TA[0]'s predicate is
    ``StateBound(OpponentControlsMoreLandsThanYou())``; that predicate
    has **0 bridge support** in ``cross_engine.py`` (no
    ``opponent_controls_more_lands`` / ``state_bound`` kind). Driving
    the genuine printing (whose TA[0] DOES gate on it) against a Rust
    synthetic that cannot express the gate would NOT be a genuine
    byte-equal probe of the card — dropped rather than ship a weaker
    synthetic-only stub.
  * **Syr Vondam, the Lucent** (rank 62, 7,857) — the genuine
    printing's ETB + ATTACKS effect is
    ``PumpCreaturesYouControlUntilEOT`` carrying
    ``granted_keywords={deathtouch}`` + ``exclude_source=True``; the
    bare ``pump_creatures_you_control_until_eot`` bridge arm
    (``cross_engine.py``:4454) carries ONLY
    ``power_bonus``/``toughness_bonus`` — the keyword-grant /
    exclude-source riders are NOT on the arm, so the genuine Python
    printing (which grants deathtouch + excludes the source) would
    genuinely DIVERGE from a bare-arm Rust synthetic. The
    "synthetic-only when riders cascade" precedent (the bridge arm's
    own docstring) applies; dropped.
  * **Skystinger** (rank 58, 8,306) — a ``blocks`` trigger gated on
    ``attacker HasKeyword(flying)``; no established cross-engine probe
    fires a ``blocks`` trigger and the blocks/attacker-keyword
    predicate has no bridge support (``"blocks"`` count 1, no
    ``attacker_has_keyword`` / ``subject_has_keyword``). Not cleanly
    probe-constructible with the existing harness; dropped.

This module is sentinel-isolated: it does NOT touch
``tests/test_parity_smoke.py``'s ``# === PHASE5_PROBES_INSERT_ABOVE
...`` sentinel nor any other owned file.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

# Skip the whole module if the Rust extension isn't built — mirrors the
# ``tests/test_parity_smoke.py`` / ``tests_rust/conftest.py`` policy so
# a fresh checkout without maturin doesn't break the gate.
pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


@pytest.fixture(scope="module")
def parity_smoke():
    """Load ``scripts/parity_smoke.py`` as a module (the field-view
    builder lives there). Identical to ``test_parity_smoke.py``'s
    module-scoped fixture — copied here so this module is fully
    self-contained / collision-free with the owned test files."""
    repo_root = pathlib.Path(__file__).resolve().parent.parent
    script_path = repo_root / "scripts" / "parity_smoke.py"
    spec = importlib.util.spec_from_file_location(
        "parity_smoke", script_path
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["parity_smoke"] = mod
    spec.loader.exec_module(mod)
    return mod


def _drain_both(py_state, rust_state):
    """Resolve the top of stack on both engines until both stacks are
    empty. Mirrors ``test_parity_smoke.py``'s ``_drain_stack_both``."""
    from mtg_bot.actions import resolve_top_of_stack

    while rust_state.stack_size() > 0:
        rust_state.resolve_top_of_stack()
    while py_state.stack:
        resolve_top_of_stack(py_state)


def _kill_both(py_state, rust_state, py_obj, rust_obj_id):
    """Lethal-damage + SBA both engines so a DIES trigger fires.
    Mirrors the established Perigee Beckoner dies-fire idiom
    (``test_parity_smoke.py``:64057-64065)."""
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.turn import state_based_actions

    py_obj.damage = 99
    for _ in range(20):
        if not state_based_actions(py_state):
            break
        while py_state.stack:
            resolve_top_of_stack(py_state)
    rust_state.deal_damage(rust_obj_id, 99)
    rust_state.apply_sbas_until_quiescent()


# ---------------------------------------------------------------------------
# Probe 1 — Gravpack Monoist (~25,252 17lands decks; rank 10, EVEN/B).
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_gravpack_monoist_dies_create_tapped_robot_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Gravpack Monoist
    (~25,252 17lands decks). Covered-by-construction → PROBED.**

    Drives the **ACTUAL parsed Gravpack Monoist printing** on the
    Python side: ``get_active_source().get_printings()["Gravpack
    Monoist"]`` — which the live parser maps to a single
    ``Event.DIES`` ``IsSelf`` trigger whose effect is
    ``CreateToken(token=Robot 2/2 artifact-creature, tapped=True,
    count=1)`` (verified live below).

    Oracle (``data/edge_of_eternities.json``):

        "When this creature dies, create a tapped 2/2 colorless Robot
         artifact creature token."

    The genuine printing's ``CreateToken`` carries ``tapped=True``
    (the parser reads the printed "tapped"); the Rust synthetic
    therefore uses the dedicated ``create_token_tapped`` closed-vocab
    kind (``cross_engine.py``:7797) so both engines spawn the SAME
    tapped Robot. The Robot pid is registered on Rust via
    ``register_and_inject_object``; Python seats the intrinsic
    ``TOKEN_PRINTINGS["Robot"]`` so the spawned token is byte-equal in
    the name-keyed field view (the established Seedship-Impact /
    Galactic-Wayfarer token-pid idiom).

    **Assertion strength: full ``compare_fields == []``** — the WHOLE
    cross-engine field view is byte-equal after the genuine carrier
    dies on BOTH engines and the DIES → CreateToken trigger resolves.
    This is the FIRST cross-engine probe to fire a real-EoE
    ``DIES → CreateToken`` trigger end-to-end (no prior probe pairs a
    dies-event dispatch with a token-spawn rider).
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.cards import TOKEN_PRINTINGS
    from mtg_bot.effects.generic.tokens import CreateToken
    from mtg_bot.effects.predicates import Event, IsSelf
    from mtg_bot.game import Zone

    real = get_active_source().get_printings().get("Gravpack Monoist")
    if real is None:
        pytest.skip("Gravpack Monoist absent from active CardSource")
    assert real.is_creature
    assert len(real.triggered_abilities) == 1
    ta = real.triggered_abilities[0]
    assert ta.event == Event.DIES
    assert isinstance(ta.predicate, IsSelf)
    assert isinstance(ta.effect, CreateToken)
    assert ta.effect.token_printing.name == "Robot"
    assert ta.effect.tapped is True
    assert ta.effect.each_player is False
    assert ta.effect.count == 1

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2

    # Register the Robot token on Rust (pid = registry_size); seat the
    # intrinsic Python printing in p0's library so the STARTING field
    # view is symmetric (the genuine effect mints a FRESH Robot on the
    # bf). summoning_sick forced False on the inert seed: Rust's
    # register_and_inject_object seats summoning_sick=False for all
    # zones while Python's new_object defaults True — the well-known
    # synthetic-state seed nuance, NOT the effect under test.
    robot_pid = rs.registry_size
    rs.register_and_inject_object(
        {"name": "Robot", "card_types": ["Artifact", "Creature"],
         "supertypes": ["Token"], "power": 2, "toughness": 2,
         "mana_cost": {"generic": 0}},
        0, 1,
    )
    py_seed = py.new_object(
        TOKEN_PRINTINGS["Robot"], owner_id=0, zone=Zone.LIBRARY
    )
    py_seed.summoning_sick = False
    py.players[0].library.append(py_seed)

    # ---- Python: the GENUINE parsed Gravpack Monoist printing on p0's
    # bf.
    py_src = py.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    py_src.summoning_sick = False
    py_src.tapped = False
    py_src.damage = 0
    py_src.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_src)

    # ---- Rust: bridged synthetic carrier with the dies →
    # create_token_tapped(Robot pid) trigger (closed-vocab tapped
    # kind = the genuine printing's tapped=True).
    rs_src = rs.register_and_inject_object(
        {"name": "Gravpack Monoist", "card_types": ["Creature"],
         "power": real.power, "toughness": real.toughness,
         "triggered_abilities": [{
             "event": "dies",
             "predicate": {"kind": "source_is_self"},
             "effect": {"kind": "create_token_tapped", "count": 1,
                        "token_printing_id": robot_pid}}]},
        0, ZB,
    )

    _kill_both(py, rs, py_src, rs_src)
    _drain_both(py, rs)
    assert len(py.stack) == 0 and rs.stack_size() == 0

    # Concrete observable: exactly one Robot spawned on BOTH.
    rust_n = sum(1 for e in rs.battlefield_snapshot()
                 if e["printing_name"] == "Robot")
    py_n = sum(1 for o in py.battlefield
               if o.printing.name == "Robot")
    assert rust_n == 1 == py_n, (
        f"Gravpack Monoist dies → exactly one Robot on BOTH; "
        f"rust={rust_n} py={py_n}"
    )

    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Gravpack Monoist dies → tapped-Robot must be byte-equal "
        f"across the WHOLE field view on BOTH engines; diffs={diffs}"
    )


# ---------------------------------------------------------------------------
# Probe 2 — Beamsaw Prospector (~24,310 17lands decks; rank 12, EVEN/B).
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_beamsaw_prospector_dies_create_lander_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Beamsaw Prospector
    (~24,310 17lands decks). Covered-by-construction → PROBED.**

    Drives the **ACTUAL parsed Beamsaw Prospector printing** on the
    Python side — a single ``Event.DIES`` ``IsSelf`` trigger whose
    effect is ``CreateToken(token=Lander artifact, tapped=False,
    each_player=False, count=1)`` (verified live below).

    Oracle (``data/edge_of_eternities.json``):

        "When this creature dies, create a Lander token."

    The genuine ``CreateToken`` is the bare (untapped, self-only)
    shape, so the Rust synthetic uses the bare ``create_token`` kind.
    The Lander pid is registered on Rust; Python seats intrinsic
    ``TOKEN_PRINTINGS["Lander"]`` (the established token-pid idiom).

    **Assertion strength: full ``compare_fields == []``** on a real
    EoE deck context — the WHOLE field view byte-equal after the
    genuine carrier dies on BOTH and DIES → CreateToken resolves.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.cards import TOKEN_PRINTINGS
    from mtg_bot.effects.generic.tokens import CreateToken
    from mtg_bot.effects.predicates import Event, IsSelf
    from mtg_bot.game import Zone

    real = get_active_source().get_printings().get("Beamsaw Prospector")
    if real is None:
        pytest.skip("Beamsaw Prospector absent from active CardSource")
    assert real.is_creature
    assert len(real.triggered_abilities) == 1
    ta = real.triggered_abilities[0]
    assert ta.event == Event.DIES
    assert isinstance(ta.predicate, IsSelf)
    assert isinstance(ta.effect, CreateToken)
    assert ta.effect.token_printing.name == "Lander"
    assert ta.effect.tapped is False
    assert ta.effect.each_player is False
    assert ta.effect.count == 1

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2

    lander_pid = rs.registry_size
    rs.register_and_inject_object(
        {"name": "Lander", "card_types": ["Artifact"],
         "supertypes": ["Token"], "mana_cost": {"generic": 0}},
        0, 1,
    )
    py_seed = py.new_object(
        TOKEN_PRINTINGS["Lander"], owner_id=0, zone=Zone.LIBRARY
    )
    py_seed.summoning_sick = False
    py.players[0].library.append(py_seed)

    py_src = py.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    py_src.summoning_sick = False
    py_src.tapped = False
    py_src.damage = 0
    py_src.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_src)

    rs_src = rs.register_and_inject_object(
        {"name": "Beamsaw Prospector", "card_types": ["Creature"],
         "power": real.power, "toughness": real.toughness,
         "triggered_abilities": [{
             "event": "dies",
             "predicate": {"kind": "source_is_self"},
             "effect": {"kind": "create_token", "count": 1,
                        "token_printing_id": lander_pid}}]},
        0, ZB,
    )

    _kill_both(py, rs, py_src, rs_src)
    _drain_both(py, rs)
    assert len(py.stack) == 0 and rs.stack_size() == 0

    rust_n = sum(1 for e in rs.battlefield_snapshot()
                 if e["printing_name"] == "Lander")
    py_n = sum(1 for o in py.battlefield
               if o.printing.name == "Lander")
    assert rust_n == 1 == py_n, (
        f"Beamsaw Prospector dies → exactly one Lander on BOTH; "
        f"rust={rust_n} py={py_n}"
    )

    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Beamsaw Prospector dies → Lander must be byte-equal across "
        f"the WHOLE field view on BOTH engines; diffs={diffs}"
    )


# ---------------------------------------------------------------------------
# Probe 3 — Icecave Crasher (~22,108 17lands decks; rank 14, EVEN/B).
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_icecave_crasher_landfall_pump_self_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Icecave Crasher
    (~22,108 17lands decks). Covered-by-construction → PROBED.**

    Drives the **ACTUAL parsed Icecave Crasher printing** on the
    Python side — a single ``Event.ENTERS`` landfall trigger
    (``And(Subject(IsLand()), Controlled(YOU))``) whose effect is
    ``PumpSelfUntilEOT(power_bonus=1, toughness_bonus=0,
    granted_keywords=∅)`` (verified live below).

    Oracle (``data/edge_of_eternities.json``):

        "Landfall — Whenever a land you control enters, this creature
         gets +1/+0 until end of turn."

    The genuine effect grants NO keywords (empty ``granted_keywords``)
    so the bare ``pump_self_until_eot`` bridge arm is exact. A Forest
    is played on BOTH engines (Python ``_play_land`` / Rust
    ``play_land`` — the established Eumidian-Terrabotanist landfall
    idiom), the self-pump fires.

    **Assertion strength: full ``compare_fields == []``** after the
    landfall trigger resolves. The land fixture's ``summoning_sick``
    slot is normalised symmetric BEFORE the compare (Python's
    ``_play_land`` seats it summoning-sick, Rust's ``play_land`` does
    not — the documented synthetic-state fixture asymmetry, NOT the
    pump under test; the established Eumidian-Terrabotanist /
    Seedship-Impact synthetic-state nuance). The self-pump itself is
    asserted byte-equal across the whole view and concretely via the
    counters-inclusive cross-engine state.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.actions import _play_land
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.generic.pump import PumpSelfUntilEOT
    from mtg_bot.effects.predicates import Event
    from mtg_bot.game import Zone, effective_power

    real = get_active_source().get_printings().get("Icecave Crasher")
    if real is None:
        pytest.skip("Icecave Crasher absent from active CardSource")
    assert real.is_creature
    assert len(real.triggered_abilities) == 1
    ta = real.triggered_abilities[0]
    assert ta.event == Event.ENTERS
    assert isinstance(ta.effect, PumpSelfUntilEOT)
    assert ta.effect.power_bonus == 1
    assert ta.effect.toughness_bonus == 0
    assert ta.effect.granted_keywords == frozenset()

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2
    ZH = 0

    py_src = py.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    py_src.summoning_sick = False
    py_src.tapped = False
    py_src.damage = 0
    py_src.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_src)

    rs_src = rs.register_and_inject_object(
        {"name": "Icecave Crasher", "card_types": ["Creature"],
         "power": real.power, "toughness": real.toughness,
         "triggered_abilities": [{
             "event": "enters",
             "predicate": {"kind": "and",
                           "left": {"kind": "subject_is_land"},
                           "right": {"kind": "controlled_by_you"}},
             "effect": {"kind": "pump_self_until_eot",
                        "power_bonus": 1, "toughness_bonus": 0}}]},
        0, ZB,
    )

    fp = CardPrinting(
        name="Forest", mana_cost_str="", mana_cost=ManaCost(),
        type_line="Basic Land — Forest", supertypes=("Basic",),
        card_types=("Land",), subtypes=("Forest",),
        power=None, toughness=None, produces=frozenset({"G"}),
    )
    py_f = py.new_object(fp, owner_id=0, zone=Zone.HAND)
    py.players[0].hand.append(py_f)
    rs_f = rs.register_and_inject_object(
        {"name": "Forest", "card_types": ["Land"],
         "mana_produced": ["G"], "supertypes": ["Basic"]},
        0, ZH,
    )

    py.players[0].lands_played_this_turn = 0
    _play_land(py, 0, py_f.id)
    rs.play_land(rs_f, 0)
    assert len(py.stack) == 1 and rs.stack_size() == 1, (
        "the landfall trigger should land on BOTH stacks"
    )

    _drain_both(py, rs)
    assert len(py.stack) == 0 and rs.stack_size() == 0

    # Concrete observable: +1/+0 self-pump on BOTH.
    assert effective_power(py, py_src) == real.power + 1
    assert rs.effective_power(rs_src) == real.power + 1

    # The played-land fixture's summoning_sick slot is a documented
    # synthetic-state asymmetry (Python _play_land seats it
    # summoning-sick; Rust play_land does not) — NOT the self-pump
    # under test. Normalise it symmetric before the WHOLE-view compare
    # so the byte-equality assertion genuinely measures the pump.
    for o in py.battlefield:
        if o.printing.name == "Forest":
            o.summoning_sick = False

    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Icecave Crasher landfall +1/+0 self-pump must be byte-equal "
        f"across the WHOLE field view on BOTH engines; diffs={diffs}"
    )


# ---------------------------------------------------------------------------
# Probe 4 — Edge Rover (~15,271 17lands decks; rank 26, EVEN/B).
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_edge_rover_dies_create_lander_each_player_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Edge Rover (~15,271
    17lands decks). Covered-by-construction → PROBED.**

    Drives the **ACTUAL parsed Edge Rover printing** on the Python
    side — an Artifact-Creature with a single ``Event.DIES``
    ``IsSelf`` trigger whose effect is ``CreateToken(token=Lander
    artifact, tapped=False, each_player=True, count=1)`` (verified
    live below).

    Oracle (``data/edge_of_eternities.json``):

        "When this creature dies, each player creates a Lander token."

    The genuine ``CreateToken`` carries ``each_player=True`` so the
    Rust synthetic uses the dedicated ``create_token_each_player``
    closed-vocab kind (``cross_engine.py``:2106). Both p0 AND p1 spawn
    a Lander → exactly 2 Landers on BOTH engines. The Lander pid is
    registered on Rust; Python seats intrinsic
    ``TOKEN_PRINTINGS["Lander"]``.

    **Assertion strength: full ``compare_fields == []``** on a real
    EoE deck context — the WHOLE field view (both Landers, one per
    player, correct controllers) byte-equal after the genuine carrier
    dies on BOTH. Pins the each-player token-spawn fan-out shape
    cross-engine on a real EoE printing (a NEW axis vs the
    same-controller token probes).
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.cards import TOKEN_PRINTINGS
    from mtg_bot.effects.generic.tokens import CreateToken
    from mtg_bot.effects.predicates import Event, IsSelf
    from mtg_bot.game import Zone

    real = get_active_source().get_printings().get("Edge Rover")
    if real is None:
        pytest.skip("Edge Rover absent from active CardSource")
    assert "Artifact" in real.card_types and "Creature" in real.card_types
    assert len(real.triggered_abilities) == 1
    ta = real.triggered_abilities[0]
    assert ta.event == Event.DIES
    assert isinstance(ta.predicate, IsSelf)
    assert isinstance(ta.effect, CreateToken)
    assert ta.effect.token_printing.name == "Lander"
    assert ta.effect.tapped is False
    assert ta.effect.each_player is True
    assert ta.effect.count == 1

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2

    lander_pid = rs.registry_size
    rs.register_and_inject_object(
        {"name": "Lander", "card_types": ["Artifact"],
         "supertypes": ["Token"], "mana_cost": {"generic": 0}},
        0, 1,
    )
    py_seed = py.new_object(
        TOKEN_PRINTINGS["Lander"], owner_id=0, zone=Zone.LIBRARY
    )
    py_seed.summoning_sick = False
    py.players[0].library.append(py_seed)

    py_src = py.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    py_src.summoning_sick = False
    py_src.tapped = False
    py_src.damage = 0
    py_src.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_src)

    rs_src = rs.register_and_inject_object(
        {"name": "Edge Rover",
         "card_types": ["Artifact", "Creature"],
         "power": real.power, "toughness": real.toughness,
         "triggered_abilities": [{
             "event": "dies",
             "predicate": {"kind": "source_is_self"},
             "effect": {"kind": "create_token_each_player", "count": 1,
                        "token_printing_id": lander_pid}}]},
        0, ZB,
    )

    _kill_both(py, rs, py_src, rs_src)
    _drain_both(py, rs)
    assert len(py.stack) == 0 and rs.stack_size() == 0

    # each_player → exactly 2 Landers (one per player) on BOTH.
    rust_n = sum(1 for e in rs.battlefield_snapshot()
                 if e["printing_name"] == "Lander")
    py_n = sum(1 for o in py.battlefield
               if o.printing.name == "Lander")
    assert rust_n == 2 == py_n, (
        f"Edge Rover dies (each_player) → exactly 2 Landers on BOTH; "
        f"rust={rust_n} py={py_n}"
    )

    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Edge Rover dies → each-player Lander fan-out must be "
        f"byte-equal across the WHOLE field view on BOTH engines; "
        f"diffs={diffs}"
    )


# ---------------------------------------------------------------------------
# Probe 5 — Luxknight Breacher (~6,216 17lands decks; rank 72, EVEN/B).
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_luxknight_breacher_etb_counters_per_other_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Luxknight Breacher
    (~6,216 17lands decks). Covered-by-construction → PROBED.**

    Drives the **ACTUAL parsed Luxknight Breacher printing** on the
    Python side — a single ``Event.ENTERS`` ``IsSelf`` trigger whose
    effect is ``PutPlusOneCountersOnSelfPerOtherCreatureOrArtifact()``
    (a field-free count-from-board counter effect; verified live
    below).

    Oracle (``data/edge_of_eternities.json``):

        "When this creature enters, put a +1/+1 counter on it for each
         other creature or artifact you control."

    Two other creatures pre-placed for p0 on BOTH engines → the ETB
    puts exactly **2** +1/+1 counters on the Breacher. The Rust
    synthetic uses the bridged
    ``put_plus_one_counters_on_self_per_other_creature_or_artifact``
    kind.

    **Assertion strength: full ``compare_fields == []``** on a real
    EoE deck context. The byte-equal signal is the field view's
    counters slot (the round-70 ``_net_counters`` counters-aware
    ``_zone_signature``): both engines land net **+2** counters on the
    Breacher, byte-equal across the WHOLE view. The concrete
    cross-engine observable is double-pinned (Python
    ``plus_one_counters == 2`` and Rust ``battlefield_snapshot``
    ``counters == 2``).

    NOTE — the out-of-band ``effective_power()`` accessor is
    DELIBERATELY NOT cross-asserted: Rust's ``effective_power`` pymethod
    does not fold +1/+1 counters into the returned power while Python's
    does (a known accessor asymmetry, NOT a state divergence — the
    underlying byte-equal field state agrees that both carry net +2
    counters, exactly the round-70 Depressurize-probe counters-slot
    discipline: the byte-equal signal is ``compare_fields``, never an
    accessor).
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.actions import _trigger_etb_abilities
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.predicates import Event, IsSelf
    from mtg_bot.game import Zone

    real = get_active_source().get_printings().get("Luxknight Breacher")
    if real is None:
        pytest.skip("Luxknight Breacher absent from active CardSource")
    assert real.is_creature
    assert len(real.triggered_abilities) == 1
    ta = real.triggered_abilities[0]
    assert ta.event == Event.ENTERS
    assert isinstance(ta.predicate, IsSelf)
    assert type(ta.effect).__name__ == (
        "PutPlusOneCountersOnSelfPerOtherCreatureOrArtifact"
    )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2

    # Two OTHER creatures for p0 on BOTH engines (the count-from-board
    # denominator → 2 counters).
    for i in range(2):
        pr = CardPrinting(
            name=f"LB Ally {i}", mana_cost_str="",
            mana_cost=ManaCost(), type_line="Creature",
            supertypes=(), card_types=("Creature",), subtypes=(),
            power=1, toughness=1, produces=frozenset(),
        )
        o = py.new_object(pr, owner_id=0, zone=Zone.BATTLEFIELD)
        o.summoning_sick = False
        py.battlefield.append(o)
        rs.register_and_inject_object(
            {"name": f"LB Ally {i}", "card_types": ["Creature"],
             "power": 1, "toughness": 1},
            0, ZB,
        )

    py_src = py.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    py_src.summoning_sick = False
    py_src.tapped = False
    py_src.damage = 0
    py_src.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_src)

    rs_src = rs.register_and_inject_object(
        {"name": "Luxknight Breacher", "card_types": ["Creature"],
         "power": real.power, "toughness": real.toughness,
         "triggered_abilities": [{
             "event": "enters",
             "predicate": {"kind": "source_is_self"},
             "effect": {"kind": (
                 "put_plus_one_counters_on_self_per_other_"
                 "creature_or_artifact")}}]},
        0, ZB,
    )

    _trigger_etb_abilities(py, py_src)
    assert len(py.stack) == 1 and rs.stack_size() == 1, (
        "the ETB counter trigger should land on BOTH stacks"
    )
    _drain_both(py, rs)
    assert len(py.stack) == 0 and rs.stack_size() == 0

    # Concrete cross-engine observable: net +2 counters on the
    # Breacher on BOTH (2 other permanents → 2 counters).
    assert py_src.plus_one_counters == 2, (
        f"Python: Breacher should carry 2 +1/+1 counters; "
        f"got {py_src.plus_one_counters}"
    )
    rs_breacher = next(
        e for e in rs.battlefield_snapshot()
        if e["printing_name"] == "Luxknight Breacher"
    )
    assert rs_breacher["counters"] == 2, (
        f"Rust: Breacher should carry 2 counters; "
        f"got {rs_breacher['counters']}"
    )

    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Luxknight Breacher ETB +1/+1-per-other-permanent must be "
        f"byte-equal across the WHOLE field view on BOTH engines "
        f"(counters-aware _zone_signature); diffs={diffs}"
    )


# ---------------------------------------------------------------------------
# Probe 6 — Remnant Elemental (~3,948 17lands decks; rank 84, EVEN/B).
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_remnant_elemental_landfall_pump_self_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Remnant Elemental
    (~3,948 17lands decks). Covered-by-construction → PROBED.**

    Drives the **ACTUAL parsed Remnant Elemental printing** on the
    Python side — a 0/4 creature with a single ``Event.ENTERS``
    landfall trigger (``And(Subject(IsLand()), Controlled(YOU))``)
    whose effect is ``PumpSelfUntilEOT(power_bonus=2,
    toughness_bonus=0, granted_keywords=∅)`` (verified live below).

    Oracle (``data/edge_of_eternities.json``):

        "Landfall — Whenever a land you control enters, this creature
         gets +2/+0 until end of turn."

    Distinct from the Icecave Crasher landfall sister: a 0/4 base
    (so the self-pump takes effective power 0→2, a sharp delta off a
    zero base) and a +2 (not +1) bonus. The genuine effect grants NO
    keywords so the bare ``pump_self_until_eot`` arm is exact.

    **Assertion strength: full ``compare_fields == []``** after the
    landfall trigger resolves; the played-land ``summoning_sick`` slot
    is normalised symmetric before the WHOLE-view compare (the same
    documented synthetic-state fixture asymmetry as the Icecave sister
    — NOT the pump under test).
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.actions import _play_land
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.generic.pump import PumpSelfUntilEOT
    from mtg_bot.effects.predicates import Event
    from mtg_bot.game import Zone, effective_power

    real = get_active_source().get_printings().get("Remnant Elemental")
    if real is None:
        pytest.skip("Remnant Elemental absent from active CardSource")
    assert real.is_creature
    assert len(real.triggered_abilities) == 1
    ta = real.triggered_abilities[0]
    assert ta.event == Event.ENTERS
    assert isinstance(ta.effect, PumpSelfUntilEOT)
    assert ta.effect.power_bonus == 2
    assert ta.effect.toughness_bonus == 0
    assert ta.effect.granted_keywords == frozenset()

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2
    ZH = 0

    py_src = py.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    py_src.summoning_sick = False
    py_src.tapped = False
    py_src.damage = 0
    py_src.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_src)

    rs_src = rs.register_and_inject_object(
        {"name": "Remnant Elemental", "card_types": ["Creature"],
         "power": real.power, "toughness": real.toughness,
         "triggered_abilities": [{
             "event": "enters",
             "predicate": {"kind": "and",
                           "left": {"kind": "subject_is_land"},
                           "right": {"kind": "controlled_by_you"}},
             "effect": {"kind": "pump_self_until_eot",
                        "power_bonus": 2, "toughness_bonus": 0}}]},
        0, ZB,
    )

    fp = CardPrinting(
        name="Forest", mana_cost_str="", mana_cost=ManaCost(),
        type_line="Basic Land — Forest", supertypes=("Basic",),
        card_types=("Land",), subtypes=("Forest",),
        power=None, toughness=None, produces=frozenset({"G"}),
    )
    py_f = py.new_object(fp, owner_id=0, zone=Zone.HAND)
    py.players[0].hand.append(py_f)
    rs_f = rs.register_and_inject_object(
        {"name": "Forest", "card_types": ["Land"],
         "mana_produced": ["G"], "supertypes": ["Basic"]},
        0, ZH,
    )

    py.players[0].lands_played_this_turn = 0
    _play_land(py, 0, py_f.id)
    rs.play_land(rs_f, 0)
    assert len(py.stack) == 1 and rs.stack_size() == 1, (
        "the landfall trigger should land on BOTH stacks"
    )

    _drain_both(py, rs)
    assert len(py.stack) == 0 and rs.stack_size() == 0

    # Concrete observable: 0/4 base → effective power 2 on BOTH.
    assert effective_power(py, py_src) == real.power + 2 == 2
    assert rs.effective_power(rs_src) == real.power + 2 == 2

    for o in py.battlefield:
        if o.printing.name == "Forest":
            o.summoning_sick = False

    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Remnant Elemental landfall +2/+0 self-pump must be "
        f"byte-equal across the WHOLE field view on BOTH engines; "
        f"diffs={diffs}"
    )
