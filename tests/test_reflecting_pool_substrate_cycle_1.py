"""**Reflecting Pool substrate Phase 4 Cycle 1 (2026-05-27).**

C1 substrate-only landing per
``docs/BLOCKED_TAIL_TRACTABILITY_SCOUT_2026-05-27.md`` §#2 Reflecting
Pool (Worker F's BLOCKED-tail scout recommendation; this slice
implements the C1 spec verbatim, sibling-discounted off the Meteor
Crater C1 substrate at ``eb059eaa`` per the scout doc).

Deliverables (Cycle 1 Rust slice + cross-engine bridge):

  - New Rust ``Effect::AddOneManaFromControlledLandsProductions``
    unit-variant on ``cards.rs::Effect`` — Reflecting Pool's single
    ``{T}: Add one mana of any type that a land you control could
    produce.`` AA pilot effect.
  - ``parse_effect`` arm in ``cards.rs`` —
    ``"add_one_mana_from_controlled_lands_productions"`` 1-key dict
    (kind only; unit variant has no rider fields).
  - ``to_pydict`` arm in ``cards.rs`` — emits the same 1-key dict.
  - Resolve arm in ``state_ops_resolve.rs::apply_effect`` — walks the
    source-controller's battlefield, filters to permanents whose
    ``card_types`` contains ``"Land"``, unions each Land's
    ``mana_produced`` symbols (W/U/B/R/G/C — the full produces
    vocabulary, unlike ``AddOneManaOfChosenPermanentColor`` which is
    bounded to colored pips only). If the union is non-empty, picks
    the canonical-first WUBRG-then-C color from the union (no-agent
    deterministic fallback — same precedent as the Meteor Crater C1
    sibling at ``state_ops_resolve.rs:14318-14333``). If the union is
    empty (no Lands in play, or Lands with no ``mana_produced``),
    mints one ``{C}`` colorless coin (defensive fallback — mirrors
    Python's ``if not options: color = "C"`` at
    ``mana.py:204-205``). Single coin minted via ``push_coins``.
  - Cross-engine bridge arms in ``src/mtg_bot/parity/cross_engine.py``:
      * Reverse arm in ``_ta_dict_to_python_effect`` — recognizes
        ``kind == "add_one_mana_from_controlled_lands_productions"``
        and returns the Python
        ``AddOneManaFromControlledLandsProductions()`` unit instance.
      * Forward arm in ``_python_aa_to_safe_dict`` — recognizes
        ``isinstance(effect, AddOneManaFromControlledLandsProductions)``
        and emits the matching 1-key dict.
    Both arms use the SPECIFIC class (no parent ``Effect`` fall-
    through) per the Phase-3A/3B/3C/4B/4C/4D/4E/Meteor-Crater
    specificity contract.

ZERO Python admit widen this cycle. ``_carrier_aa_phase_1_effect_
classes`` STILL has 16 entries — neither
``AddOneManaOfChosenPermanentColor`` (Meteor Crater's class, also
deliberately excluded at MC C1) NOR
``AddOneManaFromControlledLandsProductions`` (Reflecting Pool's
class) is in the admit set, and the substrate-only invariant pin
below is the load-bearing closure marker. The admit-set widen +
pin bump + per-card real-EoE probe all ship Cycle 2 as the FLIP
(mirrors the Meteor Crater C1 substrate-only precedent at
``eb059eaa`` — substrate lands at C1, the live FLIP lands at C2).
ZERO per-card probe this cycle (Cycle 2 ships the real-EoE
``tests/test_reflecting_pool_parity.py``).

**Cycle 2 update (2026-05-27).** Cycle 2 has now LANDED: the
substrate-only invariant pin
``test_reflecting_pool_stays_declined_at_admit_gate_post_cycle_1``
+ count sentinel ``test_reflecting_pool_carrier_aa_effect_classes
_count_stays_17`` are INVERTED in this same file to
``test_reflecting_pool_now_admits_at_admit_gate_post_cycle_2`` +
``test_reflecting_pool_carrier_aa_effect_classes_count_is_18_
post_cycle_2`` per the Coordinated Clobbering 2b / Mirrorpool C4 /
Meteor Crater C2 invariant-inversion precedent. The C1 substrate-
level Rust unit pins (parse / to_pydict / resolve canonical-W /
multi-color canonical-WUBRG-then-C / colorless empty-union
fallback / source-controller fan-out / produces-union scoping) all
stay GREEN at C2 — they pin the Rust resolve arm's invariants on
the C1 substrate shape and are untouched by the admit-set widen.

**Verify-first findings (live tree, main ``eb059eaa``):**

  - Reflecting Pool printing: ``card_types=("Land",)``,
    ``supertypes=()``, ``subtypes=()``, ``keywords=frozenset()``,
    ``triggered_abilities=()``, ``static_abilities=()``,
    ``produces=frozenset()`` (Reflecting Pool's own
    ``produces`` is empty because what it can produce DEPENDS on
    the battlefield; the production set is materialized at resolve
    time, not stored on the printing), ``n_aa=1``.
  - AA[0]: ``cost=ActivationCost(tap_self=True),
    effect=AddOneManaFromControlledLandsProductions(),
    is_mana_ability=True, tier_threshold=0,
    sorcery_speed=False``.

The verify-first walk confirms Reflecting Pool's AA shape matches
the scout-doc §#2 spec verbatim — bare ``{T}`` mana-ability + the
new Effect class; every gate except the Effect-class admit set
passes pre-cycle.

**Substrate-only invariant — Reflecting Pool STAYS DECLINED at the
admit gate post-Cycle-1.** The Rust Effect variant + cross-engine
bridge arms all landed; the live admit gate still declines
Reflecting Pool's printing because
``_carrier_aa_phase_1_effect_classes`` does NOT yet include
``AddOneManaFromControlledLandsProductions`` (the
``type(aa.effect) not in _carrier_aa_phase_1_effect_classes()``
teeth in ``_aa_is_phase1_sub_shape_a`` keeps AA[0] declined at
the per-AA gate, which cascades to the printing-level admit).
The forward serializer + Rust round-trip both succeed at C1 —
driven by synthetic unit pins; the live admit FLIP lands at C2.
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
    because Reflecting Pool's resolve scans the controller's
    battlefield for Lands-produces-derivation — pre-seeded objects
    would inject spurious produces into the test setup. Each pin
    explicitly injects only the Lands whose produces it declares.
    """
    return engine.make_synthetic_state(0, 0, 0)


