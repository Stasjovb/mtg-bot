"""Grove of the Burnwillows -- per-card real-EoE cross-engine byte-equal
probe (``covered_by_construction`` -> PROBED tier flip; Grove closure
marker).

Grove of the Burnwillows is a bare ``{T}``-cost DUAL-AA mana-ability
Land in the EoE pool:

    AA[0] -- ``{T}: Add {C}.``
        cost = ActivationCost(tap_self=True)
        effect = AddManaToPool(produces=(("C", 1),))
        is_mana_ability = True

    AA[1] -- ``{T}: Add {R} or {G}. Each opponent gains 1 life.``
        cost = ActivationCost(tap_self=True)
        effect = Sequence(
            AddNManaOfChosenColor(amount=1, options=("R", "G")),
            GrantLifeToEachOpponent(amount=1),
        )
        is_mana_ability = True

Grove is the LOAD-BEARING Sequence-IN-AA closure per
``docs/BLOCKED_TAIL_TRACTABILITY_SCOUT_2026-05-27.md`` §#3 Grove:

  * **The Sequence-IN-AA admit (the novel substrate).** The Carrier-AA
    Phase-1 Effect-class admit gate
    (``_carrier_aa_phase_1_effect_classes`` / the per-AA predicate
    ``_aa_is_phase1_sub_shape_a``) was LEAF-only -- it admitted an AA
    whose effect was a bare leaf in the admit set. Grove's AA[1] body
    is a ``Sequence`` (a combinator), not a bare leaf. The admit grew
    a recursive Sequence arm (``_carrier_aa_effect_class_admitted``)
    that admits a ``Sequence`` iff EVERY leaf is itself an admitted
    Phase-1 effect. This amortizes to any future Carrier-AA card with a
    multi-step Sequence resolve body whose leaves all admit.

  * **The two leaf Effect classes** (both added to the Phase-1 admit
    set this slice):
      - ``AddNManaOfChosenColor`` -- the Rust ``Effect::
        AddNManaOfChosenColor { amount, options }`` variant + parse +
        resolve + to_pydict have been live since the round-21 / Phase-
        4E mana-ability bridge slice; this slice adds the cross-engine
        forward arm + the Effect-class admit-set entry (the reverse arm
        already round-tripped).
      - ``GrantLifeToEachOpponent`` -- the NEW Rust ``Effect::
        GrantLifeToEachOpponent { amount }`` variant (parse + to_pydict
        + resolve: life-GAIN sister of ``each_opponent_loses_life``,
        with the ``life_gained_this_turn`` tracker increment mirroring
        Python's ``game.gain_life``) + cross-engine forward / reverse
        arms all ship this slice.

  * **The Sequence-in-AA bridge floor.** The forward arm
    ``cross_engine._python_aa_to_safe_dict`` emits ``{"kind":
    "sequence", "effects": [...]}`` by recursing each child through
    ``_carrier_aa_seq_leaf_to_dict`` (all-or-nothing -- a child with no
    forward arm declines the whole Sequence). The reverse arm at
    ``cross_engine.py:2543`` already recursed each child. Rust's
    ``Effect::Sequence { effects: Vec<Effect> }`` parse + resolve walk
    children in order.

**No no-agent-fallback color-picker divergence on the PROBE path.**
Unlike Meteor Crater C2 / Reflecting Pool C2 (both of which had a
WUBRG-canonical-vs-sorted-alphabetic color-picker divergence gated to
a multi-color board-walk union), Grove's
``AddNManaOfChosenColor(1, ("R", "G"))`` carries a FIXED 2-tuple
options list ``("R", "G")`` from the parser -- NOT a board-walk union.
Both engines pick ``options[0] = "R"`` under the no-agent fallback
(Python ``effects/generic/mana.py:115`` ``opts[0]``; Rust
``state_ops_resolve.rs:14055+`` first-option fallback), so both engines
deterministic-mint ``R`` byte-equal with NO seating constraint. The
``GrantLifeToEachOpponent`` leaf is fully fixed (amount=1).

**Scenario MINT-C (load-bearing AA[0] single-C mint).**
Grove on p0's bf at 20 life. Activate AA[0] on both engines.
Post-resolve byte-equal: p0's pool has exactly 1 C coin; both lives
untouched; stack empty (mana-ability bypass-stack); Grove tapped.

**Scenario MINT-R+LIFE (load-bearing AA[1] Sequence: chosen-color mint
+ each-opponent-life-gain).**
Grove on p0's bf at 20 life. Activate AA[1] on both engines. The
Sequence resolves both children in order: mint 1 R coin into p0's pool
(no-agent ``options[0]="R"`` fallback), THEN p1 (the one opponent)
gains 1 life (20 -> 21). Post-resolve byte-equal: p0's pool has exactly
1 R coin; p0's life unchanged (20); p1's life = 21; stack empty; Grove
tapped.

This module drives the ACTUAL parsed Grove printing on the Python side
(via ``get_active_source().get_printings()``) and the bridged
synthetic on the Rust side -- the SAME printing shape both engines read
(verified by the bridge round-trip pin below).

This module is the Grove of the Burnwillows closure marker; classified
by ``scripts/measure_pool_parity.py``'s ``PROBE_MODULES`` walk.
"""

