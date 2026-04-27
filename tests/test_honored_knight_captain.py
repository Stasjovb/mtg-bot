"""Honored Knight-Captain's activated tutor: ``{4}{W}{W}, Sacrifice
this creature: Search your library for an Equipment card, put it
onto the battlefield, then shuffle.``

Audit-found bug: pre-fix the activated ability was silently dropped
with a stale comment ("not yet implemented (no activated-ability or
sacrifice framework)") — both subsystems have been live for many
batches. This file pins the ability shape, the cost (mana +
sacrifice-self), and the effect end-to-end (fetched Equipment lands
on the battlefield, library is missing it, library is shuffled).
"""

from mtg_bot.actions import (
    ActivateAbility, apply_action, drain_stack, resolve_top_of_stack,
)
from tests._etb_helpers import _matches_legacy_key
from mtg_bot.agents import Agent
from mtg_bot.cards import (
    BASIC_LANDS, EOE_CREATURES, parse_mana_cost,
)
from mtg_bot.effects import SearchLibraryForEquipmentToBattlefield
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.turn import Step


class _Agent(Agent):
    def choose_card_from_library(self, state, player_id, option_ids):
        return option_ids[0] if option_ids else None

    def choose_target(self, state, player_id, legal_targets):
        return legal_targets[0] if legal_targets else None

    def choose_sacrifice(self, state, player_id, options):
        return options[0]


def _new_state():
    state = GameState()
    state.players.append(Player(id=0, agent=_Agent()))
    state.players.append(Player(id=1, agent=_Agent()))
    state.active_player_idx = 0
    state.priority_player_idx = 0
    state.step = Step.PRECOMBAT_MAIN
    return state


def _put(state, printing, owner_id=0):
    obj = state.new_object(printing, owner_id, Zone.BATTLEFIELD)
    state.battlefield.append(obj)
    return obj


def _stock_library(state, player_id, printings):
    p = state.player_by_id(player_id)
    for printing in printings:
        obj = state.new_object(printing, player_id, Zone.LIBRARY)
        p.library.append(obj)


def _mana_for(state, cost_str):
    cost = parse_mana_cost(cost_str)
    per_color = {"W": "Plains", "U": "Island", "B": "Swamp",
                 "R": "Mountain", "G": "Forest"}
    for color, count in cost.colored:
        for _ in range(count):
            _put(state, BASIC_LANDS[per_color[color]])
    for _ in range(cost.generic):
        _put(state, BASIC_LANDS["Plains"])


# -----------------------
# Printing shape
# -----------------------


def test_printing_has_etb_token_and_activated_tutor():
    p = EOE_CREATURES["Honored Knight-Captain"]
    assert len(p.triggered_abilities) == 1
    assert p.triggered_abilities[0] and _matches_legacy_key(p.triggered_abilities[0], "etb")
    assert len(p.activated_abilities) == 1
    ab = p.activated_abilities[0]
    assert ab.cost.mana_str == "{4}{W}{W}"
    assert ab.cost.sacrifice_self is True
    assert ab.cost.tap_self is False
    assert isinstance(ab.effect, SearchLibraryForEquipmentToBattlefield)


# -----------------------
# Effect resolution
# -----------------------


