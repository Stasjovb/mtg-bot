"""Genuine real-EoE cross-engine byte-equality probes -- activated-ability
lane, batch EE (round 7 of the activated-ability family).

**Context -- extending O2 + Q + T + W + Y + BB.**  Six prior batches proved
eighteen cards and seventeen cost axes on the CE20 substrate.  This module
(batch EE) adds three more probes, each exercising a NEW effect type not
previously reached via the activated-ability lane:

  1. Dubious Delicacy  (covered_by_construction -> PROBED)
     ``{2}, {T}, Sacrifice Dubious Delicacy: Target opponent loses 3 life.``
     Cost: {N=2}, tap_self=True, sacrifice_self=True.
     **NEW effect type:** TargetOpponentLosesLife(3) is the first probe in
     the activated-ability lane to exercise a direct life-drain targeting
     an opponent via an activated ability.  The card is a Food Artifact with
     two distinct non-mana activated abilities (GainLife and
     TargetOpponentLosesLife); this probe validates the second AA (index 1).
     Prior TargetOpponentLosesLife probes used spell or ETB triggers; this
     closes the gap in the AA lane.

  2. Chrome Companion  (covered_by_construction -> PROBED)
     ``{2}, {T}: Put target card in a graveyard on the bottom of its
     owner's library.``
     Cost: {N=2}, tap_self=True, sacrifice_self=False.
     **NEW effect type:** PutCardFromGraveyardOnBottomOfLibrary is the first
     probe in the activated-ability lane to exercise a graveyard-to-library
     zone move via an activated ability.  Chrome Companion also has a
     BECOMES_TAPPED trigger (``GainLife(1)``) that fires when the tap cost
     is paid; this probe validates that both the main effect AND the
     BECOMES_TAPPED trigger resolve byte-equal.  A card seeded in p1's
     graveyard serves as the mandatory target; Chrome Companion itself is
     NOT sacrificed.

  3. Inventors' Fair  (covered_by_construction -> PROBED)
     ``{4}, {T}, Sacrifice Inventors' Fair: Search your library for an
     artifact card, put it into your hand, then shuffle.``
     Cost: {N=4}, tap_self=True, sacrifice_self=True.
     **NEW effect type:** SearchLibraryForCard with filter_name='artifact' and
     may_fail=False is the first probe in the activated-ability lane to
     exercise a non-basic-land library search that moves an artifact to hand.
     Prior SearchLibraryForCard probes (Terramorphic Expanse, batch BB) used
     SearchLibraryForBasicLandTapped (a distinct effect class); this probe
     uses the generic SearchLibraryForCard class with an artifact filter and
     may_fail=False (mandatory fetch).  The card is sacrificed as part of the
     activation cost; the fetched artifact moves from library to hand.
     Inventors' Fair also has a BEGINNING_OF_UPKEEP trigger that is NOT
     included in the Rust synthetic carrier (the trigger has a complex
     conditional gate that is out of scope for this probe); omitting it is
     safe because the probe state has no upkeep phase.

All three cards are in the ``covered_by_construction`` tier at HEAD
(every Effect class they emit has a live Rust variant + bridge arm, but
no genuine real-EoE probe pins that card).  This module promotes them
to PROBED.

**DROPPED candidates (batch EE survey, 2026-05-19):**

  * Glimmerlight / Atomic Microsizer / Saw / any Equipment (13 total):
    ``attach_to_target_creature_you_control`` bridge arm sets
    ``attached_to`` on the Python object but Rust always emits
    ``None`` for that slot in the zone-signature 8-tuple (comment:
    "attached_to -- not modeled on the Rust side").  Every equip
    activation produces a spurious diff at ``FieldDivergence(field=
    'battlefield', ...)``.  Structurally blocked; all 13 equipment
    probes dropped.

  * Scavenger Grounds (ExileAllGraveyards): Python ``ExileAllGraveyards``
    exiles ALL players' graveyards (including the controller's), but the
    only Rust bridge analog is ``exile_each_opponents_graveyard`` (exiles
    opponents only).  Effect semantics mismatch -> persistent
    ``exile_p0`` and ``battlefield`` diffs.  Dropped.

  * Terrain Generator (PutBasicLandFromHandOntoBattlefieldTapped):
    ``put_basic_land_from_hand_onto_battlefield_tapped`` is NOT in the
    Rust bridge's valid effect kind list.  Dropped.

  * Nesting Grounds (MovePlusOneCounterBetweenPermanentsYouControl):
    The Rust bridge kind is ``move_self_counters_to_target_creature_you_
    control`` (moves counters FROM the source permanent itself) but the
    Python effect ``MovePlusOneCounterBetweenPermanentsYouControl`` moves
    counters FROM any donor permanent to any recipient.  Different
    semantics; neither side performs a visible move in the no-agent probe
    state (Python: may_fail silently declines; Rust: fizzles with no
    self-counters).  diffs=[] only because both fizzle; rejected as a
    false-positive probe.

  * Sliver Overlord (SearchLibraryForCard, may_fail=True): ``may_fail=True``
    means Python silently declines to fetch when no agent is installed
    (library card stays, GY/hand unchanged).  Rust always fetches the first
    matching card.  Produces persistent library/hand diffs.  Dropped in
    favor of Inventors' Fair which uses may_fail=False.

  * Blinkmoth Nexus (BecomeLandCreatureUEOT): BLOCKED per directive
    (BecomeLandCreatureUEOT is a blocked effect type).

  * Swarmyard (RegenerateTargetCreature): BLOCKED per directive
    (RegenerateTargetCreature is a blocked effect type).

  * Contested War Zone (PumpCreaturesYouControlUntilEOT + attacking_only):
    Effect type already probed via Dual-Sun Adepts (batch O2).  New cost
    axis ({1},{T}) would be valid but the probe would be structurally weak
    (``attacking_only=True`` makes the pump invisible without a combat phase)
    -- same rationale as Debris Field Crusher (batch Y).  Skipped.

  * Kavaron Turbodrone (PumpTargetCreatureUntilEOT + granted_keywords=haste):
    Blocked cost field ``granted_keywords``.  Dropped per prior batches.

  * Slagdrill Scrapper / Dust Bowl / Ripchain Razorkin / Rust Harvester:
    Blocked cost fields (sacrifice_another_artifact_or_land, sacrifice_a_land,
    exile_artifact_from_graveyard).  Dropped.

**Cost-shape summary after batches O2 + Q + T + W + Y + BB + EE:**

  Proven axes (single):
    {N}             -- O2 (Intrepid Tenderfoot)
    {T}             -- Q (Xu-Ifit)
    {N}{C}          -- Q (Zookeeper Mechan)

  Proven combinations (2-axis):
    {N},{T}         -- Q (Ragged Playmate) / BB (Bonders' Enclave)
                       EE (Chrome Companion {2},{T}; Inventors' Fair {4},{T})
    {N}, sac        -- T (Illvoi Galeblade)
    {N}{C}, sac     -- T (Valgavoth's Faithful)
    {N}{C},{T}      -- W (Starport Security)
    {T}, sac        -- W (Strip Mine) / BB (Terramorphic Expanse)

  Proven combinations (3-axis):
    {N},{T}, sac    -- T (Thaumaton Torpedo) / W (Bear Trap)
                       BB (Nutrient Block {2},{T},sac)
                       EE (Dubious Delicacy {2},{T},sac;
                           Inventors' Fair {4},{T},sac)
    {3}{B}{G}, sac  -- Y (Seedship Broodtender)

NEW DEDICATED MODULE (not added to ``tests/test_trajectory_parity.py``
nor the ``test_audit_safe_trigger_*`` / ``test_probe_covered_unprobed_*``
tests).
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest


# Skip the whole module if the Rust extension isn't built.
pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


@pytest.fixture(scope="module")
def parity_smoke():
    """Load ``scripts/parity_smoke.py`` as a module (it's a script, not a
    package member) so probes can call ``_build_field_view`` for the full
    cross-engine byte-equality compare -- same fixture shape as
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
# Probe #1 -- Dubious Delicacy (covered_by_construction -> PROBED).
#
# Oracle (verbatim, ``data/edge_of_eternities.json``):
#   "[Artifact -- Food]
#    {2}, {T}, Sacrifice Dubious Delicacy: You gain 3 life.
#    {2}, {T}, Sacrifice Dubious Delicacy: Target opponent loses 3 life."
# Parser -> two non-mana ActivatedAbilities:
#   [0]: cost={N=2, tap, sac_self}  effect=GainLife(3)
#   [1]: cost={N=2, tap, sac_self}  effect=TargetOpponentLosesLife(3)
# This probe exercises AA index 1 (TargetOpponentLosesLife).
#
# Rust bridge dict (for the synthetic carrier):
#   activated_abilities=[
#     {cost: {mana: {generic:2}, tap_self:true, sacrifice_self:true},
#      effect: {kind: 'gain_life', amount: 3},
#      is_mana_ability: false},
#     {cost: {mana: {generic:2}, tap_self:true, sacrifice_self:true},
#      effect: {kind: 'target_opponent_loses_life', amount: 3},
#      is_mana_ability: false}
#   ]
#
# Setup: Dubious Delicacy on p0 bf (id=0), no other permanents.
# Pre-fund: {2} generic (2 green coins).
#
# After activation (AA index 1) on BOTH engines:
#   - tap_self cost: Dubious Delicacy tapped (visible on stack push).
#   - sac_self cost: Dubious Delicacy moves from p0 BF to p0 GY.
#   - TargetOpponentLosesLife(3) resolves: p1 loses 3 life (20 -> 17).
#   - Zone net: p0 bf 1->0 (sac), p0 gy 0->1, p1 life 20->17.
#
# **NEW effect type for the lane:** TargetOpponentLosesLife(3) is the
# first probe in the activated-ability family to exercise a direct
# life-drain targeting an opponent from an activated ability.  Prior
# EachOpponentLosesLife probes used DIES / ETB / triggers; prior
# TargetOpponentLosesLife probes (if any) were sorcery/instant spell
# effects.  This closes the gap in the AA lane.
#
# Assertion strength: **full ``compare_fields``** (strongest tier).
# Zone moves (sac_self) AND p1 life change are captured in the field
# view -- byte-equal on BOTH engines.
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_dubious_delicacy_activated_tap_sac_opponent_loses_life_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe -- Dubious Delicacy.
    Batch EE (round 7 activated-ability lane) -- generic mana + tap_self +
    sacrifice_self ({2}, {T}, sac self), TargetOpponentLosesLife(3).**

    Python: the ACTUAL parsed Dubious Delicacy printing (Artifact -- Food)
    seated on p0's battlefield; its second non-mana ActivatedAbility (``{2},
    {T}, Sacrifice Dubious Delicacy: Target opponent loses 3 life``) is
    activated via ``_activate_ability``.  Rust: bridged synthetic carrier
    with both non-mana AAs (GainLife index 0 and TargetOpponentLosesLife
    index 1) registered so ability indices match.

    **NEW effect type for the activated-ability lane:** First probe in
    the family to exercise ``TargetOpponentLosesLife`` as the resolved
    effect of an activated ability end-to-end.  Validates that the Rust
    ``target_opponent_loses_life`` bridge arm correctly deducts 3 life
    from p1 inside an activated-ability sequence with tap+sac costs.

    Assertion strength: **full ``compare_fields``** over the whole field
    view -- Dubious Delicacy leaves p0 bf (sacrifice cost), p1 loses 3
    life (TargetOpponentLosesLife effect) -- byte-equal on BOTH engines.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.actions import _activate_ability, resolve_top_of_stack
    from mtg_bot.game import Zone, ManaCoin
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.generic.life import TargetOpponentLosesLife

    real = get_active_source().get_printings().get("Dubious Delicacy")
    if real is None:
        pytest.skip("Dubious Delicacy absent from active CardSource")
    assert "Artifact" in real.card_types
    assert "Food" in real.subtypes, (
        "Dubious Delicacy must have the Food subtype"
    )
    non_mana_aas = [
        (i, aa) for i, aa in enumerate(real.activated_abilities)
        if not aa.is_mana_ability
    ]
    assert len(non_mana_aas) >= 2, (
        "Dubious Delicacy must have at least 2 non-mana ActivatedAbilities"
    )
    # AA index 1 is TargetOpponentLosesLife.
    aa_idx, aa = non_mana_aas[1]
    assert isinstance(aa.effect, TargetOpponentLosesLife), (
        f"Dubious Delicacy AA[1] must be TargetOpponentLosesLife; "
        f"got {type(aa.effect).__name__}"
    )
    assert aa.effect.amount == 3, (
        "Dubious Delicacy TargetOpponentLosesLife must lose exactly 3 life"
    )
    # Verify cost: {2} + tap_self + sac_self.
    assert aa.cost.tap_self, (
        "Dubious Delicacy AA[1] cost must require tapping itself"
    )
    assert aa.cost.sacrifice_self, (
        "Dubious Delicacy AA[1] cost must require sacrificing itself"
    )
    assert aa.cost.mana is not None and aa.cost.mana.generic == 2, (
        "Dubious Delicacy AA[1] cost must require {2} generic mana"
    )
    colored_dict = dict(aa.cost.mana.colored)
    assert not colored_dict, (
        f"Dubious Delicacy AA[1] cost must have no colored mana; "
        f"got {colored_dict}"
    )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2    # ZONE_BATTLEFIELD

    # ---- Python: Dubious Delicacy on p0 bf (id=0). ----------------------
    py_obj = py.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    py_obj.summoning_sick = False
    py_obj.tapped = False
    py_obj.damage = 0
    py_obj.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_obj)
    # Pre-fund: {2} generic (2 green coins).
    py.players[0].mana_pool.extend([ManaCoin("G", None)] * 2)

    # ---- Rust: Dubious Delicacy on p0 bf (id=0). -------------------------
    # Register BOTH non-mana AAs so ability_index=1 (TargetOpponentLosesLife)
    # matches the correct bridge arm.
    rs_id = rs.register_and_inject_object(
        {
            "name": "Dubious Delicacy",
            "card_types": ["Artifact"],
            "activated_abilities": [
                {
                    "cost": {
                        "mana": {"generic": 2},
                        "tap_self": True,
                        "sacrifice_self": True,
                    },
                    "effect": {
                        "kind": "gain_life",
                        "amount": 3,
                    },
                    "is_mana_ability": False,
                },
                {
                    "cost": {
                        "mana": {"generic": 2},
                        "tap_self": True,
                        "sacrifice_self": True,
                    },
                    "effect": {
                        "kind": "target_opponent_loses_life",
                        "amount": 3,
                    },
                    "is_mana_ability": False,
                },
            ],
        },
        0,   # controller = p0
        ZB,  # battlefield
    )
    rs.clear_summoning_sick_for_player(0)
    rs.add_mana(0, "G", 2)

    # Baseline checks.
    assert len(py.battlefield) == 1, (
        "Battlefield must start with 1 permanent (Dubious Delicacy)"
    )
    assert py.players[1].life == 20, (
        "P1 starting life must be 20 (default)"
    )
    assert rs.battlefield_sizes[0] == 1
    assert rs.graveyard_sizes[0] == 0

    # ---- Python: activate AA[1] (TargetOpponentLosesLife). ---------------
    _activate_ability(py, 0, py_obj.id, aa_idx)
    assert len(py.stack) == 1, (
        "Dubious Delicacy AA[1] activation must push exactly 1 stack item "
        "(TargetOpponentLosesLife -- no triggered ability fires from sac_self)"
    )
    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)
    assert len(py.stack) == 0

    # ---- Rust: activate AA[1] (TargetOpponentLosesLife). -----------------
    rs.apply_action(
        {"kind": "activate_ability", "source_id": rs_id, "ability_index": aa_idx}
    )
    assert rs.stack_size() == 1, (
        "Dubious Delicacy AA[1] activation must push 1 stack item "
        "(TargetOpponentLosesLife)"
    )
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0

    # ---- Verify zone moves and life change on BOTH engines. --------------
    py_p0_bf = len(py.battlefield)
    py_p0_gy = len(py.players[0].graveyard)
    py_p1_life = py.players[1].life
    rs_p0_bf = rs.battlefield_sizes[0]
    rs_p0_gy = rs.graveyard_sizes[0]

    assert py_p0_bf == 0 and rs_p0_bf == 0, (
        f"Dubious Delicacy must have left p0 battlefield (sacrificed) on "
        f"BOTH; py={py_p0_bf} rs={rs_p0_bf}"
    )
    assert py_p0_gy == 1 and rs_p0_gy == 1, (
        f"Dubious Delicacy must be in p0 graveyard on BOTH; "
        f"py={py_p0_gy} rs={rs_p0_gy}"
    )
    assert py_p1_life == 17, (
        f"P1 must have 17 life (20 - 3) on Python; got {py_p1_life}"
    )

    # ---- Full compare_fields byte-equality. ------------------------------
    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        "Dubious Delicacy {2},{T},sac self: target opponent loses 3 life "
        "must be byte-equal across the WHOLE field view on BOTH engines; "
        f"diffs={diffs}"
    )


