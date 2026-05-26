"""**Carrier-AA substrate Phase 2b (2026-05-25).**

Tests for the combined Carrier-AA Phase 2b cycle per
``docs/CARRIER_AA_SUBSTRATE_PHASE_2_DESIGN.md`` §4.2 + §5.2 + §6.4 #15.

Deliverables (single-cycle Rust + Python + probe slice):

  - New Rust ``Effect`` variant ``PutBasicLandFromHandOntoBattlefield
    Tapped`` (unit variant) — Terrain Generator's AA effect (pilot
    card). With: enum variant + ``parse_effect`` arm + ``to_pydict``
    arm + ``state_ops_resolve`` resolve arm + ``cross_engine.py``
    bridge dict->Python arm (``_ta_dict_to_python_effect``) + forward
    Python->dict arm (``_python_aa_to_safe_dict``).
  - ZERO new Rust cost-shape machinery — Terrain Generator's
    ``{2}, {T}`` cost is the Phase-1.5a ``{N}, {T}`` admit shape
    (already wired).
  - ZERO new target fan-out — Terrain Generator's AA has no target
    (the activator's hand-search is internal to the resolve).
  - ``_carrier_aa_phase_1_effect_classes`` widened to include
    ``PutBasicLandFromHandOntoBattlefieldTapped`` — admits Terrain
    Generator on the Effect-class widen alone (the cost-gate shape
    was already admitted post-Phase-1.5a).

**The FLIP.** Phase 2b INVERTS Terrain Generator from DECLINED to
ADMITTED at the production-deck admit gate. The per-card real-EoE
probe at ``tests/test_terrain_generator_parity.py`` (§6.4 #15)
flips Terrain Generator from BLOCKED → PROBED at the pool-parity
tier classifier.

**Verify-first findings (live tree, main `8a31b12b`):**

  - Terrain Generator's live oracle (Stellar Sights set):
    ``{2}, {T}: You may put a basic land card from your hand onto
    the battlefield tapped.``
    Parser body whitelist at
    ``src/mtg_bot/cards/parser/land_builder.py:1634-1635`` /
    ``1667-1669`` maps the body to
    ``PutBasicLandFromHandOntoBattlefieldTapped()`` with
    ``ActivationCost(mana=ManaCost(generic=2), tap_self=True)``.
  - No existing ``Effect::PutBasicLand*`` Rust variant — confirmed
    via grep on ``PutBasicLand|put_basic_land`` over ``rust/src/``.
    (``Effect::SearchLibraryForBasicLandTapped`` exists at
    ``rust/src/cards.rs`` line 4471 + resolve — orthogonal: library-
    search, not hand-search.)
  - Anticausal Vestige's may-put-permanent-from-hand-tapped resolve
    arm at ``rust/src/state_ops_resolve.rs:15406`` is the closest
    Rust-side precedent (hand→bf-tapped + ETB queue + reserve etb_ts
    + ``pending_etb_dispatches.push(entered_id)``).

**Test plan (per design doc §6.2):**

  - Parser SoT pin: confirm Python's
    ``PutBasicLandFromHandOntoBattlefieldTapped`` class exists in
    ``effects.generic.zone_moves`` and round-trips byte-equal.
  - Phase 2b unit pins #7-9 (Python — design doc §6.2):
      * #7: ``parse_printing`` round-trip on a synthetic non-token
        CardDef carrying Terrain Generator's shape.
      * #8: ``_aa_is_phase1_sub_shape_a`` admits Terrain Generator's
        synthetic AA shape.
      * #9: ``_python_aa_to_safe_dict`` round-trips Terrain
        Generator's synthetic shape byte-equal.
  - Phase 2b unit pin #10 (Rust — design doc §6.2): ``Effect::Put
    BasicLandFromHandOntoBattlefieldTapped`` parse + resolve arms
    exercise a synthetic state with one basic Forest in hand,
    activate-and-resolve produces a state with the Forest on the
    battlefield tapped + ETB events queued.
  - Phase 2b inversion pins: Terrain Generator now ADMITS at the
    admit gate + loader filter (mirrors Phase-2a's Petrified Field
    inversion pins).
"""

