"""Sliver Overlord -- per-card real-EoE cross-engine byte-equal probe
(THE FLIP; BLOCKED -> PROBED).

**FLIP landing (2026-05-31).** Sliver Overlord is a Legendary Creature
-- Sliver Mutant (7/7) in the EoE special-guests pool with TWO
Carrier-AAs, both ``{3}`` no-tap:

    AA[0] -- ``{3}: Search your library for a Sliver card, reveal that
             card, put it into your hand, then shuffle.``
        cost   = ActivationCost(mana={3}, tap_self=False)
        effect = SearchLibraryForCard(filter_name="sliver", max_mv=0,
                                      may_fail=True)
    AA[1] -- ``{3}: Gain control of target Sliver. (This effect lasts
             indefinitely.)``
        cost   = ActivationCost(mana={3}, tap_self=False)
        effect = GainControlOfTargetSliverPermanently()

**Verify-first findings (the FOUR walls).** Confirmed by dumping the
actual parsed printing:

  1. **AA[0] is already covered.** ``SearchLibraryForCard`` with the
     ``"sliver"`` filter has a Rust ``Effect::SearchLibraryForCard``
     variant + parse + resolve (the ``"sliver"`` subtype-filter arm at
     ``state_ops_resolve.rs:15231``) + cross-engine bridge arms ON MAIN
     since round-21/Phase-4D-C2. No new Rust work for AA[0].
  2. **AA[1] needed a new Rust Effect.**
     ``GainControlOfTargetSliverPermanently`` had a Python class but NO
     Rust variant. This slice ships the new
     ``Effect::GainControlOfTargetSliverPermanently`` unit variant +
     parse + to_pydict + valid-kinds + Sliver-creature target fan-out in
     ``state_ops_legal.rs`` (BOTH bfs, ANY controller, printed-Creature
     + Sliver-subtype) + apply-time validation in
     ``state_ops_actions.rs`` + a DIRECT-permanent-controller-write
     resolve arm in ``state_ops_resolve.rs`` + cross-engine forward /
     reverse bridge arms + the trajectory reverse-serializer leaf. The
     direct-write mechanic is the SAME one Contested War Zone's
     ``ChangeControllerToCombatDamageSource`` (merge ``66fd21fd``)
     proved byte-equal -- the only new dimension is the TARGET (a Sliver
     creature on either bf) vs. that effect's source-self write.
  3. **No-tap mana cost-gate wall.** Both AAs are ``{3}`` with
     ``tap_self=False`` -- the FIRST non-tap Carrier-AA cost shape. The
     per-AA admit predicate ``_aa_is_phase1_sub_shape_a`` was widened to
     admit a pure generic-mana no-tap cost (the Rust legal-emit gate
     handles ``tap_self=False`` natively; the AA cost serializer omits
     the ``tap_self`` key when False -- ZERO new Rust cost-shape
     machinery).
  4. **Creature-carrier admit wall.** No Carrier-AA Creature admit
     predicate existed (only Land + Artifact). This slice adds
     ``_printing_is_bridge_simple_carrier_aa_creature`` +
     ``_carrier_aa_creature_card_def`` (threads the printed P/T +
     Legendary supertype + Sliver/Mutant subtypes into the CardDef) and
     wires both into the ``_any`` dispatcher + the OR-chain.

With all four walls closed, Sliver Overlord FLIPS BLOCKED -> PROBED.

The byte-equal observable is the TARGET Sliver's ``controller_id``: p0
activates Sliver Overlord's AA[1] targeting a Sliver controlled by p1,
and the target permanently becomes p0's. The control change rides the
same DIRECT-write path (NO ``controller_override`` UEOT stamp) as
Contested War Zone.

Scenarios:
  * **GAIN.** p1's Sliver -> p0 activates AA[1] targeting it -> the
    Sliver's controller flips 1 -> 0 byte-equal both engines, no UEOT
    override.
  * **SELF-NO-OP.** p0 targets a Sliver it already controls -> silent
    no-op (controller unchanged) byte-equal.
"""

from __future__ import annotations

import importlib.util

import pytest

from mtg_bot.cards.source import get_active_source


_PRINTINGS = get_active_source().get_printings()


_rust_skip = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


# Zone constants (Rust int encoding).
ZONE_HAND = 0
ZONE_BATTLEFIELD = 2


# A plain Sliver creature target (printed Creature carrying the "Sliver"
# subtype). Used as the control-change target on both engines.
_RUST_SLIVER = {
    "name": "Plain Sliver",
    "card_types": ["Creature"],
    "subtypes": ["Sliver"],
    "mana_cost": {"generic": 1},
    "power": 1,
    "toughness": 1,
}

