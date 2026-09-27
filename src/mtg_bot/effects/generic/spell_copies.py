"""Spell copies on the stack: Storm (Brain Freeze) and "That player may
copy this spell" (Chain of Smog).

A copy is a real ``StackItem`` whose source is a fresh ``GameObject``
flagged ``is_spell_copy`` (CR 707.10: a copy of a spell is itself a
spell on the stack, but it isn't a card — it isn't "cast", and it
ceases to exist when it leaves the stack). Copies resolve, can be
countered and can be targeted like any spell; see
``actions.push_spell_copy`` / ``actions.move_spell_off_stack``.
"""

from __future__ import annotations

from dataclasses import dataclass

from mtg_bot.effects.base import Effect


def _choose_copy_targets(state, controller_id: int, printing, original_targets):
    """New targets for a copy (CR 707.10c "you may choose new targets"):
    the copy's controller picks from the spell effect's legal targets
    (the original target is among them while still legal); with no
    agent the original targets are kept."""
    effect = printing.spell_effect
    if effect is None or not effect.requires_target():
        return tuple(original_targets)
    legal = effect.legal_targets(state, controller_id)
    if not legal:
        return tuple(original_targets)
    p = state.player_by_id(controller_id)
    if p.agent is None:
        return tuple(original_targets) or (legal[0],)
    pick = p.agent.choose_target(state, controller_id, legal)
    if pick is None or pick not in legal:
        pick = legal[0]
    return (pick,)


@dataclass(frozen=True)
class StormCopySpell(Effect):
    """The storm trigger (CR 702.40): "When you cast this spell, copy it
    for each spell cast before it this turn. You may choose new targets
    for the copies."

    ``spell_id`` is the storm spell's object id and ``count`` the number
    of spells cast before it this turn (fixed when the trigger is put on
    the stack). Copies are made from the spell on the stack; if it has
    already left the stack the copies use its last known printing.
    """

    spell_id: int = -1
    count: int = 0
    printing: "object" = None

    def resolve(self, state, controller_id, targets=()):
        from mtg_bot.actions import push_spell_copy

        item = next(
            (i for i in state.stack if i.source.id == self.spell_id), None,
        )
        printing = item.source.printing if item is not None else self.printing
        if printing is None:
            return
        original_targets = item.targets if item is not None else ()
        x_value = item.x_value if item is not None else 0
        for _ in range(self.count):
            copy_targets = _choose_copy_targets(
                state, controller_id, printing, original_targets,
            )
            push_spell_copy(
                state, printing, controller_id, copy_targets, x_value=x_value,
            )
        state.log.append(
            f"storm: {self.count} cop{'y' if self.count == 1 else 'ies'} of "
            f"{printing.name}"
        )

    def describe(self) -> str:
        return f"copy this spell {self.count} time(s)"


@dataclass(frozen=True)
class TargetPlayerMayCopyThisSpell(Effect):
    """"That player may copy this spell and may choose a new target for
    that copy." (Chain of Smog.) "That player" is the resolving spell's
    player target; they decide via ``choose_yes_no`` and pick the copy's
    target.

    ``needs_target_with_cards_in_hand``: the copy is only offered while
    some legal target has cards in hand (for a discard spell, copying
    against empty hands does nothing, and offering it would let two
    always-accepting agents copy forever).
    """

    needs_target_with_cards_in_hand: bool = True

    def resolve(self, state, controller_id, targets=()):
        from mtg_bot.actions import push_spell_copy

        spell = state.resolving_spell
        if spell is None or not targets or targets[0][0] != "player":
            return
        copier = state.player_by_id(targets[0][1])
        if copier.has_lost:
            return
        effect = spell.printing.spell_effect
        legal = effect.legal_targets(state, copier.id) if effect else []
        if self.needs_target_with_cards_in_hand and not any(
            kind == "player" and state.player_by_id(pid).hand
            for kind, pid in legal
        ):
            return
        if copier.agent is None or not copier.agent.choose_yes_no(
            state, copier.id, f"Copy {spell.printing.name}?",
        ):
            state.log.append(f"P{copier.id} declines to copy {spell.printing.name}")
            return
        copy_targets = _choose_copy_targets(
            state, copier.id, spell.printing, targets,
        )
        push_spell_copy(state, spell.printing, copier.id, copy_targets)

    def describe(self) -> str:
        return "that player may copy this spell and choose a new target"
