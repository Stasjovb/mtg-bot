"""Tests for opp capability-based auto-pass at non-active priority
moments.

Cache-and-skip contract:
- When the non-active player has priority AND
  ``_opp_capabilities.opp_can_act`` is False, the adapter returns
  ``[PassPriority()]`` from ``legal_decisions`` WITHOUT invoking
  ``legal.legal_actions``.
- When the non-active player has priority AND opp DOES have an
  instant-speed capability (instant in hand + mana, untapped tapper
  ability, etc.), auto-pass must NOT fire — the full legal-action
  enumeration runs.
- Active player priority is NEVER short-circuited.
- The capability cache is invalidated by ``apply()`` (same hook as
  the legal-actions cache).
- ``training.action_encoding.legal_action_mask`` agrees with the
  adapter — when auto-pass fires, the mask reflects only the PASS
  slot.
"""

from __future__ import annotations

from unittest import mock

import numpy as np

from mtg_bot import legal as legal_mod
from mtg_bot.actions import CastSpell, PassPriority
from mtg_bot.agents import RandomAgent
from mtg_bot.cards import BASIC_LANDS, SYNTHETIC_CREATURES
from mtg_bot.cards.source import get_active_source
from mtg_bot.game import Zone
from mtg_bot.search import MtgGameStateAdapter
from mtg_bot.search._opp_capabilities import (
    opp_can_act, opp_capability_hash,
)
from mtg_bot.simulate import setup_game
from mtg_bot.training import action_encoding as ae


# ---------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------


def _empty_state(seed: int = 42):
    """Two-player setup where each side starts with whatever
    setup_game's deck builder gives them. Tests that need a clean
    slate clear hand/battlefield manually.
    """
    return setup_game(
        [RandomAgent(), RandomAgent()], ["G", "R"], seed=seed,
    )


def _spy_legal_actions(monkeypatch):
    """Patch every entry point so call counting catches all calls.
    Mirrors the helper in ``test_engine_adapter_legal_cache``."""
    real = legal_mod.legal_actions
    spy = mock.Mock(wraps=real)
    monkeypatch.setattr(legal_mod, "legal_actions", spy)
    from mtg_bot.search import engine_adapter as ea_mod
    monkeypatch.setattr(ea_mod, "legal_actions", spy)
    from mtg_bot.training import action_encoding as ae_mod
    monkeypatch.setattr(ae_mod, "legal_actions", spy)
    return spy


def _strip_player_zones(state, player_idx: int) -> None:
    """Empty hand / battlefield / graveyard / exile / mana_pool for
    a single player so capability checks have nothing to fire on."""
    p = state.players[player_idx]
    # Pull our own permanents off the shared battlefield.
    state.battlefield = [
        o for o in state.battlefield
        if o.controller_id != p.id and o.owner_id != p.id
    ]
    p.hand = []
    p.graveyard = []
    p.exile = []
    p.mana_pool = []


def _give_basic_land(
    state, player_idx: int, name: str, *, tapped: bool = False,
) -> None:
    """Drop a basic land onto the battlefield under player_idx's
    control (no mana ability fires)."""
    land = state.new_object(
        BASIC_LANDS[name], owner_id=player_idx, zone=Zone.BATTLEFIELD,
    )
    land.controller_id = player_idx
    land.tapped = tapped
    state.battlefield.append(land)


def _give_synthetic_in_hand(state, player_idx: int, name: str) -> None:
    """Drop a synthetic vanilla creature into the player's hand."""
    p = state.players[player_idx]
    obj = state.new_object(
        SYNTHETIC_CREATURES[name], owner_id=p.id, zone=Zone.HAND,
    )
    p.hand.append(obj)


def _drop_to_opp_priority(adapter):
    """Pass priority once so the non-active player has priority."""
    assert (
        adapter.engine_state.priority_player_idx
        == adapter.engine_state.active_player_idx
    ), "expected fresh adapter at active player's priority"
    adapter.apply(PassPriority())
    assert (
        adapter.engine_state.priority_player_idx
        != adapter.engine_state.active_player_idx
    ), "expected priority to land on opp after one pass"


# ---------------------------------------------------------------------
# opp_can_act unit tests
# ---------------------------------------------------------------------


def test_opp_can_act_false_for_empty_player():
    """A player with empty hand / battlefield / graveyard / exile has
    no capability of any kind."""
    state = _empty_state()
    _strip_player_zones(state, 1)
    assert opp_can_act(state, 1) is False


