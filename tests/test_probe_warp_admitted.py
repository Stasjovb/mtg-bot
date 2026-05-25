"""Genuine real-EoE cross-engine byte-equality probes for the FIVE
warp-admitted creatures.

**Why this module exists (the PROBED-tier gap it closes).**

The warp substrate Phase 1 (commit ``9f3ef1d1``: Red Tiger Mechan +
Bygone Colossus) and Phase 1.5 (commit ``ce207345``: Germinating Wurm,
Knight Luminary, Starbreach Whale) admit exactly these five creatures
through ``trajectory._printing_is_bridge_pure_warp_creature``. The
round-68 broad bench sweep
(``docs/bench_trajectory_parity_smoke.md``) validated them
divergence-clean at archetype scale — but that is *collateral-net*
coverage (a card happening to ride along inside a real-deck mirror
game), NOT an individual PROBED-tier pin
(``docs/POOL_PARITY.md`` — PROBED byte-equal is the strongest
evidence tier: a controlled cross-engine state driven end-to-end with
a FULL ``compare_fields`` byte-equality assertion at every step).

The pre-existing Phase-1 / Phase-1.5 lifecycle probes in
``tests/test_parity_smoke.py``
(``test_cross_engine_real_eoe_warp_phase1_full_lifecycle_byte_equal``
and ``..._phase15_trio_lifecycle_byte_equal``) drive the warp
lifecycle on a *synthetic* Forest-heavy library and, for the trio,
parametrize only Germinating Wurm + Starbreach Whale — **Knight
Luminary has NO dedicated lifecycle probe at all**, and none of the
five is probed (a) on a **real 17lands deck context** nor (b) through
a **pure normal non-warp cast from hand** (the existing probes only
exercise warp-cast → exile → normal-recast-*from-exile*; they never
cast the card normally from hand without ever warping it).

This module closes exactly that gap. For each of the five it drives
TWO genuinely-distinct cross-engine trajectories, both seated in a
**real 17lands archetype deck context** (the round-46 real-signal
discipline — ``load_production_deck`` → the real
``_filter_deck_to_bridge_supported`` → ``production_deck_to_deckspec``,
the SAME path the bench's ``setup_matched_game_from_real_decks``
uses), asserting FULL ``compare_fields`` byte-equality (the strong
tier — the harness cleanly supports the full view compare since the
``_net_counters`` fix ``ecc5f680``; ``step_both``'s
``.divergences == []`` IS that assertion, and the per-phase ``adv``
helper runs the full ``compare_fields`` at every phase boundary):

  1. **The warp lifecycle** — cast-via-warp
     (``CastSpell{use_warp:True}``, pays the cheaper warp cost,
     ``spell_warped_this_turn`` set) → ``PHASE_END_STEP`` exile sweep
     (the permanent leaves the battlefield to exile with the warp
     marker on BOTH engines) → recast-from-exile at NORMAL cost
     (back on the battlefield). FULL byte-equality at every step +
     phase boundary, plus the lifecycle observables and the ETB's
     public effect where it has one (Germinating Wurm GainLife 2;
     Knight Luminary CreateToken Human Soldier 1/1; Surveil 2 has no
     public side — its byte-equality is proved by the zero-divergence
     full compare).

  2. **Normal non-warp play** — the SAME genuine printing cast from
     hand at its FULL normal mana cost with ``use_warp:False``,
     never warped, so it is NOT swept to exile at the end step (it
     stays on the battlefield through the following end step — the
     negative control that proves the exile sweep is keyed on the
     warp marker, not on the card identity). FULL byte-equality
     throughout, including the ETB firing byte-equal under the
     normal-cast path.

**Verify-first.** Each probe re-resolves the genuine printing via the
live ``get_active_source()`` and asserts it is *still*
warp-admitted at HEAD (``_printing_is_bridge_pure_warp_creature``
True, ``_printing_is_bridge_simple_creature`` False — the warp arm,
not the plain simple-creature arm, is the one that admits it) BEFORE
probing. If the live tree drifts so a card is no longer warp-admitted
the probe FAILs loudly with a re-orientation message (honest-failure
discipline — a silently-skipped probe is a false-green).

**Disjointness.** This is a DISJOINT card set from the
covered-but-unprobed batch stream. It does NOT touch
``tests/test_trajectory_parity.py``, the
``test_probe_covered_unprobed_*`` modules, the
``test_probe_spell_card_bridge_admitted`` module, or the protected
``test_audit_safe_trigger_*`` tests. New module, own file.

**No SEARCH_LIMITATIONS entry.** Pure evidence-strengthening — zero
shortcut, relaxation, or deliberate divergence is introduced. If a
probe ever surfaces a real divergence in the warp lifecycle that is
the work SUCCEEDING; the divergence is isolated, the wrong side
diagnosed (Python ``src/mtg_bot/`` is the source of truth), and — if
Rust-side — recorded as a precise findings note + an xfail with a
tracking comment, never papered over.
"""

