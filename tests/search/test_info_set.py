"""Tests for ``mtg_bot.search.info_set.info_set_key``.

The contract this module pins:

1. **Determinization preserves the key.** A determinized state and
   its source — viewer-equivalent by construction — must hash equal.
2. **Viewer-visible mutations change the key.** Life totals,
   graveyard contents, viewer-hand contents, etc. must affect the
   hash.
3. **Each viewer's key is independent.** Same engine state, two
   different viewers, two different keys (they know different things).
4. **Phase / step / priority changes the key.**
5. **Combat-state sensitivity** through the adapter — pending
   attackers vs main phase hash differently.
6. **Resolution-pause sensitivity** — paused vs not-paused hash
   differently.

Plus a perf check (informational, not a regression gate).
"""

from __future__ import annotations

import random
import time

from mtg_bot.agents import RandomAgent
from mtg_bot.cards import BASIC_LANDS, SYNTHETIC_CREATURES
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.search.determinize import determinize
from mtg_bot.search.engine_adapter import (
    _COMBAT_ATTACKERS, _COMBAT_BLOCKERS, MtgGameStateAdapter,
)
from mtg_bot.search.info_set import info_set_key
from mtg_bot.simulate import setup_game
from mtg_bot.turn import Step


# ---------- helpers ---------------------------------------------------------


def _new_state(num_players: int = 2) -> GameState:
    state = GameState()
    for i in range(num_players):
        state.players.append(Player(id=i))
    state.step = Step.PRECOMBAT_MAIN
    return state


def _seeded_real_state(seed: int) -> GameState:
    """Real two-player ``setup_game`` state with mono-color decks.
    Use for property tests that need realistic library / hand shapes."""
    return setup_game(
        [RandomAgent(), RandomAgent()], ["G", "R"], seed=seed,
    )


# ---------- property 1: determinization preserves the key -------------------


def test_determinize_preserves_key_simple_state():
    state = _new_state()
    p0, p1 = state.players
    p0.hand.extend(
        state.new_object(BASIC_LANDS[n], 0, Zone.HAND)
        for n in ("Plains", "Island", "Swamp")
    )
    p1.hand.extend(
        state.new_object(BASIC_LANDS[n], 1, Zone.HAND)
        for n in ("Mountain", "Forest", "Plains", "Swamp")
    )
    p1.library.extend(
        state.new_object(BASIC_LANDS[n], 1, Zone.LIBRARY)
        for n in ("Plains", "Island", "Swamp", "Mountain", "Forest")
    )
    p0.library.extend(
        state.new_object(BASIC_LANDS[n], 0, Zone.LIBRARY)
        for n in ("Forest", "Forest", "Mountain")
    )

    base_key = info_set_key(state, viewer_id=0)
    for seed in range(10):
        d = determinize(state, viewer_id=0, rng=random.Random(seed))
        assert info_set_key(d, viewer_id=0) == base_key, (
            f"seed {seed}: determinization changed viewer-0 key"
        )


def test_determinize_preserves_key_real_setup_game():
    for seed in (1, 7, 42, 100, 2026):
        state = _seeded_real_state(seed)
        for viewer_id in (0, 1):
            base_key = info_set_key(state, viewer_id=viewer_id)
            for d_seed in range(5):
                d = determinize(
                    state, viewer_id=viewer_id, rng=random.Random(d_seed),
                )
                assert info_set_key(d, viewer_id=viewer_id) == base_key, (
                    f"seed={seed} viewer={viewer_id} d_seed={d_seed}: "
                    f"determinization changed key"
                )


def test_determinize_preserves_key_through_adapter():
    """Pinning the adapter form: with the engine state wrapped in
    ``MtgGameStateAdapter``, determinizing the underlying engine state
    must also preserve the key."""
    state = _seeded_real_state(seed=42)
    adapter = MtgGameStateAdapter(state)
    base_key = info_set_key(adapter, viewer_id=0)

    for d_seed in range(5):
        d_clone = adapter.clone()
        determinize(
            d_clone.engine_state,
            viewer_id=0,
            rng=random.Random(d_seed),
            in_place=True,
        )
        assert info_set_key(d_clone, viewer_id=0) == base_key


# ---------- property 2: viewer-visible mutations change the key -------------


def test_life_total_change_changes_key():
    state = _new_state()
    state.players[1].hand.append(
        state.new_object(BASIC_LANDS["Plains"], 1, Zone.HAND)
    )
    k0 = info_set_key(state, viewer_id=0)
    state.players[1].life -= 1
    k1 = info_set_key(state, viewer_id=0)
    assert k0 != k1


def test_drawing_into_viewer_hand_changes_viewer_key():
    state = _new_state()
    p0 = state.players[0]
    p0.hand.append(state.new_object(BASIC_LANDS["Plains"], 0, Zone.HAND))
    k0 = info_set_key(state, viewer_id=0)
    p0.hand.append(state.new_object(BASIC_LANDS["Island"], 0, Zone.HAND))
    k1 = info_set_key(state, viewer_id=0)
    assert k0 != k1


