"""Nesting Grounds -- per-card real-EoE cross-engine byte-equal probe
(SUBSTRATE-ONLY landing; ``BLOCKED-SG -> covered_by_construction``;
composite-admit wall honest-stop, NOT a PROBED flip).

Nesting Grounds is a plain Land in the EoE pool with ONE Carrier-AA:

    AA[0] -- ``{1}, {T}: Move a counter from target permanent you
             control onto a second target permanent. Activate only as a
             sorcery.``
        cost   = ActivationCost(mana={1}, tap_self=True)
        effect = MovePlusOneCounterBetweenPermanentsYouControl()
        is_mana_ability = False
        sorcery_speed   = True

**Verify-first finding (the WALL).** Nesting Grounds is a CLEAN single-
AA Land carrier: the per-AA admit predicate
``_aa_is_phase1_sub_shape_a`` accepts the ``{1}{T}`` generic-only-mana
cost (the Phase-1.5a ``{N}, {T}`` widen), the ``sorcery_speed=True``
rider (Phase 4C C2 widen), and ``is_mana_ability=False``; the Land-
carrier bridge ``_printing_is_bridge_simple_carrier_aa_land`` accepts
the printing -- BOTH return True once the Effect class is added to
``_carrier_aa_phase_1_effect_classes`` (neither gates on target count).

UNLIKE Lotus Field's composite keyword/trigger wall, the ONLY thing
keeping Nesting Grounds declined is the dual-target activation gap:
``MovePlusOneCounterBetweenPermanentsYouControl`` is a 2-target effect
(``target_count_range() == (2, 2)`` -- donor + recipient permanents you
control). The Rust Carrier-AA activation path
(``state_ops_actions.rs::ActivateAbility`` -> ``new_trigger_with_
target``) binds AT MOST ONE target via the single ``target_creature_id``
slot (-> ``current_resolve_payload_target_id``). The 2nd payload slot
(``current_resolve_payload_target_id_2``) is set ONLY by the spell-cast
StackItem path (Coordinated Clobbering / Diplomatic Relations), never
the AA path. Python's ``_activate_ability`` DOES drive multi-target AAs
(``actions.py:2009`` explicitly mentions Nesting Grounds). So a loader-
admit FLIP cannot be proven byte-equal cross-engine: Rust cannot carry
the recipient through AA activation.

**Substrate-only landing.** The Rust Effect substrate
(``Effect::MovePlusOneCounterBetweenPermanentsYouControl`` unit variant
+ parse + to_pydict + dual-target resolve via the ``_2`` payload slot +
cross-engine bridge forward + reverse arms) lands so a future AA-
activation 2nd-target slot ships the FLIP cheaply. The Effect class is
NOT added to ``_carrier_aa_phase_1_effect_classes`` this cycle (the
substrate-only invariant); Nesting Grounds STAYS DECLINED at the loader
admit gate. The resolve arm + bridge round-trip are exercised by the
tests_rust unit pins
(``tests_rust/test_move_plus_one_counter_between_permanents_you_
control.py``) PLUS the cross-engine byte-equal MOVE probe below, which
drives the resolve arm DIRECTLY with both payload slots seated (the
synthetic-spell idiom -- ``MovePlusOneCounterBetweenPermanentsYouControl
().resolve(state, 0, (donor, recipient))`` on Python; the matching
``push_to_stack_with_three_targets`` + ``resolve_top_of_stack`` on
Rust).

See ``docs/SEARCH_LIMITATIONS.md`` for the composite-admit wall entry.

Scenarios:
  * **MOVE.** Donor with 2 counters -> recipient with 0; one counter
    moves (donor 2 -> 1, recipient 0 -> 1) byte-equal both engines.
  * **FIZZLE.** Donor with 0 counters -> the ability fizzles; neither
    permanent's count changes byte-equal both engines.
  * **MULTI.** Donor with 3 counters -> recipient with 0; exactly ONE
    counter moves (donor 3 -> 2, recipient 0 -> 1) byte-equal.
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


# Canonical Rust synthetic dict. A Sorcery carrying the bare
# ``move_plus_one_counter_between_permanents_you_control`` leaf as its
# spell body so the Rust harness can drive the dual-target resolve via
# ``push_to_stack_with_three_targets`` + ``resolve_top_of_stack`` (the
# 2-slot payload plumbing the AA-activation path can't reach). The spell-
# resolve path seats BOTH ``current_resolve_payload_target_id`` (slot 0)
# and ``_2`` (slot 1) from the StackItem -- byte-equal to Python's
# ``StackItem.targets`` / direct ``.resolve(state, 0, (donor,
# recipient))`` invocation.
_RUST_MOVE_SPELL_DICT = {
    "name": "Nesting Grounds (move-counter synthetic)",
    "card_types": ["Sorcery"],
    "mana_cost": {"generic": 1},
    "effects": [
        {"kind": "move_plus_one_counter_between_permanents_you_control"},
    ],
}

_RUST_PERMANENT = {
    "name": "Plain Permanent",
    "card_types": ["Creature"],
    "mana_cost": {"generic": 1},
    "power": 1,
    "toughness": 1,
}


# ---------------------------------------------------------------------------
# (1) Parser SoT -- verify-first: Nesting Grounds' parsed shape (the §2
# teeth the substrate + the loader-decline both depend on).
# ---------------------------------------------------------------------------


def test_nesting_grounds_parser_claims_card():
    assert "Nesting Grounds" in _PRINTINGS, (
        "Nesting Grounds must be parser-claimed by the active CardSource"
    )


def test_nesting_grounds_printed_attrs():
    """Pins Nesting Grounds' parsed surface: bare Land, ``{0}`` cost, no
    keywords/triggers/statics, ONE non-mana ``{1}{T}`` sorcery-speed AA
    carrying ``MovePlusOneCounterBetweenPermanentsYouControl()`` whose
    ``target_count_range() == (2, 2)`` (the dual-target teeth that wall
    the FLIP).
    """
    from mtg_bot.effects.generic.counters import (
        MovePlusOneCounterBetweenPermanentsYouControl,
    )

    p = _PRINTINGS["Nesting Grounds"]
    assert p.card_types == ("Land",)
    assert p.subtypes == ()
    assert p.supertypes == ()
    assert p.power is None and p.toughness is None
    assert p.mana_cost.generic == 0
    assert p.mana_cost.colored == ()
    assert p.keywords == frozenset()
    assert p.triggered_abilities == ()
    assert p.static_abilities == ()
    assert p.spell_effect is None

    assert len(p.activated_abilities) == 1
    aa = p.activated_abilities[0]
    # Cost: {1} generic + tap_self ({1}{T}); no other cost components.
    assert aa.cost.tap_self is True
    assert aa.cost.mana is not None
    assert aa.cost.mana.generic == 1
    assert aa.cost.mana.colored == ()
    assert aa.cost.mana.hybrid == ()
    assert aa.cost.mana.x_pips == 0
    assert aa.cost.sacrifice_self is False
    # Effect + the dual-target teeth.
    assert isinstance(aa.effect, MovePlusOneCounterBetweenPermanentsYouControl)
    assert aa.effect.requires_target() is True
    assert aa.effect.target_count_range() == (2, 2)
    assert aa.is_mana_ability is False
    assert aa.sorcery_speed is True
    assert aa.tier_threshold == 0
    assert aa.activate_only_once is False


# ---------------------------------------------------------------------------
# (2) LOAD-BEARING substrate-only invariant: Nesting Grounds STAYS
# DECLINED at the loader admit gate. The COST + Land-carrier-bridge
# predicates would ACCEPT the printing once the Effect class joins the
# admit set -- but the Effect class is deliberately NOT added this cycle
# (the dual-target AA can't be activated byte-equal; Rust binds one AA
# target). This pin is the composite-admit wall marker.
# ---------------------------------------------------------------------------


def test_nesting_grounds_stays_declined_at_loader_admit_gate():
    """**The substrate-only invariant + the composite-admit wall.**
    Nesting Grounds must DECLINE at the end-to-end loader because the
    Effect class is NOT in the Phase-1 Carrier-AA admit set this cycle.

    Crucially -- and unlike Lotus Field -- the decline is NOT a cost /
    rider / keyword wall: it is ONLY the deliberate effect-class
    omission. We pin BOTH halves:
      * The per-AA admit predicate ``_aa_is_phase1_sub_shape_a`` declines
        SOLELY on the effect-class gate (cost + riders all pass).
      * The end-to-end ``_filter_deck_to_bridge_supported`` filters
        Nesting Grounds OUT.

    A future cycle that adds the effect class to the admit set AND ships
    the 2nd AA-activation target slot will trip this pin -- the author
    must then update it to the PROBED-tier expectation deliberately
    (NOT silently auto-admit a dual-target AA the activation path can't
    drive byte-equal).
    """
    from mtg_bot.parity.trajectory import (
        _aa_is_phase1_sub_shape_a,
        _carrier_aa_effect_class_admitted,
        _filter_deck_to_bridge_supported,
        _printing_is_bridge_simple_carrier_aa_any,
        _printing_is_bridge_simple_carrier_aa_land,
    )

    p = _PRINTINGS["Nesting Grounds"]
    aa = p.activated_abilities[0]

    # The effect-class gate is the SOLE decline reason: the effect class
    # is NOT admitted, so the per-AA predicate declines.
    assert _carrier_aa_effect_class_admitted(aa.effect) is False
    assert _aa_is_phase1_sub_shape_a(aa) is False

    # Carrier-AA Land + Any printing predicates decline (effect-class
    # gated through the per-AA predicate above).
    assert _printing_is_bridge_simple_carrier_aa_land(p) is False
    assert _printing_is_bridge_simple_carrier_aa_any(p) is False

    # End-to-end loader: Nesting Grounds is filtered OUT.
    filt, defs = _filter_deck_to_bridge_supported(
        ["Nesting Grounds"], _PRINTINGS,
    )
    assert filt == [], (
        "Nesting Grounds must STAY DECLINED at the loader admit gate "
        "(substrate-only landing; the dual-target AA can't be activated "
        "byte-equal -- the Rust AA path binds one target). Got "
        "filt={filt!r}".format(filt=filt)
    )
    assert defs == []


def test_nesting_grounds_cost_and_riders_would_admit_if_effect_class_added():
    """**Verify-first composite-wall characterization.** Proves the WALL
    is ONLY the effect-class gate (NOT a cost/rider/keyword wall like
    Lotus Field): temporarily widen the Effect-class admit set with the
    Nesting Grounds effect class and confirm BOTH the per-AA predicate
    AND the Land-carrier bridge would ACCEPT the printing. This is the
    pin that documents *why* the FLIP is cheap once the 2nd AA target
    slot lands -- the cost ({1}{T}) + sorcery_speed rider + Land-carrier
    shape are ALL already accepted.
    """
    import mtg_bot.parity.trajectory as T
    from mtg_bot.effects.generic.counters import (
        MovePlusOneCounterBetweenPermanentsYouControl,
    )

    p = _PRINTINGS["Nesting Grounds"]
    aa = p.activated_abilities[0]

    orig = T._carrier_aa_phase_1_effect_classes
    try:
        T._carrier_aa_phase_1_effect_classes = lambda: (
            orig() | {MovePlusOneCounterBetweenPermanentsYouControl}
        )
        # With ONLY the effect-class widen, the per-AA predicate + the
        # Land-carrier bridge both accept -- proving the cost ({1}{T}) +
        # sorcery_speed rider + Land-carrier shape are NOT walls.
        assert T._aa_is_phase1_sub_shape_a(aa) is True, (
            "the {1}{T} cost + sorcery_speed rider are accepted -- the "
            "ONLY wall is the effect-class gate (and the downstream "
            "dual-target activation gap, which the predicate doesn't see)"
        )
        assert T._printing_is_bridge_simple_carrier_aa_land(p) is True
    finally:
        T._carrier_aa_phase_1_effect_classes = orig


# ---------------------------------------------------------------------------
# (3) Bridge round-trip -- forward (AA -> dict) emits the full AA shape;
# reverse (dict -> Python effect / AA) rehydrates byte-equal at the
# effect level. (``mana_str`` is a cosmetic cost field the AA codec does
# NOT round-trip -- a pre-existing property shared by every admitted
# ``{N}{T}`` carrier, e.g. Deserted Temple; we assert the structural
# cost atoms + the effect, NOT ``mana_str``.)
# ---------------------------------------------------------------------------


def test_nesting_grounds_bridge_forward_arm_emits_full_aa_dict():
    """The forward floor ``_python_aa_to_safe_dict`` now emits the full
    AA dict for Nesting Grounds' AA[0] (cost {1}{T} + the move-counter
    effect + sorcery_speed) -- the substrate landed the forward arm.
    The live admit STILL declines (substrate-only) -- the forward emit
    is exercised here + by the resolve probe, NOT by a loader admit.
    """
    from mtg_bot.parity.cross_engine import _python_aa_to_safe_dict

    p = _PRINTINGS["Nesting Grounds"]
    aa = p.activated_abilities[0]
    d = _python_aa_to_safe_dict(aa)
    assert d is not None, (
        "the forward floor must emit a dict for Nesting Grounds' AA "
        "post-substrate (the move-counter forward arm landed)"
    )
    assert d["cost"] == {"mana": {"generic": 1}, "tap_self": True}
    assert d["effect"] == {
        "kind": "move_plus_one_counter_between_permanents_you_control",
    }
    assert d["sorcery_speed"] is True


def test_move_counter_bridge_reverse_arm():
    """``_ta_dict_to_python_effect({"kind":
    "move_plus_one_counter_between_permanents_you_control"})`` ->
    Python ``MovePlusOneCounterBetweenPermanentsYouControl()``.
    """
    from mtg_bot.effects.generic.counters import (
        MovePlusOneCounterBetweenPermanentsYouControl,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    eff = _ta_dict_to_python_effect(
        {"kind": "move_plus_one_counter_between_permanents_you_control"}
    )
    assert isinstance(eff, MovePlusOneCounterBetweenPermanentsYouControl)
    assert eff == MovePlusOneCounterBetweenPermanentsYouControl()


def test_nesting_grounds_aa_dict_round_trips_at_effect_level():
    """The full AA dict the forward floor emits rehydrates (via
    ``_aa_dict_to_python_activated_ability``) to a Python AA carrying the
    SAME effect class + the SAME structural cost atoms (mana {1} +
    tap_self) + the SAME ``sorcery_speed`` / ``is_mana_ability`` riders.
    ``mana_str`` is the sole non-round-tripped cosmetic field (shared by
    every admitted ``{N}{T}`` carrier -- not specific to this effect).
    """
    from mtg_bot.effects.generic.counters import (
        MovePlusOneCounterBetweenPermanentsYouControl,
    )
    from mtg_bot.parity.cross_engine import (
        _aa_dict_to_python_activated_ability,
        _python_aa_to_safe_dict,
    )

    p = _PRINTINGS["Nesting Grounds"]
    aa = p.activated_abilities[0]
    d = _python_aa_to_safe_dict(aa)
    back = _aa_dict_to_python_activated_ability(d)
    assert isinstance(
        back.effect, MovePlusOneCounterBetweenPermanentsYouControl
    )
    assert back.cost.mana is not None
    assert back.cost.mana.generic == 1
    assert back.cost.tap_self is True
    assert back.cost.sacrifice_self is False
    assert back.is_mana_ability is False
    assert back.sorcery_speed is True
    assert back.tier_threshold == 0
    assert back.activate_only_once is False


# ---------------------------------------------------------------------------
# (4) Rust acceptance smoke -- the synthetic move-counter dict parses on
# ``register_printing``.
# ---------------------------------------------------------------------------


@_rust_skip
def test_rust_parser_accepts_move_counter_dict():
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(_RUST_MOVE_SPELL_DICT)
    assert isinstance(pid, int)
    assert reg.get_printing_name(pid) == (
        "Nesting Grounds (move-counter synthetic)"
    )


# ---------------------------------------------------------------------------
# Python-side harness -- two permanents (donor + recipient) on p0's bf,
# the donor seeded with ``donor_counters`` +1/+1 counters. Returns
# ``(state, donor, recipient)``.
# ---------------------------------------------------------------------------


def _build_python_move_state(donor_counters: int):
    """Two synthetic creature permanents on p0's battlefield; the donor
    seeded with ``donor_counters`` +1/+1 counters. No agent (the resolve
    is target-driven, no agent callback). Returns ``(state, donor,
    recipient)``.
    """
    from mtg_bot.cards import SYNTHETIC_CREATURES
    from mtg_bot.game import GameState, Player, Zone
    from mtg_bot.turn import Step

    state = GameState()
    state.players.append(Player(id=0, agent=None))
    state.players.append(Player(id=1, agent=None))
    state.active_player_idx = 0
    state.priority_player_idx = 0
    state.step = Step.PRECOMBAT_MAIN

    names = list(SYNTHETIC_CREATURES)[:2]
    donor = state.new_object(
        SYNTHETIC_CREATURES[names[0]], 0, Zone.BATTLEFIELD,
    )
    donor.controller_id = 0
    state.battlefield.append(donor)
    recipient = state.new_object(
        SYNTHETIC_CREATURES[names[1]], 0, Zone.BATTLEFIELD,
    )
    recipient.controller_id = 0
    state.battlefield.append(recipient)
    donor.plus_one_counters = donor_counters
    return state, donor, recipient


def _py_counters(state, obj_id):
    return next(o for o in state.battlefield if o.id == obj_id).plus_one_counters


def _build_rust_move_state(donor_counters: int):
    """Mirror of ``_build_python_move_state`` on the Rust engine. Two
    creature permanents on p0's bf (donor seeded with ``donor_counters``
    counters) + the move-counter synthetic Sorcery on p0's hand. Returns
    ``(rs, donor_id, recipient_id, spell_id)``.
    """
    import mtg_bot_engine

    rs = mtg_bot_engine.make_synthetic_state(0, 0, 0)
    donor = rs.register_and_inject_object(_RUST_PERMANENT, 0, ZONE_BATTLEFIELD)
    recipient = rs.register_and_inject_object(
        _RUST_PERMANENT, 0, ZONE_BATTLEFIELD,
    )
    assert rs.set_counters(donor, donor_counters) is True
    spell = rs.register_and_inject_object(
        _RUST_MOVE_SPELL_DICT, 0, ZONE_HAND,
    )
    return rs, donor, recipient, spell


# ---------------------------------------------------------------------------
# (5) MOVE -- the NEW Effect end-to-end byte-equal. Real-EoE effect-level
# resolve on Python (the exact effect the parsed Nesting Grounds AA[0]
# carries) vs the bridged synthetic on Rust. Both move exactly one
# counter donor -> recipient.
# ---------------------------------------------------------------------------


@_rust_skip
def test_cross_engine_real_eoe_nesting_grounds_move_parity():
    """**GENUINE real-EoE cross-engine probe -- MOVE.** The exact Effect
    the parsed Nesting Grounds AA[0] carries
    (``MovePlusOneCounterBetweenPermanentsYouControl``) resolves with
    (donor, recipient) targets on Python; the bridged synthetic resolves
    on Rust via the 2-slot payload plumbing. Both move exactly one
    counter (donor 2 -> 1, recipient 0 -> 1). Byte-equal on the
    (donor_counters, recipient_counters) pair.
    """
    from mtg_bot.effects.generic.counters import (
        MovePlusOneCounterBetweenPermanentsYouControl,
    )

    # ---- Python: real-EoE effect resolve with both targets.
    py, donor, recipient = _build_python_move_state(2)
    MovePlusOneCounterBetweenPermanentsYouControl().resolve(
        py, 0, (("permanent", donor.id), ("permanent", recipient.id)),
    )
    py_pair = (_py_counters(py, donor.id), _py_counters(py, recipient.id))
    assert py_pair == (1, 1), (
        f"Python: one counter moves donor 2 -> 1, recipient 0 -> 1; "
        f"got {py_pair}"
    )

    # ---- Rust: bridged synthetic, both payload slots seated.
    rs, rs_donor, rs_recipient, rs_spell = _build_rust_move_state(2)
    rs.push_to_stack_with_three_targets(
        rs_spell, 0, rs_donor, rs_recipient, None,
    )
    rs.resolve_top_of_stack()
    rs_pair = (rs.get_counters(rs_donor), rs.get_counters(rs_recipient))
    assert rs_pair == (1, 1), (
        f"Rust: one counter moves donor 2 -> 1, recipient 0 -> 1; "
        f"got {rs_pair}"
    )

    # ---- Cross-engine byte-equal.
    assert py_pair == rs_pair, (
        f"Cross-engine byte-equal (counter pair): py={py_pair}, "
        f"rs={rs_pair}"
    )


@_rust_skip
def test_cross_engine_real_eoe_nesting_grounds_fizzle_parity():
    """**GENUINE real-EoE cross-engine probe -- FIZZLE.** Donor with 0
    counters: the ability fizzles (Python's ``if donor.plus_one_counters
    <= 0: ... return``). Neither permanent's count changes byte-equal.
    """
    from mtg_bot.effects.generic.counters import (
        MovePlusOneCounterBetweenPermanentsYouControl,
    )

    py, donor, recipient = _build_python_move_state(0)
    MovePlusOneCounterBetweenPermanentsYouControl().resolve(
        py, 0, (("permanent", donor.id), ("permanent", recipient.id)),
    )
    py_pair = (_py_counters(py, donor.id), _py_counters(py, recipient.id))
    assert py_pair == (0, 0), f"Python fizzle: no move; got {py_pair}"

    rs, rs_donor, rs_recipient, rs_spell = _build_rust_move_state(0)
    rs.push_to_stack_with_three_targets(
        rs_spell, 0, rs_donor, rs_recipient, None,
    )
    rs.resolve_top_of_stack()
    rs_pair = (rs.get_counters(rs_donor), rs.get_counters(rs_recipient))
    assert rs_pair == (0, 0), f"Rust fizzle: no move; got {rs_pair}"

    assert py_pair == rs_pair, (
        f"Cross-engine byte-equal (fizzle): py={py_pair}, rs={rs_pair}"
    )


@_rust_skip
def test_cross_engine_real_eoe_nesting_grounds_multi_counter_parity():
    """**GENUINE real-EoE cross-engine probe -- MULTI.** Donor with 3
    counters: exactly ONE counter moves (oracle "a counter" -- singular).
    Donor 3 -> 2, recipient 0 -> 1 byte-equal both engines.
    """
    from mtg_bot.effects.generic.counters import (
        MovePlusOneCounterBetweenPermanentsYouControl,
    )

    py, donor, recipient = _build_python_move_state(3)
    MovePlusOneCounterBetweenPermanentsYouControl().resolve(
        py, 0, (("permanent", donor.id), ("permanent", recipient.id)),
    )
    py_pair = (_py_counters(py, donor.id), _py_counters(py, recipient.id))
    assert py_pair == (2, 1), (
        f"Python: exactly one of three counters moves; got {py_pair}"
    )

    rs, rs_donor, rs_recipient, rs_spell = _build_rust_move_state(3)
    rs.push_to_stack_with_three_targets(
        rs_spell, 0, rs_donor, rs_recipient, None,
    )
    rs.resolve_top_of_stack()
    rs_pair = (rs.get_counters(rs_donor), rs.get_counters(rs_recipient))
    assert rs_pair == (2, 1), (
        f"Rust: exactly one of three counters moves; got {rs_pair}"
    )

    assert py_pair == rs_pair, (
        f"Cross-engine byte-equal (multi): py={py_pair}, rs={rs_pair}"
    )
