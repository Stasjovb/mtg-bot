"""Phase 6 trajectory-parity helpers.

Sibling module to :mod:`mtg_bot.parity.cross_engine`. The cross-engine
module ships the per-step / per-action primitives (``build_matched_states``,
``step_both``, ``advance_phase_python``, the family of ``*_selector``
functions, the field-view differ); this module ships the *real-game-shaped*
primitives that drive multi-turn trajectory probes.

Inaugural surface (Phase 6 round-13 slice):

* :func:`setup_matched_game` — closes infrastructure gap #1 from
  ``docs/PHASE6_TRAJECTORY_PARITY.md``: a single ``(decks, seed,
  mulligans=...)`` entrypoint that produces a parity-synced opening
  state on both engines. Wraps :func:`cross_engine.build_matched_states`
  and the side-channel opening-hand draw the seed file currently
  inlines.

What this slice deliberately does NOT cover:

* **Mulligans.** ``mulligans=True`` is reserved for a follow-up slice
  (infrastructure gap #2 in the entry doc). Calling with
  ``mulligans=True`` raises ``NotImplementedError`` rather than
  silently no-op'ing, so a future London-mulligan agent can land here
  without breaking existing call-sites.
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

from typing import Optional

from mtg_bot.parity.cross_engine import (
    DeckSpec,
    build_matched_states,
)


__all__ = ["setup_matched_game"]


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


def setup_matched_game(
    decks: DeckSpec,
    seed: Optional[int] = None,
    mulligans: bool = False,
    opening_hand_size: int = 7,
):
    """Build a parity-synced opening state on both engines.

    Closes Phase 6 infrastructure gap #1 (``docs/PHASE6_TRAJECTORY_PARITY.md``):
    a single entrypoint that produces a starting state with seven-card
    opening hands dealt on both Python and Rust, identical libraries
    on both sides, ready to walk turn 1 from UNTAP.

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
        Reserved for the London-mulligan follow-up slice. Currently
        only ``False`` is supported — passing ``True`` raises
        ``NotImplementedError`` with a pointer to the relevant entry
        doc gap. Per-player mulligan-or-keep + bottom decisions
        require a cross-engine ``MulliganAgent`` analog (Phase 6
        infrastructure gap #2) which doesn't exist yet.
    opening_hand_size : int, default 7
        Cards to draw per player. Defaults to 7 (CR 103.5). Exposed
        primarily for test ergonomics — drop to 0 for a no-draw
        starting state matching the Phase 5 ``build_matched_states``
        pre-draw shape.

    Returns
    -------
    tuple[GameState, mtg_bot_engine.GameState]
        ``(py_state, rust_state)``. Both have ``opening_hand_size``
        cards in hand on each side, library reduced by the same count,
        ``step=Step.UNTAP``, ``turn=1``, ``active_player=0``,
        ``priority_player=0`` — the canonical "turn 1 UNTAP, no actions
        taken" shape both engines start from.

    Raises
    ------
    NotImplementedError
        If ``mulligans=True``. See module docstring for the planned
        follow-up.
    ValueError
        If ``opening_hand_size`` exceeds the per-player library size
        (would underflow on the side-channel draw).
    """
    if mulligans:
        raise NotImplementedError(
            "setup_matched_game(mulligans=True) is reserved for a "
            "follow-up slice. Closing this requires a cross-engine "
            "MulliganAgent (Phase 6 infrastructure gap #2 in "
            "docs/PHASE6_TRAJECTORY_PARITY.md). Pass mulligans=False "
            "for now."
        )

    if opening_hand_size < 0:
        raise ValueError(
            f"opening_hand_size must be >= 0 (got {opening_hand_size})"
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
    return py_state, rust_state
