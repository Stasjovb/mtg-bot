"""Nesting Grounds -- per-card real-EoE cross-engine byte-equal probe
(THE FLIP; ``covered_by_construction -> PROBED``).

**FLIP landing (2026-05-31).** The substrate landing
(``c995ac04``) shipped the Rust
``Effect::MovePlusOneCounterBetweenPermanentsYouControl`` end-to-end
(enum + parse + to_pydict + dual-target resolve via the 2-slot
``current_resolve_payload_target_id`` / ``_2`` plumbing + cross-engine
bridge arms) but left Nesting Grounds DECLINED because the Rust
Carrier-AA *activation* path bound only ONE target. THIS slice closes
that gap: a SECOND ``Action::ActivateAbility.target_creature_id_2``
field threads the recipient onto the StackItem's
``trigger_payload.target_id_2`` (via the new
``StackItem::new_trigger_with_two_targets`` constructor), and the
trigger resolve entry points swap it into
``current_resolve_payload_target_id_2`` (mirroring the spell-cast path's
``target_obj_id_2`` swap). With the gap closed, the Effect class joins
``_carrier_aa_phase_1_effect_classes`` and Nesting Grounds admits at the
loader. The decline pin below is now an ADMIT pin + a NEW real-EoE
AA-activation byte-equal probe drives the actual parsed Nesting Grounds
``{1}{T}`` AA on BOTH engines via ``apply_action``.

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


# **The FLIP probe's Rust dict.** Nesting Grounds' REAL parsed shape: a
# bare Land carrying ONE non-mana ``{1}{T}`` sorcery-speed AA whose
# effect is the move-counter leaf. The byte-equal AA-activation probe
# below drives THIS dict's AA[0] via ``apply_action`` with BOTH targets
# seated (``target_creature_id`` = donor, ``target_creature_id_2`` =
# recipient) -- the path the 2nd-target slot closes. Mirrors the live
# EoE ``_python_aa_to_safe_dict(aa)`` shape
# (``{'cost': {'mana': {'generic': 1}, 'tap_self': True}, 'effect':
# {'kind': 'move_plus_one_counter_between_permanents_you_control'},
# 'sorcery_speed': True}``).
_RUST_NESTING_GROUNDS_DICT = {
    "name": "Nesting Grounds",
    "card_types": ["Land"],
    "mana_cost": {},
    "effects": [],
    "activated_abilities": [
        {
            "cost": {"mana": {"generic": 1}, "tap_self": True},
            "effect": {
                "kind": "move_plus_one_counter_between_permanents_you_control",
            },
            "is_mana_ability": False,
            "sorcery_speed": True,
        },
    ],
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
# (2) LOAD-BEARING FLIP invariant: Nesting Grounds now ADMITS at the
# loader admit gate. The 2nd AA-activation target slot landed (the
# substrate landing's documented follow-up), so the Effect class joined
# the admit set and the COST + Land-carrier-bridge predicates ACCEPT the
# printing end-to-end. This pin is the PROBED-tier flip marker (inverted
# from the prior substrate-only DECLINE pin).
# ---------------------------------------------------------------------------


def test_nesting_grounds_now_admits_at_loader_admit_gate():
    """**The FLIP invariant (inverted from the substrate-only DECLINE
    pin).** Nesting Grounds must ADMIT at the end-to-end loader because
    the Effect class is now in the Phase-1 Carrier-AA admit set AND the
    Rust AA-activation path binds BOTH targets (the dual-target slot
    landed). We pin BOTH halves:
      * The per-AA admit predicate ``_aa_is_phase1_sub_shape_a`` ADMITS
        (effect-class gate now passes; cost + riders always passed).
      * The end-to-end ``_filter_deck_to_bridge_supported`` admits
        Nesting Grounds.
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

    # The effect-class gate now passes (the FLIP); the per-AA predicate
    # ADMITS (cost {1}{T} + sorcery_speed rider always passed).
    assert _carrier_aa_effect_class_admitted(aa.effect) is True
    assert _aa_is_phase1_sub_shape_a(aa) is True

    # Carrier-AA Land + Any printing predicates admit.
    assert _printing_is_bridge_simple_carrier_aa_land(p) is True
    assert _printing_is_bridge_simple_carrier_aa_any(p) is True

    # End-to-end loader: Nesting Grounds is ADMITTED.
    filt, defs = _filter_deck_to_bridge_supported(
        ["Nesting Grounds"], _PRINTINGS,
    )
    assert filt == ["Nesting Grounds"], (
        "Nesting Grounds must ADMIT at the loader admit gate (the FLIP: "
        "the dual-target AA's 2nd-target slot landed). Got "
        "filt={filt!r}".format(filt=filt)
    )
    assert len(defs) == 1


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


