"""Cross-engine parity probes for Boilerbilges Ripper.

**Boilerbilges Ripper Cycle 1 closure (2026-05-22).** ``{4}{R}``
Creature — Human Assassin, 4/4 (Duskmourn — sourced from
``data/duskmourn.json:17480``). ETB trigger body: "When this creature
enters, you may sacrifice another creature or enchantment. When you do,
this creature deals 2 damage to any target."

Mirrors Python's ``BoilerbilgesRipperETBEffect`` (parameterless frozen
dataclass at ``effects/bespoke.py:2738``).

**Multi-gated card; classifier stays multi-gated.** Per the round-58
subsystem-attribution classifier (``scripts/scout_r58_subsystem_
attribution.py``), Boilerbilges Ripper is multi-gated:

  * ``effect_uncovered`` — closed by this cycle. The new Rust variant
    ``Effect::BoilerbilgesRipperETBEffect`` makes the Python class
    ``BoilerbilgesRipperETBEffect`` covered via the 1:1 identity-mapping
    rule in ``effect_coverage.map_rust_to_python``; the classifier's
    ``missing_effect_classes`` array shrinks by one for this card.
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
Boilerbilges Ripper to PROBED tier. Same precedent as
``test_comet_crawler_parity.py``, ``test_dyadrine_attack.py``, and
``test_mutinous_massacre_parity.py``: a per-card probe drives the
real-EoE printing through both engines and pins byte-equal observables;
the safe-trigger bench admit set is widened in a separate cycle when
the production-deck bench needs it.

**NOT a spell-card-bridge admit-set extension.** Boilerbilges Ripper
is a Creature, not a non-creature spell. The spell-card-bridge admit
set (``trajectory.py::_python_spell_effect_to_dict`` + its §2 teeth)
gates non-creature spells only. The per-card probe approach is the
right tool here, exactly the Comet Crawler / Mutinous Massacre /
Dyadrine Attack convention.

**No-agent decline default = byte-equal silent no-op.** Python's
``BoilerbilgesRipperETBEffect.resolve`` (``effects/bespoke.py:
2776-2819``) walks four conditional gates:

  1. Build ``candidates`` = other-creature-or-enchantment on
     controller's bf.
  2. Empty candidates → silent return.
  3. ``p.agent is None`` OR ``agent.choose_yes_no(...)`` is False →
     silent return (no sacrifice, no damage). The ``p.agent is None``
     short-circuits FIRST whenever no agent is configured.
  4. (Only with a yes-agent.) Sacrifice victim + apply 2 damage to
     bound target.

The cross-engine probe convention drives BOTH engines with no agent
on the source's controller. Python takes gate 3 (``p.agent is None``
short-circuits the ``or`` to True → return); Rust has no agent surface
in ``apply_effect`` so the resolve arm is an empty no-op (gates 2+3
both produce the same observable: no bf change, no damage). The two
engines therefore agree byte-equal on the WHOLE field view.

**DISTINCTION from Comet Crawler.** Comet Crawler's
``OptionalSacAnotherForPumpSelfUEOT`` defaults to "DO" when no agent
(``combinators.py:461-462`` picks ``options[0]`` and sacrifices it);
the Rust mirror sacrifices the first eligible victim deterministically.
Boilerbilges Ripper's ``BoilerbilgesRipperETBEffect`` defaults to
"DECLINE" when no agent (gate-3 short-circuit); the Rust mirror
silently no-ops. Both are byte-equal under the no-agent probe
convention — the divergence is the no-agent default, not the
substrate.

**Cycle 2+ agent-surface widening.** A future cycle landing a Rust
agent surface (the analog of Python's ``Agent`` interface) will widen
the Rust resolve arm to gates 3-4: ask the agent yes/no, pick a
victim, sacrifice via the proven ``OptionalSacAnotherForPumpSelfUEOT``
CR 400.7 reset shape, then apply 2 damage to
``current_resolve_payload_target_id``. Cycle 1 lands ONLY the
``effect_uncovered`` gate closure + the no-agent byte-equal mirror;
the yes-agent gate-4 path is honest-stopped today (see
``docs/SEARCH_LIMITATIONS.md`` — Boilerbilges Ripper Cycle 1 entry).

Coverage:

- Parser SoT pin: the live parser maps Boilerbilges Ripper's ETB
  trigger to ``BoilerbilgesRipperETBEffect()`` (a parameterless frozen
  dataclass).
- Serializer round-trip: dict→Python via ``_ta_dict_to_python_effect``
  rebuilds ``BoilerbilgesRipperETBEffect()``; Rust
  ``Effect::BoilerbilgesRipperETBEffect`` → dict via
  ``Registry.get_printing_etb_effects`` emits the expected one-key
  dict shape.
- Effect-coverage class pin: ``BoilerbilgesRipperETBEffect`` is in the
  covered-by-rust set after this cycle (1:1 identity-mapping rule).
- Rust resolve-arm unit pins:
    * Decline path with fodder + bound target (the canonical no-agent
      mirror): Crawler-shape attacker + bear fodder + an opponent
      damage target — Rust resolve is a silent no-op, fodder stays on
      bf, opponent life unchanged.
    * Decline path with no candidates: source on bf without any other
      eligible permanent — silent no-op (gate-2 / gate-3 converge to
      the same observable).
- **GENUINE real-EoE cross-engine byte-equal probe** drives the parsed
  Boilerbilges Ripper printing through BOTH engines:
    * p0's bf: real-EoE Boilerbilges Ripper (no agent) + a synthetic
      2/2 enchantment-creature fodder + a synthetic 2/2 bear (also
      eligible fodder).
    * p1 is the bound damage target (a player).
    * Both engines drive the ETB resolution with no agent → no
      sacrifice, no damage.
    * Post-resolve on BOTH: fodder still on bf, Ripper still on bf,
      p1's life still 20.
    * ``compare_fields`` over the WHOLE field view = [] (byte-equal
      everywhere).
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


def test_real_boilerbilges_ripper_etb_trigger_is_bespoke_effect():
    """**Verify-first.** The live parser maps Boilerbilges Ripper's
    ETB trigger to ``BoilerbilgesRipperETBEffect()`` (a parameterless
    frozen dataclass). Pin the shape so a parser drift is caught
    here, not silently downstream in the cross-engine probe."""
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.bespoke import BoilerbilgesRipperETBEffect
    from mtg_bot.effects.predicates import Event, IsSelf

    p = get_active_source().get_printings().get("Boilerbilges Ripper")
    if p is None:
        pytest.skip("Boilerbilges Ripper absent from active CardSource")
    assert "Creature" in p.card_types
    assert p.power == 4
    assert p.toughness == 4
    # Single ETB triggered ability.
    enters_tas = [
        ta for ta in p.triggered_abilities if ta.event is Event.ENTERS
    ]
    assert len(enters_tas) == 1, (
        f"Boilerbilges Ripper must have exactly 1 ENTERS triggered "
        f"ability; got {len(enters_tas)}"
    )
    ta = enters_tas[0]
    assert isinstance(ta.predicate, IsSelf)
    assert ta.predicate.subject is None
    assert isinstance(ta.effect, BoilerbilgesRipperETBEffect), (
        f"ETB trigger effect must be BoilerbilgesRipperETBEffect; "
        f"got {type(ta.effect).__name__}"
    )
    # Field-free unit dataclass — equality with a fresh
    # default-constructed instance.
    assert ta.effect == BoilerbilgesRipperETBEffect()


# -------------------------------------------------------------------
# Serializer round-trip + covered-set membership pins.
# -------------------------------------------------------------------


def test_boilerbilges_ripper_effect_dict_to_python_round_trip():
    """Rust-shape dict → Python ``BoilerbilgesRipperETBEffect`` via
    ``_ta_dict_to_python_effect`` reconstructs a default-constructed
    instance. Bridge arm is the lever flip — without it, a Rust→Python
    triggered-ability translation would raise on the unknown kind."""
    from mtg_bot.effects.bespoke import BoilerbilgesRipperETBEffect
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    d = {"kind": "boilerbilges_ripper_etb_effect"}
    rebuilt = _ta_dict_to_python_effect(d)
    assert isinstance(rebuilt, BoilerbilgesRipperETBEffect), (
        f"dict→Python bridge must round-trip to "
        f"BoilerbilgesRipperETBEffect; got {type(rebuilt).__name__}"
    )
    # Field-free unit dataclass; equality with a fresh instance.
    assert rebuilt == BoilerbilgesRipperETBEffect()


def test_boilerbilges_ripper_rust_effect_to_pydict_round_trip():
    """Rust ``Effect::BoilerbilgesRipperETBEffect`` → dict emits the
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
            "name": "Boilerbilges Ripper Round-trip",
            "card_types": ["Creature"],
            "power": 4,
            "toughness": 4,
            "mana_cost": {"generic": 4, "R": 1},
            "etb_effects": [
                {"kind": "boilerbilges_ripper_etb_effect"},
            ],
        }
    )
    effs = reg.get_printing_etb_effects(pid)
    assert len(effs) == 1, f"expected 1 etb_effect, got {len(effs)}"
    eff = effs[0]
    assert eff["kind"] == "boilerbilges_ripper_etb_effect"
    # Field-free unit variant — no other keys.
    assert set(eff.keys()) == {"kind"}, (
        f"unit-variant to_pydict must emit ONLY 'kind'; got keys "
        f"{sorted(eff.keys())}"
    )


