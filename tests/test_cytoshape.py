"""Cytoshape (Saviors of Kamigawa, simplified) — UEOT layer-1
copy effect.

The architectural payoff over Clone (which uses
``expires_at=None``): Cytoshape's layer-1 entry has
``expires_at="cleanup"``, so the printing mutation must REVERT
when the entry expires. Wired via the new
``game.revert_printing_if_no_layer1_copies`` helper called from:

- ``run_cleanup_step``: after ``expire_continuous_effects(
  "cleanup")`` drops UEOT layer-1 entries, walk the battlefield
  and revert printing on any object whose original_printing is
  set but no layer-1 copies remain.
- ``move_off_battlefield``: when a permanent leaves play, its
  layered effects stop applying. The leaving object's printing
  reverts so future reanimation enters as the printed object.

Tests:
- Cytoshape resolves: target's printing becomes the source's,
  ``original_printing`` snapshotted, layer-1 registry entry
  written.
- Cleanup expires the entry → printing reverts.
- Cytoshape on a Lignified creature: Lignify's layer-6/7b
  effects are keyed by target_id and persist across the printing
  swap. Result: Lignify still applies.
- Cytoshape, then target dies: printing reverts on the leaving
  object via ``move_off_battlefield``.
- Two Cytoshapes on same target: both write entries; printing
  is the most-recent target's printing; both expire at cleanup
  → revert.
- Cytoshape fizzles when both targets are the same creature.
"""

from __future__ import annotations

from mtg_bot.actions import (
    apply_aura_static_grants_on_attach, drain_stack,
    resolve_top_of_stack,
)
from mtg_bot.agents import Agent
from mtg_bot.cards import SYNTHETIC_CREATURES
from mtg_bot.cards.demo_layers import CYTOSHAPE, LIGNIFY
from mtg_bot.effects.generic import CytoshapeBecomeCopyUEOT
from mtg_bot.game import (
    GameState, Player, StackItem, Zone,
    effective_keywords, effective_power, effective_subtypes,
    effective_toughness,
)
from mtg_bot.turn import Step, destroy, run_cleanup_step


class _PickFirst(Agent):
    def choose_target(self, state, player_id, legal_targets):
        return legal_targets[0] if legal_targets else None

    def choose_discard(self, state, player_id, hand_card_ids):
        return hand_card_ids[0] if hand_card_ids else -1


def _new_state() -> GameState:
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


def _attach(state, aura, target):
    aura.attached_to = target.id
    apply_aura_static_grants_on_attach(state, aura, target, aura.controller_id)


# ---------- Printing shape ----------


def test_cytoshape_printing_shape():
    assert CYTOSHAPE.is_sorcery is True
    from mtg_bot.effects.generic import CytoshapeBecomeCopyUEOT
    assert isinstance(CYTOSHAPE.spell_effect, CytoshapeBecomeCopyUEOT)


def test_cytoshape_not_in_eoe_pool():
    from mtg_bot.cards.registry import NONLAND_POOL, all_printings
    assert "Cytoshape" not in NONLAND_POOL
    assert "Cytoshape" not in all_printings()


# ---------- Resolution ----------


def test_cytoshape_resolves_target_becomes_copy_of_source():
    """Target creature's printing becomes the source creature's
    printing. ``original_printing`` is snapshotted. A layer-1
    registry entry with ``expires_at="cleanup"`` is written."""
    state = _new_state()
    sentinel = _put(state, SYNTHETIC_CREATURES["Sky Sentinel"], owner_id=0)
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    state.resolving_source = None  # the resolving spell is the sorcery
    CytoshapeBecomeCopyUEOT().resolve(
        state, controller_id=0,
        targets=(("creature", sentinel.id), ("creature", bear.id)),
    )

    # Sentinel now has Bear's printing (2/2 vanilla).
    assert sentinel.printing.name == "Wild Bear"
    assert sentinel.original_printing.name == "Sky Sentinel"
    assert effective_power(state, sentinel) == 2
    assert effective_toughness(state, sentinel) == 2
    assert "flying" not in effective_keywords(state, sentinel)
    # Layer-1 registry entry.
    entries = [
        ce for ce in state.continuous_effects
        if ce.layer == 1 and ce.kind == "is_copy"
        and ce.target_id == sentinel.id
    ]
    assert len(entries) == 1
    assert entries[0].expires_at == "cleanup"


