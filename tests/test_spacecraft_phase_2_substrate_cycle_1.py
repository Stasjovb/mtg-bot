"""**Spacecraft Station substrate — Phase 2 Cycle 1 (Rust substrate; Lumen-
Class Frigate, 2026-05-25).**

Lane: ``feature/spacecraft-phase-2-cycle-1-substrate-p1``.

Cycle 1 of the Spacecraft Station substrate Phase 2 campaign per
``docs/SPACECRAFT_STATION_SUBSTRATE_PHASE_2_DESIGN.md`` (1,349 lines,
2026-05-25, scoping commit ``b191475e``). Phase 2 admits ONLY sub-shape
B — Lumen-Class Frigate (1 card, the sole single-anthem-only
Spacecraft in the EoE pool, on top of the Phase-1 sub-shape A
substrate that landed in commits ``ea9aa996`` → ``62e10ff9`` →
``e9a31c83`` → ``7e07400f`` 2026-05-25).

**Cycle 1 (this slice — Rust substrate landing).**

  * New ``condition_tag`` dispatcher arm
    ``"source_charge_counters_at_least"`` in
    :func:`static_anthem_condition_matches` at
    ``rust/src/state_ops_combat.rs:737-810``. Signature widens to
    accept the SOURCE :class:`GameObject` reference so the new arm
    can read ``source.charge_counters`` (the OTHER two arms — empty
    string + ``during_your_turn`` — ignore ``source`` and stay
    bit-equivalent to pre-Phase-2 behavior on Phase-1 / MTL Phase-4
    payloads).
  * Caller-site pass-through at the two reader sites that walk
    anthems on the source's controller's battlefield:
    :func:`static_anthem_grants_keyword_to`
    (``state_ops_combat.rs:661-710``; sibling layer-6 keyword fold)
    and :func:`static_anthem_pt_bonus_for`
    (``state_ops_combat.rs:769-810``; layer-7c P/T fold). Both
    already iterate ``for source in source_player.battlefield``;
    the widen threads the loop variable into the dispatcher call.
  * Parser whitelist widen at
    ``rust/src/cards.rs:15191`` — the registry-build reject branch
    now accepts ``"source_charge_counters_at_least"`` in addition
    to the empty string + ``"during_your_turn"`` Phase-1 / MTL-Phase-4
    arms. The error message lists all three accepted values so a
    bridge-vs-Rust disagreement still fails loud with a complete
    enumeration.

**Cycle 1 explicitly DOES NOT add (deferred to later cycles per the
design doc §7 sequencing table):**

  * NO Python bridge widen (the
    :func:`_static_anthem_condition_from_tag` rehydrator stays at
    its empty / ``during_your_turn`` arms; Cycle 2 widens).
  * NO admit predicate widen (the new
    :func:`_printing_is_bridge_phase_2_static_anthem_spacecraft`
    sibling lands in Cycle 2).
  * NO admit-set pin bump (Lumen-Class Frigate STAYS DECLINED at
    the loader admit gate post-Cycle-1; the substrate-only
    invariant pin in this module asserts that fact).
  * NO per-card real-EoE probe (Cycle 3 ships Scenarios A-D per
    design doc §6.3).

**What this module pins (substrate-only invariants).**

  1. **Rust parse arm — new tag round-trip.** A synthetic registry
     dict carrying a static_anthems entry with
     ``condition_tag="source_charge_counters_at_least"`` +
     ``condition_args=[2]`` registers on
     ``mtg_bot_engine.Registry.register_printing`` with no panic
     and surfaces the full 6-tuple via
     ``get_printing_static_anthems_full`` byte-identical to input
     (round-trip).
  2. **Rust parse arm — back-compat empty tag.** A registry dict
     omitting the condition_tag / condition_args keys parses to
     the empty-tag, empty-args default — Phase-1 / pre-Phase-4
     anthem carriers stay bit-identical.
  3. **Rust parse arm — back-compat during_your_turn tag.**
     MTL-shape entries (``condition_tag="during_your_turn"``,
     no args) round-trip unchanged post-widen.
  4. **Rust parse arm — unknown tag still rejected.** The
     whitelist's reject branch still triggers on a never-existed
     tag; the error message now lists all three accepted values.
  5. **Rust reader fold (P/T) — source-counter gate closed.** A
     Phase-2-shape anthem source (``tier_threshold=2``) with
     ``charge_counters=0`` contributes 0/0 to other creatures'
     effective P/T — the gate is closed.
  6. **Rust reader fold (P/T) — source-counter gate at threshold
     edge.** With ``charge_counters=1`` (one below threshold) the
     gate stays closed (0/0); with ``charge_counters=2`` (at
     threshold) the gate opens and the anthem's ``power_bonus``
     / ``toughness_bonus`` folds through.
  7. **Rust reader fold (P/T) — source-counter gate well above
     threshold.** With ``charge_counters=100`` (well above
     threshold) the gate stays open — the gate is monotonic
     non-decreasing on counters.
  8. **Rust reader fold (P/T) — other_-scope still excludes
     source.** Even with the gate open, the source itself does
     NOT receive the anthem (``other_creatures_you_control``
     scope; the source's own effective P/T stays at printed).
  9. **Rust reader fold (P/T) — cross-controller still rejects.**
     A Phase-2 anthem on P0's battlefield does NOT fold onto a
     creature on P1's battlefield, regardless of counter state.
  10. **Rust reader fold (keyword) — source-counter gate closed.**
      A Phase-2-shape anthem source with
      ``granted_keywords=["flying"]`` + ``tier_threshold=2`` +
      ``charge_counters=0`` does NOT grant flying to other
      creatures — the gate is closed.
  11. **Rust reader fold (keyword) — source-counter gate open.**
      Same anthem with ``charge_counters=2`` (≥ threshold) DOES
      grant flying. The keyword fold rides the SAME dispatcher
      arm as the P/T fold.
  12. **Phase-1 unconditional anthem unchanged by Phase-2
      substrate.** A Phase-1 anthem (``condition_tag=""``) with
      a source at any ``charge_counters`` value contributes its
      P/T unconditionally — the empty-tag arm short-circuits
      before reading source counters, bit-equivalent to
      pre-Phase-2.
  13. **MTL Phase-4 anthem unchanged by Phase-2 substrate.** A
      ``during_your_turn``-shape anthem still fires only when the
      source's controller is the active player; the dispatcher
      ignores ``charge_counters`` for this tag, bit-equivalent to
      pre-Phase-2.

Tests follow the structure of
``test_memorial_team_leader_substrate_cycle_1.py`` (MTL Cycle 1
substrate) and ``test_spacecraft_phase_1_substrate_cycle_2.py``
(Phase 1 Cycle 2 substrate). Synthetic registry dicts are used
throughout — Cycle 1 does NOT depend on the live Lumen-Class
Frigate printing (Cycle 3 owns the real-EoE probe).
"""

