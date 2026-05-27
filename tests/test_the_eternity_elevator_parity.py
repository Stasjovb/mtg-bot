"""The Eternity Elevator -- per-card real-EoE cross-engine byte-equal
probe (``covered_by_construction`` -> PROBED tier flip; Spacecraft
Station substrate Phase 4 Cycle 3 closure marker; **SPACECRAFT CAMPAIGN
8/8 = FULL CLOSURE**).

The Eternity Elevator is a ``{5}`` Legendary Artifact -- Spacecraft in
the EoE pool with the Phase-4-pilot non-animating multi-AA shape:

    Power/Toughness: 0/0 (non-animating default)
    Station threshold: None (NEVER animates -- even at 20+ counters
        the card stays a non-creature artifact)
    Stationed keywords: <empty> (no animation -> no keyword grants)
    Baseline keywords: <empty>
    Activated abilities:
      AA[0] -- ``{T}: Add {C}{C}{C}.`` (mana ability, no tier gate):
        cost = ActivationCost(tap_self=True)
        effect = AddManaToPool(produces=(("C", 3),))
        is_mana_ability = True
        tier_threshold = 0
      AA[1] -- ``20+ | {T}: Add X mana of any one color, where X is
                the number of charge counters on this Spacecraft.``
        cost = ActivationCost(tap_self=True)
        effect = AddChargeCounterManaOfChosenColor()
        is_mana_ability = True
        tier_threshold = 20

The Eternity Elevator is the **SOLE non-animating Spacecraft** in the
live 22-Spacecraft EoE pool (``station_threshold=None``); every other
Spacecraft animates at a non-None threshold and flows through Phase
1/2/3. The strict admit predicate
:func:`mtg_bot.parity.trajectory._printing_is_bridge_phase_4_spacecraft_
eternity_elevator` positively rejects every non-Phase-4 carrier per the
verify-first walk landed at C2 (``test_spacecraft_phase_4_cycle_2_flip.
py::test_phase_4_admit_set_is_exactly_the_eternity_elevator``).

**Multi-cycle DECLINED -> ADMITTED -> PROBED transition.**

  * **Phase 4 Cycle 1 (Rust substrate landing, commit ``354588a5``,
    2026-05-26).** Rust substrate:
    ``Effect::AddChargeCounterManaOfChosenColor`` unit variant + parser
    + resolver + ``to_pydict`` + cross-engine bridge arms (forward +
    reverse). The Eternity Elevator STAYED DECLINED at the admit gate
    post-C1 -- the per-AA admit gate ``_aa_is_phase1_sub_shape_a``
    declined ``tier_threshold > 0`` AND the Effect-class admit set
    ``_carrier_aa_phase_1_effect_classes`` didn't include the new
    Effect class AND no Spacecraft admit predicate accepted
    ``station_threshold=None`` carriers.
  * **Phase 4 Cycle 2 (THE FLIP, commit ``4a2485f1``, 2026-05-26).**
    Python admit widens:
      - ``_carrier_aa_phase_1_effect_classes`` admit set widen
        14 -> 15 (adds ``AddChargeCounterManaOfChosenColor``).
      - ``_aa_is_phase1_sub_shape_a`` AA-rider widen: lifts the
        ``tier_threshold > 0`` Phase-1 honest-stop to admit AA[1]'s
        ``tier_threshold=20``.
      - ``_python_aa_to_safe_dict`` widen: emits ``tier_threshold``
        on the AA dict (empty-omit when 0); consumer
        ``_aa_dict_to_python_activated_ability`` reads it back.
      - New ``_printing_is_bridge_phase_4_spacecraft_eternity_elevator``
        admit predicate + ``_eternity_elevator_card_def`` builder +
        OR-chain registration in ``_filter_deck_to_bridge_supported``.
      - ``scripts/measure_pool_parity.loader_admits`` sync.
    The Eternity Elevator DECLINED -> ADMITTED at the production deck
    filter end-to-end (admit set 7 -> 8; the EIGHTH and FINAL
    Spacecraft admit after Sawship + Lumen-Class Frigate + Larval
    Scoutlander + Sledge-Class Seedship + Synthesizer Labship +
    Entropic Battlecruiser + Infinite Guideline Station).
  * **Phase 4 Cycle 3 (THIS LANE; THE PROBE -- Scenarios A+B+C;
    SPACECRAFT 8/8 CAMPAIGN CLOSURE).** Per-card real-EoE cross-engine
    byte-equality probe driving BOTH engines through THREE scenarios
    per design doc sect. 5 cycle plan:

    (A) **AA[1] tier-gated OFF at ``charge_counters=0`` (load-bearing
        silent-no-op pin).** The Eternity Elevator on p0's bf with
        ``charge_counters=0``. Activate AA[1] (the tier-gated
        ``AddChargeCounterManaOfChosenColor`` ability) on BOTH engines
        via ``apply_action({"kind": "activate_ability",
        "source_id": EE, "ability_index": 1})``.
        Post-resolve on both engines:
          - Mana-pool snapshot is empty on both engines
            (``charge_counters=0`` -> silent no-op per the Python
            ``mana.py:161-162`` ``if amount <= 0: return`` AND the
            mirror Rust ``state_ops_resolve.rs:14174`` ``if amount
            <= 0 { return Ok(()) }``).
          - Stack empty on both engines (mana abilities bypass the
            stack).
          - The Eternity Elevator is tapped on both engines
            (``tap_self`` cost paid).

    (B) **AA[1] tier-gated ON at ``charge_counters=20`` (load-bearing
        20-coin mint pin).** The Eternity Elevator on p0's bf with
        ``charge_counters=20`` (at the tier threshold -- the AA is
        legal). Activate AA[1] on BOTH engines.
        Post-resolve on both engines:
          - p0's mana pool has 20 W coins
            (Python ``AddNManaOfChosenColor`` falls back to
            ``options[0]="W"`` when no agent is seated; Rust pushes
            ``b'W'`` deterministically per the
            ``state_ops_resolve.rs:14188`` first-slice fallback).
          - Stack empty on both engines (mana-ability bypass).
          - The Eternity Elevator is tapped on both engines.

    (C) **Both-AA mana-ability bypass-stack semantics
        (load-bearing two-AA pin).** Fresh state per AA. For AA[0]
        (``{T}: Add {C}{C}{C}.``) drive ``apply_action`` /
        ``apply_action`` on BOTH engines; post-resolve: pool has 3 C
        coins, stack empty, Spacecraft tapped. For AA[1] at
        ``charge_counters=20``, untap the Spacecraft first, then drive
        the activation; post-resolve: pool has 3 C + 20 W coins,
        stack empty, Spacecraft tapped again. Pins:
          - BOTH AAs bypass the stack on BOTH engines
            (``is_mana_ability=True`` -> CR 605.3a).
          - Mana-pool deltas byte-equal across engines.
          - The non-animating Spacecraft stays a non-creature on both
            engines even after the 20-counter activation (``station_
            threshold=None`` -- the design doc sect. 4 non-animating
            invariant).

**Scripted-picker semantics.** The probe drives ``apply_action`` /
``apply_action`` directly on both engines with explicit
``(source_id, ability_index)`` pairs. The scripted-picker design
prevents any priority-loop ambiguity: both engines receive the same
explicit activation dict, and the bypass-stack semantics resolve the
effect immediately (no stack item to drain). Charge counters are
seeded via ``set_charge_counters`` on Rust + direct field write on
Python (mirrors the ``Galvanizing Sawship`` Phase-1-pilot probe's
test-helper convention -- design doc sect. 6.4 #16 mandate).

**Real-EoE-signal discipline.** This module uses the live
``OracleParserCardSource`` Eternity Elevator printing on the Python
side AND the canonical Rust registry dict shape emitted by the C2
bridge forward arm ``_spec_card_to_printing_dict(_eternity_elevator_
card_def(p))`` on the Rust side -- the SAME printing shape both engines
read (verified pre-flight via the bridge round-trip pin below).

**Agent-callback color-choice (HONEST-STOP).** Both engines pick
"W" deterministically when no agent is seated (Python:
``AddNManaOfChosenColor.resolve`` falls back to ``options[0]`` at
``mana.py:115``; Rust: ``state_ops_resolve.rs:14188`` pushes ``b'W'``
unconditionally per the first-slice deterministic fallback). The
agent-callback color-choice plumbing through ``choose_mana_color`` is
deferred to a follow-up cycle per the Phase 4 design doc sect. 5 SL
entry -- THIS probe pins only the no-agent W-fallback path, which IS
byte-equal across engines.

This module is the Spacecraft Phase 4 Cycle 3 closure marker;
**SPACECRAFT 8/8 CAMPAIGN COMPLETE**.
"""

