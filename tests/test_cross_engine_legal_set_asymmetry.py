"""Cross-engine LEGAL-DECISION-SET mana-payability — the CLOSED
contract (the permanent regression pin for legal_decisions
mana-awareness Slice 1).

HISTORY (the divergence this module used to characterize, now
CLOSED): Python ``mtg_bot.legal.legal_actions`` is mana-aware — it
gates every ``CastSpell`` emission on ``_can_cast`` →
``can_pay_cost`` (``src/mtg_bot/legal.py:60-76`` + the call sites
at ``:252-254`` instant-speed and ``:382-401`` sorcery-speed; the
warp variants; the graveyard-warp loop ``:457-462``; the
exile-recast ``:486-489``; and every ``ActivateAbility``). A spell
whose cost the player cannot currently pay is **never enumerated**.
Rust ``state_ops_legal.rs:legal_decisions`` USED to enumerate
**structurally** — no non-destructive ``can_pay_cost`` predicate
existed, so it emitted a ``cast_spell`` for every non-Land in hand
regardless of mana availability. The two engines presented
DIFFERENT legal-decision SETS at the same priority point whenever a
hand card's cost was un-payable.

That divergence was an ACCEPTED, benign-by-construction asymmetry
ONLY because every cross-engine harness uses the
**observation-driven single-script-replay** contract (the action is
computed from the **Python** SoT state and the SAME ``action_dict``
is replayed on BOTH engines via ``step_both`` — no path sources an
agent choice from ``rust_state.legal_decisions``). At the SoT flip
that contract INVERTS (the NN/MCTS sources decisions from Rust's OWN
enumeration), at which point Rust offering structurally-legal-but-
UNPAYABLE casts becomes a REAL correctness defect (the policy head
would score, and PUCT expand, illegal-by-mana actions).

**CLOSED by legal_decisions mana-awareness Slice 1**
(``docs/RUST_LEGAL_DECISIONS_MANA_AWARENESS_DESIGN.md``): the
non-destructive ``state_ops_mana::can_pay_cost`` predicate (composing
the already-byte-equal-pinned ``pool_can_cover`` +
``auto_tap_headroom_pool``) now gates ALL of Rust's live CastSpell
emission sites (base hand instant/sorcery, their warp variants, the
graveyard-warp loop, the warp exile-recast). On the live cast
surface ``RustCastSpellSet == PythonCastSpellSet`` — Rust no longer
emits an un-payable cast. The change is parity-NEUTRAL under the
current single-script-replay harness (the predicate is at-least-as-
permissive as Python's ``can_pay_cost`` via the same
``auto_tap_headroom_pool``, so every Python-sourced replayed action
is still emitted by post-fix Rust — design doc §4 proof) and
de-risks the flip well before the flip sequence begins.

This module is now the **permanent regression pin for the CLOSED
contract**. It:

  1. PINS THE CLOSED CONTRACT on a MINIMAL real-EoE state — the
     genuine parsed ``Slavering Branchsnapper`` printing ({4}{G}{G}
     7/6 trample, a clean bridge-simple creature) in p0's hand at a
     real turn-1 PRECOMBAT_MAIN with ZERO mana available: **BOTH**
     Python ``legal_actions`` and Rust ``legal_decisions`` now omit
     the un-payable ``CastSpell``. FAILS LOUDLY if Rust regresses to
     structural emission (the mana gate removed / broken).

  2. PINS THE REPLAY CANONICALIZATION still holds: the
     Python-derived pass-priority script replayed on both engines
     via ``step_both`` stays byte-equal, AND the now-equal sets
     persist through the replay.

  3. NEGATIVE CONTROL (over-prune guard): with {4}{G}{G} affordable
     (6 untapped G sources seated) BOTH engines emit exactly the
     base ``CastSpell`` — proving the new predicate is
     at-least-as-permissive as Python's (it does NOT over-prune a
     cast Python offers; a pool-only check would wrongly drop this).

> NOTE (mirrors ``docs/SEARCH_LIMITATIONS.md`` at landing): the
> mana-payability axis on the 5+ live CastSpell sites is CLOSED.
> The residual divergence is the SEPARATE deferred surface:
> target-satisfiability (Slice 2), additional-cost (Slice 3), and
> the non-live alt-cost axes (kicker/impending/granted-warp/Room/X/
> the "Deferred alt-cost flags"). This module pins the mana axis
> only.
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


def test_cross_engine_legal_set_mana_payability_closed_both_omit_unpayable():
    """THE CLOSED CONTRACT pin (was the characterization of the open
    divergence; FLIPPED by legal_decisions mana-awareness Slice 1).

    At a MINIMAL real-EoE turn-1 p0 PRECOMBAT_MAIN with the genuine
    ``Slavering Branchsnapper`` ({4}{G}{G}) in p0's hand and ZERO
    mana sources on the battlefield:

      * Python ``legal_actions(py, 0)`` does NOT emit a ``CastSpell``
        for the card — ``_can_cast`` → ``can_pay_cost`` prunes it
        (``src/mtg_bot/legal.py:382-385``). (Unchanged — Python was
        always mana-aware.)
      * Rust ``legal_decisions(0)`` now ALSO does NOT emit a
        ``cast_spell`` for it — Slice 1's
        ``state_ops_mana::can_pay_cost`` gate prunes the un-payable
        cast at the emission site (was: structural emission with no
        affordability gate).

    BOTH engines now present the SAME (empty-for-this-card)
    legal-decision set at the SAME real priority point. This is the
    CLOSED state of the formerly-ACCEPTED divergence.

    LOUD on regression: if Rust reverts to structural emission (the
    ``can_pay_cost`` gate removed / the ``seen_castspell``
    ordering broken / ``auto_tap_headroom_pool`` mis-credited), Rust
    would re-emit the un-payable cast and this FAILS — that is a
    Slice-1 regression, not a signal to weaken this test.
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
        f"the mana-aware prune at legal.py:382-385 regressed: "
        f"{py_casts!r}"
    )
    assert rs_casts == [], (
        f"{_CARD}: Rust legal_decisions UNEXPECTEDLY emitted a "
        f"cast_spell for an un-payable {{4}}{{G}}{{G}} with 0 mana. "
        f"legal_decisions mana-awareness Slice 1 gates every live "
        f"CastSpell site on state_ops_mana::can_pay_cost; a non-empty "
        f"set here means the gate / seen_castspell ordering / "
        f"auto_tap_headroom_pool regressed. Got rs_casts={rs_casts!r}"
    )

    # The CLOSED contract, stated as set equality at one priority
    # point: BOTH engines emit no cast for the un-payable card.
    assert {a.use_warp for a in py_casts} == set()
    assert {bool(a.get("use_warp")) for a in rs_casts} == set(), (
        f"{_CARD}: post-Slice-1 Rust must emit NO cast (base or warp) "
        f"for the un-payable card; got {rs_casts!r}"
    )


