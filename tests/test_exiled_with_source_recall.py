"""Behavioral tests for the generic "exiled with this permanent" recall
infrastructure.

The infrastructure has four new generic effect primitives in
``mtg_bot.effects.generic``:

* ``MoveEachExiledWithSourceToOwnersGraveyard`` — walks every player's
  exile zone for cards tagged ``exiled_by_source == source.id`` and
  moves each to its owner's graveyard. Records the count moved on
  ``state.last_exile_recall_count`` so a follow-up sequence step can
  read it.
* ``CreateNTokensFromLastExileRecall(token_name=...)`` — reads
  ``state.last_exile_recall_count`` and creates that many tokens
  using the named ``TOKEN_PRINTINGS`` entry under the activator's
  control.
* ``SacrificeSelf`` (effect-body sacrifice; distinct from
  ``ActivationCost.sacrifice_self``).
* ``PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYourControl
  (grant_flying_counter=..., grant_subtype_and_pt=(subtype, P, T))``
  — walks every exile zone for ``exiled_by_source == source.id``
  CREATURE cards and brings each onto the activator's battlefield.
  Optional rider parameters add a flying counter and grant a
  subtype + base PT continuous effect to each recalled card.

The Pinnacle Starcage and Ghost Vacuum integration tests live in
``test_pinnacle_starcage.py`` and ``test_parser_dsk_artifacts_batch2.py``.
"""

from __future__ import annotations

from mtg_bot.cards.base import make_artifact, make_creature
from mtg_bot.effects import (
    CreateNTokensFromLastExileRecall,
    MoveEachExiledWithSourceToOwnersGraveyard,
    PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYourControl,
    SacrificeSelf,
    Sequence,
)
from mtg_bot.game import (
    GameObject, GameState, Player, Zone, effective_keywords,
    effective_subtypes,
)


def _new_state() -> GameState:
    return GameState(players=[Player(id=0), Player(id=1)])


def _put_in_exile(
    state: GameState, owner_id: int, printing, source_id: int,
    obj_id: int,
) -> GameObject:
    """Stash a card in player ``owner_id``'s exile zone, tagged with
    ``exiled_by_source``."""
    obj = GameObject(
        id=obj_id, printing=printing,
        owner_id=owner_id, controller_id=owner_id,
        zone=Zone.EXILE, exiled_by_source=source_id,
    )
    state.players[owner_id].exile.append(obj)
    return obj


# ----------------------------------------------------------------------
# MoveEachExiledWithSourceToOwnersGraveyard
# ----------------------------------------------------------------------


def test_move_recall_moves_only_tagged_cards_to_owners_graveyards():
    """Cards tagged ``exiled_by_source == source.id`` move to their
    OWN owner's graveyard (not the activator's). Cards tagged with a
    different source id stay in exile."""
    state = _new_state()
    source_pr = make_artifact("Source", "{2}")
    source_obj = GameObject(
        id=99, printing=source_pr, owner_id=0, controller_id=0,
        zone=Zone.BATTLEFIELD,
    )
    state.battlefield.append(source_obj)
    state.resolving_source = source_obj
    bear_pr = make_creature("Bear", "{1}{G}", power=2, toughness=2)
    other_pr = make_creature("Other", "{1}", power=1, toughness=1)
    # Tagged cards: belong to opponent and to the source's controller.
    p0_card = _put_in_exile(state, 0, bear_pr, source_obj.id, obj_id=1)
    p1_card = _put_in_exile(state, 1, bear_pr, source_obj.id, obj_id=2)
    # Untagged card (different source linkage).
    untagged = _put_in_exile(state, 1, other_pr, source_id=999, obj_id=3)
    MoveEachExiledWithSourceToOwnersGraveyard().resolve(
        state, controller_id=0, targets=(),
    )
    # Tagged cards moved to OWN owner's graveyard.
    assert p0_card in state.players[0].graveyard
    assert p0_card not in state.players[0].exile
    assert p0_card.zone == Zone.GRAVEYARD
    assert p0_card.exiled_by_source is None
    assert p1_card in state.players[1].graveyard
    assert p1_card not in state.players[1].exile
    # Untagged card stayed in exile.
    assert untagged in state.players[1].exile
    # Count exposed for follow-up sequence step.
    assert state.last_exile_recall_count == 2


