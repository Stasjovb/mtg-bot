"""**Carrier-AA substrate Phase 3B Cycle 1 (2026-05-25).**

Tests for the Phase 3B Cycle 1 Rust substrate landing per
``docs/CARRIER_AA_SUBSTRATE_PHASE_3_DESIGN.md`` §4.2 (Rust spec) +
§5.3 (Python bridge spec) + §6.2 (test plan).

Deliverables (Cycle 1 Rust slice, per design doc §4.2):

  - New Rust ``Effect::ExileAllGraveyards`` variant on
    ``cards.rs::Effect`` (unit variant, no fields) — Scavenger
    Grounds's pilot effect (``{2}, {T}, Sacrifice a Desert: Exile
    all graveyards.``).
  - ``parse_effect`` arm in ``cards.rs`` — ``"exile_all_graveyards"``
    unit-variant; extra keys silently dropped (sibling of the Phase-
    2a/2b/3A unit-variant siblings).
  - ``to_pydict`` arm in ``cards.rs`` — emits ``{kind:
    "exile_all_graveyards"}``.
  - Resolve arm in ``state_ops_resolve.rs`` — walks every player's
    graveyard and moves every card into that same player's exile
    zone, stamping ``obj.zone = ZONE_EXILE``. No CR-400.7 zone-
    change resets (mirrors Python's resolve byte-equal).
  - Cross-engine bridge arms in ``cross_engine.py`` — forward emit
    (``_python_aa_to_safe_dict`` adds an ``ExileAllGraveyards`` arm)
    + reverse (``_ta_dict_to_python_effect`` adds an
    ``exile_all_graveyards`` arm).

ZERO new Rust cost-shape machinery — Scavenger Grounds's
``{2}, {T}, Sac-a-Desert:`` cost rides the existing
``ActivationCost.sacrifice_a_desert`` bool +
``parse_activation_cost`` arm + Desert-target fan-out +
cost-pay commit (all from the CE20 / Lander precedent). ZERO new
state field — ``ExileAllGraveyards`` is a zero-target mass effect
with no delayed-trigger payload.

This is a **substrate-only closure** — the cycle adds the new Rust
Effect variant + bridge plumbing as reusable infrastructure. The
pilot card (Scavenger Grounds) STAYS DECLINED at the production-deck
admit gate post-Cycle-1 because:

  (a) Python's admit predicate ``_aa_is_phase1_sub_shape_a``
      Effect-class gate doesn't yet include ``ExileAllGraveyards``
      in ``_carrier_aa_phase_1_effect_classes`` (Cycle 2 ships that
      widen, per design doc §5.1).
  (b) Python's admit predicate's cost-gate still strictly declines
      ``sacrifice_a_desert=True`` (Cycle 2 ships the cost-gate widen
      per design doc §5.3).

**Verify-first findings (live tree, main `143c95d7`):**

  - Scavenger Grounds's live oracle text: ``{2}, {T}, Sacrifice a
    Desert: Exile all graveyards.`` Confirmed via
    ``OracleParserCardSource``: ``card_types=('Land',)``,
    ``subtypes=('Desert',)``, ``power=toughness=None``, single
    non-mana AA with ``cost.tap_self=True``,
    ``cost.sacrifice_a_desert=True``, ``cost.mana=ManaCost(generic=2,
    ...)``, ``cost.sacrifice_self=False``, effect
    ``ExileAllGraveyards``, no riders.
  - Python's ``ExileAllGraveyards`` class at
    ``effects/generic/exile.py:661`` — frozen dataclass with no
    constructor args; the resolve method walks every player's
    graveyard and moves every card to that same player's exile,
    stamping ``c.zone = Zone.EXILE``. No other per-zone-change
    field resets.
  - Rust precedents: ``ActivationCost.sacrifice_a_desert`` at
    ``cards.rs:9943``; ``parse_activation_cost`` arm at
    ``cards.rs:16435``; Desert-target fan-out at
    ``state_ops_legal.rs:3522``; sacrifice cost-pay commit at
    ``state_ops_actions.rs:1287``. ``CardPrinting.subtypes:
    Vec<String>`` at ``cards.rs:10322``.

**Test plan (per design doc §6.2, Cycle 1 substrate-only slice):**

  - Parser SoT pin: confirm Python's ``ExileAllGraveyards`` class
    exists in ``effects.generic.exile`` and is a frozen unit
    variant.
  - Verify-first pin: confirm Scavenger Grounds's live AA shape
    (``{2}, {T}, Sac-a-Desert`` cost + ``ExileAllGraveyards``
    effect, no riders).
  - Rust unit pins: ``parse_effect`` arm via ``register_printing``
    round-trip + ``to_pydict`` arm via the bridge inverse + extra-
    keys-silently-dropped contract.
  - Cross-engine bridge pins: dict→Python reverse arm
    (``_ta_dict_to_python_effect``) + Python→dict forward arm
    (``_python_aa_to_safe_dict``) + symmetric round-trip via
    ``_aa_dict_to_python_activated_ability``.
  - Rust resolve arm pins: ``ExileAllGraveyards`` walks both
    graveyards into exile + empty-graveyard no-op + per-player-
    routing pin (cards stay with their owner).
  - Substrate-only invariant pins: Scavenger Grounds STAYS DECLINED
    at the admit gate + STAYS DECLINED at the production-deck
    loader filter post-Cycle-1 + ``_carrier_aa_phase_1_effect_
    classes`` UNCHANGED (5 entries, no ``ExileAllGraveyards``) +
    no-silent-auto-grow walk preserves the post-3A-C2 5-card admit
    set unchanged.
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
    per side. Mirrors the Phase-3A-C1 sibling shared fixture."""
    return engine.make_synthetic_state()


