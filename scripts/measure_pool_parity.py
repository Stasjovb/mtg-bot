"""Measured, regenerable POOL-LEVEL cross-engine parity metric.

The campaign has long answered "how far from parity?" with PROXIES:

  * per-*emission* Rust Effect coverage (``docs/RUST_EFFECT_COVERAGE.md``,
    ``scripts/measure_effect_coverage.py``) — weighted by how many
    cards each Effect class appears on, NOT a per-card classification;
  * the honest residue count (``docs/residue_worklist.json``) — the
    distinct genuinely-Rust-blocked cards, but only the blocked tail;
  * "0 FAIL_DIVERGENCE over the bridge-admitted bench subset"
    (``docs/bench_trajectory_parity_smoke.md``) — an empirical signal
    over whatever the loader admits, not a tracked pool fraction.

None of those is a single authoritative, tracked, *measured* number
for "what fraction of the EoE card pool is byte-equal cross-engine".
This script is that metric. It classifies **every** card in the EoE
pool (the same pool ``measure_effect_coverage`` walks) into honest,
precisely-defined tiers and reports the counts + percentages, then
writes ``docs/POOL_PARITY.md`` (auto-overwritten on each run) and
prints the same markdown to stdout — the same idiom as
``measure_effect_coverage.py``.

WHAT THIS MEASURES (and what it does NOT)
-----------------------------------------
This metric measures **Effect+bridge-level byte-equality evidence**,
NOT full-game-trajectory parity. The strongest tier (PROBED) has a
genuine real-EoE cross-engine probe asserting byte-equality on a
controlled state; the next tier (covered-by-construction) only proves
every Effect the card emits has a live Rust variant + bridge arm — it
does NOT prove the card is byte-equal in a real multi-turn game. The
bench tier is the empirical full-trajectory signal but is capped at
~22-25 turns and only over the loader-admitted subset. **No tier here
claims "byte-equal in real full-game trajectories for the whole
pool"** — that is explicitly out of scope and stated as a caveat in
the generated doc. Honest discipline: the headline reports the
modest, defensible number, not a flattering one.

Run with::

    PYTHONPATH=src \\
    ../../mtg-bot/.venv-py313/Scripts/python.exe \\
    scripts/measure_pool_parity.py

This script does not depend on the Rust extension being built — it
reuses ``measure_effect_coverage``'s pure-text ``cards.rs`` parser and
its EoE-pool walker (``collect_python_effect_vocab`` /
``collect_rust_effect_variants`` — the parse rule is NOT duplicated
here) plus the pure-Python ``parity.trajectory`` admit predicates and
a text scan of ``tests/test_parity_smoke.py``. The companion test
``tests/test_measure_pool_parity.py`` exercises the classifier.

TIER DEFINITIONS (precise)
--------------------------
Each EoE printing lands in EXACTLY ONE tier, evaluated in this
strict precedence order (strongest evidence wins):

1. **PROBED byte-equal** — a genuine real-EoE cross-engine probe in
   ``tests/test_parity_smoke.py`` (a ``test_cross_engine_real_eoe_
   <slug>_parity`` function whose name-prefix is the snake_case slug
   of this card's printed name — split cards keyed on the left face)
   asserts byte-equality for THIS card. Strongest evidence: a real
   pool printing pinned end-to-end on both engines on a controlled
   state. (Still a controlled-state probe, NOT a full random game —
   see the caveat above.)

2. **Effect+bridge covered (not individually probed)** — every
   distinct Python ``Effect`` class this card emits (walked with
   ``measure_effect_coverage``'s exact walker) has a live Rust
   ``Effect::`` variant + a wired bridge arm (i.e. is in the coverage
   script's covered-class set), AND the card is NOT a BLOCKED entry
   in ``docs/residue_worklist.json``. Covered-by-construction: the
   primitives all exist + bridge, but no genuine probe pins THIS
   card, so it is weaker evidence than PROBED. A card with zero
   Effects (pure vanilla / keyword-only) counts here only if it is
   also loader-admitted (otherwise it cannot be cross-engine
   exercised at all and falls to the relevant lower tier).

3. **bridge-admitted & bench-exercised** — the production-deck
   loader admits this printing (it passes
   ``trajectory._printing_is_bridge_basic_land`` or
   ``trajectory._printing_is_bridge_simple_creature`` — the exact
   admit gate the bench corpus runs through) and the bench has run
   it 0-divergence at scale. CAVEAT: the bench caps at ~22-25 turns
   (``docs/bench_trajectory_parity_smoke.md``), so this is a
   bounded-depth empirical signal, not a game-end guarantee.

4. **BLOCKED** — not byte-equal-covered today. Broken out into:
   * ``blocked_genuinely_missing`` — a residue worklist
     ``genuinely_missing`` entry: a TRUE new-Rust-Effect ask (the
     load-bearing "how far from parity" gap).
   * ``blocked_non_effect`` — a residue worklist
     ``blocked_non_effect`` entry: the card's Effects ARE shipped;
     it is gated by a non-Effect path (unbridged event / declined
     cost-mechanic / unmodeled subsystem / token-registration
     substrate).
   * ``blocked_subsystem_gated`` — NOT in the residue worklist as
     blocked, NOT probed, NOT covered-by-construction, NOT
     loader-admitted: the card emits at least one Effect with no
     covered Rust counterpart, OR is loader-rejected by a subsystem
     gate (Station / Ward / Devour / warp / Aura / Rooms /
     BECOMES_TAPPED / dynamic-P/T / activated+static abilities /
     planeswalker / …). The long, un-itemised blocked tail.

INTERNAL-CONSISTENCY CROSS-CHECK
--------------------------------
A card listed BLOCKED (``genuinely_missing`` or
``blocked_non_effect``) in ``docs/residue_worklist.json`` must NOT be
counted in PROBED or covered-by-construction. The script asserts this
and emits a ``WARNING`` line into the doc + a non-zero structural
flag (the companion test pins it) if a residue-blocked card ever
sneaks into a covered tier — exactly the residue-vs-headline drift
class the round-54/55/56 cron guards, applied to THIS metric.
"""

