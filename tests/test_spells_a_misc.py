"""Bounce removal, mass "each" removal with riders, X damage, the
"dies this turn -> exile" damage rider, and "This spell can't be
countered." for PowerLSV cube spells."""

from __future__ import annotations

from mtg_bot.cards.parser.removal_phrases import (
    parse_damage_to_target,
    parse_destroy_all,
    parse_targeted_removal,
)
from mtg_bot.cards.parser.spell_cost_lines import (
    detect_spell_line_fields,
    is_spell_cost_line,
)
from mtg_bot.effects.generic.counterspells import CounterSpell
from mtg_bot.effects.generic.spell_damage import (
    DealDamageExileIfDiesThisTurn,
    DealXDamage,
)
from mtg_bot.effects.generic.targeted_removal import (
    ControllerSearchesForBasicLand,
    IfYouControlledItDraw,
    RemoveAllMatching,
)
from mtg_bot.effects.object_predicates import ControlledByYou, IsCreature
from mtg_bot.turn import run_cleanup_step

from tests._spells_a_helpers import (
    ScriptedAgent,
    cast,
    cast_and_resolve,
    cube,
    lands,
    new_game,
    put,
    resolve,
    to_hand,
    to_library,
)


# ---------- bounce ----------


def test_boomerang_basics_draws_only_for_your_own_permanent():
    state = new_game()
    lands(state, 0, "Island", 2)
    mine = put(state, "Sol Ring", controller=0)
    theirs = put(state, "Mind Stone", controller=1)
    drawn = to_library(state, "Island", owner=0)
    state.players[0].agent.prefer = [theirs.id]
    cast_and_resolve(state, 0, to_hand(state, "Boomerang Basics"))
    assert theirs in state.players[1].hand
    assert drawn in state.players[0].library
    state.players[0].agent.prefer = [mine.id]
    for o in state.battlefield:
        o.tapped = False
    cast_and_resolve(state, 0, to_hand(state, "Boomerang Basics"))
    assert mine in state.players[0].hand
    assert drawn in state.players[0].hand


def test_bounce_grammar():
    eff = parse_targeted_removal(
        "return target nonland permanent to its owner's hand. If you "
        "controlled that permanent, draw a card",
    )
    assert eff.action == "bounce" and eff.rider == IfYouControlledItDraw(1)
    assert "if you controlled" in eff.describe()
    assert parse_targeted_removal(
        "return target creature to its owner's hand. If you controlled "
        "that permanent, draw two cards",
    ).rider == IfYouControlledItDraw(2)
    assert parse_targeted_removal("return target creature to your hand") is None


def test_aether_spellbomb_bounces_a_creature():
    state = new_game()
    lands(state, 0, "Island", 1)
    bomb = put(state, "Aether Spellbomb", controller=0)
    elf = put(state, "Llanowar Elves", controller=1)
    ability = bomb.printing.activated_abilities[0]
    ability.effect.resolve(state, 0, (("creature", elf.id),))
    assert elf in state.players[1].hand


# ---------- mass removal with "each" / riders ----------


def test_each_grammar_and_rider():
    eff = parse_destroy_all(
        "exile each creature you don't control. For each creature exiled "
        "this way, its controller searches their library for a basic land "
        "card. Those players put those cards onto the battlefield tapped, "
        "then shuffle",
    )
    assert eff == RemoveAllMatching(
        permanent_filter=IsCreature() & ~ControlledByYou(),
        action="exile",
        rider=ControllerSearchesForBasicLand(optional=False),
        label="each creature you don't control",
    )
    assert "for each" in eff.describe()
    eff = parse_destroy_all(
        "destroy each creature. A creature destroyed this way can't be "
        "regenerated",
    )
    assert eff.can_be_regenerated is False
    assert parse_destroy_all(
        "exile each creature. A creature destroyed this way can't be "
        "regenerated",
    ) is None
    assert parse_destroy_all("destroy each creatures") is None


def test_mass_exile_rider_runs_for_each_removed_permanent():
    state = new_game()
    mine = put(state, "Birds of Paradise", controller=0)
    a = put(state, "Llanowar Elves", controller=1)
    b = put(state, "Elvish Mystic", controller=1)
    lands_in_library = [to_library(state, "Forest", owner=1) for _ in range(3)]
    eff = RemoveAllMatching(
        permanent_filter=IsCreature() & ~ControlledByYou(),
        action="exile",
        rider=ControllerSearchesForBasicLand(optional=False),
    )
    eff.resolve(state, 0)
    assert mine in state.battlefield
    assert a in state.players[1].exile and b in state.players[1].exile
    assert sum(1 for c in lands_in_library if c in state.battlefield) == 2


