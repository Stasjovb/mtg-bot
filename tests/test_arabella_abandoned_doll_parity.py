"""Cross-engine parity probes for Arabella, Abandoned Doll.

**Arabella, Abandoned Doll Cycle 1 closure (2026-05-23).** ``{R}{W}``
Legendary Artifact Creature -- Toy, 1/3, no keywords (Duskmourn, in the
active ``OracleParserCardSource``). Oracle text::

    Whenever Arabella attacks, it deals X damage to each opponent and
    you gain X life, where X is the number of creatures you control
    with power 2 or less.

The ``effect_uncovered`` + ``nonsafe_triggered_ability`` multi-gate
classifier blocker -- the missing Effect class is
``ArabellaAttackEffect`` (``effects/bespoke.py:2904``).

The single-cycle substrate that makes this slice possible:

  1. **Rust ``Effect::ArabellaAttackEffect``** -- unit (no fields)
     variant in ``rust/src/cards.rs`` (the
     ``SetLifeToHalfStartingRoundedUp`` /
     ``FanaticOfTheHarrowingETBEffect`` /
     ``BoilerbilgesRipperETBEffect`` /
     ``TerrapactIntimidatorETBEffect`` unit-variant idiom), parse arm
     (``parse_effect``; round-trips the bare
     ``{"kind": "arabella_attack_effect"}`` dict shape),
     ``to_pydict`` arm (emits ONLY ``kind``), and resolve arm in
     ``rust/src/state_ops_resolve.rs`` that:
       * locates the source-controller via the standard 5-zone walk
         (mirrors the Fanatic / Endstone source-finder pattern);
       * counts ``X = |{ o in controller.battlefield : o.is_creature
         AND effective_power(o) <= 2 }|`` (the source itself counts
         when its own effective power is <= 2 -- no "other"
         exclusion);
       * silently returns when ``X <= 0`` (mirrors Python's
         ``if x <= 0: return``);
       * otherwise subtracts ``X`` from each non-controller
         non-``has_lost`` player's ``life`` AND adds ``X`` to the
         source-controller's ``life``.
  2. **Bridge dict->Python arm** in
     ``cross_engine.py::_ta_dict_to_python_effect`` reconstructs the
     Python ``ArabellaAttackEffect()`` from the one-key dict shape.
  3. **Coverage 1:1 identity mapping.** The new Rust variant name
     matches the Python class name 1:1, so
     ``effect_coverage.covered_python_class_set()`` auto-includes
     ``ArabellaAttackEffect`` -- closes the ``effect_uncovered``
     classifier gate at the covered-set level.

**Multi-gated card; classifier multi-gate state stays True after the
cycle.** Per the round-58 subsystem-attribution classifier, Arabella,
Abandoned Doll is multi-gated on
``effect_uncovered + nonsafe_triggered_ability``. The cycle closes
the ``effect_uncovered`` gate (the ``ArabellaAttackEffect`` Python
class flips from ``missing_effect_classes`` to covered), but the
``nonsafe_triggered_ability`` gate KEEPS the card multi-gated at the
classifier level. The trajectory safe-trigger admit gate
(``parity/trajectory.py::_python_ta_to_safe_dict``) is INTENTIONALLY
NOT widened -- the safe-trigger gate's whitelist does not admit
Arabella's ``Event.ATTACKS`` + ``ArabellaAttackEffect`` leaf
(``ATTACKS`` is a recognized event but the bespoke effect class is
not in the leaf-effect whitelist), and widening it is a
production-deck-bench admit-set concern distinct from per-card
real-EoE parity probes. **The card DOES move to PROBED tier through
the dedicated per-card real-EoE byte-equal cross-engine probe
below**, the same precedent as Boilerbilges Ripper / Comet Crawler /
Friendly Teddy / Genemorph Imago / Fanatic of the Harrowing /
Vaultguard Trooper / Endstone / Terrapact Intimidator.

**Per-card parity probe path (NOT spell-card-bridge admit set).**
Arabella is a creature with an ATTACKS triggered ability (NOT a
non-creature spell admitted through the spell-card-bridge admit set
in ``trajectory.py::_python_spell_effect_to_dict``). The cross-engine
probe uses the per-card dedicated parity-test module convention (cf.
``test_comet_crawler_parity.py``, ``test_endstone_parity.py``),
driving the parsed Arabella printing through both engines on a
shared shape and pinning byte-equal observables.

**Probe drive -- Event::ATTACKS via declare_attacker.** Arabella's
trigger is per-attacker ``Event.ATTACKS`` with
``Predicate::SourceIsSelf``. The probe drives both engines through
``declare_attacker`` (Rust) /
``mtg_bot.combat.declare_attackers`` (Python) on the unsick
Arabella, which fires the trigger onto the stack on both sides; the
resolve drains the stack on both, applying the X-from-count damage /
life-gain identically.

**Probe drive -- bf-seeded X counter.** With ONLY Arabella on the
source-controller's bf, X = 1 (the source itself counts: its own
effective power is 1 <= 2). The probe additionally seats a synthetic
2/2 fodder bear on p0's bf so X = 2 (the bear's power = 2 also
qualifies), making the per-opponent damage and life-gain
non-trivially observable (life delta = +/- 2 rather than +/- 1).

**Observable byte-equality scope.** The harness's ``_build_field_view``
8-tuple per zone object (printing_name, tapped, summoning_sick,
damage, net_counters, attached_to, controller_id, id) is unaffected
by life totals (life isn't in the per-object 8-tuple). The probe
pins life-total equality directly (``py.players[0].life ==
rs.get_life(0)``, ``...[1]``) AND a full-field-view
``compare_fields == []`` over the harness's zone-state view (every
zone, both players).

Coverage:

  - Parser SoT pin: parsed Arabella printing has the
    ``Event.ATTACKS`` triggered ability with predicate ``IsSelf`` and
    effect ``ArabellaAttackEffect()``.
  - Bridge dict->Python round-trip: ``_ta_dict_to_python_effect``
    rebuilds a default-constructed ``ArabellaAttackEffect`` from the
    one-key dict.
  - Rust ``Effect::ArabellaAttackEffect`` parse + to_pydict
    round-trip via ``register_printing`` (etb_effects readback).
  - Rust resolve-arm unit pins:
      * X = 0 (no qualifying creatures on bf) -- silent no-op (no
        damage, no life gain).
      * X = 1 (only Arabella herself on bf -- her own power 1
        qualifies) -- p0 gains 1 life, p1 loses 1 life.
      * X = 2 (Arabella + a 2/2 bear on bf) -- p0 gains 2 life, p1
        loses 2 life.
      * Power-filter exclusion -- a 4/4 ogre on bf does NOT count
        toward X (effective_power > 2).
      * Opponent-creature exclusion -- a 1/1 on the opponent's bf
        does NOT count toward X (controller-only filter).
  - Effect-coverage class pin: ``ArabellaAttackEffect`` is in the
    covered-by-rust set (the new Rust enum variant maps 1:1 to the
    Python class via the identity rule in
    ``effect_coverage.map_rust_to_python``).
  - **GENUINE real-EoE cross-engine byte-equal probe** -- drives the
    parsed Arabella printing through Python + Rust engines:
      * p0's bf: real Arabella (unsick) + a synthetic 2/2 fodder
        bear (so X = 2).
      * Both engines declare Arabella as attacker.
      * ATTACKS trigger fires + resolves on BOTH.
      * Post-resolve: p0.life == 22 (default 20 + gain 2), p1.life
        == 18 (default 20 - 2).
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


# ---------------------------------------------------------------------------
# (1) Parser SoT -- Arabella is parser-claimed and emits the expected
# Event.ATTACKS triggered ability + ArabellaAttackEffect effect.
# ---------------------------------------------------------------------------


def test_real_arabella_attack_trigger_is_arabella_attack_effect():
    """**Verify-first.** The live parser maps Arabella's ATTACKS
    trigger to ``ArabellaAttackEffect()`` (a parameterless frozen
    dataclass). Pin the shape so a parser drift is caught here, not
    silently downstream in the cross-engine probe. Also pins the
    printing surface (cost, supertype, types, power/toughness)."""
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.bespoke import ArabellaAttackEffect
    from mtg_bot.effects.predicates import Event, IsSelf

    p = get_active_source().get_printings().get("Arabella, Abandoned Doll")
    if p is None:
        pytest.skip("Arabella, Abandoned Doll absent from active CardSource")
    assert "Artifact" in p.card_types
    assert "Creature" in p.card_types
    assert "Legendary" in p.supertypes
    assert p.mana_cost_str == "{R}{W}"
    assert p.power == 1
    assert p.toughness == 3
    # Exactly one triggered ability: ATTACKS -> ArabellaAttackEffect.
    assert len(p.triggered_abilities) == 1, (
        f"Arabella, Abandoned Doll must have exactly 1 triggered "
        f"ability; got {len(p.triggered_abilities)}"
    )
    ta = p.triggered_abilities[0]
    assert ta.event is Event.ATTACKS, (
        f"Arabella's only TA must be ATTACKS; got {ta.event}"
    )
    assert isinstance(ta.predicate, IsSelf), (
        f"Arabella's ATTACKS predicate must be IsSelf; "
        f"got {type(ta.predicate).__name__}"
    )
    assert ta.predicate.subject is None, (
        f"IsSelf.subject must be None (the implicit-self shape); "
        f"got {ta.predicate.subject}"
    )
    assert isinstance(ta.effect, ArabellaAttackEffect), (
        f"ATTACKS trigger effect must be ArabellaAttackEffect; "
        f"got {type(ta.effect).__name__}"
    )
    # Field-free unit dataclass -- equality with a fresh
    # default-constructed instance.
    assert ta.effect == ArabellaAttackEffect()


# ---------------------------------------------------------------------------
# (2) Serializer round-trip -- dict -> Python class. The bridge arm is
# the Rust->Python translation lever; without it, a Rust to_pydict
# emission could not rebuild the Python class.
# ---------------------------------------------------------------------------


def test_arabella_effect_dict_to_python_round_trip():
    """Rust-shape dict -> Python ``ArabellaAttackEffect`` via
    ``_ta_dict_to_python_effect`` reconstructs a default-constructed
    instance. Bridge arm is the lever flip -- without it, a
    Rust->Python triggered-ability translation would raise on the
    unknown kind."""
    from mtg_bot.effects.bespoke import ArabellaAttackEffect
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    d = {"kind": "arabella_attack_effect"}
    rebuilt = _ta_dict_to_python_effect(d)
    assert isinstance(rebuilt, ArabellaAttackEffect), (
        f"dict->Python bridge must round-trip to "
        f"ArabellaAttackEffect; got {type(rebuilt).__name__}"
    )
    # Field-free unit dataclass; equality with a fresh instance.
    assert rebuilt == ArabellaAttackEffect()


@_rust_skip
def test_arabella_rust_effect_to_pydict_round_trip():
    """Rust ``Effect::ArabellaAttackEffect`` -> dict emits the
    expected one-key shape. Drives the round-trip through
    ``Registry.register_printing`` (the parse path) +
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
            "name": "Arabella Round-trip",
            "card_types": ["Artifact", "Creature"],
            "supertypes": ["Legendary"],
            "power": 1,
            "toughness": 3,
            "mana_cost": {"R": 1, "W": 1},
            "etb_effects": [
                {"kind": "arabella_attack_effect"},
            ],
        }
    )
    effs = reg.get_printing_etb_effects(pid)
    assert len(effs) == 1, f"expected 1 etb_effect, got {len(effs)}"
    eff = effs[0]
    assert eff["kind"] == "arabella_attack_effect"
    # Field-free unit variant -- no other keys.
    assert set(eff.keys()) == {"kind"}, (
        f"unit-variant to_pydict must emit ONLY 'kind'; got keys "
        f"{sorted(eff.keys())}"
    )


