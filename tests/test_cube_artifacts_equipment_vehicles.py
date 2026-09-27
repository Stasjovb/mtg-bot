"""PowerLSV cube Equipment (Skullclamp, Skateboard, Nettlecyst, Glimmer
Lens) and Vehicles (Smuggler's Copter, Esika's Chariot, Reckoner
Bankbuster, The Fantasticar) — plus the crew mechanic, living weapon /
For Mirrodin!, scaling equipment bonus, former-host dies trigger and the
generic "you may X. If you do, Y" fallback."""

from __future__ import annotations

import pytest

from mtg_bot import apply, legal_moves
from mtg_bot.actions import (
    ActivateAbility,
    CastSpell,
    drain_stack,
    put_into_battlefield,
    resolve_top_of_stack,
)
from mtg_bot.cards import BASIC_LANDS, make_creature
from mtg_bot.cards.base import make_artifact, make_instant
from mtg_bot.cards.parser.effects import _parse_effect
from mtg_bot.cards.parser.equipment_builder import _build_equipment_printing
from mtg_bot.cards.parser.printing_keywords import _parse_crew_line
from mtg_bot.cards.tokens import TOKEN_PRINTINGS
from mtg_bot.combat import declare_attackers, declare_blockers, eligible_attackers
from mtg_bot.effects.combinators import IfYouDo, MayDo
from mtg_bot.effects.generic import (
    CreateTokenAndAttachSelf,
    CreateTokenCopyOfTargetTokenYouControl,
    DiscardSelf,
    DrawCards,
    GainLife,
    IfSourceHasNoCounters,
    SacrificeSelf,
)
from mtg_bot.effects.predicates import Event, IsFormerHost
from mtg_bot.game import (
    Zone,
    counter_count,
    effective_power,
    effective_toughness,
    is_creature_now,
)
from mtg_bot.turn import Step, run_cleanup_step, state_based_actions

from tests._cube_artifact_helpers import (
    agent,
    arena,
    build_ok,
    put,
    to_hand,
    to_library,
)


def _activate(state, obj, idx, pid=0):
    apply(state, ActivateAbility(source_id=obj.id, ability_index=idx), pid)


def _can_activate(state, obj, idx, pid=0):
    return ActivateAbility(source_id=obj.id, ability_index=idx) in legal_moves(
        state, pid
    )


def _enter(state, printing, controller=0):
    obj = state.new_object(printing, owner_id=controller, zone=Zone.STACK)
    put_into_battlefield(state, obj, controller)
    return obj


def _creature(name="Bear", p=2, t=2, cost="{1}{G}"):
    return make_creature(name, cost, p, t)


def _equip(state, equipment, creature):
    equipment.attached_to = creature.id


# --- grammar --------------------------------------------------------------

def test_may_x_if_you_do_y_fallback():
    assert _parse_effect(
        "you may draw a card. If you do, discard a card"
    ) == IfYouDo(do_action=MayDo(inner=DrawCards(1)), then_action=DiscardSelf(1))
    assert _parse_effect(
        "you may frobnicate. If you do, draw a card"
    ) is None
    assert _parse_effect(
        "you may destroy target creature. If you do, destroy target "
        "artifact"
    ) is None


def test_sacrifice_self_phrase_and_crew_line():
    assert _parse_effect("sacrifice this creature") == SacrificeSelf()
    assert _parse_crew_line("Crew 3") == 3
    assert _parse_crew_line("Crew X") is None


def test_skullclamp_shape():
    clamp = build_ok("Skullclamp")
    assert clamp.equipment_bonuses == (1, -1, frozenset())
    (trigger,) = clamp.triggered_abilities
    assert trigger.event == Event.DIES
    assert trigger.predicate == IsFormerHost()
    assert trigger.effect == DrawCards(amount=2)


def test_living_weapon_and_for_mirrodin_shapes():
    cyst = build_ok("Nettlecyst")
    (lw,) = cyst.triggered_abilities
    assert isinstance(lw.effect, CreateTokenAndAttachSelf)
    germ = lw.effect.token_printing
    assert (germ.name, germ.power, germ.toughness) == ("Phyrexian Germ", 0, 0)
    assert cyst.equipment_bonus_per_controlled == (
        ("Artifact", "Enchantment"), 1, 1,
    )
    lens = build_ok("Glimmer Lens")
    rebel = lens.triggered_abilities[0].effect.token_printing
    assert (rebel.name, rebel.power, rebel.toughness) == ("Rebel", 2, 2)


