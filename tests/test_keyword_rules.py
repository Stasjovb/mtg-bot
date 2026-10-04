"""Hexproof / shroud / protection rules consumers (``mtg_bot.keyword_rules``)
plus the parser shapes that produce those keywords."""

from __future__ import annotations

import pytest

from mtg_bot import apply
from mtg_bot.actions import CastSpell, resolve_top_of_stack
from mtg_bot.agents import Agent
from mtg_bot.cards import BASIC_LANDS, make_creature
from mtg_bot.cards.base import make_aura, make_equipment, make_instant
from mtg_bot.cards.parser.effects import _parse_keyword_grant_body
from mtg_bot.cards.parser.keywords import _parse_keyword_line
from mtg_bot.combat import can_block
from mtg_bot.effects import DealDamageAnyTarget
from mtg_bot.effects.generic.destroy import DestroyTargetCreature
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.keyword_rules import (
    can_be_targeted_by,
    current_damage_source,
    filter_targetable,
    is_protected_from,
    protection_keyword,
    protection_qualities,
    source_has_quality,
    targets_all_illegal_on_resolution,
)
from mtg_bot.legal import legal_actions
from mtg_bot.turn import Step, state_based_actions

from tests._rules_helpers import _simulate_combat_step


class _RecordingAgent(Agent):
    """Picks the first offered target; records every offered pool."""

    def __init__(self):
        self.offered: list[list] = []

    def choose_target(self, state, player_id, legal_targets):
        self.offered.append(list(legal_targets))
        return legal_targets[0] if legal_targets else None

    def choose_mana_color(self, state, player_id, options):
        return options[0]


def _state(agent0=None, agent1=None) -> GameState:
    state = GameState()
    state.players.append(Player(id=0, agent=agent0 or _RecordingAgent()))
    state.players.append(Player(id=1, agent=agent1 or _RecordingAgent()))
    state.step = Step.PRECOMBAT_MAIN
    state.active_player_idx = 0
    state.priority_player_idx = 0
    return state


def _put(state, printing, controller, zone=Zone.BATTLEFIELD):
    obj = state.new_object(printing, controller, zone)
    obj.summoning_sick = False
    if zone == Zone.BATTLEFIELD:
        state.battlefield.append(obj)
    elif zone == Zone.HAND:
        state.players[controller].hand.append(obj)
    return obj


def _lands(state, controller, name, n):
    for _ in range(n):
        _put(state, BASIC_LANDS[name], controller)


def _grant(state, obj, kw):
    state.add_continuous_effect(
        source_id=obj.id, layer=6, kind="grant_keyword",
        target_id=obj.id, params=(kw,), expires_at="cleanup",
    )


BOLT = make_instant("Test Bolt", "{R}", DealDamageAnyTarget(amount=3))
MURDER = make_instant("Test Murder", "{B}", DestroyTargetCreature())


# ---------------------------------------------------------------- targeting


def test_hexproof_blocks_opponent_targeting_but_not_controller():
    state = _state()
    bear = _put(state, make_creature("Hexy", "{1}{G}", 2, 2, keywords={"hexproof"}), 1)
    assert not can_be_targeted_by(state, bear, None, controller_id=0)
    assert can_be_targeted_by(state, bear, None, controller_id=1)


def test_shroud_blocks_everyone():
    state = _state()
    bear = _put(state, make_creature("Shroudy", "{1}{G}", 2, 2, keywords={"shroud"}), 1)
    assert not can_be_targeted_by(state, bear, None, controller_id=0)
    assert not can_be_targeted_by(state, bear, None, controller_id=1)


def test_filter_targetable_passes_players_and_stack_entries():
    state = _state()
    bear = _put(state, make_creature("Shroudy", "{1}{G}", 2, 2, keywords={"shroud"}), 1)
    pool = [("creature", bear.id), ("player", bear.id), ("stack", bear.id)]
    assert filter_targetable(state, pool, None, 0) == [
        ("player", bear.id), ("stack", bear.id),
    ]


def test_opponent_cannot_cast_single_target_removal_at_only_hexproof_creature():
    state = _state()
    _lands(state, 0, "Swamp", 1)
    _put(state, make_creature("Hexy", "{1}{G}", 2, 2, keywords={"hexproof"}), 1)
    murder = _put(state, MURDER, 0, Zone.HAND)
    assert not any(
        isinstance(a, CastSpell) and a.card_id == murder.id
        for a in legal_actions(state, 0)
    )


