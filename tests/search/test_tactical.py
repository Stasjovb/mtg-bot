"""Tests for ``DefaultTacticalAgent``."""

from mtg_bot.actions import CastSpell, PassPriority, PlayLand
from mtg_bot.game import GameState, Player
from mtg_bot.search.tactical import DefaultTacticalAgent


def _state():
    s = GameState()
    s.players.append(Player(id=0))
    s.players.append(Player(id=1))
    return s


def test_choose_action_prefers_pass():
    agent = DefaultTacticalAgent()
    s = _state()
    legal = [PlayLand(card_id=1), PassPriority(), CastSpell(card_id=2)]
    assert agent.choose_action(s, 0, legal) == PassPriority()


def test_choose_action_without_pass_returns_first_legal():
    agent = DefaultTacticalAgent()
    s = _state()
    legal = [PlayLand(card_id=1), CastSpell(card_id=2)]
    assert agent.choose_action(s, 0, legal) == PlayLand(card_id=1)


def test_choose_action_with_no_legal_actions_returns_pass():
    agent = DefaultTacticalAgent()
    s = _state()
    assert agent.choose_action(s, 0, []) == PassPriority()


def test_declare_attackers_attacks_with_all_eligible():
    agent = DefaultTacticalAgent()
    s = _state()

    # Fake objects with .id — DefaultTacticalAgent only looks at .id.
    class _Obj:
        def __init__(self, oid):
            self.id = oid

    eligible = [_Obj(10), _Obj(11), _Obj(12)]
    assert agent.declare_attackers(s, 0, eligible) == [10, 11, 12]


def test_declare_blockers_blocks_nothing():
    agent = DefaultTacticalAgent()
    s = _state()
    assert agent.declare_blockers(s, 0, eligible=[], attackers=[]) == {}


def test_choose_target_picks_first_legal():
    agent = DefaultTacticalAgent()
    s = _state()
    targets = [("creature", 5), ("creature", 6)]
    assert agent.choose_target(s, 0, targets) == ("creature", 5)


def test_choose_target_none_when_no_targets():
    agent = DefaultTacticalAgent()
    s = _state()
    assert agent.choose_target(s, 0, []) is None


def test_choose_mode_defaults_to_first():
    agent = DefaultTacticalAgent()
    s = _state()
    assert agent.choose_mode(s, 0, ["mode0", "mode1", "mode2"]) == 0


def test_choose_pay_shock_life_declines():
    agent = DefaultTacticalAgent()
    s = _state()
    assert agent.choose_pay_shock_life(s, 0, 2) is False


def test_choose_x_takes_full_budget():
    agent = DefaultTacticalAgent()
    s = _state()
    assert agent.choose_x(s, 0, "Fireball", upper_bound=5) == 5


def test_choose_surveil_keeps_on_top():
    agent = DefaultTacticalAgent()
    s = _state()
    assert agent.choose_surveil(s, 0, top_card_id=99) is False


def test_choose_sacrifice_picks_first():
    agent = DefaultTacticalAgent()
    s = _state()
    assert agent.choose_sacrifice(s, 0, [10, 20, 30]) == 10


def test_choose_discard_picks_first():
    agent = DefaultTacticalAgent()
    s = _state()
    assert agent.choose_discard(s, 0, [5, 6, 7]) == 5


def test_choose_card_from_library_picks_first():
    agent = DefaultTacticalAgent()
    s = _state()
    assert agent.choose_card_from_library(s, 0, [1, 2, 3]) == 1


def test_choose_card_from_library_none_when_empty():
    agent = DefaultTacticalAgent()
    s = _state()
    assert agent.choose_card_from_library(s, 0, []) is None


def test_choose_card_from_opponent_hand_picks_first():
    agent = DefaultTacticalAgent()
    s = _state()
    assert agent.choose_card_from_opponent_hand(s, 0, [1, 2]) == 1


def test_choose_devour_lands_takes_no_lands():
    agent = DefaultTacticalAgent()
    s = _state()
    assert agent.choose_devour_lands(s, 0, [10, 11, 12]) == []


def test_defaults_cover_every_base_agent_method():
    """Every abstract method on Agent has a concrete override in
    DefaultTacticalAgent — otherwise mid-resolution callbacks would
    bubble NotImplementedError out of the adapter."""
    from mtg_bot.agents import Agent

    agent = DefaultTacticalAgent()
    for name in dir(Agent):
        if not name.startswith("choose") and name not in {
            "declare_attackers", "declare_blockers",
        }:
            continue
        # If DefaultTacticalAgent doesn't override, this raises
        # NotImplementedError when called with a null arg tuple — we
        # only need to verify the override EXISTS, not test behavior.
        assert getattr(type(agent), name) is not getattr(Agent, name), (
            f"DefaultTacticalAgent should override {name}"
        )
