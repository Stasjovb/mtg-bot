"""Unit tests for the generic ``MayDo``, ``IfYouDo`` and ``IfNot``
combinators.

These verify the contract of the combinators directly — Vengeful
Possession exercises ``MayDo`` / ``IfYouDo`` indirectly and Splitskin
Doll exercises ``IfNot`` indirectly, but the combinators are reusable
primitives that need their own coverage so the contract doesn't drift.

``MayDo``:
- Calls ``Agent.choose_yes_no``.
- Returns ``False`` if declined.
- Returns whatever ``inner.resolve`` returned if accepted.

``IfYouDo``:
- Runs ``do_action``; reads its return value.
- ``False`` → skip ``then_action``.
- ``True`` or ``None`` → run ``then_action``.

``IfNot``:
- Reads ``condition.matches(state, controller_id)`` at resolve time.
- ``True``  → no-op (the unless-clause "dodges" the inner action).
- ``False`` → run ``then`` and propagate its return value.
"""

from __future__ import annotations

from dataclasses import dataclass

from mtg_bot.agents import Agent
from mtg_bot.effects import (
    DiscardSelf,
    DrawCards,
    IfNot,
    IfYouDo,
    MayDo,
)
from mtg_bot.effects.base import Effect, Target
from mtg_bot.effects.conditions import Condition
from mtg_bot.cards.base import make_creature
from mtg_bot.game import GameObject, GameState, Player, Zone


# ---------------------------------------------------------------------------
# Test agents and inert recording effects
# ---------------------------------------------------------------------------


class _AlwaysYes(Agent):
    def choose_yes_no(self, state, player_id, prompt):
        return True

    def choose_discard(self, state, player_id, hand_card_ids):
        return hand_card_ids[0]


class _AlwaysNo(Agent):
    def choose_yes_no(self, state, player_id, prompt):
        return False

    def choose_discard(self, state, player_id, hand_card_ids):
        return hand_card_ids[0]


@dataclass(frozen=True)
class _ReturnsTrue(Effect):
    """Inert effect that records it ran and returns True. Use for
    testing IfYouDo's success-path."""

    def resolve(self, state, controller_id, targets=()):
        state.log.append("_ReturnsTrue ran")
        return True

    def describe(self) -> str:
        return "ReturnsTrue"


@dataclass(frozen=True)
class _ReturnsFalse(Effect):
    """Inert effect that records it ran and returns False. Use for
    testing IfYouDo's failure-path."""

    def resolve(self, state, controller_id, targets=()):
        state.log.append("_ReturnsFalse ran")
        return False

    def describe(self) -> str:
        return "ReturnsFalse"


@dataclass(frozen=True)
class _ReturnsNone(Effect):
    """Inert effect that records it ran and returns None implicitly
    (the back-compat default for effects that don't yet signal
    completion). IfYouDo treats None as True."""

    def resolve(self, state, controller_id, targets=()):
        state.log.append("_ReturnsNone ran")

    def describe(self) -> str:
        return "ReturnsNone"


@dataclass(frozen=True)
class _Sentinel(Effect):
    """Inert effect that just logs — the canonical "did the follow-up
    fire?" probe."""

    tag: str = "follow-up"

    def resolve(self, state, controller_id, targets=()):
        state.log.append(f"_Sentinel({self.tag}) ran")

    def describe(self) -> str:
        return f"Sentinel({self.tag})"


def _new_state_with_agent(agent: Agent) -> GameState:
    return GameState(players=[Player(id=0, agent=agent), Player(id=1)])


# ---------------------------------------------------------------------------
# MayDo
# ---------------------------------------------------------------------------


def test_may_do_yes_runs_inner_and_returns_inner_result():
    state = _new_state_with_agent(_AlwaysYes())
    result = MayDo(_ReturnsTrue()).resolve(state, controller_id=0)
    assert "_ReturnsTrue ran" in state.log
    assert result is True


def test_may_do_yes_propagates_inner_false():
    state = _new_state_with_agent(_AlwaysYes())
    result = MayDo(_ReturnsFalse()).resolve(state, controller_id=0)
    assert "_ReturnsFalse ran" in state.log
    assert result is False


def test_may_do_yes_propagates_inner_none():
    # None is the default for effects that don't yet signal completion.
    # MayDo passes it through verbatim — IfYouDo can interpret None as
    # success.
    state = _new_state_with_agent(_AlwaysYes())
    result = MayDo(_ReturnsNone()).resolve(state, controller_id=0)
    assert "_ReturnsNone ran" in state.log
    assert result is None


