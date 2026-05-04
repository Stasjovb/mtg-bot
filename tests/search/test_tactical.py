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


def test_choose_card_from_hand_picks_first():
    agent = DefaultTacticalAgent()
    s = _state()
    assert agent.choose_card_from_hand(s, 0, [3, 4, 5]) == 3


def test_choose_card_from_hand_none_when_empty():
    agent = DefaultTacticalAgent()
    s = _state()
    assert agent.choose_card_from_hand(s, 0, []) is None


def test_choose_card_from_opponent_hand_picks_first():
    agent = DefaultTacticalAgent()
    s = _state()
    assert agent.choose_card_from_opponent_hand(s, 0, [1, 2]) == 1


def test_choose_devour_lands_takes_no_lands():
    agent = DefaultTacticalAgent()
    s = _state()
    assert agent.choose_devour_lands(s, 0, [10, 11, 12]) == []


def test_choose_yes_no_takes_the_optional_action():
    """Default tactical says yes — preserves the legacy
    "may → always yes" semantics that many cards rely on."""
    agent = DefaultTacticalAgent()
    s = _state()
    assert agent.choose_yes_no(s, 0, "Take the may action?") is True


def test_choose_mana_color_picks_first_option():
    agent = DefaultTacticalAgent()
    s = _state()
    assert agent.choose_mana_color(s, 0, ["B", "G"]) == "B"


def test_choose_modes_returns_first_only():
    agent = DefaultTacticalAgent()
    s = _state()
    assert agent.choose_modes(s, 0, ["a", "b", "c"]) == [0]


def test_choose_permanent_to_tap_picks_first():
    agent = DefaultTacticalAgent()
    s = _state()
    assert agent.choose_permanent_to_tap(s, 0, [10, 11, 12]) == 10


def test_choose_permanent_to_tap_none_when_empty():
    agent = DefaultTacticalAgent()
    s = _state()
    assert agent.choose_permanent_to_tap(s, 0, []) is None


def test_choose_legend_keep_picks_first():
    agent = DefaultTacticalAgent()
    s = _state()
    assert agent.choose_legend_keep(s, 0, [10, 11, 12]) == 10


def test_choose_replacement_order_returns_identity_ordering():
    """CR 616.1 default: identity ordering matches dispatcher order."""
    agent = DefaultTacticalAgent()
    s = _state()
    candidates = ["fake_repl_0", "fake_repl_1", "fake_repl_2"]
    assert agent.choose_replacement_order(
        candidates, s, affected_player_id=0,
    ) == (0, 1, 2)


def test_choose_replacement_order_empty_candidates():
    agent = DefaultTacticalAgent()
    s = _state()
    assert agent.choose_replacement_order(
        [], s, affected_player_id=0,
    ) == ()


def test_choose_mulligan_delegates_to_heuristic():
    """Default tactical mulligan uses the extreme-only heuristic."""
    agent = DefaultTacticalAgent()
    s = _state()
    # Empty hand is degenerate; the heuristic returns False at the
    # max mull count anyway. We just need to drive the call to cover
    # the import-and-return path.
    result = agent.choose_mulligan(s, 0, hand=[], mulls_taken=0)
    assert isinstance(result, bool)


def test_choose_bottom_delegates_to_heuristic():
    """Default tactical bottom uses the heuristic-bottom-choice util."""
    agent = DefaultTacticalAgent()
    s = _state()

    # Build a tiny hand: heuristic_bottom_choice consumes objects with
    # ``.printing.card_types`` and ``.printing.mana_cost.total``. We
    # build minimal stand-ins; mana_cost.total drives the bottom
    # ordering for non-lands.
    class _Cost:
        def __init__(self, total):
            self._total = total

        def total(self):
            return self._total

    class _Printing:
        def __init__(self, card_types, mv, is_land):
            self.card_types = card_types
            self.mana_cost = _Cost(mv)
            self.is_land = is_land

    class _Card:
        def __init__(self, oid, card_types, mv, is_land=False):
            self.id = oid
            self.printing = _Printing(card_types, mv, is_land)

    hand = [
        _Card(1, ("Creature",), 2),
        _Card(2, ("Creature",), 5),  # highest MV non-land — bottoms first
        _Card(3, ("Land",), 0, is_land=True),
    ]
    bottom = agent.choose_bottom(s, 0, hand=hand, n=1)
    assert bottom == [2]


def test_choose_convoke_creatures_returns_all_candidates():
    """Default tactical convokes every candidate in input order."""
    agent = DefaultTacticalAgent()
    s = _state()
    candidates = [10, 20, 30]
    assert agent.choose_convoke_creatures(
        s, 0, candidates,
        remaining_generic=2, remaining_colored=[],
    ) == [10, 20, 30]


def test_choose_sac_for_mana_returns_ids_in_input_order():
    """Default tactical sac-for-mana hands every candidate id back."""
    agent = DefaultTacticalAgent()
    s = _state()
    candidates = [
        (10, (("R", 1),)),
        (11, (("C", 1),)),
        (12, (("any", 1),)),
    ]
    assert agent.choose_sac_for_mana(
        s, 0, candidates,
        remaining_generic=2, remaining_colored=[],
    ) == [10, 11, 12]


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