from __future__ import annotations

import io
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
else:  # pragma: no cover
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
OUTPUT_DOC = REPO_ROOT / "docs" / "POOL_PARITY.md"
SMOKE_TEST = REPO_ROOT / "tests" / "test_parity_smoke.py"
RESIDUE_WORKLIST = REPO_ROOT / "docs" / "residue_worklist.json"

# Tier keys (stable — the doc + test reference these verbatim).
TIER_PROBED = "probed"
TIER_COVERED = "covered_by_construction"
TIER_ADMITTED = "bridge_admitted_bench_exercised"
TIER_BLOCKED_MISSING = "blocked_genuinely_missing"
TIER_BLOCKED_NON_EFFECT = "blocked_non_effect"
TIER_BLOCKED_SUBSYSTEM = "blocked_subsystem_gated"

_TIER_ORDER = (
    TIER_PROBED,
    TIER_COVERED,
    TIER_ADMITTED,
    TIER_BLOCKED_MISSING,
    TIER_BLOCKED_NON_EFFECT,
    TIER_BLOCKED_SUBSYSTEM,
)

_TIER_LABEL = {
    TIER_PROBED: "PROBED byte-equal",
    TIER_COVERED: "Effect+bridge covered (not individually probed)",
    TIER_ADMITTED: "bridge-admitted & bench-exercised",
    TIER_BLOCKED_MISSING: "BLOCKED — genuinely_missing (new-Rust-Effect ask)",
    TIER_BLOCKED_NON_EFFECT: "BLOCKED — blocked_non_effect (non-Effect gate)",
    TIER_BLOCKED_SUBSYSTEM: "BLOCKED — subsystem-gated / Effect-uncovered",
}


# ------------------------------------------------- reuse the coverage parser


def _coverage_module():
    """Import ``scripts/measure_effect_coverage`` so its EoE-pool
    walker + Rust parser + name-mapping are reused verbatim (the parse
    rule is NOT duplicated here — the round-19 cron's same discipline).
    """
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))
    import measure_effect_coverage as mec  # noqa: E402

    return mec


