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
    # Warp-cast state. ``cast_via_warp`` is set True when this card was cast
    # from hand for its warp cost — it triggers an exile at the next end step.
    # ``warped`` is set True when this card sits in exile having been exiled
    # via that trigger — it can be cast from exile at its normal cost.
    cast_via_warp: bool = False
    warped: bool = False
    # EoE Spacecraft charge counters. A Spacecraft at ``station_threshold`` or
    # more is a creature (see ``is_creature_now``).
    charge_counters: int = 0
    # Stun counters: a permanent with stun counters doesn't untap during
    # its controller's untap step — instead one stun counter is removed.
    stun_counters: int = 0
    # Until-end-of-turn bonuses applied by pump effects (e.g. "+3/+0 until
    # end of turn"). Cleared on the cleanup step. Stacked additively when
    # multiple pumps hit the same object.
    temp_power_bonus: int = 0
    temp_toughness_bonus: int = 0
    temp_keywords: frozenset[str] = field(default_factory=frozenset)
    # Equipment attachment: if this object is Equipment, ``attached_to``
    # is the id of the creature it's attached to (or None if unattached).
    # Plays no role if the object isn't Equipment.
    attached_to: Optional[int] = None
    # Oblivion-Ring-style "until X leaves the battlefield" tracking: when
    # a card is exiled by a specific source, its ``exiled_by_source`` is
    # set to that source's id. When the source leaves the battlefield,
    # move_off_battlefield returns all cards tagged with its id from
    # exile back to their owner's battlefield.
    exiled_by_source: Optional[int] = None
    # "Gain control of ~ until end of turn" tracking: when this object
    # is controlled UEOT, ``temp_original_controller_id`` stores the
    # controller it came from. run_cleanup_step swaps ``controller_id``
    # back and clears this field. None = no temporary-control effect.
    temp_original_controller_id: Optional[int] = None


def is_void_active(state: GameState) -> bool:
    """EoE Void condition: a nonland permanent left the battlefield this turn
    OR a spell was warped this turn."""
    return (
        state.permanent_left_battlefield_this_turn
        or state.spell_warped_this_turn
    )


def is_stationed(obj: GameObject) -> bool:
    """True when this Spacecraft has enough charge counters to be a creature."""
    threshold = obj.printing.station_threshold
    return threshold is not None and obj.charge_counters >= threshold


def is_creature_now(obj: GameObject) -> bool:
    """Whether ``obj`` currently counts as a creature on the battlefield.

    True for printed creatures AND for Spacecraft whose charge-counter
    threshold has been crossed (they're artifact creatures while stationed).
    """
    return obj.printing.is_creature or is_stationed(obj)


def _static_bonuses(
    state: GameState, obj: GameObject
) -> tuple[int, int, frozenset[str]]:
    """Walk the battlefield for static abilities that buff ``obj``.

    Returns (power_bonus, toughness_bonus, granted_keywords). Used by the
    effective_* helpers below.
    Also folds in bonuses from any Equipment attached to ``obj``.
    """
    power_bonus = 0
    toughness_bonus = 0
    granted: set[str] = set()
    for source in state.battlefield:
        for ability in source.printing.static_abilities:
            if ability.applies_to(source, obj, state):
                power_bonus += ability.power_bonus
                toughness_bonus += ability.toughness_bonus
                granted |= ability.granted_keywords
    # Equipment attached to obj contributes its equipment_bonuses.
    for source in state.battlefield:
        if source.attached_to != obj.id:
            continue
        eb = source.printing.equipment_bonuses
        if eb is None:
            continue
        ep, et, ek = eb
        power_bonus += ep
        toughness_bonus += et
        granted |= ek
    return power_bonus, toughness_bonus, frozenset(granted)


def effective_keywords(state: GameState, obj: GameObject) -> frozenset[str]:
    """Keywords in effect right now — printing + stationed_keywords +
    keywords granted by static abilities on other permanents + UEOT
    keyword grants from pump effects."""
    kws = obj.printing.keywords
    if is_stationed(obj):
        kws = kws | obj.printing.stationed_keywords
    _, _, granted = _static_bonuses(state, obj)
    return kws | granted | obj.temp_keywords


def _dynamic_base_pt(
    state: GameState, obj: GameObject
) -> tuple[int, int] | None:
    """Return (base_power, base_toughness) for dynamic-P/T creatures,
    or None if this creature has no dynamic formula and should use
    its printed P/T.
    """
    formula = obj.printing.dynamic_pt_formula
    if formula is None:
        return None
    if formula == "cosmogoyf":
        # Cards owned in exile (by the creature's controller).
        controller = state.player_by_id(obj.controller_id)
        n = len(controller.exile)
        return n, n + 1
    return None  # pragma: no cover - defensive fallback


