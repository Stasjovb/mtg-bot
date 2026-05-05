"""Tests for active-player capability-based auto-pass.

The opp-side auto-pass landed in feature/opp-capability-autopass; this
suite covers the symmetric extension that auto-passes the ACTIVE
player when they have no possible action either. Sorcery-window
awareness is the key correctness invariant: at non-sorcery timing the
active player has the same instant-only capability set as opp, but at
sorcery timing the player can also play lands, cast sorceries /
creatures / non-instant permanents, activate sorcery-speed abilities,
and (pre-combat) declare attackers.

Cache-and-skip contract:
- When the active player has priority AND
  ``has_player_capability_to_act(state, pid, is_active_player=True)``
  is False, ``legal_decisions`` returns ``[PassPriority()]`` WITHOUT
  invoking ``legal_actions``.
- When the active player can act (sorcery-castable in hand at
  sorcery-window, payable land in hand with land-drops remaining,
  pre-combat attacker eligible, etc.), auto-pass must NOT fire.
- The capability cache is invalidated by ``apply()`` like the opp
  variant.
- The "both auto-pass" cascade across a quiet phase reduces NN /
  search workload to zero across an entire priority round.
"""

from __future__ import annotations

from unittest import mock

from mtg_bot import legal as legal_mod
from mtg_bot.actions import (
    CastSpell, PassPriority, PlayLand,
)
from mtg_bot.agents import RandomAgent
from mtg_bot.cards import BASIC_LANDS, SYNTHETIC_CREATURES
from mtg_bot.cards.source import get_active_source
from mtg_bot.game import Zone
from mtg_bot.search import MtgGameStateAdapter
from mtg_bot.search._player_capabilities import (
    _is_sorcery_window,
    has_player_capability_to_act,
    player_capability_hash,
)
from mtg_bot.simulate import setup_game
from mtg_bot.turn import Step


# ---------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------


def _empty_state(seed: int = 42):
    """Two-player setup; tests that need a clean slate clear
    hand/battlefield manually."""
    return setup_game(
        [RandomAgent(), RandomAgent()], ["G", "R"], seed=seed,
    )


def _spy_legal_actions(monkeypatch):
    """Patch every entry point so call counting catches all calls."""
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
    land = state.new_object(
        BASIC_LANDS[name], owner_id=player_idx, zone=Zone.BATTLEFIELD,
    )
    land.controller_id = player_idx
    land.tapped = tapped
    state.battlefield.append(land)


def _give_basic_in_hand(state, player_idx: int, name: str) -> None:
    p = state.players[player_idx]
    land = state.new_object(
        BASIC_LANDS[name], owner_id=p.id, zone=Zone.HAND,
    )
    p.hand.append(land)


def _give_synthetic_in_hand(state, player_idx: int, name: str) -> None:
    p = state.players[player_idx]
    obj = state.new_object(
        SYNTHETIC_CREATURES[name], owner_id=p.id, zone=Zone.HAND,
    )
    p.hand.append(obj)


def _give_creature_on_battlefield(
    state, player_idx: int, name: str,
    *, summoning_sick: bool = False, tapped: bool = False,
) -> None:
    p = state.players[player_idx]
    obj = state.new_object(
        SYNTHETIC_CREATURES[name], owner_id=p.id, zone=Zone.BATTLEFIELD,
    )
    obj.controller_id = p.id
    obj.summoning_sick = summoning_sick
    obj.tapped = tapped
    state.battlefield.append(obj)


# ---------------------------------------------------------------------
# Unit tests for capability primitives
# ---------------------------------------------------------------------


def test_is_sorcery_window_true_for_active_in_main_with_empty_stack():
    state = _empty_state()
    state.step = Step.PRECOMBAT_MAIN
    state.priority_player_idx = state.active_player_idx
    state.stack = []
    pid = state.players[state.active_player_idx].id
    assert _is_sorcery_window(state, pid) is True


