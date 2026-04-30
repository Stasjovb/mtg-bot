"""Tests for Stellar Sights batch 7: Lotus Field + Plaza of Heroes.

Nesting Grounds stays as a stand-in — its "move a counter from A to B"
ability needs dual-target (two permanents picked per activation)
which the engine doesn't model yet.
"""

from mtg_bot.actions import ActivateAbility, apply_action, resolve_top_of_stack
from mtg_bot.agents import Agent
from mtg_bot.cards import BASIC_LANDS
from mtg_bot.cards.base import make_creature
from mtg_bot.effects import SacrificeNLandsYouControl
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.turn import Step
from tests._etb_helpers import _matches_legacy_key

from mtg_bot.cards.source import get_active_source

_PRINTINGS = get_active_source().get_printings()


class _PickFirstAgent(Agent):
    """Test agent that picks the first option for every callback.

    ``forced_color`` lets a test pin the mana color for
    AddNManaOfChosenColor — defaults to None (use first option).
    """

    def __init__(self, forced_color: str | None = None) -> None:
        self.forced_color = forced_color

    def choose_target(self, state, player_id, legal_targets):
        return legal_targets[0] if legal_targets else None

    def choose_sacrifice(self, state, player_id, legal_ids):
        return legal_ids[0] if legal_ids else None

    def choose_mana_color(self, state, player_id, options):
        if self.forced_color is not None and self.forced_color in options:
            return self.forced_color
        return options[0]


def _new_state(p0_color: str | None = None):
    state = GameState()
    state.players.append(
        Player(id=0, agent=_PickFirstAgent(forced_color=p0_color))
    )
    state.players.append(Player(id=1, agent=_PickFirstAgent()))
    state.active_player_idx = 0
    state.priority_player_idx = 0
    state.step = Step.PRECOMBAT_MAIN
    return state


def _put(state, printing, owner_id=0):
    obj = state.new_object(printing, owner_id, Zone.BATTLEFIELD)
    state.battlefield.append(obj)
    return obj


# -----------------------
# SacrificeNLandsYouControl primitive
# -----------------------


def test_sacrifice_n_lands_sacs_two_and_excludes_source():
    state = _new_state()
    source = _put(state, _PRINTINGS["Lotus Field"])
    for _ in range(3):
        _put(state, BASIC_LANDS["Mountain"])
    state.resolving_source = source
    try:
        SacrificeNLandsYouControl(count=2).resolve(state, 0, ())
    finally:
        state.resolving_source = None
    # Two Mountains gone; source survives.
    remaining_mountains = [
        o for o in state.battlefield
        if o.printing.name == "Mountain"
    ]
    assert len(remaining_mountains) == 1
    assert source in state.battlefield


def test_sacrifice_n_lands_handles_fewer_available_than_count():
    """If the controller has only 1 land besides the source, sac all
    of them and stop — don't raise."""
    state = _new_state()
    source = _put(state, _PRINTINGS["Lotus Field"])
    _put(state, BASIC_LANDS["Mountain"])
    state.resolving_source = source
    try:
        SacrificeNLandsYouControl(count=3).resolve(state, 0, ())
    finally:
        state.resolving_source = None
    assert not any(
        o.printing.name == "Mountain" for o in state.battlefield
    )


def test_sacrifice_n_lands_describe():
    assert SacrificeNLandsYouControl(count=1).describe() == "sacrifice a land"
    assert "2 lands" in SacrificeNLandsYouControl(count=2).describe()


# -----------------------
# Lotus Field — ETB + tap for mana
# -----------------------


def test_lotus_field_metadata():
    p = _PRINTINGS["Lotus Field"]
    assert "hexproof" in p.keywords
    assert p.enters_tapped is True
    assert len(p.triggered_abilities) == 1
    assert _matches_legacy_key(p.triggered_abilities[0], "etb")
    assert len(p.activated_abilities) == 1