def test_cast_offers_only_targetable_creatures():
    agent = _RecordingAgent()
    state = _state(agent0=agent)
    _lands(state, 0, "Swamp", 1)
    hexy = _put(state, make_creature("Hexy", "{1}{G}", 2, 2, keywords={"hexproof"}), 1)
    plain = _put(state, make_creature("Plain", "{1}{G}", 2, 2), 1)
    murder = _put(state, MURDER, 0, Zone.HAND)
    apply(state, CastSpell(murder.id), player_id=0)
    offered_ids = {t[1] for t in agent.offered[-1]}
    assert plain.id in offered_ids and hexy.id not in offered_ids


def test_protection_from_color_blocks_targeting_by_that_color_only():
    state = _state()
    knight = _put(
        state,
        make_creature("Pro-Black", "{W}{W}", 2, 2,
                      keywords={protection_keyword("black")}),
        1,
    )
    black_spell = _put(state, MURDER, 0, Zone.HAND)
    red_spell = _put(state, BOLT, 0, Zone.HAND)
    assert not can_be_targeted_by(state, knight, black_spell, 0)
    assert can_be_targeted_by(state, knight, red_spell, 0)


def test_spell_fizzles_when_target_gains_hexproof_in_response():
    state = _state()
    _lands(state, 0, "Mountain", 1)
    bear = _put(state, make_creature("Bear", "{1}{G}", 2, 2), 1)
    bolt = _put(state, BOLT, 0, Zone.HAND)
    apply(state, CastSpell(bolt.id), player_id=0)
    assert state.stack and state.stack[-1].targets == (("creature", bear.id),)
    _grant(state, bear, "hexproof")
    resolve_top_of_stack(state)
    assert bear.damage == 0
    assert bolt in state.players[0].graveyard
    assert any("fizzles" in line for line in state.log)


def test_targets_all_illegal_is_false_for_players_and_missing_targets():
    state = _state()
    assert not targets_all_illegal_on_resolution(state, (), None, 0)
    assert not targets_all_illegal_on_resolution(state, (("player", 1),), None, 0)
    assert not targets_all_illegal_on_resolution(state, (("creature", 999),), None, 0)


# ---------------------------------------------------------------- qualities


@pytest.mark.parametrize(
    "quality,cost,expected",
    [
        ("red", "{R}", True), ("red", "{U}", False),
        ("colorless", "{2}", True), ("colorless", "{R}", False),
        ("multicolored", "{R}{G}", True), ("multicolored", "{R}", False),
        ("monocolored", "{R}", True), ("monocolored", "{R}{G}", False),
        ("everything", "{2}", True),
        ("creatures", "{R}", True),
        ("artifacts", "{R}", False),
        ("the chosen player", "{R}", False),
    ],
)
def test_source_has_quality(quality, cost, expected):
    state = _state()
    src = _put(state, make_creature("Src", cost, 1, 1), 0)
    assert source_has_quality(state, src, quality) is expected


def test_protection_keyword_rejects_unknown_quality():
    with pytest.raises(ValueError):
        protection_keyword("the chosen ones")


def test_protection_qualities_fold_printing_color_field():
    state = _state()
    obj = _put(
        state,
        make_creature("Old Knight", "{W}", 2, 2, protection_from_color="B",
                      keywords={protection_keyword("creatures")}),
        0,
    )
    assert protection_qualities(state, obj) == frozenset({"black", "creatures"})
    assert not is_protected_from(state, obj, None)


def test_current_damage_source_prefers_ability_source():
    state = _state()
    a = _put(state, make_creature("A", "{R}", 1, 1), 0)
    b = _put(state, make_creature("B", "{R}", 1, 1), 0)
    assert current_damage_source(state) is None
    state.resolving_spell = b
    assert current_damage_source(state) is b
    state.resolving_source = a
    assert current_damage_source(state) is a


# ---------------------------------------------------------------- damage


def test_noncombat_damage_from_protected_color_is_prevented():
    state = _state()
    _lands(state, 0, "Mountain", 1)
    knight = _put(
        state,
        make_creature("Pro-Red", "{W}", 2, 2, keywords={protection_keyword("red")}),
        1,
    )
    # Target it via a colorless-looking path: the source is the red
    # spell, so the damage is prevented even when the targeting check
    # is bypassed (e.g. protection gained after targets were locked in
    # on a multi-target spell).
    bolt = _put(state, BOLT, 0, Zone.HAND)
    state.resolving_spell = bolt
    BOLT.spell_effect.resolve(state, 0, (("creature", knight.id),))
    state.resolving_spell = None
    assert knight.damage == 0
    assert any("prevented (protection)" in line for line in state.log)


