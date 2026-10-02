"""Roto P6 damage prevention and redirection
(``effects/generic/roto_damage.py``): Maze of Ith, Cephalid Illusionist,
Nomads en-Kor and Black Panther -- the parse and the in-game behavior on
both damage paths (noncombat ``_apply_damage`` and combat damage)."""

from __future__ import annotations

from mtg_bot.actions import (
    ActivateAbility,
    DeclareAttackers,
    DeclareBlockers,
    apply_action,
    resolve_top_of_stack,
)
from mtg_bot.cards.base import make_creature
from mtg_bot.cards.parser.roto_keywords import (
    is_self_reference,
    parse_p6_effect,
    parse_replacement_static_line,
    target_noun_filter,
)
from mtg_bot.combat import resolve_combat_damage
from mtg_bot.effects.base import _apply_damage
from mtg_bot.effects.generic.roto_damage import (
    PREVENT_COMBAT_TO_AND_BY,
    REDIRECT_NEXT_DAMAGE,
    PreventAllDamageToSelf,
    PreventCombatDamageToAndByTarget,
    RedirectNextDamageToSourceToTarget,
    prevents_all_damage_to,
    route_combat_damage_events,
)
from mtg_bot.effects.object_predicates import ControlledByYou, IsAttacking, IsCreature
from mtg_bot.effects.predicates import Event, IsSelf
from mtg_bot.effects.targets import TargetSpec
from mtg_bot.legal import legal_actions
from mtg_bot.turn import Step
from tests._roto_helpers import agent, arena, printing, put, to_library

MAZE = "Maze of Ith"
CEPHALID = "Cephalid Illusionist"
NOMADS = "Nomads en-Kor"
TCHALLA = "King T'Challa // Black Panther, Hope Enduring"

BEAR = make_creature("Test Bear", "{1}{G}", 2, 2)
OGRE = make_creature("Test Ogre", "{2}{R}", 3, 3)


def _activations(state, obj, player_id):
    return [
        a for a in legal_actions(state, player_id)
        if isinstance(a, ActivateAbility) and a.source_id == obj.id
    ]


def _attack(state, attacker, attacking_player=1):
    state.step = Step.DECLARE_ATTACKERS
    apply_action(
        state, attacking_player,
        DeclareAttackers(attacker_ids=frozenset({attacker.id})),
    )
    state.step = Step.DECLARE_BLOCKERS


# ------------------------------------------------------------------ parse


def test_maze_of_ith_parse():
    p = printing(MAZE)
    assert p.is_land and p.produces == frozenset()
    (ability,) = p.activated_abilities
    assert ability.cost.tap_self and not ability.is_mana_ability
    assert ability.effect == PreventCombatDamageToAndByTarget(
        targets=(TargetSpec(IsCreature() & IsAttacking()),), untap=True,
    )
    assert ability.effect.describe().startswith("untap ")


def test_cephalid_illusionist_parse():
    p = printing(CEPHALID)
    (trig,) = p.triggered_abilities
    assert trig.event == Event.BECOMES_TARGET
    assert trig.predicate == IsSelf(subject="target")
    assert trig.effect.__class__.__name__ == "SelfMill" and trig.effect.amount == 3
    (ability,) = p.activated_abilities
    assert ability.cost.tap_self and ability.cost.mana_str == "{2}{U}"
    assert ability.effect == PreventCombatDamageToAndByTarget(
        targets=(TargetSpec(IsCreature() & ControlledByYou()),),
    )


def test_nomads_en_kor_parse():
    (ability,) = printing(NOMADS).activated_abilities
    assert ability.cost.mana_str == "{0}"
    assert ability.effect == RedirectNextDamageToSourceToTarget(
        amount=1, targets=(TargetSpec(IsCreature() & ControlledByYou()),),
    )
    assert "dealt to target" in ability.effect.describe()


