"""Belief-weighted determinization for ISMCTS (Phase 6).

A particle-filter sampler that draws determinizations from the
posterior over opponent hidden state, conditioned on the opponent's
observed action history. Replaces the uniform sampler in
``mtg_bot.search.determinize`` for the ``ISMCTS.determinize_fn``
callback. See ``docs/ISMCTS_MIGRATION.md`` (Phase 6) for the design
spec and ``docs/PHASE6_SNAPSHOT_AUDIT.md`` for why the priority-moment
log is supplied in-memory by the caller rather than read from disk.

Bayesian setup. For a candidate hidden-info hypothesis ``H`` (one
sampled determinization) and the opponent's observed action sequence
``A = (a_1, ..., a_T)`` taken at priority moments ``s_1, ..., s_T``::

    P(H | A) ∝ P(A | H) P(H)
    log P(A | H) = sum_t log P(a_t | s_t, H)

The prior ``P(H)`` is the uniform sampler we already have. The
likelihood ``P(a_t | s_t, H)`` comes from the trained policy head:
reconstruct the historical state with hand identities consistent
with ``H``, masked-softmax over the legal-action vocab, read off the
slot encoding ``a_t``.

The class generates ``m_candidates`` uniform draws, scores each by
log-likelihood (with a floor on zero-probability slots so a single
inconsistent action doesn't annihilate a particle), normalizes via
log-sum-exp, and resamples one. Returns the chosen
``MtgGameStateAdapter`` — same callback shape ISMCTS already invokes.

Historical-state reconstruction strategy. Each candidate is
materially identified by an integer particle seed; the same seed is
re-used to determinize a clone of each historical priority-moment
state. This is the "sample-and-project" approach in the audit's open
question 2: rather than time-rewind a fixed candidate hand to align
with each historical opponent zone shape, we re-determinize each
historical clone with the candidate's seed. The seed encodes the
particle's RNG identity; downstream effects of "this particle drew
permutation X at the root" propagate into "this particle's reading of
historical moment t" coherently because both are determinizations
sharing one ``random.Random(seed)`` per particle. This sidesteps the
zone-shape mismatch problem that arises when the candidate's
current-state hand is a subset/superset of the historical hand.

Caching. The likelihood evaluation reads from the cloned-and-
determinized historical state through ``opponent_policy_evaluator
.evaluate_logits`` plus ``action_encoding.legal_action_mask``. Calls
that share the same (printings tuple, history index) tuple return
identical results, so an LRU-bounded dict keyed on that pair holds
``(value, logits)`` and the legal mask. The eviction policy is FIFO
once the cache exceeds ``cache_max_size``; this is "good enough"
since the access pattern is heavily weighted toward recent particles
within a single ``__call__`` and we don't need true LRU semantics.

Numerical hygiene. All log-likelihood accumulation is in log-space.
Zero-probability action slots get floored at ``log(1e-12)`` to keep
the particle alive with a soft penalty rather than collapsing to
``-inf`` (Cowling et al. 2015 §4 discuss this; the floor is a soft
penalty, not absolute exclusion). Effective sample size is computed
post-normalization; values below ``ess_warn_threshold`` are surfaced
through the ``last_ess`` attribute for caller-side diagnostics
without changing search behavior — for Phase 6 this is informational.
"""

from __future__ import annotations

import math
import random
from collections import OrderedDict
from typing import Any, Callable, Optional, Sequence

import numpy as np

from mtg_bot.game import GameState as EngineGameState
from mtg_bot.search.determinize import determinize as _uniform_determinize
from mtg_bot.search.engine_adapter import MtgGameStateAdapter
from mtg_bot.search.protocol import Decision, PlayerID

# Floor for log-probability of an action that has zero probability
# under a candidate hand. log(1e-12) ≈ -27.6. Keeps the particle
# alive at a heavy but finite penalty instead of total elimination.
_LOG_PROB_FLOOR = math.log(1e-12)