def test_opp_can_act_true_with_castable_instant_in_hand():
    """Opp has a {2}{R} instant in hand (Bombard) and three
    Mountains — can act."""
    state = _empty_state()
    _strip_player_zones(state, 1)
    printings = get_active_source().get_printings()
    bombard = state.new_object(
        printings["Bombard"], owner_id=1, zone=Zone.HAND,
    )
    state.players[1].hand.append(bombard)
    for _ in range(3):
        _give_basic_land(state, 1, "Mountain")
    assert opp_can_act(state, 1) is True


def test_opp_can_act_false_with_unaffordable_instant():
    """Opp has a {R} instant in hand but no red sources — cost not
    payable; no other capability exists, so ``False``."""
    state = _empty_state()
    _strip_player_zones(state, 1)
    printings = get_active_source().get_printings()
    bombard = state.new_object(
        printings["Bombard"], owner_id=1, zone=Zone.HAND,
    )
    state.players[1].hand.append(bombard)
    # No mana sources.
    assert opp_can_act(state, 1) is False


def test_opp_can_act_false_with_only_sorcery_speed_in_hand():
    """Opp has a vanilla creature (sorcery-speed) in hand — at
    instant-speed timing it isn't castable. False."""
    state = _empty_state()
    _strip_player_zones(state, 1)
    _give_synthetic_in_hand(state, 1, "Wild Bear")
    _give_basic_land(state, 1, "Forest")
    assert opp_can_act(state, 1) is False


def test_opp_capability_hash_changes_when_hand_grows():
    """Hash is structural over hand + battlefield + ... — adding a
    card to opp's hand must blow the hash."""
    state = _empty_state()
    _strip_player_zones(state, 1)
    h0 = opp_capability_hash(state, 1)
    _give_synthetic_in_hand(state, 1, "Wild Bear")
    h1 = opp_capability_hash(state, 1)
    assert h0 != h1


def test_opp_capability_hash_stable_across_no_op_calls():
    """Hash is deterministic over an unchanging state."""
    state = _empty_state()
    _strip_player_zones(state, 1)
    a = opp_capability_hash(state, 1)
    b = opp_capability_hash(state, 1)
    assert a == b


# ---------------------------------------------------------------------
# Adapter integration: auto-pass paths
# ---------------------------------------------------------------------


def test_auto_pass_when_opp_hand_empty_and_no_abilities(monkeypatch):
    """Opp has empty hand and no permanents with abilities. At opp's
    priority moment, ``legal_decisions`` returns ``[PassPriority()]``
    without calling ``legal_actions``."""
    state = _empty_state()
    _strip_player_zones(state, 1)
    # Give opp a tapped Mountain to ensure they're alive but cannot
    # tap for mana / abilities.
    _give_basic_land(state, 1, "Mountain", tapped=True)
    adapter = MtgGameStateAdapter(state)
    _drop_to_opp_priority(adapter)

    spy = _spy_legal_actions(monkeypatch)
    decisions = adapter.legal_decisions()

    assert decisions == [PassPriority()]
    assert spy.call_count == 0, (
        "auto-pass path must not invoke legal_actions"
    )


def test_does_not_auto_pass_when_opp_has_castable_instant(monkeypatch):
    """Opp has a {2}{R} instant (Bombard) + 3 Mountains — auto-pass
    must NOT fire, full legal_actions enumeration runs."""
    state = _empty_state()
    _strip_player_zones(state, 1)
    printings = get_active_source().get_printings()
    bombard = state.new_object(
        printings["Bombard"], owner_id=1, zone=Zone.HAND,
    )
    state.players[1].hand.append(bombard)
    for _ in range(3):
        _give_basic_land(state, 1, "Mountain")
    # Drop something on opp's battlefield so Bombard has a creature
    # to target (Bombard targets a creature). Without a target,
    # legal_actions filters Bombard out and the only opp-side action
    # would be activating the Mountain — but Mountains have no
    # entry in activated_abilities. Add a creature to opp's
    # battlefield as a Bombard target.
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=1, zone=Zone.BATTLEFIELD,
    )
    bear.controller_id = 1
    bear.summoning_sick = False
    state.battlefield.append(bear)
    adapter = MtgGameStateAdapter(state)
    _drop_to_opp_priority(adapter)

    spy = _spy_legal_actions(monkeypatch)
    decisions = adapter.legal_decisions()

    # legal_actions WAS called.
    assert spy.call_count >= 1
    # And opp sees Bombard as a legal cast.
    assert any(isinstance(d, CastSpell) for d in decisions)