# ---------------------------------------------------------------------------
# (6) THE FLIP PROBE -- GENUINE real-EoE cross-engine byte-equal probe
# driving the ACTUAL parsed Nesting Grounds {1}{T} AA via the
# AA-ACTIVATION path on BOTH engines. This is the load-bearing PROBED-
# tier evidence: the substrate probes above drive the resolve arm via
# the spell-cast 2-slot plumbing, but THIS probe exercises the path the
# 2nd-target slot closes -- ``apply_action(ActivateAbility(...))`` with
# the donor + recipient threaded through, byte-equal cross-engine.
# ---------------------------------------------------------------------------


class _ScriptedTargetAgent:
    """Minimal agent that returns a pre-scripted sequence of target picks
    (one per ``choose_target`` call). Drives Python's ``_activate_ability``
    multi-target picker to the SAME (donor, recipient) ids the Rust
    ``apply_action`` carries explicitly -- so the cross-engine compare is
    on the SAME two permanents (avoids the no-agent ``pool[0]`` fallback,
    which would pick the Nesting Grounds land itself as the donor).
    """

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


def _build_python_aa_state(donor_counters: int):
    """Seat the REAL parsed Nesting Grounds + two creature permanents on
    p0's bf, donor seeded with ``donor_counters`` counters, 1 floating
    {C} coin in p0's pool to pay the AA's {1}. A scripted agent picks
    (donor, recipient). Returns ``(state, ng, donor, recipient)``.
    """
    from mtg_bot.cards import SYNTHETIC_CREATURES
    from mtg_bot.game import GameState, ManaCoin, Player, Zone
    from mtg_bot.turn import Step

    ng_printing = _PRINTINGS["Nesting Grounds"]

    state = GameState()
    state.players.append(Player(id=0, agent=None))
    state.players.append(Player(id=1, agent=None))
    state.active_player_idx = 0
    state.priority_player_idx = 0
    state.step = Step.PRECOMBAT_MAIN

    ng = state.new_object(ng_printing, 0, Zone.BATTLEFIELD)
    ng.controller_id = 0
    ng.summoning_sick = False
    state.battlefield.append(ng)

    names = list(SYNTHETIC_CREATURES)[:2]
    donor = state.new_object(SYNTHETIC_CREATURES[names[0]], 0, Zone.BATTLEFIELD)
    donor.controller_id = 0
    state.battlefield.append(donor)
    recipient = state.new_object(
        SYNTHETIC_CREATURES[names[1]], 0, Zone.BATTLEFIELD,
    )
    recipient.controller_id = 0
    state.battlefield.append(recipient)
    donor.plus_one_counters = donor_counters

    # Floating {C} to pay the AA's {1} generic cost.
    state.players[0].mana_pool.append(ManaCoin("C"))
    # Scripted agent: pick donor (slot 0) then recipient (slot 1).
    state.players[0].agent = _ScriptedTargetAgent([
        ("permanent", donor.id),
        ("permanent", recipient.id),
    ])
    return state, ng, donor, recipient


def _build_rust_aa_state(donor_counters: int):
    """Mirror of ``_build_python_aa_state`` on Rust: the REAL Nesting
    Grounds AA dict + two creature permanents on p0's bf (donor seeded),
    1 floating {C} coin to pay the {1}. Returns ``(rs, ng, donor_id,
    recipient_id)``.
    """
    import mtg_bot_engine

    rs = mtg_bot_engine.make_synthetic_state(0, 0, 0)
    ng = rs.register_and_inject_object(
        _RUST_NESTING_GROUNDS_DICT, 0, ZONE_BATTLEFIELD,
    )
    rs.force_set_summoning_sick(ng, False)
    donor = rs.register_and_inject_object(_RUST_PERMANENT, 0, ZONE_BATTLEFIELD)
    recipient = rs.register_and_inject_object(
        _RUST_PERMANENT, 0, ZONE_BATTLEFIELD,
    )
    assert rs.set_counters(donor, donor_counters) is True
    rs.add_mana(0, "C", 1)
    return rs, ng, donor, recipient