def test_card_to_graveyard_changes_key():
    state = _new_state()
    p1 = state.players[1]
    p1.hand.append(state.new_object(BASIC_LANDS["Plains"], 1, Zone.HAND))
    k0 = info_set_key(state, viewer_id=0)
    p1.graveyard.append(
        state.new_object(BASIC_LANDS["Swamp"], 1, Zone.GRAVEYARD)
    )
    k1 = info_set_key(state, viewer_id=0)
    assert k0 != k1


def test_battlefield_change_changes_key():
    state = _new_state()
    obj = state.new_object(
        SYNTHETIC_CREATURES["Battlefield Recruit"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(obj)
    k0 = info_set_key(state, viewer_id=0)
    obj.tapped = True
    k1 = info_set_key(state, viewer_id=0)
    assert k0 != k1
    obj.plus_one_counters = 2
    k2 = info_set_key(state, viewer_id=0)
    assert k1 != k2


def test_mana_pool_change_changes_key():
    from mtg_bot.game import ManaCoin
    state = _new_state()
    k0 = info_set_key(state, viewer_id=0)
    state.players[0].mana_pool.append(ManaCoin(color="G"))
    k1 = info_set_key(state, viewer_id=0)
    assert k0 != k1


def test_hidden_count_change_changes_key():
    """Even though the viewer doesn't know individual hidden cards,
    the COUNT is public — adding a card to opponent's library must
    change the key."""
    state = _new_state()
    state.players[1].library.append(
        state.new_object(BASIC_LANDS["Plains"], 1, Zone.LIBRARY)
    )
    k0 = info_set_key(state, viewer_id=0)
    state.players[1].library.append(
        state.new_object(BASIC_LANDS["Island"], 1, Zone.LIBRARY)
    )
    k1 = info_set_key(state, viewer_id=0)
    assert k0 != k1


# ---------- property 3: each viewer's key is independent --------------------


def test_each_viewer_has_independent_key():
    """A state where the two viewers have different hands hashes
    differently from each viewer's perspective."""
    state = _new_state()
    p0, p1 = state.players
    p0.hand.append(state.new_object(BASIC_LANDS["Plains"], 0, Zone.HAND))
    p1.hand.append(state.new_object(BASIC_LANDS["Mountain"], 1, Zone.HAND))
    k0 = info_set_key(state, viewer_id=0)
    k1 = info_set_key(state, viewer_id=1)
    assert k0 != k1


def test_two_viewers_real_setup_have_different_keys():
    state = _seeded_real_state(seed=42)
    k0 = info_set_key(state, viewer_id=0)
    k1 = info_set_key(state, viewer_id=1)
    assert k0 != k1


def test_hidden_opponent_hand_swap_does_not_change_viewer_key():
    """Two states that differ only in opponent's hand printings must
    hash equal for the viewer."""
    state_a = _new_state()
    state_a.players[1].hand.extend([
        state_a.new_object(BASIC_LANDS["Plains"], 1, Zone.HAND),
        state_a.new_object(BASIC_LANDS["Island"], 1, Zone.HAND),
    ])
    state_b = _new_state()
    state_b.players[1].hand.extend([
        state_b.new_object(BASIC_LANDS["Mountain"], 1, Zone.HAND),
        state_b.new_object(BASIC_LANDS["Forest"], 1, Zone.HAND),
    ])
    # Same id assignment by construction — both used new_object
    # starting from 0 (one per state). Realign so the cards actually
    # have the same ids.
    for i, c in enumerate(state_b.players[1].hand):
        c.id = state_a.players[1].hand[i].id

    assert info_set_key(state_a, viewer_id=0) == \
        info_set_key(state_b, viewer_id=0)


# ---------- property 4: phase / step changes the key ------------------------


def test_step_change_changes_key():
    state = _new_state()
    state.step = Step.PRECOMBAT_MAIN
    k0 = info_set_key(state, viewer_id=0)
    state.step = Step.POSTCOMBAT_MAIN
    k1 = info_set_key(state, viewer_id=0)
    assert k0 != k1


def test_priority_holder_change_changes_key():
    state = _new_state()
    state.priority_player_idx = 0
    k0 = info_set_key(state, viewer_id=0)
    state.priority_player_idx = 1
    k1 = info_set_key(state, viewer_id=0)
    assert k0 != k1


def test_active_player_change_changes_key():
    state = _new_state()
    state.active_player_idx = 0
    k0 = info_set_key(state, viewer_id=0)
    state.active_player_idx = 1
    k1 = info_set_key(state, viewer_id=0)
    assert k0 != k1


def test_turn_number_change_changes_key():
    state = _new_state()
    k0 = info_set_key(state, viewer_id=0)
    state.turn_number += 1
    k1 = info_set_key(state, viewer_id=0)
    assert k0 != k1


# ---------- property 5: combat-state sensitivity ----------------------------


def test_combat_phase_attackers_vs_main_have_different_keys():
    """Use the adapter so combat-phase bookkeeping differs."""
    state = _seeded_real_state(seed=42)
    adapter_main = MtgGameStateAdapter(state.clone())
    adapter_attackers = MtgGameStateAdapter(state.clone())
    # Force the second one into the attackers phase with a synthetic
    # pending attacker. We don't want to actually drive the game to
    # combat (would advance many engine fields and make the test
    # hard to isolate); we can just write the adapter fields directly
    # for this test, since the contract is "different combat phase →
    # different hash."
    adapter_attackers._combat_phase = _COMBAT_ATTACKERS
    adapter_attackers._pending_attackers = [123]

    k_main = info_set_key(adapter_main, viewer_id=0)
    k_attackers = info_set_key(adapter_attackers, viewer_id=0)
    assert k_main != k_attackers


def test_combat_phase_blockers_vs_attackers_have_different_keys():
    state = _seeded_real_state(seed=42)
    adapter_a = MtgGameStateAdapter(state.clone())
    adapter_b = MtgGameStateAdapter(state.clone())

    adapter_a._combat_phase = _COMBAT_ATTACKERS
    adapter_a._pending_attackers = [10]

    adapter_b._combat_phase = _COMBAT_BLOCKERS
    adapter_b._pending_blockers = [10]
    adapter_b._combat_defender_id = 1

    assert info_set_key(adapter_a, viewer_id=0) != \
        info_set_key(adapter_b, viewer_id=0)


def test_pending_attackers_change_changes_key():
    state = _seeded_real_state(seed=42)
    adapter = MtgGameStateAdapter(state)
    adapter._combat_phase = _COMBAT_ATTACKERS
    adapter._pending_attackers = [1, 2, 3]
    k0 = info_set_key(adapter, viewer_id=0)
    adapter._pending_attackers = [1, 2]
    k1 = info_set_key(adapter, viewer_id=0)
    assert k0 != k1


# ---------- property 6: resolution-pause sensitivity ------------------------


def test_resolution_paused_vs_not_have_different_keys():
    state = _seeded_real_state(seed=42)
    adapter = MtgGameStateAdapter(
        state.clone(), expose_resolution_decisions=True,
    )
    k0 = info_set_key(adapter, viewer_id=0)

    adapter._resolution_paused = True
    adapter._resolution_kind = "target"
    adapter._resolution_player = 0
    adapter._resolution_options = ((1,), (2,))
    k1 = info_set_key(adapter, viewer_id=0)
    assert k0 != k1


def test_resolution_kind_change_changes_key():
    state = _seeded_real_state(seed=42)
    adapter_a = MtgGameStateAdapter(
        state.clone(), expose_resolution_decisions=True,
    )
    adapter_b = MtgGameStateAdapter(
        state.clone(), expose_resolution_decisions=True,
    )

    adapter_a._resolution_paused = True
    adapter_a._resolution_kind = "target"
    adapter_a._resolution_player = 0
    adapter_a._resolution_options = ((1,),)

    adapter_b._resolution_paused = True
    adapter_b._resolution_kind = "discard"
    adapter_b._resolution_player = 0
    adapter_b._resolution_options = (1,)

    assert info_set_key(adapter_a, viewer_id=0) != \
        info_set_key(adapter_b, viewer_id=0)


# ---------- determinism / repeatability -------------------------------------


def test_key_is_deterministic_across_calls():
    state = _seeded_real_state(seed=42)
    k_a = info_set_key(state, viewer_id=0)
    k_b = info_set_key(state, viewer_id=0)
    assert k_a == k_b
    assert isinstance(k_a, bytes)
    assert len(k_a) == 16


def test_key_is_bytes_of_expected_size():
    state = _new_state()
    k = info_set_key(state, viewer_id=0)
    assert isinstance(k, bytes)
    assert len(k) == 16


# ---------- perf (informational, not a regression gate) ---------------------


def test_info_set_key_is_fast_on_realistic_state():
    """Soft target: <100us per call on a setup_game state. The test
    asserts a 500us upper bound (5x the target) so it doesn't flap on
    a slow CI runner; if it ever fails, that's a real regression."""
    state = _seeded_real_state(seed=42)
    # Warm.
    for _ in range(10):
        info_set_key(state, viewer_id=0)
    iters = 1000
    t0 = time.perf_counter()
    for _ in range(iters):
        info_set_key(state, viewer_id=0)
    elapsed_us = (time.perf_counter() - t0) * 1e6 / iters
    assert elapsed_us < 500, (
        f"info_set_key took {elapsed_us:.1f}us per call (target "
        f"<100us; ceiling 500us)"
    )
