"""Self-play move temperature + exploration-knob plumbing
(feature/lf-training).

- ``_sample_move_with_temperature``: T -> 0 gives argmax; T <= 0 is
  argmax; with rigged visits the empirical sample distribution matches
  ``visits ** (1/T)``; decisions illegal at the root are excluded.
- ``_play_one_game_recording``: the cutoff counts only NON-forced
  decisions (>1 legal option), sampled and unsampled alike; past the
  cutoff (or with T <= 0 / cutoff 0) the played move is the argmax.
- Plumbing: iterate's self-play config dict, StageSpec / claim knobs,
  SelfPlayJobSpec round-trip, worker claim parsing, launcher TOML
  fields + argv, and the eval path staying knob-free.
"""

from __future__ import annotations

import inspect
import random
from collections import Counter
from dataclasses import fields

import pytest

from mtg_bot import distributed_rest_orchestrator as orch
from mtg_bot import worker_daemon_production_runner as prr
from mtg_bot.agents import RandomAgent
from mtg_bot.cli import iterate as iterate_mod
from mtg_bot.cli import iterate_distributed as itd
from mtg_bot.launcher import config as launch_cfg
from mtg_bot.search import MtgGameStateAdapter
from mtg_bot.simulate import setup_game
from mtg_bot.training import self_play as self_play_mod
from mtg_bot.training.data_gen import (
    _play_one_game_recording, _sample_move_with_temperature,
)
from mtg_bot.training.distributed import SelfPlayJobSpec
from tests._test_decks import simple_test_decklists


# ---------- _sample_move_with_temperature -----------------------------------


def test_temperature_zero_or_negative_returns_argmax():
    visits = {"a": 3, "b": 10, "c": 7}
    legal = {"a", "b", "c"}
    for t in (0.0, -1.0):
        assert _sample_move_with_temperature(
            visits, legal, t, random.Random(0), fallback="a",
        ) == "b"


def test_temperature_tending_to_zero_gives_argmax():
    visits = {"a": 30, "b": 100, "c": 70}
    legal = set(visits)
    rng = random.Random(1)
    picks = Counter(
        _sample_move_with_temperature(visits, legal, 1e-3, rng, fallback="a")
        for _ in range(500)
    )
    assert picks == Counter({"b": 500})


def test_sampling_matches_visit_distribution_at_t1():
    visits = {"a": 8, "b": 2}
    legal = set(visits)
    rng = random.Random(123)
    n = 20000
    picks = Counter(
        _sample_move_with_temperature(visits, legal, 1.0, rng, fallback="a")
        for _ in range(n)
    )
    assert picks["a"] / n == pytest.approx(0.8, abs=0.02)
    assert picks["b"] / n == pytest.approx(0.2, abs=0.02)


def test_sampling_sharpens_at_low_temperature():
    # T=0.5 -> weights (8/8)^2 : (2/8)^2 = 1 : 0.0625 -> p(b) ~ 0.0588
    visits = {"a": 8, "b": 2}
    legal = set(visits)
    rng = random.Random(7)
    n = 20000
    picks = Counter(
        _sample_move_with_temperature(visits, legal, 0.5, rng, fallback="a")
        for _ in range(n)
    )
    assert picks["b"] / n == pytest.approx(1 / 17, abs=0.01)


def test_sampling_is_deterministic_per_rng_seed():
    visits = {"a": 5, "b": 5, "c": 5}
    legal = set(visits)
    seq1 = [
        _sample_move_with_temperature(visits, legal, 1.0, random.Random(4), "a")
        for _ in range(1)
    ]
    r1, r2 = random.Random(4), random.Random(4)
    s1 = [_sample_move_with_temperature(visits, legal, 1.0, r1, "a") for _ in range(50)]
    s2 = [_sample_move_with_temperature(visits, legal, 1.0, r2, "a") for _ in range(50)]
    assert s1 == s2
    assert seq1[0] == s1[0]