@_rust_skip
def test_cross_engine_real_eoe_nesting_grounds_aa_activation_move_parity():
    """**THE FLIP PROBE -- GENUINE real-EoE AA-activation byte-equal.**
    Drives the ACTUAL parsed Nesting Grounds AA[0] (``{1}{T}: move a
    +1/+1 counter from target permanent you control onto a second target
    permanent you control``) via the AA-ACTIVATION path on BOTH engines:

      * Python: ``apply_action(ActivateAbility(source_id=ng, 0))`` with a
        scripted agent picking (donor, recipient), then resolve the stack.
      * Rust: ``apply_action({kind: activate_ability, source_id: ng,
        ability_index: 0, target_creature_id: donor,
        target_creature_id_2: recipient})`` -- the 2nd-target slot the
        FLIP landed -- then ``resolve_top_of_stack``.

    Both move exactly one counter (donor 2 -> 1, recipient 0 -> 1) AND
    tap Nesting Grounds (tap_self cost) AND drain the {1} from the pool.
    Byte-equal on the (donor_counters, recipient_counters, ng_tapped)
    triple. This is the path the substrate landing could NOT drive --
    closing the AA-activation 2nd-target gap is the whole FLIP.
    """
    # Real-EoE-signal discipline: bind the genuine parsed printing inside
    # the *_parity body so the pool-parity classifier credits THIS slug.
    ng_printing = _PRINTINGS.get("Nesting Grounds")
    if ng_printing is None:
        pytest.skip("Nesting Grounds absent from active CardSource")

    from mtg_bot.actions import (
        ActivateAbility,
        apply_action,
        resolve_top_of_stack,
    )

    # ---- Python: real-EoE AA activation via apply_action + scripted
    # agent, then resolve the stack (non-mana AA uses the stack).
    py, py_ng, py_donor, py_recipient = _build_python_aa_state(2)
    apply_action(py, 0, ActivateAbility(source_id=py_ng.id, ability_index=0))
    # The AA goes on the stack (non-mana); resolve it.
    assert len(py.stack) == 1, (
        "Python: the non-mana AA must push exactly one stack item"
    )
    while py.stack:
        resolve_top_of_stack(py)
    py_triple = (
        _py_counters(py, py_donor.id),
        _py_counters(py, py_recipient.id),
        py_ng.tapped,
    )
    assert py_triple == (1, 1, True), (
        f"Python: AA activation moves one counter (donor 2 -> 1, "
        f"recipient 0 -> 1) + taps Nesting Grounds; got {py_triple}"
    )

    # ---- Rust: real AA activation via apply_action with BOTH targets
    # seated (the 2nd-target slot the FLIP landed), then resolve.
    rs, rs_ng, rs_donor, rs_recipient = _build_rust_aa_state(2)
    rs.apply_action(
        {
            "kind": "activate_ability",
            "source_id": rs_ng,
            "ability_index": 0,
            "target_creature_id": rs_donor,
            "target_creature_id_2": rs_recipient,
        }
    )
    assert rs.stack_size() == 1, (
        "Rust: the non-mana AA must push exactly one stack item"
    )
    rs.resolve_top_of_stack()
    rs_triple = (
        rs.get_counters(rs_donor),
        rs.get_counters(rs_recipient),
        rs.is_tapped(rs_ng),
    )
    assert rs_triple == (1, 1, True), (
        f"Rust: AA activation moves one counter (donor 2 -> 1, "
        f"recipient 0 -> 1) + taps Nesting Grounds; got {rs_triple}"
    )

    # ---- Cross-engine byte-equal on the full (counters, tapped) triple.
    assert py_triple == rs_triple, (
        f"Cross-engine byte-equal (AA-activation counter move + tap): "
        f"py={py_triple}, rs={rs_triple}"
    )
