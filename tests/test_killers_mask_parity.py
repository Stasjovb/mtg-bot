"""Killer's Mask — per-card real-EoE cross-engine byte-equal probe
(covered_by_construction → PROBED tier flip).

Killer's Mask is a ``{2}{B}`` Artifact — Equipment in the EoE pool
(Duskmourn special-guests reprint slot, 0 17lands decks) with the
canonical Duskmourn Equipment ETB manifest-dread shape:

    "When this Equipment enters, manifest dread, then attach this
    Equipment to that creature.
    Equip {2}."

Parser-emitted Effect shape:

  * Activated ability (paid Equip): mana cost ``{2}``, no tap_self,
    sorcery-speed=True, effect = ``EquipToTargetCreatureYouControl(
    granted_keywords_ueot=frozenset())``.
  * Triggered ability on ENTERS: ``ManifestDreadThenAttachSelf()``.

**EEEE-idiom for the dual-effect Duskmourn-Equipment carrier** —
sibling to ``test_conductive_machete_parity.py`` and
``test_cursed_windbreaker_parity.py`` (the same two-effect bridge-
clean shape).  Per-slug attribution distinction:

  * **Mana-cost color** — Killer's Mask is ``{2}{B}`` (black);
    Conductive Machete is ``{4}`` (colorless); Cursed Windbreaker
    is ``{2}{U}`` (blue).
  * **Equip cost** — Killer's Mask Equip{2}; Conductive Machete
    Equip{4}; Cursed Windbreaker Equip{3}.

The Effect-half shapes are bit-identical across all three slugs (both
arms are unit-variant on the Python side; the only structural
distinctions are cost-side fields).  Per the cathedral-of-war-style
same-Effect-class-different-printing-slug precedent, Killer's Mask
earns its own PROBED-tier slot on the per-slug attribution lane.
"""

from __future__ import annotations

import importlib.util

import pytest

from mtg_bot.cards.source import get_active_source
from mtg_bot.effects.generic.attach import (
    EquipToTargetCreatureYouControl,
)
from mtg_bot.effects.generic.library_lookat import (
    ManifestDreadThenAttachSelf,
)


_PRINTINGS = get_active_source().get_printings()


_rust_skip = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


ZONE_BATTLEFIELD = 2


# ---------------------------------------------------------------------------
# (1) Parser SoT.
# ---------------------------------------------------------------------------


def test_killers_mask_parser_claims_card():
    assert "Killer's Mask" in _PRINTINGS, (
        "Killer's Mask must be parser-claimed by the active CardSource"
    )


def test_killers_mask_printed_attrs():
    """Pins printing surface: Artifact - Equipment, mana cost {2}{B},
    no keywords or static abilities."""
    p = _PRINTINGS["Killer's Mask"]
    assert "Artifact" in p.card_types
    assert "Equipment" in p.subtypes
    assert p.mana_cost.generic == 2
    assert p.mana_cost.colored == (("B", 1),), (
        f"Killer's Mask mana_cost must be {{2}}{{B}} (distinct from "
        f"Conductive Machete {{4}} and Cursed Windbreaker {{2}}{{U}}); "
        f"got colored={p.mana_cost.colored}"
    )
    assert p.keywords == frozenset()
    assert p.spell_effect is None
    assert p.static_abilities == ()


def test_killers_mask_equip_aa_shape():
    """Killer's Mask has exactly one ActivatedAbility (the Equip {2}
    ability); effect = bare ``EquipToTargetCreatureYouControl(granted_
    keywords_ueot=frozenset())``."""
    p = _PRINTINGS["Killer's Mask"]
    assert len(p.activated_abilities) == 1
    aa = p.activated_abilities[0]
    assert isinstance(aa.effect, EquipToTargetCreatureYouControl)
    assert aa.effect.granted_keywords_ueot == frozenset()
    assert aa.cost.tap_self is False
    assert aa.cost.mana is not None and aa.cost.mana.generic == 2, (
        f"Killer's Mask Equip cost must be {{2}} (distinct from "
        f"Conductive Machete's {{4}} / Cursed Windbreaker's {{3}}); "
        f"got generic={aa.cost.mana.generic}"
    )
    assert aa.is_mana_ability is False
    assert aa.sorcery_speed is True