def test_does_not_auto_pass_when_opp_holds_unaffordable_instant(
    monkeypatch,
):
    """Opp has an instant in hand whose mana cost they CAN pay —
    capability is True even though we don't check target legality.
    Auto-pass must NOT fire; the full ``legal_actions`` enumerator
    runs.

    NB: today's engine returns just ``[PassPriority()]`` from
    ``legal_actions`` at non-sorcery timing for activated abilities
    on opp's permanents (early-return before the activated block).
    The bool-flip we observe here therefore comes from the hand-
    castable check, which remains the load-bearing capability path
    at non-active priority.
    """
    state = _empty_state()
    _strip_player_zones(state, 1)
    printings = get_active_source().get_printings()
    bombard = state.new_object(
        printings["Bombard"], owner_id=1, zone=Zone.HAND,
    )
    state.players[1].hand.append(bombard)
    for _ in range(3):
        _give_basic_land(state, 1, "Mountain")
    # Provide a Bombard target so the cast actually surfaces.
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=1,
        zone=Zone.BATTLEFIELD,
    )
    bear.controller_id = 1
    bear.summoning_sick = False
    state.battlefield.append(bear)

    adapter = MtgGameStateAdapter(state)
    _drop_to_opp_priority(adapter)

    spy = _spy_legal_actions(monkeypatch)
    decisions = adapter.legal_decisions()

    # Auto-pass DID NOT fire — full enumerator ran.
    assert spy.call_count >= 1
    # And opp's full legal set surfaces a CastSpell.
    assert any(isinstance(d, CastSpell) for d in decisions)


def test_active_player_priority_unaffected(monkeypatch):
    """Auto-pass is OPP-only. Even if the active player has nothing
    to do, ``legal_decisions`` still goes through ``legal_actions``."""
    state = _empty_state()
    _strip_player_zones(state, 0)  # strip ACTIVE player.
    adapter = MtgGameStateAdapter(state)
    # Priority is on the active player here.
    assert (
        adapter.engine_state.priority_player_idx
        == adapter.engine_state.active_player_idx
    )

    spy = _spy_legal_actions(monkeypatch)
    decisions = adapter.legal_decisions()

    # Active-player path always enumerates.
    assert spy.call_count == 1
    assert any(isinstance(d, PassPriority) for d in decisions)


# ---------------------------------------------------------------------
# Cache invalidation
# ---------------------------------------------------------------------


def test_capability_cache_hit_returns_immediately(monkeypatch):
    """Two consecutive ``legal_decisions`` calls within the same
    priority moment AND with no ``apply`` between them must consult
    ``opp_can_act``'s expensive helpers AT MOST ONCE — the cache
    hit serves the second call directly. Easiest observation: the
    cache tuple stays referentially the same."""
    state = _empty_state()
    _strip_player_zones(state, 1)
    adapter = MtgGameStateAdapter(state)
    _drop_to_opp_priority(adapter)

    # First call populates the cache; assert auto-pass fired.
    decisions_a = adapter.legal_decisions()
    assert decisions_a == [PassPriority()]
    cache_after_first = adapter._opp_cap_cache
    assert cache_after_first is not None

    # Second call hits the cache (hash matches).
    decisions_b = adapter.legal_decisions()
    assert decisions_b == [PassPriority()]
    # Cache entry unchanged (same tuple).
    assert adapter._opp_cap_cache is cache_after_first


def test_capability_cache_invalidated_by_apply():
    """``apply()`` clears the opp_cap_cache, regardless of whether
    the call site mutated state in a way that would have been
    structurally visible to the hash."""
    state = _empty_state()
    _strip_player_zones(state, 1)
    adapter = MtgGameStateAdapter(state)
    _drop_to_opp_priority(adapter)

    _ = adapter.legal_decisions()
    assert adapter._opp_cap_cache is not None

    # Apply a PassPriority on opp's window — explicit invariant: the
    # cache is cleared even if the same priority window shape persists.
    adapter.apply(PassPriority())
    assert adapter._opp_cap_cache is None


def test_capability_cache_recomputes_after_state_change():
    """If opp's hand / battlefield changes between two cache check
    moments, the structural hash changes and the cached value is
    rejected. Drop a payable instant into opp's hand to flip the
    bool from False to True.
    """
    state = _empty_state()
    _strip_player_zones(state, 1)
    # Pre-seed Mountains so the cost will become payable once
    # Bombard lands in hand.
    for _ in range(3):
        _give_basic_land(state, 1, "Mountain")
    adapter = MtgGameStateAdapter(state)
    _drop_to_opp_priority(adapter)

    # Prime the cache: capability is False (auto-pass — empty hand).
    _ = adapter.legal_decisions()
    assert adapter._opp_cap_cache is not None
    assert adapter._opp_cap_cache[2] is False  # can_act

    # Drop a {2}{R} instant into opp's hand.
    printings = get_active_source().get_printings()
    bombard = state.new_object(
        printings["Bombard"], owner_id=1, zone=Zone.HAND,
    )
    state.players[1].hand.append(bombard)

    can_act_now = adapter._opp_can_act_cached(
        state.players[adapter.engine_state.priority_player_idx].id
    )
    assert can_act_now is True
    # Cache replaced with the new hash + new bool.
    assert adapter._opp_cap_cache[2] is True