# A non-Sliver creature (printed Creature, no Sliver subtype) -- the
# negative target the fan-out + validator must REJECT.
_RUST_NON_SLIVER = {
    "name": "Plain Bear",
    "card_types": ["Creature"],
    "mana_cost": {"generic": 1},
    "power": 2,
    "toughness": 2,
}

# The REAL parsed Sliver Overlord shape on Rust: a Legendary Creature --
# Sliver Mutant (7/7) carrying its two ``{3}`` no-tap AAs. Mirrors the
# live ``_carrier_aa_creature_card_def(printing)`` output.
_RUST_SLIVER_OVERLORD_DICT = {
    "name": "Sliver Overlord",
    "card_types": ["Creature"],
    "supertypes": ["Legendary"],
    "subtypes": ["Sliver", "Mutant"],
    "mana_cost": {"W": 1, "U": 1, "B": 1, "R": 1, "G": 1},
    "power": 7,
    "toughness": 7,
    "effects": [],
    "activated_abilities": [
        {
            "cost": {"mana": {"generic": 3}},
            "effect": {
                "kind": "search_library_for_card",
                "filter_name": "sliver",
                "max_mv": 0,
                "may_fail": True,
            },
            "is_mana_ability": False,
        },
        {
            "cost": {"mana": {"generic": 3}},
            "effect": {
                "kind": "gain_control_of_target_sliver_permanently",
            },
            "is_mana_ability": False,
        },
    ],
}


# ---------------------------------------------------------------------------
# (1) Parser SoT -- verify-first: Sliver Overlord's parsed shape.
# ---------------------------------------------------------------------------


def test_sliver_overlord_parser_claims_card():
    assert "Sliver Overlord" in _PRINTINGS, (
        "Sliver Overlord must be parser-claimed by the active CardSource"
    )


def test_sliver_overlord_printed_attrs():
    """Pins Sliver Overlord's parsed surface: Legendary Creature (7/7,
    Sliver Mutant), no keywords/triggers/statics, TWO ``{3}`` no-tap AAs
    carrying ``SearchLibraryForCard(filter="sliver")`` +
    ``GainControlOfTargetSliverPermanently()``.
    """
    from mtg_bot.effects.generic.control import (
        GainControlOfTargetSliverPermanently,
    )
    from mtg_bot.effects.generic.search import SearchLibraryForCard

    p = _PRINTINGS["Sliver Overlord"]
    assert p.card_types == ("Creature",)
    assert p.supertypes == ("Legendary",)
    assert "Sliver" in p.subtypes
    assert p.power == 7 and p.toughness == 7
    assert p.keywords == frozenset()
    assert p.triggered_abilities == ()
    assert p.static_abilities == ()
    assert p.spell_effect is None

    assert len(p.activated_abilities) == 2
    aa0, aa1 = p.activated_abilities
    # Both AAs: {3} generic, NO tap.
    for aa in (aa0, aa1):
        assert aa.cost.tap_self is False
        assert aa.cost.mana is not None
        assert aa.cost.mana.generic == 3
        assert aa.cost.mana.colored == ()
        assert aa.cost.mana.hybrid == ()
        assert aa.cost.mana.x_pips == 0
        assert aa.cost.sacrifice_self is False
    assert isinstance(aa0.effect, SearchLibraryForCard)
    assert aa0.effect.filter_name == "sliver"
    assert isinstance(aa1.effect, GainControlOfTargetSliverPermanently)
    assert aa1.effect.requires_target() is True


# ---------------------------------------------------------------------------
# (2) LOAD-BEARING FLIP invariant: Sliver Overlord now ADMITS at the
# loader admit gate (the four walls closed). This is the PROBED-tier flip
# marker.
# ---------------------------------------------------------------------------


