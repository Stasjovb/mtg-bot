"""Tests for ``scripts/measure_pool_parity.py`` — the measured,
regenerable pool-level cross-engine parity metric.

Covers (per the round-57 task brief):

  * **Tier classification happy path** — every pool printing lands in
    exactly one tier; the headline arithmetic (PROBED + covered =
    byte-equal; tiers sum to the pool size) holds; the strict
    precedence order is respected on synthetic inputs.
  * **A BLOCKED card is not miscounted as covered** — a residue
    ``genuinely_missing`` card is hard-pinned to the BLOCKED-missing
    tier even when the class-granularity heuristic / probe-name match
    would have called it covered/probed (the metric never overstates).
  * **The residue-worklist consistency check** — every distinct
    ``genuinely_missing`` / ``blocked_non_effect`` card from
    ``docs/residue_worklist.json`` resolves to a real pool name and
    lands in its matching BLOCKED tier; no such card is ever counted
    in PROBED or covered-by-construction.
  * **Regeneration determinism** — two back-to-back ``classify_pool``
    runs (and two ``render_markdown`` renders) are byte-identical, and
    ``main()`` writes the doc with the auto-generated header (the
    ``measure_effect_coverage`` idiom).

The pure parsers (``_slug``, ``genuine_probed_cards``,
``residue_blocked_cards``) need no engine extension; the full
``classify_pool`` walks the real EoE pool (parser-only, no ``.pyd``)
exactly like ``measure_effect_coverage``.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "measure_pool_parity.py"
DOC_PATH = REPO_ROOT / "docs" / "POOL_PARITY.md"
RESIDUE_WORKLIST = REPO_ROOT / "docs" / "residue_worklist.json"
SMOKE_TEST = REPO_ROOT / "tests" / "test_parity_smoke.py"


def _load_script():
    """Import the script under a stable name without invoking
    ``main()`` (same pattern as ``test_effect_coverage`` /
    ``test_check_audit_coverage_staleness``)."""
    spec = importlib.util.spec_from_file_location(
        "_measure_pool_parity_under_test", SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def mod():
    return _load_script()


@pytest.fixture(scope="module")
def result(mod):
    """One real classification of the live EoE pool, shared across the
    happy-path / consistency tests (the walk is the slow part)."""
    return mod.classify_pool()


# --------------------------------------------------------- pure helpers


def test_slug_normalises_and_keys_split_cards_on_left_face(mod):
    assert mod._slug("Mechan Assembler") == "mechan_assembler"
    assert mod._slug("Alpharael, Dreaming Acolyte") == (
        "alpharael_dreaming_acolyte"
    )
    # Split / room cards key on the LEFT face — that's how the probe
    # function names spell them.
    assert mod._slug("Roaring Furnace // Steaming Sauna") == (
        "roaring_furnace"
    )
    assert mod._slug("  Trailing Space  ") == "trailing_space"


def test_card_effect_classes_empty_for_vanilla(mod):
    class _Vanilla:
        name = "Vanilla Bear"
        spell_effect = None
        triggered_abilities = ()
        activated_abilities = ()
        static_abilities = ()

    assert mod.card_effect_classes(_Vanilla()) == set()


def test_card_effect_classes_walks_spell_and_triggers(mod):
    class _Eff:
        def resolve(self, *a, **k):  # noqa: D401 - duck-typed Effect
            pass

        def describe(self):
            return "x"

    class _WithEffects:
        name = "Effecty"
        spell_effect = _Eff()
        triggered_abilities = ()
        activated_abilities = ()
        static_abilities = ()

    assert mod.card_effect_classes(_WithEffects()) == {"_Eff"}


def test_card_effect_classes_swallows_broken_introspection(mod):
    """A card the walker can't introspect contributes no classes (it
    then falls to a BLOCKED tier — never spuriously 'covered'). Mirrors
    the coverage walker's defensive contract."""

    class _Boom:
        name = "Boom"

        @property
        def spell_effect(self):
            raise RuntimeError("intentional")

        triggered_abilities = ()
        activated_abilities = ()
        static_abilities = ()

    assert mod.card_effect_classes(_Boom()) == set()


# ------------------------------------------------- genuine-probe parser