from __future__ import annotations

import importlib.util

import pytest

from mtg_bot.cards.source import get_active_source
from mtg_bot.effects.combinators import Sequence
from mtg_bot.effects.generic.life import GrantLifeToEachOpponent
from mtg_bot.effects.generic.mana import (
    AddManaToPool,
    AddNManaOfChosenColor,
)


_PRINTINGS = get_active_source().get_printings()


# Skip Rust-engine probes if the extension isn't built -- mirrors the
# project-wide policy for cross-engine probes.
_rust_skip = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


# Zone constants (Rust int encoding -- same shape sibling probes use).
ZONE_HAND = 0
ZONE_LIBRARY = 1
ZONE_BATTLEFIELD = 2
ZONE_GRAVEYARD = 3


# Canonical Rust dict for Grove of the Burnwillows -- the EXACT shape
# ``_spec_card_to_printing_dict`` emits for the bridge forward arm
# (verified pre-flight via the bridge round-trip pin below). Both
# engines read this same printing shape.
#
# Note: the ``supertypes: ["Basic"]`` entry is the Carrier-AA-Land
# builder convention -- ``_spec_card_to_printing_dict`` emits "Basic"
# for every Carrier-AA Land regardless of the printing's actual super-
# type (verified against the Ancient Tomb / Reflecting Pool / Meteor
# Crater sibling probes which all carry the same "Basic" supertype on
# the Rust dict). The Rust engine doesn't gate on the supertype for the
# Carrier-AA mana-ability resolve, so this convention is harmless.
_GROVE_RUST_DICT = {
    "name": "Grove of the Burnwillows",
    "card_types": ["Land"],
    "mana_cost": {},
    "effects": [],
    "supertypes": ["Basic"],
    "activated_abilities": [
        {
            "cost": {"tap_self": True},
            "effect": {
                "kind": "add_mana_to_pool",
                "color": "C",
                "amount": 1,
            },
            "is_mana_ability": True,
        },
        {
            "cost": {"tap_self": True},
            "effect": {
                "kind": "sequence",
                "effects": [
                    {
                        "kind": "add_n_mana_of_chosen_color",
                        "amount": 1,
                        "options": ["R", "G"],
                    },
                    {
                        "kind": "grant_life_to_each_opponent",
                        "amount": 1,
                    },
                ],
            },
            "is_mana_ability": True,
        },
    ],
}


_EMPTY_MANA_POOL = {
    "W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0, "any": 0,
}


# ---------------------------------------------------------------------------
# (1) Parser SoT -- Grove is parser-claimed and emits the expected
# dual-AA mana-ability shape (re-asserted here so this module is self-
# contained for the PROBED-tier evidence).
# ---------------------------------------------------------------------------


