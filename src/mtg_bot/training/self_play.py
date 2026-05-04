"""Self-play harness: run N games at given configs, aggregate stats.

The existing ``mtg_bot.search.harness`` is generic and protocol-
shaped (works on toy games too). This module wraps it for the MTG-
specific tuning use case: deterministic seeding from a base seed,
hard decision cap so a stuck game can't hang the loop, and a
``MatchStats`` that tracks average decisions per game (useful for
spotting "this config plays infinite-loop games" without time-
profiling each one).

All state is built fresh per game — no shared engine state across
games. Both player slots get independent RNGs derived from the base
seed so the same call always produces the same result (essential
for comparing tuning runs).

Parallel mode: ``run_match_parallel`` distributes the N games
across a ``multiprocessing.Pool``. Per-game seeds are derived from
``game_idx``, not worker assignment, so the result is identical to
the sequential ``run_match`` for the same ``base_seed``.

Worker-crash resilience: the parallel path catches engine-level
exceptions inside each worker (state-corruption bugs that surface
~1-in-1000 games in PIMC self-play) and converts them to a
``(None, 0)`` "crashed" sentinel so a single bad game can't tank
the whole eval. The driver tracks crashed-game indices and emits a
loud stderr summary at the end of the run; the crashes are also
counted toward ``MatchStats.draws`` (consistent with how decision-
cap timeouts are counted — both represent "game didn't reach a
clean conclusion") so the total still satisfies
``wins[0] + wins[1] + draws == games``.
"""

from __future__ import annotations

import multiprocessing as mp
import os
import random
import sys
import traceback
from dataclasses import dataclass
from typing import Optional

from mtg_bot.agents import RandomAgent
from mtg_bot.decks import Deck
from mtg_bot.replay import save_replay
from mtg_bot.search.engine_adapter import MtgGameStateAdapter
from mtg_bot.search.protocol import CHANCE_PLAYER, PlayerID
from mtg_bot.simulate import setup_game
from mtg_bot.training._worker_threads import pin_worker_torch_threads
from mtg_bot.training.config import StrategyFactory
from mtg_bot.training.data_gen import (
    ReplayCaptureConfig, _now_iso, _sample_decks_for_game,
)
from mtg_bot.training.progress import EvalProgress
from mtg_bot.training.replay_capture import ReplayRecorder


# Hard cap on decisions per game. A pathological infinite priority
# loop (which has shown up before — see PIMC step-reentry bug) would
# otherwise hang the tuning loop. Real games are well under this; if
# we hit the cap, that's a bug.
_DEFAULT_DECISION_CAP = 4000


@dataclass(frozen=True)
class MatchStats:
    """Aggregate result of ``run_match``.

    ``wins[0]`` / ``wins[1]``: games player 0 / player 1 won.
    ``draws``: games that ended in a draw — i.e. the engine hit
    the ``decision_cap`` without a terminal state. Real MTG draws
    in our model are rare; most "draws" are decision-cap timeouts.
    ``games``: number of games that COMPLETED (wins + draws).
    Worker-crashed and per-game-timeout games are dropped from
    the dataset entirely — they contribute to ``crashed`` but
    NOT to ``wins`` / ``draws`` / ``games``. So the invariant is
    ``games == wins[0] + wins[1] + draws``, NOT ``== n_games``;
    the input ``n_games`` is the requested count, ``games`` is
    what actually contributed signal.
    ``crashed``: games dropped because a worker raised an
    exception (engine-state corruption — todo e3b7d9c1) or
    blew through the per-game wall-clock timeout (todo
    d4f2a8c1). Reported separately so the win-rate denominator
    isn't polluted by what amounts to "no signal".
    ``avg_decisions``: mean decisions across non-crashed games.
    Spots pathological game-length blowups even when the win
    rate looks fine.
    """

    wins: dict[PlayerID, int]
    draws: int
    games: int
    avg_decisions: float
    crashed: int = 0

    def win_rate(self, player_id: PlayerID) -> float:
        """Fraction of completed games ``player_id`` won. Draws
        count in the denominator (someone tied), but crashed /
        timed-out games are excluded entirely — they have no
        signal to contribute."""
        return self.wins.get(player_id, 0) / self.games if self.games else 0.0


