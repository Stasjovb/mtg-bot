"""Dataset 3 — enumerate every place in the Python game loop where state
mutation depends on `random` / RNG / iteration order, plus the SBA
application sequence, trigger ordering, and layered-cache invalidation
sites.

Run with:
    PYTHONPATH=src \\
    ../../mtg-bot/.venv-py313/Scripts/python.exe \\
    scripts/parity_discovery_rng_seams.py

Audit covers ENGINE-side files only: src/mtg_bot/{game,turn,simulate,
actions,legal,combat,mulligan}.py + src/mtg_bot/effects/*.py +
src/mtg_bot/cards/*.py. Skips agents, search, training, recommend,
replay, UI, cli — those are caller-side and their RNG doesn't matter
for state-trajectory parity.
"""

from __future__ import annotations

import io
import re
import sys
from pathlib import Path

# Force UTF-8 stdout so the unicode arrows etc. in the audit don't
# trip Windows cp1252 console encoding.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
else:  # pragma: no cover
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")


ROOT = Path(__file__).resolve().parents[1] / "src" / "mtg_bot"

ENGINE_GLOBS = [
    "game.py", "turn.py", "simulate.py", "actions.py", "legal.py",
    "combat.py", "mulligan.py", "engine.py", "decks.py", "serialize.py",
]

ENGINE_DIRS = ["effects", "cards"]


def collect_engine_files() -> list[Path]:
    files: list[Path] = []
    for name in ENGINE_GLOBS:
        p = ROOT / name
        if p.exists():
            files.append(p)
    for d in ENGINE_DIRS:
        for p in (ROOT / d).rglob("*.py"):
            files.append(p)
    return files


def grep(pattern: str, files: list[Path]) -> list[tuple[Path, int, str]]:
    rx = re.compile(pattern)
    hits = []
    for p in files:
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if rx.search(line):
                hits.append((p, i, line.rstrip()))
    return hits


def relpath(p: Path) -> str:
    return str(p.relative_to(ROOT.parent.parent)).replace("\\", "/")