def test_lotus_field_etb_sacrifices_two_lands():
    from mtg_bot.actions import put_into_battlefield

    state = _new_state()
    # Stage Lotus Field in hand and have the player play it via
    # put_into_battlefield to fire the ETB trigger.
    for _ in range(3):
        _put(state, BASIC_LANDS["Mountain"])
    lotus = state.new_object(
        _PRINTINGS["Lotus Field"], 0, Zone.HAND,
    )
    put_into_battlefield(state, lotus, 0)
    while state.stack:
        resolve_top_of_stack(state)
    # Two Mountains sacrificed; Lotus Field survives.
    remaining_mountains = [
        o for o in state.battlefield if o.printing.name == "Mountain"
    ]
    assert len(remaining_mountains) == 1
    assert lotus in state.battlefield


def test_lotus_field_taps_for_three_of_one_chosen_color_default():
    """Default test agent picks the first color option (W); pool must
    contain three W coins, none of any other color."""
    state = _new_state()
    lotus = _put(state, _PRINTINGS["Lotus Field"])
    apply_action(
        state, 0, ActivateAbility(source_id=lotus.id, ability_index=0),
    )
    pool = state.players[0].mana_pool
    assert len(pool) == 3
    assert all(c.color == "W" for c in pool)
    # Crucially, no "any" wildcard coins — Lotus Field is NOT five-color.
    assert not any(c.color == "any" for c in pool)


def test_lotus_field_taps_for_three_of_chosen_color_blue():
    """Forcing the agent to pick U yields three U coins (single color,
    not three independent picks)."""
    state = _new_state(p0_color="U")
    lotus = _put(state, _PRINTINGS["Lotus Field"])
    apply_action(
        state, 0, ActivateAbility(source_id=lotus.id, ability_index=0),
    )
    pool = state.players[0].mana_pool
    assert [c.color for c in pool] == ["U", "U", "U"]


def test_lotus_field_taps_for_three_of_chosen_color_green():
    """Different color choice → three G coins, none mixed in."""
    state = _new_state(p0_color="G")
    lotus = _put(state, _PRINTINGS["Lotus Field"])
    apply_action(
        state, 0, ActivateAbility(source_id=lotus.id, ability_index=0),
    )
    pool = state.players[0].mana_pool
    assert len(pool) == 3
    assert all(c.color == "G" for c in pool)


# -----------------------
# Plaza of Heroes — flagship ability
# -----------------------


def test_plaza_of_heroes_metadata():
    p = _PRINTINGS["Plaza of Heroes"]
    assert "Legendary" in p.supertypes
    # Plaza has four activated abilities: three mana abilities
    # (baseline {C}, legendary-spell-restricted any, legendary-
    # permanent-ability-restricted any) plus the {3},{T},Exile
    # flagship pump (exile_self cost atom, not sacrifice_self).
    assert len(p.activated_abilities) == 4
    flagship = p.activated_abilities[3]
    # Oracle text reads "Exile this land" — the cost is exile_self, not
    # sacrifice_self (Plaza goes to exile, not the graveyard).
    assert flagship.cost.exile_self is True
    assert flagship.cost.sacrifice_self is False


def test_plaza_of_heroes_grants_hexproof_and_indestructible_ueot():
    state = _new_state()
    plaza = _put(state, _PRINTINGS["Plaza of Heroes"])
    # Mana for {3}.
    for _ in range(3):
        _put(state, BASIC_LANDS["Mountain"])
    bear = _put(state, make_creature("Test Bear", "{1}{G}", 2, 2))
    apply_action(
        state, 0, ActivateAbility(source_id=plaza.id, ability_index=3),
    )
    while state.stack:
        resolve_top_of_stack(state)
    assert plaza not in state.battlefield
    from mtg_bot.game import effective_keywords
    assert "hexproof" in effective_keywords(state, bear)
    assert "indestructible" in effective_keywords(state, bear)


# -----------------------
# Progress marker
# -----------------------


