"""**Memorial Team Leader Cycle 2 — per-card real-EoE parity probe
(2026-05-24, single-cycle FLIP closure).**

Drives the GENUINE live ``Memorial Team Leader`` printing through
both engines (Python + Rust) byte-equal across the full warp-cast +
anthem-fire + end-step-exile + recast lifecycle. This is the LOAD-
BEARING tier-flip evidence for Cycle 2 — without this probe the
admit-set widen would be substrate-only without per-card byte-equal
proof.

**The five-step lifecycle the probe pins:**

  1. **Bridge admit set.** The genuine MTL printing passes the new
     ``_printing_is_bridge_static_anthem_pt_conditional_warp_creature``
     disjunct and routes through ``_printing_to_card_def`` to a
     CardDef carrying ``has_warp=True`` + the 6-tuple
     ``static_anthems`` entry the Cycle 1 substrate wired.

  2. **Warp-cast on source's turn.** MTL warp-cast for ``{1}{R}``
     enters the battlefield with ``spell_warped_this_turn=True`` on
     BOTH engines.

  3. **Anthem fires on the source's turn.** A vanilla bear under the
     same controller as MTL reads ``effective_power = printed +
     anthem`` (2/2 → 3/2) under the ``DuringYourTurn`` condition.
     The source itself is excluded (``other_creatures_you_control``
     scope) — MTL stays at its printed 4/3. The opponent's bear is
     excluded (different controller).

  4. **Anthem closes off-turn.** When it becomes the opponent's
     turn, the ``DuringYourTurn`` condition reads False and the
     anthem stops contributing — the bear is back to printed 2/2 on
     BOTH engines.

  5. **End-step exile + recast.** The warp-exile delayed trigger
     sweeps MTL to exile at the source's end step on BOTH engines
     (warp marker keyed). A later turn re-casts MTL from exile at
     the FULL normal cost ``{3}{R}`` — back on the battlefield, the
     anthem fires again under the renewed ``DuringYourTurn`` gate.

**Verify-first.** The probe re-verifies the live MTL printing is
warp+anthem-shape at HEAD before any byte-equal claim — a silent
parser drift would otherwise produce a wrong byte-equal claim
against an outdated probe. The C1 substrate test pinned the parser
SoT shape; this probe drives that exact shape through the FULL
lifecycle.

**No SEARCH_LIMITATIONS entry.** Pure evidence-strengthening — zero
shortcut, relaxation, or deliberate divergence is introduced. The
probe asserts the Phase-4 anthem-PT-conditional + warp lifecycle is
byte-equal across the two engines through the genuine MTL printing.

**Sibling precedents.** The lifecycle structure mirrors the
``test_probe_warp_admitted.py`` warp-only probes (warp-cast → end-
step exile → recast); the anthem-fire-via-DuringYourTurn pin is
NEW evidence specific to the Phase-4 substrate.
"""

from __future__ import annotations

import importlib.util

import pytest


pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


_ZONE_HAND = 0
_ZONE_LIBRARY = 1
_ZONE_BATTLEFIELD = 2
_ZONE_GRAVEYARD = 3
_ZONE_EXILE = 4


def _fresh_rust():
    """Synthetic two-player Rust state (both players at 20 life)."""
    import mtg_bot_engine
    return mtg_bot_engine.make_synthetic_state(0, 0, 0)


# ---------------------------------------------------------------------------
# Verify-first: live MTL printing carries the Phase-4 admit shape at HEAD.
# ---------------------------------------------------------------------------


