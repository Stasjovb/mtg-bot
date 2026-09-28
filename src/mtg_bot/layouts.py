"""Engine support for the non-normal card layouts (cube layouts bucket).

Every layout here works by turning the object to another ``CardPrinting``
-- the object's characteristics are exactly ``obj.printing`` everywhere
in the engine, so a face change is a printing swap:

* **Transforming double-faced cards** (CR 712, 701.28): the front
  printing carries ``transform_back_face``. :func:`transform_permanent`
  turns a permanent to its other face (the front is kept in
  ``GameObject.mdfc_front_printing``, the same snapshot a modal DFC
  played as its land face uses); every zone change restores the front
  (``game.restore_mdfc_front``). :func:`put_onto_battlefield_transformed`
  covers "return it to the battlefield transformed".
* **Modal double-faced cards** with a castable back face and **split
  cards** (CR 709): :func:`castable_faces` lists the faces a card may be
  cast as; :func:`turn_to_face` flips the card to the chosen face as it
  is cast (``CastSpell(cast_face=<name>)``). A spell that leaves the
  stack for anywhere but the battlefield is turned back
  (``actions.move_spell_off_stack``).
* **Sagas** (CR 714): chapter abilities are triggered abilities with
  ``trigger == "chapter_<N>"``; :func:`add_lore_counters` fires every
  chapter whose number the lore count reaches, and the state-based
  sacrifice waits while a chapter ability of the Saga is on the stack.
* **Classes** (CR 716): each level is its own printing
  (``CardPrinting.class_levels``); :func:`gain_class_level` turns the
  Class to the new level's printing and fires "When this Class becomes
  level N".
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from mtg_bot.cards.base import CardPrinting
    from mtg_bot.game import GameObject, GameState


# ---------------------------------------------------------------------------
# Double-faced cards
# ---------------------------------------------------------------------------


def transform_back_face(printing: "CardPrinting") -> "CardPrinting | None":
    """The face ``printing`` transforms into, or ``None`` when it isn't
    the front face of a transformable double-faced card."""
    back = printing.transform_back_face
    if back is not None:
        return back
    return None


def front_face(obj: "GameObject") -> "CardPrinting":
    """The printing the card shows outside the battlefield and stack."""
    return obj.mdfc_front_printing or obj.printing


def _same_face(a: "CardPrinting | None", b: "CardPrinting") -> bool:
    return a is not None and (a is b or a == b)


def is_transformed(obj: "GameObject") -> bool:
    """True while a transforming DFC permanent has its back face up."""
    front = obj.mdfc_front_printing
    return front is not None and _same_face(
        transform_back_face(front), obj.printing,
    )


def transform_permanent(
    state: "GameState", obj: "GameObject", *, by_day_night: bool = False,
) -> bool:
    """Transform ``obj`` (CR 701.28a): turn it to its other face.

    The object keeps its counters, damage, tapped / attacking status and
    summoning sickness (it is the same object). A permanent that isn't a
    transformable double-faced card doesn't transform (CR 701.28c).
    Dispatches ``Event.TRANSFORMS`` ("When this creature transforms into
    <face>") after the face change. Returns whether it transformed."""
    if obj not in state.battlefield:
        return False
    if (obj.printing.daybound or obj.printing.nightbound) and not by_day_night:
        # CR 702.145b/d: it transforms only through day and night.
        state.log.append(f"{obj.printing.name} can't transform (daybound)")
        return False
    front = obj.mdfc_front_printing
    if front is None:
        back = transform_back_face(obj.printing)
        if back is None:
            state.log.append(f"{obj.printing.name} can't transform")
            return False
        obj.mdfc_front_printing = obj.printing
        obj.printing = back
    else:
        if not _same_face(transform_back_face(front), obj.printing):
            # A land played as its modal-DFC land face, a split half, a
            # Class level: not a transforming face.
            state.log.append(f"{obj.printing.name} can't transform")
            return False
        obj.printing = front
        obj.mdfc_front_printing = None
    state.log.append(f"{front_face(obj).name} transforms into {obj.printing.name}")
    from mtg_bot.actions import dispatch_event
    from mtg_bot.effects.predicates import Event

    dispatch_event(state, Event.TRANSFORMS, label="transforms", obj=obj)
    return True


def turn_to_back_face(obj: "GameObject", back: "CardPrinting") -> None:
    """Turn a card (off the battlefield) to ``back``, remembering the
    front face so it is restored when the card changes zones."""
    if obj.mdfc_front_printing is None:
        obj.mdfc_front_printing = obj.printing
    obj.printing = back


def put_onto_battlefield_transformed(
    state: "GameState", card: "GameObject", controller_id: int,
) -> bool:
    """Put ``card`` (in some non-battlefield zone, already removed from
    it by the caller) onto the battlefield with its back face up. A
    card that isn't a transforming DFC isn't put onto the battlefield
    (CR 701.28c / 712.14): returns False and the caller leaves it where
    it was."""
    from mtg_bot.actions import put_into_battlefield

    back = transform_back_face(front_face(card))
    if back is None:
        return False
    turn_to_back_face(card, back)
    put_into_battlefield(state, card, controller_id)
    return True


# ---------------------------------------------------------------------------
# Casting a chosen face (modal DFC back faces, split-card halves)
# ---------------------------------------------------------------------------


def castable_faces(printing: "CardPrinting") -> tuple["CardPrinting", ...]:
    """Faces other than the card's own printing it may be cast as: the
    halves of a split card (CR 709.3) and a modal DFC's nonland back
    face (CR 712.11)."""
    if printing.split_faces:
        return tuple(printing.split_faces)
    if printing.adventure_face is not None:
        return (printing.adventure_face,)
    back = printing.mdfc_back_face
    if back is not None and not back.is_land:
        return (back,)
    return ()


def face_named(printing: "CardPrinting", name: str) -> "CardPrinting | None":
    return next((f for f in castable_faces(printing) if f.name == name), None)


def turn_to_face(card: "GameObject", face: "CardPrinting") -> None:
    """Turn ``card`` to ``face`` as it's cast (CR 709.3a / 712.11a: the
    spell has only that face's characteristics)."""
    turn_to_back_face(card, face)


def _face_card_zones(state: "GameState", player_id: int) -> list[list]:
    """Zones a player may cast a card from: their hand, graveyard and
    exile, the top of their library, and other players' exile (exile
    play permissions)."""
    p = state.player_by_id(player_id)
    zones: list[list] = [p.hand, p.graveyard, p.exile]
    if p.library:
        zones.append(p.library[:1])
    zones.extend(o.exile for o in state.players if o.id != player_id)
    return zones


def find_face_card(state: "GameState", player_id: int, card_id: int):
    """The card ``card_id`` in one of :func:`_face_card_zones`."""
    for zone in _face_card_zones(state, player_id):
        for c in zone:
            if c.id == card_id:
                return c
    return None


def face_cast_actions(state: "GameState", player_id: int, actions: list, core) -> list:
    """Add ``CastSpell(..., cast_face=<name>)`` for every castable face
    of every card the player could cast (``castable_faces``), and drop
    the plain cast of a split card (CR 709.3: it's always cast as one
    half).

    Each face's legality is exactly the legality of casting a card
    with that face's printing: the card is turned to the face, the
    core enumerator ``core(state, player_id)`` runs, and its casts of
    that card are kept (timing, cost, targets, alternative costs and
    cast restrictions all come from the one enumerator). No extra work
    unless such a card is in one of the player's castable zones."""
    from dataclasses import replace

    from mtg_bot.actions import CastSpell

    cards = [
        (zi, c)
        for zi, zone in enumerate(_face_card_zones(state, player_id))
        for c in zone
        if castable_faces(c.printing)
    ]
    if not cards:
        return actions
    split_ids = {c.id for _, c in cards if c.printing.split_faces}
    out = [
        a for a in actions
        if not (
            isinstance(a, CastSpell) and a.card_id in split_ids
            and a.cast_face is None
        )
    ]
    seen: set = set()
    for zi, card in cards:
        orig = card.printing
        perm = card.exile_play_permission
        if perm is not None and getattr(perm, "primary_only", False):
            # On an adventure: only the creature may be cast (CR 715.3d).
            continue
        for face in castable_faces(orig):
            card.printing = face
            try:
                sub = core(state, player_id)
            finally:
                card.printing = orig
            for a in sub:
                if not isinstance(a, CastSpell) or a.card_id != card.id or a.use_plot:
                    continue
                cast = replace(a, cast_face=face.name)
                # Same-named copies in one zone are interchangeable (the
                # hand-cast dedup of the core enumerator).
                key = (zi, orig.name, replace(cast, card_id=-1))
                if key in seen:
                    continue
                seen.add(key)
                out.append(cast)
    return out


# ---------------------------------------------------------------------------
# Sagas (CR 714)
# ---------------------------------------------------------------------------

_ROMAN = ("", "I", "II", "III", "IV", "V", "VI")


def chapter_number(ability) -> int:
    """The chapter number of a Saga chapter ability (``trigger ==
    "chapter_<N>"``), else 0."""
    trigger = getattr(ability, "trigger", "") or ""
    if trigger.startswith("chapter_"):
        return int(trigger[len("chapter_"):])
    return 0


def add_lore_counters(state: "GameState", obj: "GameObject", amount: int) -> int:
    """Put ``amount`` lore counters on ``obj`` (CR 714.2b): each chapter
    ability whose number the lore count newly reaches or passes
    triggers (in chapter order). Returns the number added."""
    from mtg_bot.actions import push_triggered_ability

    if amount <= 0:
        return 0
    before = obj.lore_counters
    obj.lore_counters = before + amount
    state.log.append(
        f"{obj.printing.name} gets {amount} lore counter(s) "
        f"({obj.lore_counters})"
    )
    chapters = sorted(
        (chapter_number(ab), idx, ab)
        for idx, ab in enumerate(obj.printing.triggered_abilities)
        if chapter_number(ab)
    )
    for n, idx, ab in chapters:
        if before < n <= obj.lore_counters:
            push_triggered_ability(
                state, source=obj, ability=ab, ability_index=idx,
                controller_id=obj.controller_id,
                label=f"chapter {_ROMAN[n] if n < len(_ROMAN) else n}",
            )
    return amount


def saga_enters(state: "GameState", obj: "GameObject") -> None:
    """"As this Saga enters, add a lore counter" (CR 714.3a): the Saga
    enters with one lore counter, triggering chapter I."""
    obj.lore_counters = 0
    add_lore_counters(state, obj, 1)


def run_saga_lore_counters(state: "GameState") -> None:
    """The turn-based action of CR 714.3b: the active player puts a lore
    counter on each Saga they control (after the draw step -- see
    ``turn.run_draw_step``)."""
    ap = state.active_player()
    for obj in list(state.battlefield):
        if obj.controller_id == ap.id and obj.printing.is_saga:
            add_lore_counters(state, obj, 1)


def chapter_ability_on_stack(state: "GameState", obj: "GameObject") -> bool:
    """True while a chapter ability of ``obj`` has triggered and not yet
    left the stack (CR 714.4 holds off the final-chapter sacrifice)."""
    return any(
        item.source is obj and item.ability is not None
        and chapter_number(item.ability)
        for item in state.stack
    )


# ---------------------------------------------------------------------------
# Classes (CR 716)
# ---------------------------------------------------------------------------


def gain_class_level(state: "GameState", obj: "GameObject", level: int) -> bool:
    """Turn the Class ``obj`` to its level-``level`` printing (which
    carries every ability of the levels up to it) and fire its "When
    this Class becomes level <level>" abilities. Returns whether the
    level was gained."""
    from mtg_bot.actions import push_triggered_ability

    base = front_face(obj)
    idx = level - 2
    if idx < 0 or idx >= len(base.class_levels):
        return False
    turn_to_back_face(obj, base.class_levels[idx])
    state.log.append(f"{obj.printing.name} becomes level {level}")
    key = f"class_level_{level}"
    for i, ab in enumerate(obj.printing.triggered_abilities):
        if getattr(ab, "trigger", "") == key:
            push_triggered_ability(
                state, source=obj, ability=ab, ability_index=i,
                controller_id=obj.controller_id, label=f"level {level}",
            )
    return True


# ---------------------------------------------------------------------------
# "Whenever <source> deals damage" (Event.DEALS_DAMAGE)
# ---------------------------------------------------------------------------


def fire_deals_damage(state: "GameState", source, amount: int) -> None:
    """Dispatch ``Event.DEALS_DAMAGE`` for ``source`` having dealt
    ``amount`` damage in one event. Skipped unless some permanent (or
    emblem) observes the event -- the common case costs one scan."""
    from mtg_bot.effects.predicates import Event

    if source is None or amount <= 0 or not hasattr(source, "printing"):
        return
    if not any(
        ab.event is Event.DEALS_DAMAGE
        for o in (*state.battlefield, *state.emblems)
        for ab in o.printing.triggered_abilities
    ):
        return
    from mtg_bot.actions import dispatch_event

    dispatch_event(
        state, Event.DEALS_DAMAGE, label="deals damage",
        combat_damage_amount=amount, source=source,
    )


def fire_combat_deals_damage(
    state: "GameState", events: "list[tuple[int, int, int]]",
) -> None:
    """Combat damage is one simultaneous event per source (CR 510.2):
    sum each source's damage over its targets and fire once."""
    totals: dict[int, int] = {}
    for source_id, _target, amount in events:
        totals[source_id] = totals.get(source_id, 0) + amount
    for source_id, amount in totals.items():
        source = next((o for o in state.battlefield if o.id == source_id), None)
        fire_deals_damage(state, source, amount)


# ---------------------------------------------------------------------------
# Day and night (CR 726, daybound / nightbound CR 702.145)
# ---------------------------------------------------------------------------


def set_day_night(state: "GameState", value: str) -> None:
    """It becomes ``value`` ("day" / "night"). As it becomes night each
    front-face-up daybound permanent transforms; as it becomes day each
    nightbound permanent (back face up) transforms (CR 702.145b/d)."""
    if state.day_night == value:
        return
    state.day_night = value
    state.log.append(f"it becomes {value}")
    for obj in list(state.battlefield):
        if value == "night" and obj.printing.daybound:
            transform_permanent(state, obj, by_day_night=True)
        elif value == "day" and obj.printing.nightbound:
            transform_permanent(state, obj, by_day_night=True)


def run_day_night_check(state: "GameState") -> None:
    """CR 726.3a, as the untap step begins: if it's day and the previous
    turn's active player cast no spells during that turn, it becomes
    night; if it's night and they cast two or more, it becomes day."""
    n = state.previous_turn_active_spells
    if n < 0:
        return
    if state.day_night == "day" and n == 0:
        set_day_night(state, "night")
    elif state.day_night == "night" and n >= 2:
        set_day_night(state, "day")


def day_night_enters(state: "GameState", obj: "GameObject") -> None:
    """A daybound permanent entering while it's night enters transformed
    (CR 702.145b) -- a replacement, not a transformation."""
    if state.day_night == "night" and obj.printing.daybound:
        back = transform_back_face(obj.printing)
        if back is not None:
            turn_to_back_face(obj, back)


# ---------------------------------------------------------------------------
# Waterbend (Avatar: The Last Airbender)
# ---------------------------------------------------------------------------


def waterbend_helpers(state: "GameState", player_id: int) -> list:
    """Untapped artifacts and creatures ``player_id`` controls -- each can
    be tapped to pay {1} of a waterbend cost (summoning sickness doesn't
    matter: tapping it isn't an activated ability's {T} cost)."""
    from mtg_bot.game import is_creature_now

    return [
        o for o in state.battlefield
        if o.controller_id == player_id and not o.tapped
        and (o.printing.is_artifact or is_creature_now(o))
    ]


def pay_waterbend(state, player_id: int, source, mana, spell_kind):
    """Tap helpers for the generic part of a waterbend cost and return
    the rest of the cost. The controller picks how many to tap
    (``choose_x``; at least as many as the rest of their mana can't
    cover) and which (``choose_permanent_to_tap``)."""
    from mtg_bot.actions import can_pay_cost
    from mtg_bot.turn import tap_permanent

    helpers = waterbend_helpers(state, player_id)
    upper = min(mana.generic, len(helpers))
    lower = 0
    while lower < upper and not can_pay_cost(
        state, player_id, mana.reduced(lower), spell_kind,
    ):
        lower += 1
    agent = state.player_by_id(player_id).agent
    k = lower
    if agent is not None and upper > lower:
        k = max(lower, min(upper, agent.choose_x(
            state, player_id, f"{source.printing.name} (waterbend helpers)",
            upper,
        )))
    for _ in range(k):
        pick = helpers[0]
        if agent is not None and len(helpers) > 1:
            chosen = agent.choose_permanent_to_tap(
                state, player_id, [o.id for o in helpers],
            )
            pick = next((o for o in helpers if o.id == chosen), helpers[0])
        helpers.remove(pick)
        tap_permanent(state, pick)
    if k:
        state.log.append(f"P{player_id} taps {k} permanent(s) to waterbend")
    return mana.reduced(k)


# ---------------------------------------------------------------------------
# Mayhem granted to graveyard cards (Green Goblin)
# ---------------------------------------------------------------------------


def mayhem_castable(state: "GameState", player_id: int, card) -> bool:
    """Mayhem (CR 702.xxx, Marvel's Spider-Man): ``card`` -- a nonland
    card in ``player_id``'s graveyard -- may be cast for its mayhem cost
    (here its mana cost) if they discarded it this turn, while they
    control a permanent granting their graveyard cards mayhem."""
    if card.printing.is_land or card.discarded_turn != state.turn_number:
        return False
    if card not in state.player_by_id(player_id).graveyard:
        return False
    return any(
        o.controller_id == player_id and o.printing.grants_mayhem_to_graveyard
        for o in state.battlefield
    )


# ---------------------------------------------------------------------------
# Adventures (CR 715)
# ---------------------------------------------------------------------------


def is_adventure_cast(card) -> bool:
    """True while ``card`` is a spell cast as its Adventure."""
    front = card.mdfc_front_printing
    return (
        front is not None and front.adventure_face is not None
        and _same_face(front.adventure_face, card.printing)
    )


def exile_on_adventure(state: "GameState", card, controller_id: int) -> None:
    """As a spell cast as an Adventure resolves, its controller exiles it
    instead of putting it into the graveyard; for as long as it stays
    exiled they may cast it with its primary characteristics (CR 715.4)."""
    from mtg_bot.effects.generic.cube_creatures_rmc import (
        WHILE_EXILED,
        grant_exile_play,
    )
    from mtg_bot.game import Zone, restore_mdfc_front

    restore_mdfc_front(card)
    owner = state.player_by_id(card.owner_id)
    card.zone = Zone.EXILE
    owner.exile.append(card)
    grant_exile_play(
        state, card, controller_id, duration=WHILE_EXILED, cast_only=True,
        primary_only=True,
    )
    state.log.append(f"{card.printing.name} goes on an adventure (exiled)")


# ---------------------------------------------------------------------------
# Prepare (Secrets of Strixhaven)
# ---------------------------------------------------------------------------


def become_prepared(state: "GameState", obj) -> bool:
    """``obj`` becomes prepared: its controller creates a copy of its
    prepare spell in exile, castable by them while ``obj`` stays on the
    battlefield and prepared. A creature without a prepare spell, or
    already prepared, doesn't (again). Returns whether it became prepared."""
    from mtg_bot.effects.generic.cube_creatures_rmc import (
        WHILE_EXILED,
        grant_exile_play,
    )
    from mtg_bot.game import Zone

    spell = front_face(obj).prepare_spell
    if spell is None or obj.prepared_copy_id >= 0 or obj not in state.battlefield:
        return False
    controller = state.player_by_id(obj.controller_id)
    copy = state.new_object(spell, owner_id=controller.id, zone=Zone.EXILE)
    copy.is_spell_copy = True
    copy.prepare_copy_of = obj.id
    controller.exile.append(copy)
    grant_exile_play(
        state, copy, controller.id, duration=WHILE_EXILED, cast_only=True,
    )
    obj.prepared_copy_id = copy.id
    state.log.append(f"{obj.printing.name} becomes prepared ({spell.name})")
    return True


def stop_being_prepared(state: "GameState", obj) -> None:
    """``obj`` stops being prepared; the copy of its prepare spell still
    in exile ceases to exist."""
    if obj.prepared_copy_id < 0:
        return
    for p in state.players:
        for c in p.exile:
            if c.id == obj.prepared_copy_id:
                p.exile.remove(c)
                break
    obj.prepared_copy_id = -1


def prepare_copy_cast(state: "GameState", card) -> None:
    """As its controller casts the copy of a prepare spell, the creature
    it belongs to stops being prepared."""
    for obj in state.battlefield:
        if obj.id == card.prepare_copy_of and obj.prepared_copy_id == card.id:
            obj.prepared_copy_id = -1
            state.log.append(f"{obj.printing.name} is no longer prepared")
    card.prepare_copy_of = -1
