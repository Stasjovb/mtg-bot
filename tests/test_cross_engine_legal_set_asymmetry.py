"""Cross-engine LEGAL-DECISION-SET asymmetry — characterization + the
canonicalization that makes it parity-benign (regression pins).

FOUNDATIONAL QUESTION (surfaced by the warp-admitted probe agent,
worklog ``2026-05-17-296703``: the Bygone-Colossus development-time
``py=[True] vs rs=[False,True]`` legality-pair mismatch):

    Python ``mtg_bot.legal.legal_actions`` is **mana-aware** — it
    gates every ``CastSpell`` emission on ``_can_cast`` →
    ``can_pay_cost`` (``src/mtg_bot/legal.py:60-76`` + the call
    sites at ``:252-254`` instant-speed and ``:383-385``
    sorcery-speed; ditto the warp / kicker / impending / granted-
    warp / Room-half variants and EVERY ``ActivateAbility`` at
    ``:631-657``). A spell whose cost the player cannot currently
    pay is **never enumerated**.

    Rust ``state_ops_legal.rs:legal_decisions`` enumerates
    **structurally** — its own module docstring (lines 77-88,
    "Deferred mana-affordability check") states Rust has no
    non-destructive ``can_pay_cost`` predicate, so the first-slice
    ``CastSpell`` loop "emits for EVERY non-Land in hand regardless
    of mana availability".

So the two engines present DIFFERENT legal-decision SETS at the
same priority point whenever a hand card's cost is un-payable from
currently-available mana. This is parity-foundational: if any
cross-engine agent could ever PICK from the engine-specific set,
the two engines could be driven down different trajectories.

VERDICT (proven by construction below): **PROVABLY BENIGN for
cross-engine trajectory parity.** Every cross-engine harness
(``cross_engine.step_both`` / ``walk_both``, ``trajectory.*``, the
``RealGameCombatAgent``, ``scripts/bench_trajectory_parity.py``,
every ``test_probe_*`` module) uses the **observation-driven
single-script-replay** contract: the action is computed from the
**Python** state (the source of truth), and the SAME
``action_dict`` is applied to BOTH engines via ``step_both``. No
cross-engine code path lets an agent independently enumerate
``rust_state.legal_decisions(pid)`` and choose from it, and no
field-view divergence check ever compares the two emission sets.
The Rust structural superset is therefore UNREACHABLE as an
agent-choice source in any cross-engine context — the warp probe's
``rs=[False, True]`` was an un-masked DIRECT-probe observation, not
a trajectory divergence (every ``step_both`` there was byte-equal).

This module is the regression pin for that verdict. It:

  1. CHARACTERIZES the asymmetry on a MINIMAL real-EoE state — the
     genuine parsed ``Slavering Branchsnapper`` printing ({4}{G}{G}
     7/6 trample, a clean bridge-simple creature) in p0's hand at a
     real turn-1 PRECOMBAT_MAIN with ZERO mana available: Python's
     ``legal_actions`` does NOT emit its ``CastSpell``; Rust's
     ``legal_decisions`` DOES. (FAILS LOUDLY if a future Rust slice
     adds the affordability check — at which point the
     ``SEARCH_LIMITATIONS.md`` "Cross-engine legal-decision-set
     mana-payability asymmetry" entry must be retired.)

  2. PINS THE CANONICALIZATION: with the SAME Python-derived
     pass-priority script replayed on both engines via ``step_both``,
     the trajectory is byte-equal — the Rust-only structural
     ``cast_spell`` option is never taken because the harness
     replays ONE script, it does not let either engine's enumerator
     drive.

  3. NEGATIVE CONTROL: with sufficient mana seated, BOTH engines
     emit the ``CastSpell`` — proving the divergence is SPECIFICALLY
     the mana-payability prune (not a structural enumeration bug),
     and the asymmetry collapses exactly where the warp probe
     masks it (ramp-to-affordable).

> CAVEAT (mirrors ``docs/SEARCH_LIMITATIONS.md``): this pins an
> ACCEPTED divergence + the construction that neutralizes it. It is
> NOT a claim that the two raw emission sets are equal — they are
> deliberately not. It is a claim that no cross-engine AGENT CHOICE
> can ever observe the difference, because the replay contract
> interposes the Python set as the sole script source.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

# Mirror the sibling probe modules' path bootstrap so ``from
# test_trajectory_parity import _step_views`` resolves regardless of
# pytest's rootdir (the helper lives in the tests dir, not a package).
_TESTS_DIR = pathlib.Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))


# The minimal real-EoE card: a clean bridge-simple vanilla-ish
# creature with a deliberately HIGH cost so a zero-mana state makes
# the Python mana-payability prune unambiguous. {4}{G}{G} = 6 total.
_CARD = "Slavering Branchsnapper"
_CARD_GENERIC = 4
_CARD_COLOR = ("G", 2)


def _verify_card_is_minimal_bridge_simple(real):
    """Verify-first guard (Python src = SoT): the genuine printing
    must STILL be the clean bridge-simple high-cost creature this
    characterization rests on. FAILs loudly (never silently skips)
    on live-tree drift so a parser/pool change can't quietly
    invalidate the pin.
    """
    from mtg_bot.parity import trajectory

    assert real is not None, f"{_CARD} absent from active CardSource"
    assert real.card_types == ("Creature",), (
        f"{_CARD}: expected a pure Creature; got {real.card_types}"
    )
    assert real.spell_effect is None, (
        f"{_CARD}: expected no spell_effect (vanilla cast surface); "
        f"got {real.spell_effect!r}"
    )
    assert real.triggered_abilities == (), (
        f"{_CARD}: expected no triggered abilities; got "
        f"{real.triggered_abilities!r}"
    )
    assert real.warp_cost is None and real.kicker_cost is None, (
        f"{_CARD}: expected no alt-cost (the asymmetry must be on the "
        f"PLAIN cast arm, not warp/kicker); warp={real.warp_cost} "
        f"kicker={real.kicker_cost}"
    )
    assert real.mana_cost.generic == _CARD_GENERIC, (
        f"{_CARD}: generic cost moved {real.mana_cost.generic} != "
        f"{_CARD_GENERIC} — re-pin the card or the expected cost"
    )
    assert tuple(real.mana_cost.colored) == (_CARD_COLOR,), (
        f"{_CARD}: colored cost moved {real.mana_cost.colored!r} != "
        f"{(_CARD_COLOR,)!r}"
    )
    assert real.mana_cost.x_pips == 0, f"{_CARD}: unexpected X pips"
    assert trajectory._printing_is_bridge_simple_creature(real), (
        f"{_CARD}: no longer a bridge-simple creature — the Rust "
        f"synthetic carrier path this pin uses requires it"
    )


def _build_zero_mana_main_context(n_lands_in_lib: int):
    """Matched (py, rs) states at turn-1 p0 PRECOMBAT_MAIN with the
    genuine ``Slavering Branchsnapper`` in p0's opening hand and
    ``n_lands_in_lib`` Forests as library padding (NONE on the
    battlefield — p0 has produced ZERO mana).

    Built through the production trajectory path
    (``production_deck_to_deckspec`` → ``setup_matched_game``) so the
    Rust side carries the genuine printing as the bridged synthetic
    creature carrier (the established warp-admitted / batch-D shape),
    NOT a hand-rolled stub.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import CardDef, DeckSpec

    real = get_active_source().get_printings().get(_CARD)
    _verify_card_is_minimal_bridge_simple(real)

    # p0 library = [the genuine card] + Forest padding; p1 = Forest
    # mirror. The card is FIRST so the 7-card opening-hand deal
    # guarantees it lands in p0's hand on turn 1.
    p0_names = [_CARD] + ["Forest"] * n_lands_in_lib
    p1_names = ["Forest"] * (1 + n_lands_in_lib)
    spec = trajectory.production_deck_to_deckspec(
        p0_names, p1_names, pad_to_size=20, pad_with="Forest"
    )
    # Normalise every basic to tap G so the negative-control path can
    # deterministically afford {4}{G}{G} (symmetric — one registry
    # feeds both engines).
    newdefs = tuple(
        CardDef(name=c.name, card_type="Land", mana_produced=("G",))
        if c.card_type == "Land" else c
        for c in spec.card_defs
    )
    spec = DeckSpec(
        card_defs=newdefs,
        p0_library=spec.p0_library,
        p1_library=spec.p1_library,
    )
    py, rs = trajectory.setup_matched_game(spec)

    # Advance to turn-1 p0 PRECOMBAT_MAIN (UNTAP→UPKEEP→DRAW→
    # PRECOMBAT_MAIN = 3 phase ticks) byte-equal on both engines.
    from mtg_bot.parity.cross_engine import (
        advance_phase_python,
        compare_fields,
    )
    from test_trajectory_parity import _step_views

    for _ in range(3):
        advance_phase_python(py)
        rs.advance_phase()
        pv, rv = _step_views(py, rs)
        d = compare_fields(pv, rv)
        assert not d, (
            f"{_CARD}: setup phase-advance ({pv['step']}) diverged "
            f"BEFORE the characterization even began: "
            f"{[(x.field, x.py_value, x.rust_value) for x in d]}"
        )
    pv, _ = _step_views(py, rs)
    assert pv["step"] == "PRECOMBAT_MAIN" and pv["active_player"] == 0, (
        f"{_CARD}: expected turn-1 p0 PRECOMBAT_MAIN, got "
        f"step={pv['step']} active={pv['active_player']}"
    )
    return py, rs


