"""Vision Charm (Forgetful Fish): "Choose one — / • Target player mills
four cards. / • Choose a land type and a basic land type. Each land of
the first chosen type becomes the second chosen type until end of turn.
/ • Target artifact phases out." Mode 2 is a layer-4 type change: Islands
turned into Swamps sink every Dandân."""

from __future__ import annotations

from mtg_bot.cards.base import make_creature
from mtg_bot.effects.generic.fish_cards import (
    BASIC_LAND_TYPES,
    LandsOfChosenTypeBecomeBasicTypeUEOT,
    TargetArtifactPhasesOut,
)
from mtg_bot.effects.generic.draw_mill import MillTargetPlayer
from mtg_bot.game import Zone, effective_card_types, effective_subtypes
from mtg_bot.turn import run_cleanup_step

from tests._fish_helpers import cast, lands, make_state, place, printing, resolve_all, script


def _swap_index(state, first, second):
    lands_ = [o for o in state.battlefield if "Land" in effective_card_types(state, o)]
    present = {s for o in lands_ for s in effective_subtypes(state, o)}
    firsts = sorted(present | set(BASIC_LAND_TYPES))
    options = [f"{a} -> {b}" for a in firsts for b in BASIC_LAND_TYPES if a != b]
    return options.index(f"{first} -> {second}")


def test_parses_three_modes():
    modes = printing("Vision Charm").spell_effect.modes
    assert modes == (
        MillTargetPlayer(amount=4), LandsOfChosenTypeBecomeBasicTypeUEOT(),
        TargetArtifactPhasesOut(),
    )


def test_islands_become_swamps_and_every_dandan_is_sacrificed():
    state = make_state()
    mine = lands(state, 0, "Island", 2)
    lands(state, 1, "Island", 2)
    fish0 = place(state, 0, "Dandân")
    fish1 = place(state, 1, "Dandân")
    spell = place(state, 0, "Vision Charm", Zone.HAND)
    script(state, 0, "mode", 1, _swap_index(state, "Island", "Swamp"))
    cast(state, 0, spell)
    assert effective_subtypes(state, mine[0]) == ("Swamp",)
    assert fish0 not in state.battlefield and fish1 not in state.battlefield
    run_cleanup_step(state)
    assert effective_subtypes(state, mine[0]) == ("Island",)


def test_mill_four_mode():
    state = make_state()
    lands(state, 0, "Island", 1)
    for _ in range(5):
        place(state, 1, "Island", Zone.LIBRARY)
    spell = place(state, 0, "Vision Charm", Zone.HAND)
    script(state, 0, "mode", 0)
    script(state, 0, "target", ("player", 1))
    cast(state, 0, spell)
    assert len(state.players[1].library) == 1


def test_artifact_phases_out():
    state = make_state()
    art = place(state, 1, make_creature("Gizmo", "{2}", 1, 1))
    from dataclasses import replace

    art.printing = replace(art.printing, card_types=("Artifact",))
    eff = TargetArtifactPhasesOut()
    assert eff.legal_targets(state, 0) == [("permanent", art.id)]
    eff.resolve(state, 0, (("permanent", art.id),))
    assert art.phased_out
    eff.resolve(state, 0, ())
    resolve_all(state)
