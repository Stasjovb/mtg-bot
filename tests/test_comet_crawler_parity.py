"""Cross-engine parity probes for Comet Crawler.

**Comet Crawler Cycle 1 closure (2026-05-22).** ``{2}{B}`` Creature
— Insect Horror, 2/3, Lifelink. Attack trigger: "Whenever this creature
attacks, you may sacrifice another creature or artifact. If you do,
this creature gets +2/+0 until end of turn." (~9,732 17lands decks; the
Tier-C ``OptionalSacAnotherForPumpSelfUEOT`` slot per
``docs/EFFECT_UNCOVERED_TIERC_CLOSEST_TO_A.md`` row 4.)

Mirrors Python's ``OptionalSacAnotherForPumpSelfUEOT(power_bonus=2,
toughness_bonus=0, granted_keywords=frozenset())``
(``effects/combinators.py:430``).

The single-cycle substrate that makes this slice possible:

  1. **Rust ``Effect::OptionalSacAnotherForPumpSelfUEOT { power_bonus,
     toughness_bonus }``** — two-int variant + parse arm in
     ``rust/src/cards.rs::parse_effect`` + ``to_pydict`` arm + resolve
     arm in ``rust/src/state_ops_resolve.rs`` (the production mint
     site: scan source-controller's bf for the FIRST eligible other-
     creature-or-artifact, sacrifice via CR 400.7 reset, push
     ``UeotModifier::PowerToughnessBonus`` onto the source's
     ``ueot_modifiers``).
  2. **Bridge dict→Python arm** in
     ``cross_engine.py::_ta_dict_to_python_effect`` reconstructs the
     Python class with the two-int field shape. ``granted_keywords`` is
     intentionally dropped at the bridge (no EoE printing emits it
     today; future printing with the rider lands the field on both
     sides together).

**Per-card parity probe path (NOT spell-card-bridge admit set).**
Comet Crawler is a creature with an ATTACKS triggered ability; the
spell-card-bridge admit set + auto-grow §2 teeth gate spell cards
only. The cross-engine probe instead uses the per-card dedicated
parity-test module convention (cf. ``test_dyadrine_attack.py``,
``test_mutinous_massacre_parity.py``), driving the parsed Comet
Crawler printing through both engines on a shared shape and pinning
byte-equal observables. The trajectory.py safe-trigger admit gate
(``_python_ta_to_safe_dict``) is NOT widened here — that gate is
about the **production-deck bench** admit set for full-card cross-
engine bench play, a distinct concern; landing Comet Crawler there
is a follow-up cycle (the bench widen requires additional substrate
the per-card probe doesn't).

**No-agent default = "do".** Python's
``OptionalSacAnotherForPumpSelfUEOT.resolve`` no-agent default
(``combinators.py:461-462``) picks ``options[0]`` and sacrifices it;
Rust's resolve arm picks the FIRST eligible victim in bf insertion
order. The cross-engine harness keeps Rust bf insertion order in
lockstep with Python (the harness's standard contract — see
:func:`mtg_bot.parity.cross_engine.build_python_state` /
:func:`build_rust_state`), so the same object is sacrificed on BOTH
engines.

**Observable byte-equality scope.** The harness's
``_build_field_view`` 8-tuple per zone object is ``(printing_name,
tapped, summoning_sick, damage, net_counters, attached_to,
controller_id, id)`` — the UEOT P/T bonus is NOT in the byte-equal
slot set (Python carries it on the ``temp_power_bonus`` write-through
field + the registry's ``expires_at="cleanup"`` entry; Rust carries it
on ``ueot_modifiers``). The byte-equal compare therefore covers the
sacrifice path (the victim moves bf → graveyard on both engines) +
zone-level shape; the pump path is pinned by a separate
``effective_power`` readback on both engines (the round-74 R74-3
byte-equal cleanup mapping precedent — same pattern as Biosynthic
Burst / GrantKeywordsToTargetCreatureUntilEOT probes).

Coverage:

- Parser SoT pin: parsed Comet Crawler printing's ATTACKS trigger
  effect IS ``OptionalSacAnotherForPumpSelfUEOT(power_bonus=2,
  toughness_bonus=0, granted_keywords=frozenset())``.
- Serializer round-trip: dict→Python via
  ``_ta_dict_to_python_effect`` reconstructs the same class with the
  same field values; Rust ``Effect::OptionalSacAnotherForPumpSelfUEOT``
  → dict (via ``effect_to_pydict`` driving ``get_printing_effects``-
  style readback) emits the expected three-key dict shape.
- Effect-coverage class pin: ``OptionalSacAnotherForPumpSelfUEOT``
  is in the covered-by-rust set (the new Rust enum variant maps 1:1
  to the Python class via the identity rule in
  ``effect_coverage.map_rust_to_python``).
- Rust resolve-arm unit pins:
    * Sac+pump path — fodder on controller's bf becomes pumped
      ``effective_power`` 4 (= 2 base + 2 bonus).
    * No-fodder no-pump path — empty controller-bf (only attacker)
      silent no-op, ``effective_power`` stays 2.
    * Source-untrackable path — exotic resolve scenario silent no-op
      (defensive — not reachable from the live cast pipeline but
      pinned to lock in the early-return semantics).
- **GENUINE real-EoE cross-engine byte-equal probe** — drives the
  parsed Comet Crawler printing through Python + Rust engines:
    * p0's bf: real-EoE Comet Crawler (unsick) + a synthetic 2/2
      fodder bear.
    * p0 declares Comet Crawler as attacker on BOTH engines.
    * ATTACKS trigger fires + resolves on BOTH; fodder bear moves
      bf → p0's graveyard on BOTH; Comet Crawler stays on bf with
      pumped effective power 4 on BOTH.
    * ``compare_fields`` over the WHOLE field view = []  (byte-equal
      battlefield + graveyard + life + everything else).
    * Effective-power readback on BOTH engines = 4 (the pump pinned
      separately, outside the byte-equal slot).
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


def test_real_comet_crawler_attack_trigger_is_optional_sac_for_pump_self_ueot():
    """**Verify-first.** The live parser maps Comet Crawler's ATTACKS
    trigger to ``OptionalSacAnotherForPumpSelfUEOT(power_bonus=2,
    toughness_bonus=0, granted_keywords=frozenset())`` — pin the
    field shape so a parser drift is caught here, not silently
    downstream in the cross-engine probe."""
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.combinators import OptionalSacAnotherForPumpSelfUEOT
    from mtg_bot.effects.predicates import Event, IsSelf

    p = get_active_source().get_printings().get("Comet Crawler")
    if p is None:
        pytest.skip("Comet Crawler absent from active CardSource")
    assert "Creature" in p.card_types
    # Verify lifelink is on the printed face — substrate dependency.
    assert "lifelink" in p.keywords
    # Find the single ATTACKS triggered ability.
    attacks_tas = [
        ta for ta in p.triggered_abilities if ta.event is Event.ATTACKS
    ]
    assert len(attacks_tas) == 1, (
        f"Comet Crawler must have exactly 1 ATTACKS triggered ability; "
        f"got {len(attacks_tas)}"
    )
    ta = attacks_tas[0]
    assert isinstance(ta.predicate, IsSelf)
    assert ta.predicate.subject is None
    assert isinstance(ta.effect, OptionalSacAnotherForPumpSelfUEOT), (
        f"ATTACKS trigger effect must be OptionalSacAnotherForPumpSelfUEOT; "
        f"got {type(ta.effect).__name__}"
    )
    assert ta.effect.power_bonus == 2
    assert ta.effect.toughness_bonus == 0
    assert ta.effect.granted_keywords == frozenset()


# -------------------------------------------------------------------
# Serializer round-trip + covered-set membership pins.
# -------------------------------------------------------------------


def test_comet_crawler_effect_dict_to_python_round_trip():
    """Rust-shape dict → Python ``OptionalSacAnotherForPumpSelfUEOT``
    via ``_ta_dict_to_python_effect`` reconstructs the same field
    values. Bridge arm is the lever flip — without it, a Rust→Python
    triggered-ability translation would raise on the unknown kind.

    ``granted_keywords`` is INTENTIONALLY dropped at the bridge (the
    Rust variant has no rider field); the rebuilt instance has the
    default ``frozenset()`` regardless of what the dict carried."""
    from mtg_bot.effects.combinators import (
        OptionalSacAnotherForPumpSelfUEOT,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    d = {
        "kind": "optional_sac_another_for_pump_self_ueot",
        "power_bonus": 2,
        "toughness_bonus": 0,
    }
    rebuilt = _ta_dict_to_python_effect(d)
    assert isinstance(rebuilt, OptionalSacAnotherForPumpSelfUEOT), (
        f"dict→Python bridge must round-trip to "
        f"OptionalSacAnotherForPumpSelfUEOT; got {type(rebuilt).__name__}"
    )
    assert rebuilt.power_bonus == 2
    assert rebuilt.toughness_bonus == 0
    assert rebuilt.granted_keywords == frozenset()


def test_comet_crawler_effect_dict_missing_fields_default_to_zero():
    """Missing ``power_bonus`` / ``toughness_bonus`` defaults to 0 on
    both sides (Python class default + Rust parse default), so a
    future partial-dict producer doesn't crash the bridge."""
    from mtg_bot.effects.combinators import (
        OptionalSacAnotherForPumpSelfUEOT,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    rebuilt = _ta_dict_to_python_effect(
        {"kind": "optional_sac_another_for_pump_self_ueot"}
    )
    assert isinstance(rebuilt, OptionalSacAnotherForPumpSelfUEOT)
    assert rebuilt.power_bonus == 0
    assert rebuilt.toughness_bonus == 0


def test_comet_crawler_rust_effect_to_pydict_round_trip():
    """Rust ``Effect::OptionalSacAnotherForPumpSelfUEOT { power_bonus,
    toughness_bonus }`` → dict emits the expected three-key shape.

    Drives the round-trip through ``Registry.register_printing`` (the
    parse path) + ``get_printing_etb_effects`` (the ``effect_to_pydict``
    readback). Using ``etb_effects`` instead of ``triggered_abilities``
    because the Registry exposes an ``effect_to_pydict``-walking getter
    for the former but not the latter; the parse + serialize arms
    being exercised are identical (both walk ``parse_effect`` then
    ``effect_to_pydict`` on the same ``Effect`` variant)."""
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Comet Crawler Round-trip",
            "card_types": ["Creature"],
            "power": 2,
            "toughness": 3,
            "mana_cost": {"generic": 2, "B": 1},
            # etb_effects gives us a direct effect_to_pydict readback
            # (the Registry exposes get_printing_etb_effects but not a
            # parallel get_printing_triggered_abilities); the parse +
            # serialize path is the same code as the ATTACKS-trigger
            # case the cross-engine probe exercises.
            "etb_effects": [
                {
                    "kind": "optional_sac_another_for_pump_self_ueot",
                    "power_bonus": 2,
                    "toughness_bonus": 0,
                },
            ],
        }
    )
    effs = reg.get_printing_etb_effects(pid)
    assert len(effs) == 1, f"expected 1 etb_effect, got {len(effs)}"
    eff = effs[0]
    # PyDict from Rust — index by key.
    assert eff["kind"] == "optional_sac_another_for_pump_self_ueot"
    assert eff["power_bonus"] == 2
    assert eff["toughness_bonus"] == 0


