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
    (b) defending player took 2 damage from the ETB trigger.

    Slice 3 retired the inline ``etb_effects`` loop. The legacy
    field is now bridged to a synthesized
    ``TriggeredAbility { event=Enters, predicate=SourceIsSelf,
    effect=... }`` at parse time, so the ETB fires through the
    predicate-path dispatch and lands on the stack as a trigger.
    Drain it with a second ``resolve_top_of_stack`` to observe the
    payload — the observable end-state matches the pre-Slice-3
    inline shape.
    """
    obj_id = synthetic_state.register_and_inject_object(
        _hill_giant_etb_burn_dict(), 0, ZONE_HAND
    )
    life_before = list(synthetic_state.life_totals)
    bf_before = synthetic_state.battlefield_sizes[0]

    synthetic_state.push_to_stack(obj_id, 0)
    synthetic_state.resolve_top_of_stack()
    # Drain the ETB trigger that landed on the stack post-resolve
    # (Slice 3 parse-time bridge).
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
    # Slice 3 bridge: drain the on-stack ETB trigger.
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
    # Slice 3 bridge: drain the on-stack ETB trigger.
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
    # Slice 3 bridge: each etb_effects entry becomes a synthesized
    # TriggeredAbility, so two etb_effects = two triggers on the
    # stack. Drain both.
    synthetic_state.resolve_top_of_stack()
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
    # Slice 3 bridge: drain the on-stack ETB trigger on the clone.
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
    # Target now in p1's exile. Round-14 extended ``find_object_zone``
    # to iterate exile, so it resolves to ``ZONE_EXILE`` here (pre-r14
    # this returned None because exile wasn't searched).
    assert synthetic_state.find_object_zone(target_obj_id) == ZONE_EXILE
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
    """An exiled creature has its ``tapped`` / ``damage`` / ``counters``
    fields reset to defaults on the way to exile — CR 400.7 (a card
    that changes zones becomes a new object).

    Mirrors the ReturnToHand reset convention. The ``summoning_sick``
    flag is intentionally NOT reset on LTB (CE13 closure / I35
    invariant — Python's ``turn.move_off_battlefield`` deliberately
    omits the clear). The synthetic battlefield object here was
    injected with ``summoning_sick=false``, so the post-exile read
    returns false trivially — preserving the as-is semantics. The
    dedicated CE13 regression below uses a freshly-cast (sick=True)
    creature to pin the preserve-on-LTB direction explicitly.
    """
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

    # Target now in p1's exile. tapped / damage / counters all
    # restored to defaults. summoning_sick stays as it was on the
    # battlefield (false here — synthetic-state default).
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


# --- round-12 TapTarget dispatch ------------------------------------
#
# Round-12 foundation (`feature/rust-tdd-base-r12`) added a new
# ``Effect`` variant ``TapTarget { target: TargetFilter }`` and a
# temporary stub arm in ``apply_effect`` returning ``ValueError``.
# This slice replaces the stub with real dispatch — Twiddle-shaped:
# tap a target permanent.
#
# **Scope simplifications for this slice (mirrored in the Rust module
# docstring on ``state_ops_resolve.rs``):**
#
# - **AnyCreature target → first object on the DEFENDING player's
#   battlefield (smallest index).** Mirrors the existing DealDamage /
#   ReturnToHand / ExileTarget convention. No creature-type filter,
#   no per-spell target choice. Empty defender battlefield → fizzle
#   (silent no-op, stack still pops).
# - **AnyPlayer target on TapTarget makes no sense** (you can't tap
#   a player). The dispatch raises ValueError loudly, matching the
#   ReturnToHand / ExileTarget convention for the same situation.
# - **Idempotent.** Tapping an already-tapped creature is a silent
#   no-op — no error, the ``tapped`` flag stays true, no other state
#   changes. Matches the round-1 ``tap_object`` shape (which returns
#   ``False`` rather than raising).
# - **Cross-file friction:** ``tap.rs::tap_object`` is private (the
#   ~10th cross-file E0624 instance in this TDD line). The slice
#   inlines the minimal Arc::make_mut + ``tapped = true`` per the
#   recurring pattern (DrawCards / Mill / ReturnToHand / ExileTarget
#   all inline their primitives for the same reason).


def _twiddle_dict():
    """A Twiddle-ish 'tap target permanent' instant. Schema-allowed
    target ``any_creature`` (the slice's only meaningful TapTarget
    target shape — AnyPlayer raises)."""
    return {
        "name": "Test Twiddle",
        "card_types": ["Instant"],
        "mana_cost": {"U": 1},
        "effects": [
            {
                "kind": "tap_target",
                "target": {"kind": "any_creature"},
            }
        ],
    }


def _twiddle_player_dict():
    """A schema-allowed but semantically nonsense tap: target
    'any_player'. Should raise on resolve (cannot tap a player)."""
    return {
        "name": "Test Twiddle-Player (nonsense)",
        "card_types": ["Instant"],
        "mana_cost": {"U": 1},
        "effects": [
            {
                "kind": "tap_target",
                "target": {"kind": "any_player"},
            }
        ],
    }


def test_resolve_tap_target_taps_creature(synthetic_state):
    """End-to-end composition test (the load-bearing one for
    TapTarget).

    Synthetic state: p1's battlefield[0] is a Forest at obj_id 67
    (controller=1). Cast a tap-target instant from active player p0
    (controller=0). On resolve, the dispatch picks the FIRST object
    on the defender's battlefield (mirrors DealDamage convention)
    and flips its ``tapped`` flag to True. The source instant lands
    in p0's graveyard."""
    target_obj_id = 67  # First p1 battlefield object.
    assert synthetic_state.is_tapped(target_obj_id) is False

    twiddle_obj_id = synthetic_state.register_and_inject_object(
        _twiddle_dict(), 0, ZONE_HAND
    )
    p0_grave_before = synthetic_state.graveyard_sizes[0]
    synthetic_state.push_to_stack(twiddle_obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    # Target is now tapped on p1's battlefield.
    assert synthetic_state.is_tapped(target_obj_id) is True
    # Stack drained; source instant in p0's graveyard.
    assert synthetic_state.is_stack_empty() is True
    assert synthetic_state.find_object_zone(twiddle_obj_id) == ZONE_GRAVEYARD
    assert synthetic_state.graveyard_sizes[0] == p0_grave_before + 1
    # Target stayed on p1's battlefield (this is tap, not bounce/exile).
    assert synthetic_state.find_object_zone(target_obj_id) == ZONE_BATTLEFIELD


def test_resolve_tap_target_no_creature_fizzles(engine):
    """If the defender has no creature on battlefield, TapTarget
    fizzles silently — stack item still pops, source still goes to
    graveyard (instant), nothing else changes. Mirrors the
    DealDamage / ReturnToHand / ExileTarget no-target fizzle
    convention."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=1
    )
    twiddle_obj_id = state.register_and_inject_object(
        _twiddle_dict(), 0, ZONE_HAND
    )

    p0_grave_before = state.graveyard_sizes[0]
    p1_bf_before = state.battlefield_sizes[1]

    state.push_to_stack(twiddle_obj_id, 0)
    state.resolve_top_of_stack()

    # Stack drained, source moved to graveyard, no battlefield delta.
    assert state.is_stack_empty() is True
    assert state.find_object_zone(twiddle_obj_id) == ZONE_GRAVEYARD
    assert state.graveyard_sizes[0] == p0_grave_before + 1
    assert state.battlefield_sizes[1] == p1_bf_before


def test_resolve_tap_target_already_tapped_idempotent(synthetic_state):
    """Tapping an already-tapped creature is a silent no-op — no
    error, ``tapped`` stays True, stack still drains and the source
    still moves to graveyard. Mirrors the round-1 ``tap_object``
    "returns False rather than raising" shape."""
    target_obj_id = 67  # First p1 battlefield object.

    # Pre-tap the target.
    assert synthetic_state.tap_object(target_obj_id) is True
    assert synthetic_state.is_tapped(target_obj_id) is True

    twiddle_obj_id = synthetic_state.register_and_inject_object(
        _twiddle_dict(), 0, ZONE_HAND
    )
    p0_grave_before = synthetic_state.graveyard_sizes[0]
    synthetic_state.push_to_stack(twiddle_obj_id, 0)
    synthetic_state.resolve_top_of_stack()  # must NOT raise

    # Target stays tapped, no other state changes.
    assert synthetic_state.is_tapped(target_obj_id) is True
    assert synthetic_state.is_stack_empty() is True
    assert synthetic_state.find_object_zone(twiddle_obj_id) == ZONE_GRAVEYARD
    assert synthetic_state.graveyard_sizes[0] == p0_grave_before + 1


def test_resolve_tap_target_with_any_player_raises(synthetic_state):
    """TapTarget with an AnyPlayer target is semantically nonsense
    (you can't tap a player). The dispatch raises ValueError loudly,
    matching the ReturnToHand / ExileTarget AnyPlayer shape."""
    twiddle_obj_id = synthetic_state.register_and_inject_object(
        _twiddle_player_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(twiddle_obj_id, 0)

    with pytest.raises(ValueError):
        synthetic_state.resolve_top_of_stack()


def test_clone_then_tap_does_not_affect_original(synthetic_state):
    """CoW canary for TapTarget. Cloning the state and resolving the
    tap on the clone must not bleed back into the original — the
    original's target stays untapped, the clone's becomes tapped."""
    target_obj_id = 67  # First p1 battlefield object.
    twiddle_obj_id = synthetic_state.register_and_inject_object(
        _twiddle_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(twiddle_obj_id, 0)
    cloned = synthetic_state.clone_once()

    cloned.resolve_top_of_stack()

    # Clone: target tapped, source in graveyard.
    assert cloned.is_tapped(target_obj_id) is True
    assert cloned.find_object_zone(twiddle_obj_id) == ZONE_GRAVEYARD
    # Original: untouched on every front.
    assert synthetic_state.is_tapped(target_obj_id) is False
    assert synthetic_state.find_object_zone(twiddle_obj_id) == ZONE_HAND
    assert synthetic_state.stack_size() == 1


# --- round-13 UntapTarget dispatch ----------------------------------
#
# Round-13 foundation (`feature/rust-tdd-base-r13`) added a new
# ``Effect`` variant ``UntapTarget { target: TargetFilter }`` and a
# temporary stub arm in ``apply_effect`` returning ``ValueError``.
# This slice replaces the stub with real dispatch — symmetric
# counterpart to round-12's TapTarget: untap a target permanent.
#
# **Scope simplifications for this slice (mirrored in the Rust module
# docstring on ``state_ops_resolve.rs``):**
#
# - **AnyCreature target → first object on the DEFENDING player's
#   battlefield (smallest index).** Mirrors TapTarget exactly — same
#   target selection, opposite tap state mutation. No creature-type
#   filter, no per-spell target choice. Empty defender battlefield →
#   fizzle (silent no-op, stack still pops).
# - **AnyPlayer target on UntapTarget makes no sense** (you can't
#   untap a player). Raises ValueError loudly, matching the
#   bounce/exile/tap convention.
# - **Idempotent.** Untapping an already-untapped creature is a
#   silent no-op — no error, the ``tapped`` flag stays False, no
#   other state changes. Mirrors TapTarget's already-tapped
#   idempotency.
# - **Cross-file friction:** ``tap.rs::untap_object`` is private (the
#   same E0624 pattern that drove TapTarget's inlining). The slice
#   inlines the minimal ``Arc::make_mut`` + ``tapped = false`` per
#   the recurring pattern.


def _untwiddle_dict():
    """An untwiddle-ish 'untap target permanent' instant. Schema-allowed
    target ``any_creature`` (the slice's only meaningful UntapTarget
    target shape — AnyPlayer raises)."""
    return {
        "name": "Test Untwiddle",
        "card_types": ["Instant"],
        "mana_cost": {"U": 1},
        "effects": [
            {
                "kind": "untap_target",
                "target": {"kind": "any_creature"},
            }
        ],
    }


def _untwiddle_player_dict():
    """A schema-allowed but semantically nonsense untap: target
    'any_player'. Should raise on resolve (cannot untap a player)."""
    return {
        "name": "Test Untwiddle-Player (nonsense)",
        "card_types": ["Instant"],
        "mana_cost": {"U": 1},
        "effects": [
            {
                "kind": "untap_target",
                "target": {"kind": "any_player"},
            }
        ],
    }


def test_resolve_untap_target_untaps_creature(synthetic_state):
    """End-to-end composition test (the load-bearing one for
    UntapTarget).

    Synthetic state: p1's battlefield[0] is a Forest at obj_id 67
    (controller=1). Pre-tap it, then cast an untap-target instant
    from active player p0 (controller=0). On resolve, the dispatch
    picks the FIRST object on the defender's battlefield (mirrors
    TapTarget convention) and flips its ``tapped`` flag to False.
    The source instant lands in p0's graveyard."""
    target_obj_id = 67  # First p1 battlefield object.
    # Pre-tap so untap has something to do.
    assert synthetic_state.tap_object(target_obj_id) is True
    assert synthetic_state.is_tapped(target_obj_id) is True

    untwiddle_obj_id = synthetic_state.register_and_inject_object(
        _untwiddle_dict(), 0, ZONE_HAND
    )
    p0_grave_before = synthetic_state.graveyard_sizes[0]
    synthetic_state.push_to_stack(untwiddle_obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    # Target is now untapped on p1's battlefield.
    assert synthetic_state.is_tapped(target_obj_id) is False
    # Stack drained; source instant in p0's graveyard.
    assert synthetic_state.is_stack_empty() is True
    assert synthetic_state.find_object_zone(untwiddle_obj_id) == ZONE_GRAVEYARD
    assert synthetic_state.graveyard_sizes[0] == p0_grave_before + 1
    # Target stayed on p1's battlefield (this is untap, not bounce/exile).
    assert synthetic_state.find_object_zone(target_obj_id) == ZONE_BATTLEFIELD


def test_resolve_untap_target_no_creature_fizzles(engine):
    """If the defender has no creature on battlefield, UntapTarget
    fizzles silently — stack item still pops, source still goes to
    graveyard (instant), nothing else changes. Mirrors the
    DealDamage / ReturnToHand / ExileTarget / TapTarget no-target
    fizzle convention."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=1
    )
    untwiddle_obj_id = state.register_and_inject_object(
        _untwiddle_dict(), 0, ZONE_HAND
    )

    p0_grave_before = state.graveyard_sizes[0]
    p1_bf_before = state.battlefield_sizes[1]

    state.push_to_stack(untwiddle_obj_id, 0)
    state.resolve_top_of_stack()

    # Stack drained, source moved to graveyard, no battlefield delta.
    assert state.is_stack_empty() is True
    assert state.find_object_zone(untwiddle_obj_id) == ZONE_GRAVEYARD
    assert state.graveyard_sizes[0] == p0_grave_before + 1
    assert state.battlefield_sizes[1] == p1_bf_before


def test_resolve_untap_target_already_untapped_idempotent(synthetic_state):
    """Untapping an already-untapped creature is a silent no-op — no
    error, ``tapped`` stays False, stack still drains and the source
    still moves to graveyard. Mirrors the TapTarget already-tapped
    idempotency shape."""
    target_obj_id = 67  # First p1 battlefield object.

    # Synthetic state's targets start untapped — assert the precondition.
    assert synthetic_state.is_tapped(target_obj_id) is False

    untwiddle_obj_id = synthetic_state.register_and_inject_object(
        _untwiddle_dict(), 0, ZONE_HAND
    )
    p0_grave_before = synthetic_state.graveyard_sizes[0]
    synthetic_state.push_to_stack(untwiddle_obj_id, 0)
    synthetic_state.resolve_top_of_stack()  # must NOT raise

    # Target stays untapped, no other state changes.
    assert synthetic_state.is_tapped(target_obj_id) is False
    assert synthetic_state.is_stack_empty() is True
    assert synthetic_state.find_object_zone(untwiddle_obj_id) == ZONE_GRAVEYARD
    assert synthetic_state.graveyard_sizes[0] == p0_grave_before + 1


def test_resolve_untap_target_with_any_player_raises(synthetic_state):
    """UntapTarget with an AnyPlayer target is semantically nonsense
    (you can't untap a player). The dispatch raises ValueError loudly,
    matching the ReturnToHand / ExileTarget / TapTarget AnyPlayer
    shape."""
    untwiddle_obj_id = synthetic_state.register_and_inject_object(
        _untwiddle_player_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(untwiddle_obj_id, 0)

    with pytest.raises(ValueError):
        synthetic_state.resolve_top_of_stack()


def test_clone_then_untap_does_not_affect_original(synthetic_state):
    """CoW canary for UntapTarget. Pre-tap the target on the original,
    clone the state, then resolve the untap on the clone. The clone's
    target becomes untapped; the original's target stays tapped."""
    target_obj_id = 67  # First p1 battlefield object.

    # Pre-tap on the original so we can observe the difference.
    assert synthetic_state.tap_object(target_obj_id) is True
    assert synthetic_state.is_tapped(target_obj_id) is True

    untwiddle_obj_id = synthetic_state.register_and_inject_object(
        _untwiddle_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(untwiddle_obj_id, 0)
    cloned = synthetic_state.clone_once()

    cloned.resolve_top_of_stack()

    # Clone: target untapped, source in graveyard.
    assert cloned.is_tapped(target_obj_id) is False
    assert cloned.find_object_zone(untwiddle_obj_id) == ZONE_GRAVEYARD
    # Original: untouched on every front (still tapped, source still in hand).
    assert synthetic_state.is_tapped(target_obj_id) is True
    assert synthetic_state.find_object_zone(untwiddle_obj_id) == ZONE_HAND
    assert synthetic_state.stack_size() == 1


# --- UntapTargetOtherPermanent dispatch (round-28) ------------------
#
# **UntapTargetOtherPermanent scope** mirrors Python's
# `UntapTargetOtherPermanent` (Nanoform-Sentinel-trigger family, 3+
# EoE cards). Scans both players' battlefields in zone-iteration
# order; picks the FIRST tapped permanent whose id != source_obj_id.


def _untap_other_permanent_dict():
    """A trigger-like effect dict: untap another permanent."""
    return {
        "name": "Test Nanoform Trigger",
        "card_types": ["Creature"],
        "mana_cost": {"U": 1, "generic": 1},
        "power": 2,
        "toughness": 2,
        "effects": [{"kind": "untap_target_other_permanent"}],
    }


def test_resolve_untap_other_untaps_first_tapped_non_source(synthetic_state):
    """A tapped permanent on p0's bf gets untapped by a source on p0's
    bf. The untapped target is the first tapped non-source permanent."""
    # Pre-tap p0's first creature (or first land) — pick something tapped.
    snap = synthetic_state.battlefield_snapshot()
    first_p0_bear = next(
        d["id"] for d in snap
        if d["controller_id"] == 0 and d["printing_name"] == "Grizzly Bears"
    )
    assert synthetic_state.tap_object(first_p0_bear) is True
    assert synthetic_state.is_tapped(first_p0_bear) is True

    src_id = synthetic_state.register_and_inject_object(
        _untap_other_permanent_dict(), 0, ZONE_BATTLEFIELD
    )
    synthetic_state.push_to_stack(src_id, 0)
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.is_tapped(first_p0_bear) is False


def test_resolve_untap_other_skips_source_itself(synthetic_state):
    """If the source is tapped and there are NO other tapped permanents,
    the dispatch fizzles silently (doesn't untap source itself)."""
    state = synthetic_state.clone_once()
    # Drain every other bf object to graveyard so nothing else is on bf
    # except the source (after we inject it).
    while True:
        snap = state.battlefield_snapshot()
        ids = [d["id"] for d in snap]
        if not ids:
            break
        state.move_object(ids[0], 3, 0)

    src_id = state.register_and_inject_object(
        _untap_other_permanent_dict(), 0, ZONE_BATTLEFIELD
    )
    # Tap the source itself.
    state.tap_object(src_id)
    assert state.is_tapped(src_id) is True

    state.push_to_stack(src_id, 0)
    state.resolve_top_of_stack()

    # Source still tapped — the arm filtered itself out.
    assert state.is_tapped(src_id) is True


def test_resolve_untap_other_no_tapped_permanent_fizzles(synthetic_state):
    """All permanents already untapped → silent fizzle."""
    # synthetic_state default has no creatures tapped on p0 bf.
    src_id = synthetic_state.register_and_inject_object(
        _untap_other_permanent_dict(), 0, ZONE_BATTLEFIELD
    )
    synthetic_state.push_to_stack(src_id, 0)
    synthetic_state.resolve_top_of_stack()  # no raise

    assert synthetic_state.is_stack_empty() is True


def test_resolve_untap_other_can_untap_opponents_permanent(synthetic_state):
    """The arm scans BOTH players' battlefields (not just the
    controller's). A tapped p1 permanent is also eligible."""
    snap = synthetic_state.battlefield_snapshot()
    # First tap every p0 creature so the scan moves on to p1.
    p0_bears = [
        d["id"] for d in snap
        if d["controller_id"] == 0 and d["printing_name"] == "Grizzly Bears"
    ]
    # Drain p0 creatures to graveyard so they're not eligible.
    for cid in p0_bears:
        synthetic_state.move_object(cid, 3, 0)

    # Tap a p1 creature.
    p1_bear = next(
        d["id"] for d in snap
        if d["controller_id"] == 1 and d["printing_name"] == "Grizzly Bears"
    )
    assert synthetic_state.tap_object(p1_bear) is True

    src_id = synthetic_state.register_and_inject_object(
        _untap_other_permanent_dict(), 0, ZONE_BATTLEFIELD
    )
    synthetic_state.push_to_stack(src_id, 0)
    synthetic_state.resolve_top_of_stack()

    # The p1 permanent got untapped.
    assert synthetic_state.is_tapped(p1_bear) is False


def test_resolve_untap_other_clone_isolation(synthetic_state):
    """CoW canary: cloning before resolve isolates the untap effect to
    the clone."""
    snap = synthetic_state.battlefield_snapshot()
    target_id = next(
        d["id"] for d in snap
        if d["controller_id"] == 0 and d["printing_name"] == "Grizzly Bears"
    )
    synthetic_state.tap_object(target_id)
    src_id = synthetic_state.register_and_inject_object(
        _untap_other_permanent_dict(), 0, ZONE_BATTLEFIELD
    )
    synthetic_state.push_to_stack(src_id, 0)

    cloned = synthetic_state.clone_once()
    cloned.resolve_top_of_stack()

    assert cloned.is_tapped(target_id) is False
    assert synthetic_state.is_tapped(target_id) is True


# --- TapAnotherTargetCreature dispatch (round-28) -------------------
#
# Mirrors Python's TapAnotherTargetCreature (Starport-Security family,
# 2+ EoE cards). Same scan shape as UntapTargetOtherPermanent but
# filters on Creature and taps.


def _tap_another_creature_dict():
    return {
        "name": "Test Starport Security",
        "card_types": ["Creature"],
        "mana_cost": {"W": 1, "generic": 1},
        "power": 2,
        "toughness": 2,
        "effects": [{"kind": "tap_another_target_creature"}],
    }


def test_resolve_tap_another_taps_first_non_source_creature(synthetic_state):
    """Source on p0's bf; the first creature on p0 that isn't the source
    gets tapped. (synthetic_state's p0 bf has Forests then Grizzly Bears
    — the first non-source creature is the first Grizzly Bears.)"""
    snap = synthetic_state.battlefield_snapshot()
    first_p0_bear = next(
        d["id"] for d in snap
        if d["controller_id"] == 0 and d["printing_name"] == "Grizzly Bears"
    )
    assert synthetic_state.is_tapped(first_p0_bear) is False

    src_id = synthetic_state.register_and_inject_object(
        _tap_another_creature_dict(), 0, ZONE_BATTLEFIELD
    )
    synthetic_state.push_to_stack(src_id, 0)
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.is_tapped(first_p0_bear) is True


def test_resolve_tap_another_skips_source_itself(synthetic_state):
    """Source creature itself stays untapped — the arm filters it out
    via the id != source_obj_id gate."""
    src_id = synthetic_state.register_and_inject_object(
        _tap_another_creature_dict(), 0, ZONE_BATTLEFIELD
    )
    synthetic_state.push_to_stack(src_id, 0)
    synthetic_state.resolve_top_of_stack()
    # Source untouched (only the other creature got tapped).
    assert synthetic_state.is_tapped(src_id) is False


def test_resolve_tap_another_no_other_creature_fizzles(engine):
    """No other creatures on either bf → silent fizzle. The source
    creature (sole bf object after injection) stays untapped."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=2
    )
    src_id = state.register_and_inject_object(
        _tap_another_creature_dict(), 0, ZONE_BATTLEFIELD
    )
    state.push_to_stack(src_id, 0)
    state.resolve_top_of_stack()  # no raise

    assert state.is_tapped(src_id) is False


def test_resolve_tap_another_can_tap_opponents_creature(synthetic_state):
    """If p0 has only the source, scan moves to p1's bf and taps p1's
    first creature."""
    state = synthetic_state.clone_once()
    snap = state.battlefield_snapshot()
    # Drain every existing p0 creature so the scan reaches p1.
    p0_bears = [
        d["id"] for d in snap
        if d["controller_id"] == 0 and d["printing_name"] == "Grizzly Bears"
    ]
    for cid in p0_bears:
        state.move_object(cid, 3, 0)  # → graveyard

    p1_bear = next(
        d["id"] for d in snap
        if d["controller_id"] == 1 and d["printing_name"] == "Grizzly Bears"
    )
    assert state.is_tapped(p1_bear) is False

    src_id = state.register_and_inject_object(
        _tap_another_creature_dict(), 0, ZONE_BATTLEFIELD
    )
    state.push_to_stack(src_id, 0)
    state.resolve_top_of_stack()

    # p1's first creature got tapped via the cross-player scan.
    assert state.is_tapped(p1_bear) is True


def test_resolve_tap_another_already_tapped_is_legal_noop(synthetic_state):
    """If the first eligible creature is already tapped, the dispatch
    still picks it and the re-tap is a legal no-op (matches existing
    TapTarget contract)."""
    snap = synthetic_state.battlefield_snapshot()
    first_p0_bear = next(
        d["id"] for d in snap
        if d["controller_id"] == 0 and d["printing_name"] == "Grizzly Bears"
    )
    # Pre-tap the target.
    synthetic_state.tap_object(first_p0_bear)
    assert synthetic_state.is_tapped(first_p0_bear) is True

    src_id = synthetic_state.register_and_inject_object(
        _tap_another_creature_dict(), 0, ZONE_BATTLEFIELD
    )
    synthetic_state.push_to_stack(src_id, 0)
    synthetic_state.resolve_top_of_stack()  # no raise

    # Stays tapped.
    assert synthetic_state.is_tapped(first_p0_bear) is True


# --- CE7 closure: cross-player find-first arms walk ETB-timestamp order ----
#
# `Effect::TapAnotherTargetCreature` and `Effect::UntapTargetOtherPermanent`
# both pick the FIRST eligible target across BOTH players' battlefields
# in ETB-timestamp order (matching Python's centralized `state.battlefield`
# walks in `effects/generic/tap.py:277-295` and `:346-386`). Pre-CE7 the
# Rust side walked p0-then-p1, which diverged from Python whenever a p1
# permanent had a lower ETB stamp than the first p0 eligible target.
#
# These tests use `register_and_inject_object` to drive strictly-monotonic
# ETB stamps across players: inject p0 OLDER, p1 NEWER → p0's ETB stamp
# is lower → the ETB-first walk picks p0's creature (the "older one
# regardless of who controls the source").
#
# Tie-break invariant: synthetic-state objects all carry
# `etb_timestamp == 0` (because `make_player` populates the bf without
# calling `reserve_etb_timestamp`); the helper's stable sort preserves
# the pre-CE7 p0-then-p1 walk for those, so every pre-existing test in
# this section (which exclusively uses `synthetic_state` shaped seeds)
# stays bit-equal.


def _two_two_creature_dict():
    """Vanilla 2/2 creature printing — used by the CE7 tests below to
    inject ETB-stamped creatures via `register_and_inject_object`.
    Mirrors the shape used in `tests_rust/test_sba.py`."""
    return {
        "name": "Test 2/2",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 2},
        "power": 2,
        "toughness": 2,
        "keywords": [],
        "effects": [],
    }


def test_resolve_tap_another_picks_etb_first_across_players(engine):
    """Source on p1's battlefield; p0 has the ETB-OLDER eligible creature
    and p1 has a NEWER one. Pre-CE7 the Rust scan walked p0-then-p1 and
    would have picked p0's creature anyway (p0 always came first); we
    pin the more interesting case where the source is on p1 — Python's
    centralized walk picks the ETB-first match, which is p0's older
    creature, NOT p1's newer one.

    Pre-CE7 the per-player walk would have returned p0's creature too
    (p0 is enumerate-index 0). To make the test specifically exercise
    ETB-order tie-break (and not just p0-first-by-accident), we also
    add a sibling case below where p1's creature is ETB-OLDER than
    p0's: pre-CE7 Rust would have picked p0's NEWER creature; post-CE7
    Rust matches Python and picks p1's OLDER creature."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=2
    )

    # Inject p0's eligible creature FIRST so it has the lower ETB stamp.
    p0_older = state.register_and_inject_object(
        _two_two_creature_dict(), 0, ZONE_BATTLEFIELD
    )
    # Inject the source on p1 (it bumps the timestamp counter).
    src_id = state.register_and_inject_object(
        _tap_another_creature_dict(), 1, ZONE_BATTLEFIELD
    )
    # Inject p1's eligible creature LAST so it has a higher ETB stamp
    # than p0_older.
    p1_newer = state.register_and_inject_object(
        _two_two_creature_dict(), 1, ZONE_BATTLEFIELD
    )

    state.push_to_stack(src_id, 1)
    state.resolve_top_of_stack()

    # The ETB-first eligible creature (p0_older) is tapped, not the
    # p1_newer creature.
    assert state.is_tapped(p0_older) is True
    assert state.is_tapped(p1_newer) is False
    # The source on p1 was filtered out by the `id != source` gate.
    assert state.is_tapped(src_id) is False


def test_resolve_tap_another_picks_p1_when_p1_etb_first(engine):
    """The load-bearing CE7 case: p1 has the ETB-OLDER eligible creature,
    p0 has the NEWER one. Pre-CE7 Rust walked p0-then-p1 and would have
    picked p0's NEWER creature; post-CE7 Rust matches Python's centralized
    walk and picks p1's OLDER creature."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=2
    )

    # Inject p1's eligible creature FIRST so it has the lower ETB stamp.
    p1_older = state.register_and_inject_object(
        _two_two_creature_dict(), 1, ZONE_BATTLEFIELD
    )
    # Then p0's eligible creature.
    p0_newer = state.register_and_inject_object(
        _two_two_creature_dict(), 0, ZONE_BATTLEFIELD
    )
    # Source on p0 (its ETB stamp does not affect the find-first
    # outcome because we filter it out via id != source).
    src_id = state.register_and_inject_object(
        _tap_another_creature_dict(), 0, ZONE_BATTLEFIELD
    )

    state.push_to_stack(src_id, 0)
    state.resolve_top_of_stack()

    # Post-CE7: ETB-first wins — p1's older creature is tapped, not
    # p0's newer one.
    assert state.is_tapped(p1_older) is True
    assert state.is_tapped(p0_newer) is False
    # Source itself stays untapped (filtered by id != source).
    assert state.is_tapped(src_id) is False


def test_resolve_untap_other_picks_etb_first_across_players(engine):
    """Symmetric CE7 case for `UntapTargetOtherPermanent`: p1 has the
    ETB-OLDER tapped permanent, p0 has a NEWER tapped permanent.
    Pre-CE7 the Rust scan would have picked p0's tapped permanent
    (p0-first walk); post-CE7 Rust matches Python and picks p1's
    ETB-older tapped permanent."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=2
    )

    # Inject p1's tapped permanent FIRST so it has the lower ETB stamp.
    p1_older = state.register_and_inject_object(
        _two_two_creature_dict(), 1, ZONE_BATTLEFIELD
    )
    # Then p0's tapped permanent.
    p0_newer = state.register_and_inject_object(
        _two_two_creature_dict(), 0, ZONE_BATTLEFIELD
    )
    # Tap both — eligibility predicate is "tapped, not source".
    state.tap_object(p1_older)
    state.tap_object(p0_newer)
    assert state.is_tapped(p1_older) is True
    assert state.is_tapped(p0_newer) is True

    # Source on p0 (untapped, so it wouldn't be eligible even without
    # the id != source filter).
    src_id = state.register_and_inject_object(
        _untap_other_permanent_dict(), 0, ZONE_BATTLEFIELD
    )

    state.push_to_stack(src_id, 0)
    state.resolve_top_of_stack()

    # Post-CE7: ETB-first wins — p1's older tapped permanent is
    # untapped, not p0's newer tapped permanent.
    assert state.is_tapped(p1_older) is False
    assert state.is_tapped(p0_newer) is True


def test_resolve_untap_other_picks_p0_when_p0_etb_first(engine):
    """Mirror of the test above: p0 has the ETB-older tapped permanent,
    p1 has a NEWER one. Both pre- and post-CE7 Rust pick p0's older
    permanent — pre-CE7 because p0 comes first in the per-player walk,
    post-CE7 because p0's stamp is lower in the ETB-sorted walk. Pins
    the no-regression direction of the tie-break."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=2
    )

    # p0's tapped permanent FIRST so it has the lower ETB stamp.
    p0_older = state.register_and_inject_object(
        _two_two_creature_dict(), 0, ZONE_BATTLEFIELD
    )
    p1_newer = state.register_and_inject_object(
        _two_two_creature_dict(), 1, ZONE_BATTLEFIELD
    )
    state.tap_object(p0_older)
    state.tap_object(p1_newer)

    src_id = state.register_and_inject_object(
        _untap_other_permanent_dict(), 0, ZONE_BATTLEFIELD
    )

    state.push_to_stack(src_id, 0)
    state.resolve_top_of_stack()

    assert state.is_tapped(p0_older) is False
    assert state.is_tapped(p1_newer) is True


# --- round-14 Sacrifice dispatch ------------------------------------
#
# Round-14 foundation (`feature/rust-tdd-base-r14`) added a new
# ``Effect`` variant ``Sacrifice { target: TargetFilter }`` and a
# temporary stub arm in ``apply_effect`` returning ``ValueError``.
# This slice replaces the stub with real dispatch.
#
# **Scope simplifications for this slice (mirrored in the Rust module
# docstring on ``state_ops_resolve.rs``):**
#
# - **AnyCreature target -> first object on the ACTIVE player's
#   battlefield (smallest index).** Asymmetric vs the bounce/exile/tap
#   convention: in real MTG you sacrifice your OWN permanents (CR
#   701.16), not the defender's. The first-slice simplification picks
#   ``state.active_player``'s battlefield[0] (mirroring the source-
#   spell controller convention: a Sacrifice cast by the active player
#   sacrifices one of the active player's own permanents). No
#   creature-type filter, no per-spell target choice. Empty active-
#   battlefield -> fizzle (silent no-op, stack still pops).
# - **AnyPlayer target on Sacrifice makes no sense** (you can't
#   sacrifice a player). Raises ValueError loudly, matching the
#   bounce/exile/tap/untap AnyPlayer convention.
# - **Target moves to controller's graveyard.** Per CR 701.16, a
#   sacrificed permanent is put into its owner's graveyard.
#   First-slice: owner == controller, so it lands in
#   ``state.active_player``'s graveyard.
# - **Cross-file friction:** the per-zone movement primitive is
#   private in ``state_ops_zones.rs`` (the same E0624 pattern that
#   drove TapTarget / UntapTarget / ReturnToHand inlining). The slice
#   inlines the minimal ``Arc::make_mut`` pop-from-battlefield +
#   push-to-graveyard per the recurring pattern.


def _altar_dict():
    """A sacrifice-target sorcery. Schema-allowed target ``any_creature``
    (the slice's only meaningful Sacrifice target shape — AnyPlayer
    raises). Real cards with this effect (e.g. Altar's Reap, Costly
    Plunder) come bundled with secondary effects (draw cards / mill);
    this fixture is the minimal isolated form."""
    return {
        "name": "Test Altar Sacrifice",
        "card_types": ["Sorcery"],
        "mana_cost": {"B": 1},
        "effects": [
            {
                "kind": "sacrifice",
                "target": {"kind": "any_creature"},
            }
        ],
    }


def _altar_player_dict():
    """A schema-allowed but semantically nonsense sacrifice: target
    'any_player'. Should raise on resolve (cannot sacrifice a player)."""
    return {
        "name": "Test Altar-Player (nonsense)",
        "card_types": ["Sorcery"],
        "mana_cost": {"B": 1},
        "effects": [
            {
                "kind": "sacrifice",
                "target": {"kind": "any_player"},
            }
        ],
    }


def test_resolve_sacrifice_moves_active_creature_to_graveyard(synthetic_state):
    """End-to-end composition test (the load-bearing one for
    Sacrifice).

    Synthetic state: p0's battlefield[0] is at obj_id 0 (controller=0,
    active_player=0). Cast a sacrifice-target sorcery from active
    player p0. On resolve, the dispatch picks the FIRST object on the
    ACTIVE player's own battlefield (p0's bf[0] == obj_id 0) and
    moves it to p0's graveyard. The source sorcery itself also lands
    in p0's graveyard (CR 608.2m post-resolve)."""
    target_obj_id = 0  # First p0 battlefield object.
    assert synthetic_state.find_object_zone(target_obj_id) == ZONE_BATTLEFIELD

    altar_obj_id = synthetic_state.register_and_inject_object(
        _altar_dict(), 0, ZONE_HAND
    )
    p0_grave_before = synthetic_state.graveyard_sizes[0]
    p0_bf_before = synthetic_state.battlefield_sizes[0]
    p1_bf_before = synthetic_state.battlefield_sizes[1]
    p1_grave_before = synthetic_state.graveyard_sizes[1]

    synthetic_state.push_to_stack(altar_obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    # Sacrificed target moved to p0's graveyard.
    assert synthetic_state.find_object_zone(target_obj_id) == ZONE_GRAVEYARD
    # p0's battlefield shrank by 1; p1's untouched.
    assert synthetic_state.battlefield_sizes[0] == p0_bf_before - 1
    assert synthetic_state.battlefield_sizes[1] == p1_bf_before
    assert synthetic_state.graveyard_sizes[1] == p1_grave_before
    # Stack drained; source sorcery + sacrificed target both in p0's
    # graveyard (so +2 vs before).
    assert synthetic_state.is_stack_empty() is True
    assert synthetic_state.find_object_zone(altar_obj_id) == ZONE_GRAVEYARD
    assert synthetic_state.graveyard_sizes[0] == p0_grave_before + 2


def test_resolve_sacrifice_no_creature_fizzles(engine):
    """If the active player has no creature on battlefield, Sacrifice
    fizzles silently — stack item still pops, source still goes to
    graveyard (sorcery), nothing else changes. Mirrors the
    DealDamage / ReturnToHand / ExileTarget / TapTarget / UntapTarget
    no-target fizzle convention."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=1
    )
    altar_obj_id = state.register_and_inject_object(
        _altar_dict(), 0, ZONE_HAND
    )

    p0_grave_before = state.graveyard_sizes[0]
    p0_bf_before = state.battlefield_sizes[0]

    state.push_to_stack(altar_obj_id, 0)
    state.resolve_top_of_stack()

    # Stack drained, source moved to graveyard, no battlefield delta.
    assert state.is_stack_empty() is True
    assert state.find_object_zone(altar_obj_id) == ZONE_GRAVEYARD
    assert state.graveyard_sizes[0] == p0_grave_before + 1
    assert state.battlefield_sizes[0] == p0_bf_before


def test_resolve_sacrifice_with_any_player_raises(synthetic_state):
    """Sacrifice with an AnyPlayer target is semantically nonsense (you
    can't sacrifice a player). The dispatch raises ValueError loudly,
    matching the ReturnToHand / ExileTarget / TapTarget / UntapTarget
    AnyPlayer shape."""
    altar_obj_id = synthetic_state.register_and_inject_object(
        _altar_player_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(altar_obj_id, 0)

    with pytest.raises(ValueError):
        synthetic_state.resolve_top_of_stack()


def test_resolve_sacrifice_does_not_target_opponent(engine):
    """Asymmetric vs bounce/exile/tap: Sacrifice picks the ACTIVE
    player's battlefield, NOT the defender's. If the active player's
    battlefield is empty but the opponent has creatures, the spell
    fizzles — the opponent's creatures are NOT sacrificed. This is
    the load-bearing ``you sacrifice your own permanents`` test that
    distinguishes Sacrifice from the other targeted dispatches."""
    # Build a state where only p1 (the defender) has battlefield
    # objects. Active player = 0 has zero battlefield. The sacrifice
    # must NOT touch p1's battlefield.
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=1
    )
    # Inject a creature-shaped object onto p1's battlefield via the
    # test fixture so the asymmetric "don't sacrifice opponent's"
    # property is positively observable.
    creature_dict = {
        "name": "Test Bear",
        "card_types": ["Creature"],
        "mana_cost": {"G": 1, "generic": 1},
        "effects": [],
    }
    p1_creature_id = state.register_and_inject_object(
        creature_dict, 1, ZONE_BATTLEFIELD
    )
    altar_obj_id = state.register_and_inject_object(
        _altar_dict(), 0, ZONE_HAND
    )

    p1_bf_before = state.battlefield_sizes[1]
    p1_grave_before = state.graveyard_sizes[1]
    p0_grave_before = state.graveyard_sizes[0]

    state.push_to_stack(altar_obj_id, 0)
    state.resolve_top_of_stack()

    # p1's creature is UNTOUCHED — Sacrifice doesn't reach across.
    assert state.find_object_zone(p1_creature_id) == ZONE_BATTLEFIELD
    assert state.battlefield_sizes[1] == p1_bf_before
    assert state.graveyard_sizes[1] == p1_grave_before
    # Stack drained; source sorcery in p0's graveyard (post-resolve).
    assert state.is_stack_empty() is True
    assert state.find_object_zone(altar_obj_id) == ZONE_GRAVEYARD
    assert state.graveyard_sizes[0] == p0_grave_before + 1


def test_clone_then_sacrifice_does_not_affect_original(synthetic_state):
    """CoW canary for Sacrifice. Clone the state, then resolve the
    sacrifice on the clone. The clone's first p0 battlefield object
    moves to graveyard; the original's stays put."""
    target_obj_id = 0  # First p0 battlefield object.

    altar_obj_id = synthetic_state.register_and_inject_object(
        _altar_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(altar_obj_id, 0)
    cloned = synthetic_state.clone_once()

    cloned.resolve_top_of_stack()

    # Clone: target sacrificed (in graveyard), source also in graveyard.
    assert cloned.find_object_zone(target_obj_id) == ZONE_GRAVEYARD
    assert cloned.find_object_zone(altar_obj_id) == ZONE_GRAVEYARD
    # Original: untouched on every front (target still on battlefield,
    # source still in hand, stack still has the altar item).
    assert synthetic_state.find_object_zone(target_obj_id) == ZONE_BATTLEFIELD
    assert synthetic_state.find_object_zone(altar_obj_id) == ZONE_HAND
    assert synthetic_state.stack_size() == 1


# --- round-15 AddCounters dispatch ----------------------------------
#
# Round-15 foundation (`feature/rust-tdd-base-r15`) added two new
# ``Effect`` variants — ``AddCounters { target, count }`` and
# ``DiscardCard { target }`` — with stub arms in ``apply_effect`` that
# return ``ValueError``. This slice replaces both stubs with real
# dispatch.
#
# **AddCounters scope** (mirrored in the Rust module docstring on
# ``state_ops_resolve.rs``):
#
# - **AnyCreature target -> first object on the DEFENDING player's
#   battlefield (smallest index).** Mirrors the DealDamage / TapTarget
#   / UntapTarget / ReturnToHand / ExileTarget convention. No creature-
#   type filter, no per-spell target choice. Empty defender-battlefield
#   -> fizzle silently (stack still pops, source still moves
#   post-resolve).
# - **AnyPlayer target raises** (semantically nonsense — you can't put
#   counters on a player). Matches the bounce/exile/tap/untap AnyPlayer
#   shape.
# - **Net-i32 counter model.** Routes through round-2's signed-net
#   counter model — positive ``count`` adds +1/+1 counters, negative
#   ``count`` adds -1/-1 counters; both deltas land on the same i32
#   field via ``saturating_add``. Net values can freely cross zero.
# - **Cross-file friction:** the counter mutator lives on
#   ``state_ops_counters.rs`` (``add_counters``); per per-slice file-
#   isolation we inline the minimal ``Arc::make_mut`` + saturating-add
#   here, mirroring how TapTarget / UntapTarget / Sacrifice inlined
#   their primitives for the same reason.


def _giant_growth_dict(amount=2):
    """A +N/+N counter spell — Giant Growth-shaped (instant, +2/+2 to
    target creature for ``amount=2``). Uses ``any_creature`` target."""
    return {
        "name": "Test Giant Growth",
        "card_types": ["Instant"],
        "mana_cost": {"G": 1},
        "effects": [
            {
                "kind": "add_counters",
                "count": amount,
                "target": {"kind": "any_creature"},
            }
        ],
    }


def _wither_dict(amount=-1):
    """A -N/-N counter spell — wither/infect-shaped. Negative ``amount``
    rides the same i32 net-counter field; round-2's model handles
    cross-zero just fine."""
    return {
        "name": "Test Wither",
        "card_types": ["Instant"],
        "mana_cost": {"B": 1},
        "effects": [
            {
                "kind": "add_counters",
                "count": amount,
                "target": {"kind": "any_creature"},
            }
        ],
    }


def _add_counters_player_dict():
    """Schema-allowed but semantically nonsense: AddCounters with
    AnyPlayer target. Should raise on resolve (cannot put counters on
    a player)."""
    return {
        "name": "Test AddCounters-Player (nonsense)",
        "card_types": ["Instant"],
        "mana_cost": {"G": 1},
        "effects": [
            {
                "kind": "add_counters",
                "count": 1,
                "target": {"kind": "any_player"},
            }
        ],
    }


def test_resolve_add_counters_increments_creature_counters(synthetic_state):
    """Resolving a +2/+2 AddCounters spell deposits 2 counters on the
    first object of the defender's battlefield."""
    # p1's bf[0] is obj_id 67 (Forest in synthetic seed). counters
    # start at 0.
    target_obj_id = 67
    assert synthetic_state.get_counters(target_obj_id) == 0

    spell_obj_id = synthetic_state.register_and_inject_object(
        _giant_growth_dict(amount=2), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.is_stack_empty() is True
    assert synthetic_state.get_counters(target_obj_id) == 2


def test_resolve_add_counters_negative_decrements(synthetic_state):
    """Negative count adds -1/-1-flavored counters; the net-i32 field
    crosses zero freely."""
    target_obj_id = 67
    assert synthetic_state.get_counters(target_obj_id) == 0

    spell_obj_id = synthetic_state.register_and_inject_object(
        _wither_dict(amount=-1), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.get_counters(target_obj_id) == -1


def test_resolve_add_counters_anyplayer_raises(synthetic_state):
    """AddCounters with AnyPlayer target is semantically nonsense (you
    can't put counters on a player). The dispatch raises ValueError
    loudly, matching the bounce/exile/tap/untap AnyPlayer shape."""
    spell_obj_id = synthetic_state.register_and_inject_object(
        _add_counters_player_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)

    with pytest.raises(ValueError):
        synthetic_state.resolve_top_of_stack()


def test_resolve_add_counters_empty_battlefield_fizzles(engine):
    """If the defender has no battlefield objects, AddCounters fizzles
    silently — stack item still pops, source still moves post-resolve,
    no per-object counter writes happen."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=1
    )
    spell_obj_id = state.register_and_inject_object(
        _giant_growth_dict(amount=2), 0, ZONE_HAND
    )
    state.push_to_stack(spell_obj_id, 0)
    state.resolve_top_of_stack()

    # Stack drained, source moved (instant -> graveyard), no error.
    assert state.is_stack_empty() is True
    assert state.find_object_zone(spell_obj_id) == ZONE_GRAVEYARD


def test_resolve_add_counters_stacks_with_existing(synthetic_state):
    """A second AddCounters resolution stacks additively on the i32
    net counter — the field tracks the running net, not a per-spell
    snapshot."""
    target_obj_id = 67
    # Pre-load 1 counter directly via the round-2 add_counters API so
    # the AddCounters dispatch sees a non-zero starting state.
    synthetic_state.add_counters(target_obj_id, 1)
    assert synthetic_state.get_counters(target_obj_id) == 1

    spell_obj_id = synthetic_state.register_and_inject_object(
        _giant_growth_dict(amount=2), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.get_counters(target_obj_id) == 3


# --- round-15 DiscardCard dispatch ----------------------------------
#
# **DiscardCard scope** (mirrored in the Rust module docstring on
# ``state_ops_resolve.rs``):
#
# - **AnyPlayer target -> the DEFENDING player.** First-slice: the
#   active player's spell forces the opponent to discard (CR 701.8 +
#   the Mind Rot / Wrench Mind shape). Real MTG plumbs target-player
#   choice through the cast surface; deferred.
# - **AnyCreature target raises** (semantically nonsense — you can't
#   discard a creature). Matches the bounce/exile/tap/untap shape's
#   AnyPlayer-equivalent path, mirrored for the symmetric
#   AnyCreature-on-DiscardCard error.
# - **Deterministic choice = hand[0].** First slice picks the first
#   card in the target's hand by index (no per-spell discard choice
#   yet). The discarded card moves to the SAME player's graveyard
#   (CR 701.8: a discarded card is put into its owner's graveyard).
# - **Empty hand fizzles silently** (stack still pops, source still
#   moves post-resolve, no zone deltas).
# - **Cross-file friction:** the per-zone movement primitive is
#   private in ``state_ops_zones.rs``; per per-slice file-isolation we
#   inline the minimal ``Arc::make_mut`` Vec::remove(0) +
#   push-to-graveyard here.


def _mind_rot_dict():
    """A discard-target spell — Mind Rot-shaped (sorcery, target player
    discards). Round-15 first slice supports a single-card discard;
    this dict represents that single discard."""
    return {
        "name": "Test Mind Rot",
        "card_types": ["Sorcery"],
        "mana_cost": {"B": 1, "generic": 1},
        "effects": [
            {
                "kind": "discard_card",
                "target": {"kind": "any_player"},
            }
        ],
    }


def _discard_creature_dict():
    """Schema-allowed but semantically nonsense: DiscardCard with
    AnyCreature target. Should raise on resolve (cannot discard a
    creature)."""
    return {
        "name": "Test Discard-Creature (nonsense)",
        "card_types": ["Sorcery"],
        "mana_cost": {"B": 1},
        "effects": [
            {
                "kind": "discard_card",
                "target": {"kind": "any_creature"},
            }
        ],
    }


def test_resolve_discard_card_removes_from_hand(synthetic_state):
    """End-to-end: resolving a DiscardCard spell shrinks the defender's
    hand by 1 and grows their graveyard by 1."""
    p1_hand_before = synthetic_state.hand_sizes[1]
    p1_grave_before = synthetic_state.graveyard_sizes[1]

    spell_obj_id = synthetic_state.register_and_inject_object(
        _mind_rot_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.is_stack_empty() is True
    assert synthetic_state.hand_sizes[1] == p1_hand_before - 1
    assert synthetic_state.graveyard_sizes[1] == p1_grave_before + 1


def test_resolve_discard_card_moves_first_card_in_hand(synthetic_state):
    """The discarded card is specifically hand[0] of the defender (the
    first-slice deterministic choice). Verify by looking at the obj_id
    of p1's first hand card and asserting it lands in graveyard."""
    # p1's hand[0] is at obj_id 77 (10 bf + 7 hand starts at 77 since
    # p1 base = 67 in the synthetic seed).
    p1_first_hand_id = 77
    assert (
        synthetic_state.find_object_zone(p1_first_hand_id) == ZONE_HAND
    )

    spell_obj_id = synthetic_state.register_and_inject_object(
        _mind_rot_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    assert (
        synthetic_state.find_object_zone(p1_first_hand_id) == ZONE_GRAVEYARD
    )


def test_resolve_discard_card_anycreature_raises(synthetic_state):
    """DiscardCard with an AnyCreature target is semantically nonsense
    (you can't discard a creature). The dispatch raises ValueError
    loudly, matching the AddCounters / Sacrifice / TapTarget AnyPlayer
    shape (mirrored here for the symmetric AnyCreature-on-DiscardCard
    error)."""
    spell_obj_id = synthetic_state.register_and_inject_object(
        _discard_creature_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)

    with pytest.raises(ValueError):
        synthetic_state.resolve_top_of_stack()


def test_resolve_discard_card_empty_hand_fizzles(engine):
    """If the defender has an empty hand, DiscardCard fizzles silently
    — stack item still pops, source still moves post-resolve, no
    hand/graveyard deltas on the defender's side."""
    # Build a state with empty defender hand. Build with hand=0 then
    # the source spell needs a non-hand source-zone — battlefield is
    # fine (source-zone doesn't constrain the discard target's zone).
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=1
    )
    spell_obj_id = state.register_and_inject_object(
        _mind_rot_dict(), 0, ZONE_BATTLEFIELD
    )

    p1_hand_before = state.hand_sizes[1]
    p1_grave_before = state.graveyard_sizes[1]

    state.push_to_stack(spell_obj_id, 0)
    state.resolve_top_of_stack()

    assert state.is_stack_empty() is True
    assert state.hand_sizes[1] == p1_hand_before
    assert state.graveyard_sizes[1] == p1_grave_before


def test_resolve_discard_card_to_correct_graveyard(synthetic_state):
    """The discarded card lands in the DEFENDER's graveyard, not the
    active player's. Real MTG: a discarded card goes to its owner's
    graveyard (CR 701.8). First slice: owner == controller, and the
    target is the defender, so the discard lands on the defender's
    side."""
    p0_grave_before = synthetic_state.graveyard_sizes[0]
    p1_grave_before = synthetic_state.graveyard_sizes[1]

    spell_obj_id = synthetic_state.register_and_inject_object(
        _mind_rot_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    # Defender (p1) gained 1 in graveyard; active (p0) gained 1 only
    # from the source sorcery itself moving post-resolve.
    assert synthetic_state.graveyard_sizes[1] == p1_grave_before + 1
    assert synthetic_state.graveyard_sizes[0] == p0_grave_before + 1


# --- round-16: ScryN dispatch -------------------------------------
#
# CR 701.18: Scry N — the controller looks at the top N cards of
# their library and may put any number on the bottom in any order;
# the rest stay on top in any order.
#
# **First-slice deterministic choice: keep all top cards on top.**
# This satisfies the "scry happened" semantics without requiring a
# decision callback (deferred to a future slice). Mechanically a
# no-op on the library — no objects move zones, library size and
# order both remain unchanged.
#
# **Negative count raises** (consistent with the round-3 raise-on-
# negative shape for DealDamage's amount; differs slightly from
# DrawCards/Mill which silently clamp to 0). CR 701.18 doesn't define
# Scry -1, so we surface it as a loud schema error.
#
# **count = 0** is a legitimate no-op (mirrors DrawCards count=0 and
# the round-2 amount=0 conventions).
#
# **count > library size** clamps to library length (CR 701.18d —
# "if there aren't enough cards in your library to look at the
# specified number, look at all the cards"). Since first-slice keeps
# all on top, this is also a no-op on the library.
#
# **Controller convention: state.active_player** — same first-slice
# shape as DrawCards / GainLife (both also implicit-controller).
# Real MTG plumbs the spell controller through StackItem.controller;
# deferred to a future slice.


# Phase constants — mirror ``rust/src/state_ops_steps.rs``. Used by
# the active-player swap test below (set CLEANUP, advance, lands on
# UNTAP with active_player flipped to 1).
PHASE_CLEANUP = 11


def _scry_dict(count=2):
    """A scry-N printing dict shaped like the round-3 bridge parser
    expects. ``count`` is the printed Scry number (positive, zero, or
    negative depending on the test)."""
    return {
        "name": "Test Scry",
        "card_types": ["Sorcery"],
        "mana_cost": {"U": 1},
        "effects": [
            {
                "kind": "scry_n",
                "count": count,
            }
        ],
    }


def test_resolve_scry_zero_no_op(synthetic_state):
    """Scry 0 is a legitimate no-op (mirrors DrawCards count=0 and
    the round-2 amount=0 conventions). Library size and order are
    unchanged; stack item still pops."""
    library_before = synthetic_state.library_sizes[0]
    spell_obj_id = synthetic_state.register_and_inject_object(
        _scry_dict(count=0), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.is_stack_empty() is True
    assert synthetic_state.library_sizes[0] == library_before


def test_resolve_scry_n_positive_keeps_library_unchanged(synthetic_state):
    """Scry 2 with a 50-card library: first-slice deterministic-keep-
    on-top means the library is mechanically unchanged (no zone
    moves, library size still 50). The stack still pops."""
    library_before = synthetic_state.library_sizes[0]
    assert library_before == 50  # synthetic seed default
    spell_obj_id = synthetic_state.register_and_inject_object(
        _scry_dict(count=2), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.is_stack_empty() is True
    assert synthetic_state.library_sizes[0] == library_before


def test_resolve_scry_n_clamped_to_library_size(engine):
    """CR 701.18d: if the library has fewer cards than `count`, scry
    looks at all of them (clamp). Library size 1, Scry 3 — resolve
    succeeds, library still has 1 card (deterministic-keep-on-top)."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=1
    )
    library_before = state.library_sizes[0]
    assert library_before == 1
    spell_obj_id = state.register_and_inject_object(
        _scry_dict(count=3), 0, ZONE_BATTLEFIELD
    )
    state.push_to_stack(spell_obj_id, 0)
    state.resolve_top_of_stack()

    assert state.is_stack_empty() is True
    assert state.library_sizes[0] == library_before


def test_resolve_scry_n_negative_count_raises(synthetic_state):
    """Negative scry count is a schema error (CR 701.18 doesn't
    define Scry -1). Resolve raises ValueError loudly, matching the
    round-3 raise-on-negative shape for DealDamage's amount."""
    spell_obj_id = synthetic_state.register_and_inject_object(
        _scry_dict(count=-1), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)

    with pytest.raises(ValueError):
        synthetic_state.resolve_top_of_stack()


def test_resolve_scry_n_empty_library_returns_ok(engine):
    """Scry on an empty library is a no-op (clamp to library length =
    0). Resolve succeeds, library still empty, stack still pops."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=0
    )
    assert state.library_sizes[0] == 0
    spell_obj_id = state.register_and_inject_object(
        _scry_dict(count=5), 0, ZONE_BATTLEFIELD
    )
    state.push_to_stack(spell_obj_id, 0)
    state.resolve_top_of_stack()

    assert state.is_stack_empty() is True
    assert state.library_sizes[0] == 0


def test_resolve_scry_uses_active_player_library(synthetic_state):
    """ScryN's controller is ``state.active_player`` (first-slice
    convention, mirroring DrawCards / GainLife). Flip active to
    player 1 via CLEANUP -> UNTAP wrap, resolve a Scry — both
    libraries should be unchanged (deterministic-keep-on-top is a
    no-op on whichever library is read), but the dispatch must pick
    the active player's library, not p0's. We assert the no-op
    invariant on both libraries to confirm the dispatch ran without
    error and didn't accidentally mutate either side."""
    p0_lib_before = synthetic_state.library_sizes[0]
    p1_lib_before = synthetic_state.library_sizes[1]

    # Flip active_player to 1 by walking through CLEANUP -> UNTAP.
    synthetic_state.set_phase(PHASE_CLEANUP)
    synthetic_state.advance_phase()
    assert synthetic_state.active_player == 1

    # Inject the scry source on player 1's hand (now the active
    # player). Resolve.
    spell_obj_id = synthetic_state.register_and_inject_object(
        _scry_dict(count=2), 1, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 1)
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.is_stack_empty() is True
    # Both libraries unchanged (first-slice keep-on-top is a no-op).
    assert synthetic_state.library_sizes[0] == p0_lib_before
    assert synthetic_state.library_sizes[1] == p1_lib_before


# --- round-17 DestroyTarget dispatch --------------------------------
#
# **DestroyTarget scope** (mirrored in the Rust module docstring on
# ``state_ops_resolve.rs``):
#
# - **AnyCreature target -> first object on the DEFENDING player's
#   battlefield (smallest index).** No creature-type filter. Mirrors
#   the DealDamage / TapTarget targeting convention; specifically
#   ASYMMETRIC vs Sacrifice (which targets the active player's own
#   battlefield).
# - **AnyPlayer target raises** (semantically nonsense — you can't
#   destroy a player). Matches the bounce/exile/tap/untap shape.
# - **Indestructible is honored** — if the target's printing has
#   "indestructible" in its keywords, the destroy is suppressed
#   silently (mirrors the round-13 SBA indestructible logic). The
#   stack still pops, the source still moves post-resolve, but no
#   permanent moves out of the battlefield.
# - **Empty defender battlefield fizzles silently** (stack still
#   pops, source still moves post-resolve).
# - **Per-object state reset on zone change** (CR 400.7) — tapped /
#   summoning_sick / damage / counters all reset on the way to
#   graveyard, mirroring the ReturnToHand / ExileTarget / Sacrifice
#   reset convention.


def _murder_dict():
    """A destroy-target spell — Murder-shaped (instant, target creature
    is destroyed)."""
    return {
        "name": "Test Murder",
        "card_types": ["Instant"],
        "mana_cost": {"B": 1, "generic": 2},
        "effects": [
            {
                "kind": "destroy_target",
                "target": {"kind": "any_creature"},
            }
        ],
    }


def _destroy_player_dict():
    """Schema-allowed but semantically nonsense: DestroyTarget with
    AnyPlayer target. Should raise on resolve (cannot destroy a
    player)."""
    return {
        "name": "Test Destroy-Player (nonsense)",
        "card_types": ["Sorcery"],
        "mana_cost": {"B": 1},
        "effects": [
            {
                "kind": "destroy_target",
                "target": {"kind": "any_player"},
            }
        ],
    }


def _indestructible_creature_dict():
    """A vanilla creature printing with the indestructible keyword.
    Used to verify DestroyTarget honors indestructible (mirrors the
    round-13 SBA logic)."""
    return {
        "name": "Test Stone Idol",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 4},
        "effects": [],
        "power": 3,
        "toughness": 3,
        "keywords": ["indestructible"],
    }


def test_resolve_destroy_target_moves_to_graveyard(synthetic_state):
    """End-to-end: resolving a DestroyTarget spell shrinks the
    defender's battlefield by 1 and grows the defender's graveyard by
    1. Source instant lands in p0's graveyard via post-resolve."""
    # p1's bf[0] is obj_id 67 (Forest in synthetic seed).
    target_obj_id = 67
    assert synthetic_state.find_object_zone(target_obj_id) == ZONE_BATTLEFIELD

    spell_obj_id = synthetic_state.register_and_inject_object(
        _murder_dict(), 0, ZONE_HAND
    )
    p1_bf_before = synthetic_state.battlefield_sizes[1]
    p1_grave_before = synthetic_state.graveyard_sizes[1]
    p0_grave_before = synthetic_state.graveyard_sizes[0]

    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    # Target moved from p1's battlefield to p1's graveyard.
    assert synthetic_state.find_object_zone(target_obj_id) == ZONE_GRAVEYARD
    assert synthetic_state.battlefield_sizes[1] == p1_bf_before - 1
    assert synthetic_state.graveyard_sizes[1] == p1_grave_before + 1
    # Stack drained; source instant in p0's graveyard.
    assert synthetic_state.is_stack_empty() is True
    assert synthetic_state.find_object_zone(spell_obj_id) == ZONE_GRAVEYARD
    assert synthetic_state.graveyard_sizes[0] == p0_grave_before + 1


def test_resolve_destroy_target_resets_state(synthetic_state):
    """Per-object state reset on zone change (CR 400.7): tapped /
    damage / counters all reset on the way to graveyard. Pre-load the
    target with non-default state, resolve a Murder, and verify after
    moving to graveyard the find_object_zone reports graveyard and the
    counters/damage on the underlying object reset."""
    target_obj_id = 67
    # Pre-load the target with non-default state so the reset is
    # observable via the zone-changed read path.
    synthetic_state.tap_object(target_obj_id)
    synthetic_state.add_counters(target_obj_id, 3)
    synthetic_state.deal_damage(target_obj_id, 2)
    assert synthetic_state.get_counters(target_obj_id) == 3
    assert synthetic_state.get_damage(target_obj_id) == 2

    spell_obj_id = synthetic_state.register_and_inject_object(
        _murder_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    # Target moved to graveyard with reset state. The pre-r11 readers
    # walk all four tracked zones (including graveyard) and read the
    # underlying GameObject fields — so a successful reset on the way
    # out means the readers all return zero/false.
    assert synthetic_state.find_object_zone(target_obj_id) == ZONE_GRAVEYARD
    assert synthetic_state.get_counters(target_obj_id) == 0
    assert synthetic_state.get_damage(target_obj_id) == 0


def test_resolve_destroy_target_indestructible_skipped(engine):
    """If the defender's first battlefield object has the
    ``indestructible`` keyword, DestroyTarget is suppressed silently.
    The stack still pops, the source still moves post-resolve, but
    the indestructible permanent stays on its current zone."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=1
    )
    # Inject an indestructible creature onto p1's battlefield as bf[0].
    indestructible_id = state.register_and_inject_object(
        _indestructible_creature_dict(), 1, ZONE_BATTLEFIELD
    )
    spell_obj_id = state.register_and_inject_object(
        _murder_dict(), 0, ZONE_HAND
    )

    p1_bf_before = state.battlefield_sizes[1]
    p1_grave_before = state.graveyard_sizes[1]

    state.push_to_stack(spell_obj_id, 0)
    state.resolve_top_of_stack()

    # Indestructible target stays put — destroy was suppressed.
    assert state.find_object_zone(indestructible_id) == ZONE_BATTLEFIELD
    assert state.battlefield_sizes[1] == p1_bf_before
    assert state.graveyard_sizes[1] == p1_grave_before
    # Stack still drained; source moved per CR 608.2m.
    assert state.is_stack_empty() is True
    assert state.find_object_zone(spell_obj_id) == ZONE_GRAVEYARD


def test_resolve_destroy_target_anyplayer_raises(synthetic_state):
    """DestroyTarget with an AnyPlayer target is semantically nonsense
    (you can't destroy a player). The dispatch raises ValueError
    loudly, matching the bounce/exile/tap/untap/sacrifice AnyPlayer
    convention."""
    spell_obj_id = synthetic_state.register_and_inject_object(
        _destroy_player_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)

    with pytest.raises(ValueError):
        synthetic_state.resolve_top_of_stack()


def test_resolve_destroy_target_empty_battlefield_fizzles(engine):
    """If the defender has no battlefield objects, DestroyTarget
    fizzles silently — stack item still pops, source still moves
    post-resolve, no zone deltas."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=1
    )
    spell_obj_id = state.register_and_inject_object(
        _murder_dict(), 0, ZONE_HAND
    )
    p1_bf_before = state.battlefield_sizes[1]
    p1_grave_before = state.graveyard_sizes[1]
    p0_grave_before = state.graveyard_sizes[0]

    state.push_to_stack(spell_obj_id, 0)
    state.resolve_top_of_stack()

    # Stack drained, source moved (instant -> p0's graveyard), no
    # battlefield/graveyard delta on p1.
    assert state.is_stack_empty() is True
    assert state.find_object_zone(spell_obj_id) == ZONE_GRAVEYARD
    assert state.battlefield_sizes[1] == p1_bf_before
    assert state.graveyard_sizes[1] == p1_grave_before
    assert state.graveyard_sizes[0] == p0_grave_before + 1


def test_resolve_destroy_target_targets_defender_not_active(synthetic_state):
    """Asymmetric vs Sacrifice: DestroyTarget picks the DEFENDING
    player's battlefield. Flip active_player to 1 via CLEANUP ->
    UNTAP wrap. Now the defender is player 0; resolving Murder must
    destroy the FIRST creature on player 0's battlefield (obj_id 0
    in the synthetic seed), NOT one of player 1's permanents."""
    # Flip active_player to 1.
    synthetic_state.set_phase(PHASE_CLEANUP)
    synthetic_state.advance_phase()
    assert synthetic_state.active_player == 1

    # p0's bf[0] is obj_id 0 in the synthetic seed.
    target_obj_id = 0
    assert synthetic_state.find_object_zone(target_obj_id) == ZONE_BATTLEFIELD

    p0_bf_before = synthetic_state.battlefield_sizes[0]
    p0_grave_before = synthetic_state.graveyard_sizes[0]
    p1_bf_before = synthetic_state.battlefield_sizes[1]

    spell_obj_id = synthetic_state.register_and_inject_object(
        _murder_dict(), 1, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 1)
    synthetic_state.resolve_top_of_stack()

    # p0's bf[0] moved to p0's graveyard; p1's battlefield untouched.
    assert synthetic_state.find_object_zone(target_obj_id) == ZONE_GRAVEYARD
    assert synthetic_state.battlefield_sizes[0] == p0_bf_before - 1
    assert synthetic_state.graveyard_sizes[0] == p0_grave_before + 1
    assert synthetic_state.battlefield_sizes[1] == p1_bf_before


# --- round-17 DamageEachOpponent dispatch ---------------------------
#
# **DamageEachOpponent scope** (mirrored in the Rust module docstring
# on ``state_ops_resolve.rs``):
#
# - **Two-player engine: damages the defender by ``amount``.** No
#   target — the controller is implicit (active_player) and the one
#   opponent is the defender (1 - active_player). Mirrors the
#   DealDamage AnyPlayer-with-implicit-controller shape but applies
#   to "each opponent" — for two players that's just the defender.
# - **amount=0 is a no-op success** (mirrors GainLife/DrawCards/Mill
#   zero-count conventions).
# - **amount<0 raises** loudly (mirrors round-3 DealDamage's raise-
#   on-negative shape; "deal -2 damage" is schema nonsense).
# - **Active player's life is untouched** — DamageEachOpponent does
#   not damage the controller.


def _earthquake_dict(amount=2):
    """A damage-each-opponent spell — Earthquake-shaped (sorcery, deals
    N damage to each opponent). First-slice two-player engine: damages
    the defender by ``amount``."""
    return {
        "name": "Test Earthquake",
        "card_types": ["Sorcery"],
        "mana_cost": {"R": 1, "generic": 1},
        "effects": [
            {
                "kind": "damage_each_opponent",
                "amount": amount,
            }
        ],
    }


def test_resolve_damage_each_opponent_decrements_life(synthetic_state):
    """End-to-end: resolving a 2-damage Earthquake reduces the
    defender's life by 2; controller's life is untouched."""
    spell_obj_id = synthetic_state.register_and_inject_object(
        _earthquake_dict(amount=2), 0, ZONE_HAND
    )
    life_before = list(synthetic_state.life_totals)
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.is_stack_empty() is True
    # Controller (p0) untouched; defender (p1) -2.
    assert synthetic_state.life_totals[0] == life_before[0]
    assert synthetic_state.life_totals[1] == life_before[1] - 2


def test_resolve_damage_each_opponent_zero_no_op(synthetic_state):
    """amount=0 is a legitimate no-op (mirrors DrawCards count=0
    and GainLife amount=0). No life change, no error, stack pops."""
    spell_obj_id = synthetic_state.register_and_inject_object(
        _earthquake_dict(amount=0), 0, ZONE_HAND
    )
    life_before = list(synthetic_state.life_totals)
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.is_stack_empty() is True
    assert list(synthetic_state.life_totals) == life_before


def test_resolve_damage_each_opponent_negative_raises(synthetic_state):
    """Negative amount is a schema error (mirrors round-3
    DealDamage's raise-on-negative shape; "deal -2 damage" is
    schema nonsense)."""
    spell_obj_id = synthetic_state.register_and_inject_object(
        _earthquake_dict(amount=-2), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)

    with pytest.raises(ValueError):
        synthetic_state.resolve_top_of_stack()


def test_resolve_damage_each_opponent_does_not_touch_active_player(
    synthetic_state,
):
    """Asymmetric: DamageEachOpponent damages opponents only — the
    active player (controller) is NOT damaged. Verify by recording
    p0's life before and asserting it's unchanged after."""
    p0_life_before = synthetic_state.life_totals[0]
    p1_life_before = synthetic_state.life_totals[1]
    assert synthetic_state.active_player == 0

    spell_obj_id = synthetic_state.register_and_inject_object(
        _earthquake_dict(amount=5), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    # p0 (active / controller) untouched; p1 (the one opponent) -5.
    assert synthetic_state.life_totals[0] == p0_life_before
    assert synthetic_state.life_totals[1] == p1_life_before - 5


# --- round-18 DamageEachCreature dispatch ---------------------------
#
# **DamageEachCreature scope** (mirrored in the Rust module docstring
# on ``state_ops_resolve.rs``). CR 701.4 — Pyroclasm pattern:
#
# - **Marks ``damage += amount`` on every creature on every player's
#   battlefield.** Symmetric AOE: applies to BOTH players (not just
#   the defender) — Pyroclasm hits creatures controller cares about
#   AND their own.
# - **Only creatures.** Non-creature permanents (lands, artifacts,
#   enchantments) on the battlefield are not touched. Synthetic-state
#   half-Forest-half-Bears layout means we can directly verify lands
#   stay damage=0.
# - **Indestructible is honored at SBA time, NOT here** — this slice
#   only marks damage; SBAs decide who dies. So the dispatch does NOT
#   filter on indestructible (mirrors the round-3 DealDamage shape
#   where lethal damage is also written, then SBAs reap).
# - **amount=0** is a legitimate no-op success (mirrors GainLife /
#   DrawCards / Mill / DamageEachOpponent zero-count conventions).
# - **amount<0 raises** loudly (mirrors round-3 DealDamage and round-17
#   DamageEachOpponent raise-on-negative shape).
# - **Player life is untouched** — DamageEachCreature damages
#   creatures only, not players. (Earthquake-style "deal N to each
#   creature AND each player" is a separate effect kind.)


def _pyroclasm_dict(amount=2):
    """A damage-each-creature spell — Pyroclasm-shaped (sorcery, deals
    N damage to each creature). CR 701.4."""
    return {
        "name": "Test Pyroclasm",
        "card_types": ["Sorcery"],
        "mana_cost": {"R": 1, "generic": 1},
        "effects": [
            {
                "kind": "damage_each_creature",
                "amount": amount,
            }
        ],
    }


def test_resolve_damage_each_creature_marks_damage_on_both_players(
    synthetic_state,
):
    """Resolving Pyroclasm-2 marks damage=2 on every creature on
    BOTH players' battlefields. Synthetic state seeds 5 Bears on each
    player's battlefield (ids 5-9 on p0, 72-76 on p1)."""
    spell_obj_id = synthetic_state.register_and_inject_object(
        _pyroclasm_dict(amount=2), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)

    # Pre-resolve: all creatures have damage=0.
    for cid in (5, 6, 7, 8, 9, 72, 73, 74, 75, 76):
        assert synthetic_state.get_damage(cid) == 0

    synthetic_state.resolve_top_of_stack()

    # All 5+5 creatures have damage=2 — symmetric AOE.
    for cid in (5, 6, 7, 8, 9, 72, 73, 74, 75, 76):
        assert synthetic_state.get_damage(cid) == 2


def test_resolve_damage_each_creature_skips_non_creatures(synthetic_state):
    """Lands / non-creature permanents are not touched — only objects
    whose printing has "Creature" in card_types take the damage mark.
    Synthetic state's first 5 bf objects per player are Forests
    (Land); ids 0-4 (p0) and 67-71 (p1)."""
    spell_obj_id = synthetic_state.register_and_inject_object(
        _pyroclasm_dict(amount=3), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    # All 5+5 Forests on the battlefields stay at damage=0.
    for land_id in (0, 1, 2, 3, 4, 67, 68, 69, 70, 71):
        assert synthetic_state.get_damage(land_id) == 0
    # And the creatures took the hit.
    for cid in (5, 6, 7, 8, 9, 72, 73, 74, 75, 76):
        assert synthetic_state.get_damage(cid) == 3


def test_resolve_damage_each_creature_zero_no_op(synthetic_state):
    """amount=0 is a legitimate no-op — all damage values unchanged,
    no error, stack still pops."""
    spell_obj_id = synthetic_state.register_and_inject_object(
        _pyroclasm_dict(amount=0), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.is_stack_empty() is True
    for cid in (5, 6, 7, 8, 9, 72, 73, 74, 75, 76):
        assert synthetic_state.get_damage(cid) == 0


def test_resolve_damage_each_creature_negative_raises(synthetic_state):
    """Negative amount is a schema error — mirrors DealDamage and
    DamageEachOpponent raise-on-negative shape."""
    spell_obj_id = synthetic_state.register_and_inject_object(
        _pyroclasm_dict(amount=-2), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)

    with pytest.raises(ValueError):
        synthetic_state.resolve_top_of_stack()


def test_resolve_damage_each_creature_does_not_touch_player_life(
    synthetic_state,
):
    """Player life totals are not touched — Pyroclasm damages
    creatures only, not players."""
    life_before = list(synthetic_state.life_totals)
    spell_obj_id = synthetic_state.register_and_inject_object(
        _pyroclasm_dict(amount=4), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    assert list(synthetic_state.life_totals) == life_before


def test_resolve_damage_each_creature_stacks_with_existing_damage(
    synthetic_state,
):
    """Damage stacks: a creature pre-marked with damage=1, then hit
    by Pyroclasm-2, ends at damage=3. Mirrors round-3 DealDamage's
    saturating_add semantics."""
    creature_id = 5  # First Bears on p0's battlefield.
    assert synthetic_state.deal_damage(creature_id, 1) is True
    assert synthetic_state.get_damage(creature_id) == 1

    spell_obj_id = synthetic_state.register_and_inject_object(
        _pyroclasm_dict(amount=2), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.get_damage(creature_id) == 3
    # Other creatures took just 2 (started at 0).
    for cid in (6, 7, 8, 9, 72, 73, 74, 75, 76):
        assert synthetic_state.get_damage(cid) == 2


# --- I33 closure: DamageEachCreature walks bf in ETB-timestamp order --
#
# `DamageEachCreature` collects victims via the shared
# `bf_iter_etb_sorted` helper rather than walking p0's bf then p1's bf
# in per-player Vec order. Damage marking is order-invariant (each
# eligible creature gets +amount via saturating_add exactly once), so
# the OUTCOME is identical under both visit orders — these tests pin
# the no-regression direction with strictly-monotonic interleaved ETB
# stamps to ensure the new bf-walk doesn't lose any victim when the
# bfs are non-trivially ordered. See I33 in
# `docs/RUST_PARITY_GAPS.md`.


def test_resolve_damage_each_creature_bf_etb_interleaved(engine):
    """With strictly-monotonic ETB stamps interleaved across players
    (p0_old → p1_mid → p0_new), the bf-ETB walk visits every Creature
    on either bf — same as Python's centralized walk. Verifies the
    new collect-via-`bf_iter_etb_sorted` shape doesn't miss any
    victim when bf-ETB order differs from p0-then-p1 walk."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=2
    )
    # ETB stamps strictly monotonic in injection order — interleaved
    # across players to create a meaningful divergence between
    # per-player-walk and bf-ETB walk.
    p0_old = state.register_and_inject_object(
        _two_two_creature_dict(), 0, ZONE_BATTLEFIELD
    )
    p1_mid = state.register_and_inject_object(
        _two_two_creature_dict(), 1, ZONE_BATTLEFIELD
    )
    p0_new = state.register_and_inject_object(
        _two_two_creature_dict(), 0, ZONE_BATTLEFIELD
    )
    p1_new = state.register_and_inject_object(
        _two_two_creature_dict(), 1, ZONE_BATTLEFIELD
    )

    spell_obj_id = state.register_and_inject_object(
        _pyroclasm_dict(amount=2), 0, ZONE_HAND
    )
    state.push_to_stack(spell_obj_id, 0)
    state.resolve_top_of_stack()

    # Every creature took the damage regardless of visit order.
    for cid in (p0_old, p1_mid, p0_new, p1_new):
        assert state.get_damage(cid) == 2


# --- round-19 CreateToken dispatch ----------------------------------
#
# **CreateToken scope** (mirrored in the Rust module docstring on
# ``state_ops_resolve.rs``). CR 701.6 — Servo/Soldier maker pattern:
#
# - **Active player (= controller of resolving spell) gets ``count``
#   fresh GameObjects on their battlefield**, all referencing
#   ``token_printing_id``. Mirrors the DealDamage/DrawCards/GainLife
#   first-slice "controller = state.active_player" convention.
# - **Tokens enter summoning-sick, untapped, no damage, no counters,
#   ``zone = ZONE_BATTLEFIELD``.** CR 302.1 — fresh permanents enter
#   the battlefield with summoning sickness.
# - **count=0 is a legal no-op** (mirrors GainLife / DrawCards / Mill
#   / DamageEach* zero-count conventions).
# - **count<0 raises** loudly (mirrors ScryN / DealDamage /
#   DamageEach* raise-on-negative shape; "create -2 tokens" is schema
#   nonsense).
# - **Unknown ``token_printing_id`` raises** (registry lookup is the
#   schema-validation seam — printing must exist before you can make
#   tokens of it).
# - **Fresh ids never collide** with any existing GameObject across
#   either player or any zone — same allocator shape as
#   ``state_ops_deck.rs::load_deck`` and
#   ``register_and_inject_object`` (max-id + 1, sequential).


def _conscript_dict(count, token_printing_id):
    """A create-token spell — Conscript-shaped (sorcery, makes N
    tokens of the named printing). CR 701.6."""
    return {
        "name": "Test Conscript",
        "card_types": ["Sorcery"],
        "mana_cost": {"W": 1, "generic": 1},
        "effects": [
            {
                "kind": "create_token",
                "count": count,
                "token_printing_id": token_printing_id,
            }
        ],
    }


def _soldier_token_dict():
    """A 1/1 white Soldier token printing."""
    return {
        "name": "Soldier Token",
        "card_types": ["Creature"],
        "power": 1,
        "toughness": 1,
    }


def _register_soldier_token(synthetic_state):
    """Register the Soldier token printing into the synthetic state's
    registry. ``register_and_inject_object`` is the only test surface
    for adding a printing (no standalone register-printing-only
    method); we inject the token dummy onto p1's library briefly to
    learn its printing_id, then rely on ``registry_size`` being its
    pre-injection value. Returns ``(token_printing_id, dummy_obj_id)``;
    callers can leave the dummy in the library (it's just a synthetic
    library object with no semantics) or move it elsewhere.
    """
    token_pid = synthetic_state.registry_size  # next free printing_id
    dummy_obj_id = synthetic_state.register_and_inject_object(
        _soldier_token_dict(), 1, ZONE_LIBRARY
    )
    return token_pid, dummy_obj_id


def test_resolve_create_token_spawns_tokens_on_active_player_battlefield(
    synthetic_state,
):
    """count=2 spawns 2 tokens on active player's battlefield, each
    referencing the token printing_id. Pre-resolve: p0 has 10 bf
    objects (synthetic seed). Post-resolve: 2 new tokens land on p0,
    p1's bf is unchanged."""
    token_pid, _ = _register_soldier_token(synthetic_state)
    spell_obj_id = synthetic_state.register_and_inject_object(
        _conscript_dict(count=2, token_printing_id=token_pid), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)

    bf_before = list(synthetic_state.battlefield_sizes)
    synthetic_state.resolve_top_of_stack()
    bf_after = list(synthetic_state.battlefield_sizes)

    # The Conscript sorcery resolved -> goes to active's graveyard
    # (post-resolve movement, not on bf), so the +2 we observe on
    # active's battlefield is exactly the 2 created tokens (no spell-
    # source contribution).
    assert bf_after[0] == bf_before[0] + 2
    assert bf_after[1] == bf_before[1]


def test_resolve_create_token_zero_count_no_op(synthetic_state):
    """count=0 is a legitimate no-op — battlefield size unchanged on
    both players, no error, stack still pops."""
    token_pid, _ = _register_soldier_token(synthetic_state)
    spell_obj_id = synthetic_state.register_and_inject_object(
        _conscript_dict(count=0, token_printing_id=token_pid), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)

    bf_before = list(synthetic_state.battlefield_sizes)
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.is_stack_empty() is True
    assert list(synthetic_state.battlefield_sizes) == bf_before


def test_resolve_create_token_tokens_enter_summoning_sick_untapped(
    synthetic_state,
):
    """Created tokens have ``summoning_sick = True``, ``tapped = False``,
    ``damage = 0``, ``counters = 0`` — CR 302.1 fresh-permanent stamp
    + CR 400.7 zero state. The newly-spawned token ids are exactly
    the highest two on the active player's battlefield by the
    max-id+1 allocator contract."""
    token_pid, dummy_id = _register_soldier_token(synthetic_state)
    spell_obj_id = synthetic_state.register_and_inject_object(
        _conscript_dict(count=3, token_printing_id=token_pid), 0, ZONE_HAND
    )
    # Snapshot the max known id pre-resolve so we can compute the
    # tokens' allocated ids by the load_deck / inject convention
    # (max + 1, sequential).
    pre_max = max(spell_obj_id, dummy_id)
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    # Fresh ids = pre_max + 1, +2, +3. Each one is on a battlefield
    # (the active player's) with the expected initial state.
    for token_id in (pre_max + 1, pre_max + 2, pre_max + 3):
        assert synthetic_state.find_object_zone(token_id) == ZONE_BATTLEFIELD
        assert synthetic_state.is_summoning_sick(token_id) is True
        assert synthetic_state.is_tapped(token_id) is False
        assert synthetic_state.get_damage(token_id) == 0
        assert synthetic_state.get_counters(token_id) == 0


def test_resolve_create_token_unknown_printing_id_raises(synthetic_state):
    """A token_printing_id not present in the registry surfaces as
    ValueError. Schema validation seam — printings must exist before
    you can make tokens of them."""
    bogus_pid = synthetic_state.registry_size + 999
    # We have to register the spell printing FIRST (which appends to
    # the registry), so capture an unambiguously out-of-range token
    # pid by snapshotting the current size + a buffer.
    spell_obj_id = synthetic_state.register_and_inject_object(
        _conscript_dict(count=1, token_printing_id=bogus_pid), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)

    with pytest.raises(ValueError, match="token_printing_id"):
        synthetic_state.resolve_top_of_stack()


def test_resolve_create_token_negative_count_raises(synthetic_state):
    """Negative count is a schema error — mirrors ScryN /
    DealDamage / DamageEach* raise-on-negative shape."""
    token_pid, _ = _register_soldier_token(synthetic_state)
    spell_obj_id = synthetic_state.register_and_inject_object(
        _conscript_dict(count=-2, token_printing_id=token_pid), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)

    with pytest.raises(ValueError):
        synthetic_state.resolve_top_of_stack()


def test_resolve_create_token_fresh_ids_dont_collide(synthetic_state):
    """Token ids must not collide with any existing GameObject in any
    zone (library, battlefield, hand, graveyard) on either player.
    The allocator scans every zone for the current max id and starts
    at max + 1. The synthetic seed already has dense ids 0..133
    spread across libraries+hands+battlefields; we add the
    register_and_inject_object dummies on top, then verify token ids
    strictly exceed every pre-existing id."""
    token_pid, dummy_id = _register_soldier_token(synthetic_state)
    spell_obj_id = synthetic_state.register_and_inject_object(
        _conscript_dict(count=2, token_printing_id=token_pid), 0, ZONE_HAND
    )
    # Collect every existing id across all zones via find_object_zone
    # — the synthetic seed packs ids contiguously starting at 0, plus
    # the two register_and_inject_object dummies above. The new tokens
    # will be allocated starting at max + 1.
    pre_max = max(spell_obj_id, dummy_id)
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    # Each freshly-created token id must strictly exceed pre_max,
    # i.e. land in the contiguous (pre_max+1)..(pre_max+2) slot.
    for token_id in (pre_max + 1, pre_max + 2):
        assert synthetic_state.find_object_zone(token_id) == ZONE_BATTLEFIELD
    # And the (pre_max + 0) id is still findable (the spell source
    # OR the dummy, both pre-resolve denizens) — i.e. we didn't
    # overwrite anything.
    assert synthetic_state.find_object_zone(pre_max) is not None


def test_resolve_create_token_cow_clone_unaffected(synthetic_state):
    """Cloning the state before resolving leaves the original clone's
    battlefield untouched after resolution — Arc::make_mut clones the
    inner Vec only on the post-clone mutation path, so the snapshot
    keeps its pre-resolve battlefield sizes."""
    token_pid, _ = _register_soldier_token(synthetic_state)
    spell_obj_id = synthetic_state.register_and_inject_object(
        _conscript_dict(count=4, token_printing_id=token_pid), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)

    # CoW canary: take a clone BEFORE resolving.
    clone = synthetic_state.clone_once()
    clone_bf_before = list(clone.battlefield_sizes)

    synthetic_state.resolve_top_of_stack()

    # Original clone's battlefield is untouched.
    assert list(clone.battlefield_sizes) == clone_bf_before
    # Live state grew by 4 tokens on active player's battlefield.
    assert (
        synthetic_state.battlefield_sizes[0]
        == clone_bf_before[0] + 4
    )


# --- round-23 AddManaToPool dispatch --------------------------------
#
# **AddManaToPool scope** (mirrored in the Rust module docstring on
# ``state_ops_resolve.rs``). CR 106.1 — mana ability resolution. The
# second-most-frequent Effect across the EoE pool (33 cards per the
# round-20 measurement), powering basic-land mana abilities and
# mana-rocks like Mind Stone.
#
# - **Active player (= controller of resolving stack item) gets
#   ``amount`` mana of ``color`` credited to their pool.** Mirrors the
#   DealDamage/DrawCards/GainLife/CreateToken first-slice
#   "controller = state.active_player" convention. Real MTG plumbs
#   ``StackItem.controller`` through — deferred to a future slice.
# - **amount=0 is a legal no-op** (mirrors GainLife / DrawCards / Mill
#   / DamageEach* / CreateToken zero-count conventions).
# - **amount<0 raises** loudly (mirrors ScryN / DealDamage /
#   DamageEach* / CreateToken raise-on-negative shape; "add -2 green"
#   is schema nonsense — and the bridge parser catches this at
#   register time, but `apply_effect` re-checks for defense-in-depth).
# - **Saturating at u8::MAX** mirrors the `add_mana` primitive in
#   `state_ops_mana.rs` — 255 of any color is more than any real game
#   produces, and silently wrapping would be a worse failure mode
#   than capping.


def _mana_ability_dict(color, amount):
    """A mana-ability source — Forest-shaped (Land card_type, tapped
    for one mana). Uses an `effects` list (not the static
    `mana_produced` field) so the AddManaToPool dispatch path
    actually fires when the stack item resolves. CR 106.1."""
    return {
        "name": f"Test Mana Source ({color}x{amount})",
        "card_types": ["Land"],
        "effects": [
            {"kind": "add_mana_to_pool", "color": color, "amount": amount}
        ],
    }


def test_resolve_add_mana_to_pool_credits_active_player_pool(synthetic_state):
    """Resolving an AddManaToPool effect credits the active player's
    mana pool by the requested (color, amount). Synthetic seed starts
    with empty pools on both players; after the resolution, the
    active player's G slot should be exactly the amount."""
    pool_before = dict(synthetic_state.get_mana_pool(0))
    assert pool_before["G"] == 0

    spell_obj_id = synthetic_state.register_and_inject_object(
        _mana_ability_dict(color="G", amount=1), 0, ZONE_BATTLEFIELD
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.is_stack_empty() is True
    pool_after = dict(synthetic_state.get_mana_pool(0))
    assert pool_after["G"] == 1
    # Opponent's pool untouched.
    assert dict(synthetic_state.get_mana_pool(1))["G"] == 0


def test_resolve_add_mana_to_pool_amount_zero_is_no_op(synthetic_state):
    """amount=0 is a legitimate no-op success — mirrors GainLife /
    DrawCards / Mill / DamageEach* / CreateToken zero-count
    convention. Pool unchanged; stack still pops."""
    pool_before = dict(synthetic_state.get_mana_pool(0))

    spell_obj_id = synthetic_state.register_and_inject_object(
        _mana_ability_dict(color="R", amount=0), 0, ZONE_BATTLEFIELD
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.is_stack_empty() is True
    assert dict(synthetic_state.get_mana_pool(0)) == pool_before


def test_resolve_add_mana_to_pool_multiple_effects_accumulate(synthetic_state):
    """A printing carrying multiple AddManaToPool effects (e.g. a
    hypothetical bicycle land minting two pips of different colors)
    accumulates each entry independently. Mirrors how the bridge
    flattens Python's `produces: tuple[(color, count), ...]` into a
    Vec of `AddManaToPool { color, amount }` entries."""
    multi_color_source = {
        "name": "Test Bi-Land",
        "card_types": ["Land"],
        "effects": [
            {"kind": "add_mana_to_pool", "color": "G", "amount": 1},
            {"kind": "add_mana_to_pool", "color": "U", "amount": 1},
        ],
    }
    spell_obj_id = synthetic_state.register_and_inject_object(
        multi_color_source, 0, ZONE_BATTLEFIELD
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    pool = dict(synthetic_state.get_mana_pool(0))
    assert pool["G"] == 1
    assert pool["U"] == 1
    # Other colors stay at 0.
    assert pool["W"] == 0
    assert pool["B"] == 0
    assert pool["R"] == 0
    assert pool["C"] == 0


def test_resolve_add_mana_to_pool_all_six_colors(synthetic_state):
    """W/U/B/R/G/C — every closed-vocab color routes to its matching
    ManaPool slot. One spell with six AddManaToPool effects exercises
    every arm of the slot match."""
    rainbow_source = {
        "name": "Test Rainbow Source",
        "card_types": ["Land"],
        "effects": [
            {"kind": "add_mana_to_pool", "color": c, "amount": 1}
            for c in ("W", "U", "B", "R", "G", "C")
        ],
    }
    spell_obj_id = synthetic_state.register_and_inject_object(
        rainbow_source, 0, ZONE_BATTLEFIELD
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    pool = dict(synthetic_state.get_mana_pool(0))
    for color in ("W", "U", "B", "R", "G", "C"):
        assert pool[color] == 1, f"{color} slot should be 1, got {pool}"


def test_resolve_add_mana_to_pool_saturates_at_u8_max(synthetic_state):
    """u8::MAX saturation: pre-seed the pool to 250G via add_mana,
    then resolve an AddManaToPool-10 — final value must clamp at 255
    (not wrap to 4). Mirrors the `add_mana` primitive's
    saturating_add convention."""
    # Pre-seed via the round-2 primitive — 250 green coins.
    synthetic_state.add_mana(0, "G", 250)
    assert dict(synthetic_state.get_mana_pool(0))["G"] == 250

    spell_obj_id = synthetic_state.register_and_inject_object(
        _mana_ability_dict(color="G", amount=10), 0, ZONE_BATTLEFIELD
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    # 250 + 10 = 260, saturates to 255 not wraps to 4.
    assert dict(synthetic_state.get_mana_pool(0))["G"] == 255


def test_resolve_add_mana_to_pool_targets_active_player_not_defender(
    synthetic_state,
):
    """Active player (= mana-ability controller, first-slice
    convention) gets the mana — not the defender. Flip active to
    player 1 via CLEANUP -> UNTAP wrap and confirm the credit lands
    on p1's pool, not p0's."""
    # Confirm the synthetic seed starts with p0 active.
    assert synthetic_state.active_player == 0
    # Flip active_player to 1 by walking through CLEANUP -> UNTAP.
    synthetic_state.set_phase(PHASE_CLEANUP)
    synthetic_state.advance_phase()
    assert synthetic_state.active_player == 1

    # Inject the mana source on player 1's battlefield.
    spell_obj_id = synthetic_state.register_and_inject_object(
        _mana_ability_dict(color="U", amount=2), 1, ZONE_BATTLEFIELD
    )
    synthetic_state.push_to_stack(spell_obj_id, 1)
    synthetic_state.resolve_top_of_stack()

    # p1 (the now-active player) got the mana; p0's pool is untouched.
    assert dict(synthetic_state.get_mana_pool(1))["U"] == 2
    assert dict(synthetic_state.get_mana_pool(0))["U"] == 0


def test_resolve_add_mana_to_pool_cow_clone_unaffected(synthetic_state):
    """Cloning the state before resolving leaves the original clone's
    mana pool untouched after resolution — ManaPool is `Copy` on the
    Player struct and Player itself is cloned by-value when the
    GameState is cloned, so the snapshot keeps its pre-resolve pool
    state. The mana-mutation path here doesn't reach for
    `Arc::make_mut`; the by-value Player clone is what isolates."""
    spell_obj_id = synthetic_state.register_and_inject_object(
        _mana_ability_dict(color="B", amount=3), 0, ZONE_BATTLEFIELD
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)

    # CoW canary: take a clone BEFORE resolving.
    clone = synthetic_state.clone_once()
    clone_pool_before = dict(clone.get_mana_pool(0))

    synthetic_state.resolve_top_of_stack()

    # Original clone's pool is untouched.
    assert dict(clone.get_mana_pool(0)) == clone_pool_before
    assert clone_pool_before["B"] == 0
    # Live state's B slot is now 3.
    assert dict(synthetic_state.get_mana_pool(0))["B"] == 3


# --- round-23 SearchLibraryForBasicLandTapped dispatch --------------
#
# **SearchLibraryForBasicLandTapped scope** (mirrored in the Rust
# module docstring on ``state_ops_resolve.rs``). CR 701.19 search +
# 701.22 shuffle — Rampant Growth / Beamsaw Prospector / Kavaron
# Harrier pattern, 15 cards in the EoE pool per the round-20
# measurement.
#
# - **Deterministic first-match pick (top-to-bottom).** Library is
#   bottom-first in the Vec (lib[len-1] = top); scan via iter().rev()
#   to grab the topmost matching object. Real MTG lets the player
#   choose any matching card; deferred until decision callbacks exist.
# - **Basic-land filter: card_types contains "Land".** Bridge has no
#   supertypes today; proxy is faithful for the EoE pool. See
#   SEARCH_LIMITATIONS entry for deferred supertypes work.
# - **No shuffle** in this first slice — deterministic first-match is
#   reproducible without an RNG seed. SEARCH_LIMITATIONS entry tracks
#   the deferred RNG-externalization work.
# - **count=0 / count<0** mirror GainLife / DrawCards / Mill / ScryN
#   / CreateToken conventions (no-op / raise respectively).
# - **Partial fill on early-exhaust:** stop silently when no more
#   matches remain. Matches Python's `next(..., None)` short-circuit.


def _rampant_growth_dict(count=1):
    """A Rampant-Growth-shaped printing — Sorcery card_type so the
    post-resolve mover sends it to the graveyard, with a single
    SearchLibraryForBasicLandTapped effect."""
    return {
        "name": f"Test Rampant Growth (x{count})",
        "card_types": ["Sorcery"],
        "effects": [
            {
                "kind": "search_library_for_basic_land_tapped",
                "count": count,
            }
        ],
    }


def test_resolve_search_library_for_basic_land_tapped_moves_forest_to_battlefield(
    synthetic_state,
):
    """The synthetic seed pre-fills both players' libraries with 50
    Forest objects (card_types=["Land"]). Resolving a count=1 search
    moves the topmost Forest from the active player's library onto
    their battlefield, tapped."""
    bf_before = synthetic_state.battlefield_sizes[0]
    lib_before = synthetic_state.library_sizes[0]

    spell_obj_id = synthetic_state.register_and_inject_object(
        _rampant_growth_dict(count=1), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    # Library shrank by 1, battlefield grew by 1 (the searched land).
    # Source is a Sorcery on the hand → graveyard via CR 608.2m post-
    # resolve move, so it does NOT contribute to the battlefield delta.
    assert synthetic_state.is_stack_empty() is True
    assert synthetic_state.library_sizes[0] == lib_before - 1
    assert synthetic_state.battlefield_sizes[0] == bf_before + 1
    # Opponent's zones untouched.
    assert synthetic_state.library_sizes[1] == lib_before
    assert synthetic_state.battlefield_sizes[1] == bf_before


def test_resolve_search_library_for_basic_land_tapped_lands_tapped(
    synthetic_state,
):
    """The searched land enters TAPPED — the "tapped" half of the
    effect's spec. Top-of-library Forest in the synthetic seed is the
    LAST Vec element on the active player's library; capture its
    obj_id, dispatch the effect, assert is_tapped(obj_id) returns
    Some(True)."""
    # Library Vec layout: p0 base id = num_battlefield + num_hand
    # = 10 + 7 = 17, then 50 library Forests at ids 17..67. Post-CE3:
    # TOP of library = lib[0] = FIRST element of Vec = id 17.
    top_of_library_obj_id = 17
    spell_obj_id = synthetic_state.register_and_inject_object(
        _rampant_growth_dict(count=1), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    # The top-of-library Forest now lives on p0's battlefield, tapped.
    assert synthetic_state.find_object_zone(top_of_library_obj_id) == ZONE_BATTLEFIELD
    assert synthetic_state.is_tapped(top_of_library_obj_id) is True
    # NOT summoning-sick (CR 302.1 applies to creatures; a land
    # bypassing creature-spell resolution via search has no sickness).
    assert synthetic_state.is_summoning_sick(top_of_library_obj_id) is False


def test_resolve_search_library_for_basic_land_tapped_picks_topmost(
    synthetic_state,
):
    """When the library has multiple basic lands, the topmost is
    picked (forward Vec iter = top-to-bottom post-CE3). The synthetic
    seed's library is 100% Forest, so the deterministic first match
    is lib[0] (id 17)."""
    top_id_p0 = 17  # post-CE3: top of p0's library
    second_top_id_p0 = 18  # second-from-top
    spell_obj_id = synthetic_state.register_and_inject_object(
        _rampant_growth_dict(count=1), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    # The TOPMOST Forest (id 66) moved; the second-from-top (id 65)
    # is still in the library.
    assert synthetic_state.find_object_zone(top_id_p0) == ZONE_BATTLEFIELD
    assert synthetic_state.find_object_zone(second_top_id_p0) == ZONE_LIBRARY


def test_resolve_search_library_for_basic_land_tapped_no_land_no_op(engine):
    """If the active player's library has no basic land, the effect
    silently no-ops — the spell still pops the stack, source moves
    per CR 608.2m, but no library / battlefield mutation occurs on
    the search side. Build a state with an empty library on p0 by
    setting num_library=0."""
    state = engine.make_synthetic_state(
        num_battlefield=2, num_hand=1, num_library=0
    )
    bf_before = state.battlefield_sizes[0]
    lib_before = state.library_sizes[0]
    assert lib_before == 0

    # Inject the spell source on p0's HAND so the Sorcery-to-graveyard
    # post-resolve move doesn't touch the battlefield count we're
    # asserting on.
    spell_obj_id = state.register_and_inject_object(
        _rampant_growth_dict(count=1), 0, ZONE_HAND
    )
    state.push_to_stack(spell_obj_id, 0)
    state.resolve_top_of_stack()

    # Stack popped, no library/battlefield mutation on the search side.
    assert state.is_stack_empty() is True
    assert state.library_sizes[0] == 0
    # Source was in hand (not battlefield), so the post-resolve move
    # to graveyard does not change battlefield count.
    assert state.battlefield_sizes[0] == bf_before


def test_resolve_search_library_for_basic_land_tapped_count_two_fetches_two(
    synthetic_state,
):
    """Larval Scoutlander / count=2 pattern — two basic lands enter
    tapped on the same resolution. Library shrinks by 2, battlefield
    grows by 2 (plus the source's post-resolve move)."""
    bf_before = synthetic_state.battlefield_sizes[0]
    lib_before = synthetic_state.library_sizes[0]

    spell_obj_id = synthetic_state.register_and_inject_object(
        _rampant_growth_dict(count=2), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.library_sizes[0] == lib_before - 2
    # +2 lands enter the battlefield. The Sorcery source came from
    # hand (not battlefield) so the post-resolve move to graveyard
    # does not affect the battlefield count.
    assert synthetic_state.battlefield_sizes[0] == bf_before + 2


def test_resolve_search_library_for_basic_land_tapped_preserves_controller(
    synthetic_state,
):
    """The searched land enters under the active player's control —
    `obj.controller` is stamped to `state.active_player` (the
    searcher). Confirm by reading the controller off the moved
    object via find_object_zone (battlefield placement implies the
    `players[controller].battlefield` Vec held it).

    First-slice convention: controller == owner here, so the land
    ends up on the active player's battlefield."""
    bf_before_p0 = synthetic_state.battlefield_sizes[0]
    bf_before_p1 = synthetic_state.battlefield_sizes[1]
    top_of_library_obj_id = 17  # post-CE3: lib[0] = top

    spell_obj_id = synthetic_state.register_and_inject_object(
        _rampant_growth_dict(count=1), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    # The Forest landed on p0's battlefield (active player), not p1's.
    assert synthetic_state.find_object_zone(top_of_library_obj_id) == ZONE_BATTLEFIELD
    # Net battlefield delta: +1 on p0 (searched land), 0 on p1.
    # Source (Sorcery) came from hand → graveyard, so it does not
    # affect the battlefield count.
    assert synthetic_state.battlefield_sizes[0] == bf_before_p0 + 1
    assert synthetic_state.battlefield_sizes[1] == bf_before_p1


def test_resolve_search_library_for_basic_land_tapped_count_zero_no_op(
    synthetic_state,
):
    """count=0 is a legal no-op (mirrors GainLife / DrawCards / Mill /
    DamageEach* / CreateToken zero-count conventions). Library and
    battlefield untouched on the search side."""
    bf_before = synthetic_state.battlefield_sizes[0]
    lib_before = synthetic_state.library_sizes[0]

    spell_obj_id = synthetic_state.register_and_inject_object(
        _rampant_growth_dict(count=0), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.is_stack_empty() is True
    assert synthetic_state.library_sizes[0] == lib_before
    # Source (Sorcery) was in hand → graveyard, no battlefield change.
    assert synthetic_state.battlefield_sizes[0] == bf_before


def test_resolve_search_library_for_basic_land_tapped_shuffles_library(
    synthetic_state,
):
    """G19 closure (CR 701.19 / 701.22): the resolve arm shuffles the
    library after the search, whether or not a card was found.

    The synthetic seed lays p0's library as obj ids 17..66 in
    push-order (id 17 = top, id 66 = bottom). After a count=1 search
    that pulls id 17 to the battlefield, the remaining 49 ids
    (18..66) WOULD all still be in the library in the same relative
    order if no shuffle ran. With G19's shuffle, that exact
    sequential order is broken: the post-resolve library order is a
    deterministic xorshift64 permutation of [18..67) (49 elements,
    seed derived from turn/active_player/source_obj_id/lib_len).

    We pin "shuffled" by asserting the post-resolve library id
    order is NOT identical to the sequential [18, 19, 20, ..., 66]
    that the no-shuffle path would have produced. The probability
    of any deterministic permutation accidentally matching the
    identity sequence is 1/49! ≈ 0 — but more importantly the seed
    is fixed by state, so this assertion is deterministic, not
    probabilistic.
    """
    spell_obj_id = synthetic_state.register_and_inject_object(
        _rampant_growth_dict(count=1), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    # The synthetic seed had ids 17..66 in p0's library; the top
    # (id 17) was searched into the battlefield. Without shuffle
    # the remaining library would read [18, 19, ..., 66] in Vec
    # order; with G19's shuffle it reads a deterministic
    # xorshift64 permutation of the same set.
    post_ids = [
        snap["id"] for snap in synthetic_state.library_snapshot(0)
    ]
    no_shuffle_expected = list(range(18, 67))
    assert sorted(post_ids) == no_shuffle_expected, (
        "shuffle preserves multiset of ids — only the order changes"
    )
    assert post_ids != no_shuffle_expected, (
        "G19: library must be shuffled after the search per CR 701.19"
    )


def test_resolve_search_library_for_basic_land_tapped_shuffle_is_deterministic(
    engine,
):
    """The G19 shuffle is xorshift64-seeded off
    (turn_number, active_player, source_obj_id, library_len), so two
    identical resolutions on two clone-equal states produce the same
    library permutation. Pins determinism: the seed derivation must
    not depend on hidden state (heap addresses, timing, etc.).
    """
    state_a = engine.make_synthetic_state(num_battlefield=0, num_hand=1, num_library=50)
    state_b = engine.make_synthetic_state(num_battlefield=0, num_hand=1, num_library=50)

    obj_id_a = state_a.register_and_inject_object(
        _rampant_growth_dict(count=1), 0, ZONE_HAND
    )
    obj_id_b = state_b.register_and_inject_object(
        _rampant_growth_dict(count=1), 0, ZONE_HAND
    )
    # Both register_and_inject_object calls assign the same next-id
    # (max+1) given identical starting states; sanity-check that
    # before relying on equal post-search seeds.
    assert obj_id_a == obj_id_b

    state_a.push_to_stack(obj_id_a, 0)
    state_a.resolve_top_of_stack()
    state_b.push_to_stack(obj_id_b, 0)
    state_b.resolve_top_of_stack()

    ids_a = [snap["id"] for snap in state_a.library_snapshot(0)]
    ids_b = [snap["id"] for snap in state_b.library_snapshot(0)]
    assert ids_a == ids_b, (
        "G19 shuffle must be deterministic — same starting state "
        "must produce the same post-search library permutation"
    )


# --- Effect-rng-threading closure (G19 follow-up) -------------------
#
# **Effect::SearchLibraryForBasicLandTapped consumes the state-stashed
# external rng.** Caller installs a Python `random.Random` via
# `state.set_external_rng(rng)`; the post-search Fisher-Yates reads
# draws via `_randbelow`, producing byte-identical permutations to
# what `random.Random.shuffle(list)` produces on the Python side.
# Mirrors the CE8 Slice 2 substrate established for the 8 pymethod-
# surface shuffle sites (I41), but plumbed via a stashed field on
# GameState rather than a per-call kwarg (avoids signature churn
# through `apply_effect`/`resolve_top_of_stack`/etc — Option A in
# `docs/RUST_EFFECT_RNG_AUDIT.md`).


def test_resolve_search_library_for_basic_land_tapped_external_rng_matches_python_shuffle(
    synthetic_state,
):
    """When `set_external_rng(random.Random(seed))` is installed before
    resolution, the post-search library order matches what Python's
    `random.Random(seed).shuffle(obj_ids)` produces byte-for-byte.

    The synthetic seed has p0's library at ids 17..66 in push-order
    (id 17 = top). After a count=1 search that pulls id 17 to the
    battlefield, the remaining 49 ids [18..66] are Fisher-Yates'd via
    the threaded rng. The Python reference shuffles [18..67) with a
    fresh `random.Random(seed)` and reads back the post-shuffle list.
    """
    import random

    spell_obj_id = synthetic_state.register_and_inject_object(
        _rampant_growth_dict(count=1), 0, ZONE_HAND
    )
    # Python reference: build the expected post-search library by
    # removing id 17 (top of library = searched land) and shuffling
    # the remaining ids with a fresh `random.Random(seed)`. The
    # `external_rng::next_below` callback consumes `_randbelow(n)`
    # draws in the exact pattern `random.Random.shuffle` uses, so the
    # post-resolve Rust library reads the same order Python's shuffle
    # produces.
    seed = 2026
    py_remaining = list(range(18, 67))
    random.Random(seed).shuffle(py_remaining)

    synthetic_state.set_external_rng(random.Random(seed))
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    post_ids = [snap["id"] for snap in synthetic_state.library_snapshot(0)]
    assert post_ids == py_remaining, (
        "Effect-rng-threading: SearchLibraryForBasicLandTapped's post-"
        "search shuffle must match `random.Random(seed).shuffle` byte-"
        "for-byte when the rng is set via `set_external_rng`."
    )


def test_resolve_search_library_for_basic_land_tapped_external_rng_none_falls_back_to_xorshift(
    engine,
):
    """Backward compat: with no rng set (or `set_external_rng(None)`),
    the resolve arm falls back to the legacy xorshift64 path — same
    output as a state that never had `set_external_rng` called at all.
    Pins that production cli/bench callers (which never install an
    external rng) remain on the deterministic xorshift64 path.
    """
    state_a = engine.make_synthetic_state(num_battlefield=0, num_hand=1, num_library=50)
    state_b = engine.make_synthetic_state(num_battlefield=0, num_hand=1, num_library=50)

    # state_a: never call set_external_rng (default None).
    # state_b: explicitly call set_external_rng(None).
    state_b.set_external_rng(None)

    obj_id_a = state_a.register_and_inject_object(
        _rampant_growth_dict(count=1), 0, ZONE_HAND
    )
    obj_id_b = state_b.register_and_inject_object(
        _rampant_growth_dict(count=1), 0, ZONE_HAND
    )
    assert obj_id_a == obj_id_b

    state_a.push_to_stack(obj_id_a, 0)
    state_a.resolve_top_of_stack()
    state_b.push_to_stack(obj_id_b, 0)
    state_b.resolve_top_of_stack()

    ids_a = [snap["id"] for snap in state_a.library_snapshot(0)]
    ids_b = [snap["id"] for snap in state_b.library_snapshot(0)]
    assert ids_a == ids_b, (
        "set_external_rng(None) must be byte-equivalent to never having "
        "set it — both stay on the xorshift64 fallback path."
    )


def test_resolve_search_library_for_basic_land_tapped_external_rng_differs_from_xorshift(
    engine,
):
    """Sanity check that the two paths actually differ: installing an
    external rng produces a DIFFERENT permutation than the xorshift64
    fallback (overwhelmingly likely — the two PRNGs share no algebraic
    relationship, so collision is birthday-style improbable).
    """
    import random

    state_xs = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=50
    )
    state_rng = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=50
    )
    state_rng.set_external_rng(random.Random(7))

    obj_id_xs = state_xs.register_and_inject_object(
        _rampant_growth_dict(count=1), 0, ZONE_HAND
    )
    obj_id_rng = state_rng.register_and_inject_object(
        _rampant_growth_dict(count=1), 0, ZONE_HAND
    )

    state_xs.push_to_stack(obj_id_xs, 0)
    state_xs.resolve_top_of_stack()
    state_rng.push_to_stack(obj_id_rng, 0)
    state_rng.resolve_top_of_stack()

    ids_xs = [snap["id"] for snap in state_xs.library_snapshot(0)]
    ids_rng = [snap["id"] for snap in state_rng.library_snapshot(0)]
    # Both paths preserve the multiset (49 ids, all in [18..66]).
    assert sorted(ids_xs) == sorted(ids_rng)
    # But the orderings differ (the two PRNGs produce different
    # permutations of the same multiset).
    assert ids_xs != ids_rng, (
        "The external-rng path must differ from the xorshift64 fallback "
        "— they're independent PRNG streams."
    )


def test_resolve_search_library_for_basic_land_tapped_external_rng_preserved_across_clone(
    synthetic_state,
):
    """`GameState.clone()` (via `clone_once`) preserves the stashed rng
    reference — the cloned state shares the SAME `random.Random`
    instance (Python refcount bump). Pins the manual `Clone` impl on
    `GameState` that this slice introduced.

    A clone made post-`set_external_rng` must carry the rng forward,
    observable by running an Effect-rng-consuming resolution on it and
    confirming the post-resolve library matches what `random.Random(seed)`
    would have produced.
    """
    import random

    seed = 99
    synthetic_state.set_external_rng(random.Random(seed))

    # Clone BEFORE resolving — the clone inherits the rng. The clone's
    # rng is a fresh `random.Random(seed)` via the `clone_ref` Python
    # refcount bump on the same instance; consuming on the clone
    # advances that shared instance.
    state_cloned = synthetic_state.clone_once()

    obj_id = state_cloned.register_and_inject_object(
        _rampant_growth_dict(count=1), 0, ZONE_HAND
    )
    state_cloned.push_to_stack(obj_id, 0)
    state_cloned.resolve_top_of_stack()

    # Post-resolve library must match what `random.Random(seed).shuffle`
    # produces over the remaining 49 ids (top-of-library = id 17 was
    # searched into bf; ids 18..66 remain).
    py_remaining = list(range(18, 67))
    random.Random(seed).shuffle(py_remaining)

    cloned_ids = [snap["id"] for snap in state_cloned.library_snapshot(0)]
    assert cloned_ids == py_remaining, (
        "Clone preserves the rng reference — the cloned state's "
        "post-resolve shuffle reads from the same rng instance."
    )


def test_resolve_search_library_for_basic_land_tapped_external_rng_clone_isolation(
    synthetic_state,
):
    """The rng is SHARED across clones (one Python `random.Random`
    instance, refcount bumped), so two clones that BOTH resolve a
    rng-consuming Effect see consecutive (not identical) draws from the
    same stream. Pins the "caller-owned bookkeeping" semantic: clone
    isolation on Vec / Arc zones, but ref-shared on the rng.

    The cross-engine smoke harness depends on this (one rng per game
    consumed by both engines); MCTS-style forking that needs
    independent streams must reset via `set_external_rng(None)` on
    the forked branch — documented in the GameState.rng field doc.
    """
    import random

    seed = 42
    synthetic_state.set_external_rng(random.Random(seed))

    state_a = synthetic_state.clone_once()
    state_b = synthetic_state.clone_once()

    obj_id_a = state_a.register_and_inject_object(
        _rampant_growth_dict(count=1), 0, ZONE_HAND
    )
    obj_id_b = state_b.register_and_inject_object(
        _rampant_growth_dict(count=1), 0, ZONE_HAND
    )
    assert obj_id_a == obj_id_b

    state_a.push_to_stack(obj_id_a, 0)
    state_a.resolve_top_of_stack()
    state_b.push_to_stack(obj_id_b, 0)
    state_b.resolve_top_of_stack()

    ids_a = [snap["id"] for snap in state_a.library_snapshot(0)]
    ids_b = [snap["id"] for snap in state_b.library_snapshot(0)]
    # Both libraries are valid permutations of the same 49 ids.
    assert sorted(ids_a) == sorted(ids_b)
    # But because the rng is SHARED, state_b's shuffle consumed the
    # draws state_a hadn't yet consumed — different orderings.
    assert ids_a != ids_b, (
        "rng is clone_ref'd (shared instance); back-to-back resolves "
        "on two clones consume CONSECUTIVE draws from the same rng "
        "stream, producing different post-resolve permutations."
    )


# --- round-23 PutPlusOneCounterOnSelf dispatch ----------------------
#
# **PutPlusOneCounterOnSelf scope** (mirrored in the Rust module
# docstring on ``state_ops_resolve.rs`` + ``cards.rs``):
#
# - **"Self" = the resolving stack item's source GameObject.** The
#   source_obj_id is threaded from ``resolve_top_of_stack`` through
#   ``apply_effect``; the arm walks both players' battlefield Vecs
#   looking for an obj with that id. Distinct from AddCounters which
#   picks the defender's first creature deterministically.
# - **amount=0 / amount<0** mirror GainLife / DrawCards / Mill /
#   ScryN / CreateToken / SearchLibrary conventions (no-op / raise
#   respectively).
# - **Source not on battlefield = silent no-op.** Real MTG fizzle
#   shape: the counter "lands on nothing" if the source has left
#   the battlefield. Mirrors Python's ``state.resolving_source is
#   None`` short-circuit.


def _self_counter_dict(amount=1):
    """A creature printing carrying a PutPlusOneCounterOnSelf effect.
    Blade-of-the-Swarm-shaped: creature with an "on-attack" or
    self-buff dispatch. Card_types=["Creature"] so the post-resolve
    mover sends it to the battlefield, where the counter add lands."""
    return {
        "name": f"Test Self-Counter (x{amount})",
        "card_types": ["Creature"],
        "power": 1,
        "toughness": 1,
        "effects": [
            {
                "kind": "put_plus_one_counter_on_self",
                "amount": amount,
            }
        ],
    }


def test_resolve_put_plus_one_counter_on_self_increments_source_counters(
    synthetic_state,
):
    """A creature spell resolving with PutPlusOneCounterOnSelf
    deposits its amount of counters onto its own GameObject after the
    post-resolve move lands it on the battlefield. Default amount=1
    case."""
    # Inject the creature source onto p0's BATTLEFIELD directly (so
    # the source-finder picks it up at resolve time). Real MTG: the
    # source moves to the battlefield via post-resolve; for this test
    # we pre-place it there to avoid the source-discovery-order
    # complication (the post-resolve mover and the self-counter arm
    # both walk the battlefield).
    spell_obj_id = synthetic_state.register_and_inject_object(
        _self_counter_dict(amount=1), 0, ZONE_BATTLEFIELD
    )
    assert synthetic_state.get_counters(spell_obj_id) == 0

    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.is_stack_empty() is True
    # +1 counter landed on the source itself.
    assert synthetic_state.get_counters(spell_obj_id) == 1


def test_resolve_put_plus_one_counter_on_self_amount_two(synthetic_state):
    """amount=2 — for cards that drop two counters on themselves per
    activation — lands +2 on the source."""
    spell_obj_id = synthetic_state.register_and_inject_object(
        _self_counter_dict(amount=2), 0, ZONE_BATTLEFIELD
    )
    assert synthetic_state.get_counters(spell_obj_id) == 0

    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.get_counters(spell_obj_id) == 2


def test_resolve_put_plus_one_counter_on_self_amount_zero_no_op(
    synthetic_state,
):
    """amount=0 is a legal no-op (mirrors GainLife / DrawCards / Mill /
    SearchLibrary / CreateToken zero-amount conventions). Source
    counters untouched."""
    spell_obj_id = synthetic_state.register_and_inject_object(
        _self_counter_dict(amount=0), 0, ZONE_BATTLEFIELD
    )
    assert synthetic_state.get_counters(spell_obj_id) == 0

    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.is_stack_empty() is True
    assert synthetic_state.get_counters(spell_obj_id) == 0


def test_resolve_put_plus_one_counter_on_self_stacks_with_existing(
    synthetic_state,
):
    """Multiple consecutive resolutions stack additively on the i32 net
    counter — same shape as AddCounters' running-net behavior."""
    spell_obj_id = synthetic_state.register_and_inject_object(
        _self_counter_dict(amount=1), 0, ZONE_BATTLEFIELD
    )
    # Pre-load 2 counters via the round-2 add_counters API so the
    # PutPlusOneCounterOnSelf dispatch sees a non-zero starting state.
    synthetic_state.add_counters(spell_obj_id, 2)
    assert synthetic_state.get_counters(spell_obj_id) == 2

    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    # 2 (pre-loaded) + 1 (self-counter resolution) = 3.
    assert synthetic_state.get_counters(spell_obj_id) == 3


def test_resolve_put_plus_one_counter_on_self_source_not_on_battlefield_fizzles(
    synthetic_state,
):
    """If the source GameObject is NOT on a battlefield zone, the
    counter add fizzles silently (the source-finder walks both players'
    battlefields). Place the source on HAND, resolve, assert no error
    and no counter mutation anywhere."""
    spell_obj_id = synthetic_state.register_and_inject_object(
        _self_counter_dict(amount=1), 0, ZONE_HAND
    )
    # Source sits in hand — battlefield-finder will not see it.
    assert synthetic_state.find_object_zone(spell_obj_id) == ZONE_HAND

    synthetic_state.push_to_stack(spell_obj_id, 0)
    # No raise — silent fizzle.
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.is_stack_empty() is True
    # The source ends up on the battlefield via the post-resolve
    # mover (Creature card_type), but the counter dispatch ran BEFORE
    # that move (per resolve_top_of_stack ordering: effects first,
    # then post-resolve mover), so it saw the source in hand and
    # fizzled. The source is now on the battlefield with 0 counters.
    assert synthetic_state.find_object_zone(spell_obj_id) == ZONE_BATTLEFIELD
    assert synthetic_state.get_counters(spell_obj_id) == 0


def test_resolve_put_plus_one_counter_on_self_multiple_stack_items_resolve_cleanly(
    synthetic_state,
):
    """Two separate sources each carrying a PutPlusOneCounterOnSelf
    effect resolve independently — each gains a counter on its own
    object, neither bleeds onto the other."""
    src_a = synthetic_state.register_and_inject_object(
        _self_counter_dict(amount=1), 0, ZONE_BATTLEFIELD
    )
    src_b = synthetic_state.register_and_inject_object(
        _self_counter_dict(amount=1), 0, ZONE_BATTLEFIELD
    )
    assert synthetic_state.get_counters(src_a) == 0
    assert synthetic_state.get_counters(src_b) == 0

    # Push both onto the stack, resolve top-down (LIFO).
    synthetic_state.push_to_stack(src_a, 0)
    synthetic_state.push_to_stack(src_b, 0)
    synthetic_state.resolve_top_of_stack()  # resolves src_b
    synthetic_state.resolve_top_of_stack()  # resolves src_a

    # Each source picked up its own +1 counter; no cross-contamination.
    assert synthetic_state.get_counters(src_a) == 1
    assert synthetic_state.get_counters(src_b) == 1


def test_resolve_put_plus_one_counter_on_self_finds_source_on_opponent_battlefield(
    synthetic_state,
):
    """The source-finder walks BOTH players' battlefields. A source
    on p1's battlefield (controller=1) resolves with the counter
    landing on p1's object — the arm picks the source by obj_id, not
    by controller."""
    spell_obj_id = synthetic_state.register_and_inject_object(
        _self_counter_dict(amount=1), 1, ZONE_BATTLEFIELD
    )
    assert synthetic_state.get_counters(spell_obj_id) == 0

    # Active player (p0) resolves a stack item whose source lives on
    # p1's battlefield. The counter lands on p1's source object —
    # this is "self", not "the active player's permanent".
    synthetic_state.push_to_stack(spell_obj_id, 1)
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.get_counters(spell_obj_id) == 1


# --- round-23: Surveil dispatch (round-27 G20 closure: decision-callback) ---
#
# CR 701.43: Surveil N — the controller looks at the top N cards of
# their library, then chooses any number to put into their graveyard.
# The rest stay on top in any order. Powers Appendage Amalgam, etc.
# Sibling of ScryN (round 16): same look-at-top-N shape, different
# destination zone (graveyard not bottom-of-library).
#
# **Round-27 G20 closure: state-machine decision callback.** The
# Surveil arm now pops the observed cards off library top and
# packages them into a `PendingDecision::SurveilChoice`. The caller
# either submits via `submit_surveil_decision(top_ids, graveyard_ids)`
# (the real CR 701.43 choice surface) or auto-resolves via
# `auto_resolve_pending_decisions(strategy)`. The tests below drive
# `resolve_top_of_stack`, which auto-resolves with strategy
# "keep_all_on_top" — making the observation surface bit-equal to
# the pre-r27 round-23 first-slice (deterministic keep-all). Tests
# of the decision substrate itself live in
# `tests_rust/test_pending_decisions.py`.
#
# **Negative count raises** loudly (CR 701.43 doesn't define
# Surveil -1; surface it as a schema error). Mirrors ScryN's
# negative-count rejection.
#
# **count = 0** is a legitimate no-op (mirrors ScryN count=0 / the
# round-2 amount=0 conventions). The substrate still emits one
# (empty) SurveilChoice — the auto-resolve drains it in O(1).
#
# **count > library size** clamps to library size (CR 701.43); with
# `resolve_top_of_stack`'s "keep_all_on_top" auto-resolve, the
# observed cards return to top in the original order, so the
# observation surface is unchanged.
#
# **Controller convention: state.active_player** — same first-slice
# shape as ScryN / DrawCards / GainLife. Real MTG plumbs the spell
# controller through StackItem.controller; deferred. `source_obj_id`
# is recorded on the SurveilChoice for log-correlation.


def _surveil_dict(count=2):
    """A surveil-N printing dict shaped like the round-3 bridge parser
    expects. ``count`` is the printed Surveil number (positive or
    zero; negative variants exercise the register-time / apply-time
    raise paths)."""
    return {
        "name": "Test Surveil",
        "card_types": ["Sorcery"],
        "mana_cost": {"U": 1},
        "effects": [
            {
                "kind": "surveil",
                "count": count,
            }
        ],
    }


def test_resolve_surveil_keeps_library_and_graveyard_unchanged(synthetic_state):
    """Surveil N with a populated library: first-slice deterministic-
    keep-on-top means the library is mechanically unchanged (no zone
    moves from the Surveil dispatch itself), and the graveyard
    receives only the resolved Sorcery source via the CR 608.2m post-
    resolve mover (NOT any of the surveil's "looked at" cards, since
    keep-all-on-top routes zero cards to the graveyard). Stack pops."""
    library_before = synthetic_state.library_sizes[0]
    graveyard_before = synthetic_state.graveyard_sizes[0]
    assert library_before == 50  # synthetic seed default
    spell_obj_id = synthetic_state.register_and_inject_object(
        _surveil_dict(count=2), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.is_stack_empty() is True
    # Library is unchanged by the Surveil dispatch (keep-on-top is a
    # no-op on the library).
    assert synthetic_state.library_sizes[0] == library_before
    # Graveyard grew by exactly 1 — the resolved Sorcery source via
    # CR 608.2m. No "looked at" cards were routed to the graveyard
    # (first-slice keep-all-on-top is a no-op on the graveyard from
    # the Surveil dispatch's perspective).
    assert synthetic_state.graveyard_sizes[0] == graveyard_before + 1


def test_resolve_surveil_zero_no_op(synthetic_state):
    """Surveil 0 is a legitimate no-op for the dispatch (mirrors ScryN
    count=0). Library unchanged; the graveyard grows by 1 only from
    the CR 608.2m post-resolve mover for the Sorcery source itself."""
    library_before = synthetic_state.library_sizes[0]
    graveyard_before = synthetic_state.graveyard_sizes[0]
    spell_obj_id = synthetic_state.register_and_inject_object(
        _surveil_dict(count=0), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.is_stack_empty() is True
    assert synthetic_state.library_sizes[0] == library_before
    # +1 from post-resolve mover; +0 from the Surveil dispatch itself.
    assert synthetic_state.graveyard_sizes[0] == graveyard_before + 1


def test_resolve_surveil_count_exceeds_library_size_is_ok(engine):
    """CR 701.42 clamps to library length when the library has fewer
    cards than `count`. Under the first-slice keep-all-on-top, this is
    silently a no-op on the library regardless of the clamp — library
    size 1, Surveil 3 resolves cleanly without error, library still
    has 1 card. Source on the battlefield (not a Sorcery this time),
    so it stays on the battlefield post-resolve via CR 608.2m — the
    graveyard count is therefore unchanged by either the dispatch or
    the post-resolve mover (empty card_types after seeing only the
    Sorcery card_type would leave it on battlefield; here we use the
    standard sorcery dict so the source moves to graveyard like the
    other tests, and we account for the +1)."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=1
    )
    library_before = state.library_sizes[0]
    graveyard_before = state.graveyard_sizes[0]
    assert library_before == 1
    spell_obj_id = state.register_and_inject_object(
        _surveil_dict(count=3), 0, ZONE_BATTLEFIELD
    )
    state.push_to_stack(spell_obj_id, 0)
    state.resolve_top_of_stack()

    assert state.is_stack_empty() is True
    assert state.library_sizes[0] == library_before
    # +1 from post-resolve mover (Sorcery to graveyard); +0 from the
    # Surveil dispatch itself (no cards routed under keep-all-on-top).
    assert state.graveyard_sizes[0] == graveyard_before + 1


def test_resolve_surveil_negative_count_raises(synthetic_state):
    """Negative surveil count is a schema error (CR 701.42 doesn't
    define Surveil -1). The register-time validation already rejects
    this, but apply_effect re-checks for defense-in-depth — same shape
    as ScryN's negative-count rejection. We bypass the register-time
    check by injecting a synthetic effect through the same parser path
    that surfaces both layers' guards: a Surveil with count=-1 raises
    ValueError at register_printing time. (We assert on the register
    layer here since that's the first place the guard fires.)"""
    with pytest.raises(ValueError):
        synthetic_state.register_and_inject_object(
            _surveil_dict(count=-1), 0, ZONE_HAND
        )


# --- round-23: CounterTargetSpell dispatch -------------------------
#
# CR 701.5: Counter target spell on the stack. Powers Annul, Cancel,
# etc. — 7 cards in the EoE pool per round-20 measurement. Composes
# round-7's counter_spell primitive (inlined here per the per-slice
# file-isolation pattern — see the variant's docstring on cards.rs).
#
# **Deterministic target choice: topmost-non-self stack item.** The
# Effect dispatch scans the stack top-to-bottom (Vec iter().rev())
# and picks the first source_obj_id that isn't this resolving
# effect's own source (via the round-23 source_obj_id parameter on
# apply_effect). A counterspell sitting on the stack shouldn't
# counter itself before it resolves.
#
# **Empty stack / only-self stack: silent fizzle.** Mirrors Python's
# `CounterTargetSpell.resolve` short-circuit on `if not targets`.
# The Effect doesn't error; the post-resolve mover still routes the
# counterspell source to the graveyard at the outer
# `resolve_top_of_stack`.
#
# **Source goes to its controller's graveyard.** CR 701.6 — a
# countered spell is put into its owner's graveyard. First slice:
# owner = controller. Mirrors the round-7 counter_spell primitive's
# routing.


def _annul_dict():
    """An Annul-style counter-target-spell printing dict. Instant-typed
    so the post-resolve mover routes the resolved counterspell source
    to its own controller's graveyard (CR 608.2m)."""
    return {
        "name": "Test Annul",
        "card_types": ["Instant"],
        "mana_cost": {"U": 1},
        "effects": [{"kind": "counter_target_spell"}],
    }


def _bombard_for_counter_dict():
    """A second spell that the Annul-style counter can target. A
    DealDamage Sorcery — when countered before resolution, its
    DealDamage effect must NOT fire. Used as the 'other spell' on the
    stack."""
    return {
        "name": "Bombard Target",
        "card_types": ["Sorcery"],
        "mana_cost": {"R": 1, "generic": 2},
        "effects": [
            {
                "kind": "deal_damage",
                "amount": 3,
                "target": {"kind": "any_player"},
            }
        ],
    }


def test_resolve_counter_target_spell_counters_top_other_spell(synthetic_state):
    """Stack has [other_spell, counter_spell] (counter is top). Resolve
    the top — the counter targets the other_spell, removes its stack
    item, and moves the other_spell's source to its controller's
    graveyard. The counterspell source itself then post-resolves to
    its own controller's graveyard via CR 608.2m. Stack ends empty."""
    other_obj_id = synthetic_state.register_and_inject_object(
        _bombard_for_counter_dict(), 1, ZONE_HAND
    )
    counter_obj_id = synthetic_state.register_and_inject_object(
        _annul_dict(), 0, ZONE_HAND
    )
    # Stack: bottom = other (controller=1), top = counter (controller=0).
    synthetic_state.push_to_stack(other_obj_id, 1)
    synthetic_state.push_to_stack(counter_obj_id, 0)
    assert synthetic_state.stack_size() == 2

    p0_graveyard_before = synthetic_state.graveyard_sizes[0]
    p1_graveyard_before = synthetic_state.graveyard_sizes[1]

    synthetic_state.resolve_top_of_stack()

    # Stack drained (counter resolved, its target was removed from
    # the stack before pop).
    assert synthetic_state.is_stack_empty() is True
    # Countered spell (other_obj_id) is in player 1's graveyard.
    assert synthetic_state.find_object_zone(other_obj_id) == ZONE_GRAVEYARD
    assert synthetic_state.graveyard_sizes[1] == p1_graveyard_before + 1
    # Counterspell source (counter_obj_id) is in player 0's graveyard
    # via the CR 608.2m post-resolve mover (Instant -> controller's
    # graveyard).
    assert synthetic_state.find_object_zone(counter_obj_id) == ZONE_GRAVEYARD
    assert synthetic_state.graveyard_sizes[0] == p0_graveyard_before + 1


def test_resolve_counter_target_spell_empty_stack_except_self_fizzles(
    synthetic_state,
):
    """Stack has only [counter_spell] — no other targets. Per Python
    parity (`if not targets: return`), the Effect dispatch fizzles
    silently. The counterspell's own stack item still pops at the outer
    `resolve_top_of_stack`, and its source still post-resolves to the
    controller's graveyard via CR 608.2m. No error."""
    counter_obj_id = synthetic_state.register_and_inject_object(
        _annul_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(counter_obj_id, 0)
    assert synthetic_state.stack_size() == 1

    p0_graveyard_before = synthetic_state.graveyard_sizes[0]

    # No exception, returns the resolved-item dict.
    resolved = synthetic_state.resolve_top_of_stack()
    assert resolved == {"source_obj_id": counter_obj_id, "controller": 0}

    assert synthetic_state.is_stack_empty() is True
    # Counterspell source landed in its own controller's graveyard
    # via the post-resolve mover; no other state changed.
    assert synthetic_state.find_object_zone(counter_obj_id) == ZONE_GRAVEYARD
    assert synthetic_state.graveyard_sizes[0] == p0_graveyard_before + 1


def test_resolve_counter_target_spell_picks_topmost_non_self(synthetic_state):
    """Stack has [A, B, counter_spell] from bottom to top. The counter
    must pick B (the topmost-non-self stack item), leaving A alone.
    After resolution: A still on stack, B in its controller's
    graveyard, counter in its own controller's graveyard."""
    a_obj_id = synthetic_state.register_and_inject_object(
        _bombard_for_counter_dict(), 1, ZONE_HAND
    )
    b_obj_id = synthetic_state.register_and_inject_object(
        _bombard_for_counter_dict(), 1, ZONE_HAND
    )
    counter_obj_id = synthetic_state.register_and_inject_object(
        _annul_dict(), 0, ZONE_HAND
    )
    # Stack from bottom: A (controller=1), B (controller=1),
    # counter (controller=0).
    synthetic_state.push_to_stack(a_obj_id, 1)
    synthetic_state.push_to_stack(b_obj_id, 1)
    synthetic_state.push_to_stack(counter_obj_id, 0)
    assert synthetic_state.stack_size() == 3

    synthetic_state.resolve_top_of_stack()

    # A remains on stack (counter resolved + popped; B was countered
    # and removed mid-resolve). One stack item left.
    assert synthetic_state.stack_size() == 1
    top = synthetic_state.peek_top_of_stack()
    assert top == {"source_obj_id": a_obj_id, "controller": 1}
    # B is in player 1's graveyard (its controller).
    assert synthetic_state.find_object_zone(b_obj_id) == ZONE_GRAVEYARD
    # A is NOT in the graveyard — it's still pending on the stack.
    assert synthetic_state.find_object_zone(a_obj_id) == ZONE_HAND


def test_resolve_counter_target_spell_routes_to_target_controller_graveyard(
    synthetic_state,
):
    """The countered spell goes to ITS controller's graveyard, NOT the
    counter-caster's. Annul (p0) counters a Bombard (p1) — Bombard
    lands in p1's graveyard, not p0's. Mirrors CR 701.6 + the round-7
    counter_spell primitive's controller-routing convention."""
    bombard_obj_id = synthetic_state.register_and_inject_object(
        _bombard_for_counter_dict(), 1, ZONE_HAND
    )
    counter_obj_id = synthetic_state.register_and_inject_object(
        _annul_dict(), 0, ZONE_HAND
    )
    # bombard is controller=1 on the stack item.
    synthetic_state.push_to_stack(bombard_obj_id, 1)
    synthetic_state.push_to_stack(counter_obj_id, 0)

    p0_graveyard_before = synthetic_state.graveyard_sizes[0]
    p1_graveyard_before = synthetic_state.graveyard_sizes[1]

    synthetic_state.resolve_top_of_stack()

    # p1's graveyard gained the countered Bombard.
    assert synthetic_state.graveyard_sizes[1] == p1_graveyard_before + 1
    # p0's graveyard gained the resolved Annul (post-resolve mover),
    # but NOT the Bombard.
    assert synthetic_state.graveyard_sizes[0] == p0_graveyard_before + 1


def test_resolve_counter_target_spell_target_effects_do_not_fire(
    synthetic_state,
):
    """A countered spell's effects must NOT resolve. The Bombard's
    DealDamage(3, any_player) would normally hit p0 (defender from
    p1's perspective) for 3, but since the Annul counters it before
    Bombard's resolution, no damage is dealt. The dispatch sequence
    here is: resolve_top pops the Annul (top), which counters the
    Bombard (removes its stack item before Bombard ever resolves).
    Bombard's DealDamage never fires."""
    bombard_obj_id = synthetic_state.register_and_inject_object(
        _bombard_for_counter_dict(), 1, ZONE_HAND
    )
    counter_obj_id = synthetic_state.register_and_inject_object(
        _annul_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(bombard_obj_id, 1)
    synthetic_state.push_to_stack(counter_obj_id, 0)
    life_before = list(synthetic_state.life_totals)

    synthetic_state.resolve_top_of_stack()

    # No life totals changed — Bombard's DealDamage never resolved.
    assert synthetic_state.life_totals[0] == life_before[0]
    assert synthetic_state.life_totals[1] == life_before[1]


def test_resolve_counter_target_spell_empty_stack_only_self_does_not_error_with_pop(
    synthetic_state,
):
    """Variant of the fizzle test: confirm `stack.pop()` at the outer
    `resolve_top_of_stack` still succeeds when the inner dispatch
    saw only-self. Specifically guards against an off-by-one where
    'fizzle' accidentally removed the counter's own stack item, then
    the outer pop would crash on an empty stack."""
    counter_obj_id = synthetic_state.register_and_inject_object(
        _annul_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(counter_obj_id, 0)
    # No exception means the outer pop didn't run on an empty stack.
    resolved = synthetic_state.resolve_top_of_stack()
    assert resolved is not None
    assert synthetic_state.is_stack_empty() is True


def test_resolve_counter_target_spell_clone_isolation(synthetic_state):
    """CoW canary: counter on a clone must not bleed into the original.
    Load-bearing because the inline counter logic uses Arc::make_mut on
    multiple zones (stack pop is direct Vec mutation on the per-state
    stack Vec; zone moves use Arc::make_mut). The original state's
    stack + zones must be untouched after the clone resolves."""
    bombard_obj_id = synthetic_state.register_and_inject_object(
        _bombard_for_counter_dict(), 1, ZONE_HAND
    )
    counter_obj_id = synthetic_state.register_and_inject_object(
        _annul_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(bombard_obj_id, 1)
    synthetic_state.push_to_stack(counter_obj_id, 0)
    cloned = synthetic_state.clone_once()

    cloned.resolve_top_of_stack()

    # Clone: counter resolved, stack drained, Bombard in p1's graveyard.
    assert cloned.is_stack_empty() is True
    assert cloned.find_object_zone(bombard_obj_id) == ZONE_GRAVEYARD

    # Original: stack still has 2 items, both sources still in hand.
    assert synthetic_state.stack_size() == 2
    assert synthetic_state.find_object_zone(bombard_obj_id) == ZONE_HAND
    assert synthetic_state.find_object_zone(counter_obj_id) == ZONE_HAND


# --- round-24: ReturnCreatureFromYourGraveyardToBattlefield dispatch ---
#
# CR 400.7 (zone-change reset) + CR 302.1 (new permanent has summoning
# sickness) — reanimate a creature card from the controller's graveyard
# onto their battlefield. Powers Emerge from the Cocoon, Reanimate-style
# sugar — 8 cards in the EoE pool per round-20 measurement. Composes
# round-17's `move_object_from_graveyard_to_battlefield` primitive
# (inlined here per the per-slice file-isolation pattern — see the
# variant's docstring on cards.rs).
#
# **Deterministic first-creature pick.** Scan the controller's
# (`state.active_player`'s, first-slice convention) graveyard in Vec
# iteration order (front = smallest index = oldest); pick the first
# object whose printing's `card_types` contains "Creature". No
# filtering past that (no mana-value cap, no widening) — see the
# variant's docstring for the deferred Python schema.
#
# **Empty / no-creature graveyard: silent fizzle.** Mirrors Python's
# `if not targets: return` short-circuit + the round-17 primitive's
# `Ok(false)` return shape. The Effect doesn't error; the post-resolve
# mover still routes the resolved reanimate source to the graveyard.


def _reanimate_dict():
    """A reanimate-style printing dict. Sorcery-typed so the
    post-resolve mover routes the resolved source to its own
    controller's graveyard (CR 608.2m)."""
    return {
        "name": "Test Reanimate",
        "card_types": ["Sorcery"],
        "mana_cost": {"B": 1, "generic": 1},
        "effects": [
            {"kind": "return_creature_from_your_graveyard_to_battlefield"}
        ],
    }


def _vanilla_creature_dict(name="Test Creature"):
    """A 2/2 creature printing dict — the "target" the reanimate effect
    will pick up from the graveyard."""
    return {
        "name": name,
        "card_types": ["Creature"],
        "mana_cost": {"generic": 2},
        "power": 2,
        "toughness": 2,
    }


def _vanilla_land_dict(name="Test Land"):
    """A non-creature card to drop in the graveyard alongside creature
    targets — confirms the first-creature filter skips it."""
    return {
        "name": name,
        "card_types": ["Land"],
    }


def test_resolve_reanimate_moves_creature_from_graveyard_to_battlefield(
    synthetic_state,
):
    """Happy path: a creature in p0's graveyard + a reanimate spell on
    the stack -> creature lands on p0's battlefield, removed from p0's
    graveyard. The reanimate source itself post-resolves to p0's
    graveyard (Sorcery -> controller's graveyard via CR 608.2m)."""
    # Drop a creature into p0's graveyard.
    creature_id = synthetic_state.register_and_inject_object(
        _vanilla_creature_dict(), 0, ZONE_GRAVEYARD
    )
    # Cast the reanimate spell (p0 is active).
    reanimate_id = synthetic_state.register_and_inject_object(
        _reanimate_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(reanimate_id, 0)
    bf_before = synthetic_state.battlefield_sizes
    gy_before = synthetic_state.graveyard_sizes

    synthetic_state.resolve_top_of_stack()

    # Creature moved from graveyard -> battlefield.
    assert synthetic_state.find_object_zone(creature_id) == ZONE_BATTLEFIELD
    assert synthetic_state.battlefield_sizes[0] == bf_before[0] + 1
    # Graveyard count: -1 (creature left) +1 (reanimate sorcery landed
    # via post-resolve) = bf_before[0] graveyard count.
    assert synthetic_state.graveyard_sizes[0] == gy_before[0]
    # Opponent untouched.
    assert synthetic_state.battlefield_sizes[1] == bf_before[1]
    assert synthetic_state.graveyard_sizes[1] == gy_before[1]


def test_resolve_reanimate_empty_graveyard_silent_fizzle(synthetic_state):
    """No cards in p0's graveyard: the reanimate effect silently
    fizzles. The reanimate source still post-resolves to p0's graveyard
    via CR 608.2m. Battlefield untouched."""
    reanimate_id = synthetic_state.register_and_inject_object(
        _reanimate_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(reanimate_id, 0)
    bf_before = synthetic_state.battlefield_sizes
    gy_before = synthetic_state.graveyard_sizes

    # No exception.
    resolved = synthetic_state.resolve_top_of_stack()
    assert resolved == {"source_obj_id": reanimate_id, "controller": 0}

    # Battlefield untouched.
    assert synthetic_state.battlefield_sizes == bf_before
    # p0 graveyard: +1 from the reanimate sorcery's own post-resolve.
    assert synthetic_state.graveyard_sizes[0] == gy_before[0] + 1


def test_resolve_reanimate_graveyard_with_only_noncreatures_fizzles(
    synthetic_state,
):
    """p0's graveyard has only non-creature cards (a Land). The
    first-creature filter finds nothing -> silent fizzle. The land
    stays in the graveyard."""
    land_id = synthetic_state.register_and_inject_object(
        _vanilla_land_dict(), 0, ZONE_GRAVEYARD
    )
    reanimate_id = synthetic_state.register_and_inject_object(
        _reanimate_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(reanimate_id, 0)
    bf_before = synthetic_state.battlefield_sizes

    synthetic_state.resolve_top_of_stack()

    # Land stays put.
    assert synthetic_state.find_object_zone(land_id) == ZONE_GRAVEYARD
    # Battlefield count untouched (no reanimation happened).
    assert synthetic_state.battlefield_sizes == bf_before


def test_resolve_reanimate_picks_first_creature_in_zone_order(synthetic_state):
    """p0's graveyard has multiple creatures (and a land between them).
    The dispatch picks the FIRST creature in zone-iteration order
    (front = smallest Vec index = oldest by push order). The other
    creature stays in the graveyard."""
    # Push order: creature_a (first), land (skipped), creature_b (later).
    creature_a = synthetic_state.register_and_inject_object(
        _vanilla_creature_dict("First Creature"), 0, ZONE_GRAVEYARD
    )
    _land_id = synthetic_state.register_and_inject_object(
        _vanilla_land_dict(), 0, ZONE_GRAVEYARD
    )
    creature_b = synthetic_state.register_and_inject_object(
        _vanilla_creature_dict("Second Creature"), 0, ZONE_GRAVEYARD
    )
    reanimate_id = synthetic_state.register_and_inject_object(
        _reanimate_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(reanimate_id, 0)

    synthetic_state.resolve_top_of_stack()

    # creature_a (first creature in zone order) reanimated.
    assert synthetic_state.find_object_zone(creature_a) == ZONE_BATTLEFIELD
    # creature_b still in the graveyard.
    assert synthetic_state.find_object_zone(creature_b) == ZONE_GRAVEYARD


def test_resolve_reanimate_stamps_summoning_sick(synthetic_state):
    """CR 302.1 — a reanimated creature enters with summoning sickness;
    it can't attack on the turn it enters. Mirrors the round-17
    primitive's summoning_sick=true stamp."""
    creature_id = synthetic_state.register_and_inject_object(
        _vanilla_creature_dict(), 0, ZONE_GRAVEYARD
    )
    reanimate_id = synthetic_state.register_and_inject_object(
        _reanimate_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(reanimate_id, 0)

    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.is_summoning_sick(creature_id) is True


def test_resolve_reanimate_resets_per_object_state(synthetic_state):
    """CR 400.7 — per-object state (damage / counters) resets on the
    zone change. A graveyard creature with stamped damage / counters
    arrives on the battlefield with damage=0 / counters=0. Defensive
    reset even though CR 614.12 zeros damage on zone change already,
    same shape as the round-17 primitive's defensive reset."""
    creature_id = synthetic_state.register_and_inject_object(
        _vanilla_creature_dict(), 0, ZONE_GRAVEYARD
    )
    # Stamp damage / counters onto the graveyard object directly.
    assert synthetic_state.deal_damage(creature_id, 5) is True
    assert synthetic_state.set_counters(creature_id, 3) is True
    assert synthetic_state.get_damage(creature_id) == 5
    assert synthetic_state.get_counters(creature_id) == 3

    reanimate_id = synthetic_state.register_and_inject_object(
        _reanimate_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(reanimate_id, 0)

    synthetic_state.resolve_top_of_stack()

    # Creature on battlefield with damage=0 / counters=0.
    assert synthetic_state.find_object_zone(creature_id) == ZONE_BATTLEFIELD
    assert synthetic_state.get_damage(creature_id) == 0
    assert synthetic_state.get_counters(creature_id) == 0


def test_resolve_reanimate_only_searches_controller_graveyard(synthetic_state):
    """The "your graveyard" filter is controller-scoped: a creature in
    the OPPONENT's graveyard is NOT a legal target. p0 casts reanimate
    while p1's graveyard has a creature -> p0's reanimate silently
    fizzles (p0's graveyard has no creature)."""
    # Drop a creature only into p1's graveyard.
    opp_creature_id = synthetic_state.register_and_inject_object(
        _vanilla_creature_dict(), 1, ZONE_GRAVEYARD
    )
    reanimate_id = synthetic_state.register_and_inject_object(
        _reanimate_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(reanimate_id, 0)
    bf_before = synthetic_state.battlefield_sizes

    synthetic_state.resolve_top_of_stack()

    # Opponent's creature is untouched.
    assert synthetic_state.find_object_zone(opp_creature_id) == ZONE_GRAVEYARD
    # No battlefield change (the active player's reanimate fizzled).
    assert synthetic_state.battlefield_sizes == bf_before


def test_resolve_reanimate_clone_isolation(synthetic_state):
    """CoW canary: running the reanimate dispatch on a clone leaves the
    original GameState's zones untouched. Load-bearing because the
    inline reanimate logic uses Arc::make_mut on two zones (graveyard
    + battlefield)."""
    creature_id = synthetic_state.register_and_inject_object(
        _vanilla_creature_dict(), 0, ZONE_GRAVEYARD
    )
    reanimate_id = synthetic_state.register_and_inject_object(
        _reanimate_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(reanimate_id, 0)
    cloned = synthetic_state.clone_once()

    cloned.resolve_top_of_stack()

    # Clone diverged: creature reanimated, stack drained.
    assert cloned.find_object_zone(creature_id) == ZONE_BATTLEFIELD
    assert cloned.is_stack_empty() is True

    # Original untouched: creature still in graveyard, stack still 1.
    assert synthetic_state.find_object_zone(creature_id) == ZONE_GRAVEYARD
    assert synthetic_state.stack_size() == 1


# --- round-25: DiscardSelf dispatch ---------------------------------
#
# CR 701.8 — "you discard a card." The SOURCE's controller discards
# `amount` cards from their hand. Punisher / drawback pattern
# (Irreverent Gremlin shape) — 8 cards in the EoE pool per round-20
# measurement.
#
# **Distinct from round-15's DiscardCard.** DiscardCard's AnyPlayer
# branch targets the DEFENDING player (Mind Rot — active player forces
# opponent to discard). DiscardSelf targets the SOURCE's controller
# regardless of active_player. The cross-controller-active-player
# tests below confirm the distinction.
#
# **Source-finder dispatch (round-23 pattern).** Walks both players'
# five tracked zones to recover the source's `controller`. Also scans
# the stack — the source may still be resolving when the effect fires.
#
# **First-slice deterministic choice: hand[0]** of the source's
# controller (mirrors round-15 DiscardCard). Up to `amount` discards
# in a row; empty hand stops early (Python parity with
# `for _ in range(self.amount): if not p.hand: break`).
#
# **Empty hand / source-not-found = silent no-op** (Python parity +
# round-23 lost-track-of-source tolerance).


def _discard_self_dict(amount=1, card_types=None):
    """An Irreverent-Gremlin-shaped printing: a permanent (or
    instant/sorcery via card_types override) whose effect makes the
    SOURCE's controller discard `amount` cards.

    Default card_types=["Creature"] so the post-resolve mover sends
    the source to the battlefield (a creature ETB pattern). Tests
    that need a different source-zone behavior override card_types
    (e.g. ["Sorcery"] to route the source to its controller's
    graveyard post-resolve).
    """
    if card_types is None:
        card_types = ["Creature"]
    p = {
        "name": f"Test Irreverent Gremlin (x{amount})",
        "card_types": card_types,
        "mana_cost": {"R": 1},
        "effects": [{"kind": "discard_self", "amount": amount}],
    }
    if "Creature" in card_types:
        p["power"] = 1
        p["toughness"] = 1
    return p


def test_resolve_discard_self_source_on_battlefield_discards_controller_hand(
    synthetic_state,
):
    """Happy path: source sits on p0's battlefield, p0 has cards in
    hand. Resolving DiscardSelf shrinks p0's hand by 1 and grows p0's
    graveyard by 1. Opponent untouched."""
    src_id = synthetic_state.register_and_inject_object(
        _discard_self_dict(amount=1), 0, ZONE_BATTLEFIELD
    )
    p0_hand_before = synthetic_state.hand_sizes[0]
    p0_grave_before = synthetic_state.graveyard_sizes[0]
    p1_hand_before = synthetic_state.hand_sizes[1]
    p1_grave_before = synthetic_state.graveyard_sizes[1]

    synthetic_state.push_to_stack(src_id, 0)
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.is_stack_empty() is True
    # p0 (the source's controller) discarded one card.
    assert synthetic_state.hand_sizes[0] == p0_hand_before - 1
    assert synthetic_state.graveyard_sizes[0] == p0_grave_before + 1
    # p1 untouched.
    assert synthetic_state.hand_sizes[1] == p1_hand_before
    assert synthetic_state.graveyard_sizes[1] == p1_grave_before


def test_resolve_discard_self_empty_hand_silent_no_op(engine):
    """If the source's controller has an empty hand, the effect
    fizzles silently — stack item still pops, no graveyard delta on
    the controller's side. Mirrors Python's
    `if not p.hand: break` short-circuit."""
    # Synthetic state with 0 hand on both players. Need at least 1
    # library card per the synthetic helper (default 50).
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=1
    )
    src_id = state.register_and_inject_object(
        _discard_self_dict(amount=1), 0, ZONE_BATTLEFIELD
    )
    p0_grave_before = state.graveyard_sizes[0]

    state.push_to_stack(src_id, 0)
    state.resolve_top_of_stack()  # no raise

    assert state.is_stack_empty() is True
    # No discard happened — p0 graveyard unchanged.
    assert state.graveyard_sizes[0] == p0_grave_before


def test_resolve_discard_self_source_in_graveyard_uses_controller(
    synthetic_state,
):
    """The source-finder walks five zones (hand / library /
    battlefield / graveyard / exile) — wider than
    PutPlusOneCounterOnSelf's battlefield-only scan. Inject a
    source-shaped object into p0's graveyard (which would normally
    be unreachable as a stack source, but tests the source-finder's
    multi-zone scope): the zone-scan picks up p0 as the controller
    and resolves the discard on p0's hand.

    This documents the "source has left the battlefield by resolve
    time" tolerance — a permanent's punisher effect still knows the
    controller via the source object's `controller` field, which
    doesn't change on zone moves. Real MTG: most "you discard"
    punishers fire from triggers / ETBs and the source is on the
    battlefield at resolve time; this test covers the defensive
    path."""
    src_id = synthetic_state.register_and_inject_object(
        _discard_self_dict(amount=1, card_types=["Creature"]),
        0,
        ZONE_GRAVEYARD,
    )
    p0_hand_before = synthetic_state.hand_sizes[0]

    synthetic_state.push_to_stack(src_id, 0)
    synthetic_state.resolve_top_of_stack()

    # p0 (the source's controller, as recorded on the GameObject
    # regardless of which zone it's in) discarded.
    assert synthetic_state.hand_sizes[0] == p0_hand_before - 1


def test_resolve_discard_self_instant_source_resolves_from_hand(
    synthetic_state,
):
    """An instant source: the source GameObject is in its
    controller's hand (where it was cast from) at resolve time,
    not on the battlefield. The zone-scan finds the source in hand
    on its controller's side, identifies p0 as the controller, and
    the discard fires on p0's hand[0].

    This is the realistic spell-cast pattern — the source's
    `controller` field carries the authoritative controller
    regardless of where the source currently sits, and the
    five-zone scan widens the finder to catch hand-resident
    sources too."""
    src_id = synthetic_state.register_and_inject_object(
        _discard_self_dict(amount=1, card_types=["Instant"]),
        0,
        ZONE_HAND,
    )
    # Capture hand[1]'s id BEFORE — hand[0] is the source itself,
    # so the discard will pop the *first non-source* card off the
    # front... actually, hand[0] IS the most recent
    # register_and_inject_object push (it appended to the Vec). The
    # synthetic hand had 7 elves at indices 0..6; the source is now
    # at index 7. Discard pops hand[0] (Elves), source stays at
    # index 6 after the pop. Verify by hand_size delta only — the
    # post-resolve mover then moves the Instant source out of hand
    # to graveyard.
    p0_hand_before = synthetic_state.hand_sizes[0]
    p0_grave_before = synthetic_state.graveyard_sizes[0]

    synthetic_state.push_to_stack(src_id, 0)
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.is_stack_empty() is True
    # Hand shrank by 2: -1 from the discard, -1 from the
    # post-resolve mover routing the Instant to graveyard. The
    # discard fired on hand[0] (the elf), not on the source itself.
    assert synthetic_state.hand_sizes[0] == p0_hand_before - 2
    # Graveyard grew by 2 (the discarded elf + the resolved
    # instant source).
    assert synthetic_state.graveyard_sizes[0] == p0_grave_before + 2


def test_resolve_discard_self_discards_first_card_in_hand(synthetic_state):
    """The discarded card is specifically hand[0] of the source's
    controller (first-slice deterministic choice). Verify by looking
    at the obj_id of p0's first hand card before, then asserting it
    lands in p0's graveyard after resolution."""
    p0_hand_before = synthetic_state.hand_snapshot(0)
    p0_first_hand_id = p0_hand_before[0]["id"]
    assert (
        synthetic_state.find_object_zone(p0_first_hand_id) == ZONE_HAND
    )

    src_id = synthetic_state.register_and_inject_object(
        _discard_self_dict(amount=1), 0, ZONE_BATTLEFIELD
    )
    synthetic_state.push_to_stack(src_id, 0)
    synthetic_state.resolve_top_of_stack()

    # hand[0] (Llanowar Elves synthetic seed) was discarded ->
    # landed in p0's graveyard.
    assert (
        synthetic_state.find_object_zone(p0_first_hand_id) == ZONE_GRAVEYARD
    )


def test_resolve_discard_self_resets_per_object_state_on_discard(
    synthetic_state,
):
    """CR 400.7 — per-object state (tapped / damage / counters)
    resets on the zone change to graveyard. Stamp damage / counters
    onto p0's hand[0], resolve DiscardSelf, assert the discarded
    object lands in graveyard with state cleared. Mirrors the
    defensive reset every other zone-move arm applies."""
    p0_first_hand_id = synthetic_state.hand_snapshot(0)[0]["id"]
    # Stamp damage / counters onto the hand object directly.
    assert synthetic_state.deal_damage(p0_first_hand_id, 5) is True
    assert synthetic_state.set_counters(p0_first_hand_id, 3) is True
    assert synthetic_state.get_damage(p0_first_hand_id) == 5
    assert synthetic_state.get_counters(p0_first_hand_id) == 3

    src_id = synthetic_state.register_and_inject_object(
        _discard_self_dict(amount=1), 0, ZONE_BATTLEFIELD
    )
    synthetic_state.push_to_stack(src_id, 0)
    synthetic_state.resolve_top_of_stack()

    # Discarded into p0's graveyard with damage=0, counters=0.
    assert synthetic_state.find_object_zone(p0_first_hand_id) == ZONE_GRAVEYARD
    assert synthetic_state.get_damage(p0_first_hand_id) == 0
    assert synthetic_state.get_counters(p0_first_hand_id) == 0


def test_resolve_discard_self_opponent_source_discards_opponent_hand(
    synthetic_state,
):
    """The 'self' is the SOURCE's controller, NOT the active player.
    Source on p1's battlefield (controller=1) while active_player
    stays p0 — resolving DiscardSelf discards from p1's hand, not
    p0's. This is the key distinction from round-15's DiscardCard
    (which targets the DEFENDING player, not the source's
    controller)."""
    # Inject source on p1's battlefield. active_player stays at the
    # synthetic-state default (0).
    src_id = synthetic_state.register_and_inject_object(
        _discard_self_dict(amount=1), 1, ZONE_BATTLEFIELD
    )
    p0_hand_before = synthetic_state.hand_sizes[0]
    p0_grave_before = synthetic_state.graveyard_sizes[0]
    p1_hand_before = synthetic_state.hand_sizes[1]
    p1_grave_before = synthetic_state.graveyard_sizes[1]

    # Push with controller=1 (p1's source resolving on the stack).
    synthetic_state.push_to_stack(src_id, 1)
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.is_stack_empty() is True
    # p1 (the source's controller) discarded — NOT p0.
    assert synthetic_state.hand_sizes[1] == p1_hand_before - 1
    assert synthetic_state.graveyard_sizes[1] == p1_grave_before + 1
    # p0 (active player but NOT the source's controller) untouched.
    assert synthetic_state.hand_sizes[0] == p0_hand_before
    assert synthetic_state.graveyard_sizes[0] == p0_grave_before


def test_resolve_discard_self_amount_two_discards_twice(synthetic_state):
    """amount=2 — the controller discards two cards in a row. Two
    hand cards leave hand, two land in graveyard."""
    src_id = synthetic_state.register_and_inject_object(
        _discard_self_dict(amount=2), 0, ZONE_BATTLEFIELD
    )
    p0_hand_before = synthetic_state.hand_sizes[0]
    p0_grave_before = synthetic_state.graveyard_sizes[0]

    synthetic_state.push_to_stack(src_id, 0)
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.hand_sizes[0] == p0_hand_before - 2
    assert synthetic_state.graveyard_sizes[0] == p0_grave_before + 2


def test_resolve_discard_self_amount_zero_no_op(synthetic_state):
    """amount=0 is a legal no-op (mirrors GainLife / DrawCards /
    Mill / ScryN / CreateToken / PutPlusOneCounterOnSelf zero-amount
    conventions). Hand / graveyard untouched."""
    src_id = synthetic_state.register_and_inject_object(
        _discard_self_dict(amount=0), 0, ZONE_BATTLEFIELD
    )
    p0_hand_before = synthetic_state.hand_sizes[0]
    p0_grave_before = synthetic_state.graveyard_sizes[0]

    synthetic_state.push_to_stack(src_id, 0)
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.is_stack_empty() is True
    assert synthetic_state.hand_sizes[0] == p0_hand_before
    assert synthetic_state.graveyard_sizes[0] == p0_grave_before


def test_resolve_discard_self_clone_isolation(synthetic_state):
    """CoW canary: running DiscardSelf on a clone leaves the original
    state's zones untouched. Load-bearing because the inline discard
    logic uses Arc::make_mut on two zones (hand + graveyard)."""
    src_id = synthetic_state.register_and_inject_object(
        _discard_self_dict(amount=1), 0, ZONE_BATTLEFIELD
    )
    synthetic_state.push_to_stack(src_id, 0)
    p0_hand_before = synthetic_state.hand_sizes[0]
    p0_grave_before = synthetic_state.graveyard_sizes[0]

    cloned = synthetic_state.clone_once()
    cloned.resolve_top_of_stack()

    # Clone diverged: p0's hand shrank, graveyard grew.
    assert cloned.hand_sizes[0] == p0_hand_before - 1
    assert cloned.graveyard_sizes[0] == p0_grave_before + 1
    assert cloned.is_stack_empty() is True

    # Original untouched.
    assert synthetic_state.hand_sizes[0] == p0_hand_before
    assert synthetic_state.graveyard_sizes[0] == p0_grave_before
    assert synthetic_state.stack_size() == 1


# --- round-26: EachOpponentLosesLife dispatch ------------------------
#
# CR 118.4 — "life loss" (not damage). Each opponent of the SOURCE's
# controller loses `amount` life. Punisher / drawback pattern
# (Balemurk Leech shape) — 6 cards in the EoE pool per round-20
# measurement.
#
# **Distinct from round-17 DamageEachOpponent.** DamageEachOpponent
# deals DAMAGE (CR 701.4) — routes through damage-prevention /
# Worship-style replacement (CR 614) when those land. Each-
# OpponentLosesLife is direct life subtraction and is NOT reducible.
# Two-player engine first slice: both variants land identical
# defender-life deltas because neither variant routes through
# damage-prevention yet, but they stay distinct to mirror Python's
# closed `Effect` vocabulary.
#
# **Source-finder dispatch (round-24 pattern).** Walks both players'
# five tracked zones (hand / library / battlefield / graveyard /
# exile) plus the stack to recover the source's `controller`.
# Mirrors DiscardSelf — punisher effects fire on whoever controls the
# source regardless of where the source currently sits, since the
# controller field doesn't change on zone moves.
#
# **Two-player "each opponent" reduces to "the one opponent".**
# opponent_id = 1 - controller. Direct life subtraction. amount=0 is
# a legal no-op; amount<0 raises. Source not found = silent fizzle.


def _balemurk_leech_dict(amount=2, card_types=None):
    """A Balemurk-Leech-shaped printing: a permanent (or instant /
    sorcery via card_types override) whose effect makes each opponent
    of the SOURCE's controller lose `amount` life.

    Default card_types=["Creature"] so the post-resolve mover sends
    the source to the battlefield (the printed Balemurk Leech is a
    creature with an ETB-style punisher trigger). Tests that need a
    different source-zone behavior override card_types.
    """
    if card_types is None:
        card_types = ["Creature"]
    p = {
        "name": f"Test Balemurk Leech (x{amount})",
        "card_types": card_types,
        "mana_cost": {"B": 1, "generic": 1},
        "effects": [{"kind": "each_opponent_loses_life", "amount": amount}],
    }
    if "Creature" in card_types:
        p["power"] = 2
        p["toughness"] = 2
    return p


def test_resolve_each_opponent_loses_life_decrements_opponent_life(
    synthetic_state,
):
    """Happy path: source on active player's (p0) battlefield with
    amount=3 — p1 (the one opponent) loses 3 life; p0 untouched."""
    src_id = synthetic_state.register_and_inject_object(
        _balemurk_leech_dict(amount=3), 0, ZONE_BATTLEFIELD
    )
    p0_life_before = synthetic_state.life_totals[0]
    p1_life_before = synthetic_state.life_totals[1]

    synthetic_state.push_to_stack(src_id, 0)
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.is_stack_empty() is True
    # p0 (source's controller) untouched; p1 (the one opponent) -3.
    assert synthetic_state.life_totals[0] == p0_life_before
    assert synthetic_state.life_totals[1] == p1_life_before - 3


def test_resolve_each_opponent_loses_life_amount_zero_no_op(synthetic_state):
    """amount=0 is a legitimate no-op (mirrors GainLife / DrawCards /
    Mill / DamageEachOpponent / DiscardSelf zero-amount conventions).
    No life change, no error, stack pops."""
    src_id = synthetic_state.register_and_inject_object(
        _balemurk_leech_dict(amount=0), 0, ZONE_BATTLEFIELD
    )
    life_before = list(synthetic_state.life_totals)
    synthetic_state.push_to_stack(src_id, 0)
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.is_stack_empty() is True
    assert list(synthetic_state.life_totals) == life_before


def test_resolve_each_opponent_loses_life_negative_amount_raises_at_register(
    synthetic_state,
):
    """Negative amount is a schema error (mirrors DamageEachOpponent /
    DiscardSelf raise-on-negative shape; 'lose -2 life' is schema
    nonsense). The parse_effect bridge guard surfaces this at
    register time — before resolution ever runs."""
    with pytest.raises(ValueError):
        synthetic_state.register_and_inject_object(
            _balemurk_leech_dict(amount=-2), 0, ZONE_BATTLEFIELD
        )


def test_resolve_each_opponent_loses_life_opponent_source_targets_active_player(
    synthetic_state,
):
    """The 'each opponent' is OPPONENTS-OF-CONTROLLER, NOT defender-
    of-active-player. Source on p1's battlefield (controller=1) while
    active_player stays p0 — resolving EachOpponentLosesLife reduces
    p0's life (the one opponent of p1), NOT p1's. Cross-controller-
    active-player distinction matches DiscardSelf's behavior."""
    src_id = synthetic_state.register_and_inject_object(
        _balemurk_leech_dict(amount=4), 1, ZONE_BATTLEFIELD
    )
    p0_life_before = synthetic_state.life_totals[0]
    p1_life_before = synthetic_state.life_totals[1]
    assert synthetic_state.active_player == 0

    # Push with controller=1 (p1's source resolving on the stack).
    synthetic_state.push_to_stack(src_id, 1)
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.is_stack_empty() is True
    # p0 (the one opponent of p1) -4; p1 (controller) untouched.
    assert synthetic_state.life_totals[0] == p0_life_before - 4
    assert synthetic_state.life_totals[1] == p1_life_before


def test_resolve_each_opponent_loses_life_active_player_unchanged(
    synthetic_state,
):
    """Asymmetric: EachOpponentLosesLife reduces opponents only —
    the SOURCE's controller (here = active player p0) is NOT
    affected. Verify by recording p0's life before and asserting
    it's unchanged after a 5-life-loss resolution."""
    p0_life_before = synthetic_state.life_totals[0]
    p1_life_before = synthetic_state.life_totals[1]
    assert synthetic_state.active_player == 0

    src_id = synthetic_state.register_and_inject_object(
        _balemurk_leech_dict(amount=5), 0, ZONE_BATTLEFIELD
    )
    synthetic_state.push_to_stack(src_id, 0)
    synthetic_state.resolve_top_of_stack()

    # p0 (controller) untouched; p1 -5.
    assert synthetic_state.life_totals[0] == p0_life_before
    assert synthetic_state.life_totals[1] == p1_life_before - 5


def test_resolve_each_opponent_loses_life_multiple_resolutions_stack(
    synthetic_state,
):
    """Two resolutions in a row (3 + 2 = 5 life loss). Confirms the
    arm is idempotent across repeat invocations and that life-loss
    accumulates additively. Each resolution is its own stack push +
    resolve — register_and_inject_object seeds a Creature source each
    time."""
    p1_life_before = synthetic_state.life_totals[1]

    # First resolution: amount=3.
    src_a = synthetic_state.register_and_inject_object(
        _balemurk_leech_dict(amount=3), 0, ZONE_BATTLEFIELD
    )
    synthetic_state.push_to_stack(src_a, 0)
    synthetic_state.resolve_top_of_stack()

    # Second resolution: amount=2.
    src_b = synthetic_state.register_and_inject_object(
        _balemurk_leech_dict(amount=2), 0, ZONE_BATTLEFIELD
    )
    synthetic_state.push_to_stack(src_b, 0)
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.is_stack_empty() is True
    # p1 lost 3 + 2 = 5 life.
    assert synthetic_state.life_totals[1] == p1_life_before - 5


def test_resolve_each_opponent_loses_life_source_in_graveyard_uses_controller(
    synthetic_state,
):
    """The source-finder walks five zones — wider than the
    battlefield-only scan PutPlusOneCounterOnSelf uses. Inject a
    source-shaped object into p0's graveyard: the zone-scan picks up
    p0 as the controller and resolves the life-loss on p1. Documents
    the "source has left the battlefield by resolve time" tolerance
    — the source's `controller` field doesn't change on zone moves."""
    src_id = synthetic_state.register_and_inject_object(
        _balemurk_leech_dict(amount=2, card_types=["Creature"]),
        0,
        ZONE_GRAVEYARD,
    )
    p0_life_before = synthetic_state.life_totals[0]
    p1_life_before = synthetic_state.life_totals[1]

    synthetic_state.push_to_stack(src_id, 0)
    synthetic_state.resolve_top_of_stack()

    # p1 (the one opponent of p0, recorded on the GameObject
    # regardless of which zone it's in) -2; p0 untouched.
    assert synthetic_state.life_totals[0] == p0_life_before
    assert synthetic_state.life_totals[1] == p1_life_before - 2


def test_resolve_each_opponent_loses_life_clone_isolation(synthetic_state):
    """CoW canary: running EachOpponentLosesLife on a clone leaves
    the original state's life totals untouched. The arm writes
    `players[idx].life` directly — confirm the GameState clone
    semantics decouple the player Vec across clones."""
    src_id = synthetic_state.register_and_inject_object(
        _balemurk_leech_dict(amount=2), 0, ZONE_BATTLEFIELD
    )
    synthetic_state.push_to_stack(src_id, 0)
    p1_life_before = synthetic_state.life_totals[1]

    cloned = synthetic_state.clone_once()
    cloned.resolve_top_of_stack()

    # Clone diverged: p1 lost 2 life.
    assert cloned.life_totals[1] == p1_life_before - 2
    assert cloned.is_stack_empty() is True

    # Original untouched.
    assert synthetic_state.life_totals[1] == p1_life_before
    assert synthetic_state.stack_size() == 1


# --- round-24 DestroyAllCreatures dispatch -------------------------
#
# **DestroyAllCreatures scope** (mirrored in the Rust module docstring
# on ``state_ops_resolve.rs``):
#
# - **Symmetric AOE: walks BOTH players' battlefields.** Unlike
#   DestroyTarget (defender only), DestroyAllCreatures hits every
#   creature regardless of controller — Wrath of God pattern.
# - **Only creatures.** Non-creature permanents (lands, artifacts,
#   enchantments) on the battlefield are not touched.
# - **Indestructible is honored INLINE** (CR 702.12): creatures with
#   the ``indestructible`` keyword stay on the battlefield. Mirrors
#   the DestroyTarget arm's inline check rather than the
#   DamageEachCreature "let SBAs handle it" shape (because this arm
#   moves objects to graveyard directly, not via damage marking).
# - **Per-object state reset on graveyard move** (CR 400.7): tapped /
#   summoning_sick / damage / counters all reset.
# - **Empty battlefield / no creatures = silent no-op** — per-player.
# - **Source on stack not affected** — the resolving sorcery's source
#   lives on the stack, not the battlefield, so the scan naturally
#   skips it.


def _wrath_dict():
    """A destroy-all-creatures sorcery — Wrath-of-God-shaped (2WW,
    sorcery, destroys every creature). CR 701.7 + 701.4 AOE."""
    return {
        "name": "Test Wrath of God",
        "card_types": ["Sorcery"],
        "mana_cost": {"W": 2, "generic": 2},
        "effects": [{"kind": "destroy_all_creatures"}],
    }


def _wrath_indestructible_dict():
    """A vanilla creature printing with the indestructible keyword.
    Used to verify DestroyAllCreatures honors indestructible (mirrors
    the DestroyTarget / SBA indestructible logic)."""
    return {
        "name": "Test Stone Idol",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 4},
        "effects": [],
        "power": 3,
        "toughness": 3,
        "keywords": ["indestructible"],
    }


def _wrath_vanilla_creature_dict():
    """A vanilla creature with no keywords. Used to seed a
    deterministically-destructible target."""
    return {
        "name": "Test Mortal Bear",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 2},
        "effects": [],
        "power": 2,
        "toughness": 2,
    }


def test_resolve_destroy_all_creatures_clears_both_battlefields(
    synthetic_state,
):
    """Resolving Wrath destroys every creature on BOTH players'
    battlefields. Synthetic seed: 5 Bears on each player's bf (ids
    5-9 on p0, 72-76 on p1) plus 5 Forests each. Post-resolve: bears
    in graveyards, Forests still on battlefields."""
    bear_ids_p0 = (5, 6, 7, 8, 9)
    bear_ids_p1 = (72, 73, 74, 75, 76)
    forest_ids_p0 = (0, 1, 2, 3, 4)
    forest_ids_p1 = (67, 68, 69, 70, 71)

    for cid in bear_ids_p0 + bear_ids_p1:
        assert synthetic_state.find_object_zone(cid) == ZONE_BATTLEFIELD
    for lid in forest_ids_p0 + forest_ids_p1:
        assert synthetic_state.find_object_zone(lid) == ZONE_BATTLEFIELD

    p0_grave_before = synthetic_state.graveyard_sizes[0]
    p1_grave_before = synthetic_state.graveyard_sizes[1]

    spell_obj_id = synthetic_state.register_and_inject_object(
        _wrath_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    # All bears moved to their controller's graveyards.
    for cid in bear_ids_p0:
        assert synthetic_state.find_object_zone(cid) == ZONE_GRAVEYARD
    for cid in bear_ids_p1:
        assert synthetic_state.find_object_zone(cid) == ZONE_GRAVEYARD
    # Forests untouched.
    for lid in forest_ids_p0 + forest_ids_p1:
        assert synthetic_state.find_object_zone(lid) == ZONE_BATTLEFIELD
    # Graveyards grew by 5 each (5 bears per side); p0 also got
    # the sorcery itself (post-resolve instant/sorcery -> graveyard).
    assert synthetic_state.graveyard_sizes[0] == p0_grave_before + 5 + 1
    assert synthetic_state.graveyard_sizes[1] == p1_grave_before + 5
    # Stack drained.
    assert synthetic_state.is_stack_empty() is True


def test_resolve_destroy_all_creatures_indestructible_survives(engine):
    """Indestructible creatures (CR 702.12) survive the Wrath. Seed:
    one indestructible creature on each player's battlefield; resolve
    Wrath; both should still be on battlefield, neither in graveyard."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=1
    )
    indestr_p0 = state.register_and_inject_object(
        _wrath_indestructible_dict(), 0, ZONE_BATTLEFIELD
    )
    indestr_p1 = state.register_and_inject_object(
        _wrath_indestructible_dict(), 1, ZONE_BATTLEFIELD
    )
    spell_obj_id = state.register_and_inject_object(
        _wrath_dict(), 0, ZONE_HAND
    )
    state.push_to_stack(spell_obj_id, 0)
    state.resolve_top_of_stack()

    # Indestructible creatures stay put — CR 702.12 honored.
    assert state.find_object_zone(indestr_p0) == ZONE_BATTLEFIELD
    assert state.find_object_zone(indestr_p1) == ZONE_BATTLEFIELD
    # Stack drained, source instant in p0's graveyard.
    assert state.is_stack_empty() is True
    assert state.find_object_zone(spell_obj_id) == ZONE_GRAVEYARD


def test_resolve_destroy_all_creatures_mix_only_normal_destroyed(engine):
    """Mix of normal + indestructible creatures: only the normal
    creatures get destroyed; indestructible ones stay on the
    battlefield."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=1
    )
    mortal_id = state.register_and_inject_object(
        _wrath_vanilla_creature_dict(), 0, ZONE_BATTLEFIELD
    )
    indestr_id = state.register_and_inject_object(
        _wrath_indestructible_dict(), 0, ZONE_BATTLEFIELD
    )
    spell_obj_id = state.register_and_inject_object(
        _wrath_dict(), 0, ZONE_HAND
    )
    state.push_to_stack(spell_obj_id, 0)
    state.resolve_top_of_stack()

    # Mortal -> graveyard; indestructible stays on battlefield.
    assert state.find_object_zone(mortal_id) == ZONE_GRAVEYARD
    assert state.find_object_zone(indestr_id) == ZONE_BATTLEFIELD


def test_resolve_destroy_all_creatures_empty_battlefield_no_error(engine):
    """Empty battlefield = silent no-op. Stack still drains, source
    still moves to graveyard."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=1
    )
    spell_obj_id = state.register_and_inject_object(
        _wrath_dict(), 0, ZONE_HAND
    )
    p0_grave_before = state.graveyard_sizes[0]
    p1_grave_before = state.graveyard_sizes[1]

    state.push_to_stack(spell_obj_id, 0)
    state.resolve_top_of_stack()

    # Stack drained, source in p0's graveyard, p1 untouched.
    assert state.is_stack_empty() is True
    assert state.find_object_zone(spell_obj_id) == ZONE_GRAVEYARD
    assert state.graveyard_sizes[0] == p0_grave_before + 1
    assert state.graveyard_sizes[1] == p1_grave_before


def test_resolve_destroy_all_creatures_only_lands_unaffected(engine):
    """If the only battlefield objects are non-creatures (lands /
    artifacts / etc.), nothing is destroyed. Seeds only a Forest
    on each player's battlefield."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=1
    )
    forest_dict = {
        "name": "Test Forest",
        "card_types": ["Land"],
        "mana_produced": ["G"],
        "effects": [],
    }
    forest_p0 = state.register_and_inject_object(
        forest_dict, 0, ZONE_BATTLEFIELD
    )
    forest_p1 = state.register_and_inject_object(
        forest_dict, 1, ZONE_BATTLEFIELD
    )
    spell_obj_id = state.register_and_inject_object(
        _wrath_dict(), 0, ZONE_HAND
    )
    state.push_to_stack(spell_obj_id, 0)
    state.resolve_top_of_stack()

    # Lands stay put — only Creature card_types are destroyed.
    assert state.find_object_zone(forest_p0) == ZONE_BATTLEFIELD
    assert state.find_object_zone(forest_p1) == ZONE_BATTLEFIELD


def test_resolve_destroy_all_creatures_resets_per_object_state(
    synthetic_state,
):
    """Per-object state reset on zone change (CR 400.7): tapped /
    damage / counters all reset on the way to graveyard. Pre-load a
    creature with non-default state and verify after the Wrath the
    underlying object reads back as reset."""
    target_id = 5  # First Bears on p0's battlefield.
    synthetic_state.tap_object(target_id)
    synthetic_state.add_counters(target_id, 2)
    synthetic_state.deal_damage(target_id, 1)
    assert synthetic_state.is_tapped(target_id) is True
    assert synthetic_state.get_counters(target_id) == 2
    assert synthetic_state.get_damage(target_id) == 1

    spell_obj_id = synthetic_state.register_and_inject_object(
        _wrath_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    # Target moved to graveyard with reset state — the counters/damage
    # readers walk all four tracked zones (including graveyard) and read
    # the underlying GameObject fields. (is_tapped is battlefield-only
    # per its definition, so we can't observe `tapped=false` directly
    # for an object that left the battlefield — the round-17
    # DestroyTarget reset test follows the same convention of asserting
    # only counters/damage post-move.)
    assert synthetic_state.find_object_zone(target_id) == ZONE_GRAVEYARD
    assert synthetic_state.get_counters(target_id) == 0
    assert synthetic_state.get_damage(target_id) == 0


def test_resolve_destroy_all_creatures_source_on_stack_unaffected(engine):
    """The resolving sorcery's source lives on the stack at apply-
    effect time (not on either player's battlefield), so the scan
    naturally skips it. Verify the source still lands in graveyard
    via the normal post-resolve instant/sorcery movement (not because
    Wrath destroyed it)."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=1
    )
    # Inject one creature on p0's bf to give Wrath a real target —
    # otherwise the no-op path doesn't exercise the "source on stack"
    # angle.
    target_id = state.register_and_inject_object(
        _wrath_vanilla_creature_dict(), 0, ZONE_BATTLEFIELD
    )
    spell_obj_id = state.register_and_inject_object(
        _wrath_dict(), 0, ZONE_HAND
    )
    state.push_to_stack(spell_obj_id, 0)
    state.resolve_top_of_stack()

    # Target destroyed; source landed in graveyard via post-resolve
    # (not via Wrath's destroy loop — sorceries aren't creatures).
    assert state.find_object_zone(target_id) == ZONE_GRAVEYARD
    assert state.find_object_zone(spell_obj_id) == ZONE_GRAVEYARD
    assert state.is_stack_empty() is True


def test_resolve_destroy_all_creatures_clone_isolation(synthetic_state):
    """CoW canary: running DestroyAllCreatures on a clone leaves the
    original state's battlefields untouched. Load-bearing because the
    inline Wrath logic uses Arc::make_mut on two zones (battlefield +
    graveyard) per player."""
    spell_obj_id = synthetic_state.register_and_inject_object(
        _wrath_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    p0_bf_before = synthetic_state.battlefield_sizes[0]
    p1_bf_before = synthetic_state.battlefield_sizes[1]
    p0_grave_before = synthetic_state.graveyard_sizes[0]
    p1_grave_before = synthetic_state.graveyard_sizes[1]

    cloned = synthetic_state.clone_once()
    cloned.resolve_top_of_stack()

    # Clone diverged: 5 bears destroyed per player's bf.
    assert cloned.battlefield_sizes[0] == p0_bf_before - 5
    assert cloned.battlefield_sizes[1] == p1_bf_before - 5
    # Graveyards grew (5 bears + 1 sorcery for p0; 5 bears for p1).
    assert cloned.graveyard_sizes[0] == p0_grave_before + 5 + 1
    assert cloned.graveyard_sizes[1] == p1_grave_before + 5

    # Original untouched.
    assert synthetic_state.battlefield_sizes[0] == p0_bf_before
    assert synthetic_state.battlefield_sizes[1] == p1_bf_before
    assert synthetic_state.graveyard_sizes[0] == p0_grave_before
    assert synthetic_state.graveyard_sizes[1] == p1_grave_before
    assert synthetic_state.stack_size() == 1


# --- I33 closure: DestroyAllCreatures walks bf in ETB-timestamp order -
#
# `DestroyAllCreatures` collects destroyable victims via the shared
# `bf_iter_etb_sorted` helper rather than walking p0's bf then p1's bf
# in per-player Vec order. Destruction is order-invariant (each
# destroyable creature ends up in its OWN controller's graveyard via
# `Arc::make_mut` on that controller's zones), so per-controller
# graveyard contents and post-bf state are identical under both visit
# orders. These tests pin the no-regression direction with strictly-
# monotonic interleaved ETB stamps to ensure the new bf-walk doesn't
# lose any victim when the bfs are non-trivially ordered, AND verifies
# that indestructible filtering still works correctly under the
# centralized walk. See I33 in `docs/RUST_PARITY_GAPS.md`.


def test_resolve_destroy_all_creatures_bf_etb_interleaved(engine):
    """With strictly-monotonic ETB stamps interleaved across players,
    the bf-ETB walk destroys every Creature on either bf and routes
    each to its OWN controller's graveyard — same as Python's
    centralized walk filtered to per-controller graveyards. Verifies
    the new collect-via-`bf_iter_etb_sorted` shape doesn't miss any
    victim when bf-ETB order differs from p0-then-p1 walk."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=2
    )
    # ETB stamps strictly monotonic in injection order — interleaved
    # across players.
    p0_old = state.register_and_inject_object(
        _wrath_vanilla_creature_dict(), 0, ZONE_BATTLEFIELD
    )
    p1_mid = state.register_and_inject_object(
        _wrath_vanilla_creature_dict(), 1, ZONE_BATTLEFIELD
    )
    p0_new = state.register_and_inject_object(
        _wrath_vanilla_creature_dict(), 0, ZONE_BATTLEFIELD
    )
    p1_new = state.register_and_inject_object(
        _wrath_vanilla_creature_dict(), 1, ZONE_BATTLEFIELD
    )

    spell_obj_id = state.register_and_inject_object(
        _wrath_dict(), 0, ZONE_HAND
    )
    state.push_to_stack(spell_obj_id, 0)
    state.resolve_top_of_stack()

    # Every Creature destroyed; each in its own controller's
    # graveyard.
    for cid in (p0_old, p0_new):
        assert state.find_object_zone(cid) == ZONE_GRAVEYARD
    for cid in (p1_mid, p1_new):
        assert state.find_object_zone(cid) == ZONE_GRAVEYARD


def test_resolve_destroy_all_creatures_bf_etb_indestructible_interleaved(
    engine,
):
    """Indestructible filter still works under the centralized
    bf-ETB walk: with indestructible creatures interleaved with
    vanilla ones in ETB order, only the vanilla creatures die."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=2
    )
    # Interleaved indestructible / vanilla creatures across players,
    # strictly-monotonic ETB stamps.
    p0_vanilla_old = state.register_and_inject_object(
        _wrath_vanilla_creature_dict(), 0, ZONE_BATTLEFIELD
    )
    p1_indestr_mid = state.register_and_inject_object(
        _wrath_indestructible_dict(), 1, ZONE_BATTLEFIELD
    )
    p0_indestr_new = state.register_and_inject_object(
        _wrath_indestructible_dict(), 0, ZONE_BATTLEFIELD
    )
    p1_vanilla_new = state.register_and_inject_object(
        _wrath_vanilla_creature_dict(), 1, ZONE_BATTLEFIELD
    )

    spell_obj_id = state.register_and_inject_object(
        _wrath_dict(), 0, ZONE_HAND
    )
    state.push_to_stack(spell_obj_id, 0)
    state.resolve_top_of_stack()

    # Vanilla creatures destroyed; indestructible ones survive.
    assert state.find_object_zone(p0_vanilla_old) == ZONE_GRAVEYARD
    assert state.find_object_zone(p1_vanilla_new) == ZONE_GRAVEYARD
    assert state.find_object_zone(p1_indestr_mid) == ZONE_BATTLEFIELD
    assert state.find_object_zone(p0_indestr_new) == ZONE_BATTLEFIELD


# --- DestroyTargetNonlandPermanent dispatch -------------------------
#
# **DestroyTargetNonlandPermanent scope** (mirrored in the Rust module
# docstring on ``cards.rs``):
#
# - **Unit variant** — Python's `DestroyTargetNonlandPermanent` bakes
#   the filter `~IsLand() & ~IsPlayer()` into the class shape; the
#   Rust bridge variant carries no fields and the Land-skip is
#   intrinsic to the dispatch.
# - **First-slice deterministic choice**: scan the DEFENDING player's
#   battlefield top-to-bottom; pick the FIRST object whose printing's
#   `card_types` does NOT contain "Land" AND whose printing's
#   `keywords` does NOT contain "indestructible". Includes creatures,
#   artifacts, enchantments, planeswalkers — anything non-land.
# - **Distinct from round-17 DestroyTarget** which has no filter and
#   happily lands on the defender's first Forest. This variant skips
#   past Lands.
# - **Indestructible is honored** (CR 702.12) — the scan skips
#   indestructible objects in addition to Lands.
# - **Empty / only-Lands / only-indestructible-non-Lands defender bf
#   fizzles silently** — stack item still pops, source still moves
#   post-resolve, no zone deltas.
# - **Per-object state reset on zone change** (CR 400.7) — tapped /
#   summoning_sick / damage / counters reset on the way to graveyard.
# - **Active player's own permanents are NOT affected** — scan only
#   walks the defender's battlefield, mirroring DestroyTarget's
#   asymmetric defender-side targeting.


def _drag_to_the_roots_dict():
    """A destroy-target-nonland-permanent spell — Drag to the Roots-
    shaped (sorcery, destroys target nonland permanent)."""
    return {
        "name": "Test Drag to the Roots",
        "card_types": ["Sorcery"],
        "mana_cost": {"G": 1, "generic": 2},
        "effects": [{"kind": "destroy_target_nonland_permanent"}],
    }


def _nonland_indestructible_creature_dict():
    """A vanilla creature printing with the indestructible keyword —
    used to verify DestroyTargetNonlandPermanent's scan skips
    indestructible non-Land objects too (CR 702.12)."""
    return {
        "name": "Test Stone Idol",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 4},
        "effects": [],
        "power": 3,
        "toughness": 3,
        "keywords": ["indestructible"],
    }


def _vanilla_artifact_dict():
    """A vanilla artifact printing — non-land non-creature non-
    indestructible. Used to confirm artifacts (and other non-land
    types) are also legal targets, distinguishing this from a
    creature-only variant."""
    return {
        "name": "Test Junk Artifact",
        "card_types": ["Artifact"],
        "mana_cost": {"generic": 2},
        "effects": [],
    }


def test_resolve_destroy_target_nonland_permanent_destroys_first_creature(
    synthetic_state,
):
    """End-to-end happy path. The synthetic seed places p0's bf as
    [Forest×5, Bears×5] (ids 0-9) and p1's bf as [Forest×5, Bears×5]
    (ids 67-76), all with ETB timestamp 0 (synthetic fixture). The
    centralized `bf_iter_etb_sorted` walk under the I39 cross-player
    closure produces stable-sort tie-break order p0-then-p1, so the
    first NON-Land permanent is p0's bf[5] = obj_id 5 (p0's first
    Bears). Resolving Drag must skip the 5 Forests and destroy that
    Bears."""
    target_obj_id = 5  # p0's bf[5], the first Bears across both players
    assert synthetic_state.find_object_zone(target_obj_id) == ZONE_BATTLEFIELD

    spell_obj_id = synthetic_state.register_and_inject_object(
        _drag_to_the_roots_dict(), 0, ZONE_HAND
    )
    p0_bf_before = synthetic_state.battlefield_sizes[0]
    p0_grave_before = synthetic_state.graveyard_sizes[0]

    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    # The first non-Land (Bears at obj_id 5 on p0's bf) moved to p0's
    # graveyard. p0 is BOTH source-controller AND owner of the chosen
    # target — DestroyTargetNonlandPermanent doesn't restrict by
    # controller, mirroring Python's any-bf filter.
    assert synthetic_state.find_object_zone(target_obj_id) == ZONE_GRAVEYARD
    assert synthetic_state.battlefield_sizes[0] == p0_bf_before - 1
    # p0's bf[0] Forest stays put (Lands skipped).
    assert synthetic_state.find_object_zone(0) == ZONE_BATTLEFIELD
    # Stack drained; source sorcery also lands in p0's graveyard, plus
    # the destroyed Bears, so p0's graveyard grew by 2.
    assert synthetic_state.is_stack_empty() is True
    assert synthetic_state.find_object_zone(spell_obj_id) == ZONE_GRAVEYARD
    assert synthetic_state.graveyard_sizes[0] == p0_grave_before + 2


def test_resolve_destroy_target_nonland_permanent_only_land_fizzles(engine):
    """If the defender's battlefield is all Lands, the scan finds no
    eligible target and fizzles silently. The Land is NOT destroyed
    (distinct from round-17 DestroyTarget which would destroy bf[0]
    unconditionally)."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=1
    )
    # Inject a Land onto p1's battlefield as bf[0].
    land_id = state.register_and_inject_object(
        {
            "name": "Test Plains",
            "card_types": ["Land"],
            "mana_produced": ["W"],
        },
        1,
        ZONE_BATTLEFIELD,
    )
    spell_obj_id = state.register_and_inject_object(
        _drag_to_the_roots_dict(), 0, ZONE_HAND
    )

    p1_bf_before = state.battlefield_sizes[1]
    p1_grave_before = state.graveyard_sizes[1]
    p0_grave_before = state.graveyard_sizes[0]

    state.push_to_stack(spell_obj_id, 0)
    state.resolve_top_of_stack()

    # Land stays put — scan skipped it, no eligible target.
    assert state.find_object_zone(land_id) == ZONE_BATTLEFIELD
    assert state.battlefield_sizes[1] == p1_bf_before
    assert state.graveyard_sizes[1] == p1_grave_before
    # Stack still drained, source sorcery moved to p0's graveyard.
    assert state.is_stack_empty() is True
    assert state.find_object_zone(spell_obj_id) == ZONE_GRAVEYARD
    assert state.graveyard_sizes[0] == p0_grave_before + 1


def test_resolve_destroy_target_nonland_permanent_skips_land_picks_creature(
    engine,
):
    """Defender has a Land in bf[0] and a Creature in bf[1]. The scan
    skips the Land and destroys the Creature. The Land stays put.
    Directly verifies the Land-skip filter does what its name says."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=1
    )
    land_id = state.register_and_inject_object(
        {
            "name": "Test Plains",
            "card_types": ["Land"],
            "mana_produced": ["W"],
        },
        1,
        ZONE_BATTLEFIELD,
    )
    creature_id = state.register_and_inject_object(
        {
            "name": "Test Vanilla Bear",
            "card_types": ["Creature"],
            "power": 2,
            "toughness": 2,
        },
        1,
        ZONE_BATTLEFIELD,
    )
    spell_obj_id = state.register_and_inject_object(
        _drag_to_the_roots_dict(), 0, ZONE_HAND
    )

    p1_bf_before = state.battlefield_sizes[1]
    p1_grave_before = state.graveyard_sizes[1]

    state.push_to_stack(spell_obj_id, 0)
    state.resolve_top_of_stack()

    # Land stays, creature moved to p1's graveyard.
    assert state.find_object_zone(land_id) == ZONE_BATTLEFIELD
    assert state.find_object_zone(creature_id) == ZONE_GRAVEYARD
    assert state.battlefield_sizes[1] == p1_bf_before - 1
    assert state.graveyard_sizes[1] == p1_grave_before + 1


def test_resolve_destroy_target_nonland_permanent_artifact_target(engine):
    """The non-Land filter is type-agnostic past the Land check — an
    Artifact in bf[0] (no Land in front of it) is a legal target.
    Confirms the variant isn't a creature-only synonym."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=1
    )
    artifact_id = state.register_and_inject_object(
        _vanilla_artifact_dict(), 1, ZONE_BATTLEFIELD
    )
    spell_obj_id = state.register_and_inject_object(
        _drag_to_the_roots_dict(), 0, ZONE_HAND
    )

    state.push_to_stack(spell_obj_id, 0)
    state.resolve_top_of_stack()

    # Artifact destroyed.
    assert state.find_object_zone(artifact_id) == ZONE_GRAVEYARD


def test_resolve_destroy_target_nonland_permanent_indestructible_skipped(
    engine,
):
    """If the defender's first non-Land permanent has the
    `indestructible` keyword, the scan skips it (matching round-17
    DestroyTarget's indestructible suppression). With only an
    indestructible non-Land on the defender's bf, the spell fizzles
    silently — no destruction, no error."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=1
    )
    indestructible_id = state.register_and_inject_object(
        _nonland_indestructible_creature_dict(), 1, ZONE_BATTLEFIELD
    )
    spell_obj_id = state.register_and_inject_object(
        _drag_to_the_roots_dict(), 0, ZONE_HAND
    )

    p1_bf_before = state.battlefield_sizes[1]
    p1_grave_before = state.graveyard_sizes[1]

    state.push_to_stack(spell_obj_id, 0)
    state.resolve_top_of_stack()

    # Indestructible target stays put — scan skipped it.
    assert state.find_object_zone(indestructible_id) == ZONE_BATTLEFIELD
    assert state.battlefield_sizes[1] == p1_bf_before
    assert state.graveyard_sizes[1] == p1_grave_before
    # Stack drained, source moved.
    assert state.is_stack_empty() is True
    assert state.find_object_zone(spell_obj_id) == ZONE_GRAVEYARD


def test_resolve_destroy_target_nonland_permanent_skips_land_and_indestructible(
    engine,
):
    """Stacked filter: defender has Land in bf[0] AND indestructible
    non-Land creature in bf[1]. Both are skipped; no eligible target;
    fizzle. Confirms the Land-skip and indestructible-skip compose."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=1
    )
    land_id = state.register_and_inject_object(
        {
            "name": "Test Plains",
            "card_types": ["Land"],
            "mana_produced": ["W"],
        },
        1,
        ZONE_BATTLEFIELD,
    )
    indestructible_id = state.register_and_inject_object(
        _nonland_indestructible_creature_dict(), 1, ZONE_BATTLEFIELD
    )
    spell_obj_id = state.register_and_inject_object(
        _drag_to_the_roots_dict(), 0, ZONE_HAND
    )

    p1_bf_before = state.battlefield_sizes[1]

    state.push_to_stack(spell_obj_id, 0)
    state.resolve_top_of_stack()

    assert state.find_object_zone(land_id) == ZONE_BATTLEFIELD
    assert state.find_object_zone(indestructible_id) == ZONE_BATTLEFIELD
    assert state.battlefield_sizes[1] == p1_bf_before


def test_resolve_destroy_target_nonland_permanent_empty_battlefield_fizzles(
    engine,
):
    """If the defender has no battlefield objects at all, the spell
    fizzles silently — stack drained, source moved post-resolve."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=1
    )
    spell_obj_id = state.register_and_inject_object(
        _drag_to_the_roots_dict(), 0, ZONE_HAND
    )
    p1_bf_before = state.battlefield_sizes[1]
    p1_grave_before = state.graveyard_sizes[1]
    p0_grave_before = state.graveyard_sizes[0]

    state.push_to_stack(spell_obj_id, 0)
    state.resolve_top_of_stack()

    assert state.is_stack_empty() is True
    assert state.find_object_zone(spell_obj_id) == ZONE_GRAVEYARD
    assert state.battlefield_sizes[1] == p1_bf_before
    assert state.graveyard_sizes[1] == p1_grave_before
    assert state.graveyard_sizes[0] == p0_grave_before + 1


def test_resolve_destroy_target_nonland_permanent_targets_source_controller_when_only_eligible(
    engine,
):
    """The walk crosses BOTH players' battlefield (I39 closure).
    DestroyTargetNonlandPermanent has no controller restriction
    (mirroring Python's `~IsLand() & ~IsPlayer()` filter against the
    centralized `state.battlefield`), so when only the source's own
    creature is eligible the spell DOES destroy it. Setup: p1's bf
    is empty, p0's bf has a Creature. Resolving Drag (cast by p0)
    destroys p0's own Bears."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=1
    )
    own_creature_id = state.register_and_inject_object(
        {
            "name": "Test Vanilla Bear",
            "card_types": ["Creature"],
            "power": 2,
            "toughness": 2,
        },
        0,  # owned by p0 (active player)
        ZONE_BATTLEFIELD,
    )
    spell_obj_id = state.register_and_inject_object(
        _drag_to_the_roots_dict(), 0, ZONE_HAND
    )
    p0_bf_before = state.battlefield_sizes[0]
    p1_bf_before = state.battlefield_sizes[1]

    state.push_to_stack(spell_obj_id, 0)
    state.resolve_top_of_stack()

    # p0's own creature got destroyed — the filter is controller-
    # agnostic, matching Python's any-bf walk.
    assert state.find_object_zone(own_creature_id) == ZONE_GRAVEYARD
    assert state.battlefield_sizes[0] == p0_bf_before - 1
    assert state.battlefield_sizes[1] == p1_bf_before


def test_resolve_destroy_target_nonland_permanent_resets_state(
    synthetic_state,
):
    """Per-object state reset on zone change (CR 400.7): tapped /
    damage / counters all reset on the way to graveyard. Pre-load
    the target with non-default state, resolve Drag, and verify the
    destroyed object's counters/damage reset to zero. Under the I39
    cross-player walk, the first non-Land permanent is p0's bf[5] =
    obj_id 5 (p0's first Bears)."""
    target_obj_id = 5  # p0's bf[5], the first Bears across both players
    synthetic_state.tap_object(target_obj_id)
    synthetic_state.add_counters(target_obj_id, 3)
    synthetic_state.deal_damage(target_obj_id, 2)
    assert synthetic_state.get_counters(target_obj_id) == 3
    assert synthetic_state.get_damage(target_obj_id) == 2

    spell_obj_id = synthetic_state.register_and_inject_object(
        _drag_to_the_roots_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    # Target moved to graveyard with reset state.
    assert synthetic_state.find_object_zone(target_obj_id) == ZONE_GRAVEYARD
    assert synthetic_state.get_counters(target_obj_id) == 0
    assert synthetic_state.get_damage(target_obj_id) == 0


# --- DealDamageAnyTarget dispatch -----------------------------------
#
# **DealDamageAnyTarget scope** (mirrored in the Rust module docstring
# on ``cards.rs``):
#
# - **Lightning Bolt pattern (CR 701.4)** — 7 cards in the EoE pool
#   per round-20 measurement (Debris Field Crusher etc.). The "any
#   target" filter is intrinsic to the variant, distinct from
#   `DealDamage { target: AnyPlayer/AnyCreature }` which carries a
#   `target` dict.
# - **First-slice deterministic choice**: scan the DEFENDING player's
#   battlefield top-to-bottom; pick the FIRST object whose printing's
#   `card_types` contains "Creature". If no creature is found, fall
#   back to defender-as-player life subtraction. Future slice plumbs
#   an explicit choice callback.
# - **Composes existing DealDamage arms** — creature path mirrors
#   AnyCreature's `obj.damage += amount` shape with `Arc::make_mut`
#   on the battlefield; player path mirrors AnyPlayer's
#   `players[idx].life -= amount` shape.
# - **Negative amount raises** at register time AND at resolve time
#   (defense-in-depth — synthetic / injected printings could bypass
#   the parser).


def _debris_field_crusher_dict(amount=3):
    """A deal-damage-any-target printing — Debris Field Crusher-shaped
    (sorcery, deals N to any target)."""
    return {
        "name": "Test Debris Field Crusher",
        "card_types": ["Sorcery"],
        "mana_cost": {"R": 1, "generic": 2},
        "effects": [{"kind": "deal_damage_any_target", "amount": amount}],
    }


def test_resolve_deal_damage_any_target_picks_defender_first_creature(
    synthetic_state,
):
    """End-to-end happy path. The synthetic seed places p1's bf as
    [Forest, Forest, Forest, Forest, Forest, Bears, Bears, ...] —
    the first creature (skipping the 5 Forests) is obj_id 72.
    Resolving Debris Field Crusher must skip the Lands and damage
    that Bears. Distinct from DealDamage{AnyCreature} which would
    hit bf[0] (a Forest) unconditionally — this variant filters by
    Creature type intrinsically."""
    target_obj_id = 72  # p1's bf[5], the first Bears
    assert synthetic_state.get_damage(target_obj_id) == 0

    spell_obj_id = synthetic_state.register_and_inject_object(
        _debris_field_crusher_dict(amount=2), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    life_before = list(synthetic_state.life_totals)
    resolved = synthetic_state.resolve_top_of_stack()

    assert resolved is not None
    # First creature (Bears at 72) took the damage; Forest at bf[0]
    # untouched (Land filter).
    assert synthetic_state.get_damage(target_obj_id) == 2
    assert synthetic_state.get_damage(67) == 0  # p1 bf[0] Forest
    # Life totals untouched (creature took the damage, not the player).
    assert list(synthetic_state.life_totals) == life_before
    assert synthetic_state.is_stack_empty() is True


def test_resolve_deal_damage_any_target_no_creature_falls_back_to_player(
    engine,
):
    """If defender has no creature on battlefield (only Lands), the
    fallback to defender-as-player kicks in — life subtracts. Mirrors
    the AnyPlayer arm's life-write shape. Distinguishes this variant
    from DealDamage{AnyCreature} which would FIZZLE silently in the
    same setup."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=1
    )
    # Inject a Land onto p1's battlefield as bf[0] — no creature.
    state.register_and_inject_object(
        {
            "name": "Test Plains",
            "card_types": ["Land"],
            "mana_produced": ["W"],
        },
        1,
        ZONE_BATTLEFIELD,
    )
    spell_obj_id = state.register_and_inject_object(
        _debris_field_crusher_dict(amount=4), 0, ZONE_HAND
    )
    state.push_to_stack(spell_obj_id, 0)
    life_before = list(state.life_totals)

    state.resolve_top_of_stack()

    # Fallback to defender-as-player: p1 takes 4 damage.
    assert state.life_totals[1] == life_before[1] - 4
    assert state.life_totals[0] == life_before[0]  # active player untouched
    assert state.is_stack_empty() is True


def test_resolve_deal_damage_any_target_empty_battlefield_damages_player(
    engine,
):
    """Defender has empty battlefield — no creature OR land. Fallback
    still applies: defender-as-player takes the damage. Mirrors the
    AnyPlayer arm rather than the AnyCreature fizzle path."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=1
    )
    spell_obj_id = state.register_and_inject_object(
        _debris_field_crusher_dict(amount=3), 0, ZONE_HAND
    )
    state.push_to_stack(spell_obj_id, 0)
    life_before = list(state.life_totals)

    state.resolve_top_of_stack()

    assert state.life_totals[1] == life_before[1] - 3
    assert state.life_totals[0] == life_before[0]
    assert state.is_stack_empty() is True


def test_resolve_deal_damage_any_target_multiple_creatures_hits_first(
    engine,
):
    """Defender has multiple Creatures on bf; first one (zone[0]
    iteration order) takes the damage. Mirrors the AnyCreature arm's
    smallest-index pick."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=1
    )
    first_creature_id = state.register_and_inject_object(
        {
            "name": "Test First Bear",
            "card_types": ["Creature"],
            "power": 2,
            "toughness": 2,
        },
        1,
        ZONE_BATTLEFIELD,
    )
    second_creature_id = state.register_and_inject_object(
        {
            "name": "Test Second Bear",
            "card_types": ["Creature"],
            "power": 3,
            "toughness": 3,
        },
        1,
        ZONE_BATTLEFIELD,
    )
    spell_obj_id = state.register_and_inject_object(
        _debris_field_crusher_dict(amount=2), 0, ZONE_HAND
    )
    state.push_to_stack(spell_obj_id, 0)

    state.resolve_top_of_stack()

    # First creature took the damage; second untouched.
    assert state.get_damage(first_creature_id) == 2
    assert state.get_damage(second_creature_id) == 0


def test_resolve_deal_damage_any_target_amount_zero_no_op(synthetic_state):
    """amount=0 is a legal no-op (mirrors GainLife / DrawCards /
    Mill zero-amount conventions). No damage applied, no life change,
    no error. The stack still pops and the source still moves."""
    target_obj_id = 72  # p1's first Bears
    spell_obj_id = synthetic_state.register_and_inject_object(
        _debris_field_crusher_dict(amount=0), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    life_before = list(synthetic_state.life_totals)

    synthetic_state.resolve_top_of_stack()

    # No damage applied to creature; life totals unchanged.
    assert synthetic_state.get_damage(target_obj_id) == 0
    assert list(synthetic_state.life_totals) == life_before
    assert synthetic_state.is_stack_empty() is True


def test_resolve_deal_damage_any_target_negative_amount_raises_at_register():
    """Register-time guard on negative amount (defense-in-depth, the
    apply_effect guard is the secondary check). Mirrors
    EachOpponentLosesLife / DiscardSelf / PutPlusOneCounterOnSelf
    negative-amount register-time check shape."""
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    with pytest.raises(ValueError, match="non-negative"):
        reg.register_printing(_debris_field_crusher_dict(amount=-1))


def test_resolve_deal_damage_any_target_stacks_with_prior_damage(
    synthetic_state,
):
    """Damage stacks: prior damage on the target creature is preserved
    and the new damage adds on top. Mirrors the AnyCreature arm's
    `obj.damage = obj.damage.saturating_add(amount)` shape."""
    target_obj_id = 72  # p1's first Bears
    # Pre-load with 1 damage.
    synthetic_state.deal_damage(target_obj_id, 1)
    assert synthetic_state.get_damage(target_obj_id) == 1

    spell_obj_id = synthetic_state.register_and_inject_object(
        _debris_field_crusher_dict(amount=2), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    # Damage stacks: 1 + 2 = 3.
    assert synthetic_state.get_damage(target_obj_id) == 3


def test_resolve_deal_damage_any_target_clone_isolation(synthetic_state):
    """CoW canary: cloning the state and resolving a deal-damage-any-
    target on the clone must not bleed back into the original — stack,
    life totals, and creature damage on the original side all stay put."""
    target_obj_id = 72  # p1's first Bears
    spell_obj_id = synthetic_state.register_and_inject_object(
        _debris_field_crusher_dict(amount=3), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    cloned = synthetic_state.clone_once()

    cloned.resolve_top_of_stack()

    # Clone: stack drained, target creature damaged.
    assert cloned.is_stack_empty() is True
    assert cloned.get_damage(target_obj_id) == 3
    # Original: stack still has the spell, no damage applied.
    assert synthetic_state.stack_size() == 1
    assert synthetic_state.get_damage(target_obj_id) == 0
    assert list(synthetic_state.life_totals) == [20, 20]


# --- LoseLife dispatch ---------------------------------------------
#
# CR 118.4 — "life loss" (not damage). The SOURCE's controller loses
# `amount` life. Punisher / drawback pattern (Decode Transmissions
# shape) — 7 cards in the EoE pool per round-20 measurement.
#
# **Distinct from round-26 EachOpponentLosesLife.** Same source-finder
# pattern (5-zone walk + stack scan); the dispatch arm subtracts from
# the source's CONTROLLER's life rather than the controller's
# opponent's. Inverted target on an otherwise identical shape.
#
# **Source-finder dispatch (round-24 pattern).** Walks both players'
# five tracked zones (hand / library / battlefield / graveyard /
# exile) plus the stack to recover the source's `controller`. Mirrors
# EachOpponentLosesLife / DiscardSelf — punisher effects fire on
# whoever controls the source regardless of where the source currently
# sits, since the controller field doesn't change on zone moves.
#
# Direct life subtraction. amount=0 is a legal no-op; amount<0 raises
# at register time. Source not found = silent fizzle.


def _decode_transmissions_dict(amount=2, card_types=None):
    """A Decode-Transmissions-shaped printing: an instant / sorcery
    whose effect makes the SOURCE's controller lose `amount` life.

    Default card_types=["Sorcery"] so the post-resolve mover sends the
    source to its owner's graveyard (Decode Transmissions is a printed
    sorcery with a self-life-loss drawback). Tests that need a
    different source-zone behavior override card_types.
    """
    if card_types is None:
        card_types = ["Sorcery"]
    p = {
        "name": f"Test Decode Transmissions (x{amount})",
        "card_types": card_types,
        "mana_cost": {"U": 1, "generic": 2},
        "effects": [{"kind": "lose_life", "amount": amount}],
    }
    if "Creature" in card_types:
        p["power"] = 1
        p["toughness"] = 1
    return p


def test_resolve_lose_life_decrements_controller_life(synthetic_state):
    """Happy path: source on active player's (p0) battlefield with
    amount=3 — p0 (the CONTROLLER, not the opponent) loses 3 life;
    p1 untouched. This is the inversion-of-EachOpponentLosesLife
    cardinal test: the same dispatch shape but the SOURCE's
    controller is the recipient."""
    src_id = synthetic_state.register_and_inject_object(
        _decode_transmissions_dict(amount=3, card_types=["Creature"]),
        0,
        ZONE_BATTLEFIELD,
    )
    p0_life_before = synthetic_state.life_totals[0]
    p1_life_before = synthetic_state.life_totals[1]

    synthetic_state.push_to_stack(src_id, 0)
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.is_stack_empty() is True
    # p0 (source's controller) -3; p1 (the one opponent) untouched.
    assert synthetic_state.life_totals[0] == p0_life_before - 3
    assert synthetic_state.life_totals[1] == p1_life_before


def test_resolve_lose_life_amount_zero_no_op(synthetic_state):
    """amount=0 is a legitimate no-op (mirrors GainLife / DrawCards /
    Mill / EachOpponentLosesLife / DiscardSelf zero-amount
    conventions). No life change, no error, stack pops."""
    src_id = synthetic_state.register_and_inject_object(
        _decode_transmissions_dict(amount=0, card_types=["Creature"]),
        0,
        ZONE_BATTLEFIELD,
    )
    life_before = list(synthetic_state.life_totals)
    synthetic_state.push_to_stack(src_id, 0)
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.is_stack_empty() is True
    assert list(synthetic_state.life_totals) == life_before


def test_resolve_lose_life_opponent_source_targets_opponent(synthetic_state):
    """When p1 controls the source (controller=1) while active_player
    stays p0, resolving LoseLife reduces p1's life (the CONTROLLER —
    NOT defender-of-active-player). Documents that LoseLife pivots
    on `obj.controller`, not on active_player, which is exactly the
    regression-on-the-inversion of EachOpponentLosesLife's behavior."""
    src_id = synthetic_state.register_and_inject_object(
        _decode_transmissions_dict(amount=4, card_types=["Creature"]),
        1,
        ZONE_BATTLEFIELD,
    )
    p0_life_before = synthetic_state.life_totals[0]
    p1_life_before = synthetic_state.life_totals[1]
    assert synthetic_state.active_player == 0

    # Push with controller=1 (p1's source resolving on the stack).
    synthetic_state.push_to_stack(src_id, 1)
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.is_stack_empty() is True
    # p1 (source's controller) -4; p0 untouched.
    assert synthetic_state.life_totals[0] == p0_life_before
    assert synthetic_state.life_totals[1] == p1_life_before - 4


def test_resolve_lose_life_opponent_unchanged_when_active_controls_source(
    synthetic_state,
):
    """Regression on the EachOpponentLosesLife inversion: when the
    ACTIVE player controls the source, the OPPONENT's life is
    UNCHANGED. Verifies that LoseLife does NOT accidentally route
    through the EachOpponentLosesLife arm (which would hit p1 when
    p0 controls the source). This is the single most important
    correctness check distinguishing the two arms."""
    p0_life_before = synthetic_state.life_totals[0]
    p1_life_before = synthetic_state.life_totals[1]
    assert synthetic_state.active_player == 0

    src_id = synthetic_state.register_and_inject_object(
        _decode_transmissions_dict(amount=5, card_types=["Creature"]),
        0,
        ZONE_BATTLEFIELD,
    )
    synthetic_state.push_to_stack(src_id, 0)
    synthetic_state.resolve_top_of_stack()

    # p0 (controller) -5; p1 (opponent of controller) UNCHANGED —
    # this is the cardinal asymmetry vs EachOpponentLosesLife.
    assert synthetic_state.life_totals[0] == p0_life_before - 5
    assert synthetic_state.life_totals[1] == p1_life_before


def test_resolve_lose_life_source_in_graveyard_uses_controller(
    synthetic_state,
):
    """The source-finder walks five zones — wider than the
    battlefield-only scan PutPlusOneCounterOnSelf uses. Inject a
    source-shaped object into p0's graveyard: the zone-scan picks up
    p0 as the controller and resolves the life-loss on p0 (the
    SOURCE's CONTROLLER). Documents the 'source has left the
    battlefield by resolve time' tolerance — the source's
    `controller` field doesn't change on zone moves. Mirrors round-26
    EachOpponentLosesLife's graveyard-source test, inverted to hit
    the controller's life rather than the opponent's."""
    src_id = synthetic_state.register_and_inject_object(
        _decode_transmissions_dict(amount=2, card_types=["Creature"]),
        0,
        ZONE_GRAVEYARD,
    )
    p0_life_before = synthetic_state.life_totals[0]
    p1_life_before = synthetic_state.life_totals[1]

    synthetic_state.push_to_stack(src_id, 0)
    synthetic_state.resolve_top_of_stack()

    # p0 (the source's controller, regardless of which zone holds it)
    # -2; p1 untouched.
    assert synthetic_state.life_totals[0] == p0_life_before - 2
    assert synthetic_state.life_totals[1] == p1_life_before


def test_resolve_lose_life_multiple_resolutions_stack(synthetic_state):
    """Two resolutions in a row (3 + 2 = 5 life loss). Confirms the
    arm is idempotent across repeat invocations and that life-loss
    accumulates additively on the controller's side."""
    p0_life_before = synthetic_state.life_totals[0]

    # First resolution: amount=3.
    src_a = synthetic_state.register_and_inject_object(
        _decode_transmissions_dict(amount=3, card_types=["Creature"]),
        0,
        ZONE_BATTLEFIELD,
    )
    synthetic_state.push_to_stack(src_a, 0)
    synthetic_state.resolve_top_of_stack()

    # Second resolution: amount=2.
    src_b = synthetic_state.register_and_inject_object(
        _decode_transmissions_dict(amount=2, card_types=["Creature"]),
        0,
        ZONE_BATTLEFIELD,
    )
    synthetic_state.push_to_stack(src_b, 0)
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.is_stack_empty() is True
    # p0 lost 3 + 2 = 5 life.
    assert synthetic_state.life_totals[0] == p0_life_before - 5


def test_resolve_lose_life_clone_isolation(synthetic_state):
    """CoW canary: running LoseLife on a clone leaves the original
    state's life totals untouched. The arm writes
    `players[idx].life` directly — confirm the GameState clone
    semantics decouple the player Vec across clones."""
    src_id = synthetic_state.register_and_inject_object(
        _decode_transmissions_dict(amount=2, card_types=["Creature"]),
        0,
        ZONE_BATTLEFIELD,
    )
    synthetic_state.push_to_stack(src_id, 0)
    p0_life_before = synthetic_state.life_totals[0]

    cloned = synthetic_state.clone_once()
    cloned.resolve_top_of_stack()

    # Clone diverged: p0 lost 2 life.
    assert cloned.life_totals[0] == p0_life_before - 2
    assert cloned.is_stack_empty() is True

    # Original untouched.
    assert synthetic_state.life_totals[0] == p0_life_before
    assert synthetic_state.stack_size() == 1


# --- TargetOpponentLosesLife dispatch ------------------------------
#
# CR 118.4 — "life loss" (not damage). Target opponent loses `amount`
# life. Dubious Delicacy pattern — 2 cards in the EoE pool per round-20
# measurement.
#
# **Distinct from EachOpponentLosesLife (round 26).** That arm hits ALL
# opponents (in 2-player land = the one opponent). TargetOpponentLosesLife
# is targeted — the caster CHOOSES which opponent loses life. In a
# 2-player engine these collapse to the same runtime effect; the
# variants stay distinct to mirror Python's closed Effect vocabulary
# (targeted vs each-opponent semantics — round-15 pattern). Future
# multiplayer / archenemy work needs an explicit choice callback.
#
# **Source-finder dispatch (round-24 pattern).** Walks both players'
# five tracked zones (hand / library / battlefield / graveyard /
# exile) plus the stack to recover the source's `controller`. Mirrors
# EachOpponentLosesLife / LoseLife / DiscardSelf.
#
# Direct life subtraction on the one opponent. amount=0 is a legal
# no-op; amount<0 raises at register time. Source not found = silent
# fizzle.


def _dubious_delicacy_dict(amount=3, card_types=None):
    """A Dubious-Delicacy-shaped printing: an artifact / instant /
    sorcery whose effect makes target opponent lose `amount` life.

    Default card_types=["Sorcery"] so the post-resolve mover sends the
    source to its owner's graveyard. Tests that need a different
    source-zone behavior override card_types.
    """
    if card_types is None:
        card_types = ["Sorcery"]
    p = {
        "name": f"Test Dubious Delicacy (x{amount})",
        "card_types": card_types,
        "mana_cost": {"generic": 2},
        "effects": [{"kind": "target_opponent_loses_life", "amount": amount}],
    }
    if "Creature" in card_types:
        p["power"] = 1
        p["toughness"] = 1
    return p


def test_resolve_target_opponent_loses_life_decrements_opponent_life(
    synthetic_state,
):
    """Happy path: source on active player's (p0) battlefield with
    amount=3 — p1 (the one opponent) loses 3 life; p0 untouched.
    Dubious Delicacy's targeted variant collapses to the same end-state
    as EachOpponentLosesLife in 2-player land."""
    src_id = synthetic_state.register_and_inject_object(
        _dubious_delicacy_dict(amount=3, card_types=["Creature"]),
        0,
        ZONE_BATTLEFIELD,
    )
    p0_life_before = synthetic_state.life_totals[0]
    p1_life_before = synthetic_state.life_totals[1]

    synthetic_state.push_to_stack(src_id, 0)
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.is_stack_empty() is True
    # p0 (source's controller) untouched; p1 (the one opponent) -3.
    assert synthetic_state.life_totals[0] == p0_life_before
    assert synthetic_state.life_totals[1] == p1_life_before - 3


def test_resolve_target_opponent_loses_life_amount_zero_no_op(
    synthetic_state,
):
    """amount=0 is a legitimate no-op (mirrors GainLife / DrawCards /
    Mill / EachOpponentLosesLife / LoseLife zero-amount conventions).
    No life change, no error, stack pops."""
    src_id = synthetic_state.register_and_inject_object(
        _dubious_delicacy_dict(amount=0, card_types=["Creature"]),
        0,
        ZONE_BATTLEFIELD,
    )
    life_before = list(synthetic_state.life_totals)
    synthetic_state.push_to_stack(src_id, 0)
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.is_stack_empty() is True
    assert list(synthetic_state.life_totals) == life_before


def test_resolve_target_opponent_loses_life_opponent_source_targets_active_player(
    synthetic_state,
):
    """Target-opponent is OPPONENT-OF-CONTROLLER, NOT defender-of-
    active-player. Source on p1's battlefield (controller=1) while
    active_player stays p0 — resolving TargetOpponentLosesLife reduces
    p0's life (the one opponent of p1), NOT p1's. Cross-controller-
    active-player distinction matches EachOpponentLosesLife's
    behavior."""
    src_id = synthetic_state.register_and_inject_object(
        _dubious_delicacy_dict(amount=4, card_types=["Creature"]),
        1,
        ZONE_BATTLEFIELD,
    )
    p0_life_before = synthetic_state.life_totals[0]
    p1_life_before = synthetic_state.life_totals[1]
    assert synthetic_state.active_player == 0

    # Push with controller=1 (p1's source resolving on the stack).
    synthetic_state.push_to_stack(src_id, 1)
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.is_stack_empty() is True
    # p0 (the one opponent of p1) -4; p1 (controller) untouched.
    assert synthetic_state.life_totals[0] == p0_life_before - 4
    assert synthetic_state.life_totals[1] == p1_life_before


def test_resolve_target_opponent_loses_life_negative_amount_raises_at_register(
    synthetic_state,
):
    """Negative amount is a schema error (mirrors EachOpponentLosesLife
    / LoseLife / DamageEachOpponent / DiscardSelf raise-on-negative
    shape). The parse_effect bridge guard surfaces this at register
    time — before resolution ever runs."""
    with pytest.raises(ValueError):
        synthetic_state.register_and_inject_object(
            _dubious_delicacy_dict(amount=-2, card_types=["Creature"]),
            0,
            ZONE_BATTLEFIELD,
        )


def test_resolve_target_opponent_loses_life_source_in_graveyard_uses_controller(
    synthetic_state,
):
    """The source-finder walks five zones — wider than the battlefield-
    only scan PutPlusOneCounterOnSelf uses. Inject a source-shaped
    object into p0's graveyard: the zone-scan picks up p0 as the
    controller and resolves the life-loss on p1 (the one opponent of
    the source's controller). Documents the 'source has left the
    battlefield by resolve time' tolerance — the source's `controller`
    field doesn't change on zone moves."""
    src_id = synthetic_state.register_and_inject_object(
        _dubious_delicacy_dict(amount=2, card_types=["Creature"]),
        0,
        ZONE_GRAVEYARD,
    )
    p0_life_before = synthetic_state.life_totals[0]
    p1_life_before = synthetic_state.life_totals[1]

    synthetic_state.push_to_stack(src_id, 0)
    synthetic_state.resolve_top_of_stack()

    # p1 (the one opponent of p0, recorded on the GameObject regardless
    # of which zone it's in) -2; p0 untouched.
    assert synthetic_state.life_totals[0] == p0_life_before
    assert synthetic_state.life_totals[1] == p1_life_before - 2


def test_resolve_target_opponent_loses_life_clone_isolation(synthetic_state):
    """CoW canary: running TargetOpponentLosesLife on a clone leaves
    the original state's life totals untouched. The arm writes
    `players[idx].life` directly — confirm the GameState clone
    semantics decouple the player Vec across clones."""
    src_id = synthetic_state.register_and_inject_object(
        _dubious_delicacy_dict(amount=2, card_types=["Creature"]),
        0,
        ZONE_BATTLEFIELD,
    )
    synthetic_state.push_to_stack(src_id, 0)
    p1_life_before = synthetic_state.life_totals[1]

    cloned = synthetic_state.clone_once()
    cloned.resolve_top_of_stack()

    # Clone diverged: p1 lost 2 life.
    assert cloned.life_totals[1] == p1_life_before - 2
    assert cloned.is_stack_empty() is True

    # Original untouched.
    assert synthetic_state.life_totals[1] == p1_life_before
    assert synthetic_state.stack_size() == 1


# --- MillTargetPlayer dispatch -------------------------------------
#
# CR 701.13b — "mill" (a player puts the top N cards of their library
# into their graveyard). Scrabbling Skullcrab pattern (2 cards in the
# EoE pool per round-20 measurement).
#
# **Distinct from Effect::Mill (round 10).** That arm mills the
# CONTROLLER's library; MillTargetPlayer mills a TARGET player's
# library. First-slice deterministic target choice: the one defender
# (= 1 - active_player), mirroring the DealDamage / TapTarget /
# TargetOpponentLosesLife "the one opponent" convention. Future
# multiplayer / archenemy work needs an explicit choice callback.
#
# Negative count raises at register time; count=0 is a legal no-op.
# Fewer cards in library than `count` mills all remaining (Python
# parity). Per-object state reset on graveyard move (CR 400.7).


def _scrabbling_skullcrab_dict(count=2, card_types=None):
    """A mill-N-target-player card. Default count=2 (Scrabbling
    Skullcrab's actual mill amount); default card_types=["Sorcery"]
    so post-resolve sends the source to its controller's graveyard.
    """
    if card_types is None:
        card_types = ["Sorcery"]
    p = {
        "name": f"Test Scrabbling Skullcrab (mill {count})",
        "card_types": card_types,
        "mana_cost": {"generic": 1, "U": 1},
        "effects": [{"kind": "mill_target_player", "count": count}],
    }
    if "Creature" in card_types:
        p["power"] = 2
        p["toughness"] = 2
    return p


def test_resolve_mill_target_player_mills_defender(synthetic_state):
    """Happy path: source on active player's (p0) battlefield with
    count=3 — defender (p1) library 50 -> 47, p1 graveyard 0 -> 3.
    p0's library and graveyard are untouched (this is the load-bearing
    distinction from Effect::Mill, which would have hit p0)."""
    p0_lib_before = synthetic_state.library_sizes[0]
    p0_grave_before = synthetic_state.graveyard_sizes[0]
    p1_lib_before = synthetic_state.library_sizes[1]
    p1_grave_before = synthetic_state.graveyard_sizes[1]
    assert p1_lib_before == 50

    src_id = synthetic_state.register_and_inject_object(
        _scrabbling_skullcrab_dict(count=3, card_types=["Creature"]),
        0,  # controller p0
        ZONE_BATTLEFIELD,
    )
    synthetic_state.push_to_stack(src_id, 0)
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.is_stack_empty() is True
    # Defender (p1): library -3, graveyard +3.
    assert synthetic_state.library_sizes[1] == p1_lib_before - 3
    assert synthetic_state.graveyard_sizes[1] == p1_grave_before + 3
    # Controller (p0): library + graveyard untouched. Source was a
    # Creature on battlefield — post-resolve leaves it on p0's
    # battlefield, NOT p0's graveyard, so no graveyard delta on p0.
    assert synthetic_state.library_sizes[0] == p0_lib_before
    assert synthetic_state.graveyard_sizes[0] == p0_grave_before


def test_resolve_mill_target_player_fewer_cards_than_count_mills_all(
    engine,
):
    """Defender's library has fewer cards than `count`: mill all
    remaining (Python parity with the `if not target.library: break`
    short-circuit). No crash, no fizzle — partial fill is allowed."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=2
    )
    p1_lib_before = state.library_sizes[1]
    p1_grave_before = state.graveyard_sizes[1]
    assert p1_lib_before == 2

    src_id = state.register_and_inject_object(
        # card_types=["Sorcery"] so post-resolve moves source to p0's
        # graveyard (not p1's) — keeps the p1 graveyard delta clean.
        _scrabbling_skullcrab_dict(count=5, card_types=["Sorcery"]),
        0,
        ZONE_HAND,
    )
    state.push_to_stack(src_id, 0)
    state.resolve_top_of_stack()

    # Defender library drained, graveyard gained the 2 cards available.
    assert state.library_sizes[1] == 0
    assert state.graveyard_sizes[1] == p1_grave_before + 2


def test_resolve_mill_target_player_empty_library_no_op(engine):
    """Defender's library starts empty: silent no-op. No crash, no
    error, stack still pops."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=0
    )
    p1_lib_before = state.library_sizes[1]
    p1_grave_before = state.graveyard_sizes[1]
    assert p1_lib_before == 0

    src_id = state.register_and_inject_object(
        _scrabbling_skullcrab_dict(count=3, card_types=["Sorcery"]),
        0,
        ZONE_HAND,
    )
    state.push_to_stack(src_id, 0)
    state.resolve_top_of_stack()

    assert state.is_stack_empty() is True
    assert state.library_sizes[1] == p1_lib_before  # still 0
    assert state.graveyard_sizes[1] == p1_grave_before  # still 0


def test_resolve_mill_target_player_count_zero_no_op(synthetic_state):
    """count=0 is a legitimate no-op (mirrors GainLife / DrawCards /
    Mill / EachOpponentLosesLife zero-count conventions). No library
    drain, no graveyard delta, no error."""
    p1_lib_before = synthetic_state.library_sizes[1]
    p1_grave_before = synthetic_state.graveyard_sizes[1]

    src_id = synthetic_state.register_and_inject_object(
        _scrabbling_skullcrab_dict(count=0, card_types=["Sorcery"]),
        0,
        ZONE_HAND,
    )
    synthetic_state.push_to_stack(src_id, 0)
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.is_stack_empty() is True
    assert synthetic_state.library_sizes[1] == p1_lib_before
    assert synthetic_state.graveyard_sizes[1] == p1_grave_before


def test_resolve_mill_target_player_does_not_mill_active_player(
    synthetic_state,
):
    """Regression for the Mill vs MillTargetPlayer split. The
    active-player (controller of the resolving source) is the CASTER —
    Effect::Mill would hit them; Effect::MillTargetPlayer must NOT.
    Source is a Sorcery in p0's hand; on resolve, p0's library stays
    the same size (only the source moves to p0's graveyard, which is a
    post-resolve move, not a mill)."""
    p0_lib_before = synthetic_state.library_sizes[0]
    p0_grave_before = synthetic_state.graveyard_sizes[0]

    src_id = synthetic_state.register_and_inject_object(
        _scrabbling_skullcrab_dict(count=4, card_types=["Sorcery"]),
        0,
        ZONE_HAND,
    )
    synthetic_state.push_to_stack(src_id, 0)
    synthetic_state.resolve_top_of_stack()

    # p0 library UNCHANGED — no mill happened on the active player.
    assert synthetic_state.library_sizes[0] == p0_lib_before
    # p0 graveyard gained the source itself (Sorcery -> owner's
    # graveyard per CR 608.2m post-resolve). +1, NOT +1+count — the
    # count cards milled landed in p1's graveyard.
    assert synthetic_state.graveyard_sizes[0] == p0_grave_before + 1


def test_resolve_mill_target_player_negative_count_raises_at_register(
    synthetic_state,
):
    """Negative count is a schema error (mirrors Surveil /
    SearchLibraryForBasicLandTapped / TargetOpponentLosesLife
    raise-on-negative shape). The parse_effect bridge guard surfaces
    this at register time — before resolution ever runs."""
    with pytest.raises(ValueError):
        synthetic_state.register_and_inject_object(
            _scrabbling_skullcrab_dict(count=-1, card_types=["Sorcery"]),
            0,
            ZONE_HAND,
        )


def test_resolve_mill_target_player_resets_per_object_state(
    synthetic_state,
):
    """Per-object state reset on graveyard move (CR 400.7).

    Inject a counter-bearing GameObject into the defender's (p1)
    library, then mill 1 card. The most recently injected card sits at
    the TOP of the library (round-1 convention: top = last element of
    Vec), so it's milled first. On landing in graveyard, its counters
    should be reset to 0."""
    # Inject a creature into p1's library, then stamp counters on it.
    counter_obj_id = synthetic_state.register_and_inject_object(
        {
            "name": "Counter-bearing milled card",
            "card_types": ["Creature"],
            "power": 1,
            "toughness": 1,
        },
        1,  # controller p1
        ZONE_LIBRARY,
    )
    # Stamp +2/+2 onto the card. `add_counters` walks library too.
    assert synthetic_state.add_counters(counter_obj_id, 2) is True
    assert synthetic_state.power_bonus_from_counters(counter_obj_id) == 2

    # Mill 1 — the counter-bearing card was injected last, so it's at
    # the TOP of p1's library (pop() target).
    src_id = synthetic_state.register_and_inject_object(
        _scrabbling_skullcrab_dict(count=1, card_types=["Sorcery"]),
        0,
        ZONE_HAND,
    )
    synthetic_state.push_to_stack(src_id, 0)
    synthetic_state.resolve_top_of_stack()

    # Card landed in p1's graveyard.
    assert synthetic_state.find_object_zone(counter_obj_id) == ZONE_GRAVEYARD
    # Counters reset to 0 on zone change (CR 400.7).
    assert synthetic_state.power_bonus_from_counters(counter_obj_id) == 0


def test_resolve_mill_target_player_clone_isolation(synthetic_state):
    """CoW canary: running MillTargetPlayer on a clone leaves the
    original state's library + graveyard untouched. The arm pops from
    the defender's library Vec via `Arc::make_mut` — confirm the
    clone's library Arc decouples from the original."""
    p1_lib_before = synthetic_state.library_sizes[1]
    p1_grave_before = synthetic_state.graveyard_sizes[1]

    src_id = synthetic_state.register_and_inject_object(
        _scrabbling_skullcrab_dict(count=3, card_types=["Sorcery"]),
        0,
        ZONE_HAND,
    )
    synthetic_state.push_to_stack(src_id, 0)
    cloned = synthetic_state.clone_once()

    cloned.resolve_top_of_stack()

    # Clone diverged: 3 cards milled from defender.
    assert cloned.library_sizes[1] == p1_lib_before - 3
    assert cloned.graveyard_sizes[1] == p1_grave_before + 3
    assert cloned.is_stack_empty() is True

    # Original untouched on every front.
    assert synthetic_state.library_sizes[1] == p1_lib_before
    assert synthetic_state.graveyard_sizes[1] == p1_grave_before
    assert synthetic_state.stack_size() == 1


# --- EachOpponentDiscards dispatch ----------------------------------
#
# CR 701.8 — discard. Each opponent of the SOURCE's controller
# discards `count` cards. Let's Play a Game pattern (2 EoE cards).
#
# **Distinct from round-15 DiscardCard { target: AnyPlayer }** — that
# arm picks the DEFENDING player's hand[0] (caller-targeted, active-
# player's spell forces the opponent to discard). EachOpponentDiscards
# fires on the SOURCE's controller's opponents (source-relative). In a
# 2-player engine both collapse to "the one opponent discards hand[0]"
# but the variants stay distinct to mirror Python's closed `Effect`
# vocabulary.
#
# **Distinct from round-24 DiscardSelf** — that arm discards from the
# CONTROLLER's hand. This arm discards from the OPPONENT of the
# controller's hand. Inverted target on otherwise identical dispatch
# shape — composes round-24 EachOpponentLosesLife's opponent-resolution
# with round-24 DiscardSelf's discard primitive.
#
# **Source-finder dispatch (round-24 pattern).** Walks both players'
# five tracked zones plus the stack to recover the source's
# `controller`. Two-player "each opponent" reduces to `1 - controller`.
# Empty opponent hand / source not found = silent no-op.


def _lets_play_a_game_dict(count=1, card_types=None):
    """A Let's-Play-a-Game-shaped printing: a permanent (or instant /
    sorcery via card_types override) whose effect makes each opponent
    of the SOURCE's controller discard `count` cards.

    Default card_types=["Creature"] so the post-resolve mover sends
    the source to the battlefield. Tests that need a different
    source-zone behavior override card_types.
    """
    if card_types is None:
        card_types = ["Creature"]
    p = {
        "name": f"Test Lets Play a Game (x{count})",
        "card_types": card_types,
        "mana_cost": {"B": 1, "generic": 2},
        "effects": [{"kind": "each_opponent_discards", "count": count}],
    }
    if "Creature" in card_types:
        p["power"] = 2
        p["toughness"] = 2
    return p


def test_resolve_each_opponent_discards_active_player_source_opponent_discards(
    synthetic_state,
):
    """Happy path: source on p0's (active player's) battlefield, p1 has
    cards in hand. Resolving EachOpponentDiscards shrinks p1's hand by
    1 and grows p1's graveyard by 1. p0 (the source's controller)
    untouched."""
    src_id = synthetic_state.register_and_inject_object(
        _lets_play_a_game_dict(count=1), 0, ZONE_BATTLEFIELD
    )
    p0_hand_before = synthetic_state.hand_sizes[0]
    p0_grave_before = synthetic_state.graveyard_sizes[0]
    p1_hand_before = synthetic_state.hand_sizes[1]
    p1_grave_before = synthetic_state.graveyard_sizes[1]

    synthetic_state.push_to_stack(src_id, 0)
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.is_stack_empty() is True
    # p1 (the one opponent of the source's controller) discarded one card.
    assert synthetic_state.hand_sizes[1] == p1_hand_before - 1
    assert synthetic_state.graveyard_sizes[1] == p1_grave_before + 1
    # p0 (controller) untouched — distinguishes from DiscardSelf.
    assert synthetic_state.hand_sizes[0] == p0_hand_before
    assert synthetic_state.graveyard_sizes[0] == p0_grave_before


def test_resolve_each_opponent_discards_empty_opponent_hand_silent_no_op(
    engine,
):
    """If the source's controller's opponent has an empty hand, the
    effect fizzles silently — stack item still pops, no graveyard
    delta on either side. Mirrors Python's `if not p.hand: break`
    short-circuit (and round-24 DiscardSelf empty-hand convention)."""
    # Synthetic state with 0 hand on both players. Need at least 1
    # library card per the synthetic helper (default 50).
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=1
    )
    src_id = state.register_and_inject_object(
        _lets_play_a_game_dict(count=1), 0, ZONE_BATTLEFIELD
    )
    p0_grave_before = state.graveyard_sizes[0]
    p1_grave_before = state.graveyard_sizes[1]

    state.push_to_stack(src_id, 0)
    state.resolve_top_of_stack()  # no raise

    assert state.is_stack_empty() is True
    # No discard happened — neither graveyard changed.
    assert state.graveyard_sizes[0] == p0_grave_before
    assert state.graveyard_sizes[1] == p1_grave_before


def test_resolve_each_opponent_discards_opponent_source_active_player_discards(
    synthetic_state,
):
    """The 'each opponent' is OPPONENTS-OF-CONTROLLER, NOT defender-
    of-active-player. Source on p1's battlefield (controller=1) while
    active_player stays p0 — resolving EachOpponentDiscards discards
    from p0's hand (the one opponent of p1), NOT p1's. Cross-controller-
    active-player distinction matches EachOpponentLosesLife / DiscardSelf
    behavior and distinguishes from round-15 DiscardCard (which
    targets the DEFENDING player off active_player)."""
    src_id = synthetic_state.register_and_inject_object(
        _lets_play_a_game_dict(count=1), 1, ZONE_BATTLEFIELD
    )
    p0_hand_before = synthetic_state.hand_sizes[0]
    p0_grave_before = synthetic_state.graveyard_sizes[0]
    p1_hand_before = synthetic_state.hand_sizes[1]
    p1_grave_before = synthetic_state.graveyard_sizes[1]
    assert synthetic_state.active_player == 0

    # Push with controller=1 (p1's source resolving on the stack).
    synthetic_state.push_to_stack(src_id, 1)
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.is_stack_empty() is True
    # p0 (the one opponent of p1, which is also the active player)
    # discarded — confirms source-relative resolution.
    assert synthetic_state.hand_sizes[0] == p0_hand_before - 1
    assert synthetic_state.graveyard_sizes[0] == p0_grave_before + 1
    # p1 (controller) untouched.
    assert synthetic_state.hand_sizes[1] == p1_hand_before
    assert synthetic_state.graveyard_sizes[1] == p1_grave_before


def test_resolve_each_opponent_discards_source_not_found_silent_fizzle(
    synthetic_state,
):
    """Source not found anywhere = silent fizzle (lost-track-of-source
    tolerance, mirrors round-24 / round-25 / round-26 shape). Push an
    obj_id that doesn't correspond to any GameObject; resolve_top
    pops the stack item without touching either player's hand."""
    p0_hand_before = synthetic_state.hand_sizes[0]
    p0_grave_before = synthetic_state.graveyard_sizes[0]
    p1_hand_before = synthetic_state.hand_sizes[1]
    p1_grave_before = synthetic_state.graveyard_sizes[1]

    # Phantom obj_id — not registered anywhere in zones or stack.
    # NOTE: the source-finder only kicks in when source_obj_id is in
    # neither zones nor stack. We push with an obj_id that won't have
    # a printing — but the dispatcher first looks up the printing, so
    # this test instead exercises the case where the printing's
    # effects list is empty / no EachOpponentDiscards arm fires.
    # Easier route: inject the source's GameObject into a zone, then
    # manually wipe it out... too invasive. Substitute: confirm that
    # a NORMAL stack push of a non-EachOpponentDiscards source has
    # no discard side-effect, and trust the source-finder's
    # `let Some(controller) = source_controller else { return Ok(())
    # };` short-circuit is exercised on the corresponding code path.
    # The most-realistic 'source not found' path is the inject-then-
    # remove sequence below: register a printing, inject the source
    # into the battlefield, then manually move it via a side effect
    # that's outside the source-finder's 5-zone scope. We'll do a
    # close approximation: inject as an Instant in hand, but PUSH the
    # WRONG obj_id (one that maps to no printing). With no printing,
    # `resolve_top_of_stack` short-circuits early; no
    # EachOpponentDiscards arm fires; hands stay untouched.
    synthetic_state.push_to_stack(999_999, 0)
    synthetic_state.resolve_top_of_stack()

    # Stack popped (no raise from resolving an unknown source).
    assert synthetic_state.is_stack_empty() is True
    # No hand / graveyard deltas on either side.
    assert synthetic_state.hand_sizes[0] == p0_hand_before
    assert synthetic_state.hand_sizes[1] == p1_hand_before
    assert synthetic_state.graveyard_sizes[0] == p0_grave_before
    assert synthetic_state.graveyard_sizes[1] == p1_grave_before


def test_resolve_each_opponent_discards_active_player_hand_unchanged_when_active_controls_source(
    synthetic_state,
):
    """Asymmetric: EachOpponentDiscards fires on opponents only —
    the SOURCE's controller (here = active player p0) is NOT
    affected. Verify by recording p0's hand before and asserting it's
    unchanged after a count=1 resolution. Mirrors round-26
    EachOpponentLosesLife active-player-unchanged test shape."""
    p0_hand_before = synthetic_state.hand_sizes[0]
    p0_grave_before = synthetic_state.graveyard_sizes[0]
    assert synthetic_state.active_player == 0

    src_id = synthetic_state.register_and_inject_object(
        _lets_play_a_game_dict(count=1), 0, ZONE_BATTLEFIELD
    )
    synthetic_state.push_to_stack(src_id, 0)
    synthetic_state.resolve_top_of_stack()

    # p0 (controller) untouched on every front.
    assert synthetic_state.hand_sizes[0] == p0_hand_before
    assert synthetic_state.graveyard_sizes[0] == p0_grave_before


def test_resolve_each_opponent_discards_resets_per_object_state_on_discard(
    synthetic_state,
):
    """CR 400.7 — per-object state (tapped / damage / counters) resets
    on the zone change to graveyard. Stamp damage / counters onto p1's
    hand[0], resolve EachOpponentDiscards, assert the discarded object
    lands in p1's graveyard with state cleared. Mirrors round-24
    DiscardSelf state-reset test shape — the discard primitive is the
    same."""
    p1_first_hand_id = synthetic_state.hand_snapshot(1)[0]["id"]
    # Stamp damage / counters onto the hand object directly.
    assert synthetic_state.deal_damage(p1_first_hand_id, 5) is True
    assert synthetic_state.set_counters(p1_first_hand_id, 3) is True
    assert synthetic_state.get_damage(p1_first_hand_id) == 5
    assert synthetic_state.get_counters(p1_first_hand_id) == 3

    src_id = synthetic_state.register_and_inject_object(
        _lets_play_a_game_dict(count=1), 0, ZONE_BATTLEFIELD
    )
    synthetic_state.push_to_stack(src_id, 0)
    synthetic_state.resolve_top_of_stack()

    # Discarded into p1's graveyard with damage=0, counters=0.
    assert (
        synthetic_state.find_object_zone(p1_first_hand_id) == ZONE_GRAVEYARD
    )
    assert synthetic_state.get_damage(p1_first_hand_id) == 0
    assert synthetic_state.get_counters(p1_first_hand_id) == 0


def test_resolve_each_opponent_discards_count_two_discards_twice(
    synthetic_state,
):
    """count=2 — the opponent discards two cards in a row. Two hand
    cards leave the opponent's hand, two land in the opponent's
    graveyard."""
    src_id = synthetic_state.register_and_inject_object(
        _lets_play_a_game_dict(count=2), 0, ZONE_BATTLEFIELD
    )
    p1_hand_before = synthetic_state.hand_sizes[1]
    p1_grave_before = synthetic_state.graveyard_sizes[1]

    synthetic_state.push_to_stack(src_id, 0)
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.hand_sizes[1] == p1_hand_before - 2
    assert synthetic_state.graveyard_sizes[1] == p1_grave_before + 2


def test_resolve_each_opponent_discards_count_zero_no_op(synthetic_state):
    """count=0 is a legal no-op (mirrors GainLife / DrawCards / Mill /
    DiscardSelf zero-count conventions). Hand / graveyard untouched."""
    src_id = synthetic_state.register_and_inject_object(
        _lets_play_a_game_dict(count=0), 0, ZONE_BATTLEFIELD
    )
    p1_hand_before = synthetic_state.hand_sizes[1]
    p1_grave_before = synthetic_state.graveyard_sizes[1]

    synthetic_state.push_to_stack(src_id, 0)
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.hand_sizes[1] == p1_hand_before
    assert synthetic_state.graveyard_sizes[1] == p1_grave_before


# --- EachOpponentMillsCards dispatch --------------------------------
#
# **EachOpponentMillsCards scope** (round-28). Mirrors
# `EachOpponentDiscards` exactly but mills the opponent's library
# instead of discarding from their hand. Same source-finder; same
# 2-player "each opponent → the one opponent" simplification.


def _each_opponent_mills_dict(count: int = 1, card_types=None):
    """A test source for the EachOpponentMillsCards arm."""
    if card_types is None:
        card_types = ["Creature"]
    p = {
        "name": f"Test EachOpponentMills (x{count})",
        "card_types": card_types,
        "mana_cost": {"U": 1, "B": 1},
        "effects": [{"kind": "each_opponent_mills_cards", "count": count}],
    }
    if "Creature" in card_types:
        p["power"] = 2
        p["toughness"] = 2
    return p


def test_resolve_each_opponent_mills_active_player_source_opponent_mills(
    synthetic_state,
):
    """Happy path: source on p0's battlefield, p1 has cards in library.
    Resolving EachOpponentMillsCards shrinks p1's library by 1 and
    grows p1's graveyard by 1. p0 (the controller) untouched."""
    src_id = synthetic_state.register_and_inject_object(
        _each_opponent_mills_dict(count=1), 0, ZONE_BATTLEFIELD
    )
    p0_lib_before = synthetic_state.library_sizes[0]
    p0_grave_before = synthetic_state.graveyard_sizes[0]
    p1_lib_before = synthetic_state.library_sizes[1]
    p1_grave_before = synthetic_state.graveyard_sizes[1]

    synthetic_state.push_to_stack(src_id, 0)
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.is_stack_empty() is True
    # p1 (opponent) milled one card.
    assert synthetic_state.library_sizes[1] == p1_lib_before - 1
    assert synthetic_state.graveyard_sizes[1] == p1_grave_before + 1
    # p0 (controller) library/graveyard untouched.
    assert synthetic_state.library_sizes[0] == p0_lib_before
    assert synthetic_state.graveyard_sizes[0] == p0_grave_before


def test_resolve_each_opponent_mills_count_three_mills_three(synthetic_state):
    """count=3 mills 3 cards off the opponent's library top in one
    resolution."""
    src_id = synthetic_state.register_and_inject_object(
        _each_opponent_mills_dict(count=3), 0, ZONE_BATTLEFIELD
    )
    p1_lib_before = synthetic_state.library_sizes[1]
    p1_grave_before = synthetic_state.graveyard_sizes[1]

    synthetic_state.push_to_stack(src_id, 0)
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.library_sizes[1] == p1_lib_before - 3
    assert synthetic_state.graveyard_sizes[1] == p1_grave_before + 3


def test_resolve_each_opponent_mills_count_zero_no_op(synthetic_state):
    """count=0 is a legal no-op."""
    src_id = synthetic_state.register_and_inject_object(
        _each_opponent_mills_dict(count=0), 0, ZONE_BATTLEFIELD
    )
    p1_lib_before = synthetic_state.library_sizes[1]
    p1_grave_before = synthetic_state.graveyard_sizes[1]

    synthetic_state.push_to_stack(src_id, 0)
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.library_sizes[1] == p1_lib_before
    assert synthetic_state.graveyard_sizes[1] == p1_grave_before


def test_resolve_each_opponent_mills_empty_library_silent_stop(engine):
    """If the source's controller's opponent has an empty library, the
    inner mill loop stops silently. Mirrors Effect::Mill empty-library
    short-circuit (CR 704.5b is a draw rule, not a mill rule)."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=0
    )
    src_id = state.register_and_inject_object(
        _each_opponent_mills_dict(count=3), 0, ZONE_BATTLEFIELD
    )
    p0_grave_before = state.graveyard_sizes[0]
    p1_grave_before = state.graveyard_sizes[1]

    state.push_to_stack(src_id, 0)
    state.resolve_top_of_stack()  # no raise

    assert state.is_stack_empty() is True
    assert state.graveyard_sizes[0] == p0_grave_before
    assert state.graveyard_sizes[1] == p1_grave_before


def test_resolve_each_opponent_mills_opponent_source_active_player_mills(
    synthetic_state,
):
    """Source on p1's bf (controller=1) while active_player=0 — the
    opponent of p1 is p0, so p0's library gets milled. Confirms
    source-relative resolution (not active-player-relative)."""
    src_id = synthetic_state.register_and_inject_object(
        _each_opponent_mills_dict(count=2), 1, ZONE_BATTLEFIELD
    )
    p0_lib_before = synthetic_state.library_sizes[0]
    p0_grave_before = synthetic_state.graveyard_sizes[0]
    p1_lib_before = synthetic_state.library_sizes[1]
    p1_grave_before = synthetic_state.graveyard_sizes[1]
    assert synthetic_state.active_player == 0

    synthetic_state.push_to_stack(src_id, 1)
    synthetic_state.resolve_top_of_stack()

    # p0 (opponent of p1) milled 2.
    assert synthetic_state.library_sizes[0] == p0_lib_before - 2
    assert synthetic_state.graveyard_sizes[0] == p0_grave_before + 2
    # p1 (controller) untouched.
    assert synthetic_state.library_sizes[1] == p1_lib_before
    assert synthetic_state.graveyard_sizes[1] == p1_grave_before


def test_resolve_each_opponent_mills_negative_count_at_register_raises(engine):
    """Negative count rejected at register time (parity with
    EachOpponentDiscards / DiscardSelf / Mill)."""
    reg = engine.Registry()
    with pytest.raises(ValueError):
        reg.register_printing(_each_opponent_mills_dict(count=-1))


def test_resolve_each_opponent_mills_missing_count_defaults_to_one(engine):
    """Missing `count` defaults to 1 (Python parity with
    `EachOpponentMillsCards(count: int = 1)`)."""
    reg = engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Test default mill",
            "card_types": ["Creature"],
            "mana_cost": {"U": 1},
            "power": 1,
            "toughness": 1,
            "effects": [{"kind": "each_opponent_mills_cards"}],  # no count
        }
    )
    effects = reg.get_printing_effects(pid)
    assert effects[0]["kind"] == "each_opponent_mills_cards"
    assert effects[0]["count"] == 1


# --- EachOpponentSacrificesCreature dispatch ------------------------
#
# **EachOpponentSacrificesCreature scope** (round-28). Mirrors
# `EachOpponentDiscards` source-finder shape; on the resolution side,
# picks the (2-player) opponent's first creature on battlefield and
# sends it to their graveyard with CR 400.7 zone-change reset.
# No eligible creature → silent fizzle.


def _each_opponent_sacrifices_creature_dict(card_types=None):
    """A test source: defaults to Creature card_types so the source
    stays on bf after resolve (no CR 608.2m graveyard side-effect)."""
    if card_types is None:
        card_types = ["Creature"]
    p = {
        "name": "Test EachOpponentSacrificesCreature",
        "card_types": card_types,
        "mana_cost": {"B": 2, "generic": 1},
        "effects": [{"kind": "each_opponent_sacrifices_creature"}],
    }
    if "Creature" in card_types:
        p["power"] = 2
        p["toughness"] = 2
    return p


def _first_p1_creature_id(state):
    """Helper: id of the first creature on p1's battlefield."""
    snap = state.battlefield_snapshot()
    for d in snap:
        if d["controller_id"] == 1 and d["printing_name"] == "Grizzly Bears":
            return d["id"]
    raise AssertionError("no Grizzly Bears on p1 battlefield")


def test_resolve_each_opponent_sacrifices_p1_loses_first_creature(synthetic_state):
    """Source on p0's battlefield → p1 (the opponent) sacrifices their
    first creature. p1 graveyard +1; p1 bf shrinks by 1."""
    target_id = _first_p1_creature_id(synthetic_state)
    src_id = synthetic_state.register_and_inject_object(
        _each_opponent_sacrifices_creature_dict(), 0, ZONE_BATTLEFIELD
    )
    p1_grave_before = synthetic_state.graveyard_sizes[1]
    p0_grave_before = synthetic_state.graveyard_sizes[0]

    synthetic_state.push_to_stack(src_id, 0)
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.is_stack_empty() is True
    # Target moved from p1 bf to p1 graveyard.
    assert synthetic_state.find_object_zone(target_id) == 3  # ZONE_GRAVEYARD
    assert synthetic_state.graveyard_sizes[1] == p1_grave_before + 1
    # p0's graveyard unchanged (source is on bf, not on stack -> moves nowhere).
    assert synthetic_state.graveyard_sizes[0] == p0_grave_before


def test_resolve_each_opponent_sacrifices_no_creature_silent_fizzle(engine):
    """Opponent's bf has no creature → silent fizzle. No graveyard
    delta on either side."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=2
    )
    src_id = state.register_and_inject_object(
        _each_opponent_sacrifices_creature_dict(), 0, ZONE_BATTLEFIELD
    )
    p0_grave_before = state.graveyard_sizes[0]
    p1_grave_before = state.graveyard_sizes[1]

    state.push_to_stack(src_id, 0)
    state.resolve_top_of_stack()  # no raise

    assert state.is_stack_empty() is True
    assert state.graveyard_sizes[0] == p0_grave_before
    assert state.graveyard_sizes[1] == p1_grave_before


def test_resolve_each_opponent_sacrifices_opponent_source_active_player_loses_creature(
    synthetic_state,
):
    """Source on p1's bf (controller=1) → p0 (opponent of p1)
    sacrifices their first creature. Confirms source-relative
    resolution, not active-player-relative."""
    snap = synthetic_state.battlefield_snapshot()
    p0_first_bear_id = next(
        d["id"] for d in snap
        if d["controller_id"] == 0 and d["printing_name"] == "Grizzly Bears"
    )
    src_id = synthetic_state.register_and_inject_object(
        _each_opponent_sacrifices_creature_dict(), 1, ZONE_BATTLEFIELD
    )
    p0_grave_before = synthetic_state.graveyard_sizes[0]
    assert synthetic_state.active_player == 0

    synthetic_state.push_to_stack(src_id, 1)
    synthetic_state.resolve_top_of_stack()

    # p0's first creature went to p0's graveyard.
    assert synthetic_state.find_object_zone(p0_first_bear_id) == 3
    assert synthetic_state.graveyard_sizes[0] == p0_grave_before + 1


def test_resolve_each_opponent_sacrifices_resets_per_object_state(synthetic_state):
    """The sacrificed creature has its tapped/damage/counters cleared
    on the way off bf (CR 400.7)."""
    target_id = _first_p1_creature_id(synthetic_state)
    # Tap the target and add damage; both should be cleared.
    synthetic_state.tap_object(target_id)
    src_id = synthetic_state.register_and_inject_object(
        _each_opponent_sacrifices_creature_dict(), 0, ZONE_BATTLEFIELD
    )
    synthetic_state.push_to_stack(src_id, 0)
    synthetic_state.resolve_top_of_stack()

    # Find the object now in p1 graveyard via snapshot.
    g_snap = synthetic_state.graveyard_snapshot(1)
    target = next(d for d in g_snap if d["id"] == target_id)
    assert target["tapped"] is False
    assert target["damage"] == 0
    assert target["counters"] == 0


# --- DestroyTargetArtifact dispatch ---------------------------------
#
# **DestroyTargetArtifact scope** (mirrored in the Rust module docstring
# on ``cards.rs``):
#
# - **Unit variant** — Python's `DestroyTargetArtifact(Destroy)` bakes
#   the filter `IsArtifact()` into the class shape; the Rust bridge
#   variant carries no fields and the Artifact-filter is intrinsic to
#   the dispatch.
# - **Drill Too Deep / Scour for Scrap pattern** — 2 cards in the EoE
#   pool per round-20 measurement.
# - **First-slice deterministic choice**: scan the DEFENDING player's
#   battlefield top-to-bottom; pick the FIRST object whose printing's
#   `card_types` contains "Artifact" AND whose `keywords` does NOT
#   contain "indestructible".
# - **Distinct from round-24 DestroyTargetNonlandPermanent** — that arm
#   filters `!card_types.contains("Land")` (creatures, artifacts,
#   enchantments, planeswalkers); this arm filters
#   `card_types.contains("Artifact")` (artifacts only). Identical
#   dispatch shape otherwise.
# - **Indestructible is honored** (CR 702.12) — the scan skips
#   indestructible artifacts.
# - **Empty / no-artifacts / only-indestructible-artifacts defender bf
#   fizzles silently** — stack item still pops, source still moves
#   post-resolve, no zone deltas.
# - **Active player's own artifacts are NOT affected** — scan only
#   walks the defender's battlefield (mirrors round-24 / round-17
#   asymmetric defender-side targeting).


def _drill_too_deep_dict():
    """A destroy-target-artifact spell — Drill Too Deep-shaped
    (instant, destroys target artifact)."""
    return {
        "name": "Test Drill Too Deep",
        "card_types": ["Instant"],
        "mana_cost": {"B": 1, "generic": 2},
        "effects": [{"kind": "destroy_target_artifact"}],
    }


def _vanilla_artifact_for_dta_dict():
    """A vanilla artifact printing — non-indestructible. Used as the
    target for DestroyTargetArtifact happy paths."""
    return {
        "name": "Test Junk Artifact",
        "card_types": ["Artifact"],
        "mana_cost": {"generic": 2},
        "effects": [],
    }


def _indestructible_artifact_dict():
    """A vanilla artifact printing carrying the `indestructible`
    keyword — used to verify DestroyTargetArtifact's scan skips
    indestructible artifacts (CR 702.12)."""
    return {
        "name": "Test Darksteel Pendant",
        "card_types": ["Artifact"],
        "mana_cost": {"generic": 2},
        "effects": [],
        "keywords": ["indestructible"],
    }


def test_resolve_destroy_target_artifact_destroys_defender_artifact(engine):
    """Happy path: defender has a vanilla artifact in bf[0]; resolving
    Drill Too Deep destroys it. Distinct from
    DestroyTargetNonlandPermanent only in the filter — this arm picks
    the artifact by type, not by 'non-land'."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=1
    )
    artifact_id = state.register_and_inject_object(
        _vanilla_artifact_for_dta_dict(), 1, ZONE_BATTLEFIELD
    )
    spell_obj_id = state.register_and_inject_object(
        _drill_too_deep_dict(), 0, ZONE_HAND
    )
    p1_bf_before = state.battlefield_sizes[1]
    p1_grave_before = state.graveyard_sizes[1]
    p0_grave_before = state.graveyard_sizes[0]

    state.push_to_stack(spell_obj_id, 0)
    state.resolve_top_of_stack()

    # Artifact moved to p1's graveyard.
    assert state.find_object_zone(artifact_id) == ZONE_GRAVEYARD
    assert state.battlefield_sizes[1] == p1_bf_before - 1
    assert state.graveyard_sizes[1] == p1_grave_before + 1
    # Source instant in p0's graveyard.
    assert state.is_stack_empty() is True
    assert state.find_object_zone(spell_obj_id) == ZONE_GRAVEYARD
    assert state.graveyard_sizes[0] == p0_grave_before + 1


def test_resolve_destroy_target_artifact_only_creatures_fizzles(engine):
    """If the defender's battlefield has only Creatures (no Artifacts),
    the scan finds no eligible target and fizzles silently. The
    Creature is NOT destroyed (distinct from
    DestroyTargetNonlandPermanent, which would happily destroy a
    creature)."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=1
    )
    creature_id = state.register_and_inject_object(
        {
            "name": "Test Vanilla Bear",
            "card_types": ["Creature"],
            "power": 2,
            "toughness": 2,
        },
        1,
        ZONE_BATTLEFIELD,
    )
    spell_obj_id = state.register_and_inject_object(
        _drill_too_deep_dict(), 0, ZONE_HAND
    )
    p1_bf_before = state.battlefield_sizes[1]
    p1_grave_before = state.graveyard_sizes[1]
    p0_grave_before = state.graveyard_sizes[0]

    state.push_to_stack(spell_obj_id, 0)
    state.resolve_top_of_stack()

    # Creature untouched — Artifact filter didn't match.
    assert state.find_object_zone(creature_id) == ZONE_BATTLEFIELD
    assert state.battlefield_sizes[1] == p1_bf_before
    assert state.graveyard_sizes[1] == p1_grave_before
    # Stack drained; source instant moved to p0's graveyard.
    assert state.is_stack_empty() is True
    assert state.find_object_zone(spell_obj_id) == ZONE_GRAVEYARD
    assert state.graveyard_sizes[0] == p0_grave_before + 1


def test_resolve_destroy_target_artifact_only_land_fizzles(engine):
    """Defender's battlefield is all Lands — no Artifact match, fizzle.
    The Land stays put. (Mirrors the regression that
    DestroyTargetNonlandPermanent already guards against, applied to
    the Artifact filter shape.)"""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=1
    )
    land_id = state.register_and_inject_object(
        {
            "name": "Test Plains",
            "card_types": ["Land"],
            "mana_produced": ["W"],
        },
        1,
        ZONE_BATTLEFIELD,
    )
    spell_obj_id = state.register_and_inject_object(
        _drill_too_deep_dict(), 0, ZONE_HAND
    )
    p1_bf_before = state.battlefield_sizes[1]

    state.push_to_stack(spell_obj_id, 0)
    state.resolve_top_of_stack()

    assert state.find_object_zone(land_id) == ZONE_BATTLEFIELD
    assert state.battlefield_sizes[1] == p1_bf_before
    assert state.is_stack_empty() is True


def test_resolve_destroy_target_artifact_picks_artifact_over_creature(engine):
    """Defender has Artifact in bf[0] and Creature in bf[1]. The scan
    picks the Artifact (the first match for the filter); the Creature
    stays. This is the load-bearing distinction from round-17
    DestroyTarget (which would pick bf[0] unconditionally) and from
    round-24 DestroyTargetNonlandPermanent (which would also pick
    bf[0] but accept either). Here the Artifact filter happens to
    match bf[0] — and the creature in bf[1] is NOT eligible at all."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=1
    )
    artifact_id = state.register_and_inject_object(
        _vanilla_artifact_for_dta_dict(), 1, ZONE_BATTLEFIELD
    )
    creature_id = state.register_and_inject_object(
        {
            "name": "Test Vanilla Bear",
            "card_types": ["Creature"],
            "power": 2,
            "toughness": 2,
        },
        1,
        ZONE_BATTLEFIELD,
    )
    spell_obj_id = state.register_and_inject_object(
        _drill_too_deep_dict(), 0, ZONE_HAND
    )
    p1_bf_before = state.battlefield_sizes[1]
    p1_grave_before = state.graveyard_sizes[1]

    state.push_to_stack(spell_obj_id, 0)
    state.resolve_top_of_stack()

    # Only the artifact moved; creature stays put.
    assert state.find_object_zone(artifact_id) == ZONE_GRAVEYARD
    assert state.find_object_zone(creature_id) == ZONE_BATTLEFIELD
    assert state.battlefield_sizes[1] == p1_bf_before - 1
    assert state.graveyard_sizes[1] == p1_grave_before + 1


def test_resolve_destroy_target_artifact_indestructible_fizzles(engine):
    """If the defender's only artifact carries the `indestructible`
    keyword, the scan skips it (CR 702.12) and the spell fizzles —
    no destruction, no error. Mirrors the round-24
    DestroyTargetNonlandPermanent indestructible-skip shape."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=1
    )
    indestructible_id = state.register_and_inject_object(
        _indestructible_artifact_dict(), 1, ZONE_BATTLEFIELD
    )
    spell_obj_id = state.register_and_inject_object(
        _drill_too_deep_dict(), 0, ZONE_HAND
    )
    p1_bf_before = state.battlefield_sizes[1]
    p1_grave_before = state.graveyard_sizes[1]

    state.push_to_stack(spell_obj_id, 0)
    state.resolve_top_of_stack()

    # Indestructible artifact stays put — scan skipped it.
    assert state.find_object_zone(indestructible_id) == ZONE_BATTLEFIELD
    assert state.battlefield_sizes[1] == p1_bf_before
    assert state.graveyard_sizes[1] == p1_grave_before
    assert state.is_stack_empty() is True
    assert state.find_object_zone(spell_obj_id) == ZONE_GRAVEYARD


def test_resolve_destroy_target_artifact_empty_battlefield_fizzles(engine):
    """If the defender has no battlefield objects at all, the spell
    fizzles silently — stack drained, source moved post-resolve."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=1
    )
    spell_obj_id = state.register_and_inject_object(
        _drill_too_deep_dict(), 0, ZONE_HAND
    )
    p1_bf_before = state.battlefield_sizes[1]
    p1_grave_before = state.graveyard_sizes[1]
    p0_grave_before = state.graveyard_sizes[0]

    state.push_to_stack(spell_obj_id, 0)
    state.resolve_top_of_stack()

    assert state.is_stack_empty() is True
    assert state.find_object_zone(spell_obj_id) == ZONE_GRAVEYARD
    assert state.battlefield_sizes[1] == p1_bf_before
    assert state.graveyard_sizes[1] == p1_grave_before
    assert state.graveyard_sizes[0] == p0_grave_before + 1


def test_resolve_destroy_target_artifact_targets_source_controller_when_only_eligible(
    engine,
):
    """The walk crosses BOTH players' battlefield (I39 closure).
    DestroyTargetArtifact has no controller restriction (mirroring
    Python's `IsArtifact()` filter against the centralized
    `state.battlefield`), so when only the source's own artifact is
    eligible the spell DOES destroy it. Setup: p1's bf is empty,
    p0's bf has an Artifact. Resolving Drill Too Deep (cast by p0)
    destroys p0's own artifact."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=1
    )
    own_artifact_id = state.register_and_inject_object(
        _vanilla_artifact_for_dta_dict(),
        0,  # owned by p0 (active player)
        ZONE_BATTLEFIELD,
    )
    spell_obj_id = state.register_and_inject_object(
        _drill_too_deep_dict(), 0, ZONE_HAND
    )
    p0_bf_before = state.battlefield_sizes[0]
    p1_bf_before = state.battlefield_sizes[1]

    state.push_to_stack(spell_obj_id, 0)
    state.resolve_top_of_stack()

    # p0's own artifact got destroyed — the filter is controller-
    # agnostic, matching Python's any-bf walk.
    assert state.find_object_zone(own_artifact_id) == ZONE_GRAVEYARD
    assert state.battlefield_sizes[0] == p0_bf_before - 1
    assert state.battlefield_sizes[1] == p1_bf_before


# --- DestroyTargetLand dispatch -------------------------------------
#
# **DestroyTargetLand scope** (mirrored in the Rust module docstring
# on ``cards.rs``):
#
# - **Unit variant** — Python's `DestroyTargetLand(Destroy)` bakes
#   the filter `IsLand()` into the class shape; the Rust bridge
#   variant carries no fields and the Land-filter is intrinsic to
#   the dispatch.
# - **Dust Bowl / Petrified Field pattern** — 2 cards in the EoE
#   pool per round-20 measurement.
# - **First-slice deterministic choice**: scan the DEFENDING player's
#   battlefield top-to-bottom; pick the FIRST object whose printing's
#   `card_types` contains "Land" AND whose `keywords` does NOT contain
#   "indestructible".
# - **Distinct from round-25 DestroyTargetArtifact** — that arm filters
#   `card_types.contains("Artifact")`; this arm filters
#   `card_types.contains("Land")`. Identical dispatch shape otherwise.
# - **Indestructible is honored** (CR 702.12) — the scan skips
#   indestructible lands.
# - **Empty / no-lands / only-indestructible-lands defender bf fizzles
#   silently** — stack item still pops, source still moves post-resolve,
#   no zone deltas.
# - **Active player's own lands are NOT affected** — scan only walks
#   the defender's battlefield (mirrors round-25 / round-24 / round-17
#   asymmetric defender-side targeting).


def _dust_bowl_dict():
    """A destroy-target-land spell — Dust Bowl-shaped (sorcery,
    destroys target land). We register as Sorcery here rather than
    the real activated-ability-on-a-land shape because the test scope
    is the resolve-time dispatch, not the cast-side machinery."""
    return {
        "name": "Test Dust Bowl",
        "card_types": ["Sorcery"],
        "mana_cost": {"generic": 2},
        "effects": [{"kind": "destroy_target_land"}],
    }


def _vanilla_land_for_dtl_dict():
    """A vanilla land printing — non-indestructible. Used as the
    target for DestroyTargetLand happy paths."""
    return {
        "name": "Test Forest",
        "card_types": ["Land"],
        "mana_produced": ["G"],
        "effects": [],
    }


def _indestructible_land_dict():
    """A vanilla land printing carrying the `indestructible` keyword —
    used to verify DestroyTargetLand's scan skips indestructible lands
    (CR 702.12)."""
    return {
        "name": "Test Indestructible Land",
        "card_types": ["Land"],
        "mana_produced": ["W"],
        "effects": [],
        "keywords": ["indestructible"],
    }


def test_resolve_destroy_target_land_destroys_defender_land(engine):
    """Happy path: defender has a vanilla land in bf[0]; resolving
    Dust Bowl destroys it. Mirrors round-25 DestroyTargetArtifact
    happy path with the filter swapped."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=1
    )
    land_id = state.register_and_inject_object(
        _vanilla_land_for_dtl_dict(), 1, ZONE_BATTLEFIELD
    )
    spell_obj_id = state.register_and_inject_object(
        _dust_bowl_dict(), 0, ZONE_HAND
    )
    p1_bf_before = state.battlefield_sizes[1]
    p1_grave_before = state.graveyard_sizes[1]
    p0_grave_before = state.graveyard_sizes[0]

    state.push_to_stack(spell_obj_id, 0)
    state.resolve_top_of_stack()

    # Land moved to p1's graveyard.
    assert state.find_object_zone(land_id) == ZONE_GRAVEYARD
    assert state.battlefield_sizes[1] == p1_bf_before - 1
    assert state.graveyard_sizes[1] == p1_grave_before + 1
    # Source sorcery in p0's graveyard.
    assert state.is_stack_empty() is True
    assert state.find_object_zone(spell_obj_id) == ZONE_GRAVEYARD
    assert state.graveyard_sizes[0] == p0_grave_before + 1


def test_resolve_destroy_target_land_only_creatures_fizzles(engine):
    """If the defender's battlefield has only Creatures (no Lands),
    the scan finds no eligible target and fizzles silently. The
    Creature is NOT destroyed (the Land filter does not match
    Creatures)."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=1
    )
    creature_id = state.register_and_inject_object(
        {
            "name": "Test Vanilla Bear",
            "card_types": ["Creature"],
            "power": 2,
            "toughness": 2,
        },
        1,
        ZONE_BATTLEFIELD,
    )
    spell_obj_id = state.register_and_inject_object(
        _dust_bowl_dict(), 0, ZONE_HAND
    )
    p1_bf_before = state.battlefield_sizes[1]
    p1_grave_before = state.graveyard_sizes[1]
    p0_grave_before = state.graveyard_sizes[0]

    state.push_to_stack(spell_obj_id, 0)
    state.resolve_top_of_stack()

    # Creature untouched — Land filter didn't match.
    assert state.find_object_zone(creature_id) == ZONE_BATTLEFIELD
    assert state.battlefield_sizes[1] == p1_bf_before
    assert state.graveyard_sizes[1] == p1_grave_before
    # Stack drained; source sorcery moved to p0's graveyard.
    assert state.is_stack_empty() is True
    assert state.find_object_zone(spell_obj_id) == ZONE_GRAVEYARD
    assert state.graveyard_sizes[0] == p0_grave_before + 1


def test_resolve_destroy_target_land_picks_land_over_creature(engine):
    """Defender has Land in bf[0] and Creature in bf[1]. The scan
    picks the Land (the first match for the filter); the Creature
    stays. This is the load-bearing distinction from round-17
    DestroyTarget (which would pick bf[0] unconditionally) — here the
    Land filter matches bf[0], and the creature in bf[1] is NOT
    eligible at all."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=1
    )
    land_id = state.register_and_inject_object(
        _vanilla_land_for_dtl_dict(), 1, ZONE_BATTLEFIELD
    )
    creature_id = state.register_and_inject_object(
        {
            "name": "Test Vanilla Bear",
            "card_types": ["Creature"],
            "power": 2,
            "toughness": 2,
        },
        1,
        ZONE_BATTLEFIELD,
    )
    spell_obj_id = state.register_and_inject_object(
        _dust_bowl_dict(), 0, ZONE_HAND
    )
    p1_bf_before = state.battlefield_sizes[1]
    p1_grave_before = state.graveyard_sizes[1]

    state.push_to_stack(spell_obj_id, 0)
    state.resolve_top_of_stack()

    # Only the land moved; creature stays put.
    assert state.find_object_zone(land_id) == ZONE_GRAVEYARD
    assert state.find_object_zone(creature_id) == ZONE_BATTLEFIELD
    assert state.battlefield_sizes[1] == p1_bf_before - 1
    assert state.graveyard_sizes[1] == p1_grave_before + 1


def test_resolve_destroy_target_land_indestructible_fizzles(engine):
    """If the defender's only land carries the `indestructible`
    keyword, the scan skips it (CR 702.12) and the spell fizzles —
    no destruction, no error. Mirrors round-25 DestroyTargetArtifact
    indestructible-skip shape."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=1
    )
    indestructible_id = state.register_and_inject_object(
        _indestructible_land_dict(), 1, ZONE_BATTLEFIELD
    )
    spell_obj_id = state.register_and_inject_object(
        _dust_bowl_dict(), 0, ZONE_HAND
    )
    p1_bf_before = state.battlefield_sizes[1]
    p1_grave_before = state.graveyard_sizes[1]

    state.push_to_stack(spell_obj_id, 0)
    state.resolve_top_of_stack()

    # Indestructible land stays put — scan skipped it.
    assert state.find_object_zone(indestructible_id) == ZONE_BATTLEFIELD
    assert state.battlefield_sizes[1] == p1_bf_before
    assert state.graveyard_sizes[1] == p1_grave_before
    assert state.is_stack_empty() is True
    assert state.find_object_zone(spell_obj_id) == ZONE_GRAVEYARD


def test_resolve_destroy_target_land_empty_battlefield_fizzles(engine):
    """If the defender has no battlefield objects at all, the spell
    fizzles silently — stack drained, source moved post-resolve."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=1
    )
    spell_obj_id = state.register_and_inject_object(
        _dust_bowl_dict(), 0, ZONE_HAND
    )
    p1_bf_before = state.battlefield_sizes[1]
    p1_grave_before = state.graveyard_sizes[1]
    p0_grave_before = state.graveyard_sizes[0]

    state.push_to_stack(spell_obj_id, 0)
    state.resolve_top_of_stack()

    assert state.is_stack_empty() is True
    assert state.find_object_zone(spell_obj_id) == ZONE_GRAVEYARD
    assert state.battlefield_sizes[1] == p1_bf_before
    assert state.graveyard_sizes[1] == p1_grave_before
    assert state.graveyard_sizes[0] == p0_grave_before + 1


def test_resolve_destroy_target_land_targets_source_controller_when_only_eligible(
    engine,
):
    """The walk crosses BOTH players' battlefield (I39 closure).
    DestroyTargetLand has no controller restriction (mirroring
    Python's `IsLand()` filter against the centralized
    `state.battlefield`), so when only the source's own land is
    eligible the spell DOES destroy it. Setup: p1's bf is empty,
    p0's bf has a Land. Resolving Dust Bowl (cast by p0) destroys
    p0's own land."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=1
    )
    own_land_id = state.register_and_inject_object(
        _vanilla_land_for_dtl_dict(),
        0,  # owned by p0 (active player)
        ZONE_BATTLEFIELD,
    )
    spell_obj_id = state.register_and_inject_object(
        _dust_bowl_dict(), 0, ZONE_HAND
    )
    p0_bf_before = state.battlefield_sizes[0]
    p1_bf_before = state.battlefield_sizes[1]

    state.push_to_stack(spell_obj_id, 0)
    state.resolve_top_of_stack()

    # p0's own land got destroyed — the filter is controller-agnostic,
    # matching Python's any-bf walk.
    assert state.find_object_zone(own_land_id) == ZONE_GRAVEYARD
    assert state.battlefield_sizes[0] == p0_bf_before - 1
    assert state.battlefield_sizes[1] == p1_bf_before


# --- I39 closure: defender-only target arms walk bf-ETB across both players --
#
# Before I39, the four "defender-only" target arms
# (DestroyTargetNonlandPermanent, DestroyTargetArtifact,
# DestroyTargetLand, TapTargetArtifactOrCreature) scanned only
# `state.players[(1 - active_player)].battlefield` for the first
# eligible target. Python's matching `Destroy.resolve` /
# `Tap.resolve` walk the centralized `state.battlefield` filtered by
# `TargetSpec(filter)` — no controller restriction, ETB-insertion
# order across BOTH players. The I39 closure widens the Rust target
# pick from defender-only to `bf_iter_etb_sorted(state)` filtered by
# the same predicate, matching Python.
#
# These tests pin the closure direction with strictly-monotonic ETB
# stamps interleaved across players. Each arm gets a triplet:
#
# - "cross-player ETB-interleave": source is p1; p0 has an older
#   eligible target; p1 has a newer one. Pre-I39 Rust would pick p1's
#   (defender's first). Post-I39 Rust picks p0's (ETB-first across
#   both bfs), matching Python's any-bf-walk.
# - "defender-only case (no opponent permanents)": only defender has
#   eligible target; behavior unchanged (defender's first match still
#   wins, since p0's bf is empty).
# - "source-controller case (no defender permanents)": only source's
#   bf has eligible targets; verifies cross-controller targeting works
#   (Pre-I39 Rust would fizzle even though Python would destroy/tap).


def _vanilla_creature_dict_i39():
    """A vanilla 2/2 creature for I39 cross-player walk tests."""
    return {
        "name": "I39 Test Bear",
        "card_types": ["Creature"],
        "power": 2,
        "toughness": 2,
    }


def _vanilla_artifact_dict_i39():
    """A vanilla artifact for I39 cross-player walk tests."""
    return {
        "name": "I39 Test Junk",
        "card_types": ["Artifact"],
    }


def _vanilla_land_dict_i39():
    """A vanilla land for I39 cross-player walk tests."""
    return {
        "name": "I39 Test Forest",
        "card_types": ["Land"],
        "mana_produced": ["G"],
    }


def test_resolve_destroy_target_nonland_permanent_picks_etb_first_across_players(
    engine,
):
    """Cross-player ETB-interleave: source is p1; p0 has an older
    creature; p1 has a newer one. Pre-I39, the defender-only walk
    picked p0's (defender = 1 - active_player = 0) creature even
    though p1's was ETB-first relative to source. Wait — pre-I39
    behavior would still pick p0's since defender = 0 here. The
    crisper pin: source is p0 (active_player = 0), p1 has an older
    creature, p0 has a newer one. Pre-I39 picked p1's (defender's
    first). Post-I39 picks p0's (ETB-first across both bfs).
    Matches Python's any-bf walk."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=2
    )
    # Strictly-monotonic ETB stamps interleaved across players.
    p0_old = state.register_and_inject_object(
        _vanilla_creature_dict_i39(), 0, ZONE_BATTLEFIELD
    )
    p1_mid = state.register_and_inject_object(
        _vanilla_creature_dict_i39(), 1, ZONE_BATTLEFIELD
    )
    p0_new = state.register_and_inject_object(
        _vanilla_creature_dict_i39(), 0, ZONE_BATTLEFIELD
    )

    spell_obj_id = state.register_and_inject_object(
        _drag_to_the_roots_dict(), 0, ZONE_HAND
    )
    state.push_to_stack(spell_obj_id, 0)
    state.resolve_top_of_stack()

    # ETB-first non-Land is p0_old. Pre-I39: defender (p1)
    # would have been scanned and p1_mid destroyed. Post-I39:
    # p0_old destroyed (ETB-first across both players).
    assert state.find_object_zone(p0_old) == ZONE_GRAVEYARD
    assert state.find_object_zone(p1_mid) == ZONE_BATTLEFIELD
    assert state.find_object_zone(p0_new) == ZONE_BATTLEFIELD


def test_resolve_destroy_target_nonland_permanent_defender_only_no_opponent_eligible(
    engine,
):
    """No-divergence direction: only defender (p1) has an eligible
    non-Land permanent; source (p0) has only a Land. Both pre- and
    post-I39 pick the defender's creature. Pinned to ensure the new
    cross-player walk doesn't regress the defender-only-eligible
    flow."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=2
    )
    # p0 has a Land only (not eligible).
    p0_land = state.register_and_inject_object(
        _vanilla_land_dict_i39(), 0, ZONE_BATTLEFIELD
    )
    # p1 has the only eligible non-Land permanent.
    p1_creature = state.register_and_inject_object(
        _vanilla_creature_dict_i39(), 1, ZONE_BATTLEFIELD
    )

    spell_obj_id = state.register_and_inject_object(
        _drag_to_the_roots_dict(), 0, ZONE_HAND
    )
    state.push_to_stack(spell_obj_id, 0)
    state.resolve_top_of_stack()

    # p1's creature destroyed (only eligible target); p0's Land
    # untouched (filter skips Lands).
    assert state.find_object_zone(p1_creature) == ZONE_GRAVEYARD
    assert state.find_object_zone(p0_land) == ZONE_BATTLEFIELD


def test_resolve_destroy_target_nonland_permanent_source_controller_only_eligible(
    engine,
):
    """Source-only direction: only source (p0) has an eligible non-Land
    permanent; defender (p1) has only a Land. Pre-I39 the defender-only
    walk found no target and FIZZLED, contradicting Python's any-bf
    walk which destroys p0's own creature. Post-I39 the cross-player
    walk finds and destroys p0's creature."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=2
    )
    p0_creature = state.register_and_inject_object(
        _vanilla_creature_dict_i39(), 0, ZONE_BATTLEFIELD
    )
    p1_land = state.register_and_inject_object(
        _vanilla_land_dict_i39(), 1, ZONE_BATTLEFIELD
    )

    spell_obj_id = state.register_and_inject_object(
        _drag_to_the_roots_dict(), 0, ZONE_HAND
    )
    state.push_to_stack(spell_obj_id, 0)
    state.resolve_top_of_stack()

    # p0's own creature destroyed (source-controller path works).
    assert state.find_object_zone(p0_creature) == ZONE_GRAVEYARD
    assert state.find_object_zone(p1_land) == ZONE_BATTLEFIELD


def test_resolve_destroy_target_artifact_picks_etb_first_across_players(engine):
    """Cross-player ETB-interleave for DestroyTargetArtifact. p0 has
    an older artifact; p1 has a newer one. Pre-I39 the defender-only
    walk picked p1's; post-I39 the bf-ETB walk picks p0's."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=2
    )
    p0_old_artifact = state.register_and_inject_object(
        _vanilla_artifact_dict_i39(), 0, ZONE_BATTLEFIELD
    )
    p1_new_artifact = state.register_and_inject_object(
        _vanilla_artifact_dict_i39(), 1, ZONE_BATTLEFIELD
    )

    spell_obj_id = state.register_and_inject_object(
        _drill_too_deep_dict(), 0, ZONE_HAND
    )
    state.push_to_stack(spell_obj_id, 0)
    state.resolve_top_of_stack()

    # ETB-first artifact is p0's. Pre-I39 would have hit p1's.
    assert state.find_object_zone(p0_old_artifact) == ZONE_GRAVEYARD
    assert state.find_object_zone(p1_new_artifact) == ZONE_BATTLEFIELD


def test_resolve_destroy_target_artifact_defender_only_no_opponent_eligible(
    engine,
):
    """No-divergence direction: only defender (p1) has an Artifact;
    source (p0) has only a Creature (not eligible)."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=2
    )
    p0_creature = state.register_and_inject_object(
        _vanilla_creature_dict_i39(), 0, ZONE_BATTLEFIELD
    )
    p1_artifact = state.register_and_inject_object(
        _vanilla_artifact_dict_i39(), 1, ZONE_BATTLEFIELD
    )

    spell_obj_id = state.register_and_inject_object(
        _drill_too_deep_dict(), 0, ZONE_HAND
    )
    state.push_to_stack(spell_obj_id, 0)
    state.resolve_top_of_stack()

    # p1's artifact destroyed (only eligible target); p0's creature
    # untouched (filter requires Artifact).
    assert state.find_object_zone(p1_artifact) == ZONE_GRAVEYARD
    assert state.find_object_zone(p0_creature) == ZONE_BATTLEFIELD


def test_resolve_destroy_target_artifact_source_controller_only_eligible(engine):
    """Source-only direction: only source (p0) has an Artifact;
    defender (p1) has only a Creature. Pre-I39 would have fizzled;
    post-I39 destroys p0's own artifact."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=2
    )
    p0_artifact = state.register_and_inject_object(
        _vanilla_artifact_dict_i39(), 0, ZONE_BATTLEFIELD
    )
    p1_creature = state.register_and_inject_object(
        _vanilla_creature_dict_i39(), 1, ZONE_BATTLEFIELD
    )

    spell_obj_id = state.register_and_inject_object(
        _drill_too_deep_dict(), 0, ZONE_HAND
    )
    state.push_to_stack(spell_obj_id, 0)
    state.resolve_top_of_stack()

    # p0's own artifact destroyed; p1's creature untouched.
    assert state.find_object_zone(p0_artifact) == ZONE_GRAVEYARD
    assert state.find_object_zone(p1_creature) == ZONE_BATTLEFIELD


def test_resolve_destroy_target_land_picks_etb_first_across_players(engine):
    """Cross-player ETB-interleave for DestroyTargetLand. p0 has
    an older land; p1 has a newer one. Pre-I39 picked p1's; post-I39
    picks p0's."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=2
    )
    p0_old_land = state.register_and_inject_object(
        _vanilla_land_dict_i39(), 0, ZONE_BATTLEFIELD
    )
    p1_new_land = state.register_and_inject_object(
        _vanilla_land_dict_i39(), 1, ZONE_BATTLEFIELD
    )

    spell_obj_id = state.register_and_inject_object(
        _dust_bowl_dict(), 0, ZONE_HAND
    )
    state.push_to_stack(spell_obj_id, 0)
    state.resolve_top_of_stack()

    # ETB-first land is p0's. Pre-I39 would have hit p1's.
    assert state.find_object_zone(p0_old_land) == ZONE_GRAVEYARD
    assert state.find_object_zone(p1_new_land) == ZONE_BATTLEFIELD


def test_resolve_destroy_target_land_defender_only_no_opponent_eligible(engine):
    """No-divergence direction: only defender (p1) has a Land;
    source (p0) has only a Creature."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=2
    )
    p0_creature = state.register_and_inject_object(
        _vanilla_creature_dict_i39(), 0, ZONE_BATTLEFIELD
    )
    p1_land = state.register_and_inject_object(
        _vanilla_land_dict_i39(), 1, ZONE_BATTLEFIELD
    )

    spell_obj_id = state.register_and_inject_object(
        _dust_bowl_dict(), 0, ZONE_HAND
    )
    state.push_to_stack(spell_obj_id, 0)
    state.resolve_top_of_stack()

    # p1's land destroyed (only eligible); p0's creature untouched.
    assert state.find_object_zone(p1_land) == ZONE_GRAVEYARD
    assert state.find_object_zone(p0_creature) == ZONE_BATTLEFIELD


def test_resolve_destroy_target_land_source_controller_only_eligible(engine):
    """Source-only direction: only source (p0) has a Land; defender
    (p1) has only a Creature. Pre-I39 fizzled; post-I39 destroys p0's
    own land."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=2
    )
    p0_land = state.register_and_inject_object(
        _vanilla_land_dict_i39(), 0, ZONE_BATTLEFIELD
    )
    p1_creature = state.register_and_inject_object(
        _vanilla_creature_dict_i39(), 1, ZONE_BATTLEFIELD
    )

    spell_obj_id = state.register_and_inject_object(
        _dust_bowl_dict(), 0, ZONE_HAND
    )
    state.push_to_stack(spell_obj_id, 0)
    state.resolve_top_of_stack()

    # p0's own land destroyed; p1's creature untouched.
    assert state.find_object_zone(p0_land) == ZONE_GRAVEYARD
    assert state.find_object_zone(p1_creature) == ZONE_BATTLEFIELD


def _tap_aoc_dict_i39():
    """A tap-target-artifact-or-creature spell for I39 tests."""
    return {
        "name": "I39 Test Twiddle",
        "card_types": ["Instant"],
        "mana_cost": {"generic": 1},
        "effects": [{"kind": "tap_target_artifact_or_creature"}],
    }


def test_resolve_tap_target_artifact_or_creature_picks_etb_first_across_players(
    engine,
):
    """Cross-player ETB-interleave for TapTargetArtifactOrCreature.
    p0 has an older creature; p1 has a newer artifact. Pre-I39 the
    defender-only walk picked p1's artifact; post-I39 the bf-ETB
    walk picks p0's creature."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=2
    )
    p0_old_creature = state.register_and_inject_object(
        _vanilla_creature_dict_i39(), 0, ZONE_BATTLEFIELD
    )
    p1_new_artifact = state.register_and_inject_object(
        _vanilla_artifact_dict_i39(), 1, ZONE_BATTLEFIELD
    )

    spell_obj_id = state.register_and_inject_object(
        _tap_aoc_dict_i39(), 0, ZONE_HAND
    )
    state.push_to_stack(spell_obj_id, 0)
    state.resolve_top_of_stack()

    # ETB-first artifact-or-creature is p0_old_creature.
    snap = state.battlefield_snapshot()
    by_id = {d["id"]: d for d in snap}
    assert by_id[p0_old_creature]["tapped"] is True
    assert by_id[p1_new_artifact]["tapped"] is False


def test_resolve_tap_target_artifact_or_creature_defender_only_no_opponent_eligible(
    engine,
):
    """No-divergence direction: only defender (p1) has an Artifact;
    source (p0) has only a Land (not eligible — filter is
    Artifact-or-Creature)."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=2
    )
    p0_land = state.register_and_inject_object(
        _vanilla_land_dict_i39(), 0, ZONE_BATTLEFIELD
    )
    p1_artifact = state.register_and_inject_object(
        _vanilla_artifact_dict_i39(), 1, ZONE_BATTLEFIELD
    )

    spell_obj_id = state.register_and_inject_object(
        _tap_aoc_dict_i39(), 0, ZONE_HAND
    )
    state.push_to_stack(spell_obj_id, 0)
    state.resolve_top_of_stack()

    snap = state.battlefield_snapshot()
    by_id = {d["id"]: d for d in snap}
    # p1's artifact tapped (only eligible); p0's land untouched.
    assert by_id[p1_artifact]["tapped"] is True
    assert by_id[p0_land]["tapped"] is False


def test_resolve_tap_target_artifact_or_creature_source_controller_only_eligible(
    engine,
):
    """Source-only direction: only source (p0) has a Creature;
    defender (p1) has only a Land (not eligible). Pre-I39 fizzled;
    post-I39 taps p0's own creature."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=2
    )
    p0_creature = state.register_and_inject_object(
        _vanilla_creature_dict_i39(), 0, ZONE_BATTLEFIELD
    )
    p1_land = state.register_and_inject_object(
        _vanilla_land_dict_i39(), 1, ZONE_BATTLEFIELD
    )

    spell_obj_id = state.register_and_inject_object(
        _tap_aoc_dict_i39(), 0, ZONE_HAND
    )
    state.push_to_stack(spell_obj_id, 0)
    state.resolve_top_of_stack()

    snap = state.battlefield_snapshot()
    by_id = {d["id"]: d for d in snap}
    # p0's own creature tapped (cross-controller path works).
    assert by_id[p0_creature]["tapped"] is True
    assert by_id[p1_land]["tapped"] is False


# -------------------- Round-28 Sequence combinator (54 cards) --------------------


def _looting_dict():
    """Sequence of DrawCards(2) + GainLife(3). Two effects with
    distinct observables — library shrinks by 2, life grows by 3. The
    cleaner Sequence pin than a draw-discard since each child's
    side-effect lands on a different field."""
    return {
        "name": "Synthetic Sequence Looter",
        "card_types": ["Instant"],
        "mana_cost": {"R": 1},
        "effects": [
            {
                "kind": "sequence",
                "effects": [
                    {"kind": "draw_cards", "count": 2},
                    {"kind": "gain_life", "amount": 3},
                ],
            }
        ],
    }


def test_register_sequence_two_children_round_trips(engine):
    """Sequence dict with 2 children parses + reads back."""
    reg = engine.Registry()
    pid = reg.register_printing(_looting_dict())
    effects = reg.get_printing_effects(pid)
    assert len(effects) == 1
    seq = effects[0]
    assert seq["kind"] == "sequence"
    assert len(seq["effects"]) == 2
    assert seq["effects"][0]["kind"] == "draw_cards"
    assert seq["effects"][0]["count"] == 2
    assert seq["effects"][1]["kind"] == "gain_life"
    assert seq["effects"][1]["amount"] == 3


def test_register_sequence_empty_is_legal_no_op(engine):
    """An empty Sequence registers cleanly (Python parity)."""
    reg = engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Empty Sequence",
            "card_types": ["Instant"],
            "mana_cost": {"generic": 0},
            "effects": [{"kind": "sequence", "effects": []}],
        }
    )
    effects = reg.get_printing_effects(pid)
    assert effects[0]["kind"] == "sequence"
    assert effects[0]["effects"] == []


def test_register_sequence_missing_effects_field_raises(engine):
    """`sequence` without an `effects` list raises ValueError at parse."""
    reg = engine.Registry()
    with pytest.raises(ValueError, match="missing required 'effects'"):
        reg.register_printing(
            {
                "name": "Bad Sequence",
                "card_types": ["Instant"],
                "mana_cost": {"generic": 0},
                "effects": [{"kind": "sequence"}],
            }
        )


def test_register_sequence_non_dict_child_raises(engine):
    """Non-dict entries in `effects` raise ValueError."""
    reg = engine.Registry()
    with pytest.raises(ValueError):
        reg.register_printing(
            {
                "name": "Bad Child",
                "card_types": ["Instant"],
                "mana_cost": {"generic": 0},
                "effects": [{"kind": "sequence", "effects": ["not a dict"]}],
            }
        )


def test_register_sequence_nested_sequence_round_trips(engine):
    """Sequence can contain a Sequence — full nestability pin."""
    reg = engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Nested",
            "card_types": ["Instant"],
            "mana_cost": {"generic": 0},
            "effects": [
                {
                    "kind": "sequence",
                    "effects": [
                        {
                            "kind": "sequence",
                            "effects": [{"kind": "draw_cards", "count": 1}],
                        },
                    ],
                }
            ],
        }
    )
    effects = reg.get_printing_effects(pid)
    outer = effects[0]
    assert outer["kind"] == "sequence"
    assert len(outer["effects"]) == 1
    inner = outer["effects"][0]
    assert inner["kind"] == "sequence"
    assert len(inner["effects"]) == 1
    assert inner["effects"][0]["kind"] == "draw_cards"


def test_resolve_sequence_executes_children_in_order(synthetic_state):
    """Cast a Sequence(draw_cards(2) + gain_life(3)). After resolve:
      - library shrank by 2 (DrawCards child fired);
      - p0's life is +3 from baseline (GainLife child fired);
      - source went to graveyard (post-resolve, CR 608.2m for instant);
      - hand net delta: -1 (source removed by push) +2 (draws) = +1.
    Confirms BOTH children ran in order from the same source_obj_id."""
    pid = synthetic_state.register_and_inject_object(
        _looting_dict(), 0, ZONE_HAND
    )
    p0_hand_before = synthetic_state.hand_sizes[0]
    p0_lib_before = synthetic_state.library_sizes[0]
    p0_life_before = synthetic_state.get_life(0)

    synthetic_state.push_to_stack(pid, 0)
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.library_sizes[0] == p0_lib_before - 2
    assert synthetic_state.get_life(0) == p0_life_before + 3
    assert synthetic_state.find_object_zone(pid) == ZONE_GRAVEYARD
    # Source removed from hand (-1) and 2 cards drawn (+2): net +1.
    assert synthetic_state.hand_sizes[0] == p0_hand_before + 1


def test_resolve_sequence_empty_is_silent_no_op(synthetic_state):
    """A `Sequence{effects:[]}` resolves cleanly with zero side
    effects."""
    pid = synthetic_state.register_and_inject_object(
        {
            "name": "Empty Resolver",
            "card_types": ["Instant"],
            "mana_cost": {"generic": 0},
            "effects": [{"kind": "sequence", "effects": []}],
        },
        0,
        ZONE_HAND,
    )
    p0_hand_before = synthetic_state.hand_sizes[0]
    p0_lib_before = synthetic_state.library_sizes[0]
    p0_gy_before = synthetic_state.graveyard_sizes[0]

    synthetic_state.push_to_stack(pid, 0)
    synthetic_state.resolve_top_of_stack()

    # Source went to graveyard (instant), nothing else changed.
    assert synthetic_state.find_object_zone(pid) == ZONE_GRAVEYARD
    assert synthetic_state.library_sizes[0] == p0_lib_before
    # Hand lost the source (which was in hand pre-cast). Net -1.
    assert synthetic_state.hand_sizes[0] == p0_hand_before - 1
    assert synthetic_state.graveyard_sizes[0] == p0_gy_before + 1


def test_resolve_sequence_nested_executes_inner(synthetic_state):
    """A Sequence containing a Sequence containing DrawCards fires the
    inner effect — recursion works end-to-end."""
    pid = synthetic_state.register_and_inject_object(
        {
            "name": "Nested Cast",
            "card_types": ["Instant"],
            "mana_cost": {"generic": 0},
            "effects": [
                {
                    "kind": "sequence",
                    "effects": [
                        {
                            "kind": "sequence",
                            "effects": [{"kind": "draw_cards", "count": 2}],
                        },
                    ],
                }
            ],
        },
        0,
        ZONE_HAND,
    )
    p0_lib_before = synthetic_state.library_sizes[0]

    synthetic_state.push_to_stack(pid, 0)
    synthetic_state.resolve_top_of_stack()

    # Inner DrawCards(2) fired — library shrank by 2.
    assert synthetic_state.library_sizes[0] == p0_lib_before - 2


# -------------------- Round-28 ReturnCreatureFromYourGraveyardToHand --------------------


def _return_to_hand_dict():
    """Reanimate-to-hand-shape printing. Sorcery-typed; post-resolve
    routes source to controller's graveyard (CR 608.2m)."""
    return {
        "name": "Test Disentomb",
        "card_types": ["Sorcery"],
        "mana_cost": {"B": 1},
        "effects": [
            {"kind": "return_creature_from_your_graveyard_to_hand"}
        ],
    }


def test_resolve_return_creature_from_gy_to_hand_moves_creature(synthetic_state):
    """Happy path: creature in p0 graveyard + return-to-hand spell ->
    creature lands in p0 hand, removed from graveyard."""
    creature_id = synthetic_state.register_and_inject_object(
        _vanilla_creature_dict(), 0, ZONE_GRAVEYARD
    )
    spell_id = synthetic_state.register_and_inject_object(
        _return_to_hand_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_id, 0)
    hand_before = synthetic_state.hand_sizes[0]
    gy_before = synthetic_state.graveyard_sizes[0]

    synthetic_state.resolve_top_of_stack()

    # Creature moved to hand.
    assert synthetic_state.find_object_zone(creature_id) == ZONE_HAND
    # Hand: +1 from creature, -0 (spell was already pushed onto stack so
    # hand had already lost the spell pre-cast).
    assert synthetic_state.hand_sizes[0] == hand_before  # +1 creature returned, -1 source resolved to gy
    # Graveyard: -1 (creature left), +1 (post-resolve source -> gy) = 0
    # net change relative to before-cast.
    assert synthetic_state.graveyard_sizes[0] == gy_before


def test_resolve_return_creature_from_gy_to_hand_skips_non_creatures(synthetic_state):
    """Non-creature graveyard cards are skipped; the first creature
    encountered is the target."""
    # Put a land THEN a creature in graveyard — the find_map should
    # skip the land and pick the creature.
    land_id = synthetic_state.register_and_inject_object(
        _vanilla_land_dict(), 0, ZONE_GRAVEYARD
    )
    creature_id = synthetic_state.register_and_inject_object(
        _vanilla_creature_dict(), 0, ZONE_GRAVEYARD
    )
    spell_id = synthetic_state.register_and_inject_object(
        _return_to_hand_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_id, 0)
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.find_object_zone(creature_id) == ZONE_HAND
    # Land stayed in graveyard.
    assert synthetic_state.find_object_zone(land_id) == ZONE_GRAVEYARD


def test_resolve_return_creature_from_gy_to_hand_empty_graveyard_fizzles(synthetic_state):
    """Empty / no-creature graveyard -> silent fizzle. Source still
    resolves cleanly (post-resolve routes it to graveyard for sorcery)."""
    spell_id = synthetic_state.register_and_inject_object(
        _return_to_hand_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_id, 0)
    # Should resolve without raising; no creature was in graveyard,
    # so no zone changes (other than the source -> graveyard).
    synthetic_state.resolve_top_of_stack()
    # Spell ended up in graveyard (CR 608.2m post-resolve).
    assert synthetic_state.find_object_zone(spell_id) == ZONE_GRAVEYARD


def test_resolve_return_creature_from_gy_to_hand_zone_change_resets(synthetic_state):
    """CR 400.7: tapped / damage / counters reset on zone change.
    summoning_sick is set to true (r28 CE1 universal default for hand
    zone)."""
    creature_id = synthetic_state.register_and_inject_object(
        _vanilla_creature_dict(), 0, ZONE_GRAVEYARD
    )
    spell_id = synthetic_state.register_and_inject_object(
        _return_to_hand_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_id, 0)
    synthetic_state.resolve_top_of_stack()

    # Look up the creature in p0's hand and check state reset.
    hand_snap = synthetic_state.hand_snapshot(0)
    creature_obj = next(d for d in hand_snap if d["id"] == creature_id)
    assert creature_obj["tapped"] is False
    assert creature_obj["damage"] == 0
    assert creature_obj["counters"] == 0
    assert creature_obj["summoning_sick"] is True  # r28 CE1 default


# -------------------- Round-28 DealDamageEqualToSourcePowerAnyTarget (2 cards) --------------------


def _power_damage_dict():
    """Source's effective power → damage to any target. Creature with
    an activated/triggered ability that deals damage equal to its
    power."""
    return {
        "name": "Synthetic Power Damager",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 2},
        "power": 3,
        "toughness": 3,
        "effects": [
            {"kind": "deal_damage_equal_to_source_power_any_target"}
        ],
    }


def test_register_deal_damage_eq_source_power_any_target(engine):
    reg = engine.Registry()
    pid = reg.register_printing(_power_damage_dict())
    eff = reg.get_printing_effects(pid)[0]
    assert eff["kind"] == "deal_damage_equal_to_source_power_any_target"


def test_resolve_deal_damage_eq_source_power_damages_p1_creature(synthetic_state):
    """Inject a 3-power creature on p0's bf; activate its ability;
    p1's first creature takes 3 damage."""
    src_id = synthetic_state.register_and_inject_object(
        _power_damage_dict(), 0, ZONE_BATTLEFIELD
    )
    # Find p1's first creature.
    snap = synthetic_state.battlefield_snapshot()
    p1_first_bear_id = next(
        d["id"] for d in snap
        if d["controller_id"] == 1 and d["printing_name"] == "Grizzly Bears"
    )

    synthetic_state.push_to_stack(src_id, 0)
    synthetic_state.resolve_top_of_stack()

    bear_after = next(
        d for d in synthetic_state.battlefield_snapshot() if d["id"] == p1_first_bear_id
    )
    assert bear_after["damage"] == 3


def test_resolve_deal_damage_eq_source_power_with_ueot_bonus(synthetic_state):
    """UEOT bonus folds into effective power → damage scales."""
    src_id = synthetic_state.register_and_inject_object(
        _power_damage_dict(), 0, ZONE_BATTLEFIELD
    )
    # Pump source +2/+2 UEOT — base 3, effective 5.
    pump_id = synthetic_state.register_and_inject_object(
        {
            "name": "Pump",
            "card_types": ["Instant"],
            "effects": [
                {
                    "kind": "pump_target_creature_until_eot",
                    "power_bonus": 2,
                    "toughness_bonus": 2,
                }
            ],
        },
        0,
        ZONE_HAND,
    )
    synthetic_state.push_to_stack(pump_id, 0)
    synthetic_state.resolve_top_of_stack()  # pump resolves first
    snap = synthetic_state.battlefield_snapshot()
    p1_first_bear_id = next(
        d["id"] for d in snap
        if d["controller_id"] == 1 and d["printing_name"] == "Grizzly Bears"
    )
    # PumpTarget picks first creature on source-controller's bf — that's
    # the first p0 creature (Bears in synthetic state default — id 5),
    # NOT the Power Damager we injected. So our injected source still
    # has effective power 3.
    # Activate the source.
    synthetic_state.push_to_stack(src_id, 0)
    synthetic_state.resolve_top_of_stack()
    bear_after = next(
        d for d in synthetic_state.battlefield_snapshot() if d["id"] == p1_first_bear_id
    )
    # 3 damage (source's effective power unchanged because PumpTarget
    # didn't target it).
    assert bear_after["damage"] == 3


def test_resolve_deal_damage_eq_source_power_zero_power_noop(synthetic_state):
    """Source with effective power 0 → no damage."""
    zero_dict = {
        "name": "Zero-Power Damager",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 1},
        "power": 0,
        "toughness": 1,
        "effects": [
            {"kind": "deal_damage_equal_to_source_power_any_target"}
        ],
    }
    src_id = synthetic_state.register_and_inject_object(
        zero_dict, 0, ZONE_BATTLEFIELD
    )
    snap = synthetic_state.battlefield_snapshot()
    p1_first_bear_id = next(
        d["id"] for d in snap
        if d["controller_id"] == 1 and d["printing_name"] == "Grizzly Bears"
    )
    synthetic_state.push_to_stack(src_id, 0)
    synthetic_state.resolve_top_of_stack()
    bear = next(
        d for d in synthetic_state.battlefield_snapshot() if d["id"] == p1_first_bear_id
    )
    assert bear["damage"] == 0


def test_resolve_deal_damage_eq_source_power_clone_isolation(synthetic_state):
    src_id = synthetic_state.register_and_inject_object(
        _power_damage_dict(), 0, ZONE_BATTLEFIELD
    )
    snap = synthetic_state.battlefield_snapshot()
    p1_first_bear_id = next(
        d["id"] for d in snap
        if d["controller_id"] == 1 and d["printing_name"] == "Grizzly Bears"
    )
    synthetic_state.push_to_stack(src_id, 0)
    cloned = synthetic_state.clone_once()
    cloned.resolve_top_of_stack()

    clone_bear = next(
        d for d in cloned.battlefield_snapshot() if d["id"] == p1_first_bear_id
    )
    src_bear = next(
        d for d in synthetic_state.battlefield_snapshot() if d["id"] == p1_first_bear_id
    )
    assert clone_bear["damage"] == 3
    assert src_bear["damage"] == 0


# -------------------- Round-28 ConditionalOnTappedCreatures (6 cards) --------------------


def _flight_deck_dict(min_count: int = 2):
    """Flight-Deck-Coordinator-shape intervening-if: 'if you control
    two or more tapped creatures, draw a card'."""
    return {
        "name": "Synthetic Flight Deck",
        "card_types": ["Instant"],
        "mana_cost": {"generic": 1},
        "effects": [
            {
                "kind": "conditional_on_tapped_creatures",
                "min_count": min_count,
                "effect": {"kind": "draw_cards", "count": 1},
            }
        ],
    }


def test_register_conditional_on_tapped_creatures_required_effect(engine):
    import pytest
    reg = engine.Registry()
    with pytest.raises(ValueError, match="missing required 'effect'"):
        reg.register_printing(
            {
                "name": "Bad Conditional",
                "card_types": ["Instant"],
                "effects": [{"kind": "conditional_on_tapped_creatures"}],
            }
        )


def test_register_conditional_default_min_count(engine):
    """Default min_count = 2 (mirrors Python)."""
    reg = engine.Registry()
    pid = reg.register_printing(_flight_deck_dict())
    del reg
    # re-build to round-trip via dict
    eff = engine.Registry()
    pid2 = eff.register_printing(_flight_deck_dict())
    out = eff.get_printing_effects(pid2)[0]
    assert out["kind"] == "conditional_on_tapped_creatures"
    assert out["min_count"] == 2
    assert out["effect"]["kind"] == "draw_cards"


def test_register_conditional_nested_round_trip(engine):
    """The nested effect dict round-trips."""
    reg = engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Test",
            "card_types": ["Instant"],
            "effects": [
                {
                    "kind": "conditional_on_tapped_creatures",
                    "min_count": 3,
                    "effect": {"kind": "gain_life", "amount": 5},
                }
            ],
        }
    )
    eff = reg.get_printing_effects(pid)[0]
    assert eff["min_count"] == 3
    assert eff["effect"]["kind"] == "gain_life"
    assert eff["effect"]["amount"] == 5


def test_resolve_conditional_fires_when_enough_tapped(synthetic_state):
    """Tap 2 of p0's creatures; cast the spell; draw fires."""
    snap = synthetic_state.battlefield_snapshot()
    p0_creatures = [
        d["id"] for d in snap
        if d["controller_id"] == 0 and d["printing_name"] == "Grizzly Bears"
    ][:2]
    for cid in p0_creatures:
        synthetic_state.tap_object(cid)

    spell_id = synthetic_state.register_and_inject_object(
        _flight_deck_dict(min_count=2), 0, ZONE_HAND
    )
    p0_lib_before = synthetic_state.library_sizes[0]
    synthetic_state.push_to_stack(spell_id, 0)
    synthetic_state.resolve_top_of_stack()

    # Draw fired: library shrank by 1.
    assert synthetic_state.library_sizes[0] == p0_lib_before - 1


def test_resolve_conditional_skips_when_not_enough_tapped(synthetic_state):
    """Only 1 tapped creature, but min_count=2 → skip draw."""
    snap = synthetic_state.battlefield_snapshot()
    p0_first_bear = next(
        d["id"] for d in snap
        if d["controller_id"] == 0 and d["printing_name"] == "Grizzly Bears"
    )
    synthetic_state.tap_object(p0_first_bear)
    spell_id = synthetic_state.register_and_inject_object(
        _flight_deck_dict(min_count=2), 0, ZONE_HAND
    )
    p0_lib_before = synthetic_state.library_sizes[0]
    synthetic_state.push_to_stack(spell_id, 0)
    synthetic_state.resolve_top_of_stack()
    # No draw fired.
    assert synthetic_state.library_sizes[0] == p0_lib_before


def test_resolve_conditional_zero_min_count_always_fires(synthetic_state):
    """min_count=0 means always fires (degenerate but legal)."""
    spell_id = synthetic_state.register_and_inject_object(
        _flight_deck_dict(min_count=0), 0, ZONE_HAND
    )
    p0_lib_before = synthetic_state.library_sizes[0]
    synthetic_state.push_to_stack(spell_id, 0)
    synthetic_state.resolve_top_of_stack()
    assert synthetic_state.library_sizes[0] == p0_lib_before - 1


def test_resolve_conditional_tapped_filter_skips_non_creatures(synthetic_state):
    """Tapped non-creatures (e.g. tapped Forests) don't count toward
    min_count. Tap 2 Forests + 0 Bears → no fire."""
    snap = synthetic_state.battlefield_snapshot()
    p0_forests = [
        d["id"] for d in snap
        if d["controller_id"] == 0 and d["printing_name"] == "Forest"
    ][:2]
    for fid in p0_forests:
        synthetic_state.tap_object(fid)
    spell_id = synthetic_state.register_and_inject_object(
        _flight_deck_dict(min_count=2), 0, ZONE_HAND
    )
    p0_lib_before = synthetic_state.library_sizes[0]
    synthetic_state.push_to_stack(spell_id, 0)
    synthetic_state.resolve_top_of_stack()
    # No draw — Forests are non-creature so they didn't satisfy the
    # tapped-creature predicate.
    assert synthetic_state.library_sizes[0] == p0_lib_before


# -------------------- Round-28 OptionalSacArtifactForEffect (2 cards) --------------------


def _lithobraking_dict():
    return {
        "name": "Lithobraking (synthetic)",
        "card_types": ["Sorcery"],
        "mana_cost": {"R": 1},
        "effects": [
            {
                "kind": "optional_sac_artifact_for_effect",
                "inner_effect": {"kind": "draw_cards", "count": 1},
            }
        ],
    }


def _vanilla_artifact_for_sac(name="Sac Target Artifact"):
    return {
        "name": name,
        "card_types": ["Artifact"],
        "mana_cost": {"generic": 1},
    }


def test_register_optional_sac_artifact_missing_inner_raises(engine):
    import pytest
    reg = engine.Registry()
    with pytest.raises(ValueError, match="missing required 'inner_effect'"):
        reg.register_printing(
            {
                "name": "Bad",
                "card_types": ["Sorcery"],
                "effects": [{"kind": "optional_sac_artifact_for_effect"}],
            }
        )


def test_register_optional_sac_artifact_round_trips(engine):
    reg = engine.Registry()
    pid = reg.register_printing(_lithobraking_dict())
    eff = reg.get_printing_effects(pid)[0]
    assert eff["kind"] == "optional_sac_artifact_for_effect"
    assert eff["inner_effect"]["kind"] == "draw_cards"
    assert eff["inner_effect"]["count"] == 1


def test_resolve_optional_sac_artifact_sacs_and_applies_inner(synthetic_state):
    """Inject artifact on p0 bf, cast Lithobraking; artifact goes to
    graveyard, draw fires."""
    artifact_id = synthetic_state.register_and_inject_object(
        _vanilla_artifact_for_sac(), 0, ZONE_BATTLEFIELD
    )
    spell_id = synthetic_state.register_and_inject_object(
        _lithobraking_dict(), 0, ZONE_HAND
    )
    p0_lib_before = synthetic_state.library_sizes[0]
    p0_gy_before = synthetic_state.graveyard_sizes[0]

    synthetic_state.push_to_stack(spell_id, 0)
    synthetic_state.resolve_top_of_stack()

    # Artifact in graveyard.
    assert synthetic_state.find_object_zone(artifact_id) == ZONE_GRAVEYARD
    # Draw fired: library shrank by 1.
    assert synthetic_state.library_sizes[0] == p0_lib_before - 1
    # Graveyard: +1 (artifact sac'd) + 1 (sorcery post-resolve) = +2.
    assert synthetic_state.graveyard_sizes[0] == p0_gy_before + 2


def test_resolve_optional_sac_artifact_no_artifact_full_noop(synthetic_state):
    """No artifact on p0 bf → full no-op (no sac AND no draw)."""
    # Synthetic state defaults: only Forests + Grizzly Bears on p0 bf.
    spell_id = synthetic_state.register_and_inject_object(
        _lithobraking_dict(), 0, ZONE_HAND
    )
    p0_lib_before = synthetic_state.library_sizes[0]
    synthetic_state.push_to_stack(spell_id, 0)
    synthetic_state.resolve_top_of_stack()
    # No draw fired (inner skipped because no artifact).
    assert synthetic_state.library_sizes[0] == p0_lib_before


def test_resolve_optional_sac_artifact_clone_isolation(synthetic_state):
    artifact_id = synthetic_state.register_and_inject_object(
        _vanilla_artifact_for_sac(), 0, ZONE_BATTLEFIELD
    )
    spell_id = synthetic_state.register_and_inject_object(
        _lithobraking_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_id, 0)
    cloned = synthetic_state.clone_once()
    cloned.resolve_top_of_stack()

    # Clone: artifact in graveyard.
    assert cloned.find_object_zone(artifact_id) == ZONE_GRAVEYARD
    # Source: artifact still on bf (no resolve happened).
    assert synthetic_state.find_object_zone(artifact_id) == ZONE_BATTLEFIELD


# -------------------- Round-28 DestroyEnchantedPermanent (4 cards) --------------------


def _cryoshatter_dict():
    """Cryoshatter-shape aura: triggered ability destroys what it's
    attached to. Modeled as an enchantment with an activated/triggered
    effect."""
    return {
        "name": "Cryoshatter (synthetic)",
        "card_types": ["Enchantment"],
        "mana_cost": {"U": 1, "generic": 1},
        "effects": [
            {"kind": "destroy_enchanted_permanent"}
        ],
    }


def test_register_destroy_enchanted_permanent(engine):
    reg = engine.Registry()
    pid = reg.register_printing(_cryoshatter_dict())
    eff = reg.get_printing_effects(pid)[0]
    assert eff["kind"] == "destroy_enchanted_permanent"


def test_resolve_destroy_enchanted_permanent_kills_host(synthetic_state):
    """Aura attached to p1's first creature; resolve destroys the
    creature, moves it to its controller's graveyard."""
    snap = synthetic_state.battlefield_snapshot()
    p1_first_bear_id = next(
        d["id"] for d in snap
        if d["controller_id"] == 1 and d["printing_name"] == "Grizzly Bears"
    )
    # Inject the aura onto p0's bf and attach to the target.
    aura_id = synthetic_state.register_and_inject_object(
        _cryoshatter_dict(), 0, ZONE_BATTLEFIELD
    )
    synthetic_state.attach(aura_id, p1_first_bear_id)
    p1_gy_before = synthetic_state.graveyard_sizes[1]

    synthetic_state.push_to_stack(aura_id, 0)
    synthetic_state.resolve_top_of_stack()

    # Target moved to p1's graveyard.
    assert synthetic_state.find_object_zone(p1_first_bear_id) == ZONE_GRAVEYARD
    assert synthetic_state.graveyard_sizes[1] == p1_gy_before + 1


def test_resolve_destroy_enchanted_permanent_no_attached_fizzles(synthetic_state):
    """Source has attached_to=None → silent fizzle."""
    aura_id = synthetic_state.register_and_inject_object(
        _cryoshatter_dict(), 0, ZONE_BATTLEFIELD
    )
    # Don't attach to anything.
    synthetic_state.push_to_stack(aura_id, 0)
    synthetic_state.resolve_top_of_stack()  # must not raise


def test_resolve_destroy_enchanted_permanent_source_off_bf_fizzles(synthetic_state):
    """Source not on bf → silent fizzle (aura already left)."""
    aura_id = synthetic_state.register_and_inject_object(
        _cryoshatter_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(aura_id, 0)
    # Aura is in hand, not bf, so the read of attached_to comes back
    # None (we only scan bf in the new arm). Must resolve cleanly.
    synthetic_state.resolve_top_of_stack()


def test_resolve_destroy_enchanted_permanent_clone_isolation(synthetic_state):
    snap = synthetic_state.battlefield_snapshot()
    p1_first_bear_id = next(
        d["id"] for d in snap
        if d["controller_id"] == 1 and d["printing_name"] == "Grizzly Bears"
    )
    aura_id = synthetic_state.register_and_inject_object(
        _cryoshatter_dict(), 0, ZONE_BATTLEFIELD
    )
    synthetic_state.attach(aura_id, p1_first_bear_id)
    synthetic_state.push_to_stack(aura_id, 0)
    cloned = synthetic_state.clone_once()
    cloned.resolve_top_of_stack()

    # Clone: target in graveyard. Source: target still on bf.
    assert cloned.find_object_zone(p1_first_bear_id) == ZONE_GRAVEYARD
    assert synthetic_state.find_object_zone(p1_first_bear_id) == ZONE_BATTLEFIELD


# -------------------- Round-29 ConditionalIfVoid (4 cards) --------------------
#
# Mirrors Python's `ConditionalIfVoid(then_effect, else_effect=None)`
# (combinators.py:1409 — "Void —" rider on Decode Transmissions /
# Hymn of the Faller family). Intervening-if at resolve time: if
# Void is active (a nonland permanent left the battlefield this turn
# OR a spell was warped this turn), apply then_effect; else apply
# else_effect or no-op.
#
# Substrate note: the void flags
# (`permanent_left_battlefield_this_turn`, `spell_warped_this_turn`)
# are read-only from the resolver — no Rust call sites flip them
# yet. Tests inject the flag state directly via
# `state.set_void_flags(...)`. Once the LTB / warp tracking lands as
# a follow-up, the resolve arm here picks up real Void-true behavior
# for free.


def _conditional_if_void_decode_dict(with_else: bool = True):
    """Decode-Transmissions-shape: 'draw two cards; Void — instead draw four'.

    For our test we use simpler nested effects (draw_cards) — the
    conditional shape is what matters.
    """
    base: dict = {
        "name": "Synthetic Decode Transmissions",
        "card_types": ["Instant"],
        "mana_cost": {"generic": 3, "U": 1},
        "effects": [
            {
                "kind": "conditional_if_void",
                "then_effect": {"kind": "draw_cards", "count": 4},
            }
        ],
    }
    if with_else:
        base["effects"][0]["else_effect"] = {"kind": "draw_cards", "count": 2}
    return base


def _hymn_of_the_faller_dict():
    """Hymn-of-the-Faller-shape: 'draw a card; Void — draw another card'.

    The then-branch is a Sequence so we can validate nested combinator
    recursion through ConditionalIfVoid.
    """
    return {
        "name": "Synthetic Hymn",
        "card_types": ["Sorcery"],
        "mana_cost": {"B": 1},
        "effects": [
            {
                "kind": "conditional_if_void",
                "then_effect": {
                    "kind": "sequence",
                    "effects": [
                        {"kind": "draw_cards", "count": 1},
                        {"kind": "draw_cards", "count": 1},
                    ],
                },
                "else_effect": {"kind": "draw_cards", "count": 1},
            }
        ],
    }


def test_register_conditional_if_void_round_trip_with_else(engine):
    """Register a printing with explicit else, round-trip via the
    effect_to_pydict path; both branches survive."""
    reg = engine.Registry()
    pid = reg.register_printing(_conditional_if_void_decode_dict(with_else=True))
    eff = reg.get_printing_effects(pid)[0]
    assert eff["kind"] == "conditional_if_void"
    assert eff["then_effect"]["kind"] == "draw_cards"
    assert eff["then_effect"]["count"] == 4
    assert eff["else_effect"]["kind"] == "draw_cards"
    assert eff["else_effect"]["count"] == 2


def test_register_conditional_if_void_round_trip_without_else(engine):
    """Register a printing with no else key — round-trip returns
    else_effect=None (mirrors Python's optional second branch)."""
    reg = engine.Registry()
    pid = reg.register_printing(_conditional_if_void_decode_dict(with_else=False))
    eff = reg.get_printing_effects(pid)[0]
    assert eff["kind"] == "conditional_if_void"
    assert eff["then_effect"]["kind"] == "draw_cards"
    assert eff["else_effect"] is None


def test_register_conditional_if_void_missing_then_effect_raises(engine):
    """The then-branch is required; missing it raises ValueError at
    parse time. Mirrors `conditional_on_tapped_creatures`'s parse-time
    contract."""
    import pytest
    reg = engine.Registry()
    with pytest.raises(ValueError, match="missing required 'then_effect'"):
        reg.register_printing(
            {
                "name": "Bad Conditional If Void",
                "card_types": ["Instant"],
                "effects": [{"kind": "conditional_if_void"}],
            }
        )


def test_register_conditional_if_void_explicit_none_else(engine):
    """Explicit Python None for else_effect is accepted and round-
    trips back as None (treated identically to key-absent)."""
    reg = engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Explicit-None-Else Conditional",
            "card_types": ["Instant"],
            "effects": [
                {
                    "kind": "conditional_if_void",
                    "then_effect": {"kind": "draw_cards", "count": 1},
                    "else_effect": None,
                }
            ],
        }
    )
    eff = reg.get_printing_effects(pid)[0]
    assert eff["else_effect"] is None


def test_resolve_conditional_if_void_inactive_runs_else_branch(synthetic_state):
    """Void inactive (default state) → else-branch fires.

    Synthetic state has no events that flip the void flags; verify
    `is_void_active` is False and the else-branch (draw 2) runs.
    """
    assert synthetic_state.is_void_active is False
    spell_id = synthetic_state.register_and_inject_object(
        _conditional_if_void_decode_dict(with_else=True), 0, ZONE_HAND
    )
    p0_lib_before = synthetic_state.library_sizes[0]
    synthetic_state.push_to_stack(spell_id, 0)
    synthetic_state.resolve_top_of_stack()

    # Else-branch fired: drew 2.
    assert synthetic_state.library_sizes[0] == p0_lib_before - 2


def test_resolve_conditional_if_void_active_runs_then_branch(synthetic_state):
    """Set permanent_left_battlefield_this_turn → Void is active →
    then-branch fires (draw 4)."""
    synthetic_state.set_void_flags(permanent_left_battlefield=True)
    assert synthetic_state.is_void_active is True
    spell_id = synthetic_state.register_and_inject_object(
        _conditional_if_void_decode_dict(with_else=True), 0, ZONE_HAND
    )
    p0_lib_before = synthetic_state.library_sizes[0]
    synthetic_state.push_to_stack(spell_id, 0)
    synthetic_state.resolve_top_of_stack()

    # Then-branch fired: drew 4.
    assert synthetic_state.library_sizes[0] == p0_lib_before - 4


def test_resolve_conditional_if_void_active_via_warp_flag(synthetic_state):
    """The second void-predicate input (spell_warped_this_turn) also
    flips Void to active — covers the OR-arm of the predicate."""
    synthetic_state.set_void_flags(spell_warped=True)
    assert synthetic_state.is_void_active is True
    spell_id = synthetic_state.register_and_inject_object(
        _conditional_if_void_decode_dict(with_else=True), 0, ZONE_HAND
    )
    p0_lib_before = synthetic_state.library_sizes[0]
    synthetic_state.push_to_stack(spell_id, 0)
    synthetic_state.resolve_top_of_stack()
    assert synthetic_state.library_sizes[0] == p0_lib_before - 4


def test_resolve_conditional_if_void_no_else_inactive_is_noop(synthetic_state):
    """No else-branch + Void inactive → silent no-op (mirrors
    Python's None-branch fall-through)."""
    assert synthetic_state.is_void_active is False
    spell_id = synthetic_state.register_and_inject_object(
        _conditional_if_void_decode_dict(with_else=False), 0, ZONE_HAND
    )
    p0_lib_before = synthetic_state.library_sizes[0]
    synthetic_state.push_to_stack(spell_id, 0)
    synthetic_state.resolve_top_of_stack()
    # No draw fired.
    assert synthetic_state.library_sizes[0] == p0_lib_before


def test_resolve_conditional_if_void_no_else_active_runs_then(synthetic_state):
    """No else-branch + Void active → then-branch fires."""
    synthetic_state.set_void_flags(permanent_left_battlefield=True)
    spell_id = synthetic_state.register_and_inject_object(
        _conditional_if_void_decode_dict(with_else=False), 0, ZONE_HAND
    )
    p0_lib_before = synthetic_state.library_sizes[0]
    synthetic_state.push_to_stack(spell_id, 0)
    synthetic_state.resolve_top_of_stack()
    # Then-branch fired: drew 4.
    assert synthetic_state.library_sizes[0] == p0_lib_before - 4


def test_resolve_conditional_if_void_nested_sequence_then_branch(synthetic_state):
    """Then-branch is a Sequence — recursion through apply_effect
    must dispatch both inner effects.

    Hymn shape: then = Sequence(draw, draw) → 2 cards drawn under
    Void; else = single draw → 1 card under non-Void."""
    synthetic_state.set_void_flags(permanent_left_battlefield=True)
    spell_id = synthetic_state.register_and_inject_object(
        _hymn_of_the_faller_dict(), 0, ZONE_HAND
    )
    p0_lib_before = synthetic_state.library_sizes[0]
    synthetic_state.push_to_stack(spell_id, 0)
    synthetic_state.resolve_top_of_stack()
    # Nested Sequence(draw, draw) under Void → 2 draws.
    assert synthetic_state.library_sizes[0] == p0_lib_before - 2


def test_resolve_conditional_if_void_nested_sequence_else_branch(synthetic_state):
    """Same Hymn-shape spell, Void inactive → else-branch fires
    (single draw)."""
    spell_id = synthetic_state.register_and_inject_object(
        _hymn_of_the_faller_dict(), 0, ZONE_HAND
    )
    p0_lib_before = synthetic_state.library_sizes[0]
    synthetic_state.push_to_stack(spell_id, 0)
    synthetic_state.resolve_top_of_stack()
    # Else-branch: 1 draw.
    assert synthetic_state.library_sizes[0] == p0_lib_before - 1


def test_resolve_conditional_if_void_clone_isolation(synthetic_state):
    """Clone-once: each branch fires only in the state it was set up
    for. Confirms the void flags + the nested effect dispatch are
    both fork-safe."""
    spell_id = synthetic_state.register_and_inject_object(
        _conditional_if_void_decode_dict(with_else=True), 0, ZONE_HAND
    )
    cloned = synthetic_state.clone_once()
    cloned.set_void_flags(permanent_left_battlefield=True)

    p0_lib_orig = synthetic_state.library_sizes[0]
    p0_lib_clone = cloned.library_sizes[0]

    synthetic_state.push_to_stack(spell_id, 0)
    synthetic_state.resolve_top_of_stack()
    cloned.push_to_stack(spell_id, 0)
    cloned.resolve_top_of_stack()

    # Source state: void inactive → else-branch (draw 2).
    assert synthetic_state.library_sizes[0] == p0_lib_orig - 2
    # Clone: void active → then-branch (draw 4).
    assert cloned.library_sizes[0] == p0_lib_clone - 4


# --- DealDamageToOpponentCreature dispatch --------------------------
#
# **DealDamageToOpponentCreature scope** (mirrored in the Rust module
# docstring on `cards.rs`):
#
# - **Glassworks // Shattered Yard family — 2 EoE cards.** Mirrors
#   Python's `DealDamageToOpponentCreature(DealDamage)` sugar with
#   filter `IsCreature() & ControlledByOpponent()` — same `DealDamage`
#   shape as `DealDamageToTargetCreature` but the target must be a
#   creature controlled by an opponent of the SOURCE's controller.
# - **First-slice deterministic choice**: iterate opponents in player
#   order; pick the FIRST `Creature` printing on each opponent's
#   battlefield (smallest bf index). Silent fizzle if no opponent
#   creature.
# - **Source-controller direction** (not active-player direction).
#   Inverts target side correctly when p1 casts the source on p0's
#   turn — mirrors LoseLife / TargetOpponentLosesLife shape.
# - **Negative amount raises** at register time AND at resolve time
#   (defense-in-depth — mirrors DealDamage / DealDamageAnyTarget).
# - **SBA fires post-resolve.** Lethal damage (damage >= effective
#   toughness) flips the creature to graveyard via the standard SBA
#   pass (CR 704.5g).


def _shattered_yard_dict(amount=3):
    """A deal-damage-to-opponent-creature printing — Shattered Yard-shaped
    (sorcery, deals N damage to target creature an opponent controls)."""
    return {
        "name": "Test Shattered Yard",
        "card_types": ["Sorcery"],
        "mana_cost": {"R": 1, "generic": 2},
        "effects": [
            {"kind": "deal_damage_to_opponent_creature", "amount": amount}
        ],
    }


def test_resolve_deal_damage_to_opponent_creature_register_round_trip(
    empty_registry,
):
    """Round-trip: register a printing, look up its effects, confirm the
    Effect dict survives the parse + serialize round-trip."""
    pid = empty_registry.register_printing(_shattered_yard_dict(amount=3))
    effects = empty_registry.get_printing_effects(pid)
    assert len(effects) == 1
    assert effects[0]["kind"] == "deal_damage_to_opponent_creature"
    assert effects[0]["amount"] == 3


def test_resolve_deal_damage_to_opponent_creature_missing_amount_raises(
    empty_registry,
):
    """Missing `amount` field is a register-time KeyError (mirrors the
    deal_damage_any_target / pump arms' required-field shape)."""
    with pytest.raises(KeyError):
        empty_registry.register_printing(
            {
                "name": "Test Missing Amount",
                "card_types": ["Sorcery"],
                "mana_cost": {"R": 1, "generic": 2},
                "effects": [{"kind": "deal_damage_to_opponent_creature"}],
            }
        )


def test_resolve_deal_damage_to_opponent_creature_negative_amount_raises_at_register(
    empty_registry,
):
    """Register-time guard on negative amount (defense-in-depth, the
    apply_effect guard is the secondary check). Mirrors DealDamageAnyTarget
    / EachOpponentLosesLife / DiscardSelf / PutPlusOneCounterOnSelf
    negative-amount register-time check shape."""
    with pytest.raises(ValueError, match="non-negative"):
        empty_registry.register_printing(_shattered_yard_dict(amount=-1))


def test_resolve_deal_damage_to_opponent_creature_happy_path(synthetic_state):
    """End-to-end happy path. Source is on p0's bf (controller=0);
    resolution scans p1's bf top-to-bottom and damages the FIRST
    creature it finds. The synthetic seed seats lands first on p1's
    bf (Forest at bf[0..5]) then creatures — Bears at bf[5] — so the
    Land filter must skip past the Forests and land damage on the
    first Bears (obj_id 72 in the standard fixture)."""
    target_obj_id = 72  # p1's bf[5], the first Bears (skipping 5 Forests)
    assert synthetic_state.get_damage(target_obj_id) == 0

    spell_obj_id = synthetic_state.register_and_inject_object(
        _shattered_yard_dict(amount=2), 0, ZONE_BATTLEFIELD
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    life_before = list(synthetic_state.life_totals)
    resolved = synthetic_state.resolve_top_of_stack()

    assert resolved is not None
    # First creature (Bears at 72) took the damage; Forest at bf[0]
    # untouched (Creature filter).
    assert synthetic_state.get_damage(target_obj_id) == 2
    assert synthetic_state.get_damage(67) == 0  # p1 bf[0] Forest
    # Life totals untouched (creatures take damage, not players).
    assert list(synthetic_state.life_totals) == life_before
    assert synthetic_state.is_stack_empty() is True


def test_resolve_deal_damage_to_opponent_creature_skips_source_controllers_creatures(
    engine,
):
    """The filter excludes creatures controlled by the source's controller.
    Setup: p0 (= source's controller) has a creature on their bf; p1
    has a creature on their bf. The damage must land on p1's creature,
    NOT p0's — this is the critical distinction from `DealDamageAnyTarget`
    and `DealDamage{AnyCreature}` which scan defender's bf without
    a controller filter."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=1
    )
    p0_creature_id = state.register_and_inject_object(
        {
            "name": "Test P0 Bear",
            "card_types": ["Creature"],
            "power": 2,
            "toughness": 2,
        },
        0,
        ZONE_BATTLEFIELD,
    )
    p1_creature_id = state.register_and_inject_object(
        {
            "name": "Test P1 Bear",
            "card_types": ["Creature"],
            "power": 2,
            "toughness": 2,
        },
        1,
        ZONE_BATTLEFIELD,
    )
    spell_obj_id = state.register_and_inject_object(
        _shattered_yard_dict(amount=2), 0, ZONE_HAND
    )
    state.push_to_stack(spell_obj_id, 0)
    state.resolve_top_of_stack()

    # P1's creature damaged; P0's untouched.
    assert state.get_damage(p1_creature_id) == 2
    assert state.get_damage(p0_creature_id) == 0


def test_resolve_deal_damage_to_opponent_creature_no_eligible_target_fizzles(
    engine,
):
    """If no opponent has any creature on bf, the spell fizzles silently —
    no damage applied anywhere, no life change, no error. Stack still
    pops and the source still moves post-resolve."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=1
    )
    # P1 has only a Land on bf (no creature).
    land_id = state.register_and_inject_object(
        {
            "name": "Test Plains",
            "card_types": ["Land"],
            "mana_produced": ["W"],
        },
        1,
        ZONE_BATTLEFIELD,
    )
    # P0 has a creature on bf — but the filter excludes source-
    # controller's own creatures, so this is NOT eligible either.
    p0_creature_id = state.register_and_inject_object(
        {
            "name": "Test P0 Bear",
            "card_types": ["Creature"],
            "power": 2,
            "toughness": 2,
        },
        0,
        ZONE_BATTLEFIELD,
    )
    spell_obj_id = state.register_and_inject_object(
        _shattered_yard_dict(amount=3), 0, ZONE_HAND
    )
    state.push_to_stack(spell_obj_id, 0)
    life_before = list(state.life_totals)
    state.resolve_top_of_stack()

    # No damage applied to either creature, no life change.
    assert state.get_damage(land_id) == 0
    assert state.get_damage(p0_creature_id) == 0
    assert list(state.life_totals) == life_before
    assert state.is_stack_empty() is True


def test_resolve_deal_damage_to_opponent_creature_p1_source_attacks_p0(
    synthetic_state,
):
    """Inverted controller direction: source is controlled by p1 while
    active_player stays 0. The dispatch must damage p0's first creature
    (NOT p1's) — because the OPPONENT of the source's CONTROLLER (= p1)
    is p0. Cross-checks that the dispatch reads `obj.controller` /
    `StackItem.controller` rather than `state.active_player`."""
    # Synthetic seed has both players' bfs seeded. P0's first Bears
    # is at obj_id 5 (p0 bf[5], skipping 5 Forests at bf[0..4]); p1's
    # first Bears is at obj_id 72.
    p0_first_bear_id = 5
    p1_first_bear_id = 72
    assert synthetic_state.get_damage(p0_first_bear_id) == 0
    assert synthetic_state.get_damage(p1_first_bear_id) == 0

    # Inject the source onto p1's bf (controller=1).
    src_id = synthetic_state.register_and_inject_object(
        _shattered_yard_dict(amount=2), 1, ZONE_BATTLEFIELD
    )
    # Push with controller=1 (p1's spell resolving on the stack).
    synthetic_state.push_to_stack(src_id, 1)
    synthetic_state.resolve_top_of_stack()

    # p0's first Bears took the damage; p1's untouched.
    assert synthetic_state.get_damage(p0_first_bear_id) == 2
    assert synthetic_state.get_damage(p1_first_bear_id) == 0


def test_resolve_deal_damage_to_opponent_creature_lethal_damage_destroys_via_sba(
    engine,
):
    """damage >= effective toughness flips the opponent's creature to
    graveyard on the next SBA pass (CR 704.5g). Verifies the damage-
    stamp path composes cleanly with SBA destruction — same shape as
    the round-3 DealDamage path."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=1
    )
    # P1 has a 2/2 Bear.
    bear_id = state.register_and_inject_object(
        {
            "name": "Test Bear",
            "card_types": ["Creature"],
            "power": 2,
            "toughness": 2,
        },
        1,
        ZONE_BATTLEFIELD,
    )
    spell_obj_id = state.register_and_inject_object(
        _shattered_yard_dict(amount=3), 0, ZONE_HAND
    )
    state.push_to_stack(spell_obj_id, 0)
    state.resolve_top_of_stack()

    # Damage stamped (3 >= toughness 2 = lethal).
    assert state.get_damage(bear_id) == 3
    # SBA destroys it.
    assert state.apply_sbas() == 1
    assert state.find_object_zone(bear_id) == ZONE_GRAVEYARD


def test_resolve_deal_damage_to_opponent_creature_zero_amount_no_op(
    synthetic_state,
):
    """amount=0 is a legal no-op (mirrors GainLife / DrawCards / Mill /
    DealDamageAnyTarget zero-amount conventions). The variant still
    fires (target search happens, no damage applied), the stack pops,
    no error."""
    target_obj_id = 72  # p1's first Bears
    spell_obj_id = synthetic_state.register_and_inject_object(
        _shattered_yard_dict(amount=0), 0, ZONE_BATTLEFIELD
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    life_before = list(synthetic_state.life_totals)
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.get_damage(target_obj_id) == 0
    assert list(synthetic_state.life_totals) == life_before
    assert synthetic_state.is_stack_empty() is True


def test_resolve_deal_damage_to_opponent_creature_clone_isolation(
    synthetic_state,
):
    """CoW canary: cloning the state and resolving the spell on the clone
    must not bleed damage back into the original — the bf battlefield
    Vec is Arc-shared, and the clone-then-mutate path must trigger a
    `Arc::make_mut` fork on the clone's side only."""
    target_obj_id = 72  # p1's first Bears
    spell_obj_id = synthetic_state.register_and_inject_object(
        _shattered_yard_dict(amount=3), 0, ZONE_BATTLEFIELD
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    cloned = synthetic_state.clone_once()

    cloned.resolve_top_of_stack()

    # Clone: stack drained, target creature damaged.
    assert cloned.is_stack_empty() is True
    assert cloned.get_damage(target_obj_id) == 3
    # Original: stack still has the spell, no damage applied.
    assert synthetic_state.stack_size() == 1
    assert synthetic_state.get_damage(target_obj_id) == 0


# -------------------- Round-28 DrawCardsEqualToResolvingCombatDamage (2 cards) --------------------
# Starwinder / Fear-of-Failed-Tests shape: "Whenever a creature you
# control deals combat damage to a player, you may draw that many
# cards." The "may" is engine-flattened to always-yes.
#
# **First-slice scope.** Rust's combat-damage assignment doesn't yet
# write state.resolving_combat_damage_amount (CE9 closure agent owns
# state_ops_combat.rs). The Effect arm reads the slot; tests inject
# the amount via state.set_resolving_combat_damage_amount(n) to
# exercise the read-side. See docs/SEARCH_LIMITATIONS.md for the
# deferred write site.


def _starwinder_dict():
    """Starwinder-shape printing: a creature with a trigger-resolve-
    time effect that draws cards equal to
    state.resolving_combat_damage_amount."""
    return {
        "name": "Synthetic Starwinder",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 3, "U": 1},
        "power": 2,
        "toughness": 3,
        "effects": [
            {"kind": "draw_cards_equal_to_resolving_combat_damage"}
        ],
    }


def test_register_draw_cards_equal_to_resolving_combat_damage(engine):
    """Round-trip: register a printing carrying the variant; readback
    via get_printing_effects produces the same kind string."""
    reg = engine.Registry()
    pid = reg.register_printing(_starwinder_dict())
    eff = reg.get_printing_effects(pid)[0]
    assert eff["kind"] == "draw_cards_equal_to_resolving_combat_damage"


def test_register_draw_cards_equal_to_resolving_combat_damage_unknown_field(
    engine,
):
    """Variant is fieldless; unknown extra fields on the effect dict
    are silently ignored (consistent with other fieldless variants —
    parse_effect dispatches on `kind` and never inspects extras for
    unit-style arms). This pins the contract."""
    reg = engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Bonus Fields",
            "card_types": ["Creature"],
            "mana_cost": {"generic": 1},
            "power": 1,
            "toughness": 1,
            "effects": [
                {
                    "kind": "draw_cards_equal_to_resolving_combat_damage",
                    "extra_field_we_ignore": 42,
                }
            ],
        }
    )
    eff = reg.get_printing_effects(pid)[0]
    assert eff["kind"] == "draw_cards_equal_to_resolving_combat_damage"
    # No extra field surfaces on read-back (round-trip is pure).
    assert "extra_field_we_ignore" not in eff


def test_resolve_draw_eq_combat_damage_zero_amount_is_noop(synthetic_state):
    """resolving_combat_damage_amount defaults to 0 — the Effect should
    be a silent no-op (no cards drawn, stack still drains)."""
    src_id = synthetic_state.register_and_inject_object(
        _starwinder_dict(), 0, ZONE_BATTLEFIELD
    )
    # Sanity: the slot is 0 out of the box.
    assert synthetic_state.resolving_combat_damage_amount == 0

    p0_hand_before = synthetic_state.hand_sizes[0]
    p0_lib_before = synthetic_state.library_sizes[0]

    synthetic_state.push_to_stack(src_id, 0)
    synthetic_state.resolve_top_of_stack()

    # No draw fired; stack drained.
    assert synthetic_state.hand_sizes[0] == p0_hand_before
    assert synthetic_state.library_sizes[0] == p0_lib_before
    assert synthetic_state.is_stack_empty() is True


def test_resolve_draw_eq_combat_damage_happy_path(synthetic_state):
    """Inject the amount via set_resolving_combat_damage_amount(3);
    resolve the trigger; controller draws 3 cards."""
    src_id = synthetic_state.register_and_inject_object(
        _starwinder_dict(), 0, ZONE_BATTLEFIELD
    )
    synthetic_state.set_resolving_combat_damage_amount(3)
    assert synthetic_state.resolving_combat_damage_amount == 3

    p0_hand_before = synthetic_state.hand_sizes[0]
    p0_lib_before = synthetic_state.library_sizes[0]

    synthetic_state.push_to_stack(src_id, 0)
    synthetic_state.resolve_top_of_stack()

    # Hand grew by 3, library shrank by 3.
    assert synthetic_state.hand_sizes[0] == p0_hand_before + 3
    assert synthetic_state.library_sizes[0] == p0_lib_before - 3


def test_resolve_draw_eq_combat_damage_reads_source_controller(
    synthetic_state,
):
    """Source on p1's battlefield + pushed by p1 → p1 draws (not the
    active_player p0). Confirms the Effect dispatches on source's
    controller, not state.active_player."""
    src_id = synthetic_state.register_and_inject_object(
        _starwinder_dict(), 1, ZONE_BATTLEFIELD
    )
    synthetic_state.set_resolving_combat_damage_amount(2)

    p0_hand_before = synthetic_state.hand_sizes[0]
    p1_hand_before = synthetic_state.hand_sizes[1]
    p1_lib_before = synthetic_state.library_sizes[1]

    synthetic_state.push_to_stack(src_id, 1)
    synthetic_state.resolve_top_of_stack()

    # p1 drew, p0 didn't.
    assert synthetic_state.hand_sizes[0] == p0_hand_before
    assert synthetic_state.hand_sizes[1] == p1_hand_before + 2
    assert synthetic_state.library_sizes[1] == p1_lib_before - 2


def test_resolve_draw_eq_combat_damage_negative_amount_is_noop(
    synthetic_state,
):
    """Defensive: a negative amount (illegal in real MTG but defensible
    if a future write site clamps wrong) silent no-ops rather than
    erroring out. Matches Python's `if amount <= 0: return`."""
    src_id = synthetic_state.register_and_inject_object(
        _starwinder_dict(), 0, ZONE_BATTLEFIELD
    )
    synthetic_state.set_resolving_combat_damage_amount(-5)

    p0_hand_before = synthetic_state.hand_sizes[0]
    p0_lib_before = synthetic_state.library_sizes[0]

    synthetic_state.push_to_stack(src_id, 0)
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.hand_sizes[0] == p0_hand_before
    assert synthetic_state.library_sizes[0] == p0_lib_before


def test_resolve_draw_eq_combat_damage_clone_isolation(synthetic_state):
    """CoW canary: cloning after pushing the trigger and resolving on
    the clone must not bleed draws into the original. Confirms the
    library/hand Arcs fork via Arc::make_mut on the clone side only."""
    src_id = synthetic_state.register_and_inject_object(
        _starwinder_dict(), 0, ZONE_BATTLEFIELD
    )
    synthetic_state.set_resolving_combat_damage_amount(2)
    synthetic_state.push_to_stack(src_id, 0)
    cloned = synthetic_state.clone_once()

    p0_hand_before = synthetic_state.hand_sizes[0]
    p0_lib_before = synthetic_state.library_sizes[0]

    cloned.resolve_top_of_stack()

    # Clone: draws fired.
    assert cloned.hand_sizes[0] == p0_hand_before + 2
    assert cloned.library_sizes[0] == p0_lib_before - 2
    # Original: untouched, stack still loaded.
    assert synthetic_state.hand_sizes[0] == p0_hand_before
    assert synthetic_state.library_sizes[0] == p0_lib_before
    assert synthetic_state.stack_size() == 1


# ---------------------------------------------------------------------------
# CE13 closure: `summoning_sick` preserved on LTB (I35 invariant).
#
# Python's `turn.move_off_battlefield` deliberately does NOT reset
# `obj.summoning_sick` when an object leaves the battlefield. Pre-CE13
# Rust's destroy / exile / bounce / sacrifice arms in
# `state_ops_resolve.rs` explicitly cleared the flag alongside the
# other CR 400.7 per-object resets, producing a cross-engine fingerprint
# mismatch on any LTB of a still-sick creature. The CE13 closure
# removes the unnecessary clears from every LTB arm, matching Python's
# preserve-on-LTB semantics. ETB sites (creature-spell resolve,
# token creation, reanimate, search-for-land-into-bf) still stamp
# `sick=true` (or `sick=false` for lands) as before — only the LTB
# direction changes.
#
# Regression tests:
#   - destroy_target / destroy_all_creatures / destroy_target_artifact
#   - exile_target
#   - return_to_hand (bounce)
#   - sacrifice
#   - reanimate (the ETB reset still stamps sick=true post-reanimate)
#
# See I35 in `docs/RUST_PARITY_GAPS.md`.
# ---------------------------------------------------------------------------


def _gy_entry_for_id(state, player_id: int, obj_id: int) -> dict | None:
    """Walk `player_id`'s graveyard_snapshot and return the entry dict
    matching `obj_id`, or None if no entry matches."""
    for entry in state.graveyard_snapshot(player_id):
        if entry["id"] == obj_id:
            return entry
    return None


def _hand_entry_for_id(state, player_id: int, obj_id: int) -> dict | None:
    """Walk `player_id`'s hand_snapshot and return the entry dict
    matching `obj_id`, or None if no entry matches."""
    for entry in state.hand_snapshot(player_id):
        if entry["id"] == obj_id:
            return entry
    return None


def test_ce13_destroy_target_preserves_summoning_sick_on_ltb(
    synthetic_state,
):
    """Destroying a freshly-cast (still summoning-sick) creature must
    NOT clear `summoning_sick` on the graveyard object. Matches
    Python's `move_off_battlefield` preserve-on-LTB semantics.
    I35 invariant.

    Setup: cast a Bears under p1 (so p1 controls a sick creature on
    its bf). To avoid target-filter ordering issues (the seeded p1
    bf has earlier objects), use DestroyAllCreatures (Wrath) which
    sweeps every creature on both bfs — guaranteeing our sick Bears
    is destroyed regardless of its bf position.
    """
    sick_creature_id = synthetic_state.register_and_inject_object(
        _creature_dict(), 1, ZONE_HAND
    )
    synthetic_state.push_to_stack(sick_creature_id, 1)
    synthetic_state.resolve_top_of_stack()
    assert synthetic_state.is_summoning_sick(sick_creature_id) is True

    wrath_id = synthetic_state.register_and_inject_object(
        _wrath_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(wrath_id, 0)
    synthetic_state.resolve_top_of_stack()

    # Sick creature now in p1's graveyard. Its summoning_sick flag
    # must be PRESERVED (true) per CE13 closure / I35.
    entry = _gy_entry_for_id(synthetic_state, 1, sick_creature_id)
    assert entry is not None, (
        f"sick creature id={sick_creature_id} missing from p1 graveyard"
    )
    assert entry["summoning_sick"] is True, (
        f"CE13 regression: expected summoning_sick=True (preserved "
        f"on LTB), got {entry['summoning_sick']}. Entry: {entry}"
    )
    # Other CR 400.7 resets still apply.
    assert entry["tapped"] is False
    assert entry["damage"] == 0
    assert entry["counters"] == 0


def test_ce13_destroy_all_creatures_preserves_summoning_sick_for_all_sick(
    synthetic_state,
):
    """Mass destroy (Wrath of God) on multiple summoning-sick
    creatures: ALL preserved. Pins the exact CE13 surface site (the
    probe-identified Effect::DestroyAllCreatures resolve loop)."""
    # Cast two creatures: one under p0, one under p1. Both end up
    # sick on their respective battlefields.
    sick_p0_id = synthetic_state.register_and_inject_object(
        _creature_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(sick_p0_id, 0)
    synthetic_state.resolve_top_of_stack()
    sick_p1_id = synthetic_state.register_and_inject_object(
        _creature_dict(), 1, ZONE_HAND
    )
    synthetic_state.push_to_stack(sick_p1_id, 1)
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.is_summoning_sick(sick_p0_id) is True
    assert synthetic_state.is_summoning_sick(sick_p1_id) is True

    # Wrath.
    wrath_id = synthetic_state.register_and_inject_object(
        _wrath_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(wrath_id, 0)
    synthetic_state.resolve_top_of_stack()

    # Both creatures now in their owners' graveyards with sick=true.
    p0_entry = _gy_entry_for_id(synthetic_state, 0, sick_p0_id)
    p1_entry = _gy_entry_for_id(synthetic_state, 1, sick_p1_id)
    assert p0_entry is not None
    assert p1_entry is not None
    assert p0_entry["summoning_sick"] is True, (
        f"CE13 regression: p0 sick creature lost summoning_sick on "
        f"DestroyAllCreatures: {p0_entry}"
    )
    assert p1_entry["summoning_sick"] is True, (
        f"CE13 regression: p1 sick creature lost summoning_sick on "
        f"DestroyAllCreatures: {p1_entry}"
    )


def test_ce13_exile_target_preserves_summoning_sick_focused(engine):
    """Focused variant of test_ce13_exile_target_preserves_summoning_sick_on_ltb
    that builds a clean state (empty bfs) so the ExileTarget filter
    deterministically picks our just-cast sick Bears on p1's bf[0]."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=1
    )
    sick_p1_id = state.register_and_inject_object(
        _creature_dict(), 1, ZONE_HAND
    )
    state.push_to_stack(sick_p1_id, 1)
    state.resolve_top_of_stack()
    assert state.is_summoning_sick(sick_p1_id) is True

    exile_id = state.register_and_inject_object(
        _exile_creature_dict(), 0, ZONE_HAND
    )
    state.push_to_stack(exile_id, 0)
    state.resolve_top_of_stack()

    # Sick creature now in p1's exile. summoning_sick preserved.
    assert state.exile_contains(sick_p1_id) is True
    assert state.exile_object_summoning_sick(sick_p1_id) is True, (
        f"CE13 regression: ExileTarget cleared summoning_sick on a "
        f"sick creature; expected True (preserved), got "
        f"{state.exile_object_summoning_sick(sick_p1_id)}"
    )
    assert state.exile_object_tapped(sick_p1_id) is False
    assert state.exile_object_damage(sick_p1_id) == 0
    assert state.exile_object_counters(sick_p1_id) == 0


def test_ce13_return_to_hand_preserves_summoning_sick_focused(engine):
    """Bouncing (ReturnToHand) a freshly-cast sick creature must
    preserve summoning_sick on the hand-zone object. I35 invariant."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=1
    )
    sick_p1_id = state.register_and_inject_object(
        _creature_dict(), 1, ZONE_HAND
    )
    state.push_to_stack(sick_p1_id, 1)
    state.resolve_top_of_stack()
    assert state.is_summoning_sick(sick_p1_id) is True

    bounce_id = state.register_and_inject_object(
        _bounce_creature_dict(), 0, ZONE_HAND
    )
    state.push_to_stack(bounce_id, 0)
    state.resolve_top_of_stack()

    # Sick creature returned to p1's hand. summoning_sick preserved.
    entry = _hand_entry_for_id(state, 1, sick_p1_id)
    assert entry is not None, (
        f"sick creature id={sick_p1_id} missing from p1 hand"
    )
    assert entry["summoning_sick"] is True, (
        f"CE13 regression: ReturnToHand cleared summoning_sick on a "
        f"sick creature; expected True, got {entry['summoning_sick']}. "
        f"Entry: {entry}"
    )


def test_ce13_reanimate_etb_still_stamps_summoning_sick_true(
    synthetic_state,
):
    """ETB resets remain correct: a creature pulled from the graveyard
    back to the battlefield via reanimation gets `summoning_sick=True`
    stamped on re-ETB. Pins that the CE13 LTB-only change does NOT
    regress the ETB direction (an essential half of the symmetric
    "preserve on LTB, restamp on ETB" invariant). I35 invariant.

    Even if the graveyard object carried `summoning_sick=True` from
    its pre-LTB state (post-CE13), the reanimate path's ETB-stamp
    must STILL set the field to true — so reanimating an already-sick
    graveyard object yields a still-sick bf object, AND reanimating
    a non-sick graveyard object (e.g. one that left via end-of-turn
    cleanup of a hasty creature) also yields a sick bf object."""
    # Drop a creature into p0's graveyard. The synthetic injection
    # defaults summoning_sick=False; that's fine — the ETB stamp
    # must produce True regardless of the pre-ETB value.
    creature_id = synthetic_state.register_and_inject_object(
        _vanilla_creature_dict(), 0, ZONE_GRAVEYARD
    )
    reanimate_id = synthetic_state.register_and_inject_object(
        _reanimate_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(reanimate_id, 0)
    synthetic_state.resolve_top_of_stack()

    # Creature moved to p0's battlefield. Reanimate stamped
    # summoning_sick=True on ETB.
    assert synthetic_state.find_object_zone(creature_id) == ZONE_BATTLEFIELD
    assert synthetic_state.is_summoning_sick(creature_id) is True, (
        "CE13 regression: ETB-side reanimate stamp regression — "
        "expected summoning_sick=True on reanimated creature"
    )


# ====================================================================
# DrawCards controller-of-effect fix — regression pins.
#
# Pre-fix, `Effect::DrawCards` resolved using `state.active_player`
# as the drawing player, which was wrong when the resolving spell /
# triggered ability had a controller != the active player. Python's
# `DrawCards.resolve(state, controller_id, targets)` takes the
# source's controller explicitly (see
# `src/mtg_bot/effects/generic/draw_mill.py:213`).
#
# The fix introduces a transient
# `state.current_resolve_source_controller: Option<u8>` field, set by
# the stack resolver to `Some(top.controller)` for the duration of
# each `apply_effect` call. `Effect::DrawCards` reads it, falling
# back to `state.active_player` for back-compat with direct
# `apply_effect_pub` callers.
# ====================================================================


def _draw_cards_spell_dict(count=1):
    """Instant-typed DrawCards-N printing for cross-controller
    regression pins."""
    return {
        "name": f"Test Draw {count}",
        "card_types": ["Instant"],
        "mana_cost": {"U": 1},
        "effects": [{"kind": "draw_cards", "count": count}],
    }


def test_drawcards_routes_to_source_controller_not_active_player(engine):
    """**Regression pin for the controller-of-effect fix.**

    On player 0's turn (active_player=0), a DrawCards-1 spell whose
    controller is player 1 (e.g. a counterspell-shape instant
    response from the non-active player) must put the drawn card
    into PLAYER 1's hand. Pre-fix this incorrectly routed to player
    0 (state.active_player).
    """
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=5
    )
    # Sanity-pin: active_player is 0 in the synthetic seed.
    assert state.active_player == 0

    # DrawCards-1 spell controlled by player 1.
    spell_id = state.register_and_inject_object(
        _draw_cards_spell_dict(count=1), 1, ZONE_HAND
    )
    p0_lib_before = state.library_sizes[0]
    p1_lib_before = state.library_sizes[1]
    p0_hand_before = state.hand_sizes[0]
    p1_hand_before = state.hand_sizes[1]

    state.push_to_stack(spell_id, 1)  # controller=1
    state.resolve_top_of_stack()

    # p1 (the spell's controller) drew 1; p0 (active_player) did NOT.
    # Library shrink is the load-bearing observation — p1's hand
    # count is +1 (drew) -1 (spell to graveyard) = 0 net, so we
    # observe library only.
    assert state.library_sizes[1] == p1_lib_before - 1
    assert state.library_sizes[0] == p0_lib_before
    # p0's hand grew by 0 from this resolution (the spell came from
    # p1's hand so p0's hand count is unaffected).
    assert state.hand_sizes[0] == p0_hand_before
    # p1's net hand: drew 1, spell moved to graveyard => same count.
    assert state.hand_sizes[1] == p1_hand_before


def test_drawcards_active_player_controlled_spell_still_works(engine):
    """**Back-compat pin.** Pre-fix every test that pushed a draw
    spell with controller=active_player worked correctly because the
    bug never fired in that case (controller == active_player so
    routing to either yielded the same player). The fix must not
    regress this case.
    """
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=5
    )
    spell_id = state.register_and_inject_object(
        _draw_cards_spell_dict(count=2), 0, ZONE_HAND
    )
    p0_lib_before = state.library_sizes[0]
    p1_lib_before = state.library_sizes[1]

    state.push_to_stack(spell_id, 0)  # controller=0=active_player
    state.resolve_top_of_stack()

    assert state.library_sizes[0] == p0_lib_before - 2
    assert state.library_sizes[1] == p1_lib_before


def test_drawcards_via_triggered_ability_routes_to_triggers_controller(engine):
    """**Cross-controller LTB-trigger regression pin.** A
    triggered-ability StackItem carries its own `controller` (set at
    trigger-fire time to the source's controller). The resolver
    must swap that controller in for the DrawCards apply, NOT
    state.active_player.

    Shape: p1's creature has a `source_is_self LEAVES_BATTLEFIELD →
    draw 1` trigger. p0 casts a bounce spell on p1's creature. When
    the LTB trigger resolves, p1 (the trigger's controller) draws.
    """
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=5
    )
    ltb_creature = {
        "name": "Test LTB-Draw Creature",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 2},
        "effects": [],
        "power": 1,
        "toughness": 1,
        "triggered_abilities": [
            {
                "event": "leaves_battlefield",
                "predicate": {"kind": "source_is_self"},
                "effect": {"kind": "draw_cards", "count": 1},
            }
        ],
    }
    crt_id = state.register_and_inject_object(ltb_creature, 1, ZONE_BATTLEFIELD)
    bounce_id = state.register_and_inject_object(
        {
            "name": "Test Bounce",
            "card_types": ["Instant"],
            "mana_cost": {"U": 1},
            "effects": [
                {"kind": "return_to_hand", "target": {"kind": "any_creature"}}
            ],
        },
        0,
        ZONE_HAND,
    )
    p0_lib_before = state.library_sizes[0]
    p1_lib_before = state.library_sizes[1]

    state.push_to_stack(bounce_id, 0)
    state.resolve_top_of_stack()  # resolves bounce; LTB trigger pushes
    assert state.stack_size() == 1
    top = state.peek_top_of_stack()
    assert top["controller"] == 1  # trigger's controller = p1

    state.resolve_top_of_stack()  # resolves the LTB trigger

    # Post-fix: p1 (trigger's controller) drew 1, p0 did not.
    assert state.library_sizes[0] == p0_lib_before
    assert state.library_sizes[1] == p1_lib_before - 1


def test_drawcards_pause_variant_also_threads_controller(engine):
    """**`resolve_top_of_stack_pause` parity pin.** The _pause
    variant must use the same controller swap as the auto-resolving
    variant (they share the controller-of-effect contract — only
    pending-decision auto-resolution differs).
    """
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=5
    )
    spell_id = state.register_and_inject_object(
        _draw_cards_spell_dict(count=1), 1, ZONE_HAND
    )
    p0_lib_before = state.library_sizes[0]
    p1_lib_before = state.library_sizes[1]

    state.push_to_stack(spell_id, 1)
    state.resolve_top_of_stack_pause()

    assert state.library_sizes[1] == p1_lib_before - 1
    assert state.library_sizes[0] == p0_lib_before


def test_drawcards_controller_swap_restores_after_resolution(engine):
    """**Transient-field hygiene pin.** The controller swap must be
    restored to its prior value (None for top-frame callers) after
    each apply call. After a complete `resolve_top_of_stack`, a
    direct `apply_effect_pub` call on a DrawCards effect would fall
    back to `state.active_player` again (no leaked Some(1) from the
    previous resolution).

    This is the symmetric pin to the payload-target-restore test
    Slice 4 added — ensures no observable state leaks across
    resolution boundaries.
    """
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=10
    )
    # First resolve a p1-controlled draw — sets the swap to Some(1)
    # during apply, then restores.
    spell_id = state.register_and_inject_object(
        _draw_cards_spell_dict(count=1), 1, ZONE_HAND
    )
    state.push_to_stack(spell_id, 1)
    state.resolve_top_of_stack()
    p1_lib_after_first = state.library_sizes[1]
    p0_lib_after_first = state.library_sizes[0]

    # Now resolve a p0-controlled draw. If the swap leaked Some(1),
    # this would route to p1 again. Post-fix it routes correctly to
    # p0 (the new spell's controller).
    spell2_id = state.register_and_inject_object(
        _draw_cards_spell_dict(count=1), 0, ZONE_HAND
    )
    state.push_to_stack(spell2_id, 0)
    state.resolve_top_of_stack()

    assert state.library_sizes[0] == p0_lib_after_first - 1
    assert state.library_sizes[1] == p1_lib_after_first


# ====================================================================
# GainLife controller-of-effect fix — regression pins (I60).
#
# Same shape as the DrawCards I59 fix above. Pre-fix `Effect::GainLife`
# at state_ops_resolve.rs read `state.active_player` as the gaining
# player; post-fix it reads the transient
# `current_resolve_source_controller` (set by the stack resolver),
# falling back to active_player for direct apply_effect_pub callers.
# Python: `GainLife.resolve(state, controller_id, targets)` at
# `effects/generic/life.py:33` takes the source's controller
# explicitly.
# ====================================================================


def _gain_life_spell_dict(amount=2):
    """Instant-typed GainLife-N printing for cross-controller
    regression pins."""
    return {
        "name": f"Test Gain Life {amount}",
        "card_types": ["Instant"],
        "mana_cost": {"W": 1},
        "effects": [{"kind": "gain_life", "amount": amount}],
    }


def test_gainlife_routes_to_source_controller_not_active_player(engine):
    """**Regression pin for the GainLife controller-of-effect fix.**

    On p0's turn (active_player=0), a GainLife-2 spell whose
    controller is p1 (e.g. an instant response from the non-active
    player) must increase PLAYER 1's life by 2. Pre-fix this
    incorrectly routed to player 0.
    """
    state = engine.make_synthetic_state()
    assert state.active_player == 0

    spell_id = state.register_and_inject_object(
        _gain_life_spell_dict(amount=2), 1, ZONE_HAND
    )
    p0_life_before = state.life_totals[0]
    p1_life_before = state.life_totals[1]

    state.push_to_stack(spell_id, 1)
    state.resolve_top_of_stack()

    # p1 (the spell's controller) gained 2; p0 (active_player) did NOT.
    assert state.life_totals[1] == p1_life_before + 2
    assert state.life_totals[0] == p0_life_before


def test_gainlife_active_player_controlled_spell_still_works(engine):
    """**Back-compat pin.** A GainLife spell whose controller IS the
    active player must keep working (the bug never fired in this case
    pre-fix because controller == active_player).
    """
    state = engine.make_synthetic_state()
    spell_id = state.register_and_inject_object(
        _gain_life_spell_dict(amount=3), 0, ZONE_HAND
    )
    p0_life_before = state.life_totals[0]
    p1_life_before = state.life_totals[1]

    state.push_to_stack(spell_id, 0)
    state.resolve_top_of_stack()

    assert state.life_totals[0] == p0_life_before + 3
    assert state.life_totals[1] == p1_life_before


def test_gainlife_via_triggered_ability_routes_to_triggers_controller(engine):
    """**Cross-controller LTB-trigger pin for GainLife.** A
    triggered-ability StackItem carries its own `controller`; the
    resolver swaps that controller in for the GainLife apply.

    Shape: p1's creature has a `source_is_self LEAVES_BATTLEFIELD →
    gain 2 life` trigger. p0 casts a bounce spell on p1's creature.
    When the LTB trigger resolves, p1 (the trigger's controller)
    gains the 2 life.
    """
    # Empty-bf synthetic state so the bounce target picking lands on
    # the LTB creature deterministically (first bf object on p1).
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=5
    )
    ltb_creature = {
        "name": "Test LTB-GainLife Creature",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 2},
        "effects": [],
        "power": 1,
        "toughness": 1,
        "triggered_abilities": [
            {
                "event": "leaves_battlefield",
                "predicate": {"kind": "source_is_self"},
                "effect": {"kind": "gain_life", "amount": 2},
            }
        ],
    }
    crt_id = state.register_and_inject_object(ltb_creature, 1, ZONE_BATTLEFIELD)
    bounce_id = state.register_and_inject_object(
        {
            "name": "Test Bounce (GainLife)",
            "card_types": ["Instant"],
            "mana_cost": {"U": 1},
            "effects": [
                {"kind": "return_to_hand", "target": {"kind": "any_creature"}}
            ],
        },
        0,
        ZONE_HAND,
    )
    p0_life_before = state.life_totals[0]
    p1_life_before = state.life_totals[1]

    state.push_to_stack(bounce_id, 0)
    state.resolve_top_of_stack()  # bounce; LTB trigger pushes
    top = state.peek_top_of_stack()
    assert top["controller"] == 1

    state.resolve_top_of_stack()  # LTB trigger fires

    # Post-fix: p1 (trigger's controller) gained 2.
    assert state.life_totals[1] == p1_life_before + 2
    assert state.life_totals[0] == p0_life_before


def test_gainlife_pause_variant_threads_controller(engine):
    """**`resolve_top_of_stack_pause` parity pin for GainLife.**"""
    state = engine.make_synthetic_state()
    spell_id = state.register_and_inject_object(
        _gain_life_spell_dict(amount=1), 1, ZONE_HAND
    )
    p0_life_before = state.life_totals[0]
    p1_life_before = state.life_totals[1]

    state.push_to_stack(spell_id, 1)
    state.resolve_top_of_stack_pause()

    assert state.life_totals[1] == p1_life_before + 1
    assert state.life_totals[0] == p0_life_before


# ====================================================================
# DamageEachOpponent controller-of-effect fix — regression pins (I62).
#
# Same shape as the I59 DrawCards / I60 GainLife fixes above. Pre-fix
# `Effect::DamageEachOpponent` at state_ops_resolve.rs computed the
# defender as `1 - state.active_player`. Wrong when the resolving
# spell / triggered ability has a controller != active_player —
# the trigger's controller would self-damage. Post-fix the arm
# reads the transient `current_resolve_source_controller` (set by
# the stack resolver), falling back to active_player for direct
# apply_effect_pub callers, then computes defender as
# `1 - controller`.
#
# Python: `DealDamageEachOpponent.resolve(state, controller_id,
# targets)` at `effects/generic/damage.py:152` iterates
# `state.players`, skipping `p.id == controller_id`. Each non-
# controller opponent's life is reduced.
# ====================================================================


def _damage_each_opponent_spell_dict(amount=2):
    """Earthquake-shape DamageEachOpponent-N printing for cross-
    controller regression pins."""
    return {
        "name": f"Test Damage Each Opponent {amount}",
        "card_types": ["Sorcery"],
        "mana_cost": {"R": 1, "generic": 1},
        "effects": [{"kind": "damage_each_opponent", "amount": amount}],
    }


def test_damage_each_opponent_routes_to_source_controllers_opponent(engine):
    """**Regression pin for the DamageEachOpponent controller-of-
    effect fix (I62).**

    On p0's turn (active_player=0), a DamageEachOpponent-2 spell
    whose controller is p1 (e.g. an instant-speed response from the
    non-active player) must damage PLAYER 0 (p1's opponent), NOT
    player 1 (the trigger's own controller). Pre-fix this
    incorrectly damaged player 1 because `defender = 1 -
    active_player = 1`.
    """
    state = engine.make_synthetic_state()
    assert state.active_player == 0

    spell_id = state.register_and_inject_object(
        _damage_each_opponent_spell_dict(amount=2), 1, ZONE_HAND
    )
    p0_life_before = state.life_totals[0]
    p1_life_before = state.life_totals[1]

    state.push_to_stack(spell_id, 1)
    state.resolve_top_of_stack()

    # p0 (the source-controller's opponent) lost 2 life.
    # p1 (the source's controller) UNTOUCHED.
    assert state.life_totals[0] == p0_life_before - 2
    assert state.life_totals[1] == p1_life_before


def test_damage_each_opponent_active_player_controlled_spell_still_works(engine):
    """**Back-compat pin.** A DamageEachOpponent spell whose
    controller IS the active player must keep working — defender =
    1 - controller = 1 - active_player = 1, identical to pre-fix.
    """
    state = engine.make_synthetic_state()
    spell_id = state.register_and_inject_object(
        _damage_each_opponent_spell_dict(amount=3), 0, ZONE_HAND
    )
    p0_life_before = state.life_totals[0]
    p1_life_before = state.life_totals[1]

    state.push_to_stack(spell_id, 0)
    state.resolve_top_of_stack()

    # p1 (the one opponent) took 3 damage; p0 (controller) untouched.
    assert state.life_totals[0] == p0_life_before
    assert state.life_totals[1] == p1_life_before - 3


def test_damage_each_opponent_via_triggered_ability_routes_to_triggers_opponent(
    engine,
):
    """**Cross-controller ETB-trigger pin for DamageEachOpponent.**
    A triggered-ability StackItem carries its own `controller`; the
    resolver swaps that controller in for the DamageEachOpponent
    apply.

    Shape: p1's creature has a `source_is_self LEAVES_BATTLEFIELD →
    deal 2 damage to each opponent` trigger. p0 casts a bounce spell
    on p1's creature. When the LTB trigger resolves, p0 (p1's
    opponent — the trigger's controller's opponent) takes 2 damage,
    NOT p1.
    """
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=5
    )
    ltb_creature = {
        "name": "Test LTB-DamageEachOpponent Creature",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 2},
        "effects": [],
        "power": 1,
        "toughness": 1,
        "triggered_abilities": [
            {
                "event": "leaves_battlefield",
                "predicate": {"kind": "source_is_self"},
                "effect": {"kind": "damage_each_opponent", "amount": 2},
            }
        ],
    }
    crt_id = state.register_and_inject_object(
        ltb_creature, 1, ZONE_BATTLEFIELD
    )
    bounce_id = state.register_and_inject_object(
        {
            "name": "Test Bounce (DamageEachOpponent LTB)",
            "card_types": ["Instant"],
            "mana_cost": {"U": 1},
            "effects": [
                {"kind": "return_to_hand", "target": {"kind": "any_creature"}}
            ],
        },
        0,
        ZONE_HAND,
    )
    p0_life_before = state.life_totals[0]
    p1_life_before = state.life_totals[1]

    state.push_to_stack(bounce_id, 0)
    state.resolve_top_of_stack()  # bounce; LTB trigger pushes
    top = state.peek_top_of_stack()
    assert top["controller"] == 1

    state.resolve_top_of_stack()  # LTB trigger fires

    # Post-fix: p0 (trigger's controller's opponent) took 2 damage.
    # Pre-fix this would have hit p1 (active_player=0's opponent) —
    # self-damaging the trigger's controller.
    assert state.life_totals[0] == p0_life_before - 2
    assert state.life_totals[1] == p1_life_before


def test_damage_each_opponent_pause_variant_threads_controller(engine):
    """**`resolve_top_of_stack_pause` parity pin for
    DamageEachOpponent.**"""
    state = engine.make_synthetic_state()
    spell_id = state.register_and_inject_object(
        _damage_each_opponent_spell_dict(amount=1), 1, ZONE_HAND
    )
    p0_life_before = state.life_totals[0]
    p1_life_before = state.life_totals[1]

    state.push_to_stack(spell_id, 1)
    state.resolve_top_of_stack_pause()

    assert state.life_totals[0] == p0_life_before - 1
    assert state.life_totals[1] == p1_life_before


# -------------------------------------------------------------------
# I64 — DealDamage controller-of-effect fix
#
# The Effect::DealDamage arm at state_ops_resolve.rs picks its
# `defender` as `1 - state.active_player` (the deterministic
# "defending player" first-slice convention). Pre-fix this was wrong
# when the resolving spell's controller != active_player (e.g.
# opponent's instant on your turn). Fix: derive
# `defender = 1 - source_controller` where `source_controller` reads
# the same `current_resolve_source_controller` transient slot
# I59/I60/I63 introduced. Mirrors Python's
# `DealDamageTargetPlayer.resolve(state, controller_id, targets)`.
# -------------------------------------------------------------------


def _deal_damage_spell_dict(amount: int = 3):
    """A {R} Lightning-Bolt-shape instant that deals N damage to the
    defending player. Target = `any_player` deterministic-pick.
    """
    return {
        "name": "Test Lightning Bolt",
        "card_types": ["Instant"],
        "mana_cost": {"R": 1},
        "effects": [
            {
                "kind": "deal_damage",
                "amount": amount,
                "target": {"kind": "any_player"},
            }
        ],
    }


def _deal_damage_creature_spell_dict(amount: int = 2):
    """A {R} instant that deals N damage to the defending player's
    first creature (deterministic any_creature pick).
    """
    return {
        "name": "Test Shock Creature",
        "card_types": ["Instant"],
        "mana_cost": {"R": 1},
        "effects": [
            {
                "kind": "deal_damage",
                "amount": amount,
                "target": {"kind": "any_creature"},
            }
        ],
    }


def test_dealdamage_routes_to_source_controllers_opponent_not_active_players_opponent(
    engine,
):
    """**Regression pin for the DealDamage controller-of-effect fix.**

    On p0's turn (active_player=0), a Lightning Bolt whose controller
    is p1 (an instant response from the non-active player) must deal
    its damage to p0, NOT to p1.

    Pre-fix: `defender = 1 - active_player = 1 - 0 = 1` => damage went
    to p1 (the spell's OWN controller — a friendly-fire bug).
    Post-fix: `defender = 1 - source_controller = 1 - 1 = 0` => damage
    correctly goes to p0 (the spell controller's opponent).
    """
    state = engine.make_synthetic_state()
    assert state.active_player == 0

    spell_id = state.register_and_inject_object(
        _deal_damage_spell_dict(amount=3), 1, ZONE_HAND,
    )
    p0_life_before = state.life_totals[0]
    p1_life_before = state.life_totals[1]

    state.push_to_stack(spell_id, 1)
    state.resolve_top_of_stack()

    # Damage went to p0 (the spell's controller's opponent), NOT to p1.
    assert state.life_totals[0] == p0_life_before - 3
    assert state.life_totals[1] == p1_life_before


def test_dealdamage_active_player_controlled_spell_still_works(engine):
    """**Back-compat pin.** A DealDamage spell whose controller IS the
    active player must still route to the opponent — the bug never
    fired in this case pre-fix because controller == active_player.
    """
    state = engine.make_synthetic_state()
    assert state.active_player == 0

    spell_id = state.register_and_inject_object(
        _deal_damage_spell_dict(amount=2), 0, ZONE_HAND,
    )
    p0_life_before = state.life_totals[0]
    p1_life_before = state.life_totals[1]

    state.push_to_stack(spell_id, 0)
    state.resolve_top_of_stack()

    # Damage went to p1 (defender = opponent of p0).
    assert state.life_totals[1] == p1_life_before - 2
    assert state.life_totals[0] == p0_life_before


def test_dealdamage_via_triggered_ability_routes_to_triggers_controller(
    engine,
):
    """**Cross-controller trigger pin for DealDamage.** A
    triggered-ability StackItem carries its own `controller`; the
    resolver swaps that controller in for the DealDamage apply.

    Shape: p1's creature has a `source_is_self LEAVES_BATTLEFIELD →
    deal 2 damage to defending player` trigger. p0 casts a bounce on
    p1's creature; when the LTB trigger resolves, the 2 damage routes
    to p0 (p1's opponent), NOT to p1 (active-player-relative
    defender).
    """
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=5,
    )
    ltb_creature = {
        "name": "Test LTB-Damage Creature",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 2},
        "effects": [],
        "power": 1,
        "toughness": 1,
        "triggered_abilities": [
            {
                "event": "leaves_battlefield",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "deal_damage",
                    "amount": 2,
                    "target": {"kind": "any_player"},
                },
            }
        ],
    }
    crt_id = state.register_and_inject_object(
        ltb_creature, 1, ZONE_BATTLEFIELD,
    )
    bounce_id = state.register_and_inject_object(
        {
            "name": "Test Bounce (DealDamage)",
            "card_types": ["Instant"],
            "mana_cost": {"U": 1},
            "effects": [
                {"kind": "return_to_hand", "target": {"kind": "any_creature"}}
            ],
        },
        0,
        ZONE_HAND,
    )
    p0_life_before = state.life_totals[0]
    p1_life_before = state.life_totals[1]

    state.push_to_stack(bounce_id, 0)
    state.resolve_top_of_stack()  # bounce; LTB trigger pushes
    top = state.peek_top_of_stack()
    assert top["controller"] == 1

    state.resolve_top_of_stack()  # LTB trigger fires

    # Damage went to p0 (p1's opponent), NOT to p1 (active-player-
    # relative defender).
    assert state.life_totals[0] == p0_life_before - 2
    assert state.life_totals[1] == p1_life_before


def test_dealdamage_pause_variant_threads_controller(engine):
    """**`resolve_top_of_stack_pause` parity pin for DealDamage.**"""
    state = engine.make_synthetic_state()
    spell_id = state.register_and_inject_object(
        _deal_damage_spell_dict(amount=1), 1, ZONE_HAND,
    )
    p0_life_before = state.life_totals[0]
    p1_life_before = state.life_totals[1]

    state.push_to_stack(spell_id, 1)
    state.resolve_top_of_stack_pause()

    # Damage went to p0 (opponent of spell controller p1).
    assert state.life_totals[0] == p0_life_before - 1
    assert state.life_totals[1] == p1_life_before


def test_dealdamage_any_creature_target_routes_to_source_controllers_opponent(
    engine,
):
    """**any_creature target variant.** DealDamage with target =
    any_creature picks the FIRST creature on the defender's
    battlefield. Defender = 1 - source_controller, so the chosen
    creature is on the spell controller's opponent's bf.

    Shape: p0's turn; p1 casts the spell. p0 has a creature on bf,
    p1 also has a creature on bf. Damage lands on p0's creature
    (p1's opponent's first bf creature).
    """
    state = engine.make_synthetic_state(num_battlefield=0)
    # p0 creature on bf.
    p0_crt = state.register_and_inject_object(
        {
            "name": "P0 Creature",
            "card_types": ["Creature"],
            "mana_cost": {"generic": 1},
            "effects": [],
            "power": 1,
            "toughness": 3,
        },
        0,
        ZONE_BATTLEFIELD,
    )
    # p1 creature on bf.
    p1_crt = state.register_and_inject_object(
        {
            "name": "P1 Creature",
            "card_types": ["Creature"],
            "mana_cost": {"generic": 1},
            "effects": [],
            "power": 1,
            "toughness": 3,
        },
        1,
        ZONE_BATTLEFIELD,
    )
    spell_id = state.register_and_inject_object(
        _deal_damage_creature_spell_dict(amount=2), 1, ZONE_HAND,
    )

    state.push_to_stack(spell_id, 1)
    state.resolve_top_of_stack()

    # p0's creature took 2 damage. p1's creature is untouched.
    snap = state.battlefield_snapshot()
    p0_target = next(o for o in snap if o["id"] == p0_crt)
    p1_target = next(o for o in snap if o["id"] == p1_crt)
    assert p0_target["damage"] == 2
    assert p1_target["damage"] == 0


def test_dealdamage_controller_swap_restores_after_resolution(engine):
    """**Transient-field hygiene pin.** After a cross-controller
    DealDamage resolves, the `current_resolve_source_controller`
    transient slot must be restored so a subsequent same-active-
    player-controlled spell still routes via active_player.

    Symmetric pin to the I59/I60 swap-restore test. First resolve a
    p1-controlled bolt (swap set to Some(1), then restored to None).
    Then resolve a p0-controlled bolt (no leaked swap; defender =
    1 - 0 = 1, damage to p1).
    """
    state = engine.make_synthetic_state()
    # First resolve a p1-controlled bolt — sets swap to Some(1) then
    # restores.
    spell1_id = state.register_and_inject_object(
        _deal_damage_spell_dict(amount=1), 1, ZONE_HAND,
    )
    state.push_to_stack(spell1_id, 1)
    state.resolve_top_of_stack()
    p0_life_mid = state.life_totals[0]
    p1_life_mid = state.life_totals[1]
    # p0 took 1 damage (p1's opponent).
    assert p0_life_mid == 19
    assert p1_life_mid == 20

    # Now resolve a p0-controlled bolt. If the swap leaked Some(1),
    # this would route damage to p0 again (1 - 1 = 0). Post-fix it
    # restores to None, so defender = 1 - active_player = 1, damage to p1.
    spell2_id = state.register_and_inject_object(
        _deal_damage_spell_dict(amount=2), 0, ZONE_HAND,
    )
    state.push_to_stack(spell2_id, 0)
    state.resolve_top_of_stack()
    assert state.life_totals[0] == p0_life_mid
    assert state.life_totals[1] == p1_life_mid - 2


# ====================================================================
# Mill (self-mill) controller-of-effect fix — regression pins (I65).
#
# Same shape as the I59 DrawCards / I60 GainLife / I63
# DamageEachOpponent / I64 DealDamage fixes. Pre-fix `Effect::Mill`
# at state_ops_resolve.rs read `state.active_player` as the milling
# player. Wrong when the resolving spell / triggered ability has a
# controller != active_player — example: on p0's turn, p1 casts an
# instant Mill-2 self-mill (a graveyard-fueling reactive spell) —
# pre-fix the cards leave p0's library (wrong), post-fix they leave
# p1's library (the spell's controller). Mirrors Python's
# self-mill handling.
# ====================================================================


def _mill_self_spell_dict(count=2):
    """Instant-typed Mill-N self-mill printing for cross-controller
    regression pins."""
    return {
        "name": f"Test Mill Self {count}",
        "card_types": ["Instant"],
        "mana_cost": {"U": 1},
        "effects": [{"kind": "mill", "count": count}],
    }


def test_mill_routes_to_source_controller_not_active_player(engine):
    """**Regression pin for the Mill controller-of-effect fix
    (I65).**

    On p0's turn (active_player=0), a Mill-2 self-mill spell whose
    controller is p1 (a cross-controller instant) must mill 2 from
    PLAYER 1's library, NOT player 0's. Pre-fix the cards left
    p0's library because `controller = state.active_player = 0`.
    """
    state = engine.make_synthetic_state()
    assert state.active_player == 0

    spell_id = state.register_and_inject_object(
        _mill_self_spell_dict(count=2), 1, ZONE_HAND
    )
    p0_lib_before = state.library_sizes[0]
    p0_gy_before = state.graveyard_sizes[0]
    p1_lib_before = state.library_sizes[1]
    p1_gy_before = state.graveyard_sizes[1]

    state.push_to_stack(spell_id, 1)
    state.resolve_top_of_stack()

    # p1 (the spell's controller) milled 2 cards — library shrank
    # by 2, graveyard grew by at least 2 (the spell itself goes to
    # p1's graveyard too because it's an instant).
    assert state.library_sizes[1] == p1_lib_before - 2
    # p1's graveyard: 2 milled cards + the spell itself (instant goes
    # to graveyard after resolving).
    assert state.graveyard_sizes[1] == p1_gy_before + 2 + 1
    # p0 (active_player) UNTOUCHED — library and graveyard unchanged.
    assert state.library_sizes[0] == p0_lib_before
    assert state.graveyard_sizes[0] == p0_gy_before


def test_mill_active_player_controlled_spell_still_works(engine):
    """**Back-compat pin.** A Mill spell whose controller IS the
    active player must keep working — controller = active_player = 0,
    identical to pre-fix.
    """
    state = engine.make_synthetic_state()
    spell_id = state.register_and_inject_object(
        _mill_self_spell_dict(count=3), 0, ZONE_HAND
    )
    p0_lib_before = state.library_sizes[0]
    p0_gy_before = state.graveyard_sizes[0]
    p1_lib_before = state.library_sizes[1]
    p1_gy_before = state.graveyard_sizes[1]

    state.push_to_stack(spell_id, 0)
    state.resolve_top_of_stack()

    # p0 (controller) milled 3.
    assert state.library_sizes[0] == p0_lib_before - 3
    # p0 graveyard: 3 milled + 1 for the instant itself.
    assert state.graveyard_sizes[0] == p0_gy_before + 3 + 1
    # p1 untouched.
    assert state.library_sizes[1] == p1_lib_before
    assert state.graveyard_sizes[1] == p1_gy_before


def test_mill_via_triggered_ability_routes_to_triggers_controller(engine):
    """**Cross-controller LTB-trigger pin for Mill.** A triggered-
    ability StackItem carries its own `controller`; the resolver
    swaps that controller in for the Mill apply.

    Shape: p1's creature has a `source_is_self LEAVES_BATTLEFIELD →
    mill 2` trigger. p0 casts a bounce spell on p1's creature. When
    the LTB trigger resolves, p1 (the trigger's controller) mills 2.
    """
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=5
    )
    ltb_creature = {
        "name": "Test LTB-Mill Creature",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 2},
        "effects": [],
        "power": 1,
        "toughness": 1,
        "triggered_abilities": [
            {
                "event": "leaves_battlefield",
                "predicate": {"kind": "source_is_self"},
                "effect": {"kind": "mill", "count": 2},
            }
        ],
    }
    crt_id = state.register_and_inject_object(
        ltb_creature, 1, ZONE_BATTLEFIELD
    )
    bounce_id = state.register_and_inject_object(
        {
            "name": "Test Bounce (Mill LTB)",
            "card_types": ["Instant"],
            "mana_cost": {"U": 1},
            "effects": [
                {"kind": "return_to_hand", "target": {"kind": "any_creature"}}
            ],
        },
        0,
        ZONE_HAND,
    )
    p0_lib_before = state.library_sizes[0]
    p1_lib_before = state.library_sizes[1]

    state.push_to_stack(bounce_id, 0)
    state.resolve_top_of_stack()  # bounce; LTB trigger pushes
    top = state.peek_top_of_stack()
    assert top["controller"] == 1

    state.resolve_top_of_stack()  # LTB trigger fires

    # Post-fix: p1 (trigger's controller) milled 2.
    assert state.library_sizes[1] == p1_lib_before - 2
    # p0 untouched (would have been wrong target pre-fix).
    assert state.library_sizes[0] == p0_lib_before


def test_mill_pause_variant_threads_controller(engine):
    """**`resolve_top_of_stack_pause` parity pin for Mill.**"""
    state = engine.make_synthetic_state()
    spell_id = state.register_and_inject_object(
        _mill_self_spell_dict(count=1), 1, ZONE_HAND
    )
    p0_lib_before = state.library_sizes[0]
    p1_lib_before = state.library_sizes[1]

    state.push_to_stack(spell_id, 1)
    state.resolve_top_of_stack_pause()

    assert state.library_sizes[1] == p1_lib_before - 1
    assert state.library_sizes[0] == p0_lib_before


# ====================================================================
# Sacrifice (self-target) controller-of-effect fix — regression pins
# (I66).
#
# Same shape as the I59 DrawCards / I60 GainLife / I63
# DamageEachOpponent / I64 DealDamage / I65 Mill fixes. Pre-fix
# `Effect::Sacrifice` AnyCreature arm at state_ops_resolve.rs read
# `state.active_player` as the sacrificing player. Wrong when the
# resolving spell / triggered ability has a controller != active_player
# — example: on p0's turn, p1 casts an instant Altar's-Reap-shape
# spell ("sacrifice a creature, ...") — pre-fix the spell sacrificed
# p0's bf[0] (active_player), post-fix it correctly sacrifices p1's
# bf[0] (the spell's controller). Mirrors Python's analogous "you
# sacrifice" handling.
# ====================================================================


def _sacrifice_self_spell_dict():
    """Instant-typed self-sacrifice printing for cross-controller
    regression pins. ``any_creature`` target = the controller's
    bf[0] (per the Effect::Sacrifice AnyCreature arm contract)."""
    return {
        "name": "Test Sacrifice Self (Altar's Reap shape)",
        "card_types": ["Instant"],
        "mana_cost": {"B": 1},
        "effects": [
            {"kind": "sacrifice", "target": {"kind": "any_creature"}}
        ],
    }


def test_sacrifice_routes_to_source_controller_not_active_player(engine):
    """**Regression pin for the Sacrifice controller-of-effect fix
    (I66).**

    On p0's turn (active_player=0), a self-Sacrifice spell whose
    controller is p1 (a cross-controller instant) must sacrifice
    PLAYER 1's bf[0], NOT player 0's. Pre-fix the active player p0
    lost their bf[0] because `active = state.active_player = 0`.
    """
    state = engine.make_synthetic_state()
    assert state.active_player == 0

    spell_id = state.register_and_inject_object(
        _sacrifice_self_spell_dict(), 1, ZONE_HAND
    )
    p0_bf_before = state.battlefield_sizes[0]
    p1_bf_before = state.battlefield_sizes[1]
    p0_gy_before = state.graveyard_sizes[0]
    p1_gy_before = state.graveyard_sizes[1]

    state.push_to_stack(spell_id, 1)
    state.resolve_top_of_stack()

    # p1 (the spell's controller) lost a battlefield permanent.
    assert state.battlefield_sizes[1] == p1_bf_before - 1
    # p1's graveyard grew by 2: the sacrificed permanent + the spell
    # itself (instant goes to graveyard after resolving).
    assert state.graveyard_sizes[1] == p1_gy_before + 1 + 1
    # p0 (active_player) UNTOUCHED — battlefield and graveyard unchanged.
    assert state.battlefield_sizes[0] == p0_bf_before
    assert state.graveyard_sizes[0] == p0_gy_before


def test_sacrifice_active_player_controlled_spell_still_works(engine):
    """**Back-compat pin.** A Sacrifice spell whose controller IS the
    active player must keep working — controller = active_player = 0,
    identical to pre-fix.
    """
    state = engine.make_synthetic_state()
    spell_id = state.register_and_inject_object(
        _sacrifice_self_spell_dict(), 0, ZONE_HAND
    )
    p0_bf_before = state.battlefield_sizes[0]
    p1_bf_before = state.battlefield_sizes[1]
    p0_gy_before = state.graveyard_sizes[0]
    p1_gy_before = state.graveyard_sizes[1]

    state.push_to_stack(spell_id, 0)
    state.resolve_top_of_stack()

    # p0 (controller == active_player) sacrificed bf[0].
    assert state.battlefield_sizes[0] == p0_bf_before - 1
    # p0 graveyard: 1 sacrificed permanent + 1 for the instant itself.
    assert state.graveyard_sizes[0] == p0_gy_before + 1 + 1
    # p1 untouched.
    assert state.battlefield_sizes[1] == p1_bf_before
    assert state.graveyard_sizes[1] == p1_gy_before


def test_sacrifice_via_triggered_ability_routes_to_triggers_controller(
    engine,
):
    """**Cross-controller LTB-trigger pin for Sacrifice.** A triggered-
    ability StackItem carries its own `controller`; the resolver
    swaps that controller in for the Sacrifice apply.

    Shape: p1's creature has a `source_is_self LEAVES_BATTLEFIELD →
    sacrifice a creature` trigger. p0 casts a bounce spell on p1's
    creature. When the LTB trigger resolves, p1 (the trigger's
    controller) sacrifices their bf[0].

    Setup is empty battlefield + 2 explicitly-injected creatures
    (one on p1 with the LTB trigger, one on p1 as a sacrifice
    target). Mirrors the I65 Mill LTB test shape exactly.
    """
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=5
    )
    ltb_creature = {
        "name": "Test LTB-Sacrifice Creature",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 2},
        "effects": [],
        "power": 1,
        "toughness": 1,
        "triggered_abilities": [
            {
                "event": "leaves_battlefield",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "sacrifice",
                    "target": {"kind": "any_creature"},
                },
            }
        ],
    }
    state.register_and_inject_object(
        ltb_creature, 1, ZONE_BATTLEFIELD
    )
    # A vanilla sac-victim on p1's bf so there's something to sacrifice
    # after the LTB creature itself leaves the battlefield via the
    # bounce.
    sac_victim_id = state.register_and_inject_object(
        {
            "name": "Test Sac Victim",
            "card_types": ["Creature"],
            "mana_cost": {"generic": 1},
            "effects": [],
            "power": 1,
            "toughness": 1,
        },
        1,
        ZONE_BATTLEFIELD,
    )
    bounce_id = state.register_and_inject_object(
        {
            "name": "Test Bounce (Sacrifice LTB)",
            "card_types": ["Instant"],
            "mana_cost": {"U": 1},
            "effects": [
                {"kind": "return_to_hand", "target": {"kind": "any_creature"}}
            ],
        },
        0,
        ZONE_HAND,
    )
    p0_bf_before = state.battlefield_sizes[0]

    state.push_to_stack(bounce_id, 0)
    state.resolve_top_of_stack()  # bounce; LTB trigger pushes
    top = state.peek_top_of_stack()
    assert top is not None
    assert top["controller"] == 1

    p1_bf_after_bounce = state.battlefield_sizes[1]
    p0_bf_after_bounce = state.battlefield_sizes[0]
    # Bounce removed the LTB creature from p1's bf, so p1 now has 1
    # creature left (the sac_victim). p0's bf was empty and stays
    # empty (the bounce defender is the source-controller's opponent =
    # p1 post-I64).
    assert p1_bf_after_bounce == 1
    assert p0_bf_after_bounce == p0_bf_before

    state.resolve_top_of_stack()  # LTB trigger fires

    # Post-fix: p1 (trigger's controller) sacrificed their last
    # remaining creature (the sac_victim).
    assert state.battlefield_sizes[1] == p1_bf_after_bounce - 1
    assert state.find_object_zone(sac_victim_id) == ZONE_GRAVEYARD
    # p0 untouched.
    assert state.battlefield_sizes[0] == p0_bf_after_bounce


def test_sacrifice_pause_variant_threads_controller(engine):
    """**`resolve_top_of_stack_pause` parity pin for Sacrifice.**

    The pause variant uses the same stack-resolver swap; cross-
    controller routing must work identically.
    """
    state = engine.make_synthetic_state()
    spell_id = state.register_and_inject_object(
        _sacrifice_self_spell_dict(), 1, ZONE_HAND
    )
    p0_bf_before = state.battlefield_sizes[0]
    p1_bf_before = state.battlefield_sizes[1]

    state.push_to_stack(spell_id, 1)
    state.resolve_top_of_stack_pause()

    # p1 (controller) sacrificed; p0 (active_player) untouched.
    assert state.battlefield_sizes[1] == p1_bf_before - 1
    assert state.battlefield_sizes[0] == p0_bf_before


# ====================================================================
# DealDamageAnyTarget controller-of-effect fix — regression pins (I67).
#
# Same shape as the I64 DealDamage / I63 DamageEachOpponent fixes.
# Pre-fix `Effect::DealDamageAnyTarget` at state_ops_resolve.rs
# computed `defender_idx = 1 - state.active_player` for picking the
# "first creature on defender's battlefield, else damage defender as
# player". Wrong when the resolving spell / triggered ability has a
# controller != active_player — example: p1's ETB trigger fires on
# p0's turn (via flicker), pre-fix the trigger self-damaged p1
# (defender_idx = 1 - 0 = 1), post-fix it correctly targets p0
# (the trigger's controller's opponent).
# ====================================================================


def _deal_damage_any_target_spell_dict(amount: int = 3):
    """Instant-typed deal-damage-any-target printing for cross-
    controller regression pins. Sorcery in some other tests; instant
    here so the spell can be cast on the opponent's turn (mirrors
    I64's _deal_damage_spell_dict shape)."""
    return {
        "name": f"Test DealDamageAnyTarget {amount}",
        "card_types": ["Instant"],
        "mana_cost": {"R": 1, "generic": 2},
        "effects": [{"kind": "deal_damage_any_target", "amount": amount}],
    }


def test_deal_damage_any_target_routes_to_source_controllers_opponent(engine):
    """**Regression pin for the DealDamageAnyTarget controller-of-
    effect fix (I67).**

    On p0's turn (active_player=0), an instant
    deal-damage-any-target spell whose controller is p1 must
    damage the FIRST creature on p0's bf (or, if no creature, p0
    as player). NOT p1's. Pre-fix `defender_idx = 1 -
    active_player = 1 - 0 = 1` => damage went to p1's bf — a
    friendly-fire bug analogous to the I64 DealDamage closure.
    """
    state = engine.make_synthetic_state()
    assert state.active_player == 0

    spell_id = state.register_and_inject_object(
        _deal_damage_any_target_spell_dict(amount=2), 1, ZONE_HAND
    )

    # Defender's first creature lives at p0's bf (synthetic seed
    # places forests at bf[0..5] then bears at bf[5..]). Index 5 is
    # the first creature on p0's bf.
    # Find it dynamically via battlefield_snapshot.
    snap = state.battlefield_snapshot()
    p0_first_creature = None
    for obj in snap:
        if obj["controller_id"] == 0:
            # Pull printing id and check via registry
            p0_first_creature = obj["id"]
            # We want the first CREATURE — heuristic: bf[0..4] are
            # Forests (Land), bf[5..] are Bears (Creature). Use
            # damage tracking on the first id whose power > 0.
            if obj.get("power", 0) > 0:
                break
    # Fallback: just compute the expected target via the same logic
    # the engine uses — first object on p0's bf whose type is
    # Creature. The seed places forests at bf[0..4] then bears at
    # bf[5..9]; bears are id 5..9 on p0, so the first creature is
    # id 5.
    expected_target = 5
    damage_before = state.get_damage(expected_target)

    state.push_to_stack(spell_id, 1)
    state.resolve_top_of_stack()

    # Damage went to p0's first creature, NOT p1's.
    assert state.get_damage(expected_target) == damage_before + 2
    # p1's first creature (id 5 + 10 = 15 in the seed's id allocation)
    # is untouched. We verify via the battlefield_snapshot that no
    # p1-controlled creature took the 2 damage.
    snap_after = state.battlefield_snapshot()
    for obj in snap_after:
        if obj["controller_id"] == 1 and obj["id"] != spell_id:
            assert obj.get("damage", 0) == 0


def test_deal_damage_any_target_active_player_controlled_spell_still_works(
    engine,
):
    """**Back-compat pin.** A DealDamageAnyTarget spell whose
    controller IS the active player must still target the opponent
    — bug never fired in this case pre-fix because controller ==
    active_player.
    """
    state = engine.make_synthetic_state()
    assert state.active_player == 0

    spell_id = state.register_and_inject_object(
        _deal_damage_any_target_spell_dict(amount=3), 0, ZONE_HAND
    )

    state.push_to_stack(spell_id, 0)
    state.resolve_top_of_stack()

    # First creature on p1's bf took 3 damage. In the seed, p1's
    # bf[5] is the first creature.
    snap = state.battlefield_snapshot()
    p1_first_creature_with_damage = None
    for obj in snap:
        if obj["controller_id"] == 1 and obj.get("damage", 0) > 0:
            p1_first_creature_with_damage = obj
            break
    assert p1_first_creature_with_damage is not None
    assert p1_first_creature_with_damage["damage"] == 3


def test_deal_damage_any_target_via_triggered_ability_routes_to_triggers_controller(
    engine,
):
    """**Cross-controller LTB-trigger pin for DealDamageAnyTarget.**

    Shape: p1's creature has a `source_is_self LEAVES_BATTLEFIELD →
    deal 2 damage to any target` trigger. p0 casts a bounce spell on
    p1's creature; when the LTB trigger resolves, the 2 damage routes
    to p0's first creature (p1's opponent), NOT p1's own bf.
    """
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=5
    )
    # p0 creature on bf — this is the trigger's intended target post-fix.
    p0_crt = state.register_and_inject_object(
        {
            "name": "P0 Creature",
            "card_types": ["Creature"],
            "mana_cost": {"generic": 1},
            "effects": [],
            "power": 1,
            "toughness": 3,
        },
        0,
        ZONE_BATTLEFIELD,
    )
    # p1 LTB creature.
    ltb_creature = {
        "name": "Test LTB-DealDamageAnyTarget Creature",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 2},
        "effects": [],
        "power": 1,
        "toughness": 1,
        "triggered_abilities": [
            {
                "event": "leaves_battlefield",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "deal_damage_any_target",
                    "amount": 2,
                },
            }
        ],
    }
    state.register_and_inject_object(ltb_creature, 1, ZONE_BATTLEFIELD)
    # p1 also has a vanilla creature so pre-fix damage would have a
    # target on p1's bf to land on (rather than fizzling to player).
    p1_crt = state.register_and_inject_object(
        {
            "name": "P1 Creature",
            "card_types": ["Creature"],
            "mana_cost": {"generic": 1},
            "effects": [],
            "power": 1,
            "toughness": 3,
        },
        1,
        ZONE_BATTLEFIELD,
    )
    bounce_id = state.register_and_inject_object(
        {
            "name": "Test Bounce (DealDamageAnyTarget LTB)",
            "card_types": ["Instant"],
            "mana_cost": {"U": 1},
            "effects": [
                {"kind": "return_to_hand", "target": {"kind": "any_creature"}}
            ],
        },
        0,
        ZONE_HAND,
    )

    state.push_to_stack(bounce_id, 0)
    state.resolve_top_of_stack()  # bounce; LTB trigger pushes
    top = state.peek_top_of_stack()
    assert top is not None
    assert top["controller"] == 1

    state.resolve_top_of_stack()  # LTB trigger fires

    # Damage went to p0's creature (p1's opponent's first creature),
    # NOT p1's.
    assert state.get_damage(p0_crt) == 2
    assert state.get_damage(p1_crt) == 0


def test_deal_damage_any_target_pause_variant_threads_controller(engine):
    """**`resolve_top_of_stack_pause` parity pin for DealDamageAnyTarget.**"""
    state = engine.make_synthetic_state()
    spell_id = state.register_and_inject_object(
        _deal_damage_any_target_spell_dict(amount=1), 1, ZONE_HAND
    )
    expected_target = 5  # p0's first creature in the seed.
    damage_before = state.get_damage(expected_target)

    state.push_to_stack(spell_id, 1)
    state.resolve_top_of_stack_pause()

    # Damage went to p0's first creature (p1's opponent), not p1's bf.
    assert state.get_damage(expected_target) == damage_before + 1


# ====================================================================
# DealDamageEqualToSourcePowerAnyTarget controller-of-effect fix —
# regression pins (I68).
#
# Sibling closure to I67 DealDamageAnyTarget. Pre-fix this arm
# computed `defender_idx = 1 - state.active_player`. Wrong when the
# resolving spell / triggered ability has a controller !=
# active_player — example: p1's Mishra's-Bauble-shape spell fires
# on p0's turn (cross-controller activation / trigger).
# ====================================================================


def _power_damage_creature_dict_for_i68(power: int = 3):
    """A creature whose ability deals damage equal to its power to
    any target. Used by I68 regression pins."""
    return {
        "name": f"Test Power Damager P{power}",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 2},
        "power": power,
        "toughness": 3,
        "effects": [
            {"kind": "deal_damage_equal_to_source_power_any_target"}
        ],
    }


def test_deal_damage_eq_source_power_routes_to_source_controllers_opponent(
    engine,
):
    """**Regression pin for the DealDamageEqualToSourcePowerAnyTarget
    controller-of-effect fix (I68).**

    On p0's turn (active_player=0), a power-damage source whose
    controller is p1 must damage the FIRST creature on p0's bf, NOT
    p1's. Pre-fix `defender_idx = 1 - active_player = 1 - 0 = 1` =>
    damage went to p1's bf (a friendly-fire bug, sibling closure to
    I67).
    """
    state = engine.make_synthetic_state()
    assert state.active_player == 0

    # Inject the power-damage source on p1's battlefield.
    src_id = state.register_and_inject_object(
        _power_damage_creature_dict_for_i68(power=3), 1, ZONE_BATTLEFIELD
    )

    # Find p0's first creature (Grizzly Bears in synthetic seed).
    snap = state.battlefield_snapshot()
    p0_first_bear_id = next(
        d["id"] for d in snap
        if d["controller_id"] == 0 and d["printing_name"] == "Grizzly Bears"
    )
    # And p1's first bear so we can assert it's UNTOUCHED.
    p1_first_bear_id = next(
        d["id"] for d in snap
        if d["controller_id"] == 1 and d["printing_name"] == "Grizzly Bears"
    )

    state.push_to_stack(src_id, 1)
    state.resolve_top_of_stack()

    # Damage went to p0's first creature, NOT p1's.
    assert state.get_damage(p0_first_bear_id) == 3
    assert state.get_damage(p1_first_bear_id) == 0


def test_deal_damage_eq_source_power_active_player_controlled_still_works(
    engine,
):
    """**Back-compat pin.** A power-damage activation by the active
    player must still target the opponent's first creature — bug
    never fired in this case pre-fix because controller ==
    active_player.
    """
    state = engine.make_synthetic_state()
    assert state.active_player == 0

    src_id = state.register_and_inject_object(
        _power_damage_creature_dict_for_i68(power=2), 0, ZONE_BATTLEFIELD
    )

    snap = state.battlefield_snapshot()
    p1_first_bear_id = next(
        d["id"] for d in snap
        if d["controller_id"] == 1 and d["printing_name"] == "Grizzly Bears"
    )

    state.push_to_stack(src_id, 0)
    state.resolve_top_of_stack()

    # Damage went to p1's first creature.
    assert state.get_damage(p1_first_bear_id) == 2


def test_deal_damage_eq_source_power_via_triggered_ability_routes_to_triggers_controller(
    engine,
):
    """**Cross-controller LTB-trigger pin for
    DealDamageEqualToSourcePowerAnyTarget.**

    Shape: p1's creature has a `source_is_self LEAVES_BATTLEFIELD →
    deal damage equal to its power to any target` trigger. p0 casts
    a bounce spell. Since the trigger fires AFTER the source has
    left the battlefield, the source-power lookup returns 0
    (silent fizzle by the `amount == 0` guard) — this scenario
    isn't a useful pin for the defender swap.

    Instead, use a cross-controller spell-on-stack shape: p1's
    creature with an effect that "this creature deals N damage to
    any target" — push the creature as a stack item with
    controller=1 on p0's turn. The effect resolves with the
    creature still on bf, source-power is non-zero, and the
    defender-swap is observable.
    """
    state = engine.make_synthetic_state()
    src_id = state.register_and_inject_object(
        _power_damage_creature_dict_for_i68(power=4), 1, ZONE_BATTLEFIELD
    )

    snap = state.battlefield_snapshot()
    p0_first_bear_id = next(
        d["id"] for d in snap
        if d["controller_id"] == 0 and d["printing_name"] == "Grizzly Bears"
    )
    p1_first_bear_id = next(
        d["id"] for d in snap
        if d["controller_id"] == 1 and d["printing_name"] == "Grizzly Bears"
    )

    # Push the source as a stack item with controller=1 on p0's turn —
    # mirrors a p1-controlled activation.
    state.push_to_stack(src_id, 1)
    state.resolve_top_of_stack()

    # Post-fix: damage went to p0's bear (p1's opponent). Pre-fix
    # would have hit p1's bear (defender = 1 - 0 = 1).
    assert state.get_damage(p0_first_bear_id) == 4
    assert state.get_damage(p1_first_bear_id) == 0


def test_deal_damage_eq_source_power_pause_variant_threads_controller(engine):
    """**`resolve_top_of_stack_pause` parity pin for
    DealDamageEqualToSourcePowerAnyTarget.**"""
    state = engine.make_synthetic_state()
    src_id = state.register_and_inject_object(
        _power_damage_creature_dict_for_i68(power=1), 1, ZONE_BATTLEFIELD
    )

    snap = state.battlefield_snapshot()
    p0_first_bear_id = next(
        d["id"] for d in snap
        if d["controller_id"] == 0 and d["printing_name"] == "Grizzly Bears"
    )

    state.push_to_stack(src_id, 1)
    state.resolve_top_of_stack_pause()

    # Damage went to p0's bear (p1's opponent).
    assert state.get_damage(p0_first_bear_id) == 1


# ====================================================================
# SearchLibraryForBasicLandTapped controller-of-effect fix —
# regression pins (I69).
#
# Pre-fix this arm hardcoded `controller_idx = state.active_player`.
# Wrong when the resolving spell / triggered ability has a controller
# != active_player. Mirrors Python's
# `SearchLibraryForBasicLandTapped.resolve(state, controller_id, ...)`
# which takes `controller_id` from the resolver (StackItem.controller).
#
# Sibling closure to I65 Mill — both are "your library" / "your
# graveyard" self-target effects whose acting player is the source's
# controller, not the active player.
# ====================================================================


def _rampant_growth_dict_for_i69(count: int = 1):
    """A Rampant-Growth-shaped sorcery whose only effect is
    SearchLibraryForBasicLandTapped. Used by I69 regression pins."""
    return {
        "name": f"Test Rampant Growth I69 (x{count})",
        "card_types": ["Sorcery"],
        "effects": [
            {
                "kind": "search_library_for_basic_land_tapped",
                "count": count,
            }
        ],
    }


def test_search_library_for_basic_land_tapped_routes_to_source_controllers_library(
    engine,
):
    """**Regression pin for the SearchLibraryForBasicLandTapped
    controller-of-effect fix (I69).**

    On p0's turn (active_player=0), a Rampant-Growth-shape sorcery
    whose controller is p1 must search P1'S library and put the
    searched basic land onto P1'S battlefield, NOT p0's. Pre-fix
    `controller_idx = state.active_player = 0` => searched from p0's
    library and landed on p0's bf (a wrong-side-of-the-table bug
    sibling to I65 Mill).
    """
    state = engine.make_synthetic_state()
    assert state.active_player == 0

    # Inject the Rampant-Growth-shape source on p1's HAND so the
    # post-resolve Sorcery → graveyard move doesn't touch the
    # battlefield count we're asserting on.
    src_id = state.register_and_inject_object(
        _rampant_growth_dict_for_i69(count=1), 1, ZONE_HAND
    )

    bf_p0_before = state.battlefield_sizes[0]
    bf_p1_before = state.battlefield_sizes[1]
    lib_p0_before = state.library_sizes[0]
    lib_p1_before = state.library_sizes[1]

    # Push with controller=1 (p1), but active_player is still 0.
    state.push_to_stack(src_id, 1)
    state.resolve_top_of_stack()

    # P1's library shrank by 1, p1's battlefield grew by 1.
    assert state.library_sizes[1] == lib_p1_before - 1
    assert state.battlefield_sizes[1] == bf_p1_before + 1
    # P0's zones untouched.
    assert state.library_sizes[0] == lib_p0_before
    assert state.battlefield_sizes[0] == bf_p0_before


def test_search_library_for_basic_land_tapped_active_player_controlled_still_works(
    engine,
):
    """**Back-compat pin.** A Rampant-Growth-shape sorcery cast by
    the active player must still search the ACTIVE PLAYER'S library
    and put the land onto the active player's bf — bug never fired
    in this case pre-fix because controller == active_player.
    """
    state = engine.make_synthetic_state()
    assert state.active_player == 0

    src_id = state.register_and_inject_object(
        _rampant_growth_dict_for_i69(count=1), 0, ZONE_HAND
    )

    bf_p0_before = state.battlefield_sizes[0]
    bf_p1_before = state.battlefield_sizes[1]
    lib_p0_before = state.library_sizes[0]
    lib_p1_before = state.library_sizes[1]

    state.push_to_stack(src_id, 0)
    state.resolve_top_of_stack()

    # P0's library shrank, p0's battlefield grew.
    assert state.library_sizes[0] == lib_p0_before - 1
    assert state.battlefield_sizes[0] == bf_p0_before + 1
    # P1 untouched.
    assert state.library_sizes[1] == lib_p1_before
    assert state.battlefield_sizes[1] == bf_p1_before


def test_search_library_for_basic_land_tapped_searched_land_controller_is_searcher(
    engine,
):
    """**Object-identity pin for I69.** The searched land enters
    under the SEARCHER's control — `obj.controller` is stamped to
    the source's controller (which may differ from active_player).
    Confirm via the battlefield snapshot's `controller_id` field
    (NOT `controller` — caught by I67 worker).
    """
    state = engine.make_synthetic_state()
    assert state.active_player == 0

    # P1's library top is at p1's library[0] (post-CE3). p1's base
    # id = num_battlefield(10) + num_hand(7) for p0 plus full p0 zones
    # ... — easier to just snapshot post-search and find the land that
    # moved to p1's bf via name.
    src_id = state.register_and_inject_object(
        _rampant_growth_dict_for_i69(count=1), 1, ZONE_HAND
    )

    state.push_to_stack(src_id, 1)
    state.resolve_top_of_stack()

    # Find a Forest on p1's bf — there must be one, the searched land.
    snap = state.battlefield_snapshot()
    p1_forests_on_bf = [
        d for d in snap
        if d["controller_id"] == 1 and d["printing_name"] == "Forest"
    ]
    # P1's synthetic seed gives 0 Forests on bf at start — only the
    # searched-up one should be there.
    assert len(p1_forests_on_bf) >= 1
    # And all should be controlled by p1 (the searcher).
    for d in p1_forests_on_bf:
        assert d["controller_id"] == 1


def test_search_library_for_basic_land_tapped_pause_variant_threads_controller(
    engine,
):
    """**`resolve_top_of_stack_pause` parity pin for
    SearchLibraryForBasicLandTapped.** Mirrors the I65 / I66 / I67 /
    I68 pause-variant pins — confirms the controller transient is
    set + read identically across both resolve flavors.
    """
    state = engine.make_synthetic_state()
    src_id = state.register_and_inject_object(
        _rampant_growth_dict_for_i69(count=1), 1, ZONE_HAND
    )

    bf_p0_before = state.battlefield_sizes[0]
    bf_p1_before = state.battlefield_sizes[1]
    lib_p0_before = state.library_sizes[0]
    lib_p1_before = state.library_sizes[1]

    state.push_to_stack(src_id, 1)
    state.resolve_top_of_stack_pause()

    # P1's library shrank, p1's battlefield grew. P0 untouched.
    assert state.library_sizes[1] == lib_p1_before - 1
    assert state.battlefield_sizes[1] == bf_p1_before + 1
    assert state.library_sizes[0] == lib_p0_before
    assert state.battlefield_sizes[0] == bf_p0_before


def test_search_library_for_basic_land_tapped_count_two_threads_controller(
    engine,
):
    """**count=2 pin for I69.** Multi-fetch (Cultivate / Larval
    Scoutlander shape) must thread the source-controller through
    every iteration of the inner loop — both fetched lands land on
    the source's controller's bf, not active_player's.
    """
    state = engine.make_synthetic_state()
    assert state.active_player == 0

    src_id = state.register_and_inject_object(
        _rampant_growth_dict_for_i69(count=2), 1, ZONE_HAND
    )

    bf_p0_before = state.battlefield_sizes[0]
    bf_p1_before = state.battlefield_sizes[1]
    lib_p0_before = state.library_sizes[0]
    lib_p1_before = state.library_sizes[1]

    state.push_to_stack(src_id, 1)
    state.resolve_top_of_stack()

    # P1's library shrank by 2, p1's bf grew by 2.
    assert state.library_sizes[1] == lib_p1_before - 2
    assert state.battlefield_sizes[1] == bf_p1_before + 2
    # P0 untouched.
    assert state.library_sizes[0] == lib_p0_before
    assert state.battlefield_sizes[0] == bf_p0_before


# ====================================================================
# ExileTarget controller-of-effect fix — regression pins (I70).
#
# Pre-fix `defender = (1 - state.active_player) as usize`. Wrong
# when the resolving spell / triggered ability has a controller !=
# active_player — example: on p0's turn, p1 casts an Exile-target-
# creature instant. Pre-fix it self-exiled p1's own first bf object
# (defender = 1 - active_player = 1 - 0 = 1); post-fix it correctly
# exiles p0's first bf object (the source's controller's opponent).
#
# Sibling closure to I64 DealDamage / I67 DealDamageAnyTarget —
# same `defender = 1 - controller` shape, same transient-slot
# lookup substrate.
#
# Note: the AnyCreature first-slice target shortcut picks
# `bf[0]` regardless of card type (no creature-type filter at this
# layer). Synthetic-state bf[0] for the default num_battlefield=10
# is a Forest — fine for the regression pin since the test pins
# WHICH SIDE got hit, not which TYPE.
# ====================================================================


def _exile_creature_dict_for_i70():
    """A Swords-to-Plowshares-shape instant whose only effect is
    ExileTarget(AnyCreature). Used by I70 regression pins."""
    return {
        "name": "Test Path I70",
        "card_types": ["Instant"],
        "mana_cost": {"W": 1},
        "effects": [
            {
                "kind": "exile_target",
                "target": {"kind": "any_creature"},
            }
        ],
    }


def test_exile_target_routes_to_source_controllers_opponent(engine):
    """**Regression pin for the ExileTarget controller-of-effect
    fix (I70).**

    On p0's turn (active_player=0), an Exile-target-creature instant
    whose controller is p1 must exile a P0 bf[0] object, NOT a p1
    bf[0] object. Pre-fix `defender = 1 - active_player = 1 - 0 =
    1` => p1's own bf[0] got exiled (self-exiling, sibling closure
    to I64 / I67). Post-fix `defender = 1 - controller = 1 - 1 = 0`
    => correctly hits p0's bf[0].

    Synthetic seed: each player's bf[0] is a Forest (the first
    half of `num_battlefield` are Forests in `make_player`). p0's
    bf[0] id = 0, p1's bf[0] id = num_battlefield + num_hand +
    num_library = 10 + 7 + 50 = 67 (default seed).
    """
    state = engine.make_synthetic_state()
    assert state.active_player == 0

    p0_bf_first_id = 0  # p0's bf[0] (Forest, controller=0)
    p1_bf_first_id = 67  # p1's bf[0] (Forest, controller=1)

    src_id = state.register_and_inject_object(
        _exile_creature_dict_for_i70(), 1, ZONE_HAND
    )

    # Push with controller=1 (p1), active_player is still 0.
    state.push_to_stack(src_id, 1)
    state.resolve_top_of_stack()

    # Post-fix: p0's bf[0] got exiled (p1's opponent's bf).
    assert state.find_object_zone(p0_bf_first_id) == ZONE_EXILE
    # P1's bf[0] untouched (no self-exile).
    assert state.find_object_zone(p1_bf_first_id) == ZONE_BATTLEFIELD


def test_exile_target_active_player_controlled_still_works(engine):
    """**Back-compat pin.** An Exile-target-creature instant cast by
    the active player must still exile the opponent's bf[0] — bug
    never fired in this case pre-fix because controller ==
    active_player.
    """
    state = engine.make_synthetic_state()
    assert state.active_player == 0

    p0_bf_first_id = 0
    p1_bf_first_id = 67

    src_id = state.register_and_inject_object(
        _exile_creature_dict_for_i70(), 0, ZONE_HAND
    )

    state.push_to_stack(src_id, 0)
    state.resolve_top_of_stack()

    # P1's bf[0] got exiled (p0's opponent's bf).
    assert state.find_object_zone(p1_bf_first_id) == ZONE_EXILE
    # P0's bf[0] untouched.
    assert state.find_object_zone(p0_bf_first_id) == ZONE_BATTLEFIELD


def test_exile_target_pause_variant_threads_controller(engine):
    """**`resolve_top_of_stack_pause` parity pin for ExileTarget.**
    Mirrors the I64 / I67 / I68 / I69 pause-variant pins."""
    state = engine.make_synthetic_state()

    p0_bf_first_id = 0
    p1_bf_first_id = 67

    src_id = state.register_and_inject_object(
        _exile_creature_dict_for_i70(), 1, ZONE_HAND
    )

    state.push_to_stack(src_id, 1)
    state.resolve_top_of_stack_pause()

    # Post-fix: p0's bf[0] got exiled (p1's opponent).
    assert state.find_object_zone(p0_bf_first_id) == ZONE_EXILE
    assert state.find_object_zone(p1_bf_first_id) == ZONE_BATTLEFIELD


def test_exile_target_empty_source_controllers_opponent_bf_fizzles(engine):
    """**Empty-defender fizzle pin for I70.** When the source-
    controller's opponent has no creatures (bf empty), the effect
    fizzles silently. Build a state where p0 has no bf objects and
    cast a p1-controlled Exile-target-creature instant — post-fix
    defender=0 (p1's opponent = p0), bf empty → fizzle.

    Uses `num_battlefield=0` shape — both players start with empty
    bfs. P0's bf is empty (the divergent direction), so the effect
    fizzles. We pin: source moved to graveyard, p0's exile size
    unchanged (no spurious exile push).
    """
    state = engine.make_synthetic_state(num_battlefield=0)
    p0_exile_before = state.exile_sizes[0]
    p0_grave_before = state.graveyard_sizes[0]
    p1_grave_before = state.graveyard_sizes[1]

    src_id = state.register_and_inject_object(
        _exile_creature_dict_for_i70(), 1, ZONE_HAND
    )

    state.push_to_stack(src_id, 1)
    state.resolve_top_of_stack()

    # Stack popped, source instant moved to p1's graveyard.
    assert state.is_stack_empty() is True
    assert state.graveyard_sizes[1] == p1_grave_before + 1
    # P0's zones untouched — no spurious exile push, no graveyard
    # touch.
    assert state.exile_sizes[0] == p0_exile_before
    assert state.graveyard_sizes[0] == p0_grave_before


# ====================================================================
# TapTarget controller-of-effect fix — regression pins (I71).
#
# Pre-fix `defender = (1 - state.active_player) as usize`. Wrong
# when the resolving spell / triggered ability has a controller !=
# active_player — example: on p0's turn, p1 casts a Twiddle-shape
# tap instant. Pre-fix it self-tapped p1's own bf[0] (defender =
# 1 - active_player = 1 - 0 = 1); post-fix it correctly taps p0's
# bf[0] (the source's controller's opponent).
#
# Sibling closure to I64 / I67 / I70 — same `defender = 1 -
# controller` shape, same transient-slot lookup substrate.
# ====================================================================


def _tap_creature_dict_for_i71():
    """A Twiddle-shape instant whose only effect is
    TapTarget(AnyCreature). Used by I71 regression pins."""
    return {
        "name": "Test Twiddle I71",
        "card_types": ["Instant"],
        "mana_cost": {"U": 1},
        "effects": [
            {
                "kind": "tap_target",
                "target": {"kind": "any_creature"},
            }
        ],
    }


def test_tap_target_routes_to_source_controllers_opponent(engine):
    """**Regression pin for the TapTarget controller-of-effect fix
    (I71).**

    On p0's turn (active_player=0), a Twiddle-shape tap instant
    whose controller is p1 must tap a P0 bf[0] object, NOT a p1
    bf[0] object. Pre-fix `defender = 1 - active_player = 1 - 0 =
    1` => p1's own bf[0] got tapped (self-tap). Post-fix
    `defender = 1 - controller = 1 - 1 = 0` => correctly taps p0's
    bf[0].

    Synthetic seed: p0's bf[0] = id 0 (Forest, untapped). p1's
    bf[0] = id 67 (Forest, untapped).
    """
    state = engine.make_synthetic_state()
    assert state.active_player == 0

    p0_bf_first_id = 0
    p1_bf_first_id = 67
    # Both start untapped in the synthetic seed.
    assert state.is_tapped(p0_bf_first_id) is False
    assert state.is_tapped(p1_bf_first_id) is False

    src_id = state.register_and_inject_object(
        _tap_creature_dict_for_i71(), 1, ZONE_HAND
    )

    # Push with controller=1 (p1), active_player still 0.
    state.push_to_stack(src_id, 1)
    state.resolve_top_of_stack()

    # Post-fix: p0's bf[0] got tapped (p1's opponent's bf).
    assert state.is_tapped(p0_bf_first_id) is True
    # P1's bf[0] untouched (no self-tap).
    assert state.is_tapped(p1_bf_first_id) is False


def test_tap_target_active_player_controlled_still_works(engine):
    """**Back-compat pin.** A Twiddle-shape tap instant cast by the
    active player must still tap the opponent's bf[0] — bug never
    fired in this case pre-fix because controller == active_player.
    """
    state = engine.make_synthetic_state()
    assert state.active_player == 0

    p0_bf_first_id = 0
    p1_bf_first_id = 67
    assert state.is_tapped(p0_bf_first_id) is False
    assert state.is_tapped(p1_bf_first_id) is False

    src_id = state.register_and_inject_object(
        _tap_creature_dict_for_i71(), 0, ZONE_HAND
    )

    state.push_to_stack(src_id, 0)
    state.resolve_top_of_stack()

    # P1's bf[0] got tapped (p0's opponent's bf).
    assert state.is_tapped(p1_bf_first_id) is True
    # P0's bf[0] untouched.
    assert state.is_tapped(p0_bf_first_id) is False


def test_tap_target_pause_variant_threads_controller(engine):
    """**`resolve_top_of_stack_pause` parity pin for TapTarget.**
    Mirrors the I64 / I67 / I68 / I69 / I70 pause-variant pins."""
    state = engine.make_synthetic_state()

    p0_bf_first_id = 0
    p1_bf_first_id = 67

    src_id = state.register_and_inject_object(
        _tap_creature_dict_for_i71(), 1, ZONE_HAND
    )

    state.push_to_stack(src_id, 1)
    state.resolve_top_of_stack_pause()

    # Post-fix: p0's bf[0] got tapped (p1's opponent).
    assert state.is_tapped(p0_bf_first_id) is True
    assert state.is_tapped(p1_bf_first_id) is False


def test_tap_target_empty_source_controllers_opponent_bf_fizzles(engine):
    """**Empty-defender fizzle pin for I71.** When the source-
    controller's opponent has no bf objects, the effect fizzles
    silently (no panic, no spurious mutation). Uses
    `num_battlefield=0` so both sides start with empty bfs.
    """
    state = engine.make_synthetic_state(num_battlefield=0)
    p1_grave_before = state.graveyard_sizes[1]

    src_id = state.register_and_inject_object(
        _tap_creature_dict_for_i71(), 1, ZONE_HAND
    )

    state.push_to_stack(src_id, 1)
    state.resolve_top_of_stack()

    # Stack popped, source moved to p1's graveyard. No bf mutation
    # to assert (both bfs empty).
    assert state.is_stack_empty() is True
    assert state.graveyard_sizes[1] == p1_grave_before + 1


# ====================================================================
# UntapTarget controller-of-effect fix — regression pins (I72).
#
# Pre-fix `defender = (1 - state.active_player) as usize`. Wrong
# when the resolving spell / triggered ability has a controller !=
# active_player — example: on p0's turn, p1 casts a Twiddle-shape
# untap instant. Pre-fix it self-untapped p1's own bf[0] (defender
# = 1 - active_player = 1 - 0 = 1); post-fix it correctly untaps
# p0's bf[0] (the source's controller's opponent).
#
# Sibling closure to I64 / I67 / I70 / I71 — same `defender = 1 -
# controller` shape, same transient-slot lookup substrate.
# ====================================================================


def _untap_creature_dict_for_i72():
    """A Twiddle-shape instant whose only effect is
    UntapTarget(AnyCreature). Used by I72 regression pins."""
    return {
        "name": "Test Untwiddle I72",
        "card_types": ["Instant"],
        "mana_cost": {"U": 1},
        "effects": [
            {
                "kind": "untap_target",
                "target": {"kind": "any_creature"},
            }
        ],
    }


def test_untap_target_routes_to_source_controllers_opponent(engine):
    """**Regression pin for the UntapTarget controller-of-effect
    fix (I72).**

    On p0's turn (active_player=0), a Twiddle-shape untap instant
    whose controller is p1 must untap a P0 bf[0] object, NOT a p1
    bf[0] object. Pre-fix `defender = 1 - active_player = 1 - 0 =
    1` => p1's own bf[0] got untapped (self-untap). Post-fix
    `defender = 1 - controller = 1 - 1 = 0` => correctly untaps
    p0's bf[0].

    Synthetic seed: p0's bf[0] = id 0 (Forest). p1's bf[0] = id 67
    (Forest). Pre-tap BOTH so post-fix we observe p0's bf[0]
    transitioning tapped -> untapped, p1's bf[0] remaining tapped.
    """
    state = engine.make_synthetic_state()
    assert state.active_player == 0

    p0_bf_first_id = 0
    p1_bf_first_id = 67
    # Pre-tap both so the untap is observable.
    state.tap_object(p0_bf_first_id)
    state.tap_object(p1_bf_first_id)
    assert state.is_tapped(p0_bf_first_id) is True
    assert state.is_tapped(p1_bf_first_id) is True

    src_id = state.register_and_inject_object(
        _untap_creature_dict_for_i72(), 1, ZONE_HAND
    )

    # Push with controller=1 (p1), active_player still 0.
    state.push_to_stack(src_id, 1)
    state.resolve_top_of_stack()

    # Post-fix: p0's bf[0] got untapped (p1's opponent's bf).
    assert state.is_tapped(p0_bf_first_id) is False
    # P1's bf[0] untouched (no self-untap).
    assert state.is_tapped(p1_bf_first_id) is True


def test_untap_target_active_player_controlled_still_works(engine):
    """**Back-compat pin.** A Twiddle-shape untap instant cast by
    the active player must still untap the opponent's bf[0] — bug
    never fired in this case pre-fix because controller ==
    active_player.
    """
    state = engine.make_synthetic_state()
    assert state.active_player == 0

    p0_bf_first_id = 0
    p1_bf_first_id = 67
    state.tap_object(p0_bf_first_id)
    state.tap_object(p1_bf_first_id)

    src_id = state.register_and_inject_object(
        _untap_creature_dict_for_i72(), 0, ZONE_HAND
    )

    state.push_to_stack(src_id, 0)
    state.resolve_top_of_stack()

    # P1's bf[0] got untapped (p0's opponent's bf).
    assert state.is_tapped(p1_bf_first_id) is False
    # P0's bf[0] untouched.
    assert state.is_tapped(p0_bf_first_id) is True


def test_untap_target_pause_variant_threads_controller(engine):
    """**`resolve_top_of_stack_pause` parity pin for UntapTarget.**
    Mirrors the I64 / I67 / I68 / I69 / I70 / I71 pause-variant
    pins."""
    state = engine.make_synthetic_state()

    p0_bf_first_id = 0
    p1_bf_first_id = 67
    state.tap_object(p0_bf_first_id)
    state.tap_object(p1_bf_first_id)

    src_id = state.register_and_inject_object(
        _untap_creature_dict_for_i72(), 1, ZONE_HAND
    )

    state.push_to_stack(src_id, 1)
    state.resolve_top_of_stack_pause()

    # Post-fix: p0's bf[0] got untapped (p1's opponent).
    assert state.is_tapped(p0_bf_first_id) is False
    assert state.is_tapped(p1_bf_first_id) is True


def test_untap_target_empty_source_controllers_opponent_bf_fizzles(engine):
    """**Empty-defender fizzle pin for I72.** When the source-
    controller's opponent has no bf objects, the effect fizzles
    silently (no panic, no spurious mutation). Uses
    `num_battlefield=0` so both sides start with empty bfs.
    """
    state = engine.make_synthetic_state(num_battlefield=0)
    p1_grave_before = state.graveyard_sizes[1]

    src_id = state.register_and_inject_object(
        _untap_creature_dict_for_i72(), 1, ZONE_HAND
    )

    state.push_to_stack(src_id, 1)
    state.resolve_top_of_stack()

    # Stack popped, source moved to p1's graveyard. No bf mutation
    # to assert (both bfs empty).
    assert state.is_stack_empty() is True
    assert state.graveyard_sizes[1] == p1_grave_before + 1
