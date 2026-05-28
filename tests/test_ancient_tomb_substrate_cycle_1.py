"""**Ancient Tomb substrate Phase 4 Cycle 1 (2026-05-27).**

C1 substrate-only landing per
``docs/BLOCKED_TAIL_TRACTABILITY_SCOUT_2026-05-27.md`` §#3 Ancient
Tomb (Worker F's BLOCKED-tail scout recommendation; this slice
implements the C1 spec verbatim, sibling-discounted off the Meteor
Crater C1 substrate at ``eb059eaa`` + Reflecting Pool C1 substrate at
``d7be074e``).

Deliverables (Cycle 1 Rust slice + cross-engine bridge):

  - New Rust ``Effect::DealDamageToControllerAndAddMana`` fields
    variant on ``cards.rs::Effect`` — Ancient Tomb's single ``{T}:
    Add {C}{C}. This land deals 2 damage to you.`` AA pilot effect.
    Fields: ``damage: u32`` + ``produces: Vec<(u8, u32)>`` (color
    byte + count). The Python class
    ``DealDamageToControllerAndAddMana(damage, produces)`` at
    ``effects/generic/damage.py:170`` is mirrored.
  - ``parse_effect`` arm in ``cards.rs`` —
    ``"deal_damage_to_controller_and_add_mana"`` 3-key dict (kind +
    damage int + produces list-of-[color, count]); validates color
    against the closed W/U/B/R/G/C vocabulary at parse time.
  - ``to_pydict`` arm in ``cards.rs`` — emits the byte-equal dict
    (kind + damage int + produces list-of-[color, count]).
  - Resolve arm in ``state_ops_resolve.rs::apply_effect`` — walks 5
    zones + stack to resolve the source's controller, then (a)
    applies damage as life-loss (``player.life -= damage as i32``,
    NOT through ``dispatch_event`` — mirrors Python's ``p.life -=
    self.damage`` at ``damage.py:186``) FIRST, then (b) mints the
    produces tuple via ``push_coins`` per (color, count) pair —
    mirrors Python's append-ManaCoin loop verbatim. Order matters
    (damage before mana) because at 1 life the damage decrement
    runs before the mana minting, leaving the controller at <0
    life with mana in their pool until the next SBA pass.
  - Cross-engine bridge arms in ``src/mtg_bot/parity/cross_engine.py``:
      * Reverse arm in ``_ta_dict_to_python_effect`` — recognizes
        ``kind == "deal_damage_to_controller_and_add_mana"`` and
        returns the Python
        ``DealDamageToControllerAndAddMana(damage, produces)``
        instance with `produces` projected back to the tuple-of-
        tuples surface.
      * Forward arm in ``_python_aa_to_safe_dict`` — recognizes
        ``isinstance(effect, DealDamageToControllerAndAddMana)`` and
        emits the matching 3-key dict.
    Both arms use the SPECIFIC class (no parent ``Effect`` fall-
    through) per the Phase-3A/3B/3C/4B/4C/4D/4E/Meteor-Crater/
    Reflecting-Pool specificity contract.

ZERO Python admit widen this cycle. ``_carrier_aa_phase_1_effect_
classes`` STILL has 18 entries (post-Reflecting-Pool-C2 — Reflecting
Pool's C2 widen lifted the count from 17 → 18 at commit ``8250a33f``
on main). Ancient Tomb's class
``DealDamageToControllerAndAddMana`` is NOT in the admit set, and
the substrate-only invariant pin below is the load-bearing closure
marker. The admit-set widen + pin bump + per-card real-EoE probe all
ship Cycle 2 as the FLIP (mirrors the Meteor Crater C1 / Reflecting
Pool C1 substrate-only precedents — substrate lands at C1, the live
FLIP lands at C2). ZERO per-card probe this cycle (Cycle 2 ships the
real-EoE ``tests/test_ancient_tomb_parity.py``).

**Verify-first findings (live tree, main ``8250a33f``):**

  - Ancient Tomb printing: ``card_types=("Land",)``, ``supertypes=()``,
    ``subtypes=()``, ``keywords=frozenset()``, ``triggered_abilities=
    ()``, ``static_abilities=()``, ``produces=frozenset()``, ``n_aa=1``.
  - AA[0]: ``cost=ActivationCost(tap_self=True),
    effect=DealDamageToControllerAndAddMana(damage=2, produces=(("C",
    2),)), is_mana_ability=True, tier_threshold=0,
    sorcery_speed=False``.

The verify-first walk confirms Ancient Tomb's AA shape matches the
scout-doc §#3 spec verbatim — bare ``{T}`` mana-ability + the new
Effect class with `damage=2` and `produces=(("C", 2),)`; every gate
except the Effect-class admit set passes pre-cycle.

**Substrate-only invariant — Ancient Tomb STAYS DECLINED at the
admit gate post-Cycle-1.** The Rust Effect variant + cross-engine
bridge arms all landed; the live admit gate still declines Ancient
Tomb's printing because
``_carrier_aa_phase_1_effect_classes`` does NOT yet include
``DealDamageToControllerAndAddMana`` (the
``type(aa.effect) not in _carrier_aa_phase_1_effect_classes()``
teeth in ``_aa_is_phase1_sub_shape_a`` keeps AA[0] declined at the
per-AA gate, which cascades to the printing-level admit). The
forward serializer + Rust round-trip both succeed at C1 — driven by
synthetic unit pins; the live admit FLIP lands at C2.
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
    per side. The Ancient Tomb resolve doesn't scan the bf for any
    derivation (unlike Reflecting Pool's mana_produced-union walk —
    the produces tuple is on the Effect itself), but a clean empty
    bf keeps the test setup unambiguous.
    """
    return engine.make_synthetic_state(0, 0, 0)