def test_remove_all_matching_rejects_unknown_action():
    import pytest

    with pytest.raises(ValueError):
        RemoveAllMatching(permanent_filter=IsCreature(), action="mill")


# ---------- X damage / dies-exile ----------


def test_traumatic_critique_deals_x_then_loots():
    state = new_game(ScriptedAgent(prefer=[("player", 1)], x=3))
    lands(state, 0, "Island", 3)
    lands(state, 0, "Mountain", 2)
    for _ in range(2):
        to_library(state, "Island", owner=0)
    cast_and_resolve(state, 0, to_hand(state, "Traumatic Critique"))
    assert state.players[1].life == 17
    assert len(state.players[0].hand) == 1
    assert len(state.players[0].graveyard) == 2  # discarded card + spell


def test_deal_x_damage_grammar_and_fizzle():
    eff = parse_damage_to_target("deals X damage to any target")
    assert isinstance(eff, DealXDamage)
    assert eff.describe() == "deals X damage to any target"
    assert parse_damage_to_target(
        "deals X damage to target creature. If that creature would die "
        "this turn, exile it instead",
    ) is None
    state = new_game()
    eff.resolve(state, 0, (("creature", 99),))
    assert any("fizzles" in line for line in state.log)


def test_suplex_damage_mode_exiles_a_dying_creature():
    state = new_game(ScriptedAgent(mode=0))
    lands(state, 0, "Mountain", 2)
    kavu = put(state, "Flametongue Kavu", controller=1)
    cast_and_resolve(state, 0, to_hand(state, "Suplex"))
    assert kavu in state.players[1].exile
    assert kavu not in state.players[1].graveyard


def test_dies_exile_rider_wears_off_at_cleanup():
    state = new_game()
    gris = put(state, "Griselbrand", controller=1)
    eff = DealDamageExileIfDiesThisTurn(
        amount=1, targets=cube("Suplex").spell_effect.modes[0].targets,
    )
    eff.resolve(state, 0, (("creature", gris.id),))
    assert gris.exile_if_dies_this_turn
    assert "exile it instead" in eff.describe()
    run_cleanup_step(state)
    assert not gris.exile_if_dies_this_turn
    from mtg_bot.effects.targets import TargetSpec, any_target_filter

    burn = DealDamageExileIfDiesThisTurn(
        amount=1, targets=(TargetSpec(any_target_filter()),),
    )
    burn.resolve(state, 0, (("player", 1),))  # players ignore the rider
    assert state.players[1].life == 19


def test_suplex_artifact_mode():
    state = new_game(ScriptedAgent(mode=1))
    lands(state, 0, "Mountain", 2)
    ring = put(state, "Sol Ring", controller=1)
    cast_and_resolve(state, 0, to_hand(state, "Suplex"))
    assert ring in state.players[1].exile


# ---------- This spell can't be countered ----------


def test_abrupt_decay_cannot_be_countered_and_hits_small_permanents():
    state = new_game(agent1=ScriptedAgent())
    lands(state, 0, "Swamp", 1)
    lands(state, 0, "Forest", 1)
    ring = put(state, "Sol Ring", controller=1)
    put(state, "Griselbrand", controller=1)
    decay = to_hand(state, "Abrupt Decay")
    assert cube("Abrupt Decay").spell_is_uncounterable
    legal = cube("Abrupt Decay").spell_effect.legal_targets(state, 0)
    assert legal == [("permanent", ring.id)]
    cast(state, 0, decay)
    assert CounterSpell().legal_targets(state, 1) == []
    resolve(state)
    assert ring in state.players[1].graveyard


def test_uncounterable_line_detection():
    assert is_spell_cost_line("This spell can't be countered.")
    assert detect_spell_line_fields(
        "This spell can't be countered.\nDraw a card.",
    ) == {"spell_is_uncounterable": True}
    assert detect_spell_line_fields("Draw a card.") == {}


# ---------- Converge (Prismatic Ending) ----------


def test_prismatic_ending_counts_colors_spent():
    state = new_game(ScriptedAgent(x=1))
    put(state, "Plains", controller=0)
    put(state, "Island", controller=0)
    ring = put(state, "Mind Stone", controller=1)  # MV 2
    cast_and_resolve(state, 0, to_hand(state, "Prismatic Ending"))
    assert ring in state.players[1].exile