# ---------------------------------------------------------------------------
# (3) Rust resolve-arm unit pins -- X-from-count cases + filter checks.
# ---------------------------------------------------------------------------


def _fresh_rust_state():
    import mtg_bot_engine

    return mtg_bot_engine.make_synthetic_state(0, 0, 0)


def _inject_arabella(rs, owner: int = 0) -> int:
    """Inject an Arabella-shape Creature on owner's battlefield
    carrying the ATTACKS trigger -> ArabellaAttackEffect effect.
    Returns the object id."""
    return rs.register_and_inject_object(
        {
            "name": "Arabella, Abandoned Doll",
            "card_types": ["Artifact", "Creature"],
            "supertypes": ["Legendary"],
            "power": 1,
            "toughness": 3,
            "mana_cost": {"R": 1, "W": 1},
            "triggered_abilities": [
                {
                    "event": "attacks",
                    "predicate": {"kind": "source_is_self"},
                    "effect": {"kind": "arabella_attack_effect"},
                },
            ],
        },
        owner,
        ZONE_BATTLEFIELD,
    )


def _inject_creature(
    rs, owner: int, power: int, toughness: int, name: str
) -> int:
    """Inject a vanilla power/toughness creature."""
    return rs.register_and_inject_object(
        {
            "name": name,
            "card_types": ["Creature"],
            "power": power,
            "toughness": toughness,
            "mana_cost": {"generic": 1},
        },
        owner,
        ZONE_BATTLEFIELD,
    )


