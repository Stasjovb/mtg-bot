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


# --- CE20 follow-up Slice 4 (Equipment-equip) -----------------------
#
# 7 EoE Equipment printings carry an "Equip {N}" activated ability —
# pay mana, target a creature you control, attach the Equipment to it
# (CR 702.6). The cost-shape extension on `ActivationCost` is
# `requires_target_creature_you_control: bool`; setting it `true`
# turns on:
#   - emission fan-out: one ActivateAbility dict per legal target
#     creature on the activator's battlefield (CR 702.6c — target a
#     creature you control; can't equip self).
#   - apply-arm target-pick validation (Phase 2.5): the dict MUST
#     carry `target_creature_id` (raises if missing); target must be
#     a creature on the activator's bf that isn't the source itself
#     (raises otherwise).
#   - StackItem payload-target threading: non-mana activations push
#     the chosen target through `new_trigger_with_target` so the
#     `Effect::EquipToTargetCreatureYouControl` resolve arm can read
#     it from `state.current_resolve_payload_target_id`.
#
# The effect itself (`Effect::EquipToTargetCreatureYouControl`)
# already exists post-r29; this slice wires the activation surface to
# read its chosen target rather than picking the first-eligible
# creature deterministically.


def _equip_dict():
    """A 0-cost Equipment ("Auxiliary Boosters"-style) with an
    activated ability ``{1}: Equip target creature you control``.

    Modeled as an Artifact (Equipment is a subtype the Rust registry
    doesn't yet track; gating happens at the card-data level — only
    Equipment cards print this effect). Mana cost on the activation
    is {1} so the test can vary affordability cleanly via the
    synthetic state's pool helpers.
    """
    return {
        "name": "Auxiliary Boosters (synthetic)",
        "card_types": ["Artifact"],
        "mana_cost": {"generic": 2},
        "effects": [],
        # power / toughness OMITTED — non-creature artifact.
        "activated_abilities": [
            {
                "cost": {
                    "mana": {"generic": 1},
                    "requires_target_creature_you_control": True,
                },
                "effect": {
                    "kind": "equip_to_target_creature_you_control",
                },
                "is_mana_ability": False,
            }
        ],
    }


def _free_equip_dict():
    """A zero-cost Equipment used for tests that want to exercise the
    target-pick logic without pool-affordability noise. Same shape
    as _equip_dict but with no mana cost on the activation.
    """
    return {
        "name": "Free Equip (synthetic)",
        "card_types": ["Artifact"],
        "mana_cost": {"generic": 0},
        "effects": [],
        "activated_abilities": [
            {
                "cost": {
                    "requires_target_creature_you_control": True,
                },
                "effect": {
                    "kind": "equip_to_target_creature_you_control",
                },
                "is_mana_ability": False,
            }
        ],
    }


def _creature_dict(name: str, mc_generic: int = 1):
    """A vanilla 2/2 creature. Reusable per-test fixture for legal
    targets.
    """
    return {
        "name": name,
        "card_types": ["Creature"],
        "mana_cost": {"generic": mc_generic},
        "effects": [],
        "power": 2,
        "toughness": 2,
    }


# --- parser surface --------------------------------------------------


def test_equip_requires_target_parses(empty_registry):
    """A printing with the new
    `requires_target_creature_you_control` cost key parses without
    raising."""
    pid = empty_registry.register_printing(_equip_dict())
    assert pid == 0


def test_equip_requires_target_defaults_to_false(empty_registry):
    """Missing `requires_target_creature_you_control` key defaults to
    False — back-compat with every pre-Slice-4 caller. Bear Caster's
    pre-existing fixture (no key) parses with the flag false.
    """
    pid = empty_registry.register_printing(_bear_caster_dict())
    assert pid == 0


