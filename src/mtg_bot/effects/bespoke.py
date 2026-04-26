"""Card-specific one-off effects.

Each class here encodes the unique behavior of a single EoE card (ETB
triggers, attack triggers, activated abilities, end-step reanimations,
etc.). When a mechanic becomes reusable across cards, extract it to
``generic.py`` instead.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from mtg_bot.effects.base import (
    Effect, Target,
    _apply_damage, _multicolored_permanents_count,
    _find_moonlit_replacement_source,
)

if TYPE_CHECKING:
    from mtg_bot.cards import ManaCost
    from mtg_bot.game import GameState


@dataclass(frozen=True)
class AstelliReclaimerETBEffect(Effect):
    """Astelli Reclaimer's ETB: "Return target noncreature, nonland
    permanent card with mana value X or less from your graveyard to
    the battlefield, where X is the amount of mana spent to cast this
    creature."

    X is computed from the resolving source's paid cost: warp cost if
    cast_via_warp is set (for warp = {2}{W} → X = 3), otherwise the
    printed mana cost's total (for {3}{W}{W} → X = 5).
    """

    def requires_target(self) -> bool:
        return True

    def _x_from_source(self, state: "GameState") -> int:
        source = state.resolving_source
        if source is None:
            return 0
        if source.cast_via_warp and source.printing.warp_cost is not None:
            return source.printing.warp_cost.total
        return source.printing.mana_cost.total

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        x = self._x_from_source(state)
        p = state.player_by_id(controller_id)
        return [
            ("graveyard_permanent", c.id)
            for c in p.graveyard
            if c.printing.is_permanent
            and not c.printing.is_creature
            and not c.printing.is_land
            and c.printing.mana_cost.total <= x
        ]

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.actions import put_into_battlefield

        if not targets:
            return
        kind, target_id = targets[0]
        if kind != "graveyard_permanent":
            return
        p = state.player_by_id(controller_id)
        card = next((c for c in p.graveyard if c.id == target_id), None)
        if card is None:
            return
        p.graveyard.remove(card)
        state.log.append(
            f"{card.printing.name} returns from P{controller_id}'s "
            f"graveyard to the battlefield (Astelli Reclaimer)"
        )
        put_into_battlefield(state, card, controller_id)

    def describe(self) -> str:
        return (
            "return target noncreature, nonland permanent card with "
            "mana value X or less from your graveyard to the "
            "battlefield, where X is the mana spent to cast this"
        )



@dataclass(frozen=True)
class FamishedWorldsireETBEffect(Effect):
    """Famished Worldsire's ETB: "Look at the top X cards of your
    library, where X is this creature's power. Put any number of land
    cards from among them onto the battlefield tapped, then shuffle."

    Reads state.resolving_source to compute X from the source's
    effective power (post-Devour counters). Picks all land cards from
    the top-X (a strong simplification — the oracle allows choosing
    "any number", but greedy land-picking is strictly ramp-positive).
    Non-land cards go back into the library (bottom, random order).
    """

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.game import Zone, effective_power
        from mtg_bot.turn import fire_landfall_triggers

        source = state.resolving_source
        if source is None:
            return
        x = effective_power(state, source)
        if x <= 0:
            return
        p = state.player_by_id(controller_id)
        examined = p.library[:x]
        lands = [c for c in examined if c.printing.is_land]
        rest = [c for c in examined if c not in lands]
        for land in lands:
            p.library.remove(land)
            land.zone = Zone.BATTLEFIELD
            land.tapped = True
            land.controller_id = controller_id
            state.battlefield.append(land)
            state.log.append(
                f"P{controller_id} puts {land.printing.name} onto the "
                f"battlefield tapped (Famished Worldsire)"
            )
            fire_landfall_triggers(state, land)
        # Shuffle what's left (rest goes back where it was, then the
        # whole library is shuffled per oracle).
        from mtg_bot.game import shuffle_library
        shuffle_library(state, controller_id)

    def describe(self) -> str:
        return (
            "look at the top X cards of your library, where X is this "
            "creature's power; put any number of land cards from among "
            "them onto the battlefield tapped, then shuffle"
        )



@dataclass(frozen=True)
class TannukEnsignLandfallEffect(Effect):
    """Tannuk, Memorial Ensign's landfall: "Tannuk deals 1 damage to
    each opponent. If this is the second time this ability has
    resolved this turn, draw a card."

    Tracks resolutions per source in state.ability_resolutions_this_turn
    (reset at cleanup). The draw fires only on the exact 2nd resolution
    this turn; 3rd, 4th, etc. get the damage but not the draw.
    """

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        source = state.resolving_source
        # Damage each opponent 1 (log even without a source).
        for p in state.players:
            if p.id == controller_id or p.has_lost:
                continue
            p.life -= 1
            state.log.append(
                f"Tannuk deals 1 to P{p.id} (life: {p.life})"
            )
        if source is None:
            return
        key = ("tannuk_landfall", source.id)
        count = state.ability_resolutions_this_turn.get(key, 0) + 1
        state.ability_resolutions_this_turn[key] = count
        if count == 2:
            from mtg_bot.turn import draw_n_cards

            draw_n_cards(state, controller_id, 1)
            state.log.append(
                f"Tannuk landfall second-time bonus: P{controller_id} "
                f"draws a card"
            )

    def describe(self) -> str:
        return (
            "Tannuk deals 1 damage to each opponent; if this is the "
            "second time this ability has resolved this turn, draw a "
            "card"
        )



@dataclass(frozen=True)
class SelfcraftMechanETBEffect(Effect):
    """Selfcraft Mechan's ETB: "You may sacrifice an artifact. When you
    do, put a +1/+1 counter on target creature and draw a card."

    The "may" is exposed via ``agent.choose_yes_no`` — if the controller
    declines (or has no artifact), the entire reflexive rider does
    nothing: no sacrifice, no counter, no draw. Target creature is
    selected via the agent's ``choose_target`` before resolve (via the
    standard target-selection pipeline).
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
        from mtg_bot.turn import draw_n_cards, sacrifice as _sacrifice

        p = state.player_by_id(controller_id)
        artifacts = [
            o for o in state.battlefield
            if o.controller_id == controller_id and o.printing.is_artifact
        ]
        if not artifacts:
            state.log.append(
                f"Selfcraft Mechan: no artifact to sacrifice — fizzles"
            )
            return
        # Optional "may sacrifice an artifact" — controller decides.
        if p.agent is not None and not p.agent.choose_yes_no(
            state, controller_id, "Sacrifice an artifact?"
        ):
            state.log.append(
                f"P{controller_id} declines to sacrifice an artifact "
                f"(Selfcraft Mechan)"
            )
            return
        # Agent picks which artifact to sacrifice.
        if p.agent is not None:
            pick_id = p.agent.choose_sacrifice(
                state, controller_id, [o.id for o in artifacts]
            )
            chosen = next(
                (o for o in artifacts if o.id == pick_id), artifacts[0]
            )
        else:
            chosen = artifacts[0]
        state.log.append(
            f"P{controller_id} sacrifices {chosen.printing.name} "
            f"(Selfcraft Mechan)"
        )
        _sacrifice(state, chosen)
        # Apply counter to chosen target creature (if still on battlefield).
        if targets:
            kind, tid = targets[0]
            if kind == "creature":
                tgt = next(
                    (o for o in state.battlefield if o.id == tid), None
                )
                if tgt is not None:
                    from mtg_bot.game import add_plus_one_counters
                    add_plus_one_counters(state, tgt, 1)
                    state.log.append(
                        f"+1/+1 counter on {tgt.printing.name} "
                        f"(now {tgt.plus_one_counters})"
                    )
        # Draw a card either way — the sacrifice happened, so the
        # reflexive trigger's effect resolves fully.
        draw_n_cards(state, controller_id, 1)

    def describe(self) -> str:
        return (
            "you may sacrifice an artifact; if you do, put a +1/+1 "
            "counter on target creature and draw a card"
        )



