"""Player designations: the monarch (CR 724) and the initiative with
the Undercity dungeon (CR 725 / CR 309), plus goad (CR 701.38), which
the Undercity's Arena room needs.

State lives on ``Player`` (``is_monarch``, ``has_initiative``,
``dungeon_room``, ``dungeons_completed``) and ``GameObject``
(``goaded_by``), so ``GameState.clone`` carries it with no extra work.

Turn-structure hooks:

- ``on_beginning_of_upkeep`` (from ``turn.run_beginning_of_upkeep_
  triggers``): the player with the initiative ventures into Undercity.
- ``on_beginning_of_end_step`` (from ``turn.run_beginning_of_end_
  step_triggers``): the monarch draws a card.
- ``on_combat_damage_to_players`` (from ``combat._resolve_damage_step``):
  a player dealt combat damage by creatures loses the monarch /
  initiative to the attacking controller (who ventures on taking the
  initiative).

Deliberate simplification (see ``docs/SEARCH_LIMITATIONS.md``): the
designations' inherent triggered abilities and the dungeon room
abilities resolve immediately instead of using the stack.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:  # pragma: no cover
    from mtg_bot.game import GameObject, GameState


# ---------------------------------------------------------------- monarch


def become_monarch(state: "GameState", player_id: int) -> None:
    """CR 724.1: ``player_id`` becomes the monarch; nobody else is."""
    was_monarch = state.player_by_id(player_id).is_monarch
    for p in state.players:
        p.is_monarch = p.id == player_id
    state.log.append(f"P{player_id} becomes the monarch")
    if not was_monarch:
        # "... until an opponent becomes the monarch" (Palace Jailer).
        from mtg_bot.effects.generic.cube_creatures_wg import (
            release_exiled_until_opponent_monarch,
        )

        release_exiled_until_opponent_monarch(state, player_id)


def monarch_id(state: "GameState") -> int | None:
    return next((p.id for p in state.players if p.is_monarch), None)


# ---------------------------------------------------------------- goad


def goad(state: "GameState", creature: "GameObject", goader_id: int) -> None:
    """CR 701.38a: until ``goader_id``'s next turn the creature attacks
    each combat if able (and a player other than the goader if able —
    with two players that is moot). Cleared at the goader's untap."""
    creature.goaded_by = goader_id
    state.log.append(f"{creature.printing.name} is goaded by P{goader_id}")


def clear_goad_for(state: "GameState", player_id: int) -> None:
    for o in state.battlefield:
        if o.goaded_by == player_id:
            o.goaded_by = None


def forced_attackers(state: "GameState", player_id: int) -> list[int]:
    """Ids of ``player_id``'s creatures that must attack if able
    (goaded) among the currently eligible attackers."""
    from mtg_bot.combat import eligible_attackers

    eligible = eligible_attackers(state, player_id)
    forced = [o.id for o in eligible if o.goaded_by is not None]
    # "... attacks each combat if able." statics (cube creatures bucket).
    from mtg_bot.effects.generic.cube_creatures_rmc import must_attack_ids

    for oid in must_attack_ids(state, player_id, eligible):
        if oid not in forced:
            forced.append(oid)
    return forced


# ---------------------------------------------------------------- undercity


def _choose_target(state, player_id, legal):
    if not legal:
        return None
    agent = state.player_by_id(player_id).agent
    pick = agent.choose_target(state, player_id, legal) if agent else None
    return pick if pick in legal else legal[0]


def _room_secret_entrance(state: "GameState", pid: int) -> None:
    from mtg_bot.effects.generic.search import SearchLibraryForCard

    SearchLibraryForCard(filter_name="basic_land").resolve(state, pid, ())


def _room_forge(state: "GameState", pid: int) -> None:
    from mtg_bot.game import add_plus_one_counters, is_creature_now
    from mtg_bot.keyword_rules import filter_targetable

    legal = filter_targetable(
        state,
        [("creature", o.id) for o in state.battlefield if is_creature_now(o)],
        None, pid,
    )
    pick = _choose_target(state, pid, legal)
    if pick is not None:
        obj = next(o for o in state.battlefield if o.id == pick[1])
        add_plus_one_counters(state, obj, 2)


def _room_lost_well(state: "GameState", pid: int) -> None:
    from mtg_bot.effects.generic.library_lookat import Scry

    Scry(amount=2).resolve(state, pid, ())


def _room_trap(state: "GameState", pid: int) -> None:
    legal = [("player", p.id) for p in state.players if not p.has_lost]
    # A sensible default: the agent picks, falling back to an opponent.
    opp = [t for t in legal if t[1] != pid]
    pick = _choose_target(state, pid, opp or legal)
    if pick is not None:
        victim = state.player_by_id(pick[1])
        victim.life -= 5
        state.log.append(f"P{victim.id} loses 5 life (Trap!)")


def _room_arena(state: "GameState", pid: int) -> None:
    from mtg_bot.game import is_creature_now
    from mtg_bot.keyword_rules import filter_targetable

    legal = filter_targetable(
        state,
        [("creature", o.id) for o in state.battlefield if is_creature_now(o)],
        None, pid,
    )
    pick = _choose_target(state, pid, legal)
    if pick is not None:
        goad(state, next(o for o in state.battlefield if o.id == pick[1]), pid)


def _room_stash(state: "GameState", pid: int) -> None:
    from mtg_bot.cards.tokens import TOKEN_PRINTINGS
    from mtg_bot.effects.generic.tokens import CreateToken

    CreateToken(token_printing=TOKEN_PRINTINGS["Treasure"]).resolve(state, pid, ())


def _room_archives(state: "GameState", pid: int) -> None:
    from mtg_bot.turn import draw_n_cards

    draw_n_cards(state, pid, 1)


