"""Trajectory-parity bench: drains the real-divergence backlog by driving
real production-deck mirror games end-to-end on BOTH engines and
comparing per-action field views.

Each game produces a pass/fail signal:

  * **PASS** — the (archetype, seed) trajectory ran to natural game end
    (or hit ``--max-turns``) with byte-equal field views on every action
    + phase advance.
  * **FAIL_DIVERGENCE_AT_TURN_N_ACTION_M** — the first divergence wins;
    the script stops the game and records the diff shape (the per-field
    names that disagreed at that step). These are the new round's
    Rust-slice candidates.
  * **FAIL_TIMEOUT** — ``--max-turns`` reached without a loser. Not a
    parity failure. Round-69 stall-anatomy established that, at the old
    cap of 25, ~2/3 of these were NOT stalls at all — life was still
    dropping every turn and the game would have produced a verdict with
    a larger budget (the bridge-filtered mirror is slow, not frozen).
    Round-70 then supplied per-game ground truth (an escalating-cap
    ladder over the same games) showing the residual that still hit
    cap-60 is ALSO not a floor: 14/14 are near-creatureless deck-out
    races converging by ~turn 108 to a clean PASS — the round-65
    ``<3-copy → never-converter`` causal claim is refuted with data,
    and none of it is the TOKEN_PRINTING_SUBSTRATE Phase-3/5 Rust ask.
    The default cap was raised 25 → 60 (round-69) then 60 → 120
    (round-72) to recover that lost signal. There is currently NO
    genuine permanent FAIL_TIMEOUT floor on the canonical broad grid
    (60/60 reach a real parity verdict at cap-120); a residual
    FAIL_TIMEOUT at cap 120 would be a game even slower than the
    measured ~turn-108 deck-out clock.
  * **ARCHETYPE_FILTERED** — the EoE archetype's deck didn't survive
    the production-deck bridge filter (empty post-filter library on
    either side). No game ran.
  * **FAIL_EXCEPTION** — something else threw; the trajectory.* helper
    or one of the per-step primitives raised. Captured with the
    exception class + message + last action attempted.

The goal is **signal generation**, not perfect runs. Failures are
features — they identify cards / interactions the parity bridge doesn't
model yet so the next Rust-slice gets a concrete candidate.

Run from a worktree::

    PYTHONPATH=src ../../mtg-bot/.venv-py313/Scripts/python.exe \\
        scripts/bench_trajectory_parity.py \\
        --archetypes 0-50 --seeds 0-10 --max-turns 120 \\
        --json-out /tmp/parity_bench.json --verbose

(``--max-turns`` default is 120 as of round-72 — sized to the round-70
per-game ground truth that the canonical broad grid's bridge-filtered
near-creatureless mirrors are deck-out races converging by ~turn 108;
see the argparse help + the round-70/72 entries in
``docs/bench_trajectory_parity_smoke.md``. Round-69 first raised it
25 → 60 (the round-65-grid slowest decisive); round-72 raised it
60 → 120 to recover the residual ~23% that cap-60 still discarded as
FAIL_TIMEOUT on games that were still progressing — broad-sweep
parity-verdict density 76.7% → 100%, ~+3s wall.)

Reuses production helpers:

  * ``mtg_bot.parity.trajectory.setup_matched_game_from_real_decks`` —
    builds the matched DeckSpec + mulligan/draw on both engines.
  * ``mtg_bot.parity.trajectory.drive_combat_phase`` — composes
    DA -> DB -> COMBAT_DAMAGE -> END_OF_COMBAT with per-step parity.
  * ``mtg_bot.parity.trajectory.RealGameCombatAgent`` — configurable
    combat strategy.
  * ``mtg_bot.parity.cross_engine.step_both`` — per-action parity
    comparator (the same machinery the trajectory tests use).
  * ``mtg_bot.parity.cross_engine.advance_phase_python`` /
    ``rust_state.advance_phase()`` — phase plumbing.

This script does NOT modify any production module. It writes nothing
to disk unless ``--json-out`` is supplied.
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import sys
import time
import traceback
from dataclasses import asdict, dataclass, field
from typing import Optional


# --- Path bootstrap: enable `python scripts/bench_trajectory_parity.py`
# from a fresh checkout/worktree without first running `pip install -e .`.
_HERE = pathlib.Path(__file__).resolve().parent
_SRC = _HERE.parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


# ---------------------------------------------------------------------------
# Result records
# ---------------------------------------------------------------------------


@dataclass
class GameResult:
    """One (archetype, seed) game's outcome."""

    archetype: int
    seed: int
    status: str  # PASS / FAIL_DIVERGENCE / FAIL_TIMEOUT / ARCHETYPE_FILTERED / FAIL_EXCEPTION
    turns_played: int = 0
    actions_played: int = 0
    elapsed_seconds: float = 0.0
    # FAIL_DIVERGENCE only: which step / action surfaced the diff + the
    # per-field shape of the divergence.
    divergence_turn: Optional[int] = None
    divergence_action_index: Optional[int] = None
    divergence_kind: Optional[str] = None  # action-dict 'kind' OR "phase_advance"
    divergence_fields: tuple = ()  # tuple of field-name strings
    # FAIL_EXCEPTION only:
    exception_type: Optional[str] = None
    exception_message: Optional[str] = None
    last_action_kind: Optional[str] = None
    # PASS / FAIL_TIMEOUT: who won (None on FAIL_*).
    winner_player_idx: Optional[int] = None
    win_reason: Optional[str] = None


# ---------------------------------------------------------------------------
# Range parsing
# ---------------------------------------------------------------------------


def _parse_range(spec: str, *, upper_cap: Optional[int] = None) -> list[int]:
    """Parse "0-10" / "0,1,2,3" / "all" into a sorted unique int list.

    ``upper_cap`` is used as the inclusive upper bound for ``"all"``
    only — for explicit ranges the caller is on the hook for bounds.
    """
    if spec == "all":
        if upper_cap is None:
            raise ValueError("'all' requires an upper-cap bound at the call site")
        return list(range(upper_cap))
    if "," in spec:
        return sorted({int(p) for p in spec.split(",") if p.strip()})
    if "-" in spec:
        lo, hi = spec.split("-", 1)
        return list(range(int(lo), int(hi) + 1))
    return [int(spec)]


# ---------------------------------------------------------------------------
# Single-game driver
# ---------------------------------------------------------------------------


def _game_over(py_state) -> bool:
    """True when either player has lost (life <= 0, empty library draw,
    10+ poison) per Python's SBA flags."""
    return any(getattr(p, "has_lost", False) for p in py_state.players)


def _winner_and_reason(py_state) -> tuple[Optional[int], Optional[str]]:
    """Return (winning_player_idx, lose_reason_of_loser) when the game
    is over. Returns (None, None) if no loser. Idx is the *winner*."""
    for i, p in enumerate(py_state.players):
        if getattr(p, "has_lost", False):
            return (1 - i, getattr(p, "lost_reason", None))
    return (None, None)


def _try_play_one_land(py_state, rust_state) -> Optional[dict]:
    """Try to play one land for the active player at PRECOMBAT_MAIN.
    Returns the action dict that was applied, or None if no land in
    hand / land already played this turn."""
    from mtg_bot.parity.cross_engine import step_both

    active = py_state.active_player_idx
    p = py_state.players[active]
    if getattr(p, "lands_played_this_turn", 0) >= 1:
        return None
    land_obj = next(
        (o for o in p.hand if o.printing.is_land),
        None,
    )
    if land_obj is None:
        return None
    action = {"kind": "play_land", "card_id": int(land_obj.id)}
    s = step_both(py_state, rust_state, action)
    if s.divergences:
        raise _DivergenceError(action, s.divergences)
    return action


