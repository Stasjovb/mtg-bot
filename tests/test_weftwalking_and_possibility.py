"""Tests for Weftwalking's ETB shuffle-hand-and-grave + draw-7 and
Possibility Technician's ETB / Kavu-observer + persistent
cast-from-exile clause."""

from mtg_bot.actions import CastSpell, PlayLand
from mtg_bot.agents import RandomAgent
from mtg_bot.cards import BASIC_LANDS, EOE_CREATURES, EOE_SPELLS, SYNTHETIC_CREATURES
from mtg_bot.effects import PossibilityTechnicianETBEffect, WeftwalkingETBEffect
from mtg_bot.game import GameState, Player, Zone


def _new_state():
    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    return state


def _stock_library(state, player_id, n, printing=None):
    printing = printing or BASIC_LANDS["Plains"]
    p = state.players[player_id]
    for _ in range(n):
        c = state.new_object(printing, player_id, Zone.LIBRARY)
        p.library.append(c)


# -----------------------
# Weftwalking ETB
# -----------------------


def test_weftwalking_shuffles_hand_and_graveyard_into_library_and_draws_7():
    state = _new_state()
    p = state.players[0]
    # Hand has 2, graveyard has 3, library has 5.
    for _ in range(2):
        c = state.new_object(SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.HAND)
        p.hand.append(c)
    for _ in range(3):
        c = state.new_object(BASIC_LANDS["Plains"], 0, Zone.GRAVEYARD)
        p.graveyard.append(c)
    _stock_library(state, 0, 5)
    WeftwalkingETBEffect().resolve(state, 0, ())
    # Hand contains exactly 7 cards (the draw). Graveyard is empty.
    # Library started with 5 + 2 (hand) + 3 (gy) = 10; drew 7 → 3 left.
    assert len(p.hand) == 7
    assert len(p.graveyard) == 0
    assert len(p.library) == 3


def test_weftwalking_describe():
    d = WeftwalkingETBEffect().describe()
    assert "shuffle" in d and "seven" in d


def test_weftwalking_printing_has_etb():
    w = EOE_SPELLS["Weftwalking"]
    triggers = {ab.trigger for ab in w.triggered_abilities}
    assert "etb" in triggers


# -----------------------
# Possibility Technician ETB
# -----------------------


def test_possibility_exiles_top_card_and_marks_persistent_kavu_gate():
    state = _new_state()
    _stock_library(state, 0, 3)
    PossibilityTechnicianETBEffect().resolve(state, 0, ())
    p = state.players[0]
    assert len(p.exile) == 1
    # The exiled card is marked persistently playable while the
    # controller controls a Kavu — NOT the this-turn-only impulse flag.
    assert p.exile[0].play_from_exile_requires_kavu is True
    assert p.exile[0].playable_from_exile_this_turn is False


def test_possibility_empty_library_noop():
    state = _new_state()
    PossibilityTechnicianETBEffect().resolve(state, 0, ())
    assert state.players[0].exile == []


def test_possibility_describe():
    d = PossibilityTechnicianETBEffect().describe()
    # Describe must reflect the persistence + Kavu-control gate, not
    # the old "this turn" impulse phrasing.
    assert "exile" in d
    assert "Kavu" in d
    assert "this turn" not in d


def test_possibility_printing_has_subtypes_etb_kavu_observer_and_warp():
    pt = EOE_CREATURES["Possibility Technician"]
    assert pt.warp_cost_str == "{R}"
    assert "Kavu" in pt.subtypes
    triggers = {ab.trigger for ab in pt.triggered_abilities}
    # Both halves of "this creature or another Kavu you control enters"
    # are wired: self-ETB (etb) AND the Kavu-observer trigger.
    assert "etb" in triggers
    assert "kavu_you_control_enters" in triggers


# ---- Kavu-observer trigger (clause a) ----


def test_kavu_observer_fires_when_another_kavu_enters_under_technician():
    """When Possibility Technician is on the battlefield and another
    Kavu enters under the same controller, the observer trigger
    (kavu_you_control_enters) must fire — resolving directly via
    _fire_kavu_enters_triggers — so a card gets exiled with the
    persistent Kavu-gated flag set. The entering Kavu's own ETB also
    goes on the stack but isn't part of this assertion."""
    from mtg_bot.actions import put_into_battlefield

    state = _new_state()
    _stock_library(state, 0, 5)
    p = state.players[0]
    # Place Technician on the battlefield (skip its own ETB since
    # we're measuring the observer firing on a different Kavu's ETB).
    tech = state.new_object(
        EOE_CREATURES["Possibility Technician"], 0, Zone.BATTLEFIELD
    )
    state.battlefield.append(tech)
    # Snapshot exile-size pre-observer.
    before = len(p.exile)
    # Another Kavu enters: reuse the Technician printing.
    other_kavu = state.new_object(
        EOE_CREATURES["Possibility Technician"], 0, Zone.STACK
    )
    put_into_battlefield(state, other_kavu, 0)
    # Observer fires immediately (not via stack). Exactly one new card
    # is exiled, flagged for Kavu-gated cast.
    assert len(p.exile) == before + 1
    assert p.exile[-1].play_from_exile_requires_kavu is True