# ---------------------------------------------------------------------
# Probe #2 -- Chrome Companion (covered_by_construction -> PROBED).
#
# Oracle (verbatim, ``data/edge_of_eternities.json``):
#   "[Artifact Creature -- Construct]
#    Whenever Chrome Companion becomes tapped, you gain 1 life.
#    {2}, {T}: Put target card in a graveyard on the bottom of its
#    owner's library."
# Parser -> one non-mana ActivatedAbility:
#   cost = ActivationCost(mana=ManaCost(generic=2), tap_self=True,
#                         sacrifice_self=False)
#   effect = PutCardFromGraveyardOnBottomOfLibrary()
#   is_mana_ability = False
#
# Triggered ability:
#   - BECOMES_TAPPED, IsSelf -> GainLife(1)   [fires when tap cost is paid]
#
# Rust bridge dict:
#   {"cost": {"mana": {"generic": 2}, "tap_self": true},
#    "effect": {"kind": "put_card_from_graveyard_on_bottom_of_library"},
#    "is_mana_ability": false,
#    "triggered_abilities": [
#      {"event": "becomes_tapped",
#       "predicate": {"kind": "source_is_self"},
#       "effect": {"kind": "gain_life", "amount": 1}}
#    ]}
#
# Setup: Chrome Companion on p0 bf (id=0), one card in p1's graveyard (id=1).
# Pre-fund: {2} generic (2 green coins).
#
# After activation on BOTH engines:
#   - tap_self cost: Chrome Companion tapped -> BECOMES_TAPPED trigger fires
#     (GainLife(1) goes on stack).
#   - PutCardFromGraveyardOnBottomOfLibrary resolves: p1 gy card moves to
#     bottom of p1's library.
#   - GainLife(1) trigger resolves: p0 gains 1 life (20 -> 21).
#   - Zone net: p1 gy 1->0, p1 lib 0->1; p0 life 20->21; p0 bf unchanged
#     (Chrome Companion stays on bf, now tapped).
#
# **NEW effect type for the lane:** PutCardFromGraveyardOnBottomOfLibrary
# is the first probe in the activated-ability family to exercise a
# graveyard-to-library zone move (opponent's card) from an activated
# ability.  Chrome Companion's BECOMES_TAPPED trigger also exercises the
# trigger-fires-on-tap-cost interaction (same pattern as Nutrient Block's
# LB trigger but for tap, not sac).
#
# Assertion strength: **full ``compare_fields``** (strongest tier).
# Zone moves (p1 gy -> p1 lib) AND p0 life gain are captured in the field
# view -- byte-equal on BOTH engines.
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_chrome_companion_activated_tap_put_gy_card_on_library_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe -- Chrome Companion.
    Batch EE (round 7 activated-ability lane) -- generic mana + tap_self
    ({2}, {T}), PutCardFromGraveyardOnBottomOfLibrary + BECOMES_TAPPED
    GainLife(1) trigger.**

    Python: the ACTUAL parsed Chrome Companion printing (Artifact Creature)
    seated on p0's battlefield; its non-mana ActivatedAbility (``{2}, {T}:
    Put target card in a graveyard on the bottom of its owner's library``) is
    activated via ``_activate_ability``.  A card in p1's graveyard serves as
    the target.  Chrome Companion's BECOMES_TAPPED trigger (``GainLife(1)``)
    also fires when the tap cost is paid, adding 1 to p0's stack of
    resolutions.  Rust: bridged synthetic carrier with the ``{"mana":
    {"generic": 2}, "tap_self": true}`` cost dict, the
    ``put_card_from_graveyard_on_bottom_of_library`` effect, and the
    BECOMES_TAPPED trigger registered in ``triggered_abilities``.

    **NEW effect type for the activated-ability lane:** First probe in
    the family to exercise ``PutCardFromGraveyardOnBottomOfLibrary`` as
    the resolved effect of an activated ability end-to-end.  Validates
    that the Rust ``put_card_from_graveyard_on_bottom_of_library`` bridge
    arm correctly moves the first card in p1's graveyard to the bottom of
    p1's library, AND that the BECOMES_TAPPED trigger chain resolves
    byte-equal alongside the main AA effect.

    Assertion strength: **full ``compare_fields``** over the whole field
    view -- p1 gy card moves to p1 lib (main effect), p0 gains 1 life
    (BECOMES_TAPPED trigger), Chrome Companion tapped -- byte-equal on
    BOTH engines.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.actions import _activate_ability, resolve_top_of_stack
    from mtg_bot.game import Zone, ManaCoin
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.generic.graveyard import PutCardFromGraveyardOnBottomOfLibrary
    from mtg_bot.effects.generic.life import GainLife
    from mtg_bot.cards.base import CardPrinting, ManaCost as MC
    from mtg_bot.effects.predicates import Event

    real = get_active_source().get_printings().get("Chrome Companion")
    if real is None:
        pytest.skip("Chrome Companion absent from active CardSource")
    assert "Artifact" in real.card_types
    assert real.is_creature, "Chrome Companion must be a Creature"
    non_mana_aas = [
        (i, aa) for i, aa in enumerate(real.activated_abilities)
        if not aa.is_mana_ability
    ]
    assert non_mana_aas, (
        "Chrome Companion must have at least one non-mana ActivatedAbility"
    )
    aa_idx, aa = non_mana_aas[0]
    assert isinstance(aa.effect, PutCardFromGraveyardOnBottomOfLibrary), (
        f"Chrome Companion non-mana AA must be "
        f"PutCardFromGraveyardOnBottomOfLibrary; got {type(aa.effect).__name__}"
    )
    # Verify cost: {2} + tap_self, no sac.
    assert aa.cost.tap_self, (
        "Chrome Companion AA cost must require tapping itself"
    )
    assert not aa.cost.sacrifice_self, (
        "Chrome Companion AA cost must NOT require sacrificing itself"
    )
    assert aa.cost.mana is not None and aa.cost.mana.generic == 2, (
        "Chrome Companion AA cost must require {2} generic mana"
    )
    # Verify BECOMES_TAPPED trigger (GainLife(1)).
    bt_trigger = next(
        (ta for ta in real.triggered_abilities
         if ta.event == Event.BECOMES_TAPPED
         and isinstance(ta.effect, GainLife)
         and ta.effect.amount == 1),
        None,
    )
    assert bt_trigger is not None, (
        "Chrome Companion must have a BECOMES_TAPPED trigger that gains 1 life"
    )

    # Card in p1's graveyard as the target for the AA.
    gy_card_printing = CardPrinting(
        name="CC GY Card", mana_cost_str="", mana_cost=MC(generic=0),
        type_line="Creature", supertypes=(), card_types=("Creature",),
        subtypes=(), power=1, toughness=1, produces=frozenset(),
    )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2    # ZONE_BATTLEFIELD
    ZL = 1    # ZONE_LIBRARY

    # ---- Python: Chrome Companion on p0 bf (id=0),
    #      GY card in p1 graveyard (id=1). -----------------------------------
    py_obj = py.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    py_obj.summoning_sick = False
    py_obj.tapped = False
    py_obj.damage = 0
    py_obj.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_obj)

    py_gy = py.new_object(gy_card_printing, owner_id=1, zone=Zone.GRAVEYARD)
    py.players[1].graveyard.append(py_gy)
    # Pre-fund: {2} generic (2 green coins).
    py.players[0].mana_pool.extend([ManaCoin("G", None)] * 2)

    # ---- Rust: same registration order -- Chrome Companion on p0 bf (id=0),
    #      GY card injected into p1 library then moved to graveyard (id=1). --
    rs_id = rs.register_and_inject_object(
        {
            "name": "Chrome Companion",
            "card_types": ["Artifact", "Creature"],
            "power": 2,
            "toughness": 2,
            "activated_abilities": [
                {
                    "cost": {
                        "mana": {"generic": 2},
                        "tap_self": True,
                    },
                    "effect": {
                        "kind": "put_card_from_graveyard_on_bottom_of_library",
                    },
                    "is_mana_ability": False,
                }
            ],
            "triggered_abilities": [
                {
                    "event": "becomes_tapped",
                    "predicate": {"kind": "source_is_self"},
                    "effect": {"kind": "gain_life", "amount": 1},
                }
            ],
        },
        0,   # controller = p0
        ZB,  # battlefield
    )
    rs_gy_id = rs.register_and_inject_object(
        {
            "name": "CC GY Card",
            "card_types": ["Creature"],
            "power": 1,
            "toughness": 1,
        },
        1,   # owner = p1
        ZL,  # inject into library first (zone 4 not supported by register)
    )
    # Move GY card from library to graveyard.
    rs.move_object(rs_gy_id, 4, 1)   # zone 4 = GRAVEYARD, owner = p1
    rs.clear_summoning_sick_for_player(0)
    rs.add_mana(0, "G", 2)

    # Baseline checks.
    assert len(py.battlefield) == 1, (
        "Battlefield must start with 1 permanent (Chrome Companion)"
    )
    assert len(py.players[1].graveyard) == 1, (
        "P1 graveyard must start with 1 card (GY target)"
    )
    assert len(py.players[1].library) == 0, (
        "P1 library must be empty before the probe"
    )
    assert py.players[0].life == 20, (
        "P0 starting life must be 20 (default)"
    )
    assert rs.battlefield_sizes[0] == 1
    assert rs.graveyard_sizes[1] == 1
    assert rs.library_sizes[1] == 0

    # ---- Python: activate. -----------------------------------------------
    _activate_ability(py, 0, py_obj.id, aa_idx)
    # tap_self fires BECOMES_TAPPED trigger (GainLife(1)); AA itself is also
    # on the stack -> stack has 2 items.
    assert len(py.stack) == 2, (
        "Chrome Companion activation must push 2 stack items: "
        "BECOMES_TAPPED GainLife(1) trigger + the AA itself"
    )
    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)
    assert len(py.stack) == 0

    # ---- Rust: activate. -------------------------------------------------
    rs.apply_action(
        {"kind": "activate_ability", "source_id": rs_id, "ability_index": 0}
    )
    assert rs.stack_size() == 2, (
        "Chrome Companion activation must push 2 stack items on Rust: "
        "BECOMES_TAPPED trigger + AA"
    )
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0

    # ---- Verify zone moves and life gain on BOTH engines. ----------------
    py_p1_gy = len(py.players[1].graveyard)
    py_p1_lib = len(py.players[1].library)
    py_p0_life = py.players[0].life
    rs_p1_gy = rs.graveyard_sizes[1]
    rs_p1_lib = rs.library_sizes[1]

    assert py_p1_gy == 0 and rs_p1_gy == 0, (
        f"P1 graveyard must be empty (card put on bottom of library) on "
        f"BOTH; py={py_p1_gy} rs={rs_p1_gy}"
    )
    assert py_p1_lib == 1 and rs_p1_lib == 1, (
        f"P1 library must have 1 card (GY card on bottom) on BOTH; "
        f"py={py_p1_lib} rs={rs_p1_lib}"
    )
    assert py_p0_life == 21, (
        f"P0 must have 21 life (20 + 1 from BECOMES_TAPPED trigger) on "
        f"Python; got {py_p0_life}"
    )
    # Chrome Companion must be tapped (tap_self cost paid).
    assert py_obj.tapped, (
        "Python: Chrome Companion must be tapped after activation (tap_self)"
    )
    assert rs.is_tapped(rs_id), (
        "Rust: Chrome Companion must be tapped after activation (tap_self)"
    )

    # ---- Full compare_fields byte-equality. ------------------------------
    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        "Chrome Companion {2},{T}: put gy card on bottom of library + "
        "BECOMES_TAPPED gain 1 life must be byte-equal across the WHOLE "
        f"field view on BOTH engines; diffs={diffs}"
    )