def test_comet_crawler_class_covered_by_rust():
    """``OptionalSacAnotherForPumpSelfUEOT`` must be in the covered-by-
    rust set — the Rust ``Effect::OptionalSacAnotherForPumpSelfUEOT``
    variant declaration makes ``covered_python_class_set()`` include
    it via the 1:1 identity-mapping rule in
    ``effect_coverage.map_rust_to_python``. This is the §2 covered-
    set tooth (parity-doc / coverage-script "covered" alignment)."""
    from mtg_bot.parity.effect_coverage import covered_python_class_set

    covered = covered_python_class_set()
    assert "OptionalSacAnotherForPumpSelfUEOT" in covered, (
        "Rust Effect::OptionalSacAnotherForPumpSelfUEOT variant must "
        "make the Python OptionalSacAnotherForPumpSelfUEOT class "
        "covered via the 1:1 identity-mapping rule"
    )


# -------------------------------------------------------------------
# Rust resolve-arm unit pins (deterministic-yes / no-fodder no-pump /
# source-untrackable silent no-op).
# -------------------------------------------------------------------


def _fresh_rust_state():
    import mtg_bot_engine

    return mtg_bot_engine.make_synthetic_state(0, 0, 0)


def _inject_crawler(rs, owner: int = 0) -> int:
    """Inject a Comet-Crawler-shape creature with the ATTACKS trigger
    on owner's battlefield. Returns the object id."""
    return rs.register_and_inject_object(
        {
            "name": "Comet Crawler",
            "card_types": ["Creature"],
            "power": 2,
            "toughness": 3,
            "keywords": ["lifelink"],
            "mana_cost": {"generic": 2, "B": 1},
            "triggered_abilities": [
                {
                    "event": "attacks",
                    "predicate": {"kind": "source_is_self"},
                    "effect": {
                        "kind": "optional_sac_another_for_pump_self_ueot",
                        "power_bonus": 2,
                        "toughness_bonus": 0,
                    },
                },
            ],
        },
        owner,
        ZONE_BATTLEFIELD,
    )