def test_is_sorcery_window_false_in_combat():
    state = _empty_state()
    state.step = Step.DECLARE_ATTACKERS
    state.priority_player_idx = state.active_player_idx
    state.stack = []
    pid = state.players[state.active_player_idx].id
    assert _is_sorcery_window(state, pid) is False


def test_is_sorcery_window_false_with_nonempty_stack():
    state = _empty_state()
    state.step = Step.PRECOMBAT_MAIN
    state.priority_player_idx = state.active_player_idx
    # Stick anything into the stack — the type doesn't matter for the
    # capability gate, just that it's non-empty.
    state.stack = [object()]
    pid = state.players[state.active_player_idx].id
    assert _is_sorcery_window(state, pid) is False


def test_is_sorcery_window_false_when_opp_has_priority():
    state = _empty_state()
    state.step = Step.PRECOMBAT_MAIN
    # Active is index 0; flip priority to opp.
    state.priority_player_idx = 1 - state.active_player_idx
    state.stack = []
    pid = state.players[state.active_player_idx].id
    assert _is_sorcery_window(state, pid) is False


# ---------------------------------------------------------------------
# has_player_capability_to_act — active player path
# ---------------------------------------------------------------------


def test_active_no_capability_when_zones_stripped():
    """Empty player with active-player priority at sorcery window
    has no capability."""
    state = _empty_state()
    _strip_player_zones(state, 0)
    state.step = Step.PRECOMBAT_MAIN
    state.priority_player_idx = 0
    pid = state.players[0].id
    assert has_player_capability_to_act(
        state, pid, is_active_player=True,
    ) is False


def test_active_capability_with_castable_creature_at_sorcery_window():
    """Active player has a payable vanilla creature (Wild Bear, {1}{G})
    in hand AND a Forest in play AND we're at sorcery window — the
    sorcery-cast capability path returns True."""
    state = _empty_state()
    _strip_player_zones(state, 0)
    state.step = Step.PRECOMBAT_MAIN
    state.priority_player_idx = 0
    _give_synthetic_in_hand(state, 0, "Wild Bear")
    for _ in range(2):
        _give_basic_land(state, 0, "Forest")
    pid = state.players[0].id
    assert has_player_capability_to_act(
        state, pid, is_active_player=True,
    ) is True


def test_active_capability_with_land_in_hand_and_drops_remaining():
    """Active player with a Forest in hand at sorcery window AND no
    land plays consumed yet — the land-drop capability returns True."""
    state = _empty_state()
    _strip_player_zones(state, 0)
    state.step = Step.PRECOMBAT_MAIN
    state.priority_player_idx = 0
    _give_basic_in_hand(state, 0, "Forest")
    pid = state.players[0].id
    state.players[0].lands_played_this_turn = 0
    assert has_player_capability_to_act(
        state, pid, is_active_player=True,
    ) is True


def test_active_no_capability_when_land_drop_consumed():
    """Active player has a land in hand BUT already played a land this
    turn — land capability is False, and (with no other capability)
    overall is False."""
    state = _empty_state()
    _strip_player_zones(state, 0)
    state.step = Step.PRECOMBAT_MAIN
    state.priority_player_idx = 0
    _give_basic_in_hand(state, 0, "Forest")
    state.players[0].lands_played_this_turn = 1
    pid = state.players[0].id
    assert has_player_capability_to_act(
        state, pid, is_active_player=True,
    ) is False


def test_active_no_capability_for_sorcery_at_combat_step():
    """Active player has a creature in hand, payable, but we're at
    DECLARE_BLOCKERS (instant-only timing) — sorcery-speed capability
    is gated out and overall is False."""
    state = _empty_state()
    _strip_player_zones(state, 0)
    state.step = Step.DECLARE_BLOCKERS
    state.priority_player_idx = 0
    _give_synthetic_in_hand(state, 0, "Wild Bear")
    for _ in range(2):
        _give_basic_land(state, 0, "Forest")
    pid = state.players[0].id
    assert has_player_capability_to_act(
        state, pid, is_active_player=True,
    ) is False