from __future__ import annotations

import importlib.util

import pytest


def _require_engine():
    if importlib.util.find_spec("mtg_bot_engine") is None:
        pytest.skip("mtg_bot_engine PyO3 extension not installed")


_ZONE_BATTLEFIELD = 2


# A Lumen-Class-Frigate-shaped synthetic anthem source. The source's
# anthem fires only when `source.charge_counters >= 2`.
_LUMEN_LIKE_PRINTING = {
    "name": "Spacecraft Phase 2 Cycle 1 Substrate -- Lumen-like anthem source",
    "card_types": ["Creature"],
    "mana_cost": {"W": 1, "generic": 1},
    "power": 3,
    "toughness": 5,
    "static_anthems": [
        {
            "scope": "other_creatures_you_control",
            "granted_keywords": [],
            "power_bonus": 1,
            "toughness_bonus": 1,
            "condition_tag": "source_charge_counters_at_least",
            "condition_args": [2],
        },
    ],
}


# A Phase-2 anthem source that ALSO grants a keyword (flying) when
# the gate opens. This shape is not in the live EoE pool today, but
# the keyword fold rides the SAME dispatcher arm as the P/T fold —
# pin #10 / #11 exercise the layer-6 keyword fold separately from
# the layer-7c P/T fold so a future composed-shape printing can
# fan in cleanly.
_LUMEN_LIKE_PRINTING_KEYWORD = {
    "name": "Spacecraft Phase 2 Cycle 1 Substrate -- Lumen-like keyword anthem",
    "card_types": ["Creature"],
    "mana_cost": {"W": 1, "generic": 1},
    "power": 3,
    "toughness": 5,
    "static_anthems": [
        {
            "scope": "other_creatures_you_control",
            "granted_keywords": ["flying"],
            "power_bonus": 0,
            "toughness_bonus": 0,
            "condition_tag": "source_charge_counters_at_least",
            "condition_args": [2],
        },
    ],
}


