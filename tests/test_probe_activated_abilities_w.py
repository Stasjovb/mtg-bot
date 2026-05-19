"""Genuine real-EoE cross-engine byte-equality probes — activated-ability
lane, batch W (round 4 of the activated-ability family).

**Context — extending O2 + Q + T.**  Batches O2/Q/T proved seven cost
axes on the CE20 substrate:

  - O2: pure generic mana ({N}) — Intrepid Tenderfoot, Malevolent
    Chandelier, Dual-Sun Adepts.
  - Q: tap-only ({T}), colored mana ({N}{C}), mana+tap ({N},{T}) —
    Xu-Ifit, Zookeeper Mechan, Ragged Playmate.
  - T: mana+sac_self ({N}, sac), colored+sac_self ({N}{C}, sac),
    mana+tap+sac_self ({N},{T}, sac) — Illvoi Galeblade, Valgavoth's
    Faithful, Thaumaton Torpedo.

This module (batch W) extends the same lane with **three new probes**:

  1. Starport Security  (covered_by_construction -> PROBED)
     ``{3}{W}, {T}: Tap another target creature.``
     **NEW cost shape:** tap + colored mana combined ({3}{W},{T}) — the
     first probe in the lane to exercise *both* a tap component and a
     colored mana component simultaneously.

  2. Bear Trap  (covered_by_construction -> PROBED)
     ``{3}, {T}, Sacrifice Bear Trap: Deal 3 damage to target creature.``
     **NEW effect type for the lane:** DealDamageToTargetCreature on a
     mana+tap+sac_self triple-cost activation — the first direct-damage
     effect in the activated-ability probe family.

  3. Strip Mine  (covered_by_construction -> PROBED)
     ``{T}, Sacrifice Strip Mine: Destroy target land.``
     **NEW cost shape:** tap + sacrifice_self with NO mana component
     ({T}, sac_self) — the first probe in the lane with a sacrifice_self
     cost but zero mana.

All three cards are in the ``covered_by_construction`` tier at HEAD
(every Effect class they emit has a live Rust variant + bridge arm, but
no genuine real-EoE probe pins that card).  This module promotes them
to PROBED.

**Cost-shape summary after batches O2 + Q + T + W:**

  Proven axes (single):
    {N}          — O2 (Intrepid Tenderfoot)
    {T}          — Q (Xu-Ifit)
    {N}{C}       — Q (Zookeeper Mechan)

  Proven combinations (2-axis):
    {N},{T}      — Q (Ragged Playmate)
    {N}, sac     — T (Illvoi Galeblade)
    {N}{C}, sac  — T (Valgavoth's Faithful)
    {N}{C},{T}   — W (Starport Security)   ** NEW in this batch
    {T}, sac     — W (Strip Mine)          ** NEW in this batch

  Proven combinations (3-axis):
    {N},{T}, sac — T (Thaumaton Torpedo)
    {N},{T}, sac — W (Bear Trap, different effect)

**DROPPED candidates:**

  * Ripchain Razorkin: ``{2}{R}, Sacrifice a land: Draw a card.`` —
    ``sacrifice_a_land=True`` in cost.  Python's ``_activate_ability``
    guards the sacrifice with ``if options:`` (no-op when there is no
    land on the battlefield), meaning the probe would silently skip the
    land-sacrifice cost and not exercise the full activation; honest
    failure scope is the same blocker as the O2/Q/T drop-lists.

  * High Market: ``{T}, Sacrifice a creature: Gain 1 life.`` — the
    parser encodes ``sacrifice_another_creature_or_artifact=True`` in
    the cost (the oracle text reads "Sacrifice a creature" which the
    parser classifies as the general "sacrifice another C-or-A" cost).
    Python's ``_activate_ability`` crashes at ``options[0]`` when no
    other creature exists on the controller's battlefield; not probeable
    without a second creature as the sacrifice victim, and adding one
    would change the field-view signature and require extra field
    plumbing — not worth the complexity.

  * Bonders' Enclave: ``{3}, {T}: Draw a card. Activate only if you
    control a creature with power 4 or greater.`` — the
    ``requires_own_creature_power_at_least=4`` condition gate is
    silently ignored by Python's ``_activate_ability`` (not in the
    cost-payment path).  A probe that bypasses the condition gate is
    factually inaccurate — the oracle text restricts the activation
    but the probe can't observe that restriction.

  * Deserted Temple: ``{1}, {T}: Untap target land.`` — the
    ``UntapTargetLand`` Python Effect has no corresponding Rust Effect
    variant; the card is in the BLOCKED (subsystem-gated) tier.

  * Swarmyard: ``{T}: Regenerate target creature.`` — the
    ``RegenerateTargetCreature`` Rust effect kind does not exist in the
    current bridge vocab; blocked.

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
    cross-engine byte-equality compare — same fixture shape as
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
# Probe #1 — Starport Security (covered_by_construction -> PROBED).
#
# Oracle (verbatim, ``data/edge_of_eternities.json``):
#   "[Artifact Creature — Robot Soldier] 1/1
#    {3}{W}, {T}: Tap another target creature. This ability costs {2}
#    less to activate if you control a creature with a +1/+1 counter
#    on it."
# Parser -> one non-mana ActivatedAbility:
#   cost = ActivationCost(mana=ManaCost(generic=3, colored=(('W',1),)),
#                         tap_self=True, sacrifice_self=False)
#   effect = TapAnotherTargetCreature()
#   is_mana_ability = False
#
# Note: the conditional cost-reduction rider ("{2} less if you control
# a creature with a +1/+1 counter") is NOT modelled by the parser; the
# parser stores only the base cost {3}{W},{T}.  Both engines therefore
# use the full {3}{W},{T} cost in this probe — the probe is honest
# about the base cost shape even though the rider is dropped.
#
# Rust bridge dict:
#   {"cost": {"mana": {"generic": 3, "W": 1}, "tap_self": true},
#    "effect": {"kind": "tap_another_target_creature"},
#    "is_mana_ability": false}
#
# Setup: Starport Security on p0's battlefield (id=0); a victim
# creature on p1's battlefield (id=1) as the forced tap target.
# Mana supply: 1 white + 3 green coins (green satisfies {3}).
#
# After activation on BOTH engines:
#   - Starport Security taps itself (tap_self cost)
#   - TapAnotherTargetCreature resolves -> victim is tapped
#   - Zone net: bf sizes unchanged; Starport and victim now tapped.
#
# **NEW cost shape (tap + colored mana combined):** {3}{W},{T} is the
# first probe in the activated-ability family to exercise a tap_self
# component AND a colored mana component simultaneously.  Prior batches
# proved tap-only (Q), colored mana without tap (Q), and mana+tap with
# no color (Q).  This probe closes the "tap + colored" combination.
#
# Assertion strength: **full ``compare_fields``** (strongest tier).
# Both engines show Starport tapped, victim tapped, zero zone-move —
# byte-equal across the whole field view.
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_starport_security_activated_tap_colored_mana_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Starport Security.
    Batch W (round 4 activated-ability lane) — tap + colored mana cost
    ({3}{W},{T}), TapAnotherTargetCreature.**

    Python: the ACTUAL parsed Starport Security printing (Artifact
    Creature) seated on p0's battlefield; its non-mana ActivatedAbility
    (``{3}{W}, {T}: Tap another target creature``) is activated via
    ``_activate_ability`` targeting the only victim creature on p1's
    battlefield.  Rust: bridged synthetic carrier with the
    ``{"mana": {"generic": 3, "W": 1}, "tap_self": true}`` cost dict
    and the ``tap_another_target_creature`` effect.

    **NEW cost shape (tap + colored mana):** First probe in the
    activated-ability family to exercise both ``tap_self`` and a
    colored mana component simultaneously on the CE20 substrate
    end-to-end.

    Assertion strength: **full ``compare_fields``** over the whole
    cross-engine field view — Starport Security and the victim are both
    tapped; no zone-move — byte-equal on BOTH engines.
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
    from mtg_bot.effects.generic.tap import TapAnotherTargetCreature
    from mtg_bot.cards.base import CardPrinting, ManaCost as MC

    real = get_active_source().get_printings().get("Starport Security")
    if real is None:
        pytest.skip("Starport Security absent from active CardSource")
    assert "Artifact" in real.card_types
    assert "Creature" in real.card_types
    non_mana_aas = [
        (i, aa) for i, aa in enumerate(real.activated_abilities)
        if not aa.is_mana_ability
    ]
    assert non_mana_aas, (
        "Starport Security must have at least one non-mana ActivatedAbility"
    )
    aa_idx, aa = non_mana_aas[0]
    assert isinstance(aa.effect, TapAnotherTargetCreature), (
        f"genuine Starport Security non-mana AA must be TapAnotherTargetCreature; "
        f"got {type(aa.effect).__name__}"
    )
    assert aa.cost.tap_self, (
        "Starport Security AA cost must require tapping itself"
    )
    assert not aa.cost.sacrifice_self, (
        "Starport Security AA cost must NOT require sacrificing itself"
    )
    assert aa.cost.mana is not None and aa.cost.mana.generic == 3, (
        "Starport Security AA cost must require {3} generic mana"
    )
    colored_dict = dict(aa.cost.mana.colored)
    assert colored_dict.get("W", 0) == 1, (
        f"Starport Security AA cost must require 1 white mana; "
        f"got colored={aa.cost.mana.colored}"
    )
    assert not real.triggered_abilities, (
        "Starport Security must have no triggered abilities (clean probe)"
    )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2    # ZONE_BATTLEFIELD

    rp = int(real.power)
    rt = int(real.toughness)

    # A victim creature on p1's battlefield as the forced tap target.
    victim_printing = CardPrinting(
        name="Starport Victim", mana_cost_str="", mana_cost=MC(generic=0),
        type_line="Creature", supertypes=(), card_types=("Creature",),
        subtypes=(), power=2, toughness=2, produces=frozenset(),
    )

    # ---- Python: Starport Security on p0 bf (id=0), victim on p1 bf (id=1). ----
    py_obj = py.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    py_obj.summoning_sick = False
    py_obj.tapped = False
    py_obj.damage = 0
    py_obj.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_obj)
    # Pre-fund: {3}{W} = 3 generic (green) + 1 white.
    py.players[0].mana_pool.extend(
        [ManaCoin("W", None)] + [ManaCoin("G", None)] * 3
    )

    py_victim = py.new_object(victim_printing, owner_id=1, zone=Zone.BATTLEFIELD)
    py_victim.summoning_sick = False
    py_victim.tapped = False
    py_victim.damage = 0
    py_victim.controller_id = 1
    py_victim.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_victim)

    # ---- Rust: same registration order — Starport in p0 bf (id=0),
    #      victim in p1 bf (id=1). ------------------------------------------
    rs_id = rs.register_and_inject_object(
        {
            "name": "Starport Security",
            "card_types": ["Artifact", "Creature"],
            "power": rp, "toughness": rt,
            "activated_abilities": [
                {
                    "cost": {"mana": {"generic": 3, "W": 1}, "tap_self": True},
                    "effect": {"kind": "tap_another_target_creature"},
                    "is_mana_ability": False,
                }
            ],
        },
        0,   # controller = p0
        ZB,  # battlefield
    )
    rs.clear_summoning_sick_for_player(0)
    rs.add_mana(0, "W", 1)
    rs.add_mana(0, "G", 3)

    rs.register_and_inject_object(
        {
            "name": "Starport Victim",
            "card_types": ["Creature"],
            "power": 2, "toughness": 2,
        },
        1,   # controller = p1
        ZB,
    )
    rs.clear_summoning_sick_for_player(1)

    # Baseline checks.
    assert len(py.battlefield) == 2, (
        "Battlefield must start with 2 permanents (Starport + Victim)"
    )
    assert rs.battlefield_sizes[0] == 1
    assert rs.battlefield_sizes[1] == 1
    assert not py_obj.tapped, "Starport must be untapped initially"
    assert not py_victim.tapped, "Victim must be untapped initially"

    # ---- Python: activate (single victim as only legal tap target). ------
    _activate_ability(py, 0, py_obj.id, aa_idx)
    assert len(py.stack) == 1, (
        "Starport Security activation must push one StackItem (non-mana)"
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
        "Starport Security activation must push one stack item (non-mana)"
    )
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0

    # ---- Verify tap states on BOTH engines. ------------------------------
    assert py_obj.tapped, (
        "Starport Security must be tapped (tap_self cost) on Python engine"
    )
    assert py_victim.tapped, (
        "Victim must be tapped (TapAnotherTargetCreature effect) on Python engine"
    )
    rs_bf = rs.battlefield_snapshot()
    starport_snap = next(
        (o for o in rs_bf if o["printing_name"] == "Starport Security"), None
    )
    victim_snap = next(
        (o for o in rs_bf if o["printing_name"] == "Starport Victim"), None
    )
    assert starport_snap is not None and starport_snap["tapped"], (
        "Rust: Starport Security must be tapped after activation"
    )
    assert victim_snap is not None and victim_snap["tapped"], (
        "Rust: Starport Victim must be tapped (TapAnotherTargetCreature) after activation"
    )

    # ---- Full compare_fields byte-equality. ---------------------------
    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        "Starport Security {3}{W},{T}: tap another creature must be "
        "byte-equal across the WHOLE field view on BOTH engines; "
        f"diffs={diffs}"
    )


# ---------------------------------------------------------------------
# Probe #2 — Bear Trap (covered_by_construction -> PROBED).
#
# Oracle (verbatim, ``data/edge_of_eternities.json``):
#   "[Artifact]
#    {3}, {T}, Sacrifice Bear Trap: Deal 3 damage to target creature."
# Parser -> one non-mana ActivatedAbility:
#   cost = ActivationCost(mana=ManaCost(generic=3), tap_self=True,
#                         sacrifice_self=True)
#   effect = DealDamageToTargetCreature(amount=3)
#   is_mana_ability = False
#
# Rust bridge dict:
#   {"cost": {"mana": {"generic": 3}, "tap_self": true,
#             "sacrifice_self": true},
#    "effect": {"kind": "deal_damage", "amount": 3,
#               "target": {"kind": "any_creature"}},
#    "is_mana_ability": false}
#
# Mana supply: 3 green coins (green satisfies {3}).
#
# Setup: Bear Trap on p0's battlefield (id=0); a victim creature on
# p1's battlefield (id=1) as the forced damage target.  Bear Trap is
# an Artifact (non-creature), so it has no power/toughness.  Victim
# has toughness=2 so it dies to 3 damage via SBA.
#
# After activation on BOTH engines:
#   - Bear Trap taps (tap_self cost) and sacrifices (sacrifice_self
#     cost) -> moves from p0 BF to p0 GY during cost payment
#   - DealDamageToTargetCreature(3) resolves -> victim takes 3 damage;
#     SBA detects lethal damage, victim moves to p1 GY
#   - Zone net: p0 bf 1->0 (Bear Trap sacrificed), p0 gy 0->1,
#     p1 bf 1->0 (victim dies), p1 gy 0->1
#
# ID ordering: Bear Trap first (id=0), victim second (id=1) on BOTH.
#
# **NEW effect type for the lane:** DealDamageToTargetCreature is the
# first direct-damage effect in the activated-ability probe family.
# Prior damage effects were all sorceries/instants (Bombard, Focus
# Fire, Plasma Bolt, etc.).  This probe validates the
# ``deal_damage + target: any_creature`` bridge arm at resolution via
# an activated-ability source.  The cost shape (mana+tap+sac_self) was
# first proven by Thaumaton Torpedo in batch T.
#
# Assertion strength: **full ``compare_fields``** (strongest tier).
# Both Bear Trap's sacrifice (p0 bf->gy) and the victim's death
# (p1 bf->gy) are captured in the field view and match byte-equal.
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_bear_trap_activated_triple_cost_damage_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Bear Trap.
    Batch W (round 4 activated-ability lane) — mana + tap + sacrifice_self
    cost ({3},{T}, sac self), DealDamageToTargetCreature(3).**

    Python: the ACTUAL parsed Bear Trap printing (Artifact) seated on p0's
    battlefield; its non-mana ActivatedAbility (``{3}, {T}, Sacrifice Bear
    Trap: Deal 3 damage to target creature``) is activated via
    ``_activate_ability`` targeting the victim creature on p1's battlefield.
    Rust: bridged synthetic carrier with the ``{"mana": {"generic": 3},
    "tap_self": true, "sacrifice_self": true}`` cost dict and the
    ``deal_damage`` effect with ``target: {kind: any_creature}``.

    **NEW effect type for the activated-ability lane:** First probe in
    the family to exercise ``DealDamageToTargetCreature`` as the
    resolved effect of an activated ability.  Validates the Rust
    ``deal_damage`` bridge arm at activation-resolution time
    end-to-end.

    Assertion strength: **full ``compare_fields``** over the whole field
    view — Bear Trap leaves p0 bf (sacrifice cost), victim dies after
    taking 3 damage (p1 bf->gy via SBA lethal damage) — byte-equal on
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
    from mtg_bot.effects.generic.damage import DealDamageToTargetCreature
    from mtg_bot.cards.base import CardPrinting, ManaCost as MC

    real = get_active_source().get_printings().get("Bear Trap")
    if real is None:
        pytest.skip("Bear Trap absent from active CardSource")
    assert "Artifact" in real.card_types
    non_mana_aas = [
        (i, aa) for i, aa in enumerate(real.activated_abilities)
        if not aa.is_mana_ability
    ]
    assert non_mana_aas, (
        "Bear Trap must have at least one non-mana ActivatedAbility"
    )
    aa_idx, aa = non_mana_aas[0]
    assert isinstance(aa.effect, DealDamageToTargetCreature), (
        f"genuine Bear Trap non-mana AA must be DealDamageToTargetCreature; "
        f"got {type(aa.effect).__name__}"
    )
    assert aa.effect.amount == 3, (
        "Bear Trap DealDamageToTargetCreature must deal exactly 3 damage"
    )
    # Verify triple cost.
    assert aa.cost.tap_self, (
        "Bear Trap AA cost must require tapping itself"
    )
    assert aa.cost.sacrifice_self, (
        "Bear Trap AA cost must require sacrificing itself"
    )
    assert aa.cost.mana is not None and aa.cost.mana.generic == 3, (
        "Bear Trap AA cost must require {3} generic mana"
    )
    colored_dict = dict(aa.cost.mana.colored)
    assert not colored_dict, (
        f"Bear Trap AA cost must have no colored mana; got {colored_dict}"
    )
    assert not real.triggered_abilities, (
        "Bear Trap must have no triggered abilities (clean probe)"
    )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2    # ZONE_BATTLEFIELD

    # A victim creature on p1's battlefield with toughness=2 so 3 damage kills it.
    victim_printing = CardPrinting(
        name="Bear Trap Victim", mana_cost_str="", mana_cost=MC(generic=0),
        type_line="Creature", supertypes=(), card_types=("Creature",),
        subtypes=(), power=2, toughness=2, produces=frozenset(),
    )

    # ---- Python: Bear Trap on p0 bf (id=0), victim on p1 bf (id=1). ----
    py_obj = py.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    py_obj.summoning_sick = False
    py_obj.tapped = False
    py_obj.damage = 0
    py_obj.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_obj)
    # Pre-fund: {3} generic (3 green coins).
    py.players[0].mana_pool.extend([ManaCoin("G", None)] * 3)

    py_victim = py.new_object(victim_printing, owner_id=1, zone=Zone.BATTLEFIELD)
    py_victim.summoning_sick = False
    py_victim.tapped = False
    py_victim.damage = 0
    py_victim.controller_id = 1
    py_victim.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_victim)

    # ---- Rust: same registration order — Bear Trap in p0 bf (id=0),
    #      victim in p1 bf (id=1). -----------------------------------------
    rs_id = rs.register_and_inject_object(
        {
            "name": "Bear Trap",
            "card_types": ["Artifact"],
            "activated_abilities": [
                {
                    "cost": {
                        "mana": {"generic": 3},
                        "tap_self": True,
                        "sacrifice_self": True,
                    },
                    "effect": {
                        "kind": "deal_damage",
                        "amount": 3,
                        "target": {"kind": "any_creature"},
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

    rs.register_and_inject_object(
        {
            "name": "Bear Trap Victim",
            "card_types": ["Creature"],
            "power": 2, "toughness": 2,
        },
        1,   # controller = p1
        ZB,  # battlefield
    )
    rs.clear_summoning_sick_for_player(1)

    # Baseline checks.
    assert len(py.battlefield) == 2, (
        "Battlefield must start with 2 permanents (Bear Trap + Victim)"
    )
    assert rs.battlefield_sizes[0] == 1
    assert rs.battlefield_sizes[1] == 1
    assert rs.graveyard_sizes[0] == 0
    assert rs.graveyard_sizes[1] == 0

    # ---- Python: activate (single victim as only legal damage target). ---
    _activate_ability(py, 0, py_obj.id, aa_idx)
    assert len(py.stack) == 1, (
        "Bear Trap activation must push one StackItem (non-mana)"
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
        "Bear Trap activation must push one stack item (non-mana)"
    )
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0

    # ---- Verify zone moves on BOTH engines. ------------------------------
    py_p0_bf = sum(1 for o in py.battlefield if o.controller_id == 0)
    py_p1_bf = sum(1 for o in py.battlefield if o.controller_id == 1)
    py_p0_gy = len(py.players[0].graveyard)
    py_p1_gy = len(py.players[1].graveyard)
    rs_p0_bf = rs.battlefield_sizes[0]
    rs_p1_bf = rs.battlefield_sizes[1]
    rs_p0_gy = rs.graveyard_sizes[0]
    rs_p1_gy = rs.graveyard_sizes[1]

    assert py_p0_bf == 0 and rs_p0_bf == 0, (
        f"Bear Trap must have left p0 battlefield (sacrificed) on BOTH; "
        f"py={py_p0_bf} rs={rs_p0_bf}"
    )
    assert py_p1_bf == 0 and rs_p1_bf == 0, (
        f"Victim must have left p1 battlefield (killed by damage) on BOTH; "
        f"py={py_p1_bf} rs={rs_p1_bf}"
    )
    assert py_p0_gy == 1 and rs_p0_gy == 1, (
        f"Bear Trap must be in p0 graveyard on BOTH; "
        f"py={py_p0_gy} rs={rs_p0_gy}"
    )
    assert py_p1_gy == 1 and rs_p1_gy == 1, (
        f"Victim must be in p1 graveyard on BOTH; "
        f"py={py_p1_gy} rs={rs_p1_gy}"
    )

    # ---- Full compare_fields byte-equality. ---------------------------
    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        "Bear Trap {3},{T}, sac self: deal 3 damage to target creature "
        "must be byte-equal across the WHOLE field view on BOTH engines; "
        f"diffs={diffs}"
    )


# ---------------------------------------------------------------------
# Probe #3 — Strip Mine (covered_by_construction -> PROBED).
#
# Oracle (verbatim, ``data/edge_of_eternities.json``):
#   "[Land]
#    {T}, Sacrifice Strip Mine: Destroy target land."
# Parser -> one non-mana ActivatedAbility:
#   cost = ActivationCost(mana=None, tap_self=True, sacrifice_self=True)
#   effect = DestroyTargetLand()
#   is_mana_ability = False
#
# Rust bridge dict:
#   {"cost": {"tap_self": true, "sacrifice_self": true},
#    "effect": {"kind": "destroy_target_land"},
#    "is_mana_ability": false}
#
# No mana supply needed (the cost has no mana component).
#
# Setup: Strip Mine on p0's battlefield (id=0); a target land on p1's
# battlefield (id=1) as the forced destruction target.
#
# After activation on BOTH engines:
#   - Strip Mine taps (tap_self cost) and sacrifices (sacrifice_self
#     cost) -> moves from p0 BF to p0 GY during cost payment
#   - DestroyTargetLand resolves -> target land moves to p1 GY
#   - Zone net: p0 bf 1->0 (Strip Mine sacrificed), p0 gy 0->1,
#     p1 bf 1->0 (target land destroyed), p1 gy 0->1
#
# ID ordering: Strip Mine first (id=0), target land second (id=1) on
# BOTH engines.
#
# **NEW cost shape (tap + sac_self, no mana):** {T}, sac_self is the
# first probe in the activated-ability family to exercise a sacrifice
# component WITHOUT any mana component.  Prior sacrifice probes all
# required at least generic mana (batch T: Illvoi Galeblade {2}+sac,
# Valgavoth's Faithful {3}{B}+sac, Thaumaton Torpedo {6}+{T}+sac).
# Strip Mine proves that the ``sacrifice_self`` cost field works when
# the mana cost field is absent (None / missing dict key) rather than
# zero-generic.
#
# Assertion strength: **full ``compare_fields``** (strongest tier).
# Both Strip Mine's sacrifice (p0 bf->gy) and the target land's
# destruction (p1 bf->gy) are captured in the field view and match
# byte-equal on BOTH engines.
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_strip_mine_activated_tap_sac_no_mana_destroy_land_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Strip Mine.
    Batch W (round 4 activated-ability lane) — tap + sacrifice_self with
    NO mana cost ({T}, sac self), DestroyTargetLand.**

    Python: the ACTUAL parsed Strip Mine printing (Land) seated on p0's
    battlefield; its non-mana ActivatedAbility (``{T}, Sacrifice Strip
    Mine: Destroy target land``) is activated via ``_activate_ability``
    targeting the only land on p1's battlefield.  Rust: bridged synthetic
    carrier with the ``{"tap_self": true, "sacrifice_self": true}`` cost
    dict (no mana key) and the ``destroy_target_land`` effect.

    **NEW cost shape (tap + sac_self, no mana):** First probe in the
    activated-ability family to exercise ``sacrifice_self`` as a cost
    component WITHOUT any mana requirement.  Validates that the Rust
    engine's ``ActivationCost`` accepts a missing ``mana`` key and
    correctly pays the tap+sacrifice cost without attempting to spend
    any mana.

    Assertion strength: **full ``compare_fields``** over the whole field
    view — Strip Mine leaves p0 bf (sacrifice cost), target land leaves
    p1 bf (destroy effect) — both move to their respective graveyards —
    byte-equal on BOTH engines.
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
    from mtg_bot.effects.generic.destroy import DestroyTargetLand
    from mtg_bot.cards.base import CardPrinting, ManaCost as MC

    real = get_active_source().get_printings().get("Strip Mine")
    if real is None:
        pytest.skip("Strip Mine absent from active CardSource")
    assert "Land" in real.card_types
    non_mana_aas = [
        (i, aa) for i, aa in enumerate(real.activated_abilities)
        if not aa.is_mana_ability
    ]
    assert non_mana_aas, (
        "Strip Mine must have at least one non-mana ActivatedAbility"
    )
    aa_idx, aa = non_mana_aas[0]
    assert isinstance(aa.effect, DestroyTargetLand), (
        f"genuine Strip Mine non-mana AA must be DestroyTargetLand; "
        f"got {type(aa.effect).__name__}"
    )
    # Verify tap + sac_self, no mana.
    assert aa.cost.tap_self, (
        "Strip Mine AA cost must require tapping itself"
    )
    assert aa.cost.sacrifice_self, (
        "Strip Mine AA cost must require sacrificing itself"
    )
    assert aa.cost.mana is None, (
        f"Strip Mine AA cost must have NO mana component; "
        f"got mana={aa.cost.mana}"
    )
    assert not real.triggered_abilities, (
        "Strip Mine must have no triggered abilities (clean probe)"
    )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2    # ZONE_BATTLEFIELD

    # A target land on p1's battlefield.
    target_land_printing = CardPrinting(
        name="Strip Mine Target Land", mana_cost_str="", mana_cost=MC(generic=0),
        type_line="Land", supertypes=("Basic",), card_types=("Land",),
        subtypes=("Forest",), power=None, toughness=None, produces=frozenset({"G"}),
    )

    # ---- Python: Strip Mine on p0 bf (id=0), target land on p1 bf (id=1). ----
    py_obj = py.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    py_obj.summoning_sick = False
    py_obj.tapped = False
    py_obj.damage = 0
    py_obj.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_obj)
    # No mana needed — cost is {T} + sac_self only.

    py_target = py.new_object(target_land_printing, owner_id=1, zone=Zone.BATTLEFIELD)
    py_target.summoning_sick = False
    py_target.tapped = False
    py_target.damage = 0
    py_target.controller_id = 1
    py_target.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_target)

    # ---- Rust: same registration order — Strip Mine in p0 bf (id=0),
    #      target land in p1 bf (id=1). -------------------------------------
    rs_id = rs.register_and_inject_object(
        {
            "name": "Strip Mine",
            "card_types": ["Land"],
            "activated_abilities": [
                {
                    "cost": {
                        "tap_self": True,
                        "sacrifice_self": True,
                    },
                    "effect": {
                        "kind": "destroy_target_land",
                    },
                    "is_mana_ability": False,
                }
            ],
        },
        0,   # controller = p0
        ZB,  # battlefield
    )
    rs.clear_summoning_sick_for_player(0)

    rs.register_and_inject_object(
        {
            "name": "Strip Mine Target Land",
            "card_types": ["Land"],
        },
        1,   # controller = p1
        ZB,  # battlefield
    )
    rs.clear_summoning_sick_for_player(1)

    # Baseline checks.
    assert len(py.battlefield) == 2, (
        "Battlefield must start with 2 permanents (Strip Mine + Target Land)"
    )
    assert rs.battlefield_sizes[0] == 1
    assert rs.battlefield_sizes[1] == 1
    assert rs.graveyard_sizes[0] == 0
    assert rs.graveyard_sizes[1] == 0

    # ---- Python: activate (single target land as only legal target). -----
    _activate_ability(py, 0, py_obj.id, aa_idx)
    assert len(py.stack) == 1, (
        "Strip Mine activation must push one StackItem (non-mana)"
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
        "Strip Mine activation must push one stack item (non-mana)"
    )
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0

    # ---- Verify zone moves on BOTH engines. ------------------------------
    py_p0_bf = sum(1 for o in py.battlefield if o.controller_id == 0)
    py_p1_bf = sum(1 for o in py.battlefield if o.controller_id == 1)
    py_p0_gy = len(py.players[0].graveyard)
    py_p1_gy = len(py.players[1].graveyard)
    rs_p0_bf = rs.battlefield_sizes[0]
    rs_p1_bf = rs.battlefield_sizes[1]
    rs_p0_gy = rs.graveyard_sizes[0]
    rs_p1_gy = rs.graveyard_sizes[1]

    assert py_p0_bf == 0 and rs_p0_bf == 0, (
        f"Strip Mine must have left p0 battlefield (sacrificed) on BOTH; "
        f"py={py_p0_bf} rs={rs_p0_bf}"
    )
    assert py_p1_bf == 0 and rs_p1_bf == 0, (
        f"Target land must have left p1 battlefield (destroyed) on BOTH; "
        f"py={py_p1_bf} rs={rs_p1_bf}"
    )
    assert py_p0_gy == 1 and rs_p0_gy == 1, (
        f"Strip Mine must be in p0 graveyard on BOTH; "
        f"py={py_p0_gy} rs={rs_p0_gy}"
    )
    assert py_p1_gy == 1 and rs_p1_gy == 1, (
        f"Target land must be in p1 graveyard on BOTH; "
        f"py={py_p1_gy} rs={rs_p1_gy}"
    )

    # ---- Full compare_fields byte-equality. ---------------------------
    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        "Strip Mine {T}, sac self: destroy target land must be byte-equal "
        "across the WHOLE field view on BOTH engines; "
        f"diffs={diffs}"
    )
