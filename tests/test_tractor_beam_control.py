"""Tractor Beam's continuous-while-attached control swap.

Audit-found bug: pre-fix Tractor Beam wired the ETB tap and the
don't-untap rider but silently dropped the "You control enchanted
permanent" clause — so even with Tractor Beam attached to an
opponent's creature, the opponent still controlled the creature.
Now wired via two new GameObject fields
(``swapped_controller_by_aura_id`` + ``controller_id_before_aura_swap``)
and a reversion hook in ``move_off_battlefield`` that restores the
prior controller when the aura leaves play.
"""

from mtg_bot.actions import (
    _trigger_etb_abilities, apply_aura_static_grants_on_attach,
    drain_stack,
)
from mtg_bot.agents import Agent
from mtg_bot.cards import EOE_CREATURES, EOE_SPELLS, SYNTHETIC_CREATURES
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.turn import (
    Step, destroy, move_off_battlefield, run_untap_step, tap_permanent,
)


class _PickFirst(Agent):
    """Picks the first legal target — deterministic for ETB triggers."""

    def choose_target(self, state, player_id, legal_targets):
        return legal_targets[0] if legal_targets else None


def _new_state():
    state = GameState()
    state.players.append(Player(id=0, agent=_PickFirst()))
    state.players.append(Player(id=1, agent=_PickFirst()))
    state.active_player_idx = 0
    state.priority_player_idx = 0
    state.step = Step.PRECOMBAT_MAIN
    return state


def _put(state, printing, owner_id=0):
    obj = state.new_object(printing, owner_id, Zone.BATTLEFIELD)
    state.battlefield.append(obj)
    return obj


def _attach_and_etb(state, aura, target):
    """Attach an aura to a target, apply static grants (the
    continuous-while-attached statics — control swap, etc.), then
    fire and drain the ETB triggers. Mirrors the order in
    ``_resolve_top_of_stack``: statics first, ETB triggers second."""
    aura.attached_to = target.id
    apply_aura_static_grants_on_attach(state, aura, target, aura.controller_id)
    _trigger_etb_abilities(state, aura)
    drain_stack(state)


# -----------------------
# ETB control swap
# -----------------------


def test_etb_grants_control_of_enchanted_creature():
    """When Tractor Beam attaches to an opponent's creature, P0 (the
    aura's controller) gains control of that creature."""
    state = _new_state()
    aura = _put(state, EOE_SPELLS["Tractor Beam"], owner_id=0)
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=1)
    assert bear.controller_id == 1

    _attach_and_etb(state, aura, bear)

    assert bear.controller_id == 0
    assert bear.controller_id_before_aura_swap == 1
    assert bear.swapped_controller_by_aura_id == aura.id
    # ETB tap fired too.
    assert bear.tapped is True


def test_etb_no_swap_when_already_self_controlled():
    """If Tractor Beam attaches to a creature you already control, no
    swap is recorded (prevents weird revert chains if the aura later
    leaves)."""
    state = _new_state()
    aura = _put(state, EOE_SPELLS["Tractor Beam"], owner_id=0)
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)

    _attach_and_etb(state, aura, bear)

    assert bear.controller_id == 0
    assert bear.swapped_controller_by_aura_id is None
    assert bear.controller_id_before_aura_swap is None
    assert bear.tapped is True


# -----------------------
# Reversion when the aura leaves
# -----------------------


def test_aura_destroyed_reverts_controller():
    state = _new_state()
    aura = _put(state, EOE_SPELLS["Tractor Beam"], owner_id=0)
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=1)
    _attach_and_etb(state, aura, bear)
    assert bear.controller_id == 0

    destroy(state, aura)

    assert bear.controller_id == 1
    assert bear.swapped_controller_by_aura_id is None
    assert bear.controller_id_before_aura_swap is None


def test_aura_exiled_reverts_controller():
    """Same revert when the aura is exiled (not just destroyed)."""
    state = _new_state()
    aura = _put(state, EOE_SPELLS["Tractor Beam"], owner_id=0)
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=1)
    _attach_and_etb(state, aura, bear)
    assert bear.controller_id == 0

    move_off_battlefield(state, aura, destination="exile")

    assert bear.controller_id == 1


