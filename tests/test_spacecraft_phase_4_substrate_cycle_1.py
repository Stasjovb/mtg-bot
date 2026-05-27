"""**Spacecraft Station substrate Phase 4 Cycle 1 (2026-05-26).**

Tests for the Phase 4 Cycle 1 Rust substrate slice landing per
``docs/SPACECRAFT_STATION_SUBSTRATE_PHASE_4_DESIGN.md`` §3 (Rust spec)
+ §4 (Python bridge spec) + §5 (cycle plan).

Deliverables (Cycle 1 Rust slice, per design doc §3):

  - New Rust ``Effect::AddChargeCounterManaOfChosenColor`` unit-variant
    on ``cards.rs::Effect`` — The Eternity Elevator's AA[1] pilot
    effect (``20+ | {T}: Add X mana of any one color, where X is the
    number of charge counters on The Eternity Elevator.``).
  - ``parse_effect`` arm in ``cards.rs`` —
    ``"add_charge_counter_mana_of_chosen_color"`` 1-key dict (kind
    only; unit variant has no rider fields).
  - ``to_pydict`` arm in ``cards.rs`` — emits the same 1-key dict.
  - Resolve arm in ``state_ops_resolve.rs::apply_effect`` — reads the
    source object's ``charge_counters: i32`` from any zone, on
    ``charge_counters > 0`` mints ``charge_counters`` coins of
    ``options[0]="W"`` via the same ``push_coins`` path
    ``AddNManaOfChosenColor`` uses; on ``charge_counters <= 0`` silent
    no-op. First-slice deterministic color choice mirrors
    ``AddNManaOfChosenColor`` (`state_ops_resolve.rs:14057`).
  - Cross-engine bridge arms in ``src/mtg_bot/parity/cross_engine.py``:
      * Reverse arm in ``_ta_dict_to_python_effect`` — recognizes
        ``kind == "add_charge_counter_mana_of_chosen_color"`` and
        returns the Python ``AddChargeCounterManaOfChosenColor()``
        unit instance.
      * Forward arm in ``_python_aa_to_safe_dict`` — recognizes
        ``isinstance(effect, AddChargeCounterManaOfChosenColor)`` and
        emits the matching 1-key dict.
    Both arms use the SPECIFIC class (no parent ``Effect`` fall-
    through) per the Phase-3A/3B/3C/4B/4C/4D/4E specificity contract.

ZERO Python admit widen this cycle (the
``_carrier_aa_phase_1_effect_classes`` widen + the AA-rider gate widen
for ``tier_threshold > 0`` + the new
``_printing_is_bridge_phase_4_spacecraft_eternity_elevator`` predicate
all ship Cycle 2 per design doc §5).
ZERO per-card probe this cycle (Cycle 3 ships the real-EoE
``tests/test_the_eternity_elevator_parity.py`` per design doc §5).
ZERO new cost-shape Rust machinery — The Eternity Elevator's ``{T}``
(both AAs) rides the existing Phase-1 bare-``{T}`` cost-shape gate.

Substrate-only invariant — The Eternity Elevator STAYS DECLINED at
the admit gate post-Cycle-1. The Rust Effect variant + cross-engine
bridge arms all landed; the live admit gate still declines The
Eternity Elevator's printing because:

  (a) ``_carrier_aa_phase_1_effect_classes`` doesn't yet include
      ``AddChargeCounterManaOfChosenColor``; AND
  (b) the AA-rider gate at ``_aa_is_phase1_sub_shape_a`` still
      declines AA[1]'s ``tier_threshold=20``; AND
  (c) no Spacecraft admit predicate accepts
      ``station_threshold=None`` carriers (Phase 1/2/3 all reject).

ALL THREE widens ship C2. The forward serializer + Rust round-trip
both succeed at C1 — driven by synthetic unit pins; the live admit
FLIP lands at C2.

**Verify-first findings (live tree, main ``818b4c64`` — see design
doc §1 for the full walk):**

  - The Eternity Elevator printing: ``card_types=("Artifact",)``,
    ``supertypes=("Legendary",)``, ``subtypes=("Spacecraft",)``,
    ``mana_cost_str="{5}"``, ``station_threshold=None``,
    ``stationed_keywords=frozenset()``,
    ``keywords=frozenset({"Station"})``, ``n_aa=2``.
  - AA[0]: ``cost=ActivationCost(tap_self=True),
    effect=AddManaToPool(produces=(("C", 3),)),
    is_mana_ability=True, tier_threshold=0``.
  - AA[1]: ``cost=ActivationCost(tap_self=True),
    effect=AddChargeCounterManaOfChosenColor(),
    is_mana_ability=True, tier_threshold=20``.
"""

