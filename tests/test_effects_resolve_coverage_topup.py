"""Engine-resolve tests for two generic primitives that previously
only had parser-shape coverage:

- ``LookTopNPutOneInHandRestToGraveyard.resolve`` (Commune with Evil
  body, parameterized by ``n``) — the agent picks one of the top ``n``
  cards into hand, the rest go to the graveyard. Three branches: an
  empty library is a no-op; an agent's pick lands in hand; absent
  agent / declined pick falls back to the top card.
- ``ReturnAllCreaturesFromYourGraveyardToBattlefield.resolve``
  (Awakening Hall body) — every creature card in the controller's
  graveyard returns to the battlefield. Non-creature cards are left
  in the graveyard.
"""

from __future__ import annotations


# ---------- LookTopNPutOneInHandRestToGraveyard.resolve ----------

def test_look_top_n_empty_library_is_noop():
    from mtg_bot.effects import LookTopNPutOneInHandRestToGraveyard
    from mtg_bot.game import GameState, Player

    state = GameState(players=[Player(id=0), Player(id=1)])
    LookTopNPutOneInHandRestToGraveyard(n=4).resolve(
        state, controller_id=0, targets=(),
    )
    p = state.player_by_id(0)
    assert p.library == []
    assert p.hand == []
    assert p.graveyard == []


def test_look_top_n_agent_pick_lands_in_hand_rest_to_graveyard():
    from mtg_bot.cards.base import make_creature
    from mtg_bot.effects import LookTopNPutOneInHandRestToGraveyard
    from mtg_bot.game import GameObject, GameState, Player, Zone

    class _PickAgent:
        def choose_card_from_library(self, state, controller_id, ids):
            # Always pick the second id in the candidate list.
            return ids[1]

        # Stubbed unused choice methods for the agent protocol.
        def choose_yes_no(self, state, controller_id, prompt):
            return True

        def choose_target(self, state, controller_id, options):
            return options[0] if options else None

        def choose_mode(self, state, controller_id, descriptions):
            return 0

        def choose_modes(self, state, controller_id, descriptions):
            return [0]

        def choose_sacrifice(self, state, controller_id, ids):
            return ids[0]

    a_pr = make_creature("A", "{1}", 1, 1)
    b_pr = make_creature("B", "{1}", 1, 1)
    c_pr = make_creature("C", "{1}", 1, 1)
    a = GameObject(id=1, printing=a_pr, owner_id=0, controller_id=0,
                   zone=Zone.LIBRARY)
    b = GameObject(id=2, printing=b_pr, owner_id=0, controller_id=0,
                   zone=Zone.LIBRARY)
    c = GameObject(id=3, printing=c_pr, owner_id=0, controller_id=0,
                   zone=Zone.LIBRARY)
    p0 = Player(id=0, agent=_PickAgent())
    p0.library.extend([a, b, c])  # top of library is index 0
    state = GameState(players=[p0, Player(id=1)])

    LookTopNPutOneInHandRestToGraveyard(n=4).resolve(
        state, controller_id=0, targets=(),
    )
    # Library examined was [a, b, c]; agent picked the second id (b).
    assert [card.printing.name for card in p0.hand] == ["B"]
    assert {card.printing.name for card in p0.graveyard} == {"A", "C"}
    assert p0.library == []


def test_look_top_n_no_agent_falls_back_to_top_card():
    from mtg_bot.cards.base import make_creature
    from mtg_bot.effects import LookTopNPutOneInHandRestToGraveyard
    from mtg_bot.game import GameObject, GameState, Player, Zone

    a_pr = make_creature("A", "{1}", 1, 1)
    b_pr = make_creature("B", "{1}", 1, 1)
    a = GameObject(id=1, printing=a_pr, owner_id=0, controller_id=0,
                   zone=Zone.LIBRARY)
    b = GameObject(id=2, printing=b_pr, owner_id=0, controller_id=0,
                   zone=Zone.LIBRARY)
    p0 = Player(id=0)  # no agent
    p0.library.extend([a, b])
    state = GameState(players=[p0, Player(id=1)])
    LookTopNPutOneInHandRestToGraveyard(n=4).resolve(
        state, controller_id=0, targets=(),
    )
    # No agent → top card (a) goes to hand, rest (b) goes to graveyard.
    assert [card.printing.name for card in p0.hand] == ["A"]
    assert [card.printing.name for card in p0.graveyard] == ["B"]


def test_look_top_n_describe_includes_n():
    from mtg_bot.effects import LookTopNPutOneInHandRestToGraveyard

    desc = LookTopNPutOneInHandRestToGraveyard(n=4).describe()
    assert "top 4 cards" in desc
    assert "hand" in desc
    assert "graveyard" in desc


# ---------- ReturnAllCreaturesFromYourGraveyardToBattlefield.resolve ----------

def test_return_all_creatures_moves_only_creatures():
    from mtg_bot.cards.base import make_artifact, make_creature
    from mtg_bot.effects import ReturnAllCreaturesFromYourGraveyardToBattlefield
    from mtg_bot.game import GameObject, GameState, Player, Zone

    creature_a = GameObject(
        id=1, printing=make_creature("Goblin", "{R}", 1, 1),
        owner_id=0, controller_id=0, zone=Zone.GRAVEYARD,
    )
    creature_b = GameObject(
        id=2, printing=make_creature("Bear", "{1}{G}", 2, 2),
        owner_id=0, controller_id=0, zone=Zone.GRAVEYARD,
    )
    artifact = GameObject(
        id=3, printing=make_artifact("Trinket", "{1}"),
        owner_id=0, controller_id=0, zone=Zone.GRAVEYARD,
    )
    p0 = Player(id=0)
    p0.graveyard.extend([creature_a, artifact, creature_b])
    state = GameState(players=[p0, Player(id=1)])

    ReturnAllCreaturesFromYourGraveyardToBattlefield().resolve(
        state, controller_id=0, targets=(),
    )
    # Both creatures moved to battlefield, artifact stays in graveyard.
    bf_names = sorted(o.printing.name for o in state.battlefield)
    assert bf_names == ["Bear", "Goblin"]
    assert [c.printing.name for c in p0.graveyard] == ["Trinket"]


def test_return_all_creatures_empty_graveyard_is_noop():
    from mtg_bot.effects import ReturnAllCreaturesFromYourGraveyardToBattlefield
    from mtg_bot.game import GameState, Player

    state = GameState(players=[Player(id=0), Player(id=1)])
    ReturnAllCreaturesFromYourGraveyardToBattlefield().resolve(
        state, controller_id=0, targets=(),
    )
    assert state.battlefield == []
    assert state.player_by_id(0).graveyard == []


def test_return_all_creatures_describe():
    from mtg_bot.effects import ReturnAllCreaturesFromYourGraveyardToBattlefield

    desc = ReturnAllCreaturesFromYourGraveyardToBattlefield().describe()
    assert "creature" in desc
    assert "graveyard" in desc
    assert "battlefield" in desc
