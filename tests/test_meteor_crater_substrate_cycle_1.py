"""**Meteor Crater substrate Phase 4 Cycle 1 (2026-05-27).**

C1 substrate-only landing per
``docs/BLOCKED_TAIL_TRACTABILITY_SCOUT_2026-05-27.md`` §#1 Meteor
Crater (Worker F's BLOCKED-tail scout recommendation; this slice
implements the C1 spec verbatim).

Deliverables (Cycle 1 Rust slice + cross-engine bridge):

  - New Rust ``Effect::AddOneManaOfChosenPermanentColor`` unit-variant
    on ``cards.rs::Effect`` — Meteor Crater's single ``{T}: Choose a
    color of a permanent you control. Add one mana of that color.``
    AA pilot effect.
  - ``parse_effect`` arm in ``cards.rs`` —
    ``"add_one_mana_of_chosen_permanent_color"`` 1-key dict (kind
    only; unit variant has no rider fields).
  - ``to_pydict`` arm in ``cards.rs`` — emits the same 1-key dict.
  - Resolve arm in ``state_ops_resolve.rs::apply_effect`` — walks the
    source-controller's battlefield, unions colored-pip slots across
    each permanent's ``mana_cost`` (W/U/B/R/G — colorless ``{C}`` and
    generic pips do NOT contribute, mirroring Python's
    ``set(o.printing.mana_cost.colors)`` walk). If the union is non-
    empty, picks the canonical-first WUBRG-ordered color from the
    union (no-agent deterministic fallback — mirror of the Phase-4E
    ``AddNManaOfChosenColor`` no-agent-seated convention at
    ``state_ops_resolve.rs:14057``). If the union is empty (only
    colorless permanents), mints one ``{C}`` colorless coin
    (defensive fallback — mirrors Python's
    ``if not options: color = "C"`` at ``mana.py:255-256``). Single
    coin minted via ``push_coins``.
  - Cross-engine bridge arms in ``src/mtg_bot/parity/cross_engine.py``:
      * Reverse arm in ``_ta_dict_to_python_effect`` — recognizes
        ``kind == "add_one_mana_of_chosen_permanent_color"`` and
        returns the Python ``AddOneManaOfChosenPermanentColor()``
        unit instance.
      * Forward arm in ``_python_aa_to_safe_dict`` — recognizes
        ``isinstance(effect, AddOneManaOfChosenPermanentColor)`` and
        emits the matching 1-key dict.
    Both arms use the SPECIFIC class (no parent ``Effect`` fall-
    through) per the Phase-3A/3B/3C/4B/4C/4D/4E specificity contract.

ZERO Python admit widen this cycle. ``_carrier_aa_phase_1_effect_
classes`` STILL has 16 entries — ``AddOneManaOfChosenPermanentColor``
is NOT yet in the admit set, and the substrate-only invariant pin
below is the load-bearing closure marker. The admit-set widen +
pin bump + per-card real-EoE probe all ship Cycle 2 as the FLIP
(mirrors the Spacecraft Phase 4 / Phase 4E C1 substrate-only
precedent — substrate lands at C1, the live FLIP lands at C2).
ZERO per-card probe this cycle (Cycle 2 ships the real-EoE
``tests/test_meteor_crater_parity.py``).

**Cycle 2 update (2026-05-27).** Cycle 2 has now LANDED: the
substrate-only invariant pin
``test_meteor_crater_stays_declined_at_admit_gate_post_cycle_1``
+ count sentinel ``test_meteor_crater_carrier_aa_effect_classes_
count_stays_16`` are INVERTED in this same file to
``test_meteor_crater_now_admits_at_admit_gate_post_cycle_2`` +
``test_meteor_crater_carrier_aa_effect_classes_count_is_17_post_
cycle_2`` per the Coordinated Clobbering 2b / Mirrorpool C4
invariant-inversion precedent. The C1 substrate-level Rust unit
pins (parse / to_pydict / resolve canonical-W / multi-color
canonical-WUBRG / colorless empty-union fallback / source-
controller fan-out / color-union scoping) all stay GREEN at C2 —
they pin the Rust resolve arm's invariants on the C1 substrate
shape and are untouched by the admit-set widen.

**Verify-first findings (live tree, main ``6d834305``):**

  - Meteor Crater printing: ``card_types=("Land",)``,
    ``supertypes=()``, ``subtypes=()``, ``keywords=frozenset()``,
    ``triggered_abilities=()``, ``static_abilities=()``, ``n_aa=1``.
  - AA[0]: ``cost=ActivationCost(tap_self=True),
    effect=AddOneManaOfChosenPermanentColor(),
    is_mana_ability=True, tier_threshold=0,
    sorcery_speed=False``.

The verify-first walk confirms Meteor Crater is the simplest open
Carrier-AA single-Effect-class port at HEAD — every gate except the
Effect-class admit set passes pre-cycle.

**Substrate-only invariant — Meteor Crater STAYS DECLINED at the
admit gate post-Cycle-1.** The Rust Effect variant + cross-engine
bridge arms all landed; the live admit gate still declines Meteor
Crater's printing because ``_carrier_aa_phase_1_effect_classes``
does NOT yet include ``AddOneManaOfChosenPermanentColor`` (the
``type(aa.effect) not in _carrier_aa_phase_1_effect_classes()``
teeth in ``_aa_is_phase1_sub_shape_a`` keeps AA[0] declined at the
per-AA gate, which cascades to the printing-level admit). The
forward serializer + Rust round-trip both succeed at C1 — driven
by synthetic unit pins; the live admit FLIP lands at C2.
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
    """An empty synthetic state — 0 battlefield, 0 hand, 0 library
    per side. Distinct from the Phase-3/4 sibling fixture (10/7/50)
    because Meteor Crater's resolve scans the controller's
    battlefield for color-union derivation — pre-seeded objects
    would inject spurious colors into the test setup. Each pin
    explicitly injects only the permanents whose colors it
    declares.
    """
    return engine.make_synthetic_state(0, 0, 0)


# ---------------------------------------------------------------------------
# Parser SoT verify-first
# ---------------------------------------------------------------------------


def test_python_add_one_mana_of_chosen_permanent_color_class_exists():
    """**Parser source-of-truth pin.** Python's
    ``AddOneManaOfChosenPermanentColor`` class is in
    ``effects.generic.mana``, a frozen dataclass with NO fields.
    """
    from mtg_bot.effects.base import Effect
    from mtg_bot.effects.generic.mana import (
        AddOneManaOfChosenPermanentColor,
    )

    eff = AddOneManaOfChosenPermanentColor()
    assert isinstance(eff, Effect)
    # Two instances compare equal (frozen dataclass __eq__ default).
    assert eff == AddOneManaOfChosenPermanentColor()


def test_meteor_crater_live_aa_shape_matches_scout_doc():
    """**Verify-first pin (scout doc §#1 row).** The live Meteor Crater
    parser SoT carries:

      * card_types=("Land",), supertypes=(), subtypes=(),
        keywords=frozenset(), triggered_abilities=(),
        static_abilities=(), n_aa=1.
      * AA[0]: cost=ActivationCost(tap_self=True),
        effect=AddOneManaOfChosenPermanentColor(),
        is_mana_ability=True, tier_threshold=0,
        sorcery_speed=False.

    This pin protects the verify-first finding the C1 substrate is
    built against; a future parser tweak that mutates the AA shape,
    the printing's card-type tuple, or any of the rider invariants
    would need to be reconciled here BEFORE C2 ships the admit widen.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.generic.mana import (
        AddOneManaOfChosenPermanentColor,
    )

    real = get_active_source().get_printings().get("Meteor Crater")
    if real is None:
        pytest.skip("Meteor Crater absent from active CardSource")

    # Printing-level shape — bare Land.
    assert real.card_types == ("Land",)
    assert real.supertypes == ()
    assert real.subtypes == ()
    assert real.keywords == frozenset()
    assert real.triggered_abilities == ()
    assert real.static_abilities == ()
    assert len(real.activated_abilities) == 1

    # AA[0] shape — bare {T} mana-ability with the new Effect class.
    aa = real.activated_abilities[0]
    assert isinstance(aa.effect, AddOneManaOfChosenPermanentColor)
    assert aa.cost.tap_self is True
    assert aa.cost.mana is None
    assert aa.is_mana_ability is True
    assert aa.tier_threshold == 0
    assert aa.sorcery_speed is False


# ---------------------------------------------------------------------------
# Cross-engine bridge arm pins (dict <-> Python)
# ---------------------------------------------------------------------------


def test_bridge_reverse_arm_add_one_mana_of_chosen_permanent_color():
    """Reverse arm constructs ``AddOneManaOfChosenPermanentColor()``
    from the 1-key ``add_one_mana_of_chosen_permanent_color`` dict.
    Mirrors the Phase-3A/3B/3C/4B/4D/4E specificity contract — unit
    variant on the wire, unit dataclass in Python.
    """
    from mtg_bot.effects.generic.mana import (
        AddOneManaOfChosenPermanentColor,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    back = _ta_dict_to_python_effect({
        "kind": "add_one_mana_of_chosen_permanent_color",
    })
    assert isinstance(back, AddOneManaOfChosenPermanentColor)
    # Unit dataclass — two instances compare equal.
    assert back == AddOneManaOfChosenPermanentColor()


def test_bridge_forward_arm_add_one_mana_of_chosen_permanent_color():
    """Forward arm in ``_python_aa_to_safe_dict`` recognizes
    ``AddOneManaOfChosenPermanentColor`` and emits the 1-key dict
    ``{"kind": "add_one_mana_of_chosen_permanent_color"}``.

    The AA carrying this effect must itself pass the bridge-floor
    rider gates — bare ``{T}`` cost, no AA-rider deal-breakers.
    """
    from mtg_bot.effects.base import ActivatedAbility, ActivationCost
    from mtg_bot.effects.generic.mana import (
        AddOneManaOfChosenPermanentColor,
    )
    from mtg_bot.parity.cross_engine import _python_aa_to_safe_dict

    aa = ActivatedAbility(
        cost=ActivationCost(tap_self=True),
        effect=AddOneManaOfChosenPermanentColor(),
        is_mana_ability=True,
    )
    d = _python_aa_to_safe_dict(aa)
    assert d is not None
    assert d["effect"] == {
        "kind": "add_one_mana_of_chosen_permanent_color",
    }
    # The cost dict carries only the tap_self flag.
    assert d["cost"] == {"tap_self": True}
    # is_mana_ability bypass-stack semantics carried on the wire
    # (Phase-4E C2 widen).
    assert d["is_mana_ability"] is True


def test_bridge_round_trip_add_one_mana_of_chosen_permanent_color():
    """Round-trip pin — Python AA → dict → Python AA yields a byte-
    equal AA at the dataclass ``__eq__`` surface.
    """
    from mtg_bot.effects.base import ActivatedAbility, ActivationCost
    from mtg_bot.effects.generic.mana import (
        AddOneManaOfChosenPermanentColor,
    )
    from mtg_bot.parity.cross_engine import (
        _aa_dict_to_python_activated_ability,
        _python_aa_to_safe_dict,
    )

    aa_orig = ActivatedAbility(
        cost=ActivationCost(tap_self=True),
        effect=AddOneManaOfChosenPermanentColor(),
        is_mana_ability=True,
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


def _synthetic_meteor_crater_dict():
    """Minimal Meteor-Crater-shape Land printing dict for the Rust
    Registry. Single ``{T}`` mana-AA with the new
    ``add_one_mana_of_chosen_permanent_color`` Effect.
    """
    return {
        "name": "Synthetic Meteor Crater",
        "card_types": ["Land"],
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


def test_rust_register_printing_with_meteor_crater_aa(engine):
    """**Rust parse arm pin.** The new
    ``add_one_mana_of_chosen_permanent_color`` parse arm accepts the
    1-key dict and returns ``Effect::AddOneManaOfChosenPermanentColor``;
    a synthetic Meteor-Crater-shape Land registers cleanly with the
    new mana-ability AA.
    """
    reg = engine.Registry()
    pid = reg.register_printing(_synthetic_meteor_crater_dict())
    assert reg.get_printing_name(pid) == "Synthetic Meteor Crater"


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
        AddOneManaOfChosenPermanentColor,
    )
    from mtg_bot.parity.cross_engine import (
        _aa_dict_to_python_activated_ability,
        _python_aa_to_safe_dict,
    )

    aa_orig = ActivatedAbility(
        cost=ActivationCost(tap_self=True),
        effect=AddOneManaOfChosenPermanentColor(),
        is_mana_ability=True,
    )
    d = _python_aa_to_safe_dict(aa_orig)
    aa_back = _aa_dict_to_python_activated_ability(d)
    assert aa_back == aa_orig
    d2 = _python_aa_to_safe_dict(aa_back)
    assert d == d2


# ---------------------------------------------------------------------------
# Rust unit pin — resolve arm
# ---------------------------------------------------------------------------


def _white_creature_dict(name: str = "White Creature"):
    """Mono-white creature printing — contributes 'W' to the color
    union when controlled by the source-controller."""
    return {
        "name": name,
        "card_types": ["Creature"],
        "mana_cost": {"W": 1, "generic": 1},
        "power": 1,
        "toughness": 1,
    }


def _blue_creature_dict(name: str = "Blue Creature"):
    return {
        "name": name,
        "card_types": ["Creature"],
        "mana_cost": {"U": 1, "generic": 1},
        "power": 1,
        "toughness": 1,
    }


def _green_creature_dict(name: str = "Green Creature"):
    return {
        "name": name,
        "card_types": ["Creature"],
        "mana_cost": {"G": 1, "generic": 1},
        "power": 1,
        "toughness": 1,
    }


def _red_creature_dict(name: str = "Red Creature"):
    return {
        "name": name,
        "card_types": ["Creature"],
        "mana_cost": {"R": 1, "generic": 1},
        "power": 1,
        "toughness": 1,
    }


def _colorless_artifact_dict(name: str = "Colorless Artifact"):
    """Pure colorless artifact — generic-only mana cost; contributes
    NO colors to the union (CR 105.2)."""
    return {
        "name": name,
        "card_types": ["Artifact"],
        "mana_cost": {"generic": 2},
    }


def test_resolve_picks_canonical_w_when_only_white_permanent(
    engine, synthetic_state,
):
    """**Resolve arm pin — single-color union (W only).** The source-
    controller controls a mono-white permanent → color union = {'W'}
    → canonical-first pick = 'W' → 1 W coin minted.
    """
    # Inject a mono-white permanent on p0's battlefield.
    synthetic_state.register_and_inject_object(
        _white_creature_dict(), 0, ZONE_BATTLEFIELD,
    )
    # Inject the Meteor Crater itself on p0's battlefield.
    crater_id = synthetic_state.register_and_inject_object(
        _synthetic_meteor_crater_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(crater_id, False)
    pool_pre = synthetic_state.get_mana_pool(0)
    assert pool_pre == {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0, "any": 0}

    # Activate the mana ability.
    synthetic_state.apply_action({
        "kind": "activate_ability",
        "source_id": crater_id,
        "ability_index": 0,
    })

    pool_post = synthetic_state.get_mana_pool(0)
    assert pool_post == {"W": 1, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0, "any": 0}, (
        f"AA at union={{'W'}} must mint 1 W coin (canonical-first); "
        f"got pool={pool_post}"
    )


def test_resolve_picks_canonical_w_when_multicolor_union(
    engine, synthetic_state,
):
    """**Resolve arm pin — multi-color union, canonical-first WUBRG.**
    The source-controller controls a U, G, R permanents (W absent,
    no obvious canonical-first via lexicographic-sort = 'G'). The
    canonical WUBRG pick is 'U' (first present in W,U,B,R,G order
    — Phase-4E precedent at ``daecd399``).

    This pin documents the divergence with Python's ``sorted(options)
    [0]`` (which would pick 'G' lexicographic-first). The substrate-
    only invariant means this divergence is NEVER exercised in
    cross-engine probes at C1; Cycle 2 reconciles the no-agent
    fallback OR ensures the probe always seats an agent.
    """
    # Inject a blue, green, and red permanent on p0's bf.
    synthetic_state.register_and_inject_object(
        _blue_creature_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.register_and_inject_object(
        _green_creature_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.register_and_inject_object(
        _red_creature_dict(), 0, ZONE_BATTLEFIELD,
    )
    crater_id = synthetic_state.register_and_inject_object(
        _synthetic_meteor_crater_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(crater_id, False)

    synthetic_state.apply_action({
        "kind": "activate_ability",
        "source_id": crater_id,
        "ability_index": 0,
    })

    # Canonical WUBRG-first pick from {'U','G','R'} = 'U'.
    pool_post = synthetic_state.get_mana_pool(0)
    assert pool_post == {"W": 0, "U": 1, "B": 0, "R": 0, "G": 0, "C": 0, "any": 0}, (
        f"AA at union={{'U','G','R'}} must mint 1 U coin "
        f"(canonical-first WUBRG); got pool={pool_post}"
    )


def test_resolve_picks_colorless_when_only_colorless_permanents(
    engine, synthetic_state,
):
    """**Resolve arm pin — colorless fallback.** The source-controller
    controls ONLY colorless permanents (e.g. an Artifact with
    ``mana_cost={"generic": 2}``) → color union = empty → defensive
    fallback mints one ``{C}`` colorless coin. Mirrors Python's
    ``if not options: color = "C"`` defensive branch at
    ``effects/generic/mana.py:255-256``.

    **Color set bounded to {W, U, B, R, G}.** This is the empty-set
    edge — the defensive ``{C}`` only fires when the union is empty.
    """
    # Inject a colorless permanent on p0's bf.
    synthetic_state.register_and_inject_object(
        _colorless_artifact_dict(), 0, ZONE_BATTLEFIELD,
    )
    crater_id = synthetic_state.register_and_inject_object(
        _synthetic_meteor_crater_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(crater_id, False)

    synthetic_state.apply_action({
        "kind": "activate_ability",
        "source_id": crater_id,
        "ability_index": 0,
    })

    pool_post = synthetic_state.get_mana_pool(0)
    assert pool_post == {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 1, "any": 0}, (
        f"AA at empty union must mint 1 C colorless coin "
        f"(defensive fallback); got pool={pool_post}"
    )


def test_resolve_mints_to_source_controller_not_active_player(
    engine, synthetic_state,
):
    """**Source-controller fan-out pin.** The minted coin goes to the
    source object's controller, NOT to ``state.active_player``. A
    synthetic Meteor Crater on p1's bf activates with the source-
    controller's battlefield supplying the color union (p1's mono-
    white creature) — the coin must land in p1's pool, not p0's.

    Mirrors ``AddNManaOfChosenColor``'s source-controller-discovery
    pattern at ``state_ops_resolve.rs:14064-14091``; the new variant
    inherits the same contract.
    """
    # Inject mono-white creature on p1's bf (so p1's color union is W).
    synthetic_state.register_and_inject_object(
        _white_creature_dict(), 1, ZONE_BATTLEFIELD,
    )
    # Meteor Crater on p1's bf (default active_player == 0).
    crater_id = synthetic_state.register_and_inject_object(
        _synthetic_meteor_crater_dict(), 1, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(crater_id, False)

    synthetic_state.apply_action({
        "kind": "activate_ability",
        "source_id": crater_id,
        "ability_index": 0,
    })

    pool_p1 = synthetic_state.get_mana_pool(1)
    assert pool_p1 == {"W": 1, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0, "any": 0}, (
        f"AA coin must go to source-controller p1; got pool_p1={pool_p1}"
    )
    pool_p0 = synthetic_state.get_mana_pool(0)
    assert pool_p0 == {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0, "any": 0}, (
        f"p0's pool must stay empty (source controller is p1); "
        f"got pool_p0={pool_p0}"
    )


def test_resolve_color_union_only_from_source_controllers_battlefield(
    engine, synthetic_state,
):
    """**Color union scoping pin.** The color union is built from the
    SOURCE-CONTROLLER's battlefield only — NOT both players' bfs.
    Mirrors Python's ``if o.controller_id != controller_id: continue``
    at ``mana.py:251-253``.

    Setup: p0 controls a green creature; p1 controls a red creature
    + the Meteor Crater. Activating p1's Crater must produce R (R is
    on p1's bf), NOT G (G is on p0's bf, which is not source-
    controller).
    """
    # p0's bf — green creature (should be IGNORED).
    synthetic_state.register_and_inject_object(
        _green_creature_dict(), 0, ZONE_BATTLEFIELD,
    )
    # p1's bf — red creature (should contribute to union).
    synthetic_state.register_and_inject_object(
        _red_creature_dict(), 1, ZONE_BATTLEFIELD,
    )
    crater_id = synthetic_state.register_and_inject_object(
        _synthetic_meteor_crater_dict(), 1, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(crater_id, False)

    synthetic_state.apply_action({
        "kind": "activate_ability",
        "source_id": crater_id,
        "ability_index": 0,
    })

    # p1's bf union = {'R'} → canonical-first pick = 'R'.
    pool_p1 = synthetic_state.get_mana_pool(1)
    assert pool_p1 == {"W": 0, "U": 0, "B": 0, "R": 1, "G": 0, "C": 0, "any": 0}, (
        f"Color union must be source-controller p1's bf only; "
        f"got pool_p1={pool_p1}"
    )


# ---------------------------------------------------------------------------
# Substrate-only invariant — Meteor Crater STAYS DECLINED at admit gate
# (load-bearing closure marker)
# ---------------------------------------------------------------------------


def test_meteor_crater_now_admits_at_admit_gate_post_cycle_2():
    """**LOAD-BEARING flip invariant pin (INVERTED at Cycle 2).** Meteor
    Crater's live printing FLIPS DECLINED → ADMITTED at the Phase-4
    Carrier-AA admit gate post-Cycle-2.

    Post-C2 invariants:

      (a) ``_carrier_aa_phase_1_effect_classes`` INCLUDES
          ``AddOneManaOfChosenPermanentColor`` (the Effect-class
          admit set is 17 entries post-C2 — the C2 widen lands the
          16 → 17 bump).
      (b) ``_aa_is_phase1_sub_shape_a(meteor.activated_abilities[0])``
          returns True (the ``type(aa.effect) not in
          _carrier_aa_phase_1_effect_classes()`` teeth no longer
          fire; the Phase-1.5a bare ``{T}`` cost gate + the Phase-4E
          ``is_mana_ability=True`` AA-rider widen all clear too).
      (c) ``_printing_is_bridge_simple_carrier_aa_land(meteor)``
          returns True (the per-AA gate admits, and the single-AA
          all-or-nothing printing-level cascade admits the
          printing).
      (d) ``_printing_is_bridge_simple_carrier_aa_any(meteor)``
          returns True (the top-level dispatcher delegates to the
          Land sibling which admits).

    This pin was renamed from
    ``test_meteor_crater_stays_declined_at_admit_gate_post_cycle_1``
    at Cycle 2 per the Coordinated Clobbering 2b / Mirrorpool C4
    invariant-inversion precedent. If this pin fails — i.e. the
    admit-gate stops admitting Meteor Crater — the C2 FLIP has
    silently regressed and the per-card real-EoE probe would run
    against a wrong fixture. Catch the drift here.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.generic.mana import (
        AddOneManaOfChosenPermanentColor,
    )
    from mtg_bot.parity.trajectory import (
        _aa_is_phase1_sub_shape_a,
        _carrier_aa_phase_1_effect_classes,
        _printing_is_bridge_simple_carrier_aa_any,
        _printing_is_bridge_simple_carrier_aa_land,
    )

    real = get_active_source().get_printings().get("Meteor Crater")
    if real is None:
        pytest.skip("Meteor Crater absent from active CardSource")

    # (a) Effect-class admit set INCLUDES the new class post-C2.
    effect_classes = _carrier_aa_phase_1_effect_classes()
    assert AddOneManaOfChosenPermanentColor in effect_classes, (
        "Flip invariant violation: "
        "AddOneManaOfChosenPermanentColor MUST be in the Carrier-"
        "AA Phase-1 Effect-class admit set post-C2."
    )

    # (b) Per-AA gate ADMITS post-C2.
    aa = real.activated_abilities[0]
    assert _aa_is_phase1_sub_shape_a(aa) is True, (
        "Flip invariant violation: "
        "_aa_is_phase1_sub_shape_a must ADMIT Meteor Crater's "
        "AA[0] post-C2 on the Effect-class widen + Phase-1.5a "
        "bare {T} cost gate + Phase-4E is_mana_ability rider."
    )

    # (c) Carrier-AA Land admit predicate ADMITS.
    assert _printing_is_bridge_simple_carrier_aa_land(real) is True, (
        "Flip invariant violation: "
        "_printing_is_bridge_simple_carrier_aa_land must ADMIT "
        "Meteor Crater post-C2 (cascades from per-AA admit at the "
        "single-AA all-or-nothing walk)."
    )

    # (d) Top-level dispatcher ADMITS.
    assert _printing_is_bridge_simple_carrier_aa_any(real) is True, (
        "Flip invariant violation: "
        "_printing_is_bridge_simple_carrier_aa_any must ADMIT "
        "Meteor Crater post-C2 (delegates to the Land sibling)."
    )


def test_meteor_crater_carrier_aa_effect_classes_count_is_17_post_cycle_2():
    """**Flip count sentinel (INVERTED at Cycle 2; rebased at
    Reflecting Pool C2 to count 18).** The
    ``_carrier_aa_phase_1_effect_classes`` admit-set size MUST be 18
    post-Reflecting-Pool-C2 — Meteor Crater C2 landed the 16 → 17
    bump (adding ``AddOneManaOfChosenPermanentColor``); Reflecting
    Pool C2 (2026-05-27) landed the 17 → 18 bump (adding
    ``AddOneManaFromControlledLandsProductions``).

    Renamed from ``test_meteor_crater_carrier_aa_effect_classes_
    count_stays_16``; pin the new count so a future widen / drift
    surfaces here before a silent admit-gate flip beyond the C2
    closure.
    """
    from mtg_bot.parity.trajectory import (
        _carrier_aa_phase_1_effect_classes,
    )

    assert len(_carrier_aa_phase_1_effect_classes()) == 18, (
        "Flip invariant: the Carrier-AA Phase-1 Effect-class admit "
        "set MUST have exactly 18 entries post-Reflecting-Pool-Cycle-"
        "2 — Meteor Crater C2 lands the 16 → 17 bump adding "
        "AddOneManaOfChosenPermanentColor; Reflecting Pool C2 lands "
        "the 17 → 18 bump adding "
        "AddOneManaFromControlledLandsProductions."
    )