# ---------------------------------------------------------------------------
# Parser SoT verify-first
# ---------------------------------------------------------------------------


def test_python_exile_all_graveyards_class_exists():
    """**Parser source-of-truth pin.** Python's ``ExileAllGraveyards``
    class is in ``effects.generic.exile``, a frozen dataclass with no
    constructor args. Two zero-arg instances compare equal (frozen
    dataclass __eq__ default).
    """
    from mtg_bot.effects.base import Effect
    from mtg_bot.effects.generic.exile import ExileAllGraveyards

    eff = ExileAllGraveyards()
    assert isinstance(eff, Effect)
    assert eff == ExileAllGraveyards()


def test_scavenger_grounds_live_printing_matches_design_doc_shape():
    """**Verify-first pin — Scavenger Grounds's live AA shape.** Confirms
    the design doc §2.1 row at HEAD: ``Land — Desert``, single non-mana
    AA, cost ``tap_self=True`` AND ``sacrifice_a_desert=True`` AND
    ``mana=ManaCost(generic=2)``, effect ``ExileAllGraveyards``, no
    AA-level riders.

    NOTE: the live shape's ``mana={"generic": 2}`` passes the Phase
    1.5a ``{N}, {T}`` cost gate. Scavenger Grounds STAYS DECLINED at
    the admit gate post-Cycle-1 because:
      (a) The Effect-class admit set
          ``_carrier_aa_phase_1_effect_classes`` does NOT yet include
          ``ExileAllGraveyards`` (C2 ships that widen).
      (b) The cost-gate strictly declines ``sacrifice_a_desert=True``
          (C2 ships the cost-gate widen).
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.effects.generic.exile import ExileAllGraveyards

    ps = OracleParserCardSource().get_printings()
    sg = ps["Scavenger Grounds"]

    assert sg.card_types == ("Land",)
    assert sg.subtypes == ("Desert",)
    assert sg.supertypes == ()
    assert sg.power is None and sg.toughness is None

    aas = [
        aa for aa in (sg.activated_abilities or ())
        if not aa.is_mana_ability
    ]
    assert len(aas) == 1, (
        f"expected 1 non-mana AA on Scavenger Grounds, got {len(aas)}: "
        f"{aas}"
    )
    aa = aas[0]

    cost = aa.cost
    assert cost.tap_self is True
    assert cost.sacrifice_a_desert is True
    assert cost.sacrifice_self is False
    assert cost.mana is not None
    # generic-only {2} mana (no colored / hybrid / X)
    assert cost.mana.generic == 2
    assert cost.mana.colored == ()
    assert cost.mana.hybrid == ()
    assert cost.mana.x_pips == 0
    assert isinstance(aa.effect, ExileAllGraveyards)

    # No AA-level riders (verify-first contract).
    assert aa.is_mana_ability is False
    assert aa.sorcery_speed is False
    assert aa.activate_only_once is False
    assert aa.tier_threshold == 0
    assert aa.room_half is None
    assert aa.cost_reductions == ()


# ---------------------------------------------------------------------------
# Cross-engine bridge arm pins (dict <-> Python)
# ---------------------------------------------------------------------------


def test_bridge_arm_exile_all_graveyards():
    """Bridge arm constructs ``ExileAllGraveyards()`` from a single-key
    dict (no fields)."""
    from mtg_bot.effects.generic.exile import ExileAllGraveyards
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    back = _ta_dict_to_python_effect({"kind": "exile_all_graveyards"})
    assert isinstance(back, ExileAllGraveyards)


def test_bridge_arm_exile_all_graveyards_extra_keys_ignored():
    """Bridge arm silently ignores extra dict keys (unit-variant contract;
    mirrors the Rust ``parse_effect`` extra-keys-silently-dropped
    convention).
    """
    from mtg_bot.effects.generic.exile import ExileAllGraveyards
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    back = _ta_dict_to_python_effect({
        "kind": "exile_all_graveyards",
        "spurious_field": 99,
    })
    assert isinstance(back, ExileAllGraveyards)


def test_python_aa_to_safe_dict_forward_arm_round_trips_scavenger_grounds_shape():
    """**Forward emit pin.** A synthetic Scavenger-Grounds-shape
    ``ActivatedAbility`` serializes through ``_python_aa_to_safe_dict``
    to a dict carrying:

      * ``cost``: ``{"tap_self": True, "sacrifice_a_desert": True,
                     "mana": {"generic": 2}}``
      * ``effect``: ``{"kind": "exile_all_graveyards"}``

    Cycle-1 substrate-only: this round-trip succeeds, but
    ``_aa_is_phase1_sub_shape_a`` still declines Scavenger Grounds's
    AA on BOTH the Effect-class gate AND the cost-gate (C2 ships
    both widens).
    """
    from mtg_bot.effects.base import ActivatedAbility, ActivationCost
    from mtg_bot.effects.generic.exile import ExileAllGraveyards
    from mtg_bot.cards.base import ManaCost
    from mtg_bot.parity.cross_engine import (
        _aa_dict_to_python_activated_ability,
        _python_aa_to_safe_dict,
    )

    aa = ActivatedAbility(
        cost=ActivationCost(
            tap_self=True,
            sacrifice_a_desert=True,
            mana=ManaCost(generic=2),
        ),
        effect=ExileAllGraveyards(),
    )
    d = _python_aa_to_safe_dict(aa)
    assert d is not None, (
        "Scavenger Grounds AA shape must round-trip through the bridge "
        "floor — Cycle 1 widens the forward emit even though the "
        "admit predicate keeps it DECLINED."
    )
    assert d["cost"]["tap_self"] is True
    assert d["cost"]["sacrifice_a_desert"] is True
    assert d["cost"]["mana"] == {"generic": 2}
    assert d["effect"] == {"kind": "exile_all_graveyards"}
    # Reverse round-trip — byte-equal at the dataclass __eq__ surface.
    back = _aa_dict_to_python_activated_ability(d)
    assert back == aa


# ---------------------------------------------------------------------------
# Rust unit pins — parse + register
# ---------------------------------------------------------------------------


def test_rust_register_carrier_aa_scavenger_grounds_shape():
    """**Rust parse arm pin.** ``register_printing`` accepts a non-token
    Land carrier with ``subtypes=["Desert"]`` and an
    ``activated_abilities=[{cost: {tap_self: True, sacrifice_a_desert:
    True, mana: {generic: 2}}, effect: {kind: exile_all_graveyards}}]``.
    The pid is returned and ``get_printing_name`` echoes the name.
    """
    _require_engine()
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing({
        "name": "Test Scavenger Grounds",
        "card_types": ["Land"],
        "subtypes": ["Desert"],
        "mana_cost": {},
        "activated_abilities": [
            {
                "cost": {
                    "tap_self": True,
                    "sacrifice_a_desert": True,
                    "mana": {"generic": 2},
                },
                "effect": {"kind": "exile_all_graveyards"},
            }
        ],
    })
    assert reg.get_printing_name(pid) == "Test Scavenger Grounds"
    assert reg.get_printing_subtypes(pid) == ["Desert"]


def test_rust_register_exile_all_graveyards_extra_dict_keys_silently_dropped():
    """Unit-variant contract: ``exile_all_graveyards`` parse arm silently
    drops extra dict keys (no field validation; sibling of the
    Phase-2a/2b/3A unit-variant parse arms).
    """
    _require_engine()
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing({
        "name": "Test SG With Extras",
        "card_types": ["Land"],
        "subtypes": ["Desert"],
        "mana_cost": {},
        "activated_abilities": [
            {
                "cost": {
                    "tap_self": True,
                    "sacrifice_a_desert": True,
                    "mana": {"generic": 2},
                },
                "effect": {
                    "kind": "exile_all_graveyards",
                    "spurious_field": 42,
                },
            }
        ],
    })
    assert reg.get_printing_name(pid) == "Test SG With Extras"


# ---------------------------------------------------------------------------
# Rust resolve arm pins — ExileAllGraveyards walks every graveyard
# ---------------------------------------------------------------------------


def _synthetic_scavenger_grounds_dict():
    """Minimal Scavenger-Grounds-shape Land — Desert printing dict for
    the Rust Registry."""
    return {
        "name": "Synthetic Scavenger Grounds",
        "card_types": ["Land"],
        "subtypes": ["Desert"],
        "mana_cost": {},
        "activated_abilities": [
            {
                "cost": {
                    "tap_self": True,
                    "sacrifice_a_desert": True,
                    "mana": {"generic": 2},
                },
                "effect": {"kind": "exile_all_graveyards"},
                "is_mana_ability": False,
            }
        ],
    }


def _synthetic_creature_card_dict(name="Test Creature"):
    """Minimal 2/2 Creature-shape dict — used to populate graveyards
    for the ExileAllGraveyards resolve-arm pins.
    """
    return {
        "name": name,
        "card_types": ["Creature"],
        "mana_cost": {"generic": 2},
        "power": 2,
        "toughness": 2,
    }


def test_resolve_exile_all_graveyards_walks_both_graveyards_into_exile(
    engine, synthetic_state,
):
    """**Phase 3B C1 resolve arm pin.** Populate p0's graveyard with
    two cards and p1's graveyard with three cards. Activate Scavenger
    Grounds's AA (cost: ``{2}, T, sac SG itself as the Desert``);
    resolve.

    Expected post-resolve:
      * p0's graveyard is empty.
      * p1's graveyard is empty.
      * p0's exile gained the two p0-graveyard cards.
      * p1's exile gained the three p1-graveyard cards.
      * Each card carries the OWNER's player_id (= the player whose
        graveyard it sat in — cards stay with their owner).
    """
    # Populate p0's graveyard (2 cards) + p1's graveyard (3 cards).
    p0_gy_ids = []
    for i in range(2):
        oid = synthetic_state.register_and_inject_object(
            _synthetic_creature_card_dict(f"p0 GY {i}"),
            0,  # controller / owner
            ZONE_GRAVEYARD,
        )
        p0_gy_ids.append(oid)
    p1_gy_ids = []
    for i in range(3):
        oid = synthetic_state.register_and_inject_object(
            _synthetic_creature_card_dict(f"p1 GY {i}"),
            1,
            ZONE_GRAVEYARD,
        )
        p1_gy_ids.append(oid)

    # Inject Scavenger Grounds on p0's bf (untapped, not summoning sick).
    sg_id = synthetic_state.register_and_inject_object(
        _synthetic_scavenger_grounds_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(sg_id, False)
    # Pay {2} mana.
    synthetic_state.add_mana(0, "C", 2)

    # Pre-state: both graveyards populated, exiles empty.
    p0_gy_pre = [o["id"] for o in synthetic_state.graveyard_snapshot(0)]
    p1_gy_pre = [o["id"] for o in synthetic_state.graveyard_snapshot(1)]
    p0_exile_pre = [o["id"] for o in synthetic_state.exile_snapshot(0)]
    p1_exile_pre = [o["id"] for o in synthetic_state.exile_snapshot(1)]
    assert sorted(p0_gy_pre) == sorted(p0_gy_ids), (
        f"Pre-state p0 graveyard {p0_gy_pre} should contain ids "
        f"{p0_gy_ids}"
    )
    assert sorted(p1_gy_pre) == sorted(p1_gy_ids)
    # NOTE: the synthetic state may seed a non-empty exile depending on
    # the make_synthetic_state defaults; we'll diff exiles by id-set
    # rather than absolute size.

    # Activate Scavenger Grounds's AA, sacrificing SG itself as the
    # Desert (lenient SELF-eligibility per the Lander precedent).
    synthetic_state.apply_action({
        "kind": "activate_ability",
        "source_id": sg_id,
        "ability_index": 0,
        "sacrifice_target_id": sg_id,
    })
    assert synthetic_state.stack_size() == 1

    # Resolve — fires the new Effect::ExileAllGraveyards arm.
    synthetic_state.resolve_top_of_stack()
    assert synthetic_state.is_stack_empty()

    # Post-state: both graveyards empty.
    p0_gy_post = [o["id"] for o in synthetic_state.graveyard_snapshot(0)]
    p1_gy_post = [o["id"] for o in synthetic_state.graveyard_snapshot(1)]
    assert p0_gy_post == [], (
        f"p0 graveyard must be empty post-Scavenger-Grounds-resolve; "
        f"got {p0_gy_post}"
    )
    assert p1_gy_post == [], (
        f"p1 graveyard must be empty post-Scavenger-Grounds-resolve; "
        f"got {p1_gy_post}"
    )

    # Per-player exile gained the corresponding graveyard cards.
    # (SG itself was sacrificed during cost-pay, so it's in p0's
    # graveyard? Actually sacrifice moves to graveyard, then
    # ExileAllGraveyards would exile it too. But sacrifice happens at
    # cost-pay BEFORE the AA goes on the stack — so SG is in p0's
    # graveyard at resolve time and gets exiled along with the others.)
    p0_exile_post_ids = {
        o["id"] for o in synthetic_state.exile_snapshot(0)
    }
    p1_exile_post_ids = {
        o["id"] for o in synthetic_state.exile_snapshot(1)
    }
    p0_exile_pre_ids = set(p0_exile_pre)
    p1_exile_pre_ids = set(p1_exile_pre)
    # p0's exile gained at least the 2 graveyard cards. SG may also
    # have landed in p0's graveyard via cost-pay and thus in p0's
    # exile after resolve — that's the desired byte-equal-with-Python
    # behavior.
    p0_new_exiles = p0_exile_post_ids - p0_exile_pre_ids
    p1_new_exiles = p1_exile_post_ids - p1_exile_pre_ids
    for oid in p0_gy_ids:
        assert oid in p0_new_exiles, (
            f"p0 graveyard card id={oid} should appear in p0's exile "
            f"post-resolve; got new p0 exile ids = {p0_new_exiles}"
        )
    for oid in p1_gy_ids:
        assert oid in p1_new_exiles, (
            f"p1 graveyard card id={oid} should appear in p1's exile "
            f"post-resolve; got new p1 exile ids = {p1_new_exiles}"
        )


def test_resolve_exile_all_graveyards_empty_graveyards_noop(
    engine, synthetic_state,
):
    """**Phase 3B C1 resolve arm pin — empty-graveyard no-op.** With
    BOTH players' graveyards empty (modulo the synthetic-state's
    default-seed), activating + resolving Scavenger Grounds's AA
    leaves both graveyards empty + does NOT mutate either exile
    beyond cost-pay residue.

    Mirrors Python's resolve byte-equal: ``for c in list(p.graveyard)``
    over an empty list is a no-op.
    """
    sg_id = synthetic_state.register_and_inject_object(
        _synthetic_scavenger_grounds_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(sg_id, False)
    synthetic_state.add_mana(0, "C", 2)

    # Pre-snapshot: capture each player's exile id-set.
    p0_exile_pre = {
        o["id"] for o in synthetic_state.exile_snapshot(0)
    }
    p1_exile_pre = {
        o["id"] for o in synthetic_state.exile_snapshot(1)
    }
    # We don't strictly require both graveyards to be empty pre-resolve
    # (synthetic state default), but we record the pre-state for the
    # post-resolve diff.
    p0_gy_pre = [o["id"] for o in synthetic_state.graveyard_snapshot(0)]
    p1_gy_pre = [o["id"] for o in synthetic_state.graveyard_snapshot(1)]

    synthetic_state.apply_action({
        "kind": "activate_ability",
        "source_id": sg_id,
        "ability_index": 0,
        "sacrifice_target_id": sg_id,
    })
    synthetic_state.resolve_top_of_stack()

    # Post-resolve: graveyards empty (the cost-paid SG is exiled too).
    p0_gy_post = [o["id"] for o in synthetic_state.graveyard_snapshot(0)]
    p1_gy_post = [o["id"] for o in synthetic_state.graveyard_snapshot(1)]
    assert p0_gy_post == [], (
        f"p0 graveyard must be empty post-resolve (empty pre + cost-"
        f"paid SG also exiled); got {p0_gy_post}, pre={p0_gy_pre}"
    )
    assert p1_gy_post == [], (
        f"p1 graveyard must be empty post-resolve; got {p1_gy_post}, "
        f"pre={p1_gy_pre}"
    )
    # New exile entries from the empty-graveyard pair: ONLY the cost-
    # paid SG itself (no other cards moved). It's in p0's exile (it
    # came from p0's graveyard after the sacrifice).
    p0_exile_post = {
        o["id"] for o in synthetic_state.exile_snapshot(0)
    }
    p1_exile_post = {
        o["id"] for o in synthetic_state.exile_snapshot(1)
    }
    p1_new = p1_exile_post - p1_exile_pre
    assert p1_new == set(), (
        f"p1's exile must not gain any cards (p1 had no graveyard "
        f"cards to exile); got new p1 exile ids = {p1_new}"
    )
    # p0's exile gains exactly the SG itself (the cost-paid sacrifice).
    p0_new = p0_exile_post - p0_exile_pre
    assert sg_id in p0_new, (
        f"p0's exile must include the cost-paid SG (id={sg_id}); "
        f"got new p0 exile ids = {p0_new}"
    )


def test_resolve_exile_all_graveyards_one_sided_graveyard(
    engine, synthetic_state,
):
    """**Phase 3B C1 resolve arm pin — one-sided graveyard.** With ONLY
    p1's graveyard populated (and p0's empty modulo the cost-paid SG),
    the resolve arm exiles ONLY p1's cards into p1's exile — p0's
    exile is untouched beyond the cost-pay residue.

    Pins the per-player routing invariant: cards stay with their owner
    (= the player whose graveyard they sat in).
    """
    # Populate ONLY p1's graveyard (2 cards).
    p1_gy_ids = []
    for i in range(2):
        oid = synthetic_state.register_and_inject_object(
            _synthetic_creature_card_dict(f"p1 GY only {i}"),
            1,
            ZONE_GRAVEYARD,
        )
        p1_gy_ids.append(oid)

    sg_id = synthetic_state.register_and_inject_object(
        _synthetic_scavenger_grounds_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(sg_id, False)
    synthetic_state.add_mana(0, "C", 2)

    p0_exile_pre = {o["id"] for o in synthetic_state.exile_snapshot(0)}
    p1_exile_pre = {o["id"] for o in synthetic_state.exile_snapshot(1)}

    synthetic_state.apply_action({
        "kind": "activate_ability",
        "source_id": sg_id,
        "ability_index": 0,
        "sacrifice_target_id": sg_id,
    })
    synthetic_state.resolve_top_of_stack()

    # p1's gy cards landed in p1's exile (NOT p0's exile).
    p0_exile_post = {o["id"] for o in synthetic_state.exile_snapshot(0)}
    p1_exile_post = {o["id"] for o in synthetic_state.exile_snapshot(1)}
    p1_new = p1_exile_post - p1_exile_pre
    p0_new = p0_exile_post - p0_exile_pre
    for oid in p1_gy_ids:
        assert oid in p1_new, (
            f"p1 graveyard card id={oid} must appear in p1's exile "
            f"(per-owner routing invariant); got p1 new exile = {p1_new}"
        )
        assert oid not in p0_new, (
            f"p1 graveyard card id={oid} must NOT appear in p0's exile "
            f"(cards stay with their owner); got p0 new exile = {p0_new}"
        )


# ---------------------------------------------------------------------------
# Phase 3B C2 invariant pins (INVERTED) — Scavenger Grounds NOW ADMITS
# ---------------------------------------------------------------------------


def test_scavenger_grounds_now_admits_post_cycle_2():
    """**Phase 3B C2 invariant pin (INVERTED).** Scavenger Grounds's
    live ``OracleParserCardSource`` printing PASSES
    :func:`_printing_is_bridge_simple_carrier_aa_land` post-Phase-3B-
    C2 because the combined Effect-class + cost-gate widen
    admits the live ``{2}, {T}, Sac-a-Desert: ExileAllGraveyards``
    shape end-to-end.

    The two C1-substrate-only declines are both lifted in C2:
      (a) The Effect-class admit set
          ``_carrier_aa_phase_1_effect_classes`` is widened to
          include ``ExileAllGraveyards`` (per design doc §5.1).
      (b) The cost-gate ``_aa_is_phase1_sub_shape_a`` removes the
          strict ``sacrifice_a_desert`` decline and replaces it with
          a defense-in-depth both-at-once guard
          (``sacrifice_a_desert and sacrifice_self`` — no live EoE
          carrier sets both; the guard exists for future-carrier
          safety) per design doc §5.3.

    Inverts the Phase-3B-C1 substrate-only pin
    ``test_scavenger_grounds_stays_declined_post_cycle_1``.
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity import trajectory as traj

    ps = OracleParserCardSource().get_printings()
    sg = ps["Scavenger Grounds"]
    assert traj._printing_is_bridge_simple_carrier_aa_land(sg) is True, (
        "Scavenger Grounds must ADMIT at the Carrier-AA admit gate "
        "post-Phase-3B-C2. The Effect-class admit set is widened to "
        "include ExileAllGraveyards AND the cost-gate accepts the "
        "{2}, {T}, Sac-a-Desert shape under the Phase-3B widen."
    )