def test_black_panther_back_face_prevents_damage_to_itself():
    p = printing(TCHALLA)
    back = p.transform_back_face
    assert back.replacement_statics == (PreventAllDamageToSelf(),)
    assert {"flash", "double strike"} <= back.keywords
    assert p.replacement_statics == ()
    assert "prevent all damage" in PreventAllDamageToSelf().describe()


def test_damage_phrase_grammar():
    assert parse_p6_effect(
        "the next 2 damage that would be dealt to this creature this turn "
        "is dealt to target creature instead"
    ) == RedirectNextDamageToSourceToTarget(2, (TargetSpec(IsCreature()),))
    assert parse_p6_effect(
        "the next lots damage that would be dealt to this creature this "
        "turn is dealt to target creature instead"
    ) is None
    assert parse_p6_effect(
        "prevent all combat damage that would be dealt to and dealt by "
        "target goblin wizard this turn"
    ) is None
    assert target_noun_filter("attacking goblin") is None
    assert parse_replacement_static_line(
        "Prevent all damage that would be dealt to Someone Else.", "X",
    ) is None
    assert is_self_reference("Black Panther", "Black Panther, Hope Enduring")


# ----------------------------------------------------------- Maze of Ith


def _maze_arena():
    s = arena(active=1)  # P1 attacks P0, who controls the Maze
    maze = put(s, printing(MAZE), 0)
    attacker = put(s, OGRE, 1)
    return s, maze, attacker


def test_maze_targets_only_attacking_creatures():
    s, maze, attacker = _maze_arena()
    s.step = Step.PRECOMBAT_MAIN
    s.priority_player_idx = 0
    effect = maze.printing.activated_abilities[0].effect
    assert effect.legal_targets(s, 0) == []
    _attack(s, attacker)
    assert effect.legal_targets(s, 0) == [("creature", attacker.id)]


def test_maze_untaps_and_prevents_combat_damage_to_and_by():
    s, maze, attacker = _maze_arena()
    blocker = put(s, BEAR, 0)
    _attack(s, attacker)
    assert attacker.tapped
    agent(s, 0).targets = [("creature", attacker.id)]
    s.priority_player_idx = 0
    apply_action(s, 0, ActivateAbility(source_id=maze.id, ability_index=0))
    assert maze.tapped
    resolve_top_of_stack(s)
    assert not attacker.tapped
    assert [ce.kind for ce in s.continuous_effects] == [PREVENT_COMBAT_TO_AND_BY]
    apply_action(
        s, 0, DeclareBlockers(assignments=((blocker.id, attacker.id),)),
    )
    s.step = Step.COMBAT_DAMAGE
    resolve_combat_damage(s, defending_player_id=0)
    assert attacker.damage == 0 and blocker.damage == 0
    # Noncombat damage isn't prevented.
    _apply_damage(s, ("creature", attacker.id), 1)
    assert attacker.damage == 1
    # "this turn": gone at cleanup.
    s.expire_continuous_effects("cleanup")
    assert s.continuous_effects == []


def test_unblocked_mazed_attacker_deals_no_damage_to_the_player():
    s, maze, attacker = _maze_arena()
    _attack(s, attacker)
    agent(s, 0).targets = [("creature", attacker.id)]
    apply_action(s, 0, ActivateAbility(source_id=maze.id, ability_index=0))
    resolve_top_of_stack(s)
    s.step = Step.COMBAT_DAMAGE
    resolve_combat_damage(s, defending_player_id=0)
    assert s.players[0].life == 20


def test_maze_effect_outlives_the_maze():
    s, maze, attacker = _maze_arena()
    _attack(s, attacker)
    agent(s, 0).targets = [("creature", attacker.id)]
    apply_action(s, 0, ActivateAbility(source_id=maze.id, ability_index=0))
    resolve_top_of_stack(s)
    s.battlefield.remove(maze)
    s.step = Step.COMBAT_DAMAGE
    resolve_combat_damage(s, defending_player_id=0)
    assert s.players[0].life == 20