_BEAR_PRINTING = {
    "name": "Spacecraft Phase 2 Cycle 1 Substrate -- 2/2 Bear",
    "card_types": ["Creature"],
    "mana_cost": {"G": 1, "generic": 1},
    "power": 2,
    "toughness": 2,
}


# A Phase-1 unconditional anthem source (Tannuk-shape; back-compat
# 2-tuple bridge shape but expressed here as the 6-tuple registry
# dict with `condition_tag=""`). Used for pin #12.
_PHASE_1_UNCOND_ANTHEM = {
    "name": "Spacecraft Phase 2 Cycle 1 Substrate -- Phase-1 unconditional anthem",
    "card_types": ["Creature"],
    "mana_cost": {"R": 2, "generic": 2},
    "power": 3,
    "toughness": 5,
    "static_anthems": [
        {
            "scope": "other_creatures_you_control",
            "granted_keywords": [],
            "power_bonus": 1,
            "toughness_bonus": 0,
            "condition_tag": "",
            "condition_args": [],
        },
    ],
}


# An MTL-shape anthem source (``during_your_turn`` tag). Used for
# pin #13.
_MTL_LIKE_PRINTING = {
    "name": "Spacecraft Phase 2 Cycle 1 Substrate -- MTL-like during-your-turn anthem",
    "card_types": ["Creature"],
    "mana_cost": {"R": 1, "generic": 3},
    "power": 4,
    "toughness": 3,
    "static_anthems": [
        {
            "scope": "other_creatures_you_control",
            "granted_keywords": [],
            "power_bonus": 1,
            "toughness_bonus": 0,
            "condition_tag": "during_your_turn",
            "condition_args": [],
        },
    ],
}


# ---------------------------------------------------------------------------
# Pin 1-4 — Rust parse arm round-trip + back-compat + reject
# ---------------------------------------------------------------------------


def test_pin1_rust_registry_round_trips_source_charge_counters_at_least_tag():
    """**Pin #1 — Rust parse arm new-tag round-trip.**

    A registry dict carrying ``condition_tag=
    "source_charge_counters_at_least"`` + ``condition_args=[2]``
    registers on ``Registry.register_printing`` with no panic and
    surfaces the full 6-tuple via
    ``get_printing_static_anthems_full`` byte-identical to input.
    """
    _require_engine()
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(_LUMEN_LIKE_PRINTING)
    full = reg.get_printing_static_anthems_full(pid)
    assert full == [
        (
            "other_creatures_you_control",
            [],
            1,
            1,
            "source_charge_counters_at_least",
            [2],
        ),
    ]


def test_pin2_rust_registry_back_compat_empty_tag_unchanged():
    """**Pin #2 — back-compat: omitted condition_tag / args.**

    A registry dict omitting the condition_tag / condition_args keys
    (the Phase-1 anthem-carrier shape — every pre-MTL anthem in the
    EoE pool) parses to the empty-tag, empty-args default — Phase-1
    behavior stays bit-identical to pre-Phase-2.
    """
    _require_engine()
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing({
        "name": "Spacecraft Phase 2 Cycle 1 Substrate -- back-compat Phase-1 anthem",
        "card_types": ["Creature"],
        "mana_cost": {"R": 2, "generic": 2},
        "power": 3,
        "toughness": 5,
        "static_anthems": [
            {
                "scope": "other_creatures_you_control",
                "granted_keywords": ["haste"],
            },
        ],
    })
    full = reg.get_printing_static_anthems_full(pid)
    assert full == [
        ("other_creatures_you_control", ["haste"], 0, 0, "", []),
    ]


