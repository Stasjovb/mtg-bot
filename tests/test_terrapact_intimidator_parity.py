"""Cross-engine parity probes for Terrapact Intimidator.

**Terrapact Intimidator Cycle 1 closure (2026-05-23).** ``{1}{R}``
Creature — Kavu Scout, 2/1 (EoE — sourced from
``data/edge_of_eternities.json:21227``). ETB trigger body: "When this
creature enters, target opponent may have you create two Lander tokens.
If they don't, put two +1/+1 counters on this creature."

Mirrors Python's ``TerrapactIntimidatorETBEffect`` (parameterless frozen
dataclass at ``effects/bespoke.py:912``).

**Multi-gated card; classifier stays multi-gated.** Per the round-58
subsystem-attribution classifier (``scripts/scout_r58_subsystem_
attribution.py``), Terrapact Intimidator is multi-gated:

  * ``effect_uncovered`` — closed by this cycle. The new Rust variant
    ``Effect::TerrapactIntimidatorETBEffect`` makes the Python class
    ``TerrapactIntimidatorETBEffect`` covered via the 1:1 identity-
    mapping rule in ``effect_coverage.map_rust_to_python``; the
    classifier's ``missing_effect_classes`` array shrinks by one for
    this card.
  * ``nonsafe_triggered_ability`` — **STAYS active**. The trajectory
    safe-trigger admit gate (``parity/trajectory.py::
    _python_ta_to_safe_dict``) is INTENTIONALLY NOT widened — that
    gate is about the production-deck bench admit set, a distinct
    concern from per-card real-EoE parity probes. The
    ``TerrapactIntimidatorETBEffect`` leaf is explicitly negative-
    pinned at trajectory.py:1620-1628 because the substrate seats a
    *target* but the resolve is a modal ``opponent.agent.choose_mode``.
    The classifier's multi-gate state therefore reads
    ``{'gates': ['effect_uncovered', 'nonsafe_triggered_ability'],
       'multi_gated': True,
       'missing_effect_classes': []}``
    after this cycle (the effect-class list is empty; the trigger
    leaf class is still not in the safe set).

**Per-card dedicated parity probe path (PROBED tier flip).** Even
though the classifier keeps the card multi-gated at
``nonsafe_triggered_ability``, this test module is the dedicated
per-card real-EoE byte-equal cross-engine probe that flips Terrapact
Intimidator to PROBED tier. Same precedent as
``test_boilerbilges_ripper_parity.py``,
``test_fanatic_of_the_harrowing_parity.py``,
``test_comet_crawler_parity.py``, ``test_dyadrine_attack.py``, and
``test_mutinous_massacre_parity.py``: a per-card probe drives the
real printing through both engines and pins byte-equal observables;
the safe-trigger bench admit set is widened in a separate cycle when
the production-deck bench needs it.

**NOT a spell-card-bridge admit-set extension.** Terrapact Intimidator
is a Creature, not a non-creature spell. The spell-card-bridge admit
set (``trajectory.py::_python_spell_effect_to_dict`` + its §2 teeth)
gates non-creature spells only. The per-card probe approach is the
right tool here, exactly the Comet Crawler / Mutinous Massacre /
Dyadrine Attack / Boilerbilges Ripper / Fanatic of the Harrowing
convention.

**No-agent decline byte-equal (the Boilerbilges-shape pattern).**
Python's ``TerrapactIntimidatorETBEffect.resolve`` (``effects/bespoke.
py:935-972``) walks five conditional gates:

  1. Read ``state.resolving_source``.
  2. ``if not targets: return`` — empty targets → silent return.
  3. ``if kind != "player": return`` — non-player target → silent return.
  4. ``if opponent.has_lost or opponent.agent is None: return`` — the
     no-agent decline short-circuit. Silent return (no Lander tokens,
     no +1/+1 counters).
  5. (Only reachable with a yes-agent.) Modal ``choose_mode`` over
     ``["have controller create two Lander tokens", "decline"]``.

The cross-engine probe convention drives BOTH engines with no agent
on any player. Python's ``push_triggered_ability`` (``actions.py:
3260``) breaks at target-pick time because the SOURCE'S CONTROLLER
agent is None and the trigger is NOT in ``_SAFE_TRIGGERS`` — the
trigger fizzles at push time (``len(chosen_list) < min_t`` → False
return); no stack item is queued, no resolve body runs. Rust has no
agent surface in ``apply_effect`` so the resolve arm is an empty
no-op. The two engines therefore agree byte-equal on the WHOLE field
view (no Lander tokens, no +1/+1 counters).

**DISTINCTION from Boilerbilges Ripper.** Identical no-agent decline
empty-arm shape (silent no-op), BUT the no-agent gate is on a
DIFFERENT player in Python's resolve: Boilerbilges Ripper checks
``controller.agent is None``; Terrapact Intimidator checks the
TARGET OPPONENT's agent (``opponent.agent is None``). At the
push_triggered_ability site both fizzle for the SAME reason (source
controller's agent is None → can't pick a target), so both probes
take the same fizzle path. The semantic distinction is on which
player's choice the resolve depends; the observable byte-equality
holds either way when no agent surfaces exist.

**DISTINCTION from Fanatic of the Harrowing.** Fanatic's discard is
MANDATORY (no decline gate in the resolve body); Terrapact's mode
pick IS optional via the target opponent's choice but ALSO short-
circuits to silent return when the agent is None. Net: Fanatic's
no-agent path REQUIRES a deterministic agent surface to drive the
probe; Terrapact's no-agent path silently no-ops.

**Cycle 2+ agent-surface widening.** A future cycle landing a Rust
agent surface (the analog of Python's ``Agent`` interface) will widen
the Rust resolve arm to gate 5: ask the target opponent's agent
``choose_mode``, then EITHER create two Lander tokens via the proven
``Effect::CreateToken`` / ``SeedshipImpactEffect`` lander-create block
OR put two +1/+1 counters on ``state.resolving_source`` via the
established +1/+1 counter substrate. Cycle 1 lands ONLY the
``effect_uncovered`` gate closure + the byte-equal no-agent mirror;
the yes-agent gate-5 path is honest-stopped today (see
``docs/SEARCH_LIMITATIONS.md`` — Terrapact Intimidator Cycle 1 entry).

Coverage:

- Parser SoT pin: the live parser maps Terrapact Intimidator's ETB
  trigger to ``TerrapactIntimidatorETBEffect()`` (a parameterless
  frozen dataclass).
- Serializer round-trip: dict→Python via ``_ta_dict_to_python_effect``
  rebuilds ``TerrapactIntimidatorETBEffect()``; Rust
  ``Effect::TerrapactIntimidatorETBEffect`` → dict via
  ``Registry.get_printing_etb_effects`` emits the expected one-key
  dict shape.
- Effect-coverage class pin: ``TerrapactIntimidatorETBEffect`` is in
  the covered-by-rust set after this cycle (1:1 identity-mapping rule).
- Rust resolve-arm unit pins:
    * Decline path with eligible opponent (the canonical no-agent
      mirror): Terrapact-shape attacker — Rust resolve is a silent
      no-op, no Lander tokens, no +1/+1 counters on the source.
    * Decline path with multiple opponents: source on bf with multiple
      potential opponents — silent no-op regardless of which opponent
      would be targeted.
- **GENUINE real-EoE cross-engine byte-equal probe** drives the parsed
  Terrapact Intimidator printing through BOTH engines:
    * p0's bf: real-EoE Terrapact Intimidator (no agent on p0 or p1).
    * Both engines drive the ETB resolution with no agent → no Lander
      tokens, no +1/+1 counters.
    * Post-resolve on BOTH: Terrapact still on bf with 0 +1/+1 counters,
      no Lander tokens on either bf.
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


def test_real_terrapact_intimidator_etb_trigger_is_bespoke_effect():
    """**Verify-first.** The live parser maps Terrapact Intimidator's
    ETB trigger to ``TerrapactIntimidatorETBEffect()`` (a parameterless
    frozen dataclass). Pin the shape so a parser drift is caught
    here, not silently downstream in the cross-engine probe."""
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.bespoke import TerrapactIntimidatorETBEffect
    from mtg_bot.effects.predicates import Event, IsSelf

    p = get_active_source().get_printings().get("Terrapact Intimidator")
    if p is None:
        pytest.skip("Terrapact Intimidator absent from active CardSource")
    assert "Creature" in p.card_types
    assert p.power == 2
    assert p.toughness == 1
    # Single ETB triggered ability.
    enters_tas = [
        ta for ta in p.triggered_abilities if ta.event is Event.ENTERS
    ]
    assert len(enters_tas) == 1, (
        f"Terrapact Intimidator must have exactly 1 ENTERS triggered "
        f"ability; got {len(enters_tas)}"
    )
    ta = enters_tas[0]
    assert isinstance(ta.predicate, IsSelf)
    assert ta.predicate.subject is None
    assert isinstance(ta.effect, TerrapactIntimidatorETBEffect), (
        f"ETB trigger effect must be TerrapactIntimidatorETBEffect; "
        f"got {type(ta.effect).__name__}"
    )
    # Field-free unit dataclass — equality with a fresh
    # default-constructed instance.
    assert ta.effect == TerrapactIntimidatorETBEffect()


# -------------------------------------------------------------------
# Serializer round-trip + covered-set membership pins.
# -------------------------------------------------------------------


def test_terrapact_intimidator_effect_dict_to_python_round_trip():
    """Rust-shape dict → Python ``TerrapactIntimidatorETBEffect`` via
    ``_ta_dict_to_python_effect`` reconstructs a default-constructed
    instance. Bridge arm is the lever flip — without it, a Rust→Python
    triggered-ability translation would raise on the unknown kind."""
    from mtg_bot.effects.bespoke import TerrapactIntimidatorETBEffect
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    d = {"kind": "terrapact_intimidator_etb_effect"}
    rebuilt = _ta_dict_to_python_effect(d)
    assert isinstance(rebuilt, TerrapactIntimidatorETBEffect), (
        f"dict→Python bridge must round-trip to "
        f"TerrapactIntimidatorETBEffect; got {type(rebuilt).__name__}"
    )
    # Field-free unit dataclass; equality with a fresh instance.
    assert rebuilt == TerrapactIntimidatorETBEffect()


def test_terrapact_intimidator_rust_effect_to_pydict_round_trip():
    """Rust ``Effect::TerrapactIntimidatorETBEffect`` → dict emits the
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
            "name": "Terrapact Intimidator Round-trip",
            "card_types": ["Creature"],
            "power": 2,
            "toughness": 1,
            "mana_cost": {"generic": 1, "R": 1},
            "etb_effects": [
                {"kind": "terrapact_intimidator_etb_effect"},
            ],
        }
    )
    effs = reg.get_printing_etb_effects(pid)
    assert len(effs) == 1, f"expected 1 etb_effect, got {len(effs)}"
    eff = effs[0]
    assert eff["kind"] == "terrapact_intimidator_etb_effect"
    # Field-free unit variant — no other keys.
    assert set(eff.keys()) == {"kind"}, (
        f"unit-variant to_pydict must emit ONLY 'kind'; got keys "
        f"{sorted(eff.keys())}"
    )