def test_move_recall_no_tagged_cards_records_zero_count():
    state = _new_state()
    source_pr = make_artifact("Source", "{2}")
    source_obj = GameObject(
        id=99, printing=source_pr, owner_id=0, controller_id=0,
        zone=Zone.BATTLEFIELD,
    )
    state.battlefield.append(source_obj)
    state.resolving_source = source_obj
    # Pre-set a stale value to prove resolve overwrites it.
    state.last_exile_recall_count = 7
    MoveEachExiledWithSourceToOwnersGraveyard().resolve(
        state, controller_id=0, targets=(),
    )
    assert state.last_exile_recall_count == 0


def test_move_recall_no_source_is_noop():
    state = _new_state()
    # No resolving_source set.
    MoveEachExiledWithSourceToOwnersGraveyard().resolve(
        state, controller_id=0, targets=(),
    )
    assert state.last_exile_recall_count == 0


def test_move_recall_describe():
    desc = MoveEachExiledWithSourceToOwnersGraveyard().describe()
    assert "exiled with this permanent" in desc
    assert "graveyard" in desc


# ----------------------------------------------------------------------
# CreateNTokensFromLastExileRecall
# ----------------------------------------------------------------------


def test_create_n_tokens_reads_last_recall_count():
    state = _new_state()
    state.last_exile_recall_count = 3
    CreateNTokensFromLastExileRecall(token_name="Robot").resolve(
        state, controller_id=0, targets=(),
    )
    robots = [o for o in state.battlefield if o.printing.name == "Robot"]
    assert len(robots) == 3
    assert all(o.controller_id == 0 for o in robots)


def test_create_n_tokens_zero_count_makes_no_tokens():
    state = _new_state()
    state.last_exile_recall_count = 0
    CreateNTokensFromLastExileRecall(token_name="Robot").resolve(
        state, controller_id=0, targets=(),
    )
    assert state.battlefield == []


def test_create_n_tokens_describe():
    desc = CreateNTokensFromLastExileRecall(token_name="Robot").describe()
    assert "Robot" in desc


# ----------------------------------------------------------------------
# Sequence integration: recall -> create-N -> sacrifice-self
# (the Pinnacle Starcage shape)
# ----------------------------------------------------------------------


def test_sequence_recall_then_create_n_threads_count_correctly():
    """End-to-end: a Sequence of MoveEach* + CreateNTokensFrom* mints
    exactly one token per card moved out of exile."""
    state = _new_state()
    source_pr = make_artifact("Source", "{2}")
    source_obj = GameObject(
        id=99, printing=source_pr, owner_id=0, controller_id=0,
        zone=Zone.BATTLEFIELD,
    )
    state.battlefield.append(source_obj)
    state.resolving_source = source_obj
    bear_pr = make_creature("Bear", "{1}{G}", power=2, toughness=2)
    _put_in_exile(state, 0, bear_pr, source_obj.id, obj_id=1)
    _put_in_exile(state, 1, bear_pr, source_obj.id, obj_id=2)
    _put_in_exile(state, 1, bear_pr, source_obj.id, obj_id=3)
    seq = Sequence(effects=(
        MoveEachExiledWithSourceToOwnersGraveyard(),
        CreateNTokensFromLastExileRecall(token_name="Robot"),
    ))
    seq.resolve(state, controller_id=0, targets=())
    # Three Robots created (one per card moved).
    robots = [o for o in state.battlefield if o.printing.name == "Robot"]
    assert len(robots) == 3


# ----------------------------------------------------------------------
# SacrificeSelf
# ----------------------------------------------------------------------


def test_sacrifice_self_sends_source_to_graveyard():
    state = _new_state()
    source_pr = make_artifact("Source", "{2}")
    source_obj = GameObject(
        id=99, printing=source_pr, owner_id=0, controller_id=0,
        zone=Zone.BATTLEFIELD,
    )
    state.battlefield.append(source_obj)
    state.resolving_source = source_obj
    SacrificeSelf().resolve(state, controller_id=0, targets=())
    assert source_obj not in state.battlefield
    assert source_obj in state.players[0].graveyard


def test_sacrifice_self_no_source_is_noop():
    state = _new_state()
    SacrificeSelf().resolve(state, controller_id=0, targets=())
    # No exception, no battlefield change.
    assert state.battlefield == []


def test_sacrifice_self_already_off_battlefield_is_noop():
    """If the source has already left (e.g., an earlier Sequence step
    moved it), SacrificeSelf is a no-op rather than reaching into the
    graveyard or raising."""
    state = _new_state()
    source_pr = make_artifact("Source", "{2}")
    # Source not on battlefield (already gone).
    source_obj = GameObject(
        id=99, printing=source_pr, owner_id=0, controller_id=0,
        zone=Zone.GRAVEYARD,
    )
    state.players[0].graveyard.append(source_obj)
    state.resolving_source = source_obj
    SacrificeSelf().resolve(state, controller_id=0, targets=())
    # Still in graveyard, not double-processed.
    assert source_obj in state.players[0].graveyard