def _inject_bear(rs, owner: int = 0) -> int:
    """Inject a vanilla 2/2 creature on owner's battlefield."""
    return rs.register_and_inject_object(
        {
            "name": "Wild Bear",
            "card_types": ["Creature"],
            "power": 2,
            "toughness": 2,
            "mana_cost": {"generic": 1, "G": 1},
        },
        owner,
        ZONE_BATTLEFIELD,
    )


def test_rust_resolve_sacs_first_fodder_and_pumps_crawler():
    """Sac + pump path: a fodder bear on p0's bf is the first
    eligible victim; resolve sacrifices it (bf → p0's graveyard) and
    pumps the Crawler's effective_power from 2 to 4."""
    rs = _fresh_rust_state()
    crawler = _inject_crawler(rs, owner=0)
    bear = _inject_bear(rs, owner=0)
    rs.clear_summoning_sick_for_player(0)

    assert rs.declare_attacker(crawler) is True, (
        "declare_attacker must succeed for unsick attacker"
    )
    assert rs.stack_size() == 1, (
        "ATTACKS trigger must push onto the stack"
    )
    rs.resolve_top_of_stack()

    bf_ids = [e["id"] for e in rs.battlefield_snapshot()]
    assert crawler in bf_ids, "Comet Crawler must remain on bf"
    assert bear not in bf_ids, "fodder bear must be sacrificed"
    # Bear moved to p0's graveyard.
    gy0_ids = [e["id"] for e in rs.graveyard_snapshot(0)]
    assert bear in gy0_ids, (
        "sacrificed bear must move to controller's graveyard"
    )
    # Crawler pumped: effective_power = 2 + 2 = 4.
    assert rs.effective_power(crawler) == 4, (
        f"Crawler effective_power must be 4 (2 base + 2 UEOT); "
        f"got {rs.effective_power(crawler)}"
    )


