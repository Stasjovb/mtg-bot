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
    + carries all three round-56 statuses (structural-regression
    guard, like ``test_live_inventory_parses_real_tree``)."""
    mod = _load_tool()
    entries = mod.parse_residue_worklist()
    assert len(entries) >= 15
    statuses = {e["status"] for e in entries}
    # Round-56 added the third `blocked_non_effect` status; the
    # committed file now carries all three (Seedship Agrarian is the
    # blocked_non_effect entry).
    assert statuses == {
        "genuinely_missing",
        "blocked_non_effect",
        "closed",
    }
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


# ------------------ round-55 structural (non-lexical) hardening
#
# These pin the structural anti-staleness fix whose own gap round-54
# exposed: the round-54 resolver is purely LEXICAL (an alias must
# literally be a live variant), so Pulsar Squadron Ace — Effect
# LookAtTopNRevealOrCounter shipped r28/29, plan-name
# ChoiceTriggerSpacecraftRevealOrCounter never lexically resolving —
# passed BOTH the re-walk and the per-entry cron silently. Round-55
# adds (a) a required `verified_absent_at_commit` stamp + a
# cards.rs/cross_engine.py-touch cadence, and (b) a non-lexical
# name-in-wired-bridge-arm cross-check (Pulsar's name is verbatim in
# the wired look_at_top_n_reveal_or_counter arm). Both never-blocking
# (same hook contract). Covered: the Pulsar shape IS flagged
# non-lexically; a genuinely-absent entry is NOT false-flagged; the
# per-arm ack suppresses (and only the exact arm); the stale-SHA
# cadence path; the schema-missing-field path; the helpers.


def test_camel_to_snake_still_acronym_aware_for_round55_path():
    """The round-55 non-lexical resolver reuses ``_camel_to_snake``
    to map a live variant to its expected bridge ``kind``. Re-pin the
    acronym rule on the exact Pulsar variant so a regression in the
    snake_case rule can't silently re-open the gap."""
    mod = _load_tool()
    assert (
        mod._camel_to_snake("LookAtTopNRevealOrCounter")
        == "look_at_top_n_reveal_or_counter"
    )


def test_split_bridge_arm_blocks_keeps_comments(tmp_path):
    """Unlike the count path, the round-55 arm splitter must KEEP
    comments — a wired arm's doc-comment naming the card IS the
    non-lexical signal (Pulsar's name is only in the arm comment).
    Also: arm-scoped (def → sentinel), keyed by kind."""
    mod = _load_tool()
    fake = tmp_path / "ce.py"
    fake.write_text(
        textwrap.dedent(
            '''
            def _ta_dict_to_python_effect(eff_dict):
                kind = eff_dict["kind"]
                if kind == "arm_one":
                    # names Some Card Name in a comment
                    return 1
                if kind == "arm_two":
                    return 2
                # === PHASE5_BRIDGE_ARMS_INSERT_ABOVE_THIS_LINE ===

            def after():
                if kind == "below_decoy":
                    return 9
            '''
        ),
        encoding="utf-8",
    )
    blocks = mod.split_bridge_arm_blocks(fake)
    assert set(blocks) == {"arm_one", "arm_two"}
    # Comment text is retained inside the arm block.
    assert "Some Card Name" in blocks["arm_one"]
    assert "below_decoy" not in "".join(blocks.values())


