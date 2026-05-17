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

5. **Structural (non-lexical) anti-staleness hardening (round-55).**
   The round-54 alias resolver in (4) is purely *lexical*: it only
   fires when one of an entry's curated ``aliases`` is *literally* a
   live Rust variant. Round-54 exposed its gap on Pulsar Squadron Ace
   — the Effect ``LookAtTopNRevealOrCounter`` + ``"spacecraft"``
   filter + bridge had shipped round 28/29 (the Rust doc-comment at
   ``rust/src/cards.rs`` literally names "Pulsar-Squadron-Ace"), yet
   the entry's plan-name ``ChoiceTriggerSpacecraftRevealOrCounter``
   did *not* lexically alias-resolve to ``LookAtTopNRevealOrCounter``,
   so BOTH the re-walk's "0 false-flags" pass AND the new per-entry
   cron missed it; the orchestrator caught it by hand. A guard
   defeatable by a non-lexically-matching plan-name is not a
   structural guarantee. Round-55 closes that with two additive,
   never-blocking signals (same hook contract — the report just gains
   rows; the hook still ignores the exit code):

   * **``verified_absent_at_commit`` + a re-verification cadence.**
     Every ``genuinely_missing`` entry must carry a
     ``verified_absent_at_commit`` git SHA — the commit at which a
     human/agent actually re-verified (live-enum + bridge + the
     name-in-bridge-arm check below) that the card's effect is
     genuinely absent. A missing field is itself a staleness signal
     (``residue_unverified``). The **cadence rule**: an entry needs
     re-verification if *any commit since its
     ``verified_absent_at_commit`` touched
     ``rust/src/cards.rs`` or ``src/mtg_bot/parity/cross_engine.py``*
     — those are the *only* two files whose changes can ship/bridge
     an Effect and thereby turn a genuinely-missing residue stale
     (exactly the Pulsar mechanism). That is the precise, minimal
     trigger: a stamp older than the last cards.rs / cross_engine.py
     touch can no longer be trusted, so the cron emits a
     ``residue_needs_reverify`` row. When git history is unavailable
     (a source tarball / a CI checkout with no ``rust/src/cards.rs``
     ancestry) the cadence check soft-skips — git-history *absence*
     is a known non-signal, not a staleness signal, so it must never
     produce a false re-verify (the broken-input-is-loud philosophy
     applies to the worklist/sentinel, NOT to optional git history).

   * **Non-lexical name-in-bridge-arm cross-check.** Independent of
     the curated ``aliases``, the card's *printed name* is scanned
     against the live bridge-arm blocks inside
     ``_ta_dict_to_python_effect`` (each ``if kind == "..."`` block,
     same scope/comment rule as ``count_bridge_arms`` — comments are
     KEPT here on purpose: a wired arm's doc-comment naming the card
     is the very signal, cf. Pulsar's
     ``look_at_top_n_reveal_or_counter`` arm naming "Pulsar Squadron
     Ace"). If the card name appears in an arm whose ``kind``
     resolves (acronym-aware snake_case) to a *live Rust ``Effect::``
     variant* — i.e. a fully-wired end-to-end effect path exists,
     named for that card — then either: (a) that arm's ``kind`` also
     matches one of the entry's own ``aliases`` → the entry's own
     data proves it should have resolved → hard ``residue_stale``;
     or (b) no alias matches (the *exact pre-r54 Pulsar shape*) → a
     ``residue_suspect_needs_reverify`` row demanding a hand re-walk.
     The (b) branch is what makes Pulsar-shaped staleness structurally
     un-silenceable: a wired arm naming the card surfaces it even
     when the plan-name never lexically matched the variant. It does
     *not* false-FAIL genuinely-absent cards whose name happens to
     appear in an *unrelated* card's-other-ability arm (Command
     Bridge in ``add_mana_to_pool``; Meltstrider's Resolve in the
     bare-bilateral ``fight_target_creature_with_target_creature``
     arm) — those legitimately surface as never-blocking
     *suspect/re-verify* prompts, which is correct: a human DID have
     to re-walk them, and the cron's contract is "Pulsar-shaped
     staleness cannot pass *silently*", not "auto-classify". A
     re-verify row is not silent.