def test_sliver_overlord_now_admits_at_loader_admit_gate():
    """**The FLIP invariant.** Sliver Overlord must ADMIT end-to-end:
      * Both AAs pass the per-AA predicate ``_aa_is_phase1_sub_shape_a``
        (no-tap {3} cost gate + both Effect classes in the admit set).
      * The Creature-carrier predicate
        ``_printing_is_bridge_simple_carrier_aa_creature`` accepts.
      * The ``_any`` dispatcher + ``_filter_deck_to_bridge_supported``
        admit Sliver Overlord.
    """
    from mtg_bot.parity.trajectory import (
        _aa_is_phase1_sub_shape_a,
        _carrier_aa_effect_class_admitted,
        _filter_deck_to_bridge_supported,
        _printing_is_bridge_simple_carrier_aa_any,
        _printing_is_bridge_simple_carrier_aa_creature,
    )

    p = _PRINTINGS["Sliver Overlord"]

    # Both AAs admit at the per-AA gate.
    for aa in p.activated_abilities:
        assert _carrier_aa_effect_class_admitted(aa.effect) is True
        assert _aa_is_phase1_sub_shape_a(aa) is True

    # Creature-carrier + Any printing predicates admit.
    assert _printing_is_bridge_simple_carrier_aa_creature(p) is True
    assert _printing_is_bridge_simple_carrier_aa_any(p) is True

    # End-to-end loader: Sliver Overlord is ADMITTED.
    filt, defs = _filter_deck_to_bridge_supported(
        ["Sliver Overlord"], _PRINTINGS,
    )
    assert filt == ["Sliver Overlord"], (
        f"Sliver Overlord must ADMIT at the loader admit gate (the FLIP). "
        f"Got filt={filt!r}"
    )
    assert len(defs) == 1


# ---------------------------------------------------------------------------
# (3) Bridge round-trip -- forward (AA -> dict) emits the gain-control AA
# shape; reverse (dict -> Python effect) rehydrates byte-equal.
# ---------------------------------------------------------------------------


def test_sliver_overlord_bridge_forward_arm_emits_both_aa_dicts():
    """The forward floor ``_python_aa_to_safe_dict`` emits dicts for BOTH
    of Sliver Overlord's AAs (the no-tap {3} cost serializes cleanly -- a
    bare ``{"mana": {"generic": 3}}`` with NO ``tap_self`` key)."""
    from mtg_bot.parity.cross_engine import _python_aa_to_safe_dict

    p = _PRINTINGS["Sliver Overlord"]
    aa0, aa1 = p.activated_abilities

    d0 = _python_aa_to_safe_dict(aa0)
    assert d0 is not None
    assert d0["cost"] == {"mana": {"generic": 3}}
    assert "tap_self" not in d0["cost"]
    assert d0["effect"]["kind"] == "search_library_for_card"
    assert d0["effect"]["filter_name"] == "sliver"

    d1 = _python_aa_to_safe_dict(aa1)
    assert d1 is not None
    assert d1["cost"] == {"mana": {"generic": 3}}
    assert "tap_self" not in d1["cost"]
    assert d1["effect"] == {
        "kind": "gain_control_of_target_sliver_permanently",
    }


