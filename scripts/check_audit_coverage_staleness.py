#!/usr/bin/env python3
"""Audit / coverage-doc staleness check (round-19 cron proposal).

The cross-engine parity campaign has hit the same audit/coverage-doc
staleness class **three times** (rounds 34, 49, 51): a human/agent has
to manually re-walk the diff between the *live* Rust-Effect /
bridge-arm / ``_SAFE_*`` inventory and the headline numbers the audit
+ coverage doc assert, because substrate keeps shipping underneath a
frozen headline. The standing round-19 proposal (recorded in
``docs/EOE_PROBE_READINESS_AUDIT.md``) is to auto-diff that inventory
on every ``main`` merge and surface drift structurally instead of
re-discovering it by hand.

This module is that check. It:

1. **Derives the live inventory** off the working tree —
   * the number of top-level ``Effect::`` enum variants in
     ``rust/src/cards.rs`` (reuses
     ``measure_effect_coverage.collect_rust_effect_variants`` — the
     same pure-text parser the coverage doc is generated from, so the
     two can never disagree on the parsing rule);
   * the number of distinct ``kind == "..."`` bridge arms inside
     ``cross_engine._ta_dict_to_python_effect`` (scoped to the
     function body, between the ``def`` and the
     ``PHASE5_BRIDGE_ARMS_INSERT_ABOVE_THIS_LINE`` sentinel, with
     comments stripped so prose ``kind ==`` mentions don't inflate
     the count);
   * the sizes of ``parity.trajectory._SAFE_TRIGGERS`` /
     ``_SAFE_KEYWORDS`` / ``_SAFE_EFFECT_KEYS`` (read off the imported
     module objects — authoritative, no literal re-parsing).

2. **Reads the doc-asserted headline numbers** from a single
   machine-readable sentinel block in
   ``docs/EOE_PROBE_READINESS_AUDIT.md`` (delimited by
   ``<!-- STALENESS-SENTINEL:BEGIN -->`` /
   ``<!-- STALENESS-SENTINEL:END -->``; ``key = value`` lines, ``#``
   comments allowed) PLUS the auto-generated ``Rust Effect`` variant
   count headline in ``docs/RUST_EFFECT_COVERAGE.md``. The sentinel
   block is the structured record the prose headline tables paraphrase
   — it is the one place a refresh updates the asserted counts, the
   same way ``hooks/post-commit`` keeps its structured record in
   ``.perf_history.log``.

3. **Diffs and reports.** On drift it prints a precise, actionable
   line per drifted count: which inventory, doc-claimed vs actual,
   and where to refresh.

4. **Per-entry residue staleness (round-54 extension).** The
   count-level diff above catches the inventory *totals* moving, but
   it structurally CANNOT catch a BLOCKED-RUST-EFFECT residue entry
   that names an Effect which *actually exists* — the Rust-variant
   count goes UP when that Effect ships, so the count diff is happy
   even though the residue list is now over-counting a closed card.
   That is exactly the sub-class rounds 51/53 had to hand-find
   (Mechanozoa, Warmaker Gunship, Mightform Harmonizer) and the
   round-54 full re-walk surfaced 2 more of (Monoist Circuit-Feeder,
   Extinguisher Battleship). The round-54 extension reads the
   machine-readable residue worklist ``docs/residue_worklist.json``
   (the canonical output of the round-54 re-walk) and, for every
   ``genuinely_missing`` entry, resolves its claimed-missing Effect
   name through its ``aliases`` (plan-name → real-variant) against the
   live Rust ``Effect`` enum + the live bridge-arm inventory; if any
   such entry's Effect *actually exists + is bridged*, the entry is
   STALE (the audit would over-count it) and the check FAILs. It also
   regression-guards the ``closed`` entries the other way: each must
   still resolve to a live + bridged variant, or the closure prose
   itself went stale. Same alias-resolution rule the re-walk used
   (robust acronym-aware snake_case so e.g. ``DoubleTargetCreaturesPowerUEOT``
   → bridge ``double_target_creatures_power_ueot``).

Standalone use::

    PYTHONPATH=src \\
    ../../mtg-bot/.venv-py313/Scripts/python.exe \\
    scripts/check_audit_coverage_staleness.py

Exit code is ``0`` when in sync, ``1`` when drift is detected — so a
CI step or a human can gate on it. The **post-commit hook wiring**
(``hooks/post-commit``) deliberately does NOT propagate that exit
code: per the campaign's git-hook contract (mirrored from the perf
hook) the staleness report is purely informational, runs only on
``main`` commits, is skipped on feature branches, and never blocks a
commit — it prints the report to stderr and the hook exits 0
regardless. The non-zero standalone exit is for the explicit
``python scripts/check_audit_coverage_staleness.py`` /
CI-gate use only.
"""

