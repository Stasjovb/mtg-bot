"""Tests for Alpharael, Dreaming Acolyte's ETB:

  "When Alpharael enters, draw two cards. Then discard two cards
   unless you discard an artifact card."

Covers:
- The "with-artifact dodge" path: agent picks the artifact branch and
  discards exactly one artifact card.
- The "without-artifact fallback" path: no artifact in hand → forced
  two-card discard regardless of agent preference.
- The "agent declines the dodge" branch: artifact is available but
  agent picks mode 1 → falls back to discarding two cards.
- Defensive handling when the agent returns a non-artifact id while
  in artifact-dodge mode.
- Printing metadata (legendary, deathtouch static) survives the rewire.
"""

from mtg_bot.actions import put_into_battlefield, resolve_top_of_stack
from mtg_bot.agents import Agent
from mtg_bot.cards import BASIC_LANDS
from mtg_bot.effects import AlpharaelDreamingAcolyteDiscardEffect
from mtg_bot.game import GameState, Player, Zone
from tests._etb_helpers import _legacy_or_inferred_key, _matches_legacy_key

from mtg_bot.cards.source import get_active_source

_PRINTINGS = get_active_source().get_printings()


class _ScriptedAgent(Agent):
    """Agent that returns scripted answers for the decision points
    Alpharael's ETB pokes at — choose_mode for the dodge fork and
    choose_discard for which card to actually pitch."""

    def __init__(
        self,
        mode_pick: int = 1,
        discard_picker=None,
    ):
        self.mode_pick = mode_pick
        # discard_picker: callable(hand_card_ids) -> int.
        # Default: pick the first id offered.
        self.discard_picker = discard_picker or (lambda ids: ids[0])
        self.mode_calls: list[list[str]] = []
        self.discard_calls: list[list[int]] = []

    def choose_mode(self, state, player_id, mode_descriptions):
        self.mode_calls.append(list(mode_descriptions))
        return self.mode_pick

    def choose_discard(self, state, player_id, hand_card_ids):
        self.discard_calls.append(list(hand_card_ids))
        return self.discard_picker(hand_card_ids)


def _new_state(p0_agent=None, p1_agent=None):
    state = GameState()
    state.players.append(Player(id=0, agent=p0_agent or _ScriptedAgent()))
    state.players.append(Player(id=1, agent=p1_agent or _ScriptedAgent()))
    return state


def _stock_library(state, player_id, n=20):
    """Give the player enough library to absorb 2-card draws without
    drawing themselves to death."""
    p = state.player_by_id(player_id)
    for _ in range(n):
        c = state.new_object(BASIC_LANDS["Plains"], player_id, Zone.LIBRARY)
        p.library.append(c)


def _resolve_all(state):
    while state.stack:
        resolve_top_of_stack(state)


# -----------------------
# Effect-level tests (resolve directly, no stack)
# -----------------------


def test_artifact_dodge_discards_one_artifact_when_available():
    """Hand has 1 artifact + 2 non-artifacts. Agent picks mode 0
    (the dodge). Exactly the artifact card moves to graveyard; the
    two non-artifact cards stay in hand."""
    agent = _ScriptedAgent(mode_pick=0)
    state = _new_state(p0_agent=agent)
    p = state.players[0]
    plains_a = state.new_object(BASIC_LANDS["Plains"], 0, Zone.HAND)
    plains_b = state.new_object(BASIC_LANDS["Plains"], 0, Zone.HAND)
    artifact = state.new_object(
        _PRINTINGS["Mechan Assembler"], 0, Zone.HAND,
    )
    p.hand.extend([plains_a, plains_b, artifact])

    AlpharaelDreamingAcolyteDiscardEffect().resolve(state, 0, ())

    # Exactly one card discarded — the artifact.
    assert artifact in p.graveyard
    assert plains_a in p.hand
    assert plains_b in p.hand
    assert len(p.hand) == 2
    # Mode prompt was shown with both options, in order.
    assert agent.mode_calls == [
        ["discard an artifact card", "discard two cards"],
    ]
    # choose_discard was called once, with only the artifact id.
    assert agent.discard_calls == [[artifact.id]]


