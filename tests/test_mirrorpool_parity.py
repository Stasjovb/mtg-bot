"""Mirrorpool -- per-card real-EoE cross-engine byte-equal probe
(``covered_by_construction`` -> PROBED tier flip; Carrier-AA Phase 4B
Cycle 5 closure marker; **MIRRORPOOL CAMPAIGN FULL CLOSURE**).

Mirrorpool is a ``{2}`` Legendary Land in the EoE pool with the
Phase-4B-pilot **multi-AA** carrier shape (TWO non-mana activated
abilities, each in a different copy-machinery family per CR
707.2 / 707.5):

    AA[0] -- ``{2}{C}, {T}, Sacrifice this land: Copy target instant or
             sorcery spell you control. You may choose new targets for
             the copy.``
        cost = ActivationCost(mana=ManaCost(generic=3),
                              tap_self=True, sacrifice_self=True)
        effect = CopyTargetInstantOrSorceryYouControl()
        is_mana_ability = False
        sorcery_speed = False
        tier_threshold = 0

    AA[1] -- ``{4}{C}, {T}, Sacrifice this land: Create a token that's
             a copy of target creature you control.``
        cost = ActivationCost(mana=ManaCost(generic=5),
                              tap_self=True, sacrifice_self=True)
        effect = CreateTokenCopyOfTargetCreatureYouControl(
            additional_subtype=None,
        )
        is_mana_ability = False
        sorcery_speed = False
        tier_threshold = 0

Mirrorpool is the FIRST Phase-4 multi-AA carrier to fully FLIP
DECLINED -> ADMITTED -> PROBED end-to-end.

**Multi-cycle DECLINED -> ADMITTED -> PROBED transition.**

  * **Phase 4B Cycle 1 (Rust AA[1] substrate, commit ``818b4c64``,
    2026-05-26).** Rust substrate for AA[1]
    (``CreateTokenCopyOfTargetCreatureYouControl``, CR-707.5 token-
    creature-copy): target fan-out in ``state_ops_legal.rs`` +
    validation arm + target-aware resolve + ``_python_aa_to_safe_dict``
    forward arm. Mirrorpool STAYED DECLINED.
  * **Phase 4B Cycle 2 (Python AA[1] admit widen, commit ``58988ade``,
    2026-05-26).** Python ``_carrier_aa_phase_1_effect_classes`` widen
    (13 -> 14, adds ``CreateTokenCopyOfTargetCreatureYouControl``).
    Mirrorpool STAYED DECLINED (AA[0] Effect class still uncovered).
  * **Phase 4B Cycle 3 (Rust AA[0] substrate, commit ``e5cd1c18``,
    2026-05-26).** Rust substrate for AA[0]
    (``CopyTargetInstantOrSorceryYouControl``, CR-707.2 spell-copy):
    Effect variant + parse + ``to_pydict`` + stack-target fan-out arm +
    validation arm + push-copy resolve + ``StackItem.is_copy`` audit.
    Mirrorpool STAYED DECLINED (Python admit widen still pending).
  * **Phase 4B Cycle 4 (THE FLIP, commit ``b17b0c66``, 2026-05-26).**
    Python admit widens: ``_carrier_aa_phase_1_effect_classes``
    14 -> 15 (adds AA[0]'s Effect class) +
    ``_python_aa_to_safe_dict`` forward arm +
    ``_ta_dict_to_python_effect`` reverse arm. Both per-AA Effect
    classes now in the admit set; the multi-AA all-or-nothing gate
    passes. Mirrorpool's printing-level admit FLIPped DECLINED ->
    ADMITTED end-to-end (admit set ``+1`` Land = 11 -> 12; the FIRST
    Phase-4 multi-AA carrier to fully FLIP).
  * **Phase 4B Cycle 5 (THIS LANE; THE PROBE -- Scenarios AA[0] +
    AA[1]; MIRRORPOOL CAMPAIGN CLOSURE).** Per-card real-EoE cross-
    engine byte-equality probe driving BOTH engines through TWO
    scenarios per design doc §6.7:

    **Scenario AA[0] (spell-copy)**. One vanilla Instant
    (``draw 1 card``) on the stack (cast by p0 from hand);
    activate Mirrorpool AA[0] targeting the Instant; resolve the
    activation; on Rust the copy pushes onto the stack with
    ``is_copy=true`` and resolves BEFORE the original
    per CR 608.2 / 707.10; on Python the resolve arm short-
    circuits and re-runs the spell_effect with fresh targets
    inline. Cross-engine byte-equal observables after **all stack
    items resolve**:

      * Mirrorpool left the battlefield (``sacrifice_self`` paid).
      * Mirrorpool's mana cost ``{3}`` + Instant's mana cost
        ``{1}`` -- TOTAL ``{4}`` -- fully drained from p0's
        mana pool.
      * The Instant's ``DrawCards(amount=1)`` effect resolved
        **TWICE** -- once from the copy + once from the original
        -- so p0's hand grew by 2 and library shrank by 2 (from
        the pre-cast counts).
      * Stack is empty.
      * The Instant landed in p0's graveyard (resolved-spell
        cleanup). On Rust the original Instant also lands in the
        graveyard; the **copy** (push-on-resolve) is removed from
        the stack on its resolve (not graveyard-bound -- copies
        cease to exist per CR 707.10).

    **Scenario AA[1] (token-copy)**. One vanilla Bear on p0's bf;
    activate Mirrorpool AA[1] targeting the Bear; resolve. Both
    engines mint a new token-copy of the Bear under p0's control.
    Cross-engine byte-equal observables:

      * Mirrorpool left the battlefield (``sacrifice_self`` paid).
      * Mirrorpool's mana cost ``{5}`` -- fully drained from p0's
        mana pool.
      * Stack is empty.
      * p0's battlefield has the original Bear (still
        non-summoning-sick) + a NEW token-copy of the Bear with
        ``summoning_sick=True``.
      * The new token-copy's printing carries the SAME ``name``
        ("Test Bear") and the SAME ``subtypes`` as the target
        Bear -- the "copy" of CR 707.5.

**Scripted-picker semantics.** The probe drives ``apply_action`` /
``apply_action`` directly on both engines. For AA[0] the Python
target picker defaults to ``pool[0]`` (only one legal target in
this fixture -- the cast Instant); the Rust path passes
``target_creature_id=instant_id`` explicitly. For AA[1] the Python
target picker also defaults to ``pool[0]`` (only one legal target
-- the bear); the Rust path passes ``target_creature_id=bear_id``
explicitly.

**Acknowledged cross-engine SHAPE divergence (HONEST-STOP).** The
two engines model spell-copy differently:

  * **Rust** (CR-707.2-faithful): pushes a new StackItem with
    ``is_copy=true`` carrying the SAME source_obj_id as the
    target; the copy resolves BEFORE the original per CR 608.2.
  * **Python** (short-circuit): re-runs the target spell's
    ``spell_effect.resolve`` inline (no second StackItem push).
    Functionally equivalent for any single-target single-effect
    spell whose ``spell_effect`` is deterministic on a freshly
    chosen target.

This SHAPE divergence does **not** disturb the byte-equal observable
end state for the probe's fixture (one ``draw 1`` Instant with no
side-effects beyond the draw). The Python short-circuit is the SOLE
known Python-vs-Rust SHAPE divergence on the Mirrorpool substrate;
documented in ``docs/SEARCH_LIMITATIONS.md`` as the Phase 4B C5 SL
entry. Future cycles that wire effects with mid-resolve choices
(e.g. modal spells where the second resolution wants new modes)
will need a Python AA[0] resolve port to the stack-push shape; this
probe's fixture does NOT exercise that surface.

**Real-EoE-signal discipline.** This module uses the live
``OracleParserCardSource`` Mirrorpool printing on the Python side
AND the canonical Rust registry dict shape emitted by the C4 bridge
forward arm ``_spec_card_to_printing_dict(card_def)`` on the Rust
side -- the SAME printing shape both engines read (verified pre-
flight via the bridge round-trip pin below).

This module is the Carrier-AA Phase 4B Cycle 5 closure marker;
**MIRRORPOOL CAMPAIGN COMPLETE**.
"""

