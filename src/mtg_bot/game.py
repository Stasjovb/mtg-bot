"""Game state: zones, game objects, players, stack, and GameState."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Optional

from mtg_bot.cards import CardPrinting

if TYPE_CHECKING:
    from mtg_bot.agents import Agent
    from mtg_bot.effects import TriggeredAbility
    from mtg_bot.turn import Step


class Zone(Enum):
    LIBRARY = "library"
    HAND = "hand"
    BATTLEFIELD = "battlefield"
    GRAVEYARD = "graveyard"
    EXILE = "exile"
    STACK = "stack"


@dataclass
class GameObject:
    """An instance of a card in the game. Uniquely identified by ``id``."""

    id: int
    printing: CardPrinting
    owner_id: int
    controller_id: int
    zone: Zone
    tapped: bool = False
    damage: int = 0
    summoning_sick: bool = True
    attacking: bool = False
    blocking: Optional[int] = None
    blocked_by: list[int] = field(default_factory=list)
    # Marked lethal by a deathtouch source this turn — destroyed by SBAs
    # regardless of damage vs toughness. Cleared when damage is cleared.
    marked_lethal: bool = False
    # +1/+1 counters raise effective power and toughness by equal amounts.
    # Persist across turns (never wear off on their own).
    plus_one_counters: int = 0


def effective_power(obj: GameObject) -> int:
    """Power including +1/+1 counters. Falls back to 0 for non-creatures."""
    base = obj.printing.power or 0
    return base + obj.plus_one_counters


def effective_toughness(obj: GameObject) -> int:
    """Toughness including +1/+1 counters. Falls back to 0 for non-creatures."""
    base = obj.printing.toughness or 0
    return base + obj.plus_one_counters


@dataclass
class StackItem:
    """A spell or triggered ability on the stack.

    When ``ability`` is None the stack item represents a spell being cast;
    resolving it moves ``source`` to the battlefield. When ``ability`` is set,
    the item represents a triggered ability; resolving it runs the effect.

    ``targets`` holds (kind, id) pairs chosen when the ability went on the
    stack — empty for spells and for untargeted abilities.
    """

    source: GameObject
    controller_id: int
    ability: Optional["TriggeredAbility"] = None
    targets: tuple[tuple[str, int], ...] = ()


@dataclass
class Player:
    id: int
    life: int = 20
    library: list[GameObject] = field(default_factory=list)
    hand: list[GameObject] = field(default_factory=list)
    graveyard: list[GameObject] = field(default_factory=list)
    exile: list[GameObject] = field(default_factory=list)
    lands_played_this_turn: int = 0
    has_lost: bool = False
    lost_reason: str = ""
    agent: Optional["Agent"] = None


@dataclass
class GameState:
    players: list[Player] = field(default_factory=list)
    battlefield: list[GameObject] = field(default_factory=list)
    stack: list[StackItem] = field(default_factory=list)
    active_player_idx: int = 0
    priority_player_idx: int = 0
    turn_number: int = 1
    step: Optional["Step"] = None
    next_object_id: int = 0
    log: list[str] = field(default_factory=list)
    winner_id: Optional[int] = None
    is_draw: bool = False

    def active_player(self) -> Player:
        return self.players[self.active_player_idx]

    def player_by_id(self, player_id: int) -> Player:
        for p in self.players:
            if p.id == player_id:
                return p
        raise KeyError(f"no player with id={player_id}")

    def index_of(self, player_id: int) -> int:
        for i, p in enumerate(self.players):
            if p.id == player_id:
                return i
        raise KeyError(f"no player with id={player_id}")

    def new_object(
        self, printing: CardPrinting, owner_id: int, zone: Zone
    ) -> GameObject:
        obj = GameObject(
            id=self.next_object_id,
            printing=printing,
            owner_id=owner_id,
            controller_id=owner_id,
            zone=zone,
        )
        self.next_object_id += 1
        return obj

    def is_over(self) -> bool:
        return self.winner_id is not None or self.is_draw

    def creatures_controlled_by(self, player_id: int) -> list[GameObject]:
        return [
            o for o in self.battlefield
            if o.controller_id == player_id and o.printing.is_creature
        ]

    def lands_controlled_by(self, player_id: int) -> list[GameObject]:
        return [
            o for o in self.battlefield
            if o.controller_id == player_id and o.printing.is_land
        ]