def run_match(
    p0_factory: StrategyFactory,
    p1_factory: StrategyFactory,
    n_games: int,
    base_seed: int = 0,
    decision_cap: int = _DEFAULT_DECISION_CAP,
    enable_mulligans: bool = False,
    per_game_timeout_sec: Optional[float] = None,
    deck_pool: Optional[list[Deck]] = None,
    replay_config: Optional[ReplayCaptureConfig] = None,
    hang_dump_dir: Optional[str] = None,
) -> MatchStats:
    """Play ``n_games`` of ``p0_factory`` vs ``p1_factory`` and
    aggregate stats.

    Each game gets independent seeds derived from ``base_seed``:

    - Game ``i`` uses engine seed ``base_seed + i``.
    - P0's strategy is built with seed ``base_seed + 100*i``.
    - P1's strategy is built with seed ``base_seed + 100*i + 50``.
    - Chance-node sampling RNG uses seed ``base_seed + 100*i + 99``.

    The deterministic seeding means the same call produces the same
    result — essential for "does heuristic config A beat config B?"
    comparisons across tuning runs.
    """
    results = [
        _play_one_match_game(
            game_idx, p0_factory, p1_factory, base_seed, decision_cap,
            enable_mulligans, per_game_timeout_sec, deck_pool,
            replay_config, hang_dump_dir,
        )
        for game_idx in range(n_games)
    ]
    return _aggregate_results(results, n_games)


