"""Shared fixtures for the cube W/G creature-bucket tests (not collected).

Builds on ``tests._spells_b_helpers`` (``ScriptedAgent`` / ``make_state``
/ ``add``): helpers to put arbitrary printings into zones, drain the
stack, run a combat's declare-attackers step and fire the end step's
delayed triggers.
"""

from __future__ import annotations

from mtg_bot.actions import DeclareAttackers, apply_action, resolve_top_of_stack
from mtg_bot.cards import make_creature
from mtg_bot.cards.parser.source import OracleParserCardSource
from mtg_bot.game import Zone
from mtg_bot.turn import Step, run_delayed_end_step_triggers
from tests._spells_b_helpers import (  # noqa: F401  (re-exported)
    ScriptedAgent,
    add,
    add_lands,
    cast_and_resolve,
    make_state,
)

_CUBE: dict = {}


def cube() -> dict:
    """The cube pool's parsed printings (built once per session)."""
    if not _CUBE:
        _CUBE.update(OracleParserCardSource(pool="cube").get_printings())
    return _CUBE


def put(state, pid: int, printing, zone: Zone = Zone.BATTLEFIELD):
    """Put a ``printing`` (or a cube card name) owned by ``pid`` into
    ``zone`` (battlefield permanents are not summoning sick)."""
    if isinstance(printing, str):
        printing = cube()[printing]
    obj = state.new_object(printing, owner_id=pid, zone=zone)
    p = state.player_by_id(pid)
    if zone == Zone.BATTLEFIELD:
        obj.summoning_sick = False
        state.battlefield.append(obj)
    else:
        {
            Zone.HAND: p.hand, Zone.LIBRARY: p.library,
            Zone.GRAVEYARD: p.graveyard, Zone.EXILE: p.exile,
        }[zone].append(obj)
    return obj


def bear(name: str = "Bear", cost: str = "{1}{G}", power: int = 2,
         toughness: int = 2, **kwargs):
    return make_creature(name, cost, power, toughness, **kwargs)


def drain(state) -> None:
    while state.stack:
        resolve_top_of_stack(state)


def attack(state, pid: int, attacker_ids) -> None:
    """Declare ``attacker_ids`` as ``pid``'s attackers and resolve the
    resulting attack triggers."""
    state.step = Step.DECLARE_ATTACKERS
    apply_action(state, pid, DeclareAttackers(attacker_ids=frozenset(attacker_ids)))
    drain(state)


def end_step(state) -> None:
    """Enter the end step: push the delayed triggers and resolve them."""
    state.step = Step.END
    run_delayed_end_step_triggers(state)
    drain(state)
