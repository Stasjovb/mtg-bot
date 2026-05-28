"""Ancient Tomb -- per-card real-EoE cross-engine byte-equal probe
(``covered_by_construction`` -> PROBED tier flip; Ancient Tomb Phase
4 Cycle 2 closure marker; **ANCIENT TOMB CAMPAIGN FULL CLOSURE**).

Ancient Tomb is a bare ``{T}``-cost mana-ability Land in the EoE pool
with the Phase-4-pilot single-AA mana-ability shape carrying the new
``DealDamageToControllerAndAddMana`` Effect class (Worker B's C1
substrate at commit ``c250a60d`` shipped the Rust fields variant +
parse + to_pydict + life-decrement-then-push_coins resolve arm +
source-controller fan-out + cross-engine bridge forward + reverse
arms):

    AA[0] -- ``{T}: Add {C}{C}. This land deals 2 damage to you.``
        cost = ActivationCost(tap_self=True)
        effect = DealDamageToControllerAndAddMana(damage=2,
                                                  produces=(("C", 2),))
        is_mana_ability = True
        sorcery_speed = False
        tier_threshold = 0

Ancient Tomb is the SOLE EoE carrier of the
``DealDamageToControllerAndAddMana`` Effect class per
``docs/BLOCKED_TAIL_TRACTABILITY_SCOUT_2026-05-27.md`` §#3; it admits
at the Carrier-AA Phase-1 admit gate post-Cycle-2 via the combined
Effect-class widen (18 -> 19) + the Phase-1.5a bare ``{T}`` cost gate
+ the Phase-4E ``is_mana_ability=True`` AA-rider widen (commit
``daecd399``). No additional rider work is needed at C2 -- the per-AA
admit gate ``_aa_is_phase1_sub_shape_a`` ADMITS Ancient Tomb's AA[0]
on the Effect-class widen alone.

**Multi-cycle DECLINED -> ADMITTED -> PROBED transition.**

  * **Ancient Tomb Phase 4 Cycle 1 (Rust substrate landing, commit
    ``c250a60d``, 2026-05-27).** Rust substrate:
    ``Effect::DealDamageToControllerAndAddMana`` fields variant
    (``damage: u32`` + ``produces: Vec<(u8, u32)>``) + parser +
    resolver (life-decrement THEN push_coins -- damage applies as
    raw ``player.life -= damage as i32`` NOT via dispatch_event,
    mirroring Python's ``p.life -= self.damage``) + ``to_pydict`` +
    cross-engine bridge arms (forward + reverse). Ancient Tomb
    STAYED DECLINED at the admit gate post-C1 -- the Effect-class
    admit set ``_carrier_aa_phase_1_effect_classes`` didn't include
    the new Effect class (covered_by_construction +1 / BLOCKED-SG -1
    at C1).
  * **Ancient Tomb Phase 4 Cycle 2 (THIS LANE; THE FLIP + THE PROBE
    -- Scenarios MINT + MINT-at-2-life + MINT+PAY; ANCIENT TOMB
    CAMPAIGN CLOSURE).** Python admit widen:
      - ``_carrier_aa_phase_1_effect_classes`` admit-set widen
        18 -> 19 (adds ``DealDamageToControllerAndAddMana``).
    Ancient Tomb FLIPS DECLINED -> ADMITTED at the production deck
    filter end-to-end (LAND admits 11 -> 12 at the live-pool walk);
    the printing-level admit cascades through
    ``_printing_is_bridge_simple_carrier_aa_any`` -> Land sibling ->
    ``_carrier_aa_land_card_def`` (the cross-engine builder gate).

    Plus the per-card real-EoE byte-equality probe driving BOTH
    engines through THREE scenarios:

    **Scenario MINT (load-bearing 2-mana mint + 2-damage rider).**
    Ancient Tomb on p0's bf, controller at 20 life, empty mana pool
    on both engines. Activate Ancient Tomb's AA[0] on BOTH engines
    via ``apply_action({"kind": "activate_ability", "source_id":
    AT, "ability_index": 0})``.
    Post-resolve byte-equal observables on both engines:
      - p0's mana pool has exactly 2 C coins (the fixed
        ``produces=(("C", 2),)`` tuple mints 2 C coins
        deterministically -- no chosen-color path, no produces-union
        scan, no agent callback).
      - p0's life dropped by exactly 2 (20 -> 18; the damage rider
        applies as raw life-loss, NOT via dispatch_event, mirroring
        Python's ``p.life -= self.damage`` at
        ``effects/generic/damage.py:186``).
      - Stack empty on both engines (mana abilities bypass the stack
        per CR 605.3a; ``is_mana_ability=True``).
      - Ancient Tomb is tapped on both engines (``tap_self`` cost
        paid).
      - p1's mana pool untouched (source-controller-scoping invariant).
      - p1's life untouched (the damage rider scopes to source-
        controller, not active_player or all-opponents).

    **Scenario MINT-at-2-life (load-bearing self-kill edge case).**
    Same fixture as MINT but p0's life set to EXACTLY 2 PRE-activate.
    Tapping Ancient Tomb deals 2 damage = current life. Both engines
    must drop life to EXACTLY 0 byte-equal AND mint the 2 C coins
    AFTER the damage (mirrors Python's ``.resolve()`` which
    unconditionally appends ManaCoins after the life decrement -- the
    mana stays in the now-zero-life controller's pool until the next
    SBA check). The SBA-loss-flag check is DEFERRED to the orchestrator;
    THIS probe pins the post-resolve mid-step state (pool + life)
    only -- the lose-the-game state-based action runs at the next SBA
    pass which is the game-loop's responsibility, not the resolve
    arm's. (See ``docs/SEARCH_LIMITATIONS.md`` Ancient Tomb Phase 4 C2
    SL entry for the SBA-pass observability note.)

    **Scenario MINT+PAY (load-bearing end-to-end pay-from-mint).**
    Same fixture as MINT, but additionally cast a ``{2}`` generic
    Instant from p0's hand using the 2 minted C coins. Pin both the
    mint half (post-mint pool = ``C=2``) AND the pay half (post-cast
    pool fully drained). The canonical MINT+PAY shape per the
    BLOCKED-tail scout's C2 spec:

      1. Resolve AA[0] -> 2 C coins minted, life -= 2.
      2. Cast ``{2}`` generic Instant -- Python pops both C coins
         (matches the ``generic`` cost slot via
         ``_coin_matches_color(coin, None)`` -> True for any color
         where the lifetime context is generic-only); Rust's
         ``cast_spell_noncreature`` -> ``auto_tap_pay_for_cost``
         FIFO-walks the pool, finds the 2 C coins, decrements
         ``mp.C``, removes from ``mp.coins``.
      3. Both pools end fully empty (byte-equal cross-engine).

**Scripted-picker semantics.** The probe drives ``apply_action`` /
``apply_action`` directly on both engines with explicit
``(source_id, ability_index)`` pairs. The mana-ability bypass-stack
semantics resolve the effect immediately (no stack item to drain).
Unlike MC C2 / RP C2 there is NO color-picker divergence to gate
around -- Ancient Tomb's produces tuple is FIXED at ``(("C", 2),)``
on the Effect itself, so both engines mint 2 C coins byte-equal
regardless of the controller's board shape. The damage half is also
deterministic (a fixed ``damage: u32 = 2`` field on the Effect; no
agent-callback path).

**Real-EoE-signal discipline.** This module uses the live
``OracleParserCardSource`` Ancient Tomb printing on the Python side
AND the canonical Rust registry dict shape emitted by the C2 bridge
forward arm ``_spec_card_to_printing_dict(_carrier_aa_land_card_def(p))``
on the Rust side -- the SAME printing shape both engines read
(verified pre-flight via the bridge round-trip pin below).

This module is the Ancient Tomb Phase 4 Cycle 2 closure marker;
**ANCIENT TOMB CAMPAIGN COMPLETE**.
"""

