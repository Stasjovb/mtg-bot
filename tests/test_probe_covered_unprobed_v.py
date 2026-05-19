"""Genuine real-EoE cross-engine byte-equality probes — batch V.

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

PARTITION DISCIPLINE (batch V — SORCERY round 6, after G + J + M + P + S)
---------------------------------------------------------------------------
This module is batch V, the sixth round of SORCERY (and trivially-
resolving INSTANT) covered-but-unprobed probes, extending the sorcery
lane after batches G (Scrounge for Eternity / Pyroclasm / Final
Vengeance), J (Murder / Impossible Inferno / Midnight Mayhem /
Winter's Intervention), M (Scorching Dragonfire / Untimely
Malfunction / Turn Inside Out), P (Don't Make a Sound / Commune with
Evil / Trial of Agony), and S (Drag to the Roots / Emerge from the
Cocoon / Glimmerburst). Sibling agents W (activated-abilities round 4)
and X (ATTACKS/LEAVES_BATTLEFIELD triggers) run in parallel worktrees.
The covered-by-construction-but-unprobed list (computed read-only via
``scripts/measure_pool_parity.classify_pool``, sorted by 17lands deck
count desc) was verify-first-recomputed at live HEAD 48f8bd13; every
card below is (a) covered-by-construction, (b) NOT individually probed,
(c) NOT in any sibling batch, (d) an Instant or Sorcery with a
``spell_effect`` that resolves directly with no creature-trigger
involvement.

**LANE STATUS: NEAR EXHAUSTION.**  After six rounds the sorcery
covered-but-unprobed Instant/Sorcery pool has narrowed to a single
clean card (``Cerebral Download``). Every remaining covered spell
either (a) duplicates an already-PROBED effect shape (Murder family),
(b) carries a known-gap bridge arm (ManifestDread, GrantUnblockableUEOT
→ class mismatch, TargetOpponentDiscardsCasterChoice, SearchLibraryFor
Card, OptionalSacArtifactForEffect, OwnerPutsTargetArtifactOrCreature
OnTopOrBottomOfLibrary, or_enchantment rider on destroy_target,
two-slot DiplomaticRelations via push_to_stack, or_enchantment on
Withering Torment), or (c) has a compound cost-reduction rider
(Dark Endurance — costs {1} less if targets a blocking creature) that
falls outside the sorcery-lane scope. The two ``Cerebral Download``
probes below (0-artifact and 2-artifact) together close the last
genuinely clean covered Instant/Sorcery in the EoE pool and constitute
the complete deliverable for this round.

The 1 card pinned here (deck counts from ``data/17lands/
eoe_decks.json.gz`` at verify-first walk):

  1. Cerebral Download  (~0 17lands decks) — Instant,
     Sequence(SurveilXEqualToArtifactCount, DrawCards(3)).
     Two probes: the 0-artifact arm (surveil no-op, pure draw-3
     observable) and the 2-artifact arm (surveil keeps 2 top cards,
     then draw-3). The ``surveil_x_equal_to_artifact_count`` +
     ``draw_cards`` Sequence path was previously only exercised via a
     SYNTHETIC ``cd_printing`` in ``test_parity_smoke.py`` (function
     ``test_cross_engine_cerebral_download_real_eoe_cast_xfails_on_
     sequence_surveil_then_draw``, which does NOT match the ``*_parity``
     naming convention and does NOT call ``compare_fields``). These
     probes are the FIRST genuine real-EoE byte-equality probes for
     Cerebral Download, using the ACTUAL parsed printing from
     ``get_active_source()`` and asserting full ``compare_fields == []``.

DROPPED-ON-VERIFY (honest verify-first discipline):

  * **Come Back Wrong / Seized from Slumber / Unwanted Remake** —
    all parse to ``DestroyTargetCreature(draw_if_undamaged_amount=0)``
    — the same effect shape as Murder (batch J). Low marginal value;
    the ``destroy_target`` arm is already PROBED-level evidence via
    Murder. Excluded per batch-S drop documentation.
  * **Withering Torment** — ``Sequence(DestroyTargetCreature(
    or_enchantment=True), LoseLife(2))``. The ``destroy_target`` bridge
    arm only supports ``any_creature`` filter and does NOT plumb the
    ``or_enchantment`` rider. Excluded per batch-S drop documentation.
  * **Temporal Intervention** — ``TargetOpponentDiscardsCasterChoice``
    (the CASTER picks which card the opponent discards). The
    ``discard_card`` bridge arm maps to ``TargetOpponentDiscards``
    (the DISCARDER picks). Excluded per batch-S drop documentation.
  * **Diplomatic Relations** — ``DiplomaticRelationsEffect()``. Rust's
    ``push_to_stack`` API only seats ``target_obj_id_2 = None`` (Phase-1
    single-target contract); the 2-slot target binding required by
    ``DiplomaticRelationsEffect`` cannot go through the synthetic
    ``push_to_stack`` probe idiom. Excluded per batch-S drop
    documentation.
  * **Manifest Dread / Under the Skin / Break Down the Door /
    Unnerving Grasp** — all contain ``ManifestDread``. The
    ManifestDread bridge is a bridge-defer (no ``manifest_dread``
    bridge arm exists in the closed vocab). Excluded per batch-S drop
    documentation.
  * **Dual-Sun Technique / Give In to Violence / Dark Endurance /
    Jump Scare / Horrid Vigor / Rig for War / Violent Urge** — all
    ``PumpTargetCreatureUntilEOT`` with non-empty ``granted_keywords``
    rider. The ``pump_target_creature_until_eot`` bridge arm does NOT
    plumb ``granted_keywords`` into the dict shape; the
    ``grant_keyword_to_target_creature_until_eot`` arm handles only
    the keyword (no P/T bonus), so neither arm round-trips the
    combined pump+keyword shape. Excluded per batch-M/S drop
    documentation.
  * **Enter the Enigma** — ``Sequence(GrantUnblockableUEOT,
    DrawCards(1))``. The ``grant_keyword_to_target_creature_until_eot``
    bridge arm returns ``PumpTargetCreatureUntilEOT(granted_keywords=
    {"unblockable"})`` while the Python printing carries
    ``GrantUnblockableUEOT`` — a genuinely different class; the bridge
    is ``covered`` (``GrantUnblockableUEOT`` is in the covered-class
    set) but the class mismatch is documented in batch drops as
    ``grant_keyword_to_target_creature_until_eot returns wrong class``.
    Excluded.
  * **Let's Play a Game / Split Up** — Modal cards. Lane U (modal+
    counter-spell partition). Excluded from this (sorcery) lane.
  * **Demonic Counsel** — ``SearchLibraryForCard``. SearchLibrary
    bridge-defer documented in prior batches. Excluded.
  * **Lithobraking** — ``Sequence(CreateToken(Lander, 1),
    OptionalSacArtifactForEffect(inner_effect=DealNDamageToEachCreature
    (2)))``. ``OptionalSacArtifactForEffect`` is a known-gap bridge arm
    excluded from prior batches. Excluded.
  * **Vanish from Sight** — ``Sequence(
    OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary(
    nonland_permanent=True), Surveil(1))``.
    ``OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary`` is a
    known-gap class excluded from prior batches (divergence documented
    in batch-S drop section). Excluded.

NEW DEDICATED MODULE (not added to ``tests/test_trajectory_parity.py``
nor the batch_a / batch_b / batch_c / batch_d / batch_e / batch_f /
batch_g / batch_h / batch_i / batch_j / batch_k / batch_l /
spell_card_bridge_admitted / warp_admitted / warp_combat_interaction
modules nor the 6 ``test_audit_safe_trigger_*`` tests — those are
owned/protected; this module avoids all collision and touches no
STALENESS-SENTINEL). Registration in
``scripts/measure_pool_parity.PROBE_MODULES`` is the orchestrator's
separate wire-in step (per the established G/H/I/J/K/L/M/P/S batch
cadence).
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
# Batch-V probe #1 — Cerebral Download, 0-artifact arm (~0 17lands
# decks; EoE).
#
# Covered (``Sequence``, ``Surveil(use_artifact_count=True)`` via
# ``SurveilXEqualToArtifactCount``, and ``DrawCards`` all in covered
# set) + unprobed at HEAD (the existing parity_smoke test uses a
# SYNTHETIC ``CardPrinting`` on the Python side, does NOT call
# ``compare_fields``, and uses function name
# ``test_cross_engine_cerebral_download_real_eoe_cast_xfails_on_
# sequence_surveil_then_draw`` which does NOT match the ``*_parity``
# naming convention required by ``genuine_probed_cards``). Oracle:
#   "[Instant] {1}{U} — Surveil X, where X is the number of artifacts
#    you control. Then draw three cards."
# Parser -> ``spell_effect = Sequence(effects=(
#   Surveil(amount=1, use_artifact_count=True), DrawCards(amount=3)))``.
#
# The ``surveil_x_equal_to_artifact_count`` bridge arm (cross_engine.py,
# round-34 BLOCKED-RUST-EFFECT slice) constructs
# ``Surveil(use_artifact_count=True)``. Rust's resolve computes
# ``X = artifact_count_on_source_controller_bf`` at resolve time;
# Python's ``Surveil.resolve`` computes the same count via
# ``sum(1 for o in state.battlefield if o.controller_id == controller_id
# and o.printing.is_artifact)``. Both engines agree on X for any
# controlled bf state.
#
# **Round-36 Sequence-loop in-loop auto-resolve fix (prerequisite).**
# Prior to this fix Rust's ``Sequence::apply_effect`` drained
# ``PendingDecision::SurveilChoice`` only AFTER the full effects fan-out
# completed, meaning ``DrawCards`` fired from the post-pop shortened
# library (before Surveil's auto-drain re-inserted the surveiled cards).
# After the fix, ``auto_resolve_pending(state, "keep_all_on_top")``
# fires INSIDE the loop AFTER each child effect resolves. Surveil's
# PendingDecision is drained immediately before DrawCards runs, so
# DrawCards sees the same library top as Python's no-agent short-circuit
# path (which never mutates the library at all). Both engines now agree
# on the draw contents. The fix is confirmed by the existing
# ``test_cross_engine_cerebral_download_real_eoe_cast_xfails_on_
# sequence_surveil_then_draw`` test (which now passes at HEAD).
#
# Probe shape (0-artifact arm — simplest clean observable):
#
#   p0's library is seeded with 3 "CD Filler" 1/1 creatures via
#   DeckSpec. No artifacts on either bf. p0 casts the GENUINE parsed
#   "Cerebral Download". The spell resolves:
#     * SurveilX(X=0): no-op on both engines (zero artifacts).
#     * DrawCards(3): p0 draws all 3 fillers; library is now empty.
#   Cerebral Download routes to p0's graveyard. Lives unchanged.
#
#   Rust side: synthetic Sequence([surveil_x_equal_to_artifact_count,
#   draw_cards count=3]) carrier injected to p0's HAND and pushed.
#
# Observable (0-artifact arm): p0 hand = 3 fillers, p0 library = 0,
# spell in p0's graveyard, p1 unchanged, lives unchanged on BOTH.
# Full compare_fields byte-equal.
#
# This is the FIRST genuine real-EoE byte-equality probe for
# ``Cerebral Download`` with the ACTUAL parsed printing and full
# ``compare_fields`` assertion.
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_cerebral_download_surveil_x_zero_artifacts_draw_3_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Cerebral Download,
    0-artifact arm (~0 17lands decks; genuine EoE covered card).
    Batch-V covered->PROBED.**

    Python: the ACTUAL parsed "Cerebral Download" printing on a
    ``StackItem`` (no target — Instant resolves via p0 controller).
    Rust: the bridged ``{"kind":"sequence","effects":[
    {"kind":"surveil_x_equal_to_artifact_count"},
    {"kind":"draw_cards","count":3}]}`` synthetic Instant.

    p0's library is seeded with 3 "CD Filler" 1/1 creatures via DeckSpec.
    No artifacts on either battlefield. SurveilX fires with X=0 (no-op
    on both engines). DrawCards(3) draws all 3 fillers; p0's library is
    empty post-resolve. Cerebral Download routes to p0's graveyard.
    Lives unchanged.

    Assertion strength: **full ``compare_fields``** over the whole
    cross-engine field view (p0 hand = 3 fillers, p0 library = 0,
    spell in p0's GY, both stacks empty, p1 unchanged, lives
    unchanged on BOTH).
    """
    from mtg_bot.parity.cross_engine import (
        CardDef, DeckSpec, build_python_state, build_rust_state,
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.game import StackItem, Zone
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.combinators import Sequence
    from mtg_bot.effects.generic.library_lookat import Surveil
    from mtg_bot.effects.generic.draw_mill import DrawCards

    real = get_active_source().get_printings().get("Cerebral Download")
    if real is None:
        pytest.skip("Cerebral Download absent from active CardSource")
    assert "Instant" in real.card_types
    se = real.spell_effect
    assert isinstance(se, Sequence), (
        f"genuine Cerebral Download spell_effect must be Sequence; "
        f"got {type(se).__name__}"
    )
    assert len(se.effects) == 2
    assert isinstance(se.effects[0], Surveil), (
        f"Cerebral Download first effect must be Surveil; got "
        f"{type(se.effects[0]).__name__}"
    )
    assert se.effects[0].use_artifact_count is True, (
        "Cerebral Download Surveil must have use_artifact_count=True "
        "(SurveilXEqualToArtifactCount shape)"
    )
    assert isinstance(se.effects[1], DrawCards), (
        f"Cerebral Download second effect must be DrawCards; got "
        f"{type(se.effects[1]).__name__}"
    )
    assert se.effects[1].amount == 3, (
        f"Cerebral Download DrawCards must be amount=3; "
        f"got {se.effects[1].amount}"
    )

    # Seed p0's library with 3 filler cards via DeckSpec (identical on
    # both engines by construction — DeckSpec push path).
    filler = CardDef(name="CD Filler", card_type="Creature", power=1, toughness=1)
    spec = DeckSpec(
        card_defs=(filler,),
        p0_library=("CD Filler", "CD Filler", "CD Filler"),
        p1_library=(),
    )
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZH = 0  # ZONE_HAND

    py_lib_before = len(py.players[0].library)  # = 3
    assert py_lib_before == 3, (
        f"DeckSpec must seed 3 fillers in p0's library; got {py_lib_before}"
    )
    py_hand_before = len(py.players[0].hand)    # = 0

    # ---- Python: genuine "Cerebral Download" on a StackItem,
    # controller p0 (Instant — no target). No artifacts on p0's bf:
    # SurveilX(X=0) is a no-op. DrawCards(3) draws all 3 fillers.
    # ----
    py_spell = py.new_object(real, owner_id=0, zone=Zone.STACK)
    py_spell.summoning_sick = False
    py.stack.append(
        StackItem(source=py_spell, controller_id=0, targets=())
    )
    resolve_top_of_stack(py)
    py_sba(py)

    assert len(py.stack) == 0
    # p0 library must be empty (all 3 fillers drawn).
    assert len(py.players[0].library) == 0, (
        f"Cerebral Download (0-art): p0 library must be empty after "
        f"DrawCards(3) (Python); size={len(py.players[0].library)}"
    )
    # p0 hand must have grown by 3.
    assert len(py.players[0].hand) == py_hand_before + 3, (
        f"Cerebral Download (0-art): p0 hand must grow by 3 (Python); "
        f"got {len(py.players[0].hand)}"
    )
    # Cerebral Download routes to p0's graveyard.
    py_p0_gy_names = [o.printing.name for o in py.players[0].graveyard]
    assert "Cerebral Download" in py_p0_gy_names, (
        f"Cerebral Download must be in p0's graveyard (Python); "
        f"got {py_p0_gy_names}"
    )

    # ---- Rust: bridged Sequence(surveil_x_equal_to_artifact_count,
    # draw_cards count=3) synthetic Instant. No artifacts on Rust bf
    # (none injected). The library is seeded with 3 CD Filler cards
    # from build_rust_state(spec). ----
    rs_spell_id = rs.register_and_inject_object(
        {
            "name": "Cerebral Download",
            "card_types": ["Instant"],
            "effects": [
                {
                    "kind": "sequence",
                    "effects": [
                        {"kind": "surveil_x_equal_to_artifact_count"},
                        {"kind": "draw_cards", "count": 3},
                    ],
                }
            ],
        },
        0, ZH,
    )
    rs.push_to_stack(rs_spell_id, 0)
    rs.resolve_top_of_stack()
    rs.apply_sbas()

    assert rs.stack_size() == 0
    assert rs.library_sizes[0] == 0, (
        f"Cerebral Download (0-art): Rust p0 library must be empty "
        f"after DrawCards(3); got {rs.library_sizes[0]}"
    )
    assert rs.hand_sizes[0] == py_hand_before + 3, (
        f"Cerebral Download (0-art): Rust p0 hand must be "
        f"{py_hand_before + 3} (3 drawn); got {rs.hand_sizes[0]}"
    )

    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Cerebral Download surveil-X(0-artifact)/draw-3 must be "
        f"byte-equal across the WHOLE field view on BOTH; diffs={diffs}"
    )