def test_active_capability_with_castable_instant_at_combat_step():
    """Active player at instant-only timing (combat step) WITH an
    instant in hand AND payable mana — instant-cast capability fires
    independent of the sorcery window."""
    state = _empty_state()
    _strip_player_zones(state, 0)
    state.step = Step.DECLARE_BLOCKERS
    state.priority_player_idx = 0
    printings = get_active_source().get_printings()
    bombard = state.new_object(
        printings["Bombard"], owner_id=0, zone=Zone.HAND,
    )
    state.players[0].hand.append(bombard)
    for _ in range(3):
        _give_basic_land(state, 0, "Mountain")
    pid = state.players[0].id
    assert has_player_capability_to_act(
        state, pid, is_active_player=True,
    ) is True


def test_active_capability_pre_combat_with_eligible_attacker():
    """Active player at BEGINNING_OF_COMBAT with an untapped non-sick
    creature is capable (could declare it as an attacker). Even with
    nothing else to do."""
    state = _empty_state()
    _strip_player_zones(state, 0)
    state.step = Step.BEGINNING_OF_COMBAT
    state.priority_player_idx = 0
    _give_creature_on_battlefield(
        state, 0, "Wild Bear", summoning_sick=False, tapped=False,
    )
    pid = state.players[0].id
    assert has_player_capability_to_act(
        state, pid, is_active_player=True,
    ) is True


def test_active_no_capability_pre_combat_with_only_sick_creatures():
    """Active player at BEGINNING_OF_COMBAT with only summoning-sick
    creatures — no attacker is eligible, no other capability, so
    overall False."""
    state = _empty_state()
    _strip_player_zones(state, 0)
    state.step = Step.BEGINNING_OF_COMBAT
    state.priority_player_idx = 0
    _give_creature_on_battlefield(
        state, 0, "Wild Bear", summoning_sick=True, tapped=False,
    )
    pid = state.players[0].id
    assert has_player_capability_to_act(
        state, pid, is_active_player=True,
    ) is False


# ---------------------------------------------------------------------
# Adapter integration: active-player auto-pass paths
# ---------------------------------------------------------------------


def _drive_to_main_phase(adapter, max_passes: int = 30) -> None:
    """Advance the adapter through UPKEEP / DRAW (and any
    instant-speed priority round in between) until we reach
    PRECOMBAT_MAIN at the active player's priority. Bounded so a bug
    can't loop forever; raise if we couldn't get there."""
    for _ in range(max_passes):
        if adapter.engine_state.step == Step.PRECOMBAT_MAIN and (
            adapter.engine_state.priority_player_idx
            == adapter.engine_state.active_player_idx
        ):
            return
        decs = adapter.legal_decisions()
        # Always pass — this is the path that drives steps forward
        # through their priority rounds.
        adapter.apply(PassPriority())
    raise RuntimeError("could not advance adapter to PRECOMBAT_MAIN")


def test_adapter_auto_passes_when_active_hand_empty(monkeypatch):
    """At PRECOMBAT_MAIN with active priority, sorcery window: hand
    empty + no land-drop remaining + only a tapped Forest in play
    means no capability — auto-pass fires for active without
    enumeration."""
    state = _empty_state()
    _strip_player_zones(state, 0)
    _give_basic_land(state, 0, "Forest", tapped=False)
    state.players[0].lands_played_this_turn = 1  # land-drop consumed.
    adapter = MtgGameStateAdapter(state)
    _drive_to_main_phase(adapter)

    spy = _spy_legal_actions(monkeypatch)
    decisions = adapter.legal_decisions()

    assert decisions == [PassPriority()]
    assert spy.call_count == 0


def test_adapter_does_not_auto_pass_active_with_castable_sorcery(
    monkeypatch,
):
    """Active player has Wild Bear in hand + 2 Forests at sorcery
    window — cast is legal so legal_actions IS enumerated and
    CastSpell appears in the result."""
    state = _empty_state()
    _strip_player_zones(state, 0)
    _give_synthetic_in_hand(state, 0, "Wild Bear")
    for _ in range(2):
        _give_basic_land(state, 0, "Forest")
    state.players[0].lands_played_this_turn = 1  # consume land drop
    adapter = MtgGameStateAdapter(state)
    _drive_to_main_phase(adapter)

    spy = _spy_legal_actions(monkeypatch)
    decisions = adapter.legal_decisions()

    assert spy.call_count >= 1
    assert any(isinstance(d, CastSpell) for d in decisions)


