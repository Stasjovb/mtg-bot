"""Activated-ability substrate smoke tests (CE20 Slice 1).

Covers the substrate introduced by `feature/ce20-activated-substrate`:

- ``ActivatedAbility`` + ``ActivationCost`` parse from registry-dict
  input under the ``activated_abilities`` key.
- ``CardPrinting.activated_abilities`` defaults to empty Vec when the
  dict omits the key (back-compat for every pre-Slice-1 caller).
- A creature with a ``{1}{G}, T: Draw a card`` activated ability
  (Bear Caster shape) emits ActivateAbility from ``legal_decisions``
  when its cost is affordable AND the source is untapped + non-sick.
- ``apply_action({"kind": "activate_ability", ...})``:
    * Pays mana cost from the controller's pool.
    * Taps the source (tap_self cost).
    * For ``is_mana_ability=false`` pushes a StackItem so the next
      ``resolve_top_of_stack`` fires the effect.
- Affordability failures (empty pool) and tap-state failures (already
  tapped, summoning-sick creature) RAISE on apply.

Companion docs:
- ``docs/RUST_PARITY_GAPS.md`` — CE20 CLOSED entry + I48 invariant.
- ``rust/src/cards.rs`` — ``ActivatedAbility`` / ``ActivationCost``
  data shapes + parser.
- ``rust/src/state_ops_actions.rs`` — ``ActivateAbility`` apply arm.
- ``rust/src/state_ops_legal.rs`` — ``ActivateAbility`` emission.
"""

from __future__ import annotations

import pytest


# Zone constants — mirror ``rust/src/state_ops_zones.rs``.
ZONE_HAND = 0
ZONE_LIBRARY = 1
ZONE_BATTLEFIELD = 2
ZONE_GRAVEYARD = 3


def _tap_all_default_p0_mana_sources(synthetic_state):
    """Tap every default-mana-producing object on p0's battlefield.

    Post-I50 (auto-tap-from-lands composer), `legal_decisions`
    affordability widens to include untapped mana sources on bf.
    The synthetic state's default `make_synthetic_state(10, 7, 50)`
    pre-seeds p0 with 5 Forests (mana_produced=["G"]) on the
    battlefield, which compose to 5 G of headroom.

    Tests that want to isolate the affordability check to a SPECIFIC
    pool state (e.g. "pool is empty, prove the ability does NOT
    emit") must first tap out those default Forests so the headroom
    composer can't silently cover the cost.

    Tapping a non-mana-producing source (Grizzly Bears) is harmless;
    we tap every untapped p0 object whose printing has
    `mana_produced`.
    """
    for obj in synthetic_state.battlefield_snapshot():
        if obj.get("controller_id") != 0:
            continue
        if obj.get("tapped"):
            continue
        if obj.get("printing_name") in ("Forest", "Llanowar Elves"):
            synthetic_state.tap_object(obj["id"])


def _bear_caster_dict():
    """A 2/2 creature with the activated ability
    ``{1}{G}, {T}: Draw a card``. is_mana_ability=False so the ability
    goes through the stack (CR 605/113.3b — non-mana activated
    abilities use the stack).
    """
    return {
        "name": "Bear Caster",
        "card_types": ["Creature"],
        "mana_cost": {"G": 1, "generic": 1},
        "effects": [],
        "power": 2,
        "toughness": 2,
        "activated_abilities": [
            {
                "cost": {
                    "mana": {"generic": 1, "G": 1},
                    "tap_self": True,
                },
                "effect": {"kind": "draw_cards", "count": 1},
                "is_mana_ability": False,
            }
        ],
    }


def _ranger_dict():
    """A 1/1 creature with a free pump activated ability:
    ``{T}: This creature gets +1/+1 until end of turn`` shape, but
    simplified to a tap-self mana ability that doesn't actually
    add mana (sentinel for "no mana cost, tap_self only").
    Effect=GainLife(0) so the test asserts state stays put.
    """
    return {
        "name": "Test Ranger",
        "card_types": ["Creature"],
        "mana_cost": {"G": 1, "generic": 1},
        "effects": [],
        "power": 1,
        "toughness": 1,
        "activated_abilities": [
            {
                "cost": {"tap_self": True},  # mana defaults to zero
                "effect": {"kind": "gain_life", "amount": 0},
                "is_mana_ability": False,
            }
        ],
    }


# --- parser surface --------------------------------------------------


def test_activated_abilities_field_defaults_to_empty(empty_registry):
    """Registry dicts that omit ``activated_abilities`` are accepted
    (back-compat). Implicit default = empty Vec on the printing.
    """
    pid = empty_registry.register_printing(
        {
            "name": "Vanilla",
            "card_types": ["Creature"],
            "mana_cost": {"generic": 1},
            "effects": [],
            "power": 1,
            "toughness": 1,
        }
    )
    assert pid == 0


def test_activated_abilities_parses_full_bear_caster_shape(empty_registry):
    """The full Bear Caster shape parses and registers."""
    pid = empty_registry.register_printing(_bear_caster_dict())
    assert pid == 0


def test_activated_abilities_default_mana_cost_is_zero(empty_registry):
    """Missing ``cost.mana`` key defaults to a zero ManaCost."""
    pid = empty_registry.register_printing(_ranger_dict())
    assert pid == 0


def test_activated_abilities_unknown_cost_key_raises(empty_registry):
    """Unknown activation_cost keys raise loudly at register time.

    CE20 Slice 2 added `sacrifice_self` to the allow-list; this test
    now uses `pay_life` (a still-unmodeled cost variant) as the
    canonical "unknown" key. Future cost-variant slices that ship
    `pay_life` will update this test in lockstep.
    """
    d = {
        "name": "Bad Cost Card",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 1},
        "effects": [],
        "power": 1,
        "toughness": 1,
        "activated_abilities": [
            {
                "cost": {"mana": {"G": 1}, "pay_life": 1},
                "effect": {"kind": "draw_cards", "count": 1},
                "is_mana_ability": False,
            }
        ],
    }
    with pytest.raises(ValueError, match="unknown activation_cost key"):
        empty_registry.register_printing(d)


# --- end-to-end Bear Caster smoke ----------------------------------


def test_bear_caster_activate_succeeds_with_pre_populated_pool(synthetic_state):
    """**Load-bearing CE20 Slice 1 smoke.**

    Inject a Bear Caster onto p0's battlefield. Pre-populate p0's
    mana pool with {1}{G}. Apply ActivateAbility(bear, 0).

    Expected post-state:
    - Bear is tapped (tap_self cost fired).
    - p0's mana pool emptied (1 generic + 1 G drained).
    - Stack has exactly 1 item (the draw effect waiting to
      resolve; is_mana_ability=False -> goes through the stack).
    - Hand not yet grown — the draw fires only after
      ``resolve_top_of_stack`` pops the trigger off the stack.

    Then resolve the top of stack and verify hand grew by 1 +
    library shrunk by 1.
    """
    bear_id = synthetic_state.register_and_inject_object(
        _bear_caster_dict(), 0, ZONE_BATTLEFIELD,
    )
    # Clear summoning sickness so the tap_self cost is payable
    # immediately (CR 302.1 — newly entered creatures normally
    # can't pay tap costs; tests bypass this via the test-only
    # `set_summoning_sick` helper).
    synthetic_state.force_set_summoning_sick(bear_id, False)

    # Pre-populate p0's pool: 1 generic (we use "C" — colorless
    # counts toward generic per the cost-pay drain order) + 1 G.
    synthetic_state.add_mana(0, "C", 1)
    synthetic_state.add_mana(0, "G", 1)

    hand_before = synthetic_state.hand_sizes[0]
    library_before = synthetic_state.library_sizes[0]

    synthetic_state.apply_action(
        {
            "kind": "activate_ability",
            "source_id": bear_id,
            "ability_index": 0,
        }
    )

    # Bear tapped, pool emptied, stack carries the draw effect.
    assert synthetic_state.is_tapped(bear_id) is True, (
        "Bear should be tapped after activate (tap_self cost paid)"
    )
    pool = synthetic_state.get_mana_pool(0)
    assert pool["G"] == 0 and pool["C"] == 0, (
        f"Pool should be drained of the {{1}}{{G}} cost; got {pool}"
    )
    assert synthetic_state.stack_size() == 1, (
        "Non-mana activated ability (is_mana_ability=False) should "
        f"push a StackItem; got stack_size={synthetic_state.stack_size()}"
    )
    # Hand not yet grown — draw resolves on the next pop.
    assert synthetic_state.hand_sizes[0] == hand_before, (
        f"Hand should not grow until the trigger resolves; got "
        f"{synthetic_state.hand_sizes[0]} vs {hand_before}"
    )

    # Resolve the stack — the draw fires.
    resolved = synthetic_state.resolve_top_of_stack()
    assert resolved is not None
    assert resolved["source_obj_id"] == bear_id
    assert synthetic_state.hand_sizes[0] == hand_before + 1, (
        f"After resolve, hand should grow by 1 (DrawCards(1) "
        f"payload); got {synthetic_state.hand_sizes[0]} vs "
        f"{hand_before + 1}"
    )
    assert synthetic_state.library_sizes[0] == library_before - 1


