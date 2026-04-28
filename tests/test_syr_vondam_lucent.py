"""Tests for Syr Vondam, the Lucent — ETB/attacks team pump granting
deathtouch to other creatures you control, plus the new exclude_source
flag on PumpCreaturesYouControlUntilEOT."""

from mtg_bot.actions import drain_stack, put_into_battlefield, resolve_top_of_stack
from mtg_bot.agents import RandomAgent
from mtg_bot.cards import SYNTHETIC_CREATURES
from mtg_bot.combat import declare_attackers
from mtg_bot.effects import PumpCreaturesYouControlUntilEOT
from mtg_bot.game import GameState, Player, Zone, effective_keywords
from tests._etb_helpers import _legacy_or_inferred_key, _matches_legacy_key

from mtg_bot.cards.source import get_active_source

_PRINTINGS = get_active_source().get_printings()


def _new_state():
    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    return state


# -----------------------
# exclude_source flag on PumpCreaturesYouControlUntilEOT
# -----------------------


def test_exclude_source_skips_the_resolving_permanent():
    state = _new_state()
    source = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(source)
    other = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(other)
    state.resolving_source = source
    try:
        PumpCreaturesYouControlUntilEOT(
            power_bonus=1, exclude_source=True,
        ).resolve(state, 0, ())
    finally:
        state.resolving_source = None
    assert source.temp_power_bonus == 0
    assert other.temp_power_bonus == 1


def test_exclude_source_without_flag_pumps_everyone():
    state = _new_state()
    a = state.new_object(SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD)
    state.battlefield.append(a)
    b = state.new_object(SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD)
    state.battlefield.append(b)
    state.resolving_source = a
    try:
        PumpCreaturesYouControlUntilEOT(power_bonus=1).resolve(state, 0, ())
    finally:
        state.resolving_source = None
    assert a.temp_power_bonus == 1 and b.temp_power_bonus == 1


def test_exclude_source_describe_changes_wording():
    plain = PumpCreaturesYouControlUntilEOT(power_bonus=1).describe()
    other = PumpCreaturesYouControlUntilEOT(
        power_bonus=1, exclude_source=True,
    ).describe()
    assert "other creatures" in other
    assert "other" not in plain


# -----------------------
# Syr Vondam, the Lucent integration
# -----------------------


def test_vondam_etb_pumps_other_creatures_not_self():
    state = _new_state()
    ally = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(ally)
    vondam = state.new_object(
        _PRINTINGS["Syr Vondam, the Lucent"], 0, Zone.HAND,
    )
    state.players[0].hand.append(vondam)
    put_into_battlefield(state, vondam, controller_id=0)
    while state.stack:
        resolve_top_of_stack(state)
    assert ally.temp_power_bonus == 1
    assert "deathtouch" in effective_keywords(state, ally)
    # Vondam herself unchanged by the trigger (she already has deathtouch
    # from her printed keywords, but temp_power_bonus stays 0).
    assert vondam.temp_power_bonus == 0


def test_vondam_attacks_pumps_other_creatures():
    state = _new_state()
    vondam = state.new_object(
        _PRINTINGS["Syr Vondam, the Lucent"], 0, Zone.BATTLEFIELD,
    )
    vondam.summoning_sick = False
    state.battlefield.append(vondam)
    ally = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    ally.summoning_sick = False
    state.battlefield.append(ally)
    declare_attackers(state, [vondam.id])
    drain_stack(state)
    assert ally.temp_power_bonus == 1
    assert "deathtouch" in effective_keywords(state, ally)
    assert vondam.temp_power_bonus == 0


def test_vondam_printing_metadata():
    v = _PRINTINGS["Syr Vondam, the Lucent"]
    assert "Legendary" in v.supertypes
    assert "deathtouch" in v.keywords
    assert "lifelink" in v.keywords
    triggers = {_legacy_or_inferred_key(ab) for ab in v.triggered_abilities}
    assert "etb" in triggers
    assert "attacks" in triggers