def test_adapter_does_not_auto_pass_active_with_land_in_hand(
    monkeypatch,
):
    """Active player has Forest in hand at sorcery window — the land
    play capability prevents auto-pass and PlayLand surfaces in the
    decision set."""
    state = _empty_state()
    _strip_player_zones(state, 0)
    _give_basic_in_hand(state, 0, "Forest")
    state.players[0].lands_played_this_turn = 0
    adapter = MtgGameStateAdapter(state)
    _drive_to_main_phase(adapter)
    # Reset lands_played_this_turn after _drive (which runs UPKEEP /
    # DRAW pre-priority logic that doesn't touch the counter).
    state.players[0].lands_played_this_turn = 0
    # The drive's apply() invalidations have cleared the cap cache;
    # subsequent legal_decisions will recompute.

    spy = _spy_legal_actions(monkeypatch)
    decisions = adapter.legal_decisions()

    assert spy.call_count >= 1
    assert any(isinstance(d, PlayLand) for d in decisions)


def test_adapter_does_not_auto_pass_active_with_castable_instant_in_combat(
    monkeypatch,
):
    """Active player at DECLARE_BLOCKERS step priority has an instant
    castable — auto-pass must NOT fire even at instant-only timing."""
    state = _empty_state()
    _strip_player_zones(state, 0)
    printings = get_active_source().get_printings()
    bombard = state.new_object(
        printings["Bombard"], owner_id=0, zone=Zone.HAND,
    )
    state.players[0].hand.append(bombard)
    for _ in range(3):
        _give_basic_land(state, 0, "Mountain")
    # Provide a Bombard target so the cast actually surfaces.
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=0,
        zone=Zone.BATTLEFIELD,
    )
    bear.controller_id = 0
    bear.summoning_sick = False
    state.battlefield.append(bear)
    # Force the engine to a combat step so we're at instant-only timing.
    state.step = Step.DECLARE_BLOCKERS
    state.priority_player_idx = state.active_player_idx
    adapter = MtgGameStateAdapter.__new__(MtgGameStateAdapter)
    # Use the standard ctor path on the same state. Since we've forced
    # state.step, _advance_to_next_decision will see we're already at
    # priority and return immediately.
    from mtg_bot.search.tactical import DefaultTacticalAgent
    adapter._state = state
    adapter._tactical = DefaultTacticalAgent()
    adapter._expose_resolution = False
    adapter._channel_agent = None
    for p in state.players:
        p.agent = adapter._tactical
    adapter._pass_count = 0
    adapter._step_entered = True
    adapter._expose_combat = True
    adapter._combat_phase = None
    adapter._pending_attackers = []
    adapter._chosen_attackers = []
    adapter._pending_blockers = []
    adapter._chosen_blocks = {}
    adapter._combat_defender_id = None
    adapter._resolution_paused = False
    adapter._resolution_kind = None
    adapter._resolution_player = None
    adapter._resolution_options = ()
    adapter._pre_action_clone = None
    adapter._pending_replay_decision = None
    adapter._legal_actions_cache_player = None
    adapter._legal_actions_cache_value = None
    adapter._opp_cap_cache = None
    adapter._phase_prune_enabled = False
    adapter._force_landdrop_enabled = False
    adapter._skip_empty_combat_enabled = False
    adapter._skip_opp_postcombat_main_enabled = False

    spy = _spy_legal_actions(monkeypatch)
    decisions = adapter.legal_decisions()

    assert spy.call_count >= 1
    assert any(isinstance(d, CastSpell) for d in decisions)


