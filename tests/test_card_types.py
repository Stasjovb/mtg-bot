"""``mtg_bot.effects.card_types``: the one shared "card types among
cards in <zone>" definition, and every cube consumer of it -- Delirium
(Dragon's Rage Channeler, Unholy Heat, Fear of Missing Out, Shifting
Woodland), the Lhurgoyfs, Ursine Monstrosity, Keen-Eyed Curator, Occult
Epiphany and Atraxa."""

from __future__ import annotations

import dataclasses

import pytest

from mtg_bot.actions import DeclareAttackers, apply_action, resolve_top_of_stack
from mtg_bot.cards.review_render import summarize_printing
from mtg_bot.designations import forced_attackers
from mtg_bot.effects.card_types import (
    CARD_TYPES,
    DELIRIUM_THRESHOLD,
    card_types_of,
    count_card_types,
    delirium_active,
    distinct_card_types,
)
from mtg_bot.effects.conditions import DeliriumActive
from mtg_bot.effects.state_predicates import Delirium
from mtg_bot.game import Zone, effective_keywords, effective_power, effective_toughness
from mtg_bot.turn import Step, move_off_battlefield
from tests._rmc_helpers import (
    activate,
    add,
    add_lands,
    can_activate,
    cast,
    cube_printings,
    make_state,
    printing,
)


def _with_types(state, pid, types, zone=Zone.GRAVEYARD, name="Lightning Bolt"):
    """A card whose printing carries exactly ``types`` (a synthetic
    variant of a real printing)."""
    card = add(state, pid, name, zone)
    card.printing = dataclasses.replace(card.printing, card_types=tuple(types))
    return card


def _four_type_graveyard(state, pid=0):
    # land, instant, artifact (+ creature), sorcery
    for name in ("Island", "Lightning Bolt", "Walking Ballista", "Ponder"):
        add(state, pid, name, Zone.GRAVEYARD)


# ---------------------------------------------------------------- helper


def test_card_types_are_the_cr_205_2a_list():
    assert CARD_TYPES == (
        "Artifact", "Battle", "Creature", "Enchantment", "Instant",
        "Kindred", "Land", "Planeswalker", "Sorcery",
    )
    assert DELIRIUM_THRESHOLD == 4


def test_supertypes_and_subtypes_do_not_count():
    state = make_state()
    card = add(state, 0, "Gemstone Caverns", Zone.GRAVEYARD)  # Legendary Land
    assert card_types_of(card) == frozenset({"Land"})
    goblin = add(state, 0, "Walking Ballista", Zone.GRAVEYARD)
    assert card_types_of(goblin) == frozenset({"Artifact", "Creature"})


def test_kindred_counts_and_tribal_is_the_same_type():
    state = make_state()
    kindred = _with_types(state, 0, ("Kindred", "Instant"))
    tribal = _with_types(state, 0, ("Tribal", "Sorcery"))
    assert card_types_of(kindred) == frozenset({"Kindred", "Instant"})
    assert card_types_of(tribal) == frozenset({"Kindred", "Sorcery"})
    assert distinct_card_types([kindred, tribal]) == frozenset(
        {"Kindred", "Instant", "Sorcery"}
    )


def test_split_card_contributes_both_halves():
    state = make_state()
    card = add(state, 0, "Life // Death", Zone.GRAVEYARD)
    first, second = card.printing.split_faces
    mixed = dataclasses.replace(
        card.printing, card_types=("Instant",),
        split_faces=(
            dataclasses.replace(first, card_types=("Instant",)),
            dataclasses.replace(second, card_types=("Sorcery",)),
        ),
    )
    card.printing = mixed
    assert card_types_of(card) == frozenset({"Instant", "Sorcery"})


def test_modal_dfc_counts_only_its_front_face():
    state = make_state()
    smashing = add(state, 0, "Shatterskull Smashing // Shatterskull, the Hammer Pass", Zone.GRAVEYARD)
    assert card_types_of(smashing) == frozenset({"Sorcery"})
    stupor = add(state, 0, "Sink into Stupor // Soporific Springs", Zone.GRAVEYARD)
    assert card_types_of(stupor) == frozenset({"Instant"})


def test_adventurer_counts_only_its_normal_characteristics():
    state = make_state()
    borrower = add(state, 0, "Brazen Borrower // Petty Theft", Zone.GRAVEYARD)
    assert card_types_of(borrower) == frozenset({"Creature"})


