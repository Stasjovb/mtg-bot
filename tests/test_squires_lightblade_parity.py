"""Squire's Lightblade — per-card real-EoE cross-engine byte-equal
probe (covered_by_construction → PROBED tier flip).

Squire's Lightblade is a ``{W}`` Artifact — Equipment in the EoE pool
with an ETB attach trigger and a paid Equip activated ability:

    "Flash.
     When this Equipment enters, attach it to target creature you
     control. That creature gains first strike until end of turn.
     Equip {3}."

The load-bearing parity-relevant ability for this probe is the
**activated Equip ability** (AA[0]):

    "{3}: attach this Equipment to target creature you control."

Parser-emitted Effect shape for the Equip AA:

    ``EquipToTargetCreatureYouControl(granted_keywords_ueot=frozenset())``

attached to an ActivatedAbility whose ``cost`` carries no tap_self
(Equip costs use the printed mana cost only; the source Equipment
does NOT tap to equip per CR 702.6c) + mana cost ``{3}``.  The bridge
arm ``equip_to_target_creature_you_control`` (cross_engine.py:4581)
is a unit variant — no fields — and round-trips ``{"kind":
"equip_to_target_creature_you_control"}`` byte-equal to Python's
default-fielded
``EquipToTargetCreatureYouControl(granted_keywords_ueot=frozenset())``.

This module is the **load-bearing PROBED-tier flip evidence** for
Squire's Lightblade and opens a **NEW shape family** for the per-slug
attribution lane: **activated-ability + EquipToTargetCreatureYouControl
on artifact-equipment carrier**.  The ETB-attach sibling arm
(``attach_to_target_creature_you_control``) is exercised via the
TriggeredAbility on the ETB event — distinct from the paid Equip AA;
both arms ship in Rust as separate variants (sister bridge arms per
the round-19 audit-refresh).  THIS probe pins the **Equip AA** half
specifically.

**FFFF EEEE-idiom for the ActivatedAbility carrier.**  Same lane
discipline as batches 1-4 (parse + bridge round-trip + Python-side
resolve, NO cross-engine ``compare_fields``).  The Python-side
resolve drives the EquipToTargetCreatureYouControl Effect directly
through its resolve path on a creature-target seat; the post-resolve
observable is "the Equipment's ``attached_to`` field stamps to the
target creature's id".

**AA-cost-substrate deferral.**  The full Equip-AA-cost-payment
trajectory (the ``{3}`` mana cost atom on the ActivationCost, the
sorcery-speed-only restriction per CR 702.6b, the targeting-step
choose-a-creature-you-control gate, the cross-engine observer parity
on the attached_to field) is the cost-substrate /
test_probe_activated_abilities_o2 family scope and stays substrate-
deferred for this lane.  Per-slug attribution credits the slug based
on the Effect+bridge byte-equality alone.

**NEW shape coverage:** the FIRST PROBE_MODULES-credited probe
binding the Squire's Lightblade slug to its parsed
``ActivatedAbility(EquipToTargetCreatureYouControl())`` shape; the
FIRST PROBED-tier slot for the EquipToTargetCreatureYouControl
Effect class on a real-EoE equipment AA carrier (the round-19 bridge
arm landed end-to-end without a slug-attribution probe).

**ETB-attach TriggeredAbility half-coverage scope.**  Squire's
Lightblade's TriggeredAbility on ENTERS emits ``Attach
ToTargetCreatureYouControl(granted_keywords_ueot=frozenset({'first
strike'}))`` — the ETB-attach + UEOT-keyword-grant combo.  The
``granted_keywords_ueot`` rider would not round-trip cleanly via the
unit-variant bridge arm (``attach_to_target_creature_you_control``
is unit-variant; the keyword rider is structurally narrower than
what the bridge expresses today).  Per the IIII / HHHH "covered
carrier with a non-bridge-clean rider" implicit drop precedent + the
batch-2 narrow-pin half-coverage precedent, the Equip AA alone
carries the load-bearing slug-attribution flip.
"""

from __future__ import annotations

import importlib.util

import pytest

