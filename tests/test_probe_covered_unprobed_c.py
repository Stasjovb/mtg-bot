"""Genuine real-EoE cross-engine byte-equality probes — batch C.

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
    the production bridge round-trips — the established
    Embrace-Oblivion / Decode-Transmissions / Mental-Modulation
    cross-engine driving pattern: the full Instant/Sorcery is NOT
    loader-admitted, there is no Instant/Sorcery bench path);
  * asserts **full ``compare_fields(...) == []``** — byte-equality
    across the WHOLE cross-engine field view, the strongest
    Effect+bridge-level evidence — after a real EoE deck context
    (the carrier resolved end-to-end on both engines, the trigger /
    spell fired, the stack drained), made possible campaign-wide by
    the round-r70 ``_zone_signature`` ``_net_counters`` counters-
    blindness fix.

This is the same canonical idiom the established genuine real-EoE
probes use (Embrace Oblivion / Decode Transmissions / Susurian
Voidborn in ``test_probe_covered_unprobed_a.py``; Depressurize /
Seedship Impact in ``test_parity_smoke.py``): real parsed
``spell_effect`` / ``triggered_abilities`` on Python, a bridged
synthetic carrier on Rust, ``compare_fields == []`` on a controlled
real-EoE state.

> CAVEAT (mirrors ``docs/POOL_PARITY.md``): this is Effect+bridge-
> level byte-equality on a *controlled* cross-engine state, NOT
> full-game-trajectory parity. PROBED is the strongest evidence tier
> the campaign tracks; it is not a full random multi-turn game.

PARTITION DISCIPLINE (batch C — the NEXT deck-count band below A/B)
------------------------------------------------------------------
Sibling agents own the disjoint batch A (odd-ranked top band,
``tests/test_probe_covered_unprobed_a.py``) + batch B (even-ranked top
band, ``tests/test_probe_covered_unprobed_b.py``) + the
spell-card-bridge sweep (Radiant Strike / Depressurize,
``tests/test_probe_spell_card_bridge_admitted.py``); a Rust agent owns
Seedship Impact / Orbital Plunge. This module owns **batch C = the
NEXT deck-count band**: the highest-deck cleanly-probe-constructible
covered-but-unprobed cards NOT in any sibling/Rust set. The
covered-by-construction-but-unprobed list (computed read-only via
``scripts/measure_pool_parity.classify_pool`` +
``scripts/scout_r58_subsystem_attribution._deck_counts``, sorted by
17lands deck count desc) was verify-first-recomputed at live HEAD
``4f952186``; every card below is (a) covered-by-construction,
(b) NOT individually probed, (c) NOT in batch A / batch B / the
spell-card-bridge module / the Rust-owned pair.

The 7 cards pinned here (deck counts at the verify-first walk):

  | rank | card               | decks  | shape                          |
  |-----:|--------------------|-------:|--------------------------------|
  |    8 | Gravkill           | 28,373 | Instant ExileTargetCreature    |
  |   16 | Plasma Bolt        | 21,617 | Sorcery CondVoid→DealDmgAny(2) |
  |   18 | Bombard            | 20,554 | Instant DealDamageToTgtCrea(4) |
  |   24 | Starfighter Pilot  | 17,058 | becomes_tapped → Surveil(1)    |
  |   28 | Desculpting Blast  | 14,787 | Instant ReturnTgtCreatureHand  |
  |   32 | Tragic Trajectory  | 13,705 | Sorcery CondVoid→Pump(-2/-2)   |
  |   38 | Vote Out           | 12,495 | Sorcery DestroyTargetCreature  |

DROPPED ON VERIFY (honest verify-first discipline):

  * **Weftblade Enhancer** (rank 29, ~14,406) — ETB IsSelf →
    ``PutPlusOneCounterOnEachOfUpToNTargetCreatures(max_n=2)``. The
    ``put_plus_one_counter_on_each_of_up_to_n_target_creatures``
    bridge arm's OWN docstring (``cross_engine.py``:3903-3919)
    explicitly defers the cross-engine end-to-end probe: Rust's
    resolve picks the first ``max_n`` creatures (controller-bf-first
    then opponent) at apply time while Python is target-driven via a
    Decision pipeline asking the agent for up to ``max_n`` targets —
    a faithful byte-equal probe needs a NEW multi-target picker shim
    mirroring Rust's exact iterator order, which the harness does not
    provide ("the cross-engine probe lands when a multi-target shim
    slice ships"). Driving the genuine printing against a bare-arm
    synthetic without that shim would not be a genuine byte-equal
    probe. Dropped per the round-17/18/19 synthetic-only-when-the-
    harness-lacks-the-idiom precedent; replaced by the next clean
    pick, Tragic Trajectory (rank 32, 13,705 decks — bare
    ``PumpTargetCreatureUntilEOT``, no rider cascade).

Each of the 7 picks asserts **full ``compare_fields == []``** over
the whole cross-engine field view (the strongest tier). The
Desculpting Blast probe documents the genuine printing's
``allow_nonland_permanent=True`` + ``create_drone_if_was_attacking=
True`` riders as observationally INERT for the chosen scenario (a
plain non-attacking creature: ``allow_nonland_permanent`` only widens
the legal-target filter — a creature is still legal — and the drone
rider snapshots ``obj.attacking`` which is False, so NO drone is
created and the genuine resolve path IS the bare ``return_to_hand``
Rust arm) — a true byte-equal mirror, not a rider-suppressing stub.

NEW DEDICATED MODULE (not added to ``tests/test_trajectory_parity.py``
nor the batch_a / batch_b / spell_card_bridge_admitted modules nor the
6 ``test_audit_safe_trigger_*`` tests — those are owned/protected;
this module avoids all collision and touches no STALENESS-SENTINEL).
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


# ---------------------------------------------------------------------
# Batch-C probe #1 — Gravkill (~28,373 17lands decks; rank 8).
#
# Verified covered (``ExileTargetCreature`` ∈ covered set) + unprobed
# at HEAD 4f952186. Oracle (``data/edge_of_eternities.json``):
#   "[Instant] {2}{B} — Exile target creature."
# Parser → ``spell_effect = ExileTargetCreature(targets=(TargetSpec(
# IsCreature()),))``. The covered Effect class is ``ExileTargetCreature``
# (subclass of ``Exile``); the Rust ``exile_target`` bridge arm (the
# sibling closure of ``destroy_target`` — same defender-swap first-slice
# picker substrate) is exact. This probe drives the genuine printing's
# creature-target leg, the byte-equal overlap the covered tier claims.
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_gravkill_exile_target_creature_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Gravkill (~28,373
    17lands decks). Batch-C covered→PROBED.**

    Python: the ACTUAL parsed Gravkill printing on a ``StackItem``
    with the chosen creature target. Rust: the bridged
    ``{"kind":"exile_target","target":{"kind":"any_creature"}}``
    synthetic Instant (the established Embrace-Oblivion cross-engine
    driving pattern — the full Instant is NOT loader-admitted).

    Assertion strength: **full ``compare_fields``** over the whole
    cross-engine field view. The exiled 2/2 leaves the battlefield to
    EXILE (not graveyard) on BOTH engines byte-equal — distinct from
    the destroy-to-graveyard sibling probes.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.game import StackItem, Zone
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.generic.exile import ExileTargetCreature
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from tests.parity._picker_shims import _PickFirstOpponentTargetAgent

    real = get_active_source().get_printings().get("Gravkill")
    if real is None:
        pytest.skip("Gravkill absent from active CardSource")
    assert "Instant" in real.card_types
    se = real.spell_effect
    assert isinstance(se, ExileTargetCreature), (
        f"genuine Gravkill spell_effect must be ExileTargetCreature; "
        f"got {type(se).__name__}"
    )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2

    # p1 (opponent) has a single vanilla 2/2 creature — the legal
    # target on BOTH engines.
    py_vic = py.new_object(
        CardPrinting(
            name="GK Victim", mana_cost_str="",
            mana_cost=ManaCost(generic=0), type_line="Creature",
            supertypes=(), card_types=("Creature",), subtypes=(),
            power=2, toughness=2, produces=frozenset(),
        ),
        owner_id=1, zone=Zone.BATTLEFIELD,
    )
    py_vic.summoning_sick = False
    py.battlefield.append(py_vic)
    py.players[0].agent = _PickFirstOpponentTargetAgent()

    rs_vic_id = rs.register_and_inject_object(
        {"name": "GK Victim", "card_types": ["Creature"],
         "power": 2, "toughness": 2}, 1, ZB,
    )

    # ---- Python: genuine parsed Gravkill on a StackItem, controller
    # p0, chosen target = p1's creature. ----
    py_spell = py.new_object(real, owner_id=0, zone=Zone.STACK)
    py_spell.summoning_sick = False
    py.stack.append(
        StackItem(source=py_spell, controller_id=0,
                  targets=(("creature", py_vic.id),))
    )
    resolve_top_of_stack(py)
    py_sba(py)
    assert len(py.stack) == 0

    # ---- Rust: bridged synthetic Instant carrying the covered
    # exile_target arm (AnyCreature first-slice picker → p1 bf[0]). ----
    rs_spell_id = rs.register_and_inject_object(
        {"name": "Gravkill", "card_types": ["Instant"],
         "effects": [{"kind": "exile_target",
                      "target": {"kind": "any_creature"}}]},
        0, 0,  # controller p0, ZONE_HAND
    )
    rs.push_to_stack(rs_spell_id, 0)
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0

    rs_alive = any(e["id"] == rs_vic_id
                   for e in rs.battlefield_snapshot())
    py_alive = any(o.id == py_vic.id for o in py.battlefield)
    assert rs_alive is False and py_alive is False, (
        f"the 2/2 must be exiled off the bf on BOTH; "
        f"rust_alive={rs_alive} py_alive={py_alive}"
    )

    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Gravkill exile-target-creature must be byte-equal across the "
        f"WHOLE field view on BOTH (exiled, not in any graveyard); "
        f"diffs={diffs}"
    )


# ---------------------------------------------------------------------
# Batch-C probe #2 — Plasma Bolt (~21,617 17lands decks; rank 16).
#
# Verified covered (``ConditionalIfVoid`` / ``DealDamageAnyTarget`` ∈
# covered set) + unprobed at HEAD. Oracle:
#   "[Sorcery] {1}{R} — Plasma Bolt deals 2 damage to any target.
#    Void — Plasma Bolt deals 3 damage instead if a nonland permanent
#    left the battlefield this turn or a spell was warped this turn."
# Parser → ``spell_effect = ConditionalIfVoid(then=DealDamageAnyTarget
# (3), else=DealDamageAnyTarget(2))``. On a fresh state Void is
# INACTIVE → the ELSE branch fires (2 damage). Driven via the
# established Decode-Transmissions Void-inactive idiom + the
# deal_damage_any_target opponent-creature pick (Nebula-Dragon idiom).
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_plasma_bolt_void_inactive_deal_2_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Plasma Bolt (~21,617
    17lands decks). Batch-C covered→PROBED.**

    Python: the ACTUAL parsed Plasma Bolt printing on a ``StackItem``
    with the chosen any-target = p1's creature. Rust: the bridged
    ``conditional_if_void`` synthetic Sorcery (recursive bridge:
    then=deal_damage_any_target 3, else=deal_damage_any_target 2).
    Void is INACTIVE on the fresh state → the ELSE branch (2 damage)
    resolves on BOTH; the targeted 2/2 dies via SBA on BOTH.

    Assertion strength: **full ``compare_fields``** over the whole
    cross-engine field view (the dead creature in p1's graveyard on
    BOTH; lives untouched). Rust's deal_damage_any_target scans the
    defender's bf first-slice; Python's agent (_PickFirstOpponent…)
    picks the single p1 creature — same target on BOTH.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.game import StackItem, Zone, is_void_active
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.combinators import ConditionalIfVoid
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from tests.parity._picker_shims import _PickFirstOpponentTargetAgent

    real = get_active_source().get_printings().get("Plasma Bolt")
    if real is None:
        pytest.skip("Plasma Bolt absent from active CardSource")
    assert "Sorcery" in real.card_types
    se = real.spell_effect
    assert isinstance(se, ConditionalIfVoid), (
        f"genuine Plasma Bolt spell_effect must be ConditionalIfVoid; "
        f"got {type(se).__name__}"
    )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2

    assert is_void_active(py) is False, (
        "fresh state must have Void INACTIVE so the else-branch fires"
    )

    # p1 has a single vanilla 2/2 — 2 damage from the else-branch is
    # lethal → it dies via SBA on BOTH.
    py_vic = py.new_object(
        CardPrinting(
            name="PB Victim", mana_cost_str="",
            mana_cost=ManaCost(generic=0), type_line="Creature",
            supertypes=(), card_types=("Creature",), subtypes=(),
            power=2, toughness=2, produces=frozenset(),
        ),
        owner_id=1, zone=Zone.BATTLEFIELD,
    )
    py_vic.summoning_sick = False
    py.battlefield.append(py_vic)
    py.players[0].agent = _PickFirstOpponentTargetAgent()

    rs_vic_id = rs.register_and_inject_object(
        {"name": "PB Victim", "card_types": ["Creature"],
         "power": 2, "toughness": 2}, 1, ZB,
    )

    py_p0_life0 = py.players[0].life
    py_p1_life0 = py.players[1].life

    # ---- Python: genuine parsed Plasma Bolt on a StackItem,
    # controller p0, chosen target = p1's creature. ----
    py_spell = py.new_object(real, owner_id=0, zone=Zone.STACK)
    py_spell.summoning_sick = False
    py.stack.append(
        StackItem(source=py_spell, controller_id=0,
                  targets=(("creature", py_vic.id),))
    )
    resolve_top_of_stack(py)
    py_sba(py)
    assert len(py.stack) == 0

    # ---- Rust: bridged conditional_if_void synthetic Sorcery. ----
    rs_spell_id = rs.register_and_inject_object(
        {"name": "Plasma Bolt", "card_types": ["Sorcery"],
         "effects": [{
             "kind": "conditional_if_void",
             "then_effect": {"kind": "deal_damage_any_target",
                             "amount": 3},
             "else_effect": {"kind": "deal_damage_any_target",
                             "amount": 2},
         }]},
        0, 0,  # controller p0, ZONE_HAND
    )
    rs.push_to_stack(rs_spell_id, 0)
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0

    rs_alive = any(e["id"] == rs_vic_id
                   for e in rs.battlefield_snapshot())
    py_alive = any(o.id == py_vic.id for o in py.battlefield)
    assert rs_alive is False and py_alive is False, (
        f"the 2/2 must take 2 lethal damage (else-branch) on BOTH; "
        f"rust_alive={rs_alive} py_alive={py_alive}"
    )
    assert py.players[0].life == py_p0_life0
    assert py.players[1].life == py_p1_life0

    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Plasma Bolt Void-inactive 2-damage else-branch must be "
        f"byte-equal across the WHOLE field view on BOTH; diffs={diffs}"
    )


# ---------------------------------------------------------------------
# Batch-C probe #3 — Bombard (~20,554 17lands decks; rank 18).
#
# Verified covered (``DealDamageToTargetCreature`` ∈ covered set) +
# unprobed at HEAD. Oracle:
#   "[Instant] {1}{R} — Bombard deals 4 damage to target creature."
# Parser → ``spell_effect = DealDamageToTargetCreature(amount=4,
# targets=(TargetSpec(IsCreature()),))``. ``DealDamageToTargetCreature``
# subclasses ``DealDamage``; the Rust ``deal_damage`` bridge arm with
# ``target={"kind":"any_creature"}`` constructs the same DealDamage
# family — exact round-trip.
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_bombard_deal_4_to_target_creature_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Bombard (~20,554
    17lands decks). Batch-C covered→PROBED.**

    Python: the ACTUAL parsed Bombard printing on a ``StackItem`` with
    the chosen creature target. Rust: the bridged ``{"kind":
    "deal_damage","amount":4,"target":{"kind":"any_creature"}}``
    synthetic Instant (the deal_damage parametric-target arm; AnyCreature
    first-slice picker → p1 bf[0]).

    Assertion strength: **full ``compare_fields``** over the whole
    cross-engine field view (the 3/3 takes 4 lethal damage and dies via
    SBA → p1's graveyard on BOTH; lives untouched).
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.game import StackItem, Zone
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.generic.damage import DealDamageToTargetCreature
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from tests.parity._picker_shims import _PickFirstOpponentTargetAgent

    real = get_active_source().get_printings().get("Bombard")
    if real is None:
        pytest.skip("Bombard absent from active CardSource")
    assert "Instant" in real.card_types
    se = real.spell_effect
    assert isinstance(se, DealDamageToTargetCreature), (
        f"genuine Bombard spell_effect must be "
        f"DealDamageToTargetCreature; got {type(se).__name__}"
    )
    assert se.amount == 4

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2

    # p1 has a single vanilla 3/3 — 4 damage is lethal → dies via SBA.
    py_vic = py.new_object(
        CardPrinting(
            name="BM Victim", mana_cost_str="",
            mana_cost=ManaCost(generic=0), type_line="Creature",
            supertypes=(), card_types=("Creature",), subtypes=(),
            power=3, toughness=3, produces=frozenset(),
        ),
        owner_id=1, zone=Zone.BATTLEFIELD,
    )
    py_vic.summoning_sick = False
    py.battlefield.append(py_vic)
    py.players[0].agent = _PickFirstOpponentTargetAgent()

    rs_vic_id = rs.register_and_inject_object(
        {"name": "BM Victim", "card_types": ["Creature"],
         "power": 3, "toughness": 3}, 1, ZB,
    )

    py_p1_life0 = py.players[1].life

    # ---- Python: genuine parsed Bombard on a StackItem. ----
    py_spell = py.new_object(real, owner_id=0, zone=Zone.STACK)
    py_spell.summoning_sick = False
    py.stack.append(
        StackItem(source=py_spell, controller_id=0,
                  targets=(("creature", py_vic.id),))
    )
    resolve_top_of_stack(py)
    py_sba(py)
    assert len(py.stack) == 0

    # ---- Rust: bridged synthetic Instant. ----
    rs_spell_id = rs.register_and_inject_object(
        {"name": "Bombard", "card_types": ["Instant"],
         "effects": [{"kind": "deal_damage", "amount": 4,
                      "target": {"kind": "any_creature"}}]},
        0, 0,  # controller p0, ZONE_HAND
    )
    rs.push_to_stack(rs_spell_id, 0)
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0

    rs_alive = any(e["id"] == rs_vic_id
                   for e in rs.battlefield_snapshot())
    py_alive = any(o.id == py_vic.id for o in py.battlefield)
    assert rs_alive is False and py_alive is False, (
        f"the 3/3 must take 4 lethal damage on BOTH; "
        f"rust_alive={rs_alive} py_alive={py_alive}"
    )
    assert py.players[1].life == py_p1_life0, "p1 life untouched"

    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Bombard 4-damage-to-target-creature must be byte-equal "
        f"across the WHOLE field view on BOTH; diffs={diffs}"
    )


# ---------------------------------------------------------------------
# Batch-C probe #4 — Starfighter Pilot (~17,058 17lands decks; rank
# 24).
#
# Verified covered (``Surveil`` ∈ covered set) + unprobed at HEAD.
# Oracle:
#   "[Creature] 2/2 …
#    Whenever this creature becomes tapped, surveil 1."
# BECOMES_TAPPED leg, predicate ``IsSelf`` → ``Surveil(amount=1)``.
# Driven via the established declare_attacker (Rust) / tap_permanent
# (Python) BECOMES_TAPPED idiom (the Chrome Companion / Mechan
# Navigator pattern) + the Thawbringer surveil-1 KEEP-ALL default
# idiom (no surveil agent seated → BOTH engines keep the observed card
# on library top in place; Rust's terminal
# ``auto_resolve_pending("keep_all_on_top")`` == Python's
# ``p.agent is None`` short-circuit). Deterministic, no RNG.
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_starfighter_pilot_becomes_tapped_surveil_1_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Starfighter Pilot
    (~17,058 17lands decks). Batch-C covered→PROBED.**

    Python: the ACTUAL parsed Starfighter Pilot printing seated on
    p0's battlefield, tapped via the production ``tap_permanent``
    path; its BECOMES_TAPPED trigger (IsSelf → Surveil{1}) fires.
    Rust: the bridged synthetic carrier tapped via ``declare_attacker``
    (→ Event::BecomesTapped).

    Surveil keep-all default: NO surveil decision callback is seated,
    so BOTH engines keep the single observed library card on top in
    its original position (Rust auto_resolve keep_all_on_top; Python
    ``p.agent`` is None short-circuit) — the Thawbringer surveil-1
    parity-trivially-safe leg.

    Assertion strength: **full ``compare_fields``** over the whole
    cross-engine field view (the carrier tapped on BOTH; p0 library
    unchanged — the surveil-bait card still on top, untouched; both
    graveyards empty). The mill path (send-to-graveyard) is a separate
    surveil-agent surface, out of scope (the established Starbreach
    Whale split).
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
        build_python_field_view, compare_fields, CardDef,
        parity_smoke as ce_parity_smoke,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.game import Zone
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.turn import tap_permanent as py_tap_permanent
    from mtg_bot.effects.generic.library_lookat import Surveil

    real = get_active_source().get_printings().get("Starfighter Pilot")
    if real is None:
        pytest.skip("Starfighter Pilot absent from active CardSource")
    assert "Creature" in real.card_types
    bt = next(
        (ta for ta in real.triggered_abilities
         if getattr(ta.event, "value", ta.event) == "becomes_tapped"),
        None,
    )
    assert bt is not None, (
        "Starfighter Pilot must have a BECOMES_TAPPED trigger"
    )
    assert isinstance(bt.effect, Surveil), (
        f"genuine Starfighter Pilot BECOMES_TAPPED must be Surveil; "
        f"got {type(bt.effect).__name__}"
    )
    assert bt.effect.amount == 1

    # One distinct vanilla surveil-bait at library top on BOTH engines
    # (surveil 1 observes exactly the top one card; keep-all leaves it
    # in place — byte-equal on BOTH).
    spec = DeckSpec(
        card_defs=(CardDef(name="SP Surveil Bait", card_type="Creature",
                           power=1, toughness=1),),
        p0_library=("SP Surveil Bait",),
        p1_library=(),
    )
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2

    rp = int(real.power) if real.power is not None else 2
    rt = int(real.toughness) if real.toughness is not None else 2

    # Python: seat the GENUINE parsed printing on p0's bf.
    py_obj = py.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    py_obj.summoning_sick = False
    py_obj.tapped = False
    py_obj.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_obj)

    # Rust: bridged synthetic carrier with the faithful source_is_self
    # BECOMES_TAPPED → surveil{1} trigger.
    rs_id = rs.register_and_inject_object(
        {
            "name": "Starfighter Pilot",
            "card_types": ["Creature"],
            "power": rp, "toughness": rt,
            "effects": [],
            "triggered_abilities": [
                {
                    "event": "becomes_tapped",
                    "predicate": {"kind": "source_is_self"},
                    "effect": {"kind": "surveil", "count": 1},
                }
            ],
        },
        0, ZB,
    )

    # ETB does NOT fire BECOMES_TAPPED (CR 701.21a).
    assert rs.stack_size() == 0 and len(py.stack) == 0

    rs.clear_summoning_sick_for_player(0)
    assert rs.declare_attacker(rs_id) is True
    assert rs.stack_size() == 1, (
        "Rust: tapping Starfighter Pilot must fire BECOMES_TAPPED"
    )
    py_tap_permanent(py, py_obj)
    assert len(py.stack) == 1, (
        "Python: tapping Starfighter Pilot must fire BECOMES_TAPPED"
    )

    _drain_both(py, rs)
    py_sba(py)
    rs.apply_sbas()
    assert rs.stack_size() == 0 and len(py.stack) == 0

    # Keep-all default: the single bait card is still on p0's library
    # top, both graveyards empty, on BOTH engines.
    rs_p0_gy = [e["printing_name"] for e in rs.graveyard_snapshot(0)]
    py_p0_gy = [o.printing.name for o in py.players[0].graveyard]
    assert rs_p0_gy == [] == py_p0_gy, (
        f"surveil keep-all: p0 graveyard must be empty on BOTH; "
        f"rust={rs_p0_gy} py={py_p0_gy}"
    )
    assert rs.library_sizes[0] == len(py.players[0].library) == 1, (
        "surveil keep-all: the bait card stays in p0's library on BOTH"
    )
    rs_carrier_tapped = next(
        e["tapped"] for e in rs.battlefield_snapshot()
        if e["id"] == rs_id
    )
    assert rs_carrier_tapped is True and py_obj.tapped is True, (
        "Starfighter Pilot must be tapped on BOTH (it became tapped)"
    )

    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Starfighter Pilot BECOMES_TAPPED surveil-1 (keep-all) must "
        f"be byte-equal across the WHOLE field view on BOTH; "
        f"diffs={diffs}"
    )


# ---------------------------------------------------------------------
# Batch-C probe #5 — Desculpting Blast (~14,787 17lands decks; rank
# 28).
#
# Verified covered (``ReturnTargetCreatureToOwnersHand`` ∈ covered
# set) + unprobed at HEAD. Oracle:
#   "[Instant] {2}{U} — Return target creature or other nonland
#    permanent to its owner's hand. If it was attacking, create a
#    1/1 colorless Drone artifact creature token."
# Parser → ``spell_effect = ReturnTargetCreatureToOwnersHand(
# allow_nonland_permanent=True, create_drone_if_was_attacking=True)``.
#
# RIDER-INERT REASONING (documented, honest — NOT a rider-suppressing
# stub). For the chosen scenario (a plain NON-ATTACKING vanilla
# creature target on p1's bf):
#   * ``allow_nonland_permanent=True`` only WIDENS the legal-target
#     filter from ``IsCreature()`` to ``~IsLand() & ~IsPlayer()`` — a
#     plain creature is a legal target under BOTH filters, so the
#     genuine printing picks the same target the bare Rust
#     ``return_to_hand`` arm (``Bounce(targets=(TargetSpec(
#     IsCreature()),))``) picks.
#   * ``create_drone_if_was_attacking=True`` snapshots
#     ``obj.attacking`` BEFORE the bounce (effects/generic/bounce.py:
#     127-159). The target is NOT attacking (it is seated inert, no
#     combat declared), so the snapshot is False and the rider creates
#     NO Drone — the genuine resolve path IS the bare bounce-to-hand,
#     identical to the Rust ``return_to_hand`` arm. This is a true
#     byte-equal mirror on the chosen scenario, not a coincidental
#     match.
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_desculpting_blast_return_creature_to_hand_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Desculpting Blast
    (~14,787 17lands decks). Batch-C covered→PROBED.**

    Python: the ACTUAL parsed Desculpting Blast printing on a
    ``StackItem`` with the chosen creature target (a plain
    NON-ATTACKING 2/2 — see the module-level RIDER-INERT REASONING:
    the drone rider's ``obj.attacking`` snapshot is False so NO drone
    spawns, and ``allow_nonland_permanent`` only widens the filter
    that a creature already satisfies → the genuine resolve path is
    the bare bounce-to-hand). Rust: the bridged ``{"kind":
    "return_to_hand","target":{"kind":"any_creature"}}`` synthetic
    Instant (the I76 bounce sibling of destroy_target / exile_target).

    Assertion strength: **full ``compare_fields``** over the whole
    cross-engine field view (the 2/2 leaves p1's bf and lands in p1's
    HAND — its OWNER's hand per CR 401.1 — on BOTH engines byte-equal;
    NO Drone token on either side; both graveyards empty).
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.game import StackItem, Zone
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.generic.bounce import (
        ReturnTargetCreatureToOwnersHand,
    )
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from tests.parity._picker_shims import _PickFirstOpponentTargetAgent

    real = get_active_source().get_printings().get("Desculpting Blast")
    if real is None:
        pytest.skip("Desculpting Blast absent from active CardSource")
    assert "Instant" in real.card_types
    se = real.spell_effect
    assert isinstance(se, ReturnTargetCreatureToOwnersHand), (
        f"genuine Desculpting Blast spell_effect must be "
        f"ReturnTargetCreatureToOwnersHand; got {type(se).__name__}"
    )
    # Document the riders we reason inert for the chosen scenario.
    assert se.allow_nonland_permanent is True
    assert se.create_drone_if_was_attacking is True

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2

    # p1 (opponent) has a single vanilla 2/2 — NOT attacking (no
    # combat declared), so the drone rider never fires.
    py_vic = py.new_object(
        CardPrinting(
            name="DB Victim", mana_cost_str="",
            mana_cost=ManaCost(generic=0), type_line="Creature",
            supertypes=(), card_types=("Creature",), subtypes=(),
            power=2, toughness=2, produces=frozenset(),
        ),
        owner_id=1, zone=Zone.BATTLEFIELD,
    )
    py_vic.summoning_sick = False
    py_vic.attacking = False
    py.battlefield.append(py_vic)
    py.players[0].agent = _PickFirstOpponentTargetAgent()

    rs_vic_id = rs.register_and_inject_object(
        {"name": "DB Victim", "card_types": ["Creature"],
         "power": 2, "toughness": 2}, 1, ZB,
    )

    # ---- Python: genuine parsed Desculpting Blast on a StackItem. ----
    py_spell = py.new_object(real, owner_id=0, zone=Zone.STACK)
    py_spell.summoning_sick = False
    py.stack.append(
        StackItem(source=py_spell, controller_id=0,
                  targets=(("creature", py_vic.id),))
    )
    resolve_top_of_stack(py)
    py_sba(py)
    assert len(py.stack) == 0

    # ---- Rust: bridged synthetic Instant carrying return_to_hand. ----
    rs_spell_id = rs.register_and_inject_object(
        {"name": "Desculpting Blast", "card_types": ["Instant"],
         "effects": [{"kind": "return_to_hand",
                      "target": {"kind": "any_creature"}}]},
        0, 0,  # controller p0, ZONE_HAND
    )
    rs.push_to_stack(rs_spell_id, 0)
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0

    rs_bf_ids = [e["id"] for e in rs.battlefield_snapshot()]
    py_bf_ids = [o.id for o in py.battlefield]
    assert rs_vic_id not in rs_bf_ids and py_vic.id not in py_bf_ids, (
        "the 2/2 must be bounced off the bf on BOTH"
    )
    # It lands in its OWNER's (p1's) hand on BOTH; NO Drone token.
    assert rs.hand_sizes[1] == len(py.players[1].hand) == 1, (
        f"the bounced 2/2 must be in p1's (owner's) hand on BOTH; "
        f"rust={rs.hand_sizes[1]} py={len(py.players[1].hand)}"
    )
    rs_drones = sum(1 for e in rs.battlefield_snapshot()
                    if e["printing_name"] == "Drone")
    py_drones = sum(1 for o in py.battlefield
                    if o.printing.name == "Drone")
    assert rs_drones == 0 == py_drones, (
        f"target was NOT attacking → NO Drone on BOTH; "
        f"rust={rs_drones} py={py_drones}"
    )

    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Desculpting Blast bounce-to-owner-hand (non-attacking "
        f"target, drone rider inert) must be byte-equal across the "
        f"WHOLE field view on BOTH; diffs={diffs}"
    )


# ---------------------------------------------------------------------
# Batch-C probe #6 — Tragic Trajectory (~13,705 17lands decks; rank
# 32).
#
# Verified covered (``ConditionalIfVoid`` / ``PumpTargetCreature
# UntilEOT`` ∈ covered set) + unprobed at HEAD. Oracle:
#   "[Sorcery] {1}{B} — Target creature gets -2/-2 until end of turn.
#    Void — That creature gets -10/-10 until end of turn instead if a
#    nonland permanent left the battlefield this turn or a spell was
#    warped this turn."
# Parser → ``spell_effect = ConditionalIfVoid(then=PumpTargetCreature
# UntilEOT(-10,-10), else=PumpTargetCreatureUntilEOT(-2,-2))``. The
# genuine pump is BARE (no granted_keywords, no you_control_only, no
# exclude_source) so the bare ``pump_target_creature_until_eot`` bridge
# arm is exact. Void INACTIVE on the fresh state → the ELSE branch
# (-2/-2) fires; a 2/2 → eff toughness 0 → dies via SBA. Rust's pump
# scans the SOURCE CONTROLLER's bf first-slice; Python picks via the
# established ``_PickFirstControlledCreatureAgent`` (same-side) — so
# the target creature is seated on p0 (the caster's) bf.
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_tragic_trajectory_void_inactive_pump_minus2_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Tragic Trajectory
    (~13,705 17lands decks). Batch-C covered→PROBED.**

    Python: the ACTUAL parsed Tragic Trajectory printing on a
    ``StackItem`` with the chosen creature target (a p0-controlled 2/2
    — Rust's pump scans the source-controller's own bf, the
    ``_PickFirstControlledCreatureAgent`` mirrors that same-side
    pick). Rust: the bridged ``conditional_if_void`` synthetic Sorcery
    (then=pump_target -10/-10, else=pump_target -2/-2). Void INACTIVE
    on the fresh state → the ELSE branch (-2/-2) resolves on BOTH; the
    2/2 → effective toughness 0 → dies via SBA on BOTH.

    Assertion strength: **full ``compare_fields``** over the whole
    cross-engine field view (the pumped-to-death 2/2 in p0's graveyard
    on BOTH; lives untouched).
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.game import StackItem, Zone, is_void_active
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.combinators import ConditionalIfVoid
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from tests.parity._picker_shims import (
        _PickFirstControlledCreatureAgent,
    )

    real = get_active_source().get_printings().get("Tragic Trajectory")
    if real is None:
        pytest.skip("Tragic Trajectory absent from active CardSource")
    assert "Sorcery" in real.card_types
    se = real.spell_effect
    assert isinstance(se, ConditionalIfVoid), (
        f"genuine Tragic Trajectory spell_effect must be "
        f"ConditionalIfVoid; got {type(se).__name__}"
    )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2

    assert is_void_active(py) is False, (
        "fresh state must have Void INACTIVE so the else-branch fires"
    )

    # p0 (the caster) has a single vanilla 2/2 — Rust's pump scans the
    # SOURCE CONTROLLER's bf; the same-side picker shim mirrors that.
    # -2/-2 takes effective toughness to 0 → dies via SBA on BOTH.
    py_vic = py.new_object(
        CardPrinting(
            name="TT Victim", mana_cost_str="",
            mana_cost=ManaCost(generic=0), type_line="Creature",
            supertypes=(), card_types=("Creature",), subtypes=(),
            power=2, toughness=2, produces=frozenset(),
        ),
        owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_vic.summoning_sick = False
    py.battlefield.append(py_vic)
    py.players[0].agent = _PickFirstControlledCreatureAgent()

    rs_vic_id = rs.register_and_inject_object(
        {"name": "TT Victim", "card_types": ["Creature"],
         "power": 2, "toughness": 2}, 0, ZB,
    )

    py_p0_life0 = py.players[0].life
    py_p1_life0 = py.players[1].life

    # ---- Python: genuine parsed Tragic Trajectory on a StackItem. ----
    py_spell = py.new_object(real, owner_id=0, zone=Zone.STACK)
    py_spell.summoning_sick = False
    py.stack.append(
        StackItem(source=py_spell, controller_id=0,
                  targets=(("creature", py_vic.id),))
    )
    resolve_top_of_stack(py)
    py_sba(py)
    assert len(py.stack) == 0

    # ---- Rust: bridged conditional_if_void synthetic Sorcery. ----
    rs_spell_id = rs.register_and_inject_object(
        {"name": "Tragic Trajectory", "card_types": ["Sorcery"],
         "effects": [{
             "kind": "conditional_if_void",
             "then_effect": {"kind": "pump_target_creature_until_eot",
                             "power_bonus": -10,
                             "toughness_bonus": -10},
             "else_effect": {"kind": "pump_target_creature_until_eot",
                             "power_bonus": -2,
                             "toughness_bonus": -2},
         }]},
        0, 0,  # controller p0, ZONE_HAND
    )
    rs.push_to_stack(rs_spell_id, 0)
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0

    rs_alive = any(e["id"] == rs_vic_id
                   for e in rs.battlefield_snapshot())
    py_alive = any(o.id == py_vic.id for o in py.battlefield)
    assert rs_alive is False and py_alive is False, (
        f"the 2/2 must be pumped -2/-2 to lethal (else-branch) on "
        f"BOTH; rust_alive={rs_alive} py_alive={py_alive}"
    )
    assert py.players[0].life == py_p0_life0
    assert py.players[1].life == py_p1_life0

    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Tragic Trajectory Void-inactive -2/-2 else-branch must be "
        f"byte-equal across the WHOLE field view on BOTH; diffs={diffs}"
    )


# ---------------------------------------------------------------------
# Batch-C probe #7 — Vote Out (~12,495 17lands decks; rank 38).
#
# Verified covered (``DestroyTargetCreature`` ∈ covered set) +
# unprobed at HEAD. Oracle:
#   "[Sorcery] {2}{W} — Destroy target creature."
# Parser → ``spell_effect = DestroyTargetCreature(targets=(TargetSpec(
# IsCreature()),))`` — the BARE destroy shape (no draw_if_undamaged,
# no or_spacecraft, no exclude_self riders). The Rust ``destroy_target``
# bridge arm is exact. Distinct from the Embrace Oblivion sister
# (which carries ``or_spacecraft=True``): Vote Out is the plain
# unconditional single-target destroy.
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_vote_out_destroy_target_creature_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Vote Out (~12,495
    17lands decks). Batch-C covered→PROBED.**

    Python: the ACTUAL parsed Vote Out printing on a ``StackItem``
    with the chosen creature target. Rust: the bridged ``{"kind":
    "destroy_target","target":{"kind":"any_creature"}}`` synthetic
    Sorcery (the established Embrace-Oblivion cross-engine driving
    pattern — the full Sorcery is NOT loader-admitted).

    Assertion strength: **full ``compare_fields``** over the whole
    cross-engine field view. The destroyed 2/2 lands in p1's graveyard
    on BOTH engines byte-equal.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.game import StackItem, Zone
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.generic.destroy import DestroyTargetCreature
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from tests.parity._picker_shims import _PickFirstOpponentTargetAgent

    real = get_active_source().get_printings().get("Vote Out")
    if real is None:
        pytest.skip("Vote Out absent from active CardSource")
    assert "Sorcery" in real.card_types
    se = real.spell_effect
    assert isinstance(se, DestroyTargetCreature), (
        f"genuine Vote Out spell_effect must be DestroyTargetCreature; "
        f"got {type(se).__name__}"
    )
    # Vote Out is the BARE destroy (distinct from Embrace Oblivion's
    # or_spacecraft / Faller's Faithful's draw_if_undamaged riders).
    assert se.or_spacecraft is False
    assert se.draw_if_undamaged_amount == 0

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2

    py_vic = py.new_object(
        CardPrinting(
            name="VO Victim", mana_cost_str="",
            mana_cost=ManaCost(generic=0), type_line="Creature",
            supertypes=(), card_types=("Creature",), subtypes=(),
            power=2, toughness=2, produces=frozenset(),
        ),
        owner_id=1, zone=Zone.BATTLEFIELD,
    )
    py_vic.summoning_sick = False
    py.battlefield.append(py_vic)
    py.players[0].agent = _PickFirstOpponentTargetAgent()

    rs_vic_id = rs.register_and_inject_object(
        {"name": "VO Victim", "card_types": ["Creature"],
         "power": 2, "toughness": 2}, 1, ZB,
    )

    # ---- Python: genuine parsed Vote Out on a StackItem. ----
    py_spell = py.new_object(real, owner_id=0, zone=Zone.STACK)
    py_spell.summoning_sick = False
    py.stack.append(
        StackItem(source=py_spell, controller_id=0,
                  targets=(("creature", py_vic.id),))
    )
    resolve_top_of_stack(py)
    py_sba(py)
    assert len(py.stack) == 0

    # ---- Rust: bridged synthetic Sorcery carrying destroy_target. ----
    rs_spell_id = rs.register_and_inject_object(
        {"name": "Vote Out", "card_types": ["Sorcery"],
         "effects": [{"kind": "destroy_target",
                      "target": {"kind": "any_creature"}}]},
        0, 0,  # controller p0, ZONE_HAND
    )
    rs.push_to_stack(rs_spell_id, 0)
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0

    rs_alive = any(e["id"] == rs_vic_id
                   for e in rs.battlefield_snapshot())
    py_alive = any(o.id == py_vic.id for o in py.battlefield)
    assert rs_alive is False and py_alive is False, (
        f"the 2/2 must be destroyed on BOTH; "
        f"rust_alive={rs_alive} py_alive={py_alive}"
    )

    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Vote Out destroy-target-creature must be byte-equal across "
        f"the WHOLE field view on BOTH; diffs={diffs}"
    )