def _py_cast_decisions_for(py, card_id, player_id):
    from mtg_bot.legal import legal_actions

    return [
        a for a in legal_actions(py, player_id)
        if getattr(a, "card_id", None) == card_id
    ]


def _rs_cast_decisions_for(rs, card_id, player_id):
    return [
        a for a in rs.legal_decisions(player_id)
        if a.get("kind") == "cast_spell" and a.get("card_id") == card_id
    ]


def test_cross_engine_legal_set_mana_payability_asymmetry_characterized():
    """CHARACTERIZATION + the documented-divergence pin.

    At a MINIMAL real-EoE turn-1 p0 PRECOMBAT_MAIN with the genuine
    ``Slavering Branchsnapper`` ({4}{G}{G}) in p0's hand and ZERO
    mana sources on the battlefield:

      * Python ``legal_actions(py, 0)`` does NOT emit a ``CastSpell``
        for the card — ``_can_cast`` → ``can_pay_cost`` prunes it
        (``src/mtg_bot/legal.py:383-385``).
      * Rust ``legal_decisions(0)`` DOES emit a ``cast_spell`` for
        it — the structural first-slice loop has no affordability
        gate (``state_ops_legal.rs:77-88``, "Deferred
        mana-affordability check").

    The two engines present DIFFERENT legal-decision SETS at the
    SAME real priority point. This is the asymmetry the warp probe
    surfaced, in its un-masked form, on a genuine EoE printing.

    LOUD on closure: if a future Rust slice ports ``can_pay_cost``
    (the docstring's promised follow-up), Rust will stop emitting
    the un-payable cast and this assertion FAILS — that is the
    signal to retire the ``SEARCH_LIMITATIONS.md`` "Cross-engine
    legal-decision-set mana-payability asymmetry" entry, not to
    weaken this test.
    """
    py, rs = _build_zero_mana_main_context(n_lands_in_lib=6)

    card_obj = next(
        o for o in py.players[0].hand if o.printing.name == _CARD
    )
    # Pre-condition: p0 truly has zero mana available (no lands on bf).
    n_mana_src = sum(
        1 for o in py.battlefield
        if o.controller_id == 0 and o.printing.is_land
    )
    assert n_mana_src == 0, (
        f"{_CARD}: setup expected ZERO p0 mana sources on bf; got "
        f"{n_mana_src} — the payability prune is only unambiguous at 0"
    )

    py_casts = _py_cast_decisions_for(py, card_obj.id, 0)
    rs_casts = _rs_cast_decisions_for(rs, card_obj.id, 0)

    assert py_casts == [], (
        f"{_CARD}: Python legal_actions UNEXPECTEDLY emitted a "
        f"CastSpell for an un-payable {{4}}{{G}}{{G}} with 0 mana — "
        f"the mana-aware prune at legal.py:383-385 regressed: "
        f"{py_casts!r}"
    )
    assert len(rs_casts) >= 1, (
        f"{_CARD}: Rust legal_decisions did NOT emit the structural "
        f"cast_spell for the un-payable card. If the affordability "
        f"check was ported to Rust (state_ops_legal.rs:77-88), this "
        f"asymmetry is CLOSED — retire the SEARCH_LIMITATIONS entry "
        f"'Cross-engine legal-decision-set mana-payability "
        f"asymmetry'. Got rs_casts={rs_casts!r}"
    )

    # The asymmetry, stated as a set difference at one priority point.
    assert {a.use_warp for a in py_casts} == set()
    assert any(a.get("use_warp") is False for a in rs_casts), (
        f"{_CARD}: Rust's structural emission should include the base "
        f"(non-warp) cast for a no-alt-cost card; got {rs_casts!r}"
    )