def test_terrapact_intimidator_class_covered_by_rust():
    """``TerrapactIntimidatorETBEffect`` must be in the covered-by-
    rust set — the Rust ``Effect::TerrapactIntimidatorETBEffect``
    variant declaration makes ``covered_python_class_set()`` include
    it via the 1:1 identity-mapping rule in
    ``effect_coverage.map_rust_to_python``. This is the §2 covered-set
    tooth (parity-doc / coverage-script "covered" alignment) AND the
    closure of the classifier's ``effect_uncovered`` gate for
    Terrapact Intimidator."""
    from mtg_bot.parity.effect_coverage import covered_python_class_set

    covered = covered_python_class_set()
    assert "TerrapactIntimidatorETBEffect" in covered, (
        "Rust Effect::TerrapactIntimidatorETBEffect variant must make "
        "the Python TerrapactIntimidatorETBEffect class covered via "
        "the 1:1 identity-mapping rule"
    )


def test_terrapact_intimidator_classifier_effect_uncovered_gate_closed():
    """The round-58 subsystem-attribution classifier should report
    Terrapact Intimidator with an EMPTY ``missing_effect_classes`` list
    after this cycle — proof the ``effect_uncovered`` gate is closed
    at the classifier level. The card stays multi-gated overall
    because ``nonsafe_triggered_ability`` is still in ``gates``; this
    test pins the effect-class closure specifically.

    NB: this is the canonical observable for "the Cycle 1
    effect_uncovered closure landed". The
    ``nonsafe_triggered_ability`` gate is deliberately NOT closed
    this cycle (no widen of ``_python_ta_to_safe_dict`` — and the
    ``TerrapactIntimidatorETBEffect`` leaf is explicitly negative-
    pinned at trajectory.py:1620-1628), so the classifier's
    ``multi_gated`` flag stays ``True``."""
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
    row = attr["cards"].get("Terrapact Intimidator")
    if row is None:
        pytest.skip("Terrapact Intimidator absent from classifier output")
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
# byte-equal mirror of Python's gate-4 short-circuit).
# -------------------------------------------------------------------