def test_maze_fizzles_if_the_creature_stopped_attacking():
    s, maze, attacker = _maze_arena()
    _attack(s, attacker)
    agent(s, 0).targets = [("creature", attacker.id)]
    apply_action(s, 0, ActivateAbility(source_id=maze.id, ability_index=0))
    attacker.attacking = False
    resolve_top_of_stack(s)
    assert s.continuous_effects == []
    assert attacker.tapped


# ---------------------------------------------------- Cephalid Illusionist


def test_cephalid_mills_three_when_it_becomes_a_target_and_shields_itself():
    s = arena()
    ceph = put(s, printing(CEPHALID), 0)
    for _ in range(3):
        put(s, printing("Tolaria West"), 0).tapped = False
    for _ in range(5):
        to_library(s, BEAR, 0)
    agent(s, 0).targets = [("creature", ceph.id)]
    acts = _activations(s, ceph, 0)
    assert len(acts) == 1
    apply_action(s, 0, acts[0])
    # The becomes-target trigger went on the stack above the ability.
    assert len(s.stack) == 2
    resolve_top_of_stack(s)
    assert len(s.players[0].graveyard) == 3 and len(s.players[0].library) == 2
    resolve_top_of_stack(s)
    assert [ce.target_id for ce in s.continuous_effects] == [ceph.id]


# --------------------------------------------------------- Nomads en-Kor


def _nomads_arena():
    s = arena()
    nomads = put(s, printing(NOMADS), 0)
    other = put(s, OGRE, 0)
    return s, nomads, other


def _shield(s, nomads, recipient):
    agent(s, 0).targets = [("creature", recipient.id)]
    apply_action(s, 0, ActivateAbility(source_id=nomads.id, ability_index=0))
    resolve_top_of_stack(s)


def test_nomads_redirects_the_next_one_damage():
    s, nomads, other = _nomads_arena()
    _shield(s, nomads, other)
    assert [ce.kind for ce in s.continuous_effects] == [REDIRECT_NEXT_DAMAGE]
    _apply_damage(s, ("creature", nomads.id), 3)
    assert other.damage == 1 and nomads.damage == 2
    assert s.continuous_effects == []  # the shield is used up
    _apply_damage(s, ("creature", nomads.id), 1)
    assert nomads.damage == 3


def test_nomads_shields_stack():
    s, nomads, other = _nomads_arena()
    _shield(s, nomads, other)
    _shield(s, nomads, other)
    _apply_damage(s, ("creature", nomads.id), 1)
    assert other.damage == 1 and nomads.damage == 0
    assert len(s.continuous_effects) == 1
    _apply_damage(s, ("creature", nomads.id), 2)
    assert other.damage == 2 and nomads.damage == 1


def test_nomads_redirect_to_itself_changes_nothing():
    s, nomads, _ = _nomads_arena()
    _shield(s, nomads, nomads)
    _apply_damage(s, ("creature", nomads.id), 1)
    assert nomads.damage == 1 and s.continuous_effects == []


def test_nomads_recipient_gone_keeps_the_damage():
    s, nomads, other = _nomads_arena()
    _shield(s, nomads, other)
    s.battlefield.remove(other)
    _apply_damage(s, ("creature", nomads.id), 1)
    assert nomads.damage == 1


def test_nomads_redirects_combat_damage():
    s = arena(active=1)
    nomads = put(s, printing(NOMADS), 0)
    other = put(s, BEAR, 0)
    attacker = put(s, OGRE, 1)
    _shield(s, nomads, other)
    _attack(s, attacker)
    apply_action(s, 0, DeclareBlockers(assignments=((nomads.id, attacker.id),)))
    s.step = Step.COMBAT_DAMAGE
    resolve_combat_damage(s, defending_player_id=0)
    assert other.damage == 1 and nomads.damage == 2
    assert attacker.damage == 1  # Nomads' own damage is unaffected