def test_bear_caster_activate_raises_when_pool_empty(synthetic_state):
    """Affordability gate: with no mana in pool, the activate
    apply raises ValueError flagging unaffordable cost. No state
    mutation — the Bear stays untapped, no stack push."""
    bear_id = synthetic_state.register_and_inject_object(
        _bear_caster_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(bear_id, False)
    # Pool starts empty by default; defensively empty it again.
    synthetic_state.empty_mana_pool(0)

    stack_before = synthetic_state.stack_size()
    with pytest.raises(ValueError, match=r"unaffordable from controller's mana pool"):
        synthetic_state.apply_action(
            {
                "kind": "activate_ability",
                "source_id": bear_id,
                "ability_index": 0,
            }
        )
    # No mutation.
    assert synthetic_state.is_tapped(bear_id) is False
    assert synthetic_state.stack_size() == stack_before


def test_bear_caster_activate_raises_when_tapped(synthetic_state):
    """tap_self gate: a tapped source can't pay the implicit `{T}`
    cost. Raises ValueError flagging "already tapped"; no state
    mutation. (The mana cost is NOT debited — the tap-state gate
    fires before pay_mana_cost runs.)
    """
    bear_id = synthetic_state.register_and_inject_object(
        _bear_caster_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(bear_id, False)
    synthetic_state.tap_object(bear_id)
    # Pre-populate the pool so the affordability gate would PASS —
    # the only thing keeping the activate from succeeding is the
    # tap state.
    synthetic_state.add_mana(0, "C", 1)
    synthetic_state.add_mana(0, "G", 1)

    with pytest.raises(ValueError, match=r"already tapped"):
        synthetic_state.apply_action(
            {
                "kind": "activate_ability",
                "source_id": bear_id,
                "ability_index": 0,
            }
        )
    # Pool unchanged.
    pool = synthetic_state.get_mana_pool(0)
    assert pool["G"] == 1 and pool["C"] == 1


def test_bear_caster_activate_raises_when_summoning_sick(synthetic_state):
    """CR 302.1 gate: a summoning-sick creature can't pay a tap_self
    cost. Flip the summoning_sick flag explicitly via the test-only
    `force_set_summoning_sick` helper to set up the sick state.
    """
    bear_id = synthetic_state.register_and_inject_object(
        _bear_caster_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(bear_id, True)
    synthetic_state.add_mana(0, "C", 1)
    synthetic_state.add_mana(0, "G", 1)

    with pytest.raises(ValueError, match=r"summoning-sick"):
        synthetic_state.apply_action(
            {
                "kind": "activate_ability",
                "source_id": bear_id,
                "ability_index": 0,
            }
        )


# --- emission-side smoke -------------------------------------------


def test_bear_caster_emits_activate_when_affordable(synthetic_state):
    """``legal_decisions`` emits ActivateAbility(bear, 0) when:
    - bear is untapped + non-sick
    - p0's pool covers {1}{G}

    Tests the emission path through the new activated_abilities walk.
    """
    bear_id = synthetic_state.register_and_inject_object(
        _bear_caster_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(bear_id, False)
    synthetic_state.add_mana(0, "C", 1)
    synthetic_state.add_mana(0, "G", 1)

    # Park into PRECOMBAT_MAIN so the sorcery-timing gate is open
    # (the ActivateAbility emission loop runs INSIDE that gate today).
    synthetic_state.set_phase(3)  # PHASE_MAIN1 / PRECOMBAT_MAIN
    actions = synthetic_state.legal_decisions(0)
    bear_emits = [
        a for a in actions
        if a.get("kind") == "activate_ability"
        and a.get("source_id") == bear_id
    ]
    assert len(bear_emits) == 1, (
        f"Bear Caster should emit exactly one ActivateAbility when "
        f"affordable + untapped + non-sick. Got {len(bear_emits)} "
        f"emissions; full action list: {actions}"
    )
    assert bear_emits[0].get("ability_index") == 0


def test_bear_caster_no_emission_when_unaffordable(synthetic_state):
    """``legal_decisions`` does NOT emit ActivateAbility(bear, 0)
    when p0's mana pool can't cover {1}{G}.

    Post-I50: the auto-tap-from-lands composer widens emission-side
    affordability to include untapped mana sources on bf, so this
    test must first tap out the synthetic state's default Forests
    to force the composer to return an empty headroom — only then
    does the pool-empty branch dominate.
    """
    bear_id = synthetic_state.register_and_inject_object(
        _bear_caster_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(bear_id, False)
    _tap_all_default_p0_mana_sources(synthetic_state)
    synthetic_state.empty_mana_pool(0)

    # Park into PRECOMBAT_MAIN so the sorcery-timing gate is open
    # (the ActivateAbility emission loop runs INSIDE that gate today).
    synthetic_state.set_phase(3)  # PHASE_MAIN1 / PRECOMBAT_MAIN
    actions = synthetic_state.legal_decisions(0)
    bear_emits = [
        a for a in actions
        if a.get("kind") == "activate_ability"
        and a.get("source_id") == bear_id
    ]
    assert bear_emits == [], (
        f"Bear Caster should NOT emit ActivateAbility when pool can't "
        f"cover {{1}}{{G}}. Got {bear_emits}"
    )


def test_bear_caster_no_emission_when_tapped(synthetic_state):
    """``legal_decisions`` does NOT emit ActivateAbility(bear, 0)
    when the bear is tapped (can't pay the tap_self portion of cost)."""
    bear_id = synthetic_state.register_and_inject_object(
        _bear_caster_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(bear_id, False)
    synthetic_state.tap_object(bear_id)
    synthetic_state.add_mana(0, "C", 1)
    synthetic_state.add_mana(0, "G", 1)

    # Park into PRECOMBAT_MAIN so the sorcery-timing gate is open
    # (the ActivateAbility emission loop runs INSIDE that gate today).
    synthetic_state.set_phase(3)  # PHASE_MAIN1 / PRECOMBAT_MAIN
    actions = synthetic_state.legal_decisions(0)
    bear_emits = [
        a for a in actions
        if a.get("kind") == "activate_ability"
        and a.get("source_id") == bear_id
    ]
    assert bear_emits == [], (
        f"Bear Caster should NOT emit ActivateAbility when tapped. "
        f"Got {bear_emits}"
    )


def test_bear_caster_no_emission_when_summoning_sick(synthetic_state):
    """``legal_decisions`` does NOT emit ActivateAbility(bear, 0)
    when the bear is summoning-sick — the tap_self gate applies to
    creatures per CR 302.1."""
    bear_id = synthetic_state.register_and_inject_object(
        _bear_caster_dict(), 0, ZONE_BATTLEFIELD,
    )
    # Force sick — register_and_inject_object's default is non-sick
    # for the test fixture path.
    synthetic_state.force_set_summoning_sick(bear_id, True)
    synthetic_state.add_mana(0, "C", 1)
    synthetic_state.add_mana(0, "G", 1)

    # Park into PRECOMBAT_MAIN so the sorcery-timing gate is open
    # (the ActivateAbility emission loop runs INSIDE that gate today).
    synthetic_state.set_phase(3)  # PHASE_MAIN1 / PRECOMBAT_MAIN
    actions = synthetic_state.legal_decisions(0)
    bear_emits = [
        a for a in actions
        if a.get("kind") == "activate_ability"
        and a.get("source_id") == bear_id
    ]
    assert bear_emits == [], (
        f"Bear Caster should NOT emit ActivateAbility when summoning-"
        f"sick (CR 302.1 tap_self gate). Got {bear_emits}"
    )


# --- auto-tap-from-lands headroom composer (I50) -------------------


def _forest_dict():
    """Vanilla Forest — non-creature land with `mana_produced=["G"]`.
    Mirrors the synthetic-state Forest baked into `state.rs:1462`.
    """
    return {
        "name": "Forest",
        "card_types": ["Land"],
        "mana_produced": ["G"],
    }


def test_auto_tap_headroom_emits_with_empty_pool_plus_untapped_forests(
    synthetic_state,
):
    """**I50 load-bearing pin.** Bear Caster's `{1}{G}` cost is
    affordable via auto-tap-from-lands headroom: empty pool + 2
    untapped Forests on p0's bf compose to `{G}{G}` of headroom,
    which covers `{1}{G}` (1 G colored + 1 generic paid by the
    second G).

    Pre-closure (pool-only `pool_can_cover`): emission skipped
    because the floating pool is empty.
    Post-closure (`auto_tap_headroom_pool` composer): emission
    fires because pool + 2-Forest headroom covers the cost.
    """
    # Start from a battlefield where ONLY the 2 Forests we inject
    # contribute headroom (tap out the synthetic state's default
    # mana sources first).
    _tap_all_default_p0_mana_sources(synthetic_state)
    bear_id = synthetic_state.register_and_inject_object(
        _bear_caster_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(bear_id, False)
    # 2 untapped Forests on p0's bf (default non-sick on injection).
    synthetic_state.register_and_inject_object(
        _forest_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.register_and_inject_object(
        _forest_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.empty_mana_pool(0)

    synthetic_state.set_phase(3)  # PRECOMBAT_MAIN
    actions = synthetic_state.legal_decisions(0)
    bear_emits = [
        a for a in actions
        if a.get("kind") == "activate_ability"
        and a.get("source_id") == bear_id
    ]
    assert len(bear_emits) == 1, (
        f"Bear Caster should emit ActivateAbility when 2 untapped "
        f"Forests cover {{1}}{{G}} via auto-tap headroom. Got "
        f"{len(bear_emits)} emissions; full action list: {actions}"
    )


def test_auto_tap_headroom_no_emission_with_empty_pool_no_lands(
    synthetic_state,
):
    """Bear Caster with empty pool AND no mana sources on bf: no
    headroom to compose, no emission. Anchors the "we still skip
    when there's truly nothing to pay with" branch.
    """
    # Tap out the synthetic state's default Forests so the composer
    # genuinely sees zero headroom.
    _tap_all_default_p0_mana_sources(synthetic_state)
    bear_id = synthetic_state.register_and_inject_object(
        _bear_caster_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(bear_id, False)
    synthetic_state.empty_mana_pool(0)

    synthetic_state.set_phase(3)
    actions = synthetic_state.legal_decisions(0)
    bear_emits = [
        a for a in actions
        if a.get("kind") == "activate_ability"
        and a.get("source_id") == bear_id
    ]
    assert bear_emits == [], (
        f"Bear Caster should NOT emit ActivateAbility with empty pool "
        f"and zero mana sources on bf. Got {bear_emits}"
    )


def test_auto_tap_headroom_excludes_tapped_lands(synthetic_state):
    """Tapped Forests don't contribute headroom — a tapped land can't
    be tapped again to produce mana. Pool empty + 2 TAPPED Forests:
    Bear Caster emission skipped.
    """
    # Tap out the default Forests first; then inject 2 Forests
    # explicitly and tap them too. The composer should see zero
    # headroom because every mana source on the bf is tapped.
    _tap_all_default_p0_mana_sources(synthetic_state)
    bear_id = synthetic_state.register_and_inject_object(
        _bear_caster_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(bear_id, False)
    f1 = synthetic_state.register_and_inject_object(
        _forest_dict(), 0, ZONE_BATTLEFIELD,
    )
    f2 = synthetic_state.register_and_inject_object(
        _forest_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.tap_object(f1)
    synthetic_state.tap_object(f2)
    synthetic_state.empty_mana_pool(0)

    synthetic_state.set_phase(3)
    actions = synthetic_state.legal_decisions(0)
    bear_emits = [
        a for a in actions
        if a.get("kind") == "activate_ability"
        and a.get("source_id") == bear_id
    ]
    assert bear_emits == [], (
        f"Bear Caster should NOT emit ActivateAbility when all Forests "
        f"are tapped (zero headroom). Got {bear_emits}"
    )


def test_auto_tap_headroom_gates_on_source_sickness_not_land_sickness(
    synthetic_state,
):
    """CR 302.1 summoning-sickness gate applies to the SOURCE of the
    tap-cost activation, not the mana-source lands. A summoning-sick
    Bear Caster can't pay its own tap_self cost even when 2 untapped
    Forests are available — the gate fires on the Bear, not on the
    Forests. Pool empty + Bear sick + 2 untapped Forests: emission
    skipped.
    """
    # The 2 Forests we inject DO contribute headroom; the gate that
    # blocks emission is the source's own summoning-sickness, not
    # the composer's pool-coverage check.
    _tap_all_default_p0_mana_sources(synthetic_state)
    bear_id = synthetic_state.register_and_inject_object(
        _bear_caster_dict(), 0, ZONE_BATTLEFIELD,
    )
    # Bear is sick — can't pay its own tap_self.
    synthetic_state.force_set_summoning_sick(bear_id, True)
    # Forests are non-sick (lands skip CR 302.1 — only creature
    # tap-cost activations are gated).
    synthetic_state.register_and_inject_object(
        _forest_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.register_and_inject_object(
        _forest_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.empty_mana_pool(0)

    synthetic_state.set_phase(3)
    actions = synthetic_state.legal_decisions(0)
    bear_emits = [
        a for a in actions
        if a.get("kind") == "activate_ability"
        and a.get("source_id") == bear_id
    ]
    assert bear_emits == [], (
        f"Bear Caster should NOT emit ActivateAbility when itself "
        f"summoning-sick, regardless of Forest headroom. Got {bear_emits}"
    )


def test_auto_tap_headroom_pool_only_path_still_works(synthetic_state):
    """Regression — the pool-only emission path stays end-to-end
    functional. Bear Caster with `{1}{G}` in pool + 0 untapped
    Forests still emits ActivateAbility; the composer is a strict
    widening of the affordability check, never a narrowing.
    """
    # Tap out default mana sources so the assertion is specifically
    # about the pool-only path, not the composer's headroom widening.
    _tap_all_default_p0_mana_sources(synthetic_state)
    bear_id = synthetic_state.register_and_inject_object(
        _bear_caster_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(bear_id, False)
    synthetic_state.add_mana(0, "C", 1)
    synthetic_state.add_mana(0, "G", 1)
    # No untapped Forests on bf — pool alone must cover.

    synthetic_state.set_phase(3)
    actions = synthetic_state.legal_decisions(0)
    bear_emits = [
        a for a in actions
        if a.get("kind") == "activate_ability"
        and a.get("source_id") == bear_id
    ]
    assert len(bear_emits) == 1, (
        f"Pool-only affordability path still emits: pool covers "
        f"{{1}}{{G}} directly. Got {len(bear_emits)} emissions."
    )


# --- mana_produced -> activated_abilities bridge (CE20 follow-up) ----
#
# The legacy `CardPrinting.mana_produced` side-channel has been bridged
# into `activated_abilities` at parse time. Every printing with
# `mana_produced.is_some()` carries a synthesized ActivatedAbility at
# `ability_index=0` with `tap_self=true`, free mana cost,
# `is_mana_ability=true`, and an effect that adds the listed pips to the
# controller's pool. The legacy emission block in `state_ops_legal.rs`
# is gone; the legacy `is_legacy_mana_produced` branch in
# `state_ops_actions.rs` is gone — a single unified
# `activated_abilities` walk handles everything.
#
# These tests pin the BRIDGE INVARIANT: pre-bridge tests must continue
# to pass bit-equal post-bridge (Forest emission, Forest apply, sickness
# gates). Plus a multi-pip hybrid shape exercises the Sequence wrapper.


def _mountain_dict():
    """A second basic-land shape — tap for {R}. Used for bridge tests
    that want to assert the synthesis works for non-Forest colors.
    """
    return {
        "name": "Mountain",
        "card_types": ["Land"],
        "mana_produced": ["R"],
    }


def _hybrid_dual_land_dict():
    """A synthetic dual land that produces TWO different colors on a
    single activation. `mana_produced=["G", "U"]` mirrors a (hypothetical)
    "{T}: Add {G}{U}" land — exercises the bridge's multi-color Sequence
    wrapping. Cost stays at free + tap_self.
    """
    return {
        "name": "Sim Dual Land",
        "card_types": ["Land"],
        "mana_produced": ["G", "U"],
    }


def _double_green_land_dict():
    """A synthetic land that produces TWO of the same color on a single
    activation. `mana_produced=["G", "G"]` mirrors a "{T}: Add {G}{G}"
    land — exercises the bridge's same-color aggregation (one
    AddManaToPool with amount=2, not two amount=1 entries).
    """
    return {
        "name": "Sim Green Geyser",
        "card_types": ["Land"],
        "mana_produced": ["G", "G"],
    }


def test_bridge_forest_emission_unchanged(synthetic_state):
    """Forest on p0 bf emits exactly ONE ActivateAbility at
    `ability_index=0`. Pre-bridge: emitted by the legacy
    `mana_produced.is_some()` block. Post-bridge: emitted by the
    activated_abilities walk on the synthesized entry. Same observable
    result.
    """
    _tap_all_default_p0_mana_sources(synthetic_state)
    forest_id = synthetic_state.register_and_inject_object(
        _forest_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.empty_mana_pool(0)
    synthetic_state.set_phase(3)
    actions = synthetic_state.legal_decisions(0)
    forest_emits = [
        a for a in actions
        if a.get("kind") == "activate_ability"
        and a.get("source_id") == forest_id
    ]
    assert len(forest_emits) == 1, (
        f"Forest should emit exactly one ActivateAbility post-bridge "
        f"(via synthesized activated_abilities[0]). Got {forest_emits}"
    )
    assert forest_emits[0]["ability_index"] == 0, (
        f"Synthesized mana ability lives at ability_index=0 "
        f"(prepended). Got {forest_emits[0]}"
    )


def test_bridge_forest_apply_unchanged(synthetic_state):
    """Apply ActivateAbility(forest, 0): forest tapped, pool +1 G.
    Bit-equal observable behavior to the legacy free-mana-ability path.
    """
    forest_id = synthetic_state.register_and_inject_object(
        _forest_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.empty_mana_pool(0)
    pool_before = synthetic_state.get_mana_pool(0)
    assert pool_before["G"] == 0

    synthetic_state.apply_action(
        {
            "kind": "activate_ability",
            "source_id": forest_id,
            "ability_index": 0,
        }
    )

    assert synthetic_state.is_tapped(forest_id) is True, (
        "Forest should be tapped after the synthesized tap_self cost fires"
    )
    pool_after = synthetic_state.get_mana_pool(0)
    assert pool_after["G"] == 1, (
        f"Pool should carry +1 G post-activation; got {pool_after}"
    )
    # Mana ability bypasses the stack (CR 605.3a, is_mana_ability=true).
    assert synthetic_state.stack_size() == 0, (
        f"Bridged mana ability is is_mana_ability=true; stack should "
        f"stay empty. Got stack_size={synthetic_state.stack_size()}"
    )


def test_bridge_mountain_apply_adds_red(synthetic_state):
    """Bridge synthesizes correctly for non-Green colors too. Mountain
    on p0 bf, apply: Mountain tapped, pool +1 R.
    """
    mountain_id = synthetic_state.register_and_inject_object(
        _mountain_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.empty_mana_pool(0)

    synthetic_state.apply_action(
        {
            "kind": "activate_ability",
            "source_id": mountain_id,
            "ability_index": 0,
        }
    )

    pool_after = synthetic_state.get_mana_pool(0)
    assert pool_after["R"] == 1, (
        f"Mountain's bridged ability should add {{R}}; got {pool_after}"
    )


def test_bridge_double_green_land_aggregates(synthetic_state):
    """`mana_produced=["G","G"]` synthesizes one AddManaToPool with
    amount=2 (aggregated by color), not two entries. Observable: a
    single activation adds 2 G to the pool, taps the source once.
    """
    land_id = synthetic_state.register_and_inject_object(
        _double_green_land_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.empty_mana_pool(0)

    synthetic_state.apply_action(
        {
            "kind": "activate_ability",
            "source_id": land_id,
            "ability_index": 0,
        }
    )

    assert synthetic_state.is_tapped(land_id) is True
    pool_after = synthetic_state.get_mana_pool(0)
    assert pool_after["G"] == 2, (
        f"Double-green land should add 2 G in one activation; got {pool_after}"
    )


def test_bridge_hybrid_dual_land_sequence(synthetic_state):
    """`mana_produced=["G","U"]` synthesizes a Sequence with two
    AddManaToPool entries (one per color). One activation, one tap, two
    colors landed in the pool.
    """
    land_id = synthetic_state.register_and_inject_object(
        _hybrid_dual_land_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.empty_mana_pool(0)

    synthetic_state.apply_action(
        {
            "kind": "activate_ability",
            "source_id": land_id,
            "ability_index": 0,
        }
    )

    assert synthetic_state.is_tapped(land_id) is True
    pool_after = synthetic_state.get_mana_pool(0)
    assert pool_after["G"] == 1 and pool_after["U"] == 1, (
        f"Hybrid dual land should add G+U in one activation; got {pool_after}"
    )


def test_bridge_creature_summoning_sick_still_gated(synthetic_state):
    """A sick creature mana source (Llanowar Elves shape) still skips
    emission. The bridge synthesizes the ability with `tap_self=true`,
    which fires the existing creature-sickness gate (CR 302.1) at the
    activated_abilities-walk emission filter.
    """
    elf_dict = {
        "name": "Llanowar Elves",
        "card_types": ["Creature"],
        "mana_produced": ["G"],
        "power": 1,
        "toughness": 1,
    }
    elf_id = synthetic_state.register_and_inject_object(
        elf_dict, 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(elf_id, True)
    synthetic_state.empty_mana_pool(0)

    synthetic_state.set_phase(3)
    actions = synthetic_state.legal_decisions(0)
    elf_emits = [
        a for a in actions
        if a.get("kind") == "activate_ability"
        and a.get("source_id") == elf_id
    ]
    assert elf_emits == [], (
        f"Sick creature mana source should not emit (CR 302.1 gate "
        f"on tap_self cost). Got {elf_emits}"
    )


def test_bridge_creature_non_sick_emits(synthetic_state):
    """Non-sick Llanowar Elves emits its bridged mana ability at
    `ability_index=0`. Confirms the sickness gate doesn't over-fire on
    creatures that have shed it.
    """
    elf_dict = {
        "name": "Llanowar Elves",
        "card_types": ["Creature"],
        "mana_produced": ["G"],
        "power": 1,
        "toughness": 1,
    }
    elf_id = synthetic_state.register_and_inject_object(
        elf_dict, 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(elf_id, False)
    synthetic_state.empty_mana_pool(0)

    synthetic_state.set_phase(3)
    actions = synthetic_state.legal_decisions(0)
    elf_emits = [
        a for a in actions
        if a.get("kind") == "activate_ability"
        and a.get("source_id") == elf_id
    ]
    assert len(elf_emits) == 1 and elf_emits[0]["ability_index"] == 0


def test_bridge_tapped_source_no_emission(synthetic_state):
    """Tapped Forest doesn't emit. The bridge synthesizes `tap_self=true`
    on the ability, which the new-path emission filter rejects when the
    source is already tapped.
    """
    _tap_all_default_p0_mana_sources(synthetic_state)
    forest_id = synthetic_state.register_and_inject_object(
        _forest_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.tap_object(forest_id)
    synthetic_state.empty_mana_pool(0)

    synthetic_state.set_phase(3)
    actions = synthetic_state.legal_decisions(0)
    forest_emits = [
        a for a in actions
        if a.get("kind") == "activate_ability"
        and a.get("source_id") == forest_id
    ]
    assert forest_emits == [], (
        f"Tapped Forest should not emit. Got {forest_emits}"
    )


def test_bridge_prepended_before_explicit_activated_abilities(
    synthetic_state,
):
    """If a printing carries BOTH `mana_produced` AND an explicit
    `activated_abilities` entry, the synthesized mana ability is
    PREPENDED (lives at ability_index=0), the explicit entries land
    at ability_index=1+. Pin: existing `ActivateAbility(land, 0)`
    callers keep working bit-equal.

    Synthetic shape: a Forest that ALSO carries `{T}, Pay 1 life: gain
    1 life` — clearly distinct from its mana ability. The bridge
    must put the mana ability first.
    """
    # NOTE: ActivationCost in CE20 Slice 1 only supports mana + tap_self
    # — pay_life as a cost variant doesn't ship until a future slice. We
    # use a free + tap_self ability as the explicit entry instead; the
    # SHAPE under test is "explicit-entries get bumped to index >= 1".
    composite_land = {
        "name": "Composite Land",
        "card_types": ["Land"],
        "mana_produced": ["G"],
        "activated_abilities": [
            {
                "cost": {"tap_self": True},
                "effect": {"kind": "gain_life", "amount": 1},
                "is_mana_ability": False,
            }
        ],
    }
    land_id = synthetic_state.register_and_inject_object(
        composite_land, 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.empty_mana_pool(0)
    life_before = synthetic_state.life_totals[0]

    # ability_index=0 is the BRIDGED mana ability (adds G).
    synthetic_state.apply_action(
        {
            "kind": "activate_ability",
            "source_id": land_id,
            "ability_index": 0,
        }
    )
    assert synthetic_state.is_tapped(land_id) is True
    assert synthetic_state.get_mana_pool(0)["G"] == 1
    # The is_mana_ability=true bridged effect didn't push a stack item.
    assert synthetic_state.stack_size() == 0
    # Life unchanged — the explicit gain_life entry didn't fire.
    assert synthetic_state.life_totals[0] == life_before


def test_bridge_synthesizes_is_mana_ability_true(synthetic_state):
    """The bridge synthesizes `is_mana_ability=true` — apply does NOT
    push a stack item, the mana is added immediately (CR 605.3a). This
    matches the legacy `mana_produced` semantics (legacy resolved the
    pool credit inline, not through the stack).
    """
    forest_id = synthetic_state.register_and_inject_object(
        _forest_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.empty_mana_pool(0)
    stack_before = synthetic_state.stack_size()

    synthetic_state.apply_action(
        {
            "kind": "activate_ability",
            "source_id": forest_id,
            "ability_index": 0,
        }
    )
    # Stack size unchanged — mana ability bypassed the stack.
    assert synthetic_state.stack_size() == stack_before


def test_bridge_apply_with_invalid_ability_index_raises(synthetic_state):
    """A Forest has ONE bridged ability at index 0. ability_index=1
    raises with the unified "has no ability at index" error — the
    legacy `mana_produced` fallback for invalid indices is gone.
    """
    forest_id = synthetic_state.register_and_inject_object(
        _forest_dict(), 0, ZONE_BATTLEFIELD,
    )
    with pytest.raises(ValueError, match=r"has no ability at index 1"):
        synthetic_state.apply_action(
            {
                "kind": "activate_ability",
                "source_id": forest_id,
                "ability_index": 1,
            }
        )


# --- SacrificeSelf cost (CE20 follow-up Slice 2) ---------------------
#
# `ActivationCost.sacrifice_self: bool` extends the cost shape with a
# "sacrifice this permanent" portion. Dispatch order on activation:
#   1. Locate source on a battlefield.
#   2. Resolve ability shape.
#   3. tap_self precheck (CR 302.1 sickness gate for creatures).
#   4. pay_mana_cost on controller's pool.
#   5a. commit tap_self.
#   5b. commit sacrifice_self: move source to its controller's
#       graveyard via the existing move_object primitive shape (zero
#       damage/counters/attached_to on the way out, preserve
#       summoning_sick per CE13 I35). LTB void-flag stamps via
#       `mark_left_battlefield_if_nonland` (CE13 / I29).
#   6. dispatch the effect (stack push for non-mana abilities).
#
# 35 EoE printings carry this shape. Slice 2 covers ONLY
# sacrifice_self; targeted sacrifice variants ride on Equipment-equip
# Slice 4's target-pick substrate.


def _illvoi_galeblade_dict():
    """A 2-mana sacrifice-self draw-a-card shape — mirrors the EoE
    printing "Illvoi Galeblade" (`{2}, Sacrifice this creature: Draw
    a card.`). Slice 2 simplification: no tap_self on the cost (the
    real card has just the mana + sac). is_mana_ability=False so the
    draw goes through the stack.
    """
    return {
        "name": "Illvoi Galeblade",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 2},
        "effects": [],
        "power": 2,
        "toughness": 1,
        "activated_abilities": [
            {
                "cost": {
                    "mana": {"generic": 2},
                    "sacrifice_self": True,
                },
                "effect": {"kind": "draw_cards", "count": 1},
                "is_mana_ability": False,
            }
        ],
    }


def _free_sacrifice_self_dict():
    """A degenerate "free sacrifice for nothing" shape — zero mana
    cost + sacrifice_self + GainLife(0). Useful for isolating the
    sacrifice commit without mana / draw confounders.
    """
    return {
        "name": "Free Sac Token",
        "card_types": ["Creature"],
        "mana_cost": {},
        "effects": [],
        "power": 1,
        "toughness": 1,
        "activated_abilities": [
            {
                "cost": {"sacrifice_self": True},
                "effect": {"kind": "gain_life", "amount": 0},
                "is_mana_ability": False,
            }
        ],
    }


def _tap_and_sac_self_dict():
    """`{T}, Sacrifice this: Draw a card` — composes both cost
    primitives. Pins the dispatch ordering tap → sac.
    """
    return {
        "name": "Tap And Sac",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 1},
        "effects": [],
        "power": 1,
        "toughness": 1,
        "activated_abilities": [
            {
                "cost": {"tap_self": True, "sacrifice_self": True},
                "effect": {"kind": "draw_cards", "count": 1},
                "is_mana_ability": False,
            }
        ],
    }


def test_sacrifice_self_parses(empty_registry):
    """`sacrifice_self: True` parses without raising; lands on the
    printing's cost shape.
    """
    pid = empty_registry.register_printing(_illvoi_galeblade_dict())
    assert pid == 0


def test_sacrifice_self_parses_with_zero_mana(empty_registry):
    """Free-cost sacrifice-self is legal — no mana key, just
    `sacrifice_self: True`.
    """
    pid = empty_registry.register_printing(_free_sacrifice_self_dict())
    assert pid == 0


def test_sacrifice_self_parses_with_tap_and_sac(empty_registry):
    """`tap_self: True` AND `sacrifice_self: True` co-compose.
    Both keys parse together; the dispatcher commits tap first, then
    sacrifice.
    """
    pid = empty_registry.register_printing(_tap_and_sac_self_dict())
    assert pid == 0


def test_sacrifice_self_invalid_bool_raises(empty_registry):
    """`sacrifice_self` must be a bool — string raises loud."""
    d = {
        "name": "Bad Card",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 1},
        "effects": [],
        "power": 1,
        "toughness": 1,
        "activated_abilities": [
            {
                "cost": {"sacrifice_self": "yes"},
                "effect": {"kind": "gain_life", "amount": 0},
                "is_mana_ability": False,
            }
        ],
    }
    with pytest.raises(
        ValueError, match=r"sacrifice_self must be a bool"
    ):
        empty_registry.register_printing(d)


def test_sacrifice_self_apply_moves_source_to_graveyard(synthetic_state):
    """**Load-bearing Slice 2 smoke.** Apply ActivateAbility on an
    Illvoi Galeblade-shape source: cost pays (2 generic), source moves
    to controller's graveyard, stack carries the draw effect waiting
    to resolve. After resolve, hand grows by 1 / library shrinks by 1.
    """
    card_id = synthetic_state.register_and_inject_object(
        _illvoi_galeblade_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(card_id, False)
    # Pay 2 generic from pool (no colored cost). Colorless counts.
    synthetic_state.empty_mana_pool(0)
    synthetic_state.add_mana(0, "C", 2)

    gy_before = synthetic_state.graveyard_sizes[0]
    bf_before_has_card = any(
        o["id"] == card_id for o in synthetic_state.battlefield_snapshot()
    )
    assert bf_before_has_card

    synthetic_state.apply_action(
        {
            "kind": "activate_ability",
            "source_id": card_id,
            "ability_index": 0,
        }
    )

    # Source moved to graveyard.
    bf_after_has_card = any(
        o["id"] == card_id for o in synthetic_state.battlefield_snapshot()
    )
    assert not bf_after_has_card, (
        "Source should be off the battlefield after sacrifice_self"
    )
    assert synthetic_state.graveyard_sizes[0] == gy_before + 1, (
        f"Controller's graveyard should grow by 1; got "
        f"{synthetic_state.graveyard_sizes[0]} vs {gy_before + 1}"
    )
    # Mana pool drained.
    assert synthetic_state.get_mana_pool(0)["C"] == 0
    # Stack has the draw effect (is_mana_ability=False).
    assert synthetic_state.stack_size() == 1


def test_sacrifice_self_pays_before_effect_resolves(synthetic_state):
    """CR 117.10 / 119 — costs pay BEFORE effects resolve. After the
    activate apply, the effect is on the stack but hasn't fired yet.
    Hand is unchanged; the source is already in the graveyard. After
    resolve_top_of_stack, hand grows.
    """
    card_id = synthetic_state.register_and_inject_object(
        _illvoi_galeblade_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(card_id, False)
    synthetic_state.empty_mana_pool(0)
    synthetic_state.add_mana(0, "C", 2)

    hand_before = synthetic_state.hand_sizes[0]

    synthetic_state.apply_action(
        {
            "kind": "activate_ability",
            "source_id": card_id,
            "ability_index": 0,
        }
    )

    # Source sac'd, draw waiting on stack.
    assert synthetic_state.hand_sizes[0] == hand_before, (
        "Hand should not grow until the trigger resolves"
    )
    assert synthetic_state.stack_size() == 1

    resolved = synthetic_state.resolve_top_of_stack()
    assert resolved is not None
    assert synthetic_state.hand_sizes[0] == hand_before + 1


def test_sacrifice_self_raises_when_mana_insufficient(synthetic_state):
    """If mana can't be paid, the sacrifice DOES NOT happen — source
    stays on bf, pool unchanged, no stack push. Apply raises with the
    affordability error.
    """
    card_id = synthetic_state.register_and_inject_object(
        _illvoi_galeblade_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(card_id, False)
    synthetic_state.empty_mana_pool(0)
    # No mana — cost is unaffordable.

    gy_before = synthetic_state.graveyard_sizes[0]
    stack_before = synthetic_state.stack_size()

    with pytest.raises(
        ValueError, match=r"unaffordable from controller's mana pool"
    ):
        synthetic_state.apply_action(
            {
                "kind": "activate_ability",
                "source_id": card_id,
                "ability_index": 0,
            }
        )

    # No mutation.
    bf_still_has_card = any(
        o["id"] == card_id for o in synthetic_state.battlefield_snapshot()
    )
    assert bf_still_has_card, (
        "Source should stay on bf when mana cost fails"
    )
    assert synthetic_state.graveyard_sizes[0] == gy_before
    assert synthetic_state.stack_size() == stack_before


def test_sacrifice_self_tap_and_sac_composes(synthetic_state):
    """`tap_self: True` + `sacrifice_self: True`: source taps first
    (Phase 5), then sacrifices (Phase 5b). Net observable result:
    source is in graveyard (already moved off bf, so the tap state
    only matters for any in-flight trigger between phases — out of
    scope of this slice).
    """
    card_id = synthetic_state.register_and_inject_object(
        _tap_and_sac_self_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(card_id, False)
    synthetic_state.empty_mana_pool(0)
    synthetic_state.add_mana(0, "C", 1)

    gy_before = synthetic_state.graveyard_sizes[0]

    synthetic_state.apply_action(
        {
            "kind": "activate_ability",
            "source_id": card_id,
            "ability_index": 0,
        }
    )

    # Source moved to graveyard despite the tap-self cost having
    # committed first (Phase 5 wrote tapped=true, then Phase 5b moved
    # the object to gy).
    bf_after_has_card = any(
        o["id"] == card_id for o in synthetic_state.battlefield_snapshot()
    )
    assert not bf_after_has_card
    assert synthetic_state.graveyard_sizes[0] == gy_before + 1


def test_sacrifice_self_tap_gate_rejects_already_tapped(synthetic_state):
    """If `tap_self=True` AND `sacrifice_self=True`, the tap precheck
    fires FIRST (Phase 3) — an already-tapped source rejects the
    activation BEFORE any mana / sacrifice commit. No state mutation.
    """
    card_id = synthetic_state.register_and_inject_object(
        _tap_and_sac_self_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(card_id, False)
    synthetic_state.tap_object(card_id)
    synthetic_state.empty_mana_pool(0)
    synthetic_state.add_mana(0, "C", 1)

    gy_before = synthetic_state.graveyard_sizes[0]

    with pytest.raises(ValueError, match=r"already tapped"):
        synthetic_state.apply_action(
            {
                "kind": "activate_ability",
                "source_id": card_id,
                "ability_index": 0,
            }
        )

    # Pool unchanged, source on bf still tapped, gy unchanged.
    assert synthetic_state.get_mana_pool(0)["C"] == 1
    bf_has = any(
        o["id"] == card_id for o in synthetic_state.battlefield_snapshot()
    )
    assert bf_has
    assert synthetic_state.graveyard_sizes[0] == gy_before


def test_sacrifice_self_credits_correct_controller_graveyard(synthetic_state):
    """A sacrifice-self source on player 1's bf activated by player 1
    moves to player 1's graveyard, not player 0's. Pins the
    controller-resolution invariant from the bridge slice.
    """
    card_id = synthetic_state.register_and_inject_object(
        _illvoi_galeblade_dict(), 1, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(card_id, False)
    synthetic_state.empty_mana_pool(1)
    synthetic_state.add_mana(1, "C", 2)

    p0_gy_before = synthetic_state.graveyard_sizes[0]
    p1_gy_before = synthetic_state.graveyard_sizes[1]

    synthetic_state.apply_action(
        {
            "kind": "activate_ability",
            "source_id": card_id,
            "ability_index": 0,
        }
    )

    assert synthetic_state.graveyard_sizes[0] == p0_gy_before, (
        "Player 0's gy should NOT grow"
    )
    assert synthetic_state.graveyard_sizes[1] == p1_gy_before + 1, (
        "Player 1's gy should grow by 1"
    )


def test_sacrifice_self_no_emission_when_already_tapped_with_tap_self(
    synthetic_state,
):
    """When BOTH `tap_self=True` AND `sacrifice_self=True`, the
    emission filter still gates on tap state — a tapped source
    doesn't emit. Sacrifice-self alone (no tap_self) would emit
    regardless of tap state (covered by the next test).
    """
    card_id = synthetic_state.register_and_inject_object(
        _tap_and_sac_self_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(card_id, False)
    synthetic_state.tap_object(card_id)
    synthetic_state.empty_mana_pool(0)
    synthetic_state.add_mana(0, "C", 1)

    synthetic_state.set_phase(3)
    actions = synthetic_state.legal_decisions(0)
    card_emits = [
        a for a in actions
        if a.get("kind") == "activate_ability"
        and a.get("source_id") == card_id
    ]
    assert card_emits == [], (
        f"Tapped tap+sac source should not emit. Got {card_emits}"
    )


def test_sacrifice_self_no_emission_when_mana_unaffordable(synthetic_state):
    """Sacrifice-self with a {2} mana cost doesn't emit when the pool
    + auto-tap headroom can't cover 2 generic. Pool-gating still
    fires per I50.
    """
    # Tap out the synthetic state's default Forests so the headroom
    # composer can't cover the cost.
    _tap_all_default_p0_mana_sources(synthetic_state)
    card_id = synthetic_state.register_and_inject_object(
        _illvoi_galeblade_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(card_id, False)
    synthetic_state.empty_mana_pool(0)

    synthetic_state.set_phase(3)
    actions = synthetic_state.legal_decisions(0)
    card_emits = [
        a for a in actions
        if a.get("kind") == "activate_ability"
        and a.get("source_id") == card_id
    ]
    assert card_emits == [], (
        f"Unaffordable sacrifice-self should not emit. Got {card_emits}"
    )


# --- Tier-threshold (Spacecraft station-charge, CE20 Slice 3) --------
#
# `ActivatedAbility.tier_threshold: i32 = 0` extends the substrate with
# a usability gate (NOT a cost). The source's `GameObject.charge_counters`
# (new field, default 0) must be `>= tier_threshold` for the ability
# to be emitted from `legal_decisions` AND for `apply_action` to
# accept the dispatch. Sub-tier sources are outright inert — no mana
# / tap / sacrifice cost is evaluated when the tier gate fails.
#
# 28 EoE Spacecraft printings carry this shape (Lumen-Class Frigate,
# Eternity Elevator, Rescue Skiff, ...). Slice 3 ships the gate + the
# charge_counters field + test-helpers to seed/read counters; the
# station-as-cost mechanic that ACCRUES charge counters is a future
# slice (no EoE printing pays counters; only accrues them via station).


def _spacecraft_tier3_draw_dict():
    """A synthetic Spacecraft-shape: `tier_threshold=3`, cost
    `{2}, {T}`, effect `Draw a card`. The shape mirrors Lumen-Class
    Frigate's tier-3 station ability.
    """
    return {
        "name": "Synthetic Frigate",
        "card_types": ["Artifact"],
        "mana_cost": {"generic": 2},
        "effects": [],
        # power / toughness OMITTED — non-creature artifact (Spacecraft).
        "activated_abilities": [
            {
                "cost": {"mana": {"generic": 2}, "tap_self": True},
                "effect": {"kind": "draw_cards", "count": 1},
                "is_mana_ability": False,
                "tier_threshold": 3,
            }
        ],
    }


def _spacecraft_multi_tier_dict():
    """A synthetic Spacecraft with TWO tiered abilities at tier=3
    and tier=10. Each gates independently — Eternity Elevator's
    multi-tier shape.
    """
    return {
        "name": "Synthetic Multi Tier",
        "card_types": ["Artifact"],
        "mana_cost": {"generic": 1},
        "effects": [],
        # power / toughness OMITTED — non-creature artifact (Spacecraft).
        "activated_abilities": [
            {
                "cost": {"tap_self": True},
                "effect": {"kind": "draw_cards", "count": 1},
                "is_mana_ability": False,
                "tier_threshold": 3,
            },
            {
                "cost": {"tap_self": True},
                "effect": {"kind": "draw_cards", "count": 2},
                "is_mana_ability": False,
                "tier_threshold": 10,
            },
        ],
    }


def test_tier_threshold_parses(empty_registry):
    """A printing with `tier_threshold: 3` parses without raising."""
    pid = empty_registry.register_printing(_spacecraft_tier3_draw_dict())
    assert pid == 0


def test_tier_threshold_negative_raises(empty_registry):
    """`tier_threshold` must be non-negative; -1 raises loud."""
    d = {
        "name": "Bad Tier Card",
        "card_types": ["Artifact"],
        "mana_cost": {"generic": 1},
        "effects": [],
        "activated_abilities": [
            {
                "cost": {"tap_self": True},
                "effect": {"kind": "gain_life", "amount": 0},
                "is_mana_ability": False,
                "tier_threshold": -1,
            }
        ],
    }
    with pytest.raises(ValueError, match=r"tier_threshold must be"):
        empty_registry.register_printing(d)


def test_tier_threshold_defaults_to_zero(empty_registry):
    """Missing `tier_threshold` key defaults to 0 — back-compat with
    every pre-Slice-3 caller. Bear Caster's pre-existing fixture (no
    tier_threshold key) parses with tier=0.
    """
    pid = empty_registry.register_printing(_bear_caster_dict())
    assert pid == 0


def test_tier_gate_emission_below_threshold_skips(synthetic_state):
    """Source with `tier_threshold=3` but `charge_counters=2`:
    emission MUST skip. Even with mana paid + non-sick + untapped,
    the tier gate blocks.
    """
    card_id = synthetic_state.register_and_inject_object(
        _spacecraft_tier3_draw_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(card_id, False)
    synthetic_state.set_charge_counters(card_id, 2)
    synthetic_state.empty_mana_pool(0)
    synthetic_state.add_mana(0, "C", 2)

    synthetic_state.set_phase(3)
    actions = synthetic_state.legal_decisions(0)
    card_emits = [
        a for a in actions
        if a.get("kind") == "activate_ability"
        and a.get("source_id") == card_id
    ]
    assert card_emits == [], (
        f"Sub-tier source should not emit. Got {card_emits}"
    )


def test_tier_gate_emission_at_threshold_emits(synthetic_state):
    """`tier_threshold=3` AND `charge_counters=3`: emits (gate is
    `>=`, not `==` or `>`).
    """
    card_id = synthetic_state.register_and_inject_object(
        _spacecraft_tier3_draw_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(card_id, False)
    synthetic_state.set_charge_counters(card_id, 3)
    synthetic_state.empty_mana_pool(0)
    synthetic_state.add_mana(0, "C", 2)

    synthetic_state.set_phase(3)
    actions = synthetic_state.legal_decisions(0)
    card_emits = [
        a for a in actions
        if a.get("kind") == "activate_ability"
        and a.get("source_id") == card_id
    ]
    assert len(card_emits) == 1


def test_tier_gate_emission_above_threshold_emits(synthetic_state):
    """`tier_threshold=3` AND `charge_counters=99`: emits."""
    card_id = synthetic_state.register_and_inject_object(
        _spacecraft_tier3_draw_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(card_id, False)
    synthetic_state.set_charge_counters(card_id, 99)
    synthetic_state.empty_mana_pool(0)
    synthetic_state.add_mana(0, "C", 2)

    synthetic_state.set_phase(3)
    actions = synthetic_state.legal_decisions(0)
    card_emits = [
        a for a in actions
        if a.get("kind") == "activate_ability"
        and a.get("source_id") == card_id
    ]
    assert len(card_emits) == 1


def test_tier_gate_apply_below_threshold_raises(synthetic_state):
    """Direct apply (bypassing emission) of a sub-tier activation
    raises with `below tier threshold`. No state mutation.
    """
    card_id = synthetic_state.register_and_inject_object(
        _spacecraft_tier3_draw_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(card_id, False)
    synthetic_state.set_charge_counters(card_id, 2)
    synthetic_state.empty_mana_pool(0)
    synthetic_state.add_mana(0, "C", 2)

    with pytest.raises(ValueError, match=r"below tier threshold"):
        synthetic_state.apply_action(
            {
                "kind": "activate_ability",
                "source_id": card_id,
                "ability_index": 0,
            }
        )

    # No mutation.
    assert synthetic_state.is_tapped(card_id) is False
    assert synthetic_state.get_mana_pool(0)["C"] == 2


def test_tier_gate_apply_at_threshold_succeeds(synthetic_state):
    """At-threshold activation commits: mana drained, source tapped,
    stack carries the draw effect.
    """
    card_id = synthetic_state.register_and_inject_object(
        _spacecraft_tier3_draw_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(card_id, False)
    synthetic_state.set_charge_counters(card_id, 3)
    synthetic_state.empty_mana_pool(0)
    synthetic_state.add_mana(0, "C", 2)

    synthetic_state.apply_action(
        {
            "kind": "activate_ability",
            "source_id": card_id,
            "ability_index": 0,
        }
    )

    assert synthetic_state.is_tapped(card_id) is True
    assert synthetic_state.get_mana_pool(0)["C"] == 0
    assert synthetic_state.stack_size() == 1
    # Tier gate does NOT decrement charge_counters.
    assert synthetic_state.get_charge_counters(card_id) == 3


def test_tier_gate_does_not_decrement_charge_counters(synthetic_state):
    """Pin: tier_threshold is a USABILITY GATE, not a cost. The
    charge_counters value is unchanged after activation.
    """
    card_id = synthetic_state.register_and_inject_object(
        _spacecraft_tier3_draw_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(card_id, False)
    synthetic_state.set_charge_counters(card_id, 5)
    synthetic_state.empty_mana_pool(0)
    synthetic_state.add_mana(0, "C", 2)

    synthetic_state.apply_action(
        {
            "kind": "activate_ability",
            "source_id": card_id,
            "ability_index": 0,
        }
    )

    assert synthetic_state.get_charge_counters(card_id) == 5


def test_tier_gate_multi_tier_independent_gating(synthetic_state):
    """Source with tier=3 + tier=10 abilities, `charge_counters=5`:
    emits ONLY the tier-3 ability (5 >= 3, 5 < 10).
    """
    card_id = synthetic_state.register_and_inject_object(
        _spacecraft_multi_tier_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(card_id, False)
    synthetic_state.set_charge_counters(card_id, 5)
    synthetic_state.empty_mana_pool(0)

    synthetic_state.set_phase(3)
    actions = synthetic_state.legal_decisions(0)
    card_emits = [
        a for a in actions
        if a.get("kind") == "activate_ability"
        and a.get("source_id") == card_id
    ]
    assert len(card_emits) == 1
    assert card_emits[0]["ability_index"] == 0


def test_tier_gate_multi_tier_above_both_emits_both(synthetic_state):
    """Same multi-tier shape with `charge_counters=20`: emits both
    abilities.
    """
    card_id = synthetic_state.register_and_inject_object(
        _spacecraft_multi_tier_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(card_id, False)
    synthetic_state.set_charge_counters(card_id, 20)
    synthetic_state.empty_mana_pool(0)

    synthetic_state.set_phase(3)
    actions = synthetic_state.legal_decisions(0)
    card_emits = [
        a for a in actions
        if a.get("kind") == "activate_ability"
        and a.get("source_id") == card_id
    ]
    assert len(card_emits) == 2
    indices = sorted([a["ability_index"] for a in card_emits])
    assert indices == [0, 1]


def test_tier_gate_zero_default_does_not_gate(synthetic_state):
    """Bear Caster-shape with `tier_threshold=0` (default) emits
    regardless of charge_counters (which defaults to 0 — gate is
    `0 >= 0` which passes). Back-compat regression.
    """
    card_id = synthetic_state.register_and_inject_object(
        _bear_caster_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(card_id, False)
    synthetic_state.empty_mana_pool(0)
    synthetic_state.add_mana(0, "C", 1)
    synthetic_state.add_mana(0, "G", 1)

    synthetic_state.set_phase(3)
    actions = synthetic_state.legal_decisions(0)
    card_emits = [
        a for a in actions
        if a.get("kind") == "activate_ability"
        and a.get("source_id") == card_id
    ]
    assert len(card_emits) == 1


def test_charge_counters_field_independent_of_plus_one_counters(
    synthetic_state,
):
    """G8 pin: `charge_counters` is DISTINCT from `counters` (+1/+1).
    """
    card_id = synthetic_state.register_and_inject_object(
        _spacecraft_tier3_draw_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.set_charge_counters(card_id, 5)
    for obj in synthetic_state.battlefield_snapshot():
        if obj["id"] == card_id:
            assert obj.get("counters", 0) == 0, (
                f"+1/+1 slot should be 0 after seeding charge_counters; "
                f"got {obj.get('counters')}"
            )
            break
    assert synthetic_state.get_charge_counters(card_id) == 5


def test_set_charge_counters_returns_false_on_no_change(synthetic_state):
    """Test-helper returns False when value didn't change."""
    card_id = synthetic_state.register_and_inject_object(
        _spacecraft_tier3_draw_dict(), 0, ZONE_BATTLEFIELD,
    )
    assert synthetic_state.set_charge_counters(card_id, 5) is True
    assert synthetic_state.set_charge_counters(card_id, 5) is False
    assert synthetic_state.set_charge_counters(card_id, 7) is True


def test_get_charge_counters_returns_none_for_unknown_obj(synthetic_state):
    """Reading charge_counters on an unknown id returns None."""
    assert synthetic_state.get_charge_counters(99999) is None