def _skeleton_token():
    from mtg_bot.cards.base import make_token_creature

    return make_token_creature(
        "Skeleton", 4, 1, subtypes=("Skeleton",), keywords=frozenset({"menace"}),
    )


def _room_catacombs(state: "GameState", pid: int) -> None:
    from mtg_bot.effects.generic.tokens import CreateToken

    CreateToken(token_printing=_skeleton_token()).resolve(state, pid, ())


def _room_throne(state: "GameState", pid: int) -> None:
    """Reveal the top ten cards of your library. Put a creature card
    from among them onto the battlefield with three +1/+1 counters on
    it. It gains hexproof until your next turn. Then shuffle."""
    from mtg_bot.actions import put_into_battlefield
    from mtg_bot.game import add_plus_one_counters, shuffle_library

    p = state.player_by_id(pid)
    revealed = list(p.library[:10])
    creatures = [c for c in revealed if c.printing.is_creature]
    if creatures:
        chosen_id = creatures[0].id
        if p.agent is not None:
            pick = p.agent.choose_card_from_library(
                state, pid, [c.id for c in creatures],
            )
            if pick is not None:
                chosen_id = pick
        card = next((c for c in creatures if c.id == chosen_id), creatures[0])
        p.library.remove(card)
        put_into_battlefield(state, card, pid)
        if card in state.battlefield:
            add_plus_one_counters(state, card, 3)
            state.add_continuous_effect(
                source_id=card.id, layer=6, kind="grant_keyword",
                target_id=card.id, params=("hexproof",),
                description="Throne of the Dead Three: hexproof",
                expires_at="controller_untap", expires_at_player_id=pid,
            )
    shuffle_library(state, pid)


@dataclass(frozen=True)
class Room:
    name: str
    effect: Callable[["GameState", int], None]
    exits: tuple[str, ...]


# CR 309 / the Undercity dungeon card (CLB).
UNDERCITY: dict[str, Room] = {
    "Secret Entrance": Room("Secret Entrance", _room_secret_entrance,
                            ("Forge", "Lost Well")),
    "Forge": Room("Forge", _room_forge, ("Trap!", "Arena")),
    "Lost Well": Room("Lost Well", _room_lost_well, ("Arena", "Stash")),
    "Trap!": Room("Trap!", _room_trap, ("Archives",)),
    "Arena": Room("Arena", _room_arena, ("Archives", "Catacombs")),
    "Stash": Room("Stash", _room_stash, ("Catacombs",)),
    "Archives": Room("Archives", _room_archives, ("Throne of the Dead Three",)),
    "Catacombs": Room("Catacombs", _room_catacombs, ("Throne of the Dead Three",)),
    "Throne of the Dead Three": Room(
        "Throne of the Dead Three", _room_throne, (),
    ),
}
UNDERCITY_FIRST_ROOM = "Secret Entrance"


def venture_into_undercity(state: "GameState", player_id: int) -> None:
    """CR 309.5 / 725.2: move the venture marker to the next room (the
    first room if not in the dungeon, a chosen exit otherwise, or a new
    dungeon after completing the last room) and resolve that room."""
    p = state.player_by_id(player_id)
    current = p.dungeon_room
    if current is None:
        nxt = UNDERCITY_FIRST_ROOM
    else:
        exits = UNDERCITY[current].exits
        if len(exits) == 1:
            nxt = exits[0]
        else:
            idx = 0
            if p.agent is not None:
                idx = p.agent.choose_mode(state, player_id, list(exits))
            nxt = exits[idx] if 0 <= idx < len(exits) else exits[0]
    p.dungeon_room = nxt
    state.log.append(f"P{player_id} ventures into {nxt}")
    UNDERCITY[nxt].effect(state, player_id)
    if not UNDERCITY[nxt].exits:
        # CR 309.7: the dungeon is completed once its last room's
        # ability has resolved; the next venture starts a new one.
        p.dungeon_room = None
        p.dungeons_completed += 1
        state.log.append(f"P{player_id} completes the Undercity")


def take_initiative(state: "GameState", player_id: int) -> None:
    """CR 725.2: take the initiative, then venture into Undercity."""
    for p in state.players:
        p.has_initiative = p.id == player_id
    state.log.append(f"P{player_id} takes the initiative")
    venture_into_undercity(state, player_id)


def initiative_id(state: "GameState") -> int | None:
    return next((p.id for p in state.players if p.has_initiative), None)


# ---------------------------------------------------------------- turn hooks


def on_beginning_of_upkeep(state: "GameState") -> None:
    ap = state.active_player()
    if ap.has_initiative:
        venture_into_undercity(state, ap.id)


def on_beginning_of_end_step(state: "GameState") -> None:
    from mtg_bot.turn import draw_n_cards

    ap = state.active_player()
    if ap.is_monarch:
        draw_n_cards(state, ap.id, 1)
        state.log.append(f"P{ap.id} draws a card (the monarch)")


def on_combat_damage_to_players(
    state: "GameState", hits: list[tuple[int, int, int]],
) -> None:
    """``hits`` are ``(source_id, player_id, amount)`` combat-damage
    events. CR 724.2 / 725.2: the controller of creatures that dealt
    combat damage to the monarch / the player with the initiative
    takes that designation."""
    for source_id, victim_id, amount in hits:
        if amount <= 0:
            continue
        source = next((o for o in state.battlefield if o.id == source_id), None)
        if source is None:
            continue
        taker = source.controller_id
        if taker == victim_id:
            continue
        victim = state.player_by_id(victim_id)
        if victim.is_monarch:
            become_monarch(state, taker)
        if victim.has_initiative:
            take_initiative(state, taker)