def test_enchanted_creature_destroyed_aura_falls_off_no_revert_needed():
    """If the enchanted creature dies, the aura goes with it. There's
    no orphaned permanent to revert — the post-death cleanup just
    works."""
    state = _new_state()
    aura = _put(state, EOE_SPELLS["Tractor Beam"], owner_id=0)
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=1)
    _attach_and_etb(state, aura, bear)

    destroy(state, bear)

    # Both gone. The aura was buried by move_off_battlefield's
    # falling-aura logic. No crashes.
    assert aura not in state.battlefield
    assert bear not in state.battlefield


# -----------------------
# Don't-untap rider still works (regression)
# -----------------------


def test_dont_untap_during_controllers_untap_step():
    """Tractor Beam's don't-untap rider is wired via
    ``attached_prevents_untap=True``. After P0 takes control of an
    opponent's creature, on P0's untap step the creature stays tapped
    (since enchanted-permanent's controller is now P0)."""
    state = _new_state()
    aura = _put(state, EOE_SPELLS["Tractor Beam"], owner_id=0)
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=1)
    _attach_and_etb(state, aura, bear)
    # Tap the bear (already tapped from ETB, but be explicit).
    if not bear.tapped:
        tap_permanent(state, bear)
    assert bear.tapped is True
    # P0's untap step.
    state.active_player_idx = 0
    run_untap_step(state)
    # Bear should still be tapped — Tractor Beam prevents untap.
    assert bear.tapped is True


# -----------------------
# Targeting filter (regression: enchant creature OR Spacecraft)
# -----------------------


def test_printing_is_aura_with_correct_etb_and_static_flags():
    """Pin the printing's shape so future refactors don't drop the
    fix."""
    p = EOE_SPELLS["Tractor Beam"]
    assert p.is_aura is True
    assert p.attached_prevents_untap is True
    assert p.attached_grants_control is True
    assert len(p.triggered_abilities) == 1
    assert p.triggered_abilities[0].trigger == "etb"


# -----------------------
# Static-vs-triggered ordering (the user-reported observation)
# -----------------------


def test_control_swap_applies_before_etb_tap_resolves():
    """The 'You control enchanted permanent' clause is a STATIC
    ability — continuous, not stack-based — so it must take effect
    the instant Tractor Beam enters attached, BEFORE the ETB tap
    trigger resolves. Pin that ordering by inspecting state at the
    intermediate moment (aura on the battlefield, ETB trigger on
    the stack but not yet resolved)."""
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.game import StackItem

    state = _new_state()
    aura = state.new_object(EOE_SPELLS["Tractor Beam"], 0, Zone.STACK)
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=1)
    bear.summoning_sick = False
    bear.tapped = False  # untapped pre-cast

    # Place Tractor Beam on the stack as a cast spell targeting bear.
    state.stack.append(StackItem(
        source=aura,
        controller_id=0,
        targets=(("creature", bear.id),),
    ))
    # Resolve the cast: aura enters attached, static control swap
    # applies, then ETB tap is pushed onto the stack.
    resolve_top_of_stack(state)

    # *** Intermediate state — the user-reported expectation. ***
    # Tractor Beam is on the battlefield, attached to bear, AND the
    # control swap has already taken effect. The ETB tap is queued
    # on the stack but has NOT resolved yet.
    assert aura in state.battlefield
    assert aura.attached_to == bear.id
    assert bear.controller_id == 0, (
        "static control swap must apply before ETB tap resolves"
    )
    assert bear.controller_id_before_aura_swap == 1
    assert bear.swapped_controller_by_aura_id == aura.id
    # ETB tap is on the stack but bear is still UNTAPPED.
    assert any(
        item.ability is not None and item.source.id == aura.id
        for item in state.stack
    )
    assert bear.tapped is False, (
        "ETB tap should not have resolved yet — it's on the stack"
    )

    # Now drain the ETB tap. After this, bear is tapped AND still
    # under P0's control (the static persists).
    drain_stack(state)
    assert bear.tapped is True
    assert bear.controller_id == 0