def test_pin3_rust_registry_back_compat_during_your_turn_unchanged():
    """**Pin #3 — back-compat: ``during_your_turn`` tag unchanged.**

    MTL Phase-4 carriers (``condition_tag="during_your_turn"``) round-
    trip unchanged post-Phase-2 widen.
    """
    _require_engine()
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(_MTL_LIKE_PRINTING)
    full = reg.get_printing_static_anthems_full(pid)
    assert full == [
        (
            "other_creatures_you_control",
            [],
            1,
            0,
            "during_your_turn",
            [],
        ),
    ]


def test_pin4_rust_registry_rejects_unknown_anthem_condition_tag():
    """**Pin #4 — whitelist still rejects unknown tag.**

    The parser whitelist's reject branch still triggers on a
    never-existed tag; post-Phase-2 the accepted set is `""`,
    `"during_your_turn"`, `"source_charge_counters_at_least"` — any
    other tag fails loudly with an error message listing all three.
    """
    _require_engine()
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    with pytest.raises(ValueError) as exc:
        reg.register_printing({
            "name": "Bad-Anthem-Phase2",
            "card_types": ["Creature"],
            "mana_cost": {"R": 1},
            "power": 2,
            "toughness": 2,
            "static_anthems": [
                {
                    "scope": "other_creatures_you_control",
                    "granted_keywords": [],
                    "power_bonus": 1,
                    "condition_tag": "never_your_turn",
                    "condition_args": [],
                },
            ],
        })
    msg = str(exc.value)
    assert "condition_tag" in msg
    assert "source_charge_counters_at_least" in msg, (
        "Error message must enumerate the new Phase-2 tag so a "
        "bridge-vs-Rust disagreement fails loud with the full "
        "accepted set."
    )


# ---------------------------------------------------------------------------
# Pin 5-9 — Rust reader fold (P/T) source-counter gate
# ---------------------------------------------------------------------------


def _inject_anthem_source_with_charge_counters(rs, printing_dict, owner, ccs):
    """Inject the anthem-source object on owner's battlefield with the
    requested ``charge_counters`` value. Returns the new object id.
    """
    src_id = rs.register_and_inject_object(printing_dict, owner, _ZONE_BATTLEFIELD)
    rs.set_charge_counters(src_id, ccs)
    assert rs.get_charge_counters(src_id) == ccs
    return src_id


def test_pin5_anthem_pt_gate_closed_at_zero_counters():
    """**Pin #5 — P/T fold closed at ``charge_counters=0``.**

    A Phase-2-shape anthem source with ``tier_threshold=2`` and
    ``charge_counters=0`` contributes 0/0 to other creatures' effective
    P/T — the gate is closed; the bear stays at its printed 2/2.
    """
    _require_engine()
    import mtg_bot_engine

    rs = mtg_bot_engine.make_synthetic_state(0, 0, 0)
    _inject_anthem_source_with_charge_counters(
        rs, _LUMEN_LIKE_PRINTING, owner=0, ccs=0,
    )
    bear_id = rs.register_and_inject_object(_BEAR_PRINTING, 0, _ZONE_BATTLEFIELD)
    rs.set_active_player(0)
    # Gate closed → printed P/T.
    assert rs.effective_power(bear_id) == 2
    assert rs.effective_toughness(bear_id) == 2