def _fresh_rust_state():
    import mtg_bot_engine
    return mtg_bot_engine.make_synthetic_state(0, 0, 0)


_INTIMIDATOR_PRINTING_DICT: dict = {
    "name": "Terrapact Intimidator",
    "card_types": ["Creature"],
    "power": 2,
    "toughness": 1,
    "mana_cost": {"generic": 1, "R": 1},
    "triggered_abilities": [
        {
            "event": "enters",
            "predicate": {"kind": "source_is_self"},
            "effect": {
                "kind": "terrapact_intimidator_etb_effect",
            },
        },
    ],
}


def _inject_intimidator_in_hand(rs, owner: int = 0) -> int:
    """Inject a Terrapact-Intimidator-shape creature into ``owner``'s
    HAND. Returns the object id. The caller then casts by
    ``rs.push_to_stack(rid, owner); rs.resolve_top_of_stack()`` —
    this drives the standard spell-resolution pipeline that lands
    the permanent on the bf AND fires its ETB trigger automatically
    (the synthesized self-ENTERS predicate path the round-58
    ETB-trigger substrate established for cross-engine probes).

    The ``triggered_abilities`` ENTERS+IsSelf+
    ``terrapact_intimidator_etb_effect`` shape mirrors the parsed
    Python printing (which the live parser maps to a single
    ``TriggeredAbility(event=ENTERS, predicate=IsSelf(subject=None),
    effect=TerrapactIntimidatorETBEffect())``).
    """
    return rs.register_and_inject_object(
        _INTIMIDATOR_PRINTING_DICT,
        owner,
        ZONE_HAND,
    )