def test_killers_mask_etb_ta_shape():
    """Killer's Mask has exactly one TriggeredAbility (the ETB
    manifest-dread-then-attach); effect = bare
    ``ManifestDreadThenAttachSelf()``."""
    p = _PRINTINGS["Killer's Mask"]
    assert len(p.triggered_abilities) == 1
    ta = p.triggered_abilities[0]
    assert isinstance(ta.effect, ManifestDreadThenAttachSelf)
    from mtg_bot.effects.predicates import Event
    assert ta.event is Event.ENTERS


# ---------------------------------------------------------------------------
# (2) Bridge round-trip.
# ---------------------------------------------------------------------------


def test_killers_mask_bridge_arms_round_trip():
    """Both bridge arms round-trip the Killer's Mask shapes byte-
    equal."""
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    bridged_eq = _ta_dict_to_python_effect(
        {"kind": "equip_to_target_creature_you_control"}
    )
    bridged_mt = _ta_dict_to_python_effect(
        {"kind": "manifest_dread_then_attach_self"}
    )
    assert isinstance(bridged_eq, EquipToTargetCreatureYouControl)
    assert isinstance(bridged_mt, ManifestDreadThenAttachSelf)
    p = _PRINTINGS["Killer's Mask"]
    assert p.activated_abilities[0].effect == bridged_eq
    assert p.triggered_abilities[0].effect == bridged_mt


# ---------------------------------------------------------------------------
# (3) Rust synthetic-carrier sanity.
# ---------------------------------------------------------------------------


@_rust_skip
def test_rust_parser_accepts_killers_mask_synthetic_dict():
    """Lockstep pin: Rust's ``parse_effect`` arm accepts both bridge
    dict shapes on a Killer's-Mask-shape Artifact Equipment carrier
    with synthetic {2} AA cost."""
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Killer's Mask (synthetic carrier)",
            "card_types": ["Artifact"],
            "subtypes": ["Equipment"],
            "mana_cost": {"generic": 2, "B": 1},
            "effects": [],
            "activated_abilities": [
                {
                    "cost": {"mana": {"generic": 2}},
                    "effect": {
                        "kind": "equip_to_target_creature_you_control",
                    },
                    "is_mana_ability": False,
                },
            ],
            "triggered_abilities": [
                {
                    "event": "enters",
                    "predicate": {"kind": "source_is_self"},
                    "effect": {
                        "kind": "manifest_dread_then_attach_self",
                    },
                },
            ],
        }
    )
    assert isinstance(pid, int)