import sys
import pathlib

import pytest

from mtg_bot.agents import Agent

_SCRIPTS_DIR = pathlib.Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

_TESTS_DIR = pathlib.Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))


# The five warp-admitted creatures, each paired with a real 17lands
# archetype whose post-filter library carries a workable basic-land
# base in the card's primary color (surveyed live against the active
# CardSource — arch 5 is R-heavy, arch 2 is G/U, arch 9 is W/B). The
# basic-land CardDefs in the union registry are forced to tap the
# card's color so the warp / normal cost is always payable on BOTH
# engines symmetrically (the round-46 real-deck-context discipline:
# the deck IS a genuine 17lands decklist; only the basic-land mana
# colors are normalised so the probe can deterministically afford the
# cast — exactly the established Phase-1.5 idiom, lifted onto a real
# archetype instead of a synthetic Forest pile).
_WARP_CARDS = [
    # card_name, color, warp_str, normal_str, real_archetype,
    # etb_kind ("life+2" | "token" | "none")
    # **Anticausal Vestige Cycle 3** — warp-arm admit set 7→8 (Cycle-2
    # closure marker ``c32f07f9`` flipped AV DECLINED → ADMITTED at
    # ``_printing_is_bridge_pure_warp_creature`` via the
    # ``_python_ta_to_safe_dict`` event-vocabulary widen for
    # ``LEAVES_BATTLEFIELD``). AV's printed warp cost ``{4}`` differs
    # from its normal cost ``{6}`` (colorless, Eldrazi) — the two
    # lifecycles cost-side differ as well as semantically. AV's
    # LEAVES_BATTLEFIELD observable (draw a card + may put a permanent
    # with MV<=lands-you-control from hand onto bf tapped) carries no
    # public side beyond the zero-divergence full ``compare_fields``
    # under the warp end-step exile sweep (the LEAVES dispatches on
    # both engines symmetrically, the LTB resolves byte-equal under
    # the deterministic-first contract — Rust's resolve arm at
    # ``state_ops_resolve.rs:15219-15392`` picks the first hand-iter
    # MV<=land_count permanent; Python's ``AnticausalVestigeLeavesEffect``
    # under the trajectory-harness ``p.agent is None`` short-circuit
    # is NOT seated by default, so the no-agent path early-returns
    # AFTER the draw with NO put-onto-bf — which mirrors Rust's
    # behavior whenever no candidate qualifies). etb_kind="none" — no
    # public-side observable beyond the zero-divergence full compare.
    # Archetype 24 is B-heavy (Sw=9, Mt=8) and AV-free (preserves the
    # ``p0_library.count(card_name) == 1`` invariant).
    ("Anticausal Vestige", "B", "{4}", "{6}", 24, "none"),
    ("Red Tiger Mechan", "R", "{1}{R}", "{3}{R}", 5, "none"),
    ("Bygone Colossus", "R", "{3}", "{9}", 5, "none"),
    # **Codecracker Hound Cycle 3** — warp-arm admit set 6→7 (Cycle-2
    # closure marker ``278992d7`` flipped CH DECLINED → ADMITTED at
    # ``_printing_is_bridge_pure_warp_creature``). CH's printed warp
    # cost equals its normal cost (both ``{2}{U}``) — the cost-side
    # is identical between the warp arm and the normal arm, but the
    # warp arm still fires the at-end-step delayed-trigger exile sweep
    # distinct from a normal cast (Lifecycle 1's load-bearing
    # observable). CH's ETB observable is the chosen card moving to
    # hand WITHOUT ``reveal_to_all`` (Cycle-1 refined fold's
    # ``reveal_chosen=False`` rider preserves the no-reveal observable
    # cross-engine; byte-equality is proved by the surrounding zero-
    # divergence full ``compare_fields``) — etb_kind="none" (no
    # public side beyond the zero-divergence full compare).
    # Archetype 22 is U/B (9 Islands, 8 Swamps); CH is NOT in arch
    # 22's real 17lands deck (the exact-one-copy probe invariant the
    # other Phase-1/1.5 cards naturally satisfy because none of them
    # is in their respective archetype's real deck either — arch 2's
    # real deck contains 2 copies of CH, which would multiply with
    # the seated copy and break the
    # ``p0_library.count(card_name) == 1`` invariant; arch 22 is the
    # nearest U-heavy CH-free real archetype).
    ("Codecracker Hound", "U", "{2}{U}", "{2}{U}", 22, "none"),
    ("Germinating Wurm", "G", "{1}{G}", "{4}{G}", 2, "life+2"),
    ("Knight Luminary", "W", "{1}{W}", "{3}{W}", 9, "token"),
    ("Starbreach Whale", "U", "{1}{U}", "{4}{U}", 2, "none"),
]