def test_cross_engine_legal_set_closed_replay_stays_byte_equal():
    """THE REPLAY CANONICALIZATION PIN — still holds post-Slice-1.

    From the SAME zero-mana priority point as the closed-contract
    test (now BOTH engines omit the un-payable cast), drive the
    cross-engine harness's single-script-replay contract: the
    decision is computed from the **Python** SoT state (here
    PassPriority — Python's mana-aware ``legal_actions`` offers no
    cast) and the SAME ``action_dict`` is applied to BOTH engines
    via ``step_both``.

    Asserts (a) the trajectory stays byte-equal across a run of
    replayed decisions (the single-script-replay contract is intact —
    the load-bearing reason every cross-engine harness is parity-safe
    pre-flip), AND (b) the now-EQUAL emission sets persist through
    the replay (post-Slice-1 the asymmetry is closed, not merely
    masked: Rust no longer has a structural-only cast to mask). This
    is the parity-NEUTRALITY tripwire from the design doc §4 proof —
    if Slice 1 had over-pruned a Python-sourced action the replay
    would diverge here.
    """
    from mtg_bot.parity.cross_engine import step_both

    py, rs = _build_zero_mana_main_context(n_lands_in_lib=6)
    card_obj = next(
        o for o in py.players[0].hand if o.printing.name == _CARD
    )

    # Post-Slice-1: BOTH engines omit the un-payable cast here (the
    # sets are now EQUAL, not divergent — the closed contract).
    assert _py_cast_decisions_for(py, card_obj.id, 0) == []
    assert _rs_cast_decisions_for(rs, card_obj.id, 0) == []

    # The replay contract: the script is Python-derived. Python's
    # mana-aware legal_actions for p0 here is exactly [PassPriority]
    # for this card surface (the un-payable cast is pruned, as it
    # always was) — so the only thing any cross-engine agent could
    # pick is pass_priority. Replay it on BOTH engines and assert
    # byte-equality every step (the §4 parity-neutrality tripwire:
    # an over-prune of a Python-sourced action would diverge here).
    for step_idx in range(8):
        s = step_both(py, rs, {"kind": "pass_priority"})
        assert not s.divergences, (
            f"{_CARD}: replayed pass_priority step {step_idx} "
            f"diverged — the single-script-replay contract (the §4 "
            f"parity-neutrality proof's tripwire) has BROKEN: "
            f"{[(d.field, d.py_value, d.rust_value) for d in s.divergences]}"
        )

    # The sets stay EQUAL through the replay (the closed contract is
    # stable, not a transient — Rust never re-acquires a structural-
    # only un-payable cast as the game state advances under replay).
    assert _py_cast_decisions_for(py, card_obj.id, 0) == []
    assert _rs_cast_decisions_for(rs, card_obj.id, 0) == []