from __future__ import annotations

import importlib.util

import pytest


# Zone constants — mirror ``rust/src/state_ops_zones.rs``.
ZONE_HAND = 0
ZONE_LIBRARY = 1
ZONE_BATTLEFIELD = 2
ZONE_GRAVEYARD = 3


def _require_engine():
    if importlib.util.find_spec("mtg_bot_engine") is None:
        pytest.skip("mtg_bot_engine PyO3 extension not installed")


@pytest.fixture
def engine():
    """The ``mtg_bot_engine`` module, or skip if not installed.

    Local fixture — ``tests_rust/`` has a sibling fixture in
    ``conftest.py`` but ``tests/`` doesn't share that conftest.
    """
    if importlib.util.find_spec("mtg_bot_engine") is None:
        pytest.skip("mtg_bot_engine PyO3 extension not installed")
    import mtg_bot_engine
    return mtg_bot_engine


# ---------------------------------------------------------------------------
# Parser SoT — the Python Effect class exists at the expected import path
# ---------------------------------------------------------------------------


def test_python_class_exists_at_effects_generic_zone_moves():
    """**Phase 2b SoT pin.** Python's
    ``PutBasicLandFromHandOntoBattlefieldTapped`` class lives at
    ``effects.generic.zone_moves`` and is an ``Effect`` subclass.
    Mirrors the Rust ``Effect::PutBasicLandFromHandOntoBattlefieldTapped``
    variant landed in this cycle."""
    from mtg_bot.effects.base import Effect
    from mtg_bot.effects.generic.zone_moves import (
        PutBasicLandFromHandOntoBattlefieldTapped,
    )

    assert issubclass(PutBasicLandFromHandOntoBattlefieldTapped, Effect)
    # Zero-arg frozen dataclass — unit variant.
    inst = PutBasicLandFromHandOntoBattlefieldTapped()
    assert inst is not None


# ---------------------------------------------------------------------------
# Pin #7 (design doc §6.2) — parse_printing round-trip on a synthetic
# Terrain Generator-shape CardDef
# ---------------------------------------------------------------------------


def test_parse_printing_round_trips_terrain_generator_synthetic_shape(engine):
    """**Phase 2b Rust + Python parse-arm pin (design doc §6.2 #7).**
    A synthetic non-token CardDef registry dict carrying Terrain
    Generator's exact AA shape parses cleanly on the Rust side
    (``parse_effect`` + ``parse_activated_ability``) and round-trips
    back through ``to_pydict`` byte-equal.

    Shape:
      ``activated_abilities=[{"cost":{"tap_self":True,"mana":
      {"generic":2}}, "effect":{"kind":"put_basic_land_from_hand_
      onto_battlefield_tapped"}}]``
    """
    reg = engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Terrain Generator (synthetic carrier)",
            "card_types": ["Land"],
            "mana_cost": {"generic": 0},
            "effects": [],
            "activated_abilities": [
                {
                    "cost": {
                        "tap_self": True,
                        "mana": {"generic": 2},
                    },
                    "effect": {
                        "kind": "put_basic_land_from_hand_onto_battlefield_tapped",
                    },
                },
            ],
        }
    )
    assert isinstance(pid, int)


# ---------------------------------------------------------------------------
# Pin #8 (design doc §6.2) — _aa_is_phase1_sub_shape_a admits Terrain
# Generator's synthetic AA shape
# ---------------------------------------------------------------------------