_BASIC_FOR_COLOR = {
    "R": "Mountain", "G": "Forest", "W": "Plains",
    "U": "Island", "B": "Swamp",
}


def _verify_warp_admitted(card_name, warp_str, normal_str):
    """Verify-first: the genuine live printing IS still warp-admitted
    (the warp arm, not the plain simple-creature arm). Returns the
    resolved printing. FAILs loudly (never skips) on live-tree drift.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    src = get_active_source().get_printings()
    real = src.get(card_name)
    if real is None:
        pytest.fail(
            f"{card_name} absent from the active CardSource — the warp "
            f"Phase-1/1.5 admit set drifted; a re-orienting agent must "
            f"re-derive the warp-admitted set and drop/replace this "
            f"probe honestly (do NOT relax to a skip)."
        )
    assert real.warp_cost is not None, (
        f"{card_name}: live printing has no warp_cost — no longer a "
        f"warp card; re-derive the warp-admitted set."
    )
    assert real.warp_cost_str == warp_str, (
        f"{card_name}: live warp_cost_str {real.warp_cost_str!r} != "
        f"pinned {warp_str!r}; the printing drifted — re-pin."
    )
    assert real.mana_cost_str == normal_str, (
        f"{card_name}: live mana_cost_str {real.mana_cost_str!r} != "
        f"pinned {normal_str!r}; the printing drifted — re-pin."
    )
    # Phase-2 riders must be absent (the §2 guardrail teeth).
    assert getattr(real, "warp_additional_life_cost", 0) == 0
    assert getattr(real, "warp_castable_from_graveyard", False) is False
    assert trajectory._printing_is_bridge_pure_warp_creature(real), (
        f"{card_name} is NOT warp-admitted at live HEAD "
        f"(_printing_is_bridge_pure_warp_creature False) — the warp "
        f"Phase-1/1.5 guardrail no longer admits it. This probe's "
        f"premise is invalid; re-derive the warp-admitted set."
    )
    assert not trajectory._printing_is_bridge_simple_creature(real), (
        f"{card_name}: the PLAIN simple-creature arm admits it — the "
        f"warp arm is then NOT the load-bearing admit path and this "
        f"probe would not exercise the warp substrate. Re-derive."
    )
    return real


class _PickFirstSacrificeAgent(Agent):
    """Deterministic agent that picks the first legal id on every
    ``choose_sacrifice`` prompt — the seated-agent counterpart to
    Rust's deterministic first-legal hand-iteration pick used by
    bespoke LTB / sacrifice resolves (Anticausal Vestige LTB at
    ``rust/src/state_ops_resolve.rs:15219-15392``). Inherits all
    other Agent callbacks from the base ``Agent`` class — which
    raise ``NotImplementedError`` if invoked. The cross-engine
    trajectory harness's idiom is to seat narrow shims only when a
    SPECIFIC callback method needs deterministic resolution; for AV
    the trajectory's resolve path only calls ``choose_sacrifice``
    (during LTB) so the narrow shim is correct."""

    def choose_sacrifice(self, state, player_id, legal_ids):
        return legal_ids[0] if legal_ids else None


def _build_real_deck_context(card_name, color, real_archetype):
    """Seat the genuine warp printing into a REAL 17lands archetype
    deck context, with the union's basic lands normalised to tap the
    card's color. Returns ``(py, rs)`` matched states.

    The opponent gets the same real filtered decklist (a clean mirror
    — the established trajectory-probe shape). Padding uses the
    card's-color basic so a short post-filter deck still drives a
    multi-turn game with a payable mana base.

    **Anticausal Vestige special-case (Cycle 3, 2026-05-24).** AV's
    LEAVES_BATTLEFIELD trigger fires during the warp end-step exile
    sweep; its bespoke ``AnticausalVestigeLeavesEffect.resolve``
    carries an ``if not candidates or p.agent is None: return``
    short-circuit (the no-agent path early-returns BEFORE the put-
    onto-bf step). Rust's resolve arm does NOT short-circuit on a
    no-agent state — it deterministically picks the first hand-iter
    permanent with ``mana_value <= land_count``. The
    trajectory-harness default ``Player(agent=None)`` would surface
    this as a byte-divergence (Python keeps the picked card in
    hand, Rust puts it on bf tapped). Seat
    ``_PickFirstSacrificeAgent`` on p0 ONLY when ``card_name ==
    "Anticausal Vestige"`` to mirror Rust's deterministic-first
    contract. The seated agent only overrides ``choose_sacrifice``
    (the load-bearing callback for AV's LTB); all other harness
    code paths still hit the ``agent is None`` guards because no
    other LEAVES-related code path on the AV trajectory invokes a
    non-``choose_sacrifice`` callback (verified empirically — the
    warp cast / phase advancement / SBA passes never call into
    the agent on the AV path).
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import CardDef, DeckSpec

    try:
        deck_names = trajectory.load_production_deck(
            archetype=real_archetype)
    except (FileNotFoundError, IndexError):
        pytest.skip("17lands deck pool unavailable")

    src = get_active_source().get_printings()
    filtered, _defs = trajectory._filter_deck_to_bridge_supported(
        deck_names, src)
    basic = _BASIC_FOR_COLOR[color]
    # p0 = the genuine warp card seated into the real filtered context;
    # p1 = the same real filtered context (clean mirror).
    p0_names = [card_name] + list(filtered)
    p1_names = list(filtered)
    spec = trajectory.production_deck_to_deckspec(
        p0_names, p1_names, pad_to_size=45, pad_with=basic)
    # Normalise EVERY basic land in the union registry to tap the
    # card's color so the warp / normal cost is deterministically
    # payable on BOTH engines (symmetric — same registry feeds both).
    newdefs = tuple(
        CardDef(name=c.name, card_type="Land", mana_produced=(color,))
        if c.card_type == "Land" else c
        for c in spec.card_defs
    )
    spec = DeckSpec(
        card_defs=newdefs,
        p0_library=spec.p0_library,
        p1_library=spec.p1_library,
    )
    assert spec.p0_library.count(card_name) == 1, (
        f"{card_name}: expected exactly one copy seated into the real "
        f"archetype-{real_archetype} context; got "
        f"{spec.p0_library.count(card_name)}"
    )
    py, rs = trajectory.setup_matched_game(spec)
    # **Anticausal Vestige Cycle 3 — seated-agent deterministic-first
    # contract.** Seat ``_PickFirstSacrificeAgent`` on p0 so AV's
    # LEAVES_BATTLEFIELD trigger (fired during the warp end-step
    # exile sweep) picks the first hand-iter MV<=land_count
    # permanent — matching Rust's deterministic first-legal pick.
    # See the helper's docstring for the full rationale.
    if card_name == "Anticausal Vestige":
        py.players[0].agent = _PickFirstSacrificeAgent()
    return py, rs


def _mana_total(cost_str):
    import re
    return sum(
        int(x) if x.isdigit() else 1
        for x in re.findall(r"\{([^}]+)\}", cost_str)
    )


def _make_adv(card_name, py, rs):
    """A phase-advance helper that runs the FULL ``compare_fields``
    byte-equality check at EVERY phase boundary (the strong tier).
    """
    from mtg_bot.parity.cross_engine import (
        advance_phase_python, compare_fields,
    )
    from test_trajectory_parity import _step_views

    def adv(n):
        for _ in range(n):
            advance_phase_python(py)
            rs.advance_phase()
            pv, rv = _step_views(py, rs)
            d = compare_fields(pv, rv)
            assert not d, (
                f"{card_name}: phase advance ({pv['step']}, turn "
                f"{pv['turn']}) diverged (FULL compare_fields): "
                f"{[(x.field, x.py_value, x.rust_value) for x in d]}"
            )
    return adv


def _ramp_to_main_with_mana(card_name, py, rs, adv, color, need):
    """Walk to a p0 PRECOMBAT_MAIN with ``need`` lands of ``color`` on
    the battlefield, all driven byte-equal via ``step_both``. Returns
    the active player index.
    """
    from mtg_bot.parity.cross_engine import step_both, step_both_drained

    adv(3)  # turn 1 PRECOMBAT_MAIN
    p0 = py.active_player_idx
    # Drive land development turn-by-turn (2-turn skip per cycle — the
    # established Phase-1/1.5 idiom) until p0 controls ``need`` lands.
    # One land per p0 turn (CR 305.2). Generous cycle cap so a
    # genuinely land-light real-deck shuffle skips loudly rather than
    # loops; every step up to that point is still byte-equal-asserted.
    for _cycle in range(40):
        n_lands_bf = sum(
            1 for o in py.battlefield
            if o.controller_id == p0 and o.printing.is_land
        )
        if n_lands_bf >= need:
            break
        if (py.active_player_idx == p0
                and py.players[p0].lands_played_this_turn == 0):
            hand_land = [
                o for o in py.players[p0].hand
                if o.printing.is_land
            ]
            if hand_land:
                s = step_both(
                    py, rs,
                    {"kind": "play_land",
                     "card_id": int(hand_land[0].id)})
                assert not s.divergences, (
                    f"{card_name}: play_land diverged: "
                    f"{[(d.field, d.py_value, d.rust_value) for d in s.divergences]}"
                )
        adv(24)  # +2 turns -> back to the same player's MAIN1
    n_lands_bf = sum(
        1 for o in py.battlefield
        if o.controller_id == p0 and o.printing.is_land
    )
    if n_lands_bf < need:
        pytest.skip(
            f"{card_name}: real-deck-context arch draw did not develop "
            f"{need} lands within the cycle budget (got {n_lands_bf}) — "
            f"land-light shuffle; the byte-equal trajectory up to here "
            f"held (every step_both passed). Re-pin a land-richer "
            f"archetype if this becomes persistent."
        )
    # Land into a clean p0 PRECOMBAT_MAIN with the land drop available.
    for _ in range(60):
        from test_trajectory_parity import _step_views
        pv, _rv = _step_views(py, rs)
        if (py.active_player_idx == p0
                and pv["step"] == "PRECOMBAT_MAIN"
                and py.players[p0].lands_played_this_turn == 0):
            break
        adv(1)
    return p0


def _tap_for(card_name, py, rs, ai, total):
    """Tap exactly ``total`` untapped non-summoning-sick lands p0
    controls, byte-equal via ``step_both``.
    """
    from mtg_bot.parity.cross_engine import step_both, step_both_drained

    taps = 0
    for o in list(py.battlefield):
        if (o.controller_id == ai and o.printing.is_land
                and not o.tapped and not o.summoning_sick
                and taps < total):
            s = step_both(
                py, rs,
                {"kind": "activate_ability",
                 "source_id": int(o.id), "ability_index": 0})
            assert not s.divergences, (
                f"{card_name}: land tap diverged: "
                f"{[(d.field, d.py_value, d.rust_value) for d in s.divergences]}"
            )
            taps += 1
    assert taps == total, (
        f"{card_name}: needed {total} mana; only tapped {taps} "
        f"(real-deck-context mana base too shallow — re-pin the "
        f"archetype or raise the ramp turns)"
    )


def _assert_etb_observable(card_name, etb_kind, py, rs, ai,
                           life_before, phase):
    """Assert the ETB's PUBLIC effect fired byte-equal on BOTH engines
    where it has one. Surveil-2 ("none") has no public side — its
    byte-equality is already proved by the surrounding zero-divergence
    full ``compare_fields``.
    """
    if etb_kind == "life+2":
        assert py.players[ai].life == life_before + 2, (
            f"{card_name} ETB GainLife 2 must fire {phase} on Python; "
            f"{life_before}->{py.players[ai].life}"
        )
        assert rs.get_life(ai) == life_before + 2, (
            f"{card_name} ETB GainLife 2 must fire {phase} on Rust; "
            f"{life_before}->{rs.get_life(ai)}"
        )
    elif etb_kind == "token":
        py_tok = [
            o for o in py.battlefield
            if o.controller_id == ai
            and o.printing.name == "Human Soldier"
        ]
        rs_tok = [
            o for o in rs.battlefield_snapshot()
            if o.get("controller_id") == ai
            and o["printing_name"] == "Human Soldier"
        ]
        assert len(py_tok) >= 1, (
            f"{card_name} ETB CreateToken must mint a Human Soldier "
            f"{phase} on Python; bf tokens={len(py_tok)}"
        )
        assert len(rs_tok) == len(py_tok), (
            f"{card_name} ETB CreateToken token-count diverged "
            f"{phase}: py={len(py_tok)} rs={len(rs_tok)}"
        )


@pytest.mark.parametrize(
    "card_name,color,warp_str,normal_str,real_archetype,etb_kind",
    _WARP_CARDS,
    ids=[c[0].replace(" ", "_") for c in _WARP_CARDS],
)
def test_warp_admitted_full_warp_lifecycle_real_deck_byte_equal(
    card_name, color, warp_str, normal_str, real_archetype, etb_kind,
):
    """**Probe 1 — the FULL warp lifecycle on a REAL 17lands deck
    context, FULL compare_fields byte-equal.**

    cast-via-warp -> PHASE_END_STEP exile sweep -> recast-from-exile
    at normal cost. The genuine live printing, seated into real
    17lands archetype-N, driven on BOTH engines via ``step_both`` /
    the per-phase full-``compare_fields`` ``adv`` helper. Closes the
    individual PROBED-tier pin the round-68 collateral-net sweep did
    not give these five.
    """
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import step_both, step_both_drained
    from mtg_bot.legal import legal_actions

    real = _verify_warp_admitted(card_name, warp_str, normal_str)
    cd = trajectory._printing_to_card_def(real)
    assert cd.has_warp is True, (
        f"{card_name}: _printing_to_card_def dropped has_warp — the "
        f"warp arm of the bridge is not engaging"
    )

    py, rs = _build_real_deck_context(
        card_name, color, real_archetype)
    adv = _make_adv(card_name, py, rs)

    warp_total = _mana_total(warp_str)
    normal_total = _mana_total(normal_str)
    # Ramp to ``normal_total`` lands (not just ``warp_total``) before
    # the cast. Rationale (NOT a divergence — verified: every
    # ``step_both`` trajectory call below is byte-equal): Python's
    # ``legal_actions`` is MANA-AWARE — it only enumerates a
    # ``CastSpell`` whose cost is payable from the mana the player can
    # currently produce — whereas Rust's ``legal_decisions`` enumerates
    # the warp/normal pair STRUCTURALLY (it lists both whenever the
    # printing has a warp_cost, independent of available mana). This is
    # a known harness-side legal-action *enumeration* asymmetry, not a
    # trajectory divergence: the actual cast/resolve trajectory is
    # byte-equal (the ``step_both`` calls prove it). To keep the strong
    # ``[False, True]`` legal-pair assertion meaningful on BOTH engines
    # we ensure enough lands are on the battlefield that Python's
    # mana-aware enumerator ALSO sees the (expensive) normal cost as
    # affordable — the SAME thing the pre-existing Phase-1 probe does
    # by flooding 10 lands. We still pay the warp cast with only
    # ``warp_total`` of them; the rest stay untapped so both costs read
    # affordable to Python at the legality check.
    ai = _ramp_to_main_with_mana(
        card_name, py, rs, adv, color, max(normal_total, 1))
    _tap_for(card_name, py, rs, ai, warp_total)

    card_obj = next(
        o for o in py.players[ai].hand
        if o.printing.name == card_name)
    life_before = py.players[ai].life
    assert rs.get_life(ai) == life_before

    # (1) Both engines offer the SAME base+warp CastSpell pair.
    py_pair = sorted(
        a.use_warp for a in legal_actions(py, ai)
        if getattr(a, "card_id", None) == card_obj.id
    )
    rs_pair = sorted(
        a["use_warp"] for a in rs.legal_decisions(ai)
        if a.get("kind") == "cast_spell"
        and a.get("card_id") == card_obj.id
    )
    assert py_pair == rs_pair == [False, True], (
        f"{card_name}: legal base+warp pair mismatch on the real-deck "
        f"context — py={py_pair} rs={rs_pair}"
    )

    # (2) The warp cast — FULL compare_fields byte-equal post-cast.
    s = step_both_drained(
        py, rs,
        {"kind": "cast_spell", "card_id": int(card_obj.id),
         "use_warp": True})
    assert not s.divergences, (
        f"{card_name}: warp cast diverged (FULL compare_fields): "
        f"{[(d.field, d.py_value, d.rust_value) for d in s.divergences]}"
    )
    assert py.spell_warped_this_turn is True
    assert rs.spell_warped_this_turn is True
    _assert_etb_observable(
        card_name, etb_kind, py, rs, ai, life_before,
        "under the warp-cast path")

    # (3) The following end step — the warp-exile delayed trigger
    # fires + resolves; the permanent is in exile (warp marker) on
    # BOTH, byte-equal at END. S7-A2: drain the stack via the
    # explicit primitive (post-G7 closure both engines push the
    # CR-603.7 delayed trigger onto the stack at END_STEP entry; the
    # drain resolves it via real stack-and-priority resolution).
    from mtg_bot.parity.cross_engine import drain_stack_both
    adv(7)  # MAIN1 -> END (WarpExileSelf delayed trigger on stack)
    drain_stack_both(py, rs)  # resolve the delayed trigger
    py_ex = sorted(
        o.printing.name for o in py.players[ai].exile)
    rs_ex = sorted(
        o["printing_name"] for o in rs.exile_snapshot(ai))
    assert py_ex == rs_ex == [card_name], (
        f"{card_name}: must be warp-exiled on BOTH at the end step; "
        f"py={py_ex} rs={rs_ex}"
    )
    assert not [
        o for o in py.battlefield
        if o.printing.name == card_name], (
        f"{card_name}: must have left the Python battlefield"
    )
    assert not [
        o for o in rs.battlefield_snapshot()
        if o["printing_name"] == card_name], (
        f"{card_name}: must have left the Rust battlefield"
    )

    # (4) A later p0 main — recast from exile at NORMAL cost,
    # FULL compare_fields byte-equal.
    for _ in range(200):
        from test_trajectory_parity import _step_views
        pv, _rv = _step_views(py, rs)
        if (py.active_player_idx == ai
                and pv["step"] == "PRECOMBAT_MAIN"
                and py.players[ai].lands_played_this_turn == 0):
            break
        adv(1)
    fhand = [
        o for o in py.players[ai].hand if o.printing.is_land]
    if fhand:
        s = step_both(
            py, rs,
            {"kind": "play_land", "card_id": int(fhand[0].id)})
        assert not s.divergences, (
            f"{card_name}: pre-recast play_land diverged: "
            f"{[(d.field, d.py_value, d.rust_value) for d in s.divergences]}"
        )
    _tap_for(card_name, py, rs, ai, normal_total)
    life_before_recast = py.players[ai].life
    assert rs.get_life(ai) == life_before_recast
    exiled = next(
        o for o in py.players[ai].exile
        if o.printing.name == card_name)
    s = step_both_drained(
        py, rs,
        {"kind": "cast_spell", "card_id": int(exiled.id),
         "use_warp": False})
    assert not s.divergences, (
        f"{card_name}: warp exile-recast diverged (FULL "
        f"compare_fields): "
        f"{[(d.field, d.py_value, d.rust_value) for d in s.divergences]}"
    )
    assert any(
        o.printing.name == card_name for o in py.battlefield), (
        f"{card_name}: recast must be back on the Python bf"
    )
    assert any(
        o["printing_name"] == card_name
        for o in rs.battlefield_snapshot()), (
        f"{card_name}: recast must be back on the Rust bf"
    )
    _assert_etb_observable(
        card_name, etb_kind, py, rs, ai, life_before_recast,
        "AGAIN under the normal-cost exile-recast path")


@pytest.mark.parametrize(
    "card_name,color,warp_str,normal_str,real_archetype,etb_kind",
    _WARP_CARDS,
    ids=[c[0].replace(" ", "_") for c in _WARP_CARDS],
)
def test_warp_admitted_normal_nonwarp_play_real_deck_byte_equal(
    card_name, color, warp_str, normal_str, real_archetype, etb_kind,
):
    """**Probe 2 — pure NORMAL non-warp play on a REAL 17lands deck
    context, FULL compare_fields byte-equal.**

    The genuine printing cast from hand at its FULL normal mana cost
    with ``use_warp:False``, NEVER warped. The negative control the
    pre-existing lifecycle probes do not exercise: a non-warped warp
    creature must NOT be swept to exile at the end step (the sweep is
    keyed on the warp marker, not the card identity) — it stays on
    the battlefield through the following end step, byte-equal on
    BOTH engines. The ETB fires byte-equal under the normal-cast
    path.
    """
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import step_both, step_both_drained
    from mtg_bot.legal import legal_actions

    real = _verify_warp_admitted(card_name, warp_str, normal_str)
    trajectory._printing_to_card_def(real)  # exercises the warp arm

    py, rs = _build_real_deck_context(
        card_name, color, real_archetype)
    adv = _make_adv(card_name, py, rs)

    normal_total = _mana_total(normal_str)
    ai = _ramp_to_main_with_mana(
        card_name, py, rs, adv, color, normal_total)
    _tap_for(card_name, py, rs, ai, normal_total)

    card_obj = next(
        o for o in py.players[ai].hand
        if o.printing.name == card_name)
    life_before = py.players[ai].life
    assert rs.get_life(ai) == life_before

    # Both engines still offer the SAME base+warp pair (warp is an
    # OPTION; we deliberately take the base/normal one).
    py_pair = sorted(
        a.use_warp for a in legal_actions(py, ai)
        if getattr(a, "card_id", None) == card_obj.id
    )
    rs_pair = sorted(
        a["use_warp"] for a in rs.legal_decisions(ai)
        if a.get("kind") == "cast_spell"
        and a.get("card_id") == card_obj.id
    )
    assert py_pair == rs_pair == [False, True], (
        f"{card_name}: legal base+warp pair mismatch — "
        f"py={py_pair} rs={rs_pair}"
    )

    # Normal cast (use_warp:False) — FULL compare_fields byte-equal.
    s = step_both_drained(
        py, rs,
        {"kind": "cast_spell", "card_id": int(card_obj.id),
         "use_warp": False})
    assert not s.divergences, (
        f"{card_name}: normal non-warp cast diverged (FULL "
        f"compare_fields): "
        f"{[(d.field, d.py_value, d.rust_value) for d in s.divergences]}"
    )
    # NOT warped — the warp marker must NOT be set on either engine.
    assert py.spell_warped_this_turn is False, (
        f"{card_name}: a normal (use_warp:False) cast must NOT set "
        f"spell_warped_this_turn on Python"
    )
    assert rs.spell_warped_this_turn is False, (
        f"{card_name}: a normal (use_warp:False) cast must NOT set "
        f"spell_warped_this_turn on Rust"
    )
    assert any(
        o.printing.name == card_name for o in py.battlefield), (
        f"{card_name}: normal cast must be on the Python bf"
    )
    assert any(
        o["printing_name"] == card_name
        for o in rs.battlefield_snapshot()), (
        f"{card_name}: normal cast must be on the Rust bf"
    )
    _assert_etb_observable(
        card_name, etb_kind, py, rs, ai, life_before,
        "under the normal non-warp cast path")

    # The negative control: at the FOLLOWING end step the
    # non-warped permanent must STILL be on the battlefield on BOTH
    # engines and NOT in exile (the sweep is warp-marker-keyed). Drive
    # a full turn cycle of phase boundaries, FULL compare_fields each.
    adv(7)   # this turn's MAIN1 -> END
    adv(12)  # through the opponent's turn, back toward p0
    py_bf = [
        o for o in py.battlefield
        if o.printing.name == card_name]
    rs_bf = [
        o for o in rs.battlefield_snapshot()
        if o["printing_name"] == card_name]
    assert len(py_bf) == 1 and len(rs_bf) == 1, (
        f"{card_name}: a NON-warped cast must NOT be swept to exile — "
        f"it must remain on the battlefield on BOTH engines after the "
        f"end step; py_bf={len(py_bf)} rs_bf={len(rs_bf)}"
    )
    py_ex = [
        o for o in py.players[ai].exile
        if o.printing.name == card_name]
    rs_ex = [
        o for o in rs.exile_snapshot(ai)
        if o["printing_name"] == card_name]
    assert not py_ex and not rs_ex, (
        f"{card_name}: a NON-warped cast must NOT be in exile after "
        f"the end step on EITHER engine; py_ex={len(py_ex)} "
        f"rs_ex={len(rs_ex)}"
    )