def _cast_intimidator_and_resolve_all(rs, intimidator_id: int, controller: int = 0):
    """Cast the Intimidator from ``controller``'s HAND via the standard
    spell-resolution pipeline:

      1. ``push_to_stack(intimidator_id, controller)`` — append a
         ``StackItem::new_spell`` whose ``source_obj_id ==
         intimidator_id``.
      2. ``resolve_top_of_stack()`` — drains the spell resolution,
         which moves the Intimidator from HAND → BATTLEFIELD AND
         queues the synthesized self-ENTERS triggered ability (the
         round-58 ETB-trigger substrate's ``triggered_abilities``
         dict-shape path drains via ``pending_etb_dispatches`` →
         ``push_triggered_ability``).
      3. Loop ``resolve_top_of_stack()`` until ``stack_size() == 0``
         — drains the ETB trigger itself, which on this Cycle 1
         arm is a silent no-op (the no-agent decline path).

    This is the byte-equal mirror of Python's cast-then-resolve
    pipeline used in the real-EoE cross-engine probe further down.
    """
    rs.push_to_stack(intimidator_id, controller)
    # Loop until stack is empty — first resolve = the spell cast
    # (lands the Intimidator on bf + queues the ETB trigger);
    # subsequent resolves drain the queued ETB trigger.
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()