def test_pulsar_shaped_entry_is_caught_non_lexically():
    """THE round-55 proof. A pre-r54-shaped Pulsar entry — status
    ``genuinely_missing``, aliases that do NOT lexically resolve to
    the real variant ``LookAtTopNRevealOrCounter``, no ack — is
    flagged ``residue_suspect_needs_reverify`` against the REAL live
    tree, because "Pulsar Squadron Ace" appears verbatim in the
    wired ``look_at_top_n_reveal_or_counter`` arm whose kind resolves
    to live ``Effect::LookAtTopNRevealOrCounter``. The round-54
    lexical resolver returns nothing for this exact entry (no alias
    is a live variant) — that contrast IS the closed gap."""
    mod = _load_tool()
    rust = mod.collect_rust_variant_set()
    arms = mod.split_bridge_arm_blocks()
    bridge = mod.collect_bridge_arm_set()
    pulsar_pre_r54 = {
        "entry": "PulsarSquadronAce-Spacecraft-submode",
        "card": "Pulsar Squadron Ace",
        "status": "genuinely_missing",
        "claimed_missing_effect": "ChoiceTriggerSpacecraftRevealOrCounter",
        # The exact pre-r54 alias list — NOTE no
        # "LookAtTopNRevealOrCounter". This is the gap.
        "aliases": [
            "ChoiceTriggerSpacecraftRevealOrCounter",
            "LookTop5RevealSpacecraftElseCounterOnSelf",
        ],
        "verified_absent_at_commit": "deadbee",  # SHA-shaped, fake
    }
    # Round-54 LEXICAL resolver: blind to this entry (no alias is a
    # live variant) — exactly why Pulsar slipped through.
    lex = mod.compute_residue_staleness([pulsar_pre_r54], rust, bridge)
    assert lex == [], (
        "the round-54 lexical resolver is (correctly, for this test) "
        "blind to the Pulsar shape — that blindness is the gap "
        "round-55 closes"
    )
    # Round-55 STRUCTURAL check: catches it non-lexically.
    drifts = mod.compute_structural_residue_staleness(
        [pulsar_pre_r54], rust, arms, git_available=False
    )
    suspect = [
        d
        for d in drifts
        if d.key.startswith("residue_suspect_needs_reverify::")
        and d.key.endswith("PulsarSquadronAce-Spacecraft-submode")
    ]
    assert suspect, (
        f"Pulsar-shaped entry MUST surface "
        f"residue_suspect_needs_reverify; got {[d.key for d in drifts]}"
    )
    hit = next(
        d
        for d in suspect
        if "look_at_top_n_reveal_or_counter" in d.hint
    )
    assert "LookAtTopNRevealOrCounter" in hit.hint
    assert "Pulsar Squadron Ace" in hit.label
    assert hit.line().startswith("  - NEEDS RE-VERIFY:")


def test_genuinely_absent_entry_not_false_flagged_structurally():
    """A genuinely-absent entry whose printed name is in NO bridge
    arm is NOT flagged by the non-lexical check (only the unverified
    row if it lacks a stamp). The check must not minimize the residue
    count via false positives."""
    mod = _load_tool()
    rust = mod.collect_rust_variant_set()
    arms = mod.split_bridge_arm_blocks()
    entry = {
        "entry": "SeedshipAgrarian-landfall-composer",
        "card": "Seedship Agrarian",
        "status": "genuinely_missing",
        "claimed_missing_effect": "LandfallComplexEffectSeedship",
        "aliases": ["LandfallComplexEffectSeedship"],
        "verified_absent_at_commit": "abc1234",
    }
    drifts = mod.compute_structural_residue_staleness(
        [entry], rust, arms, git_available=False
    )
    assert drifts == [], (
        f"genuinely-absent Seedship Agrarian must NOT be flagged; "
        f"got {[d.key for d in drifts]}"
    )


def test_alias_matched_name_in_arm_is_hard_stale_not_ack_suppressible():
    """If the named wired arm's kind ALSO matches one of the entry's
    own aliases, that is the entry's own data proving the effect
    shipped → hard ``residue_stale``, and a ``name_in_arm_ack`` must
    NOT suppress it (acks are for unrelated arms only; a true shipped
    effect must hard-fail)."""
    mod = _load_tool()
    rust = {"FooBarEffect"}
    arms = {"foo_bar_effect": '  # handles Stale Card here\n  return 1'}
    entry = {
        "entry": "x",
        "card": "Stale Card",
        "status": "genuinely_missing",
        "claimed_missing_effect": "FooBarEffect",
        "aliases": ["FooBarEffect"],  # alias-match → hard stale
        "verified_absent_at_commit": "abc1234",
        # Even an ack on the exact arm must not suppress the hard row.
        "name_in_arm_ack": "foo_bar_effect",
    }
    drifts = mod.compute_structural_residue_staleness(
        [entry], rust, arms, git_available=False
    )
    keys = [d.key for d in drifts]
    assert any(
        k.startswith("residue_stale::") for k in keys
    ), keys
    assert not any(
        k.startswith("residue_suspect_needs_reverify::") for k in keys
    )
    stale = next(d for d in drifts if d.key.startswith("residue_stale::"))
    assert "NOT ack-suppressible" in stale.hint
    assert stale.line().startswith("  - STALE:")