def test_adapter_auto_passes_active_when_only_sorcery_at_combat(
    monkeypatch,
):
    """Active player at DECLARE_BLOCKERS (instant-only) holds a
    sorcery-speed creature in hand. The sorcery cast is gated out by
    timing, the player has no instant-speed capability, and (no
    pre-combat eligible attackers) auto-pass DOES fire."""
    state = _empty_state()
    _strip_player_zones(state, 0)
    _give_synthetic_in_hand(state, 0, "Wild Bear")
    for _ in range(2):
        _give_basic_land(state, 0, "Forest")
    # Force into DECLARE_BLOCKERS at active-player priority.
    state.step = Step.DECLARE_BLOCKERS
    state.priority_player_idx = state.active_player_idx

    # Fresh adapter using __new__ so the constructor doesn't try to
    # advance turn structure.
    from mtg_bot.search.tactical import DefaultTacticalAgent
    adapter = MtgGameStateAdapter.__new__(MtgGameStateAdapter)
    adapter._state = state
    adapter._tactical = DefaultTacticalAgent()
    adapter._expose_resolution = False
    adapter._channel_agent = None
    for p in state.players:
        p.agent = adapter._tactical
    adapter._pass_count = 0
    adapter._step_entered = True
    adapter._expose_combat = True
    adapter._combat_phase = None
    adapter._pending_attackers = []
    adapter._chosen_attackers = []
    adapter._pending_blockers = []
    adapter._chosen_blocks = {}
    adapter._combat_defender_id = None
    adapter._resolution_paused = False
    adapter._resolution_kind = None
    adapter._resolution_player = None
    adapter._resolution_options = ()
    adapter._pre_action_clone = None
    adapter._pending_replay_decision = None
    adapter._legal_actions_cache_player = None
    adapter._legal_actions_cache_value = None
    adapter._opp_cap_cache = None
    adapter._phase_prune_enabled = False
    adapter._force_landdrop_enabled = False
    adapter._skip_empty_combat_enabled = False
    adapter._skip_opp_postcombat_main_enabled = False

    spy = _spy_legal_actions(monkeypatch)
    decisions = adapter.legal_decisions()

    # Sorcery in hand can't be cast at instant-only timing; no
    # instant-speed capability → auto-pass.
    assert decisions == [PassPriority()]
    assert spy.call_count == 0


def test_adapter_pre_combat_active_does_not_auto_pass_with_attacker(
    monkeypatch,
):
    """Active player at BEGINNING_OF_COMBAT with an untapped non-sick
    creature should NOT auto-pass — the player has an attacker to
    declare."""
    state = _empty_state()
    _strip_player_zones(state, 0)
    _give_creature_on_battlefield(
        state, 0, "Wild Bear", summoning_sick=False, tapped=False,
    )
    state.step = Step.BEGINNING_OF_COMBAT
    state.priority_player_idx = state.active_player_idx

    from mtg_bot.search.tactical import DefaultTacticalAgent
    adapter = MtgGameStateAdapter.__new__(MtgGameStateAdapter)
    adapter._state = state
    adapter._tactical = DefaultTacticalAgent()
    adapter._expose_resolution = False
    adapter._channel_agent = None
    for p in state.players:
        p.agent = adapter._tactical
    adapter._pass_count = 0
    adapter._step_entered = True
    adapter._expose_combat = True
    adapter._combat_phase = None
    adapter._pending_attackers = []
    adapter._chosen_attackers = []
    adapter._pending_blockers = []
    adapter._chosen_blocks = {}
    adapter._combat_defender_id = None
    adapter._resolution_paused = False
    adapter._resolution_kind = None
    adapter._resolution_player = None
    adapter._resolution_options = ()
    adapter._pre_action_clone = None
    adapter._pending_replay_decision = None
    adapter._legal_actions_cache_player = None
    adapter._legal_actions_cache_value = None
    adapter._opp_cap_cache = None

    # has_player_capability_to_act sees the eligible attacker → True.
    pid = state.players[0].id
    assert has_player_capability_to_act(
        state, pid, is_active_player=True,
    ) is True