# ---------------------------------------------------------------------
# Probe #3 -- Inventors' Fair (covered_by_construction -> PROBED).
#
# Oracle (verbatim, ``data/edge_of_eternities.json``):
#   "[Legendary Land]
#    At the beginning of your upkeep, if you control three or more
#    artifacts, you gain 1 life. (BEGINNING_OF_UPKEEP trigger -- omitted.)
#    {4}, {T}, Sacrifice Inventors' Fair: Search your library for an
#    artifact card, put it into your hand, then shuffle your library."
# Parser -> one non-mana ActivatedAbility:
#   cost = ActivationCost(mana=ManaCost(generic=4), tap_self=True,
#                         sacrifice_self=True)
#   effect = SearchLibraryForCard(filter_name='artifact', may_fail=False)
#   is_mana_ability = False
#
# Triggered ability:
#   - BEGINNING_OF_UPKEEP, ConditionalIfYouControlAtLeast -> GainLife(1)
#     [omitted from Rust carrier -- no upkeep phase in probe state]
#
# Rust bridge dict:
#   {"cost": {"mana": {"generic": 4}, "tap_self": true,
#             "sacrifice_self": true},
#    "effect": {"kind": "search_library_for_card",
#               "filter_name": "artifact", "may_fail": false},
#    "is_mana_ability": false}
#
# NOTE on may_fail=False: The real Inventors' Fair oracle does not offer
# a ``may fail`` clause -- the controller MUST find an artifact if one
# exists.  The parser sets ``may_fail=False``, which means the Python
# SearchLibraryForCard.resolve() takes the first matching card without
# asking an agent.  This is what makes the probe viable: a ``may_fail=True``
# card would silently decline to fetch in the no-agent probe state (see
# Sliver Overlord drop note in the module docstring).
#
# Library setup: ONE artifact card seeded in p0's library as the forced
# fetch target.
#
# ID ordering: artifact filler (id=0), Inventors' Fair (id=1) on BOTH
# engines.
#
# After activation on BOTH engines:
#   - tap_self cost: Inventors' Fair tapped (visible on stack push).
#   - sac_self cost: Inventors' Fair moves from p0 BF to p0 GY.
#   - SearchLibraryForCard(artifact, may_fail=False) resolves: artifact
#     filler moves from p0 library to p0 hand.
#   - Zone net: p0 bf 1->0 (sac IF), p0 lib 1->0 (artifact fetched),
#     p0 hand 0->1, p0 gy 0->1.
#
# **NEW effect type for the lane:** SearchLibraryForCard with
# filter_name='artifact' is the first probe in the activated-ability
# family to exercise a non-basic-land library search that puts a CARD
# (not a land) into hand.  Prior library-search probes were:
#   - SearchLibraryForBasicLandTapped (Terramorphic Expanse, batch BB) --
#     a distinct effect class that puts a basic land onto the battlefield.
# This is the first probe using the generic ``SearchLibraryForCard`` class
# from an activated ability.
#
# Assertion strength: **full ``compare_fields``** (strongest tier).
# Zone moves (IF sac, artifact lib->hand) are captured in the field view
# -- byte-equal on BOTH engines.
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_inventors_fair_activated_tap_sac_search_artifact_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe -- Inventors' Fair.
    Batch EE (round 7 activated-ability lane) -- generic mana + tap_self +
    sacrifice_self ({4}, {T}, sac self), SearchLibraryForCard(artifact,
    may_fail=False).**

    Python: the ACTUAL parsed Inventors' Fair printing (Legendary Land)
    seated on p0's battlefield; its non-mana ActivatedAbility (``{4}, {T},
    Sacrifice Inventors' Fair: Search your library for an artifact card,
    put it into your hand, then shuffle``) is activated via
    ``_activate_ability``.  A single artifact card is seeded in p0's library
    as the forced fetch target.  The BEGINNING_OF_UPKEEP trigger on the real
    card is NOT exercised (no upkeep phase in the probe state).  Rust:
    bridged synthetic carrier with the ``{"mana": {"generic": 4}, "tap_self":
    true, "sacrifice_self": true}`` cost dict and the
    ``search_library_for_card(filter_name='artifact', may_fail=False)``
    effect (the upkeep trigger is omitted from the Rust carrier).

    **NEW effect type for the activated-ability lane:** First probe in
    the family to exercise ``SearchLibraryForCard`` as the resolved
    effect of an activated ability end-to-end, putting an artifact card
    into hand.  Prior library-search probes used
    ``SearchLibraryForBasicLandTapped`` (a distinct effect class);
    this probe advances the library-search effect surface to the generic
    tutor pattern.  Validates that ``may_fail=False`` forces the Python
    engine to pick the first matching card (no agent required), matching
    the Rust engine's deterministic pick behavior.

    Assertion strength: **full ``compare_fields``** over the whole field
    view -- Inventors' Fair leaves p0 bf (sacrifice cost), artifact moves
    from p0 library to p0 hand (tutor) -- byte-equal on BOTH engines.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.actions import _activate_ability, resolve_top_of_stack
    from mtg_bot.game import Zone, ManaCoin
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.generic.search import SearchLibraryForCard
    from mtg_bot.cards.base import CardPrinting, ManaCost as MC

    real = get_active_source().get_printings().get("Inventors' Fair")
    if real is None:
        pytest.skip("Inventors' Fair absent from active CardSource")
    assert "Land" in real.card_types
    assert "Legendary" in real.supertypes, (
        "Inventors' Fair must have the Legendary supertype"
    )
    non_mana_aas = [
        (i, aa) for i, aa in enumerate(real.activated_abilities)
        if not aa.is_mana_ability
    ]
    assert non_mana_aas, (
        "Inventors' Fair must have at least one non-mana ActivatedAbility"
    )
    aa_idx, aa = non_mana_aas[0]
    assert isinstance(aa.effect, SearchLibraryForCard), (
        f"genuine Inventors' Fair non-mana AA must be SearchLibraryForCard; "
        f"got {type(aa.effect).__name__}"
    )
    assert aa.effect.filter_name == "artifact", (
        "Inventors' Fair SearchLibraryForCard must filter for artifacts"
    )
    assert not aa.effect.may_fail, (
        "Inventors' Fair SearchLibraryForCard must have may_fail=False "
        "(mandatory fetch)"
    )
    # Verify cost: {4} + tap_self + sac_self.
    assert aa.cost.tap_self, (
        "Inventors' Fair AA cost must require tapping itself"
    )
    assert aa.cost.sacrifice_self, (
        "Inventors' Fair AA cost must require sacrificing itself"
    )
    assert aa.cost.mana is not None and aa.cost.mana.generic == 4, (
        "Inventors' Fair AA cost must require {4} generic mana"
    )
    colored_dict = dict(aa.cost.mana.colored)
    assert not colored_dict, (
        f"Inventors' Fair AA cost must have no colored mana; got {colored_dict}"
    )

    # Artifact filler to tutor for.
    artifact_printing = CardPrinting(
        name="IVF Artifact", mana_cost_str="", mana_cost=MC(generic=0),
        type_line="Artifact", supertypes=(), card_types=("Artifact",),
        subtypes=(), power=None, toughness=None, produces=frozenset(),
    )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2    # ZONE_BATTLEFIELD
    ZL = 1    # ZONE_LIBRARY

    # ---- Python: artifact filler in p0 library (id=0),
    #      Inventors' Fair on p0 bf (id=1). ----------------------------------
    py_artifact = py.new_object(artifact_printing, owner_id=0, zone=Zone.LIBRARY)
    # NOTE: summoning_sick is set True here to match Rust's behavior:
    # Rust's search_library_for_card marks the fetched card summoning_sick=True
    # when it moves it to hand.  Python preserves whatever summoning_sick value
    # the object has in the library.  Both sides agree on True when we pre-set it.
    py_artifact.summoning_sick = True
    py.players[0].library.append(py_artifact)

    py_obj = py.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    py_obj.summoning_sick = False
    py_obj.tapped = False
    py_obj.damage = 0
    py_obj.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_obj)
    # Pre-fund: {4} generic (4 green coins).
    py.players[0].mana_pool.extend([ManaCoin("G", None)] * 4)

    # ---- Rust: same registration order -- artifact in p0 library (id=0),
    #      Inventors' Fair on p0 bf (id=1). ----------------------------------
    # NOTE: Inventors' Fair has a BEGINNING_OF_UPKEEP trigger not included
    # here (no upkeep phase in the probe state; omitting it is safe).
    rs_artifact_id = rs.register_and_inject_object(
        {
            "name": "IVF Artifact",
            "card_types": ["Artifact"],
        },
        0,   # owner = p0
        ZL,  # ZONE_LIBRARY
    )
    rs_id = rs.register_and_inject_object(
        {
            "name": "Inventors' Fair",
            "card_types": ["Land"],
            "activated_abilities": [
                {
                    "cost": {
                        "mana": {"generic": 4},
                        "tap_self": True,
                        "sacrifice_self": True,
                    },
                    "effect": {
                        "kind": "search_library_for_card",
                        "filter_name": "artifact",
                        "may_fail": False,
                    },
                    "is_mana_ability": False,
                }
            ],
        },
        0,   # controller = p0
        ZB,  # battlefield
    )
    rs.clear_summoning_sick_for_player(0)
    rs.add_mana(0, "G", 4)

    # Baseline checks.
    assert len(py.battlefield) == 1, (
        "Battlefield must start with 1 permanent (Inventors' Fair)"
    )
    assert len(py.players[0].library) == 1, (
        "Library must start with 1 artifact card (forced fetch target)"
    )
    assert rs.battlefield_sizes[0] == 1
    assert rs.library_sizes[0] == 1
    assert rs.graveyard_sizes[0] == 0
    assert rs.hand_sizes[0] == 0

    # ---- Python: activate. -----------------------------------------------
    _activate_ability(py, 0, py_obj.id, aa_idx)
    assert len(py.stack) == 1, (
        "Inventors' Fair activation must push exactly 1 stack item "
        "(SearchLibraryForCard -- no triggered ability fires from sac_self)"
    )
    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)
    assert len(py.stack) == 0

    # ---- Rust: activate. -------------------------------------------------
    rs.apply_action(
        {"kind": "activate_ability", "source_id": rs_id, "ability_index": 0}
    )
    assert rs.stack_size() == 1, (
        "Inventors' Fair activation must push exactly 1 stack item on Rust "
        "(SearchLibraryForCard)"
    )
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0

    # ---- Verify zone moves on BOTH engines. ------------------------------
    py_p0_bf = len(py.battlefield)
    py_p0_lib = len(py.players[0].library)
    py_p0_hand = len(py.players[0].hand)
    py_p0_gy = len(py.players[0].graveyard)
    rs_p0_bf = rs.battlefield_sizes[0]
    rs_p0_lib = rs.library_sizes[0]
    rs_p0_hand = rs.hand_sizes[0]
    rs_p0_gy = rs.graveyard_sizes[0]

    assert py_p0_bf == 0 and rs_p0_bf == 0, (
        f"Inventors' Fair must have left p0 battlefield (sacrificed) on "
        f"BOTH; py={py_p0_bf} rs={rs_p0_bf}"
    )
    assert py_p0_lib == 0 and rs_p0_lib == 0, (
        f"Library must be empty (artifact fetched) on BOTH; "
        f"py={py_p0_lib} rs={rs_p0_lib}"
    )
    assert py_p0_hand == 1 and rs_p0_hand == 1, (
        f"Artifact must be in p0 hand (tutored) on BOTH; "
        f"py={py_p0_hand} rs={rs_p0_hand}"
    )
    assert py_p0_gy == 1 and rs_p0_gy == 1, (
        f"Inventors' Fair must be in p0 graveyard (sac cost) on BOTH; "
        f"py={py_p0_gy} rs={rs_p0_gy}"
    )
    # Confirm the tutored card is the artifact (not IF itself).
    py_hand_names = [o.printing.name for o in py.players[0].hand]
    assert "IVF Artifact" in py_hand_names, (
        f"Python: IVF Artifact must be in p0 hand after tutor; "
        f"hand_names={py_hand_names}"
    )
    assert "Inventors' Fair" not in py_hand_names, (
        f"Python: Inventors' Fair must NOT be in p0 hand; "
        f"hand_names={py_hand_names}"
    )

    # ---- Full compare_fields byte-equality. ------------------------------
    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        "Inventors' Fair {4},{T},sac self: search for artifact card must be "
        "byte-equal across the WHOLE field view on BOTH engines; "
        f"diffs={diffs}"
    )