def test_a_face_snapshot_left_behind_still_reads_the_front_face():
    """A card whose printing is still a back face (a zone move that
    didn't turn it front face up) is counted by its front face."""
    state = make_state()
    fable = add(state, 0, "Fable of the Mirror-Breaker // Reflection of Kiki-Jiki", Zone.GRAVEYARD)
    front = fable.printing
    fable.mdfc_front_printing = front
    fable.printing = front.transform_back_face
    assert card_types_of(fable) == frozenset({"Enchantment"})


def test_transformed_dfc_dying_is_its_front_face_in_the_graveyard():
    state = make_state()
    fable = add(state, 0, "Fable of the Mirror-Breaker // Reflection of Kiki-Jiki")
    fable.mdfc_front_printing = fable.printing
    fable.printing = fable.printing.transform_back_face
    move_off_battlefield(state, fable)
    assert fable in state.players[0].graveyard
    assert card_types_of(fable) == frozenset({"Enchantment"})


def test_tokens_and_spell_copies_are_not_cards():
    state = make_state()
    token = add(state, 0, "Walking Ballista", Zone.GRAVEYARD)
    token.printing = dataclasses.replace(
        token.printing, supertypes=token.printing.supertypes + ("Token",),
    )
    assert token.printing.is_token
    assert card_types_of(token) == frozenset()
    copy = add(state, 0, "Lightning Bolt", Zone.GRAVEYARD)
    copy.is_spell_copy = True
    assert card_types_of(copy) == frozenset()


def test_count_and_distinct():
    state = make_state()
    cards = [
        add(state, 0, n, Zone.GRAVEYARD)
        for n in ("Island", "Lightning Bolt", "Chain Lightning", "Walking Ballista")
    ]
    assert distinct_card_types(cards) == frozenset(
        {"Land", "Instant", "Sorcery", "Artifact", "Creature"}
    )
    assert count_card_types(cards) == 5
    assert count_card_types([]) == 0


def test_delirium_active_counts_only_that_players_graveyard():
    state = make_state()
    for name in ("Island", "Lightning Bolt", "Ponder"):
        add(state, 0, name, Zone.GRAVEYARD)
    add(state, 1, "Walking Ballista", Zone.GRAVEYARD)
    assert not delirium_active(state, 0)
    assert delirium_active(state, 0, threshold=3)
    add(state, 0, "Mox Pearl", Zone.GRAVEYARD)
    assert delirium_active(state, 0)
    assert not delirium_active(state, 1)
    assert not delirium_active(state, 99)  # unknown player
    assert delirium_active(state, 1, threshold=0)


def test_delirium_counts_types_not_cards():
    state = make_state()
    for _ in range(6):
        add(state, 0, "Lightning Bolt", Zone.GRAVEYARD)
    assert not delirium_active(state, 0)


# ---------------------------------------------------- the two condition tiers


def test_both_delirium_tiers_share_one_definition(monkeypatch):
    import mtg_bot.effects.card_types as ct

    calls = []

    def fake(state, player_id, threshold=4):
        calls.append((player_id, threshold))
        return True

    monkeypatch.setattr(ct, "delirium_active", fake)
    state = make_state()
    assert Delirium().test(state, 1)
    assert DeliriumActive().matches(state, 0)
    assert Delirium(min_card_types=3).test(state, 0)
    assert calls == [(1, 4), (0, 4), (0, 3)]


def test_every_cube_delirium_condition_is_the_shared_one_with_threshold_four():
    """Walk every cube printing: each delirium check is one of the two
    shared tiers carrying the printed threshold -- no per-card copy."""
    found: list = []

    def walk(obj, seen):
        if id(obj) in seen or isinstance(obj, (str, int, float, bool, type(None))):
            return
        seen.add(id(obj))
        if isinstance(obj, (Delirium, DeliriumActive)):
            found.append(obj)
            return
        if "delirium" in type(obj).__name__.lower():
            found.append(obj)
        if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
            for f in dataclasses.fields(obj):
                walk(getattr(obj, f.name, None), seen)
        elif isinstance(obj, (tuple, list, frozenset, set)):
            for x in obj:
                walk(x, seen)

    by_card = {}
    for name in (
        "Dragon's Rage Channeler", "Unholy Heat", "Fear of Missing Out",
        "Shifting Woodland",
    ):
        found.clear()
        walk(cube_printings()[name], set())
        by_card[name] = list(found)
    for name, conds in by_card.items():
        assert conds, name
        for c in conds:
            assert type(c) in (Delirium, DeliriumActive), (name, c)
            assert c.min_card_types == 4, (name, c)


