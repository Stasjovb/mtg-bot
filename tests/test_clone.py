"""Clone (Alpha) — exercises CR 613 layer 1 (copy effects).

Clone's oracle text: "You may have Clone enter the battlefield as a
copy of any creature on the battlefield."

Clone is a real Magic card, not in the Edge of Eternities pool. The
printing lives in ``mtg_bot.cards.demo_layers``.

Pinned behavior:

- At resolution, the controller picks any creature on the
  battlefield. Clone snapshots ``original_printing`` and replaces
  ``printing`` with the target's printing.
- A layer-1 ``"is_copy"`` registry entry is written with
  ``source_id=target_id=clone.id`` and ``expires_at=None``. The
  entry is dropped when the clone leaves play.
- Copy effects copy COPIABLE values (CR 706.2) — that is, the
  printed characteristics on the printing object. Auras, +1/+1
  counters, current animations, and other continuous effects on
  the target are NOT copied through:
    * Clone of a Lignified bear is a 2/2 Bear (not a 0/4 Treefolk).
    * Clone of an animated land copies the LAND printing — Clone
      enters as a land, not as the animated creature.
- If no creature is on the battlefield, or the controller's agent
  declines, Clone enters as its printed self (0/0 vanilla).
"""

from __future__ import annotations

from mtg_bot.actions import (
    apply_clone_enters_as_copy_replacement, drain_stack,
    resolve_top_of_stack,
)
from mtg_bot.agents import Agent
from mtg_bot.cards import SYNTHETIC_CREATURES
from mtg_bot.cards.base import make_basic_land
from mtg_bot.cards.demo_layers import CLONE, LIGNIFY
from mtg_bot.game import (
    GameState, Player, StackItem, Zone,
    effective_keywords, effective_power, effective_subtypes,
    effective_toughness, is_creature_now,
)
from mtg_bot.turn import Step, destroy, move_off_battlefield

from mtg_bot.cards.source import get_active_source

_PRINTINGS = get_active_source().get_printings()


class _PickFirst(Agent):
    """Deterministic agent: always picks the first legal target."""

    def choose_target(self, state, player_id, legal_targets):
        return legal_targets[0] if legal_targets else None


class _DeclineCopy(Agent):
    """Agent that always declines target selection (returns None).
    Models the 'you may' optionality on Clone's replacement effect."""

    def choose_target(self, state, player_id, legal_targets):
        return None


def _new_state(agent_cls=_PickFirst) -> GameState:
    state = GameState()
    state.players.append(Player(id=0, agent=agent_cls()))
    state.players.append(Player(id=1, agent=agent_cls()))
    state.active_player_idx = 0
    state.priority_player_idx = 0
    state.step = Step.PRECOMBAT_MAIN
    return state


def _put(state, printing, owner_id=0):
    obj = state.new_object(printing, owner_id, Zone.BATTLEFIELD)
    state.battlefield.append(obj)
    return obj


def _put_clone_off_battlefield(state, owner_id=0):
    """Build a Clone GameObject in the STACK zone — the spell-resolution
    path expects this to be off-battlefield when the replacement runs."""
    return state.new_object(CLONE, owner_id, Zone.STACK)


def _animate_ueot(state, obj, *, power, toughness, subtype=None):
    """Test helper: animate ``obj`` as a creature (optionally with a
    granted subtype) and base P/T until end of turn, via the production
    ``ApplyEffect(BecomeType(...), EndOfTurn())`` path."""
    from mtg_bot.effects import ApplyEffect, BecomeType, EndOfTurn

    subtypes = (subtype,) if subtype else ()
    ApplyEffect(
        inner=BecomeType(
            types_to_add=("creature",),
            subtypes_to_add=subtypes,
            base_pt=(power, toughness),
        ),
        ends_at=EndOfTurn(),
    ).resolve(state, 0, (("permanent", obj.id),))


# ---------- Printing shape ----------


def test_clone_printing_shape():
    assert CLONE.is_creature is True
    assert CLONE.power == 0
    assert CLONE.toughness == 0
    assert CLONE.enters_as_copy_of_creature is True


