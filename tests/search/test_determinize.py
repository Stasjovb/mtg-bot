"""Tests for ``mtg_bot.search.determinize``.

Covers:

- ``viewer_knows`` for each of the four "known" cases (public zone,
  own hand, explicit reveal) and for the unknown defaults.
- ``determinize`` invariants: per-zone counts preserved, public zones
  untouched, known cards keep their printing, unknown printings get
  re-permuted within the per-player hand+library pool, the multiset
  of unknown printings is preserved, players don't bleed printings
  across each other.
- Edge cases: empty zones, single-hidden-card no-op, all-known no-op,
  rng=None, clone independence.
- A statistical sanity check that with enough samples the unknown
  positions actually receive every possible printing.
"""

from __future__ import annotations

import random

from mtg_bot.cards import BASIC_LANDS, SYNTHETIC_CREATURES
from mtg_bot.game import GameState, Player, Zone, reveal_to
from mtg_bot.search.determinize import determinize, viewer_knows


def _new_state(num_players: int = 2) -> GameState:
    state = GameState()
    for i in range(num_players):
        state.players.append(Player(id=i))
    return state


# ---------- viewer_knows ----------------------------------------------------


def test_viewer_knows_public_zones_always_true():
    state = _new_state()
    for zone in (Zone.BATTLEFIELD, Zone.GRAVEYARD, Zone.EXILE, Zone.STACK):
        # Owned by P1, viewed by P0 — still True because the zone is public.
        obj = state.new_object(BASIC_LANDS["Plains"], 1, zone)
        assert viewer_knows(obj, viewer_id=0)


def test_viewer_knows_own_hand_true_even_without_reveal_flag():
    state = _new_state()
    obj = state.new_object(BASIC_LANDS["Plains"], 0, Zone.HAND)
    # Default publicly_known_to is empty; own-hand rule fills the gap
    # because the reveal-tracking layer doesn't mark drawn cards.
    assert obj.publicly_known_to == frozenset()
    assert viewer_knows(obj, viewer_id=0)


def test_viewer_knows_opponent_hand_default_false():
    state = _new_state()
    obj = state.new_object(BASIC_LANDS["Plains"], 1, Zone.HAND)
    assert not viewer_knows(obj, viewer_id=0)


def test_viewer_knows_publicly_known_to_overrides_zone_rules():
    state = _new_state()
    # Library card — would be unknown by zone — but explicit reveal flips it.
    obj = state.new_object(BASIC_LANDS["Plains"], 1, Zone.LIBRARY)
    assert not viewer_knows(obj, viewer_id=0)
    reveal_to(obj, 0)
    assert viewer_knows(obj, viewer_id=0)


def test_viewer_knows_own_library_default_false():
    # The viewer's own library order is hidden from the viewer, so
    # library cards default to unknown even when owned by viewer.
    state = _new_state()
    obj = state.new_object(BASIC_LANDS["Plains"], 0, Zone.LIBRARY)
    assert not viewer_knows(obj, viewer_id=0)


# ---------- determinize: per-zone count + identity preservation -------------


def test_determinize_preserves_per_zone_counts():
    state = _new_state()
    p0, p1 = state.players
    p0.library = [
        state.new_object(BASIC_LANDS["Plains"], 0, Zone.LIBRARY)
        for _ in range(7)
    ]
    p0.hand = [
        state.new_object(BASIC_LANDS["Island"], 0, Zone.HAND)
        for _ in range(3)
    ]
    p1.library = [
        state.new_object(BASIC_LANDS["Swamp"], 1, Zone.LIBRARY)
        for _ in range(5)
    ]
    p1.hand = [
        state.new_object(BASIC_LANDS["Mountain"], 1, Zone.HAND)
        for _ in range(2)
    ]
    out = determinize(state, viewer_id=0, rng=random.Random(42))
    assert len(out.players[0].library) == 7
    assert len(out.players[0].hand) == 3
    assert len(out.players[1].library) == 5
    assert len(out.players[1].hand) == 2