def test_name_in_arm_ack_suppresses_only_the_exact_arm():
    """The per-arm ack suppresses the suspect row for the acked arm
    ONLY. A SECOND, un-acked wired arm that also names the card still
    surfaces — so an ack can never silently mask a future real
    Pulsar. (Command-Bridge/Meltstrider shape: name legitimately in a
    different-ability arm, hand-re-walked, genuinely absent.)"""
    mod = _load_tool()
    rust = {"AddManaToPool", "LookAtTopNRevealOrCounter"}
    arms = {
        "add_mana_to_pool": "  # mana ability of Command Bridge\n  x",
        "look_at_top_n_reveal_or_counter": (
            "  # Command Bridge also named here (hypothetical 2nd arm)\n y"
        ),
    }
    base = {
        "entry": "SacUnlessYouTap",
        "card": "Command Bridge",
        "status": "genuinely_missing",
        "claimed_missing_effect": "SacUnlessYouTap",
        "aliases": ["SacUnlessYouTap"],
        "verified_absent_at_commit": "abc1234",
    }
    # Ack only the mana-ability arm.
    acked = dict(base, name_in_arm_ack="add_mana_to_pool")
    drifts = mod.compute_structural_residue_staleness(
        [acked], rust, arms, git_available=False
    )
    keys = [d.key for d in drifts]
    # add_mana_to_pool suspect suppressed; the OTHER arm still fires.
    suspects = [
        d
        for d in drifts
        if d.key.startswith("residue_suspect_needs_reverify::")
    ]
    assert len(suspects) == 1, keys
    assert "look_at_top_n_reveal_or_counter" in suspects[0].hint
    assert "add_mana_to_pool" not in suspects[0].hint
    # Acking BOTH arms suppresses both.
    acked_both = dict(
        base,
        name_in_arm_ack=[
            "add_mana_to_pool",
            "look_at_top_n_reveal_or_counter",
        ],
    )
    assert (
        mod.compute_structural_residue_staleness(
            [acked_both], rust, arms, git_available=False
        )
        == []
    )


def test_missing_verified_absent_at_commit_is_unverified_row():
    """The schema-missing-field path: a ``genuinely_missing`` entry
    with no (or a non-SHA-shaped) ``verified_absent_at_commit`` yields
    a never-blocking ``residue_unverified`` row."""
    mod = _load_tool()
    rust = mod.collect_rust_variant_set()
    arms = mod.split_bridge_arm_blocks()
    no_field = {
        "entry": "x",
        "card": "Some Genuinely Missing Card",
        "status": "genuinely_missing",
        "claimed_missing_effect": "TotallyAbsentEffect",
        "aliases": ["TotallyAbsentEffect"],
    }
    drifts = mod.compute_structural_residue_staleness(
        [no_field], rust, arms, git_available=False
    )
    assert [d.key for d in drifts] == ["residue_unverified::x"]
    assert "no SHA-shaped" in drifts[0].hint
    assert drifts[0].line().startswith("  - NEEDS RE-VERIFY:")
    # A garbled (non-SHA) value is treated the same.
    garbled = dict(no_field, verified_absent_at_commit="not-a-sha!!")
    d2 = mod.compute_structural_residue_staleness(
        [garbled], rust, arms, git_available=False
    )
    assert [d.key for d in d2] == ["residue_unverified::x"]


