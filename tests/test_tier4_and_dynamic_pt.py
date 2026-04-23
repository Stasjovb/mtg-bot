"""Tests for Exalted Sunborn (token doubling), Harmonious Grovestrider
and Emissary Escort (dynamic P/T)."""

from mtg_bot.agents import RandomAgent
from mtg_bot.cards import (
    BASIC_LANDS,
    EOE_CREATURES,
    EOE_SPELLS,
    SYNTHETIC_CREATURES,
    TOKEN_PRINTINGS,
)
from mtg_bot.effects import CreateToken
from mtg_bot.game import (
    GameState,
    Player,
    Zone,
    effective_power,
    effective_toughness,
)


def _new_state():
    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    return state


# -----------------------
# Exalted Sunborn: token doubling
# -----------------------


def test_create_token_without_doubler_creates_one():
    state = _new_state()
    effect = CreateToken(
        token_printing=TOKEN_PRINTINGS["Robot"], count=1,
    )
    effect.resolve(state, 0, ())
    robots = [o for o in state.battlefield if o.printing.name == "Robot"]
    assert len(robots) == 1


def test_exalted_sunborn_doubles_token_creation():
    state = _new_state()
    # Put Exalted Sunborn on battlefield (is_token_doubler=True).
    sunborn = state.new_object(
        EOE_CREATURES["Exalted Sunborn"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(sunborn)
    effect = CreateToken(
        token_printing=TOKEN_PRINTINGS["Robot"], count=1,
    )
    effect.resolve(state, 0, ())
    robots = [
        o for o in state.battlefield
        if o.printing.name == "Robot" and o.controller_id == 0
    ]
    assert len(robots) == 2


def test_two_doublers_quadruple_token_creation():
    """Two Exalted Sunborns → 4x tokens (2^2)."""
    state = _new_state()
    for _ in range(2):
        s = state.new_object(
            EOE_CREATURES["Exalted Sunborn"], 0, Zone.BATTLEFIELD,
        )
        state.battlefield.append(s)
    effect = CreateToken(
        token_printing=TOKEN_PRINTINGS["Robot"], count=1,
    )
    effect.resolve(state, 0, ())
    robots = [
        o for o in state.battlefield
        if o.printing.name == "Robot" and o.controller_id == 0
    ]
    assert len(robots) == 4


def test_exalted_sunborn_doesnt_double_opponents_tokens():
    state = _new_state()
    # P0 controls the Sunborn.
    sunborn = state.new_object(
        EOE_CREATURES["Exalted Sunborn"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(sunborn)
    # P1 creates tokens.
    effect = CreateToken(
        token_printing=TOKEN_PRINTINGS["Robot"], count=1,
    )
    effect.resolve(state, 1, ())
    # Only 1 token should be created under P1's control.
    p1_robots = [
        o for o in state.battlefield
        if o.printing.name == "Robot" and o.controller_id == 1
    ]
    assert len(p1_robots) == 1


def test_exalted_sunborn_count_3_doubled_to_6():
    state = _new_state()
    sunborn = state.new_object(
        EOE_CREATURES["Exalted Sunborn"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(sunborn)
    effect = CreateToken(
        token_printing=TOKEN_PRINTINGS["Robot"], count=3,
    )
    effect.resolve(state, 0, ())
    robots = [
        o for o in state.battlefield
        if o.printing.name == "Robot" and o.controller_id == 0
    ]
    assert len(robots) == 6


def test_exalted_sunborn_printing_has_flag():
    assert EOE_CREATURES["Exalted Sunborn"].is_token_doubler is True


# -----------------------
# Harmonious Grovestrider dynamic P/T
# -----------------------


def test_grovestrider_zero_lands_is_zero_over_zero():
    state = _new_state()
    grove = state.new_object(
        EOE_SPELLS["Harmonious Grovestrider"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(grove)
    assert effective_power(state, grove) == 0
    assert effective_toughness(state, grove) == 0


def test_grovestrider_three_lands_is_three_over_three():
    state = _new_state()
    grove = state.new_object(
        EOE_SPELLS["Harmonious Grovestrider"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(grove)
    for _ in range(3):
        l = state.new_object(BASIC_LANDS["Forest"], 0, Zone.BATTLEFIELD)
        state.battlefield.append(l)
    assert effective_power(state, grove) == 3
    assert effective_toughness(state, grove) == 3


def test_grovestrider_ignores_opponent_lands():
    state = _new_state()
    grove = state.new_object(
        EOE_SPELLS["Harmonious Grovestrider"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(grove)
    # Opponent has 5 lands, we have 2.
    for _ in range(5):
        l = state.new_object(BASIC_LANDS["Forest"], 1, Zone.BATTLEFIELD)
        state.battlefield.append(l)
    for _ in range(2):
        l = state.new_object(BASIC_LANDS["Plains"], 0, Zone.BATTLEFIELD)
        state.battlefield.append(l)
    assert effective_power(state, grove) == 2


# -----------------------
# Emissary Escort dynamic power bonus
# -----------------------


def test_emissary_escort_no_other_artifacts_is_printed():
    state = _new_state()
    escort = state.new_object(
        EOE_CREATURES["Emissary Escort"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(escort)
    # No other artifacts → X = 0, P/T = 0/4 (printed).
    assert effective_power(state, escort) == 0
    assert effective_toughness(state, escort) == 4


def test_emissary_escort_takes_greatest_mv_among_other_artifacts():
    state = _new_state()
    escort = state.new_object(
        EOE_CREATURES["Emissary Escort"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(escort)
    # Add an artifact with MV 3 and one with MV 5.
    mv3 = state.new_object(
        EOE_SPELLS["Memorial Vault"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(mv3)
    # Synthesizer Labship cost is {U} = MV 1. Find something bigger.
    mv5 = state.new_object(
        EOE_SPELLS["Virulent Silencer"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(mv5)
    # Memorial Vault is {3}{R} = MV 4. Virulent Silencer is {3} = MV 3.
    # max = 4.
    assert effective_power(state, escort) == 4


def test_emissary_escort_excludes_self_from_artifact_pool():
    state = _new_state()
    escort = state.new_object(
        EOE_CREATURES["Emissary Escort"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(escort)
    # Emissary Escort is itself an artifact with MV 2 ({1}{U}). If we
    # included self, X = 2; excluded, X = 0.
    assert effective_power(state, escort) == 0


def test_emissary_escort_excludes_opponent_artifacts():
    state = _new_state()
    escort = state.new_object(
        EOE_CREATURES["Emissary Escort"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(escort)
    opp_artifact = state.new_object(
        EOE_SPELLS["Memorial Vault"], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(opp_artifact)
    # Opponent's MV-4 artifact doesn't count.
    assert effective_power(state, escort) == 0


def test_emissary_escort_printing_has_formula():
    assert EOE_CREATURES["Emissary Escort"].dynamic_pt_formula == (
        "emissary_escort"
    )