def run_match_parallel(
    p0_factory: StrategyFactory,
    p1_factory: StrategyFactory,
    n_games: int,
    base_seed: int = 0,
    decision_cap: int = _DEFAULT_DECISION_CAP,
    n_workers: Optional[int] = None,
    progress: Optional[EvalProgress] = None,
    enable_mulligans: bool = False,
    per_game_timeout_sec: Optional[float] = None,
    deck_pool: Optional[list[Deck]] = None,
    replay_config: Optional[ReplayCaptureConfig] = None,
    hang_dump_dir: Optional[str] = None,
    alternate_seats: bool = False,
) -> MatchStats:
    """Same contract as ``run_match`` but distributes games across a
    ``multiprocessing.Pool``.

    Identical output to the sequential function for the same
    ``base_seed`` — per-game seeds are derived from ``game_idx``,
    not worker assignment, so each game produces the same result
    no matter which worker plays it.

    ``n_workers`` defaults to ``cpu_count() - 2`` (leaves a few
    cores for OS / Python main / other work). Pass an explicit int
    to override.

    Caller note: factories must be picklable. Module-level functions
    and bound methods of picklable dataclasses work; lambdas and
    nested closures don't. The ``evaluate_nn`` CLI builds factories
    that pickle.

    Worker spawn cost on Windows is ~1-2s per worker, paid once per
    pool. Dominates wall-clock at very small ``n_games``; amortizes
    away past a few dozen games.

    When ``progress`` is supplied, results stream back via
    ``imap_unordered`` and the tracker is fed per-game so the UI
    sees live win-rate updates. The tracker is finalized
    ('completed' or 'failed') by this function before returning;
    the caller doesn't need to call ``finalize`` itself. With no
    progress tracker the legacy ``pool.map`` blocking path is used
    so existing callers keep their exact behavior (no per-game
    Python overhead).
    """
    if n_workers is None:
        n_workers = max(1, (os.cpu_count() or 1) - 2)
    if n_workers < 1:
        raise ValueError(f"n_workers must be >= 1, got {n_workers}")
    if n_games == 0:
        if progress is not None:
            progress.finalize(status="completed")
        return MatchStats(wins={0: 0, 1: 0}, draws=0, games=0, avg_decisions=0.0)

    args_list = [
        (i, p0_factory, p1_factory, base_seed, decision_cap,
         enable_mulligans, per_game_timeout_sec, deck_pool,
         replay_config, hang_dump_dir)
        for i in range(n_games)
    ]
    packed_worker = (
        _play_one_match_game_alternating_packed if alternate_seats
        else _play_one_match_game_packed
    )
    indexed_worker = (
        _play_one_match_game_alternating_indexed if alternate_seats
        else _play_one_match_game_indexed
    )
    if progress is None:
        with mp.Pool(processes=n_workers) as pool:
            results = pool.map(packed_worker, args_list)
        # ``_play_one_match_game_packed`` returns a ``(None, 0)``
        # sentinel for any worker-side crash. We re-pair each result
        # with its game_idx (preserved by pool.map's input ordering)
        # so the driver can log which games died and account for
        # them as draws — keeps ``wins+draws == n_games`` honest
        # rather than letting crashes silently disappear.
        crashed_game_indices = [
            i for i, (winner, decisions) in enumerate(results)
            if winner is None and decisions == 0
        ]
        _log_crashed_games(crashed_game_indices, n_games)
        return _aggregate_results(results, n_games)

    # Progress-tracked path: stream completions via imap_unordered.
    # Wrap args with the game_idx so we can re-sort for deterministic
    # aggregation (imap_unordered preserves identity but not order).
    progress.begin()
    indexed: list[tuple[int, tuple[Optional[PlayerID], int]]] = []
    crashed_game_indices: list[int] = []
    try:
        with mp.Pool(processes=n_workers) as pool:
            for game_idx, result in pool.imap_unordered(
                indexed_worker, args_list, chunksize=1,
            ):
                indexed.append((game_idx, result))
                winner, decisions = result
                # ``_play_one_match_game_indexed`` converts engine-
                # level worker crashes into a ``(None, 0)`` sentinel.
                # Surface them through the progress tracker as
                # ``crashed=True`` so the UI sees a dedicated counter
                # without polluting wins_new / wins_old / draws /
                # win_rate; remember the index so we can print a
                # loud stderr summary at the end of the run.
                crashed = winner is None and decisions == 0
                if crashed:
                    crashed_game_indices.append(game_idx)
                progress.record_game(
                    winner=winner, decisions=decisions, crashed=crashed,
                )
    except BaseException:
        progress.finalize(status="failed")
        raise
    progress.finalize(status="completed")
    _log_crashed_games(crashed_game_indices, n_games)
    indexed.sort(key=lambda t: t[0])
    return _aggregate_results([r for _, r in indexed], n_games)


def _log_crashed_games(crashed: list[int], n_games: int) -> None:
    """Print a loud stderr summary if any worker games crashed.

    Mirrors ``data_gen``'s post-pool warning: a silent partial-skip
    would mask the underlying engine bug (today's residual ~1/1000
    PIMC state-corruption bug). Crashed games are still counted as
    draws in ``MatchStats`` so the totals satisfy
    ``wins+draws == n_games``; this print is purely operator-facing.
    """
    if not crashed:
        return
    print(
        f"# WARNING: {len(crashed)}/{n_games} games crashed in the "
        f"eval pool and were dropped (engine state corruption — see "
        f"worker stderr above for tracebacks). Crashed games are "
        f"EXCLUDED from MatchStats — they don't pollute the win-rate "
        f"denominator; ``MatchStats.crashed`` carries the count "
        f"separately. Affected game indices: {crashed[:20]}"
        f"{' ...' if len(crashed) > 20 else ''}",
        file=sys.stderr,
    )


