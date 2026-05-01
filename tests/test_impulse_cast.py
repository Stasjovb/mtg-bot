"""Tests for impulse-cast plumbing (cards exiled with
playable_from_exile_this_turn) + Territorial Bruntar landfall exile +
Memorial Vault sacrifice exile."""

from mtg_bot import legal_moves
from mtg_bot.actions import CastSpell, apply_action
from mtg_bot.agents import RandomAgent
from mtg_bot.cards import BASIC_LANDS, SYNTHETIC_CREATURES
from mtg_bot.effects import TerritorialBruntarLandfallEffect
from mtg_bot.effects.formulas import MVOfCostPaidObjectPlus
from mtg_bot.effects.generic import ExileTopXOfLibraryMayPlayThisTurn
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.turn import Step, run_cleanup_step
from tests._etb_helpers import _legacy_or_inferred_key, _matches_legacy_key

from mtg_bot.cards.source import get_active_source

_PRINTINGS = get_active_source().get_printings()


def _new_state():
    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    state.active_player_idx = 0
    state.priority_player_idx = 0
    state.step = Step.PRECOMBAT_MAIN
    return state


def _put(state, printing, owner_id=0):
    obj = state.new_object(printing, owner_id, Zone.BATTLEFIELD)
    state.battlefield.append(obj)
    return obj


# -----------------------
# Impulse-cast plumbing
# -----------------------


def test_playable_from_exile_offers_cast_action():
    state = _new_state()
    # Put enough mana to cast Wild Bear {1}{G}.
    _put(state, BASIC_LANDS["Forest"])
    _put(state, BASIC_LANDS["Forest"])
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.EXILE,
    )
    bear.playable_from_exile_this_turn = True
    state.players[0].exile.append(bear)
    legal = [a for a in legal_moves(state) if isinstance(a, CastSpell)]
    assert any(a.card_id == bear.id for a in legal)


def test_cleanup_clears_playable_from_exile_flag():
    state = _new_state()
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.EXILE,
    )
    bear.playable_from_exile_this_turn = True
    state.players[0].exile.append(bear)
    run_cleanup_step(state)
    assert bear.playable_from_exile_this_turn is False


def test_cast_from_exile_with_impulse_flag_resolves():
    state = _new_state()
    _put(state, BASIC_LANDS["Forest"])
    _put(state, BASIC_LANDS["Forest"])
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.EXILE,
    )
    bear.playable_from_exile_this_turn = True
    state.players[0].exile.append(bear)
    apply_action(state, 0, CastSpell(bear.id))
    # Bear is now on the stack or battlefield; either way, out of exile.
    assert bear not in state.players[0].exile


# -----------------------
# Territorial Bruntar landfall
# -----------------------


def test_bruntar_landfall_exiles_lands_until_nonland_and_marks_playable():
    state = _new_state()
    p = state.players[0]
    # Stack library: [Forest, Plains, Wild Bear, Island]. Bruntar digs
    # past the lands to the Bear.
    for printing in [
        BASIC_LANDS["Forest"], BASIC_LANDS["Plains"],
        SYNTHETIC_CREATURES["Wild Bear"], BASIC_LANDS["Island"],
    ]:
        c = state.new_object(printing, 0, Zone.LIBRARY)
        p.library.append(c)
    TerritorialBruntarLandfallEffect().resolve(state, 0, ())
    exiled = p.exile
    # Two lands + one Bear exiled; Bear has the impulse flag.
    assert len(exiled) == 3
    bear_in_exile = next(
        (c for c in exiled if c.printing.name == "Wild Bear"), None
    )
    assert bear_in_exile is not None
    assert bear_in_exile.playable_from_exile_this_turn is True


def test_bruntar_landfall_empty_library_stops_gracefully():
    state = _new_state()
    TerritorialBruntarLandfallEffect().resolve(state, 0, ())
    assert state.players[0].exile == []


def test_bruntar_describe():
    d = TerritorialBruntarLandfallEffect().describe()
    assert "exile" in d and "nonland" in d


# -----------------------
# Memorial Vault activated
# -----------------------


def test_memorial_vault_effect_exiles_top_X_and_marks_playable():
    """The generic ``ExileTopXOfLibraryMayPlayThisTurn`` driven by
    ``MVOfCostPaidObjectPlus(constant=1)`` reads the cost-paid
    artifact's MV via ``state.resolving_cost_paid_objects`` and exiles
    1+MV cards, marking each impulse-cast for the turn."""
    state = _new_state()
    p = state.players[0]
    # Simulate a paid MV-4 artifact (Memorial Vault itself, MV 4).
    paid = state.new_object(_PRINTINGS["Memorial Vault"], 0, Zone.GRAVEYARD)
    p.graveyard.append(paid)
    state.resolving_cost_paid_objects = (paid,)
    # Stock library with seven cards.
    for _ in range(7):
        c = state.new_object(BASIC_LANDS["Plains"], 0, Zone.LIBRARY)
        p.library.append(c)
    try:
        ExileTopXOfLibraryMayPlayThisTurn(
            amount=MVOfCostPaidObjectPlus(constant=1),
        ).resolve(state, 0, ())
    finally:
        state.resolving_cost_paid_objects = ()
    # 5 cards exiled (1 + MV 4), all marked playable.
    assert len(p.exile) == 5
    for c in p.exile:
        assert c.playable_from_exile_this_turn is True


def test_memorial_vault_describe():
    d = ExileTopXOfLibraryMayPlayThisTurn(
        amount=MVOfCostPaidObjectPlus(constant=1),
    ).describe()
    assert "exile" in d and "X cards" in d


# -----------------------
# Printing metadata
# -----------------------


def test_territorial_bruntar_printing_has_landfall_trigger():
    t = _PRINTINGS["Territorial Bruntar"]
    triggers = {_legacy_or_inferred_key(ab) for ab in t.triggered_abilities}
    assert "landfall" in triggers


def test_memorial_vault_printing_has_activated_ability():
    v = _PRINTINGS["Memorial Vault"]
    assert len(v.activated_abilities) == 1
    cost = v.activated_abilities[0].cost
    assert cost.tap_self
    # Oracle: "Sacrifice another artifact" — strict artifact-only cost,
    # not the wider creature-or-artifact variant.
    assert cost.sacrifice_another_artifact
    assert not cost.sacrifice_another_creature_or_artifact