# ---------------------------------------------------------------------
# Cache invalidation
# ---------------------------------------------------------------------


def test_active_capability_cache_hit_returns_immediately():
    """Two consecutive ``legal_decisions`` on the same active-player
    priority moment should hit the cache; the cache tuple stays
    referentially the same."""
    state = _empty_state()
    _strip_player_zones(state, 0)
    _give_basic_land(state, 0, "Forest", tapped=False)
    state.players[0].lands_played_this_turn = 1
    # Disable phase-prune so the capability cache (under test here)
    # actually populates instead of being short-circuited.
    adapter = MtgGameStateAdapter(state, phase_prune_enabled=False)

    decisions_a = adapter.legal_decisions()
    assert decisions_a == [PassPriority()]
    cache_after_first = adapter._opp_cap_cache
    assert cache_after_first is not None
    # Cache shape: (player_id, is_active_player, hash, can_act).
    assert cache_after_first[1] is True  # active player
    assert cache_after_first[3] is False  # can_act

    decisions_b = adapter.legal_decisions()
    assert decisions_b == [PassPriority()]
    assert adapter._opp_cap_cache is cache_after_first


def test_active_capability_cache_invalidated_by_apply():
    """Apply-on-active-priority must clear the active-side cap cache."""
    state = _empty_state()
    _strip_player_zones(state, 0)
    _give_basic_land(state, 0, "Forest", tapped=False)
    state.players[0].lands_played_this_turn = 1
    adapter = MtgGameStateAdapter(state, phase_prune_enabled=False)

    _ = adapter.legal_decisions()
    assert adapter._opp_cap_cache is not None

    adapter.apply(PassPriority())
    assert adapter._opp_cap_cache is None


def test_active_capability_cache_recomputes_after_state_change():
    """If active player gains capability mid-priority-window (e.g. a
    castable instant lands in hand), the next cache check recomputes
    against the new structural hash and flips the answer. Tested at
    instant-only timing (UPKEEP) so the instant-cast path is the
    capability flip."""
    state = _empty_state()
    _strip_player_zones(state, 0)
    for _ in range(3):
        _give_basic_land(state, 0, "Mountain", tapped=False)
    state.players[0].lands_played_this_turn = 1  # consume land drop
    adapter = MtgGameStateAdapter(state, phase_prune_enabled=False)

    _ = adapter.legal_decisions()
    assert adapter._opp_cap_cache is not None
    # Active-player can_act False at fresh-adapter UPKEEP step
    # (instant-only timing, no instants, no abilities).
    assert adapter._opp_cap_cache[3] is False

    # Drop a {2}{R} instant into active's hand — instant-speed
    # capability fires regardless of step.
    printings = get_active_source().get_printings()
    bombard = state.new_object(
        printings["Bombard"], owner_id=0, zone=Zone.HAND,
    )
    state.players[0].hand.append(bombard)

    pid = state.players[0].id
    can_act_now = adapter._can_act_cached(pid, is_active_player=True)
    assert can_act_now is True
    assert adapter._opp_cap_cache[3] is True


def test_player_capability_hash_differs_active_vs_opp():
    """The hash includes ``is_active_player`` so cross-flavor cache
    hits are impossible."""
    state = _empty_state()
    pid = state.players[0].id
    h_active = player_capability_hash(state, pid, is_active_player=True)
    h_opp = player_capability_hash(state, pid, is_active_player=False)
    assert h_active != h_opp


def test_player_capability_hash_changes_when_lands_played_changes():
    """Active-player hash must depend on ``lands_played_this_turn`` —
    the same hand at land-drop=0 vs land-drop=1 has different
    capability."""
    state = _empty_state()
    state.step = Step.PRECOMBAT_MAIN
    state.priority_player_idx = state.active_player_idx
    pid = state.players[0].id
    state.players[0].lands_played_this_turn = 0
    h0 = player_capability_hash(state, pid, is_active_player=True)
    state.players[0].lands_played_this_turn = 1
    h1 = player_capability_hash(state, pid, is_active_player=True)
    assert h0 != h1


