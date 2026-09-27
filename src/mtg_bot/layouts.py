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


def transform_permanent(state: "GameState", obj: "GameObject") -> bool:
    """Transform ``obj`` (CR 701.28a): turn it to its other face.

    The object keeps its counters, damage, tapped / attacking status and
    summoning sickness (it is the same object). A permanent that isn't a
    transformable double-faced card doesn't transform (CR 701.28c).
    Dispatches ``Event.TRANSFORMS`` ("When this creature transforms into
    <face>") after the face change. Returns whether it transformed."""
    if obj not in state.battlefield:
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