def test_artifact_dodge_respected_only_when_artifact_in_hand():
    """No artifact in hand → mode prompt is skipped and the
    fallback two-card discard fires unconditionally."""
    agent = _ScriptedAgent(mode_pick=0)  # would prefer dodge if asked
    state = _new_state(p0_agent=agent)
    p = state.players[0]
    a = state.new_object(BASIC_LANDS["Plains"], 0, Zone.HAND)
    b = state.new_object(BASIC_LANDS["Forest"], 0, Zone.HAND)
    c = state.new_object(BASIC_LANDS["Island"], 0, Zone.HAND)
    p.hand.extend([a, b, c])

    AlpharaelDreamingAcolyteDiscardEffect().resolve(state, 0, ())

    # Two cards moved to graveyard, one survives.
    assert len(p.graveyard) == 2
    assert len(p.hand) == 1
    # No mode prompt issued (artifact-dodge wasn't an option).
    assert agent.mode_calls == []
    # Two discard prompts (one per card).
    assert len(agent.discard_calls) == 2


def test_agent_declines_dodge_falls_back_to_two_discard():
    """Hand has an artifact, but agent picks mode 1 → discards two
    cards (any). The artifact may or may not be among them — what
    matters is two cards leave hand."""
    # Discard picker prefers the non-artifact cards (returns first
    # non-artifact id when offered, else first id).
    def picker(ids):
        return ids[0]

    agent = _ScriptedAgent(mode_pick=1, discard_picker=picker)
    state = _new_state(p0_agent=agent)
    p = state.players[0]
    plains = state.new_object(BASIC_LANDS["Plains"], 0, Zone.HAND)
    forest = state.new_object(BASIC_LANDS["Forest"], 0, Zone.HAND)
    artifact = state.new_object(
        _PRINTINGS["Mechan Assembler"], 0, Zone.HAND,
    )
    p.hand.extend([plains, forest, artifact])

    AlpharaelDreamingAcolyteDiscardEffect().resolve(state, 0, ())

    # Mode prompt was shown (artifact was in hand) but agent picked 1.
    assert agent.mode_calls == [
        ["discard an artifact card", "discard two cards"],
    ]
    # Two cards discarded total.
    assert len(p.graveyard) == 2
    assert len(p.hand) == 1


def test_empty_hand_resolves_no_op():
    """No cards in hand → effect is a no-op (no agent calls, nothing
    moves). Defensive guard against the "draw two then immediately
    discard from empty hand" edge case if a pump effect cleared hand."""
    agent = _ScriptedAgent(mode_pick=0)
    state = _new_state(p0_agent=agent)
    AlpharaelDreamingAcolyteDiscardEffect().resolve(state, 0, ())
    assert agent.mode_calls == []
    assert agent.discard_calls == []
    assert state.players[0].hand == []
    assert state.players[0].graveyard == []


def test_artifact_dodge_falls_back_when_agent_returns_non_artifact():
    """Defensive: in artifact-dodge mode, if the agent breaks contract
    and returns a non-artifact id, the effect should still discard an
    artifact (the first available) rather than crash or silently
    pitch a non-artifact."""
    plains_id_capture: dict[str, int] = {}

    def bad_picker(ids):
        # Return an id that's NOT in the offered list (simulating an
        # out-of-contract agent).
        return plains_id_capture["non_artifact_id"]

    agent = _ScriptedAgent(mode_pick=0, discard_picker=bad_picker)
    state = _new_state(p0_agent=agent)
    p = state.players[0]
    plains = state.new_object(BASIC_LANDS["Plains"], 0, Zone.HAND)
    artifact_a = state.new_object(
        _PRINTINGS["Mechan Assembler"], 0, Zone.HAND,
    )
    artifact_b = state.new_object(
        _PRINTINGS["Mechan Assembler"], 0, Zone.HAND,
    )
    p.hand.extend([plains, artifact_a, artifact_b])
    plains_id_capture["non_artifact_id"] = plains.id

    AlpharaelDreamingAcolyteDiscardEffect().resolve(state, 0, ())

    # The first artifact id (artifact_a) was the fallback pick. Plains
    # stays in hand; no non-artifact was discarded.
    assert artifact_a in p.graveyard
    assert plains in p.hand
    assert artifact_b in p.hand


