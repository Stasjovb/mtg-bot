"""Genuine real-EoE cross-engine byte-equality probes -- activated-ability
lane, batch BB (round 6 of the activated-ability family).

**Context -- extending O2 + Q + T + W + Y.**  Batches O2/Q/T/W/Y proved
fifteen cost axes on the CE20 substrate:

  - O2: pure generic mana ({N}) -- Intrepid Tenderfoot, Malevolent
    Chandelier, Dual-Sun Adepts.
  - Q: tap-only ({T}), colored mana ({N}{C}), mana+tap ({N},{T}) --
    Xu-Ifit, Zookeeper Mechan, Ragged Playmate.
  - T: mana+sac_self ({N}, sac), colored+sac_self ({N}{C}, sac),
    mana+tap+sac_self ({N},{T}, sac) -- Illvoi Galeblade, Valgavoth's
    Faithful, Thaumaton Torpedo.
  - W: tap+colored ({N}{C},{T}), mana+tap+sac_self (Bear Trap),
    tap+sac_self no-mana ({T}, sac) -- Starport Security, Bear Trap,
    Strip Mine.
  - Y: {N},sac+surveil+draw (Found Footage), {1}{U}+sac+stun (Cryogen
    Relic), {3}{B}{G}+sac+reanimate (Seedship Broodtender).

This module (batch BB) extends the same lane with **three new probes**:

  1. Nutrient Block  (covered_by_construction -> PROBED)
     ``{2}, {T}, Sacrifice Nutrient Block: You gain 3 life.``
     Cost: {N=2}, tap_self=True, sacrifice_self=True.
     **NEW effect type:** GainLife(3) is the first probe in the
     activated-ability lane to exercise a life-gain effect.  Prior
     GainLife probes were all ETB / BECOMES_TAPPED triggers; this closes
     the GainLife gap in the AA lane.  The card also has a
     LEAVES_BATTLEFIELD trigger (DrawCards(1)) that fires after the
     sac_self cost is paid; this probe validates that both the main
     GainLife effect AND the LB trigger resolve byte-equal.

  2. Terramorphic Expanse  (covered_by_construction -> PROBED)
     ``{T}, Sacrifice Terramorphic Expanse: Search your library for a
     basic land card, put it onto the battlefield tapped, then shuffle.``
     Cost: mana=None (no mana), tap_self=True, sacrifice_self=True.
     **NEW effect type:** SearchLibraryForBasicLandTapped is the first
     probe in the activated-ability lane to exercise a library-search
     effect.  Cost shape is ``{T}, sac`` (no mana), which is the same
     shape as Strip Mine (batch W) -- but with a different effect, so
     the probe advances the effect-type surface without introducing a
     new cost axis.

  3. Bonders' Enclave  (covered_by_construction -> PROBED)
     ``{3}, {T}: Draw a card. Activate only if you control a creature
     with power 4 or greater.``
     Cost: {N=3}, tap_self=True, no sacrifice.
     **NEW probe:** DrawCards(1) via ``{3},{T}`` (the highest-generic
     tap-only cost in the lane so far).  The ``requires_own_creature_
     power_at_least=4`` gate is checked by Python's legal-action filter
     but is NOT enforced inside ``_activate_ability`` itself; the probe
     satisfies the gate by seating a power-4 creature on the controller's
     battlefield, making the activation fully valid in the probe state.
     The probe is honest: the GE4-power creature IS present, so the
     activation would be legal if checked.  What is NOT tested here is
     the gate-rejection path (no power-4 creature -> illegal action) --
     that is a separate legal-action-surface test, out of scope for a
     byte-equality probe.  Rust: bridged synthetic carrier with
     ``{"mana": {"generic": 3}, "tap_self": true}`` (no
     requires_own_creature_power_at_least mirror -- the bridge does not
     model activation condition gates today).

All three cards are in the ``covered_by_construction`` tier at HEAD
(every Effect class they emit has a live Rust variant + bridge arm, but
no genuine real-EoE probe pins that card).  This module promotes them
to PROBED.

**Cost-shape summary after batches O2 + Q + T + W + Y + BB:**

  Proven axes (single):
    {N}             -- O2 (Intrepid Tenderfoot)
    {T}             -- Q (Xu-Ifit)
    {N}{C}          -- Q (Zookeeper Mechan)

  Proven combinations (2-axis):
    {N},{T}         -- Q (Ragged Playmate) / BB (Bonders' Enclave, {3},{T})
    {N}, sac        -- T (Illvoi Galeblade)
    {N}{C}, sac     -- T (Valgavoth's Faithful)
    {N}{C},{T}      -- W (Starport Security)
    {T}, sac        -- W (Strip Mine) / BB (Terramorphic Expanse, no mana)
    {N}{2C}, sac    -- Y (Seedship Broodtender)

  Proven combinations (3-axis):
    {N},{T}, sac    -- T (Thaumaton Torpedo) / W (Bear Trap)
                       BB (Nutrient Block, {2},{T},sac)

**DROPPED candidates (batch BB survey, 2026-05-19):**

  * Slagdrill Scrapper: ``{2}, {T}: Draw a card.``  Parsed cost has
    ``sacrifice_another_artifact_or_land=True`` (blocked cost field).
    Skipped.

  * Dust Bowl: ``{3}, {T}: Destroy target land.``  Parsed cost has
    ``sacrifice_a_land=True`` (blocked cost field).  Skipped.

  * Ripchain Razorkin: ``{2}{R}: Draw a card.``  Parsed cost has
    ``sacrifice_a_land=True`` (blocked cost field).  Skipped.

  * Rust Harvester: ``{2}, {T}: Put a +1/+1 counter on Rust Harvester,
    then it deals damage equal to its power to any target.``  Parsed
    cost has ``exile_artifact_from_graveyard=True`` (blocked cost field).
    Skipped.

  * High Market: ``{T}, Sacrifice a creature: You gain 1 life.``  Parsed
    cost has ``sacrifice_another_creature_or_artifact=True`` (blocked
    cost field).  Skipped.

  * Umbral Collar Zealot (free Surveil ability): Parsed cost has
    ``sacrifice_another_creature_or_artifact=True`` (blocked cost field).
    Skipped.

  * Sunstar Chaplain: ``{2}: Tap target artifact or creature.``  Parsed
    cost has ``remove_plus_one_counter_from_your_creature=True`` (blocked
    cost field).  Skipped.

  * Kavaron Turbodrone: ``{T}: Target creature you control gets +1/+1
    and gains haste until end of turn.``  Effect is
    PumpTargetCreatureUntilEOT with ``granted_keywords={'haste'}``.
    Rust's ``pump_target_creature_until_eot`` bridge arm does not carry
    the ``granted_keywords`` rider; the haste grant is invisible in the
    field view, making the probe structurally weak (diffs==[] for the
    wrong reason -- same rationale as Debris Field Crusher in batch Y).
    Skipped.

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
# Probe #1 -- Nutrient Block (covered_by_construction -> PROBED).
#
# Oracle (verbatim, ``data/edge_of_eternities.json``):
#   "[Artifact]
#    {2}, {T}, Sacrifice Nutrient Block: You gain 3 life."
# Parser -> one non-mana ActivatedAbility:
#   cost = ActivationCost(mana=ManaCost(generic=2), tap_self=True,
#                         sacrifice_self=True)
#   effect = GainLife(amount=3)
#   is_mana_ability = False
#
# Triggered abilities:
#   - LEAVES_BATTLEFIELD, IsSelf -> DrawCards(1)   [LB]
#
# Rust bridge dict:
#   {"cost": {"mana": {"generic": 2}, "tap_self": true,
#             "sacrifice_self": true},
#    "effect": {"kind": "gain_life", "amount": 3},
#    "is_mana_ability": false,
#    "triggered_abilities": [
#      {"event": "leaves_battlefield",
#       "predicate": {"kind": "source_is_self"},
#       "effect": {"kind": "draw_cards", "count": 1}}
#    ]}
#
# Library filler: one filler seeded in p0's library for the LB trigger
# DrawCards(1).
#
# ID ordering: filler (id=0), Nutrient Block (id=1) on BOTH engines.
#
# After activation on BOTH engines:
#   - tap_self cost: Nutrient Block tapped (visible on stack push).
#   - sac_self cost: Nutrient Block moves from p0 BF to p0 GY ->
#     LB trigger fires, DrawCards(1) goes on stack.
#   - GainLife(3) resolves: p0 gains 3 life (20 -> 23).
#   - LB trigger DrawCards(1) resolves: p0 draws the library filler.
#   - Zone net: p0 bf 1->0 (sac), p0 lib 1->0 (drawn), p0 hand 0->1,
#     p0 gy 0->1 (Nutrient Block); life 20->23.
#
# **NEW effect type for the lane:** GainLife(3) is the first probe in
# the activated-ability family to exercise a life-gain effect from an
# activated ability.  Prior GainLife probes were BECOMES_TAPPED or ETB
# triggers (Chrome Companion, Samis's Curiosity shape).  This closes
# the GainLife gap in the AA lane.
#
# Assertion strength: **full ``compare_fields``** (strongest tier).
# Zone moves (sac_self, lib->hand draw) AND the p0 life change are all
# captured in the field view -- byte-equal on BOTH engines.
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_nutrient_block_activated_tap_sac_gain_life_draw_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe -- Nutrient Block.
    Batch BB (round 6 activated-ability lane) -- mana + tap_self +
    sacrifice_self ({2}, {T}, sac self), GainLife(3) + LB trigger
    DrawCards(1).**

    Python: the ACTUAL parsed Nutrient Block printing (Artifact) seated on
    p0's battlefield; its non-mana ActivatedAbility (``{2}, {T}, Sacrifice
    Nutrient Block: You gain 3 life``) is activated via
    ``_activate_ability``.  The card's LEAVES_BATTLEFIELD trigger
    (``DrawCards(1)``) also fires and resolves; a single library filler
    is seeded for the draw.  Rust: bridged synthetic carrier with the
    ``{"mana": {"generic": 2}, "tap_self": true, "sacrifice_self": true}``
    cost dict, the ``gain_life(amount=3)`` effect, and the LB trigger
    registered in ``triggered_abilities``.

    **NEW effect type for the activated-ability lane:** First probe in
    the family to exercise ``GainLife`` as the resolved effect of an
    activated ability end-to-end.  Validates that the Rust ``gain_life``
    bridge arm works inside an activated-ability sequence that also
    chains a LEAVES_BATTLEFIELD trigger.

    Assertion strength: **full ``compare_fields``** over the whole field
    view -- Nutrient Block leaves p0 bf (tap + sacrifice cost), p0 gains
    3 life (GainLife effect), p0 draws the library filler (LB trigger) --
    byte-equal on BOTH engines.
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
    from mtg_bot.effects.generic.life import GainLife
    from mtg_bot.effects.generic.draw_mill import DrawCards
    from mtg_bot.cards.base import CardPrinting, ManaCost as MC

    real = get_active_source().get_printings().get("Nutrient Block")
    if real is None:
        pytest.skip("Nutrient Block absent from active CardSource")
    assert "Artifact" in real.card_types
    non_mana_aas = [
        (i, aa) for i, aa in enumerate(real.activated_abilities)
        if not aa.is_mana_ability
    ]
    assert non_mana_aas, (
        "Nutrient Block must have at least one non-mana ActivatedAbility"
    )
    aa_idx, aa = non_mana_aas[0]
    assert isinstance(aa.effect, GainLife), (
        f"genuine Nutrient Block non-mana AA must be GainLife; "
        f"got {type(aa.effect).__name__}"
    )
    assert aa.effect.amount == 3, (
        "Nutrient Block GainLife must gain exactly 3 life"
    )
    # Verify cost: {2} + tap_self + sac_self.
    assert aa.cost.tap_self, (
        "Nutrient Block AA cost must require tapping itself"
    )
    assert aa.cost.sacrifice_self, (
        "Nutrient Block AA cost must require sacrificing itself"
    )
    assert aa.cost.mana is not None and aa.cost.mana.generic == 2, (
        "Nutrient Block AA cost must require {2} generic mana"
    )
    colored_dict = dict(aa.cost.mana.colored)
    assert not colored_dict, (
        f"Nutrient Block AA cost must have no colored mana; got {colored_dict}"
    )
    # Card has LB trigger (DrawCards(1)).
    assert real.triggered_abilities, (
        "Nutrient Block must have triggered abilities (LB draw trigger)"
    )
    lb_trigger = next(
        (ta for ta in real.triggered_abilities
         if isinstance(ta.effect, DrawCards) and ta.effect.amount == 1),
        None,
    )
    assert lb_trigger is not None, (
        "Nutrient Block must have a LB trigger that draws 1 card"
    )

    # Library filler for the LB trigger DrawCards(1).
    filler_printing = CardPrinting(
        name="NB Library Filler", mana_cost_str="", mana_cost=MC(generic=0),
        type_line="Creature", supertypes=(), card_types=("Creature",),
        subtypes=(), power=1, toughness=1, produces=frozenset(),
    )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2    # ZONE_BATTLEFIELD

    # ---- Python: filler in library (id=0), Nutrient Block on p0 bf (id=1). ----
    py_filler = py.new_object(filler_printing, owner_id=0, zone=Zone.LIBRARY)
    py_filler.summoning_sick = False
    py.players[0].library.append(py_filler)

    py_obj = py.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    py_obj.summoning_sick = False
    py_obj.tapped = False
    py_obj.damage = 0
    py_obj.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_obj)
    # Pre-fund: {2} generic (2 green coins).
    py.players[0].mana_pool.extend([ManaCoin("G", None)] * 2)

    # ---- Rust: same registration order -- filler in library (id=0),
    #      Nutrient Block in battlefield (id=1). -------------------------
    rs.register_and_inject_object(
        {
            "name": "NB Library Filler",
            "card_types": ["Creature"],
            "power": 1, "toughness": 1,
        },
        0,   # controller = p0
        1,   # ZONE_LIBRARY
    )
    rs_id = rs.register_and_inject_object(
        {
            "name": "Nutrient Block",
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
                }
            ],
            "triggered_abilities": [
                {
                    "event": "leaves_battlefield",
                    "predicate": {"kind": "source_is_self"},
                    "effect": {"kind": "draw_cards", "count": 1},
                }
            ],
        },
        0,   # controller = p0
        ZB,  # battlefield
    )
    rs.clear_summoning_sick_for_player(0)
    rs.add_mana(0, "G", 2)

    # Baseline checks.
    assert len(py.battlefield) == 1, (
        "Battlefield must start with 1 permanent (Nutrient Block)"
    )
    assert len(py.players[0].library) == 1, (
        "Library must start with 1 filler card for the LB trigger draw"
    )
    assert py.players[0].life == 20, (
        "P0 starting life must be 20 (default)"
    )
    assert rs.battlefield_sizes[0] == 1
    assert rs.library_sizes[0] == 1
    assert rs.graveyard_sizes[0] == 0

    # ---- Python: activate. -----------------------------------------------
    _activate_ability(py, 0, py_obj.id, aa_idx)
    assert len(py.stack) == 2, (
        "Nutrient Block activation must push 2 items: LB trigger + AA "
        "(sac_self fires LB before AA resolves)"
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
        "Nutrient Block activation must push 2 stack items: LB trigger + AA"
    )
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0

    # ---- Verify zone moves and life gain on BOTH engines. ----------------
    py_p0_bf = len(py.battlefield)
    py_p0_lib = len(py.players[0].library)
    py_p0_hand = len(py.players[0].hand)
    py_p0_gy = len(py.players[0].graveyard)
    py_p0_life = py.players[0].life
    rs_p0_bf = rs.battlefield_sizes[0]
    rs_p0_lib = rs.library_sizes[0]
    rs_p0_hand = rs.hand_sizes[0]
    rs_p0_gy = rs.graveyard_sizes[0]

    assert py_p0_bf == 0 and rs_p0_bf == 0, (
        f"Nutrient Block must have left p0 battlefield (sacrificed) on BOTH; "
        f"py={py_p0_bf} rs={rs_p0_bf}"
    )
    assert py_p0_lib == 0 and rs_p0_lib == 0, (
        f"Library must be empty (filler drawn by LB trigger) on BOTH; "
        f"py={py_p0_lib} rs={rs_p0_lib}"
    )
    assert py_p0_hand == 1 and rs_p0_hand == 1, (
        f"Filler must be in p0 hand (drawn by LB trigger) on BOTH; "
        f"py={py_p0_hand} rs={rs_p0_hand}"
    )
    assert py_p0_gy == 1 and rs_p0_gy == 1, (
        f"Nutrient Block must be in p0 graveyard (sac cost) on BOTH; "
        f"py={py_p0_gy} rs={rs_p0_gy}"
    )
    assert py_p0_life == 23, (
        f"P0 must have 23 life (20 + 3 gained) on Python; got {py_p0_life}"
    )

    # ---- Full compare_fields byte-equality. ---------------------------
    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        "Nutrient Block {2},{T},sac self: gain 3 life + LB draw must be "
        "byte-equal across the WHOLE field view on BOTH engines; "
        f"diffs={diffs}"
    )


# ---------------------------------------------------------------------
# Probe #2 -- Terramorphic Expanse (covered_by_construction -> PROBED).
#
# Oracle (verbatim, ``data/edge_of_eternities.json``):
#   "[Land]
#    {T}, Sacrifice Terramorphic Expanse: Search your library for a basic
#    land card, put it onto the battlefield tapped, then shuffle."
# Parser -> one non-mana ActivatedAbility:
#   cost = ActivationCost(mana=None (no mana), tap_self=True,
#                         sacrifice_self=True)
#   effect = SearchLibraryForBasicLandTapped()
#   is_mana_ability = False
#
# Rust bridge dict:
#   {"cost": {"tap_self": true, "sacrifice_self": true},
#    "effect": {"kind": "search_library_for_basic_land_tapped"},
#    "is_mana_ability": false}
#
# Library setup: ONE basic land (Plains) seeded in p0's library as the
# forced fetch target.  SearchLibraryForBasicLandTapped finds the first
# basic land and puts it on the battlefield tapped.
#
# After activation on BOTH engines:
#   - tap_self cost: Terramorphic Expanse tapped.
#   - sac_self cost: Terramorphic Expanse moves to p0 GY.
#   - SearchLibraryForBasicLandTapped resolves: Plains moves from p0
#     library to p0 battlefield (tapped).
#   - Zone net: p0 bf 1->1 (TE leaves, Plains enters),
#     p0 lib 1->0 (Plains fetched), p0 gy 0->1 (TE sac'd).
#
# **NEW effect type for the lane:** SearchLibraryForBasicLandTapped is
# the first probe in the activated-ability family to exercise a library
# search effect.  All prior library-affecting probes were draw / surveil
# / mill shapes.
#
# Cost shape: ``{T}, sac`` (no mana) -- same axis as Strip Mine (batch
# W), but with a different effect (DestroyTargetLand vs
# SearchLibraryForBasicLandTapped).  Confirms the bridge handles the
# no-mana-tap-sac cost shape for a second distinct effect type.
#
# Assertion strength: **full ``compare_fields``** (strongest tier).
# Zone moves (TE sac, Plains fetch-to-bf) are captured in the field
# view -- byte-equal on BOTH engines.
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_terramorphic_expanse_activated_tap_sac_fetch_land_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe -- Terramorphic Expanse.
    Batch BB (round 6 activated-ability lane) -- no mana + tap_self +
    sacrifice_self ({T}, sac self), SearchLibraryForBasicLandTapped.**

    Python: the ACTUAL parsed Terramorphic Expanse printing (Land) seated
    on p0's battlefield; its non-mana ActivatedAbility (``{T}, Sacrifice
    Terramorphic Expanse: Search your library for a basic land card, put
    it onto the battlefield tapped, then shuffle``) is activated via
    ``_activate_ability``.  A Plains basic land is seeded in p0's library
    as the forced fetch target.  Rust: bridged synthetic carrier with the
    ``{"tap_self": true, "sacrifice_self": true}`` cost dict (no mana
    key -- mirrors the no-mana activation) and the
    ``search_library_for_basic_land_tapped`` effect.

    **NEW effect type for the activated-ability lane:** First probe in
    the family to exercise ``SearchLibraryForBasicLandTapped`` as the
    resolved effect of an activated ability end-to-end.  Validates that
    the Rust ``search_library_for_basic_land_tapped`` bridge arm
    correctly fetches the first basic land from the library and places
    it on the battlefield tapped.

    Assertion strength: **full ``compare_fields``** over the whole field
    view -- Terramorphic Expanse leaves p0 bf (sacrifice cost), Plains
    moves from library to p0 bf (fetch) -- byte-equal on BOTH engines.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.actions import _activate_ability, resolve_top_of_stack
    from mtg_bot.game import Zone
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.generic.search import SearchLibraryForBasicLandTapped
    from mtg_bot.cards.base import CardPrinting, ManaCost as MC

    real = get_active_source().get_printings().get("Terramorphic Expanse")
    if real is None:
        pytest.skip("Terramorphic Expanse absent from active CardSource")
    assert "Land" in real.card_types
    non_mana_aas = [
        (i, aa) for i, aa in enumerate(real.activated_abilities)
        if not aa.is_mana_ability
    ]
    assert non_mana_aas, (
        "Terramorphic Expanse must have at least one non-mana ActivatedAbility"
    )
    aa_idx, aa = non_mana_aas[0]
    assert isinstance(aa.effect, SearchLibraryForBasicLandTapped), (
        f"genuine Terramorphic Expanse non-mana AA must be "
        f"SearchLibraryForBasicLandTapped; got {type(aa.effect).__name__}"
    )
    # Verify cost: no mana, tap_self + sac_self.
    assert aa.cost.tap_self, (
        "Terramorphic Expanse AA cost must require tapping itself"
    )
    assert aa.cost.sacrifice_self, (
        "Terramorphic Expanse AA cost must require sacrificing itself"
    )
    assert aa.cost.mana is None, (
        "Terramorphic Expanse AA cost must NOT require mana (free tap+sac)"
    )
    assert not real.triggered_abilities, (
        "Terramorphic Expanse must have no triggered abilities (clean probe)"
    )

    # Basic land (Plains) seeded in p0's library as the forced fetch target.
    plains_printing = CardPrinting(
        name="Plains", mana_cost_str="", mana_cost=MC(generic=0),
        type_line="Basic Land — Plains", supertypes=("Basic",),
        card_types=("Land",), subtypes=("Plains",),
        power=None, toughness=None, produces=frozenset({"W"}),
    )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2    # ZONE_BATTLEFIELD
    ZL = 1    # ZONE_LIBRARY

    # ---- Python: Plains in library (id=0), Terramorphic Expanse on p0 bf (id=1). ----
    py_plains = py.new_object(plains_printing, owner_id=0, zone=Zone.LIBRARY)
    py_plains.summoning_sick = False
    py.players[0].library.append(py_plains)

    py_obj = py.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    py_obj.summoning_sick = False
    py_obj.tapped = False
    py_obj.damage = 0
    py_obj.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_obj)
    # No mana needed (cost is only {T}, sac self -- no mana payment).

    # ---- Rust: same registration order -- Plains in library (id=0),
    #      Terramorphic Expanse in battlefield (id=1). --------------------
    rs.register_and_inject_object(
        {
            "name": "Plains",
            "card_types": ["Land"],
            "supertypes": ["Basic"],
        },
        0,   # controller = p0
        ZL,  # ZONE_LIBRARY
    )
    rs_id = rs.register_and_inject_object(
        {
            "name": "Terramorphic Expanse",
            "card_types": ["Land"],
            "activated_abilities": [
                {
                    "cost": {
                        "tap_self": True,
                        "sacrifice_self": True,
                    },
                    "effect": {
                        "kind": "search_library_for_basic_land_tapped",
                    },
                    "is_mana_ability": False,
                }
            ],
        },
        0,   # controller = p0
        ZB,  # battlefield
    )
    rs.clear_summoning_sick_for_player(0)

    # Baseline checks.
    assert len(py.battlefield) == 1, (
        "Battlefield must start with 1 permanent (Terramorphic Expanse)"
    )
    assert len(py.players[0].library) == 1, (
        "Library must start with 1 basic land (Plains)"
    )
    assert rs.battlefield_sizes[0] == 1
    assert rs.library_sizes[0] == 1
    assert rs.graveyard_sizes[0] == 0

    # ---- Python: activate. -----------------------------------------------
    _activate_ability(py, 0, py_obj.id, aa_idx)
    assert len(py.stack) == 1, (
        "Terramorphic Expanse activation must push one StackItem (non-mana)"
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
        "Terramorphic Expanse activation must push one stack item (non-mana)"
    )
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0

    # ---- Verify zone moves on BOTH engines. ------------------------------
    py_p0_bf = len(py.battlefield)
    py_p0_lib = len(py.players[0].library)
    py_p0_gy = len(py.players[0].graveyard)
    rs_p0_bf = rs.battlefield_sizes[0]
    rs_p0_lib = rs.library_sizes[0]
    rs_p0_gy = rs.graveyard_sizes[0]

    assert py_p0_bf == 1 and rs_p0_bf == 1, (
        f"Exactly 1 permanent must be on p0 battlefield (Plains) on BOTH; "
        f"py={py_p0_bf} rs={rs_p0_bf}"
    )
    assert py_p0_lib == 0 and rs_p0_lib == 0, (
        f"Library must be empty (Plains fetched) on BOTH; "
        f"py={py_p0_lib} rs={rs_p0_lib}"
    )
    assert py_p0_gy == 1 and rs_p0_gy == 1, (
        f"Terramorphic Expanse must be in p0 graveyard (sac cost) on BOTH; "
        f"py={py_p0_gy} rs={rs_p0_gy}"
    )

    # Confirm Plains is on battlefield (not Terramorphic Expanse).
    py_bf_names = [o.printing.name for o in py.battlefield]
    assert "Plains" in py_bf_names, (
        f"Python: Plains must be on battlefield after fetch; "
        f"bf_names={py_bf_names}"
    )
    assert "Terramorphic Expanse" not in py_bf_names, (
        f"Python: Terramorphic Expanse must NOT be on battlefield; "
        f"bf_names={py_bf_names}"
    )

    # ---- Full compare_fields byte-equality. ---------------------------
    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        "Terramorphic Expanse {T},sac self: fetch basic land tapped must be "
        "byte-equal across the WHOLE field view on BOTH engines; "
        f"diffs={diffs}"
    )


# ---------------------------------------------------------------------
# Probe #3 -- Bonders' Enclave (covered_by_construction -> PROBED).
#
# Oracle (verbatim, ``data/edge_of_eternities.json``):
#   "[Land]
#    {3}, {T}: Draw a card. Activate only if you control a creature
#    with power 4 or greater."
# Parser -> one non-mana ActivatedAbility:
#   cost = ActivationCost(mana=ManaCost(generic=3), tap_self=True,
#                         sacrifice_self=False,
#                         requires_own_creature_power_at_least=4)
#   effect = DrawCards(amount=1)
#   is_mana_ability = False
#
# Rust bridge dict:
#   {"cost": {"mana": {"generic": 3}, "tap_self": true},
#    "effect": {"kind": "draw_cards", "count": 1},
#    "is_mana_ability": false}
#
# NOTE on the condition gate: ``requires_own_creature_power_at_least=4``
# is checked by Python's legal-action filter (``legal.py``) but is NOT
# enforced inside ``_activate_ability`` itself.  The probe satisfies the
# gate by seating a power-4 creature on p0's battlefield, making the
# activation fully valid in the probe state.  The Rust synthetic carrier
# does not include this field (the bridge does not model activation
# condition gates today); the omission is safe because the field-view
# output is identical whether or not the gate is modelled.
#
# Library setup: ONE filler seeded in p0's library for the DrawCards(1).
# Power-4 creature also seated on p0's bf to satisfy the gate condition.
#
# ID ordering: filler (id=0), power-4 creature (id=1),
#              Bonders' Enclave (id=2) on BOTH engines.
#
# After activation on BOTH engines:
#   - tap_self cost: Bonders' Enclave tapped.
#   - DrawCards(1) resolves: p0 draws the library filler.
#   - Zone net: p0 bf 2->2 (unchanged -- Enclave stays tapped, big
#     creature unchanged), p0 lib 1->0 (drawn), p0 hand 0->1.
#
# **Cost-shape significance:** {3},{T} (3 generic + tap, no sac,
# no colored mana) is the highest-generic tap-only cost in the lane so
# far.  All prior {N},{T} probes used lower generics (Ragged Playmate
# was {1},{T}).  Confirms the bridge scales cleanly to higher generic
# amounts on the same cost axis.
#
# Assertion strength: **full ``compare_fields``** (strongest tier).
# The draw move (lib->hand) is captured in the field view -- byte-equal
# on BOTH engines.
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_bonders_enclave_activated_tap_draw_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe -- Bonders' Enclave.
    Batch BB (round 6 activated-ability lane) -- generic mana + tap_self
    ({3}, {T}), DrawCards(1), condition gate satisfied.**

    Python: the ACTUAL parsed Bonders' Enclave printing (Land) seated on
    p0's battlefield; its non-mana ActivatedAbility (``{3}, {T}: Draw a
    card. Activate only if you control a creature with power 4 or
    greater``) is activated via ``_activate_ability``.  A power-4 creature
    is seated on p0's battlefield to satisfy the ``requires_own_creature_
    power_at_least=4`` gate condition.  A single library filler is seeded
    for the draw.  Rust: bridged synthetic carrier with the
    ``{"mana": {"generic": 3}, "tap_self": true}`` cost dict and the
    ``draw_cards(count=1)`` effect (the condition gate has no Rust mirror
    today).

    **Cost-shape significance:** {3},{T} is the highest-generic tap-only
    cost proven in the activated-ability lane so far (prior {N},{T}
    probes used {1} generic on Ragged Playmate, batch Q).  Validates
    that the bridge handles larger generic amounts on the tap-only axis.

    Assertion strength: **full ``compare_fields``** over the whole field
    view -- Bonders' Enclave tapped (tap cost), filler moves from library
    to p0 hand (draw) -- byte-equal on BOTH engines.
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
    from mtg_bot.effects.generic.draw_mill import DrawCards
    from mtg_bot.cards.base import CardPrinting, ManaCost as MC

    real = get_active_source().get_printings().get("Bonders' Enclave")
    if real is None:
        pytest.skip("Bonders' Enclave absent from active CardSource")
    assert "Land" in real.card_types
    non_mana_aas = [
        (i, aa) for i, aa in enumerate(real.activated_abilities)
        if not aa.is_mana_ability
    ]
    assert non_mana_aas, (
        "Bonders' Enclave must have at least one non-mana ActivatedAbility"
    )
    aa_idx, aa = non_mana_aas[0]
    assert isinstance(aa.effect, DrawCards), (
        f"genuine Bonders' Enclave non-mana AA must be DrawCards; "
        f"got {type(aa.effect).__name__}"
    )
    assert aa.effect.amount == 1, (
        "Bonders' Enclave DrawCards must draw exactly 1 card"
    )
    # Verify cost: {3} generic + tap_self, no sac.
    assert aa.cost.tap_self, (
        "Bonders' Enclave AA cost must require tapping itself"
    )
    assert not aa.cost.sacrifice_self, (
        "Bonders' Enclave AA cost must NOT require sacrificing itself"
    )
    assert aa.cost.mana is not None and aa.cost.mana.generic == 3, (
        "Bonders' Enclave AA cost must require {3} generic mana"
    )
    colored_dict = dict(aa.cost.mana.colored)
    assert not colored_dict, (
        f"Bonders' Enclave AA cost must have no colored mana; got {colored_dict}"
    )
    assert aa.cost.requires_own_creature_power_at_least == 4, (
        "Bonders' Enclave AA must have requires_own_creature_power_at_least=4"
    )
    assert not real.triggered_abilities, (
        "Bonders' Enclave must have no triggered abilities (clean probe)"
    )

    # Library filler for DrawCards(1).
    filler_printing = CardPrinting(
        name="BE Library Filler", mana_cost_str="", mana_cost=MC(generic=0),
        type_line="Creature", supertypes=(), card_types=("Creature",),
        subtypes=(), power=1, toughness=1, produces=frozenset(),
    )
    # Power-4 creature to satisfy the requires_own_creature_power_at_least=4 gate.
    big_creature_printing = CardPrinting(
        name="BE Big Creature", mana_cost_str="", mana_cost=MC(generic=0),
        type_line="Creature", supertypes=(), card_types=("Creature",),
        subtypes=(), power=4, toughness=4, produces=frozenset(),
    )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2    # ZONE_BATTLEFIELD
    ZL = 1    # ZONE_LIBRARY

    # ---- Python: filler in library (id=0), big creature on p0 bf (id=1),
    #      Bonders' Enclave on p0 bf (id=2). --------------------------------
    py_filler = py.new_object(filler_printing, owner_id=0, zone=Zone.LIBRARY)
    py_filler.summoning_sick = False
    py.players[0].library.append(py_filler)

    py_big = py.new_object(big_creature_printing, owner_id=0, zone=Zone.BATTLEFIELD)
    py_big.summoning_sick = False
    py_big.tapped = False
    py_big.damage = 0
    py_big.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_big)

    py_obj = py.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    py_obj.summoning_sick = False
    py_obj.tapped = False
    py_obj.damage = 0
    py_obj.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_obj)
    # Pre-fund: {3} generic (3 green coins).
    py.players[0].mana_pool.extend([ManaCoin("G", None)] * 3)

    # ---- Rust: same registration order -- filler in library (id=0),
    #      big creature on p0 bf (id=1), Bonders' Enclave on p0 bf (id=2). --
    rs.register_and_inject_object(
        {
            "name": "BE Library Filler",
            "card_types": ["Creature"],
            "power": 1, "toughness": 1,
        },
        0,   # controller = p0
        ZL,  # ZONE_LIBRARY
    )
    rs.register_and_inject_object(
        {
            "name": "BE Big Creature",
            "card_types": ["Creature"],
            "power": 4, "toughness": 4,
        },
        0,   # controller = p0
        ZB,  # battlefield
    )
    rs.clear_summoning_sick_for_player(0)

    rs_id = rs.register_and_inject_object(
        {
            "name": "Bonders' Enclave",
            "card_types": ["Land"],
            "activated_abilities": [
                {
                    "cost": {
                        "mana": {"generic": 3},
                        "tap_self": True,
                    },
                    "effect": {
                        "kind": "draw_cards",
                        "count": 1,
                    },
                    "is_mana_ability": False,
                }
            ],
        },
        0,   # controller = p0
        ZB,  # battlefield
    )
    rs.clear_summoning_sick_for_player(0)
    rs.add_mana(0, "G", 3)

    # Baseline checks.
    assert len(py.battlefield) == 2, (
        "Battlefield must start with 2 permanents (big creature + Bonders' Enclave)"
    )
    assert len(py.players[0].library) == 1, (
        "Library must start with 1 filler card"
    )
    assert rs.battlefield_sizes[0] == 2
    assert rs.library_sizes[0] == 1
    assert rs.graveyard_sizes[0] == 0

    # Verify the gate condition IS satisfied (power-4 creature is present).
    from mtg_bot.game import effective_power
    has_ge4 = any(
        effective_power(py, o) >= 4
        for o in py.battlefield
        if o.controller_id == 0 and o.printing.is_creature
    )
    assert has_ge4, (
        "Gate condition must be satisfied: p0 must control a creature with "
        "power >= 4 before activation"
    )

    # ---- Python: activate. -----------------------------------------------
    _activate_ability(py, 0, py_obj.id, aa_idx)
    assert len(py.stack) == 1, (
        "Bonders' Enclave activation must push one StackItem (non-mana DrawCards)"
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
        "Bonders' Enclave activation must push one stack item (non-mana DrawCards)"
    )
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0

    # ---- Verify zone moves on BOTH engines. ------------------------------
    py_p0_bf = len(py.battlefield)
    py_p0_lib = len(py.players[0].library)
    py_p0_hand = len(py.players[0].hand)
    rs_p0_bf = rs.battlefield_sizes[0]
    rs_p0_lib = rs.library_sizes[0]
    rs_p0_hand = rs.hand_sizes[0]

    assert py_p0_bf == 2 and rs_p0_bf == 2, (
        f"Both permanents (big creature + Enclave tapped) must remain on "
        f"p0 battlefield on BOTH; py={py_p0_bf} rs={rs_p0_bf}"
    )
    assert py_p0_lib == 0 and rs_p0_lib == 0, (
        f"Library must be empty (filler drawn) on BOTH; "
        f"py={py_p0_lib} rs={rs_p0_lib}"
    )
    assert py_p0_hand == 1 and rs_p0_hand == 1, (
        f"Filler must be in p0 hand (drawn by DrawCards) on BOTH; "
        f"py={py_p0_hand} rs={rs_p0_hand}"
    )

    # Enclave must be tapped after activation (tap_self cost was paid).
    assert py_obj.tapped, (
        "Python: Bonders' Enclave must be tapped after activation (tap_self cost)"
    )
    assert rs.is_tapped(rs_id), (
        "Rust: Bonders' Enclave must be tapped after activation (tap_self cost)"
    )

    # ---- Full compare_fields byte-equality. ---------------------------
    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        "Bonders' Enclave {3},{T}: draw a card must be byte-equal across "
        "the WHOLE field view on BOTH engines; "
        f"diffs={diffs}"
    )
