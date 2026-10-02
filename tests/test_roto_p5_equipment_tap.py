"""Vintage Roto P5: Equipment and tap/untap effects -- Umezawa's Jitte,
Hawkeye's Bow, Lavaspur Boots, Ichorclaw Myr, Deceiver Exarch,
Opposition, Earthcraft, Minamo, Pendelhaven -- and the charms (Emerald,
Boros, Prismari Charm)."""

from __future__ import annotations

from mtg_bot.cards.parser.roto_board import (
    claim_equipment_lines,
    parse_roto_board_effect,
    parse_roto_board_line,
    parse_roto_trigger_phrase,
)
from mtg_bot.cards.parser.creature_rmc_grammar import rmc_grammar_disabled
from mtg_bot.combat import declare_attackers, declare_blockers, resolve_combat_damage
from mtg_bot.effects.generic.roto_board import (
    DealDamageToEachTarget,
    EventSubjectDealsDamageToEachOpponent,
    GrantKeywordsToEachUEOT,
    LoseKeywordUEOT,
    PumpEquippedCreatureUEOT,
)
from mtg_bot.effects.predicates import Event
from mtg_bot.game import (
    Zone,
    effective_keywords,
    effective_power,
    effective_toughness,
    effective_ward_cost,
)
from mtg_bot.turn import Step, run_cleanup_step, tap_permanent

from tests._roto_p5_helpers import (
    activate,
    cast,
    lands,
    make_state,
    place,
    printing,
    resolve_all,
    roto_card,
    script,
    vanilla,
)


def _equip(state, equipment_name, creature, pid=0):
    eq = place(state, pid, equipment_name)
    eq.attached_to = creature.id
    return eq


def _combat(state, attackers, blocks=None, defender=1):
    state.step = Step.DECLARE_ATTACKERS
    declare_attackers(state, [a.id for a in attackers])
    resolve_all(state)
    state.step = Step.DECLARE_BLOCKERS
    declare_blockers(state, blocks or {})
    resolve_all(state)
    state.step = Step.COMBAT_DAMAGE
    resolve_combat_damage(state, defender)
    resolve_all(state)


# ---------------------------------------------------------------------------
# Grammar
# ---------------------------------------------------------------------------


def test_trigger_phrases():
    assert parse_roto_trigger_phrase(
        "equipped creature deals combat damage"
    )[0] is Event.DEALS_COMBAT_DAMAGE_ANY
    assert parse_roto_trigger_phrase(
        "this creature becomes blocked"
    )[0] is Event.BECOMES_BLOCKED
    assert parse_roto_trigger_phrase("this creature becomes tired") is None
    with rmc_grammar_disabled():
        assert parse_roto_trigger_phrase("this creature becomes blocked") is None


def test_effect_phrases():
    assert parse_roto_board_effect(
        "equipped creature gets +2/+2 until end of turn"
    ) == PumpEquippedCreatureUEOT(power_bonus=2, toughness_bonus=2)
    lose = parse_roto_board_effect("target creature loses flying until end of turn")
    assert isinstance(lose, LoseKeywordUEOT) and lose.keyword == "flying"
    assert lose.describe().startswith("target creature loses flying")
    assert parse_roto_board_effect(
        "target creature loses gizmo until end of turn"
    ) is None
    each = parse_roto_board_effect(
        "permanents you control gain indestructible until end of turn"
    )
    assert isinstance(each, GrantKeywordsToEachUEOT)
    assert "indestructible" in each.describe()
    assert parse_roto_board_effect(
        "permanents you control gain gizmos until end of turn"
    ) is None
    pris = parse_roto_board_effect("deals 1 damage to each of one or two targets")
    assert isinstance(pris, DealDamageToEachTarget)
    assert pris.targets[0].count_min == 1 and pris.targets[0].count_max == 2
    assert "one or two" in pris.describe()
    upto = parse_roto_board_effect("deals 1 damage to each of up to two targets")
    assert upto.targets[0].count_min == 0
    # Damage to a player-or-permanent list needs a player arm.
    assert parse_roto_board_effect(
        "deals 2 damage to target creature or planeswalker"
    ) is None
    assert parse_roto_board_effect(
        "deals 2 damage to target opponent or gizmo"
    ) is None
    assert parse_roto_board_effect("destroy target gizmo") is None
    assert parse_roto_board_effect("untap target gizmo") is None
    assert parse_roto_board_effect("tap up to X target creatures") is None
    assert parse_roto_board_effect("target gizmo gets +1/+1 until end of turn") is None