from __future__ import annotations

import importlib.util

import pytest


# Zone constants — mirror ``rust/src/state_ops_zones.rs``.
ZONE_HAND = 0
ZONE_LIBRARY = 1
ZONE_BATTLEFIELD = 2
ZONE_GRAVEYARD = 3
ZONE_EXILE = 5


def _require_engine():
    if importlib.util.find_spec("mtg_bot_engine") is None:
        pytest.skip("mtg_bot_engine PyO3 extension not installed")


@pytest.fixture
def engine():
    """The ``mtg_bot_engine`` module, or skip if not installed."""
    if importlib.util.find_spec("mtg_bot_engine") is None:
        pytest.skip("mtg_bot_engine PyO3 extension not installed")
    import mtg_bot_engine
    return mtg_bot_engine


@pytest.fixture
def synthetic_state(engine):
    """A default synthetic state — 10 battlefield, 7 hand, 50 library
    per side. Mirrors the Phase-3A/3B/3C/4D/4E sibling shared fixture."""
    return engine.make_synthetic_state()


# ---------------------------------------------------------------------------
# Parser SoT verify-first
# ---------------------------------------------------------------------------


def test_python_add_charge_counter_mana_of_chosen_color_class_exists():
    """**Parser source-of-truth pin.** Python's
    ``AddChargeCounterManaOfChosenColor`` class is in
    ``effects.generic.mana``, a frozen dataclass with NO fields.
    """
    from mtg_bot.effects.base import Effect
    from mtg_bot.effects.generic.mana import (
        AddChargeCounterManaOfChosenColor,
    )

    eff = AddChargeCounterManaOfChosenColor()
    assert isinstance(eff, Effect)
    # Two instances compare equal (frozen dataclass __eq__ default).
    assert eff == AddChargeCounterManaOfChosenColor()


def test_the_eternity_elevator_live_aa_shapes_match_design_doc():
    """**Verify-first pin (design doc §1.2 row).** The live The
    Eternity Elevator parser SoT carries:

      * AA[0]: ``AddManaToPool(produces=(("C", 3),))`` +
        ``is_mana_ability=True`` + ``tier_threshold=0``.
      * AA[1]: ``AddChargeCounterManaOfChosenColor()`` +
        ``is_mana_ability=True`` + ``tier_threshold=20``.

    Plus printing-level shape: ``card_types=("Artifact",)``,
    ``supertypes=("Legendary",)``, ``subtypes=("Spacecraft",)``,
    ``station_threshold is None``, ``stationed_keywords`` empty,
    ``keywords == {"Station"}``.

    This pin protects the verify-first finding the C1 substrate is
    built against: a future parser tweak that mutates either AA's
    shape, the supertype/subtype slot, or the non-animating
    ``station_threshold=None`` invariant would need to be reconciled
    here BEFORE C2 ships the admit widens.
    """
    import json

    from mtg_bot.cards.parser_source import (
        _build_spacecraft_printing as build_spacecraft_printing,
    )
    from mtg_bot.effects.generic.mana import (
        AddChargeCounterManaOfChosenColor,
        AddManaToPool,
    )

    with open("data/edge_of_eternities.json", encoding="utf-8") as f:
        raw_cards = json.load(f)
    raw = next(
        (c for c in raw_cards if c.get("name") == "The Eternity Elevator"),
        None,
    )
    assert raw is not None, (
        "Verify-first invariant: The Eternity Elevator must be present "
        "in data/edge_of_eternities.json"
    )
    printing = build_spacecraft_printing(raw)
    assert printing is not None, (
        "Verify-first invariant: build_spacecraft_printing must accept "
        "The Eternity Elevator"
    )

    # Printing-level shape — non-animating Legendary Artifact Spacecraft.
    assert printing.card_types == ("Artifact",)
    assert printing.supertypes == ("Legendary",)
    assert "Spacecraft" in printing.subtypes
    assert printing.station_threshold is None, (
        "The Eternity Elevator must be non-animating — "
        "station_threshold=None per its lack of printed P/T"
    )
    assert printing.stationed_keywords == frozenset(), (
        "Non-animating Spacecraft must have empty stationed_keywords"
    )
    # The "Station" keyword on the oracle text is encoded via the
    # ``station_threshold`` mechanism + the ``Action::ActivateStation``
    # path, NOT via the printing's ``keywords`` field — confirmed by
    # verify-first walk against the live parser SoT (the parser elides
    # baseline-keyword tracking of the Station ability). The
    # non-animating ``station_threshold=None`` invariant is the real
    # load-bearing identity-tag for this card.
    assert printing.keywords == frozenset(), (
        "The Eternity Elevator's printing.keywords is empty per the "
        "verify-first walk; the Station mechanic rides on "
        "station_threshold + the activate-station action path"
    )
    assert printing.power == 0
    assert printing.toughness == 0

    # Multi-AA shape — 2 AAs, both is_mana_ability=True, AA[1] tier=20.
    assert len(printing.activated_abilities) == 2

    aa0 = printing.activated_abilities[0]
    assert isinstance(aa0.effect, AddManaToPool)
    assert aa0.effect.produces == (("C", 3),)
    assert aa0.is_mana_ability is True
    assert aa0.tier_threshold == 0
    assert aa0.cost.tap_self is True
    assert aa0.cost.mana is None

    aa1 = printing.activated_abilities[1]
    assert isinstance(aa1.effect, AddChargeCounterManaOfChosenColor)
    assert aa1.is_mana_ability is True
    assert aa1.tier_threshold == 20, (
        "The Eternity Elevator's AA[1] is gated by the 20+ charge-"
        "counter tier — the Spacecraft Phase 4 sub-shape keystone"
    )
    assert aa1.cost.tap_self is True
    assert aa1.cost.mana is None