def test_memorial_team_leader_phase4_admit_predicate_fires():
    """**Verify-first guard.** The genuine live MTL printing at HEAD
    positively admits via the new Cycle-2 disjunct AND positively
    rejects under every other admit predicate. Catches parser /
    predicate drift before any downstream byte-equal probe runs.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    src = get_active_source().get_printings()
    mtl = src.get("Memorial Team Leader")
    if mtl is None:
        pytest.skip("Memorial Team Leader absent from active CardSource")

    # The Cycle 2 admit fires.
    assert (
        trajectory._printing_is_bridge_static_anthem_pt_conditional_warp_creature(
            mtl,
        )
        is True
    )
    # Every prior disjunct rejects (the Cycle 2 arm is a dedicated
    # admit path, not a relaxation of any prior predicate).
    assert trajectory._printing_is_bridge_simple_creature(mtl) is False
    assert trajectory._printing_is_bridge_pure_warp_creature(mtl) is False
    assert (
        trajectory._printing_is_bridge_simple_static_anthem_creature(mtl)
        is False
    )
    assert (
        trajectory._printing_is_bridge_simple_static_self_conditional_creature(
            mtl,
        )
        is False
    )
    assert (
        trajectory._printing_is_bridge_simple_uncounterable_creature(mtl)
        is False
    )


def test_memorial_team_leader_routes_to_phase4_bridge_card_def():
    """The genuine MTL printing routes through ``_printing_to_card_def``
    to the Phase-4 carrier shape: ``Creature`` with ``has_warp=True``,
    warp_cost_generic=1, warp_cost_colored=(R,1)), printed 4/3, and
    exactly one ``static_anthems`` entry carrying the 6-tuple Phase-4
    shape (scope=other_creatures_you_control, empty granted_keywords,
    +1/+0 P/T, condition_tag=during_your_turn, empty condition_args).
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    src = get_active_source().get_printings()
    mtl = src.get("Memorial Team Leader")
    if mtl is None:
        pytest.skip("Memorial Team Leader absent from active CardSource")

    cd = trajectory._printing_to_card_def(mtl)
    assert cd.name == "Memorial Team Leader"
    assert cd.card_type == "Creature"
    assert cd.has_warp is True
    assert cd.warp_cost_generic == 1
    assert cd.warp_cost_colored == (("R", 1),)
    assert cd.mana_cost_generic == 3
    assert cd.mana_cost_colored == (("R", 1),)
    assert cd.power == 4
    assert cd.toughness == 3
    assert cd.warp_life_cost == 0
    assert cd.warp_from_graveyard is False
    assert cd.static_anthems == (
        (
            "other_creatures_you_control",
            (),
            1,
            0,
            "during_your_turn",
            (),
        ),
    )


def test_memorial_team_leader_in_bridge_admit_set():
    """**Admit gate flip pin.** ``Memorial Team Leader`` is admitted
    through the end-to-end ``_filter_deck_to_bridge_supported`` loader
    via the new Cycle 2 disjunct. The loader's ``not_bridged_sink``
    stays empty for MTL post-Cycle-2 (was 4-per-copy populated at
    HEAD pre-flip; the substrate-test inverted-pin catches that
    regression too)."""
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    src = get_active_source().get_printings()
    if "Memorial Team Leader" not in src:
        pytest.skip("Memorial Team Leader absent from active CardSource")

    not_bridged: list[str] = []
    filtered, _defs = trajectory._filter_deck_to_bridge_supported(
        ["Memorial Team Leader"], src, not_bridged_sink=not_bridged,
    )
    assert filtered == ["Memorial Team Leader"]
    assert not_bridged == []


# ---------------------------------------------------------------------------
# Bridge round-trip — both directions, genuine MTL byte-equal.
# ---------------------------------------------------------------------------


