"""Phase 6 trajectory-parity helpers.

Sibling module to :mod:`mtg_bot.parity.cross_engine`. The cross-engine
module ships the per-step / per-action primitives (``build_matched_states``,
``step_both``, ``advance_phase_python``, the family of ``*_selector``
functions, the field-view differ); this module ships the *real-game-shaped*
primitives that drive multi-turn trajectory probes.

Surface (Phase 6 round-13 + round-14 slices):

* :func:`setup_matched_game` — closes infrastructure gap #1 from
  ``docs/PHASE6_TRAJECTORY_PARITY.md``: a single ``(decks, seed,
  mulligans=...)`` entrypoint that produces a parity-synced opening
  state on both engines. Wraps :func:`cross_engine.build_matched_states`
  and the side-channel opening-hand draw.
* :class:`MulliganDeterministicAgent` — Round-14 closure (gap #2): a
  deterministic cross-engine mulligan agent that produces matching
  keep/mulligan + bottom-pick decisions on both Python and Rust. The
  default policy is ``mulligan_target_hand_size=7`` (always keep at 7,
  never mulligan); pass a smaller value to mulligan exactly to that
  size. Bottom-picks are positional (``hand[0..n]``) so they're
  trivially reproducible across engines.

What this module deliberately does NOT cover:

* **Decision-callback mulligans.** The agent surface here is config-
  driven (mulligan to N, bottom by position). It is NOT a full
  ``Agent.choose_mulligan`` / ``Agent.choose_bottom`` bridge — those
  agents make state-conditional decisions, and getting state-
  conditional cross-engine agreement requires either (a) the SAME
  agent instance making the decision and routing it to both engines,
  or (b) two agents that always agree on the same hand. The
  deterministic agent is the (a) path: one agent, one decision per
  iteration, applied to both engines.
* **Real ``mtg_bot.simulate.setup_game`` mirror.** Production
  ``setup_game`` constructs Players via ``_build_player_from_names``,
  which materializes printings out of the *active card source*
  (Scryfall-loaded printings). The cross-engine harness already has
  its own per-DeckSpec card-pool plumbing; this slice builds on that
  plumbing rather than the production printings dict so the harness
  can drive synthetic ``CardDef`` decks (the only deck shape Phase 5
  + 6 actually probe).

The natural follow-up: a ``setup_matched_game_from_real_decks(decks,
seed, mulligans=...)`` that accepts decklist *names* against the live
``mtg_bot.cards.printings`` dict and threads them into a freshly-
materialized DeckSpec. That's a Phase 6 follow-on once the trajectory
suite outgrows hand-rolled CardDef registries.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Optional

from mtg_bot.parity.cross_engine import (
    DeckSpec,
    build_matched_states,
)


__all__ = ["setup_matched_game", "MulliganDeterministicAgent"]


@dataclass(frozen=True)
class MulliganDeterministicAgent:
    """Cross-engine deterministic mulligan policy.

    A config-driven decision source that produces byte-identical
    keep/mulligan + bottom-pick decisions on both Python and Rust.
    Closes Phase 6 infrastructure gap #2: any state-conditional
    ``Agent.choose_mulligan`` would need a state-equivalent decision
    on both engines, but a config-driven agent ("mulligan exactly
    until hand_size==N, then bottom by position") sidesteps the
    state-equivalence question entirely — the agent makes the same
    decision regardless of which side's hand it's looking at.

    Parameters
    ----------
    target_hand_size : int, default 7
        Number of cards the player should END UP HOLDING after all
        mulligans + bottoming. ``target_hand_size=7`` means "never
        mulligan" (each player keeps the initial 7). ``target_hand_size
        =6`` means "mulligan exactly once and bottom 1". ``=5`` means
        "mulligan twice and bottom 2". Etc. Must be in ``[0, 7]``.
        The London-mulligan rule (CR 103.4) bottoms ``mulls_taken``
        cards on keep, so the final hand size is always
        ``7 - mulls_taken``.
    bottom_strategy : str, default "first"
        Which cards to put on the bottom after the final keep. Only
        ``"first"`` is supported in this slice — bottoms ``hand[0..n]``
        in insertion order. Trivial to reproduce on Rust because hand
        order is byte-equal across engines after the shared-RNG shuffle.
        A ``"last"`` / ``"by_id_descending"`` variant is a one-line
        addition if a future test needs it; ``"first"`` is the default
        because it matches Rust's own
        ``bottom_cards_from_hand``-by-position default.

    Notes
    -----
    The agent does NOT consume any RNG state. The randomness in the
    mulligan loop comes from the *shared RNG instance* threaded into
    each engine's shuffle primitive (``random.Random(seed)._randbelow``
    in both Rust's ``mulligan_atomic(rng=)`` path and Python's local
    Fisher-Yates). The agent only governs the policy decisions
    (mulligan/keep, which cards to bottom), not the shuffle outcome.

    This separation keeps the agent reproducible regardless of seed —
    two calls with ``target_hand_size=5`` always mulligan twice, no
    matter what cards land in hand.
    """

    target_hand_size: int = 7
    bottom_strategy: str = "first"

    def __post_init__(self) -> None:  # pragma: no cover — frozen guard
        # frozen=True forbids __setattr__, so __post_init__ is a no-op
        # validate-only hook. Raise on construction with a bad config.
        if not (0 <= self.target_hand_size <= 7):
            raise ValueError(
                f"target_hand_size must be in [0, 7], got "
                f"{self.target_hand_size}"
            )
        if self.bottom_strategy != "first":
            raise ValueError(
                f"bottom_strategy={self.bottom_strategy!r} not supported. "
                f"Only 'first' is implemented in this slice."
            )

    @property
    def mulligans_to_take(self) -> int:
        """Number of mulligans this agent will run before keeping.

        ``7 - target_hand_size`` per the London-mulligan rule. A
        target of 7 means 0 mulligans; target 5 means 2 mulligans
        (then bottom 2 cards on keep).
        """
        return 7 - self.target_hand_size

    def should_mulligan(self, mulls_taken: int) -> bool:
        """Decision: should the player mulligan again?

        Returns True until ``mulls_taken`` reaches the configured
        ``mulligans_to_take``, then False (keep). Stateless — the
        decision is a pure function of the agent's config and the
        current mulligan count.
        """
        return mulls_taken < self.mulligans_to_take

    def pick_bottom(self, hand_ids: list[int], n: int) -> list[int]:
        """Pick ``n`` card ids from ``hand_ids`` to put on the bottom.

        With ``bottom_strategy="first"`` (the only currently-supported
        strategy), returns ``hand_ids[:n]`` — the first ``n`` cards
        in hand-insertion order.
        """
        if n == 0:
            return []
        if n > len(hand_ids):
            raise ValueError(
                f"pick_bottom: requested {n} cards but hand has only "
                f"{len(hand_ids)}"
            )
        return list(hand_ids[:n])


def _draw_opening_hand_both(py_state, rust_state, n: int = 7) -> None:
    """Mirror real-game ``setup_game``'s seven-card opening draw on BOTH engines.

    Phase 5's CE3 closure proved Python's ``turn.draw_card`` + Rust's
    ``draw_card`` pymethod produce byte-equal hand/library views when
    both libraries start at the same permutation. This helper just
    fires that draw ``n`` times per player.

    Internal helper — :func:`setup_matched_game` is the public entry.
    """
    from mtg_bot.turn import draw_card as py_draw_card

    for pid in (0, 1):
        for _ in range(n):
            py_draw_card(py_state, pid)
            rust_state.draw_card(pid)


def _python_mulligan_iteration(py_state, player_id: int, rng) -> None:
    """One mulligan iteration on the PYTHON side.

    Mirrors Rust's ``mulligan_atomic`` shuffle+redraw step (the bottom
    step is applied separately by :func:`_python_bottom_cards`). Drains
    ``player_id``'s hand back into the library, runs Python's
    ``random.Random.shuffle`` on the library using the SHARED ``rng``
    instance (which is the same instance Rust's ``mulligan_atomic``
    consumes via ``_randbelow``), then redraws 7 cards.

    Both engines call ``rng.shuffle(<library_list>)`` (Python directly,
    Rust via ``_randbelow`` callback in Fisher-Yates). Because the
    rng instance is shared and the pre-shuffle library order is byte-
    equal on both engines, the post-shuffle libraries will be
    byte-equal as well.

    The internal-state mutation here mirrors
    ``mtg_bot.simulate.setup_game``'s mulligan-redraw block (lines
    160-170 of simulate.py) verbatim — same drain, same shuffle, same
    redraw — except it consumes the shared external rng rather than
    setup_game's local one.
    """
    from mtg_bot.game import Zone
    from mtg_bot.turn import draw_card as py_draw_card

    p = py_state.players[player_id]
    # Drain hand into library in HAND-INSERTION order (hand[0] first,
    # hand[6] last). Rust's mulligan_to_n / mulligan_atomic uses
    # ``hand.drain(..)`` which yields entries in insertion order; we
    # mirror that exactly so the pre-shuffle library tail order matches
    # across engines. (NOTE: this differs from Python's
    # mtg_bot.simulate.setup_game which uses ``p.hand.pop()`` (LIFO);
    # the cross-engine path needs the FIFO order to match Rust.)
    returning = list(p.hand)
    p.hand.clear()
    for card in returning:
        card.zone = Zone.LIBRARY
        p.library.append(card)
    # Shared-rng shuffle. random.shuffle consumes _randbelow in
    # Fisher-Yates order, matching Rust's mulligan_atomic(rng=...)
    # consumption order.
    rng.shuffle(p.library)
    # Redraw 7 (or until empty).
    for _ in range(7):
        if not p.library:
            break
        py_draw_card(py_state, player_id)


def _python_bottom_cards(py_state, player_id: int, bottom_ids: list[int]) -> None:
    """Apply the post-mulligan bottom step on the PYTHON side.

    Mirrors Rust's ``bottom_cards_from_hand`` orientation: the FIRST
    id in ``bottom_ids`` ends up at the very BOTTOM of the library
    (last index), each subsequent id sits one slot above.
    Implementation: walk ids in reverse and ``library.append`` each —
    the last-walked (= first-supplied) lands at the tail.

    Per-instance state reset matches Rust's ``bottom_cards_from_hand``:
    ``tapped=False``, ``summoning_sick=False``, ``damage=0``, plus
    counters / attachments cleared. Without this reset, a hand card
    carrying ``summoning_sick=True`` (the default for cards just
    drawn to hand on Python) would keep that flag in the library
    while Rust would not — surfacing as a per-object field divergence
    on the very last cards of the library after bottoming.
    """
    from mtg_bot.game import Zone

    p = py_state.players[player_id]
    by_id = {c.id: c for c in p.hand}
    for oid in reversed(bottom_ids):
        card = by_id[oid]
        p.hand.remove(card)
        card.zone = Zone.LIBRARY
        # Mirror Rust's per-instance reset on bottom (CR-equivalent
        # cleanup: a card moving from hand to library can't legally
        # carry battlefield-only state; defensive against future
        # paths that might leave stale flags).
        card.tapped = False
        card.summoning_sick = False
        card.damage = 0
        # ``counters`` on the Python side is a list (vs Rust's int).
        # Empty it out to match the int=0 reset semantically.
        if hasattr(card, "counters") and isinstance(card.counters, list):
            card.counters.clear()
        if hasattr(card, "attached_to"):
            card.attached_to = None
        p.library.append(card)


def _run_mulligan_loop_both(
    py_state,
    rust_state,
    agent: MulliganDeterministicAgent,
    base_seed: int,
) -> None:
    """Drive the mulligan loop on BOTH engines for both players.

    Per-player loop:

    1. Ask the agent ``should_mulligan(mulls_taken)``. If False, exit
       to step 4.
    2. Construct two ``random.Random(iter_seed)`` instances — one for
       Python's local Fisher-Yates, one for Rust's ``mulligan_to_n``.
       Both seeds derive deterministically from
       ``(base_seed, player_id, mulls_taken)``. Two ``random.Random``
       instances seeded identically produce bit-identical
       ``_randbelow`` sequences (MT determinism), so the in-mulligan
       shuffle on each engine consumes the same draw order.
    3. Fire shuffle+redraw on both engines. Increment ``mulls_taken``.
       Loop to 1.
    4. Pick ``mulls_taken`` bottom ids via ``agent.pick_bottom``. Apply
       on both engines: Python via :func:`_python_bottom_cards`, Rust
       via ``bottom_cards_from_hand(n=mulls_taken)`` which bottoms
       hand[0..n] by position.

    Why ``mulligan_to_n`` for intermediate iterations and a separate
    ``bottom_cards_from_hand`` for the final keep, rather than Rust's
    parity-canonical ``mulligan_atomic``? Two reasons:

    * ``mulligan_atomic`` requires ``bottom_card_ids.len() ==
      mulligan_count + 1``, so an N-mulligan loop would need to bottom
      progressively-larger sets on each iteration even though only the
      LAST iteration's bottom is meaningful.
    * Splitting shuffle+redraw from bottom mirrors Python's
      ``simulate.setup_game`` mulligan-loop shape exactly (intermediate
      iterations are shuffle+redraw only; bottom fires once on keep).

    The split-call path consumes one Rust ``mulligan_count`` slot per
    mulligan, same as ``mulligan_atomic`` would; the per-call cap of 7
    still holds. With ``bottom_strategy="first"`` (the only currently-
    supported strategy), Rust's positional ``bottom_cards_from_hand(n)``
    is exactly equivalent to the agent's ``pick_bottom(hand_ids, n)``
    returning ``hand_ids[:n]``, so the chosen-by-id and chosen-by-
    position results agree.

    A future non-positional bottom strategy (e.g. "highest mana value
    first") would need either Rust hand-reordering before the bottom
    call or a Rust primitive that takes explicit bottom_ids — see the
    Rust API gaps section in ``docs/PHASE6_TRAJECTORY_PARITY.md``.
    """
    for pid in (0, 1):
        mulls_taken = 0
        while agent.should_mulligan(mulls_taken):
            # Per-iteration seed: deterministic in (base_seed, pid,
            # mulls_taken). Two random.Random instances with the same
            # seed produce identical _randbelow sequences, so Python's
            # local Fisher-Yates and Rust's mulligan_to_n consume the
            # same draw order even though they don't share state.
            iter_seed = (base_seed * 1000003 + pid * 31 + mulls_taken) & 0xFFFFFFFF
            py_rng = random.Random(iter_seed)
            rust_rng = random.Random(iter_seed)

            _python_mulligan_iteration(py_state, pid, py_rng)
            # Rust ``mulligan_to_n``'s ``seed`` arg is unused on the
            # external-rng path (the rng kwarg owns shuffle order); pass
            # 0 as a placeholder.
            rust_state.mulligan_to_n(pid, 7, 0, rng=rust_rng)

            mulls_taken += 1

        if mulls_taken > 0:
            # Pick bottom ids from the kept hand. By-position policy
            # ("first") matches Rust's bottom_cards_from_hand(n) which
            # also bottoms by position.
            hand_ids = [c.id for c in py_state.players[pid].hand]
            bottom_ids = agent.pick_bottom(hand_ids, mulls_taken)

            # Python: apply bottoming.
            _python_bottom_cards(py_state, pid, bottom_ids)
            # Rust: bottom by position (n cards from hand[0..n]).
            # bottom_strategy="first" guarantees this matches the
            # agent's pick_bottom([:n]) result by id.
            rust_state.bottom_cards_from_hand(pid, mulls_taken)


def setup_matched_game(
    decks: DeckSpec,
    seed: Optional[int] = None,
    mulligans: bool = False,
    opening_hand_size: int = 7,
    mulligan_agent: Optional[MulliganDeterministicAgent] = None,
    mulligan_seed: int = 0,
):
    """Build a parity-synced opening state on both engines.

    Closes Phase 6 infrastructure gap #1 (``docs/PHASE6_TRAJECTORY_PARITY.md``):
    a single entrypoint that produces a starting state with seven-card
    opening hands dealt on both Python and Rust, identical libraries
    on both sides, ready to walk turn 1 from UNTAP. Round-14 extends
    the helper to optionally drive a deterministic London-mulligan
    loop (gap #2).

    Parameters
    ----------
    decks : DeckSpec
        The matched decklist for both players. Reuses the existing
        ``cross_engine.DeckSpec`` shape so trajectory tests share the
        same registry / decklist / shuffle-seed plumbing as Phase 5
        smoke tests. The DeckSpec's ``shared_rng_seed`` (or
        ``shuffle_seed``) governs library shuffling on both engines —
        see :class:`cross_engine.DeckSpec` for the precedence rules.
    seed : Optional[int], default None
        Convenience: when set AND ``decks.shared_rng_seed`` is None,
        rebuilds ``decks`` with ``shared_rng_seed=seed`` so callers
        don't have to thread the seed twice. When BOTH are None the
        libraries are unshuffled (deck-list order). Callers that want
        explicit per-engine shuffle semantics should set
        ``decks.shared_rng_seed`` directly and leave ``seed=None``.
    mulligans : bool, default False
        When True, runs the deterministic London-mulligan loop on
        both engines using the supplied ``mulligan_agent`` (defaults
        to ``MulliganDeterministicAgent(target_hand_size=7)`` — a
        no-op agent that always keeps the initial 7). When False
        (legacy default), the helper deals 7 cards and stops, matching
        round-13's behavior exactly.
    opening_hand_size : int, default 7
        Cards to draw per player. Defaults to 7 (CR 103.5). Exposed
        primarily for test ergonomics — drop to 0 for a no-draw
        starting state matching the Phase 5 ``build_matched_states``
        pre-draw shape. Ignored when ``mulligans=True`` (the mulligan
        loop assumes the standard 7-card opening hand).
    mulligan_agent : Optional[MulliganDeterministicAgent], default None
        Cross-engine deterministic mulligan policy. Required when
        ``mulligans=True`` to govern the keep/mulligan + bottom-pick
        decisions. Defaults to ``MulliganDeterministicAgent()`` (the
        always-keep policy, equivalent to ``mulligans=False``) when
        not supplied. Ignored when ``mulligans=False``.
    mulligan_seed : int, default 0
        Base seed for the per-iteration shuffle RNGs. Each per-player
        per-iteration shuffle uses a freshly-constructed
        ``random.Random`` derived from ``(mulligan_seed, player_id,
        mulls_taken)``. Two calls with the same agent + seed produce
        bit-identical post-mulligan states. Ignored when
        ``mulligans=False``.

    Returns
    -------
    tuple[GameState, mtg_bot_engine.GameState]
        ``(py_state, rust_state)``. With ``mulligans=False``: both
        have ``opening_hand_size`` cards in hand on each side. With
        ``mulligans=True``: both have ``agent.target_hand_size`` cards
        in hand on each side, library has the bottomed cards on its
        tail. ``step=Step.UNTAP``, ``turn=1``, ``active_player=0``,
        ``priority_player=0`` in either case.

    Raises
    ------
    ValueError
        If ``opening_hand_size`` exceeds the per-player library size
        (would underflow on the side-channel draw); or if a supplied
        ``mulligan_agent`` is passed without ``mulligans=True`` (a
        likely caller bug — the agent has no effect in that path).
    """
    if opening_hand_size < 0:
        raise ValueError(
            f"opening_hand_size must be >= 0 (got {opening_hand_size})"
        )

    if mulligans:
        # MulliganAgent is the gap-#2 substrate. The default agent is
        # the "always keep" policy — equivalent to mulligans=False on
        # the post-state, but exercises the mulligan-loop plumbing.
        if mulligan_agent is None:
            mulligan_agent = MulliganDeterministicAgent()
        # The mulligan path assumes the standard 7-card opening hand
        # (London mulligan only makes sense at 7). Refuse to silently
        # drop a non-default opening_hand_size in this path.
        if opening_hand_size != 7:
            raise ValueError(
                "setup_matched_game(mulligans=True) requires "
                "opening_hand_size=7 (London mulligan deals 7 cards "
                f"by rule); got opening_hand_size={opening_hand_size}"
            )
    else:
        if mulligan_agent is not None:
            raise ValueError(
                "mulligan_agent supplied with mulligans=False — the "
                "agent would have no effect. Pass mulligans=True to "
                "drive the mulligan loop."
            )

    # Apply the convenience seed if the DeckSpec doesn't already pin
    # a shared_rng_seed. Build a fresh DeckSpec (frozen-dataclass
    # contract) rather than mutating in place.
    if seed is not None and decks.shared_rng_seed is None:
        decks = DeckSpec(
            card_defs=decks.card_defs,
            p0_library=decks.p0_library,
            p1_library=decks.p1_library,
            shuffle_seed=decks.shuffle_seed,
            shared_rng_seed=seed,
        )

    # Validate library sizes BEFORE construction so a sub-7-card spec
    # surfaces as a ValueError here rather than as an IndexError deep
    # in the draw loop.
    if opening_hand_size > 0:
        if len(decks.p0_library) < opening_hand_size:
            raise ValueError(
                f"p0 library ({len(decks.p0_library)} cards) smaller "
                f"than opening_hand_size={opening_hand_size}"
            )
        if len(decks.p1_library) < opening_hand_size:
            raise ValueError(
                f"p1 library ({len(decks.p1_library)} cards) smaller "
                f"than opening_hand_size={opening_hand_size}"
            )

    py_state, rust_state = build_matched_states(decks)
    if opening_hand_size > 0:
        _draw_opening_hand_both(py_state, rust_state, n=opening_hand_size)

    if mulligans:
        _run_mulligan_loop_both(
            py_state, rust_state, mulligan_agent, mulligan_seed,
        )

    return py_state, rust_state
