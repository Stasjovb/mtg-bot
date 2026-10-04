"""Cube layouts bucket: creatures that exile and return transformed into
planeswalkers (Jace, Vryn's Prodigy; Tamiyo, Inquisitive Student;
Ajani, Nacatl Pariah) and Cecil, Dark Knight's damage-driven transform.

Covers the back faces' loyalty abilities through the planeswalker
grammar and the effect / trigger / condition shapes the faces print
(``layout_face_grammar`` / ``layout_face_effects``).
"""

from __future__ import annotations

from mtg_bot.actions import ActivateAbility, CastSpell, apply_action, drain_stack
from mtg_bot.cards import SYNTHETIC_CREATURES
from mtg_bot.cards.parser.layout_face_grammar import (
    parse_face_effect,
    parse_face_trigger_phrase,
    parse_layout_condition,
)
from mtg_bot.effects.base import _apply_damage
from mtg_bot.effects.generic.layout_face_effects import (
    CardsInYourGraveyardAtLeast,
    ControlOtherPermanentOfColor,
    CreateEmblemWithStatics,
    CreateTriggersUntilYourNextTurn,
    DrawHalfLibraryRoundedUp,
    EachChoosesOneOfEachTypeSacrificesRest,
    EventSubjectGetsUEOT,
    LifeAtMostHalfStartingLife,
    LoseLifeEqualToEventAmount,
    NthCardDrawnThisTurn,
    PoisonCountersEqualToDamage,
    PumpTargetUntilYourNextTurn,
    PutPlusOneCounterOnEachMatching,
    ReturnTargetCardFromYourGraveyardToHand,
    TargetOpponentMills,
)
from mtg_bot.effects.predicates import Event
from mtg_bot.game import Zone, effective_power, is_creature_now
from mtg_bot.layouts import fire_deals_damage, is_transformed, transform_permanent
from mtg_bot.legal import legal_actions
from mtg_bot.turn import (
    Step,
    draw_card,
    move_off_battlefield,
    run_cleanup_step,
    run_untap_step,
    state_based_actions,
)
from tests._spells_b_helpers import ScriptedAgent, add, add_lands, make_state, printing

JACE = "Jace, Vryn's Prodigy // Jace, Telepath Unbound"
TAMIYO = "Tamiyo, Inquisitive Student // Tamiyo, Seasoned Scholar"
AJANI = "Ajani, Nacatl Pariah // Ajani, Nacatl Avenger"
CECIL = "Cecil, Dark Knight // Cecil, Redeemed Paladin"


def _creature(state, pid, name="Stalwart Knight"):
    obj = state.new_object(SYNTHETIC_CREATURES[name], pid, Zone.BATTLEFIELD)
    obj.summoning_sick = False
    state.battlefield.append(obj)
    return obj


def _loyalty(state, pid, obj, idx):
    apply_action(state, pid, ActivateAbility(source_id=obj.id, ability_index=idx))
    drain_stack(state)


# ---------------------------------------------------------------------------
# Jace, Vryn's Prodigy
# ---------------------------------------------------------------------------


def test_jace_loots_then_flips_with_five_in_graveyard():
    agent = ScriptedAgent()
    state = make_state(agent0=agent)
    jace = add(state, 0, JACE, Zone.BATTLEFIELD)
    for _ in range(3):
        add(state, 0, "Island", Zone.LIBRARY)
    add(state, 0, "Island", Zone.HAND)
    apply_action(state, 0, ActivateAbility(source_id=jace.id, ability_index=0))
    drain_stack(state)
    assert not is_transformed(jace) and jace in state.battlefield
    for _ in range(4):
        add(state, 0, "Swamp", Zone.GRAVEYARD)
    jace.tapped = False
    apply_action(state, 0, ActivateAbility(source_id=jace.id, ability_index=0))
    drain_stack(state)
    assert jace.printing.name == "Jace, Telepath Unbound"
    assert jace.loyalty_counters == 5 and not jace.tapped