def test_review_summary_shows_the_threshold():
    text = summarize_printing(cube_printings()["Dragon's Rage Channeler"]).to_text()
    assert "Delirium active (min card types: 4)" in text
    text = summarize_printing(cube_printings()["Fear of Missing Out"]).to_text()
    assert "Delirium (min card types: 4)" in text


# ------------------------------------------------------------ consumers


def test_dragons_rage_channeler_static_turns_on_and_off():
    state = make_state()
    drc = add(state, 0, "Dragon's Rage Channeler")
    for name in ("Island", "Lightning Bolt", "Ponder"):
        add(state, 0, name, Zone.GRAVEYARD)
    assert (effective_power(state, drc), effective_toughness(state, drc)) == (1, 1)
    assert "flying" not in effective_keywords(state, drc)
    assert forced_attackers(state, 0) == []
    # An MDFC land in the graveyard is a sorcery card there: no delirium.
    add(state, 0, "Shatterskull Smashing // Shatterskull, the Hammer Pass", Zone.GRAVEYARD)
    assert effective_power(state, drc) == 1
    # The opponent's graveyard doesn't count.
    add(state, 1, "Mox Pearl", Zone.GRAVEYARD)
    assert effective_power(state, drc) == 1
    mox = add(state, 0, "Mox Pearl", Zone.GRAVEYARD)
    assert (effective_power(state, drc), effective_toughness(state, drc)) == (3, 3)
    assert "flying" in effective_keywords(state, drc)
    assert forced_attackers(state, 0) == [drc.id]
    # Continuous: losing the fourth type turns it straight back off.
    state.players[0].graveyard.remove(mox)
    assert (effective_power(state, drc), effective_toughness(state, drc)) == (1, 1)
    assert "flying" not in effective_keywords(state, drc)


def test_dragons_rage_channeler_counts_a_kindred_card():
    state = make_state()
    drc = add(state, 0, "Dragon's Rage Channeler")
    for name in ("Island", "Lightning Bolt", "Ponder"):
        add(state, 0, name, Zone.GRAVEYARD)
    _with_types(state, 0, ("Kindred", "Instant"))
    assert effective_power(state, drc) == 3


def _heat(state, graveyard_types: int):
    add_lands(state, 0, "Mountain", 1)
    target = add(state, 1, "Atraxa, Grand Unifier")
    names = ("Island", "Lightning Bolt", "Ponder", "Mox Pearl")[:graveyard_types]
    for name in names:
        add(state, 0, name, Zone.GRAVEYARD)
    heat = add(state, 0, "Unholy Heat", Zone.HAND)
    state.players[0].agent.scripts["target"] = [("permanent", target.id)]
    return heat, target


@pytest.mark.parametrize("types, damage", [(3, 2), (4, 6)])
def test_unholy_heat_damage_by_delirium(types, damage):
    state = make_state()
    heat, target = _heat(state, types)
    cast(state, 0, heat)
    assert target.damage == damage


def test_unholy_heat_checks_delirium_on_resolution():
    state = make_state()
    heat, target = _heat(state, 3)
    cast(state, 0, heat, resolve=False)
    # The fourth type arrives while Unholy Heat is on the stack.
    add(state, 0, "Mox Pearl", Zone.GRAVEYARD)
    while state.stack:
        resolve_top_of_stack(state)
    assert target.damage == 6


def test_fear_of_missing_out_gate():
    state = make_state()
    fomo = add(state, 0, "Fear of Missing Out")
    state.step = Step.DECLARE_ATTACKERS
    apply_action(state, 0, DeclareAttackers(attacker_ids=frozenset({fomo.id})))
    assert state.stack == []

    state = make_state()
    _four_type_graveyard(state)
    fomo = add(state, 0, "Fear of Missing Out")
    state.step = Step.DECLARE_ATTACKERS
    apply_action(state, 0, DeclareAttackers(attacker_ids=frozenset({fomo.id})))
    assert len(state.stack) == 1