def _try_cast_one_creature(py_state, rust_state) -> Optional[dict]:
    """Try to tap untapped+unsick lands the active player controls to
    cast one castable creature from hand. Returns the cast action dict
    on success, None if nothing could be cast (insufficient mana / no
    creature in hand / etc.).

    Mana-cost handling: for the bridge-filtered production decks the
    only creatures that survive the filter are vanilla creatures, so
    the cost is generic + single-color symbols. We tap untapped+unsick
    lands of the right color first, then enough untapped+unsick
    colorless-eligible lands for the generic cost. If we run out of
    suitable lands, return None (and untap any speculatively-tapped
    lands by RAISING — we don't actually mutate on failure; the loop
    checks counts BEFORE issuing any tap action).
    """
    from mtg_bot.parity.cross_engine import step_both

    active = py_state.active_player_idx
    p = py_state.players[active]

    # Find castable creatures in hand. Try cheapest first so we maximize
    # the chance of getting SOMETHING onto the bf in a tight-mana game.
    creatures = [
        o for o in p.hand
        if "Creature" in o.printing.card_types
    ]
    # Spell-card-bridge lever, Phase 1 (round-70): ALSO admit a pure
    # single-target Instant/Sorcery in hand that survived the loader
    # guardrail (``_printing_is_bridge_simple_spell`` — only such
    # spells reach the bench; every other spell was stripped from the
    # deck) AND for which a legal target exists right now. This is the
    # third lever surface the lever-doc §7 flagged as in-slice (a
    # bench spell-cast loop added BEFORE the Rust lever existed would
    # be unreachable dead code that, if reachable, would inject a
    # guaranteed _DivergenceError on every spell cast — the
    # silent-no-op / no-fallback-hybrid anti-pattern; it is correct
    # and reachable ONLY now that Gate A/B/B'/B'' all land together).
    # The Rust cast-time deterministic-first scan binds the target on
    # the StackItem; Python's ``_select_spell_targets`` binds
    # ``legal_targets[0]`` via the first-legal agent installed below
    # — the campaign-wide no-callback first-legal convention (the
    # ~30 trigger/activated probes + the _PickFirst* shims). The CE5
    # cast-vs-resolve mirror in ``step_both`` drains BOTH stacks
    # before the field-view compare so the post-resolve state
    # (effect applied + spell in graveyard) is what is compared.
    from mtg_bot.parity.trajectory import _printing_is_bridge_simple_spell

    spells: list = []
    for o in p.hand:
        pr = o.printing
        if "Creature" in pr.card_types:
            continue
        if not _printing_is_bridge_simple_spell(pr):
            continue
        se = pr.spell_effect
        if se is None:
            continue
        # Only attempt a cast when a legal target currently exists —
        # a fizzle-on-no-target spell would still resolve byte-equal
        # (both engines no-op), but gating on a live target keeps the
        # bench exercising the load-bearing target-binding path.
        try:
            if not se.legal_targets(py_state, active):
                continue
        except Exception:
            continue
        spells.append(o)
    if not creatures and not spells:
        return None
    # Install the first-legal target agent on BOTH Python players so
    # ``_select_spell_targets`` binds ``legal_targets[0]`` (matching
    # Rust's ``bf_iter_etb_sorted`` first-creature cast-time scan —
    # the equivalence the Tier-A real-EoE probes already proved
    # byte-equal). Idempotent + only installed when a spell may be
    # cast; the creature path never touches ``choose_target`` so
    # pre-lever creature-only bench games are bit-identical.
    if spells:
        from tests.parity._picker_shims import _PickFirstLegalTargetAgent
        for pl in py_state.players:
            if pl.agent is None:
                pl.agent = _PickFirstLegalTargetAgent()
    creatures.sort(key=lambda o: getattr(o.printing, "cmc", 0) or 0)
    spells.sort(key=lambda o: getattr(o.printing, "cmc", 0) or 0)
    # Try creatures first (board presence), then spells. Both share
    # the mana-payment + cast machinery below — a spell's
    # ``mana_cost`` is single-mode (the guardrail rejected X / kicker
    # / warp) so the exact creature mana logic applies unchanged.
    creatures = creatures + spells

    # Untapped+unsick lands controlled by active. Group by mana color.
    # CardDef-backed basic lands produce a single color via the auto-
    # wired {T}: Add C ability; we derive the color from the basic-
    # land subtype (the production-deck filter only admits basic lands
    # via _printing_is_bridge_basic_land — Forest/Island/Plains/
    # Mountain/Swamp/Wastes).
    lands = [
        o for o in py_state.battlefield
        if o.controller_id == active
        and o.printing.is_land
        and not o.tapped
        and not o.summoning_sick
    ]
    color_lands: dict[str, list] = collections.defaultdict(list)
    for ld in lands:
        color = _basic_land_color(ld.printing)
        color_lands[color].append(ld)

    for cre in creatures:
        # Read the creature's mana cost. CardPrinting.mana_cost is a
        # ManaCost dataclass with generic / colored fields; the bridge
        # filter rejects X-cost / hybrid / Phyrexian cards before they
        # reach here, but stay defensive.
        mc = getattr(cre.printing, "mana_cost", None)
        if mc is None:
            continue
        generic = int(getattr(mc, "generic", 0))
        colored_raw = getattr(mc, "colored", ())
        # ``colored`` is an iterable of (color, count) tuples on
        # ManaCost; fall back to parsing a string if a future shape
        # change makes it a plain str.
        if isinstance(colored_raw, str):
            try:
                _g, colored_list = _parse_mana_cost(colored_raw)
            except Exception:
                continue
            colored = colored_list
        else:
            colored = list(colored_raw)
        # Skip uncastable shapes (hybrid / X pips). ManaCost may carry
        # ``x_pips`` and ``hybrid``; both should be empty for vanilla
        # creatures that pass the filter.
        if getattr(mc, "x_pips", 0):
            continue
        if getattr(mc, "hybrid", ()):
            continue
        # Check we have enough lands by color, then enough total for
        # generic. Treat each land as single-use.
        used_ids: set[int] = set()
        pick: list = []
        ok = True
        for color, n in colored:
            avail = [
                ld for ld in color_lands.get(color, [])
                if int(ld.id) not in used_ids
            ]
            if len(avail) < n:
                ok = False
                break
            for ld in avail[:n]:
                used_ids.add(int(ld.id))
                pick.append(ld)
        if not ok:
            continue
        # Generic mana: any untapped land we haven't picked yet.
        remaining = [ld for ld in lands if int(ld.id) not in used_ids]
        if len(remaining) < generic:
            continue
        pick.extend(remaining[:generic])

        # Commit: tap each picked land via activate_ability(ability_index=0)
        # (the auto-wired mana ability), then cast.
        for ld in pick:
            tap_action = {
                "kind": "activate_ability",
                "source_id": int(ld.id),
                "ability_index": 0,
            }
            s = step_both(py_state, rust_state, tap_action)
            if s.divergences:
                raise _DivergenceError(tap_action, s.divergences)
        cast_action = {"kind": "cast_spell", "card_id": int(cre.id)}
        # S7-A2: step_both_drained applies the cast then drains both
        # engines' stacks via real stack-and-priority resolution —
        # the explicit byte-equal replacement for CE5's atomic-
        # reconcile mirror (removed in S7-1). The bench previously
        # relied on CE5's implicit post-cast drain to land the
        # creature on bf; now the drain is explicit at the call site.
        from mtg_bot.parity.cross_engine import step_both_drained
        s = step_both_drained(py_state, rust_state, cast_action)
        if s.divergences:
            raise _DivergenceError(cast_action, s.divergences)
        return cast_action

    return None


_BASIC_LAND_SUBTYPE_TO_COLOR: dict[str, str] = {
    "Forest": "G",
    "Island": "U",
    "Plains": "W",
    "Mountain": "R",
    "Swamp": "B",
    "Wastes": "C",
}


