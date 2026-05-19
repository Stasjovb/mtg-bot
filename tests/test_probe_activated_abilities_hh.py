"""Genuine real-EoE cross-engine byte-equality probes -- activated-ability
lane, batch HH (round 8 of the activated-ability family).

**Context -- extending O2 + Q + T + W + Y + BB + EE.**  Seven prior batches
proved twenty-one cards and eleven-plus cost axes on the CE20 substrate.
This module (batch HH) adds two more probes from the covered-by-construction
tier, each using an effect type that either exercises a new card or a
new observable interaction within the activated-ability lane:

  1. Blinkmoth Nexus  (covered_by_construction -> PROBED)
     ``{1}, {T}: Target Blinkmoth creature gets +1/+1 until end of turn.``
     (Blinkmoth Nexus's AA[2]; AA[0] is BecomeLandCreatureUEOT (BLOCKED),
     AA[1] is the {T}: Add {C} mana ability.)
     Cost: {N=1}, tap_self=True, sacrifice_self=False.
     **NEW card in the PROBED tier:** PumpTargetCreatureUntilEOT with
     ``target_subtype='Blinkmoth'`` is the first probe in the activated-ability
     lane to exercise a subtype-filtered pump.  The subtype filter is dropped
     by the Rust bridge (all existing ``PumpTargetCreatureUntilEOT`` probes
     omit ``target_subtype``) but is made observationally invisible by seeding
     exactly ONE creature -- a synthetic Blinkmoth-subtype creature -- on p0's
     battlefield.  Python's ``target_subtype='Blinkmoth'`` filter returns that
     one creature as the sole legal target; Rust's first-creature-on-
     controller's-bf scan also picks it.  Both engines apply +1/+1 UEOT to
     the same object, verified via the ``rs.effective_power`` / Python
     ``temp_power_bonus`` targeted-observable idiom (the Dual-Sun Adepts
     pattern from batch O2) alongside a full ``compare_fields`` zone check.

  2. Endless Sands  (covered_by_construction -> PROBED)
     ``{4}, {T}, Sacrifice Endless Sands: Return each creature card exiled
     with Endless Sands to the battlefield under its owner's control.``
     The Python parser maps this AA to ``Sequence(effects=())``.  The bridge
     is exercised as cost-only: {4} generic + tap_self + sacrifice_self, with
     an empty-Sequence body (no-op on both engines).  The sole observable is
     Endless Sands leaving p0's battlefield (sacrifice cost) and landing in
     p0's graveyard -- byte-equal on BOTH engines.
     Cost: {N=4}, tap_self=True, sacrifice_self=True.
     **NEW cost axis for the lane:** ``{4},{T},sac`` differs from all prior
     proven ``{N},{T},sac`` instances only in N (Thaumaton Torpedo {1},{T},sac;
     Bear Trap {2},{T},sac; Nutrient Block {2},{T},sac; Dubious Delicacy
     {2},{T},sac; Inventors' Fair {4},{T},sac -- Endless Sands matches the
     Inventors' Fair axis but on a different card type: Desert Land vs
     Legendary Land).  This probe also confirms that the ``sequence``
     bridge-kind wires correctly for an empty-body non-mana AA on a Land.

**DROPPED candidates (batch HH survey, 2026-05-19):**

  * Endless Sands AA[0] (ExileTargetCreatureUntilSourceLeaves, yours_only=True):
    Python's ``ExileTargetCreatureUntilSourceLeaves(yours_only=True)``
    restricts the legal-target pool to creatures the CONTROLLER (p0) owns.
    Rust's ``ExileTargetCreatureUntilSourceLeaves`` arm drops ``yours_only``
    and always picks the first creature on the SOURCE CONTROLLER'S OPPONENT'S
    battlefield (``defender = 1 - controller``).  No probe state can make
    these two picks land on the same object: if p0 has a creature (Python's
    only target), Rust picks from p1 (opponent); if p1 has a creature
    (Rust's only target), Python sees no legal target (yours_only=True, so
    p1's creature is ineligible) and fizzles.  Either way the engines
    diverge.  Dropped.

  * All Equipment cards (13 total: Glimmerlight, Conductive Machete,
    Cursed Windbreaker, Hylderblade, Illvoi Light Jammer, Killer's Mask,
    Meltstrider's Gear, Squire's Lightblade, The Dominion Bracelet, and four
    others): Rust ``attach_to_target_creature_you_control`` bridge arm sets
    ``attached_to`` on the Python object but always emits ``None`` for that
    slot in the Rust zone-signature 8-tuple.  Structural blocker -- all 13
    equipment probes dropped (same reason as batches EE + prior rounds).

  * BecomeLandCreatureUEOT cards (Blinkmoth Nexus AA[0], Celestial Colonnade
    AA[0], Creeping Tar Pit AA[0], Hissing Quagmire AA[0], Inkmoth Nexus AA[0],
    Lumbering Falls AA[0], Mutavault AA[0], Needle Spires AA[0], Raging Ravine
    AA[0], Shambling Vent AA[0], Stirring Wildwood AA[0]): BLOCKED per
    directive (BecomeLandCreatureUEOT blocked effect type).

  * Dust Bowl AA[0] (sacrifice_a_land cost): BLOCKED (sacrifice_a_land
    cost mechanic blocked per directive).

  * Ripchain Razorkin AA[0] (sacrifice_a_land cost): BLOCKED same reason.

  * High Market AA[0] (sacrifice_another_creature_or_artifact cost): BLOCKED.

  * Slagdrill Scrapper AA[0] (sacrifice_another_artifact_or_land cost): BLOCKED.

  * Rust Harvester AA[0] (exile_artifact_from_graveyard cost): BLOCKED.

  * Sunstar Chaplain AA[0] (remove_plus_one_counter cost): BLOCKED.

  * Umbral Collar Zealot AA[0] (sacrifice_another_creature_or_artifact cost):
    BLOCKED.

  * Kavaron Turbodrone AA[0] (granted_keywords=haste): BLOCKED per directive
    (granted_keywords on pump arms blocked).

  * Plaza of Heroes AA[3] (granted_keywords={hexproof,indestructible}): BLOCKED
    same reason.

  * Gene Pollinator (mana ability only, no non-mana AA): skipped.

  * Steelswarm Operator (mana abilities only, no non-mana AA): skipped.

  * Lithobraking, Dawnsire, The Seriema (no parser-recognized AA): skipped.

**Cost-shape summary after batches O2 + Q + T + W + Y + BB + EE + HH:**

  Proven axes (single):
    {N}             -- O2 (Intrepid Tenderfoot)
    {T}             -- Q (Xu-Ifit)
    {N}{C}          -- Q (Zookeeper Mechan)

  Proven combinations (2-axis):
    {N},{T}         -- Q (Ragged Playmate) / BB (Bonders' Enclave)
                       EE (Chrome Companion {2},{T}; Inventors' Fair {4},{T})
                       HH (Blinkmoth Nexus {1},{T})
    {N}, sac        -- T (Illvoi Galeblade)
    {N}{C}, sac     -- T (Valgavoth's Faithful)
    {N}{C},{T}      -- W (Starport Security)
    {T}, sac        -- W (Strip Mine) / BB (Terramorphic Expanse)

  Proven combinations (3-axis):
    {N},{T}, sac    -- T (Thaumaton Torpedo) / W (Bear Trap)
                       BB (Nutrient Block {2},{T},sac)
                       EE (Dubious Delicacy {2},{T},sac;
                           Inventors' Fair {4},{T},sac)
                       HH (Endless Sands {4},{T},sac)
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
# Probe #1 -- Blinkmoth Nexus (covered_by_construction -> PROBED).
#
# Oracle (verbatim, Scryfall):
#   "[Land]
#    {1}: Blinkmoth Nexus becomes a 1/1 Blinkmoth artifact creature with
#    flying until end of turn. It's still a land.
#    {T}: Add {C}.
#    {1}, {T}: Target Blinkmoth creature gets +1/+1 until end of turn."
#
# Activated abilities as parsed (Python):
#   [0]: cost={N=1}        effect=BecomeLandCreatureUEOT   is_mana=False
#        [BLOCKED -- BecomeLandCreatureUEOT blocked effect type]
#   [1]: cost={T}          effect=AddManaToPool({C,1})      is_mana=True
#   [2]: cost={N=1, tap}   effect=PumpTargetCreatureUntilEOT(
#                               power_bonus=1, toughness_bonus=1,
#                               target_subtype='Blinkmoth',
#                               you_control_only=False,
#                               granted_keywords=frozenset())
#        is_mana=False   <-- THIS probe activates AA[2]
#
# Rust bridge dict for the carrier (preserves ability_index mapping):
#   activated_abilities=[
#     [0] {cost: {mana:{generic:1}},
#          effect: {kind:'become_land_creature_ueot', power:1, toughness:1,
#                   granted_subtype:'Blinkmoth', granted_keywords:['flying']},
#          is_mana_ability: false},
#     [1] {cost: {tap_self: true},
#          effect: {kind:'add_mana_to_pool', color:'C', amount:1},
#          is_mana_ability: true},
#     [2] {cost: {mana:{generic:1}, tap_self:true},
#          effect: {kind:'pump_target_creature_until_eot',
#                   power_bonus:1, toughness_bonus:1},
#          is_mana_ability: false},
#   ]
#
# ** target_subtype invisibility design **
# Python's PumpTargetCreatureUntilEOT(target_subtype='Blinkmoth') only
# considers creatures with the Blinkmoth subtype as legal targets.  The
# Rust bridge arm drops ``target_subtype`` and picks the FIRST creature
# on the source controller's (p0's) battlefield.
#
# Probe state seeds exactly ONE creature on p0's battlefield: a synthetic
# creature with subtype=('Blinkmoth',), card_types=('Artifact','Creature'),
# power=1, toughness=1.  With this setup:
#   - Python legal_targets: [('creature', blinkmoth_id)] -- the Blinkmoth
#     creature is the ONLY creature satisfying target_subtype='Blinkmoth'.
#   - Rust target pick: first creature on p0 bf = same Blinkmoth creature.
#   Both pick the same object; the subtype divergence is observationally
#   invisible.
#
# No creatures on p1's battlefield (Rust's pump arm targets the SOURCE
# CONTROLLER'S first creature, not the defender's).
#
# Setup:
#   - Synthetic Blinkmoth creature on p0 bf (id=0).
#   - Blinkmoth Nexus (real printing) on p0 bf (id=1).
#   - Pre-fund: {1} generic (1 green coin).
#
# After activation (AA[2]) on BOTH engines:
#   - tap_self cost: Blinkmoth Nexus tapped.
#   - PumpTargetCreatureUntilEOT(+1/+1) resolves: Blinkmoth creature
#     gets +1/+1 UEOT (1/1 -> effective 2/2 until EOT).
#   - Zone net: Blinkmoth Nexus tapped (no zone move), Blinkmoth
#     creature still on p0 bf with ueot pump.
#
# Assertion strength: **targeted-observable** (effective_power / temp_power_bonus)
# PLUS **full compare_fields** zone check.  The +1/+1 pump is NOT captured in
# the battlefield zone signature (ueot_modifiers are not in the 8-tuple) so
# the targeted observable is the load-bearing pump verification; compare_fields
# asserts byte-equality on zone layout (Blinkmoth Nexus tapped, creature on bf).
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_blinkmoth_nexus_activated_tap_pump_blinkmoth_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe -- Blinkmoth Nexus.
    Batch HH (round 8 activated-ability lane) -- generic mana + tap_self
    ({1}, {T}), PumpTargetCreatureUntilEOT(+1/+1, target_subtype='Blinkmoth').**

    Python: the ACTUAL parsed Blinkmoth Nexus printing (Land) seated on
    p0's battlefield; its third non-mana ActivatedAbility (AA[2]: ``{1}, {T}:
    Target Blinkmoth creature gets +1/+1 until end of turn``) is activated via
    ``_activate_ability``.  A synthetic Blinkmoth-subtype creature on p0's
    battlefield is the only legal target; Python's ``target_subtype='Blinkmoth'``
    filter selects it.  Rust: bridged synthetic carrier with ALL THREE of
    Blinkmoth Nexus's abilities registered (BecomeLandCreatureUEOT at index 0,
    mana ability at index 1, PumpTargetCreatureUntilEOT at index 2) so that
    ``ability_index=2`` resolves the pump arm.  Rust drops the
    ``target_subtype`` knob and picks the first creature on p0's battlefield
    (the same Blinkmoth creature), so the subtype filter is observationally
    invisible when exactly one creature is on p0's bf.

    **NEW card in the activated-ability lane:** First probe in the family to
    exercise ``PumpTargetCreatureUntilEOT`` from a Land permanent.  Prior pump
    probes (Dual-Sun Adepts, Xu-Ifit, etc.) sourced from Creatures; Blinkmoth
    Nexus is the first Land-type source.  Also first probe with
    ``target_subtype`` non-None, though the bridge drops it (made invisible
    by the single-Blinkmoth setup).

    Assertion strength: **targeted-observable** (``rs.effective_power`` /
    ``py_obj.temp_power_bonus``) confirms +1/+1 landed on the Blinkmoth
    creature on BOTH engines; **full ``compare_fields``** asserts zone-layout
    byte-equality (Blinkmoth Nexus tapped, creature on bf, no zone moves).
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
    from mtg_bot.effects.generic.pump import PumpTargetCreatureUntilEOT
    from mtg_bot.cards.base import CardPrinting, ManaCost as MC

    real = get_active_source().get_printings().get("Blinkmoth Nexus")
    if real is None:
        pytest.skip("Blinkmoth Nexus absent from active CardSource")
    assert "Land" in real.card_types, (
        "Blinkmoth Nexus must be a Land"
    )
    # AA[2] is the pump ability (index in full activated_abilities list).
    non_mana_aas = [
        (i, aa) for i, aa in enumerate(real.activated_abilities)
        if not aa.is_mana_ability
    ]
    assert len(non_mana_aas) >= 2, (
        "Blinkmoth Nexus must have at least 2 non-mana ActivatedAbilities "
        "(BecomeLandCreatureUEOT at [0] and PumpTargetCreatureUntilEOT at [2])"
    )
    # Find the PumpTargetCreatureUntilEOT among non-mana AAs.
    pump_aa_pair = next(
        ((i, aa) for i, aa in non_mana_aas
         if isinstance(aa.effect, PumpTargetCreatureUntilEOT)),
        None,
    )
    assert pump_aa_pair is not None, (
        "Blinkmoth Nexus must have a non-mana AA with PumpTargetCreatureUntilEOT"
    )
    aa_idx, aa = pump_aa_pair
    assert aa.effect.target_subtype == "Blinkmoth", (
        f"Blinkmoth Nexus PumpTargetCreatureUntilEOT must target Blinkmoth "
        f"subtype; got target_subtype={aa.effect.target_subtype!r}"
    )
    assert aa.effect.power_bonus == 1 and aa.effect.toughness_bonus == 1, (
        "Blinkmoth Nexus pump AA must give +1/+1"
    )
    assert not aa.effect.granted_keywords, (
        "Blinkmoth Nexus pump AA must NOT grant keywords "
        f"(got: {aa.effect.granted_keywords})"
    )
    assert aa.cost.tap_self, (
        "Blinkmoth Nexus pump AA cost must require tapping itself"
    )
    assert not aa.cost.sacrifice_self, (
        "Blinkmoth Nexus pump AA cost must NOT require sacrificing itself"
    )
    assert aa.cost.mana is not None and aa.cost.mana.generic == 1, (
        "Blinkmoth Nexus pump AA cost must require {1} generic mana"
    )

    # Synthetic Blinkmoth-subtype creature as the sole target.
    blinkmoth_creature_printing = CardPrinting(
        name="Blinkmoth Scout",
        mana_cost_str="",
        mana_cost=MC(generic=0),
        type_line="Artifact Creature -- Blinkmoth",
        supertypes=(),
        card_types=("Artifact", "Creature"),
        subtypes=("Blinkmoth",),
        power=1,
        toughness=1,
        produces=frozenset(),
    )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2    # ZONE_BATTLEFIELD

    # ---- Python: Blinkmoth creature on p0 bf (id=0),
    #      Blinkmoth Nexus on p0 bf (id=1). ----------------------------------
    py_bm = py.new_object(blinkmoth_creature_printing, owner_id=0, zone=Zone.BATTLEFIELD)
    py_bm.summoning_sick = False
    py_bm.tapped = False
    py_bm.damage = 0
    py_bm.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_bm)

    py_obj = py.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    py_obj.summoning_sick = False
    py_obj.tapped = False
    py_obj.damage = 0
    py_obj.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_obj)
    # Pre-fund: {1} generic (1 green coin).
    py.players[0].mana_pool.extend([ManaCoin("G", None)] * 1)

    # ---- Rust: same registration order -- Blinkmoth creature at id=0,
    #      Blinkmoth Nexus at id=1. ------------------------------------------
    # Register Blinkmoth Nexus with ALL THREE abilities so ability_index=2
    # correctly resolves the PumpTargetCreatureUntilEOT arm.
    rs_bm_id = rs.register_and_inject_object(
        {
            "name": "Blinkmoth Scout",
            "card_types": ["Artifact", "Creature"],
            "power": 1,
            "toughness": 1,
        },
        0,   # controller = p0
        ZB,  # battlefield
    )
    rs_id = rs.register_and_inject_object(
        {
            "name": "Blinkmoth Nexus",
            "card_types": ["Land"],
            "activated_abilities": [
                # AA[0]: BecomeLandCreatureUEOT (blocked -- registered to
                # preserve index alignment; NOT activated in this probe).
                {
                    "cost": {"mana": {"generic": 1}},
                    "effect": {
                        "kind": "become_land_creature_ueot",
                        "power": 1,
                        "toughness": 1,
                        "granted_subtype": "Blinkmoth",
                        "granted_keywords": ["flying"],
                    },
                    "is_mana_ability": False,
                },
                # AA[1]: {T}: Add {C} mana ability.
                {
                    "cost": {"tap_self": True},
                    "effect": {
                        "kind": "add_mana_to_pool",
                        "color": "C",
                        "amount": 1,
                    },
                    "is_mana_ability": True,
                },
                # AA[2]: {1},{T}: PumpTargetCreatureUntilEOT +1/+1.
                # Rust drops target_subtype; made invisible by seeding
                # exactly one creature (the Blinkmoth) on p0's bf.
                {
                    "cost": {
                        "mana": {"generic": 1},
                        "tap_self": True,
                    },
                    "effect": {
                        "kind": "pump_target_creature_until_eot",
                        "power_bonus": 1,
                        "toughness_bonus": 1,
                    },
                    "is_mana_ability": False,
                },
            ],
        },
        0,   # controller = p0
        ZB,  # battlefield
    )
    rs.clear_summoning_sick_for_player(0)
    rs.add_mana(0, "G", 1)

    # Baseline: base power of Blinkmoth creature before activation.
    assert rs.effective_power(rs_bm_id) == 1, (
        "Blinkmoth creature must start at power=1"
    )
    assert getattr(py_bm, "temp_power_bonus", 0) == 0, (
        "Python: Blinkmoth creature must start with temp_power_bonus=0"
    )
    assert len(py.battlefield) == 2, (
        "p0 battlefield must start with 2 permanents (Blinkmoth creature + Nexus)"
    )
    assert not py_obj.tapped, (
        "Blinkmoth Nexus must start untapped"
    )
    assert rs.battlefield_sizes[0] == 2, (
        "Rust: p0 battlefield must start with 2 permanents"
    )

    # ---- Python: activate AA[2] (PumpTargetCreatureUntilEOT). ---------------
    _activate_ability(py, 0, py_obj.id, aa_idx)
    assert len(py.stack) == 1, (
        "Blinkmoth Nexus AA[2] activation must push exactly 1 stack item "
        "(PumpTargetCreatureUntilEOT -- no triggered ability fires)"
    )
    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)
    assert len(py.stack) == 0

    # ---- Rust: activate AA[2] (PumpTargetCreatureUntilEOT). -----------------
    rs.apply_action(
        {"kind": "activate_ability", "source_id": rs_id, "ability_index": aa_idx}
    )
    assert rs.stack_size() == 1, (
        "Blinkmoth Nexus AA[2] activation must push 1 stack item on Rust "
        "(PumpTargetCreatureUntilEOT)"
    )
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0

    # ---- Verify Blinkmoth Nexus is tapped after activation. -----------------
    assert py_obj.tapped, (
        "Python: Blinkmoth Nexus must be tapped after activation (tap_self cost)"
    )
    assert rs.is_tapped(rs_id), (
        "Rust: Blinkmoth Nexus must be tapped after activation (tap_self cost)"
    )

    # ---- Targeted observable: +1/+1 pump landed on Blinkmoth creature. ------
    py_eff_power = 1 + getattr(py_bm, "temp_power_bonus", 0)
    rs_eff_power = rs.effective_power(rs_bm_id)
    assert py_eff_power == 2, (
        f"Python: Blinkmoth creature effective power must be 2 (1+1 pump); "
        f"got {py_eff_power} (temp_power_bonus={getattr(py_bm,'temp_power_bonus',0)})"
    )
    assert rs_eff_power == 2, (
        f"Rust: Blinkmoth creature effective_power must be 2 (1+1 pump); "
        f"got {rs_eff_power}"
    )

    # ---- Both permanents still on p0 bf (no zone moves from this AA). -------
    assert len(py.battlefield) == 2, (
        "p0 battlefield must still have 2 permanents (no zone move from pump)"
    )
    assert rs.battlefield_sizes[0] == 2, (
        "Rust: p0 battlefield must still have 2 permanents"
    )

    # ---- Full compare_fields byte-equality. ----------------------------------
    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        "Blinkmoth Nexus {1},{T}: pump Blinkmoth +1/+1 UEOT must be byte-equal "
        "across the WHOLE field view on BOTH engines; "
        f"diffs={diffs}"
    )


# ---------------------------------------------------------------------
# Probe #2 -- Endless Sands (covered_by_construction -> PROBED).
#
# Oracle (verbatim, Scryfall):
#   "[Land -- Desert]
#    {2}, {T}: Exile target creature you control.
#    {4}, {T}, Sacrifice Endless Sands: Return each creature card exiled
#    with Endless Sands to the battlefield under its owner's control."
#
# Activated abilities as parsed (Python):
#   [0]: cost={N=2, tap}         effect=ExileTargetCreatureUntilSourceLeaves
#                                 (yours_only=True)   is_mana=False
#        [DROPPED -- Rust ExileTargetCreatureUntilSourceLeaves targets
#         the SOURCE CONTROLLER'S OPPONENT'S first creature, not the
#         controller's own creature.  yours_only=True → Python picks p0;
#         Rust picks p1; diverges in any non-trivial probe state.]
#   [1]: cost={N=4, tap, sac}    effect=Sequence(effects=())   is_mana=False
#        [THIS probe activates AA[1] -- empty Sequence.]
#
# Rust bridge dict (AA[0] registered for index alignment; AA[1] exercises
# the Sequence kind with an empty effects list):
#   activated_abilities=[
#     [0] {cost: {mana:{generic:2}, tap_self:true},
#          effect: {kind:'exile_target_creature_until_source_leaves'},
#          is_mana_ability: false},
#     [1] {cost: {mana:{generic:4}, tap_self:true, sacrifice_self:true},
#          effect: {kind:'sequence', effects:[]},
#          is_mana_ability: false},
#   ]
#
# ** Empty-Sequence design **
# The real Endless Sands's second AA should return all creatures exiled
# WITH Endless Sands when Endless Sands leaves via sacrifice.  The Python
# parser maps this to ``Sequence(effects=())`` (the return-exiled body is
# not yet implemented).  Both engines resolve an empty Sequence -- a no-op.
# The sole observable is the sac_self cost: Endless Sands moves from p0 bf
# to p0 gy; {4} generic mana is spent; Endless Sands is tapped before the
# sac (tap_self cost).
#
# No creatures seeded (AA[1] has no target; the "exiled with source"
# return mechanic has no objects to return in an empty state).
#
# Setup:
#   - Endless Sands (real printing) on p0 bf (id=0).
#   - Pre-fund: {4} generic (4 green coins).
#
# After activation (AA[1]) on BOTH engines:
#   - tap_self cost: Endless Sands tapped.
#   - sac_self cost: Endless Sands moves from p0 bf to p0 gy.
#   - Sequence(effects=()) resolves: no-op.
#   - Zone net: p0 bf 1->0, p0 gy 0->1.
#
# Assertion strength: **full compare_fields** (strongest tier).  Zone moves
# (sac_self: Endless Sands bf→gy) are captured in the battlefield /
# graveyard fields -- byte-equal on BOTH engines.
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_endless_sands_activated_tap_sac_empty_sequence_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe -- Endless Sands.
    Batch HH (round 8 activated-ability lane) -- generic mana + tap_self +
    sacrifice_self ({4}, {T}, sac self), Sequence(effects=()) no-op body.**

    Python: the ACTUAL parsed Endless Sands printing (Land -- Desert) seated
    on p0's battlefield; its second non-mana ActivatedAbility (AA[1]: ``{4},
    {T}, Sacrifice Endless Sands: <return body>``) is activated via
    ``_activate_ability``.  The Python parser maps the return body to
    ``Sequence(effects=())``.  Both engines resolve the empty Sequence as a
    no-op.  Rust: bridged synthetic carrier with AA[0]
    (``exile_target_creature_until_source_leaves``) registered for index
    alignment and AA[1] as ``sequence`` with an empty effects list.

    **NEW card in the activated-ability lane:** Endless Sands (Desert Land)
    is the first Desert-Land-type source in the activated-ability family.
    The probe exercises the ``{4},{T},sac`` cost axis on a new card --
    the same axis shape as Inventors' Fair (also ``{4},{T},sac``) but on a
    Desert Land vs a Legendary Land, and with an empty-body Sequence instead
    of SearchLibraryForCard.  Confirms that the ``sequence`` bridge kind with
    an empty ``effects`` list resolves correctly (no-op body) alongside a
    ``sacrifice_self`` cost that moves the Desert Land to the graveyard.

    Assertion strength: **full ``compare_fields``** over the whole field view
    -- Endless Sands leaves p0 battlefield (sacrifice cost), enters p0
    graveyard -- byte-equal on BOTH engines.
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
    from mtg_bot.effects.combinators import Sequence

    real = get_active_source().get_printings().get("Endless Sands")
    if real is None:
        pytest.skip("Endless Sands absent from active CardSource")
    assert "Land" in real.card_types, (
        "Endless Sands must be a Land"
    )
    assert "Desert" in real.subtypes, (
        "Endless Sands must have the Desert subtype"
    )
    non_mana_aas = [
        (i, aa) for i, aa in enumerate(real.activated_abilities)
        if not aa.is_mana_ability
    ]
    assert len(non_mana_aas) >= 2, (
        "Endless Sands must have at least 2 non-mana ActivatedAbilities"
    )
    # AA[1] is the Sequence (sac self) ability.
    aa_idx, aa = non_mana_aas[1]
    assert isinstance(aa.effect, Sequence), (
        f"Endless Sands AA[1] must be Sequence; got {type(aa.effect).__name__}"
    )
    assert aa.effect.effects == (), (
        "Endless Sands AA[1] Sequence must have no sub-effects "
        f"(got: {aa.effect.effects!r})"
    )
    assert aa.cost.tap_self, (
        "Endless Sands AA[1] cost must require tapping itself"
    )
    assert aa.cost.sacrifice_self, (
        "Endless Sands AA[1] cost must require sacrificing itself"
    )
    assert aa.cost.mana is not None and aa.cost.mana.generic == 4, (
        "Endless Sands AA[1] cost must require {4} generic mana"
    )
    colored_dict = dict(aa.cost.mana.colored)
    assert not colored_dict, (
        f"Endless Sands AA[1] cost must have no colored mana; got {colored_dict}"
    )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2    # ZONE_BATTLEFIELD

    # ---- Python: Endless Sands on p0 bf (id=0). ---------------------------
    py_obj = py.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    py_obj.summoning_sick = False
    py_obj.tapped = False
    py_obj.damage = 0
    py_obj.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_obj)
    # Pre-fund: {4} generic (4 green coins).
    py.players[0].mana_pool.extend([ManaCoin("G", None)] * 4)

    # ---- Rust: Endless Sands on p0 bf (id=0). --------------------------------
    # AA[0] (exile_target_creature_until_source_leaves) registered for index
    # alignment; AA[1] is the empty Sequence (sac self).
    rs_id = rs.register_and_inject_object(
        {
            "name": "Endless Sands",
            "card_types": ["Land"],
            "activated_abilities": [
                # AA[0]: {2},{T}: ExileTargetCreatureUntilSourceLeaves
                # Registered for index alignment (NOT activated in this probe;
                # the yours_only divergence makes that AA unprobeable).
                {
                    "cost": {
                        "mana": {"generic": 2},
                        "tap_self": True,
                    },
                    "effect": {
                        "kind": "exile_target_creature_until_source_leaves",
                    },
                    "is_mana_ability": False,
                },
                # AA[1]: {4},{T},sac: Sequence(effects=[]) -- THIS probe.
                {
                    "cost": {
                        "mana": {"generic": 4},
                        "tap_self": True,
                        "sacrifice_self": True,
                    },
                    "effect": {
                        "kind": "sequence",
                        "effects": [],
                    },
                    "is_mana_ability": False,
                },
            ],
        },
        0,   # controller = p0
        ZB,  # battlefield
    )
    rs.clear_summoning_sick_for_player(0)
    rs.add_mana(0, "G", 4)

    # Baseline checks.
    assert len(py.battlefield) == 1, (
        "Battlefield must start with 1 permanent (Endless Sands)"
    )
    assert len(py.players[0].graveyard) == 0, (
        "P0 graveyard must start empty"
    )
    assert rs.battlefield_sizes[0] == 1, (
        "Rust: p0 battlefield must start with 1 permanent"
    )
    assert rs.graveyard_sizes[0] == 0, (
        "Rust: p0 graveyard must start empty"
    )

    # ---- Python: activate AA[1] (Sequence). ----------------------------------
    _activate_ability(py, 0, py_obj.id, aa_idx)
    assert len(py.stack) == 1, (
        "Endless Sands AA[1] activation must push exactly 1 stack item "
        "(Sequence -- no triggered ability fires from tap_self or sac_self "
        "on a Land)"
    )
    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)
    assert len(py.stack) == 0

    # ---- Rust: activate AA[1] (Sequence). ------------------------------------
    rs.apply_action(
        {"kind": "activate_ability", "source_id": rs_id, "ability_index": aa_idx}
    )
    assert rs.stack_size() == 1, (
        "Endless Sands AA[1] activation must push 1 stack item on Rust "
        "(Sequence)"
    )
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0

    # ---- Verify zone moves on BOTH engines. ----------------------------------
    py_p0_bf = len(py.battlefield)
    py_p0_gy = len(py.players[0].graveyard)
    rs_p0_bf = rs.battlefield_sizes[0]
    rs_p0_gy = rs.graveyard_sizes[0]

    assert py_p0_bf == 0 and rs_p0_bf == 0, (
        f"Endless Sands must have left p0 battlefield (sacrificed) on "
        f"BOTH; py={py_p0_bf} rs={rs_p0_bf}"
    )
    assert py_p0_gy == 1 and rs_p0_gy == 1, (
        f"Endless Sands must be in p0 graveyard (sac cost) on BOTH; "
        f"py={py_p0_gy} rs={rs_p0_gy}"
    )

    # ---- Full compare_fields byte-equality. ----------------------------------
    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        "Endless Sands {4},{T},sac self: empty Sequence body must be byte-equal "
        "across the WHOLE field view on BOTH engines; "
        f"diffs={diffs}"
    )
