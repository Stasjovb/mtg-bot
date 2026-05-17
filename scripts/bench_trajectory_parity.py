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
    parity failure; just a cap on a long stall.
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
        --archetypes 0-50 --seeds 0-10 --max-turns 25 \\
        --json-out /tmp/parity_bench.json --verbose

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
    if not creatures:
        return None
    creatures.sort(key=lambda o: getattr(o.printing, "cmc", 0) or 0)

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
        s = step_both(py_state, rust_state, cast_action)
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
        "--archetypes", default="0-9",
        help="Archetype range (e.g. '0-50'), comma list ('0,1,2'), or 'all'.",
    )
    p.add_argument(
        "--seeds", default="0-10",
        help="RNG seed range (e.g. '0-10') or comma list.",
    )
    p.add_argument(
        "--max-turns", type=int, default=25,
        help="Game-turn cap (FAIL_TIMEOUT if reached without a loser).",
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
        f"[bench] driving {len(archetypes)} archetype(s) x {len(seeds)} "
        f"seed(s) = {len(archetypes) * len(seeds)} games; strategy="
        f"{args.combat_strategy}, max_turns={args.max_turns}, "
        f"mulligans={args.mulligans}, "
        f"activate_lander_sac={args.activate_lander_sac}\n"
    )

    results: list[GameResult] = []
    total = len(archetypes) * len(seeds)
    n_done = 0
    for arch in archetypes:
        for seed in seeds:
            n_done += 1
            r = drive_one_game(
                archetype=arch,
                seed=seed,
                max_turns=args.max_turns,
                combat_strategy=args.combat_strategy,
                mulligans=args.mulligans,
                verbose=args.verbose,
                activate_lander_sac=args.activate_lander_sac,
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
                "archetypes": args.archetypes,
                "seeds": args.seeds,
                "max_turns": args.max_turns,
                "combat_strategy": args.combat_strategy,
                "mulligans": args.mulligans,
                "activate_lander_sac": args.activate_lander_sac,
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