# ---------------------------------------------------------------------------
# Cross-engine bridge arm pins (dict <-> Python)
# ---------------------------------------------------------------------------


def test_bridge_reverse_arm_add_charge_counter_mana_of_chosen_color():
    """Reverse arm constructs ``AddChargeCounterManaOfChosenColor()``
    from the 1-key ``add_charge_counter_mana_of_chosen_color`` dict.
    Mirrors the Phase-3A/3B/3C/4B/4D/4E specificity contract — unit
    variant on the wire, unit dataclass in Python.
    """
    from mtg_bot.effects.generic.mana import (
        AddChargeCounterManaOfChosenColor,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    back = _ta_dict_to_python_effect({
        "kind": "add_charge_counter_mana_of_chosen_color",
    })
    assert isinstance(back, AddChargeCounterManaOfChosenColor)
    # Unit dataclass — two instances compare equal.
    assert back == AddChargeCounterManaOfChosenColor()


def test_bridge_forward_arm_add_charge_counter_mana_of_chosen_color():
    """Forward arm in ``_python_aa_to_safe_dict`` recognizes
    ``AddChargeCounterManaOfChosenColor`` and emits the 1-key dict
    ``{"kind": "add_charge_counter_mana_of_chosen_color"}``.

    The AA carrying this effect must itself pass the bridge-floor
    rider gates — bare ``{T}`` cost, no AA-rider deal-breakers. For
    this Cycle 1 pin we wrap it in a minimum-shape AA (no
    ``tier_threshold``, no ``is_mana_ability``) so the bridge floor
    admits the AA; the C2 widens flip ``tier_threshold > 0`` into the
    admit set, but the per-effect forward arm is exercise-able
    independently.
    """
    from mtg_bot.effects.base import ActivatedAbility, ActivationCost
    from mtg_bot.effects.generic.mana import (
        AddChargeCounterManaOfChosenColor,
    )
    from mtg_bot.parity.cross_engine import _python_aa_to_safe_dict

    aa = ActivatedAbility(
        cost=ActivationCost(tap_self=True),
        effect=AddChargeCounterManaOfChosenColor(),
    )
    d = _python_aa_to_safe_dict(aa)
    assert d is not None
    assert d["effect"] == {
        "kind": "add_charge_counter_mana_of_chosen_color",
    }
    # The cost dict carries only the tap_self flag.
    assert d["cost"] == {"tap_self": True}


def test_bridge_round_trip_add_charge_counter_mana_of_chosen_color():
    """Round-trip pin — Python AA → dict → Python AA yields a byte-
    equal AA at the dataclass ``__eq__`` surface.
    """
    from mtg_bot.effects.base import ActivatedAbility, ActivationCost
    from mtg_bot.effects.generic.mana import (
        AddChargeCounterManaOfChosenColor,
    )
    from mtg_bot.parity.cross_engine import (
        _aa_dict_to_python_activated_ability,
        _python_aa_to_safe_dict,
    )

    aa_orig = ActivatedAbility(
        cost=ActivationCost(tap_self=True),
        effect=AddChargeCounterManaOfChosenColor(),
    )
    d = _python_aa_to_safe_dict(aa_orig)
    assert d is not None
    aa_back = _aa_dict_to_python_activated_ability(d)
    assert aa_back == aa_orig
    # A second forward emit yields a byte-equal dict.
    d2 = _python_aa_to_safe_dict(aa_back)
    assert d == d2


# ---------------------------------------------------------------------------
# Rust unit pin — parse_effect arm via Registry.register_printing
# ---------------------------------------------------------------------------


def _synthetic_elevator_dict():
    """Minimal The-Eternity-Elevator-shape Artifact printing dict for
    the Rust Registry. AA[0] is the basic ``{T}: Add {C}{C}{C}.`` mana
    ability (pre-wired via ``AddManaToPool``); AA[1] is the new
    ``add_charge_counter_mana_of_chosen_color`` shape with
    ``tier_threshold=20``.

    Used by the C1 synthetic-pin path; the live admit gate still
    declines this shape at production (see substrate-only invariant
    pins below).
    """
    return {
        "name": "Synthetic The Eternity Elevator",
        "card_types": ["Artifact"],
        "supertypes": ["Legendary"],
        "subtypes": ["Spacecraft"],
        "mana_cost": {"generic": 5},
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


def test_rust_register_printing_with_add_charge_counter_mana_effect(engine):
    """**Rust parse arm pin.** The new
    ``add_charge_counter_mana_of_chosen_color`` parse arm accepts the
    1-key dict and returns ``Effect::AddChargeCounterManaOfChosenColor``;
    a synthetic Eternity-Elevator-shape Artifact registers cleanly,
    including the multi-AA carriage of the basic mana ability + the
    new tier_threshold-gated AA.
    """
    reg = engine.Registry()
    pid = reg.register_printing(_synthetic_elevator_dict())
    assert reg.get_printing_name(pid) == "Synthetic The Eternity Elevator"


# ---------------------------------------------------------------------------
# Rust unit pin — to_pydict arm via the parse-emit inverse
# ---------------------------------------------------------------------------


def test_rust_to_pydict_round_trip_via_bridge_inverse():
    """**Rust to_pydict arm pin.** The Rust to_pydict arm emits the
    byte-equal 1-key dict. Round-trip via the bridge forward arm
    (Python→dict) + the reverse arm (dict→Python) yields the same
    Python AA.
    """
    from mtg_bot.effects.base import ActivatedAbility, ActivationCost
    from mtg_bot.effects.generic.mana import (
        AddChargeCounterManaOfChosenColor,
    )
    from mtg_bot.parity.cross_engine import (
        _aa_dict_to_python_activated_ability,
        _python_aa_to_safe_dict,
    )

    aa_orig = ActivatedAbility(
        cost=ActivationCost(tap_self=True),
        effect=AddChargeCounterManaOfChosenColor(),
    )
    d = _python_aa_to_safe_dict(aa_orig)
    aa_back = _aa_dict_to_python_activated_ability(d)
    assert aa_back == aa_orig
    # And: a second forward emit yields a byte-equal dict.
    d2 = _python_aa_to_safe_dict(aa_back)
    assert d == d2


# ---------------------------------------------------------------------------
# Rust unit pin — resolve arm: mints `charge_counters` coins of W
# ---------------------------------------------------------------------------


def test_resolve_add_charge_counter_mana_silent_noop_on_zero_counters(
    engine, synthetic_state,
):
    """**Resolve arm pin — silent no-op when charge_counters == 0.**

    Activate AA[0] on a synthetic Eternity-Elevator-shape Spacecraft
    with ``charge_counters=0``. Wait — AA[0] is the basic mana ability
    (Add {C}{C}{C}); use it as the baseline pre-resolve. Then activate
    AA[1] (the new charge-counter mana variant) — with
    ``charge_counters=0``, the resolve arm must NOT mint any coins
    (silent no-op per ``amount <= 0`` guard in
    ``state_ops_resolve.rs::apply_effect`` for the new variant).

    Mirrors Python's ``if amount <= 0: return`` at
    ``effects/generic/mana.py:161-162`` and the
    ``AddNManaOfChosenColor::amount == 0`` short-circuit at
    ``state_ops_resolve.rs:14054-14056``.

    **Note on tier_threshold.** The Rust legal-emit gate
    (``state_ops_legal.rs::legal_decisions`` AA emitter at
    ``state_ops_legal.rs:3328`` per CE20 follow-up Slice 3) hides
    tier_threshold>0 AAs from the legal_actions list when
    ``charge_counters < tier_threshold``. To exercise the resolve arm
    directly without the legal-emit gate, we use the
    ``register_and_inject_object`` + ``apply_action`` path with an
    explicit ``activate_ability`` action targeting the new AA index.
    On a synthetic injected object the tier_threshold gate IS still
    checked at activation time on the apply_action side; for this
    silent-no-op pin we therefore drop tier_threshold on AA[1] to 0
    (substrate-only pin — exercising the resolve arm directly, not
    the tier gate which is data-carrying-only at this slice).
    """
    # Build a printing with tier_threshold=0 on AA[1] so we can
    # activate it at charge_counters=0 (the production tier=20 gate
    # is a separate concern — the legal-emit gate is exercised via
    # Sawship-shape Phase-1 tests).
    dict_with_no_tier_gate = _synthetic_elevator_dict()
    dict_with_no_tier_gate["activated_abilities"][1]["tier_threshold"] = 0
    elevator_id = synthetic_state.register_and_inject_object(
        dict_with_no_tier_gate, 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(elevator_id, False)
    # Pre-resolve: charge_counters=0.
    assert synthetic_state.get_charge_counters(elevator_id) == 0
    # Pre-resolve mana pool is empty (synthetic state default).
    pool_pre = synthetic_state.get_mana_pool(0)
    assert pool_pre == {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0}

    # Activate AA[1] (the charge-counter mana ability).
    # is_mana_ability=True → bypass-stack semantics: the Rust
    # `activate_ability` path dispatches the effect immediately via
    # `apply_effect_pub` rather than pushing onto the stack.
    synthetic_state.apply_action({
        "kind": "activate_ability",
        "source_id": elevator_id,
        "ability_index": 1,
    })

    # Post-resolve: no coins minted (silent no-op on
    # charge_counters=0).
    pool_post = synthetic_state.get_mana_pool(0)
    assert pool_post == {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0}, (
        f"AA[1] at charge_counters=0 must silent-no-op (no coins "
        f"minted); got pool={pool_post}"
    )


def test_resolve_add_charge_counter_mana_mints_w_coins_equal_to_charge_counters(
    engine, synthetic_state,
):
    """**Resolve arm happy path.** With ``charge_counters=5`` on the
    source, activating AA[1] mints 5 ``W`` coins to the source's
    controller's mana pool. ``options[0]="W"`` is the first-slice
    deterministic fallback (mirrors ``AddNManaOfChosenColor``'s
    no-agent-seated fallback at ``state_ops_resolve.rs:14057``).

    Mirrors Python's ``AddChargeCounterManaOfChosenColor.resolve`` at
    ``effects/generic/mana.py:153-165`` which delegates to
    ``AddNManaOfChosenColor(amount=X).resolve`` — both engines compute
    X at resolve time from the source's ``charge_counters``.
    """
    dict_with_no_tier_gate = _synthetic_elevator_dict()
    dict_with_no_tier_gate["activated_abilities"][1]["tier_threshold"] = 0
    elevator_id = synthetic_state.register_and_inject_object(
        dict_with_no_tier_gate, 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(elevator_id, False)
    # Seed 5 charge counters.
    synthetic_state.set_charge_counters(elevator_id, 5)
    assert synthetic_state.get_charge_counters(elevator_id) == 5

    pool_pre = synthetic_state.get_mana_pool(0)
    assert pool_pre == {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0}

    # Activate AA[1] — bypass-stack mana-ability semantics.
    synthetic_state.apply_action({
        "kind": "activate_ability",
        "source_id": elevator_id,
        "ability_index": 1,
    })

    # Post-resolve: 5 W coins added to p0's pool.
    pool_post = synthetic_state.get_mana_pool(0)
    assert pool_post == {"W": 5, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0}, (
        f"AA[1] at charge_counters=5 must mint 5 W coins (first-slice "
        f"deterministic options[0] fallback); got pool={pool_post}"
    )


def test_resolve_add_charge_counter_mana_mints_to_source_controller(
    engine, synthetic_state,
):
    """**Source-controller fan-out pin.** The minted coins go to the
    source object's controller, NOT to ``state.active_player``. A
    synthetic Eternity Elevator on p1's bf activates during p0's turn
    (default active_player==0 on a fresh synthetic state) — the coins
    must land in p1's pool, not p0's.

    Mirrors ``AddNManaOfChosenColor``'s source-controller-discovery
    pattern at ``state_ops_resolve.rs:14064-14091``; the new variant
    inherits the same contract.
    """
    dict_with_no_tier_gate = _synthetic_elevator_dict()
    dict_with_no_tier_gate["activated_abilities"][1]["tier_threshold"] = 0
    # Inject on p1's battlefield.
    elevator_id = synthetic_state.register_and_inject_object(
        dict_with_no_tier_gate, 1, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(elevator_id, False)
    synthetic_state.set_charge_counters(elevator_id, 3)

    # Activate AA[1] from p1 (the source's controller).
    synthetic_state.apply_action({
        "kind": "activate_ability",
        "source_id": elevator_id,
        "ability_index": 1,
    })

    # p1's pool gets the coins; p0's pool stays empty.
    pool_p1 = synthetic_state.get_mana_pool(1)
    assert pool_p1 == {"W": 3, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0}, (
        f"AA[1] coins must go to source-controller p1; got pool_p1={pool_p1}"
    )
    pool_p0 = synthetic_state.get_mana_pool(0)
    assert pool_p0 == {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0}, (
        f"p0's pool must stay empty (source controller is p1); "
        f"got pool_p0={pool_p0}"
    )


# ---------------------------------------------------------------------------
# Substrate-only invariant pins — Eternity Elevator STAYS DECLINED at admit
# gate post-Cycle-1
# ---------------------------------------------------------------------------


def test_the_eternity_elevator_stays_declined_post_cycle_1_admit_gate():
    """**Substrate-only invariant.** The Eternity Elevator's live
    printing must STAY DECLINED at every relevant admit gate post-C1:

      (a) ``_aa_is_phase1_sub_shape_a`` on AA[1] returns False
          (``tier_threshold > 0`` decline).
      (b) ``_carrier_aa_phase_1_effect_classes`` does NOT include
          ``AddChargeCounterManaOfChosenColor`` — the C2 widen ships
          that admit.
      (c) ``_printing_is_bridge_pure_station_spacecraft`` (Phase 1)
          returns False (``station_threshold is None`` decline).
      (d) ``_printing_is_bridge_phase_3_trigger_spacecraft`` (Phase 3)
          returns False (``station_threshold is None`` decline AND
          empty ``triggered_abilities``).
      (e) ``_printing_is_bridge_simple_carrier_aa_artifact``
          (Carrier-AA Phase 4A.2 Artifact sibling) returns False (the
          ``Spacecraft`` subtype excludes the Artifact admit; per
          ``trajectory.py:9440-9441`` non-empty subtypes decline).

    This pin is the load-bearing invariant of the Cycle 1 substrate-
    only landing — the Rust + bridge slice is dormant on production
    traffic until Cycle 2 ships the Python admit widens. A regression
    here would mean Cycle 1 silently auto-admitted the carrier
    without the matching Python admit-set bump + per-card real-EoE
    probe (Cycle 3) — a no-silent-auto-grow violation.
    """
    import json

    from mtg_bot.cards.parser_source import (
        _build_spacecraft_printing as build_spacecraft_printing,
    )
    from mtg_bot.parity.trajectory import (
        _aa_is_phase1_sub_shape_a,
        _carrier_aa_phase_1_effect_classes,
        _printing_is_bridge_pure_station_spacecraft,
        _printing_is_bridge_phase_3_trigger_spacecraft,
        _printing_is_bridge_simple_carrier_aa_artifact,
    )
    from mtg_bot.effects.generic.mana import (
        AddChargeCounterManaOfChosenColor,
    )

    with open("data/edge_of_eternities.json", encoding="utf-8") as f:
        raw_cards = json.load(f)
    raw = next(
        (c for c in raw_cards if c.get("name") == "The Eternity Elevator"),
        None,
    )
    assert raw is not None
    printing = build_spacecraft_printing(raw)
    assert printing is not None

    # (a) AA[1] declines on tier_threshold>0.
    aa1 = printing.activated_abilities[1]
    assert aa1.tier_threshold == 20
    assert _aa_is_phase1_sub_shape_a(aa1) is False, (
        "AA[1] must decline at the Phase 1 sub-shape A predicate on "
        "tier_threshold>0; Spacecraft Phase 4 C2 widens that gate"
    )

    # (b) Effect-class admit set does NOT yet include the new class.
    effect_classes = _carrier_aa_phase_1_effect_classes()
    assert AddChargeCounterManaOfChosenColor not in effect_classes, (
        "Phase 4 C1 substrate must NOT yet auto-widen "
        "_carrier_aa_phase_1_effect_classes; that widen ships C2"
    )

    # (c) Phase 1 admit predicate declines on station_threshold=None.
    assert _printing_is_bridge_pure_station_spacecraft(printing) is False

    # (d) Phase 3 admit predicate declines on station_threshold=None
    # AND empty triggered_abilities.
    assert _printing_is_bridge_phase_3_trigger_spacecraft(printing) is False

    # (e) Carrier-AA Artifact admit predicate declines on Spacecraft
    # subtype (extra_card_types is empty for Artifact-only, but
    # subtypes={"Spacecraft"} non-empty rejects at trajectory.py:9440-
    # 9441).
    assert (
        _printing_is_bridge_simple_carrier_aa_artifact(printing) is False
    ), (
        "Carrier-AA Artifact admit predicate must decline on non-empty "
        "subtypes={'Spacecraft'}; Spacecraft Phase 4 admit goes through "
        "a NEW sibling, not a widen of the Carrier-AA Artifact admit"
    )


def test_carrier_aa_phase_1_effect_classes_unchanged_post_cycle_1():
    """**No-silent-auto-grow pin.** The
    ``_carrier_aa_phase_1_effect_classes`` admit set must NOT include
    ``AddChargeCounterManaOfChosenColor`` post-C1. This pin breaks
    LOUD if a future hand mutates the Effect-class admit set without
    landing the matching admit-predicate + per-card probe + design
    doc updates.

    Sibling of the Carrier-AA Phase 4B/4C/4D/4E substrate-only
    invariant pins.
    """
    from mtg_bot.effects.generic.mana import (
        AddChargeCounterManaOfChosenColor,
    )
    from mtg_bot.parity.trajectory import (
        _carrier_aa_phase_1_effect_classes,
    )

    effect_classes = _carrier_aa_phase_1_effect_classes()
    assert AddChargeCounterManaOfChosenColor not in effect_classes


def test_python_aa_to_safe_dict_declines_eternity_elevator_aa1_on_tier_threshold():
    """**Bridge-floor invariant.** Even with the new
    ``AddChargeCounterManaOfChosenColor`` forward emit arm, the bridge
    floor ``_python_aa_to_safe_dict`` STILL DECLINES The Eternity
    Elevator's live AA[1] post-C1 because of the unrelated
    ``tier_threshold > 0`` rider gate
    (``cross_engine.py:15021``). The forward arm exists; the
    surrounding floor still says no until C2 lifts the rider gate.

    This pin is the bridge-side mirror of the per-AA admit-predicate
    decline pin above. Together they guarantee the C1 substrate is
    truly dormant on production traffic.
    """
    import json

    from mtg_bot.cards.parser_source import (
        _build_spacecraft_printing as build_spacecraft_printing,
    )
    from mtg_bot.parity.cross_engine import _python_aa_to_safe_dict

    with open("data/edge_of_eternities.json", encoding="utf-8") as f:
        raw_cards = json.load(f)
    raw = next(
        (c for c in raw_cards if c.get("name") == "The Eternity Elevator"),
        None,
    )
    assert raw is not None
    printing = build_spacecraft_printing(raw)
    assert printing is not None

    aa1 = printing.activated_abilities[1]
    assert aa1.tier_threshold == 20
    d = _python_aa_to_safe_dict(aa1)
    assert d is None, (
        "Bridge floor _python_aa_to_safe_dict must decline AA[1] on "
        "tier_threshold>0 (Phase 4 C2 widen lifts this); got dict={d}"
    )
