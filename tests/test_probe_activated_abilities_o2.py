"""Genuine real-EoE cross-engine byte-equality probes — activated-ability
PIVOT lane, batch O2.

**Context — PIVOT after DIES lane exhausted.**  Sibling batches G/H/I/J/K/L/N
probed sorcery / ETB / DIES / BECOMES_TAPPED+landfall trigger families.  The
DIES lane exhausted in round 3 (batch O found all remaining candidates blocked
by Rust substrate gaps: ``HasCounter``, ``subject_is_enchantment``,
``HasPowerAtMost``, ``granted_keywords``).  This module opens a **new family:
ACTIVATED ABILITIES** — the first probe batch to exercise the CE20 activated-
ability substrate end-to-end with genuine EoE real-card printings.

**CE20 substrate status (at HEAD):**  The Rust engine's CE20 closure wired
``activated_abilities`` on ``CardPrinting`` with a unified cost-pay + stack-
push dispatch (``state_ops_actions.rs:ActivateAbility``).  The enumerator
(``state_ops_legal.rs``) emits ``ActivateAbility`` for any object carrying a
non-empty ``activated_abilities`` Vec.  The ``parse_activated_ability`` /
``parse_activation_cost`` parsers accept the same dict schema as Python's
``ActivatedAbility`` / ``ActivationCost``.  Prior CE20 probes (in
``tests/test_parity_smoke.py``) exercised the **mana-ability** and **cost-
paying** axes synthetically (Bear Caster shape); this batch drives the ACTUAL
PARSED EoE printings end-to-end for the first time.

**What this module proves:**  Three EoE creature cards — whose primary
mechanic is an activated ability — are driven end-to-end on BOTH engines with
genuine parsed printings on the Python side and bridged synthetic carriers on
the Rust side.  Every probe asserts full ``compare_fields`` byte-equality over
the whole cross-engine field view (the strongest tier the harness supports).

**Card picks:**

  1. Intrepid Tenderfoot  (covered_by_construction, rank ~mid-pool)
     ``{3}: Put a +1/+1 counter on this creature.``
     Cost: generic-mana only (no tap, no sac).  Effect: ``PutPlusOneCounterOnSelf``.
     Counter IS observable in the field-view ``_net_counters`` slot.
     Bridged cost dict: ``{"mana": {"generic": 3}}``.

  2. Malevolent Chandelier  (covered_by_construction)
     ``{2}: Put target card from a graveyard on the bottom of its owner's library.``
     Cost: generic-mana only (no tap).  Effect: ``PutCardFromGraveyardOnBottomOfLibrary``.
     Graveyard → library move IS observable (zone sizes change in the field view).
     Bridged cost dict: ``{"mana": {"generic": 2}}``.

  3. Dual-Sun Adepts  (covered_by_construction)
     ``{5}: Creatures you control get +1/+1 until end of turn.``
     Cost: generic-mana only (no tap).  Effect: ``PumpCreaturesYouControlUntilEOT``.
     Temp power bonus NOT in field-view signature; observed directly via
     ``rs.effective_power`` + Python ``temp_power_bonus`` attribute (same
     targeted-observable idiom the Mechan Navigator / Uthros Scanship probes
     use for gameplay-irrelevant representation artifacts).  Full
     ``compare_fields`` also asserts (field-view is clean despite temp bonus
     not appearing in the sig — both engines agree on the zone layout).

**DROPPED candidates (verify-first exhaustion):**

  * Kavaron Turbodrone: ``{T}: PumpTargetCreatureUntilEOT`` — ``granted_keywords=
    frozenset({'haste'})`` on the Python effect; gap-list blocker.
  * Ripchain Razorkin: ``{2}{R}: DrawCards(1)`` — ``sacrifice_a_land=True`` in
    activation cost (not in Rust's ``ActivationCost`` struct).
  * Sunstar Chaplain: ``{2}: TapTargetArtifactOrCreature`` — ``remove_plus_one_
    counter_from_your_creature=True`` in cost; deferred from CE20 Slice 1.
  * Slagdrill Scrapper: ``{2},{T}: DrawCards(1)`` — ``sacrifice_another_artifact_
    or_land=True`` in cost; not a field on Rust's ``ActivationCost``.
  * Ragost, Deft Gastronaut: ``blocked_subsystem_gated`` tier; out of scope.
  * Starport Security: conditional cost-reduction rider; out of scope for a
    clean mana-only probe.

NEW DEDICATED MODULE (not added to ``tests/test_trajectory_parity.py`` nor
the ``test_audit_safe_trigger_*`` / ``test_probe_covered_unprobed_*`` tests).
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
# Probe #1 — Intrepid Tenderfoot (covered_by_construction → PROBED).
#
# Oracle (verbatim, ``data/edge_of_eternities.json``):
#   "[Creature — Insect Citizen] 2/2
#    {3}: Put a +1/+1 counter on this creature.
#    Activate only as a sorcery."
# Parser → one non-mana ActivatedAbility:
#   cost = ActivationCost(mana=ManaCost(generic=3), tap_self=False)
#   effect = PutPlusOneCounterOnSelf(amount=1)
#   is_mana_ability = False
#
# Rust bridge dict:
#   {"cost": {"mana": {"generic": 3}},
#    "effect": {"kind": "put_plus_one_counter_on_self", "amount": 1},
#    "is_mana_ability": false}
#
# Mana supply: both engines pre-funded with 3 green coins (ManaCoin('G')
# on Python; rs.add_mana(0,'G',3) on Rust). After activation the pool is
# drained on BOTH engines (the mana is consumed), so the field-view
# ``mana_pool_p0`` matches (both empty).
#
# Assertion strength: **full ``compare_fields``** over the whole cross-engine
# field view — the +1/+1 counter is captured in the ``_net_counters`` slot
# of the battlefield signature (Rust: ``counters=1``, Python:
# ``plus_one_counters=1`` → both normalize to net=1). Strongest tier.
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_intrepid_tenderfoot_activated_plus_one_counter_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Intrepid Tenderfoot.
    Batch O2 PIVOT — activated-ability family (first probe of this family).**

    Python: the ACTUAL parsed Intrepid Tenderfoot printing seated on p0's
    battlefield; its non-mana ActivatedAbility
    (``{3}: PutPlusOneCounterOnSelf``) is activated via
    ``_activate_ability``, stack item resolved.  Rust: the bridged synthetic
    carrier with the exact ``{mana: {generic: 3}}`` / ``put_plus_one_counter_
    on_self`` ability dict, activated via ``apply_action(activate_ability)``.

    Assertion strength: **full ``compare_fields``** over the whole
    cross-engine field view (battlefield + both graveyards + lives + hands +
    libraries), no targeted-delta carve-out.  The +1/+1 counter on the
    creature is byte-equal on BOTH engines via the ``_net_counters`` slot.
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
    from mtg_bot.effects.generic.counters import PutPlusOneCounterOnSelf

    real = get_active_source().get_printings().get("Intrepid Tenderfoot")
    if real is None:
        pytest.skip("Intrepid Tenderfoot absent from active CardSource")
    assert "Creature" in real.card_types
    non_mana_aas = [
        (i, aa) for i, aa in enumerate(real.activated_abilities)
        if not aa.is_mana_ability
    ]
    assert non_mana_aas, (
        "Intrepid Tenderfoot must have at least one non-mana ActivatedAbility"
    )
    aa_idx, aa = non_mana_aas[0]
    assert isinstance(aa.effect, PutPlusOneCounterOnSelf), (
        f"genuine Intrepid Tenderfoot non-mana AA must be "
        f"PutPlusOneCounterOnSelf; got {type(aa.effect).__name__}"
    )
    assert aa.effect.amount == 1
    assert aa.cost.mana is not None and aa.cost.mana.generic == 3
    assert not aa.cost.tap_self

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2  # ZONE_BATTLEFIELD

    # ---- Python: seat the GENUINE parsed printing on p0's battlefield. ----
    py_obj = py.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    py_obj.summoning_sick = False
    py_obj.tapped = False
    py_obj.damage = 0
    py_obj.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_obj)
    # Pre-fund the pool with 3 generic mana (G satisfies generic).
    py.players[0].mana_pool.extend(
        [ManaCoin("G", None), ManaCoin("G", None), ManaCoin("G", None)]
    )

    # ---- Rust: bridged synthetic carrier with the exact cost + effect dict. --
    rs_id = rs.register_and_inject_object(
        {
            "name": "Intrepid Tenderfoot",
            "card_types": ["Creature"],
            "power": int(real.power), "toughness": int(real.toughness),
            "activated_abilities": [
                {
                    "cost": {"mana": {"generic": 3}},
                    "effect": {
                        "kind": "put_plus_one_counter_on_self",
                        "amount": 1,
                    },
                    "is_mana_ability": False,
                }
            ],
        },
        0,   # controller = p0
        ZB,  # inject onto battlefield
    )
    rs.clear_summoning_sick_for_player(0)
    # Pre-fund the Rust pool with 3 green coins (pays generic {3}).
    rs.add_mana(0, "G", 3)

    # Baseline: no +1/+1 counter on EITHER engine.
    assert getattr(py_obj, "plus_one_counters", 0) == 0
    rs_snap_pre = rs.battlefield_snapshot()
    assert next(
        e["counters"] for e in rs_snap_pre if e["id"] == rs_id
    ) == 0

    # ---- Python: activate ability. ----
    _activate_ability(py, 0, py_obj.id, aa_idx)
    assert len(py.stack) == 1, (
        "Intrepid Tenderfoot activation must push one StackItem (non-mana)"
    )
    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)
    assert len(py.stack) == 0

    # ---- Rust: activate ability. ----
    rs.apply_action(
        {"kind": "activate_ability", "source_id": rs_id, "ability_index": 0}
    )
    assert rs.stack_size() == 1, (
        "Intrepid Tenderfoot activation must push one stack item (non-mana)"
    )
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0

    # ---- Verify +1/+1 counter on BOTH engines. ----
    py_counters = getattr(py_obj, "plus_one_counters", 0)
    rs_snap_post = rs.battlefield_snapshot()
    rs_counters = next(
        e["counters"] for e in rs_snap_post if e["id"] == rs_id
    )
    assert py_counters == 1, f"Python: +1/+1 counter must be 1; got {py_counters}"
    assert rs_counters == 1, f"Rust: +1/+1 counter must be 1; got {rs_counters}"

    # ---- Full compare_fields byte-equality. ----
    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Intrepid Tenderfoot {'{3}'}: +1/+1-on-self must be byte-equal "
        f"across the WHOLE field view on BOTH engines; diffs={diffs}"
    )


# ---------------------------------------------------------------------
# Probe #2 — Malevolent Chandelier (covered_by_construction → PROBED).
#
# Oracle (verbatim, ``data/edge_of_eternities.json``):
#   "[Artifact Creature — Construct] 4/4
#    {2}: Put target card from a graveyard on the bottom of its owner's
#    library."
# Parser → one non-mana ActivatedAbility:
#   cost = ActivationCost(mana=ManaCost(generic=2), tap_self=False)
#   effect = PutCardFromGraveyardOnBottomOfLibrary()
#   is_mana_ability = False
#
# Rust resolve: takes graveyard[0] of the first non-empty graveyard
# and appends it to the owner's library (bottom).  With exactly ONE
# card seeded in p0's graveyard the choice is forced on BOTH engines:
# Python picks legal_targets()[0] (the only graveyard card) via the
# default-no-agent pick; Rust pops gy[0] from the first non-empty
# graveyard.  The seeded "MC GY Filler" ends up in p0's library on
# BOTH — byte-equal zone-size change observable in the field view.
#
# Assertion strength: **full ``compare_fields``** (strongest tier).
# p0 graveyard_p0 shrinks by 1 (1→0) + library_p0 grows by 1 (0→1)
# on BOTH engines, both captured in the field-view zone-signature slots.
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_malevolent_chandelier_activated_gy_to_library_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Malevolent Chandelier.
    Batch O2 PIVOT — activated-ability family.**

    Python: the ACTUAL parsed Malevolent Chandelier printing seated on p0's
    battlefield; its non-mana ActivatedAbility (``{2}: PutCardFromGraveyard
    OnBottomOfLibrary``) is activated with a single seeded graveyard card as
    the forced target.  Rust: bridged synthetic carrier with the
    ``put_card_from_graveyard_on_bottom_of_library`` effect dict and the
    same seeded graveyard card injected to zone 3 (ZONE_GRAVEYARD).

    Assertion strength: **full ``compare_fields``** over the whole field view
    (the single graveyard card moves to p0's library on BOTH — graveyard size
    0 and library size 1 on BOTH, byte-equal).
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
    from mtg_bot.cards.base import CardPrinting, ManaCost as MC

    real = get_active_source().get_printings().get("Malevolent Chandelier")
    if real is None:
        pytest.skip("Malevolent Chandelier absent from active CardSource")
    assert "Creature" in real.card_types
    non_mana_aas = [
        (i, aa) for i, aa in enumerate(real.activated_abilities)
        if not aa.is_mana_ability
    ]
    assert non_mana_aas, (
        "Malevolent Chandelier must have at least one non-mana ActivatedAbility"
    )
    aa_idx, aa = non_mana_aas[0]
    assert isinstance(aa.effect, PutCardFromGraveyardOnBottomOfLibrary), (
        f"genuine Malevolent Chandelier non-mana AA must be "
        f"PutCardFromGraveyardOnBottomOfLibrary; got {type(aa.effect).__name__}"
    )
    assert aa.cost.mana is not None and aa.cost.mana.generic == 2
    assert not aa.cost.tap_self

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2           # ZONE_BATTLEFIELD
    ZGY = 3          # ZONE_GRAVEYARD (state_ops_zones.rs constant)

    # A simple filler printing for the graveyard target — must share the
    # same name on both engines so the field-view printing-name slot matches.
    filler_printing = CardPrinting(
        name="MC GY Filler", mana_cost_str="", mana_cost=MC(generic=0),
        type_line="Creature", supertypes=(), card_types=("Creature",),
        subtypes=(), power=1, toughness=1, produces=frozenset(),
    )

    # ---- Python: seat Malevolent Chandelier on p0's bf, filler in p0 gy. --
    py_mc = py.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    py_mc.summoning_sick = False
    py_mc.tapped = False
    py_mc.damage = 0
    py_mc.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_mc)

    py_gy_card = py.new_object(filler_printing, owner_id=0, zone=Zone.GRAVEYARD)
    py.players[0].graveyard.append(py_gy_card)

    py.players[0].mana_pool.extend(
        [ManaCoin("G", None), ManaCoin("G", None)]
    )

    # ---- Rust: bridged synthetic carrier on bf, filler in p0 gy. --------
    rs_mc_id = rs.register_and_inject_object(
        {
            "name": "Malevolent Chandelier",
            "card_types": ["Artifact", "Creature"],
            "power": int(real.power), "toughness": int(real.toughness),
            "activated_abilities": [
                {
                    "cost": {"mana": {"generic": 2}},
                    "effect": {
                        "kind": "put_card_from_graveyard_on_bottom_of_library",
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
            "name": "MC GY Filler",
            "card_types": ["Creature"],
            "power": 1, "toughness": 1,
        },
        0,   # owner = p0
        ZGY, # graveyard zone
    )
    rs.add_mana(0, "G", 2)

    # Baseline: exactly one card in p0's graveyard, zero in library.
    assert len(py.players[0].graveyard) == 1
    assert len(py.players[0].library) == 0
    assert rs.graveyard_sizes[0] == 1
    assert rs.library_sizes[0] == 0

    # ---- Python: activate. Default-agent (None) picks the only legal
    # graveyard target (pool[0]). ----
    _activate_ability(py, 0, py_mc.id, aa_idx)
    assert len(py.stack) == 1, (
        "Malevolent Chandelier activation must push one StackItem (non-mana)"
    )
    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)
    assert len(py.stack) == 0

    # ---- Rust: activate. Rust pops gy[0] of the first non-empty gy. ----
    rs.apply_action(
        {"kind": "activate_ability", "source_id": rs_mc_id, "ability_index": 0}
    )
    assert rs.stack_size() == 1, (
        "Malevolent Chandelier activation must push one stack item (non-mana)"
    )
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0

    # ---- Verify zone-move on BOTH engines. ----
    py_gy_after = len(py.players[0].graveyard)
    py_lib_after = len(py.players[0].library)
    rs_gy_after = rs.graveyard_sizes[0]
    rs_lib_after = rs.library_sizes[0]
    assert py_gy_after == 0 and rs_gy_after == 0, (
        f"filler must leave p0 graveyard on BOTH; "
        f"py_gy={py_gy_after} rs_gy={rs_gy_after}"
    )
    assert py_lib_after == 1 and rs_lib_after == 1, (
        f"filler must be in p0 library (bottom) on BOTH; "
        f"py_lib={py_lib_after} rs_lib={rs_lib_after}"
    )

    # ---- Full compare_fields byte-equality. ----
    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Malevolent Chandelier {'{2}'}: gy→library must be byte-equal "
        f"across the WHOLE field view on BOTH engines; diffs={diffs}"
    )


# ---------------------------------------------------------------------
# Probe #3 — Dual-Sun Adepts (covered_by_construction → PROBED).
#
# Oracle (verbatim, ``data/edge_of_eternities.json``):
#   "[Creature — Human Soldier] 2/2
#    Double strike
#    {5}: Creatures you control get +1/+1 until end of turn."
# Parser → one non-mana ActivatedAbility:
#   cost = ActivationCost(mana=ManaCost(generic=5), tap_self=False)
#   effect = PumpCreaturesYouControlUntilEOT(power_bonus=1, toughness_bonus=1)
#   is_mana_ability = False
#
# **Assertion note (targeted-observable idiom):**  The ``temp_power_bonus``
# / ``temp_toughness_bonus`` pump-until-EOT fields are NOT captured in the
# field-view ``_zone_signature`` (they live on the in-memory object but the
# signature only encodes tapped/sick/damage/net_counters/attached_to/
# controller/id).  The raw ``compare_fields == []`` call is still correct
# and the strongest available assertion — both engines agree on the zone
# layout — but the pump's presence is confirmed by a DIRECT observable
# assertion: ``rs.effective_power(rs_id)`` returns base+1 and Python's
# ``obj.temp_power_bonus == 1`` both verify the effect fired.  This is
# the EXACT targeted-observable idiom the Mechan Navigator / Uthros Scanship
# probes use for gameplay-irrelevant representation artifacts — here the
# "irrelevant divergence" is absence of temp_power in the sig, not a
# zone-change artifact; the gameplay-load-bearing pump IS checked directly.
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_dual_sun_adepts_activated_pump_all_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Dual-Sun Adepts.
    Batch O2 PIVOT — activated-ability family.**

    Python: the ACTUAL parsed Dual-Sun Adepts printing seated on p0's
    battlefield; its non-mana ActivatedAbility (``{5}: Creatures you control
    get +1/+1 until end of turn``) is activated via ``_activate_ability``.
    Rust: bridged synthetic carrier with the ``pump_creatures_you_control_
    until_eot`` effect dict.

    Assertion strength: **full ``compare_fields``** over the whole field view
    PLUS a direct observable check (``rs.effective_power`` / Python
    ``temp_power_bonus``) confirming the +1/+1 pump landed on BOTH engines
    before the ``compare_fields`` call (the pump is not in the field-view
    signature but IS verified explicitly — targeted-observable idiom).
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
    from mtg_bot.effects.generic.pump import PumpCreaturesYouControlUntilEOT

    real = get_active_source().get_printings().get("Dual-Sun Adepts")
    if real is None:
        pytest.skip("Dual-Sun Adepts absent from active CardSource")
    assert "Creature" in real.card_types
    non_mana_aas = [
        (i, aa) for i, aa in enumerate(real.activated_abilities)
        if not aa.is_mana_ability
    ]
    assert non_mana_aas, (
        "Dual-Sun Adepts must have at least one non-mana ActivatedAbility"
    )
    aa_idx, aa = non_mana_aas[0]
    assert isinstance(aa.effect, PumpCreaturesYouControlUntilEOT), (
        f"genuine Dual-Sun Adepts non-mana AA must be "
        f"PumpCreaturesYouControlUntilEOT; got {type(aa.effect).__name__}"
    )
    assert aa.effect.power_bonus == 1 and aa.effect.toughness_bonus == 1
    assert aa.cost.mana is not None and aa.cost.mana.generic == 5
    assert not aa.cost.tap_self

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2  # ZONE_BATTLEFIELD

    rp = int(real.power)
    rt = int(real.toughness)

    # ---- Python: seat the GENUINE parsed printing on p0's battlefield. ----
    py_obj = py.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    py_obj.summoning_sick = False
    py_obj.tapped = False
    py_obj.damage = 0
    py_obj.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_obj)
    # Pre-fund the pool with 5 generic mana (G satisfies generic).
    py.players[0].mana_pool.extend([ManaCoin("G", None)] * 5)

    # ---- Rust: bridged synthetic carrier. --------------------------------
    rs_id = rs.register_and_inject_object(
        {
            "name": "Dual-Sun Adepts",
            "card_types": ["Creature"],
            "power": rp, "toughness": rt,
            "activated_abilities": [
                {
                    "cost": {"mana": {"generic": 5}},
                    "effect": {
                        "kind": "pump_creatures_you_control_until_eot",
                        "power_bonus": 1,
                        "toughness_bonus": 1,
                    },
                    "is_mana_ability": False,
                }
            ],
        },
        0,   # controller = p0
        ZB,  # battlefield
    )
    rs.clear_summoning_sick_for_player(0)
    rs.add_mana(0, "G", 5)

    # Baseline: base power before activation.
    assert rs.effective_power(rs_id) == rp
    assert getattr(py_obj, "temp_power_bonus", 0) == 0

    # ---- Python: activate ability. ----
    _activate_ability(py, 0, py_obj.id, aa_idx)
    assert len(py.stack) == 1, (
        "Dual-Sun Adepts activation must push one StackItem (non-mana)"
    )
    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)
    assert len(py.stack) == 0

    # ---- Rust: activate ability. ----
    rs.apply_action(
        {"kind": "activate_ability", "source_id": rs_id, "ability_index": 0}
    )
    assert rs.stack_size() == 1, (
        "Dual-Sun Adepts activation must push one stack item (non-mana)"
    )
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0

    # ---- Direct observable: effective power is base + 1 on BOTH. --------
    py_eff_power = rp + getattr(py_obj, "temp_power_bonus", 0)
    rs_eff_power = rs.effective_power(rs_id)
    assert py_eff_power == rp + 1, (
        f"Python: Dual-Sun Adepts effective power must be {rp+1} after pump; "
        f"got {py_eff_power} (temp_power_bonus={getattr(py_obj,'temp_power_bonus',0)})"
    )
    assert rs_eff_power == rp + 1, (
        f"Rust: Dual-Sun Adepts effective_power must be {rp+1} after pump; "
        f"got {rs_eff_power}"
    )

    # ---- Full compare_fields byte-equality (field view agrees on zones). ---
    # Note: temp_power_bonus is NOT in the battlefield zone signature so
    # the pump doesn't appear in the field view directly — compare_fields
    # asserts both engines agree on the ZONE LAYOUT (same cards, same
    # tapped/sick/counters/ids), which is the cleanest possible assertion
    # for this effect shape.  The pump itself is verified by the direct
    # observable above.
    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Dual-Sun Adepts {'{5}'}: pump-all-until-eot must be byte-equal "
        f"across the WHOLE field view on BOTH engines; diffs={diffs}"
    )
