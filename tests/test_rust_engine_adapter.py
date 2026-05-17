"""B3-S1 — ``RustGameStateAdapter`` + the ``decision_source`` flag +
the non-vestigial dict<->Decision adapter.

Covers:

* The dict<->Decision adapter round-trips every priority-window +
  combat kind both ways (``rust_decision_adapter``).
* ``HeuristicsConfig.decision_source`` defaults to ``"python"``,
  round-trips through ``to_dict``/``from_dict``, and a pre-B3 dict
  (no ``decision_source`` key) decodes to ``"python"`` (the
  parity-safe default).
* The factory returns the unchanged ``MtgGameStateAdapter`` under
  ``python`` (parity-safe default) and raises loudly (NO silent
  Python fallback) when a Rust source is requested at a Python-engine
  construction site.
* ``RustGameStateAdapter`` satisfies ``search.protocol.GameState`` and
  drives a real Rust game (priority-window axis) to a terminal state
  via the Protocol surface only.

These tests exercise the NEW B3 surface directly; they are NOT part of
the default trajectory/probe pins (which must stay byte-unchanged with
``decision_source="python"`` — verified separately by the unmodified
gate).
"""

from __future__ import annotations

import random

import pytest

from mtg_bot.actions import (
    ActivateAbility, CastSpell, DeclareAttackers, DeclareBlockers,
    PassPriority, PlayLand,
)
from mtg_bot.search.combat_decisions import (
    AttackerDecision, BlockerDecision,
)
from mtg_bot.search.heuristics_config import (
    DEFAULT_DECISION_SOURCE, HeuristicsConfig,
)
from mtg_bot.search.protocol import GameState as GameStateProtocol
from mtg_bot.search.rust_decision_adapter import (
    UnsupportedRustDecisionKind, decision_to_rust_dict,
    declare_attackers_dict, declare_blockers_dict,
    rust_dict_to_decision,
)


# ---------------------------------------------------------------------------
# dict <-> Decision adapter
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "d, expected",
    [
        ({"kind": "pass_priority"}, PassPriority()),
        ({"kind": "play_land", "card_id": 42}, PlayLand(card_id=42)),
        (
            {
                "kind": "cast_spell", "card_id": 7, "use_warp": False,
                "kicked": False, "cast_for_free": False,
                "use_impending": False, "cast_room_half": None,
            },
            CastSpell(card_id=7),
        ),
        (
            {"kind": "cast_spell", "card_id": 9, "use_warp": True},
            CastSpell(card_id=9, use_warp=True),
        ),
        (
            {"kind": "activate_ability", "source_id": 3,
             "ability_index": 1},
            ActivateAbility(source_id=3, ability_index=1),
        ),
        (
            {"kind": "attacker_decision", "attacker_id": 5,
             "attack": True},
            AttackerDecision(attacker_id=5, attack=True),
        ),
        (
            {"kind": "blocker_decision", "blocker_id": 6,
             "attacker_id": None},
            BlockerDecision(blocker_id=6, attacker_id=None),
        ),
        (
            {"kind": "blocker_decision", "blocker_id": 6,
             "attacker_id": 5},
            BlockerDecision(blocker_id=6, attacker_id=5),
        ),
        (
            {"kind": "declare_attackers", "attacker_ids": [2, 1]},
            DeclareAttackers(attacker_ids=frozenset({1, 2})),
        ),
        (
            {"kind": "declare_blockers",
             "assignments": [[6, 5], [7, 5]]},
            DeclareBlockers(assignments=((6, 5), (7, 5))),
        ),
    ],
)
def test_rust_dict_to_decision(d, expected):
    assert rust_dict_to_decision(d) == expected


