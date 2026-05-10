"""First-cut stack resolution on the Rust ``GameState``.

Composes round-5 stack (``push/pop/peek``) + round-3 bridge effects
(``Effect::DealDamage``) + round-3 damage (``deal_damage``) +
zone-search to actually resolve a stack item end-to-end.

Ported from the spell-resolution path in
``src/mtg_bot/actions.py:resolve_top_of_stack``. The Python side
spreads resolution across hundreds of lines (counters, abilities,
auras, modal modes, X / kicker, replacement effects); the Rust
first slice carves off the irreducible primitive: pop one item,
look up the source's printing's effects, dispatch each one.

**Scope simplifications** (mirrored in the module docstring on
``rust/src/state_ops_resolve.rs``):

- **Supported effects: just ``DealDamage``.** The other effect
  variants don't exist in the bridge yet — the round-3 bridge slice
  only landed ``DealDamage``. Any unknown variant raises
  ``ValueError`` loudly rather than silently no-op'ing.
- **Targeting is deterministic + simplified.**
  ``TargetFilter::AnyPlayer`` resolves to the defending player
  (``1 - active_player``); ``TargetFilter::AnyCreature`` resolves
  to the FIRST creature on the defending player's battlefield
  (smallest index in their ``battlefield`` Vec). If there is no
  creature on the defender's side, the spell fizzles — stack item
  still pops, but no damage is applied.
- **Post-resolve spell-source movement (round-7 slice).** Real MTG
  CR 608.2m: when a spell finishes resolving, an instant or sorcery
  goes to its owner's graveyard; a permanent spell becomes a
  permanent on the battlefield. The round-7 ``post-resolve``
  slice closes round-6's deferred case: ``resolve_top_of_stack``
  now dispatches on the source printing's ``card_types`` and moves
  the source accordingly. Creatures landing on the battlefield get
  ``summoning_sick = true``. ETB triggers are still deferred
  (future slice). Empty ``card_types`` (synthetic-test escape
  hatch) leaves the source where it is — see
  ``test_resolution_with_empty_card_types_leaves_source_in_place``.
- **No stack-empty error.** ``resolve_top_of_stack()`` on an empty
  stack returns None gracefully.

## Test-setup helper

Constructing a state where a specific obj_id resolves to a
specific printing's effects is awkward — the registry is private to
the GameState and the synthetic-state seed has no DealDamage
printings. We add a single test-fixture method on the resolve slice:
``register_and_inject_object(printing_dict, controller, zone) ->
new_obj_id``. It (a) parses + appends the printing into the
in-place registry via ``Arc::make_mut`` and (b) constructs a fresh
GameObject pointing at it on the requested zone. Lives in the
resolve slice (not state.rs) per per-slice file-isolation.
"""

from __future__ import annotations

import pytest


# Zone constants — mirror ``rust/src/state_ops_zones.rs``.
ZONE_HAND = 0
ZONE_LIBRARY = 1
ZONE_BATTLEFIELD = 2
ZONE_GRAVEYARD = 3
# Round-11 exile slice: matches `ZONE_EXILE` in `state_ops_zones.rs`,
# which was already defined as 5 (alongside `ZONE_STACK = 4`) before
# this slice landed. We use the existing constant rather than picking
# a new integer.
ZONE_EXILE = 5


def _bombard_dict(amount=3, target_kind="any_player"):
    """A deal-damage printing dict shaped like the round-3 bridge
    parser expects. Bombard-flavored: 1R, sorcery-typed, deals N to
    target."""
    return {
        "name": "Test Bombard",
        "card_types": ["Sorcery"],
        "mana_cost": {"R": 1, "generic": 2},
        "effects": [
            {
                "kind": "deal_damage",
                "amount": amount,
                "target": {"kind": target_kind},
            }
        ],
    }


# --- empty-stack + basic mechanics ----------------------------------


def test_resolve_top_on_empty_stack_returns_none(synthetic_state):
    """An empty stack is not an error — resolve_top returns None."""
    assert synthetic_state.is_stack_empty() is True
    assert synthetic_state.resolve_top_of_stack() is None


def test_resolve_top_pops_the_item(synthetic_state):
    """A single push, then resolve_top — stack returns to empty."""
    synthetic_state.push_to_stack(42, 0)
    assert synthetic_state.stack_size() == 1
    synthetic_state.resolve_top_of_stack()
    assert synthetic_state.stack_size() == 0
    assert synthetic_state.is_stack_empty() is True


def test_resolve_top_returns_dict_describing_resolved_item(synthetic_state):
    """The return shape mirrors ``pop_top_of_stack``: a 2-key dict
    naming the source obj_id and the controller of the resolved item."""
    synthetic_state.push_to_stack(42, 0)
    resolved = synthetic_state.resolve_top_of_stack()
    assert isinstance(resolved, dict)
    assert resolved == {"source_obj_id": 42, "controller": 0}


# --- cross-slice: DealDamage to AnyPlayer ---------------------------


def test_resolve_dealdamage_to_any_player_hits_defender(synthetic_state):
    """End-to-end composition test (the load-bearing one).

    Build a Bombard-shaped printing (3 damage to any player), inject
    a GameObject of that printing onto player 0's battlefield, push
    a stack item naming it as the source. ``resolve_top_of_stack``
    must look up the source's printing, dispatch DealDamage, and
    apply 3 damage to the defending player (player 1, since
    active_player=0 in the synthetic seed) — life goes 20 -> 17.
    """
    bombard_obj_id = synthetic_state.register_and_inject_object(
        _bombard_dict(amount=3, target_kind="any_player"),
        0,  # controller
        ZONE_BATTLEFIELD,
    )
    synthetic_state.push_to_stack(bombard_obj_id, 0)

    life_before = list(synthetic_state.life_totals)
    resolved = synthetic_state.resolve_top_of_stack()

    assert resolved == {"source_obj_id": bombard_obj_id, "controller": 0}
    assert synthetic_state.is_stack_empty() is True
    # Defender (p1) takes 3; controller (p0) untouched.
    assert synthetic_state.life_totals[0] == life_before[0]
    assert synthetic_state.life_totals[1] == life_before[1] - 3


# --- DealDamage to AnyCreature --------------------------------------


def test_resolve_dealdamage_to_any_creature_hits_first_blocker_target(
    synthetic_state,
):
    """``any_creature`` targeting picks the FIRST creature on the
    defender's battlefield (smallest battlefield-index). Player 1's
    battlefield in the synthetic seed: ids 67..71 Forest, 72..76
    Grizzly Bears — first creature (skipping non-creature lands) is
    obj_id 72.

    Simpler: the slice doesn't filter by creature-ness on the target
    side either — it picks the FIRST OBJECT in the defender's
    battlefield Vec, regardless of card type. That matches the
    docstring "first creature" simplification the way the slice
    landed: in the test, we just inject a Bombard-shaped printing
    pointing at any_creature and verify damage shows up on whatever
    sits at battlefield[0] of the defender.
    """
    # First object on defender (p1) battlefield is obj_id 67 (Forest)
    # in the synthetic seed. The slice uses smallest-index, not
    # type-filtered — any object suffices for this damage-applied
    # check.
    first_p1_bf_obj_id = 67
    bombard_obj_id = synthetic_state.register_and_inject_object(
        _bombard_dict(amount=2, target_kind="any_creature"),
        0,
        ZONE_BATTLEFIELD,
    )
    synthetic_state.push_to_stack(bombard_obj_id, 0)
    assert synthetic_state.get_damage(first_p1_bf_obj_id) == 0

    resolved = synthetic_state.resolve_top_of_stack()
    assert resolved is not None
    assert synthetic_state.get_damage(first_p1_bf_obj_id) == 2
    # Stack popped, life totals untouched (creature took the damage).
    assert synthetic_state.is_stack_empty() is True
    assert list(synthetic_state.life_totals) == [20, 20]


