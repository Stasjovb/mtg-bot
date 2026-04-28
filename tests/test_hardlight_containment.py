"""Tests for Hardlight Containment: Aura that enchants artifacts."""

from mtg_bot.actions import (
    CastSpell,
    apply_action,
    resolve_top_of_stack,
)
from mtg_bot.agents import RandomAgent
from mtg_bot.cards import BASIC_LANDS, SYNTHETIC_CREATURES, TOKEN_PRINTINGS
from mtg_bot.effects import ExileTargetCreatureUntilSourceLeaves
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.turn import destroy

from mtg_bot.cards.source import get_active_source

_PRINTINGS = get_active_source().get_printings()


def _new_state_with_plains(n: int = 2):
    state = GameState()
    p0 = Player(id=0, agent=RandomAgent())
    p1 = Player(id=1, agent=RandomAgent())
    state.players.append(p0)
    state.players.append(p1)
    for _ in range(n):
        pl = state.new_object(BASIC_LANDS["Plains"], 0, Zone.BATTLEFIELD)
        state.battlefield.append(pl)
    return state


# -----------------------
# ExileTargetCreatureUntilSourceLeaves.opponents_only
# -----------------------


def test_exile_opponents_only_restricts_legal_targets_to_opponents():
    state = _new_state_with_plains()
    mine = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(mine)
    theirs = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(theirs)
    effect = ExileTargetCreatureUntilSourceLeaves(opponents_only=True)
    legal = effect.legal_targets(state, controller_id=0)
    ids = {t[1] for t in legal}
    assert theirs.id in ids
    assert mine.id not in ids


def test_exile_without_opponents_only_includes_self_creatures():
    state = _new_state_with_plains()
    mine = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(mine)
    effect = ExileTargetCreatureUntilSourceLeaves(opponents_only=False)
    legal = effect.legal_targets(state, controller_id=0)
    assert ("creature", mine.id) in legal


# -----------------------
# Hardlight Containment full cast flow
# -----------------------


def _drain_stack(state):
    while state.stack:
        resolve_top_of_stack(state)


def test_hardlight_containment_resolves_with_artifact_target():
    state = _new_state_with_plains(n=1)
    p0 = state.players[0]
    # Give P0 an artifact to enchant.
    robot = state.new_object(TOKEN_PRINTINGS["Robot"], 0, Zone.BATTLEFIELD)
    state.battlefield.append(robot)
    # Opponent has a creature to exile.
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear)
    aura_card = state.new_object(
        _PRINTINGS["Hardlight Containment"], 0, Zone.HAND,
    )
    p0.hand.append(aura_card)
    apply_action(state, 0, CastSpell(aura_card.id))
    _drain_stack(state)
    # Aura is on the battlefield attached to the robot.
    assert aura_card in state.battlefield
    assert aura_card.attached_to == robot.id
    # Opponent's bear is exiled, tagged with the aura's id.
    assert bear not in state.battlefield
    assert bear.zone == Zone.EXILE
    assert bear.exiled_by_source == aura_card.id


def test_hardlight_containment_releases_exiled_when_leaves():
    """When the Aura leaves the battlefield, the exiled creature returns."""
    state = _new_state_with_plains(n=1)
    p0 = state.players[0]
    p1 = state.players[1]
    robot = state.new_object(TOKEN_PRINTINGS["Robot"], 0, Zone.BATTLEFIELD)
    state.battlefield.append(robot)
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear)
    aura_card = state.new_object(
        _PRINTINGS["Hardlight Containment"], 0, Zone.HAND,
    )
    p0.hand.append(aura_card)
    apply_action(state, 0, CastSpell(aura_card.id))
    _drain_stack(state)
    assert bear not in state.battlefield

    # Destroy the enchanted robot — aura falls off and goes to graveyard.
    destroy(state, robot)
    # Bear should return (release_exiled_until_leaves).
    assert bear in state.battlefield
    assert bear.controller_id == 1
    # Aura is in graveyard.
    assert aura_card in p0.graveyard


def test_hardlight_containment_fizzles_without_artifact_target():
    """If no artifact exists at cast time, the Aura can't find a
    target and doesn't go on the stack (or fizzles at resolution)."""
    state = _new_state_with_plains(n=1)
    # No artifact to enchant.
    p0 = state.players[0]
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear)
    aura_card = state.new_object(
        _PRINTINGS["Hardlight Containment"], 0, Zone.HAND,
    )
    p0.hand.append(aura_card)
    apply_action(state, 0, CastSpell(aura_card.id))
    _drain_stack(state)
    # Aura fizzles to graveyard because no legal enchant target.
    assert aura_card in p0.graveyard
    # The opponent's bear wasn't exiled (ETB never fired).
    assert bear in state.battlefield


def test_hardlight_containment_aura_enchant_type_wired():
    p = _PRINTINGS["Hardlight Containment"]
    assert p.is_aura
    assert p.aura_enchant_type == "artifact"


