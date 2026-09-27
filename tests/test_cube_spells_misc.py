"""Cube spells-B: Lingering Souls / Malevolent Rumble tokens, Expressive
Iteration, Once Upon a Time's conditional free cast, Balance, Council's
Judgment, Flash, Transmute Artifact, Rain of Filth, Demonic
Consultation, Lim-Dul's Vault, Occult Epiphany."""

from __future__ import annotations

import pytest

from mtg_bot.actions import CastSpell, apply_action, resolve_top_of_stack
from mtg_bot.cards import SYNTHETIC_CREATURES
from mtg_bot.cards.parser.card_flow_grammar import parse_card_flow_effect
from mtg_bot.cards.parser.effects import _parse_create_token_effect
from mtg_bot.cards.parser.source import OracleParserCardSource
from mtg_bot.cards.parser.spell_builder import _casting_keyword_fields
from mtg_bot.effects.conditions import FirstSpellYouCastThisGame
from mtg_bot.effects.generic.card_flow import (
    NAME_NOT_IN_LIBRARY,
    ChooseNameExileThenRevealUntilNamed,
    DrawDiscardThenTokensPerDiscardedType,
    LookAtTopCardsDistribute,
    LookAtTopRepeatPayLifeThenStackTop,
)
from mtg_bot.effects.generic.cheat_into_play import (
    PutCreatureFromHandSacrificeUnlessPay,
    SacrificeArtifactTutorArtifactPayDifference,
)
from mtg_bot.effects.generic.mass_effects import (
    BalanceEffect,
    GrantAbilityToPermanentsYouControlUEOT,
    VoteExileNonlandPermanent,
)
from mtg_bot.game import Zone, effective_activated_abilities
from mtg_bot.legal import legal_actions
from mtg_bot.turn import run_cleanup_step
from tests._spells_b_helpers import (
    ScriptedAgent,
    add,
    add_lands,
    cast_and_resolve,
    make_state,
)


@pytest.fixture(scope="module")
def cube():
    return OracleParserCardSource(pool="cube").get_printings()


def _creature(state, pid, name, zone=Zone.BATTLEFIELD):
    obj = state.new_object(SYNTHETIC_CREATURES[name], pid, zone)
    p = state.player_by_id(pid)
    if zone == Zone.BATTLEFIELD:
        obj.summoning_sick = False
        state.battlefield.append(obj)
    elif zone == Zone.HAND:
        p.hand.append(obj)
    elif zone == Zone.LIBRARY:
        p.library.append(obj)
    elif zone == Zone.GRAVEYARD:
        p.graveyard.append(obj)
    return obj


# ---------------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------------


def test_lingering_souls_creates_spirits_and_flashes_back():
    state = make_state()
    souls = add(state, 0, "Lingering Souls", Zone.HAND)
    add_lands(state, 0, "Plains", 3)
    add_lands(state, 0, "Swamp", 2)
    cast_and_resolve(state, 0, souls)
    spirits = [o for o in state.battlefield if o.printing.name == "Spirit"]
    assert len(spirits) == 2
    assert all("flying" in o.printing.keywords for o in spirits)
    assert souls in state.players[0].graveyard
    cast_and_resolve(state, 0, souls, use_flashback=True)
    assert sum(1 for o in state.battlefield if o.printing.name == "Spirit") == 4
    assert souls in state.players[0].exile


def test_token_stats_mismatching_registry_are_synthesized():
    # A registry token keyed by the same subtype but with other stats
    # is a different token: it's built from its printed characteristics
    # (keyword substrate's token synthesis), not the registered one.
    eff = _parse_create_token_effect(
        "create a 2/2 colorless Eldrazi Spawn creature token"
    )
    assert eff.token_printing.power == 2 and eff.token_printing.toughness == 2
    spirit = _parse_create_token_effect(
        "create a 1/1 white Spirit creature token with flying"
    )
    assert spirit.token_printing.name == "Spirit"
    assert "flying" in spirit.token_printing.keywords


def test_malevolent_rumble_takes_permanent_rest_to_graveyard_and_spawn():
    state = make_state()
    lib = [add(state, 0, n, Zone.LIBRARY)
           for n in ("Dark Ritual", "Island", "Brainstorm", "Swamp", "Forest")]
    state.players[0].agent.scripts["library"] = [lib[3].id]
    card = add(state, 0, "Malevolent Rumble", Zone.HAND)
    add_lands(state, 0, "Forest", 2)
    cast_and_resolve(state, 0, card)
    p = state.players[0]
    assert p.hand == [lib[3]]
    assert {c.id for c in lib[:3]} <= {c.id for c in p.graveyard}
    assert p.library == [lib[4]]
    spawn = [o for o in state.battlefield if o.printing.name == "Eldrazi Spawn"]
    assert len(spawn) == 1 and spawn[0].printing.toughness == 1