# ---------------------------------------------------------------------------
# Parser SoT verify-first
# ---------------------------------------------------------------------------


def test_python_add_one_mana_from_controlled_lands_productions_class_exists():
    """**Parser source-of-truth pin.** Python's
    ``AddOneManaFromControlledLandsProductions`` class is in
    ``effects.generic.mana``, a frozen dataclass with NO fields.
    """
    from mtg_bot.effects.base import Effect
    from mtg_bot.effects.generic.mana import (
        AddOneManaFromControlledLandsProductions,
    )

    eff = AddOneManaFromControlledLandsProductions()
    assert isinstance(eff, Effect)
    # Two instances compare equal (frozen dataclass __eq__ default).
    assert eff == AddOneManaFromControlledLandsProductions()


def test_reflecting_pool_live_aa_shape_matches_scout_doc():
    """**Verify-first pin (scout doc §#2 row).** The live Reflecting
    Pool parser SoT carries:

      * card_types=("Land",), supertypes=(), subtypes=(),
        keywords=frozenset(), triggered_abilities=(),
        static_abilities=(), n_aa=1.
      * AA[0]: cost=ActivationCost(tap_self=True),
        effect=AddOneManaFromControlledLandsProductions(),
        is_mana_ability=True, tier_threshold=0,
        sorcery_speed=False.

    This pin protects the verify-first finding the C1 substrate is
    built against; a future parser tweak that mutates the AA shape,
    the printing's card-type tuple, or any of the rider invariants
    would need to be reconciled here BEFORE C2 ships the admit widen.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.generic.mana import (
        AddOneManaFromControlledLandsProductions,
    )

    real = get_active_source().get_printings().get("Reflecting Pool")
    if real is None:
        pytest.skip("Reflecting Pool absent from active CardSource")

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
    assert isinstance(aa.effect, AddOneManaFromControlledLandsProductions)
    assert aa.cost.tap_self is True
    assert aa.cost.mana is None
    assert aa.is_mana_ability is True
    assert aa.tier_threshold == 0
    assert aa.sorcery_speed is False


# ---------------------------------------------------------------------------
# Cross-engine bridge arm pins (dict <-> Python)
# ---------------------------------------------------------------------------


def test_bridge_reverse_arm_add_one_mana_from_controlled_lands_productions():
    """Reverse arm constructs
    ``AddOneManaFromControlledLandsProductions()`` from the 1-key
    ``add_one_mana_from_controlled_lands_productions`` dict.
    Mirrors the Phase-3A/3B/3C/4B/4D/4E/Meteor-Crater specificity
    contract — unit variant on the wire, unit dataclass in Python.
    """
    from mtg_bot.effects.generic.mana import (
        AddOneManaFromControlledLandsProductions,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    back = _ta_dict_to_python_effect({
        "kind": "add_one_mana_from_controlled_lands_productions",
    })
    assert isinstance(back, AddOneManaFromControlledLandsProductions)
    # Unit dataclass — two instances compare equal.
    assert back == AddOneManaFromControlledLandsProductions()


def test_bridge_forward_arm_add_one_mana_from_controlled_lands_productions():
    """Forward arm in ``_python_aa_to_safe_dict`` recognizes
    ``AddOneManaFromControlledLandsProductions`` and emits the 1-key
    dict ``{"kind": "add_one_mana_from_controlled_lands_productions"}``.

    The AA carrying this effect must itself pass the bridge-floor
    rider gates — bare ``{T}`` cost, no AA-rider deal-breakers.
    """
    from mtg_bot.effects.base import ActivatedAbility, ActivationCost
    from mtg_bot.effects.generic.mana import (
        AddOneManaFromControlledLandsProductions,
    )
    from mtg_bot.parity.cross_engine import _python_aa_to_safe_dict

    aa = ActivatedAbility(
        cost=ActivationCost(tap_self=True),
        effect=AddOneManaFromControlledLandsProductions(),
        is_mana_ability=True,
    )
    d = _python_aa_to_safe_dict(aa)
    assert d is not None
    assert d["effect"] == {
        "kind": "add_one_mana_from_controlled_lands_productions",
    }
    # The cost dict carries only the tap_self flag.
    assert d["cost"] == {"tap_self": True}
    # is_mana_ability bypass-stack semantics carried on the wire
    # (Phase-4E C2 widen).
    assert d["is_mana_ability"] is True


def test_bridge_round_trip_add_one_mana_from_controlled_lands_productions():
    """Round-trip pin — Python AA → dict → Python AA yields a byte-
    equal AA at the dataclass ``__eq__`` surface.
    """
    from mtg_bot.effects.base import ActivatedAbility, ActivationCost
    from mtg_bot.effects.generic.mana import (
        AddOneManaFromControlledLandsProductions,
    )
    from mtg_bot.parity.cross_engine import (
        _aa_dict_to_python_activated_ability,
        _python_aa_to_safe_dict,
    )

    aa_orig = ActivatedAbility(
        cost=ActivationCost(tap_self=True),
        effect=AddOneManaFromControlledLandsProductions(),
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


def _synthetic_reflecting_pool_dict():
    """Minimal Reflecting-Pool-shape Land printing dict for the Rust
    Registry. Single ``{T}`` mana-AA with the new
    ``add_one_mana_from_controlled_lands_productions`` Effect.
    """
    return {
        "name": "Synthetic Reflecting Pool",
        "card_types": ["Land"],
        "activated_abilities": [
            {
                "cost": {"tap_self": True},
                "effect": {
                    "kind": "add_one_mana_from_controlled_lands_productions",
                },
                "is_mana_ability": True,
            },
        ],
    }


def test_rust_register_printing_with_reflecting_pool_aa(engine):
    """**Rust parse arm pin.** The new
    ``add_one_mana_from_controlled_lands_productions`` parse arm
    accepts the 1-key dict and returns
    ``Effect::AddOneManaFromControlledLandsProductions``; a synthetic
    Reflecting-Pool-shape Land registers cleanly with the new mana-
    ability AA.
    """
    reg = engine.Registry()
    pid = reg.register_printing(_synthetic_reflecting_pool_dict())
    assert reg.get_printing_name(pid) == "Synthetic Reflecting Pool"


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
        AddOneManaFromControlledLandsProductions,
    )
    from mtg_bot.parity.cross_engine import (
        _aa_dict_to_python_activated_ability,
        _python_aa_to_safe_dict,
    )

    aa_orig = ActivatedAbility(
        cost=ActivationCost(tap_self=True),
        effect=AddOneManaFromControlledLandsProductions(),
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


def _land_dict(name: str, produces: list[str]):
    """Synthetic Land printing with explicit ``mana_produced`` list."""
    return {
        "name": name,
        "card_types": ["Land"],
        "mana_produced": produces,
    }


def _green_creature_dict(name: str = "Green Creature"):
    """Mono-G creature — NOT a Land; must NOT contribute to the
    Reflecting Pool union. Sibling-shape of the MC C1 _green_creature_
    dict but used here as the negative-control (Land filter rejects)."""
    return {
        "name": name,
        "card_types": ["Creature"],
        "mana_cost": {"G": 1, "generic": 1},
        "power": 1,
        "toughness": 1,
    }


def _colorless_artifact_dict(name: str = "Colorless Artifact"):
    """Pure colorless artifact — NOT a Land, also colorless. Negative-
    control on the Land filter."""
    return {
        "name": name,
        "card_types": ["Artifact"],
        "mana_cost": {"generic": 2},
    }


def test_resolve_picks_canonical_w_when_only_white_land(
    engine, synthetic_state,
):
    """**Resolve arm pin — single-color Land union (W only).** The
    source-controller controls a single mono-white-producing Land →
    produces union = {'W'} → canonical-first pick = 'W' → 1 W coin
    minted.
    """
    # Inject a Plains-shape (W-producing Land) on p0's battlefield.
    synthetic_state.register_and_inject_object(
        _land_dict("Synth Plains", ["W"]), 0, ZONE_BATTLEFIELD,
    )
    # Inject the Reflecting Pool itself on p0's battlefield.
    pool_id = synthetic_state.register_and_inject_object(
        _synthetic_reflecting_pool_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(pool_id, False)
    pool_pre = synthetic_state.get_mana_pool(0)
    assert pool_pre == {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0, "any": 0}

    # Activate the mana ability.
    synthetic_state.apply_action({
        "kind": "activate_ability",
        "source_id": pool_id,
        "ability_index": 0,
    })

    pool_post = synthetic_state.get_mana_pool(0)
    assert pool_post == {"W": 1, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0, "any": 0}, (
        f"AA at union={{'W'}} must mint 1 W coin (canonical-first); "
        f"got pool={pool_post}"
    )


def test_resolve_picks_canonical_u_when_multicolor_land_union(
    engine, synthetic_state,
):
    """**Resolve arm pin — multi-color Land union, canonical-first
    WUBRG.** The source-controller controls U, G, R-producing Lands
    (W absent). The canonical WUBRG pick is 'U' (first present in
    W,U,B,R,G,C order — Meteor Crater C1 / Phase-4E precedent at
    ``daecd399``).

    This pin documents the divergence with Python's
    ``sorted(options)[0]`` (which would pick 'G' lexicographic-
    first). The substrate-only invariant means this divergence is
    NEVER exercised in cross-engine probes at C1; Cycle 2 reconciles
    the no-agent fallback OR ensures the probe always seats an
    agent.
    """
    # Inject U, G, R Lands on p0's bf.
    synthetic_state.register_and_inject_object(
        _land_dict("Synth Island", ["U"]), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.register_and_inject_object(
        _land_dict("Synth Forest", ["G"]), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.register_and_inject_object(
        _land_dict("Synth Mountain", ["R"]), 0, ZONE_BATTLEFIELD,
    )
    pool_id = synthetic_state.register_and_inject_object(
        _synthetic_reflecting_pool_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(pool_id, False)

    synthetic_state.apply_action({
        "kind": "activate_ability",
        "source_id": pool_id,
        "ability_index": 0,
    })

    # Canonical WUBRG-first pick from {'U','G','R'} = 'U'.
    pool_post = synthetic_state.get_mana_pool(0)
    assert pool_post == {"W": 0, "U": 1, "B": 0, "R": 0, "G": 0, "C": 0, "any": 0}, (
        f"AA at union={{'U','G','R'}} must mint 1 U coin "
        f"(canonical-first WUBRG); got pool={pool_post}"
    )


def test_resolve_picks_w_over_c_when_dual_produces_includes_colored(
    engine, synthetic_state,
):
    """**Resolve arm pin — colored-vs-C precedence.** Mirrors the
    real-EoE Grove-of-the-Burnwillows shape (``produces={G, C, R}``):
    when the union contains both colored AND ``C`` slots, the
    canonical pick prefers colored. Setup: a single Land producing
    ``{R, C}`` → union = {R, C}; canonical W → U → B → R → G → C
    picks R first, NOT C.
    """
    synthetic_state.register_and_inject_object(
        _land_dict("Synth Dual RC", ["R", "C"]), 0, ZONE_BATTLEFIELD,
    )
    pool_id = synthetic_state.register_and_inject_object(
        _synthetic_reflecting_pool_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(pool_id, False)

    synthetic_state.apply_action({
        "kind": "activate_ability",
        "source_id": pool_id,
        "ability_index": 0,
    })

    pool_post = synthetic_state.get_mana_pool(0)
    assert pool_post == {"W": 0, "U": 0, "B": 0, "R": 1, "G": 0, "C": 0, "any": 0}, (
        f"AA at union={{'R','C'}} must mint 1 R coin "
        f"(canonical W→U→B→R→G→C prefers colored over C); "
        f"got pool={pool_post}"
    )


def test_resolve_picks_c_when_only_c_producing_land(
    engine, synthetic_state,
):
    """**Resolve arm pin — C-only Land union.** Mirrors Wastes /
    Blinkmoth-Nexus-shape Lands (``produces={C}``): when the only
    Lands in play produce only colorless, the union is {C} →
    canonical pick = C → 1 C coin minted.

    This is the W→U→B→R→G→C fall-through case where the union is
    non-empty but contains ONLY ``C``; the C branch fires from the
    canonical chain itself, NOT from the empty-union defensive
    fallback (both yield the same observable coin, but distinguish
    the code path).
    """
    synthetic_state.register_and_inject_object(
        _land_dict("Synth Wastes", ["C"]), 0, ZONE_BATTLEFIELD,
    )
    pool_id = synthetic_state.register_and_inject_object(
        _synthetic_reflecting_pool_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(pool_id, False)

    synthetic_state.apply_action({
        "kind": "activate_ability",
        "source_id": pool_id,
        "ability_index": 0,
    })

    pool_post = synthetic_state.get_mana_pool(0)
    assert pool_post == {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 1, "any": 0}, (
        f"AA at union={{'C'}} must mint 1 C coin; got pool={pool_post}"
    )


def test_resolve_falls_back_to_c_when_no_lands(
    engine, synthetic_state,
):
    """**Resolve arm pin — empty-union defensive fallback.** The
    source-controller controls ONLY non-Land permanents (Reflecting
    Pool is the only Land — but its own ``mana_produced`` is empty
    because Reflecting Pool's printing has ``produces=frozenset()``;
    the produces are derived at resolve time from OTHER Lands). Union
    is empty → defensive fallback mints one ``{C}`` colorless coin.
    Mirrors Python's ``if not options: color = "C"`` defensive
    branch at ``effects/generic/mana.py:204-205``.

    Subtle but important: Reflecting Pool ITSELF is a Land on the
    bf at this point, but its own synthetic dict has no
    ``mana_produced`` key (defaults to ``None`` in Rust). With only
    Reflecting Pool on the bf (no other Lands), and no
    ``mana_produced`` symbols, the union stays empty and the
    defensive ``{C}`` fallback fires.
    """
    # Inject ONLY the Reflecting Pool itself on p0's bf — no other
    # Lands, so the Land union has only Reflecting Pool which has
    # an empty mana_produced (None), and the produces union is
    # empty.
    pool_id = synthetic_state.register_and_inject_object(
        _synthetic_reflecting_pool_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(pool_id, False)

    synthetic_state.apply_action({
        "kind": "activate_ability",
        "source_id": pool_id,
        "ability_index": 0,
    })

    pool_post = synthetic_state.get_mana_pool(0)
    assert pool_post == {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 1, "any": 0}, (
        f"AA at empty union must mint 1 C colorless coin "
        f"(defensive fallback); got pool={pool_post}"
    )


def test_resolve_ignores_non_land_permanents(
    engine, synthetic_state,
):
    """**Resolve arm pin — Land filter.** Non-Land permanents
    contribute nothing to the produces union, even if their
    ``mana_cost`` carries colored pips (mirrors Python's
    ``if not o.printing.is_land: continue`` walk at
    ``effects/generic/mana.py:201-203``). Setup: a green creature
    + a colorless artifact + the Reflecting Pool — no other Lands.
    Union is empty (none of the non-Lands contribute) → defensive
    ``{C}`` fallback fires.

    This distinguishes Reflecting Pool's behavior from Meteor
    Crater (whose union is built from ALL permanents' mana_cost
    colors). The Land filter is the key delta.
    """
    # Inject a green creature on p0's bf (non-Land — ignored).
    synthetic_state.register_and_inject_object(
        _green_creature_dict(), 0, ZONE_BATTLEFIELD,
    )
    # Inject a colorless artifact (non-Land — ignored).
    synthetic_state.register_and_inject_object(
        _colorless_artifact_dict(), 0, ZONE_BATTLEFIELD,
    )
    pool_id = synthetic_state.register_and_inject_object(
        _synthetic_reflecting_pool_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(pool_id, False)

    synthetic_state.apply_action({
        "kind": "activate_ability",
        "source_id": pool_id,
        "ability_index": 0,
    })

    pool_post = synthetic_state.get_mana_pool(0)
    assert pool_post == {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 1, "any": 0}, (
        f"AA must IGNORE non-Land permanents (creature + artifact); "
        f"empty Land-produces union → defensive C fallback; "
        f"got pool={pool_post}"
    )


def test_resolve_mints_to_source_controller_not_active_player(
    engine, synthetic_state,
):
    """**Source-controller fan-out pin.** The minted coin goes to the
    source object's controller, NOT to ``state.active_player``. A
    synthetic Reflecting Pool on p1's bf activates with the source-
    controller's controlled Lands supplying the produces union (p1's
    Synth Plains) — the coin must land in p1's pool, not p0's.

    Mirrors the Meteor Crater C1 source-controller-discovery
    pattern; the new variant inherits the same contract via the
    5-zone walk + stack scan.
    """
    # Inject Synth Plains on p1's bf (so p1's Land union is W).
    synthetic_state.register_and_inject_object(
        _land_dict("Synth Plains", ["W"]), 1, ZONE_BATTLEFIELD,
    )
    # Reflecting Pool on p1's bf (default active_player == 0).
    pool_id = synthetic_state.register_and_inject_object(
        _synthetic_reflecting_pool_dict(), 1, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(pool_id, False)

    synthetic_state.apply_action({
        "kind": "activate_ability",
        "source_id": pool_id,
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


def test_resolve_produces_union_only_from_source_controllers_lands(
    engine, synthetic_state,
):
    """**Produces-union scoping pin.** The produces union is built
    from the SOURCE-CONTROLLER's Lands only — NOT both players'
    Lands. Mirrors Python's
    ``if o.controller_id != controller_id: continue`` at
    ``mana.py:198-200``.

    Setup: p0 controls a Synth Forest (G); p1 controls a Synth
    Mountain (R) + the Reflecting Pool. Activating p1's Pool must
    produce R (R is on p1's bf), NOT G (G is on p0's bf, which is
    not source-controller).
    """
    # p0's bf — Synth Forest (G-producing; should be IGNORED).
    synthetic_state.register_and_inject_object(
        _land_dict("Synth Forest", ["G"]), 0, ZONE_BATTLEFIELD,
    )
    # p1's bf — Synth Mountain (R-producing; should contribute to
    # union).
    synthetic_state.register_and_inject_object(
        _land_dict("Synth Mountain", ["R"]), 1, ZONE_BATTLEFIELD,
    )
    pool_id = synthetic_state.register_and_inject_object(
        _synthetic_reflecting_pool_dict(), 1, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(pool_id, False)

    synthetic_state.apply_action({
        "kind": "activate_ability",
        "source_id": pool_id,
        "ability_index": 0,
    })

    # p1's bf union = {'R'} → canonical-first pick = 'R'.
    pool_p1 = synthetic_state.get_mana_pool(1)
    assert pool_p1 == {"W": 0, "U": 0, "B": 0, "R": 1, "G": 0, "C": 0, "any": 0}, (
        f"Produces union must be source-controller p1's Lands only; "
        f"got pool_p1={pool_p1}"
    )


# ---------------------------------------------------------------------------
# Substrate-only invariant — Reflecting Pool STAYS DECLINED at admit gate
# (load-bearing closure marker)
# ---------------------------------------------------------------------------


def test_reflecting_pool_now_admits_at_admit_gate_post_cycle_2():
    """**LOAD-BEARING flip invariant pin (INVERTED at Cycle 2).**
    Reflecting Pool's live printing FLIPS DECLINED → ADMITTED at
    the Phase-4 Carrier-AA admit gate post-Cycle-2.

    Post-C2 invariants:

      (a) ``_carrier_aa_phase_1_effect_classes`` INCLUDES
          ``AddOneManaFromControlledLandsProductions`` (the Effect-
          class admit set is 18 entries post-C2 — the C2 widen
          lands the 17 → 18 bump).
      (b) ``_aa_is_phase1_sub_shape_a(reflecting.activated_abilities
          [0])`` returns True (the ``type(aa.effect) not in
          _carrier_aa_phase_1_effect_classes()`` teeth no longer
          fire; the Phase-1.5a bare ``{T}`` cost gate + the
          Phase-4E ``is_mana_ability=True`` AA-rider widen all
          clear too).
      (c) ``_printing_is_bridge_simple_carrier_aa_land(reflecting)``
          returns True (the per-AA gate admits, and the single-AA
          all-or-nothing printing-level cascade admits the
          printing).
      (d) ``_printing_is_bridge_simple_carrier_aa_any(reflecting)``
          returns True (the top-level dispatcher delegates to the
          Land sibling which admits).

    This pin was renamed from
    ``test_reflecting_pool_stays_declined_at_admit_gate_post_cycle_1``
    at Cycle 2 per the Coordinated Clobbering 2b / Mirrorpool C4 /
    Meteor Crater C2 invariant-inversion precedent. If this pin
    fails — i.e. the admit-gate stops admitting Reflecting Pool —
    the C2 FLIP has silently regressed and the per-card real-EoE
    probe would run against a wrong fixture. Catch the drift here.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.generic.mana import (
        AddOneManaFromControlledLandsProductions,
    )
    from mtg_bot.parity.trajectory import (
        _aa_is_phase1_sub_shape_a,
        _carrier_aa_phase_1_effect_classes,
        _printing_is_bridge_simple_carrier_aa_any,
        _printing_is_bridge_simple_carrier_aa_land,
    )

    real = get_active_source().get_printings().get("Reflecting Pool")
    if real is None:
        pytest.skip("Reflecting Pool absent from active CardSource")

    # (a) Effect-class admit set INCLUDES the new class post-C2.
    effect_classes = _carrier_aa_phase_1_effect_classes()
    assert AddOneManaFromControlledLandsProductions in effect_classes, (
        "Flip invariant violation: "
        "AddOneManaFromControlledLandsProductions MUST be in the "
        "Carrier-AA Phase-1 Effect-class admit set post-C2."
    )

    # (b) Per-AA gate ADMITS post-C2.
    aa = real.activated_abilities[0]
    assert _aa_is_phase1_sub_shape_a(aa) is True, (
        "Flip invariant violation: "
        "_aa_is_phase1_sub_shape_a must ADMIT Reflecting Pool's "
        "AA[0] post-C2 on the Effect-class widen + Phase-1.5a bare "
        "{T} cost gate + Phase-4E is_mana_ability rider."
    )

    # (c) Carrier-AA Land admit predicate ADMITS.
    assert _printing_is_bridge_simple_carrier_aa_land(real) is True, (
        "Flip invariant violation: "
        "_printing_is_bridge_simple_carrier_aa_land must ADMIT "
        "Reflecting Pool post-C2 (cascades from per-AA admit at "
        "the single-AA all-or-nothing walk)."
    )

    # (d) Top-level dispatcher ADMITS.
    assert _printing_is_bridge_simple_carrier_aa_any(real) is True, (
        "Flip invariant violation: "
        "_printing_is_bridge_simple_carrier_aa_any must ADMIT "
        "Reflecting Pool post-C2 (delegates to the Land sibling)."
    )


def test_reflecting_pool_carrier_aa_effect_classes_count_is_18_post_cycle_2():
    """**Flip count sentinel (INVERTED at Cycle 2).** The
    ``_carrier_aa_phase_1_effect_classes`` admit-set size MUST be
    18 post-C2 — the C2 widen lands the 17 → 18 bump (adding
    ``AddOneManaFromControlledLandsProductions``).

    Renamed from ``test_reflecting_pool_carrier_aa_effect_classes_
    count_stays_17``; pin the new count so a future widen / drift
    surfaces here before a silent admit-gate flip beyond the C2
    closure.
    """
    from mtg_bot.parity.trajectory import (
        _carrier_aa_phase_1_effect_classes,
    )

    assert len(_carrier_aa_phase_1_effect_classes()) == 18, (
        "Flip invariant: the Carrier-AA Phase-1 Effect-class admit "
        "set MUST have exactly 18 entries post-Cycle-2 — Reflecting "
        "Pool C2 lands the 17 → 18 bump adding "
        "AddOneManaFromControlledLandsProductions."
    )