def test_scavenger_grounds_now_passes_loader_filter():
    """**Phase 3B C2 invariant pin (INVERTED, loader-level).** The
    end-to-end production-deck loader filter ADMITS Scavenger Grounds
    post-Phase-3B-C2 — the Carrier-AA disjunct fires now that both
    the Effect-class admit set and the cost-gate are widened.

    Inverts the Phase-3B-C1 pin
    ``test_scavenger_grounds_stays_declined_at_loader_filter``.
    Mirrors the Phase-3A-C2 sibling pin
    ``test_mystifying_maze_now_passes_loader_filter``.
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import _filter_deck_to_bridge_supported

    ps = OracleParserCardSource().get_printings()
    assert "Scavenger Grounds" in ps
    filtered, card_defs = _filter_deck_to_bridge_supported(
        ["Scavenger Grounds"], ps,
    )
    assert filtered == ["Scavenger Grounds"], (
        f"Scavenger Grounds must PASS the loader filter post-Phase-"
        f"3B-C2; got filtered={filtered}, card_defs={card_defs}"
    )
    assert len(card_defs) == 1
    assert card_defs[0].name == "Scavenger Grounds"


def test_carrier_aa_phase_1_effect_classes_widened_post_phase_3b_c2():
    """**Phase 3B C2 invariant pin (FURTHER-WIDENED in Phase 3C C3 +
    Phase 4E C2) — admit set widened.** The Carrier-AA Effect-class
    admit set accessor returns the 9 classes post-Phase-4E-C2,
    including the Phase-3B-C2-widened ``ExileAllGraveyards``, the
    Phase-3C-C3-widened ``BecomesCopyOfTargetLand``, AND the
    Phase-4E-C2-widened ``DrawCardsByConditionMultiplier`` +
    ``AddManaToPool``.

    Each widen is strictly additive — the prior classes stay in the
    set bit-identical at each Phase close.
    """
    from mtg_bot.effects.generic.become_type import BecomesCopyOfTargetLand
    from mtg_bot.effects.generic.bounce import (
        ReturnTargetLandFromGraveyardToHand,
    )
    from mtg_bot.effects.generic.destroy import RegenerateTargetCreature
    from mtg_bot.effects.generic.draw_mill import (
        DrawCardsByConditionMultiplier,
    )
    from mtg_bot.effects.generic.exile import (
        ExileAllGraveyards,
        ExileTargetAttackingCreatureUntilEndStep,
    )
    from mtg_bot.effects.generic.mana import AddManaToPool
    from mtg_bot.effects.generic.misc import (
        LockOrUnlockDoorOfTargetRoomYouControl,
    )
    from mtg_bot.effects.generic.search import SearchLibraryForCard
    from mtg_bot.effects.generic.tap import UntapTargetLand
    from mtg_bot.effects.generic.zone_moves import (
        PutBasicLandFromHandOntoBattlefieldTapped,
    )
    from mtg_bot.parity.trajectory import (
        _carrier_aa_phase_1_effect_classes,
    )

    expected_subset = {
        RegenerateTargetCreature,
        UntapTargetLand,
        ReturnTargetLandFromGraveyardToHand,
        PutBasicLandFromHandOntoBattlefieldTapped,
        ExileTargetAttackingCreatureUntilEndStep,
        ExileAllGraveyards,
        BecomesCopyOfTargetLand,
        DrawCardsByConditionMultiplier,
        AddManaToPool,
        # Phase-4D-C2 widens: Keys-to-the-House FLIP.
        LockOrUnlockDoorOfTargetRoomYouControl,
        SearchLibraryForCard,
    }
    classes = _carrier_aa_phase_1_effect_classes()
    # Lower-bound invariant -- subsequent sub-phase widens (Phase 4C
    # C2 grew the admit set 9 -> 11 for Ghost Vacuum's Effect classes)
    # are strictly additive on this Phase-4E-C2 baseline.
    assert expected_subset.issubset(classes), (
        "Phase 4E C2 invariant: admit set must contain (at least) the "
        "9 Effect classes accumulated through Phase 4E C2 (Phase-3B-C2 "
        "added ExileAllGraveyards; Phase-3C-C3 added "
        "BecomesCopyOfTargetLand; Phase-4E-C2 added "
        "DrawCardsByConditionMultiplier + AddManaToPool). Phase 4C C2 "
        "ADDED the Ghost Vacuum AA Effect classes."
    )
    assert ExileAllGraveyards in classes, (
        "ExileAllGraveyards must be in the admit set post-Phase-3B-"
        "C2 — that is the C2 widen."
    )
    assert BecomesCopyOfTargetLand in classes, (
        "BecomesCopyOfTargetLand must be in the admit set post-"
        "Phase-3C-C3 — that is the C3 widen."
    )


def test_no_silent_auto_grow_admit_set_post_phase_3b_c2():
    """**Phase 3B C2 invariant pin (FURTHER-WIDENED in Phase 3C C3)
    — no-silent-auto-grow walk.** Confirms the 30 BLOCKED-SG
    Carrier-AA cards from design doc §2.1 admit exactly the 7 cards
    post-Phase-3C-C3 widen:

      Deserted Temple + Mystifying Maze + Petrified Field +
      Scavenger Grounds + Swarmyard + Terrain Generator +
      Thespian's Stage.

    All the multi-AA carriers STAY DECLINED (Mirrorpool / Ghost
    Vacuum / Keys to the House / All-Fates Scroll / Haunted Screen /
    The Eternity Elevator — Phase 4 frontier). Any new Effect class
    admitted to the set (Phase 4+) would surface here as a silent
    auto-grow — investigate before merging.

    Inverts the Phase-3B-C1 substrate-only pin
    ``test_no_silent_auto_grow_admit_set_post_phase_3b_c1``
    (expected 5 admits pre-3B-C2 → 6 post-3B-C2 → 7 post-3C-C3).
    The verify-first full-pool audit at 2026-05-26 confirmed exactly
    one new card admits under the Phase-3C-C3 widen (Thespian's
    Stage).
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import (
        _printing_is_bridge_simple_carrier_aa_land,
    )

    ps = OracleParserCardSource().get_printings()
    carrier_aa_30 = [
        "All-Fates Scroll", "Ancient Tomb", "Atomic Microsizer",
        "Auxiliary Boosters", "Baseball Bat", "Blast Zone",
        "Contested War Zone", "Deserted Temple", "Ghost Vacuum",
        "Grove of the Burnwillows", "Haunted Screen",
        "Keys to the House", "Lavaclaw Reaches", "Lotus Field",
        "Meteor Crater", "Mirrorpool", "Mystifying Maze",
        "Nesting Grounds", "Petrified Field", "Pinnacle Starcage",
        "Reflecting Pool", "Robe of Stars", "Saw", "Scavenger Grounds",
        "Sliver Overlord", "Swarmyard", "Terrain Generator",
        "The Eternity Elevator", "Thespian's Stage",
        "Wandering Fumarole",
    ]
    admits = sorted(
        name
        for name in carrier_aa_30
        if _printing_is_bridge_simple_carrier_aa_land(ps[name])
    )
    # **Phase 4B C4 (2026-05-26).** Mirrorpool FLIPped ADMITTED via
    # the full Option A widen. **Meteor Crater / Reflecting Pool /
    # Ancient Tomb P4 C2 (2026-05-27).** Each FLIPped ADMITTED via its
    # Effect-class widen. **Grove of the Burnwillows (2026-05-31).**
    # FLIPped ADMITTED via the Sequence-IN-AA admit + the
    # AddNManaOfChosenColor + GrantLifeToEachOpponent leaf-class widens.
    # (This sentinel was last refreshed at the Grove closure; the prior
    # 8-card expectation predated the MC/RP/AT/Grove flips.)
    # **Nesting Grounds (2026-05-31).** FLIPped ADMITTED via the dual-
    # target AA 2nd-target-slot closure + the
    # MovePlusOneCounterBetweenPermanentsYouControl Effect-class widen.
    assert admits == [
        "Ancient Tomb",
        "Deserted Temple",
        "Grove of the Burnwillows",
        "Meteor Crater",
        "Mirrorpool",
        "Mystifying Maze",
        "Nesting Grounds",
        "Petrified Field",
        "Reflecting Pool",
        "Scavenger Grounds",
        "Swarmyard",
        "Terrain Generator",
        "Thespian's Stage",
    ], (
        f"Carrier-AA Grove + Nesting-Grounds admit-set pin violated: "
        f"expected the 13-card admit set (Phase-3 7 + Mirrorpool + "
        f"Meteor Crater + Reflecting Pool + Ancient Tomb + Grove + "
        f"Nesting Grounds), got {admits}. "
        f"A widen in a sibling substrate or predicate would surface "
        f"here as a silent auto-grow — investigate before merging."
    )
    assert "Scavenger Grounds" in admits, (
        "Scavenger Grounds must ADMIT post-3B-C2; the "
        "ExileAllGraveyards Effect-class admit + cost-gate widen "
        "land in C2."
    )
    assert "Thespian's Stage" in admits, (
        "Thespian's Stage must ADMIT post-3C-C3; the "
        "BecomesCopyOfTargetLand Effect-class admit widen ships at C3."
    )


