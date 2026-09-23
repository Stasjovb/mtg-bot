"""Action-history bookkeeping shared by search and training.

The structured NN input carries up to ``DEFAULT_ACTION_HISTORY_N``
"recent action" tokens (roadmap §3). Each token is rendered by
``mtg_bot.training.state_tokenizer`` from an :class:`ActionEvent` — the
applied decision plus a *pre-apply* engine snapshot (the tokenizer
resolves card printings against it) and the turn / step / actor at
the moment the decision was applied.

Single source of truth
----------------------
There is exactly one place that constructs these events:
:func:`record_action_event`, called from ``MtgGameStateAdapter.apply``.
The adapter carries the resulting bounded tuple on
``MtgGameStateAdapter.recent_actions``; ``clone()`` shares the (immutable)
tuple with the clone, so every search-tree child, PIMC / ISMCTS
determinized world, and the live self-play adapter all see the same
history. Both consumers read that one attribute:

- ``data_gen`` passes ``adapter.recent_actions`` to ``tokenize_state``
  when it writes a training row.
- ``NNEvaluator``'s structured path passes ``state.recent_actions`` to
  the same tokenizer at search time.

Train and inference therefore cannot drift — there is no second
history list to fall out of sync.

Why this module lives under ``mtg_bot.search``
----------------------------------------------
The adapter imports it at module load. ``mtg_bot.training`` is a
heavy package (its ``__init__`` pulls in the trainer, data_gen and the
torch model) and ``mtg_bot.training.state_tokenizer`` itself imports
``structured_model`` (torch), so the recorder must sit on the light,
engine-only side. ``state_tokenizer`` imports and re-exports
``ActionEvent`` / ``DEFAULT_ACTION_HISTORY_N`` from here so existing
callers keep working.

Cost model
----------
The pre-apply snapshot is a full ``GameState.clone()`` (~25us mid-
game). We only take it for decisions that survive the tokenizer's §3
strategic-relevance filter (drop ``PassPriority`` + mana abilities) —
~10% of applied decisions in self-play — so the amortized cost per
``apply`` is a few microseconds. Because the filter is applied *before*
bounding, ``recent_actions`` holds the last ``n`` *relevant* events,
which is exactly what the tokenizer would have computed from an
unbounded raw list (filter-then-truncate).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mtg_bot.actions import Action, ActivateAbility, PassPriority

if TYPE_CHECKING:  # pragma: no cover - typing only
    from mtg_bot.game import GameState


# Action-history window — roadmap §3 default. ``tokenize_state`` takes
# it as its default ``n``; the adapter bounds ``recent_actions`` to it.
DEFAULT_ACTION_HISTORY_N = 32


# Heuristic note for the mana-ability filter. Kept as a module-level
# string so the docstring below can reference it.
_MANA_ABILITY_HEURISTIC_NOTE = (
    "Mana-ability ActivateAbility filter: per roadmap §3, drop activations "
    "whose source is a land (the resulting tap is already visible in the "
    "next state's permanent token). Non-land activated abilities (Spacecraft "
    "stations, planeswalker loyalty, equipment, etc.) stay in the history."
)


class ActionEvent:
    """Bookkeeping struct for an action that has been applied.

    Built exclusively by :func:`record_action_event` (from
    ``MtgGameStateAdapter.apply``) so the tokenizer can read the
    temporal sequence at sample time — in training *and* at search.
    The struct is intentionally minimal — turn / step / actor are
    captured at the moment the action was applied (the pre-apply
    state); the tokenizer's redaction logic does the rest.

    ``state_snapshot`` is a *clone* of the pre-apply engine state (the
    engine mutates in place during apply, and it reassigns
    ``obj.printing`` for face-up / copy / become-type effects, so a
    reference to the live objects would not be faithful).

    Plain ``__slots__`` attributes for cheap construction.
    """

    __slots__ = (
        "action",
        "state_snapshot",
        "turn",
        "step",
        "actor_player_id",
    )

    def __init__(
        self,
        action: Action,
        state_snapshot: GameState,
        turn: int,
        step,
        actor_player_id: int,
    ) -> None:
        self.action = action
        self.state_snapshot = state_snapshot
        self.turn = turn
        self.step = step
        self.actor_player_id = actor_player_id


def _is_mana_ability(action: Action, state: GameState) -> bool:
    """Heuristic test for "this ActivateAbility represents a mana
    ability." We approximate by checking whether the source object is
    a land — the EoE pool is dominated by land mana abilities, and
    non-land mana sources (Spacecraft station, planeswalkers, etc.)
    are infrequent enough that classifying them as non-mana is safe
    for filtering purposes. See ``_MANA_ABILITY_HEURISTIC_NOTE``.

    Used only by the action-history filter; mis-classification just
    changes whether a token enters the model's history window.
    """
    if not isinstance(action, ActivateAbility):
        return False
    obj = next(
        (o for o in state.battlefield if o.id == action.source_id), None,
    )
    if obj is None:
        return False
    return bool(obj.printing.is_land)


def _is_strategically_relevant(action: Action, state: GameState) -> bool:
    """Filter rule from roadmap §3.

    - Drop ``PassPriority`` events.
    - Drop mana-ability ``ActivateAbility`` events (see helper).
    - Keep everything else (cast / play land / unlock / activate /
      station / face-up / declare / resolution-decisions).
    """
    if isinstance(action, PassPriority):
        return False
    if _is_mana_ability(action, state):
        return False
    return True


def record_action_event(
    history: tuple[ActionEvent, ...],
    *,
    action: Action,
    pre_apply_state: GameState,
    actor_player_id: int,
    n: int = DEFAULT_ACTION_HISTORY_N,
) -> tuple[ActionEvent, ...]:
    """Return ``history`` extended with the event for ``action``.

    Call this *before* applying ``action`` to ``pre_apply_state`` (the
    turn / step are read from it and it is cloned for the snapshot);
    assign the result to the carrier *after* the apply succeeds so a
    raising apply leaves the history untouched.

    - Non-relevant actions (``PassPriority``, mana abilities — see
      :func:`_is_strategically_relevant`) return ``history`` unchanged
      (same tuple object, no clone taken).
    - The result is bounded to the last ``n`` events. Filtering
      happens before bounding, so the tuple always holds the ``n``
      most recent *relevant* events — identical to what
      ``tokenize_state`` computes from an unbounded raw list.
    - ``history`` is never mutated; tuples are shared freely across
      adapter clones.
    """
    if not _is_strategically_relevant(action, pre_apply_state):
        return history
    event = ActionEvent(
        action=action,
        state_snapshot=pre_apply_state.clone(),
        turn=pre_apply_state.turn_number,
        step=pre_apply_state.step,
        actor_player_id=actor_player_id,
    )
    extended = history + (event,)
    if len(extended) > n:
        extended = extended[-n:]
    return extended


__all__ = [
    "DEFAULT_ACTION_HISTORY_N",
    "ActionEvent",
    "record_action_event",
]