def test_illegal_and_zero_visit_decisions_are_excluded():
    visits = {"illegal": 1000, "a": 1, "zero": 0}
    picks = {
        _sample_move_with_temperature(
            visits, {"a", "zero"}, 1.0, random.Random(i), fallback="x",
        )
        for i in range(20)
    }
    assert picks == {"a"}
    # Nothing eligible -> fallback.
    assert _sample_move_with_temperature(
        {"illegal": 5}, {"a"}, 1.0, random.Random(0), fallback="x",
    ) == "x"


# ---------- cutoff semantics through the game loop --------------------------


class _Recorder:
    """Shared per-game log: one ``(n_legal, argmax)`` entry per
    non-chance decision (appended by whichever seat is active) and
    the decision actually applied (appended via ``observe_action``
    from the seat-0 strategy only)."""

    def __init__(self):
        self.info: list[tuple[int, object]] = []
        self.played: list[object] = []


class _UniformVisitsStrategy:
    """Every legal decision gets 1 visit, so argmax = the first legal
    decision and T=1 sampling picks uniformly. Records through the
    shared recorder."""

    def __init__(self, rec: _Recorder, seat: int):
        self.rec = rec
        self.seat = seat

    def _note(self, adapter):
        legal = list(adapter.legal_decisions())
        self.rec.info.append((len(legal), legal[0]))
        return legal

    def choose(self, adapter, player_id):
        return self._note(adapter)[0]

    def choose_with_visits(self, adapter, player_id):
        legal = self._note(adapter)
        return {d: 1 for d in legal}

    def observe_action(self, pre_state, decision, actor):
        if self.seat == 0:
            self.rec.played.append(decision)


def _run(seed, *, move_temperature, temperature_cutoff, sample_every=1,
         decision_cap=150):
    engine = setup_game(
        [RandomAgent(rng=random.Random(seed)),
         RandomAgent(rng=random.Random(seed + 1))],
        decks=simple_test_decklists(), seed=seed,
    )
    adapter = MtgGameStateAdapter(engine, expose_combat_decisions=True)
    rec = _Recorder()
    strategies = {
        0: _UniformVisitsStrategy(rec, 0),
        1: _UniformVisitsStrategy(rec, 1),
    }
    _play_one_game_recording(
        adapter, strategies, random.Random(seed + 99), decision_cap,
        sample_every, move_temperature=move_temperature,
        temperature_cutoff=temperature_cutoff,
    )
    assert len(rec.info) == len(rec.played)
    return rec


def _deviation_flags(rec):
    """Per decision: (is_nonforced, deviated_from_argmax)."""
    out = []
    for (n_legal, argmax), played in zip(rec.info, rec.played):
        out.append((n_legal > 1, played != argmax))
    return out


@pytest.mark.parametrize("sample_every", [1, 2])
def test_cutoff_counts_only_non_forced_decisions(sample_every):
    cutoff = 6
    rec = _run(
        11, move_temperature=1.0, temperature_cutoff=cutoff,
        sample_every=sample_every,
    )
    flags = _deviation_flags(rec)
    nonforced_seen = 0
    within, beyond = 0, 0
    for is_nonforced, deviated in flags:
        if not is_nonforced:
            # Forced decisions never deviate and never count.
            assert not deviated
            continue
        if nonforced_seen < cutoff:
            within += int(deviated)
        else:
            assert not deviated, (
                "played a non-argmax move after the non-forced cutoff"
            )
            beyond += 1
        nonforced_seen += 1
    assert nonforced_seen > cutoff, "game too short to exercise the cutoff"
    assert beyond > 0
    # With uniform visits at T=1 the first `cutoff` non-forced
    # decisions sample uniformly, so some deviation must have occurred.
    assert within > 0


def test_cutoff_zero_or_non_positive_temperature_is_pure_argmax():
    for kwargs in (
        {"move_temperature": 1.0, "temperature_cutoff": 0},
        {"move_temperature": 0.0, "temperature_cutoff": 30},
        {"move_temperature": -1.0, "temperature_cutoff": 30},
    ):
        rec = _run(11, **kwargs)
        assert all(not dev for _, dev in _deviation_flags(rec)), kwargs


def test_game_loop_defaults_are_t1_cutoff30():
    sig = inspect.signature(_play_one_game_recording)
    assert sig.parameters["move_temperature"].default == 1.0
    assert sig.parameters["temperature_cutoff"].default == 30