def test_cross_engine_legal_set_closed_negative_control_both_emit_when_affordable():
    """NEGATIVE CONTROL / over-prune guard — Slice 1's predicate is
    at-least-as-permissive as Python's ``can_pay_cost``.

    Same genuine ``Slavering Branchsnapper`` in p0's hand, but now
    {4}{G}{G} = 6 Forests SEATED on p0's battlefield (untapped) so
    Python's mana-aware ``legal_actions`` sees the cost as
    affordable. Post-Slice-1 BOTH engines emit exactly the base
    ``CastSpell`` for the card. This is the design doc §3.2
    over-prune guard: ``state_ops_mana::can_pay_cost`` reuses
    ``auto_tap_headroom_pool`` (NOT a pool-only check) precisely so a
    {4}{G}{G} cast Python offers when 6 untapped Forests are on the
    battlefield is STILL emitted by Rust — a pool-only gate would
    WRONGLY drop it (the predicate must not be NARROWER than Python's
    or the single-script-replay harness would replay a Python-sourced
    cast Rust no longer considers legal). Confirms Slice 1 closed the
    over-emission without introducing an under-emission.
    """
    from mtg_bot.parity.cross_engine import step_both

    py, rs = _build_zero_mana_main_context(n_lands_in_lib=8)
    card_obj = next(
        o for o in py.players[0].hand if o.printing.name == _CARD
    )

    # Post-Slice-1: BOTH omit before seating mana (the closed
    # contract — was Python-omit / Rust-emit).
    assert _py_cast_decisions_for(py, card_obj.id, 0) == []
    assert _rs_cast_decisions_for(rs, card_obj.id, 0) == []

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