@dataclass(frozen=True)
class SotheraExileOpponentCreatureEffect(Effect):
    """Sothera's dies-observer: "Each opponent chooses a creature they
    control and exiles it." Uses the source's id for exiled_by_source
    bookkeeping so Sothera's end-step reanimate can find them.

    Simplification: engine uses the generic your_creature_or_artifact
    _dies observer, which also fires for artifact deaths — slightly
    wider than oracle's "creature you control".
    """

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.turn import move_off_battlefield

        source = state.resolving_source
        if source is None:
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
            chosen.exiled_by_source = source.id
            state.log.append(
                f"P{opp.id} exiles {chosen.printing.name} "
                f"(Sothera, the Supervoid)"
            )
            move_off_battlefield(state, chosen, destination="exile")

    def describe(self) -> str:
        return (
            "each opponent chooses a creature they control and exiles it"
        )



@dataclass(frozen=True)
class SotheraEndStepReanimateEffect(Effect):
    """Sothera's end-step: "If a player controls no creatures, sacrifice
    Sothera, then put a creature card exiled with it onto the
    battlefield under your control with two additional +1/+1 counters
    on it."
    """

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.actions import put_into_battlefield
        from mtg_bot.game import Zone, add_plus_one_counters
        from mtg_bot.turn import sacrifice as _sacrifice

        source = state.resolving_source
        if source is None:
            return
        # Gate: does any player control zero creatures?
        any_empty = any(
            not [
                o for o in state.battlefield
                if o.controller_id == p.id and o.printing.is_creature
            ]
            for p in state.players
            if not p.has_lost
        )
        if not any_empty:
            return
        # Find a creature card exiled by this Sothera, and pull it out
        # of exile BEFORE sacrificing Sothera — the release-on-leave
        # hook would otherwise auto-return it to the owner's bf.
        exiled_creature = None
        owner = None
        for p in state.players:
            for c in p.exile:
                if (
                    c.exiled_by_source == source.id
                    and c.printing.is_creature
                ):
                    exiled_creature = c
                    owner = p
                    break
            if exiled_creature is not None:
                break
        if exiled_creature is not None and owner is not None:
            owner.exile.remove(exiled_creature)
            exiled_creature.exiled_by_source = None
        _sacrifice(state, source)
        if exiled_creature is None:
            return
        state.log.append(
            f"Sothera puts {exiled_creature.printing.name} onto the "
            f"battlefield under P{controller_id}'s control"
        )
        put_into_battlefield(state, exiled_creature, controller_id)
        add_plus_one_counters(state, exiled_creature, 2)

    def describe(self) -> str:
        return (
            "if a player controls no creatures, sacrifice Sothera, "
            "then put a creature card exiled with it onto the "
            "battlefield under your control with two +1/+1 counters"
        )



@dataclass(frozen=True)
class TerritorialBruntarLandfallEffect(Effect):
    """Territorial Bruntar's landfall: "Exile cards from the top of
    your library until you exile a nonland card. You may cast that
    card this turn."

    Any lands revealed during the process stay exiled — the oracle
    doesn't specify returning them, just exiles until non-land. We
    mark the non-land with playable_from_exile_this_turn so
    legal_actions will surface a CastSpell for it.
    """

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.game import Zone

        p = state.player_by_id(controller_id)
        while p.library:
            top = p.library.pop(0)
            top.zone = Zone.EXILE
            p.exile.append(top)
            state.log.append(
                f"P{controller_id} exiles {top.printing.name} (Bruntar)"
            )
            if not top.printing.is_land:
                top.playable_from_exile_this_turn = True
                state.log.append(
                    f"{top.printing.name} may be cast this turn"
                )
                return

    def describe(self) -> str:
        return (
            "exile cards from the top of your library until you exile "
            "a nonland card; you may cast that card this turn"
        )



@dataclass(frozen=True)
class MemorialVaultActivatedEffect(Effect):
    """Memorial Vault's activated effect: "Exile the top X cards of
    your library, where X is one plus the mana value of the sacrificed
    artifact. You may play those cards this turn."

    The ``sacrifice_another_artifact`` ActivationCost (artifact-only
    filter) pays the cost, so the most-recently-graveyarded artifact
    in the controller's graveyard at resolution time is exactly the
    one we just sacrificed. X = 1 + that artifact's mana value. The
    cost gate guarantees an artifact is present; the X=1 fallback only
    matters if defensive code is ever called without the cost paid.
    """

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.game import Zone

        # X reads the most-recently-graveyarded artifact's mana value.
        # Cost payment runs immediately before resolve, so this is the
        # artifact we just sacrificed.
        p = state.player_by_id(controller_id)
        x = 1
        for c in reversed(p.graveyard):
            if c.printing.is_artifact:
                x = 1 + c.printing.mana_cost.total
                break
        exiled_names = []
        for _ in range(x):
            if not p.library:
                break
            top = p.library.pop(0)
            top.zone = Zone.EXILE
            top.playable_from_exile_this_turn = True
            p.exile.append(top)
            exiled_names.append(top.printing.name)
        state.log.append(
            f"Memorial Vault exiles {len(exiled_names)} cards "
            f"(may play this turn)"
        )

    def describe(self) -> str:
        return (
            "exile the top X cards of your library, where X is one "
            "plus the mana value of the sacrificed artifact; you may "
            "play those cards this turn"
        )



@dataclass(frozen=True)
class PainForAllETBEffect(Effect):
    """Pain for All's ETB (as an aura): "Enchanted creature deals
    damage equal to its power to any other target."

    "Any other target" (creature or player, excluding the source).
    Reads state.resolving_source for the aura; `aura.attached_to` is
    the enchanted creature; damage amount = enchanted creature's
    effective power at resolution.
    """

    def requires_target(self) -> bool:
        return True

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        aura = state.resolving_source
        enchanted_id = aura.attached_to if aura is not None else None
        out: list[Target] = []
        for p in state.players:
            if p.has_lost:
                continue
            out.append(("player", p.id))
        for o in state.battlefield:
            if not o.printing.is_creature:
                continue
            if o.id == enchanted_id:
                continue
            out.append(("creature", o.id))
        return out

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.game import effective_power

        aura = state.resolving_source
        if aura is None or aura.attached_to is None:
            return
        enchanted = next(
            (o for o in state.battlefield if o.id == aura.attached_to),
            None,
        )
        if enchanted is None:
            return
        if not targets:
            return
        kind, target_id = targets[0]
        amount = effective_power(state, enchanted)
        if amount <= 0:
            return
        if kind == "player":
            victim = state.player_by_id(target_id)
            victim.life -= amount
            state.log.append(
                f"{enchanted.printing.name} deals {amount} to "
                f"P{target_id} (life: {victim.life})"
            )
        elif kind == "creature":
            creature = next(
                (o for o in state.battlefield if o.id == target_id), None
            )
            if creature is None:
                return
            creature.damage += amount
            creature.damaged_this_turn = True
            state.log.append(
                f"{enchanted.printing.name} deals {amount} to "
                f"{creature.printing.name}"
            )

    def describe(self) -> str:
        return (
            "enchanted creature deals damage equal to its power to any "
            "other target"
        )



@dataclass(frozen=True)
class PainForAllDamageEchoEffect(Effect):
    """Pain for All's damage-echo: "Whenever enchanted creature is
    dealt damage, it deals that much damage to each opponent."

    Reads state.resolving_combat_damage_amount for the incoming amount.
    Simplified: each opponent loses ``amount`` life (modeling "deals
    damage" as life loss for simplicity in the non-creature-target
    case).
    """

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        amount = state.resolving_combat_damage_amount
        if amount <= 0:
            return
        for p in state.players:
            if p.id == controller_id or p.has_lost:
                continue
            p.life -= amount
            state.log.append(
                f"Pain for All echoes {amount} to P{p.id} "
                f"(life: {p.life})"
            )

    def describe(self) -> str:
        return (
            "enchanted creature deals that much damage to each "
            "opponent"
        )



@dataclass(frozen=True)
class AllFatesScrollDrawEffect(Effect):
    """All-Fates Scroll's sac-draw: "Draw X cards, where X is the
    number of differently named lands you control."

    Counts distinct land names on the controller's battlefield at
    resolve time and draws that many cards.
    """

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.turn import draw_n_cards

        names: set[str] = set()
        for o in state.battlefield:
            if o.controller_id == controller_id and o.printing.is_land:
                names.add(o.printing.name)
        x = len(names)
        if x <= 0:
            state.log.append(
                f"All-Fates Scroll: P{controller_id} controls no "
                f"lands; draws 0"
            )
            return
        drawn = draw_n_cards(state, controller_id, x)
        state.log.append(
            f"All-Fates Scroll: P{controller_id} draws {drawn} cards"
        )

    def describe(self) -> str:
        return (
            "draw X cards, where X is the number of differently named "
            "lands you control"
        )