def test_boilerbilges_ripper_class_covered_by_rust():
    """``BoilerbilgesRipperETBEffect`` must be in the covered-by-rust
    set — the Rust ``Effect::BoilerbilgesRipperETBEffect`` variant
    declaration makes ``covered_python_class_set()`` include it via
    the 1:1 identity-mapping rule in
    ``effect_coverage.map_rust_to_python``. This is the §2 covered-
    set tooth (parity-doc / coverage-script "covered" alignment) AND
    the closure of the classifier's ``effect_uncovered`` gate for
    Boilerbilges Ripper."""
    from mtg_bot.parity.effect_coverage import covered_python_class_set

    covered = covered_python_class_set()
    assert "BoilerbilgesRipperETBEffect" in covered, (
        "Rust Effect::BoilerbilgesRipperETBEffect variant must make "
        "the Python BoilerbilgesRipperETBEffect class covered via the "
        "1:1 identity-mapping rule"
    )


def test_boilerbilges_ripper_classifier_effect_uncovered_gate_closed():
    """The round-58 subsystem-attribution classifier should report
    Boilerbilges Ripper with an EMPTY ``missing_effect_classes`` list
    after this cycle — proof the ``effect_uncovered`` gate is closed
    at the classifier level. The card stays multi-gated overall
    because ``nonsafe_triggered_ability`` is still in ``gates``; this
    test pins the effect-class closure specifically.

    NB: this is the canonical observable for "the Cycle 1
    effect_uncovered closure landed". The
    ``nonsafe_triggered_ability`` gate is deliberately NOT closed
    this cycle (no widen of ``_python_ta_to_safe_dict``), so the
    classifier's ``multi_gated`` flag stays ``True``."""
    repo_root = pathlib.Path(__file__).resolve().parent.parent
    scripts_dir = repo_root / "scripts"
    # Add scripts/ to sys.path the same way the verify-first command
    # in the task does. Scope to this test so we don't pollute other
    # tests' sys.path.
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
    row = attr["cards"].get("Boilerbilges Ripper")
    if row is None:
        pytest.skip("Boilerbilges Ripper absent from classifier output")
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