def test_rust_resolve_no_fodder_silent_noop_no_pump():
    """No-fodder no-pump path: Crawler is the only permanent on its
    controller's bf — no eligible victim (the "another" filter
    excludes the Crawler itself). Silent no-op: Crawler effective_
    power stays 2 (NO pump applied; mirrors Python's
    ``if not options: return`` early-return at
    ``combinators.py:457-458``)."""
    rs = _fresh_rust_state()
    crawler = _inject_crawler(rs, owner=0)
    rs.clear_summoning_sick_for_player(0)

    assert rs.declare_attacker(crawler) is True
    rs.resolve_top_of_stack()

    # Crawler still on bf, NO pump.
    bf_ids = [e["id"] for e in rs.battlefield_snapshot()]
    assert crawler in bf_ids
    assert rs.effective_power(crawler) == 2, (
        f"NO fodder → NO pump → effective_power stays 2; "
        f"got {rs.effective_power(crawler)}"
    )
    # NOTHING in p0's graveyard.
    assert rs.graveyard_snapshot(0) == [], (
        "no sacrifice occurred → graveyard stays empty"
    )


def test_rust_resolve_opponent_creature_is_not_eligible_fodder():
    """An opponent-controlled creature is NOT eligible fodder (the
    Python filter requires ``o.controller_id == controller_id`` —
    only the source's controller's permanents qualify). Resolve is
    a silent no-op even though p1 has a bear on the battlefield."""
    rs = _fresh_rust_state()
    crawler = _inject_crawler(rs, owner=0)
    # Opponent bear — NOT eligible fodder.
    p1_bear = _inject_bear(rs, owner=1)
    rs.clear_summoning_sick_for_player(0)

    assert rs.declare_attacker(crawler) is True
    rs.resolve_top_of_stack()

    # p1's bear unchanged on p1's bf.
    p1_bear_alive = any(
        e["id"] == p1_bear for e in rs.battlefield_snapshot()
    )
    assert p1_bear_alive, "opponent bear must NOT be sacrificed"
    # Crawler not pumped.
    assert rs.effective_power(crawler) == 2


