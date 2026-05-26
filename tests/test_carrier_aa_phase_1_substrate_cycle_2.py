"""**Carrier-AA substrate Phase 1 Cycle 2 + Phase 1.5a (2026-05-25).**

Tests for the Phase 1 Cycle 2 admit-gate landing per
``docs/CARRIER_AA_SUBSTRATE_PHASE_1_DESIGN.md`` §5/§6/§7 (Python bridge
+ admit predicate + builder slice), with C2 honest-stop pins **inverted
in-place by Phase 1.5a** (cost-gate widen — see
``docs/CARRIER_AA_SUBSTRATE_PHASE_1_5_DESIGN.md`` §5/§6):

  - New :func:`mtg_bot.parity.cross_engine._python_aa_to_safe_dict`
    helper — sibling of :func:`trajectory._python_ta_to_safe_dict`,
    walks an ``ActivatedAbility`` and returns the Rust-parse-shaped
    dict OR ``None`` if any rider falls outside the Phase-1 admit
    set.
  - New :func:`mtg_bot.parity.trajectory._aa_is_phase1_sub_shape_a`
    predicate — gates the per-AA shape. **Phase 1.5a widened the
    cost gate** from STRICT bare ``{T}`` to bare ``{T}`` OR
    ``{N}, {T}`` (generic-only mana — no colored / hybrid / X-pip).
  - New :func:`mtg_bot.parity.trajectory._printing_is_bridge_simple_
    carrier_aa_land` admit predicate — gates the printing-level shape
    (single-typed non-token Land, exactly 1 AA, no co-gates).
  - New :func:`mtg_bot.parity.trajectory._carrier_aa_land_card_def`
    builder — sibling of the token-AA builder for non-token Land
    carriers.
  - Wires the new predicate into
    ``_filter_deck_to_bridge_supported``'s OR-chain (the FLIP).

**The FLIPs.** Cycle 2 inverted the C1 substrate-only invariant pin
``test_swarmyard_stays_declined_post_cycle_1`` →
``test_swarmyard_now_admits_at_admit_gate_post_cycle_2``. Phase 1.5a
(this slice) inverts the C2 honest-stop pins for Deserted Temple
(cost-axis admit on ``{N}, {T}``):

  * ``test_aa_is_phase1_sub_shape_a_declines_deserted_temple_1T_cost``
    → ``test_aa_is_phase1_5_sub_shape_a_admits_deserted_temple_1T_cost``
  * ``test_printing_is_bridge_simple_carrier_aa_land_declines_live_
    deserted_temple`` →
    ``test_printing_is_bridge_simple_carrier_aa_land_admits_live_
    deserted_temple``
  * ``test_filter_deck_to_bridge_supported_declines_deserted_temple``
    → ``test_filter_deck_to_bridge_supported_admits_deserted_temple``

Admit-set count + 1 (Swarmyard + Deserted Temple, total 2).

**No silent auto-grow (Phase 1.5a re-walk).** Verify-first walk of
the 30 BLOCKED-SG Carrier-AA cards (per design doc §2.1) under the
WIDENED cost-gate confirms only Swarmyard + Deserted Temple admit at
the Phase-1 Effect-class scope ``{RegenerateTargetCreature,
UntapTargetLand}``. Candidate siblings stay declined on Effect-class
teeth: Terrain Generator
(``PutBasicLandFromHandOntoBattlefieldTapped``), Thespian's Stage
(``BecomesCopyOfTargetLand``), Mystifying Maze
(``ExileTargetAttackingCreatureUntilEndStep``).
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
    # Phase 2a INVERTED ``sacrifice_self`` — moved to the admit pin
    # ``test_aa_is_phase2a_sub_shape_a_now_admits_T_plus_sac_after_widen``.
    # Phase 3B C2 INVERTED ``sacrifice_a_desert`` — moved to the
    # admit pin
    # ``test_aa_is_phase3b_sub_shape_a_now_admits_T_plus_sac_a_desert_after_widen``.
    ({"tap_self": True, "pay_life": 1}, "pay_life"),
    ({"tap_self": False}, "missing tap_self"),
])
def test_aa_is_phase1_sub_shape_a_declines_non_bare_T_costs(
    cost_kwargs, reason,
):
    """**Decline pin (cost-gate teeth).** Every cost-shape outside
    the Phase-3B admit set still declines. Phase 2a widened the
    ``sacrifice_self`` axis; Phase 3B C2 widens the
    ``sacrifice_a_desert`` axis; other cost-bools (``pay_life``,
    missing ``tap_self``) keep their Phase-N honest-stops."""
    from mtg_bot.effects.base import ActivatedAbility, ActivationCost
    from mtg_bot.effects.generic.tap import UntapTargetLand
    from mtg_bot.parity.trajectory import _aa_is_phase1_sub_shape_a

    aa = ActivatedAbility(
        cost=ActivationCost(**cost_kwargs),
        effect=UntapTargetLand(),
    )
    assert _aa_is_phase1_sub_shape_a(aa) is False, reason


def test_aa_is_phase3b_sub_shape_a_now_admits_T_plus_sac_a_desert_after_widen():
    """**Phase 3B C2 INVERSION admit pin (sacrifice_a_desert axis).**
    The Phase-3B C2 cost-gate widen accepts
    ``cost.sacrifice_a_desert=True`` alongside ``tap_self`` (with
    or without generic mana) — Scavenger Grounds's printed cost
    ``{2}, {T}, Sac-a-Desert`` now ADMITS at the cost-gate level
    (was Phase-1/1.5/2a honest-stop on the strict
    ``sacrifice_a_desert`` decline). Pairs with the Effect-class
    widen for ``ExileAllGraveyards`` so the end-to-end admit-gate
    FLIPs DECLINED → ADMITTED on Scavenger Grounds.

    The both-at-once defense-in-depth guard
    (``sacrifice_a_desert and sacrifice_self``) still declines —
    see ``test_aa_is_phase3b_sub_shape_a_declines_both_sacrifice_axes_at_once``.
    """
    from mtg_bot.effects.base import ActivatedAbility, ActivationCost
    from mtg_bot.effects.generic.exile import ExileAllGraveyards
    from mtg_bot.parity.trajectory import _aa_is_phase1_sub_shape_a

    aa = ActivatedAbility(
        cost=ActivationCost(
            tap_self=True,
            sacrifice_a_desert=True,
        ),
        effect=ExileAllGraveyards(),
    )
    assert _aa_is_phase1_sub_shape_a(aa) is True


def test_aa_is_phase3b_sub_shape_a_declines_both_sacrifice_axes_at_once():
    """**Phase 3B C2 defense-in-depth guard pin.** The cost-gate
    declines synthetic carriers with BOTH ``sacrifice_a_desert=True``
    AND ``sacrifice_self=True`` set. No live EoE carrier carries both
    axes (verify-first full-pool audit at 2026-05-25); the guard
    exists so a future-carrier carrying both axes fails honestly
    rather than silently auto-admitting under the Phase-3B widen.
    """
    from mtg_bot.effects.base import ActivatedAbility, ActivationCost
    from mtg_bot.effects.generic.exile import ExileAllGraveyards
    from mtg_bot.parity.trajectory import _aa_is_phase1_sub_shape_a

    aa = ActivatedAbility(
        cost=ActivationCost(
            tap_self=True,
            sacrifice_a_desert=True,
            sacrifice_self=True,
        ),
        effect=ExileAllGraveyards(),
    )
    assert _aa_is_phase1_sub_shape_a(aa) is False


# ---------------------------------------------------------------------------
# Pin 5 — _aa_is_phase1_sub_shape_a (Phase 1.5a widen) — admits {N}, {T}
# generic-only mana costs; declines colored / hybrid / X-pip
# ---------------------------------------------------------------------------


def test_aa_is_phase1_5_sub_shape_a_admits_deserted_temple_1T_cost():
    """**Phase 1.5a INVERSION admit pin (Deserted Temple's exact
    ``{1}, {T}`` shape).** The Phase-1.5a cost-gate widen accepts
    ``cost.mana`` carrying generic-only pips alongside ``tap_self`` —
    Deserted Temple's printed cost ``{1}, {T}`` now ADMITS at the
    Phase-1.5a admit gate (was Phase-1 honest-stop on the STRICT
    bare-``{T}`` gate). Inverts the C2 pin
    ``test_aa_is_phase1_sub_shape_a_declines_deserted_temple_1T_cost``.
    """
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
    assert _aa_is_phase1_sub_shape_a(aa) is True


def test_aa_is_phase1_5_sub_shape_a_admits_generic_two_T_cost():
    """**Phase 1.5a admit pin (generic mana axis — ``{2}, {T}`` shape).**
    The Phase-1.5a widen accepts any positive generic-only mana count
    alongside ``tap_self``. Synthetic two-generic carrier with
    ``UntapTargetLand`` admits (regression coverage past the
    Deserted-Temple-shape ``generic=1`` case)."""
    from mtg_bot.cards.base import ManaCost
    from mtg_bot.effects.base import ActivatedAbility, ActivationCost
    from mtg_bot.effects.generic.tap import UntapTargetLand
    from mtg_bot.parity.trajectory import _aa_is_phase1_sub_shape_a

    aa = ActivatedAbility(
        cost=ActivationCost(
            mana=ManaCost(generic=2),
            tap_self=True,
        ),
        effect=UntapTargetLand(),
    )
    assert _aa_is_phase1_sub_shape_a(aa) is True


def test_aa_is_phase1_5_sub_shape_a_declines_colored_mana_cost():
    """**Phase 1.5a decline pin (colored mana axis).** A synthetic AA
    carrying ``cost=ActivationCost(tap_self=True,
    mana=ManaCost(colored=(('R', 1),)))`` declines — colored mana stays
    Phase-2+ honest-stop. The widen is strictly additive on the
    generic-mana axis."""
    from mtg_bot.cards.base import ManaCost
    from mtg_bot.effects.base import ActivatedAbility, ActivationCost
    from mtg_bot.effects.generic.tap import UntapTargetLand
    from mtg_bot.parity.trajectory import _aa_is_phase1_sub_shape_a

    aa = ActivatedAbility(
        cost=ActivationCost(
            mana=ManaCost(generic=0, colored=(("R", 1),)),
            tap_self=True,
        ),
        effect=UntapTargetLand(),
    )
    assert _aa_is_phase1_sub_shape_a(aa) is False


def test_aa_is_phase1_5_sub_shape_a_declines_hybrid_mana_cost():
    """**Phase 1.5a decline pin (hybrid mana axis).** A synthetic AA
    carrying a hybrid-mana cost (``mana=ManaCost(hybrid=(('R', 'G'),))``)
    declines — hybrid mana stays Phase-2+ honest-stop."""
    from mtg_bot.cards.base import ManaCost
    from mtg_bot.effects.base import ActivatedAbility, ActivationCost
    from mtg_bot.effects.generic.tap import UntapTargetLand
    from mtg_bot.parity.trajectory import _aa_is_phase1_sub_shape_a

    aa = ActivatedAbility(
        cost=ActivationCost(
            mana=ManaCost(generic=0, hybrid=(("R", "G"),)),
            tap_self=True,
        ),
        effect=UntapTargetLand(),
    )
    assert _aa_is_phase1_sub_shape_a(aa) is False


def test_aa_is_phase1_5_sub_shape_a_declines_x_pip_mana_cost():
    """**Phase 1.5a decline pin (X-cost axis).** A synthetic AA carrying
    an X-pip mana cost (``mana=ManaCost(x_pips=1)``) declines — X-cost
    AAs stay Phase-2+ honest-stop."""
    from mtg_bot.cards.base import ManaCost
    from mtg_bot.effects.base import ActivatedAbility, ActivationCost
    from mtg_bot.effects.generic.tap import UntapTargetLand
    from mtg_bot.parity.trajectory import _aa_is_phase1_sub_shape_a

    aa = ActivatedAbility(
        cost=ActivationCost(
            mana=ManaCost(generic=0, x_pips=1),
            tap_self=True,
        ),
        effect=UntapTargetLand(),
    )
    assert _aa_is_phase1_sub_shape_a(aa) is False


def test_aa_is_phase2a_sub_shape_a_now_admits_T_plus_sac_after_widen():
    """**Phase 2a INVERSION pin (cost-gate widen on ``sacrifice_self``
    axis).** Bare ``{T}`` + ``sacrifice_self=True`` now ADMITS under
    Phase 2a (Effect must be in the Phase-2a admit set — pair with
    ``UntapTargetLand`` for the cost-axis pin; the Effect-class teeth
    are exercised separately in the Phase-2a Petrified Field probe
    + the Phase-2a sub-shape unit pins).

    Inverts the Phase-1.5a pin
    ``test_aa_is_phase1_5_sub_shape_a_still_declines_T_plus_sac_after_
    widen``. The widen is strictly additive on the ``sacrifice_self``
    axis; other cost-bools (``pay_life``, ``sacrifice_a_desert``,
    ``sacrifice_another_*``, ``exile_self``,
    ``tap_permanent_you_control``, etc.) still decline — see the
    sibling regression pins."""
    from mtg_bot.effects.base import ActivatedAbility, ActivationCost
    from mtg_bot.effects.generic.tap import UntapTargetLand
    from mtg_bot.parity.trajectory import _aa_is_phase1_sub_shape_a

    aa = ActivatedAbility(
        cost=ActivationCost(tap_self=True, sacrifice_self=True),
        effect=UntapTargetLand(),
    )
    assert _aa_is_phase1_sub_shape_a(aa) is True


def test_aa_is_phase1_5_sub_shape_a_round_trips_deserted_temple_synthetic():
    """**Phase 1.5a round-trip pin (cost-mana axis through the safe-
    dict bridge).** A synthetic Deserted-Temple-shape AA round-trips
    byte-equal through ``_python_aa_to_safe_dict`` ↔
    ``_aa_dict_to_python_activated_ability`` — confirming the bridge
    already serializes generic-mana costs (no Rust change needed for
    Phase 1.5a)."""
    from mtg_bot.cards.base import ManaCost
    from mtg_bot.effects.base import ActivatedAbility, ActivationCost
    from mtg_bot.effects.generic.tap import UntapTargetLand
    from mtg_bot.parity.cross_engine import (
        _aa_dict_to_python_activated_ability,
        _python_aa_to_safe_dict,
    )

    aa = ActivatedAbility(
        cost=ActivationCost(
            mana=ManaCost(generic=1),
            tap_self=True,
        ),
        effect=UntapTargetLand(),
    )
    safe = _python_aa_to_safe_dict(aa)
    assert safe is not None
    assert safe == {
        "cost": {"mana": {"generic": 1}, "tap_self": True},
        "effect": {"kind": "untap_target_land"},
    }
    back = _aa_dict_to_python_activated_ability(safe)
    assert back == aa


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


def test_printing_is_bridge_simple_carrier_aa_land_admits_live_deserted_temple():
    """**Phase 1.5a INVERSION admit-set pin.** Deserted Temple's live
    printing now PASSES :func:`_printing_is_bridge_simple_carrier_aa_
    land` post-cost-gate-widen. The Phase 1.5a admit-set has Swarmyard
    + Deserted Temple (was Swarmyard alone at strict bare-``{T}``).
    Inverts the C2 pin
    ``test_printing_is_bridge_simple_carrier_aa_land_declines_live_
    deserted_temple``."""
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import (
        _printing_is_bridge_simple_carrier_aa_land,
    )

    ps = OracleParserCardSource().get_printings()
    assert (
        _printing_is_bridge_simple_carrier_aa_land(ps["Deserted Temple"])
        is True
    )


# ---------------------------------------------------------------------------
# Pin 7 — no-silent-auto-grow walk of the 30 BLOCKED-SG Carrier-AA cards
# ---------------------------------------------------------------------------


def test_carrier_aa_30_no_silent_auto_grow_admit_set_swarmyard_plus_deserted_temple_plus_petrified_field_plus_terrain_generator_plus_mystifying_maze_plus_scavenger_grounds_plus_thespians_stage():
    """**Phase 3C C3 no-silent-auto-grow pin (INVERTED — admit count
    6 → 7).** Walks the 30 BLOCKED-SG Carrier-AA cards from design
    doc §2.1 against :func:`_printing_is_bridge_simple_carrier_aa_land`
    under the Phase-3C-C3 widened Effect-class admit set
    (``RegenerateTargetCreature`` + ``UntapTargetLand`` +
    ``ReturnTargetLandFromGraveyardToHand`` +
    ``PutBasicLandFromHandOntoBattlefieldTapped`` +
    ``ExileTargetAttackingCreatureUntilEndStep`` +
    ``ExileAllGraveyards`` + ``BecomesCopyOfTargetLand``) atop the
    Phase-3B widened cost-gate (bare ``{T}`` OR ``{N}, {T}`` OR
    ``({T}, Sac:)`` OR ``({N}, {T}, Sac:)`` OR
    ``({T}, Sac-a-Desert:)`` OR ``({N}, {T}, Sac-a-Desert:)`` under
    the both-at-once defense-in-depth guard). ONLY Swarmyard +
    Deserted Temple + Petrified Field + Terrain Generator +
    Mystifying Maze + Scavenger Grounds + Thespian's Stage admit;
    every other carrier honestly declines per the verify-first walk
    at 2026-05-26.

    Verify-first walk (2026-05-26 against the live EoE pool with
    ``BecomesCopyOfTargetLand`` added to the Effect-class admit set):
    exactly ONE new card admits (Thespian's Stage) under the
    widened gate — every other carrier honestly declines via the
    multi-AA gate (Mirrorpool / Ghost Vacuum / Keys to the House /
    All-Fates Scroll / Haunted Screen / The Eternity Elevator /
    Sliver Overlord / Robe of Stars / Saw / Atomic Microsizer / etc.)
    OR the colored-mana / x-pip cost-shape gate (Reflecting Pool /
    Meteor Crater / Grove of the Burnwillows / Lotus Field /
    Ancient Tomb / Nesting Grounds / Blast Zone / Lavaclaw Reaches /
    Wandering Fumarole / Contested War Zone / Pinnacle Starcage /
    Auxiliary Boosters / Baseball Bat).

    Sibling-candidate Effect-class teeth remain load-bearing — no
    Phase-3 Carrier-AA Effect candidate remains outside the admit
    set. Any NEW Effect class admitted to the set (Phase 4+) would
    surface here as a silent auto-grow — investigate before merging.

    Inverts the Phase-3B-C2 pin
    ``test_carrier_aa_30_no_silent_auto_grow_admit_set_swarmyard_
    plus_deserted_temple_plus_petrified_field_plus_terrain_generator_
    plus_mystifying_maze_plus_scavenger_grounds`` (admit set was
    ``['Deserted Temple', 'Mystifying Maze', 'Petrified Field',
    'Scavenger Grounds', 'Swarmyard', 'Terrain Generator']``).
    """
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
    admits = sorted(
        name
        for name in carrier_aa_30
        if _printing_is_bridge_simple_carrier_aa_land(ps[name])
    )
    assert admits == [
        "Deserted Temple",
        "Mystifying Maze",
        "Petrified Field",
        "Scavenger Grounds",
        "Swarmyard",
        "Terrain Generator",
        "Thespian's Stage",
    ], (
        f"Carrier-AA Phase 3C C3 admit-set pin violated: expected "
        f"admit set = ['Deserted Temple', 'Mystifying Maze', "
        f"'Petrified Field', 'Scavenger Grounds', 'Swarmyard', "
        f"'Terrain Generator', \"Thespian's Stage\"], got {admits}. "
        f"A widen in a sibling substrate or predicate would surface "
        f"here as a silent auto-grow — investigate before merging."
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
# Pin 10 — Phase 1.5a INVERSION — loader ADMITS Deserted Temple end-to-end
# ---------------------------------------------------------------------------


def test_filter_deck_to_bridge_supported_admits_deserted_temple():
    """**Phase 1.5a INVERSION wiring pin.** The loader ADMITS Deserted
    Temple end-to-end post-cost-gate-widen — the Carrier-AA disjunct
    fires under the bare-``{T}`` OR ``{N}, {T}`` gate. The returned
    CardDef carries the Carrier-AA builder's output for the
    ``UntapTargetLand`` Effect.

    Inverts the C2 pin
    ``test_filter_deck_to_bridge_supported_declines_deserted_temple``."""
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import _filter_deck_to_bridge_supported

    ps = OracleParserCardSource().get_printings()
    filtered, card_defs = _filter_deck_to_bridge_supported(
        ["Deserted Temple"], ps,
    )
    assert filtered == ["Deserted Temple"]
    assert len(card_defs) == 1
    card_def = card_defs[0]
    assert card_def.name == "Deserted Temple"
    assert len(card_def.activated_abilities) == 1
    aa_dict = card_def.activated_abilities[0]
    assert aa_dict["cost"] == {"mana": {"generic": 1}, "tap_self": True}
    assert aa_dict["effect"] == {"kind": "untap_target_land"}


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