def _play_one_match_game_packed(
    args: tuple,
) -> tuple[Optional[PlayerID], int]:
    """Top-level pickleable worker. Unpacks the args tuple and
    delegates to ``_play_one_match_game``. Lives at module top
    level (not nested) so multiprocessing can pickle it across
    the spawn boundary.

    Engine-level errors (state-corruption bugs that surface at scale —
    ~1 in 1000 PIMC games as of 2026-05-02) are caught here and
    converted to a ``(None, 0)`` sentinel so a single bad game
    doesn't take down the entire eval pool. Without this catch,
    ``pool.map`` re-raises the worker exception and aborts the whole
    run, losing the ~99 games of useful data already played. The
    traceback is logged to worker stderr so failures stay visible
    via the pool's stderr relay; the driver re-detects the sentinel
    by ``winner is None and decisions == 0`` and surfaces a loud
    summary at the end of the run.

    Mirrors the worker-crash handling in
    ``mtg_bot.training.data_gen._play_one_parallel_game``.
    """
    game_idx = args[0]
    try:
        return _play_one_match_game(*args)
    except Exception as exc:  # noqa: BLE001 - intentional broad catch
        print(
            f"[worker] eval game {game_idx} crashed "
            f"({type(exc).__name__}: {exc}); dropping this game, "
            f"pool continues.",
            file=sys.stderr,
        )
        traceback.print_exc(file=sys.stderr)
        return None, 0


def _play_one_match_game_indexed(
    args: tuple,
) -> tuple[int, tuple[Optional[PlayerID], int]]:
    """Same as ``_play_one_match_game_packed`` but tags each result
    with its ``game_idx`` so the progress-tracked driver can re-sort
    ``imap_unordered`` results into deterministic input order before
    aggregating. The unindexed variant uses ``pool.map`` which
    preserves order on its own and doesn't need this tagging.

    Same worker-crash handling as the packed variant: engine-level
    exceptions are caught and converted to the ``(game_idx, (None, 0))``
    sentinel so one bad game doesn't tank the whole eval; the driver
    keys off ``winner is None and decisions == 0`` to detect crashes.
    """
    game_idx = args[0]
    try:
        return game_idx, _play_one_match_game(*args)
    except Exception as exc:  # noqa: BLE001 - intentional broad catch
        print(
            f"[worker] eval game {game_idx} crashed "
            f"({type(exc).__name__}: {exc}); dropping this game, "
            f"pool continues.",
            file=sys.stderr,
        )
        traceback.print_exc(file=sys.stderr)
        return game_idx, (None, 0)


def _play_one_match_game_alternating_packed(
    args: tuple,
) -> tuple[Optional[PlayerID], int]:
    """``pool.map`` counterpart to
    ``_play_one_match_game_alternating_indexed`` — same swap-on-odd-
    game_idx logic, no game_idx tagging in the return."""
    game_idx = args[0]
    if game_idx % 2 == 0:
        return _play_one_match_game_packed(args)
    swapped = (args[0], args[2], args[1], *args[3:])
    winner, decisions = _play_one_match_game_packed(swapped)
    remapped = None if winner is None else 1 - winner
    return remapped, decisions


def _play_one_match_game_alternating_indexed(
    args: tuple,
) -> tuple[int, tuple[Optional[PlayerID], int]]:
    """Like ``_play_one_match_game_indexed`` but neutralizes seat-
    order bias by playing odd-indexed games with the two factories
    swapped. The returned winner is remapped so seat 0 in the result
    always means "the original ``p0_factory`` won" — the caller
    aggregates wins[0]/wins[1] without needing to know about the
    swap.

    Use case: eval-gate matches where seat 0 has a structural engine
    advantage. v6-vs-v6 (identical NN) showed wins[0] = 77% on a
    500-game match without alternation; with alternation it should
    converge to 50% within stat noise.
    """
    game_idx = args[0]
    if game_idx % 2 == 0:
        return _play_one_match_game_indexed(args)
    swapped = (args[0], args[2], args[1], *args[3:])
    game_idx_returned, (winner, decisions) = (
        _play_one_match_game_indexed(swapped)
    )
    remapped = None if winner is None else 1 - winner
    return game_idx_returned, (remapped, decisions)