def test_no_other_carrier_has_both_sacrifice_axes():
    """**Phase 3B C2 verify-first audit pin.** The cost-gate's new
    defense-in-depth guard at
    :func:`_aa_is_phase1_sub_shape_a`
    (``cost.sacrifice_a_desert and cost.sacrifice_self`` declines)
    has no live consumer in the EoE pool: no carrier carries both
    sacrifice axes at once. Scavenger Grounds is the SOLE carrier
    carrying ``sacrifice_a_desert=True`` AND its ``sacrifice_self``
    is ``False``; the guard exists for future-carrier safety so a
    new card carrying both axes fails honestly rather than silently
    auto-admitting under the Phase-3B widen.

    This pin confirms (a) Scavenger Grounds is the only
    ``sacrifice_a_desert=True`` carrier in the pool and (b) zero
    carriers carry both ``sacrifice_a_desert=True`` AND
    ``sacrifice_self=True`` at once.
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource

    ps = OracleParserCardSource().get_printings()
    both_at_once = []
    sad_only = []
    for name, p in ps.items():
        for aa in (p.activated_abilities or ()):
            if aa.cost.sacrifice_a_desert and aa.cost.sacrifice_self:
                both_at_once.append(name)
            elif aa.cost.sacrifice_a_desert:
                sad_only.append(name)
    assert both_at_once == [], (
        f"Phase 3B C2 defense-in-depth guard invariant: no carrier "
        f"may carry both sacrifice_a_desert AND sacrifice_self; got "
        f"both_at_once={both_at_once}. If a new carrier surfaces "
        f"here, the cost-gate's both-at-once guard fires honestly "
        f"— widen the gate intentionally."
    )
    assert sorted(sad_only) == ["Scavenger Grounds"], (
        f"Phase 3B C2 verify-first audit: Scavenger Grounds must be "
        f"the SOLE sacrifice_a_desert carrier in the EoE pool; got "
        f"{sorted(sad_only)}."
    )
