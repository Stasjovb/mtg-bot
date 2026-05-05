"""Compat shim: re-export the unified capability API for opp-side use.

Historical home of ``opp_can_act`` / ``opp_capability_hash``. As of
``feature/active-player-capability-autopass`` the implementation lives
in ``_player_capabilities.py`` and serves both opp and active-player
priority moments. These two thin wrappers preserve the legacy import
path so external tests / call sites keep working.
"""

from __future__ import annotations

from mtg_bot.game import GameState
from mtg_bot.search._player_capabilities import (
    has_player_capability_to_act,
    player_capability_hash,
)


def opp_can_act(state: GameState, opp_id: int) -> bool:
    """Definitive "does opp have at least one instant-speed capability
    right now" check. Thin wrapper around
    ``has_player_capability_to_act(..., is_active_player=False)``.
    Kept for backwards compatibility with the original module name."""
    return has_player_capability_to_act(
        state, opp_id, is_active_player=False,
    )


def opp_capability_hash(state: GameState, opp_id: int) -> int:
    """Fast structural hash for the non-active player's capability
    inputs. Thin wrapper around
    ``player_capability_hash(..., is_active_player=False)``."""
    return player_capability_hash(
        state, opp_id, is_active_player=False,
    )