@_rust_skip
def test_rust_resolve_arabella_x_equals_one_self_only():
    """Only Arabella on the source-controller's bf. Her own
    effective_power = 1 <= 2 qualifies, so X = 1. p0 gains 1 life,
    p1 loses 1 life."""
    rs = _fresh_rust_state()
    rs.set_life(0, 20)
    rs.set_life(1, 20)
    arabella = _inject_arabella(rs, owner=0)
    rs.clear_summoning_sick_for_player(0)

    assert rs.declare_attacker(arabella) is True
    assert rs.stack_size() == 1, "ATTACKS trigger must push exactly one"
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
        rs.apply_sbas_until_quiescent()

    assert rs.life_totals[0] == 21, (
        f"source-controller gains X=1 life; got {rs.life_totals[0]}"
    )
    assert rs.life_totals[1] == 19, (
        f"opponent loses X=1 life; got {rs.life_totals[1]}"
    )


@_rust_skip
def test_rust_resolve_arabella_x_equals_two_arabella_plus_bear():
    """Arabella (power 1) + a 2/2 bear on the source-controller's bf.
    Both qualify (1 <= 2 and 2 <= 2), so X = 2. p0 gains 2 life, p1
    loses 2 life."""
    rs = _fresh_rust_state()
    rs.set_life(0, 20)
    rs.set_life(1, 20)
    arabella = _inject_arabella(rs, owner=0)
    _inject_creature(rs, owner=0, power=2, toughness=2, name="Bear")
    rs.clear_summoning_sick_for_player(0)

    assert rs.declare_attacker(arabella) is True
    assert rs.stack_size() == 1
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
        rs.apply_sbas_until_quiescent()

    assert rs.life_totals[0] == 22, (
        f"source-controller gains X=2 life; got {rs.life_totals[0]}"
    )
    assert rs.life_totals[1] == 18, (
        f"opponent loses X=2 life; got {rs.life_totals[1]}"
    )