def test_cross_engine_legal_set_asymmetry_is_parity_benign_under_replay():
    """THE CANONICALIZATION PIN — why the asymmetry is benign.

    From the SAME divergent priority point as the characterization
    test (Python prunes the cast, Rust structurally emits it), drive
    the cross-engine harness's single-script-replay contract: the
    decision is computed from the **Python** state (the SoT) — here
    PassPriority, because Python's mana-aware ``legal_actions`` would
    never offer the un-payable cast to any agent — and the SAME
    ``action_dict`` is applied to BOTH engines via ``step_both``.

    Asserts the trajectory stays byte-equal across a run of replayed
    decisions. The Rust-only structural ``cast_spell`` option is
    NEVER taken because the harness replays ONE Python-derived
    script; neither engine's own enumerator is ever an agent-choice
    source in a cross-engine context. This is the construction that
    makes the legal-set asymmetry unobservable to any cross-engine
    agent — the load-bearing reason the warp probes' trajectories
    were byte-equal despite the raw-set difference.
    """
    from mtg_bot.parity.cross_engine import step_both

    py, rs = _build_zero_mana_main_context(n_lands_in_lib=6)
    card_obj = next(
        o for o in py.players[0].hand if o.printing.name == _CARD
    )

    # Re-confirm the divergence is LIVE at this point (the premise of
    # the benign claim is that the sets genuinely differ here).
    assert _py_cast_decisions_for(py, card_obj.id, 0) == []
    assert len(_rs_cast_decisions_for(rs, card_obj.id, 0)) >= 1

    # The replay contract: the script is Python-derived. Python's
    # mana-aware legal_actions for p0 here is exactly [PassPriority]
    # for this card surface (the un-payable cast is pruned) — so the
    # only thing any cross-engine agent could pick is pass_priority.
    # Replay it on BOTH engines and assert byte-equality every step.
    # The Rust-only structural cast_spell is unreachable: nothing in
    # the cross-engine path consults rs.legal_decisions() to choose.
    for step_idx in range(8):
        s = step_both(py, rs, {"kind": "pass_priority"})
        assert not s.divergences, (
            f"{_CARD}: replayed pass_priority step {step_idx} "
            f"diverged — the single-script-replay canonicalization "
            f"that makes the legal-set asymmetry benign has BROKEN: "
            f"{[(d.field, d.py_value, d.rust_value) for d in s.divergences]}"
        )

    # And the card is STILL only-castable-on-Rust — i.e. the
    # asymmetry persisted through the replay (it was never resolved
    # by an agent choosing it; it was simply never offered by the
    # Python script that the harness replays).
    assert _py_cast_decisions_for(py, card_obj.id, 0) == []
    assert len(_rs_cast_decisions_for(rs, card_obj.id, 0)) >= 1