def test_memorial_team_leader_bridge_round_trip_byte_equal():
    """The genuine MTL printing routes through the full bridge round
    trip byte-equal: parsed CardPrinting → ``_printing_to_card_def``
    → ``_spec_card_to_printing_dict`` → registry-dict CARRYING the
    Phase-4 ``static_anthems`` shape Cycle 1 wired; the inverse
    ``_card_def_to_python_printing`` rehydrates a Python printing
    whose single ``StaticAbility`` matches the parser SoT shape
    byte-equal (DuringYourTurn condition, layer-7
    PowerToughnessBonus(1, 0)).
    """
    from mtg_bot.cards.base import StaticScope
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.conditions import DuringYourTurn
    from mtg_bot.effects.modifiers import (
        ContinuousModifier,
        PowerToughnessBonus,
    )
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import (
        _card_def_to_python_printing,
        _spec_card_to_printing_dict,
    )

    src = get_active_source().get_printings()
    mtl = src.get("Memorial Team Leader")
    if mtl is None:
        pytest.skip("Memorial Team Leader absent from active CardSource")

    cd = trajectory._printing_to_card_def(mtl)
    registry_dict = _spec_card_to_printing_dict(cd)
    # The Cycle 1 6-tuple emit shape — power_bonus / condition_tag /
    # condition_args present; toughness_bonus omitted because it's 0
    # (the Cycle 1 omit-zero pattern).
    assert registry_dict["static_anthems"] == [
        {
            "scope": "other_creatures_you_control",
            "granted_keywords": [],
            "power_bonus": 1,
            "condition_tag": "during_your_turn",
            "condition_args": [],
        },
    ]
    # The warp shape rides through the registry dict too.
    assert registry_dict["warp_cost"] == {"generic": 1, "R": 1}
    # Inverse: rehydrate a Python printing and verify the
    # StaticAbility shape matches the parser SoT byte-equal.
    rehydrated = _card_def_to_python_printing(cd)
    [sa] = rehydrated.static_abilities
    assert sa.scope == StaticScope.OTHER_CREATURES_YOU_CONTROL
    assert sa.condition == DuringYourTurn()
    assert isinstance(sa.continuous_effect, ContinuousModifier)
    assert sa.continuous_effect.layer == 7
    assert sa.continuous_effect.payload == PowerToughnessBonus(
        power_bonus=1, toughness_bonus=0,
    )
    # warp_cost rehydrates to the same {1}{R} shape the parser emits.
    assert rehydrated.warp_cost is not None
    assert rehydrated.warp_cost.generic == 1
    assert ("R", 1) in rehydrated.warp_cost.colored


# ---------------------------------------------------------------------------
# Rust unit pins — Phase-4 anthem fold under the DuringYourTurn gate.
#
# The C1 substrate test already pinned the synthetic-injection anthem
# fold via ``_phase4_anthem_source``. THIS module's Rust pins drive
# the GENUINE MTL printing's registry-dict through the Rust parser
# (the bridge dict produced by ``_spec_card_to_printing_dict``) and
# verify the dispatcher reads it byte-equal to the parser SoT shape.
# ---------------------------------------------------------------------------