from __future__ import annotations

import io
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
else:  # pragma: no cover
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
AUDIT_DOC = REPO_ROOT / "docs" / "EOE_PROBE_READINESS_AUDIT.md"
COVERAGE_DOC = REPO_ROOT / "docs" / "RUST_EFFECT_COVERAGE.md"
CROSS_ENGINE = REPO_ROOT / "src" / "mtg_bot" / "parity" / "cross_engine.py"
RESIDUE_WORKLIST = REPO_ROOT / "docs" / "residue_worklist.json"

SENTINEL_BEGIN = "<!-- STALENESS-SENTINEL:BEGIN -->"
SENTINEL_END = "<!-- STALENESS-SENTINEL:END -->"

# Keys recorded in the audit sentinel block. Each maps to a
# (human label, "where to refresh" hint) pair used in the drift
# report.
_SENTINEL_KEYS = {
    "rust_effect_variants": (
        "Rust `Effect::` enum variants (rust/src/cards.rs)",
        "rerun scripts/measure_effect_coverage.py, then sync the "
        "audit headline table + the STALENESS-SENTINEL block",
    ),
    "bridge_arms": (
        "Bridge `kind ==` arms in cross_engine._ta_dict_to_python_effect",
        "sync the audit headline table + the STALENESS-SENTINEL block",
    ),
    "safe_triggers": (
        "parity.trajectory._SAFE_TRIGGERS triples",
        "sync the audit headline table + the STALENESS-SENTINEL block",
    ),
    "safe_keywords": (
        "parity.trajectory._SAFE_KEYWORDS entries",
        "sync the audit headline table + the STALENESS-SENTINEL block",
    ),
    "safe_effect_keys": (
        "parity.trajectory._SAFE_EFFECT_KEYS arms",
        "sync the audit headline table + the STALENESS-SENTINEL block",
    ),
}


# ----------------------------------------------------------- live inventory


def count_rust_effect_variants() -> int:
    """Number of top-level ``Effect::`` enum variants in
    ``rust/src/cards.rs``. Reuses the coverage script's pure-text
    parser so the staleness check and the coverage doc can never
    disagree on the parsing rule."""
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))
    from measure_effect_coverage import collect_rust_effect_variants

    return len(collect_rust_effect_variants())


def count_bridge_arms(cross_engine_path: Path = CROSS_ENGINE) -> int:
    """Distinct ``kind == "..."`` literals inside
    ``_ta_dict_to_python_effect``.

    Scoped to the function body — from the ``def`` line to the
    ``PHASE5_BRIDGE_ARMS_INSERT_ABOVE_THIS_LINE`` sentinel — and with
    ``#`` comments stripped first so a ``kind ==`` mentioned in a
    docstring/comment doesn't inflate the count. This is the same
    bucket the audit's "Bridge-arm effect ``kind ==`` literals in
    ``_ta_dict_to_python_effect``" headline row tracks.
    """
    text = cross_engine_path.read_text(encoding="utf-8")
    try:
        start = text.index("def _ta_dict_to_python_effect")
    except ValueError as exc:  # pragma: no cover - structural guard
        raise RuntimeError(
            f"could not find _ta_dict_to_python_effect in "
            f"{cross_engine_path}"
        ) from exc
    try:
        end = text.index(
            "# === PHASE5_BRIDGE_ARMS_INSERT_ABOVE_THIS_LINE ===",
            start,
        )
    except ValueError as exc:  # pragma: no cover - structural guard
        raise RuntimeError(
            f"could not find the PHASE5_BRIDGE_ARMS_INSERT_ABOVE "
            f"sentinel after _ta_dict_to_python_effect in "
            f"{cross_engine_path}"
        ) from exc
    body = text[start:end]
    body_no_comments = re.sub(r"#[^\n]*", "", body)
    arms = set(re.findall(r'kind == "([a-z0-9_]+)"', body_no_comments))
    return len(arms)