def test_gain_control_bridge_reverse_arm():
    """``_ta_dict_to_python_effect({"kind":
    "gain_control_of_target_sliver_permanently"})`` ->
    Python ``GainControlOfTargetSliverPermanently()``.
    """
    from mtg_bot.effects.generic.control import (
        GainControlOfTargetSliverPermanently,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    eff = _ta_dict_to_python_effect(
        {"kind": "gain_control_of_target_sliver_permanently"}
    )
    assert isinstance(eff, GainControlOfTargetSliverPermanently)
    assert eff == GainControlOfTargetSliverPermanently()


def test_gain_control_serializer_round_trip():
    """The trajectory reverse-serializer leaf emits the bare unit dict
    for ``GainControlOfTargetSliverPermanently`` (the Rust ``to_pydict``
    mirror).
    """
    from mtg_bot.effects.generic.control import (
        GainControlOfTargetSliverPermanently,
    )
    from mtg_bot.parity.trajectory import _python_spell_effect_to_dict

    d = _python_spell_effect_to_dict(GainControlOfTargetSliverPermanently())
    assert d == {"kind": "gain_control_of_target_sliver_permanently"}


# ---------------------------------------------------------------------------
# (4) Rust acceptance smoke -- the real Sliver Overlord dict parses on
# ``register_printing`` (both AAs round-trip).
# ---------------------------------------------------------------------------


@_rust_skip
def test_rust_parser_accepts_sliver_overlord_dict():
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(_RUST_SLIVER_OVERLORD_DICT)
    assert isinstance(pid, int)
    assert reg.get_printing_name(pid) == "Sliver Overlord"


# ---------------------------------------------------------------------------
# Python-side harness -- Sliver Overlord on p0's bf + a target Sliver
# (controlled by ``sliver_controller``) on the relevant bf, 3 floating
# {C} coins in p0's pool to pay the AA's {3}. Returns
# ``(state, overlord, sliver)``.
# ---------------------------------------------------------------------------


class _ScriptedTargetAgent:
    """Minimal agent returning a pre-scripted sequence of target picks
    (one per ``choose_target`` call). Drives Python's
    ``_activate_ability`` single-target picker to the SAME Sliver id the
    Rust ``apply_action`` carries explicitly."""

    def __init__(self, picks):
        self._picks = list(picks)
        self._i = 0

    def choose_target(self, state, player_id, legal_targets):
        pick = self._picks[self._i]
        self._i += 1
        assert pick in legal_targets, (
            f"scripted pick {pick!r} not in legal_targets {legal_targets!r}"
        )
        return pick


def _build_python_aa_state(sliver_controller: int):
    """Seat the REAL parsed Sliver Overlord on p0's bf + a target Sliver
    creature controlled by ``sliver_controller``, 3 floating {C} coins in
    p0's pool to pay the AA's {3}. A scripted agent picks the Sliver.
    Returns ``(state, overlord, sliver)``.
    """
    from mtg_bot.cards import SYNTHETIC_CREATURES
    from mtg_bot.game import GameState, ManaCoin, Player, Zone
    from mtg_bot.turn import Step

    so_printing = _PRINTINGS["Sliver Overlord"]

    state = GameState()
    state.players.append(Player(id=0, agent=None))
    state.players.append(Player(id=1, agent=None))
    state.active_player_idx = 0
    state.priority_player_idx = 0
    state.step = Step.PRECOMBAT_MAIN

    overlord = state.new_object(so_printing, 0, Zone.BATTLEFIELD)
    overlord.controller_id = 0
    overlord.summoning_sick = False
    state.battlefield.append(overlord)

    # A plain Sliver creature target. Build a synthetic printing carrying
    # the Sliver subtype by reusing a synthetic creature + overriding.
    sliver = _make_python_sliver(state, sliver_controller)

    # 3 floating {C} to pay the AA's {3} generic cost.
    for _ in range(3):
        state.players[0].mana_pool.append(ManaCoin("C"))
    # Scripted agent picks the Sliver.
    state.players[0].agent = _ScriptedTargetAgent([
        ("creature", sliver.id),
    ])
    return state, overlord, sliver


def _make_python_sliver(state, controller_id: int):
    """Build a plain Sliver creature permanent on ``controller_id``'s bf.
    Reuses a synthetic creature printing but forces a Sliver subtype via a
    lightweight printing clone so the legal-target filter + resolve arm's
    subtype check see "Sliver"."""
    import dataclasses

    from mtg_bot.cards import SYNTHETIC_CREATURES
    from mtg_bot.game import Zone

    base = SYNTHETIC_CREATURES[list(SYNTHETIC_CREATURES)[0]]
    # Clone the printing with subtypes = ("Sliver",) so
    # effective_subtypes(state, obj) reports "Sliver".
    sliver_printing = dataclasses.replace(base, name="Plain Sliver",
                                          subtypes=("Sliver",))
    obj = state.new_object(sliver_printing, controller_id, Zone.BATTLEFIELD)
    obj.controller_id = controller_id
    state.battlefield.append(obj)
    return obj


def _py_controller(state, obj_id):
    return next(
        o for o in state.battlefield if o.id == obj_id
    ).controller_id


def _build_rust_aa_state(sliver_controller: int):
    """Mirror of ``_build_python_aa_state`` on Rust: the REAL Sliver
    Overlord dict on p0's bf + a target Sliver controlled by
    ``sliver_controller``, 3 floating {C} coins to pay the {3}. Returns
    ``(rs, overlord, sliver)``.
    """
    import mtg_bot_engine

    rs = mtg_bot_engine.make_synthetic_state(0, 0, 0)
    overlord = rs.register_and_inject_object(
        _RUST_SLIVER_OVERLORD_DICT, 0, ZONE_BATTLEFIELD,
    )
    rs.force_set_summoning_sick(overlord, False)
    sliver = rs.register_and_inject_object(
        _RUST_SLIVER, sliver_controller, ZONE_BATTLEFIELD,
    )
    rs.add_mana(0, "C", 3)
    return rs, overlord, sliver


# ---------------------------------------------------------------------------
# (5) THE FLIP PROBE -- GENUINE real-EoE cross-engine byte-equal probe
# driving the ACTUAL parsed Sliver Overlord AA[1] (gain control of target
# Sliver) via the AA-ACTIVATION path on BOTH engines.
# ---------------------------------------------------------------------------


@_rust_skip
def test_cross_engine_real_eoe_sliver_overlord_gain_control_parity():
    """**THE FLIP PROBE -- GENUINE real-EoE AA-activation byte-equal.**
    p0 activates Sliver Overlord's AA[1] (``{3}: Gain control of target
    Sliver.``) targeting a Sliver controlled by p1. The Sliver's
    controller flips 1 -> 0 via a DIRECT permanent write (NO UEOT
    ``controller_override`` stamp), byte-equal both engines.
    """
    so_printing = _PRINTINGS.get("Sliver Overlord")
    if so_printing is None:
        pytest.skip("Sliver Overlord absent from active CardSource")

    from mtg_bot.actions import (
        ActivateAbility,
        apply_action,
        resolve_top_of_stack,
    )

    # ---- Python: real-EoE AA activation, target = p1's Sliver.
    py, py_overlord, py_sliver = _build_python_aa_state(sliver_controller=1)
    assert _py_controller(py, py_sliver.id) == 1
    apply_action(
        py, 0, ActivateAbility(source_id=py_overlord.id, ability_index=1),
    )
    assert len(py.stack) == 1, (
        "Python: the non-mana AA must push exactly one stack item"
    )
    while py.stack:
        resolve_top_of_stack(py)
    py_controller = _py_controller(py, py_sliver.id)
    assert py_controller == 0, (
        f"Python: p0 gains control of the target Sliver (1 -> 0); "
        f"got controller={py_controller}"
    )

    # ---- Rust: real AA activation with the target seated.
    rs, rs_overlord, rs_sliver = _build_rust_aa_state(sliver_controller=1)
    rs_before = next(
        e for e in rs.battlefield_snapshot() if e["id"] == rs_sliver
    )
    assert rs_before["controller_id"] == 1
    rs.apply_action(
        {
            "kind": "activate_ability",
            "source_id": rs_overlord,
            "ability_index": 1,
            "target_creature_id": rs_sliver,
        }
    )
    assert rs.stack_size() == 1, (
        "Rust: the non-mana AA must push exactly one stack item"
    )
    rs.resolve_top_of_stack()
    rs_after = next(
        e for e in rs.battlefield_snapshot() if e["id"] == rs_sliver
    )
    assert rs_after["controller_id"] == 0, (
        f"Rust: p0 gains control of the target Sliver (1 -> 0); "
        f"got controller={rs_after['controller_id']}"
    )
    assert rs_after["controller_override"] is None, (
        "permanent direct control change must NOT stamp the UEOT "
        "controller_override field"
    )

    # ---- Cross-engine byte-equal on the target's controller.
    assert py_controller == rs_after["controller_id"], (
        f"Cross-engine byte-equal (gain-control): py={py_controller}, "
        f"rs={rs_after['controller_id']}"
    )


@_rust_skip
def test_cross_engine_real_eoe_sliver_overlord_self_noop_parity():
    """**SELF-NO-OP byte-equal.** p0 targets a Sliver it ALREADY controls
    -> silent no-op (mirrors Python's ``if obj.controller_id ==
    controller_id`` early return). Controller unchanged (0) byte-equal,
    no UEOT override.
    """
    so_printing = _PRINTINGS.get("Sliver Overlord")
    if so_printing is None:
        pytest.skip("Sliver Overlord absent from active CardSource")

    from mtg_bot.actions import (
        ActivateAbility,
        apply_action,
        resolve_top_of_stack,
    )

    # ---- Python: target a p0-controlled Sliver.
    py, py_overlord, py_sliver = _build_python_aa_state(sliver_controller=0)
    apply_action(
        py, 0, ActivateAbility(source_id=py_overlord.id, ability_index=1),
    )
    while py.stack:
        resolve_top_of_stack(py)
    py_controller = _py_controller(py, py_sliver.id)
    assert py_controller == 0, (
        f"Python self-no-op: controller stays 0; got {py_controller}"
    )

    # ---- Rust: target a p0-controlled Sliver.
    rs, rs_overlord, rs_sliver = _build_rust_aa_state(sliver_controller=0)
    rs.apply_action(
        {
            "kind": "activate_ability",
            "source_id": rs_overlord,
            "ability_index": 1,
            "target_creature_id": rs_sliver,
        }
    )
    rs.resolve_top_of_stack()
    rs_after = next(
        e for e in rs.battlefield_snapshot() if e["id"] == rs_sliver
    )
    assert rs_after["controller_id"] == 0, (
        f"Rust self-no-op: controller stays 0; got "
        f"{rs_after['controller_id']}"
    )
    assert rs_after["controller_override"] is None

    assert py_controller == rs_after["controller_id"], (
        f"Cross-engine byte-equal (self-no-op): py={py_controller}, "
        f"rs={rs_after['controller_id']}"
    )
