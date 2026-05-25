"""Conductive Machete — per-card real-EoE cross-engine byte-equal probe
(covered_by_construction → PROBED tier flip).

Conductive Machete is a ``{4}`` Artifact — Equipment in the EoE pool
(Duskmourn special-guests reprint slot, 0 17lands decks) with the
canonical Duskmourn Equipment ETB manifest-dread shape:

    "When this Equipment enters, manifest dread, then attach this
    Equipment to that creature.
    Equip {4}."

Parser-emitted Effect shape:

  * Activated ability (paid Equip): mana cost ``{4}``, no tap_self,
    sorcery-speed=True, effect = ``EquipToTargetCreatureYouControl(
    granted_keywords_ueot=frozenset())`` — the bare bridge-clean
    Equip primitive (sister of Squire's Lightblade's Equip AA).
  * Triggered ability on ENTERS: ``ManifestDreadThenAttachSelf()`` —
    the bare-fielded Duskmourn-Equipment-ETB primitive.

**EEEE-idiom for the dual-effect Duskmourn-Equipment carrier.**
Templates off ``test_squires_lightblade_parity.py`` (the FIRST
PROBE_MODULES-credited EquipToTargetCreatureYouControl PROBED-tier
binding) at the Equip-AA half, with an ADDED ETB-manifest-dread half
covering the ``ManifestDreadThenAttachSelf`` Effect class.  Both halves
round-trip byte-equal through their bridge arms:

  * ``equip_to_target_creature_you_control`` (unit variant — no fields)
  * ``manifest_dread_then_attach_self`` (unit variant on the Python
    side; ``count`` field on Rust defaults to 1 and matches Python's
    hard-coded count=1 inside ManifestDread)

Per the cathedral-of-war-style same-Effect-class-different-printing-
slug precedent, the Conductive Machete slug earns its own PROBED-tier
slot distinct from Squire's Lightblade (the Equip-AA half) — the
distinction is the **ETB-attach via ManifestDreadThenAttachSelf**
sub-shape (Squire's Lightblade's ETB-attach trigger emits the sibling
``AttachToTargetCreatureYouControl(granted_keywords_ueot=frozenset(
{'first strike'}))`` with a UEOT keyword rider that does NOT round-
trip clean; Conductive Machete's ETB emits the bare-fielded
``ManifestDreadThenAttachSelf()`` instead).

**Duskmourn-Equipment-ETB cycle members in covered_by_construction**
sharing this exact two-effect shape — Conductive Machete + Killer's
Mask + Cursed Windbreaker (all 0 17lands decks).  Sibling probes in
this batch cover Killer's Mask and Cursed Windbreaker via per-slug
attribution slots; Conductive Machete is the FIRST PROBE_MODULES-
credited real-EoE probe binding ``ManifestDreadThenAttachSelf`` to a
slug.
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


# Zone constants (mirror Rust's u8 zone IDs).
ZONE_BATTLEFIELD = 2


# ---------------------------------------------------------------------------
# (1) Parser SoT — Conductive Machete is parser-claimed; carries one
# Equip AA + one ETB TA.
# ---------------------------------------------------------------------------


def test_conductive_machete_parser_claims_card():
    assert "Conductive Machete" in _PRINTINGS, (
        "Conductive Machete must be parser-claimed by the active "
        "CardSource"
    )


def test_conductive_machete_printed_attrs():
    """Pins the basic printing surface: Artifact - Equipment, generic
    mana cost {4}, no colored mana."""
    p = _PRINTINGS["Conductive Machete"]
    assert "Artifact" in p.card_types
    assert "Equipment" in p.subtypes
    assert p.mana_cost.generic == 4
    assert p.mana_cost.colored == ()
    # Documented for context — no keywords; no spell_effect (it's a
    # permanent); no static abilities.
    assert p.keywords == frozenset()
    assert p.spell_effect is None
    assert p.static_abilities == ()


def test_conductive_machete_equip_aa_shape():
    """Conductive Machete has exactly one ActivatedAbility (the Equip
    {4} ability); its effect is the bare
    ``EquipToTargetCreatureYouControl(granted_keywords_ueot=frozenset())``
    — the canonical "Equip cost" primitive (CR 702.6, no UEOT keyword
    granted by the paid-Equip side; the manifest-dread-then-attach
    rides the ETB TriggeredAbility, NOT the paid Equip AA)."""
    p = _PRINTINGS["Conductive Machete"]
    assert len(p.activated_abilities) == 1, (
        f"Conductive Machete must have exactly one ActivatedAbility "
        f"(the Equip {{4}} ability); got {len(p.activated_abilities)}"
    )
    aa = p.activated_abilities[0]
    assert isinstance(aa.effect, EquipToTargetCreatureYouControl)
    assert aa.effect.granted_keywords_ueot == frozenset()
    # Cost-side: {4} mana, no tap_self (Equip costs don't tap the
    # source Equipment per CR 702.6c).
    assert aa.cost.tap_self is False
    assert aa.cost.mana is not None and aa.cost.mana.generic == 4
    assert aa.is_mana_ability is False
    assert aa.sorcery_speed is True


def test_conductive_machete_etb_ta_shape():
    """Conductive Machete has exactly one TriggeredAbility (the ETB
    manifest-dread-then-attach); its effect is the bare-fielded
    ``ManifestDreadThenAttachSelf()`` primitive (unit variant — no
    fields on the Python class today; Python hardcodes count=1
    internally via ManifestDread(count=1).resolve)."""
    p = _PRINTINGS["Conductive Machete"]
    assert len(p.triggered_abilities) == 1, (
        f"Conductive Machete must have exactly one TriggeredAbility; "
        f"got {len(p.triggered_abilities)}"
    )
    ta = p.triggered_abilities[0]
    assert isinstance(ta.effect, ManifestDreadThenAttachSelf), (
        f"Conductive Machete TA effect must be "
        f"ManifestDreadThenAttachSelf; got {type(ta.effect).__name__}"
    )
    # Trigger event: ENTERS (the ETB-self trigger).
    from mtg_bot.effects.predicates import Event
    assert ta.event is Event.ENTERS


# ---------------------------------------------------------------------------
# (2) Bridge round-trip — both bridge arms round-trip byte-equal to
# the parsed printing's emitted Effects.
# ---------------------------------------------------------------------------


def test_conductive_machete_bridge_arms_round_trip():
    """Both bridge arms round-trip the Conductive Machete shapes
    byte-equal:

      * ``equip_to_target_creature_you_control`` (unit variant — no
        fields) → ``EquipToTargetCreatureYouControl(granted_keywords_
        ueot=frozenset())`` byte-equal to the parsed Equip AA effect.
      * ``manifest_dread_then_attach_self`` (Python class is unit-
        variant; Rust's ``count`` field defaults to 1 and is silently
        consumed by Python's hardcoded-1 internal call) →
        ``ManifestDreadThenAttachSelf()`` byte-equal to the parsed
        ETB TA effect.

    Effect-level byte-equality between the parsed real-EoE printing's
    emitted Effects and the bridged Effects — the structural contract
    for the PROBED tier."""
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    bridged_eq = _ta_dict_to_python_effect(
        {"kind": "equip_to_target_creature_you_control"}
    )
    bridged_mt = _ta_dict_to_python_effect(
        {"kind": "manifest_dread_then_attach_self"}
    )
    assert isinstance(bridged_eq, EquipToTargetCreatureYouControl)
    assert isinstance(bridged_mt, ManifestDreadThenAttachSelf)
    assert bridged_eq.granted_keywords_ueot == frozenset()

    p = _PRINTINGS["Conductive Machete"]
    aa = p.activated_abilities[0]
    ta = p.triggered_abilities[0]
    assert aa.effect == bridged_eq, (
        f"Conductive Machete AA Effect must be byte-equal to bridged "
        f"EquipToTargetCreatureYouControl; got parsed={aa.effect!r}, "
        f"bridged={bridged_eq!r}"
    )
    assert ta.effect == bridged_mt, (
        f"Conductive Machete TA Effect must be byte-equal to bridged "
        f"ManifestDreadThenAttachSelf; got parsed={ta.effect!r}, "
        f"bridged={bridged_mt!r}"
    )


# ---------------------------------------------------------------------------
# (3) Rust synthetic-carrier sanity — Rust's parse_effect arm accepts
# both bridge dict shapes on a Conductive-Machete-shape Artifact
# Equipment carrier.
# ---------------------------------------------------------------------------


@_rust_skip
def test_rust_parser_accepts_conductive_machete_synthetic_dict():
    """Lockstep pin: Rust's ``parse_effect`` arm accepts both the
    ``equip_to_target_creature_you_control`` dict shape (paid Equip
    AA) AND the ``manifest_dread_then_attach_self`` dict shape (ETB
    TA) on a Conductive-Machete-shape Artifact Equipment carrier with
    a synthetic {4} AA cost."""
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Conductive Machete (synthetic carrier)",
            "card_types": ["Artifact"],
            "subtypes": ["Equipment"],
            "mana_cost": {"generic": 4},
            "effects": [],
            "activated_abilities": [
                {
                    "cost": {"mana": {"generic": 4}},
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
# (4) GENUINE real-EoE cross-engine byte-equal probe — drives the
# ACTUAL parsed Conductive Machete printing on Python-side resolve
# for BOTH the EquipToTargetCreatureYouControl effect (paid Equip AA)
# AND the ManifestDreadThenAttachSelf effect (ETB TA).
# Mirrors the EEEE-idiom (parse + bridge round-trip + Python-side
# resolve, NO cross-engine compare_fields).
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_conductive_machete_etb_manifest_dread_attach_parity():
    """**GENUINE real-EoE cross-engine probe — Conductive Machete ETB
    TriggeredAbility → ManifestDreadThenAttachSelf() resolve.  PROBED-
    tier flip (covered_by_construction → PROBED).**

    Drives the **ACTUAL parsed Conductive Machete printing** on the
    Python side through both Effect resolve paths.  Mirrors the
    EEEE-idiom (parse + bridge round-trip + Python-side resolve, no
    cross-engine ``compare_fields``); same lane discipline as batches
    1-11.

    **NEW shape coverage:** the FIRST PROBE_MODULES-credited probe
    binding the Conductive Machete slug AND the
    ``ManifestDreadThenAttachSelf`` Effect class to a real-EoE
    printing.  Distinct from Squire's Lightblade (the Equip-AA half
    sibling) on the **ETB-attach mechanism**: Squire's Lightblade's
    ETB-attach trigger emits ``AttachToTargetCreatureYouControl(
    granted_keywords_ueot=frozenset({'first strike'}))`` with a UEOT
    keyword rider that does NOT round-trip clean through the unit-
    variant ``attach_to_target_creature_you_control`` bridge arm,
    while Conductive Machete's ETB-attach emits the bare-fielded
    ``ManifestDreadThenAttachSelf()`` which DOES round-trip clean
    through ``manifest_dread_then_attach_self``.

    **Bridge arms exercised:**
      * ``equip_to_target_creature_you_control`` (paid Equip AA,
        unit variant — no fields).
      * ``manifest_dread_then_attach_self`` (ETB TA, Python class is
        unit variant; Rust's ``count`` field defaults to 1).

    **AA-cost-substrate / TA-trigger-machinery deferral.**  The full
    Equip-AA-cost-payment trajectory ({4} mana cost atom on the
    ActivationCost, sorcery-speed restriction per CR 702.6b, cross-
    engine observer parity on the attached_to field) AND the full
    ETB-trigger-machinery trajectory (the ENTERS event firing path,
    cross-engine observer parity on the manifest-then-attach
    composition) are the cost-substrate / trigger-substrate scopes
    and stay substrate-deferred for this lane.  Per-slug attribution
    credits the slug based on the Effect+bridge byte-equality alone.

    **Setup (Python-side):**
      * p0 has Conductive Machete on the battlefield (the ETB/AA
        source; the Effect resolves on the source's controller).
      * p0's library has 2 filler cards (one will be manifested
        face-down to the bf, the other goes to graveyard per CR
        701.55 — the "look at top 2" semantics of manifest dread).
      * Pre-resolve: source.attached_to is None (the Equipment has
        not yet equipped).

    **Observables asserted:**
      * Bridge round-trips: both bridge dicts translate to byte-
        equal Effects.
      * Conductive Machete's parsed AA + TA emit those same Effects.
      * Post-resolve (ETB TA): a new face-down 2/2 creature enters
        p0's battlefield; the Conductive Machete's ``attached_to``
        field stamps to that new permanent's id; p0's library has 0
        cards remaining (one manifested, one to graveyard); p0's
        graveyard has the milled card.
      * Post-resolve (Equip AA on a separate target): the Equipment
        re-attaches to a new target creature (the source can be
        re-equipped per CR 702.6c — Equip can target any creature
        you control; attached_to updates).
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _ta_dict_to_python_effect,
    )
    from mtg_bot.game import Zone
    from mtg_bot.cards.base import CardPrinting, ManaCost

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Conductive Machete printing.
    # ------------------------------------------------------------------
    real = _PRINTINGS.get("Conductive Machete")
    if real is None:
        pytest.skip("Conductive Machete absent from active CardSource")
    assert "Artifact" in real.card_types
    assert "Equipment" in real.subtypes
    aa = real.activated_abilities[0]
    ta = real.triggered_abilities[0]
    assert isinstance(aa.effect, EquipToTargetCreatureYouControl)
    assert isinstance(ta.effect, ManifestDreadThenAttachSelf)

    # ------------------------------------------------------------------
    # 2. Bridge round-trip pins (both arms).
    # ------------------------------------------------------------------
    bridged_eq = _ta_dict_to_python_effect(
        {"kind": "equip_to_target_creature_you_control"}
    )
    bridged_mt = _ta_dict_to_python_effect(
        {"kind": "manifest_dread_then_attach_self"}
    )
    assert aa.effect == bridged_eq, (
        f"Conductive Machete Equip AA effect must be byte-equal to "
        f"bridged; got parsed={aa.effect!r}, bridged={bridged_eq!r}"
    )
    assert ta.effect == bridged_mt, (
        f"Conductive Machete ETB TA effect must be byte-equal to "
        f"bridged; got parsed={ta.effect!r}, bridged={bridged_mt!r}"
    )

    # ------------------------------------------------------------------
    # 3. Distinctness regression guard — Conductive Machete's ETB-
    # attach via ManifestDreadThenAttachSelf is distinct from sibling
    # ETB-attach shapes.  Squire's Lightblade emits
    # AttachToTargetCreatureYouControl(granted_keywords_ueot=
    # frozenset({'first strike'})) (UEOT keyword rider — NOT byte-
    # equal to bridge).  Other sibling Duskmourn Equipment ETB-
    # manifest-dread carriers (Killer's Mask, Cursed Windbreaker)
    # share the exact ManifestDreadThenAttachSelf() shape but are
    # parsed as separate per-printing slugs (cathedral-of-war same-
    # shape-different-slug precedent).
    # ------------------------------------------------------------------
    assert bridged_mt == ManifestDreadThenAttachSelf(), (
        "Bridged ManifestDreadThenAttachSelf must equal the bare-"
        "fielded form (Python class is unit-variant today; the "
        "count != 1 lane is Rust-parse-tolerated but Python-side "
        "structurally narrow)"
    )

    # ------------------------------------------------------------------
    # 4. Python-side resolve smoke — drive the parsed ETB TA effect
    #    through its actual resolve path.  Manifest dread looks at the
    #    top 2 of p0's library, manifests one face-down, mills the
    #    other, and attaches Conductive Machete to the manifested
    #    creature.
    # ------------------------------------------------------------------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py_state = build_python_state(spec)

    # Seat the GENUINE parsed Conductive Machete on p0's bf.
    py_source = py_state.new_object(
        real, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_source.tapped = False
    py_source.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_source)

    # Seat 2 filler library cards (manifest dread examines top 2).
    filler_printing = CardPrinting(
        name="Conductive Machete Manifest Filler",
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
    pre_lib_size = len(py_state.players[0].library)
    assert pre_lib_size == 2
    assert len(py_state.players[0].graveyard) == 0
    pre_bf_ids = {o.id for o in py_state.battlefield}

    # Pre-resolve sanity: source is not attached yet.
    assert py_source.attached_to is None

    # ManifestDreadThenAttachSelf.resolve reads
    # ``state.resolving_source`` — stamp it before driving the Effect.
    py_state.resolving_source = py_source
    try:
        ta.effect.resolve(py_state, py_source.controller_id)
    finally:
        py_state.resolving_source = None

    # Post-resolve: one new face-down creature on p0's bf; Conductive
    # Machete attached to it; library now empty; graveyard has the
    # milled card.
    post_bf_ids = {o.id for o in py_state.battlefield}
    new_ids = post_bf_ids - pre_bf_ids
    assert len(new_ids) == 1, (
        f"Manifest dread must put exactly one face-down creature on "
        f"the battlefield; got {len(new_ids)} new ids"
    )
    new_id = next(iter(new_ids))
    new_obj = next(o for o in py_state.battlefield if o.id == new_id)
    assert new_obj.face_down is True, (
        "Manifested creature must be face-down"
    )
    assert new_obj.controller_id == 0, (
        "Manifested creature must be controlled by p0 (the source's "
        "controller)"
    )
    assert py_source.attached_to == new_id, (
        f"Conductive Machete must be attached to the manifested "
        f"creature; got attached_to={py_source.attached_to!r}, "
        f"expected {new_id}"
    )
    assert len(py_state.players[0].library) == 0, (
        f"Library must be empty after manifest dread (top 2 consumed); "
        f"got {len(py_state.players[0].library)} remaining"
    )
    assert len(py_state.players[0].graveyard) == 1, (
        f"Graveyard must hold the milled card; got "
        f"{len(py_state.players[0].graveyard)}"
    )

    # ------------------------------------------------------------------
    # 5. Drive the Equip AA Effect through resolve on a SEPARATE
    #    target — re-equipping is legal per CR 702.6c, and the
    #    Equipment's attached_to field updates to the new target.
    # ------------------------------------------------------------------
    # Seat a SYNTHETIC vanilla creature target on p0's bf (per the
    # Squire's Lightblade precedent — bypasses the live ``_PRINTINGS``
    # binding so the credit-walk doesn't transitively flip an
    # otherwise-covered_by_construction card).
    new_target_printing = CardPrinting(
        name="Conductive Machete Equip Bait",
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

    # Post-resolve: source.attached_to stamps to the new target.id —
    # the Equip AA overwrites the previous ETB attach.
    assert py_source.attached_to == py_target.id, (
        f"After Equip {{4}}: source Equipment must re-attach to "
        f"target.id={py_target.id}; got attached_to="
        f"{py_source.attached_to!r}"
    )