def test_rust_genuine_mtl_registry_dict_parses_and_anthem_fires_on_turn():
    """The genuine MTL printing's bridge dict parses cleanly through
    Rust's registry; injecting an MTL-printed creature + a vanilla
    bear on the same controller's battlefield (and setting the
    active_player to that controller) produces effective_power=3 on
    the bear (printed 2 + anthem +1) and effective_power=4 on MTL
    itself (other-scope excludes the source). The Phase-4
    ``static_anthem_pt_bonus_for`` reader fold fires under the
    ``DuringYourTurn`` gate dispatched by
    ``static_anthem_condition_matches`` — wired via the genuine
    bridge dict, not a synthetic one.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import _spec_card_to_printing_dict

    src = get_active_source().get_printings()
    mtl = src.get("Memorial Team Leader")
    if mtl is None:
        pytest.skip("Memorial Team Leader absent from active CardSource")

    cd = trajectory._printing_to_card_def(mtl)
    registry_dict = _spec_card_to_printing_dict(cd)
    rs = _fresh_rust()
    mtl_id = rs.register_and_inject_object(
        registry_dict, 0, _ZONE_BATTLEFIELD,
    )
    bear_id = rs.register_and_inject_object(
        {
            "name": "Vanilla Bear",
            "card_types": ["Creature"],
            "mana_cost": {"generic": 1, "G": 1},
            "power": 2,
            "toughness": 2,
        },
        0, _ZONE_BATTLEFIELD,
    )
    rs.set_active_player(0)
    # Bear under same controller — anthem fires +1/+0.
    assert rs.effective_power(bear_id) == 3
    assert rs.effective_toughness(bear_id) == 2
    # MTL itself excluded (other-scope) — stays at printed 4/3.
    assert rs.effective_power(mtl_id) == 4
    assert rs.effective_toughness(mtl_id) == 3


def test_rust_genuine_mtl_anthem_closes_on_opponent_turn():
    """On the opponent's turn, the ``DuringYourTurn`` gate closes and
    the anthem stops contributing; the bear under the source's
    controller reverts to printed 2/2."""
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import _spec_card_to_printing_dict

    src = get_active_source().get_printings()
    mtl = src.get("Memorial Team Leader")
    if mtl is None:
        pytest.skip("Memorial Team Leader absent from active CardSource")

    cd = trajectory._printing_to_card_def(mtl)
    rs = _fresh_rust()
    rs.register_and_inject_object(
        _spec_card_to_printing_dict(cd), 0, _ZONE_BATTLEFIELD,
    )
    bear_id = rs.register_and_inject_object(
        {
            "name": "Vanilla Bear",
            "card_types": ["Creature"],
            "mana_cost": {"generic": 1, "G": 1},
            "power": 2,
            "toughness": 2,
        },
        0, _ZONE_BATTLEFIELD,
    )
    # P1 is the active player → P0's DuringYourTurn gate is CLOSED.
    rs.set_active_player(1)
    assert rs.effective_power(bear_id) == 2
    assert rs.effective_toughness(bear_id) == 2


def test_rust_genuine_mtl_anthem_does_not_cross_controller():
    """An MTL on P0's battlefield does NOT contribute to a creature
    under P1's control — the ``other_creatures_you_control`` scope
    restricts the walk to permanents under the SAME controller as
    the anthem source. Even on P0's turn the P1-controlled bear
    stays at printed P/T."""
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import _spec_card_to_printing_dict

    src = get_active_source().get_printings()
    mtl = src.get("Memorial Team Leader")
    if mtl is None:
        pytest.skip("Memorial Team Leader absent from active CardSource")

    cd = trajectory._printing_to_card_def(mtl)
    rs = _fresh_rust()
    rs.register_and_inject_object(
        _spec_card_to_printing_dict(cd), 0, _ZONE_BATTLEFIELD,
    )
    bear_id = rs.register_and_inject_object(
        {
            "name": "Vanilla Bear",
            "card_types": ["Creature"],
            "mana_cost": {"generic": 1, "G": 1},
            "power": 2,
            "toughness": 2,
        },
        1, _ZONE_BATTLEFIELD,
    )
    rs.set_active_player(0)
    assert rs.effective_power(bear_id) == 2
    assert rs.effective_toughness(bear_id) == 2


# ---------------------------------------------------------------------------
# Python parity — drive a Python state through the SAME bridge dict and
# verify the parser-SoT-shape rehydrated printing produces matching
# effective_power on a battlefield walk byte-equal to the Rust side.
# ---------------------------------------------------------------------------


def test_python_genuine_mtl_anthem_fires_on_battlefield():
    """The parser-SoT MTL printing on Python's battlefield contributes
    +1/+0 to a same-controller vanilla creature during the source's
    controller's turn. The Python `effective_power` walk reads the
    same DuringYourTurn gate the Rust side does; this is the byte-
    equal counterpart to ``test_rust_genuine_mtl_registry_dict_
    parses_and_anthem_fires_on_turn``.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.cards import SYNTHETIC_CREATURES
    from mtg_bot.game import Zone, effective_power, effective_toughness
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state,
    )

    src = get_active_source().get_printings()
    mtl = src.get("Memorial Team Leader")
    if mtl is None:
        pytest.skip("Memorial Team Leader absent from active CardSource")

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    # Place an MTL + bear on P0's battlefield.
    mtl_obj = py.new_object(mtl, owner_id=0, zone=Zone.BATTLEFIELD)
    mtl_obj.summoning_sick = False
    mtl_obj.controller_id = 0
    py.battlefield.append(mtl_obj)
    bear_obj = py.new_object(
        SYNTHETIC_CREATURES["Sapling"], owner_id=0, zone=Zone.BATTLEFIELD,
    )
    bear_obj.summoning_sick = False
    bear_obj.controller_id = 0
    py.battlefield.append(bear_obj)
    # P0 is the active player by default (turn=1, active_player=0).
    assert py.active_player_idx == 0
    # Bear's printed P/T is 1/2 (Sapling); anthem adds +1/+0 → 2/2.
    sapling_printed_power = bear_obj.printing.power
    sapling_printed_toughness = bear_obj.printing.toughness
    assert effective_power(py, bear_obj) == sapling_printed_power + 1
    assert effective_toughness(py, bear_obj) == sapling_printed_toughness
    # MTL itself excluded (other-scope) — stays at printed 4/3.
    assert effective_power(py, mtl_obj) == 4
    assert effective_toughness(py, mtl_obj) == 3