def test_cytoshape_fizzles_when_targets_are_same():
    """Cytoshape requires "another target creature" — fizzles if
    both targets point to the same creature."""
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)

    CytoshapeBecomeCopyUEOT().resolve(
        state, controller_id=0,
        targets=(("creature", bear.id), ("creature", bear.id)),
    )

    # No mutation, no entry.
    assert bear.original_printing is None
    assert bear.printing.name == "Wild Bear"
    assert state.continuous_effects == []


# ---------- Cleanup revert ----------


def test_cleanup_reverts_cytoshape_printing():
    """At cleanup, the layer-1 entry expires and the target's
    printing reverts to ``original_printing`` (which is then
    cleared)."""
    state = _new_state()
    sentinel = _put(state, SYNTHETIC_CREATURES["Sky Sentinel"], owner_id=0)
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    CytoshapeBecomeCopyUEOT().resolve(
        state, 0,
        (("creature", sentinel.id), ("creature", bear.id)),
    )
    assert sentinel.printing.name == "Wild Bear"

    run_cleanup_step(state)

    # Sentinel reverts to its printed self.
    assert sentinel.printing.name == "Sky Sentinel"
    assert sentinel.original_printing is None
    assert effective_power(state, sentinel) == 1
    assert effective_toughness(state, sentinel) == 3
    assert "flying" in effective_keywords(state, sentinel)
    # Registry entry is gone.
    assert not any(
        ce.layer == 1 and ce.kind == "is_copy"
        for ce in state.continuous_effects
    )


# ---------- Leave-play revert ----------


def test_cytoshape_target_destroyed_printing_reverts():
    """When a Cytoshape'd creature leaves the battlefield, its
    printing reverts via ``move_off_battlefield``. Important for
    reanimation: the graveyard card has its printed self, so
    coming back doesn't carry the copy effect."""
    state = _new_state()
    sentinel = _put(state, SYNTHETIC_CREATURES["Sky Sentinel"], owner_id=0)
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    CytoshapeBecomeCopyUEOT().resolve(
        state, 0,
        (("creature", sentinel.id), ("creature", bear.id)),
    )
    assert sentinel.printing.name == "Wild Bear"

    destroy(state, sentinel)

    # Now in graveyard with its printed self.
    assert sentinel.printing.name == "Sky Sentinel"
    assert sentinel.original_printing is None


# ---------- Composition with Lignify ----------


def test_cytoshape_on_lignified_creature_lignify_still_applies():
    """Cytoshape changes the printing; Lignify's registry entries
    are keyed by target_id and persist. Lignified Sentinel is
    still 0/4 Treefolk no abilities, even after Cytoshape changes
    its printing to Wild Bear's.
    """
    state = _new_state()
    sentinel = _put(state, SYNTHETIC_CREATURES["Sky Sentinel"], owner_id=0)
    aura = _put(state, LIGNIFY, owner_id=0)
    _attach(state, aura, sentinel)
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    # Pre-Cytoshape: Lignified Sentinel is 0/4 Treefolk no abilities.
    assert effective_power(state, sentinel) == 0
    assert effective_toughness(state, sentinel) == 4
    assert "Treefolk" in effective_subtypes(state, sentinel)

    state.resolving_source = None
    CytoshapeBecomeCopyUEOT().resolve(
        state, 0,
        (("creature", sentinel.id), ("creature", bear.id)),
    )

    # Sentinel's printing is now Wild Bear's, but Lignify still
    # applies on top (target_id-keyed).
    assert sentinel.printing.name == "Wild Bear"
    assert effective_power(state, sentinel) == 0
    assert effective_toughness(state, sentinel) == 4
    assert "Treefolk" in effective_subtypes(state, sentinel)
    assert effective_keywords(state, sentinel) == frozenset()