def _basic_land_color(printing) -> str:
    """Return the single mana color a basic-land CardPrinting taps for.

    The production-deck filter (``_printing_is_bridge_basic_land``)
    only admits cards whose basic-land subtype is one of the six in
    :data:`_BASIC_LAND_SUBTYPE_TO_COLOR`. Falls back to ``"C"``
    (colorless / wastes) if the subtype is missing — same default
    as the cross_engine bridge.
    """
    subtypes = getattr(printing, "subtypes", ()) or ()
    for st in subtypes:
        c = _BASIC_LAND_SUBTYPE_TO_COLOR.get(st)
        if c is not None:
            return c
    return "C"


def _parse_mana_cost(s: str) -> tuple[int, list[tuple[str, int]]]:
    """Cheap mana-cost parser mirroring trajectory._parse_mana_cost_string.

    Returns ``(generic, [(color, count), ...])``. Raises ValueError on
    unsupported symbols (X / hybrid / Phyrexian) so the caller can
    treat the creature as uncastable.
    """
    if not s:
        return 0, []
    generic = 0
    colored: dict[str, int] = {}
    i = 0
    while i < len(s):
        if s[i] != "{":
            raise ValueError(f"unexpected char {s[i]!r} at {i} in {s!r}")
        end = s.index("}", i + 1)
        sym = s[i + 1:end]
        if sym.isdigit():
            generic += int(sym)
        elif sym in {"W", "U", "B", "R", "G", "C"}:
            colored[sym] = colored.get(sym, 0) + 1
        else:
            raise ValueError(f"unsupported mana symbol {sym!r} in {s!r}")
        i = end + 1
    return generic, sorted(colored.items())


# ---------------------------------------------------------------------------
# Round-66 N1 — `--require-creatures N` bench precondition
# ---------------------------------------------------------------------------
#
# WHY THIS EXISTS (the round-65 N3 FAIL_TIMEOUT/creature-floor
# finding, merge 6568c346, docs/bench_trajectory_parity_smoke.md
# round-65). The standing ~42-50% FAIL_TIMEOUT floor is the campaign's
# biggest non-divergence signal drag. Round-65 quantified it: the
# CardDef bridge-admit filter collapses each 17lands archetype to ~1-2
# admitted creature copies + ~58 lands → a near-creatureless mirror →
# never reaches lethal → max-turns cap → FAIL_TIMEOUT (zero
# trajectory-divergence signal). Round-65's data showed the
# admitted-copy↔PASS correlation is **monotone and stark**: every
# archetype with ≥5 admitted copies went 4/4 PASS, every 1-copy
# archetype timed out ≥50%; an archetype with `< 3` admitted creature
# copies is a STRUCTURALLY uncloseable mirror — it can never convert,
# so counting it as FAIL_TIMEOUT pollutes the headline metric.
#
# Round-65 established with data that no cheap §2-correct unlock
# exists (the real lever is the multi-round TOKEN_PRINTING_SUBSTRATE
# Phase-3/5 Rust work). The ONLY contained ~1-Python-slice it
# recommended (lever G, r47 option 2) is this: a `--require-creatures
# N` bench precondition (N≈3, justified from r65's
# admitted-copy↔PASS-monotone data) that, when a post-bridge-filter
# deck has `< N` admitted creature copies, marks the game
# **ARCHETYPE_FILTERED** (the EXISTING outcome class for a
# structurally-uncloseable mirror) instead of FAIL_TIMEOUT BEFORE
# running it (skip the wasted play). It adds ZERO coverage but
# separates the structural never-can-close population from genuine
# stalls, so the headline FAIL_TIMEOUT % becomes a true signal-
# coverage metric and the Phase-3/5 substrate's future TIMEOUT→
# PASS/DIV conversion is trackable.
#
# SCOPING DISCIPLINE (deliberately narrow, like the round-59 Lander
# harness above):
#
#   * It is GATED behind an explicit opt-in (the ``require_creatures``
#     parameter / ``--require-creatures N`` CLI flag), DEFAULT-OFF
#     (``None``), so the default bench / production self-play / all
#     existing invocations are byte-for-byte unchanged. This is opt-in
#     instrumentation, NOT a behavior change.
#   * The precondition is a property of the bridge-FILTERED deck — it
#     is engine-agnostic (same admitted card-name list on both
#     engines; the filter is deterministic and shared via the REAL
#     production loader's ``_printing_is_bridge_simple_creature``).
#     Counting it identically on both sides means it can NEVER itself
#     introduce a cross-engine divergence: it gates the game (skip /
#     run), it does NOT alter the trajectory. The game is classified
#     ``ARCHETYPE_FILTERED`` BEFORE either engine's state is even
#     constructed.
#   * It reuses the round-65 scout's EXACT admitted-creature-copy
#     counting (``scout_r64_timeout_creature_floor._admitted_creature
#     _profile``'s body) — the same REAL production loader path
#     (``trajectory._printing_is_bridge_simple_creature``), so the
#     count is EXACTLY what the bench plays with. Not re-derived.


