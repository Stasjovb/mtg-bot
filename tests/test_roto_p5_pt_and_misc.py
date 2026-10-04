"""Vintage Roto P5: static / dynamic P/T and one-off effects -- Elvish
Reclaimer, Knight of the Reliquary, Kaheera, Craterhoof Behemoth, Might
of Old Krosa, Devoted Druid, Shrieking Drake, Aether Vial, Terastodon,
Aang's Iceberg, Temporary Lockdown and Turnabout."""

from __future__ import annotations

from mtg_bot.actions import put_into_battlefield
from mtg_bot.cards.parser.roto_board import (
    parse_roto_board_effect,
    parse_roto_board_line,
    parse_roto_cost_piece,
)
from mtg_bot.effects.generic.roto_board import (
    IfResolvingInYourMainPhase,
    PutMinusOneCounterOnSelfCost,
    TapOrUntapAllOfChosenType,
)
# Shrieking Drake's untargeted bounce is P3's recognizer / effect (the
# Simic Growth Chamber shape); P5's identical copy was dropped when the
# packages were integrated.
from mtg_bot.effects.generic.roto_mana import ReturnPermanentYouControlToHand
from mtg_bot.game import (
    Zone,
    effective_keywords,
    effective_power,
    effective_toughness,
)
from mtg_bot.turn import Step, move_off_battlefield, state_based_actions

from tests._roto_p5_helpers import (
    activate,
    can_activate,
    cast,
    lands,
    make_state,
    place,
    printing,
    resolve_all,
    script,
    vanilla,
)


def _pt(state, obj):
    return effective_power(state, obj), effective_toughness(state, obj)


# ---------------------------------------------------------------------------
# Grammar edges
# ---------------------------------------------------------------------------


def test_grammar_edges():
    assert parse_roto_cost_piece("Put a -1/-1 counter on this creature").atom == (
        PutMinusOneCounterOnSelfCost()
    )
    assert parse_roto_board_effect(
        "return a gizmo you control to its owner's hand"
    ) is None
    assert parse_roto_board_effect(
        "creatures you control gain gizmo and get +X/+X until end of turn, "
        "where X is the number of creatures you control"
    ) is None
    assert parse_roto_board_effect(
        "target gizmo gets +2/+2 until end of turn. If you cast this spell "
        "during your main phase, that creature gets +4/+4 until end of turn "
        "instead"
    ) is None
    assert parse_roto_board_effect(
        "destroy up to three target gizmos. For each permanent put into a "
        "graveyard this way, its controller creates a 3/3 green Elephant "
        "creature token"
    ) is None
    assert parse_roto_board_effect(
        "destroy target artifact. For each permanent put into a graveyard "
        "this way, its controller creates a gizmo"
    ) is None
    assert parse_roto_board_effect(
        "exile target gizmo until this enchantment leaves the battlefield"
    ) is None
    assert parse_roto_board_effect(
        "exile each gizmo until this enchantment leaves the battlefield"
    ) is None
    assert parse_roto_board_effect(
        "choose artifact, creature, or gizmo. Tap all untapped permanents of "
        "the chosen type target player controls, or untap all tapped "
        "permanents of that type that player controls"
    ) is None
    assert parse_roto_board_line(
        "This creature gets +2/+2 as long as there are many or more land "
        "cards in your graveyard.", {"name": "X"},
    ) is None
    assert parse_roto_board_line(
        "This creature gets +1/+1 for each gizmo card in your graveyard.",
        {"name": "X"},
    ) is None
    assert parse_roto_board_line(
        "Each other creature you control that's a Cat or Beast gets +1/+1 "
        "and has gizmo.", {"name": "X"},
    ) is None
    only_pt = parse_roto_board_line(
        "Each other creature you control that's a Cat or Beast gets +1/+1.",
        {"name": "X"},
    )
    assert len(only_pt.statics) == 1


# ---------------------------------------------------------------------------
# Static P/T
# ---------------------------------------------------------------------------


