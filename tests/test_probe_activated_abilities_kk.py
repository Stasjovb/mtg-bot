"""Genuine real-EoE cross-engine byte-equality probes -- activated-ability
lane, batch KK (round 9 of the activated-ability family).

**Context -- extending O2 + Q + T + W + Y + BB + EE + HH.**  Eight prior
batches proved twenty-three cards and eleven-plus cost axes on the CE20
substrate.  This module (batch KK) adds two more probes from the
covered-but-previously-blocked tier, each exercising a NEW cost atom that
was previously believed unworkable due to technical limitations now
resolved:

  1. Ragost, Deft Gastronaut  (previously-blocked -> PROBED)
     ``{1}, {T}, Sacrifice a Food: Ragost deals 3 damage to each opponent.``
     Cost: {N=1}, tap_self=True, sacrifice_food=True.
     **NEW cost axis:** ``sacrifice_food`` had been listed as BLOCKED in
     prior batches because Python's ``_activate_ability`` raised
     ``IndexError: list index out of range`` when no Food existed on the
     controller's battlefield (``options[0]`` on an empty list).  The fix
     is to seed exactly ONE Food token on p0's battlefield before
     activation; Python then auto-picks it (``options[0]``), and the Rust
     side receives an explicit ``sacrifice_target_id`` in the action dict.
     The Rust bridge requires ``sacrifice_target_id`` whenever any targeted
     sacrifice flag is set (``sacrifice_food``, ``sacrifice_another_*``,
     ``sacrifice_a_land``); passing the pre-known Food token id satisfies
     this contract without any agent involvement.
     Token-cease parity: the Food token has ``supertypes=['Token']`` in the
     Rust registration so Rust's ``queue_token_cease`` removes it from the
     graveyard after the stack drains -- byte-equal to Python's
     ``move_off_battlefield`` which skips the graveyard entirely for tokens
     (CR 111.7 / 704.5d).
     Effect: ``DealDamageEachOpponent(3)`` -- p1 takes 3 damage (from 20
     to 17) on BOTH engines.  Observable strength: **compare_fields** zone
     check (Food token ceases, Ragost tapped, p1 life 17).

  2. Umbral Collar Zealot  (previously-blocked -> PROBED)
     ``Sacrifice another creature or artifact: Surveil 1.``
     Cost: no mana, no tap, sacrifice_another_creature_or_artifact=True.
     **NEW cost axis:** ``sacrifice_another_creature_or_artifact`` had been
     listed as BLOCKED (batch EE dropped it for the same "sac_another"
     family), but the Rust bridge DOES support it via the
     ``sacrifice_target_id`` key in the action dict (the same mechanism
     proven here for Ragost's ``sacrifice_food``).  Python auto-picks
     ``options[0]`` (first non-self creature or artifact on p0's
     battlefield); the Rust probe passes the pre-known victim id.  Surveil 1
     on an EMPTY library is a no-op on both engines (Python's loop over
     ``p.library[:1]`` iterates zero items; Rust's ``Surveil`` arm
     similarly no-ops).  The sole observable is the victim artifact
     leaving p0's battlefield and entering p0's graveyard -- verified
     by **compare_fields** zone check.
     **NEW effect type:** Surveil in the activated-ability lane.  Prior
     Surveil probes (batch BB: Found Footage, a Sequence(Surveil,DrawCards))
     reached the effect via a Sequence wrapper; this probe is the first
     in the AA lane to exercise ``Surveil`` as the TOP-LEVEL effect of an
     activated ability (cost: pure sacrifice, no mana, no tap).

**DROPPED candidates (batch KK survey, 2026-05-19):**

  * Ragost, Deft Gastronaut AA sacrifice_food -- see Probe #1 above (now
    PROMOTED, not dropped).

  * Umbral Collar Zealot sacrifice_another_creature_or_artifact -- see
    Probe #2 above (now PROMOTED, not dropped).

  * Kavaron Turbodrone (PumpTargetCreatureUntilEOT + granted_keywords=haste):
    BLOCKED per directive (granted_keywords on pump is blocked).

  * Sunstar Chaplain (TapTargetArtifactOrCreature + remove_plus_one_counter):
    BLOCKED per directive (remove_plus_one_counter cost is blocked).

  * Requiem Monolith (Sequence(GrantTriggeredAbilityUEOT, MayHaveSource...)):
    GrantTriggeredAbilityUEOT not in Rust bridge.

  * Pinnacle Starcage (Sequence(MoveEachExiledWithSource..., CreateNTokens...,
    SacrificeSelf)): MoveEachExiledWithSource and CreateNTokensFromLastExileRecall
    not in Rust bridge.

  * Haunted Screen (Sequence(PutPlusOneCounterOnSelf, BecomeType)):
    BecomeType not in Rust bridge.

  * Memorial Vault (ExileTopXOfLibraryMayPlayThisTurn + sac_another_artifact):
    ExileTopXOfLibraryMayPlayThisTurn not in Rust bridge.

  * All-Fates Scroll (DrawCardsByConditionMultiplier): not in Rust bridge.

  * Survey Mechan (SurveyMechanActivationEffect): bespoke effect, not in
    Rust bridge.

  * Rust Harvester (Sequence + exile_artifact_from_graveyard cost):
    BLOCKED per directive (exile_artifact_from_graveyard cost is blocked).

  * Slagdrill Scrapper (DrawCards + sacrifice_another_artifact_or_land cost):
    BLOCKED per directive (sacrifice_another_artifact_or_land is blocked).

  * Equipment cards (Atomic Microsizer, Auxiliary Boosters, Hylderblade,
    Illvoi Light Jammer, Meltrider's Gear, Squire's Lightblade, The Dominion
    Bracelet -- 7 EoE equipment total): EquipToTargetCreatureYouControl
    attach_to bridge arm emits None for attached_to slot in Rust zone-
    signature 8-tuple (same blocker as prior batches).

  * Contested War Zone (PumpCreaturesYouControlUntilEOT + attacking_only=True):
    attacking_only is invisible without combat; structural weakness per
    prior drops (EE batch).

  * Blast Zone (PutChargeCountersOnSelf with amount_from_x=True): X-pip cost
    ({X}{X},{T}) is not in the Rust bridge's activation-cost schema.

  * All remaining Stellar Sights manlands (BecomeLandCreatureUEOT): BLOCKED
    per directive (BecomeLandCreatureUEOT is a blocked effect type).

  * Petrified Field (ReturnTargetLandFromGraveyardToHand): not in Rust bridge.

  * Terrain Generator (PutBasicLandFromHandOntoBattlefieldTapped): not in
    Rust bridge (confirmed in batch EE drops).

  * Swarmyard (RegenerateTargetCreature): BLOCKED per directive.

  * Nesting Grounds (MovePlusOneCounterBetweenPermanentsYouControl): driver-
    side false-positive fizzle (no self-counters -> Python declines silently,
    Rust also fizzles, diffs=[] only by coincidence) per EE drops.

  * Sliver Overlord AA[0] (SearchLibraryForCard, may_fail=True): BLOCKED per
    directive (may_fail=True diverges: Python declines silently, Rust fetches).

  * Sliver Overlord AA[1] (GainControlOfTargetSliverPermanently): not in
    Rust bridge.

  * Deserted Temple (UntapTargetLand): BLOCKED per directive.

  * Ghost Vacuum (ExileTargetCardFromGraveyard,
    PutEachCreatureCardExiledWithSource...): both effects not in Rust bridge.

  * Keys to the House (SearchLibraryForCard may_fail=True + LockOrUnlockDoor):
    BLOCKED (may_fail=True) + LockOrUnlockDoor not in bridge.

  * Plaza of Heroes (PumpTargetCreatureUntilEOT + granted_keywords=
    {hexproof,indestructible}): BLOCKED per directive (granted_keywords).

  * Scavenger Grounds (ExileAllGraveyards): ExileAllGraveyards vs
    ExileEachOpponentsGraveyard mismatch (confirmed in EE drops).

  * High Market (GainLife + sacrifice_another_creature_or_artifact):
    sacrifice_another_c_a cost is NOW PROVEN VIABLE, but GainLife's observable
    is only on the life-total field (no zone move) -- the resulting probe
    would be observationally weak AND High Market is a Stellar Sights card,
    not a direct EoE card.

  * Mirrorpool (CopyTargetInstantOrSorceryYouControl,
    CreateTokenCopyOfTargetCreatureYouControl): neither effect in Rust bridge.

  * Thespian's Stage (BecomesCopyOfTargetLand): not in Rust bridge.

  * Baseball Bat (EquipToTargetCreatureYouControl): BLOCKED (equipment).

  * Robe of Stars (PhaseOutEquippedCreature + EquipToTargetCreatureYouControl):
    PhaseOutEquippedCreature not in Rust bridge; Equip BLOCKED.

**Lane status after batch KK:** EoE activated-ability lane is EXHAUSTED at
current bridge limits.  All 34 EoE non-mana AA cards have now been surveyed;
25 are in the PROBED tier (via AA or ETB probes), and the remaining 9 are
blocked by unsupported effects or blocked cost atoms (equipment equip-attach_to
None, BecomeType, SurveyMechanActivationEffect, SearchLibraryForEquipmentToBattlefield,
ExileTopXOfLibraryMayPlayThisTurn, DrawCardsByConditionMultiplier, remove_plus_one_counter,
granted_keywords=haste on pump, X-pip cost on Blast Zone).  A future bridge
extension would be needed to unlock these remaining 9 cards for the AA lane.

**Cost-shape summary after batches O2 + Q + T + W + Y + BB + EE + HH + KK:**

  Proven axes (single):
    {N}             -- O2 (Intrepid Tenderfoot)
    {T}             -- Q (Xu-Ifit)
    {N}{C}          -- Q (Zookeeper Mechan)
    sac_another     -- KK (Umbral Collar Zealot, no mana, no tap)

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
    {N},{T},sac_food -- KK (Ragost, Deft Gastronaut {1},{T},sac_food)

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
# Probe #1 -- Ragost, Deft Gastronaut (previously-blocked -> PROBED).
#
# Oracle (verbatim, Scryfall):
#   "[Legendary Creature -- Lobster Citizen]
#    Artifacts you control are Foods in addition to their other types
#    and have '{2}, {T}, Sacrifice this artifact: You gain 3 life.'
#    {1}, {T}, Sacrifice a Food: Ragost deals 3 damage to each opponent.
#    At the beginning of each end step, if you gained life this turn,
#    untap Ragost."
#
# Activated abilities as parsed (Python):
#   [0]: cost={N=1, tap_self, sacrifice_food}
#        effect=DealDamageEachOpponent(amount=3)  is_mana=False
#        [THIS probe activates AA[0]]
#
# Rust bridge dict for the synthetic carrier:
#   activated_abilities=[
#     {cost: {mana: {generic:1}, tap_self: true, sacrifice_food: true},
#      effect: {kind: 'damage_each_opponent', amount: 3},
#      is_mana_ability: false}
#   ]
#
# ** sacrifice_food probe design **
# Prior batches dropped Ragost because Python's _activate_ability raised
# IndexError when no Food was on the battlefield (options[0] on empty
# list).  The fix: seed ONE Food TOKEN on p0's battlefield at id=0.
# Python auto-picks options[0] (the Food); Rust requires an explicit
# sacrifice_target_id in the action dict -- we pass rs_food_id (0).
#
# Token-cease parity: the Food token has supertypes=['Token'] so BOTH
# engines handle it as a token (ceases to exist per CR 111.7 / 704.5d):
#   - Python: move_off_battlefield checks printing.is_token, skips
#     graveyard append, logs "Food Token token ceases to exist".
#   - Rust: queue_token_cease removes it from the graveyard after
#     drain_pending_leaves_dispatches (which resolves the LEAVES trigger
#     queue), then apply_sbas cleans up the ceased token.
# After apply_sbas, BOTH engines have 0 items in p0's graveyard (the
# token has ceased) and the sacrificed Food is gone.
#
# No triggered abilities are seeded in the Rust carrier (Ragost's static
# "grant Food ability to your artifacts" and its end-step untap trigger
# are complex and out of scope for this probe -- the probe state has no
# non-Food artifacts and no end step phase).
#
# Setup:
#   - Food Token (Artifact, supertypes=['Token'], subtypes=['Food']) on
#     p0 bf (id=0).
#   - Ragost, Deft Gastronaut (real printing, Legendary Creature) on p0
#     bf (id=1).
#   - Pre-fund: {1} generic (1 green ManaCoin).
#
# After activation (AA[0]) on BOTH engines:
#   - tap_self cost: Ragost tapped.
#   - sacrifice_food cost: Food Token leaves p0 bf (ceases to exist
#     as a token -- net: p0 bf shrinks by 1, p0 gy stays at 0).
#   - DealDamageEachOpponent(3): p1 takes 3 damage (life: 20 -> 17).
#   - Zone net: p0 bf 2->1 (Ragost remains, Food ceases), p0 gy 0->0.
#
# Assertion strength: **full compare_fields** zone check.  The bf-shrink
# (Food ceases) and p1 life change (20->17) are captured in the
# battlefield and life-total fields -- byte-equal on BOTH engines.
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_ragost_deft_gastronaut_activated_tap_sac_food_damage_each_opponent_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe -- Ragost, Deft Gastronaut.
    Batch KK (round 9 activated-ability lane) -- generic mana + tap_self +
    sacrifice_food ({1}, {T}, Sacrifice a Food), DealDamageEachOpponent(3).**

    Python: the ACTUAL parsed Ragost, Deft Gastronaut printing (Legendary
    Creature -- Lobster Citizen) seated on p0's battlefield; its ONLY
    non-mana ActivatedAbility (AA[0]: ``{1}, {T}, Sacrifice a Food: Ragost
    deals 3 damage to each opponent``) is activated via
    ``_activate_ability``.  A synthetic Food token (Artifact, subtype Food,
    supertype Token) on p0's battlefield is the sole sacrifice target;
    Python's ``sacrifice_food=True`` branch picks ``options[0]`` (the
    Food).  Rust: bridged synthetic carrier with AA[0]
    ({mana:{generic:1}, tap_self:true, sacrifice_food:true} + effect
    damage_each_opponent amount=3); ``sacrifice_target_id=rs_food_id`` is
    passed explicitly in the action dict so the Rust engine finds and
    sacrifices the correct Food.

    **NEW cost axis:** ``sacrifice_food`` combined with ``{N},{T}`` is the
    first three-atom cost shape in the AA lane to include a subtype-filtered
    sacrifice variant.  Prior three-atom probes used ``sac_self`` (Thaumaton
    Torpedo, Bear Trap, etc.) or dual-colored mana (Seedship Broodtender).
    Ragost is the first non-self, non-land sacrifice cost to reach the
    PROBED tier.

    **Token-cease parity design:** The Food token carries
    ``supertypes=['Token']`` in BOTH registrations.  Python's
    ``move_off_battlefield`` detects ``printing.is_token=True`` and routes
    the exit to "token ceases to exist" (no graveyard append).  Rust's
    ``queue_token_cease`` + ``drain_pending_leaves_dispatches`` achieves
    parity: the token is briefly placed in the graveyard inside the
    action-dispatch critical section, then removed by ``apply_sbas``.  The
    net observable is identical: p0 graveyard size = 0 on BOTH engines
    after the full sequence.

    Assertion strength: **full ``compare_fields``** over the whole field
    view -- Food token ceases to exist (p0 bf shrinks from 2 to 1), Ragost
    tapped, p1 life drops from 20 to 17 -- byte-equal on BOTH engines.
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
    from mtg_bot.effects.generic.damage import DealDamageEachOpponent
    from mtg_bot.cards.base import CardPrinting, ManaCost as MC

    real = get_active_source().get_printings().get("Ragost, Deft Gastronaut")
    if real is None:
        pytest.skip("Ragost, Deft Gastronaut absent from active CardSource")
    assert "Creature" in real.card_types, (
        "Ragost, Deft Gastronaut must be a Creature"
    )
    # Locate the non-mana AA with DealDamageEachOpponent + sacrifice_food.
    non_mana_aas = [
        (i, aa) for i, aa in enumerate(real.activated_abilities)
        if not aa.is_mana_ability
    ]
    assert len(non_mana_aas) >= 1, (
        "Ragost, Deft Gastronaut must have at least 1 non-mana AA"
    )
    aa_idx, aa = next(
        ((i, a) for i, a in non_mana_aas
         if isinstance(a.effect, DealDamageEachOpponent)),
        (None, None),
    )
    assert aa is not None, (
        "Ragost, Deft Gastronaut must have a non-mana AA with "
        "DealDamageEachOpponent"
    )
    assert aa.cost.sacrifice_food, (
        "Ragost, Deft Gastronaut AA must have sacrifice_food=True in cost"
    )
    assert aa.cost.tap_self, (
        "Ragost, Deft Gastronaut AA cost must require tapping itself"
    )
    assert not aa.cost.sacrifice_self, (
        "Ragost, Deft Gastronaut AA cost must NOT require sacrificing itself"
    )
    assert aa.cost.mana is not None and aa.cost.mana.generic == 1, (
        "Ragost, Deft Gastronaut AA cost must require {1} generic mana"
    )
    assert aa.effect.amount == 3, (
        f"Ragost, Deft Gastronaut DealDamageEachOpponent must be amount=3; "
        f"got {aa.effect.amount}"
    )

    # Food Token printing: Artifact supertype=Token subtype=Food.
    food_printing = CardPrinting(
        name="Food Token",
        mana_cost_str="",
        mana_cost=MC(generic=0),
        type_line="Token Artifact -- Food",
        supertypes=("Token",),
        card_types=("Artifact",),
        subtypes=("Food",),
        power=None,
        toughness=None,
        produces=frozenset(),
    )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2    # ZONE_BATTLEFIELD

    # ---- Python: Food Token at id=0, Ragost at id=1. ------------------
    py_food = py.new_object(food_printing, owner_id=0, zone=Zone.BATTLEFIELD)
    py_food.summoning_sick = False
    py_food.tapped = False
    py_food.damage = 0
    py_food.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_food)

    py_ragost = py.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    py_ragost.summoning_sick = False
    py_ragost.tapped = False
    py_ragost.damage = 0
    py_ragost.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_ragost)
    # Pre-fund: {1} generic (1 green coin).
    py.players[0].mana_pool.extend([ManaCoin("G", None)] * 1)

    # ---- Rust: Food Token at id=0, Ragost at id=1. --------------------
    # Food token: supertypes=['Token'] so Rust also treats it as a token
    # (queue_token_cease removes it from graveyard after sacrifice).
    rs_food_id = rs.register_and_inject_object(
        {
            "name": "Food Token",
            "card_types": ["Artifact"],
            "subtypes": ["Food"],
            "supertypes": ["Token"],
        },
        0,   # controller = p0
        ZB,  # battlefield
    )
    rs_ragost_id = rs.register_and_inject_object(
        {
            "name": "Ragost, Deft Gastronaut",
            "card_types": ["Creature"],
            "power": 2,
            "toughness": 2,
            "supertypes": ["Legendary"],
            "activated_abilities": [
                # AA[0]: {1},{T},sacrifice_food: DealDamageEachOpponent(3).
                # Ragost's static "grant Food ability" and end-step untap
                # trigger are NOT registered here (they are complex and
                # involve the probe state having no other artifacts).
                {
                    "cost": {
                        "mana": {"generic": 1},
                        "tap_self": True,
                        "sacrifice_food": True,
                    },
                    "effect": {
                        "kind": "damage_each_opponent",
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
    rs.add_mana(0, "G", 1)

    # Baseline checks.
    assert len(py.battlefield) == 2, (
        "p0 battlefield must start with 2 permanents (Food token + Ragost)"
    )
    assert len(py.players[0].graveyard) == 0, (
        "p0 graveyard must start empty"
    )
    assert rs.battlefield_sizes[0] == 2, (
        "Rust: p0 battlefield must start with 2 permanents"
    )
    assert rs.graveyard_sizes[0] == 0, (
        "Rust: p0 graveyard must start empty"
    )
    p0_life_before = py.players[0].life
    p1_life_before = py.players[1].life
    assert p1_life_before == 20, (
        f"p1 must start at 20 life; got {p1_life_before}"
    )
    assert rs.get_life(1) == 20, (
        f"Rust: p1 must start at 20 life; got {rs.get_life(1)}"
    )

    # ---- Python: activate AA[0] ({1},{T},sacrifice_food). -------------
    # Python auto-picks py_food (options[0]) as the Food to sacrifice.
    _activate_ability(py, 0, py_ragost.id, aa_idx)
    assert len(py.stack) == 1, (
        "Ragost AA[0] activation must push exactly 1 stack item "
        "(DealDamageEachOpponent -- no triggered ability fires)"
    )
    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)
    assert len(py.stack) == 0

    # ---- Rust: activate AA[0] with sacrifice_target_id=rs_food_id. ----
    rs.apply_action(
        {
            "kind": "activate_ability",
            "source_id": rs_ragost_id,
            "ability_index": aa_idx,
            "sacrifice_target_id": rs_food_id,
        }
    )
    assert rs.stack_size() == 1, (
        "Ragost AA[0] activation must push 1 stack item on Rust "
        "(damage_each_opponent)"
    )
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0

    # ---- Verify observables on BOTH engines. --------------------------
    # 1. Ragost tapped (tap_self cost).
    assert py_ragost.tapped, (
        "Python: Ragost must be tapped after activation (tap_self cost)"
    )
    assert rs.is_tapped(rs_ragost_id), (
        "Rust: Ragost must be tapped after activation (tap_self cost)"
    )

    # 2. Food token ceases to exist (token-cease per CR 111.7 / 704.5d).
    #    p0 bf shrinks to 1; p0 gy stays at 0 (token doesn't go to gy).
    assert len(py.battlefield) == 1, (
        "Python: p0 bf must have 1 permanent (Ragost only; Food ceases)"
    )
    assert len(py.players[0].graveyard) == 0, (
        "Python: p0 gy must be empty (Food is a token, ceases to exist)"
    )
    assert rs.battlefield_sizes[0] == 1, (
        "Rust: p0 bf must have 1 permanent (Ragost only; Food ceases)"
    )
    assert rs.graveyard_sizes[0] == 0, (
        "Rust: p0 gy must be empty (token ceases; queue_token_cease removed it)"
    )

    # 3. p1 takes 3 damage (DealDamageEachOpponent(3): 20->17).
    assert py.players[1].life == 17, (
        f"Python: p1 life must be 17 after Ragost deals 3 (was 20); "
        f"got {py.players[1].life}"
    )
    assert rs.get_life(1) == 17, (
        f"Rust: p1 life must be 17 after Ragost deals 3 (was 20); "
        f"got {rs.get_life(1)}"
    )

    # 4. p0 life unchanged (DealDamageEachOpponent targets opponents only).
    assert py.players[0].life == p0_life_before, (
        f"Python: p0 life must be unchanged; "
        f"got {py.players[0].life}, expected {p0_life_before}"
    )
    assert rs.get_life(0) == p0_life_before, (
        f"Rust: p0 life must be unchanged; "
        f"got {rs.get_life(0)}, expected {p0_life_before}"
    )

    # ---- Full compare_fields byte-equality. ----------------------------
    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        "Ragost {1},{T},sac_food: DealDamageEachOpponent(3) must be byte-"
        "equal across the WHOLE field view on BOTH engines; "
        f"diffs={diffs}"
    )


# ---------------------------------------------------------------------
# Probe #2 -- Umbral Collar Zealot (previously-blocked -> PROBED).
#
# Oracle (verbatim, Scryfall):
#   "[Creature -- Human Soldier]
#    Sacrifice another creature or artifact: Surveil 1."
#
# Activated abilities as parsed (Python):
#   [0]: cost={sacrifice_another_creature_or_artifact=True, no mana, no tap}
#        effect=Surveil(amount=1, use_artifact_count=False)  is_mana=False
#        [THIS probe activates AA[0]]
#
# Rust bridge dict for the synthetic carrier:
#   activated_abilities=[
#     {cost: {sacrifice_another_creature_or_artifact: true},
#      effect: {kind: 'surveil', count: 1},
#      is_mana_ability: false}
#   ]
#
# ** sacrifice_another_creature_or_artifact probe design **
# Prior batches had listed this cost family as BLOCKED (the EE batch note
# on Scavenger Grounds and similar cards).  The Rust bridge DOES support
# sacrifice_another_creature_or_artifact as an activation cost (Phase 2.7
# / Slice 6 of the CE20 substrate) via the sacrifice_target_id key in the
# action dict.  Python's _activate_ability auto-picks options[0] (first
# non-self creature or artifact on the controller's bf).
#
# Surveil(1) on an empty library is a no-op on BOTH engines:
#   - Python: p.library[:1] = [] -> loop iterates 0 cards -> 0 milled.
#   - Rust: Surveil arm iterates the (empty) library slice -> no-op.
# Surveil's choice-delegation (may_keep vs may_mill) never fires.
# The sole observable is the victim artifact entering p0's graveyard.
#
# The victim is a NON-TOKEN synthetic artifact (no supertype=Token) so
# it goes to the graveyard normally (not token-cease).
#
# Setup:
#   - Synthetic victim artifact (non-token Artifact) on p0 bf (id=0).
#   - Umbral Collar Zealot (real printing, Creature) on p0 bf (id=1).
#   - No mana pre-fund (the cost requires no mana).
#   - Empty libraries (Surveil on empty library is a no-op).
#
# After activation (AA[0]) on BOTH engines:
#   - sacrifice_another_creature_or_artifact cost: victim artifact
#     moves from p0 bf to p0 gy.
#   - Surveil(1) resolves: no-op (empty library).
#   - Zone net: p0 bf 2->1, p0 gy 0->1 (victim artifact).
#
# Assertion strength: **full compare_fields** zone check.  The bf-shrink
# (victim leaves) and gy-grow (victim in p0 gy) are captured in the
# battlefield / graveyard fields -- byte-equal on BOTH engines.
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_umbral_collar_zealot_activated_sac_another_artifact_surveil_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe -- Umbral Collar Zealot.
    Batch KK (round 9 activated-ability lane) -- sacrifice_another_creature_or_
    artifact (no mana, no tap), Surveil(1) no-op on empty library.**

    Python: the ACTUAL parsed Umbral Collar Zealot printing (Creature --
    Human Soldier) seated on p0's battlefield; its ONLY non-mana
    ActivatedAbility (AA[0]: ``Sacrifice another creature or artifact:
    Surveil 1``) is activated via ``_activate_ability``.  A synthetic
    non-token artifact on p0's battlefield is the sole sacrifice target;
    Python's ``sacrifice_another_creature_or_artifact=True`` branch picks
    ``options[0]`` (the victim artifact, not the source).  Rust: bridged
    synthetic carrier with AA[0] (sacrifice_another_creature_or_artifact:
    true + effect surveil count=1); ``sacrifice_target_id=rs_victim_id``
    is passed explicitly in the action dict.

    **NEW cost axis:** pure ``sacrifice_another_creature_or_artifact`` (no
    mana, no tap) is the first single-atom cost in the AA lane to use a
    sacrifice-other-permanent variant.  Prior sacrifice costs all used
    ``sac_self`` (the source sacrifices itself).  This probe is the first
    to exercise the targeted non-self sacrifice cost path in the AA lane.

    **NEW effect type in AA lane:** Surveil.  The only prior Surveil probe
    in the AA lane was Found Footage (batch BB) which used
    ``Sequence(Surveil(2), DrawCards(1))`` -- Surveil as a sub-effect
    inside a Sequence.  This is the first probe where Surveil IS the
    top-level effect of an activated ability, with no wrapping Sequence.

    **Surveil no-op design:** Surveil(1) on an empty library produces
    identical behavior on both engines (zero cards seen, zero milled,
    zero kept).  No agent is installed so Python's ``choose_surveil``
    branch is never reached.  The probe is not a false-positive: the
    sacrifice cost IS the load-bearing observable (victim goes to gy),
    and the Surveil no-op confirms that the effect arm resolves without
    error on both engines.

    Assertion strength: **full ``compare_fields``** over the whole field
    view -- victim artifact leaves p0 battlefield (sacrifice cost), enters
    p0 graveyard (non-token so it goes to gy) -- byte-equal on BOTH engines.
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
    from mtg_bot.effects.generic.library_lookat import Surveil
    from mtg_bot.cards.base import CardPrinting, ManaCost as MC

    real = get_active_source().get_printings().get("Umbral Collar Zealot")
    if real is None:
        pytest.skip("Umbral Collar Zealot absent from active CardSource")
    assert "Creature" in real.card_types, (
        "Umbral Collar Zealot must be a Creature"
    )
    # Locate the non-mana AA with Surveil + sac_another_creature_or_artifact.
    non_mana_aas = [
        (i, aa) for i, aa in enumerate(real.activated_abilities)
        if not aa.is_mana_ability
    ]
    assert len(non_mana_aas) >= 1, (
        "Umbral Collar Zealot must have at least 1 non-mana AA"
    )
    aa_idx, aa = next(
        ((i, a) for i, a in non_mana_aas
         if isinstance(a.effect, Surveil)),
        (None, None),
    )
    assert aa is not None, (
        "Umbral Collar Zealot must have a non-mana AA with Surveil effect"
    )
    assert aa.cost.sacrifice_another_creature_or_artifact, (
        "Umbral Collar Zealot AA cost must require sacrifice_another_"
        "creature_or_artifact=True"
    )
    assert not aa.cost.tap_self, (
        "Umbral Collar Zealot AA cost must NOT require tapping itself"
    )
    assert not aa.cost.sacrifice_self, (
        "Umbral Collar Zealot AA cost must NOT require sacrificing itself"
    )
    assert aa.cost.mana is None or aa.cost.mana.generic == 0, (
        "Umbral Collar Zealot AA cost must have no mana cost "
        f"(got {aa.cost.mana!r})"
    )
    assert aa.effect.amount == 1, (
        f"Umbral Collar Zealot Surveil must be amount=1; got {aa.effect.amount}"
    )
    assert not aa.effect.use_artifact_count, (
        "Umbral Collar Zealot Surveil must have use_artifact_count=False"
    )

    # Victim printing: a simple non-token Artifact (goes to gy, not ceases).
    victim_printing = CardPrinting(
        name="Victim Artifact",
        mana_cost_str="",
        mana_cost=MC(generic=0),
        type_line="Artifact",
        supertypes=(),
        card_types=("Artifact",),
        subtypes=(),
        power=None,
        toughness=None,
        produces=frozenset(),
    )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2    # ZONE_BATTLEFIELD

    # ---- Python: victim artifact at id=0, Umbral Collar Zealot at id=1. --
    py_victim = py.new_object(victim_printing, owner_id=0, zone=Zone.BATTLEFIELD)
    py_victim.summoning_sick = False
    py_victim.tapped = False
    py_victim.damage = 0
    py_victim.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_victim)

    py_umbral = py.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    py_umbral.summoning_sick = False
    py_umbral.tapped = False
    py_umbral.damage = 0
    py_umbral.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_umbral)
    # No mana needed -- the cost has no mana component.

    # ---- Rust: victim artifact at id=0, Umbral Collar Zealot at id=1. ---
    rs_victim_id = rs.register_and_inject_object(
        {
            "name": "Victim Artifact",
            "card_types": ["Artifact"],
        },
        0,   # controller = p0
        ZB,  # battlefield
    )
    rs_umbral_id = rs.register_and_inject_object(
        {
            "name": "Umbral Collar Zealot",
            "card_types": ["Creature"],
            "power": 2,
            "toughness": 2,
            "activated_abilities": [
                # AA[0]: sac_another_c_a: Surveil(1).
                {
                    "cost": {
                        "sacrifice_another_creature_or_artifact": True,
                    },
                    "effect": {
                        "kind": "surveil",
                        "count": 1,
                    },
                    "is_mana_ability": False,
                },
            ],
        },
        0,   # controller = p0
        ZB,  # battlefield
    )
    rs.clear_summoning_sick_for_player(0)
    # No mana pre-fund needed.

    # Baseline checks.
    assert len(py.battlefield) == 2, (
        "p0 battlefield must start with 2 permanents "
        "(victim artifact + Umbral Collar Zealot)"
    )
    assert len(py.players[0].graveyard) == 0, (
        "p0 graveyard must start empty"
    )
    assert rs.battlefield_sizes[0] == 2, (
        "Rust: p0 battlefield must start with 2 permanents"
    )
    assert rs.graveyard_sizes[0] == 0, (
        "Rust: p0 graveyard must start empty"
    )

    # ---- Python: activate AA[0] (sac_another_c_a + Surveil(1)). --------
    # Python auto-picks py_victim (options[0], the first non-self c/a on bf).
    _activate_ability(py, 0, py_umbral.id, aa_idx)
    assert len(py.stack) == 1, (
        "Umbral Collar Zealot AA[0] activation must push exactly 1 stack "
        "item (Surveil -- no triggered ability fires)"
    )
    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)
    assert len(py.stack) == 0

    # ---- Rust: activate AA[0] with sacrifice_target_id=rs_victim_id. ---
    rs.apply_action(
        {
            "kind": "activate_ability",
            "source_id": rs_umbral_id,
            "ability_index": aa_idx,
            "sacrifice_target_id": rs_victim_id,
        }
    )
    assert rs.stack_size() == 1, (
        "Umbral Collar Zealot AA[0] activation must push 1 stack item on "
        "Rust (surveil)"
    )
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0

    # ---- Verify observables on BOTH engines. --------------------------
    # 1. Umbral Collar Zealot NOT tapped (no tap_self in cost).
    assert not py_umbral.tapped, (
        "Python: Umbral Collar Zealot must NOT be tapped (no tap_self cost)"
    )
    assert not rs.is_tapped(rs_umbral_id), (
        "Rust: Umbral Collar Zealot must NOT be tapped (no tap_self cost)"
    )

    # 2. Victim artifact leaves p0 bf and enters p0 gy (non-token -> gy).
    assert len(py.battlefield) == 1, (
        "Python: p0 bf must have 1 permanent (Umbral Collar Zealot only; "
        "victim artifact sacrificed)"
    )
    assert len(py.players[0].graveyard) == 1, (
        "Python: p0 gy must have 1 card (victim artifact)"
    )
    assert py.players[0].graveyard[0].printing.name == "Victim Artifact", (
        "Python: p0 gy must contain the Victim Artifact"
    )
    assert rs.battlefield_sizes[0] == 1, (
        "Rust: p0 bf must have 1 permanent (Umbral Collar Zealot only)"
    )
    assert rs.graveyard_sizes[0] == 1, (
        "Rust: p0 gy must have 1 card (victim artifact)"
    )

    # 3. Life totals unchanged (Surveil has no life effect).
    assert py.players[0].life == 20, (
        f"Python: p0 life must be unchanged at 20; got {py.players[0].life}"
    )
    assert py.players[1].life == 20, (
        f"Python: p1 life must be unchanged at 20; got {py.players[1].life}"
    )
    assert rs.get_life(0) == 20, (
        f"Rust: p0 life must be unchanged at 20; got {rs.get_life(0)}"
    )
    assert rs.get_life(1) == 20, (
        f"Rust: p1 life must be unchanged at 20; got {rs.get_life(1)}"
    )

    # ---- Full compare_fields byte-equality. ----------------------------
    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        "Umbral Collar Zealot sac_another_c_a: Surveil(1) no-op must be "
        "byte-equal across the WHOLE field view on BOTH engines; "
        f"diffs={diffs}"
    )