6. **The ``blocked_non_effect`` status (round-56 extension).** The
   binary ``genuinely_missing`` / ``closed`` schema had no precise
   bucket for "the Effect arm(s) this card needs ARE shipped in Rust;
   the card's residual blocker is a NON-Effect gate (an unbridged
   event like ``BECOMES_TAPPED``, a §2-declined cost-mechanic, an
   unmodeled subsystem, or a token-registration substrate)". Such a
   card is **not** a BLOCKED-RUST-EFFECT ask (its Effects exist) yet
   it **cannot** be ``closed`` (``closed`` requires the blocking path
   be bridged, and the gating path here is precisely *unbridged*).
   Round-55 hit this with Seedship Agrarian: its real parse is
   ``Effect::CreateToken`` (Lander) on ``Event.BECOMES_TAPPED`` +
   ``Effect::PutPlusOneCounterOnSelf`` on landfall — BOTH Effects ARE
   shipped + bridged at the Effect level, but ``BECOMES_TAPPED`` is
   §2-declined / unbridged (the round-55 cron correctly rejected a
   forced ``closed``). The round-56 third status closes that gap. Its
   cron invariant is the *inverse* of ``genuinely_missing``: instead
   of asserting the claimed Effect stays *absent*, it asserts every
   name in the entry's ``shipped_variants`` list IS a live Rust
   ``Effect::`` variant — so a ``blocked_non_effect`` entry whose
   "shipped" Effect silently *regresses* to actually-missing (the
   card quietly became a genuine-Effect ask again) is caught
   (``residue_blocked_non_effect_regressed``) — AND it requires the
   entry record its specific ``non_effect_blocker``
   (missing/empty → ``residue_blocked_non_effect_underspecified``).
   It deliberately does **NOT** require ``bridged=True`` (that is the
   whole point — the card is gated precisely because some non-Effect
   path is unbridged) and does **NOT** carry
   ``verified_absent_at_commit`` (a genuine-absence stamp is
   meaningless when the Effects are present; the invariant is
   shipped-*presence*, not absence). The honest "how far from parity"
   number is the count of ``genuinely_missing`` entries (TRUE
   new-Rust-Effect asks); ``blocked_non_effect`` entries are NOT in
   that count — their Effects exist; they need an event-bridge /
   subsystem on a different lane. Same never-blocking hook contract:
   the rows only add to the report + flip the standalone/CI exit.

