"""Behavioural tests for cards whose activated abilities only work at
instant speed (``docs/INSTANT_SPEED_ACTIVATIONS_DESIGN.md``).

Every test drives the real turn structure (``simulate.run_step`` and its
priority loop) with scripted agents that activate an ability only when
it is offered in the window the card is built for -- the opponent's
turn, in response to a spell, or mid-combat -- and then checks the
outcome. Before instant-speed activations these windows never offered
the ability, so every plan below would have gone unexecuted.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from mtg_bot.actions import ActivateAbility, CastSpell, PassPriority
from mtg_bot.cards.base import make_creature
from mtg_bot.game import Zone
from mtg_bot.legal import legal_actions
from mtg_bot.simulate import run_step
from mtg_bot.turn import Step
from tests._cube_artifact_helpers import ScriptedAgent
from tests._roto_helpers import arena, printing, put, to_hand, to_library

BEAR = make_creature("Test Bear", "{1}{G}", 2, 2)
OGRE = make_creature("Test Ogre", "{2}{R}", 3, 3)
TROLL = make_creature("Test Troll", "{3}{G}", 4, 4)

COMBAT = (
    Step.BEGINNING_OF_COMBAT, Step.DECLARE_ATTACKERS, Step.DECLARE_BLOCKERS,
    Step.COMBAT_DAMAGE, Step.END_OF_COMBAT,
)

def _cube(name: str):
    """A PowerLSV cube card built through the parser source's own claim
    path (``build_card_record``), asserting it is claimed."""
    from mtg_bot.cards.parser.source import build_card_record
    from tests._cube_artifact_helpers import cube_card

    built = build_card_record(cube_card(name))
    assert built is not None, f"{name} should be claimed by the parser"
    return built



@dataclass
class PlanAgent(ScriptedAgent):
    """Passes priority unless a planned action is legal right now.

    ``plan`` is a list of ``(when(state) -> bool, action)`` pairs; an
    entry fires (once) the first time ``when`` holds and ``action`` --
    an ``Action`` or a ``state -> Action`` callable -- is in the legal
    set. ``fired`` records ``(step, action)`` for every executed entry.
    """

    plan: list = field(default_factory=list)
    attack_with: tuple = ()
    blocks: dict = field(default_factory=dict)
    fired: list = field(default_factory=list)

    def choose_action(self, state, player_id, legal):
        for i, (when, action) in enumerate(self.plan):
            act = action(state) if callable(action) else action
            if when(state) and act in legal:
                del self.plan[i]
                self.fired.append((state.step, act))
                return act
        return PassPriority()

    def declare_attackers(self, state, player_id, eligible):
        ids = {o.id for o in eligible}
        return [i for i in self.attack_with if i in ids]

    def declare_blockers(self, state, player_id, eligible, attackers):
        return dict(self.blocks)


def _seat(state):
    for p in state.players:
        p.agent = PlanAgent()
    return state.players[0].agent, state.players[1].agent


def _run(state, *steps):
    for step in steps:
        run_step(state, step)
        if state.is_over():
            return


def _lands(state, name, n, pid=0):
    return [put(state, printing(name), pid) for _ in range(n)]


def _in(step):
    return lambda s: s.step == step


def _stack_nonempty(s):
    return bool(s.stack)


def _opp_turn_arena():
    """P1 is the active player (P0 acts on the opponent's turn)."""
    state = arena(active=1)
    for pid in (0, 1):
        for _ in range(3):
            to_library(state, BEAR, pid)
    return state


# ---------------------------------------------------------------------
# The roto P6 cards claimed under the old sorcery-only limitation
# ---------------------------------------------------------------------


def test_maze_of_ith_stops_an_attacker_on_the_opponents_turn():
    state = _opp_turn_arena()
    me, opp = _seat(state)
    maze = put(state, printing("Maze of Ith"), 0)
    ogre = put(state, OGRE, 1)
    opp.attack_with = (ogre.id,)
    me.targets = [("creature", ogre.id)]
    me.plan = [(_in(Step.DECLARE_ATTACKERS), ActivateAbility(maze.id, 0))]
    _run(state, *COMBAT)
    assert me.fired == [(Step.DECLARE_ATTACKERS, ActivateAbility(maze.id, 0))]
    assert state.players[0].life == 20
    assert maze.tapped and not ogre.tapped


def test_maze_of_ith_without_the_activation_takes_the_hit():
    """Control: the same combat with no activation deals 3."""
    state = _opp_turn_arena()
    _me, opp = _seat(state)
    put(state, printing("Maze of Ith"), 0)
    ogre = put(state, OGRE, 1)
    opp.attack_with = (ogre.id,)
    _run(state, *COMBAT)
    assert state.players[0].life == 17


def test_cephalid_illusionist_shields_a_blocker_on_the_opponents_turn():
    state = _opp_turn_arena()
    me, opp = _seat(state)
    illusionist = put(state, printing("Cephalid Illusionist"), 0)
    _lands(state, "Island", 3)
    bear = put(state, BEAR, 0)
    ogre = put(state, OGRE, 1)
    opp.attack_with = (ogre.id,)
    me.blocks = {bear.id: ogre.id}
    me.targets = [("creature", bear.id)]
    me.plan = [
        (_in(Step.DECLARE_BLOCKERS), ActivateAbility(illusionist.id, 0)),
    ]
    _run(state, *COMBAT)
    assert me.fired
    assert bear in state.battlefield and bear.damage == 0
    assert ogre.damage == 0


def test_cephalid_illusionist_mills_itself_when_targeted_mid_combat():
    """The Nomads en-Kor combo half: targeting the Illusionist with its
    own ability (in a combat it isn't in) mills three."""
    state = _opp_turn_arena()
    me, opp = _seat(state)
    illusionist = put(state, printing("Cephalid Illusionist"), 0)
    _lands(state, "Island", 3)
    for _ in range(3):
        to_library(state, BEAR, 0)
    ogre = put(state, OGRE, 1)
    opp.attack_with = (ogre.id,)
    me.targets = [("creature", illusionist.id)]
    me.plan = [
        (_in(Step.DECLARE_ATTACKERS), ActivateAbility(illusionist.id, 0)),
    ]
    library_before = len(state.players[0].library)
    _run(state, *COMBAT)
    assert me.fired
    assert len(state.players[0].library) == library_before - 3


def test_nomads_en_kor_redirects_combat_damage_three_times_in_response():
    state = _opp_turn_arena()
    me, opp = _seat(state)
    nomads = put(state, printing("Nomads en-Kor"), 0)
    troll = put(state, TROLL, 0)
    ogre = put(state, OGRE, 1)
    opp.attack_with = (ogre.id,)
    me.blocks = {nomads.id: ogre.id}
    me.targets = [("creature", troll.id)] * 3
    redirect = ActivateAbility(nomads.id, 0)
    me.plan = [(_in(Step.DECLARE_BLOCKERS), redirect)] * 3
    _run(state, *COMBAT)
    assert len(me.fired) == 3
    assert nomads in state.battlefield and nomads.damage == 0
    assert troll.damage == 3


def test_blight_mamba_regenerates_while_blocking():
    state = _opp_turn_arena()
    me, opp = _seat(state)
    mamba = put(state, printing("Blight Mamba"), 0)
    _lands(state, "Forest", 2)
    ogre = put(state, OGRE, 1)
    opp.attack_with = (ogre.id,)
    me.blocks = {mamba.id: ogre.id}
    me.plan = [(_in(Step.DECLARE_BLOCKERS), ActivateAbility(mamba.id, 0))]
    _run(state, *COMBAT)
    assert me.fired
    assert mamba in state.battlefield and mamba.tapped  # regenerated
    assert ogre.temp_toughness_bonus == -1  # infect (engine folds -1/-1)


def test_blight_mamba_dies_without_the_shield():
    state = _opp_turn_arena()
    me, opp = _seat(state)
    mamba = put(state, printing("Blight Mamba"), 0)
    _lands(state, "Forest", 2)
    ogre = put(state, OGRE, 1)
    opp.attack_with = (ogre.id,)
    me.blocks = {mamba.id: ogre.id}
    _run(state, *COMBAT)
    assert mamba not in state.battlefield


def test_sundial_ends_the_turn_in_response_to_a_spell():
    state = arena(active=0)
    me, opp = _seat(state)
    sundial = put(state, printing("Sundial of the Infinite"), 0)
    _lands(state, "Plains", 1)
    bolt = to_hand(state, printing("Lightning Bolt"), 1)
    _lands(state, "Mountain", 1, 1)
    opp.targets = [("player", 0)]
    opp.plan = [(lambda s: not s.stack, CastSpell(bolt.id))]
    me.plan = [(_stack_nonempty, ActivateAbility(sundial.id, 0))]
    _run(state, Step.PRECOMBAT_MAIN)
    assert opp.fired and me.fired
    assert state.players[0].life == 20  # the Bolt never resolved
    assert bolt in state.players[1].exile
    assert state.turn_ending


def test_sundial_is_not_offered_on_the_opponents_turn():
    state = _opp_turn_arena()
    sundial = put(state, printing("Sundial of the Infinite"), 0)
    _lands(state, "Plains", 1)
    state.step = Step.END
    state.priority_player_idx = 0
    assert ActivateAbility(sundial.id, 0) not in legal_actions(state, 0)


def test_ranger_captain_sacrifices_in_the_opponents_upkeep():
    state = _opp_turn_arena()
    me, opp = _seat(state)
    captain = put(state, printing("Ranger-Captain of Eos"), 0)
    bolt = to_hand(state, printing("Lightning Bolt"), 1)
    _lands(state, "Mountain", 1, 1)
    me.plan = [(_in(Step.UPKEEP), ActivateAbility(captain.id, 0))]
    _run(state, Step.UPKEEP)
    assert me.fired and captain not in state.battlefield
    state.step = Step.PRECOMBAT_MAIN
    state.priority_player_idx = 1
    assert CastSpell(bolt.id) not in legal_actions(state, 1)


def test_high_noon_kills_an_attacker_before_damage():
    state = _opp_turn_arena()
    me, opp = _seat(state)
    noon = put(state, printing("High Noon"), 0)
    _lands(state, "Mountain", 5)
    ogre = put(state, OGRE, 1)
    opp.attack_with = (ogre.id,)
    me.targets = [("creature", ogre.id)]
    me.plan = [(_in(Step.DECLARE_ATTACKERS), ActivateAbility(noon.id, 0))]
    _run(state, *COMBAT)
    assert me.fired
    assert ogre not in state.battlefield and noon not in state.battlefield
    assert state.players[0].life == 20


def test_glen_elendra_guardian_counters_through_the_priority_loop():
    state = arena(active=1)
    me, opp = _seat(state)
    guardian = put(state, printing("Glen Elendra Guardian"), 0)
    guardian.minus_one_counters = 1
    _lands(state, "Island", 2)
    bolt = to_hand(state, printing("Lightning Bolt"), 1)
    _lands(state, "Mountain", 1, 1)
    to_library(state, BEAR, 1)
    opp.targets = [("player", 0)]
    opp.plan = [(lambda s: not s.stack, CastSpell(bolt.id))]
    me.targets = [("stack", 0)]
    me.plan = [(_stack_nonempty, ActivateAbility(guardian.id, 0))]
    hand_before = len(state.players[1].hand)
    _run(state, Step.PRECOMBAT_MAIN)
    assert me.fired
    assert state.players[0].life == 20
    assert guardian.minus_one_counters == 0
    # Bolt left the hand (cast) and its controller drew a card.
    assert len(state.players[1].hand) == hand_before


# ---------------------------------------------------------------------
# Tinder Wall (claimed by this change)
# ---------------------------------------------------------------------


def test_tinder_wall_is_claimed_with_its_blocking_target():
    from mtg_bot.effects.object_predicates import BlockedBySource, IsCreature

    p = printing("Tinder Wall")
    mana, burn = p.activated_abilities
    assert mana.is_mana_ability and mana.cost.sacrifice_self
    assert not burn.is_mana_ability and burn.cost.sacrifice_self
    assert burn.cost.mana_str == "{R}"
    assert burn.effect.amount == 2
    assert burn.effect.targets[0].filter == IsCreature() & BlockedBySource()


def test_tinder_wall_burns_the_creature_it_blocks():
    state = _opp_turn_arena()
    me, opp = _seat(state)
    wall = put(state, printing("Tinder Wall"), 0)
    _lands(state, "Mountain", 1)
    bear = put(state, BEAR, 1)
    other = put(state, BEAR, 1)
    opp.attack_with = (bear.id, other.id)
    me.blocks = {wall.id: bear.id}
    me.plan = [(_in(Step.DECLARE_BLOCKERS), ActivateAbility(wall.id, 1))]
    seen_targets = []

    def _pick(state_, pid, legal):
        seen_targets.append(list(legal))
        return legal[0]

    me.choose_target = _pick
    _run(state, *COMBAT)
    assert me.fired
    # Only the creature it's blocking was a legal target, and the
    # damage is dealt even though the Wall was sacrificed as a cost
    # (last known information).
    assert seen_targets == [[("creature", bear.id)]]
    assert bear not in state.battlefield
    assert wall not in state.battlefield
    assert other in state.battlefield
    assert state.players[0].life == 18  # the unblocked Bear connects


def test_tinder_wall_burn_needs_a_creature_it_is_blocking():
    state = _opp_turn_arena()
    wall = put(state, printing("Tinder Wall"), 0)
    _lands(state, "Mountain", 1)
    state.step = Step.END
    state.priority_player_idx = 0
    assert ActivateAbility(wall.id, 1) not in legal_actions(state, 0)


def test_blocked_by_source_reads_the_live_block_then_last_known_info():
    from mtg_bot.effects.object_predicates import BlockedBySource

    state = arena(active=1)
    wall = put(state, printing("Tinder Wall"), 0)
    bear = put(state, BEAR, 1)
    pred = BlockedBySource()
    assert not pred.test(bear, state)  # no source pinned
    state.resolving_source = wall
    assert not pred.test(bear, state)
    wall.blocking = bear.id
    bear.blocked_by = [wall.id]
    assert pred.test(bear, state)
    assert not pred.test(wall, state)
    # Removed from combat while still on the battlefield: not blocking.
    wall.blocking = None
    assert not pred.test(bear, state)
    # Left the battlefield: last known information (the attacker still
    # lists it among its blockers, CR 509.1h).
    state.battlefield.remove(wall)
    wall.zone = Zone.GRAVEYARD
    assert pred.test(bear, state)
    assert not pred.test(state.players[0], state)  # a player, not an object


# ---------------------------------------------------------------------
# Already-claimed cards whose abilities only now work at instant speed
# ---------------------------------------------------------------------


def test_mother_of_runes_saves_a_creature_in_response_to_removal():
    state = arena(active=1)
    me, opp = _seat(state)
    mother = put(state, printing("Mother of Runes"), 0)
    bear = put(state, BEAR, 0)
    bolt = to_hand(state, printing("Lightning Bolt"), 1)
    _lands(state, "Mountain", 1, 1)
    opp.targets = [("creature", bear.id)]
    opp.plan = [(lambda s: not s.stack, CastSpell(bolt.id))]
    me.targets = [("creature", bear.id)]
    me.colors = ["R"]
    me.plan = [(_stack_nonempty, ActivateAbility(mother.id, 0))]
    _run(state, Step.PRECOMBAT_MAIN)
    assert me.fired and mother.tapped
    assert bear in state.battlefield and bear.damage == 0


def test_giver_of_runes_protects_another_creature_from_removal():
    state = arena(active=1)
    me, opp = _seat(state)
    giver = put(state, printing("Giver of Runes"), 0)
    bear = put(state, BEAR, 0)
    bolt = to_hand(state, printing("Lightning Bolt"), 1)
    _lands(state, "Mountain", 1, 1)
    opp.targets = [("creature", bear.id)]
    opp.plan = [(lambda s: not s.stack, CastSpell(bolt.id))]
    me.targets = [("creature", bear.id)]
    me.colors = ["R"]
    me.plan = [(_stack_nonempty, ActivateAbility(giver.id, 0))]
    _run(state, Step.PRECOMBAT_MAIN)
    assert me.fired
    assert bear in state.battlefield and bear.damage == 0


def test_walking_ballista_pings_at_the_opponents_end_step():
    state = _opp_turn_arena()
    me, _opp = _seat(state)
    ballista = put(state, printing("Walking Ballista"), 0)
    ballista.plus_one_counters = 2
    me.targets = [("player", 1), ("player", 1)]
    ping = ActivateAbility(ballista.id, 1)
    me.plan = [(_in(Step.END), ping), (_in(Step.END), ping)]
    _run(state, Step.END)
    assert len(me.fired) == 2
    assert state.players[1].life == 18
    assert ballista not in state.battlefield  # 0/0 with no counters


def test_aether_vial_puts_a_creature_in_at_the_opponents_end_step():
    state = _opp_turn_arena()
    me, _opp = _seat(state)
    vial = put(state, printing("Aether Vial"), 0)
    vial.charge_counters = 2
    bear = to_hand(state, BEAR, 0)
    me.plan = [(_in(Step.END), ActivateAbility(vial.id, 0))]
    _run(state, Step.END)
    assert me.fired
    assert bear in state.battlefield and bear.controller_id == 0


def test_wasteland_destroys_a_land_in_the_opponents_upkeep():
    state = _opp_turn_arena()
    me, _opp = _seat(state)
    waste = put(state, printing("Wasteland"), 0)
    ind = waste.printing.activated_abilities.index(next(
        a for a in waste.printing.activated_abilities if not a.is_mana_ability
    ))
    target = put(state, printing("Library of Alexandria"), 1)
    me.targets = [("permanent", target.id), ("land", target.id)]
    me.plan = [(_in(Step.UPKEEP), ActivateAbility(waste.id, ind))]
    _run(state, Step.UPKEEP)
    assert me.fired
    assert target not in state.battlefield and waste not in state.battlefield


def test_strip_mine_hits_a_land_at_instant_speed():
    state = _opp_turn_arena()
    state.step = Step.END
    strip = put(state, printing("Strip Mine"), 0)
    put(state, printing("Mountain"), 1)
    state.priority_player_idx = 0
    assert any(
        isinstance(a, ActivateAbility) and a.source_id == strip.id
        for a in legal_actions(state, 0)
    )


def test_smugglers_copter_crews_on_the_opponents_turn_to_block():
    state = _opp_turn_arena()
    me, opp = _seat(state)
    copter = put(state, _cube("Smuggler's Copter"), 0)
    crew = put(state, BEAR, 0)
    ogre = put(state, BEAR, 1)
    opp.attack_with = (ogre.id,)
    me.blocks = {copter.id: ogre.id}
    me.plan = [
        (_in(Step.DECLARE_ATTACKERS), ActivateAbility(copter.id, 0)),
    ]
    _run(state, *COMBAT)
    assert me.fired and crew.tapped
    assert state.players[0].life == 20  # the crewed Copter blocked
