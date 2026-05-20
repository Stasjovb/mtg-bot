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


# ----------------------- HONEST-MEASUREMENT-TOOLING fix: the dedicated
# ``tests/test_probe_covered_unprobed_*.py`` batch modules are now
# credited at the SAME bar as the smoke-file probes (the cycle-4 flag
# resolution). The integrity guard cuts BOTH ways: genuinely-probed
# batch cards ARE counted; a synthetic non-probe binding is NOT.


def test_probe_modules_credited_and_apostrophe_names_not_undercounted(
    mod,
):
    """The four dedicated batch probe modules' genuine real-EoE
    ``*_parity`` cards are credited PROBED — including the
    apostrophe-name cards (``Sami's Curiosity`` / ``Faller's
    Faithful`` / ``Mm'menon, Uthros Exile``) a function-name-slug
    match would silently UNDERCOUNT (the precise measurement bug this
    fix closes). Each named card is verified to be a live pool printing
    so the assertion can't pass on a stale fixture."""
    from mtg_bot.cards.parser.source import OracleParserCardSource

    pool = set(OracleParserCardSource().get_printings().keys())
    smoke_only = mod._smoke_probed_cards(pool, SMOKE_TEST)
    union = mod.genuine_probed_cards(pool)
    net_new = union - smoke_only
    # The fix MUST add the batch modules' genuine cards (the
    # understatement the cycle-4 flag tracked) — a healthy lower bound
    # so a regression that silently stops scanning a module fails here.
    assert len(net_new) >= 25, (
        f"expected the batch modules to add >=25 net-new genuine "
        f"PROBED cards; got {len(net_new)} — the probe-module scan "
        f"regressed (cycle-4 honest-measurement-tooling fix)"
    )
    # The apostrophe-name cards the slug rule truncates at the embedded
    # quote MUST be credited via the genuine-binding detector.
    for nm in (
        "Sami's Curiosity",
        "Faller's Faithful",
        "Mm'menon, Uthros Exile",
    ):
        assert nm in pool, f"{nm!r} drifted out of the live pool — re-pin"
        assert nm in union, (
            f"{nm!r} is genuinely real-EoE probed in a batch module "
            f"but NOT credited — the apostrophe-name undercount the "
            f"genuine-binding detector exists to fix has regressed"
        )
    # And a clean spot-check from each batch module (the idiom is
    # uniform; pin one representative per file).
    for nm in (
        "Embrace Oblivion",      # batch A
        "Gravpack Monoist",      # batch B
        "Gravkill",              # batch C
        "Divert Disaster",       # batch D
        "Lost in Space",         # batch E
    ):
        assert nm in union, f"{nm!r} batch probe not credited PROBED"


def test_probe_module_synthetic_nonprobe_is_not_counted(
    mod, tmp_path
):
    """**The integrity guard (the metric's teeth cut BOTH ways).** A
    function in a probe module that does NOT meet the bar must NOT be
    credited:

      * a ``*_parity`` function that binds a name which is NOT a live
        pool card (a synthetic stub / typo) — NOT counted;
      * a non-``_parity`` function (``*_divergence_pin`` — pins a KNOWN
        divergence, the opposite of byte-equality) — NOT counted even
        though it binds a real pool card;
      * a real-pool ``get_printings()`` binding OUTSIDE any
        ``*_parity`` function body (module-level / a helper) — NOT
        counted.

    Only a genuine ``*_parity`` function binding a real pool card is
    credited — the SAME bar the 60 smoke-file PROBED cards meet."""
    fake_mod = tmp_path / "test_probe_fake.py"
    fake_mod.write_text(
        # (1) genuine *_parity binding a REAL pool card -> CREDITED.
        "def test_cross_engine_real_eoe_real_card_x_parity():\n"
        '    real = get_active_source().get_printings().get("Honor")\n'
        "    assert real\n"
        # (2) *_parity binding a SYNTHETIC (non-pool) name -> NOT.
        "def test_cross_engine_real_eoe_fake_y_parity():\n"
        '    s = get_printings().get("Totally Synthetic Stub")\n'
        "    assert s\n"
        # (3) *_divergence_pin binding a real pool card -> NOT.
        "def test_cross_engine_real_eoe_divpin_z_divergence_pin():\n"
        '    r = get_printings().get("Bombard")\n'
        "    assert r\n"
        # (4) real-pool binding OUTSIDE any *_parity fn -> NOT.
        '_MODULE_LEVEL = get_printings().get("Gravkill")\n'
        "def _helper():\n"
        '    return get_printings().get("Plasma Bolt")\n',
        encoding="utf-8",
    )
    pool = {
        "Honor",
        "Bombard",
        "Gravkill",
        "Plasma Bolt",
        # NB: "Totally Synthetic Stub" is intentionally NOT in the pool.
    }
    got = mod._probe_module_probed_cards(pool, fake_mod)
    assert got == {"Honor"}, (
        f"only the genuine *_parity probe of a REAL pool card may be "
        f"credited; got {sorted(got)} (synthetic stub / divergence_pin "
        f"/ out-of-fn binding must all be excluded — the integrity "
        f"guard)"
    )
    # Defensive: a missing module path yields the empty set, never an
    # error (mirrors the smoke detector's never-block contract).
    assert mod._probe_module_probed_cards(
        pool, tmp_path / "does_not_exist.py"
    ) == set()


