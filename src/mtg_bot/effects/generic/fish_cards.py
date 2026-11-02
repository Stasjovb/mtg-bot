"""Forgetful Fish cards (pool ``fish``): the effects and conditions the
user's 80-card shared library needs beyond the cube / roto pools.

Text-changing effects (CR 612): a ``"fish_text_change"`` continuous
effect (layer 3) on one object with ``params=(old_word, new_word)``.
It changes the object's rules text and its type line (CR 612.1; the
Mind Bend / Crystal Spray rulings: "Forest can be changed to Island so
it produces blue mana"), never its name (612.2). Abilities that print a basic
land type or a color word read it through :func:`changed_word`, so a
Mind Bend on Dandân (Island -> Mountain) makes it read "can't attack
unless defending player controls a Mountain" / "When you control no
Mountains, sacrifice this creature." Several changes apply in timestamp
order, each to the text as the earlier ones left it.

The effect is keyed to the object's id. An object that changes zones
is a new object (CR 400.7): ``changed_word`` only counts entries whose
target is the same object it was created for (see
:func:`_live_text_changes`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from mtg_bot.effects.base import Effect
from mtg_bot.roto_board_statics import CantAttack

if TYPE_CHECKING:
    from mtg_bot.game import GameObject, GameState

TEXT_CHANGE_KIND = "fish_text_change"
BASIC_LAND_TYPES = ("Plains", "Island", "Swamp", "Mountain", "Forest")
COLOR_WORDS = ("white", "blue", "black", "red", "green")


def _live_text_changes(state: "GameState", obj: "GameObject") -> list:
    return sorted(
        (
            ce for ce in state.continuous_effects
            if ce.kind == TEXT_CHANGE_KIND and ce.target_id == obj.id
        ),
        key=lambda ce: ce.timestamp,
    )


def changed_word(state: "GameState", obj: "GameObject", word: str) -> str:
    """``word`` (a basic land type or a color word printed in ``obj``'s
    rules text) as the text reads now, after text-changing effects."""
    if not state.continuous_effects:
        return word
    for ce in _live_text_changes(state, obj):
        old, new = ce.params
        if word == old:
            word = new
    return word


def controls_land_of_type(state: "GameState", player_id: int, land_type: str) -> bool:
    """Whether ``player_id`` controls a land with subtype ``land_type``
    (after layer-4 type changes such as Vision Charm)."""
    from mtg_bot.game import effective_card_types, effective_subtypes

    return any(
        o.controller_id == player_id
        and "Land" in effective_card_types(state, o)
        and land_type in effective_subtypes(state, o)
        for o in state.battlefield
    )


def _plural(land_type: str) -> str:
    return "Plains" if land_type == "Plains" else land_type + "s"


@dataclass(frozen=True)
class DefendingPlayerControlsNoLandType:
    """The attack condition of "can't attack unless defending player
    controls an <land type>": holds (the creature can't attack) when no
    opponent of the creature's controller controls such a land. The
    land type is the source's text (``changed_word``).

    Two-player shortcut: the defending player is the controller's
    opponent (SEARCH_LIMITATIONS, "Forgetful Fish cards" 1)."""

    land_type: str

    def holds(self, state, source, creature) -> bool:
        word = changed_word(state, source, self.land_type)
        return not any(
            controls_land_of_type(state, p.id, word)
            for p in state.players
            if p.id != creature.controller_id
        )

    def describe(self) -> str:
        article = "an" if self.land_type[0] in "AEIOU" else "a"
        return f"unless defending player controls {article} {self.land_type}"


@dataclass(frozen=True)
class CantAttackUnless(CantAttack):
    """"This creature can't attack unless <condition>." (Dandân)."""

    def describe(self) -> str:
        return f"This creature can't attack {self.condition.describe()}."


@dataclass(frozen=True)
class YouControlNoLandType:
    """State-trigger condition "you control no <land type>s" (CR 603.8;
    "you" = the source's controller, the type is the source's text)."""

    land_type: str

    def holds(self, state, source) -> bool:
        word = changed_word(state, source, self.land_type)
        return not controls_land_of_type(state, source.controller_id, word)

    def describe(self) -> str:
        return f"you control no {_plural(self.land_type)}"


def all_card_names(state: "GameState") -> list[str]:
    """Every card name in the game (each zone, both players), sorted: the
    names offered for "choose a card name" in a Fish game, where the
    shared list is public. Tokens and spell copies aren't cards."""
    names: set[str] = set()

    def add(card) -> None:
        if card.printing.is_token or getattr(card, "is_spell_copy", False):
            return
        names.add(card.printing.name)

    for zone in (*state.distinct_libraries(), *state.distinct_graveyards()):
        for c in zone:
            add(c)
    for p in state.players:
        for c in (*p.hand, *p.exile):
            add(c)
    for o in state.battlefield:
        add(o)
    for item in state.stack:
        if item.ability is None and item.source is not None:
            add(item.source)
    return sorted(names)


