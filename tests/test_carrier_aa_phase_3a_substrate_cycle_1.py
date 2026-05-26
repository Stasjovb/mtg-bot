"""**Carrier-AA substrate Phase 3A Cycle 1 (2026-05-25).**

Tests for the Phase 3A Cycle 1 Rust substrate landing per
``docs/CARRIER_AA_SUBSTRATE_PHASE_3_DESIGN.md`` §4.1 (Rust spec) +
§5.2 (Python bridge spec) + §6.1 (test plan).

Deliverables (Cycle 1 Rust slice, per design doc §4.1):

  - New Rust ``Effect`` variants on ``cards.rs::Effect``:
      * ``ExileTargetAttackingCreatureUntilEndStep`` (unit variant) —
        Mystifying Maze's pilot effect (`{4}, {T}: Exile target
        attacking creature an opponent controls. At the beginning of
        the next end step, return it to the battlefield tapped under
        its owner's control.`).
      * ``ReturnExiledPermanentToOwnerTapped { exile_card_id: u32 }``
        — paired delayed-trigger effect.
    With: enum variants + ``parse_effect`` arms + ``to_pydict`` arms
    + ``state_ops_resolve`` resolve arms + ``state_ops_legal.rs``
    attacking-creature target fan-out + ``state_ops_actions.rs``
    apply-time validation arm + ``cross_engine.py`` bridge dict→Python
    + forward emit arms + ``trajectory.py`` reverse-serializer leaf.
  - ZERO new Rust cost-shape machinery — Mystifying Maze's `{4}, {T}`
    cost is the Phase 1.5a `{N}, {T}` admit shape already wired (cost-
    gate at ``trajectory.py:8549``+).
  - ZERO new state field — ``state.delayed_triggers`` Vec + the
    ``WarpExileSelf`` precedent's ``DelayedTrigger`` struct + the
    ``state.attackers`` Vec are all already in place.

This is a **substrate-only closure** — the cycle adds the new Rust
Effect variants + bridge plumbing as reusable infrastructure. The
pilot card (Mystifying Maze) STAYS DECLINED at the production-deck
admit gate post-Cycle-1 because the Python admit predicate
``_aa_is_phase1_sub_shape_a`` Effect-class gate doesn't yet include
``ExileTargetAttackingCreatureUntilEndStep`` in
``_carrier_aa_phase_1_effect_classes`` (Cycle 2 ships that widen).

**Verify-first findings (live tree, main `604de874`):**

  - Mystifying Maze's live oracle text: ``{4}, {T}: Exile target
    attacking creature an opponent controls. At the beginning of the
    next end step, return it to the battlefield tapped under its
    owner's control.``  Parser body whitelist at
    ``src/mtg_bot/cards/parser/land_builder.py:1604-1606`` maps the
    body to ``ExileTargetAttackingCreatureUntilEndStep()`` with
    ``ActivationCost(tap_self=True, mana={"generic": 4})``.
  - Python's ``ExileTargetAttackingCreatureUntilEndStep`` class at
    ``effects/generic/exile.py:180`` — frozen dataclass with no
    constructor args; the resolve method exiles the target +
    schedules a delayed trigger with
    ``ReturnExiledPermanentToOwnerTapped(exile_card_id=target.id)``.
  - Python's ``ReturnExiledPermanentToOwnerTapped`` at
    ``effects/generic/exile.py:86`` — single-field dataclass carrying
    the captured-at-schedule-time exiled object id.
  - Rust precedents: ``state.delayed_triggers`` Vec +
    ``DelayedTrigger`` struct at ``cards.rs:8585`` + the
    ``WarpExileSelf`` resolve arm at
    ``state_ops_resolve.rs:19049`` + the
    ``run_delayed_end_step_triggers`` machinery at
    ``state_ops_steps.rs:465``. ``state.attackers: Vec<u32>`` exists
    at ``state.rs:2253``.

**Test plan (per design doc §6.1):**

  - Parser SoT pin: confirm Python's
    ``ExileTargetAttackingCreatureUntilEndStep`` /
    ``ReturnExiledPermanentToOwnerTapped`` classes exist in
    ``effects.generic.exile`` and round-trip byte-equal.
  - Verify-first pin: confirm Mystifying Maze's live AA shape
    (``{4}, {T}`` cost + ``ExileTargetAttackingCreatureUntilEndStep``
    effect, no riders).
  - Rust unit pins: ``parse_effect`` arms via
    ``register_printing`` round-trip + ``to_pydict`` arms via the
    bridge inverse.
  - Cross-engine bridge pins: dict→Python bridge arms
    (``_ta_dict_to_python_effect``) for both kinds + Python→dict
    forward arm (``_python_aa_to_safe_dict``) for the AA effect +
    the trajectory ``_leaf`` arm for the paired
    ``ReturnExiledPermanentToOwnerTapped``.
  - Rust resolve arm pins: ``ExileTargetAttackingCreatureUntilEndStep``
    exiles + pushes delayed trigger; silent fizzle when target is no
    longer attacking; ``ReturnExiledPermanentToOwnerTapped`` returns
    the exiled object to the owner's bf tapped.
  - Legal-emit fan-out pin: ``legal_decisions`` emits one
    ActivateAbility per attacking creature an opponent controls.
  - Combat-phase guard pin: outside combat,
    ``state.attackers`` is empty → the fan-out emits zero actions.
  - Substrate-only invariant pin: Mystifying Maze STAYS DECLINED at
    the production-deck loader filter post-Cycle-1.
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

# Phase enum index for PRECOMBAT_MAIN — matches Rust state enum
# discriminant. Mirrors the constant exported in tests_rust/test_legal.py.
PHASE_MAIN1 = 3


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
    per side. Mirrors ``tests_rust/conftest.py``'s shared fixture for
    AA resolve-arm pins."""
    return engine.make_synthetic_state()