def test_grove_parser_claims_card():
    """Pins the active CardSource is producing the Grove printing under
    its canonical EoE name.
    """
    assert "Grove of the Burnwillows" in _PRINTINGS, (
        "Grove of the Burnwillows must be parser-claimed by the active "
        "CardSource (EoE set + reprint coverage)"
    )


def test_grove_printed_attrs():
    """Pins the basic printing surface: bare Land (no super/subtype),
    cost ``{0}``, no power/toughness, no keywords/triggers/statics, two
    AAs -- AA[0] the ``AddManaToPool({C})`` shape, AA[1] the
    ``Sequence(AddNManaOfChosenColor(1, ('R','G')),
    GrantLifeToEachOpponent(1))`` shape, both bare ``{T}`` cost +
    ``is_mana_ability=True``. The §2 teeth -- the admit predicate's
    load-bearing gates (including the Sequence-IN-AA admit).
    """
    p = _PRINTINGS["Grove of the Burnwillows"]
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
    assert p.warp_cost is None
    # The §2 teeth -- TWO mana AAs.
    assert len(p.activated_abilities) == 2

    # AA[0] -- {T}: Add {C}.
    aa0 = p.activated_abilities[0]
    assert aa0.cost.tap_self is True
    assert aa0.cost.mana is None
    assert aa0.cost.sacrifice_self is False
    assert isinstance(aa0.effect, AddManaToPool)
    assert aa0.effect.produces == (("C", 1),)
    assert aa0.is_mana_ability is True
    assert aa0.sorcery_speed is False
    assert aa0.tier_threshold == 0
    assert aa0.activate_only_once is False

    # AA[1] -- {T}: Add {R} or {G}. Each opponent gains 1 life.
    aa1 = p.activated_abilities[1]
    assert aa1.cost.tap_self is True
    assert aa1.cost.mana is None
    assert aa1.cost.sacrifice_self is False
    assert isinstance(aa1.effect, Sequence)
    assert len(aa1.effect.effects) == 2
    leaf0, leaf1 = aa1.effect.effects
    assert isinstance(leaf0, AddNManaOfChosenColor)
    assert leaf0.amount == 1
    assert leaf0.options == ("R", "G")
    assert isinstance(leaf1, GrantLifeToEachOpponent)
    assert leaf1.amount == 1
    assert aa1.is_mana_ability is True
    assert aa1.sorcery_speed is False
    assert aa1.tier_threshold == 0
    assert aa1.activate_only_once is False


# ---------------------------------------------------------------------------
# (2) Bridge round-trip -- the forward arm
# ``_spec_card_to_printing_dict`` on the genuine parsed Grove printing
# emits the canonical Rust registry dict carrying BOTH AAs (the
# ``add_mana_to_pool`` AA[0] + the ``sequence`` AA[1] with the
# ``add_n_mana_of_chosen_color`` + ``grant_life_to_each_opponent``
# leaves). Reverse arm rehydrates byte-equal.
# ---------------------------------------------------------------------------