def test_jace_back_face_abilities():
    agent = ScriptedAgent()
    state = make_state(agent0=agent)
    jace = add(state, 0, JACE, Zone.BATTLEFIELD)
    transform_permanent(state, jace)
    jace.loyalty_counters = 12
    ogre = _creature(state, 1)
    base = effective_power(state, ogre)
    agent.scripts["target"] = [("creature", ogre.id)]
    _loyalty(state, 0, jace, 0)
    assert jace.loyalty_counters == 13
    assert effective_power(state, ogre) == base - 2
    run_cleanup_step(state)
    assert effective_power(state, ogre) == base - 2
    state.active_player_idx = 1
    run_untap_step(state)
    assert effective_power(state, ogre) == base - 2
    state.active_player_idx = 0
    run_untap_step(state)
    assert effective_power(state, ogre) == base
    # -3: an instant in the graveyard may be cast this turn.
    bolt = add(state, 0, "Lightning Bolt", Zone.GRAVEYARD)
    state.loyalty_activated_this_turn.clear()
    agent.scripts["target"] = [("graveyard_card", bolt.id)]
    _loyalty(state, 0, jace, 1)
    assert bolt.castable_from_graveyard_this_turn
    assert bolt.exile_if_put_into_graveyard_from_stack
    add_lands(state, 0, "Mountain", 1)
    assert CastSpell(bolt.id) in legal_actions(state, 0)
    # -9: emblem -- whenever you cast a spell, target opponent mills five.
    for _ in range(6):
        add(state, 1, "Island", Zone.LIBRARY)
    state.loyalty_activated_this_turn.clear()
    _loyalty(state, 0, jace, 2)
    assert state.emblems
    agent.scripts["target"] = [("player", 1), ("player", 1)]
    apply_action(state, 0, CastSpell(bolt.id))
    drain_stack(state)
    assert len(state.players[1].graveyard) == 5
    assert bolt in state.players[0].exile


def test_target_opponent_mills():
    state = make_state()
    for _ in range(6):
        add(state, 1, "Island", Zone.LIBRARY)
    eff = TargetOpponentMills(amount=5)
    assert eff.requires_target()
    assert eff.legal_targets(state, 0) == [("player", 1)]
    eff.resolve(state, 0, (("player", 1),))
    assert len(state.players[1].graveyard) == 5
    assert "mills 5" in eff.describe()


# ---------------------------------------------------------------------------
# Tamiyo, Inquisitive Student
# ---------------------------------------------------------------------------


def test_tamiyo_flips_on_third_draw():
    state = make_state()
    tamiyo = add(state, 0, TAMIYO, Zone.BATTLEFIELD)
    for _ in range(4):
        add(state, 0, "Island", Zone.LIBRARY)
    draw_card(state, 0)
    draw_card(state, 0)
    assert not state.stack
    draw_card(state, 0)
    drain_stack(state)
    assert tamiyo.printing.name == "Tamiyo, Seasoned Scholar"
    assert tamiyo.loyalty_counters == 2
    # The opponent's third draw doesn't count.
    tam2 = add(state, 0, TAMIYO, Zone.BATTLEFIELD)
    for _ in range(3):
        add(state, 1, "Island", Zone.LIBRARY)
        draw_card(state, 1)
    assert not state.stack and not is_transformed(tam2)


def test_tamiyo_plus_two_shrinks_attackers_until_your_next_turn():
    from mtg_bot.actions import DeclareAttackers

    state = make_state()
    tamiyo = add(state, 0, TAMIYO, Zone.BATTLEFIELD)
    transform_permanent(state, tamiyo)
    tamiyo.loyalty_counters = 2
    _loyalty(state, 0, tamiyo, 0)
    assert tamiyo.loyalty_counters == 4 and state.emblems
    attacker = _creature(state, 1)
    base = effective_power(state, attacker)
    state.active_player_idx = 1
    state.step = Step.DECLARE_ATTACKERS
    apply_action(state, 1, DeclareAttackers(attacker_ids=frozenset({attacker.id})))
    drain_stack(state)
    assert effective_power(state, attacker) == base - 1
    run_cleanup_step(state)
    assert state.emblems  # lasts through the opponent's turn
    state.active_player_idx = 0
    run_untap_step(state)
    assert not state.emblems