# -----------------------
# "Enchanted permanent has ward {1}" rider
# -----------------------


def test_hardlight_containment_printing_grants_ward_one():
    """The printing carries the granted-ward field with the correct cost."""
    p = _PRINTINGS["Hardlight Containment"]
    assert p.attached_grants_ward_str == "{1}"
    assert p.attached_grants_ward_cost is not None
    assert p.attached_grants_ward_cost.generic == 1


def test_effective_ward_cost_grants_ward_to_enchanted_artifact():
    """While the Aura is attached, the artifact has effective ward {1}
    even though its printing has no printed ward."""
    from mtg_bot.game import effective_ward_cost

    state = _new_state_with_plains(n=1)
    robot = state.new_object(TOKEN_PRINTINGS["Robot"], 0, Zone.BATTLEFIELD)
    state.battlefield.append(robot)
    # Baseline: bare robot has no ward.
    cost, label = effective_ward_cost(state, robot)
    assert cost is None
    assert label == ""
    # Attach the Aura.
    aura = state.new_object(
        _PRINTINGS["Hardlight Containment"], 0, Zone.BATTLEFIELD,
    )
    aura.attached_to = robot.id
    state.battlefield.append(aura)
    cost, label = effective_ward_cost(state, robot)
    assert cost is not None
    assert cost.generic == 1
    assert label == "{1}"


def test_apply_ward_check_counters_opponent_spell_when_unpaid():
    """Opponent targets the enchanted artifact with no mana — ward {1}
    can't be paid and the check returns True (spell countered)."""
    from mtg_bot.actions import _apply_ward_check

    state = _new_state_with_plains(n=0)
    robot = state.new_object(TOKEN_PRINTINGS["Robot"], 0, Zone.BATTLEFIELD)
    state.battlefield.append(robot)
    aura = state.new_object(
        _PRINTINGS["Hardlight Containment"], 0, Zone.BATTLEFIELD,
    )
    aura.attached_to = robot.id
    state.battlefield.append(aura)
    # P1 has no untapped lands → can't pay ward {1}.
    countered = _apply_ward_check(
        state, caster_id=1, targets=(("permanent", robot.id),),
    )
    assert countered is True


def test_apply_ward_check_autopays_when_opponent_has_mana():
    """Opponent has 1 untapped Plains — ward {1} auto-pays, spell goes
    through (returns False)."""
    from mtg_bot.actions import _apply_ward_check

    state = _new_state_with_plains(n=0)
    robot = state.new_object(TOKEN_PRINTINGS["Robot"], 0, Zone.BATTLEFIELD)
    state.battlefield.append(robot)
    aura = state.new_object(
        _PRINTINGS["Hardlight Containment"], 0, Zone.BATTLEFIELD,
    )
    aura.attached_to = robot.id
    state.battlefield.append(aura)
    # Give the opponent (P1) one untapped land to pay ward.
    plains = state.new_object(BASIC_LANDS["Plains"], 1, Zone.BATTLEFIELD)
    state.battlefield.append(plains)
    countered = _apply_ward_check(
        state, caster_id=1, targets=(("permanent", robot.id),),
    )
    assert countered is False
    assert plains.tapped


def test_ward_grant_disappears_when_aura_leaves():
    """Once the Aura is gone (graveyard / unattached), the artifact no
    longer has the granted ward."""
    from mtg_bot.actions import _apply_ward_check
    from mtg_bot.game import effective_ward_cost

    state = _new_state_with_plains(n=1)
    p0 = state.players[0]
    robot = state.new_object(TOKEN_PRINTINGS["Robot"], 0, Zone.BATTLEFIELD)
    state.battlefield.append(robot)
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear)
    aura_card = state.new_object(
        _PRINTINGS["Hardlight Containment"], 0, Zone.HAND,
    )
    p0.hand.append(aura_card)
    apply_action(state, 0, CastSpell(aura_card.id))
    _drain_stack(state)
    # Aura is attached → robot has ward {1}.
    cost, _ = effective_ward_cost(state, robot)
    assert cost is not None and cost.generic == 1
    # Destroy the robot — aura falls off into graveyard.
    destroy(state, robot)
    assert aura_card in p0.graveyard
    # Probe a different artifact: stand up another robot with no aura
    # and confirm it has no ward.
    robot2 = state.new_object(TOKEN_PRINTINGS["Robot"], 0, Zone.BATTLEFIELD)
    state.battlefield.append(robot2)
    cost2, label2 = effective_ward_cost(state, robot2)
    assert cost2 is None
    assert label2 == ""
    # Targeting the new (unenchanted) robot triggers no ward — spell
    # goes through with no mana required.
    countered = _apply_ward_check(
        state, caster_id=1, targets=(("permanent", robot2.id),),
    )
    assert countered is False