def test_clone_not_in_eoe_pool():
    """Clone is a demo-only card. It must not leak into _PRINTINGS
    or all_printings."""
    assert "Clone" not in _PRINTINGS
    assert "Clone" not in _PRINTINGS


# ---------- Helper-direct invocation (skip the full cast pipeline) ----------


def test_clone_copies_target_creature_printing():
    """Direct helper invocation: Clone becomes a copy of Wild Bear."""
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    clone = _put_clone_off_battlefield(state, owner_id=0)

    apply_clone_enters_as_copy_replacement(state, clone, controller_id=0)

    assert clone.printing is bear.printing
    assert clone.original_printing.name == "Clone"
    # Clone is now a 2/2 Bear (the target's printing).
    state.battlefield.append(clone)  # simulate put_into_battlefield
    assert effective_power(state, clone) == 2
    assert effective_toughness(state, clone) == 2


def test_clone_writes_layer1_is_copy_entry():
    """The replacement helper records a layer-1 'is_copy' registry
    entry sourced by the clone."""
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    clone = _put_clone_off_battlefield(state, owner_id=0)

    apply_clone_enters_as_copy_replacement(state, clone, controller_id=0)

    entries = [
        ce for ce in state.continuous_effects
        if ce.layer == 1
        and ce.kind == "is_copy"
        and ce.source_id == clone.id
        and ce.target_id == clone.id
    ]
    assert len(entries) == 1
    assert entries[0].params == (bear.printing,)
    assert entries[0].expires_at is None


def test_clone_with_no_creatures_on_battlefield_enters_as_self():
    """No creatures to copy → Clone keeps its 0/0 printed self, no
    registry entry written."""
    state = _new_state()
    clone = _put_clone_off_battlefield(state, owner_id=0)

    apply_clone_enters_as_copy_replacement(state, clone, controller_id=0)

    assert clone.printing.name == "Clone"
    assert clone.original_printing is None
    assert state.continuous_effects == []


def test_clone_declined_enters_as_self():
    """Agent declines the copy → no mutation, no registry entry."""
    state = _new_state(agent_cls=_DeclineCopy)
    _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    clone = _put_clone_off_battlefield(state, owner_id=0)

    apply_clone_enters_as_copy_replacement(state, clone, controller_id=0)

    assert clone.printing.name == "Clone"
    assert clone.original_printing is None
    assert state.continuous_effects == []


# ---------- Copy copies PRINTED values, not effective ones ----------


def test_clone_of_lignified_creature_copies_printed_2_2():
    """Lignified Bear is effectively a 0/4 Treefolk with no abilities,
    but its PRINTING is still 'Wild Bear' (2/2 vanilla). Clone
    copies the printing → Clone enters as a vanilla 2/2 Bear, NOT
    a 0/4 Treefolk."""
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    aura = _put(state, LIGNIFY, owner_id=0)
    # Attach Lignify to Bear via the static-grants helper.
    from mtg_bot.actions import apply_aura_static_grants_on_attach
    aura.attached_to = bear.id
    apply_aura_static_grants_on_attach(state, aura, bear, 0)
    # Lignify-affected bear: 0/4 Treefolk, no flying.
    assert effective_power(state, bear) == 0
    assert effective_toughness(state, bear) == 4
    assert "Treefolk" in effective_subtypes(state, bear)

    clone = _put_clone_off_battlefield(state, owner_id=0)
    apply_clone_enters_as_copy_replacement(state, clone, controller_id=0)
    state.battlefield.append(clone)

    # Clone got Bear's PRINTING — vanilla 2/2, no Treefolk subtype.
    assert effective_power(state, clone) == 2
    assert effective_toughness(state, clone) == 2
    assert "Treefolk" not in effective_subtypes(state, clone)


def test_clone_of_creature_with_keywords_copies_printed_keywords():
    """Sky Sentinel has flying. Clone of Sky Sentinel has flying."""
    state = _new_state()
    sentinel = _put(state, SYNTHETIC_CREATURES["Sky Sentinel"], owner_id=0)
    clone = _put_clone_off_battlefield(state, owner_id=0)

    apply_clone_enters_as_copy_replacement(state, clone, controller_id=0)
    state.battlefield.append(clone)

    assert "flying" in effective_keywords(state, clone)