7. **Cross-entry card-status consistency (round-63 extension).** The
   round-54 lexical / round-55 structural / round-56
   ``blocked_non_effect`` arms each judge ONE entry in isolation —
   none looks ACROSS entries. That leaves a structurally-silent class
   the audit's own round-54 section names as the historical pain: an
   *internally self-contradictory* worklist where the same card is
   carried as ``genuinely_missing`` in one row AND reclassified-out
   (``closed`` / ``blocked_non_effect``) in another. The audit was
   exactly this for Mightform Harmonizer (§2.6 line ~80 recorded its
   round-31 closure while lines ~586/598/984/1048 still said "no Rust
   arm"); the round-54 re-walk fixed the *instances* but no guard was
   ever added against the *class* recurring — and it recurs precisely
   via a same-round fold: an agent closes a residue card but forgets
   to flip the card's still-``genuinely_missing`` row, so the card is
   simultaneously counted in the load-bearing "how far from parity"
   number (= # ``genuinely_missing`` entries) AND recorded as
   reclassified-out, each row passing its own in-isolation arm. The
   round-63 guard (``compute_card_status_consistency``) is the first
   cross-entry arm: it groups every entry by its printed ``card`` and
   flags any card whose rows MIX ``genuinely_missing`` with a
   reclassified-out status (one ``residue_card_status_conflict`` row
   per such card). It is deliberately tight — it does NOT flag the
   *legitimate* same-status multi-row patterns this worklist already
   uses (two ``genuinely_missing`` rows = two distinct unshipped arms,
   e.g. Lightstall Inquisitor's CastFromExile + EachOpponentExiles;
   two ``closed`` rows = a kept cron-regression duplicate). Only the
   load-bearing contradiction surfaces. Pure — one pass over the
   parsed worklist, no live tree / no git. Same additive
   never-blocking post-commit-hook contract as the round-54/55/56
   rows.

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
        if st not in (
            "genuinely_missing",
            "blocked_non_effect",
            "closed",
        ):
            raise RuntimeError(
                f"residue worklist entry {e.get('entry')!r} has invalid "
                f"status {st!r} (expected 'genuinely_missing', "
                f"'blocked_non_effect' or 'closed')"
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
        if st == "blocked_non_effect":
            # Round-56 invariant fields. A blocked_non_effect entry's
            # whole contract is "these Effects ARE shipped; the card is
            # gated by THIS non-Effect path" — both must be recorded
            # for the cron to assert the inverse-of-genuinely_missing
            # invariant (shipped-presence, not absence). A broken entry
            # is itself a staleness signal (same loud-on-broken-input
            # contract as the closed/genuinely_missing checks).
            sv = e.get("shipped_variants")
            if not isinstance(sv, list) or not sv:
                raise RuntimeError(
                    f"blocked_non_effect residue entry "
                    f"{e.get('entry')!r} must record a non-empty "
                    f"'shipped_variants' list (the live Rust Effect:: "
                    f"variant names the card actually needs)"
                )
            blk = e.get("non_effect_blocker")
            if not isinstance(blk, str) or not blk.strip():
                raise RuntimeError(
                    f"blocked_non_effect residue entry "
                    f"{e.get('entry')!r} must record a non-empty "
                    f"'non_effect_blocker' string (the specific "
                    f"non-Effect gate — unbridged event / declined "
                    f"cost-mechanic / unmodeled subsystem / "
                    f"token-registration substrate)"
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

    ``blocked_non_effect`` entries are OUT of scope here — their
    invariant is the *inverse* (assert the named ``shipped_variants``
    stay live, NOT that a claimed Effect stays absent) and is owned by
    ``compute_blocked_non_effect_staleness`` (round-56). They are
    skipped so a ``blocked_non_effect`` entry is never mis-handled by
    the ``genuinely_missing`` or ``closed`` arm.

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
        elif r.status == "closed":  # regression guard the other way
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


# ------------------------------------- round-56 blocked_non_effect invariant
#
# The round-54 lexical check + round-55 structural hardening both
# answer "is this `genuinely_missing` entry's claimed Effect actually
# absent?" — they assert *absence*. A `blocked_non_effect` entry makes
# the OPPOSITE claim: "the Effect arm(s) this card needs ARE shipped;
# the card is gated by a NON-Effect path (an unbridged event like
# BECOMES_TAPPED, a §2-declined cost-mechanic, an unmodeled subsystem,
# a token-registration substrate)". Its invariant is therefore the
# inverse: every name in the entry's `shipped_variants` MUST stay a
# live Rust Effect:: variant (a silent regression to actually-missing
# means the card quietly became a genuine-Effect ask again — that must
# NOT pass silently), and the entry MUST record its specific
# non-Effect blocker. It deliberately does NOT require bridged=True
# (the card is gated precisely because some non-Effect path is
# unbridged — Seedship Agrarian's Effects ARE bridged; BECOMES_TAPPED
# is the gate) and carries no `verified_absent_at_commit` (a
# genuine-absence stamp is meaningless when the Effects are present).
# Same additive never-blocking hook contract as the round-54/55 rows.


def compute_blocked_non_effect_staleness(
    entries: list[dict],
    rust_variants: set[str],
) -> list["Drift"]:
    """Round-56. For every ``blocked_non_effect`` entry emit, as
    applicable:

    * ``residue_blocked_non_effect_regressed`` — one or more names in
      the entry's ``shipped_variants`` is NOT (any longer) a live Rust
      ``Effect::`` variant. The entry asserts those Effects are
      shipped (that is why it is NOT a new-Rust-Effect ask); if one
      silently regressed to actually-missing the card quietly became a
      genuine-Effect ask again and the honest "how far from parity"
      count is wrong — surface it, do not pass silently.
    * ``residue_blocked_non_effect_underspecified`` — the
      ``non_effect_blocker`` is missing/empty. (The
      ``parse_residue_worklist`` schema check already raises loudly on
      this for the committed file; this row is the defensive
      in-function mirror for direct callers / unit inputs that bypass
      the parser, exactly like the round-55 ``residue_unverified``
      row mirrors the absent-stamp condition.)

    Does NOT require ``bridged=True`` and does NOT consult
    ``verified_absent_at_commit`` — see the section comment.
    ``genuinely_missing`` / ``closed`` entries are out of scope here.
    """
    drifts: list[Drift] = []
    for e in entries:
        if e.get("status") != "blocked_non_effect":
            continue
        entry = e.get("entry", "?")
        card = e.get("card", "?")

        blk = e.get("non_effect_blocker")
        if not isinstance(blk, str) or not blk.strip():
            drifts.append(
                Drift(
                    key=f"residue_blocked_non_effect_underspecified::"
                    f"{entry}",
                    label=(
                        f"BLOCKED-NON-EFFECT residue entry '{card}' "
                        f"({entry}) is UNDERSPECIFIED"
                    ),
                    claimed=1,
                    actual=0,
                    hint=(
                        f"it has no non-empty `non_effect_blocker` "
                        f"string. A blocked_non_effect entry MUST "
                        f"record the specific non-Effect gate (an "
                        f"unbridged event such as BECOMES_TAPPED, a "
                        f"§2-declined cost-mechanic, an unmodeled "
                        f"subsystem, or a token-registration "
                        f"substrate) so the residual is actionable on "
                        f"the correct lane (event-bridge / subsystem, "
                        f"NOT new-Rust-Effect). Record it in "
                        f"docs/residue_worklist.json (round-56 schema)."
                    ),
                )
            )

        shipped = e.get("shipped_variants") or []
        missing = [
            v for v in shipped if v not in rust_variants
        ]
        if missing:
            drifts.append(
                Drift(
                    key=f"residue_blocked_non_effect_regressed::{entry}",
                    label=(
                        f"BLOCKED-NON-EFFECT residue entry '{card}' "
                        f"({entry}) REGRESSED"
                    ),
                    claimed=1,
                    actual=0,
                    hint=(
                        f"it is classed `blocked_non_effect` (the "
                        f"Effect arm(s) it needs ARE shipped; the card "
                        f"is gated by `{blk if isinstance(blk, str) else '?'}`"
                        f"), but its declared shipped Rust Effect "
                        f"variant(s) {missing!r} no longer resolve to a "
                        f"live `Effect::` variant — the card quietly "
                        f"became a genuine-Rust-Effect ask again. "
                        f"Re-walk it: either the variant was "
                        f"renamed/removed (fix `shipped_variants` in "
                        f"docs/residue_worklist.json) or the Effect was "
                        f"genuinely lost and the entry must move back "
                        f"to `genuinely_missing` (which would INCREASE "
                        f"the honest 'how far from parity' count). "
                        f"Never-blocking, but a blocked_non_effect "
                        f"regression can no longer pass silently."
                    ),
                )
            )
    return drifts


# --------------------------- round-63 cross-entry card-status consistency
#
# The round-54 lexical / round-55 structural / round-56 blocked_non_effect
# arms each evaluate ONE entry against the live tree in isolation. None of
# them looks ACROSS entries. That leaves a structurally-silent class the
# audit's own round-54 section names as the historical pain: a worklist
# that is *internally self-contradictory* — the same card carried as
# `genuinely_missing` in one row AND reclassified-out (`closed` /
# `blocked_non_effect`) in another. The audit was exactly this for
# Mightform (§2.6 line ~80 recorded its round-31 closure while lines
# ~586/598/984/1048 still said "no Rust arm"); the round-54 re-walk fixed
# the *instances* but no guard was ever added against the *class*
# recurring. It recurs precisely via a same-round fold: an agent closes a
# residue card (adds/flips a `closed` row) but forgets to flip the card's
# still-`genuinely_missing` row — so the card is simultaneously counted in
# the load-bearing "how far from parity" number (= # genuinely_missing
# entries) AND recorded as reclassified-out. Each row passes its own
# in-isolation arm; the contradiction is invisible. This is the exact
# same-round-drift hazard a concurrent Rust-fold round (e.g. a warp
# Phase-1 closing a card) creates.
#
# The guard is the inverse-of-isolation cross-check: group every entry by
# its printed `card` and flag any card whose rows MIX `genuinely_missing`
# with a reclassified-out status (`closed` or `blocked_non_effect`). It is
# deliberately tight — it does NOT flag the *legitimate* multi-row
# patterns this worklist already uses:
#   * two `genuinely_missing` rows for one card = two distinct unshipped
#     arms (Lightstall Inquisitor's CastFromExile + EachOpponentExiles);
#   * two `closed` rows for one card = a kept cron-regression duplicate
#     (Monoist Circuit-Feeder's two closures — and those even differ on
#     the `card` string so they don't collide here anyway).
# Only the load-bearing contradiction — a card asserted BOTH a TRUE
# new-Rust-Effect ask AND reclassified-out — surfaces. Same additive,
# never-blocking post-commit-hook contract as every round-54/55/56 row.


def compute_card_status_consistency(
    entries: list[dict],
) -> list["Drift"]:
    """Round-63. Cross-entry guard: a card whose worklist rows MIX
    ``genuinely_missing`` with a reclassified-out status (``closed`` or
    ``blocked_non_effect``) is internally self-contradictory — it is
    simultaneously counted in the load-bearing honest "how far from
    parity" number AND recorded as reclassified-out. Emits one
    ``residue_card_status_conflict`` row per such card.

    Pure — no live tree, no git, no engine import; a single pass over
    the parsed worklist. Legitimate same-status multi-row cards (two
    genuine arms, two closed rows) are NOT flagged: the guard fires
    ONLY on the genuinely_missing-vs-reclassified-out mix, which is the
    exact internal contradiction the round-54 re-walk had to hand-fix
    and which a same-round fold re-introduces.
    """
    from collections import defaultdict

    rows_by_card: dict[str, list[dict]] = defaultdict(list)
    for e in entries:
        card = e.get("card", "?")
        rows_by_card[card].append(e)

    drifts: list[Drift] = []
    for card, rows in sorted(rows_by_card.items()):
        statuses = {r.get("status") for r in rows}
        if "genuinely_missing" in statuses and statuses & {
            "closed",
            "blocked_non_effect",
        }:
            gm = sorted(
                r.get("entry", "?")
                for r in rows
                if r.get("status") == "genuinely_missing"
            )
            other = sorted(
                f"{r.get('entry', '?')}({r.get('status')})"
                for r in rows
                if r.get("status")
                in ("closed", "blocked_non_effect")
            )
            drifts.append(
                Drift(
                    key=f"residue_card_status_conflict::{card}",
                    label=(
                        f"residue worklist card '{card}' has "
                        f"CONFLICTING entry statuses"
                    ),
                    claimed=1,
                    actual=0,
                    hint=(
                        f"it is carried as `genuinely_missing` in "
                        f"{gm} AND as reclassified-out in {other}. A "
                        f"card cannot be BOTH a TRUE new-Rust-Effect "
                        f"ask (counted in the load-bearing 'how far "
                        f"from parity' number) AND closed / "
                        f"blocked_non_effect at the same time — this "
                        f"is the internal self-contradiction the "
                        f"round-54 re-walk had to hand-fix (the audit's "
                        f"Mightform §2.6-vs-line-586 split), recurring "
                        f"via a same-round fold that closed the card "
                        f"but forgot to flip its still-genuinely_"
                        f"missing row (inflating the honest count). "
                        f"Re-walk this card and reconcile its rows in "
                        f"docs/residue_worklist.json: either flip the "
                        f"genuinely_missing row(s) to match the "
                        f"closure, or (if a distinct arm really is "
                        f"still unshipped) correct the over-eager "
                        f"closure. Never-blocking, but a "
                        f"self-contradictory worklist can no longer "
                        f"pass silently. (Two SAME-status rows — two "
                        f"genuine arms, two closed rows — are "
                        f"legitimate and NOT flagged.)"
                    ),
                )
            )
    return drifts


# ---------------------------------------- round-55 structural anti-staleness
#
# The round-54 resolver above is purely *lexical* (an alias must
# literally BE a live variant). Pulsar Squadron Ace defeated it: the
# Effect shipped r28/29 but the plan-name never lexically matched the
# variant, so a count-blind AND alias-blind gap let a stale entry pass
# both the re-walk and the cron. These two additive signals close that
# — both never-blocking (same hook contract; they only add report
# rows + flip the standalone/CI exit, exactly like the round-54 rows).

CARDS_RS = REPO_ROOT / "rust" / "src" / "cards.rs"
# The two files whose changes can ship/bridge an Effect and thereby
# turn a `genuinely_missing` residue stale — i.e. the EXACT Pulsar
# mechanism (Effect arm in cards.rs + bridge arm in cross_engine.py).
# A `verified_absent_at_commit` older than the last touch of EITHER
# can no longer be trusted. Paths are repo-root-relative POSIX (git's
# pathspec form, stable across OS).
_REVERIFY_TRIGGER_PATHS = (
    "rust/src/cards.rs",
    "src/mtg_bot/parity/cross_engine.py",
)


def _git(*args: str) -> str | None:
    """Run ``git`` in the repo and return stripped stdout, or ``None``
    if git is unavailable / the command fails / there is no history
    (a source tarball or a CI checkout with no ancestry). Git-history
    *absence* is a known non-signal — it must never manufacture a
    false re-verify — so this swallows every failure to ``None`` and
    the caller soft-skips. (Contrast the worklist / sentinel parsers,
    which raise loudly: a broken worklist IS a staleness signal;
    missing optional git history is NOT.)"""
    import subprocess

    try:
        out = subprocess.run(
            ["git", *args],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return out.stdout.strip()


def commits_touching_trigger_paths_since(sha: str) -> int | None:
    """Number of commits AFTER ``sha`` (exclusive, up to ``HEAD``)
    that touched ``rust/src/cards.rs`` or
    ``src/mtg_bot/parity/cross_engine.py`` — the cadence trigger.

    Returns ``None`` (caller soft-skips, never a false re-verify)
    when git or the history for ``sha`` is unavailable: an unknown
    SHA, a shallow / tarball checkout, or no git at all. ``0`` means
    the stamp is still fresh (no relevant code moved since); ``>0``
    means it must be re-verified.
    """
    if not sha or not re.fullmatch(r"[0-9a-fA-F]{7,40}", sha):
        # Not a plausible SHA — let the schema check (which requires
        # the field be present + SHA-shaped) own that error; here we
        # just decline to compute a cadence on garbage.
        return None
    # `sha..HEAD` is empty (rc 0, no output) when sha == HEAD or HEAD
    # is an ancestor of sha; non-empty when commits exist after sha.
    # `--` + the two pathspecs scopes it to the trigger files only.
    out = _git(
        "rev-list",
        "--count",
        f"{sha}..HEAD",
        "--",
        *_REVERIFY_TRIGGER_PATHS,
    )
    if out is None:
        return None
    try:
        return int(out)
    except ValueError:
        return None


def _card_name_variants(name: str) -> set[str]:
    """Surface forms a printed card name can take in a Rust
    doc-comment / bridge-arm comment. Rust doc-comments hyphenate
    multi-word card names (``Pulsar-Squadron-Ace``); apostrophes are
    sometimes dropped (``Meltstriders Resolve``). Keep this small and
    deterministic — over-broad variants would manufacture false
    name hits."""
    base = name.strip()
    out = {
        base,
        base.replace("'", ""),
        base.replace("'", "’"),  # curly apostrophe
        base.replace(" ", "-"),
        base.replace(" ", "-").replace("'", ""),
    }
    return {v for v in out if v}


def split_bridge_arm_blocks(
    cross_engine_path: Path = CROSS_ENGINE,
) -> dict[str, str]:
    """Return ``{kind: arm_block_text}`` for every ``if/elif kind ==
    "..."`` arm inside ``_ta_dict_to_python_effect``. An arm block is
    the text from one ``kind ==`` guard to the next (or the
    PHASE5 sentinel). Comments are KEPT — unlike the count path —
    because a wired arm's doc-comment NAMING the card is precisely the
    non-lexical signal (Pulsar's ``look_at_top_n_reveal_or_counter``
    arm names "Pulsar Squadron Ace" only in its comment). Same scoping
    (def → sentinel) as ``count_bridge_arms`` so the two never
    disagree on which arms exist."""
    text = cross_engine_path.read_text(encoding="utf-8")
    start = text.index("def _ta_dict_to_python_effect")
    end = text.index(
        "# === PHASE5_BRIDGE_ARMS_INSERT_ABOVE_THIS_LINE ===", start
    )
    body = text[start:end]
    guard = re.compile(r'(?:el)?if kind == "([a-z0-9_]+)"\s*:', re.M)
    hits = list(guard.finditer(body))
    blocks: dict[str, str] = {}
    for i, m in enumerate(hits):
        s = m.start()
        e = hits[i + 1].start() if i + 1 < len(hits) else len(body)
        # Several arms can share a kind via separate guards; append so
        # the name scan sees all of them.
        blocks[m.group(1)] = blocks.get(m.group(1), "") + body[s:e]
    return blocks


@dataclass(frozen=True)
class NonLexicalSignal:
    """One non-lexical name-in-bridge-arm hit for a residue card."""

    arm_kind: str  # the bridge arm whose block names the card
    variant: str  # the live Rust Effect:: variant that arm wires
    alias_match: bool  # arm_kind == snake_case(one of the entry aliases)


def find_name_in_wired_bridge_arms(
    entry: dict,
    rust_variants: set[str],
    arm_blocks: dict[str, str],
) -> list[NonLexicalSignal]:
    """The non-lexical Pulsar catch. Scan the card's printed-name
    surface forms against EVERY live bridge-arm block; for each arm
    whose ``kind`` (acronym-aware snake_case) corresponds to a LIVE
    Rust ``Effect::`` variant, a fully-wired end-to-end effect path
    NAMED for that card exists — independent of whatever
    (possibly-wrong) ``aliases`` the entry curated. This is exactly
    the pre-r54 Pulsar shape the lexical resolver was blind to.

    Returns ALL such hits (sorted by arm kind for determinism), each
    flagged with whether the arm also lexically matches an alias
    (sharpens hard-stale vs needs-reverify). Returning every hit —
    not just the first — is what keeps the per-arm ``name_in_arm_ack``
    suppression honest: acking one legitimately-unrelated arm cannot
    mask a *second*, genuinely-stale arm that also names the card.
    Pure text; no engine import, no ``.pyd``."""
    card = entry.get("card", "")
    if not card or card == "?":
        return []
    name_forms = _card_name_variants(card)
    # snake_case of every live variant → its expected bridge kind, so
    # we can map an arm's kind back to a live variant deterministically.
    variant_by_kind = {_camel_to_snake(v): v for v in rust_variants}
    alias_kinds = {
        _camel_to_snake(a) for a in entry.get("aliases", [])
    }
    hits: list[NonLexicalSignal] = []
    for kind in sorted(arm_blocks):
        block = arm_blocks[kind]
        if not any(form in block for form in name_forms):
            continue
        variant = variant_by_kind.get(kind)
        if variant is None:
            # The arm names the card but its kind doesn't correspond
            # to a live variant (a synthetic/composed arm) — not a
            # shipped-Effect signal, skip.
            continue
        hits.append(
            NonLexicalSignal(
                arm_kind=kind,
                variant=variant,
                alias_match=kind in alias_kinds,
            )
        )
    return hits


def compute_structural_residue_staleness(
    entries: list[dict],
    rust_variants: set[str],
    arm_blocks: dict[str, str],
    *,
    git_available: bool = True,
) -> list["Drift"]:
    """Round-55 structural hardening. For every ``genuinely_missing``
    entry emit, as applicable:

    * ``residue_unverified`` — no (or non-SHA-shaped)
      ``verified_absent_at_commit``: the entry was never structurally
      re-verified, so its genuine-absence is an unbacked claim.
    * ``residue_needs_reverify`` — the stamp is stale by the cadence
      rule (≥1 commit since it touched cards.rs / cross_engine.py).
      Soft-skipped when git history is unavailable (never a false
      re-verify).
    * ``residue_stale`` — the card name appears in a LIVE-WIRED bridge
      arm whose ``kind`` ALSO matches one of the entry's own aliases:
      the entry's own data proves it should have lexically resolved →
      hard stale (the round-54 row, reached non-lexically).
    * ``residue_suspect_needs_reverify`` — the card name appears in a
      live-wired bridge arm but NO alias matches (the exact pre-r54
      Pulsar shape): a never-blocking demand for a hand re-walk,
      UNLESS the entry carries ``name_in_arm_ack`` listing that exact
      arm kind (an audited "this is a different ability of the same
      card, hand-re-walked, genuinely absent" acknowledgment). The
      ack is per-arm: a *second*, un-acked arm naming the card — or
      the acked arm's kind changing — still surfaces the row, so the
      ack can never silently mask a future real Pulsar.

    ``closed`` entries are out of scope here — the round-54
    ``compute_residue_staleness`` already regression-guards them.
    """
    drifts: list[Drift] = []
    for e in entries:
        if e.get("status") != "genuinely_missing":
            continue
        entry = e.get("entry", "?")
        card = e.get("card", "?")

        # --- non-lexical name-in-wired-bridge-arm cross-check --------
        # Audited per-arm acks: arms a human re-walked + confirmed are
        # a DIFFERENT ability of the same card (genuinely absent).
        # Normalize to a set of arm kinds; tolerate str or list.
        raw_ack = e.get("name_in_arm_ack")
        if isinstance(raw_ack, str):
            acked_arms = {raw_ack}
        elif isinstance(raw_ack, (list, tuple)):
            acked_arms = {str(a) for a in raw_ack}
        else:
            acked_arms = set()
        for sig in find_name_in_wired_bridge_arms(
            e, rust_variants, arm_blocks
        ):
            if sig.alias_match:
                # Hard stale — the entry's OWN aliases prove the
                # effect shipped + bridged for this card. NEVER
                # suppressible by an ack (an ack is for unrelated
                # arms only; a true shipped effect must hard-fail).
                drifts.append(
                    Drift(
                        key=f"residue_stale::{entry}",
                        label=(
                            f"BLOCKED-RUST-EFFECT residue entry "
                            f"'{card}' ({entry})"
                        ),
                        claimed=0,
                        actual=1,
                        hint=(
                            f"its printed name appears in the LIVE, "
                            f"wired bridge arm `kind == "
                            f'"{sig.arm_kind}"` (→ live '
                            f"`Effect::{sig.variant}`), and that arm's "
                            f"kind matches one of the entry's own "
                            f"aliases — the effect is shipped + bridged "
                            f"end-to-end for this card. Reclassify it "
                            f"out of BLOCKED-RUST-EFFECT in "
                            f"docs/EOE_PROBE_READINESS_AUDIT.md and flip "
                            f"its status to 'closed' in "
                            f"docs/residue_worklist.json. (Non-lexical "
                            f"catch — the round-55 hardening of the "
                            f"round-54 lexical resolver.) NOT "
                            f"ack-suppressible."
                        ),
                    )
                )
                continue
            if sig.arm_kind in acked_arms:
                # Audited: this exact arm was hand-re-walked and is a
                # different ability of the same card — genuinely
                # absent. Suppressed (the ack is the audit trail).
                continue
            drifts.append(
                Drift(
                    key=f"residue_suspect_needs_reverify::{entry}",
                    label=(
                        f"BLOCKED-RUST-EFFECT residue entry "
                        f"'{card}' ({entry}) is Pulsar-shaped "
                        f"SUSPECT"
                    ),
                    claimed=0,
                    actual=1,
                    hint=(
                        f"its printed name appears in the LIVE, "
                        f"wired bridge arm `kind == "
                        f'"{sig.arm_kind}"` (→ live '
                        f"`Effect::{sig.variant}`) but NONE of the "
                        f"entry's curated aliases lexically resolve "
                        f"to it — this is the exact shape that let "
                        f"Pulsar Squadron Ace pass the round-54 "
                        f"resolver + re-walk silently. Hand-re-walk "
                        f"this card. If the named arm is a DIFFERENT "
                        f"ability of the same card (e.g. a mana "
                        f"ability or a bare-shape sibling) and the "
                        f"claimed effect IS genuinely missing, record "
                        f'`"name_in_arm_ack": "{sig.arm_kind}"` on '
                        f"this entry to acknowledge it (per-arm; a "
                        f"new un-acked arm still surfaces). If the "
                        f"claimed effect really did ship, close the "
                        f"entry. Never-blocking, but Pulsar-shaped "
                        f"staleness can no longer pass WITHOUT this "
                        f"prompt or an explicit ack."
                    ),
                )
            )

        # --- verified_absent_at_commit presence + cadence -----------
        sha = e.get("verified_absent_at_commit")
        if not isinstance(sha, str) or not re.fullmatch(
            r"[0-9a-fA-F]{7,40}", sha or ""
        ):
            drifts.append(
                Drift(
                    key=f"residue_unverified::{entry}",
                    label=(
                        f"BLOCKED-RUST-EFFECT residue entry '{card}' "
                        f"({entry}) is UNVERIFIED"
                    ),
                    claimed=1,
                    actual=0,
                    hint=(
                        f"it has no SHA-shaped "
                        f"`verified_absent_at_commit` field. Every "
                        f"`genuinely_missing` entry must record the "
                        f"commit at which its genuine-absence was "
                        f"actually re-verified (live-enum + bridge + "
                        f"name-in-wired-arm). Re-verify the card is "
                        f"absent at HEAD and stamp the SHA in "
                        f"docs/residue_worklist.json (round-55 schema)."
                    ),
                )
            )
            # No usable SHA → no cadence to compute; the unverified
            # row already demands a re-stamp.
            continue

        if not git_available:
            continue
        n_commits = commits_touching_trigger_paths_since(sha)
        if n_commits is None:
            # Git history unavailable for this SHA — soft-skip; a
            # missing-history is a known non-signal, never a false
            # re-verify.
            continue
        if n_commits > 0:
            drifts.append(
                Drift(
                    key=f"residue_needs_reverify::{entry}",
                    label=(
                        f"BLOCKED-RUST-EFFECT residue entry '{card}' "
                        f"({entry}) STAMP IS STALE"
                    ),
                    claimed=1,
                    actual=0,
                    hint=(
                        f"`verified_absent_at_commit` is `{sha}`, but "
                        f"{n_commits} commit(s) since then touched "
                        f"rust/src/cards.rs or "
                        f"src/mtg_bot/parity/cross_engine.py — the two "
                        f"files whose changes can ship/bridge an "
                        f"Effect (the exact Pulsar mechanism). The "
                        f"stamp can no longer be trusted. Re-verify "
                        f"the card is still genuinely absent at HEAD "
                        f"and refresh the SHA (or close it if it "
                        f"shipped). Never-blocking."
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
        # Per-entry residue drifts (round-54 + the round-55 structural
        # rows) are boolean stale/not — the "doc-claimed N, actual M
        # (delta)" framing only makes sense for the numeric count
        # diffs, so render the residue rows as a plain tagged line;
        # the hint carries the full actionable detail in both cases.
        if self.key.startswith(
            ("residue_stale::", "residue_closure_stale::")
        ):
            return f"  - STALE: {self.label} — {self.hint}"
        if self.key.startswith(
            "residue_blocked_non_effect_regressed::"
        ):
            return f"  - REGRESSED: {self.label} — {self.hint}"
        if self.key.startswith("residue_card_status_conflict::"):
            return f"  - CONFLICT: {self.label} — {self.hint}"
        if self.key.startswith(
            (
                "residue_suspect_needs_reverify::",
                "residue_needs_reverify::",
                "residue_unverified::",
                "residue_blocked_non_effect_underspecified::",
            )
        ):
            return f"  - NEEDS RE-VERIFY: {self.label} — {self.hint}"
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
    _RESIDUE_PREFIXES = (
        "residue_stale::",
        "residue_closure_stale::",
        "residue_suspect_needs_reverify::",
        "residue_needs_reverify::",
        "residue_unverified::",
        "residue_blocked_non_effect_regressed::",
        "residue_blocked_non_effect_underspecified::",
        "residue_card_status_conflict::",
    )
    count_drifts = [
        d
        for d in drifts
        if not d.key.startswith(_RESIDUE_PREFIXES)
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
            "(round-54 lexical check + round-55 structural hardening "
            "+ round-56 blocked_non_effect inverse-invariant + "
            "round-63 cross-entry card-status consistency — the "
            "sub-class the count-only cron could not catch, plus the "
            "non-lexical Pulsar-shape catch, plus the shipped-Effect "
            "regression catch for blocked_non_effect entries, plus the "
            "internal-self-contradiction catch (a card both "
            "genuinely_missing AND reclassified-out — the round-54 "
            "Mightform §2.6-vs-line-586 split, recurring via a "
            "same-round fold):"
        )
        lines.extend(d.line() for d in residue_drifts)
    lines.append(
        "  Fix: refresh docs/EOE_PROBE_READINESS_AUDIT.md (headline "
        "table + the STALENESS-SENTINEL block + the per-card residue "
        "rows), sync docs/residue_worklist.json (including the "
        "`verified_absent_at_commit` stamp on every still-genuinely-"
        "missing entry), and, if the Rust variant count moved, "
        "regenerate + commit docs/RUST_EFFECT_COVERAGE.md. This is the "
        "round-34/49/51/53 staleness class the round-19 cron proposal "
        "+ the round-54 per-entry extension + the round-55 structural "
        "(non-lexical) hardening target."
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
    # Round-55 structural (non-lexical) hardening — additive, same
    # never-blocking-hook contract. Catches the Pulsar shape the
    # round-54 *lexical* resolver was blind to (name in a wired bridge
    # arm whose Effect shipped, even when no curated alias matched) +
    # enforces the `verified_absent_at_commit` stamp + its cadence.
    # `git_available` gates ONLY the cadence sub-check (an unknown SHA
    # / tarball checkout soft-skips per-entry inside the function too).
    git_available = _git("rev-parse", "--is-inside-work-tree") == "true"
    arm_blocks = split_bridge_arm_blocks()
    drifts.extend(
        compute_structural_residue_staleness(
            residue_entries,
            rust_variants,
            arm_blocks,
            git_available=git_available,
        )
    )
    # Round-56 blocked_non_effect inverse-invariant — additive, same
    # never-blocking-hook contract. Asserts every `shipped_variants`
    # name on a blocked_non_effect entry is still a live Rust Effect::
    # variant (a silent regression to actually-missing means the card
    # quietly became a genuine-Effect ask again) + that the entry
    # records its specific non-Effect blocker. Pure — reuses the
    # already-collected live `rust_variants` set; no bridge / git.
    drifts.extend(
        compute_blocked_non_effect_staleness(
            residue_entries, rust_variants
        )
    )
    # Round-63 cross-entry card-status consistency — additive, same
    # never-blocking-hook contract. The round-54/55/56 arms each judge
    # ONE entry in isolation; this is the first cross-entry arm. It
    # flags a card carried as `genuinely_missing` in one row AND
    # reclassified-out (`closed` / `blocked_non_effect`) in another —
    # the internal self-contradiction the round-54 re-walk had to
    # hand-fix (the audit's Mightform §2.6-vs-line-586 split), which a
    # same-round fold (closing a card but forgetting to flip its
    # still-genuinely_missing row) silently re-introduces, inflating
    # the load-bearing honest count. Pure — one pass over the parsed
    # worklist; no live tree, no git.
    drifts.extend(
        compute_card_status_consistency(residue_entries)
    )
    print(build_report(drifts), file=stream)
    return 1 if drifts else 0


def main() -> int:
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