def test_may_do_no_skips_inner_and_returns_false():
    state = _new_state_with_agent(_AlwaysNo())
    result = MayDo(_ReturnsTrue()).resolve(state, controller_id=0)
    assert "_ReturnsTrue ran" not in state.log
    assert result is False


def test_may_do_describe():
    desc = MayDo(_ReturnsTrue()).describe()
    assert desc.startswith("you may ")


# ---------------------------------------------------------------------------
# IfYouDo
# ---------------------------------------------------------------------------


def test_if_you_do_runs_then_when_action_returns_true():
    state = _new_state_with_agent(_AlwaysYes())
    IfYouDo(
        do_action=_ReturnsTrue(),
        then_action=_Sentinel(tag="ran"),
    ).resolve(state, controller_id=0)
    assert "_ReturnsTrue ran" in state.log
    assert "_Sentinel(ran) ran" in state.log


def test_if_you_do_runs_then_when_action_returns_none():
    # None is treated as success (back-compat for effects that don't
    # signal completion).
    state = _new_state_with_agent(_AlwaysYes())
    IfYouDo(
        do_action=_ReturnsNone(),
        then_action=_Sentinel(tag="ran"),
    ).resolve(state, controller_id=0)
    assert "_ReturnsNone ran" in state.log
    assert "_Sentinel(ran) ran" in state.log


def test_if_you_do_skips_then_when_action_returns_false():
    state = _new_state_with_agent(_AlwaysYes())
    IfYouDo(
        do_action=_ReturnsFalse(),
        then_action=_Sentinel(tag="should-skip"),
    ).resolve(state, controller_id=0)
    assert "_ReturnsFalse ran" in state.log
    assert "_Sentinel(should-skip) ran" not in state.log


# ---------------------------------------------------------------------------
# IfYouDo + MayDo composition (the full "you may X. If you do, Y." shape)
# ---------------------------------------------------------------------------


def test_compose_may_then_if_you_do_runs_then_when_yes():
    state = _new_state_with_agent(_AlwaysYes())
    IfYouDo(
        do_action=MayDo(_ReturnsTrue()),
        then_action=_Sentinel(tag="ran"),
    ).resolve(state, controller_id=0)
    assert "_Sentinel(ran) ran" in state.log


def test_compose_may_then_if_you_do_skips_then_when_no():
    state = _new_state_with_agent(_AlwaysNo())
    IfYouDo(
        do_action=MayDo(_ReturnsTrue()),
        then_action=_Sentinel(tag="should-skip"),
    ).resolve(state, controller_id=0)
    assert "_ReturnsTrue ran" not in state.log
    assert "_Sentinel(should-skip) ran" not in state.log


def test_compose_may_discard_then_draw_with_card_in_hand():
    # The canonical looter shape: "you may discard a card. If you do,
    # draw a card." Verifies DiscardSelf returns True (so IfYouDo
    # gates True) when there's a card to discard.
    junk_pr = make_creature("Junk", "{1}", power=1, toughness=1)
    junk = GameObject(
        id=1, printing=junk_pr, owner_id=0, controller_id=0,
        zone=Zone.HAND,
    )
    library_card = GameObject(
        id=2, printing=junk_pr, owner_id=0, controller_id=0,
        zone=Zone.LIBRARY,
    )
    p0 = Player(id=0, agent=_AlwaysYes())
    p0.hand = [junk]
    p0.library = [library_card]
    state = GameState(players=[p0, Player(id=1)])

    IfYouDo(
        do_action=MayDo(DiscardSelf(amount=1)),
        then_action=DrawCards(amount=1),
    ).resolve(state, controller_id=0)

    # Card discarded.
    assert junk in p0.graveyard
    # Library card drawn — IfYouDo gate fired through.
    assert library_card in p0.hand


def test_compose_may_discard_then_draw_with_empty_hand_fizzles():
    # DiscardSelf returns False on empty hand → IfYouDo skips the
    # draw → no library card moves to hand.
    junk_pr = make_creature("Junk", "{1}", power=1, toughness=1)
    library_card = GameObject(
        id=2, printing=junk_pr, owner_id=0, controller_id=0,
        zone=Zone.LIBRARY,
    )
    p0 = Player(id=0, agent=_AlwaysYes())
    # Empty hand.
    p0.library = [library_card]
    state = GameState(players=[p0, Player(id=1)])

    IfYouDo(
        do_action=MayDo(DiscardSelf(amount=1)),
        then_action=DrawCards(amount=1),
    ).resolve(state, controller_id=0)

    # Library card NOT drawn — empty-hand discard returned False,
    # IfYouDo gate skipped the draw.
    assert library_card in p0.library
    assert library_card not in p0.hand