# ---------------------------------------------------------------------
# Expressive Iteration
# ---------------------------------------------------------------------


def test_expressive_iteration_distributes_three(cube):
    assert cube["Expressive Iteration"].spell_effect == LookAtTopCardsDistribute(
        count=3, piles=("hand", "bottom", "exile_playable"),
    )
    state = make_state()
    lib = [add(state, 0, n, Zone.LIBRARY)
           for n in ("Island", "Mountain", "Dark Ritual", "Swamp")]
    state.players[0].agent.scripts["library"] = [lib[2].id, lib[0].id]
    card = add(state, 0, "Expressive Iteration", Zone.HAND)
    add_lands(state, 0, "Island", 1)
    add_lands(state, 0, "Mountain", 1)
    cast_and_resolve(state, 0, card)
    p = state.players[0]
    assert p.hand == [lib[2]]
    assert p.library == [lib[3], lib[0]]
    assert lib[1] in p.exile and lib[1].playable_from_exile_this_turn
    # The exiled land is playable this turn.
    from mtg_bot.actions import PlayLand

    assert PlayLand(lib[1].id) in legal_actions(state, 0)


def test_distribute_leftovers_and_bad_pile():
    state = make_state()
    lib = [add(state, 0, n, Zone.LIBRARY) for n in ("Island", "Swamp", "Forest")]
    LookAtTopCardsDistribute(count=3, piles=("hand",)).resolve(state, 0)
    p = state.players[0]
    assert p.hand == [lib[0]] and p.library == [lib[1], lib[2]]
    with pytest.raises(ValueError):
        LookAtTopCardsDistribute(piles=("graveyard",))
    assert "distribute" in LookAtTopCardsDistribute().describe()


@pytest.mark.parametrize("phrase", [
    "look at the top three cards of your library. Put one of them into your "
    "hand, put one of them into your hand, and exile one of them. You may "
    "play the exiled card this turn",
    "look at the top three cards of your library. Put one of them into your "
    "hand, sacrifice one of them, and exile one of them. You may play the "
    "exiled card this turn",
    "look at the top X cards of your library. Put one of them into your "
    "hand, put one of them on the bottom of your library, and exile one of "
    "them. You may play the exiled card this turn",
])
def test_distribute_grammar_rejects(phrase):
    assert parse_card_flow_effect(phrase) is None


# ---------------------------------------------------------------------
# Once Upon a Time
# ---------------------------------------------------------------------


def test_once_upon_a_time_free_only_as_first_spell(cube):
    assert cube["Once Upon a Time"].free_cast_condition == FirstSpellYouCastThisGame()
    assert _casting_keyword_fields(
        "If you control a Wizard, you may cast it without paying its mana cost."
    ) is None
    state = make_state()
    for n in ("Island", "Swamp", "Forest", "Mountain", "Plains"):
        add(state, 0, n, Zone.LIBRARY)
    card = add(state, 0, "Once Upon a Time", Zone.HAND)
    free = CastSpell(card.id, cast_for_free=True)
    assert free in legal_actions(state, 0)  # no lands needed
    state.players[0].spells_cast_this_game = 1
    assert free not in legal_actions(state, 0)
    state.players[0].spells_cast_this_game = 0
    cast_and_resolve(state, 0, card, cast_for_free=True)
    p = state.players[0]
    assert len(p.hand) == 1 and p.hand[0].printing.is_land
    assert p.spells_cast_this_game == 1
    assert len(p.library) == 4
    assert FirstSpellYouCastThisGame().matches(state, 42) is False


# ---------------------------------------------------------------------
# Balance
# ---------------------------------------------------------------------