def effective_power(state: GameState, obj: GameObject) -> int:
    """Power including +1/+1 counters, static bonuses, and UEOT pumps.
    Dynamic P/T creatures compute their base via ``dynamic_pt_formula``
    instead of reading ``printing.power``.
    """
    dynamic = _dynamic_base_pt(state, obj)
    base = dynamic[0] if dynamic is not None else (obj.printing.power or 0)
    power_bonus, _, _ = _static_bonuses(state, obj)
    return (
        base + obj.plus_one_counters + power_bonus + obj.temp_power_bonus
    )


def effective_toughness(state: GameState, obj: GameObject) -> int:
    """Toughness including +1/+1 counters, static bonuses, and UEOT pumps.
    Dynamic P/T creatures compute their base via ``dynamic_pt_formula``
    instead of reading ``printing.toughness``.
    """
    dynamic = _dynamic_base_pt(state, obj)
    base = dynamic[1] if dynamic is not None else (obj.printing.toughness or 0)
    _, toughness_bonus, _ = _static_bonuses(state, obj)
    return (
        base + obj.plus_one_counters + toughness_bonus + obj.temp_toughness_bonus
    )


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
    # Either a TriggeredAbility or an ActivatedAbility — both have an
    # ``.effect`` attribute and resolve the same way.
    ability: "object | None" = None
    targets: tuple[tuple[str, int], ...] = ()
    # True when the spell was countered at cast time (currently by unpaid
    # Ward). A countered spell resolves as a no-op, with the card going
    # to its owner's graveyard (for instants/sorceries) or vanishing
    # (for permanents) without firing any effects/ETBs.
    countered: bool = False
    # The value chosen for {X} in this spell's cost (0 for non-X spells).
    # Set by _cast_spell via agent.choose_x; exposed to the resolving
    # effect via state.resolving_x_value.
    x_value: int = 0


@dataclass
class Player:
    id: int
    life: int = 20
    # Starting life total — used by effects that reference it directly
    # (e.g. "your life total becomes half your starting life total").
    # Defaults to 20 (MTG standard); adjust for alternate formats.
    starting_life: int = 20
    # Poison counters (MTG rule 704.5c). A player with 10+ poison
    # counters loses the game — enforced via state-based actions.
    poison_counters: int = 0
    library: list[GameObject] = field(default_factory=list)
    hand: list[GameObject] = field(default_factory=list)
    graveyard: list[GameObject] = field(default_factory=list)
    exile: list[GameObject] = field(default_factory=list)
    lands_played_this_turn: int = 0
    # Number of spells this player has cast in the current turn. Reset at
    # cleanup. Used by "whenever you cast your Nth spell each turn" triggers.
    spells_cast_this_turn: int = 0
    # True if this player has declared at least one Spacecraft as an
    # attacker this turn. Reset at cleanup. Drives the
    # "attacked_with_spacecraft_this_turn" cost-reduction condition.
    attacked_with_spacecraft_this_turn: bool = False
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
    # EoE "Void" turn-state flags. Both are reset on cleanup (end of turn).
    # ``permanent_left_battlefield_this_turn`` is set whenever any nonland
    # permanent leaves the battlefield (destroy, exile, bounce, cease-to-
    # exist, warp-exile). ``spell_warped_this_turn`` is set when a spell
    # was cast via its warp alt-cost. The ``is_void_active`` helper returns
    # True when either flag is set, which is the Void trigger condition.
    permanent_left_battlefield_this_turn: bool = False
    spell_warped_this_turn: bool = False
    # Tracks (source_id, ability_index) pairs for triggered abilities that
    # have already fired this turn under the ``once_per_turn`` restriction.
    # Reset by run_cleanup_step.
    once_per_turn_fired: set[tuple[int, int]] = field(default_factory=set)
    # Delayed triggered abilities scheduled for a future end step. Each
    # entry is a dict: {"fire_at_turn": int, "controller_id": int,
    # "action": str, "target_id": int}.
    # Actions currently supported: "sacrifice".
    delayed_triggers: list[dict] = field(default_factory=list)
    # Source GameObject of the currently-resolving ability, if any. Set by
    # resolve_top_of_stack during ability resolution so effects like
    # "put a +1/+1 counter on this creature" can reach the source without
    # having to thread it through every resolve() signature.
    resolving_source: Optional[GameObject] = None
    # Value of {X} for the currently-resolving spell or ability. Mirrors
    # StackItem.x_value during resolution so effects can read X without
    # threading it through every resolve() signature. 0 when no X spell
    # is resolving.
    resolving_x_value: int = 0

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