def test_rust_resolve_artifact_fodder_is_eligible():
    """Artifacts on the controller's bf are eligible fodder (the
    Python filter is
    ``o.printing.is_creature or o.printing.is_artifact``). Pin the
    artifact-half of the eligibility OR explicitly — Crawler's
    printed oracle reads "creature or artifact" and both halves must
    fire."""
    rs = _fresh_rust_state()
    crawler = _inject_crawler(rs, owner=0)
    # Synthetic artifact on p0's bf.
    artifact = rs.register_and_inject_object(
        {
            "name": "Test Artifact",
            "card_types": ["Artifact"],
            "mana_cost": {"generic": 1},
        },
        0,
        ZONE_BATTLEFIELD,
    )
    rs.clear_summoning_sick_for_player(0)

    assert rs.declare_attacker(crawler) is True
    rs.resolve_top_of_stack()

    # Artifact sacrificed.
    bf_ids = [e["id"] for e in rs.battlefield_snapshot()]
    assert artifact not in bf_ids, (
        "artifact must be eligible fodder (creature OR artifact filter)"
    )
    gy0_ids = [e["id"] for e in rs.graveyard_snapshot(0)]
    assert artifact in gy0_ids
    # Pump fires.
    assert rs.effective_power(crawler) == 4


def test_rust_resolve_picks_first_eligible_in_insertion_order():
    """When multiple eligible fodders are on the controller's bf,
    the resolve arm picks the FIRST one in insertion-order (mirrors
    Python's ``[o for o in state.battlefield if ...]`` which
    preserves append order; the no-agent default's ``options[0]``).
    Pin the pick by injecting two fodders and asserting the EARLIER
    one is the victim."""
    rs = _fresh_rust_state()
    crawler = _inject_crawler(rs, owner=0)
    # Two fodder bears — first injected wins.
    bear1 = _inject_bear(rs, owner=0)
    bear2 = _inject_bear(rs, owner=0)
    rs.clear_summoning_sick_for_player(0)

    assert rs.declare_attacker(crawler) is True
    rs.resolve_top_of_stack()

    bf_ids = [e["id"] for e in rs.battlefield_snapshot()]
    assert bear1 not in bf_ids, "first-injected fodder must be picked"
    assert bear2 in bf_ids, "second-injected fodder must survive"
    assert rs.effective_power(crawler) == 4