# ---------------------------------------------------------------------
# Batch-V probe #2 — Cerebral Download, 2-artifact arm (~0 17lands
# decks; EoE).
#
# Same card, distinct observable: 2 artifacts on p0's bf so X = 2.
# The ``surveil_x_equal_to_artifact_count`` resolve arm computes X = 2
# on both engines; Surveil(X=2) examines the top 2 cards of p0's
# 5-card library. With no custom agent (the no-agent default-strategy
# contract), both engines keep all examined cards on top in their
# original order (Python's ``if p.agent is None`` short-circuit in
# ``library_lookat.py``; Rust's ``auto_resolve_pending(...,
# "keep_all_on_top")`` drain INSIDE the Sequence loop after the child
# Surveil effect resolves — the round-36 in-loop drain fix). DrawCards(3)
# then draws from the same post-surveil top-3 on both engines. Both
# stacks empty post-resolve.
#
# Library setup: p0's library is seeded with 5 "CD Filler" 1/1
# creatures via DeckSpec. After Surveil(X=2) + DrawCards(3):
#   * Library: 2 fillers remaining (the bottom 2 were not drawn).
#   * Hand: 3 fillers drawn (the top 3, matching what Surveil peeked
#     then kept and DrawCards drew).
#   * p0's bf: 2 "CD Artifact" artifact permanents (inert; seeded for
#     the X computation). Both engines see the same bf objects.
#
# Rust: 2 artifact permanents seeded on p0's bf via
# ``register_and_inject_object`` into ZONE_BATTLEFIELD (zone 2).
# Python: 2 ``CardPrinting`` artifact objects injected into
# ``py.battlefield`` directly (same pattern as batch-S / batch-J
# creature-victim probes).
#
# Observable (2-artifact arm): p0 hand = 3 fillers, p0 library = 2,
# 2 "CD Artifact" objects on p0's bf, spell in p0's graveyard, lives
# unchanged, p1 unchanged on BOTH. Full compare_fields byte-equal.
#
# This is the second probe of ``surveil_x_equal_to_artifact_count``
# in the genuine-real-EoE lane (complementing probe #1's 0-artifact
# no-op path with the X > 0 resolution path).
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_cerebral_download_surveil_x_two_artifacts_draw_3_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Cerebral Download,
    2-artifact arm (~0 17lands decks; genuine EoE covered card).
    Batch-V covered->PROBED (2nd probe).**

    Python: the ACTUAL parsed "Cerebral Download" printing on a
    ``StackItem`` (no target — Instant resolves via p0 controller).
    Rust: the same bridged Sequence([surveil_x_equal_to_artifact_count,
    draw_cards count=3]) synthetic Instant.

    2 "CD Artifact" permanents are seated on p0's battlefield (both
    engines). p0's library is seeded with 5 "CD Filler" 1/1 creatures
    via DeckSpec. The spell resolves:
      * SurveilX(X=2): both engines compute X = artifact count = 2;
        Surveil examines the top 2 fillers and keeps them (no-agent
        default). Library remains 5 fillers deep in original order.
      * DrawCards(3): p0 draws the top 3 fillers; library has 2 remaining.
    Cerebral Download routes to p0's graveyard. Lives unchanged.

    Assertion strength: **full ``compare_fields``** over the whole
    cross-engine field view (p0 hand = 3 fillers, p0 library = 2, 2
    artifact permanents on p0's bf, spell in p0's GY, both stacks empty,
    p1 unchanged, lives unchanged on BOTH).
    """
    from mtg_bot.parity.cross_engine import (
        CardDef, DeckSpec, build_python_state, build_rust_state,
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.game import StackItem, Zone
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.combinators import Sequence
    from mtg_bot.effects.generic.library_lookat import Surveil
    from mtg_bot.effects.generic.draw_mill import DrawCards
    from mtg_bot.cards.base import CardPrinting, ManaCost

    real = get_active_source().get_printings().get("Cerebral Download")
    if real is None:
        pytest.skip("Cerebral Download absent from active CardSource")
    assert "Instant" in real.card_types
    se = real.spell_effect
    assert isinstance(se, Sequence), (
        f"genuine Cerebral Download spell_effect must be Sequence; "
        f"got {type(se).__name__}"
    )
    assert se.effects[0].use_artifact_count is True, (
        "Cerebral Download Surveil must have use_artifact_count=True"
    )
    assert se.effects[1].amount == 3, (
        f"Cerebral Download DrawCards must be amount=3; "
        f"got {se.effects[1].amount}"
    )

    # Seed p0's library with 5 filler cards via DeckSpec.
    filler = CardDef(name="CD Filler", card_type="Creature", power=1, toughness=1)
    spec = DeckSpec(
        card_defs=(filler,),
        p0_library=(
            "CD Filler", "CD Filler", "CD Filler",
            "CD Filler", "CD Filler",
        ),
        p1_library=(),
    )
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZH = 0   # ZONE_HAND
    ZB = 2   # ZONE_BATTLEFIELD

    assert len(py.players[0].library) == 5, (
        "DeckSpec must seed 5 fillers in p0's library"
    )
    py_hand_before = len(py.players[0].hand)   # = 0

    # ---- Python: seat 2 artifact permanents on p0's bf (the X count).
    # Minimal artifact printing — Artifact type, no power/toughness. ----
    artifact_printing = CardPrinting(
        name="CD Artifact", mana_cost_str="",
        mana_cost=ManaCost(generic=0), type_line="Artifact",
        supertypes=(), card_types=("Artifact",), subtypes=(),
        power=None, toughness=None, produces=frozenset(),
    )
    for _ in range(2):
        art = py.new_object(artifact_printing, owner_id=0, zone=Zone.BATTLEFIELD)
        art.summoning_sick = False
        py.battlefield.append(art)

    # ---- Python: genuine "Cerebral Download" on a StackItem. ----
    py_spell = py.new_object(real, owner_id=0, zone=Zone.STACK)
    py_spell.summoning_sick = False
    py.stack.append(
        StackItem(source=py_spell, controller_id=0, targets=())
    )
    resolve_top_of_stack(py)
    py_sba(py)

    assert len(py.stack) == 0
    # SurveilX(X=2) + DrawCards(3): 3 drawn, 2 remaining.
    assert len(py.players[0].library) == 2, (
        f"Cerebral Download (2-art): p0 library must have 2 remaining "
        f"after Surveil+DrawCards (Python); got {len(py.players[0].library)}"
    )
    assert len(py.players[0].hand) == py_hand_before + 3, (
        f"Cerebral Download (2-art): p0 hand must grow by 3 (Python); "
        f"got {len(py.players[0].hand)}"
    )
    # Artifacts remain on the bf (they were not affected by the spell).
    py_art_on_bf = [
        o for o in py.battlefield if o.printing.name == "CD Artifact"
    ]
    assert len(py_art_on_bf) == 2, (
        f"Cerebral Download (2-art): 2 CD Artifact objects must remain "
        f"on Python p0's bf; got {len(py_art_on_bf)}"
    )
    # Cerebral Download routes to p0's graveyard.
    py_p0_gy_names = [o.printing.name for o in py.players[0].graveyard]
    assert "Cerebral Download" in py_p0_gy_names, (
        f"Cerebral Download must be in p0's graveyard (Python); "
        f"got {py_p0_gy_names}"
    )

    # ---- Rust: seat 2 artifacts on p0's bf. ----
    for _ in range(2):
        rs.register_and_inject_object(
            {"name": "CD Artifact", "card_types": ["Artifact"]},
            0, ZB,
        )

    rs_spell_id = rs.register_and_inject_object(
        {
            "name": "Cerebral Download",
            "card_types": ["Instant"],
            "effects": [
                {
                    "kind": "sequence",
                    "effects": [
                        {"kind": "surveil_x_equal_to_artifact_count"},
                        {"kind": "draw_cards", "count": 3},
                    ],
                }
            ],
        },
        0, ZH,
    )
    rs.push_to_stack(rs_spell_id, 0)
    rs.resolve_top_of_stack()
    rs.apply_sbas()

    assert rs.stack_size() == 0
    assert rs.library_sizes[0] == 2, (
        f"Cerebral Download (2-art): Rust p0 library must have 2 "
        f"remaining after Surveil+DrawCards; got {rs.library_sizes[0]}"
    )
    assert rs.hand_sizes[0] == py_hand_before + 3, (
        f"Cerebral Download (2-art): Rust p0 hand must be "
        f"{py_hand_before + 3} (3 drawn); got {rs.hand_sizes[0]}"
    )
    rs_art_on_bf = [
        e for e in rs.battlefield_snapshot()
        if e["printing_name"] == "CD Artifact"
    ]
    assert len(rs_art_on_bf) == 2, (
        f"Cerebral Download (2-art): 2 CD Artifact objects must remain "
        f"on Rust p0's bf; got {len(rs_art_on_bf)}"
    )

    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Cerebral Download surveil-X(2-artifact)/draw-3 must be "
        f"byte-equal across the WHOLE field view on BOTH; diffs={diffs}"
    )
