"""Tests for the publicly_known_to reveal-tracking field.

These exercise the engine sites instrumented in PR 1 of the
hidden-information / determinization work. See
``docs/HIDDEN_INFO_MODEL.md`` for the design.

Coverage by site:

- ``GameObject.publicly_known_to`` default + helper functions
  (reveal_to / reveal_to_all / reset_public_knowledge /
  reset_library_public_knowledge / shuffle_library)
- ``GameState.clone()`` preserves the field
- Library shuffles reset the field on every card in the library
- Bounce-from-battlefield-to-hand marks the bounced card publicly known
- Graveyard-to-hand recursion marks the returned card publicly known
- Tutor-with-reveal marks the fetched card publicly known
- Temporal Intervention marks the surviving hand contents publicly known
  to the caster only (not to the third player)
"""

from __future__ import annotations

from mtg_bot.agents import Agent
from mtg_bot.cards import (
    BASIC_LANDS,
    EOE_CREATURES,
    SYNTHETIC_CREATURES,
)
from mtg_bot.effects import (
    LookAtTopNRevealOrCounter,
    ReturnTargetCreatureToOwnersHand,
    ReturnTargetPermanentYouControlToOwnersHand,
    ReturnUpToNTargetCreaturesToOwnersHands,
    ReturnTargetArtifactCardFromYourGraveyardToHand,
    ReturnCreatureFromYourGraveyardToHand,
    SearchLibraryForCard,
    TargetOpponentDiscardsCasterChoice,
)
from mtg_bot.game import (
    GameState,
    Player,
    Zone,
    reset_library_public_knowledge,
    reset_public_knowledge,
    reveal_to,
    reveal_to_all,
    shuffle_library,
)

_SYN_CREATURE = "Battlefield Recruit"  # any vanilla synthetic creature


class _TakeFirstAgent(Agent):
    def choose_card_from_library(self, state, player_id, option_ids):
        return option_ids[0] if option_ids else None

    def choose_card_from_opponent_hand(self, state, player_id, option_ids):
        return option_ids[0] if option_ids else None

    def choose_target(self, state, player_id, legal_targets):
        return legal_targets[0] if legal_targets else None


def _new_state(num_players: int = 2) -> GameState:
    state = GameState()
    for i in range(num_players):
        state.players.append(
            Player(id=i, agent=_TakeFirstAgent())
        )
    return state


# --- field default + helpers -----------------------------------------------


def test_publicly_known_to_defaults_to_empty_frozenset():
    state = _new_state()
    obj = state.new_object(BASIC_LANDS["Plains"], 0, Zone.LIBRARY)
    assert obj.publicly_known_to == frozenset()
    assert isinstance(obj.publicly_known_to, frozenset)


def test_reveal_to_unions_player_ids():
    state = _new_state()
    obj = state.new_object(BASIC_LANDS["Plains"], 0, Zone.LIBRARY)
    reveal_to(obj, 1)
    assert obj.publicly_known_to == frozenset({1})
    # Idempotent and unions correctly with later marks.
    reveal_to(obj, 1, 0)
    assert obj.publicly_known_to == frozenset({0, 1})


def test_reveal_to_with_no_args_is_a_noop():
    state = _new_state()
    obj = state.new_object(BASIC_LANDS["Plains"], 0, Zone.LIBRARY)
    reveal_to(obj, 0)
    reveal_to(obj)
    assert obj.publicly_known_to == frozenset({0})


def test_reveal_to_all_marks_every_player():
    state = _new_state(num_players=3)
    obj = state.new_object(BASIC_LANDS["Plains"], 0, Zone.LIBRARY)
    reveal_to_all(state, obj)
    assert obj.publicly_known_to == frozenset({0, 1, 2})


def test_reset_public_knowledge_clears():
    state = _new_state()
    obj = state.new_object(BASIC_LANDS["Plains"], 0, Zone.LIBRARY)
    reveal_to_all(state, obj)
    reset_public_knowledge(obj)
    assert obj.publicly_known_to == frozenset()


def test_reset_library_public_knowledge_clears_every_library_card():
    state = _new_state()
    p = state.players[0]
    for _ in range(3):
        c = state.new_object(BASIC_LANDS["Plains"], 0, Zone.LIBRARY)
        reveal_to_all(state, c)
        p.library.append(c)
    reset_library_public_knowledge(state, 0)
    assert all(c.publicly_known_to == frozenset() for c in p.library)


def test_shuffle_library_clears_knowledge_alongside_shuffle():
    state = _new_state()
    p = state.players[0]
    for _ in range(5):
        c = state.new_object(BASIC_LANDS["Plains"], 0, Zone.LIBRARY)
        reveal_to_all(state, c)
        p.library.append(c)
    shuffle_library(state, 0)
    assert len(p.library) == 5
    assert all(c.publicly_known_to == frozenset() for c in p.library)


# --- clone preserves the field ---------------------------------------------