def test_determinize_returns_fresh_state_not_mutating_input():
    state = _new_state()
    p1 = state.players[1]
    a = state.new_object(BASIC_LANDS["Plains"], 1, Zone.HAND)
    b = state.new_object(BASIC_LANDS["Island"], 1, Zone.HAND)
    p1.hand.extend([a, b])
    pre_input_printings = [c.printing.name for c in state.players[1].hand]
    out = determinize(state, viewer_id=0, rng=random.Random(0))
    assert out is not state
    # Input untouched.
    post_input_printings = [c.printing.name for c in state.players[1].hand]
    assert pre_input_printings == post_input_printings
    # Output cards are different objects than input cards.
    assert out.players[1].hand[0] is not state.players[1].hand[0]


# ---------- determinize: public zones / known cards untouched ---------------


def test_determinize_does_not_touch_battlefield_graveyard_exile_stack():
    state = _new_state()
    p1 = state.players[1]
    bf = state.new_object(SYNTHETIC_CREATURES["Battlefield Recruit"], 1, Zone.BATTLEFIELD)
    state.battlefield.append(bf)
    gy_card = state.new_object(BASIC_LANDS["Plains"], 1, Zone.GRAVEYARD)
    p1.graveyard.append(gy_card)
    ex_card = state.new_object(BASIC_LANDS["Island"], 1, Zone.EXILE)
    p1.exile.append(ex_card)
    out = determinize(state, viewer_id=0, rng=random.Random(7))
    # Same printings, same counts.
    assert out.battlefield[0].printing.name == "Battlefield Recruit"
    assert out.players[1].graveyard[0].printing.name == "Plains"
    assert out.players[1].exile[0].printing.name == "Island"


def test_determinize_keeps_viewer_own_hand_in_place():
    state = _new_state()
    p0 = state.players[0]
    plains = state.new_object(BASIC_LANDS["Plains"], 0, Zone.HAND)
    island = state.new_object(BASIC_LANDS["Island"], 0, Zone.HAND)
    p0.hand.extend([plains, island])
    out = determinize(state, viewer_id=0, rng=random.Random(1))
    # Viewer always knows their own hand — order and identities preserved.
    out_names = [c.printing.name for c in out.players[0].hand]
    assert out_names == ["Plains", "Island"]


def test_determinize_keeps_explicitly_revealed_cards_in_place():
    state = _new_state()
    p1 = state.players[1]
    revealed = state.new_object(BASIC_LANDS["Plains"], 1, Zone.HAND)
    reveal_to(revealed, 0)
    hidden_a = state.new_object(BASIC_LANDS["Island"], 1, Zone.HAND)
    hidden_b = state.new_object(BASIC_LANDS["Swamp"], 1, Zone.HAND)
    p1.hand.extend([revealed, hidden_a, hidden_b])
    # Run many seeds — the revealed card never moves.
    for seed in range(20):
        out = determinize(state, viewer_id=0, rng=random.Random(seed))
        # The revealed card is at position 0 of the cloned hand list and
        # still has its known printing.
        assert out.players[1].hand[0].printing.name == "Plains"


# ---------- determinize: unknown printings are permuted ---------------------


def test_determinize_preserves_multiset_of_unknown_printings():
    state = _new_state()
    p1 = state.players[1]
    expected = ["Plains", "Island", "Swamp", "Mountain", "Forest"]
    for name in expected:
        c = state.new_object(BASIC_LANDS[name], 1, Zone.HAND)
        p1.hand.append(c)
    out = determinize(state, viewer_id=0, rng=random.Random(123))
    out_names = sorted(c.printing.name for c in out.players[1].hand)
    assert out_names == sorted(expected)


def test_determinize_pools_hand_and_library_for_one_player():
    # A printing originally in opponent's hand can land in their library
    # after determinization (and vice versa) — pooling across hidden
    # zones is sound under our model.
    state = _new_state()
    p1 = state.players[1]
    # 2 hand + 2 library, all distinct printings, all unknown to P0.
    h1 = state.new_object(BASIC_LANDS["Plains"], 1, Zone.HAND)
    h2 = state.new_object(BASIC_LANDS["Island"], 1, Zone.HAND)
    l1 = state.new_object(BASIC_LANDS["Swamp"], 1, Zone.LIBRARY)
    l2 = state.new_object(BASIC_LANDS["Mountain"], 1, Zone.LIBRARY)
    p1.hand.extend([h1, h2])
    p1.library.extend([l1, l2])
    # Across many seeds, at least one run should put a printing that
    # originated in hand into the library and vice versa.
    saw_hand_to_library_swap = False
    for seed in range(50):
        out = determinize(state, viewer_id=0, rng=random.Random(seed))
        out_hand_names = {c.printing.name for c in out.players[1].hand}
        if "Swamp" in out_hand_names or "Mountain" in out_hand_names:
            saw_hand_to_library_swap = True
            break
    assert saw_hand_to_library_swap, (
        "expected hand+library pooling to allow cross-zone permutation "
        "within a single player"
    )