def test_pin6_anthem_pt_gate_edge_one_below_then_at_threshold():
    """**Pin #6 — P/T fold edge: one below threshold then at.**

    With ``charge_counters=1`` (one below the ``tier_threshold=2`` gate)
    the gate stays closed; with ``charge_counters=2`` (at the threshold)
    the gate opens. The bear's effective P/T flips from (2, 2) to
    (3, 3) byte-equal.
    """
    _require_engine()
    import mtg_bot_engine

    rs = mtg_bot_engine.make_synthetic_state(0, 0, 0)
    src_id = _inject_anthem_source_with_charge_counters(
        rs, _LUMEN_LIKE_PRINTING, owner=0, ccs=1,
    )
    bear_id = rs.register_and_inject_object(_BEAR_PRINTING, 0, _ZONE_BATTLEFIELD)
    rs.set_active_player(0)
    # ccs=1 < threshold=2 → still gated closed.
    assert rs.effective_power(bear_id) == 2
    assert rs.effective_toughness(bear_id) == 2
    # Flip to ccs=2 → gate opens.
    rs.set_charge_counters(src_id, 2)
    assert rs.effective_power(bear_id) == 3
    assert rs.effective_toughness(bear_id) == 3


def test_pin7_anthem_pt_gate_well_above_threshold():
    """**Pin #7 — P/T fold monotonic non-decreasing above threshold.**

    With ``charge_counters=100`` (well above the threshold) the gate
    stays open. The condition reads ``>=``, not ``==``, so any value
    at-or-above threshold fires.
    """
    _require_engine()
    import mtg_bot_engine

    rs = mtg_bot_engine.make_synthetic_state(0, 0, 0)
    _inject_anthem_source_with_charge_counters(
        rs, _LUMEN_LIKE_PRINTING, owner=0, ccs=100,
    )
    bear_id = rs.register_and_inject_object(_BEAR_PRINTING, 0, _ZONE_BATTLEFIELD)
    rs.set_active_player(0)
    assert rs.effective_power(bear_id) == 3
    assert rs.effective_toughness(bear_id) == 3


def test_pin8_anthem_pt_gate_open_other_scope_still_excludes_source():
    """**Pin #8 — ``other_creatures_you_control`` scope excludes source
    even with the gate open.**

    With the source's gate open at ``charge_counters=2``, the source
    itself does NOT receive the anthem fold (scope is
    ``other_creatures_you_control``). The source's printed (3, 5)
    stays unchanged.
    """
    _require_engine()
    import mtg_bot_engine

    rs = mtg_bot_engine.make_synthetic_state(0, 0, 0)
    src_id = _inject_anthem_source_with_charge_counters(
        rs, _LUMEN_LIKE_PRINTING, owner=0, ccs=2,
    )
    bear_id = rs.register_and_inject_object(_BEAR_PRINTING, 0, _ZONE_BATTLEFIELD)
    rs.set_active_player(0)
    # Bear (other) DOES receive: 2 + 1 = 3.
    assert rs.effective_power(bear_id) == 3
    assert rs.effective_toughness(bear_id) == 3
    # Source (self) does NOT receive: stays printed (3, 5).
    assert rs.effective_power(src_id) == 3
    assert rs.effective_toughness(src_id) == 5


def test_pin9_anthem_pt_gate_open_cross_controller_still_rejects():
    """**Pin #9 — cross-controller scope still rejects.**

    A Phase-2 anthem on P0's battlefield does NOT fold onto a creature
    on P1's battlefield, regardless of counter state — the scope is
    "you control", which restricts the fold to permanents under the
    SAME controller as the source.
    """
    _require_engine()
    import mtg_bot_engine

    rs = mtg_bot_engine.make_synthetic_state(0, 0, 0)
    _inject_anthem_source_with_charge_counters(
        rs, _LUMEN_LIKE_PRINTING, owner=0, ccs=2,
    )
    # P1's bear — different controller from the anthem source.
    bear_id = rs.register_and_inject_object(_BEAR_PRINTING, 1, _ZONE_BATTLEFIELD)
    rs.set_active_player(0)
    # P1's bear stays printed (2, 2) — no cross-controller fold.
    assert rs.effective_power(bear_id) == 2
    assert rs.effective_toughness(bear_id) == 2


# ---------------------------------------------------------------------------
# Pin 10-11 — Rust reader fold (keyword) source-counter gate
# ---------------------------------------------------------------------------