def choose_card_name(state: "GameState", controller_id: int) -> "str | None":
    """The controller names a card (``Agent.choose_mode`` over
    :func:`all_card_names`; the first name without an agent)."""
    names = all_card_names(state)
    if not names:
        return None
    idx = 0
    agent = state.player_by_id(controller_id).agent
    if agent is not None and len(names) > 1:
        picked = agent.choose_mode(state, controller_id, names)
        if isinstance(picked, int) and 0 <= picked < len(names):
            idx = picked
    state.log.append(f"P{controller_id} names {names[idx]}")
    return names[idx]


@dataclass(frozen=True)
class NameThenMillDrawOnHit(Effect):
    """"Choose a card name, then target player mills N cards. If a card
    with the chosen name was milled this way, you draw <hit> cards.
    Otherwise, you draw <miss> cards." (Predict.) The name is chosen on
    resolution, before the mill (CR 608.2c, in printed order)."""

    mill: int = 1
    hit: int = 2
    miss: int = 1

    def requires_target(self) -> bool:
        return True

    def legal_targets(self, state, controller_id):
        return [("player", p.id) for p in state.players if not p.has_lost]

    def resolve(self, state, controller_id, targets=()):
        from mtg_bot.game import Zone
        from mtg_bot.turn import draw_n_cards

        if not targets or targets[0][0] != "player":
            return
        target = state.player_by_id(targets[0][1])
        if target.has_lost:
            return
        name = choose_card_name(state, controller_id)
        milled = []
        for _ in range(self.mill):
            if not target.library:
                break
            card = target.library.pop(0)
            card.zone = Zone.GRAVEYARD
            target.graveyard.append(card)
            milled.append(card)
        state.log.append(
            f"P{target.id} mills "
            + (", ".join(c.printing.name for c in milled) or "nothing")
        )
        hit = name is not None and any(c.printing.name == name for c in milled)
        n = draw_n_cards(state, controller_id, self.hit if hit else self.miss)
        state.log.append(f"P{controller_id} draws {n} card(s)")

    def describe(self) -> str:
        return (
            f"choose a card name, then target player mills {self.mill} "
            f"card(s); draw {self.hit} if one has that name, else {self.miss}"
        )


@dataclass(frozen=True)
class ReorderTargetPlayersTopCards(Effect):
    """"Look at the top N cards of target player's library, then put them
    back in any order[. You may have that player shuffle]." (Portent.)
    The controller orders the cards top-down with
    ``choose_card_from_library`` (as ``ReorderTopCards``), then decides
    the shuffle with ``choose_yes_no``. In Fish the target's library is
    the shared one, so either target sets up both players' draws."""

    count: int = 3
    may_shuffle: bool = False

    def requires_target(self) -> bool:
        return True

    def legal_targets(self, state, controller_id):
        return [("player", p.id) for p in state.players if not p.has_lost]

    def resolve(self, state, controller_id, targets=()):
        from mtg_bot.game import Zone, reveal_to, shuffle_library

        if not targets or targets[0][0] != "player":
            return
        target = state.player_by_id(targets[0][1])
        if target.has_lost:
            return
        me = state.player_by_id(controller_id)
        n = min(self.count, len(target.library))
        remaining = [target.library.pop(0) for _ in range(n)]
        ordered: list = []
        while remaining:
            chosen = remaining[0]
            if me.agent is not None and len(remaining) > 1:
                picked = me.agent.choose_card_from_library(
                    state, controller_id, [c.id for c in remaining],
                )
                chosen = next((c for c in remaining if c.id == picked), remaining[0])
            remaining.remove(chosen)
            ordered.append(chosen)
        for c in reversed(ordered):
            c.zone = Zone.LIBRARY
            target.library.insert(0, c)
            reveal_to(c, controller_id)
        state.log.append(f"P{controller_id} reorders the top {n} card(s) of P{target.id}'s library")
        if self.may_shuffle and me.agent is not None and me.agent.choose_yes_no(
            state, controller_id, f"Have P{target.id} shuffle their library?",
        ):
            shuffle_library(state, target.id)
            state.log.append(f"P{target.id} shuffles their library")

    def describe(self) -> str:
        tail = ". You may have that player shuffle" if self.may_shuffle else ""
        return (
            f"look at the top {self.count} cards of target player's library, "
            f"then put them back in any order{tail}"
        )


