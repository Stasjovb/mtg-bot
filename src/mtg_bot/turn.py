"""Turn structure: steps, turn-based actions, and state-based actions."""

from __future__ import annotations

from enum import Enum

from mtg_bot.game import GameState, Zone


class Step(Enum):
    UNTAP = "untap"
    UPKEEP = "upkeep"
    DRAW = "draw"
    PRECOMBAT_MAIN = "precombat_main"
    BEGINNING_OF_COMBAT = "beginning_of_combat"
    DECLARE_ATTACKERS = "declare_attackers"
    DECLARE_BLOCKERS = "declare_blockers"
    COMBAT_DAMAGE = "combat_damage"
    END_OF_COMBAT = "end_of_combat"
    POSTCOMBAT_MAIN = "postcombat_main"
    END = "end"
    CLEANUP = "cleanup"


STEP_ORDER: tuple[Step, ...] = (
    Step.UNTAP, Step.UPKEEP, Step.DRAW,
    Step.PRECOMBAT_MAIN,
    Step.BEGINNING_OF_COMBAT, Step.DECLARE_ATTACKERS, Step.DECLARE_BLOCKERS,
    Step.COMBAT_DAMAGE, Step.END_OF_COMBAT,
    Step.POSTCOMBAT_MAIN,
    Step.END, Step.CLEANUP,
)

MAIN_STEPS: frozenset[Step] = frozenset({Step.PRECOMBAT_MAIN, Step.POSTCOMBAT_MAIN})
COMBAT_STEPS: frozenset[Step] = frozenset({
    Step.BEGINNING_OF_COMBAT, Step.DECLARE_ATTACKERS, Step.DECLARE_BLOCKERS,
    Step.COMBAT_DAMAGE, Step.END_OF_COMBAT,
})
# Untap and cleanup don't normally grant priority.
STEPS_WITH_PRIORITY: frozenset[Step] = frozenset(set(STEP_ORDER) - {Step.UNTAP, Step.CLEANUP})


def run_untap_step(state: GameState) -> None:
    ap = state.active_player()
    ap.lands_played_this_turn = 0
    for obj in state.battlefield:
        if obj.controller_id == ap.id:
            obj.tapped = False
            obj.summoning_sick = False


def draw_card(state: GameState, player_id: int) -> None:
    p = state.player_by_id(player_id)
    if not p.library:
        p.has_lost = True
        p.lost_reason = "drew from empty library"
        return
    top = p.library.pop(0)
    top.zone = Zone.HAND
    p.hand.append(top)


def run_draw_step(state: GameState) -> None:
    draw_card(state, state.active_player().id)


def run_cleanup_step(state: GameState) -> None:
    ap = state.active_player()
    while len(ap.hand) > 7:
        card = ap.hand.pop()
        card.zone = Zone.GRAVEYARD
        ap.graveyard.append(card)
    for obj in state.battlefield:
        obj.damage = 0
        obj.marked_lethal = False


def state_based_actions(state: GameState) -> bool:
    """Apply state-based actions. Returns True if any changes were made."""
    changed = False

    for p in state.players:
        if not p.has_lost and p.life <= 0:
            p.has_lost = True
            p.lost_reason = "life total <= 0"
            changed = True

    destroyed = []
    for obj in state.battlefield:
        if not obj.printing.is_creature:
            continue
        tough = obj.printing.toughness or 0
        if tough <= 0 or obj.damage >= tough or obj.marked_lethal:
            destroyed.append(obj)

    for obj in destroyed:
        state.battlefield.remove(obj)
        obj.zone = Zone.GRAVEYARD
        obj.damage = 0
        obj.marked_lethal = False
        obj.tapped = False
        obj.attacking = False
        obj.blocking = None
        obj.blocked_by = []
        state.player_by_id(obj.owner_id).graveyard.append(obj)
        state.log.append(f"{obj.printing.name} destroyed (lethal damage)")
        changed = True

    alive = [p for p in state.players if not p.has_lost]
    if len(alive) == 0 and not state.is_draw:
        state.is_draw = True
        changed = True
    elif (
        len(alive) == 1
        and state.winner_id is None
        and len(state.players) > 1
    ):
        state.winner_id = alive[0].id
        changed = True

    return changed
