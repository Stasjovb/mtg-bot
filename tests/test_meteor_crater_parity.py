"""Meteor Crater -- per-card real-EoE cross-engine byte-equal probe
(``covered_by_construction`` -> PROBED tier flip; Meteor Crater Phase 4
Cycle 2 closure marker; **METEOR CRATER CAMPAIGN FULL CLOSURE**).

Meteor Crater is a bare ``{T}``-cost mana-ability Land in the EoE pool
with the Phase-4-pilot single-AA mana-ability shape carrying the new
``AddOneManaOfChosenPermanentColor`` Effect class (Worker H's C1
substrate at commit ``eb059eaa`` shipped the Rust unit variant + parse
+ to_pydict + source-controller battlefield walk + WUBRG-canonical-first
color pick + empty-union colorless ``{C}`` defensive fallback + cross-
engine bridge forward + reverse arms):

    AA[0] -- ``{T}: Choose a color of a permanent you control. Add
             one mana of that color.``
        cost = ActivationCost(tap_self=True)
        effect = AddOneManaOfChosenPermanentColor()
        is_mana_ability = True
        sorcery_speed = False
        tier_threshold = 0

Meteor Crater is the SOLE EoE carrier of the
``AddOneManaOfChosenPermanentColor`` Effect class per
``docs/BLOCKED_TAIL_TRACTABILITY_SCOUT_2026-05-27.md`` §#1; it admits at
the Carrier-AA Phase-1 admit gate post-Cycle-2 via the combined
Effect-class widen (16 -> 17) + the Phase-1.5a bare ``{T}`` cost gate
+ the Phase-4E ``is_mana_ability=True`` AA-rider widen (commit
``daecd399``). No additional rider work is needed at C2 — the per-AA
admit gate ``_aa_is_phase1_sub_shape_a`` ADMITS Meteor Crater's AA[0]
on the Effect-class widen alone.

**Multi-cycle DECLINED -> ADMITTED -> PROBED transition.**

  * **Meteor Crater Phase 4 Cycle 1 (Rust substrate landing, commit
    ``eb059eaa``, 2026-05-27).** Rust substrate:
    ``Effect::AddOneManaOfChosenPermanentColor`` unit variant + parser
    + resolver + ``to_pydict`` + cross-engine bridge arms (forward +
    reverse). Meteor Crater STAYED DECLINED at the admit gate post-C1
    -- the Effect-class admit set ``_carrier_aa_phase_1_effect_classes``
    didn't include the new Effect class.
  * **Meteor Crater Phase 4 Cycle 2 (THIS LANE; THE FLIP + THE PROBE
    -- Scenarios MINT + MINT+PAY; MEMORATOR CRATER CAMPAIGN CLOSURE).**
    Python admit widen:
      - ``_carrier_aa_phase_1_effect_classes`` admit-set widen
        16 -> 17 (adds ``AddOneManaOfChosenPermanentColor``).
    Meteor Crater FLIPS DECLINED -> ADMITTED at the production deck
    filter end-to-end (LAND admits 9 -> 10 at the live-pool walk);
    the printing-level admit cascades through
    ``_printing_is_bridge_simple_carrier_aa_any`` -> Land sibling ->
    ``_carrier_aa_land_card_def`` (the cross-engine builder gate).

    Plus the per-card real-EoE byte-equality probe driving BOTH engines
    through TWO scenarios:

    **Scenario MINT (load-bearing color-pick from controller's bf).**
    Meteor Crater on p0's bf with EXACTLY ONE mono-white creature also
    on p0's bf (no other permanents -> color union = {"W"} on both
    engines). Activate Meteor Crater's AA[0] on BOTH engines via
    ``apply_action({"kind": "activate_ability", "source_id": MC,
    "ability_index": 0})``.
    Post-resolve byte-equal observables on both engines:
      - p0's mana pool has exactly 1 W coin (the color union of
        {"W"} resolves byte-equal cross-engine -- Rust's WUBRG-
        canonical-first pick and Python's ``sorted(options)[0]``
        both produce "W" when the union has a single element).
      - Stack empty on both engines (mana abilities bypass the
        stack per CR 605.3a; ``is_mana_ability=True``).
      - Meteor Crater is tapped on both engines (``tap_self``
        cost paid).
      - The Bear stays untapped on both engines.

    **Scenario MINT+PAY (load-bearing end-to-end pay-from-mint).**
    Same fixture as Scenario MINT, but additionally cast a ``{W}``
    Instant from p0's hand using the minted W coin. Pin both the
    mint half (post-mint pool = ``W=1``) AND the pay half (post-cast
    pool fully drained). Pre-fix-Worker-K-isolated this is the
    canonical MINT+PAY shape per the BLOCKED-tail scout's C2 spec:

      1. Resolve AA[0] -> 1 W coin minted.
      2. Cast ``{W}`` Instant -- Python's
         ``actions._consume_for_color`` pops the W coin; Rust's
         ``cast_spell_noncreature`` -> ``auto_tap_pay_for_cost``
         FIFO-walks the pool, finds the W coin, decrements
         ``mp.W``, removes from ``mp.coins``.
      3. Both pools end fully empty (byte-equal cross-engine).

**Scripted-picker semantics.** The probe drives ``apply_action`` /
``apply_action`` directly on both engines with explicit
``(source_id, ability_index)`` pairs. The mana-ability bypass-stack
semantics resolve the effect immediately (no stack item to drain).
The MINT scenario seats EXACTLY ONE colored permanent (a mono-white
Bear) on the source-controller's battlefield so the color union has
exactly ONE element ({"W"}) -- BOTH the Rust WUBRG-canonical-first
picker AND Python's ``sorted(options)[0]`` lexicographic-first picker
return "W" on a single-element union. This avoids exercising the
WUBRG-vs-sorted-alphabetic divergence (documented in
``docs/SEARCH_LIMITATIONS.md`` -- the divergence ONLY fires on
multi-color unions; on single-color unions the two pickers agree).

**WUBRG-canonical-vs-sorted-alphabetic divergence (HONEST-STOP).**
Rust picks the canonical-first WUBRG-ordered color from the union
(e.g. ``{'U','G','R'}`` -> ``U``); Python picks ``sorted(options)[0]``
(alphabetic-first -> ``G`` from the same set). The divergence is
deliberate per the Phase-4E ``any`` precedent (commit ``daecd399``)
and is documented in ``docs/SEARCH_LIMITATIONS.md`` under the
Meteor Crater Phase 4 C2 entry. THIS probe DELIBERATELY avoids the
divergence by seating only a single colored permanent on the source-
controller's bf; future multi-color probes will need either the
agent-callback ``choose_mana_color`` plumbing (an INDEPENDENT cross-
cutting slice -- round-28 precedent applies) OR an explicit Python
agent seating that converges both engines on the same color BEFORE
the byte-equality pin lands.

**Real-EoE-signal discipline.** This module uses the live
``OracleParserCardSource`` Meteor Crater printing on the Python side
AND the canonical Rust registry dict shape emitted by the C2 bridge
forward arm ``_spec_card_to_printing_dict(_carrier_aa_land_card_def(p))``
on the Rust side -- the SAME printing shape both engines read
(verified pre-flight via the bridge round-trip pin below).

This module is the Meteor Crater Phase 4 Cycle 2 closure marker;
**METEOR CRATER CAMPAIGN COMPLETE**.
"""