def test_equipment_builder_rejects_unmodeled_lines():
    base = {"name": "Test Gear", "mana_cost": "{1}",
            "type_line": "Artifact — Equipment"}
    assert _build_equipment_printing({
        **base, "oracle_text": "Equipped creature has haste and shroud.\nEquip {0}",
    }) is None
    assert _build_equipment_printing({
        **base, "oracle_text": "Frobnicate.\nEquip {1}",
    }) is None
    assert _build_equipment_printing({
        **base,
        "oracle_text": (
            "Equipped creature gets +1/+1 for each artifact you control.\n"
            "Equipped creature gets +1/+1 for each land you control.\n"
            "Equip {1}"
        ),
    }) is None
    # Static lines have no Equipment-side bucket.
    assert _build_equipment_printing({
        **base,
        "oracle_text": "Creatures you control get +1/+1.\nEquip {1}",
    }) is None
    ok = _build_equipment_printing({
        **base,
        "oracle_text": (
            "Equipped creature gets +1/+0 and has trample and haste.\n"
            "{1}: Draw a card.\nFlash\nEquip {1}"
        ),
    })
    assert ok.equipment_bonuses == (1, 0, frozenset({"trample", "haste"}))
    assert "flash" in ok.keywords


def test_vehicle_shapes():
    copter = build_ok("Smuggler's Copter")
    assert (copter.power, copter.toughness) == (3, 3)
    assert "flying" in copter.keywords
    assert copter.activated_abilities[-1].cost.crew == 1
    assert "Crew 1" in copter.activated_abilities[-1].cost.describe()
    chariot = build_ok("Esika's Chariot")
    assert chariot.activated_abilities[-1].cost.crew == 4
    assert chariot.triggered_abilities[1].effect == (
        CreateTokenCopyOfTargetTokenYouControl()
    )
    bank = build_ok("Reckoner Bankbuster")
    assert bank.enters_with_counters == (("charge", 3),)
    draw = bank.activated_abilities[0]
    assert isinstance(draw.effect.effects[1], IfSourceHasNoCounters)
    car = build_ok("The Fantasticar")
    assert not any(a.cost.crew for a in car.activated_abilities)
    assert len(car.triggered_abilities) == 2


def test_crew_on_non_vehicle_or_bad_pt_rejects():
    from mtg_bot.cards.parser.artifact_builder import _build_artifact_printing
    assert _build_artifact_printing({
        "name": "Not A Vehicle", "mana_cost": "{2}", "type_line": "Artifact",
        "oracle_text": "Crew 1",
    }) is None
    assert _build_artifact_printing({
        "name": "Star Vehicle", "mana_cost": "{2}",
        "type_line": "Artifact — Vehicle", "power": "*", "toughness": "3",
        "oracle_text": "Crew 1",
    }) is None


# --- Skullclamp -----------------------------------------------------------

def test_skullclamp_kills_x1_and_draws_two():
    state = arena()
    clamp = put(state, build_ok("Skullclamp"))
    for _ in range(3):
        to_library(state, BASIC_LANDS["Forest"])
    elf = put(state, _creature("Elf", 1, 1))
    _equip(state, clamp, elf)
    assert effective_toughness(state, elf) == 0
    assert effective_power(state, elf) == 2
    state_based_actions(state)
    assert elf.zone == Zone.GRAVEYARD
    assert clamp.attached_to is None and clamp.last_attached_to is None
    drain_stack(state)
    assert len(state.players[0].hand) == 2


def test_skullclamp_does_not_draw_for_unequipped_deaths():
    state = arena()
    put(state, build_ok("Skullclamp"))
    to_library(state, BASIC_LANDS["Forest"])
    elf = put(state, _creature("Elf", 1, 1))
    elf.damage = 5
    state_based_actions(state)
    drain_stack(state)
    assert state.players[0].hand == []


def test_former_host_predicate_needs_subject():
    assert not IsFormerHost().matches(None, {}, object())


# --- Skateboard / Nettlecyst / Glimmer Lens -------------------------------

def test_skateboard_taps_on_entry_and_grants_haste():
    state = arena()
    theirs = put(state, _creature("Wall", 0, 4), 1)
    agent(state).targets = [("creature", theirs.id)]
    board = _enter(state, build_ok("Skateboard"))
    drain_stack(state)
    assert theirs.tapped
    guy = put(state, _creature("Guy"), sick=True)
    _equip(state, board, guy)
    assert effective_power(state, guy) == 3
    assert guy in eligible_attackers(state, 0)