def test_elvish_reclaimer_threshold():
    state = make_state()
    elf = place(state, 0, "Elvish Reclaimer")
    assert _pt(state, elf) == (1, 2)
    for _ in range(2):
        place(state, 0, "Forest", Zone.GRAVEYARD)
    place(state, 1, "Forest", Zone.GRAVEYARD)   # the opponent's don't count
    place(state, 0, "Lightning Bolt", Zone.GRAVEYARD)
    assert _pt(state, elf) == (1, 2)
    place(state, 0, "Wasteland", Zone.GRAVEYARD)
    assert _pt(state, elf) == (3, 4)


def test_knight_of_the_reliquary_counts_land_cards():
    state = make_state()
    knight = place(state, 0, "Knight of the Reliquary")
    assert _pt(state, knight) == (2, 2)
    for name in ("Forest", "Wasteland", "Lightning Bolt"):
        place(state, 0, name, Zone.GRAVEYARD)
    assert _pt(state, knight) == (4, 4)


def test_kaheera_pumps_other_listed_types_once():
    state = make_state()
    kaheera = place(state, 0, "Kaheera, the Orphanguard")
    cat_beast = place(state, 0, vanilla(2, 2, name="Cat Beast", subtypes=("Cat", "Beast")))
    elemental = place(state, 0, vanilla(1, 1, name="Elemental", subtypes=("Elemental",)))
    human = place(state, 0, vanilla(2, 2, name="Human", subtypes=("Human",)))
    theirs = place(state, 1, vanilla(2, 2, name="Their Cat", subtypes=("Cat",)))
    assert _pt(state, cat_beast) == (3, 3)     # once, not per subtype
    assert _pt(state, elemental) == (2, 2)
    assert _pt(state, human) == (2, 2)
    assert _pt(state, theirs) == (2, 2)
    assert _pt(state, kaheera) == (3, 2)       # "other": not itself
    assert "vigilance" in effective_keywords(state, cat_beast)
    assert "vigilance" not in effective_keywords(state, human)


# ---------------------------------------------------------------------------
# Craterhoof / Might of Old Krosa
# ---------------------------------------------------------------------------


def test_craterhoof_counts_creatures_on_resolution():
    state = make_state()
    a = place(state, 0, vanilla(1, 1, name="A"))
    b = place(state, 0, vanilla(2, 2, name="B"))
    theirs = place(state, 1, vanilla(2, 2, name="Theirs"))
    hoof = state.new_object(printing("Craterhoof Behemoth"), owner_id=0, zone=Zone.HAND)
    put_into_battlefield(state, hoof, 0)
    resolve_all(state)
    # Three creatures (Hoof included): everyone gets +3/+3 and trample.
    assert _pt(state, a) == (4, 4)
    assert _pt(state, b) == (5, 5)
    assert _pt(state, hoof) == (8, 8)
    assert "trample" in effective_keywords(state, a)
    assert _pt(state, theirs) == (2, 2)


def test_might_of_old_krosa_main_phase_vs_other_steps():
    state = make_state()
    lands(state, 0, "Forest", 2)
    bear = place(state, 0, vanilla(2, 2))
    might = place(state, 0, "Might of Old Krosa", Zone.HAND)
    assert isinstance(might.printing.spell_effect, IfResolvingInYourMainPhase)
    cast(state, 0, might)
    assert _pt(state, bear) == (6, 6)
    state.step = Step.BEGINNING_OF_COMBAT
    might2 = place(state, 0, "Might of Old Krosa", Zone.HAND)
    cast(state, 0, might2)
    assert _pt(state, bear) == (8, 8)
    assert "main phase" in might.printing.spell_effect.describe()


def test_might_of_old_krosa_in_opponents_main_phase_is_plus_two():
    state = make_state()
    state.active_player_idx = 1
    state.priority_player_idx = 0
    lands(state, 0, "Forest", 1)
    bear = place(state, 0, vanilla(2, 2))
    might = place(state, 0, "Might of Old Krosa", Zone.HAND)
    cast(state, 0, might)
    assert _pt(state, bear) == (4, 4)