TAP_WHEN_CONTROL_LOST_KIND = "fish_tap_when_control_lost"


def apply_fish_card_checks(state: "GameState") -> bool:
    """Run wherever state-based actions are checked and after cleanup's
    control refresh. Returns True when a creature was tapped.

    * ``TAP_WHEN_CONTROL_LOST_KIND`` (Ray of Command's "When you lose
      control of the creature, tap it."): once the creature's controller
      is no longer ``params[0]``, tap it and drop the watch; a creature
      that left the battlefield is a new object (CR 400.7), the watch
      just ends. The tap happens at once instead of as a triggered
      ability on the stack (SEARCH_LIMITATIONS, "Forgetful Fish cards" 3).
    * Text changes (``TEXT_CHANGE_KIND``) on an object that is neither on
      the battlefield nor a spell on the stack end (CR 400.7).
    """
    if not state.continuous_effects:
        return False
    on_battlefield = {o.id: o for o in state.battlefield}
    on_stack = {
        item.source.id for item in state.stack
        if item.ability is None and item.source is not None
    }
    dropped = []
    tapped = False
    for ce in state.continuous_effects:
        if ce.kind == TAP_WHEN_CONTROL_LOST_KIND:
            obj = on_battlefield.get(ce.target_id)
            if obj is None:
                dropped.append(ce)
            elif obj.controller_id != ce.params[0]:
                dropped.append(ce)
                if not obj.tapped:
                    obj.tapped = True
                    tapped = True
                    state.log.append(
                        f"P{ce.params[0]} lost control of {obj.printing.name}: it taps"
                    )
        elif ce.kind in (TEXT_CHANGE_KIND, "replace_basic_land_type"):
            if ce.target_id not in on_battlefield and ce.target_id not in on_stack:
                dropped.append(ce)
    if dropped:
        gone = {id(ce) for ce in dropped}
        state.continuous_effects = [
            ce for ce in state.continuous_effects if id(ce) not in gone
        ]
        state._invalidate_layered_cache()
    return tapped


@dataclass(frozen=True)
class UntapGainControlHasteTapWhenLost(Effect):
    """"Untap target creature an opponent controls and gain control of it
    until end of turn. That creature gains haste until end of turn. When
    you lose control of the creature, tap it." (Ray of Command.) Control
    and haste as the Threaten shape (``GainControlUntapHasteUEOT``); the
    last sentence is a ``TAP_WHEN_CONTROL_LOST_KIND`` watch (see
    :func:`apply_fish_card_checks`)."""

    def requires_target(self) -> bool:
        return True

    def legal_targets(self, state, controller_id):
        from mtg_bot.game import is_creature_now

        return [
            ("creature", o.id) for o in state.battlefield
            if is_creature_now(o) and o.controller_id != controller_id
        ]

    def resolve(self, state, controller_id, targets=()):
        from mtg_bot.game import is_creature_now

        if not targets:
            return
        obj = next((o for o in state.battlefield if o.id == targets[0][1]), None)
        if obj is None or not is_creature_now(obj) or obj.controller_id == controller_id:
            state.log.append("Ray of Command: its target is gone or illegal")
            return
        src = state.resolving_spell or state.resolving_source
        source_id = src.id if src is not None else obj.id
        obj.tapped = False
        state.grant_control_change_ueot(
            source_id=source_id, target_id=obj.id, new_controller_id=controller_id,
            description=f"P{controller_id} controls {obj.printing.name} until end of turn",
        )
        state.add_continuous_effect(
            source_id=source_id, layer=6, kind="grant_keyword", target_id=obj.id,
            params=("haste",), expires_at="cleanup",
            description=f"{obj.printing.name} gains haste until end of turn",
        )
        state.add_continuous_effect(
            source_id=source_id, layer=0, kind=TAP_WHEN_CONTROL_LOST_KIND,
            target_id=obj.id, params=(controller_id,),
            description=f"tap {obj.printing.name} when P{controller_id} loses control of it",
        )
        state.log.append(
            f"P{controller_id} untaps and gains control of {obj.printing.name} "
            "until end of turn; it gains haste"
        )

    def describe(self) -> str:
        return (
            "untap target creature an opponent controls and gain control of it "
            "until end of turn; it gains haste until end of turn; when you lose "
            "control of it, tap it"
        )