# ----------------------------------------------------------------------
# PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYourControl
# ----------------------------------------------------------------------


def test_put_creature_recall_filters_to_creatures_only():
    state = _new_state()
    source_pr = make_artifact("Source", "{2}")
    source_obj = GameObject(
        id=99, printing=source_pr, owner_id=0, controller_id=0,
        zone=Zone.GRAVEYARD,  # cost-time sacrifice is fine
    )
    state.resolving_source = source_obj
    bear_pr = make_creature("Bear", "{1}{G}", power=2, toughness=2)
    other_art_pr = make_artifact("Junk", "{1}")
    creature = _put_in_exile(state, 1, bear_pr, source_obj.id, obj_id=1)
    artifact = _put_in_exile(state, 1, other_art_pr, source_obj.id, obj_id=2)
    PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYourControl().resolve(
        state, controller_id=0, targets=(),
    )
    # Creature recalled under activator's control; artifact stayed.
    assert creature in state.battlefield
    assert creature.controller_id == 0
    assert creature.exiled_by_source is None
    assert artifact in state.players[1].exile


def test_put_creature_recall_bare_no_riders_grants_no_counters_or_subtypes():
    state = _new_state()
    source_pr = make_artifact("Source", "{2}")
    source_obj = GameObject(
        id=99, printing=source_pr, owner_id=0, controller_id=0,
        zone=Zone.GRAVEYARD,
    )
    state.resolving_source = source_obj
    bear_pr = make_creature("Bear", "{1}{G}", power=2, toughness=2)
    creature = _put_in_exile(state, 1, bear_pr, source_obj.id, obj_id=1)
    PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYourControl().resolve(
        state, controller_id=0, targets=(),
    )
    assert creature.flying_counters == 0
    assert "flying" not in effective_keywords(state, creature)
    assert "Spirit" not in effective_subtypes(state, creature)


def test_put_creature_recall_with_flying_counter_rider():
    state = _new_state()
    source_pr = make_artifact("Source", "{2}")
    source_obj = GameObject(
        id=99, printing=source_pr, owner_id=0, controller_id=0,
        zone=Zone.GRAVEYARD,
    )
    state.resolving_source = source_obj
    bear_pr = make_creature("Bear", "{1}{G}", power=2, toughness=2)
    creature = _put_in_exile(state, 1, bear_pr, source_obj.id, obj_id=1)
    PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYourControl(
        grant_flying_counter=True,
    ).resolve(state, controller_id=0, targets=())
    assert creature.flying_counters == 1
    assert "flying" in effective_keywords(state, creature)


def test_put_creature_recall_with_subtype_pt_rider():
    state = _new_state()
    source_pr = make_artifact("Source", "{2}")
    source_obj = GameObject(
        id=99, printing=source_pr, owner_id=0, controller_id=0,
        zone=Zone.GRAVEYARD,
    )
    state.resolving_source = source_obj
    bear_pr = make_creature("Bear", "{1}{G}", power=2, toughness=2)
    creature = _put_in_exile(state, 1, bear_pr, source_obj.id, obj_id=1)
    PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYourControl(
        grant_subtype_and_pt=("Spirit", 1, 1),
    ).resolve(state, controller_id=0, targets=())
    subs = effective_subtypes(state, creature)
    assert "Spirit" in subs


def test_put_creature_recall_no_creature_cards_is_silent_noop():
    state = _new_state()
    source_pr = make_artifact("Source", "{2}")
    source_obj = GameObject(
        id=99, printing=source_pr, owner_id=0, controller_id=0,
        zone=Zone.GRAVEYARD,
    )
    state.resolving_source = source_obj
    PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYourControl(
        grant_flying_counter=True,
        grant_subtype_and_pt=("Spirit", 1, 1),
    ).resolve(state, controller_id=0, targets=())
    assert state.battlefield == []


def test_put_creature_recall_no_source_is_noop():
    state = _new_state()
    # No resolving_source set.
    PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYourControl(
        grant_flying_counter=True,
    ).resolve(state, controller_id=0, targets=())


def test_put_creature_recall_describe_with_riders():
    desc = PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYourControl(
        grant_flying_counter=True,
        grant_subtype_and_pt=("Spirit", 1, 1),
    ).describe()
    assert "creature card exiled with this permanent" in desc
    assert "flying counter" in desc
    assert "1/1 Spirit" in desc
