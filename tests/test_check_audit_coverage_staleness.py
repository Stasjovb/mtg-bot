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


# ---------------------------------------- round-54 per-entry residue check
#
# These pin the structural fix the round-52 count-only cron missed: a
# BLOCKED-RUST-EFFECT residue entry naming an Effect that actually
# exists. Covers the alias-resolution rule, a stale entry IS detected,
# a genuinely-missing entry is NOT falsely flagged, the closed-entry
# regression guard, the worklist parser error paths, and the
# round-51/53 confirmed-stale trio is provably caught.


def test_camel_to_snake_acronym_aware():
    """The exact bug the round-54 re-walk's first pass hit: an
    acronym run like ``UEOT`` must collapse to ``ueot``, not
    ``u_e_o_t`` — otherwise the bridge-arm lookup misses and a
    genuinely-closed entry would be falsely reported stale-the-other-
    way (or, worse, a stale entry would be missed)."""
    mod = _load_tool()
    assert (
        mod._camel_to_snake("DoubleTargetCreaturesPowerUEOT")
        == "double_target_creatures_power_ueot"
    )
    assert (
        mod._camel_to_snake("TapTargetOpponentPermanentAndStunIt")
        == "tap_target_opponent_permanent_and_stun_it"
    )
    assert (
        mod._camel_to_snake("DealDamageToOpponentCreatureByArtifactCount")
        == "deal_damage_to_opponent_creature_by_artifact_count"
    )


def test_resolve_residue_entry_alias_resolution():
    """The plan-name → real-variant alias pass: the audit/plan name
    (`TwoMobileSubjects`) is NOT a live variant, but its alias
    (`TwoSubjectPumpAndDebuffByArtifactCount`) is — the first alias
    present in the live enum wins, and ``bridged`` is computed via the
    acronym-aware snake_case."""
    mod = _load_tool()
    rust = {"TwoSubjectPumpAndDebuffByArtifactCount", "Unrelated"}
    bridge = {"two_subject_pump_and_debuff_by_artifact_count"}
    entry = {
        "entry": "TwoMobileSubjects",
        "card": "Monoist Circuit-Feeder",
        "status": "genuinely_missing",
        "claimed_missing_effect": "TwoMobileSubjects",
        "aliases": [
            "TwoMobileSubjects",  # plan-invented, NOT a live variant
            "TwoSubjectPumpAndDebuffByArtifactCount",  # the real one
        ],
    }
    r = mod.resolve_residue_entry(entry, rust, bridge)
    assert r.resolved_variant == "TwoSubjectPumpAndDebuffByArtifactCount"
    assert r.bridged is True


def test_resolve_residue_entry_genuinely_missing_stays_none():
    mod = _load_tool()
    entry = {
        "entry": "SacUnlessYouTap",
        "card": "Command Bridge",
        "status": "genuinely_missing",
        "claimed_missing_effect": "SacUnlessYouTap",
        "aliases": ["SacUnlessYouTap", "SacrificeSelfUnlessYouTapAPermanent"],
    }
    r = mod.resolve_residue_entry(entry, {"DrawCards"}, {"draw_cards"})
    assert r.resolved_variant is None
    assert r.bridged is False


def test_compute_residue_staleness_detects_stale_entry():
    """A ``genuinely_missing`` entry whose claimed Effect actually
    resolves to a live + bridged variant is flagged STALE — exactly
    the Mechanozoa/Warmaker/Mightform sub-class the count-only cron
    could not catch."""
    mod = _load_tool()
    rust = {"TapTargetOpponentPermanentAndStunIt"}
    bridge = {"tap_target_opponent_permanent_and_stun_it"}
    entries = [
        {
            "entry": "TapTargetAndPutStunCounter",
            "card": "Mechanozoa",
            "status": "genuinely_missing",
            "claimed_missing_effect": "TapTargetAndPutStunCounter",
            "aliases": ["TapTargetOpponentPermanentAndStunIt"],
        }
    ]
    drifts = mod.compute_residue_staleness(entries, rust, bridge)
    assert len(drifts) == 1
    d = drifts[0]
    assert d.key == "residue_stale::TapTargetAndPutStunCounter"
    assert "Mechanozoa" in d.label
    assert "resolves to live" in d.hint
    assert "TapTargetOpponentPermanentAndStunIt" in d.hint
    # Renders as a plain STALE line, not the numeric "doc-claimed" form.
    assert d.line().startswith("  - STALE:")
    assert "doc-claimed" not in d.line()


