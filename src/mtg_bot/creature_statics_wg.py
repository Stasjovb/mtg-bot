"""Rules-restricting static abilities printed by cube W/G creatures.

Each helper reads ``CardPrinting`` flags set by the parser
(``cards.parser.creature_wg_lines``) on permanents currently on the
battlefield:

* ``opponents_cant_cast_spells_during_your_turn`` -- "Your opponents
  can't cast spells during your turn." (Voice of Victory)
* ``each_player_one_spell_per_turn`` -- "Each player can't cast more
  than one spell each turn." (Archon of Emeria)
* ``opponents_nonbasic_lands_enter_tapped`` -- "Nonbasic lands your
  opponents control enter tapped." (Archon of Emeria)

The cast restrictions post-filter ``legal.legal_actions``'s
``CastSpell`` proposals (the plot special action isn't a cast and stays
legal); the enters-tapped replacement is applied by every land-entry
path (``actions.apply_land_etb_replacements`` and
``actions.put_into_battlefield``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mtg_bot.game import GameObject, GameState


def cast_forbidden(state: "GameState", player_id: int) -> bool:
    """Whether a static on the battlefield forbids ``player_id`` from
    casting any spell right now."""
    active_id = state.players[state.active_player_idx].id
    p = state.player_by_id(player_id)
    for o in state.battlefield:
        pr = o.printing
        if (
            pr.opponents_cant_cast_spells_during_your_turn
            and o.controller_id != player_id
            and o.controller_id == active_id
        ):
            return True
        if pr.each_player_one_spell_per_turn and p.spells_cast_this_turn >= 1:
            return True
    return False


def filter_cast_restrictions(
    state: "GameState", player_id: int, actions: list,
) -> list:
    """Drop ``CastSpell`` proposals a W/G restriction static forbids."""
    from mtg_bot.actions import CastSpell

    if not cast_forbidden(state, player_id):
        return actions
    return [
        a for a in actions
        if not (isinstance(a, CastSpell) and not a.use_plot)
    ]


def forced_to_enter_tapped(
    state: "GameState", obj: "GameObject", controller_id: int,
) -> bool:
    """"Nonbasic lands your opponents control enter tapped." applied to
    ``obj`` entering under ``controller_id``'s control."""
    pr = obj.printing
    if not pr.is_land or pr.is_basic_land:
        return False
    return any(
        o.printing.opponents_nonbasic_lands_enter_tapped
        and o.controller_id != controller_id
        for o in state.battlefield
    )


# ---------------------------------------------------------------------
# Spell cost increases (Thalia, Guardian of Thraben)
# ---------------------------------------------------------------------


def spell_cost_increase(
    state: "GameState", printing, caster_id: "int | None" = None,
) -> int:
    """Total generic increase statics on the battlefield impose on
    ``caster_id`` casting ``printing`` (CR 601.2f): "<Filter> spells cost
    {N} more to cast." (every player's spells) and "Spells your
    opponents cast with the chosen name cost {N} more to cast."."""
    total = 0
    for o in state.battlefield:
        for card_filter, amount in o.printing.spell_cost_increases:
            if card_filter.matches(printing):
                total += amount
        if (
            o.printing.named_spell_cost_increase
            and o.chosen_card_name == printing.name
            and caster_id is not None
            and caster_id != o.controller_id
        ):
            total += o.printing.named_spell_cost_increase
    return total


def ability_cost_increase(state: "GameState", source, ability) -> int:
    """"Activated abilities of sources with the chosen name cost {N} more
    to activate unless they're mana abilities." (Anointed Peacekeeper)."""
    if ability.is_mana_ability:
        return 0
    total = 0
    for o in state.battlefield:
        if (
            o.printing.named_ability_cost_increase
            and o.chosen_card_name is not None
            and o.chosen_card_name == source.printing.name
        ):
            total += o.printing.named_ability_cost_increase
    return total


def choose_card_name_as_enters(
    state: "GameState", obj: "GameObject", controller_id: int,
) -> None:
    """"As this creature enters, look at an opponent's hand, then choose
    any card name." The opponent's hand is revealed to the controller;
    the name is picked (``choose_mode``) among the names of the
    opponent's cards the controller can see -- hand, graveyard and
    battlefield (the offered set is narrowed from "any card name"; see
    ``docs/SEARCH_LIMITATIONS.md``)."""
    from mtg_bot.game import reveal_to

    opponents = [
        p for p in state.players if p.id != controller_id and not p.has_lost
    ]
    names: list[str] = []
    for opp in opponents[:1]:
        for c in opp.hand:
            reveal_to(c, controller_id)
        seen = list(opp.hand) + list(opp.graveyard) + [
            o for o in state.battlefield
            if o.controller_id == opp.id and not o.printing.is_token
        ]
        for c in seen:
            if c.printing.name not in names:
                names.append(c.printing.name)
    names.sort()
    obj.chosen_card_name = None
    if not names:
        return
    idx = 0
    agent = state.player_by_id(controller_id).agent
    if agent is not None and len(names) > 1:
        pick = agent.choose_mode(state, controller_id, names)
        if isinstance(pick, int) and 0 <= pick < len(names):
            idx = pick
    obj.chosen_card_name = names[idx]
    state.log.append(f"{obj.printing.name}: P{controller_id} names {names[idx]}")