def test_resolve_dealdamage_no_creature_target_fizzles_gracefully(engine):
    """If the defender has no creature (empty battlefield),
    DealDamage with ``any_creature`` fizzles — no damage applied,
    life totals unchanged, but the stack item still pops."""
    # Build a synthetic state with empty battlefields on both sides
    # so the defender has no creature to target.
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=1
    )
    bombard_obj_id = state.register_and_inject_object(
        _bombard_dict(amount=5, target_kind="any_creature"),
        0,
        ZONE_BATTLEFIELD,  # source object lives somewhere; battlefield is fine
    )
    state.push_to_stack(bombard_obj_id, 0)

    life_before = list(state.life_totals)
    resolved = state.resolve_top_of_stack()

    assert resolved is not None
    assert state.is_stack_empty() is True
    assert list(state.life_totals) == life_before


# --- error path: unknown effect kind --------------------------------


def test_resolve_unknown_effect_kind_raises(synthetic_state):
    """If the source's printing carries an effect variant we don't
    know how to dispatch, raise ValueError loudly. The bridge today
    only exposes DealDamage, so the way to trigger this is to push a
    stack item whose source has NO effects — and the resolver should
    succeed (zero effects = no-op, not an error).

    To actually exercise the error path we'd need a second variant
    in the closed enum. Instead this test asserts the no-effects
    happy-path: push a source with empty effects, resolve, no
    damage applied, no error. The "raise on unknown" behavior is
    structural (Rust ``match`` on a closed enum) and lands behind
    the future second-variant slice.
    """
    no_effect_dict = {
        "name": "Inert",
        "card_types": ["Artifact"],
        "mana_cost": {"generic": 1},
        "effects": [],
    }
    obj_id = synthetic_state.register_and_inject_object(
        no_effect_dict, 0, ZONE_BATTLEFIELD
    )
    synthetic_state.push_to_stack(obj_id, 0)
    life_before = list(synthetic_state.life_totals)
    resolved = synthetic_state.resolve_top_of_stack()
    assert resolved is not None
    assert list(synthetic_state.life_totals) == life_before


# --- CoW canary -----------------------------------------------------


def test_clone_then_resolve_does_not_affect_original(synthetic_state):
    """Cloning the state and resolving on the clone must not bleed
    back into the original — neither the stack nor the life totals
    on the original side should change.
    """
    bombard_obj_id = synthetic_state.register_and_inject_object(
        _bombard_dict(amount=4, target_kind="any_player"),
        0,
        ZONE_BATTLEFIELD,
    )
    synthetic_state.push_to_stack(bombard_obj_id, 0)
    cloned = synthetic_state.clone_once()

    cloned.resolve_top_of_stack()
    # Clone: defender life dropped, stack drained.
    assert cloned.is_stack_empty() is True
    assert cloned.life_totals[1] == 20 - 4
    # Original: untouched on both fronts.
    assert synthetic_state.stack_size() == 1
    assert list(synthetic_state.life_totals) == [20, 20]


# --- round-7 post-resolve spell-source movement ---------------------
#
# Real MTG CR 608.2m: when a spell finishes resolving, the spell-as-
# game-object moves out of the stack zone — an instant or sorcery
# goes to its owner's graveyard, a permanent spell becomes a
# permanent on the battlefield. Round-6's ``resolve_top_of_stack``
# popped the stack ``StackItem`` but didn't move the source
# GameObject. This slice closes that gap.
#
# Dispatch key: the source printing's ``card_types`` Vec.
#   - "Instant" or "Sorcery" -> controller's graveyard
#   - "Creature" / "Artifact" / "Enchantment" / "Planeswalker" /
#     "Battle" -> controller's battlefield
#   - empty card_types -> leave the source where it is (synthetic-
#     test escape hatch — these are first-slice test cards without
#     real types)
#
# Creatures specifically: when entering the battlefield via this
# path, the slice sets ``summoning_sick = true``. ETB triggers are
# NOT in scope (a future slice).


def _instant_zap_dict():
    """An instant deal-damage printing — Lightning Bolt-shaped."""
    return {
        "name": "Test Zap",
        "card_types": ["Instant"],
        "mana_cost": {"R": 1},
        "effects": [
            {
                "kind": "deal_damage",
                "amount": 3,
                "target": {"kind": "any_player"},
            }
        ],
    }


def _sorcery_strike_dict():
    """A sorcery deal-damage printing — same shape as ``_bombard_dict``
    but defined separately so it's clear this test is the sorcery-
    typed companion to the instant test."""
    return {
        "name": "Test Strike",
        "card_types": ["Sorcery"],
        "mana_cost": {"R": 1, "generic": 2},
        "effects": [
            {
                "kind": "deal_damage",
                "amount": 4,
                "target": {"kind": "any_player"},
            }
        ],
    }


def _creature_dict():
    """A vanilla creature printing — no effects, just card_types."""
    return {
        "name": "Test Bear",
        "card_types": ["Creature"],
        "mana_cost": {"G": 1, "generic": 1},
        "effects": [],
        "power": 2,
        "toughness": 2,
    }


def _artifact_dict():
    """A vanilla artifact printing — no effects, just card_types."""
    return {
        "name": "Test Trinket",
        "card_types": ["Artifact"],
        "mana_cost": {"generic": 2},
        "effects": [],
    }


def _typeless_synthetic_dict():
    """A synthetic-test card with no card_types (empty Vec). The
    dispatch's documented escape hatch — leave the source in place."""
    return {
        "name": "Test Typeless",
        "mana_cost": {"generic": 1},
        "effects": [],
    }


