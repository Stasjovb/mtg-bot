"""Genuine real-EoE cross-engine byte-equality probes — activated-ability
lane, batch Q (round 4 of the activated-ability family).

**Context — extending batch O2.**  Batch O2 opened the activated-ability probe
family with three EoE cards whose abilities use *pure generic mana* costs
(``{3}``, ``{2}``, ``{5}``).  This module (batch Q) extends the same lane with
**three different cost shapes** that O2 did not exercise:

  - Tap-only cost (no mana): ``{T}`` (Xu-Ifit, Osteoharmonist)
  - Generic + colored mana cost: ``{6}{R}`` (Zookeeper Mechan)
  - Generic mana + tap cost: ``{1}{T}`` (Ragged Playmate)

All three cards are in the ``covered_by_construction`` tier at HEAD (every
Effect class they emit has a live Rust variant + bridge arm, but no genuine
real-EoE probe pins that card).  This module promotes them to PROBED.

**CE20 substrate note (inherited from O2):**  The Rust engine's CE20 closure
wires ``activated_abilities`` on ``CardPrinting`` with a unified cost-pay +
stack-push dispatch (``state_ops_actions.rs:ActivateAbility``).  The
``parse_activation_cost`` parser accepts ``tap_self`` (bool) and ``mana``
(optional ManaCost dict with ``generic``, ``W``, ``U``, ``B``, ``R``, ``G``
keys).  **This batch confirms that tap_self works end-to-end for non-mana
activated abilities** (the O2 module only exercised generic-mana-only costs;
no prior batch drove a tap-cost non-mana AA through the CE20 substrate).

**What this module proves:**  Three EoE cards — whose primary mechanic is a
non-mana activated ability — are driven end-to-end on BOTH engines.  Each
probe asserts full ``compare_fields`` byte-equality over the whole cross-engine
field view (the strongest tier the harness supports).

**Card picks:**

  1. Xu-Ifit, Osteoharmonist  (covered_by_construction → PROBED)
     ``{T}: Return target creature card from your graveyard to
     the battlefield.``
     Cost: tap_self=True, mana=None (tap-only, no mana).
     Effect: ``ReturnCreatureFromYourGraveyardToBattlefield``.
     Graveyard → battlefield move IS observable (zone sizes change
     in the field view).  Bridged cost dict: ``{"tap_self": True}``.
     **NEW cost shape: tap-only (no mana at all).**

  2. Zookeeper Mechan  (covered_by_construction → PROBED)
     ``{6}{R}: Target creature you control gets +4/+0 until end of turn.``
     Cost: generic=6 + R=1 (colored mana component). tap_self=False.
     Effect: ``PumpTargetCreatureUntilEOT(power_bonus=4, toughness_bonus=0)``.
     No ``granted_keywords`` rider (clean).  Bridged cost dict:
     ``{"mana": {"generic": 6, "R": 1}}``.
     **NEW cost shape: colored mana (generic + R).**
     The ability targets the first creature p0 controls; in a single-
     creature state that is the Zookeeper itself — BOTH engines agree.

  3. Ragged Playmate  (covered_by_construction → PROBED)
     ``{1}, {T}: Target creature with power 2 or less can't be blocked
     this turn.``
     Cost: generic=1 + tap_self=True.  Effect: ``GrantUnblockableUEOT``
     (Python) → ``grant_keyword_to_target_creature_until_eot{keyword=
     "unblockable"}`` (Rust).  The "can't be blocked" effect IS observable
     via ``is_cant_be_blocked(state, obj)`` (Python) and
     ``rs.has_keyword(id, "unblockable")`` (Rust).  Field-view is clean
     (unblockable status is a layer-6 registry entry, not captured in the
     zone signature — same targeted-observable idiom as the pump probes).
     Bridged cost dict: ``{"mana": {"generic": 1}, "tap_self": True}``.
     **NEW cost shape: generic mana + tap combined.**

**DROPPED candidates:**

  * Kavaron Turbodrone: ``{T}: PumpTargetCreatureUntilEOT`` —
    ``granted_keywords=frozenset({'haste'})`` rider on the Python effect;
    inherited gap-list blocker from O2. tap-only cost shape IS accessible
    (proven by Xu-Ifit above), but this card's effect shape is blocked.
  * Blinkmoth Nexus: ``{1}: BecomeLandCreatureUEOT`` — ``BecomeLandCreature``
    effect has no Rust bridge arm (manland animation subsystem not in CE20).
    Also a Land card, not a Creature.
  * Bonders' Enclave: ``{3},{T}: DrawCards`` — ``requires_own_creature_power_at_least=4``
    precondition check; legal activation requires controlling a 4+ power
    creature which complicates the single-card probe setup.
  * Starport Security: already PROBED at HEAD (not in covered_by_construction
    tier).
  * Rust Harvester: ``{2},{T},exile artifact from GY: Sequence(+1/+1+Damage)``
    — ``exile_artifact_from_graveyard=True`` is not in Rust's ``ActivationCost``
    struct (not bridged); complex Sequence effect with targeted damage also out
    of scope for a clean single-card probe.

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
# Probe #1 — Xu-Ifit, Osteoharmonist (covered_by_construction → PROBED).
#
# Oracle (verbatim, ``data/edge_of_eternities.json``):
#   "[Creature — Human Cleric] 2/3
#    {T}: Return target creature card from your graveyard to the
#    battlefield."
# Parser → one non-mana ActivatedAbility:
#   cost = ActivationCost(mana=None, tap_self=True)
#   effect = ReturnCreatureFromYourGraveyardToBattlefield()
#   is_mana_ability = False
#
# Rust bridge dict:
#   {"cost": {"tap_self": true},
#    "effect": {"kind": "return_creature_from_your_graveyard_to_battlefield"},
#    "is_mana_ability": false}
#
# Mana supply: none needed (tap-only cost). A single creature filler
# "Xu GY Filler" is seeded in p0's graveyard as the forced target on
# BOTH engines (only valid choice). After resolution the filler moves
# to p0's battlefield on BOTH engines — graveyard size 0, battlefield
# size 2 (Xu-Ifit + filler) — observable in the field-view zone-size
# slots.  Xu-Ifit itself becomes tapped (cost paid) on BOTH engines.
#
# **NEW cost shape:** tap-only (no mana component at all). O2 only
# exercised pure generic-mana costs. This probe is the first in the
# activated-ability family to drive a tap-only non-mana AA.
#
# Assertion strength: **full ``compare_fields``** (strongest tier).
# Both graveyard→battlefield zone moves and the tapped flag on Xu-Ifit
# are captured in the field view and match byte-equal.
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_xu_ifit_osteoharmonist_activated_tap_reanimate_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Xu-Ifit, Osteoharmonist.
    Batch Q (round 4 activated-ability lane) — tap-only cost, reanimate.**

    Python: the ACTUAL parsed Xu-Ifit, Osteoharmonist printing seated on
    p0's battlefield; its non-mana ActivatedAbility (``{T}: Return target
    creature card from your graveyard to the battlefield``) is activated
    via ``_activate_ability`` with a forced single graveyard target.
    Rust: bridged synthetic carrier with the exact ``{"tap_self": true}``
    cost and ``return_creature_from_your_graveyard_to_battlefield`` effect.

    **NEW cost shape (tap-only):** First probe in the activated-ability
    family to drive a zero-mana tap-only non-mana AA through the CE20
    substrate end-to-end.

    Assertion strength: **full ``compare_fields``** over the whole
    cross-engine field view — p0 graveyard shrinks 1→0, p0 battlefield
    grows 1→2 (Xu-Ifit + filler), Xu-Ifit tapped=True — all byte-equal
    on BOTH engines.
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
    from mtg_bot.effects.generic.graveyard import (
        ReturnCreatureFromYourGraveyardToBattlefield,
    )
    from mtg_bot.cards.base import CardPrinting, ManaCost as MC

    real = get_active_source().get_printings().get("Xu-Ifit, Osteoharmonist")
    if real is None:
        pytest.skip("Xu-Ifit, Osteoharmonist absent from active CardSource")
    assert "Creature" in real.card_types
    non_mana_aas = [
        (i, aa) for i, aa in enumerate(real.activated_abilities)
        if not aa.is_mana_ability
    ]
    assert non_mana_aas, (
        "Xu-Ifit, Osteoharmonist must have at least one non-mana ActivatedAbility"
    )
    aa_idx, aa = non_mana_aas[0]
    assert isinstance(aa.effect, ReturnCreatureFromYourGraveyardToBattlefield), (
        f"genuine Xu-Ifit non-mana AA must be "
        f"ReturnCreatureFromYourGraveyardToBattlefield; got {type(aa.effect).__name__}"
    )
    # Verify tap-only cost (no mana component).
    assert aa.cost.tap_self, "Xu-Ifit AA cost must require tapping"
    assert aa.cost.mana is None, (
        "Xu-Ifit AA cost must have no mana component (tap-only)"
    )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2   # ZONE_BATTLEFIELD
    ZGY = 3  # ZONE_GRAVEYARD

    # A simple filler printing for the forced graveyard target.
    filler_printing = CardPrinting(
        name="Xu GY Filler", mana_cost_str="", mana_cost=MC(generic=0),
        type_line="Creature", supertypes=(), card_types=("Creature",),
        subtypes=(), power=1, toughness=1, produces=frozenset(),
    )

    # ---- Python: seat Xu-Ifit on p0's bf (NOT tapped — tap is the cost),
    #      filler in p0's graveyard as the forced target. ----------------
    rp = int(real.power)
    rt = int(real.toughness)
    py_xu = py.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    py_xu.summoning_sick = False
    py_xu.tapped = False
    py_xu.damage = 0
    py_xu.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_xu)

    py_gy_card = py.new_object(
        filler_printing, owner_id=0, zone=Zone.GRAVEYARD
    )
    py.players[0].graveyard.append(py_gy_card)
    # No mana needed — cost is tap_self only.

    # Baseline checks.
    assert len(py.players[0].graveyard) == 1
    assert len(py.battlefield) == 1
    assert not py_xu.tapped

    # ---- Rust: bridged synthetic carrier on bf, filler in p0 gy. -------
    rs_xu_id = rs.register_and_inject_object(
        {
            "name": "Xu-Ifit, Osteoharmonist",
            "card_types": ["Creature"],
            "power": rp, "toughness": rt,
            "activated_abilities": [
                {
                    "cost": {"tap_self": True},
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

    rs.register_and_inject_object(
        {
            "name": "Xu GY Filler",
            "card_types": ["Creature"],
            "power": 1, "toughness": 1,
        },
        0,   # owner = p0
        ZGY, # graveyard zone
    )

    assert rs.graveyard_sizes[0] == 1
    assert rs.battlefield_sizes[0] == 1

    # ---- Python: activate (tap-only cost, default agent picks the
    #      only graveyard creature as target). --------------------------
    _activate_ability(py, 0, py_xu.id, aa_idx)
    assert len(py.stack) == 1, (
        "Xu-Ifit activation must push one StackItem (non-mana)"
    )
    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)
    assert len(py.stack) == 0

    # ---- Rust: activate (Rust pops gy[0] of first non-empty graveyard). -
    rs.apply_action(
        {"kind": "activate_ability", "source_id": rs_xu_id, "ability_index": 0}
    )
    assert rs.stack_size() == 1, (
        "Xu-Ifit activation must push one stack item (non-mana)"
    )
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0

    # ---- Verify zone-move and tap on BOTH engines. --------------------
    py_gy_after = len(py.players[0].graveyard)
    py_bf_after = len(py.battlefield)
    rs_gy_after = rs.graveyard_sizes[0]
    rs_bf_after = rs.battlefield_sizes[0]

    assert py_gy_after == 0 and rs_gy_after == 0, (
        f"filler must leave p0 graveyard on BOTH; "
        f"py_gy={py_gy_after} rs_gy={rs_gy_after}"
    )
    assert py_bf_after == 2 and rs_bf_after == 2, (
        f"filler must be on p0 battlefield (size 2) on BOTH; "
        f"py_bf={py_bf_after} rs_bf={rs_bf_after}"
    )
    assert py_xu.tapped, "Xu-Ifit must be tapped after activation (cost paid)"
    rs_snap = rs.battlefield_snapshot()
    rs_xu_entry = next(e for e in rs_snap if e["id"] == rs_xu_id)
    assert rs_xu_entry["tapped"], (
        "Xu-Ifit (Rust) must be tapped after activation (tap cost paid)"
    )

    # ---- Full compare_fields byte-equality. ---------------------------
    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        "Xu-Ifit {T}: reanimate must be byte-equal across the WHOLE "
        f"field view on BOTH engines; diffs={diffs}"
    )


# ---------------------------------------------------------------------
# Probe #2 — Zookeeper Mechan (covered_by_construction → PROBED).
#
# Oracle (verbatim, ``data/edge_of_eternities.json``):
#   "[Artifact Creature — Construct] 1/3
#    {T}: Add {R}.
#    {6}{R}: Target creature you control gets +4/+0 until end of turn."
# Parser → two ActivatedAbilities:
#   AA[0]: is_mana_ability=True  (the mana ability — out of scope)
#   AA[1]: is_mana_ability=False
#          cost = ActivationCost(mana=ManaCost(generic=6, colored=(('R',1),)),
#                                tap_self=False)
#          effect = PumpTargetCreatureUntilEOT(power_bonus=4, toughness_bonus=0,
#                                              granted_keywords=frozenset())
#
# Rust bridge dict:
#   {"cost": {"mana": {"generic": 6, "R": 1}},
#    "effect": {"kind": "pump_target_creature_until_eot",
#               "power_bonus": 4, "toughness_bonus": 0},
#    "is_mana_ability": false}
#
# Mana supply: both engines pre-funded with 6 green + 1 red coins.
#
# Target selection: in a single-creature state (Zookeeper Mechan alone
# on p0's battlefield), BOTH engines target the Zookeeper itself
# (the only creature p0 controls).  Python's default agent picks
# legal_targets()[0]; Rust's PumpTargetCreatureUntilEOT arm targets
# the first creature on p0's battlefield by scan order.  Both select
# the Zookeeper → effective power 1+4=5 on BOTH.
#
# **NEW cost shape:** generic + colored mana (``{6}{R}``). O2 only
# exercised pure generic-mana costs. This probe confirms the ``"R": 1``
# field in the mana cost dict is accepted end-to-end.
#
# Assertion strength: **full ``compare_fields``** PLUS a direct
# observable (``rs.effective_power`` / ``py_obj.temp_power_bonus``)
# confirming the +4/+0 pump landed on BOTH (targeted-observable idiom
# — same as Dual-Sun Adepts in O2, here with a different cost shape
# and a single-target rather than global pump).
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_zookeeper_mechan_activated_pump_target_colored_mana_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Zookeeper Mechan.
    Batch Q (round 4 activated-ability lane) — colored mana cost ({6}{R}),
    PumpTargetCreatureUntilEOT(+4/+0).**

    Python: the ACTUAL parsed Zookeeper Mechan printing seated on p0's
    battlefield; its non-mana ActivatedAbility (``{6}{R}: Target creature you
    control gets +4/+0 until end of turn``) is activated via
    ``_activate_ability``.  Rust: bridged synthetic carrier with the
    ``{"mana": {"generic": 6, "R": 1}}`` cost dict and the
    ``pump_target_creature_until_eot`` effect.

    **NEW cost shape (generic + colored mana):** First probe in the
    activated-ability family to exercise a colored mana component in the
    ``ActivationCost.mana`` dict end-to-end.

    Assertion strength: **full ``compare_fields``** over the whole field
    view PLUS a direct observable check (``rs.effective_power`` /
    ``temp_power_bonus``) confirming the +4/+0 pump landed on BOTH engines.
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

    real = get_active_source().get_printings().get("Zookeeper Mechan")
    if real is None:
        pytest.skip("Zookeeper Mechan absent from active CardSource")
    assert "Creature" in real.card_types
    non_mana_aas = [
        (i, aa) for i, aa in enumerate(real.activated_abilities)
        if not aa.is_mana_ability
    ]
    assert non_mana_aas, (
        "Zookeeper Mechan must have at least one non-mana ActivatedAbility"
    )
    aa_idx, aa = non_mana_aas[0]
    assert isinstance(aa.effect, PumpTargetCreatureUntilEOT), (
        f"genuine Zookeeper Mechan non-mana AA must be "
        f"PumpTargetCreatureUntilEOT; got {type(aa.effect).__name__}"
    )
    assert aa.effect.power_bonus == 4
    assert aa.effect.toughness_bonus == 0
    assert aa.effect.granted_keywords == frozenset(), (
        "Zookeeper Mechan pump must have no granted_keywords rider"
    )
    assert aa.cost.mana is not None and aa.cost.mana.generic == 6
    # Verify colored mana component.
    colored_dict = dict(aa.cost.mana.colored)
    assert colored_dict.get("R", 0) == 1, (
        f"Zookeeper Mechan AA cost must require 1 red mana; "
        f"got colored={aa.cost.mana.colored}"
    )
    assert not aa.cost.tap_self

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2  # ZONE_BATTLEFIELD

    rp = int(real.power)   # 1
    rt = int(real.toughness)  # 3

    # ---- Python: seat the GENUINE parsed printing on p0's battlefield. ----
    py_obj = py.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    py_obj.summoning_sick = False
    py_obj.tapped = False
    py_obj.damage = 0
    py_obj.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_obj)
    # Pre-fund: {6}{R} = 6 generic (green satisfies) + 1 red.
    py.players[0].mana_pool.extend(
        [ManaCoin("R", None)] + [ManaCoin("G", None)] * 6
    )

    # ---- Rust: bridged synthetic carrier. --------------------------------
    rs_id = rs.register_and_inject_object(
        {
            "name": "Zookeeper Mechan",
            "card_types": ["Artifact", "Creature"],
            "power": rp, "toughness": rt,
            "activated_abilities": [
                {
                    "cost": {"mana": {"generic": 6, "R": 1}},
                    "effect": {
                        "kind": "pump_target_creature_until_eot",
                        "power_bonus": 4,
                        "toughness_bonus": 0,
                    },
                    "is_mana_ability": False,
                }
            ],
        },
        0,   # controller = p0
        ZB,  # battlefield
    )
    rs.clear_summoning_sick_for_player(0)
    rs.add_mana(0, "R", 1)
    rs.add_mana(0, "G", 6)

    # Baseline: base power before activation.
    assert rs.effective_power(rs_id) == rp, (
        f"Rust Zookeeper baseline power must be {rp}"
    )
    assert getattr(py_obj, "temp_power_bonus", 0) == 0

    # ---- Python: activate ability. ------------------------------------
    _activate_ability(py, 0, py_obj.id, aa_idx)
    assert len(py.stack) == 1, (
        "Zookeeper Mechan activation must push one StackItem (non-mana)"
    )
    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)
    assert len(py.stack) == 0

    # ---- Rust: activate ability. --------------------------------------
    rs.apply_action(
        {"kind": "activate_ability", "source_id": rs_id, "ability_index": 0}
    )
    assert rs.stack_size() == 1, (
        "Zookeeper Mechan activation must push one stack item (non-mana)"
    )
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0

    # ---- Direct observable: effective power is base + 4 on BOTH. ------
    # In the single-creature state, BOTH engines target the Zookeeper
    # itself (first / only creature p0 controls).
    py_eff_power = rp + getattr(py_obj, "temp_power_bonus", 0)
    rs_eff_power = rs.effective_power(rs_id)
    assert py_eff_power == rp + 4, (
        f"Python: Zookeeper Mechan effective power must be {rp+4} after "
        f"+4/+0 pump; got {py_eff_power} "
        f"(temp_power_bonus={getattr(py_obj,'temp_power_bonus',0)})"
    )
    assert rs_eff_power == rp + 4, (
        f"Rust: Zookeeper Mechan effective_power must be {rp+4} after "
        f"+4/+0 pump; got {rs_eff_power}"
    )

    # ---- Full compare_fields byte-equality. ---------------------------
    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Zookeeper Mechan {'{6}{R}'}: +4/+0 pump-target must be byte-equal "
        f"across the WHOLE field view on BOTH engines; diffs={diffs}"
    )


# ---------------------------------------------------------------------
# Probe #3 — Ragged Playmate (covered_by_construction → PROBED).
#
# Oracle (verbatim, ``data/edge_of_eternities.json``):
#   "[Artifact Creature — Construct] 2/2
#    {1}, {T}: Target creature with power 2 or less can't be blocked
#    this turn."
# Parser → one non-mana ActivatedAbility:
#   cost = ActivationCost(mana=ManaCost(generic=1), tap_self=True)
#   effect = GrantUnblockableUEOT(power_at_most=2)
#   is_mana_ability = False
#
# Rust bridge dict:
#   {"cost": {"mana": {"generic": 1}, "tap_self": true},
#    "effect": {"kind": "grant_keyword_to_target_creature_until_eot",
#               "keyword": "unblockable"},
#    "is_mana_ability": false}
#
# Mana supply: both engines pre-funded with 1 green coin.
#
# Target selection: Ragged Playmate's own power is 2 (≤ the filter's
# power_at_most=2 bound), so it is a legal target for its own ability.
# In the single-creature state, Python's default agent picks the only
# legal target (the Playmate itself); Rust's
# ``grant_keyword_to_target_creature_until_eot`` arm scans for the
# first creature on p0's battlefield and picks the carrier.  Both
# engines grant the Playmate unblockable for the turn.
#
# **NEW cost shape:** generic mana + tap combined (``{1},{T}``). O2
# only exercised pure generic-mana costs; Xu-Ifit above proved tap-only;
# this probe proves the *combination* (mana AND tap).
#
# "Can't be blocked" effect observability: ``GrantUnblockableUEOT``
# on Python writes a layer-6 ``cant_be_blocked`` registry entry (read
# by ``game.is_cant_be_blocked``).  On Rust, the
# ``grant_keyword_to_target_creature_until_eot{keyword="unblockable"}``
# arm pushes a ``UeotModifier::GrantKeyword{"unblockable"}`` entry
# (read by ``rs.has_keyword(id, "unblockable")``).  The "unblockable"
# UEOT modifier is NOT captured in the field-view zone signature
# (the zone sig encodes tapped/sick/damage/counters/id/controller —
# not UEOT keyword grants).  The raw ``compare_fields == []`` call is
# still the correct strongest assertion for the zone layout; the
# unblockable effect is verified directly via the targeted-observable
# idiom (same pattern as the pump probes).
#
# Assertion strength: **full ``compare_fields``** PLUS direct
# observables (``is_cant_be_blocked`` / ``rs.has_keyword``).
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_ragged_playmate_activated_unblockable_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Ragged Playmate.
    Batch Q (round 4 activated-ability lane) — combined mana+tap cost
    ({1},{T}), GrantUnblockableUEOT.**

    Python: the ACTUAL parsed Ragged Playmate printing seated on p0's
    battlefield; its non-mana ActivatedAbility (``{1},{T}: Target creature
    with power 2 or less can't be blocked this turn``) is activated via
    ``_activate_ability`` targeting the Playmate itself (only valid
    target in the single-creature state).  Rust: bridged synthetic carrier
    with the ``{"mana": {"generic": 1}, "tap_self": true}`` cost dict and
    the ``grant_keyword_to_target_creature_until_eot{keyword="unblockable"}``
    effect.

    **NEW cost shape (generic mana + tap combined):** The third distinct
    tap-related cost shape in the activated-ability family (after
    generic-only in O2 and tap-only in probe #1 above).

    Assertion strength: **full ``compare_fields``** over the whole field
    view PLUS a direct observable check (``is_cant_be_blocked`` /
    ``rs.has_keyword``) confirming the unblockable grant landed on BOTH
    engines (targeted-observable idiom — the UEOT keyword is not in the
    field-view zone signature).
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.actions import _activate_ability, resolve_top_of_stack
    from mtg_bot.game import Zone, ManaCoin, is_cant_be_blocked
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.generic.grant_keywords import GrantUnblockableUEOT

    real = get_active_source().get_printings().get("Ragged Playmate")
    if real is None:
        pytest.skip("Ragged Playmate absent from active CardSource")
    assert "Creature" in real.card_types
    non_mana_aas = [
        (i, aa) for i, aa in enumerate(real.activated_abilities)
        if not aa.is_mana_ability
    ]
    assert non_mana_aas, (
        "Ragged Playmate must have at least one non-mana ActivatedAbility"
    )
    aa_idx, aa = non_mana_aas[0]
    assert isinstance(aa.effect, GrantUnblockableUEOT), (
        f"genuine Ragged Playmate non-mana AA must be "
        f"GrantUnblockableUEOT; got {type(aa.effect).__name__}"
    )
    assert aa.effect.power_at_most == 2, (
        "Ragged Playmate GrantUnblockableUEOT must target power ≤ 2"
    )
    # Verify combined mana + tap cost.
    assert aa.cost.mana is not None and aa.cost.mana.generic == 1, (
        "Ragged Playmate AA cost must require {1} generic mana"
    )
    assert aa.cost.tap_self, "Ragged Playmate AA cost must require tapping"

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2  # ZONE_BATTLEFIELD

    rp = int(real.power)   # 2
    rt = int(real.toughness)  # 2

    # ---- Python: seat the GENUINE parsed printing on p0's battlefield.
    #      Power=2 satisfies the ≤2 target filter for self-targeting. ------
    py_obj = py.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    py_obj.summoning_sick = False
    py_obj.tapped = False
    py_obj.damage = 0
    py_obj.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_obj)
    # Pre-fund: {1} generic (green satisfies).
    py.players[0].mana_pool.extend([ManaCoin("G", None)])

    # ---- Rust: bridged synthetic carrier with combined mana+tap cost. ----
    rs_id = rs.register_and_inject_object(
        {
            "name": "Ragged Playmate",
            "card_types": ["Artifact", "Creature"],
            "power": rp, "toughness": rt,
            "activated_abilities": [
                {
                    "cost": {"mana": {"generic": 1}, "tap_self": True},
                    "effect": {
                        "kind": "grant_keyword_to_target_creature_until_eot",
                        "keyword": "unblockable",
                    },
                    "is_mana_ability": False,
                }
            ],
        },
        0,   # controller = p0
        ZB,  # battlefield
    )
    rs.clear_summoning_sick_for_player(0)
    rs.add_mana(0, "G", 1)

    # Baseline: not tapped, no unblockable grant yet.
    assert not py_obj.tapped
    rs_snap_pre = rs.battlefield_snapshot()
    rs_entry_pre = next(e for e in rs_snap_pre if e["id"] == rs_id)
    assert not rs_entry_pre["tapped"]
    assert not rs.has_keyword(rs_id, "unblockable")

    # ---- Python: activate (default agent picks the Playmate as the only
    #      creature with power ≤ 2 in the single-creature state). ---------
    _activate_ability(py, 0, py_obj.id, aa_idx)
    assert len(py.stack) == 1, (
        "Ragged Playmate activation must push one StackItem (non-mana)"
    )
    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)
    assert len(py.stack) == 0

    # ---- Rust: activate (carrier targets itself as the first creature
    #      on p0's battlefield). ------------------------------------------
    rs.apply_action(
        {"kind": "activate_ability", "source_id": rs_id, "ability_index": 0}
    )
    assert rs.stack_size() == 1, (
        "Ragged Playmate activation must push one stack item (non-mana)"
    )
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0

    # ---- Direct observable: unblockable grant on BOTH engines. ---------
    py_cant_be_blocked = is_cant_be_blocked(py, py_obj)
    rs_has_unblockable = rs.has_keyword(rs_id, "unblockable")

    assert py_cant_be_blocked, (
        "Python: Ragged Playmate must have cant_be_blocked after activation"
    )
    assert rs_has_unblockable, (
        "Rust: Ragged Playmate must have 'unblockable' keyword after activation"
    )

    # ---- Tapped check (combined cost: mana consumed + tap paid). --------
    assert py_obj.tapped, (
        "Ragged Playmate must be tapped after activation (tap cost paid)"
    )
    rs_snap_post = rs.battlefield_snapshot()
    rs_entry_post = next(e for e in rs_snap_post if e["id"] == rs_id)
    assert rs_entry_post["tapped"], (
        "Rust Ragged Playmate must be tapped after activation (tap cost paid)"
    )

    # ---- Full compare_fields byte-equality (zone layout agrees). --------
    # Note: the UEOT unblockable grant is NOT in the field-view zone
    # signature, so compare_fields asserts ZONE LAYOUT equality (both
    # engines see 1 tapped creature on p0's battlefield — tapped IS in
    # the sig).  The unblockable effect itself is verified by the direct
    # observables above (targeted-observable idiom).
    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Ragged Playmate {'{1},{T}'}: cant-be-blocked grant must be "
        f"byte-equal across the WHOLE field view on BOTH engines; "
        f"diffs={diffs}"
    )