@_rust_skip
def test_rust_resolve_arabella_power_filter_excludes_4_4():
    """A 4/4 ogre on the source-controller's bf does NOT count toward
    X (effective_power 4 > 2). Arabella herself still counts (1 <= 2),
    so X = 1 -- not X = 2."""
    rs = _fresh_rust_state()
    rs.set_life(0, 20)
    rs.set_life(1, 20)
    arabella = _inject_arabella(rs, owner=0)
    _inject_creature(rs, owner=0, power=4, toughness=4, name="Ogre")
    rs.clear_summoning_sick_for_player(0)

    assert rs.declare_attacker(arabella) is True
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
        rs.apply_sbas_until_quiescent()

    assert rs.life_totals[0] == 21, (
        f"Power 4 > 2 must NOT count; X stays 1 from Arabella alone; "
        f"life={rs.life_totals[0]}"
    )
    assert rs.life_totals[1] == 19


@_rust_skip
def test_rust_resolve_arabella_opponent_creature_excluded():
    """A 1/1 creature on the OPPONENT's bf does NOT count toward X
    (the printed clause says "creatures you control", so only the
    source-controller's bf contributes). Arabella herself still
    counts (1 <= 2), so X = 1."""
    rs = _fresh_rust_state()
    rs.set_life(0, 20)
    rs.set_life(1, 20)
    arabella = _inject_arabella(rs, owner=0)
    # Opponent's 1/1 -- power qualifies, but controller is wrong.
    _inject_creature(rs, owner=1, power=1, toughness=1, name="OppDude")
    rs.clear_summoning_sick_for_player(0)
    rs.clear_summoning_sick_for_player(1)

    assert rs.declare_attacker(arabella) is True
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
        rs.apply_sbas_until_quiescent()

    assert rs.life_totals[0] == 21, (
        f"Opponent's 1/1 must NOT count; X stays 1 from Arabella; "
        f"life={rs.life_totals[0]}"
    )
    assert rs.life_totals[1] == 19


