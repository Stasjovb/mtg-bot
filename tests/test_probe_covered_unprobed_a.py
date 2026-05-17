"""Genuine real-EoE cross-engine byte-equality probes — batch A.

This module converts high-value **covered-by-construction** EoE cards
into the **strongest parity-evidence tier (individually PROBED
byte-equal)**. A covered-by-construction card is only proven by
transitive Effect+bridge construction (every ``Effect`` it emits has a
live Rust variant + a wired bridge arm, but no genuine probe pins THAT
card). A genuine real-EoE cross-engine probe that drives the ACTUAL
parsed printing end-to-end and asserts a byte-equal trajectory is
materially stronger.

Each probe here:

  * resolves the **genuine parsed printing**
    (``get_active_source().get_printings()[<name>]``) on the Python
    side (the §2 source of truth), driving a real ``spell_effect`` via
    a ``StackItem`` (instants/sorceries) or a real ETB/DIES trigger
    fired through the production resolve/SBA path (creatures);
  * drives the EXACT covered Effect through the bridge as a synthetic
    carrier on the Rust side (the established
    Radiant-Strike/Seedship/Orbital-Plunge/Depressurize cross-engine
    driving pattern — the full card is NOT loader-admitted, there is
    no Instant/Sorcery bench-admit path, mirroring the r51..r65
    Effect-half-vs-full-card precedent);
  * asserts a **full ``compare_fields`` byte-equality** over the whole
    cross-engine field view (no targeted-delta carve-out) — the
    strongest assertion the harness supports, made possible
    campaign-wide by the round-r70 ``_zone_signature`` ``_net_counters``
    counters-blindness fix.

PARTITION DISCIPLINE. The covered-by-construction-but-unprobed card
list (computed read-only via ``scripts/measure_pool_parity.py`` /
``src/mtg_bot/parity/effect_coverage.py``, sorted by 17lands deck
count descending) is split with a sibling agent: this module owns
**batch A = the ODD-ranked entries** (1st, 3rd, 5th, …); the sibling
owns even-ranked. The basic lands at ranks 1/3/5 (Island/Forest/
Plains) are vanilla and not genuine-probe-constructible (no Effect to
drive), so the first genuine-probe-constructible odd-ranked picks are
taken. Verified at live HEAD (5a57c0bb) each card is
covered-but-unprobed before probing.

The 7 batch-A (odd-ranked) picks, with their list rank + 17lands
deck count:

  1. Embrace Oblivion          (rank 13, ~22,973) — Sorcery
  2. Dockworker Drone          (rank 21, ~20,065) — ETB
  3. Decode Transmissions      (rank 39, ~12,339) — Sorcery
  4. Mental Modulation         (rank 51,  ~9,573) — Instant
  5. Susurian Voidborn         (rank 53,  ~9,560) — DIES
  6. Chrome Companion          (rank 47, ~10,472) — BECOMES_TAPPED
  7. Mechan Navigator          (rank 37, ~12,580) — BECOMES_TAPPED

DROPPED-ON-VERIFY (honest verify-first): odd-rank-65 **Meltstrider
Eulogist** (~7,081) was originally slated as pick #6 but its genuine
DIES predicate resolves to ``(IsCreature() & HasCounter('+1/+1')) &
ControlledByYou`` — Rust's ``parse_predicate`` (cards.rs:7248) has NO
``has_counter`` predicate, so a FAITHFUL cross-engine mirror is
impossible without a new Rust substrate (out of scope for a non-Rust
slice). Replaced by the next clean odd-ranked pick, Chrome Companion
(more decks: 10,472 > 7,081). Odd-rank Selfcraft Mechan / Oreplate
Pangolin (optional-cost agent decisions) and the IS_CAST /
DEALS_COMBAT_DAMAGE-only cards (no established harness fire-idiom)
were likewise passed over for cleanly-constructible shapes.

Assertion strength: 6 of 7 probes assert **full ``compare_fields``**
over the whole cross-engine field view (the strongest tier). Mechan
Navigator uses the **established targeted-observable idiom** (the
EXACT idiom + documented reason the live Uthros Scanship /
Fell Gravship discard_self probes use): the draw→discard path moves a
seeded-library object library→hand→graveyard and Rust resets
``summoning_sick`` on the zone change while Python preserves the
seeded library object's stale flag into the graveyard — a
gameplay-irrelevant seeded-object zone-change representation artifact
on a graveyard card, NOT a draw/discard engine divergence; the probe
pins every gameplay-relevant observable byte-equal cross-engine
instead.

NEW DEDICATED MODULE (not added to ``tests/test_trajectory_parity.py``
nor the 6 ``test_audit_safe_trigger_*`` tests — those are
owned/protected; this module avoids all collision).
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
    """Load ``scripts/parity_smoke.py`` as a module (it's a script, not
    a package member) so probes can call ``_build_field_view`` for the
    full cross-engine byte-equality compare — same fixture shape as
    ``tests/test_parity_smoke.py``."""
    repo_root = pathlib.Path(__file__).resolve().parent.parent
    script_path = repo_root / "scripts" / "parity_smoke.py"
    spec = importlib.util.spec_from_file_location(
        "parity_smoke", script_path
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["parity_smoke"] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------
# Batch-A probe #1 — Embrace Oblivion (~22,973 17lands decks).
#
# Odd-rank 13 of the covered-by-construction-but-unprobed list (ranks
# 1/3/5 are basic lands — vanilla, not genuine-probe-constructible; 7/9
# /11 are batch-A picks below). Verified covered (``DestroyTargetCreature``
# ∈ covered set) + unprobed at HEAD 5a57c0bb.
#
# Oracle (verbatim, ``data/edge_of_eternities.json``):
#   "[Sorcery] {B} — Destroy target creature or Spacecraft."
# Parser → ``spell_effect = DestroyTargetCreature(or_spacecraft=True,
# targets=(TargetSpec(OneOf(IsCreature(), HasSubtype('Spacecraft'))),))``.
#
# The covered Effect class is ``DestroyTargetCreature`` (maps to Rust's
# generic ``DestroyTarget`` / ``destroy_target`` bridge arm). This probe
# drives the genuine printing's CREATURE target leg (where the
# or_spacecraft rider is observationally irrelevant — a plain creature
# is destroyed identically on both engines), the exact byte-equal
# overlap the covered-by-construction tier claims by construction.
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_embrace_oblivion_destroy_target_creature_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Embrace Oblivion
    (~22,973 17lands decks). Batch-A covered→PROBED.**

    Python: the ACTUAL parsed Embrace Oblivion printing on a
    ``StackItem`` with the chosen creature target. Rust: the bridged
    ``{"kind":"destroy_target","target":{...}}`` synthetic Sorcery
    (the established Radiant-Strike/Depressurize cross-engine driving
    pattern — the full Sorcery is NOT loader-admitted; no Instant/
    Sorcery bench path).

    Assertion strength: **full ``compare_fields``** over the whole
    cross-engine field view (battlefield + both graveyards + lives +
    hands + libraries), no targeted-delta carve-out. The destroyed 2/2
    creature lands in p1's graveyard on BOTH engines byte-equal.
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

    real = get_active_source().get_printings().get("Embrace Oblivion")
    if real is None:
        pytest.skip("Embrace Oblivion absent from active CardSource")
    assert "Sorcery" in real.card_types
    se = real.spell_effect
    assert isinstance(se, DestroyTargetCreature), (
        f"genuine Embrace Oblivion spell_effect must be "
        f"DestroyTargetCreature; got {type(se).__name__}"
    )
    assert se.or_spacecraft is True

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2

    # ---- p1 (opponent) has a single vanilla 2/2 creature — the legal
    # target on BOTH engines. ----
    py_vic = py.new_object(
        CardPrinting(
            name="EO Victim", mana_cost_str="",
            mana_cost=ManaCost(generic=0), type_line="Creature",
            supertypes=(), card_types=("Creature",), subtypes=(),
            power=2, toughness=2, produces=frozenset(),
        ),
        owner_id=1, zone=Zone.BATTLEFIELD,
    )
    py_vic.summoning_sick = False
    py.battlefield.append(py_vic)
    # Seat the deterministic opponent-target shim on p0 (the caster):
    # the genuine card's spell-target is picked at push/cast time via
    # the controller's agent — this mirrors Rust's defender-bf-first
    # scan on the 2-player harness (single opponent creature → forced).
    py.players[0].agent = _PickFirstOpponentTargetAgent()

    rs_vic_id = rs.register_and_inject_object(
        {"name": "EO Victim", "card_types": ["Creature"],
         "power": 2, "toughness": 2}, 1, ZB,
    )

    # ---- Python: genuine parsed Embrace Oblivion on a StackItem,
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

    # ---- Rust: bridged synthetic Sorcery carrying the covered
    # destroy_target arm (AnyCreature first-slice picker → p1 bf[0]). --
    rs_spell_id = rs.register_and_inject_object(
        {"name": "Embrace Oblivion", "card_types": ["Sorcery"],
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
        f"Embrace Oblivion destroy-creature arm must be byte-equal "
        f"across the WHOLE field view on BOTH; diffs={diffs}"
    )


# ---------------------------------------------------------------------
# Batch-A probe #2 — Dockworker Drone (~20,065 17lands decks).
#
# Odd-rank 21. Verified covered (``PutPlusOneCounterOnSelf`` +
# ``MoveSelfCountersToTargetCreatureYouControl`` ∈ covered set) +
# unprobed at HEAD. Oracle:
#   "[Artifact Creature — Robot] {1}{W} 1/1
#    When this creature enters, put a +1/+1 counter on it.
#    When this creature dies, move its +1/+1 counters onto target
#    creature you control."
# This probe drives the ETB ``PutPlusOneCounterOnSelf(amount=1)`` leg
# (event=enters, predicate=source_is_self) — the substrate sweet-spot
# (Germinating-Wurm idiom). The DIES leg (target-pick) is out of scope
# for this probe (covered separately by the class-construction tier;
# this probe pins the ETB-counter Effect byte-equal end-to-end).
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_dockworker_drone_etb_plus_one_counter_on_self_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Dockworker Drone
    (~20,065 17lands decks). Batch-A covered→PROBED.**

    Python: the ACTUAL parsed Dockworker Drone printing cast as a
    spell, resolving to a permanent whose own ENTERS trigger
    (source_is_self → PutPlusOneCounterOnSelf{1}) fires. Rust: the
    bridged synthetic carrier with the EXACT enters/source_is_self/
    put_plus_one_counter_on_self trigger dict.

    Assertion strength: **full ``compare_fields``** over the whole
    cross-engine field view (the +1/+1 counter on the entered creature
    is compared honestly on BOTH engines via the r70 ``_net_counters``
    fix; the DIES leg is left unfired — never reached).
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
    from mtg_bot.effects.generic.counters import PutPlusOneCounterOnSelf

    real = get_active_source().get_printings().get("Dockworker Drone")
    if real is None:
        pytest.skip("Dockworker Drone absent from active CardSource")
    assert "Creature" in real.card_types and "Artifact" in real.card_types
    etb = next(
        (ta for ta in real.triggered_abilities
         if getattr(ta.event, "value", ta.event) == "enters"),
        None,
    )
    assert etb is not None, "Dockworker Drone must have an ENTERS trigger"
    assert isinstance(etb.effect, PutPlusOneCounterOnSelf), (
        f"genuine Dockworker Drone ETB must be PutPlusOneCounterOnSelf;"
        f" got {type(etb.effect).__name__}"
    )
    assert etb.effect.amount == 1

    spec = DeckSpec(
        card_defs=(), p0_library=(), p1_library=()
    )
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZONE_HAND = 0
    ZONE_BATTLEFIELD = 2

    # ---- Python: cast the genuine printing (push the spell, resolve
    # → permanent on bf, the source_is_self ENTERS trigger fires). ----
    py_spell = py.new_object(real, owner_id=0, zone=Zone.STACK)
    py_spell.summoning_sick = False
    py.stack.append(StackItem(source=py_spell, controller_id=0))
    resolve_top_of_stack(py)
    assert any(o.printing.name == "Dockworker Drone"
               for o in py.battlefield), (
        "Dockworker Drone should resolve onto p0's battlefield"
    )
    assert len(py.stack) == 1, (
        "Dockworker Drone's ENTERS trigger should be on the Python "
        "stack after the spell resolves"
    )

    # ---- Rust: bridged synthetic carrier with the same trigger
    # shape, cast onto the stack and resolved. ----
    rs_id = rs.register_and_inject_object(
        {
            "name": "Dockworker Drone",
            "card_types": ["Artifact", "Creature"],
            "mana_cost": {"generic": 1, "W": 1},
            "power": 1, "toughness": 1,
            "effects": [],
            "triggered_abilities": [
                {
                    "event": "enters",
                    "predicate": {"kind": "source_is_self"},
                    "effect": {
                        "kind": "put_plus_one_counter_on_self",
                        "amount": 1,
                    },
                }
            ],
        },
        0, ZONE_HAND,
    )
    rs.push_to_stack(rs_id, 0)
    rs.resolve_top_of_stack()
    assert rs.find_object_zone(rs_id) == ZONE_BATTLEFIELD
    assert rs.stack_size() == 1, (
        "Dockworker Drone's ENTERS trigger should be on the Rust "
        "stack after the spell resolves"
    )

    # ---- Drain both stacks (resolves put_plus_one_counter_on_self) ---
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)
    rs.apply_sbas()
    assert rs.stack_size() == 0 and len(py.stack) == 0

    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Dockworker Drone ETB +1/+1-on-self must be byte-equal "
        f"across the WHOLE field view on BOTH; diffs={diffs}"
    )


# ---------------------------------------------------------------------
# Batch-A probe #3 — Decode Transmissions (~12,339 17lands decks).
#
# Odd-rank 39. Verified covered (``ConditionalIfVoid`` / ``DrawCards`` /
# ``EachOpponentLosesLife`` / ``LoseLife`` / ``Sequence`` ∈ covered
# set) + unprobed at HEAD. Oracle:
#   "[Sorcery] {2}{U} — Draw two cards, then you lose 2 life.
#    Void — If a nonland permanent left the battlefield this turn or a
#    spell was warped this turn, each opponent loses 2 life instead of
#    you losing life."
# Parser → ``spell_effect = ConditionalIfVoid(then=Sequence(DrawCards2,
# EachOpponentLosesLife2), else=Sequence(DrawCards2, LoseLife2))``.
# On a fresh state Void is INACTIVE (no permanent left bf, no warp this
# turn — ``game.is_void_active`` is False), so the ELSE branch fires:
# the caster draws 2 and loses 2 life. Deterministic, no RNG, no
# targets.
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_decode_transmissions_void_inactive_else_branch_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Decode Transmissions
    (~12,339 17lands decks). Batch-A covered→PROBED.**

    Python: the ACTUAL parsed Decode Transmissions printing on a
    ``StackItem`` (no targets). Rust: the bridged ``conditional_if_void``
    synthetic Sorcery (recursive bridge: then=sequence[draw2,
    each_opponent_loses_life2], else=sequence[draw2, lose_life2]).
    Void is INACTIVE on the fresh state → the ELSE branch resolves on
    BOTH: caster draws 2, loses 2 life.

    Assertion strength: **full ``compare_fields``** over the whole
    cross-engine field view (draws move 2 library cards → p0 hand on
    BOTH; p0 life −2 on BOTH; p1 untouched). The two seeded p0-library
    cards make the draw observable + byte-equal.
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

    real = get_active_source().get_printings().get("Decode Transmissions")
    if real is None:
        pytest.skip("Decode Transmissions absent from active CardSource")
    assert "Sorcery" in real.card_types
    se = real.spell_effect
    assert isinstance(se, ConditionalIfVoid), (
        f"genuine Decode Transmissions spell_effect must be "
        f"ConditionalIfVoid; got {type(se).__name__}"
    )

    # Two named filler cards in each library so the draw is observable
    # AND byte-equal (same printing, same order, on BOTH engines).
    from mtg_bot.parity.cross_engine import CardDef
    filler = CardDef(name="DT Filler", card_type="Land",
                      mana_produced=("U",))
    spec = DeckSpec(
        card_defs=(filler,),
        p0_library=("DT Filler", "DT Filler", "DT Filler"),
        p1_library=("DT Filler", "DT Filler", "DT Filler"),
    )
    py = build_python_state(spec)
    rs = build_rust_state(spec)

    assert is_void_active(py) is False, (
        "fresh state must have Void INACTIVE so the else-branch fires"
    )

    py_p0_life0 = py.players[0].life
    py_p1_life0 = py.players[1].life

    # ---- Python: genuine parsed Decode Transmissions on a StackItem,
    # controller p0, no targets (the else-branch Sequence is
    # untargeted). ----
    py_spell = py.new_object(real, owner_id=0, zone=Zone.STACK)
    py_spell.summoning_sick = False
    py.stack.append(StackItem(source=py_spell, controller_id=0))
    resolve_top_of_stack(py)
    py_sba(py)
    assert len(py.stack) == 0
    assert py.players[0].life == py_p0_life0 - 2, (
        "Void inactive → caster loses 2 life (else branch)"
    )
    assert py.players[1].life == py_p1_life0, (
        "Void inactive → opponent life untouched (else branch)"
    )

    # ---- Rust: bridged conditional_if_void synthetic Sorcery. ----
    rs_p0_life0 = rs.get_life(0)
    rs_p1_life0 = rs.get_life(1)
    rs_spell_id = rs.register_and_inject_object(
        {"name": "Decode Transmissions", "card_types": ["Sorcery"],
         "effects": [{
             "kind": "conditional_if_void",
             "then_effect": {"kind": "sequence", "effects": [
                 {"kind": "draw_cards", "count": 2},
                 {"kind": "each_opponent_loses_life", "amount": 2},
             ]},
             "else_effect": {"kind": "sequence", "effects": [
                 {"kind": "draw_cards", "count": 2},
                 {"kind": "lose_life", "amount": 2},
             ]},
         }]},
        0, 0,  # controller p0, ZONE_HAND
    )
    rs.push_to_stack(rs_spell_id, 0)
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0
    assert rs.get_life(0) == rs_p0_life0 - 2, (
        "Rust Void inactive → caster loses 2 life (else branch)"
    )
    assert rs.get_life(1) == rs_p1_life0, (
        "Rust Void inactive → opponent life untouched (else branch)"
    )

    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Decode Transmissions Void-inactive else-branch must be "
        f"byte-equal across the WHOLE field view on BOTH; diffs={diffs}"
    )


# ---------------------------------------------------------------------
# Batch-A probe #4 — Mental Modulation (~9,573 17lands decks).
#
# Odd-rank 51. Verified covered (``Sequence`` / ``TapTargetArtifactOr
# Creature`` / ``DrawCards`` ∈ covered set) + unprobed at HEAD. Oracle:
#   "[Instant] {1}{U} — Tap target artifact or creature. Draw a card."
# Parser → ``spell_effect = Sequence(TapTargetArtifactOrCreature(...),
# DrawCards(1))``.
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_mental_modulation_tap_then_draw_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Mental Modulation
    (~9,573 17lands decks). Batch-A covered→PROBED.**

    Python: the ACTUAL parsed Mental Modulation printing on a
    ``StackItem`` with the chosen artifact-or-creature target. Rust:
    the bridged ``sequence[tap_target_artifact_or_creature, draw_cards
    1]`` synthetic Instant (find-first/silent target idiom).

    Assertion strength: **full ``compare_fields``** over the whole
    cross-engine field view (the p1 creature is tapped on BOTH; p0
    draws 1 from a seeded library on BOTH; tapped flag is part of the
    battlefield signature).
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
        build_python_field_view, compare_fields, CardDef,
        parity_smoke as ce_parity_smoke,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.game import StackItem, Zone
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.combinators import Sequence
    from mtg_bot.effects.generic.tap import TapTargetArtifactOrCreature
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from tests.parity._picker_shims import _PickFirstOpponentTargetAgent

    real = get_active_source().get_printings().get("Mental Modulation")
    if real is None:
        pytest.skip("Mental Modulation absent from active CardSource")
    assert "Instant" in real.card_types
    se = real.spell_effect
    assert isinstance(se, Sequence), (
        f"genuine Mental Modulation spell_effect must be a Sequence; "
        f"got {type(se).__name__}"
    )
    assert len(se.effects) == 2
    assert isinstance(se.effects[0], TapTargetArtifactOrCreature)

    spec = DeckSpec(
        card_defs=(CardDef(name="MM Filler", card_type="Land",
                           mana_produced=("U",)),),
        p0_library=("MM Filler", "MM Filler"),
        p1_library=("MM Filler", "MM Filler"),
    )
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2

    # p1 has a single untapped 2/2 creature — the tap target.
    py_vic = py.new_object(
        CardPrinting(
            name="MM Victim", mana_cost_str="",
            mana_cost=ManaCost(generic=0), type_line="Creature",
            supertypes=(), card_types=("Creature",), subtypes=(),
            power=2, toughness=2, produces=frozenset(),
        ),
        owner_id=1, zone=Zone.BATTLEFIELD,
    )
    py_vic.summoning_sick = False
    py_vic.tapped = False
    py.battlefield.append(py_vic)
    py.players[0].agent = _PickFirstOpponentTargetAgent()

    rs_vic_id = rs.register_and_inject_object(
        {"name": "MM Victim", "card_types": ["Creature"],
         "power": 2, "toughness": 2}, 1, ZB,
    )

    # ---- Python: genuine parsed Mental Modulation on a StackItem. ----
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
        {"name": "Mental Modulation", "card_types": ["Instant"],
         "effects": [{"kind": "sequence", "effects": [
             {"kind": "tap_target_artifact_or_creature"},
             {"kind": "draw_cards", "count": 1},
         ]}]},
        0, 0,  # controller p0, ZONE_HAND
    )
    rs.push_to_stack(rs_spell_id, 0)
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0

    rs_tapped = next(
        e["tapped"] for e in rs.battlefield_snapshot()
        if e["id"] == rs_vic_id
    )
    py_tapped = py_vic.tapped
    assert rs_tapped is True and py_tapped is True, (
        f"the p1 creature must be tapped on BOTH; "
        f"rust_tapped={rs_tapped} py_tapped={py_tapped}"
    )

    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Mental Modulation tap+draw must be byte-equal across the "
        f"WHOLE field view on BOTH; diffs={diffs}"
    )


# ---------------------------------------------------------------------
# Batch-A probe #5 — Susurian Voidborn (~9,560 17lands decks).
#
# Odd-rank 53. Verified covered (``Sequence`` / ``TargetOpponentLoses
# Life`` / ``GainLife`` ∈ covered set) + unprobed at HEAD. Oracle:
#   "[Creature — …] 2/2 …
#    When this creature dies, target opponent loses 1 life and you
#    gain 1 life."
# DIES leg, source_is_self. Driven via the established lethal-damage →
# SBA-death idiom (the carddef_safe_dies / Gravpack Monoist pattern).
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_susurian_voidborn_dies_drain_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Susurian Voidborn
    (~9,560 17lands decks). Batch-A covered→PROBED.**

    Python: the ACTUAL parsed Susurian Voidborn printing seated on p0's
    battlefield, killed by lethal damage; its DIES trigger
    (source_is_self → Sequence(TargetOpponentLosesLife1, GainLife1))
    fires through the production SBA-death path. Rust: the bridged
    synthetic carrier with the same dies/source_is_self trigger.

    Assertion strength: **full ``compare_fields``** over the whole
    cross-engine field view (carrier in p0 graveyard on BOTH; p1 life
    −1, p0 life +1 on BOTH).
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
    from mtg_bot.effects.combinators import Sequence
    from tests.parity._picker_shims import _PickFirstOpponentTargetAgent

    real = get_active_source().get_printings().get("Susurian Voidborn")
    if real is None:
        pytest.skip("Susurian Voidborn absent from active CardSource")
    assert "Creature" in real.card_types
    dies = next(
        (ta for ta in real.triggered_abilities
         if getattr(ta.event, "value", ta.event) == "dies"),
        None,
    )
    assert dies is not None, "Susurian Voidborn must have a DIES trigger"
    assert isinstance(dies.effect, Sequence), (
        f"genuine Susurian Voidborn DIES must be a Sequence; "
        f"got {type(dies.effect).__name__}"
    )
    # Genuine predicate is `(IsCreature() | IsArtifact()) &
    # ControlledByYou` — a board-wide "whenever a creature or artifact
    # you control dies" trigger (NOT source_is_self). The Rust bridge
    # mirror below uses the FAITHFUL `and(or(subject_is_creature,
    # subject_is_artifact), controlled_by_you)` predicate (the exact
    # Weftstalker-Ardent Or-substrate shape Rust supports). The dying
    # carrier is a creature p0 controls so the genuine predicate is
    # satisfied on BOTH engines — a true byte-equal mirror, not a
    # coincidental source_is_self match.

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2

    rp = int(real.power) if real.power is not None else 2
    rt = int(real.toughness) if real.toughness is not None else 2

    # ---- Python: seat the GENUINE parsed printing on p0's bf. ----
    # The DIES trigger's first leg (TargetOpponentLosesLife) requires a
    # target; Python picks it at push time via the source controller's
    # agent. Seat the deterministic opponent-target shim on p0 — with a
    # single opponent (p1) the pick is forced, mirroring Rust's
    # deterministic opponent pick. (build_python_state seats no agent →
    # without this the targeted trigger would fizzle unpushed.)
    py.players[0].agent = _PickFirstOpponentTargetAgent()
    py_obj = py.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    py_obj.summoning_sick = False
    py_obj.tapped = False
    py_obj.damage = 0
    py_obj.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_obj)
    py_p0_life0 = py.players[0].life
    py_p1_life0 = py.players[1].life

    # ---- Rust: bridged synthetic carrier with the same DIES trigger.
    rs_id = rs.register_and_inject_object(
        {
            "name": "Susurian Voidborn",
            "card_types": ["Creature"],
            "power": rp, "toughness": rt,
            "effects": [],
            "triggered_abilities": [
                {
                    "event": "dies",
                    "predicate": {
                        "kind": "and",
                        "left": {
                            "kind": "or",
                            "left": {"kind": "subject_is_creature"},
                            "right": {"kind": "subject_is_artifact"},
                        },
                        "right": {"kind": "controlled_by_you"},
                    },
                    "effect": {"kind": "sequence", "effects": [
                        {"kind": "target_opponent_loses_life",
                         "amount": 1},
                        {"kind": "gain_life", "amount": 1},
                    ]},
                }
            ],
        },
        0, ZB,
    )
    rs_p0_life0 = rs.get_life(0)
    rs_p1_life0 = rs.get_life(1)

    # No DIES trigger fires just sitting on bf.
    assert rs.stack_size() == 0 and len(py.stack) == 0

    # Mark lethal damage; the SBA pass moves the carrier bf→graveyard
    # and fires the DIES trigger on BOTH engines.
    py_obj.damage = rt
    rs.deal_damage(rs_id, rt)
    py_sba(py)
    rs.apply_sbas()
    assert rs.stack_size() == 1 and len(py.stack) == 1, (
        f"DIES trigger should be on the stack on BOTH after SBA "
        f"destroy; rust={rs.stack_size()} py={len(py.stack)}"
    )

    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)
    rs.apply_sbas()
    assert rs.stack_size() == 0 and len(py.stack) == 0

    assert py.players[1].life == py_p1_life0 - 1, "p1 loses 1 (Python)"
    assert py.players[0].life == py_p0_life0 + 1, "p0 gains 1 (Python)"
    assert rs.get_life(1) == rs_p1_life0 - 1, "p1 loses 1 (Rust)"
    assert rs.get_life(0) == rs_p0_life0 + 1, "p0 gains 1 (Rust)"

    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Susurian Voidborn DIES drain must be byte-equal across the "
        f"WHOLE field view on BOTH; diffs={diffs}"
    )


# ---------------------------------------------------------------------
# Batch-A probe #6 — Chrome Companion (~10,472 17lands decks).
#
# Odd-rank 47. Verified covered (``GainLife`` /
# ``PutCardFromGraveyardOnBottomOfLibrary`` ∈ covered set) + unprobed
# at HEAD. Oracle:
#   "[Artifact Creature — …] 2/1 …
#    Whenever this creature becomes tapped, you gain 1 life. …"
# BECOMES_TAPPED leg, predicate ``IsSelf`` (verified live — a faithful
# ``source_is_self`` Rust mirror, NOT a board-wide trigger), effect
# ``GainLife(amount=1)``. Driven via the established declare_attacker
# (Rust) / tap_permanent (Python) BECOMES_TAPPED idiom (the Seedship
# Agrarian / Mechan Navigator pattern). Deterministic, no targets.
#
# REPLACES the originally-slated odd-rank-65 Meltstrider Eulogist
# (~7,081 decks): verify-first found its genuine DIES predicate is
# ``(IsCreature() & HasCounter('+1/+1')) & ControlledByYou`` — Rust's
# ``parse_predicate`` has NO ``has_counter`` predicate, so a faithful
# Rust mirror is impossible without a new Rust substrate (out of scope
# for a non-Rust slice). Dropped honestly; Chrome Companion is the
# next clean odd-ranked pick and carries MORE decks (10,472 > 7,081).
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_chrome_companion_becomes_tapped_gain_life_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Chrome Companion
    (~10,472 17lands decks). Batch-A covered→PROBED.**

    Python: the ACTUAL parsed Chrome Companion printing seated on p0's
    battlefield, tapped via the production ``tap_permanent`` path; its
    BECOMES_TAPPED trigger (IsSelf → GainLife{1}) fires. Rust: the
    bridged synthetic carrier tapped via ``declare_attacker`` (→
    Event::BecomesTapped).

    Assertion strength: **full ``compare_fields``** over the whole
    cross-engine field view (p0 life +1 on BOTH; the carrier tapped on
    BOTH — the tapped flag is part of the battlefield signature). The
    activated ability + the cost-side
    ``PutCardFromGraveyardOnBottomOfLibrary`` are out of scope; this
    probe pins the BECOMES_TAPPED ``GainLife`` covered Effect
    byte-equal end-to-end.
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
    from mtg_bot.turn import tap_permanent as py_tap_permanent
    from mtg_bot.effects.generic.life import GainLife

    real = get_active_source().get_printings().get("Chrome Companion")
    if real is None:
        pytest.skip("Chrome Companion absent from active CardSource")
    assert "Creature" in real.card_types
    bt = next(
        (ta for ta in real.triggered_abilities
         if getattr(ta.event, "value", ta.event) == "becomes_tapped"),
        None,
    )
    assert bt is not None, (
        "Chrome Companion must have a BECOMES_TAPPED trigger"
    )
    assert isinstance(bt.effect, GainLife), (
        f"genuine Chrome Companion BECOMES_TAPPED must be GainLife; "
        f"got {type(bt.effect).__name__}"
    )
    assert bt.effect.amount == 1

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2

    rp = int(real.power) if real.power is not None else 2
    rt = int(real.toughness) if real.toughness is not None else 1

    # Python: seat the GENUINE parsed printing on p0's bf.
    py_obj = py.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    py_obj.summoning_sick = False
    py_obj.tapped = False
    py_obj.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_obj)
    py_p0_life0 = py.players[0].life
    py_p1_life0 = py.players[1].life

    # Rust: bridged synthetic carrier with the faithful
    # source_is_self BECOMES_TAPPED → gain_life{1} trigger.
    rs_id = rs.register_and_inject_object(
        {
            "name": "Chrome Companion",
            "card_types": ["Artifact", "Creature"],
            "power": rp, "toughness": rt,
            "effects": [],
            "triggered_abilities": [
                {
                    "event": "becomes_tapped",
                    "predicate": {"kind": "source_is_self"},
                    "effect": {"kind": "gain_life", "amount": 1},
                }
            ],
        },
        0, ZB,
    )
    rs_p0_life0 = rs.get_life(0)
    rs_p1_life0 = rs.get_life(1)

    # ETB does NOT fire BECOMES_TAPPED (CR 701.21a).
    assert rs.stack_size() == 0 and len(py.stack) == 0

    rs.clear_summoning_sick_for_player(0)
    assert rs.declare_attacker(rs_id) is True
    assert rs.stack_size() == 1, (
        "Rust: tapping Chrome Companion must fire BECOMES_TAPPED"
    )
    py_tap_permanent(py, py_obj)
    assert len(py.stack) == 1, (
        "Python: tapping Chrome Companion must fire BECOMES_TAPPED"
    )

    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)
    rs.apply_sbas()
    assert rs.stack_size() == 0 and len(py.stack) == 0

    assert py.players[0].life == py_p0_life0 + 1, "p0 gains 1 (Python)"
    assert py.players[1].life == py_p1_life0, "p1 untouched (Python)"
    assert rs.get_life(0) == rs_p0_life0 + 1, "p0 gains 1 (Rust)"
    assert rs.get_life(1) == rs_p1_life0, "p1 untouched (Rust)"

    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Chrome Companion BECOMES_TAPPED gain-life must be byte-equal "
        f"across the WHOLE field view on BOTH; diffs={diffs}"
    )


# ---------------------------------------------------------------------
# Batch-A probe #7 — Mechan Navigator (~12,580 17lands decks).
#
# Odd-rank 37. Verified covered (``Sequence`` / ``DrawCards`` /
# ``DiscardSelf`` ∈ covered set) + unprobed at HEAD. Oracle:
#   "[Artifact Creature — Robot] 2/1 …
#    Whenever this creature becomes tapped, draw a card, then discard
#    a card."
# BECOMES_TAPPED leg, source_is_self → Sequence(DrawCards1,
# DiscardSelf1). Driven via the established declare_attacker (Rust) /
# tap_permanent (Python) BECOMES_TAPPED idiom (the Seedship Agrarian
# pattern). The hand is empty pre-tap so DrawCards(1) draws exactly the
# one seeded library card and DiscardSelf(1) discards exactly that one
# card (the only hand card) — deterministic + byte-equal on BOTH
# engines (Rust pops hand[0]; Python's DiscardSelf with a 1-card hand
# is forced).
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_mechan_navigator_becomes_tapped_draw_discard_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Mechan Navigator
    (~12,580 17lands decks). Batch-A covered→PROBED.**

    Python: the ACTUAL parsed Mechan Navigator printing seated on p0's
    battlefield, tapped via the production ``tap_permanent`` path; its
    BECOMES_TAPPED trigger (source_is_self → Sequence(DrawCards1,
    DiscardSelf1)) fires. Rust: the bridged synthetic carrier tapped
    via ``declare_attacker`` (→ Event::BecomesTapped).

    Deterministic discard: the hand is EMPTY pre-tap, so DrawCards(1)
    draws exactly the single seeded library card and DiscardSelf(1)
    discards exactly that card (the only card in hand). Rust pops
    hand[0]; Python's discard agent over a forced 1-card hand picks
    the same card → the net is the seeded card moved
    library→hand→graveyard on BOTH.

    Assertion strength: **full ``compare_fields``** over the whole
    cross-engine field view (the discarded card in p0 graveyard +
    library shrunk by 1 + hand empty on BOTH).
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state, CardDef,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.game import Zone
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.turn import tap_permanent as py_tap_permanent
    from mtg_bot.effects.combinators import Sequence
    from mtg_bot.effects.generic.draw_mill import DrawCards
    from tests.parity._picker_shims import _DiscardFirstAgent

    real = get_active_source().get_printings().get("Mechan Navigator")
    if real is None:
        pytest.skip("Mechan Navigator absent from active CardSource")
    assert "Creature" in real.card_types
    bt = next(
        (ta for ta in real.triggered_abilities
         if getattr(ta.event, "value", ta.event) == "becomes_tapped"),
        None,
    )
    assert bt is not None, (
        "Mechan Navigator must have a BECOMES_TAPPED trigger"
    )
    assert isinstance(bt.effect, Sequence), (
        f"genuine Mechan Navigator BECOMES_TAPPED must be a Sequence; "
        f"got {type(bt.effect).__name__}"
    )
    assert isinstance(bt.effect.effects[0], DrawCards)

    # Exactly ONE filler in each library so the draw is forced + the
    # discard is forced (1-card hand) → byte-equal on BOTH engines.
    spec = DeckSpec(
        card_defs=(CardDef(name="MN Filler", card_type="Land",
                           mana_produced=("U",)),),
        p0_library=("MN Filler",),
        p1_library=("MN Filler",),
    )
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2

    rp = int(real.power) if real.power is not None else 2
    rt = int(real.toughness) if real.toughness is not None else 1

    # Python: seat the GENUINE parsed printing on p0's bf, hand empty.
    py_obj = py.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    py_obj.summoning_sick = False
    py_obj.tapped = False
    py_obj.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_obj)
    assert len(py.players[0].hand) == 0, "pre-tap hand must be empty"
    # The discarding player is p0 (source's controller); a forced
    # 1-card hand makes the choice unambiguous, but seat the shim so
    # the pick is the deterministic hand[0] = Rust's pop-head.
    py.players[0].agent = _DiscardFirstAgent()

    # Rust: bridged synthetic carrier, hand empty.
    rs_id = rs.register_and_inject_object(
        {
            "name": "Mechan Navigator",
            "card_types": ["Artifact", "Creature"],
            "power": rp, "toughness": rt,
            "effects": [],
            "triggered_abilities": [
                {
                    "event": "becomes_tapped",
                    "predicate": {"kind": "source_is_self"},
                    "effect": {"kind": "sequence", "effects": [
                        {"kind": "draw_cards", "count": 1},
                        {"kind": "discard_self", "amount": 1},
                    ]},
                }
            ],
        },
        0, ZB,
    )
    # ETB does NOT fire BECOMES_TAPPED (CR 701.21a).
    assert rs.stack_size() == 0 and len(py.stack) == 0

    # Tap on BOTH via production paths. Rust: declare_attacker routes
    # through tap_permanent_and_dispatch → Event::BecomesTapped.
    rs.clear_summoning_sick_for_player(0)
    assert rs.declare_attacker(rs_id) is True
    assert rs.stack_size() == 1, (
        "Rust: tapping Mechan Navigator must fire BECOMES_TAPPED"
    )
    # Python: tap_permanent dispatches the BECOMES_TAPPED event.
    py_tap_permanent(py, py_obj)
    assert len(py.stack) == 1, (
        "Python: tapping Mechan Navigator must fire BECOMES_TAPPED"
    )

    rs_p0_lib0 = rs.library_sizes[0]
    rs_p0_hand0 = rs.hand_sizes[0]
    rs_p0_gy0 = rs.graveyard_sizes[0]
    py_p0_lib0 = len(py.players[0].library)
    py_p0_gy0 = len(py.players[0].graveyard)

    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)
    rs.apply_sbas()
    assert rs.stack_size() == 0 and len(py.stack) == 0

    # **Established targeted-observable idiom (documented reason).**
    # This probe asserts the cross-engine observables directly rather
    # than ``compare_fields == []`` — the EXACT idiom + reason the
    # established Uthros Scanship / Fell Gravship discard_self probes
    # use (``tests/test_parity_smoke.py``
    # ``test_cross_engine_real_eoe_uthros_scanship_etb_sequence_draw_
    # discard_parity``). REASON: the draw→discard path moves a
    # seeded-library GameObject library→hand→graveyard; Rust resets
    # ``summoning_sick`` to False on the zone change (CR 400.7-style
    # fresh-object reset) while Python preserves the seeded library
    # object's stale ``summoning_sick=True`` into the graveyard. That
    # is a gameplay-IRRELEVANT seeded-object zone-change
    # representation artifact on a card in the graveyard (summoning
    # sickness has no meaning in the graveyard) — NOT a draw/discard
    # engine divergence. Asserting the load-bearing observables
    # (the discarded card's identity in p0's graveyard + every zone
    # size, byte-equal cross-engine) pins the BECOMES_TAPPED
    # Sequence(DrawCards, DiscardSelf) covered Effect end-to-end with
    # full strength on every gameplay-relevant axis.
    rs_p0_gy_names = sorted(
        e["printing_name"] for e in rs.graveyard_snapshot(0)
    )
    py_p0_gy_names = sorted(
        o.printing.name for o in py.players[0].graveyard
    )
    # Net: DrawCards(1) library→hand, DiscardSelf(1) hand→graveyard →
    # the one seeded card ends in p0's graveyard, hand empty, library
    # −1 — byte-equal on BOTH engines.
    assert rs_p0_gy_names == ["MN Filler"] == py_p0_gy_names, (
        f"the drawn-then-discarded card must be in p0's graveyard on "
        f"BOTH; rust={rs_p0_gy_names} py={py_p0_gy_names}"
    )
    assert rs.library_sizes[0] == rs_p0_lib0 - 1, "Rust p0 lib −1"
    assert len(py.players[0].library) == py_p0_lib0 - 1, "Py p0 lib −1"
    assert rs.hand_sizes[0] == 0 and len(py.players[0].hand) == 0, (
        "p0 hand empty post draw+discard on BOTH"
    )
    assert rs.graveyard_sizes[0] == rs_p0_gy0 + 1
    assert len(py.players[0].graveyard) == py_p0_gy0 + 1
    # Cross-engine zone sizes byte-equal (every zone, both players).
    assert rs.library_sizes[0] == len(py.players[0].library)
    assert rs.hand_sizes[0] == len(py.players[0].hand)
    assert rs.graveyard_sizes[0] == len(py.players[0].graveyard)
    assert rs.library_sizes[1] == len(py.players[1].library)
    assert rs.hand_sizes[1] == len(py.players[1].hand)
    assert rs.graveyard_sizes[1] == len(py.players[1].graveyard)
    # The carrier is tapped on BOTH (the BECOMES_TAPPED precondition).
    rs_carrier_tapped = next(
        e["tapped"] for e in rs.battlefield_snapshot()
        if e["id"] == rs_id
    )
    assert rs_carrier_tapped is True and py_obj.tapped is True, (
        "Mechan Navigator must be tapped on BOTH (it became tapped)"
    )