def test_grove_bridge_round_trip_canonical_rust_dict():
    """Grove's printing -> ``_filter_deck_to_bridge_supported`` ->
    CardDef -> ``_spec_card_to_printing_dict`` -> canonical Rust
    registry dict matches ``_GROVE_RUST_DICT`` byte-equal. Pins the
    probe's source-of-truth that both engines read the SAME printing
    shape. Reverse-arm pin: each AA dict rehydrates to a Python
    ActivatedAbility carrying the same effect class tree byte-equal.
    """
    from mtg_bot.parity.trajectory import _filter_deck_to_bridge_supported
    from mtg_bot.parity.cross_engine import (
        _aa_dict_to_python_activated_ability,
        _spec_card_to_printing_dict,
    )

    filt, defs = _filter_deck_to_bridge_supported(
        ["Grove of the Burnwillows"], _PRINTINGS,
    )
    assert filt == ["Grove of the Burnwillows"], (
        "Grove must pass the bridge admit gate post-FLIP (the Sequence-"
        "IN-AA admit + the two leaf-class widens)"
    )
    assert len(defs) == 1
    cd = defs[0]
    pd = _spec_card_to_printing_dict(cd)
    assert pd == _GROVE_RUST_DICT, (
        f"Grove Rust registry dict must match the probe's pinned shape "
        f"(the bridge SoT for both engines); got pd={pd!r}, "
        f"expected={_GROVE_RUST_DICT!r}"
    )

    # Reverse-arm pin: AA[0] rehydrates to AddManaToPool({C}).
    aa0_py = _aa_dict_to_python_activated_ability(
        pd["activated_abilities"][0]
    )
    assert isinstance(aa0_py.effect, AddManaToPool)
    assert aa0_py.effect.produces == (("C", 1),)
    assert aa0_py.cost.tap_self is True
    assert aa0_py.is_mana_ability is True

    # Reverse-arm pin: AA[1] rehydrates to the Sequence tree.
    aa1_py = _aa_dict_to_python_activated_ability(
        pd["activated_abilities"][1]
    )
    assert isinstance(aa1_py.effect, Sequence)
    leaf0, leaf1 = aa1_py.effect.effects
    assert isinstance(leaf0, AddNManaOfChosenColor)
    assert leaf0.amount == 1
    assert leaf0.options == ("R", "G")
    assert isinstance(leaf1, GrantLifeToEachOpponent)
    assert leaf1.amount == 1
    assert aa1_py.cost.tap_self is True
    assert aa1_py.is_mana_ability is True


# ---------------------------------------------------------------------------
# (3) Rust acceptance smoke -- the canonical Grove Rust dict parses on
# ``register_printing`` (the bridge contract Rust honors).
# ---------------------------------------------------------------------------