def test_equipped_it_trigger_line():
    line = parse_roto_board_line(
        "Whenever equipped creature attacks, it deals 2 damage to each "
        "opponent.", {"name": "X"},
    )
    (trig,) = line.triggers
    assert trig.event is Event.ATTACKS
    assert trig.effect == EventSubjectDealsDamageToEachOpponent(
        amount=2, subject_slot="attacker",
    )
    assert parse_roto_board_line(
        "Whenever equipped creature attacks, it gains flying.", {"name": "X"},
    ) is None


def test_claim_equipment_lines_rejects_a_bad_modal_block():
    card = dict(roto_card("Umezawa's Jitte"))
    card["oracle_text"] = (
        "Remove a charge counter from this: Choose one —\n"
        "• Do something odd.\n• You gain 2 life.\nEquip {2}"
    )
    assert claim_equipment_lines(card) is None
    with rmc_grammar_disabled():
        text, board = claim_equipment_lines(card)
        assert text == card["oracle_text"] and board.activated == ()


# ---------------------------------------------------------------------------
# Umezawa's Jitte
# ---------------------------------------------------------------------------


def test_jitte_counts_combat_damage_once_per_step():
    state = make_state()
    bear = place(state, 0, vanilla(2, 2, name="Bear"))
    jitte = _equip(state, "Umezawa's Jitte", bear)
    b1 = place(state, 1, vanilla(1, 1, name="Blocker 1"))
    b2 = place(state, 1, vanilla(1, 1, name="Blocker 2"))
    _combat(state, [bear], {b1.id: bear.id, b2.id: bear.id})
    # Damage to two blockers is still one "deals combat damage" event.
    assert jitte.charge_counters == 2


def test_jitte_unblocked_damage_and_modes():
    state = make_state()
    bear = place(state, 0, vanilla(2, 2, name="Bear"))
    jitte = _equip(state, "Umezawa's Jitte", bear)
    _combat(state, [bear])
    assert jitte.charge_counters == 2
    assert state.players[1].life == 18
    # Mode 0: equipped creature gets +2/+2.
    state.step = Step.POSTCOMBAT_MAIN
    script(state, 0, "mode", 0)
    activate(state, 0, jitte, 0)
    assert jitte.charge_counters == 1
    assert effective_power(state, bear) == 4
    # Mode 1: target creature gets -1/-1.
    elf = place(state, 1, "Llanowar Elves")
    script(state, 0, "target", ("creature", elf.id))
    script(state, 0, "mode", 1)
    activate(state, 0, jitte, 0)
    assert elf in state.players[1].graveyard
    assert jitte.charge_counters == 0


def test_jitte_life_mode_and_unattached_pump():
    state = make_state()
    jitte = place(state, 0, "Umezawa's Jitte")
    jitte.charge_counters = 2
    script(state, 0, "mode", 2)
    activate(state, 0, jitte, 0)
    assert state.players[0].life == 22
    script(state, 0, "mode", 0)
    activate(state, 0, jitte, 0)   # unattached: nothing to pump
    assert jitte.charge_counters == 0
    assert "pump does nothing" in " ".join(state.log)


def test_jitte_ignores_noncombat_damage():
    from mtg_bot.effects.base import _apply_damage

    state = make_state()
    bear = place(state, 0, vanilla(2, 2))
    jitte = _equip(state, "Umezawa's Jitte", bear)
    state.resolving_source = bear
    _apply_damage(state, ("player", 1), 2)
    state.resolving_source = None
    resolve_all(state)
    assert jitte.charge_counters == 0


# ---------------------------------------------------------------------------
# Hawkeye's Bow / Lavaspur Boots
# ---------------------------------------------------------------------------


def test_hawkeyes_bow_damage_comes_from_the_equipped_creature():
    state = make_state()
    bear = place(state, 0, vanilla(2, 2, name="Archer"))
    bow = _equip(state, "Hawkeye's Bow", bear)
    assert effective_power(state, bear) == 3
    assert "reach" in effective_keywords(state, bear)
    tap_permanent(state, bear)
    item = state.stack[-1]
    assert item.event_subject_id == bear.id
    resolve_all(state)
    assert state.players[1].life == 19
    assert state.players[0].life == 20
    # Tapping the Bow itself isn't the equipped creature becoming tapped.
    tap_permanent(state, bow)
    assert not state.stack


