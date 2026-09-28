"""Turn-scoped characteristic statics for the cube glue bucket.

Kaito, Bane of Nightmares: "During your turn, as long as Kaito has one or
more loyalty counters on him, he's a 3/4 Ninja creature and has
hexproof." (``CardPrinting.creature_during_your_turn``). The engine's
``is_creature_now`` has no game-state argument, so the static is applied
as UEOT registry entries (layer 4 ``add_type`` / ``add_subtype``, layer 6
``grant_keyword``, layer 7b ``set_base_pt``, ``expires_at="cleanup"``)
whenever its controller's turn begins (``turn.run_untap_step``) and when
the permanent enters during its controller's turn
(``actions.put_into_battlefield``); the cleanup step expires them. The
"one or more loyalty counters" condition isn't re-checked: a walker
without loyalty counters is put into the graveyard by the next
state-based-action check. See the "glue" section of
``docs/SEARCH_LIMITATIONS.md``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mtg_bot.game import GameObject, GameState


def apply_creature_during_your_turn(state: "GameState") -> None:
    """Apply the static to every such permanent the active player
    controls (called as the turn begins)."""
    ap_id = state.active_player().id
    for obj in state.battlefield:
        if obj.printing.creature_during_your_turn and obj.controller_id == ap_id:
            animate_for_turn(state, obj)


def animate_for_turn(state: "GameState", obj: "GameObject") -> None:
    """Write the UEOT entries for ``obj``'s creature-during-your-turn
    static (no-op when it lost its abilities or has no loyalty)."""
    from mtg_bot.game import _source_layer6_wiped

    spec = obj.printing.creature_during_your_turn
    if not spec:
        return
    if state.continuous_effects and _source_layer6_wiped(state, obj):
        return
    if obj.printing.is_planeswalker and obj.loyalty_counters <= 0:
        return
    power, toughness, subtypes, keywords = spec
    name = obj.printing.name
    state.add_continuous_effect(
        source_id=obj.id, layer=4, kind="add_type", target_id=obj.id,
        params=("creature",), expires_at="cleanup",
        description=f"{name} is a creature during its controller's turn",
    )
    obj.permanent_is_creature = True
    for sub in subtypes:
        state.add_continuous_effect(
            source_id=obj.id, layer=4, kind="add_subtype", target_id=obj.id,
            params=(sub,), expires_at="cleanup",
            description=f"{name} is a {sub}",
        )
    for kw in sorted(keywords):
        state.add_continuous_effect(
            source_id=obj.id, layer=6, kind="grant_keyword",
            target_id=obj.id, params=(kw,), expires_at="cleanup",
            description=f"{name} has {kw}",
        )
    state.add_continuous_effect(
        source_id=obj.id, layer=7, sublayer=1, kind="set_base_pt",
        target_id=obj.id, params=(power, toughness), expires_at="cleanup",
        description=f"{name} base {power}/{toughness}",
    )


def on_enters_battlefield(state: "GameState", obj: "GameObject") -> None:
    """A permanent with the static entering during its controller's turn
    is a creature at once; it hasn't been controlled continuously since
    the turn began (CR 302.6), so it's summoning-sick."""
    if not obj.printing.creature_during_your_turn:
        return
    if state.active_player().id != obj.controller_id:
        return
    animate_for_turn(state, obj)
    if obj.permanent_is_creature:
        obj.summoning_sick = True
