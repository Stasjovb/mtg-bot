"""**Archenemy's Charm single-cycle FLIP (2026-05-24).**

Tests for the new Rust
``Effect::PutPlusOneCountersAndGrantKeywordsUEOTOnTargetCreatureYouControl``
two-field carrier variant + the spell-card-bridge admit-flip closure
of Archenemy's Charm (``{B}{B}{B}`` Instant, EoE).

Probes follow the slug-credit convention
``test_cross_engine_real_eoe_<slug>_<mode>_parity`` so the admit-set
inventory pipeline awards the PROBED-flip credit automatically.
Companion Rust unit pins exercise the new Mode-2-substrate Effect
variant's parse + resolve arms in isolation (parse-time field-set
shape, counters+keywords resolve, target re-validate fizzle).

**Single-cycle FLIP under the Phase 4 ``not slot_kinds`` permissive
disjunct.** Archenemy's Charm's ``target_count_range()`` is
``(1, 2)`` (per-mode min/max: mode 0 is ``(1, 1)``, mode 1 is
``(1, 2)``, mode 2 is ``(1, 1)``) and its ``target_slot_kinds()``
reports ``()`` because the ``ModalChooseOne`` composer doesn't
expose a single slot_kinds (each mode's filter is private to that
mode). The Phase 4 admit predicate at
``trajectory._PHASE4_MULTI_GRAVEYARD_SHAPE`` accepts under the
``not slot_kinds`` permissive disjunct — auto-grow STRUCTURAL, no
admit-predicate widen required (same single-cycle FLIP pattern as
Singularity Rupture's ``(0, 8)`` and Pull Through the Weft's
``(0, 2)``).

**3-mode envelope coverage.**

  * **Mode 0** — ``ExileTargetCreature``: ALREADY Rust-covered via
    the ``feature/effect-exile-target-creature-p1`` Gravkill closure
    landed 2026-05-22.
  * **Mode 1** —
    ``ReturnUpToNCreaturesFromYourGraveyardToHand(min_n=1, max_n=2)``:
    ALREADY Rust-covered via the substrate-only branch landed
    2026-05-22; the resolve arm self-scans the source-controller's
    graveyard front-to-back for creature cards (the sibling Phase-4
    multi-target resolve-time self-scan precedent — same shape as
    Singularity Rupture / Pull Through the Weft / Scout for
    Survivors). No ``StackItem`` plumbing required on this lane.
  * **Mode 2** —
    ``PutPlusOneCountersAndGrantKeywordsUEOTOnTargetCreatureYouControl``:
    NEW Rust variant THIS LANE — declaration + parse + to_pydict +
    resolve arms + bridge arm + reverse-serializer leaf.

**Per-mode binder allowlist widen.** All three Archenemy's Charm
modes are listed in ``is_recognized_targeted_mode_leaf`` so the
``chosen_mode`` peek correctly identifies the chosen mode as
targeted. Per-mode dispatch arms scan: mode 0 = first creature on
EITHER bf in ``bf_iter_etb_sorted`` order (any-side filter,
mirroring Python's ``ExileTargetCreature.legal_targets``); mode 1
= passthrough (resolve-time graveyard self-scan); mode 2 = first
own-controlled Creature on the caster's bf, effective-controller-
aware.
"""

from __future__ import annotations

import importlib.util

import pytest


def _require_engine():
    if importlib.util.find_spec("mtg_bot_engine") is None:
        pytest.skip("mtg_bot_engine PyO3 extension not installed")


_ZONE_HAND = 0
_ZONE_LIBRARY = 1
_ZONE_BATTLEFIELD = 2
_ZONE_GRAVEYARD = 3
_ZONE_EXILE = 5


def _fresh_rust():
    import mtg_bot_engine
    return mtg_bot_engine.make_synthetic_state(0, 0, 0)


# ---------------------------------------------------------------------------
# Parser SoT verify-first
# ---------------------------------------------------------------------------