# ---------------------------------------------------------------------
# Combat restrictions (Questing Beast)
# ---------------------------------------------------------------------


def blocking_forbidden(
    state: "GameState", blocker: "GameObject", attacker: "GameObject",
) -> bool:
    """"<Attacker> can't be blocked by <creatures with ...>." """
    restriction = attacker.printing.cant_be_blocked_by
    return restriction is not None and restriction.test(blocker, state)


def combat_damage_unpreventable(state: "GameState", source: "GameObject") -> bool:
    """Combat damage ``source`` deals can't be prevented: its own "Combat
    damage can't be prevented." or a "Combat damage that would be dealt
    by creatures you control can't be prevented." permanent its
    controller controls."""
    if source.printing.combat_damage_cant_be_prevented:
        return True
    from mtg_bot.game import is_creature_now

    if not is_creature_now(source):
        return False
    return any(
        o.printing.your_creatures_combat_damage_cant_be_prevented
        and o.controller_id == source.controller_id
        for o in state.battlefield
    )


# ---------------------------------------------------------------------
# "When <this> is put into a graveyard from anywhere" (Worldspine Wurm)
# ---------------------------------------------------------------------


def fire_graveyard_arrival_triggers(state: "GameState") -> bool:
    """Put the "put into a graveyard from anywhere" triggers of cards
    that arrived in a graveyard since the last check onto the stack
    (CR 603.3: a triggered ability goes on the stack the next time a
    player would receive priority). Returns True when any fired."""
    from mtg_bot.actions import push_triggered_ability

    fired = False
    for p in state.players:
        for card in list(p.graveyard):
            abilities = card.printing.graveyard_arrival_triggers
            if not abilities or card.graveyard_arrival_pending:
                continue
            card.graveyard_arrival_pending = True
            for ability in abilities:
                push_triggered_ability(
                    state, source=card, ability=ability, ability_index=-1,
                    controller_id=card.owner_id,
                    label="put into a graveyard",
                )
                fired = True
    return fired


# ---------------------------------------------------------------------
# Activation locks (Clarion Conqueror)
# ---------------------------------------------------------------------


def _card_types_now(obj) -> set:
    from mtg_bot.game import is_creature_now

    types = set(obj.printing.card_types)
    if is_creature_now(obj):
        types.add("Creature")
    else:
        types.discard("Creature")
    return types


def activation_locked(state: "GameState", obj: "GameObject") -> bool:
    """"Activated abilities of <types> can't be activated." -- does a
    permanent on the battlefield lock ``obj``'s activated abilities?"""
    locks = [
        o.printing.locks_activated_abilities_of for o in state.battlefield
        if o.printing.locks_activated_abilities_of
    ]
    if not locks:
        return False
    types = _card_types_now(obj)
    return any(types.intersection(lock) for lock in locks)


def filter_activation_locks(state: "GameState", actions: list) -> list:
    """Drop ``ActivateAbility`` / ``ActivateStation`` proposals whose
    battlefield source is locked."""
    if not any(o.printing.locks_activated_abilities_of for o in state.battlefield):
        return actions
    from mtg_bot.actions import ActivateAbility, ActivateStation

    by_id = {o.id: o for o in state.battlefield}
    out = []
    for a in actions:
        source_id = (
            a.source_id if isinstance(a, ActivateAbility)
            else a.spacecraft_id if isinstance(a, ActivateStation) else None
        )
        src = by_id.get(source_id) if source_id is not None else None
        if src is not None and activation_locked(state, src):
            continue
        out.append(a)
    return out


# ---------------------------------------------------------------------
# Containment Priest
# ---------------------------------------------------------------------


def exile_instead_of_entering(state: "GameState", obj: "GameObject") -> bool:
    """"If a nontoken creature would enter and it wasn't cast, exile it
    instead." -- apply the replacement to ``obj`` (about to enter the
    battlefield). "Cast" means it is the permanent spell now resolving;
    copies of spells are tokens. Returns True when ``obj`` was exiled
    instead."""
    if not any(
        o.printing.exiles_uncast_nontoken_creatures_entering
        for o in state.battlefield
    ):
        return False
    pr = obj.printing
    if not pr.is_creature or pr.is_token or obj.is_spell_copy:
        return False
    if getattr(state, "resolving_spell", None) is obj:
        return False
    from mtg_bot.game import Zone

    owner = state.player_by_id(obj.owner_id)
    obj.zone = Zone.EXILE
    owner.exile.append(obj)
    state.log.append(
        f"{pr.name} would enter without being cast -- exiled instead"
    )
    return True


# ---------------------------------------------------------------------
# Ascend (CR 702.131)
# ---------------------------------------------------------------------


def apply_ascend(state: "GameState") -> None:
    """A permanent with ascend gives its controller the city's blessing
    as soon as they control ten or more permanents (checked with the
    state-based actions)."""
    for o in state.battlefield:
        if "ascend" not in o.printing.keywords:
            continue
        p = state.player_by_id(o.controller_id)
        if p.has_citys_blessing:
            continue
        if sum(1 for x in state.battlefield if x.controller_id == p.id) >= 10:
            p.has_citys_blessing = True
            state.log.append(f"P{p.id} gets the city's blessing")