def collect_live_inventory() -> dict[str, int]:
    """Return the live inventory dict keyed by the sentinel keys."""
    from mtg_bot.parity import trajectory as traj

    return {
        "rust_effect_variants": count_rust_effect_variants(),
        "bridge_arms": count_bridge_arms(),
        "safe_triggers": len(traj._SAFE_TRIGGERS),
        "safe_keywords": len(traj._SAFE_KEYWORDS),
        "safe_effect_keys": len(traj._SAFE_EFFECT_KEYS),
    }


# ----------------------------------------------- per-entry residue staleness
#
# Round-54 extension. The count-level diff above cannot catch a
# BLOCKED-RUST-EFFECT residue entry naming an Effect that actually
# exists (the Rust-variant count goes UP when it ships, so the count
# diff stays happy). This block reads the canonical machine-readable
# residue worklist `docs/residue_worklist.json` (the round-54 re-walk
# output) and resolves each entry's claimed-missing Effect name through
# its plan-name→real-variant `aliases` against the live Rust enum +
# bridge. A `genuinely_missing` entry that DOES resolve is STALE (the
# audit over-counts it). A `closed` entry that does NOT resolve means
# the closure prose itself went stale (regression guard the other way).


def collect_rust_variant_set() -> set[str]:
    """The live Rust ``Effect`` variant *names* (not just the count) —
    used by the per-entry residue resolver. Reuses the same coverage
    parser as the count path."""
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))
    from measure_effect_coverage import collect_rust_effect_variants

    return set(collect_rust_effect_variants())


def collect_bridge_arm_set(
    cross_engine_path: Path = CROSS_ENGINE,
) -> set[str]:
    """The live ``kind == "..."`` bridge-arm *names* inside
    ``_ta_dict_to_python_effect`` — same scoping/comment-stripping as
    ``count_bridge_arms`` (factored so the residue resolver and the
    count path can never disagree on what counts as a bridge arm)."""
    text = cross_engine_path.read_text(encoding="utf-8")
    start = text.index("def _ta_dict_to_python_effect")
    end = text.index(
        "# === PHASE5_BRIDGE_ARMS_INSERT_ABOVE_THIS_LINE ===", start
    )
    body_no_comments = re.sub(r"#[^\n]*", "", text[start:end])
    return set(re.findall(r'kind == "([a-z0-9_]+)"', body_no_comments))


def _camel_to_snake(camel: str) -> str:
    """Acronym-aware CamelCase → snake_case, matching the bridge-arm
    literal style. ``DoubleTargetCreaturesPowerUEOT`` →
    ``double_target_creatures_power_ueot`` (the ``UEOT`` acronym run
    must collapse to ``ueot``, NOT ``u_e_o_t`` — a naive
    ``(?=[A-Z])`` split gets that wrong, which is the exact bug the
    round-54 re-walk's first pass hit). This is the SAME resolution
    rule the re-walk used so the cron and the worklist can never
    disagree on how a variant name maps to its bridge ``kind``."""
    s = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", camel)
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s)
    return s.lower()


@dataclass(frozen=True)
class ResidueResolution:
    """Result of resolving one residue entry against the live tree."""

    entry: str
    card: str
    status: str  # "genuinely_missing" | "closed"
    claimed: str
    resolved_variant: str | None  # live Rust variant an alias hit, or None
    bridged: bool  # the resolved variant has a wired bridge arm


def resolve_residue_entry(
    entry: dict,
    rust_variants: set[str],
    bridge_arms: set[str],
) -> ResidueResolution:
    """Resolve one worklist entry: walk its ``aliases`` (plan-name →
    real-variant candidates) against the live Rust ``Effect`` enum;
    the first alias present wins. ``bridged`` is True iff that
    variant's acronym-aware snake_case is a live ``kind ==`` bridge
    arm. Pure — no engine import, no .pyd."""
    resolved: str | None = None
    for alias in entry.get("aliases", []):
        if alias in rust_variants:
            resolved = alias
            break
    bridged = resolved is not None and _camel_to_snake(resolved) in bridge_arms
    return ResidueResolution(
        entry=entry.get("entry", "?"),
        card=entry.get("card", "?"),
        status=entry.get("status", "?"),
        claimed=entry.get("claimed_missing_effect", "?"),
        resolved_variant=resolved,
        bridged=bridged,
    )