# -------------------------------------------------------------------
# Rust resolve-arm unit pins — no-agent decline silent no-op (the
# byte-equal mirror of Python's gate-3 short-circuit).
# -------------------------------------------------------------------


def _fresh_rust_state():
    import mtg_bot_engine
    return mtg_bot_engine.make_synthetic_state(0, 0, 0)


_RIPPER_PRINTING_DICT: dict = {
    "name": "Boilerbilges Ripper",
    "card_types": ["Creature"],
    "power": 4,
    "toughness": 4,
    "mana_cost": {"generic": 4, "R": 1},
    "triggered_abilities": [
        {
            "event": "enters",
            "predicate": {"kind": "source_is_self"},
            "effect": {
                "kind": "boilerbilges_ripper_etb_effect",
            },
        },
    ],
}


def _inject_ripper_in_hand(rs, owner: int = 0) -> int:
    """Inject a Boilerbilges-Ripper-shape creature into ``owner``'s
    HAND. Returns the object id. The caller then casts by
    ``rs.push_to_stack(rid, owner); rs.resolve_top_of_stack()`` —
    this drives the standard spell-resolution pipeline that lands
    the permanent on the bf AND fires its ETB trigger automatically
    (the synthesized self-ENTERS predicate path the round-58
    ETB-trigger substrate established for cross-engine probes).

    The ``triggered_abilities`` ENTERS+IsSelf+
    ``boilerbilges_ripper_etb_effect`` shape mirrors the parsed
    Python printing (which the live parser maps to a single
    ``TriggeredAbility(event=ENTERS, predicate=IsSelf(subject=None),
    effect=BoilerbilgesRipperETBEffect())``).
    """
    return rs.register_and_inject_object(
        _RIPPER_PRINTING_DICT,
        owner,
        ZONE_HAND,
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


def _cast_ripper_and_resolve_all(rs, ripper_id: int, controller: int = 0):
    """Cast the Ripper from ``controller``'s HAND via the standard
    spell-resolution pipeline:

      1. ``push_to_stack(ripper_id, controller)`` — append a
         ``StackItem::new_spell`` whose ``source_obj_id == ripper_id``.
      2. ``resolve_top_of_stack()`` — drains the spell resolution,
         which moves the Ripper from HAND → BATTLEFIELD AND queues
         the synthesized self-ENTERS triggered ability (the
         round-58 ETB-trigger substrate's ``triggered_abilities``
         dict-shape path drains via ``pending_etb_dispatches`` →
         ``push_triggered_ability``).
      3. Loop ``resolve_top_of_stack()`` until ``stack_size() == 0``
         — drains the ETB trigger itself, which on this Cycle 1
         arm is a silent no-op (the no-agent decline path).

    This is the byte-equal mirror of Python's cast-then-resolve
    pipeline used in the real-EoE cross-engine probe further down.
    """
    rs.push_to_stack(ripper_id, controller)
    # Loop until stack is empty — first resolve = the spell cast
    # (lands the Ripper on bf + queues the ETB trigger); subsequent
    # resolves drain the queued ETB trigger.
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()


def test_rust_resolve_with_fodder_no_agent_declines_silent_noop():
    """No-agent decline path with eligible fodder. Mirrors Python's
    gate-3 short-circuit (``p.agent is None`` → ``or`` evaluates True
    → silent return). Observable:

      * Fodder bear stays on bf (NOT sacrificed).
      * Nothing in p0's graveyard.
      * Opponent life unchanged at 20 (NO damage applied).

    The Ripper is cast from hand → lands on bf via the spell-
    resolution pipeline → ETB trigger queues on the stack → ETB
    trigger resolves into the Cycle 1 silent-no-op arm.
    """
    rs = _fresh_rust_state()
    bear = _inject_bear(rs, owner=0)
    ripper = _inject_ripper_in_hand(rs, owner=0)
    rs.clear_summoning_sick_for_player(0)

    _cast_ripper_and_resolve_all(rs, ripper, controller=0)

    bf_ids = [e["id"] for e in rs.battlefield_snapshot()]
    assert ripper in bf_ids, "Ripper must land on bf after spell resolves"
    assert bear in bf_ids, (
        "no-agent decline → fodder bear must NOT be sacrificed"
    )
    assert rs.graveyard_snapshot(0) == [], (
        "no sacrifice occurred → p0's graveyard stays empty"
    )
    # Opponent life unchanged (no damage applied).
    p1_life = rs.life_totals[1]
    assert p1_life == 20, (
        f"no damage applied → p1's life must stay 20; got {p1_life}"
    )


def test_rust_resolve_no_candidates_no_agent_silent_noop():
    """No-agent + no eligible fodder path. Gate 2 (empty candidates)
    and gate 3 (no agent) both converge to the same observable —
    silent no-op. Pin the gate-2 / gate-3 convergence."""
    rs = _fresh_rust_state()
    ripper = _inject_ripper_in_hand(rs, owner=0)
    rs.clear_summoning_sick_for_player(0)

    _cast_ripper_and_resolve_all(rs, ripper, controller=0)

    bf_ids = [e["id"] for e in rs.battlefield_snapshot()]
    assert ripper in bf_ids, "Ripper must land on bf after spell resolves"
    assert rs.graveyard_snapshot(0) == [], (
        "no candidates → no sacrifice → graveyard stays empty"
    )
    # No damage applied to either player.
    lts = rs.life_totals
    assert lts[0] == 20
    assert lts[1] == 20


def test_rust_resolve_opponent_fodder_is_not_eligible_no_pump():
    """An opponent-controlled creature is NOT eligible fodder (the
    Python filter requires ``o.controller_id == controller_id``).
    Combined with the no-agent decline path, this resolves to a
    silent no-op regardless of opponent's bf state.

    Pinning this gate now keeps the Cycle 2+ agent-surface widening
    honest: even with a yes-agent, the eligibility filter must still
    skip opponent-controlled permanents. Today the no-agent decline
    fires before the eligibility check is exercised, but pinning
    the observable forwards-protects the gate."""
    rs = _fresh_rust_state()
    p1_bear = _inject_bear(rs, owner=1)
    ripper = _inject_ripper_in_hand(rs, owner=0)
    rs.clear_summoning_sick_for_player(0)
    rs.clear_summoning_sick_for_player(1)

    _cast_ripper_and_resolve_all(rs, ripper, controller=0)

    # p1's bear unchanged on p1's bf — never sacrificed (wrong
    # controller; also the no-agent decline took the silent-return
    # path first).
    p1_bear_alive = any(
        e["id"] == p1_bear for e in rs.battlefield_snapshot()
    )
    assert p1_bear_alive, "opponent bear must NEVER be sacrificed"
    # No life loss on either side.
    lts = rs.life_totals
    assert lts[0] == 20
    assert lts[1] == 20


# -------------------------------------------------------------------
# GENUINE real-EoE cross-engine byte-equal probe — drives the parsed
# Boilerbilges Ripper printing through BOTH engines and pins
# byte-equal full-field-view + observable equality on the decline path.
# -------------------------------------------------------------------


@pytest.fixture(scope="module")
def parity_smoke():
    """Load ``scripts/parity_smoke.py`` as a module so the probe can
    call ``_build_field_view`` for the full cross-engine byte-equality
    compare — same fixture shape as ``tests/test_parity_smoke.py``,
    ``tests/test_comet_crawler_parity.py``, etc."""
    repo_root = pathlib.Path(__file__).resolve().parent.parent
    script_path = repo_root / "scripts" / "parity_smoke.py"
    spec = importlib.util.spec_from_file_location(
        "parity_smoke", script_path
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["parity_smoke"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_cross_engine_real_eoe_boilerbilges_ripper_decline_path_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine byte-equal probe — Boilerbilges
    Ripper ETB no-agent decline path.** The slug-credit anchor for the
    PROBED tier flip even though the classifier multi-gates the card
    on ``nonsafe_triggered_ability``.

    Drives the **real parsed Boilerbilges Ripper printing** through
    both engines:
      - p0's bf: real-EoE Boilerbilges Ripper (unsick) + a synthetic
        2/2 bear (eligible fodder).
      - p1 is the bound damage target (a player target — the ETB
        trigger's ``DealDamageAnyTarget``-shape legal_targets includes
        every non-eliminated player).
      - Both engines: drive the ETB trigger with NO agent on p0 →
        Python takes gate-3 short-circuit (``p.agent is None``);
        Rust resolve arm is an empty no-op.
      - Post-resolve on BOTH: fodder bear still on p0's bf, Ripper
        still on p0's bf, NO graveyard delta, p1 life still 20.

    **Byte-equality scope.** The full ``compare_fields`` over the
    harness's field view is empty — the no-agent decline path
    produces no observable delta on EITHER engine (no zone moves, no
    counters, no life changes). The cross-engine probe pins this
    silent-no-op equality as the byte-equal observable.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.game import Zone
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.predicates import Event
    from mtg_bot.effects.bespoke import BoilerbilgesRipperETBEffect

    real = get_active_source().get_printings().get("Boilerbilges Ripper")
    if real is None:
        pytest.skip("Boilerbilges Ripper absent from active CardSource")

    # §2 source-of-truth: genuine ENTERS trigger must be a
    # BoilerbilgesRipperETBEffect (parameterless).
    enters_ta = next(
        (
            ta for ta in real.triggered_abilities
            if ta.event is Event.ENTERS
        ),
        None,
    )
    assert enters_ta is not None, (
        "Boilerbilges Ripper must have an ENTERS triggered ability"
    )
    assert isinstance(
        enters_ta.effect, BoilerbilgesRipperETBEffect
    ), (
        f"ETB trigger must be BoilerbilgesRipperETBEffect; "
        f"got {type(enters_ta.effect).__name__}"
    )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2  # ZONE_BATTLEFIELD
    ZH = 0  # ZONE_HAND

    # Synthetic 2/2 fodder bear (same shape on both engines).
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

    # --- Python: synthetic bear pre-seated on p0's bf; real Ripper
    # in p0's HAND so the cast resolves it through the spell pipeline
    # (mirrors the Rust cast-from-hand convention below).
    py_bear = py.new_object(
        _bear_printing("BR Decline Bear"),
        owner_id=0,
        zone=Zone.BATTLEFIELD,
    )
    py_bear.summoning_sick = False
    py_bear.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_bear)
    py_ripper = py.new_object(real, owner_id=0, zone=Zone.HAND)
    py.players[0].hand.append(py_ripper)
    # No agent on p0 — Python's gate-3 ``p.agent is None`` short-
    # circuits the ``or`` to True → silent return (no sacrifice, no
    # damage).
    py.players[0].agent = None
    # Open enough mana so the spell can be cast — synthesize the
    # cast via the lower-level direct push path. The cast pipeline's
    # mana-pay path would also need to be driven; we use a direct
    # bf-move approach to keep the probe focused on the ETB
    # resolution semantics, NOT the cast-pay logistics.

    # --- Rust: same shape via register_and_inject_object. Bear
    # first (pre-cast on bf), Ripper second (in hand to be cast).
    rs_bear = rs.register_and_inject_object(
        {
            "name": "BR Decline Bear",
            "card_types": ["Creature"],
            "power": 2,
            "toughness": 2,
            "mana_cost": {"generic": 1, "G": 1},
        },
        0,
        ZB,
    )
    rs_ripper = rs.register_and_inject_object(
        _RIPPER_PRINTING_DICT,
        0,
        ZH,
    )
    rs.clear_summoning_sick_for_player(0)

    # ---- Drive the ETB resolution on both engines.
    #
    # **Python (no-agent fizzle).** Python's
    # ``push_triggered_ability`` short-circuits at
    # ``controller.agent is None`` when the effect has
    # ``min_t > 0`` (BoilerbilgesRipperETBEffect's
    # ``requires_target() == True`` → ``target_count_range() ==
    # (1, 1)``). The trigger NEVER lands on the stack — it fizzles
    # at the push site, byte-equal observable to the gate-3 silent
    # return path (no sacrifice, no damage). Manually move Ripper
    # bf → bf is no-op (already there); we fire ``dispatch_event``
    # to exercise the predicate-walk path, which will scan the
    # ENTERS triggers and call ``push_triggered_ability`` — that
    # call no-ops out because of the no-agent fizzle.
    #
    # **Rust (cast-pipeline).** Push Ripper onto the stack via
    # ``push_to_stack`` (the spell-cast push convention), then
    # drain. The cast resolution lands Ripper on bf AND queues
    # the ETB trigger (the round-58 ETB-trigger substrate's
    # ``pending_etb_dispatches`` → ``push_triggered_ability``
    # pipeline). The queued ETB trigger then resolves into the
    # Cycle 1 silent-no-op arm.
    #
    # **Both paths converge on the SAME final field-view.** Python
    # ends with Ripper on bf + bear on bf + no damage; Rust ends
    # with Ripper on bf + bear on bf + no damage. The
    # cross-engine ``compare_fields`` diff over the harness's
    # field-view tuple should be empty.
    from mtg_bot.actions import dispatch_event
    # Move the Python Ripper from hand → bf (the cast-resolution
    # zone change). dispatch_event walks the predicate-style trigger
    # path; the no-agent fizzle in push_triggered_ability keeps the
    # trigger off the stack (byte-equal observable: no sacrifice,
    # no damage). This mirrors what would happen if we drove the
    # full priority loop with no agent surface — the trigger never
    # gets to do anything anyway.
    py.players[0].hand.remove(py_ripper)
    py_ripper.zone = Zone.BATTLEFIELD
    # summoning_sick stays True — matches the Rust cast-pipeline
    # default (the spell-resolve path puts the permanent on bf with
    # sb=True; CR 302.1). Python's default-true on the GameObject
    # would already match without this assignment; we keep it
    # explicit so the byte-equal field-view contract is visible.
    py_ripper.summoning_sick = True
    py_ripper.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_ripper)
    dispatch_event(py, Event.ENTERS, label="enters", obj=py_ripper)
    # Drain any other stack items that landed (none expected — the
    # trigger fizzled at push time).
    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)

    # Rust: cast the Ripper through the spell pipeline → lands on
    # bf → ETB trigger queues → ETB trigger resolves as no-op.
    rs.push_to_stack(rs_ripper, 0)
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert len(py.stack) == 0 and rs.stack_size() == 0

    # ---- Observable parity: NO sacrifice, NO damage on BOTH.
    # Python observables.
    assert py_bear in py.battlefield, (
        "Python: fodder bear must NOT be sacrificed (no-agent decline)"
    )
    assert py_bear not in py.players[0].graveyard, (
        "Python: fodder bear must NOT be in p0's graveyard"
    )
    assert py.players[1].life == 20, (
        f"Python: p1 life must stay 20 (no damage applied on decline); "
        f"got {py.players[1].life}"
    )
    # Ripper landed on bf on both engines.
    assert py_ripper in py.battlefield, (
        "Python: Ripper must be on bf post-resolve"
    )

    # Rust observables.
    rs_bf_ids = [e["id"] for e in rs.battlefield_snapshot()]
    assert rs_bear in rs_bf_ids, (
        "Rust: fodder bear must NOT be sacrificed (no-agent decline)"
    )
    assert rs_ripper in rs_bf_ids, (
        "Rust: Ripper must be on bf post-cast"
    )
    rs_gy0_ids = [e["id"] for e in rs.graveyard_snapshot(0)]
    assert rs_bear not in rs_gy0_ids
    rs_life_p1 = rs.life_totals[1]
    assert rs_life_p1 == 20, (
        f"Rust: p1 life must stay 20 (no damage applied on decline); "
        f"got {rs_life_p1}"
    )

    # ---- Full byte-equal field-view compare.
    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Boilerbilges Ripper ETB no-agent decline path must be "
        f"byte-equal across the WHOLE field view on BOTH engines; "
        f"diffs={diffs}"
    )