@dataclass(frozen=True)
class TractorBeamETBEffect(Effect):
    """Tractor Beam's ETB (simplified): "Tap enchanted permanent."

    Real oracle adds "You control enchanted permanent." and
    "Enchanted permanent doesn't untap during its controller's untap
    step." Neither is modeled — engine has no "don't untap" replacement
    effect and no persistent gain-control mechanic yet.
    """

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.turn import tap_permanent

        aura = state.resolving_source
        if aura is None or aura.attached_to is None:
            return
        target = next(
            (o for o in state.battlefield if o.id == aura.attached_to),
            None,
        )
        if target is None:
            return
        tap_permanent(state, target)
        state.log.append(
            f"Tractor Beam taps {target.printing.name}"
        )

    def describe(self) -> str:
        return "tap enchanted permanent"



@dataclass(frozen=True)
class WeftwalkingETBEffect(Effect):
    """Weftwalking's ETB: "Shuffle your hand and graveyard into your
    library, then draw seven cards."

    The real oracle gates the shuffle-and-draw on "if you cast it"
    (vs. put into play by some other means). Our engine only puts
    enchantments onto the battlefield via casting, so the gate is a
    no-op. The card's static "first spell each turn may be cast
    without paying mana cost" is modeled via the
    ``grants_first_spell_each_turn_free`` printing flag, plumbed
    through legal_actions and _cast_spell — see those modules.
    """

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.game import Zone
        from mtg_bot.turn import draw_n_cards

        p = state.player_by_id(controller_id)
        # Move hand and graveyard back into the library.
        moved = 0
        for c in list(p.hand):
            c.zone = Zone.LIBRARY
            p.library.append(c)
            moved += 1
        p.hand.clear()
        for c in list(p.graveyard):
            c.zone = Zone.LIBRARY
            p.library.append(c)
            moved += 1
        p.graveyard.clear()
        # Shuffle.
        from mtg_bot.game import shuffle_library
        shuffle_library(state, controller_id)
        state.log.append(
            f"Weftwalking: P{controller_id} shuffles {moved} cards into "
            f"library and draws 7"
        )
        draw_n_cards(state, controller_id, 7)

    def describe(self) -> str:
        return (
            "shuffle your hand and graveyard into your library, then "
            "draw seven cards"
        )



@dataclass(frozen=True)
class PossibilityTechnicianETBEffect(Effect):
    """Possibility Technician's ETB-and-Kavu-observer effect: "Exile
    the top card of your library. For as long as that card remains
    exiled, you may play it if you control a Kavu."

    Wired by the printing as both an ``etb`` trigger (this creature)
    and a ``kavu_you_control_enters`` observer trigger (another Kavu),
    matching the printed oracle's "this creature or another Kavu you
    control enters". Persistence is modelled with the
    ``play_from_exile_requires_kavu`` flag on the exiled card —
    legal_actions surfaces a CastSpell/PlayLand for it whenever the
    controller currently controls at least one Kavu, and the flag is
    NOT cleared at end of turn (so the cast remains available across
    turns until the card leaves exile or the Kavu count drops to 0).
    """

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.game import Zone

        p = state.player_by_id(controller_id)
        if not p.library:
            return
        top = p.library.pop(0)
        top.zone = Zone.EXILE
        top.play_from_exile_requires_kavu = True
        p.exile.append(top)
        state.log.append(
            f"Possibility Technician: P{controller_id} exiles "
            f"{top.printing.name} (playable while controller "
            f"controls a Kavu)"
        )

    def describe(self) -> str:
        return (
            "exile the top card of your library; for as long as that "
            "card remains exiled, you may play it if you control a Kavu"
        )



@dataclass(frozen=True)
class RovingActuatorETBEffect(Effect):
    """Roving Actuator's Void ETB: "Exile up to one target instant or
    sorcery card with mana value 2 or less from your graveyard. Copy
    it. You may cast the copy without paying its mana cost."

    Simplification: the "copy and cast" machinery short-circuits to
    directly resolving the exiled card's spell_effect with fresh
    targets selected by the agent. The copy doesn't go on the stack
    and can't be counterspelled — acceptable given the engine's lack
    of responses. "May" is always yes.
    """

    max_mv: int = 2

    def requires_target(self) -> bool:
        return True

    def target_count_range(self) -> tuple[int, int]:
        return (0, 1)

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        p = state.player_by_id(controller_id)
        return [
            ("graveyard_spell", c.id)
            for c in p.graveyard
            if (c.printing.is_instant or c.printing.is_sorcery)
            and c.printing.mana_cost.total <= self.max_mv
        ]

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.game import Zone

        if not targets:
            return
        kind, target_id = targets[0]
        if kind != "graveyard_spell":
            return
        p = state.player_by_id(controller_id)
        card = next((c for c in p.graveyard if c.id == target_id), None)
        if card is None:
            return
        # Exile the original.
        p.graveyard.remove(card)
        card.zone = Zone.EXILE
        p.exile.append(card)
        state.log.append(
            f"Roving Actuator exiles {card.printing.name} and copies it"
        )
        # Resolve a copy of its spell_effect. Fresh targets if any.
        spell_effect = card.printing.spell_effect
        if spell_effect is None:
            return
        copy_targets: tuple[Target, ...] = ()
        min_t, max_t = spell_effect.target_count_range()
        if max_t > 0:
            legal = spell_effect.legal_targets(state, controller_id)
            if not legal and min_t > 0:
                state.log.append(
                    f"Copy of {card.printing.name} fizzles "
                    f"(no legal targets)"
                )
                return
            if p.agent is not None:
                chosen_list: list[Target] = []
                remaining = list(legal)
                for _ in range(max_t):
                    if not remaining:
                        break
                    pick = p.agent.choose_target(
                        state, controller_id, remaining
                    )
                    if pick is None or pick not in remaining:
                        break
                    chosen_list.append(pick)
                    remaining.remove(pick)
                copy_targets = tuple(chosen_list)
        spell_effect.resolve(state, controller_id, copy_targets)

    def describe(self) -> str:
        return (
            f"exile up to one target instant or sorcery card with "
            f"mana value {self.max_mv} or less from your graveyard, "
            f"copy it; you may cast the copy without paying its cost"
        )



@dataclass(frozen=True)
class RequiemMonolithDealtDamageEffect(Effect):
    """The "draw that many cards and lose that much life" rider Requiem
    Monolith grants UEOT.

    Reads ``state.resolving_combat_damage_amount`` for the incoming
    damage amount and applies it to the granted creature's controller
    (state.resolving_source is set to that creature by the fire helper).
    """

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.turn import draw_card

        amount = state.resolving_combat_damage_amount
        if amount <= 0:
            return
        source = state.resolving_source
        if source is None:
            return
        owner = state.player_by_id(source.controller_id)
        for _ in range(amount):
            draw_card(state, owner.id)
        owner.life -= amount
        state.log.append(
            f"Requiem Monolith rider: P{owner.id} draws {amount} "
            f"and loses {amount} life (life: {owner.life})"
        )

    def describe(self) -> str:
        return (
            "you draw that many cards and lose that much life"
        )