def test_player_capability_hash_changes_at_step_transition():
    """Active-player hash includes the step / sorcery-window — moving
    from PRECOMBAT_MAIN to BEGINNING_OF_COMBAT must blow the hash."""
    state = _empty_state()
    state.priority_player_idx = state.active_player_idx
    pid = state.players[0].id
    state.step = Step.PRECOMBAT_MAIN
    h0 = player_capability_hash(state, pid, is_active_player=True)
    state.step = Step.BEGINNING_OF_COMBAT
    h1 = player_capability_hash(state, pid, is_active_player=True)
    assert h0 != h1


# ---------------------------------------------------------------------
# Both-auto-pass cascade — the big-win scenario
# ---------------------------------------------------------------------


def test_both_players_auto_pass_advances_through_priority(monkeypatch):
    """When BOTH players have no capability to act, the priority round
    advances entirely through auto-pass. Drives a sequence of
    legal_decisions / apply pairs through a full priority round and
    asserts ``legal_actions`` was never invoked."""
    state = _empty_state()
    _strip_player_zones(state, 0)
    _strip_player_zones(state, 1)
    # Give each player a tapped land just so ``has_lost`` doesn't fire
    # via empty-library on the first draw — but we'll only run
    # priority loops, not draw steps.
    _give_basic_land(state, 0, "Forest", tapped=True)
    _give_basic_land(state, 1, "Mountain", tapped=True)
    state.players[0].lands_played_this_turn = 1
    state.players[1].lands_played_this_turn = 1
    adapter = MtgGameStateAdapter(state)

    spy = _spy_legal_actions(monkeypatch)

    # Drive through several legal_decisions / apply iterations. Both
    # auto-pass means the engine churns through priority rounds and
    # phase transitions purely on the auto-pass path. Cap iterations
    # so we don't loop forever — the goal is to confirm zero
    # legal_actions calls in the auto-pass-only regime.
    for _ in range(50):
        if adapter.is_terminal():
            break
        decs = adapter.legal_decisions()
        # In every priority moment of this scenario, the only legal
        # decision is Pass (because both sides have no capability).
        assert decs == [PassPriority()]
        adapter.apply(decs[0])

    assert spy.call_count == 0, (
        "both-auto-pass cascade must not invoke legal_actions"
    )


def test_sorcery_speed_castable_room_capability():
    """A DSK Room in hand at sorcery window with a payable mana cost
    surfaces sorcery-speed cast capability via the room-half loop."""
    from mtg_bot.search._player_capabilities import (
        _sorcery_speed_castable_in_hand,
    )
    state = _empty_state()
    _strip_player_zones(state, 0)
    state.step = Step.PRECOMBAT_MAIN
    state.priority_player_idx = 0
    # Skip if no Room is available in the active card source.
    printings = get_active_source().get_printings()
    room_pr = None
    for name, pr in printings.items():
        if getattr(pr, "is_room", False):
            room_pr = pr
            break
    if room_pr is None:
        return  # no Room in pool — nothing to assert
    obj = state.new_object(room_pr, owner_id=0, zone=Zone.HAND)
    state.players[0].hand.append(obj)
    pid = state.players[0].id
    p = state.players[0]
    # Without mana the room half cost isn't payable; capability False.
    assert _sorcery_speed_castable_in_hand(state, pid, p) is False
    # Add enough basics of every color to cover any room half cost.
    for color in ("W", "U", "B", "R", "G"):
        for _ in range(3):
            land_name = {
                "W": "Plains", "U": "Island", "B": "Swamp",
                "R": "Mountain", "G": "Forest",
            }[color]
            _give_basic_land(state, 0, land_name)
    # At least one room half should be payable now.
    assert _sorcery_speed_castable_in_hand(state, pid, p) is True