@pytest.mark.parametrize(
    "decision",
    [
        PassPriority(),
        PlayLand(card_id=42),
        CastSpell(card_id=7),
        CastSpell(card_id=9, use_warp=True, kicked=True),
        ActivateAbility(source_id=3, ability_index=2),
        AttackerDecision(attacker_id=5, attack=False),
        BlockerDecision(blocker_id=6, attacker_id=None),
        BlockerDecision(blocker_id=6, attacker_id=5),
        DeclareAttackers(attacker_ids=frozenset({1, 2})),
        DeclareBlockers(assignments=((6, 5), (7, 5))),
    ],
)
def test_decision_dict_roundtrip(decision):
    """decision -> rust dict -> decision is identity for every kind."""
    d = decision_to_rust_dict(decision)
    assert rust_dict_to_decision(d) == decision


def test_cast_spell_dict_canonical_key_is_card_id():
    """The Rust apply_action contract is strict (verify-first
    re-anchor vs the spec's ``"id"`` drift): cast_spell/play_land use
    the LIVE canonical ``card_id`` key, NOT the cross-vocabulary
    ``source_id`` alias the vestigial _dict_to_python_action honors."""
    d = decision_to_rust_dict(CastSpell(card_id=11))
    assert d["card_id"] == 11
    assert "id" not in d and "source_id" not in d
    pl = decision_to_rust_dict(PlayLand(card_id=12))
    assert pl["card_id"] == 12 and "id" not in pl


def test_unsupported_kind_raises_loudly():
    with pytest.raises(UnsupportedRustDecisionKind):
        rust_dict_to_decision({"kind": "totally_unknown"})

    class _NotADecision:
        pass

    with pytest.raises(UnsupportedRustDecisionKind):
        decision_to_rust_dict(_NotADecision())


def test_whole_action_combat_builders():
    assert declare_attackers_dict([3, 1, 2]) == {
        "kind": "declare_attackers", "attacker_ids": [1, 2, 3],
    }
    assert declare_blockers_dict([(6, 5), (7, 5)]) == {
        "kind": "declare_blockers", "assignments": [[6, 5], [7, 5]],
    }


# ---------------------------------------------------------------------------
# decision_source flag on HeuristicsConfig
# ---------------------------------------------------------------------------


def test_decision_source_defaults_to_python():
    hc = HeuristicsConfig()
    assert hc.decision_source == "python"
    assert DEFAULT_DECISION_SOURCE == "python"
    # disabled() (eval default) must also keep the flag at python —
    # it is orthogonal to the heuristic toggles.
    assert HeuristicsConfig.disabled().decision_source == "python"


def test_decision_source_roundtrips():
    for src in ("python", "rust", "rust_shadow"):
        hc = HeuristicsConfig(decision_source=src)
        d = hc.to_dict()
        assert d["decision_source"] == src
        assert HeuristicsConfig.from_dict(d).decision_source == src


def test_pre_b3_dict_defaults_to_python():
    """A serialized config from before B3 (no decision_source key)
    MUST decode to "python" — the parity-safe default that keeps
    every existing distributed plumbing path byte-unchanged."""
    pre_b3 = {
        "phase_prune_enabled": True,
        "force_landdrop_enabled": True,
        "skip_empty_combat_enabled": True,
        "skip_opp_postcombat_main_enabled": True,
        "skip_dead_main1_enabled": True,
    }
    hc = HeuristicsConfig.from_dict(pre_b3)
    assert hc.decision_source == "python"


def test_invalid_decision_source_rejected():
    with pytest.raises(ValueError):
        HeuristicsConfig(decision_source="rust_only")


# ---------------------------------------------------------------------------
# the factory (parity-safe default + loud-fail)
# ---------------------------------------------------------------------------


def _python_engine():
    from mtg_bot.agents import RandomAgent
    from mtg_bot.simulate import setup_game

    return setup_game(
        [RandomAgent(rng=random.Random(1)),
         RandomAgent(rng=random.Random(2))],
        decks=[["Forest"] * 10, ["Forest"] * 10],
        seed=7,
    )