def main():
    files = collect_engine_files()

    out = []
    out.append("## Dataset 3 — RNG and ordering seam audit")
    out.append("")
    out.append(
        "Audited engine files: `src/mtg_bot/{game,turn,simulate,actions,legal,"
        "combat,mulligan,engine,decks,serialize}.py` + `src/mtg_bot/effects/**/*.py`"
        " + `src/mtg_bot/cards/**/*.py`."
    )
    out.append("")
    out.append(
        "Caller-side files (`agents.py`, `recommend.py`, `replay.py`, "
        "`interactive.py`, `ui.py`, `search/`, `training/`, `cli/`, "
        "`training_ui/`) are NOT in scope — their RNG doesn't affect "
        "state-trajectory parity between the Python and Rust engines as "
        "long as both consume the same `(state, decision)` stream."
    )
    out.append("")

    # ─── RNG call sites ───────────────────────────────────────────────
    out.append("### 3.1 — RNG call sites in the engine")
    out.append("")
    rng_patterns = [
        (r"\bstate\.rng\.", "state.rng — canonical engine RNG (seeded in setup_game)"),
        (r"\brandom\.Random\(", "fresh local random.Random — seeded from caller"),
        (r"\b\w+\.shuffle\(", "shuffle call"),
        (r"\brandom\.shuffle\(", "module-level random.shuffle"),
    ]
    rows: list[tuple[str, int, str]] = []
    for pat, _label in rng_patterns:
        for p, lineno, line in grep(pat, files):
            rows.append((relpath(p), lineno, line.strip()))
    seen = set()
    dedup: list[tuple[str, int, str]] = []
    for r in rows:
        if r not in seen:
            seen.add(r)
            dedup.append(r)
    dedup.sort()

    out.append("| File:line | Line |")
    out.append("|---|---|")
    for path, lineno, line in dedup:
        # Trim very long lines
        s = line if len(line) < 110 else (line[:107] + "...")
        out.append(f"| `{path}:{lineno}` | `{s}` |")
    out.append("")
    out.append(
        "**Seed source**: `simulate.setup_game(...)` calls `state.rng.seed(seed)` "
        "(simulate.py:130). Every in-game RNG draw flows through `state.rng` — "
        "the only setup-only local `rng = random.Random(seed)` (simulate.py:131, "
        "472, 540, 554) is used for deck-shuffle and agent sub-seeds at game "
        "construction, not during play. Clone path (`game.py:3289-3294`) "
        "snapshots `state.rng.getstate()` via `Random.__new__` + `setstate` so "
        "two clones share an RNG history then diverge per-clone — important: a "
        "Rust port must match this same Mersenne-Twister stream for "
        "bit-identical parity, OR the parity gate compares trajectories where "
        "any RNG decision the Rust side makes differs deterministically. "
        "(Easier path: lift every RNG draw to a caller-supplied stream the "
        "test harness can replay, treating `state.rng` as a black-box oracle.)"
    )

    # ─── 3.2 — Order-sensitive iterations ─────────────────────────────
    out.append("")
    out.append("### 3.2 — Order-sensitive iterations (\"first match wins\")")
    out.append("")
    out.append(
        "The engine iterates `state.battlefield` (a plain `list`, append-on-"
        "ETB), `p.hand`, `p.library`, `p.graveyard`, `p.exile` everywhere. "
        "Battlefield order = ETB order (move_off_battlefield removes, "
        "put_into_battlefield appends), so iteration order is "
        "**timestamp-by-ETB**. Sites where iteration order is observable in "
        "state mutation:"
    )
    out.append("")
    notes = [
        ("legal.py:168", "legal_actions iterates p.hand and state.battlefield in zone-insertion order; the emitted CastSpell / ActivateAbility actions are ordered by that walk. Agents that pick the *first* legal in their search may be sensitive."),
        ("legal.py:230 + 246-310", "Hand-zone PlayLand / CastSpell **dedup** is keyed on (printing.name, *modifier_tuple, **kwargs)** via _emit_hand_cast — two copies of the same card in hand collapse to one action. MAINTENANCE INVARIANT noted in source: if hand-zone per-object state is ever added, the dedup key must absorb it. Rust port must match this dedup or legal-action counts diverge."),
        ("actions.py:3346", "dispatch_event snapshots `permanents = list(state.battlefield)` BEFORE walking, so triggers ETBing new permanents don't see them on the same dispatch pass. Order = battlefield iteration order."),
        ("actions.py:3353-3399", "Trigger walk: `for source in permanents: for ability_index, ability in enumerate(source.printing.triggered_abilities)`. **No APNAP sort.** Push order = battlefield iteration order × ability index. Multiple simultaneous triggers land on the stack in that fixed order."),
        ("turn.py:785-792", "`run_delayed_end_step_triggers` documents the stand-in: FIFO walk of `state.delayed_triggers`, pushed onto a LIFO stack → resolves **reverse-scheduling**. Source comment acknowledges APNAP is not modeled (single-controller queue makes it moot today, but the Rust port must match the same FIFO-push / LIFO-resolve ordering)."),
        ("turn.py:1146-1395", "`_state_based_actions_pass` iterates `state.battlefield` for planeswalker bury, legend-rule grouping (by `(controller_id, name)` dict-insertion order), destroyed-creature collection, saga age check, +1/+1 vs -1/-1 cancellation, aura legality, equipment legality. Each pass produces a deterministic list, but the *interleaving* across SBAs and the per-group `keep_id = group[0].id` fallback when agent is None (turn.py:1230) depend on iteration order."),
        ("turn.py:1215-1239", "Legend-rule grouping uses `dict.setdefault((controller_id, name), [])` — Python dict insertion order is preserved (3.7+), so first-ETB-of-the-name comes first. The `keep_id` fallback (no agent) picks `group[0].id` = lowest ETB-timestamp by id; Rust port must match Python's `dict` insertion-order semantics here."),
        ("combat.py", "Eligible-attackers / eligible-blockers walks battlefield order; declared-blockers assignment is a dict in defender-controlled iteration order. Combat damage assignment order = declared-blockers dict order."),
        ("game.py:_compute_effective_pt + _static_bonuses", "Continuous-effect application walks `state.continuous_effects` in timestamp order (allocated by `state.next_timestamp` at `add_continuous_effect`). Multiple sources at the same layer are tie-broken by allocation order = registration order."),
    ]
    for site, note in notes:
        out.append(f"- `src/mtg_bot/{site}` — {note}")

    # ─── 3.3 — SBA application order ─────────────────────────────────
    out.append("")
    out.append("### 3.3 — State-based actions: literal application order")
    out.append("")
    out.append(
        "Single pass (`_state_based_actions_pass` at `src/mtg_bot/turn.py:1146`)"
        " applies the following SBAs **in this order**, then "
        "`state_based_actions` (turn.py:1125) loops until quiescent "
        "(cap `_SBA_MAX_PASSES = 50` at turn.py:1143):"
    )
    out.append("")
    sba_order = [
        ("1. Life ≤ 0 / poison ≥ 10 → has_lost", "turn.py:1186-1194 (CR 704.5a / 704.5c)"),
        ("2. Planeswalker with 0 loyalty → graveyard", "turn.py:1198-1208 (CR 704.5i)"),
        ("3. Legend rule (per (controller_id, name) dict-insertion order; agent.choose_legend_keep or group[0].id fallback)", "turn.py:1215-1239 (CR 704.5j)"),
        ("4. Creature lethal/toughness pass: walks battlefield, picks targets with toughness ≤ 0 (NOT indestructible-saved), then damage ≥ toughness OR marked_lethal (saved by indestructible)", "turn.py:1241-1254 (CR 704.5f/g/h)"),
        ("5. Regeneration shield consumption (CR 701.15) — runs inside the destroyed-pass loop at turn.py:1265-1278; toughness-≤-0 path is NOT regeneratable (gated on `tough > 0` at line 1265)", "turn.py:1265-1278"),
        ("6. Move destroyed creatures → graveyard", "turn.py:1280-1283"),
        ("7. Saga age (lore_counters ≥ chapter_count → sacrifice)", "turn.py:1288-1298 (CR 704.5r audit)"),
        ("8. +1/+1 vs -1/-1 counter cancellation", "turn.py:1308-1317 (CR 704.5r current CR)"),
        ("9. Aura on illegal target → graveyard (walks battlefield; aura_enchant_type ∈ {creature, artifact, land})", "turn.py:1327-1358 (CR 704.5q current CR)"),
        ("10. Equipment on illegal target → unattach (stays on battlefield)", "turn.py:1360-1381 (CR 704.5p audit)"),
        ("11. Alive-count → is_draw / winner_id", "turn.py:1383-1393"),
    ]
    for step, where in sba_order:
        out.append(f"- {step}  *(`src/mtg_bot/{where}`)*")
    out.append("")
    out.append(
        "**Known gaps documented in source** (turn.py:1172-1182): world rule "
        "(704.5o), battle 0 defense (704.5u), 21+ commander damage, and "
        "non-battlefield token scrubbing are NOT implemented. The Rust "
        "port should match the same omissions for parity."
    )
    out.append("")
    out.append(
        "**Loop convergence**: `state_based_actions` re-runs the pass until "
        "no SBA fires; counter cancellation can drive toughness across 0, "
        "which is intentionally handled in the NEXT pass rather than "
        "interleaved (`for _ in range(_SBA_MAX_PASSES)` at turn.py:1136). "
        "Rust port must match the same per-pass / re-loop boundary."
    )

    # ─── 3.4 — Trigger stack ordering ────────────────────────────────
    out.append("")
    out.append("### 3.4 — Trigger queue / stack ordering")
    out.append("")
    out.append(
        "No APNAP sort anywhere in the engine. Triggers are pushed onto "
        "`state.stack` in **the order they're discovered**, then resolved "
        "LIFO via `resolve_top_of_stack`. Discovery order is:"
    )
    out.append("")
    out.append(
        "1. **`dispatch_event` (actions.py:3283)** — walks `permanents = "
        "list(state.battlefield)` (snapshotted before iteration), and for "
        "each source `enumerate(source.printing.triggered_abilities)`. "
        "For each match, calls `push_triggered_ability` "
        "(actions.py:3172-3280) which appends to `state.stack`. "
        "ETB multiplier (`etb_trigger_multiplier`, actions.py:3382) "
        "expands a single match to N pushes (Starfield Vocalist) in a "
        "tight loop — those N pushes are adjacent on the stack."
    )
    out.append(
        "2. **Per-event legacy paths** (`turn._fire_dies_triggers` at "
        "turn.py:661, `combat._fire_*_triggers`, etc.) — same shape: "
        "iterate battlefield, push in order found. Migration is in "
        "progress (predicate-style is the new path; string-key style is "
        "legacy but still alive for some events)."
    )
    out.append(
        "3. **`run_delayed_end_step_triggers` (turn.py:773-840)** — walks "
        "`state.delayed_triggers` in FIFO scheduling order, pushes each "
        "onto the stack. Resolution is LIFO, so most recently scheduled "
        "fires first. Source comment (turn.py:789-792) explicitly notes "
        "this is a deterministic stand-in for APNAP."
    )
    out.append("")
    out.append(
        "**APNAP**: not modeled. Active player's triggers and non-active "
        "players' triggers go on the stack in **dispatch / battlefield "
        "iteration order**, not in APNAP order. Real MTG rule 603.3b "
        "says active player chooses order for their own triggers, then "
        "non-active players in turn order. Our engine's deterministic "
        "stand-in is good enough as long as Python and Rust agree on the "
        "battlefield iteration order. The grep for 'APNAP' returns "
        "exactly 2 hits, both comments in `turn.py:789` and "
        "`effects/generic/graveyard.py:403` — the latter is a comment on "
        "an iteration site where APNAP would matter but doesn't because "
        "the iteration is single-controller."
    )

    # ─── 3.5 — Layered cache ─────────────────────────────────────────
    out.append("")
    out.append("### 3.5 — Layered continuous-effect cache")
    out.append("")
    out.append(
        "Defined at `game.py:2760-2770`:"
    )
    out.append("")
    out.append("```")
    out.append("_layered_cache_version: int = 0")
    out.append("_layer6_wiped_cache: dict[int, tuple[int, bool]]  # source_id -> (version, result)")
    out.append("def _invalidate_layered_cache(self): self._layered_cache_version += 1")
    out.append("```")
    out.append("")
    out.append(
        "**Currently caches only `_source_layer6_wiped`** — the per-source "
        "answer to \"is this source's printed abilities wiped by a "
        "lose-all-abilities layer-6 effect attached to it\". Cache hit "
        "skips the inner doubly-nested `_static_bonuses` walk that "
        "dominates ~5% of a self-play game's profile (game.py:2754-2759 "
        "comment)."
    )
    out.append("")
    out.append("**Invalidation sites** (every write to `state.continuous_effects` must call this):")
    out.append("")
    invalidate_hits = grep(r"_invalidate_layered_cache", files)
    for p, lineno, line in invalidate_hits:
        s = line.strip()
        if len(s) > 100:
            s = s[:97] + "..."
        out.append(f"- `{relpath(p)}:{lineno}` — `{s}`")
    out.append("")
    out.append(
        "**What depends on coherence** (read path): only "
        "`_source_layer6_wiped` consults the cache today (single helper "
        "in `game.py`). The general mechanism is in place for future "
        "memoizations (`_static_bonuses`, `_compute_effective_pt`, "
        "`effective_keywords`) but they read directly from "
        "`state.continuous_effects` today."
    )
    out.append("")
    out.append(
        "**Per-clone semantics** (game.py:2752-2753 comment): cache is "
        "per-state, NOT shared across `state.clone()` calls — clone "
        "starts with `version=0` and empty `_layer6_wiped_cache`. The "
        "Rust port must match this clone-resets-cache behavior or "
        "shared-cache poisoning between MCTS-search branches will cause "
        "subtle wrong-trajectory bugs."
    )
    out.append("")
    out.append(
        "**Cleanup-step invalidation** (turn.py:309): the "
        "`move_off_battlefield` path filters `state.continuous_effects` "
        "to drop entries targeting the leaving object, then calls "
        "`state._invalidate_layered_cache()`. Cleanup-step expiry of "
        "`expires_at=\"cleanup\"` UEOT entries similarly invalidates "
        "(via `run_cleanup_step` at turn.py:969 — see the function "
        "for the literal expiry walk and counter resets)."
    )

    print("\n".join(out))


if __name__ == "__main__":
    main()