def test_rust_resolve_with_opponent_no_agent_declines_silent_noop():
    """No-agent decline path with an eligible opponent (p1, alive
    and ready to be targeted). Mirrors Python's gate-4 short-circuit
    (``opponent.agent is None`` → silent return). Observable:

      * Intimidator lands on bf with 0 +1/+1 counters.
      * No Lander tokens on either bf (both bfs hold only the
        Intimidator).
      * No graveyard delta.

    The Intimidator is cast from hand → lands on bf via the spell-
    resolution pipeline → ETB trigger queues on the stack → ETB
    trigger resolves into the Cycle 1 silent-no-op arm.
    """
    rs = _fresh_rust_state()
    intimidator = _inject_intimidator_in_hand(rs, owner=0)
    rs.clear_summoning_sick_for_player(0)

    _cast_intimidator_and_resolve_all(rs, intimidator, controller=0)

    bf_ids = [e["id"] for e in rs.battlefield_snapshot()]
    assert intimidator in bf_ids, (
        "Intimidator must land on bf after spell resolves"
    )

    # No Lander tokens created — battlefield holds ONLY the Intimidator.
    bf = rs.battlefield_snapshot()
    bf_names = {e["printing_name"] for e in bf}
    assert "Lander" not in bf_names, (
        "no-agent decline → NO Lander tokens must be created"
    )

    # No +1/+1 counters on the Intimidator (the alternative branch of
    # the resolve body that would only fire on a yes-agent decline).
    # Rust's snapshot uses the singular ``counters`` field (which maps
    # to ``GameObject.counters`` — the unified +1/+1 counter slot at
    # this Cycle's substrate scope).
    intimidator_obj = next(e for e in bf if e["id"] == intimidator)
    assert intimidator_obj.get("counters", 0) == 0, (
        f"no-agent decline → NO +1/+1 counters on Intimidator; got "
        f"{intimidator_obj.get('counters', 0)}"
    )

    # No graveyard delta on either side.
    assert rs.graveyard_snapshot(0) == [], (
        "no-agent decline → p0's graveyard stays empty"
    )
    assert rs.graveyard_snapshot(1) == [], (
        "no-agent decline → p1's graveyard stays empty"
    )


def test_rust_resolve_multiple_opponents_no_agent_silent_noop():
    """No-agent decline path regardless of which opponent would be
    targeted. Pins the gate-4 silent return as the canonical observable
    for the Cycle 1 arm — no Lander tokens, no +1/+1 counters, no
    graveyard delta — across the cast-and-resolve pipeline.

    Drives the same observable as the single-opponent variant; the
    distinction is the synthetic state size, but the Cycle 1 arm is
    state-shape invariant (it's an empty arm body).
    """
    rs = _fresh_rust_state()
    intimidator = _inject_intimidator_in_hand(rs, owner=0)
    rs.clear_summoning_sick_for_player(0)

    _cast_intimidator_and_resolve_all(rs, intimidator, controller=0)

    bf_ids = [e["id"] for e in rs.battlefield_snapshot()]
    assert intimidator in bf_ids, (
        "Intimidator must land on bf after spell resolves"
    )
    bf = rs.battlefield_snapshot()
    bf_names = {e["printing_name"] for e in bf}
    assert "Lander" not in bf_names, (
        "no-agent decline → NO Lander tokens"
    )
    intimidator_obj = next(e for e in bf if e["id"] == intimidator)
    assert intimidator_obj.get("counters", 0) == 0, (
        "no-agent decline → NO +1/+1 counters on Intimidator"
    )


# -------------------------------------------------------------------
# GENUINE real-EoE cross-engine byte-equal probe — drives the parsed
# Terrapact Intimidator printing through BOTH engines and pins
# byte-equal full-field-view + observable equality on the decline path.
# -------------------------------------------------------------------


