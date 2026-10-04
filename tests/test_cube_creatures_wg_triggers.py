"""Cube W/G creatures: Titania (land put into a graveyard), Torsten (any
number from the top seven), Vaultborn Tyrant (self-or-another enters,
token copy), Enduring Innocence (batched enters, once each turn), White
Plume / Undermountain Adventurer (dungeon "instead" riders)."""

from __future__ import annotations

from mtg_bot.actions import ActivateAbility, apply_action
from mtg_bot.cards.parser.creature_wg_effects import (
    parse_wg_effect,
    parse_wg_trigger_phrase,
    trigger_subject,
)
from mtg_bot.cards.parser.creature_wg_lines import parse_wg_creature_line
from mtg_bot.effects.combinators import IfConditionElse
from mtg_bot.effects.generic.cube_creatures_wg import (
    CreateTokenCopyOfSource,
    UntapAllMatching,
    UntapChosenPermanents,
    token_copy_printing,
)
from mtg_bot.effects.object_predicates import HasPowerAtLeast
from mtg_bot.game import Zone
from mtg_bot.turn import (
    Step,
    run_beginning_of_upkeep_triggers,
    sacrifice,
)
from tests._wg_helpers import (
    add_lands,
    bear,
    cast_and_resolve,
    cube,
    drain,
    make_state,
    put,
)


# ---------------------------------------------------------------------
# Titania
# ---------------------------------------------------------------------


def test_titania_returns_land_and_makes_elementals_when_lands_hit_graveyard():
    state = make_state()
    titania = put(state, 0, "Titania, Protector of Argoth", Zone.HAND)
    add_lands(state, 0, "Forest", 5)
    gy_land = put(state, 0, "Wasteland", Zone.GRAVEYARD)
    cast_and_resolve(state, 0, titania)
    assert gy_land in state.battlefield
    sacrifice(state, gy_land)
    drain(state)
    elementals = [o for o in state.battlefield if o.printing.name == "Elemental"]
    assert len(elementals) == 1
    assert (elementals[0].printing.power, elementals[0].printing.toughness) == (5, 3)
    # An opponent's land doesn't count.
    theirs = put(state, 1, "Forest")
    sacrifice(state, theirs)
    drain(state)
    assert sum(o.printing.name == "Elemental" for o in state.battlefield) == 1


def test_land_graveyard_trigger_phrase_rejects_unknown_noun():
    assert parse_wg_trigger_phrase(
        "a wombat you control is put into a graveyard from the battlefield"
    ) is None
    assert parse_wg_trigger_phrase("something else happens") is None


# ---------------------------------------------------------------------
# Torsten
# ---------------------------------------------------------------------


def test_torsten_takes_any_number_of_creatures_and_lands():
    state = make_state()
    torsten = put(state, 0, "Torsten, Founder of Benalia", Zone.HAND)
    add_lands(state, 0, "Plains", 4)
    add_lands(state, 0, "Forest", 3)
    names = ["Llanowar Elves", "Brainstorm", "Forest", "Lightning Bolt",
             "Plains", "Birds of Paradise", "Dark Ritual", "Island"]
    lib = [put(state, 0, n, Zone.LIBRARY) for n in names]
    # Take the Elves and the Forest, then stop.
    state.players[0].agent.scripts["library"] = [lib[0].id, lib[2].id, None]
    cast_and_resolve(state, 0, torsten)
    p = state.players[0]
    assert {c.id for c in p.hand} == {lib[0].id, lib[2].id}
    assert p.library[0] is lib[7]  # the eighth card stays on top
    assert {c.id for c in p.library[1:]} == {
        lib[i].id for i in (1, 3, 4, 5, 6)
    }


def test_torsten_dies_into_seven_soldiers():
    state = make_state()
    torsten = put(state, 0, "Torsten, Founder of Benalia")
    sacrifice(state, torsten)
    drain(state)
    assert sum(o.printing.name == "Soldier" for o in state.battlefield) == 7


# ---------------------------------------------------------------------
# Vaultborn Tyrant
# ---------------------------------------------------------------------


def test_vaultborn_trigger_subject_and_copy_on_death():
    pr = cube()["Vaultborn Tyrant"]
    state = make_state()
    for _ in range(4):
        put(state, 0, "Forest", Zone.LIBRARY)
    tyrant = put(state, 0, pr, Zone.HAND)
    add_lands(state, 0, "Forest", 7)
    cast_and_resolve(state, 0, tyrant)
    p = state.players[0]
    assert p.life == 23 and len(p.hand) == 1
    # A small creature entering doesn't trigger; a big one does.
    from mtg_bot.actions import put_into_battlefield

    small = put(state, 0, bear("Small"), Zone.HAND)
    p.hand.remove(small)
    put_into_battlefield(state, small, 0)
    drain(state)
    assert p.life == 23
    big = put(state, 0, bear("Big", "{4}{G}", 4, 4), Zone.HAND)
    p.hand.remove(big)
    put_into_battlefield(state, big, 0)
    drain(state)
    assert p.life == 26
    # Dies -> token copy that's also an artifact (and the copy's own
    # death doesn't loop).
    sacrifice(state, tyrant)
    drain(state)
    copies = [o for o in state.battlefield if o.printing.name == "Vaultborn Tyrant"]
    assert len(copies) == 1
    tok = copies[0]
    assert tok.printing.is_token and tok.printing.is_artifact
    assert "Token Artifact Creature" in tok.printing.type_line
    assert p.life == 29  # the copy entering triggers itself
    sacrifice(state, tok)
    drain(state)
    assert not any(o.printing.name == "Vaultborn Tyrant" for o in state.battlefield)