def test_pin10_anthem_keyword_gate_closed_at_zero_counters():
    """**Pin #10 — keyword fold closed at ``charge_counters=0``.**

    A Phase-2-shape anthem source carrying ``granted_keywords=
    ["flying"]`` and ``tier_threshold=2`` does NOT grant flying when
    ``charge_counters=0`` — the layer-6 keyword fold rides the same
    dispatcher arm as the layer-7c P/T fold; both gates flip together.
    """
    _require_engine()
    import mtg_bot_engine

    rs = mtg_bot_engine.make_synthetic_state(0, 0, 0)
    _inject_anthem_source_with_charge_counters(
        rs, _LUMEN_LIKE_PRINTING_KEYWORD, owner=0, ccs=0,
    )
    bear_id = rs.register_and_inject_object(_BEAR_PRINTING, 0, _ZONE_BATTLEFIELD)
    rs.set_active_player(0)
    # Gate closed → bear does NOT have flying.
    assert rs.has_keyword(bear_id, "flying") is False


def test_pin11_anthem_keyword_gate_open_at_threshold():
    """**Pin #11 — keyword fold opens at-threshold.**

    Same anthem at ``charge_counters=2`` grants flying. The keyword
    fold rides the same dispatcher as the P/T fold, so the gate flip
    is observable on both axes simultaneously.
    """
    _require_engine()
    import mtg_bot_engine

    rs = mtg_bot_engine.make_synthetic_state(0, 0, 0)
    _inject_anthem_source_with_charge_counters(
        rs, _LUMEN_LIKE_PRINTING_KEYWORD, owner=0, ccs=2,
    )
    bear_id = rs.register_and_inject_object(_BEAR_PRINTING, 0, _ZONE_BATTLEFIELD)
    rs.set_active_player(0)
    # Gate open → bear DOES have flying.
    assert rs.has_keyword(bear_id, "flying") is True


# ---------------------------------------------------------------------------
# Pin 12-13 — Non-regression: Phase-1 + MTL Phase-4 anthems unchanged
# ---------------------------------------------------------------------------


def test_pin12_phase_1_unconditional_anthem_unchanged_by_phase_2_substrate():
    """**Pin #12 — Phase-1 unconditional anthem unchanged.**

    A Phase-1 anthem (``condition_tag=""``) on a source with ANY
    ``charge_counters`` value contributes its P/T unconditionally —
    the empty-tag arm in the dispatcher short-circuits BEFORE reading
    source counters, bit-equivalent to pre-Phase-2 behavior. This is
    the load-bearing back-compat pin for every Phase-1 anthem in the
    EoE pool (Tannuk Steadfast Second + the others) — the signature
    widen must not change their fold.
    """
    _require_engine()
    import mtg_bot_engine

    rs = mtg_bot_engine.make_synthetic_state(0, 0, 0)
    # Inject the unconditional anthem with ccs=0; the fold MUST fire
    # regardless of counter state because the gate is unconditional.
    _inject_anthem_source_with_charge_counters(
        rs, _PHASE_1_UNCOND_ANTHEM, owner=0, ccs=0,
    )
    bear_id = rs.register_and_inject_object(_BEAR_PRINTING, 0, _ZONE_BATTLEFIELD)
    rs.set_active_player(0)
    # Phase-1 anthem: +1/+0. Bear flips 2/2 → 3/2.
    assert rs.effective_power(bear_id) == 3
    assert rs.effective_toughness(bear_id) == 2