# ---------------------------------------------------------------------------
# Devoted Druid / Shrieking Drake / Aether Vial
# ---------------------------------------------------------------------------


def test_devoted_druid_untaps_with_minus_counters():
    state = make_state()
    druid = place(state, 0, "Devoted Druid")
    druid.tapped = True
    assert can_activate(state, 0, druid, 1)
    activate(state, 0, druid, 1)
    assert not druid.tapped and druid.minus_one_counters == 1
    druid.tapped = True
    activate(state, 0, druid, 1)
    # Toughness 0: it dies to the state-based action.
    assert druid in state.players[0].graveyard
    cost = PutMinusOneCounterOnSelfCost()
    assert not cost.payable(state, 0, druid)
    assert cost.describe() == "Put a -1/-1 counter on ~"


def test_shrieking_drake_returns_a_creature_you_control():
    state = make_state()
    lands(state, 0, "Island", 1)
    bear = place(state, 0, vanilla(2, 2))
    drake = place(state, 0, "Shrieking Drake", Zone.HAND)
    # Picked on resolution through the "which of my permanents" hook.
    script(state, 0, "sacrifice", bear.id)
    cast(state, 0, drake)
    assert bear in state.players[0].hand
    assert drake in state.battlefield


def test_shrieking_drake_alone_returns_itself():
    state = make_state()
    lands(state, 0, "Island", 1)
    drake = place(state, 0, "Shrieking Drake", Zone.HAND)
    cast(state, 0, drake)
    assert drake in state.players[0].hand


def test_return_you_control_with_nothing_to_return():
    state = make_state()
    eff = printing("Shrieking Drake").triggered_abilities[0].effect
    assert isinstance(eff, ReturnPermanentYouControlToHand)
    eff.resolve(state, 0)
    assert "no creature to return" in state.log[-1]
    assert eff.describe().startswith("return a creature")


def test_aether_vial_puts_a_matching_creature():
    state = make_state()
    vial = place(state, 0, "Aether Vial")
    vial.charge_counters = 1
    elves = place(state, 0, "Llanowar Elves", Zone.HAND)
    bear = place(state, 0, vanilla(2, 2, cost="{1}{G}"), Zone.HAND)
    activate(state, 0, vial)
    assert elves in state.battlefield and bear in state.players[0].hand
    vial.tapped = False
    script(state, 0, "hand", None)
    vial.charge_counters = 2
    activate(state, 0, vial)
    assert bear in state.players[0].hand   # declined


def test_aether_vial_upkeep_counter():
    from mtg_bot.turn import run_beginning_of_upkeep_triggers

    state = make_state()
    vial = place(state, 0, "Aether Vial")
    state.step = Step.UPKEEP
    run_beginning_of_upkeep_triggers(state)
    resolve_all(state)
    assert vial.charge_counters == 1


# ---------------------------------------------------------------------------
# Terastodon / Aang's Iceberg / Temporary Lockdown / Turnabout
# ---------------------------------------------------------------------------


def test_terastodon_elephants_for_each_permanent_destroyed():
    state = make_state()
    mine = place(state, 0, "Wasteland")
    theirs = place(state, 1, "Underground Sea")
    rock = place(state, 1, "Mox Pearl")
    ttd = state.new_object(printing("Terastodon"), owner_id=0, zone=Zone.HAND)
    script(state, 0, "target", ("permanent", mine.id), ("permanent", theirs.id),
           ("permanent", rock.id))
    put_into_battlefield(state, ttd, 0)
    resolve_all(state)
    elephants = [o for o in state.battlefield if o.printing.name == "Elephant"]
    assert sorted(o.controller_id for o in elephants) == [0, 1, 1]
    assert all((o.printing.power, o.printing.toughness) == (3, 3) for o in elephants)