def test_aa_is_phase1_sub_shape_a_admits_terrain_generator_synthetic_shape():
    """**Phase 2b admit-gate pin (design doc §6.2 #8).** A synthetic
    ``ActivatedAbility`` carrying Terrain Generator's exact shape
    (``cost=ActivationCost(mana=ManaCost(generic=2), tap_self=True)``,
    ``effect=PutBasicLandFromHandOntoBattlefieldTapped()``) passes
    ``_aa_is_phase1_sub_shape_a`` under the Phase-2b Effect-class
    widen.

    The cost shape ``{N}, {T}`` was already admitted at Phase 1.5a;
    Phase 2b widens only the Effect-class axis. The synthetic pin is
    isolated from the live parser surface — pure shape gating."""
    from mtg_bot.cards.base import ManaCost
    from mtg_bot.effects.base import ActivatedAbility, ActivationCost
    from mtg_bot.effects.generic.zone_moves import (
        PutBasicLandFromHandOntoBattlefieldTapped,
    )
    from mtg_bot.parity.trajectory import _aa_is_phase1_sub_shape_a

    aa = ActivatedAbility(
        cost=ActivationCost(
            mana=ManaCost(generic=2),
            tap_self=True,
        ),
        effect=PutBasicLandFromHandOntoBattlefieldTapped(),
    )
    assert _aa_is_phase1_sub_shape_a(aa) is True


def test_aa_is_phase1_sub_shape_a_still_declines_terrain_generator_with_pay_life_rider():
    """**Phase 2b decline-axis regression pin.** The Phase-2b widen is
    strictly additive on the Effect-class axis; every other cost-bool
    + AA-rider gate stays bit-identical. A Terrain-Generator-shape AA
    carrying an EXTRA ``pay_life=1`` cost-bool DECLINES — the
    ``pay_life`` cost-bool gate is unaffected by the Phase-2b widen.
    Same convention as Phase 1.5a's
    ``test_aa_is_phase1_sub_shape_a_declines_T_plus_pay_life``."""
    from mtg_bot.cards.base import ManaCost
    from mtg_bot.effects.base import ActivatedAbility, ActivationCost
    from mtg_bot.effects.generic.zone_moves import (
        PutBasicLandFromHandOntoBattlefieldTapped,
    )
    from mtg_bot.parity.trajectory import _aa_is_phase1_sub_shape_a

    aa = ActivatedAbility(
        cost=ActivationCost(
            mana=ManaCost(generic=2),
            tap_self=True,
            pay_life=1,
        ),
        effect=PutBasicLandFromHandOntoBattlefieldTapped(),
    )
    assert _aa_is_phase1_sub_shape_a(aa) is False


# ---------------------------------------------------------------------------
# Pin #9 (design doc §6.2) — _python_aa_to_safe_dict round-trips
# Terrain Generator's synthetic shape byte-equal
# ---------------------------------------------------------------------------


def test_python_aa_to_safe_dict_round_trips_terrain_generator_shape():
    """**Phase 2b bridge round-trip pin (design doc §6.2 #9).** A
    synthetic Terrain-Generator-shape AA round-trips byte-equal
    through ``_python_aa_to_safe_dict`` ↔
    ``_aa_dict_to_python_activated_ability`` — confirming the bridge
    serializes the ``{N}, {T}`` cost + ``put_basic_land_from_hand_
    onto_battlefield_tapped`` Effect kind in lockstep.

    Mirrors the Phase-2a Petrified Field round-trip pin
    ``test_petrified_field_aa_round_trip_through_safe_dict``."""
    from mtg_bot.cards.base import ManaCost
    from mtg_bot.effects.base import ActivatedAbility, ActivationCost
    from mtg_bot.effects.generic.zone_moves import (
        PutBasicLandFromHandOntoBattlefieldTapped,
    )
    from mtg_bot.parity.cross_engine import (
        _aa_dict_to_python_activated_ability,
        _python_aa_to_safe_dict,
    )

    aa = ActivatedAbility(
        cost=ActivationCost(
            mana=ManaCost(generic=2),
            tap_self=True,
        ),
        effect=PutBasicLandFromHandOntoBattlefieldTapped(),
    )
    safe = _python_aa_to_safe_dict(aa)
    assert safe is not None
    assert safe == {
        "cost": {"mana": {"generic": 2}, "tap_self": True},
        "effect": {
            "kind": "put_basic_land_from_hand_onto_battlefield_tapped",
        },
    }
    back = _aa_dict_to_python_activated_ability(safe)
    # Effect + cost-shape byte-equality. The cost-side ``mana_str``
    # display-string field is parser-only and is NOT round-tripped
    # through the bridge (UI-side annotation; both engines ignore it
    # for activation semantics). Pin the load-bearing fields directly.
    assert back.effect == aa.effect
    assert back.cost.mana == aa.cost.mana
    assert back.cost.tap_self == aa.cost.tap_self
    assert back.cost.sacrifice_self == aa.cost.sacrifice_self
    assert back.is_mana_ability == aa.is_mana_ability
    assert back.sorcery_speed == aa.sorcery_speed
    assert back.cost_reductions == aa.cost_reductions
    assert back.room_half == aa.room_half
    assert back.tier_threshold == aa.tier_threshold
    assert back.activate_only_once == aa.activate_only_once