def test_nettlecyst_germ_scales_with_artifacts_and_enchantments():
    from mtg_bot.cards.base import make_enchantment
    state = arena()
    cyst = _enter(state, build_ok("Nettlecyst"))
    drain_stack(state)
    germ = next(o for o in state.battlefield if o.printing.name == "Phyrexian Germ")
    assert cyst.attached_to == germ.id
    assert effective_power(state, germ) == 1  # Nettlecyst itself
    put(state, make_artifact("Test Rock", "{1}"))
    put(state, make_enchantment("Test Aura-ish", "{W}"))
    put(state, make_artifact("Their Rock", "{1}"), 1)
    assert (effective_power(state, germ), effective_toughness(state, germ)) == (3, 3)
    state_based_actions(state)
    assert germ in state.battlefield


def test_glimmer_lens_for_mirrodin_and_attack_draw():
    state = arena()
    to_library(state, BASIC_LANDS["Plains"])
    lens = _enter(state, build_ok("Glimmer Lens"))
    drain_stack(state)
    rebel = next(o for o in state.battlefield if o.printing.name == "Rebel")
    assert lens.attached_to == rebel.id
    rebel.summoning_sick = False
    other = put(state, _creature("Other"))
    state.step = Step.DECLARE_ATTACKERS
    declare_attackers(state, [rebel.id])
    drain_stack(state)
    assert state.players[0].hand == []  # alone: no trigger
    for o in (rebel, other):
        o.attacking = False
        o.tapped = False
    declare_attackers(state, [rebel.id, other.id])
    drain_stack(state)
    assert len(state.players[0].hand) == 1


# --- crew / Vehicles ------------------------------------------------------

def test_crew_makes_vehicle_a_creature_until_end_of_turn():
    state = arena()
    copter = put(state, build_ok("Smuggler's Copter"))
    assert not is_creature_now(copter)
    assert not _can_activate(state, copter, 0)  # no crew
    pilot = put(state, _creature("Pilot Guy", 1, 1), sick=True)
    assert _can_activate(state, copter, 0)
    _activate(state, copter, 0)
    assert pilot.tapped  # summoning-sick creatures can crew
    resolve_top_of_stack(state)
    assert is_creature_now(copter)
    assert effective_power(state, copter) == 3
    assert copter in eligible_attackers(state, 0)
    run_cleanup_step(state)
    assert not is_creature_now(copter)


def test_vehicle_that_entered_this_turn_is_summoning_sick():
    state = arena()
    copter = _enter(state, build_ok("Smuggler's Copter"))
    put(state, _creature("Pilot Guy", 1, 1))
    _activate(state, copter, 0)
    resolve_top_of_stack(state)
    assert is_creature_now(copter)
    assert copter not in eligible_attackers(state, 0)


def test_crew_picks_until_power_reached_and_excludes_vehicle():
    state = arena()
    chariot = put(state, build_ok("Esika's Chariot"))
    a = put(state, _creature("A", 2, 2))
    b = put(state, _creature("B", 1, 1))
    assert not _can_activate(state, chariot, 0)  # 3 < 4
    c = put(state, _creature("C", 3, 3))
    agent(state).choose_permanent_to_tap = lambda s, p, ids: ids[-1]
    _activate(state, chariot, 0)
    # picks C (3) then B (1): total 4
    assert c.tapped and b.tapped and not a.tapped


def test_pilot_token_crews_with_bonus():
    state = arena()
    bank = _enter(state, build_ok("Reckoner Bankbuster"))
    assert counter_count(bank, "charge") == 3
    pilot = TOKEN_PRINTINGS.get("Pilot")
    assert pilot is None  # synthesized, not registered
    for _ in range(2):
        put(state, BASIC_LANDS["Swamp"])
    for _ in range(3):
        to_library(state, BASIC_LANDS["Swamp"])
    bank.named_counters = ()
    bank.charge_counters = 1
    _activate(state, bank, 0)
    resolve_top_of_stack(state)
    assert len(state.players[0].hand) == 1
    names = sorted(o.printing.name for o in state.battlefield if o.printing.is_token)
    assert names == ["Pilot", "Treasure"]
    pilot_obj = next(o for o in state.battlefield if o.printing.name == "Pilot")
    assert pilot_obj.printing.crew_power_bonus == 2
    bank.tapped = False
    # Pilot (1 power + 2) crews Crew 3 alone.
    assert _can_activate(state, bank, 1)
    _activate(state, bank, 1)
    assert pilot_obj.tapped