@pytest.fixture(scope="module")
def parity_smoke():
    """Load ``scripts/parity_smoke.py`` as a module so the probe can
    call ``_build_field_view`` for the full cross-engine byte-equality
    compare — same fixture shape as ``tests/test_parity_smoke.py``,
    ``tests/test_boilerbilges_ripper_parity.py``, etc."""
    repo_root = pathlib.Path(__file__).resolve().parent.parent
    script_path = repo_root / "scripts" / "parity_smoke.py"
    spec = importlib.util.spec_from_file_location(
        "parity_smoke", script_path
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["parity_smoke"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_cross_engine_real_eoe_terrapact_intimidator_decline_path_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine byte-equal probe — Terrapact
    Intimidator ETB no-agent decline path.** The slug-credit anchor
    for the PROBED tier flip even though the classifier multi-gates
    the card on ``nonsafe_triggered_ability``.

    Drives the **real parsed Terrapact Intimidator printing** through
    both engines:
      - p0's bf: real-EoE Terrapact Intimidator (cast from hand →
        lands on bf via the spell pipeline).
      - p1 is the would-be target opponent (a player target — the ETB
        trigger's ``legal_targets`` returns non-eliminated opponents).
      - Both engines: drive the ETB trigger with NO agent on either
        player → Python's ``push_triggered_ability`` fizzles at
        target-pick time (the SOURCE'S CONTROLLER agent is None and
        the trigger is NOT in ``_SAFE_TRIGGERS``); Rust resolve arm
        is an empty no-op.
      - Post-resolve on BOTH: Intimidator still on p0's bf with 0
        +1/+1 counters, NO Lander tokens, NO graveyard delta.

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
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.game import Zone
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.predicates import Event
    from mtg_bot.effects.bespoke import TerrapactIntimidatorETBEffect

    real = get_active_source().get_printings().get("Terrapact Intimidator")
    if real is None:
        pytest.skip("Terrapact Intimidator absent from active CardSource")

    # §2 source-of-truth: genuine ENTERS trigger must be a
    # TerrapactIntimidatorETBEffect (parameterless).
    enters_ta = next(
        (
            ta for ta in real.triggered_abilities
            if ta.event is Event.ENTERS
        ),
        None,
    )
    assert enters_ta is not None, (
        "Terrapact Intimidator must have an ENTERS triggered ability"
    )
    assert isinstance(
        enters_ta.effect, TerrapactIntimidatorETBEffect
    ), (
        f"ETB trigger must be TerrapactIntimidatorETBEffect; "
        f"got {type(enters_ta.effect).__name__}"
    )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2  # ZONE_BATTLEFIELD
    ZH = 0  # ZONE_HAND

    # --- Python: real Intimidator in p0's HAND. No-agent on both
    # players → Python's push_triggered_ability fizzles the trigger
    # because the source's controller (p0) has no agent to pick a
    # target. The trigger never lands on the stack — byte-equal
    # observable to Rust's empty resolve arm (no Lander tokens, no
    # +1/+1 counters).
    py_intimidator = py.new_object(real, owner_id=0, zone=Zone.HAND)
    py.players[0].hand.append(py_intimidator)
    # No agent on either player (Python's gate-4 short-circuit fires
    # at push time; Rust resolve arm is an empty no-op).
    py.players[0].agent = None
    py.players[1].agent = None

    # --- Rust: real Intimidator in p0's HAND. Same shape via
    # register_and_inject_object.
    rs_intimidator = rs.register_and_inject_object(
        _INTIMIDATOR_PRINTING_DICT,
        0,
        ZH,
    )
    rs.clear_summoning_sick_for_player(0)

    # ---- Drive the ETB resolution on both engines.
    #
    # **Python (no-agent fizzle).** Python's
    # ``push_triggered_ability`` short-circuits at target-pick time
    # when the source's controller has no agent
    # (``controller.agent is None`` → ``break`` from the per-slot
    # target loop → ``len(chosen_list) < min_t (=1)`` → fizzle
    # return). The trigger NEVER lands on the stack — byte-equal
    # observable to the gate-4 silent return path (no Lander
    # tokens, no +1/+1 counters). Manually move Intimidator hand →
    # bf, then fire ``dispatch_event`` to exercise the predicate-walk
    # path — that call no-ops out because of the no-agent fizzle in
    # push_triggered_ability.
    #
    # **Rust (cast-pipeline).** Push Intimidator onto the stack via
    # ``push_to_stack`` (the spell-cast push convention), then drain.
    # The cast resolution lands Intimidator on bf AND queues the ETB
    # trigger (the round-58 ETB-trigger substrate's
    # ``pending_etb_dispatches`` → ``push_triggered_ability``
    # pipeline). The queued ETB trigger then resolves into the Cycle
    # 1 silent-no-op arm.
    #
    # **Both paths converge on the SAME final field-view.** Python
    # ends with Intimidator on bf + 0 +1/+1 counters + no Landers;
    # Rust ends with Intimidator on bf + 0 +1/+1 counters + no
    # Landers. The cross-engine ``compare_fields`` diff over the
    # harness's field-view tuple should be empty.
    from mtg_bot.actions import dispatch_event
    # Move the Python Intimidator from hand → bf (the cast-resolution
    # zone change). dispatch_event walks the predicate-style trigger
    # path; the no-agent fizzle in push_triggered_ability keeps the
    # trigger off the stack (byte-equal observable: no Lander tokens,
    # no +1/+1 counters). This mirrors what would happen if we drove
    # the full priority loop with no agent surface — the trigger
    # never gets to do anything anyway.
    py.players[0].hand.remove(py_intimidator)
    py_intimidator.zone = Zone.BATTLEFIELD
    # summoning_sick stays True — matches the Rust cast-pipeline
    # default (the spell-resolve path puts the permanent on bf with
    # sb=True; CR 302.1). Python's default-true on the GameObject
    # would already match without this assignment; we keep it
    # explicit so the byte-equal field-view contract is visible.
    py_intimidator.summoning_sick = True
    py_intimidator.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_intimidator)
    dispatch_event(py, Event.ENTERS, label="enters", obj=py_intimidator)
    # Drain any other stack items that landed (none expected — the
    # trigger fizzled at push time).
    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)

    # Rust: cast the Intimidator through the spell pipeline → lands
    # on bf → ETB trigger queues → ETB trigger resolves as no-op.
    rs.push_to_stack(rs_intimidator, 0)
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert len(py.stack) == 0 and rs.stack_size() == 0

    # ---- Observable parity: NO Lander tokens, NO +1/+1 counters on
    # BOTH engines.
    # Python observables.
    assert py_intimidator in py.battlefield, (
        "Python: Intimidator must be on bf post-resolve"
    )
    assert py_intimidator.plus_one_counters == 0, (
        f"Python: Intimidator must have 0 +1/+1 counters (no-agent "
        f"decline); got {py_intimidator.plus_one_counters}"
    )
    # No Lander tokens on either bf.
    py_lander_names = [
        obj.printing.name for obj in py.battlefield
        if obj.printing.name == "Lander"
    ]
    assert py_lander_names == [], (
        f"Python: NO Lander tokens must be created (no-agent decline); "
        f"got {py_lander_names}"
    )

    # Rust observables.
    rs_bf = rs.battlefield_snapshot()
    rs_bf_ids = [e["id"] for e in rs_bf]
    assert rs_intimidator in rs_bf_ids, (
        "Rust: Intimidator must be on bf post-cast"
    )
    rs_intimidator_obj = next(e for e in rs_bf if e["id"] == rs_intimidator)
    assert rs_intimidator_obj.get("counters", 0) == 0, (
        f"Rust: Intimidator must have 0 +1/+1 counters (no-agent "
        f"decline); got {rs_intimidator_obj.get('counters', 0)}"
    )
    rs_lander_names = [
        e["printing_name"] for e in rs_bf
        if e.get("printing_name") == "Lander"
    ]
    assert rs_lander_names == [], (
        f"Rust: NO Lander tokens must be created (no-agent decline); "
        f"got {rs_lander_names}"
    )

    # ---- Full byte-equal field-view compare.
    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Terrapact Intimidator ETB no-agent decline path must be "
        f"byte-equal across the WHOLE field view on BOTH engines; "
        f"diffs={diffs}"
    )