from mtg_bot.cards.source import get_active_source
from mtg_bot.effects.generic.attach import (
    EquipToTargetCreatureYouControl,
)


_PRINTINGS = get_active_source().get_printings()


_rust_skip = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


# Zone constants (mirror Rust's u8 zone IDs).
ZONE_BATTLEFIELD = 2


# ---------------------------------------------------------------------------
# (1) Parser SoT — Squire's Lightblade is parser-claimed and carries
# one AA whose effect is ``EquipToTargetCreatureYouControl()``.
# ---------------------------------------------------------------------------


def test_squires_lightblade_parser_claims_card():
    assert "Squire's Lightblade" in _PRINTINGS, (
        "Squire's Lightblade must be parser-claimed by the active "
        "CardSource"
    )


def test_squires_lightblade_printed_attrs():
    """Pins the basic printing surface: Artifact, mana cost {W},
    flash keyword."""
    p = _PRINTINGS["Squire's Lightblade"]
    assert "Artifact" in p.card_types
    assert p.mana_cost.generic == 0
    assert p.mana_cost.colored == (("W", 1),)
    # Flash is documented for context — the keyword surface isn't
    # exercised by the EFFECT-half probe but pins the printing's
    # printed identity.
    assert "flash" in p.keywords


def test_squires_lightblade_equip_ability_shape():
    """Squire's Lightblade has exactly one ActivatedAbility (the Equip
    {3} ability); its effect is the bare
    ``EquipToTargetCreatureYouControl(granted_keywords_ueot=
    frozenset())`` — the canonical "Equip cost" primitive (CR 702.6,
    no UEOT keyword granted by the paid-Equip side; the first-strike
    grant rides the ETB-attach TriggeredAbility, NOT the paid Equip
    AA)."""
    p = _PRINTINGS["Squire's Lightblade"]
    assert len(p.activated_abilities) == 1, (
        f"Squire's Lightblade must have exactly one ActivatedAbility "
        f"(the Equip {{3}} ability); got {len(p.activated_abilities)}"
    )
    aa = p.activated_abilities[0]
    assert isinstance(aa.effect, EquipToTargetCreatureYouControl), (
        f"Squire's Lightblade AA effect must be "
        f"EquipToTargetCreatureYouControl; got "
        f"{type(aa.effect).__name__}"
    )
    assert aa.effect.granted_keywords_ueot == frozenset(), (
        f"Squire's Lightblade Equip AA must NOT carry "
        f"granted_keywords_ueot (the first-strike rider is on the "
        f"ETB-attach TriggeredAbility, not the paid Equip); got "
        f"granted_keywords_ueot={aa.effect.granted_keywords_ueot!r}"
    )
    # Cost-side: {3} mana, no tap_self (Equip costs don't tap the
    # source Equipment).
    assert aa.cost.tap_self is False
    assert aa.cost.mana is not None and aa.cost.mana.generic == 3
    assert aa.is_mana_ability is False


# ---------------------------------------------------------------------------
# (2) Bridge round-trip — the equip_to_target_creature_you_control dict
# shape round-trips byte-equal to the parsed printing's emitted Effect.
# ---------------------------------------------------------------------------


def test_squires_lightblade_bridge_arm_round_trip():
    """The bridge arm ``equip_to_target_creature_you_control`` (cross_
    engine.py:4581) is a unit-variant arm (no fields) — round-trips
    ``{"kind": "equip_to_target_creature_you_control"}`` to the matching
    Python ``EquipToTargetCreatureYouControl(granted_keywords_ueot=
    frozenset())`` instance with default-empty keywords.

    Distinct from the sister ``attach_to_target_creature_you_control``
    bridge arm (ETB-shape) — both arms exist in Rust as separate Effect
    variants (separate parser arms + separate to_dict emission paths)
    per the round-19 audit-refresh; the Equip AA emits the
    ``equip_to_*`` dict, while the ETB-attach TriggeredAbility emits
    the ``attach_to_*`` dict."""
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    bridged = _ta_dict_to_python_effect(
        {"kind": "equip_to_target_creature_you_control"}
    )
    assert isinstance(bridged, EquipToTargetCreatureYouControl)
    assert bridged.granted_keywords_ueot == frozenset()

    # Effect-level byte-equality between the parsed real-EoE printing's
    # emitted EquipToTargetCreatureYouControl Effect and the bridged
    # Effect — the structural contract for the PROBED tier.
    p = _PRINTINGS["Squire's Lightblade"]
    aa = p.activated_abilities[0]
    assert aa.effect == bridged, (
        f"Squire's Lightblade AA Effect must be byte-equal to the "
        f"bridged Effect (EquipToTargetCreatureYouControl() structural "
        f"contract for the PROBED tier); got parsed={aa.effect!r}, "
        f"bridged={bridged!r}"
    )