@dataclass(frozen=True)
class BounceTargetThenTokenCopy(Effect):
    """"Return target creature to its owner's hand. You create a token
    that's a copy of that creature." (Supplant Form.) The token copies
    the creature's copiable values as it last existed on the battlefield
    (CR 707.2, 608.2h): its printing, including a layer-1 copy effect,
    but not text changes, type changes or ability loss from other
    effects. An illegal target on resolution means no token either."""

    def requires_target(self) -> bool:
        return True

    def legal_targets(self, state, controller_id):
        from mtg_bot.game import is_creature_now

        return [("creature", o.id) for o in state.battlefield if is_creature_now(o)]

    def resolve(self, state, controller_id, targets=()):
        import dataclasses

        from mtg_bot.effects.generic.tokens import CreateToken
        from mtg_bot.game import is_creature_now
        from mtg_bot.turn import move_off_battlefield

        if not targets:
            return
        obj = next((o for o in state.battlefield if o.id == targets[0][1]), None)
        if obj is None or not is_creature_now(obj):
            state.log.append("Supplant Form: its target is gone or illegal")
            return
        base = obj.printing
        move_off_battlefield(state, obj, destination="hand")
        supertypes = tuple(base.supertypes) + (
            ("Token",) if "Token" not in base.supertypes else ()
        )
        CreateToken(
            token_printing=dataclasses.replace(base, supertypes=supertypes),
        ).resolve(state, controller_id, ())

    def describe(self) -> str:
        return (
            "return target creature to its owner's hand; you create a token "
            "that's a copy of that creature"
        )


@dataclass(frozen=True)
class TuckOpponentsPermanentTheyMayPutOne(Effect):
    """"Put target permanent an opponent controls on top of its owner's
    library. That opponent may put <types> card from their hand onto the
    battlefield." (Metamorphose: artifact, creature, enchantment or land.)
    "That opponent" is the permanent's controller as it last existed on
    the battlefield; they pick with ``choose_card_from_hand`` (``None``
    declines). A land put this way isn't a land play (CR 305.4)."""

    card_types: tuple[str, ...] = ("Artifact", "Creature", "Enchantment", "Land")

    def requires_target(self) -> bool:
        return True

    def legal_targets(self, state, controller_id):
        return [
            ("permanent", o.id) for o in state.battlefield
            if o.controller_id != controller_id
        ]

    def resolve(self, state, controller_id, targets=()):
        from mtg_bot.actions import put_into_battlefield
        from mtg_bot.turn import move_off_battlefield

        if not targets:
            return
        obj = next((o for o in state.battlefield if o.id == targets[0][1]), None)
        if obj is None or obj.controller_id == controller_id:
            state.log.append("Metamorphose: its target is gone or illegal")
            return
        opponent = state.player_by_id(obj.controller_id)
        move_off_battlefield(state, obj, destination="library", library_index=0)
        state.log.append(f"{obj.printing.name} is put on top of its owner's library")
        options = [
            c for c in opponent.hand
            if set(c.printing.card_types) & set(self.card_types)
        ]
        if not options or opponent.agent is None:
            return
        picked = opponent.agent.choose_card_from_hand(
            state, opponent.id, [c.id for c in options],
        )
        card = next((c for c in options if c.id == picked), None)
        if card is None:
            state.log.append(f"P{opponent.id} puts nothing onto the battlefield")
            return
        opponent.hand.remove(card)
        put_into_battlefield(state, card, opponent.id)
        state.log.append(f"P{opponent.id} puts {card.printing.name} onto the battlefield")

    def describe(self) -> str:
        kinds = ", ".join(t.lower() for t in self.card_types)
        return (
            "put target permanent an opponent controls on top of its owner's "
            f"library; that opponent may put a card ({kinds}) from their hand "
            "onto the battlefield"
        )