class PriorityMoment:
    """One historical opponent priority moment.

    Stored in the in-memory log the caller maintains. Holds the
    pre-action engine state clone (``state``), the action that was
    actually taken (``decision``), and the player who held priority
    (``actor``). The state clone is a real ``EngineGameState`` — not
    a serialized snapshot — so the per-particle re-determinization
    can call into the engine's clone/legal_action machinery without
    deserialization. The audit (option (b)) recommends this in-memory
    representation; it is not written to disk.
    """

    __slots__ = ("state", "decision", "actor")

    def __init__(
        self,
        state: EngineGameState,
        decision: Decision,
        actor: PlayerID,
    ) -> None:
        self.state = state
        self.decision = decision
        self.actor = actor


class BeliefWeightedDeterminizer:
    """Particle-filter sampler over hidden-info hypotheses about the
    opponent.

    Use as a drop-in for ``ISMCTS(determinize_fn=...)``. With an
    empty ``played_history`` the sampler degenerates to the uniform
    sampler (posterior = prior). With a non-empty history each
    candidate's log-weight is the sum of historical-action log-
    probabilities under the candidate's hidden state, evaluated by
    the supplied ``opponent_policy_evaluator``.

    The callback contract matches the uniform determinizer:
    ``__call__(engine_state, viewer_id, rng, in_place=True)``
    returns one ``EngineGameState`` (in-place mutation of the input
    when ``in_place=True``). ISMCTS calls it once per iteration.
    """

    def __init__(
        self,
        opponent_policy_evaluator: Any,
        played_history: Optional[Sequence[PriorityMoment]] = None,
        m_candidates: int = 64,
        cache_max_size: int = 4096,
        log_prob_floor: float = _LOG_PROB_FLOOR,
        ess_warn_threshold: float = 1.0,
    ) -> None:
        """Construct the sampler.

        ``opponent_policy_evaluator`` must expose ``evaluate_logits(
        state, player_id) → (value, logits)`` — the same shape
        ``NNEvaluator(with_policy=True)`` and the test stubs in
        ``test_ismcts.py`` implement.

        ``played_history`` is the in-memory list of opponent priority
        moments collected by the caller as the game progresses. An
        empty / ``None`` history short-circuits to uniform sampling.
        Each entry is a ``PriorityMoment`` — see that class for the
        required shape. The caller is responsible for populating this
        log; this module never reads on-disk replay files.

        ``m_candidates`` controls the proposal pool size. Higher is a
        better posterior approximation at higher cost; the cost is
        ``O(m_candidates * len(played_history))`` policy queries per
        ``__call__``, mitigated by the cache.

        ``cache_max_size`` bounds the ((hand_names, library_names),
        history_index) cache. FIFO eviction;
        ``OrderedDict.popitem(last=False)``.

        ``log_prob_floor`` is the minimum log-probability assigned to
        an action with zero probability under a candidate hand —
        typically because the candidate determinization makes the
        opponent's actual action illegal in the reconstructed state.
        Defaults to log(1e-12); larger floors weaken the prior, smaller
        ones approximate hard exclusion.

        ``ess_warn_threshold`` is the effective-sample-size floor
        below which the particle filter is flagged as degenerate;
        ``last_ess`` is set on each ``__call__`` and a value
        ``< ess_warn_threshold`` is informational for now.
        """
        if m_candidates < 1:
            raise ValueError(
                f"m_candidates must be >= 1, got {m_candidates!r}"
            )
        if cache_max_size < 1:
            raise ValueError(
                f"cache_max_size must be >= 1, got {cache_max_size!r}"
            )
        if not callable(getattr(
            opponent_policy_evaluator, "evaluate_logits", None,
        )):
            raise ValueError(
                "opponent_policy_evaluator must expose "
                "evaluate_logits(state, player_id); got "
                f"{type(opponent_policy_evaluator).__name__}."
            )
        self.opponent_policy_evaluator = opponent_policy_evaluator
        self.played_history: tuple[PriorityMoment, ...] = tuple(
            played_history or (),
        )
        self.m_candidates = m_candidates
        self.cache_max_size = cache_max_size
        self.log_prob_floor = log_prob_floor
        self.ess_warn_threshold = ess_warn_threshold
        # FIFO cache keyed on (opponent_hand_printings_tuple,
        # history_index) → (legal_mask, logits). Uses an OrderedDict
        # so popitem(last=False) gives FIFO eviction, no extra
        # bookkeeping.
        self._cache: "OrderedDict[tuple[Any, ...], tuple[np.ndarray, np.ndarray]]" = (
            OrderedDict()
        )
        # Diagnostic counters reset on every ``__call__``.
        self.last_ess: float = 0.0
        self.last_evaluator_calls: int = 0

    # ------------------------------------------------------------------
    # Determinizer-callback surface
    # ------------------------------------------------------------------

    def __call__(
        self,
        engine_state: EngineGameState,
        viewer_id: PlayerID,
        rng: random.Random,
        *,
        in_place: bool = False,
    ) -> EngineGameState:
        """Sample one belief-weighted determinization.

        Mirrors the ``determinize.determinize`` signature so it's a
        drop-in for ``ISMCTS.determinize_fn``. With an empty
        ``played_history`` returns ``determinize(engine_state,
        viewer_id, rng, in_place=in_place)`` — the prior IS the
        uniform sampler.

        Otherwise: draws ``m_candidates`` particle seeds, scores each
        by log-likelihood under ``played_history``, normalizes, and
        resamples one particle. The chosen particle's seed is then
        applied (via ``determinize``) to the input state.

        ``in_place=True`` mutates ``engine_state``; ``in_place=False``
        clones first. Same convention as the uniform determinizer.
        """
        # Reset per-call diagnostics.
        self.last_evaluator_calls = 0

        if not self.played_history:
            # No history → posterior == prior. Uniform sampler is the
            # MLE / sole correct answer; skip the particle-filter
            # plumbing.
            self.last_ess = float(self.m_candidates)
            return _uniform_determinize(
                engine_state, viewer_id, rng, in_place=in_place,
            )

        # Each particle is identified by an independent seed drawn
        # from ``rng``. Drawing seeds (rather than passing ``rng``
        # directly to each determinization) keeps the particles
        # independently reproducible and lets the resampling step
        # pick a particle by replaying its seed.
        seeds = [rng.randrange(1 << 62) for _ in range(self.m_candidates)]
        log_weights = np.empty(self.m_candidates, dtype=np.float64)
        for i, seed in enumerate(seeds):
            log_weights[i] = self._score_particle(
                engine_state, viewer_id, seed,
            )

        normalized = _normalize_log_weights(log_weights)
        self.last_ess = _effective_sample_size(normalized)

        # Sample one particle index from the categorical(normalized).
        # ``rng.random()`` is the user-supplied stream; using it
        # (instead of np.random) keeps the whole sampler reproducible
        # under the caller's seed.
        chosen_idx = _categorical_draw(normalized, rng)
        chosen_seed = seeds[chosen_idx]

        # Re-apply the chosen particle's seed to the input state.
        # ``random.Random(seed)`` reproduces the determinization
        # (printing permutation) we scored.
        return _uniform_determinize(
            engine_state, viewer_id,
            random.Random(chosen_seed),
            in_place=in_place,
        )

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def _score_particle(
        self,
        engine_state: EngineGameState,
        viewer_id: PlayerID,
        seed: int,
    ) -> float:
        """Return ``log P(played_history | particle)``.

        For each historical priority moment whose actor is NOT
        ``viewer_id`` (i.e. an opponent priority moment), clone the
        historical state, re-determinize it under the particle's seed,
        evaluate the opponent NN's policy at the reconstructed state,
        and add ``log P(action_taken)``. Sum across moments.

        Viewer-action moments are SKIPPED — the played_history log
        captures every priority moment in the game (game loops can't
        easily filter at append time without knowing the search
        viewer), and only opponent moments contribute likelihood
        signal under the Bayesian setup. The viewer's own actions are
        deterministic from the viewer's perspective (the viewer chose
        them with full information about their own hand) so
        P(viewer_action | candidate_opponent_hand) is independent of
        the candidate and contributes nothing to the posterior weight.

        Cache hits skip the evaluator call. Cache key is the opponent
        hand's printing tuple at the reconstructed state plus the
        history index; same hand at the same moment → same NN call →
        same policy distribution.
        """
        from mtg_bot.training import action_encoding as ae

        log_likelihood = 0.0
        for h_idx, moment in enumerate(self.played_history):
            if moment.actor == viewer_id:
                continue
            opponent = moment.actor
            # Per-moment determinization. The first moment (h_idx=0)
            # uses the particle's seed unmixed so its permutation is
            # the same one applied at the current state in
            # ``__call__``'s resample step — that's what makes the
            # particle a coherent "hidden hand hypothesis" rather
            # than just an RNG identifier. Subsequent moments mix in
            # ``h_idx`` so the same particle yields distinct (but
            # reproducible) permutations across moments; without the
            # mix every moment's permutation would be identical
            # modulo zone shape and the per-moment likelihoods would
            # be redundant.
            if h_idx == 0:
                moment_rng = random.Random(seed)
            else:
                mix = (
                    seed * 0x9E3779B97F4A7C15 + h_idx
                ) & ((1 << 63) - 1)
                moment_rng = random.Random(mix)
            reconstructed = moment.state.clone()
            _uniform_determinize(
                reconstructed, viewer_id, moment_rng, in_place=True,
            )
            hand_key = _opponent_hand_key(reconstructed, opponent)
            cache_key = (hand_key, h_idx)
            cached = self._cache.get(cache_key)
            if cached is None:
                # ``evaluate_logits`` calls ``state.is_terminal()`` on
                # the input — that's an adapter method, so wrap the
                # raw engine state in an adapter before passing.
                value, logits = (
                    self.opponent_policy_evaluator.evaluate_logits(
                        MtgGameStateAdapter(reconstructed), opponent,
                    )
                )
                # ``value`` is unused for the policy likelihood;
                # ``logits`` is the raw policy head.
                _ = value
                mask = ae.legal_action_mask(reconstructed, opponent)
                self._cache[cache_key] = (mask, logits)
                self._evict_if_oversize()
                self.last_evaluator_calls += 1
            else:
                mask, logits = cached
                # Re-touch for FIFO-vs-LRU hybrid: an entry just
                # accessed gets bumped to the end so FIFO eviction
                # behaves like simple LRU when access patterns favor
                # recent entries. Cheap; doesn't change correctness.
                self._cache.move_to_end(cache_key)

            try:
                slot = ae.encode(
                    moment.decision, reconstructed, opponent,
                )
            except ae.EncodingOverflowError:
                # The action's slot is unreachable in this candidate
                # — equivalent to zero probability under the policy
                # (the network can't represent it). Floor the log-
                # probability and continue.
                log_likelihood += self.log_prob_floor
                continue
            except Exception:
                # Other encoding errors (e.g. zone mismatch under
                # candidate determinization) — same handling: floor.
                log_likelihood += self.log_prob_floor
                continue

            log_p = _slot_log_prob(
                logits, mask, slot, self.log_prob_floor,
            )
            log_likelihood += log_p
        return log_likelihood

    def _evict_if_oversize(self) -> None:
        while len(self._cache) > self.cache_max_size:
            self._cache.popitem(last=False)


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def _opponent_hand_key(
    state: EngineGameState, opponent: PlayerID,
) -> tuple[Any, ...]:
    """Cache key built from the opponent's hand + library printing
    NAMES (in zone order). Library order matters because the NN may
    consult library top via features (we don't know which features it
    uses, so be conservative). Including library order trades a bit
    of cache-miss rate for correctness.

    We key by ``printing.name`` rather than the printing object
    itself: at least one ``CardPrinting`` field (``StaticAbility`` ->
    ``ReplacementEffect`` -> ``EventPattern.subject_filters``, a
    ``Mapping`` defaulting to ``dict``) is mutably-typed and breaks
    ``hash``. Names are unique per card and ``extract_features`` only
    reads identity-equivalent fields, so name keys are sufficient.
    Fixing ``EventPattern.subject_filters`` to a frozen container is
    the right structural fix; tracked as a follow-up.
    """
    player = state.players[opponent]
    hand = tuple(c.printing.name for c in player.hand)
    library = tuple(c.printing.name for c in player.library)
    return (hand, library)