def test_redirected_damage_meets_the_recipients_prevention():
    s, nomads, _ = _nomads_arena()
    panther = put(s, printing(TCHALLA).transform_back_face, 0)
    _shield(s, nomads, panther)
    _apply_damage(s, ("creature", nomads.id), 1)
    assert panther.damage == 0 and nomads.damage == 0


# ---------------------------------------------------------- Black Panther


def test_black_panther_prevents_all_damage_dealt_to_it():
    s = arena(active=1)
    panther = put(s, printing(TCHALLA).transform_back_face, 0)
    assert prevents_all_damage_to(panther)
    _apply_damage(s, ("creature", panther.id), 5)
    assert panther.damage == 0
    attacker = put(s, OGRE, 1)
    _attack(s, attacker)
    apply_action(s, 0, DeclareBlockers(assignments=((panther.id, attacker.id),)))
    s.step = Step.COMBAT_DAMAGE
    resolve_combat_damage(s, defending_player_id=0)
    assert panther.damage == 0
    # Its own first-strike damage is dealt: the 3/3 Ogre died.
    assert attacker not in s.battlefield


def test_combat_router_is_a_no_op_without_p6_effects():
    s = arena()
    events = [("player", 1, 2, 99, frozenset(), 0)]
    assert route_combat_damage_events(s, events) is events


# ------------------------------------------------------ Vizier of Remedies

VIZIER = "Vizier of Remedies"


def test_vizier_of_remedies_parse():
    from mtg_bot.effects.generic.roto_keywords import (
        FewerMinusOneCountersOnYourCreatures,
    )

    p = printing(VIZIER)
    assert p.replacement_statics == (FewerMinusOneCountersOnYourCreatures(1),)
    assert "minus 1" in p.replacement_statics[0].describe()
    assert parse_replacement_static_line(
        "If one or more -1/-1 counters would be put on a creature you "
        "control, that many -1/-1 counters minus lots are put on it instead.",
        "X",
    ) is None


def test_vizier_takes_one_off_each_minus_one_placement():
    from mtg_bot.game import add_counters, add_minus_one_counters

    s = arena()
    vizier = put(s, printing(VIZIER), 0)
    mine = put(s, OGRE, 0)
    theirs = put(s, OGRE, 1)
    assert add_counters(s, mine, "-1/-1", 2) == 1
    assert mine.minus_one_counters == 1
    assert add_minus_one_counters(s, mine, 1) == 0
    assert add_counters(s, vizier, "-1/-1", 1) == 0  # itself too
    assert add_counters(s, theirs, "-1/-1", 2) == 2  # not an opponent's
    # Two Viziers: two off.
    put(s, printing(VIZIER), 0)
    assert add_counters(s, mine, "-1/-1", 3) == 1


def test_vizier_ignores_noncreatures_and_other_counters():
    from mtg_bot.game import add_counters

    s = arena()
    put(s, printing(VIZIER), 0)
    rock = put(s, printing("Serum Powder"), 0)
    assert add_counters(s, rock, "-1/-1", 1) == 1
    bear = put(s, BEAR, 0)
    assert add_counters(s, bear, "+1/+1", 1) == 1


def test_vizier_with_persist_returns_the_creature_counterless():
    from mtg_bot.actions import drain_stack
    from mtg_bot.turn import move_off_battlefield

    s = arena()
    put(s, printing(VIZIER), 0)
    finks = put(s, make_creature("Test Finks", "{3}", 3, 2, keywords={"persist"}), 0)
    move_off_battlefield(s, finks, destination="graveyard")
    drain_stack(s)
    assert finks in s.battlefield and finks.minus_one_counters == 0
    # ...so it persists again.
    move_off_battlefield(s, finks, destination="graveyard")
    drain_stack(s)
    assert finks in s.battlefield
