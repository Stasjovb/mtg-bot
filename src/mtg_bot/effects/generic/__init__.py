"""Generic, reusable effects — damage, life, counters, zone moves,
tokens, pumps, search, draw, tap/untap, etc. Card-agnostic primitives that
many printings reuse. Card-specific one-off effects live in ``bespoke.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from mtg_bot.effects.base import (
    Effect, Target, TriggeredAbility,
    _apply_damage, _multicolored_permanents_count,
    _find_moonlit_replacement_source,
)

if TYPE_CHECKING:
    from mtg_bot.cards import ManaCost
    from mtg_bot.effects.formulas import Formula
    from mtg_bot.game import GameState


@dataclass(frozen=True)
class OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary(Effect):
    """Target artifact or creature's owner puts it on their choice of the
    top or bottom of their library.

    Matches Lost in Space's main effect. The OWNER (not the spell's
    controller) makes the top-vs-bottom decision via their agent's
    ``choose_mode`` hook. Tokens cease to exist when bounced (rule
    704.5d) — they'd briefly land in the library, but a non-trivial
    state-based action removes them. Combat / counter state is cleared
    on the way off the battlefield as in other bounce effects.

    ``nonland_permanent`` widens the legal-target pool from "artifact
    or creature" to "any nonland permanent" — Vanish from Sight's
    printed scope. The same engine class is reused with a flag (rather
    than a sibling class) because every line below the legal-target
    filter is identical: same owner-choice top-vs-bottom prompt, same
    bounce-style cleanup, same token-ceases-to-exist handling.
    """

    nonland_permanent: bool = False

    def requires_target(self) -> bool:
        return True

    def _matches(self, printing) -> bool:
        if self.nonland_permanent:
            return not printing.is_land
        return printing.is_artifact or printing.is_creature

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        return [
            ("permanent", o.id)
            for o in state.battlefield
            if self._matches(o.printing)
        ]

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.game import Zone

        if not targets:
            return
        kind, target_id = targets[0]
        if kind != "permanent":
            return
        obj = next((o for o in state.battlefield if o.id == target_id), None)
        if obj is None:
            return
        if not self._matches(obj.printing):
            return
        owner = state.player_by_id(obj.owner_id)
        # Owner picks top vs bottom via their agent's choose_mode.
        # Default to top when no agent is seated (e.g., in unit tests).
        if owner.agent is not None:
            choice = owner.agent.choose_mode(
                state, owner.id,
                ["top of library", "bottom of library"],
            )
        else:
            choice = 0
        choice = 0 if choice not in (0, 1) else choice

        # Strip the permanent off the battlefield with the same
        # housekeeping as other bounce-style effects.
        state.battlefield.remove(obj)
        obj.damage = 0
        obj.marked_lethal = False
        obj.damaged_this_turn = False
        obj.tapped = False
        obj.attacking = False
        obj.blocking = None
        obj.blocked_by = []
        obj.plus_one_counters = 0
        obj.charge_counters = 0
        obj.temp_power_bonus = 0
        obj.temp_toughness_bonus = 0
        obj.attached_to = None
        if not obj.printing.is_land:
            state.permanent_left_battlefield_this_turn = True
        if obj.printing.is_token:
            state.log.append(
                f"{obj.printing.name} token ceases to exist (bounced)"
            )
            return
        obj.zone = Zone.LIBRARY
        if choice == 0:
            owner.library.insert(0, obj)
            destination = "top"
        else:
            owner.library.append(obj)
            destination = "bottom"
        state.log.append(
            f"{obj.printing.name} put on the {destination} of "
            f"P{owner.id}'s library"
        )

    def describe(self) -> str:
        scope = (
            "nonland permanent"
            if self.nonland_permanent
            else "artifact or creature"
        )
        return (
            f"target {scope}'s owner puts it on their choice of the "
            f"top or bottom of their library"
        )



@dataclass(frozen=True)
class OwnerPutsTargetWarpedExileCardOnBottomOfLibrary(Effect):
    """Put target exiled card with warp on the bottom of its owner's library.

    Matches mode 1 of Blade of the Swarm. Target pool is every card in
    any player's exile zone whose ``warped`` flag is set (the flag is
    raised when a warp-cast creature is exiled at the end step). The
    chosen card is moved to the bottom of its owner's library and its
    warp-related state is cleared (it's now a normal library card).

    Sibling of ``OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary``,
    but without the top/bottom owner choice (always bottom) and sourcing
    from exile rather than the battlefield. Targets carry kind
    ``"exile_card"`` — distinct from "permanent" because the card isn't
    on the battlefield and the cast pipeline shouldn't try to look it up
    there.
    """

    def requires_target(self) -> bool:
        return True

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        out: list[Target] = []
        for p in state.players:
            for c in p.exile:
                if c.warped:
                    out.append(("exile_card", c.id))
        return out

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.game import Zone

        if not targets:
            return
        kind, target_id = targets[0]
        if kind != "exile_card":
            return
        # Locate the target across every player's exile.
        obj = None
        owner = None
        for p in state.players:
            for c in p.exile:
                if c.id == target_id:
                    obj = c
                    owner = p
                    break
            if obj is not None:
                break
        if obj is None or owner is None:
            return
        # Re-check the warped flag at resolution — if something stripped
        # it (or the card moved zones in response), the spell fizzles.
        if not obj.warped:
            return
        owner.exile.remove(obj)
        obj.warped = False
        obj.zone = Zone.LIBRARY
        owner.library.append(obj)
        state.log.append(
            f"{obj.printing.name} put on the bottom of P{owner.id}'s "
            f"library (was warped in exile)"
        )

    def describe(self) -> str:
        return (
            "put target exiled card with warp on the bottom of "
            "its owner's library"
        )



@dataclass(frozen=True)
class AttachToTargetCreatureYouControl(Effect):
    """Attach the source (Equipment) to target creature the controller
    controls. Matches the common ETB trigger on EoE Equipment.

    Reads state.resolving_source for the Equipment. No-op if the source
    isn't an Equipment (is_equipment check on subtypes).

    Optional ``granted_keywords_ueot``: keywords the chosen target also
    gains until end of turn. Matches oracle riders like Squire's
    Lightblade's "...attach it to target creature you control. That
    creature gains first strike until end of turn." and Illvoi Light
    Jammer's "...gains hexproof until end of turn." Adding the keyword
    here (rather than via a separate Sequence sub-effect) keeps the
    target shared between attach and the UEOT grant. The grant is
    applied after the attach succeeds; if the attach fizzles, no
    keywords are granted.
    """

    granted_keywords_ueot: frozenset[str] = frozenset()

    def requires_target(self) -> bool:
        return True

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        return [
            ("creature", o.id)
            for o in state.battlefield
            if o.printing.is_creature and o.controller_id == controller_id
        ]

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        source = state.resolving_source
        if source is None:
            return
        if "Equipment" not in source.printing.subtypes:
            return
        if not targets:
            return
        kind, target_id = targets[0]
        if kind != "creature":
            return
        target = next(
            (o for o in state.battlefield if o.id == target_id), None
        )
        if target is None or not target.printing.is_creature:
            return
        if target.controller_id != controller_id:
            return
        source.attached_to = target_id
        state.log.append(
            f"{source.printing.name} is attached to {target.printing.name}"
        )
        if self.granted_keywords_ueot:
            from mtg_bot.effects.combinators import ApplyEffect
            from mtg_bot.effects.durations import EndOfTurn

            ApplyEffect(
                inner=GrantKeywords(keywords=self.granted_keywords_ueot),
                ends_at=EndOfTurn(),
            ).resolve(
                state, controller_id, (("creature", target.id),),
            )
            state.log.append(
                f"{target.printing.name} gains "
                f"{', '.join(sorted(self.granted_keywords_ueot))} "
                "until end of turn"
            )

    def describe(self) -> str:
        base = "attach this Equipment to target creature you control"
        if self.granted_keywords_ueot:
            return (
                f"{base}. That creature gains "
                f"{', '.join(sorted(self.granted_keywords_ueot))} "
                "until end of turn"
            )
        return base



@dataclass(frozen=True)
class EquipToTargetCreatureYouControl(AttachToTargetCreatureYouControl):
    """Equip activated-ability resolution effect (rule 702.6).

    Behaves identically to ``AttachToTargetCreatureYouControl`` (re-targets
    the source Equipment onto a creature the controller controls, replacing
    any prior attachment), but is given a distinct name and ``describe``
    string so logs and tooling can tell ETB-attach from a paid Equip
    activation. Pair with an ``ActivatedAbility`` whose cost is the printed
    Equip mana cost and ``sorcery_speed=True``.
    """

    def describe(self) -> str:
        return "equip: attach this Equipment to target creature you control"



@dataclass(frozen=True)
class ReturnCreatureFromYourGraveyardToBattlefield(Effect):
    """Target creature card from your graveyard enters the battlefield under
    your control. Fires ETB triggers (via put_into_battlefield).

    Target format: ``("graveyard_creature", id)`` where id is a GameObject
    in the controller's graveyard.

    ``max_mv``: when set, restricts the legal target pool to creature
    cards with mana value ≤ ``max_mv``. Models Surgical Suite's "with
    mana value 3 or less" rider. None = no mana-value restriction.

    ``or_enchantment`` widens the legal-target pool to also include
    enchantment cards in the graveyard. Matches oracle text "return
    target creature or enchantment card from your graveyard to the
    battlefield" — Rescue Skiff's ETB body. Mirrors the ``or_spacecraft``
    flag on ``ReturnCreatureFromYourGraveyardToHand`` (Fell Gravship).
    """

    max_mv: "int | None" = None
    # When True, enchantment cards in the graveyard are also legal
    # targets. Matches "return target creature or enchantment card from
    # your graveyard to the battlefield" — Rescue Skiff.
    or_enchantment: bool = False
    # When True, Spacecraft cards in the graveyard are also legal
    # targets. Matches "return target creature or Spacecraft card from
    # your graveyard to the battlefield" — Seedship Broodtender.
    or_spacecraft: bool = False

    def requires_target(self) -> bool:
        return True

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        p = state.player_by_id(controller_id)
        return [
            ("graveyard_creature", c.id)
            for c in p.graveyard
            if (
                c.printing.is_creature
                or (self.or_enchantment and c.printing.is_enchantment)
                or (self.or_spacecraft and c.printing.is_spacecraft)
            )
            and (
                self.max_mv is None
                or c.printing.mana_cost.total <= self.max_mv
            )
        ]

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.actions import put_into_battlefield

        if not targets:
            return
        kind, target_id = targets[0]
        if kind != "graveyard_creature":
            return
        p = state.player_by_id(controller_id)
        card = next((c for c in p.graveyard if c.id == target_id), None)
        if card is None:
            return
        p.graveyard.remove(card)
        state.log.append(
            f"{card.printing.name} returns from P{controller_id}'s "
            f"graveyard to the battlefield"
        )
        put_into_battlefield(state, card, controller_id)

    def describe(self) -> str:
        type_phrase = (
            "creature or enchantment" if self.or_enchantment else "creature"
        )
        return (
            f"return target {type_phrase} card from your graveyard to the "
            f"battlefield"
        )



@dataclass(frozen=True)
class ReturnAllCreaturesFromYourGraveyardToBattlefield(Effect):
    """Return every creature card from your graveyard to the battlefield
    under your control. Untargeted mass-reanimation — Awakening Hall's
    "Return all creature cards from your graveyard to the battlefield"
    when its door is unlocked.

    Each creature is moved out of the graveyard and routed through
    ``put_into_battlefield`` so its ETB triggers fire normally. Order
    of resolution follows the graveyard's stored order (oldest first);
    we don't model APNAP for the iteration since the controller is the
    same player throughout.
    """

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.actions import put_into_battlefield

        p = state.player_by_id(controller_id)
        # Snapshot the graveyard before mutation — entering creatures
        # could (in theory) trigger other effects that touch the
        # graveyard mid-resolution. We iterate the snapshot.
        creatures = [c for c in list(p.graveyard) if c.printing.is_creature]
        for card in creatures:
            if card not in p.graveyard:
                # Defensive: an ETB earlier in this loop already moved
                # the card (very rare; included for safety).
                continue
            p.graveyard.remove(card)
            state.log.append(
                f"{card.printing.name} returns from P{controller_id}'s "
                f"graveyard to the battlefield"
            )
            put_into_battlefield(state, card, controller_id)

    def describe(self) -> str:
        return (
            "return all creature cards from your graveyard to the "
            "battlefield"
        )


@dataclass(frozen=True)
class PutCardFromGraveyardOnBottomOfLibrary(Effect):
    """Put target card from a graveyard on the bottom of its owner's
    library. Matches Chrome Companion's activated ability. Any
    graveyard is a legal target source (either player's).
    """

    def requires_target(self) -> bool:
        return True

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        from mtg_bot.game import Zone

        return [
            ("card_in_graveyard", c.id)
            for p in state.players
            for c in p.graveyard
            if c.zone == Zone.GRAVEYARD
        ]

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.game import Zone

        if not targets:
            return
        kind, target_id = targets[0]
        if kind != "card_in_graveyard":
            return
        for p in state.players:
            card = next((c for c in p.graveyard if c.id == target_id), None)
            if card is None:
                continue
            p.graveyard.remove(card)
            card.zone = Zone.LIBRARY
            p.library.append(card)  # bottom = end of list
            state.log.append(
                f"{card.printing.name} put on the bottom of "
                f"P{p.id}'s library"
            )
            return

    def describe(self) -> str:
        return (
            "put target card from a graveyard on the bottom of its "
            "owner's library"
        )



@dataclass(frozen=True)
class ControlTargetOpponentNextTurn(Effect):
    """The Dominion Bracelet: "You control target opponent during
    their next turn."

    Implementation: schedule the target player's ``scheduled_agent_
    override`` to the source-controller's agent, taking effect the
    next time it's the target's turn. On cleanup of that turn, the
    override is reverted automatically by run_cleanup_step.
    """

    def requires_target(self) -> bool:
        return True

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        return [
            ("player", p.id)
            for p in state.players
            if p.id != controller_id and not p.has_lost
        ]

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        if not targets:
            return
        kind, target_id = targets[0]
        if kind != "player":
            return
        target = state.player_by_id(target_id)
        caster = state.player_by_id(controller_id)
        # Schedule the override: the caster's agent will be swapped
        # into the target at the start of the target's next turn.
        target.scheduled_agent_override = caster.agent
        target.scheduled_agent_override_by = controller_id
        state.log.append(
            f"P{controller_id} will control P{target_id} during "
            f"P{target_id}'s next turn"
        )

    def describe(self) -> str:
        return "you control target opponent during their next turn"



@dataclass(frozen=True)
class ChangeControllerToCombatDamageSource(Effect):
    """Contested War Zone: "Whenever a creature deals combat damage to
    you, that creature's controller gains control of this land."

    Phase-9 wired the predicate-style ``Event.DEALS_COMBAT_DAMAGE``
    dispatch to thread the attacker's controller through
    ``state.resolving_combat_damage_source_controller_id`` (mirrored
    onto the StackItem) rather than ``fixed_targets``. The slot
    works the same way as ``state.resolving_combat_damage_amount``:
    set on push, mirrored at resolve time, cleared after. Permanent
    continuous effect (not UEOT); the new controller keeps the land
    until another control-change effect overrides it.
    """

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        source = state.resolving_source
        if source is None:
            return
        new_cid = state.resolving_combat_damage_source_controller_id
        if new_cid is None or new_cid == source.controller_id:
            return
        old_cid = source.controller_id
        source.controller_id = new_cid
        state.log.append(
            f"P{new_cid} gains control of {source.printing.name} "
            f"(was P{old_cid})"
        )

    def describe(self) -> str:
        return "that creature's controller gains control of this land"



@dataclass(frozen=True)
class EachOpponentMillsCards(Effect):
    """Each opponent puts the top ``amount`` cards of their library into
    their graveyard. Used as the 2-player simplification of "defending
    player mills N" attack triggers (Specimen Freighter).
    """

    amount: int = 1

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.game import Zone

        for p in state.players:
            if p.id == controller_id or p.has_lost:
                continue
            milled = 0
            for _ in range(self.amount):
                if not p.library:
                    break
                card = p.library.pop(0)
                card.zone = Zone.GRAVEYARD
                p.graveyard.append(card)
                milled += 1
            state.log.append(f"P{p.id} mills {milled} cards")

    def describe(self) -> str:
        return f"defending player mills {self.amount} cards"



@dataclass(frozen=True)
class DrawCardsEqualToResolvingCounterAmount(Effect):
    """Draw a number of cards equal to
    ``state.resolving_counter_amount``. Matches Terrasymbiosis's "draw
    that many cards" observer. No-op if amount is 0.
    """

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.turn import draw_n_cards

        amount = state.resolving_counter_amount
        if amount <= 0:
            return
        drawn = draw_n_cards(state, controller_id, amount)
        state.log.append(
            f"P{controller_id} draws {drawn} (counter-added trigger)"
        )

    def describe(self) -> str:
        return "you may draw that many cards"



@dataclass(frozen=True)
class DrawCardsEqualToResolvingCombatDamage(Effect):
    """Draw a number of cards equal to
    ``state.resolving_combat_damage_amount``. Matches Starwinder's
    "you may draw that many cards" observer trigger (the "may" is
    simplified to always yes, consistent with other OptionalXyz
    simplifications in this engine).

    No-op if the resolving amount is 0 (e.g. accidentally invoked
    outside a combat-damage trigger).
    """

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.turn import draw_n_cards

        amount = state.resolving_combat_damage_amount
        if amount <= 0:
            return
        drawn = draw_n_cards(state, controller_id, amount)
        state.log.append(
            f"P{controller_id} draws {drawn} cards (combat-damage trigger)"
        )

    def describe(self) -> str:
        return "you may draw that many cards"



@dataclass(frozen=True)
class DrawCardPerMulticoloredPermanent(Effect):
    """Draw one card for each multicolored permanent you control.
    Matches Infinite Guideline Station's attack trigger."""

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.game import Zone

        n = _multicolored_permanents_count(state, controller_id)
        p = state.player_by_id(controller_id)
        drew = 0
        for _ in range(n):
            if not p.library:
                break
            card = p.library.pop(0)
            card.zone = Zone.HAND
            p.hand.append(card)
            drew += 1
        state.log.append(
            f"P{controller_id} draws {drew} cards "
            f"(multicolored-permanent count)"
        )

    def describe(self) -> str:
        return "draw a card for each multicolored permanent you control"



@dataclass(frozen=True)
class MillTargetPlayer(Effect):
    """Target player puts the top N cards of their library into their
    graveyard.

    If ``use_controller_life`` is True, N is the controller's current life
    total (minimum 0) instead of ``amount`` — matches Space-Time Anomaly.
    Running out of cards mid-mill simply stops; empty-library loss is
    handled separately by the draw step.
    """

    amount: int = 1
    use_controller_life: bool = False

    def requires_target(self) -> bool:
        return True

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        return [
            ("player", p.id) for p in state.players if not p.has_lost
        ]

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.game import Zone

        if not targets:
            return
        kind, target_id = targets[0]
        if kind != "player":
            return
        target = state.player_by_id(target_id)
        if self.use_controller_life:
            n = max(0, state.player_by_id(controller_id).life)
        else:
            n = self.amount
        milled = 0
        for _ in range(n):
            if not target.library:
                break
            card = target.library.pop(0)
            card.zone = Zone.GRAVEYARD
            target.graveyard.append(card)
            milled += 1
        state.log.append(f"P{target_id} mills {milled} cards")

    def describe(self) -> str:
        if self.use_controller_life:
            return (
                "target player mills cards equal to your life total"
            )
        return f"target player mills {self.amount} cards"



@dataclass(frozen=True)
class DrawCards(Effect):
    amount: int

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.turn import draw_n_cards

        drawn = draw_n_cards(state, controller_id, self.amount)
        state.log.append(f"P{controller_id} draws {drawn} card(s)")

    def describe(self) -> str:
        if self.amount == 1:
            return "you draw a card"
        return f"you draw {self.amount} cards"



@dataclass(frozen=True)
class EachPlayerDraws(Effect):
    amount: int

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.turn import draw_n_cards

        for i in range(len(state.players)):
            idx = (state.active_player_idx + i) % len(state.players)
            p = state.players[idx]
            if p.has_lost:
                continue
            draw_n_cards(state, p.id, self.amount)
        state.log.append(
            f"each player draws {self.amount} card(s) "
            f"(from {state.players[controller_id].id}'s trigger)"
        )

    def describe(self) -> str:
        if self.amount == 1:
            return "each player draws a card"
        return f"each player draws {self.amount} cards"



@dataclass(frozen=True)
class TargetArtifactBecomesCreatureUEOT(Effect):
    """Synthesizer Labship's 2+ tier trigger: ``up to one other target
    artifact you control becomes an artifact creature with base power
    and toughness ``power``/``toughness`` and gains ``granted_keywords``
    until end of turn.``

    Composes ``ApplyEffect(BecomeType(...), EndOfTurn())`` for the
    type/PT side and ``ApplyEffect(GrantKeywords(...), EndOfTurn())``
    for the keyword grants — both threaded through the chosen target.
    Targets exclude the source (``"other"``); both creature and
    non-creature artifacts are valid targets (a non-creature artifact
    gains creature status until end of turn; an already-creature
    artifact has its base P/T overridden — which can shrink a
    stationed Spacecraft).
    """

    power: int = 0
    toughness: int = 0
    granted_keywords: frozenset[str] = frozenset()

    def requires_target(self) -> bool:
        return True

    def target_count_range(self) -> tuple[int, int]:
        # "Up to one" — declining is legal.
        return (0, 1)

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        source = state.resolving_source
        source_id = source.id if source is not None else -1
        return [
            ("permanent", o.id)
            for o in state.battlefield
            if o.controller_id == controller_id
            and o.printing.is_artifact
            and o.id != source_id
        ]

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.effects.combinators import ApplyEffect
        from mtg_bot.effects.durations import EndOfTurn

        if not targets:
            return
        kind, target_id = targets[0]
        if kind != "permanent":
            return
        obj = next(
            (o for o in state.battlefield if o.id == target_id), None
        )
        if obj is None:
            return
        ApplyEffect(
            inner=BecomeType(
                types_to_add=("creature",),
                base_pt=(self.power, self.toughness),
            ),
            ends_at=EndOfTurn(),
        ).resolve(state, controller_id, targets)
        if self.granted_keywords:
            ApplyEffect(
                inner=GrantKeywords(keywords=self.granted_keywords),
                ends_at=EndOfTurn(),
            ).resolve(state, controller_id, targets)
        kw_note = (
            f" and gains {', '.join(sorted(self.granted_keywords))}"
            if self.granted_keywords else ""
        )
        state.log.append(
            f"{obj.printing.name} becomes a {self.power}/{self.toughness}"
            f" artifact creature{kw_note} until end of turn"
        )

    def describe(self) -> str:
        kw = ""
        if self.granted_keywords:
            kw = f" and gains {', '.join(sorted(self.granted_keywords))}"
        return (
            f"up to one other target artifact you control becomes a "
            f"{self.power}/{self.toughness} artifact creature{kw} until "
            f"end of turn"
        )



@dataclass(frozen=True)
class BecomeLandCreatureUEOT(Effect):
    """Animate a land into a creature until end of turn.

    Composes the new ``ApplyEffect(BecomeType(...), EndOfTurn())``
    primitive for the type/subtype/PT side: writes layer-4
    ``add_type "creature"`` (+ optional ``add_subtype``) and layer-7
    ``set_base_pt`` registry entries with ``expires_at="cleanup"``,
    flipping ``permanent_is_creature`` for the duration. The
    cleanup-step rebuild in ``run_cleanup_step`` reverts the cache to
    False once the registry entries expire, so the land returns to
    its non-creature state at end of turn.

    Keyword grants ride ``ApplyEffect(GrantKeywords(...),
    EndOfTurn())`` (layer-6 ``grant_keyword`` registry entries). The
    ``unblockable`` rider for Creeping Tar Pit is structurally
    distinct from real keywords — "can't be blocked" is a continuous
    gameplay-action restriction, not an ability — so it composes via
    ``ApplyEffect(GrantUnblockable(...), EndOfTurn())`` (layer-6
    ``cant_be_blocked`` registry entry), separately from the keyword
    grants. Granted activated / triggered abilities ride
    ``ApplyEffect(GrantActivatedAbility(...), EndOfTurn())`` /
    ``ApplyEffect(GrantTriggeredAbility(...), EndOfTurn())`` (layer-6
    ``grant_*_ability`` registry entries).
    """

    power: int = 0
    toughness: int = 0
    granted_keywords: frozenset[str] = frozenset()
    unblockable: bool = False
    # Subtype the animated creature gains UEOT (e.g., "Blinkmoth" for
    # Blinkmoth Nexus, "Elemental" for Lavaclaw Reaches). Written as
    # a layer-4 ``add_subtype`` registry entry (read by
    # ``effective_subtypes``); reverts when the entry expires at
    # cleanup.
    granted_subtype: str | None = None
    # Activated / triggered abilities granted UEOT to the source while
    # animated. Composed via
    # ``ApplyEffect(GrantActivatedAbility(...), EndOfTurn())`` /
    # ``ApplyEffect(GrantTriggeredAbility(...), EndOfTurn())`` — each
    # writes a layer-6 registry entry with ``expires_at="cleanup"``.
    # Used by manlands whose printed text grants per-card abilities
    # only while the land is a creature (Lavaclaw Reaches, Wandering
    # Fumarole, Raging Ravine).
    granted_activated_abilities: tuple = ()
    granted_triggered_abilities: tuple = ()

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.effects.combinators import ApplyEffect
        from mtg_bot.effects.durations import EndOfTurn

        source = state.resolving_source
        if source is None:
            return
        subtypes = (
            (self.granted_subtype,) if self.granted_subtype else ()
        )
        ApplyEffect(
            inner=BecomeType(
                types_to_add=("creature",),
                subtypes_to_add=subtypes,
                base_pt=(self.power, self.toughness),
            ),
            ends_at=EndOfTurn(),
        ).resolve(state, controller_id, ())
        kws = self.granted_keywords
        if kws:
            ApplyEffect(
                inner=GrantKeywords(keywords=kws),
                ends_at=EndOfTurn(),
            ).resolve(state, controller_id, ())
        if self.unblockable:
            # "Can't be blocked" is a continuous effect, not a keyword
            # — composes via the dedicated ``GrantUnblockable``
            # primitive (direct / self-target shape: ``self.targets``
            # empty, runtime ``targets`` carries the animated land),
            # which writes a layer-6 ``cant_be_blocked`` registry
            # entry (read by ``game.is_cant_be_blocked``).
            ApplyEffect(
                inner=GrantUnblockable(),
                ends_at=EndOfTurn(),
            ).resolve(state, controller_id, (("permanent", source.id),))
        for ab in self.granted_activated_abilities:
            ApplyEffect(
                inner=GrantActivatedAbility(ability=ab),
                ends_at=EndOfTurn(),
            ).resolve(state, controller_id, ())
        for ab in self.granted_triggered_abilities:
            ApplyEffect(
                inner=GrantTriggeredAbility(ability=ab),
                ends_at=EndOfTurn(),
            ).resolve(state, controller_id, ())
        kw_parts = sorted(kws)
        if self.unblockable:
            kw_parts.append("unblockable")
        kw_note = (
            f" with {', '.join(kw_parts)}" if kw_parts else ""
        )
        state.log.append(
            f"{source.printing.name} becomes a {self.power}/{self.toughness}"
            f" creature UEOT{kw_note}"
        )

    def describe(self) -> str:
        kws = (
            " with " + ", ".join(sorted(self.granted_keywords))
            if self.granted_keywords else ""
        )
        unb = " (unblockable)" if self.unblockable else ""
        return (
            f"until end of turn, this land becomes a "
            f"{self.power}/{self.toughness} creature{kws}{unb}; "
            f"it's still a land"
        )


@dataclass(frozen=True)
class BecomesCopyOfTargetLand(Effect):
    """Thespian's Stage: "This land becomes a copy of target land,
    except it has this ability." Continuous effect — persists until the
    source leaves play or another copy effect overrides.

    Implementation: mutates ``source.printing`` to point at a fresh
    CardPrinting derived from the target's, with the source's own
    activated abilities appended (so "it has this ability" is
    preserved across repeated re-copies).

    Simplifications:
    - Re-copying from the newly-mutated printing still re-derives
      "retained own abilities" from ``source.original_printing``, which
      is snapshotted on the first resolve. Prevents accidental
      ability accumulation across multiple copies.
    - Copying a token target (rare but possible) carries the token
      supertype through unchanged; the source itself doesn't become a
      token.
    """

    def requires_target(self) -> bool:
        return True

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        return [
            ("permanent", o.id)
            for o in state.battlefield
            if o.printing.is_land
        ]

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        import dataclasses as _dc

        source = state.resolving_source
        if source is None or not targets:
            return
        _, tid = targets[0]
        target = next(
            (o for o in state.battlefield if o.id == tid), None,
        )
        if target is None:
            return
        # Snapshot the original printing the first time we copy — so
        # re-copy activations don't lose "this ability".
        if source.original_printing is None:
            source.original_printing = source.printing
        retained = source.original_printing.activated_abilities
        source.printing = _dc.replace(
            target.printing,
            activated_abilities=tuple(target.printing.activated_abilities)
            + tuple(retained),
        )
        state.log.append(
            f"{source.original_printing.name} becomes a copy of "
            f"{target.printing.name}"
        )

    def describe(self) -> str:
        return (
            "this land becomes a copy of target land, except it has "
            "this ability"
        )



@dataclass(frozen=True)
class CopyTargetInstantOrSorceryYouControl(Effect):
    """Mirrorpool mode 1: "Copy target instant or sorcery spell you
    control. You may choose new targets for the copy."

    Simplification: rather than pushing a real stack copy (which would
    require mid-resolution target selection — not supported by the
    engine's cast-time target pipeline), we short-circuit by re-
    resolving the target spell's ``spell_effect`` with freshly-chosen
    targets. Functionally equivalent for anything our engine models.
    Close enough for flavor; counterspell-proofing isn't modeled.
    """

    def requires_target(self) -> bool:
        return True

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        # Target key is the spell source's object id, NOT the stack
        # index — the cost-payment pipeline filters targets whose id
        # matches the ability source (``sacrifice_self``), so stack
        # indices (0, 1, …) would collide with low object ids.
        out: list[Target] = []
        for item in state.stack:
            if item.controller_id != controller_id:
                continue
            src = item.source
            if src is None:
                continue
            if not (src.printing.is_instant or src.printing.is_sorcery):
                continue
            out.append(("stack_spell", src.id))
        return out

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        if not targets:
            return
        kind, src_id = targets[0]
        if kind != "stack_spell":
            return
        item = next(
            (
                i for i in state.stack
                if i.source is not None and i.source.id == src_id
            ),
            None,
        )
        if item is None:
            return
        src = item.source
        if src is None:
            return
        spell_effect = src.printing.spell_effect
        if spell_effect is None:
            return
        # Choose fresh targets for the copy.
        copy_targets: tuple[Target, ...] = ()
        if spell_effect.requires_target():
            legal = spell_effect.legal_targets(state, controller_id)
            if legal:
                p = state.player_by_id(controller_id)
                if p.agent is not None:
                    chosen = p.agent.choose_target(
                        state, controller_id, legal
                    )
                    if chosen is not None:
                        copy_targets = (chosen,)
                if not copy_targets:
                    copy_targets = (legal[0],)
        state.log.append(
            f"Mirrorpool copies {src.printing.name}"
        )
        # Short-circuit: resolve the copy by re-running the spell
        # effect with the freshly-chosen target.
        prior = state.resolving_source
        state.resolving_source = src
        try:
            spell_effect.resolve(state, controller_id, copy_targets)
        finally:
            state.resolving_source = prior

    def describe(self) -> str:
        return (
            "copy target instant or sorcery spell you control; you may "
            "choose new targets for the copy"
        )



@dataclass(frozen=True)
class SacrificeNLandsYouControl(Effect):
    """Sacrifice ``count`` lands the effect's controller controls.

    Matches Lotus Field's "When this land enters, sacrifice two lands."
    Excludes the source (the ETB trigger is on the entering land
    itself, which is already on the battlefield at trigger time;
    oracle allows sac'ing the source in principle, but the engine
    never models that as a desirable choice).

    Simplification: the agent's choose_sacrifice picks; if the agent
    is None we pick the first ``count`` legal lands. If fewer than
    ``count`` legal lands exist, sacrifices all available.
    """

    count: int = 2

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.turn import sacrifice as _sacrifice

        source = state.resolving_source
        source_id = source.id if source is not None else -1
        p = state.player_by_id(controller_id)
        remaining = self.count
        while remaining > 0:
            options = [
                o for o in state.battlefield
                if o.controller_id == controller_id
                and o.printing.is_land
                and o.id != source_id
            ]
            if not options:
                break
            chosen = options[0]
            if p.agent is not None:
                pick_id = p.agent.choose_sacrifice(
                    state, controller_id, [o.id for o in options]
                )
                chosen = next(
                    (o for o in options if o.id == pick_id), options[0]
                )
            state.log.append(
                f"P{controller_id} sacrifices {chosen.printing.name} "
                f"(Lotus Field ETB)"
            )
            _sacrifice(state, chosen)
            remaining -= 1

    def describe(self) -> str:
        if self.count == 1:
            return "sacrifice a land"
        return f"sacrifice {self.count} lands"



@dataclass(frozen=True)
class PutBasicLandFromHandOntoBattlefieldTapped(Effect):
    """Terrain Generator's {2}, {T} activated: "You may put a basic
    land card from your hand onto the battlefield tapped."
    Simplification: "may" always yes when a basic is in hand.
    """

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.game import Zone
        from mtg_bot.turn import fire_landfall_triggers

        p = state.player_by_id(controller_id)
        basic = next(
            (
                c for c in p.hand
                if c.printing.is_land and "Basic" in c.printing.supertypes
            ),
            None,
        )
        if basic is None:
            return
        p.hand.remove(basic)
        basic.zone = Zone.BATTLEFIELD
        basic.controller_id = controller_id
        basic.tapped = True
        state.battlefield.append(basic)
        state.log.append(
            f"P{controller_id} puts {basic.printing.name} onto the "
            f"battlefield tapped (Terrain Generator)"
        )
        # ``fire_landfall_triggers`` covers both the legacy
        # string-key path and the predicate-style ENTERS dispatch.
        fire_landfall_triggers(state, basic)

    def describe(self) -> str:
        return (
            "you may put a basic land card from your hand onto the "
            "battlefield tapped"
        )



@dataclass(frozen=True)
class CounterTargetSpell(Effect):
    """Counter target spell on the stack.

    ``filter_types`` optionally restricts what card types can be
    countered (e.g., frozenset({"Artifact", "Enchantment"}) for Annul).
    Empty set means "any spell".

    Targets a stack item by its index via the new ``"stack"`` target kind.
    Triggered and activated abilities on the stack can't be countered by
    this effect (only spells — items where ``ability`` is None).

    Uncounterable spells are excluded from legal targets:
    - A spell whose printing has ``spell_is_uncounterable=True`` (e.g.
      Frenzied Baloth's "This spell can't be countered.").
    - A creature spell whose controller controls a permanent with a
      static ability carrying ``grants_creature_spells_uncounterable=True``
      (e.g. Frenzied Baloth on the battlefield granting the same
      protection to your other creature spells).

    CR 101.2: such spells can't be countered by spells or abilities.
    """

    filter_types: frozenset[str] = frozenset()

    def requires_target(self) -> bool:
        return True

    @staticmethod
    def _is_uncounterable(state: "GameState", item: "object") -> bool:
        """Return True if this stack item is immune to counter effects.

        Checks two sources of uncounterability:
        1. The spell's own printing carries ``spell_is_uncounterable``.
        2. The spell is a creature spell and the controller has a permanent
           on the battlefield with a static ability carrying
           ``grants_creature_spells_uncounterable``.
        """
        src = item.source.printing  # type: ignore[attr-defined]
        # Self-flag: "This spell can't be countered."
        if src.spell_is_uncounterable:
            return True
        # Battlefield static grant: "Creature spells you control can't be
        # countered." Only applies to creature spells.
        if "Creature" in src.card_types:
            spell_controller = item.controller_id  # type: ignore[attr-defined]
            for obj in state.battlefield:
                if obj.controller_id != spell_controller:
                    continue
                for sa in obj.printing.static_abilities:
                    if sa.grants_creature_spells_uncounterable:
                        return True
        return False

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        out: list[Target] = []
        for i, item in enumerate(state.stack):
            if item.ability is not None:
                continue  # not a spell
            if item.countered:
                continue
            if self._is_uncounterable(state, item):
                continue  # CR 101.2: can't be countered
            src = item.source.printing
            if self.filter_types:
                if not any(t in src.card_types for t in self.filter_types):
                    continue
            out.append(("stack", i))
        return out

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        if not targets:
            return
        kind, idx = targets[0]
        if kind != "stack":
            return
        if not (0 <= idx < len(state.stack)):
            return
        item = state.stack[idx]
        if item.ability is not None:
            return
        # Re-check uncounterability at resolve time (the spell may have
        # gained protection between targeting and resolution, e.g. a
        # Frenzied Baloth entering the battlefield in response).
        if self._is_uncounterable(state, item):
            state.log.append(
                f"counterspell fizzles: "
                f"{item.source.printing.name} can't be countered"
            )
            return
        item.countered = True
        state.log.append(
            f"counterspell: {item.source.printing.name} is countered"
        )

    def describe(self) -> str:
        if not self.filter_types:
            return "counter target spell"
        types = ", ".join(sorted(t.lower() for t in self.filter_types))
        return f"counter target {types} spell"



@dataclass(frozen=True)
class TakeExtraTurnAfterThisOne(Effect):
    """"Take an extra turn after this one."

    Appends the controller to ``state.extra_turn_queue``; the sim loop
    in simulate.simulate_game consumes the queue between turns. Matches
    Nexus of Fate's extra-turn clause.
    """

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        state.extra_turn_queue.append(controller_id)
        state.log.append(
            f"P{controller_id} is scheduled to take an extra turn"
        )

    def describe(self) -> str:
        return "take an extra turn after this one"



@dataclass(frozen=True)
class GainControlOfTargetSliverPermanently(Effect):
    """"Gain control of target Sliver. (This effect lasts indefinitely.)"

    Matches Sliver Overlord's second activated ability. Unlike temporary
    steal effects (Mutinous Massacre, Control-target-opponent), this
    one reassigns controller_id without scheduling a revert — it is
    not reset at cleanup. The Sliver becomes permanently the
    activator's.
    """

    def requires_target(self) -> bool:
        return True

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        return [
            ("creature", o.id)
            for o in state.battlefield
            if o.printing.is_creature
            and "Sliver" in _eff_subtypes(state, o)
        ]

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        if not targets:
            return
        kind, target_id = targets[0]
        if kind != "creature":
            return
        obj = next(
            (o for o in state.battlefield if o.id == target_id), None
        )
        if obj is None:
            return
        if "Sliver" not in _eff_subtypes(state, obj):
            return
        if obj.controller_id == controller_id:
            # Already yours — no change, but log for visibility.
            state.log.append(
                f"P{controller_id} targets own Sliver "
                f"{obj.printing.name} — no change"
            )
            return
        obj.controller_id = controller_id
        # Permanent gain of control: do NOT set temp_original_controller_id.
        state.log.append(
            f"P{controller_id} permanently gains control of "
            f"{obj.printing.name}"
        )

    def describe(self) -> str:
        return "gain control of target Sliver (indefinitely)"



@dataclass(frozen=True)
class PreventAllCombatDamageThisTurn(Effect):
    """"Prevent all combat damage that would be dealt this turn."

    Matches Darkness ({B} instant). Sets state-level flag consumed by
    ``combat._resolve_damage_step``; the flag is cleared at end-of-turn
    cleanup. Non-combat damage (direct damage, pings) is unaffected.
    """

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        state.prevent_combat_damage_this_turn = True
        state.log.append("all combat damage prevented this turn")

    def describe(self) -> str:
        return "prevent all combat damage that would be dealt this turn"



# DealDamage and its helpers moved earlier in the file (above
# DealDamageToTargetOpponent at line ~1620 in the pre-collapse
# layout) so the sugar subclasses can reference DealDamage at class-
# definition time. See the canonical DealDamage definition near the
# top of the module.



@dataclass(frozen=True)
class EachOpponentSacrificesCreature(Effect):
    """Each opponent sacrifices a nontoken creature of their choice.

    Each sacrificing player picks via their agent's ``choose_sacrifice``.
    If an opponent has no legal nontoken creature, they skip — no target
    required to match the standard MTG "of their choice" wording.
    """

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.turn import sacrifice as _sacrifice

        for p in state.players:
            if p.id == controller_id or p.has_lost:
                continue
            legal = [
                o for o in state.battlefield
                if o.controller_id == p.id
                and o.printing.is_creature
                and not o.printing.is_token
            ]
            if not legal or p.agent is None:
                continue
            chosen_id = p.agent.choose_sacrifice(
                state, p.id, [o.id for o in legal]
            )
            obj = next((o for o in legal if o.id == chosen_id), legal[0])
            state.log.append(f"P{p.id} sacrifices {obj.printing.name}")
            _sacrifice(state, obj)

    def describe(self) -> str:
        return "each opponent sacrifices a nontoken creature of their choice"



@dataclass(frozen=True)
class TargetOpponentSacrificesCreatureOtherThanEnchanted(Effect):
    """"Target opponent sacrifices a creature of their choice other
    than enchanted creature."

    Used by Sporogenic Infection's ETB. Identifies the source Aura's
    enchanted creature via ``state.resolving_source.attached_to`` and
    excludes it from the target's sac options. The target opponent
    picks via their own ``Agent.choose_sacrifice`` — same agent path
    ``EachOpponentSacrificesCreature`` rides.

    Simplification vs. printed ``target player``: targets are
    restricted to opponents only — the standard EoE / DSK ``target
    player`` simplification used by other Caster-controls-target
    effects in this codebase. Self-targeting is never strategically
    correct for the controller of an enchant-an-opponent's-creature
    Aura; narrowing legality doesn't affect rational play. The
    nontoken filter that ``EachOpponentSacrificesCreature`` ships is
    NOT applied here — the printed text says ``a creature of their
    choice``, not ``a nontoken creature``.
    """

    def requires_target(self) -> bool:
        return True

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        return [
            ("player", p.id) for p in state.players
            if p.id != controller_id and not p.has_lost
        ]

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.turn import sacrifice as _sacrifice

        if not targets:
            return
        kind, target_id = targets[0]
        if kind != "player":
            return
        target = state.player_by_id(target_id)
        if target.has_lost:
            return
        # Excluded id: the Aura's enchanted creature, if any. When the
        # Aura is enchanting a creature controlled by the target (the
        # usual case for Sporogenic Infection), the host is excluded
        # from the sac options. When the Aura is enchanting one of
        # the controller's own creatures, the target's own creatures
        # are unaffected by the exclusion (the host isn't theirs).
        aura = state.resolving_source
        excluded_id = aura.attached_to if aura is not None else None
        legal = [
            o for o in state.battlefield
            if o.controller_id == target_id
            and o.printing.is_creature
            and o.id != excluded_id
        ]
        if not legal or target.agent is None:
            return
        chosen_id = target.agent.choose_sacrifice(
            state, target_id, [o.id for o in legal]
        )
        obj = next((o for o in legal if o.id == chosen_id), legal[0])
        state.log.append(
            f"P{target_id} sacrifices {obj.printing.name} "
            f"(Sporogenic Infection)"
        )
        _sacrifice(state, obj)

    def describe(self) -> str:
        return (
            "target opponent sacrifices a creature of their choice "
            "other than enchanted creature"
        )



@dataclass(frozen=True)
class MagicalHackTextChangeEffect(Effect):
    """Magical Hack: 'Change the text of target spell or permanent
    by replacing all instances of one basic land type with another.'

    Implementation scope: targets a basic land on the battlefield.
    Picks the new basic land type via the controller's
    ``choose_mana_color`` callback, mapped W/U/B/R/G to
    Plains/Island/Swamp/Mountain/Forest. The OLD basic land type is
    derived automatically from the target's effective subtypes
    (basic lands typically have exactly one). Writes a layer-3
    ``"replace_basic_land_type"`` registry entry sourced by the
    resolving spell with ``params=(old, new)`` and
    ``expires_at=None`` — text changes persist indefinitely (CR
    612). The sorcery itself goes to graveyard, so the entry is
    never auto-dropped.

    Limitations: only handles basic-land-type substitution on basic
    lands. Real Magical Hack also rewrites rules text on non-basic
    permanents that mention basic land types (e.g., a creature with
    "Forestwalk"); this engine doesn't yet model landwalk so the
    extension is a no-op there.
    """

    def requires_target(self) -> bool:
        return True

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        return [
            ("permanent", o.id)
            for o in state.battlefield
            if o.printing.is_basic_land
        ]

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.game import (
            _BASIC_LAND_TYPE_TO_COLOR, effective_subtypes,
        )

        if not targets:
            return
        _, target_id = targets[0]
        target = next(
            (o for o in state.battlefield if o.id == target_id), None,
        )
        if target is None:
            return
        # Pick the OLD basic land type from the target's current
        # effective subtypes. Basic lands typically have exactly one
        # basic-land-type subtype.
        current_subs = effective_subtypes(state, target)
        old = next(
            (s for s in current_subs if s in _BASIC_LAND_TYPE_TO_COLOR),
            None,
        )
        if old is None:
            state.log.append(
                f"{target.printing.name} has no basic land type — "
                f"Magical Hack fizzles"
            )
            return
        # Pick the NEW basic land type via choose_mana_color, excluding
        # the OLD color (per Magical Hack: "ONE basic land type with
        # ANOTHER" implies they must differ).
        color_to_type = {
            v: k for k, v in _BASIC_LAND_TYPE_TO_COLOR.items()
        }
        old_color = _BASIC_LAND_TYPE_TO_COLOR[old]
        options = [c for c in ["W", "U", "B", "R", "G"] if c != old_color]
        chosen = state.players[controller_id].agent.choose_mana_color(
            state, controller_id, options,
        )
        new = color_to_type.get(chosen)
        if new is None or new == old:
            state.log.append(
                f"Magical Hack: invalid new basic land type, fizzling"
            )
            return
        src = state.resolving_source
        source_id = src.id if src is not None else target.id
        state.add_continuous_effect(
            source_id=source_id,
            layer=3,
            kind="replace_basic_land_type",
            target_id=target.id,
            params=(old, new),
            description=(
                f"Magical Hack rewrites {target.printing.name}: "
                f"{old} -> {new}"
            ),
        )
        state.log.append(
            f"Magical Hack rewrites {target.printing.name}: "
            f"{old} -> {new}"
        )

    def describe(self) -> str:
        return (
            "change the text of target spell or permanent by replacing "
            "all instances of one basic land type with another"
        )



@dataclass(frozen=True)
class SleightOfMindTextChangeEffect(Effect):
    """Sleight of Mind: 'Change the text of target spell or
    permanent by replacing all instances of one color word with
    another.' Layer 3 text-changing.

    Implementation scope: rewrites color words in
    ``protection_from_color`` on the target's printing. The OLD
    color is auto-derived from the target's current effective
    protection (the only color-word reference our engine
    currently models on permanents); the controller picks the NEW
    color via ``choose_mana_color``. Writes a layer-3
    ``"replace_color_word"`` registry entry sourced by the
    resolving spell with ``params=(old, new)`` and
    ``expires_at=None`` (text changes persist per CR 612).

    Limitations: doesn't rewrite color words inside other rules
    text (e.g., "Whenever a black creature ETBs, ..."). The engine
    doesn't have such color-keyed triggers in scope, so the
    extension is a no-op there.
    """

    def requires_target(self) -> bool:
        return True

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        # Permits any permanent on the battlefield. In practice
        # only the protection-from-color holders get observable
        # results; targeting elsewhere just writes a no-op entry.
        return [
            ("permanent", o.id) for o in state.battlefield
        ]

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.game import effective_protection_from_colors

        if not targets:
            return
        _, target_id = targets[0]
        target = next(
            (o for o in state.battlefield if o.id == target_id), None,
        )
        if target is None:
            return
        # Derive the OLD color from the target's current effective
        # protection set. If protection is empty or has multiple
        # colors, we can't unambiguously rewrite — fizzle.
        prot = effective_protection_from_colors(state, target)
        if len(prot) != 1:
            state.log.append(
                f"Sleight of Mind fizzles: {target.printing.name} "
                f"has no single color word to rewrite"
            )
            return
        (old,) = prot
        options = [c for c in ["W", "U", "B", "R", "G"] if c != old]
        chosen = state.players[controller_id].agent.choose_mana_color(
            state, controller_id, options,
        )
        if chosen not in options:
            state.log.append(
                f"Sleight of Mind fizzles: invalid new color choice"
            )
            return
        src = state.resolving_source
        source_id = src.id if src is not None else target.id
        state.add_continuous_effect(
            source_id=source_id,
            layer=3,
            kind="replace_color_word",
            target_id=target.id,
            params=(old, chosen),
            description=(
                f"Sleight of Mind rewrites {target.printing.name}: "
                f"{old} -> {chosen}"
            ),
        )
        state.log.append(
            f"Sleight of Mind rewrites {target.printing.name}: "
            f"{old} -> {chosen}"
        )

    def describe(self) -> str:
        return (
            "change the text of target spell or permanent by replacing "
            "all instances of one color word with another"
        )



@dataclass(frozen=True)
class CytoshapeBecomeCopyUEOT(Effect):
    """Cytoshape (Saviors of Kamigawa, simplified): "Until end of
    turn, target creature becomes a copy of another target
    creature." Layer 1 copy effect with ``expires_at="cleanup"``.

    The architectural payoff over Clone (which is permanent /
    ``expires_at=None``): the printing mutation must REVERT at
    cleanup. Wired via the new ``revert_printing_if_no_layer1_copies``
    helper called from ``run_cleanup_step`` after layer-1 entries
    expire.

    Demo simplifications:
    - Drops the real card's "Sacrifice a Spirit" cost.
    - Drops the "except it isn't a Spirit" rider on the resulting
      copy.
    - Activate-as-sorcery is moot because we ship as a sorcery
      directly.

    Two creature targets: slot 0 is the creature being changed;
    slot 1 is the source whose printing is copied. The two must
    differ ("another target creature") — fizzles if same.
    """

    def requires_target(self) -> bool:
        return True

    def target_count_range(self) -> tuple[int, int]:
        return (2, 2)

    def target_slot_kinds(self) -> tuple[str, ...]:
        return ("creature", "creature")

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        return [
            ("creature", o.id)
            for o in state.battlefield
            if o.printing.is_creature
        ]

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        if len(targets) < 2:
            return
        first_id = targets[0][1]
        second_id = targets[1][1]
        if first_id == second_id:
            state.log.append(
                "Cytoshape fizzles: targets must be different creatures"
            )
            return
        first = next(
            (o for o in state.battlefield if o.id == first_id), None,
        )
        second = next(
            (o for o in state.battlefield if o.id == second_id), None,
        )
        if first is None or second is None:
            return
        if first.original_printing is None:
            first.original_printing = first.printing
        copied_printing = second.printing
        first.printing = copied_printing
        src = state.resolving_source
        source_id = src.id if src is not None else first.id
        state.add_continuous_effect(
            source_id=source_id,
            layer=1,
            kind="is_copy",
            target_id=first.id,
            params=(copied_printing,),
            expires_at="cleanup",
            description=(
                f"{first.original_printing.name} becomes a copy of "
                f"{copied_printing.name} UEOT"
            ),
        )
        state.log.append(
            f"{first.original_printing.name} becomes a copy of "
            f"{copied_printing.name} until end of turn"
        )

    def describe(self) -> str:
        return (
            "until end of turn, target creature becomes a copy of "
            "another target creature"
        )



@dataclass(frozen=True)
class ScuttlemuttColorChangeUEOT(Effect):
    """Scuttlemutt: '{T}: Target creature becomes the color or colors
    of your choice until end of turn.' Layer 5 color-changing effect.

    Demo scope: picks exactly one color via ``choose_mana_color``.
    Real Scuttlemutt allows zero, one, or multiple colors; the demo
    keeps it to a single color since that's enough to exercise
    block legality with protection-from-color.

    Resolution writes a layer-5 ``"set_colors"`` registry entry
    sourced by Scuttlemutt with ``params=(frozenset({chosen}),)``
    and ``expires_at="cleanup"``. The entry REPLACES the target's
    color set (matching real-card "becomes" semantics, not
    "becomes ... in addition to"). At cleanup the entry is dropped
    via ``expire_continuous_effects("cleanup")`` and the target
    reverts to its printed colors.
    """

    def requires_target(self) -> bool:
        return True

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        return [
            ("creature", o.id)
            for o in state.battlefield
            if o.printing.is_creature
        ]

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        if not targets:
            return
        _, target_id = targets[0]
        target = next(
            (o for o in state.battlefield if o.id == target_id), None,
        )
        if target is None:
            return
        chosen = state.players[controller_id].agent.choose_mana_color(
            state, controller_id, ["W", "U", "B", "R", "G"],
        )
        if chosen not in ("W", "U", "B", "R", "G"):
            return
        src = state.resolving_source
        source_id = src.id if src is not None else target.id
        state.add_continuous_effect(
            source_id=source_id,
            layer=5,
            kind="set_colors",
            target_id=target.id,
            params=(frozenset({chosen}),),
            expires_at="cleanup",
            description=(
                f"{target.printing.name} becomes {chosen} until end "
                f"of turn"
            ),
        )
        state.log.append(
            f"{target.printing.name} becomes {chosen} until end of turn"
        )

    def describe(self) -> str:
        return (
            "target creature becomes the color of your choice until "
            "end of turn"
        )



@dataclass(frozen=True)
class LockOrUnlockDoorOfTargetRoomYouControl(Effect):
    """Keys to the House: "Lock or unlock a door of target Room you
    control. Activate only as a sorcery."

    Resolves on a target Room permanent the controller controls. The
    controller chooses one of the Room's two doors to toggle (via
    ``choose_target`` over the legal-target pool — Rooms — and then
    ``choose_mode`` over a per-Room ``["lock <X>", "unlock <X>", ...]``
    label list). The chosen half flips its membership in
    ``GameObject.unlocked_halves``: a locked half being unlocked is
    added to the set; an unlocked half being locked is removed.

    The ``Activate only as a sorcery.`` rider is honored at the
    activated-ability level (``sorcery_speed=True``), not in the
    effect; the effect itself is happy to resolve at any point.

    Unlike the printed ``UnlockRoomHalf`` action (sorcery-speed special
    action that pays the half's mana cost), this effect skips the cost
    payment — the controller's "Keys" sacrifice already paid for the
    privilege. The unlock side-effects (Eerie observers, etc.) follow
    the same path the action takes: the predicate-style ENTERS event
    on a half-name filter does NOT re-fire here because the engine
    layer's ``_unlock_room_half_with_triggers`` is the canonical entry
    point. We mirror its observable state change (modify
    ``unlocked_halves``) without re-firing the per-half on-unlock
    triggered abilities — keeps the effect surgical.
    """

    def requires_target(self) -> bool:
        return True

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        return [
            ("permanent", o.id)
            for o in state.battlefield
            if o.controller_id == controller_id
            and o.printing.is_room
        ]

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        if not targets:
            return
        kind, target_id = targets[0]
        if kind != "permanent":
            return
        obj = next(
            (o for o in state.battlefield if o.id == target_id), None
        )
        if obj is None or obj.controller_id != controller_id:
            return
        if not obj.printing.is_room:
            return
        # Build the choose_mode label list: one entry per door, each
        # pre-prefixed with "lock" or "unlock" depending on the door's
        # current state. The controller's pick maps directly to the
        # door name and the new state.
        labels: list[str] = []
        actions: list[tuple[str, str]] = []  # (door_name, "lock"/"unlock")
        for half in obj.printing.room_halves:
            if half.name in obj.unlocked_halves:
                labels.append(f"lock {half.name}")
                actions.append((half.name, "lock"))
            else:
                labels.append(f"unlock {half.name}")
                actions.append((half.name, "unlock"))
        if not labels:
            return
        p = state.player_by_id(controller_id)
        pick = 0
        if p.agent is not None:
            pick = p.agent.choose_mode(state, controller_id, labels)
            pick = max(0, min(pick, len(labels) - 1))
        door_name, op = actions[pick]
        if op == "unlock":
            obj.unlocked_halves = obj.unlocked_halves | {door_name}
            state.log.append(
                f"P{controller_id} unlocks {door_name} on "
                f"{obj.printing.name}"
            )
        else:
            obj.unlocked_halves = obj.unlocked_halves - {door_name}
            state.log.append(
                f"P{controller_id} locks {door_name} on "
                f"{obj.printing.name}"
            )

    def describe(self) -> str:
        return "lock or unlock a door of target Room you control"



# ---------------------------------------------------------------------------
# Threaten core (gain control + untap + grant haste UEOT, on a single target)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ShuffleZonesIntoLibrary(Effect):
    """Shuffle one or more of the controller's owned zones into their
    library, then re-shuffle the library.

    ``zones`` is a tuple of zone-name strings — recognized values are
    ``"hand"`` and ``"graveyard"``. Each card in those zones is moved
    to the library, ``Zone.LIBRARY`` is stamped on the card's zone
    field, and ``shuffle_library`` is called once at the end.

    Used by Weftwalking's ETB ("shuffle your hand and graveyard into
    your library, then draw seven cards") composed with ``DrawCards``
    in a ``Sequence``. Future printings (e.g. shuffle-just-graveyard
    or shuffle-just-hand variants) reuse the same primitive with a
    different ``zones`` tuple.
    """

    zones: tuple[str, ...] = ()

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.game import Zone, shuffle_library

        p = state.player_by_id(controller_id)
        moved = 0
        if "hand" in self.zones:
            for c in list(p.hand):
                c.zone = Zone.LIBRARY
                p.library.append(c)
                moved += 1
            p.hand.clear()
        if "graveyard" in self.zones:
            for c in list(p.graveyard):
                c.zone = Zone.LIBRARY
                p.library.append(c)
                moved += 1
            p.graveyard.clear()
        shuffle_library(state, controller_id)
        zone_phrase = " and ".join(self.zones) if self.zones else "(none)"
        state.log.append(
            f"P{controller_id} shuffles {moved} cards from "
            f"{zone_phrase} into their library"
        )

    def describe(self) -> str:
        if not self.zones:
            return "shuffle (no zones) into your library"
        zone_phrase = " and ".join(f"your {z}" for z in self.zones)
        return f"shuffle {zone_phrase} into your library"



@dataclass(frozen=True)
class DrawCardsByConditionMultiplier(Effect):
    """Draw X cards, where X is the ``multiplier`` of a structural
    ``Condition``.

    Generic primitive for the "draw X cards, where X is <count>" oracle
    shape. Reuses the existing ``Condition`` algebra (the same one
    ``CostReduction.condition`` uses): the resolve site reads
    ``condition.multiplier(state, controller_id)`` at fire time, which
    is the exact count semantics each ``Condition`` already encodes
    (``PerDifferentlyNamedLand`` counts distinctly-named lands the
    viewer controls, ``PerControlled`` counts permanents matching the
    inner ``ObjectPredicate``, etc.).

    The ``description`` argument is a short oracle-text fragment used
    by ``describe()`` so log output reads naturally — e.g. for
    ``PerDifferentlyNamedLand`` we want "draw X cards, where X is the
    number of differently named lands you control" rather than the
    generic ``Condition.__class__.__name__``. The fragment is parser-
    supplied (one per claimed phrase shape), keeping the runtime engine
    class oblivious to oracle-text wording while still producing
    readable logs.

    Replaces the bespoke ``AllFatesScrollDrawEffect`` for the
    differently-named-lands surface; reusable for any future "draw X
    where X is <Condition.multiplier>" printing without further engine
    work.
    """

    condition: "Condition"  # noqa: F821 - forward ref via TYPE_CHECKING
    description_fragment: str = "where X is determined at resolution"

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.turn import draw_n_cards

        x = self.condition.multiplier(state, controller_id)
        if x <= 0:
            state.log.append(
                f"P{controller_id} draws 0 cards "
                f"({self.description_fragment})"
            )
            return
        drawn = draw_n_cards(state, controller_id, x)
        state.log.append(
            f"P{controller_id} draws {drawn} cards "
            f"({self.description_fragment})"
        )

    def describe(self) -> str:
        return f"draw X cards, {self.description_fragment}"


@dataclass(frozen=True)
class EachOpponentExilesOwnCreature(Effect):
    """Per-opponent independent-choice primitive: each opponent chooses
    one creature they control and exiles it.

    Per-opponent loop walks each non-controller, non-eliminated player in
    turn order; their agent's ``choose_sacrifice`` hook (re-used as a
    "pick one of your battlefield creatures" prompt — same shape) selects
    the creature to exile. Opponents who control no creature, or whose
    agent is missing, are silently skipped (matching CR 700.2 "if a
    player can't make a choice, they don't").

    When ``link_to_source`` is True, each exiled object is tagged with
    ``exiled_by_source = state.resolving_source.id`` so a sibling ability
    on the same source can later locate "creature card exiled with it"
    (Sothera, the Supervoid's end-step recall pattern). When False the
    exile is a plain zone change with no source-link bookkeeping.

    Generic across the per-opponent-exile shape; Sothera is the only
    consumer in the EoE pool today, but a future card with the same
    "each opponent chooses a creature they control and exiles it" body
    (with or without source-link) reuses this primitive verbatim.
    """

    link_to_source: bool = False

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.turn import move_off_battlefield

        source = state.resolving_source
        # When the caller asked for source linkage but the resolving
        # source is missing, we'd silently drop the link — defensively
        # short-circuit so the failure is visible rather than producing
        # exiled-without-link cards that downstream effects can't find.
        if self.link_to_source and source is None:
            return
        for opp in state.players:
            if opp.id == controller_id or opp.has_lost:
                continue
            candidates = [
                o for o in state.battlefield
                if o.controller_id == opp.id and o.printing.is_creature
            ]
            if not candidates or opp.agent is None:
                continue
            pick_id = opp.agent.choose_sacrifice(
                state, opp.id, [o.id for o in candidates]
            )
            chosen = next(
                (o for o in candidates if o.id == pick_id), candidates[0]
            )
            if self.link_to_source and source is not None:
                chosen.exiled_by_source = source.id
                state.log.append(
                    f"P{opp.id} exiles {chosen.printing.name} "
                    f"({source.printing.name})"
                )
            else:
                state.log.append(
                    f"P{opp.id} exiles {chosen.printing.name}"
                )
            move_off_battlefield(state, chosen, destination="exile")

    def describe(self) -> str:
        return (
            "each opponent chooses a creature they control and exiles it"
        )


@dataclass(frozen=True)
class EachOpponentSacsOrDiscardsOrTakesSourcePowerDamage(Effect):
    """Per-opponent independent-choice primitive: each opponent picks
    among (sacrifice a nonland permanent, discard a card, decline);
    opponents who declined OR had no legal sac/discard option take damage
    equal to the source's effective power.

    The per-opponent loop walks each non-controller, non-eliminated
    player in turn order. The agent's ``choose_mode`` hook is presented
    only with the modes that are legal for that opponent at resolve time
    (sac is offered only when they control a nonland permanent; discard
    only when they have at least one card in hand; decline is always
    offered). Resolution branches:

    - **sac**: ``choose_sacrifice`` picks a victim from the legal nonland
      permanents, ``mtg_bot.turn.sacrifice`` fires the sac through the
      standard pipeline.
    - **discard**: ``choose_discard`` picks a hand card; the card moves
      to the graveyard and ``fire_opponent_discards_triggers`` fires.
    - **decline**: the opponent is recorded as non-compliant and takes
      damage at the end of the loop.

    A defensive missing-agent counts as decline (same as the bespoke
    behavior). The damage step uses ``_apply_damage`` so the source's
    lifelink keyword (Osseous Sticktwister has lifelink) interacts with
    the damage cleanly.

    Generic across the per-opponent three-mode shape with conditional
    damage to non-compliers; Osseous Sticktwister is the only EoE/DSK
    consumer today. A future card with a different damage formula
    (fixed N, source toughness, etc.) would parameterize this primitive
    via a callable amount-resolver.
    """

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.game import Zone, effective_power
        from mtg_bot.turn import (
            fire_opponent_discards_triggers, sacrifice as _sacrifice,
        )

        source = state.resolving_source
        if source is None:
            return
        non_compliant: list[int] = []
        for opp in state.players:
            if opp.id == controller_id or opp.has_lost:
                continue
            if opp.agent is None:
                # Defensive: a missing agent counts as decline.
                non_compliant.append(opp.id)
                continue
            sac_candidates = [
                o for o in state.battlefield
                if o.controller_id == opp.id
                and not o.printing.is_land
            ]
            modes: list[str] = []
            options: list[str] = []
            if sac_candidates:
                modes.append(
                    "sacrifice a nonland permanent of your choice"
                )
                options.append("sac")
            if opp.hand:
                modes.append("discard a card")
                options.append("discard")
            modes.append("decline (take damage)")
            options.append("decline")
            choice = opp.agent.choose_mode(state, opp.id, modes)
            choice = max(0, min(choice, len(modes) - 1))
            chosen_tag = options[choice]
            if chosen_tag == "sac":
                pick_id = opp.agent.choose_sacrifice(
                    state, opp.id, [o.id for o in sac_candidates],
                )
                chosen = next(
                    (o for o in sac_candidates if o.id == pick_id),
                    sac_candidates[0],
                )
                state.log.append(
                    f"P{opp.id} sacrifices {chosen.printing.name} "
                    f"({source.printing.name})"
                )
                _sacrifice(state, chosen)
            elif chosen_tag == "discard":
                hand_ids = [c.id for c in opp.hand]
                pick_id = opp.agent.choose_discard(
                    state, opp.id, hand_ids,
                )
                card = next(
                    (c for c in opp.hand if c.id == pick_id), None,
                )
                if card is not None:
                    opp.hand.remove(card)
                    card.zone = Zone.GRAVEYARD
                    opp.graveyard.append(card)
                    state.log.append(
                        f"P{opp.id} discards {card.printing.name} "
                        f"({source.printing.name})"
                    )
                    fire_opponent_discards_triggers(state, opp.id)
            else:
                non_compliant.append(opp.id)
        if not non_compliant:
            return
        damage = max(0, effective_power(state, source))
        if damage <= 0:
            return
        for opp_id in non_compliant:
            _apply_damage(state, ("player", opp_id), damage)
            state.log.append(
                f"{source.printing.name} deals {damage} to P{opp_id}"
            )

    def describe(self) -> str:
        return (
            "each opponent may sacrifice a nonland permanent or discard "
            "a card; this creature deals damage equal to its power to "
            "each opponent who did neither"
        )


# ---------------------------------------------------------------------------
# Paired-target opposite-polarity pump/debuff (audit-monoist-chorale).
#
# Models a single resolving effect that picks TWO distinct creature
# targets — one matching ``positive_kind`` (e.g. ``"my_creature"``) and
# one matching ``negative_kind`` (e.g. ``"creature"`` for an opponent's
# creature) — and grants opposite UEOT P/T deltas keyed off a shared X
# computed at resolve time from a ``Formula``.
#
# Why not a ``Sequence``: the engine's ``Sequence`` combinator restricts
# itself to a SINGLE targeting sub-effect by design (the cast-time
# target-selection pipeline picks one target prompt per cast).
# Two-target paired-polarity bodies (Monoist Circuit-Feeder) need both
# slots filled atomically, with a shared X, in one trigger firing —
# decomposing into ``Sequence(PumpYourCreature, DebuffOppCreature)``
# would either double-prompt the targeting pipeline (illegal) or drop
# one of the targets (silent no-op, forbidden).
#
# Future direction (Option B in the audit notes): extend the
# ``Effect.targets`` grammar to declare ``targets: tuple[TargetSpec,
# ...]`` with multiple slots and wire the cast/activation pipeline to
# ask the agent for one target per slot. That refactor unblocks
# multi-target spells generally; until then this primitive is the
# contained "ship-now" answer for the paired-polarity shape.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Reanimate from defending player's graveyard, tapped + attacking
# (audit-monoist-chorale).
#
# Models the Chorale of the Void attacks-trigger reanimate body:
# "put target creature card from defending player's graveyard onto the
# battlefield under your control tapped and attacking".
#
# 2-player simplification: legal targets = any creature card in any
# opponent's graveyard. The engine's combat model doesn't thread the
# per-attacker defending-player identity into a slot the resolving
# effect can read, so the multi-defender / multiplayer / planeswalker-
# defender variants degrade to "any opponent's graveyard" — matching
# the printed text exactly in 2-player and approximating it elsewhere.
# When the engine grows a per-attacker defending-player slot, this
# primitive will read it; the public API doesn't need to change.
#
# The reanimated card enters tapped AND attacking. Combat-state
# bookkeeping marks the card ``attacking=True`` and clears
# ``summoning_sick`` so it's a "real" attacker for the rest of the
# combat phase. The engine's combat damage path reads
# ``obj.attacking`` and applies damage to the defending player by id
# (via the ``defending_player_id`` argument threaded from
# ``resolve_combat_damage``); the engine doesn't carry a
# per-attacker defender slot today, so the new attacker rides the
# combat phase's single defender id implicitly.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReanimateTargetCreatureCardFromDefendersGraveyard(Effect):
    """Put target creature card from a defending player's graveyard
    onto the battlefield under the resolving controller's control,
    tapped and attacking.

    Used by Chorale of the Void's attacks trigger: the source aura's
    enchanted creature attacks, and the trigger reanimates a creature
    card from the defending player's graveyard, on the active player's
    side, already attacking.

    Target kind: ``("graveyard_creature", id)``. The legal-target pool
    is the union of every opponent's graveyard creature cards. In
    2-player mode this matches the printed "defending player" exactly
    because the resolving controller has only one opponent; in
    multiplayer / planeswalker-defender cases this is an approximation
    until the engine threads per-attacker defender identity into a
    state slot the effect can read.

    Resolve semantics:

    1. Locate the chosen card in any opponent's graveyard; remove it.
    2. ``put_into_battlefield`` brings it on under the resolving
       controller's id (CR 405.5: "under your control" — the ETB is
       the new permanent's first ETB under that controller).
    3. ``obj.tapped = True``, ``obj.attacking = True``,
       ``obj.summoning_sick = False`` so the new permanent is a
       legal attacker for the in-progress combat phase. The engine's
       combat damage path reads ``obj.attacking`` and the defending
       player id from the calling combat phase (single-defender
       semantics; the new attacker rides the same defender as the
       triggering attacker).
    """

    def requires_target(self) -> bool:
        return True

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        return [
            ("graveyard_creature", c.id)
            for p in state.players
            if p.id != controller_id
            for c in p.graveyard
            if c.printing.is_creature
        ]

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.actions import put_into_battlefield

        if not targets:
            return
        kind, target_id = targets[0]
        if kind != "graveyard_creature":
            return
        for p in state.players:
            card = next(
                (c for c in p.graveyard if c.id == target_id), None,
            )
            if card is None:
                continue
            p.graveyard.remove(card)
            state.log.append(
                f"{card.printing.name} returns from P{p.id}'s graveyard "
                f"under P{controller_id} tapped and attacking"
            )
            put_into_battlefield(state, card, controller_id)
            card.tapped = True
            card.attacking = True
            card.summoning_sick = False
            return

    def describe(self) -> str:
        return (
            "put target creature card from defending player's "
            "graveyard onto the battlefield under your control tapped "
            "and attacking"
        )


@dataclass(frozen=True)
class BecomeType(Effect):
    """Source gains the listed card-types and/or subtypes, optionally with
    a new base P/T, IN ADDITION TO ITS OTHER TYPES.

    Always writes registry entries with ``expires_at=None`` (the entry
    persists until the source leaves play). Wrap with
    ``ApplyEffect(BecomeType(...), ends_at=<Duration>)`` to give the
    change a finite lifetime — ``ApplyEffect`` rewrites the lifetime
    fields of every entry written here.

    Registry writes (each gated on its parameter being non-empty):

      - For each entry in ``types_to_add``: layer 4 ``add_type``. When
        the type is ``"creature"``, also flips the
        ``GameObject.permanent_is_creature`` write-through cache that
        ``is_creature_now`` reads. ``run_cleanup_step`` rebuilds the
        cache from the registry after expiring cleanup-scoped entries,
        so an ``ApplyEffect``-wrapped ``BecomeType`` with a finite
        duration correctly reverts the cache when its entry expires.
      - For each entry in ``subtypes_to_add``: layer 4 ``add_subtype``.
        Read by ``effective_subtypes`` walking the registry, so any
        duration is faithfully respected.
      - When ``base_pt`` is set: layer 7 sublayer 1 ``set_base_pt``.
        Read by ``_compute_effective_pt`` via
        ``_registry_set_base_pt``, so any duration is faithfully
        respected.

    Target selection: when ``targets`` carries a ``(kind, id)`` pair,
    the registry entries target that object — the spell/ability source
    (``state.resolving_source``) is still recorded as the
    registry-entry ``source_id``, so the entry is dropped when the
    spell/ability source leaves play. With no targets, the effect
    falls back to self-target (Haunted Screen, manland animation):
    both ``source_id`` and ``target_id`` are
    ``state.resolving_source.id``.

    No-op when neither ``targets`` nor ``state.resolving_source``
    yields a battlefield object.
    """

    types_to_add: tuple[str, ...] = ()
    subtypes_to_add: tuple[str, ...] = ()
    base_pt: "tuple[int, int] | None" = None

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        source = state.resolving_source
        if targets:
            _, target_id = targets[0]
            target = next(
                (o for o in state.battlefield if o.id == target_id), None
            )
        else:
            target = source
        if target is None:
            return
        # Registry ``source_id`` = the spell/ability source (so its
        # leave-play drops the entry); falls back to the target itself
        # for self-target callers that resolve outside a stack frame.
        source_id = source.id if source is not None else target.id
        for type_name in self.types_to_add:
            state.add_continuous_effect(
                source_id=source_id, layer=4, kind="add_type",
                target_id=target.id, params=(type_name,),
                expires_at=None,
                description=(
                    f"{target.printing.name} becomes a {type_name}"
                ),
            )
            if type_name.lower() == "creature":
                target.permanent_is_creature = True
        for subtype in self.subtypes_to_add:
            state.add_continuous_effect(
                source_id=source_id, layer=4, kind="add_subtype",
                target_id=target.id, params=(subtype,),
                expires_at=None,
                description=(
                    f"{target.printing.name} becomes a {subtype}"
                ),
            )
        if self.base_pt is not None:
            base_p, base_t = self.base_pt
            state.add_continuous_effect(
                source_id=source_id, layer=7, sublayer=1,
                kind="set_base_pt",
                target_id=target.id, params=(base_p, base_t),
                expires_at=None,
                description=(
                    f"{target.printing.name} base {base_p}/{base_t}"
                ),
            )
        state.log.append(
            f"{target.printing.name} {self.describe()}"
        )

    def describe(self) -> str:
        parts: list[str] = []
        if self.base_pt is not None:
            parts.append(f"becomes a {self.base_pt[0]}/{self.base_pt[1]}")
        else:
            parts.append("becomes")
        if self.subtypes_to_add:
            parts.append(" ".join(self.subtypes_to_add))
        if self.types_to_add:
            parts.append(" ".join(self.types_to_add))
        body = " ".join(parts)
        return f"{body} in addition to its other types"



from mtg_bot.effects.generic.targets_helpers import (
    _eff_subtypes,
    _slot_target_still_legal,
    _fizzle_message,
    _describe_targets,
    _describe_filter,
    _bounce_to_hand,
)

from mtg_bot.effects.generic.damage import (
    DealDamage,
    DealDamageToTargetOpponent,
    DealDamageEachOpponent,
    DealNDamageToEachCreature,
    DealDamageToControllerAndAddMana,
    DealDamageEqualToSourcePowerAnyTarget,
    DealDamageAnyTarget,
    DealDamageToTargetCreature,
    DealDamageToTargetCreatureWithExcessLanderRider,
    DealDamageToOpponentCreatureByArtifactCount,
    DealDamageToOpponentCreatureByCardsInHand,
    DealDamageToTargetCreatureSpacecraftBoosted,
    DealDamageToOpponentCreature,
    DealDamageToTargetTappedCreature,
    MayHaveSourceDealDamageToTarget,
    DrawCardsAndLoseLifeEqualToResolvingDamage,
)

from mtg_bot.effects.generic.grant_keywords import (
    GrantUnblockable,
    GrantUnblockableUEOT,
    GrantTriggeredAbilityUEOT,
    GrantKeywords,
    GrantActivatedAbility,
    GrantTriggeredAbility,
)

from mtg_bot.effects.generic.pump import (
    Pump,
    PumpTargetOtherCreatureByXOverXWhereXIsSourcePower,
    DoubleTargetCreaturesPowerUEOT,
    PumpTargetCreatureUntilEOT,
    SetBasePTUntilEOT,
    SetBasePTConditionalUntilEOT,
    PumpSelfUntilEOT,
    PumpCreaturesYouControlUntilEOT,
    PumpCreaturesOpponentsControlUntilEOT,
    PumpSelfXPowerUEOT,
    SwitchSourcePowerToughnessUEOT,
    PumpTargetArtifactOrCreatureUntilEOT,
    ThreatenTargetCreatureUEOT,
    _signed,
    PairedTargetPumpDebuffUEOT,
)

from mtg_bot.effects.generic.counters import (
    PutPlusOneCounters,
    PutPlusOneCountersOnEachCreatureYouControlEqualToSourcePower,
    PutPlusOneCounterOnEachOfUpToNTargetCreatures,
    PutPlusOneCounterOnTargetCreature,
    PutPlusOneCountersAndGrantKeywordsUEOTOnTargetCreatureYouControl,
    PutPlusOneCounterOnEachCreatureYouControl,
    PutPlusOneCounterOnSelf,
    PutPlusOneCounterOnOpponentsCreature,
    PutPlusOneCounterOnCreatureYouControl,
    PutPlusOneCountersOnSelfPerOtherCreatureOrArtifact,
    PutChargeCountersOnTargetSpacecraftYouControl,
    PutChargeCountersOnTargetSpacecraftOrPlanetYouControl,
    PutChargeCountersOnSelf,
    PutPoisonCountersOnTargetPlayer,
    PutStunCounterOnTappedCreature,
    PutLoyaltyCounterOnSelf,
    MoveSelfCountersToTargetCreatureYouControl,
    MovePlusOneCounterBetweenPermanentsYouControl,
)

from mtg_bot.effects.generic.destroy import (
    Destroy,
    DestroyTargetCreature,
    DestroyEnchantedPermanent,
    DestroyTargetArtifact,
    DestroyTargetNoncreaturePermanent,
    DestroyTargetLand,
    DestroyTargetNonlandPermanent,
    DestroyUpToOneTargetNonlandPermanent,
    RegenerateTargetCreature,
    DestroyEachNonlandPermanentWithMVEqualToSourceChargeCounters,
    DestroyTargetArtifactOrTappedCreature,
    DestroyTargetArtifactEnchantmentOrFlyingCreature,
    DestroyAllCreatures,
    DestroyTargetNonlandPermanentWithLanderForController,
)

from mtg_bot.effects.generic.tap import (
    Tap,
    UntapTargetLand,
    IfGainedLifeThisTurnUntapSelf,
    TapTargetOpponentPermanentAndStunIt,
    TapAndStunUpToOneTargetCreature,
    TapAnotherTargetCreature,
    TapUpToOneTargetCreature,
    TapTargetArtifactOrCreature,
    UntapTargetOtherPermanent,
    PhaseOutEquippedCreature,
    TapEnchantedPermanent,
)

from mtg_bot.effects.generic.exile import (
    Exile,
    ExileTargetCreatureUntilSourceLeaves,
    ExileOpponentsNonlandPermanentUntilLeaves,
    ExileTargetCreature,
    ExileTargetCreatureWithPowerOrToughnessAtMost,
    ExileTargetCardFromGraveyard,
    ExileTargetAttackingCreatureUntilEndStep,
    ExileEachOpponentsGraveyard,
    ExileAllGraveyards,
    ExileAllArtifactsWithManaValueAtMost,
    ExileAllCreaturesAndSpacecraft,
    ExileTopOfLibraryMayPlayThisTurn,
    ExileTopXOfLibraryMayPlayThisTurn,
    ExileAllMatchingUntilSourceLeaves,
    WarpExileSelf,
    ReturnExiledPermanentToOwnerTapped,
    MoveEachExiledWithSourceToOwnersGraveyard,
    CreateNTokensFromLastExileRecall,
    PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYourControl,
    ReanimateOneExiledWithSourceWithCounters,
    SacrificeSelf,
    SacrificeSelfPreservingExileLink,
)

from mtg_bot.effects.generic.bounce import (
    Bounce,
    ReturnTargetCreatureToOwnersHand,
    ReturnTargetPermanentYouControlToOwnersHand,
    ReturnUpToNTargetCreaturesToOwnersHands,
    ReturnTargetArtifactCardFromYourGraveyardToHand,
    ReturnCreatureFromYourGraveyardToHand,
    ReturnUpToNCreaturesFromYourGraveyardToHand,
    ReturnUpToNNonlandPermanentCardsFromGraveyardToHand,
    ReturnTargetLandFromGraveyardToHand,
    ReturnUpToNSmallCreaturesFromGraveyardWithCounters,
)

from mtg_bot.effects.generic.delayed_actions import (
    SacrificeSourceDelayed,
    ScheduleSelfSacAtNextEndStep,
    RemoveChargeCountersFromSourceDelayed,
)

from mtg_bot.effects.generic.tokens import (
    CreateLanderAndScheduleSacrifice,
    CreateTokenAndAttachSelf,
    CreateTokenPerMulticoloredPermanent,
    CreateToken,
    CreateTokenCopyOfTargetCreatureYouControl,
    CreateXTokensOfTargetPermanentWithHasteEndStepSac,
)

from mtg_bot.effects.generic.mana import (
    AddManaToPool,
    AddNManaOfChosenColor,
    AddChargeCounterManaOfChosenColor,
    AddOneManaFromControlledLandsProductions,
    AddOneManaOfChosenPermanentColor,
)

from mtg_bot.effects.generic.search import (
    SearchLibraryForCard,
    SearchLibraryForBasicLandTapped,
    SearchLibraryForEquipmentToBattlefield,
    SearchLibraryForGreenCreatureWithMVAtMostX,
)

from mtg_bot.effects.generic.library_lookat import (
    LookAtTopNRevealOrCounter,
    LookAtTopTwoSplitHandGraveyard,
    LookTopNPutOneInHandRestToGraveyard,
    PeekTopMayBattlefieldIfLandElseHand,
    ManifestDread,
    ManifestDreadThenPutPlusOneCountersOnIt,
    ManifestDreadThenAttachSelf,
    Surveil,
    SelfMill,
)

from mtg_bot.effects.generic.life import (
    GainLife,
    SetLifeToHalfStartingRoundedUp,
    TargetPlayerLosesLife,
    EachOpponentDiscardsOrLosesLife,
    LoseLife,
    EachOpponentLosesLife,
    TargetOpponentLosesNYouGainN,
    TargetOpponentLosesLife,
    GrantLifeToEachOpponent,
    DefendingPlayerLosesHalfLifeRoundedUp,
)

from mtg_bot.effects.generic.discard import (
    DiscardSelf,
    DiscardHandThenDrawN,
    EachOpponentDiscards,
    EachOpponentExilesCardFromHandWithCastPermission,
    TargetOpponentDiscardsCasterChoice,
    TargetOpponentLookHandMayDiscard,
    TargetOpponentDiscards,
)