def test_genuine_probed_cards_only_parity_fns(mod, tmp_path):
    """``*_parity`` functions count; ``*_divergence_pin`` (a KNOWN
    divergence — the opposite of byte-equality) must NOT, and the slug
    match is longest-first so a prefix card can't steal attribution."""
    fake = tmp_path / "fake_smoke.py"
    fake.write_text(
        "def test_cross_engine_real_eoe_mechan_assembler_x_parity():\n"
        "    pass\n"
        "def test_cross_engine_real_eoe_mechan_x_parity():\n"
        "    pass\n"
        "def test_cross_engine_real_eoe_pinnacle_kill_ship_y"
        "_divergence_pin():\n"
        "    pass\n",
        encoding="utf-8",
    )
    pool = {"Mechan Assembler", "Mechan", "Pinnacle Kill-Ship"}
    probed = mod.genuine_probed_cards(pool, smoke_path=fake)
    assert "Mechan Assembler" in probed
    assert "Mechan" in probed  # the bare-`mechan` *_parity fn
    # divergence_pin must NOT promote Pinnacle Kill-Ship.
    assert "Pinnacle Kill-Ship" not in probed


def test_genuine_probed_cards_real_inventory_nonempty(mod):
    """Structural-regression guard: the real smoke file must yield a
    healthy genuine-probe inventory (if the probe naming convention or
    the file moves and breaks the parser this fails directly, like
    ``test_effect_coverage``'s extractor sanity test)."""
    from mtg_bot.cards.parser.source import OracleParserCardSource

    pool = set(OracleParserCardSource().get_printings().keys())
    probed = mod.genuine_probed_cards(pool, smoke_path=SMOKE_TEST)
    assert len(probed) >= 40, (
        f"expected >=40 genuine real-EoE *_parity probed cards, got "
        f"{len(probed)} — probe naming convention may have drifted"
    )
    # Every probed name must be a real pool card (the slug match keys
    # against the pool, so this is guaranteed — assert it anyway as the
    # contract).
    assert probed <= pool


# --------------------------------------------- residue worklist parsing


def test_residue_blocked_cards_split_and_normalised(mod):
    missing, non_effect = mod.residue_blocked_cards(RESIDUE_WORKLIST)
    # The honest residue, settled at round-57 (the load-bearing "how
    # far from parity" number). This named-set is a per-round snapshot
    # the orchestrator post-merge fold updates — pinning exact names is
    # an intentional tracked snapshot, NOT a brittle gate: the durable
    # assertions are the structural ones below (disjoint, no qualified
    # names) which a legitimate fold must never break. Round-57 fold:
    # Faller's Faithful -> closed (Effect shipped + genuine probe);
    # Tractor Beam -> blocked_non_effect (only the shipped bare
    # TapEnchantedPermanent is emitted; control-swap is the Aura
    # subsystem, not a probe-droppable Effect).
    assert missing == {
        "Astelli Reclaimer",
        "Command Bridge",
        "Lightstall Inquisitor",
        "Meltstrider's Resolve",
        "Pain for All",
        "Perigee Beckoner",
        "Roving Actuator",
    }
    assert non_effect == {
        "Dauntless Scrapbot",
        "Seedship Agrarian",
        "Tractor Beam",
    }
    # Durable structural invariants (hold every round regardless of
    # which card is in which bucket):
    # - a card cannot be both genuinely_missing and blocked_non_effect
    assert missing.isdisjoint(non_effect)
    # - the parenthetical-strip (e.g. "Monoist Circuit-Feeder (legacy
    #   duplicate row)" is `closed`) never leaks a qualified name into
    #   either blocked set.
    assert not any("(" in c for c in missing | non_effect)


def test_residue_worklist_missing_file_raises(mod, tmp_path):
    with pytest.raises(RuntimeError, match="missing"):
        mod.residue_blocked_cards(tmp_path / "nope.json")


# ------------------------------------------------- classification happy


def test_every_card_in_exactly_one_tier(mod, result):
    """Tier classification happy path: the tiers partition the pool —
    every printing lands in exactly one tier and the counts sum to the
    pool size."""
    total = sum(result.counts().values())
    assert total == result.n_pool
    # No card appears in two tiers.
    seen: set[str] = set()
    for names in result.tiers.values():
        for nm in names:
            assert nm not in seen, f"{nm} double-counted across tiers"
            seen.add(nm)
    assert len(seen) == result.n_pool