def test_bankbuster_draw_without_emptying_makes_no_tokens():
    state = arena()
    bank = _enter(state, build_ok("Reckoner Bankbuster"))
    for _ in range(2):
        put(state, BASIC_LANDS["Swamp"])
    to_library(state, BASIC_LANDS["Swamp"])
    _activate(state, bank, 0)
    resolve_top_of_stack(state)
    assert counter_count(bank, "charge") == 2
    assert not any(o.printing.is_token for o in state.battlefield)


def test_if_source_has_no_counters_edge_cases():
    state = arena()
    eff = IfSourceHasNoCounters(kind="charge", inner=GainLife(amount=1))
    eff.resolve(state, 0)  # no source -> condition holds
    assert state.players[0].life == 21
    assert "charge" in eff.describe()
    assert eff.requires_target() is False
    assert eff.legal_targets(state, 0) == []


def test_smugglers_copter_loots_on_attack():
    state = arena()
    copter = put(state, build_ok("Smuggler's Copter"))
    put(state, _creature("Pilot Guy", 1, 1))
    card = to_library(state, BASIC_LANDS["Island"])
    keep = to_hand(state, _creature("Keeper"))
    _activate(state, copter, 0)
    resolve_top_of_stack(state)
    agent(state).discards = [card.id]
    declare_attackers(state, [copter.id])
    drain_stack(state)
    assert keep in state.players[0].hand
    assert card.zone == Zone.GRAVEYARD


def test_smugglers_copter_decline_loot():
    state = arena()
    copter = put(state, build_ok("Smuggler's Copter"))
    put(state, _creature("Pilot Guy", 1, 1))
    to_library(state, BASIC_LANDS["Island"])
    _activate(state, copter, 0)
    resolve_top_of_stack(state)
    agent(state).yes = False
    declare_attackers(state, [copter.id])
    drain_stack(state)
    assert state.players[0].hand == []


def test_smugglers_copter_blocks_trigger():
    state = arena(active=1)
    copter = put(state, build_ok("Smuggler's Copter"))
    put(state, _creature("Pilot Guy", 1, 1))
    to_library(state, BASIC_LANDS["Island"])
    state.priority_player_idx = 0
    _activate(state, copter, 0)
    resolve_top_of_stack(state)
    attacker = put(state, _creature("Attacker"), 1)
    declare_attackers(state, [attacker.id])
    declare_blockers(state, {copter.id: attacker.id})
    drain_stack(state)
    assert len(state.players[0].graveyard) == 1  # drew then discarded


def test_esikas_chariot_cats_and_token_copy():
    state = arena()
    chariot = _enter(state, build_ok("Esika's Chariot"))
    drain_stack(state)
    cats = [o for o in state.battlefield if o.printing.name == "Cat"]
    assert len(cats) == 2
    chariot.summoning_sick = False
    for c in cats:
        c.summoning_sick = False
    _activate(state, chariot, 0)
    resolve_top_of_stack(state)
    assert all(c.tapped for c in cats)
    declare_attackers(state, [chariot.id])
    drain_stack(state)
    assert len([o for o in state.battlefield if o.printing.name == "Cat"]) == 3


def test_token_copy_targets_only_your_tokens():
    state = arena()
    mine = put(state, TOKEN_PRINTINGS["Treasure"])
    put(state, TOKEN_PRINTINGS["Treasure"], 1)
    put(state, _creature("Nontoken"))
    eff = CreateTokenCopyOfTargetTokenYouControl()
    assert eff.legal_targets(state, 0) == [("permanent", mine.id)]
    eff.resolve(state, 0, (("permanent", mine.id),))
    assert len([o for o in state.battlefield if o.controller_id == 0
                and o.printing.name == "Treasure"]) == 2
    eff.resolve(state, 0, ())
    eff.resolve(state, 0, (("permanent", 999),))
    assert eff.describe()