def test_factory_python_returns_unchanged_adapter():
    from mtg_bot.search.engine_adapter import MtgGameStateAdapter
    from mtg_bot.search.engine_adapter_factory import (
        make_game_state_adapter,
    )

    eng = _python_engine()
    adapter = make_game_state_adapter(
        eng, expose_combat_decisions=True,
        heuristics=HeuristicsConfig(),
    )
    assert type(adapter) is MtgGameStateAdapter
    # The default (no heuristics, no explicit source) is also python.
    assert type(make_game_state_adapter(_python_engine())) is (
        MtgGameStateAdapter
    )


def test_factory_rust_at_python_site_raises_no_silent_fallback():
    from mtg_bot.search.engine_adapter_factory import (
        make_game_state_adapter,
    )

    eng = _python_engine()
    for src in ("rust", "rust_shadow"):
        with pytest.raises(NotImplementedError):
            make_game_state_adapter(
                eng,
                heuristics=HeuristicsConfig(decision_source=src),
            )


# ---------------------------------------------------------------------------
# RustGameStateAdapter — Protocol conformance + real Rust game
# ---------------------------------------------------------------------------


def _rust_state():
    pytest.importorskip("mtg_bot_engine")
    from mtg_bot.parity.cross_engine import (
        build_rust_state, tiny_synthetic_deckspec,
    )

    return build_rust_state(tiny_synthetic_deckspec())


def test_rust_adapter_is_protocol_conformant():
    from mtg_bot.search.engine_adapter_factory import (
        make_rust_game_state_adapter,
    )

    adapter = make_rust_game_state_adapter(_rust_state())
    assert isinstance(adapter, GameStateProtocol)
    assert adapter.players() == [0, 1]
    assert adapter.chance_outcomes() == []
    assert not adapter.is_terminal()
    assert adapter.winner() is None
    legal = adapter.legal_decisions()
    assert legal, "legal_decisions must be non-empty pre-terminal"
    # PassPriority is always emitted (Rust contract: index 0).
    assert any(isinstance(d, PassPriority) for d in legal)


def test_rust_adapter_clone_is_independent():
    from mtg_bot.search.engine_adapter_factory import (
        make_rust_game_state_adapter,
    )

    adapter = make_rust_game_state_adapter(_rust_state())
    fp0 = adapter.fingerprint()
    clone = adapter.clone()
    assert clone.fingerprint() == fp0
    # Mutate the clone; the original must be untouched.
    clone.apply(PassPriority())
    assert adapter.fingerprint() == fp0
    assert isinstance(clone, GameStateProtocol)


def test_rust_adapter_drives_real_game_to_terminal():
    """Drive a real Rust game through the Protocol surface only
    (priority-window axis): ask legal_decisions, pick deterministically,
    apply, until terminal. Proves the provider is a working
    second GameState implementation."""
    from mtg_bot.search.engine_adapter_factory import (
        make_rust_game_state_adapter,
    )

    adapter = make_rust_game_state_adapter(_rust_state())
    rng = random.Random(12345)
    steps = 0
    while not adapter.is_terminal() and steps < 4000:
        legal = adapter.legal_decisions()
        assert legal, "non-empty legal set required pre-terminal"
        choice = rng.choice(legal)
        adapter.apply(choice)
        steps += 1
    # The tiny 3-card-library deck decks both players out quickly;
    # the game must terminate well within the cap.
    assert adapter.is_terminal()
    # winner() is well-defined post-terminal (id or None for a draw).
    w = adapter.winner()
    assert w is None or w in (0, 1)


def test_rust_adapter_apply_on_terminal_raises():
    from mtg_bot.search.engine_adapter_factory import (
        make_rust_game_state_adapter,
    )

    adapter = make_rust_game_state_adapter(_rust_state())
    rng = random.Random(99)
    steps = 0
    while not adapter.is_terminal() and steps < 4000:
        adapter.apply(rng.choice(adapter.legal_decisions()))
        steps += 1
    assert adapter.is_terminal()
    assert adapter.legal_decisions() == []
    with pytest.raises(ValueError):
        adapter.apply(PassPriority())
