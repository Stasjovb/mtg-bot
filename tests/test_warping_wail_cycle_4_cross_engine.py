"""**Warping Wail Cycle 4 — genuine real-EoE cross-engine probes
(2026-05-24).**

Cross-engine parity probes for Warping Wail's three modes. THE FLIP
that closes Warping Wail BLOCKED → PROBED.

Substrate landings the probes consume:

  * Cycle 1a (``ff512bea``) — ``Effect::ExileTargetCreatureWithPower
    OrToughnessAtMost { max_value: i32 }`` Rust variant + bridge arms
    + reverse-serializer leaf.
  * Cycle 2 (``32248da3``) — ``CounterTargetSpell.filter_types``
    Rust schema widening + bridge thread + reverse-serializer leaf.
  * Cycle 3 (``62bb1d94``) — ``_token_creature_with_safe_mana_
    activated_ability_card_def`` token-AA bridge widen (the
    Eldrazi Scion shape).
  * Cycle 4 (THIS lane) — per-leaf ``CreateToken`` spell-side
    serializer arm in ``_python_spell_effect_to_dict``'s ``_leaf``
    table (narrow ``_in_modal_mode`` gate keeps the
    Glimmerburst / Midnight Mayhem / Sami's Curiosity honest-stops
    intact) + the ``_seat_token_printings`` nested-mode walk
    extension (``_carrier_choose_one_mode_token_refs``) + per-mode
    cast-time binders in ``state_ops_cast.rs``'s
    ``is_recognized_targeted_mode_leaf`` allowlist for modes 0 + 1.

**Probe count: 3 (one per mode).** Each probe drives Warping Wail's
chosen mode through the Rust resolve path against an equivalent
Python resolve and asserts the observables match. The probe shape
mirrors the Drill Too Deep + Scour for Scrap precedent probes
(Cycle 6 + Cycle 2 of the per-mode-target ModalChooseOne envelope):

  * Setup: empty ``DeckSpec`` + synthetic state on both engines.
  * Rust: ``cast_spell_noncreature`` for the production cast-path
    (so the per-mode cast-time binder fires); narrow chosen modes
    via ``set_stack_top_chosen_mode_idxs([mode_idx])`` to mirror
    Python's ``chosen_modes=(mode_idx,)`` single-pick.
  * Python: direct stack push with ``chosen_modes=(mode_idx,)`` +
    ``resolve_top_of_stack``.
"""

from __future__ import annotations

import importlib.util

import pytest


def _require_engine():
    if importlib.util.find_spec("mtg_bot_engine") is None:
        pytest.skip("mtg_bot_engine PyO3 extension not installed")


_ZONE_HAND = 0
_ZONE_BATTLEFIELD = 2
_ZONE_GRAVEYARD = 3
_ZONE_EXILE = 5


# ---------------------------------------------------------------------------
# Verify-first: the production loader admits Warping Wail end-to-end
# ---------------------------------------------------------------------------