def test_balance_levels_lands_hands_and_creatures(cube):
    assert cube["Balance"].spell_effect == BalanceEffect()
    state = make_state()
    my_lands = add_lands(state, 0, "Plains", 4)
    opp_lands = add_lands(state, 1, "Swamp", 2)
    for _ in range(3):
        add(state, 0, "Island", Zone.HAND)
    add(state, 1, "Island", Zone.HAND)
    my_bear = _creature(state, 0, "Wild Bear")
    opp_c = [_creature(state, 1, "Stone Ogre"), _creature(state, 1, "Raging Goblin")]
    card = add(state, 0, "Balance", Zone.HAND)
    state.players[0].hand.remove(card)
    state.players[0].hand.append(card)
    apply_action(state, 0, CastSpell(card.id))
    # Balance cost {1}{W} tapped two of P0's Plains.
    state.players[1].agent.scripts["sacrifice"] = [opp_c[1].id]
    resolve_top_of_stack(state)
    lands0 = [o for o in state.battlefield if o.controller_id == 0 and o.printing.is_land]
    lands1 = [o for o in state.battlefield if o.controller_id == 1 and o.printing.is_land]
    assert len(lands0) == 2 and len(lands1) == 2
    assert len(state.players[0].hand) == 1 and len(state.players[1].hand) == 1
    assert my_bear in state.battlefield
    assert opp_c[0] in state.battlefield and opp_c[1] not in state.battlefield
    assert "fewest" in BalanceEffect().describe()


def test_balance_with_lost_player_and_no_agent():
    state = make_state()
    state.players[0].agent = None
    add_lands(state, 0, "Plains", 2)
    add(state, 0, "Island", Zone.HAND)
    state.players[1].has_lost = True
    BalanceEffect().resolve(state, 0)
    assert len(state.players[0].hand) == 1


# ---------------------------------------------------------------------
# Council's Judgment
# ---------------------------------------------------------------------


def test_councils_judgment_exiles_most_voted(cube):
    assert cube["Council's Judgment"].spell_effect == VoteExileNonlandPermanent()
    state = make_state()
    ogre = _creature(state, 1, "Stone Ogre")
    gob = _creature(state, 1, "Raging Goblin")
    mine = _creature(state, 0, "Wild Bear")
    state.players[0].agent.scripts["target"] = [("creature", ogre.id)]
    state.players[1].agent.scripts["sacrifice"] = [gob.id]
    VoteExileNonlandPermanent().resolve(state, 0)
    # 1-1 tie: both exiled; the caster's own creature was never eligible.
    assert ogre in state.players[1].exile and gob in state.players[1].exile
    assert mine in state.battlefield


def test_councils_judgment_same_vote_and_no_options():
    state = make_state()
    ogre = _creature(state, 1, "Stone Ogre")
    gob = _creature(state, 1, "Raging Goblin")
    state.players[0].agent.scripts["target"] = [("creature", gob.id)]
    state.players[1].agent.scripts["sacrifice"] = [gob.id]
    VoteExileNonlandPermanent().resolve(state, 0)
    assert gob in state.players[1].exile and ogre in state.battlefield
    empty = make_state()
    VoteExileNonlandPermanent().resolve(empty, 0)
    state.players[0].agent = None
    VoteExileNonlandPermanent().resolve(state, 0)
    assert ogre in state.players[1].exile
    assert "votes" in VoteExileNonlandPermanent().describe()


# ---------------------------------------------------------------------
# Flash
# ---------------------------------------------------------------------


def test_flash_pays_reduced_cost_to_keep():
    state = make_state()
    wurm = _creature(state, 0, "Great Wurm", Zone.HAND)  # {3}{G}{G}
    card = add(state, 0, "Flash", Zone.HAND)
    add_lands(state, 0, "Island", 2)
    add_lands(state, 0, "Forest", 3)
    cast_and_resolve(state, 0, card)
    assert wurm in state.battlefield
    assert all(o.tapped for o in state.battlefield if o.printing.is_land)


def test_flash_sacrifices_when_unpaid_or_declined():
    state = make_state(agent0=ScriptedAgent(yes_no=[False]))
    bear = _creature(state, 0, "Wild Bear", Zone.HAND)
    add_lands(state, 0, "Forest", 4)
    PutCreatureFromHandSacrificeUnlessPay(reduction=2).resolve(state, 0)
    assert bear in state.players[0].graveyard
    state = make_state()
    wurm = _creature(state, 0, "Great Wurm", Zone.HAND)
    PutCreatureFromHandSacrificeUnlessPay(reduction=2).resolve(state, 0)
    assert wurm in state.players[0].graveyard  # can't pay {1}{G}{G}


def test_flash_decline_and_no_creature():
    state = make_state(agent0=ScriptedAgent(library=[None]))
    bear = _creature(state, 0, "Wild Bear", Zone.HAND)
    eff = PutCreatureFromHandSacrificeUnlessPay(reduction=2)
    eff.resolve(state, 0)
    assert bear in state.players[0].hand
    PutCreatureFromHandSacrificeUnlessPay().resolve(make_state(), 0)
    assert "reduced by {2}" in eff.describe()