def test_fantasticar_animates_and_fourth_spell_sacrifice():
    state = arena()
    car = put(state, build_ok("The Fantasticar"))
    spell = make_instant("Test Shock", "{0}", GainLife(amount=1))
    creature_spell = make_creature("Test Dude", "{0}", 1, 1)
    agent(state).yes = True
    cards = [to_hand(state, spell) for _ in range(4)]
    dude = to_hand(state, creature_spell)
    apply(state, CastSpell(card_id=dude.id), 0)
    drain_stack(state)
    assert not is_creature_now(car)  # creature spell doesn't animate it
    apply(state, CastSpell(card_id=cards[0].id), 0)
    drain_stack(state)
    assert is_creature_now(car)
    for c in cards[1:]:
        apply(state, CastSpell(card_id=c.id), 0)
        drain_stack(state)
    assert car.zone == Zone.GRAVEYARD
    constructs = [o for o in state.battlefield if o.printing.name == "Construct"]
    assert len(constructs) == 4
    assert constructs[0].printing.keywords == frozenset({"flying", "haste"})


def test_fantasticar_decline_keeps_it():
    state = arena()
    car = put(state, build_ok("The Fantasticar"))
    agent(state).yes = False
    spell = make_instant("Test Shock", "{0}", GainLife(amount=1))
    for _ in range(4):
        c = to_hand(state, spell)
        apply(state, CastSpell(card_id=c.id), 0)
        drain_stack(state)
    assert car in state.battlefield
    assert not is_creature_now(car)


def test_sacrifice_self_reports_success():
    state = arena()
    obj = put(state, make_artifact("Test Box", "{1}"))
    assert SacrificeSelf().resolve(state, 0) is False
    state.resolving_source = obj
    assert SacrificeSelf().resolve(state, 0) is True
    assert SacrificeSelf().resolve(state, 0) is False


# --- Kaldra Compleat ------------------------------------------------------

def test_kaldra_compleat_germ_and_granted_exile_trigger():
    from mtg_bot.cards.base import make_creature as mk
    from dataclasses import replace
    state = arena()
    kaldra = _enter(state, build_ok("Kaldra Compleat"))
    drain_stack(state)
    germ = next(o for o in state.battlefield if o.printing.name == "Phyrexian Germ")
    assert kaldra.attached_to == germ.id
    assert (effective_power(state, germ), effective_toughness(state, germ)) == (5, 5)
    from mtg_bot.game import effective_keywords
    assert {"first strike", "trample", "indestructible", "haste"} <= (
        effective_keywords(state, germ)
    )
    # An indestructible blocker survives the damage but is exiled by the
    # granted trigger.
    wall = put(state, replace(mk("Wall", "{3}", 0, 8), keywords=frozenset({"indestructible"})), 1)
    declare_attackers(state, [germ.id])
    declare_blockers(state, {wall.id: germ.id})
    from mtg_bot.combat import resolve_combat_damage
    resolve_combat_damage(state, defending_player_id=1)
    drain_stack(state)
    assert wall.zone == Zone.EXILE


def test_kaldra_trigger_needs_the_equipment_attached():
    from mtg_bot.cards.base import make_creature as mk
    from dataclasses import replace
    state = arena()
    kaldra = put(state, build_ok("Kaldra Compleat"))
    guy = put(state, mk("Guy", "{1}", 2, 2))
    wall = put(state, replace(mk("Wall", "{3}", 0, 8), keywords=frozenset({"indestructible"})), 1)
    declare_attackers(state, [guy.id])
    declare_blockers(state, {wall.id: guy.id})
    from mtg_bot.combat import resolve_combat_damage
    resolve_combat_damage(state, defending_player_id=1)
    drain_stack(state)
    assert wall in state.battlefield
    assert kaldra.attached_to is None


def test_exile_that_creature_edge_cases():
    from mtg_bot.effects.generic import ExileThatCreature
    state = arena()
    ExileThatCreature().resolve(state, 0, ())
    ExileThatCreature().resolve(state, 0, (("creature", 999),))
    assert ExileThatCreature().describe()


def test_granted_quoted_trigger_must_be_known():
    base = {"name": "Test Gear", "mana_cost": "{1}",
            "type_line": "Artifact — Equipment"}
    assert _build_equipment_printing({
        **base,
        "oracle_text": (
            'Equipped creature gets +1/+1 and has haste, and "Whenever this '
            'creature attacks, draw a card."\nEquip {1}'
        ),
    }) is None
    assert _build_equipment_printing({
        **base,
        "oracle_text": (
            'Equipped creature gets +1/+1 and has shmaste, and "Whenever '
            'this creature deals combat damage to a creature, exile that '
            'creature."\nEquip {1}'
        ),
    }) is None