@dataclass(frozen=True)
class TargetYouControlBecomesUEOT(Effect):
    """"Until end of turn, target creature you control becomes a <color>
    <Subtypes> with base power and toughness P/T, loses all abilities, and
    gains <keyword>." (Dance of the Skywise.) The entries of Oko's
    ``TargetBecomesCreatureIndefinitely`` with ``expires_at="cleanup"``:
    layer 4 ``set_creature_subtypes``, layer 5 ``set_colors``, layer 6
    ``lose_all_abilities`` then ``grant_keyword`` (later timestamp, so the
    keyword stays), layer 7b ``set_base_pt``. Self-sourced, so they end at
    cleanup or when the creature leaves."""

    colors: frozenset = frozenset()
    creature_subtypes: tuple = ()
    base_pt: tuple = (0, 0)
    lose_all_abilities: bool = True
    keywords: tuple = ()

    def requires_target(self) -> bool:
        return True

    def legal_targets(self, state, controller_id):
        from mtg_bot.game import is_creature_now

        return [
            ("creature", o.id) for o in state.battlefield
            if is_creature_now(o) and o.controller_id == controller_id
        ]

    def resolve(self, state, controller_id, targets=()):
        from mtg_bot.game import is_creature_now

        if not targets:
            return
        obj = next((o for o in state.battlefield if o.id == targets[0][1]), None)
        if obj is None or not is_creature_now(obj) or obj.controller_id != controller_id:
            state.log.append("Dance of the Skywise: its target is gone or illegal")
            return
        name = obj.printing.name

        def add(layer, kind, params=(), sublayer=0, what=""):
            state.add_continuous_effect(
                source_id=obj.id, layer=layer, sublayer=sublayer, kind=kind,
                target_id=obj.id, params=params, expires_at="cleanup",
                description=f"{name} {what} until end of turn",
            )

        add(4, "set_creature_subtypes", tuple(self.creature_subtypes),
            what=f"is a {' '.join(self.creature_subtypes)}")
        colors = self.colors
        spell = state.resolving_spell
        if spell is not None:
            # A text change on the spell (Crystal Spray: "blue" -> "red").
            colors = frozenset(
                _COLOR_LETTER[changed_word(state, spell, _COLOR_WORD[c])] for c in colors
            )
        if colors:
            add(5, "set_colors", (frozenset(colors),),
                what=f"is {'/'.join(sorted(colors))}")
        if self.lose_all_abilities:
            add(6, "lose_all_abilities", what="loses all abilities")
        for kw in self.keywords:
            add(6, "grant_keyword", (kw,), what=f"gains {kw}")
        p, t = self.base_pt
        add(7, "set_base_pt", (p, t), sublayer=1, what=f"has base {p}/{t}")
        state.log.append(
            f"{name} becomes a {' '.join(self.creature_subtypes)} {p}/{t} "
            f"until end of turn"
        )

    def describe(self) -> str:
        p, t = self.base_pt
        return (
            f"until end of turn, target creature you control becomes a "
            f"{' '.join(self.creature_subtypes)} with base power and toughness "
            f"{p}/{t}"
            + (", loses all abilities" if self.lose_all_abilities else "")
            + (f", and gains {', '.join(self.keywords)}" if self.keywords else "")
        )


_COLOR_WORD = dict(zip("WUBRG", COLOR_WORDS))
_COLOR_LETTER = {w: c for c, w in _COLOR_WORD.items()}


def printed_text_words(printing) -> set[str]:
    """The basic land types and color words printed in ``printing``'s
    rules text that the engine reads through :func:`changed_word`:
    Dandân's two land-type abilities and Dance of the Skywise's color.
    Other words (an Islandcycling cost, a reminder text) aren't modeled
    (SEARCH_LIMITATIONS, "Forgetful Fish cards" 4)."""
    words: set[str] = set()
    for rule in printing.board_rules:
        for part in (rule, getattr(rule, "condition", None)):
            land_type = getattr(part, "land_type", None)
            if land_type:
                words.add(land_type)
    colors = getattr(printing.spell_effect, "colors", None)
    if isinstance(colors, frozenset):
        words |= {_COLOR_WORD[c] for c in colors if c in _COLOR_WORD}
    return words