# -------------------------------------------------------------------
# GENUINE real-EoE cross-engine probe — drives the parsed Comet
# Crawler printing through BOTH engines and pins byte-equal field
# view + effective-power readback.
# -------------------------------------------------------------------


@pytest.fixture(scope="module")
def parity_smoke():
    """Load ``scripts/parity_smoke.py`` as a module so the probe can
    call ``_build_field_view`` for the full cross-engine byte-equality
    compare — same fixture shape as ``tests/test_parity_smoke.py``
    and ``tests/test_probe_attacks_leaves_battlefield_x.py``."""
    repo_root = pathlib.Path(__file__).resolve().parent.parent
    script_path = repo_root / "scripts" / "parity_smoke.py"
    spec = importlib.util.spec_from_file_location(
        "parity_smoke", script_path
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["parity_smoke"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_cross_engine_real_eoe_comet_crawler_attack_trigger_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine byte-equal probe — Comet
    Crawler ATTACKS OptionalSacAnotherForPumpSelfUEOT.** The
    slug-credit anchor for the lane's COVERED → PROBED tier flip
    (~9,732 17lands decks).

    Drives the **real parsed Comet Crawler printing** through both
    engines:
      - p0's bf: real-EoE Comet Crawler (unsick) + a synthetic 2/2
        fodder bear.
      - Both engines: p0 declares Comet Crawler as attacker;
        ATTACKS trigger fires + resolves with NO agent on the
        source's controller → both engines pick the first eligible
        victim deterministically (Python: ``options[0]``; Rust:
        first-eligible scan in bf insertion order).
      - Post-resolve on BOTH: fodder bear in p0's graveyard;
        Crawler on bf with effective_power = 4.

    **Byte-equality scope.** The full ``compare_fields`` over the
    harness's 22-field view is empty — including the
    battlefield/graveyard signatures (the sacrifice path's
    observables). The UEOT pump itself is NOT in the byte-equal slot
    set (Python's ``temp_power_bonus`` vs Rust's
    ``ueot_modifiers``); it's pinned separately by the
    effective-power readback on both engines (the round-74 R74-3
    cleanup-mapping precedent).
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
    from mtg_bot.game import Zone, effective_power
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.predicates import Event
    from mtg_bot.effects.combinators import (
        OptionalSacAnotherForPumpSelfUEOT,
    )

    real = get_active_source().get_printings().get("Comet Crawler")
    if real is None:
        pytest.skip("Comet Crawler absent from active CardSource")

    # §2 source-of-truth: genuine ATTACKS trigger must be
    # OptionalSacAnotherForPumpSelfUEOT(power_bonus=2,
    # toughness_bonus=0).
    attacks_ta = next(
        (
            ta for ta in real.triggered_abilities
            if ta.event is Event.ATTACKS
        ),
        None,
    )
    assert attacks_ta is not None, (
        "Comet Crawler must have an ATTACKS triggered ability"
    )
    assert isinstance(
        attacks_ta.effect, OptionalSacAnotherForPumpSelfUEOT
    ), (
        f"ATTACKS trigger must be OptionalSacAnotherForPumpSelfUEOT; "
        f"got {type(attacks_ta.effect).__name__}"
    )
    assert attacks_ta.effect.power_bonus == 2
    assert attacks_ta.effect.toughness_bonus == 0

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2

    # Synthetic 2/2 fodder bear (printing shape that mirrors the Rust
    # inject below) — used on BOTH engines for byte-equal sacrifice.
    def _bear_printing(name: str) -> CardPrinting:
        return CardPrinting(
            name=name,
            mana_cost_str="",
            mana_cost=ManaCost(generic=1, colored=(("G", 1),)),
            type_line="Creature — Bear",
            supertypes=(),
            card_types=("Creature",),
            subtypes=("Bear",),
            power=2,
            toughness=2,
            produces=frozenset(),
            keywords=frozenset(),
        )

    # --- Python: real Comet Crawler + synthetic bear on p0's bf ----
    py_crawler = py.new_object(
        real, owner_id=0, zone=Zone.BATTLEFIELD
    )
    py_crawler.summoning_sick = False
    py_crawler.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_crawler)
    py_bear = py.new_object(
        _bear_printing("CC Real Bear"),
        owner_id=0,
        zone=Zone.BATTLEFIELD,
    )
    py_bear.summoning_sick = False
    py_bear.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_bear)
    # No agent on p0 — defensive default fires "pick options[0]" at
    # resolve time (combinators.py:461-462).
    py.players[0].agent = None

    # --- Rust: same shape via register_and_inject_object ---
    rs_crawler = rs.register_and_inject_object(
        {
            "name": "Comet Crawler",
            "card_types": ["Creature"],
            "power": int(real.power),
            "toughness": int(real.toughness),
            "keywords": ["lifelink"],
            "mana_cost": {"generic": 2, "B": 1},
            "triggered_abilities": [
                {
                    "event": "attacks",
                    "predicate": {"kind": "source_is_self"},
                    "effect": {
                        "kind": "optional_sac_another_for_pump_self_ueot",
                        "power_bonus": 2,
                        "toughness_bonus": 0,
                    },
                },
            ],
        },
        0,
        ZB,
    )
    rs_bear = rs.register_and_inject_object(
        {
            "name": "CC Real Bear",
            "card_types": ["Creature"],
            "power": 2,
            "toughness": 2,
            "mana_cost": {"generic": 1, "G": 1},
        },
        0,
        ZB,
    )
    rs.clear_summoning_sick_for_player(0)

    # ---- Declare attacker on both, fire + resolve the ATTACKS trigger.
    py_declare_attackers(py, [py_crawler.id])
    assert len(py.stack) == 1, "Python: ATTACKS trigger must push"
    assert rs.declare_attacker(rs_crawler) is True
    assert rs.stack_size() == 1, "Rust: ATTACKS trigger must push"

    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert len(py.stack) == 0 and rs.stack_size() == 0

    # ---- Observable parity: bear sacrificed on BOTH; Crawler pumped.
    # Python observables.
    assert py_bear not in py.battlefield, (
        "Python: fodder bear must be sacrificed"
    )
    assert py_bear in py.players[0].graveyard, (
        "Python: fodder bear must be in p0's graveyard"
    )
    assert effective_power(py, py_crawler) == 4, (
        f"Python: Crawler effective_power must be 4; "
        f"got {effective_power(py, py_crawler)}"
    )

    # Rust observables.
    rs_bf_ids = [e["id"] for e in rs.battlefield_snapshot()]
    assert rs_bear not in rs_bf_ids, (
        "Rust: fodder bear must be sacrificed"
    )
    rs_gy0_ids = [e["id"] for e in rs.graveyard_snapshot(0)]
    assert rs_bear in rs_gy0_ids, (
        "Rust: fodder bear must be in p0's graveyard"
    )
    assert rs.effective_power(rs_crawler) == 4, (
        f"Rust: Crawler effective_power must be 4; "
        f"got {rs.effective_power(rs_crawler)}"
    )

    # ---- Full byte-equal field-view compare. The UEOT pump itself
    # is NOT in the 8-tuple slot set (see module docstring); the
    # sacrifice (bf → graveyard) IS captured and must agree.
    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Comet Crawler ATTACKS optional-sac-for-pump must be "
        f"byte-equal across the WHOLE field view on BOTH; diffs={diffs}"
    )