def test_hawkeyes_bow_damage_survives_the_creature_leaving():
    from mtg_bot.turn import move_off_battlefield

    state = make_state()
    bear = place(state, 0, vanilla(2, 2))
    _equip(state, "Hawkeye's Bow", bear)
    tap_permanent(state, bear)
    move_off_battlefield(state, bear)
    resolve_all(state)
    assert state.players[1].life == 19


def test_lavaspur_boots_grant_haste_and_ward():
    state = make_state()
    bear = place(state, 0, vanilla(2, 2), sick=True)
    _equip(state, "Lavaspur Boots", bear)
    assert "haste" in effective_keywords(state, bear)
    assert effective_power(state, bear) == 3
    cost, label = effective_ward_cost(state, bear)
    assert cost.generic == 1 and label == "{1}"


# ---------------------------------------------------------------------------
# Ichorclaw Myr
# ---------------------------------------------------------------------------


def test_ichorclaw_myr_pumps_once_when_blocked():
    state = make_state()
    myr = place(state, 0, "Ichorclaw Myr")
    b1 = place(state, 1, vanilla(1, 4, name="Wall 1"))
    b2 = place(state, 1, vanilla(1, 4, name="Wall 2"))
    state.step = Step.DECLARE_ATTACKERS
    declare_attackers(state, [myr.id])
    state.step = Step.DECLARE_BLOCKERS
    declare_blockers(state, {b1.id: myr.id, b2.id: myr.id})
    resolve_all(state)
    # A 1/1 that got +2/+2 exactly once.
    assert effective_power(state, myr) == 3
    assert effective_toughness(state, myr) == 3


def test_ichorclaw_myr_unblocked_gets_nothing():
    state = make_state()
    myr = place(state, 0, "Ichorclaw Myr")
    _combat(state, [myr])
    assert state.players[1].poison_counters == 1


# ---------------------------------------------------------------------------
# Deceiver Exarch / Opposition / Earthcraft / Minamo / Pendelhaven
# ---------------------------------------------------------------------------


def test_deceiver_exarch_modes():
    state = make_state()
    lands(state, 0, "Island", 3)
    mine = place(state, 0, "Wasteland", tapped=True)
    theirs = place(state, 1, "Underground Sea")
    exarch = place(state, 0, "Deceiver Exarch", Zone.HAND)
    script(state, 0, "target", ("permanent", mine.id))
    script(state, 0, "mode", 0)
    cast(state, 0, exarch)
    assert not mine.tapped
    exarch2 = place(state, 0, "Deceiver Exarch", Zone.HAND)
    for land in state.battlefield:
        if land.printing.name == "Island":
            land.tapped = False
    script(state, 0, "target", ("permanent", theirs.id))
    script(state, 0, "mode", 1)
    cast(state, 0, exarch2)
    assert theirs.tapped


def test_opposition_taps_with_an_untapped_creature():
    state = make_state()
    opp = place(state, 0, "Opposition")
    elf = place(state, 0, "Llanowar Elves", sick=True)
    land = place(state, 1, "Underground Sea")
    script(state, 0, "target", ("permanent", land.id))
    activate(state, 0, opp)
    assert land.tapped and elf.tapped


def test_earthcraft_untaps_a_basic_land():
    state = make_state()
    craft = place(state, 0, "Earthcraft")
    place(state, 0, vanilla(1, 1))
    forest = place(state, 0, "Forest", tapped=True)
    waste = place(state, 0, "Wasteland", tapped=True)
    effect = craft.printing.activated_abilities[0].effect
    assert effect.legal_targets(state, 0) == [("permanent", forest.id)]
    activate(state, 0, craft)
    assert not forest.tapped and waste.tapped


def test_minamo_untaps_legendary_permanents_only():
    state = make_state()
    minamo = place(state, 0, "Minamo, School at Water's Edge")
    place(state, 0, "Island")
    legend = place(state, 0, vanilla(2, 2, name="Legend", legendary=True), tapped=True)
    place(state, 0, vanilla(2, 2, name="Nobody"), tapped=True)
    ability = next(
        a for a in minamo.printing.activated_abilities if not a.is_mana_ability
    )
    # Minamo itself is a legendary permanent too.
    assert ability.effect.legal_targets(state, 0) == [
        ("permanent", minamo.id), ("creature", legend.id),
    ]
    script(state, 0, "target", ("creature", legend.id))
    idx = minamo.printing.activated_abilities.index(ability)
    activate(state, 0, minamo, idx)
    assert not legend.tapped