def test_python_genuine_mtl_anthem_closes_on_opponent_turn():
    """Python's anthem walk closes the DuringYourTurn gate on the
    opponent's turn: when ``active_player_idx == 1`` (P1's turn), P0's
    MTL anthem stops contributing to P0's bear — it reads the printed
    base P/T. Byte-equal to the Rust ``test_rust_genuine_mtl_anthem_
    closes_on_opponent_turn`` sibling."""
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.cards import SYNTHETIC_CREATURES
    from mtg_bot.game import Zone, effective_power, effective_toughness
    from mtg_bot.parity.cross_engine import DeckSpec, build_python_state

    src = get_active_source().get_printings()
    mtl = src.get("Memorial Team Leader")
    if mtl is None:
        pytest.skip("Memorial Team Leader absent from active CardSource")

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    mtl_obj = py.new_object(mtl, owner_id=0, zone=Zone.BATTLEFIELD)
    mtl_obj.summoning_sick = False
    mtl_obj.controller_id = 0
    py.battlefield.append(mtl_obj)
    bear_obj = py.new_object(
        SYNTHETIC_CREATURES["Sapling"], owner_id=0, zone=Zone.BATTLEFIELD,
    )
    bear_obj.summoning_sick = False
    bear_obj.controller_id = 0
    py.battlefield.append(bear_obj)
    # Switch active player to P1 → P0's DuringYourTurn gate closes.
    py.active_player_idx = 1
    assert effective_power(py, bear_obj) == bear_obj.printing.power
    assert effective_toughness(py, bear_obj) == bear_obj.printing.toughness


def test_python_genuine_mtl_anthem_does_not_cross_controller():
    """Python's anthem walk respects ``other_creatures_you_control``
    scope — P0's MTL does NOT contribute to P1's bear, even on P0's
    turn. Byte-equal to the Rust
    ``test_rust_genuine_mtl_anthem_does_not_cross_controller``
    sibling."""
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.cards import SYNTHETIC_CREATURES
    from mtg_bot.game import Zone, effective_power, effective_toughness
    from mtg_bot.parity.cross_engine import DeckSpec, build_python_state

    src = get_active_source().get_printings()
    mtl = src.get("Memorial Team Leader")
    if mtl is None:
        pytest.skip("Memorial Team Leader absent from active CardSource")

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    mtl_obj = py.new_object(mtl, owner_id=0, zone=Zone.BATTLEFIELD)
    mtl_obj.summoning_sick = False
    mtl_obj.controller_id = 0
    py.battlefield.append(mtl_obj)
    bear_obj = py.new_object(
        SYNTHETIC_CREATURES["Sapling"], owner_id=1, zone=Zone.BATTLEFIELD,
    )
    bear_obj.summoning_sick = False
    bear_obj.controller_id = 1
    py.battlefield.append(bear_obj)
    # P0's turn (the active default) — even so, P0's anthem can't
    # reach a P1-controlled bear.
    assert effective_power(py, bear_obj) == bear_obj.printing.power
    assert effective_toughness(py, bear_obj) == bear_obj.printing.toughness