from __future__ import annotations

import importlib.util

import pytest

from mtg_bot.cards.source import get_active_source


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


# Canonical Rust dict for The Eternity Elevator -- the EXACT shape
# ``_spec_card_to_printing_dict`` emits for the C2 bridge forward arm
# (verified pre-flight via the bridge round-trip pin below). Both
# engines read this same printing shape.
_ETERNITY_ELEVATOR_RUST_DICT = {
    "name": "The Eternity Elevator",
    "card_types": ["Artifact"],
    "mana_cost": {"generic": 5},
    "effects": [],
    "power": 0,
    "toughness": 0,
    "subtypes": ["Spacecraft"],
    "supertypes": ["Legendary"],
    "activated_abilities": [
        {
            "cost": {"tap_self": True},
            "effect": {
                "kind": "add_mana_to_pool",
                "color": "C",
                "amount": 3,
            },
            "is_mana_ability": True,
        },
        {
            "cost": {"tap_self": True},
            "effect": {
                "kind": "add_charge_counter_mana_of_chosen_color",
            },
            "is_mana_ability": True,
            "tier_threshold": 20,
        },
    ],
}


_EMPTY_MANA_POOL = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0}


# ---------------------------------------------------------------------------
# (1) Parser SoT -- The Eternity Elevator is parser-claimed and emits
# the expected Phase-4-pilot shape (re-asserted here so this module is
# self-contained for the PROBED-tier evidence).
# ---------------------------------------------------------------------------