def _slot_log_prob(
    logits: np.ndarray,
    mask: np.ndarray,
    slot: int,
    floor: float,
) -> float:
    """Compute ``log P(slot)`` under the masked-softmax policy.

    Returns ``floor`` when the slot is masked illegal or when the
    softmax has no support (no legal slots). Otherwise computes
    log-softmax in the numerically-safe form (subtract max, log-sum-
    exp) and returns the slot's component.
    """
    if slot < 0 or slot >= logits.shape[0]:
        return floor
    if not bool(mask[slot]):
        return floor
    if not mask.any():
        return floor
    # Apply mask as -inf in a working copy.
    row = logits.astype(np.float64, copy=True)
    row[~mask] = -np.inf
    row_max = float(row.max())
    if not math.isfinite(row_max):
        return floor
    shifted = row - row_max
    # Slot's pre-softmax shifted logit; normalize via log-sum-exp.
    log_z = math.log(float(np.exp(shifted).sum()))
    log_p = float(shifted[slot]) - log_z
    if not math.isfinite(log_p):
        return floor
    if log_p < floor:
        return floor
    return log_p


def _normalize_log_weights(log_weights: np.ndarray) -> np.ndarray:
    """Convert log-weights to a normalized probability vector via
    log-sum-exp. Returns a length-N float64 vector summing to 1.

    All-``-inf`` input degrades to a uniform distribution: that's the
    "no particle has any support" pathological case; uniform is the
    least-bad fallback (and surfaces via ``last_ess == N``).
    """
    finite_mask = np.isfinite(log_weights)
    if not finite_mask.any():
        n = log_weights.shape[0]
        return np.full(n, 1.0 / n, dtype=np.float64)
    max_lw = float(log_weights[finite_mask].max())
    shifted = log_weights - max_lw
    # ``-inf`` after shift → exp = 0, drops out of the sum.
    weights = np.exp(shifted)
    z = float(weights.sum())
    if z <= 0.0 or not math.isfinite(z):
        n = log_weights.shape[0]
        return np.full(n, 1.0 / n, dtype=np.float64)
    return (weights / z).astype(np.float64, copy=False)


def _effective_sample_size(normalized: np.ndarray) -> float:
    """Kish's effective sample size: ``1 / sum(p_i^2)``. Range
    [1, N]; N = uniform, 1 = all weight on one particle. Used as a
    degeneracy monitor — Phase 6 surfaces this for diagnostics; later
    phases would trigger stratified resampling on low ESS.
    """
    s = float(np.square(normalized).sum())
    if s <= 0.0:
        return 0.0
    return 1.0 / s


def _categorical_draw(
    probabilities: np.ndarray, rng: random.Random,
) -> int:
    """Sample one index from a categorical distribution using
    ``rng.random()`` for reproducibility under the caller's seed.

    Inverse-CDF sampling: cumulate probabilities, draw u in [0, 1),
    return the first index with cumsum > u. O(N) worst case;
    ``m_candidates`` is small (default 64) so this is negligible.
    """
    u = rng.random()
    cumulative = 0.0
    last = probabilities.shape[0] - 1
    for i, p in enumerate(probabilities):
        cumulative += float(p)
        if u < cumulative:
            return i
    # Floating-point safety net: if u landed past the last cumulative
    # due to rounding, return the last index.
    return last


__all__ = [
    "BeliefWeightedDeterminizer",
    "PriorityMoment",
]