@_rust_skip
def test_rust_parser_accepts_canonical_grove_dict():
    """Lockstep pin: Rust's parse arm accepts the canonical Grove
    registry-dict shape ``_GROVE_RUST_DICT`` -- the SAME dict the
    forward emit arm produces for the live printing (including the
    nested ``sequence`` effect with the ``add_n_mana_of_chosen_color``
    + ``grant_life_to_each_opponent`` children).
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(_GROVE_RUST_DICT)
    assert isinstance(pid, int)
    assert reg.get_printing_name(pid) == "Grove of the Burnwillows"


# ---------------------------------------------------------------------------
# (4) Loader end-to-end admit -- Grove admits at the deck-level filter
# post-FLIP (the FLIP marker mirror).
# ---------------------------------------------------------------------------


def test_grove_loader_end_to_end_admit():
    """End-to-end loader admit: pass ``["Grove of the Burnwillows"]`` to
    ``_filter_deck_to_bridge_supported`` -> admitted; CardDef emitted
    carries the dual-AA shape (Land card type, no super/subtype on
    Python, AA[0] AddManaToPool({C}) + AA[1] the Sequence-of-leaves).
    """
    from mtg_bot.parity.trajectory import _filter_deck_to_bridge_supported

    filt, defs = _filter_deck_to_bridge_supported(
        ["Grove of the Burnwillows"], _PRINTINGS,
    )
    assert filt == ["Grove of the Burnwillows"]
    assert len(defs) == 1
    cd = defs[0]
    assert cd.name == "Grove of the Burnwillows"
    assert cd.card_type == "Land"
    assert cd.subtypes == ()
    assert cd.supertypes == ()
    assert len(cd.activated_abilities) == 2
    aa0 = cd.activated_abilities[0]
    assert aa0["cost"] == {"tap_self": True}
    assert aa0["effect"] == {
        "kind": "add_mana_to_pool", "color": "C", "amount": 1,
    }
    assert aa0["is_mana_ability"] is True
    aa1 = cd.activated_abilities[1]
    assert aa1["cost"] == {"tap_self": True}
    assert aa1["effect"] == {
        "kind": "sequence",
        "effects": [
            {
                "kind": "add_n_mana_of_chosen_color",
                "amount": 1,
                "options": ["R", "G"],
            },
            {"kind": "grant_life_to_each_opponent", "amount": 1},
        ],
    }
    assert aa1["is_mana_ability"] is True


# ---------------------------------------------------------------------------
# Helper -- seat Grove on p0's bf on both engines. Mana pools empty on
# both engines; no other permanents on either side. Returns
# ``(py, py_g, rs, rs_g)``.
# ---------------------------------------------------------------------------


def _seat_grove(starting_life: int = 20):
    """Seat Grove of the Burnwillows on p0's bf on BOTH engines. Mana
    pools empty; no other permanents on either side; p0/p1 life set to
    ``starting_life`` on both engines; no agent seated (so the chosen-
    color path falls back to ``options[0]`` deterministically on both
    engines). Returns ``(py, py_g, rs, rs_g)``.
    """
    from mtg_bot.game import Zone
    from mtg_bot.parity.cross_engine import (
        DeckSpec,
        build_python_state,
        build_rust_state,
    )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)

    grove_printing = _PRINTINGS["Grove of the Burnwillows"]

    # ---- Python: seat Grove on p0's bf. ----
    py_g = py.new_object(
        grove_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_g.summoning_sick = False
    py_g.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_g)
    py.players[0].life = starting_life
    py.players[1].life = starting_life
    py.active_player_idx = 0
    py.priority_player_idx = 0
    py.players[0].agent = None
    py.players[1].agent = None

    # ---- Rust: seat Grove on p0's bf. ----
    rs_g = rs.register_and_inject_object(
        _GROVE_RUST_DICT, 0, ZONE_BATTLEFIELD,
    )
    rs.force_set_summoning_sick(rs_g, False)
    rs.set_life(0, starting_life)
    rs.set_life(1, starting_life)

    return py, py_g, rs, rs_g


def _py_mana_pool_counts(py, player_id: int) -> dict:
    """Build a 7-key W/U/B/R/G/C/any count dict from Python's list-of-
    coins mana pool -- mirrors Rust's ``mana_pool_snapshot`` shape for
    byte-equal compare.
    """
    counts = dict(_EMPTY_MANA_POOL)
    for coin in py.players[player_id].mana_pool:
        if coin.color in counts:
            counts[coin.color] += 1
    return counts


# ---------------------------------------------------------------------------
# (5) GENUINE real-EoE cross-engine byte-equal probe -- Scenario MINT-C:
# Grove's AA[0] mints 1 C coin byte-equal cross-engine; both lives
# untouched. PROBED tier flip evidence (the {T}:C mana path).
# ---------------------------------------------------------------------------


@_rust_skip
def test_cross_engine_real_eoe_grove_mint_c_scenario_parity():
    """**GENUINE real-EoE cross-engine probe -- Scenario MINT-C
    (AA[0]).** PROBED tier flip evidence (the {T}:C mana path).

    Pre-state: Grove on p0's bf (untapped, not summoning-sick), p0/p1
    at 20 life, no other permanents, empty pools.

    Drive: activate Grove's AA[0] on both engines.

    Post-resolve (both engines, byte-equal):
      * p0's mana pool has exactly 1 C coin.
      * p0/p1 lives untouched (20/20).
      * Stack empty (mana-ability bypass-stack).
      * Grove tapped.
      * p1's pool untouched (empty) -- source-controller-scoping.
    """
    grove_printing = _PRINTINGS.get("Grove of the Burnwillows")
    if grove_printing is None:
        pytest.skip("Grove of the Burnwillows absent from active CardSource")

    py, py_g, rs, rs_g = _seat_grove(starting_life=20)

    # ---- Pre-state pins.
    assert _py_mana_pool_counts(py, 0) == _EMPTY_MANA_POOL
    assert rs.mana_pool_snapshot(0) == _EMPTY_MANA_POOL
    assert py_g.tapped is False
    assert rs.is_tapped(rs_g) is False

    # ---- Drive AA[0] activation on both engines.
    from mtg_bot.actions import ActivateAbility, apply_action

    apply_action(
        py, 0, ActivateAbility(source_id=py_g.id, ability_index=0),
    )
    rs.apply_action(
        {"kind": "activate_ability", "source_id": rs_g, "ability_index": 0}
    )

    # ---- Post-resolve observables: 1 C coin on both engines.
    expected_pool = dict(_EMPTY_MANA_POOL, C=1)
    py_pool = _py_mana_pool_counts(py, 0)
    rs_pool = rs.mana_pool_snapshot(0)
    assert py_pool == expected_pool, (
        f"Python: Grove AA[0] must mint 1 C coin; got py_pool={py_pool}"
    )
    assert rs_pool == expected_pool, (
        f"Rust: Grove AA[0] must mint 1 C coin; got rs_pool={rs_pool}"
    )
    assert py_pool == rs_pool, (
        f"Cross-engine byte-equal (1-C-coin mint pool): "
        f"py_pool={py_pool}, rs_pool={rs_pool}"
    )

    # ---- Lives untouched on both engines (AA[0] has no life rider).
    assert py.players[0].life == 20 and py.players[1].life == 20
    assert rs.get_life(0) == 20 and rs.get_life(1) == 20

    # ---- Stack empty + Grove tapped on both engines.
    assert len(py.stack) == 0
    assert rs.stack_size() == 0
    assert py_g.tapped is True
    assert rs.is_tapped(rs_g) is True

    # ---- p1's pool untouched (source-controller-scoping).
    assert _py_mana_pool_counts(py, 1) == _EMPTY_MANA_POOL
    assert rs.mana_pool_snapshot(1) == _EMPTY_MANA_POOL


# ---------------------------------------------------------------------------
# (6) GENUINE real-EoE cross-engine byte-equal probe -- Scenario
# MINT-R+LIFE: Grove's AA[1] Sequence mints 1 R coin (no-agent
# options[0] fallback) THEN the one opponent gains 1 life, byte-equal
# cross-engine. PROBED tier flip evidence (THE LOAD-BEARING {T}:Sequence
# path -- chosen-color mint + each-opponent-life-gain).
# ---------------------------------------------------------------------------


@_rust_skip
def test_cross_engine_real_eoe_grove_mint_r_plus_life_scenario_parity():
    """**GENUINE real-EoE cross-engine probe -- Scenario MINT-R+LIFE
    (AA[1] Sequence).** PROBED tier flip evidence (THE LOAD-BEARING
    {T}:Sequence path).

    Pre-state: Grove on p0's bf (untapped, not summoning-sick), p0/p1
    at 20 life, no other permanents, empty pools, NO agent seated (the
    chosen-color path falls back to ``options[0]="R"`` deterministically
    on both engines).

    Drive: activate Grove's AA[1] on both engines. The Sequence resolves
    both children IN ORDER:
      1. ``AddNManaOfChosenColor(1, ("R","G"))`` mints 1 R coin into
         p0's pool (no-agent ``options[0]="R"`` fallback -- the fixed
         2-tuple is NOT a board-walk union, so both engines pick R with
         no seating constraint, no divergence).
      2. ``GrantLifeToEachOpponent(1)`` -- the one opponent (p1) gains
         1 life (20 -> 21).

    Post-resolve (both engines, byte-equal):
      * p0's mana pool has exactly 1 R coin.
      * p0's life unchanged (20) -- the life rider is each-OPPONENT, not
        self.
      * p1's life = 21 (20 + 1).
      * Stack empty (mana-ability bypass-stack).
      * Grove tapped.
      * p1's pool untouched (empty) -- the mint scopes to source-
        controller (p0), not the opponent.
    """
    grove_printing = _PRINTINGS.get("Grove of the Burnwillows")
    if grove_printing is None:
        pytest.skip("Grove of the Burnwillows absent from active CardSource")

    py, py_g, rs, rs_g = _seat_grove(starting_life=20)

    # ---- Pre-state pins.
    assert _py_mana_pool_counts(py, 0) == _EMPTY_MANA_POOL
    assert rs.mana_pool_snapshot(0) == _EMPTY_MANA_POOL
    assert py.players[0].life == 20 and py.players[1].life == 20
    assert rs.get_life(0) == 20 and rs.get_life(1) == 20
    assert py_g.tapped is False
    assert rs.is_tapped(rs_g) is False

    # ---- Drive AA[1] activation on both engines.
    from mtg_bot.actions import ActivateAbility, apply_action

    apply_action(
        py, 0, ActivateAbility(source_id=py_g.id, ability_index=1),
    )
    rs.apply_action(
        {"kind": "activate_ability", "source_id": rs_g, "ability_index": 1}
    )

    # ---- Post-resolve observables: 1 R coin on both engines (the
    # Sequence leaf #0 chosen-color mint via the options[0]="R"
    # no-agent fallback).
    expected_pool = dict(_EMPTY_MANA_POOL, R=1)
    py_pool = _py_mana_pool_counts(py, 0)
    rs_pool = rs.mana_pool_snapshot(0)
    assert py_pool == expected_pool, (
        f"Python: Grove AA[1] Sequence leaf #0 must mint 1 R coin "
        f"(options[0] fallback); got py_pool={py_pool}"
    )
    assert rs_pool == expected_pool, (
        f"Rust: Grove AA[1] Sequence leaf #0 must mint 1 R coin "
        f"(options[0] fallback); got rs_pool={rs_pool}"
    )
    assert py_pool == rs_pool, (
        f"Cross-engine byte-equal (1-R-coin chosen-color mint): "
        f"py_pool={py_pool}, rs_pool={rs_pool}"
    )

    # ---- Post-resolve life: p0 unchanged, p1 += 1 byte-equal (the
    # Sequence leaf #1 each-opponent-life-gain).
    assert py.players[0].life == 20, (
        f"Python: Grove AA[1] life rider is each-OPPONENT, p0 (the "
        f"controller) must be unchanged at 20; got {py.players[0].life}"
    )
    assert rs.get_life(0) == 20, (
        f"Rust: Grove AA[1] life rider is each-OPPONENT, p0 (the "
        f"controller) must be unchanged at 20; got {rs.get_life(0)}"
    )
    assert py.players[1].life == 21, (
        f"Python: Grove AA[1] each-opponent-life-gain must raise p1's "
        f"life by 1 (20 -> 21); got {py.players[1].life}"
    )
    assert rs.get_life(1) == 21, (
        f"Rust: Grove AA[1] each-opponent-life-gain must raise p1's "
        f"life by 1 (20 -> 21); got {rs.get_life(1)}"
    )
    assert py.players[0].life == rs.get_life(0), (
        f"Cross-engine byte-equal (p0 life): py={py.players[0].life}, "
        f"rs={rs.get_life(0)}"
    )
    assert py.players[1].life == rs.get_life(1), (
        f"Cross-engine byte-equal (p1 life): py={py.players[1].life}, "
        f"rs={rs.get_life(1)}"
    )

    # ---- Stack empty + Grove tapped on both engines.
    assert len(py.stack) == 0
    assert rs.stack_size() == 0
    assert py_g.tapped is True
    assert rs.is_tapped(rs_g) is True

    # ---- p1's pool untouched (the mint scopes to source-controller p0).
    assert _py_mana_pool_counts(py, 1) == _EMPTY_MANA_POOL
    assert rs.mana_pool_snapshot(1) == _EMPTY_MANA_POOL


# ---------------------------------------------------------------------------
# (7) Sequence-IN-AA admit invariant -- the load-bearing substrate.
# Pins that the per-AA admit predicate now ADMITS a Sequence whose
# leaves are all in the Phase-1 admit set, AND still DECLINES a Sequence
# carrying a leaf class NOT in the admit set (defense-in-depth against
# silent admit-set widening).
# ---------------------------------------------------------------------------


def test_grove_sequence_in_aa_admit_invariant():
    """Pins the Sequence-IN-AA admit teeth:

      * Grove's actual AA[1] (a Sequence of two admitted leaves) admits.
      * A synthetic Sequence carrying a NON-admitted leaf class declines
        (the recursive all-leaves-admit gate bites).
      * A synthetic bare non-admitted leaf still declines (the leaf-only
        path is unchanged).
    """
    from mtg_bot.parity.trajectory import (
        _aa_is_phase1_sub_shape_a,
        _carrier_aa_effect_class_admitted,
    )
    from mtg_bot.cards import ActivatedAbility, ActivationCost
    from mtg_bot.effects.generic.draw_mill import DrawCards

    # Grove's real AA[1] admits (Sequence of two admitted leaves).
    p = _PRINTINGS["Grove of the Burnwillows"]
    aa1 = p.activated_abilities[1]
    assert _aa_is_phase1_sub_shape_a(aa1) is True
    assert _carrier_aa_effect_class_admitted(aa1.effect) is True

    # A Sequence carrying a NON-admitted leaf (DrawCards is not in the
    # Phase-1 Carrier-AA admit set) declines.
    bad_seq = Sequence(
        effects=(
            AddNManaOfChosenColor(amount=1, options=("R", "G")),
            DrawCards(amount=1),
        ),
    )
    assert _carrier_aa_effect_class_admitted(bad_seq) is False
    bad_aa = ActivatedAbility(
        cost=ActivationCost(tap_self=True),
        effect=bad_seq,
        is_mana_ability=True,
    )
    assert _aa_is_phase1_sub_shape_a(bad_aa) is False

    # A bare non-admitted leaf still declines (leaf-only path unchanged).
    assert _carrier_aa_effect_class_admitted(DrawCards(amount=1)) is False

    # A nested Sequence of admitted leaves admits (recursion works).
    nested_ok = Sequence(
        effects=(
            Sequence(
                effects=(GrantLifeToEachOpponent(amount=1),),
            ),
            AddNManaOfChosenColor(amount=1, options=("R", "G")),
        ),
    )
    assert _carrier_aa_effect_class_admitted(nested_ok) is True


# ---------------------------------------------------------------------------
# (8) Effect-class admit-set count sentinel -- pins the admit-set size
# so a silently-added new Effect class surfaces here.
# ---------------------------------------------------------------------------


def test_grove_carrier_aa_effect_classes_count():
    """Count sentinel for the Carrier-AA Phase-1 Effect-class admit set
    after the Grove FLIP (adds ``AddNManaOfChosenColor`` +
    ``GrantLifeToEachOpponent`` -- two entries). The exact size is the
    load-bearing invariant: a silently-added class that admits an
    unexpected card surfaces as a count-sentinel break.
    """
    from mtg_bot.parity.trajectory import _carrier_aa_phase_1_effect_classes

    classes = _carrier_aa_phase_1_effect_classes()
    assert AddNManaOfChosenColor in classes
    assert GrantLifeToEachOpponent in classes
    # 19 (post Ancient Tomb C2) + 2 (Grove) + 1 (Nesting Grounds flip:
    # MovePlusOneCounterBetweenPermanentsYouControl) = 22.
    assert len(classes) == 22, (
        f"Carrier-AA Phase-1 Effect-class admit set must be 22 after the "
        f"Grove FLIP + the Nesting Grounds flip (19 + "
        f"AddNManaOfChosenColor + GrantLifeToEachOpponent + "
        f"MovePlusOneCounterBetweenPermanentsYouControl); got "
        f"{len(classes)}"
    )