def test_clone_starts_with_empty_cache():
    """A cloned adapter must NOT share its cap cache with the source
    — the determinizer often mutates clones in place."""
    state = _empty_state()
    _strip_player_zones(state, 1)
    adapter = MtgGameStateAdapter(state)
    _drop_to_opp_priority(adapter)

    _ = adapter.legal_decisions()  # primes the source cache
    assert adapter._opp_cap_cache is not None

    clone = adapter.clone()
    assert clone._opp_cap_cache is None


# ---------------------------------------------------------------------
# Mask coherence with auto-pass
# ---------------------------------------------------------------------


def test_legal_action_mask_consistent_with_auto_pass():
    """When the adapter says auto-pass, the encoded mask returned by
    ``legal_action_mask`` must contain ONLY the PASS slot. Otherwise
    the policy head would expose phantom legal slots that the engine
    refuses."""
    state = _empty_state()
    _strip_player_zones(state, 1)
    adapter = MtgGameStateAdapter(state)
    _drop_to_opp_priority(adapter)

    decisions = adapter.legal_decisions()
    assert decisions == [PassPriority()]

    viewer = adapter.active_player()
    mask = ae.legal_action_mask(adapter, viewer)
    assert isinstance(mask, np.ndarray)
    assert mask.shape == (ae.ACTION_VOCAB_SIZE,)
    # Only the PASS slot is set.
    assert mask[ae.SLOT_PASS]
    assert int(mask.sum()) == 1


def test_legal_action_mask_does_not_call_legal_actions_under_autopass(
    monkeypatch,
):
    """With auto-pass active, the mask helper must take the
    ``_can_short_circuit_to_pass`` fast path and NOT invoke
    ``legal_actions``."""
    state = _empty_state()
    _strip_player_zones(state, 1)
    adapter = MtgGameStateAdapter(state)
    _drop_to_opp_priority(adapter)

    spy = _spy_legal_actions(monkeypatch)
    viewer = adapter.active_player()
    _ = adapter.legal_decisions()  # primes auto-pass
    _ = ae.legal_action_mask(adapter, viewer)
    # Both calls hit the auto-pass path; no legal_actions runs.
    assert spy.call_count == 0


# ---------------------------------------------------------------------
# Multi-turn / combat sanity
# ---------------------------------------------------------------------


def test_capability_skip_does_not_break_combat_flow(monkeypatch):
    """Drive a multi-turn random walk. With auto-pass on, every game
    must still terminate (or hit a normal step boundary) without any
    decision-mismatch error. Pin the broad invariant: applying a
    legal decision randomly until a few turns have passed never
    raises."""
    state = _empty_state()
    adapter = MtgGameStateAdapter(state)
    import random
    rng = random.Random(0)
    for _ in range(200):
        if adapter.is_terminal():
            break
        decisions = adapter.legal_decisions()
        assert decisions, "no legal decisions at non-terminal moment"
        adapter.apply(rng.choice(decisions))


def test_auto_pass_disables_when_opp_gains_capability(monkeypatch):
    """Walk an opp from "no capability" to "has capability" within
    a single test by giving them a payable instant in hand mid-game.
    The hash check must catch the shift.
    """
    state = _empty_state()
    _strip_player_zones(state, 1)
    for _ in range(3):
        _give_basic_land(state, 1, "Mountain")
    adapter = MtgGameStateAdapter(state)
    _drop_to_opp_priority(adapter)

    # Step 1: auto-pass active (empty hand).
    assert adapter.legal_decisions() == [PassPriority()]

    # Step 2: drop a Bombard into opp's hand. Three Mountains are
    # already untapped — cost is payable.
    printings = get_active_source().get_printings()
    bombard = state.new_object(
        printings["Bombard"], owner_id=1, zone=Zone.HAND,
    )
    state.players[1].hand.append(bombard)

    can_act = adapter._opp_can_act_cached(
        adapter.engine_state.players[
            adapter.engine_state.priority_player_idx
        ].id
    )
    assert can_act is True