# ---------------------------------------------------------------------------
# (4) GENUINE real-EoE cross-engine byte-equal probe.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_killers_mask_etb_manifest_dread_attach_parity():
    """**GENUINE real-EoE cross-engine probe — Killer's Mask ETB
    TriggeredAbility → ManifestDreadThenAttachSelf() resolve.
    PROBED-tier flip (covered_by_construction → PROBED).**

    Drives the **ACTUAL parsed Killer's Mask printing** through both
    Effect resolve paths.  Mirrors the EEEE-idiom (parse + bridge
    round-trip + Python-side resolve, no cross-engine compare_fields).

    **Per-slug attribution distinction** vs the sibling Duskmourn-
    Equipment probes (Conductive Machete, Cursed Windbreaker):
      * **Mana cost** {2}{B} (black; the only colored-mana sibling
        in the cycle).
      * **Equip cost** {2} (cheapest of the three).

    Effect-half shapes are bit-identical to the siblings — both arms
    are unit-variant on the Python side.  Per the cathedral-of-war-
    style same-Effect-class-different-printing-slug precedent, the
    Killer's Mask slug earns its own PROBED-tier slot.

    **Bridge arms exercised:** ``equip_to_target_creature_you_control``
    + ``manifest_dread_then_attach_self``.

    **Setup (Python-side):**
      * p0 has Killer's Mask on the battlefield.
      * p0's library has 2 filler cards (one manifested, one to
        graveyard per CR 701.55).
      * Pre-resolve: source.attached_to is None.

    **Observables asserted:**
      * Bridge round-trips byte-equal both effects.
      * Post-resolve (ETB): one new face-down creature; Killer's
        Mask attaches to it; library now empty; graveyard has the
        milled card.
      * Post-resolve (Equip AA on a new target): re-attach updates
        attached_to.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _ta_dict_to_python_effect,
    )
    from mtg_bot.game import Zone
    from mtg_bot.cards.base import CardPrinting, ManaCost

    real = _PRINTINGS.get("Killer's Mask")
    if real is None:
        pytest.skip("Killer's Mask absent from active CardSource")
    assert "Artifact" in real.card_types
    assert "Equipment" in real.subtypes
    aa = real.activated_abilities[0]
    ta = real.triggered_abilities[0]
    assert isinstance(aa.effect, EquipToTargetCreatureYouControl)
    assert isinstance(ta.effect, ManifestDreadThenAttachSelf)

    bridged_eq = _ta_dict_to_python_effect(
        {"kind": "equip_to_target_creature_you_control"}
    )
    bridged_mt = _ta_dict_to_python_effect(
        {"kind": "manifest_dread_then_attach_self"}
    )
    assert aa.effect == bridged_eq
    assert ta.effect == bridged_mt

    # Distinctness regression guard — Killer's Mask differs from the
    # Conductive Machete / Cursed Windbreaker siblings ONLY on the
    # cost-side fields (printing mana cost + Equip-AA mana cost).
    # The Effect-half shapes are byte-identical across all three.
    assert real.mana_cost.colored == (("B", 1),), (
        "Killer's Mask must carry {B} in its printed mana cost — "
        "distinct from Conductive Machete (colorless) / Cursed "
        "Windbreaker ({U})"
    )
    assert aa.cost.mana.generic == 2, (
        "Killer's Mask Equip cost must be {2} — distinct from "
        "Conductive Machete's {4} / Cursed Windbreaker's {3}"
    )

    # Python-side resolve smoke for the ETB TA.
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py_state = build_python_state(spec)

    py_source = py_state.new_object(
        real, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_source.tapped = False
    py_source.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_source)

    filler_printing = CardPrinting(
        name="Killer's Mask Manifest Filler",
        mana_cost_str="",
        mana_cost=ManaCost(generic=0, colored=()),
        type_line="Creature — Bear",
        supertypes=(),
        card_types=("Creature",),
        subtypes=("Bear",),
        power=2,
        toughness=2,
        produces=frozenset(),
        triggered_abilities=(),
    )
    for _ in range(2):
        card = py_state.new_object(
            filler_printing, owner_id=0, zone=Zone.LIBRARY,
        )
        py_state.players[0].library.append(card)
    pre_bf_ids = {o.id for o in py_state.battlefield}
    assert py_source.attached_to is None

    py_state.resolving_source = py_source
    try:
        ta.effect.resolve(py_state, py_source.controller_id)
    finally:
        py_state.resolving_source = None

    post_bf_ids = {o.id for o in py_state.battlefield}
    new_ids = post_bf_ids - pre_bf_ids
    assert len(new_ids) == 1
    new_id = next(iter(new_ids))
    new_obj = next(o for o in py_state.battlefield if o.id == new_id)
    assert new_obj.face_down is True
    assert new_obj.controller_id == 0
    assert py_source.attached_to == new_id
    assert len(py_state.players[0].library) == 0
    assert len(py_state.players[0].graveyard) == 1

    # Equip AA re-attach.
    new_target_printing = CardPrinting(
        name="Killer's Mask Equip Bait",
        mana_cost_str="",
        mana_cost=ManaCost(generic=2, colored=()),
        type_line="Creature — Bear",
        supertypes=(),
        card_types=("Creature",),
        subtypes=("Bear",),
        power=2,
        toughness=2,
        produces=frozenset(),
        triggered_abilities=(),
    )
    py_target = py_state.new_object(
        new_target_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_target.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_target)

    py_state.resolving_source = py_source
    try:
        aa.effect.resolve(
            py_state,
            py_source.controller_id,
            (("creature", py_target.id),),
        )
    finally:
        py_state.resolving_source = None

    assert py_source.attached_to == py_target.id