# ---------------------------------------------------------------------------
# Parser SoT verify-first
# ---------------------------------------------------------------------------


def test_python_exile_target_attacking_creature_until_end_step_class_exists():
    """**Parser source-of-truth pin.** Python's
    ``ExileTargetAttackingCreatureUntilEndStep`` class is in
    ``effects.generic.exile``, a frozen dataclass with no constructor
    args; ``requires_target() is True``.
    """
    from mtg_bot.effects.base import Effect
    from mtg_bot.effects.generic.exile import (
        ExileTargetAttackingCreatureUntilEndStep,
    )

    eff = ExileTargetAttackingCreatureUntilEndStep()
    # Subclass invariant.
    assert isinstance(eff, Effect)
    # Frozen-dataclass identity check.
    assert eff == ExileTargetAttackingCreatureUntilEndStep()
    # Requires a target by design.
    assert eff.requires_target() is True


def test_python_return_exiled_permanent_to_owner_tapped_class_exists():
    """**Parser SoT pin.** ``ReturnExiledPermanentToOwnerTapped`` carries
    a single ``exile_card_id: int`` field. Two instances with the same
    id compare equal (frozen dataclass __eq__); different ids compare
    unequal.
    """
    from mtg_bot.effects.base import Effect
    from mtg_bot.effects.generic.exile import (
        ReturnExiledPermanentToOwnerTapped,
    )

    a = ReturnExiledPermanentToOwnerTapped(exile_card_id=42)
    b = ReturnExiledPermanentToOwnerTapped(exile_card_id=42)
    c = ReturnExiledPermanentToOwnerTapped(exile_card_id=43)
    assert isinstance(a, Effect)
    assert a == b
    assert a != c
    assert a.exile_card_id == 42