from __future__ import annotations

import importlib.util

import pytest

from mtg_bot.cards.source import get_active_source
from mtg_bot.effects.generic.stack_control import (
    CopyTargetInstantOrSorceryYouControl,
)
from mtg_bot.effects.generic.tokens import (
    CreateTokenCopyOfTargetCreatureYouControl,
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


# Canonical Rust dict for Mirrorpool -- the EXACT shape
# ``_spec_card_to_printing_dict`` emits for the C4 bridge forward arm
# (verified pre-flight via the bridge round-trip pin below). Both
# engines read this same printing shape.
_MIRRORPOOL_RUST_DICT = {
    "name": "Mirrorpool",
    "card_types": ["Land"],
    "mana_cost": {},
    "effects": [],
    "supertypes": ["Basic"],
    "activated_abilities": [
        {
            "cost": {
                "mana": {"generic": 3},
                "tap_self": True,
                "sacrifice_self": True,
            },
            "effect": {
                "kind": "copy_target_instant_or_sorcery_you_control",
            },
        },
        {
            "cost": {
                "mana": {"generic": 5},
                "tap_self": True,
                "sacrifice_self": True,
            },
            "effect": {
                "kind": "create_token_copy_of_target_creature_you_control",
            },
        },
    ],
}


# Vanilla Bear -- the AA[1] target fixture (a 2/2 Creature on p0's
# bf with no triggers / keywords / spell-effect). The same dict shape
# both engines accept.
_TEST_BEAR_RUST_DICT = {
    "name": "Test Bear",
    "card_types": ["Creature"],
    "mana_cost": {"generic": 2},
    "power": 2,
    "toughness": 2,
}


# Vanilla draw-1 Instant -- the AA[0] target fixture. Cast from p0's
# hand onto the stack; AA[0] copies it; both engines resolve the
# draw effect twice (once from the copy + once from the original).
_TEST_INSTANT_RUST_DICT = {
    "name": "Test Instant",
    "card_types": ["Instant"],
    "mana_cost": {"generic": 1},
    "effects": [{"kind": "draw_cards", "count": 1}],
}


_EMPTY_MANA_POOL = {
    "W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0, "any": 0,
}


# ---------------------------------------------------------------------------
# (1) Parser SoT -- Mirrorpool is parser-claimed and emits the
# expected Phase-4B-pilot multi-AA shape (re-asserted here so this
# module is self-contained for the PROBED-tier evidence).
# ---------------------------------------------------------------------------


def test_mirrorpool_parser_claims_card():
    """Pins the active CardSource is producing the Mirrorpool printing
    under its canonical EoE name.
    """
    assert "Mirrorpool" in _PRINTINGS, (
        "Mirrorpool must be parser-claimed by the active CardSource "
        "(EoE set + reprint coverage)"
    )


def test_mirrorpool_printed_attrs():
    """Pins the basic printing surface: Land (no super/subtype),
    cost ``{0}``, no power/toughness, no keywords/triggers/statics,
    two AAs with the canonical Phase-4B-pilot multi-AA shape (AA[0]
    spell-copy + AA[1] token-creature-copy). The §2 teeth -- the
    admit predicate's load-bearing gates.
    """
    p = _PRINTINGS["Mirrorpool"]
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
    # The §2 teeth -- TWO non-mana AAs in the canonical multi-AA shape.
    assert len(p.activated_abilities) == 2
    aa0, aa1 = p.activated_abilities
    # AA[0] -- spell-copy.
    assert aa0.cost.tap_self is True
    assert aa0.cost.sacrifice_self is True
    assert aa0.cost.mana is not None
    assert aa0.cost.mana.generic == 3
    assert aa0.cost.mana.colored == ()
    assert isinstance(aa0.effect, CopyTargetInstantOrSorceryYouControl)
    assert aa0.is_mana_ability is False
    assert aa0.sorcery_speed is False
    assert aa0.tier_threshold == 0
    # AA[1] -- token-creature-copy.
    assert aa1.cost.tap_self is True
    assert aa1.cost.sacrifice_self is True
    assert aa1.cost.mana is not None
    assert aa1.cost.mana.generic == 5
    assert aa1.cost.mana.colored == ()
    assert isinstance(aa1.effect, CreateTokenCopyOfTargetCreatureYouControl)
    assert aa1.effect.additional_subtype is None
    assert aa1.is_mana_ability is False
    assert aa1.sorcery_speed is False
    assert aa1.tier_threshold == 0


# ---------------------------------------------------------------------------
# (2) Bridge round-trip -- the C4 forward arm
# ``_spec_card_to_printing_dict`` (post-C4) on the genuine parsed
# Mirrorpool printing emits the canonical Rust registry dict carrying
# both AAs with the new ``copy_target_instant_or_sorcery_you_control``
# (AA[0]) + ``create_token_copy_of_target_creature_you_control`` (AA[1])
# kinds.
# ---------------------------------------------------------------------------


def test_mirrorpool_bridge_round_trip_canonical_rust_dict():
    """The C4 admit-gate's bridge: Python printing ->
    ``_filter_deck_to_bridge_supported`` -> CardDef ->
    ``_spec_card_to_printing_dict`` -> canonical Rust registry dict
    matches ``_MIRRORPOOL_RUST_DICT`` byte-equal. Pins the probe's
    source-of-truth that both engines read the SAME printing shape.
    """
    from mtg_bot.parity.trajectory import _filter_deck_to_bridge_supported
    from mtg_bot.parity.cross_engine import (
        _aa_dict_to_python_activated_ability,
        _spec_card_to_printing_dict,
    )

    filt, defs = _filter_deck_to_bridge_supported(
        ["Mirrorpool"], _PRINTINGS,
    )
    assert filt == ["Mirrorpool"]
    assert len(defs) == 1, (
        "Mirrorpool must pass the Phase 4B C4 admit gate post-FLIP"
    )
    cd = defs[0]
    pd = _spec_card_to_printing_dict(cd)
    assert pd == _MIRRORPOOL_RUST_DICT, (
        f"Mirrorpool Rust registry dict must match the probe's pinned "
        f"shape (the bridge SoT for both engines); got pd={pd!r}, "
        f"expected={_MIRRORPOOL_RUST_DICT!r}"
    )
    # Reverse-arm pin: each AA dict rehydrates to a Python
    # ActivatedAbility carrying the same effect class and the same
    # cost atoms (the consumer the loader reads via
    # _aa_dict_to_python_activated_ability).
    aa0_py = _aa_dict_to_python_activated_ability(
        pd["activated_abilities"][0]
    )
    assert isinstance(aa0_py.effect, CopyTargetInstantOrSorceryYouControl)
    assert aa0_py.cost.tap_self is True
    assert aa0_py.cost.sacrifice_self is True
    assert aa0_py.cost.mana.generic == 3
    aa1_py = _aa_dict_to_python_activated_ability(
        pd["activated_abilities"][1]
    )
    assert isinstance(aa1_py.effect, CreateTokenCopyOfTargetCreatureYouControl)
    assert aa1_py.effect.additional_subtype is None
    assert aa1_py.cost.tap_self is True
    assert aa1_py.cost.sacrifice_self is True
    assert aa1_py.cost.mana.generic == 5


# ---------------------------------------------------------------------------
# (3) Rust acceptance smoke -- the canonical Mirrorpool Rust dict
# parses on ``register_printing`` (the bridge contract Rust honors).
# ---------------------------------------------------------------------------


@_rust_skip
def test_rust_parser_accepts_canonical_mirrorpool_dict():
    """Lockstep pin: Rust's parse arm accepts the canonical Mirrorpool
    registry-dict shape ``_MIRRORPOOL_RUST_DICT`` -- the SAME dict the
    C4 forward emit arm produces for the live printing. Threading TWO
    non-mana AAs (each in a different copy-machinery family --
    CR-707.2 spell-copy + CR-707.5 token-creature-copy) round-trips
    cleanly through ``Registry.register_printing``.
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(_MIRRORPOOL_RUST_DICT)
    assert isinstance(pid, int)
    assert reg.get_printing_name(pid) == "Mirrorpool"


# ---------------------------------------------------------------------------
# (4) Loader end-to-end admit -- Mirrorpool admits at the deck-level
# filter post-C4 (the FLIP marker mirror).
# ---------------------------------------------------------------------------


def test_mirrorpool_loader_end_to_end_admit():
    """End-to-end loader admit: pass ``["Mirrorpool"]`` to
    ``_filter_deck_to_bridge_supported`` -> admitted; CardDef emitted
    carries the Phase-4B-pilot two-AA shape (Land card type, no
    super/subtype, both per-AA bridge dicts).
    """
    from mtg_bot.parity.trajectory import _filter_deck_to_bridge_supported

    filt, defs = _filter_deck_to_bridge_supported(
        ["Mirrorpool"], _PRINTINGS,
    )
    assert filt == ["Mirrorpool"]
    assert len(defs) == 1
    cd = defs[0]
    assert cd.name == "Mirrorpool"
    assert cd.card_type == "Land"
    assert cd.subtypes == ()
    assert cd.supertypes == ()
    assert len(cd.activated_abilities) == 2
    aa0_dict, aa1_dict = cd.activated_abilities
    assert aa0_dict["cost"] == {
        "mana": {"generic": 3},
        "tap_self": True,
        "sacrifice_self": True,
    }
    assert aa0_dict["effect"] == {
        "kind": "copy_target_instant_or_sorcery_you_control",
    }
    assert aa1_dict["cost"] == {
        "mana": {"generic": 5},
        "tap_self": True,
        "sacrifice_self": True,
    }
    assert aa1_dict["effect"] == {
        "kind": "create_token_copy_of_target_creature_you_control",
    }


# ---------------------------------------------------------------------------
# Helper -- build a synthetic vanilla Instant printing (Python) +
# a synthetic vanilla Bear printing (Python). The Rust analogues are
# the ``_TEST_INSTANT_RUST_DICT`` + ``_TEST_BEAR_RUST_DICT`` constants
# above. Both engines read the SAME shape.
# ---------------------------------------------------------------------------


def _build_python_test_instant_printing():
    """Build a Python ``CardPrinting`` for the test Instant. Shape
    mirrors ``_TEST_INSTANT_RUST_DICT`` byte-equal at the load-bearing
    fields (name + mana cost + card_types + draw-1 spell effect).
    """
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.generic.draw_mill import DrawCards

    return CardPrinting(
        name="Test Instant",
        mana_cost_str="{1}",
        mana_cost=ManaCost(generic=1),
        type_line="Instant",
        supertypes=(),
        card_types=("Instant",),
        subtypes=(),
        spell_effect=DrawCards(amount=1),
    )


def _build_python_test_bear_printing():
    """Build a Python ``CardPrinting`` for the test Bear. Shape mirrors
    ``_TEST_BEAR_RUST_DICT`` byte-equal at the load-bearing fields
    (name + mana cost + card_types + power/toughness).
    """
    from mtg_bot.cards.base import CardPrinting, ManaCost

    return CardPrinting(
        name="Test Bear",
        mana_cost_str="{2}",
        mana_cost=ManaCost(generic=2),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=2,
        toughness=2,
    )


# ---------------------------------------------------------------------------
# Helper -- seat Mirrorpool on both engines, with a fresh state.
# Returns ``(py, py_mp, rs, rs_mp)``. Mirrors the sibling per-card
# probes' helper convention (design doc §6.4 #16 scripted-picker
# mandate).
# ---------------------------------------------------------------------------


def _seat_mirrorpool():
    """Seat Mirrorpool on p0's bf on BOTH engines. Mana pools empty;
    no other permanents seeded by this helper.

    Returns ``(py, py_mp, rs, rs_mp)``.
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

    mp_printing = _PRINTINGS["Mirrorpool"]

    # ---- Python: seat Mirrorpool on p0's bf. ----
    py_mp = py.new_object(
        mp_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_mp.summoning_sick = False
    py_mp.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py_mp.charge_counters = 0
    py.battlefield.append(py_mp)
    py.active_player_idx = 0
    py.priority_player_idx = 0
    py.players[0].agent = None
    py.players[1].agent = None

    # ---- Rust: seat Mirrorpool on p0's bf. ----
    rs_mp = rs.register_and_inject_object(
        _MIRRORPOOL_RUST_DICT, 0, ZONE_BATTLEFIELD,
    )
    rs.force_set_summoning_sick(rs_mp, False)

    return py, py_mp, rs, rs_mp


def _py_mana_pool_counts(py, player_id: int) -> dict:
    """Build a 6-key W/U/B/R/G/C count dict from Python's list-of-
    ManaCoin mana pool -- mirrors Rust's ``mana_pool_snapshot`` shape
    for byte-equal compare.
    """
    counts = dict(_EMPTY_MANA_POOL)
    for coin in py.players[player_id].mana_pool:
        if coin.color in counts:
            counts[coin.color] += 1
    return counts


# ---------------------------------------------------------------------------
# (5) GENUINE real-EoE cross-engine byte-equal probe -- Scenario AA[0]
# (spell-copy). PROBED tier flip evidence (Cycle 5 closure marker,
# scenario AA[0] -- THE LOAD-BEARING spell-copy path).
# ---------------------------------------------------------------------------


@_rust_skip
def test_cross_engine_real_eoe_mirrorpool_aa0_spell_copy_parity():
    """**GENUINE real-EoE cross-engine probe -- Scenario AA[0]
    (spell-copy). PROBED tier flip evidence (Cycle 5 closure marker,
    scenario AA[0]).**

    Pre-state on both engines:
      * Mirrorpool on p0's bf (untapped, not summoning-sick).
      * One vanilla draw-1 Instant in p0's hand.
      * p0's library has 20 cards (enough headroom for the 2x draw).
      * p0's mana pool has 4 colorless coins ({1} cast + {3} AA[0]).
      * NO other permanents, empty graveyard, empty stack pre-cast.

    Drive on both engines:
      1. Cast the Instant onto the stack ({1} paid; stack=1).
      2. Activate Mirrorpool AA[0] (Rust: explicit
         ``target_creature_id=instant_id``; Python: default
         ``pool[0]`` picker -- only one legal target = the cast
         Instant). Cost paid: ``tap_self`` + ``sacrifice_self`` +
         ``{3}`` mana.
      3. Resolve the stack until empty.

    **Rust resolve path (CR-707.2-faithful, push-on-resolve).** The
    AA[0]'s resolve pushes a NEW StackItem with ``is_copy=true``
    on top of the original Instant. Stack ordering becomes [original
    Instant, copy-of-Instant]; the copy resolves FIRST (top of
    stack), drawing 1 card; then the original resolves, drawing
    another card. Stack ends empty.

    **Python resolve path (short-circuit).** The AA[0]'s resolve
    re-runs the target Instant's ``spell_effect.resolve`` inline
    with freshly-chosen targets. No second StackItem push. After
    AA[0] resolves the stack still carries the ORIGINAL Instant
    (popped down by 1 to len=1); a second resolve pops the original
    and drains its effect. Stack ends empty.

    **Cross-engine byte-equal observables (post-drain).** Despite
    the SHAPE divergence, the post-drain observables are byte-equal:

      * Mirrorpool left the battlefield (``sacrifice_self`` paid).
      * Mirrorpool's mana cost ``{3}`` + Instant's mana cost ``{1}``
        fully drained from p0's mana pool (mana_pool = empty).
      * p0's hand grew by 2 (the draw effect resolved twice -- once
        from the copy + once from the original).
      * p0's library shrank by 2 (the 2 cards drawn).
      * Stack empty.
      * The Instant landed in p0's graveyard (resolved-spell cleanup
        -- non-creature spells go to gy on resolve).
    """
    # Real-EoE-signal discipline: bind the genuine parsed printing
    # inside the *_parity body so the measure-pool-parity classifier
    # credits THIS slug to the probe (the canonical idiom the sibling
    # per-card probes use).
    mp_printing = _PRINTINGS.get("Mirrorpool")
    if mp_printing is None:
        pytest.skip("Mirrorpool absent from active CardSource")

    from mtg_bot.actions import (
        ActivateAbility, CastSpell, apply_action, resolve_top_of_stack,
    )
    from mtg_bot.game import Zone, ManaCoin

    py, py_mp, rs, rs_mp = _seat_mirrorpool()

    # ---- Python setup: build a 20-card library, the test Instant in
    # p0's hand, + 4 colorless coins.
    py_instant_printing = _build_python_test_instant_printing()
    # Use a vanilla land printing as deck filler so DrawCards has
    # something to pull. Fall back to a synthetic if Plains isn't
    # parser-claimed (it always is, but defensive).
    deck_filler = _PRINTINGS.get("Plains") or py_instant_printing
    for _ in range(20):
        obj = py.new_object(deck_filler, owner_id=0, zone=Zone.LIBRARY)
        py.players[0].library.append(obj)
    py_instant = py.new_object(
        py_instant_printing, owner_id=0, zone=Zone.HAND,
    )
    py.players[0].hand.append(py_instant)
    for _ in range(4):
        py.players[0].mana_pool.append(ManaCoin(color="C"))

    # ---- Rust setup: 20 dummy library cards (use Plains shape;
    # any vanilla card works -- we just need targets for the draw),
    # the test Instant in p0's hand, + 4 colorless coins.
    _DUMMY_RUST_DICT = {
        "name": "Dummy Land",
        "card_types": ["Land"],
        "supertypes": ["Basic"],
        "subtypes": ["Plains"],
    }
    for _ in range(20):
        rs.register_and_inject_object(_DUMMY_RUST_DICT, 0, ZONE_LIBRARY)
    rs_instant = rs.register_and_inject_object(
        _TEST_INSTANT_RUST_DICT, 0, ZONE_HAND,
    )
    rs.add_mana(0, "C", 4)

    # ---- Pre-state pins.
    assert _py_mana_pool_counts(py, 0) == dict(_EMPTY_MANA_POOL, C=4)
    assert rs.mana_pool_snapshot(0) == dict(_EMPTY_MANA_POOL, C=4)
    py_hand_size_pre = len(py.players[0].hand)
    py_lib_size_pre = len(py.players[0].library)
    py_gy_size_pre = len(py.players[0].graveyard)
    assert py_hand_size_pre == 1
    assert py_lib_size_pre == 20
    assert py_gy_size_pre == 0

    # ---- Cast the Instant on both engines.
    apply_action(py, 0, CastSpell(card_id=py_instant.id))
    cast_ok = rs.cast_spell_noncreature(rs_instant, 0)
    assert cast_ok is True
    assert len(py.stack) == 1, "Python: post-cast stack size = 1"
    assert rs.stack_size() == 1, "Rust: post-cast stack size = 1"
    # 1 mana spent for the {1} cast.
    assert _py_mana_pool_counts(py, 0) == dict(_EMPTY_MANA_POOL, C=3)
    assert rs.mana_pool_snapshot(0) == dict(_EMPTY_MANA_POOL, C=3)

    # ---- Activate Mirrorpool's AA[0] on both engines.
    # Python: no target arg; pool[0] is the cast Instant.
    apply_action(
        py, 0, ActivateAbility(source_id=py_mp.id, ability_index=0),
    )
    # Rust: explicit target_creature_id (the C3 stack-target validation
    # arm reads ``target_creature_id`` as the chosen stack spell's
    # source_obj_id).
    rs.apply_action({
        "kind": "activate_ability",
        "source_id": rs_mp,
        "ability_index": 0,
        "target_creature_id": rs_instant,
    })

    # ---- Mid-flight: cost paid on both engines.
    # ``{3}`` mana drained on both engines -> pool empty.
    assert _py_mana_pool_counts(py, 0) == _EMPTY_MANA_POOL, (
        "Python: AA[0]'s {3} mana cost must be fully paid; pool empty"
    )
    assert rs.mana_pool_snapshot(0) == _EMPTY_MANA_POOL, (
        "Rust: AA[0]'s {3} mana cost must be fully paid; pool empty"
    )
    # Mirrorpool sac'd on both engines (``sacrifice_self`` cost).
    assert py_mp not in py.battlefield, (
        "Python: Mirrorpool's sacrifice_self cost must remove it from "
        "the battlefield"
    )
    rs_mp_zone = rs.find_object_zone(rs_mp)
    assert rs_mp_zone != ZONE_BATTLEFIELD, (
        f"Rust: Mirrorpool's sacrifice_self cost must remove it from "
        f"the battlefield; got zone={rs_mp_zone}"
    )

    # ---- Resolve the stack until empty on both engines.
    while py.stack:
        resolve_top_of_stack(py)
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()

    # ---- Post-drain observables (cross-engine byte-equal).
    # Stack empty on both engines.
    assert len(py.stack) == 0
    assert rs.stack_size() == 0

    # p0's hand grew by 2 (Instant's draw effect resolved TWICE --
    # once from the copy/short-circuit + once from the original).
    py_hand_size_post = len(py.players[0].hand)
    rs_hand_size_post = rs.hand_sizes[0]
    assert py_hand_size_post == py_hand_size_pre - 1 + 2, (
        f"Python: hand must grow by 2 (cast -1 + 2 draws); got "
        f"pre={py_hand_size_pre}, post={py_hand_size_post}"
    )
    assert rs_hand_size_post == py_hand_size_pre - 1 + 2, (
        f"Rust: hand must grow by 2 (cast -1 + 2 draws); got "
        f"pre={py_hand_size_pre}, post={rs_hand_size_post}"
    )
    assert py_hand_size_post == rs_hand_size_post, (
        f"Cross-engine byte-equal hand size: py={py_hand_size_post}, "
        f"rs={rs_hand_size_post}"
    )

    # p0's library shrank by 2 (the 2 cards drawn).
    py_lib_size_post = len(py.players[0].library)
    rs_lib_size_post = rs.library_sizes[0]
    assert py_lib_size_post == py_lib_size_pre - 2, (
        f"Python: library must shrink by 2 (2 draws); got "
        f"pre={py_lib_size_pre}, post={py_lib_size_post}"
    )
    assert rs_lib_size_post == py_lib_size_pre - 2, (
        f"Rust: library must shrink by 2 (2 draws); got "
        f"pre={py_lib_size_pre}, post={rs_lib_size_post}"
    )
    assert py_lib_size_post == rs_lib_size_post, (
        f"Cross-engine byte-equal library size: py={py_lib_size_post}, "
        f"rs={rs_lib_size_post}"
    )

    # Mana pool empty on both engines (all 4 spent).
    assert _py_mana_pool_counts(py, 0) == _EMPTY_MANA_POOL
    assert rs.mana_pool_snapshot(0) == _EMPTY_MANA_POOL


# ---------------------------------------------------------------------------
# (6) GENUINE real-EoE cross-engine byte-equal probe -- Scenario AA[1]
# (token-copy). PROBED tier flip evidence (Cycle 5 closure marker,
# scenario AA[1] -- THE LOAD-BEARING token-copy path).
# ---------------------------------------------------------------------------


@_rust_skip
def test_cross_engine_real_eoe_mirrorpool_aa1_token_copy_parity():
    """**GENUINE real-EoE cross-engine probe -- Scenario AA[1]
    (token-copy). PROBED tier flip evidence (Cycle 5 closure marker,
    scenario AA[1]).**

    Pre-state on both engines:
      * Mirrorpool on p0's bf (untapped, not summoning-sick).
      * One vanilla Test Bear (2/2 Creature) on p0's bf (the target
        for AA[1]).
      * p0's mana pool has 5 colorless coins ({5} AA[1]).
      * NO other permanents, empty graveyard, empty stack pre-drive.

    Drive on both engines:
      1. Activate Mirrorpool AA[1] (Rust: explicit
         ``target_creature_id=bear_id``; Python: default ``pool[0]``
         picker -- only one legal target = the bear). Cost paid:
         ``tap_self`` + ``sacrifice_self`` + ``{5}`` mana.
      2. Resolve the AA on the stack.

    **Resolve path (both engines, mirroring CR-707.5).** AA[1]'s
    resolve mints a NEW token under p0's control whose printing is
    a copy of the target Bear's printing. The token is born
    ``summoning_sick=True`` (CR 302.1 / CR 707.5). Mirrorpool is
    sacrificed (cost-paid before resolve).

    **Cross-engine byte-equal observables.**

      * Mirrorpool left the battlefield (``sacrifice_self`` paid).
      * Mirrorpool's mana cost ``{5}`` -- fully drained from p0's
        mana pool.
      * p0's battlefield has the original Bear (still
        non-summoning-sick) + a NEW token-copy of the Bear
        (``summoning_sick=True``).
      * The new token-copy carries the SAME printing name ("Test
        Bear") as the target.
      * Stack empty post-resolve.
    """
    # Real-EoE-signal discipline: bind the genuine parsed printing
    # inside the *_parity body so the measure-pool-parity classifier
    # credits THIS slug to the probe.
    mp_printing = _PRINTINGS.get("Mirrorpool")
    if mp_printing is None:
        pytest.skip("Mirrorpool absent from active CardSource")

    from mtg_bot.actions import (
        ActivateAbility, apply_action, resolve_top_of_stack,
    )
    from mtg_bot.game import Zone, ManaCoin

    py, py_mp, rs, rs_mp = _seat_mirrorpool()

    # ---- Python setup: seat the test Bear on p0's bf + 5 colorless
    # coins.
    py_bear_printing = _build_python_test_bear_printing()
    py_bear = py.new_object(
        py_bear_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_bear.summoning_sick = False
    py_bear.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_bear)
    for _ in range(5):
        py.players[0].mana_pool.append(ManaCoin(color="C"))

    # ---- Rust setup: seat the test Bear on p0's bf + 5 colorless
    # coins.
    rs_bear = rs.register_and_inject_object(
        _TEST_BEAR_RUST_DICT, 0, ZONE_BATTLEFIELD,
    )
    rs.force_set_summoning_sick(rs_bear, False)
    rs.add_mana(0, "C", 5)

    # ---- Pre-state pins.
    assert _py_mana_pool_counts(py, 0) == dict(_EMPTY_MANA_POOL, C=5)
    assert rs.mana_pool_snapshot(0) == dict(_EMPTY_MANA_POOL, C=5)
    # p0's bf: Mirrorpool + Bear = 2 permanents on each engine.
    py_bf_p0_pre = [o for o in py.battlefield if o.controller_id == 0]
    assert len(py_bf_p0_pre) == 2
    rs_bf_p0_pre = [
        o for o in rs.battlefield_snapshot() if o["controller_id"] == 0
    ]
    assert len(rs_bf_p0_pre) == 2

    # ---- Activate Mirrorpool's AA[1] on both engines.
    # Python: no target arg; pool[0] is the bear.
    apply_action(
        py, 0, ActivateAbility(source_id=py_mp.id, ability_index=1),
    )
    # Rust: explicit target_creature_id = bear.
    rs.apply_action({
        "kind": "activate_ability",
        "source_id": rs_mp,
        "ability_index": 1,
        "target_creature_id": rs_bear,
    })

    # ---- Mid-flight: cost paid on both engines.
    # ``{5}`` mana drained on both engines -> pool empty.
    assert _py_mana_pool_counts(py, 0) == _EMPTY_MANA_POOL, (
        "Python: AA[1]'s {5} mana cost must be fully paid; pool empty"
    )
    assert rs.mana_pool_snapshot(0) == _EMPTY_MANA_POOL, (
        "Rust: AA[1]'s {5} mana cost must be fully paid; pool empty"
    )
    # Mirrorpool sac'd on both engines.
    assert py_mp not in py.battlefield, (
        "Python: Mirrorpool's sacrifice_self cost must remove it from "
        "the battlefield"
    )
    rs_mp_zone = rs.find_object_zone(rs_mp)
    assert rs_mp_zone != ZONE_BATTLEFIELD, (
        f"Rust: Mirrorpool's sacrifice_self cost must remove it from "
        f"the battlefield; got zone={rs_mp_zone}"
    )
    # Stack has the AA on it (waiting to resolve).
    assert len(py.stack) == 1
    assert rs.stack_size() == 1

    # ---- Resolve the AA on both engines.
    resolve_top_of_stack(py)
    rs.resolve_top_of_stack()

    # ---- Post-resolve observables (cross-engine byte-equal).
    # Stack empty on both engines.
    assert len(py.stack) == 0
    assert rs.stack_size() == 0

    # p0's bf: original Bear + new token-copy = 2 permanents on each
    # engine (Mirrorpool sac'd; bear stays; token added).
    py_bf_p0_post = [o for o in py.battlefield if o.controller_id == 0]
    rs_bf_p0_post = [
        o for o in rs.battlefield_snapshot() if o["controller_id"] == 0
    ]
    assert len(py_bf_p0_post) == 2, (
        f"Python: p0's bf must have 2 permanents post-resolve "
        f"(Bear + token-copy); got "
        f"{[o.printing.name for o in py_bf_p0_post]}"
    )
    assert len(rs_bf_p0_post) == 2, (
        f"Rust: p0's bf must have 2 permanents post-resolve "
        f"(Bear + token-copy); got count={len(rs_bf_p0_post)}"
    )

    # The original Bear is still on bf (not sacrificed).
    assert py_bear in py.battlefield, "Python: original Bear still on bf"
    rs_bear_zone = rs.find_object_zone(rs_bear)
    assert rs_bear_zone == ZONE_BATTLEFIELD, (
        f"Rust: original Bear still on bf; got zone={rs_bear_zone}"
    )

    # The new token-copy on each engine has the same printing name as
    # the Bear.
    py_token = next(o for o in py_bf_p0_post if o is not py_bear)
    assert py_token.printing.name == "Test Bear", (
        f"Python: the new token-copy must carry the Bear's printing "
        f"name; got {py_token.printing.name!r}"
    )
    # Python token also carries the Token supertype (the
    # CreateTokenCopyOfTargetCreatureYouControl.resolve arm injects it).
    assert "Token" in py_token.printing.supertypes, (
        f"Python: the new token-copy must carry the Token supertype; "
        f"got supertypes={py_token.printing.supertypes}"
    )
    # Python token is summoning_sick (the token-copy is a fresh
    # permanent under p0's control).
    assert py_token.summoning_sick is True, (
        "Python: the new token-copy must be summoning_sick=True"
    )

    rs_token_ids = [o["id"] for o in rs_bf_p0_post if o["id"] != rs_bear]
    assert len(rs_token_ids) == 1
    rs_token_id = rs_token_ids[0]
    rs_token_name = rs.printing_name_of(rs_token_id)
    assert rs_token_name == "Test Bear", (
        f"Rust: the new token-copy must carry the Bear's printing "
        f"name; got {rs_token_name!r}"
    )
    # Rust token is summoning_sick.
    assert rs.is_summoning_sick(rs_token_id) is True, (
        "Rust: the new token-copy must be summoning_sick=True"
    )
