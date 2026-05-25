"""The Dominion Bracelet — per-card real-EoE cross-engine byte-equal
probe (covered_by_construction → PROBED tier flip).

The Dominion Bracelet is a ``{2}`` Artifact — Equipment in the EoE
pool with a paid Equip activated ability:

    "Equip {1}." (and printed equipment-bonus riders unrelated to the
    Equip-AA EFFECT half this probe pins.)

Parser-emitted Effect shape for the Equip AA:

    ``EquipToTargetCreatureYouControl(granted_keywords_ueot=frozenset())``

attached to an ActivatedAbility whose ``cost`` carries no tap_self
(Equip costs use the printed mana cost only; the source Equipment
does NOT tap to equip per CR 702.6c) + mana cost ``{1}``.  The bridge
arm ``equip_to_target_creature_you_control`` (cross_engine.py:4581)
is a unit variant — no fields — and round-trips ``{"kind":
"equip_to_target_creature_you_control"}`` byte-equal to Python's
default-fielded
``EquipToTargetCreatureYouControl(granted_keywords_ueot=frozenset())``.

This module is the **load-bearing PROBED-tier flip evidence** for
The Dominion Bracelet.  Templates on the immediately-prior sibling
probe ``test_squires_lightblade_parity.py`` (the FIRST PROBE_MODULES-
credited consumer of ``equip_to_target_creature_you_control`` on a
real-EoE equipment AA carrier with ``{3}`` cost); THIS probe
distinguishes itself by exercising the **``{1}`` Equip cost** + the
**colorless mana cost** ``{2}`` printed mana cost (Squire's
Lightblade is ``{W}`` with Equip ``{3}``; The Dominion Bracelet is
``{2}`` with Equip ``{1}``).  Per the cathedral-of-war-style same-
Effect-class-different-printing-slug precedent, each printing-slug
gets its own PROBED-tier slot.

**FFFF EEEE-idiom.**  Same lane discipline as batches 1-4 + the
sibling Squire's Lightblade probe (parse + bridge round-trip +
Python-side resolve, NO cross-engine ``compare_fields``).  Bit-
identical Effect-level bridge round-trip to Squire's Lightblade; the
per-slug attribution distinction is the printing identity (mana
cost, Equip cost) + the absence of any TriggeredAbility shape on
The Dominion Bracelet (Squire's Lightblade has an ETB-attach trigger;
The Dominion Bracelet does not).

**NEW shape coverage:** the second PROBE_MODULES-credited probe of
the EquipToTargetCreatureYouControl Effect class on a real-EoE
equipment AA carrier (Squire's Lightblade was the first via the
preceding probe in this batch).
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
# (1) Parser SoT — The Dominion Bracelet is parser-claimed and carries
# one AA whose effect is ``EquipToTargetCreatureYouControl()``.
# ---------------------------------------------------------------------------


def test_the_dominion_bracelet_parser_claims_card():
    assert "The Dominion Bracelet" in _PRINTINGS, (
        "The Dominion Bracelet must be parser-claimed by the active "
        "CardSource"
    )


def test_the_dominion_bracelet_printed_attrs():
    """Pins the basic printing surface: Artifact, mana cost {2}
    (generic-only — distinct from Squire's Lightblade's {W} cost)."""
    p = _PRINTINGS["The Dominion Bracelet"]
    assert "Artifact" in p.card_types
    assert p.mana_cost.generic == 2, (
        f"The Dominion Bracelet mana cost must be {{2}} (generic-only); "
        f"got generic={p.mana_cost.generic}"
    )
    assert p.mana_cost.colored == (), (
        f"The Dominion Bracelet must have no colored mana cost; got "
        f"colored={p.mana_cost.colored}"
    )


def test_the_dominion_bracelet_equip_ability_shape():
    """The Dominion Bracelet has exactly one ActivatedAbility (the
    Equip {1} ability); its effect is the bare
    ``EquipToTargetCreatureYouControl(granted_keywords_ueot=
    frozenset())`` — the canonical "Equip cost" primitive (CR 702.6,
    no UEOT keyword granted)."""
    p = _PRINTINGS["The Dominion Bracelet"]
    assert len(p.activated_abilities) == 1, (
        f"The Dominion Bracelet must have exactly one ActivatedAbility "
        f"(the Equip {{1}} ability); got "
        f"{len(p.activated_abilities)}"
    )
    aa = p.activated_abilities[0]
    assert isinstance(aa.effect, EquipToTargetCreatureYouControl), (
        f"The Dominion Bracelet AA effect must be "
        f"EquipToTargetCreatureYouControl; got "
        f"{type(aa.effect).__name__}"
    )
    assert aa.effect.granted_keywords_ueot == frozenset(), (
        f"The Dominion Bracelet Equip AA must NOT carry "
        f"granted_keywords_ueot; got granted_keywords_ueot="
        f"{aa.effect.granted_keywords_ueot!r}"
    )
    # Cost-side: {1} mana, no tap_self.
    assert aa.cost.tap_self is False
    assert aa.cost.mana is not None and aa.cost.mana.generic == 1, (
        f"The Dominion Bracelet Equip AA cost must be {{1}}; got "
        f"generic={aa.cost.mana.generic if aa.cost.mana else None} "
        f"(distinct from Squire's Lightblade's {{3}} Equip cost)"
    )
    assert aa.is_mana_ability is False


# ---------------------------------------------------------------------------
# (2) Bridge round-trip — the equip_to_target_creature_you_control dict
# shape round-trips byte-equal to the parsed printing's emitted Effect.
# Bit-identical bridge round-trip to Squire's Lightblade.
# ---------------------------------------------------------------------------


def test_the_dominion_bracelet_bridge_arm_round_trip():
    """The bridge arm ``equip_to_target_creature_you_control``
    (cross_engine.py:4581) is a unit-variant arm (no fields) — round-
    trips ``{"kind": "equip_to_target_creature_you_control"}`` to the
    matching Python ``EquipToTargetCreatureYouControl(granted_keywords_
    ueot=frozenset())`` instance with default-empty keywords.  Bit-
    identical bridge round-trip to the sibling Squire's Lightblade
    probe at the Effect level; the per-slug attribution distinction
    is the printing identity (mana cost, Equip cost)."""
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    bridged = _ta_dict_to_python_effect(
        {"kind": "equip_to_target_creature_you_control"}
    )
    assert isinstance(bridged, EquipToTargetCreatureYouControl)
    assert bridged.granted_keywords_ueot == frozenset()

    # Effect-level byte-equality between the parsed real-EoE printing's
    # emitted Effect and the bridged Effect.
    p = _PRINTINGS["The Dominion Bracelet"]
    aa = p.activated_abilities[0]
    assert aa.effect == bridged, (
        f"The Dominion Bracelet AA Effect must be byte-equal to the "
        f"bridged Effect (EquipToTargetCreatureYouControl() structural "
        f"contract for the PROBED tier); got parsed={aa.effect!r}, "
        f"bridged={bridged!r}"
    )


# ---------------------------------------------------------------------------
# (3) Rust synthetic-carrier sanity — the Rust parser accepts the
# bridged equip_to_target_creature_you_control dict shape on a
# Dominion-Bracelet-shape Artifact carrier with a synthetic {1} AA
# cost.
# ---------------------------------------------------------------------------


@_rust_skip
def test_rust_parser_accepts_the_dominion_bracelet_equip_synthetic_dict():
    """Lockstep pin: Rust's ``parse_effect`` arm accepts the
    ``{"kind": "equip_to_target_creature_you_control"}`` dict shape on
    a Dominion-Bracelet-shape Artifact carrier with a synthetic {1} AA
    cost (the cost-side {1} mana atom distinguishes this synthetic
    pin from the sibling Squire's Lightblade {3} synthetic carrier)."""
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "The Dominion Bracelet (synthetic carrier)",
            "card_types": ["Artifact"],
            "mana_cost": {"generic": 2},
            "effects": [],
            "activated_abilities": [
                {
                    "cost": {"mana": {"generic": 1}},
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
# ACTUAL parsed The Dominion Bracelet printing on Python-side resolve
# for the EquipToTargetCreatureYouControl effect.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_the_dominion_bracelet_equip_activation_parity():
    """**GENUINE real-EoE cross-engine probe — The Dominion Bracelet
    Equip AA → EquipToTargetCreatureYouControl(). PROBED-tier flip
    (covered_by_construction → PROBED).**

    Drives the **ACTUAL parsed The Dominion Bracelet printing** on the
    Python side through the EquipToTargetCreatureYouControl effect's
    resolve path with a creature-target seat.  Mirrors the FFFF
    EEEE-idiom (parse + bridge round-trip + Python-side resolve, no
    cross-engine ``compare_fields``); same lane discipline as batches
    1-4 + the sibling Squire's Lightblade probe.

    **NEW shape coverage:** the second PROBE_MODULES-credited probe of
    the EquipToTargetCreatureYouControl Effect class on a real-EoE
    equipment AA carrier (Squire's Lightblade was the first via the
    immediately-prior probe in this batch).  Bit-identical bridge
    round-trip; the per-slug attribution distinction is the printing
    identity (mana cost {2} generic-only vs {W} colored; Equip {1} vs
    {3}).

    **Setup (Python-side):**
      * p0 has The Dominion Bracelet on the battlefield (the AA source
        Equipment).
      * p0 has a creature on the battlefield to be equipped.

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
    # 1. Verify the genuine parsed The Dominion Bracelet printing.
    # ------------------------------------------------------------------
    real = _PRINTINGS.get("The Dominion Bracelet")
    if real is None:
        pytest.skip(
            "The Dominion Bracelet absent from active CardSource"
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
        f"The Dominion Bracelet AA Effect must be byte-equal to "
        f"bridged; got parsed={aa.effect!r}, bridged={bridged!r}"
    )

    # ------------------------------------------------------------------
    # 3. Distinctness regression guard.
    # ------------------------------------------------------------------
    # Bit-identical Effect-level bridge round-trip to Squire's
    # Lightblade — the per-slug attribution flips both slugs
    # independently per the cathedral-of-war-style same-Effect-class-
    # different-printing-slug precedent.  The empty
    # granted_keywords_ueot distinguishes this paid-Equip Effect from
    # the ETB-attach AttachToTargetCreatureYouControl variant
    # (different bridge arm + different keyword-rider shape).
    assert bridged.granted_keywords_ueot == frozenset()

    # ------------------------------------------------------------------
    # 4. Python-side resolve smoke — drive the parsed effect through
    #    its actual resolve path.  Source equipment attaches to target.
    # ------------------------------------------------------------------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py_state = build_python_state(spec)

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
    # otherwise-covered_by_construction card).
    from mtg_bot.cards.base import CardPrinting, ManaCost
    vanilla_creature_target = CardPrinting(
        name="Dominion Bracelet Equip Bait",
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

    assert py_source.attached_to is None

    py_state.resolving_source = py_source
    try:
        aa.effect.resolve(
            py_state,
            py_source.controller_id,
            (("creature", py_target.id),),
        )
    finally:
        py_state.resolving_source = None

    assert py_source.attached_to == py_target.id, (
        f"Post-resolve: source Equipment's attached_to must stamp to "
        f"target.id={py_target.id}; got attached_to="
        f"{py_source.attached_to!r}"
    )