# ---------------------------------------------------------------------------
# C4 re-sweep `cast_spell 76` LEGAL_SET_EQ shape — the END-TO-END
# real-deck closure anchor (B1 keystone closed at scale).
# ---------------------------------------------------------------------------
#
# The synthetic per-axis pins above (Slice 1 mana here, Slice 2 target
# in test_cross_engine_legal_set_target_satisf.py, Slice 3
# additional-cost in test_cross_engine_legal_set_addcost.py) pin each
# C1 prune axis on a minimal side-channel state. This pin anchors the
# EXACT shape the C4 scaled re-sweep surfaced on the live real-deck
# admit surface — the verbatim B1 LEGAL_SET_EQ divergence
# `docs/C4_RESWEEP_EVIDENCE.md:126-147` records:
#
#   [LEGAL_SET_EQ] rust\py=["('cast_spell', 76, False, False, False,
#   False, None)"] py\rust=[] (active_player=1)
#
# 22/300 games in the C4 re-sweep (`c4_resweep.json` @ `e87a6ebe`)
# FAIL_DIVERGENCEd here; archetype 7 / seeds 0 & 3 carried the
# verbatim `cast_spell 76` shape (archetype 8 → `75`, archetype 16 →
# `79` — the SAME C1 over-emission axis, different bridged card id).
# Pre-Slices-2/3 the `rust_shadow` bake-in's LEGAL_SET_EQ assertion
# (`src/mtg_bot/search/rust_shadow.py:_assert_legal_set_eq`) tripped
# on the FIRST priority point where Rust `legal_decisions` offered a
# `cast_spell` Python's `legal_actions` pruned (mana / target /
# additional-cost). Post-Slices-1/2/3 that over-emission is GONE: the
# C1 axis is CLOSED end-to-end on the admitted real-deck surface.
#
# SCOPE (honest, per the B1 brief + `C4_RESWEEP_EVIDENCE.md:142-147`):
# this pin asserts ONLY that the **LEGAL_SET_EQ `cast_spell` C1 axis**
# is closed. The C4 re-sweep ALSO surfaced a SEPARATE, already-tracked
# STATE_EQ divergence — **G7** (`SOT_FLIP_CUTOVER_PLAN.md` §4 ledger
# row G7: Rust resolves `CastSpell` atomically vs Python's
# stack-pending model; the `rust_shadow` STATE_EQ has no post-cast
# stack-drain). G7 is OUT OF SCOPE of B1 (it is the G7-S3+ lane's
# response-window machinery). This pin therefore tolerates a G7
# STATE_EQ trip but FAILS LOUDLY on any LEGAL_SET_EQ trip whose
# divergence carries a `cast_spell` over-emission — i.e. it is the
# permanent regression sentinel for the B1 LEGAL_SET_EQ axis
# specifically, not a "C4 fully clean" claim (the brief explicitly
# states B1 is not expected to make C4/rust_shadow fully clean).


# The exact (archetype, seed) pairs the committed C4 re-sweep recorded
# as FAIL_DIVERGENCE @ LEGAL_SET_EQ with the verbatim `cast_spell N`
# C1 over-emission shape (`c4_resweep.json` @ `e87a6ebe`).
_C4_LEGAL_SET_EQ_CAST_SPELL_REPROS = [
    (7, 0),   # rust\py=["('cast_spell', 76, ...)"] py\rust=[]
    (7, 3),   # rust\py=["('cast_spell', 76, ...)"] py\rust=[]
    (8, 3),   # rust\py=["('cast_spell', 75, ...)"] py\rust=[]
    (16, 3),  # rust\py=["('cast_spell', 79, ...)"] py\rust=[]
]