def test_tamiyo_minus_three_and_minus_seven():
    agent = ScriptedAgent()
    state = make_state(agent0=agent)
    tamiyo = add(state, 0, TAMIYO, Zone.BATTLEFIELD)
    transform_permanent(state, tamiyo)
    tamiyo.loyalty_counters = 10
    bolt = add(state, 0, "Lightning Bolt", Zone.GRAVEYARD)
    agent.scripts["target"] = [("graveyard_card", bolt.id)]
    _loyalty(state, 0, tamiyo, 1)
    assert bolt in state.players[0].hand
    assert not state.players[0].mana_pool  # red: no bonus mana
    for _ in range(5):
        add(state, 0, "Island", Zone.LIBRARY)
    hand_before = len(state.players[0].hand)
    state.players[0].agent  # noqa: B018
    tamiyo2 = add(state, 0, TAMIYO, Zone.BATTLEFIELD)
    transform_permanent(state, tamiyo2)
    tamiyo2.loyalty_counters = 10
    _loyalty(state, 0, tamiyo2, 2)
    assert len(state.players[0].hand) == hand_before + 3
    # No maximum hand size from the emblem.
    for _ in range(10):
        add(state, 0, "Island", Zone.HAND)
    run_cleanup_step(state)
    assert len(state.players[0].hand) > 7


def test_return_card_green_bonus():
    state = make_state()
    grn = add(state, 0, AJANI, Zone.GRAVEYARD)  # a white card
    from mtg_bot.cards.base import AddManaToPool
    from mtg_bot.effects.generic.card_flow import CardFilter

    eff = ReturnTargetCardFromYourGraveyardToHand(
        card_filter=CardFilter(), bonus_color="W",
        bonus=AddManaToPool(produces=(("W", 1),)),
    )
    assert eff.legal_targets(state, 0) == [("graveyard_card", grn.id)]
    eff.resolve(state, 0, ())
    eff.resolve(state, 0, (("graveyard_card", 999),))
    eff.resolve(state, 0, (("graveyard_card", grn.id),))
    assert grn in state.players[0].hand and len(state.players[0].mana_pool) == 1
    assert "if it's W" in eff.describe()


# ---------------------------------------------------------------------------
# Ajani, Nacatl Pariah
# ---------------------------------------------------------------------------


def test_ajani_enters_with_cat_and_flips_when_cat_dies():
    state = make_state()
    ajani = add(state, 0, AJANI, Zone.HAND)
    add_lands(state, 0, "Plains", 2)
    apply_action(state, 0, CastSpell(ajani.id))
    drain_stack(state)
    cat = next(o for o in state.battlefield if o.printing.name == "Cat Warrior")
    move_off_battlefield(state, cat, destination="graveyard")
    drain_stack(state)
    assert ajani.printing.name == "Ajani, Nacatl Avenger"
    assert ajani.loyalty_counters == 3


def test_ajani_avenger_abilities():
    agent = ScriptedAgent()
    state = make_state(agent0=agent)
    ajani = add(state, 0, AJANI, Zone.BATTLEFIELD)
    transform_permanent(state, ajani)
    ajani.loyalty_counters = 10
    cat = add(state, 0, AJANI, Zone.BATTLEFIELD)  # a Cat Warrior creature
    _loyalty(state, 0, ajani, 0)
    assert cat.plus_one_counters == 1
    # 0: a Cat token, and -- Ajani himself is red -- but "other than
    # Ajani": no other red permanent, no damage.
    agent.scripts["target"] = [("player", 1)]
    _loyalty(state, 0, ajani, 1)
    assert state.players[1].life == 20
    # With another red permanent: damage equal to creatures you control.
    red = add(state, 0, "Fable of the Mirror-Breaker // Reflection of Kiki-Jiki", Zone.BATTLEFIELD)
    red.lore_counters = 1
    n_before = sum(1 for o in state.battlefield if o.controller_id == 0 and is_creature_now(o))
    agent.scripts["target"] = [("player", 1)]
    _loyalty(state, 0, ajani, 1)
    assert state.players[1].life == 20 - (n_before + 1)


def test_ajani_minus_four_each_opponent_keeps_one_of_each():
    agent1 = ScriptedAgent()
    state = make_state(agent1=agent1)
    ajani = add(state, 0, AJANI, Zone.BATTLEFIELD)
    transform_permanent(state, ajani)
    ajani.loyalty_counters = 10
    c1 = _creature(state, 1)
    c2 = _creature(state, 1)
    ring = add(state, 1, "Sol Ring", Zone.BATTLEFIELD)
    land = add(state, 1, "Swamp", Zone.BATTLEFIELD)
    mine = _creature(state, 0)
    agent1.scripts["legend_keep"] = []
    _loyalty(state, 0, ajani, 2)
    state_based_actions(state)
    kept = [o for o in (c1, c2) if o in state.battlefield]
    assert len(kept) == 1 and ring in state.battlefield and land in state.battlefield
    assert mine in state.battlefield
    assert "keeps one" in EachChoosesOneOfEachTypeSacrificesRest().describe()
    both = EachChoosesOneOfEachTypeSacrificesRest(opponents_only=False, nonland_only=False)
    both.resolve(state, 0)
    assert "each player" in both.describe()