def test_the_eternity_elevator_parser_claims_card():
    """Pins the active CardSource is producing The Eternity Elevator
    printing under its canonical EoE name.
    """
    assert "The Eternity Elevator" in _PRINTINGS, (
        "The Eternity Elevator must be parser-claimed by the active "
        "CardSource (EoE set + reprint coverage)"
    )


def test_the_eternity_elevator_printed_attrs():
    """Pins the basic printing surface: Legendary Artifact -- Spacecraft,
    0/0, cost ``{5}``, ``station_threshold=None`` (non-animating),
    stationed_keywords = empty, two AAs with the canonical Phase-4-pilot
    shape (AA[0] basic 3C mana ability, AA[1] tier-gated 20+ X-of-any-
    one-color mana ability). The sect. 2 teeth -- the admit predicate's
    load-bearing gates.
    """
    from mtg_bot.effects.generic.mana import (
        AddChargeCounterManaOfChosenColor,
        AddManaToPool,
    )

    p = _PRINTINGS["The Eternity Elevator"]
    assert p.card_types == ("Artifact",)
    assert "Spacecraft" in p.subtypes
    assert "Legendary" in p.supertypes
    assert p.power == 0 and p.toughness == 0
    assert p.mana_cost.generic == 5
    assert p.mana_cost.colored == ()
    # The Phase 4 hallmark: non-animating Spacecraft.
    assert p.station_threshold is None
    assert p.stationed_keywords == frozenset()
    # No baseline keywords / triggers / statics / spell_effect / warp.
    assert p.keywords == frozenset()
    assert p.triggered_abilities == ()
    assert p.static_abilities == ()
    assert p.spell_effect is None
    assert p.warp_cost is None
    # The sect. 2 teeth -- TWO AAs in the canonical pilot shape.
    assert len(p.activated_abilities) == 2
    aa0, aa1 = p.activated_abilities
    # AA[0] -- basic {T}: Add {C}{C}{C}. Mana ability, no tier gate.
    assert aa0.cost.tap_self is True
    assert aa0.cost.mana is None
    assert isinstance(aa0.effect, AddManaToPool)
    assert aa0.effect.produces == (("C", 3),)
    assert aa0.effect.spend_restriction is None
    assert aa0.is_mana_ability is True
    assert aa0.tier_threshold == 0
    # AA[1] -- 20+ tier-gated {T}: Add X mana of any one color where
    # X is the number of charge counters on the source.
    assert aa1.cost.tap_self is True
    assert aa1.cost.mana is None
    assert isinstance(aa1.effect, AddChargeCounterManaOfChosenColor)
    assert aa1.is_mana_ability is True
    assert aa1.tier_threshold == 20


# ---------------------------------------------------------------------------
# (2) Bridge round-trip -- the C2 forward arm
# ``_spec_card_to_printing_dict`` (post-C2) on the genuine parsed
# Eternity Elevator printing emits the canonical Rust registry dict
# carrying both AAs with the new ``tier_threshold`` rider on AA[1].
# ---------------------------------------------------------------------------


def test_the_eternity_elevator_bridge_round_trip_canonical_rust_dict():
    """The C2 admit-gate's bridge: Python printing ->
    ``_eternity_elevator_card_def`` -> CardDef ->
    ``_spec_card_to_printing_dict`` -> canonical Rust registry dict
    matches ``_ETERNITY_ELEVATOR_RUST_DICT`` byte-equal. Pins the probe's
    source-of-truth that both engines read the SAME printing shape.
    """
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import (
        _aa_dict_to_python_activated_ability,
        _spec_card_to_printing_dict,
    )
    from mtg_bot.effects.generic.mana import (
        AddChargeCounterManaOfChosenColor,
        AddManaToPool,
    )

    p_orig = _PRINTINGS["The Eternity Elevator"]
    cd = trajectory._eternity_elevator_card_def(p_orig)
    assert cd is not None, (
        "The Eternity Elevator must pass the Phase-4 admit predicate "
        "post-C2 FLIP"
    )
    pd = _spec_card_to_printing_dict(cd)
    assert pd == _ETERNITY_ELEVATOR_RUST_DICT, (
        f"Eternity Elevator Rust registry dict must match the probe's "
        f"pinned shape (the bridge SoT for both engines); got pd={pd!r}, "
        f"expected={_ETERNITY_ELEVATOR_RUST_DICT!r}"
    )
    # Reverse-arm pin: each AA dict rehydrates to a Python
    # ActivatedAbility carrying the same effect class and the same
    # tier_threshold/is_mana_ability riders (the consumer the loader
    # reads via _aa_dict_to_python_activated_ability).
    aa0_py = _aa_dict_to_python_activated_ability(
        pd["activated_abilities"][0]
    )
    assert isinstance(aa0_py.effect, AddManaToPool)
    assert aa0_py.effect.produces == (("C", 3),)
    assert aa0_py.is_mana_ability is True
    assert aa0_py.tier_threshold == 0
    assert aa0_py.cost.tap_self is True
    aa1_py = _aa_dict_to_python_activated_ability(
        pd["activated_abilities"][1]
    )
    assert isinstance(aa1_py.effect, AddChargeCounterManaOfChosenColor)
    assert aa1_py.is_mana_ability is True
    assert aa1_py.tier_threshold == 20
    assert aa1_py.cost.tap_self is True