def _count_admitted_creature_copies(deck_names: list[str]) -> int:
    """Round-66: count admitted creature *copies* in one deck.

    Reuses the round-65 scout's EXACT counting logic verbatim
    (``scout_r64_timeout_creature_floor._admitted_creature_profile``):
    for every card name in the raw deck, resolve its printing via the
    active CardSource and count it iff it is a Creature that passes
    the REAL production-deck bridge-admit filter
    (``trajectory._printing_is_bridge_simple_creature``) — i.e. it is
    a creature the bench actually plays (post-filter, pre-pad;
    duplicates preserved, mirroring the bench's pre-pad library).

    This is engine-agnostic (a property of the deterministic
    bridge-filtered deck), so the same count is produced on both
    engines — the precondition can never itself introduce a
    cross-engine divergence.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    src = get_active_source()
    printings = src.get_printings()
    admitted_creature_copies = 0
    for name in deck_names:
        pr = printings.get(name)
        if pr is None:
            continue
        if "Creature" in pr.card_types:
            if trajectory._printing_is_bridge_simple_creature(pr):
                admitted_creature_copies += 1
    return admitted_creature_copies


class _DivergenceError(Exception):
    """Raised from inside the action loop when a step_both reports
    divergences. Carries the action dict + divergence list so the
    outer driver can record the diff shape."""

    def __init__(self, action: dict, divergences) -> None:
        super().__init__(f"divergence on action kind={action.get('kind')!r}")
        self.action = action
        self.divergences = divergences


def _advance_phase_with_compare(py_state, rust_state) -> None:
    """advance_phase_python + rust_state.advance_phase() + field-view
    compare; raises _DivergenceError on disagreement."""
    from mtg_bot.parity.cross_engine import (
        advance_phase_python,
        build_python_field_view,
        compare_fields,
        parity_smoke,
    )

    advance_phase_python(py_state)
    rust_state.advance_phase()
    ps = parity_smoke()
    py_view = build_python_field_view(py_state)
    rust_view = ps._build_field_view(rust_state)
    divs = compare_fields(py_view, rust_view)
    if divs:
        raise _DivergenceError(
            {"kind": "phase_advance"}, divs,
        )


# ---------------------------------------------------------------------------
# Round-59 N3 — review-gated Lander sac-activation harness step
# ---------------------------------------------------------------------------
#
# WHY THIS EXISTS (the round-55→58 standing question). The round-55 N2
# Rust token-cease-to-exist SBA (CR 111.7 — a token leaving the
# battlefield ceases to exist) is byte-pinned by the round-53 GENUINE
# in-test probe
# (``test_phase3a_genuine_real_eoe_galactic_wayfarer_lander_activation``)
# but has NEVER been validated in a real production-deck bench game.
# Round-58 N3's 240-game sweep proved why: the EoE ``Lander`` token is
# a NON-creature ``Token Artifact`` whose ONLY battlefield-exit is its
# ``{2}, Sacrifice: SearchLibraryForBasicLandTapped`` activated
# ability, and the bench emits ``activate_ability`` ONLY for mana-
# tapping lands — so a Lander structurally NEVER leaves the
# battlefield in a bench game (token-LEFT-bf 0/240) and the SBA never
# fires. Round-58 N3 specified the exact minimal unlock: a review-
# gated Lander ``{2},Sac`` activation harness step. This is it.
#
# SCOPING DISCIPLINE (deliberately narrow, NOT a general activator):
#
#   * It activates ONLY a ``Lander`` token's ability_index=0 (the
#     ``{2},Sac:SearchLibraryForBasicLandTapped``). It is NOT a
#     general "bench activates arbitrary abilities" change — that
#     would alter bench combat/mana semantics broadly and is out of
#     scope per round-58 N3's spec + the standing bridge-correctness
#     discipline.
#   * It is GATED behind an explicit opt-in (the ``activate_lander_sac``
#     parameter / ``--activate-lander-sac`` CLI flag), DEFAULT-OFF, so
#     the default bench / production self-play is byte-for-byte
#     unchanged. This is a *validation* harness, not a behavior change.
#   * It drives the IDENTICAL activation on BOTH engines via
#     ``step_both`` (same source id, same ability index, no target —
#     ``SearchLibraryForBasicLandTapped`` is untargeted; the search
#     picks the topmost basic on both engines), exactly mirroring the
#     proven in-test probe's recipe so the post-sac state is a FAIR
#     cross-engine comparison:
#       - ONE shared ``random.Random`` threaded into both engines
#         (``py_state.rng`` + ``rust_state.set_external_rng``) so the
#         round-54 post-search shuffle is byte-equal cross-engine
#         (SEARCH_LIMITATIONS #15 closure recipe). Installed ONCE per
#         game, lazily, only when the first Lander activation happens
#         (so it never perturbs games that never see a Lander).
#       - ``{2}`` colorless mana seeded SYMMETRICALLY into both pools
#         (deterministic — not dependent on which lands auto-tap), the
#         exact recipe
#         ``test_phase3a_genuine_real_eoe_galactic_wayfarer_lander_activation``
#         proves produces a byte-equal post-state.
#   * The Lander's ability goes on the stack (it is NOT a mana
#     ability), so after ``step_both`` BOTH stacks are drained to the
#     pre-activation floor (``resolve_top_of_stack_python`` /
#     ``_rust``) and the field views re-compared — a divergence raises
#     ``_DivergenceError`` exactly like every other bench step.


# Per-game one-shot guard for the shared-rng install (the round-54
# byte-equal post-search-shuffle recipe). Keyed by id(py_state) so a
# fresh game (fresh state object) re-installs; we never want to leak a
# shared stream across games.
_LANDER_SAC_RNG_SEED = 0x5EED59  # round-59 fresh shared MT position


def _try_activate_lander_sac(py_state, rust_state, _rng_installed: set) -> Optional[dict]:
    """Round-59 N3 review-gated harness step (default-off; caller gates).

    If the active player controls a ``Lander`` token on the
    battlefield, deterministically drive its
    ``{2},Sac:SearchLibraryForBasicLandTapped`` activation on BOTH
    engines (identical action via ``step_both``), so the token leaves
    the battlefield and the round-55 token-cease-to-exist SBA actually
    fires in a real game. Returns the activation action dict on
    success, or None when there is no Lander to sac / preconditions
    aren't met.

    Cross-engine fairness (mirrors the proven in-test probe):
      * a single shared ``random.Random`` is installed into both
        engines (once per game, lazily) so the post-search shuffle is
        byte-equal (round-54 SEARCH_LIMITATIONS #15 recipe);
      * ``{2}`` colorless mana is seeded symmetrically into both pools
        so the cost payment is deterministic and identical (not
        dependent on which lands auto-tap).

    Raises ``_DivergenceError`` if the post-activation field views
    diverge — the high-value find this harness exists to surface.
    """
    import random as _random

    from mtg_bot.game import ManaCoin
    from mtg_bot.parity.cross_engine import (
        build_python_field_view,
        compare_fields,
        parity_smoke,
        resolve_top_of_stack_python,
        resolve_top_of_stack_rust,
        step_both,
    )

    active = py_state.active_player_idx
    lander = next(
        (
            o for o in py_state.battlefield
            if o.controller_id == active
            and o.printing.name == "Lander"
            and getattr(o.printing, "is_token", False)
            and not o.tapped
        ),
        None,
    )
    if lander is None:
        return None
    # The Lander's ability is untargeted (library search). Only drive
    # it when a basic land actually exists to be searched on BOTH
    # sides (no-match silently no-ops in the resolve, but driving it
    # then is pointless noise; the byte-equal validation wants the
    # full cost+search+shuffle+token-cease path exercised).
    if not any(
        getattr(c.printing, "is_basic_land", False)
        for c in py_state.players[active].library
    ):
        return None

    # Install the shared post-search-shuffle stream ONCE per game,
    # lazily (only now that a real Lander activation is about to
    # happen) so games that never see a Lander are byte-for-byte
    # unaffected. Two ``random.Random(seed)`` at the same fresh MT
    # position consume the identical ``_randbelow`` sequence -> byte-
    # identical post-search library order (round-54 #15 closure).
    key = id(py_state)
    if key not in _rng_installed:
        py_state.rng = _random.Random(_LANDER_SAC_RNG_SEED)
        rust_state.set_external_rng(_random.Random(_LANDER_SAC_RNG_SEED))
        _rng_installed.add(key)

    # Seed {2} colorless mana symmetrically on both engines — the
    # exact deterministic recipe the in-test probe proves byte-equal.
    py_state.players[active].mana_pool.clear()
    py_state.players[active].mana_pool.append(ManaCoin(color="C"))
    py_state.players[active].mana_pool.append(ManaCoin(color="C"))
    rust_state.empty_all_mana_pools()
    rust_state.add_mana(active, "C", 2)

    lander_id = int(lander.id)
    py_stack_floor = len(getattr(py_state, "stack", ()))
    rust_stack_floor = rust_state.stack_size()
    action = {
        "kind": "activate_ability",
        "source_id": lander_id,
        "ability_index": 0,
    }
    s = step_both(py_state, rust_state, action)
    if s.divergences:
        raise _DivergenceError(action, s.divergences)
    # The Lander's ability is NOT a mana ability — it went on the
    # stack. Drain BOTH engines down to the pre-activation floor and
    # re-compare (the in-test probe's drain pattern; the round-55
    # token-cease-to-exist SBA fires during/after this drain on Rust).
    resolve_top_of_stack_python(py_state, floor=py_stack_floor)
    resolve_top_of_stack_rust(rust_state, floor=rust_stack_floor)
    ps = parity_smoke()
    post_divs = compare_fields(
        build_python_field_view(py_state),
        ps._build_field_view(rust_state),
    )
    if post_divs:
        raise _DivergenceError(
            {"kind": "lander_sac_post_resolve",
             "source_id": lander_id, "ability_index": 0},
            post_divs,
        )
    return action


def drive_one_game(
    archetype: int,
    seed: int,
    max_turns: int,
    combat_strategy: str,
    mulligans: int,
    verbose: bool = False,
    activate_lander_sac: bool = False,
    require_creatures: Optional[int] = None,
) -> GameResult:
    """Drive one (archetype, seed) mirror game end-to-end on both engines.

    ``activate_lander_sac`` (round-59 N3, default-off, review-gated):
    when True, the PRECOMBAT_MAIN driver additionally activates any
    active-player ``Lander`` token's ``{2},Sac`` ability (see
    :func:`_try_activate_lander_sac`). Default-off: the bench /
    production self-play is byte-for-byte unchanged unless explicitly
    opted in (``--activate-lander-sac``). This is the round-58 N3-
    specified minimal unlock for REAL-GAME-validating the round-55
    token-cease-to-exist SBA.

    ``require_creatures`` (round-66 N1, default-off / ``None``): when
    set to an int ``N``, a precondition runs at game start AFTER the
    deck is loaded and the bridge-admit filter is applied but BEFORE
    the matched game state is constructed: if the post-filter deck
    carries ``< N`` admitted creature copies (counted via
    :func:`_count_admitted_creature_copies`, the round-65 scout's
    exact logic), the game is classified ``ARCHETYPE_FILTERED`` (the
    EXISTING outcome class for a structurally-uncloseable mirror) and
    returned WITHOUT running it — so it is NOT counted as
    FAIL_TIMEOUT. This adds zero coverage; it separates the structural
    never-can-close population from genuine stalls so the headline
    FAIL_TIMEOUT % is a true signal-coverage metric (round-65 N3
    finding; docs/bench_trajectory_parity_smoke.md round-65, lever G /
    r47 option 2). Engine-agnostic — the precondition is a property of
    the deterministic bridge-filtered deck, computed identically on
    both engines, so it can never itself introduce a divergence.
    Default-off (``None``): the default bench / production self-play /
    all existing invocations are byte-for-byte unchanged.
    """
    from mtg_bot.parity import trajectory
    from mtg_bot.turn import Step

    result = GameResult(archetype=archetype, seed=seed, status="PASS")
    t0 = time.perf_counter()
    # Per-game guard set for the lazy shared-rng install (see
    # _try_activate_lander_sac). Local to this game so it never leaks
    # the shared stream across games.
    _lander_rng_installed: set = set()

    # ---- Setup ------------------------------------------------------------
    try:
        deck_names = trajectory.load_production_deck(archetype=archetype)
    except (FileNotFoundError, IndexError) as e:
        result.status = "FAIL_EXCEPTION"
        result.exception_type = type(e).__name__
        result.exception_message = str(e)
        result.elapsed_seconds = time.perf_counter() - t0
        return result

    # ---- Round-66 N1: `--require-creatures N` precondition ----------------
    # If opted in and the post-bridge-filter deck carries fewer than N
    # admitted creature copies, this archetype is a structurally
    # uncloseable mirror (round-65 N3: admitted-copy↔PASS is monotone;
    # `< N` admitted copies can never reach lethal before the cap).
    # Classify it as ARCHETYPE_FILTERED (the EXISTING outcome class for
    # a structurally-filtered-out archetype — same column the empty-
    # post-filter-library path already uses) and return WITHOUT running
    # the game, so it is NOT counted as FAIL_TIMEOUT and no play is
    # wasted. The count is engine-agnostic (a property of the
    # deterministic bridge-filtered deck), so this never introduces a
    # cross-engine divergence — it gates the game, it does not alter
    # any trajectory. Default-off (require_creatures is None): this
    # block is inert and the bench is byte-for-byte unchanged.
    if require_creatures is not None:
        n_admitted = _count_admitted_creature_copies(deck_names)
        if n_admitted < require_creatures:
            result.status = "ARCHETYPE_FILTERED"
            result.exception_message = (
                f"require-creatures precondition: {n_admitted} admitted "
                f"creature copies < N={require_creatures} "
                f"(structurally-uncloseable mirror; round-65 N3 — "
                f"reclassified out of FAIL_TIMEOUT, no game run)"
            )
            result.elapsed_seconds = time.perf_counter() - t0
            return result

    # Build agent (covers mulligan + combat). mulligan_agent only
    # supplied when mulligans>0; default no-op otherwise.
    mull_agent = None
    if mulligans > 0:
        if mulligans > 7:
            raise ValueError(f"mulligans={mulligans} out of range [0, 7]")
        mull_agent = trajectory.MulliganDeterministicAgent(
            target_hand_size=7 - mulligans,
        )

    try:
        py_state, rust_state = trajectory.setup_matched_game_from_real_decks(
            deck_names,
            shared_rng_seed=seed,
            mulligans=(mulligans > 0),
            mulligan_agent=mull_agent,
            mulligan_seed=seed,
        )
    except ValueError as e:
        msg = str(e)
        if "empty library" in msg or "production deck filter" in msg:
            result.status = "ARCHETYPE_FILTERED"
            result.exception_message = msg
            result.elapsed_seconds = time.perf_counter() - t0
            return result
        result.status = "FAIL_EXCEPTION"
        result.exception_type = type(e).__name__
        result.exception_message = msg
        result.elapsed_seconds = time.perf_counter() - t0
        return result
    except Exception as e:  # noqa: BLE001 — bench is signal-generation
        result.status = "FAIL_EXCEPTION"
        result.exception_type = type(e).__name__
        result.exception_message = str(e)
        if verbose:
            traceback.print_exc()
        result.elapsed_seconds = time.perf_counter() - t0
        return result

    combat_agent = trajectory.RealGameCombatAgent(strategy=combat_strategy)

    # ---- Action loop ------------------------------------------------------
    action_index = 0
    try:
        # The matched state starts at UNTAP turn 1 with opening hands
        # already drawn. We drive: advance to each phase, do MAIN1 +
        # combat work, advance through cleanup. Repeat until game over
        # OR max_turns reached.
        while not _game_over(py_state):
            if py_state.turn_number > max_turns:
                result.status = "FAIL_TIMEOUT"
                break

            # If we're at MAIN1, do land + cast work.
            if py_state.step == Step.PRECOMBAT_MAIN:
                played_land = _try_play_one_land(py_state, rust_state)
                if played_land is not None:
                    action_index += 1
                # Cast as many creatures as mana allows (greedy cheapest
                # first). Loop until no cast succeeds.
                while True:
                    cast = _try_cast_one_creature(py_state, rust_state)
                    if cast is None:
                        break
                    action_index += 1
                # Round-59 N3 review-gated harness step (default-off).
                # Sac-activate any active-player Lander token so the
                # round-55 token-cease-to-exist SBA fires in a real
                # game. Loops in case multiple Landers are on the bf
                # (one activation per Lander; each search refreshes
                # the library so a subsequent Lander still has a
                # basic to find). No-op when the flag is off.
                if activate_lander_sac:
                    while (
                        _try_activate_lander_sac(
                            py_state, rust_state, _lander_rng_installed,
                        )
                        is not None
                    ):
                        action_index += 1
                _advance_phase_with_compare(py_state, rust_state)  # → BoC
                continue

            # If at DECLARE_ATTACKERS, drive combat phase end-to-end.
            if py_state.step == Step.DECLARE_ATTACKERS:
                # drive_combat_phase walks DA → DB → CD → EoC. It does
                # internal parity asserts; on failure it raises
                # AssertionError. Catch separately so we surface diff
                # shape info if possible (drive_combat_phase doesn't
                # expose divergences in its raise; we record the action
                # kind as combat_phase and an empty field tuple).
                try:
                    trajectory.drive_combat_phase(
                        py_state, rust_state, combat_agent,
                    )
                except AssertionError as e:
                    # Try to extract the divergence list embedded in
                    # the assertion message (drive_combat_phase formats
                    # it as a stringified list of tuples).
                    result.status = "FAIL_DIVERGENCE"
                    result.divergence_turn = py_state.turn_number
                    result.divergence_action_index = action_index
                    result.divergence_kind = "combat_phase"
                    result.divergence_fields = _extract_field_names_from_assertion(
                        str(e),
                    )
                    result.exception_message = str(e)[:500]
                    break
                action_index += 1  # count the whole combat phase as one
                # Now at END_OF_COMBAT. Advance to POSTCOMBAT_MAIN.
                _advance_phase_with_compare(py_state, rust_state)
                continue

            # Other phases: just advance.
            _advance_phase_with_compare(py_state, rust_state)

        if result.status == "PASS" and _game_over(py_state):
            result.winner_player_idx, result.win_reason = _winner_and_reason(py_state)

    except _DivergenceError as e:
        result.status = "FAIL_DIVERGENCE"
        result.divergence_turn = py_state.turn_number
        result.divergence_action_index = action_index
        result.divergence_kind = e.action.get("kind", "?")
        result.divergence_fields = tuple(
            d.field for d in e.divergences
        )
        result.exception_message = (
            "diff shape: "
            + ", ".join(
                f"{d.field}(py={d.py_value!r}, rust={d.rust_value!r})"
                for d in e.divergences[:3]
            )
        )[:500]
    except Exception as e:  # noqa: BLE001
        result.status = "FAIL_EXCEPTION"
        result.exception_type = type(e).__name__
        result.exception_message = str(e)[:500]
        if verbose:
            traceback.print_exc()

    result.turns_played = py_state.turn_number
    result.actions_played = action_index
    result.elapsed_seconds = time.perf_counter() - t0
    return result


def drive_one_game_rust_shadow(
    archetype: int,
    seed: int,
    max_steps: int,
    require_creatures: Optional[int] = None,
    verbose: bool = False,
) -> GameResult:
    """C4 re-sweep driver: drive one (archetype, seed) REAL
    production-deck game THROUGH the role-swapped ``rust_shadow``
    bake-in (``ShadowCheckedRustAdapter``: Rust drives, Python
    shadow-checks in lock-step with the 4-assertion tripwire) instead
    of the ``step_both`` Python-drives/Rust-mirrors comparator.

    This is the Step-0 / SOT_FLIP_CUTOVER_PLAN C4 evidence harness:
    the SAME real-deck loader path (``load_production_deck`` +
    ``production_deck_to_deckspec`` — the bench's
    ``setup_matched_game_from_real_decks`` two-step expansion) and the
    SAME ``require_creatures`` engine-agnostic precondition / outcome
    classes as :func:`drive_one_game`, but the decision flow runs
    through ``rust_shadow.drive_shadow_game_to_terminal`` (the EXACT
    idiom ``tests/test_rust_shadow_bakein.py`` drives the bake-in
    with — a deterministic seeded ``random.Random`` over
    ``legal_decisions()`` applied via ``apply`` until terminal), just
    longer + on a real DeckSpec.

    A ``ShadowDivergenceError`` is recorded as FAIL_DIVERGENCE with the
    tripwire name as ``divergence_kind`` and the tripwire detail in
    ``exception_message`` (the honest bake-in fail signal — NO silent
    fallback to ``step_both``, NO skipped game:
    ``feedback_no_fallback_hybrids`` / ``feedback_silent_noop``). A
    clean run to the natural terminal is PASS. Reuses the existing
    ``GameResult`` / ``aggregate`` / ``render_summary`` / ``--json-out``
    machinery so the report shape is byte-consistent with round-76.
    """
    from mtg_bot.parity import trajectory
    from mtg_bot.search.rust_shadow import drive_shadow_game_to_terminal

    result = GameResult(archetype=archetype, seed=seed, status="PASS")
    t0 = time.perf_counter()

    # ---- Setup: identical real-deck loader path to drive_one_game ----
    try:
        deck_names = trajectory.load_production_deck(archetype=archetype)
    except (FileNotFoundError, IndexError) as e:
        result.status = "FAIL_EXCEPTION"
        result.exception_type = type(e).__name__
        result.exception_message = str(e)
        result.elapsed_seconds = time.perf_counter() - t0
        return result

    # ---- Round-66 N1 `--require-creatures N` precondition ------------
    # Engine-agnostic (a property of the deterministic bridge-filtered
    # deck), so it classifies identically to the step_both path and can
    # never itself introduce a divergence. Default-off.
    if require_creatures is not None:
        n_admitted = _count_admitted_creature_copies(deck_names)
        if n_admitted < require_creatures:
            result.status = "ARCHETYPE_FILTERED"
            result.exception_message = (
                f"require-creatures precondition: {n_admitted} admitted "
                f"creature copies < N={require_creatures} "
                f"(structurally-uncloseable mirror; round-65 N3 — "
                f"reclassified out of FAIL_TIMEOUT, no game run)"
            )
            result.elapsed_seconds = time.perf_counter() - t0
            return result

    # ---- Build the SAME real-deck DeckSpec the bench plays -----------
    # This is exactly setup_matched_game_from_real_decks's first step
    # (production_deck_to_deckspec); the bake-in factory
    # (build_shadow_checked_adapter) owns the matched-state /
    # mulligan-free construction from the spec. shared_rng_seed=seed
    # gives the same per-seed library permutation the step_both path
    # uses (DeckSpec.shared_rng_seed). An empty post-filter library
    # raises ValueError -> ARCHETYPE_FILTERED, same as the step_both
    # path's setup_matched_game_from_real_decks failure mode.
    try:
        spec = trajectory.production_deck_to_deckspec(
            deck_names, shared_rng_seed=seed,
        )
    except ValueError as e:
        msg = str(e)
        if "empty library" in msg or "production deck filter" in msg:
            result.status = "ARCHETYPE_FILTERED"
            result.exception_message = msg
            result.elapsed_seconds = time.perf_counter() - t0
            return result
        result.status = "FAIL_EXCEPTION"
        result.exception_type = type(e).__name__
        result.exception_message = msg
        result.elapsed_seconds = time.perf_counter() - t0
        return result
    except Exception as e:  # noqa: BLE001 — bench is signal-generation
        result.status = "FAIL_EXCEPTION"
        result.exception_type = type(e).__name__
        result.exception_message = str(e)
        if verbose:
            traceback.print_exc()
        result.elapsed_seconds = time.perf_counter() - t0
        return result

    # ---- Drive THROUGH the rust_shadow bake-in to terminal ----------
    outcome = drive_shadow_game_to_terminal(
        spec, seed=seed, max_steps=max_steps,
    )
    result.status = outcome.status
    result.actions_played = outcome.steps
    # turns_played has no clean cross-engine analog under the
    # Rust-driver bake-in (the adapter abstracts the phase loop);
    # the step count is the load-bearing progress metric here.
    result.turns_played = 0
    if outcome.status == "PASS":
        result.winner_player_idx = outcome.winner
        result.win_reason = "terminal"
    elif outcome.status == "FAIL_DIVERGENCE":
        # The tripwire name is the divergence "kind"; the field-shape
        # histogram key becomes "<tripwire>::<detail-head>" so the
        # aggregate() shape histogram buckets by tripwire + the
        # divergence head (consistent with the step_both kind::fields
        # shape).
        result.divergence_kind = outcome.divergence_kind
        detail = outcome.divergence_detail or ""
        # Use the leading bracketed/parenthesized shape token as the
        # field-shape so distinct divergence shapes bucket separately
        # while staying compact in render_summary.
        result.divergence_fields = (_shadow_shape_token(detail),)
        result.exception_message = detail[:500]
    elif outcome.status == "FAIL_EXCEPTION":
        result.exception_type = outcome.exception_type
        result.exception_message = (outcome.exception_message or "")[:500]
    # FAIL_TIMEOUT / ARCHETYPE_FILTERED carry no extra fields.

    result.elapsed_seconds = time.perf_counter() - t0
    return result


def _shadow_shape_token(detail: str) -> str:
    """Extract a compact, stable divergence-shape token from a
    ShadowDivergenceError detail string for the shape histogram.

    The detail looks like ``rust\\py=[...] py\\rust=[...]`` (LEGAL_SET)
    or ``compare_fields divergences (...): [('field', ...)]`` (STATE)
    or ``Python apply_action raised on ...`` (NO_RAISE). We want a
    short key that groups the SAME divergence shape together without
    the per-game ids. Best-effort; falls back to the detail head."""
    import re

    # STATE_EQ: pull the diverging field names.
    fields = re.findall(r"\('([^']+)',", detail)
    if fields:
        return "fields:" + ",".join(sorted(set(fields)))
    # LEGAL_SET_EQ: the canon kinds that differ (strip numeric ids).
    kinds = re.findall(r"'\(?'?([a-z_]+)'", detail)
    if kinds:
        return "legalset:" + ",".join(sorted(set(kinds)))
    # NO_RAISE / other: the exception class head.
    m = re.search(r"raised on .*?: (\w+):", detail)
    if m:
        return "noraise:" + m.group(1)
    return detail[:60]


def _extract_field_names_from_assertion(msg: str) -> tuple:
    """drive_combat_phase formats its raise as a stringified list of
    ``(field, py_val, rust_val, known_gap)`` tuples. Pull the field
    names out for the divergence-shape histogram. Best-effort; if the
    parse fails we return an empty tuple."""
    import re

    # Each tuple's first element is the field name string in single quotes.
    matches = re.findall(r"\('([^']+)',", msg)
    return tuple(matches)


# ---------------------------------------------------------------------------
# Aggregation + reporting
# ---------------------------------------------------------------------------


@dataclass
class BenchSummary:
    total_games: int = 0
    passes: int = 0
    fail_divergence: int = 0
    fail_timeout: int = 0
    archetype_filtered: int = 0
    fail_exception: int = 0
    total_elapsed_seconds: float = 0.0
    # divergence-shape -> count (the field-name tuple is the histogram key)
    divergence_shape_histogram: dict = field(default_factory=dict)
    # archetype -> {status: count}
    per_archetype: dict = field(default_factory=dict)


def aggregate(results: list[GameResult]) -> BenchSummary:
    s = BenchSummary(total_games=len(results))
    per_arch: dict[int, dict[str, int]] = collections.defaultdict(
        lambda: collections.defaultdict(int)
    )
    shape_hist: dict[str, int] = collections.defaultdict(int)
    for r in results:
        s.total_elapsed_seconds += r.elapsed_seconds
        per_arch[r.archetype][r.status] += 1
        if r.status == "PASS":
            s.passes += 1
        elif r.status == "FAIL_DIVERGENCE":
            s.fail_divergence += 1
            shape_key = (
                f"{r.divergence_kind}::"
                + ",".join(r.divergence_fields)
            )
            shape_hist[shape_key] += 1
        elif r.status == "FAIL_TIMEOUT":
            s.fail_timeout += 1
        elif r.status == "ARCHETYPE_FILTERED":
            s.archetype_filtered += 1
        elif r.status == "FAIL_EXCEPTION":
            s.fail_exception += 1
    s.divergence_shape_histogram = dict(
        sorted(shape_hist.items(), key=lambda kv: -kv[1])
    )
    s.per_archetype = {a: dict(d) for a, d in sorted(per_arch.items())}
    return s


def render_summary(summary: BenchSummary) -> str:
    lines = [
        "=" * 72,
        "trajectory-parity bench summary",
        "=" * 72,
        f"  total games:        {summary.total_games}",
        f"  PASS:               {summary.passes}",
        f"  FAIL_DIVERGENCE:    {summary.fail_divergence}",
        f"  FAIL_TIMEOUT:       {summary.fail_timeout}",
        f"  ARCHETYPE_FILTERED: {summary.archetype_filtered}",
        f"  FAIL_EXCEPTION:     {summary.fail_exception}",
        f"  wall time:          {summary.total_elapsed_seconds:.2f}s",
        "",
    ]
    if summary.divergence_shape_histogram:
        lines.append("divergence shapes (most common first):")
        for shape, count in summary.divergence_shape_histogram.items():
            lines.append(f"  {count:4d}  {shape}")
        lines.append("")
    if summary.per_archetype:
        lines.append("per-archetype breakdown (first 50 rows):")
        for arch, counts in list(summary.per_archetype.items())[:50]:
            counts_str = ", ".join(f"{k}={v}" for k, v in counts.items())
            lines.append(f"  archetype {arch:3d}: {counts_str}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="bench_trajectory_parity",
        description=(
            "Run production-deck mirror games end-to-end on Python + "
            "Rust engines; surface real-divergence backlog signal."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--decks", default="17lands",
        help=(
            "Deck source. Today only '17lands' is supported "
            "(data/17lands/eoe_decks.json.gz)."
        ),
    )
    p.add_argument(
        "--driver", default="step_both",
        choices=("step_both", "rust_shadow"),
        help=(
            "Per-game driver. 'step_both' (DEFAULT, byte-unchanged): "
            "the Python-drives / Rust-mirrors comparator the bench has "
            "always used. 'rust_shadow': drive each REAL production-deck "
            "game THROUGH the role-swapped ShadowCheckedRustAdapter "
            "bake-in (Rust drives, Python shadow-checks in lock-step "
            "with the 4-assertion tripwire; a ShadowDivergenceError is "
            "FAIL_DIVERGENCE with the tripwire name as the divergence "
            "kind; a clean run to the natural terminal is PASS). This "
            "is the SOT_FLIP_CUTOVER_PLAN C4 / Step-0 evidence harness "
            "— the round-76-class grid re-run through the flip-readiness "
            "gate on the flip-candidate commit. Default-off: the "
            "step_both path is byte-for-byte unchanged unless this is "
            "explicitly set to rust_shadow (feedback_no_fallback_"
            "hybrids: NO silent fallback to step_both on a divergence)."
        ),
    )
    p.add_argument(
        "--shadow-max-steps", type=int, default=4000,
        help=(
            "rust_shadow driver only: per-game decision-step upper "
            "bound (FAIL_TIMEOUT if reached without a terminal). Pure "
            "upper bound on the otherwise-deterministic decision loop "
            "— parity-safe exactly like --max-turns (raising it can "
            "ONLY convert TIMEOUT -> PASS/DIVERGENCE). Default 4000 is "
            "the same generous cap the G6 closure pin uses; a real "
            "60-card mirror's deck-out tail converges well within it."
        ),
    )
    p.add_argument(
        "--archetypes", default="0-9",
        help="Archetype range (e.g. '0-50'), comma list ('0,1,2'), or 'all'.",
    )
    p.add_argument(
        "--seeds", default="0-10",
        help="RNG seed range (e.g. '0-10') or comma list.",
    )
    p.add_argument(
        # Default raised 60 → 120 (round-72: applies the round-70
        # FAIL_TIMEOUT-floor characterization, docs/
        # bench_trajectory_parity_smoke.md round-70/72). Round-69 first
        # raised the cap 25 → 60 on per-turn stall-anatomy of the
        # round-65 grid (~67% of cap-25 FAIL_TIMEOUTs were
        # `budget_progressing`, not frozen — the bridge-filtered mirror
        # is SLOW, not stalled), recovering ~30 pts of broad-sweep
        # signal. Round-70 then supplied the missing PER-GAME ground
        # truth for the residual ~23% that still hit exactly cap-60 on
        # the canonical broad grid (archetypes 0-29 × seeds 0-1): an
        # escalating-cap ladder (60→90→120→160→220) over the SAME games
        # via the bench's own per-step primitives proved 14/14 of the
        # residual are `budget_recoverable` (0 `genuine_stalemate`, 0
        # round-65 `structural_never_converter`). They are
        # near-creatureless deck-out RACES: 12/14 converge at ~turn 108
        # with both players still at 20 life (library-exhaustion wins,
        # zero damage ever dealt — the round-69 life-only classifier's
        # `no_board`/`frozen_stalemate` labels were FALSE POSITIVES);
        # the other 2 are a genuine lone-1/1 slow damage clock. ALL 14
        # converge to a clean PASS by cap-120 (caps 160/220 recover +0
        # — 120 is the true ceiling). Real-bench cross-check: the
        # canonical broad grid goes FAIL_TIMEOUT 14 (23.3%) → 0 (0.0%),
        # parity verdicts 46/60 → 60/60, all 14 converts → PASS (0 →
        # FAIL_DIVERGENCE), wall +3s (81s → 84.3s, well inside the
        # ≤3-min sweep budget). The round-65 `<3 admitted-copy → never
        # converges` causal claim is REFUTED with data (all 14 carry
        # <3 copies, 10 carry zero — `<3` predicts "slow deck-out
        # race", NOT "never converges"); the residual is the SAME
        # budget lever as round-69, under-corrected by ~2×, NOT the
        # round-65 TOKEN_PRINTING_SUBSTRATE Phase-3/5 Rust ask.
        # PARITY-SAFE (identical to the round-69 proof): `max_turns` is
        # a pure upper bound on an otherwise-deterministic loop (checked
        # only as `if turn_number > max_turns`), so raising it can ONLY
        # convert FAIL_TIMEOUT → PASS/DIVERGENCE; it can NEVER alter a
        # game that already ended before the old cap (empirically
        # verified per-game: 0 trajectory-shift / 0 divergence /
        # 0 exception across all 60 canonical-grid games × all 5 cap
        # rungs 60→90→120→160→220). Every gate test passes max_turns
        # explicitly (MT local constant / per-test value), so no pinned
        # trajectory depends on this argparse default.
        "--max-turns", type=int, default=120,
        help="Game-turn cap (FAIL_TIMEOUT if reached without a loser). "
             "Default 120: sized to the round-70 per-game ground truth "
             "(the canonical broad grid's bridge-filtered "
             "near-creatureless mirrors are deck-out races converging "
             "by ~turn 108; 60/60 reach a real parity verdict at "
             "cap-120, +0 beyond — raised from round-69's 60, which "
             "was sized only to the round-65 grid's slowest decisive). "
             "Raising the cap is parity-safe — it is a pure upper bound "
             "and never alters a game that ended before the old cap.",
    )
    p.add_argument(
        "--combat-strategy", default="attack_all",
        choices=sorted({
            "attack_all",
            "attack_all_block_smallest",
            "no_attack",
            "attack_with_unblockable_creatures_only",
            "block_with_largest_able",
            "optimal_no_loss_attack",
        }),
        help="RealGameCombatAgent strategy.",
    )
    p.add_argument(
        "--mulligans", type=int, default=0,
        help="N: mulligan to (7 - N). 0 means keep openers.",
    )
    p.add_argument(
        "--activate-lander-sac", action="store_true",
        help=(
            "ROUND-59 N3 review-gated VALIDATION harness step "
            "(DEFAULT-OFF). When set, the PRECOMBAT_MAIN driver "
            "additionally sac-activates any active-player Lander "
            "token's {2},Sac:SearchLibraryForBasicLandTapped ability "
            "(identical action on BOTH engines, shared post-search "
            "shuffle rng, {2} seeded symmetrically) so the round-55 "
            "token-cease-to-exist SBA (CR 111.7) actually fires in a "
            "real production-deck game. NARROW: only the Lander sac "
            "ability, NOT a general bench activator. Off by default — "
            "the bench / production self-play is byte-for-byte "
            "unchanged unless this is explicitly passed."
        ),
    )
    p.add_argument(
        "--require-creatures", type=int, default=None, metavar="N",
        help=(
            "ROUND-66 N1 reporting-honesty precondition (DEFAULT-OFF). "
            "When set to an int N, any (archetype, seed) game whose "
            "post-bridge-filter deck carries < N admitted creature "
            "copies is classified ARCHETYPE_FILTERED (the existing "
            "outcome class for a structurally-uncloseable mirror) "
            "BEFORE running it, instead of being run and timing out as "
            "FAIL_TIMEOUT. N~3 is the round-65 N3 data-driven floor "
            "(admitted-copy-to-PASS is monotone; <3 admitted copies "
            "can never reach lethal before the cap). Adds ZERO "
            "coverage - it separates the structural never-can-close "
            "population from genuine stalls so the headline "
            "FAIL_TIMEOUT pct is a true signal-coverage metric. "
            "Engine-agnostic (a property "
            "of the deterministic bridge-filtered deck) so it never "
            "introduces a divergence. Off by default — the default "
            "bench / production self-play / all existing invocations "
            "are byte-for-byte unchanged unless this is explicitly "
            "passed."
        ),
    )
    p.add_argument(
        "--json-out", default=None,
        help="Optional path to dump structured results as JSON.",
    )
    p.add_argument(
        "--verbose", action="store_true",
        help="Per-game progress logging on stderr.",
    )
    p.add_argument(
        "--archetypes-upper-cap", type=int, default=5000,
        help=(
            "Upper bound used when --archetypes is 'all' (the EoE pool "
            "carries ~5000 decks)."
        ),
    )
    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    if args.decks != "17lands":
        sys.stderr.write(
            f"unsupported --decks={args.decks!r}; only '17lands' today.\n"
        )
        return 2

    archetypes = _parse_range(args.archetypes, upper_cap=args.archetypes_upper_cap)
    seeds = _parse_range(args.seeds)

    sys.stderr.write(
        f"[bench] driver={args.driver}; driving {len(archetypes)} "
        f"archetype(s) x {len(seeds)} seed(s) = "
        f"{len(archetypes) * len(seeds)} games; strategy="
        f"{args.combat_strategy}, max_turns={args.max_turns}, "
        f"shadow_max_steps={args.shadow_max_steps}, "
        f"mulligans={args.mulligans}, "
        f"activate_lander_sac={args.activate_lander_sac}, "
        f"require_creatures={args.require_creatures}\n"
    )

    results: list[GameResult] = []
    total = len(archetypes) * len(seeds)
    n_done = 0
    for arch in archetypes:
        for seed in seeds:
            n_done += 1
            if args.driver == "rust_shadow":
                r = drive_one_game_rust_shadow(
                    archetype=arch,
                    seed=seed,
                    max_steps=args.shadow_max_steps,
                    require_creatures=args.require_creatures,
                    verbose=args.verbose,
                )
            else:
                r = drive_one_game(
                    archetype=arch,
                    seed=seed,
                    max_turns=args.max_turns,
                    combat_strategy=args.combat_strategy,
                    mulligans=args.mulligans,
                    verbose=args.verbose,
                    activate_lander_sac=args.activate_lander_sac,
                    require_creatures=args.require_creatures,
                )
            results.append(r)
            if args.verbose:
                tag = r.status
                if r.status == "FAIL_DIVERGENCE":
                    tag += (
                        f" t{r.divergence_turn} a{r.divergence_action_index}"
                        f" kind={r.divergence_kind} "
                        f"fields={','.join(r.divergence_fields) or '?'}"
                    )
                sys.stderr.write(
                    f"[bench] {n_done:>4d}/{total} arch={arch:3d} "
                    f"seed={seed:2d}  {tag}  "
                    f"({r.turns_played}t/{r.actions_played}a "
                    f"in {r.elapsed_seconds:.2f}s)\n"
                )

    summary = aggregate(results)
    sys.stdout.write(render_summary(summary))
    sys.stdout.write("\n")

    if args.json_out:
        payload = {
            "config": {
                "decks": args.decks,
                "driver": args.driver,
                "shadow_max_steps": args.shadow_max_steps,
                "archetypes": args.archetypes,
                "seeds": args.seeds,
                "max_turns": args.max_turns,
                "combat_strategy": args.combat_strategy,
                "mulligans": args.mulligans,
                "activate_lander_sac": args.activate_lander_sac,
                "require_creatures": args.require_creatures,
            },
            "summary": asdict(summary),
            "games": [asdict(r) for r in results],
        }
        # tuple → list for JSON; asdict already does this recursively but
        # divergence_fields is a tuple field which asdict preserves.
        for g in payload["games"]:
            g["divergence_fields"] = list(g["divergence_fields"])
        pathlib.Path(args.json_out).write_text(
            json.dumps(payload, indent=2, default=str), encoding="utf-8",
        )
        sys.stderr.write(f"[bench] wrote {args.json_out}\n")

    # Exit nonzero ONLY on outright script failure (zero games run).
    # Per-game FAIL_DIVERGENCE / FAIL_EXCEPTION are EXPECTED signal —
    # the script returns 0 so the operator can grep the summary and
    # JSON for divergence shapes regardless of failure counts.
    if summary.total_games == 0:
        sys.stderr.write("[bench] ERROR: zero games ran\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