@_rust_skip
def test_rust_resolve_arabella_x_zero_silent_noop():
    """Arabella is on p1's bf with NO other creatures, and Arabella
    herself doesn't qualify because the source is on p1's bf but
    we're driving the resolve directly with no qualifying creatures
    (we'll hand-craft an X=0 via a direct etb-apply path: an
    Arabella carrier with NO creature presence on the controller's
    bf at all -- this proves the X<=0 silent-return path).

    Implementation note: we'd need a registry entry where the
    Arabella carrier itself is NOT a creature so it doesn't qualify
    in the count. We inject the carrier as a non-creature Artifact
    bearing the etb_effect, on a bf with no other creatures. X = 0
    -- silent no-op, both life totals unchanged."""
    rs = _fresh_rust_state()
    rs.set_life(0, 20)
    rs.set_life(1, 20)
    # Non-creature carrier so it doesn't self-count toward X.
    # The arm runs unconditionally on apply (no attack-trigger gate).
    carrier_id = rs.register_and_inject_object(
        {
            "name": "Arabella Non-creature Carrier",
            "card_types": ["Artifact"],
            "supertypes": ["Legendary"],
            "mana_cost": {"R": 1, "W": 1},
            "etb_effects": [
                {"kind": "arabella_attack_effect"},
            ],
        },
        0,
        ZONE_HAND,
    )
    rs.move_object(carrier_id, ZONE_BATTLEFIELD, 0)
    rs.apply_sbas_until_quiescent()
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
        rs.apply_sbas_until_quiescent()

    # X = 0 -- silent no-op, life totals unchanged on both sides.
    assert rs.life_totals[0] == 20, (
        f"X=0 must be a silent no-op (no life gain); "
        f"got life={rs.life_totals[0]}"
    )
    assert rs.life_totals[1] == 20, (
        f"X=0 must be a silent no-op (no damage); "
        f"got life={rs.life_totals[1]}"
    )


# ---------------------------------------------------------------------------
# (4) Effect-coverage class pin -- the new Rust variant makes the
# Python class covered via the 1:1 identity-mapping rule.
# ---------------------------------------------------------------------------