def test_pin13_mtl_phase_4_during_your_turn_anthem_unchanged_by_phase_2_substrate():
    """**Pin #13 — MTL Phase-4 ``during_your_turn`` anthem unchanged.**

    The dispatcher's ``during_your_turn`` arm ignores
    ``source.charge_counters`` entirely. Post-Phase-2 widen, MTL-shape
    anthems still fire iff the source's controller is the active
    player — independent of counter state. The signature widen must
    not regress MTL's reader fold.
    """
    _require_engine()
    import mtg_bot_engine

    rs = mtg_bot_engine.make_synthetic_state(0, 0, 0)
    # Inject the MTL-shape anthem with a non-zero ccs value to prove
    # the new arg has no effect on the during_your_turn arm.
    _inject_anthem_source_with_charge_counters(
        rs, _MTL_LIKE_PRINTING, owner=0, ccs=100,
    )
    bear_id = rs.register_and_inject_object(_BEAR_PRINTING, 0, _ZONE_BATTLEFIELD)
    # On P0's turn → MTL gate open → +1/+0 fold.
    rs.set_active_player(0)
    assert rs.effective_power(bear_id) == 3
    assert rs.effective_toughness(bear_id) == 2
    # On P1's turn → MTL gate closed → printed 2/2.
    rs.set_active_player(1)
    assert rs.effective_power(bear_id) == 2
    assert rs.effective_toughness(bear_id) == 2


# ---------------------------------------------------------------------------
# Substrate-only invariant — Lumen-Class Frigate STAYS DECLINED at admit gate
# ---------------------------------------------------------------------------


def test_lumen_class_frigate_stays_declined_at_admit_gate_post_cycle_1():
    """**LOAD-BEARING substrate-only invariant pin.**

    Cycle 1 lands the Rust substrate ONLY — the Python bridge widen,
    the new admit predicate, and the OR-chain disjunct registration
    all ship in Cycle 2. Lumen-Class Frigate's live ``CardPrinting``
    must STAY DECLINED at every existing admit predicate disjunct
    after Cycle 1 — every Cycle-1-shipped Rust change is gated behind
    a parser-whitelist arm that is unreachable from the deck loader
    until Cycle 2 widens the bridge emit + admit predicate.

    Cycle 2 is what flips this pin.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    src = get_active_source().get_printings()
    lumen = src.get("Lumen-Class Frigate")
    if lumen is None:
        pytest.skip("Lumen-Class Frigate absent from active CardSource")

    # Phase-1 sub-shape A predicate STILL rejects Lumen-Class Frigate —
    # the Phase-1 admit gates zero static abilities, but Lumen-Class
    # Frigate carries one anthem static (the Phase-2 carrier shape).
    assert (
        trajectory._printing_is_bridge_pure_station_spacecraft(lumen) is False
    ), (
        "Phase-1 sub-shape A predicate must positively reject Lumen-"
        "Class Frigate (carries one static_abilities entry; Phase-1's "
        "predicate gates on `printing.static_abilities` being empty)."
    )

    # MTL Phase-4 anthem-PT-conditional warp predicate STILL rejects
    # Lumen-Class Frigate — MTL's predicate gates on `warp_cost is not
    # None`, but Lumen-Class Frigate has no warp_cost.
    assert (
        trajectory._printing_is_bridge_static_anthem_pt_conditional_warp_creature(
            lumen,
        ) is False
    ), (
        "MTL Phase-4 anthem-PT-conditional warp predicate must reject "
        "Lumen-Class Frigate (no warp_cost). The Phase-2 admit "
        "predicate that DOES admit Lumen-Class Frigate is "
        "`_printing_is_bridge_phase_2_static_anthem_spacecraft`, which "
        "Cycle 2 lands."
    )

    # The new Phase-2 admit predicate is NOT yet present on
    # trajectory — Cycle 2 lands it. Cycle 1 substrate-only invariant:
    # the symbol must NOT exist yet (the predicate is the Cycle-2
    # FLIP marker; landing it in Cycle 1 would silently flip the
    # admit set before Cycle 2's bridge widen is in place).
    assert not hasattr(
        trajectory, "_printing_is_bridge_phase_2_static_anthem_spacecraft"
    ), (
        "Cycle 1 is substrate-only — the new admit predicate "
        "`_printing_is_bridge_phase_2_static_anthem_spacecraft` "
        "must land in Cycle 2 alongside the bridge widen + "
        "admit-set pin bump. Cycle 1 landing the predicate "
        "out-of-order would silently flip the admit set before "
        "the bridge emit / rehydrator widen is in place."
    )