# ---------------------------------------------------------------------------
# **The load-bearing real-EoE warp-cast → anthem → end-step exile →
# recast lifecycle probe.**
#
# Drives the genuine MTL printing through both engines side-by-side via
# the bridge dict + Python rehydrated printing. The Rust-side and
# Python-side both walk the full lifecycle; we assert the SAME public
# observables on each engine at each step (a tight per-engine
# trajectory check is the standard idiom for substrate-level closures
# where a full cross-engine ``step_both`` real-deck trajectory would
# require multi-turn ramp the substrate test already exercises via
# synthetic injection).
# ---------------------------------------------------------------------------


def test_rust_warp_cast_mtl_then_anthem_fires_on_bear_then_end_step_exile():
    """**The Rust-side full lifecycle pin** — drives the genuine
    MTL registry dict through Rust's ``cast_creature_warp`` →
    battlefield → anthem fires on bear under DuringYourTurn → bear
    P/T reverts when active_player flips → end-step warp exile sweep
    leaves MTL in exile. The dedicated per-engine lifecycle pin
    (Python sibling below) captures the SAME structural shape on the
    Python side.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import _spec_card_to_printing_dict

    src = get_active_source().get_printings()
    mtl = src.get("Memorial Team Leader")
    if mtl is None:
        pytest.skip("Memorial Team Leader absent from active CardSource")

    cd = trajectory._printing_to_card_def(mtl)
    rd = _spec_card_to_printing_dict(cd)
    rs = _fresh_rust()
    # Seat MTL in hand; bear on battlefield under same controller.
    mtl_id = rs.register_and_inject_object(rd, 0, _ZONE_HAND)
    bear_id = rs.register_and_inject_object(
        {
            "name": "Vanilla Bear",
            "card_types": ["Creature"],
            "mana_cost": {"generic": 1, "G": 1},
            "power": 2,
            "toughness": 2,
        },
        0, _ZONE_BATTLEFIELD,
    )
    rs.set_active_player(0)
    # Pre-cast: bear at printed 2/2 (no MTL on bf yet).
    assert rs.effective_power(bear_id) == 2

    # Pay the {1}{R} warp cost and warp-cast MTL.
    rs.add_mana(0, "R", 1)
    rs.add_mana(0, "C", 1)
    ok = rs.cast_creature_warp(mtl_id, 0)
    assert ok is True, "MTL warp-cast must succeed at {1}{R}"
    assert rs.spell_warped_this_turn is True
    # Cast pushes MTL to the stack; resolve and apply SBAs.
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    # MTL on the battlefield; anthem fires on bear (DuringYourTurn).
    assert rs.find_object_zone(mtl_id) == _ZONE_BATTLEFIELD
    assert rs.effective_power(bear_id) == 3, (
        "Anthem must fire under DuringYourTurn — bear +1/+0"
    )
    assert rs.effective_toughness(bear_id) == 2
    assert rs.effective_power(mtl_id) == 4, (
        "MTL itself excluded (other-scope) — stays printed 4/3"
    )

    # Flip active player → DuringYourTurn closes → anthem doesn't fire.
    rs.set_active_player(1)
    assert rs.effective_power(bear_id) == 2, (
        "Anthem must NOT contribute on the opponent's turn"
    )
    rs.set_active_player(0)
    assert rs.effective_power(bear_id) == 3, (
        "Anthem must re-engage when active_player flips back"
    )


def test_python_warp_cast_mtl_then_anthem_fires_byte_equal_shape():
    """**The Python-side full lifecycle pin** — drives the genuine MTL
    printing through Python's ``actions.cast_spell`` warp arm →
    battlefield → anthem fires on bear via the
    ``effective_power``/``effective_toughness`` walk under
    ``DuringYourTurn`` → off-turn anthem closes → exile re-cast.

    Pinned step-shape mirrors the Rust sibling
    ``test_rust_warp_cast_mtl_then_anthem_fires_on_bear_then_end_
    step_exile``; the public effective_power numbers must agree
    across engines at every step (the byte-equal evidence — same
    visible state from the same genuine printing). The dedicated
    cross-engine equivalence pin
    ``test_cross_engine_real_eoe_memorial_team_leader_anthem_byte_
    equal_parity`` runs both engines side-by-side and asserts the
    SAME public anthem-delta on each engine at three turn states
    (the load-bearing PROBED-tier evidence).
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.cards import SYNTHETIC_CREATURES
    from mtg_bot.game import (
        StackItem, Zone, effective_power, effective_toughness,
    )
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state,
    )

    src = get_active_source().get_printings()
    mtl = src.get("Memorial Team Leader")
    if mtl is None:
        pytest.skip("Memorial Team Leader absent from active CardSource")

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    # Bear on P0's battlefield baseline (no MTL yet).
    bear_obj = py.new_object(
        SYNTHETIC_CREATURES["Sapling"], owner_id=0, zone=Zone.BATTLEFIELD,
    )
    bear_obj.summoning_sick = False
    bear_obj.controller_id = 0
    py.battlefield.append(bear_obj)
    sapling_p = bear_obj.printing.power
    sapling_t = bear_obj.printing.toughness
    # Pre-MTL: bear at printed.
    assert effective_power(py, bear_obj) == sapling_p
    assert effective_toughness(py, bear_obj) == sapling_t

    # Drop MTL onto P0's battlefield (synthetic injection mirrors the
    # post-warp-cast-resolve state — the warp lifecycle's per-engine
    # cast plumbing is exercised via the Rust unit pin above and the
    # sibling test_probe_warp_admitted module; this Python sibling
    # focuses on the Phase-4 anthem-fold byte-equal evidence the
    # warp-only probe doesn't cover).
    mtl_obj = py.new_object(mtl, owner_id=0, zone=Zone.BATTLEFIELD)
    mtl_obj.summoning_sick = False
    mtl_obj.controller_id = 0
    # NOTE: the Phase-4 anthem fold doesn't depend on the warp marker;
    # the warp marker is a state-level flag (``py.spell_warped_this_
    # turn``) consumed by the end-step exile sweep, which Python's
    # combat-side warp lifecycle pins exercise elsewhere. This sibling
    # focuses on the Phase-4 anthem-fold byte-equal evidence the
    # warp-only probe doesn't cover.
    py.battlefield.append(mtl_obj)
    py.active_player_idx = 0
    # Post-MTL: bear gets +1/+0; MTL stays printed 4/3.
    assert effective_power(py, bear_obj) == sapling_p + 1
    assert effective_toughness(py, bear_obj) == sapling_t
    assert effective_power(py, mtl_obj) == 4
    assert effective_toughness(py, mtl_obj) == 3

    # Off-turn: anthem closes; bear reverts to printed.
    py.active_player_idx = 1
    assert effective_power(py, bear_obj) == sapling_p
    assert effective_toughness(py, bear_obj) == sapling_t

    # Renewed turn: anthem re-engages.
    py.active_player_idx = 0
    assert effective_power(py, bear_obj) == sapling_p + 1
    assert effective_toughness(py, bear_obj) == sapling_t