def test_headline_arithmetic_is_sane(mod, result):
    c = result.counts()
    n = result.n_pool
    assert n > 0
    byte_equal = c[mod.TIER_PROBED] + c[mod.TIER_COVERED]
    assert 0 <= byte_equal <= n
    assert 0 <= c[mod.TIER_PROBED] <= byte_equal
    # The blocked tiers + the covered/probed/admitted tiers cover the
    # whole pool with no remainder.
    assert (
        byte_equal
        + c[mod.TIER_ADMITTED]
        + c[mod.TIER_BLOCKED_MISSING]
        + c[mod.TIER_BLOCKED_NON_EFFECT]
        + c[mod.TIER_BLOCKED_SUBSYSTEM]
        == n
    )


def test_headline_line_states_the_caveat(mod, result):
    line = mod.headline_line(result)
    assert "byte-equal at the Effect+bridge level" in line
    assert "NOT full-game-trajectory parity" in line
    assert f"/{result.n_pool}" in line


# ------------------------------- a BLOCKED card is NOT miscounted as covered


def test_genuinely_missing_cards_are_pinned_blocked_not_covered(
    mod, result
):
    """The load-bearing invariant: every residue ``genuinely_missing``
    distinct card lands in the BLOCKED-missing tier and is ABSENT from
    PROBED + covered-by-construction — the metric never overstates
    parity by class-granularity false-positives."""
    missing, _ = mod.residue_blocked_cards(RESIDUE_WORKLIST)
    blocked_missing = set(result.tiers[mod.TIER_BLOCKED_MISSING])
    probed = set(result.tiers[mod.TIER_PROBED])
    covered = set(result.tiers[mod.TIER_COVERED])
    for card in missing:
        assert card in blocked_missing, (
            f"{card!r} is residue genuinely_missing but not in the "
            f"BLOCKED-missing tier"
        )
        assert card not in probed, (
            f"{card!r} is residue genuinely_missing but counted PROBED "
            f"— that overstates parity"
        )
        assert card not in covered, (
            f"{card!r} is residue genuinely_missing but counted "
            f"covered-by-construction — that overstates parity"
        )


def test_blocked_non_effect_cards_pinned_blocked_not_byte_equal(
    mod, result
):
    """A ``blocked_non_effect`` card's Effects may legitimately be
    covered/probed (that is its definition) but the CARD must still be
    counted BLOCKED (full-card parity is what's gated) — never in a
    byte-equal tier."""
    _, non_effect = mod.residue_blocked_cards(RESIDUE_WORKLIST)
    bne_tier = set(result.tiers[mod.TIER_BLOCKED_NON_EFFECT])
    probed = set(result.tiers[mod.TIER_PROBED])
    covered = set(result.tiers[mod.TIER_COVERED])
    for card in non_effect:
        assert card in bne_tier
        assert card not in probed
        assert card not in covered


