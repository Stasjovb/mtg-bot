"""**Carrier-AA substrate Phase 1 Cycle 2 (2026-05-25).**

Tests for the Phase 1 Cycle 2 admit-gate landing per
``docs/CARRIER_AA_SUBSTRATE_PHASE_1_DESIGN.md`` §5/§6/§7 (Python bridge
+ admit predicate + builder slice):

  - New :func:`mtg_bot.parity.cross_engine._python_aa_to_safe_dict`
    helper — sibling of :func:`trajectory._python_ta_to_safe_dict`,
    walks an ``ActivatedAbility`` and returns the Rust-parse-shaped
    dict OR ``None`` if any rider falls outside the Phase-1 admit
    set.
  - New :func:`mtg_bot.parity.trajectory._aa_is_phase1_sub_shape_a`
    predicate — gates the per-AA shape (bare ``{T}`` cost + no
    AA-level riders + Phase-1 Effect class).
  - New :func:`mtg_bot.parity.trajectory._printing_is_bridge_simple_
    carrier_aa_land` admit predicate — gates the printing-level shape
    (single-typed non-token Land, exactly 1 AA, no co-gates).
  - New :func:`mtg_bot.parity.trajectory._carrier_aa_land_card_def`
    builder — sibling of the token-AA builder for non-token Land
    carriers.
  - Wires the new predicate into
    ``_filter_deck_to_bridge_supported``'s OR-chain (the FLIP).

**The FLIP.** Cycle 2 inverts the C1 substrate-only invariant pin
``test_swarmyard_stays_declined_post_cycle_1`` →
``test_swarmyard_now_admits_at_admit_gate_post_cycle_2`` (lives in the
C1 test module; the C1 inversion is part of the C2 commit).
Swarmyard DECLINED → ADMITTED. Admit-set count + 1.

**Honest-stop.** Deserted Temple stays declined (cost ``{1}, {T}``
fails the STRICT bare-``{T}`` admit gate per design doc §2.3). Pin
``test_deserted_temple_stays_declined_post_cycle_2`` in the C1 module
guards the honest-stop. Phase 1.5 ships the ``{N}, {T}`` cost-shape
widen.

**No silent auto-grow.** Verify-first walk of the 30 BLOCKED-SG
Carrier-AA cards (per design doc §2.1) confirmed only Swarmyard
admits at Phase 1's STRICT bare-``{T}`` gate. The decline-set pin
below codifies the +1 admit count.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Pin 1 — _python_aa_to_safe_dict round-trip (Swarmyard regenerate shape)
# ---------------------------------------------------------------------------


def test_python_aa_to_safe_dict_round_trips_swarmyard_shape():
    """**Bridge round-trip pin (per design doc §7.1.4).** A Python
    ``ActivatedAbility`` carrying Swarmyard's pilot shape
    (``cost=tap_self``, ``effect=RegenerateTargetCreature(allowed_
    subtypes={...})``) round-trips through
    :func:`cross_engine._python_aa_to_safe_dict` and back through
    :func:`cross_engine._aa_dict_to_python_activated_ability` to a
    byte-equal Python ``ActivatedAbility``."""
    from mtg_bot.effects.base import ActivatedAbility, ActivationCost
    from mtg_bot.effects.generic.destroy import RegenerateTargetCreature
    from mtg_bot.parity.cross_engine import (
        _aa_dict_to_python_activated_ability,
        _python_aa_to_safe_dict,
    )

    aa = ActivatedAbility(
        cost=ActivationCost(tap_self=True),
        effect=RegenerateTargetCreature(
            allowed_subtypes=frozenset(
                {"Rat", "Spider", "Squirrel", "Insect"}
            ),
        ),
    )
    safe = _python_aa_to_safe_dict(aa)
    assert safe is not None
    assert safe == {
        "cost": {"tap_self": True},
        "effect": {
            "kind": "regenerate_target_creature",
            # sorted-canonical emission (sorted for deterministic
            # round-trip across the frozenset).
            "allowed_subtypes": sorted(
                ["Rat", "Spider", "Squirrel", "Insect"]
            ),
        },
    }
    back = _aa_dict_to_python_activated_ability(safe)
    assert back == aa


# ---------------------------------------------------------------------------
# Pin 2 — _python_aa_to_safe_dict round-trip (Deserted Temple untap shape)
# ---------------------------------------------------------------------------


def test_python_aa_to_safe_dict_round_trips_untap_target_land_no_mana():
    """**Bridge round-trip pin.** A Python ``ActivatedAbility``
    carrying a bare-``{T}: Untap target land.`` shape round-trips
    through the safe-dict helper. (The live Deserted Temple printing
    carries a ``{1}, {T}`` cost which fails ``_aa_is_phase1_sub_shape_a``
    at the cost gate; this pin exercises the bare-``{T}`` cost-shape
    surface so the substrate is verified ready for a Phase-1.5
    sibling-swap admit OR a ``{N}, {T}`` widen.)"""
    from mtg_bot.effects.base import ActivatedAbility, ActivationCost
    from mtg_bot.effects.generic.tap import UntapTargetLand
    from mtg_bot.parity.cross_engine import (
        _aa_dict_to_python_activated_ability,
        _python_aa_to_safe_dict,
    )

    aa = ActivatedAbility(
        cost=ActivationCost(tap_self=True),
        effect=UntapTargetLand(),
    )
    safe = _python_aa_to_safe_dict(aa)
    assert safe == {
        "cost": {"tap_self": True},
        "effect": {"kind": "untap_target_land"},
    }
    back = _aa_dict_to_python_activated_ability(safe)
    assert back == aa


# ---------------------------------------------------------------------------
# Pin 3 — _python_aa_to_safe_dict declines AA-level riders
# ---------------------------------------------------------------------------


def test_python_aa_to_safe_dict_declines_mana_ability_rider():
    """**Decline pin.** ``is_mana_ability=True`` is a Phase-2+ rider;
    the safe-dict helper declines (returns ``None``)."""
    from mtg_bot.effects.base import ActivatedAbility, ActivationCost
    from mtg_bot.effects.generic.tap import UntapTargetLand
    from mtg_bot.parity.cross_engine import _python_aa_to_safe_dict

    aa = ActivatedAbility(
        cost=ActivationCost(tap_self=True),
        effect=UntapTargetLand(),
        is_mana_ability=True,
    )
    assert _python_aa_to_safe_dict(aa) is None


def test_python_aa_to_safe_dict_declines_sorcery_speed_rider():
    """**Decline pin.** ``sorcery_speed=True`` is a Phase-3 rider
    (Equipment cluster); the safe-dict helper declines."""
    from mtg_bot.effects.base import ActivatedAbility, ActivationCost
    from mtg_bot.effects.generic.tap import UntapTargetLand
    from mtg_bot.parity.cross_engine import _python_aa_to_safe_dict

    aa = ActivatedAbility(
        cost=ActivationCost(tap_self=True),
        effect=UntapTargetLand(),
        sorcery_speed=True,
    )
    assert _python_aa_to_safe_dict(aa) is None


def test_python_aa_to_safe_dict_declines_unsupported_effect_class():
    """**Decline pin.** An Effect class outside the Phase-1 admit set
    (here ``DrawCards``) declines."""
    from mtg_bot.effects.base import ActivatedAbility, ActivationCost
    from mtg_bot.effects.generic.draw_mill import DrawCards
    from mtg_bot.parity.cross_engine import _python_aa_to_safe_dict

    aa = ActivatedAbility(
        cost=ActivationCost(tap_self=True),
        effect=DrawCards(amount=1),
    )
    assert _python_aa_to_safe_dict(aa) is None


# ---------------------------------------------------------------------------
# Pin 4 — _aa_is_phase1_sub_shape_a positive + per-rider decline matrix
# ---------------------------------------------------------------------------


def test_aa_is_phase1_sub_shape_a_admits_swarmyard_pilot_shape():
    """**Admit pin.** Swarmyard's exact pilot-pair AA shape passes
    :func:`_aa_is_phase1_sub_shape_a`."""
    from mtg_bot.effects.base import ActivatedAbility, ActivationCost
    from mtg_bot.effects.generic.destroy import RegenerateTargetCreature
    from mtg_bot.parity.trajectory import _aa_is_phase1_sub_shape_a

    aa = ActivatedAbility(
        cost=ActivationCost(tap_self=True),
        effect=RegenerateTargetCreature(
            allowed_subtypes=frozenset(
                {"Rat", "Spider", "Squirrel", "Insect"}
            ),
        ),
    )
    assert _aa_is_phase1_sub_shape_a(aa) is True


@pytest.mark.parametrize("cost_kwargs,reason", [
    ({"tap_self": True, "sacrifice_self": True}, "sacrifice_self"),
    ({"tap_self": True, "pay_life": 1}, "pay_life"),
    ({"tap_self": True, "sacrifice_a_desert": True}, "sacrifice_a_desert"),
    ({"tap_self": False}, "missing tap_self"),
])
def test_aa_is_phase1_sub_shape_a_declines_non_bare_T_costs(
    cost_kwargs, reason,
):
    """**Decline pin (cost-gate teeth).** Every cost-shape outside the
    STRICT bare-``{T}`` Phase-1 admit set declines."""
    from mtg_bot.effects.base import ActivatedAbility, ActivationCost
    from mtg_bot.effects.generic.tap import UntapTargetLand
    from mtg_bot.parity.trajectory import _aa_is_phase1_sub_shape_a

    aa = ActivatedAbility(
        cost=ActivationCost(**cost_kwargs),
        effect=UntapTargetLand(),
    )
    assert _aa_is_phase1_sub_shape_a(aa) is False, reason


# ---------------------------------------------------------------------------
# Pin 5 — _aa_is_phase1_sub_shape_a declines cost.mana not None
# ---------------------------------------------------------------------------


def test_aa_is_phase1_sub_shape_a_declines_deserted_temple_1T_cost():
    """**Decline pin (Deserted Temple's exact ``{1}, {T}`` shape).**
    The STRICT bare-``{T}`` admit gate rejects ``cost.mana is not None``
    — Deserted Temple's printed cost ``{1}, {T}`` is HONESTLY out-of-
    scope for Phase 1 (waits for Phase 1.5's ``{N}, {T}`` widen)."""
    from mtg_bot.cards.base import ManaCost
    from mtg_bot.effects.base import ActivatedAbility, ActivationCost
    from mtg_bot.effects.generic.tap import UntapTargetLand
    from mtg_bot.parity.trajectory import _aa_is_phase1_sub_shape_a

    aa = ActivatedAbility(
        cost=ActivationCost(
            mana=ManaCost(generic=1),
            tap_self=True,
        ),
        effect=UntapTargetLand(),
    )
    assert _aa_is_phase1_sub_shape_a(aa) is False


# ---------------------------------------------------------------------------
# Pin 6 — _printing_is_bridge_simple_carrier_aa_land admits Swarmyard
# ---------------------------------------------------------------------------


def test_printing_is_bridge_simple_carrier_aa_land_admits_live_swarmyard():
    """**Admit-set pin.** The live ``OracleParserCardSource``
    Swarmyard printing passes
    :func:`_printing_is_bridge_simple_carrier_aa_land` — the FLIP."""
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import (
        _printing_is_bridge_simple_carrier_aa_land,
    )

    ps = OracleParserCardSource().get_printings()
    assert _printing_is_bridge_simple_carrier_aa_land(ps["Swarmyard"]) is True


def test_printing_is_bridge_simple_carrier_aa_land_declines_live_deserted_temple():
    """**Honest-stop pin.** Deserted Temple's live printing fails the
    STRICT bare-``{T}`` gate (cost ``{1}, {T}``). The predicate
    declines; substrate is in place for Phase 1.5 widen."""
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import (
        _printing_is_bridge_simple_carrier_aa_land,
    )

    ps = OracleParserCardSource().get_printings()
    assert (
        _printing_is_bridge_simple_carrier_aa_land(ps["Deserted Temple"])
        is False
    )


# ---------------------------------------------------------------------------
# Pin 7 — no-silent-auto-grow walk of the 30 BLOCKED-SG Carrier-AA cards
# ---------------------------------------------------------------------------


def test_carrier_aa_30_no_silent_auto_grow_admit_set_exactly_swarmyard():
    """**No-silent-auto-grow pin (per design doc §7.4.10).** Walks the
    30 BLOCKED-SG Carrier-AA cards from design doc §2.1 against
    :func:`_printing_is_bridge_simple_carrier_aa_land`. ONLY Swarmyard
    admits. Every other carrier honestly declines per the verify-first
    walk recorded in the C2 commit message."""
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import (
        _printing_is_bridge_simple_carrier_aa_land,
    )

    ps = OracleParserCardSource().get_printings()
    carrier_aa_30 = [
        "All-Fates Scroll", "Ancient Tomb", "Atomic Microsizer",
        "Auxiliary Boosters", "Baseball Bat", "Blast Zone",
        "Contested War Zone", "Deserted Temple", "Ghost Vacuum",
        "Grove of the Burnwillows", "Haunted Screen",
        "Keys to the House", "Lavaclaw Reaches", "Lotus Field",
        "Meteor Crater", "Mirrorpool", "Mystifying Maze",
        "Nesting Grounds", "Petrified Field", "Pinnacle Starcage",
        "Reflecting Pool", "Robe of Stars", "Saw", "Scavenger Grounds",
        "Sliver Overlord", "Swarmyard", "Terrain Generator",
        "The Eternity Elevator", "Thespian's Stage",
        "Wandering Fumarole",
    ]
    admits = [
        name
        for name in carrier_aa_30
        if _printing_is_bridge_simple_carrier_aa_land(ps[name])
    ]
    assert admits == ["Swarmyard"], (
        f"Carrier-AA Phase 1 Cycle 2 admit-set pin violated: "
        f"expected admit set = ['Swarmyard'], got {admits}. A widen "
        f"in a sibling substrate or predicate would surface here as "
        f"a silent auto-grow — investigate before merging."
    )


# ---------------------------------------------------------------------------
# Pin 8 — _carrier_aa_land_card_def builder shape on live Swarmyard
# ---------------------------------------------------------------------------


def test_carrier_aa_land_card_def_builds_swarmyard_carddef_byte_equal():
    """**Builder pin.** :func:`_carrier_aa_land_card_def` produces a
    CardDef carrying the Swarmyard AA dict shape — single non-token
    activated_abilities entry, no mana_produced (Swarmyard is NOT
    mana-producing), no triggered/static/keyword surface."""
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity.cross_engine import CardDef
    from mtg_bot.parity.trajectory import _carrier_aa_land_card_def

    ps = OracleParserCardSource().get_printings()
    card_def = _carrier_aa_land_card_def(ps["Swarmyard"])
    assert isinstance(card_def, CardDef)
    assert card_def.name == "Swarmyard"
    assert card_def.card_type == "Land"
    assert card_def.mana_produced == ()
    assert card_def.triggered_abilities == ()
    assert card_def.keywords == ()
    assert card_def.token_activated_abilities == ()
    aas = card_def.activated_abilities
    assert len(aas) == 1
    aa_dict = aas[0]
    assert aa_dict["cost"] == {"tap_self": True}
    eff = aa_dict["effect"]
    assert eff["kind"] == "regenerate_target_creature"
    assert eff["allowed_subtypes"] == sorted(
        ["Rat", "Spider", "Squirrel", "Insect"]
    )


# ---------------------------------------------------------------------------
# Pin 9 — End-to-end loader admit threads Swarmyard through
# ---------------------------------------------------------------------------


def test_filter_deck_to_bridge_supported_admits_swarmyard():
    """**OR-chain wiring pin (per design doc §7.4.11).** The
    production-deck loader's ``_filter_deck_to_bridge_supported``
    OR-chain admits Swarmyard end-to-end. ``filtered_names`` carries
    ``Swarmyard``; the returned CardDef list carries the Carrier-AA
    builder's output."""
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import _filter_deck_to_bridge_supported

    ps = OracleParserCardSource().get_printings()
    filtered, card_defs = _filter_deck_to_bridge_supported(
        ["Swarmyard"], ps,
    )
    assert filtered == ["Swarmyard"]
    assert len(card_defs) == 1
    card_def = card_defs[0]
    assert card_def.name == "Swarmyard"
    assert len(card_def.activated_abilities) == 1
    aa_dict = card_def.activated_abilities[0]
    assert aa_dict["effect"]["kind"] == "regenerate_target_creature"


# ---------------------------------------------------------------------------
# Pin 10 — loader DECLINES Deserted Temple (honest-stop end-to-end)
# ---------------------------------------------------------------------------


def test_filter_deck_to_bridge_supported_declines_deserted_temple():
    """**Honest-stop wiring pin.** The loader DROPS Deserted Temple
    (cost-shape mismatch with the STRICT bare-``{T}`` gate). The
    ``not_bridged_sink`` records the drop with the original name."""
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import _filter_deck_to_bridge_supported

    ps = OracleParserCardSource().get_printings()
    not_bridged: list[str] = []
    filtered, card_defs = _filter_deck_to_bridge_supported(
        ["Deserted Temple"], ps,
        not_bridged_sink=not_bridged,
    )
    assert filtered == []
    assert card_defs == []
    assert not_bridged == ["Deserted Temple"]


# ---------------------------------------------------------------------------
# Pin 11 — round-trip through CardDef ↔ Python printing (Swarmyard end-to-end)
# ---------------------------------------------------------------------------


def test_swarmyard_carddef_round_trips_through_python_printing_byte_equal():
    """**Round-trip pin (per design doc §7.2.5).** The Swarmyard
    CardDef → Python CardPrinting reverse arm
    (:func:`cross_engine._card_def_to_python_printing`) materializes a
    Python printing whose ``activated_abilities`` tuple carries an
    ``ActivatedAbility`` byte-equal to the live source printing's AA
    at the dataclass ``__eq__`` surface (cost + effect; the live AA
    has no riders so dataclass-eq compares cleanly)."""
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity.cross_engine import _card_def_to_python_printing
    from mtg_bot.parity.trajectory import _carrier_aa_land_card_def

    ps = OracleParserCardSource().get_printings()
    src = ps["Swarmyard"]
    card_def = _carrier_aa_land_card_def(src)
    assert card_def is not None
    rebuilt = _card_def_to_python_printing(card_def)
    src_aas = tuple(src.activated_abilities)
    rebuilt_aas = tuple(rebuilt.activated_abilities)
    assert len(rebuilt_aas) == 1
    assert len(src_aas) == 1
    # Dataclass __eq__ compares all fields — cost + effect + every
    # rider. Both sides carry the same default-rider shape (no
    # riders), so equality holds end-to-end.
    assert rebuilt_aas[0] == src_aas[0]