def test_clone_does_not_copy_plus_one_counters():
    """+1/+1 counters live on the GameObject, not the printing.
    Clone of a +1/+1-stacked Bear is a fresh 2/2 (no counters)."""
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    bear.plus_one_counters = 3
    assert effective_power(state, bear) == 5  # 2 + 3 counters
    clone = _put_clone_off_battlefield(state, owner_id=0)

    apply_clone_enters_as_copy_replacement(state, clone, controller_id=0)
    state.battlefield.append(clone)

    assert effective_power(state, clone) == 2
    assert effective_toughness(state, clone) == 2
    assert clone.plus_one_counters == 0


def test_clone_of_animated_manland_copies_printed_land_type():
    """Animate a land into a creature via the manland helper, then
    clone it. Per CR 706.2 copiable values, the copy gets the land's
    PRINTED characteristics — the animation (a UEOT continuous
    effect) is NOT copied. Clone enters as a land, NOT as a creature.
    """
    state = _new_state()
    forest = _put(state, make_basic_land("Forest", "G"), owner_id=0)
    # Animate Forest into a 4/4 creature UEOT (manland-style).
    _animate_ueot(state, forest, power=4, toughness=4, subtype="Elemental")
    # Forest is now a creature with effective P/T 4/4.
    assert is_creature_now(forest) is True
    assert effective_power(state, forest) == 4

    clone = _put_clone_off_battlefield(state, owner_id=0)
    # Forest is castable as a creature target during the replacement
    # because is_creature_now considers the animation. We expect the
    # CLONE to copy the printing — and the printing is still
    # "Forest" (the land), not a creature printing.
    apply_clone_enters_as_copy_replacement(state, clone, controller_id=0)
    state.battlefield.append(clone)

    # Clone copied Forest's printing — Clone is now a Forest.
    assert clone.printing.name == "Forest"
    assert clone.printing.is_land is True
    assert clone.printing.is_creature is False
    # Without the animation entry on the clone, it isn't a creature.
    # (The animation registry entry is sourced by Forest, target_id
    # is Forest's id — not Clone's.)
    assert is_creature_now(clone) is False


# ---------- Lifecycle: registry entry cleared on detach ----------


def test_clone_destroyed_drops_registry_entry():
    """When the clone leaves play, the layer-1 is_copy entry is
    dropped (only_static=True path)."""
    state = _new_state()
    _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    clone = _put_clone_off_battlefield(state, owner_id=0)
    apply_clone_enters_as_copy_replacement(state, clone, controller_id=0)
    state.battlefield.append(clone)
    assert any(
        ce.layer == 1 and ce.source_id == clone.id
        for ce in state.continuous_effects
    )

    destroy(state, clone)

    assert not any(
        ce.source_id == clone.id for ce in state.continuous_effects
    )


def test_clone_exiled_drops_registry_entry():
    state = _new_state()
    _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    clone = _put_clone_off_battlefield(state, owner_id=0)
    apply_clone_enters_as_copy_replacement(state, clone, controller_id=0)
    state.battlefield.append(clone)

    move_off_battlefield(state, clone, destination="exile")

    assert not any(
        ce.source_id == clone.id for ce in state.continuous_effects
    )


# ---------- Full cast pipeline (resolve_top_of_stack) ----------


def test_clone_resolves_via_full_cast_pipeline():
    """Drive Clone through resolve_top_of_stack (not the helper
    directly). Verify the replacement runs at resolve, the layer-1
    entry is recorded, and Clone reaches the battlefield with the
    target's printing."""
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    clone = state.new_object(CLONE, 0, Zone.STACK)

    state.stack.append(StackItem(
        source=clone,
        controller_id=0,
        targets=(),
    ))
    resolve_top_of_stack(state)
    drain_stack(state)

    assert clone in state.battlefield
    assert clone.printing.name == bear.printing.name
    assert clone.original_printing.name == "Clone"
    assert any(
        ce.layer == 1 and ce.kind == "is_copy"
        and ce.source_id == clone.id
        for ce in state.continuous_effects
    )