def test_genuine_probed_cards_union_is_superset_of_smoke_only(mod):
    """The union detector can only ADD cards (set union) — it must
    never DROP a card the original smoke-only rule credited (the 60
    pre-fix PROBED cards are byte-for-byte preserved; the headline
    byte-equal total is unchanged because the net-new cards merely move
    from covered-by-construction to the stronger PROBED tier)."""
    from mtg_bot.cards.parser.source import OracleParserCardSource

    pool = set(OracleParserCardSource().get_printings().keys())
    smoke_only = mod._smoke_probed_cards(pool, SMOKE_TEST)
    union = mod.genuine_probed_cards(pool)
    assert smoke_only <= union, (
        "the union detector dropped a smoke-only PROBED card — it must "
        "be strictly additive"
    )


# ------------------- CYCLE-10 honest-attribution reconciliation: the
# Tier-C target-seating lever-a cards (Sunset Saboteur / Exosuit
# Savior) each carry a GENUINE real-EoE cross-engine byte-equal
# firing-parity probe in ``tests/test_parity_smoke.py``. Their function
# names were renamed to the established ``..._parity`` convention so the
# UNCHANGED single inclusion predicate credits them at EXACTLY the
# established bar (covered-by-construction → the stronger PROBED tier).
# The integrity guard cuts BOTH ways — these genuine probes ARE
# counted; a synthetic non-bar Tier-C-shaped probe is NOT.


def test_tierc_target_seating_cards_credited_probed(mod):
    """The two Tier-C target-seating cards (Sunset Saboteur / Exosuit
    Savior) are credited PROBED via the genuine real-EoE
    cross-engine byte-equal probes in ``tests/test_parity_smoke.py``
    (the cycle-10 honest-attribution reconciliation: their probe
    functions were renamed to the established ``..._parity`` convention
    so the unchanged smoke detector credits them).

    Each card is verified to be a live pool printing so the assertion
    cannot pass on a stale fixture, and is asserted to land in the
    PROBED tier of the full classification (NOT merely
    covered-by-construction) — pins the +2 the reconciliation surfaces
    (PROBED 104 → 106) and fails directly if a future rebase reverts
    the naming convention."""
    from mtg_bot.cards.parser.source import OracleParserCardSource

    pool = set(OracleParserCardSource().get_printings().keys())
    union = mod.genuine_probed_cards(pool)
    for nm in ("Sunset Saboteur", "Exosuit Savior"):
        assert nm in pool, f"{nm!r} drifted out of the live pool — re-pin"
        assert nm in union, (
            f"{nm!r} has a genuine real-EoE cross-engine byte-equal "
            f"firing-parity probe in tests/test_parity_smoke.py but is "
            f"NOT credited PROBED — the cycle-10 honest-attribution "
            f"reconciliation (the ``..._parity`` rename) has regressed"
        )
    # And the full classification places them in the PROBED tier (not
    # covered-by-construction) — neither is a residue BLOCKED entry, so
    # the strongest-evidence tier wins.
    res = mod.classify_pool()
    probed = set(res.tiers[mod.TIER_PROBED])
    for nm in ("Sunset Saboteur", "Exosuit Savior"):
        assert nm in probed, (
            f"{nm!r} must classify into the PROBED tier (genuine "
            f"real-EoE probe); got "
            f"{[k for k, v in res.tiers.items() if nm in v]}"
        )