def test_combat_damage_from_protected_color_is_prevented_and_blocks_disallowed():
    state = _state()
    attacker = _put(
        state,
        make_creature("Pro-Green Attacker", "{W}", 2, 2,
                      keywords={protection_keyword("green")}),
        0,
    )
    green = _put(state, make_creature("Green Blocker", "{G}", 3, 3), 1)
    blue = _put(state, make_creature("Blue Blocker", "{U}", 1, 1), 1)
    assert not can_block(state, green, attacker)
    assert can_block(state, blue, attacker)


def test_combat_damage_to_protected_blocker_is_prevented():
    state = _state()
    attacker = _put(state, make_creature("Red Attacker", "{R}", 3, 3), 0)
    blocker = _put(
        state,
        make_creature("Pro-Red Wall", "{W}", 0, 2, keywords={protection_keyword("red")}),
        1,
    )
    _simulate_combat_step(state, [attacker.id], [(blocker.id, attacker.id)])
    assert blocker in state.battlefield and blocker.damage == 0


def test_combat_damage_that_cant_be_prevented_ignores_protection():
    state = _state()
    attacker = _put(
        state,
        make_creature("Baloth", "{R}", 3, 3, combat_damage_cant_be_prevented=True),
        0,
    )
    blocker = _put(
        state,
        make_creature("Pro-Red Wall", "{W}", 0, 5, keywords={protection_keyword("red")}),
        1,
    )
    _simulate_combat_step(state, [attacker.id], [(blocker.id, attacker.id)])
    assert blocker.damage == 3


# ---------------------------------------------------------------- attachments


def test_aura_falls_off_creature_that_gains_protection_from_its_color():
    state = _state()
    host = _put(state, make_creature("Host", "{W}", 2, 2), 1)
    aura = _put(state, make_aura("Black Aura", "{B}", 1, 0), 0)
    aura.attached_to = host.id
    state_based_actions(state)
    assert aura in state.battlefield
    _grant(state, host, protection_keyword("black"))
    state_based_actions(state)
    assert aura not in state.battlefield


def test_equipment_unattaches_from_creature_with_protection_from_artifacts():
    state = _state()
    host = _put(state, make_creature("Host", "{W}", 2, 2), 0)
    eq = _put(state, make_equipment("Sword", "{2}", 1, 1, equip_cost="{2}"), 0)
    eq.attached_to = host.id
    state_based_actions(state)
    assert eq.attached_to == host.id
    _grant(state, host, protection_keyword("artifacts"))
    state_based_actions(state)
    assert eq.attached_to is None and eq in state.battlefield


# ---------------------------------------------------------------- parser


def test_keyword_line_parses_shroud_exalted_and_protection():
    assert _parse_keyword_line("Shroud") == ("shroud",)
    assert _parse_keyword_line("Exalted") == ("exalted",)
    assert _parse_keyword_line("Protection from red") == ("protection from red",)
    assert _parse_keyword_line("Flying, protection from black and from white") == (
        "flying", "protection from black", "protection from white",
    )


@pytest.mark.parametrize(
    "line",
    [
        "Protection from the chosen ones",
        "Protection from spells that are one or more colors",
        "Flying, protection from purple",
    ],
)
def test_keyword_line_refuses_unmodeled_protection(line):
    assert _parse_keyword_line(line) is None


def test_granted_keyword_body_accepts_protection_and_shroud():
    assert _parse_keyword_grant_body("haste and shroud") == frozenset({"haste", "shroud"})
    assert _parse_keyword_grant_body("protection from red and from blue") == frozenset(
        {"protection from red", "protection from blue"}
    )
    assert _parse_keyword_grant_body("hexproof and indestructible") == frozenset(
        {"hexproof", "indestructible"}
    )
    assert _parse_keyword_grant_body("protection from the chosen ones") is None


# ---------------------------------------------------------------- prowess / menace / exalted


def _cast_and_drain(state, card):
    from mtg_bot.actions import drain_stack

    apply(state, CastSpell(card.id), player_id=0)
    drain_stack(state)


def test_prowess_pumps_on_noncreature_spell_only():
    from mtg_bot.game import effective_power, effective_toughness

    state = _state()
    _lands(state, 0, "Mountain", 3)
    monk = _put(state, make_creature("Monk", "{R}", 1, 4, keywords={"prowess"}), 0)
    bolt = _put(state, BOLT, 0, Zone.HAND)
    _cast_and_drain(state, bolt)
    assert (effective_power(state, monk), effective_toughness(state, monk)) == (2, 5)
    assert monk in state.battlefield
    bear = _put(state, make_creature("Bear", "{R}", 2, 2), 0, Zone.HAND)
    _cast_and_drain(state, bear)
    assert effective_power(state, monk) == 2