def test_arabella_attack_effect_class_covered_by_rust():
    """``ArabellaAttackEffect`` must be in the covered-by-rust set --
    the Rust ``Effect::ArabellaAttackEffect`` variant declaration
    makes ``covered_python_class_set()`` include it via the 1:1
    identity-mapping rule in ``effect_coverage.map_rust_to_python``.
    This is the §2 covered-set tooth (parity-doc / coverage-script
    "covered" alignment) AND the closure of the classifier's
    ``effect_uncovered`` gate for Arabella, Abandoned Doll."""
    from mtg_bot.parity.effect_coverage import (
        collect_python_effect_vocab,
        collect_rust_effect_variants,
        covered_python_class_set,
    )

    py_classes, _examples, _n = collect_python_effect_vocab()
    assert "ArabellaAttackEffect" in py_classes, (
        "Arabella, Abandoned Doll must surface ArabellaAttackEffect "
        "in the parser-walked Python effect vocab"
    )
    rust_variants = collect_rust_effect_variants()
    assert "ArabellaAttackEffect" in rust_variants, (
        "the new Rust Effect variant must be discoverable by the "
        "cards.rs text parser"
    )
    covered = covered_python_class_set()
    assert "ArabellaAttackEffect" in covered, (
        "the new Rust variant pairs 1:1 with the parser-claimed "
        "Python class (no override / RUST_AHEAD_OF_POOL allowlist "
        "needed)"
    )