def test_compute_residue_staleness_genuinely_missing_not_flagged():
    """A genuinely-missing entry (no alias resolves) is NOT falsely
    flagged — the check must not minimize the count by false
    positives."""
    mod = _load_tool()
    entries = [
        {
            "entry": "SacUnlessYouTap",
            "card": "Command Bridge",
            "status": "genuinely_missing",
            "claimed_missing_effect": "SacUnlessYouTap",
            "aliases": ["SacUnlessYouTap"],
        }
    ]
    drifts = mod.compute_residue_staleness(
        entries, {"DrawCards", "GainLife"}, {"draw_cards"}
    )
    assert drifts == []


def test_compute_residue_staleness_live_but_unbridged_still_flagged():
    """A claimed-missing Effect that exists in the live enum but has
    NO bridge arm is STILL stale (the residue list over-counts it as
    no-Rust-arm) — the message just notes the missing bridge arm."""
    mod = _load_tool()
    entries = [
        {
            "entry": "X",
            "card": "Card X",
            "status": "genuinely_missing",
            "claimed_missing_effect": "FooBar",
            "aliases": ["FooBar"],
        }
    ]
    drifts = mod.compute_residue_staleness(entries, {"FooBar"}, set())
    assert len(drifts) == 1
    assert "no bridge arm" in drifts[0].hint


def test_compute_residue_staleness_closed_entry_regression_guard():
    """The inverse: a ``closed`` entry whose recorded
    ``resolved_variant`` no longer resolves (variant renamed/removed
    or its bridge arm dropped) means the closure prose itself went
    stale — flagged as ``residue_closure_stale``."""
    mod = _load_tool()
    entries = [
        {
            "entry": "TwoMobileSubjects",
            "card": "Monoist Circuit-Feeder",
            "status": "closed",
            "claimed_missing_effect": "TwoMobileSubjects",
            "resolved_variant": "TwoSubjectPumpAndDebuffByArtifactCount",
            "aliases": ["TwoSubjectPumpAndDebuffByArtifactCount"],
        }
    ]
    # Variant gone from the live enum → closure no longer holds.
    drifts = mod.compute_residue_staleness(entries, set(), set())
    assert len(drifts) == 1
    assert drifts[0].key.startswith("residue_closure_stale::")
    assert "closure" in drifts[0].label
    # Still-resolving closed entry → no drift.
    ok = mod.compute_residue_staleness(
        entries,
        {"TwoSubjectPumpAndDebuffByArtifactCount"},
        {"two_subject_pump_and_debuff_by_artifact_count"},
    )
    assert ok == []


def test_parse_residue_worklist_real_file_is_valid():
    """The committed ``docs/residue_worklist.json`` parses + validates
    + has both statuses (structural-regression guard, like
    ``test_live_inventory_parses_real_tree``)."""
    mod = _load_tool()
    entries = mod.parse_residue_worklist()
    assert len(entries) >= 15
    statuses = {e["status"] for e in entries}
    assert statuses == {"genuinely_missing", "closed"}
    # The round-51/53 confirmed-stale trio + the round-54 pair must
    # all be recorded as closed (not genuinely_missing).
    closed_cards = {
        e["card"] for e in entries if e["status"] == "closed"
    }
    for card in (
        "Mechanozoa",
        "Warmaker Gunship",
        "Mightform Harmonizer",
        "Monoist Circuit-Feeder",
        "Extinguisher Battleship",
    ):
        assert card in closed_cards, card