def _play_one_match_game(
    game_idx: int,
    p0_factory: StrategyFactory,
    p1_factory: StrategyFactory,
    base_seed: int,
    decision_cap: int,
    enable_mulligans: bool = False,
    per_game_timeout_sec: Optional[float] = None,
    deck_pool: Optional[list[Deck]] = None,
    replay_config: Optional[ReplayCaptureConfig] = None,
    hang_dump_dir: Optional[str] = None,
) -> tuple[Optional[PlayerID], int]:
    """Play one game and return ``(winner_or_None, decisions)``.
    Used by both the sequential and parallel match drivers — same
    seed derivation logic in both paths so the results match.

    When ``deck_pool`` is provided, two distinct decks are sampled
    per game (deterministic per ``(base_seed, game_idx)``); both
    seats use real archetypes from the pool. When ``None``, falls
    back to the legacy mono-color synthetic decks (G vs R), matching
    ``data_gen``'s back-compat default.

    When ``replay_config`` is supplied AND ``should_capture(game_idx)``
    returns True, snapshots are recorded after each priority moment
    and saved to ``replay_path(base_seed, game_idx)`` after the game
    completes. Mirrors data_gen's capture pattern so the same replay
    files / format are produced for self-play and eval games.
    """
    engine_seed = base_seed + game_idx
    seat_agents = [
        RandomAgent(rng=random.Random(engine_seed + 1)),
        RandomAgent(rng=random.Random(engine_seed + 2)),
    ]
    if deck_pool is not None:
        deck_p0, deck_p1 = _sample_decks_for_game(
            deck_pool, game_idx, base_seed,
        )
        engine = setup_game(
            seat_agents,
            decks=[deck_p0.cards, deck_p1.cards],
            seed=engine_seed,
            enable_mulligans=enable_mulligans,
        )
    else:
        engine = setup_game(
            seat_agents,
            ["G", "R"],
            seed=engine_seed,
            enable_mulligans=enable_mulligans,
        )
    adapter = MtgGameStateAdapter(engine, expose_combat_decisions=True)
    strategies = {
        0: p0_factory(base_seed + 100 * game_idx),
        1: p1_factory(base_seed + 100 * game_idx + 50),
    }
    # Pin torch CPU threads to 1 in this worker process. Strategy
    # factories that use the NN evaluator have just imported torch;
    # without this pin, every worker inherits the default of "host
    # CPU count" threads and 30 workers x 32 MKL threads thrash the
    # 32 host cores (~30-40% effective utilization). The trainer
    # has the analogous pin (commit 3ad808f); this is the worker-
    # side equivalent. No-op when torch isn't loaded (random /
    # heuristic strategies); idempotent across games.
    pin_worker_torch_threads()
    rng = random.Random(base_seed + 100 * game_idx + 99)

    recorder: Optional[ReplayRecorder] = None
    if replay_config is not None and replay_config.should_capture(game_idx):
        recorder = replay_config.build_recorder()
        # Capture the initial state too so the first scrubber frame
        # shows "before any actions taken." Mirrors data_gen.
        recorder.record(adapter.engine_state)

    if per_game_timeout_sec is not None and per_game_timeout_sec > 0:
        from mtg_bot.training._timeout import run_with_timeout
        try:
            winner, decisions = run_with_timeout(
                _play_capped_game,
                (adapter, strategies, rng, decision_cap, recorder),
                per_game_timeout_sec,
            )
        except TimeoutError as exc:
            # Drop a structured hang dump before the outer worker-
            # crash sentinel handler converts this to a (None, 0)
            # tuple. ``hang_dump_dir`` is opt-in; without it the
            # timeout still works exactly as before.
            if hang_dump_dir is not None:
                from mtg_bot.training._hang_dump import (
                    dump_hang_diagnostics,
                )
                dump_hang_diagnostics(
                    hang_dump_dir,
                    base_seed=base_seed,
                    game_idx=game_idx,
                    engine_seed=engine_seed,
                    error_type="TimeoutError",
                    error_message=str(exc),
                    extra={
                        "phase": "eval",
                        "decision_cap": decision_cap,
                        "enable_mulligans": enable_mulligans,
                        "per_game_timeout_sec": per_game_timeout_sec,
                    },
                )
            raise
    else:
        winner, decisions = _play_capped_game(
            adapter, strategies, rng, decision_cap, recorder,
        )

    if recorder is not None and replay_config is not None:
        replay = recorder.to_replay(metadata={
            "game_idx": game_idx,
            "base_seed": base_seed,
            "engine_seed": engine_seed,
            "winner": winner,
            "n_decisions": len(recorder.snapshots),
            "captured_at": _now_iso(),
            "annotated_with_nn_version": replay_config.nn_version_label,
        })
        save_replay(replay, replay_config.replay_path(base_seed, game_idx))

    return winner, decisions