def test_shifting_woodland_activation_needs_delirium():
    state = make_state()
    wood = add(state, 0, "Shifting Woodland")
    add_lands(state, 0, "Forest", 4)
    add(state, 0, "Walking Ballista", Zone.GRAVEYARD)  # artifact + creature
    add(state, 0, "Lightning Bolt", Zone.GRAVEYARD)
    assert not can_activate(state, 0, wood)
    add(state, 0, "Island", Zone.GRAVEYARD)
    assert can_activate(state, 0, wood)


def test_lhurgoyfs_count_all_graveyards_by_card():
    from mtg_bot.game import effective_power as power

    state = make_state()
    goyf = add(state, 0, "Barrowgoyf")
    assert (power(state, goyf), effective_toughness(state, goyf)) == (0, 1)
    add(state, 0, "Shatterskull Smashing // Shatterskull, the Hammer Pass", Zone.GRAVEYARD)  # sorcery only
    add(state, 1, "Walking Ballista", Zone.GRAVEYARD)  # artifact + creature
    _with_types(state, 1, ("Kindred", "Instant"))
    assert (power(state, goyf), effective_toughness(state, goyf)) == (5, 6)


def test_ursine_monstrosity_pumps_by_graveyard_card_types():
    from mtg_bot.effects.generic.cube_creatures_wg import MillChooseOpponentAttackPump

    state = make_state()
    ursine = add(state, 0, "Ursine Monstrosity")
    _four_type_graveyard(state)
    add(state, 0, "Island", Zone.LIBRARY)  # the milled card adds nothing new
    state.resolving_source = ursine
    MillChooseOpponentAttackPump().resolve(state, 0)
    state.resolving_source = None
    base = ursine.printing.power
    assert effective_power(state, ursine) == base + 5


def test_keen_eyed_curator_counts_exiled_card_types():
    from mtg_bot.effects.generic.cube_creatures_wg import (
        CardTypesAmongExiledWithSourceAtLeast,
    )

    cond = CardTypesAmongExiledWithSourceAtLeast(n=2)
    state = make_state()
    curator = add(state, 0, "Keen-Eyed Curator")
    smashing = add(state, 1, "Shatterskull Smashing // Shatterskull, the Hammer Pass", Zone.EXILE)
    bolt = add(state, 1, "Lightning Bolt", Zone.EXILE)
    import mtg_bot.effects.generic.cube_creatures_wg as wg

    original = wg.cards_exiled_with
    try:
        wg.cards_exiled_with = lambda st, src: [smashing, bolt]
        assert cond.matches_for_source(state, curator)  # sorcery + instant
        wg.cards_exiled_with = lambda st, src: [smashing]
        assert not cond.matches_for_source(state, curator)
    finally:
        wg.cards_exiled_with = original


def test_occult_epiphany_tokens_per_discarded_card_type():
    state = make_state()
    add_lands(state, 0, "Island", 4)
    epiphany = add(state, 0, "Occult Epiphany", Zone.HAND)
    for name in ("Shatterskull Smashing // Shatterskull, the Hammer Pass", "Walking Ballista"):
        add(state, 0, name, Zone.LIBRARY)
    state.players[0].agent.scripts["x"] = [2]
    before = len(state.battlefield)
    cast(state, 0, epiphany)
    # sorcery (MDFC front) + artifact + creature = 3 Spirit tokens
    spirits = [
        o for o in state.battlefield[before:] if o.printing.name == "Spirit"
    ]
    assert len(spirits) == 3


def test_atraxa_walks_the_shared_type_list(monkeypatch):
    from mtg_bot.effects.generic.cube_creatures_rmc import (
        RevealTopNOnePerCardTypeToHand,
    )

    state = make_state()
    kindred = _with_types(state, 0, ("Kindred", "Instant"), zone=Zone.LIBRARY)
    add(state, 0, "Island", Zone.LIBRARY)
    RevealTopNOnePerCardTypeToHand(count=2).resolve(state, 0)
    hand = state.players[0].hand
    # Instant then Kindred are both offered the kindred instant; the
    # Island is taken for Land.
    assert kindred in hand
    assert any(c.printing.name == "Island" for c in hand)


def test_shifting_woodland_activates_with_delirium():
    state = make_state()
    wood = add(state, 0, "Shifting Woodland")
    add_lands(state, 0, "Forest", 4)
    _four_type_graveyard(state)
    target = add(state, 0, "Walking Ballista", Zone.GRAVEYARD)
    state.players[0].agent.scripts["target"] = [("graveyard_card", target.id)]
    assert can_activate(state, 0, wood)
    activate(state, 0, wood)
