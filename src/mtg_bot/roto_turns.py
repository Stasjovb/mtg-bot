"""Turn structure for the Vintage Roto P4 package (draw-step skips,
ending the turn, extra-turn riders) plus the sideboard ("outside the
game") helpers Wish effects read.

The sideboard model is the user's decision (2026-10-02): "a card you own
from outside the game" is fetched from the player's sideboard, which
``simulate.setup_game(sideboards=...)`` takes as an explicit input
(empty by default). In a roto draft the sideboard is the drafter's
picks that didn't make the main deck.

Both turn loops (``simulate.run_turn`` and the search adapter's
``_advance_to_next_step``) pick the next step through
``turn.next_step``; that function consults
:func:`turn_structure_next_step` -- the single turn-structure hook -- so
the two loops can't diverge. Shortcuts are documented in the "Vintage
Roto P4" section of ``docs/SEARCH_LIMITATIONS.md``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mtg_bot.game import GameObject, GameState
    from mtg_bot.turn import Step


# ---------------------------------------------------------------------------
# "Skip your draw step." (CR 614.10)
# ---------------------------------------------------------------------------


def skips_draw_step(state: "GameState", player_id: int) -> bool:
    """Whether ``player_id`` controls a permanent (or emblem) with an
    active "Skip your draw step." static (Necropotence, Yawgmoth's
    Bargain)."""
    from mtg_bot.game import _active_static_abilities

    for obj in (*state.battlefield, *state.emblems):
        if obj.controller_id != player_id:
            continue
        if any(
            st.skips_your_draw_step for st in _active_static_abilities(obj)
        ):
            return True
    return False


def schedule_at_your_next_end_step(
    state: "GameState", controller_id: int, source_id: int, effect,
) -> None:
    """Schedule ``effect`` as a delayed trigger "at the beginning of your
    next end step" (CR 603.7): ``controller_id``'s first end step that
    begins after now -- this turn's if it is their turn and the end
    step hasn't begun, otherwise the first end step of a later turn of
    theirs (extra turns included; ``turn.run_delayed_end_step_triggers``
    honours ``own_next_end_step``). ``source_id`` is the object the
    delayed trigger acts on (``state.resolving_source`` on resolution)."""
    from mtg_bot.turn import Step

    this_turn = (
        state.active_player().id == controller_id
        and state.step not in (Step.END, Step.CLEANUP)
    )
    state.delayed_triggers.append({
        "fire_at_turn": state.turn_number + (0 if this_turn else 1),
        "controller_id": controller_id,
        "source_id": source_id,
        "effect": effect,
        "own_next_end_step": True,
    })


def turn_structure_next_step(
    state: "GameState", current: "Step",
) -> "Step | None":
    """The step that replaces ``current``'s natural successor, or
    ``None`` to follow the normal order.

    * The turn was ended ("End the turn." -- Sundial of the Infinite,
      Day's Undoing; CR 723.1d): every step up to cleanup is skipped.
    * The active player skips their draw step (CR 614.10: a skipped
      step simply doesn't happen -- no turn-based draw, no "beginning
      of the draw step" triggers, no priority): upkeep is followed by
      the precombat main phase.
    """
    from mtg_bot.turn import Step

    if state.turn_ending:
        state.turn_ending = False
        if current != Step.END:
            state.log.append("the turn ends: skipping to the cleanup step")
        return Step.CLEANUP
    if current == Step.UPKEEP:
        ap = state.active_player()
        if skips_draw_step(state, ap.id):
            state.log.append(f"P{ap.id} skips their draw step")
            return Step.PRECOMBAT_MAIN
    return None


# ---------------------------------------------------------------------------
# "End the turn." (CR 723)
# ---------------------------------------------------------------------------


def end_the_turn(state: "GameState") -> None:
    """CR 723.1: exile every object on the stack -- the resolving spell
    included (a spell copy or an ability simply ceases to exist) --,
    remove every creature from combat, and skip straight to the cleanup
    step. No player gets priority in between: ``state.turn_ending``
    leaves only passing legal (``legal.legal_actions``) until
    ``turn.next_step`` jumps to cleanup."""
    from mtg_bot.combat import clear_combat_state
    from mtg_bot.game import Zone

    spells = [item.source for item in state.stack if item.ability is None]
    resolving = state.resolving_spell
    if resolving is not None and resolving.zone == Zone.STACK:
        spells.append(resolving)
    state.stack.clear()
    for card in spells:
        if card.is_spell_copy:
            continue
        card.cast_via_flashback = False
        card.zone = Zone.EXILE
        state.player_by_id(card.owner_id).exile.append(card)
        state.log.append(f"{card.printing.name} is exiled (the turn ends)")
    clear_combat_state(state)
    state.turn_ending = True
    state.log.append("the turn is ended")



# ---------------------------------------------------------------------------
# Outside the game: the sideboard (CR 400.11)
# ---------------------------------------------------------------------------


def sideboard_printings(player_id: int, names: list[str]) -> tuple:
    """The printings for a player's sideboard card names (one entry per
    copy), validated against the active card source like a decklist."""
    from mtg_bot.cards.source import get_active_source

    printings = get_active_source().get_printings()
    unknown = sorted({n for n in names if n not in printings})
    if unknown:
        raise ValueError(
            f"sideboard for player {player_id} contains unknown cards: "
            f"{unknown}"
        )
    return tuple(printings[n] for n in names)


def take_from_outside_the_game(
    state: "GameState", player_id: int, printing,
) -> "GameObject":
    """Bring one copy of ``printing`` from ``player_id``'s sideboard into
    their hand, revealed (CR 400.11b: it becomes a new object in the
    game). Raises ``ValueError`` if the sideboard holds no such card."""
    from mtg_bot.game import Zone, reveal_to_all

    p = state.player_by_id(player_id)
    entries = list(p.sideboard)
    try:
        entries.remove(printing)
    except ValueError:
        raise ValueError(
            f"P{player_id} owns no {printing.name} outside the game"
        ) from None
    p.sideboard = tuple(entries)
    card = state.new_object(printing, owner_id=player_id, zone=Zone.HAND)
    p.hand.append(card)
    reveal_to_all(state, card)
    state.log.append(
        f"P{player_id} reveals {printing.name} from outside the game and "
        "puts it into their hand"
    )
    return card