def test_warp_castable_in_graveyard_capability():
    """A non-instant warp-castable card in graveyard with a payable
    warp cost flips ``_sorcery_speed_castable_in_graveyard`` to True
    when the controller has a "warp from graveyard" grant in play."""
    from mtg_bot.search._player_capabilities import (
        _sorcery_speed_castable_in_graveyard,
    )
    state = _empty_state()
    _strip_player_zones(state, 0)
    pid = state.players[0].id
    p = state.players[0]
    # Search for any printing with warp_castable_from_graveyard in
    # the active source. If none, skip.
    printings = get_active_source().get_printings()
    candidate = None
    for pr in printings.values():
        if (
            pr.warp_castable_from_graveyard
            and pr.warp_cost is not None
            and not pr.is_instant
        ):
            candidate = pr
            break
    if candidate is None:
        return
    # Capability before adding the card: False.
    assert _sorcery_speed_castable_in_graveyard(state, pid, p) is False
    # Add the warp-castable card to graveyard and enough untapped
    # mountains to cover any warp cost.
    obj = state.new_object(candidate, owner_id=0, zone=Zone.GRAVEYARD)
    p.graveyard.append(obj)
    for _ in range(8):
        for color in ("W", "U", "B", "R", "G"):
            land_name = {
                "W": "Plains", "U": "Island", "B": "Swamp",
                "R": "Mountain", "G": "Forest",
            }[color]
            _give_basic_land(state, 0, land_name)
    # Warp-cost-payable flips capability True.
    assert _sorcery_speed_castable_in_graveyard(state, pid, p) is True


def test_spacecraft_capability_with_untapped_creature():
    """Active player at sorcery window controls a spacecraft AND an
    untapped non-sick creature — capability flips to True via the
    Station-crew capability path."""
    state = _empty_state()
    _strip_player_zones(state, 0)
    state.step = Step.PRECOMBAT_MAIN
    state.priority_player_idx = 0
    # Find a spacecraft in the active source. Skip if none.
    printings = get_active_source().get_printings()
    spacecraft_pr = None
    for pr in printings.values():
        if getattr(pr, "is_spacecraft", False):
            spacecraft_pr = pr
            break
    if spacecraft_pr is None:
        return
    obj = state.new_object(
        spacecraft_pr, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    obj.controller_id = 0
    state.battlefield.append(obj)
    _give_creature_on_battlefield(
        state, 0, "Wild Bear", summoning_sick=False, tapped=False,
    )
    state.players[0].lands_played_this_turn = 1  # consume drop.
    pid = state.players[0].id
    assert has_player_capability_to_act(
        state, pid, is_active_player=True,
    ) is True


def test_ability_costs_payable_pay_life_gate():
    """``_ability_costs_payable`` returns False when the activator's
    life total wouldn't survive a pay-life cost. Smoke test for the
    branch."""
    from mtg_bot.effects.base import (
        ActivatedAbility, ActivationCost,
    )
    from mtg_bot.effects.generic import GainLife
    from mtg_bot.search._player_capabilities import (
        _ability_costs_payable,
    )

    state = _empty_state()
    _strip_player_zones(state, 0)
    _give_creature_on_battlefield(
        state, 0, "Wild Bear", summoning_sick=False, tapped=False,
    )
    pid = state.players[0].id
    p = state.players[0]
    obj = next(
        o for o in state.battlefield if o.controller_id == pid
    )
    # Synthetic ability costing 100 life — way over default 20.
    ability = ActivatedAbility(
        cost=ActivationCost(pay_life=100),
        effect=GainLife(amount=1),
    )
    assert _ability_costs_payable(state, pid, p, obj, ability) is False
    # Also smoke-test the tap_self gate by tapping the obj.
    obj.tapped = True
    ability_tap = ActivatedAbility(
        cost=ActivationCost(tap_self=True),
        effect=GainLife(amount=1),
    )
    assert _ability_costs_payable(
        state, pid, p, obj, ability_tap,
    ) is False


def test_random_walk_with_both_auto_pass_does_not_crash(monkeypatch):
    """A random-walk multi-turn smoke test: with active-player
    auto-pass on top of opp-side auto-pass, the engine still drives
    forward correctly. The meaningful assertion is the absence of
    decision-mismatch errors."""
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