from __future__ import annotations

import importlib.util

import pytest

from mtg_bot.cards.source import get_active_source
from mtg_bot.effects.generic.mana import (
    AddOneManaOfChosenPermanentColor,
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


# Canonical Rust dict for Meteor Crater -- the EXACT shape
# ``_spec_card_to_printing_dict`` emits for the C2 bridge forward arm
# (verified pre-flight via the bridge round-trip pin below). Both
# engines read this same printing shape.
#
# Note: the ``supertypes: ["Basic"]`` entry is the Carrier-AA-Land
# builder convention -- ``_spec_card_to_printing_dict`` emits "Basic"
# for every Carrier-AA Land regardless of the printing's actual super-
# type (verified against Swarmyard / Deserted Temple / Mirrorpool
# sibling probes which all carry the same "Basic" supertype on the
# Rust dict). The Rust engine doesn't gate on the supertype for the
# Carrier-AA mana-ability resolve, so this convention is harmless;
# bumping it requires a separate cross-cutting slice on the bridge
# floor.
_METEOR_CRATER_RUST_DICT = {
    "name": "Meteor Crater",
    "card_types": ["Land"],
    "mana_cost": {},
    "effects": [],
    "supertypes": ["Basic"],
    "activated_abilities": [
        {
            "cost": {"tap_self": True},
            "effect": {
                "kind": "add_one_mana_of_chosen_permanent_color",
            },
            "is_mana_ability": True,
        },
    ],
}


# Vanilla mono-white Bear -- the source-controller's-bf color-union
# fixture. A 2/2 Creature with mana_cost={W,1} contributes "W" (and
# only "W") to the color union per CR 105.2 (colored mana symbols in
# the cost determine the permanent's colors; generic pips don't).
_WHITE_BEAR_RUST_DICT = {
    "name": "MeteorCraterTestWhiteBear",
    "card_types": ["Creature"],
    "mana_cost": {"W": 1, "generic": 1},
    "power": 2,
    "toughness": 2,
}


# Vanilla {W} Instant -- the PAY-scenario target. A bare draw-1 effect
# resolves without target prompts; the load-bearing surface here is
# the COST payment via ``auto_tap_pay_for_cost`` on the Rust side and
# ``_consume_for_color`` on the Python side.
_WHITE_INSTANT_RUST_DICT = {
    "name": "MeteorCraterTestWhiteInstant",
    "card_types": ["Instant"],
    "mana_cost": {"W": 1},
    "effects": [{"kind": "draw_cards", "count": 1}],
}


_EMPTY_MANA_POOL = {
    "W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0, "any": 0,
}


# ---------------------------------------------------------------------------
# (1) Parser SoT -- Meteor Crater is parser-claimed and emits the
# expected Phase-4-pilot single-AA mana-ability shape (re-asserted here
# so this module is self-contained for the PROBED-tier evidence).
# ---------------------------------------------------------------------------


def test_meteor_crater_parser_claims_card():
    """Pins the active CardSource is producing the Meteor Crater
    printing under its canonical EoE name.
    """
    assert "Meteor Crater" in _PRINTINGS, (
        "Meteor Crater must be parser-claimed by the active CardSource "
        "(EoE set + reprint coverage)"
    )


def test_meteor_crater_printed_attrs():
    """Pins the basic printing surface: bare Land (no super/subtype),
    cost ``{0}``, no power/toughness, no keywords/triggers/statics,
    one AA with the canonical Phase-4-pilot single-AA mana-ability
    shape (``AddOneManaOfChosenPermanentColor`` + bare ``{T}`` cost +
    ``is_mana_ability=True``). The §2 teeth -- the admit predicate's
    load-bearing gates.
    """
    p = _PRINTINGS["Meteor Crater"]
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
    assert isinstance(aa.effect, AddOneManaOfChosenPermanentColor)
    assert aa.is_mana_ability is True
    assert aa.sorcery_speed is False
    assert aa.tier_threshold == 0
    assert aa.activate_only_once is False


# ---------------------------------------------------------------------------
# (2) Bridge round-trip -- the C2 forward arm
# ``_spec_card_to_printing_dict`` (post-C2) on the genuine parsed
# Meteor Crater printing emits the canonical Rust registry dict
# carrying the AA[0] with the new ``add_one_mana_of_chosen_permanent_
# color`` kind.
# ---------------------------------------------------------------------------


def test_meteor_crater_bridge_round_trip_canonical_rust_dict():
    """The C2 admit-gate's bridge: Python printing ->
    ``_filter_deck_to_bridge_supported`` -> CardDef ->
    ``_spec_card_to_printing_dict`` -> canonical Rust registry dict
    matches ``_METEOR_CRATER_RUST_DICT`` byte-equal. Pins the probe's
    source-of-truth that both engines read the SAME printing shape.
    """
    from mtg_bot.parity.trajectory import _filter_deck_to_bridge_supported
    from mtg_bot.parity.cross_engine import (
        _aa_dict_to_python_activated_ability,
        _spec_card_to_printing_dict,
    )

    filt, defs = _filter_deck_to_bridge_supported(
        ["Meteor Crater"], _PRINTINGS,
    )
    assert filt == ["Meteor Crater"]
    assert len(defs) == 1, (
        "Meteor Crater must pass the Phase 4 C2 admit gate post-FLIP"
    )
    cd = defs[0]
    pd = _spec_card_to_printing_dict(cd)
    assert pd == _METEOR_CRATER_RUST_DICT, (
        f"Meteor Crater Rust registry dict must match the probe's "
        f"pinned shape (the bridge SoT for both engines); got pd={pd!r}, "
        f"expected={_METEOR_CRATER_RUST_DICT!r}"
    )
    # Reverse-arm pin: the AA dict rehydrates to a Python
    # ActivatedAbility carrying the same effect class and the same
    # cost atoms (the consumer the loader reads via
    # _aa_dict_to_python_activated_ability).
    aa_py = _aa_dict_to_python_activated_ability(
        pd["activated_abilities"][0]
    )
    assert isinstance(aa_py.effect, AddOneManaOfChosenPermanentColor)
    assert aa_py.cost.tap_self is True
    assert aa_py.cost.mana is None
    assert aa_py.is_mana_ability is True
    assert aa_py.tier_threshold == 0


# ---------------------------------------------------------------------------
# (3) Rust acceptance smoke -- the canonical Meteor Crater Rust dict
# parses on ``register_printing`` (the bridge contract Rust honors).
# ---------------------------------------------------------------------------


@_rust_skip
def test_rust_parser_accepts_canonical_meteor_crater_dict():
    """Lockstep pin: Rust's parse arm accepts the canonical Meteor
    Crater registry-dict shape ``_METEOR_CRATER_RUST_DICT`` -- the
    SAME dict the C2 forward emit arm produces for the live printing.
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(_METEOR_CRATER_RUST_DICT)
    assert isinstance(pid, int)
    assert reg.get_printing_name(pid) == "Meteor Crater"


# ---------------------------------------------------------------------------
# (4) Loader end-to-end admit -- Meteor Crater admits at the deck-level
# filter post-C2 (the FLIP marker mirror).
# ---------------------------------------------------------------------------


def test_meteor_crater_loader_end_to_end_admit():
    """End-to-end loader admit: pass ``["Meteor Crater"]`` to
    ``_filter_deck_to_bridge_supported`` -> admitted; CardDef emitted
    carries the Phase-4-pilot single-AA shape (Land card type, no
    super/subtype on Python, single AA with the AddOneManaOfChosen
    PermanentColor Effect).
    """
    from mtg_bot.parity.trajectory import _filter_deck_to_bridge_supported

    filt, defs = _filter_deck_to_bridge_supported(
        ["Meteor Crater"], _PRINTINGS,
    )
    assert filt == ["Meteor Crater"]
    assert len(defs) == 1
    cd = defs[0]
    assert cd.name == "Meteor Crater"
    assert cd.card_type == "Land"
    assert cd.subtypes == ()
    assert cd.supertypes == ()
    assert len(cd.activated_abilities) == 1
    aa_dict = cd.activated_abilities[0]
    assert aa_dict["cost"] == {"tap_self": True}
    assert aa_dict["effect"] == {
        "kind": "add_one_mana_of_chosen_permanent_color",
    }
    assert aa_dict["is_mana_ability"] is True


# ---------------------------------------------------------------------------
# Helper -- seat Meteor Crater + a mono-white Bear on both engines.
# Mana pools empty on both engines; no other permanents on either side.
# The Bear is the SOLE colored permanent on the source-controller's bf
# -- color union = {"W"} on both engines -- so BOTH the Rust WUBRG-
# canonical-first picker AND Python's sorted-alphabetic picker pick
# "W". Returns ``(py, py_mc, py_bear, rs, rs_mc, rs_bear)``.
# ---------------------------------------------------------------------------


def _seat_meteor_crater_with_white_bear():
    """Seat Meteor Crater + a mono-white Bear on p0's bf on BOTH
    engines. Mana pools empty on both engines; no other permanents on
    either side. Returns ``(py, py_mc, py_bear, rs, rs_mc, rs_bear)``.

    Both engines:
      * Meteor Crater: ``summoning_sick = False`` (Lands lose
        summoning-sickness at the start of their controller's turn;
        we also bypass the cost-pay summoning-sick gate for
        ``tap_self`` mana abilities which is anti-CR but the test-
        helper shape sibling probes use).
      * Mono-white Bear: ``summoning_sick = False`` (so the bf walk
        sees the Bear as a stable colored permanent; the Bear is
        NOT activated here, it's just a color-union contributor).
      * Phase / priority: not driven (mana abilities are CR 605.1
        "any time you could cast an instant" + bypass-stack; the
        dispatch arm accepts ``apply_action`` directly without phase
        gating).

    Meteor Crater + the Bear are the ONLY permanents on either bf.
    Pre-state pin: empty mana pool on both engines for the probe's
    load-bearing pool-delta comparisons.
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

    mc_printing = _PRINTINGS["Meteor Crater"]

    # ---- Python: seat Meteor Crater on p0's bf. ----
    py_mc = py.new_object(
        mc_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_mc.summoning_sick = False
    py_mc.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_mc)

    # ---- Python: seat the mono-white Bear on p0's bf. The Bear's
    # printing carries mana_cost={W,1}, which contributes "W" to the
    # color union. We need to synthesize the printing on the Python
    # side since the parser SoT doesn't include this test fixture; we
    # build a minimal CardPrinting object that mirrors the Rust dict.
    from mtg_bot.cards.base import CardPrinting, ManaCost

    bear_printing = CardPrinting(
        name="MeteorCraterTestWhiteBear",
        mana_cost_str="{1}{W}",
        mana_cost=ManaCost(generic=1, colored=(("W", 1),)),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=2,
        toughness=2,
    )
    py_bear = py.new_object(
        bear_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_bear.summoning_sick = False
    py_bear.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_bear)

    py.active_player_idx = 0
    py.priority_player_idx = 0
    py.players[0].agent = None
    py.players[1].agent = None

    # ---- Rust: seat Meteor Crater + the Bear on p0's bf. ----
    rs_mc = rs.register_and_inject_object(
        _METEOR_CRATER_RUST_DICT, 0, ZONE_BATTLEFIELD,
    )
    rs.force_set_summoning_sick(rs_mc, False)
    rs_bear = rs.register_and_inject_object(
        _WHITE_BEAR_RUST_DICT, 0, ZONE_BATTLEFIELD,
    )
    rs.force_set_summoning_sick(rs_bear, False)

    return py, py_mc, py_bear, rs, rs_mc, rs_bear


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
# Meteor Crater + mono-white Bear, AA[0] picks W (single-element color
# union -> both pickers agree). PROBED tier flip evidence (Cycle 2
# closure marker, scenario MINT -- THE LOAD-BEARING color-union pick).
# ---------------------------------------------------------------------------


@_rust_skip
def test_cross_engine_real_eoe_meteor_crater_mint_scenario_parity():
    """**GENUINE real-EoE cross-engine probe -- Scenario MINT.** PROBED
    tier flip evidence (Cycle 2 closure marker, scenario MINT -- THE
    LOAD-BEARING color-union pick).

    Pre-state on both engines:
      * Meteor Crater on p0's bf (untapped, not summoning-sick).
      * One mono-white Bear on p0's bf (not summoning-sick) -- the
        SOLE colored permanent -> color union = {"W"} on both engines.
      * NO other permanents on either side, empty mana pool on both
        engines.

    Drive: activate Meteor Crater's AA[0] directly via ``apply_action``
    on both engines. The dispatch arm pays the ``tap_self`` cost (taps
    Meteor Crater), walks the source-controller's bf, builds the color
    union ({"W"}), and mints 1 W coin -- both engines deterministically
    pick "W" on a single-element union regardless of the picker.

    Post-resolve (both engines, byte-equal):
      * p0's mana pool has exactly 1 W coin.
      * Stack empty on both engines (mana-ability bypass-stack).
      * Meteor Crater is tapped on both engines.
      * The Bear stays untapped on both engines.
      * p1's mana pool untouched (empty).
    """
    # Real-EoE-signal discipline: bind the genuine parsed printing
    # inside the *_parity body so the measure-pool-parity classifier
    # credits THIS slug to the probe (the canonical idiom the sibling
    # per-card probes use).
    mc_printing = _PRINTINGS.get("Meteor Crater")
    if mc_printing is None:
        pytest.skip("Meteor Crater absent from active CardSource")

    py, py_mc, py_bear, rs, rs_mc, rs_bear = (
        _seat_meteor_crater_with_white_bear()
    )

    # ---- Pre-state pins.
    assert _py_mana_pool_counts(py, 0) == _EMPTY_MANA_POOL
    assert rs.mana_pool_snapshot(0) == _EMPTY_MANA_POOL
    assert py_mc.tapped is False
    assert rs.is_tapped(rs_mc) is False
    assert py_bear.tapped is False
    assert rs.is_tapped(rs_bear) is False

    # ---- Drive AA[0] activation on both engines.
    from mtg_bot.actions import ActivateAbility, apply_action

    apply_action(
        py, 0, ActivateAbility(source_id=py_mc.id, ability_index=0),
    )
    rs.apply_action(
        {
            "kind": "activate_ability",
            "source_id": rs_mc,
            "ability_index": 0,
        }
    )

    # ---- Post-resolve observables: 1 W coin on both engines.
    expected_pool = dict(_EMPTY_MANA_POOL, W=1)
    py_pool = _py_mana_pool_counts(py, 0)
    rs_pool = rs.mana_pool_snapshot(0)
    assert py_pool == expected_pool, (
        f"Python: Meteor Crater AA[0] must mint 1 W coin from "
        f"single-element color union {{'W'}}; got py_pool={py_pool}"
    )
    assert rs_pool == expected_pool, (
        f"Rust: Meteor Crater AA[0] must mint 1 W coin from single-"
        f"element color union {{'W'}}; got rs_pool={rs_pool}"
    )
    assert py_pool == rs_pool, (
        f"Cross-engine byte-equal (1-W-coin mint pool): py_pool={py_pool}, "
        f"rs_pool={rs_pool}"
    )

    # ---- Stack empty on both engines (mana-ability bypass-stack).
    assert len(py.stack) == 0, (
        "Python: mana-ability bypass-stack -- stack must be empty"
    )
    assert rs.stack_size() == 0, (
        "Rust: mana-ability bypass-stack -- stack must be empty"
    )

    # ---- Meteor Crater is tapped on both engines (tap_self cost paid).
    assert py_mc.tapped is True, (
        "Python: tap_self cost must tap Meteor Crater"
    )
    assert rs.is_tapped(rs_mc) is True, (
        "Rust: tap_self cost must tap Meteor Crater"
    )

    # ---- The Bear stays untapped on both engines (it's just a color-
    # union contributor; it's never activated or paid).
    assert py_bear.tapped is False, (
        "Python: the Bear must stay untapped (it's a color-union "
        "contributor, not an activated ability source)"
    )
    assert rs.is_tapped(rs_bear) is False, (
        "Rust: the Bear must stay untapped"
    )

    # ---- p1's pool untouched (the source-controller-scoping invariant
    # — coins must go to p0 only).
    py_pool_p1 = _py_mana_pool_counts(py, 1)
    rs_pool_p1 = rs.mana_pool_snapshot(1)
    assert py_pool_p1 == _EMPTY_MANA_POOL, (
        f"Python: p1's pool must stay empty (source-controller-"
        f"scoping); got py_pool_p1={py_pool_p1}"
    )
    assert rs_pool_p1 == _EMPTY_MANA_POOL, (
        f"Rust: p1's pool must stay empty (source-controller-scoping); "
        f"got rs_pool_p1={rs_pool_p1}"
    )


# ---------------------------------------------------------------------------
# (6) GENUINE real-EoE cross-engine byte-equal probe -- Scenario
# MINT+PAY: Meteor Crater mints 1 W coin, then a {W} Instant is cast
# using the minted W coin. PROBED tier flip evidence (Cycle 2 closure
# marker, scenario MINT+PAY -- THE LOAD-BEARING end-to-end pay-from-
# mint).
# ---------------------------------------------------------------------------


@_rust_skip
def test_cross_engine_real_eoe_meteor_crater_mint_then_pay_byte_equal():
    """**GENUINE real-EoE cross-engine probe -- Scenario MINT+PAY.**
    PROBED tier flip evidence (Cycle 2 closure marker, scenario
    MINT+PAY -- THE LOAD-BEARING end-to-end pay-from-mint pin).

    Drives the **ACTUAL parsed Meteor Crater printing** through a full
    mint -> pay sequence on BOTH engines and asserts byte-equality on
    the post-pay ManaPool snapshot at each step:

      1. Empty starting pool -- 7-key snapshot all-zero on both sides.
      2. Resolve Meteor Crater's AA[0] (mint one W coin from the bf
         color union of {"W"}) on Python via the actions dispatch;
         ``apply_action`` on Rust -- both pools show ``W=1``, all
         other slots 0.
      3. Pay {W} from the minted coin -- Python pops the W coin
         (mirrors ``actions._consume_for_color`` / ``auto_tap_for_
         cost``); Rust casts a {W} Instant via ``cast_spell_non
         creature``, which routes through ``auto_tap_pay_for_cost``.
         Both pools fully drain.

    **Bridge arms exercised:**
      * ``add_one_mana_of_chosen_permanent_color`` (mint, Cycle 1
        substrate at ``eb059eaa``).
      * ``activate_ability`` (Meteor Crater's AA[0] dispatch).
      * Python ``AddOneManaOfChosenPermanentColor.resolve`` (the bf
        walk + sorted-alphabetic single-element pick).
      * Rust ``state_ops_resolve.rs::apply_effect`` arm for
        ``AddOneManaOfChosenPermanentColor`` (the bf walk + WUBRG-
        canonical-first single-element pick).
      * Rust ``GameState.cast_spell_noncreature`` ->
        ``auto_tap_pay_for_cost`` (the {W} PAY path).

    **Observables asserted at each step:**
      * Step-1 snapshot byte-equality (empty pool, 7 zeros on both).
      * Step-2 snapshot byte-equality (post-mint: ``W=1`` only).
      * Step-3 snapshot byte-equality (post-pay: fully empty).
    """
    mc_printing = _PRINTINGS.get("Meteor Crater")
    if mc_printing is None:
        pytest.skip("Meteor Crater absent from active CardSource")

    py, py_mc, py_bear, rs, rs_mc, rs_bear = (
        _seat_meteor_crater_with_white_bear()
    )

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

    # ---- Step 2: Mint.  Activate Meteor Crater's AA[0] on both engines.
    from mtg_bot.actions import ActivateAbility, apply_action

    apply_action(
        py, 0, ActivateAbility(source_id=py_mc.id, ability_index=0),
    )
    rs.apply_action(
        {
            "kind": "activate_ability",
            "source_id": rs_mc,
            "ability_index": 0,
        }
    )

    expected_post_mint = dict(_EMPTY_MANA_POOL, W=1)
    py_pool_post_mint = _py_mana_pool_counts(py, 0)
    rs_pool_post_mint = rs.mana_pool_snapshot(0)
    assert py_pool_post_mint == expected_post_mint, (
        f"Step-2 Python post-mint pool must reflect a single W coin; "
        f"got {py_pool_post_mint}"
    )
    assert rs_pool_post_mint == expected_post_mint, (
        f"Step-2 Rust post-mint pool must reflect a single W coin; "
        f"got {rs_pool_post_mint}"
    )
    assert py_pool_post_mint == rs_pool_post_mint, (
        f"Step-2 post-mint snapshot must be byte-equal cross-engine; "
        f"python={py_pool_post_mint}, rust={rs_pool_post_mint}"
    )

    # ---- Step 3: Pay {W}.  Python: pop the W coin from p0's pool
    # (mirrors the spend by ``actions._consume_for_color`` /
    # ``auto_tap_for_cost``).  Rust: cast a {W} Instant via
    # ``cast_spell_noncreature``, which routes through
    # ``auto_tap_pay_for_cost``.

    # Python: pop the coin.
    from mtg_bot.actions import _coin_matches_color
    py_coin = py.players[0].mana_pool[0]
    assert _coin_matches_color(py_coin, "W"), (
        "Python ``_coin_matches_color`` must return True for the "
        "minted W coin against the {W} requirement"
    )
    py.players[0].mana_pool.pop(0)

    # Rust: register the white instant + library fodder, then cast it.
    rs.register_and_inject_object(
        {
            "name": "MeteorCraterTestLibFiller",
            "card_types": ["Land"],
            "supertypes": ["Basic"],
        },
        0,
        ZONE_LIBRARY,
    )
    spell_id = rs.register_and_inject_object(
        _WHITE_INSTANT_RUST_DICT, 0, ZONE_HAND,
    )
    ok = rs.cast_spell_noncreature(spell_id, 0)
    assert ok, (
        "Rust ``cast_spell_noncreature`` must accept the minted W coin "
        "as payment for the {W} requirement via "
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

    # p1's pool untouched throughout (source-controller-scoping
    # invariant + the {W} spell is cast by p0 only).
    assert _py_mana_pool_counts(py, 1) == _EMPTY_MANA_POOL
    assert rs.mana_pool_snapshot(1) == _EMPTY_MANA_POOL