def test_determinize_does_not_bleed_printings_across_players():
    # Each player has a unique printing in hand. After determinization,
    # P0 never ends up with P1's printing or vice versa.
    state = _new_state()
    p0, p1 = state.players
    p0.hand.append(state.new_object(BASIC_LANDS["Plains"], 0, Zone.HAND))
    p1.hand.append(state.new_object(BASIC_LANDS["Mountain"], 1, Zone.HAND))
    for seed in range(20):
        out = determinize(state, viewer_id=0, rng=random.Random(seed))
        p0_names = {c.printing.name for c in out.players[0].hand}
        p1_names = {c.printing.name for c in out.players[1].hand}
        assert "Mountain" not in p0_names
        assert "Plains" not in p1_names


# ---------- determinize: edge cases -----------------------------------------


def test_determinize_handles_empty_zones():
    state = _new_state()
    out = determinize(state, viewer_id=0, rng=random.Random(0))
    # No exception, no changes.
    assert len(out.players[0].hand) == 0
    assert len(out.players[1].library) == 0


def test_determinize_single_hidden_card_is_a_noop():
    state = _new_state()
    p1 = state.players[1]
    p1.hand.append(state.new_object(BASIC_LANDS["Plains"], 1, Zone.HAND))
    out = determinize(state, viewer_id=0, rng=random.Random(0))
    # One card has nothing to swap with.
    assert out.players[1].hand[0].printing.name == "Plains"


def test_determinize_with_all_cards_known_is_a_noop():
    state = _new_state()
    p1 = state.players[1]
    cards = []
    for name in ("Plains", "Island", "Swamp"):
        c = state.new_object(BASIC_LANDS[name], 1, Zone.HAND)
        reveal_to(c, 0)
        p1.hand.append(c)
        cards.append(c)
    out = determinize(state, viewer_id=0, rng=random.Random(0))
    # Everything remains in original order with original printings.
    out_names = [c.printing.name for c in out.players[1].hand]
    assert out_names == ["Plains", "Island", "Swamp"]


def test_determinize_default_rng_works():
    state = _new_state()
    p1 = state.players[1]
    p1.hand.extend(
        state.new_object(BASIC_LANDS[n], 1, Zone.HAND)
        for n in ("Plains", "Island", "Swamp")
    )
    # No rng provided — should not raise and should produce a valid sample.
    out = determinize(state, viewer_id=0)
    assert sorted(c.printing.name for c in out.players[1].hand) == [
        "Island", "Plains", "Swamp",
    ]


def test_determinize_reproducible_with_same_seed():
    state = _new_state()
    p1 = state.players[1]
    p1.hand.extend(
        state.new_object(BASIC_LANDS[n], 1, Zone.HAND)
        for n in ("Plains", "Island", "Swamp", "Mountain", "Forest")
    )
    a = determinize(state, viewer_id=0, rng=random.Random(99))
    b = determinize(state, viewer_id=0, rng=random.Random(99))
    a_names = [c.printing.name for c in a.players[1].hand]
    b_names = [c.printing.name for c in b.players[1].hand]
    assert a_names == b_names


def test_determinize_clone_is_independent_of_input():
    state = _new_state()
    p1 = state.players[1]
    c = state.new_object(BASIC_LANDS["Plains"], 1, Zone.HAND)
    p1.hand.append(c)
    out = determinize(state, viewer_id=0, rng=random.Random(0))
    # Mutate the clone's card; the input must not change.
    out.players[1].hand[0].damage = 3
    assert state.players[1].hand[0].damage == 0