@dataclass(frozen=True)
class RequiemMonolithActivatedEffect(Effect):
    """Requiem Monolith's activated ability (full):
    "Until end of turn, target creature gains 'Whenever this creature is
    dealt damage, you draw that many cards and lose that much life.'
    That creature's controller may have this artifact deal 1 damage to
    it."

    Wires the granted UEOT trigger via ``temp_triggered_abilities`` and
    then offers the target's controller (via ``choose_mode``) a may-deal-
    1-damage decision. If the controller accepts, the artifact deals 1
    to the target — which fires the granted trigger we just installed,
    drawing 1 and losing 1 life.
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
        from mtg_bot.combat import _fire_enchanted_dealt_damage_triggers
        from mtg_bot.effects.base import TriggeredAbility

        if not targets:
            return
        kind, target_id = targets[0]
        if kind != "creature":
            return
        tgt = next(
            (o for o in state.battlefield if o.id == target_id), None
        )
        if tgt is None:
            return
        # Grant the UEOT trigger.
        granted = TriggeredAbility(
            trigger="this_dealt_damage",
            effect=RequiemMonolithDealtDamageEffect(),
        )
        tgt.temp_triggered_abilities = tgt.temp_triggered_abilities + (granted,)
        state.log.append(
            f"Requiem Monolith: {tgt.printing.name} gains the "
            f"dealt-damage trigger until end of turn"
        )
        # The TARGET's controller may have the artifact deal 1 damage to it.
        target_controller = state.player_by_id(tgt.controller_id)
        if target_controller.has_lost or target_controller.agent is None:
            return
        modes = ["have Requiem Monolith deal 1 damage to it", "decline"]
        choice = target_controller.agent.choose_mode(
            state, target_controller.id, modes,
        )
        if choice != 0:
            state.log.append(
                f"P{target_controller.id} declines the optional 1 damage"
            )
            return
        tgt.damage += 1
        tgt.damaged_this_turn = True
        state.log.append(
            f"Requiem Monolith deals 1 to {tgt.printing.name}"
        )
        _fire_enchanted_dealt_damage_triggers(state, tgt, 1)

    def describe(self) -> str:
        return (
            "until end of turn, target creature gains \"whenever this "
            "creature is dealt damage, you draw that many cards and "
            "lose that much life\"; that creature's controller may have "
            "this artifact deal 1 damage to it"
        )



@dataclass(frozen=True)
class AtomicMicrosizerAttackEffect(Effect):
    """Atomic Microsizer's equipped-attacks trigger: "Choose up to one
    target creature. That creature can't be blocked this turn and has
    base power and toughness 1/1 until end of turn."

    Max 1 target; if no creature exists it fizzles (0 is fine per
    "up to one").
    """

    def requires_target(self) -> bool:
        return True

    def target_count_range(self) -> tuple[int, int]:
        return (0, 1)

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
        kind, target_id = targets[0]
        if kind != "creature":
            return
        obj = next(
            (o for o in state.battlefield if o.id == target_id), None
        )
        if obj is None:
            return
        obj.temp_unblockable = True
        obj.temp_base_pt_override = (1, 1)
        state.log.append(
            f"{obj.printing.name} can't be blocked this turn and has "
            f"base P/T 1/1 UEOT"
        )

    def describe(self) -> str:
        return (
            "choose up to one target creature. That creature can't be "
            "blocked this turn and has base power and toughness 1/1 "
            "until end of turn"
        )



@dataclass(frozen=True)
class ChoraleReanimateDefenderGraveCreatureEffect(Effect):
    """Chorale of the Void's attacks trigger: "Put target creature
    card from defending player's graveyard onto the battlefield under
    your control tapped and attacking."

    Simplification: legal targets = any creature card in any opponent's
    graveyard (2-player case matches oracle exactly; multiplayer is an
    approximation). The reanimated creature enters tapped and attacking.
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
            card = next((c for c in p.graveyard if c.id == target_id), None)
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
class KavaronHarrierAttackEffect(Effect):
    """Kavaron Harrier's attacks trigger: "You may pay {2}. If you do,
    create a 2/2 colorless Robot artifact creature token that's tapped
    and attacking. Sacrifice that token at end of combat."

    "May" is treated as yes whenever the caster can afford {2}. Token
    is created tapped+attacking; its id is scheduled for end-of-combat
    sacrifice via state.pending_end_of_combat_sacrifices.
    """

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.actions import auto_tap_for_cost, can_pay_cost
        from mtg_bot.cards import TOKEN_PRINTINGS, parse_mana_cost
        from mtg_bot.game import Zone

        cost = parse_mana_cost("{2}")
        if not can_pay_cost(state, controller_id, cost):
            state.log.append(
                f"Kavaron Harrier: P{controller_id} can't pay {{2}}; "
                f"trigger does nothing"
            )
            return
        auto_tap_for_cost(state, controller_id, cost)
        robot = TOKEN_PRINTINGS["Robot"]
        token = state.new_object(robot, controller_id, Zone.BATTLEFIELD)
        token.tapped = True
        token.attacking = True
        token.summoning_sick = False
        state.battlefield.append(token)
        state.pending_end_of_combat_sacrifices.append(token.id)
        state.log.append(
            f"Kavaron Harrier creates tapped+attacking Robot token "
            f"(will be sacrificed at end of combat)"
        )

    def describe(self) -> str:
        return (
            "you may pay {2}; if you do, create a 2/2 Robot token "
            "that's tapped and attacking; sacrifice that token at "
            "end of combat"
        )



@dataclass(frozen=True)
class MonoistCircuitFeederETBEffect(Effect):
    """Monoist Circuit-Feeder's ETB: "Until end of turn, target creature
    you control gets +X/+0 and target creature an opponent controls
    gets -0/-X, where X is the number of artifacts you control."

    Uses two distinct target slots (own creature, opponent creature)
    picked by the agent in sequence. X is computed at resolve time
    from the caster's battlefield artifact count. If one slot has no
    legal target, that half silently no-ops; the trigger still fires
    if at least one creature exists across both sides.
    """

    def requires_target(self) -> bool:
        return True

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        # Union of both slots — at least one legal target is required
        # to queue the trigger (has_legal check).
        return [
            ("creature", o.id)
            for o in state.battlefield
            if o.printing.is_creature
        ]

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        p = state.player_by_id(controller_id)
        x = sum(
            1 for o in state.battlefield
            if o.controller_id == controller_id and o.printing.is_artifact
        )
        # Pick own target and opponent target independently via the agent
        # (ignoring any targets passed in — this effect manages its own
        # two-slot selection).
        own_options = [
            o for o in state.battlefield
            if o.printing.is_creature and o.controller_id == controller_id
        ]
        opp_options = [
            o for o in state.battlefield
            if o.printing.is_creature and o.controller_id != controller_id
        ]
        own_target = None
        if own_options and p.agent is not None:
            pick = p.agent.choose_target(
                state, controller_id,
                [("creature", o.id) for o in own_options],
            )
            if pick is not None:
                own_target = next(
                    (o for o in own_options if o.id == pick[1]), None
                )
        opp_target = None
        if opp_options and p.agent is not None:
            pick = p.agent.choose_target(
                state, controller_id,
                [("creature", o.id) for o in opp_options],
            )
            if pick is not None:
                opp_target = next(
                    (o for o in opp_options if o.id == pick[1]), None
                )
        if own_target is not None:
            own_target.temp_power_bonus += x
            state.log.append(
                f"{own_target.printing.name} gets +{x}/+0 UEOT"
            )
        if opp_target is not None:
            opp_target.temp_toughness_bonus -= x
            state.log.append(
                f"{opp_target.printing.name} gets -0/-{x} UEOT"
            )

    def describe(self) -> str:
        return (
            "until end of turn, target creature you control gets +X/+0 "
            "and target creature an opponent controls gets -0/-X, where "
            "X is the number of artifacts you control"
        )



@dataclass(frozen=True)
class AnticausalVestigeLeavesEffect(Effect):
    """Anticausal Vestige's leaves-battlefield trigger: "Draw a card,
    then you may put a permanent card with mana value less than or
    equal to the number of lands you control from your hand onto the
    battlefield tapped."

    Simplification: "may" is always yes if there's a legal permanent
    card in hand. Agent picks which via choose_sacrifice (reusing the
    id-from-list picker — no dedicated "pick from hand" hook exists).
    """

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.actions import put_into_battlefield
        from mtg_bot.turn import draw_n_cards

        draw_n_cards(state, controller_id, 1)
        p = state.player_by_id(controller_id)
        land_count = sum(
            1 for o in state.battlefield
            if o.controller_id == controller_id and o.printing.is_land
        )
        candidates = [
            c for c in p.hand
            if c.printing.is_permanent
            and c.printing.mana_cost.total <= land_count
        ]
        if not candidates or p.agent is None:
            return
        pick_id = p.agent.choose_sacrifice(
            state, controller_id, [c.id for c in candidates]
        )
        card = next((c for c in candidates if c.id == pick_id), candidates[0])
        p.hand.remove(card)
        state.log.append(
            f"P{controller_id} puts {card.printing.name} onto the "
            f"battlefield tapped (Anticausal Vestige)"
        )
        put_into_battlefield(state, card, controller_id)
        card.tapped = True

    def describe(self) -> str:
        return (
            "draw a card, then you may put a permanent card with mana "
            "value X or less from your hand onto the battlefield "
            "tapped, where X is the number of lands you control"
        )



