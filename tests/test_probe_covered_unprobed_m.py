"""Genuine real-EoE cross-engine byte-equality probes — batch M.

CONTINUOUS-PIPELINE phase: convert high-value
``covered-by-construction`` EoE cards into the **strongest parity-
evidence tier** (``PROBED byte-equal`` per ``docs/POOL_PARITY.md`` /
``scripts/measure_pool_parity.py``) via genuine real-EoE cross-engine
probes.

WHAT EACH PROBE ASSERTS
-----------------------
Every probe drives the **ACTUAL parsed EoE printing** on the Python
side (``get_active_source().get_printings().get("<card>")`` — NOT a
synthetic stub) against the bridged synthetic carrier on the Rust side
(``register_and_inject_object`` with the closed-vocab effect dict the
production bridge round-trips — the established Embrace-Oblivion /
Decode-Transmissions / Sami's-Curiosity cross-engine driving pattern;
the full Sorcery/Instant is NOT loader-admitted, there is no
Instant/Sorcery bench path) and asserts **full ``compare_fields(...)
== []``** — byte-equality across the WHOLE cross-engine field view,
the strongest Effect+bridge-level evidence — after a real EoE deck
context (the carrier resolved end-to-end on both engines, the spell
fired, the stack drained). Made campaign-wide possible by the
round-r70 ``_zone_signature`` ``_net_counters`` counters-blindness fix.

> CAVEAT (mirrors ``docs/POOL_PARITY.md``): this is Effect+bridge-
> level byte-equality on a *controlled* cross-engine state, NOT
> full-game-trajectory parity. PROBED is the strongest evidence tier
> the campaign tracks; it is not a full random multi-turn game.

PARTITION DISCIPLINE (batch M — SORCERY round 3, after G + J)
-------------------------------------------------------------
This module is batch M, the third round of SORCERY (and trivially-
resolving INSTANT) covered-but-unprobed probes, extending the sorcery
lane after batches G (Scrounge for Eternity / Pyroclasm / Final
Vengeance) and J (Murder / Impossible Inferno / Midnight Mayhem /
Winter's Intervention). Sibling agents N (ETB triggers, round 3) and
O (DIES triggers, round 3) run in parallel worktrees. The
covered-by-construction-but-unprobed list (computed read-only via
``scripts/measure_pool_parity.classify_pool``, sorted by 17lands deck
count desc) was verify-first-recomputed at live HEAD e5993c43; every
card below is (a) covered-by-construction, (b) NOT individually
probed, (c) NOT in any sibling batch, (d) an Instant or Sorcery with
a ``spell_effect`` that resolves directly with no creature-trigger
involvement.

The 3 cards pinned here (deck counts from ``data/17lands/
eoe_decks.json.gz`` at verify-first walk):

  1. Scorching Dragonfire  (~0 17lands decks) — Instant,
     DealDamageToTargetCreature(amount=3)
  2. Untimely Malfunction  (~0 17lands decks) — Instant,
     DestroyTargetArtifact (plain vanilla destroy-artifact, no riders)
  3. Turn Inside Out       (~0 17lands decks) — Instant,
     PumpTargetCreatureUntilEOT(power_bonus=3, toughness_bonus=0,
       granted_keywords=frozenset())

DROPPED-ON-VERIFY (honest verify-first discipline):

  * **Temporal Intervention** (~1,715 decks) — ``spell_effect`` is
    ``TargetOpponentDiscardsCasterChoice`` (the CASTER picks which
    card the opponent discards). The ``discard_card`` bridge arm maps
    to ``TargetOpponentDiscards`` (the DISCARDER's own agent picks) —
    a genuinely DIFFERENT resolution semantic documented in the batch-G
    drops. Excluded.
  * **Dual-Sun Technique** (~3,734 decks) — ``PumpTargetCreatureUntilEOT``
    with ``draw_if_target_has_plus_one_counter=1``; the Rust
    ``pump_target_creature_until_eot`` bridge arm carries NO
    draw-if-counter rider. Documented in batch-G drops. Excluded.
  * **Drag to the Roots** (~0 decks) — ``DestroyTargetNonlandPermanent``.
    Rust's ``destroy_target_nonland_permanent`` arm scans BOTH players'
    bf in ETB-timestamp order (``bf_iter_etb_sorted``) and picks the
    first non-land permanent. On Python, the StackItem target is pre-
    chosen; Rust picks at apply time. A probe needs a SINGLE non-land
    on the board so both sides agree on the pick. A creature on p1's bf
    satisfies both the ``IsCreature`` and the ``~IsLand() & ~IsPlayer()``
    filter — but a lone creature on p1 makes the probe byte-equal with
    ``destroy_target`` (Murder shape) rather than specifically exercising
    the nonland-permanent arm. Without a distinct non-creature, non-land
    permanent (e.g. an artifact or enchantment) on the board, the probe
    can't distinguish the nonland-permanent arm from the creature arm.
    Seating an artifact on p1 would make Untimely Malfunction (probe #2
    here) and Drag to the Roots overlap on the same scenario. The
    nonland arm is already bridged and its Python class is covered; the
    marginal value over probe #2 is low. Dropped; Untimely Malfunction
    (artifact subtype) pins the nonland-permanent family differently.
  * **Come Back Wrong / Seized from Slumber** (~0 decks) — both parse
    to ``DestroyTargetCreature(draw_if_undamaged_amount=0)`` — the same
    shape as Murder (batch J). ``draw_if_undamaged_amount=0`` means the
    draw leg is a no-op (the rider fires only when amount > 0). While
    the field view would be byte-equal for the pure-destroy case, both
    cards produce the SAME covered-effect tier uplift Murder already
    provides (DestroyTargetCreature is already PROBED-level evidence
    via Murder). Dropped; low marginal value.
  * **Trial of Agony** (~0 decks) — ``DealDamageToTargetCreature(
    amount=5)``. Same shape as Impossible Inferno (batch J, amount=6)
    and Scorching Dragonfire (probe #1 here, amount=3). The ``deal_
    damage`` arm is already PROBED-level evidence; adding a third probe
    for the same bridge arm would add no new Effect coverage. Dropped;
    Scorching Dragonfire provides the amount=3 variant.
  * **Violent Urge / Give In to Violence / Dual-Sun Technique** — all
    ``PumpTargetCreatureUntilEOT`` with ``granted_keywords`` rider.
    The ``pump_target_creature_until_eot`` bridge arm (cross_engine.py:
    1126) passes only ``power_bonus`` / ``toughness_bonus`` and does NOT
    plumb the ``granted_keywords`` field through the dict shape. Any
    probe of the keyword-bearing variant would diverge on the granted
    keyword (Python grants it; Rust's bridge arm omits it). Turn Inside
    Out (+3/+0, ``granted_keywords=frozenset()``) is the ONLY clean
    keyword-free variant in the candidate set. The keyword-bearing cards
    are excluded; Turn Inside Out (#3 here) covers the PT-only form.
  * **Horrid Vigor** (~0 decks) — ``PumpTargetCreatureUntilEOT(+0/+0,
    frozenset({'indestructible','deathtouch'}))``. Keywords-only rider
    (zero PT bonus) — same keyword-bridge gap as above. Dropped.
  * **Manifest Dread / Under the Skin / Break Down the Door** — all
    ``ManifestDread``. The ManifestDread bridge is documented as a
    bridge-defer (no ``manifest_dread`` bridge arm exists in the closed
    vocab). Excluded.

NEW DEDICATED MODULE (not added to ``tests/test_trajectory_parity.py``
nor the batch_a / batch_b / batch_c / batch_d / batch_e / batch_f /
batch_g / batch_h / batch_i / batch_j / batch_k / batch_l /
spell_card_bridge_admitted / warp_admitted / warp_combat_interaction
modules nor the 6 ``test_audit_safe_trigger_*`` tests — those are
owned/protected; this module avoids all collision and touches no
STALENESS-SENTINEL). Registration in
``scripts/measure_pool_parity.PROBE_MODULES`` is the orchestrator's
separate wire-in step (per the established G/H/I/J/K/L batch cadence).
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest


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


# ---------------------------------------------------------------------
# Batch-M probe #1 — Scorching Dragonfire (~0 17lands decks; EoE).
#
# Covered (``DealDamageToTargetCreature`` in covered set) + unprobed
# at HEAD. Oracle:
#   "[Instant] {1}{R} — Scorching Dragonfire deals 3 damage to
#    target creature."
# Parser -> ``spell_effect = DealDamageToTargetCreature(amount=3,
#   targets=(TargetSpec(IsCreature()),), optional=False)``.
#
# The ``deal_damage`` bridge arm (cross_engine.py:568) with
# ``target: {"kind": "any_creature"}`` maps to Python's
# ``DealDamageToTargetCreature``. Rust picks the first creature on
# the defender's bf; Python's ``_PickFirstOpponentTargetAgent``
# mirrors that pick exactly (single opponent creature -> forced).
# A vanilla 2/4 creature is seated on p1's bf: 3 damage < 4
# toughness, so the creature SURVIVES with 3 damage counters on
# BOTH engines — an observable non-death state that distinguishes
# this probe from Murder / Final Vengeance (where the victim dies).
# The non-lethal-damage branch is the specific new evidence path
# (vs Impossible Inferno (J, amount=6, lethal) and Winter's
# Intervention (J, amount=2+life-gain, sequence)).
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_scorching_dragonfire_deal_3_damage_to_creature_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Scorching Dragonfire
    (~0 17lands decks; genuine EoE covered card). Batch-M covered->PROBED.**

    Python: the ACTUAL parsed Scorching Dragonfire printing on a
    ``StackItem`` with the chosen creature target. Rust: the bridged
    ``{"kind":"deal_damage","amount":3,"target":{"kind":"any_creature"}}``
    synthetic Instant (AnyCreature first-slice picker -> p1 bf[0]).

    A 2/4 creature on p1's bf takes 3 non-lethal damage and survives
    (3 < 4 toughness). The observable: creature remains on bf with 3
    damage counters on BOTH engines, distinguishing this probe from the
    lethal-damage branch exercised by Impossible Inferno (batch J,
    amount=6). Lives are unchanged on BOTH. The ``deal_damage`` arm is
    the SAME bridge arm as Impossible Inferno but with a different
    amount and non-lethal outcome.

    Assertion strength: **full ``compare_fields``** over the whole
    cross-engine field view (2/4 still on p1's battlefield with 3
    damage; no graveyard movement; lives unchanged on BOTH).
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

    real = get_active_source().get_printings().get("Scorching Dragonfire")
    if real is None:
        pytest.skip("Scorching Dragonfire absent from active CardSource")
    assert "Instant" in real.card_types
    se = real.spell_effect
    assert isinstance(se, DealDamageToTargetCreature), (
        f"genuine Scorching Dragonfire spell_effect must be "
        f"DealDamageToTargetCreature; got {type(se).__name__}"
    )
    assert se.amount == 3, (
        f"Scorching Dragonfire must deal 3 damage; got {se.amount}"
    )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2  # ZONE_BATTLEFIELD

    # p1 has a single 2/4 creature. 3 damage < 4 toughness -> survives.
    # Observables: creature remains on bf with 3 damage counters on BOTH.
    py_vic = py.new_object(
        CardPrinting(
            name="SD Victim", mana_cost_str="",
            mana_cost=ManaCost(generic=0), type_line="Creature",
            supertypes=(), card_types=("Creature",), subtypes=(),
            power=2, toughness=4, produces=frozenset(),
        ),
        owner_id=1, zone=Zone.BATTLEFIELD,
    )
    py_vic.summoning_sick = False
    py.battlefield.append(py_vic)
    py.players[0].agent = _PickFirstOpponentTargetAgent()

    rs_vic_id = rs.register_and_inject_object(
        {"name": "SD Victim", "card_types": ["Creature"],
         "power": 2, "toughness": 4}, 1, ZB,
    )

    # ---- Python: genuine parsed Scorching Dragonfire on a StackItem,
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
    assert py_vic in py.battlefield, (
        "SD Victim (2/4) must survive 3 non-lethal damage (Python)"
    )
    assert py_vic.damage == 3, (
        f"SD Victim must have 3 damage counters (Python); "
        f"got {py_vic.damage}"
    )

    # ---- Rust: bridged deal_damage any_creature(3) synthetic Instant. ----
    rs_spell_id = rs.register_and_inject_object(
        {"name": "Scorching Dragonfire", "card_types": ["Instant"],
         "effects": [{"kind": "deal_damage", "amount": 3,
                      "target": {"kind": "any_creature"}}]},
        0, 0,  # controller p0, ZONE_HAND
    )
    rs.push_to_stack(rs_spell_id, 0)
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0

    rs_vic_state = next(
        (e for e in rs.battlefield_snapshot() if e["id"] == rs_vic_id),
        None,
    )
    assert rs_vic_state is not None, (
        "SD Victim (2/4) must survive 3 non-lethal damage (Rust)"
    )
    assert rs_vic_state.get("damage", 0) == 3, (
        f"SD Victim must have 3 damage (Rust); "
        f"got {rs_vic_state.get('damage', 0)}"
    )

    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Scorching Dragonfire deal-3-to-creature must be byte-equal "
        f"across the WHOLE field view on BOTH; diffs={diffs}"
    )


# ---------------------------------------------------------------------
# Batch-M probe #2 — Untimely Malfunction (~0 17lands decks; EoE).
#
# Covered (``DestroyTargetArtifact`` in covered set) + unprobed at
# HEAD. Oracle:
#   "[Instant] {2}{B} — Destroy target artifact."
# Parser -> ``spell_effect = DestroyTargetArtifact(targets=(
#   TargetSpec(IsArtifact()),))``.
#
# The ``destroy_target_artifact`` bridge arm (cross_engine.py:4542)
# maps to Python's ``DestroyTargetArtifact``. Rust scans BOTH players'
# battlefield in ETB-timestamp order (``bf_iter_etb_sorted``) and picks
# the first non-indestructible Artifact. A vanilla artifact is seated
# on p1's bf only; Rust picks it first (no p0 artifacts); Python's
# StackItem carries the same target pre-chosen (``("artifact", id)``).
# The artifact is destroyed to p1's graveyard on BOTH engines. This
# probe pins the ``DestroyTargetArtifact`` covered Effect + the
# ``destroy_target_artifact`` bridge arm byte-equal end-to-end —
# distinct from Murder/Final Vengeance (creature filter) and from
# the ``destroy_target`` arm (creature/player filter).
# Deck count is 0 in the 17lands draft pool but the card is a genuine
# EoE pool member and genuinely covered-by-construction.
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_untimely_malfunction_destroy_target_artifact_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Untimely Malfunction
    (~0 17lands decks; genuine EoE covered card). Batch-M covered->PROBED.**

    Python: the ACTUAL parsed Untimely Malfunction printing on a
    ``StackItem`` with the chosen artifact target. Rust: the bridged
    ``{"kind":"destroy_target_artifact"}`` synthetic Instant (ETB-order
    all-bf scan picks p1's lone artifact).

    A vanilla 2/2 Artifact Creature is seated on p1's bf. Both engines
    destroy it: the artifact leaves the battlefield to p1's graveyard on
    BOTH. This pins the ``DestroyTargetArtifact`` covered Effect +
    ``destroy_target_artifact`` bridge arm end-to-end — the first real-
    EoE probe of the artifact-destroy shape (distinct from the creature-
    destroy probes in batches G/J).

    Assertion strength: **full ``compare_fields``** over the whole
    cross-engine field view (artifact destroyed -> p1 graveyard on BOTH;
    battlefield empty; lives unchanged on BOTH).
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
    from mtg_bot.effects.generic.destroy import DestroyTargetArtifact
    from mtg_bot.cards.base import CardPrinting, ManaCost

    real = get_active_source().get_printings().get("Untimely Malfunction")
    if real is None:
        pytest.skip("Untimely Malfunction absent from active CardSource")
    assert "Instant" in real.card_types
    se = real.spell_effect
    assert isinstance(se, DestroyTargetArtifact), (
        f"genuine Untimely Malfunction spell_effect must be "
        f"DestroyTargetArtifact; got {type(se).__name__}"
    )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2  # ZONE_BATTLEFIELD

    # p1 has a single vanilla Artifact Creature (2/2) — the artifact
    # target on BOTH. Rust scans BOTH sides ETB order; p0 has no
    # artifacts, so Rust picks p1's artifact first.
    py_vic = py.new_object(
        CardPrinting(
            name="UM Victim", mana_cost_str="",
            mana_cost=ManaCost(generic=0),
            type_line="Artifact Creature",
            supertypes=(), card_types=("Artifact", "Creature"),
            subtypes=(), power=2, toughness=2, produces=frozenset(),
        ),
        owner_id=1, zone=Zone.BATTLEFIELD,
    )
    py_vic.summoning_sick = False
    py.battlefield.append(py_vic)
    # No agent override needed: the StackItem target is pre-specified;
    # Python re-verifies at resolve time (IsArtifact filter passes).

    rs_vic_id = rs.register_and_inject_object(
        {"name": "UM Victim", "card_types": ["Artifact", "Creature"],
         "power": 2, "toughness": 2}, 1, ZB,
    )

    # ---- Python: genuine parsed Untimely Malfunction on a StackItem,
    # controller p0, chosen target = p1's Artifact Creature. ----
    py_spell = py.new_object(real, owner_id=0, zone=Zone.STACK)
    py_spell.summoning_sick = False
    py.stack.append(
        StackItem(source=py_spell, controller_id=0,
                  targets=(("artifact", py_vic.id),))
    )
    resolve_top_of_stack(py)
    py_sba(py)
    assert len(py.stack) == 0
    assert py_vic not in py.battlefield, (
        "UM Victim must be destroyed, not on bf (Python)"
    )
    assert py_vic in py.players[1].graveyard, (
        "UM Victim must be in p1 graveyard after artifact destroy (Python)"
    )

    # ---- Rust: bridged destroy_target_artifact synthetic Instant. ----
    rs_spell_id = rs.register_and_inject_object(
        {"name": "Untimely Malfunction", "card_types": ["Instant"],
         "effects": [{"kind": "destroy_target_artifact"}]},
        0, 0,  # controller p0, ZONE_HAND
    )
    rs.push_to_stack(rs_spell_id, 0)
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0

    rs_alive = any(e["id"] == rs_vic_id
                   for e in rs.battlefield_snapshot())
    assert rs_alive is False, (
        f"UM Victim must be destroyed on Rust side; "
        f"bf={[e['printing_name'] for e in rs.battlefield_snapshot()]}"
    )

    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Untimely Malfunction destroy-artifact must be byte-equal "
        f"across the WHOLE field view on BOTH; diffs={diffs}"
    )


# ---------------------------------------------------------------------
# Batch-M probe #3 — Turn Inside Out (~0 17lands decks; EoE).
#
# Covered (``PumpTargetCreatureUntilEOT`` in covered set) + unprobed
# at HEAD. Oracle:
#   "[Instant] {G} — Target creature gets +3/+0 until end of turn."
# Parser -> ``spell_effect = PumpTargetCreatureUntilEOT(
#   power_bonus=3, toughness_bonus=0, granted_keywords=frozenset(),
#   you_control_only=False, opponents_only=False, ...)``.
#
# The ``pump_target_creature_until_eot`` bridge arm (cross_engine.py:
# 1064) maps ``power_bonus`` / ``toughness_bonus`` fields directly.
# Turn Inside Out has ZERO granted keywords — the clean PT-only form
# of ``PumpTargetCreatureUntilEOT``. Rust picks the first creature on
# the SOURCE CONTROLLER's battlefield (p0's side). Python's
# ``_PickFirstControlledCreatureAgent`` mirrors that pick exactly.
# A 2/2 creature is seated on p0's bf: +3/+0 UEOT makes it
# effectively 5/2 before cleanup on BOTH engines. The UEOT modifier
# persists (we do NOT drive cleanup in this probe — the
# effective-P/T getter reads the modifier directly). The ``granted_
# keywords=frozenset()`` ensures NO bridge keyword gap fires.
# Deck count is 0 in the 17lands draft pool but the card is a genuine
# EoE pool member and genuinely covered-by-construction.
#
# NOTE on ``you_control_only=False``: Turn Inside Out has no "target
# creature you control" restriction in the oracle text ("target
# creature" — unrestricted). However, Rust's bridge arm ALWAYS scans
# the SOURCE CONTROLLER's bf (state_ops_resolve.rs:3927-3988). The
# probe constrains p1's bf to zero creatures, so both engines pick
# the SAME p0 creature unambiguously. This mirrors the Dubious Delicacy
# ETB probe design (test_parity_smoke.py:16273) and the
# ``_PickFirstControlledCreatureAgent`` shim's documented usage.
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_turn_inside_out_pump_3_plus0_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Turn Inside Out
    (~0 17lands decks; genuine EoE covered card). Batch-M covered->PROBED.**

    Python: the ACTUAL parsed Turn Inside Out printing on a ``StackItem``
    with the chosen creature target. Rust: the bridged
    ``{"kind":"pump_target_creature_until_eot","power_bonus":3,
    "toughness_bonus":0}`` synthetic Instant (controller-bf first-
    creature scan -> p0 bf[0]).

    A 2/2 creature on p0's bf receives +3/+0 UEOT; effective power
    becomes 5 (2+3) on BOTH engines, toughness unchanged at 2. The
    UEOT modifier persists through the probe (cleanup not driven).
    Turn Inside Out is the keyword-free variant of
    ``PumpTargetCreatureUntilEOT`` — ``granted_keywords=frozenset()``
    — so no bridge keyword gap fires. This is the first real-EoE probe
    of the ``pump_target_creature_until_eot`` arm as a SPELL (prior
    probes: Dubious Delicacy ETB trigger in test_parity_smoke.py).

    Assertion strength: **full ``compare_fields``** over the whole
    cross-engine field view (p0 2/2 creature has effective_power 5 on
    BOTH; battlefield occupied on BOTH; lives unchanged on BOTH).
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
    from mtg_bot.effects.generic.pump import PumpTargetCreatureUntilEOT
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.game import effective_power as py_effective_power
    from tests.parity._picker_shims import _PickFirstControlledCreatureAgent

    real = get_active_source().get_printings().get("Turn Inside Out")
    if real is None:
        pytest.skip("Turn Inside Out absent from active CardSource")
    assert "Instant" in real.card_types
    se = real.spell_effect
    assert isinstance(se, PumpTargetCreatureUntilEOT), (
        f"genuine Turn Inside Out spell_effect must be "
        f"PumpTargetCreatureUntilEOT; got {type(se).__name__}"
    )
    assert se.power_bonus == 3, (
        f"Turn Inside Out must grant +3 power; got {se.power_bonus}"
    )
    assert se.toughness_bonus == 0, (
        f"Turn Inside Out must grant +0 toughness; got {se.toughness_bonus}"
    )
    assert se.granted_keywords == frozenset(), (
        f"Turn Inside Out must have no granted keywords; "
        f"got {se.granted_keywords}"
    )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2  # ZONE_BATTLEFIELD

    # p0 has a single 2/2 creature (the pump target).
    # p1's bf is empty — no creatures — so Rust's source-controller scan
    # and Python's _PickFirstControlledCreatureAgent both pick p0's bear
    # unambiguously.
    py_bear = py.new_object(
        CardPrinting(
            name="TIO Bear", mana_cost_str="",
            mana_cost=ManaCost(generic=0), type_line="Creature",
            supertypes=(), card_types=("Creature",), subtypes=(),
            power=2, toughness=2, produces=frozenset(),
        ),
        owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_bear.summoning_sick = False
    py.battlefield.append(py_bear)
    py.players[0].agent = _PickFirstControlledCreatureAgent()

    rs_bear_id = rs.register_and_inject_object(
        {"name": "TIO Bear", "card_types": ["Creature"],
         "power": 2, "toughness": 2}, 0, ZB,
    )

    # ---- Python: genuine parsed Turn Inside Out on a StackItem,
    # controller p0, chosen target = p0's own creature. ----
    py_spell = py.new_object(real, owner_id=0, zone=Zone.STACK)
    py_spell.summoning_sick = False
    py.stack.append(
        StackItem(source=py_spell, controller_id=0,
                  targets=(("creature", py_bear.id),))
    )
    resolve_top_of_stack(py)
    py_sba(py)
    assert len(py.stack) == 0
    assert py_bear in py.battlefield, (
        "TIO Bear must survive after +3/+0 pump (Python)"
    )
    # Effective power = printed 2 + UEOT bonus 3 = 5.
    eff_power = py_effective_power(py, py_bear)
    assert eff_power == 5, (
        f"TIO Bear effective power must be 5 after +3/+0 (Python); "
        f"got {eff_power}"
    )

    # ---- Rust: bridged pump_target_creature_until_eot(+3/+0)
    # synthetic Instant. ----
    rs_spell_id = rs.register_and_inject_object(
        {"name": "Turn Inside Out", "card_types": ["Instant"],
         "effects": [{"kind": "pump_target_creature_until_eot",
                      "power_bonus": 3, "toughness_bonus": 0}]},
        0, 0,  # controller p0, ZONE_HAND
    )
    rs.push_to_stack(rs_spell_id, 0)
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0

    rs_bear_state = next(
        (e for e in rs.battlefield_snapshot() if e["id"] == rs_bear_id),
        None,
    )
    assert rs_bear_state is not None, (
        "TIO Bear must remain on Rust bf after +3/+0 pump (Rust)"
    )
    rs_eff_power = rs.effective_power(rs_bear_id)
    assert rs_eff_power == 5, (
        f"TIO Bear effective power must be 5 after +3/+0 (Rust); "
        f"got {rs_eff_power}"
    )

    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Turn Inside Out pump-3-plus-0 must be byte-equal "
        f"across the WHOLE field view on BOTH; diffs={diffs}"
    )