# ---------- statistical sanity -----------------------------------------------


def test_determinize_eventually_visits_every_printing_in_every_position():
    """With enough samples, each unknown position should see each
    printing at least once. Loose check — confirms the shuffle is
    actually shuffling rather than producing a fixed permutation.
    """
    state = _new_state()
    p1 = state.players[1]
    names = ("Plains", "Island", "Swamp", "Mountain")
    for n in names:
        p1.hand.append(state.new_object(BASIC_LANDS[n], 1, Zone.HAND))
    seen_at_position = {i: set() for i in range(len(names))}
    for seed in range(200):
        out = determinize(state, viewer_id=0, rng=random.Random(seed))
        for i, c in enumerate(out.players[1].hand):
            seen_at_position[i].add(c.printing.name)
    for i in range(len(names)):
        assert seen_at_position[i] == set(names), (
            f"position {i} missed some printings: {seen_at_position[i]}"
        )


def test_determinize_in_place_does_not_leak_to_source_state():
    """The PIMC bug fix (todo f8c2a4d1): when the caller follows the
    intended pattern of ``state.clone()`` followed by ``determinize(
    cloned, viewer_id, in_place=True)``, the determinization must
    NOT mutate the source state's library cards.

    The leak: ``state.clone()`` sets up a CoW share group on
    library/graveyard/exile so they share GameObject references with
    the source until the first list-mutator forks them. But the
    determinizer rewrites ``card.printing`` directly on the GameObject
    — that's not a list-level mutation, so the share group stays
    intact and the source state's library cards see the new printings
    too. Over many MCTS calls per game, the source state's library
    accumulates whatever the determinizer happened to bind it to,
    producing the phantom-card-in-replay bug seen on iter_002 (P1
    drew 4 Biomechan Engineers from a deck that contained 1).

    Pin: a 5-card library + a clone + a determinize on the clone
    must leave the source's library card-printings untouched.
    """
    state = _new_state()
    p1 = state.players[1]
    starter_names = ("Plains", "Island", "Swamp", "Mountain", "Forest")
    p1.library = [
        state.new_object(BASIC_LANDS[n], 1, Zone.LIBRARY)
        for n in starter_names
    ]
    cloned = state.clone()
    determinize(
        cloned, viewer_id=0, rng=random.Random(0), in_place=True,
    )
    # Source's library card printings remain exactly as set up.
    src_names = [c.printing.name for c in state.players[1].library]
    assert src_names == list(starter_names)


def test_determinize_in_place_isolated_under_repeated_pimc_pattern():
    """Stress version of the leak test: under PIMC, the same source
    state is cloned + determinized many times in a row (one per
    sample × one per MCTS-call × one per priority moment ≈ 1000s/
    game). Each repetition is an independent rebinding; none of them
    should accumulate on the source.
    """
    state = _new_state()
    p1 = state.players[1]
    starter_names = ("Plains", "Island", "Swamp", "Mountain", "Forest")
    p1.library = [
        state.new_object(BASIC_LANDS[n], 1, Zone.LIBRARY)
        for n in starter_names
    ]
    for seed in range(50):
        cloned = state.clone()
        determinize(
            cloned, viewer_id=0, rng=random.Random(seed), in_place=True,
        )
    src_names = [c.printing.name for c in state.players[1].library]
    assert src_names == list(starter_names)


def test_determinize_preserves_original_printing_alongside_printing():
    # original_printing is set by "becomes a copy" effects; for hand
    # cards it's typically None. Still, the determinizer must permute
    # it in lockstep with printing so the two never desynchronize.
    state = _new_state()
    p1 = state.players[1]
    a = state.new_object(BASIC_LANDS["Plains"], 1, Zone.HAND)
    b = state.new_object(BASIC_LANDS["Island"], 1, Zone.HAND)
    # Force divergent original_printing values to detect any swap-then-
    # don't-swap-the-other bug.
    a.original_printing = BASIC_LANDS["Plains"]
    b.original_printing = BASIC_LANDS["Island"]
    p1.hand.extend([a, b])
    for seed in range(20):
        out = determinize(state, viewer_id=0, rng=random.Random(seed))
        for c in out.players[1].hand:
            assert c.printing is c.original_printing