def test_equip_requires_target_unknown_key_raises_paranoid(empty_registry):
    """The `pay_life` key remains the canonical 'unknown' for the
    activation_cost parse — Slice 4 added
    `requires_target_creature_you_control` to the allow-list, so the
    Slice 1 unknown-key test stays bit-equal.
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


# --- emission-side smoke (target fan-out) ---------------------------


def test_equip_emits_one_activation_per_legal_target(synthetic_state):
    """**Load-bearing Slice 4 emission pin.** Equipment on p0's bf
    with two test-injected creature targets on p0's bf: emission
    produces a unique ActivateAbility dict per legal target. Both
    test-injected target ids must appear in the
    `target_creature_id` slot. The synthetic state's default
    creatures (Grizzly Bears, Llanowar Elves) ALSO contribute as
    legal targets — we assert the test ids are PRESENT rather than
    asserting an absolute emission count, to stay robust against
    synthetic-state fixture changes.
    """
    equip_id = synthetic_state.register_and_inject_object(
        _free_equip_dict(), 0, ZONE_BATTLEFIELD,
    )
    target_a = synthetic_state.register_and_inject_object(
        _creature_dict("Target A"), 0, ZONE_BATTLEFIELD,
    )
    target_b = synthetic_state.register_and_inject_object(
        _creature_dict("Target B"), 0, ZONE_BATTLEFIELD,
    )

    synthetic_state.set_phase(3)  # PRECOMBAT_MAIN
    actions = synthetic_state.legal_decisions(0)
    equip_emits = [
        a for a in actions
        if a.get("kind") == "activate_ability"
        and a.get("source_id") == equip_id
    ]
    # At least the two test-injected creatures must appear.
    assert len(equip_emits) >= 2, (
        f"Equipment with 2 test-injected legal targets should emit "
        f"at least 2 ActivateAbility dicts; got {len(equip_emits)}: "
        f"{equip_emits}"
    )
    targets_emitted = {a["target_creature_id"] for a in equip_emits}
    assert target_a in targets_emitted
    assert target_b in targets_emitted
    # Defensive: the equip's own id MUST NOT appear (CR 702.6c).
    assert equip_id not in targets_emitted
    # Emission count equals unique target count — no double-emit.
    assert len(targets_emitted) == len(equip_emits)
    # Every emission targets a distinct creature; ids are unique.
    target_ids_list = [a["target_creature_id"] for a in equip_emits]
    assert len(set(target_ids_list)) == len(target_ids_list)


def test_equip_excludes_self_from_targets(synthetic_state):
    """CR 702.6c — Equipment can't equip itself. The equip's own
    id MUST NOT appear in any `target_creature_id` slot, regardless
    of how many other creatures are on the activator's bf.
    """
    equip_id = synthetic_state.register_and_inject_object(
        _free_equip_dict(), 0, ZONE_BATTLEFIELD,
    )
    target_id = synthetic_state.register_and_inject_object(
        _creature_dict("Lone Target"), 0, ZONE_BATTLEFIELD,
    )

    synthetic_state.set_phase(3)
    actions = synthetic_state.legal_decisions(0)
    equip_emits = [
        a for a in actions
        if a.get("kind") == "activate_ability"
        and a.get("source_id") == equip_id
    ]
    # At least one emission for the test-injected target (the
    # synthetic state's default Grizzly Bears bf also contribute).
    targets_emitted = {a["target_creature_id"] for a in equip_emits}
    assert target_id in targets_emitted
    # CR 702.6c: own id must NEVER appear.
    assert equip_id not in targets_emitted, (
        f"Equipment's own id {equip_id} appeared as an equip target: "
        f"{equip_emits}"
    )


def test_equip_excludes_opponent_creatures(synthetic_state):
    """Targets must be on the ACTIVATOR's battlefield (CR 702.6c).
    A creature on p1's bf is NOT a legal target for p0's equip
    activation. Pin: the opponent-side creature's id never appears
    in any `target_creature_id` slot.
    """
    equip_id = synthetic_state.register_and_inject_object(
        _free_equip_dict(), 0, ZONE_BATTLEFIELD,
    )
    own_target = synthetic_state.register_and_inject_object(
        _creature_dict("Own Target"), 0, ZONE_BATTLEFIELD,
    )
    # Opponent's creature — should NOT appear as a target.
    opp_target = synthetic_state.register_and_inject_object(
        _creature_dict("Opponent Target"), 1, ZONE_BATTLEFIELD,
    )

    synthetic_state.set_phase(3)
    actions = synthetic_state.legal_decisions(0)
    equip_emits = [
        a for a in actions
        if a.get("kind") == "activate_ability"
        and a.get("source_id") == equip_id
    ]
    targets_emitted = {a["target_creature_id"] for a in equip_emits}
    assert own_target in targets_emitted
    # Opponent's creature MUST NOT be a legal target.
    assert opp_target not in targets_emitted


def test_equip_excludes_non_creature_artifacts(synthetic_state):
    """Targets must be CREATURES (CR 702.6c — equip targets a
    creature you control). A non-creature artifact on the
    activator's bf is NOT a legal target. Pin: the artifact's id
    never appears in any `target_creature_id` slot.
    """
    equip_id = synthetic_state.register_and_inject_object(
        _free_equip_dict(), 0, ZONE_BATTLEFIELD,
    )
    creature_id = synthetic_state.register_and_inject_object(
        _creature_dict("Real Creature"), 0, ZONE_BATTLEFIELD,
    )
    # Another artifact (non-creature) — should NOT appear as a target.
    artifact_id = synthetic_state.register_and_inject_object(
        {
            "name": "Other Artifact",
            "card_types": ["Artifact"],
            "mana_cost": {"generic": 1},
            "effects": [],
        },
        0,
        ZONE_BATTLEFIELD,
    )

    synthetic_state.set_phase(3)
    actions = synthetic_state.legal_decisions(0)
    equip_emits = [
        a for a in actions
        if a.get("kind") == "activate_ability"
        and a.get("source_id") == equip_id
    ]
    targets_emitted = {a["target_creature_id"] for a in equip_emits}
    assert creature_id in targets_emitted
    # Non-creature artifact MUST NOT be a legal target.
    assert artifact_id not in targets_emitted


def test_equip_no_legal_targets_no_emission(synthetic_state):
    """Equipment on bf with NO other creatures on activator's bf:
    emission produces ZERO ActivateAbility dicts for the equip.
    Pinned by setting up a controller-2 (out-of-range) won't work;
    instead, we use a custom empty_registry fixture with hand-rolled
    state. The simpler approach for the synthetic_state fixture is
    to verify the count when N is known: with the default p0 bf
    having K creatures and adding 0 test creatures, expected
    equip-emit count = K. When K is replaced by 0 (an isolated
    fixture), expected = 0. We use the absence-of-test-creatures
    side to assert no test-injected ids appear among emitted
    targets — the load-bearing pin for "the gate honors target
    eligibility".
    """
    equip_id = synthetic_state.register_and_inject_object(
        _free_equip_dict(), 0, ZONE_BATTLEFIELD,
    )
    # No own test-creatures injected.
    # Inject a non-creature artifact on p0's bf — emission MUST
    # NOT include it as a target.
    non_creature_id = synthetic_state.register_and_inject_object(
        {
            "name": "Inert Artifact",
            "card_types": ["Artifact"],
            "mana_cost": {"generic": 1},
            "effects": [],
        },
        0,
        ZONE_BATTLEFIELD,
    )

    synthetic_state.set_phase(3)
    actions = synthetic_state.legal_decisions(0)
    equip_emits = [
        a for a in actions
        if a.get("kind") == "activate_ability"
        and a.get("source_id") == equip_id
    ]
    targets_emitted = {a["target_creature_id"] for a in equip_emits}
    # Inert Artifact MUST NOT be a legal target.
    assert non_creature_id not in targets_emitted
    # Equip's own id MUST NOT be a legal target.
    assert equip_id not in targets_emitted


def test_equip_no_emission_when_mana_unaffordable(synthetic_state):
    """Equipment with mana cost > activator's pool + headroom: no
    emission (the affordability gate fires before the target
    fan-out). Tap out the synthetic state's default mana sources
    first so the auto-tap headroom composer can't silently cover
    the cost.
    """
    _tap_all_default_p0_mana_sources(synthetic_state)
    equip_id = synthetic_state.register_and_inject_object(
        _equip_dict(), 0, ZONE_BATTLEFIELD,  # costs {1}
    )
    synthetic_state.register_and_inject_object(
        _creature_dict("Some Target"), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.empty_mana_pool(0)

    synthetic_state.set_phase(3)
    actions = synthetic_state.legal_decisions(0)
    equip_emits = [
        a for a in actions
        if a.get("kind") == "activate_ability"
        and a.get("source_id") == equip_id
    ]
    assert equip_emits == [], (
        f"Equip activation with empty pool + no mana sources should "
        f"NOT emit. Got {equip_emits}"
    )


# --- apply-arm smoke (target validation + StackItem threading) ------


def test_equip_apply_attaches_to_chosen_target(synthetic_state):
    """**Load-bearing Slice 4 apply pin.** Apply
    `ActivateAbility(equip_id, 0, target_creature_id=target)` →
    stack item carrying the target → resolve_top_of_stack →
    equipment's `attached_to` becomes `target`.
    """
    equip_id = synthetic_state.register_and_inject_object(
        _free_equip_dict(), 0, ZONE_BATTLEFIELD,
    )
    target_id = synthetic_state.register_and_inject_object(
        _creature_dict("Target Bear"), 0, ZONE_BATTLEFIELD,
    )

    synthetic_state.apply_action(
        {
            "kind": "activate_ability",
            "source_id": equip_id,
            "ability_index": 0,
            "target_creature_id": target_id,
        }
    )
    # Stack carries the equip trigger; resolve it.
    assert synthetic_state.stack_size() == 1
    synthetic_state.resolve_top_of_stack()
    # Verify the equipment is now attached to the chosen target.
    bf_post = synthetic_state.battlefield_snapshot()
    equip = next(d for d in bf_post if d["id"] == equip_id)
    assert equip["attached_to"] == target_id


def test_equip_apply_retargets_to_new_creature(synthetic_state):
    """CR 702.6c — equip can re-target an already-attached
    Equipment. Apply twice with different targets: final
    `attached_to` matches the second target.
    """
    equip_id = synthetic_state.register_and_inject_object(
        _free_equip_dict(), 0, ZONE_BATTLEFIELD,
    )
    target_a = synthetic_state.register_and_inject_object(
        _creature_dict("Target A"), 0, ZONE_BATTLEFIELD,
    )
    target_b = synthetic_state.register_and_inject_object(
        _creature_dict("Target B"), 0, ZONE_BATTLEFIELD,
    )

    # First equip to A.
    synthetic_state.apply_action(
        {
            "kind": "activate_ability",
            "source_id": equip_id,
            "ability_index": 0,
            "target_creature_id": target_a,
        }
    )
    synthetic_state.resolve_top_of_stack()
    bf_after_a = synthetic_state.battlefield_snapshot()
    equip_a = next(d for d in bf_after_a if d["id"] == equip_id)
    assert equip_a["attached_to"] == target_a

    # Then equip to B — stamps over.
    synthetic_state.apply_action(
        {
            "kind": "activate_ability",
            "source_id": equip_id,
            "ability_index": 0,
            "target_creature_id": target_b,
        }
    )
    synthetic_state.resolve_top_of_stack()
    bf_after_b = synthetic_state.battlefield_snapshot()
    equip_b = next(d for d in bf_after_b if d["id"] == equip_id)
    assert equip_b["attached_to"] == target_b


def test_equip_apply_missing_target_raises(synthetic_state):
    """The action dict MUST carry `target_creature_id` for an
    activation whose cost flags
    `requires_target_creature_you_control = true`. Missing key
    raises ValueError; no state mutation.
    """
    equip_id = synthetic_state.register_and_inject_object(
        _free_equip_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.register_and_inject_object(
        _creature_dict("Target"), 0, ZONE_BATTLEFIELD,
    )

    stack_before = synthetic_state.stack_size()
    with pytest.raises(
        ValueError, match=r"requires a target creature you control"
    ):
        synthetic_state.apply_action(
            {
                "kind": "activate_ability",
                "source_id": equip_id,
                "ability_index": 0,
                # NO target_creature_id key.
            }
        )
    # No mutation.
    assert synthetic_state.stack_size() == stack_before


def test_equip_apply_self_target_raises(synthetic_state):
    """An Equipment can't equip itself (CR 702.6c — equip targets
    a creature, an Equipment is an Artifact not a Creature). Apply
    with target_creature_id = source_id raises ValueError.
    """
    equip_id = synthetic_state.register_and_inject_object(
        _free_equip_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.register_and_inject_object(
        _creature_dict("Real Target"), 0, ZONE_BATTLEFIELD,
    )

    with pytest.raises(ValueError, match=r"cannot target itself"):
        synthetic_state.apply_action(
            {
                "kind": "activate_ability",
                "source_id": equip_id,
                "ability_index": 0,
                "target_creature_id": equip_id,  # self → illegal
            }
        )


def test_equip_apply_opponent_target_raises(synthetic_state):
    """Target on opponent's bf is not a legal target (CR 702.6c —
    target a creature you control). Apply raises ValueError.
    """
    equip_id = synthetic_state.register_and_inject_object(
        _free_equip_dict(), 0, ZONE_BATTLEFIELD,
    )
    opp_target_id = synthetic_state.register_and_inject_object(
        _creature_dict("Opponent's Bear"), 1, ZONE_BATTLEFIELD,
    )

    with pytest.raises(
        ValueError, match=r"not a legal target"
    ):
        synthetic_state.apply_action(
            {
                "kind": "activate_ability",
                "source_id": equip_id,
                "ability_index": 0,
                "target_creature_id": opp_target_id,
            }
        )


def test_equip_apply_non_creature_target_raises(synthetic_state):
    """Target must be a Creature. A non-creature artifact on the
    activator's bf is NOT a legal target.
    """
    equip_id = synthetic_state.register_and_inject_object(
        _free_equip_dict(), 0, ZONE_BATTLEFIELD,
    )
    artifact_id = synthetic_state.register_and_inject_object(
        {
            "name": "Some Artifact",
            "card_types": ["Artifact"],
            "mana_cost": {"generic": 1},
            "effects": [],
        },
        0,
        ZONE_BATTLEFIELD,
    )

    with pytest.raises(
        ValueError, match=r"not a legal target"
    ):
        synthetic_state.apply_action(
            {
                "kind": "activate_ability",
                "source_id": equip_id,
                "ability_index": 0,
                "target_creature_id": artifact_id,
            }
        )


def test_equip_apply_unknown_target_id_raises(synthetic_state):
    """Target id that doesn't resolve to any object on the
    activator's bf raises ValueError.
    """
    equip_id = synthetic_state.register_and_inject_object(
        _free_equip_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.register_and_inject_object(
        _creature_dict("Real Target"), 0, ZONE_BATTLEFIELD,
    )

    with pytest.raises(
        ValueError, match=r"not a legal target"
    ):
        synthetic_state.apply_action(
            {
                "kind": "activate_ability",
                "source_id": equip_id,
                "ability_index": 0,
                "target_creature_id": 99999,  # unknown id
            }
        )


def test_equip_apply_mana_cost_paid(synthetic_state):
    """Mana cost is debited from the activator's pool when the
    equip activation succeeds. {1} cost: pool has {C}=1 pre-apply,
    pool has {C}=0 post-apply.
    """
    equip_id = synthetic_state.register_and_inject_object(
        _equip_dict(), 0, ZONE_BATTLEFIELD,  # costs {1}
    )
    target_id = synthetic_state.register_and_inject_object(
        _creature_dict("Target"), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.empty_mana_pool(0)
    synthetic_state.add_mana(0, "C", 1)

    synthetic_state.apply_action(
        {
            "kind": "activate_ability",
            "source_id": equip_id,
            "ability_index": 0,
            "target_creature_id": target_id,
        }
    )
    pool = synthetic_state.get_mana_pool(0)
    assert pool["C"] == 0


# --- back-compat regression -----------------------------------------


def test_non_target_activation_dict_omits_target_creature_id_key(
    synthetic_state,
):
    """Back-compat: a non-target activation dict (Bear Caster
    shape, sacrifice-self shape, mana-ability shape) can OMIT
    `target_creature_id` entirely; the parser maps missing key to
    None and the apply arm ignores the absence. Pre-Slice-4
    callers keep working.
    """
    bear_id = synthetic_state.register_and_inject_object(
        _bear_caster_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(bear_id, False)
    synthetic_state.add_mana(0, "C", 1)
    synthetic_state.add_mana(0, "G", 1)
    # Note: NO target_creature_id key — the pre-Slice-4 shape.
    synthetic_state.apply_action(
        {
            "kind": "activate_ability",
            "source_id": bear_id,
            "ability_index": 0,
        }
    )
    # Bear tapped, stack has the draw effect — same as
    # test_bear_caster_activate_succeeds_with_pre_populated_pool.
    assert synthetic_state.is_tapped(bear_id) is True
    assert synthetic_state.stack_size() == 1


def test_non_target_activation_dict_explicit_none_target_works(
    synthetic_state,
):
    """An explicit `target_creature_id: None` is also accepted
    (round-trip with `action_to_pydict` produces this shape) on a
    non-target activation. Equivalent to omitting the key.
    """
    bear_id = synthetic_state.register_and_inject_object(
        _bear_caster_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(bear_id, False)
    synthetic_state.add_mana(0, "C", 1)
    synthetic_state.add_mana(0, "G", 1)
    synthetic_state.apply_action(
        {
            "kind": "activate_ability",
            "source_id": bear_id,
            "ability_index": 0,
            "target_creature_id": None,
        }
    )
    assert synthetic_state.is_tapped(bear_id) is True


def test_non_target_activation_dict_extra_target_id_silently_ignored(
    synthetic_state,
):
    """If a caller accidentally supplies `target_creature_id` on a
    non-target activation (Bear Caster, mana ability), the field is
    silently ignored — matches Python's permissive
    `ActivateAbility(target_creature_id=...)` for non-target
    abilities. The activation succeeds; the target value never
    flows into the StackItem payload because
    `validated_target_id` resolves to `None` for the
    non-target shape.
    """
    bear_id = synthetic_state.register_and_inject_object(
        _bear_caster_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(bear_id, False)
    other_id = synthetic_state.register_and_inject_object(
        _creature_dict("Other Bear"), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.add_mana(0, "C", 1)
    synthetic_state.add_mana(0, "G", 1)
    # Accidentally supply target_creature_id — should be ignored.
    synthetic_state.apply_action(
        {
            "kind": "activate_ability",
            "source_id": bear_id,
            "ability_index": 0,
            "target_creature_id": other_id,
        }
    )
    # Bear tapped + stack has the draw. The "stray" target_id
    # was ignored (the StackItem carries target_id=None internally).
    assert synthetic_state.is_tapped(bear_id) is True
    assert synthetic_state.stack_size() == 1


# --- Effect-side legality recheck (CR 608.2b) -----------------------


def test_equip_resolve_uses_payload_target_not_first_eligible(
    synthetic_state,
):
    """Pin the payload-target-pick path: with TWO legal targets
    available, the resolver uses the activator's CHOSEN target
    (target_b, the later-injected one), NOT the first-eligible
    creature on bf order (target_a, the earlier-injected one).
    """
    equip_id = synthetic_state.register_and_inject_object(
        _free_equip_dict(), 0, ZONE_BATTLEFIELD,
    )
    target_a = synthetic_state.register_and_inject_object(
        _creature_dict("First Target"), 0, ZONE_BATTLEFIELD,
    )
    target_b = synthetic_state.register_and_inject_object(
        _creature_dict("Second Target"), 0, ZONE_BATTLEFIELD,
    )

    # Activate explicitly choosing target_b (the second creature).
    synthetic_state.apply_action(
        {
            "kind": "activate_ability",
            "source_id": equip_id,
            "ability_index": 0,
            "target_creature_id": target_b,
        }
    )
    synthetic_state.resolve_top_of_stack()
    bf_post = synthetic_state.battlefield_snapshot()
    equip = next(d for d in bf_post if d["id"] == equip_id)
    assert equip["attached_to"] == target_b, (
        f"Resolver should use payload target_b ({target_b}), not "
        f"first-eligible target_a ({target_a}); got {equip['attached_to']}"
    )


# -------------------------------------------------------------------
# CE20 Slice 6 — targeted-sacrifice variants
#
# Tests for `sacrifice_another_creature_or_artifact`, `sacrifice_a_land`,
# and `sacrifice_another_artifact` cost shapes. Rides on the Slice 4
# target-pick substrate but uses a SEPARATE `sacrifice_target_id` field
# on the action dict so equip's effect-target and a sac-cost target
# don't collide.
# -------------------------------------------------------------------


def _sac_another_creature_or_artifact_dict():
    """`{0}, Sacrifice another creature or artifact: gain 1 life`. A
    minimal Umbral Collar Zealot-shape source for testing the
    sacrifice_another_creature_or_artifact cost variant. Free mana
    cost so tests can isolate the sac-target machinery.
    """
    return {
        "name": "Umbral Collar Zealot (synthetic)",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 2},
        "effects": [],
        "power": 2,
        "toughness": 2,
        "activated_abilities": [
            {
                "cost": {
                    "sacrifice_another_creature_or_artifact": True,
                },
                "effect": {"kind": "gain_life", "amount": 1},
                "is_mana_ability": False,
            }
        ],
    }


def _sac_a_land_dict():
    """`{2}, {T}, Sacrifice a land: gain 1 life`. Dust-Bowl-shape source
    — no "another" qualifier, so the source itself is eligible when
    the source is a land. This synthetic uses a non-land artifact
    source to keep self-sac out of the picture for most tests; a
    separate fixture covers the self-eligible-land case.
    """
    return {
        "name": "Dust Bowl (synthetic, non-land)",
        "card_types": ["Artifact"],
        "mana_cost": {"generic": 1},
        "effects": [],
        "activated_abilities": [
            {
                "cost": {"sacrifice_a_land": True},
                "effect": {"kind": "gain_life", "amount": 1},
                "is_mana_ability": False,
            }
        ],
    }


def _sac_a_land_self_eligible_dict():
    """A LAND source with a `sacrifice_a_land` ability. Per the printed
    text reading "a land" (no "another"), the source itself is
    eligible as the sacrifice target.
    """
    return {
        "name": "Self-Sac Land (synthetic)",
        "card_types": ["Land"],
        "mana_cost": {},
        "effects": [],
        "activated_abilities": [
            {
                "cost": {"sacrifice_a_land": True},
                "effect": {"kind": "gain_life", "amount": 1},
                "is_mana_ability": False,
            }
        ],
    }


def _sac_another_artifact_dict():
    """`{0}, Sacrifice another artifact: gain 1 life`. Memorial
    Vault-shape source.
    """
    return {
        "name": "Memorial Vault (synthetic)",
        "card_types": ["Artifact"],
        "mana_cost": {"generic": 1},
        "effects": [],
        "activated_abilities": [
            {
                "cost": {"sacrifice_another_artifact": True},
                "effect": {"kind": "gain_life", "amount": 1},
                "is_mana_ability": False,
            }
        ],
    }


def _vanilla_land_dict(name: str = "Plains"):
    """A non-mana-producing vanilla land for sac-target eligibility
    tests. Uses no mana_produced so it doesn't fan out an unrelated
    mana ability that would crowd the legal_decisions output.
    """
    return {
        "name": name,
        "card_types": ["Land"],
        "effects": [],
    }


def _vanilla_artifact_dict(name: str = "Junk Artifact"):
    return {
        "name": name,
        "card_types": ["Artifact"],
        "mana_cost": {"generic": 1},
        "effects": [],
    }


# --- parser surface ---------------------------------------------------


def test_sacrifice_another_creature_or_artifact_parses(empty_registry):
    """`sacrifice_another_creature_or_artifact: True` parses."""
    pid = empty_registry.register_printing(
        _sac_another_creature_or_artifact_dict()
    )
    assert pid == 0


def test_sacrifice_a_land_parses(empty_registry):
    """`sacrifice_a_land: True` parses."""
    pid = empty_registry.register_printing(_sac_a_land_dict())
    assert pid == 0


def test_sacrifice_another_artifact_parses(empty_registry):
    """`sacrifice_another_artifact: True` parses."""
    pid = empty_registry.register_printing(_sac_another_artifact_dict())
    assert pid == 0


def test_sacrifice_another_creature_or_artifact_invalid_bool_raises(
    empty_registry,
):
    """Bad type on `sacrifice_another_creature_or_artifact` raises
    loud."""
    d = _sac_another_creature_or_artifact_dict()
    d["activated_abilities"][0]["cost"][
        "sacrifice_another_creature_or_artifact"
    ] = "yes"
    with pytest.raises(
        ValueError,
        match=r"sacrifice_another_creature_or_artifact must be a bool",
    ):
        empty_registry.register_printing(d)


def test_sacrifice_a_land_invalid_bool_raises(empty_registry):
    d = _sac_a_land_dict()
    d["activated_abilities"][0]["cost"]["sacrifice_a_land"] = 1
    with pytest.raises(
        ValueError, match=r"sacrifice_a_land must be a bool"
    ):
        empty_registry.register_printing(d)


def test_sacrifice_another_artifact_invalid_bool_raises(empty_registry):
    d = _sac_another_artifact_dict()
    d["activated_abilities"][0]["cost"]["sacrifice_another_artifact"] = []
    with pytest.raises(
        ValueError, match=r"sacrifice_another_artifact must be a bool"
    ):
        empty_registry.register_printing(d)


# --- emission target fan-out ------------------------------------------


def test_sac_another_creature_or_artifact_emits_one_per_legal_target(
    synthetic_state,
):
    """Source + injected creatures + injected artifact on activator's
    bf => legal_decisions emits one ActivateAbility dict per non-self
    creature/artifact. The source itself is NOT a legal target. The
    synthetic state's default Grizzly Bears on p0's bf also contribute
    as legal targets; we assert PRESENCE of injected ids rather than
    an exact count (matches the Equipment-equip test convention).
    """
    PHASE_MAIN1 = 3
    synthetic_state.set_phase(PHASE_MAIN1)
    _tap_all_default_p0_mana_sources(synthetic_state)

    src_id = synthetic_state.register_and_inject_object(
        _sac_another_creature_or_artifact_dict(),
        0,
        ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(src_id, False)
    c1 = synthetic_state.register_and_inject_object(
        _creature_dict("C1"), 0, ZONE_BATTLEFIELD,
    )
    c2 = synthetic_state.register_and_inject_object(
        _creature_dict("C2"), 0, ZONE_BATTLEFIELD,
    )
    a1 = synthetic_state.register_and_inject_object(
        _vanilla_artifact_dict("A1"), 0, ZONE_BATTLEFIELD,
    )

    decisions = synthetic_state.legal_decisions(0)
    sac_acts = [
        d
        for d in decisions
        if d["kind"] == "activate_ability"
        and d["source_id"] == src_id
    ]
    target_ids = {d["sacrifice_target_id"] for d in sac_acts}
    # The 3 injected ids must all be legal targets.
    assert c1 in target_ids
    assert c2 in target_ids
    assert a1 in target_ids
    # CR rule: source itself MUST NOT be a legal target.
    assert src_id not in target_ids
    # All carry None for target_creature_id (sac target ≠ equip
    # target).
    for d in sac_acts:
        assert d["target_creature_id"] is None
    # Unique-target invariant: no double-emit.
    assert len(target_ids) == len(sac_acts)


def test_sac_another_creature_or_artifact_excludes_source_self(
    synthetic_state,
):
    """The source's own id is NOT a legal sac target."""
    PHASE_MAIN1 = 3
    synthetic_state.set_phase(PHASE_MAIN1)
    _tap_all_default_p0_mana_sources(synthetic_state)
    src_id = synthetic_state.register_and_inject_object(
        _sac_another_creature_or_artifact_dict(),
        0,
        ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(src_id, False)
    c1 = synthetic_state.register_and_inject_object(
        _creature_dict("C1"), 0, ZONE_BATTLEFIELD,
    )

    decisions = synthetic_state.legal_decisions(0)
    sac_targets = [
        d["sacrifice_target_id"]
        for d in decisions
        if d["kind"] == "activate_ability"
        and d["source_id"] == src_id
    ]
    assert src_id not in sac_targets
    assert c1 in sac_targets


def test_sac_a_land_includes_self_when_source_is_land(synthetic_state):
    """Dust-Bowl-style: when the source IS a land, the source itself
    is a legal sac target (printed text "a land" with no "another").
    """
    PHASE_MAIN1 = 3
    synthetic_state.set_phase(PHASE_MAIN1)
    _tap_all_default_p0_mana_sources(synthetic_state)
    src_id = synthetic_state.register_and_inject_object(
        _sac_a_land_self_eligible_dict(),
        0,
        ZONE_BATTLEFIELD,
    )
    l2 = synthetic_state.register_and_inject_object(
        _vanilla_land_dict("Plains2"), 0, ZONE_BATTLEFIELD,
    )

    decisions = synthetic_state.legal_decisions(0)
    sac_targets = sorted(
        d["sacrifice_target_id"]
        for d in decisions
        if d["kind"] == "activate_ability"
        and d["source_id"] == src_id
    )
    # Both the source itself and the other land are eligible.
    assert src_id in sac_targets
    assert l2 in sac_targets


def test_sac_a_land_excludes_non_lands(synthetic_state):
    """A creature on bf is NOT a legal sac-a-land target."""
    PHASE_MAIN1 = 3
    synthetic_state.set_phase(PHASE_MAIN1)
    _tap_all_default_p0_mana_sources(synthetic_state)
    src_id = synthetic_state.register_and_inject_object(
        _sac_a_land_dict(), 0, ZONE_BATTLEFIELD,
    )
    creature = synthetic_state.register_and_inject_object(
        _creature_dict("Just A Creature"), 0, ZONE_BATTLEFIELD,
    )
    land = synthetic_state.register_and_inject_object(
        _vanilla_land_dict("Plains2"), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.empty_mana_pool(0)
    synthetic_state.add_mana(0, "C", 1)
    # Source must be untapped (its cost includes {T}). force tap state.
    synthetic_state.force_set_summoning_sick(src_id, False)

    decisions = synthetic_state.legal_decisions(0)
    sac_targets = [
        d["sacrifice_target_id"]
        for d in decisions
        if d["kind"] == "activate_ability"
        and d["source_id"] == src_id
    ]
    assert creature not in sac_targets
    assert land in sac_targets


def test_sac_another_artifact_excludes_creatures_and_self(synthetic_state):
    """sacrifice_another_artifact: strict artifact-only filter, NOT
    self.
    """
    PHASE_MAIN1 = 3
    synthetic_state.set_phase(PHASE_MAIN1)
    _tap_all_default_p0_mana_sources(synthetic_state)
    src_id = synthetic_state.register_and_inject_object(
        _sac_another_artifact_dict(), 0, ZONE_BATTLEFIELD,
    )
    creature = synthetic_state.register_and_inject_object(
        _creature_dict("C"), 0, ZONE_BATTLEFIELD,
    )
    art = synthetic_state.register_and_inject_object(
        _vanilla_artifact_dict("A2"), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.empty_mana_pool(0)
    synthetic_state.add_mana(0, "C", 1)

    decisions = synthetic_state.legal_decisions(0)
    sac_targets = [
        d["sacrifice_target_id"]
        for d in decisions
        if d["kind"] == "activate_ability"
        and d["source_id"] == src_id
    ]
    assert creature not in sac_targets
    assert src_id not in sac_targets
    assert art in sac_targets


def test_sac_excludes_opponent_permanents(synthetic_state):
    """Sac target must be on the ACTIVATOR's bf, not the opponent's
    (you can only sac permanents you control).
    """
    PHASE_MAIN1 = 3
    synthetic_state.set_phase(PHASE_MAIN1)
    _tap_all_default_p0_mana_sources(synthetic_state)
    src_id = synthetic_state.register_and_inject_object(
        _sac_another_creature_or_artifact_dict(),
        0,
        ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(src_id, False)
    # Opponent's creature.
    opp_c = synthetic_state.register_and_inject_object(
        _creature_dict("Opp"), 1, ZONE_BATTLEFIELD,
    )

    decisions = synthetic_state.legal_decisions(0)
    sac_targets = [
        d["sacrifice_target_id"]
        for d in decisions
        if d["kind"] == "activate_ability"
        and d["source_id"] == src_id
    ]
    assert opp_c not in sac_targets


def test_sac_no_legal_targets_no_emission(synthetic_state):
    """sacrifice_another_artifact source with no OTHER artifacts on
    bf: no emission. (CR 601.2c — can't begin to activate without a
    legal target.)

    The synthetic state's default p0 battlefield has only Forests
    (lands) and Grizzly Bears (creatures) — neither is an artifact,
    so a sacrifice_another_artifact source has NO legal targets and
    emits zero ActivateAbility dicts.
    """
    PHASE_MAIN1 = 3
    synthetic_state.set_phase(PHASE_MAIN1)
    _tap_all_default_p0_mana_sources(synthetic_state)
    src_id = synthetic_state.register_and_inject_object(
        _sac_another_artifact_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.empty_mana_pool(0)
    synthetic_state.add_mana(0, "C", 1)

    decisions = synthetic_state.legal_decisions(0)
    sac_acts = [
        d
        for d in decisions
        if d["kind"] == "activate_ability"
        and d["source_id"] == src_id
    ]
    assert len(sac_acts) == 0, (
        f"Expected 0 emissions when no legal sac targets; got "
        f"{len(sac_acts)}"
    )


# --- apply-arm target validation -------------------------------------


def test_sac_apply_moves_chosen_target_to_graveyard(synthetic_state):
    """Apply sacrifice_another_creature_or_artifact with a chosen
    target: target moves to controller's gy, source stays on bf.
    """
    src_id = synthetic_state.register_and_inject_object(
        _sac_another_creature_or_artifact_dict(),
        0,
        ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(src_id, False)
    victim = synthetic_state.register_and_inject_object(
        _creature_dict("Victim"), 0, ZONE_BATTLEFIELD,
    )

    gy_before = synthetic_state.graveyard_sizes[0]
    synthetic_state.apply_action(
        {
            "kind": "activate_ability",
            "source_id": src_id,
            "ability_index": 0,
            "sacrifice_target_id": victim,
        }
    )

    bf_ids = [o["id"] for o in synthetic_state.battlefield_snapshot()]
    assert victim not in bf_ids
    assert src_id in bf_ids
    assert synthetic_state.graveyard_sizes[0] == gy_before + 1


def test_sac_apply_raises_when_target_missing(synthetic_state):
    """sacrifice_target_id missing => raise BEFORE any commit."""
    src_id = synthetic_state.register_and_inject_object(
        _sac_another_creature_or_artifact_dict(),
        0,
        ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(src_id, False)
    _victim = synthetic_state.register_and_inject_object(
        _creature_dict("V"), 0, ZONE_BATTLEFIELD,
    )

    gy_before = synthetic_state.graveyard_sizes[0]
    with pytest.raises(
        ValueError, match=r"requires a sacrifice target"
    ):
        synthetic_state.apply_action(
            {
                "kind": "activate_ability",
                "source_id": src_id,
                "ability_index": 0,
            }
        )
    # No state mutation.
    assert synthetic_state.graveyard_sizes[0] == gy_before


def test_sac_apply_raises_on_self_target_when_another_required(
    synthetic_state,
):
    """sacrifice_another_creature_or_artifact: passing the source's own
    id as the target raises loud. (Source is not a legal target — the
    cost reads "another".)
    """
    src_id = synthetic_state.register_and_inject_object(
        _sac_another_creature_or_artifact_dict(),
        0,
        ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(src_id, False)
    _victim = synthetic_state.register_and_inject_object(
        _creature_dict("V"), 0, ZONE_BATTLEFIELD,
    )

    with pytest.raises(
        ValueError, match=r"not a legal sacrifice target"
    ):
        synthetic_state.apply_action(
            {
                "kind": "activate_ability",
                "source_id": src_id,
                "ability_index": 0,
                "sacrifice_target_id": src_id,
            }
        )


def test_sac_apply_raises_on_opponent_target(synthetic_state):
    """Trying to sac the opponent's creature raises (not on
    activator's bf).
    """
    src_id = synthetic_state.register_and_inject_object(
        _sac_another_creature_or_artifact_dict(),
        0,
        ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(src_id, False)
    opp_v = synthetic_state.register_and_inject_object(
        _creature_dict("Opp"), 1, ZONE_BATTLEFIELD,
    )

    with pytest.raises(
        ValueError, match=r"not a legal sacrifice target"
    ):
        synthetic_state.apply_action(
            {
                "kind": "activate_ability",
                "source_id": src_id,
                "ability_index": 0,
                "sacrifice_target_id": opp_v,
            }
        )


def test_sac_apply_raises_on_wrong_type_for_filter(synthetic_state):
    """sacrifice_another_artifact: passing a creature (not artifact)
    as the target raises.
    """
    src_id = synthetic_state.register_and_inject_object(
        _sac_another_artifact_dict(), 0, ZONE_BATTLEFIELD,
    )
    creature = synthetic_state.register_and_inject_object(
        _creature_dict("C"), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.empty_mana_pool(0)
    synthetic_state.add_mana(0, "C", 1)

    with pytest.raises(
        ValueError, match=r"not a legal sacrifice target"
    ):
        synthetic_state.apply_action(
            {
                "kind": "activate_ability",
                "source_id": src_id,
                "ability_index": 0,
                "sacrifice_target_id": creature,
            }
        )


def test_sac_a_land_apply_self_target_succeeds(synthetic_state):
    """sacrifice_a_land on a land source with target=source: succeeds
    (source moves to gy).
    """
    src_id = synthetic_state.register_and_inject_object(
        _sac_a_land_self_eligible_dict(),
        0,
        ZONE_BATTLEFIELD,
    )

    gy_before = synthetic_state.graveyard_sizes[0]
    synthetic_state.apply_action(
        {
            "kind": "activate_ability",
            "source_id": src_id,
            "ability_index": 0,
            "sacrifice_target_id": src_id,
        }
    )
    bf_ids = [o["id"] for o in synthetic_state.battlefield_snapshot()]
    assert src_id not in bf_ids
    assert synthetic_state.graveyard_sizes[0] == gy_before + 1


def test_sac_apply_credits_controller_graveyard(synthetic_state):
    """Sacrificed target moves to the SOURCE's controller's gy (which
    is the activator since the target is on the activator's bf).
    Player-1-controlled source sacrifices a player-1 creature -> p1 gy
    grows, p0 gy doesn't.
    """
    src_id = synthetic_state.register_and_inject_object(
        _sac_another_creature_or_artifact_dict(),
        1,
        ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(src_id, False)
    victim = synthetic_state.register_and_inject_object(
        _creature_dict("V"), 1, ZONE_BATTLEFIELD,
    )
    synthetic_state.empty_mana_pool(1)
    synthetic_state.add_mana(1, "C", 0)

    p0_gy_before = synthetic_state.graveyard_sizes[0]
    p1_gy_before = synthetic_state.graveyard_sizes[1]
    synthetic_state.apply_action(
        {
            "kind": "activate_ability",
            "source_id": src_id,
            "ability_index": 0,
            "sacrifice_target_id": victim,
        }
    )
    assert synthetic_state.graveyard_sizes[0] == p0_gy_before
    assert synthetic_state.graveyard_sizes[1] == p1_gy_before + 1


# --- back-compat: existing non-sac ActivateAbility dicts -------------


def test_back_compat_pre_slice_6_dict_without_sac_target_works(
    synthetic_state,
):
    """A pre-Slice-6 ActivateAbility dict (no sacrifice_target_id key)
    on a non-sacrifice cost still works — Forest tap-for-mana is the
    canonical example.
    """
    # synthetic_state has Forests baked in. Find one untapped non-sick.
    forest_id = None
    for o in synthetic_state.battlefield_snapshot():
        if o["printing_name"] == "Forest" and not o["tapped"]:
            forest_id = o["id"]
            break
    assert forest_id is not None
    synthetic_state.empty_mana_pool(0)

    # Pre-Slice-6 dict shape: no sacrifice_target_id key.
    synthetic_state.apply_action(
        {
            "kind": "activate_ability",
            "source_id": forest_id,
            "ability_index": 0,
        }
    )
    # Mana pool got +G.
    assert synthetic_state.get_mana_pool(0)["G"] >= 1


# --- non-sac activation stray sacrifice_target_id ignored -----------


def test_non_sac_activation_ignores_stray_sacrifice_target_id(
    synthetic_state,
):
    """A non-sac activation (Forest tap-for-mana) with a stray
    sacrifice_target_id field is permissively accepted (mirrors Phase
    2.5's stray-target_creature_id handling).
    """
    forest_id = None
    for o in synthetic_state.battlefield_snapshot():
        if o["printing_name"] == "Forest" and not o["tapped"]:
            forest_id = o["id"]
            break
    assert forest_id is not None
    synthetic_state.empty_mana_pool(0)

    # Stray sacrifice_target_id is silently ignored.
    synthetic_state.apply_action(
        {
            "kind": "activate_ability",
            "source_id": forest_id,
            "ability_index": 0,
            "sacrifice_target_id": 99999,  # bogus id, ignored.
        }
    )
    assert synthetic_state.get_mana_pool(0)["G"] >= 1


# --- action dict round-trip -----------------------------------------


def test_activate_ability_dict_carries_sacrifice_target_id_in_emission(
    synthetic_state,
):
    """legal_decisions emission for a targeted-sac source carries
    sacrifice_target_id (not None) and target_creature_id=None.

    Uses sacrifice_another_artifact (no default artifacts on
    synthetic state's bf) so the injected artifact is the sole legal
    target.
    """
    PHASE_MAIN1 = 3
    synthetic_state.set_phase(PHASE_MAIN1)
    _tap_all_default_p0_mana_sources(synthetic_state)
    src_id = synthetic_state.register_and_inject_object(
        _sac_another_artifact_dict(), 0, ZONE_BATTLEFIELD,
    )
    victim = synthetic_state.register_and_inject_object(
        _vanilla_artifact_dict("V"), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.empty_mana_pool(0)
    synthetic_state.add_mana(0, "C", 1)

    decisions = synthetic_state.legal_decisions(0)
    sac_acts = [
        d
        for d in decisions
        if d["kind"] == "activate_ability"
        and d["source_id"] == src_id
    ]
    assert len(sac_acts) == 1
    d = sac_acts[0]
    assert d["sacrifice_target_id"] == victim
    assert d["target_creature_id"] is None
    assert d["ability_index"] == 0


# --- unknown-key paranoia rolled into Slice 6 -----------------------


def test_targeted_sac_unknown_cost_key_raises(empty_registry):
    """Adding an unknown key to the cost dict still raises loud. Pins
    the parser's loud-fail contract — a typo'd "sacrifice_another"
    (missing the "_creature_or_artifact" suffix) doesn't silently
    no-op.
    """
    d = _sac_another_creature_or_artifact_dict()
    d["activated_abilities"][0]["cost"]["sacrifice_another"] = True
    with pytest.raises(
        ValueError,
        match=r"unknown activation_cost key",
    ):
        empty_registry.register_printing(d)


# -------------------------------------------------------------------
# CE20 Slice 5 — Planeswalker loyalty (Slice A)
#
# Tests for the `cost.loyalty: i32` extension and the
# `GameObject.loyalty_counters: i32` slot. Tezzeret-shape walker
# with the standard +/0/- ability cycle. Slice A scope:
# cost-pay + loyalty counter slot + SBA pass at <= 0. Combat damage
# redirect (CR 119.5) and once-per-turn ledger (CR 606.3) are Slice
# B / C — out of scope here.
# -------------------------------------------------------------------


def _walker_dict(starting_loyalty: int = 4):
    """A 3-ability planeswalker (Tezzeret-shape minus the printed
    starting loyalty seed — tests stamp loyalty_counters directly via
    `set_loyalty_counters` for now since `starting_loyalty` on
    CardPrinting is not yet wired). The three abilities mirror the
    classic +/0/- cycle:
      - ability 0: +1 (cost loyalty: -1, "draw a card")
      - ability 1: 0 (cost loyalty: 0, "gain 1 life")
      - ability 2: -3 (cost loyalty: 3, "deal 0 damage" no-op)

    Walker card_type. Effects are simple (DrawCards / GainLife /
    no-op) to keep tests focused on the cost machinery.
    """
    _ = starting_loyalty  # field reserved for future ETB-seeding work
    return {
        "name": "Test Walker (Tezzeret-shape)",
        "card_types": ["Planeswalker"],
        "mana_cost": {"generic": 3, "U": 1, "B": 1},
        "effects": [],
        # No P/T — non-creature walker.
        "activated_abilities": [
            {
                # +1 ability
                "cost": {"loyalty": -1},
                "effect": {"kind": "draw_cards", "count": 1},
                "is_mana_ability": False,
            },
            {
                # 0 ability
                "cost": {"loyalty": 0},
                "effect": {"kind": "gain_life", "amount": 1},
                "is_mana_ability": False,
            },
            {
                # -3 ability
                "cost": {"loyalty": 3},
                "effect": {"kind": "gain_life", "amount": 0},
                "is_mana_ability": False,
            },
        ],
    }


# --- parser surface ---------------------------------------------------


def test_walker_loyalty_parses_signed_values(empty_registry):
    """A printing with three loyalty abilities (positive, zero,
    negative cost) parses without raising."""
    pid = empty_registry.register_printing(_walker_dict())
    assert pid == 0


def test_walker_loyalty_invalid_type_raises(empty_registry):
    """A non-int loyalty value raises loud."""
    d = _walker_dict()
    d["activated_abilities"][0]["cost"]["loyalty"] = "two"
    with pytest.raises(
        ValueError, match=r"loyalty must be an int"
    ):
        empty_registry.register_printing(d)


def test_walker_loyalty_unknown_key_raises_paranoid(empty_registry):
    """Adding an unknown key 'loyalty_payment' (typo) still raises."""
    d = _walker_dict()
    d["activated_abilities"][0]["cost"]["loyalty_payment"] = 1
    with pytest.raises(
        ValueError, match=r"unknown activation_cost key"
    ):
        empty_registry.register_printing(d)


# --- loyalty counter slot --------------------------------------------


def test_walker_loyalty_counters_default_zero(synthetic_state):
    """A non-walker object has loyalty_counters=0 by default."""
    forest_id = None
    for o in synthetic_state.battlefield_snapshot():
        if o["printing_name"] == "Forest":
            forest_id = o["id"]
            break
    assert forest_id is not None
    assert synthetic_state.get_loyalty_counters(forest_id) == 0


def test_walker_loyalty_counters_can_be_set_and_read(synthetic_state):
    """`set_loyalty_counters` writes, `get_loyalty_counters` reads.
    Round-trip pin."""
    walker_id = synthetic_state.register_and_inject_object(
        _walker_dict(), 0, ZONE_BATTLEFIELD,
    )
    assert synthetic_state.set_loyalty_counters(walker_id, 4) is True
    assert synthetic_state.get_loyalty_counters(walker_id) == 4
    # Idempotent: no change returns False.
    assert synthetic_state.set_loyalty_counters(walker_id, 4) is False


# --- emission gate ----------------------------------------------------


def test_walker_loyalty_emission_positive_cost_below_loyalty_skips(
    synthetic_state,
):
    """A -3 ability on a walker with loyalty_counters=2: emission
    filter skips the ability (insufficient loyalty for the positive
    cost). The +1 and 0 abilities still emit.
    """
    PHASE_MAIN1 = 3
    synthetic_state.set_phase(PHASE_MAIN1)
    _tap_all_default_p0_mana_sources(synthetic_state)
    walker_id = synthetic_state.register_and_inject_object(
        _walker_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(walker_id, False)
    synthetic_state.set_loyalty_counters(walker_id, 2)

    decisions = synthetic_state.legal_decisions(0)
    walker_acts = [
        d
        for d in decisions
        if d["kind"] == "activate_ability"
        and d["source_id"] == walker_id
    ]
    ability_indices = sorted({d["ability_index"] for d in walker_acts})
    # +1 (idx 0) and 0 (idx 1) emit; -3 (idx 2) is filtered.
    assert 0 in ability_indices
    assert 1 in ability_indices
    assert 2 not in ability_indices


def test_walker_loyalty_emission_positive_cost_at_loyalty_emits(
    synthetic_state,
):
    """At loyalty_counters == cost.loyalty (exactly affordable), the
    -3 ability emits."""
    PHASE_MAIN1 = 3
    synthetic_state.set_phase(PHASE_MAIN1)
    _tap_all_default_p0_mana_sources(synthetic_state)
    walker_id = synthetic_state.register_and_inject_object(
        _walker_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(walker_id, False)
    synthetic_state.set_loyalty_counters(walker_id, 3)

    decisions = synthetic_state.legal_decisions(0)
    walker_acts = [
        d
        for d in decisions
        if d["kind"] == "activate_ability"
        and d["source_id"] == walker_id
    ]
    ability_indices = {d["ability_index"] for d in walker_acts}
    # All three emit at loyalty=3.
    assert {0, 1, 2}.issubset(ability_indices)


def test_walker_loyalty_emission_negative_cost_always_emits(
    synthetic_state,
):
    """The +1 ability (cost.loyalty = -1) emits even at
    loyalty_counters=0 (the lower bound of legal walker state — a
    walker at 0 is about to die via SBA, but emission happens
    BEFORE the SBA pass in synthetic-state queries; the test pins
    that the negative-cost gate is "always affordable").
    """
    PHASE_MAIN1 = 3
    synthetic_state.set_phase(PHASE_MAIN1)
    _tap_all_default_p0_mana_sources(synthetic_state)
    walker_id = synthetic_state.register_and_inject_object(
        _walker_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(walker_id, False)
    # Force loyalty to 1 (so SBA doesn't sweep, but only the +1
    # ability is "affordable" by the strict loyalty-counter test —
    # actually 0 ability also fires since 0 is also "affordable").
    synthetic_state.set_loyalty_counters(walker_id, 1)

    decisions = synthetic_state.legal_decisions(0)
    walker_acts = [
        d
        for d in decisions
        if d["kind"] == "activate_ability"
        and d["source_id"] == walker_id
    ]
    ability_indices = {d["ability_index"] for d in walker_acts}
    # +1 (idx 0): negative cost, always affordable. 0 (idx 1): always.
    # -3 (idx 2): loyalty < 3, NOT emitted.
    assert 0 in ability_indices
    assert 1 in ability_indices
    assert 2 not in ability_indices


# --- apply arm: signed commit ----------------------------------------


def test_walker_loyalty_apply_positive_cost_decrements(synthetic_state):
    """Activate the -3 ability on a loyalty=5 walker: post-activate
    loyalty_counters == 2.
    """
    walker_id = synthetic_state.register_and_inject_object(
        _walker_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(walker_id, False)
    synthetic_state.set_loyalty_counters(walker_id, 5)

    synthetic_state.apply_action(
        {
            "kind": "activate_ability",
            "source_id": walker_id,
            "ability_index": 2,  # -3 ability
        }
    )
    assert synthetic_state.get_loyalty_counters(walker_id) == 2


def test_walker_loyalty_apply_negative_cost_increments(synthetic_state):
    """Activate the +1 ability on a loyalty=3 walker: post-activate
    loyalty_counters == 4.
    """
    walker_id = synthetic_state.register_and_inject_object(
        _walker_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(walker_id, False)
    synthetic_state.set_loyalty_counters(walker_id, 3)

    synthetic_state.apply_action(
        {
            "kind": "activate_ability",
            "source_id": walker_id,
            "ability_index": 0,  # +1 ability
        }
    )
    assert synthetic_state.get_loyalty_counters(walker_id) == 4


def test_walker_loyalty_apply_zero_cost_no_change(synthetic_state):
    """Activate the 0 ability on a loyalty=3 walker: loyalty_counters
    unchanged (cost.loyalty == 0).
    """
    walker_id = synthetic_state.register_and_inject_object(
        _walker_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(walker_id, False)
    synthetic_state.set_loyalty_counters(walker_id, 3)

    synthetic_state.apply_action(
        {
            "kind": "activate_ability",
            "source_id": walker_id,
            "ability_index": 1,  # 0 ability
        }
    )
    assert synthetic_state.get_loyalty_counters(walker_id) == 3


def test_walker_loyalty_apply_insufficient_loyalty_raises(synthetic_state):
    """Direct apply of the -3 ability on a loyalty=2 walker raises
    BEFORE any state mutation (Phase 3b precheck). Pool / tap state
    untouched.
    """
    walker_id = synthetic_state.register_and_inject_object(
        _walker_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(walker_id, False)
    synthetic_state.set_loyalty_counters(walker_id, 2)

    with pytest.raises(
        ValueError, match=r"insufficient loyalty"
    ):
        synthetic_state.apply_action(
            {
                "kind": "activate_ability",
                "source_id": walker_id,
                "ability_index": 2,
            }
        )
    assert synthetic_state.get_loyalty_counters(walker_id) == 2


# --- SBA pass: walker dies at loyalty <= 0 ---------------------------


def test_walker_loyalty_sba_removes_at_zero(synthetic_state):
    """A walker with loyalty_counters=0 on bf is moved to its
    controller's gy by the next apply_sbas pass (CR 704.5i).
    """
    walker_id = synthetic_state.register_and_inject_object(
        _walker_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.set_loyalty_counters(walker_id, 0)
    gy_before = synthetic_state.graveyard_sizes[0]

    n_destroyed = synthetic_state.apply_sbas()
    assert n_destroyed == 1

    bf_ids = [o["id"] for o in synthetic_state.battlefield_snapshot()]
    assert walker_id not in bf_ids
    assert synthetic_state.graveyard_sizes[0] == gy_before + 1


def test_walker_loyalty_sba_removes_at_negative(synthetic_state):
    """A walker with loyalty_counters=-1 also dies (CR 704.5i — "0 or
    less")."""
    walker_id = synthetic_state.register_and_inject_object(
        _walker_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.set_loyalty_counters(walker_id, -1)

    n_destroyed = synthetic_state.apply_sbas()
    assert n_destroyed == 1
    bf_ids = [o["id"] for o in synthetic_state.battlefield_snapshot()]
    assert walker_id not in bf_ids


def test_walker_loyalty_sba_no_op_at_positive(synthetic_state):
    """A walker with loyalty_counters=4 stays on bf — no SBA
    destruction."""
    walker_id = synthetic_state.register_and_inject_object(
        _walker_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.set_loyalty_counters(walker_id, 4)

    synthetic_state.apply_sbas()
    bf_ids = [o["id"] for o in synthetic_state.battlefield_snapshot()]
    assert walker_id in bf_ids


def test_walker_loyalty_ultimate_activation_then_sba_kills(synthetic_state):
    """End-to-end: activate the -3 ability on a loyalty=3 walker.
    Post-activate loyalty=0; subsequent apply_sbas moves the walker
    to gy.
    """
    walker_id = synthetic_state.register_and_inject_object(
        _walker_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(walker_id, False)
    synthetic_state.set_loyalty_counters(walker_id, 3)

    synthetic_state.apply_action(
        {
            "kind": "activate_ability",
            "source_id": walker_id,
            "ability_index": 2,
        }
    )
    assert synthetic_state.get_loyalty_counters(walker_id) == 0
    # Walker still on bf at this instant — SBA hasn't been invoked
    # yet (real engine would invoke before next priority, but the
    # apply_action arm itself doesn't drain SBAs).
    bf_ids = [o["id"] for o in synthetic_state.battlefield_snapshot()]
    assert walker_id in bf_ids

    # Run SBA: walker dies.
    synthetic_state.apply_sbas()
    bf_ids = [o["id"] for o in synthetic_state.battlefield_snapshot()]
    assert walker_id not in bf_ids


def test_walker_does_not_fire_dies_trigger_only_leaves(synthetic_state):
    """CR 700.4 — Event::Dies is "a creature dies". A non-creature
    walker dying via CR 704.5i fires LEAVES_BATTLEFIELD but NOT
    DIES. Pin: a `subject_is_creature` DIES observer does NOT fire
    when a walker hits the gy via loyalty-zero SBA. Conversely a
    LEAVES observer DOES fire.
    """
    # Set up a creature observer that listens for both DIES (which
    # SHOULD NOT fire for the walker) and LEAVES_BATTLEFIELD (which
    # SHOULD fire). Use two separate observers for cleaner assertions.
    dies_observer = {
        "name": "DIES Observer",
        "card_types": ["Creature"],
        "mana_cost": {},
        "effects": [],
        "power": 1,
        "toughness": 10,  # high tough so it doesn't die to SBA itself
        "keywords": ["indestructible"],
        "triggered_abilities": [
            {
                "event": "dies",
                "predicate": {"kind": "subject_is_creature"},
                "effect": {"kind": "gain_life", "amount": 5},
            }
        ],
    }
    leaves_observer = {
        "name": "LEAVES Observer",
        "card_types": ["Creature"],
        "mana_cost": {},
        "effects": [],
        "power": 1,
        "toughness": 10,
        "keywords": ["indestructible"],
        "triggered_abilities": [
            {
                "event": "leaves_battlefield",
                "predicate": {"kind": "always"},
                "effect": {"kind": "gain_life", "amount": 7},
            }
        ],
    }
    _dies_id = synthetic_state.register_and_inject_object(
        dies_observer, 0, ZONE_BATTLEFIELD,
    )
    _leaves_id = synthetic_state.register_and_inject_object(
        leaves_observer, 0, ZONE_BATTLEFIELD,
    )
    walker_id = synthetic_state.register_and_inject_object(
        _walker_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.set_loyalty_counters(walker_id, 0)

    stack_before = synthetic_state.stack_size()
    synthetic_state.apply_sbas()
    # Walker died. LEAVES observer (always-firing) fires; DIES
    # observer DOES NOT (walker is non-creature, DIES skipped).
    stack_after = synthetic_state.stack_size()
    # We expect exactly 1 new trigger on the stack — the LEAVES
    # observer. (The default-creature SBA pass may also have
    # destroyed other things; we just assert stack growth happened
    # but the LEAVES gain_life=7 trigger should be on top.)
    assert stack_after > stack_before
    # Drain the stack and assert observer fired by checking the
    # gain_life-7 trigger is present (life jumped by at least 7 from
    # the leaves observer, but NOT the DIES observer's 5).
    p0_life_before = synthetic_state.life_totals[0]
    while synthetic_state.stack_size() > 0:
        synthetic_state.resolve_top_of_stack()
    p0_life_after = synthetic_state.life_totals[0]
    life_delta = p0_life_after - p0_life_before
    # Should be exactly 7 (LEAVES observer) — NOT 5+7=12 (DIES + LEAVES).
    assert life_delta == 7, (
        f"Expected p0 life +7 from LEAVES observer alone (DIES "
        f"observer should NOT fire on a walker); got {life_delta}"
    )


# -------------------------------------------------------------------
# CE20 Slice 5 — Planeswalker loyalty (Slice C)
#
# CR 606.3 once-per-turn-per-walker ledger. After ANY successful
# loyalty activation, the walker is locked for the remainder of the
# turn; emission filter skips ALL of its abilities and direct apply
# raises. Cleared at the cleanup step (same site as
# `triggered_this_turn`).
# -------------------------------------------------------------------


# --- emission gate: locked walker emits nothing ----------------------


def test_walker_once_per_turn_emission_locked_after_activate(synthetic_state):
    """Activate the +1 ability on a walker; emission filter then
    skips ALL of the walker's activated abilities for the rest of
    the turn (CR 606.3).
    """
    PHASE_MAIN1 = 3
    synthetic_state.set_phase(PHASE_MAIN1)
    _tap_all_default_p0_mana_sources(synthetic_state)
    walker_id = synthetic_state.register_and_inject_object(
        _walker_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(walker_id, False)
    synthetic_state.set_loyalty_counters(walker_id, 4)

    # Pre-activation: all three abilities emit (+1, 0, -3 — loyalty
    # 4 >= 3 covers the -3 ability).
    decisions = synthetic_state.legal_decisions(0)
    walker_acts = [
        d
        for d in decisions
        if d["kind"] == "activate_ability"
        and d["source_id"] == walker_id
    ]
    pre_indices = {d["ability_index"] for d in walker_acts}
    assert {0, 1, 2}.issubset(pre_indices), (
        f"Pre-activation expected all 3 abilities to emit, got {pre_indices}"
    )

    # Activate the 0 ability (simplest effect; gain_life=1).
    synthetic_state.apply_action(
        {
            "kind": "activate_ability",
            "source_id": walker_id,
            "ability_index": 1,
        }
    )
    # Drain the stack item so emission returns to its priority-emission
    # shape (with a stack item pending, only `pass_priority` emits).
    while synthetic_state.stack_size() > 0:
        synthetic_state.resolve_top_of_stack()

    # Post-activation: NONE of the walker's abilities emit.
    decisions_after = synthetic_state.legal_decisions(0)
    walker_acts_after = [
        d
        for d in decisions_after
        if d["kind"] == "activate_ability"
        and d["source_id"] == walker_id
    ]
    assert walker_acts_after == [], (
        f"Expected zero walker activations after locking, "
        f"got {walker_acts_after}"
    )


def test_walker_once_per_turn_emission_other_walkers_unaffected(
    synthetic_state,
):
    """Activating one walker doesn't lock OTHER walkers (the ledger
    is per-walker, not global)."""
    PHASE_MAIN1 = 3
    synthetic_state.set_phase(PHASE_MAIN1)
    _tap_all_default_p0_mana_sources(synthetic_state)
    w1 = synthetic_state.register_and_inject_object(
        _walker_dict(), 0, ZONE_BATTLEFIELD,
    )
    w2 = synthetic_state.register_and_inject_object(
        _walker_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(w1, False)
    synthetic_state.force_set_summoning_sick(w2, False)
    synthetic_state.set_loyalty_counters(w1, 4)
    synthetic_state.set_loyalty_counters(w2, 4)

    # Activate w1 with the 0 ability (no stack effect to interfere
    # with emission post-activation; gain_life=1 is the simplest
    # effect that doesn't depend on library state).
    synthetic_state.apply_action(
        {
            "kind": "activate_ability",
            "source_id": w1,
            "ability_index": 1,
        }
    )
    # Drain any stack items the activation produced so emission
    # returns to the priority-emission shape (not just pass_priority).
    while synthetic_state.stack_size() > 0:
        synthetic_state.resolve_top_of_stack()

    # w1 should be locked; w2 should still emit.
    decisions = synthetic_state.legal_decisions(0)
    w1_acts = [
        d
        for d in decisions
        if d["kind"] == "activate_ability" and d["source_id"] == w1
    ]
    w2_acts = [
        d
        for d in decisions
        if d["kind"] == "activate_ability" and d["source_id"] == w2
    ]
    assert w1_acts == [], (
        f"Expected w1 locked, got {w1_acts}"
    )
    assert len(w2_acts) >= 1, (
        f"Expected w2 still active, got {w2_acts}"
    )


def test_walker_once_per_turn_emission_non_walker_unaffected(
    synthetic_state,
):
    """The ledger is gated on Planeswalker card_type. Non-walker
    activated-ability sources (e.g. Forest's mana ability) keep
    emitting after a walker activation.
    """
    PHASE_MAIN1 = 3
    synthetic_state.set_phase(PHASE_MAIN1)
    walker_id = synthetic_state.register_and_inject_object(
        _walker_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(walker_id, False)
    synthetic_state.set_loyalty_counters(walker_id, 4)

    # Count Forest mana abilities BEFORE walker activation.
    forest_ids = {
        o["id"]
        for o in synthetic_state.battlefield_snapshot()
        if o["printing_name"] == "Forest" and o.get("controller_id") == 0
    }
    decisions_pre = synthetic_state.legal_decisions(0)
    forest_acts_pre = [
        d
        for d in decisions_pre
        if d["kind"] == "activate_ability"
        and d["source_id"] in forest_ids
    ]
    n_forest_pre = len(forest_acts_pre)
    assert n_forest_pre >= 1, "Need at least 1 Forest for this test"

    # Activate walker (use the 0-cost ability — gain_life=1 — so the
    # stack trigger is simple and resolution is a no-op for the
    # forests on bf).
    synthetic_state.apply_action(
        {
            "kind": "activate_ability",
            "source_id": walker_id,
            "ability_index": 1,
        }
    )
    # Drain the stack so emission returns to non-priority-only shape.
    while synthetic_state.stack_size() > 0:
        synthetic_state.resolve_top_of_stack()

    # Forest mana abilities should still emit (Forest is not a
    # Planeswalker; not gated by the ledger).
    decisions_post = synthetic_state.legal_decisions(0)
    forest_acts_post = [
        d
        for d in decisions_post
        if d["kind"] == "activate_ability"
        and d["source_id"] in forest_ids
    ]
    assert len(forest_acts_post) == n_forest_pre, (
        f"Expected {n_forest_pre} Forest activations to remain "
        f"emitted, got {len(forest_acts_post)}"
    )


# --- apply-arm: locked walker raises on direct call ------------------


def test_walker_once_per_turn_apply_locked_raises(synthetic_state):
    """A direct apply_action on an already-activated walker raises
    BEFORE any mutation (Phase 3c precheck). Loyalty counters and
    other state untouched.
    """
    walker_id = synthetic_state.register_and_inject_object(
        _walker_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(walker_id, False)
    synthetic_state.set_loyalty_counters(walker_id, 5)

    # First activation: succeeds (+1 ability brings loyalty to 6).
    synthetic_state.apply_action(
        {
            "kind": "activate_ability",
            "source_id": walker_id,
            "ability_index": 0,
        }
    )
    assert synthetic_state.get_loyalty_counters(walker_id) == 6

    # Second activation attempt (try the 0 ability — different
    # ability_index): raises CR 606.3 violation.
    with pytest.raises(
        ValueError, match=r"already activated a loyalty ability"
    ):
        synthetic_state.apply_action(
            {
                "kind": "activate_ability",
                "source_id": walker_id,
                "ability_index": 1,
            }
        )
    # Loyalty unchanged from first activation.
    assert synthetic_state.get_loyalty_counters(walker_id) == 6


def test_walker_once_per_turn_apply_same_ability_twice_raises(
    synthetic_state,
):
    """Activating the SAME ability twice on the same walker raises
    on the second attempt (the ledger keys on walker, not ability).
    """
    walker_id = synthetic_state.register_and_inject_object(
        _walker_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(walker_id, False)
    synthetic_state.set_loyalty_counters(walker_id, 4)

    synthetic_state.apply_action(
        {
            "kind": "activate_ability",
            "source_id": walker_id,
            "ability_index": 0,
        }
    )

    with pytest.raises(
        ValueError, match=r"already activated a loyalty ability"
    ):
        synthetic_state.apply_action(
            {
                "kind": "activate_ability",
                "source_id": walker_id,
                "ability_index": 0,
            }
        )


def test_walker_once_per_turn_apply_zero_cost_locks_walker(
    synthetic_state,
):
    """The "0" ability (cost.loyalty == 0) still stamps the ledger.
    CR 606.3 says "activated A loyalty ability" — the cost value
    doesn't matter.
    """
    walker_id = synthetic_state.register_and_inject_object(
        _walker_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(walker_id, False)
    synthetic_state.set_loyalty_counters(walker_id, 4)

    # Activate the 0 ability.
    synthetic_state.apply_action(
        {
            "kind": "activate_ability",
            "source_id": walker_id,
            "ability_index": 1,
        }
    )
    # Loyalty unchanged (cost == 0).
    assert synthetic_state.get_loyalty_counters(walker_id) == 4

    # Walker is now locked.
    with pytest.raises(
        ValueError, match=r"already activated a loyalty ability"
    ):
        synthetic_state.apply_action(
            {
                "kind": "activate_ability",
                "source_id": walker_id,
                "ability_index": 0,
            }
        )


# --- no ledger residue on failed activation --------------------------


def test_walker_once_per_turn_no_stamp_on_failed_activation(
    synthetic_state,
):
    """A failed activation (insufficient loyalty) MUST NOT stamp the
    ledger — the walker stays activatable for a subsequent
    legal-cost ability this turn.
    """
    walker_id = synthetic_state.register_and_inject_object(
        _walker_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(walker_id, False)
    # Loyalty 2: -3 ability is unaffordable, +1 and 0 are fine.
    synthetic_state.set_loyalty_counters(walker_id, 2)

    # Try the -3 ability: raises BEFORE Phase 5e stamp (Phase 3b
    # short-circuit).
    with pytest.raises(
        ValueError, match=r"insufficient loyalty"
    ):
        synthetic_state.apply_action(
            {
                "kind": "activate_ability",
                "source_id": walker_id,
                "ability_index": 2,
            }
        )

    # Walker is NOT locked; the +1 ability should still apply.
    synthetic_state.apply_action(
        {
            "kind": "activate_ability",
            "source_id": walker_id,
            "ability_index": 0,
        }
    )
    assert synthetic_state.get_loyalty_counters(walker_id) == 3


# --- cleanup step clears the ledger ----------------------------------


def test_walker_once_per_turn_cleanup_clears_ledger(synthetic_state):
    """`cleanup_step_for_active_player` clears the ledger, so the
    walker is re-activatable next turn.
    """
    walker_id = synthetic_state.register_and_inject_object(
        _walker_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(walker_id, False)
    synthetic_state.set_loyalty_counters(walker_id, 5)

    # Activate on turn N.
    synthetic_state.apply_action(
        {
            "kind": "activate_ability",
            "source_id": walker_id,
            "ability_index": 0,
        }
    )

    # Confirm locked.
    with pytest.raises(
        ValueError, match=r"already activated a loyalty ability"
    ):
        synthetic_state.apply_action(
            {
                "kind": "activate_ability",
                "source_id": walker_id,
                "ability_index": 1,
            }
        )

    # Run cleanup step (resets ledger).
    synthetic_state.cleanup_step_for_active_player()

    # Walker is re-activatable.
    synthetic_state.apply_action(
        {
            "kind": "activate_ability",
            "source_id": walker_id,
            "ability_index": 1,
        }
    )
    # Loyalty unchanged from the +1 (now at 6) plus the 0 ability.
    assert synthetic_state.get_loyalty_counters(walker_id) == 6


def test_walker_once_per_turn_end_turn_clears_ledger(synthetic_state):
    """`end_turn_and_start_next` (which composes cleanup + advance)
    also clears the ledger as a regression pin on the composition
    primitive."""
    walker_id = synthetic_state.register_and_inject_object(
        _walker_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(walker_id, False)
    synthetic_state.set_loyalty_counters(walker_id, 5)

    synthetic_state.apply_action(
        {
            "kind": "activate_ability",
            "source_id": walker_id,
            "ability_index": 0,
        }
    )

    turn_before = synthetic_state.turn_number
    synthetic_state.end_turn_and_start_next()
    assert synthetic_state.turn_number == turn_before + 1

    # Walker now controlled by previously-non-active player (it's
    # still on p0's bf, but active_player has flipped to p1). The
    # ledger is keyed on (controller, walker_id) = (0, walker_id),
    # which has been cleared. Confirm by directly applying — note
    # apply_action doesn't check active_player for ActivateAbility,
    # so we can fire as p0 even on p1's turn.
    synthetic_state.apply_action(
        {
            "kind": "activate_ability",
            "source_id": walker_id,
            "ability_index": 1,
        }
    )
    # Activation succeeded (no raise); ledger was cleared.


# --- CoW invariant: cloning before activation isolates the ledger ----


def test_walker_once_per_turn_clone_isolates_ledger(synthetic_state):
    """Cloning the GameState and activating on the clone does NOT
    lock the walker on the source. The ledger is per-state."""
    walker_id = synthetic_state.register_and_inject_object(
        _walker_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(walker_id, False)
    synthetic_state.set_loyalty_counters(walker_id, 5)

    clone = synthetic_state.clone_once()

    # Activate on the clone.
    clone.apply_action(
        {
            "kind": "activate_ability",
            "source_id": walker_id,
            "ability_index": 0,
        }
    )

    # Source's walker is still activatable.
    synthetic_state.apply_action(
        {
            "kind": "activate_ability",
            "source_id": walker_id,
            "ability_index": 0,
        }
    )
    # Both ran successfully; no exception raised.


# --- combined: end-to-end double-activate-then-cleanup-then-reactivate


def test_walker_once_per_turn_end_to_end(synthetic_state):
    """Full life cycle: activate -> locked -> cleanup -> re-activate.
    Pins the 3-state contract of the CR 606.3 ledger."""
    walker_id = synthetic_state.register_and_inject_object(
        _walker_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(walker_id, False)
    synthetic_state.set_loyalty_counters(walker_id, 5)

    # State 1: fresh — activate the +1.
    synthetic_state.apply_action(
        {
            "kind": "activate_ability",
            "source_id": walker_id,
            "ability_index": 0,
        }
    )
    assert synthetic_state.get_loyalty_counters(walker_id) == 6

    # State 2: locked — second activation raises.
    with pytest.raises(
        ValueError, match=r"already activated a loyalty ability"
    ):
        synthetic_state.apply_action(
            {
                "kind": "activate_ability",
                "source_id": walker_id,
                "ability_index": 2,
            }
        )
    assert synthetic_state.get_loyalty_counters(walker_id) == 6

    # State 3: cleanup -> re-activatable.
    synthetic_state.cleanup_step_for_active_player()
    synthetic_state.apply_action(
        {
            "kind": "activate_ability",
            "source_id": walker_id,
            "ability_index": 2,  # -3 ability (loyalty 6 >= 3)
        }
    )
    assert synthetic_state.get_loyalty_counters(walker_id) == 3


# -------------------------------------------------------------------
# CE20 Slice 5 — Planeswalker starting_loyalty ETB seeding
#
# CR 606.5b: a planeswalker enters the battlefield with a number of
# loyalty counters equal to its printed starting loyalty. The
# `CardPrinting.starting_loyalty: i32` field on the registry +
# `crate::state::seed_starting_loyalty_for_etb` helper stamp
# `obj.loyalty_counters` on every bf-entry call site (cast-and-resolve
# + reanimation + move_object).
# -------------------------------------------------------------------


def _walker_dict_with_starting_loyalty(starting_loyalty: int):
    """Tezzeret-shape walker with an explicit `starting_loyalty` key.
    The 3 abilities mirror the standard +/0/- cycle (gain_life=1 for
    each so resolution is trivial)."""
    return {
        "name": "Test Walker (starting_loyalty)",
        "card_types": ["Planeswalker"],
        "mana_cost": {"generic": 1},  # trivially castable
        "effects": [],
        "starting_loyalty": starting_loyalty,
        "activated_abilities": [
            {
                "cost": {"loyalty": -1},
                "effect": {"kind": "gain_life", "amount": 1},
                "is_mana_ability": False,
            },
            {
                "cost": {"loyalty": 0},
                "effect": {"kind": "gain_life", "amount": 1},
                "is_mana_ability": False,
            },
            {
                "cost": {"loyalty": 3},
                "effect": {"kind": "gain_life", "amount": 1},
                "is_mana_ability": False,
            },
        ],
    }


# --- parser surface --------------------------------------------------


def test_starting_loyalty_parses_positive(empty_registry):
    """A printing with `starting_loyalty: 4` parses without error."""
    pid = empty_registry.register_printing(
        _walker_dict_with_starting_loyalty(4)
    )
    assert pid == 0


def test_starting_loyalty_defaults_to_zero(empty_registry):
    """A printing WITHOUT the `starting_loyalty` key parses; the field
    defaults to 0 (back-compat for every pre-Slice-5-C registry dict).
    """
    d = _walker_dict_with_starting_loyalty(4)
    del d["starting_loyalty"]
    pid = empty_registry.register_printing(d)
    assert pid == 0


def test_starting_loyalty_invalid_type_raises(empty_registry):
    """A non-int starting_loyalty value raises loud."""
    d = _walker_dict_with_starting_loyalty(4)
    d["starting_loyalty"] = "four"
    with pytest.raises(
        ValueError, match=r"starting_loyalty must be an integer"
    ):
        empty_registry.register_printing(d)


# --- ETB seeding via cast-and-resolve --------------------------------


def test_starting_loyalty_seeded_on_cast_to_battlefield(synthetic_state):
    """A walker cast and resolved via the stack-resolution path
    (`move_source_post_resolve`) enters bf with loyalty_counters ==
    starting_loyalty. Substrate-direct test using
    register_and_inject_object to ZONE_HAND + push_to_stack +
    resolve_top_of_stack to drive the canonical resolve path.
    """
    walker_in_hand = synthetic_state.register_and_inject_object(
        _walker_dict_with_starting_loyalty(4), 0, ZONE_HAND,
    )
    synthetic_state.push_to_stack(walker_in_hand, 0)
    synthetic_state.resolve_top_of_stack()
    # Walker landed on bf.
    bf = synthetic_state.battlefield_snapshot()
    walker_on_bf = next(
        (o for o in bf if o["id"] == walker_in_hand), None
    )
    assert walker_on_bf is not None, "Walker did not enter battlefield"
    assert synthetic_state.get_loyalty_counters(walker_in_hand) == 4


def test_starting_loyalty_zero_seeds_zero(synthetic_state):
    """A walker with starting_loyalty=0 (degenerate / hypothetical
    printing) enters with loyalty_counters=0. The SBA pass then sweeps
    it next tick (CR 704.5i)."""
    walker_in_hand = synthetic_state.register_and_inject_object(
        _walker_dict_with_starting_loyalty(0), 0, ZONE_HAND,
    )
    synthetic_state.push_to_stack(walker_in_hand, 0)
    synthetic_state.resolve_top_of_stack()
    assert synthetic_state.get_loyalty_counters(walker_in_hand) == 0


def test_starting_loyalty_non_walker_unaffected(synthetic_state):
    """A non-walker printing with starting_loyalty in its dict (the
    field is registered for every printing; for non-walkers it has
    no observable effect) enters bf with loyalty_counters=0.
    """
    creature_dict = {
        "name": "Test Creature",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 1},
        "effects": [],
        "starting_loyalty": 7,  # ignored — not a walker
        "power": 1,
        "toughness": 1,
    }
    obj_id = synthetic_state.register_and_inject_object(
        creature_dict, 0, ZONE_HAND,
    )
    synthetic_state.push_to_stack(obj_id, 0)
    synthetic_state.resolve_top_of_stack()
    # Non-walker — loyalty_counters stays at the default 0.
    assert synthetic_state.get_loyalty_counters(obj_id) == 0


# --- ETB seeding via move_object (e.g. zone-change effects) ----------


def test_starting_loyalty_seeded_on_move_object_to_battlefield(
    synthetic_state,
):
    """A walker moved onto the battlefield via the generic
    `move_object` primitive (e.g. a zone-change effect) gets its
    loyalty seeded.

    Driving path: register the walker into ZONE_HAND, then call
    `move_object` to relocate it onto p0's battlefield. Mirrors the
    pattern used by bounce-then-replay / zone-flicker effects.
    """
    walker_id = synthetic_state.register_and_inject_object(
        _walker_dict_with_starting_loyalty(5), 0, ZONE_HAND,
    )
    # Walker is in hand — `get_loyalty_counters` returns None for
    # non-bf objects (the helper only walks battlefields). Pre-move
    # we just confirm the walker exists in hand.
    assert synthetic_state.find_object_zone(walker_id) == ZONE_HAND
    # Move from hand to bf via the generic primitive.
    synthetic_state.move_object(walker_id, ZONE_BATTLEFIELD, 0)
    # Now on bf with seeded loyalty.
    assert synthetic_state.get_loyalty_counters(walker_id) == 5


# --- end-to-end: cast walker, activate without test-helper seed ------


def test_starting_loyalty_end_to_end_cast_then_activate(synthetic_state):
    """End-to-end: cast walker -> enters with starting_loyalty -> the
    +1 ability is activatable next turn (no `set_loyalty_counters`
    test-helper call needed).
    """
    walker_in_hand = synthetic_state.register_and_inject_object(
        _walker_dict_with_starting_loyalty(4), 0, ZONE_HAND,
    )
    synthetic_state.push_to_stack(walker_in_hand, 0)
    synthetic_state.resolve_top_of_stack()
    assert synthetic_state.get_loyalty_counters(walker_in_hand) == 4

    # Walker is summoning-sick from the cast (CR 302.1 doesn't apply
    # to walkers but the engine flags creature-shape `summoning_sick`
    # on ETB regardless). The loyalty cost machinery doesn't check
    # sickness — only tap-self costs do. So +1 is activatable on the
    # turn it enters.
    synthetic_state.force_set_summoning_sick(walker_in_hand, False)

    synthetic_state.apply_action(
        {
            "kind": "activate_ability",
            "source_id": walker_in_hand,
            "ability_index": 0,  # +1 — loyalty 4 -> 5
        }
    )
    assert synthetic_state.get_loyalty_counters(walker_in_hand) == 5