def test_synthetic_precedence_genuinely_missing_beats_probe(
    mod, monkeypatch
):
    """Synthetic-input precedence check: a card that is BOTH genuinely
    probed AND a residue ``genuinely_missing`` entry is pinned BLOCKED
    (the worklist is the authority) and recorded as a
    consistency-violation, NOT promoted to PROBED."""

    class _Eff:
        def resolve(self, *a, **k):
            pass

        def describe(self):
            return "x"

    class _P:
        def __init__(self, name, eff=None):
            self.name = name
            self.spell_effect = eff
            self.triggered_abilities = ()
            self.activated_abilities = ()
            self.static_abilities = ()

    fake_pool = {
        "Genuine Probed Covered": _P("Genuine Probed Covered", _Eff()),
        "Residue Missing Probed": _P("Residue Missing Probed", _Eff()),
        "Plain Vanilla": _P("Plain Vanilla", None),
    }

    class _Src:
        def get_printings(self):
            return fake_pool

    import mtg_bot.cards.parser.source as src_mod

    monkeypatch.setattr(
        src_mod, "OracleParserCardSource", lambda: _Src()
    )
    # Both synthetic effect-bearing cards' effect class is "_Eff" —
    # mark it covered. Probe both effect-bearing cards. Mark the
    # second one residue genuinely_missing.
    monkeypatch.setattr(
        mod, "covered_python_class_set", lambda: {"_Eff"}
    )
    monkeypatch.setattr(
        mod,
        "genuine_probed_cards",
        lambda names: {
            "Genuine Probed Covered",
            "Residue Missing Probed",
        },
    )
    monkeypatch.setattr(
        mod,
        "residue_blocked_cards",
        lambda: ({"Residue Missing Probed"}, set()),
    )
    # Vanilla card is loader-admitted so it reaches a covered tier.
    monkeypatch.setattr(mod, "loader_admits", lambda p: True)

    res = mod.classify_pool()
    assert "Genuine Probed Covered" in res.tiers[mod.TIER_PROBED]
    # The residue genuinely_missing card is BLOCKED, NOT probed.
    assert "Residue Missing Probed" in res.tiers[
        mod.TIER_BLOCKED_MISSING
    ]
    assert "Residue Missing Probed" not in res.tiers[mod.TIER_PROBED]
    # And the class-heuristic disagreement is surfaced as a violation.
    assert (
        "Residue Missing Probed",
        mod.TIER_PROBED,
    ) in res.consistency_violations
    # The vanilla loader-admitted 0-effect card is covered.
    assert "Plain Vanilla" in res.tiers[mod.TIER_COVERED]


# ----------------------------------------- residue consistency cross-check


def test_residue_consistency_cross_check_clean_on_live_tree(
    mod, result
):
    """The cross-check's contract: violations are ONLY genuinely_missing
    cards the class heuristic would have over-counted (pinned BLOCKED
    regardless). On the live tree the only such cards are the documented
    class-granularity-rider cases (Faller's Faithful / Tractor Beam) —
    assert the violation set is a SUBSET of the genuinely_missing set
    (never a covered/probed card leaking the other way) and the
    blocked_non_effect 'context' rows are NOT counted as violations."""
    missing, non_effect = mod.residue_blocked_cards(RESIDUE_WORKLIST)
    violation_cards = {c for c, _ in result.consistency_violations}
    # Every violation is a genuinely_missing card (never a leak the
    # other way).
    assert violation_cards <= missing
    # blocked_non_effect cards are surfaced as context, never as
    # violations.
    bne_context_cards = {
        c for c, _ in result.blocked_non_effect_with_covered_effects
    }
    assert bne_context_cards <= non_effect
    assert violation_cards.isdisjoint(bne_context_cards)


# ---------------------------------------------- regeneration determinism


def test_classify_pool_is_deterministic(mod):
    r1 = mod.classify_pool()
    r2 = mod.classify_pool()
    assert r1.counts() == r2.counts()
    assert r1.tiers == r2.tiers
    assert r1.consistency_violations == r2.consistency_violations
    assert (
        r1.blocked_non_effect_with_covered_effects
        == r2.blocked_non_effect_with_covered_effects
    )


def test_render_markdown_is_deterministic(mod, result):
    md1 = mod.render_markdown(result)
    md2 = mod.render_markdown(result)
    assert md1 == md2
    assert md1.startswith(
        "Generated by `scripts/measure_pool_parity.py`"
    )
    assert "## Headline" in md1
    assert "CAVEAT — what this measures vs. what it does NOT" in md1


def test_main_writes_doc_with_generated_header(mod):
    """``main()`` runs end-to-end and (re)writes the target doc with
    the auto-generated header — the ``measure_effect_coverage`` idiom
    (the doc IS regenerable; the script writes it)."""
    rc = mod.main()
    assert rc in (0, 1)  # 1 iff a genuinely_missing false-positive
    assert DOC_PATH.exists()
    text = DOC_PATH.read_text(encoding="utf-8")
    assert text.startswith(
        "Generated by `scripts/measure_pool_parity.py`"
    )
    assert "# Pool-level cross-engine parity metric" in text
    # The headline must carry an X / N (Y%) byte-equal claim.
    assert re.search(
        r"\*\*\d+ / \d+ EoE cards \([\d.]+%\) are byte-equal at the "
        r"Effect\+bridge level\*\*",
        text,
    )