def test_cytoshape_copies_printing_not_lignify_modifications():
    """Cytoshape copies the SOURCE's printing (CR 706 copiable
    values), NOT the source's effective layered state. So
    Cytoshape pointing AT a Lignified bear should copy the bare
    Bear printing — Lignify on the source doesn't transfer.
    """
    state = _new_state()
    target_sentinel = _put(state, SYNTHETIC_CREATURES["Sky Sentinel"], owner_id=0)
    source_bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    aura = _put(state, LIGNIFY, owner_id=0)
    _attach(state, aura, source_bear)
    # Lignified bear is 0/4 Treefolk no abilities at the moment.

    state.resolving_source = None
    CytoshapeBecomeCopyUEOT().resolve(
        state, 0,
        (("creature", target_sentinel.id),
         ("creature", source_bear.id)),
    )

    # Sentinel's printing is now Bear (printed 2/2 vanilla), NOT
    # Lignify-modified. Sentinel's existing layered effects (none)
    # don't apply, so result is a fresh 2/2 Bear.
    assert target_sentinel.printing.name == "Wild Bear"
    assert effective_power(state, target_sentinel) == 2
    assert effective_toughness(state, target_sentinel) == 2
    assert effective_keywords(state, target_sentinel) == frozenset()


# ---------- Multiple Cytoshapes ----------


def test_two_cytoshapes_on_same_target_most_recent_wins():
    """Two Cytoshapes on the same target. Layer-1 within-layer
    timestamp ordering: most recent wins. After both, target's
    printing matches the SECOND copy source. Both entries expire
    at cleanup."""
    state = _new_state()
    target = _put(state, SYNTHETIC_CREATURES["Sky Sentinel"], owner_id=0)
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    sentinel2 = _put(state, SYNTHETIC_CREATURES["Sky Sentinel"], owner_id=0)

    state.resolving_source = None
    # First: copy bear.
    CytoshapeBecomeCopyUEOT().resolve(
        state, 0,
        (("creature", target.id), ("creature", bear.id)),
    )
    assert target.printing.name == "Wild Bear"

    # Second: copy a different sentinel. Latest write wins —
    # printing becomes sentinel2's.
    CytoshapeBecomeCopyUEOT().resolve(
        state, 0,
        (("creature", target.id), ("creature", sentinel2.id)),
    )
    assert target.printing.name == "Sky Sentinel"

    # Both entries exist, target's original_printing held since
    # the first mutation.
    entries = [
        ce for ce in state.continuous_effects
        if ce.layer == 1 and ce.kind == "is_copy"
        and ce.target_id == target.id
    ]
    assert len(entries) == 2

    run_cleanup_step(state)

    # Both expired; printing reverted to original (Sky Sentinel —
    # ironically the same name as sentinel2's printing, but the
    # original_printing snapshot is the printed identity).
    assert target.original_printing is None


# ---------- Full cast pipeline ----------


def test_cytoshape_resolves_via_full_stack_pipeline():
    """Drive Cytoshape through the cast pipeline and stack
    resolution to confirm no plumbing got missed."""
    state = _new_state()
    sentinel = _put(state, SYNTHETIC_CREATURES["Sky Sentinel"], owner_id=0)
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    cytoshape = state.new_object(CYTOSHAPE, 0, Zone.STACK)

    state.stack.append(StackItem(
        source=cytoshape,
        controller_id=0,
        targets=(("creature", sentinel.id), ("creature", bear.id)),
    ))
    resolve_top_of_stack(state)
    drain_stack(state)

    assert sentinel.printing.name == "Wild Bear"
    assert any(
        ce.layer == 1 and ce.kind == "is_copy"
        and ce.target_id == sentinel.id
        for ce in state.continuous_effects
    )