def _pick(state, controller_id: int, options: list[str]) -> str:
    agent = state.player_by_id(controller_id).agent
    idx = 0
    if agent is not None and len(options) > 1:
        picked = agent.choose_mode(state, controller_id, options)
        if isinstance(picked, int) and 0 <= picked < len(options):
            idx = picked
    return options[idx]


@dataclass(frozen=True)
class ChangeTextOfTarget(Effect):
    """"Change the text of target [spell or ]permanent by replacing all
    instances of one color word with another or one basic land type with
    another[ until end of turn]." (Mind Bend: permanents, indefinitely;
    Crystal Spray: a spell or a permanent, until end of turn.) CR 612.1:
    the rules text and the type line (an Island can become a Mountain:
    ``game.effective_subtypes`` reads these entries in layer 3), never a
    name (612.2). The controller picks
    "<old> -> <new>" (``choose_mode``) among the words the target's text
    has now; a target with no such word is changed in no way. A change
    to a spell carries over to the permanent it becomes (CR 400.7a)."""

    spells: bool = False
    until_end_of_turn: bool = False

    def requires_target(self) -> bool:
        return True

    def legal_targets(self, state, controller_id):
        out: list[Target] = [("permanent", o.id) for o in state.battlefield]
        if self.spells:
            out += [
                ("stack", i) for i, item in enumerate(state.stack)
                if item.ability is None and item.source is not None
            ]
        return out

    def _target_object(self, state, target):
        kind, tid = target
        if kind == "stack":
            if self.spells and 0 <= tid < len(state.stack):
                item = state.stack[tid]
                if item.ability is None:
                    return item.source
            return None
        return next((o for o in state.battlefield if o.id == tid), None)

    def resolve(self, state, controller_id, targets=()):
        if not targets:
            return
        obj = self._target_object(state, targets[0])
        if obj is None:
            state.log.append("text change: its target is gone")
            return
        # Rules-text words plus the type line's basic land types (CR 612.1:
        # Mind Bend on an Island can make it a Mountain).
        printed = printed_text_words(obj.printing) | {
            s for s in obj.printing.subtypes if s in BASIC_LAND_TYPES
        }
        words = sorted({changed_word(state, obj, w) for w in printed})
        options = []
        for old in words:
            pool = COLOR_WORDS if old in COLOR_WORDS else BASIC_LAND_TYPES
            options += [f"{old} -> {new}" for new in pool if new != old]
        if not options:
            state.log.append(f"{obj.printing.name}'s text has no word to change")
            return
        old, new = _pick(state, controller_id, options).split(" -> ")
        state.add_continuous_effect(
            source_id=obj.id, layer=3, kind=TEXT_CHANGE_KIND, target_id=obj.id,
            params=(old, new),
            expires_at="cleanup" if self.until_end_of_turn else None,
            description=f"{obj.printing.name}'s text: {old} -> {new}",
        )
        state.log.append(f"{obj.printing.name}'s text: {old} -> {new}")

    def describe(self) -> str:
        what = "spell or permanent" if self.spells else "permanent"
        when = " until end of turn" if self.until_end_of_turn else ""
        return (
            f"change the text of target {what} by replacing all instances of "
            f"one color word with another or one basic land type with another{when}"
        )