def test_stale_verified_absent_at_commit_cadence_path(monkeypatch):
    """The cadence path: a SHA-shaped stamp with ≥1 commit since it
    touched cards.rs / cross_engine.py yields a never-blocking
    ``residue_needs_reverify`` row. Patch the git probe so the test
    is deterministic regardless of the checkout's real history."""
    mod = _load_tool()
    rust = mod.collect_rust_variant_set()
    arms = mod.split_bridge_arm_blocks()
    entry = {
        "entry": "y",
        "card": "Absent Card",
        "status": "genuinely_missing",
        "claimed_missing_effect": "AbsentEffect",
        "aliases": ["AbsentEffect"],
        "verified_absent_at_commit": "0badf00",
    }
    # 3 commits touched the trigger files since the stamp → stale.
    monkeypatch.setattr(
        mod, "commits_touching_trigger_paths_since", lambda sha: 3
    )
    drifts = mod.compute_structural_residue_staleness(
        [entry], rust, arms, git_available=True
    )
    assert [d.key for d in drifts] == ["residue_needs_reverify::y"]
    assert "3 commit(s) since then touched" in drifts[0].hint
    assert "0badf00" in drifts[0].hint
    assert drifts[0].line().startswith("  - NEEDS RE-VERIFY:")
    # Fresh stamp (0 touches) → no cadence row.
    monkeypatch.setattr(
        mod, "commits_touching_trigger_paths_since", lambda sha: 0
    )
    assert (
        mod.compute_structural_residue_staleness(
            [entry], rust, arms, git_available=True
        )
        == []
    )
    # git unavailable → soft-skip (never a false re-verify).
    assert (
        mod.compute_structural_residue_staleness(
            [entry], rust, arms, git_available=False
        )
        == []
    )
    # git available but history for the SHA unknown (None) → soft-skip.
    monkeypatch.setattr(
        mod, "commits_touching_trigger_paths_since", lambda sha: None
    )
    assert (
        mod.compute_structural_residue_staleness(
            [entry], rust, arms, git_available=True
        )
        == []
    )


def test_commits_touching_trigger_paths_since_handles_bad_input():
    """``commits_touching_trigger_paths_since`` returns ``None``
    (caller soft-skips, never a false re-verify) for a non-SHA-shaped
    argument — the unverified row owns the missing-stamp error, this
    helper just declines to compute a cadence on garbage."""
    mod = _load_tool()
    assert mod.commits_touching_trigger_paths_since("") is None
    assert mod.commits_touching_trigger_paths_since("not-a-sha") is None
    # A SHA-shaped but non-existent ref → git rev-list fails → None
    # (real git call against the real repo; deterministic: this SHA
    # cannot exist).
    assert (
        mod.commits_touching_trigger_paths_since("0" * 40) is None
    )


def test_real_worklist_genuinely_missing_all_carry_stamp():
    """Structural-regression guard on the committed worklist: every
    ``genuinely_missing`` entry carries a SHA-shaped
    ``verified_absent_at_commit`` (round-55 schema), and the two
    known different-ability cards carry the per-arm ack so the cron
    stays exit-0 in-sync on the real tree."""
    import re

    mod = _load_tool()
    entries = mod.parse_residue_worklist()
    gm = [e for e in entries if e["status"] == "genuinely_missing"]
    # Sanity only — there is still genuine residue. A hard count FLOOR
    # (was `>= 10`) is the wrong invariant: the honest residue
    # legitimately SHRINKS as folds close/­reclassify cards (that is
    # the campaign's success metric, not a regression). The durable
    # guard is the per-entry stamp + per-arm ack below.
    assert len(gm) >= 1
    for e in gm:
        sha = e.get("verified_absent_at_commit")
        assert isinstance(sha, str) and re.fullmatch(
            r"[0-9a-fA-F]{7,40}", sha
        ), f"{e['entry']} missing/garbled verified_absent_at_commit"
    by_card = {e["card"]: e for e in gm}
    assert (
        by_card["Command Bridge"]["name_in_arm_ack"]
        == "add_mana_to_pool"
    )
    assert (
        by_card["Meltstrider's Resolve"]["name_in_arm_ack"]
        == "fight_target_creature_with_target_creature"
    )


def test_run_against_real_tree_still_in_sync_with_round55(capsys):
    """End-to-end: the committed branch state (stamped worklist +
    acks + refreshed sentinel) keeps the cron exit-0 in-sync WITH the
    round-55 structural arm wired into ``run()``."""
    mod = _load_tool()
    rc = mod.run()
    out = capsys.readouterr().out
    assert rc == 0, f"expected in-sync exit 0; report:\n{out}"
    assert "in sync" in out