def test_put_counter_on_each_matching():
    from mtg_bot.effects.object_predicates import IsCreature

    state = make_state()
    a = _creature(state, 0)
    b = _creature(state, 1)
    eff = PutPlusOneCounterOnEachMatching(predicate=IsCreature())
    eff.resolve(state, 0)
    assert a.plus_one_counters == 1 and b.plus_one_counters == 0
    assert "each matching" in eff.describe()


# ---------------------------------------------------------------------------
# Cecil, Dark Knight
# ---------------------------------------------------------------------------


def test_cecil_combat_damage_loses_life_then_flips_at_half():
    from mtg_bot.combat import resolve_combat_damage

    state = make_state()
    cecil = add(state, 0, CECIL, Zone.BATTLEFIELD)
    cecil.attacking = True
    cecil.tapped = True
    state.step = Step.COMBAT_DAMAGE
    resolve_combat_damage(state, 1)
    drain_stack(state)
    assert state.players[1].life == 18 and state.players[0].life == 18
    assert not is_transformed(cecil)
    state.players[0].life = 12
    resolve_combat_damage(state, 1)
    drain_stack(state)
    assert state.players[0].life == 10
    assert cecil.printing.name == "Cecil, Redeemed Paladin" and not cecil.tapped


def test_cecil_noncombat_damage_triggers_too():
    state = make_state()
    cecil = add(state, 0, CECIL, Zone.BATTLEFIELD)
    target = _creature(state, 1)
    state.resolving_source = cecil
    _apply_damage(state, ("creature", target.id), 2)
    state.resolving_source = None
    drain_stack(state)
    assert state.players[0].life == 18
    # Players and planeswalkers too.
    state.resolving_source = cecil
    _apply_damage(state, ("player", 1), 1)
    state.resolving_source = None
    drain_stack(state)
    assert state.players[0].life == 17
    fire_deals_damage(state, None, 3)
    fire_deals_damage(state, cecil, 0)
    assert not state.stack


def test_redeemed_paladin_protects_other_attackers():
    from mtg_bot.actions import DeclareAttackers
    from mtg_bot.game import effective_keywords

    state = make_state()
    cecil = add(state, 0, CECIL, Zone.BATTLEFIELD)
    transform_permanent(state, cecil)
    buddy = _creature(state, 0)
    state.step = Step.DECLARE_ATTACKERS
    apply_action(state, 0, DeclareAttackers(attacker_ids=frozenset({cecil.id, buddy.id})))
    drain_stack(state)
    assert "indestructible" in effective_keywords(state, buddy)
    assert "indestructible" not in effective_keywords(state, cecil)
    assert "lifelink" in effective_keywords(state, cecil)


# ---------------------------------------------------------------------------
# Grammar / primitives
# ---------------------------------------------------------------------------


def test_conditions():
    state = make_state()
    assert parse_layout_condition("there are five or more cards in your graveyard") == (
        CardsInYourGraveyardAtLeast(n=5)
    )
    assert parse_layout_condition(
        "your life total is less than or equal to half your starting life total"
    ) == LifeAtMostHalfStartingLife()
    assert parse_layout_condition(
        "you control a red permanent other than Ajani"
    ) == ControlOtherPermanentOfColor(color="R")
    assert parse_layout_condition("the moon is full") is None
    assert not CardsInYourGraveyardAtLeast(1).matches(state, 0)
    assert not LifeAtMostHalfStartingLife().matches(state, 0)
    state.players[0].life = 10
    assert LifeAtMostHalfStartingLife().matches(state, 0)
    assert not ControlOtherPermanentOfColor("R").matches(state, 0)


