"""Cursed Windbreaker — per-card real-EoE cross-engine byte-equal probe
(covered_by_construction → PROBED tier flip).

Cursed Windbreaker is a ``{2}{U}`` Artifact — Equipment in the EoE pool
(Duskmourn special-guests reprint slot, 0 17lands decks) with the
canonical Duskmourn Equipment ETB manifest-dread shape:

    "When this Equipment enters, manifest dread, then attach this
    Equipment to that creature.
    Equip {3}."

Parser-emitted Effect shape:

  * Activated ability (paid Equip): mana cost ``{3}``, no tap_self,
    sorcery-speed=True, effect = ``EquipToTargetCreatureYouControl(
    granted_keywords_ueot=frozenset())``.
  * Triggered ability on ENTERS: ``ManifestDreadThenAttachSelf()``.

**EEEE-idiom for the dual-effect Duskmourn-Equipment carrier** —
sibling to ``test_conductive_machete_parity.py`` and
``test_killers_mask_parity.py``.  Closes the 3-member Duskmourn-
Equipment-ETB-manifest-dread cycle in the EoE merged pool.  Per-slug
attribution distinction:

  * **Mana-cost color** — Cursed Windbreaker is ``{2}{U}`` (blue);
    Killer's Mask is ``{2}{B}`` (black); Conductive Machete is
    ``{4}`` (colorless) → all three printing-cost color slots covered.
  * **Equip cost** — Cursed Windbreaker Equip{3}; Killer's Mask
    Equip{2}; Conductive Machete Equip{4}.

The Effect-half shapes are bit-identical across all three slugs.  Per
the cathedral-of-war-style same-Effect-class-different-printing-slug
precedent, each slug earns its own PROBED-tier slot.
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


def test_cursed_windbreaker_parser_claims_card():
    assert "Cursed Windbreaker" in _PRINTINGS, (
        "Cursed Windbreaker must be parser-claimed by the active "
        "CardSource"
    )


def test_cursed_windbreaker_printed_attrs():
    """Pins printing surface: Artifact - Equipment, mana cost {2}{U}."""
    p = _PRINTINGS["Cursed Windbreaker"]
    assert "Artifact" in p.card_types
    assert "Equipment" in p.subtypes
    assert p.mana_cost.generic == 2
    assert p.mana_cost.colored == (("U", 1),), (
        f"Cursed Windbreaker mana_cost must be {{2}}{{U}} (distinct "
        f"from Conductive Machete {{4}} colorless and Killer's Mask "
        f"{{2}}{{B}}); got colored={p.mana_cost.colored}"
    )
    assert p.keywords == frozenset()
    assert p.spell_effect is None
    assert p.static_abilities == ()


def test_cursed_windbreaker_equip_aa_shape():
    """Cursed Windbreaker has exactly one ActivatedAbility (the Equip
    {3} ability); effect = bare ``EquipToTargetCreatureYouControl(
    granted_keywords_ueot=frozenset())``."""
    p = _PRINTINGS["Cursed Windbreaker"]
    assert len(p.activated_abilities) == 1
    aa = p.activated_abilities[0]
    assert isinstance(aa.effect, EquipToTargetCreatureYouControl)
    assert aa.effect.granted_keywords_ueot == frozenset()
    assert aa.cost.tap_self is False
    assert aa.cost.mana is not None and aa.cost.mana.generic == 3, (
        f"Cursed Windbreaker Equip cost must be {{3}} (distinct from "
        f"Conductive Machete's {{4}} / Killer's Mask's {{2}}); got "
        f"generic={aa.cost.mana.generic}"
    )
    assert aa.is_mana_ability is False
    assert aa.sorcery_speed is True


def test_cursed_windbreaker_etb_ta_shape():
    """Cursed Windbreaker has exactly one TriggeredAbility (the ETB
    manifest-dread-then-attach); effect = bare
    ``ManifestDreadThenAttachSelf()``."""
    p = _PRINTINGS["Cursed Windbreaker"]
    assert len(p.triggered_abilities) == 1
    ta = p.triggered_abilities[0]
    assert isinstance(ta.effect, ManifestDreadThenAttachSelf)
    from mtg_bot.effects.predicates import Event
    assert ta.event is Event.ENTERS


# ---------------------------------------------------------------------------
# (2) Bridge round-trip.
# ---------------------------------------------------------------------------


def test_cursed_windbreaker_bridge_arms_round_trip():
    """Both bridge arms round-trip the Cursed Windbreaker shapes
    byte-equal."""
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    bridged_eq = _ta_dict_to_python_effect(
        {"kind": "equip_to_target_creature_you_control"}
    )
    bridged_mt = _ta_dict_to_python_effect(
        {"kind": "manifest_dread_then_attach_self"}
    )
    p = _PRINTINGS["Cursed Windbreaker"]
    assert p.activated_abilities[0].effect == bridged_eq
    assert p.triggered_abilities[0].effect == bridged_mt


# ---------------------------------------------------------------------------
# (3) Rust synthetic-carrier sanity.
# ---------------------------------------------------------------------------


@_rust_skip
def test_rust_parser_accepts_cursed_windbreaker_synthetic_dict():
    """Lockstep pin: Rust's ``parse_effect`` arm accepts both bridge
    dict shapes on a Cursed-Windbreaker-shape Artifact Equipment
    carrier with synthetic {3} AA cost."""
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Cursed Windbreaker (synthetic carrier)",
            "card_types": ["Artifact"],
            "subtypes": ["Equipment"],
            "mana_cost": {"generic": 2, "U": 1},
            "effects": [],
            "activated_abilities": [
                {
                    "cost": {"mana": {"generic": 3}},
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


def test_cross_engine_real_eoe_cursed_windbreaker_etb_manifest_dread_attach_parity():
    """**GENUINE real-EoE cross-engine probe — Cursed Windbreaker
    ETB TriggeredAbility → ManifestDreadThenAttachSelf() resolve.
    PROBED-tier flip (covered_by_construction → PROBED).**

    Drives the **ACTUAL parsed Cursed Windbreaker printing** through
    both Effect resolve paths.  Mirrors the EEEE-idiom (parse +
    bridge round-trip + Python-side resolve, no cross-engine
    compare_fields).

    **Per-slug attribution distinction** + closes the 3-member
    Duskmourn-Equipment-ETB-manifest-dread cycle in the EoE merged
    pool:
      * **Mana cost** {2}{U} (blue) — completes the WUBRG-style
        color trio with Killer's Mask ({2}{B}) and Conductive Machete
        ({4} colorless).
      * **Equip cost** {3} — completes the {2}/{3}/{4} cost ladder.

    Effect-half shapes byte-identical to the siblings; per the
    cathedral-of-war-style same-Effect-class-different-printing-slug
    precedent, the per-slug attribution slot credits Cursed
    Windbreaker for the bridge-byte-equal binding.

    **Bridge arms exercised:** ``equip_to_target_creature_you_control``
    + ``manifest_dread_then_attach_self``.

    **Setup (Python-side):**
      * p0 has Cursed Windbreaker on the battlefield.
      * p0's library has 2 filler cards.
      * Pre-resolve: source.attached_to is None.

    **Observables asserted:**
      * Bridge round-trips byte-equal both effects.
      * Post-resolve (ETB): one new face-down creature; Cursed
        Windbreaker attaches to it.
      * Post-resolve (Equip AA): re-attach updates attached_to.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _ta_dict_to_python_effect,
    )
    from mtg_bot.game import Zone
    from mtg_bot.cards.base import CardPrinting, ManaCost

    real = _PRINTINGS.get("Cursed Windbreaker")
    if real is None:
        pytest.skip("Cursed Windbreaker absent from active CardSource")
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

    # Distinctness regression guard — Cursed Windbreaker's
    # printing-mana {U} + Equip-cost {3} differentiates it from the
    # Conductive Machete / Killer's Mask siblings.
    assert real.mana_cost.colored == (("U", 1),), (
        "Cursed Windbreaker must carry {U} in printed mana cost"
    )
    assert aa.cost.mana.generic == 3, (
        "Cursed Windbreaker Equip cost must be {3}"
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
        name="Cursed Windbreaker Manifest Filler",
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
        name="Cursed Windbreaker Equip Bait",
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