def test_clone_preserves_publicly_known_to():
    state = _new_state()
    p = state.players[0]
    a = state.new_object(BASIC_LANDS["Plains"], 0, Zone.HAND)
    b = state.new_object(BASIC_LANDS["Plains"], 0, Zone.HAND)
    reveal_to(a, 1)
    reveal_to_all(state, b)
    p.hand.extend([a, b])
    clone = state.clone()
    cloned_a, cloned_b = clone.players[0].hand
    assert cloned_a.publicly_known_to == frozenset({1})
    assert cloned_b.publicly_known_to == frozenset({0, 1})
    # Independence: mutating original doesn't change the clone.
    reset_public_knowledge(a)
    assert cloned_a.publicly_known_to == frozenset({1})


# --- bounce-from-battlefield-to-hand ---------------------------------------


def test_bounce_creature_marks_publicly_known():
    state = _new_state()
    p0 = state.players[0]
    creature = state.new_object(
        SYNTHETIC_CREATURES[_SYN_CREATURE], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(creature)
    ReturnTargetCreatureToOwnersHand().resolve(
        state, 0, (("creature", creature.id),),
    )
    assert creature.zone == Zone.HAND
    assert creature in p0.hand
    assert creature.publicly_known_to == frozenset({0, 1})


def test_bounce_target_permanent_you_control_marks_publicly_known():
    state = _new_state()
    p0 = state.players[0]
    creature = state.new_object(
        SYNTHETIC_CREATURES[_SYN_CREATURE], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(creature)
    ReturnTargetPermanentYouControlToOwnersHand().resolve(
        state, 0, (("permanent", creature.id),),
    )
    assert creature in p0.hand
    assert creature.publicly_known_to == frozenset({0, 1})


def test_bounce_multi_marks_each_returned_card_publicly_known():
    state = _new_state()
    p0 = state.players[0]
    creatures = []
    for _ in range(3):
        c = state.new_object(
            SYNTHETIC_CREATURES[_SYN_CREATURE], 0, Zone.BATTLEFIELD,
        )
        state.battlefield.append(c)
        creatures.append(c)
    ReturnUpToNTargetCreaturesToOwnersHands(max_n=3).resolve(
        state, 0, tuple(("creature", c.id) for c in creatures),
    )
    for c in creatures:
        assert c in p0.hand
        assert c.publicly_known_to == frozenset({0, 1})


# --- graveyard-to-hand -----------------------------------------------------


def test_return_artifact_from_graveyard_marks_publicly_known():
    state = _new_state()
    p0 = state.players[0]
    # Use any artifact card from EOE_CREATURES — Synthesizer Labship is a
    # Spacecraft (artifact). Land it in the graveyard directly.
    art = state.new_object(
        EOE_CREATURES["Synthesizer Labship"], 0, Zone.GRAVEYARD,
    )
    p0.graveyard.append(art)
    ReturnTargetArtifactCardFromYourGraveyardToHand().resolve(
        state, 0, (("graveyard_artifact", art.id),),
    )
    assert art in p0.hand
    assert art.publicly_known_to == frozenset({0, 1})


def test_return_creature_from_graveyard_marks_publicly_known():
    state = _new_state()
    p0 = state.players[0]
    cr = state.new_object(
        SYNTHETIC_CREATURES[_SYN_CREATURE], 0, Zone.GRAVEYARD,
    )
    p0.graveyard.append(cr)
    ReturnCreatureFromYourGraveyardToHand().resolve(
        state, 0, (("graveyard_creature", cr.id),),
    )
    assert cr in p0.hand
    assert cr.publicly_known_to == frozenset({0, 1})


# --- tutor-with-reveal -----------------------------------------------------


def test_search_library_for_card_marks_fetched_card_publicly_known():
    state = _new_state()
    p0 = state.players[0]
    target = state.new_object(
        BASIC_LANDS["Plains"], 0, Zone.LIBRARY,
    )
    # Salt the library with a couple non-matching cards so the shuffle
    # actually exercises reset on remaining cards.
    other_a = state.new_object(BASIC_LANDS["Forest"], 0, Zone.LIBRARY)
    other_b = state.new_object(BASIC_LANDS["Mountain"], 0, Zone.LIBRARY)
    # Pre-mark the others as publicly_known_to to verify the shuffle
    # resets them.
    reveal_to_all(state, other_a)
    reveal_to_all(state, other_b)
    p0.library.extend([target, other_a, other_b])
    SearchLibraryForCard(
        filter_name="basic_plains", may_fail=False,
    ).resolve(state, 0, ())
    assert target in p0.hand
    assert target.publicly_known_to == frozenset({0, 1})
    # Library shuffle reset the others.
    for c in p0.library:
        assert c.publicly_known_to == frozenset()


def test_search_library_decline_still_resets_on_shuffle():
    """SearchLibraryForCard with may_fail=True and the agent declining
    still triggers the mandatory shuffle and resets library state."""
    class _DeclineAgent(Agent):
        def choose_card_from_library(self, state, player_id, option_ids):
            return None

    state = _new_state()
    state.players[0].agent = _DeclineAgent()
    p0 = state.players[0]
    salted = state.new_object(BASIC_LANDS["Plains"], 0, Zone.LIBRARY)
    reveal_to_all(state, salted)
    p0.library.append(salted)
    # Add a fetchable card so the search has options (otherwise it
    # short-circuits without shuffling).
    target = state.new_object(BASIC_LANDS["Plains"], 0, Zone.LIBRARY)
    p0.library.append(target)
    SearchLibraryForCard(
        filter_name="basic_plains", may_fail=True,
    ).resolve(state, 0, ())
    # Decline triggers the mandatory shuffle, which clears reveal state.
    assert salted.publicly_known_to == frozenset()


def test_search_library_no_options_still_shuffles():
    """No matching card in library: oracle "then shuffle" still fires."""
    state = _new_state()
    p0 = state.players[0]
    salted = state.new_object(BASIC_LANDS["Plains"], 0, Zone.LIBRARY)
    reveal_to_all(state, salted)
    p0.library.append(salted)
    SearchLibraryForCard(
        filter_name="basic_island", may_fail=True,
    ).resolve(state, 0, ())
    assert salted.publicly_known_to == frozenset()


def test_look_at_top_n_reveal_marks_only_revealed_card_publicly_known():
    state = _new_state()
    p0 = state.players[0]
    ship = state.new_object(
        EOE_CREATURES["Synthesizer Labship"], 0, Zone.LIBRARY,
    )
    p0.library.append(ship)
    for _ in range(4):
        p0.library.append(
            state.new_object(BASIC_LANDS["Plains"], 0, Zone.LIBRARY)
        )
    ace = state.new_object(
        EOE_CREATURES["Pulsar Squadron Ace"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(ace)
    state.resolving_source = ace
    LookAtTopNRevealOrCounter(n=5, filter_name="spacecraft").resolve(
        state, 0, (),
    )
    state.resolving_source = None
    assert ship in p0.hand
    assert ship.publicly_known_to == frozenset({0, 1})
    # The bottomed cards' positional knowledge is reset.
    for c in p0.library:
        assert c.publicly_known_to == frozenset()


# --- look at opponent's hand (Temporal Intervention) -----------------------


def test_temporal_intervention_marks_remaining_hand_known_to_caster():
    state = _new_state(num_players=3)
    # Caster is P0, target is P1, third player P2 must NOT know the
    # remaining hand.
    target = state.players[1]
    revealed_cards = []
    for _ in range(3):
        c = state.new_object(
            SYNTHETIC_CREATURES[_SYN_CREATURE], 1, Zone.HAND,
        )
        target.hand.append(c)
        revealed_cards.append(c)
    # Need at least one nonland for the directed-discard step to do
    # something — Bear 2/2 is a creature, so all are valid options.
    TargetOpponentDiscardsCasterChoice().resolve(
        state, 0, (("player", 1),),
    )
    # One card was discarded; the rest stay in target's hand and are
    # marked known-to-P0 (the caster) but NOT known-to-P2.
    discarded = [c for c in revealed_cards if c not in target.hand]
    assert len(discarded) == 1
    remaining = [c for c in revealed_cards if c in target.hand]
    assert len(remaining) == 2
    for c in remaining:
        assert 0 in c.publicly_known_to
        assert 2 not in c.publicly_known_to
    # The discarded card was also marked-to-P0 before being moved.
    assert 0 in discarded[0].publicly_known_to


def test_temporal_intervention_fizzles_with_only_lands_but_still_marks():
    state = _new_state()
    target = state.players[1]
    only_lands = []
    for _ in range(2):
        c = state.new_object(
            BASIC_LANDS["Plains"], 1, Zone.HAND,
        )
        target.hand.append(c)
        only_lands.append(c)
    TargetOpponentDiscardsCasterChoice().resolve(
        state, 0, (("player", 1),),
    )
    # Hand still intact — no nonland to discard.
    for c in only_lands:
        assert c in target.hand
        # The caster STILL saw the hand during the reveal step.
        assert 0 in c.publicly_known_to


def test_temporal_intervention_no_targets_is_safe_noop():
    state = _new_state()
    target = state.players[1]
    c = state.new_object(SYNTHETIC_CREATURES[_SYN_CREATURE], 1, Zone.HAND)
    target.hand.append(c)
    TargetOpponentDiscardsCasterChoice().resolve(state, 0, ())
    # Nothing happened — no reveal mark.
    assert c.publicly_known_to == frozenset()


def test_temporal_intervention_against_lost_player_is_noop():
    state = _new_state()
    target = state.players[1]
    target.has_lost = True
    c = state.new_object(SYNTHETIC_CREATURES[_SYN_CREATURE], 1, Zone.HAND)
    target.hand.append(c)
    TargetOpponentDiscardsCasterChoice().resolve(
        state, 0, (("player", 1),),
    )
    assert c.publicly_known_to == frozenset()