# ----------------- round-56 blocked_non_effect status invariant
#
# These pin the round-56 third residue status. Its cron invariant is
# the INVERSE of genuinely_missing: instead of asserting a claimed
# Effect stays absent, it asserts every name in the entry's
# `shipped_variants` IS a live Rust Effect:: variant (a silent
# regression to actually-missing → residue_blocked_non_effect_regressed
# — the card quietly became a genuine-Effect ask again) AND requires
# the entry record its specific `non_effect_blocker`
# (missing/empty → residue_blocked_non_effect_underspecified). It does
# NOT require bridged=True (the whole point — the card is gated
# precisely because some non-Effect path is unbridged) and does NOT
# consult verified_absent_at_commit (a genuine-absence stamp is
# meaningless when the Effects are present). Same additive
# never-blocking post-commit-hook contract as the round-54/55 rows
# (the hook tests below are status-agnostic and still cover it).
# Covered: shipped-Effect-present is NOT flagged (even unbridged),
# the regression IS flagged, the underspecified path, the
# parser-accepts-the-status + validates-its-fields error paths, the
# real committed worklist carries exactly the round-56 reclassification,
# and the round-54 lexical / round-55 structural arms leave
# blocked_non_effect entries alone.


def test_blocked_non_effect_shipped_variants_present_not_flagged():
    """The happy path: a ``blocked_non_effect`` entry whose every
    ``shipped_variants`` name IS a live Rust variant is NOT flagged —
    and it is NOT flagged even though it is UNBRIDGED (the invariant
    deliberately does not require bridged=True; the card is gated
    precisely because some non-Effect path is unbridged)."""
    mod = _load_tool()
    entry = {
        "entry": "SeedshipAgrarian-landfall-composer",
        "card": "Seedship Agrarian",
        "status": "blocked_non_effect",
        "claimed_missing_effect": "LandfallComplexEffectSeedship",
        "aliases": ["LandfallComplexEffectSeedship"],
        "shipped_variants": ["CreateToken", "PutPlusOneCounterOnSelf"],
        "non_effect_blocker": (
            "Event.BECOMES_TAPPED unbridged + Lander token-registration"
        ),
    }
    # Both shipped variants live; NO bridge-arm set passed at all —
    # the function does not consult bridging by design.
    rust = {"CreateToken", "PutPlusOneCounterOnSelf", "Unrelated"}
    drifts = mod.compute_blocked_non_effect_staleness([entry], rust)
    assert drifts == [], (
        f"a blocked_non_effect entry whose shipped Effects are all "
        f"live must NOT be flagged (and bridging is irrelevant); got "
        f"{[d.key for d in drifts]}"
    )


def test_blocked_non_effect_regressed_shipped_variant_is_flagged():
    """THE round-56 proof: a ``blocked_non_effect`` entry whose
    declared-shipped Effect silently regressed to actually-missing
    (renamed/removed from the live enum) is flagged
    ``residue_blocked_non_effect_regressed`` — the card quietly became
    a genuine-Rust-Effect ask again and that must NOT pass silently."""
    mod = _load_tool()
    entry = {
        "entry": "SeedshipAgrarian-landfall-composer",
        "card": "Seedship Agrarian",
        "status": "blocked_non_effect",
        "claimed_missing_effect": "LandfallComplexEffectSeedship",
        "aliases": ["LandfallComplexEffectSeedship"],
        "shipped_variants": ["CreateToken", "PutPlusOneCounterOnSelf"],
        "non_effect_blocker": "Event.BECOMES_TAPPED unbridged",
    }
    # PutPlusOneCounterOnSelf is GONE from the live enum → regression.
    rust = {"CreateToken"}
    drifts = mod.compute_blocked_non_effect_staleness([entry], rust)
    assert len(drifts) == 1
    d = drifts[0]
    assert d.key == (
        "residue_blocked_non_effect_regressed::"
        "SeedshipAgrarian-landfall-composer"
    )
    assert "Seedship Agrarian" in d.label
    assert "PutPlusOneCounterOnSelf" in d.hint
    assert "no longer resolve" in d.hint
    # Renders as a plain REGRESSED line, not the numeric form.
    assert d.line().startswith("  - REGRESSED:")
    assert "doc-claimed" not in d.line()