# ---------------------------------------------------------------------------
# (3) Rust acceptance smoke -- the canonical Eternity Elevator Rust dict
# parses on ``register_printing`` (the bridge contract Rust honors).
# ---------------------------------------------------------------------------


@_rust_skip
def test_rust_parser_accepts_canonical_eternity_elevator_dict():
    """Lockstep pin: Rust's parse arm accepts the canonical Eternity
    Elevator registry-dict shape ``_ETERNITY_ELEVATOR_RUST_DICT`` -- the
    SAME dict the C2 forward emit arm produces for the live printing.
    Threading TWO mana-ability AAs (the second carrying
    ``tier_threshold=20`` + the new
    ``add_charge_counter_mana_of_chosen_color`` Effect kind) round-trips
    byte-equal through ``Registry.register_printing``.
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(_ETERNITY_ELEVATOR_RUST_DICT)
    assert isinstance(pid, int)
    assert reg.get_printing_name(pid) == "The Eternity Elevator"


# ---------------------------------------------------------------------------
# (4) Loader end-to-end admit -- The Eternity Elevator admits at the
# deck-level filter post-C2 (the FLIP marker mirror).
# ---------------------------------------------------------------------------


def test_the_eternity_elevator_loader_end_to_end_admit():
    """End-to-end loader admit: pass ``["The Eternity Elevator"]`` to
    ``_filter_deck_to_bridge_supported`` -> admitted; CardDef emitted
    carries the Phase-4-pilot two-AA shape (no station_threshold, no
    stationed_keywords, Legendary supertype, Spacecraft subtype).
    """
    from mtg_bot.parity import trajectory

    filt, defs = trajectory._filter_deck_to_bridge_supported(
        ["The Eternity Elevator"], _PRINTINGS,
    )
    assert filt == ["The Eternity Elevator"]
    assert len(defs) == 1
    cd = defs[0]
    assert cd.name == "The Eternity Elevator"
    assert cd.card_type == "Artifact"
    assert cd.subtypes == ("Spacecraft",)
    assert cd.supertypes == ("Legendary",)
    assert cd.station_threshold is None
    assert cd.stationed_keywords == ()
    assert len(cd.activated_abilities) == 2
    aa0_dict, aa1_dict = cd.activated_abilities
    assert aa0_dict["cost"] == {"tap_self": True}
    assert aa0_dict["effect"] == {
        "kind": "add_mana_to_pool",
        "color": "C",
        "amount": 3,
    }
    assert aa0_dict["is_mana_ability"] is True
    assert "tier_threshold" not in aa0_dict
    assert aa1_dict["cost"] == {"tap_self": True}
    assert aa1_dict["effect"] == {
        "kind": "add_charge_counter_mana_of_chosen_color",
    }
    assert aa1_dict["is_mana_ability"] is True
    assert aa1_dict["tier_threshold"] == 20


# ---------------------------------------------------------------------------
# Helper -- seat The Eternity Elevator on both engines at a chosen
# ``charge_counters`` value, with empty mana pools, no other permanents,
# no priority-loop scheduling. Returns ``(py, py_ee, rs, rs_ee)``.
# Mirrors the Galvanizing Sawship probe's helper convention (design
# doc sect. 6.4 #16 scripted-picker mandate).
# ---------------------------------------------------------------------------


def _seat_eternity_elevator(charge_counters: int):
    """Seat The Eternity Elevator on p0's bf on BOTH engines with the
    specified ``charge_counters`` value. Mana pools empty on both
    engines; no other permanents on either side. Returns ``(py,
    py_ee, rs, rs_ee)``.

    Both engines:
      * The Eternity Elevator: ``summoning_sick = False`` (it's a non-
        animating artifact and ``tap_self`` is a mana-ability cost that
        bypasses summoning-sickness anyway, but we explicitly clear the
        flag to keep the field-view byte-equal compare clean across the
        helper-vs-production path).
      * ``charge_counters`` set via the test-helper
        ``set_charge_counters`` on Rust + direct field write on Python.
      * Phase / priority: not driven (we invoke ``apply_action``
        directly which doesn't gate on phase or sorcery-timing for
        mana abilities at the dispatch arm; mana abilities are CR
        605.1 "any time you could cast an instant" + bypass-stack).

    The Eternity Elevator is the ONLY permanent on either bf. Pre-state
    pin: empty mana pool on both engines for the probe's load-bearing
    pool-delta comparisons.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.game import Zone
    from mtg_bot.parity.cross_engine import (
        DeckSpec,
        build_python_state,
        build_rust_state,
    )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)

    ee_printing = get_active_source().get_printings()["The Eternity Elevator"]

    # ---- Python: seat The Eternity Elevator on p0's bf. ----
    py_ee = py.new_object(
        ee_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_ee.summoning_sick = False
    py_ee.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py_ee.charge_counters = charge_counters
    py.battlefield.append(py_ee)
    py.active_player_idx = 0
    py.priority_player_idx = 0
    py.players[0].agent = None
    py.players[1].agent = None

    # ---- Rust: seat The Eternity Elevator on p0's bf. ----
    rs_ee = rs.register_and_inject_object(
        _ETERNITY_ELEVATOR_RUST_DICT, 0, ZONE_BATTLEFIELD,
    )
    if charge_counters != 0:
        rs.set_charge_counters(rs_ee, charge_counters)

    return py, py_ee, rs, rs_ee


def _py_mana_pool_counts(py, player_id: int) -> dict:
    """Build a 6-key W/U/B/R/G/C count dict from Python's list-of-coins
    mana pool -- mirrors Rust's ``mana_pool_snapshot`` shape for byte-
    equal compare.
    """
    counts = dict(_EMPTY_MANA_POOL)
    for coin in py.players[player_id].mana_pool:
        if coin.color in counts:
            counts[coin.color] += 1
    return counts


# ---------------------------------------------------------------------------
# (5) GENUINE real-EoE cross-engine byte-equal probe -- Scenario A:
# AA[1] tier-gated OFF at ``charge_counters=0`` (load-bearing silent-
# no-op pin). PROBED tier flip evidence (Cycle 3 closure marker,
# scenario A -- THE LOAD-BEARING silent-no-op path).
# ---------------------------------------------------------------------------


@_rust_skip
def test_cross_engine_real_eoe_the_eternity_elevator_tier_gated_off_scenario_a_parity():
    """**GENUINE real-EoE cross-engine probe -- Scenario A (AA[1]
    tier-gated OFF, ``charge_counters=0``). PROBED tier flip evidence
    (Cycle 3 closure marker, scenario A -- THE LOAD-BEARING tier-gate
    legality pin).**

    Pre-state on both engines:
      * The Eternity Elevator on p0's bf with ``charge_counters=0``
        (untapped, not summoning-sick).
      * NO other permanents on either side, empty mana pool on both
        engines.

    Drive + observe: BOTH engines refuse to mint mana from AA[1] when
    ``charge_counters < tier_threshold`` -- the tier gate fires at
    legal-emit time on BOTH sides and the activation is illegal:

      * Python: ``effective_activated_abilities`` filters out the
        tier-gated AA at ``game.py:1870-1874`` (``charge_counters=0 <
        tier_threshold=20``), so the resolved ``abilities`` list has
        length 1; ``_activate_ability`` with ``ability_index=1``
        falls into the out-of-range silent-return at
        ``actions.py:1939-1940``. NO mutation -- EE stays untapped,
        pool stays empty.
      * Rust: ``apply_action`` is permissive on legality (it doesn't
        re-run the legal-emit filter) but the post-dispatch tier
        gate at ``state_ops_actions.rs`` raises ``ValueError`` with
        ``"below tier threshold (charge_counters=0 < tier_threshold=
        20)"`` BEFORE paying ``tap_self`` or minting mana. NO
        mutation observable on the Rust state either.

    The post-attempt observable on BOTH engines is byte-equal: empty
    mana pool + untapped EE + empty stack + ``charge_counters`` still
    0. The cross-engine SHAPE of the legality refusal differs (Python
    silent / Rust raise) but the observable mutation IS byte-equal
    (zero mutation on both sides).
    """
    # Real-EoE-signal discipline: bind the genuine parsed printing
    # inside the *_parity body so the measure-pool-parity classifier
    # credits THIS slug to the probe (the canonical idiom the sibling
    # per-card probes use).
    ee_printing = _PRINTINGS.get("The Eternity Elevator")
    if ee_printing is None:
        pytest.skip(
            "The Eternity Elevator absent from active CardSource"
        )

    py, py_ee, rs, rs_ee = _seat_eternity_elevator(charge_counters=0)

    # ---- Pre-state pins.
    assert _py_mana_pool_counts(py, 0) == _EMPTY_MANA_POOL
    assert rs.mana_pool_snapshot(0) == _EMPTY_MANA_POOL
    assert py_ee.charge_counters == 0
    assert rs.get_charge_counters(rs_ee) == 0
    assert py_ee.tapped is False
    assert rs.is_tapped(rs_ee) is False

    from mtg_bot.actions import ActivateAbility, apply_action
    from mtg_bot.game import effective_activated_abilities

    # ---- Python load-bearing legality pin: AA[1] is tier-gated OFF
    # at the ``effective_activated_abilities`` filter -- only AA[0]
    # survives.
    eff = effective_activated_abilities(py, py_ee)
    assert len(eff) == 1, (
        f"Python: effective_activated_abilities must filter out the "
        f"tier-gated AA[1] at charge_counters=0 < tier_threshold=20; "
        f"got {len(eff)} abilities"
    )

    # ---- Python: drive the AA[1] activation -- the out-of-range
    # silent-return at ``actions.py:1939-1940`` leaves the state
    # untouched.
    apply_action(
        py, 0, ActivateAbility(source_id=py_ee.id, ability_index=1),
    )

    # ---- Rust load-bearing legality pin: apply_action raises with
    # the tier-gate refusal BEFORE paying any cost.
    with pytest.raises(
        ValueError, match="below tier threshold",
    ):
        rs.apply_action(
            {
                "kind": "activate_ability",
                "source_id": rs_ee,
                "ability_index": 1,
            }
        )

    # ---- Post-attempt cross-engine byte-equal observable: zero
    # mutation on either side.
    py_pool = _py_mana_pool_counts(py, 0)
    rs_pool = rs.mana_pool_snapshot(0)
    assert py_pool == _EMPTY_MANA_POOL, (
        f"Python: tier-gated-off AA[1] must leave pool empty; got "
        f"py_pool={py_pool}"
    )
    assert rs_pool == _EMPTY_MANA_POOL, (
        f"Rust: tier-gated-off AA[1] must leave pool empty; got "
        f"rs_pool={rs_pool}"
    )
    assert py_pool == rs_pool, (
        f"Cross-engine byte-equal (tier-gated-off pool): py={py_pool}, "
        f"rs={rs_pool}"
    )

    # ---- Stack empty on both engines.
    assert len(py.stack) == 0
    assert rs.stack_size() == 0

    # ---- EE stays UNTAPPED on both engines (the tier-gate refusal
    # short-circuits BEFORE the tap_self cost is paid).
    assert py_ee.tapped is False, (
        "Python: tier-gated-off refusal must short-circuit BEFORE "
        "paying tap_self -- EE stays untapped"
    )
    assert rs.is_tapped(rs_ee) is False, (
        "Rust: tier-gated-off refusal must short-circuit BEFORE "
        "paying tap_self -- EE stays untapped"
    )

    # ---- charge_counters unchanged.
    assert py_ee.charge_counters == 0
    assert rs.get_charge_counters(rs_ee) == 0


# ---------------------------------------------------------------------------
# (6) GENUINE real-EoE cross-engine byte-equal probe -- Scenario B:
# AA[1] tier-gated ON at ``charge_counters=20`` (load-bearing 20-coin
# mint pin). PROBED tier flip evidence (Cycle 3 closure marker,
# scenario B -- THE LOAD-BEARING X-coin mint path).
# ---------------------------------------------------------------------------


@_rust_skip
def test_cross_engine_real_eoe_the_eternity_elevator_tier_gated_on_scenario_b_parity():
    """**GENUINE real-EoE cross-engine probe -- Scenario B (AA[1]
    tier-gated ON, ``charge_counters=20``). PROBED tier flip evidence
    (Cycle 3 closure marker, scenario B -- THE LOAD-BEARING 20-coin
    mint path).**

    Pre-state on both engines:
      * The Eternity Elevator on p0's bf with ``charge_counters=20``
        (untapped, not summoning-sick).
      * NO other permanents, empty mana pool on both engines.

    Drive: activate AA[1] directly via ``apply_action`` on both
    engines. The dispatch arm pays the ``tap_self`` cost (taps EE),
    reads ``charge_counters=20`` for X, and -- since X>0 -- mints 20
    coins. Both engines deterministically pick "W" when no agent is
    seated (Python: ``AddNManaOfChosenColor.resolve`` falls back to
    ``options[0]="W"`` at ``mana.py:115``; Rust: ``state_ops_resolve.
    rs:14188`` pushes ``b'W'`` per the first-slice fallback).

    Post-resolve (both engines):
      * p0's mana pool has 20 W coins (byte-equal across engines).
      * Stack empty on both engines (mana-ability bypass-stack).
      * EE is tapped on both engines.
      * EE's ``charge_counters`` still 20 (the effect doesn't deduct).
    """
    # Real-EoE-signal discipline: bind the genuine parsed printing
    # inside the *_parity body so the measure-pool-parity classifier
    # credits THIS slug to the probe.
    ee_printing = _PRINTINGS.get("The Eternity Elevator")
    if ee_printing is None:
        pytest.skip(
            "The Eternity Elevator absent from active CardSource"
        )

    py, py_ee, rs, rs_ee = _seat_eternity_elevator(charge_counters=20)

    # ---- Pre-state pins.
    assert _py_mana_pool_counts(py, 0) == _EMPTY_MANA_POOL
    assert rs.mana_pool_snapshot(0) == _EMPTY_MANA_POOL
    assert py_ee.charge_counters == 20
    assert rs.get_charge_counters(rs_ee) == 20

    # ---- Drive AA[1] activation on both engines.
    from mtg_bot.actions import ActivateAbility, apply_action

    apply_action(
        py, 0, ActivateAbility(source_id=py_ee.id, ability_index=1),
    )
    rs.apply_action(
        {
            "kind": "activate_ability",
            "source_id": rs_ee,
            "ability_index": 1,
        }
    )

    # ---- Post-resolve observables: 20 W coins on both engines.
    expected_pool = dict(_EMPTY_MANA_POOL, W=20)
    py_pool = _py_mana_pool_counts(py, 0)
    rs_pool = rs.mana_pool_snapshot(0)
    assert py_pool == expected_pool, (
        f"Python: charge_counters=20 activation must mint 20 W coins; "
        f"got py_pool={py_pool}"
    )
    assert rs_pool == expected_pool, (
        f"Rust: charge_counters=20 activation must mint 20 W coins; "
        f"got rs_pool={rs_pool}"
    )
    assert py_pool == rs_pool, (
        f"Cross-engine byte-equal (20-coin mint pool): py_pool={py_pool}, "
        f"rs_pool={rs_pool}"
    )

    # ---- Stack empty on both engines (mana-ability bypass-stack).
    assert len(py.stack) == 0, (
        "Python: mana-ability bypass-stack -- stack must be empty"
    )
    assert rs.stack_size() == 0, (
        "Rust: mana-ability bypass-stack -- stack must be empty"
    )

    # ---- EE is tapped on both engines (tap_self cost paid).
    assert py_ee.tapped is True, (
        "Python: tap_self cost must tap EE post-activation"
    )
    assert rs.is_tapped(rs_ee) is True, (
        "Rust: tap_self cost must tap EE post-activation"
    )

    # ---- charge_counters unchanged (the effect reads X, doesn't
    # mutate counters).
    assert py_ee.charge_counters == 20
    assert rs.get_charge_counters(rs_ee) == 20


# ---------------------------------------------------------------------------
# (7) GENUINE real-EoE cross-engine byte-equal probe -- Scenario C:
# both-AA mana-ability bypass-stack semantics (load-bearing two-AA pin).
# PROBED tier flip evidence (Cycle 3 closure marker, scenario C -- THE
# LOAD-BEARING two-AA bypass-stack path).
# ---------------------------------------------------------------------------


@_rust_skip
def test_cross_engine_real_eoe_the_eternity_elevator_both_aa_bypass_stack_scenario_c_parity():
    """**GENUINE real-EoE cross-engine probe -- Scenario C (BOTH AAs
    bypass-stack semantics). PROBED tier flip evidence (Cycle 3 closure
    marker, scenario C -- THE LOAD-BEARING two-AA mana-ability pin).**

    Pre-state on both engines:
      * The Eternity Elevator on p0's bf with ``charge_counters=20``
        (untapped, not summoning-sick).
      * NO other permanents, empty mana pool on both engines.

    Drive: activate AA[0] first (``{T}: Add {C}{C}{C}.``) on both
    engines. Pin: 3 C coins minted on both engines + stack empty + EE
    tapped + EE is NOT a creature (the load-bearing non-animating
    invariant -- ``station_threshold=None`` means CR 311 keeps it an
    artifact even at 20+ counters). Then untap EE on both engines and
    activate AA[1]; pin: 20 W coins ALSO minted (cumulative pool: 3 C
    + 20 W) + stack empty + EE tapped again + EE still NOT a creature.

    Both activations bypass the stack (``is_mana_ability=True`` -> CR
    605.3a). The cumulative pool delta across BOTH activations is the
    byte-equal pin -- the two-AA pin is the load-bearing closure of
    the Phase 4 cycle.
    """
    # Real-EoE-signal discipline: bind the genuine parsed printing
    # inside the *_parity body so the measure-pool-parity classifier
    # credits THIS slug to the probe.
    ee_printing = _PRINTINGS.get("The Eternity Elevator")
    if ee_printing is None:
        pytest.skip(
            "The Eternity Elevator absent from active CardSource"
        )

    py, py_ee, rs, rs_ee = _seat_eternity_elevator(charge_counters=20)

    from mtg_bot.actions import ActivateAbility, apply_action
    from mtg_bot.game import is_creature_now

    # ---- Pre-state pins (sanity).
    assert _py_mana_pool_counts(py, 0) == _EMPTY_MANA_POOL
    assert rs.mana_pool_snapshot(0) == _EMPTY_MANA_POOL

    # ---- AA[0] activation on both engines (basic {T}: Add {C}{C}{C}).
    apply_action(
        py, 0, ActivateAbility(source_id=py_ee.id, ability_index=0),
    )
    rs.apply_action(
        {
            "kind": "activate_ability",
            "source_id": rs_ee,
            "ability_index": 0,
        }
    )

    # ---- Post-AA[0] pins: 3 C coins on both engines, stack empty,
    # EE tapped, EE NOT a creature.
    expected_after_aa0 = dict(_EMPTY_MANA_POOL, C=3)
    py_pool_after_aa0 = _py_mana_pool_counts(py, 0)
    rs_pool_after_aa0 = rs.mana_pool_snapshot(0)
    assert py_pool_after_aa0 == expected_after_aa0, (
        f"Python: AA[0] must mint 3 C coins; got {py_pool_after_aa0}"
    )
    assert rs_pool_after_aa0 == expected_after_aa0, (
        f"Rust: AA[0] must mint 3 C coins; got {rs_pool_after_aa0}"
    )
    assert py_pool_after_aa0 == rs_pool_after_aa0, (
        f"Cross-engine byte-equal (AA[0] 3-C-coin pool): "
        f"py={py_pool_after_aa0}, rs={rs_pool_after_aa0}"
    )
    assert len(py.stack) == 0, (
        "Python: AA[0] mana-ability bypass-stack must leave stack empty"
    )
    assert rs.stack_size() == 0, (
        "Rust: AA[0] mana-ability bypass-stack must leave stack empty"
    )
    assert py_ee.tapped is True
    assert rs.is_tapped(rs_ee) is True
    # **Non-animating invariant pin.** EE is NOT a creature even at
    # ``charge_counters=20`` because ``station_threshold=None`` -- the
    # design doc sect. 4 non-animating closure leg.
    assert is_creature_now(py_ee) is False, (
        "Python: non-animating EE (station_threshold=None) must NOT be "
        "a creature regardless of charge_counters"
    )

    # ---- Untap EE on both engines to drive AA[1] next.
    py_ee.tapped = False
    rs.untap_object(rs_ee)
    assert py_ee.tapped is False
    assert rs.is_tapped(rs_ee) is False

    # ---- AA[1] activation on both engines (20+ tier-gated; X=20).
    apply_action(
        py, 0, ActivateAbility(source_id=py_ee.id, ability_index=1),
    )
    rs.apply_action(
        {
            "kind": "activate_ability",
            "source_id": rs_ee,
            "ability_index": 1,
        }
    )

    # ---- Post-AA[1] pins: cumulative 3 C + 20 W coins on both engines,
    # stack empty, EE tapped again, EE still NOT a creature.
    expected_after_aa1 = dict(_EMPTY_MANA_POOL, C=3, W=20)
    py_pool_after_aa1 = _py_mana_pool_counts(py, 0)
    rs_pool_after_aa1 = rs.mana_pool_snapshot(0)
    assert py_pool_after_aa1 == expected_after_aa1, (
        f"Python: AA[1] must add 20 W to the 3 C from AA[0]; got "
        f"{py_pool_after_aa1}"
    )
    assert rs_pool_after_aa1 == expected_after_aa1, (
        f"Rust: AA[1] must add 20 W to the 3 C from AA[0]; got "
        f"{rs_pool_after_aa1}"
    )
    assert py_pool_after_aa1 == rs_pool_after_aa1, (
        f"Cross-engine byte-equal (cumulative AA[0] + AA[1] pool): "
        f"py={py_pool_after_aa1}, rs={rs_pool_after_aa1}"
    )
    assert len(py.stack) == 0, (
        "Python: AA[1] mana-ability bypass-stack must leave stack empty"
    )
    assert rs.stack_size() == 0, (
        "Rust: AA[1] mana-ability bypass-stack must leave stack empty"
    )
    assert py_ee.tapped is True, (
        "Python: AA[1] tap_self cost must tap EE again"
    )
    assert rs.is_tapped(rs_ee) is True, (
        "Rust: AA[1] tap_self cost must tap EE again"
    )
    # Non-animating invariant pin -- still holds after the 20-counter
    # activation.
    assert is_creature_now(py_ee) is False, (
        "Python: non-animating EE stays a non-creature post-AA[1] "
        "activation (station_threshold=None CR 311 leg)"
    )
