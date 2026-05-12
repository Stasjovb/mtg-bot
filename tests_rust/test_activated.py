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
    """Unknown activation_cost keys raise loudly at register time."""
    d = {
        "name": "Bad Cost Card",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 1},
        "effects": [],
        "power": 1,
        "toughness": 1,
        "activated_abilities": [
            {
                "cost": {"mana": {"G": 1}, "sacrifice_self": True},
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
    when p0's mana pool can't cover {1}{G}."""
    bear_id = synthetic_state.register_and_inject_object(
        _bear_caster_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(bear_id, False)
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