def test_prismatic_ending_one_color_is_not_enough_for_mv_two():
    state = new_game(ScriptedAgent(x=1))
    lands(state, 0, "Plains", 2)
    stone = put(state, "Mind Stone", controller=1)
    cast_and_resolve(state, 0, to_hand(state, "Prismatic Ending"))
    assert stone in state.battlefield


def test_colors_spent_counts_pool_mana():
    from mtg_bot.game import ManaCoin

    state = new_game(ScriptedAgent(x=1))
    put(state, "Plains", controller=0)
    state.players[0].mana_pool.append(ManaCoin(color="B"))
    stone = put(state, "Mind Stone", controller=1)
    cast_and_resolve(state, 0, to_hand(state, "Prismatic Ending"))
    assert stone in state.players[1].exile


def test_colors_spent_recorded_for_every_cast():
    from mtg_bot.game import ManaCoin

    state = new_game()
    state.players[0].mana_pool.extend([ManaCoin(color="any"), ManaCoin(color="R")])
    bolt = to_hand(state, "Lightning Bolt")
    state.players[1].agent = ScriptedAgent()
    from tests._spells_a_helpers import cast

    cast(state, 0, bolt)
    assert bolt.sunburst_colors_spent == 1


# ---------- Pest Infestation: "up to X target", twice X Pest tokens ----------


def test_pest_infestation_destroys_up_to_x_and_makes_pests():
    agent = ScriptedAgent(x=2)
    state = new_game(agent)
    lands(state, 0, "Forest", 5)
    a = put(state, "Sol Ring", controller=1)
    b = put(state, "Mind Stone", controller=1)
    c = put(state, "Lotus Petal", controller=1)
    agent.prefer = [a.id, b.id]
    cast(state, 0, to_hand(state, "Pest Infestation"))
    assert state.stack[-1].x_value == 2
    assert len(state.stack[-1].targets) == 2
    resolve(state)
    assert a not in state.battlefield and b not in state.battlefield
    assert c in state.battlefield
    pests = [o for o in state.battlefield if o.printing.name == "Pest"]
    assert len(pests) == 4 and all(p.controller_id == 0 for p in pests)


def test_pest_token_gains_life_when_it_dies():
    from mtg_bot.actions import drain_stack
    from mtg_bot.cards.parser.keyword_actions import (
        _synthesize_creature_token_effect as parse_scaled_token_creation,
    )
    from mtg_bot.turn import move_off_battlefield

    token = parse_scaled_token_creation(
        'create X 1/1 black and green Pest creature tokens with "When this '
        'token dies, you gain 1 life."',
    ).token_printing
    state = new_game()
    pest = put(state, token, controller=0)
    move_off_battlefield(state, pest, destination="graveyard")
    drain_stack(state)
    assert state.players[0].life == 21


def test_pest_infestation_x_zero_targets_nothing():
    state = new_game(ScriptedAgent(x=0))
    lands(state, 0, "Forest", 1)
    ring = put(state, "Sol Ring", controller=1)
    cast(state, 0, to_hand(state, "Pest Infestation"))
    assert state.stack[-1].targets == ()
    resolve(state)
    assert ring in state.battlefield
    assert not [o for o in state.battlefield if o.printing.name == "Pest"]


def test_x_scaled_token_synthesis_on_the_base_token_grammar():
    from mtg_bot.cards.parser.keyword_actions import (
        _synthesize_creature_token_effect as parse_scaled_token_creation,
    )

    ok = parse_scaled_token_creation(
        'create X 1/1 black and green Pest creature tokens with "When this '
        'token dies, you gain 1 life."',
    )
    tok = ok.token_printing
    assert ok.multiplier == 1
    assert (tok.name, tok.power, tok.toughness) == ("Pest", 1, 1)
    assert tok.color_indicator == frozenset({"B", "G"})
    assert "Pest" in tok.subtypes and len(tok.triggered_abilities) == 1
    assert "X" in ok.describe()
    kw = parse_scaled_token_creation(
        "create twice X 1/1 white Soldier creature tokens with lifelink",
    )
    assert kw.multiplier == 2 and "lifelink" in kw.token_printing.keywords
    assert not kw.token_printing.triggered_abilities
    assert parse_scaled_token_creation(
        "create X 1/1 plaid Pest creature tokens",
    ) is None  # unknown color word
    assert parse_scaled_token_creation(
        'create X 1/1 black Pest creature tokens with "Gibberish here."',
    ) is None  # unparseable quoted ability
    assert parse_scaled_token_creation(
        "create X 1/1 black Pest creature tokens with frobnicate",
    ) is None  # unknown keyword
    assert parse_scaled_token_creation("create a Treasure token") is None