def test_parse_residue_worklist_missing_file_raises(tmp_path):
    mod = _load_tool()
    with pytest.raises(RuntimeError, match="missing"):
        mod.parse_residue_worklist(tmp_path / "nope.json")


def test_parse_residue_worklist_bad_json_raises(tmp_path):
    mod = _load_tool()
    bad = tmp_path / "wl.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(RuntimeError, match="not valid JSON"):
        mod.parse_residue_worklist(bad)


def test_parse_residue_worklist_no_entries_raises(tmp_path):
    mod = _load_tool()
    bad = tmp_path / "wl.json"
    bad.write_text('{"entries": []}', encoding="utf-8")
    with pytest.raises(RuntimeError, match="no 'entries' list"):
        mod.parse_residue_worklist(bad)


def test_parse_residue_worklist_bad_status_raises(tmp_path):
    mod = _load_tool()
    bad = tmp_path / "wl.json"
    bad.write_text(
        '{"entries": [{"entry": "x", "status": "weird", '
        '"aliases": ["A"]}]}',
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="invalid\\s+status"):
        mod.parse_residue_worklist(bad)


def test_parse_residue_worklist_closed_needs_resolved_variant(tmp_path):
    mod = _load_tool()
    bad = tmp_path / "wl.json"
    bad.write_text(
        '{"entries": [{"entry": "x", "status": "closed", '
        '"aliases": ["A"]}]}',
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="must record a"):
        mod.parse_residue_worklist(bad)


def test_residue_check_would_have_caught_the_known_stale_trio():
    """End-to-end proof against the REAL live tree: if Mechanozoa /
    Warmaker Gunship / Mightform Harmonizer were (as the pre-round-54
    audit had them) still classed ``genuinely_missing``, the per-entry
    check flags ALL THREE — this is the round-52-cron gap closed. A
    genuinely-missing control (Command Bridge) is NOT flagged in the
    same batch."""
    mod = _load_tool()
    rust = mod.collect_rust_variant_set()
    bridge = mod.collect_bridge_arm_set()
    simulated_pre_r54 = [
        {
            "entry": "TapTargetAndPutStunCounter",
            "card": "Mechanozoa",
            "status": "genuinely_missing",
            "claimed_missing_effect": "TapTargetAndPutStunCounter",
            "aliases": ["TapTargetOpponentPermanentAndStunIt"],
        },
        {
            "entry": "DealDamageToAnyTargetEqualToArtifactCount",
            "card": "Warmaker Gunship",
            "status": "genuinely_missing",
            "claimed_missing_effect": (
                "DealDamageToAnyTargetEqualToArtifactCount"
            ),
            "aliases": ["DealDamageToOpponentCreatureByArtifactCount"],
        },
        {
            "entry": "DoubleTargetPowerUntilEOT",
            "card": "Mightform Harmonizer",
            "status": "genuinely_missing",
            "claimed_missing_effect": "DoubleTargetPowerUntilEOT",
            "aliases": ["DoubleTargetCreaturesPowerUEOT"],
        },
        {
            "entry": "SacUnlessYouTap",
            "card": "Command Bridge",
            "status": "genuinely_missing",  # genuinely missing control
            "claimed_missing_effect": "SacUnlessYouTap",
            "aliases": ["SacUnlessYouTap"],
        },
    ]
    drifts = mod.compute_residue_staleness(
        simulated_pre_r54, rust, bridge
    )
    flagged = {d.label for d in drifts}
    assert len(drifts) == 3
    assert any("Mechanozoa" in f for f in flagged)
    assert any("Warmaker Gunship" in f for f in flagged)
    assert any("Mightform Harmonizer" in f for f in flagged)
    assert not any("Command Bridge" in f for f in flagged)


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
    # Round-54 widened the lineage string to include round-53 + the
    # per-entry extension; assert the stable substring.
    assert "round-34/49/51/53 staleness class" in report
    assert "round-54 per-entry extension" in report
    # Pure count-drift input → only the headline-count section, no
    # per-entry residue section.
    assert "Headline-count drift:" in report
    assert "Per-entry residue staleness" not in report
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