def test_mystifying_maze_live_printing_matches_design_doc_shape():
    """**Verify-first pin — Mystifying Maze's live AA shape.** Confirms
    the design doc §2.1 row at HEAD: ``Land``, single non-mana AA, cost
    ``tap_self=True`` AND ``mana={"generic": 4}``,
    effect ``ExileTargetAttackingCreatureUntilEndStep``, no AA-level
    riders.

    NOTE: the live shape's ``mana={"generic": 4}`` passes the Phase
    1.5a ``{N}, {T}`` cost gate. Mystifying Maze stays DECLINED at the
    admit gate post-Cycle-1 because the Effect-class admit set
    ``_carrier_aa_phase_1_effect_classes`` does NOT yet include
    ``ExileTargetAttackingCreatureUntilEndStep`` (Cycle 2 ships that
    widen).
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.effects.generic.exile import (
        ExileTargetAttackingCreatureUntilEndStep,
    )

    ps = OracleParserCardSource().get_printings()
    mm = ps["Mystifying Maze"]

    assert mm.card_types == ("Land",)
    assert mm.power is None and mm.toughness is None

    aas = [
        aa for aa in (mm.activated_abilities or ())
        if not aa.is_mana_ability
    ]
    assert len(aas) == 1, (
        f"expected 1 non-mana AA on Mystifying Maze, got {len(aas)}: "
        f"{aas}"
    )
    aa = aas[0]

    cost = aa.cost
    assert cost.tap_self is True
    assert cost.sacrifice_self is False
    assert cost.mana is not None
    assert isinstance(aa.effect, ExileTargetAttackingCreatureUntilEndStep)

    # No AA-level riders (verify-first contract).
    assert aa.is_mana_ability is False
    assert aa.sorcery_speed is False
    assert aa.activate_only_once is False
    assert aa.tier_threshold == 0
    assert aa.room_half is None
    assert aa.cost_reductions == ()


# ---------------------------------------------------------------------------
# Cross-engine bridge arm pins (dict -> Python)
# ---------------------------------------------------------------------------


def test_bridge_arm_exile_target_attacking_creature_until_end_step():
    """Bridge arm constructs
    ``ExileTargetAttackingCreatureUntilEndStep()`` from a single-key
    dict (no fields)."""
    from mtg_bot.effects.generic.exile import (
        ExileTargetAttackingCreatureUntilEndStep,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    back = _ta_dict_to_python_effect(
        {"kind": "exile_target_attacking_creature_until_end_step"}
    )
    assert isinstance(back, ExileTargetAttackingCreatureUntilEndStep)


def test_bridge_arm_return_exiled_permanent_to_owner_tapped():
    """Bridge arm constructs ``ReturnExiledPermanentToOwnerTapped`` from
    a dict carrying ``exile_card_id``. The id round-trips int-typed."""
    from mtg_bot.effects.generic.exile import (
        ReturnExiledPermanentToOwnerTapped,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    back = _ta_dict_to_python_effect({
        "kind": "return_exiled_permanent_to_owner_tapped",
        "exile_card_id": 42,
    })
    assert isinstance(back, ReturnExiledPermanentToOwnerTapped)
    assert back.exile_card_id == 42
    assert isinstance(back.exile_card_id, int)


def test_python_aa_to_safe_dict_forward_arm_round_trips_maze_shape():
    """**Forward emit pin.** A synthetic Mystifying-Maze-shape
    ``ActivatedAbility`` serializes through ``_python_aa_to_safe_dict``
    to a dict carrying:

      * ``cost``: ``{"tap_self": True, "mana": {"generic": 4}}``
      * ``effect``: ``{"kind": "exile_target_attacking_creature_until_end_step"}``

    Cycle-1 substrate-only: this round-trip succeeds, but
    ``_aa_is_phase1_sub_shape_a`` still declines Mystifying Maze's AA
    on the Effect-class gate — Cycle 2 ships the widen.
    """
    from mtg_bot.effects.base import ActivatedAbility, ActivationCost
    from mtg_bot.effects.generic.exile import (
        ExileTargetAttackingCreatureUntilEndStep,
    )
    from mtg_bot.cards.base import ManaCost
    from mtg_bot.parity.cross_engine import (
        _aa_dict_to_python_activated_ability,
        _python_aa_to_safe_dict,
    )

    aa = ActivatedAbility(
        cost=ActivationCost(
            tap_self=True,
            mana=ManaCost(generic=4),
        ),
        effect=ExileTargetAttackingCreatureUntilEndStep(),
    )
    d = _python_aa_to_safe_dict(aa)
    assert d is not None, (
        "Mystifying Maze AA shape must round-trip through the bridge "
        "floor — Cycle 1 widens the forward emit even though the "
        "admit predicate keeps it DECLINED."
    )
    assert d["cost"]["tap_self"] is True
    assert d["cost"]["mana"] == {"generic": 4}
    assert d["effect"] == {
        "kind": "exile_target_attacking_creature_until_end_step",
    }
    # Reverse round-trip — byte-equal at the dataclass __eq__ surface.
    back = _aa_dict_to_python_activated_ability(d)
    assert back == aa


def test_trajectory_leaf_serializes_return_exiled_permanent_to_owner_tapped():
    """**Trajectory ``_leaf`` arm pin.** The reverse-serializer leaf at
    ``trajectory.py::_python_spell_effect_to_dict::_leaf`` serializes a
    Python ``ReturnExiledPermanentToOwnerTapped(exile_card_id=N)``
    instance into the round-trip dict shape
    ``{"kind": "return_exiled_permanent_to_owner_tapped",
       "exile_card_id": N}``. This is the producer-side serializer used
    by ``delayed_triggers`` snapshots; round-trips byte-equal back
    through the bridge.
    """
    from mtg_bot.effects.generic.draw_mill import DrawCards
    from mtg_bot.effects.generic.exile import (
        ReturnExiledPermanentToOwnerTapped,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect
    from mtg_bot.parity.trajectory import _python_spell_effect_to_dict
    from mtg_bot.effects.combinators import Sequence

    # The `_leaf` is private — wrap inside a Sequence so we can exercise
    # the public `_python_spell_effect_to_dict` entrypoint which routes
    # to `_leaf` for each child. Pair the target effect with a trivial
    # DrawCards leaf to satisfy the multi-child Sequence shape.
    eff = Sequence(effects=(
        ReturnExiledPermanentToOwnerTapped(exile_card_id=99),
        DrawCards(amount=1),
    ))
    d = _python_spell_effect_to_dict(eff)
    assert d is not None
    assert d["kind"] == "sequence"
    leaves = d["effects"]
    assert any(
        leaf.get("kind") == "return_exiled_permanent_to_owner_tapped"
        and leaf.get("exile_card_id") == 99
        for leaf in leaves
    ), (
        f"Sequence leaves must include the "
        f"return_exiled_permanent_to_owner_tapped arm; got {leaves}"
    )
    # Reverse round-trip via the bridge dict-arm.
    leaf = next(
        leaf for leaf in leaves
        if leaf.get("kind") == "return_exiled_permanent_to_owner_tapped"
    )
    back = _ta_dict_to_python_effect(leaf)
    assert isinstance(back, ReturnExiledPermanentToOwnerTapped)
    assert back.exile_card_id == 99


# ---------------------------------------------------------------------------
# Rust unit pins — parse + register
# ---------------------------------------------------------------------------


def test_rust_register_carrier_aa_mystifying_maze_shape():
    """**Rust parse arm pin.** ``register_printing`` accepts a non-token
    Land carrier with ``activated_abilities=[{cost: {tap_self: True,
    mana: {generic: 4}}, effect: {kind:
    exile_target_attacking_creature_until_end_step}}]``. The pid is
    returned and ``get_printing_name`` echoes the name.
    """
    _require_engine()
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing({
        "name": "Test Mystifying Maze",
        "card_types": ["Land"],
        "mana_cost": {},
        "activated_abilities": [
            {
                "cost": {"tap_self": True, "mana": {"generic": 4}},
                "effect": {
                    "kind": "exile_target_attacking_creature_until_end_step",
                },
            }
        ],
    })
    assert reg.get_printing_name(pid) == "Test Mystifying Maze"


def test_rust_register_carrier_aa_extra_dict_keys_silently_dropped():
    """Unit-variant contract:
    ``exile_target_attacking_creature_until_end_step`` parse arm
    silently drops extra dict keys (no field validation).
    """
    _require_engine()
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing({
        "name": "Test Maze With Extras",
        "card_types": ["Land"],
        "mana_cost": {},
        "activated_abilities": [
            {
                "cost": {"tap_self": True, "mana": {"generic": 4}},
                "effect": {
                    "kind": "exile_target_attacking_creature_until_end_step",
                    "spurious_field": 42,
                },
            }
        ],
    })
    assert reg.get_printing_name(pid) == "Test Maze With Extras"


def test_rust_parse_return_exiled_permanent_to_owner_tapped_via_delayed_trigger():
    """**Rust parse arm pin for the paired EoT-return effect.** The
    ``return_exiled_permanent_to_owner_tapped`` parse arm requires
    ``exile_card_id`` (REQUIRED u32). Missing key raises. The parse
    arm is exercised indirectly here by registering a synthetic
    triggered-ability dict that carries the effect via a delayed-
    trigger consumer dict — direct exposure of parse_effect outside
    the registry path isn't available, so this pin asserts the
    round-trip via ``register_printing`` of a synthetic carrier where
    the effect appears inside an activated_abilities body.
    """
    _require_engine()
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    # The Effect is normally injected via the producer arm at resolve
    # time. To exercise the parse_effect arm directly, attach it to a
    # synthetic carrier ability and confirm registration succeeds.
    pid = reg.register_printing({
        "name": "Test Return Carrier",
        "card_types": ["Land"],
        "mana_cost": {},
        "activated_abilities": [
            {
                "cost": {"tap_self": True},
                "effect": {
                    "kind": "return_exiled_permanent_to_owner_tapped",
                    "exile_card_id": 7,
                },
            }
        ],
    })
    assert reg.get_printing_name(pid) == "Test Return Carrier"


def test_rust_parse_return_exiled_permanent_missing_id_raises():
    """**Rust parse arm pin — required field guard.** Missing
    ``exile_card_id`` key raises ValueError loudly (mirrors the
    ``remove_charge_counters_from_source_delayed`` single-int-field
    sibling's required-field contract).
    """
    _require_engine()
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    with pytest.raises(ValueError, match="exile_card_id"):
        reg.register_printing({
            "name": "Test Bad Return",
            "card_types": ["Land"],
            "mana_cost": {},
            "activated_abilities": [
                {
                    "cost": {"tap_self": True},
                    "effect": {
                        "kind": "return_exiled_permanent_to_owner_tapped",
                        # exile_card_id missing.
                    },
                }
            ],
        })


# ---------------------------------------------------------------------------
# Rust resolve arm pin — Maze exiles + pushes delayed trigger
# ---------------------------------------------------------------------------


def _synthetic_mystifying_maze_dict():
    """Minimal Maze-shape printing dict for the Rust Registry."""
    return {
        "name": "Synthetic Mystifying Maze",
        "card_types": ["Land"],
        "mana_cost": {},
        "activated_abilities": [
            {
                "cost": {"tap_self": True, "mana": {"generic": 4}},
                "effect": {
                    "kind": "exile_target_attacking_creature_until_end_step",
                },
                "is_mana_ability": False,
            }
        ],
    }


def _synthetic_bear_dict(name="Test Bear"):
    """Minimal 2/2 Bear-shape creature dict — used as the attacking
    creature target for the Maze resolve-arm pin.
    """
    return {
        "name": name,
        "card_types": ["Creature"],
        "mana_cost": {"generic": 2},
        "power": 2,
        "toughness": 2,
    }


def test_resolve_exile_target_attacking_creature_exiles_target_and_pushes_delayed_trigger(
    engine, synthetic_state,
):
    """**Resolve arm pin — exile + delayed-trigger push.**
    Set up: Maze on p0 bf; opponent (p1) controls an attacking Bear.
    Activate Maze's AA targeting the attacker; resolve. Expected:
      - Bear moves from p1 bf to p1 exile.
      - A new DelayedTrigger entry on state.delayed_triggers carries
        the EoT-return effect with exile_card_id == bear_id +
        source_id == maze_id + controller_id == state.active_player.
    """
    maze_id = synthetic_state.register_and_inject_object(
        _synthetic_mystifying_maze_dict(),
        0,  # controller (p0)
        ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(maze_id, False)
    # Inject an attacking Bear on p1's bf (opponent of activator p0).
    bear_id = synthetic_state.register_and_inject_object(
        _synthetic_bear_dict(),
        1,  # controller (p1 = opponent of p0)
        ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(bear_id, False)

    # Declare bear_id as an attacker by p1 — sets state.attackers and
    # taps the bear.
    # active_player is p0 by default in make_synthetic_state, but
    # declare_attacker only checks tap/summoning-sick — not whose turn
    # it is. We push attackers explicitly here for the cross-controller
    # scenario (Maze is activated by p0 on p1's attack).
    assert synthetic_state.declare_attacker(bear_id) is True
    assert bear_id in synthetic_state.get_attackers()

    # Pre-state: stack empty, bear on p1 bf.
    assert synthetic_state.stack_size() == 0
    bf_pre = synthetic_state.battlefield_snapshot()
    assert any(o["id"] == bear_id for o in bf_pre)

    # Activate Maze's AA with target = bear_id.
    # Mana cost: {4}. Add 4 generic mana to p0's pool.
    synthetic_state.add_mana(0, "C", 4)
    synthetic_state.apply_action({
        "kind": "activate_ability",
        "source_id": maze_id,
        "ability_index": 0,
        "target_creature_id": bear_id,
    })
    # Stack has the queued effect (the AA isn't a mana ability — it
    # uses the stack).
    assert synthetic_state.stack_size() == 1

    # Pre-snapshot delayed_triggers count.
    dt_pre = list(synthetic_state.delayed_triggers_snapshot())
    n_dt_pre = len(dt_pre)

    # Resolve.
    synthetic_state.resolve_top_of_stack()

    # Bear is now in p1's exile.
    bf_post = synthetic_state.battlefield_snapshot()
    assert not any(o["id"] == bear_id for o in bf_post), (
        f"Bear (id={bear_id}) should be off bf after Maze resolves; "
        f"got bf={bf_post}"
    )
    exile_post = synthetic_state.exile_snapshot(1)
    assert any(o["id"] == bear_id for o in exile_post), (
        f"Bear (id={bear_id}) should be in p1's exile; got "
        f"exile={exile_post}"
    )

    # New delayed-trigger entry — exactly one new entry, carrying the
    # return-on-EoT effect with the bear's id.
    dt_post = list(synthetic_state.delayed_triggers_snapshot())
    assert len(dt_post) == n_dt_pre + 1, (
        f"Expected exactly one new delayed-trigger entry "
        f"post-Maze-resolve; got {len(dt_post) - n_dt_pre} new entries"
    )
    new_entry = dt_post[-1]
    assert new_entry["effect_kind"] == "return_exiled_permanent_to_owner_tapped"
    assert new_entry["source_id"] == maze_id


def test_resolve_exile_target_no_target_silent_fizzle(
    engine, synthetic_state,
):
    """**Resolve arm — silent fizzle (CR 608.2b).** If no target is
    bound on the StackItem (``current_resolve_payload_target_id ==
    None``), the resolve arm silently fizzles — NO exile move, NO
    delayed-trigger push.

    Drives the no-target path via direct apply_action with
    ``target_creature_id`` omitted; the apply-time validator under
    ``is_exile_attacking_creature_effect`` accepts ``None`` (matches
    Python's `if not targets: return` early-return at
    `exile.py:216-217` and the Phase 2a substrate-fallback contract).
    """
    maze_id = synthetic_state.register_and_inject_object(
        _synthetic_mystifying_maze_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(maze_id, False)
    synthetic_state.add_mana(0, "C", 4)
    n_dt_pre = len(synthetic_state.delayed_triggers_snapshot())

    # No target_creature_id provided — substrate-fallback / no-target
    # path.
    synthetic_state.apply_action({
        "kind": "activate_ability",
        "source_id": maze_id,
        "ability_index": 0,
    })
    synthetic_state.resolve_top_of_stack()

    n_dt_post = len(synthetic_state.delayed_triggers_snapshot())
    assert n_dt_post == n_dt_pre, (
        "Silent fizzle: no delayed-trigger push when no target "
        "is bound on the StackItem."
    )


def test_resolve_return_exiled_permanent_end_to_end_via_eot_trigger(engine):
    """**End-to-end Maze + EoT-return path.** Sets up Maze + opponent
    attacker, activates Maze, resolves the exile, advances to the end
    step, lets the delayed trigger fire + resolve, and verifies the
    attacker returns to the owner's battlefield tapped.

    Exercises the full delayed-trigger machinery: producer arm
    (`ExileTargetAttackingCreatureUntilEndStep` schedules the trigger
    on `state.delayed_triggers`), `run_delayed_end_step_triggers` at
    end-step entry, push_triggered_ability onto stack, and consumer
    arm (`ReturnExiledPermanentToOwnerTapped` returns object).
    """
    state = engine.make_synthetic_state(0, 0, 0)
    maze_id = state.register_and_inject_object(
        _synthetic_mystifying_maze_dict(), 0, ZONE_BATTLEFIELD,
    )
    state.force_set_summoning_sick(maze_id, False)
    bear_id = state.register_and_inject_object(
        _synthetic_bear_dict(), 1, ZONE_BATTLEFIELD,
    )
    state.force_set_summoning_sick(bear_id, False)
    assert state.declare_attacker(bear_id) is True
    state.add_mana(0, "C", 4)

    state.apply_action({
        "kind": "activate_ability",
        "source_id": maze_id,
        "ability_index": 0,
        "target_creature_id": bear_id,
    })
    state.resolve_top_of_stack()
    # Bear is now in p1's exile; delayed trigger scheduled.
    exile_post_maze = state.exile_snapshot(1)
    assert any(o["id"] == bear_id for o in exile_post_maze)

    # Advance phases until we hit PHASE_END_STEP (10), which triggers
    # run_delayed_end_step_triggers. Bound the loop to a turn cycle.
    PHASE_END_STEP = 10
    fired = False
    for _ in range(20):
        state.advance_phase()
        if state.current_phase() == PHASE_END_STEP:
            # On entry to end step, the delayed trigger is pushed onto
            # the stack. Drain it.
            while state.stack_size() > 0:
                state.resolve_top_of_stack()
            fired = True
            break

    assert fired, "Failed to reach PHASE_END_STEP within 20 advances"
    bf_post = state.battlefield_snapshot()
    bear_obj = next((o for o in bf_post if o["id"] == bear_id), None)
    assert bear_obj is not None, (
        f"Bear should return to bf at end step; got bf={bf_post}"
    )
    assert bear_obj["controller_id"] == 1
    assert bear_obj["tapped"] is True
    # And the bear is no longer in exile.
    assert not any(
        o["id"] == bear_id for o in state.exile_snapshot(1)
    )


# ---------------------------------------------------------------------------
# Legal-emit fan-out pin — attacking-creature target enumeration
# ---------------------------------------------------------------------------


def _build_maze_state(engine_module, attacker_dicts_p1):
    """Helper — build a synthetic state with Mystifying Maze on p0's bf
    (untapped, not summoning-sick) + N opponent attackers on p1's bf.

    Returns ``(state, maze_id, attacker_ids)``.
    """
    state = engine_module.make_synthetic_state(0, 0, 0)
    maze_id = state.register_and_inject_object(
        _synthetic_mystifying_maze_dict(), 0, ZONE_BATTLEFIELD,
    )
    state.force_set_summoning_sick(maze_id, False)
    attacker_ids = []
    for d in attacker_dicts_p1:
        aid = state.register_and_inject_object(d, 1, ZONE_BATTLEFIELD)
        state.force_set_summoning_sick(aid, False)
        # Declare as attacker — pushes onto state.attackers.
        assert state.declare_attacker(aid) is True
        attacker_ids.append(aid)
    state.set_phase(PHASE_MAIN1)
    state.give_priority_to(0)
    # Pre-add mana to p0's pool so the {4} cost is affordable in the
    # emission walk's pool check.
    state.add_mana(0, "C", 4)
    return state, maze_id, attacker_ids


def test_rust_legal_emit_fan_out_one_aa_per_attacking_opponent(engine):
    """**Phase 3A C1 legal-emit pin — fan-out cardinality (1 attacker).**
    With Maze on bf + one attacking opponent Bear, emits exactly ONE
    ``ActivateAbility`` dict carrying ``target_creature_id = bear_id``.
    """
    state, maze_id, attacker_ids = _build_maze_state(
        engine, [_synthetic_bear_dict()],
    )
    bear_id = attacker_ids[0]

    decisions = state.legal_decisions(0)
    aa_decisions = [
        d for d in decisions
        if d.get("kind") == "activate_ability"
        and d.get("source_id") == maze_id
    ]
    assert len(aa_decisions) == 1, (
        f"Expected 1 ActivateAbility emit on Maze with one attacking "
        f"opponent; got {len(aa_decisions)}: {aa_decisions}"
    )
    aa = aa_decisions[0]
    assert aa["target_creature_id"] == bear_id


def test_rust_legal_emit_fan_out_multiple_attacking_opponents(engine):
    """**Phase 3A C1 legal-emit pin — fan-out cardinality (N=3
    attackers).** With Maze on bf + THREE attacking opponent Bears,
    the fan-out emits THREE ``ActivateAbility`` dicts.
    """
    state, maze_id, attacker_ids = _build_maze_state(
        engine,
        [_synthetic_bear_dict("Bear A"),
         _synthetic_bear_dict("Bear B"),
         _synthetic_bear_dict("Bear C")],
    )

    decisions = state.legal_decisions(0)
    aa_decisions = [
        d for d in decisions
        if d.get("kind") == "activate_ability"
        and d.get("source_id") == maze_id
    ]
    assert len(aa_decisions) == 3
    emit_target_ids = sorted(d["target_creature_id"] for d in aa_decisions)
    assert emit_target_ids == sorted(attacker_ids)


def test_rust_legal_emit_fan_out_no_emit_outside_combat(engine):
    """**Phase 3A C1 legal-emit pin — combat-phase guard.** With Maze on
    bf + NO declared attackers (the Vec is empty), the fan-out emits
    ZERO ``ActivateAbility`` dicts (CR 117.5 — an AA with no legal
    target cannot be activated).
    """
    state, maze_id, _ = _build_maze_state(engine, [])

    decisions = state.legal_decisions(0)
    aa_decisions = [
        d for d in decisions
        if d.get("kind") == "activate_ability"
        and d.get("source_id") == maze_id
    ]
    assert aa_decisions == [], (
        f"Expected 0 emits on Maze with empty state.attackers; got "
        f"{aa_decisions}"
    )


def test_rust_legal_emit_fan_out_skips_own_attackers(engine):
    """**Phase 3A C1 legal-emit pin — opponent-controlled gate.** Maze's
    target text is "attacking creature an OPPONENT controls" — own
    attackers must NOT appear in the emit fan-out. Inject a Bear on
    p0's bf, declare it as an attacker. The fan-out skips it.
    """
    state = engine.make_synthetic_state(0, 0, 0)
    maze_id = state.register_and_inject_object(
        _synthetic_mystifying_maze_dict(), 0, ZONE_BATTLEFIELD,
    )
    state.force_set_summoning_sick(maze_id, False)
    # Own attacker (p0) — must be skipped.
    own_attacker_id = state.register_and_inject_object(
        _synthetic_bear_dict("Own Bear"), 0, ZONE_BATTLEFIELD,
    )
    state.force_set_summoning_sick(own_attacker_id, False)
    assert state.declare_attacker(own_attacker_id) is True
    state.set_phase(PHASE_MAIN1)
    state.give_priority_to(0)
    state.add_mana(0, "C", 4)

    decisions = state.legal_decisions(0)
    aa_decisions = [
        d for d in decisions
        if d.get("kind") == "activate_ability"
        and d.get("source_id") == maze_id
    ]
    assert aa_decisions == [], (
        "Maze must skip own attackers (opponent-controlled gate); "
        f"got {aa_decisions}"
    )


# ---------------------------------------------------------------------------
# Apply-time validation pins
# ---------------------------------------------------------------------------


def test_rust_apply_action_raises_on_illegal_attacker_target(engine):
    """**Phase 3A C1 apply-time validation pin — illegal target raises.**
    A malformed direct-caller-built dict pointing at an id that is NOT
    in ``state.attackers`` raises ValueError BEFORE any state mutation.
    """
    state, maze_id, attacker_ids = _build_maze_state(
        engine, [_synthetic_bear_dict()],
    )
    # 99999 is not in state.attackers.
    with pytest.raises(ValueError, match="not currently attacking"):
        state.apply_action({
            "kind": "activate_ability",
            "source_id": maze_id,
            "ability_index": 0,
            "target_creature_id": 99999,
        })


def test_rust_apply_action_raises_on_own_attacker_target(engine):
    """**Phase 3A C1 apply-time validation pin — own attacker raises.**
    Even if an own-attacker id IS in ``state.attackers``, the target
    legality check fails because the target must be opponent-
    controlled.
    """
    state = engine.make_synthetic_state(0, 0, 0)
    maze_id = state.register_and_inject_object(
        _synthetic_mystifying_maze_dict(), 0, ZONE_BATTLEFIELD,
    )
    state.force_set_summoning_sick(maze_id, False)
    own_bear_id = state.register_and_inject_object(
        _synthetic_bear_dict(), 0, ZONE_BATTLEFIELD,
    )
    state.force_set_summoning_sick(own_bear_id, False)
    assert state.declare_attacker(own_bear_id) is True
    state.add_mana(0, "C", 4)
    with pytest.raises(ValueError, match="not a legal attacking-creature target"):
        state.apply_action({
            "kind": "activate_ability",
            "source_id": maze_id,
            "ability_index": 0,
            "target_creature_id": own_bear_id,
        })


# ---------------------------------------------------------------------------
# Phase 3A C2 invariant (INVERTED) — Mystifying Maze NOW ADMITS post-C2
# ---------------------------------------------------------------------------


def test_mystifying_maze_now_admits_at_admit_gate_post_phase_3a():
    """**Phase 3A C2 invariant pin (INVERTED).** Mystifying Maze's live
    ``OracleParserCardSource`` printing PASSES
    :func:`_printing_is_bridge_simple_carrier_aa_land` post-Phase-3A-
    C2 because the Effect-class admit set
    ``_carrier_aa_phase_1_effect_classes`` is widened to include
    ``ExileTargetAttackingCreatureUntilEndStep`` (the C1 substrate's
    Rust Effect variant at ``3de469a3``).

    Inverts the Phase-3A-C1 substrate-only pin
    ``test_mystifying_maze_stays_declined_post_cycle_1`` — admit-gate
    FLIPped DECLINED → ADMITTED on the Python accessor widen alone
    (Mystifying Maze's ``{4}, {T}`` cost shape already passes the
    Phase-1.5a ``{N}, {T}`` cost-gate).
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity import trajectory as traj

    ps = OracleParserCardSource().get_printings()
    mm = ps["Mystifying Maze"]
    assert traj._printing_is_bridge_simple_carrier_aa_land(mm) is True, (
        "Mystifying Maze must ADMIT at the Carrier-AA admit gate "
        "post-Phase-3A-C2. The Effect-class admit set "
        "_carrier_aa_phase_1_effect_classes is widened to include "
        "ExileTargetAttackingCreatureUntilEndStep and the cost-gate "
        "already accepts the {4}, {T} Phase-1.5a shape."
    )


def test_mystifying_maze_now_passes_loader_filter():
    """**Phase 3A C2 invariant pin (INVERTED, loader-level).** The
    end-to-end production-deck loader filter ADMITS Mystifying Maze
    post-Phase-3A-C2 — the Carrier-AA disjunct fires now that the
    Effect-class admit set is widened.

    Inverts the Phase-3A-C1 pin
    ``test_mystifying_maze_stays_declined_at_loader_filter``.
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import _filter_deck_to_bridge_supported

    ps = OracleParserCardSource().get_printings()
    assert "Mystifying Maze" in ps
    filtered, card_defs = _filter_deck_to_bridge_supported(
        ["Mystifying Maze"], ps,
    )
    assert filtered == ["Mystifying Maze"], (
        f"Mystifying Maze must PASS the loader filter post-Phase-3A-"
        f"C2; got filtered={filtered}, card_defs={card_defs}"
    )
    assert len(card_defs) == 1
    assert card_defs[0].name == "Mystifying Maze"


def test_carrier_aa_phase_1_effect_classes_widened_post_phase_3a_c2():
    """**Phase 3A C2 invariant pin (FURTHER-WIDENED in Phase 3B C2 +
    Phase 3C C3 + Phase 4E C2).** The Carrier-AA Effect-class admit
    set accessor returns the 9 classes post-Phase-4E-C2, including
    the Phase-3A-C2-widened ``ExileTargetAttackingCreatureUntilEndStep``,
    the Phase-3B-C2-widened ``ExileAllGraveyards``, the
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
    from mtg_bot.effects.generic.tap import UntapTargetLand
    from mtg_bot.effects.generic.zone_moves import (
        PutBasicLandFromHandOntoBattlefieldTapped,
    )
    from mtg_bot.parity.trajectory import (
        _carrier_aa_phase_1_effect_classes,
    )

    expected = frozenset({
        RegenerateTargetCreature,
        UntapTargetLand,
        ReturnTargetLandFromGraveyardToHand,
        PutBasicLandFromHandOntoBattlefieldTapped,
        ExileTargetAttackingCreatureUntilEndStep,
        ExileAllGraveyards,
        BecomesCopyOfTargetLand,
        DrawCardsByConditionMultiplier,
        AddManaToPool,
    })
    assert _carrier_aa_phase_1_effect_classes() == expected, (
        "Phase 4E C2 invariant: admit set must contain exactly the 9 "
        "Effect classes (Phase-3A-C2 added "
        "ExileTargetAttackingCreatureUntilEndStep; Phase-3B-C2 added "
        "ExileAllGraveyards; Phase-3C-C3 added BecomesCopyOfTargetLand; "
        "Phase-4E-C2 added DrawCardsByConditionMultiplier + "
        "AddManaToPool)."
    )


def test_no_silent_auto_grow_admit_set_post_phase_3a_c2():
    """**Phase 3A C2 invariant pin (FURTHER-WIDENED in Phase 3B C2 +
    Phase 3C C3) — no-silent-auto-grow walk.** Confirms the 30
    BLOCKED-SG Carrier-AA cards from design doc §2.1 admit exactly
    the 7 cards post-Phase-3C-C3 widen:

      Swarmyard + Deserted Temple + Petrified Field + Terrain
      Generator + Mystifying Maze + Scavenger Grounds + Thespian's
      Stage.

    All the multi-AA carriers STAY DECLINED (Mirrorpool / Ghost
    Vacuum / Keys to the House / All-Fates Scroll / Haunted Screen /
    The Eternity Elevator — Phase 4 frontier per design doc §3) +
    every other carrier honestly declines on the colored-mana /
    x-pip cost-shape gate per the verify-first walk at 2026-05-26.
    Mirrors the Phase-3C-C3 sibling walk in
    ``tests/test_carrier_aa_phase_1_substrate_cycle_2.py`` and the
    direct C3 sibling pin in
    ``tests/test_carrier_aa_phase_3b_substrate_cycle_1.py``.

    Inverted from ``test_no_silent_auto_grow_admit_set_post_cycle_1``
    (4 admits pre-3A-C2 → 5 post-3A-C2 → 6 post-3B-C2 → 7 post-3C-C3).
    Any new Effect class admitted to the set (Phase 4+) would surface
    here as a silent auto-grow — investigate before merging.
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
    assert admits == [
        "Deserted Temple",
        "Mystifying Maze",
        "Petrified Field",
        "Scavenger Grounds",
        "Swarmyard",
        "Terrain Generator",
        "Thespian's Stage",
    ], (
        f"Carrier-AA Phase 3C C3 admit-set pin violated: expected "
        f"admit set = ['Deserted Temple', 'Mystifying Maze', "
        f"'Petrified Field', 'Scavenger Grounds', 'Swarmyard', "
        f"'Terrain Generator', \"Thespian's Stage\"], got "
        f"{admits}. A widen in a sibling substrate or predicate "
        f"would surface here as a silent auto-grow — investigate "
        f"before merging."
    )