def parse_residue_worklist(path: Path = RESIDUE_WORKLIST) -> list[dict]:
    """Load + minimally validate the residue worklist. Raises
    ``RuntimeError`` for a missing/garbled file or a malformed entry —
    a broken worklist is itself a staleness signal we want surfaced
    loudly, not silently treated as "no residue to check" (same
    contract as ``parse_sentinel_block``)."""
    if not path.exists():
        raise RuntimeError(
            f"residue worklist {path} is missing — it is the canonical "
            f"round-54 re-walk output the per-entry staleness check "
            f"reads; restore it (see "
            f"scripts/check_audit_coverage_staleness.py docstring)"
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"residue worklist {path} is not valid JSON: {exc}"
        ) from exc
    entries = data.get("entries")
    if not isinstance(entries, list) or not entries:
        raise RuntimeError(
            f"residue worklist {path} has no 'entries' list"
        )
    for e in entries:
        st = e.get("status")
        if st not in ("genuinely_missing", "closed"):
            raise RuntimeError(
                f"residue worklist entry {e.get('entry')!r} has invalid "
                f"status {st!r} (expected 'genuinely_missing' or "
                f"'closed')"
            )
        if not e.get("aliases"):
            raise RuntimeError(
                f"residue worklist entry {e.get('entry')!r} has no "
                f"'aliases' list (need at least the claimed name)"
            )
        if st == "closed" and not e.get("resolved_variant"):
            raise RuntimeError(
                f"closed residue entry {e.get('entry')!r} must record a "
                f"'resolved_variant'"
            )
    return entries


def compute_residue_staleness(
    entries: list[dict],
    rust_variants: set[str],
    bridge_arms: set[str],
) -> list["Drift"]:
    """Return a list of ``Drift`` rows, one per residue entry that is
    stale:

    * a ``genuinely_missing`` entry whose claimed Effect actually
      resolves to a live Rust variant (bridged or not — a live variant
      alone already means the audit over-counts it as no-Rust-arm; the
      bridged flag sharpens the message);
    * a ``closed`` entry whose recorded ``resolved_variant`` no longer
      resolves to a live + bridged variant (the closure prose itself
      went stale — the inverse regression).

    Empty list == every residue claim still matches the live tree.
    """
    drifts: list[Drift] = []
    for e in entries:
        r = resolve_residue_entry(e, rust_variants, bridge_arms)
        if r.status == "genuinely_missing":
            if r.resolved_variant is not None:
                where = (
                    "bridged" if r.bridged else "live enum (no bridge arm)"
                )
                drifts.append(
                    Drift(
                        key=f"residue_stale::{r.entry}",
                        label=(
                            f"BLOCKED-RUST-EFFECT residue entry "
                            f"'{r.card}' ({r.entry})"
                        ),
                        claimed=0,
                        actual=1,
                        hint=(
                            f"claims `{r.claimed}` is a missing Rust "
                            f"Effect, but it resolves to live "
                            f"`Effect::{r.resolved_variant}` ({where}) — "
                            f"the residue list over-counts this card. "
                            f"Reclassify it out of BLOCKED-RUST-EFFECT in "
                            f"docs/EOE_PROBE_READINESS_AUDIT.md and flip "
                            f"its status to 'closed' in "
                            f"docs/residue_worklist.json. This is the "
                            f"round-51/53-class stale residue entry the "
                            f"count-only cron could not catch."
                        ),
                    )
                )
        else:  # closed — regression guard the other way
            recorded = e.get("resolved_variant")
            if r.resolved_variant != recorded or not r.bridged:
                drifts.append(
                    Drift(
                        key=f"residue_closure_stale::{r.entry}",
                        label=(
                            f"CLOSED residue entry '{r.card}' "
                            f"({r.entry}) closure prose"
                        ),
                        claimed=1,
                        actual=0,
                        hint=(
                            f"recorded as closed via "
                            f"`Effect::{recorded}`, but the live tree "
                            f"resolves it to "
                            f"`{r.resolved_variant}` (bridged="
                            f"{r.bridged}) — the recorded closure no "
                            f"longer holds (variant renamed/removed or "
                            f"its bridge arm dropped). Re-walk this "
                            f"entry and fix docs/residue_worklist.json + "
                            f"the audit."
                        ),
                    )
                )
    return drifts