def test_c4_resweep_cast_spell_legal_set_eq_axis_is_closed_end_to_end():
    """B1 KEYSTONE CLOSURE PIN (end-to-end, real-deck, the C4
    `cast_spell 76` shape).

    Drives the EXACT (archetype, seed) games the C4 scaled re-sweep
    (`docs/C4_RESWEEP_EVIDENCE.md`, `c4_resweep.json` @ `e87a6ebe`)
    recorded as FAIL_DIVERGENCE at LEGAL_SET_EQ with the verbatim
    ``rust\\py=["('cast_spell', 76, False, False, False, False,
    None)"] py\\rust=[]`` C1 over-emission shape, THROUGH the
    role-swapped ``rust_shadow`` bake-in (the SAME loader +
    drive-to-terminal idiom `scripts/bench_trajectory_parity.py`'s
    ``drive_one_game_rust_shadow`` C4 driver uses).

    Post legal_decisions mana-awareness Slices 1+2+3 (mana / target /
    additional-cost — ALL merged to main), Rust ``legal_decisions``
    no longer offers a ``cast_spell`` Python's ``legal_actions``
    prunes. This pin PROVES the B1 LEGAL_SET_EQ C1 axis is CLOSED on
    the admitted real-deck surface: NO ``ShadowDivergenceError`` whose
    tripwire is ``LEGAL_SET_EQ`` and whose detail carries a
    ``cast_spell`` over-emission is raised driving these games.

    HONEST SCOPE (per the B1 brief + C4_RESWEEP_EVIDENCE §142-147): a
    SEPARATE, already-tracked **G7** STATE_EQ divergence (Rust resolves
    ``CastSpell`` atomically vs Python's stack-pending model — owned by
    the G7-S3+ lane, OUT OF SCOPE of B1) may still trip on a game that
    actually casts a spell. This pin TOLERATES a non-LEGAL_SET_EQ trip
    (it is not a "C4 fully clean" assertion — the brief explicitly
    states B1 is not expected to make C4/rust_shadow fully clean) but
    FAILS LOUDLY if the B1 LEGAL_SET_EQ ``cast_spell`` axis ever
    regresses to an over-emission divergence.
    """
    pytest.importorskip("mtg_bot_engine")
    from mtg_bot.parity import trajectory
    from mtg_bot.search.rust_shadow import (
        ShadowDivergenceError,
        drive_shadow_game_to_terminal,
    )

    drove_any = False
    for archetype, seed in _C4_LEGAL_SET_EQ_CAST_SPELL_REPROS:
        try:
            deck_names = trajectory.load_production_deck(
                archetype=archetype
            )
            spec = trajectory.production_deck_to_deckspec(
                deck_names, shared_rng_seed=seed
            )
        except (FileNotFoundError, IndexError, ValueError) as e:
            # The 17lands pool / a bridge-filtered empty library is an
            # environment precondition, not a B1 regression — skip this
            # repro (never silently pass the whole pin).
            pytest.skip(
                f"C4 repro (arch={archetype}, seed={seed}) loader "
                f"precondition unmet ({type(e).__name__}: {e}); the "
                f"B1 LEGAL_SET_EQ axis is unprovable from this env."
            )
        drove_any = True
        try:
            drive_shadow_game_to_terminal(
                spec, seed=seed, max_steps=120
            )
            # Clean run (or a degenerate FAIL_TIMEOUT land-walk that
            # never casts) — the C1 over-emission did NOT trip. Good.
        except ShadowDivergenceError as e:
            # A G7 STATE_EQ (or any non-LEGAL_SET_EQ) trip is the
            # SEPARATE, out-of-B1-scope axis — tolerated here.
            if e.tripwire == "LEGAL_SET_EQ" and "cast_spell" in str(e):
                raise AssertionError(
                    f"B1 REGRESSION: the C4 LEGAL_SET_EQ `cast_spell` "
                    f"C1 over-emission axis re-opened on real-deck "
                    f"(archetype={archetype}, seed={seed}). Rust "
                    f"`legal_decisions` is offering a `cast_spell` "
                    f"Python's `legal_actions` prunes — the exact "
                    f"docs/C4_RESWEEP_EVIDENCE.md:126-147 shape "
                    f"legal_decisions mana-awareness Slices 1/2/3 "
                    f"CLOSED. Tripwire detail: {e}"
                ) from e
            # else: G7 / non-C1 axis — out of B1 scope (the brief's
            # explicit "NOT expected to make C4 fully clean" note).

    assert drove_any, (
        "No C4 `cast_spell` LEGAL_SET_EQ repro was driven — the "
        "real-deck pool was entirely unavailable; the B1 axis is "
        "unprovable from this environment."
    )