def test_scaled_token_grammar_plain_token():
    from mtg_bot.cards.parser.keyword_actions import (
        _synthesize_creature_token_effect as parse_scaled_token_creation,
    )

    eff = parse_scaled_token_creation("create X 1/1 red Gremlin creature tokens")
    assert eff.token_printing.name == "Gremlin" and eff.multiplier == 1


# ---------- substrate glue: energy, Map tokens, monarch ----------


def test_galvanic_discharge_pays_energy_for_damage():
    state = new_game(ScriptedAgent(x=2))
    lands(state, 0, "Mountain", 1)
    kavu = put(state, "Flametongue Kavu", controller=1)  # 4/2
    cast_and_resolve(state, 0, to_hand(state, "Galvanic Discharge"))
    assert kavu in state.players[1].graveyard
    assert state.players[0].energy == 1  # got 3, paid 2


def test_galvanic_discharge_default_pays_everything_and_fizzles_cleanly():
    from mtg_bot.effects.generic.spell_damage import DealDamagePaidInEnergy

    state = new_game()
    state.players[0].energy = 2
    lands(state, 0, "Mountain", 1)
    gris = put(state, "Griselbrand", controller=1)  # 7/7
    cast_and_resolve(state, 0, to_hand(state, "Galvanic Discharge"))
    assert gris.damage == 5 and state.players[0].energy == 0
    eff = cube("Galvanic Discharge").spell_effect
    assert isinstance(eff, DealDamagePaidInEnergy) and eff.energy == 3
    eff.resolve(state, 0, (("permanent", 999),))  # illegal target
    assert state.players[0].energy == 0  # didn't resolve: no energy
    assert "{E}{E}{E}" in eff.describe()
    state.players[0].agent = None
    eff.resolve(state, 0, (eff.legal_targets(state, 0)[0],))
    assert gris.damage == 8


def test_forth_eorlingas_tokens_and_this_turn_monarch_trigger():
    from mtg_bot.actions import drain_stack
    from mtg_bot.combat import resolve_combat_damage

    state = new_game(ScriptedAgent(x=2))
    lands(state, 0, "Mountain", 2)
    lands(state, 0, "Plains", 2)
    cast_and_resolve(state, 0, to_hand(state, "Forth Eorlingas!"))
    knights = [o for o in state.battlefield if o.printing.name == "Human Knight"]
    assert len(knights) == 2
    assert {"trample", "haste"} <= set(knights[0].printing.keywords)
    assert knights[0].printing.color_indicator == frozenset({"R"})
    assert len(state.emblems) == 1 and state.emblems[0].expires_at_cleanup
    knights[0].attacking = True
    resolve_combat_damage(state, 1)
    drain_stack(state)
    assert state.players[0].is_monarch
    assert state.players[1].life == 18
    run_cleanup_step(state)
    assert state.emblems == []


def test_this_turn_trigger_grammar():
    from mtg_bot.cards.parser.spell_misc_phrases import (
        parse_energy_paid_damage,
        parse_this_turn_trigger,
    )
    from mtg_bot.effects.generic.spell_misc import (
        CreateThisTurnTriggeredAbility,
    )

    eff = parse_this_turn_trigger(
        "whenever one or more creatures you control deal combat damage to "
        "one or more players this turn, you become the monarch",
    )
    assert isinstance(eff, CreateThisTurnTriggeredAbility)
    assert "this turn" in eff.describe()
    assert parse_this_turn_trigger("whenever frobnicate this turn, draw a card") is None
    assert parse_this_turn_trigger("draw a card") is None
    assert parse_energy_paid_damage(
        "choose target wizard. You get {E}, then you may pay any amount of "
        "{E}. X deals that much damage to that permanent",
    ) is None
    assert parse_energy_paid_damage("draw a card") is None
    # Outside a resolving spell the holder is labeled generically.
    state = new_game()
    eff.resolve(state, 0)
    assert "(effect)" in state.log[-1]


def test_get_lost_destroys_and_gives_its_controller_two_maps():
    state = new_game()
    lands(state, 0, "Plains", 2)
    kavu = put(state, "Flametongue Kavu", controller=1)
    cast_and_resolve(state, 0, to_hand(state, "Get Lost"))
    assert kavu in state.players[1].graveyard
    maps = [o for o in state.battlefield if o.printing.name == "Map"]
    assert len(maps) == 2 and all(m.controller_id == 1 for m in maps)