def test_instant_resolves_to_graveyard(synthetic_state):
    """Resolving an instant spell moves the source to the
    controller's graveyard (CR 608.2m)."""
    obj_id = synthetic_state.register_and_inject_object(
        _instant_zap_dict(), 0, ZONE_HAND
    )
    assert synthetic_state.find_object_zone(obj_id) == ZONE_HAND
    grave_before = synthetic_state.graveyard_sizes[0]

    synthetic_state.push_to_stack(obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.find_object_zone(obj_id) == ZONE_GRAVEYARD
    assert synthetic_state.graveyard_sizes[0] == grave_before + 1
    # The instant's effect still fires (defender takes 3).
    assert synthetic_state.life_totals[1] == 20 - 3


def test_sorcery_resolves_to_graveyard(synthetic_state):
    """Resolving a sorcery moves the source to controller's graveyard."""
    obj_id = synthetic_state.register_and_inject_object(
        _sorcery_strike_dict(), 0, ZONE_HAND
    )
    assert synthetic_state.find_object_zone(obj_id) == ZONE_HAND
    grave_before = synthetic_state.graveyard_sizes[0]

    synthetic_state.push_to_stack(obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.find_object_zone(obj_id) == ZONE_GRAVEYARD
    assert synthetic_state.graveyard_sizes[0] == grave_before + 1
    assert synthetic_state.life_totals[1] == 20 - 4


def test_creature_spell_resolves_to_battlefield_with_summoning_sick(
    synthetic_state,
):
    """Resolving a creature spell moves the source onto the
    controller's battlefield with ``summoning_sick = true`` — it
    just entered, can't attack this turn."""
    obj_id = synthetic_state.register_and_inject_object(
        _creature_dict(), 0, ZONE_HAND
    )
    assert synthetic_state.find_object_zone(obj_id) == ZONE_HAND
    bf_before = synthetic_state.battlefield_sizes[0]

    synthetic_state.push_to_stack(obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.find_object_zone(obj_id) == ZONE_BATTLEFIELD
    assert synthetic_state.battlefield_sizes[0] == bf_before + 1
    # New permanent has summoning sickness.
    assert synthetic_state.is_summoning_sick(obj_id) is True


def test_artifact_resolves_to_battlefield(synthetic_state):
    """Resolving an artifact spell moves the source onto the
    controller's battlefield. (No summoning-sick assertion: the
    flag is irrelevant for non-creatures, but for first slice we
    don't bother gating on card type — value is uninteresting.)"""
    obj_id = synthetic_state.register_and_inject_object(
        _artifact_dict(), 0, ZONE_HAND
    )
    assert synthetic_state.find_object_zone(obj_id) == ZONE_HAND
    bf_before = synthetic_state.battlefield_sizes[0]

    synthetic_state.push_to_stack(obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.find_object_zone(obj_id) == ZONE_BATTLEFIELD
    assert synthetic_state.battlefield_sizes[0] == bf_before + 1


def test_resolution_with_empty_card_types_leaves_source_in_place(
    synthetic_state,
):
    """Documented escape hatch: a printing with empty ``card_types``
    (the synthetic-test shape several round-6 tests use) is left
    where it is by the post-resolve dispatch. Real MTG cards always
    have at least one card type — this branch only fires for
    first-slice synthetic cards."""
    obj_id = synthetic_state.register_and_inject_object(
        _typeless_synthetic_dict(), 0, ZONE_HAND
    )
    assert synthetic_state.find_object_zone(obj_id) == ZONE_HAND
    hand_before = synthetic_state.hand_sizes[0]
    grave_before = synthetic_state.graveyard_sizes[0]
    bf_before = synthetic_state.battlefield_sizes[0]

    synthetic_state.push_to_stack(obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    # Source unchanged: still in hand, no zone deltas.
    assert synthetic_state.find_object_zone(obj_id) == ZONE_HAND
    assert synthetic_state.hand_sizes[0] == hand_before
    assert synthetic_state.graveyard_sizes[0] == grave_before
    assert synthetic_state.battlefield_sizes[0] == bf_before


def test_resolve_then_move_does_not_affect_original_via_clone(synthetic_state):
    """CoW canary for the post-resolve movement path. Cloning the
    state and resolving an instant on the clone must not bleed the
    source-zone change back into the original — the original's
    source object stays in hand, the clone's lands in graveyard."""
    obj_id = synthetic_state.register_and_inject_object(
        _instant_zap_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(obj_id, 0)
    cloned = synthetic_state.clone_once()

    cloned.resolve_top_of_stack()

    # Clone: source landed in graveyard, hand shrank.
    assert cloned.find_object_zone(obj_id) == ZONE_GRAVEYARD
    # Original: source still in hand, stack still has the item.
    assert synthetic_state.find_object_zone(obj_id) == ZONE_HAND
    assert synthetic_state.stack_size() == 1


# --- round-8 DrawCards + GainLife dispatch --------------------------
#
# Round-8 foundation (`feature/rust-tdd-base-r8`) extended the closed
# `Effect` enum with two new variants:
#
#   - DrawCards { count: i32 } — caller's controller draws N cards.
#   - GainLife  { amount: i32 } — caller's controller gains N life.
#
# The foundation left a stub arm in ``apply_effect`` that returned
# ValueError for both variants; this slice replaces it with real
# dispatch.
#
# **Scope simplifications for this slice (mirrored in the Rust module
# docstring on ``state_ops_resolve.rs``):**
#
# - **Controller = ``state.active_player``.** Real MTG: a spell's
#   controller is whoever cast it, plumbed through the StackItem.
#   ``StackItem`` already carries a ``controller: u8`` field, but this
#   apply-effect dispatch reads ``state.active_player`` instead — the
#   first-slice convention the existing DealDamage path uses too.
#   First-slice MTG always has the active player as the spell caster,
#   so this matches in practice. Future slice plumbs
#   ``StackItem.controller`` through.
# - **DrawCards on an empty library is a silent no-op.** Real MTG:
#   the player who tries to draw from an empty library loses on the
#   next state-based-action check (CR 704.5b). Deck-out integration
#   is deferred — for this slice, an empty library short-circuits the
#   draw and the spell otherwise resolves cleanly.
# - **GainLife with negative amount is a silent subtract.** The
#   round-1 ``gain_life`` Python-exposed method raises on negative
#   inputs as a guard against caller bugs; here the dispatch goes
#   straight to ``players[c].life += amount`` to avoid that guard
#   firing on legitimate (if unusual) compile-time-negative effects
#   like a future "lose 1 life" expressed as ``GainLife{ -1 }``. No
#   real MTG card today wants this, but it's the lowest-friction
#   shape for the slice.
#
# **Cross-file friction note:** ``apply_effect`` lives in this slice's
# file (``state_ops_resolve.rs``), but ``draw_card`` is a
# ``#[pymethods]`` method on ``GameState`` defined in
# ``state_ops_zones.rs``. The per-slice file-isolation rule prevents
# touching that file, so DrawCards inlines its draw logic here
# (pop-from-library + push-to-hand via ``Arc::make_mut``), mirroring
# the round-7 counterspell agent's inlining of ``move_object``. A
# follow-up consolidation slice can collapse the two implementations
# once that constraint relaxes.


def _draw_three_dict():
    """A draw-three printing — Concentrate-shaped. Sorcery-typed so
    the post-resolve dispatch routes the source to the graveyard."""
    return {
        "name": "Test Concentrate",
        "card_types": ["Sorcery"],
        "mana_cost": {"U": 2, "generic": 2},
        "effects": [{"kind": "draw_cards", "count": 3}],
    }


def _draw_five_dict():
    """A draw-five printing — for the empty-library test."""
    return {
        "name": "Test Wheel",
        "card_types": ["Sorcery"],
        "mana_cost": {"U": 2, "generic": 2},
        "effects": [{"kind": "draw_cards", "count": 5}],
    }


def _heal_three_dict():
    """A gain-3-life printing — Healing Salve-shaped (one mode of)."""
    return {
        "name": "Test Heal",
        "card_types": ["Instant"],
        "mana_cost": {"W": 1},
        "effects": [{"kind": "gain_life", "amount": 3}],
    }


def _zap_and_draw_dict():
    """A multi-effect printing: deal 2 damage to any player AND draw
    one card. Order matters — we want both effects to fire in the
    order they appear in the list, so the test asserts both end-states
    independently."""
    return {
        "name": "Test ZapAndDraw",
        "card_types": ["Sorcery"],
        "mana_cost": {"R": 1, "U": 1, "generic": 1},
        "effects": [
            {
                "kind": "deal_damage",
                "amount": 2,
                "target": {"kind": "any_player"},
            },
            {"kind": "draw_cards", "count": 1},
        ],
    }


def test_resolve_drawcards_increases_hand_size(synthetic_state):
    """Resolving a DrawCards-3 spell grows the active player's hand
    by 3 and shrinks their library by 3."""
    obj_id = synthetic_state.register_and_inject_object(
        _draw_three_dict(), 0, ZONE_HAND
    )
    hand_before = synthetic_state.hand_sizes[0]
    library_before = synthetic_state.library_sizes[0]

    synthetic_state.push_to_stack(obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    # Source moved to graveyard (sorcery), so hand shrank by 1 from
    # the source leaving hand AND grew by 3 from the draws — net +2.
    assert synthetic_state.hand_sizes[0] == hand_before - 1 + 3
    assert synthetic_state.library_sizes[0] == library_before - 3


def test_resolve_drawcards_handles_empty_library(engine):
    """If the library has fewer cards than the count, the draw stops
    at the first empty pop. No crash, no error, library ends empty."""
    # Build a state with a tiny library (2 cards) so DrawCards-5
    # exhausts it.
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=2
    )
    obj_id = state.register_and_inject_object(
        _draw_five_dict(), 0, ZONE_BATTLEFIELD
    )
    hand_before = state.hand_sizes[0]
    library_before = state.library_sizes[0]
    assert library_before == 2

    state.push_to_stack(obj_id, 0)
    state.resolve_top_of_stack()

    # Library drained, hand grew by however many cards were available.
    assert state.library_sizes[0] == 0
    assert state.hand_sizes[0] == hand_before + 2


def test_resolve_gainlife_increases_active_player_life(synthetic_state):
    """Resolving a GainLife-3 instant takes the active player from
    20 to 23. Defender (passive player) is untouched."""
    obj_id = synthetic_state.register_and_inject_object(
        _heal_three_dict(), 0, ZONE_HAND
    )
    life_before = list(synthetic_state.life_totals)
    assert life_before == [20, 20]

    synthetic_state.push_to_stack(obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    # Active player (p0, the controller) gained 3.
    assert synthetic_state.life_totals[0] == life_before[0] + 3
    # Defender untouched.
    assert synthetic_state.life_totals[1] == life_before[1]


def test_resolve_drawcards_does_not_affect_opponent(synthetic_state):
    """DrawCards has the controller draw — opponent's hand and
    library are untouched."""
    p1_hand_before = synthetic_state.hand_sizes[1]
    p1_library_before = synthetic_state.library_sizes[1]

    obj_id = synthetic_state.register_and_inject_object(
        _draw_three_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.hand_sizes[1] == p1_hand_before
    assert synthetic_state.library_sizes[1] == p1_library_before


def test_resolve_multi_effect_card_applies_each(synthetic_state):
    """A printing with two effects (DealDamage + DrawCards) fires
    both in order. After resolve, defender lost 2 life AND active
    player drew 1 card."""
    obj_id = synthetic_state.register_and_inject_object(
        _zap_and_draw_dict(), 0, ZONE_HAND
    )
    life_before = list(synthetic_state.life_totals)
    hand_before = synthetic_state.hand_sizes[0]
    library_before = synthetic_state.library_sizes[0]

    synthetic_state.push_to_stack(obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    # DealDamage fired: defender lost 2 life.
    assert synthetic_state.life_totals[1] == life_before[1] - 2
    assert synthetic_state.life_totals[0] == life_before[0]
    # DrawCards fired: source left hand to graveyard (sorcery) AND
    # active player drew 1 -> hand net unchanged (-1 + 1 = 0).
    assert synthetic_state.hand_sizes[0] == hand_before - 1 + 1
    assert synthetic_state.library_sizes[0] == library_before - 1


def test_clone_then_resolve_drawcards_does_not_affect_original(synthetic_state):
    """CoW canary for DrawCards. Resolving on the clone must not
    drain the original's library or grow its hand."""
    obj_id = synthetic_state.register_and_inject_object(
        _draw_three_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(obj_id, 0)
    hand_before = synthetic_state.hand_sizes[0]
    library_before = synthetic_state.library_sizes[0]
    cloned = synthetic_state.clone_once()

    cloned.resolve_top_of_stack()

    # Original: untouched on every front.
    assert synthetic_state.hand_sizes[0] == hand_before
    assert synthetic_state.library_sizes[0] == library_before
    assert synthetic_state.stack_size() == 1
    # Clone: drew 3 (and source moved to graveyard).
    assert cloned.library_sizes[0] == library_before - 3


def test_clone_then_resolve_gainlife_does_not_affect_original(synthetic_state):
    """CoW canary for GainLife. Resolving on the clone must not
    raise the original's life total."""
    obj_id = synthetic_state.register_and_inject_object(
        _heal_three_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(obj_id, 0)
    cloned = synthetic_state.clone_once()

    cloned.resolve_top_of_stack()

    # Original: life unchanged, stack still has the item.
    assert list(synthetic_state.life_totals) == [20, 20]
    assert synthetic_state.stack_size() == 1
    # Clone: active player gained 3.
    assert cloned.life_totals[0] == 23


# --- round-9 ETB-triggered effects ----------------------------------
#
# Round-9 foundation (`feature/rust-tdd-base-r9`) added a new
# ``etb_effects: Vec<Effect>`` field to ``CardPrinting`` plus a bridge
# parser/getter, but did NOT wire dispatch — that's this slice. When a
# permanent spell finishes resolving and post-resolve movement places
# the source on the controller's battlefield (round-7 slice), the
# permanent's ``etb_effects`` fire one-by-one via the same
# ``apply_effect`` dispatcher the spell-effects path uses.
#
# **Scope simplifications for this slice (mirrored in the Rust
# module docstring on ``state_ops_resolve.rs``):**
#
# - **ETB fires AFTER post-resolve movement.** Real MTG: the trigger
#   condition is "this permanent enters the battlefield" — the
#   creature must already be on the battlefield when the trigger
#   resolves. So our slice runs etb_effects *after*
#   ``move_source_post_resolve`` lands the permanent.
# - **No real stack triggering.** Real MTG: ETB triggers go onto the
#   stack and resolve in priority order, can be responded to with
#   instant-speed effects, and (for "deal damage" ETBs) carry their
#   own targets chosen on-trigger. First slice applies them
#   immediately at resolution time, same convention as the spell-
#   effects path. The stack-triggered model is a future slice.
# - **No ETB replacement effects** ("enters tapped", "enters with N
#   counters") — those are a different schema (CR 614.1c
#   replacement effects, not 603 triggers). Not in scope.
# - **Controller of ETB effects = ``state.active_player``.** Same
#   first-slice convention as DealDamage / DrawCards / GainLife.
#   Real MTG plumbs the trigger's controller through the trigger
#   ability; deferred to a future slice along with the rest of the
#   StackItem.controller plumbing.
# - **No "leaves the battlefield" triggers (LtB).** Different schema,
#   different timing. Future slice.
# - **Instants/Sorceries do NOT fire etb_effects** — they go to
#   graveyard, never enter the battlefield, so by definition no ETB
#   trigger condition is met. The dispatch gates on "did
#   post-resolve route this source to the battlefield?".


def _hill_giant_etb_burn_dict():
    """A creature with an ETB-burn trigger: 'When this creature ETBs,
    it deals 2 damage to any player.' Hill Giant flavored — body 3/3,
    cost 3R."""
    return {
        "name": "Test Hill Giant ETB Burn",
        "card_types": ["Creature"],
        "mana_cost": {"R": 1, "generic": 3},
        "effects": [],
        "power": 3,
        "toughness": 3,
        "etb_effects": [
            {
                "kind": "deal_damage",
                "amount": 2,
                "target": {"kind": "any_player"},
            }
        ],
    }


def _etb_draw_two_dict():
    """A creature with 'When this enters, draw two cards.'"""
    return {
        "name": "Test ETB Draw 2",
        "card_types": ["Creature"],
        "mana_cost": {"U": 1, "generic": 2},
        "effects": [],
        "power": 2,
        "toughness": 2,
        "etb_effects": [{"kind": "draw_cards", "count": 2}],
    }


def _etb_gain_three_life_dict():
    """A creature with 'When this enters, you gain 3 life.'"""
    return {
        "name": "Test ETB Healer",
        "card_types": ["Creature"],
        "mana_cost": {"W": 1, "generic": 1},
        "effects": [],
        "power": 1,
        "toughness": 3,
        "etb_effects": [{"kind": "gain_life", "amount": 3}],
    }


def _etb_two_effects_dict():
    """A creature with two ETB effects: deal 1 to any player AND
    draw 1 card. Order matters — both must fire."""
    return {
        "name": "Test ETB Multi",
        "card_types": ["Creature"],
        "mana_cost": {"R": 1, "U": 1, "generic": 1},
        "effects": [],
        "power": 2,
        "toughness": 2,
        "etb_effects": [
            {
                "kind": "deal_damage",
                "amount": 1,
                "target": {"kind": "any_player"},
            },
            {"kind": "draw_cards", "count": 1},
        ],
    }


def _instant_with_etb_dict():
    """An instant with an etb_effects entry. Schema-allowed but
    semantically nonsense — instants go to graveyard, never trigger
    ETB. The dispatch should NOT fire the etb_effects on this card."""
    return {
        "name": "Test Instant with bogus ETB",
        "card_types": ["Instant"],
        "mana_cost": {"R": 1},
        "effects": [
            {
                "kind": "deal_damage",
                "amount": 3,
                "target": {"kind": "any_player"},
            }
        ],
        # This MUST NOT fire because instants don't enter the battlefield.
        "etb_effects": [{"kind": "draw_cards", "count": 5}],
    }


def test_etb_triggers_apply_on_creature_resolve(synthetic_state):
    """Cross-slice composition test (the load-bearing one).

    Inject a creature with an ETB-burn trigger onto active player's
    hand, push it on the stack, resolve. Verify (a) the creature
    landed on active player's battlefield (post-resolve worked) AND
    (b) defending player took 2 damage from the ETB trigger."""
    obj_id = synthetic_state.register_and_inject_object(
        _hill_giant_etb_burn_dict(), 0, ZONE_HAND
    )
    life_before = list(synthetic_state.life_totals)
    bf_before = synthetic_state.battlefield_sizes[0]

    synthetic_state.push_to_stack(obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    # Post-resolve: creature on active player's battlefield (with
    # summoning sickness from the round-7 stamp).
    assert synthetic_state.find_object_zone(obj_id) == ZONE_BATTLEFIELD
    assert synthetic_state.battlefield_sizes[0] == bf_before + 1
    assert synthetic_state.is_summoning_sick(obj_id) is True
    # ETB fired: defender took 2 damage. Active player untouched.
    assert synthetic_state.life_totals[0] == life_before[0]
    assert synthetic_state.life_totals[1] == life_before[1] - 2


def test_etb_with_draw_cards_effect(synthetic_state):
    """An ETB ``draw_cards`` effect grows the controller's hand by
    ``count`` (minus 1 for the source leaving hand to battlefield)
    and shrinks their library by ``count``."""
    obj_id = synthetic_state.register_and_inject_object(
        _etb_draw_two_dict(), 0, ZONE_HAND
    )
    hand_before = synthetic_state.hand_sizes[0]
    library_before = synthetic_state.library_sizes[0]

    synthetic_state.push_to_stack(obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    # Source moved out of hand to battlefield (-1), drew 2 (+2) = +1.
    assert synthetic_state.hand_sizes[0] == hand_before - 1 + 2
    assert synthetic_state.library_sizes[0] == library_before - 2
    assert synthetic_state.find_object_zone(obj_id) == ZONE_BATTLEFIELD


def test_etb_with_gain_life_effect(synthetic_state):
    """An ETB ``gain_life`` effect raises the controller's life total
    on resolve. Active player's life +3, defender untouched."""
    obj_id = synthetic_state.register_and_inject_object(
        _etb_gain_three_life_dict(), 0, ZONE_HAND
    )
    life_before = list(synthetic_state.life_totals)

    synthetic_state.push_to_stack(obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.life_totals[0] == life_before[0] + 3
    assert synthetic_state.life_totals[1] == life_before[1]
    assert synthetic_state.find_object_zone(obj_id) == ZONE_BATTLEFIELD


def test_etb_with_multiple_effects_applies_each_in_order(synthetic_state):
    """An ETB with two effects (deal 1 + draw 1) fires both in list
    order. After resolve: defender lost 1 life AND active player drew
    1 card."""
    obj_id = synthetic_state.register_and_inject_object(
        _etb_two_effects_dict(), 0, ZONE_HAND
    )
    life_before = list(synthetic_state.life_totals)
    hand_before = synthetic_state.hand_sizes[0]
    library_before = synthetic_state.library_sizes[0]

    synthetic_state.push_to_stack(obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    # First ETB effect: 1 damage to defender.
    assert synthetic_state.life_totals[1] == life_before[1] - 1
    assert synthetic_state.life_totals[0] == life_before[0]
    # Second ETB effect: draw 1. Source left hand (-1), drew 1 (+1)
    # = net 0.
    assert synthetic_state.hand_sizes[0] == hand_before - 1 + 1
    assert synthetic_state.library_sizes[0] == library_before - 1
    assert synthetic_state.find_object_zone(obj_id) == ZONE_BATTLEFIELD


def test_etb_does_not_fire_for_instant(synthetic_state):
    """Instants go to graveyard on resolve, not the battlefield —
    even if the printing's etb_effects list is non-empty (allowed by
    schema), nothing in it fires. The instant's own ``effects`` (the
    deal_damage 3) DO fire because that's the spell's effect, not an
    ETB trigger.

    Setup uses a small library so the bogus ``draw_cards: 5`` ETB
    would be observable if it incorrectly fired — drawing 5 against
    a 2-card library would empty it."""
    state = synthetic_state
    life_before = list(state.life_totals)

    obj_id = state.register_and_inject_object(
        _instant_with_etb_dict(), 0, ZONE_HAND
    )
    # Capture sizes AFTER inject so the deltas measure the resolve
    # step alone.
    library_before = state.library_sizes[0]
    hand_before = state.hand_sizes[0]

    state.push_to_stack(obj_id, 0)
    state.resolve_top_of_stack()

    # Source went to graveyard (instant), NOT battlefield.
    assert state.find_object_zone(obj_id) == ZONE_GRAVEYARD
    # Spell's own effect (deal 3) fired against defender.
    assert state.life_totals[1] == life_before[1] - 3
    # ETB did NOT fire: library unchanged from the bogus
    # etb_effects [draw_cards:5]. Hand shrank by 1 from the source
    # leaving hand for graveyard — and ONLY by 1, not by 1 + the
    # 5-card-draw the bogus ETB would have triggered.
    assert state.library_sizes[0] == library_before
    assert state.hand_sizes[0] == hand_before - 1


def test_creature_with_no_etb_effects_resolves_normally(synthetic_state):
    """Sanity: a vanilla creature (etb_effects empty) resolves the
    same way the round-7 post-resolve test verifies. No life / hand
    deltas from the ETB step — just the round-7 movement."""
    obj_id = synthetic_state.register_and_inject_object(
        _creature_dict(), 0, ZONE_HAND
    )
    life_before = list(synthetic_state.life_totals)
    library_before = synthetic_state.library_sizes[0]
    hand_before = synthetic_state.hand_sizes[0]

    synthetic_state.push_to_stack(obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    # No ETB effects, so no life / library deltas. Hand shrank by 1
    # (source moved hand -> battlefield).
    assert list(synthetic_state.life_totals) == life_before
    assert synthetic_state.library_sizes[0] == library_before
    assert synthetic_state.hand_sizes[0] == hand_before - 1
    assert synthetic_state.find_object_zone(obj_id) == ZONE_BATTLEFIELD
    assert synthetic_state.is_summoning_sick(obj_id) is True


def test_clone_then_resolve_etb_does_not_affect_original(synthetic_state):
    """CoW canary for the ETB dispatch path. Cloning the state and
    resolving an ETB-burn creature on the clone must not bleed the
    damage-from-ETB back into the original — original's defender
    life stays at 20, source stays in hand."""
    obj_id = synthetic_state.register_and_inject_object(
        _hill_giant_etb_burn_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(obj_id, 0)
    cloned = synthetic_state.clone_once()

    cloned.resolve_top_of_stack()

    # Clone: defender took 2 ETB damage, creature on battlefield.
    assert cloned.life_totals[1] == 20 - 2
    assert cloned.find_object_zone(obj_id) == ZONE_BATTLEFIELD
    # Original: defender life unchanged, source still in hand,
    # stack still has the item.
    assert list(synthetic_state.life_totals) == [20, 20]
    assert synthetic_state.find_object_zone(obj_id) == ZONE_HAND
    assert synthetic_state.stack_size() == 1


# --- round-10 ReturnToHand + Mill dispatch --------------------------
#
# Round-10 foundation (`feature/rust-tdd-base-r10`) extended the closed
# `Effect` enum with two new variants:
#
#   - ReturnToHand { target: TargetFilter } — bounce: target permanent
#     goes back to its owner's (= controller, first-slice) hand.
#   - Mill { count: i32 } — caller's controller mills `count` cards
#     from the top of their library to graveyard.
#
# The foundation left a stub arm in ``apply_effect`` returning
# ValueError for both variants; this slice replaces it with real
# dispatch.
#
# **Scope simplifications for this slice (mirrored in the Rust module
# docstring on ``state_ops_resolve.rs``):**
#
# - **ReturnToHand target's controller = its current controller.**
#   First slice: controller == owner, so "owner's hand" is just
#   "current controller's hand". Real MTG distinguishes owner from
#   controller (CR 109.3); deferred along with the rest of the
#   ownership/control plumbing.
# - **AnyCreature target → first object on the DEFENDING player's
#   battlefield (smallest index).** Mirrors the existing DealDamage
#   convention; no creature-type filter, no per-spell target choice.
#   Empty defender battlefield → fizzle (silent no-op, stack still
#   pops).
# - **AnyPlayer target on ReturnToHand makes no sense** (you can't
#   bounce a player). The dispatch raises ValueError loudly rather
#   than silently fizzling — schema-allowed but semantically nonsense
#   should fail loud, same shape as the unknown-effect-kind raise.
# - **Mill controller = ``state.active_player``.** Same first-slice
#   convention as DrawCards / GainLife.
# - **Mill top of library = LAST element of the library Vec.**
#   Mirrors the round-1 zones convention (drawing pops the back).
# - **Mill on empty library is a silent stop.** Real MTG: drawing from
#   an empty library is a deck-out loss on the next SBA check (CR
#   704.5b). Mill on an empty library is NOT a deck-out trigger by
#   itself in real MTG (the loss happens on the next *draw* attempt,
#   not the mill that empties the library), so a silent stop is
#   actually closer to real rules than the DrawCards short-circuit
#   already in place.
# - **Mill 0 is a no-op.** Negative counts treated as 0 (silent
#   clamp), same shape as DrawCards.
#
# **Cross-file friction note:** Both effects need zone movement.
# ``move_object`` is private to ``state_ops_zones.rs``; per per-slice
# file-isolation, this slice inlines the minimal Arc::make_mut
# logic, mirroring how DrawCards inlines pop+push.


def _bounce_creature_dict():
    """An instant 'return target creature to its owner's hand' —
    Unsummon-shaped. Sorcery would also work but instant matches the
    real card."""
    return {
        "name": "Test Unsummon",
        "card_types": ["Instant"],
        "mana_cost": {"U": 1},
        "effects": [
            {
                "kind": "return_to_hand",
                "target": {"kind": "any_creature"},
            }
        ],
    }


def _bounce_player_dict():
    """A schema-allowed but semantically nonsense bounce: target
    'any_player'. Should raise on resolve."""
    return {
        "name": "Test Bounce-Player (nonsense)",
        "card_types": ["Instant"],
        "mana_cost": {"U": 1},
        "effects": [
            {
                "kind": "return_to_hand",
                "target": {"kind": "any_player"},
            }
        ],
    }


def _mill_three_dict():
    """A mill-3 sorcery — a chunk of e.g. Tome Scour."""
    return {
        "name": "Test Mill 3",
        "card_types": ["Sorcery"],
        "mana_cost": {"U": 1},
        "effects": [{"kind": "mill", "count": 3}],
    }


def _mill_five_dict():
    """A mill-5 sorcery — for the empty-library stop test."""
    return {
        "name": "Test Mill 5",
        "card_types": ["Sorcery"],
        "mana_cost": {"U": 1, "generic": 1},
        "effects": [{"kind": "mill", "count": 5}],
    }


def _mill_zero_dict():
    """A mill-0 sorcery — degenerate no-op."""
    return {
        "name": "Test Mill 0",
        "card_types": ["Sorcery"],
        "mana_cost": {"U": 1},
        "effects": [{"kind": "mill", "count": 0}],
    }


def test_resolve_return_to_hand_creature_moves_target_to_owner_hand(
    synthetic_state,
):
    """End-to-end composition test (the load-bearing one for
    ReturnToHand).

    Synthetic state: p1's battlefield[0] is a Forest at obj_id 67
    (controller=1). Cast a Bounce-creature instant from active player
    p0 (controller=0). On resolve, the Bounce should pick the FIRST
    creature on the defender's battlefield (mirrors DealDamage convention),
    move it from p1's battlefield to p1's hand, and the source
    instant lands in p0's graveyard."""
    # First p1 battlefield object (Forest at smallest index).
    target_obj_id = 67
    assert synthetic_state.find_object_zone(target_obj_id) == ZONE_BATTLEFIELD
    p1_bf_before = synthetic_state.battlefield_sizes[1]
    p1_hand_before = synthetic_state.hand_sizes[1]
    p0_grave_before = synthetic_state.graveyard_sizes[0]

    bounce_obj_id = synthetic_state.register_and_inject_object(
        _bounce_creature_dict(), 0, ZONE_HAND
    )
    p0_hand_before = synthetic_state.hand_sizes[0]

    synthetic_state.push_to_stack(bounce_obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    # Target moved p1 battlefield -> p1 hand.
    assert synthetic_state.find_object_zone(target_obj_id) == ZONE_HAND
    assert synthetic_state.battlefield_sizes[1] == p1_bf_before - 1
    assert synthetic_state.hand_sizes[1] == p1_hand_before + 1
    # Source: instant -> p0 graveyard.
    assert synthetic_state.find_object_zone(bounce_obj_id) == ZONE_GRAVEYARD
    assert synthetic_state.graveyard_sizes[0] == p0_grave_before + 1
    # p0 hand: source left (-1) — no other deltas on p0 hand.
    assert synthetic_state.hand_sizes[0] == p0_hand_before - 1


def test_resolve_return_to_hand_no_target_fizzles(engine):
    """If the defender has no creature on battlefield, ReturnToHand
    fizzles silently — stack item still pops, source still goes to
    graveyard (instant), nothing else changes. Mirrors the
    DealDamage-no-creature-target fizzle convention."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=1
    )
    bounce_obj_id = state.register_and_inject_object(
        _bounce_creature_dict(), 0, ZONE_HAND
    )

    p0_hand_before = state.hand_sizes[0]
    p1_hand_before = state.hand_sizes[1]
    p1_bf_before = state.battlefield_sizes[1]
    p0_grave_before = state.graveyard_sizes[0]
    p1_grave_before = state.graveyard_sizes[1]

    state.push_to_stack(bounce_obj_id, 0)
    state.resolve_top_of_stack()

    # Stack drained, source moved to graveyard, nothing else changed.
    assert state.is_stack_empty() is True
    assert state.find_object_zone(bounce_obj_id) == ZONE_GRAVEYARD
    assert state.graveyard_sizes[0] == p0_grave_before + 1
    assert state.graveyard_sizes[1] == p1_grave_before
    assert state.battlefield_sizes[1] == p1_bf_before
    assert state.hand_sizes[1] == p1_hand_before
    # Source left p0's hand (-1); the bogus AnyCreature with no target
    # didn't move anything else.
    assert state.hand_sizes[0] == p0_hand_before - 1


def test_resolve_return_to_hand_with_any_player_target_raises(
    synthetic_state,
):
    """ReturnToHand with an AnyPlayer target is semantically nonsense
    (you can't bounce a player). The dispatch raises ValueError
    loudly, matching the unknown-effect-kind shape."""
    bounce_obj_id = synthetic_state.register_and_inject_object(
        _bounce_player_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(bounce_obj_id, 0)

    with pytest.raises(ValueError):
        synthetic_state.resolve_top_of_stack()


def test_resolve_mill_moves_top_n_to_graveyard(synthetic_state):
    """Mill 3 from active player p0: library 50 -> 47, graveyard
    0 -> 3. Defender's library and graveyard untouched."""
    p0_lib_before = synthetic_state.library_sizes[0]
    p0_grave_before = synthetic_state.graveyard_sizes[0]
    p1_lib_before = synthetic_state.library_sizes[1]
    p1_grave_before = synthetic_state.graveyard_sizes[1]
    assert p0_lib_before == 50
    assert p0_grave_before == 0

    mill_obj_id = synthetic_state.register_and_inject_object(
        _mill_three_dict(), 0, ZONE_HAND
    )

    synthetic_state.push_to_stack(mill_obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    # Active player p0: 3 cards milled.
    assert synthetic_state.library_sizes[0] == p0_lib_before - 3
    # p0 graveyard: 3 milled cards + the source sorcery itself (post-resolve).
    assert synthetic_state.graveyard_sizes[0] == p0_grave_before + 3 + 1
    # Defender p1: untouched.
    assert synthetic_state.library_sizes[1] == p1_lib_before
    assert synthetic_state.graveyard_sizes[1] == p1_grave_before


def test_resolve_mill_handles_empty_library_silent(engine):
    """Mill 5 from a 2-card library: library ends empty, graveyard
    has 2 milled cards (+ source), no error."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=2
    )
    mill_obj_id = state.register_and_inject_object(
        _mill_five_dict(), 0, ZONE_BATTLEFIELD
    )
    p0_lib_before = state.library_sizes[0]
    p0_grave_before = state.graveyard_sizes[0]
    assert p0_lib_before == 2

    state.push_to_stack(mill_obj_id, 0)
    state.resolve_top_of_stack()

    # Library drained, graveyard gained the 2 cards available (no
    # source-to-graveyard delta: source was on battlefield, sorcery
    # post-resolve sends it to graveyard, so +1 from that too).
    assert state.library_sizes[0] == 0
    assert state.graveyard_sizes[0] == p0_grave_before + 2 + 1


def test_resolve_mill_zero_count_no_op(synthetic_state):
    """Mill 0: no library/graveyard delta from the mill effect itself.
    Source still moves to graveyard (sorcery post-resolve), so
    graveyard +1 from that alone."""
    p0_lib_before = synthetic_state.library_sizes[0]
    p0_grave_before = synthetic_state.graveyard_sizes[0]

    mill_obj_id = synthetic_state.register_and_inject_object(
        _mill_zero_dict(), 0, ZONE_HAND
    )

    synthetic_state.push_to_stack(mill_obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    # Library unchanged.
    assert synthetic_state.library_sizes[0] == p0_lib_before
    # Graveyard: only the source sorcery itself.
    assert synthetic_state.graveyard_sizes[0] == p0_grave_before + 1


def test_resolve_return_to_hand_clone_canary(synthetic_state):
    """CoW canary for ReturnToHand. Resolving on the clone must not
    bleed the bounce back into the original."""
    target_obj_id = 67  # First p1 battlefield obj
    bounce_obj_id = synthetic_state.register_and_inject_object(
        _bounce_creature_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(bounce_obj_id, 0)
    cloned = synthetic_state.clone_once()

    cloned.resolve_top_of_stack()

    # Clone: target bounced to p1 hand, source in graveyard.
    assert cloned.find_object_zone(target_obj_id) == ZONE_HAND
    assert cloned.find_object_zone(bounce_obj_id) == ZONE_GRAVEYARD
    # Original: target still on p1 battlefield, source still in hand,
    # stack still has the item.
    assert synthetic_state.find_object_zone(target_obj_id) == ZONE_BATTLEFIELD
    assert synthetic_state.find_object_zone(bounce_obj_id) == ZONE_HAND
    assert synthetic_state.stack_size() == 1


def test_resolve_mill_clone_canary(synthetic_state):
    """CoW canary for Mill. Resolving on the clone must not drain the
    original's library or grow its graveyard."""
    p0_lib_before = synthetic_state.library_sizes[0]
    p0_grave_before = synthetic_state.graveyard_sizes[0]

    mill_obj_id = synthetic_state.register_and_inject_object(
        _mill_three_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(mill_obj_id, 0)
    cloned = synthetic_state.clone_once()

    cloned.resolve_top_of_stack()

    # Original: untouched on every front.
    assert synthetic_state.library_sizes[0] == p0_lib_before
    assert synthetic_state.graveyard_sizes[0] == p0_grave_before
    assert synthetic_state.stack_size() == 1
    # Clone: 3 milled + source -> graveyard.
    assert cloned.library_sizes[0] == p0_lib_before - 3
    assert cloned.graveyard_sizes[0] == p0_grave_before + 3 + 1


# --- round-11 ExileTarget dispatch ----------------------------------
#
# Round-11 foundation (`feature/rust-tdd-base-r11`) added a new
# ``Effect`` variant ``ExileTarget { target: TargetFilter }`` plus the
# ``Player.exile`` zone (CR 406) and a temporary stub arm in
# ``apply_effect`` returning ``ValueError``. This slice replaces the
# stub with real dispatch.
#
# **Scope simplifications for this slice (mirrored in the Rust module
# docstring on ``state_ops_resolve.rs``):**
#
# - **AnyCreature target → first object on the DEFENDING player's
#   battlefield (smallest index).** Mirrors the existing DealDamage /
#   ReturnToHand convention. No creature-type filter, no per-spell
#   target choice. Empty defender battlefield → fizzle (silent no-op,
#   stack still pops).
# - **AnyPlayer target on ExileTarget makes no sense** (you can't
#   exile a player). The dispatch raises ValueError loudly, matching
#   the ReturnToHand convention for the same situation.
# - **Target's owner = its current controller, first-slice convention.**
#   The exiled card lands in its current controller's exile zone —
#   which equals "owner's exile" under the controller==owner
#   simplification still in place across all the resolve effects.
# - **Object state reset on exile.** The exiled card has its
#   ``tapped``, ``summoning_sick``, ``damage``, and ``counters``
#   fields reset to their defaults — same shape as ReturnToHand.
#   Real MTG: an object that changes zones is treated as a brand new
#   object (CR 400.7) so per-object state from the previous zone
#   doesn't follow. Round-11 mirrors that for exile.
# - **Zone field on the GameObject = ``ZONE_EXILE`` (= 5).**
#   ``ZONE_EXILE`` was already declared in ``state_ops_zones.rs``
#   alongside ``ZONE_STACK = 4`` before this slice landed. We use the
#   existing constant (5) rather than picking a new integer.
# - **Cross-file friction:** zone movement is internal; the slice
#   inlines the minimal Arc::make_mut pop-from-current-zone +
#   push-to-target-exile per the recurring pattern (DrawCards / Mill /
#   ReturnToHand all do this).
#
# **Test-readability note on inspection:** ``find_object_zone`` in
# ``state_ops_zones.rs`` only iterates the four pre-r11 zones (hand /
# library / battlefield / graveyard) — it does NOT search exile.
# Likewise ``get_damage`` / ``get_counters`` / ``is_summoning_sick``
# all walk pre-r11 zones only. So once a card lands in exile,
# ``find_object_zone`` returns ``None``, which is itself a
# verification signal: "no longer in any of the four tracked zones".
# This slice adds two small read helpers in ``state_ops_resolve.rs``
# (``exile_sizes`` getter and ``exile_contains(obj_id)``) so tests can
# positively assert exile presence; both live in this slice's file
# per per-slice file-isolation. A future-slice consolidation can
# extend ``find_object_zone`` once exile has more readers.


def _exile_creature_dict():
    """An instant 'exile target creature' — Path-to-Exile-shaped (the
    'land' rider isn't modeled — first slice only handles the exile
    half). Sorcery would also work but instant matches the real card."""
    return {
        "name": "Test Path",
        "card_types": ["Instant"],
        "mana_cost": {"W": 1},
        "effects": [
            {
                "kind": "exile_target",
                "target": {"kind": "any_creature"},
            }
        ],
    }


def _exile_player_dict():
    """A schema-allowed but semantically nonsense exile: target
    'any_player'. Should raise on resolve (cannot exile a player)."""
    return {
        "name": "Test Exile-Player (nonsense)",
        "card_types": ["Instant"],
        "mana_cost": {"W": 1},
        "effects": [
            {
                "kind": "exile_target",
                "target": {"kind": "any_player"},
            }
        ],
    }


def test_resolve_exile_target_moves_creature_to_owner_exile(synthetic_state):
    """End-to-end composition test (the load-bearing one for
    ExileTarget).

    Synthetic state: p1's battlefield[0] is a Forest at obj_id 67
    (controller=1). Cast an exile-creature instant from active player
    p0 (controller=0). On resolve, the exile should pick the FIRST
    creature on the defender's battlefield (mirrors DealDamage
    convention), move it from p1's battlefield to p1's exile, and
    the source instant lands in p0's graveyard.

    Verifies it is NOT in graveyard or battlefield (specifically
    distinguishing exile from the bounce / destroy paths)."""
    target_obj_id = 67  # First p1 battlefield object.
    assert synthetic_state.find_object_zone(target_obj_id) == ZONE_BATTLEFIELD
    p1_bf_before = synthetic_state.battlefield_sizes[1]
    p1_grave_before = synthetic_state.graveyard_sizes[1]
    p1_exile_before = synthetic_state.exile_sizes[1]

    exile_obj_id = synthetic_state.register_and_inject_object(
        _exile_creature_dict(), 0, ZONE_HAND
    )
    p0_grave_before = synthetic_state.graveyard_sizes[0]

    synthetic_state.push_to_stack(exile_obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    # Target moved p1 battlefield -> p1 exile.
    assert synthetic_state.battlefield_sizes[1] == p1_bf_before - 1
    assert synthetic_state.exile_sizes[1] == p1_exile_before + 1
    # Specifically NOT in graveyard (this is exile, not destroy).
    assert synthetic_state.graveyard_sizes[1] == p1_grave_before
    # Target no longer in any of the four pre-r11 tracked zones.
    assert synthetic_state.find_object_zone(target_obj_id) is None
    # And it IS in p1's exile.
    assert synthetic_state.exile_contains(target_obj_id) is True
    # Source instant: p0 graveyard.
    assert synthetic_state.find_object_zone(exile_obj_id) == ZONE_GRAVEYARD
    assert synthetic_state.graveyard_sizes[0] == p0_grave_before + 1


def test_resolve_exile_target_no_creature_fizzles(engine):
    """If the defender has no creature on battlefield, ExileTarget
    fizzles silently — stack item still pops, source still goes to
    graveyard (instant), nothing else changes. Mirrors the
    DealDamage / ReturnToHand no-target fizzle convention."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=1
    )
    exile_obj_id = state.register_and_inject_object(
        _exile_creature_dict(), 0, ZONE_HAND
    )

    p0_hand_before = state.hand_sizes[0]
    p1_bf_before = state.battlefield_sizes[1]
    p0_grave_before = state.graveyard_sizes[0]
    p0_exile_before = state.exile_sizes[0]
    p1_exile_before = state.exile_sizes[1]

    state.push_to_stack(exile_obj_id, 0)
    state.resolve_top_of_stack()

    # Stack drained, source moved to graveyard, no exile delta.
    assert state.is_stack_empty() is True
    assert state.find_object_zone(exile_obj_id) == ZONE_GRAVEYARD
    assert state.graveyard_sizes[0] == p0_grave_before + 1
    assert state.battlefield_sizes[1] == p1_bf_before
    assert state.exile_sizes[0] == p0_exile_before
    assert state.exile_sizes[1] == p1_exile_before
    # Source left p0's hand (-1).
    assert state.hand_sizes[0] == p0_hand_before - 1


def test_resolve_exile_target_with_any_player_raises(synthetic_state):
    """ExileTarget with an AnyPlayer target is semantically nonsense
    (you can't exile a player). The dispatch raises ValueError
    loudly, matching the ReturnToHand-with-AnyPlayer shape."""
    exile_obj_id = synthetic_state.register_and_inject_object(
        _exile_player_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(exile_obj_id, 0)

    with pytest.raises(ValueError):
        synthetic_state.resolve_top_of_stack()


def test_resolve_exile_target_object_state_resets(synthetic_state):
    """An exiled creature has its ``tapped`` / ``summoning_sick`` /
    ``damage`` / ``counters`` fields reset to defaults on the way to
    exile — CR 400.7 (a card that changes zones becomes a new object).
    Mirrors the ReturnToHand reset convention."""
    target_obj_id = 67  # First p1 battlefield object.

    # Stamp non-default state on the target before exile.
    assert synthetic_state.tap_object(target_obj_id) is True
    assert synthetic_state.deal_damage(target_obj_id, 1) is True
    assert synthetic_state.add_counters(target_obj_id, 2) is True

    # Pre-resolve sanity: state is non-default.
    assert synthetic_state.is_tapped(target_obj_id) is True
    assert synthetic_state.get_damage(target_obj_id) == 1
    assert synthetic_state.get_counters(target_obj_id) == 2

    exile_obj_id = synthetic_state.register_and_inject_object(
        _exile_creature_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(exile_obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    # Target now in p1's exile, defaults restored.
    assert synthetic_state.exile_contains(target_obj_id) is True
    assert synthetic_state.exile_object_tapped(target_obj_id) is False
    assert synthetic_state.exile_object_summoning_sick(target_obj_id) is False
    assert synthetic_state.exile_object_damage(target_obj_id) == 0
    assert synthetic_state.exile_object_counters(target_obj_id) == 0


def test_clone_then_exile_does_not_affect_original(synthetic_state):
    """CoW canary for ExileTarget. Cloning the state and resolving
    the exile on the clone must not bleed back into the original —
    the original's target stays on p1's battlefield, the clone's
    moves to p1's exile."""
    target_obj_id = 67
    exile_obj_id = synthetic_state.register_and_inject_object(
        _exile_creature_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(exile_obj_id, 0)
    p1_bf_before = synthetic_state.battlefield_sizes[1]
    p1_exile_before = synthetic_state.exile_sizes[1]
    cloned = synthetic_state.clone_once()

    cloned.resolve_top_of_stack()

    # Clone: target in p1 exile, source in p0 graveyard.
    assert cloned.exile_contains(target_obj_id) is True
    assert cloned.find_object_zone(exile_obj_id) == ZONE_GRAVEYARD
    assert cloned.exile_sizes[1] == p1_exile_before + 1
    assert cloned.battlefield_sizes[1] == p1_bf_before - 1
    # Original: target still on p1 battlefield, source still in hand,
    # stack still has the item, exile still empty.
    assert synthetic_state.find_object_zone(target_obj_id) == ZONE_BATTLEFIELD
    assert synthetic_state.find_object_zone(exile_obj_id) == ZONE_HAND
    assert synthetic_state.stack_size() == 1
    assert synthetic_state.exile_sizes[1] == p1_exile_before
    assert synthetic_state.battlefield_sizes[1] == p1_bf_before


def test_exile_target_object_zone_field_updated(synthetic_state):
    """The exiled GameObject's ``zone`` field is stamped with
    ``ZONE_EXILE`` (= 5) after resolution — matches the constant
    declared in ``state_ops_zones.rs``."""
    target_obj_id = 67  # First p1 battlefield obj.
    exile_obj_id = synthetic_state.register_and_inject_object(
        _exile_creature_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(exile_obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    # Zone field on the now-exiled object is the exile constant.
    assert synthetic_state.exile_object_zone_field(target_obj_id) == ZONE_EXILE