def test_tierc_synthetic_nonbar_probe_is_not_counted(mod, tmp_path):
    """**The integrity guard (the bar cuts BOTH ways).** A
    Tier-C-shaped function that does NOT meet the established bar must
    NOT be credited, even though it binds a real pool card via the
    genuine ``get_printings().get(...)`` idiom:

      * a function whose name keeps the original Tier-C
        ``..._seats_first_...`` suffix (NOT renamed to ``..._parity``)
        — the unchanged single inclusion predicate must NOT credit it
        (this is precisely the undercount the cycle-10 reconciliation
        fixed by RENAMING, not by loosening the predicate — proving the
        bar was never weakened);
      * a ``*_divergence_pin`` Tier-C function (pins a KNOWN
        divergence, the opposite of byte-equality) — NOT counted.

    Only a genuine ``..._parity`` function binding a real pool card is
    credited — the SAME bar the smoke-file + batch-module PROBED cards
    meet. This asserts the reconciliation did not introduce a second,
    looser inclusion rule."""
    fake_mod = tmp_path / "test_probe_tierc_fake.py"
    fake_mod.write_text(
        # (1) genuine ..._parity binding a REAL pool card -> CREDITED.
        "def test_cross_engine_real_eoe_honor_seats_parity():\n"
        '    real = get_active_source().get_printings().get("Honor")\n'
        "    assert real\n"
        # (2) the ORIGINAL un-renamed Tier-C suffix binding a real pool
        # card -> NOT counted (the exact undercount the rename fixed;
        # proves the predicate itself was never loosened).
        "def test_cross_engine_real_eoe_bombard_attacks_seats_"
        "first_opponent_creature():\n"
        '    r = get_active_source().get_printings().get("Bombard")\n'
        "    assert r\n"
        # (3) a Tier-C *_divergence_pin binding a real pool card -> NOT.
        "def test_cross_engine_real_eoe_gravkill_seats_"
        "divergence_pin():\n"
        '    g = get_printings().get("Gravkill")\n'
        "    assert g\n",
        encoding="utf-8",
    )
    pool = {"Honor", "Bombard", "Gravkill"}
    got = mod._probe_module_probed_cards(pool, fake_mod)
    assert got == {"Honor"}, (
        f"only the genuine ..._parity probe of a REAL pool card may be "
        f"credited; got {sorted(got)} (the un-renamed Tier-C suffix and "
        f"the divergence_pin must both be excluded — the bar was not "
        f"loosened, the deviating probes were conformed to it)"
    )
    # The smoke detector (the actual path that credits Sunset Saboteur /
    # Exosuit Savior) enforces the SAME ``_parity``-suffix bar — a
    # ``..._seats_first_...`` name is invisible to it.
    smoke_pool = {"Bombard"}
    no_credit = mod._smoke_probed_cards(smoke_pool, fake_mod)
    assert "Bombard" not in no_credit, (
        "the smoke detector must NOT credit the un-renamed Tier-C "
        "suffix — the established bar is the ``_parity`` convention"
    )


# --------------------------------------------- residue worklist parsing