def _aggregate_results(
    results: list[tuple[Optional[PlayerID], int]], n_games: int,
) -> MatchStats:
    """Aggregate per-game ``(winner_or_None, decisions)`` results
    into a ``MatchStats``.

    Distinguishes crashed/timed-out games (sentinel
    ``(None, 0)``) from real draws (``(None, decisions > 0)``,
    typically the decision-cap timeout from
    ``_play_capped_game``). Crashed games are EXCLUDED entirely
    from ``wins`` / ``draws`` / ``games`` / ``avg_decisions`` —
    they contribute zero signal so they shouldn't pollute the
    win rate. Counted separately under ``MatchStats.crashed`` so
    the loss isn't silent.
    """
    wins: dict[PlayerID, int] = {0: 0, 1: 0}
    draws = 0
    crashed = 0
    total_decisions = 0
    for winner, decisions in results:
        if winner is None and decisions == 0:
            # Worker crash or per-game timeout sentinel — drop.
            crashed += 1
            continue
        total_decisions += decisions
        if winner == 0:
            wins[0] += 1
        elif winner == 1:
            wins[1] += 1
        else:
            # Real draw: decision-cap timeout (winner=None,
            # decisions=decision_cap > 0).
            draws += 1
    completed = wins[0] + wins[1] + draws
    return MatchStats(
        wins=wins,
        draws=draws,
        games=completed,
        avg_decisions=total_decisions / completed if completed else 0.0,
        crashed=crashed,
    )


def _play_capped_game(
    adapter: MtgGameStateAdapter,
    strategies: dict[PlayerID, "object"],
    rng: random.Random,
    decision_cap: int,
    replay_recorder: Optional[ReplayRecorder] = None,
) -> tuple[PlayerID | None, int]:
    """Play one game with a hard decision cap. Returns
    ``(winner_id_or_None, decisions_made)``. If the cap is hit
    without termination, returns ``(None, decision_cap)`` — caller
    counts that as a draw.

    When ``replay_recorder`` is supplied, captures a snapshot of
    the engine state after each applied decision (the initial
    pre-action state is captured by the caller). Snapshot cost is
    ~5 ms per priority moment, dwarfed by typical PIMC decision
    time, so capture-on means a small wall-clock hit but no skew.
    """
    decisions = 0
    while not adapter.is_terminal() and decisions < decision_cap:
        active = adapter.active_player()
        if active == CHANCE_PLAYER:
            outcomes = adapter.chance_outcomes()
            choices = [d for d, _ in outcomes]
            weights = [w for _, w in outcomes]
            decision = rng.choices(choices, weights=weights, k=1)[0]
        else:
            decision = strategies[active].choose(adapter, active)
        adapter.apply(decision)
        decisions += 1
        if replay_recorder is not None:
            replay_recorder.record(adapter.engine_state)
    if adapter.is_terminal():
        return adapter.winner(), decisions
    return None, decisions