def test_ward_grant_does_not_fire_for_owner_spells():
    """Wards only fire on opponents' spells. The Aura's controller can
    target their own enchanted artifact freely."""
    from mtg_bot.actions import _apply_ward_check

    state = _new_state_with_plains(n=0)
    robot = state.new_object(TOKEN_PRINTINGS["Robot"], 0, Zone.BATTLEFIELD)
    state.battlefield.append(robot)
    aura = state.new_object(
        _PRINTINGS["Hardlight Containment"], 0, Zone.BATTLEFIELD,
    )
    aura.attached_to = robot.id
    state.battlefield.append(aura)
    # P0 (owner of both) targets their own permanent → no ward.
    countered = _apply_ward_check(
        state, caster_id=0, targets=(("permanent", robot.id),),
    )
    assert countered is False


def test_ward_grant_stacks_with_printed_ward():
    """If a permanent already has printed ward and an Aura grants more
    ward on top, both costs are required at cast time."""
    from mtg_bot.actions import _apply_ward_check
    from mtg_bot.game import effective_ward_cost

    state = _new_state_with_plains(n=0)
    # Mouth of the Storm has printed ward {2}.
    mouth = state.new_object(
        _PRINTINGS["Mouth of the Storm"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(mouth)
    # Attach Hardlight Containment (granted ward {1}) directly. Note:
    # in real play the Aura only enchants artifacts; here we're just
    # exercising the ward-stacking helper, so we attach it manually.
    aura = state.new_object(
        _PRINTINGS["Hardlight Containment"], 0, Zone.BATTLEFIELD,
    )
    aura.attached_to = mouth.id
    state.battlefield.append(aura)
    cost, label = effective_ward_cost(state, mouth)
    assert cost is not None
    # {2} printed + {1} granted → {3} generic.
    assert cost.generic == 3
    assert "{2}" in label and "{1}" in label
    # Opponent with no mana → countered.
    countered = _apply_ward_check(
        state, caster_id=1, targets=(("creature", mouth.id),),
    )
    assert countered is True


def test_apply_ward_check_skips_player_targets():
    """Sanity: targeting a player never trips the ward-check loop."""
    from mtg_bot.actions import _apply_ward_check

    state = _new_state_with_plains(n=0)
    countered = _apply_ward_check(
        state, caster_id=1, targets=(("player", 0),),
    )
    assert countered is False


def test_effective_ward_cost_skips_attached_non_ward_auras():
    """An Aura attached to the permanent that doesn't grant ward must
    not contribute anything to the effective ward cost."""
    from mtg_bot.game import effective_ward_cost

    state = _new_state_with_plains(n=0)
    creature = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(creature)
    # Tractor Beam is an Aura with NO ward grant — verify it doesn't
    # add anything when attached to a creature.
    tb = state.new_object(
        _PRINTINGS["Tractor Beam"], 0, Zone.BATTLEFIELD,
    )
    tb.attached_to = creature.id
    state.battlefield.append(tb)
    cost, label = effective_ward_cost(state, creature)
    assert cost is None
    assert label == ""


def test_effective_ward_cost_sums_colored_when_multiple():
    """Stacking ward instances combines colored pips too — exercise the
    multi-part summation branch with a synthetic colored ward grant."""
    from mtg_bot.cards.base import (
        CardPrinting, ManaCost, parse_mana_cost,
    )
    from mtg_bot.game import effective_ward_cost

    state = _new_state_with_plains(n=0)
    # Creature with printed ward {W}.
    base_creature_printing = CardPrinting(
        name="ColoredWardBeast",
        mana_cost_str="{2}{G}",
        mana_cost=parse_mana_cost("{2}{G}"),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=2,
        toughness=2,
        ward_cost=parse_mana_cost("{W}"),
        ward_cost_str="{W}",
    )
    creature = state.new_object(base_creature_printing, 0, Zone.BATTLEFIELD)
    state.battlefield.append(creature)
    # Synthetic Aura with attached_grants_ward_cost = {U}.
    aura_printing = CardPrinting(
        name="ColoredWardAura",
        mana_cost_str="{U}",
        mana_cost=parse_mana_cost("{U}"),
        type_line="Enchantment — Aura",
        supertypes=(),
        card_types=("Enchantment",),
        subtypes=("Aura",),
        attached_grants_ward_cost=parse_mana_cost("{U}"),
        attached_grants_ward_str="{U}",
    )
    aura = state.new_object(aura_printing, 0, Zone.BATTLEFIELD)
    aura.attached_to = creature.id
    state.battlefield.append(aura)
    cost, label = effective_ward_cost(state, creature)
    assert cost is not None
    assert isinstance(cost, ManaCost)
    # Colored pips for {W} + {U} aggregated.
    color_dict = dict(cost.colored)
    assert color_dict.get("W", 0) == 1
    assert color_dict.get("U", 0) == 1
    assert "{W}" in label and "{U}" in label
