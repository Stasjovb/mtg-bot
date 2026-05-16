"""Tests for ``scripts/check_audit_coverage_staleness.py`` — the
round-19 cron-proposal staleness check + its post-commit-hook wiring.

Covers:
  * happy path: docs in sync with the live inventory → empty drift,
    exit 0, "in sync" report;
  * drift detection: a stale doc-claimed count is reported precisely
    (which count, claimed-vs-actual, +delta), exit 1;
  * the auto-generated coverage-doc cross-check (committed-stale
    ``RUST_EFFECT_COVERAGE.md`` — the round-51 class) is flagged;
  * the STALENESS-SENTINEL parser: well-formed block, comment/blank
    skipping, and every malformed-input error path;
  * the live-inventory derivers parse the real working tree
    (structural-regression guard, like ``test_effect_coverage``'s
    extractor sanity test);
  * the ``hooks/post-commit`` contract: feature-branch commits are
    skipped, ``main`` commits run the staleness step, and a failing
    staleness check never changes the hook's exit code (mirrors the
    perf-hook never-blocks contract).

No ``mtg_bot_engine`` dependency — the tool parses ``cards.rs`` as
text and imports the pure-Python ``parity.trajectory`` module, so this
runs on a fresh checkout without a ``.pyd`` build.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "check_audit_coverage_staleness.py"
HOOK_PATH = REPO_ROOT / "hooks" / "post-commit"


def _load_tool():
    """Import the script module under a stable name without invoking
    its ``main()`` (same pattern as ``test_effect_coverage``)."""
    spec = importlib.util.spec_from_file_location(
        "_check_audit_coverage_staleness_under_test", SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


# --------------------------------------------------------- live derivers


def test_live_inventory_parses_real_tree():
    """The five derivers return positive ints off the real working
    tree. Structural-regression guard: if a sentinel marker or the
    enum/function shape moves and breaks a parser, this fails directly
    instead of surfacing as a confusing false-drift."""
    mod = _load_tool()
    live = mod.collect_live_inventory()
    assert set(live) == {
        "rust_effect_variants",
        "bridge_arms",
        "safe_triggers",
        "safe_keywords",
        "safe_effect_keys",
    }
    for key, val in live.items():
        assert isinstance(val, int), key
        assert val > 0, f"{key} should be a positive count, got {val}"
    # Sanity floors — these only ever grow in this campaign.
    assert live["rust_effect_variants"] >= 100
    assert live["bridge_arms"] >= 100
    assert live["safe_keywords"] >= 12


def test_bridge_arm_count_is_function_scoped(tmp_path):
    """``count_bridge_arms`` must count only ``kind ==`` literals
    INSIDE ``_ta_dict_to_python_effect`` (between the def and the
    insert sentinel) and must ignore ones in comments — a ``kind ==``
    in a docstring elsewhere in the file must not inflate the count."""
    mod = _load_tool()
    fake = tmp_path / "ce.py"
    fake.write_text(
        textwrap.dedent(
            '''
            def _ta_dict_to_python_predicate(d):
                if kind == "decoy_outside_function":
                    return 1

            def _ta_dict_to_python_effect(eff_dict):
                kind = eff_dict["kind"]
                if kind == "real_arm_one":
                    return 1
                # commented: if kind == "comment_decoy":
                if kind == "real_arm_two":
                    return 2
                # === PHASE5_BRIDGE_ARMS_INSERT_ABOVE_THIS_LINE ===

            def after():
                if kind == "below_sentinel_decoy":
                    return 9
            '''
        ),
        encoding="utf-8",
    )
    assert mod.count_bridge_arms(fake) == 2


def test_count_bridge_arms_missing_function_raises(tmp_path):
    mod = _load_tool()
    bad = tmp_path / "ce.py"
    bad.write_text("def something_else(): pass\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="_ta_dict_to_python_effect"):
        mod.count_bridge_arms(bad)


def test_count_bridge_arms_missing_sentinel_raises(tmp_path):
    mod = _load_tool()
    bad = tmp_path / "ce.py"
    bad.write_text(
        "def _ta_dict_to_python_effect(d):\n"
        '    if kind == "x":\n        return 1\n',
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="PHASE5_BRIDGE_ARMS_INSERT"):
        mod.count_bridge_arms(bad)


def test_rust_variant_count_matches_coverage_helper():
    """The staleness check reuses the coverage script's Rust parser so
    the two can never disagree on the parsing rule. Verify they return
    the same number off the real tree."""
    mod = _load_tool()
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from measure_effect_coverage import collect_rust_effect_variants

    assert mod.count_rust_effect_variants() == len(
        collect_rust_effect_variants()
    )


# ---------------------------------------------------- sentinel parser


_GOOD_BLOCK = textwrap.dedent(
    """
    Some prose before.

    {begin}
    <!-- a multi-line html comment
         whose continuation lines do not each start with the
         comment opener — must still be skipped wholesale -->
    # a hash comment
    rust_effect_variants = 107
    bridge_arms = 109
    safe_triggers = 18
    safe_keywords = 12
    safe_effect_keys = 8
    {end}

    Some prose after.
    """
)


def _doc(begin, end, body):
    return body.format(begin=begin, end=end)


def test_parse_sentinel_block_happy(tmp_module=None):
    mod = _load_tool()
    text = _doc(mod.SENTINEL_BEGIN, mod.SENTINEL_END, _GOOD_BLOCK)
    parsed = mod.parse_sentinel_block(text)
    assert parsed == {
        "rust_effect_variants": 107,
        "bridge_arms": 109,
        "safe_triggers": 18,
        "safe_keywords": 12,
        "safe_effect_keys": 8,
    }


def test_parse_sentinel_block_missing_block_raises():
    mod = _load_tool()
    with pytest.raises(RuntimeError, match="missing the"):
        mod.parse_sentinel_block("no sentinel here at all")


def test_parse_sentinel_block_no_equals_raises():
    mod = _load_tool()
    text = (
        mod.SENTINEL_BEGIN
        + "\nrust_effect_variants 107\n"
        + mod.SENTINEL_END
    )
    with pytest.raises(RuntimeError, match="no '='"):
        mod.parse_sentinel_block(text)


def test_parse_sentinel_block_unknown_key_raises():
    mod = _load_tool()
    text = (
        mod.SENTINEL_BEGIN
        + "\nbogus_key = 1\n"
        + mod.SENTINEL_END
    )
    with pytest.raises(RuntimeError, match="unknown STALENESS-SENTINEL"):
        mod.parse_sentinel_block(text)


def test_parse_sentinel_block_non_int_raises():
    mod = _load_tool()
    text = (
        mod.SENTINEL_BEGIN
        + "\nrust_effect_variants = lots\n"
        + mod.SENTINEL_END
    )
    with pytest.raises(RuntimeError, match="not an int"):
        mod.parse_sentinel_block(text)


def test_parse_sentinel_block_missing_keys_raises():
    mod = _load_tool()
    text = (
        mod.SENTINEL_BEGIN
        + "\nrust_effect_variants = 1\n"
        + mod.SENTINEL_END
    )
    with pytest.raises(RuntimeError, match="missing keys"):
        mod.parse_sentinel_block(text)


# ---------------------------------------------------- coverage-doc parse


def test_parse_coverage_doc_rust_count_happy():
    mod = _load_tool()
    assert (
        mod.parse_coverage_doc_rust_count(
            "blah\n- **107 Rust `Effect` variants** in ...\nblah"
        )
        == 107
    )


def test_parse_coverage_doc_rust_count_missing_raises():
    mod = _load_tool()
    with pytest.raises(RuntimeError, match="could not find"):
        mod.parse_coverage_doc_rust_count("no headline here")


# ------------------------------------------------------ drift + report


def _live():
    return {
        "rust_effect_variants": 107,
        "bridge_arms": 109,
        "safe_triggers": 18,
        "safe_keywords": 12,
        "safe_effect_keys": 8,
    }


def test_compute_drift_in_sync_is_empty():
    mod = _load_tool()
    live = _live()
    drifts = mod.compute_drift(live, dict(live), 107)
    assert drifts == []
    report = mod.build_report(drifts)
    assert "in sync" in report
    assert "DRIFT" not in report


def test_compute_drift_reports_each_stale_count():
    mod = _load_tool()
    live = _live()
    claimed = {
        "rust_effect_variants": 104,
        "bridge_arms": 106,
        "safe_triggers": 15,
        "safe_keywords": 12,  # in sync
        "safe_effect_keys": 6,
    }
    drifts = mod.compute_drift(live, claimed, 107)
    drifted_keys = {d.key for d in drifts}
    assert drifted_keys == {
        "rust_effect_variants",
        "bridge_arms",
        "safe_triggers",
        "safe_effect_keys",
    }
    report = mod.build_report(drifts)
    assert "DRIFT DETECTED" in report
    # Precise actionable content: claimed, actual, signed delta.
    assert "doc-claimed 104, actual 107 (delta +3)" in report
    assert "doc-claimed 15, actual 18 (delta +3)" in report
    assert "round-34/49/51 staleness class" in report
    # The in-sync count must NOT appear.
    assert "_SAFE_KEYWORDS" not in report


def test_compute_drift_flags_committed_stale_coverage_doc():
    """The round-51 class: the auto-generated coverage doc was
    committed at a stale variant count. Even if the audit sentinel is
    in sync, a stale coverage-doc headline must be flagged with the
    regenerate hint."""
    mod = _load_tool()
    live = _live()
    drifts = mod.compute_drift(live, dict(live), coverage_rust_count=93)
    assert len(drifts) == 1
    d = drifts[0]
    assert d.key == "coverage_doc_rust_variants"
    assert d.claimed == 93 and d.actual == 107
    assert "regenerate" in mod.build_report(drifts)


def test_compute_drift_skips_coverage_check_when_doc_absent():
    mod = _load_tool()
    live = _live()
    assert mod.compute_drift(live, dict(live), None) == []


def test_run_against_real_tree_is_in_sync(capsys):
    """End-to-end: against the committed tree (this branch ships the
    refreshed sentinel + regenerated coverage doc) the tool must
    report in sync and return 0."""
    mod = _load_tool()
    rc = mod.run()
    out = capsys.readouterr().out
    assert rc == 0, f"expected in-sync exit 0; report:\n{out}"
    assert "in sync" in out


def test_run_writes_to_provided_stream():
    import io

    mod = _load_tool()
    buf = io.StringIO()
    rc = mod.run(write_stream=buf)
    assert rc == 0
    assert "[staleness]" in buf.getvalue()


def test_main_returns_run_exit_code():
    mod = _load_tool()
    assert mod.main() == 0


# ----------------------------------------------------- post-commit hook
#
# The hook resolves its repo root + branch off the REAL checkout
# (``_git`` hardcodes ``cwd=REPO_ROOT``), so a throwaway tmp git repo
# can't drive its branch logic. Load it as a module and stub ``_git``
# / ``subprocess`` to exercise the main-only + never-block contract
# deterministically (same script-loading pattern as the tool above).


def _load_hook():
    # ``hooks/post-commit`` has no ``.py`` suffix, so an explicit
    # SourceFileLoader is needed (extension-based auto-detection
    # would reject it).
    from importlib.machinery import SourceFileLoader

    loader = SourceFileLoader(
        "_post_commit_hook_under_test", str(HOOK_PATH)
    )
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = mod
    loader.exec_module(mod)
    return mod


def test_hook_loads_as_module():
    """The version-controlled hook is importable (valid Python) and
    exposes the split perf/staleness steps + main."""
    hook = _load_hook()
    assert hasattr(hook, "_run_perf_step")
    assert hasattr(hook, "_run_staleness_step")
    assert hasattr(hook, "main")


def test_hook_skips_on_feature_branch(monkeypatch):
    """Feature-branch commits are silently skipped: neither step
    runs, no output (mirrors the perf-hook feature-branch contract)."""
    hook = _load_hook()
    monkeypatch.setattr(hook, "_git", lambda *a: "feature/whatever")
    perf_called, stale_called = [], []
    monkeypatch.setattr(
        hook, "_run_perf_step", lambda p: perf_called.append(p)
    )
    monkeypatch.setattr(
        hook, "_run_staleness_step", lambda p: stale_called.append(p)
    )
    hook.main()  # must not raise
    assert perf_called == [] and stale_called == []


def test_hook_runs_both_steps_on_main(monkeypatch):
    """On ``main`` both the perf and staleness steps run, and the
    staleness step runs even though they are independent."""
    hook = _load_hook()
    monkeypatch.setattr(hook, "_git", lambda *a: "main")
    monkeypatch.setattr(hook, "_find_venv_python", lambda: "/fake/py")
    calls = []
    monkeypatch.setattr(
        hook, "_run_perf_step", lambda p: calls.append(("perf", p))
    )
    monkeypatch.setattr(
        hook, "_run_staleness_step", lambda p: calls.append(("stale", p))
    )
    hook.main()
    assert calls == [("perf", "/fake/py"), ("stale", "/fake/py")]


def test_hook_staleness_step_no_venv_is_silent_skip(monkeypatch, capsys):
    """No venv → the staleness step prints a ``[staleness hook]`` skip
    note and returns (never raises, never blocks)."""
    hook = _load_hook()
    hook._run_staleness_step(None)
    err = capsys.readouterr().err
    assert "[staleness hook]" in err and "no .venv" in err


def test_hook_staleness_step_reports_drift_without_blocking(
    monkeypatch, capsys
):
    """A non-zero staleness exit (drift) is echoed to stderr but the
    step returns normally — the hook never propagates it (the
    never-block contract that would have caught round-47/48)."""
    hook = _load_hook()

    class _Proc:
        returncode = 1
        stdout = "[staleness] DRIFT DETECTED ...\n"
        stderr = ""

    monkeypatch.setattr(
        hook.subprocess, "run", lambda *a, **k: _Proc()
    )
    # STALENESS_SCRIPT genuinely exists in this branch's tree, so the
    # step proceeds to the (stubbed) subprocess call.
    assert hook.STALENESS_SCRIPT.exists()
    hook._run_staleness_step("/fake/py")  # must not raise
    err = capsys.readouterr().err
    assert "DRIFT DETECTED" in err


def test_hook_staleness_step_swallows_exceptions(monkeypatch, capsys):
    """Belt-and-suspenders: if the subprocess call itself raises, the
    step swallows it with a ``[staleness hook]`` note so the commit
    always succeeds (never-block contract)."""
    hook = _load_hook()

    def _boom(*a, **k):
        raise OSError("kaboom")

    monkeypatch.setattr(hook.subprocess, "run", _boom)
    assert hook.STALENESS_SCRIPT.exists()
    hook._run_staleness_step("/fake/py")  # must not raise
    err = capsys.readouterr().err
    assert "[staleness hook] check raised, ignoring" in err


def test_hook_end_to_end_subprocess_never_blocks():
    """Run the hook as a real subprocess (as git would). It resolves
    the REAL checkout's branch; whatever branch the test runs on, the
    hook must exit 0 — it never blocks a commit by contract."""
    proc = subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, (
        f"hook must never block; rc={proc.returncode}\n"
        f"stdout={proc.stdout}\nstderr={proc.stderr}"
    )