# ------------------------------------------------------- doc-asserted counts


def parse_sentinel_block(audit_text: str) -> dict[str, int]:
    """Parse the ``key = value`` lines inside the audit's
    STALENESS-SENTINEL block. Lines that are blank or start with
    ``#`` (after stripping) are ignored; the value must be an int.

    Raises ``RuntimeError`` if the block is missing or malformed —
    a missing/garbled sentinel is itself a staleness signal we want
    surfaced loudly, not silently treated as "in sync".
    """
    try:
        b = audit_text.index(SENTINEL_BEGIN)
        e = audit_text.index(SENTINEL_END, b)
    except ValueError as exc:
        raise RuntimeError(
            f"audit doc is missing the {SENTINEL_BEGIN} / "
            f"{SENTINEL_END} sentinel block — add it (see "
            f"scripts/check_audit_coverage_staleness.py docstring)"
        ) from exc
    block = audit_text[b + len(SENTINEL_BEGIN):e]
    # Strip any nested HTML comments (``<!-- ... -->``) first — the
    # block carries a multi-line explanatory comment whose
    # continuation lines do NOT each start with ``<!--``, so a
    # per-line ``startswith`` check would misfire. ``re.S`` lets the
    # span cross newlines.
    block = re.sub(r"<!--.*?-->", "", block, flags=re.S)
    out: dict[str, int] = {}
    for raw in block.splitlines():
        line = raw.strip()
        # Blank lines / ``#`` comments are skipped.
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise RuntimeError(
                f"malformed STALENESS-SENTINEL line (no '='): {raw!r}"
            )
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip()
        if key not in _SENTINEL_KEYS:
            raise RuntimeError(
                f"unknown STALENESS-SENTINEL key {key!r}; expected one "
                f"of {sorted(_SENTINEL_KEYS)}"
            )
        try:
            out[key] = int(val)
        except ValueError as exc:
            raise RuntimeError(
                f"STALENESS-SENTINEL value for {key!r} is not an int: "
                f"{val!r}"
            ) from exc
    missing = sorted(set(_SENTINEL_KEYS) - set(out))
    if missing:
        raise RuntimeError(
            f"STALENESS-SENTINEL block is missing keys: {missing}"
        )
    return out


def parse_coverage_doc_rust_count(coverage_text: str) -> int:
    """Pull the ``- **N Rust `Effect` variants**`` headline number
    out of the auto-generated coverage doc. This is the doc the
    measure script writes; comparing it to the live parse catches a
    committed-stale ``RUST_EFFECT_COVERAGE.md`` (the round-51
    orphaned-regen problem)."""
    m = re.search(
        r"\*\*(\d+) Rust `Effect` variants\*\*", coverage_text
    )
    if m is None:
        raise RuntimeError(
            "could not find the '**N Rust `Effect` variants**' "
            "headline in docs/RUST_EFFECT_COVERAGE.md — regenerate it "
            "with scripts/measure_effect_coverage.py"
        )
    return int(m.group(1))


# ----------------------------------------------------------------- report


@dataclass(frozen=True)
class Drift:
    key: str
    label: str
    claimed: int
    actual: int
    hint: str

    def line(self) -> str:
        # Per-entry residue drifts (round-54) are boolean stale/not —
        # the "doc-claimed N, actual M (delta)" framing only makes
        # sense for the numeric count diffs, so render the residue
        # rows as a plain STALE line; the hint carries the full
        # actionable detail in both cases.
        if self.key.startswith(
            ("residue_stale::", "residue_closure_stale::")
        ):
            return f"  - STALE: {self.label} — {self.hint}"
        return (
            f"  - {self.label}: doc-claimed {self.claimed}, "
            f"actual {self.actual} "
            f"(delta {self.actual - self.claimed:+d}) — {self.hint}"
        )