# ---------------------------------------------------------------------------
# (3) Rust synthetic-carrier sanity — the Rust parser accepts the
# bridged equip_to_target_creature_you_control dict shape on a
# Squire's-Lightblade-shape Artifact Equipment carrier with a
# synthetic {3} AA cost.
# ---------------------------------------------------------------------------


@_rust_skip
def test_rust_parser_accepts_squires_lightblade_equip_synthetic_dict():
    """Lockstep pin: Rust's ``parse_effect`` arm accepts the
    ``{"kind": "equip_to_target_creature_you_control"}`` dict shape on
    a Squire's-Lightblade-shape Artifact Equipment carrier with a
    synthetic {3} AA cost.  Unit-variant — no fields beyond ``kind`` —
    so the closed-vocab dispatch is bare."""
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Squire's Lightblade (synthetic carrier)",
            "card_types": ["Artifact"],
            "mana_cost": {"generic": 0, "W": 1},
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
        }
    )
    assert isinstance(pid, int)


# ---------------------------------------------------------------------------
# (4) GENUINE real-EoE cross-engine byte-equal probe — drives the
# ACTUAL parsed Squire's Lightblade printing on Python-side resolve
# for the EquipToTargetCreatureYouControl effect.  Mirrors the FFFF
# EEEE-idiom (parse + bridge round-trip + Python-side resolve, NO
# cross-engine compare_fields).
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_squires_lightblade_equip_activation_parity():
    """**GENUINE real-EoE cross-engine probe — Squire's Lightblade
    Equip AA → EquipToTargetCreatureYouControl(). PROBED-tier flip
    (covered_by_construction → PROBED).**

    Drives the **ACTUAL parsed Squire's Lightblade printing** on the
    Python side through the EquipToTargetCreatureYouControl effect's
    resolve path with a creature-target seat.  Mirrors the FFFF
    EEEE-idiom (parse + bridge round-trip + Python-side resolve, no
    cross-engine ``compare_fields``); same lane discipline as batches
    1-4.

    **NEW shape coverage:** the FIRST PROBE_MODULES-credited probe
    binding the Squire's Lightblade slug to the AA +
    EquipToTargetCreatureYouControl() Effect+bridge round-trip on the
    REAL parsed EoE printing.  Opens the
    **activated-ability + EquipToTargetCreatureYouControl on artifact-
    equipment carrier** shape family (distinct from the sister ETB-
    attach TriggeredAbility variant which emits the round-trip-
    incompatible ``granted_keywords_ueot`` rider).

    **Bridge arm exercised:**
      * ``equip_to_target_creature_you_control`` (cross_engine.py:4581;
        unit-variant — no fields).

    **AA-cost-substrate deferral.**  The full Equip-AA-cost-payment
    trajectory (the ``{3}`` mana cost atom on the ActivationCost, the
    sorcery-speed-only restriction per CR 702.6b, the targeting gate
    + cross-engine observer parity on the attached_to field) is the
    cost-substrate / test_probe_activated_abilities_o2 family scope
    and stays substrate-deferred for this lane.

    **Setup (Python-side):**
      * p0 has Squire's Lightblade on the battlefield (the AA source
        Equipment).
      * p0 has a creature on the battlefield to be equipped (the
        target seat).
      * Pre-resolve: source.attached_to is None.

    **Observables asserted:**
      * Bridge round-trip:
        ``{"kind": "equip_to_target_creature_you_control"}``
        translates to ``EquipToTargetCreatureYouControl(granted_
        keywords_ueot=frozenset())``.
      * The carrier's AA emits the same Effect.
      * Effect-level byte-equality between the parsed real-EoE
        emission and the bridged Effect.
      * Post-resolve: the source Equipment's attached_to stamps to
        the target creature's id.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _ta_dict_to_python_effect,
    )
    from mtg_bot.game import Zone

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Squire's Lightblade printing.
    # ------------------------------------------------------------------
    real = _PRINTINGS.get("Squire's Lightblade")
    if real is None:
        pytest.skip(
            "Squire's Lightblade absent from active CardSource"
        )
    assert "Artifact" in real.card_types
    aa = real.activated_abilities[0]
    assert isinstance(aa.effect, EquipToTargetCreatureYouControl)
    assert aa.effect.granted_keywords_ueot == frozenset()

    # ------------------------------------------------------------------
    # 2. Bridge round-trip: Rust kind dict -> Python Effect.
    # ------------------------------------------------------------------
    bridged = _ta_dict_to_python_effect(
        {"kind": "equip_to_target_creature_you_control"}
    )
    assert isinstance(bridged, EquipToTargetCreatureYouControl)
    assert aa.effect == bridged, (
        f"Squire's Lightblade AA Effect must be byte-equal to "
        f"bridged; got parsed={aa.effect!r}, bridged={bridged!r}"
    )

    # ------------------------------------------------------------------
    # 3. Distinctness regression guard.
    # ------------------------------------------------------------------
    # EquipToTargetCreatureYouControl with empty granted_keywords_ueot
    # is the bare paid-Equip-cost primitive.  Distinct from the
    # sibling ETB-attach trigger's
    # AttachToTargetCreatureYouControl(granted_keywords_ueot=
    # frozenset({'first strike'})) which carries the UEOT keyword rider
    # — the bridge arm for the activated Equip half is unit-variant
    # only; the ETB-attach + keyword rider half is implicit-drop here.
    assert bridged.granted_keywords_ueot == frozenset(), (
        "Bridged EquipToTargetCreatureYouControl must NOT carry a "
        "granted_keywords_ueot rider — that's the ETB-attach trigger's "
        "shape, not the paid-Equip AA's shape"
    )

    # ------------------------------------------------------------------
    # 4. Python-side resolve smoke — drive the parsed effect through
    #    its actual resolve path.  Source equipment attaches to a
    #    creature target.
    # ------------------------------------------------------------------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py_state = build_python_state(spec)

    # Seat the GENUINE parsed Squire's Lightblade on p0's bf.
    py_source = py_state.new_object(
        real, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_source.tapped = False
    py_source.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_source)

    # Seat a SYNTHETIC vanilla creature target on p0's bf (per the
    # Cosmogrand Zenith precedent — bypasses the live ``_PRINTINGS``
    # binding so the credit-walk doesn't transitively flip an
    # otherwise-covered_by_construction card).  The target's identity
    # doesn't matter for the Equip-attach observable, only that it's
    # a creature p0 controls.
    from mtg_bot.cards.base import CardPrinting, ManaCost
    vanilla_creature_target = CardPrinting(
        name="Squire's Lightblade Equip Bait",
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
        vanilla_creature_target, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_target.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_target)

    # Pre-resolve sanity: source is not yet attached.
    assert py_source.attached_to is None, (
        "Pre-resolve: source Equipment's attached_to must be None"
    )

    # The Equip Effect requires resolving_source pointer + a
    # ("creature", target_id) target tuple, per the
    # EquipToTargetCreatureYouControl.resolve contract (inherited
    # from AttachToTargetCreatureYouControl).
    py_state.resolving_source = py_source
    try:
        aa.effect.resolve(
            py_state,
            py_source.controller_id,
            (("creature", py_target.id),),
        )
    finally:
        py_state.resolving_source = None

    # Post-resolve: source.attached_to stamps to target.id.
    assert py_source.attached_to == py_target.id, (
        f"Post-resolve: source Equipment's attached_to must stamp to "
        f"target.id={py_target.id}; got attached_to="
        f"{py_source.attached_to!r}"
    )