def covered_python_class_set() -> set[str]:
    """The set of Python ``Effect`` class names that have a live Rust
    ``Effect::`` variant + (by the coverage script's mapping) a
    counterpart — i.e. ``py_class_set ∩ rust_py_name_set``. This is the
    EXACT "covered" relation ``measure_effect_coverage`` reports as its
    class-count headline; reused so the two metrics can never disagree
    on what "covered" means."""
    mec = _coverage_module()
    py_classes, _examples, _n = mec.collect_python_effect_vocab()
    rust_variants = mec.collect_rust_effect_variants()
    rust_py_name_set = {mec.map_rust_to_python(v) for v in rust_variants}
    return set(py_classes.keys()) & rust_py_name_set


# ------------------------------------------------- per-card Effect classes


def card_effect_classes(printing) -> set[str]:
    """The distinct Python ``Effect`` class names a single printing
    emits, using ``measure_effect_coverage``'s exact recursive walker
    (``_maybe_walk`` over ``spell_effect`` + ``triggered_abilities`` +
    ``activated_abilities`` + ``static_abilities``). Returns an empty
    set for a pure-vanilla / keyword-only card."""
    mec = _coverage_module()
    from collections import Counter

    classes: Counter[str] = Counter()
    examples: dict[str, set[str]] = defaultdict(set)
    seen_ids: set[int] = set()
    name = getattr(printing, "name", "?")
    try:
        mec._maybe_walk(
            printing.spell_effect, classes, examples, name, seen_ids
        )
        for ta in printing.triggered_abilities:
            mec._maybe_walk(ta, classes, examples, name, seen_ids)
        for aa in getattr(printing, "activated_abilities", ()) or ():
            mec._maybe_walk(aa, classes, examples, name, seen_ids)
        for sa in getattr(printing, "static_abilities", ()) or ():
            mec._maybe_walk(sa, classes, examples, name, seen_ids)
    except Exception:
        # Mirror the coverage walker's defensive contract: a card the
        # walker can't introspect contributes no classes (it then
        # falls to a BLOCKED tier — never spuriously "covered").
        return set()
    return set(classes.keys())


# ------------------------------------------------- genuine-probe inventory


def _slug(text: str) -> str:
    """snake_case slug used to match a probe function-name prefix to a
    printed card name. Lowercase, non-alphanumerics → ``_``, collapsed,
    trimmed. ``"Mechan Assembler"`` → ``mechan_assembler``;
    ``"Roaring Furnace // Steaming Sauna"`` is keyed on its LEFT face
    (``roaring_furnace``) since split-card probes name the left face."""
    primary = text.split(" // ")[0]
    return re.sub(r"[^a-z0-9]+", "_", primary.lower()).strip("_")


def genuine_probed_cards(
    pool_names: set[str], smoke_path: Path = SMOKE_TEST
) -> set[str]:
    """The set of EoE pool card names that have a genuine real-EoE
    cross-engine *parity* probe pinning them.

    Detection: every ``def test_cross_engine_real_eoe_<mid>_parity``
    function in ``tests/test_parity_smoke.py``; ``<mid>`` is matched
    against the slug of each pool card's printed name, longest slug
    first (so ``mechan_assembler`` wins over ``mechan``). Only
    ``*_parity`` functions count — ``*_divergence_pin`` functions
    assert a KNOWN divergence, the opposite of byte-equality, and are
    deliberately excluded. Pure text; no engine import."""
    text = smoke_path.read_text(encoding="utf-8")
    fn_mids = re.findall(
        r"def test_cross_engine_real_eoe_(\w+?)_parity\(", text
    )
    # Longest-slug-first so a card whose slug is a prefix of another
    # card's slug doesn't steal the attribution.
    slug_to_name: dict[str, str] = {}
    for n in pool_names:
        slug_to_name.setdefault(_slug(n), n)
    ordered = sorted(slug_to_name, key=len, reverse=True)
    probed: set[str] = set()
    for mid in fn_mids:
        for sg in ordered:
            if mid == sg or mid.startswith(sg + "_"):
                probed.add(slug_to_name[sg])
                break
    return probed


# ------------------------------------------------- residue worklist split


