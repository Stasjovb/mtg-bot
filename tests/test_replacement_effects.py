"""Tests for replacement effects:
- Starfield Vocalist: extra ETB trigger firing
- Moonlit Meditation: first-tokens-each-turn become copies
- Tractor Beam: attached permanent doesn't untap
"""

from mtg_bot.actions import put_into_battlefield, resolve_top_of_stack
from mtg_bot.agents import Agent, RandomAgent
from mtg_bot.cards import BASIC_LANDS, EOE_CREATURES, EOE_SPELLS, SYNTHETIC_CREATURES, TOKEN_PRINTINGS
from mtg_bot.effects import CreateToken
from mtg_bot.game import GameState, Player, Zone, etb_trigger_multiplier
from mtg_bot.turn import run_cleanup_step, run_untap_step


class _PickFirstAgent(Agent):
    def choose_target(self, state, player_id, legal_targets):
        return legal_targets[0] if legal_targets else None


def _new_state():
    state = GameState()
    state.players.append(Player(id=0, agent=_PickFirstAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    state.active_player_idx = 0
    return state


def _put(state, printing, owner_id=0, attached_to=None):
    obj = state.new_object(printing, owner_id, Zone.BATTLEFIELD)
    if attached_to is not None:
        obj.attached_to = attached_to
    state.battlefield.append(obj)
    return obj


# -----------------------
# etb_trigger_multiplier
# -----------------------


def test_multiplier_default_is_one():
    state = _new_state()
    assert etb_trigger_multiplier(state, 0) == 1


def test_multiplier_adds_one_per_starfield():
    state = _new_state()
    _put(state, EOE_CREATURES["Starfield Vocalist"])
    assert etb_trigger_multiplier(state, 0) == 2
    _put(state, EOE_CREATURES["Starfield Vocalist"])
    assert etb_trigger_multiplier(state, 0) == 3


def test_multiplier_scoped_by_controller():
    state = _new_state()
    _put(state, EOE_CREATURES["Starfield Vocalist"], owner_id=1)
    assert etb_trigger_multiplier(state, 0) == 1
    assert etb_trigger_multiplier(state, 1) == 2


# -----------------------
# Starfield: ETB trigger fires extra time
# -----------------------


def test_starfield_doubles_own_creature_etb_trigger():
    """With Starfield on the bf, Haliya's ETB counter-pump fires twice
    → 2 counters distributed across the target pool."""
    state = _new_state()
    sf = _put(state, EOE_CREATURES["Starfield Vocalist"])
    haliya = state.new_object(
        EOE_CREATURES["Haliya, Ascendant Cadet"], 0, Zone.HAND,
    )
    put_into_battlefield(state, haliya, controller_id=0)
    while state.stack:
        resolve_top_of_stack(state)
    # Haliya's ETB fires twice; each puts +1/+1 on the first legal
    # target the PickFirst agent picks. Across the 2 controller-side
    # creatures on the battlefield, 2 counters land in total.
    total = haliya.plus_one_counters + sf.plus_one_counters
    assert total == 2


def test_starfield_doubles_landfall_trigger():
    """Icetill Explorer's landfall mills 1. With Starfield, it mills 2
    per land ETB."""
    state = _new_state()
    _put(state, EOE_CREATURES["Starfield Vocalist"])
    _put(state, EOE_CREATURES["Icetill Explorer"])
    # Seed library.
    for _ in range(5):
        c = state.new_object(BASIC_LANDS["Plains"], 0, Zone.LIBRARY)
        state.players[0].library.append(c)
    # Play a land — landfall fires twice.
    from mtg_bot.actions import PlayLand, apply_action
    from mtg_bot.turn import Step
    state.step = Step.PRECOMBAT_MAIN
    state.priority_player_idx = 0
    land = state.new_object(BASIC_LANDS["Forest"], 0, Zone.HAND)
    state.players[0].hand.append(land)
    gy_before = len(state.players[0].graveyard)
    apply_action(state, 0, PlayLand(land.id))
    assert len(state.players[0].graveyard) == gy_before + 2


# -----------------------
# Moonlit Meditation: first token creation becomes copies
# -----------------------


def test_moonlit_replaces_first_token_with_copy():
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"])
    _put(state, EOE_SPELLS["Moonlit Meditation"], attached_to=bear.id)
    # Create a Drone token — normally a 1/1 flying artifact. With
    # Moonlit, the token becomes a copy of the enchanted bear (2/2).
    CreateToken(token_printing=TOKEN_PRINTINGS["Drone"]).resolve(
        state, 0, (),
    )
    tokens = [
        o for o in state.battlefield
        if o.controller_id == 0 and "Token" in o.printing.supertypes
    ]
    assert len(tokens) == 1
    assert tokens[0].printing.name == "Wild Bear"
    assert 0 in state.players_who_created_tokens_this_turn


def test_moonlit_only_replaces_first_time_each_turn():
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"])
    _put(state, EOE_SPELLS["Moonlit Meditation"], attached_to=bear.id)
    CreateToken(token_printing=TOKEN_PRINTINGS["Drone"]).resolve(
        state, 0, (),
    )
    # Second creation this turn — no replacement.
    CreateToken(token_printing=TOKEN_PRINTINGS["Drone"]).resolve(
        state, 0, (),
    )
    drones = [
        o for o in state.battlefield if o.printing.name == "Drone"
    ]
    bears = [
        o for o in state.battlefield
        if o.printing.name == "Wild Bear"
        and "Token" in o.printing.supertypes
    ]
    assert len(drones) == 1
    assert len(bears) == 1


def test_moonlit_does_not_replace_without_attachment():
    state = _new_state()
    # Moonlit on battlefield but NOT attached (edge case).
    _put(state, EOE_SPELLS["Moonlit Meditation"])
    CreateToken(token_printing=TOKEN_PRINTINGS["Drone"]).resolve(
        state, 0, (),
    )
    drones = [o for o in state.battlefield if o.printing.name == "Drone"]
    assert len(drones) == 1


def test_cleanup_resets_moonlit_gate():
    state = _new_state()
    state.players_who_created_tokens_this_turn.add(0)
    run_cleanup_step(state)
    assert state.players_who_created_tokens_this_turn == set()


# -----------------------
# Tractor Beam: attached permanent doesn't untap
# -----------------------


def test_tractor_beam_prevents_untap():
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"])
    bear.tapped = True
    _put(state, EOE_SPELLS["Tractor Beam"], attached_to=bear.id)
    run_untap_step(state)
    assert bear.tapped is True


def test_untap_works_for_non_tractor_creature():
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"])
    bear.tapped = True
    run_untap_step(state)
    assert bear.tapped is False


def test_tractor_beam_printing_has_no_untap_flag():
    t = EOE_SPELLS["Tractor Beam"]
    assert t.attached_prevents_untap is True


def test_moonlit_meditation_printing_has_replace_flag():
    m = EOE_SPELLS["Moonlit Meditation"]
    assert m.replaces_first_tokens_with_copies is True


def test_starfield_printing_has_extra_etb_trigger():
    s = EOE_CREATURES["Starfield Vocalist"]
    assert s.extra_etb_trigger == 1
