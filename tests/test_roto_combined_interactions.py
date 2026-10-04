"""Interactions between the two 2026-10-03 roto branches.

``feature/roto-instant-activations`` made permanents' activated
abilities activatable whenever their controller has priority (CR 117.1b
/ 602.5); ``feature/roto-default-pool-leyline-wizard`` folded the
Vintage Roto list into the default ``all`` card source and built
Meddling Wizard's post-mulligan hand reveal. Each branch tested its
change against the other's absence. Covered here, with both in place:

* roto-only permanents reached through the *default* card source (the
  one ``setup_game`` resolves decklists through) are offered their
  abilities at instant speed exactly as the ``roto`` pool's build is;
* Meddling Wizard's reveal holds across the new priority windows: an
  instant-speed activation in the Wizard controller's own turn that
  puts hand cards back face down (Scroll Rack) forgets them, one that
  moves a hand card face up (Aether Vial) keeps the rest known, and the
  search at a decision only the instant-speed rule creates (the
  Wizard's controller holding an ability in the opponent's upkeep)
  samples worlds holding the revealed hand.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from functools import lru_cache

import pytest

from mtg_bot.actions import ActivateAbility, PassPriority
from mtg_bot.agents import RandomAgent
from mtg_bot.cards import pools
from mtg_bot.cards.base import make_creature
from mtg_bot.cards.parser_source import OracleParserCardSource
from mtg_bot.cards.source import get_active_source
from mtg_bot.game import Zone, effective_activated_abilities
from mtg_bot.legal import activation_timing_permits, legal_actions
from mtg_bot.search import Budget, HeuristicsConfig, MtgGameStateAdapter
from mtg_bot.search import RandomRolloutEvaluator
from mtg_bot.search.determinize import determinize
from mtg_bot.search.ismcts import ISMCTS
from mtg_bot.simulate import run_step, setup_game
from mtg_bot.turn import Step
from tests._cube_artifact_helpers import ScriptedAgent, arena, put, to_library
from tests._test_decks import simple_test_decklist

WIZARD = "Meddling Wizard"

BEAR = make_creature("Test Bear", "{1}{G}", 2, 2)
OGRE = make_creature("Test Ogre", "{2}{R}", 3, 3)

COMBAT = (
    Step.BEGINNING_OF_COMBAT, Step.DECLARE_ATTACKERS, Step.DECLARE_BLOCKERS,
    Step.COMBAT_DAMAGE, Step.END_OF_COMBAT,
)

# Roto-only cards (on neither the cube nor the EoE-era lists) whose
# abilities the instant-speed change covers; each is exercised
# behaviourally in tests/test_instant_activation_cards.py through the
# roto pool's build.
ROTO_ONLY_INSTANT_SPEED = (
    "Aether Vial", "Blight Mamba", "Cephalid Illusionist",
    "Glen Elendra Guardian", "High Noon", "Maze of Ith", "Nomads en-Kor",
    "Ranger-Captain of Eos", "Scroll Rack", "Sundial of the Infinite",
    "Tinder Wall",
)


def _default_printings():
    return get_active_source().get_printings()


@lru_cache(maxsize=1)
def _roto_pool_printings():
    return OracleParserCardSource(pool="roto").get_printings()


def _roto_only_names() -> set[str]:
    return (
        pools.pool_card_names("roto") - pools.pool_card_names("cube")
        - pools.pool_card_names("eoe")
    )


def _instant_speed_names(printings, names) -> set[str]:
    """Names whose permanent has an ability the timing rule lets its
    controller activate outside a sorcery window (P0 on P1's turn)."""
    state = arena(active=1)
    out = set()
    for name in names:
        if name not in printings or not printings[name].is_permanent:
            continue
        obj = put(state, printings[name], 0)
        if any(
            activation_timing_permits(state, obj, ab, sorcery_timing=False)
            for ab in effective_activated_abilities(state, obj)
        ):
            out.add(name)
        state.battlefield.remove(obj)
    return out


@dataclass
class PlanAgent(ScriptedAgent):
    """Passes priority unless a planned action is legal right now.

    ``plan`` is a list of ``(when(state) -> bool, action)`` pairs; an
    entry fires once, the first time ``when`` holds and ``action`` (an
    ``Action`` or a ``state -> Action`` callable) is legal. ``fired``
    records ``(active player, step, action)`` per executed entry."""

    plan: list = field(default_factory=list)
    attack_with: tuple = ()
    blocks: dict = field(default_factory=dict)
    hand_picks: list = field(default_factory=list)
    fired: list = field(default_factory=list)

    def choose_action(self, state, player_id, legal):
        for i, (when, action) in enumerate(self.plan):
            act = action(state) if callable(action) else action
            if when(state) and act in legal:
                del self.plan[i]
                self.fired.append((state.active_player_idx, state.step, act))
                return act
        return PassPriority()

    def declare_attackers(self, state, player_id, eligible):
        ids = {o.id for o in eligible}
        return [i for i in self.attack_with if i in ids]

    def declare_blockers(self, state, player_id, eligible, attackers):
        return dict(self.blocks)

    def choose_card_from_hand(self, state, player_id, option_ids):
        while self.hand_picks:
            pick = self.hand_picks.pop(0)
            if pick in option_ids:
                return pick
        return None


def _when(active: int, step: Step):
    return lambda s: s.active_player_idx == active and s.step == step


# ---------------------------------------------------------------------
# Roto instant-speed abilities through the default card source
# ---------------------------------------------------------------------


def test_default_source_holds_the_roto_instant_speed_permanents():
    """Every roto-only permanent whose ability is activatable at instant
    speed in the ``roto`` pool is in the default source, built the same,
    and the timing rule treats it the same there."""
    assert get_active_source().pool_name == pools.DEFAULT_POOL == "all"
    default, roto = _default_printings(), _roto_pool_printings()
    roto_only = _roto_only_names()
    assert set(ROTO_ONLY_INSTANT_SPEED) <= roto_only
    claimed_by_roto = roto_only & set(roto)
    assert roto_only & set(default) == claimed_by_roto
    via_default = _instant_speed_names(default, roto_only)
    assert via_default == _instant_speed_names(roto, roto_only)
    assert set(ROTO_ONLY_INSTANT_SPEED) <= via_default
    for name in via_default:
        assert default[name] == roto[name], name


def _offer_state(name: str, *, active: int, step: Step, lands: int = 3):
    """P0 controls ``name`` (default-source printing) and ``lands``
    Islands; P1 controls a creature. P0 holds priority in ``step`` of
    ``active``'s turn with an empty stack."""
    printings = _default_printings()
    state = arena(active=active)
    obj = put(state, printings[name], 0)
    for _ in range(lands):
        put(state, printings["Island"], 0)
    put(state, BEAR, 1)
    state.step = step
    state.priority_player_idx = 0
    return state, obj


def _offered(state, obj) -> list[int]:
    return sorted(
        a.ability_index for a in legal_actions(state, 0)
        if isinstance(a, ActivateAbility) and a.source_id == obj.id
    )


@pytest.mark.parametrize("name", [
    "Nomads en-Kor", "Cephalid Illusionist", "Scroll Rack", "Aether Vial",
])
@pytest.mark.parametrize("step", [Step.UPKEEP, Step.END])
def test_default_source_offers_roto_abilities_on_the_opponents_turn(
    name, step,
):
    state, obj = _offer_state(name, active=1, step=step)
    assert obj.printing is _default_printings()[name]
    assert _offered(state, obj) == [0]


def test_activate_only_during_your_turn_still_holds_in_the_default_source():
    """Sundial of the Infinite: instant speed, but only on its
    controller's turn."""
    theirs, dial = _offer_state(
        "Sundial of the Infinite", active=1, step=Step.END,
    )
    assert _offered(theirs, dial) == []
    mine, dial = _offer_state(
        "Sundial of the Infinite", active=0, step=Step.END,
    )
    assert _offered(mine, dial) == [0]


def test_default_source_maze_of_ith_and_tinder_wall_in_the_opponents_combat():
    """P1 attacks with an Ogre and a Bear; P0 mazes the Ogre in the
    declare-attackers step and burns the Bear its Tinder Wall blocks in
    the declare-blockers step -- both printings from the default source."""
    printings = _default_printings()
    state = arena(active=1)
    for pid in (0, 1):
        for _ in range(3):
            to_library(state, BEAR, pid)
    me, opp = PlanAgent(), PlanAgent()
    state.players[0].agent, state.players[1].agent = me, opp
    maze = put(state, printings["Maze of Ith"], 0)
    wall = put(state, printings["Tinder Wall"], 0)
    put(state, printings["Mountain"], 0)
    ogre, bear = put(state, OGRE, 1), put(state, BEAR, 1)
    opp.attack_with = (ogre.id, bear.id)
    me.blocks = {wall.id: bear.id}
    me.targets = [("creature", ogre.id)]
    burn = next(
        i for i, ab in enumerate(wall.printing.activated_abilities)
        if not ab.is_mana_ability
    )
    me.plan = [
        (_when(1, Step.DECLARE_ATTACKERS), ActivateAbility(maze.id, 0)),
        (_when(1, Step.DECLARE_BLOCKERS), ActivateAbility(wall.id, burn)),
    ]
    for step in COMBAT:
        run_step(state, step)
    assert me.fired == [
        (1, Step.DECLARE_ATTACKERS, ActivateAbility(maze.id, 0)),
        (1, Step.DECLARE_BLOCKERS, ActivateAbility(wall.id, burn)),
    ]
    assert state.players[0].life == 20
    assert maze.tapped and not ogre.tapped and ogre in state.battlefield
    assert bear not in state.battlefield and wall not in state.battlefield


# ---------------------------------------------------------------------
# Meddling Wizard's reveal across the new priority windows
# ---------------------------------------------------------------------


def _known_to(cards, viewer: int) -> list[bool]:
    return [viewer in c.publicly_known_to for c in cards]


def _names(cards) -> list[str]:
    return [c.printing.name for c in cards]


def _onto_battlefield(state, pid: int, name: str):
    """Move ``pid``'s copy of ``name`` (dealt from their decklist) onto
    the battlefield under their control, wherever it was dealt."""
    p = state.players[pid]
    for zone in (p.hand, p.library):
        obj = next((c for c in zone if c.printing.name == name), None)
        if obj is not None:
            zone.remove(obj)
            obj.zone = Zone.BATTLEFIELD
            obj.controller_id = pid
            obj.summoning_sick = False
            state.battlefield.append(obj)
            return obj
    raise AssertionError(f"P{pid} has no {name}")


def _wizard_game(p1_extra: list[str], *, agents, starting: int = 0):
    """P0 has Meddling Wizard; P1's decklist adds ``p1_extra`` (roto
    cards, resolved through the default source like any decklist)."""
    state = setup_game(
        agents,
        decks=[[WIZARD] + simple_test_decklist("G"),
               p1_extra + simple_test_decklist("R")],
        seed=5, starting_player_idx=starting,
    )
    assert all(_known_to(state.players[1].hand, 0))
    return state


def test_scroll_rack_in_the_wizard_controllers_upkeep_forgets_the_hand():
    """P1 activates Scroll Rack in P0's upkeep -- a window that offered
    it only once activations went instant-speed -- and puts one revealed
    card back face down: P0 can no longer tell which card went back, so
    neither it nor the rest of P1's hand stays known."""
    me, opp = PlanAgent(), PlanAgent()
    state = _wizard_game(["Scroll Rack"], agents=[me, opp])
    p1 = state.players[1]
    rack = _onto_battlefield(state, 1, "Scroll Rack")
    put(state, _default_printings()["Mountain"], 1)
    put_back = p1.hand[0]
    opp.hand_picks = [put_back.id]
    opp.plan = [(_when(0, Step.UPKEEP), ActivateAbility(rack.id, 0))]
    state.active_player_idx = 0
    state.step = Step.UPKEEP
    state.priority_player_idx = 1
    assert ActivateAbility(rack.id, 0) in legal_actions(state, 1)
    run_step(state, Step.UPKEEP)
    assert opp.fired == [(0, Step.UPKEEP, ActivateAbility(rack.id, 0))]
    assert rack.tapped and p1.library[0] is put_back
    assert not any(_known_to(p1.hand, 0)) and not _known_to([put_back], 0)[0]
    # P0's search samples P1's hand again.
    truth = _names(p1.hand)
    worlds = [determinize(state, 0, random.Random(s)) for s in range(20)]
    assert any(_names(w.players[1].hand) != truth for w in worlds)


def test_aether_vial_in_the_wizard_controllers_end_step_keeps_the_rest_known():
    """P1 vials a revealed creature in at P0's end step: the creature is
    public on the battlefield, and the cards still in P1's hand stay
    known to P0 (and fixed in P0's determinized worlds)."""
    me, opp = PlanAgent(), PlanAgent()
    state = _wizard_game(["Aether Vial"], agents=[me, opp])
    p1 = state.players[1]
    vial = _onto_battlefield(state, 1, "Aether Vial")
    creature = next(c for c in p1.hand if c.printing.is_creature)
    vial.charge_counters = creature.printing.mana_cost.total
    opp.hand_picks = [creature.id]
    opp.plan = [(_when(0, Step.END), ActivateAbility(vial.id, 0))]
    state.active_player_idx = 0
    run_step(state, Step.END)
    assert opp.fired == [(0, Step.END, ActivateAbility(vial.id, 0))]
    assert creature in state.battlefield and creature.controller_id == 1
    assert p1.hand and all(_known_to(p1.hand, 0))
    truth = _names(p1.hand)
    worlds = [determinize(state, 0, random.Random(s)) for s in range(20)]
    assert all(_names(w.players[1].hand) == truth for w in worlds)


def _recording(store):
    """A determinizer that records, per sampled world, the viewer and the
    opponent's hand as sampled (a snapshot: the iteration goes on to play
    that world forward, casting from the same hand list)."""

    def det(engine_state, viewer_id, rng, *, in_place=False):
        world = determinize(engine_state, viewer_id, rng, in_place=in_place)
        store.append((viewer_id, {
            c.id: c.printing.name for c in world.players[1 - viewer_id].hand
        }))
        return world

    return det


def test_search_in_an_instant_speed_window_uses_the_reveal():
    """P1 starts; P0 (the Wizard's controller) holds Aether Vial, so its
    first real decision comes in P1's opening upkeep -- before the
    instant-speed rule it would have been auto-passed. ISMCTS there
    searches worlds holding P1's revealed hand. (A tap ability: a free
    repeatable one such as Nomads en-Kor's would keep the random
    rollouts activating it to the decision cap -- SEARCH_LIMITATIONS,
    instant-speed activations #4.)

    The window is a search decision only where SEARCH_LIMITATIONS #17
    (the opponent's quiet-window skip) is off: the live eval config and
    ``disabled()`` offer it, the self-play default auto-passes it."""
    state = _wizard_game(
        [], agents=[RandomAgent(), RandomAgent()], starting=1,
    )
    vial = put(state, _default_printings()["Aether Vial"], 0)
    adapter = MtgGameStateAdapter(
        state, heuristics=HeuristicsConfig.disabled(),
    )
    for _ in range(200):
        legal = adapter.legal_decisions()
        if adapter.active_player() == 0 and len(legal) > 1:
            break
        adapter.apply(legal[0])
    else:  # pragma: no cover - the loop finds P0's decision
        pytest.fail("no multi-action decision for P0")
    engine = adapter.engine_state
    assert engine.active_player_idx == 1 and engine.step == Step.UPKEEP
    assert ActivateAbility(vial.id, 0) in legal_actions(engine, 0)
    assert ActivateAbility(vial.id, 0) in legal
    for config, offered in (
        (HeuristicsConfig.live_eval(), True), (HeuristicsConfig(), False),
    ):
        other = adapter.clone()
        other._heuristics = config
        other._invalidate_legal_actions_cache()
        assert (ActivateAbility(vial.id, 0) in other.legal_decisions()) is offered
    assert other.legal_decisions() == [PassPriority()]
    known = {
        c.id: c.printing.name for c in engine.players[1].hand
        if 0 in c.publicly_known_to
    }
    assert known and len(known) == len(engine.players[1].hand)
    worlds = []
    ismcts = ISMCTS(
        evaluator=RandomRolloutEvaluator(rng=random.Random(0)),
        budget_factory=lambda: Budget(max_nodes=12),
        rng=random.Random(1), determinize_fn=_recording(worlds), puct=False,
    )
    ismcts.choose_with_visits(adapter, 0)
    assert len(worlds) == 12
    for viewer, by_id in worlds:
        assert viewer == 0
        assert all(by_id.get(i) == name for i, name in known.items())