# ---------------------------------------------------------------------
# Transmute Artifact
# ---------------------------------------------------------------------


def _artifact(state, pid, zone):
    return add(state, pid, "Expedition Map", zone)


def test_transmute_artifact_equal_mv_enters(cube):
    assert cube["Transmute Artifact"].spell_effect == (
        SacrificeArtifactTutorArtifactPayDifference()
    )
    state = make_state()
    old = _artifact(state, 0, Zone.BATTLEFIELD)
    new = _artifact(state, 0, Zone.LIBRARY)
    SacrificeArtifactTutorArtifactPayDifference().resolve(state, 0)
    assert old in state.players[0].graveyard and new in state.battlefield


def test_transmute_artifact_pays_difference_or_bins():
    import dataclasses

    from mtg_bot.cards import parse_mana_cost

    state = make_state()
    old = _artifact(state, 0, Zone.BATTLEFIELD)
    big = _artifact(state, 0, Zone.LIBRARY)
    big.printing = dataclasses.replace(
        big.printing, mana_cost=parse_mana_cost("{3}"), mana_cost_str="{3}",
    )
    add_lands(state, 0, "Island", 2)
    SacrificeArtifactTutorArtifactPayDifference().resolve(state, 0)
    assert big in state.battlefield
    assert all(o.tapped for o in state.battlefield if o.printing.is_land)
    # Can't pay: the card goes to the graveyard.
    state = make_state()
    _artifact(state, 0, Zone.BATTLEFIELD)
    big = _artifact(state, 0, Zone.LIBRARY)
    big.printing = dataclasses.replace(
        big.printing, mana_cost=parse_mana_cost("{3}"), mana_cost_str="{3}",
    )
    SacrificeArtifactTutorArtifactPayDifference().resolve(state, 0)
    assert big in state.players[0].graveyard


def test_transmute_artifact_no_artifact_or_decline():
    state = make_state()
    SacrificeArtifactTutorArtifactPayDifference().resolve(state, 0)
    state = make_state(agent0=ScriptedAgent(library=[None]))
    old = _artifact(state, 0, Zone.BATTLEFIELD)
    lib = _artifact(state, 0, Zone.LIBRARY)
    SacrificeArtifactTutorArtifactPayDifference().resolve(state, 0)
    assert old in state.players[0].graveyard and lib in state.players[0].library
    assert "sacrifice an artifact" in SacrificeArtifactTutorArtifactPayDifference().describe()


# ---------------------------------------------------------------------
# Rain of Filth
# ---------------------------------------------------------------------


def test_rain_of_filth_lands_gain_sac_for_black_until_eot(cube):
    eff = cube["Rain of Filth"].spell_effect
    assert isinstance(eff, GrantAbilityToPermanentsYouControlUEOT)
    assert eff.ability.is_mana_ability and eff.ability.cost.sacrifice_self
    state = make_state()
    swamp = add(state, 0, "Swamp", Zone.BATTLEFIELD)
    island = add(state, 0, "Island", Zone.BATTLEFIELD)
    opp = add(state, 1, "Swamp", Zone.BATTLEFIELD)
    card = add(state, 0, "Rain of Filth", Zone.HAND)
    cast_and_resolve(state, 0, card)
    assert swamp.tapped
    # Basic lands' own mana ability lives on ``produces``; the granted
    # sac-for-{B} is the only activated ability.
    assert len(effective_activated_abilities(state, island)) == 1
    assert len(effective_activated_abilities(state, opp)) == 0
    # Island + a sacrificed land pay for a {1}{B} spell.
    tutor = add(state, 0, "Demonic Tutor", Zone.HAND)
    assert CastSpell(tutor.id) in legal_actions(state, 0)
    state.step = None
    run_cleanup_step(state)
    assert len(effective_activated_abilities(state, island)) == 0


def test_grant_ability_edge_cases():
    state = make_state()
    GrantAbilityToPermanentsYouControlUEOT().resolve(state, 0)
    assert "you control gains" in GrantAbilityToPermanentsYouControlUEOT().describe()


# ---------------------------------------------------------------------
# Demonic Consultation
# ---------------------------------------------------------------------