def test_blocked_non_effect_underspecified_blocker_is_flagged():
    """A ``blocked_non_effect`` entry with no (or empty)
    ``non_effect_blocker`` yields a never-blocking
    ``residue_blocked_non_effect_underspecified`` row (the defensive
    in-function mirror — the parser also raises loudly on the
    committed file; see the parser test below)."""
    mod = _load_tool()
    base = {
        "entry": "x",
        "card": "Some Blocked Card",
        "status": "blocked_non_effect",
        "claimed_missing_effect": "Whatever",
        "aliases": ["Whatever"],
        "shipped_variants": ["CreateToken"],
    }
    rust = {"CreateToken"}
    # Missing entirely.
    d1 = mod.compute_blocked_non_effect_staleness([base], rust)
    assert [d.key for d in d1] == [
        "residue_blocked_non_effect_underspecified::x"
    ]
    assert "no non-empty `non_effect_blocker`" in d1[0].hint
    assert d1[0].line().startswith("  - NEEDS RE-VERIFY:")
    # Present but blank.
    blank = dict(base, non_effect_blocker="   ")
    d2 = mod.compute_blocked_non_effect_staleness([blank], rust)
    assert [d.key for d in d2] == [
        "residue_blocked_non_effect_underspecified::x"
    ]


def test_blocked_non_effect_other_statuses_out_of_scope():
    """``compute_blocked_non_effect_staleness`` touches ONLY
    blocked_non_effect entries — a genuinely_missing / closed entry
    in the same batch is ignored (the round-54/55 arms own those)."""
    mod = _load_tool()
    entries = [
        {
            "entry": "gm",
            "card": "GM Card",
            "status": "genuinely_missing",
            "claimed_missing_effect": "AbsentEffect",
            "aliases": ["AbsentEffect"],
            "verified_absent_at_commit": "abc1234",
        },
        {
            "entry": "cl",
            "card": "Closed Card",
            "status": "closed",
            "claimed_missing_effect": "X",
            "aliases": ["XVariant"],
            "resolved_variant": "XVariant",
        },
    ]
    assert (
        mod.compute_blocked_non_effect_staleness(entries, {"XVariant"})
        == []
    )


def test_lexical_and_structural_arms_skip_blocked_non_effect():
    """A ``blocked_non_effect`` entry must NOT be mishandled by the
    round-54 lexical arm (it would otherwise fall into the old
    ``else: closed`` branch and be wrongly closure-regression-flagged)
    nor by the round-55 structural arm (genuinely_missing-only)."""
    mod = _load_tool()
    entry = {
        "entry": "bne",
        "card": "Seedship Agrarian",
        "status": "blocked_non_effect",
        "claimed_missing_effect": "LandfallComplexEffectSeedship",
        "aliases": ["LandfallComplexEffectSeedship"],
        "shipped_variants": ["CreateToken"],
        "non_effect_blocker": "BECOMES_TAPPED unbridged",
    }
    # Round-54 lexical arm: no genuinely_missing/closed handling fires.
    assert (
        mod.compute_residue_staleness([entry], {"CreateToken"}, set())
        == []
    )
    # Round-55 structural arm: status != genuinely_missing → skipped.
    assert (
        mod.compute_structural_residue_staleness(
            [entry], {"CreateToken"}, {}, git_available=False
        )
        == []
    )