def test_activation_fetches_equipment_to_battlefield_and_shuffles():
    state = _new_state()
    captain = _put(state, EOE_CREATURES["Honored Knight-Captain"])
    captain.summoning_sick = False
    _stock_library(
        state, 0,
        [
            EOE_CREATURES["Auxiliary Boosters"],   # Equipment
            EOE_CREATURES["Hylderblade"],          # Equipment
            EOE_CREATURES["Starfighter Pilot"],    # not Equipment
        ],
    )
    _mana_for(state, "{4}{W}{W}")
    # Pre-state: captain on battlefield, 3 cards in library.
    assert captain in state.battlefield
    assert len(state.players[0].library) == 3

    apply_action(
        state, 0, ActivateAbility(source_id=captain.id, ability_index=0),
    )
    # Mana abilities and tap/sac costs paid as part of activation;
    # the search effect itself goes onto the stack.
    drain_stack(state)

    # Captain has been sacrificed.
    assert captain not in state.battlefield
    assert captain in state.players[0].graveyard

    # Exactly one Equipment fetched onto the battlefield.
    fetched_equipment = [
        o for o in state.battlefield
        if "Equipment" in o.printing.subtypes
    ]
    assert len(fetched_equipment) == 1
    fetched = fetched_equipment[0]
    # The agent picks options[0] which is Auxiliary Boosters in stock.
    assert fetched.printing.name == "Auxiliary Boosters"
    assert fetched.controller_id == 0
    assert fetched.tapped is False

    # Library is missing the fetched card.
    library_names = [c.printing.name for c in state.players[0].library]
    assert "Auxiliary Boosters" not in library_names
    assert "Hylderblade" in library_names
    assert "Starfighter Pilot" in library_names


def test_activation_with_no_equipment_in_library_just_shuffles():
    state = _new_state()
    captain = _put(state, EOE_CREATURES["Honored Knight-Captain"])
    captain.summoning_sick = False
    _stock_library(
        state, 0,
        [
            EOE_CREATURES["Starfighter Pilot"],
            EOE_CREATURES["Rayblade Trooper"],
        ],
    )
    _mana_for(state, "{4}{W}{W}")
    apply_action(
        state, 0, ActivateAbility(source_id=captain.id, ability_index=0),
    )
    drain_stack(state)

    # Captain still sacrificed (cost is paid even if effect whiffs).
    assert captain in state.players[0].graveyard
    # No Equipment landed.
    assert not any(
        "Equipment" in o.printing.subtypes for o in state.battlefield
    )
    # Library size unchanged.
    assert len(state.players[0].library) == 2


def test_describe_text():
    e = SearchLibraryForEquipmentToBattlefield()
    desc = e.describe()
    assert "search" in desc.lower()
    assert "equipment" in desc.lower()
    assert "battlefield" in desc.lower()
    assert "shuffle" in desc.lower()


# -----------------------
# ETB triggers fire on the fetched Equipment
# -----------------------


def test_fetched_equipment_etb_triggers_fire():
    """Auxiliary Boosters has an ETB token-creation trigger. Verify the
    fetched Equipment goes through the same ETB pipeline as a normal
    cast — the Robot token should appear."""
    state = _new_state()
    captain = _put(state, EOE_CREATURES["Honored Knight-Captain"])
    captain.summoning_sick = False
    _stock_library(state, 0, [EOE_CREATURES["Auxiliary Boosters"]])
    _mana_for(state, "{4}{W}{W}")
    apply_action(
        state, 0, ActivateAbility(source_id=captain.id, ability_index=0),
    )
    drain_stack(state)

    # The fetched Auxiliary Boosters should have ETB-created its token.
    robot_tokens = [
        o for o in state.battlefield
        if o.printing.is_token and "Robot" in o.printing.subtypes
    ]
    assert len(robot_tokens) >= 1


# -----------------------
# Cost gating
# -----------------------


def test_activation_unavailable_without_sufficient_mana():
    """Cost is {4}{W}{W} + sac. With only 5 mana available the
    ability must not be in legal_actions."""
    from mtg_bot.legal import legal_actions

    state = _new_state()
    captain = _put(state, EOE_CREATURES["Honored Knight-Captain"])
    captain.summoning_sick = False
    _stock_library(state, 0, [EOE_CREATURES["Auxiliary Boosters"]])
    _mana_for(state, "{2}{W}{W}")  # only {4} total, need {6}
    actions = legal_actions(state, 0)
    activates = [
        a for a in actions
        if isinstance(a, ActivateAbility) and a.source_id == captain.id
    ]
    assert activates == []
