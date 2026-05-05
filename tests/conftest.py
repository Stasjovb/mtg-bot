"""Session-scoped card-source swap driven by ``MTG_BOT_CARD_SOURCE``,
plus a session-scoped flip of all training-time priority short-circuit
heuristic defaults to ``False`` so legacy tests written before the
heuristics existed pass without modification.

Default (env var unset) uses the production ``OracleParserCardSource``,
so ``pytest`` runs unchanged. The env-var hook is preserved as a seam
for any future alternative sources, but the parser source is the only
production source today.

Heuristic-default flip: production code (``SelfPlayJobSpec``,
``data_gen``, etc.) explicitly passes the heuristic flags as ``True``
through the call chain, so production behavior is unchanged. The
adapter-level default of ``True`` exists for ergonomic CLI use; flipping
it OFF in test sessions means tests that don't care about heuristics
(the vast majority) get the expected non-short-circuited behavior, and
tests that DO care about a specific heuristic (the per-heuristic
``test_<heuristic>.py`` files) can opt in by passing ``True`` explicitly.
"""

from __future__ import annotations

import os
from unittest import mock

import pytest

from mtg_bot.cards.source import (
    card_source_from_env,
    get_active_source,
    set_active_source,
)


@pytest.fixture(scope="session", autouse=True)
def _swap_card_source_from_env():
    requested = card_source_from_env(os.environ.get("MTG_BOT_CARD_SOURCE"))
    original = get_active_source()
    set_active_source(requested)
    try:
        yield
    finally:
        set_active_source(original)


_HEURISTIC_FLAGS_OFF_IN_TESTS = (
    "phase_prune_enabled",
    "force_landdrop_enabled",
    "skip_empty_combat_enabled",
    "skip_opp_postcombat_main_enabled",
    "skip_dead_main1_enabled",
)


@pytest.fixture(scope="session", autouse=True)
def _flip_heuristic_defaults_off_for_tests():
    """Wrap ``MtgGameStateAdapter.__init__`` so each
    heuristic flag defaults to ``False`` unless the test explicitly
    sets it. Production callers (``data_gen``, ``self_play``,
    ``distributed``) pass the flags explicitly and are unaffected.

    Tests in ``tests/search/test_<heuristic>.py`` that exercise the
    heuristic itself pass the relevant flag as ``True`` and continue
    to exercise that path."""
    from mtg_bot.search import engine_adapter as _ea

    real_init = _ea.MtgGameStateAdapter.__init__

    def _patched_init(self, *args, **kwargs):
        for flag in _HEURISTIC_FLAGS_OFF_IN_TESTS:
            kwargs.setdefault(flag, False)
        return real_init(self, *args, **kwargs)

    with mock.patch.object(
        _ea.MtgGameStateAdapter, "__init__", _patched_init,
    ):
        yield