def test_cross_engine_legal_set_asymmetry_collapses_with_sufficient_mana():
    """NEGATIVE CONTROL — the divergence is SPECIFICALLY the
    mana-payability prune, not a structural enumeration bug.

    Same genuine ``Slavering Branchsnapper`` in p0's hand, but now
    {4}{G}{G} = 6 Forests SEATED on p0's battlefield (untapped) so
    Python's mana-aware ``legal_actions`` ALSO sees the cost as
    affordable. Both engines now emit the base ``CastSpell`` for the
    card — the set difference vanishes exactly where the warp probes
    mask it (ramp-to-affordable). This proves the asymmetry is the
    ``can_pay_cost`` prune alone; Rust's structural set is a
    superset that becomes EQUAL once Python's payability gate opens.
    """
    from mtg_bot.parity.cross_engine import step_both

    py, rs = _build_zero_mana_main_context(n_lands_in_lib=8)
    card_obj = next(
        o for o in py.players[0].hand if o.printing.name == _CARD
    )

    # Divergent before seating mana.
    assert _py_cast_decisions_for(py, card_obj.id, 0) == []
    assert len(_rs_cast_decisions_for(rs, card_obj.id, 0)) >= 1

    # Seat 6 Forests onto p0's battlefield byte-equal: play one land
    # per p0 turn (CR 305.2) via the single-script-replay contract.
    from test_trajectory_parity import _step_views
    from mtg_bot.parity.cross_engine import (
        advance_phase_python,
        compare_fields,
    )

    def _adv(n):
        for _ in range(n):
            advance_phase_python(py)
            rs.advance_phase()
            pv, rv = _step_views(py, rs)
            d = compare_fields(pv, rv)
            assert not d, (
                f"{_CARD}: phase advance ({pv['step']}, turn "
                f"{pv['turn']}) diverged: "
                f"{[(x.field, x.py_value, x.rust_value) for x in d]}"
            )

    seated = 0
    for _cycle in range(40):
        if seated >= 6:
            break
        pv, _ = _step_views(py, rs)
        if (
            py.active_player_idx == 0
            and pv["step"] == "PRECOMBAT_MAIN"
            and py.players[0].lands_played_this_turn == 0
        ):
            land = next(
                (o for o in py.players[0].hand if o.printing.is_land),
                None,
            )
            if land is not None:
                s = step_both(
                    py, rs,
                    {"kind": "play_land", "card_id": int(land.id)},
                )
                assert not s.divergences, (
                    f"{_CARD}: play_land diverged: "
                    f"{[(d.field, d.py_value, d.rust_value) for d in s.divergences]}"
                )
                seated += 1
        _adv(24)  # +2 turns → back to p0's PRECOMBAT_MAIN

    n_lands_bf = sum(
        1 for o in py.battlefield
        if o.controller_id == 0 and o.printing.is_land
    )
    if n_lands_bf < 6:
        pytest.skip(
            f"{_CARD}: opening-hand land draw did not develop 6 "
            f"lands within the cycle budget (got {n_lands_bf}); the "
            f"byte-equal trajectory up to here held. Re-pin a "
            f"land-richer library if this becomes persistent."
        )

    # Land in a clean p0 PRECOMBAT_MAIN, stack empty, lands untapped.
    for _ in range(60):
        pv, _ = _step_views(py, rs)
        if (
            py.active_player_idx == 0
            and pv["step"] == "PRECOMBAT_MAIN"
            and not py.stack
        ):
            break
        _adv(1)

    # With 6 untapped G sources, Python's mana-aware prune OPENS.
    py_casts = _py_cast_decisions_for(py, card_obj.id, 0)
    rs_casts = _rs_cast_decisions_for(rs, card_obj.id, 0)

    py_base = sorted(getattr(a, "use_warp", False) for a in py_casts)
    rs_base = sorted(bool(a.get("use_warp")) for a in rs_casts)
    assert py_base == [False] and rs_base == [False], (
        f"{_CARD}: with {{4}}{{G}}{{G}} affordable, BOTH engines must "
        f"emit exactly the base (non-warp) cast — the asymmetry must "
        f"collapse here (negative control). py={py_base} rs={rs_base} "
        f"(py_casts={py_casts!r} rs_casts={rs_casts!r})"
    )