def test_token_copy_helpers():
    pr = cube()["Vaultborn Tyrant"]
    once = token_copy_printing(pr, ("Artifact",))
    twice = token_copy_printing(once, ("Artifact",))
    assert twice.card_types.count("Artifact") == 1
    assert twice.supertypes.count("Token") == 1
    plain = token_copy_printing(bear("Nameless", subtypes=()))
    assert plain.type_line == "Token Creature"
    state = make_state()
    CreateTokenCopyOfSource().resolve(state, 0)  # no source: no-op
    assert "artifact" in CreateTokenCopyOfSource(("Artifact",)).describe()
    assert parse_wg_effect("create a token that's a copy of it").extra_card_types == ()


def test_trigger_subject_grammar():
    pred, controlled = trigger_subject("creature you control with power 4 or greater")
    assert controlled is not None
    assert pred.right == HasPowerAtLeast(4)
    assert trigger_subject("creatures an opponent controls")[1] is not None
    assert trigger_subject("wombat") is None
    assert trigger_subject("creature")[1] is None


# ---------------------------------------------------------------------
# Enduring Innocence
# ---------------------------------------------------------------------


def test_enduring_innocence_draws_once_per_turn():
    pr = cube()["Enduring Innocence"]
    trig = next(t for t in pr.triggered_abilities if t.once_per_turn)
    assert "lifelink" in pr.keywords
    state = make_state()
    for _ in range(3):
        put(state, 0, "Forest", Zone.LIBRARY)
    put(state, 0, pr)
    from mtg_bot.actions import put_into_battlefield

    p = state.players[0]
    for name in ("One", "Two"):
        c = put(state, 0, bear(name), Zone.HAND)
        p.hand.remove(c)
        put_into_battlefield(state, c, 0)
        drain(state)
    assert len(p.hand) == 1
    big = put(state, 0, bear("Big", "{3}", 3, 3), Zone.HAND)
    p.hand.remove(big)
    state.turn_number += 1
    put_into_battlefield(state, big, 0)
    drain(state)
    assert len(p.hand) == 1  # power 3 doesn't count
    assert trig.event.value == "enters"


def test_batched_enters_needs_once_per_turn_rider():
    card = {"name": "X"}
    assert parse_wg_creature_line(
        "Whenever one or more other creatures you control enter, draw a card.",
        card,
    ) is None
    assert parse_wg_creature_line(
        "Whenever one or more wombats enter, draw a card. This ability "
        "triggers only once each turn.", card,
    ) is None
    wg = parse_wg_creature_line(
        "Whenever one or more creatures enter, draw a card. This ability "
        "triggers only once each turn.", card,
    )
    assert wg.triggers[0].once_per_turn


# ---------------------------------------------------------------------
# White Plume / Undermountain Adventurer
# ---------------------------------------------------------------------


def test_white_plume_untaps_on_opponents_upkeep():
    pr = cube()["White Plume Adventurer"]
    state = make_state(step=Step.UPKEEP)
    put(state, 0, pr)
    a = put(state, 0, bear("A"))
    b = put(state, 0, bear("B"))
    a.tapped = b.tapped = True
    state.active_player_idx = 1
    run_beginning_of_upkeep_triggers(state)
    drain(state)
    assert [a.tapped, b.tapped].count(False) == 1
    a.tapped = b.tapped = True
    state.players[0].dungeons_completed = 1
    run_beginning_of_upkeep_triggers(state)
    drain(state)
    assert not a.tapped and not b.tapped
    # Not on its controller's own upkeep.
    a.tapped = True
    state.active_player_idx = 0
    run_beginning_of_upkeep_triggers(state)
    drain(state)
    assert a.tapped


def test_untap_effects_edges():
    state = make_state()
    eff = parse_wg_effect("untap a creature you control")
    assert isinstance(eff, UntapChosenPermanents)
    eff.resolve(state, 0)  # nothing tapped
    theirs = put(state, 1, bear("Theirs"))
    theirs.tapped = True
    eff.resolve(state, 0)
    assert theirs.tapped
    assert "untap" in eff.describe()
    all_eff = parse_wg_effect("untap all creatures you control")
    assert isinstance(all_eff, UntapAllMatching) and "all" in all_eff.describe()
    assert parse_wg_effect("untap a wombat") is None
    assert parse_wg_effect("untap all wombats") is None


def test_undermountain_mana_ability():
    pr = cube()["Undermountain Adventurer"]
    ab = next(a for a in pr.activated_abilities if a.is_mana_ability)
    assert isinstance(ab.effect, IfConditionElse)
    state = make_state()
    und = put(state, 0, pr)
    idx = pr.activated_abilities.index(ab)
    apply_action(state, 0, ActivateAbility(source_id=und.id, ability_index=idx))
    assert len(state.players[0].mana_pool) == 2
    state.players[0].mana_pool.clear()
    und.tapped = False
    state.players[0].dungeons_completed = 1
    apply_action(state, 0, ActivateAbility(source_id=und.id, ability_index=idx))
    assert len(state.players[0].mana_pool) == 6


def test_instead_rider_rejects_unknown_condition_and_bodies():
    assert parse_wg_effect(
        "add {G}. If you control a wombat, add {G}{G} instead"
    ) is None
    assert parse_wg_effect(
        "add {G}. If you've completed a dungeon, dance instead"
    ) is None
    assert parse_wg_effect("add 3 {C}").produces == (("C", 3),)