def test_residue_blocked_cards_split_and_normalised(mod):
    missing, non_effect = mod.residue_blocked_cards(RESIDUE_WORKLIST)
    # The honest residue (the load-bearing "how far from parity"
    # number). This named-set is a per-round snapshot the orchestrator
    # post-merge fold updates — pinning exact names is an intentional
    # tracked snapshot, NOT a brittle gate: the durable assertions are
    # the structural ones below (disjoint, no qualified names) which a
    # legitimate fold must never break. Round-60 fold: Perigee Beckoner
    # genuinely_missing -> closed (Effect-half shipped
    # `PumpTargetCreatureUntilEotGrantDiesReturnTapped` + genuine
    # probe; full card stays nested-trigger-grant/warp_cost gated).
    # Slice-16 fold: Astelli Reclaimer genuinely_missing -> closed
    # (Effect::AstelliReclaimerETBEffect shipped + bridge).
    # Slice-18 fold: Roving Actuator genuinely_missing -> closed
    # (Effect::RovingActuatorETBEffect { max_mv: u8 } shipped + bridge).
    # Slice-19 fold: Meltstrider's Resolve genuinely_missing -> closed
    # (Effect::EnchantedCreatureFightsTarget shipped + bridge; honest-stop
    # closure — full-card byte-equality stays gated on the Aura attach
    # substrate, but the Effect-level closure flips the residue tier).
    # Slice-20 fold: Command Bridge genuinely_missing -> closed
    # (Effect::SacrificeSelfUnlessTapPermanent + PendingDecision::
    # TapPermanentChoice cost-decision substrate + bridge shipped).
    # Slice-22 fold: Sothera, the Supervoid genuinely_missing -> closed
    # (Effect::SotheraDIESCreaturesEachOpponentControlsBattleLoseLife
    # + Effect::SotheraBeginningOfEndStepIfSurvivedCreaturesLoseLife
    # composite shipped + bridge + Sothera DIES probe at
    # ``tests/test_probe_sothera_requiem_downstream.py``).
    # `missing` is now 2 distinct genuine new-Rust-Effect asks
    # (Lightstall Inquisitor appears twice in the worklist; the set
    # dedupes it).
    assert missing == {
        "Lightstall Inquisitor",
        "Pain for All",
    }
    assert non_effect == {
        "Dauntless Scrapbot",
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
    # Round-58: the BLOCKED-subsystem tier is no longer one opaque
    # number — the per-subsystem breakout table + reconciliation must
    # render into the regenerated doc.
    assert "| Subsystem | #cards | 1gate | multi |" in text
    assert "**Reconciliation:**" in text
    assert "docs/SUBSYSTEM_ROADMAP.md" in text


# --------------------------- round-58: subsystem attribution breakout
#
# The scout owns the subsystem taxonomy ONCE; this metric + these tests
# import it (the same reuse discipline as ``measure_effect_coverage``'s
# parser). These tests pin: a card maps to its expected subsystem;
# multi-gated cards are handled; the per-subsystem counts reconcile
# with the old single ``subsystem-gated`` bucket AND the residue
# worklist.


@pytest.fixture(scope="module")
def scout():
    import importlib.util as _ilu

    sp = REPO_ROOT / "scripts" / "scout_r58_subsystem_attribution.py"
    spec = _ilu.spec_from_file_location("_scout_r58_under_test", sp)
    assert spec is not None and spec.loader is not None
    m = _ilu.module_from_spec(spec)
    sys.modules[spec.name] = m
    spec.loader.exec_module(m)
    return m


@pytest.fixture(scope="module")
def attr(scout):
    return scout.subsystem_attribution()


def test_attribution_total_reconciles_with_old_single_bucket(
    scout, attr, result, mod
):
    """The per-subsystem breakout must partition EXACTLY the same cards
    the opaque ``blocked_subsystem_gated`` tier reported (no card
    gained/lost in the itemisation) — the headline stays honest."""
    old_bucket = set(result.tiers[mod.TIER_BLOCKED_SUBSYSTEM])
    assert set(attr["cards"].keys()) == old_bucket
    assert attr["n_subsystem_gated"] == len(old_bucket)


def test_single_gate_counts_sum_to_single_gated_total(scout, attr):
    """Reconciliation invariant: every subsystem-gated card is either
    single-gated (credited to its ONE gate) or multi-gated; the
    per-subsystem ``single_gate`` lists sum to the single-gated total
    with no double-count, and every card carries >=1 gate."""
    n = attr["n_subsystem_gated"]
    n_single = sum(
        1 for c in attr["cards"].values() if not c["multi_gated"]
    )
    n_multi = n - n_single
    assert n_single + n_multi == n
    summed = sum(len(v) for v in attr["single_gate"].values())
    assert summed == n_single
    # Single-gate lists are disjoint (a single-gated card has exactly
    # one owning subsystem).
    seen: set[str] = set()
    for names in attr["single_gate"].values():
        for nm in names:
            assert nm not in seen, f"{nm} double-counted single-gate"
            seen.add(nm)
    # Every card has at least one gate; a multi-gated card has >=2.
    for nm, cd in attr["cards"].items():
        assert len(cd["gates"]) >= 1
        if cd["multi_gated"]:
            assert len(cd["gates"]) >= 2
            assert cd["last_mile"] is None
        else:
            assert len(cd["gates"]) == 1
            assert cd["last_mile"] == cd["gates"][0]


def test_known_card_subsystem_attribution(scout, attr):
    """A card maps to the expected gating subsystem. Non-basic lands
    are single-gated on the non-basic-land substrate; a warp creature
    trips the warp gate; the honest unclassified residual is the two
    documented rule-static enchantments."""
    cards = attr["cards"]
    # Breeding Pool: zero-Effect non-basic dual land — single-gated on
    # the non-basic-land substrate.
    bp = cards["Breeding Pool"]
    assert bp["gates"] == [scout.SUB_NONBASIC_LAND]
    assert bp["last_mile"] == scout.SUB_NONBASIC_LAND
    assert bp["multi_gated"] is False
    # Bygone Colossus: warp_cost-gated.
    assert scout.SUB_WARP in cards["Bygone Colossus"]["gates"]
    # The honest unclassified bucket is exactly the two documented
    # rule-static enchantments (no force-guess).
    unclass = set(attr["by_subsystem"].get(scout.SUB_UNCLASSIFIED, []))
    assert unclass == {"Deafening Silence", "Leyline of Mutation"}
    for u in unclass:
        assert cards[u]["gates"] == [scout.SUB_UNCLASSIFIED]


def test_multi_gated_card_recorded_under_every_gate(scout, attr):
    """A multi-gated card appears under EVERY gate it trips in
    ``by_subsystem`` and under NO subsystem's ``single_gate`` list."""
    multi = [
        nm for nm, c in attr["cards"].items() if c["multi_gated"]
    ]
    assert multi, "expected at least one multi-gated card"
    for nm in multi:
        gates = attr["cards"][nm]["gates"]
        assert len(gates) >= 2
        for g in gates:
            assert nm in attr["by_subsystem"][g]
        for sg_names in attr["single_gate"].values():
            assert nm not in sg_names


def test_residue_blocked_non_effect_not_in_subsystem_breakout(
    scout, attr, mod
):
    """Cross-check vs the residue worklist: the 3 ``blocked_non_effect``
    cards are in their OWN residue tier, NOT the subsystem-gated tier,
    so they must be absent from the subsystem attribution set — the
    breakout never double-counts a residue card. Their
    ``non_effect_blocker`` subsystems (BECOMES_TAPPED / Aura) must
    nonetheless be expressible keys in the taxonomy (consistency of
    the named-subsystem vocabulary with the residue worklist)."""
    _, non_effect = mod.residue_blocked_cards(RESIDUE_WORKLIST)
    for card in non_effect:
        assert card not in attr["cards"], (
            f"{card!r} is residue blocked_non_effect but leaked into "
            f"the subsystem-gated breakout"
        )
    # The residue non_effect_blocker vocabulary (BECOMES_TAPPED, Aura)
    # must be representable in the taxonomy.
    assert scout.SUB_BECOMES_TAPPED in scout._SUB_LABEL
    assert scout.SUB_AURA in scout._SUB_LABEL


def test_leverage_table_sorted_and_complete(scout, attr):
    """Every occurring subsystem has a leverage row with a label,
    tractability bucket and (possibly zero) deck-count; the table is
    tractability-then-single-gate sorted (contained first)."""
    dc = {n: 0 for n in attr["cards"]}  # zero deck pool is fine here
    rows = scout.leverage_table(attr, dc)
    assert {r["subsystem"] for r in rows} == set(attr["order"])
    for r in rows:
        assert r["label"]
        assert r["tractability"] in (
            scout.TRACT_CONTAINED,
            scout.TRACT_MEDIUM,
            scout.TRACT_SPRAWLING,
            scout.TRACT_DIFFUSE,
        )
        assert r["n_cards"] == r["n_single_gate"] + r["n_multi_gated"]
    tract_rank = {
        scout.TRACT_CONTAINED: 0,
        scout.TRACT_MEDIUM: 1,
        scout.TRACT_SPRAWLING: 2,
        scout.TRACT_DIFFUSE: 3,
    }
    ranks = [tract_rank[r["tractability"]] for r in rows]
    assert ranks == sorted(ranks)