def test_kavu_observer_does_not_fire_for_non_kavu_creature():
    """A non-Kavu creature entering must NOT trigger the Technician's
    observer (filter is Kavu-only, not "any creature")."""
    from mtg_bot.actions import put_into_battlefield

    state = _new_state()
    _stock_library(state, 0, 5)
    p = state.players[0]
    tech = state.new_object(
        EOE_CREATURES["Possibility Technician"], 0, Zone.BATTLEFIELD
    )
    state.battlefield.append(tech)
    # SYNTHETIC_CREATURES["Wild Bear"] has no Kavu subtype.
    bear = state.new_object(SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.STACK)
    put_into_battlefield(state, bear, 0)
    # Exile remains empty — the Technician's own ETB already fired
    # earlier (we skipped that), and Wild Bear is not a Kavu.
    assert p.exile == []


# ---- Persistence clause (clause b) ----


def test_persistent_cast_from_exile_legal_only_while_controlling_kavu():
    """The exiled card must be legal to cast from exile only when the
    controller currently controls at least one Kavu — and across turns,
    not just the turn it was exiled."""
    import mtg_bot.legal as legal_mod
    import mtg_bot.turn as turn_mod

    state = _new_state()
    # Stock exile with a castable creature flagged for Kavu-gated cast.
    target = state.new_object(SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.EXILE)
    target.play_from_exile_requires_kavu = True
    state.players[0].exile.append(target)
    # Controller has plenty of mana available (Wild Bear is {1}{G}, so
    # untapped Forests cover the cost via can_pay_cost).
    for _ in range(5):
        land = state.new_object(BASIC_LANDS["Forest"], 0, Zone.BATTLEFIELD)
        state.battlefield.append(land)
    # Make it sorcery-timing on player 0's main phase with empty stack.
    state.active_player_idx = 0
    state.priority_player_idx = 0
    state.step = turn_mod.Step.PRECOMBAT_MAIN
    # No Kavu on battlefield: cast must NOT be offered.
    actions = legal_mod.legal_actions(state, 0)
    assert not any(
        isinstance(a, CastSpell) and a.card_id == target.id for a in actions
    )
    # Add a Kavu to the battlefield (reuse the Technician printing).
    kavu = state.new_object(
        EOE_CREATURES["Possibility Technician"], 0, Zone.BATTLEFIELD
    )
    state.battlefield.append(kavu)
    actions = legal_mod.legal_actions(state, 0)
    assert any(
        isinstance(a, CastSpell) and a.card_id == target.id for a in actions
    )
    # Persistence: the flag survives a cleanup step (which clears the
    # this-turn impulse flag). Simulate by calling the cleanup handler
    # directly and re-checking the flag is still set.
    target.playable_from_exile_this_turn = False  # baseline
    turn_mod.run_cleanup_step(state)
    assert target.play_from_exile_requires_kavu is True
    actions = legal_mod.legal_actions(state, 0)
    assert any(
        isinstance(a, CastSpell) and a.card_id == target.id for a in actions
    )


def test_persistent_flag_cleared_on_cast_from_exile():
    """Once the card is cast from exile, the persistent flag must be
    cleared so the same GameObject doesn't double-cast."""
    from mtg_bot.actions import _cast_spell
    from mtg_bot.game import ManaCoin

    state = _new_state()
    state.active_player_idx = 0
    state.priority_player_idx = 0
    target = state.new_object(SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.EXILE)
    target.play_from_exile_requires_kavu = True
    state.players[0].exile.append(target)
    # Pre-fill the mana pool with Wild Bear's cost ({1}{G}).
    state.players[0].mana_pool.extend(
        [ManaCoin(color="G"), ManaCoin(color="C")]
    )
    _cast_spell(state, 0, target.id)
    # Spell goes onto the stack; the persistent flag is consumed on
    # the cast-from-exile path so a re-cast can't happen.
    assert target.play_from_exile_requires_kavu is False
    assert target not in state.players[0].exile
