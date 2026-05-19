"""Genuine real-EoE cross-engine byte-equality probes — activated-ability
lane, batch T (round 5 of the activated-ability family).

**Context — extending O2 + Q.**  Batch O2 opened the activated-ability
probe family with three EoE cards using *pure generic mana* costs
(``{3}``, ``{2}``, ``{5}``).  Batch Q extended with three new cost shapes:
tap-only (``{T}``), colored mana (``{6}{R}``), and mana+tap combined
(``{1},{T}``).  This module (batch T) extends the same lane with a **fourth
cost axis — sacrifice_self as a cost component** — across three different
sub-shapes:

  - Pure generic mana + sacrifice_self (``{2}, sac self``): Illvoi Galeblade
  - Colored mana + sacrifice_self (``{3}{B}, sac self``): Valgavoth's Faithful
  - Generic mana + tap + sacrifice_self (``{6},{T}, sac self``): Thaumaton Torpedo

All three cards are in the ``covered_by_construction`` tier at HEAD (every
Effect class they emit has a live Rust variant + bridge arm, but no genuine
real-EoE probe pins that card).  This module promotes them to PROBED.

**sacrifice_self cost bridge note:**  The Rust ``ActivationCost`` struct
carries a ``sacrifice_self: bool`` field (landed in the CE20 follow-up
Slice 2).  The ``parse_activation_cost`` parser accepts the ``"sacrifice_self"``
key (``state_ops_actions.rs:parse_activation_cost``).  At resolve time, the
Rust engine pays the sacrifice cost BEFORE resolving the effect: the source
object is moved from its current zone to its owner's graveyard during cost
payment (``state_ops_actions.rs:ActivateAbility``, phase 5b).  Python's
``_activate_ability`` follows the same order: ``cost.sacrifice_self`` is
checked at cost-payment time and the source is sacrificed before the
stack item is pushed.

**Batch O2 + Q cross-reference:**  O2 proved generic-mana cost shapes
with zero tap/sacrifice component; Q proved tap-only, colored mana, and
mana+tap combined.  This batch closes the ``sacrifice_self`` gap — confirming
that all four cost axes (mana, tap, sacrifice_self, and their combinations)
are fully wired on the CE20 substrate.

**Card picks:**

  1. Illvoi Galeblade  (covered_by_construction → PROBED)
     ``{2}, sacrifice this creature: Draw a card.``
     Cost: generic=2 + sacrifice_self=True (no tap).
     Effect: ``DrawCards(amount=1)``.
     The activation draws from p0's library — filler card seeded in library
     to observe the draw zone-move.  Illvoi sacrifices to graveyard; filler
     moves from library to hand.  Zone sizes (bf 1→0, lib 1→0, hand 0→1,
     gy 0→1) are all captured in the field view.  ID ordering: filler
     registered first (id=0), Illvoi second (id=1) on BOTH engines.
     **NEW cost shape:** pure mana + sacrifice_self (no tap component).

  2. Valgavoth's Faithful  (covered_by_construction → PROBED)
     ``{3}{B}, sacrifice this creature: Return target creature card from
     your graveyard to the battlefield.``
     Cost: generic=3 + B=1 + sacrifice_self=True (no tap).
     Effect: ``ReturnCreatureFromYourGraveyardToBattlefield``.
     Graveyard filler seeded in p0's GY as the forced reanimate target.
     After activation: Valgavoth sacrifices to GY; filler reanimates to BF.
     Zone-size net: bf 1→1 (Valgavoth out, filler in), gy 1→1 (filler
     out, Valgavoth in) — card identities swap, captured in the field-view
     zone signature.  ID ordering: filler first (id=0), Valgavoth second
     (id=1) on BOTH engines.
     **NEW cost shape:** colored mana + sacrifice_self (new colored component
     in the sacrifice-self sub-family; O2/Q colored probes used non-sacrifice
     costs).

  3. Thaumaton Torpedo  (covered_by_construction → PROBED)
     ``{6}, {T}, sacrifice this artifact: Destroy target nonland permanent.``
     Cost: generic=6 + tap_self=True + sacrifice_self=True.
     Effect: ``DestroyTargetNonlandPermanent``.
     Victim creature seated on p1's battlefield as the forced target.
     Rust's ``DestroyTargetNonlandPermanent`` arm scans bf_iter_etb_sorted
     for the first non-land, non-indestructible permanent (after Torpedo
     sacrifices itself, the only remaining permanent is the p1 victim).
     Python's default agent picks the only legal target (the p1 victim).
     After activation: Torpedo → p0 GY (sacrifice cost), victim → p1 GY
     (destroy effect).
     ID ordering: Torpedo first (id=0), victim second (id=1) on BOTH engines.
     **NEW cost shape:** mana + tap + sacrifice_self (triple combination —
     first probe in the family with all three non-colored-mana cost axes
     active simultaneously).

**DROPPED candidates:**

  * Nutrient Block: ``{2},{T}, sacrifice_self: GainLife(3)`` — also carries
    a ``leaves_battlefield`` triggered ability (DrawCards(1)) that fires
    when the artifact is sacrificed; in the single-card probe state the
    draw from an empty library marks p0 as having lost (``attempted_draw_on_
    empty``), making ``is_over=True`` in Python while Rust's ``is_over``
    disagrees.  The LTB trigger causes compare_fields divergence on
    ``is_over`` / ``winner_id`` fields; out of scope for this batch.
  * Slagdrill Scrapper: ``{2},{T}: DrawCards(1)`` — ``sacrifice_another_
    artifact_or_land=True`` in cost; not a field on Rust's ``ActivationCost``
    (same blocker as O2 drop-list).
  * Sunstar Chaplain: ``{2}: TapTargetArtifactOrCreature`` — ``remove_plus_
    one_counter_from_your_creature=True`` in cost; deferred blocker carried
    from O2 + Q.
  * Kavaron Turbodrone: ``{T}: PumpTargetCreatureUntilEOT`` — ``granted_
    keywords=frozenset({'haste'})`` rider on the Python effect; same
    blocker from O2 + Q.

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
# Probe #1 — Illvoi Galeblade (covered_by_construction → PROBED).
#
# Oracle (verbatim, ``data/edge_of_eternities.json``):
#   "[Creature — Human Warrior] 1/1
#    {2}, Sacrifice Illvoi Galeblade: Draw a card."
# Parser → one non-mana ActivatedAbility:
#   cost = ActivationCost(mana=ManaCost(generic=2), tap_self=False,
#                         sacrifice_self=True)
#   effect = DrawCards(amount=1)
#   is_mana_ability = False
#
# Rust bridge dict:
#   {"cost": {"mana": {"generic": 2}, "sacrifice_self": true},
#    "effect": {"kind": "draw_cards", "count": 1},
#    "is_mana_ability": false}
#
# Setup: a single draw-filler creature is seeded in p0's library
# (id=0); Illvoi Galeblade is seated on p0's battlefield (id=1).
# Mana supply: 2 green coins (generic satisfies {2}).
#
# After activation on BOTH engines:
#   - Illvoi Galeblade pays sacrifice_self cost → moves to p0 graveyard
#   - DrawCards resolves → filler moves from library to hand
#   - Zone net: bf 1→0, lib 1→0, hand 0→1, gy 0→1
#
# ID ordering: filler registered first (id=0) on BOTH engines so the
# graveyard-signature id slot matches across engines.
#
# **NEW cost shape:** pure generic mana + sacrifice_self (no tap
# component). All prior activated-ability probes (O2 + Q) used
# non-sacrifice costs only; this is the first sacrifice_self probe
# in the dedicated activated-ability module family.
#
# Assertion strength: **full ``compare_fields``** (strongest tier).
# All four zone-size moves (bf/lib/hand/gy) plus the card identity
# swaps are captured in the field-view signature and match byte-equal.
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_illvoi_galeblade_activated_sacrifice_draw_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Illvoi Galeblade.
    Batch T (round 5 activated-ability lane) — pure mana + sacrifice_self
    cost ({2}, sac self), DrawCards(1).**

    Python: the ACTUAL parsed Illvoi Galeblade printing seated on p0's
    battlefield; its non-mana ActivatedAbility (``{2}, Sacrifice Illvoi
    Galeblade: Draw a card``) is activated via ``_activate_ability``.
    Rust: bridged synthetic carrier with the ``{"mana": {"generic": 2},
    "sacrifice_self": true}`` cost dict and the ``draw_cards`` effect.

    **NEW cost shape (mana + sacrifice_self):** First probe in the
    activated-ability family to exercise ``sacrifice_self`` as a cost
    component on the CE20 substrate end-to-end.

    Assertion strength: **full ``compare_fields``** over the whole
    cross-engine field view — bf shrinks 1→0 (Illvoi sacrificed), lib
    shrinks 1→0 (filler drawn), hand grows 0→1 (filler drawn), gy grows
    0→1 (Illvoi sacrificed) — all byte-equal on BOTH engines.
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

    real = get_active_source().get_printings().get("Illvoi Galeblade")
    if real is None:
        pytest.skip("Illvoi Galeblade absent from active CardSource")
    assert "Creature" in real.card_types
    non_mana_aas = [
        (i, aa) for i, aa in enumerate(real.activated_abilities)
        if not aa.is_mana_ability
    ]
    assert non_mana_aas, (
        "Illvoi Galeblade must have at least one non-mana ActivatedAbility"
    )
    aa_idx, aa = non_mana_aas[0]
    assert isinstance(aa.effect, DrawCards), (
        f"genuine Illvoi Galeblade non-mana AA must be DrawCards; "
        f"got {type(aa.effect).__name__}"
    )
    assert aa.effect.amount == 1, (
        "Illvoi Galeblade DrawCards must draw exactly 1 card"
    )
    assert aa.cost.sacrifice_self, (
        "Illvoi Galeblade AA cost must require sacrificing itself"
    )
    assert not aa.cost.tap_self, (
        "Illvoi Galeblade AA cost must NOT require tapping (pure mana+sac)"
    )
    assert aa.cost.mana is not None and aa.cost.mana.generic == 2, (
        "Illvoi Galeblade AA cost must require {2} generic mana"
    )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2   # ZONE_BATTLEFIELD
    ZL = 1   # ZONE_LIBRARY

    rp = int(real.power)
    rt = int(real.toughness)

    # A filler printing for the forced draw target (seeded in library).
    filler_printing = CardPrinting(
        name="Illvoi Draw Filler", mana_cost_str="", mana_cost=MC(generic=0),
        type_line="Creature", supertypes=(), card_types=("Creature",),
        subtypes=(), power=1, toughness=1, produces=frozenset(),
    )

    # ---- Python: filler in library (id=0), Illvoi on p0's bf (id=1).
    #      filler.summoning_sick=False (it's in library, not freshly ETB'd). ---
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
    # Pre-fund: {2} generic (2 green coins satisfy generic).
    py.players[0].mana_pool.extend([ManaCoin("G", None)] * 2)

    # ---- Rust: same registration order — filler in library (id=0),
    #      Illvoi in battlefield (id=1). -----------------------------------
    rs.register_and_inject_object(
        {
            "name": "Illvoi Draw Filler",
            "card_types": ["Creature"],
            "power": 1, "toughness": 1,
        },
        0,   # owner = p0
        ZL,  # library zone
    )
    rs_id = rs.register_and_inject_object(
        {
            "name": "Illvoi Galeblade",
            "card_types": ["Creature"],
            "power": rp, "toughness": rt,
            "activated_abilities": [
                {
                    "cost": {"mana": {"generic": 2}, "sacrifice_self": True},
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
    rs.add_mana(0, "G", 2)

    # Baseline checks.
    assert len(py.players[0].library) == 1
    assert len(py.battlefield) == 1
    assert len(py.players[0].hand) == 0
    assert rs.library_sizes[0] == 1
    assert rs.battlefield_sizes[0] == 1
    assert rs.hand_sizes[0] == 0

    # ---- Python: activate (sacrifice self, draw 1 from library). ----------
    _activate_ability(py, 0, py_obj.id, aa_idx)
    assert len(py.stack) == 1, (
        "Illvoi Galeblade activation must push one StackItem (non-mana)"
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
        "Illvoi Galeblade activation must push one stack item (non-mana)"
    )
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0

    # ---- Verify zone moves on BOTH engines. ------------------------------
    py_bf = len(py.battlefield)
    py_hand = len(py.players[0].hand)
    py_lib = len(py.players[0].library)
    py_gy = len(py.players[0].graveyard)
    rs_bf = rs.battlefield_sizes[0]
    rs_hand = rs.hand_sizes[0]
    rs_lib = rs.library_sizes[0]
    rs_gy = rs.graveyard_sizes[0]

    assert py_bf == 0 and rs_bf == 0, (
        f"Illvoi Galeblade must have left battlefield (sacrificed) on BOTH; "
        f"py_bf={py_bf} rs_bf={rs_bf}"
    )
    assert py_gy == 1 and rs_gy == 1, (
        f"Illvoi Galeblade must be in p0 graveyard on BOTH; "
        f"py_gy={py_gy} rs_gy={rs_gy}"
    )
    assert py_hand == 1 and rs_hand == 1, (
        f"Filler must have been drawn to p0 hand on BOTH; "
        f"py_hand={py_hand} rs_hand={rs_hand}"
    )
    assert py_lib == 0 and rs_lib == 0, (
        f"Library must be empty after draw on BOTH; "
        f"py_lib={py_lib} rs_lib={rs_lib}"
    )

    # ---- Full compare_fields byte-equality. ---------------------------
    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        "Illvoi Galeblade {2}, sac self: draw 1 must be byte-equal across "
        f"the WHOLE field view on BOTH engines; diffs={diffs}"
    )


# ---------------------------------------------------------------------
# Probe #2 — Valgavoth's Faithful (covered_by_construction → PROBED).
#
# Oracle (verbatim, ``data/edge_of_eternities.json``):
#   "[Creature — Vampire] 1/1
#    {3}{B}, Sacrifice Valgavoth's Faithful: Return target creature card
#    from your graveyard to the battlefield."
# Parser → one non-mana ActivatedAbility:
#   cost = ActivationCost(mana=ManaCost(generic=3, colored=(('B',1),)),
#                         tap_self=False, sacrifice_self=True)
#   effect = ReturnCreatureFromYourGraveyardToBattlefield()
#   is_mana_ability = False
#
# Rust bridge dict:
#   {"cost": {"mana": {"generic": 3, "B": 1}, "sacrifice_self": true},
#    "effect": {"kind": "return_creature_from_your_graveyard_to_battlefield"},
#    "is_mana_ability": false}
#
# Mana supply: 1 black + 3 green coins (green satisfies generic).
#
# Setup: a filler creature in p0's graveyard (id=0) as the forced
# reanimate target; Valgavoth's Faithful on p0's battlefield (id=1).
# No triggered abilities on the card.
#
# After activation on BOTH engines:
#   - Valgavoth's Faithful sacrifices to p0 GY
#   - ReturnCreatureFromYourGraveyardToBattlefield reanimates filler
#     from p0 GY to p0 BF
#   - Zone net: bf 1→1 (Valgavoth out, filler in), gy 1→1 (filler
#     out, Valgavoth in) — card identities swap, captured in zone sig
#
# ID ordering: filler first (id=0), Valgavoth second (id=1) on BOTH.
# After the swap: graveyard sig contains Valgavoth (id=1);
# battlefield sig contains filler (id=0). Both engines agree.
#
# **NEW cost shape:** colored mana + sacrifice_self (no tap). Batch Q
# proved colored mana (``{6}{R}``) without sacrifice; this probe is
# the first in the family to combine a colored mana component WITH
# sacrifice_self.
#
# Assertion strength: **full ``compare_fields``** over the whole
# cross-engine field view — all zone-size moves and card-identity
# swaps captured in the zone signature.
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_valgavoth_faithful_activated_sacrifice_reanimate_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Valgavoth's Faithful.
    Batch T (round 5 activated-ability lane) — colored mana + sacrifice_self
    cost ({3}{B}, sac self), ReturnCreatureFromYourGraveyardToBattlefield.**

    Python: the ACTUAL parsed Valgavoth's Faithful printing seated on p0's
    battlefield; its non-mana ActivatedAbility (``{3}{B}, Sacrifice
    Valgavoth's Faithful: Return target creature card from your graveyard
    to the battlefield``) is activated via ``_activate_ability`` targeting
    the only filler creature in p0's graveyard.  Rust: bridged synthetic
    carrier with the ``{"mana": {"generic": 3, "B": 1},
    "sacrifice_self": true}`` cost dict and the
    ``return_creature_from_your_graveyard_to_battlefield`` effect.

    **NEW cost shape (colored mana + sacrifice_self):** First probe in the
    activated-ability family to exercise a colored mana component combined
    with ``sacrifice_self`` cost on the CE20 substrate end-to-end.

    Assertion strength: **full ``compare_fields``** over the whole field
    view — zone-size moves and card-identity swaps across bf and gy are
    captured in the zone signature and match byte-equal on BOTH engines.
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
    from mtg_bot.effects.generic.graveyard import (
        ReturnCreatureFromYourGraveyardToBattlefield,
    )
    from mtg_bot.cards.base import CardPrinting, ManaCost as MC

    real = get_active_source().get_printings().get("Valgavoth's Faithful")
    if real is None:
        pytest.skip("Valgavoth's Faithful absent from active CardSource")
    assert "Creature" in real.card_types
    non_mana_aas = [
        (i, aa) for i, aa in enumerate(real.activated_abilities)
        if not aa.is_mana_ability
    ]
    assert non_mana_aas, (
        "Valgavoth's Faithful must have at least one non-mana ActivatedAbility"
    )
    aa_idx, aa = non_mana_aas[0]
    assert isinstance(aa.effect, ReturnCreatureFromYourGraveyardToBattlefield), (
        f"genuine Valgavoth's Faithful non-mana AA must be "
        f"ReturnCreatureFromYourGraveyardToBattlefield; "
        f"got {type(aa.effect).__name__}"
    )
    assert aa.cost.sacrifice_self, (
        "Valgavoth's Faithful AA cost must require sacrificing itself"
    )
    assert not aa.cost.tap_self, (
        "Valgavoth's Faithful AA cost must NOT require tapping"
    )
    assert aa.cost.mana is not None and aa.cost.mana.generic == 3, (
        "Valgavoth's Faithful AA cost must require {3} generic mana"
    )
    # Verify colored mana component (black).
    colored_dict = dict(aa.cost.mana.colored)
    assert colored_dict.get("B", 0) == 1, (
        f"Valgavoth's Faithful AA cost must require 1 black mana; "
        f"got colored={aa.cost.mana.colored}"
    )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2    # ZONE_BATTLEFIELD
    ZGY = 3   # ZONE_GRAVEYARD

    rp = int(real.power)
    rt = int(real.toughness)

    # A filler printing for the forced graveyard reanimate target.
    filler_printing = CardPrinting(
        name="Valg GY Filler", mana_cost_str="", mana_cost=MC(generic=0),
        type_line="Creature", supertypes=(), card_types=("Creature",),
        subtypes=(), power=2, toughness=2, produces=frozenset(),
    )

    # ---- Python: filler in p0 GY (id=0), Valgavoth on p0 BF (id=1). ----
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
    # Pre-fund: {3}{B} = 3 generic (green) + 1 black.
    py.players[0].mana_pool.extend(
        [ManaCoin("B", None)] + [ManaCoin("G", None)] * 3
    )

    # ---- Rust: same registration order — filler in GY (id=0),
    #      Valgavoth's Faithful in BF (id=1). ------------------------------
    rs.register_and_inject_object(
        {
            "name": "Valg GY Filler",
            "card_types": ["Creature"],
            "power": 2, "toughness": 2,
        },
        0,    # owner = p0
        ZGY,  # graveyard zone
    )
    rs_id = rs.register_and_inject_object(
        {
            "name": "Valgavoth's Faithful",
            "card_types": ["Creature"],
            "power": rp, "toughness": rt,
            "activated_abilities": [
                {
                    "cost": {
                        "mana": {"generic": 3, "B": 1},
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
    rs.add_mana(0, "B", 1)
    rs.add_mana(0, "G", 3)

    # Baseline checks.
    assert len(py.players[0].graveyard) == 1
    assert len(py.battlefield) == 1
    assert rs.graveyard_sizes[0] == 1
    assert rs.battlefield_sizes[0] == 1

    # ---- Python: activate (single GY creature forced target). ------------
    _activate_ability(py, 0, py_obj.id, aa_idx)
    assert len(py.stack) == 1, (
        "Valgavoth's Faithful activation must push one StackItem (non-mana)"
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
        "Valgavoth's Faithful activation must push one stack item (non-mana)"
    )
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0

    # ---- Verify zone swap on BOTH engines. --------------------------------
    py_bf = len(py.battlefield)
    py_gy = len(py.players[0].graveyard)
    rs_bf = rs.battlefield_sizes[0]
    rs_gy = rs.graveyard_sizes[0]

    assert py_bf == 1 and rs_bf == 1, (
        f"Exactly one creature must be on p0 battlefield after swap on BOTH; "
        f"py_bf={py_bf} rs_bf={rs_bf}"
    )
    assert py_gy == 1 and rs_gy == 1, (
        f"Exactly one creature must be in p0 graveyard after swap on BOTH; "
        f"py_gy={py_gy} rs_gy={rs_gy}"
    )
    # Verify card identities swapped.
    bf_name_py = py.battlefield[0].printing.name
    gy_name_py = py.players[0].graveyard[0].printing.name
    rs_bf_snap = rs.battlefield_snapshot()
    rs_gy_snap = rs.graveyard_snapshot(0)
    bf_name_rs = rs_bf_snap[0]["printing_name"]
    gy_name_rs = rs_gy_snap[0]["printing_name"]
    assert bf_name_py == "Valg GY Filler" and bf_name_rs == "Valg GY Filler", (
        f"Filler must be on p0 battlefield on BOTH; "
        f"py={bf_name_py!r} rs={bf_name_rs!r}"
    )
    assert gy_name_py == "Valgavoth's Faithful" and gy_name_rs == "Valgavoth's Faithful", (
        f"Valgavoth's Faithful must be in p0 graveyard on BOTH; "
        f"py={gy_name_py!r} rs={gy_name_rs!r}"
    )

    # ---- Full compare_fields byte-equality. ---------------------------
    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        "Valgavoth's Faithful {3}{B}, sac self: reanimate must be "
        "byte-equal across the WHOLE field view on BOTH engines; "
        f"diffs={diffs}"
    )


# ---------------------------------------------------------------------
# Probe #3 — Thaumaton Torpedo (covered_by_construction → PROBED).
#
# Oracle (verbatim, ``data/edge_of_eternities.json``):
#   "[Artifact] (no power/toughness — not a creature)
#    {6}, {T}, Sacrifice Thaumaton Torpedo: Destroy target nonland
#    permanent."
# Parser → one non-mana ActivatedAbility:
#   cost = ActivationCost(mana=ManaCost(generic=6), tap_self=True,
#                         sacrifice_self=True)
#   effect = DestroyTargetNonlandPermanent()
#   is_mana_ability = False
#
# Rust bridge dict:
#   {"cost": {"mana": {"generic": 6}, "tap_self": true,
#             "sacrifice_self": true},
#    "effect": {"kind": "destroy_target_nonland_permanent"},
#    "is_mana_ability": false}
#
# Mana supply: 6 green coins (green satisfies generic {6}).
#
# Target selection: a victim creature on p1's battlefield is the only
# non-land permanent. After Torpedo pays its tap+sacrifice cost (the
# artifact leaves BF during cost payment), Rust's
# ``DestroyTargetNonlandPermanent`` arm scans bf_iter_etb_sorted for
# the first non-land, non-indestructible permanent — with Torpedo
# gone, only the victim remains. Python's default agent also picks
# the victim as the only legal target at legal_targets() time.
# Both engines destroy the victim → victim moves to p1's GY.
#
# Setup (ID ordering): Torpedo first (id=0), victim second (id=1)
# on BOTH engines.  After activation: Torpedo in p0 GY (sacrifice
# cost), victim in p1 GY (destroy effect).
#
# **NEW cost shape:** generic mana + tap + sacrifice_self combined —
# the FIRST probe in the activated-ability family to activate all
# three non-colored-mana cost axes (mana, tap, sacrifice_self)
# simultaneously.  Prior batches proved: mana-only (O2), tap-only
# (Q), colored mana (Q), mana+tap (Q), mana+sacrifice_self (T#1,2).
# This completes the combinatorial coverage of the proven cost axes.
#
# Assertion strength: **full ``compare_fields``** (strongest tier).
# Both Torpedo's graveyard move (p0 gy 0→1) and the victim's
# destruction (p1 bf 1→0, p1 gy 0→1) are captured in the field view
# and match byte-equal on BOTH engines.
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_thaumaton_torpedo_activated_triple_cost_destroy_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Thaumaton Torpedo.
    Batch T (round 5 activated-ability lane) — triple cost (mana + tap +
    sacrifice_self: {6},{T}, sac self), DestroyTargetNonlandPermanent.**

    Python: the ACTUAL parsed Thaumaton Torpedo printing (Artifact) seated
    on p0's battlefield; its non-mana ActivatedAbility (``{6}, {T},
    Sacrifice Thaumaton Torpedo: Destroy target nonland permanent``) is
    activated via ``_activate_ability`` targeting the victim creature on
    p1's battlefield.  Rust: bridged synthetic carrier with the
    ``{"mana": {"generic": 6}, "tap_self": true, "sacrifice_self": true}``
    cost dict and the ``destroy_target_nonland_permanent`` effect.

    **NEW cost shape (mana + tap + sacrifice_self triple):** The first probe
    in the activated-ability family to exercise all three non-colored-mana
    cost axes simultaneously on the CE20 substrate end-to-end.

    Assertion strength: **full ``compare_fields``** over the whole field
    view — Torpedo leaves p0 bf (sacrifice cost), victim leaves p1 bf
    (destroy effect), both move to their respective graveyards — all
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
    from mtg_bot.effects.generic.destroy import DestroyTargetNonlandPermanent
    from mtg_bot.cards.base import CardPrinting, ManaCost as MC

    real = get_active_source().get_printings().get("Thaumaton Torpedo")
    if real is None:
        pytest.skip("Thaumaton Torpedo absent from active CardSource")
    assert "Artifact" in real.card_types
    non_mana_aas = [
        (i, aa) for i, aa in enumerate(real.activated_abilities)
        if not aa.is_mana_ability
    ]
    assert non_mana_aas, (
        "Thaumaton Torpedo must have at least one non-mana ActivatedAbility"
    )
    aa_idx, aa = non_mana_aas[0]
    assert isinstance(aa.effect, DestroyTargetNonlandPermanent), (
        f"genuine Thaumaton Torpedo non-mana AA must be "
        f"DestroyTargetNonlandPermanent; got {type(aa.effect).__name__}"
    )
    # Verify triple cost.
    assert aa.cost.sacrifice_self, (
        "Thaumaton Torpedo AA cost must require sacrificing itself"
    )
    assert aa.cost.tap_self, (
        "Thaumaton Torpedo AA cost must require tapping"
    )
    assert aa.cost.mana is not None and aa.cost.mana.generic == 6, (
        "Thaumaton Torpedo AA cost must require {6} generic mana"
    )
    assert not real.triggered_abilities, (
        "Thaumaton Torpedo must have no triggered abilities (clean probe)"
    )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2   # ZONE_BATTLEFIELD

    # A victim creature on p1's battlefield.
    victim_printing = CardPrinting(
        name="Torpedo Victim", mana_cost_str="", mana_cost=MC(generic=0),
        type_line="Creature", supertypes=(), card_types=("Creature",),
        subtypes=(), power=3, toughness=3, produces=frozenset(),
    )

    # ---- Python: Torpedo on p0's bf (id=0), victim on p1's bf (id=1). ----
    py_torpedo = py.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    py_torpedo.summoning_sick = False
    py_torpedo.tapped = False
    py_torpedo.damage = 0
    py_torpedo.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_torpedo)
    # Pre-fund: {6} generic (6 green coins).
    py.players[0].mana_pool.extend([ManaCoin("G", None)] * 6)

    py_victim = py.new_object(victim_printing, owner_id=1, zone=Zone.BATTLEFIELD)
    py_victim.summoning_sick = False
    py_victim.tapped = False
    py_victim.damage = 0
    py_victim.controller_id = 1
    py_victim.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_victim)

    # ---- Rust: same order — Torpedo in p0 bf (id=0), victim in p1 bf (id=1). -
    rs_torpedo_id = rs.register_and_inject_object(
        {
            "name": "Thaumaton Torpedo",
            "card_types": ["Artifact"],
            "activated_abilities": [
                {
                    "cost": {
                        "mana": {"generic": 6},
                        "tap_self": True,
                        "sacrifice_self": True,
                    },
                    "effect": {
                        "kind": "destroy_target_nonland_permanent",
                    },
                    "is_mana_ability": False,
                }
            ],
        },
        0,   # controller = p0
        ZB,  # battlefield
    )
    rs.clear_summoning_sick_for_player(0)
    rs.add_mana(0, "G", 6)

    rs.register_and_inject_object(
        {
            "name": "Torpedo Victim",
            "card_types": ["Creature"],
            "power": 3, "toughness": 3,
        },
        1,   # controller = p1
        ZB,  # battlefield
    )
    rs.clear_summoning_sick_for_player(1)

    # Baseline checks.
    assert len(py.battlefield) == 2, (
        "Battlefield must start with 2 permanents (Torpedo + Victim)"
    )
    assert rs.battlefield_sizes[0] == 1
    assert rs.battlefield_sizes[1] == 1
    assert rs.graveyard_sizes[0] == 0
    assert rs.graveyard_sizes[1] == 0

    # ---- Python: activate (single victim as only legal target). ----------
    _activate_ability(py, 0, py_torpedo.id, aa_idx)
    assert len(py.stack) == 1, (
        "Thaumaton Torpedo activation must push one StackItem (non-mana)"
    )
    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)
    assert len(py.stack) == 0

    # ---- Rust: activate. -------------------------------------------------
    rs.apply_action(
        {"kind": "activate_ability", "source_id": rs_torpedo_id, "ability_index": 0}
    )
    assert rs.stack_size() == 1, (
        "Thaumaton Torpedo activation must push one stack item (non-mana)"
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
        f"Torpedo must have left p0 battlefield (sacrificed) on BOTH; "
        f"py={py_p0_bf} rs={rs_p0_bf}"
    )
    assert py_p1_bf == 0 and rs_p1_bf == 0, (
        f"Victim must have left p1 battlefield (destroyed) on BOTH; "
        f"py={py_p1_bf} rs={rs_p1_bf}"
    )
    assert py_p0_gy == 1 and rs_p0_gy == 1, (
        f"Torpedo must be in p0 graveyard on BOTH; "
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
        "Thaumaton Torpedo {6},{T}, sac self: destroy nonland permanent "
        "must be byte-equal across the WHOLE field view on BOTH engines; "
        f"diffs={diffs}"
    )