def test_describe_text():
    d = AlpharaelDreamingAcolyteDiscardEffect().describe()
    assert "discard two cards" in d
    assert "artifact" in d


# -----------------------
# Full ETB pipeline (via stack resolution)
# -----------------------


def test_full_etb_with_artifact_dodge_draws_two_then_pitches_one_artifact():
    """End-to-end: resolve Alpharael's ETB on the stack. Hand starts
    with one artifact + nothing else; library has fillers. After the
    ETB resolves: hand grew by net +1 (drew 2, pitched 1 artifact)."""
    agent = _ScriptedAgent(mode_pick=0)
    state = _new_state(p0_agent=agent)
    _stock_library(state, 0, n=10)
    p = state.players[0]
    artifact = state.new_object(
        _PRINTINGS["Mechan Assembler"], 0, Zone.HAND,
    )
    p.hand.append(artifact)
    hand_before = len(p.hand)

    alpha = state.new_object(
        _PRINTINGS["Alpharael, Dreaming Acolyte"], 0, Zone.HAND,
    )
    put_into_battlefield(state, alpha, controller_id=0)
    _resolve_all(state)

    # Net hand size: started with 1, drew 2 (=3), discarded 1 (=2).
    assert len(p.hand) == hand_before + 1
    # The discarded card is the artifact.
    assert artifact in p.graveyard


def test_full_etb_without_artifact_pitches_two():
    """End-to-end: no artifact in hand → fallback discard of two."""
    agent = _ScriptedAgent(mode_pick=0)  # would prefer dodge; can't
    state = _new_state(p0_agent=agent)
    _stock_library(state, 0, n=10)
    # Empty hand at start: draws 2, then discards 2.
    p = state.players[0]
    alpha = state.new_object(
        _PRINTINGS["Alpharael, Dreaming Acolyte"], 0, Zone.HAND,
    )
    put_into_battlefield(state, alpha, controller_id=0)
    _resolve_all(state)

    # Drew 2, discarded 2 → net 0 in hand.
    assert len(p.hand) == 0
    assert len(p.graveyard) == 2


# -----------------------
# Printing metadata
# -----------------------


def test_alpharael_dreaming_acolyte_printing_metadata():
    a = _PRINTINGS["Alpharael, Dreaming Acolyte"]
    assert "Legendary" in a.supertypes
    # Single ETB triggered ability.
    assert len(a.triggered_abilities) == 1
    ab = a.triggered_abilities[0]
    assert _matches_legacy_key(ab, "etb")
    # Static deathtouch on own turn.
    assert len(a.static_abilities) == 1
    sa = a.static_abilities[0]
    # PR-D continuous-effects shape: keyword rides on a layer-6
    # ``ContinuousModifier(GrantKeyword)`` and the during-your-turn
    # gate is a structural ``condition=DuringYourTurn()``.
    from mtg_bot.effects.conditions import DuringYourTurn
    from mtg_bot.effects.modifiers import ContinuousModifier, GrantKeyword
    assert sa.continuous_effect == ContinuousModifier(
        layer=6, payload=GrantKeyword("deathtouch"),
    )
    assert sa.condition == DuringYourTurn()
    assert sa.granted_keywords == frozenset()
    assert sa.active_turn_only is False