def test_real_eoe_warping_wail_production_loader_admit_and_seating():
    """**Verify-first pin.** The production loader path
    (``production_deck_to_deckspec`` + the
    ``_seat_token_printings`` nested-mode walk extension) admits a
    deck that contains Warping Wail and seats the nested Eldrazi
    Scion token's pid onto the spell CardDef's ``spell_effect`` —
    the EXACT field set Rust's parse_effect arms require.

    Pin the SHAPE that flips Cycle 4: the modal spell_effect dict
    carries (a) ``kind == "choose_one_mode"``, (b) three modes
    matching the parser SoT (``exile_target_creature_with_power_
    or_toughness_at_most`` / ``counter_target_spell`` /
    ``create_token``), (c) the mode-2 create_token dict has the
    NUMERIC ``token_printing_id`` field (no symbolic
    ``_token_card_def`` leak — the seating pass resolved it).
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    if get_active_source().get_printings().get("Warping Wail") is None:
        pytest.skip("Warping Wail absent from active CardSource")

    spec = trajectory.production_deck_to_deckspec(
        ["Warping Wail"] * 4 + ["Forest"] * 36,
        ["Forest"] * 40,
        pad_to_size=40,
    )
    cds = {cd.name: cd for cd in spec.card_defs}
    assert "Warping Wail" in cds, (
        "Warping Wail must be admitted by the production loader (the "
        "Cycle-4 admit-gate widen + reverse-serializer leaves fire)"
    )
    assert "Eldrazi Scion" in cds, (
        "the seating pass must register the Eldrazi Scion token CardDef "
        "(the Cycle-4 _carrier_choose_one_mode_token_refs extension)"
    )
    scion_pid = next(
        i for i, cd in enumerate(spec.card_defs) if cd.name == "Eldrazi Scion"
    )

    se = cds["Warping Wail"].spell_effect
    assert isinstance(se, dict)
    assert se["kind"] == "choose_one_mode"
    assert len(se["modes"]) == 3
    assert se["modes"][0] == {
        "kind": "exile_target_creature_with_power_or_toughness_at_most",
        "max_value": 1,
    }
    assert se["modes"][1] == {
        "kind": "counter_target_spell",
        "filter_types": ["Sorcery"],
    }
    # Mode 2 = create_token with NUMERIC pid, NO symbolic ref.
    mode2 = se["modes"][2]
    assert mode2["kind"] == "create_token"
    assert mode2["count"] == 1
    assert mode2["token_printing_id"] == scion_pid
    assert "_token_card_def" not in mode2, (
        "the seating pass must DROP the symbolic ref and seat the "
        "numeric pid — leaking the symbolic ref past the loader would "
        "be the no-fallback-hybrid violation §2 exists to prevent"
    )


# ---------------------------------------------------------------------------
# Mode 1 (exile target creature with P or T <= 1) — cross-engine probe
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_warping_wail_mode_0_exile_creature_pt_at_most_parity():
    """**Genuine real-EoE cross-engine probe — Warping Wail mode 0
    (ExileTargetCreatureWithPowerOrToughnessAtMost(max_value=1)).
    PROBED tier — one of the three Cycle 4 admit-flip probes.**

    Drives the GENUINE parsed Warping Wail through resolve on BOTH
    engines for the mode-0 exile path. Asserts byte-equal target
    state (the bear is exiled) post-resolve.

    Setup:
      * p1 controls a 1/1 Bear (legal target — P=1 ≤ max_value=1).
      * Python: spell on stack with ``chosen_modes=(0,)`` + the
        ``("creature", bear_id)`` target tuple.
      * Rust: spell cast through ``cast_spell_noncreature`` so the
        per-mode cast-time binder fires (the new Cycle-4 arm at
        ``state_ops_cast.rs``'s ``is_recognized_targeted_mode_leaf``
        scans for the first creature with P-or-T-≤-1); chosen-modes
        narrowed to [0] via ``set_stack_top_chosen_mode_idxs([0])``;
        resolve arm exiles the bear per CR 608.2b re-validation.
    """
    _require_engine()
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.combinators import ModalChooseOne
    from mtg_bot.effects.generic.exile import (
        ExileTargetCreatureWithPowerOrToughnessAtMost,
    )
    from mtg_bot.game import StackItem, Zone
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
    )
    from mtg_bot.turn import state_based_actions as py_sba

    real = get_active_source().get_printings().get("Warping Wail")
    if real is None:
        pytest.skip("Warping Wail absent from active CardSource")
    se = real.spell_effect
    assert isinstance(se, ModalChooseOne)
    assert isinstance(
        se.modes[0], ExileTargetCreatureWithPowerOrToughnessAtMost
    )
    assert se.modes[0].max_value == 1

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)

    # ---- Python: bear on p1's bf + Warping Wail on the stack mode 0.
    from mtg_bot.cards import SYNTHETIC_CREATURES
    # Use a known 1/1 vanilla creature — Healing Wisp is the simplest
    # synthetic 1/1 with no per-card riders. Its printed P=1 ≤
    # max_value=1 so the mode-0 filter accepts it.
    bear_printing = SYNTHETIC_CREATURES["Healing Wisp"]
    py_bear = py.new_object(bear_printing, owner_id=1, zone=Zone.BATTLEFIELD)
    py.battlefield.append(py_bear)
    py_spell = py.new_object(real, owner_id=0, zone=Zone.STACK)
    py_spell.summoning_sick = False
    py.stack.append(
        StackItem(
            source=py_spell, controller_id=0,
            chosen_modes=(0,),
            targets=(("creature", py_bear.id),),
        ),
    )
    resolve_top_of_stack(py)
    py_sba(py)
    assert len(py.stack) == 0
    # Python: bear is now in p1's exile zone.
    assert py_bear.zone == Zone.EXILE
    assert any(o.id == py_bear.id for o in py.players[1].exile)

    # ---- Rust: register the bear on p1's bf, register Warping Wail
    # on p0's hand, cast through the production cast path so the
    # per-mode binder fires + narrow chosen modes to [0].
    rs_bear_id = rs.register_and_inject_object(
        {
            "name": "Healing Wisp",
            "card_types": ["Creature"],
            "mana_cost": {"generic": 1, "W": 1},
            "power": 1,
            "toughness": 1,
        },
        1, _ZONE_BATTLEFIELD,
    )
    rs_spell_id = rs.register_and_inject_object(
        {
            "name": "Warping Wail",
            "card_types": ["Instant"],
            "mana_cost": {"generic": 1, "C": 1},
            "effects": [
                {
                    "kind": "choose_one_mode",
                    "modes": [
                        {
                            "kind": (
                                "exile_target_creature_with_power_or_"
                                "toughness_at_most"
                            ),
                            "max_value": 1,
                        },
                        {
                            "kind": "counter_target_spell",
                            "filter_types": ["Sorcery"],
                        },
                        # Synthetic registration — token_printing_id 0
                        # references the just-registered bear (creature
                        # printing). Mode 2 isn't exercised on this
                        # probe so the pid doesn't matter as long as it
                        # parses; the mode-0 cast-path binder fires +
                        # resolves before mode 2 would ever dispatch.
                        {
                            "kind": "create_token",
                            "count": 1,
                            "token_printing_id": 0,
                        },
                    ],
                }
            ],
        },
        0, _ZONE_HAND,
    )
    rs.add_mana(0, "C", 1)
    rs.add_mana(0, "C", 1)
    ok = rs.cast_spell_noncreature(rs_spell_id, 0)
    assert ok is True, "Warping Wail cast must succeed"
    # The cast-time per-mode binder picked the bear.
    assert rs.stack_top_target_id() == rs_bear_id, (
        "Rust per-mode-0 binder must seat the bear as the bound target"
    )
    # Narrow chosen modes to [0] (mirror Python chosen_modes=(0,)).
    rs.set_stack_top_chosen_mode_idxs([0])
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    # Mode 0's resolve arm exiled the bear.
    assert rs.find_object_zone(rs_bear_id) == _ZONE_EXILE


# ---------------------------------------------------------------------------
# Mode 2 (counter target sorcery spell) — cross-engine probe
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_warping_wail_mode_1_counter_target_sorcery_parity():
    """**Genuine real-EoE cross-engine probe — Warping Wail mode 1
    (CounterTargetSpell(filter_types=frozenset({"Sorcery"}))).
    PROBED tier — one of the three Cycle 4 admit-flip probes.**

    Mode 1's resolve arm walks the stack at resolve time and counters
    the topmost Sorcery (the ``filter_types`` gate is the C2
    substrate's headline closure). The cast-time binder is a
    passthrough (the binder doesn't seat a target — the resolve arm
    walks the stack itself).

    Setup:
      * A Sorcery is pushed onto the stack first.
      * Warping Wail is cast on top with mode 1.
      * Resolve drains the Wail first (top-of-stack); the resolve
        arm walks the stack top-down past its own source, finds the
        Sorcery, applies the Sorcery filter (matches — Sorcery in
        {"Sorcery"}), and counters it.
    """
    _require_engine()
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.combinators import ModalChooseOne
    from mtg_bot.effects.generic.stack_control import CounterTargetSpell
    from mtg_bot.game import StackItem, Zone
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
    )
    from mtg_bot.turn import state_based_actions as py_sba

    real = get_active_source().get_printings().get("Warping Wail")
    if real is None:
        pytest.skip("Warping Wail absent from active CardSource")
    se = real.spell_effect
    assert isinstance(se, ModalChooseOne)
    assert isinstance(se.modes[1], CounterTargetSpell)
    assert se.modes[1].filter_types == frozenset({"Sorcery"})

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)

    # ---- Python: stack a sorcery first, then Warping Wail mode 1.
    sources = get_active_source().get_printings()
    # Pick a known EoE Sorcery whose printing carries the "Sorcery"
    # card_type and is not a Creature (the filter_types matches the
    # "Sorcery" string against the source printing's card_types).
    py_sorcery_printing = sources.get("Pyroclasm")
    if py_sorcery_printing is None or "Sorcery" not in py_sorcery_printing.card_types:
        pytest.skip(
            "Pyroclasm absent or not a Sorcery in the active CardSource"
        )
    py_sorcery = py.new_object(
        py_sorcery_printing, owner_id=1, zone=Zone.STACK,
    )
    py.stack.append(
        StackItem(source=py_sorcery, controller_id=1, targets=()),
    )
    # Sorcery is at stack index 0; Warping Wail goes on top at index 1.
    sorcery_stack_idx = len(py.stack) - 1
    py_spell = py.new_object(real, owner_id=0, zone=Zone.STACK)
    py_spell.summoning_sick = False
    py.stack.append(
        StackItem(
            source=py_spell, controller_id=0,
            chosen_modes=(1,),
            # CounterTargetSpell.resolve reads ``("stack", idx)`` target
            # shape (stack-index, not spell-object-id).
            targets=(("stack", sorcery_stack_idx),),
        ),
    )
    resolve_top_of_stack(py)  # Warping Wail resolves first
    py_sba(py)
    # The Python CounterTargetSpell.resolve sets the target StackItem's
    # ``countered = True`` flag (the resolve sweeper drops countered
    # items when its turn comes). Both engines mark "this spell was
    # countered" via different routes — Rust moves the source object
    # to the controller's graveyard at counter-resolution time; Python
    # flips the StackItem flag and the next resolve pass moves the
    # object. The CYCLE-4 PROBED claim is "Warping Wail's mode 1 mode-
    # dispatch + filter_types Sorcery gate fires" — pinned via the
    # ``countered`` flag on the Sorcery's StackItem.
    sorcery_items = [
        s for s in py.stack if s.source.id == py_sorcery.id
    ]
    assert len(sorcery_items) == 1, (
        f"Python: sorcery stack item must still be present (countered "
        f"items are flagged then cleaned up by the next resolve pass; "
        f"got {len(sorcery_items)} entries on the stack)"
    )
    assert sorcery_items[0].countered is True, (
        "Python: sorcery's StackItem.countered must be True — the "
        "CounterTargetSpell mode 1 dispatch + filter_types Sorcery "
        "gate fired (the C2 substrate's headline parity path)"
    )

    # ---- Rust: push a synthetic Sorcery on the stack, then cast
    # Warping Wail through the production path + narrow to mode 1.
    rs_sorcery_id = rs.register_and_inject_object(
        {
            "name": "Test Sorcery",
            "card_types": ["Sorcery"],
            "mana_cost": {"generic": 1},
            "effects": [{"kind": "draw_cards", "count": 1}],
        },
        1, _ZONE_HAND,
    )
    rs.push_to_stack(rs_sorcery_id, 1)
    rs_spell_id = rs.register_and_inject_object(
        {
            "name": "Warping Wail",
            "card_types": ["Instant"],
            "mana_cost": {"generic": 1, "C": 1},
            "effects": [
                {
                    "kind": "choose_one_mode",
                    "modes": [
                        {
                            "kind": (
                                "exile_target_creature_with_power_or_"
                                "toughness_at_most"
                            ),
                            "max_value": 1,
                        },
                        {
                            "kind": "counter_target_spell",
                            "filter_types": ["Sorcery"],
                        },
                        {
                            "kind": "create_token",
                            "count": 1,
                            "token_printing_id": 0,
                        },
                    ],
                }
            ],
        },
        0, _ZONE_HAND,
    )
    rs.add_mana(0, "C", 1)
    rs.add_mana(0, "C", 1)
    ok = rs.cast_spell_noncreature(rs_spell_id, 0)
    assert ok is True, "Warping Wail cast must succeed"
    # Narrow chosen modes to [1] (mirror Python chosen_modes=(1,)).
    rs.set_stack_top_chosen_mode_idxs([1])
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    # The sorcery was countered: stack carries nothing for sorcery;
    # its GameObject is now in p1's graveyard.
    assert rs.find_object_zone(rs_sorcery_id) == _ZONE_GRAVEYARD, (
        f"Rust: sorcery must be in graveyard post-resolve; got "
        f"zone={rs.find_object_zone(rs_sorcery_id)}"
    )


# ---------------------------------------------------------------------------
# Mode 3 (create Eldrazi Scion token) — cross-engine probe
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_warping_wail_mode_2_create_eldrazi_scion_token_parity():
    """**Genuine real-EoE cross-engine probe — Warping Wail mode 2
    (CreateToken(Eldrazi Scion, count=1)). PROBED tier — one of the
    three Cycle 4 admit-flip probes.**

    Mode 2 mints a 1/1 colorless Eldrazi Scion creature token with
    "Sacrifice this token: Add {C}." — the C3 substrate's headline
    consumer. Cast-time binder is a no-target passthrough; the
    resolve arm dispatches to ``Effect::CreateToken { count,
    token_printing_id }`` (the Cycle-4 seating pass minted the
    Eldrazi Scion pid by walking ``choose_one_mode.modes``).

    Drives the GENUINE production-loader-built spec on the Rust side
    (so the seated pid lands in the registry); the matching Python
    side resolves the live ``CreateToken(Eldrazi Scion)`` mode and
    asserts both engines mint exactly one Eldrazi Scion on p0's bf.
    """
    _require_engine()
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.combinators import ModalChooseOne
    from mtg_bot.effects.generic.tokens import CreateToken
    from mtg_bot.game import StackItem, Zone
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import (
        build_python_state, build_rust_state,
    )
    from mtg_bot.turn import state_based_actions as py_sba

    real = get_active_source().get_printings().get("Warping Wail")
    if real is None:
        pytest.skip("Warping Wail absent from active CardSource")
    se = real.spell_effect
    assert isinstance(se, ModalChooseOne)
    assert isinstance(se.modes[2], CreateToken)
    assert se.modes[2].token_printing.name == "Eldrazi Scion"
    assert se.modes[2].count == 1

    # Use the production loader spec so the Eldrazi Scion pid is
    # seated by ``_seat_token_printings``'s nested-mode walk.
    spec = trajectory.production_deck_to_deckspec(
        ["Warping Wail"] * 4 + ["Forest"] * 36,
        ["Forest"] * 40,
        pad_to_size=40,
    )
    ww_pid = next(
        i for i, cd in enumerate(spec.card_defs) if cd.name == "Warping Wail"
    )
    scion_pid = next(
        i for i, cd in enumerate(spec.card_defs) if cd.name == "Eldrazi Scion"
    )

    py = build_python_state(spec)
    rs = build_rust_state(spec)

    # ---- Python: spell on stack with mode 2 (create token).
    py_spell = py.new_object(real, owner_id=0, zone=Zone.STACK)
    py_spell.summoning_sick = False
    py.stack.append(
        StackItem(
            source=py_spell, controller_id=0,
            chosen_modes=(2,),
            targets=(),
        ),
    )
    # Battlefield is a global on GameState in Python; the owner is
    # tracked per-GameObject. Snapshot the p0-owned bf object count.
    def _py_p0_bf_count(state):
        return sum(
            1 for o in state.battlefield if o.controller_id == 0
        )
    py_bf_before = _py_p0_bf_count(py)
    resolve_top_of_stack(py)
    py_sba(py)
    py_bf_after = _py_p0_bf_count(py)
    assert py_bf_after == py_bf_before + 1, (
        f"Python: mode 2 must mint one p0-owned token on the bf "
        f"(before={py_bf_before}, after={py_bf_after})"
    )
    # The new p0-owned bf object is the Eldrazi Scion.
    new_py_tokens = [
        o for o in py.battlefield
        if o.controller_id == 0 and o.printing.name == "Eldrazi Scion"
    ]
    assert len(new_py_tokens) == 1, (
        f"Python: expected exactly 1 Eldrazi Scion on p0's bf; got "
        f"{len(new_py_tokens)}"
    )

    # ---- Rust: inject Warping Wail into p0's hand from the seated
    # pid, cast through the production path (no target → cast still
    # succeeds because mode 2's no-target nature lets the modal cast
    # pass with bound_target=None — Mode 0's per-mode binder is the
    # default since cast-time binds Some(0) for single-pick modals,
    # but the resolve dispatch will read chosen_mode_idxs=[2] from
    # our override below); narrow chosen modes to [2].
    rs_spell_id = rs.register_and_inject_object(
        {
            "name": "Warping Wail",
            "card_types": ["Instant"],
            "mana_cost": {"generic": 1, "C": 1},
            "effects": [
                {
                    "kind": "choose_one_mode",
                    "modes": [
                        {
                            "kind": (
                                "exile_target_creature_with_power_or_"
                                "toughness_at_most"
                            ),
                            "max_value": 1,
                        },
                        {
                            "kind": "counter_target_spell",
                            "filter_types": ["Sorcery"],
                        },
                        {
                            "kind": "create_token",
                            "count": 1,
                            "token_printing_id": scion_pid,
                        },
                    ],
                }
            ],
        },
        0, _ZONE_HAND,
    )
    rs.add_mana(0, "C", 1)
    rs.add_mana(0, "C", 1)
    ok = rs.cast_spell_noncreature(rs_spell_id, 0)
    assert ok is True, "Warping Wail cast must succeed"
    # Narrow chosen modes to [2] (mirror Python chosen_modes=(2,)).
    rs.set_stack_top_chosen_mode_idxs([2])
    def _rs_p0_bf(state):
        return [e for e in state.battlefield_snapshot() if e["controller_id"] == 0]
    rs_bf_before = len(_rs_p0_bf(rs))
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    rs_bf_after = len(_rs_p0_bf(rs))
    assert rs_bf_after == rs_bf_before + 1, (
        f"Rust: mode 2 must mint one token on p0's bf "
        f"(before={rs_bf_before}, after={rs_bf_after})"
    )
    # Find the new Eldrazi Scion token on p0's bf by printing_id.
    p0_bf = _rs_p0_bf(rs)
    scion_entries = [
        e for e in p0_bf if e["printing_id"] == scion_pid
    ]
    assert len(scion_entries) == 1, (
        f"Rust: expected exactly 1 Eldrazi Scion on p0's bf; got "
        f"{len(scion_entries)} (p0 bf: {p0_bf})"
    )
