"""Tests for subtype-filtered targets and graveyard-to-hand effects.

Covers All-Fates Stalker's "non-Assassin" target filter on
ExileTargetCreatureUntilSourceLeaves, and Scour for Scrap's modal
"search library for artifact OR return artifact from graveyard" effect
with the new ReturnTargetArtifactCardFromYourGraveyardToHand.
"""

from mtg_bot.agents import Agent, RandomAgent
from mtg_bot.cards import BASIC_LANDS, SYNTHETIC_CREATURES
from mtg_bot.effects import (
    ExileTargetCreatureUntilSourceLeaves,
    ModalChooseOne,
    ReturnTargetArtifactCardFromYourGraveyardToHand,
    SearchLibraryForCard,
)
from mtg_bot.game import GameState, Player, Zone

from mtg_bot.cards.source import get_active_source

_PRINTINGS = get_active_source().get_printings()


def _new_state():
    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    return state


# -----------------------
# ExileTargetCreatureUntilSourceLeaves.excluded_subtypes
# -----------------------


def test_all_fates_stalker_excludes_assassin_creatures():
    """Legal targets must skip creatures with excluded subtypes.
    All-Fates Stalker is itself an Assassin — excluded via filter."""
    state = _new_state()
    stalker = state.new_object(
        _PRINTINGS["All-Fates Stalker"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(stalker)
    # Another Assassin — should NOT be a legal target.
    other_stalker = state.new_object(
        _PRINTINGS["All-Fates Stalker"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(other_stalker)
    # A non-Assassin creature — should be legal.
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear)
    effect = ExileTargetCreatureUntilSourceLeaves(
        excluded_subtypes=frozenset({"Assassin"}),
    )
    legal = effect.legal_targets(state, 0)
    assert ("creature", bear.id) in legal
    assert ("creature", stalker.id) not in legal
    assert ("creature", other_stalker.id) not in legal


def test_exile_target_creature_no_excluded_allows_all_creatures():
    """When excluded_subtypes is empty, every creature is fair game."""
    state = _new_state()
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear)
    effect = ExileTargetCreatureUntilSourceLeaves()
    assert ("creature", bear.id) in effect.legal_targets(state, 0)


# -----------------------
# ReturnTargetArtifactCardFromYourGraveyardToHand
# -----------------------


def test_return_target_artifact_from_graveyard_happy_path():
    state = _new_state()
    p = state.players[0]
    # Put an artifact in the graveyard.
    artifact = state.new_object(
        _PRINTINGS["Memorial Vault"], 0, Zone.GRAVEYARD,
    )
    p.graveyard.append(artifact)
    effect = ReturnTargetArtifactCardFromYourGraveyardToHand()
    legal = effect.legal_targets(state, 0)
    assert legal == [("graveyard_artifact", artifact.id)]
    effect.resolve(state, 0, (("graveyard_artifact", artifact.id),))
    assert artifact not in p.graveyard
    assert artifact in p.hand
    assert artifact.zone == Zone.HAND


def test_return_target_artifact_empty_graveyard_no_legal_targets():
    state = _new_state()
    effect = ReturnTargetArtifactCardFromYourGraveyardToHand()
    assert effect.legal_targets(state, 0) == []


def test_return_target_artifact_missing_target_returns_early():
    """Defensive: target id not in caster's graveyard is a no-op."""
    state = _new_state()
    effect = ReturnTargetArtifactCardFromYourGraveyardToHand()
    # Should not crash.
    effect.resolve(state, 0, (("graveyard_artifact", 999),))


def test_return_target_artifact_no_targets_returns_early():
    state = _new_state()
    effect = ReturnTargetArtifactCardFromYourGraveyardToHand()
    effect.resolve(state, 0, ())


def test_return_target_artifact_wrong_kind_returns_early():
    state = _new_state()
    effect = ReturnTargetArtifactCardFromYourGraveyardToHand()
    effect.resolve(state, 0, (("creature", 1),))


def test_return_target_artifact_describe():
    text = ReturnTargetArtifactCardFromYourGraveyardToHand().describe()
    assert "artifact" in text
    assert "graveyard" in text


# -----------------------
# SearchLibraryForCard: new "artifact" filter
# -----------------------


def test_search_library_for_artifact_matches_artifacts_only():
    state = _new_state()
    p = state.players[0]
    artifact = state.new_object(
        _PRINTINGS["Memorial Vault"], 0, Zone.LIBRARY,
    )
    p.library.append(artifact)
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.LIBRARY,
    )
    p.library.append(bear)
    effect = SearchLibraryForCard(filter_name="artifact")
    effect.resolve(state, 0)
    # RandomAgent will fetch one of the legal options; only the artifact
    # matches the filter.
    assert artifact in p.hand
    assert bear not in p.hand


# -----------------------
# ModalChooseOne: mixed target/untargeted castability
# -----------------------


def test_modal_choose_one_mixed_modes_not_required_to_target():
    """When at least one mode has no target, the modal effect must be
    castable even if the targeted mode's pool is empty."""
    state = _new_state()
    # No artifact in graveyard, so ReturnTargetArtifact... has no legal
    # targets. But the modal spell should still be castable because the
    # first mode (search library) is untargeted.
    effect = ModalChooseOne(modes=(
        SearchLibraryForCard(filter_name="artifact", may_fail=True),
        ReturnTargetArtifactCardFromYourGraveyardToHand(),
    ))
    # requires_target=False because not every mode needs a target.
    assert effect.requires_target() is False
    # target_count_range = (0, 1) for mixed.
    assert effect.target_count_range() == (0, 1)


def test_modal_choose_one_all_untargeted_modes():
    """All-untargeted modal: requires_target=False, (0,0) range."""
    class NullEffect:
        def requires_target(self):
            return False

    effect = ModalChooseOne(modes=(NullEffect(), NullEffect()))
    assert effect.requires_target() is False
    assert effect.target_count_range() == (0, 0)


def test_modal_choose_one_all_targeted_modes():
    """All-targeted modal: requires_target=True, (1,1) range — matches
    the pre-existing behavior for cards like Drill Too Deep."""
    class TargetedEffect:
        def requires_target(self):
            return True

    effect = ModalChooseOne(modes=(TargetedEffect(), TargetedEffect()))
    assert effect.requires_target() is True
    assert effect.target_count_range() == (1, 1)


def test_scour_for_scrap_modal_resolves_search_mode():
    """Agent picks mode 0 → searches library for an artifact.
    Scour for Scrap is "Choose one or both" — agents drive mode picks
    via ``choose_modes`` (plural) rather than ``choose_mode``."""
    class AlwaysModeZero(Agent):
        def choose_modes(self, state, player_id, mode_descriptions):
            return [0]

        def choose_card_from_library(self, state, player_id, option_ids):
            return option_ids[0] if option_ids else None

        def choose_target(self, state, player_id, legal_targets):
            return legal_targets[0] if legal_targets else None

    state = _new_state()
    state.players[0].agent = AlwaysModeZero()
    p = state.players[0]
    artifact = state.new_object(
        _PRINTINGS["Memorial Vault"], 0, Zone.LIBRARY,
    )
    p.library.append(artifact)
    scour = state.new_object(
        _PRINTINGS["Scour for Scrap"], 0, Zone.HAND,
    )
    p.hand.append(scour)
    scour.printing.spell_effect.resolve(state, 0, ())
    assert artifact in p.hand


def test_scour_for_scrap_modal_resolves_graveyard_mode():
    """Agent picks mode 1 → returns target artifact from graveyard.
    Scour for Scrap is "Choose one or both" — agents drive mode picks
    via ``choose_modes`` (plural) rather than ``choose_mode``."""
    class AlwaysModeOne(Agent):
        def choose_modes(self, state, player_id, mode_descriptions):
            return [1]

        def choose_target(self, state, player_id, legal_targets):
            return legal_targets[0] if legal_targets else None

    state = _new_state()
    state.players[0].agent = AlwaysModeOne()
    p = state.players[0]
    artifact = state.new_object(
        _PRINTINGS["Memorial Vault"], 0, Zone.GRAVEYARD,
    )
    p.graveyard.append(artifact)
    scour_printing = _PRINTINGS["Scour for Scrap"]
    scour_printing.spell_effect.resolve(
        state, 0, (("graveyard_artifact", artifact.id),),
    )
    assert artifact in p.hand
    assert artifact not in p.graveyard