def compute_drift(
    live: dict[str, int],
    claimed: dict[str, int],
    coverage_rust_count: int | None,
) -> list[Drift]:
    """Return the list of drifted counts (empty == in sync)."""
    drifts: list[Drift] = []
    for key, (label, hint) in _SENTINEL_KEYS.items():
        if live[key] != claimed[key]:
            drifts.append(
                Drift(key, label, claimed[key], live[key], hint)
            )
    # The coverage doc is auto-generated; if its committed headline
    # disagrees with the live Rust parse it is committed-stale (the
    # round-51 orphaned-regen class).
    if (
        coverage_rust_count is not None
        and coverage_rust_count != live["rust_effect_variants"]
    ):
        drifts.append(
            Drift(
                "coverage_doc_rust_variants",
                "docs/RUST_EFFECT_COVERAGE.md `Rust `Effect` "
                "variants` headline",
                coverage_rust_count,
                live["rust_effect_variants"],
                "regenerate it: PYTHONPATH=src python "
                "scripts/measure_effect_coverage.py, then commit "
                "docs/RUST_EFFECT_COVERAGE.md",
            )
        )
    return drifts


def build_report(drifts: list[Drift]) -> str:
    if not drifts:
        return (
            "[staleness] audit + coverage-doc headline counts are in "
            "sync with the live Rust-Effect / bridge-arm / _SAFE_* "
            "inventory, and every BLOCKED-RUST-EFFECT residue entry's "
            "claimed-missing Effect still matches the live tree."
        )
    count_drifts = [
        d
        for d in drifts
        if not d.key.startswith(
            ("residue_stale::", "residue_closure_stale::")
        )
    ]
    residue_drifts = [d for d in drifts if d not in count_drifts]
    lines = [
        "[staleness] DRIFT DETECTED between the live inventory and "
        "the doc-asserted headline counts / residue worklist:",
    ]
    if count_drifts:
        lines.append("  Headline-count drift:")
        lines.extend(d.line() for d in count_drifts)
    if residue_drifts:
        lines.append(
            "  Per-entry residue staleness "
            "(round-54 check — the sub-class the count-only cron "
            "could not catch):"
        )
        lines.extend(d.line() for d in residue_drifts)
    lines.append(
        "  Fix: refresh docs/EOE_PROBE_READINESS_AUDIT.md (headline "
        "table + the STALENESS-SENTINEL block + the per-card residue "
        "rows), sync docs/residue_worklist.json, and, if the Rust "
        "variant count moved, regenerate + commit "
        "docs/RUST_EFFECT_COVERAGE.md. This is the round-34/49/51/53 "
        "staleness class the round-19 cron proposal + the round-54 "
        "per-entry extension target."
    )
    return "\n".join(lines)


def run(*, write_stream=None) -> int:
    """Core entrypoint. Prints the report to ``write_stream``
    (default stdout) and returns the exit code (0 in sync, 1 drift).
    Never raises for the in-sync/drift path — only for genuinely
    broken inputs (missing sentinel block, unparseable docs), which
    are themselves staleness signals worth surfacing loudly."""
    stream = write_stream if write_stream is not None else sys.stdout
    live = collect_live_inventory()
    claimed = parse_sentinel_block(
        AUDIT_DOC.read_text(encoding="utf-8")
    )
    coverage_rust_count: int | None = None
    if COVERAGE_DOC.exists():
        coverage_rust_count = parse_coverage_doc_rust_count(
            COVERAGE_DOC.read_text(encoding="utf-8")
        )
    drifts = compute_drift(live, claimed, coverage_rust_count)
    # Round-54 per-entry residue staleness check (additive — same
    # never-blocking-hook contract: the hook ignores the exit code
    # regardless; this just adds rows to the same report and the same
    # non-zero standalone/CI exit). A broken worklist raises loudly,
    # exactly like a broken sentinel block.
    rust_variants = collect_rust_variant_set()
    bridge_arms = collect_bridge_arm_set()
    residue_entries = parse_residue_worklist()
    drifts.extend(
        compute_residue_staleness(
            residue_entries, rust_variants, bridge_arms
        )
    )
    print(build_report(drifts), file=stream)
    return 1 if drifts else 0


def main() -> int:
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