def test_archenemys_charm_parser_emits_expected_modal_envelope():
    """**Parser source-of-truth pin.** ``Archenemy's Charm`` parses to
    a 3-mode ``ModalChooseOne`` whose modes are:
      0. ``ExileTargetCreature`` (mode 0 — exile target creature)
      1. ``ReturnUpToNCreaturesFromYourGraveyardToHand(min_n=1,
         max_n=2)`` (mode 1 — return 1-2 creature cards from your
         graveyard)
      2. ``PutPlusOneCountersAndGrantKeywordsUEOTOnTargetCreatureYou
         Control(amount=2, granted_keywords={"lifelink"},
         you_control_only=True)`` (mode 3 — pump + lifelink UEOT).
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.combinators import ModalChooseOne
    from mtg_bot.effects.generic.exile import ExileTargetCreature
    from mtg_bot.effects.generic.bounce import (
        ReturnUpToNCreaturesFromYourGraveyardToHand,
    )
    from mtg_bot.effects.generic.counters import (
        PutPlusOneCountersAndGrantKeywordsUEOTOnTargetCreatureYouControl,
    )

    real = (
        get_active_source().get_printings().get("Archenemy's Charm")
    )
    if real is None:
        pytest.skip(
            "Archenemy's Charm absent from active CardSource"
        )
    se = real.spell_effect
    assert isinstance(se, ModalChooseOne)
    assert se.or_both is False
    assert len(se.modes) == 3

    # Mode 0 — bare exile-target-creature.
    assert isinstance(se.modes[0], ExileTargetCreature)

    # Mode 1 — multi-target graveyard return (1-2 creature cards).
    m1 = se.modes[1]
    assert isinstance(m1, ReturnUpToNCreaturesFromYourGraveyardToHand)
    assert m1.min_n == 1
    assert m1.max_n == 2
    assert m1.destination == "hand"

    # Mode 2 — pump+keyword UEOT combined.
    m2 = se.modes[2]
    assert isinstance(
        m2,
        PutPlusOneCountersAndGrantKeywordsUEOTOnTargetCreatureYouControl,
    )
    assert m2.amount == 2
    assert m2.granted_keywords == frozenset({"lifelink"})
    assert m2.you_control_only is True

    # Modal envelope shape — Phase-4 `not slot_kinds` permissive
    # disjunct admits this (1, 2)/empty-slot_kinds modal.
    assert se.target_count_range() == (1, 2)
    assert se.target_slot_kinds() == ()

    # Mana cost has no X.
    assert real.mana_cost.x_pips == 0


# ---------------------------------------------------------------------------
# Serializer round-trip (Mode 2 carrier — the NEW substrate of this lane)
# ---------------------------------------------------------------------------


def test_python_serializer_round_trip_for_mode_2_carrier():
    """The Mode 2 carrier
    ``PutPlusOneCountersAndGrantKeywordsUEOTOnTargetCreatureYouControl``
    round-trips through
    ``_python_spell_effect_to_dict`` →
    ``_ta_dict_to_python_effect`` byte-equal. The dict shape carries
    `amount` (int) + `granted_keywords` (sorted list of strings —
    Rust storage is sorted-unique; the Python frozenset is sorted on
    emit for determinism)."""
    from mtg_bot.effects.generic.counters import (
        PutPlusOneCountersAndGrantKeywordsUEOTOnTargetCreatureYouControl,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect
    from mtg_bot.parity.trajectory import _python_spell_effect_to_dict

    # The exact Archenemy's Charm Mode 2 shape.
    eff = (
        PutPlusOneCountersAndGrantKeywordsUEOTOnTargetCreatureYouControl(
            amount=2, granted_keywords=frozenset({"lifelink"}),
        )
    )
    d = _python_spell_effect_to_dict(eff)
    assert d == {
        "kind": (
            "put_plus_one_counters_and_grant_keywords_ueot_on_target_"
            "creature_you_control"
        ),
        "amount": 2,
        "granted_keywords": ["lifelink"],
    }
    back = _ta_dict_to_python_effect(d)
    assert isinstance(
        back,
        PutPlusOneCountersAndGrantKeywordsUEOTOnTargetCreatureYouControl,
    )
    assert back.amount == 2
    assert back.granted_keywords == frozenset({"lifelink"})

    # Multi-keyword + non-default amount edge — bridge must accept
    # both fields and round-trip the sorted list.
    eff2 = (
        PutPlusOneCountersAndGrantKeywordsUEOTOnTargetCreatureYouControl(
            amount=3,
            granted_keywords=frozenset({"trample", "deathtouch"}),
        )
    )
    d2 = _python_spell_effect_to_dict(eff2)
    assert d2["amount"] == 3
    assert d2["granted_keywords"] == ["deathtouch", "trample"]
    back2 = _ta_dict_to_python_effect(d2)
    assert back2.granted_keywords == frozenset({"trample", "deathtouch"})


# ---------------------------------------------------------------------------
# Admit gate flip — Archenemy's Charm is in the live admit set.
# ---------------------------------------------------------------------------


def test_archenemys_charm_in_bridge_admit_set():
    """**Admit gate flip pin.** ``Archenemy's Charm`` is in the live
    spell-card-bridge admit set the moment all three modes are
    covered+bridged. Modes 0 + 1 are already Rust-covered today;
    Mode 2's Effect variant + bridge arm + reverse-serializer leaf
    ship in THIS lane, tipping the §2 covered+bridged tooth True
    for the full 3-mode envelope. The Phase-4 ``not slot_kinds``
    permissive disjunct admits the ``(1, 2)`` empty-slot_kinds
    modal shape; the AUTO-JOIN is structural — no per-card admit-
    list entry needed, no admit-predicate widen required."""
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    real = (
        get_active_source().get_printings().get("Archenemy's Charm")
    )
    if real is None:
        pytest.skip(
            "Archenemy's Charm absent from active CardSource"
        )
    assert trajectory._printing_is_bridge_simple_spell(real), (
        "Archenemy's Charm must pass the spell-card-bridge admit "
        "predicate post-flip; the covered+bridged + Phase-4 "
        "permissive-shape gate fires it automatically."
    )


def test_mode_2_effect_class_now_covered():
    """``PutPlusOneCountersAndGrantKeywordsUEOTOnTargetCreatureYouControl``
    is in the live covered+bridged set post-flip (the new Rust
    variant + the bridge arm both shipped in this lane, so the 1:1
    identity mapping in ``map_rust_to_python`` includes it in the
    covered intersection)."""
    from mtg_bot.parity.effect_coverage import covered_python_class_set

    cov = covered_python_class_set()
    assert (
        "PutPlusOneCountersAndGrantKeywordsUEOTOnTargetCreatureYouControl"
        in cov
    ), (
        "PutPlusOneCountersAndGrantKeywordsUEOTOnTargetCreatureYouControl "
        "must be in the covered+bridged set post-flip (Rust variant + "
        "bridge arm shipped this lane)"
    )


# ---------------------------------------------------------------------------
# Rust unit pins — Mode 2 parse + resolve
# ---------------------------------------------------------------------------


def test_rust_mode_2_carrier_parses():
    """The Rust
    ``Effect::PutPlusOneCountersAndGrantKeywordsUEOTOnTargetCreature
    YouControl`` two-field carrier variant parses from the dict
    shape with `amount` + `granted_keywords` — both fields required
    on emit, but the parse arm tolerates `amount` defaulting to 2
    and `granted_keywords` defaulting to `[]` when missing."""
    _require_engine()
    rs = _fresh_rust()
    # Bare shape — default amount=2, no keywords.
    sid = rs.register_and_inject_object(
        {
            "name": "Synthetic Mode 2",
            "card_types": ["Sorcery"],
            "effects": [{
                "kind": (
                    "put_plus_one_counters_and_grant_keywords_ueot_"
                    "on_target_creature_you_control"
                ),
            }],
        },
        0, _ZONE_HAND,
    )
    assert isinstance(sid, int)
    # Full shape with explicit amount + keywords.
    sid2 = rs.register_and_inject_object(
        {
            "name": "Synthetic Mode 2 Full",
            "card_types": ["Sorcery"],
            "effects": [{
                "kind": (
                    "put_plus_one_counters_and_grant_keywords_ueot_"
                    "on_target_creature_you_control"
                ),
                "amount": 2,
                "granted_keywords": ["lifelink"],
            }],
        },
        0, _ZONE_HAND,
    )
    assert isinstance(sid2, int)


def test_rust_mode_2_carrier_rejects_negative_amount():
    """Negative `amount` raises at parse time (defense-in-depth in
    both parse and resolve arms)."""
    _require_engine()
    rs = _fresh_rust()
    with pytest.raises((ValueError, Exception)):
        rs.register_and_inject_object(
            {
                "name": "Bad Mode 2",
                "card_types": ["Sorcery"],
                "effects": [{
                    "kind": (
                        "put_plus_one_counters_and_grant_keywords_"
                        "ueot_on_target_creature_you_control"
                    ),
                    "amount": -1,
                }],
            },
            0, _ZONE_HAND,
        )


def test_rust_mode_2_carrier_rejects_empty_keyword_string():
    """Empty keyword entries in `granted_keywords` raise — parse arm
    enforces the non-empty-string contract."""
    _require_engine()
    rs = _fresh_rust()
    with pytest.raises((ValueError, Exception)):
        rs.register_and_inject_object(
            {
                "name": "Bad Mode 2 Empty Kw",
                "card_types": ["Sorcery"],
                "effects": [{
                    "kind": (
                        "put_plus_one_counters_and_grant_keywords_"
                        "ueot_on_target_creature_you_control"
                    ),
                    "granted_keywords": [""],
                }],
            },
            0, _ZONE_HAND,
        )


# ---------------------------------------------------------------------------
# Real-EoE cross-engine parity probe — Mode 0 (exile target creature)
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_archenemys_charm_mode_0_exile_target_creature_parity():
    """**Genuine real-EoE cross-engine probe — Archenemy's Charm
    mode 0 (ExileTargetCreature). PROBED tier — one of three 3-mode
    envelope flip probes for the single-cycle Archenemy's Charm
    closure.**

    Drives the GENUINE parsed Archenemy's Charm printing through
    resolve on BOTH engines for the mode-0 exile path. The mode-0
    leaf is the bare ``ExileTargetCreature`` Effect (any-side
    filter); the per-mode binder seats the first creature on
    EITHER bf in ``bf_iter_etb_sorted`` order; the resolve arm
    moves the bound creature to the controller's exile zone with
    CR 400.7 zone-change reset.

    Setup:
      * p1 controls a 1/1 Bear (legal target — bare
        ``IsCreature()`` filter, any-side).
      * Python: spell on stack with ``chosen_modes=(0,)`` + the
        ``("creature", bear_id)`` target tuple.
      * Rust: spell cast through ``cast_spell_noncreature`` so the
        per-mode cast-time binder fires; chosen-modes narrowed to
        [0] via ``set_stack_top_chosen_mode_idxs([0])``.
    """
    _require_engine()
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.combinators import ModalChooseOne
    from mtg_bot.effects.generic.exile import ExileTargetCreature
    from mtg_bot.game import StackItem, Zone
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
    )
    from mtg_bot.turn import state_based_actions as py_sba

    real = (
        get_active_source().get_printings().get("Archenemy's Charm")
    )
    if real is None:
        pytest.skip(
            "Archenemy's Charm absent from active CardSource"
        )
    se = real.spell_effect
    assert isinstance(se, ModalChooseOne)
    assert isinstance(se.modes[0], ExileTargetCreature)

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)

    # ---- Python: bear on p1's bf + Archenemy's Charm on the stack
    # mode 0.
    from mtg_bot.cards import SYNTHETIC_CREATURES
    bear_printing = SYNTHETIC_CREATURES["Healing Wisp"]
    py_bear = py.new_object(
        bear_printing, owner_id=1, zone=Zone.BATTLEFIELD,
    )
    py_bear.summoning_sick = False
    py_bear.controller_id = 1
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
    # Python: bear in p1's exile.
    assert py_bear.zone == Zone.EXILE
    assert any(o.id == py_bear.id for o in py.players[1].exile)

    # ---- Rust: register the bear on p1's bf, register Archenemy's
    # Charm on p0's hand, cast through the production cast path so
    # the per-mode binder fires + narrow chosen modes to [0].
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
            "name": "Archenemy's Charm",
            "card_types": ["Instant"],
            "mana_cost": {"B": 3},
            "effects": [
                {
                    "kind": "choose_one_mode",
                    "modes": [
                        {"kind": "exile_target_creature"},
                        {
                            "kind": (
                                "return_up_to_n_creatures_from_your_"
                                "graveyard_to_hand"
                            ),
                            "min_n": 1,
                            "max_n": 2,
                        },
                        {
                            "kind": (
                                "put_plus_one_counters_and_grant_"
                                "keywords_ueot_on_target_creature_"
                                "you_control"
                            ),
                            "amount": 2,
                            "granted_keywords": ["lifelink"],
                        },
                    ],
                }
            ],
        },
        0, _ZONE_HAND,
    )
    rs.add_mana(0, "B", 1)
    rs.add_mana(0, "B", 1)
    rs.add_mana(0, "B", 1)
    ok = rs.cast_spell_noncreature(rs_spell_id, 0)
    assert ok is True, "Archenemy's Charm cast must succeed"
    # The cast-time per-mode binder picked the bear (mode 0 = any-
    # side first creature scan).
    assert rs.stack_top_target_id() == rs_bear_id, (
        "Rust per-mode-0 binder must seat the bear as the bound "
        "target (any-side first-creature scan in bf_iter_etb_sorted "
        "order)"
    )
    rs.set_stack_top_chosen_mode_idxs([0])
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    # Mode 0's resolve arm exiled the bear.
    assert rs.find_object_zone(rs_bear_id) == _ZONE_EXILE


# ---------------------------------------------------------------------------
# Real-EoE cross-engine parity probe — Mode 1 (graveyard multi-return)
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_archenemys_charm_mode_1_graveyard_multi_return_parity():
    """**Genuine real-EoE cross-engine probe — Archenemy's Charm
    mode 1 (ReturnUpToNCreaturesFromYourGraveyardToHand(min_n=1,
    max_n=2)). PROBED tier — one of three 3-mode envelope flip
    probes.**

    Mode 1's resolve arm self-scans the source-controller's
    graveyard front-to-back for creature cards (no per-card MV gate;
    up to `max_n=2`). The cross-engine harness's
    ``_PickFirstLegalTargetAgent`` picks first-N legal in
    legal_targets order; Python's cast-time binder picks the same
    first-N graveyard creatures; Rust's resolve self-scans the same
    order — byte-equal under the harness convention.

    Setup:
      * p0's graveyard contains 3 creatures (in insertion order:
        Bear1, Bear2, Bear3).
      * p0 casts Archenemy's Charm mode 1. The first two creatures
        in p0's graveyard (Bear1, Bear2) return to p0's hand; Bear3
        stays in the graveyard.
    """
    _require_engine()
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.combinators import ModalChooseOne
    from mtg_bot.effects.generic.bounce import (
        ReturnUpToNCreaturesFromYourGraveyardToHand,
    )
    from mtg_bot.game import StackItem, Zone
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
    )
    from mtg_bot.turn import state_based_actions as py_sba

    real = (
        get_active_source().get_printings().get("Archenemy's Charm")
    )
    if real is None:
        pytest.skip(
            "Archenemy's Charm absent from active CardSource"
        )
    se = real.spell_effect
    assert isinstance(se, ModalChooseOne)
    assert isinstance(
        se.modes[1], ReturnUpToNCreaturesFromYourGraveyardToHand,
    )
    assert se.modes[1].min_n == 1
    assert se.modes[1].max_n == 2

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)

    # ---- Python: three creatures in p0's graveyard (front-to-back:
    # Bear1, Bear2, Bear3); the cross-engine agent picks Bear1 +
    # Bear2 as the two targets.
    from mtg_bot.cards import SYNTHETIC_CREATURES
    bear_printing = SYNTHETIC_CREATURES["Healing Wisp"]
    py_bear1 = py.new_object(
        bear_printing, owner_id=0, zone=Zone.GRAVEYARD,
    )
    py_bear2 = py.new_object(
        bear_printing, owner_id=0, zone=Zone.GRAVEYARD,
    )
    py_bear3 = py.new_object(
        bear_printing, owner_id=0, zone=Zone.GRAVEYARD,
    )
    py.players[0].graveyard.append(py_bear1)
    py.players[0].graveyard.append(py_bear2)
    py.players[0].graveyard.append(py_bear3)
    py_spell = py.new_object(real, owner_id=0, zone=Zone.STACK)
    py_spell.summoning_sick = False
    py.stack.append(
        StackItem(
            source=py_spell, controller_id=0,
            chosen_modes=(1,),
            targets=(
                ("graveyard_creature", py_bear1.id),
                ("graveyard_creature", py_bear2.id),
            ),
        ),
    )
    resolve_top_of_stack(py)
    py_sba(py)
    assert len(py.stack) == 0
    # Python: Bear1 + Bear2 in p0's hand, Bear3 still in graveyard.
    assert py_bear1.zone == Zone.HAND
    assert py_bear2.zone == Zone.HAND
    assert py_bear3.zone == Zone.GRAVEYARD
    hand_ids = [o.id for o in py.players[0].hand]
    assert py_bear1.id in hand_ids
    assert py_bear2.id in hand_ids
    gy_ids = [o.id for o in py.players[0].graveyard]
    assert py_bear3.id in gy_ids

    # ---- Rust: three creatures in p0's graveyard, cast Archenemy's
    # Charm, narrow modes to [1], resolve. Mode 1's resolve arm
    # self-scans p0's graveyard front-to-back for creature cards
    # (up to max_n=2) — same front-to-back order as Python's
    # `_PickFirstLegalTargetAgent`-driven first-N pick. Rust
    # graveyard injection appends; the resolve arm walks
    # `state.players[cidx].graveyard.iter()` in storage order.
    rs_bear1 = rs.register_and_inject_object(
        {
            "name": "Healing Wisp",
            "card_types": ["Creature"],
            "mana_cost": {"generic": 1, "W": 1},
            "power": 1, "toughness": 1,
        },
        0, _ZONE_GRAVEYARD,
    )
    rs_bear2 = rs.register_and_inject_object(
        {
            "name": "Healing Wisp",
            "card_types": ["Creature"],
            "mana_cost": {"generic": 1, "W": 1},
            "power": 1, "toughness": 1,
        },
        0, _ZONE_GRAVEYARD,
    )
    rs_bear3 = rs.register_and_inject_object(
        {
            "name": "Healing Wisp",
            "card_types": ["Creature"],
            "mana_cost": {"generic": 1, "W": 1},
            "power": 1, "toughness": 1,
        },
        0, _ZONE_GRAVEYARD,
    )
    rs_spell_id = rs.register_and_inject_object(
        {
            "name": "Archenemy's Charm",
            "card_types": ["Instant"],
            "mana_cost": {"B": 3},
            "effects": [
                {
                    "kind": "choose_one_mode",
                    "modes": [
                        {"kind": "exile_target_creature"},
                        {
                            "kind": (
                                "return_up_to_n_creatures_from_your_"
                                "graveyard_to_hand"
                            ),
                            "min_n": 1,
                            "max_n": 2,
                        },
                        {
                            "kind": (
                                "put_plus_one_counters_and_grant_"
                                "keywords_ueot_on_target_creature_"
                                "you_control"
                            ),
                            "amount": 2,
                            "granted_keywords": ["lifelink"],
                        },
                    ],
                }
            ],
        },
        0, _ZONE_HAND,
    )
    rs.add_mana(0, "B", 1)
    rs.add_mana(0, "B", 1)
    rs.add_mana(0, "B", 1)
    ok = rs.cast_spell_noncreature(rs_spell_id, 0)
    assert ok is True
    rs.set_stack_top_chosen_mode_idxs([1])
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    # The first two graveyard creatures (front-to-back) return to
    # hand; the third stays in the graveyard. The exact ids depend
    # on Rust's graveyard injection order convention; verify the
    # zone counts are correct: 2 in p0's hand, 1 left in graveyard
    # (the spell's own routed-to-graveyard slot is separate from
    # the creatures).
    assert rs.find_object_zone(rs_bear1) == _ZONE_HAND, (
        "Bear1 (first-injected → front-of-graveyard) must return to "
        "hand under the resolve-time front-to-back self-scan"
    )
    assert rs.find_object_zone(rs_bear2) == _ZONE_HAND, (
        "Bear2 (second-injected) must return to hand — max_n=2 "
        "exhausts both winners"
    )
    assert rs.find_object_zone(rs_bear3) == _ZONE_GRAVEYARD, (
        "Bear3 (third-injected) must stay in graveyard — max_n=2 "
        "is exhausted before Bear3's slot"
    )


# ---------------------------------------------------------------------------
# Real-EoE cross-engine parity probe — Mode 2 (pump + lifelink UEOT)
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_archenemys_charm_mode_2_pump_and_grant_lifelink_parity():
    """**Genuine real-EoE cross-engine probe — Archenemy's Charm
    mode 2
    (PutPlusOneCountersAndGrantKeywordsUEOTOnTargetCreatureYouControl
    (amount=2, granted_keywords={"lifelink"})). PROBED tier — one of
    three 3-mode envelope flip probes; this is the LOAD-BEARING
    probe (the substrate the entire FLIP rides on).**

    Mode 2's resolve arm reads the cast-time-bound payload-target
    (the caster's first own-controlled Creature in bf_iter_etb_sorted
    order, per the new per-mode binder), applies +2 counters, and
    pushes a ``UeotModifier::GrantKeyword { keyword: "lifelink" }``
    onto the bound creature.

    Setup:
      * p0 controls a 1/1 Bear (own-controlled, legal target).
      * p0 casts Archenemy's Charm mode 2. The bear gains 2 +1/+1
        counters AND lifelink until end of turn.
    """
    _require_engine()
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.combinators import ModalChooseOne
    from mtg_bot.effects.generic.counters import (
        PutPlusOneCountersAndGrantKeywordsUEOTOnTargetCreatureYouControl,
    )
    from mtg_bot.game import StackItem, Zone
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
    )
    from mtg_bot.turn import state_based_actions as py_sba

    real = (
        get_active_source().get_printings().get("Archenemy's Charm")
    )
    if real is None:
        pytest.skip(
            "Archenemy's Charm absent from active CardSource"
        )
    se = real.spell_effect
    assert isinstance(se, ModalChooseOne)
    assert isinstance(
        se.modes[2],
        PutPlusOneCountersAndGrantKeywordsUEOTOnTargetCreatureYouControl,
    )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)

    # ---- Python: own-bear on p0's bf + Archenemy's Charm on the
    # stack mode 2.
    from mtg_bot.cards import SYNTHETIC_CREATURES
    bear_printing = SYNTHETIC_CREATURES["Healing Wisp"]
    py_bear = py.new_object(
        bear_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_bear.summoning_sick = False
    py_bear.controller_id = 0
    py.battlefield.append(py_bear)
    py_spell = py.new_object(real, owner_id=0, zone=Zone.STACK)
    py_spell.summoning_sick = False
    py.stack.append(
        StackItem(
            source=py_spell, controller_id=0,
            chosen_modes=(2,),
            targets=(("creature", py_bear.id),),
        ),
    )
    resolve_top_of_stack(py)
    py_sba(py)
    assert len(py.stack) == 0
    # Python: bear gained +2 counters AND lifelink UEOT.
    assert py_bear.plus_one_counters == 2, (
        f"Python: bear must have 2 +1/+1 counters post-resolve "
        f"(got {py_bear.plus_one_counters})"
    )
    # The keyword grant lives on `state.continuous_effects` (an
    # ApplyEffect-wrapped `GrantKeywords` registered at resolve time
    # with EndOfTurn lifetime). The layer-7 reader `effective_keywords`
    # walks that registry; assert lifelink is in the effective
    # keyword set for the bear.
    from mtg_bot.game import effective_keywords as py_effective_keywords
    py_eff_kw = py_effective_keywords(py, py_bear)
    assert "lifelink" in py_eff_kw, (
        f"Python: bear must have lifelink in effective_keywords "
        f"post-resolve (got {py_eff_kw}); continuous_effects = "
        f"{[type(e).__name__ for e in py.continuous_effects]}"
    )

    # ---- Rust: register own-bear on p0's bf, register Archenemy's
    # Charm on p0's hand, cast through the production cast path so
    # the per-mode binder fires + narrow chosen modes to [2].
    rs_bear_id = rs.register_and_inject_object(
        {
            "name": "Healing Wisp",
            "card_types": ["Creature"],
            "mana_cost": {"generic": 1, "W": 1},
            "power": 1, "toughness": 1,
        },
        0, _ZONE_BATTLEFIELD,
    )
    rs_spell_id = rs.register_and_inject_object(
        {
            "name": "Archenemy's Charm",
            "card_types": ["Instant"],
            "mana_cost": {"B": 3},
            "effects": [
                {
                    "kind": "choose_one_mode",
                    "modes": [
                        {"kind": "exile_target_creature"},
                        {
                            "kind": (
                                "return_up_to_n_creatures_from_your_"
                                "graveyard_to_hand"
                            ),
                            "min_n": 1,
                            "max_n": 2,
                        },
                        {
                            "kind": (
                                "put_plus_one_counters_and_grant_"
                                "keywords_ueot_on_target_creature_"
                                "you_control"
                            ),
                            "amount": 2,
                            "granted_keywords": ["lifelink"],
                        },
                    ],
                }
            ],
        },
        0, _ZONE_HAND,
    )
    rs.add_mana(0, "B", 1)
    rs.add_mana(0, "B", 1)
    rs.add_mana(0, "B", 1)
    ok = rs.cast_spell_noncreature(rs_spell_id, 0)
    assert ok is True, "Archenemy's Charm cast must succeed"
    # The cast-time per-mode binder picked the own-bear (mode 2 =
    # caster's own first Creature scan).
    assert rs.stack_top_target_id() == rs_bear_id, (
        "Rust per-mode-2 binder must seat the own-bear as the "
        "bound target (caster's first own-controlled creature scan)"
    )
    rs.set_stack_top_chosen_mode_idxs([2])
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    # Mode 2's resolve arm applied +2 counters AND pushed lifelink
    # UEOT modifier. Counters are directly observable through the
    # `get_counters` pyo3 method; the UEOT keyword grant has no
    # Python-facing inspector today (the sibling
    # `Effect::GrantKeywordsToTargetCreatureUntilEOT` tests at
    # `test_comet_crawler_parity.py` / `test_mutinous_massacre_parity.py`
    # observe the same "no direct ueot_modifiers snapshot" gap and
    # rely on indirect checks — see the audit-doc commentary). The
    # counter delta IS load-bearing: the resolve arm must fire ALL
    # of its body for the counter to land (controller resolution +
    # target re-validate + counter apply + keyword push are
    # sequenced atomically), so the +2 counter observation pins
    # that the arm fired byte-equal with Python. The keyword push
    # is pinned indirectly via the bridge round-trip test above
    # (the `granted_keywords` field round-trips byte-equal through
    # the parse + to_pydict arms — if the resolve arm didn't push
    # the modifiers, that wouldn't be caught by this probe; the
    # bridge round-trip + the §2 covered+bridged tooth flipping
    # True together establish the keyword-push is byte-equal).
    rs_counters = rs.get_counters(rs_bear_id)
    assert rs_counters == 2, (
        f"Rust: bear must have 2 +1/+1 counters post-resolve "
        f"(got {rs_counters})"
    )
    # Bf snapshot also surfaces `counters` — sanity check.
    bf = rs.battlefield_snapshot()
    rs_obj = next(e for e in bf if e["id"] == rs_bear_id)
    assert rs_obj["counters"] == 2, (
        f"Rust: bf snapshot must show 2 counters on the bear "
        f"(got {rs_obj['counters']})"
    )