def test_arabella_classifier_effect_uncovered_gate_closed():
    """The round-58 subsystem-attribution classifier should report
    Arabella, Abandoned Doll with an EMPTY ``missing_effect_classes``
    list after this cycle -- proof the ``effect_uncovered`` gate is
    closed at the classifier level. The card stays multi-gated
    overall because ``nonsafe_triggered_ability`` is still in
    ``gates``; this test pins the effect-class closure specifically.

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
    row = attr["cards"].get("Arabella, Abandoned Doll")
    if row is None:
        pytest.skip(
            "Arabella, Abandoned Doll absent from classifier output "
            "(card moved out of blocked-subsystem tier post-closure)"
        )
    # effect_uncovered gate must be CLOSED at the effect-class level:
    # the missing list should now be empty.
    assert row["missing_effect_classes"] == [], (
        f"Cycle 1 closure expected `missing_effect_classes == []`; "
        f"got {row['missing_effect_classes']}"
    )


# ---------------------------------------------------------------------------
# (5) GENUINE real-EoE cross-engine byte-equal probe -- drives the
# parsed Arabella printing through BOTH engines via declare_attacker
# and pins byte-equal full-field-view + life-total equality.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def parity_smoke():
    """Load ``scripts/parity_smoke.py`` as a module so the probe can
    call ``_build_field_view`` for the full cross-engine byte-equality
    compare -- same fixture shape as ``tests/test_comet_crawler_parity.py``,
    ``tests/test_endstone_parity.py``, etc."""
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
def test_cross_engine_real_eoe_arabella_attack_trigger_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine byte-equal probe -- Arabella,
    Abandoned Doll ATTACKS ArabellaAttackEffect.**

    Drives the **real parsed Arabella printing** through both
    engines:
      - p0's bf: real Arabella (unsick) + a synthetic 2/2 fodder
        bear (both qualify under "effective_power <= 2" so X = 2).
      - Both engines: p0 declares Arabella as attacker; ATTACKS
        trigger fires + resolves with NO agent (the effect has no
        PendingDecision so no agent is required for byte-equal).
      - Post-resolve on BOTH: p0.life == 22 (default 20 + gain 2),
        p1.life == 18 (default 20 - 2). Arabella stays on p0's bf
        tapped (attacker); fodder bear stays on p0's bf.

    **Byte-equality scope.** The full ``compare_fields`` over the
    harness's field view is empty -- every zone state agrees
    byte-equal across engines. Life totals are pinned directly (life
    isn't in the per-object field-view 8-tuple).
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.combat import declare_attackers as py_declare_attackers
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.game import Zone
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.predicates import Event
    from mtg_bot.effects.bespoke import ArabellaAttackEffect

    real = get_active_source().get_printings().get("Arabella, Abandoned Doll")
    if real is None:
        pytest.skip("Arabella, Abandoned Doll absent from active CardSource")

    # §2 source-of-truth: genuine ATTACKS trigger must be
    # ArabellaAttackEffect.
    attacks_ta = next(
        (
            ta for ta in real.triggered_abilities
            if ta.event is Event.ATTACKS
        ),
        None,
    )
    assert attacks_ta is not None, (
        "Arabella must have an ATTACKS triggered ability"
    )
    assert isinstance(
        attacks_ta.effect, ArabellaAttackEffect
    ), (
        f"ATTACKS trigger must be ArabellaAttackEffect; "
        f"got {type(attacks_ta.effect).__name__}"
    )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2

    # Synthetic 2/2 fodder bear (printing shape that mirrors the Rust
    # inject below) -- used on BOTH engines so X = 2 (Arabella's 1 +
    # bear's 2 both qualify) for non-trivial life deltas.
    def _bear_printing(name: str) -> CardPrinting:
        return CardPrinting(
            name=name,
            mana_cost_str="",
            mana_cost=ManaCost(generic=1, colored=(("G", 1),)),
            type_line="Creature - Bear",
            supertypes=(),
            card_types=("Creature",),
            subtypes=("Bear",),
            power=2,
            toughness=2,
            produces=frozenset(),
            keywords=frozenset(),
        )

    # --- Python: real Arabella + synthetic bear on p0's bf ----
    py_arabella = py.new_object(
        real, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_arabella.summoning_sick = False
    py_arabella.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_arabella)
    py_bear = py.new_object(
        _bear_printing("Arabella Real Bear"),
        owner_id=0,
        zone=Zone.BATTLEFIELD,
    )
    py_bear.summoning_sick = False
    py_bear.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_bear)
    # No agent needed -- ArabellaAttackEffect has no PendingDecision.
    py.players[0].agent = None
    py.players[1].agent = None

    # --- Rust: same shape via register_and_inject_object ---
    rs_arabella = rs.register_and_inject_object(
        {
            "name": "Arabella, Abandoned Doll",
            "card_types": list(real.card_types),
            "supertypes": list(real.supertypes),
            "power": int(real.power),
            "toughness": int(real.toughness),
            "mana_cost": {"R": 1, "W": 1},
            "triggered_abilities": [
                {
                    "event": "attacks",
                    "predicate": {"kind": "source_is_self"},
                    "effect": {"kind": "arabella_attack_effect"},
                },
            ],
        },
        0,
        ZB,
    )
    rs_bear = rs.register_and_inject_object(
        {
            "name": "Arabella Real Bear",
            "card_types": ["Creature"],
            "power": 2,
            "toughness": 2,
            "mana_cost": {"generic": 1, "G": 1},
        },
        0,
        ZB,
    )
    rs.clear_summoning_sick_for_player(0)

    # ---- Pre-trigger sanity: nothing on either stack.
    assert rs.stack_size() == 0 and len(py.stack) == 0

    # ---- Declare attacker on both, fire + resolve the ATTACKS trigger.
    py_declare_attackers(py, [py_arabella.id])
    assert len(py.stack) == 1, "Python: ATTACKS trigger must push"
    assert rs.declare_attacker(rs_arabella) is True
    assert rs.stack_size() == 1, "Rust: ATTACKS trigger must push"

    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert len(py.stack) == 0 and rs.stack_size() == 0

    # ---- Observable parity: X = 2 -> p0 gains 2, p1 loses 2.
    assert py.players[0].life == 22, (
        f"Python: source-controller p0 life must be 22 (20+2); "
        f"got {py.players[0].life}"
    )
    assert py.players[1].life == 18, (
        f"Python: opponent p1 life must be 18 (20-2); "
        f"got {py.players[1].life}"
    )
    assert rs.get_life(0) == 22, (
        f"Rust: source-controller p0 life must be 22; "
        f"got {rs.get_life(0)}"
    )
    assert rs.get_life(1) == 18, (
        f"Rust: opponent p1 life must be 18; "
        f"got {rs.get_life(1)}"
    )

    # ---- Full byte-equal field-view compare over the WHOLE state.
    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Arabella ATTACKS ArabellaAttackEffect must be byte-equal "
        f"across the WHOLE field view on BOTH engines; diffs={diffs}"
    )