def test_parse_residue_worklist_accepts_blocked_non_effect(tmp_path):
    """The parser accepts the new status and enforces its two required
    fields (non-empty ``shipped_variants`` list + non-empty
    ``non_effect_blocker`` string) loudly — same broken-input-is-loud
    contract as the closed ``resolved_variant`` check."""
    mod = _load_tool()
    good = tmp_path / "wl.json"
    good.write_text(
        '{"entries": [{"entry": "x", "status": "blocked_non_effect", '
        '"aliases": ["A"], "shipped_variants": ["CreateToken"], '
        '"non_effect_blocker": "BECOMES_TAPPED unbridged"}]}',
        encoding="utf-8",
    )
    parsed = mod.parse_residue_worklist(good)
    assert parsed[0]["status"] == "blocked_non_effect"

    miss_sv = tmp_path / "wl2.json"
    miss_sv.write_text(
        '{"entries": [{"entry": "x", "status": "blocked_non_effect", '
        '"aliases": ["A"], "non_effect_blocker": "z"}]}',
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="shipped_variants"):
        mod.parse_residue_worklist(miss_sv)

    empty_sv = tmp_path / "wl3.json"
    empty_sv.write_text(
        '{"entries": [{"entry": "x", "status": "blocked_non_effect", '
        '"aliases": ["A"], "shipped_variants": [], '
        '"non_effect_blocker": "z"}]}',
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="shipped_variants"):
        mod.parse_residue_worklist(empty_sv)

    miss_blk = tmp_path / "wl4.json"
    miss_blk.write_text(
        '{"entries": [{"entry": "x", "status": "blocked_non_effect", '
        '"aliases": ["A"], "shipped_variants": ["CreateToken"]}]}',
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="non_effect_blocker"):
        mod.parse_residue_worklist(miss_blk)