def residue_blocked_cards(
    path: Path = RESIDUE_WORKLIST,
) -> tuple[set[str], set[str]]:
    """Return ``(genuinely_missing_cards, blocked_non_effect_cards)``
    from the canonical residue worklist. ``closed`` entries are NOT
    blocked (they shipped + bridged) so they are excluded. Card names
    are taken verbatim from each entry's ``card`` field; entries whose
    ``card`` carries a parenthetical qualifier (e.g. the legacy
    duplicate row "Monoist Circuit-Feeder (legacy duplicate row)") are
    normalised to the bare printed name so the consistency cross-check
    keys on the real pool name."""
    import json

    if not path.exists():
        raise RuntimeError(
            f"residue worklist {path} is missing — it is the canonical "
            f"BLOCKED-RUST-EFFECT residue list this metric cross-checks "
            f"against; restore it."
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    missing: set[str] = set()
    non_effect: set[str] = set()
    for e in data.get("entries", []):
        card = (e.get("card") or "").strip()
        if not card:
            continue
        # Strip a trailing " (qualifier)" so a legacy-duplicate /
        # annotated row still keys on the real printed name.
        card = re.sub(r"\s*\([^)]*\)\s*$", "", card).strip()
        st = e.get("status")
        if st == "genuinely_missing":
            missing.add(card)
        elif st == "blocked_non_effect":
            non_effect.add(card)
    return missing, non_effect


# ------------------------------------------------- loader admit predicate


def loader_admits(printing) -> bool:
    """True iff the production-deck loader admits this printing — the
    EXACT gate the bench corpus runs through
    (``trajectory._printing_is_bridge_basic_land`` OR
    ``_printing_is_bridge_simple_creature``). Reused, not reimplemented,
    so the bench tier and the real bench can never disagree on what
    "admitted" means."""
    from mtg_bot.parity import trajectory as traj

    try:
        return bool(
            traj._printing_is_bridge_basic_land(printing)
            or traj._printing_is_bridge_simple_creature(printing)
        )
    except Exception:
        return False


# ------------------------------------------------- the classifier


@dataclass
class PoolParityResult:
    n_pool: int
    tiers: dict[str, list[str]]
    # Internal-consistency violations: a residue `genuinely_missing`
    # card the class-granularity heuristic WOULD have counted as
    # covered/probed. The worklist's per-card re-walk is the authority
    # on genuine absence (it sees riders the class heuristic can't —
    # e.g. `DestroyTargetCreature` maps to Rust's generic `DestroyTarget`
    # but a `draw_if_undamaged` rider is genuinely unshipped). When this
    # list is non-empty the class heuristic is over-optimistic for
    # those cards and the doc emits a WARNING; the cards are pinned to
    # BLOCKED regardless (the metric never overstates). Each tuple is
    # (card, tier_the_heuristic_would_have_used).
    consistency_violations: list[tuple[str, str]] = field(
        default_factory=list
    )
    # Informational (NOT a violation): residue `blocked_non_effect`
    # cards whose Effects ARE covered/probed at the Effect+bridge level
    # — that is precisely their definition (Effects shipped; the card
    # is gated by a non-Effect path). The metric measures Effect+bridge
    # byte-equality; the residue worklist tracks full-card admit
    # blockers — these legitimately differ and are surfaced as context,
    # not drift. Each tuple is (card, effect_evidence) where
    # effect_evidence is "probed" or "covered".
    blocked_non_effect_with_covered_effects: list[tuple[str, str]] = (
        field(default_factory=list)
    )

    def counts(self) -> dict[str, int]:
        return {k: len(self.tiers[k]) for k in _TIER_ORDER}


def classify_pool() -> PoolParityResult:
    """Walk the EoE pool, classify every printing into exactly one
    tier by the strict precedence in the module docstring, and run the
    residue-worklist internal-consistency cross-check."""
    from mtg_bot.cards.parser.source import OracleParserCardSource

    src = OracleParserCardSource()
    printings = src.get_printings()
    pool_names = set(printings.keys())

    covered_classes = covered_python_class_set()
    probed = genuine_probed_cards(pool_names)
    missing_cards, non_effect_cards = residue_blocked_cards()

    tiers: dict[str, list[str]] = {k: [] for k in _TIER_ORDER}
    violations: list[tuple[str, str]] = []
    bne_covered: list[tuple[str, str]] = []

    for name, printing in sorted(printings.items()):
        eff_classes = card_effect_classes(printing)
        all_effects_covered = bool(eff_classes) and eff_classes.issubset(
            covered_classes
        )
        admitted = loader_admits(printing)
        is_missing = name in missing_cards
        is_non_effect = name in non_effect_cards
        is_probed = name in probed
        covered_ok = (
            all_effects_covered or (not eff_classes and admitted)
        )

        # --- residue-worklist authority over the class heuristic -----
        # The per-card residue re-walk is the source of truth on
        # genuine absence; it sees Effect-shape riders the
        # class-granularity heuristic cannot (e.g. a `draw_if_undamaged`
        # rider on a class that otherwise maps to a live Rust variant).
        # So a `genuinely_missing` card is HARD-pinned to the BLOCKED-
        # missing tier no matter what the probe-name match / class
        # heuristic says — the metric must never overstate parity.
        if is_missing:
            tiers[TIER_BLOCKED_MISSING].append(name)
            if is_probed or covered_ok:
                # The class heuristic disagrees with the per-card
                # re-walk — surface it (the worklist wins, but the
                # heuristic's blind spot is worth a WARNING).
                violations.append(
                    (name, TIER_PROBED if is_probed else TIER_COVERED)
                )
            continue

        # A `blocked_non_effect` card is, BY DEFINITION, one whose
        # Effects ARE shipped/bridged but whose full-card admit is
        # gated by a non-Effect path. Its Effects being covered/probed
        # is EXPECTED, not drift — record it as informational context
        # and pin the card to the blocked_non_effect tier (full-card
        # parity is what's blocked; the metric does not count it as
        # byte-equal).
        if is_non_effect:
            tiers[TIER_BLOCKED_NON_EFFECT].append(name)
            if is_probed:
                bne_covered.append((name, "probed"))
            elif covered_ok:
                bne_covered.append((name, "covered"))
            continue

        # Precedence 1: PROBED (strongest). A genuine probe pins it.
        if is_probed:
            tiers[TIER_PROBED].append(name)
            continue

        # Precedence 2: covered-by-construction. Every emitted Effect
        # class has a live+bridged Rust counterpart. A 0-Effect
        # (vanilla / keyword-only) card qualifies here only if
        # loader-admitted (otherwise it has no cross-engine exercise
        # path and drops to the bench / blocked tier below).
        if covered_ok:
            tiers[TIER_COVERED].append(name)
            continue

        # Precedence 3: bridge-admitted & bench-exercised. The loader
        # admits it (the bench runs it 0-divergence at scale, capped
        # at ~22-25 turns). In practice the loader's admit gate only
        # passes vanilla / safe-trigger creatures + basic lands — all
        # of which have covered (or zero) Effects and were already
        # caught by precedence 2 — so this tier is typically empty.
        # It is kept explicit so that if the admit gate ever widens to
        # admit a card whose Effects are NOT all class-covered, the
        # bench's empirical 0-divergence signal still counts it here
        # rather than dropping it to BLOCKED.
        if admitted:
            tiers[TIER_ADMITTED].append(name)
            continue

        # Precedence 4: BLOCKED — the long subsystem-gated /
        # Effect-uncovered tail (not itemised in the residue worklist).
        tiers[TIER_BLOCKED_SUBSYSTEM].append(name)

    return PoolParityResult(
        n_pool=len(pool_names),
        tiers=tiers,
        consistency_violations=violations,
        blocked_non_effect_with_covered_effects=bne_covered,
    )


# ------------------------------------------------- markdown render


def _pct(n: int, d: int) -> float:
    return (100.0 * n / d) if d else 0.0


def render_markdown(res: PoolParityResult) -> str:
    c = res.counts()
    n = res.n_pool
    probed_n = c[TIER_PROBED]
    covered_n = c[TIER_COVERED]
    admitted_n = c[TIER_ADMITTED]
    # "byte-equal at the Effect+bridge level" = PROBED + covered (every
    # Effect lives + bridges; PROBED additionally has a genuine probe).
    byte_equal_n = probed_n + covered_n
    blocked_total = (
        c[TIER_BLOCKED_MISSING]
        + c[TIER_BLOCKED_NON_EFFECT]
        + c[TIER_BLOCKED_SUBSYSTEM]
    )

    L: list[str] = []
    L.append(
        "Generated by `scripts/measure_pool_parity.py` — "
        "DO NOT EDIT MANUALLY. Run the script to refresh."
    )
    L.append("")
    L.append("# Pool-level cross-engine parity metric")
    L.append("")
    L.append(
        "The authoritative, measured, regenerable answer to *\"what "
        "fraction of the EoE card pool is byte-equal cross-engine?\"* "
        "Every printing the parser claims (the same pool "
        "`measure_effect_coverage.py` walks) is classified into exactly "
        "one honest tier by a strict precedence (strongest evidence "
        "wins). This replaces the three PROXIES the campaign used to "
        "estimate from (per-emission Rust coverage, the residue count, "
        "\"0 FAIL_DIVERGENCE over the admitted subset\") with a single "
        "tracked number."
    )
    L.append("")
    L.append("## Headline")
    L.append("")
    L.append(
        f"- **{byte_equal_n} / {n} EoE cards "
        f"({_pct(byte_equal_n, n):.1f}%) are byte-equal at the "
        f"Effect+bridge level**; of those, **{probed_n} "
        f"({_pct(probed_n, n):.1f}% of the pool) are individually "
        f"pinned by a genuine real-EoE cross-engine byte-equality "
        f"probe** (the strongest evidence), the remaining "
        f"{covered_n} are covered-by-construction (every Effect they "
        f"emit has a live Rust variant + bridge arm, but no genuine "
        f"probe pins THAT card)."
    )
    L.append(
        f"- A further **{admitted_n} ({_pct(admitted_n, n):.1f}%)** "
        f"are bridge-admitted & bench-exercised 0-divergence at scale "
        f"(empirical, but bounded — see the caveat)."
    )
    L.append(
        f"- **{blocked_total} ({_pct(blocked_total, n):.1f}%)** are "
        f"BLOCKED, broken out below."
    )
    L.append("")
    L.append(
        "> **CAVEAT — what this measures vs. what it does NOT.** This "
        "is **Effect+bridge-level byte-equality evidence**, NOT "
        "full-game-trajectory parity. The PROBED tier asserts "
        "byte-equality on a *controlled* cross-engine state (a real "
        "EoE printing driven end-to-end), not over a full random "
        "multi-turn game. The covered-by-construction tier only proves "
        "the card's Effect *primitives* all exist + bridge — it does "
        "**not** prove the card plays byte-equal in a real game. The "
        "bench tier is the empirical full-trajectory signal but is "
        "**capped at ~22-25 turns** (see "
        "`docs/bench_trajectory_parity_smoke.md`) and only over the "
        "loader-admitted subset. **No tier here claims the whole pool "
        "is byte-equal in real full-game trajectories** — that "
        "remains out of scope and is the campaign's open frontier."
    )
    L.append("")

    L.append("## Tiers")
    L.append("")
    L.append("| Tier | Count | % of pool |")
    L.append("|---|---:|---:|")
    for k in _TIER_ORDER:
        L.append(
            f"| {_TIER_LABEL[k]} | {c[k]} | {_pct(c[k], n):.1f}% |"
        )
    L.append(f"| **Pool total** | **{n}** | **100.0%** |")
    L.append("")

    L.append("### Tier definitions")
    L.append("")
    L.append(
        "Evaluated in this strict precedence (a card lands in the "
        "FIRST tier it qualifies for):"
    )
    L.append("")
    L.append(
        "1. **PROBED byte-equal** — a "
        "`test_cross_engine_real_eoe_<slug>_parity` function in "
        "`tests/test_parity_smoke.py` (slug = the card's printed-name "
        "slug, split cards keyed on the left face) asserts "
        "byte-equality for THIS card. `*_divergence_pin` functions are "
        "excluded (they pin a KNOWN divergence). Strongest evidence."
    )
    L.append(
        "2. **Effect+bridge covered (not individually probed)** — "
        "every distinct Python `Effect` class the card emits (walked "
        "with `measure_effect_coverage`'s exact walker) is in that "
        "script's covered-class set (live Rust variant + bridge), AND "
        "the card is not a residue-worklist BLOCKED entry. A "
        "0-Effect vanilla / keyword-only card qualifies here only if "
        "loader-admitted. Covered-by-construction — weaker than a "
        "genuine probe."
    )
    L.append(
        "3. **bridge-admitted & bench-exercised** — the production-deck "
        "loader admits the printing "
        "(`trajectory._printing_is_bridge_basic_land` or "
        "`_printing_is_bridge_simple_creature` — the exact bench admit "
        "gate) and the bench runs it 0-divergence at scale. "
        "Bounded-depth empirical signal (~22-25 turn cap)."
    )
    L.append(
        "4. **BLOCKED** — not byte-equal-covered today; broken out:"
    )
    L.append(
        "   - **genuinely_missing** — a residue-worklist "
        "`genuinely_missing` entry: a TRUE new-Rust-Effect ask (the "
        "load-bearing \"how far from parity\" gap)."
    )
    L.append(
        "   - **blocked_non_effect** — a residue-worklist "
        "`blocked_non_effect` entry: Effects shipped, gated by a "
        "non-Effect path (unbridged event / declined cost-mechanic / "
        "unmodeled subsystem / token-registration substrate)."
    )
    L.append(
        "   - **subsystem-gated / Effect-uncovered** — the long "
        "blocked tail: emits an Effect with no covered Rust "
        "counterpart, or is loader-rejected by a subsystem gate "
        "(Station / Ward / Devour / warp / Aura / Rooms / "
        "BECOMES_TAPPED / dynamic-P/T / activated+static abilities / "
        "planeswalker / …), and is not itemised in the residue "
        "worklist."
    )
    L.append("")

    # Internal-consistency cross-check.
    L.append("## Internal-consistency cross-check (residue worklist)")
    L.append("")
    L.append(
        "The residue worklist's per-card re-walk is the AUTHORITY on "
        "genuine Effect absence (it sees Effect-shape riders the "
        "class-granularity coverage heuristic cannot). A "
        "`genuinely_missing` card is therefore hard-pinned to the "
        "BLOCKED tier regardless of what the class heuristic / probe "
        "name-match says — the metric never overstates parity."
    )
    L.append("")
    if res.consistency_violations:
        L.append(
            f"**WARNING: {len(res.consistency_violations)} "
            f"`genuinely_missing` card(s) the class-granularity "
            f"heuristic WOULD have counted as covered/probed.** They "
            f"are pinned to BLOCKED (the worklist wins), but the "
            f"heuristic's class-level blind spot for these is worth "
            f"reconciling — either the worklist entry is stale (the "
            f"Effect actually shipped → close it; the round-54/55 cron "
            f"is the structural backstop) or the class heuristic is "
            f"genuinely too coarse for that card's rider (expected — "
            f"this is exactly why the per-card worklist exists):"
        )
        L.append("")
        for card, tier in sorted(res.consistency_violations):
            L.append(
                f"- `{card}` — residue `genuinely_missing`; class "
                f"heuristic would have placed it in `{tier}` "
                f"(class-granularity false-positive — pinned BLOCKED)."
            )
    else:
        L.append(
            "- **0 violations** — no `genuinely_missing` residue card "
            "was class-heuristic-counted as covered/probed. The "
            "headline does not overstate parity relative to the honest "
            "residue list."
        )
    L.append("")
    # Informational: blocked_non_effect cards with covered/probed
    # Effects. This is EXPECTED (their definition) — surfaced as
    # context, not drift, so a reader understands the gap between
    # "Effect+bridge byte-equal" and "full-card parity".
    if res.blocked_non_effect_with_covered_effects:
        L.append(
            f"_Context (NOT drift): "
            f"{len(res.blocked_non_effect_with_covered_effects)} "
            f"`blocked_non_effect` card(s) have covered/probed Effects "
            f"— that is their definition (Effects shipped; full-card "
            f"admit gated by a non-Effect path). The metric counts "
            f"Effect+bridge byte-equality; these cards' Effects ARE "
            f"byte-equal but the CARD is not full-game parity-able. "
            f"This is the precise gap between the two — surfaced for "
            f"honesty:_"
        )
        L.append("")
        for card, ev in sorted(
            res.blocked_non_effect_with_covered_effects
        ):
            L.append(
                f"- `{card}` — Effects {ev} at the Effect+bridge "
                f"level; CARD remains `blocked_non_effect` "
                f"(non-Effect gate)."
            )
        L.append("")

    # Per-tier card listings (BLOCKED tiers itemised; covered tiers
    # summarised — the bulk; PROBED listed in full as it's the
    # strongest, most-auditable claim).
    L.append("## PROBED cards (genuine real-EoE byte-equality probes)")
    L.append("")
    if res.tiers[TIER_PROBED]:
        for nm in sorted(res.tiers[TIER_PROBED]):
            L.append(f"- {nm}")
    else:
        L.append("- (none)")
    L.append("")

    for k in (
        TIER_BLOCKED_MISSING,
        TIER_BLOCKED_NON_EFFECT,
    ):
        L.append(f"## {_TIER_LABEL[k]} ({c[k]})")
        L.append("")
        if res.tiers[k]:
            for nm in sorted(res.tiers[k]):
                L.append(f"- {nm}")
        else:
            L.append("- (none)")
        L.append("")

    L.append(
        f"## {_TIER_LABEL[TIER_BLOCKED_SUBSYSTEM]} "
        f"({c[TIER_BLOCKED_SUBSYSTEM]})"
    )
    L.append("")
    L.append(
        "The long blocked tail (not itemised in the residue "
        "worklist). First 60 shown for auditability; the full set is "
        "regenerable from the script:"
    )
    L.append("")
    for nm in sorted(res.tiers[TIER_BLOCKED_SUBSYSTEM])[:60]:
        L.append(f"- {nm}")
    if c[TIER_BLOCKED_SUBSYSTEM] > 60:
        L.append(f"- … and {c[TIER_BLOCKED_SUBSYSTEM] - 60} more")
    L.append("")

    return "\n".join(L) + "\n"


# ------------------------------------------------- headline (one-liner)


def headline_line(res: PoolParityResult) -> str:
    """A single never-blocking headline string for the staleness cron /
    post-commit hook. Mirrors the round-52/55 cron headline contract:
    one line, no exit-code semantics for the hook."""
    c = res.counts()
    n = res.n_pool
    be = c[TIER_PROBED] + c[TIER_COVERED]
    viol = len(res.consistency_violations)
    suffix = (
        f" ⚠ {viol} residue-consistency violation(s)" if viol else ""
    )
    return (
        f"[pool-parity] {be}/{n} EoE cards "
        f"({_pct(be, n):.1f}%) byte-equal at the Effect+bridge level "
        f"({c[TIER_PROBED]} genuinely probed); "
        f"{c[TIER_ADMITTED]} bench-exercised; "
        f"{c[TIER_BLOCKED_MISSING]} genuinely_missing / "
        f"{c[TIER_BLOCKED_NON_EFFECT]} blocked_non_effect / "
        f"{c[TIER_BLOCKED_SUBSYSTEM]} subsystem-gated. "
        f"NOT full-game-trajectory parity (caveat in "
        f"docs/POOL_PARITY.md).{suffix}"
    )


# ------------------------------------------------- entrypoint


def main(argv: list[str] | None = None) -> int:
    """Default: classify, (re)write ``docs/POOL_PARITY.md``, print the
    full markdown. With ``--headline``: classify and print ONLY the
    one-line never-blocking headline (the post-commit-hook entry — does
    NOT rewrite the doc, mirroring the round-52/55 cron headline
    contract: surface a line, never block, never side-effect on disk).

    Exit code is non-zero iff the residue-consistency cross-check fired
    (a ``genuinely_missing`` card the class heuristic over-counted) —
    for explicit CI / standalone gating only. The post-commit hook
    never propagates it, exactly like the staleness cron.
    """
    argv = sys.argv[1:] if argv is None else argv
    headline_only = "--headline" in argv
    res = classify_pool()
    if headline_only:
        print(headline_line(res))
    else:
        md = render_markdown(res)
        OUTPUT_DOC.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_DOC.write_text(md, encoding="utf-8")
        print(md)
    return 1 if res.consistency_violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