def test_terastodon_no_elephant_for_indestructible():
    state = make_state()
    land = place(state, 1, "Underground Sea")
    state.add_continuous_effect(
        source_id=-1, layer=6, kind="grant_keyword", target_id=land.id,
        params=("indestructible",),
    )
    ttd = state.new_object(printing("Terastodon"), owner_id=0, zone=Zone.HAND)
    script(state, 0, "target", ("permanent", land.id), None)
    put_into_battlefield(state, ttd, 0)
    resolve_all(state)
    assert land in state.battlefield
    assert not [o for o in state.battlefield if o.printing.name == "Elephant"]


def test_aangs_iceberg_exiles_until_it_leaves():
    state = make_state()
    rock = place(state, 1, "Mox Pearl")
    berg = state.new_object(printing("Aang's Iceberg"), owner_id=0, zone=Zone.HAND)
    script(state, 0, "target", ("permanent", rock.id))
    put_into_battlefield(state, berg, 0)
    resolve_all(state)
    assert rock in state.players[1].exile
    move_off_battlefield(state, berg)
    assert any(o.printing.name == "Mox Pearl" for o in state.battlefield)


def test_temporary_lockdown_exiles_cheap_nonland_permanents():
    state = make_state()
    cheap = place(state, 1, "Llanowar Elves")
    mine = place(state, 0, "Mox Pearl")
    big = place(state, 1, vanilla(3, 3, cost="{2}{G}"))
    land = place(state, 1, "Forest")
    lock = state.new_object(printing("Temporary Lockdown"), owner_id=0, zone=Zone.HAND)
    put_into_battlefield(state, lock, 0)
    resolve_all(state)
    assert cheap in state.players[1].exile and mine in state.players[0].exile
    assert big in state.battlefield and land in state.battlefield
    move_off_battlefield(state, lock)
    names = {o.printing.name for o in state.battlefield}
    assert {"Llanowar Elves", "Mox Pearl"} <= names


def test_temporary_lockdown_gone_before_resolution_exiles_nothing():
    from mtg_bot.effects.generic.roto_board import ExileEachUntilSourceLeaves

    state = make_state()
    cheap = place(state, 1, "Llanowar Elves")
    lock = place(state, 0, "Temporary Lockdown")
    eff = lock.printing.triggered_abilities[0].effect
    assert isinstance(eff, ExileEachUntilSourceLeaves)
    move_off_battlefield(state, lock)
    state.resolving_source = lock
    eff.resolve(state, 0)
    state.resolving_source = None
    assert cheap in state.battlefield
    assert "until this permanent leaves" in eff.describe()


def test_turnabout_taps_or_untaps_the_chosen_type():
    state = make_state()
    lands(state, 0, "Island", 4)
    their_lands = lands(state, 1, "Forest", 2)
    bear = place(state, 1, vanilla(2, 2))
    turn = place(state, 0, "Turnabout", Zone.HAND)
    script(state, 0, "target", ("player", 1))
    script(state, 0, "mode", 2, 0)       # land, tap
    cast(state, 0, turn)
    assert all(l.tapped for l in their_lands) and not bear.tapped
    for land in state.battlefield:
        if land.controller_id == 0:
            land.tapped = False
    my_lands = [o for o in state.battlefield if o.controller_id == 0]
    turn2 = place(state, 0, "Turnabout", Zone.HAND)
    script(state, 0, "target", ("player", 0))
    script(state, 0, "mode", 2, 1)       # land, untap
    cast(state, 0, turn2)
    assert not any(l.tapped for l in my_lands)
    eff = TapOrUntapAllOfChosenType()
    assert eff.requires_target() and eff.target_count_range() == (1, 1)
    assert "choose artifact" in eff.describe()


def test_turnabout_creatures():
    state = make_state()
    bears = [place(state, 1, vanilla(2, 2, name=f"B{i}")) for i in range(2)]
    eff = TapOrUntapAllOfChosenType()
    script(state, 0, "mode", 1, 0)
    eff.resolve(state, 0, (("player", 1),))
    assert all(b.tapped for b in bears)
    eff.resolve(state, 0, ())
    state_based_actions(state)