def test_demonic_consultation_finds_named_card(cube):
    assert cube["Demonic Consultation"].spell_effect == (
        ChooseNameExileThenRevealUntilNamed(exile_first=6)
    )
    state = make_state()
    names = ["Island"] * 7 + ["Brainstorm", "Swamp", "Forest"]
    lib = [add(state, 0, n, Zone.LIBRARY) for n in names]
    options = sorted(set(names)) + [NAME_NOT_IN_LIBRARY]
    state.players[0].agent.scripts["mode"] = [options.index("Brainstorm")]
    ChooseNameExileThenRevealUntilNamed(exile_first=6).resolve(state, 0)
    p = state.players[0]
    assert p.hand == [lib[7]]
    assert len(p.exile) == 7 and p.library == lib[8:]


def test_demonic_consultation_unfound_name_exiles_library():
    state = make_state(agent0=None)
    state.players[0].agent = None  # defaults to the not-in-library name
    lib = [add(state, 0, "Island", Zone.LIBRARY) for _ in range(8)]
    eff = ChooseNameExileThenRevealUntilNamed(exile_first=6)
    eff.resolve(state, 0)
    assert state.players[0].library == [] and len(state.players[0].exile) == 8
    assert state.players[0].hand == []
    assert "choose a card name" in eff.describe()
    # A named card inside the first six is exiled with them.
    state = make_state()
    lib = [add(state, 0, n, Zone.LIBRARY) for n in ("Swamp", "Island", "Island")]
    state.players[0].agent.scripts["mode"] = [1]  # "Swamp"
    ChooseNameExileThenRevealUntilNamed(exile_first=6).resolve(state, 0)
    assert lib[0] in state.players[0].exile


# ---------------------------------------------------------------------
# Lim-Dul's Vault
# ---------------------------------------------------------------------


def test_lim_duls_vault_repeat_then_stack_top(cube):
    vault = next(p for n, p in cube.items() if n.startswith("Lim-D"))
    assert vault.spell_effect == LookAtTopRepeatPayLifeThenStackTop(
        count=5, life_per_repeat=1,
    )
    state = make_state(agent0=ScriptedAgent(yes_no=[True, False]))
    lib = [add(state, 0, "Island", Zone.LIBRARY) for _ in range(12)]
    state.players[0].agent.scripts["library"] = [lib[9].id]
    LookAtTopRepeatPayLifeThenStackTop(count=5).resolve(state, 0)
    p = state.players[0]
    assert p.life == 19
    top5 = {c.id for c in p.library[:5]}
    assert top5 == {c.id for c in lib[5:10]}
    assert p.library[0] is lib[9]


def test_lim_duls_vault_stops_at_low_life_and_small_library():
    state = make_state()  # default yes
    state.players[0].life = 2
    for _ in range(20):
        add(state, 0, "Island", Zone.LIBRARY)
    LookAtTopRepeatPayLifeThenStackTop(count=5).resolve(state, 0)
    assert state.players[0].life == 1
    state = make_state()
    for _ in range(3):
        add(state, 0, "Island", Zone.LIBRARY)
    LookAtTopRepeatPayLifeThenStackTop(count=5).resolve(state, 0)
    assert state.players[0].life == 20
    assert "pay 1 life" in LookAtTopRepeatPayLifeThenStackTop().describe()


# ---------------------------------------------------------------------
# Occult Epiphany
# ---------------------------------------------------------------------


def test_occult_epiphany_tokens_per_discarded_type(cube):
    eff = cube["Occult Epiphany"].spell_effect
    assert isinstance(eff, DrawDiscardThenTokensPerDiscardedType)
    state = make_state(agent0=ScriptedAgent(x=[3]))
    for n in ("Island", "Dark Ritual", "Brainstorm"):
        add(state, 0, n, Zone.LIBRARY)
    keep = add(state, 0, "Swamp", Zone.HAND)
    card = add(state, 0, "Occult Epiphany", Zone.HAND)
    add_lands(state, 0, "Island", 4)
    lib = list(state.players[0].library)
    state.players[0].agent.scripts["discard"] = [lib[0].id, lib[1].id, lib[2].id]
    cast_and_resolve(state, 0, card)
    spirits = [o for o in state.battlefield if o.printing.name == "Spirit"]
    # Land + Instant (both rituals/brainstorm are instants) = 2 types.
    assert len(spirits) == 2
    assert state.players[0].hand == [keep]


def test_occult_epiphany_zero_and_no_agent():
    state = make_state()
    state.players[0].agent = None
    add(state, 0, "Island", Zone.LIBRARY)
    DrawDiscardThenTokensPerDiscardedType(amount=1, token_printing=None).resolve(state, 0)
    assert len(state.players[0].graveyard) == 1
    assert state.battlefield == []
    assert "discard" in DrawDiscardThenTokensPerDiscardedType().describe()