def test_granted_prowess_triggers_and_opponent_prowess_does_not():
    from mtg_bot.game import effective_power

    state = _state()
    _lands(state, 0, "Mountain", 1)
    mine = _put(state, make_creature("Mine", "{R}", 1, 1), 0)
    theirs = _put(state, make_creature("Theirs", "{R}", 1, 1, keywords={"prowess"}), 1)
    _grant(state, mine, "prowess")
    bolt = _put(state, BOLT, 0, Zone.HAND)
    state.players[0].agent = _RecordingAgent()
    _cast_and_drain(state, bolt)
    assert effective_power(state, mine) == 2
    assert theirs not in state.battlefield or effective_power(state, theirs) == 1


def test_granted_menace_requires_two_blockers():
    from mtg_bot.actions import DeclareAttackers, DeclareBlockers

    state = _state()
    attacker = _put(state, make_creature("Brute", "{R}", 3, 3), 0)
    _grant(state, attacker, "menace")
    blocker = _put(state, make_creature("Wall", "{W}", 0, 5), 1)
    state.step = Step.DECLARE_ATTACKERS
    apply(state, DeclareAttackers(attacker_ids=frozenset({attacker.id})), player_id=0)
    state.step = Step.DECLARE_BLOCKERS
    apply(state, DeclareBlockers(assignments=((blocker.id, attacker.id),)), player_id=1)
    assert blocker.blocking is None


def test_granted_exalted_pumps_lone_attacker():
    from mtg_bot.game import effective_power

    state = _state()
    attacker = _put(state, make_creature("Lone", "{G}", 1, 1), 0)
    helper = _put(state, make_creature("Helper", "{G}", 0, 1), 0)
    _grant(state, helper, "exalted")
    _simulate_combat_step(state, [attacker.id])
    assert state.players[1].life == 18


# ---------------------------------------------------------------- player-quality protection


def test_true_name_nemesis_protection_from_chosen_player():
    from mtg_bot.actions import put_into_battlefield
    from mtg_bot.cards.parser.source import OracleParserCardSource

    tnn = OracleParserCardSource(pool="cube").get_printings()["True-Name Nemesis"]
    assert tnn.chooses_player_as_enters
    state = _state()
    obj = state.new_object(tnn, 0, Zone.HAND)
    put_into_battlefield(state, obj, 0)
    # _RecordingAgent picks the first offered player (P0) — the engine
    # honours the agent's choice.
    assert obj.chosen_player_id == 0
    obj.chosen_player_id = 1
    theirs = _put(state, make_creature("Theirs", "{R}", 3, 3), 1)
    mine = _put(state, make_creature("Mine", "{R}", 3, 3), 0)
    assert is_protected_from(state, obj, theirs)
    assert not is_protected_from(state, obj, mine)
    assert not can_be_targeted_by(state, obj, theirs, 1)
    assert not can_block(state, theirs, obj)


def test_chosen_player_default_and_opponents_quality():
    from mtg_bot.actions import put_into_battlefield

    class _BadAgent(_RecordingAgent):
        def choose_target(self, state, player_id, legal_targets):
            return ("player", 99)

    state = _state(agent0=_BadAgent())
    card = make_creature("Chooser", "{1}", 1, 1, chooses_player_as_enters=True)
    obj = state.new_object(card, 0, Zone.HAND)
    put_into_battlefield(state, obj, 0)
    assert obj.chosen_player_id == 1
    guarded = _put(
        state,
        make_creature("Guarded", "{W}", 1, 1,
                      keywords={protection_keyword("each of your opponents")}),
        0,
    )
    assert is_protected_from(state, guarded, _put(state, make_creature("O", "{R}", 1, 1), 1))
    assert not is_protected_from(state, guarded, _put(state, make_creature("M", "{R}", 1, 1), 0))
    unset = _put(
        state,
        make_creature("Unset", "{W}", 1, 1,
                      keywords={protection_keyword("the chosen player")}),
        0,
    )
    assert not is_protected_from(state, unset, _put(state, make_creature("Q", "{R}", 1, 1), 1))


def test_self_has_keywords_and_choose_player_lines():
    from mtg_bot.cards.parser.printing_keywords import (
        _parse_chooses_player_line,
        _parse_self_has_keywords_line,
    )

    assert _parse_chooses_player_line("As this creature enters, choose a player.")
    assert _parse_self_has_keywords_line("This creature has flying and haste.") == frozenset(
        {"flying", "haste"}
    )
    assert _parse_self_has_keywords_line("This creature has banding.") is None
    assert _parse_self_has_keywords_line("Flying") is None
    assert _parse_keyword_line("Protection from each of your opponents") == (
        "protection from each of your opponents",
    )