def test_pendelhaven_pumps_a_one_one():
    state = make_state()
    haven = place(state, 0, "Pendelhaven")
    elf = place(state, 0, "Llanowar Elves")
    place(state, 0, vanilla(2, 2))
    ability = next(
        a for a in haven.printing.activated_abilities if not a.is_mana_ability
    )
    assert ability.effect.legal_targets(state, 0) == [("creature", elf.id)]
    activate(state, 0, haven, haven.printing.activated_abilities.index(ability))
    assert (effective_power(state, elf), effective_toughness(state, elf)) == (2, 3)


# ---------------------------------------------------------------------------
# Charms
# ---------------------------------------------------------------------------


def test_emerald_charm_modes():
    state = make_state()
    lands(state, 0, "Forest", 3)
    waste = place(state, 0, "Wasteland", tapped=True)
    charm = place(state, 0, "Emerald Charm", Zone.HAND)
    script(state, 0, "mode", 0)
    script(state, 0, "target", ("permanent", waste.id))
    cast(state, 0, charm)
    assert not waste.tapped
    # Non-Aura enchantment.
    seal = place(state, 1, "Seal of Cleansing")
    charm2 = place(state, 0, "Emerald Charm", Zone.HAND)
    script(state, 0, "mode", 1)
    script(state, 0, "target", ("permanent", seal.id))
    cast(state, 0, charm2)
    assert seal in state.players[1].graveyard
    # Lose flying until end of turn.
    flier = place(state, 1, vanilla(2, 2, name="Flier", keywords=frozenset({"flying"})))
    charm3 = place(state, 0, "Emerald Charm", Zone.HAND)
    script(state, 0, "mode", 2)
    script(state, 0, "target", ("creature", flier.id))
    cast(state, 0, charm3)
    assert "flying" not in effective_keywords(state, flier)
    run_cleanup_step(state)
    assert "flying" in effective_keywords(state, flier)


def test_boros_charm_modes():
    state = make_state()
    lands(state, 0, "Plateau", 2)
    charm = place(state, 0, "Boros Charm", Zone.HAND)
    script(state, 0, "mode", 0)
    script(state, 0, "target", ("player", 1))
    cast(state, 0, charm)
    assert state.players[1].life == 16
    for land in state.battlefield:
        land.tapped = False
    rock = place(state, 0, "Mox Pearl")
    bear = place(state, 0, vanilla(2, 2))
    theirs = place(state, 1, vanilla(2, 2, name="Theirs"))
    charm2 = place(state, 0, "Boros Charm", Zone.HAND)
    script(state, 0, "mode", 1)
    cast(state, 0, charm2)
    assert "indestructible" in effective_keywords(state, rock)
    assert "indestructible" in effective_keywords(state, bear)
    assert "indestructible" not in effective_keywords(state, theirs)


def test_prismari_charm_hits_one_or_two_targets():
    state = make_state()
    lands(state, 0, "Volcanic Island", 2)
    a = place(state, 1, vanilla(1, 1, name="A"))
    b = place(state, 1, vanilla(1, 1, name="B"))
    charm = place(state, 0, "Prismari Charm", Zone.HAND)
    script(state, 0, "mode", 1)
    script(state, 0, "target", ("creature", a.id), ("creature", b.id))
    cast(state, 0, charm)
    assert a in state.players[1].graveyard and b in state.players[1].graveyard


def test_deal_damage_to_each_target_skips_illegal_targets():
    from mtg_bot.effects.targets import TargetSpec
    from mtg_bot.effects.object_predicates import IsCreature

    state = make_state()
    a = place(state, 1, vanilla(1, 1))
    eff = DealDamageToEachTarget(amount=1, targets=(TargetSpec(IsCreature()),))
    eff.resolve(state, 0, (("creature", a.id), ("creature", 999)))
    assert a.damage == 1
    eff.resolve(state, 0, ())
    assert DealDamageToEachTarget(amount=2).describe().endswith("the targets")