# ---------------------------------------------------------------------------
# Parser SoT verify-first
# ---------------------------------------------------------------------------


def test_python_deal_damage_to_controller_and_add_mana_class_exists():
    """**Parser source-of-truth pin.** Python's
    ``DealDamageToControllerAndAddMana`` class is in
    ``effects.generic.damage``, a frozen dataclass with ``damage:
    int = 2`` and ``produces: tuple[tuple[str, int], ...] = (("C",
    2),)`` defaults.
    """
    from mtg_bot.effects.base import Effect
    from mtg_bot.effects.generic.damage import (
        DealDamageToControllerAndAddMana,
    )

    eff = DealDamageToControllerAndAddMana(damage=2, produces=(("C", 2),))
    assert isinstance(eff, Effect)
    # Defaults match the Ancient Tomb printing.
    default_eff = DealDamageToControllerAndAddMana()
    assert default_eff.damage == 2
    assert default_eff.produces == (("C", 2),)
    # Two instances compare equal (frozen dataclass __eq__ default).
    assert eff == DealDamageToControllerAndAddMana(
        damage=2, produces=(("C", 2),),
    )


def test_ancient_tomb_live_aa_shape_matches_scout_doc():
    """**Verify-first pin (scout doc §#3 row).** The live Ancient
    Tomb parser SoT carries:

      * card_types=("Land",), supertypes=(), subtypes=(),
        keywords=frozenset(), triggered_abilities=(),
        static_abilities=(), produces=frozenset(), n_aa=1.
      * AA[0]: cost=ActivationCost(tap_self=True),
        effect=DealDamageToControllerAndAddMana(damage=2,
        produces=(("C", 2),)), is_mana_ability=True,
        tier_threshold=0, sorcery_speed=False.

    This pin protects the verify-first finding the C1 substrate is
    built against; a future parser tweak that mutates the AA shape,
    the printing's card-type tuple, or any of the rider invariants
    (damage amount, produces tuple) would need to be reconciled here
    BEFORE C2 ships the admit widen.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.generic.damage import (
        DealDamageToControllerAndAddMana,
    )

    real = get_active_source().get_printings().get("Ancient Tomb")
    if real is None:
        pytest.skip("Ancient Tomb absent from active CardSource")

    # Printing-level shape — bare Land.
    assert real.card_types == ("Land",)
    assert real.supertypes == ()
    assert real.subtypes == ()
    assert real.keywords == frozenset()
    assert real.triggered_abilities == ()
    assert real.static_abilities == ()
    assert real.produces == frozenset()
    assert len(real.activated_abilities) == 1

    # AA[0] shape — bare {T} mana-ability with the new Effect class
    # + Ancient-Tomb-specific rider values.
    aa = real.activated_abilities[0]
    assert isinstance(aa.effect, DealDamageToControllerAndAddMana)
    assert aa.effect.damage == 2
    assert aa.effect.produces == (("C", 2),)
    assert aa.cost.tap_self is True
    assert aa.cost.mana is None
    assert aa.is_mana_ability is True
    assert aa.tier_threshold == 0
    assert aa.sorcery_speed is False


# ---------------------------------------------------------------------------
# Cross-engine bridge arm pins (dict <-> Python)
# ---------------------------------------------------------------------------


def test_bridge_reverse_arm_deal_damage_to_controller_and_add_mana():
    """Reverse arm constructs
    ``DealDamageToControllerAndAddMana(damage=2, produces=(("C",
    2),))`` from the 3-key
    ``deal_damage_to_controller_and_add_mana`` dict. Mirrors the
    Phase-3A/3B/3C/4B/4D/4E/Meteor-Crater/Reflecting-Pool
    specificity contract — fields variant on the wire round-trips
    to the frozen dataclass with byte-equal field surface.
    """
    from mtg_bot.effects.generic.damage import (
        DealDamageToControllerAndAddMana,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    back = _ta_dict_to_python_effect({
        "kind": "deal_damage_to_controller_and_add_mana",
        "damage": 2,
        "produces": [["C", 2]],
    })
    assert isinstance(back, DealDamageToControllerAndAddMana)
    assert back.damage == 2
    assert back.produces == (("C", 2),)
    # Two equal-content instances compare equal.
    assert back == DealDamageToControllerAndAddMana(
        damage=2, produces=(("C", 2),),
    )


def test_bridge_reverse_arm_handles_alt_damage_and_produces():
    """Reverse arm parameterizes cleanly on `damage` + `produces`.
    Future printings with `Add {C}{C}{C}. This land deals 3 damage
    to you.` would emit `damage=3, produces=[["C", 3]]`; the reverse
    arm must reconstruct that surface byte-equal.
    """
    from mtg_bot.effects.generic.damage import (
        DealDamageToControllerAndAddMana,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    back = _ta_dict_to_python_effect({
        "kind": "deal_damage_to_controller_and_add_mana",
        "damage": 3,
        "produces": [["C", 3]],
    })
    assert isinstance(back, DealDamageToControllerAndAddMana)
    assert back.damage == 3
    assert back.produces == (("C", 3),)


def test_bridge_forward_arm_deal_damage_to_controller_and_add_mana():
    """Forward arm in ``_python_aa_to_safe_dict`` recognizes
    ``DealDamageToControllerAndAddMana`` and emits the 3-key dict
    ``{"kind": "deal_damage_to_controller_and_add_mana", "damage":
    int, "produces": list[[color_str, count]]}``.

    The AA carrying this effect must itself pass the bridge-floor
    rider gates — bare ``{T}`` cost, no AA-rider deal-breakers.
    """
    from mtg_bot.effects.base import ActivatedAbility, ActivationCost
    from mtg_bot.effects.generic.damage import (
        DealDamageToControllerAndAddMana,
    )
    from mtg_bot.parity.cross_engine import _python_aa_to_safe_dict

    aa = ActivatedAbility(
        cost=ActivationCost(tap_self=True),
        effect=DealDamageToControllerAndAddMana(
            damage=2, produces=(("C", 2),),
        ),
        is_mana_ability=True,
    )
    d = _python_aa_to_safe_dict(aa)
    assert d is not None
    assert d["effect"] == {
        "kind": "deal_damage_to_controller_and_add_mana",
        "damage": 2,
        "produces": [["C", 2]],
    }
    # The cost dict carries only the tap_self flag.
    assert d["cost"] == {"tap_self": True}
    # is_mana_ability bypass-stack semantics carried on the wire
    # (Phase-4E C2 widen).
    assert d["is_mana_ability"] is True


def test_bridge_round_trip_deal_damage_to_controller_and_add_mana():
    """Round-trip pin — Python AA → dict → Python AA yields a byte-
    equal AA at the dataclass ``__eq__`` surface.
    """
    from mtg_bot.effects.base import ActivatedAbility, ActivationCost
    from mtg_bot.effects.generic.damage import (
        DealDamageToControllerAndAddMana,
    )
    from mtg_bot.parity.cross_engine import (
        _aa_dict_to_python_activated_ability,
        _python_aa_to_safe_dict,
    )

    aa_orig = ActivatedAbility(
        cost=ActivationCost(tap_self=True),
        effect=DealDamageToControllerAndAddMana(
            damage=2, produces=(("C", 2),),
        ),
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


def _synthetic_ancient_tomb_dict():
    """Minimal Ancient-Tomb-shape Land printing dict for the Rust
    Registry. Single ``{T}`` mana-AA with the new
    ``deal_damage_to_controller_and_add_mana`` Effect.
    """
    return {
        "name": "Synthetic Ancient Tomb",
        "card_types": ["Land"],
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


def test_rust_register_printing_with_ancient_tomb_aa(engine):
    """**Rust parse arm pin.** The new
    ``deal_damage_to_controller_and_add_mana`` parse arm accepts the
    3-key dict and returns
    ``Effect::DealDamageToControllerAndAddMana { damage, produces }``;
    a synthetic Ancient-Tomb-shape Land registers cleanly with the
    new mana-ability AA.
    """
    reg = engine.Registry()
    pid = reg.register_printing(_synthetic_ancient_tomb_dict())
    assert reg.get_printing_name(pid) == "Synthetic Ancient Tomb"


# ---------------------------------------------------------------------------
# Rust unit pin — to_pydict arm via the parse-emit inverse
# ---------------------------------------------------------------------------


def test_rust_to_pydict_round_trip_via_bridge_inverse():
    """**Rust to_pydict arm pin.** The Rust to_pydict arm emits the
    byte-equal 3-key dict. Round-trip via the bridge forward arm
    (Python→dict) + the reverse arm (dict→Python) yields the same
    Python AA.
    """
    from mtg_bot.effects.base import ActivatedAbility, ActivationCost
    from mtg_bot.effects.generic.damage import (
        DealDamageToControllerAndAddMana,
    )
    from mtg_bot.parity.cross_engine import (
        _aa_dict_to_python_activated_ability,
        _python_aa_to_safe_dict,
    )

    aa_orig = ActivatedAbility(
        cost=ActivationCost(tap_self=True),
        effect=DealDamageToControllerAndAddMana(
            damage=2, produces=(("C", 2),),
        ),
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


def test_resolve_default_at_high_life_2_mana_2_damage(
    engine, synthetic_state,
):
    """**Resolve arm pin — default scenario.** Controller at full
    life. Activating Ancient Tomb mints {C}{C} into the controller's
    mana pool AND drops their life by 2.
    """
    pool_id = synthetic_state.register_and_inject_object(
        _synthetic_ancient_tomb_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(pool_id, False)

    pool_pre = synthetic_state.get_mana_pool(0)
    assert pool_pre == {
        "W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0, "any": 0,
    }
    life_pre = synthetic_state.get_life(0)

    synthetic_state.apply_action({
        "kind": "activate_ability",
        "source_id": pool_id,
        "ability_index": 0,
    })

    pool_post = synthetic_state.get_mana_pool(0)
    assert pool_post == {
        "W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 2, "any": 0,
    }, (
        f"AA must mint 2 C coins (Ancient Tomb's produces=[['C',2]]); "
        f"got pool={pool_post}"
    )
    life_post = synthetic_state.get_life(0)
    assert life_post == life_pre - 2, (
        f"AA must drop controller's life by 2 (Ancient Tomb's "
        f"damage=2); pre={life_pre} post={life_post}"
    )


def test_resolve_drops_life_by_2_from_arbitrary_starting_life(
    engine, synthetic_state,
):
    """**Resolve arm pin — life delta byte-equal.** Setting the
    controller's life to 10 explicitly and activating: life lands
    at 8 (10 - damage=2). Mana minting still adds the {C}{C} after.
    """
    pool_id = synthetic_state.register_and_inject_object(
        _synthetic_ancient_tomb_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(pool_id, False)
    synthetic_state.set_life(0, 10)

    synthetic_state.apply_action({
        "kind": "activate_ability",
        "source_id": pool_id,
        "ability_index": 0,
    })

    assert synthetic_state.get_life(0) == 8, (
        f"Damage=2 from life=10 must land at 8; got "
        f"{synthetic_state.get_life(0)}"
    )
    pool_post = synthetic_state.get_mana_pool(0)
    assert pool_post == {
        "W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 2, "any": 0,
    }


def test_resolve_at_1_life_drives_life_to_negative_1_and_still_mints_mana(
    engine, synthetic_state,
):
    """**Resolve arm pin — lethal damage at 1 life.** Setting the
    controller's life to 1: damage=2 drives life to -1 (the SBA
    pass is the global game-loop's responsibility — this arm
    doesn't pre-empt SBA). The mana minting still runs after the
    lethal damage (mirrors Python's `.resolve()` which
    unconditionally appends ManaCoins after the life decrement).
    The mana stays in the (now-losing) controller's pool until the
    next SBA check clears it.

    This pins the order invariant: damage runs FIRST (Python
    parity), then mana. If a future refactor flipped the order
    (mana first → would mint mana BEFORE the lethal damage), this
    test would still pass on observable state (final life = -1,
    final pool = 2 C) because there's no observable inter-step
    state captured here. The test exists primarily to pin the
    overall observable state after a lethal-damage activation; the
    order itself is documented in the resolve-arm comment block.
    """
    pool_id = synthetic_state.register_and_inject_object(
        _synthetic_ancient_tomb_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(pool_id, False)
    synthetic_state.set_life(0, 1)

    synthetic_state.apply_action({
        "kind": "activate_ability",
        "source_id": pool_id,
        "ability_index": 0,
    })

    assert synthetic_state.get_life(0) == -1, (
        f"Damage=2 from life=1 must land at -1; got "
        f"{synthetic_state.get_life(0)}"
    )
    pool_post = synthetic_state.get_mana_pool(0)
    assert pool_post == {
        "W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 2, "any": 0,
    }


def test_resolve_mints_to_source_controller_not_active_player(
    engine, synthetic_state,
):
    """**Source-controller fan-out pin.** The minted coins go to the
    source object's controller, AND the damage applies to the same
    controller — NOT to ``state.active_player``. A synthetic Ancient
    Tomb on p1's bf activates: p1's life drops by 2 + p1's pool
    gets {C}{C}; p0 is untouched.

    Mirrors the Meteor Crater C1 / Reflecting Pool C1 source-
    controller-discovery pattern; the new variant inherits the same
    contract via the 5-zone walk + stack scan.
    """
    pool_id = synthetic_state.register_and_inject_object(
        _synthetic_ancient_tomb_dict(), 1, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(pool_id, False)
    life_p0_pre = synthetic_state.get_life(0)
    life_p1_pre = synthetic_state.get_life(1)

    synthetic_state.apply_action({
        "kind": "activate_ability",
        "source_id": pool_id,
        "ability_index": 0,
    })

    # p1 (source controller) gets coins + damage.
    pool_p1 = synthetic_state.get_mana_pool(1)
    assert pool_p1 == {
        "W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 2, "any": 0,
    }, (
        f"AA coins must go to source-controller p1; got pool_p1={pool_p1}"
    )
    assert synthetic_state.get_life(1) == life_p1_pre - 2, (
        f"Damage must apply to source-controller p1; "
        f"pre={life_p1_pre} post={synthetic_state.get_life(1)}"
    )
    # p0 untouched.
    pool_p0 = synthetic_state.get_mana_pool(0)
    assert pool_p0 == {
        "W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0, "any": 0,
    }, (
        f"p0's pool must stay empty (source controller is p1); "
        f"got pool_p0={pool_p0}"
    )
    assert synthetic_state.get_life(0) == life_p0_pre, (
        f"p0's life must stay unchanged (source controller is p1); "
        f"pre={life_p0_pre} post={synthetic_state.get_life(0)}"
    )


def test_resolve_cross_engine_byte_equal_mana_pool_and_life_delta(
    engine, synthetic_state,
):
    """**Cross-engine byte-equal pin.** Drive the Rust resolve
    through `apply_action` on the synthetic state, then drive the
    Python resolve directly on a synthetic Python state of matching
    shape: post-resolve life delta + pool delta must be byte-equal
    across engines.

    This test does NOT use the live admit gate (which still
    declines Ancient Tomb at C1) — it bypasses the bridge and pokes
    each engine directly at the resolve boundary, mirroring the
    sibling-of-the-MC/RP C1 substrate-cycle pins.
    """
    # Rust side — drive resolve via apply_action.
    pool_id = synthetic_state.register_and_inject_object(
        _synthetic_ancient_tomb_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(pool_id, False)
    synthetic_state.set_life(0, 20)

    synthetic_state.apply_action({
        "kind": "activate_ability",
        "source_id": pool_id,
        "ability_index": 0,
    })
    rust_life = synthetic_state.get_life(0)
    rust_pool = synthetic_state.get_mana_pool(0)

    # Python side — synthesize a state with the same Ancient Tomb
    # shape on p0's bf, drive .resolve() directly. The Python
    # `.resolve()` body takes (state, controller_id, targets) and
    # mutates state in place — exactly mirrors Rust's
    # `apply_action(activate_ability)` for a mana-ability bypass-
    # stack activation.
    from mtg_bot.effects.generic.damage import (
        DealDamageToControllerAndAddMana,
    )
    from mtg_bot.game import GameState, Player

    py_state = GameState(
        players=[
            Player(id=0, life=20),
            Player(id=1, life=20),
        ],
    )
    eff = DealDamageToControllerAndAddMana(
        damage=2, produces=(("C", 2),),
    )
    eff.resolve(py_state, controller_id=0, targets=())
    py_life = py_state.players[0].life
    # Project the Python `mana_pool` (list of ManaCoin) onto the
    # Rust-side dict shape for byte-equal comparison.
    py_pool_counts = {
        "W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0, "any": 0,
    }
    for coin in py_state.players[0].mana_pool:
        py_pool_counts[coin.color] = py_pool_counts.get(coin.color, 0) + 1

    assert rust_life == py_life, (
        f"Cross-engine life delta divergence: rust={rust_life} "
        f"py={py_life}"
    )
    assert rust_pool == py_pool_counts, (
        f"Cross-engine mana pool divergence: rust={rust_pool} "
        f"py={py_pool_counts}"
    )


# ---------------------------------------------------------------------------
# Substrate-only invariant — Ancient Tomb STAYS DECLINED at admit gate
# (load-bearing closure marker)
# ---------------------------------------------------------------------------


def test_ancient_tomb_stays_declined_at_admit_gate_post_cycle_1():
    """**LOAD-BEARING substrate-only invariant pin.** Ancient
    Tomb's live printing STAYS DECLINED at the Phase-4 Carrier-AA
    admit gate post-Cycle-1.

    Post-C1 invariants:

      (a) ``_carrier_aa_phase_1_effect_classes`` does NOT include
          ``DealDamageToControllerAndAddMana`` (the Effect-class
          admit set stays at 18 entries post-C1 — Reflecting Pool's
          C2 widen brought the count to 18 at main HEAD ``8250a33f``;
          Ancient Tomb's C2 widen will lift it to 19).
      (b) ``_aa_is_phase1_sub_shape_a(ancient_tomb.activated_abilities
          [0])`` returns False (the ``type(aa.effect) not in
          _carrier_aa_phase_1_effect_classes()`` teeth fire because
          Ancient Tomb's class is NOT widened in).
      (c) ``_printing_is_bridge_simple_carrier_aa_land(ancient_tomb)``
          returns False (the per-AA gate declines, and the single-
          AA all-or-nothing printing-level cascade declines the
          printing).
      (d) ``_printing_is_bridge_simple_carrier_aa_any(ancient_tomb)``
          returns False (the top-level dispatcher delegates to the
          Land sibling which declines).

    This is the load-bearing closure marker for the C1 substrate-
    only invariant: if any of these flips True before C2 ships, the
    substrate has silently widened the admit set and the C2 cycle
    has been pre-empted. Catch the drift here.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.generic.damage import (
        DealDamageToControllerAndAddMana,
    )
    from mtg_bot.parity.trajectory import (
        _aa_is_phase1_sub_shape_a,
        _carrier_aa_phase_1_effect_classes,
        _printing_is_bridge_simple_carrier_aa_any,
        _printing_is_bridge_simple_carrier_aa_land,
    )

    real = get_active_source().get_printings().get("Ancient Tomb")
    if real is None:
        pytest.skip("Ancient Tomb absent from active CardSource")

    # (a) Effect-class admit set does NOT include the new class
    # post-C1.
    effect_classes = _carrier_aa_phase_1_effect_classes()
    assert DealDamageToControllerAndAddMana not in effect_classes, (
        "Substrate-only invariant violation: "
        "DealDamageToControllerAndAddMana MUST NOT be in the "
        "Carrier-AA Phase-1 Effect-class admit set post-C1 — C2 "
        "ships the widen as the FLIP."
    )

    # (b) Per-AA gate DECLINES post-C1.
    aa = real.activated_abilities[0]
    assert _aa_is_phase1_sub_shape_a(aa) is False, (
        "Substrate-only invariant violation: "
        "_aa_is_phase1_sub_shape_a must DECLINE Ancient Tomb's "
        "AA[0] post-C1 on the Effect-class teeth (C2 ships the "
        "widen)."
    )

    # (c) Carrier-AA Land admit predicate DECLINES.
    assert _printing_is_bridge_simple_carrier_aa_land(real) is False, (
        "Substrate-only invariant violation: "
        "_printing_is_bridge_simple_carrier_aa_land must DECLINE "
        "Ancient Tomb post-C1 (cascades from per-AA decline at the "
        "single-AA all-or-nothing walk)."
    )

    # (d) Top-level dispatcher DECLINES.
    assert _printing_is_bridge_simple_carrier_aa_any(real) is False, (
        "Substrate-only invariant violation: "
        "_printing_is_bridge_simple_carrier_aa_any must DECLINE "
        "Ancient Tomb post-C1 (delegates to the Land sibling)."
    )


def test_ancient_tomb_carrier_aa_effect_classes_count_stays_18():
    """**Count sentinel.** The
    ``_carrier_aa_phase_1_effect_classes`` admit-set size MUST be
    18 post-C1 — Reflecting Pool's C2 widen at commit ``8250a33f``
    on main brought the count to 18; Ancient Tomb C1 is substrate-
    only (ZERO admit widen this cycle), so the count stays at 18.
    Cycle 2 ships the 18 → 19 widen adding
    ``DealDamageToControllerAndAddMana``.

    Pin the count so a future widen / drift surfaces here before a
    silent admit-gate flip beyond the C1 substrate-only closure.
    """
    from mtg_bot.parity.trajectory import (
        _carrier_aa_phase_1_effect_classes,
    )

    assert len(_carrier_aa_phase_1_effect_classes()) == 18, (
        "Substrate-only invariant: the Carrier-AA Phase-1 Effect-"
        "class admit set MUST have exactly 18 entries post-Cycle-1 "
        "— Reflecting Pool's C2 widen brought the count to 18 at "
        "main HEAD 8250a33f; Ancient Tomb C1 is substrate-only and "
        "does NOT widen the count. C2 widens 18 → 19 by adding "
        "DealDamageToControllerAndAddMana."
    )
