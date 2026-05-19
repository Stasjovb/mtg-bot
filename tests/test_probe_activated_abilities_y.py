"""Genuine real-EoE cross-engine byte-equality probes -- activated-ability
lane, batch Y (round 5 of the activated-ability family).

**Context -- extending O2 + Q + T + W.**  Batches O2/Q/T/W proved nine
cost axes on the CE20 substrate:

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

This module (batch Y) extends the same lane with **three new probes**:

  1. Found Footage  (covered_by_construction -> PROBED)
     ``{2}, Sacrifice Found Footage: Surveil 2, then draw a card.``
     Cost: {N=2}, sac_self (no tap).
     **NEW effect type:** Sequence(Surveil(2), DrawCards(1)) via an
     activated ability -- the first probe in the lane that resolves
     a multi-step surveil-then-draw sequence as the activated effect.
     (Prior Surveil probes were all sorceries/instants.)

  2. Cryogen Relic  (covered_by_construction -> PROBED)
     ``{1}{U}, Sacrifice Cryogen Relic: Put a stun counter on target
     tapped creature.``
     Cost: {1}{U} (colored), sac_self (no tap).
     **NEW effect type:** PutStunCounterOnTappedCreature -- first probe
     in the lane to exercise the stun-counter bridge arm.  The card
     also has a LEAVES_BATTLEFIELD trigger (DrawCards(1)) that fires
     after the sac_self cost is paid; this probe validates that both
     the main activated effect AND the LB trigger resolve byte-equal.

  3. Seedship Broodtender  (covered_by_construction -> PROBED)
     ``{3}{B}{G}, Sacrifice Seedship Broodtender: Return target
     creature card from your graveyard to the battlefield.``
     Cost: {3}{B}{G} + sac_self.
     **NEW cost shape:** first probe in the activated-ability lane with
     TWO distinct colored mana requirements simultaneously (B AND G in
     the same mana cost).  All prior colored probes used at most one
     color (Q: {6}{R} on Zookeeper Mechan; W: {3}{W},{T} on Starport
     Security; T: {3}{B} on Valgavoth's Faithful).

All three cards are in the ``covered_by_construction`` tier at HEAD
(every Effect class they emit has a live Rust variant + bridge arm, but
no genuine real-EoE probe pins that card).  This module promotes them
to PROBED.

**Cost-shape summary after batches O2 + Q + T + W + Y:**

  Proven axes (single):
    {N}             -- O2 (Intrepid Tenderfoot)
    {T}             -- Q (Xu-Ifit)
    {N}{C}          -- Q (Zookeeper Mechan)

  Proven combinations (2-axis):
    {N},{T}         -- Q (Ragged Playmate)
    {N}, sac        -- T (Illvoi Galeblade)
    {N}{C}, sac     -- T (Valgavoth's Faithful)
    {N}{C},{T}      -- W (Starport Security)
    {T}, sac        -- W (Strip Mine)
    {N}{2C}, sac    -- Y (Seedship Broodtender)  ** NEW in this batch

  Proven combinations (3-axis):
    {N},{T}, sac    -- T (Thaumaton Torpedo) / W (Bear Trap)

**DROPPED candidates:**

  * Debris Field Crusher: ``{1}{R}: This creature gets +2/+0 until end
    of turn.`` -- cost shape {N}{C} without tap/sac is already proven
    (Zookeeper Mechan, batch Q).  The PumpSelfUntilEOT effect is applied
    on both engines but the current field-view signature does not expose
    UEOT power bonuses, so the proof is structurally weak (diffs==[])
    for the wrong reason.  Skipped in favour of probes with more
    observable outcomes.

  * Ragost, Deft Gastronaut: ``{1}, {T}: Deal 3 damage to each
    opponent.`` -- the parser encodes ``sacrifice_food=True`` in the
    cost.  Python's ``_activate_ability`` crashes at ``options[0]``
    when no Food permanent exists on the controller's battlefield.
    Skipped (sacrifice_food cost requires a Food artifact on the bf,
    adding one would change the field-view signature significantly).

  * Contested War Zone: ``{1}, {T}: Attacking creatures you control
    get +1/+0 until end of turn.`` -- the PumpCreaturesYouControlUntilEOT
    effect has ``attacking_only=True``, and with no attacking creatures
    in the probe setup neither engine shows any power change.  The probe
    would only observe the tap cost, not the effect, making it
    structurally weak.  Skipped.

  * Bonders' Enclave: ``{3}, {T}: Draw a card. Activate only if you
    control a creature with power 4 or greater.`` -- the
    ``requires_own_creature_power_at_least=4`` condition gate is
    silently ignored by Python's ``_activate_ability``.  Skipped
    (condition gate not exercised; probe would be dishonest).

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
# Probe #1 -- Found Footage (covered_by_construction -> PROBED).
#
# Oracle (verbatim, ``data/edge_of_eternities.json``):
#   "[Artifact]
#    {2}, Sacrifice Found Footage: Surveil 2, then draw a card."
# Parser -> one non-mana ActivatedAbility:
#   cost = ActivationCost(mana=ManaCost(generic=2), tap_self=False,
#                         sacrifice_self=True)
#   effect = Sequence([Surveil(amount=2), DrawCards(amount=1)])
#   is_mana_ability = False
#
# Rust bridge dict:
#   {"cost": {"mana": {"generic": 2}, "sacrifice_self": true},
#    "effect": {"kind": "sequence",
#               "effects": [{"kind": "surveil", "count": 2},
#                            {"kind": "draw_cards", "count": 1}]},
#    "is_mana_ability": false}
#
# Library setup: ONE filler card seeded in p0's library.
# Surveil(2) on a 1-card library looks at 1 card (keeps it, as the
# default no-agent decision keeps every surveilled card); DrawCards(1)
# then draws that card.
#
# After activation on BOTH engines:
#   - Found Footage pays sac_self cost -> moves to p0 GY
#   - Sequence resolves: Surveil(2) on 1-card lib = look at 1, keep 1;
#     DrawCards(1) draws the top card
#   - Zone net: bf 1->0 (sac), lib 1->0 (drawn), hand 0->1, gy 0->1
#
# ID ordering: filler registered first (id=0), Found Footage second
# (id=1) on BOTH engines (matching the established batch-T idiom for
# library-draw probes).
#
# **NEW effect type for the lane:** Sequence(Surveil, DrawCards) is the
# first probe in the activated-ability family to exercise a multi-step
# surveil-then-draw sequence as the resolved effect of an activated
# ability.  Prior surveil probes were all sorceries/instants in the
# sorcery/instant lane; this closes the surveil gap in the AA lane.
#
# Assertion strength: **full ``compare_fields``** (strongest tier).
# Zone moves (sac_self, lib->hand draw) are captured in the field view
# -- byte-equal across the whole field view on BOTH engines.
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_found_footage_activated_sac_surveil_draw_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe -- Found Footage.
    Batch Y (round 5 activated-ability lane) -- mana + sacrifice_self cost
    ({2}, sac self), Sequence(Surveil(2), DrawCards(1)).**

    Python: the ACTUAL parsed Found Footage printing (Artifact) seated on
    p0's battlefield; its non-mana ActivatedAbility (``{2}, Sacrifice
    Found Footage: Surveil 2, then draw a card``) is activated via
    ``_activate_ability``.  A single library filler is seeded for the
    draw.  Rust: bridged synthetic carrier with the
    ``{"mana": {"generic": 2}, "sacrifice_self": true}`` cost dict and
    the ``sequence([surveil(2), draw_cards(1)])`` effect.

    **NEW effect type for the activated-ability lane:** First probe in
    the family to exercise a multi-step ``Surveil + DrawCards`` sequence
    as the resolved effect of an activated ability end-to-end.  Validates
    that the Rust ``surveil`` and ``draw_cards`` bridge arms work inside
    a ``sequence`` resolved from an activated ability source.

    Assertion strength: **full ``compare_fields``** over the whole field
    view -- Found Footage leaves p0 bf (sacrifice cost), filler moves
    from library to hand (draw) -- byte-equal on BOTH engines.
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
    from mtg_bot.effects.generic.library_lookat import Surveil
    from mtg_bot.effects.generic.draw_mill import DrawCards
    from mtg_bot.cards.base import CardPrinting, ManaCost as MC

    real = get_active_source().get_printings().get("Found Footage")
    if real is None:
        pytest.skip("Found Footage absent from active CardSource")
    assert "Artifact" in real.card_types
    non_mana_aas = [
        (i, aa) for i, aa in enumerate(real.activated_abilities)
        if not aa.is_mana_ability
    ]
    assert non_mana_aas, (
        "Found Footage must have at least one non-mana ActivatedAbility"
    )
    aa_idx, aa = non_mana_aas[0]
    assert isinstance(aa.effect, Sequence), (
        f"genuine Found Footage non-mana AA must be Sequence; "
        f"got {type(aa.effect).__name__}"
    )
    assert len(aa.effect.effects) == 2, (
        "Found Footage Sequence must have exactly 2 sub-effects"
    )
    assert isinstance(aa.effect.effects[0], Surveil), (
        f"Found Footage Sequence first sub-effect must be Surveil; "
        f"got {type(aa.effect.effects[0]).__name__}"
    )
    assert aa.effect.effects[0].amount == 2, (
        "Found Footage Surveil must surveil exactly 2 cards"
    )
    assert isinstance(aa.effect.effects[1], DrawCards), (
        f"Found Footage Sequence second sub-effect must be DrawCards; "
        f"got {type(aa.effect.effects[1]).__name__}"
    )
    assert aa.effect.effects[1].amount == 1, (
        "Found Footage DrawCards must draw exactly 1 card"
    )
    # Verify cost: {2} + sac_self, no tap.
    assert not aa.cost.tap_self, (
        "Found Footage AA cost must NOT require tapping itself"
    )
    assert aa.cost.sacrifice_self, (
        "Found Footage AA cost must require sacrificing itself"
    )
    assert aa.cost.mana is not None and aa.cost.mana.generic == 2, (
        "Found Footage AA cost must require {2} generic mana"
    )
    colored_dict = dict(aa.cost.mana.colored)
    assert not colored_dict, (
        f"Found Footage AA cost must have no colored mana; got {colored_dict}"
    )
    assert not real.triggered_abilities, (
        "Found Footage must have no triggered abilities (clean probe)"
    )

    # A draw filler seeded in p0's library.
    filler_printing = CardPrinting(
        name="FF Draw Filler", mana_cost_str="", mana_cost=MC(generic=0),
        type_line="Creature", supertypes=(), card_types=("Creature",),
        subtypes=(), power=1, toughness=1, produces=frozenset(),
    )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2    # ZONE_BATTLEFIELD

    # ---- Python: filler in library (id=0), Found Footage on p0 bf (id=1). ----
    py_filler = py.new_object(filler_printing, owner_id=0, zone=Zone.LIBRARY)
    py_filler.summoning_sick = False  # library card, not freshly ETB'd
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
    #      Found Footage in battlefield (id=1). ----------------------------
    rs.register_and_inject_object(
        {
            "name": "FF Draw Filler",
            "card_types": ["Creature"],
            "power": 1, "toughness": 1,
        },
        0,   # controller = p0
        1,   # ZONE_LIBRARY
    )
    rs_id = rs.register_and_inject_object(
        {
            "name": "Found Footage",
            "card_types": ["Artifact"],
            "activated_abilities": [
                {
                    "cost": {
                        "mana": {"generic": 2},
                        "sacrifice_self": True,
                    },
                    "effect": {
                        "kind": "sequence",
                        "effects": [
                            {"kind": "surveil", "count": 2},
                            {"kind": "draw_cards", "count": 1},
                        ],
                    },
                    "is_mana_ability": False,
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
        "Battlefield must start with 1 permanent (Found Footage)"
    )
    assert len(py.players[0].library) == 1, (
        "Library must start with 1 filler card"
    )
    assert rs.battlefield_sizes[0] == 1
    assert rs.library_sizes[0] == 1
    assert rs.graveyard_sizes[0] == 0

    # ---- Python: activate. -----------------------------------------------
    _activate_ability(py, 0, py_obj.id, aa_idx)
    assert len(py.stack) == 1, (
        "Found Footage activation must push one StackItem (non-mana)"
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
        "Found Footage activation must push one stack item (non-mana)"
    )
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
        f"Found Footage must have left p0 battlefield (sacrificed) on BOTH; "
        f"py={py_p0_bf} rs={rs_p0_bf}"
    )
    assert py_p0_lib == 0 and rs_p0_lib == 0, (
        f"Library must be empty (filler drawn) on BOTH; "
        f"py={py_p0_lib} rs={rs_p0_lib}"
    )
    assert py_p0_hand == 1 and rs_p0_hand == 1, (
        f"Filler must be in p0 hand (drawn by DrawCards) on BOTH; "
        f"py={py_p0_hand} rs={rs_p0_hand}"
    )
    assert py_p0_gy == 1 and rs_p0_gy == 1, (
        f"Found Footage must be in p0 graveyard (sac cost) on BOTH; "
        f"py={py_p0_gy} rs={rs_p0_gy}"
    )

    # ---- Full compare_fields byte-equality. ---------------------------
    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        "Found Footage {2}, sac self: surveil 2 then draw a card must be "
        "byte-equal across the WHOLE field view on BOTH engines; "
        f"diffs={diffs}"
    )


# ---------------------------------------------------------------------
# Probe #2 -- Cryogen Relic (covered_by_construction -> PROBED).
#
# Oracle (verbatim, ``data/edge_of_eternities.json``):
#   "[Artifact]
#    When Cryogen Relic enters the battlefield, draw a card.
#    When Cryogen Relic leaves the battlefield, draw a card.
#    {1}{U}, Sacrifice Cryogen Relic: Put a stun counter on target
#    tapped creature."
# Parser -> one non-mana ActivatedAbility:
#   cost = ActivationCost(mana=ManaCost(generic=1, colored=(('U',1),)),
#                         tap_self=False, sacrifice_self=True)
#   effect = PutStunCounterOnTappedCreature()
#   is_mana_ability = False
#
# Triggered abilities:
#   - ENTERS, IsSelf -> DrawCards(1)   [ETB]
#   - LEAVES_BATTLEFIELD, IsSelf -> DrawCards(1)   [LB]
#
# The ETB trigger fires when Cryogen Relic enters the battlefield.
# We inject it directly via ``register_and_inject_object`` (which
# places it on the battlefield without triggering ETB), so the ETB
# trigger does NOT fire in this probe.  Only the LB trigger fires --
# after the sac_self cost is paid, Cryogen Relic leaves the battlefield
# and the LB trigger DrawCards(1) goes on the stack.
#
# Rust bridge dict:
#   {"cost": {"mana": {"generic": 1, "U": 1}, "sacrifice_self": true},
#    "effect": {"kind": "put_stun_counter_on_tapped_creature"},
#    "is_mana_ability": false,
#    "triggered_abilities": [
#      {"event": "leaves_battlefield",
#       "predicate": {"kind": "source_is_self"},
#       "effect": {"kind": "draw_cards", "count": 1}}
#    ]}
#
# Setup: one library filler seeded in p0's library for the LB trigger
# DrawCards(1); one victim creature on p1's battlefield, already tapped,
# as the PutStunCounterOnTappedCreature target.
#
# ID ordering: filler (id=0), victim (id=1), Cryogen Relic (id=2) on
# BOTH engines so the zone signatures align.
#
# After activation on BOTH engines:
#   - sac_self cost: Cryogen Relic moves from p0 BF to p0 GY ->
#     LB trigger fires, DrawCards(1) goes on stack second (below AA)
#   - PutStunCounterOnTappedCreature resolves: victim gains 1 stun
#     counter
#   - LB trigger DrawCards(1) resolves: p0 draws the library filler
#   - Zone net: p0 bf 1->0 (sac), p0 gy 0->1 (Cryogen),
#     p0 lib 1->0 (drawn), p0 hand 0->1; p1 bf 1->1 (victim tapped+stunned)
#
# **NEW effect type for the lane:** PutStunCounterOnTappedCreature is
# the first probe in the activated-ability family to exercise the
# stun-counter bridge arm.  Prior counter probes were all sorceries or
# ETB triggers.
#
# Assertion strength: **full ``compare_fields``** (strongest tier).
# Both the stun counter on the victim (p1 bf) and the zone moves
# (sac_self p0 bf->gy, LB draw p0 lib->hand) are captured in the
# field view -- byte-equal on BOTH engines.
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_cryogen_relic_activated_colored_sac_stun_counter_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe -- Cryogen Relic.
    Batch Y (round 5 activated-ability lane) -- colored mana + sacrifice_self
    ({1}{U}, sac self), PutStunCounterOnTappedCreature + LB trigger
    DrawCards(1).**

    Python: the ACTUAL parsed Cryogen Relic printing (Artifact) seated on
    p0's battlefield; its non-mana ActivatedAbility (``{1}{U}, Sacrifice
    Cryogen Relic: Put a stun counter on target tapped creature``) is
    activated via ``_activate_ability`` targeting a pre-tapped victim
    creature on p1's battlefield.  The card's LEAVES_BATTLEFIELD trigger
    (``DrawCards(1)``) also fires and resolves; a single library filler
    is seeded for the draw.  Rust: bridged synthetic carrier with the
    ``{"mana": {"generic": 1, "U": 1}, "sacrifice_self": true}`` cost
    dict, the ``put_stun_counter_on_tapped_creature`` effect, and the
    LB trigger registered in ``triggered_abilities``.

    **NEW effect type for the activated-ability lane:** First probe in
    the family to exercise ``PutStunCounterOnTappedCreature`` as the
    resolved effect of an activated ability.  Also validates that the
    LEAVES_BATTLEFIELD trigger chain (LB trigger -> DrawCards(1)) is
    byte-equal across both engines in the same activation sequence.

    Assertion strength: **full ``compare_fields``** over the whole field
    view -- Cryogen Relic leaves p0 bf (sacrifice cost), victim gains a
    stun counter (PutStunCounterOnTappedCreature), p0 draws the library
    filler (LB trigger) -- byte-equal on BOTH engines.
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
    from mtg_bot.effects.generic.counters import PutStunCounterOnTappedCreature
    from mtg_bot.cards.base import CardPrinting, ManaCost as MC

    real = get_active_source().get_printings().get("Cryogen Relic")
    if real is None:
        pytest.skip("Cryogen Relic absent from active CardSource")
    assert "Artifact" in real.card_types
    non_mana_aas = [
        (i, aa) for i, aa in enumerate(real.activated_abilities)
        if not aa.is_mana_ability
    ]
    assert non_mana_aas, (
        "Cryogen Relic must have at least one non-mana ActivatedAbility"
    )
    aa_idx, aa = non_mana_aas[0]
    assert isinstance(aa.effect, PutStunCounterOnTappedCreature), (
        f"genuine Cryogen Relic non-mana AA must be PutStunCounterOnTappedCreature; "
        f"got {type(aa.effect).__name__}"
    )
    # Verify cost: {1}{U} + sac_self, no tap.
    assert not aa.cost.tap_self, (
        "Cryogen Relic AA cost must NOT require tapping itself"
    )
    assert aa.cost.sacrifice_self, (
        "Cryogen Relic AA cost must require sacrificing itself"
    )
    assert aa.cost.mana is not None and aa.cost.mana.generic == 1, (
        "Cryogen Relic AA cost must require {1} generic mana"
    )
    colored_dict = dict(aa.cost.mana.colored)
    assert colored_dict.get("U", 0) == 1, (
        f"Cryogen Relic AA cost must require 1 blue mana; "
        f"got colored={aa.cost.mana.colored}"
    )
    # Card has LB trigger (DrawCards); ETB trigger is bypassed by direct injection.
    assert real.triggered_abilities, (
        "Cryogen Relic must have triggered abilities (LB draw trigger)"
    )

    # Library filler for the LB trigger DrawCards(1).
    filler_printing = CardPrinting(
        name="CR Library Filler", mana_cost_str="", mana_cost=MC(generic=0),
        type_line="Creature", supertypes=(), card_types=("Creature",),
        subtypes=(), power=1, toughness=1, produces=frozenset(),
    )
    # Victim: pre-tapped creature on p1's battlefield.
    victim_printing = CardPrinting(
        name="CR Victim", mana_cost_str="", mana_cost=MC(generic=0),
        type_line="Creature", supertypes=(), card_types=("Creature",),
        subtypes=(), power=2, toughness=2, produces=frozenset(),
    )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2    # ZONE_BATTLEFIELD

    # ---- Python: filler in library (id=0), victim on p1 bf (id=1),
    #      Cryogen Relic on p0 bf (id=2). ----------------------------------
    py_filler = py.new_object(filler_printing, owner_id=0, zone=Zone.LIBRARY)
    py_filler.summoning_sick = False
    py.players[0].library.append(py_filler)

    py_victim = py.new_object(victim_printing, owner_id=1, zone=Zone.BATTLEFIELD)
    py_victim.summoning_sick = False
    py_victim.tapped = True    # must be tapped for PutStunCounterOnTappedCreature
    py_victim.damage = 0
    py_victim.controller_id = 1
    py_victim.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_victim)

    py_obj = py.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    py_obj.summoning_sick = False
    py_obj.tapped = False
    py_obj.damage = 0
    py_obj.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_obj)
    # Pre-fund: {1}{U} = 1 generic (green) + 1 blue.
    py.players[0].mana_pool.extend(
        [ManaCoin("U", None), ManaCoin("G", None)]
    )

    # ---- Rust: same registration order -- filler in p0 library (id=0),
    #      victim on p1 bf (id=1), Cryogen Relic on p0 bf (id=2). ---------
    rs.register_and_inject_object(
        {
            "name": "CR Library Filler",
            "card_types": ["Creature"],
            "power": 1, "toughness": 1,
        },
        0,   # controller = p0
        1,   # ZONE_LIBRARY
    )
    rs_victim_id = rs.register_and_inject_object(
        {
            "name": "CR Victim",
            "card_types": ["Creature"],
            "power": 2, "toughness": 2,
        },
        1,   # controller = p1
        ZB,
    )
    rs.clear_summoning_sick_for_player(1)
    rs.tap_object(rs_victim_id)   # victim must be tapped for the effect

    rs_id = rs.register_and_inject_object(
        {
            "name": "Cryogen Relic",
            "card_types": ["Artifact"],
            "activated_abilities": [
                {
                    "cost": {
                        "mana": {"generic": 1, "U": 1},
                        "sacrifice_self": True,
                    },
                    "effect": {
                        "kind": "put_stun_counter_on_tapped_creature",
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
    rs.add_mana(0, "U", 1)
    rs.add_mana(0, "G", 1)

    # Baseline checks.
    assert len(py.battlefield) == 2, (
        "Battlefield must start with 2 permanents (victim + Cryogen Relic)"
    )
    assert len(py.players[0].library) == 1, (
        "Library must start with 1 filler for the LB trigger draw"
    )
    assert rs.battlefield_sizes[0] == 1
    assert rs.battlefield_sizes[1] == 1
    assert rs.library_sizes[0] == 1
    assert rs.graveyard_sizes[0] == 0
    assert rs.is_tapped(rs_victim_id), (
        "Victim must be tapped before activation (target requirement)"
    )

    # ---- Python: activate (single victim as only legal stun target). -----
    _activate_ability(py, 0, py_obj.id, aa_idx)
    assert len(py.stack) == 2, (
        "Cryogen Relic activation must push 2 items: LB trigger + AA"
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
        "Cryogen Relic activation must push 2 stack items: LB trigger + AA"
    )
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0

    # ---- Verify zone moves and stun counter on BOTH engines. ------------
    py_p0_bf = sum(1 for o in py.battlefield if o.controller_id == 0)
    py_p1_bf = sum(1 for o in py.battlefield if o.controller_id == 1)
    py_p0_lib = len(py.players[0].library)
    py_p0_hand = len(py.players[0].hand)
    py_p0_gy = len(py.players[0].graveyard)
    rs_p0_bf = rs.battlefield_sizes[0]
    rs_p1_bf = rs.battlefield_sizes[1]
    rs_p0_lib = rs.library_sizes[0]
    rs_p0_hand = rs.hand_sizes[0]
    rs_p0_gy = rs.graveyard_sizes[0]

    assert py_p0_bf == 0 and rs_p0_bf == 0, (
        f"Cryogen Relic must have left p0 battlefield (sacrificed) on BOTH; "
        f"py={py_p0_bf} rs={rs_p0_bf}"
    )
    assert py_p1_bf == 1 and rs_p1_bf == 1, (
        f"Victim must still be on p1 battlefield on BOTH; "
        f"py={py_p1_bf} rs={rs_p1_bf}"
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
        f"Cryogen Relic must be in p0 graveyard on BOTH; "
        f"py={py_p0_gy} rs={rs_p0_gy}"
    )

    # Stun counter on the victim.
    py_victim_stun = getattr(py_victim, "stun_counters", 0)
    assert py_victim_stun == 1, (
        f"Victim must have 1 stun counter on Python; got {py_victim_stun}"
    )
    rs_victim_stun = rs.get_stun_counters(rs_victim_id)
    assert rs_victim_stun == 1, (
        f"Victim must have 1 stun counter on Rust; got {rs_victim_stun}"
    )

    # ---- Full compare_fields byte-equality. ---------------------------
    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        "Cryogen Relic {1}{U}, sac self: stun counter + LB draw must be "
        "byte-equal across the WHOLE field view on BOTH engines; "
        f"diffs={diffs}"
    )


# ---------------------------------------------------------------------
# Probe #3 -- Seedship Broodtender (covered_by_construction -> PROBED).
#
# Oracle (verbatim, ``data/edge_of_eternities.json``):
#   "[Creature -- Alien]
#    When Seedship Broodtender enters the battlefield, mill 3.
#    {3}{B}{G}, Sacrifice Seedship Broodtender: Return target creature
#    card from your graveyard to the battlefield."
# Parser -> one non-mana ActivatedAbility:
#   cost = ActivationCost(mana=ManaCost(generic=3,
#                                       colored=(('B',1),('G',1))),
#                         tap_self=False, sacrifice_self=True)
#   effect = ReturnCreatureFromYourGraveyardToBattlefield()
#   is_mana_ability = False
#
# Triggered abilities:
#   - ENTERS, IsSelf -> SelfMill(3)   [ETB]
#
# The ETB trigger fires when Seedship Broodtender enters the battlefield.
# We inject it directly via ``register_and_inject_object`` (which
# places it on the battlefield without triggering ETB), so the SelfMill(3)
# ETB trigger does NOT fire in this probe.
#
# Rust bridge dict:
#   {"cost": {"mana": {"generic": 3, "B": 1, "G": 1},
#             "sacrifice_self": true},
#    "effect": {"kind": "return_creature_from_your_graveyard_to_battlefield"},
#    "is_mana_ability": false}
#
# Mana supply: 1 black + 4 green (3 generic satisfied by green + 1 explicit
# green for the G pip).
#
# Setup: a filler creature seeded in p0's graveyard as the forced
# reanimate target; Seedship Broodtender on p0's battlefield.
#
# ID ordering: filler first (id=0), Seedship second (id=1) on BOTH.
#
# After activation on BOTH engines:
#   - Seedship Broodtender pays sac_self cost -> moves to p0 GY
#   - ReturnCreatureFromYourGraveyardToBattlefield reanimates filler
#     from p0 GY to p0 BF
#   - Zone net: bf 1->1 (Seedship out, filler in), gy 1->1 (filler
#     out, Seedship in) -- card-identity swap, captured in field-view
#     zone signatures.
#
# **NEW cost shape (two distinct colored mana simultaneously):**
# {3}{B}{G} is the first probe in the activated-ability family to
# require TWO distinct colored mana pips at the same time (B and G).
# Prior colored probes used at most one color:
#   - Q: {6}{R} (Zookeeper Mechan) -- single red pip
#   - W: {3}{W},{T} (Starport Security) -- single white pip + tap
#   - T: {3}{B} (Valgavoth's Faithful) -- single black pip
# This probe closes the "two-color" combination gap in the cost axis.
#
# Assertion strength: **full ``compare_fields``** (strongest tier).
# The card-identity swap (Seedship to GY, filler to BF) is captured
# in the zone signatures and matches byte-equal on BOTH engines.
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_seedship_broodtender_activated_dual_color_sac_reanimate_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe -- Seedship Broodtender.
    Batch Y (round 5 activated-ability lane) -- dual-colored mana +
    sacrifice_self ({3}{B}{G}, sac self),
    ReturnCreatureFromYourGraveyardToBattlefield.**

    Python: the ACTUAL parsed Seedship Broodtender printing (Creature)
    seated on p0's battlefield; its non-mana ActivatedAbility
    (``{3}{B}{G}, Sacrifice Seedship Broodtender: Return target creature
    card from your graveyard to the battlefield``) is activated via
    ``_activate_ability`` targeting the only creature in p0's graveyard.
    The card's ETB trigger (SelfMill(3)) is bypassed by direct injection.
    Rust: bridged synthetic carrier with the
    ``{"mana": {"generic": 3, "B": 1, "G": 1}, "sacrifice_self": true}``
    cost dict and the
    ``return_creature_from_your_graveyard_to_battlefield`` effect.

    **NEW cost shape (dual-color):** First probe in the activated-ability
    lane to require TWO distinct colored mana pips simultaneously (B and
    G in the same mana cost).  Validates that the Rust engine's mana
    payment correctly deducts colored pips from the pool when multiple
    colors are required, and that the sacrifice_self + two-color
    combination is fully byte-equal end-to-end.

    Assertion strength: **full ``compare_fields``** over the whole field
    view -- the card-identity swap (Seedship to p0 GY, filler reanimates
    to p0 BF) is byte-equal on BOTH engines.
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
    from mtg_bot.effects.generic.graveyard import ReturnCreatureFromYourGraveyardToBattlefield
    from mtg_bot.cards.base import CardPrinting, ManaCost as MC

    real = get_active_source().get_printings().get("Seedship Broodtender")
    if real is None:
        pytest.skip("Seedship Broodtender absent from active CardSource")
    assert "Creature" in real.card_types
    non_mana_aas = [
        (i, aa) for i, aa in enumerate(real.activated_abilities)
        if not aa.is_mana_ability
    ]
    assert non_mana_aas, (
        "Seedship Broodtender must have at least one non-mana ActivatedAbility"
    )
    aa_idx, aa = non_mana_aas[0]
    assert isinstance(aa.effect, ReturnCreatureFromYourGraveyardToBattlefield), (
        f"genuine Seedship Broodtender non-mana AA must be "
        f"ReturnCreatureFromYourGraveyardToBattlefield; "
        f"got {type(aa.effect).__name__}"
    )
    # Verify cost: {3}{B}{G} + sac_self, no tap.
    assert not aa.cost.tap_self, (
        "Seedship Broodtender AA cost must NOT require tapping itself"
    )
    assert aa.cost.sacrifice_self, (
        "Seedship Broodtender AA cost must require sacrificing itself"
    )
    assert aa.cost.mana is not None and aa.cost.mana.generic == 3, (
        "Seedship Broodtender AA cost must require {3} generic mana"
    )
    colored_dict = dict(aa.cost.mana.colored)
    assert colored_dict.get("B", 0) == 1, (
        f"Seedship Broodtender AA cost must require 1 black mana; "
        f"got colored={aa.cost.mana.colored}"
    )
    assert colored_dict.get("G", 0) == 1, (
        f"Seedship Broodtender AA cost must require 1 green mana; "
        f"got colored={aa.cost.mana.colored}"
    )
    # ETB trigger (SelfMill) is bypassed by direct injection -- present on card but not tested here.
    assert real.triggered_abilities, (
        "Seedship Broodtender must have triggered abilities (ETB SelfMill)"
    )

    rp = int(real.power)
    rt = int(real.toughness)

    # A filler creature seeded in p0's graveyard as the forced reanimate target.
    filler_printing = CardPrinting(
        name="SB GY Filler", mana_cost_str="", mana_cost=MC(generic=0),
        type_line="Creature", supertypes=(), card_types=("Creature",),
        subtypes=(), power=2, toughness=2, produces=frozenset(),
    )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2    # ZONE_BATTLEFIELD
    ZG = 3    # ZONE_GRAVEYARD

    # ---- Python: filler in p0 GY (id=0), Seedship on p0 BF (id=1). -----
    py_filler = py.new_object(filler_printing, owner_id=0, zone=Zone.GRAVEYARD)
    py_filler.summoning_sick = False
    py.players[0].graveyard.append(py_filler)

    py_obj = py.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    py_obj.summoning_sick = False
    py_obj.tapped = False
    py_obj.damage = 0
    py_obj.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_obj)
    # Pre-fund: {3}{B}{G} = 1 black + 4 green (3 generic + G pip all satisfied by green).
    py.players[0].mana_pool.extend(
        [ManaCoin("B", None)] + [ManaCoin("G", None)] * 4
    )

    # ---- Rust: same registration order -- filler in p0 GY (id=0),
    #      Seedship Broodtender in p0 BF (id=1). --------------------------
    rs.register_and_inject_object(
        {
            "name": "SB GY Filler",
            "card_types": ["Creature"],
            "power": 2, "toughness": 2,
        },
        0,   # controller = p0
        ZG,  # ZONE_GRAVEYARD
    )
    rs_id = rs.register_and_inject_object(
        {
            "name": "Seedship Broodtender",
            "card_types": ["Creature"],
            "power": rp, "toughness": rt,
            "activated_abilities": [
                {
                    "cost": {
                        "mana": {"generic": 3, "B": 1, "G": 1},
                        "sacrifice_self": True,
                    },
                    "effect": {
                        "kind": "return_creature_from_your_graveyard_to_battlefield",
                    },
                    "is_mana_ability": False,
                }
            ],
        },
        0,   # controller = p0
        ZB,  # battlefield
    )
    rs.clear_summoning_sick_for_player(0)
    # Fund: {3}{B}{G} = B + 4G (3 generic satisfied by G, plus the G pip).
    rs.add_mana(0, "B", 1)
    rs.add_mana(0, "G", 4)

    # Baseline checks.
    assert len(py.battlefield) == 1, (
        "Battlefield must start with 1 permanent (Seedship Broodtender)"
    )
    assert len(py.players[0].graveyard) == 1, (
        "Graveyard must start with 1 filler card"
    )
    assert rs.battlefield_sizes[0] == 1
    assert rs.graveyard_sizes[0] == 1

    # ---- Python: activate (single GY creature as only reanimate target). --
    _activate_ability(py, 0, py_obj.id, aa_idx)
    assert len(py.stack) == 1, (
        "Seedship Broodtender activation must push one StackItem (non-mana)"
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
        "Seedship Broodtender activation must push one stack item (non-mana)"
    )
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0

    # ---- Verify the card-identity swap on BOTH engines. -----------------
    py_p0_bf = len(py.battlefield)
    py_p0_gy = len(py.players[0].graveyard)
    rs_p0_bf = rs.battlefield_sizes[0]
    rs_p0_gy = rs.graveyard_sizes[0]

    assert py_p0_bf == 1 and rs_p0_bf == 1, (
        f"Exactly 1 permanent must be on p0 battlefield (filler) on BOTH; "
        f"py={py_p0_bf} rs={rs_p0_bf}"
    )
    assert py_p0_gy == 1 and rs_p0_gy == 1, (
        f"Exactly 1 card must be in p0 graveyard (Seedship) on BOTH; "
        f"py={py_p0_gy} rs={rs_p0_gy}"
    )

    # Confirm identity swap: filler is now on BF, Seedship in GY.
    py_bf_names = [o.printing.name for o in py.battlefield]
    py_gy_names = [o.printing.name for o in py.players[0].graveyard]
    assert "SB GY Filler" in py_bf_names, (
        f"Python: filler must be on battlefield after reanimate; "
        f"bf_names={py_bf_names}"
    )
    assert "Seedship Broodtender" in py_gy_names, (
        f"Python: Seedship Broodtender must be in graveyard after sacrifice; "
        f"gy_names={py_gy_names}"
    )

    rs_bf_snap = rs.battlefield_snapshot()
    rs_gy_snap = rs.graveyard_snapshot(0)
    rs_bf_names = [o["printing_name"] for o in rs_bf_snap]
    rs_gy_names = [o["printing_name"] for o in rs_gy_snap]
    assert "SB GY Filler" in rs_bf_names, (
        f"Rust: filler must be on battlefield after reanimate; "
        f"bf_names={rs_bf_names}"
    )
    assert "Seedship Broodtender" in rs_gy_names, (
        f"Rust: Seedship Broodtender must be in graveyard after sacrifice; "
        f"gy_names={rs_gy_names}"
    )

    # ---- Full compare_fields byte-equality. ---------------------------
    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        "Seedship Broodtender {3}{B}{G}, sac self: reanimate creature "
        "must be byte-equal across the WHOLE field view on BOTH engines; "
        f"diffs={diffs}"
    )