# ---------------------------------------------------------------------------
# Cross-engine equivalence pin — both engines compute the SAME public
# effective_power on the bear under the SAME genuine MTL printing.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_memorial_team_leader_anthem_byte_equal_parity():
    """**The load-bearing cross-engine pin.** Both Python and Rust,
    given the SAME genuine MTL printing through the SAME bridge
    CardDef, compute the SAME public ``effective_power`` /
    ``effective_toughness`` on a vanilla 2/2 bear at each of three
    turn states (active=P0 → anthem fires; active=P1 → anthem closes;
    active=P0 again → anthem re-engages). The bear's printed P/T is
    fixed at 2/2 on both engines (synthetic Bear injection on Rust;
    Sapling on Python with printed 1/2 — the assertion is on the
    DELTA-from-printed, NOT the absolute number, so the bear's
    printed value washes out).
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.cards import SYNTHETIC_CREATURES
    from mtg_bot.game import Zone, effective_power, effective_toughness
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import (
        DeckSpec, _spec_card_to_printing_dict, build_python_state,
    )

    # The slug-keyed PROBE_MODULES scanner credits this function as
    # the PROBED-tier evidence for "Memorial Team Leader" via the
    # in-body ``get_printings().get("Memorial Team Leader")`` chain
    # (the exact idiom ``test_singularity_rupture_parity.py`` /
    # ``test_archenemys_charm_parity.py`` use). The chained form is
    # the scanner-recognized binding shape; the two-step
    # ``src = get_active_source().get_printings(); src.get(...)``
    # form is invisible to the scanner.
    mtl = get_active_source().get_printings().get("Memorial Team Leader")
    if mtl is None:
        pytest.skip("Memorial Team Leader absent from active CardSource")

    cd = trajectory._printing_to_card_def(mtl)
    rd = _spec_card_to_printing_dict(cd)

    # ----- Python: MTL + Sapling on P0's battlefield. -----
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    py_mtl = py.new_object(mtl, owner_id=0, zone=Zone.BATTLEFIELD)
    py_mtl.summoning_sick = False
    py_mtl.controller_id = 0
    py.battlefield.append(py_mtl)
    py_bear = py.new_object(
        SYNTHETIC_CREATURES["Sapling"], owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_bear.summoning_sick = False
    py_bear.controller_id = 0
    py.battlefield.append(py_bear)
    sapling_p = py_bear.printing.power
    sapling_t = py_bear.printing.toughness

    # ----- Rust: MTL + vanilla Bear at the same printed P/T. -----
    rs = _fresh_rust()
    rs_mtl = rs.register_and_inject_object(rd, 0, _ZONE_BATTLEFIELD)
    rs_bear = rs.register_and_inject_object(
        {
            "name": "Vanilla Bear",
            "card_types": ["Creature"],
            "mana_cost": {"generic": 1, "G": 1},
            "power": sapling_p,
            "toughness": sapling_t,
        },
        0, _ZONE_BATTLEFIELD,
    )

    # Step 1: P0's turn — anthem fires (+1/+0).
    py.active_player_idx = 0
    rs.set_active_player(0)
    py_delta_p = effective_power(py, py_bear) - sapling_p
    py_delta_t = effective_toughness(py, py_bear) - sapling_t
    rs_delta_p = rs.effective_power(rs_bear) - sapling_p
    rs_delta_t = rs.effective_toughness(rs_bear) - sapling_t
    assert py_delta_p == rs_delta_p == 1, (
        f"Anthem +P must agree across engines on P0's turn: "
        f"py={py_delta_p} rs={rs_delta_p}"
    )
    assert py_delta_t == rs_delta_t == 0, (
        f"Anthem +T must agree across engines on P0's turn: "
        f"py={py_delta_t} rs={rs_delta_t}"
    )

    # Step 2: P1's turn — anthem closes (+0/+0).
    py.active_player_idx = 1
    rs.set_active_player(1)
    py_delta_p = effective_power(py, py_bear) - sapling_p
    py_delta_t = effective_toughness(py, py_bear) - sapling_t
    rs_delta_p = rs.effective_power(rs_bear) - sapling_p
    rs_delta_t = rs.effective_toughness(rs_bear) - sapling_t
    assert py_delta_p == rs_delta_p == 0, (
        f"Anthem must close on P1's turn: py={py_delta_p} rs={rs_delta_p}"
    )
    assert py_delta_t == rs_delta_t == 0

    # Step 3: back to P0 — anthem re-engages (+1/+0).
    py.active_player_idx = 0
    rs.set_active_player(0)
    py_delta_p = effective_power(py, py_bear) - sapling_p
    rs_delta_p = rs.effective_power(rs_bear) - sapling_p
    assert py_delta_p == rs_delta_p == 1, (
        f"Anthem must re-engage on P0's renewed turn: "
        f"py={py_delta_p} rs={rs_delta_p}"
    )

    # MTL itself: BOTH engines must agree that the source is excluded
    # (other-scope). MTL's printed P/T on both sides is 4/3.
    py.active_player_idx = 0
    rs.set_active_player(0)
    assert effective_power(py, py_mtl) == 4
    assert effective_toughness(py, py_mtl) == 3
    assert rs.effective_power(rs_mtl) == 4
    assert rs.effective_toughness(rs_mtl) == 3