def test_face_grammar_rejections():
    assert parse_face_effect("if the moon is full, draw a card") is None
    assert parse_face_effect("if there are two or more cards in your graveyard, frobnicate") is None
    assert parse_face_effect("frobnicate. When you do, draw a card") is None
    assert parse_face_effect("deals damage equal to the number of widgets you control to any target") is None
    assert parse_face_effect("target widget gets -2/-0 until your next turn") is None
    assert parse_face_effect(
        "you may cast target widget card from your graveyard this turn. If that spell "
        "would be put into your graveyard, exile it instead"
    ) is None
    assert parse_face_effect("other attacking creatures gain frobnication until end of turn") is None
    assert parse_face_effect("put a +1/+1 counter on each widget you control") is None
    assert parse_face_effect("return target widget card from your graveyard to your hand") is None
    assert parse_face_effect(
        "return target creature card from your graveyard to your hand. If it's a red card, frobnicate"
    ) is None
    assert parse_face_effect('you get an emblem with "Frobnicate."') is None
    assert parse_face_effect("until your next turn, whenever frobnication happens, draw a card") is None
    assert parse_face_effect(
        "until your next turn, whenever a creature attacks you or a planeswalker you control, it gets +x/+y until end of turn"
    ) is None
    assert parse_face_effect(
        "each opponent chooses an artifact and a widget from among the permanents they control, then sacrifices the rest"
    ) is None
    assert parse_face_trigger_phrase("frobnication happens") is None


def test_until_your_next_turn_with_a_regular_trigger():
    eff = parse_face_effect(
        "until your next turn, whenever you cast a spell, draw a card"
    )
    assert isinstance(eff, CreateTriggersUntilYourNextTurn)
    assert "until your next turn" in eff.describe()


def test_trigger_phrases():
    trig = parse_face_trigger_phrase("you draw your second card each turn")
    assert trig[0] == Event.DRAWS_CARD
    assert parse_face_trigger_phrase("this creature deals damage")[0] == Event.DEALS_DAMAGE
    assert NthCardDrawnThisTurn(2).matches(None, {}, None) is False


def test_small_primitives():
    state = make_state()
    p0 = state.players[0]
    LoseLifeEqualToEventAmount().resolve(state, 0)
    assert p0.life == 20
    state.resolving_combat_damage_amount = 3
    LoseLifeEqualToEventAmount().resolve(state, 0)
    assert p0.life == 17
    PoisonCountersEqualToDamage().resolve(state, 0, (("player", 1),))
    assert state.players[1].poison_counters == 3
    PoisonCountersEqualToDamage().resolve(state, 0, ())
    state.resolving_combat_damage_amount = 0
    for eff in (LoseLifeEqualToEventAmount(), PoisonCountersEqualToDamage(),
                DrawHalfLibraryRoundedUp(), CreateEmblemWithStatics()):
        assert eff.describe()
    for _ in range(5):
        add(state, 0, "Island", Zone.LIBRARY)
    DrawHalfLibraryRoundedUp().resolve(state, 0)
    assert len(p0.hand) == 3
    assert "until your next turn" in PumpTargetUntilYourNextTurn(power=-2).describe()
    assert "until end of turn" in EventSubjectGetsUEOT(power=-1).describe()
    EventSubjectGetsUEOT(power=-1).resolve(state, 0)
    assert EventSubjectGetsUEOT().event_subject_id({"player": p0}) == -1


def test_pump_until_next_turn_fizzles_on_illegal_target():
    from mtg_bot.effects.object_predicates import IsCreature
    from mtg_bot.effects.targets import TargetSpec

    state = make_state()
    land = add(state, 1, "Swamp", Zone.BATTLEFIELD)
    eff = PumpTargetUntilYourNextTurn(power=-2, targets=(TargetSpec(IsCreature()),))
    eff.resolve(state, 0, (("creature", land.id),))
    assert not state.continuous_effects


def test_jace_cast_permission_expires_at_cleanup():
    from mtg_bot.effects.generic.card_flow import CardFilter
    from mtg_bot.effects.generic.layout_face_effects import (
        MayCastTargetGraveyardCardThisTurnExileInstead,
    )

    state = make_state()
    bolt = add(state, 0, "Lightning Bolt", Zone.GRAVEYARD)
    eff = MayCastTargetGraveyardCardThisTurnExileInstead(
        card_filter=CardFilter(any_types=("Instant",)),
    )
    assert eff.requires_target()
    assert eff.legal_targets(state, 0) == [("graveyard_card", bolt.id)]
    eff.resolve(state, 0, ())
    eff.resolve(state, 0, (("graveyard_card", 999),))
    eff.resolve(state, 0, (("graveyard_card", bolt.id),))
    assert bolt.exile_if_put_into_graveyard_from_stack
    run_cleanup_step(state)
    assert not bolt.castable_from_graveyard_this_turn
    assert not bolt.exile_if_put_into_graveyard_from_stack
    assert "exile it instead" in eff.describe()