# ---------- plumbing --------------------------------------------------------


def test_iterate_alpha_helper_and_self_play_config_dict():
    assert iterate_mod._dirichlet_alpha_or_none(None) is None
    assert iterate_mod._dirichlet_alpha_or_none(0.0) is None
    assert iterate_mod._dirichlet_alpha_or_none(-2) is None
    assert iterate_mod._dirichlet_alpha_or_none(0.5) == 0.5

    class _Args:
        games_per_iteration = 10
        samples = 4
        nodes = 200
        deck_pool = "pool.json.gz"
        root_dirichlet_alpha = 0.5
        root_dirichlet_eps = 0.25
        move_temperature = 1.0
        temperature_cutoff = 30

    d = iterate_mod._self_play_config_dict(
        args=_Args(), best_version="v1", cycle_seed=7, distributed=False,
    )
    assert d["root_dirichlet_alpha"] == 0.5
    assert d["root_dirichlet_eps"] == 0.25
    assert d["move_temperature"] == 1.0
    assert d["temperature_cutoff"] == 30


def test_iterate_flags_have_expected_defaults():
    src = inspect.getsource(iterate_mod.main)
    assert '"--root-dirichlet-alpha", type=float, default=0.5' in src
    assert '"--root-dirichlet-eps", type=float, default=0.25' in src
    assert '"--move-temperature", type=float, default=1.0' in src
    assert '"--temperature-cutoff", type=int, default=30' in src


def test_eval_paths_do_not_take_exploration_knobs():
    """Eval must stay deterministic-argmax: no temperature / Dirichlet
    plumbing on run_match*, cli eval, or iterate's eval match."""
    for fn in (
        self_play_mod.run_match, self_play_mod.run_match_parallel,
        iterate_mod._eval_match, iterate_mod._eval_match_distributed,
    ):
        params = inspect.signature(fn).parameters
        assert "move_temperature" not in params
        assert "temperature_cutoff" not in params
        assert "root_dirichlet_alpha" not in params
        src = inspect.getsource(fn)
        assert "root_dirichlet" not in src
        assert "move_temperature" not in src
    # And the self-play side does thread them.
    sp_src = inspect.getsource(iterate_mod._self_play)
    assert "root_dirichlet_alpha=root_dirichlet_alpha" in sp_src
    assert "move_temperature=move_temperature" in sp_src


def test_stage_spec_carries_knobs_and_eval_pins_them_off():
    sp = orch.make_self_play_stage_spec(
        stage_id="s", n_games=1, base_seed=0, deck_pool_size=4,
        weights_version="v1", nodes=10, samples=1,
        per_game_timeout_sec=5.0,
        root_dirichlet_alpha=0.5, root_dirichlet_eps=0.3,
        move_temperature=0.9, temperature_cutoff=20,
    )
    d = sp.to_dict()
    assert d["root_dirichlet_alpha"] == 0.5
    assert d["root_dirichlet_eps"] == 0.3
    assert d["move_temperature"] == 0.9
    assert d["temperature_cutoff"] == 20
    # Defaults on a bare self-play spec: noise off, data_gen temperature.
    bare = orch.make_self_play_stage_spec(
        stage_id="s", n_games=1, base_seed=0, deck_pool_size=4,
        weights_version="v1", nodes=10, samples=1, per_game_timeout_sec=5.0,
    ).to_dict()
    assert bare["root_dirichlet_alpha"] is None
    assert bare["move_temperature"] == 1.0
    assert bare["temperature_cutoff"] == 30
    ev = orch.make_eval_stage_spec(
        stage_id="e", n_games=1, base_seed=0, deck_pool_size=4,
        new_version="v2", old_version="v1", nodes=10, samples=1,
        per_game_timeout_sec=5.0,
    ).to_dict()
    assert ev["root_dirichlet_alpha"] is None
    assert ev["move_temperature"] == 0.0
    assert ev["temperature_cutoff"] == 0


