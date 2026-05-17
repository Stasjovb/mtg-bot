"""The single game-construction factory that selects the decision
source (B3-S1 / SOT_FLIP_CUTOVER_PLAN Step 3).

Per the umbrella's rollback constraint
(``docs/SOT_FLIP_CUTOVER_PLAN.md`` §3 + the B3 wiring spec
``docs/NN_RUST_DECISION_SOURCING_WIRING_DESIGN.md`` §3.1) the
decision-source switch MUST be a **single atomic-revert flag** read
once at game construction. This module is the ONE place the
``MtgGameStateAdapter`` vs ``RustGameStateAdapter`` choice is made; a
half-reverted state is unrepresentable because the whole game uses one
provider chosen here.

``decision_source`` lives on the frozen ``HeuristicsConfig`` (so it
travels through the existing JSON / cross-pickle plumbing for free):

* ``"python"`` (DEFAULT) — return the unchanged ``MtgGameStateAdapter``
  built exactly as the call sites built it before B3. **Byte-identical
  to pre-B3 behavior** — this module adds zero behavior change while
  the flag is off (the parity-safe landing).
* ``"rust"`` / ``"rust_shadow"`` — the Rust-backed provider. B3-S1
  ships the dispatch + the provider class; the Rust-state *loader*
  wiring at the production self-play construction sites
  (``data_gen``/``self_play`` build a Python ``engine`` from decks,
  not a Rust state) is sequenced into B3-S3/S4 (the
  ``build_matched_states`` loader path + the ``rust_shadow``
  shadow-checker). Until then, requesting a Rust source at a
  Python-engine construction site raises loudly rather than silently
  degrading (``feedback_no_fallback_hybrids`` — an honest hard
  failure is the real progress signal; NEVER a silent fallback to
  Python).

Tests / the B3-S4 bake-in construct the Rust provider directly from a
Rust ``GameState`` via :func:`make_rust_game_state_adapter`.
"""

from __future__ import annotations

from typing import Any, Optional

from mtg_bot.search.heuristics_config import (
    DEFAULT_DECISION_SOURCE, HeuristicsConfig,
)


def _resolve_decision_source(
    heuristics: Optional[HeuristicsConfig],
    decision_source: Optional[str],
) -> str:
    """Resolve the effective decision source. An explicit
    ``decision_source`` argument overrides the heuristics field
    (the heuristics field is the production/distributed plumbing
    path; the explicit arg is the test / direct-construction path).
    Defaults to ``"python"`` — the safe-by-default landing."""
    if decision_source is not None:
        return decision_source
    if heuristics is not None:
        return heuristics.decision_source
    return DEFAULT_DECISION_SOURCE


def make_game_state_adapter(
    engine_state: Any,
    *,
    tactical_agent: Any = None,
    expose_combat_decisions: bool = True,
    expose_resolution_decisions: bool = False,
    heuristics: Optional[HeuristicsConfig] = None,
    decision_source: Optional[str] = None,
):
    """Construct the search ``GameState`` provider for a game.

    Under ``decision_source="python"`` (default) this returns exactly
    ``MtgGameStateAdapter(engine_state, ...)`` — the SAME object the
    call sites built before B3, with the SAME arguments. The only
    behavioral difference vs a direct ``MtgGameStateAdapter(...)``
    call is *nothing* when the flag is off.

    Under ``"rust"`` / ``"rust_shadow"`` at a Python-engine
    construction site, raises ``NotImplementedError`` (the Rust-state
    loader wiring at the production sites is B3-S3/S4). The Rust
    provider is constructed directly from a Rust state via
    :func:`make_rust_game_state_adapter` by tests + the B3-S4 bake-in.
    """
    src = _resolve_decision_source(heuristics, decision_source)

    if src == "python":
        # Lazy import to keep the factory import-cheap and avoid any
        # import cycle through the heavy engine_adapter module at
        # config-construction time.
        from mtg_bot.search.engine_adapter import MtgGameStateAdapter

        return MtgGameStateAdapter(
            engine_state,
            tactical_agent=tactical_agent,
            expose_combat_decisions=expose_combat_decisions,
            expose_resolution_decisions=expose_resolution_decisions,
            heuristics=heuristics,
        )

    if src in ("rust", "rust_shadow"):
        raise NotImplementedError(
            f"decision_source={src!r} requested at a Python-engine "
            f"construction site. The Rust-state loader wiring at the "
            f"production self-play sites is sequenced into B3-S3/S4 "
            f"(the build_matched_states loader path + the rust_shadow "
            f"shadow-checker). Construct the Rust provider directly "
            f"from a Rust GameState via "
            f"make_rust_game_state_adapter(...) until then. NO silent "
            f"fallback to Python (feedback_no_fallback_hybrids)."
        )

    raise ValueError(f"unknown decision_source: {src!r}")


def make_rust_game_state_adapter(
    rust_state: Any,
    *,
    expose_combat_decisions: bool = True,
):
    """Construct the Rust-backed provider directly from a live Rust
    ``GameState`` handle (e.g. from
    ``cross_engine.build_rust_state`` / ``build_matched_states`` — the
    surviving loader path per ``BRIDGE_VESTIGIALIZATION_PLAN.md``
    §2.1). Used by the B3 unit tests and the B3-S4 ``rust_shadow``
    bake-in; the production self-play sites adopt it in B3-S3/S4."""
    from mtg_bot.search.rust_engine_adapter import RustGameStateAdapter

    return RustGameStateAdapter(
        rust_state,
        expose_combat_decisions=expose_combat_decisions,
    )