def test_real_worklist_has_round56_reclassification():
    """Structural-regression guard on the committed worklist: it
    carries the round-56 reclassifications and every
    ``blocked_non_effect`` entry's declared shipped variants ARE live
    Rust variants (so the cron stays exit-0 in-sync on the real tree);
    every genuinely_missing entry is a TRUE new-Rust-Effect ask (none
    resolve to a live variant).

    Round-56 settled state: Seedship Agrarian (reclassified by N2 in
    the round-56 slice) AND Dauntless Scrapbot (folded at the round-56
    post-N1-merge resync, exactly as N2 queued, once N1 shipped
    ``ExileEachOpponentsGraveyard``) are both ``blocked_non_effect``.
    The guard asserts the structural invariant for EVERY bne entry
    rather than a brittle hardcoded count/index — pinning an exact
    count is the snapshot-pin anti-pattern this campaign exists to
    eliminate (a legitimate post-merge fold must not turn it red)."""
    mod = _load_tool()
    entries = mod.parse_residue_worklist()
    statuses = {e["status"] for e in entries}
    assert statuses == {
        "genuinely_missing",
        "blocked_non_effect",
        "closed",
    }
    bne = [
        e for e in entries if e["status"] == "blocked_non_effect"
    ]
    by_card = {e["card"]: e for e in bne}
    # The two known round-56 reclassifications must both be present.
    assert "Seedship Agrarian" in by_card
    assert "Dauntless Scrapbot" in by_card
    seed = by_card["Seedship Agrarian"]
    assert seed["shipped_variants"] == [
        "CreateToken",
        "PutPlusOneCounterOnSelf",
    ]
    daunt = by_card["Dauntless Scrapbot"]
    assert "ExileEachOpponentsGraveyard" in daunt["shipped_variants"]
    # Generic structural invariant for EVERY blocked_non_effect entry
    # (robust to future legitimate folds): non-empty shipped_variants
    # + a blocker string + no meaningless absence stamp.
    for e in bne:
        assert e["shipped_variants"], e["card"]
        assert e["non_effect_blocker"].strip(), e["card"]
        # `verified_absent_at_commit` is meaningless for
        # blocked_non_effect (the Effects are present) — must NOT carry
        # one.
        assert "verified_absent_at_commit" not in e, e["card"]
    # The declared shipped Effects ARE live Rust variants → the round-56
    # invariant holds on the real tree (no regression row).
    rust = mod.collect_rust_variant_set()
    assert mod.compute_blocked_non_effect_staleness(entries, rust) == []
    # The honest "how far from parity" count: every genuinely_missing
    # entry is a TRUE new-Rust-Effect ask (none lexically resolve to a
    # live variant — re-pinned against the REAL tree).
    bridge = mod.collect_bridge_arm_set()
    for e in entries:
        if e["status"] != "genuinely_missing":
            continue
        r = mod.resolve_residue_entry(e, rust, bridge)
        assert r.resolved_variant is None, (
            f"{e['entry']} is classed genuinely_missing but resolves "
            f"to live Effect::{r.resolved_variant} — it is NOT a TRUE "
            f"new-Rust-Effect ask"
        )


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
    exposes the split perf/staleness/pool-parity steps + main."""
    hook = _load_hook()
    assert hasattr(hook, "_run_perf_step")
    assert hasattr(hook, "_run_staleness_step")
    # Round-57: the never-blocking pool-parity headline step.
    assert hasattr(hook, "_run_pool_parity_headline_step")
    assert hasattr(hook, "main")


def test_hook_skips_on_feature_branch(monkeypatch):
    """Feature-branch commits are silently skipped: no step
    runs, no output (mirrors the perf-hook feature-branch contract)."""
    hook = _load_hook()
    monkeypatch.setattr(hook, "_git", lambda *a: "feature/whatever")
    perf_called, stale_called, pp_called = [], [], []
    monkeypatch.setattr(
        hook, "_run_perf_step", lambda p: perf_called.append(p)
    )
    monkeypatch.setattr(
        hook, "_run_staleness_step", lambda p: stale_called.append(p)
    )
    monkeypatch.setattr(
        hook,
        "_run_pool_parity_headline_step",
        lambda p: pp_called.append(p),
    )
    hook.main()  # must not raise
    assert perf_called == [] and stale_called == [] and pp_called == []


def test_hook_runs_all_steps_on_main(monkeypatch):
    """On ``main`` the perf, staleness AND pool-parity-headline steps
    all run (independently, in order)."""
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
    monkeypatch.setattr(
        hook,
        "_run_pool_parity_headline_step",
        lambda p: calls.append(("pool", p)),
    )
    hook.main()
    assert calls == [
        ("perf", "/fake/py"),
        ("stale", "/fake/py"),
        ("pool", "/fake/py"),
    ]


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


def test_hook_pool_parity_step_no_venv_is_silent_skip(
    monkeypatch, capsys
):
    """Round-57: no venv → the pool-parity headline step prints a
    ``[pool-parity hook]`` skip note and returns (never raises, never
    blocks — same contract as the perf + staleness steps)."""
    hook = _load_hook()
    hook._run_pool_parity_headline_step(None)
    err = capsys.readouterr().err
    assert "[pool-parity hook]" in err and "no .venv" in err


def test_hook_pool_parity_step_reports_without_blocking(
    monkeypatch, capsys
):
    """A non-zero pool-parity exit (a residue-consistency over-count)
    is echoed to stderr but the step returns normally — the hook never
    propagates it (the never-block contract, identical to the
    round-54/55 staleness rows)."""
    hook = _load_hook()

    class _Proc:
        returncode = 1
        stdout = (
            "[pool-parity] 295/475 EoE cards (62.1%) byte-equal "
            "... ⚠ 2 residue-consistency violation(s)\n"
        )
        stderr = ""

    monkeypatch.setattr(
        hook.subprocess, "run", lambda *a, **k: _Proc()
    )
    assert hook.POOL_PARITY_SCRIPT.exists()
    hook._run_pool_parity_headline_step("/fake/py")  # must not raise
    err = capsys.readouterr().err
    assert "[pool-parity]" in err and "byte-equal" in err


def test_hook_pool_parity_step_swallows_exceptions(
    monkeypatch, capsys
):
    """Belt-and-suspenders: if the subprocess call itself raises, the
    pool-parity step swallows it with a ``[pool-parity hook]`` note so
    the commit always succeeds (never-block contract)."""
    hook = _load_hook()

    def _boom(*a, **k):
        raise OSError("kaboom")

    monkeypatch.setattr(hook.subprocess, "run", _boom)
    assert hook.POOL_PARITY_SCRIPT.exists()
    hook._run_pool_parity_headline_step("/fake/py")  # must not raise
    err = capsys.readouterr().err
    assert "[pool-parity hook] step raised, ignoring" in err


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