from __future__ import annotations

import importlib.util

import pytest

from mtg_bot.cards.source import get_active_source
from mtg_bot.effects.generic.damage import (
    DealDamageToControllerAndAddMana,
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


# Canonical Rust dict for Ancient Tomb -- the EXACT shape
# ``_spec_card_to_printing_dict`` emits for the C2 bridge forward arm
# (verified pre-flight via the bridge round-trip pin below). Both
# engines read this same printing shape.
#
# Note: the ``supertypes: ["Basic"]`` entry is the Carrier-AA-Land
# builder convention -- ``_spec_card_to_printing_dict`` emits "Basic"
# for every Carrier-AA Land regardless of the printing's actual super-
# type (verified against Swarmyard / Deserted Temple / Mirrorpool /
# Meteor Crater / Reflecting Pool sibling probes which all carry the
# same "Basic" supertype on the Rust dict). The Rust engine doesn't
# gate on the supertype for the Carrier-AA mana-ability resolve, so
# this convention is harmless; bumping it requires a separate cross-
# cutting slice on the bridge floor.
_ANCIENT_TOMB_RUST_DICT = {
    "name": "Ancient Tomb",
    "card_types": ["Land"],
    "mana_cost": {},
    "effects": [],
    "supertypes": ["Basic"],
    "activated_abilities": [
        {
            "cost": {"tap_self": True},
            "effect": {
                "kind": "deal_damage_to_controller_and_add_mana",
                "damage": 2,
                "produces": [["C", 2]],
            },
            "is_mana_ability": True,
        },
    ],
}


# Vanilla {2} generic Instant -- the PAY-scenario target. A bare
# draw-1 effect resolves without target prompts; the load-bearing
# surface here is the COST payment via ``auto_tap_pay_for_cost`` on
# the Rust side (FIFO-walking the 2 C coins to pay {2} generic).
_GENERIC_TWO_INSTANT_RUST_DICT = {
    "name": "AncientTombTestGeneric2Instant",
    "card_types": ["Instant"],
    "mana_cost": {"generic": 2},
    "effects": [{"kind": "draw_cards", "count": 1}],
}


_EMPTY_MANA_POOL = {
    "W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0, "any": 0,
}


# ---------------------------------------------------------------------------
# (1) Parser SoT -- Ancient Tomb is parser-claimed and emits the
# expected Phase-4-pilot single-AA mana-ability shape (re-asserted here
# so this module is self-contained for the PROBED-tier evidence).
# ---------------------------------------------------------------------------


def test_ancient_tomb_parser_claims_card():
    """Pins the active CardSource is producing the Ancient Tomb
    printing under its canonical EoE name.
    """
    assert "Ancient Tomb" in _PRINTINGS, (
        "Ancient Tomb must be parser-claimed by the active "
        "CardSource (EoE set + reprint coverage)"
    )


def test_ancient_tomb_printed_attrs():
    """Pins the basic printing surface: bare Land (no super/subtype),
    cost ``{0}``, no power/toughness, no keywords/triggers/statics,
    one AA with the canonical Phase-4-pilot single-AA mana-ability
    shape (``DealDamageToControllerAndAddMana(damage=2, produces=(("C",
    2),))`` + bare ``{T}`` cost + ``is_mana_ability=True``). The §2
    teeth -- the admit predicate's load-bearing gates.
    """
    p = _PRINTINGS["Ancient Tomb"]
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
    # The §2 teeth -- ONE non-mana AA in the canonical single-AA shape.
    assert len(p.activated_abilities) == 1
    aa = p.activated_abilities[0]
    assert aa.cost.tap_self is True
    assert aa.cost.mana is None
    assert aa.cost.sacrifice_self is False
    assert isinstance(aa.effect, DealDamageToControllerAndAddMana)
    assert aa.effect.damage == 2
    assert aa.effect.produces == (("C", 2),)
    assert aa.is_mana_ability is True
    assert aa.sorcery_speed is False
    assert aa.tier_threshold == 0
    assert aa.activate_only_once is False


# ---------------------------------------------------------------------------
# (2) Bridge round-trip -- the C2 forward arm
# ``_spec_card_to_printing_dict`` (post-C2) on the genuine parsed
# Ancient Tomb printing emits the canonical Rust registry dict
# carrying the AA[0] with the
# ``deal_damage_to_controller_and_add_mana`` kind + damage + produces
# fields.
# ---------------------------------------------------------------------------


def test_ancient_tomb_bridge_round_trip_canonical_rust_dict():
    """The C2 admit-gate's bridge: Python printing ->
    ``_filter_deck_to_bridge_supported`` -> CardDef ->
    ``_spec_card_to_printing_dict`` -> canonical Rust registry dict
    matches ``_ANCIENT_TOMB_RUST_DICT`` byte-equal. Pins the probe's
    source-of-truth that both engines read the SAME printing shape.
    """
    from mtg_bot.parity.trajectory import _filter_deck_to_bridge_supported
    from mtg_bot.parity.cross_engine import (
        _aa_dict_to_python_activated_ability,
        _spec_card_to_printing_dict,
    )

    filt, defs = _filter_deck_to_bridge_supported(
        ["Ancient Tomb"], _PRINTINGS,
    )
    assert filt == ["Ancient Tomb"]
    assert len(defs) == 1, (
        "Ancient Tomb must pass the Phase 4 C2 admit gate post-FLIP"
    )
    cd = defs[0]
    pd = _spec_card_to_printing_dict(cd)
    assert pd == _ANCIENT_TOMB_RUST_DICT, (
        f"Ancient Tomb Rust registry dict must match the probe's "
        f"pinned shape (the bridge SoT for both engines); got pd={pd!r}, "
        f"expected={_ANCIENT_TOMB_RUST_DICT!r}"
    )
    # Reverse-arm pin: the AA dict rehydrates to a Python
    # ActivatedAbility carrying the same effect class + damage +
    # produces field values + the same cost atoms (the consumer the
    # loader reads via _aa_dict_to_python_activated_ability).
    aa_py = _aa_dict_to_python_activated_ability(
        pd["activated_abilities"][0]
    )
    assert isinstance(aa_py.effect, DealDamageToControllerAndAddMana)
    assert aa_py.effect.damage == 2
    assert aa_py.effect.produces == (("C", 2),)
    assert aa_py.cost.tap_self is True
    assert aa_py.cost.mana is None
    assert aa_py.is_mana_ability is True
    assert aa_py.tier_threshold == 0


# ---------------------------------------------------------------------------
# (3) Rust acceptance smoke -- the canonical Ancient Tomb Rust dict
# parses on ``register_printing`` (the bridge contract Rust honors).
# ---------------------------------------------------------------------------


@_rust_skip
def test_rust_parser_accepts_canonical_ancient_tomb_dict():
    """Lockstep pin: Rust's parse arm accepts the canonical Ancient
    Tomb registry-dict shape ``_ANCIENT_TOMB_RUST_DICT`` -- the SAME
    dict the C2 forward emit arm produces for the live printing.
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(_ANCIENT_TOMB_RUST_DICT)
    assert isinstance(pid, int)
    assert reg.get_printing_name(pid) == "Ancient Tomb"


# ---------------------------------------------------------------------------
# (4) Loader end-to-end admit -- Ancient Tomb admits at the
# deck-level filter post-C2 (the FLIP marker mirror).
# ---------------------------------------------------------------------------


def test_ancient_tomb_loader_end_to_end_admit():
    """End-to-end loader admit: pass ``["Ancient Tomb"]`` to
    ``_filter_deck_to_bridge_supported`` -> admitted; CardDef emitted
    carries the Phase-4-pilot single-AA shape (Land card type, no
    super/subtype on Python, single AA with the
    DealDamageToControllerAndAddMana Effect carrying damage=2 +
    produces=[["C", 2]]).
    """
    from mtg_bot.parity.trajectory import _filter_deck_to_bridge_supported

    filt, defs = _filter_deck_to_bridge_supported(
        ["Ancient Tomb"], _PRINTINGS,
    )
    assert filt == ["Ancient Tomb"]
    assert len(defs) == 1
    cd = defs[0]
    assert cd.name == "Ancient Tomb"
    assert cd.card_type == "Land"
    assert cd.subtypes == ()
    assert cd.supertypes == ()
    assert len(cd.activated_abilities) == 1
    aa_dict = cd.activated_abilities[0]
    assert aa_dict["cost"] == {"tap_self": True}
    assert aa_dict["effect"] == {
        "kind": "deal_damage_to_controller_and_add_mana",
        "damage": 2,
        "produces": [["C", 2]],
    }
    assert aa_dict["is_mana_ability"] is True


# ---------------------------------------------------------------------------
# Helper -- seat Ancient Tomb on p0's bf on both engines. Mana pools
# empty on both engines; no other permanents on either side. Returns
# ``(py, py_at, rs, rs_at)``. The starting life is parameterized so
# the MINT-at-2-life scenario can re-use this helper.
# ---------------------------------------------------------------------------


def _seat_ancient_tomb(starting_life: int = 20):
    """Seat Ancient Tomb on p0's bf on BOTH engines. Mana pools empty
    on both engines; no other permanents on either side; p0's life is
    set to ``starting_life`` on both engines. Returns
    ``(py, py_at, rs, rs_at)``.

    Both engines:
      * Ancient Tomb: ``summoning_sick = False`` (Lands lose
        summoning-sickness at the start of their controller's turn;
        we also bypass the cost-pay summoning-sick gate for
        ``tap_self`` mana abilities which is anti-CR but the test-
        helper shape sibling probes use).
      * Phase / priority: not driven (mana abilities are CR 605.1
        "any time you could cast an instant" + bypass-stack; the
        dispatch arm accepts ``apply_action`` directly without phase
        gating).

    Ancient Tomb is the ONLY permanent on either bf. Pre-state pin:
    empty mana pool on both engines for the probe's load-bearing pool-
    delta comparisons.

    Note: Ancient Tomb's resolve doesn't scan the battlefield for
    any derivation -- the produces tuple ``(("C", 2),)`` lives on the
    Effect itself (a fields variant on the Rust side; dataclass field
    on the Python side). The bf-walk + produces-union machinery the
    MC/RP siblings exercise is absent here; this probe purely pins
    the fixed-mint + fixed-damage arms.
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

    at_printing = _PRINTINGS["Ancient Tomb"]

    # ---- Python: seat Ancient Tomb on p0's bf. ----
    py_at = py.new_object(
        at_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_at.summoning_sick = False
    py_at.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_at)
    py.players[0].life = starting_life
    py.active_player_idx = 0
    py.priority_player_idx = 0
    py.players[0].agent = None
    py.players[1].agent = None

    # ---- Rust: seat Ancient Tomb on p0's bf. ----
    rs_at = rs.register_and_inject_object(
        _ANCIENT_TOMB_RUST_DICT, 0, ZONE_BATTLEFIELD,
    )
    rs.force_set_summoning_sick(rs_at, False)
    rs.set_life(0, starting_life)

    return py, py_at, rs, rs_at


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
# (5) GENUINE real-EoE cross-engine byte-equal probe -- Scenario MINT:
# Ancient Tomb at 20 life mints 2 C coins + drops life by 2 byte-equal
# cross-engine. PROBED tier flip evidence (Cycle 2 closure marker,
# scenario MINT -- THE LOAD-BEARING 2-mana-mint + 2-damage-rider).
# ---------------------------------------------------------------------------


@_rust_skip
def test_cross_engine_real_eoe_ancient_tomb_mint_scenario_parity():
    """**GENUINE real-EoE cross-engine probe -- Scenario MINT.** PROBED
    tier flip evidence (Cycle 2 closure marker, scenario MINT -- THE
    LOAD-BEARING 2-mana-mint + 2-damage-rider).

    Pre-state on both engines:
      * Ancient Tomb on p0's bf (untapped, not summoning-sick).
      * p0's life = 20 (default starting life).
      * NO other permanents on either side, empty mana pool on both
        engines.

    Drive: activate Ancient Tomb's AA[0] directly via ``apply_action``
    on both engines. The dispatch arm pays the ``tap_self`` cost
    (taps Ancient Tomb), applies the damage rider (p0's life -= 2),
    then mints the fixed ``produces=(("C", 2),)`` tuple as 2 C coins
    into p0's pool.

    Post-resolve (both engines, byte-equal):
      * p0's mana pool has exactly 2 C coins.
      * p0's life = 18 (20 - damage=2).
      * Stack empty on both engines (mana-ability bypass-stack).
      * Ancient Tomb is tapped on both engines.
      * p1's mana pool untouched (empty) -- source-controller-scoping.
      * p1's life untouched (20) -- the damage scopes to source-
        controller, not active_player.
    """
    # Real-EoE-signal discipline: bind the genuine parsed printing
    # inside the *_parity body so the measure-pool-parity classifier
    # credits THIS slug to the probe (the canonical idiom the sibling
    # per-card probes use).
    at_printing = _PRINTINGS.get("Ancient Tomb")
    if at_printing is None:
        pytest.skip("Ancient Tomb absent from active CardSource")

    py, py_at, rs, rs_at = _seat_ancient_tomb(starting_life=20)

    # ---- Pre-state pins.
    assert _py_mana_pool_counts(py, 0) == _EMPTY_MANA_POOL
    assert rs.mana_pool_snapshot(0) == _EMPTY_MANA_POOL
    assert py_at.tapped is False
    assert rs.is_tapped(rs_at) is False
    assert py.players[0].life == 20
    assert rs.get_life(0) == 20
    assert py.players[1].life == 20
    assert rs.get_life(1) == 20

    # ---- Drive AA[0] activation on both engines.
    from mtg_bot.actions import ActivateAbility, apply_action

    apply_action(
        py, 0, ActivateAbility(source_id=py_at.id, ability_index=0),
    )
    rs.apply_action(
        {
            "kind": "activate_ability",
            "source_id": rs_at,
            "ability_index": 0,
        }
    )

    # ---- Post-resolve observables: 2 C coins on both engines.
    expected_pool = dict(_EMPTY_MANA_POOL, C=2)
    py_pool = _py_mana_pool_counts(py, 0)
    rs_pool = rs.mana_pool_snapshot(0)
    assert py_pool == expected_pool, (
        f"Python: Ancient Tomb AA[0] must mint 2 C coins from fixed "
        f"produces=(('C', 2),); got py_pool={py_pool}"
    )
    assert rs_pool == expected_pool, (
        f"Rust: Ancient Tomb AA[0] must mint 2 C coins from fixed "
        f"produces=[['C', 2]]; got rs_pool={rs_pool}"
    )
    assert py_pool == rs_pool, (
        f"Cross-engine byte-equal (2-C-coin mint pool): "
        f"py_pool={py_pool}, rs_pool={rs_pool}"
    )

    # ---- Post-resolve life: p0 -= damage=2 byte-equal.
    assert py.players[0].life == 18, (
        f"Python: Ancient Tomb damage rider must drop p0's life by "
        f"2 (20 -> 18); got {py.players[0].life}"
    )
    assert rs.get_life(0) == 18, (
        f"Rust: Ancient Tomb damage rider must drop p0's life by 2 "
        f"(20 -> 18); got {rs.get_life(0)}"
    )
    assert py.players[0].life == rs.get_life(0), (
        f"Cross-engine byte-equal (life delta): "
        f"py={py.players[0].life}, rs={rs.get_life(0)}"
    )

    # ---- Stack empty on both engines (mana-ability bypass-stack).
    assert len(py.stack) == 0, (
        "Python: mana-ability bypass-stack -- stack must be empty"
    )
    assert rs.stack_size() == 0, (
        "Rust: mana-ability bypass-stack -- stack must be empty"
    )

    # ---- Ancient Tomb is tapped on both engines (tap_self cost paid).
    assert py_at.tapped is True, (
        "Python: tap_self cost must tap Ancient Tomb"
    )
    assert rs.is_tapped(rs_at) is True, (
        "Rust: tap_self cost must tap Ancient Tomb"
    )

    # ---- p1's pool untouched (the source-controller-scoping
    # invariant -- coins must go to p0 only).
    py_pool_p1 = _py_mana_pool_counts(py, 1)
    rs_pool_p1 = rs.mana_pool_snapshot(1)
    assert py_pool_p1 == _EMPTY_MANA_POOL, (
        f"Python: p1's pool must stay empty (source-controller-"
        f"scoping); got py_pool_p1={py_pool_p1}"
    )
    assert rs_pool_p1 == _EMPTY_MANA_POOL, (
        f"Rust: p1's pool must stay empty (source-controller-"
        f"scoping); got rs_pool_p1={rs_pool_p1}"
    )

    # ---- p1's life untouched (damage rider scopes to source-
    # controller, not active_player or all-opponents).
    assert py.players[1].life == 20, (
        f"Python: p1's life must stay 20 (damage rider scopes to "
        f"source-controller); got {py.players[1].life}"
    )
    assert rs.get_life(1) == 20, (
        f"Rust: p1's life must stay 20 (damage rider scopes to "
        f"source-controller); got {rs.get_life(1)}"
    )


# ---------------------------------------------------------------------------
# (6) GENUINE real-EoE cross-engine byte-equal probe -- Scenario
# MINT-at-2-life: Ancient Tomb activated at exactly 2 life takes life
# to 0 byte-equal AND still mints 2 C coins. PROBED tier flip evidence
# (Cycle 2 closure marker, scenario MINT-at-2-life -- THE LOAD-BEARING
# self-kill edge case).
# ---------------------------------------------------------------------------


@_rust_skip
def test_cross_engine_real_eoe_ancient_tomb_mint_at_2_life_parity():
    """**GENUINE real-EoE cross-engine probe -- Scenario MINT-at-2-
    life.** PROBED tier flip evidence (Cycle 2 closure marker,
    scenario MINT-at-2-life -- THE LOAD-BEARING self-kill edge case).

    Pre-state on both engines:
      * Ancient Tomb on p0's bf (untapped, not summoning-sick).
      * p0's life = 2 (the edge case -- damage = current life).
      * Empty mana pool on both engines.

    Drive: activate Ancient Tomb's AA[0] on both engines. The
    damage rider drops p0's life from 2 to 0 EXACTLY (Python:
    ``p.life -= self.damage`` = 2 - 2 = 0; Rust: ``player.life -=
    damage as i32`` = 2 - 2 = 0). The mint still runs AFTER the
    damage (Python's ``.resolve()`` unconditionally appends
    ManaCoins after the life decrement; Rust's resolve arm mirrors
    by running ``push_coins`` after the life decrement). The lose-
    the-game SBA runs at the NEXT SBA pass which is outside the
    scope of THIS probe -- the post-resolve mid-step state is what
    we byte-equal here.

    Post-resolve (both engines, byte-equal):
      * p0's life = 0 (2 - damage=2 = 0).
      * p0's mana pool has exactly 2 C coins (the mint still runs
        even at lethal damage -- mirrors the lifetime contract of
        the resolve arm; SBA is the orchestrator's job).
      * Stack empty on both engines (mana-ability bypass-stack).
      * Ancient Tomb is tapped on both engines.
      * p1's pool + life untouched.

    Note on order: the resolve arm explicitly does damage FIRST then
    mint SECOND on both engines. If a future refactor flipped the
    order this probe would still pass on observable end-state (final
    life = 0, final pool = 2 C) -- there's no observable inter-step
    state captured here. The C1 substrate's
    ``test_resolve_at_1_life_drives_life_to_negative_1_and_still_
    mints_mana`` pin documents the order invariant at the unit level;
    THIS probe ratifies the observable end-state cross-engine at the
    real-EoE printing surface.
    """
    at_printing = _PRINTINGS.get("Ancient Tomb")
    if at_printing is None:
        pytest.skip("Ancient Tomb absent from active CardSource")

    py, py_at, rs, rs_at = _seat_ancient_tomb(starting_life=2)

    # ---- Pre-state pins.
    assert _py_mana_pool_counts(py, 0) == _EMPTY_MANA_POOL
    assert rs.mana_pool_snapshot(0) == _EMPTY_MANA_POOL
    assert py.players[0].life == 2
    assert rs.get_life(0) == 2

    # ---- Drive AA[0] activation on both engines.
    from mtg_bot.actions import ActivateAbility, apply_action

    apply_action(
        py, 0, ActivateAbility(source_id=py_at.id, ability_index=0),
    )
    rs.apply_action(
        {
            "kind": "activate_ability",
            "source_id": rs_at,
            "ability_index": 0,
        }
    )

    # ---- Post-resolve life: p0 drops to EXACTLY 0 byte-equal.
    assert py.players[0].life == 0, (
        f"Python: at 2 life, Ancient Tomb damage=2 must drive life "
        f"to EXACTLY 0; got {py.players[0].life}"
    )
    assert rs.get_life(0) == 0, (
        f"Rust: at 2 life, Ancient Tomb damage=2 must drive life "
        f"to EXACTLY 0; got {rs.get_life(0)}"
    )
    assert py.players[0].life == rs.get_life(0), (
        f"Cross-engine byte-equal (life delta at lethal): "
        f"py={py.players[0].life}, rs={rs.get_life(0)}"
    )

    # ---- Post-resolve pool: 2 C coins minted AFTER the lethal damage
    # (the resolve arm's lifetime contract is damage-first then mint;
    # SBA runs at the next pass which is outside this probe's scope).
    expected_pool = dict(_EMPTY_MANA_POOL, C=2)
    py_pool = _py_mana_pool_counts(py, 0)
    rs_pool = rs.mana_pool_snapshot(0)
    assert py_pool == expected_pool, (
        f"Python: even at lethal damage, AA[0] mints 2 C coins "
        f"AFTER the damage (resolve-arm lifetime contract); got "
        f"py_pool={py_pool}"
    )
    assert rs_pool == expected_pool, (
        f"Rust: even at lethal damage, AA[0] mints 2 C coins AFTER "
        f"the damage; got rs_pool={rs_pool}"
    )
    assert py_pool == rs_pool, (
        f"Cross-engine byte-equal (post-lethal pool): "
        f"py={py_pool}, rs={rs_pool}"
    )

    # ---- Stack empty on both engines.
    assert len(py.stack) == 0
    assert rs.stack_size() == 0

    # ---- Ancient Tomb is tapped on both engines.
    assert py_at.tapped is True
    assert rs.is_tapped(rs_at) is True


# ---------------------------------------------------------------------------
# (7) GENUINE real-EoE cross-engine byte-equal probe -- Scenario
# MINT+PAY: Ancient Tomb mints 2 C coins, then a {2} generic Instant
# is cast using the 2 minted coins. PROBED tier flip evidence (Cycle 2
# closure marker, scenario MINT+PAY -- THE LOAD-BEARING end-to-end
# pay-from-mint).
# ---------------------------------------------------------------------------


@_rust_skip
def test_cross_engine_real_eoe_ancient_tomb_mint_then_pay_byte_equal():
    """**GENUINE real-EoE cross-engine probe -- Scenario MINT+PAY.**
    PROBED tier flip evidence (Cycle 2 closure marker, scenario
    MINT+PAY -- THE LOAD-BEARING end-to-end pay-from-mint pin).

    Drives the **ACTUAL parsed Ancient Tomb printing** through a
    full mint -> pay sequence on BOTH engines and asserts byte-equality
    on the post-pay ManaPool snapshot at each step:

      1. Empty starting pool -- 7-key snapshot all-zero on both sides.
      2. Resolve Ancient Tomb's AA[0] (mint 2 C coins from the fixed
         produces tuple ``(("C", 2),)``, drop p0's life by 2) on
         Python via the actions dispatch; ``apply_action`` on Rust --
         both pools show ``C=2``, all other slots 0; p0 at 18 life.
      3. Pay {2} from the 2 minted C coins -- Python pops both C
         coins (mirrors ``actions._consume_for_color`` /
         ``auto_tap_for_cost`` for the generic-cost slot); Rust casts
         a {2} generic Instant via ``cast_spell_noncreature``, which
         routes through ``auto_tap_pay_for_cost``. Both pools fully
         drain.

    **Bridge arms exercised:**
      * ``deal_damage_to_controller_and_add_mana`` (mint + damage,
        Cycle 1 substrate at ``c250a60d``).
      * ``activate_ability`` (Ancient Tomb's AA[0] dispatch).
      * Python ``DealDamageToControllerAndAddMana.resolve``
        (the life-decrement-then-append-ManaCoins lifetime).
      * Rust ``state_ops_resolve.rs::apply_effect`` arm for
        ``DealDamageToControllerAndAddMana`` (the life-decrement-
        then-push_coins lifetime).
      * Rust ``GameState.cast_spell_noncreature`` ->
        ``auto_tap_pay_for_cost`` (the {2} generic PAY path).

    **Observables asserted at each step:**
      * Step-1 snapshot byte-equality (empty pool, 7 zeros on both).
      * Step-2 snapshot byte-equality (post-mint: ``C=2`` only;
        life=18 on both).
      * Step-3 snapshot byte-equality (post-pay: fully empty).

    Note: the Rust side casts a {2} generic Instant which DOES go
    through the stack (it's a non-mana spell -- bypass-stack is for
    mana abilities). The post-pay assertion compares the POOL only,
    not the stack size, because the Python side here does a manual
    coin pop without driving the cast through the actions dispatch
    (the spell-cast / draw-resolve interplay is not the load-bearing
    surface here -- the COST payment is).
    """
    at_printing = _PRINTINGS.get("Ancient Tomb")
    if at_printing is None:
        pytest.skip("Ancient Tomb absent from active CardSource")

    py, py_at, rs, rs_at = _seat_ancient_tomb(starting_life=20)

    # ---- Step 1: Empty-pool snapshot byte-equality (sanity / pre-mint).
    expected_empty = dict(_EMPTY_MANA_POOL)
    py_pool_pre = _py_mana_pool_counts(py, 0)
    rs_pool_pre = rs.mana_pool_snapshot(0)
    assert py_pool_pre == expected_empty
    assert rs_pool_pre == expected_empty
    assert py_pool_pre == rs_pool_pre, (
        f"Step-1 empty-pool snapshot must be byte-equal cross-engine; "
        f"python={py_pool_pre}, rust={rs_pool_pre}"
    )

    # ---- Step 2: Mint. Activate AT's AA[0] on both engines.
    from mtg_bot.actions import ActivateAbility, apply_action

    apply_action(
        py, 0, ActivateAbility(source_id=py_at.id, ability_index=0),
    )
    rs.apply_action(
        {
            "kind": "activate_ability",
            "source_id": rs_at,
            "ability_index": 0,
        }
    )

    expected_post_mint = dict(_EMPTY_MANA_POOL, C=2)
    py_pool_post_mint = _py_mana_pool_counts(py, 0)
    rs_pool_post_mint = rs.mana_pool_snapshot(0)
    assert py_pool_post_mint == expected_post_mint, (
        f"Step-2 Python post-mint pool must reflect 2 C coins; got "
        f"{py_pool_post_mint}"
    )
    assert rs_pool_post_mint == expected_post_mint, (
        f"Step-2 Rust post-mint pool must reflect 2 C coins; got "
        f"{rs_pool_post_mint}"
    )
    assert py_pool_post_mint == rs_pool_post_mint, (
        f"Step-2 post-mint snapshot must be byte-equal cross-engine; "
        f"python={py_pool_post_mint}, rust={rs_pool_post_mint}"
    )
    # Life must also be byte-equal post-mint (the damage rider half).
    assert py.players[0].life == 18 == rs.get_life(0), (
        f"Step-2 post-mint life must be 18 (= 20 - damage=2) on both "
        f"engines; python={py.players[0].life}, rust={rs.get_life(0)}"
    )

    # ---- Step 3: Pay {2}. Python: pop the 2 C coins from p0's pool
    # (mirrors the spend by ``actions._consume_for_color`` for the
    # generic-cost slot which accepts any color). Rust: cast a {2}
    # generic Instant via ``cast_spell_noncreature``, which routes
    # through ``auto_tap_pay_for_cost``.

    # Python: pop both coins.
    py.players[0].mana_pool.pop(0)
    py.players[0].mana_pool.pop(0)

    # Rust: register library filler + the {2} instant, then cast it.
    rs.register_and_inject_object(
        {
            "name": "AncientTombTestLibFiller",
            "card_types": ["Land"],
            "supertypes": ["Basic"],
        },
        0,
        ZONE_LIBRARY,
    )
    spell_id = rs.register_and_inject_object(
        _GENERIC_TWO_INSTANT_RUST_DICT, 0, ZONE_HAND,
    )
    ok = rs.cast_spell_noncreature(spell_id, 0)
    assert ok, (
        "Rust ``cast_spell_noncreature`` must accept the 2 minted C "
        "coins as payment for the {2} generic requirement via "
        "``auto_tap_pay_for_cost``"
    )

    expected_post_pay = dict(_EMPTY_MANA_POOL)
    py_pool_post_pay = _py_mana_pool_counts(py, 0)
    rs_pool_post_pay = rs.mana_pool_snapshot(0)
    assert py_pool_post_pay == expected_post_pay, (
        f"Step-3 Python post-pay pool must be fully drained; got "
        f"{py_pool_post_pay}"
    )
    assert rs_pool_post_pay == expected_post_pay, (
        f"Step-3 Rust post-pay pool must be fully drained; got "
        f"{rs_pool_post_pay}"
    )
    assert py_pool_post_pay == rs_pool_post_pay, (
        f"Step-3 post-pay snapshot must be byte-equal cross-engine; "
        f"python={py_pool_post_pay}, rust={rs_pool_post_pay}"
    )

    # p1's pool + life untouched throughout (source-controller-scoping
    # invariant + the {2} spell is cast by p0 only).
    assert _py_mana_pool_counts(py, 1) == _EMPTY_MANA_POOL
    assert rs.mana_pool_snapshot(1) == _EMPTY_MANA_POOL
    assert py.players[1].life == 20
    assert rs.get_life(1) == 20