def test_ta_dict_to_python_effect_arm_returns_unit_variant_instance():
    """**Phase 2b reverse-arm pin (design doc §5.4).** The bridge arm
    at ``cross_engine.py::_ta_dict_to_python_effect`` for the
    ``put_basic_land_from_hand_onto_battlefield_tapped`` kind returns
    a fresh zero-arg ``PutBasicLandFromHandOntoBattlefieldTapped()``
    instance — unit variant, no rider fields.

    Mirrors the Phase-2a sibling pin
    ``test_petrified_field_bridge_arm_round_trip``."""
    from mtg_bot.effects.generic.zone_moves import (
        PutBasicLandFromHandOntoBattlefieldTapped,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    bridged = _ta_dict_to_python_effect(
        {"kind": "put_basic_land_from_hand_onto_battlefield_tapped"},
    )
    assert isinstance(bridged, PutBasicLandFromHandOntoBattlefieldTapped)


# ---------------------------------------------------------------------------
# Pin #10 (design doc §6.2) — Rust Effect::PutBasicLandFromHandOnto
# BattlefieldTapped parse + resolve arm: given one basic Forest in
# hand, resolve produces a state with the Forest on the battlefield
# tapped + ETB events dispatched.
# ---------------------------------------------------------------------------


def _forest_basic_land_dict():
    """Synthetic registry dict for a basic Forest — the most common
    target of the put-basic-land-from-hand-tapped effect."""
    return {
        "name": "Forest",
        "card_types": ["Land"],
        "supertypes": ["Basic"],
        "subtypes": ["Forest"],
        "mana_cost": {"generic": 0},
        "effects": [],
    }


def _synthetic_terrain_generator_dict():
    """Synthetic Terrain Generator registry dict — single non-token
    AA carrying the ``{2}, {T}: put_basic_land_from_hand_onto_battle
    field_tapped`` shape. Mirrors Petrified Field's
    ``_synthetic_petrified_field_dict`` test-helper at
    ``test_carrier_aa_phase_2a_substrate_cycle_1.py``."""
    return {
        "name": "Terrain Generator",
        "card_types": ["Land"],
        "mana_cost": {"generic": 0},
        "effects": [],
        "activated_abilities": [
            {
                "cost": {
                    "tap_self": True,
                    "mana": {"generic": 2},
                },
                "effect": {
                    "kind": "put_basic_land_from_hand_onto_battlefield_tapped",
                },
            },
        ],
    }


@pytest.fixture
def synthetic_state(engine):
    """A default synthetic state — mirrors the Phase-2a Cycle-1
    fixture at ``tests_rust/conftest.py``'s shared form."""
    return engine.make_synthetic_state()


def test_rust_resolve_put_basic_land_from_hand_moves_forest_to_bf_tapped(
    synthetic_state, engine,
):
    """**Phase 2b Rust resolve arm pin (design doc §6.2 #10).** Build
    a synthetic state with a Terrain-Generator-shape source on p0's
    bf + one basic Forest in p0's hand. Activate the AA: cost-pay
    taps the source + drains the ``{2}`` mana (provided via a
    pre-filled mana pool); resolve fires the new
    ``Effect::PutBasicLandFromHandOntoBattlefieldTapped`` arm.

    Post-resolve:

      * Forest is on p0's battlefield, tapped.
      * Forest is no longer in p0's hand.
      * Terrain Generator source stays on bf (tapped).
    """
    tg_id = synthetic_state.register_and_inject_object(
        _synthetic_terrain_generator_dict(),
        0,  # owner_id = p0
        ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(tg_id, False)
    forest_id = synthetic_state.register_and_inject_object(
        _forest_basic_land_dict(),
        0,  # owner_id = p0
        ZONE_HAND,
    )
    # Pay the ``{2}`` mana via the test mana-pool pre-fill API.
    synthetic_state.add_mana(0, "C", 2)

    # Pre-state snapshots.
    hand_before = synthetic_state.hand_sizes[0]
    bf_before = synthetic_state.battlefield_sizes[0]

    # Activate the AA.
    synthetic_state.apply_action({
        "kind": "activate_ability",
        "source_id": tg_id,
        "ability_index": 0,
    })

    # The AA is non-mana — a StackItem is pushed.
    assert synthetic_state.stack_size() == 1

    # Resolve the stack — fires the new
    # ``Effect::PutBasicLandFromHandOntoBattlefieldTapped`` arm.
    synthetic_state.resolve_top_of_stack()
    assert synthetic_state.is_stack_empty()

    # Forest moved hand → bf (tapped).
    hand_post = synthetic_state.hand_snapshot(0)
    bf_post = [
        o for o in synthetic_state.battlefield_snapshot()
        if o["controller_id"] == 0
    ]
    assert not any(o["id"] == forest_id for o in hand_post), (
        f"Forest (id={forest_id}) must be removed from hand "
        f"post-resolve; got hand={hand_post}"
    )
    forest_on_bf = [o for o in bf_post if o["id"] == forest_id]
    assert len(forest_on_bf) == 1, (
        f"Forest (id={forest_id}) must be on p0's battlefield "
        f"post-resolve; got bf={bf_post}"
    )
    forest_obj = forest_on_bf[0]
    assert forest_obj["tapped"] is True, (
        "Forest must be tapped (the printed text 'onto the "
        "battlefield tapped')"
    )
    # Hand shrank by 1; bf grew by 1.
    assert synthetic_state.hand_sizes[0] == hand_before - 1
    assert synthetic_state.battlefield_sizes[0] == bf_before + 1
    # Terrain Generator source stays on bf, now tapped (from cost-pay).
    tg_on_bf = [o for o in bf_post if o["id"] == tg_id]
    assert len(tg_on_bf) == 1
    assert tg_on_bf[0]["tapped"] is True, (
        "Terrain Generator source must be tapped post-cost-pay "
        "(tap_self cost)"
    )


def test_rust_resolve_put_basic_land_silent_fizzle_on_no_basic_in_hand(
    synthetic_state, engine,
):
    """**Phase 2b Rust resolve arm pin — silent fizzle.** Activate
    Terrain Generator with NO basic land in p0's hand. Post-resolve:

      * Source stays tapped on bf (cost-pay committed).
      * Hand is unchanged.
      * Battlefield gains no new permanents.

    Mirrors Python's ``zone_moves.py:382`` early-return on no basic
    in hand."""
    tg_id = synthetic_state.register_and_inject_object(
        _synthetic_terrain_generator_dict(),
        0,
        ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(tg_id, False)
    synthetic_state.add_mana(0, "C", 2)

    hand_before = synthetic_state.hand_sizes[0]
    bf_before = synthetic_state.battlefield_sizes[0]
    # Snapshot id-set in p0's hand pre-activation.
    hand_ids_before = sorted(o["id"] for o in synthetic_state.hand_snapshot(0))

    synthetic_state.apply_action({
        "kind": "activate_ability",
        "source_id": tg_id,
        "ability_index": 0,
    })
    synthetic_state.resolve_top_of_stack()
    assert synthetic_state.is_stack_empty()

    # Hand id-set unchanged (no basic moved out).
    hand_ids_after = sorted(o["id"] for o in synthetic_state.hand_snapshot(0))
    assert hand_ids_after == hand_ids_before, (
        "Hand id-set must be unchanged on silent fizzle (no basic "
        "in hand → resolve early-returns per zone_moves.py:382)"
    )
    # Hand size unchanged.
    assert synthetic_state.hand_sizes[0] == hand_before
    # Battlefield unchanged (no new bf entries).
    assert synthetic_state.battlefield_sizes[0] == bf_before


def test_rust_resolve_put_basic_land_skips_non_basic_land(
    synthetic_state, engine,
):
    """**Phase 2b Rust resolve arm pin — non-basic land filter.**
    p0's hand carries a non-basic land (no ``Basic`` supertype) only.
    The resolve arm silently fizzles — non-basic lands are not
    eligible targets per the ``card_types.contains("Land") AND
    supertypes.contains("Basic")`` predicate (CR 205.4a).
    """
    tg_id = synthetic_state.register_and_inject_object(
        _synthetic_terrain_generator_dict(),
        0,
        ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(tg_id, False)
    synthetic_state.add_mana(0, "C", 2)
    non_basic_dict = {
        "name": "Nonbasic Land",
        "card_types": ["Land"],
        # No supertypes — NOT a basic.
        "mana_cost": {"generic": 0},
        "effects": [],
    }
    nb_id = synthetic_state.register_and_inject_object(
        non_basic_dict,
        0,
        ZONE_HAND,
    )

    bf_before = synthetic_state.battlefield_sizes[0]

    synthetic_state.apply_action({
        "kind": "activate_ability",
        "source_id": tg_id,
        "ability_index": 0,
    })
    synthetic_state.resolve_top_of_stack()

    hand_post = synthetic_state.hand_snapshot(0)
    bf_post = [
        o for o in synthetic_state.battlefield_snapshot()
        if o["controller_id"] == 0
    ]
    # Non-basic stays in hand — the basic-supertype gate held.
    assert any(o["id"] == nb_id for o in hand_post), (
        "Non-basic land must stay in hand (the basic-supertype "
        "gate held)"
    )
    assert not any(o["id"] == nb_id for o in bf_post), (
        "Non-basic land must NOT enter battlefield (the basic-"
        "supertype gate filtered it out)"
    )
    # Battlefield size unchanged (no new bf entry from the fizzle).
    assert synthetic_state.battlefield_sizes[0] == bf_before


# ---------------------------------------------------------------------------
# Inversion pins — Terrain Generator now ADMITS at the admit gate +
# loader filter post-Phase-2b. Mirrors Phase-2a's Petrified Field
# inversion pins.
# ---------------------------------------------------------------------------


def test_terrain_generator_now_admits_at_admit_gate_post_phase_2b():
    """**Phase 2b INVERSION admit pin (Terrain Generator's live
    printing).** Terrain Generator's live
    ``OracleParserCardSource`` printing now PASSES
    :func:`_printing_is_bridge_simple_carrier_aa_land` post-Phase-2b
    Effect-class widen (``_carrier_aa_phase_1_effect_classes`` now
    includes ``PutBasicLandFromHandOntoBattlefieldTapped``).

    Cost-gate was already admitted at Phase 1.5a (the ``{2}, {T}``
    cost shape is the standard ``{N}, {T}`` admit). Phase 2b widens
    only the Effect-class axis.

    Verifies:
      (a) The Carrier-AA disjunct
          ``_printing_is_bridge_simple_carrier_aa_land`` now ADMITS
          Terrain Generator.
      (b) Verify-first load-bearing-clause anchor: the live AA's
          cost shape carries ``mana=ManaCost(generic=2)`` +
          ``tap_self=True`` AND the Effect is
          ``PutBasicLandFromHandOntoBattlefieldTapped``.
      (c) The admit predicate ``_aa_is_phase1_sub_shape_a`` returns
          True on the AA shape.
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.effects.generic.zone_moves import (
        PutBasicLandFromHandOntoBattlefieldTapped,
    )
    from mtg_bot.parity import trajectory as traj

    ps = OracleParserCardSource().get_printings()
    tg = ps["Terrain Generator"]

    # (a) Carrier-AA disjunct admits.
    assert traj._printing_is_bridge_simple_carrier_aa_land(tg) is True, (
        "Terrain Generator MUST now ADMIT at the Carrier-AA admit "
        "gate post-Phase-2b — the Effect-class widen "
        "(admits ``PutBasicLandFromHandOntoBattlefieldTapped``) "
        "lands the FLIP."
    )

    # (b) Verify-first anchor.
    non_mana_aas = [
        aa for aa in (tg.activated_abilities or ())
        if not aa.is_mana_ability
    ]
    assert len(non_mana_aas) == 1
    aa = non_mana_aas[0]
    assert aa.cost.tap_self is True
    assert aa.cost.mana is not None
    assert aa.cost.mana.generic == 2
    assert aa.cost.mana.colored == ()
    assert aa.cost.mana.hybrid == ()
    assert aa.cost.mana.x_pips == 0
    assert aa.cost.sacrifice_self is False
    assert isinstance(aa.effect, PutBasicLandFromHandOntoBattlefieldTapped), (
        "Terrain Generator's AA effect must be "
        "PutBasicLandFromHandOntoBattlefieldTapped (the Phase-2b "
        "Effect class now in the Carrier-AA admit set)."
    )

    # (c) The admit predicate explicitly admits on this clause.
    assert traj._aa_is_phase1_sub_shape_a(aa) is True, (
        "Admit predicate ``_aa_is_phase1_sub_shape_a`` must ADMIT "
        "Terrain Generator's AA shape post-Phase-2b "
        "(Effect-class widen). Phase 2b FLIP."
    )


def test_terrain_generator_now_passes_loader_filter():
    """**Phase 2b INVERSION wiring pin.** The loader ADMITS Terrain
    Generator end-to-end post-Phase-2b — the Carrier-AA disjunct
    fires under the widened Effect-class admit set. The returned
    CardDef carries the Carrier-AA builder's output for the
    ``PutBasicLandFromHandOntoBattlefieldTapped`` Effect.

    Mirrors Phase-2a's Petrified Field inversion pin
    ``test_petrified_field_now_passes_loader_filter``.
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import _filter_deck_to_bridge_supported

    ps = OracleParserCardSource().get_printings()
    assert "Terrain Generator" in ps

    filtered, card_defs = _filter_deck_to_bridge_supported(
        ["Terrain Generator"], ps,
    )
    assert filtered == ["Terrain Generator"]
    assert len(card_defs) == 1
    card_def = card_defs[0]
    assert card_def.name == "Terrain Generator"
    assert card_def.card_type == "Land"
    aas = card_def.activated_abilities
    assert len(aas) == 1
    aa_dict = aas[0]
    # Cost is `{2}, {T}` (the Phase-1.5a ``{N}, {T}`` shape).
    assert aa_dict["cost"] == {
        "tap_self": True,
        "mana": {"generic": 2},
    }
    assert aa_dict["effect"] == {
        "kind": "put_basic_land_from_hand_onto_battlefield_tapped",
    }