def test_worker_claim_knob_parsing():
    k = prr._self_play_exploration_knobs({})
    assert k == {
        "root_dirichlet_alpha": None, "root_dirichlet_eps": 0.25,
        "move_temperature": 1.0, "temperature_cutoff": 30,
    }
    k = prr._self_play_exploration_knobs({
        "root_dirichlet_alpha": 0.5, "root_dirichlet_eps": 0.1,
        "move_temperature": 0.7, "temperature_cutoff": 5,
    })
    assert k == {
        "root_dirichlet_alpha": 0.5, "root_dirichlet_eps": 0.1,
        "move_temperature": 0.7, "temperature_cutoff": 5,
    }
    # Explicit None / <= 0 alpha both mean "off".
    assert prr._self_play_exploration_knobs(
        {"root_dirichlet_alpha": None}
    )["root_dirichlet_alpha"] is None
    assert prr._self_play_exploration_knobs(
        {"root_dirichlet_alpha": 0}
    )["root_dirichlet_alpha"] is None


def test_worker_play_self_play_game_accepts_knobs():
    params = inspect.signature(prr._play_self_play_game).parameters
    assert params["move_temperature"].default == 1.0
    assert params["temperature_cutoff"].default == 30


def test_self_play_job_spec_round_trips_knobs():
    spec = SelfPlayJobSpec(
        weights_path="w.pt", samples=2, inner_nodes=4, hidden_sizes=None,
        base_seed=0, per_game_timeout_sec=None,
        root_dirichlet_alpha=0.5, root_dirichlet_eps=0.2,
        move_temperature=0.8, temperature_cutoff=10,
    )
    assert SelfPlayJobSpec.from_dict(spec.to_dict()) == spec
    legacy = SelfPlayJobSpec.from_dict({
        "weights_path": "w.pt", "samples": 2, "inner_nodes": 4,
        "hidden_sizes": None, "base_seed": 0, "per_game_timeout_sec": None,
    })
    assert legacy.root_dirichlet_alpha is None
    assert legacy.root_dirichlet_eps == 0.25
    assert legacy.move_temperature == 1.0
    assert legacy.temperature_cutoff == 30


def test_launcher_iter_section_and_argv_carry_knobs(tmp_path):
    names = {f.name for f in fields(launch_cfg.IterSection)}
    assert {
        "root_dirichlet_alpha", "root_dirichlet_eps",
        "move_temperature", "temperature_cutoff",
    } <= names
    sec = launch_cfg.IterSection()
    assert (sec.root_dirichlet_alpha, sec.root_dirichlet_eps,
            sec.move_temperature, sec.temperature_cutoff) == (
        0.5, 0.25, 1.0, 30,
    )
    # New float coercion path (CLI overrides arrive as strings).
    assert launch_cfg._coerce_value("iter", "move_temperature", "0.5", float) == 0.5
    assert launch_cfg._coerce_value("iter", "move_temperature", 2, float) == 2.0
    with pytest.raises(launch_cfg.LaunchConfigError):
        launch_cfg._coerce_value("iter", "move_temperature", "abc", float)
    with pytest.raises(launch_cfg.LaunchConfigError):
        launch_cfg._coerce_value("iter", "move_temperature", True, float)

    cfg = launch_cfg.LaunchConfig(
        iter=launch_cfg.IterSection(
            target_iter=3, root_dirichlet_alpha=0.4, move_temperature=0.9,
            temperature_cutoff=12,
        ),
    )
    argv = itd._build_iterate_argv(
        cfg, shards_config_path=tmp_path / "shards.json",
        queue_url="http://q", deck_pool=None, registry_root=None,
        extra_iterate_args=[],
    )
    def _val(flag):
        return argv[argv.index(flag) + 1]
    assert _val("--root-dirichlet-alpha") == "0.4"
    assert _val("--root-dirichlet-eps") == "0.25"
    assert _val("--move-temperature") == "0.9"
    assert _val("--temperature-cutoff") == "12"


def test_launch_template_documents_knobs():
    from pathlib import Path
    text = Path("configs/launch/iter_TEMPLATE.toml").read_text()
    for key in (
        "root_dirichlet_alpha = 0.5", "root_dirichlet_eps = 0.25",
        "move_temperature = 1.0", "temperature_cutoff = 30",
    ):
        assert key in text
