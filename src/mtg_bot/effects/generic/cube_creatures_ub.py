"""Engine effects for the PowerLSV cube's blue / black creatures.

Each class models one printed effect shape (not one card); the parser
side lives in :mod:`mtg_bot.cards.parser.cube_creatures_ub`.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import TYPE_CHECKING

from mtg_bot.effects.base import Effect, Target

if TYPE_CHECKING:
    from mtg_bot.game import GameState


# ---------------------------------------------------------------------------
# Event-bound anaphora ("they", "that player")
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BindEventPlayer(Effect):
    """Resolve ``inner`` against the player named by the triggering
    event's ``slot`` subject -- the "they" of "Whenever an opponent
    draws a card, they lose 2 life." The player is fixed when the
    trigger fires (``dispatch_event``'s ``targets_from_event`` hook), not
    targeted, so the ability never prompts and can't fizzle for lack of
    a target.
    """

    inner: Effect
    slot: str = "player"

    def targets_from_event(self, state: "GameState", subjects) -> tuple:
        player = subjects.get(self.slot)
        if player is None:
            return ()
        return (("player", player.id),)

    def requires_target(self) -> bool:
        return False

    def legal_targets(self, state, controller_id):
        return []

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        self.inner.resolve(state, controller_id, targets)

    def describe(self) -> str:
        return self.inner.describe()


# ---------------------------------------------------------------------------
# Amass (CR 701.44)
# ---------------------------------------------------------------------------


def _army_token_printing(subtype: str):
    from mtg_bot.cards.base import make_token_creature

    return make_token_creature(
        f"{subtype} Army", 0, 0, subtypes=(subtype, "Army"), colors={"B"},
    )


@dataclass(frozen=True)
class Amass(Effect):
    """``amass <Subtype> N`` (CR 701.44a): if you don't control an Army
    creature, create a 0/0 black <Subtype> Army creature token; choose
    an Army creature you control, put N +1/+1 counters on it, and if it
    isn't a <Subtype> it becomes one in addition to its other types."""

    subtype: str
    amount: int = 1

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.game import add_plus_one_counters, is_creature_now

        def armies():
            return [
                o for o in state.battlefield
                if o.controller_id == controller_id
                and is_creature_now(o)
                and "Army" in o.printing.subtypes
            ]

        if not armies():
            from mtg_bot.effects.generic.tokens import CreateToken

            CreateToken(
                token_printing=_army_token_printing(self.subtype),
            ).resolve(state, controller_id, ())
        pool = armies()
        if not pool:
            return
        army = pool[0]
        p = state.player_by_id(controller_id)
        if len(pool) > 1 and p.agent is not None:
            pick = p.agent.choose_target(
                state, controller_id, [("creature", o.id) for o in pool],
            )
            if pick is not None:
                army = next((o for o in pool if o.id == pick[1]), army)
        add_plus_one_counters(state, army, self.amount)
        if self.subtype not in army.printing.subtypes:
            army.printing = dataclasses.replace(
                army.printing,
                subtypes=army.printing.subtypes + (self.subtype,),
            )
        state.log.append(
            f"P{controller_id} amasses {self.subtype} {self.amount} "
            f"({army.printing.name})"
        )

    def describe(self) -> str:
        return f"amass {self.subtype}s {self.amount}"


# ---------------------------------------------------------------------------
# Self-referential riders
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TapSelf(Effect):
    """"Tap it." where "it" is the ability's own source (Iron-Shield
    Elf's "This creature gains indestructible until end of turn. Tap
    it."). No-op when the source has left the battlefield."""

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.turn import tap_permanent

        src = state.resolving_source
        if src is None or src not in state.battlefield:
            return
        tap_permanent(state, src)

    def describe(self) -> str:
        return "tap this creature"


@dataclass(frozen=True)
class SourceCantBeBlockedThisTurn(Effect):
    """"This creature can't be blocked this turn." -- the ability's own
    source gets the layer-6 can't-be-blocked restriction until end of
    turn (same registry entry ``GrantUnblockableUEOT`` writes)."""

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        src = state.resolving_source
        if src is None or src not in state.battlefield:
            return
        state.add_continuous_effect(
            source_id=src.id, layer=6, kind="cant_be_blocked",
            target_id=src.id, params=(), expires_at="cleanup",
            description=f"{src.printing.name} can't be blocked this turn",
        )
        state.log.append(f"{src.printing.name} can't be blocked this turn")

    def describe(self) -> str:
        return "this creature can't be blocked this turn"


# ---------------------------------------------------------------------------
# Graveyard cast permissions
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MayCastTargetGraveyardCardThisTurn(Effect):
    """"Choose target artifact card in your graveyard. You may cast
    that card this turn." (Emry, Lurker of the Loch). The permission
    rides on the card (``castable_from_graveyard_this_turn``) until
    cleanup; ``legal_actions`` offers the cast at its normal timing for
    its mana cost."""

    card_filter: object = None

    def requires_target(self) -> bool:
        return True

    def legal_targets(self, state, controller_id):
        p = state.player_by_id(controller_id)
        return [
            ("graveyard_card", c.id) for c in p.graveyard
            if self.card_filter.matches(c.printing)
        ]

    def resolve(self, state, controller_id, targets=()):
        from mtg_bot.game import _CowList

        if not targets:
            return
        _, tid = targets[0]
        p = state.player_by_id(controller_id)
        if not any(c.id == tid for c in p.graveyard):
            state.log.append("cast-permission target is gone")
            return
        if isinstance(p.graveyard, _CowList):
            p.graveyard.fork()
        card = next(c for c in p.graveyard if c.id == tid)
        card.castable_from_graveyard_this_turn = True
        state.log.append(
            f"P{controller_id} may cast {card.printing.name} from their "
            f"graveyard this turn"
        )

    def describe(self) -> str:
        return (
            f"choose target {self.card_filter.describe()} in your graveyard; "
            f"you may cast it this turn"
        )


# ---------------------------------------------------------------------------
# Library-top reveals
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RevealTopCardToHandLoseLifeEqualMV(Effect):
    """"Reveal the top card of your library and put that card into your
    hand. You lose life equal to its mana value." (Dark Confidant). An
    empty library reveals nothing and costs no life."""

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.game import Zone

        p = state.player_by_id(controller_id)
        if not p.library:
            return
        card = p.library.pop(0)
        card.zone = Zone.HAND
        p.hand.append(card)
        card.publicly_known_to = frozenset(pl.id for pl in state.players)
        mv = card.printing.mana_cost.total
        p.life -= mv
        state.log.append(
            f"P{controller_id} reveals {card.printing.name} and puts it "
            f"into their hand, losing {mv} life (now {p.life})"
        )

    def describe(self) -> str:
        return (
            "reveal the top card of your library and put it into your "
            "hand; you lose life equal to its mana value"
        )


# ---------------------------------------------------------------------------
# "Target opponent <does A>, <does B>, and <does C>"
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TargetPlayerPerformsActions(Effect):
    """One targeted player performs a list of actions in printed order
    (Archon of Cruelty: "target opponent sacrifices a creature or
    planeswalker of their choice, discards a card, and loses 3 life").

    ``actions`` holds ``(verb, arg)`` pairs:

    * ``("sacrifice", CardFilter)`` -- a permanent of their choice
      matching the filter (none -> nothing happens)
    * ``("discard", n)`` -- n cards of their choice
    * ``("lose_life", n)``
    """

    actions: tuple = ()
    opponent_only: bool = True

    def requires_target(self) -> bool:
        return True

    def legal_targets(self, state: "GameState", controller_id: int):
        return [
            ("player", p.id) for p in state.players
            if not p.has_lost
            and not (self.opponent_only and p.id == controller_id)
        ]

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.effects.generic.card_flow import discard_card
        from mtg_bot.turn import sacrifice

        if not targets or targets[0][0] != "player":
            return
        p = state.player_by_id(targets[0][1])
        if p.has_lost:
            return
        for verb, arg in self.actions:
            if verb == "sacrifice":
                legal = [
                    o for o in state.battlefield
                    if o.controller_id == p.id and arg.matches(o.printing)
                ]
                if not legal:
                    continue
                pick = legal[0]
                if p.agent is not None:
                    pid = p.agent.choose_sacrifice(
                        state, p.id, [o.id for o in legal],
                    )
                    pick = next((o for o in legal if o.id == pid), pick)
                state.log.append(f"P{p.id} sacrifices {pick.printing.name}")
                sacrifice(state, pick)
            elif verb == "discard":
                for _ in range(arg):
                    if not p.hand:
                        break
                    card = p.hand[0]
                    if p.agent is not None:
                        cid = p.agent.choose_discard(
                            state, p.id, [c.id for c in p.hand],
                        )
                        card = next((c for c in p.hand if c.id == cid), card)
                    discard_card(state, p, card)
            else:  # lose_life
                p.life -= arg
                state.log.append(f"P{p.id} loses {arg} life (now {p.life})")

    def describe(self) -> str:
        parts = []
        for verb, arg in self.actions:
            if verb == "sacrifice":
                parts.append(f"sacrifices a {arg.describe()[:-5]} of their choice")
            elif verb == "discard":
                parts.append(f"discards {arg} card(s)")
            else:
                parts.append(f"loses {arg} life")
        who = "target opponent" if self.opponent_only else "target player"
        return f"{who} " + ", ".join(parts)


# ---------------------------------------------------------------------------
# Squad / Offspring token copies
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CreateTokenCopiesOfSelf(Effect):
    """Create token copies of the resolving ability's source: one per
    squad payment (``per_squad_payment``, CR 702.157a), else one; with
    ``base_pt`` set the copies are that size (Offspring's "except it's
    1/1", CR 702.175a). The copy uses the source's copiable values (its
    printing), or its last known printing if it has left the
    battlefield."""

    per_squad_payment: bool = False
    base_pt: "tuple[int, int] | None" = None

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.effects.generic.tokens import CreateToken

        src = state.resolving_source
        if src is None:
            return
        count = src.squad_paid_count if self.per_squad_payment else 1
        if count <= 0:
            return
        base = src.printing
        changes: dict = {}
        if "Token" not in base.supertypes:
            changes["supertypes"] = base.supertypes + ("Token",)
        if self.base_pt is not None:
            changes["power"], changes["toughness"] = self.base_pt
        CreateToken(
            token_printing=dataclasses.replace(base, **changes), count=count,
        ).resolve(state, controller_id, ())

    def describe(self) -> str:
        what = "a token copy of it"
        if self.per_squad_payment:
            what = "a token copy of it for each squad payment"
        if self.base_pt is not None:
            what += f", except it's {self.base_pt[0]}/{self.base_pt[1]}"
        return f"create {what}"


# ---------------------------------------------------------------------------
# Devotion / library-top selection (Thassa's Oracle)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DevotionTo:
    """Formula: your devotion to ``color`` (CR 700.5) -- the number of
    that color's mana symbols (hybrid and Phyrexian included) among the
    mana costs of permanents you control."""

    color: str

    def value(self, state: "GameState", controller_id: int) -> int:
        total = 0
        for o in state.battlefield:
            if o.controller_id != controller_id:
                continue
            mc = o.printing.mana_cost
            total += sum(n for c, n in mc.colored if c == self.color)
            total += sum(1 for pair in mc.hybrid if self.color in pair)
            total += sum(1 for c in mc.phyrexian if c == self.color)
        return total


@dataclass(frozen=True)
class LookTopNKeepUpToOneOnTopRestBottom(Effect):
    """"Look at the top N cards of your library. Put up to one of them
    on top of your library and the rest on the bottom of your library
    in a random order." The kept card is the agent's pick
    (``choose_card_from_library``; ``None`` keeps none)."""

    count: object = 1

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        n = self.count if isinstance(self.count, int) else self.count.value(
            state, controller_id,
        )
        p = state.player_by_id(controller_id)
        n = max(0, min(n, len(p.library)))
        if n == 0:
            return
        looked = [p.library.pop(0) for _ in range(n)]
        keep = None
        if p.agent is not None:
            pick = p.agent.choose_card_from_library(
                state, controller_id, [c.id for c in looked],
            )
            keep = next((c for c in looked if c.id == pick), None)
        rest = [c for c in looked if c is not keep]
        state.rng.shuffle(rest)
        p.library.extend(rest)
        if keep is not None:
            p.library.insert(0, keep)
        kept = "one" if keep is not None else "none"
        state.log.append(
            f"P{controller_id} looks at the top {n} cards; keeps {kept} on top"
        )

    def describe(self) -> str:
        return (
            "look at the top N cards of your library; put up to one on top "
            "and the rest on the bottom in a random order"
        )


@dataclass(frozen=True)
class FormulaCoversLibrary:
    """Condition: ``formula`` >= the number of cards in your library
    ("If X is greater than or equal to the number of cards in your
    library")."""

    formula: object

    def matches(self, state, viewer_id, chosen_targets=None) -> bool:
        return self.formula.value(state, viewer_id) >= len(
            state.player_by_id(viewer_id).library
        )


# ---------------------------------------------------------------------------
# "... loses all abilities for as long as <source> remains on the battlefield"
# ---------------------------------------------------------------------------


def _lose_abilities_while_source_remains(state, source, obj) -> None:
    """Layer-6 lose-all-abilities on ``obj`` that lasts while ``source``
    is on the battlefield (a registry entry with no expiry is dropped
    when its source leaves play)."""
    if source is None or source not in state.battlefield:
        return
    if obj not in state.battlefield:
        return
    state.add_continuous_effect(
        source_id=source.id, layer=6, kind="lose_all_abilities",
        target_id=obj.id, params=(),
        description=(
            f"{obj.printing.name} loses all abilities while "
            f"{source.printing.name} remains"
        ),
    )
    state.log.append(
        f"{obj.printing.name} loses all abilities for as long as "
        f"{source.printing.name} remains on the battlefield"
    )


@dataclass(frozen=True)
class ThenTargetLosesAbilitiesWhileSourceRemains(Effect):
    """"<targeted effect>. It loses all abilities for as long as this
    creature remains on the battlefield." (The Wondrous Wasp). The
    inner effect's single target is the "it"."""

    inner: Effect

    def requires_target(self) -> bool:
        return self.inner.requires_target()

    def legal_targets(self, state, controller_id):
        return self.inner.legal_targets(state, controller_id)

    def target_count_range(self):
        return self.inner.target_count_range()

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        self.inner.resolve(state, controller_id, targets)
        if not targets:
            return
        obj = next((o for o in state.battlefield if o.id == targets[0][1]), None)
        if obj is not None:
            _lose_abilities_while_source_remains(
                state, state.resolving_source, obj,
            )

    def describe(self) -> str:
        return (
            f"{self.inner.describe()}; it loses all abilities for as long "
            "as this creature remains on the battlefield"
        )


# ---------------------------------------------------------------------------
# Countering spells and abilities
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CounterTargetStackObject(Effect):
    """"Counter target spell, activated ability, or triggered ability"
    and its narrower forms (Ertai Resurrected, Tishana's Tidebinder).
    ``kinds`` names what may be targeted: ``"spell"``, ``"activated"``,
    ``"triggered"``. ``up_to_one`` makes the target optional.
    ``lose_abilities_while_source`` adds Tidebinder's rider: if the
    countered ability's source is an artifact, creature, or
    planeswalker, it loses all abilities while this creature remains.
    Mana abilities never use the stack, so they're never targets."""

    kinds: tuple = ("spell", "activated", "triggered")
    up_to_one: bool = False
    lose_abilities_while_source: bool = False

    def requires_target(self) -> bool:
        return True

    def target_count_range(self) -> tuple[int, int]:
        return (0 if self.up_to_one else 1, 1)

    @staticmethod
    def _kind(item) -> str:
        from mtg_bot.effects import ActivatedAbility

        if item.ability is None:
            return "spell"
        if isinstance(item.ability, ActivatedAbility):
            return "activated"
        return "triggered"

    def legal_targets(self, state, controller_id):
        from mtg_bot.effects.generic.stack_control import CounterTargetSpell

        out = []
        for i, item in enumerate(state.stack):
            if item.countered or self._kind(item) not in self.kinds:
                continue
            if item.ability is None and CounterTargetSpell._is_uncounterable(
                state, item,
            ):
                continue
            out.append(("stack", i))
        return out

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        if not targets or targets[0] not in self.legal_targets(
            state, controller_id,
        ):
            return
        item = state.stack[targets[0][1]]
        item.countered = True
        state.log.append(
            f"{item.source.printing.name}'s {self._kind(item)} is countered"
        )
        if self.lose_abilities_while_source and item.ability is not None:
            src = item.source
            pr = src.printing
            if pr.is_artifact or pr.is_creature or "Planeswalker" in pr.card_types:
                _lose_abilities_while_source_remains(
                    state, state.resolving_source, src,
                )

    def describe(self) -> str:
        words = {
            "spell": "spell", "activated": "activated ability",
            "triggered": "triggered ability",
        }
        noun = " or ".join(words[k] for k in self.kinds)
        up = "up to one " if self.up_to_one else ""
        return f"counter {up}target {noun}"


@dataclass(frozen=True)
class ThenItsControllerDraws(Effect):
    """"<targeted effect>. Its controller draws a card." -- the
    controller of the (still legal) target, fixed before ``inner``
    resolves, draws ``amount`` (Ertai Resurrected's modes). A target
    that has become illegal means the ability does nothing (CR
    608.2b)."""

    inner: Effect
    amount: int = 1

    def requires_target(self) -> bool:
        return self.inner.requires_target()

    def legal_targets(self, state, controller_id):
        return self.inner.legal_targets(state, controller_id)

    def target_count_range(self):
        return self.inner.target_count_range()

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.turn import draw_n_cards

        if not targets:
            return
        prior = state.resolving_controller_id
        state.resolving_controller_id = controller_id
        try:
            legal = targets[0] in self.inner.legal_targets(state, controller_id)
        finally:
            state.resolving_controller_id = prior
        if not legal:
            return
        kind, tid = targets[0]
        if kind == "stack":
            who = state.stack[tid].controller_id
        else:
            obj = next((o for o in state.battlefield if o.id == tid), None)
            who = obj.controller_id if obj is not None else None
        self.inner.resolve(state, controller_id, targets)
        if who is not None:
            draw_n_cards(state, who, self.amount)

    def describe(self) -> str:
        return f"{self.inner.describe()}; its controller draws a card"


@dataclass(frozen=True)
class ChooseNoMode(Effect):
    """The "none" option of a "choose up to one" modal ability."""

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        state.log.append(f"P{controller_id} chooses no mode")

    def describe(self) -> str:
        return "choose no mode"


__all__ = [
    "ChooseNoMode",
    "CounterTargetStackObject",
    "DevotionTo",
    "FormulaCoversLibrary",
    "LookTopNKeepUpToOneOnTopRestBottom",
    "ThenItsControllerDraws",
    "ThenTargetLosesAbilitiesWhileSourceRemains",
    "MayCastTargetGraveyardCardThisTurn",
    "SourceCantBeBlockedThisTurn",
    "CreateTokenCopiesOfSelf",
    "TargetPlayerPerformsActions",
    "RevealTopCardToHandLoseLifeEqualMV",
    "TapSelf",
    "Amass",
    "BindEventPlayer",
]