@dataclass(frozen=True)
class TerrapactIntimidatorETBEffect(Effect):
    """Terrapact Intimidator's ETB: "Target opponent may have you create
    two Lander tokens. If they don't, put two +1/+1 counters on this
    creature."

    Targets a player (the chosen opponent). The opponent then picks:
    option 0 = controller creates two Landers; option 1 = controller
    puts two +1/+1 counters on the source. Reads state.resolving_source
    for the source permanent.
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
        from mtg_bot.cards import TOKEN_PRINTINGS
        from mtg_bot.game import Zone

        source = state.resolving_source
        if not targets:
            return
        kind, target_id = targets[0]
        if kind != "player":
            return
        opponent = state.player_by_id(target_id)
        if opponent.has_lost or opponent.agent is None:
            return
        modes = ["have controller create two Lander tokens", "decline"]
        choice = opponent.agent.choose_mode(state, opponent.id, modes)
        if choice == 0:
            lander_printing = TOKEN_PRINTINGS["Lander"]
            for _ in range(2):
                token = state.new_object(
                    lander_printing, controller_id, Zone.BATTLEFIELD,
                )
                state.battlefield.append(token)
            state.log.append(
                f"P{opponent.id} elected — P{controller_id} creates "
                f"two Lander tokens"
            )
        else:
            if source is not None:
                from mtg_bot.game import add_plus_one_counters
                add_plus_one_counters(state, source, 2)
                state.log.append(
                    f"P{opponent.id} declined — {source.printing.name} "
                    f"gets two +1/+1 counters (now "
                    f"{source.plus_one_counters})"
                )

    def describe(self) -> str:
        return (
            "target opponent may have you create two Lander tokens; if "
            "they don't, put two +1/+1 counters on this creature"
        )



@dataclass(frozen=True)
class DyadrineAttackEffect(Effect):
    """Dyadrine, Synthesis Amalgam's attack trigger:
    "Whenever you attack, you may remove a +1/+1 counter from each of
    two creatures you control. If you do, draw a card and create a
    2/2 colorless Robot artifact creature token."

    Simplifications:
    - Agent always opts to pay the cost when possible (consistent
      with other OptionalSac-like effects in the codebase).
    - The two creatures are picked by iteration order — the agent's
      choose_sacrifice hook is re-used to select one creature at a
      time so at least some agency is exposed.
    """

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.actions import put_into_battlefield
        from mtg_bot.cards import TOKEN_PRINTINGS
        from mtg_bot.game import Zone

        p = state.player_by_id(controller_id)
        candidates = [
            o for o in state.battlefield
            if o.controller_id == controller_id
            and o.printing.is_creature
            and o.plus_one_counters > 0
        ]
        if len(candidates) < 2:
            state.log.append(
                "Dyadrine's attack trigger: fewer than 2 creatures "
                "with +1/+1 counters — skipped"
            )
            return
        picks: list = []
        remaining = list(candidates)
        for _ in range(2):
            chosen = remaining[0]
            if p.agent is not None:
                pick_id = p.agent.choose_sacrifice(
                    state, controller_id, [o.id for o in remaining]
                )
                chosen = next(
                    (o for o in remaining if o.id == pick_id),
                    remaining[0],
                )
            chosen.plus_one_counters -= 1
            picks.append(chosen)
            remaining.remove(chosen)
            state.log.append(
                f"Dyadrine removes +1/+1 counter from "
                f"{chosen.printing.name} (now {chosen.plus_one_counters})"
            )
        # Draw a card.
        if p.library:
            card = p.library.pop(0)
            card.zone = Zone.HAND
            p.hand.append(card)
            state.log.append(
                f"Dyadrine: P{controller_id} draws {card.printing.name}"
            )
        # Create the Robot token.
        token = state.new_object(
            TOKEN_PRINTINGS["Robot"], owner_id=controller_id,
            zone=Zone.BATTLEFIELD,
        )
        put_into_battlefield(state, token, controller_id)
        state.log.append(
            f"Dyadrine: P{controller_id} creates a Robot token"
        )

    def describe(self) -> str:
        return (
            "you may remove a +1/+1 counter from each of two creatures "
            "you control; if you do, draw a card and create a 2/2 "
            "colorless Robot artifact creature token"
        )



@dataclass(frozen=True)
class CloseEncounterEffect(Effect):
    """Close Encounter `{1}{G}`:
    "As an additional cost to cast this spell, choose a creature you
    control or a warped creature card you own in exile.
    Close Encounter deals damage equal to the power of the chosen
    creature or card to target creature."

    Reads state.resolving_additional_cost_choice_id to know which
    creature/card the caster designated, then deals damage equal to
    that creature's or card's power to the chosen target creature.

    For a battlefield-creature pick, uses ``effective_power`` (the
    designation's current power, including any pumps). For an exiled
    warped creature card, uses the card's printed power — the card
    isn't on the battlefield so continuous effects don't apply.
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
        from mtg_bot.game import effective_power

        if not targets:
            return
        kind, target_id = targets[0]
        if kind != "creature":
            return
        chosen_id = state.resolving_additional_cost_choice_id
        if chosen_id is None:
            return
        chosen = next(
            (o for o in state.battlefield if o.id == chosen_id), None
        )
        if chosen is not None:
            amount = effective_power(state, chosen)
        else:
            # Look in the caster's exile for a warped creature card —
            # that's the other branch of the additional cost.
            p = state.player_by_id(controller_id)
            chosen = next(
                (o for o in p.exile if o.id == chosen_id), None
            )
            if chosen is not None:
                amount = chosen.printing.power or 0
            else:
                # The designated creature left the battlefield before
                # this resolved (e.g., destroyed in response) — we
                # don't track a P/T snapshot at cost-pay time, so
                # fall back to 0.
                amount = 0
        _apply_damage(state, targets[0], amount)

    def describe(self) -> str:
        return (
            "deals damage equal to the designated creature's power to "
            "target creature"
        )



@dataclass(frozen=True)
class ConsultTheStarChartsEffect(Effect):
    """Consult the Star Charts `{1}{U}` (kicker `{1}{U}`):
    "Look at the top X cards of your library, where X is the number of
    lands you control. Put one of those cards into your hand. If this
    spell was kicked, put two of those cards into your hand instead.
    Put the rest on the bottom of your library in a random order."

    Reads state.resolving_kicked to choose between 1 and 2 cards to
    keep. Agent picks the kept cards via ``choose_card_from_library``.
    """

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.game import Zone

        p = state.player_by_id(controller_id)
        x = sum(
            1 for o in state.battlefield
            if o.controller_id == controller_id and o.printing.is_land
        )
        if x == 0 or not p.library:
            state.log.append(
                f"Consult the Star Charts: X={x}, nothing to look at"
            )
            return
        examined = p.library[:x]
        keep = 2 if state.resolving_kicked else 1
        kept_cards: list = []
        remaining = list(examined)
        for _ in range(keep):
            if not remaining:
                break
            chosen_id = None
            if p.agent is not None:
                chosen_id = p.agent.choose_card_from_library(
                    state, controller_id, [c.id for c in remaining]
                )
            if chosen_id is None:
                chosen_id = remaining[0].id
            card = next(
                (c for c in remaining if c.id == chosen_id), remaining[0]
            )
            kept_cards.append(card)
            remaining.remove(card)
        from mtg_bot.game import reset_public_knowledge
        for card in kept_cards:
            p.library.remove(card)
            card.zone = Zone.HAND
            p.hand.append(card)
            # Disturbance: opponent who previously knew this card's
            # library position can no longer track which examined card
            # went to hand vs bottom. Conservatively forget reveals.
            reset_public_knowledge(card)
            state.log.append(
                f"P{controller_id} puts {card.printing.name} into hand "
                f"from Consult the Star Charts"
            )
        # Bottom the rest in random order.
        for card in remaining:
            p.library.remove(card)
            reset_public_knowledge(card)
        state.rng.shuffle(remaining)
        p.library.extend(remaining)
        state.log.append(
            f"Consult the Star Charts: put {len(remaining)} cards on "
            f"the bottom in random order"
        )

    def describe(self) -> str:
        return (
            "look at the top X cards of your library (X = lands you "
            "control); put one into your hand (two if kicked); put "
            "the rest on the bottom in a random order"
        )



@dataclass(frozen=True)
class PinnacleStarcageETBEffect(Effect):
    """Pinnacle Starcage's ETB: "Exile all artifacts and creatures with
    mana value 2 or less until this artifact leaves the battlefield."

    Untargeted mass exile filtered by type (artifact or creature) and
    mana value. Uses the same ``exiled_by_source`` bookkeeping as other
    "exile until this leaves" effects so they return when the Starcage
    itself leaves the battlefield.
    """

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.turn import move_off_battlefield

        source = state.resolving_source
        if source is None:
            return
        victims = [
            o for o in list(state.battlefield)
            if o is not source
            and (o.printing.is_artifact or o.printing.is_creature)
            and not o.printing.is_land
            and o.printing.mana_cost.total <= 2
        ]
        for obj in victims:
            obj.exiled_by_source = source.id
            state.log.append(
                f"{obj.printing.name} exiled by "
                f"{source.printing.name}"
            )
            move_off_battlefield(state, obj, destination="exile")

    def describe(self) -> str:
        return (
            "exile all artifacts and creatures with mana value 2 or "
            "less until this artifact leaves the battlefield"
        )



@dataclass(frozen=True)
class PinnacleStarcageSacEffect(Effect):
    """Pinnacle Starcage's {6}{W}{W} activated ability: "Put each card
    exiled with this artifact into its owner's graveyard, then create
    a 2/2 colorless Robot artifact creature token for each card put
    into a graveyard this way. Sacrifice this artifact."

    The Starcage is sacrificed at the end, which also releases any
    remaining exiled-by-it cards back — but we've already moved them
    to graveyards explicitly, so the release-on-leave is a no-op here.
    """

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.cards import TOKEN_PRINTINGS
        from mtg_bot.game import Zone

        source = state.resolving_source
        if source is None:
            return
        moved = 0
        for p in state.players:
            still_exiled = [c for c in p.exile if c.exiled_by_source == source.id]
            for card in still_exiled:
                p.exile.remove(card)
                card.zone = Zone.GRAVEYARD
                card.exiled_by_source = None
                p.graveyard.append(card)
                moved += 1
        state.log.append(
            f"{source.printing.name} moves {moved} exiled cards to "
            f"graveyards; creates {moved} Robot tokens"
        )
        robot = TOKEN_PRINTINGS["Robot"]
        for _ in range(moved):
            token = state.new_object(robot, controller_id, Zone.BATTLEFIELD)
            state.battlefield.append(token)
        # Sacrifice the Starcage itself.
        from mtg_bot.turn import sacrifice as _sacrifice
        _sacrifice(state, source)

    def describe(self) -> str:
        return (
            "put each card exiled with this artifact into its owner's "
            "graveyard, then create a 2/2 Robot for each; sacrifice "
            "this artifact"
        )



@dataclass(frozen=True)
class SeedshipImpactEffect(Effect):
    """Destroy target artifact or enchantment. If its mana value was 2
    or less, create a Lander token.
    """

    def requires_target(self) -> bool:
        return True

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        return [
            ("permanent", o.id)
            for o in state.battlefield
            if o.printing.is_artifact
            or "Enchantment" in o.printing.card_types
        ]

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.actions import put_into_battlefield
        from mtg_bot.cards import TOKEN_PRINTINGS
        from mtg_bot.game import Zone
        from mtg_bot.turn import destroy

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
        if not (
            obj.printing.is_artifact
            or "Enchantment" in obj.printing.card_types
        ):
            return
        mv = obj.printing.mana_cost.total
        state.log.append(f"{obj.printing.name} is destroyed")
        if not destroy(state, obj):
            return  # indestructible — no Lander consolation
        if mv <= 2:
            lander = state.new_object(
                TOKEN_PRINTINGS["Lander"],
                owner_id=controller_id,
                zone=Zone.BATTLEFIELD,
            )
            state.log.append(f"P{controller_id} creates a Lander token")
            put_into_battlefield(state, lander, controller_id)

    def describe(self) -> str:
        return (
            "destroy target artifact or enchantment; if its mana value "
            "was 2 or less, create a Lander token"
        )



@dataclass(frozen=True)
class MutinousMassacreEffect(Effect):
    """Mutinous Massacre `{3}{B}{B}{R}{R}`:
    "Choose odd or even. Destroy each creature with mana value of the
    chosen quality. Then gain control of all creatures until end of
    turn. Untap them. They gain haste until end of turn. (Zero is even.)"

    The "choose odd or even" pick goes through ``choose_mode`` with
    descriptions ``["odd", "even"]``. Surviving creatures (those whose
    mana value parity differed from the chosen one) are all stolen via
    ``temp_original_controller_id``, untapped, and given haste UEOT.
    """

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.turn import destroy

        p = state.player_by_id(controller_id)
        pick = 0  # 0 = odd, 1 = even
        if p.agent is not None:
            pick = p.agent.choose_mode(state, controller_id, ["odd", "even"])
            pick = max(0, min(pick, 1))
        chosen_label = "odd" if pick == 0 else "even"
        state.log.append(
            f"P{controller_id} chooses {chosen_label} for Mutinous Massacre"
        )
        # Destroy phase: each creature whose mana value matches the
        # chosen parity.
        victims = []
        for o in list(state.battlefield):
            if not o.printing.is_creature:
                continue
            mv = o.printing.mana_cost.total
            if pick == 0 and mv % 2 == 1:
                victims.append(o)
            elif pick == 1 and mv % 2 == 0:
                victims.append(o)
        for v in victims:
            state.log.append(
                f"{v.printing.name} (MV {v.printing.mana_cost.total}) "
                f"destroyed by Mutinous Massacre ({chosen_label})"
            )
            destroy(state, v)
        # Gain control of all surviving creatures UEOT, untap, haste.
        for o in state.battlefield:
            if not o.printing.is_creature:
                continue
            if o.controller_id != controller_id:
                if o.temp_original_controller_id is None:
                    o.temp_original_controller_id = o.controller_id
                o.controller_id = controller_id
            o.tapped = False
            o.temp_keywords = o.temp_keywords | frozenset({"haste"})
            state.log.append(
                f"P{controller_id} takes control of {o.printing.name} "
                f"UEOT; untaps + gains haste"
            )

    def describe(self) -> str:
        return (
            "choose odd or even; destroy each creature with mana value "
            "of the chosen quality; then gain control of all creatures "
            "until end of turn, untap them, they gain haste until end "
            "of turn"
        )



@dataclass(frozen=True)
class SystemsOverrideEffect(Effect):
    """Systems Override `{2}{R}` — gain control of target artifact or
    creature until end of turn, untap it, give it haste UEOT. If it's
    a Spacecraft, put ten charge counters on it; if so, remove ten
    at the beginning of the next end step.

    Control reverts on cleanup via ``temp_original_controller_id``. The
    ten-counter remove is scheduled as a delayed end-step action
    (``"remove_charge_counters"``) resolved in run_delayed_end_step_triggers.
    """

    def requires_target(self) -> bool:
        return True

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        return [
            ("permanent", o.id)
            for o in state.battlefield
            if o.printing.is_artifact or o.printing.is_creature
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
        if obj is None:
            return
        # Gain control UEOT. If we already stole it this turn, keep the
        # original controller (don't overwrite with the current — rare
        # but preserves correct reversion).
        if obj.temp_original_controller_id is None:
            obj.temp_original_controller_id = obj.controller_id
        obj.controller_id = controller_id
        obj.tapped = False
        obj.temp_keywords = obj.temp_keywords | frozenset({"haste"})
        state.log.append(
            f"P{controller_id} takes control of {obj.printing.name} "
            f"UEOT; untaps + gains haste"
        )
        if obj.printing.is_spacecraft:
            from mtg_bot.game import add_charge_counters
            add_charge_counters(state, obj, 10)
            state.log.append(
                f"{obj.printing.name} gets 10 charge counters "
                f"(now {obj.charge_counters})"
            )
            state.delayed_triggers.append({
                "fire_at_turn": state.turn_number,
                "controller_id": controller_id,
                "action": "remove_charge_counters",
                "target_id": obj.id,
                "amount": 10,
            })

    def describe(self) -> str:
        return (
            "gain control of target artifact or creature until end of "
            "turn; untap it; it gains haste until end of turn; if it's "
            "a Spacecraft, put ten charge counters on it, then remove "
            "ten at the next end step"
        )



@dataclass(frozen=True)
class BiosynthicBurstEffect(Effect):
    """Put a +1/+1 counter on target creature you control. It gains reach,
    trample, and indestructible UEOT. Untap it.

    One dedicated effect because all three pieces operate on the same
    target, which doesn't compose cleanly via Sequence in our single-
    target-per-Sequence model.
    """

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
        if not targets:
            return
        kind, target_id = targets[0]
        if kind != "creature":
            return
        obj = next(
            (o for o in state.battlefield if o.id == target_id), None
        )
        if obj is None or obj.controller_id != controller_id:
            return
        from mtg_bot.game import add_plus_one_counters
        add_plus_one_counters(state, obj, 1)
        obj.temp_keywords = obj.temp_keywords | frozenset(
            {"reach", "trample", "indestructible"}
        )
        obj.tapped = False
        state.log.append(
            f"{obj.printing.name} gets a +1/+1 counter, gains reach, "
            f"trample, indestructible UEOT, and untaps"
        )

    def describe(self) -> str:
        return (
            "put a +1/+1 counter on target creature you control; it "
            "gains reach, trample, and indestructible until end of "
            "turn; untap it"
        )



@dataclass(frozen=True)
class DepressurizeEffect(Effect):
    """Target creature gets -3/-0 UEOT; then if its power is 0 or less,
    destroy it.

    Dedicated effect because the conditional destroy reads the pumped
    creature's post-modification power — an inline check after the pump
    is clearer than stitching Sequence + ConditionalDestroyIfPowerLEQ.
    """

    power_penalty: int = 3  # applied as a negative to temp_power_bonus

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
        from mtg_bot.game import effective_power
        from mtg_bot.turn import destroy

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
        obj.temp_power_bonus -= self.power_penalty
        state.log.append(
            f"{obj.printing.name} gets -{self.power_penalty}/-0 until end "
            f"of turn"
        )
        # "Then if that creature's power is 0 or less, destroy it."
        if effective_power(state, obj) <= 0:
            state.log.append(f"{obj.printing.name} is destroyed (depressurized)")
            destroy(state, obj)

    def describe(self) -> str:
        return (
            f"target creature gets -{self.power_penalty}/-0 until end of "
            f"turn; then if its power is 0 or less, destroy it"
        )



@dataclass(frozen=True)
class SingularityRuptureEffect(Effect):
    """Singularity Rupture `{3}{U}{B}{B}`:
    "Destroy all creatures, then any number of target players each mill
    half their library, rounded down."

    Multi-target: min 0, max = number of living players. After the
    wrath, each chosen player mills ``floor(library_size / 2)`` cards.
    """

    def requires_target(self) -> bool:
        # "Any number of target" — technically optional, but the cast
        # pipeline only requires a target pool to exist. legal_actions
        # won't gate casting on this since there's always at least one
        # living player.
        return True

    def target_count_range(self) -> tuple[int, int]:
        # "Any number" — min 0, max bounded by a reasonable ceiling.
        # Two-player games → max 2. We pick 8 to cover any plausible
        # multiplayer pod size; the cast pipeline clamps to actual
        # legal_targets length anyway.
        return (0, 8)

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
        from mtg_bot.turn import destroy

        # Wrath phase.
        victims = [o for o in state.battlefield if o.printing.is_creature]
        for o in victims:
            state.log.append(
                f"{o.printing.name} destroyed by Singularity Rupture"
            )
            destroy(state, o)
        # Mill phase — each targeted player mills half their library,
        # rounded down.
        for kind, tid in targets:
            if kind != "player":
                continue
            try:
                p = state.player_by_id(tid)
            except KeyError:
                continue
            if p.has_lost:
                continue
            n = len(p.library) // 2
            milled = 0
            for _ in range(n):
                if not p.library:
                    break
                card = p.library.pop(0)
                card.zone = Zone.GRAVEYARD
                p.graveyard.append(card)
                milled += 1
            state.log.append(
                f"P{tid} mills {milled} card(s) from Singularity Rupture "
                f"(library now {len(p.library)})"
            )

    def describe(self) -> str:
        return (
            "destroy all creatures; then any number of target players "
            "each mill half their library, rounded down"
        )



@dataclass(frozen=True)
class ZeroPointBalladEffect(Effect):
    """Zero Point Ballad `{X}{B}`:
    "Destroy all creatures with toughness X or less. You lose X life. If
    X is 6 or more, return a creature card put into a graveyard this way
    to the battlefield under your control."

    Reads X from ``state.resolving_x_value``. For the X≥6 clause, a
    creature card is "put into a graveyard this way" only if it was
    destroyed by the first clause AND landed in the caster's graveyard
    (i.e. the caster owned it). The agent picks one of those candidates
    via ``choose_target`` (kind=``creature_card``); declining is legal —
    the reanimation is optional.
    """

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.actions import put_into_battlefield
        from mtg_bot.game import effective_toughness
        from mtg_bot.turn import destroy

        x = state.resolving_x_value
        victims = [
            o for o in state.battlefield
            if o.printing.is_creature and effective_toughness(state, o) <= x
        ]
        caster_owned_victim_ids = {
            o.id for o in victims if o.owner_id == controller_id
        }
        for obj in victims:
            state.log.append(
                f"{obj.printing.name} destroyed by Zero Point Ballad "
                f"(X={x})"
            )
            destroy(state, obj)

        p = state.player_by_id(controller_id)
        p.life -= x
        state.log.append(
            f"P{controller_id} loses {x} life to Zero Point Ballad "
            f"(life: {p.life})"
        )

        if x >= 6:
            candidates = [
                c for c in p.graveyard
                if c.id in caster_owned_victim_ids
                and c.printing.is_creature
            ]
            if candidates and p.agent is not None:
                legal = [("creature_card", c.id) for c in candidates]
                chosen = p.agent.choose_target(state, controller_id, legal)
                if chosen is not None:
                    card = next(
                        (c for c in candidates if c.id == chosen[1]), None
                    )
                    if card is not None:
                        p.graveyard.remove(card)
                        put_into_battlefield(state, card, controller_id)
                        state.log.append(
                            f"Zero Point Ballad returns "
                            f"{card.printing.name} to the battlefield"
                        )

    def describe(self) -> str:
        return (
            "destroy all creatures with toughness X or less; you lose X "
            "life; if X is 6 or more, return a creature card put into a "
            "graveyard this way to the battlefield under your control"
        )



@dataclass(frozen=True)
class FocusFireEffect(Effect):
    """Deal (``base`` + your creatures and Spacecraft) damage to an attacking
    or blocking creature.

    Matches Focus Fire. Dynamic amount is recomputed at resolution.
    Legality is filtered to attackers/blockers only; that's re-checked at
    resolve time so a creature that stops attacking/blocking between cast
    and resolve fizzles the damage.
    """

    base: int = 2

    def requires_target(self) -> bool:
        return True

    @staticmethod
    def _is_in_combat(obj: "GameObject") -> bool:
        return obj.attacking or obj.blocking is not None

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        return [
            ("creature", o.id)
            for o in state.battlefield
            if o.printing.is_creature and self._is_in_combat(o)
        ]

    def _amount(self, state: "GameState", controller_id: int) -> int:
        bonus = sum(
            1 for o in state.battlefield
            if o.controller_id == controller_id
            and (o.printing.is_creature or o.printing.is_spacecraft)
        )
        return self.base + bonus

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
        if obj is None or not self._is_in_combat(obj):
            return
        _apply_damage(state, targets[0], self._amount(state, controller_id))

    def describe(self) -> str:
        return (
            f"deals {self.base}+X damage to target attacking or blocking "
            f"creature, where X is creatures and Spacecraft you control"
        )



@dataclass(frozen=True)
class CutPropulsionEffect(Effect):
    """Target creature deals damage to itself equal to its power; doubled if
    that creature has flying.

    Matches Cut Propulsion. Self-damage uses _apply_damage, which applies
    deathtouch-style marked_lethal only when a deathtouch source is involved
    — self-damage carries no source keywords so SBA-based lethal checks
    behave normally.
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
        from mtg_bot.game import effective_keywords, effective_power

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
        power = effective_power(state, obj)
        if power <= 0:
            state.log.append(
                f"{obj.printing.name} deals 0 damage to itself "
                f"(Cut Propulsion)"
            )
            return
        if "flying" in effective_keywords(state, obj):
            amount = power * 2
        else:
            amount = power
        state.log.append(
            f"{obj.printing.name} takes {amount} (Cut Propulsion self-damage)"
        )
        _apply_damage(state, targets[0], amount)

    def describe(self) -> str:
        return (
            "target creature deals damage to itself equal to its power; "
            "doubled if it has flying"
        )



@dataclass(frozen=True)
class DiplomaticRelationsEffect(Effect):
    """Diplomatic Relations `{2}{G}` Instant:
    "Target creature you control gets +1/+0 and gains vigilance until end
    of turn. It deals damage equal to its power to target creature an
    opponent controls."

    Two-target spell with disjoint filters. To let the existing flat
    target-pick pipeline validate each slot independently, we expose the
    two slots as distinct kinds:

    - ``("my_creature", id)`` — the pumped friendly creature (slot 0)
    - ``("creature",   id)`` — the opponent's creature taking damage (slot 1)

    ``legal_targets`` returns a flat list mixing both kinds. The agent
    picks twice; ``resolve`` then locates one entry of each kind and
    applies pump-then-damage. The damage amount is the pumped creature's
    effective power AT RESOLUTION (i.e., +1 already applied).

    If either slot has no legal candidates, ``legal_targets`` returns
    ``[]`` so the cast-time gate (``_targets_are_satisfiable``) refuses
    the spell entirely — mirroring MTG's "if you can't choose a legal
    target for each, you can't cast" rule.
    """

    def requires_target(self) -> bool:
        return True

    def target_count_range(self) -> tuple[int, int]:
        return (2, 2)

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        mine = [
            ("my_creature", o.id)
            for o in state.battlefield
            if o.printing.is_creature
            and o.controller_id == controller_id
        ]
        theirs = [
            ("creature", o.id)
            for o in state.battlefield
            if o.printing.is_creature
            and o.controller_id != controller_id
        ]
        # Both slots must be satisfiable; if either side is empty the
        # spell cannot be cast.
        if not mine or not theirs:
            return []
        return mine + theirs

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.game import effective_power

        # Locate one entry per slot. Order is agent-dependent so we
        # search by kind rather than index.
        my_target = next(
            ((k, t) for (k, t) in targets if k == "my_creature"), None
        )
        opp_target = next(
            ((k, t) for (k, t) in targets if k == "creature"), None
        )
        # Pump the friendly creature first if it's still on the battlefield
        # and still controlled by the caster (target re-validation: if it
        # left or changed control, that target is illegal and skipped per
        # rule 608.2b).
        my_obj = None
        if my_target is not None:
            my_obj = next(
                (o for o in state.battlefield if o.id == my_target[1]),
                None,
            )
            if my_obj is not None and my_obj.controller_id == controller_id:
                my_obj.temp_power_bonus += 1
                my_obj.temp_keywords = my_obj.temp_keywords | frozenset(
                    {"vigilance"}
                )
                state.log.append(
                    f"{my_obj.printing.name} gets +1/+0 and gains "
                    f"vigilance until end of turn"
                )
            else:
                my_obj = None
        # Damage component: requires both an opponent's-creature target
        # AND a still-living, still-controlled friendly creature whose
        # power we read.
        if opp_target is None or my_obj is None:
            return
        opp_obj = next(
            (o for o in state.battlefield if o.id == opp_target[1]),
            None,
        )
        if opp_obj is None or opp_obj.controller_id == controller_id:
            return
        amount = effective_power(state, my_obj)
        state.log.append(
            f"{my_obj.printing.name} deals {amount} damage to "
            f"{opp_obj.printing.name} (Diplomatic Relations)"
        )
        _apply_damage(state, ("creature", opp_obj.id), amount)

    def describe(self) -> str:
        return (
            "target creature you control gets +1/+0 and gains vigilance "
            "until end of turn; it deals damage equal to its power to "
            "target creature an opponent controls"
        )



@dataclass(frozen=True)
class PerigeeBeckonerDiesReturnTappedEffect(Effect):
    """Perigee Beckoner's granted dies-rider: "When this creature dies,
    return it to the battlefield tapped under its owner's control."

    Resolves directly from ``_fire_dies_triggers`` (mirrors the
    Requiem-Monolith dealt-damage rider pattern): the dying creature is
    sitting in its owner's graveyard with ``state.resolving_source`` set
    to it. We move it back onto the battlefield, tapped, under its
    owner's id (per oracle — "owner's control", not "your control").
    """

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.actions import put_into_battlefield
        from mtg_bot.game import Zone

        source = state.resolving_source
        if source is None:
            return
        owner = state.player_by_id(source.owner_id)
        # Tokens cease to exist on death — nothing to bring back.
        if source.printing.is_token:
            return
        # The dying creature should be in its owner's graveyard. If it's
        # been moved elsewhere already (e.g. exiled by a replacement),
        # we don't return anything.
        if source not in owner.graveyard:
            return
        owner.graveyard.remove(source)
        # Clear the temp_triggered_abilities now so a second death this
        # turn (re-killed after the return) doesn't re-fire the rider —
        # rules-wise the granted UEOT trigger is on the FORMER object;
        # the returned object is a "new object" with no memory of UEOT
        # grants. (Cleanup wipes them at end of turn anyway.)
        source.temp_triggered_abilities = ()
        put_into_battlefield(state, source, owner.id)
        source.tapped = True
        state.log.append(
            f"{source.printing.name} returns to P{owner.id}'s "
            f"battlefield tapped (granted dies-rider)"
        )

    def describe(self) -> str:
        return (
            "return this creature to the battlefield tapped under its "
            "owner's control"
        )


@dataclass(frozen=True)
class AlpharaelDreamingAcolyteDiscardEffect(Effect):
    """Alpharael, Dreaming Acolyte's "discard" tail of the ETB clause:

    "...Then discard two cards unless you discard an artifact card."

    Templated as a "do X unless Y" choice — the controller may sub the
    main discard (two cards, any) for a single artifact-card discard.
    Implemented as a binary mode pick:

    - Mode 0: discard one artifact card from hand. Only legal when the
      controller has at least one artifact card in hand. The specific
      artifact picked goes through ``choose_discard`` filtered to the
      artifact subset.
    - Mode 1: discard two cards (any), the standard fallback.

    If the controller has no artifact card in hand, mode 0 is unavailable
    and the effect always falls back to discarding two cards. The draw-
    two portion of the printed clause is handled by the preceding
    ``DrawCards(2)`` in the parent ``Sequence``; this effect only models
    the "discard ... unless ..." rider.
    """

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.game import Zone
        from mtg_bot.turn import fire_opponent_discards_triggers

        p = state.player_by_id(controller_id)
        if not p.hand:
            return

        artifact_ids = [c.id for c in p.hand if c.printing.is_artifact]
        # If no artifact in hand, the "unless" branch is unavailable —
        # fall through to the discard-two path.
        use_artifact_dodge = False
        if artifact_ids and p.agent is not None:
            pick = p.agent.choose_mode(
                state, controller_id,
                ["discard an artifact card", "discard two cards"],
            )
            pick = max(0, min(pick, 1))
            use_artifact_dodge = (pick == 0)

        if use_artifact_dodge:
            # Discard exactly one artifact card. Agent picks which via
            # choose_discard restricted to the artifact-card subset.
            chosen_id = p.agent.choose_discard(
                state, controller_id, artifact_ids,
            )
            # Defensive: if the agent returns a non-artifact id (out of
            # contract), fall back to the first artifact id rather than
            # crashing — keeps the "unless" semantics intact.
            if chosen_id not in artifact_ids:
                chosen_id = artifact_ids[0]
            card = next(c for c in p.hand if c.id == chosen_id)
            p.hand.remove(card)
            card.zone = Zone.GRAVEYARD
            p.graveyard.append(card)
            state.log.append(
                f"P{p.id} discards {card.printing.name} "
                f"(Alpharael artifact dodge)"
            )
            fire_opponent_discards_triggers(state, p.id)
            return

        # Fallback: discard two cards (any). Mirrors DiscardSelf(amount=2).
        for _ in range(2):
            if not p.hand:
                break
            hand_ids = [c.id for c in p.hand]
            chosen_id = p.agent.choose_discard(state, p.id, hand_ids)
            card = next(c for c in p.hand if c.id == chosen_id)
            p.hand.remove(card)
            card.zone = Zone.GRAVEYARD
            p.graveyard.append(card)
            state.log.append(f"P{p.id} discards {card.printing.name}")
            fire_opponent_discards_triggers(state, p.id)

    def describe(self) -> str:
        return "discard two cards unless you discard an artifact card"