def test_compose_decline_skips_discard_and_draw():
    # The agent says no — neither the discard nor the draw should
    # happen.
    junk_pr = make_creature("Junk", "{1}", power=1, toughness=1)
    junk = GameObject(
        id=1, printing=junk_pr, owner_id=0, controller_id=0,
        zone=Zone.HAND,
    )
    library_card = GameObject(
        id=2, printing=junk_pr, owner_id=0, controller_id=0,
        zone=Zone.LIBRARY,
    )
    p0 = Player(id=0, agent=_AlwaysNo())
    p0.hand = [junk]
    p0.library = [library_card]
    state = GameState(players=[p0, Player(id=1)])

    IfYouDo(
        do_action=MayDo(DiscardSelf(amount=1)),
        then_action=DrawCards(amount=1),
    ).resolve(state, controller_id=0)

    # No discard.
    assert junk in p0.hand
    assert junk not in p0.graveyard
    # No draw.
    assert library_card in p0.library
    assert library_card not in p0.hand


# ---------------------------------------------------------------------------
# IfNot
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _StaticCondition(Condition):
    """A constant-value condition for exercising IfNot independently of
    any state shape. ``value`` drives ``matches``; ``multiplier``
    inherits the default of 1."""

    value: bool

    def matches(self, state, viewer_id, chosen_targets=None):
        return self.value


def test_if_not_skips_then_when_condition_true():
    # Condition true → IfNot is a no-op; the inner ``then`` doesn't run
    # and the resolve result signals the skip via ``False``.
    state = _new_state_with_agent(_AlwaysYes())
    result = IfNot(
        condition=_StaticCondition(value=True),
        then=_Sentinel(tag="should-skip"),
    ).resolve(state, controller_id=0)
    assert "_Sentinel(should-skip) ran" not in state.log
    assert result is False


def test_if_not_runs_then_when_condition_false():
    # Condition false → IfNot runs the inner ``then`` normally and
    # propagates its return value (None for sentinel effects without
    # an explicit completion signal).
    state = _new_state_with_agent(_AlwaysYes())
    result = IfNot(
        condition=_StaticCondition(value=False),
        then=_Sentinel(tag="ran"),
    ).resolve(state, controller_id=0)
    assert "_Sentinel(ran) ran" in state.log
    # Sentinel resolve returns None implicitly; IfNot propagates.
    assert result is None


def test_if_not_propagates_inner_true():
    # When the inner ``then`` returns True, IfNot returns True.
    state = _new_state_with_agent(_AlwaysYes())
    result = IfNot(
        condition=_StaticCondition(value=False),
        then=_ReturnsTrue(),
    ).resolve(state, controller_id=0)
    assert "_ReturnsTrue ran" in state.log
    assert result is True


def test_if_not_propagates_inner_false():
    # When the inner ``then`` returns False (e.g. ``DiscardSelf`` on
    # empty hand), IfNot returns False — distinguishable from the
    # condition-true skip path only by the log entry, but both indicate
    # "the unless clause didn't accomplish anything".
    state = _new_state_with_agent(_AlwaysYes())
    result = IfNot(
        condition=_StaticCondition(value=False),
        then=_ReturnsFalse(),
    ).resolve(state, controller_id=0)
    assert "_ReturnsFalse ran" in state.log
    assert result is False


def test_if_not_describe_includes_then_and_unless():
    desc = IfNot(
        condition=_StaticCondition(value=True),
        then=_Sentinel(tag="x"),
    ).describe()
    assert "Sentinel(x)" in desc
    assert "unless" in desc


def test_if_not_target_count_range_passes_through_inner():
    # IfNot wraps an inner effect and exposes the inner's targeting
    # contract — ``requires_target``, ``target_count_range``, and
    # ``legal_targets`` all delegate to the inner. Sentinel is
    # untargeted so the range collapses to (0, 0).
    inner = _Sentinel(tag="probe")
    cond = _StaticCondition(value=False)
    eff = IfNot(condition=cond, then=inner)
    assert eff.requires_target() is False
    assert eff.target_count_range() == (0, 0)
    state = _new_state_with_agent(_AlwaysYes())
    assert eff.legal_targets(state, controller_id=0) == []