@dataclass(frozen=True)
class LandsOfChosenTypeBecomeBasicTypeUEOT(Effect):
    """"Choose a land type and a basic land type. Each land of the first
    chosen type becomes the second chosen type until end of turn."
    (Vision Charm.) A layer-4 ``set_basic_land_subtype`` on each land that
    has the first type as the effect resolves (CR 611.2c: the set is
    locked in); CR 305.7: those lands lose their old land types and
    rules-text abilities and tap for the new type's mana. Options are
    "<first> -> <second>" over the land types on the battlefield and the
    basic land types (``choose_mode``)."""

    def resolve(self, state, controller_id, targets=()):
        from mtg_bot.game import effective_card_types, effective_subtypes

        lands = [o for o in state.battlefield if "Land" in effective_card_types(state, o)]
        present = {s for o in lands for s in effective_subtypes(state, o)}
        firsts = sorted(present | set(BASIC_LAND_TYPES))
        options = [f"{a} -> {b}" for a in firsts for b in BASIC_LAND_TYPES if a != b]
        first, second = _pick(state, controller_id, options).split(" -> ")
        changed = [o for o in lands if first in effective_subtypes(state, o)]
        for o in changed:
            state.add_continuous_effect(
                source_id=o.id, layer=4, kind="set_basic_land_subtype",
                target_id=o.id, params=(second,), expires_at="cleanup",
                description=f"{o.printing.name} is a {second} until end of turn",
            )
        state.log.append(
            f"Each {first} becomes a {second} until end of turn ({len(changed)} land(s))"
        )

    def describe(self) -> str:
        return (
            "choose a land type and a basic land type; each land of the first "
            "chosen type becomes the second chosen type until end of turn"
        )


@dataclass(frozen=True)
class TargetArtifactPhasesOut(Effect):
    """"Target artifact phases out." (Vision Charm.) Uses the engine's
    phasing model (``GameObject.phased_out``; it phases in at its
    controller's untap step, ``turn.py``), the same simplified scope as
    Robe of Stars' ``PhaseOutEquippedCreature``."""

    def requires_target(self) -> bool:
        return True

    def legal_targets(self, state, controller_id):
        from mtg_bot.game import effective_card_types

        return [
            ("permanent", o.id) for o in state.battlefield
            if "Artifact" in effective_card_types(state, o) and not o.phased_out
        ]

    def resolve(self, state, controller_id, targets=()):
        if not targets:
            return
        obj = next((o for o in state.battlefield if o.id == targets[0][1]), None)
        if obj is None or obj.phased_out:
            return
        obj.phased_out = True
        obj.attacking = False
        obj.blocking = None
        obj.blocked_by = []
        state.log.append(f"{obj.printing.name} phases out")

    def describe(self) -> str:
        return "target artifact phases out"


@dataclass(frozen=True)
class EachPlayerDrawsUpTo(Effect):
    """"Each player draws up to N cards." (Diminishing Returns.) In turn
    order from the active player (CR 101.4), each player picks how many
    to draw, 0..N, with ``Agent.choose_x`` (upper bound N, or the cards
    left in their library if fewer), then draws
    them; with a shared library the later player draws after the
    earlier one."""

    amount: int = 7

    def resolve(self, state, controller_id, targets=()):
        from mtg_bot.turn import draw_n_cards

        n_players = len(state.players)
        for i in range(n_players):
            p = state.players[(state.active_player_idx + i) % n_players]
            if p.has_lost:
                continue
            # Never offered: drawing past the library's end, which only
            # loses the game (SEARCH_LIMITATIONS, "Forgetful Fish cards" 5).
            bound = min(self.amount, len(p.library))
            n = bound
            if p.agent is not None:
                picked = p.agent.choose_x(state, p.id, "draw up to", bound)
                if isinstance(picked, int):
                    n = max(0, min(bound, picked))
            drawn = draw_n_cards(state, p.id, n)
            state.log.append(f"P{p.id} draws {drawn} card(s) (up to {self.amount})")

    def describe(self) -> str:
        return f"each player draws up to {self.amount} cards"


__all__ = [
    "BASIC_LAND_TYPES",
    "BounceTargetThenTokenCopy",
    "EachPlayerDrawsUpTo",
    "ChangeTextOfTarget",
    "LandsOfChosenTypeBecomeBasicTypeUEOT",
    "TargetArtifactPhasesOut",
    "printed_text_words",
    "TargetYouControlBecomesUEOT",
    "TuckOpponentsPermanentTheyMayPutOne",
    "COLOR_WORDS",
    "CantAttackUnless",
    "DefendingPlayerControlsNoLandType",
    "NameThenMillDrawOnHit",
    "ReorderTargetPlayersTopCards",
    "TAP_WHEN_CONTROL_LOST_KIND",
    "TEXT_CHANGE_KIND",
    "UntapGainControlHasteTapWhenLost",
    "apply_fish_card_checks",
    "YouControlNoLandType",
    "all_card_names",
    "changed_word",
    "choose_card_name",
    "controls_land_of_type",
]
